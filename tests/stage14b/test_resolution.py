# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportArgumentType=false
"""Gate G14B clauses 8-10, 13-14, 19-20: the resolution-time refusal set.

Every refusal here needs a registry record, a published artifact or a bound
tool — the reason CAM.md §4.3 files it at resolution and nowhere else. The
project is the session bench: two REAL built parts plus the never-built
``ghost``.
"""

from __future__ import annotations

from typing import Any

import pytest
from _g14b import (
    declare_baseline,
    fixture_entry,
    materials_index,
    operation_entry,
    setup_entry,
    stock_entry,
    tools_index,
    wcs_entry,
)
from hephaestus.core.limits import (
    CAM_KERNEL_NOISE_MM3,
    CAM_RESOLUTION_K,
    cam_min_resolvable_mm3,
)
from hephaestus.core.machining import (
    CAM_AXIS_EPS_DEG,
    MachiningError,
    resolve_setup,
    sim_step_mm,
)
from hephaestus.core.project_store.cam import CamState

TOOLS = tools_index()
MATERIALS = materials_index()


def _resolve(layout: Any, store: Any, setup_id: str = "s-op1") -> Any:
    return resolve_setup(layout, store, setup_id, tools=TOOLS, materials=MATERIALS)


def _cam(bench_copy: tuple[Any, Any]) -> CamState:
    layout, store = bench_copy
    cam = CamState(layout, store)
    declare_baseline(cam)
    return cam


# -- clause 8: stock_too_small, both sides, per axis ------------------------


@pytest.mark.parametrize(
    ("axis", "side", "overrides", "overhang"),
    [
        ("X", "max", {"extents_mm": [119.0, 80.0, 20.0]}, 1.0),
        ("X", "min", {"origin_offset_mm": [0.5, 0.0, 0.0]}, 0.5),
        ("Y", "max", {"extents_mm": [120.0, 79.0, 20.0]}, 1.0),
        ("Y", "min", {"origin_offset_mm": [0.0, 0.25, 0.0]}, 0.25),
        ("Z", "max", {"extents_mm": [120.0, 80.0, 19.0]}, 1.0),
        ("Z", "min", {"origin_offset_mm": [0.0, 0.0, 0.75]}, 0.75),
    ],
)
def test_stock_too_small_names_axis_side_and_overhang(
    bench_copy: tuple[Any, Any], axis: str, side: str, overrides: dict[str, Any], overhang: float
) -> None:
    layout, store = bench_copy
    cam = CamState(layout, store)
    cam.stock.declare(stock_entry(**overrides))
    cam.fixtures.declare(fixture_entry())
    cam.wcs.declare(wcs_entry())
    cam.setups.declare(setup_entry())
    with pytest.raises(MachiningError) as caught:
        _resolve(layout, store)
    assert caught.value.reason == "stock_too_small"
    assert caught.value.data["axis"] == axis
    assert caught.value.data["side"] == side
    assert float(caught.value.data["overhang_mm"]) == pytest.approx(overhang, abs=1e-6)


def test_exactly_fitting_part_does_not_fire(bench_copy: tuple[Any, Any]) -> None:
    layout, store = bench_copy
    _cam(bench_copy)  # exact extents [120, 80, 20] at zero offset
    resolved = _resolve(layout, store)
    assert resolved.stock.id == "st-plate"
    assert resolved.stock_min_mm == pytest.approx((0.0, 0.0, 0.0))
    assert resolved.stock_max_mm == pytest.approx((120.0, 80.0, 20.0))


# -- clause 9: axis_not_parallel_to_spindle, both sides of the epsilon ------


def _declare_tilt_setup(cam: CamState, feature: str) -> None:
    cam.stock.declare(
        stock_entry(id="st-tilt", origin_anchor="tiltpart", extents_mm=[40.0, 20.0, 10.0])
    )
    cam.wcs.declare(wcs_entry(id="w-tilt", datum="tiltpart"))
    cam.setups.declare(setup_entry(id="s-tilt", stock="st-tilt", wcs="w-tilt"))
    cam.operations.declare(
        operation_entry(
            id="op-tilt",
            setup="s-tilt",
            kind="drill",
            feature=feature,
            tool="drill_5mm_hss",
            depth_mm=10.0,
            stepdown_mm=5.0,
            stepover_mm=None,
        )
    )


def test_axis_inside_the_epsilon_resolves(bench_copy: tuple[Any, Any]) -> None:
    """0.3 deg of tilt sits inside CAM_AXIS_EPS_DEG = 0.5 and resolves."""
    layout, store = bench_copy
    cam = CamState(layout, store)
    cam.fixtures.declare(fixture_entry())
    _declare_tilt_setup(cam, "tiltpart:drill_ok")
    resolved = _resolve(layout, store, "s-tilt")
    assert [op.entry.id for op in resolved.operations] == ["op-tilt"]
    assert CAM_AXIS_EPS_DEG == 0.5


def test_axis_outside_the_epsilon_refuses_naming_the_angle(
    bench_copy: tuple[Any, Any],
) -> None:
    """0.7 deg of tilt sits outside and is the named refusal."""
    layout, store = bench_copy
    cam = CamState(layout, store)
    cam.fixtures.declare(fixture_entry())
    _declare_tilt_setup(cam, "tiltpart:drill_tilted")
    with pytest.raises(MachiningError) as caught:
        _resolve(layout, store, "s-tilt")
    assert caught.value.reason == "axis_not_parallel_to_spindle"
    assert float(caught.value.data["angle_deg"]) == pytest.approx(0.7, abs=0.02)
    assert float(caught.value.data["eps_deg"]) == CAM_AXIS_EPS_DEG


# -- clause 10: WCS resolution, and each 8C unresolvable reason named -------


def test_wcs_resolves_through_tag_and_whole_part_anchor_forms(
    bench_copy: tuple[Any, Any],
) -> None:
    layout, store = bench_copy
    cam = _cam(bench_copy)
    resolved = _resolve(layout, store)
    assert resolved.wcs.id == "w-g54"
    assert resolved.wcs_rule == "tag"  # bracket:face_top
    assert resolved.wcs_artifact_ref.startswith("artifact:")
    # the whole-part form resolves under the §7 part rule.
    cam.wcs.declare(wcs_entry(id="w-part", datum="bracket"))
    cam.setups.declare(setup_entry(id="s-part", order=2, wcs="w-part"))
    assert _resolve(layout, store, "s-part").wcs_rule == "part"


@pytest.mark.parametrize(
    ("datum", "reason"),
    [
        ("nosuchpart:face_top", "missing_part"),
        ("ghost", "no_current_build"),
        ("bracket:face_gone", "dangling_selector"),
    ],
)
def test_each_8c_unresolvable_reason_is_named_not_conflated(
    bench_copy: tuple[Any, Any], datum: str, reason: str
) -> None:
    layout, store = bench_copy
    cam = CamState(layout, store)
    cam.stock.declare(stock_entry())
    cam.fixtures.declare(fixture_entry())
    cam.wcs.declare(wcs_entry(datum=datum))
    cam.setups.declare(setup_entry())
    with pytest.raises(MachiningError) as caught:
        _resolve(layout, store)
    assert caught.value.reason == "wcs_anchor_unresolvable"
    assert caught.value.data["unresolvable_reason"] == reason


# -- clause 13: feed resolution, no third branch ----------------------------


def _feed_setup(cam: CamState, *, material: str, **op_overrides: Any) -> None:
    cam.stock.declare(stock_entry(material=material))
    cam.fixtures.declare(fixture_entry())
    cam.wcs.declare(wcs_entry())
    cam.setups.declare(setup_entry())
    cam.operations.declare(operation_entry(**op_overrides))


def test_explicit_wins_over_the_tool_record(bench_copy: tuple[Any, Any]) -> None:
    layout, store = bench_copy
    cam = CamState(layout, store)
    _feed_setup(cam, material="al-6061", feed_mm_min=999.0)
    resolved = _resolve(layout, store)
    feeds = resolved.operations[0].feeds
    assert feeds.feed_mm_min == 999.0
    assert feeds.sources["feed_mm_min"] == "explicit"
    assert feeds.sources["rpm"] == "tool"  # the rest transported from the record


def test_tool_record_feeds_are_used_and_reported_source_tool(
    bench_copy: tuple[Any, Any],
) -> None:
    layout, store = bench_copy
    cam = CamState(layout, store)
    _feed_setup(cam, material="al-6061")
    feeds = _resolve(layout, store).operations[0].feeds
    assert feeds.feed_mm_min == 1200.0 and feeds.rpm == 9000.0
    assert feeds.doc_mm == 3.0 and feeds.woc_mm == 2.4
    assert set(feeds.sources.values()) == {"tool"}
    assert feeds.tool_feed_source == "tool vendor datasheet rev C, 2026-03"


@pytest.mark.parametrize(
    ("explicit", "reason"),
    [
        ({}, "no_declared_feed"),
        ({"feed_mm_min": 800.0}, "no_declared_speed"),
        ({"feed_mm_min": 800.0, "rpm": 9000.0}, "no_declared_doc"),
        ({"feed_mm_min": 800.0, "rpm": 9000.0, "doc_mm": 2.0}, "no_declared_woc"),
    ],
)
def test_missing_numbers_exhaust_into_the_four_named_refusals(
    bench_copy: tuple[Any, Any], explicit: dict[str, float], reason: str
) -> None:
    """No entry value, no (material, op) record entry — and NOTHING ELSE: the
    branch is exhausted number by number, so there is provably no case in
    which a number is produced from neither source."""
    layout, store = bench_copy
    cam = CamState(layout, store)
    # plywood-baltic-birch: em_6mm's feeds table has NO (plywood, pocket)
    # entry, so branch 2 is empty and only the explicit values remain.
    _feed_setup(cam, material="plywood-baltic-birch", **explicit)
    with pytest.raises(MachiningError) as caught:
        _resolve(layout, store)
    assert caught.value.reason == reason
    assert "no third branch" in caught.value.message.lower()


def test_the_source_vocabulary_has_exactly_two_values(bench_copy: tuple[Any, Any]) -> None:
    layout, store = bench_copy
    cam = CamState(layout, store)
    _feed_setup(cam, material="al-6061", feed_mm_min=999.0)
    feeds = _resolve(layout, store).operations[0].feeds
    assert set(feeds.sources.values()) <= {"explicit", "tool"}


# -- clause 14: doc_exceeds_tool_limit refuses, never clamps ----------------


def test_doc_exceeds_tool_limit_is_a_refusal_not_a_clamp(
    bench_copy: tuple[Any, Any],
) -> None:
    layout, store = bench_copy
    cam = CamState(layout, store)
    _feed_setup(cam, material="al-6061", doc_mm=4.5)  # em_6mm max_doc_mm = 3.0
    with pytest.raises(MachiningError) as caught:
        _resolve(layout, store)
    assert caught.value.reason == "doc_exceeds_tool_limit"
    assert float(caught.value.data["doc_mm"]) == 4.5
    assert float(caught.value.data["max_doc_mm"]) == 3.0
    assert "clamp" in caught.value.message  # states the rule it applies


# -- clause 19: the published resolution-floor formula ----------------------


def test_formula_on_the_scallop_side_of_the_max() -> None:
    """Fine step, real radius: the scallop term binds, hand-computed."""
    import math

    step, r, doc = 0.3, 3.0, 3.0
    sagitta = r - math.sqrt(r * r - (step / 2.0) ** 2)
    expected = CAM_RESOLUTION_K * step * sagitta * doc
    assert expected > CAM_KERNEL_NOISE_MM3
    assert cam_min_resolvable_mm3(step, r, doc) == pytest.approx(expected, rel=1e-12)


def test_formula_on_the_kernel_noise_side_of_the_max() -> None:
    """Tiny step and doc: the scallop term underflows the absolute floor."""
    import math

    step, r, doc = 0.05, 10.0, 0.001
    sagitta = r - math.sqrt(r * r - (step / 2.0) ** 2)
    assert CAM_RESOLUTION_K * step * sagitta * doc < CAM_KERNEL_NOISE_MM3
    assert cam_min_resolvable_mm3(step, r, doc) == CAM_KERNEL_NOISE_MM3
    assert CAM_KERNEL_NOISE_MM3 == 1e-6 and CAM_RESOLUTION_K == 10.0


def test_largest_floor_binds_across_a_two_tool_setup(bench_copy: tuple[Any, Any]) -> None:
    layout, store = bench_copy
    cam = _cam(bench_copy)
    cam.operations.declare(operation_entry(id="op-6mm"))
    cam.operations.declare(
        operation_entry(
            id="op-3mm",
            feature="bracket:pocket_bell",
            tool="em_3mm_2fl_carbide",
            depth_mm=3.0,
            stepdown_mm=1.5,
            stepover_mm=1.5,
        )
    )
    resolved = _resolve(layout, store)
    floors = {op.entry.id: op.floor_mm3 for op in resolved.operations}
    assert floors["op-6mm"] == cam_min_resolvable_mm3(sim_step_mm(3.0), 3.0, 3.0)
    assert floors["op-3mm"] == cam_min_resolvable_mm3(sim_step_mm(1.5), 1.5, 1.5)
    assert resolved.floor_mm3 == max(floors.values())
    assert resolved.binding_floor_operation == "op-6mm"


# -- clause 20: budget_below_resolution at resolution time ------------------


def test_budget_below_resolution_names_budget_floor_and_operation(
    bench_copy: tuple[Any, Any],
) -> None:
    layout, store = bench_copy
    cam = CamState(layout, store)
    cam.stock.declare(stock_entry())
    cam.fixtures.declare(fixture_entry())
    cam.wcs.declare(wcs_entry())
    # DECLARES cleanly (the declaration half, test_declaration_rules.py) …
    cam.setups.declare(
        setup_entry(
            tolerance={
                "gouge_budget_mm3": 1e-9,
                "rest_budget_mm3": 40.0,
                "max_deviation_mm": 0.1,
                "rejects_mm3": 4e-9,
            }
        )
    )
    cam.operations.declare(operation_entry())
    # … and refuses HERE, once an operation binds a tool and a doc.
    with pytest.raises(MachiningError) as caught:
        _resolve(layout, store)
    assert caught.value.reason == "budget_below_resolution"
    assert float(caught.value.data["budget_mm3"]) == 1e-9
    assert float(caught.value.data["floor_mm3"]) == pytest.approx(
        cam_min_resolvable_mm3(sim_step_mm(3.0), 3.0, 3.0)
    )
    assert caught.value.data["operation"] == "op-rect"


def test_unknown_tool_is_the_resolution_refusal(bench_copy: tuple[Any, Any]) -> None:
    layout, store = bench_copy
    cam = _cam(bench_copy)
    cam.operations.declare(operation_entry(tool="em_99mm_unobtainium"))
    with pytest.raises(MachiningError) as caught:
        _resolve(layout, store)
    assert caught.value.reason == "unknown_tool"


def test_unknown_material_is_stock_material_unknown(bench_copy: tuple[Any, Any]) -> None:
    layout, store = bench_copy
    cam = CamState(layout, store)
    cam.stock.declare(stock_entry(material="unobtainium-9000"))
    cam.fixtures.declare(fixture_entry())
    cam.wcs.declare(wcs_entry())
    cam.setups.declare(setup_entry())
    with pytest.raises(MachiningError) as caught:
        _resolve(layout, store)
    assert caught.value.reason == "stock_material_unknown"
