"""Sidecar supervisor: spawn + framed JSON-RPC + watchdog + orphan-free restart.

The supervisor owns the private bridge to the packaged Node sidecar
(``node agent/dist/main.js``). It is the *client* for the frozen ``session.*``/
``history.*``/``query.*`` request methods and the *server* for the ``py.*``
requests the sidecar originates; ``event``/``terminal`` notifications from the
sidecar are handed to an injected sink (the :mod:`events` pump).

Design points (architecture §5, digest §6):

* **Minimal environment.** :func:`build_minimal_env` forwards only
  ``PATH``/``HOME``/``LANG``/``TMPDIR`` plus credential variables named in an
  explicit allowlist. Ambient provider keys (``ANTHROPIC_API_KEY`` …) are never
  forwarded unless allowlisted (mission rule 7).
* **Framing.** Uses :mod:`framing` (LF-delimited, incremental 64 MiB cap) and
  :mod:`protocol` (``hv`` negotiation, frozen method sets, error codes). A
  ``FrameTooLargeError`` on the sidecar's stdout fails the bridge closed.
* **Correlation + timeouts.** Each outbound request gets a monotonic id and a
  per-call deadline; the default is the ``tool_seconds`` bridge limit and the
  ``cad_build`` class the ``cad_build_seconds`` limit.
* **Watchdog.** A background thread kills the *whole* sidecar once a pending
  call passes its deadline by ``watchdog_grace_s`` (unresponsive process), then
  hands the set of tracked run ids to the injected recovery hook **before** any
  terminal synthesis, and restarts.
* **Bounded automatic respawn.** An *unexpected* child exit (a crash, or a
  bridge torn down by an oversized frame) no longer leaves the supervisor
  permanently childless waiting for a watchdog that only fires while a call is
  pending. The order is fixed and observable: the in-flight calls still fail
  with the structured ``PROCESS_DOWN`` error, the recovery hook still runs
  **before** anything is respawned (architecture §5 hands recoverable runs to
  their coordinators before terminal synthesis), and only then is a replacement
  spawned — through the same :meth:`~Supervisor.start` path, so the spawn hook
  replays ``runtime.configure`` on it. The respawn is bounded by
  ``respawn_max_attempts`` with exponential backoff
  (``respawn_backoff_s`` doubling per attempt, capped at
  ``respawn_backoff_max_s``);
  a child that survives ``respawn_cooldown_s`` is deemed healthy and resets the
  attempt counter, so a crash *loop* exhausts the budget and leaves the
  supervisor **durably dead** with an error naming the attempt count, instead of
  thrashing forever. A deliberate :meth:`~Supervisor.close` — or a
  :meth:`~Supervisor.restart`, which does its own respawn — never triggers it.
* **Re-configuration on every spawn.** A fresh child is a blank runtime: it has
  never seen ``runtime.configure``. :meth:`Supervisor.set_spawn_hook` registers a
  post-spawn callback that :class:`~.app.BridgeRuntime` uses to replay exactly
  the payload it sent at start-up, and it fires for *every* path that produces a
  child — initial :meth:`~Supervisor.start`, explicit :meth:`~Supervisor.restart`
  and the watchdog's own respawn. Without it a watchdog restart silently drops
  the provider configuration and every later ``session.create``/``session.prompt``
  fails with ``runtime.configure has not run yet``.
* **Orphan-free.** On Linux the child gets ``PR_SET_PDEATHSIG=SIGKILL`` so it
  dies with the supervisor; an ``atexit`` hook and ``close()`` also kill it. No
  sidecar survives the supervisor.
"""

from __future__ import annotations

import atexit
import contextlib
import ctypes
import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from io import BufferedReader
from typing import Any, cast

from .framing import FrameDecoder, FrameTooLargeError, encode_frame
from .limits import LIMITS
from .protocol import (
    ErrorCode,
    ProtocolError,
    make_error,
    make_notification,
    make_request,
    make_response,
    validate_frame,
)

__all__ = [
    "BASE_ENV_VARS",
    "STDERR_TAIL_LINES",
    "STDERR_TAIL_LINE_CHARS",
    "ProcessLossEvent",
    "PyRequestHandler",
    "SpawnHook",
    "Supervisor",
    "SupervisorConfig",
    "SupervisorError",
    "build_minimal_env",
]

#: The non-credential environment variables the sidecar is always given.
BASE_ENV_VARS: tuple[str, ...] = ("PATH", "HOME", "LANG", "TMPDIR")

_TOOL_SECONDS: float = float(LIMITS["timeouts"]["tool_seconds"])
_CAD_BUILD_SECONDS: float = float(LIMITS["timeouts"]["cad_build_seconds"])

# Linux prctl option to receive a signal when the parent thread dies.
_PR_SET_PDEATHSIG = 1

#: Bound on the retained sidecar stderr: the newest lines only, each truncated.
#: A tail, not the firehose — the evidence a crash diagnosis needs is the last
#: page of logs, and an unbounded buffer over a chatty child is a memory leak.
STDERR_TAIL_LINES: int = 200
STDERR_TAIL_LINE_CHARS: int = 500

#: Sync handler for a ``py.*`` request: ``(method, params) -> result``.
#: Raising :class:`ProtocolError` maps to its code; any other exception maps to
#: ``INTERNAL_ERROR``.
PyRequestHandler = Callable[[str, dict[str, Any]], Any]

#: Sink for a sidecar-originated notification (``event``/``terminal``):
#: ``(method, params) -> None``.
NotificationSink = Callable[[str, dict[str, Any]], None]

#: Called with the supervisor immediately after *every* successful spawn, before
#: any other caller can use the fresh child. This is where per-process state that
#: does not survive a respawn (``runtime.configure``) is replayed.
SpawnHook = Callable[["Supervisor"], None]


class SupervisorError(Exception):
    """A supervisor-layer failure (spawn, or a call against a dead sidecar)."""


def build_minimal_env(
    allowlist: frozenset[str] | set[str] | tuple[str, ...] = (),
    *,
    source: dict[str, str] | None = None,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """Construct the sidecar's minimal environment.

    Includes each present :data:`BASE_ENV_VARS` variable plus each *allowlisted*
    credential variable that exists in ``source`` (default ``os.environ``).
    Nothing else — an ambient provider key not in ``allowlist`` is dropped.

    ``extra`` carries **app-owned, non-secret** settings the supervisor itself
    computes (currently only ``HEPHAESTUS_AGENT_DIR``); it is applied last and
    never read from the ambient environment, so it cannot smuggle a credential.
    """
    src = os.environ if source is None else source
    env: dict[str, str] = {}
    for name in BASE_ENV_VARS:
        value = src.get(name)
        if value is not None:
            env[name] = value
    for name in allowlist:
        value = src.get(name)
        if value is not None:
            env[name] = value
    env.update(extra or {})
    return env


def _pdeathsig_preexec() -> None:  # pragma: no cover - exercised in a subprocess
    """Ask the kernel to SIGKILL this child when the parent dies (Linux only)."""
    if sys.platform != "linux":
        return
    try:
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        libc.prctl(_PR_SET_PDEATHSIG, signal.SIGKILL)
    except OSError:
        pass


@dataclass(frozen=True)
class SupervisorConfig:
    """Static configuration for one supervised sidecar."""

    argv: list[str]
    credential_allowlist: frozenset[str] = frozenset()
    default_timeout_s: float = _TOOL_SECONDS
    cad_build_timeout_s: float = _CAD_BUILD_SECONDS
    watchdog_interval_s: float = 0.1
    watchdog_grace_s: float = 5.0
    #: How many times an *unexpected* child exit may be respawned automatically
    #: before the supervisor gives up and stays dead. Three is chosen so the
    #: worst case (0.5 + 1.0 + 2.0 s of backoff) still fits comfortably inside
    #: one `tool_seconds` call deadline: a genuine one-off crash is invisible to
    #: the caller, while a sidecar that cannot stay up fails loudly in <4 s.
    respawn_max_attempts: int = 3
    #: First backoff, doubled per consecutive attempt.
    respawn_backoff_s: float = 0.5
    #: Ceiling for the doubling (irrelevant at 3 attempts; a bound on any
    #: future widening of `respawn_max_attempts`).
    respawn_backoff_max_s: float = 5.0
    #: A child that stayed up this long counts as healthy: the next unexpected
    #: exit starts a fresh attempt budget. Long enough that a crash *loop*
    #: (sub-second children) can never reset it, short enough that two unrelated
    #: crashes minutes apart are not charged to the same budget.
    respawn_cooldown_s: float = 30.0
    env_source: dict[str, str] | None = None
    #: App-owned non-secret settings injected verbatim (e.g. HEPHAESTUS_AGENT_DIR).
    extra_env: dict[str, str] | None = None
    #: Working directory for the sidecar process (default: the supervisor's).
    cwd: str | None = None


@dataclass
class ProcessLossEvent:
    """Handed to the recovery hook when the sidecar is lost, before synthesis."""

    reason: str  # "watchdog" | "crash"
    returncode: int | None
    tracked_run_ids: frozenset[str]
    restart_generation: int


@dataclass
class _Call:
    """One in-flight outbound request."""

    id: int
    method: str
    deadline: float
    done: threading.Event = field(default_factory=threading.Event)
    result: Any | None = None
    error: dict[str, Any] | None = None

    def complete_ok(self, result: Any) -> None:
        if not self.done.is_set():
            self.result = result
            self.done.set()

    def complete_err(self, error: dict[str, Any]) -> None:
        if not self.done.is_set():
            self.error = error
            self.done.set()


class Supervisor:
    """Supervises one sidecar process over the private framed JSON-RPC bridge."""

    def __init__(
        self,
        config: SupervisorConfig,
        *,
        py_handler: PyRequestHandler | None = None,
        notification_sink: NotificationSink | None = None,
        recovery_hook: Callable[[ProcessLossEvent], None] | None = None,
        spawn_hook: SpawnHook | None = None,
    ) -> None:
        self.config = config
        self._py_handler = py_handler
        self._sink = notification_sink
        self._recovery_hook = recovery_hook
        self._spawn_hook = spawn_hook

        self.proc: subprocess.Popen[bytes] | None = None
        self._next_id = 0
        self._pending: dict[int, _Call] = {}
        self._tracked_runs: set[str] = set()
        self._plock = threading.RLock()
        self._wlock = threading.Lock()
        self._reader: threading.Thread | None = None
        self._watchdog: threading.Thread | None = None
        self._closing = threading.Event()
        self._restart_generation = 0
        self.last_exit: int | None = None
        self.frame_errors: list[str] = []
        # -- bounded automatic respawn state --------------------------------
        #: Set once a child is up (and configured); cleared while an automatic
        #: respawn is under way, so `call` can wait for the replacement instead
        #: of failing with "sidecar is not running" during the backoff.
        self._child_ready = threading.Event()
        #: Raised by a dead child's reader thread, serviced by the watchdog
        #: thread (the only long-lived thread that may fork: see `_on_child_exit`).
        self._respawn_request = threading.Event()
        #: Serializes respawn chains; also the "a respawn is in progress" flag.
        self._respawn_lock = threading.Lock()
        self._respawning = False
        self._respawn_attempts = 0
        self._spawned_at = 0.0
        self._respawn_last_error: str | None = None
        #: Terminal state: automatic respawn exhausted its attempts. Every later
        #: `call` fails with this message until an explicit `restart()`.
        self._respawn_failure: str | None = None
        #: PIDs of children *we* killed on purpose; their exit is never a crash.
        self._deliberate_exits: set[int] = set()
        #: Automatic respawns, by outcome (regression evidence).
        self.auto_respawns = 0
        #: Post-spawn hook failures, newest last (a watchdog respawn cannot raise
        #: at a caller, so the failure is recorded here instead of vanishing).
        self.spawn_errors: list[str] = []
        #: Successful spawns, including the initial one (regression evidence).
        self.spawn_count = 0
        #: Every child loss/replacement with its reason, newest last — one row
        #: per explicit ``restart()`` (manual/watchdog) and per unexpected exit.
        #: ``EXTERNAL_EVAL.md`` §5: restarts must be archived evidence, not
        #: something inferred from event-stream shape after the fact.
        self.restart_events: list[dict[str, Any]] = []
        #: Rolling bounded tail of the child's stderr, across every child this
        #: supervisor spawned (a crash's last words arrive just before the
        #: replacement's first). Read it for the archive; never unbounded.
        self.stderr_tail: deque[str] = deque(maxlen=STDERR_TAIL_LINES)

        self._atexit = self._kill_now
        atexit.register(self._atexit)

    # -- lifecycle ---------------------------------------------------------

    def set_spawn_hook(self, hook: SpawnHook | None) -> None:
        """Register the post-spawn callback (see :data:`SpawnHook`).

        Set before :meth:`start`; it then fires for every child this supervisor
        ever creates, so per-process runtime state is never silently lost to a
        respawn the app did not ask for.
        """
        self._spawn_hook = hook

    def start(self) -> None:
        """Spawn the sidecar, start the reader + watchdog, run the spawn hook."""
        with self._plock:
            if self.proc is not None and self.proc.poll() is None:
                raise SupervisorError("sidecar already running")
            env = build_minimal_env(
                self.config.credential_allowlist,
                source=self.config.env_source,
                extra=self.config.extra_env,
            )
            try:
                self.proc = subprocess.Popen(
                    self.config.argv,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=env,
                    cwd=self.config.cwd,
                    preexec_fn=_pdeathsig_preexec if sys.platform == "linux" else None,
                )
            except OSError as exc:
                raise SupervisorError(f"failed to spawn sidecar: {exc}") from exc
            proc = self.proc
            self._reader = threading.Thread(target=self._read_loop, args=(proc,), daemon=True)
            self._reader.start()
            threading.Thread(target=self._drain_stderr, args=(proc,), daemon=True).start()
            if self._watchdog is None or not self._watchdog.is_alive():
                self._watchdog = threading.Thread(target=self._watchdog_loop, daemon=True)
                self._watchdog.start()
            self.spawn_count += 1
            self._spawned_at = time.monotonic()
        # Outside the process lock on purpose: the hook issues real requests, and
        # a blocking call under `_plock` would deadlock against the reader thread.
        self._fire_spawn_hook()
        # Only now is the child usable: the hook has replayed `runtime.configure`.
        self._child_ready.set()

    def _fire_spawn_hook(self) -> None:
        """Replay per-process state onto the fresh child; record any failure."""
        hook = self._spawn_hook
        if hook is None:
            return
        try:
            hook(self)
        except Exception as exc:
            self.spawn_errors.append(f"{type(exc).__name__}: {exc}")
            raise

    def restart(self, *, reason: str = "manual") -> None:
        """Kill the whole sidecar, fire recovery, and respawn.

        The recovery hook is invoked with the tracked run ids **before** any
        pending call is failed (so coordinators own recoverable runs before a
        terminal is synthesized for them).
        """
        with self._plock:
            proc = self.proc
            tracked = frozenset(self._tracked_runs)
            self._restart_generation += 1
            generation = self._restart_generation
            # An explicit restart is operator intent: it clears any durable
            # automatic-respawn failure and hands back a full attempt budget.
            self._respawn_failure = None
            self._respawn_attempts = 0
            self._child_ready.clear()
            if proc is not None:
                self._deliberate_exits.add(proc.pid)
        returncode: int | None = None
        if proc is not None:
            if proc.poll() is None:
                proc.kill()
            returncode = proc.wait()
        self.last_exit = returncode
        self._record_restart(reason=reason, returncode=returncode, generation=generation)
        self._fire_recovery(
            ProcessLossEvent(
                reason=reason,
                returncode=returncode,
                tracked_run_ids=tracked,
                restart_generation=generation,
            )
        )
        self._fail_all_pending(
            make_error(None, ErrorCode.PROCESS_DOWN, "sidecar restarted")["error"]
        )
        if self._reader is not None:
            self._reader.join(timeout=5)
        if not self._closing.is_set():
            self.start()

    def close(self, *, timeout: float = 5.0) -> int | None:
        """Graceful shutdown: close stdin, escalate, reap, leave no orphan."""
        self._closing.set()
        proc = self.proc
        if proc is None:
            self._safe_unregister_atexit()
            return None
        try:
            if proc.stdin is not None:
                proc.stdin.close()
        except OSError:
            pass
        try:
            rc = proc.wait(timeout)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                rc = proc.wait(2)
            except subprocess.TimeoutExpired:
                proc.kill()
                rc = proc.wait()
        self.last_exit = rc
        self._fail_all_pending(
            make_error(None, ErrorCode.PROCESS_DOWN, "sidecar shut down")["error"]
        )
        if self._reader is not None:
            self._reader.join(timeout=5)
        self._safe_unregister_atexit()
        return rc

    def _kill_now(self) -> None:  # pragma: no cover - atexit path
        proc = self.proc
        if proc is not None and proc.poll() is None:
            with contextlib.suppress(OSError):
                proc.kill()

    def _record_restart(self, *, reason: str, returncode: int | None, generation: int) -> None:
        """One archived-evidence row per lost/replaced child, with its reason."""
        self.restart_events.append(
            {
                "reason": reason,
                "returncode": returncode,
                "restart_generation": generation,
                "at": datetime.now(UTC).isoformat(),
            }
        )

    def _safe_unregister_atexit(self) -> None:
        # unregister must never raise, whatever atexit's internal state.
        with contextlib.suppress(Exception):
            atexit.unregister(self._atexit)

    def __enter__(self) -> Supervisor:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- run tracking (for recovery handoff) -------------------------------

    def track_run(self, run_id: str) -> None:
        """Register a run id so a process-loss recovery hook receives it."""
        with self._plock:
            self._tracked_runs.add(run_id)

    def untrack_run(self, run_id: str) -> None:
        """Drop a run id once its terminal is durably recorded/acked."""
        with self._plock:
            self._tracked_runs.discard(run_id)

    @property
    def child_pid(self) -> int:
        if self.proc is None:
            raise SupervisorError("no sidecar process")
        return self.proc.pid

    def is_running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    @property
    def respawn_failure(self) -> str | None:
        """The durable-death reason once automatic respawn exhausted its budget."""
        with self._plock:
            return self._respawn_failure

    def wait_for_child(self, timeout: float) -> bool:
        """Block until a child is up and configured (or the respawn gave up)."""
        self._child_ready.wait(timeout)
        return self.is_running()

    # -- outbound requests -------------------------------------------------

    def call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> Any:
        """Send a request and block for the response; structured on failure.

        Returns the ``result`` on success; raises :class:`SupervisorError`
        carrying the JSON-RPC error envelope on timeout / error / process loss.
        """
        deadline_s = timeout if timeout is not None else self.config.default_timeout_s
        self._await_child()
        with self._plock:
            proc = self.proc
            if proc is None or proc.poll() is not None:
                raise SupervisorError(self._respawn_failure or "sidecar is not running")
            self._next_id += 1
            call = _Call(
                id=self._next_id,
                method=method,
                deadline=time.monotonic() + deadline_s,
            )
            self._pending[call.id] = call
        frame = make_request(call.id, method, params or {})
        try:
            self._write_frame(frame)
        except (FrameTooLargeError, BrokenPipeError, OSError) as exc:
            with self._plock:
                self._pending.pop(call.id, None)
            raise SupervisorError(f"failed to send {method}: {exc}") from exc
        # The watchdog is what normally ends an unanswered call (it kills the
        # child at deadline+grace and fails every pending call). The bound here
        # is only a backstop for the one case the watchdog cannot cover: a call
        # issued *from* the watchdog thread, i.e. the spawn hook's replayed
        # `runtime.configure`. Without it a child that accepts the frame and
        # never answers would wedge the watchdog forever.
        if not call.done.wait(self._hard_wait_s(deadline_s)):
            with self._plock:
                self._pending.pop(call.id, None)
            raise SupervisorError(f"{method} timed out after {deadline_s}s with no response")
        if call.error is not None:
            raise SupervisorError(f"{method} failed: {call.error}")
        return call.result

    def _await_child(self) -> None:
        """Block briefly if an automatic respawn is under way; fail if it gave up.

        A crash that is being recovered from is a *transient* absence of a child,
        so a caller that arrives during the backoff waits for the replacement
        rather than seeing ``sidecar is not running``. Once the attempt budget is
        exhausted the absence is permanent and every caller is told so, naming
        the attempt count.
        """
        with self._plock:
            failure = self._respawn_failure
            respawning = self._respawning
        if failure is not None:
            raise SupervisorError(failure)
        if self._closing.is_set() or not respawning or self.is_running():
            return
        self._child_ready.wait(self._respawn_window_s())
        with self._plock:
            failure = self._respawn_failure
        if failure is not None:
            raise SupervisorError(failure)

    def _respawn_window_s(self) -> float:
        """Worst-case wall time a full respawn chain can occupy, plus margin."""
        total = 0.0
        for attempt in range(self.config.respawn_max_attempts):
            total += self._backoff_s(attempt + 1)
        return total + 5.0

    def _backoff_s(self, attempt: int) -> float:
        return min(
            self.config.respawn_backoff_s * (2.0 ** (attempt - 1)),
            self.config.respawn_backoff_max_s,
        )

    def _hard_wait_s(self, deadline_s: float) -> float:
        """The backstop wait: strictly later than the watchdog's own kill point."""
        return deadline_s + self.config.watchdog_grace_s + self.config.watchdog_interval_s + 5.0

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        """Fire-and-forget notification to the sidecar (``cancel``, acks, …)."""
        if not self.is_running():
            return
        with contextlib.suppress(FrameTooLargeError, BrokenPipeError, OSError):
            self._write_frame(make_notification(method, params or {}))

    def _write_frame(self, frame: dict[str, Any]) -> None:
        payload = encode_frame(frame)
        with self._wlock:
            proc = self.proc
            if proc is None or proc.stdin is None:
                raise BrokenPipeError("sidecar stdin unavailable")
            proc.stdin.write(payload)
            proc.stdin.flush()

    # -- reader ------------------------------------------------------------

    def _read_loop(self, proc: subprocess.Popen[bytes]) -> None:
        assert proc.stdout is not None
        stdout = cast("BufferedReader", proc.stdout)
        decoder = FrameDecoder()
        try:
            while True:
                chunk = stdout.read1(65536)
                if not chunk:
                    break
                for raw in decoder.push(chunk):
                    self._on_frame(raw)
        except FrameTooLargeError as exc:
            # Fail closed: an oversized inbound frame tears the bridge down.
            self.frame_errors.append(exc.message)
            self._on_child_exit(proc, crash=True)
            return
        self._on_child_exit(proc, crash=not self._closing.is_set())

    def _drain_stderr(self, proc: subprocess.Popen[bytes]) -> None:
        assert proc.stderr is not None
        # The logs are still the sidecar's — nothing here is parsed or acted on.
        # A bounded tail is retained purely as archive evidence (EXTERNAL_EVAL.md
        # §5): the 2026-07-29 sweep's crashes left no stderr anywhere.
        for line in proc.stderr:
            text = line.decode("utf-8", errors="replace").rstrip("\n")
            self.stderr_tail.append(text[:STDERR_TAIL_LINE_CHARS])

    def _on_frame(self, raw: bytes) -> None:
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            self.frame_errors.append("parse_error")
            return
        try:
            frame = validate_frame(obj)
        except ProtocolError as exc:
            self.frame_errors.append(exc.message)
            return
        msg_id = frame.get("id")
        method = frame.get("method")
        if method is not None and msg_id is None:
            self._dispatch_notification(str(method), frame.get("params") or {})
            return
        if method is not None:
            self._dispatch_py_request(msg_id, str(method), frame.get("params") or {})
            return
        # A response to one of our outbound requests.
        if msg_id is None:
            return
        with self._plock:
            call = self._pending.pop(msg_id, None)
        if call is None:
            return  # late response after timeout/restart
        if "error" in frame:
            call.complete_err(frame["error"])
        else:
            call.complete_ok(frame.get("result"))

    def _dispatch_notification(self, method: str, params: dict[str, Any]) -> None:
        if self._sink is not None:
            self._sink(method, params)

    def _dispatch_py_request(self, msg_id: Any, method: str, params: dict[str, Any]) -> None:
        if self._py_handler is None:
            self._write_frame(
                make_error(msg_id, ErrorCode.METHOD_NOT_FOUND, f"no handler: {method}")
            )
            return
        try:
            result = self._py_handler(method, params)
        except ProtocolError as exc:
            # Structured refusals (DispatchError and friends) carry a stable
            # machine `reason` in `.data`; forward it so the model sees the
            # discriminated code, not only prose.
            data = getattr(exc, "data", None)
            self._safe_send(make_error(msg_id, exc.code, exc.message, data))
            return
        except Exception as exc:
            self._safe_send(
                make_error(msg_id, ErrorCode.INTERNAL_ERROR, f"{type(exc).__name__}: {exc}")
            )
            return
        self._safe_send(make_response(msg_id, result))

    def _safe_send(self, frame: dict[str, Any]) -> None:
        with contextlib.suppress(FrameTooLargeError, BrokenPipeError, OSError):
            self._write_frame(frame)

    def _on_child_exit(self, proc: subprocess.Popen[bytes], *, crash: bool) -> None:
        rc = proc.wait()
        self.last_exit = rc
        with self._plock:
            deliberate = proc.pid in self._deliberate_exits
            self._deliberate_exits.discard(proc.pid)
            superseded = self.proc is not proc
        # An exit we caused (`restart`, a failed spawn hook) is not a crash, and
        # neither is the late reaping of a child something else already replaced.
        unexpected = crash and not self._closing.is_set() and not (deliberate or superseded)
        if unexpected:
            self._child_ready.clear()
            with self._plock:
                tracked = frozenset(self._tracked_runs)
                self._restart_generation += 1
                generation = self._restart_generation
                # Claim the respawn *before* recovery runs, so a caller arriving
                # in that window waits rather than seeing a childless supervisor.
                self._respawning = True
            self._record_restart(reason="crash", returncode=rc, generation=generation)
            self._fire_recovery(
                ProcessLossEvent(
                    reason="crash",
                    returncode=rc,
                    tracked_run_ids=tracked,
                    restart_generation=generation,
                )
            )
        self._fail_all_pending(
            make_error(None, ErrorCode.PROCESS_DOWN, f"sidecar exited (rc={rc})")["error"]
        )
        if unexpected:
            # Strictly after the recovery handoff and after the in-flight calls
            # have their structured error (architecture §5). The respawn itself
            # is handed to the watchdog thread: `PR_SET_PDEATHSIG` is armed
            # per-*thread*, so a child forked from this (about to exit) reader
            # thread would be SIGKILLed the instant this function returns.
            self._respawn_request.set()

    def _auto_respawn(self) -> None:
        """Bounded exponential-backoff respawn after an unexpected child exit.

        Runs on the watchdog thread (the only long-lived thread that may fork;
        see :meth:`_on_child_exit`). The crashed call already has its structured
        error, so the backoff blocks no caller. Attempts are counted across
        *consecutive* short-lived children; a child that survives
        ``respawn_cooldown_s`` resets the budget.
        """
        if not self._respawn_lock.acquire(blocking=False):
            return  # a chain is already running; it owns the attempt budget
        try:
            while True:
                with self._plock:
                    self._respawning = True
                    if time.monotonic() - self._spawned_at >= self.config.respawn_cooldown_s:
                        self._respawn_attempts = 0
                    if self._respawn_attempts >= self.config.respawn_max_attempts:
                        self._give_up_locked()
                        return
                    self._respawn_attempts += 1
                    attempt = self._respawn_attempts
                if self._closing.wait(self._backoff_s(attempt)):
                    return  # a deliberate shutdown never respawns
                with self._plock:
                    if self._closing.is_set() or self.is_running():
                        self._respawning = False
                        return
                try:
                    self.start()
                except Exception as exc:  # spawn failure, or a spawn hook that raised
                    self._respawn_last_error = f"{type(exc).__name__}: {exc}"
                    self._discard_child()
                    continue
                with self._plock:
                    self._respawning = False
                    self.auto_respawns += 1
                if self._closing.is_set():
                    # Raced a close(): do not leave a child behind.
                    self._discard_child()
                return
        finally:
            self._respawn_lock.release()

    def _give_up_locked(self) -> None:
        """Enter the durable dead state (call under ``_plock``)."""
        self._respawning = False
        detail = f" (last error: {self._respawn_last_error})" if self._respawn_last_error else ""
        self._respawn_failure = (
            "sidecar is not running: automatic respawn gave up after "
            f"{self.config.respawn_max_attempts} attempts{detail}; "
            "the supervisor stays dead until restart() is called"
        )
        # Release anyone waiting on the replacement; they re-check the failure.
        self._child_ready.set()

    def _discard_child(self) -> None:
        """Kill the current child on purpose (its exit must not count as a crash)."""
        with self._plock:
            proc = self.proc
            reader = self._reader
            if proc is None:
                return
            self._deliberate_exits.add(proc.pid)
        if proc.poll() is None:
            with contextlib.suppress(OSError):
                proc.kill()
        with contextlib.suppress(OSError, subprocess.TimeoutExpired):
            proc.wait(timeout=5)
        # Drain its reader before the next spawn, exactly as `restart` does: a
        # reader still winding down calls `_fail_all_pending`, and after the
        # replacement is up that would fail the *new* child's calls (the spawn
        # hook's own `runtime.configure` first of all).
        if reader is not None:
            reader.join(timeout=5)

    def _fail_all_pending(self, error: dict[str, Any]) -> None:
        with self._plock:
            pending = list(self._pending.values())
            self._pending.clear()
        for call in pending:
            call.complete_err(error)

    def _fire_recovery(self, event: ProcessLossEvent) -> None:
        # A recovery-hook fault must not wedge the restart path.
        if self._recovery_hook is not None:
            with contextlib.suppress(Exception):
                self._recovery_hook(event)

    # -- watchdog ----------------------------------------------------------

    def _watchdog_loop(self) -> None:
        while not self._closing.is_set():
            time.sleep(self.config.watchdog_interval_s)
            if self._closing.is_set():
                return
            if self._respawn_request.is_set():
                # An unexpected exit asked for a replacement. This thread owns
                # every automatic spawn because `PR_SET_PDEATHSIG` binds the
                # child's life to the *thread* that forked it, and this one lives
                # as long as the supervisor does.
                self._respawn_request.clear()
                with contextlib.suppress(Exception):
                    self._auto_respawn()
                continue
            if not self.is_running():
                continue
            now = time.monotonic()
            overdue = False
            with self._plock:
                for call in self._pending.values():
                    if now > call.deadline + self.config.watchdog_grace_s:
                        overdue = True
                        break
            if overdue:
                # The restart replays `runtime.configure` through the spawn hook,
                # so this blocks on a request; the hard bound in `call` keeps the
                # watchdog from being wedged by a child that never answers. A
                # failing hook is recorded by `_fire_spawn_hook` and must not take
                # the watchdog thread down with it.
                with contextlib.suppress(Exception):
                    self.restart(reason="watchdog")


# -- orphan verification helpers (used by tests) ---------------------------


def pid_alive(pid: int) -> bool:
    """True if ``pid`` exists and is not a zombie (per ``ps``)."""
    r = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True, check=False
    )
    if r.returncode != 0 or not r.stdout.strip():
        return False
    return "Z" not in r.stdout.strip()
