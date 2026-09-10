# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""The serving process's one open project (``INTERFACE.md`` §2.1, §2.2).

**One process owns the leases.** ``heph serve --web`` opens exactly one project
and holds its ``.heph/locks/`` session leases; ``heph agent`` reads
``serve.json`` and attaches as a client rather than opening a second in-process
bridge. That is why this class binds a *single* root instead of the MCP app's
session→project map: there is no per-connection project binding to make, because
the process is the binding.

Everything below the boundary is the code the Pi bridge and the MCP server
already use — the same :class:`~hephaestus.agent_bridge.dispatch.ToolDispatcher`
over the same :class:`~hephaestus.agent_bridge.cad_ops.CadOps` over the same
project store, opened through the same
:func:`~hephaestus.agent_bridge.admission.open_project_store`. Mission rule 6 is
not a slogan here: this module constructs, and constructs nothing new.

**Executor policy.** ``--web`` forces ``serve_mode=True`` exactly as ``--mcp``
does, so builds run on a probed secure backend and an injected unsafe backend is
refused up front. The web never has an unsandboxed path.
"""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, cast

from hephaestus.agent_bridge.admission import open_project_store
from hephaestus.agent_bridge.cad_ops import CadOps
from hephaestus.agent_bridge.dispatch import Principal, ToolDispatcher
from hephaestus.agent_bridge.session_edges import SessionEdgeStore
from hephaestus.agent_bridge.wiring import build_dispatcher
from hephaestus.core.errors import ValidationError
from hephaestus.core.executor.sandbox.base import ExecBackend
from hephaestus.core.executor.sandbox.probe import refuse_unsafe, secure_backend
from hephaestus.core.project_store.layout import ProjectLayout, load_project
from hephaestus.core.project_store.store import ProjectStore

from opstore import OpStore

from .agent_attach import (
    DETACHED_CAUSE,
    AgentAlreadyAttached,
    AgentAttachState,
    AttachRefused,
    provider_config_path,
    start_agent_runtime,
)
from .agent_credentials import CredentialBackend
from .errors import HttpRefusal
from .git_projection import is_work_tree
from .idempotency import RestLedger
from .principal import WORKSPACE_PROFILE, WorkspacePrincipal, token_id
from .providers import DiscoveryRegistry
from .sessions import SessionBackend, WorkspaceSessions

if TYPE_CHECKING:  # pragma: no cover - typing only
    from hephaestus.agent_bridge.app import BridgeRuntime

__all__ = [
    "CAPABILITY_TTL_SECONDS",
    "PART_FILENAME_MAX_BYTES",
    "WorkspaceRuntime",
    "resolve_part",
]

#: How long a computed capability map may be re-served without re-probing
#: (audit-2026-09-04 J-http-limits-7). The probe fails **open** by design — it
#: caches only successes, so installing bubblewrap later is picked up without a
#: restart — and that is right for a build about to run and wrong for a
#: projection the web client polls: with a `bwrap` that stalls, two consecutive
#: `GET /project` calls cost 25.035 s and 25.034 s, because the failure was
#: re-probed every time. The cache lives HERE rather than inside the probe for
#: exactly that reason: the probe's policy is correct for its own callers, and
#: this is a different question asked on a different cadence.
#:
#: Five seconds is short enough that an operator who installs bubblewrap and
#: reloads sees it, and long enough that a page load's worth of requests pays
#: for one probe. :meth:`WorkspaceRuntime.capabilities` takes ``refresh=True``
#: for the caller that must not be served a stale answer, and attach, detach and
#: a manifest reload invalidate it outright.
CAPABILITY_TTL_SECONDS: Final[float] = 5.0

#: The longest ``parts/<name>.py`` this server will address. ``NAME_MAX`` on
#: every filesystem this project runs on (ext4, xfs, btrfs, apfs, ntfs) is 255
#: bytes, so a longer name cannot name a file and is therefore not a part name —
#: a fact the store's identifier *pattern* does not cover, because it bounds the
#: alphabet and not the length. See :func:`resolve_part`.
PART_FILENAME_MAX_BYTES: Final[int] = 255

_DFM_TABLE: Final[str] = "http_dfm_last"
_CREATE_DFM_TABLE: Final[str] = f"""
CREATE TABLE IF NOT EXISTS {_DFM_TABLE}(
  part TEXT PRIMARY KEY,
  payload TEXT NOT NULL,
  recorded_at REAL NOT NULL)
"""


@dataclass
class WorkspaceRuntime:
    """One open project plus the machinery every route rides.

    Construct with :meth:`open`; close with :meth:`close`.
    """

    root: Path
    layout: ProjectLayout
    store: OpStore
    project_store: ProjectStore
    cad: CadOps
    dispatcher: ToolDispatcher
    ledger: RestLedger
    edges: SessionEdgeStore
    backend: ExecBackend
    token: str
    serve_mode: bool
    #: The host this serve is BOUND to, so §23.6's route-level ``not_loopback``
    #: precondition has something to check. §15.6 already makes the serve
    #: loopback-only and ``serve.py`` has no flag that could change it; the
    #: field exists because §23 re-checks the fact **at the route** on the §2.6
    #: pattern rather than inheriting it, and a precondition with nothing behind
    #: it is a comment. Defaulted to loopback so an in-process harness — which
    #: binds no socket at all — is not accidentally off-loopback.
    bind_host: str = "127.0.0.1"
    #: The attached agent runtime, or ``None``. Held so a manifest reload can
    #: re-point it at the same objects the routes now use.
    session_backend: SessionBackend | None = None
    #: The §2.7/§2.8 session layer, present once an agent runtime is attached.
    #: ``None`` is a *named* state, not a half-built one: a serve with no
    #: provider config has no sidecar to drive, and the session routes refuse by
    #: name (``agent_unavailable``) rather than pretending to have sessions.
    sessions: WorkspaceSessions | None = None
    #: The :class:`~hephaestus.agent_bridge.app.BridgeRuntime` **this process
    #: spawned**, when it spawned one. Held separately from ``session_backend``
    #: because that one is a Protocol with no lifecycle: only an agent runtime
    #: we started is ours to close, and :meth:`detach_agent` closes exactly it.
    agent: BridgeRuntime | None = None
    #: The §23 credential backend, when the attached session backend is also
    #: one. Separate from ``agent`` because §23.0's third row is about a
    #: *capability* — "Pi is the credential store" — not about who spawned the
    #: process: an in-process harness may drive the credential routes without a
    #: sidecar, and a session backend that is not a credential store must leave
    #: those routes refusing ``agent_unavailable`` by name.
    credentials: CredentialBackend | None = None
    #: Whether this process has an agent runtime and — if not — why, from
    #: :data:`~hephaestus.http.agent_attach.ATTACH_CAUSES` (§7A.8, §23.0).
    #: ``None`` until something attempts an attach: a serve always does, at
    #: start-up, so "no attempt has been made" is a state only an in-process
    #: harness can be in, and it is reported as an absent cause rather than as a
    #: guessed one.
    attach_state: AgentAttachState | None = None
    #: Serializes attach against detach. Both mutate four fields together, and
    #: two browser tabs racing the same button must not half-attach a serve.
    _attach_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    #: The one thread sidecars are spawned on; see :meth:`spawn_executor`.
    #: Created on first use, because a serve that never attaches never needs it.
    _spawn_pool: ThreadPoolExecutor | None = field(default=None, repr=False)
    #: The live §23.5 discovery offers. Per-runtime rather than module-level so
    #: two serves in one test process cannot adopt each other's handles.
    discoveries: DiscoveryRegistry = field(default_factory=DiscoveryRegistry, repr=False)
    #: The §2.3 capability map and the moment it was computed, or ``None``.
    #: See :data:`CAPABILITY_TTL_SECONDS` for why this is cached at all.
    _capabilities: tuple[float, dict[str, bool]] | None = field(default=None, repr=False)

    @classmethod
    def open(
        cls,
        root: Path,
        *,
        token: str,
        serve_mode: bool = True,
        backend: ExecBackend | None = None,
        bind_host: str = "127.0.0.1",
    ) -> WorkspaceRuntime:
        """Open ``root`` for serving under ``token``.

        An injected unsafe backend is refused under ``serve_mode`` before any of
        it is used — the same guard ``mcp/app.py`` applies, for the same reason:
        ``heph serve`` has no ``--unsafe-local-executor`` flag and must not
        acquire one by injection.
        """
        if serve_mode and backend is not None and getattr(backend, "unsafe", False):
            refuse_unsafe(registry_content=False, serve=True)
        resolved = Path(root).expanduser().resolve()
        layout = load_project(resolved)
        store = open_project_store(layout)
        store.db.conn.execute(_CREATE_DFM_TABLE)
        exec_backend = backend if backend is not None else _backend_for(layout, serve_mode)
        cad = CadOps(layout, store, backend=exec_backend)
        # ONE ``ProjectStore``, shared by the read routes and the dispatcher: each
        # instance builds its own ``LockManager`` with its own owner id, and two
        # owners inside one process would be two writers on one project's locks —
        # the very thing §2.1's "one process owns the leases" exists to prevent.
        # ``mcp/app.py`` shares one for the same reason.
        project_store = ProjectStore(layout, store)
        # ONE edge store too, shared by the thread projection and the delegation
        # WAL that WRITES the edges (§2.8): the row is recorded at the PREPARED
        # transition inside the dispatcher's delegation service, so the panel
        # and the writer must be looking at the same table handle.
        edges = SessionEdgeStore(store.db)
        return cls(
            root=resolved,
            layout=layout,
            store=store,
            project_store=project_store,
            cad=cad,
            # B-2: the capability set is resolved in ONE place for every shipped
            # runtime (``agent_bridge/wiring.py``). This serve is the process
            # that owns the project's leases (§2.1) and now its registry set as
            # well; ``exec_backend`` is the probed secure backend under
            # ``serve_mode``, which is what lets ``instance_store_part`` run a
            # store generator here at all.
            dispatcher=build_dispatcher(
                layout, store, project_store, cad, backend=exec_backend, edges=edges
            ),
            ledger=RestLedger(store),
            edges=edges,
            backend=exec_backend,
            token=token,
            serve_mode=serve_mode,
            bind_host=bind_host,
        )

    # -- the agent runtime -------------------------------------------------

    def attach_sessions(self, backend: SessionBackend) -> WorkspaceSessions:
        """Bind the one agent runtime this process owns (§2.1, §2.7).

        The backend is expected to have been constructed **over this runtime's
        store, project store, CadOps and dispatcher** — ``BridgeRuntime`` takes
        all four as injections for exactly this caller. Two opstore handles in
        one process would be two ``LockManager`` owners over one project's
        ``.heph/locks/``, which is the thing §2.1's "one process owns the leases"
        exists to prevent.

        This is the **binding** half of attach, and it is the only one: both
        :meth:`attach_agent` and the test harness that drives the HTTP layer
        without a sidecar come through here, so "the session routes are live"
        means one thing in this process.
        """
        self.session_backend = backend
        self.credentials = backend if isinstance(backend, CredentialBackend) else None
        self.sessions = WorkspaceSessions(backend, self.edges)
        previous = 0 if self.attach_state is None else self.attach_state.generation
        self.attach_state = AgentAttachState(
            attached=True,
            config_path=str(provider_config_path(self.root)),
            generation=previous + 1,
        )
        return self.sessions

    def attach_agent(
        self, *, config_path: Path | None = None, dist_main: Path | None = None
    ) -> AgentAttachState:
        """Start a sidecar **now** and put the session routes into service (§23.0).

        The capability §23.14 names first, because without it §23 could not be
        used in the only state it exists to fix: with no ``providers.json`` there
        was no ``BridgeRuntime``, no ``Supervisor`` and no sidecar, so every
        credential route — each one a relay to the sidecar — refused, and nothing
        in the process could make one exist. ``heph serve --web`` calls this at
        start-up and ``POST /providers/attach`` calls it later; they are the same
        call, which is what stops the post-hoc path from drifting away from the
        one the gates exercise.

        Refuses :class:`AgentAlreadyAttached` rather than replacing a live
        runtime (§23.7 makes a replacement an explicit, confirmed act because it
        kills every in-flight run), and :class:`AttachRefused` — named cause,
        checked path, redacted detail — for everything else. **A refusal leaves
        this runtime exactly as it was**: the binding happens only after the
        sidecar has started and answered ``runtime.configure``.
        """
        with self._attach_lock:
            if self.sessions is not None:
                raise AgentAlreadyAttached(
                    "this server already has an agent runtime attached; "
                    "detach it before attaching another"
                )
            resolved = provider_config_path(self.root) if config_path is None else config_path
            try:
                bridge = start_agent_runtime(self, config_path=resolved, dist_main=dist_main)
            except AttachRefused as exc:
                # The prior state, re-recorded with the reason it is still the
                # prior state. Nothing else changed, so nothing else is written.
                self.attach_state = exc.state(generation=self._attach_generation())
                raise
            self.agent = bridge
            self.attach_sessions(bridge)
            self._invalidate_capabilities()
            state = self.attach_state
            if state is None:  # pragma: no cover - attach_sessions always records one
                raise RuntimeError("attach bound a session backend without recording a state")
            return state

    def detach_agent(self) -> AgentAttachState:
        """Tear the agent runtime down and return the session routes to refusing.

        Idempotent, and honest in both directions: with nothing attached this
        reports the state the serve is already in rather than inventing a
        transition, and after a real detach the session routes refuse
        ``agent_unavailable`` with cause ``detached`` — not with the cause the
        serve started under, which is no longer true.

        Closing the sidecar is what makes detach a *state* rather than a label:
        ``BridgeRuntime.close`` shuts the supervisor down (no orphan) and leaves
        the injected opstore alone, because that one belongs to this runtime.

        **Honest limit, stated rather than papered over:** a ``GET /events``
        socket already open when this runs is not closed here — it holds its own
        reference to the session layer and simply stops receiving. Its next
        request on any session route refuses ``agent_unavailable`` by name, and
        §2.7 already makes a silent stream a client-side resync condition rather
        than a promise. Closing live sockets on detach needs a socket registry
        the session layer does not have, and inventing half of one here would be
        a second observer-ownership mechanism (§2.7).
        """
        with self._attach_lock:
            sessions, agent = self.sessions, self.agent
            if sessions is None and agent is None and self.attach_state is not None:
                # Already detached (or never attached). Reporting the state that
                # is actually true beats overwriting a `no_provider_config` with
                # a `detached` that never happened.
                return self.attach_state
            self.sessions = None
            self.session_backend = None
            self.credentials = None
            self.agent = None
            if sessions is not None:
                # Suspended `ask_user` calls are released before the process
                # they were waiting on goes away, so each fails honestly instead
                # of hanging on a runtime that no longer exists (§2.7).
                sessions.close()
            if agent is not None:
                agent.close()
            detached_something = sessions is not None or agent is not None
            self.attach_state = AgentAttachState(
                attached=False,
                config_path=str(provider_config_path(self.root)),
                cause=DETACHED_CAUSE,
                detail=(
                    "the agent runtime was detached from this server"
                    if detached_something
                    else "no agent runtime is attached to this server"
                ),
                generation=self._attach_generation(),
            )
            self._invalidate_capabilities()
            return self.attach_state

    def spawn_executor(self) -> ThreadPoolExecutor:
        """The **one** thread every sidecar spawn happens on, for its lifetime.

        BLOCKING FINDING, found by the orphan assertion and fixed here rather
        than worked around in the test. ``Supervisor`` makes the sidecar
        orphan-free on Linux with ``PR_SET_PDEATHSIG=SIGKILL``, and that signal
        is delivered when the **spawning thread** exits — not when the process
        does. That was invisible while the only spawn happened on the main
        thread during ``serve`` start-up. §23.0's attach happens on a *request*,
        and ``asyncio.to_thread`` hands it whichever pooled worker is free: the
        sidecar then died the moment that worker did, which reads to an operator
        as a runtime that attached and then silently vanished.

        So every spawn goes through one dedicated worker that lives as long as
        this runtime, which is exactly the lifetime the death signal is supposed
        to mean. ``max_workers=1`` is not throughput tuning — it *is* the
        property: two spawn threads would be two lifetimes.
        """
        if self._spawn_pool is None:
            self._spawn_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="heph-spawn")
        return self._spawn_pool

    def agent_attach_state(self) -> AgentAttachState | None:
        """The current attach state, for the surfaces that report it (§7A.8)."""
        return self.attach_state

    def invalidate_attach_state(self) -> AgentAttachState | None:
        """Recompute the no-runtime cause from disk (audit-2026-09-04 J-http-envelope-6).

        The stored state is written at exactly three places — attach, attach
        failure and detach — so a route that changes *what a future attach would
        find* left the cause describing the last attempt while presenting it as
        a fact about the present: after writing a provider configuration, the
        credential routes still refused with cause ``no_provider_config`` while
        ``GET /providers`` reported the file existed. The refusal told the
        operator to do the thing they had just done.

        Invalidate on write rather than derive on read: the cause is a fact
        about *this process's* attach history for every case except the one this
        method fixes — an unattached serve whose configuration has changed —
        and re-deriving it on every read would throw away ``sidecar_failed`` and
        ``node_missing``, which no amount of disk-reading can recover.

        **It does not attach.** §23 separates "write a config" from "attach a
        runtime" deliberately, and an implicit attach from a config write is the
        deadlock that section exists to remove. When a configuration now exists
        and nothing is attached, the honest cause is still
        ``no_provider_config``'s *sibling* condition — a config exists and no
        runtime has been attached to it — and §7A.8's closed vocabulary has no
        member for it, so the **message** carries it and the cause stays
        ``no_provider_config``. Widening a closed vocabulary needs a
        specification change, a client change and a copy string, none of which a
        bug fix may take on its own authority; the amendment is recorded in the
        lane's hand-off.

        Attached runtimes are left alone: this answers "why is there nothing
        attached", and when there *is* something attached there is no question.
        The generation counter is preserved, because it counts spawns and
        nothing here spawns.
        """
        with self._attach_lock:
            if self.sessions is not None or self.attach_state is None:
                return self.attach_state
            state = self.attach_state
            if state.attached:  # pragma: no cover - `sessions is None` implies not attached
                return state
            config_path = provider_config_path(self.root)
            if state.cause == DETACHED_CAUSE:
                # An operator's own act, not a fact about the file. Overwriting
                # it would be the mirror of the bug: `detach_agent` already
                # argues that a real cause must not be replaced by one that
                # never happened.
                return state
            self.attach_state = AgentAttachState(
                attached=False,
                config_path=str(config_path),
                cause="no_provider_config" if not config_path.is_file() else state.cause,
                detail=(
                    "no provider configuration exists at this path"
                    if not config_path.is_file()
                    else "a provider configuration exists and no runtime has been attached "
                    "to it; attach one (POST /providers/attach)"
                ),
                generation=state.generation,
            )
            return self.attach_state

    def _attach_generation(self) -> int:
        return 0 if self.attach_state is None else self.attach_state.generation

    # -- principal ---------------------------------------------------------

    def workspace_principal(self) -> WorkspacePrincipal:
        """The §2.2 principal for this serve: project root + token identity."""
        return WorkspacePrincipal(project_root=self.root, token_id=token_id(self.token))

    def dispatch_principal(self) -> Principal:
        """The dispatch principal every tool route goes through — no bypass.

        ``profile="orchestrator"`` mirrors ``mcp/app.py``'s ``_MCP_PROFILE``: a
        local operator with the project open is orchestrator-equivalent.
        Dispatch's own object-scope and reviewer rules apply unchanged and the
        HTTP layer adds no authz of its own beyond the token. Sessions spawned
        *from* the workspace (quick edit) keep their own profile and their own
        ``Principal``; this one is never lent to them.
        """
        return Principal(
            session_id=self.workspace_principal().session_id,
            profile=WORKSPACE_PROFILE,
            part=None,
        )

    # -- capabilities ------------------------------------------------------

    def capabilities(self, *, refresh: bool = False) -> dict[str, bool]:
        """The closed ``GET /project`` capability map (see ``CAPABILITY_KEYS``).

        **Both members spawn a subprocess**, which is why this is cached and why
        every caller runs it off the event loop (audit-2026-09-04 J-http-limits-6
        and -7): ``secure_executor`` runs a sandbox version check and then a full
        sandboxed worker, and ``git`` shells to ``git rev-parse``. Serving the
        map from a :data:`CAPABILITY_TTL_SECONDS` window means a page load pays
        for one probe rather than one per request, and it bounds the damage a
        pathological probe can do to a client that polls this route.

        ``refresh=True`` bypasses the window for the caller that must not be
        handed a value up to five seconds old; :meth:`_invalidate_capabilities`
        drops it outright on attach, detach and a manifest reload, so a state
        change is never waited out.

        A ``git`` that exceeds :data:`~.git_projection.GIT_TIMEOUT_SECONDS` is
        reported as ``git: false`` rather than failing this call. That is the
        same discipline ``secure_executor`` already applies to a failed probe:
        the capability map answers "can this server do X **right now**", and a
        git that will not answer within the ceiling cannot. The *git routes*
        still surface ``git_timeout`` by name — a capability map is a summary,
        and a summary is the wrong place to raise.
        """
        cached = self._capabilities
        if (
            not refresh
            and cached is not None
            and time.monotonic() - cached[0] < (CAPABILITY_TTL_SECONDS)
        ):
            return dict(cached[1])
        computed = {
            "secure_executor": self._secure_executor_available(),
            "git": self._git_available(),
        }
        self._capabilities = (time.monotonic(), computed)
        return dict(computed)

    def _invalidate_capabilities(self) -> None:
        """Drop the cached map: something happened that could have changed it."""
        self._capabilities = None

    def _secure_executor_available(self) -> bool:
        try:
            secure_backend(self.layout.store_root)
        except Exception:
            return False
        return True

    def _git_available(self) -> bool:
        try:
            return is_work_tree(self.root)
        except HttpRefusal:
            # `git_timeout` — see :meth:`capabilities`. Not `GitUnavailable`,
            # which `is_work_tree` already answers `False` for.
            return False

    # -- the last DFM evaluation ------------------------------------------

    def record_dfm(self, part: str, payload: dict[str, Any]) -> None:
        """Record the projection ``GET /parts/{part}/dfm`` reports as "last".

        DEVIATION from ``INTERFACE.md`` §2.3, recorded rather than papered over:
        the row reads "last ``run_dfm`` projection + ``{auto_run, resolved_from}``",
        and **nothing in the engine stores a last ``run_dfm`` result**. ``run_dfm``
        is a pure evaluation (``cad_ops/_dfm.py``) and the auto-run variant rides
        inside a build critique; neither is durable on its own. Rather than have
        the GET route fabricate an empty finding list — which would read as "no
        DFM problems", exactly the silence-as-pass §6.4 forbids — the POST route
        records its own result here and the GET route reports it, or reports a
        named absence.
        """
        with self.store.db.transaction() as conn:
            conn.execute(
                f"INSERT OR REPLACE INTO {_DFM_TABLE}(part, payload, recorded_at) VALUES(?, ?, ?)",
                (part, json.dumps(payload, sort_keys=True, ensure_ascii=False), time.time()),
            )

    def last_dfm(self, part: str) -> dict[str, Any] | None:
        with self.store.db.reading() as conn:
            row = conn.execute(
                f"SELECT payload FROM {_DFM_TABLE} WHERE part = ?", (part,)
            ).fetchone()
        if row is None:
            return None
        loaded: Any = json.loads(str(row["payload"]))
        return cast("dict[str, Any]", loaded) if isinstance(loaded, dict) else None

    # -- project configuration --------------------------------------------

    def reload_manifest(self) -> None:
        """Re-read ``hephaestus.toml`` and rebind everything that captured it.

        ``POST /project/config/dfm`` writes ``[dfm] auto_run`` into the human's
        manifest, and ``CadOps`` reads that flag off the ``ProjectLayout`` it was
        constructed with (``cad_ops/_build.py::_auto_dfm``). Rebinding here is
        what makes the toggle a *project setting* that takes effect now rather
        than one that waits for a restart — §6.4 splits the DFM surface into an
        action and a setting precisely so the setting behaves like one.
        """
        self.layout = load_project(self.root)
        self.cad = CadOps(self.layout, self.store, backend=self.backend)
        self.project_store = ProjectStore(self.layout, self.store)
        # The same construction as :meth:`open`, so toggling a manifest flag
        # cannot silently drop the registry set (B-2). ``BridgeRuntime.
        # rebind_project`` re-binds the live-sidecar capabilities onto this new
        # dispatcher below.
        self.dispatcher = build_dispatcher(
            self.layout,
            self.store,
            self.project_store,
            self.cad,
            backend=self.backend,
            edges=self.edges,
        )
        if self.session_backend is not None:
            # The sidecar must not keep building against the pre-toggle layout:
            # the agent and the panel disagreeing about a *project setting* is
            # exactly the split §6.4 splits the DFM surface to avoid.
            self.session_backend.rebind_project(
                layout=self.layout,
                project_store=self.project_store,
                cad=self.cad,
                dispatcher=self.dispatcher,
            )

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        # The spawn thread goes last and only after :meth:`detach_agent` has
        # taken the sidecar down: its death is a SIGKILL to whatever child it
        # spawned, which is the right thing at process teardown and the wrong
        # thing at any other moment.
        pool, self._spawn_pool = self._spawn_pool, None
        if pool is not None:
            pool.shutdown(wait=True)
        self.store.close()


def resolve_part(runtime: WorkspaceRuntime, name: str) -> str:
    """``name``, or the §2.4 refusal a part-addressed route owes its caller.

    THE ONE PART RESOLVER for ``server/http`` (audit-2026-09-04 J-http-envelope-3,
    root cause RC-4). Before it, ``app.py``'s ``_part()`` returned the path
    parameter as a string and every route discovered the miss — or did not — as a
    side effect of what it happened to call: for one absent name the script route
    refused ``invalid_part``, params and properties refused ``addressing_error``,
    build answered 200 ``not_built``, checks answered 200 with the whole project
    report and the fictional name echoed into it, DFM and exports answered 200
    with empty documents, and only ``POST /context/preview`` — which checked the
    part list explicitly, in the wrong place to be shared — answered correctly.
    Three of those routes fabricated a document about a part that does not exist.

    Two rungs, and the split is §2.4's vocabulary (J-http-envelope-4/-17): a name
    that cannot be a part **at all** is ``invalid_part`` at 400, because the
    request is malformed; a well-formed name this project does not have is
    ``unknown_part`` at 404, because it is an addressing miss. The grammar is the
    store's own — :meth:`ProjectLayout.part_path` is *called*, not restated — so
    the web layer cannot drift from what the store will accept, and the check
    runs **before** the directory listing, so an 8 MB name is refused without a
    store read (J-http-limits-2).

    The known parts ride on the 404 so a client can offer them; ``error_body``
    bounds every string in that payload.
    """
    try:
        path = runtime.layout.part_path(name)
    except ValidationError as exc:
        raise HttpRefusal(
            400, "invalid_part", exc.message, data={"part": name, "field": "part"}
        ) from exc
    if len(path.name.encode("utf-8")) > PART_FILENAME_MAX_BYTES:
        # The store's identifier pattern is unbounded in length, so a name of a
        # million legal characters passed the grammar and was answered
        # `unknown_part` — a 404 about an address that can never exist, whose
        # refusal then quoted the whole megabyte back (audit-2026-09-04
        # J-http-limits-2). This is the same "is it a part name at all" question
        # the pattern asks, on the axis the pattern does not cover.
        raise HttpRefusal(
            400,
            "invalid_part",
            f"a part name may be at most {PART_FILENAME_MAX_BYTES - len('.py')} bytes",
            data={"part": name, "field": "part", "max_bytes": PART_FILENAME_MAX_BYTES},
        )
    known = runtime.project_store.list_parts()
    if name not in known:
        raise HttpRefusal(
            404,
            "unknown_part",
            f"this project has no part {name!r}",
            data={"part": name, "parts": sorted(known)},
        )
    return name


def _backend_for(layout: ProjectLayout, serve_mode: bool) -> ExecBackend:
    if serve_mode:
        return secure_backend(layout.store_root)
    from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend

    return UnsafeLocalBackend()
