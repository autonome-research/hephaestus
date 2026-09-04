"""``BridgeRuntime``: the composed Stage 2A runtime loop (Python side).

Wires the supervised Node sidecar (:mod:`supervisor`) to the Python halves of
the bridge so a caller — ``heph agent`` or an end-to-end test — can drive a real
Pi session over the frozen wire protocol:

* **runtime.configure** is built once from a provider list (the fake
  OpenAI-compatible server in tests, real providers in production) and replayed
  onto *every* sidecar process via the supervisor's spawn hook — the first one
  and every respawn, since a fresh child has no configuration at all;
* **session.create / session.prompt / session.cancel** are issued as ordinary
  supervisor requests; every prompt gets a durably-admitted, tracked run id;
* the sidecar's **py.tool_dispatch** requests are authorized against the bound
  session **principal** (profile + part, recorded when this runtime originated
  ``session.create``) and routed through :class:`dispatch.ToolDispatcher` into
  the real core (create/edit/read + build/inspect via :class:`cad_ops.CadOps`);
* **py.ask_user** blocks on an injected *answerer* (interactive stdin in the CLI,
  a scripted callback in tests) and returns the human selection to the model;
* the sidecar's **event** / **terminal** notifications are normalized into a
  per-run buffer and streamed to an optional ``on_event`` callback; each terminal
  is durably ingested and acknowledged (``terminal.ack`` names the terminal id)
  before its admission slot is released.

The bridge itself is never surfaced to the client — callers see only normalized
Hephaestus events, never raw frames.
"""

from __future__ import annotations

import contextlib
import stat
import threading
import uuid
from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from hephaestus.core.project_store.layout import ProjectLayout, load_project
from hephaestus.core.project_store.retention import DefaultProtectedRoots
from hephaestus.core.project_store.store import ProjectStore
from opstore.types import JSONValue, TerminalState

from opstore import OpStore

from .admission import BridgeAdmission, bridge_store_config
from .cad_ops import (
    CadOps,
    bind_run_request_text,
    question_refusal,
    record_answers,
    release_run_request_text,
)
from .dispatch import DispatchError, Principal, ToolDispatcher
from .events import EventPump, HephaestusEvent, ObserverClient, PerClientQueue
from .protocol import ErrorCode, ProtocolError
from .sessions import RunInFlightError
from .sidecar import SidecarResolution, node_executable, resolve_sidecar
from .supervisor import ProcessLossEvent, Supervisor, SupervisorConfig, SupervisorError

__all__ = [
    "AgentUnavailableError",
    "AskUserAnswerer",
    "AuthLinkError",
    "BridgeRuntime",
    "EventCallback",
    "PromptResult",
    "ProviderSpec",
    "SessionRouteError",
    "UnknownSessionError",
    "default_dist_main",
    "link_auth_source",
    "repo_root",
]

_STATE_DB_NAME = "state.db"

#: ``<project>/.heph/agent`` — the app-owned credential directory (§23.2).
#: ``0700``, so the ``0600`` credential file inside it is not merely unreadable
#: but unreachable by another local user.
AGENT_DIR_MODE: int = 0o700

#: How many run→session bindings a long-lived serving process keeps (§2.7).
#: Chosen to match the pump's own 1024-slot per-client bound: a client that
#: cannot be more than 1024 events behind cannot need a binding older than that
#: many runs, and an evicted binding degrades to a *named* absence rather than a
#: wrong session id.
_RUN_SESSION_BINDINGS_MAX = 1024

#: ``(question_params) -> selection`` — resolves a ``py.ask_user`` request.
AskUserAnswerer = Callable[[dict[str, Any]], Any]

#: ``(event_dict) -> None`` — receives each normalized event as it streams.
EventCallback = Callable[[dict[str, Any]], None]

#: A provider spec understood by the sidecar's ``runtime.configure`` handler.
ProviderSpec = dict[str, Any]


def repo_root() -> Path:
    """The repository root (…/hephaestus), four levels above this file.

    Only meaningful inside a source checkout, and retained only for the test
    helpers that legitimately need the tree. Sidecar resolution must NOT use it:
    in an installed wheel this arithmetic lands somewhere above
    ``site-packages``. See :mod:`hephaestus.agent_bridge.sidecar`.
    """
    return Path(__file__).resolve().parents[4]


def default_dist_main() -> Path:
    """The verified sidecar entry the supervisor spawns.

    Delegates to the single resolver so the wheel, the override, and the source
    checkout all answer through one ordered, fail-closed policy.
    """
    return resolve_sidecar().main


@dataclass
class _Run:
    """Per-run event buffer + terminal record, filled by the notification sink."""

    run_id: str
    session_id: str
    events: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    terminal: dict[str, Any] | None = None
    on_event: EventCallback | None = None


@dataclass(frozen=True)
class PromptResult:
    """The outcome of one ``session.prompt`` run."""

    run_id: str
    status: str
    events: list[dict[str, Any]]
    terminal: dict[str, Any] | None

    def kinds(self) -> list[str]:
        """The ordered event kinds (handy for shape assertions)."""
        return [str(ev.get("kind")) for ev in self.events]


def _open_project_store(layout: ProjectLayout) -> OpStore:
    """Create-or-open the project's opstore with the 16-slot bridge config."""
    layout.store_root.mkdir(parents=True, exist_ok=True)
    layout.journal_dir.mkdir(parents=True, exist_ok=True)
    roots = DefaultProtectedRoots(layout)
    if (layout.store_root / _STATE_DB_NAME).exists():
        store = OpStore.open(layout.store_root, protected_roots=roots)
    else:
        store = OpStore.create(layout.store_root, bridge_store_config(), protected_roots=roots)
    roots.bind(store)
    return store


class AuthLinkError(Exception):
    """``auth_source`` could not be exposed to the app-owned agent dir."""


class SessionRouteError(SupervisorError):
    """A session route refused **by name** (``INTERFACE.md`` §2.4, 2026-09-03).

    Raised in place of a bare :class:`SupervisorError` so the HTTP layer can map
    a failed session read or prompt onto a *named* reason. Today an unmapped
    ``SupervisorError`` is re-raised by ``http/errors.py`` and reaches the client
    as an unnamed 500 — over a transcript that is sitting intact on disk — so the
    panel can only say "the recorded transcript could not be read", forever, with
    no remedy attached.

    ``reason`` is both the token the route refuses with (§2.4) and the token
    :meth:`BridgeRuntime.sessions` reports as ``unreadable_reason`` (§2.3), so a
    panel renders the same word whichever way it learns the fact.

    A **subclass of** :class:`SupervisorError` on purpose: every existing
    ``except SupervisorError`` handler (the CLI, ``http/agent_attach``,
    ``workflows``) keeps exactly the behaviour it has today, and only a caller
    that asks for ``reason`` sees the new fact.
    """

    #: The wire token. Overridden per subclass and never composed at a call site,
    #: so the two vocabularies (§2.3's mark and §2.4's refusal) cannot drift.
    reason: str = "agent_unavailable"

    def __init__(
        self,
        message: str,
        *,
        session_id: str,
        error: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, error=error)
        self.session_id = session_id


class UnknownSessionError(SessionRouteError):
    """The sidecar does not know this session, after one re-adoption attempt.

    §2.4: **404** ``unknown_session`` + ``{session_id}``. An addressing miss and
    nothing more — the Pi JSONL may be perfectly intact on disk, which is why
    §2.3 keeps the row *listed* and merely marks it. Delisting would erase from
    the UI a transcript that still exists.
    """

    reason: str = "unknown_session"


class AgentUnavailableError(SessionRouteError):
    """No sidecar can serve this route — none attached, or none that will start.

    §2.4: **503** ``agent_unavailable`` carrying §7A.8's ``cause``. The cause is
    ``sidecar_failed``, which is already in §7A.8's closed cause set, so naming
    this path does not widen the vocabulary.

    **Never collapsed into** :class:`UnknownSessionError`: one says *this
    session*, the other says *this runtime*. The remedies differ — open another
    session versus repair the runtime — and a client that could not tell them
    apart would offer the wrong one.
    """

    reason: str = "agent_unavailable"
    #: §7A.8's closed ``cause`` set; named here so the HTTP layer copies a token
    #: rather than inventing one.
    cause: str = "sidecar_failed"


def _names_unknown_session(exc: SupervisorError) -> bool:
    """Does this failure carry the sidecar's *unknown session* refusal?

    The sidecar answers ``INVALID_PARAMS`` with ``unknown session '<id>'`` for
    every session route it cannot address (``agent/src/main.ts:505`` prompt,
    ``:668`` compact, ``:680`` history). Read off the **structured envelope** the
    supervisor already retains (:attr:`SupervisorError.error`) rather than the
    formatted message: the envelope is the frame's own fact and the message is
    only a rendering of it.

    Deliberately narrow. Every other failure — a timeout, a provider error, a
    refused tool — is *not* an addressing miss, and re-adopting on one would
    retry work the model may already have done.
    """
    error = exc.error
    code = error.get("code")
    if not isinstance(code, int) or code != ErrorCode.INVALID_PARAMS:
        return False
    return "unknown session" in str(error.get("message", "")).casefold()


#: Content of a Pi ``auth.json`` that carries nothing worth protecting; the
#: sidecar writes this placeholder on first run, so an ``auth_source`` declared
#: after a plain run must be allowed to replace it.
_EMPTY_AUTH = ("", "{}")


def link_auth_source(agent_dir: Path, auth_source: Path) -> Path:
    """Symlink ``<agent_dir>/auth.json`` at an existing Pi ``auth.json``.

    This is the *only* way a credential the app did not mint reaches the sidecar,
    and it is opt-in: nothing happens unless the provider config named an
    ``auth_source``. Two properties are load-bearing.

    **A symlink, never a copy.** OAuth records rotate: Pi refreshes the access
    token and rewrites the file, invalidating the refresh token it replaced. A
    copy would therefore either go stale or — worse — refresh independently and
    revoke the user's own Codex/Pi login out from under them. A symlink keeps a
    single file with a single rotation, shared by both readers.

    **Never clobber a real credential.** An existing symlink is ours to re-point;
    an existing *file* is replaced only when it is Pi's empty placeholder.
    Anything else raises rather than destroying a login.
    """
    target = auth_source.expanduser()
    if not target.is_file():
        raise AuthLinkError(
            f"auth_source {target} does not exist (or is not a file); "
            "point it at an existing Pi auth.json, or drop the setting"
        )
    link = agent_dir / "auth.json"
    if link.is_symlink():
        link.unlink()
    elif link.exists():
        try:
            existing = link.read_text(encoding="utf-8").strip()
        except OSError as exc:  # pragma: no cover - unreadable file
            raise AuthLinkError(f"cannot inspect existing {link}: {exc}") from exc
        if existing not in _EMPTY_AUTH:
            raise AuthLinkError(
                f"{link} already exists and holds credentials; refusing to replace it "
                f"with a link to {target}. Move or delete it first if that is intended."
            )
        link.unlink()
    link.symlink_to(target)
    return link


def _node_executable() -> str:
    """Node, after the explicit ≥22.19 compatibility check (`repo_conventions`)."""
    return node_executable()


def _as_dict(value: Any) -> dict[str, Any]:
    """Narrow a bridge result to an object; anything else is an empty one.

    The bridge's results are ``Any`` by construction (they crossed a JSON-RPC
    frame). Narrowing here once keeps every credential relay below free of a
    cast, and a non-object result reads as "the sidecar said nothing" rather
    than as a type error at a call site three layers up.
    """
    return cast("dict[str, Any]", value) if isinstance(value, dict) else {}


def _provider_status_of(result: Any) -> list[dict[str, Any]]:
    """``configure``'s per-provider verification list (§23.7), defensively read.

    An older sidecar answers ``{ok, providers: <count>}`` — an integer where
    this expects a list. That is not an error: it is a runtime built before
    verification became per-provider, and it reports *no* per-provider facts
    rather than inventing optimistic ones.
    """
    rows = _as_dict(result).get("providers")
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for row in cast("list[Any]", rows):
        if isinstance(row, dict):
            out.append(cast("dict[str, Any]", row))
    return out


class BridgeRuntime:
    """Composed runtime: supervised sidecar + Python dispatch/admission/events."""

    def __init__(
        self,
        *,
        project_root: Path,
        providers: Sequence[ProviderSpec],
        credentials: dict[str, str] | None = None,
        credential_allowlist: Sequence[str] = (),
        dist_main: Path | None = None,
        agent_dir: Path | None = None,
        answerer: AskUserAnswerer | None = None,
        auth_source: Path | None = None,
        store: OpStore | None = None,
        project_store: ProjectStore | None = None,
        cad: CadOps | None = None,
        dispatcher: ToolDispatcher | None = None,
    ) -> None:
        self._layout = load_project(project_root)
        # ONE store, ONE ``ProjectStore``, ONE dispatcher per process. The four
        # optional injections exist for exactly one caller — ``heph serve --web``,
        # which has already opened this project (``http/runtime.py``) — and they
        # are what keeps that process from holding *two* ``LockManager`` owners
        # over one project's ``.heph/locks/``. §2.1's "one process owns the
        # leases" is not a slogan: two owners in one process is two writers, the
        # very thing it exists to prevent. An injected store is not ours to
        # close (see :meth:`close`).
        self._owns_store = store is None
        self._store = _open_project_store(self._layout) if store is None else store
        self._project = (
            ProjectStore(self._layout, self._store) if project_store is None else project_store
        )
        self._cad = CadOps(self._layout, self._store) if cad is None else cad
        self._dispatcher = (
            ToolDispatcher(self._project, cad=self._cad) if dispatcher is None else dispatcher
        )
        self._admission = BridgeAdmission(self._store.admission)
        # Bounded per-client fan-out + the durable terminal channel (digest §6):
        # the pump coalesces progress, never drops audit/tool/question/terminal
        # events, and acks each terminal by id only once it is durable.
        self._pump = EventPump(
            self._store.admission,
            ack_terminal=self._ack_terminal,
            cancel_run=self._backpressure_cancel,
        )
        self._providers = list(providers)
        self._credentials = dict(credentials or {})
        #: §23.2's ``serve`` scope: keys pasted into this serve, held in this
        #: process's heap and nowhere else. Never written, never projected, and
        #: gone when the process ends.
        self._runtime_keys: dict[str, str] = {}
        #: The last ``runtime.configure`` result's per-provider verification
        #: (§23.7). Empty until a child has been configured.
        self._provider_status: list[dict[str, Any]] = []
        self._default_answerer = answerer

        self._principals: dict[str, Principal] = {}
        # INTERFACE.md §2.3 (amended 2026-09-03): why a session this runtime
        # LISTS could not be read, keyed by session id and holding §2.4's reason
        # token. IN MEMORY, and that is correct rather than a shortcut: the flag
        # is a cache of a *failure*, not a fact about the transcript, so a
        # process that restarts has not tried yet and every row starts readable.
        # Worst case of forgetting is one honest attempt; worst case of
        # persisting is a session marked dead by a process that is gone.
        #
        # Beside the principal map rather than a field ON ``Principal``:
        # ``Principal`` is the *authz* identity ``py.tool_dispatch`` is resolved
        # against (``dispatch.py``), and a read-failure cache is not an authz
        # fact. Same lifetime, same lock, no widening of what authorizes a tool.
        self._unreadable: dict[str, str] = {}
        # §2.8(6)'s "resume ONCE": the child generation (``Supervisor``'s
        # ``spawn_count``) a session was last re-adopted against, plus a
        # per-session lock so two concurrent readers of the same session share
        # one attempt instead of each spawning their own. The clause exists to
        # prevent a spawn storm, and "once per failure" alone does not: N
        # concurrent history reads of a dead session are N failures.
        self._readopted: dict[str, int] = {}
        self._readopt_locks: dict[str, threading.Lock] = {}
        self._runs: dict[str, _Run] = {}
        # INTERFACE.md §2.7: the live wire frame carries exactly one envelope
        # field beyond the Python-side shape — ``session_id`` — so a
        # multi-session panel can route without inspecting payloads. The pump's
        # events are keyed by run, so the run→session binding has to live
        # somewhere that OUTLIVES the run: ``_runs`` is popped when ``prompt``
        # returns, and a terminal or a late event arriving after that would be
        # unroutable. Bounded because a long-lived serving process runs
        # unboundedly many runs; the oldest binding is evicted, and an event for
        # an evicted run is served with a null session id rather than a guess.
        self._run_sessions: OrderedDict[str, str] = OrderedDict()
        self._answerers: dict[str, AskUserAnswerer] = {}
        self._lock = threading.RLock()
        # Serializes cancel() against close(): cancels arrive on daemon
        # threads (bench budget ceilings, timeouts) and write through the
        # opstore, so a cancel in flight while close() tears the store down
        # was a native use-after-free (the long-sweep SIGSEGV). After close,
        # cancel is a quiet no-op — the runtime it would cancel is gone.
        self._teardown_lock = threading.Lock()
        self._closed = False

        agent_dir = agent_dir or (self._layout.store_root / "agent")
        # 0700, created private and tightened if it already exists looser.
        # INTERFACE.md §23.2 closes the list of places a provider secret may
        # live and names the mode of each: ``<project>/.heph/agent/auth.json``
        # at ``0600``, **parent ``0700``**. Pi writes the file privately; the
        # directory was ours and was being created with the process umask
        # (0755 on a default install), which leaves another local user able to
        # stat the credential file and watch it appear. §23.13's second threat
        # class is exactly "another local user", and this is the half of that
        # defence the app owns.
        #
        # Tightened rather than only created: an agent dir made by an earlier
        # version is still a directory THIS code created, so §23.2's "a file the
        # operator hand-authored is not chmod'ed by the workspace" does not
        # reach it — that rule is about the operator's own files.
        agent_dir.mkdir(parents=True, exist_ok=True, mode=AGENT_DIR_MODE)
        with contextlib.suppress(OSError):
            if stat.S_IMODE(agent_dir.stat().st_mode) != AGENT_DIR_MODE:
                agent_dir.chmod(AGENT_DIR_MODE)
        # Opt-in credential linking: with no auth_source the agent dir keeps only
        # what the sidecar itself writes, so a `pi_native` provider has nothing to
        # authenticate with and fails loudly instead of borrowing an ambient login.
        if auth_source is not None:
            link_auth_source(agent_dir, auth_source)
        # Resolution and integrity verification happen HERE, before any child is
        # spawned — a tampered or missing packaged sidecar raises a named
        # SidecarError rather than degrading to a global pi/thread-phase binary.
        # An explicit `dist_main` names one exact entry file (the harness escape
        # hatch); everything else goes through the ordered policy and is verified.
        self._sidecar: SidecarResolution | None
        if dist_main is None:
            self._sidecar = resolve_sidecar()
            entry = self._sidecar.main
        else:
            self._sidecar = None
            entry = dist_main
        argv = [_node_executable(), str(entry)]
        # HEPHAESTUS_AGENT_DIR is app-owned configuration, not a credential: it is
        # injected explicitly (never sourced from the ambient environment) so the
        # sidecar's auth.json / models-store.json live under the project's
        # .heph/agent instead of whatever directory the supervisor happened to
        # run from.
        config = SupervisorConfig(
            argv=argv,
            credential_allowlist=frozenset(credential_allowlist),
            extra_env={"HEPHAESTUS_AGENT_DIR": str(agent_dir)},
            cwd=str(self._layout.root),
        )
        self._sup = Supervisor(
            config,
            py_handler=self._on_py_request,
            notification_sink=self._on_notification,
            recovery_hook=self._on_process_loss,
            # Every child — the first one, an explicit restart(), and the
            # watchdog's own respawn — gets the configure payload replayed
            # before anyone can use it. A respawned sidecar is a blank runtime,
            # and without this it answers every later session.create /
            # session.prompt with "runtime.configure has not run yet".
            spawn_hook=self._configure_runtime,
        )
        # INTERFACE.md §23.6/§23.14 item 10: the allowlisted credentials this
        # process is about to forward are exactly the values a provider's error
        # text could quote back onto the sidecar's stderr, which the supervisor
        # drains into a tail the bench harness archives. Registered before the
        # first child exists, so there is no window in which a leak could be
        # retained un-redacted.
        for secret in self._credentials.values():
            self._sup.add_redaction(secret)

    # -- lifecycle ---------------------------------------------------------

    @property
    def sidecar(self) -> SidecarResolution | None:
        """The verified sidecar this runtime spawns, or ``None`` under an
        explicit ``dist_main`` override.

        Exposed so G7H's packaged-sidecar test can assert on the *resolution the
        runtime actually used* — its source branch and root path — instead of
        re-deriving one and hoping the two agree.
        """
        return self._sidecar

    @property
    def configure_payload(self) -> dict[str, Any]:
        """The one ``runtime.configure`` payload, replayed onto every child.

        Built here and nowhere else: two call sites that each assemble their own
        dict are two payloads that can drift, and the drift would only show up
        after a respawn nobody asked for.

        ``runtime_keys`` is §23.2's ``serve`` scope on the wire: keys pasted
        into this serve and held **only** in this process's heap. Omitted
        entirely when empty, so the ordinary payload is byte-identical to what
        it has always been and the respawn-replay goldens do not move.
        """
        payload: dict[str, Any] = {
            "providers": self._providers,
            "credentials": self._credentials,
        }
        if self._runtime_keys:
            payload["runtime_keys"] = dict(self._runtime_keys)
        return payload

    def _configure_runtime(self, sup: Supervisor) -> None:
        """Supervisor spawn hook: push ``runtime.configure`` onto a fresh child.

        The result is retained because §23.7 makes provider verification
        **fail-closed per provider** rather than per runtime: ``configure``
        answers ``providers: [{id, available, unavailable_reason?}]``, and that
        list is what ``GET /providers`` renders and what a ``session.create``
        against an unavailable provider is refused by. Retained here rather than
        re-asked because it is replayed onto every child, so the freshest answer
        is always the one the current child gave.

        **Why the hook does not also re-open this runtime's sessions.** A fresh
        child has an empty session map while ``_principals`` still lists every
        session this process opened, which is the whole of §2.8(6)'s bug.
        Replaying them here — one ``session.create resume=true`` per retained
        principal — was considered and rejected on two grounds, both about
        failure rather than cost:

        * *A hook that raises kills the runtime.* ``Supervisor._respawn_loop``
          treats a spawn-hook exception exactly like a failed spawn: it discards
          the child and burns a respawn attempt, and once the budget is gone the
          supervisor is durably dead until an explicit ``restart()``. One session
          whose JSONL cannot be re-opened would take down every other session,
          the provider config, and the login path that might repair it. Wrapping
          each resume in a ``try`` only converts that into the second objection.
        * *It re-opens sessions nobody asked about.* Re-adoption is per read
          (:meth:`_call_for_session`): it costs one extra round trip on the first
          call after a respawn, is scoped to the session actually addressed, and
          its failure is answerable to the caller that provoked it — which is
          what lets §2.4 name a reason instead of logging one into the void.
          Eager replay pays for every session on every respawn to save that trip.

        The lazy path is also the one §2.8(6) specifies ("the server resumes the
        session once and retries"), so this is not a deviation, only its reason.
        """
        result = sup.call("runtime.configure", self.configure_payload)
        self._provider_status = _provider_status_of(result)

    def provider_status(self) -> list[dict[str, Any]]:
        """Per-provider verification from the last ``runtime.configure`` (§23.7).

        **This looks like a weakening and is not.** The property the old
        fail-per-runtime behaviour carried is about *substitution*: an
        unauthenticated provider can never fall back to an ambient login. That
        is unchanged and asserted — an unavailable provider is never silently
        replaced and cannot serve a turn. What changes is that its failure no
        longer takes its neighbours, and the login path that would fix it, down
        with it. `createModelRuntime` used to throw on the first provider that
        failed verification, so a declared-but-unauthenticated provider meant no
        sidecar, therefore no bridge, therefore no way to perform the login.
        """
        return [dict(row) for row in self._provider_status]

    def start(self) -> None:
        """Spawn the sidecar (the spawn hook pushes ``runtime.configure``)."""
        self._sup.start()

    def restart(self, *, reason: str = "manual") -> None:
        """Kill the whole sidecar and respawn it; the spawn hook re-configures.

        Generic in-flight runs are marked interrupted by the supervisor's
        recovery hook before this returns; persisted Pi sessions are re-openable
        via :meth:`resume_session`.

        ``reason`` reaches the archived restart record. §23.7 applies a
        credential change by restarting with ``reason="credentials"`` — a
        credential change is not a hot swap and the record says which restarts
        were one.
        """
        self._sup.restart(reason=reason)

    # -- credentials (§23.14 item 3) ---------------------------------------
    #
    # Eight thin relays and nothing more. **Pi remains the single authority**:
    # nothing below stores a credential, mints a PKCE verifier, exchanges a
    # token, or refreshes one — mission rule 6 forbids a second implementation
    # of what the pinned dependency owns, and §23.2 states the cost of that
    # decision plainly (every credential write needs a live sidecar, which is
    # why §23.0's attach capability is item 1 and not a footnote).
    #
    # The Python side sees four non-secret values on the way out of a login
    # (`user_code`, `verification_uri`, `interval_seconds`, `expires_at`) and
    # `{state, type, expires_at}` on the way back. It never sees an
    # authorization code, an access token, or a refresh token at all.

    def provider_catalog(self) -> dict[str, Any]:
        """Pi's built-in catalog plus this runtime's registered providers (§23.1).

        Read live over the bridge. §23.1 rejects a Hephaestus-defined provider
        catalog outright: a second catalog beside Pi's would drift the moment Pi
        ships a provider, which mission rule 6 forbids.
        """
        return _as_dict(self._sup.call("providers.list", {}))

    def credential_status(self, provider_id: str) -> dict[str, Any]:
        """``{state, type?, expires_at?, health, last_observed_at, flow?}`` — metadata only."""
        return _as_dict(self._sup.call("credentials.status", {"provider_id": provider_id}))

    def set_api_key(self, provider_id: str, key: str, *, scope: str) -> dict[str, Any]:
        """Hand Pi an API key. The key crosses this boundary once and is never held.

        ``scope="project"`` persists it through Pi's ``AuthStorage`` (``0600``
        under a cross-process lock); ``scope="serve"`` keeps it in the configure
        map for this serve only. The value is registered with the supervisor's
        redaction pass **before** it is sent, so a provider that quotes it back
        on stderr cannot leave it in the retained tail (§23.6).
        """
        self._sup.add_redaction(key)
        if scope == "serve":
            # The serving process's heap, en route to `runtime.configure` — one
            # of §23.2's three permitted places, and the only one this process
            # is on. Carried on the configure payload so a respawn replays it
            # (a `serve`-scoped key that vanished on the watchdog's own respawn
            # would be a credential the operator set and the product silently
            # forgot); gone when the process ends, which is what `serve` means.
            self._runtime_keys[provider_id] = key
        result = _as_dict(
            self._sup.call(
                "credentials.set_key",
                {"provider_id": provider_id, "key": key, "scope": scope},
            )
        )
        return result

    def sign_out(self, provider_id: str) -> dict[str, Any]:
        """Remove the credential under Pi's lock and drop any serve-scoped key.

        §23.9's three properties: the provider **spec** is not deleted (the row
        stays, in state ``none``), and the write cannot fail halfway because
        Pi's ``modify`` is a serialized read-modify-write whose throwing
        operation propagates without writing.
        """
        self._runtime_keys.pop(provider_id, None)
        return _as_dict(self._sup.call("credentials.signout", {"provider_id": provider_id}))

    def login_begin(self, provider_id: str, flow_type: str) -> dict[str, Any]:
        """Start a subscription flow. Returns non-secret values only (§23.4)."""
        return _as_dict(
            self._sup.call("login.begin", {"provider_id": provider_id, "type": flow_type})
        )

    def login_status(self, provider_id: str) -> dict[str, Any]:
        """Poll the flow. The **sidecar** polls the provider; the browser never does."""
        return _as_dict(self._sup.call("login.status", {"provider_id": provider_id}))

    def login_complete(self, provider_id: str, text: str) -> dict[str, Any]:
        """Hand Pi the operator's pasted redirect URL / ``code#state`` / bare code.

        Pi's own ``parseAuthorizationInput`` accepts all three and **verifies
        ``state``**; a mismatch is refused and the credential is unchanged. This
        server is not an OAuth client and applies to become one for nobody.
        """
        return _as_dict(
            self._sup.call("login.complete", {"provider_id": provider_id, "input": text})
        )

    def login_cancel(self, provider_id: str) -> dict[str, Any]:
        """Abandon a pending flow. Idempotent by construction."""
        return _as_dict(self._sup.call("login.cancel", {"provider_id": provider_id}))

    def live_run_ids(self) -> list[str]:
        """Run ids with a turn in flight right now (§23.7's ``runs_in_flight``).

        A credential change restarts the sidecar and **a restart kills every
        in-flight run in every session**. That cost is surfaced rather than
        swallowed: the refusal lists these ids and the dialog names the count.
        """
        with self._lock:
            return sorted(self._runs)

    def close(self) -> None:
        """Graceful shutdown: close the sidecar (no orphan) and the opstore."""
        try:
            self._sup.notify("cancel", {"run_id": "*"})
        finally:
            self._sup.close()
            with self._teardown_lock:
                self._closed = True
                # An injected store belongs to the caller that opened it; closing
                # it here would tear the workspace's own project out from under
                # the HTTP routes that share it.
                if self._owns_store:
                    self._store.close()

    def __enter__(self) -> BridgeRuntime:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def child_pid(self) -> int:
        return self._sup.child_pid

    def sidecar_evidence(self) -> dict[str, Any]:
        """The supervisor's own record of this runtime's sidecar lifecycle.

        ``EXTERNAL_EVAL.md`` §5: every restart with its reason plus a bounded
        stderr tail, read for the bench archive (``restarts.json`` /
        ``sidecar.log``). The state lives on the supervisor object, so it is
        still readable after :meth:`close` — which is when the harness asks.
        """
        return {
            "restarts": [dict(event) for event in self._sup.restart_events],
            "stderr_tail": list(self._sup.stderr_tail),
            "auto_respawns": self._sup.auto_respawns,
            "spawn_count": self._sup.spawn_count,
            "spawn_errors": list(self._sup.spawn_errors),
        }

    @property
    def admission(self) -> BridgeAdmission:
        return self._admission

    @property
    def store(self) -> OpStore:
        """The project's opstore — the same handle when one was injected."""
        return self._store

    def rebind_project(
        self,
        *,
        layout: ProjectLayout,
        project_store: ProjectStore,
        cad: CadOps,
        dispatcher: ToolDispatcher,
    ) -> None:
        """Re-point this runtime at a re-read manifest (``INTERFACE.md`` §6.4).

        ``POST /project/config/dfm`` rewrites ``[dfm] auto_run`` in the human's
        manifest and the workspace rebinds; a sidecar still holding the *old*
        ``CadOps`` would keep building with the old flag, so the agent and the
        panel would disagree about a project setting. Called only by the process
        that injected these objects in the first place.
        """
        self._layout = layout
        self._project = project_store
        self._cad = cad
        self._dispatcher = dispatcher

    @property
    def cad(self) -> CadOps:
        """The runtime's own CAD/ledger handle.

        Exposed because the ``VALIDATION.md`` §5/§6 ladder must read *this*
        ledger — the one the run actually wrote through the dispatcher — rather
        than a second handle opened over the same store.
        """
        return self._cad

    # -- sessions ----------------------------------------------------------

    def create_session(
        self,
        profile: str,
        *,
        part: str | None = None,
        session_id: str | None = None,
        resume: bool = False,
    ) -> str:
        """Create (or resume) a sidecar session; record its principal for authz."""
        params: dict[str, Any] = {
            "profile": profile,
            "project_root": str(self._layout.root),
        }
        if session_id is not None:
            params["session_id"] = session_id
        if part is not None:
            params["part"] = part
        if resume:
            params["resume"] = True
        result = self._sup.call("session.create", params)
        sid = str(result["session_id"])
        with self._lock:
            self._principals[sid] = Principal(session_id=sid, profile=profile, part=part)
            # §2.3: the mark is cleared the moment a call for that session
            # succeeds. Opening it IS such a call, so a hand-written
            # ``resume_session`` (the CLI, the stage-2 workflow tests) heals the
            # listing exactly like the automatic re-adoption below does.
            self._unreadable.pop(sid, None)
        return sid

    def resume_session(self, profile: str, session_id: str, *, part: str | None = None) -> str:
        """Resume a persisted session by id after a restart."""
        return self.create_session(profile, part=part, session_id=session_id, resume=True)

    # -- readability: re-adopt once, then refuse by name (§2.3/§2.4/§2.8(6)) --

    def _principal_of(self, session_id: str) -> Principal | None:
        with self._lock:
            return self._principals.get(session_id)

    def _mark_readable(self, session_id: str) -> None:
        """Forget a recorded failure the moment a call for it succeeds (§2.3)."""
        with self._lock:
            self._unreadable.pop(session_id, None)

    def _mark_unreadable(self, session_id: str, reason: str) -> None:
        """Record *why* this session's last call failed, for ``GET /sessions``.

        Only for a session this runtime retains a principal for: the listing is
        built from the principal map, so a mark for anything else is an entry
        nothing can render and nothing can ever clear.
        """
        with self._lock:
            if session_id in self._principals:
                self._unreadable[session_id] = reason

    def _readopt_lock(self, session_id: str) -> threading.Lock:
        """The per-session re-adoption lock (created on first use).

        Never acquired while holding it: :meth:`_readopt_once` takes ``_lock``
        here, releases it, and only then takes the session lock, so the one lock
        order in this file is *session lock → ``_lock``*.
        """
        with self._lock:
            lock = self._readopt_locks.get(session_id)
            if lock is None:
                lock = threading.Lock()
                self._readopt_locks[session_id] = lock
            return lock

    def _readopt_once(self, session_id: str, principal: Principal) -> None:
        """Re-open a retained session on the current child. **Once per child.**

        §2.8(6) says "resumes the session once and retries", and leaves open what
        a *second concurrent* reader should do during that resume. Decided here,
        in the bridge that owns the locking: the attempt is keyed by
        ``(session, child generation)``, so concurrent readers share one attempt
        and a session is re-adopted at most once per sidecar process. Reading
        ``once`` as once-per-failure would let N concurrent history reads of a
        genuinely dead session become N spawns — exactly the storm the clause
        exists to prevent.

        Keyed by generation rather than by a boolean because a *later* child is a
        genuinely new fact: the next respawn empties the session map again, and
        the first read after it must be allowed its one honest attempt.

        What is recorded is the ATTEMPT, not its success, and it is recorded
        BEFORE the resume runs. A resume that fails still consumes the attempt:
        otherwise eight concurrent readers of a genuinely dead session would
        queue on this lock and take eight turns at spawning it, which is the
        storm read the other way round.
        """
        generation = self._sup.spawn_count
        with self._readopt_lock(session_id):
            with self._lock:
                if self._readopted.get(session_id) == generation:
                    # Another reader already spent this child's attempt; the
                    # caller retries the call rather than resuming a second time.
                    return
                self._readopted[session_id] = generation
            self.resume_session(principal.profile, session_id, part=principal.part)

    def _refuse_by_name(
        self,
        session_id: str,
        exc: SupervisorError,
        *,
        readopted: bool,
        fallback: str | None = None,
    ) -> SupervisorError:
        """Classify a failed session call onto §2.4's two named refusals.

        Returns the exception the caller should raise: a named one — with the
        listing marked to match — or ``exc`` **unchanged** when the failure is
        neither of §2.4's two conditions. A timeout is not an addressing miss and
        not a dead runtime; renaming it would put a wrong remedy in front of the
        operator, and §2.4's two rows are two conditions, not a catch-all.

        ``fallback`` is the reason to use when a *retry* failed for some third
        cause: the first failure already established that the sidecar does not
        know this session, and a resume that failed for its own reasons does not
        unsay that.

        ``readopted`` says whether §2.8(6)'s single re-adoption attempt actually
        ran, and it changes only the sentence — never the reason token, never the
        status, never the ``{session_id}`` body §2.4 specifies. The two paths
        into ``unknown_session`` are genuinely different events: one runtime
        *tried* to re-open a retained principal and failed, the other holds no
        principal for the id and so could not try. A refusal's words are the
        operator's only account of what this server did, so a fixed sentence
        claiming an attempt that never happened is a small lie told on the path
        where the operator most needs the truth — a mistyped or foreign id looks
        exactly like a transcript this runtime broke.
        """
        if _names_unknown_session(exc):
            reason = UnknownSessionError.reason
        elif not exc.error and not self._sup.is_running():
            # No JSON-RPC envelope AND no child: the call never reached a
            # sidecar. §7A.8's ``sidecar_failed`` cause, reached by one more path.
            reason = AgentUnavailableError.reason
        elif fallback is not None:
            reason = fallback
        else:
            return exc
        refusal: SessionRouteError
        if reason == UnknownSessionError.reason:
            recovery = (
                "and one re-adoption attempt did not recover it"
                if readopted
                else "and this runtime holds no session with that id to re-adopt"
            )
            refusal = UnknownSessionError(
                f"unknown session {session_id!r}: the sidecar does not know it, {recovery}",
                session_id=session_id,
                error=exc.error,
            )
        else:
            refusal = AgentUnavailableError(
                f"no sidecar can serve session {session_id!r}: {exc}",
                session_id=session_id,
                error=exc.error,
            )
        self._mark_unreadable(session_id, refusal.reason)
        return refusal

    def _call_for_session(
        self,
        method: str,
        params: dict[str, Any],
        *,
        session_id: str,
        timeout: float | None = None,
    ) -> Any:
        """One supervisor call for a session, made self-healing (§2.8(6)).

        Argument order mirrors :meth:`Supervisor.call` — ``(method, params,
        timeout=)`` — because this *is* that call plus a re-adoption; the
        session is the healing context and rides as a keyword. The mirroring is
        also what keeps ``tests/stage2/test_workflow_history.py``'s "Python
        reaches a transcript only through an RPC" guard able to see which method
        each literal names: that check reads the FIRST positional argument of
        every call, so a method name demoted to second position would leave it
        asserting an empty list — a guard that passes by seeing nothing.

        **The gap this closes.** The spawn hook replays ``runtime.configure`` and
        nothing else (:meth:`_configure_runtime`), so a respawned child's session
        map is empty while ``_principals`` — written by :meth:`create_session`,
        never pruned — still lists every session this process opened. Every route
        for such a session then failed ``INVALID_PARAMS: unknown session``, which
        ``http/errors.py`` re-raised as an unnamed 500 over a transcript that
        exists intact on disk.

        On exactly that failure, and on no other, the retained principal is
        re-opened once (:meth:`_readopt_once`) and the call is retried once. **A
        success is silent** — the client never learns anything happened, which is
        the point. A second failure is refused BY NAME and the principal is
        marked, so the route and ``GET /sessions`` say the same word.

        Retrying is safe here *because* the refusal is an addressing miss: the
        sidecar rejected the frame before running anything, so no model work is
        repeated and §2.3's at-least-once prompt rule is not stretched. Nothing
        else is retried — a timeout may well have started a turn.
        """
        try:
            result = self._sup.call(method, params, timeout=timeout)
        except SupervisorError as exc:
            principal = self._principal_of(session_id)
            if principal is None or not _names_unknown_session(exc):
                # No attempt is made here and none was possible: either the
                # failure is not an addressing miss, or this runtime retains no
                # principal to re-open. The sentence must not claim one ran.
                refusal = self._refuse_by_name(session_id, exc, readopted=False)
                if refusal is exc:
                    raise
                raise refusal from exc
            try:
                self._readopt_once(session_id, principal)
                result = self._sup.call(method, params, timeout=timeout)
            except SupervisorError as retry_exc:
                raise self._refuse_by_name(
                    session_id,
                    retry_exc,
                    readopted=True,
                    fallback=UnknownSessionError.reason,
                ) from retry_exc
        self._mark_readable(session_id)
        return result

    # -- prompting ---------------------------------------------------------

    def new_run_id(self) -> str:
        """Mint a stable run id (allocate it *before* prompting to cancel a run)."""
        return f"run-{uuid.uuid4().hex[:12]}"

    def client_queue(self, client_id: str) -> PerClientQueue:
        """Register a **durable** client and get its bounded, coalescing queue."""
        return self._pump.add_client(client_id)

    def add_observer(
        self, client_id: str, *, notify: Callable[[], None] | None = None
    ) -> ObserverClient:
        """Register a §2.7 **non-durable observer** (a browser tab, or the
        ``heph agent`` client attached to a running server).

        The distinction is the whole of §2.7's second trap: an observer's
        overflow drops the observer, never the run.
        """
        return self._pump.add_observer(client_id, notify=notify)

    def drop_client(self, client_id: str) -> None:
        self._pump.remove_client(client_id)

    def add_event_tap(self, tap: Callable[[HephaestusEvent], None]) -> None:
        """Register a process-owned synchronous hook on the event fan-out.

        The serving process's bounded live buffer (§2.7) rides this, not a client
        queue: see :meth:`EventPump.add_tap`.
        """
        self._pump.add_tap(tap)

    # -- what a client needs to route an event -----------------------------

    def session_for_run(self, run_id: str) -> str | None:
        """The session a run belongs to, or ``None`` once the binding is evicted.

        The one authority for §2.7's ``session_id`` envelope field. ``None`` is a
        named absence, not a default: a client routing on it must show the event
        unrouted rather than attribute it to whichever session it happens to be
        rendering.
        """
        with self._lock:
            return self._run_sessions.get(run_id)

    def sessions(self) -> list[dict[str, Any]]:
        """The sessions **this runtime owns**, for ``GET /sessions`` (§2.3).

        Bounded by honesty: these are the sessions this process created or
        resumed, which is the same thing as the sessions whose ``.heph/locks/``
        leases it holds (§2.1 — one process owns the leases). A persisted Pi
        JSONL on disk that nobody has opened is *not* listed, because finding one
        would mean parsing Pi's session format outside the sidecar, which
        ``STAGE2_DIGEST`` §2 forbids: nothing outside the sidecar ever parses Pi
        JSONL. The workspace's "attach" affordance therefore lists live sessions,
        exactly as §7.1 describes it.
        """
        with self._lock:
            principals = list(self._principals.values())
            unreadable = dict(self._unreadable)
        # §2.3 (amended 2026-09-03): each row says whether it is known to be
        # unreadable. ``readable: true`` means NOT KNOWN TO BE UNREADABLE —
        # stated that way because it is what the field can support. THE LISTING
        # NEVER PROBES: fanning one ``GET /sessions`` into one bridge call per
        # session is a list route nobody would call. The mark is written only
        # where a real call for that session failed after re-adoption
        # (:meth:`_refuse_by_name`) and cleared where one succeeded.
        return [
            {
                "session_id": p.session_id,
                "profile": p.profile,
                "part": p.part,
                "readable": p.session_id not in unreadable,
                "unreadable_reason": unreadable.get(p.session_id),
            }
            for p in principals
        ]

    def prompt(
        self,
        session_id: str,
        text: str,
        *,
        run_id: str | None = None,
        context: str | None = None,
        answerer: AskUserAnswerer | None = None,
        on_event: EventCallback | None = None,
        timeout: float | None = None,
    ) -> PromptResult:
        """Run one prompt turn; stream normalized events; return its outcome.

        Pass ``run_id`` (from :meth:`new_run_id`) when the caller needs the id
        before the call blocks — that is what makes mid-run cancellation possible.

        Refuses :class:`~.sessions.RunInFlightError` when a turn is already live
        where this one would have to run (``INTERFACE.md`` §7A.5) — see
        :meth:`_admit_turn` for which two conditions that is and why the reason
        is not ``session_busy``.

        ``context`` is the workspace's composed context block (``INTERFACE.md``
        §7A.3/§7A.4, §19.22). It is **forwarded to the sidecar and never bound**:
        :func:`bind_run_request_text` below receives ``text`` alone, so
        ``VALIDATION.md`` §4's ``prompt_number_diff`` keeps diffing the
        operator's own words against the built geometry. Prepending the block to
        ``text`` instead would put the build's own extents into "the request" and
        every one of them would come back ``matched: true`` **against itself** —
        the rung that exists to catch a design that does not meet its brief would
        be measuring the workspace's own context block.
        """
        run_id = run_id or self.new_run_id()
        run = _Run(run_id=run_id, session_id=session_id, on_event=on_event)
        self._admit_turn(run, answerer)
        # Everything from here is inside the ``finally`` that un-registers the
        # run. It has to be: with the §7A.5 guard in place, a turn that leaked
        # its ``_runs`` entry on a failed admission would refuse the session's
        # every later turn ``run_in_flight`` for the life of the process.
        try:
            # VALIDATION.md §4/§5: the prompt IS the request every validation rung
            # judges against, so it is bound here — the only place that sees it —
            # rather than asked for later from a model that has already
            # paraphrased it. INTERFACE.md §7A.4/§19.23: bound to the RUN, not to
            # the ops object. One field on CadOps was shared by every session, so
            # a second concurrent turn clobbered the first and session A's build
            # was critiqued against session B's prompt. Delegated child prompts
            # never pass through this method; they inherit the parent run's text
            # at the dispatcher, so a part agent's build is still critiqued
            # against the original.
            bind_run_request_text(run_id, text)
            self._admission.admit_run(run_id)
            self._sup.track_run(run_id)
            params: dict[str, Any] = {
                "session_id": session_id,
                "run_id": run_id,
                "prompt": text,
            }
            if context is not None:
                # Present only when there is one, so an unmodified sidecar sees
                # the params it always saw and a turn with no workspace context
                # is byte-identical on the wire to one from before this change.
                params["context"] = context
            # Through the self-healing path (§2.8(6)): a prompt for a session
            # the current child has forgotten is re-adopted and re-sent once,
            # rather than refusing a turn whose transcript is intact. The retry
            # is safe for the same reason the read's is — the sidecar refused the
            # frame before running anything, so nothing is re-run.
            result = self._call_for_session(
                "session.prompt", params, session_id=session_id, timeout=timeout
            )
            status = str(result.get("status", "completed"))
        finally:
            release_run_request_text(run_id)
            with self._lock:
                self._answerers.pop(run_id, None)
                self._runs.pop(run_id, None)
        return PromptResult(run_id=run_id, status=status, events=run.events, terminal=run.terminal)

    def _admit_turn(self, run: _Run, answerer: AskUserAnswerer | None) -> None:
        """Register a turn, or refuse it ``run_in_flight`` (``INTERFACE.md`` §7A.5).

        Two conditions, one reason, told apart by ``scope``:

        * ``run_id`` — **this run id is already live**, anywhere under the
          runtime. Its request text is bound by run, so a second live turn on one
          id is exactly "the binding cannot be honoured": one key, two requests.
          Before this guard ``_runs[run_id]`` was silently overwritten and the
          first turn's events were routed to the second turn's buffer.
        * ``session`` — **this session already has a live turn.** Two interleaved
          turns on one Pi JSONL is the condition §2.1's lease design exists to
          prevent, and nothing refused it: ``manager.ts`` guards run-id
          uniqueness only.

        §7A.5 scoped the guard project-wide *until* §19.23 bound request text to
        the run, "then narrows to per-session and ``run_in_flight`` keeps its
        meaning — the scope changes, the vocabulary does not". §19.23 is this
        change, so the session clause is per session: a part session and the
        orchestrator may now think at the same time, which is what §7.1's nested
        tabs render and what the interim restriction cost.

        Not ``session_busy``: that means a foreign lease holder owns the session
        (§2.1), a different fact with a different remedy.
        """
        with self._lock:
            live = self._runs.get(run.run_id)
            if live is not None:
                raise RunInFlightError(live.session_id, live.run_id, scope="run_id")
            for other in self._runs.values():
                if other.session_id == run.session_id:
                    raise RunInFlightError(other.session_id, other.run_id, scope="session")
            self._runs[run.run_id] = run
            self._bind_run_session(run.run_id, run.session_id)
            if answerer is not None:
                self._answerers[run.run_id] = answerer

    def _bind_run_session(self, run_id: str, session_id: str) -> None:
        """Remember which session a run belongs to (caller holds ``_lock``)."""
        self._run_sessions[run_id] = session_id
        self._run_sessions.move_to_end(run_id)
        while len(self._run_sessions) > _RUN_SESSION_BINDINGS_MAX:
            self._run_sessions.popitem(last=False)

    def cancel(self, run_id: str) -> None:
        """Request cancellation of a run (aborts only its stream + tool children).

        Safe to call from daemon threads at any time: after :meth:`close` it
        is a quiet no-op instead of a write through a closed store.
        """
        with self._teardown_lock:
            if self._closed:
                return
            self._admission.request_cancel(run_id)
        self._sup.notify("cancel", {"run_id": run_id})

    def history_page(
        self, session_id: str, cursor: str | None = None, after: str | None = None
    ) -> dict[str, Any]:
        """Fetch one normalized, high-water-frozen page of a session's history.

        A **passthrough** in both directions (§2.8): the opaque token is
        forwarded and returned unmodified and is never decoded on this side, and
        every key the sidecar answers with — including the ``user_prompts`` and
        ``end_cursor`` the 2026-09-03 amendment adds — flows through untouched.

        ``after`` is §2.8(5)'s tail read: freeze a new mark now and start at the
        ordinal the token names, so a client that already holds a walked prefix
        can read what was recorded since instead of re-walking the session.
        Forwarded only when present, so an older staged sidecar sees the params
        it always saw. Both together is refused at the HTTP boundary
        (``invalid_cursor``, §2.4) rather than here, where one would silently win.
        """
        params: dict[str, Any] = {"session_id": session_id}
        if cursor is not None:
            params["cursor"] = cursor
        if after is not None:
            params["after"] = after
        return self._call_for_session("history.page", params, session_id=session_id)

    # -- py.* request handling (sidecar -> python) -------------------------

    def _on_py_request(self, method: str, params: dict[str, Any]) -> Any:
        if method == "py.tool_dispatch":
            return self._handle_tool_dispatch(params)
        if method == "py.ask_user":
            return self._handle_ask_user(params)
        if method == "py.admission_capacity":
            return {"capacity": self._admission.capacity()}
        if method == "py.delegate":
            # Delegation is owned by the delegation coordinator; the runtime-core
            # slice rejects rather than fabricating a child.
            return {"status": "rejected", "reason": "no_run_slot", "part_session_id": None}
        raise ProtocolError(ErrorCode.METHOD_NOT_FOUND, f"unhandled py request: {method}")

    def _handle_tool_dispatch(self, params: dict[str, Any]) -> Any:
        session_id = str(params.get("session_id", ""))
        with self._lock:
            principal = self._principals.get(session_id)
        if principal is None:
            raise DispatchError(
                "session_busy", f"unknown session {session_id!r}", code=ErrorCode.INVALID_PARAMS
            )
        return self._dispatcher.dispatch(principal, params)

    def _handle_ask_user(self, params: dict[str, Any]) -> Any:
        """Ask, then record the answer against the ledger (``VALIDATION.md`` §3).

        A question naming ``requirement_ids`` is a *clarification*: its shape is
        enforced before anyone is asked (2-4 options, each stating its geometric
        consequence), and the answer is written back to those entries by the
        runtime — a committal answer as ``resolution``, a declined or
        non-committal one as ``asked: true`` only, leaving the entry assumed and
        unconfirmed for the §5 review. Neither half depends on the model choosing
        to call ``update_requirement`` afterwards, and neither half is reachable
        that way: both fields are refused on model-facing ledger writes.
        """
        run_id = str(params.get("run_id", ""))
        refusal = question_refusal(params)
        if refusal is not None:
            return refusal
        with self._lock:
            answerer = self._answerers.get(run_id) or self._default_answerer
        if answerer is None:
            raise ProtocolError(
                ErrorCode.INVALID_PARAMS, "no ask_user answerer configured for this run"
            )
        selection = answerer(params)
        recorded = record_answers(self._cad, run_id, params, cast("JSONValue", selection))
        if not recorded:
            return {"selection": selection}
        return {"selection": selection, "recorded": recorded}

    # -- notifications (sidecar -> python) ---------------------------------

    def _on_notification(self, method: str, params: dict[str, Any]) -> None:
        # The pump owns the bounded client queues and the durable terminal
        # channel; the per-run buffers below serve the synchronous prompt caller.
        self._pump.on_notification(method, params)
        if method == "event":
            self._on_event(params)
        elif method == "terminal":
            self._on_terminal(params)

    def _on_event(self, params: dict[str, Any]) -> None:
        run_id = str(params.get("run_id", ""))
        with self._lock:
            run = self._runs.get(run_id)
        if run is None:
            return
        run.events.append(params)
        if run.on_event is not None:
            run.on_event(params)

    def _on_terminal(self, params: dict[str, Any]) -> None:
        """Record the terminal for the synchronous caller (the pump made it durable)."""
        run_id = str(params.get("run_id", ""))
        self._sup.untrack_run(run_id)
        with self._lock:
            run = self._runs.get(run_id)
            if run is not None:
                run.terminal = dict(params)

    def _ack_terminal(self, run_id: str, terminal_id: str) -> None:
        """Pump callback: the terminal is durable — name it back to the sidecar."""
        self._sup.notify("terminal.ack", {"run_id": run_id, "terminal_id": terminal_id})

    def _backpressure_cancel(self, run_id: str) -> None:
        """Pump callback: a client queue overflowed past coalescing — cancel the run."""
        self._sup.notify("cancel", {"run_id": run_id})

    def _on_process_loss(self, event: ProcessLossEvent) -> None:
        """Mark generic tracked runs interrupted when the sidecar is lost."""
        for run_id in event.tracked_run_ids:
            existing = self._admission.get_terminal(run_id)
            if existing is not None:
                continue
            try:
                self._admission.ingest_terminal(
                    run_id,
                    f"interrupted:{run_id}",
                    TerminalState.INTERRUPTED,
                    {"reason": "interrupted"},
                )
                self._admission.acknowledge(run_id, f"interrupted:{run_id}")
            except Exception:
                continue
