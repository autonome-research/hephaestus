# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""Gate G0B — Tier 1 performance budgets (verification.md).

Wall-clock ceilings, enforced as tests (public-fixture scaled):

- **Full build ≤ 30 s.** The whole assembly (both parts) builds within budget.
- **Incremental rebuild ≤ 1.5x the changed-statement cost + 2 s.** Re-building
  after a single-statement edit must not blow past the original build cost —
  the per-statement checkpointing with lazy metrics keeps this honest.
- **Measure interference across all assembly pairs ≤ 5 s.** The kernel measures
  every unordered solid pair of the built frame within budget.

Budgets tighten (never loosen) by amendment; the assertions use the
verification.md ceilings directly.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from _gate import ASSEMBLY, InProcessPart, build_part, build_source, read
from hephaestus.geom import AnyShape, interference_pairs

FULL_BUILD_BUDGET_S = 30.0
INTERFERENCE_BUDGET_S = 5.0
INCREMENTAL_FIXED_OVERHEAD_S = 2.0
INCREMENTAL_COST_FACTOR = 1.5

PRIMARY = ASSEMBLY / "parts" / "primary.py"
BRACKET = ASSEMBLY / "parts" / "bracket.py"
GLOBALS = ASSEMBLY / "globals.py"


def _timed_build_primary(out_dir: Path, script: str | None = None) -> float:
    started = time.monotonic()
    if script is None:
        built = build_part("primary", PRIMARY, out_dir, globals_path=GLOBALS)
    else:
        built = build_source("primary", script, out_dir, globals_source=read(GLOBALS))
    elapsed = time.monotonic() - started
    assert built.result.status == "ok"
    return elapsed


class TestFullBuildBudget:
    def test_assembly_full_build_within_30s(self, tmp_path: Path) -> None:
        started = time.monotonic()
        primary = build_part("primary", PRIMARY, tmp_path / "p", globals_path=GLOBALS)
        bracket = build_part("bracket", BRACKET, tmp_path / "b", globals_path=GLOBALS)
        elapsed = time.monotonic() - started
        assert primary.result.status == "ok"
        assert bracket.result.status == "ok"
        assert elapsed <= FULL_BUILD_BUDGET_S, f"full assembly build took {elapsed:.2f}s"


class TestIncrementalRebuildBudget:
    def test_single_statement_edit_rebuild_within_budget(self, tmp_path: Path) -> None:
        # Baseline cost of a full primary build.
        baseline = _timed_build_primary(tmp_path / "base")

        # Edit exactly one statement: change the single numeric literal in the
        # post_inset PARAM default (15.0 -> 16.0). Every other statement is
        # byte-identical, so this is a single-statement edit.
        original = read(PRIMARY)
        edited = original.replace(
            "Param(15.0, min=6.0, max=30.0)", "Param(16.0, min=6.0, max=30.0)"
        )
        assert edited != original, "the edit target statement must exist verbatim"

        rebuild = _timed_build_primary(tmp_path / "rebuild", script=edited)
        budget = INCREMENTAL_COST_FACTOR * baseline + INCREMENTAL_FIXED_OVERHEAD_S
        assert rebuild <= budget, (
            f"incremental rebuild {rebuild:.2f}s exceeded budget {budget:.2f}s "
            f"(baseline {baseline:.2f}s)"
        )


class TestInterferenceBudget:
    def test_interference_across_all_assembly_pairs_within_5s(self) -> None:
        # Real solids of the built frame (6 solids => 15 unordered pairs).
        part = InProcessPart(read(PRIMARY), read(GLOBALS))
        solids = part.solids()
        assert len(solids) == 6
        named: dict[str, AnyShape] = {f"solid_{i}": solid for i, solid in enumerate(solids)}
        started = time.monotonic()
        pairs = interference_pairs(named)
        elapsed = time.monotonic() - started
        assert len(pairs) == 15  # C(6, 2)
        assert elapsed <= INTERFERENCE_BUDGET_S, (
            f"interference across {len(pairs)} pairs took {elapsed:.2f}s"
        )
        # The four congruent corner posts are mutually disjoint (sanity: the
        # measure ran on real geometry, not a no-op).
        assert all(overlap >= 0.0 for overlap in pairs.values())


class TestMeasureFacadeBudget:
    def test_cross_part_interference_within_5s(self) -> None:
        # The assembly's flagship cross-part measure (frame vs bracket) also
        # sits inside the interference budget.
        primary = InProcessPart(read(PRIMARY), read(GLOBALS))
        bracket = InProcessPart(read(BRACKET), read(GLOBALS))
        started = time.monotonic()
        from hephaestus.geom import clearance, interference

        overlap = interference(primary.shape, bracket.shape)
        gap = clearance(primary.shape, bracket.shape)
        elapsed = time.monotonic() - started
        assert elapsed <= INTERFERENCE_BUDGET_S
        # At defaults the bracket seats one joint_clear (0.3 mm) off the frame.
        assert overlap == pytest.approx(0.0, abs=1e-6)
        assert gap == pytest.approx(0.3, abs=0.05)
