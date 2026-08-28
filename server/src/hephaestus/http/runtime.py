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
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, cast

from hephaestus.agent_bridge.admission import open_project_store
from hephaestus.agent_bridge.cad_ops import CadOps
from hephaestus.agent_bridge.dispatch import Principal, ToolDispatcher
from hephaestus.agent_bridge.session_edges import SessionEdgeStore
from hephaestus.core.executor.sandbox.base import ExecBackend
from hephaestus.core.executor.sandbox.probe import refuse_unsafe, secure_backend
from hephaestus.core.project_store.layout import ProjectLayout, load_project
from hephaestus.core.project_store.store import ProjectStore

from opstore import OpStore

from .git_projection import is_work_tree
from .idempotency import RestLedger
from .principal import WORKSPACE_PROFILE, WorkspacePrincipal, token_id
from .sessions import SessionBackend, WorkspaceSessions

__all__ = ["WorkspaceRuntime"]

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
    #: The attached agent runtime, or ``None``. Held so a manifest reload can
    #: re-point it at the same objects the routes now use.
    session_backend: SessionBackend | None = None
    #: The §2.7/§2.8 session layer, present once an agent runtime is attached.
    #: ``None`` is a *named* state, not a half-built one: a serve with no
    #: provider config has no sidecar to drive, and the session routes refuse by
    #: name (``agent_unavailable``) rather than pretending to have sessions.
    sessions: WorkspaceSessions | None = None

    @classmethod
    def open(
        cls,
        root: Path,
        *,
        token: str,
        serve_mode: bool = True,
        backend: ExecBackend | None = None,
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
        return cls(
            root=resolved,
            layout=layout,
            store=store,
            project_store=project_store,
            cad=cad,
            dispatcher=ToolDispatcher(project_store, cad=cad),
            ledger=RestLedger(store),
            edges=SessionEdgeStore(store.db),
            backend=exec_backend,
            token=token,
            serve_mode=serve_mode,
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
        """
        self.session_backend = backend
        self.sessions = WorkspaceSessions(backend, self.edges)
        return self.sessions

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

    def capabilities(self) -> dict[str, bool]:
        """The closed ``GET /project`` capability map (see ``CAPABILITY_KEYS``)."""
        return {
            "secure_executor": self._secure_executor_available(),
            "git": is_work_tree(self.root),
        }

    def _secure_executor_available(self) -> bool:
        try:
            secure_backend(self.layout.store_root)
        except Exception:
            return False
        return True

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
        row = self.store.db.conn.execute(
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
        self.dispatcher = ToolDispatcher(self.project_store, cad=self.cad)
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
        self.store.close()


def _backend_for(layout: ProjectLayout, serve_mode: bool) -> ExecBackend:
    if serve_mode:
        return secure_backend(layout.store_root)
    from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend

    return UnsafeLocalBackend()
