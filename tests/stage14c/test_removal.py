# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""G14C clauses 5-8 and 14: the §5.3 removal simulation, on cylinder arithmetic.

Every fixture here is a drilled bore, because a drilled volume is literal
``pi * r^2 * h`` a reader can check by hand (the ``_g14c`` module docstring
carries the numbers), and clause 8's 10x margin from every threshold is
asserted NUMERICALLY rather than assumed. The gouge fixture doubles as the
iou clause: the verdict keys on ``b_only_mm3`` while the same record's
``iou`` stays above 0.99 — the single most important statistic decision in
the spec (§5.3), proven rather than narrated.
"""

from __future__ import annotations

from typing import Any

import pytest
from _g14c import BORE_MM3_PER_MM, check_kwargs, declare_drill_setup
from hephaestus.core.cam_check import CAM_VERDICT_MARGIN, check_setup
from hephaestus.core.limits import cam_min_resolvable_mm3
from hephaestus.core.project_store.cam import CamState


def _simulated(bench_copy: tuple[Any, Any], depth_mm: float) -> Any:
    layout, store = bench_copy
    declare_drill_setup(CamState(layout, store), depth_mm=depth_mm)
    status = check_setup(layout, store, "s-op1", **check_kwargs())
    assert status.state == "checked"
    assert status.simulation is not None, [r for r in status.refusals]
    return status


# -- clause 5: matches_at_samples, every number present, the floor formula --


def test_matches_at_samples_with_every_number_and_the_formula_floor(
    bench_copy: tuple[Any, Any],
) -> None:
    status = _simulated(bench_copy, 4.0)
    record = status.simulation.to_json()
    assert record["verdict"] == "matches_at_samples"
    # Every directed volume, the deviation, the sample count, the step and
    # the floor — present AS NUMBERS in the record (§5.9).
    for key in ("a_only_mm3", "b_only_mm3", "common_mm3", "iou", "max_deviation_mm"):
        assert isinstance(record[key], float | int)
    assert record["samples_evaluated"] > 0
    per_op = {item["op"]: item for item in record["per_op"]}
    assert per_op["op-drill"]["samples"] > 0
    step = record["min_resolvable_inputs"]["step_mm"]
    assert step == pytest.approx(0.25)  # 0.10 x r=2.5, inside the clamp
    # The reported floor EQUALS the §5.3 formula at the run's own
    # (step_mm, r, doc_mm) — asserted against the published formula itself.
    inputs = record["min_resolvable_inputs"]
    assert record["min_resolvable_mm3"] == cam_min_resolvable_mm3(
        inputs["step_mm"], inputs["r_mm"], inputs["doc_mm"]
    )
    assert inputs == {"operation": "op-drill", "step_mm": 0.25, "r_mm": 2.5, "doc_mm": 25.0}


# -- clause 6: gouge via b_only, localized, and the iou trap ----------------


def test_gouge_at_samples_is_driven_by_b_only_while_iou_stays_above_099(
    bench_copy: tuple[Any, Any],
) -> None:
    """A deliberate 1.0 mm overdepth: b_only = pi * 2.5^2 * 1 = 19.63 mm^3."""
    status = _simulated(bench_copy, 5.0)
    record = status.simulation.to_json()
    assert record["verdict"] == "gouge_at_samples"
    assert record["b_only_mm3"] == pytest.approx(BORE_MM3_PER_MM * 1.0, rel=0.02)
    # Localized by the surface max-deviation: the extra millimetre of floor.
    assert record["max_deviation_mm"] == pytest.approx(1.0, abs=0.1)
    # THE clause that proves iou is not a legal threshold (§5.3): a 19.6 mm^3
    # gouge in a ~3500 mm^3 part barely moves one scalar.
    assert record["iou"] > 0.99
    # And the verdict files as a part_risk finding (§1.3), never crash_risk.
    finding = next(f for f in record["findings"] if f["reason"] == "gouge_at_samples")
    assert finding["severity"] == "part_risk"
    assert finding["budget_mm3"] == 1.5


# -- clause 7: rest via a_only ----------------------------------------------


def test_rest_at_samples_is_driven_by_a_only(bench_copy: tuple[Any, Any]) -> None:
    """Declared 2 mm shallow: a_only = pi * 2.5^2 * 2 = 39.27 mm^3."""
    status = _simulated(bench_copy, 2.0)
    record = status.simulation.to_json()
    assert record["verdict"] == "rest_at_samples"
    assert record["a_only_mm3"] == pytest.approx(BORE_MM3_PER_MM * 2.0, rel=0.02)
    finding = next(f for f in record["findings"] if f["reason"] == "rest_at_samples")
    assert finding["severity"] == "part_risk"


# -- clause 8: every fixture 10x from its threshold, numerically ------------


def test_every_fixture_sits_ten_x_from_its_threshold(bench_copy: tuple[Any, Any]) -> None:
    layout, store = bench_copy
    cam = CamState(layout, store)
    declare_drill_setup(cam, depth_mm=5.0)
    gouge = check_setup(layout, store, "s-op1", **check_kwargs()).simulation.to_json()
    cam.operations.update("op-drill", {"depth_mm": 2.0}, "the rest fixture")
    rest = check_setup(layout, store, "s-op1", **check_kwargs()).simulation.to_json()
    cam.operations.update("op-drill", {"depth_mm": 4.0}, "the matches fixture")
    matches = check_setup(layout, store, "s-op1", **check_kwargs()).simulation.to_json()

    budgets = gouge["budgets"]
    # The failing fixtures overshoot their thresholds by >= 10x…
    assert gouge["b_only_mm3"] >= CAM_VERDICT_MARGIN * budgets["gouge_budget_mm3"]
    assert rest["a_only_mm3"] >= CAM_VERDICT_MARGIN * budgets["rest_budget_mm3"]
    # …and the passing fixture undershoots by >= 10x, so no kernel-build
    # difference can flip any of the three (§4.4).
    assert matches["b_only_mm3"] * CAM_VERDICT_MARGIN <= budgets["gouge_budget_mm3"]
    assert matches["a_only_mm3"] * CAM_VERDICT_MARGIN <= budgets["rest_budget_mm3"]
    # The budgets themselves clear the reported resolution floor.
    assert budgets["gouge_budget_mm3"] > matches["min_resolvable_mm3"]


# -- clause 14: removal_boolean_failed, never a partial solid ---------------


def test_a_null_boolean_is_removal_boolean_failed_never_a_partial_solid(
    bench_copy: tuple[Any, Any],
) -> None:
    layout, store = bench_copy
    declare_drill_setup(CamState(layout, store))
    status = check_setup(
        layout, store, "s-op1", **check_kwargs(), fault={"null_boolean": True}
    )
    # The named refusal — and NO simulation record: a partial solid is never
    # reported as a result (§5.3, the fourth blocking finding's fix).
    assert status.simulation is None
    refusal = next(r for r in status.refusals if r["reason"] == "removal_boolean_failed")
    assert "partial solid" in str(refusal["message"])
    # The cheap halves still stand: a failed boolean costs the boolean.
    assert status.coverage is not None and status.coverage.verdict == "covered"
    assert status.round_trip is not None
