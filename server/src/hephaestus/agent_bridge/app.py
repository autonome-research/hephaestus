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

import threading
import uuid
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
from .cad_ops import CadOps, question_refusal, record_answers
from .dispatch import DispatchError, Principal, ToolDispatcher
from .events import EventPump, PerClientQueue
from .protocol import ErrorCode, ProtocolError
from .sidecar import SidecarResolution, node_executable, resolve_sidecar
from .supervisor import ProcessLossEvent, Supervisor, SupervisorConfig

__all__ = [
    "AskUserAnswerer",
    "AuthLinkError",
    "BridgeRuntime",
    "EventCallback",
    "PromptResult",
    "ProviderSpec",
    "default_dist_main",
    "link_auth_source",
    "repo_root",
]

_STATE_DB_NAME = "state.db"

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
    ) -> None:
        self._layout = load_project(project_root)
        self._store = _open_project_store(self._layout)
        self._project = ProjectStore(self._layout, self._store)
        self._cad = CadOps(self._layout, self._store)
        self._dispatcher = ToolDispatcher(self._project, cad=self._cad)
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
        self._default_answerer = answerer

        self._principals: dict[str, Principal] = {}
        self._runs: dict[str, _Run] = {}
        self._answerers: dict[str, AskUserAnswerer] = {}
        self._lock = threading.RLock()

        agent_dir = agent_dir or (self._layout.store_root / "agent")
        agent_dir.mkdir(parents=True, exist_ok=True)
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
        """
        return {"providers": self._providers, "credentials": self._credentials}

    def _configure_runtime(self, sup: Supervisor) -> None:
        """Supervisor spawn hook: push ``runtime.configure`` onto a fresh child."""
        sup.call("runtime.configure", self.configure_payload)

    def start(self) -> None:
        """Spawn the sidecar (the spawn hook pushes ``runtime.configure``)."""
        self._sup.start()

    def restart(self) -> None:
        """Kill the whole sidecar and respawn it; the spawn hook re-configures.

        Generic in-flight runs are marked interrupted by the supervisor's
        recovery hook before this returns; persisted Pi sessions are re-openable
        via :meth:`resume_session`.
        """
        self._sup.restart(reason="manual")

    def close(self) -> None:
        """Graceful shutdown: close the sidecar (no orphan) and the opstore."""
        try:
            self._sup.notify("cancel", {"run_id": "*"})
        finally:
            self._sup.close()
            self._store.close()

    def __enter__(self) -> BridgeRuntime:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def child_pid(self) -> int:
        return self._sup.child_pid

    @property
    def admission(self) -> BridgeAdmission:
        return self._admission

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
        return sid

    def resume_session(self, profile: str, session_id: str, *, part: str | None = None) -> str:
        """Resume a persisted session by id after a restart."""
        return self.create_session(profile, part=part, session_id=session_id, resume=True)

    # -- prompting ---------------------------------------------------------

    def new_run_id(self) -> str:
        """Mint a stable run id (allocate it *before* prompting to cancel a run)."""
        return f"run-{uuid.uuid4().hex[:12]}"

    def client_queue(self, client_id: str) -> PerClientQueue:
        """Register a client and get its bounded, coalescing event queue."""
        return self._pump.add_client(client_id)

    def drop_client(self, client_id: str) -> None:
        self._pump.remove_client(client_id)

    def prompt(
        self,
        session_id: str,
        text: str,
        *,
        run_id: str | None = None,
        answerer: AskUserAnswerer | None = None,
        on_event: EventCallback | None = None,
        timeout: float | None = None,
    ) -> PromptResult:
        """Run one prompt turn; stream normalized events; return its outcome.

        Pass ``run_id`` (from :meth:`new_run_id`) when the caller needs the id
        before the call blocks — that is what makes mid-run cancellation possible.
        """
        run_id = run_id or self.new_run_id()
        # VALIDATION.md §4/§5: the prompt IS the request every validation rung
        # judges against, so it is bound to the ops layer here — the only place
        # that sees it — rather than asked for later from a model that has
        # already paraphrased it. Delegated child prompts never pass through
        # this method, so a part agent's build is critiqued against the original.
        self._cad.set_request_text(text)
        run = _Run(run_id=run_id, session_id=session_id, on_event=on_event)
        with self._lock:
            self._runs[run_id] = run
            if answerer is not None:
                self._answerers[run_id] = answerer
        self._admission.admit_run(run_id)
        self._sup.track_run(run_id)
        try:
            result = self._sup.call(
                "session.prompt",
                {"session_id": session_id, "run_id": run_id, "prompt": text},
                timeout=timeout,
            )
            status = str(result.get("status", "completed"))
        finally:
            with self._lock:
                self._answerers.pop(run_id, None)
                self._runs.pop(run_id, None)
        return PromptResult(run_id=run_id, status=status, events=run.events, terminal=run.terminal)

    def cancel(self, run_id: str) -> None:
        """Request cancellation of a run (aborts only its stream + tool children)."""
        self._admission.request_cancel(run_id)
        self._sup.notify("cancel", {"run_id": run_id})

    def history_page(self, session_id: str, cursor: str | None = None) -> dict[str, Any]:
        """Fetch one normalized, high-water-frozen page of a session's history."""
        params: dict[str, Any] = {"session_id": session_id}
        if cursor is not None:
            params["cursor"] = cursor
        return self._sup.call("history.page", params)

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
