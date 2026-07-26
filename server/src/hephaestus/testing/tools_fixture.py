"""Shared tmp-project + dispatcher helpers for the per-tool dispatch tests.

A real Hephaestus project (manifest, ``globals.py`` with a bounded project
parameter, two parts that consume it, an empty ``checks/``) over a real opstore,
driven through the real :class:`~hephaestus.agent_bridge.dispatch.ToolDispatcher`
with the **unsafe local backend** (no OS sandbox) so builds are fast.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hephaestus.agent_bridge.cad_ops import CadOps
from hephaestus.agent_bridge.dispatch import Principal, ToolDispatcher
from hephaestus.core.project_store.layout import ProjectLayout, load_project, open_store
from hephaestus.core.project_store.store import ProjectStore

from opstore import OpStore

GLOBALS_SRC = """PARAMS = {
    "wall": Param(2.0, min=1.0, max=6.0),
}

SHELF_W = 100.0
"""

WIDGET_SRC = """PARAMS = {
    "width": Param(40.0, min=10.0, max=80.0),
}

body = Box(p.width, 20.0, hc.wall)
body.label = "widget_body"
part.geometry = body

CHECKS = {
    "wide_enough": lambda m: m.bbox("part")[0] >= 10.0,
}
"""

BRACKET_SRC = """body = Box(10.0, 10.0, hc.wall)
body.label = "bracket_body"
part.geometry = body
"""

BROKEN_SRC = """body = Box(10.0, 10.0, 0.0)
part.geometry = body
"""

ORCH = Principal(session_id="orch", profile="orchestrator", part=None)
PART_WIDGET = Principal(session_id="pw", profile="part", part="widget")
QUICK_WIDGET = Principal(session_id="qw", profile="quick_edit", part="widget")


@dataclass
class Project:
    """One scaffolded project plus the dispatcher under test."""

    root: Path
    layout: ProjectLayout
    store: OpStore
    cad: CadOps
    dispatcher: ToolDispatcher
    _n: list[int]

    def call(
        self,
        tool: str,
        arguments: dict[str, Any],
        *,
        principal: Principal = ORCH,
        entry: str | None = None,
        run_id: str = "run-1",
    ) -> Any:
        """Dispatch one tool call with a fresh (or explicitly reused) invocation."""
        self._n[0] += 1
        return self.dispatcher.dispatch(
            principal,
            {
                "session_id": principal.session_id,
                "run_id": run_id,
                "tool": tool,
                "arguments": arguments,
                "invocation": {
                    "session_id": principal.session_id,
                    "entry_id": entry or f"entry-{self._n[0]}",
                    "ordinal": 1,
                    "provider_call_id": "call_0",
                },
            },
        )

    def build(self, *parts: str) -> dict[str, Any]:
        return {name: self.call("build_part", {"name": name}) for name in parts}

    def close(self) -> None:
        self.store.close()


def scaffold(root: Path, *, broken: bool = False) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "parts").mkdir(exist_ok=True)
    (root / "checks").mkdir(exist_ok=True)
    (root / "hephaestus.toml").write_text('[project]\nname = "tools"\n', encoding="utf-8")
    (root / "globals.py").write_text(GLOBALS_SRC, encoding="utf-8")
    (root / "parts" / "widget.py").write_text(WIDGET_SRC, encoding="utf-8")
    (root / "parts" / "bracket.py").write_text(BRACKET_SRC, encoding="utf-8")
    if broken:
        (root / "parts" / "broken.py").write_text(BROKEN_SRC, encoding="utf-8")
    return root


def make_project(
    root: Path,
    *,
    broken: bool = False,
    delegation: Any = None,
    delegation_runner: Any = None,
    snapshot_caller: Any = None,
    seed_ledger: bool = True,
) -> Project:
    """A scaffolded project + dispatcher, ready to build.

    ``seed_ledger`` records the one-entry minimal ledger
    (:func:`hephaestus.testing.ledger.seed_minimal_ledger`) because
    ``VALIDATION.md`` §2 is enforced by rule: an empty ledger refuses every
    ``build_part`` (``reason: "no_ledger"``). Almost every test here builds
    geometry to get at something *downstream* of the build, and for those the
    ledger is a precondition, not a subject — the entry is ``source:"specified"``
    so it can never trip §3's clarification gate either.

    Pass ``seed_ledger=False`` in the tests whose subject *is* the ledger or the
    gate: they need to see the project's real initial state (no ledger at all).
    """
    scaffold(root, broken=broken)
    layout = load_project(root)
    store = open_store(layout)
    cad = CadOps(layout, store)
    dispatcher = ToolDispatcher(
        ProjectStore(layout, store),
        cad=cad,
        delegation=delegation,
        delegation_runner=delegation_runner,
        snapshot_caller=snapshot_caller,
    )
    if seed_ledger:
        from hephaestus.testing.ledger import seed_minimal_ledger

        seed_minimal_ledger(cad)
    return Project(root=root, layout=layout, store=store, cad=cad, dispatcher=dispatcher, _n=[0])
