# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""Gate G14B clauses 11, 12, 18 and clause 20's declaration half.

Everything here is decidable from entries alone — asserted by running against
a project whose parts have **never been built** (clause 18's own wording): no
registry, no artifact, no geometry is touched, and the sieve still fires.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import pytest
from _g14b import (
    BENCH_PARTS,
    declare_baseline,
    make_project,
    operation_entry,
    setup_entry,
    stock_entry,
)
from hephaestus.core.limits import CAM_OP_PASS_BOUND_MAX
from hephaestus.core.project_store.cam import (
    CAM_TAG_PREFIXES,
    KEEPOUT_TAG_PREFIX,
    CamError,
    CamState,
    operation_kind_for_tag,
)
from hephaestus.core.project_store.layout import open_store


@pytest.fixture
def cam(tmp_path: Path) -> Any:
    layout = make_project(tmp_path / "proj", BENCH_PARTS)
    store = open_store(layout)
    try:
        state = CamState(layout, store)
        declare_baseline(state)
        yield state
    finally:
        store.close()


# -- clause 11: the tag-prefix table ----------------------------------------


def test_each_cam_prefix_maps_to_its_operation_kind() -> None:
    """``layer_for_tag`` generalized: a lookup over the fixed table."""
    assert dict(CAM_TAG_PREFIXES) == {
        "drill_": "drill",
        "pocket_": "pocket",
        "profile_": "profile",
        "face_": "face",
        "mill_": None,  # the generic prefix, claimable by any kind
    }
    assert operation_kind_for_tag("drill_bore_a") == ("drill_", "drill")
    assert operation_kind_for_tag("pocket_relief") == ("pocket_", "pocket")
    assert operation_kind_for_tag("profile_outer") == ("profile_", "profile")
    assert operation_kind_for_tag("face_top") == ("face_", "face")
    assert operation_kind_for_tag("mill_anything") == ("mill_", "*")
    assert operation_kind_for_tag("keepout_clamp") == (KEEPOUT_TAG_PREFIX, "keepout")


def test_mismatched_prefix_is_tag_prefix_mismatch(cam: CamState) -> None:
    with pytest.raises(CamError) as caught:
        cam.operations.declare(operation_entry(kind="drill", feature="bracket:pocket_rect"))
    assert caught.value.reason == "tag_prefix_mismatch"
    # keepout_ is reserved for scenes and is a mismatch for every kind.
    with pytest.raises(CamError) as caught:
        cam.operations.declare(operation_entry(feature="bracket:keepout_clamp"))
    assert caught.value.reason == "tag_prefix_mismatch"


def test_unknown_prefix_is_tag_prefix_unknown(cam: CamState) -> None:
    with pytest.raises(CamError) as caught:
        cam.operations.declare(operation_entry(feature="bracket:engrave_logo"))
    assert caught.value.reason == "tag_prefix_unknown"


def test_bare_prefix_names_no_feature(cam: CamState) -> None:
    """The ``layer_for_tag`` boundary rule (cutfile.py:139-143), generalized."""
    assert operation_kind_for_tag("pocket_") == (None, None)
    with pytest.raises(CamError) as caught:
        cam.operations.declare(operation_entry(feature="bracket:pocket_"))
    assert caught.value.reason == "tag_prefix_unknown"
    assert "names no feature" in caught.value.message


def test_mill_prefix_is_generic_across_kinds(cam: CamState) -> None:
    cam.operations.declare(
        operation_entry(id="op-mill", kind="face", feature="bracket:mill_top", stepover_mm=2.0)
    )


# -- clause 12: duplicate_feature_claim -------------------------------------


def test_two_operations_claiming_one_feature_in_one_setup_refuse(cam: CamState) -> None:
    cam.operations.declare(operation_entry(id="op-a"))
    with pytest.raises(CamError) as caught:
        cam.operations.declare(operation_entry(id="op-b"))
    assert caught.value.reason == "duplicate_feature_claim"
    assert caught.value.data["claimed_by"] == "op-a"
    # a different setup may claim the same feature (the exclusion is per setup)
    cam.setups.declare(setup_entry(id="s-op2", order=2))
    cam.operations.declare(operation_entry(id="op-c", setup="s-op2"))
    # and a WITHDRAWN claim stops blocking: withdrawal is a real act.
    cam.operations.withdraw("op-a", "replaced by the second declaration")
    cam.operations.declare(operation_entry(id="op-b"))


# -- clause 18: op_sample_bound_exceeded at declaration, unbuilt project ----


def test_op_sample_bound_exceeded_fires_at_declaration_with_no_build(cam: CamState) -> None:
    """levels x loops_bound from the entry's own numbers and the stock extents.

    depth 6 / stepdown 0.001 -> 6000 levels; stepover 0.5 over the 80 mm
    stock minor extent -> ceil(80 / 1.0) = 80 bounded loops; 480000 > 20000.
    The project's parts have never been built — the fixture never calls the
    executor — so the sieve provably needs no geometry.
    """
    with pytest.raises(CamError) as caught:
        cam.operations.declare(
            operation_entry(id="op-absurd", depth_mm=6.0, stepdown_mm=0.001, stepover_mm=0.5)
        )
    assert caught.value.reason == "op_sample_bound_exceeded"
    assert caught.value.data["levels"] == 6000
    assert caught.value.data["loops_bound"] == 80
    assert caught.value.data["passes"] == 480000
    assert caught.value.data["bound"] == CAM_OP_PASS_BOUND_MAX
    assert CAM_OP_PASS_BOUND_MAX == 20000


def test_the_sieve_bounds_passes_not_samples(cam: CamState) -> None:
    """A long-toolpath declaration under the pass bound declares fine — the
    sample cap is generation-time machinery (clause 17), deliberately not
    reachable from here."""
    cam.operations.declare(
        operation_entry(id="op-dense", depth_mm=6.0, stepdown_mm=0.05, stepover_mm=1.5)
    )


# -- clause 20 (declaration half): only the shape rules fire here -----------


def test_absent_tolerance_block_is_no_declared_tolerance(cam: CamState) -> None:
    entry = setup_entry(id="s-none", order=5)
    del entry["tolerance"]
    with pytest.raises(CamError) as caught:
        cam.setups.declare(entry)
    assert caught.value.reason == "no_declared_tolerance"


def test_budget_without_rejects_is_budget_missing_rejects(cam: CamState) -> None:
    entry = setup_entry(id="s-norej", order=6)
    tolerance = dict(cast("Mapping[str, float]", entry["tolerance"]))
    del tolerance["rejects_mm3"]
    entry["tolerance"] = cast("Any", tolerance)
    with pytest.raises(CamError) as caught:
        cam.setups.declare(entry)
    assert caught.value.reason == "budget_missing_rejects"


def test_budget_below_resolution_is_unraisable_at_declaration(cam: CamState) -> None:
    """A setup entry names no tool, so the floor has no operand here: a budget
    far below any plausible floor still DECLARES. The refusal fires at
    resolution (test_resolution.py) once operations bind tools."""
    state = cam.setups.declare(
        setup_entry(
            id="s-tiny",
            order=7,
            tolerance={
                "gouge_budget_mm3": 1e-9,
                "rest_budget_mm3": 40.0,
                "max_deviation_mm": 0.1,
                "rejects_mm3": 4e-9,
            },
        )
    )
    assert state.by_id["s-tiny"].withdrawn is False


def test_stock_kind_outside_stage_14_is_refused_naming_future_kinds(cam: CamState) -> None:
    with pytest.raises(CamError) as caught:
        cam.stock.declare(stock_entry(id="st-bar", kind="cylindrical_bar"))
    assert caught.value.reason == "invalid_stock"
    assert "future kinds" in caught.value.message
