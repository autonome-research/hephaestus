# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""G14C clauses 1-2: §5.1 declaration coverage and order consistency.

Coverage is a check over DECLARATIONS plus the parts' tag indexes —
exhaustive, deterministic, no boolean — which is why ``covered`` is the one
§1.1 verdict with no ``_at_samples`` suffix. The ``uncovered`` result names
every feature with its tag, its descriptor and its reason, on the fixture the
clause words demand: one untagged bore, one tagged bore with no operation,
and one operation that was refused.
"""

from __future__ import annotations

from typing import Any

from _g14c import (
    check_kwargs,
    declare_coverage_setup,
    declare_drill_setup,
    declare_occlusion_setup,
)
from hephaestus.core.cam_check import check_setup
from hephaestus.core.project_store.cam import CamState

# -- clause 1: covered / uncovered, naming every tag and reason -------------


def test_a_fully_declared_setup_is_covered(bench_copy: tuple[Any, Any]) -> None:
    layout, store = bench_copy
    declare_drill_setup(CamState(layout, store))
    status = check_setup(layout, store, "s-op1", **check_kwargs(), simulate=False)
    assert status.coverage is not None
    report = status.coverage.to_json()
    # `covered` — deliberately WITHOUT a sampling suffix: coverage quantifies
    # over a finite enumerated set (CAM.md §1.1).
    assert report["verdict"] == "covered"
    assert report["uncovered"] == []
    covered = {item["tag"]: item for item in report["covered"]}
    assert "simpart:drill_a" in covered
    assert covered["simpart:drill_a"]["operation"] == "op-drill"
    assert "cylindrical face" in covered["simpart:drill_a"]["descriptor"]


def test_uncovered_names_every_tag_and_reason(bench_copy: tuple[Any, Any]) -> None:
    """The clause's own fixture: an untagged bore, a tagged bore with no
    operation, and an operation refused ``feature_below_tool_radius``."""
    layout, store = bench_copy
    declare_coverage_setup(CamState(layout, store))
    status = check_setup(layout, store, "s-cov", **check_kwargs(), simulate=False)
    assert status.coverage is not None
    report = status.coverage.to_json()
    assert report["verdict"] == "uncovered"

    by_reason = {item["reason"]: item for item in report["uncovered"]}
    assert set(by_reason) == {"no_operation", "operation_refused", "untagged_bore"}

    # The tagged bore no operation claims, by name and with its descriptor.
    lone = by_reason["no_operation"]
    assert lone["tag"] == "covpart:drill_lone"
    assert "cylindrical face" in lone["descriptor"]

    # The refused operation's feature: the refusal is NAMED, never summarized.
    refused = by_reason["operation_refused"]
    assert refused["tag"] == "covpart:pocket_narrow"
    assert refused["operation"] == "op-narrow"
    assert refused["refusal"]["reason"] == "feature_below_tool_radius"

    # The untagged bore: no tag to name, so the census names the geometry —
    # anything not declared was not checked, and it must not vanish (§1.6.8).
    untagged = by_reason["untagged_bore"]
    assert untagged["tag"] is None
    assert untagged["part"] == "covpart"
    assert "diameter 4" in untagged["descriptor"]

    # The covered bore is still covered: one bad feature never hides the rest.
    assert {item["tag"] for item in report["covered"]} == {"covpart:drill_hole"}


# -- clause 2: feature_occluded_by_order, naming both operations ------------


def test_feature_occluded_by_order_names_both_operations(bench_copy: tuple[Any, Any]) -> None:
    layout, store = bench_copy
    declare_occlusion_setup(CamState(layout, store))
    status = check_setup(layout, store, "s-occ", **check_kwargs(), simulate=False)
    assert status.coverage is not None
    occlusions = status.coverage.to_json()["occlusions"]
    assert len(occlusions) == 1
    finding = occlusions[0]
    assert finding["reason"] == "feature_occluded_by_order"
    # BOTH operations, named — the clause's whole subject.
    assert finding["operation"] == "op-first"
    assert finding["occluded_by"] == "op-second"
    assert finding["feature"] == "occpart:drill_deep"
    assert finding["occluding_feature"] == "occpart:pocket_top"
    # And it surfaces as a finding on the status, so a reader cannot miss it.
    assert any(
        item.get("reason") == "feature_occluded_by_order" for item in status.to_json()["findings"]
    )


def test_the_correct_order_raises_no_occlusion(bench_copy: tuple[Any, Any]) -> None:
    """Pocket first, drill second: the drill's material is already gone by the
    time it runs, so the pair is consistent and nothing fires."""
    layout, store = bench_copy
    cam = CamState(layout, store)
    from _g14c import drill_op, fixture_entry, provenance, setup_entry, stock_entry, wcs_entry

    cam.stock.declare(stock_entry("occpart", id="st-occ", extents_mm=[30.0, 20.0, 8.0]))
    cam.fixtures.declare(fixture_entry(id="fx-occ"))
    cam.wcs.declare(wcs_entry("occpart", id="w-occ"))
    cam.setups.declare(setup_entry(id="s-occ", stock="st-occ", fixture="fx-occ", wcs="w-occ"))
    cam.operations.declare(
        {
            "id": "op-second",
            "setup": "s-occ",
            "kind": "pocket",
            "feature": "occpart:pocket_top",
            "tool": "em_6mm_3fl_carbide",
            "depth_mm": 3.0,
            "stepdown_mm": 3.0,
            "stepover_mm": 2.4,
            "provenance": provenance(),
        }
    )
    cam.operations.declare(drill_op("occpart", "drill_deep", id="op-first", setup="s-occ", depth_mm=3.0))
    status = check_setup(layout, store, "s-occ", **check_kwargs(), simulate=False)
    assert status.coverage is not None
    assert status.coverage.to_json()["occlusions"] == []
