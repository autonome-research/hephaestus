"""Seed the minimal requirement ledger a build now *requires* (``VALIDATION.md`` §2).

Geometry may not precede requirements: ``cad_ops.clarification_gate`` refuses
``build_part`` while the project's ledger is empty (``reason: "no_ledger"``).
That rule is what makes the ladder fire at all — measured 2026-07-26, a bench run
reported ``compelled=0`` on every run because nothing compelled the ledger to
exist — but it also means every test whose *subject* is downstream of the build
(the post-build critique, the review context, the reviewer's tool surface) has to
satisfy the precondition first.

This helper is that precondition and nothing more: **one** ``source:"specified"``
entry with a quote, so it can never gate (§3 gates only *assumed* entries) and
never changes what the test under it is measuring. A test that is *about* the
ledger writes its own entries instead.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

from hephaestus.agent_bridge.cad_ops import LedgerState
from hephaestus.agent_bridge.cad_ops._requirements import RequirementOps

__all__ = ["MINIMAL_LEDGER_ENTRY", "seed_minimal_ledger", "seed_minimal_ledger_at"]

#: The one entry: traceable to a phrase of the request, so §3 never gates on it.
MINIMAL_LEDGER_ENTRY: Final[dict[str, Any]] = {
    "id": "R0",
    "text": "the part is built as the request describes it",
    "source": "specified",
    "quote": "build the part",
}


def seed_minimal_ledger(
    project: RequirementOps | Any,
    *,
    op_id: str = "seed-minimal-ledger",
) -> LedgerState:
    """Record :data:`MINIMAL_LEDGER_ENTRY` so ``build_part`` is not refused.

    Accepts either a :class:`~hephaestus.agent_bridge.cad_ops.CadOps` (any
    ``RequirementOps``) or a fixture object carrying one as ``.cad``, so the
    call site reads the same in both test styles.
    """
    cad = getattr(project, "cad", project)
    if not isinstance(cad, RequirementOps):  # pragma: no cover - misuse guard
        raise TypeError(f"seed_minimal_ledger needs a CadOps (or a .cad), got {type(project)!r}")
    return cad.record_requirements([MINIMAL_LEDGER_ENTRY], op_id=op_id)


def seed_minimal_ledger_at(root: Path) -> None:
    """The same seed for a project directory that has no open store yet.

    Opens the project's opstore just long enough to record the entry and closes
    it again, so a harness that later opens the project (a bridge runtime, an MCP
    server, a second dispatcher) finds the ledger already there.
    """
    from hephaestus.agent_bridge.cad_ops import CadOps
    from hephaestus.core.project_store.layout import load_project, open_store

    layout = load_project(root)
    store = open_store(layout)
    try:
        seed_minimal_ledger(CadOps(layout, store))
    finally:
        store.close()
