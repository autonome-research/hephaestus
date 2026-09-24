# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""G14C clause 22: the Tier 1 ``check_program`` budget, read from its record.

The ceiling is READ from ``verification.md``'s Tier 1 budget list rather than
retyped, so this test cannot drift from the declared number, and §5.8's rule
rides the assertion: if the reference setup cannot meet the budget, the gate
is tightened by shrinking the reference setup — never by raising the budget.
The number bounds a CURVE, not one fixture: clause 12 (test_collision) pins
the collision boolean count to ``samples x bodies x scene`` exactly at two
sample counts, and both boolean loops carry their own caps
(``CAM_SIM_SAMPLES_MAX``, ``CAM_COLLISION_SAMPLES_MAX``), which is what makes
this measurement a bound rather than an observation.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from _g14c import REPO, check_kwargs
from hephaestus.core.cam_check import check_program

VERIFICATION = REPO / "verification.md"


def declared_budget_s() -> float:
    text = VERIFICATION.read_text(encoding="utf-8")
    match = re.search(r"`check_program`\s*\n?on the CAM reference setup ≤ (\d+) s", text)
    if match is None:
        match = re.search(r"check_program[^≤]*≤ (\d+) s", text, re.DOTALL)
    assert match is not None, "verification.md declares no check_program budget"
    return float(match.group(1))


def test_the_budget_is_declared_and_paired_with_the_counted_curve() -> None:
    text = VERIFICATION.read_text(encoding="utf-8")
    assert declared_budget_s() == 120.0
    # §5.8's rule, in the budget's own text: the reference setup shrinks, the
    # budget never grows — and the counted-curve pairing is stated.
    assert "shrinking the" in text and "reference setup" in text
    assert "G14C clause 12" in text
    assert "CAM_COLLISION_SAMPLES_MAX" in text


def test_check_program_on_the_reference_setup_meets_the_budget(
    ref: tuple[Any, Any], tmp_path: Path
) -> None:
    layout, store = ref
    budget = declared_budget_s()
    started = time.monotonic()
    statuses, partial = check_program(
        layout, store, None, **check_kwargs(), scratch=tmp_path, record=False
    )
    elapsed = time.monotonic() - started
    assert partial is False
    assert statuses[0].state == "checked"
    assert statuses[0].simulation is not None
    assert elapsed <= budget, (
        f"check_program took {elapsed:.1f}s against the declared {budget:.0f}s budget — "
        "the fix is to SHRINK the reference setup, never to raise the budget "
        "(verification.md, CAM.md §5.8)"
    )
