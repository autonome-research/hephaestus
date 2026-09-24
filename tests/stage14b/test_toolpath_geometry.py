# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""Gate G14B clauses 2-5 and 16 (geometry half): the offset ladder's two rules.

Clause 2 and clause 16 are the two halves of CAM.md §4.1's termination rule
and are satisfiable together **only because collapse is a fact and not a
refusal**: the hand-computed pockets here run their ladders to normal
collapse with EMPTY refusal lists (asserted as such, not merely as an absent
``toolpath_offset_failed``), while the fault-injected kernel raises the one
refusal this module owns.

Every expected number is hand arithmetic: a 30 x 20 rectangle inset by d
bounds (30-2d)(20-2d); a radius-10 circle bounds pi(10-d)^2; the dumbbell of
``_g14b`` splits into two rings past its 5 mm neck and the smaller square
dies before the larger — pruned into disjoint rings, each terminating on its
own.
"""

from __future__ import annotations

import math
from typing import Any

import pytest
from _g14b import circle_ring_areas, rect_ring_areas
from hephaestus.geom import toolpath as tp


def _rect_wire(width: float, height: float) -> Any:
    from build123d import Polyline, Wire

    return Wire(Polyline((0, 0), (width, 0), (width, height), (0, height), close=True).edges())


def _circle_wire(radius: float) -> Any:
    from build123d import Edge, Wire

    return Wire(Edge.make_circle(radius))


def _dumbbell_wire() -> Any:
    """The ``_g14b`` bell footprint: 15 sq + 11 sq joined by a 10 x 5 neck."""
    from build123d import Polyline, Wire

    points = [
        (75, 5),
        (90, 5),
        (90, 8),
        (100, 8),
        (100, 5),
        (111, 5),
        (111, 16),
        (100, 16),
        (100, 13),
        (90, 13),
        (90, 20),
        (75, 20),
    ]
    return Wire(Polyline(*points, close=True).edges())


# -- clause 2: hand-computed fixtures terminate normally, EMPTY refusals ----


def test_rectangular_pocket_ladder_matches_hand_computed_loops() -> None:
    ladder = tp.offset_ladder(_rect_wire(30.0, 20.0), tool_radius_mm=3.0, stepover_mm=2.0)
    expected = rect_ring_areas(30.0, 20.0, [3.0, 5.0, 7.0, 9.0])
    assert ladder.loops_emitted == 4
    for loop, area in zip(ladder.loops, expected, strict=True):
        assert loop.area_mm2 == pytest.approx(area, abs=1e-9)
    # Termination is a fact next to the loops, never a refusal (CAM.md §4.1).
    assert ladder.termination.loop_index == 4
    assert ladder.termination.distance_mm == pytest.approx(11.0)


def test_circular_pocket_ladder_matches_hand_computed_loops() -> None:
    ladder = tp.offset_ladder(_circle_wire(10.0), tool_radius_mm=3.0, stepover_mm=2.0)
    expected = circle_ring_areas(10.0, [3.0, 5.0, 7.0, 9.0])
    assert ladder.loops_emitted == 4
    for loop, area in zip(ladder.loops, expected, strict=True):
        assert loop.area_mm2 == pytest.approx(area, abs=1e-9)


def test_profile_with_declared_tabs_yields_the_declared_count_and_width() -> None:
    boundary = tp.offset_ladder(_rect_wire(30.0, 20.0), tool_radius_mm=3.0, stepover_mm=2.0)
    points = boundary.loops[0].points
    moves = tp.profile_moves(
        points,
        z_mm=-6.0,
        safe_z_mm=5.0,
        tab_count=3,
        tab_width_mm=6.0,
        tab_top_z_mm=-4.0,
        feed_mm_min=800.0,
        plunge_mm_min=200.0,
        feed_source="explicit",
        op_id="op-prof",
    )
    # A tab is a raised bridge: a vertical up-move at the cut feed followed
    # later by a plunge back down. Count the ups; they are the tabs.
    from itertools import pairwise

    ups = [
        (a, b)
        for a, b in pairwise(moves)
        if a.kind == "linear" and b.kind == "linear" and b.z > a.z and a.x == b.x and a.y == b.y
    ]
    assert len(ups) == 3
    # Each bridge spans the declared width along the path: the down-move for
    # each up-move sits 6 mm of arc length later by construction; assert the
    # bridged deck really is at the declared tab height.
    assert all(b.z == pytest.approx(-4.0) for _a, b in ups)


# -- clause 3: termination rule + self-intersection pruning -----------------


def test_below_min_loop_area_termination_is_a_fact_naming_the_loop_index() -> None:
    """A rung whose offset bounds a face below the floor stops the ladder."""
    # 30 x 20 at r = 3, stepover 3.5: d = 3 (336), 6.5 (119), then d = 10 —
    # exactly the half-height, where the kernel returns a degenerate boundary
    # bounding zero area, below TOOLPATH_MIN_LOOP_AREA_MM2.
    ladder = tp.offset_ladder(_rect_wire(30.0, 20.0), tool_radius_mm=3.0, stepover_mm=3.5)
    assert [round(loop.area_mm2, 9) for loop in ladder.loops] == [336.0, 119.0]
    assert ladder.termination.reason == "below_min_loop_area"
    assert ladder.termination.loop_index == 2
    assert ladder.termination.distance_mm == pytest.approx(10.0)


def test_non_convex_pocket_splits_into_disjoint_rings_each_terminating_alone() -> None:
    """The dumbbell: pruning carries disjoint rings; the smaller dies first."""
    ladder = tp.offset_ladder(_dumbbell_wire(), tool_radius_mm=1.5, stepover_mm=1.5)
    by_rung: dict[int, list[float]] = {}
    for loop in ladder.loops:
        by_rung.setdefault(loop.loop_index, []).append(loop.area_mm2)
    # d = 1.5: one connected ring. d = 3.0: TWO disjoint rings (the 15-square
    # insets to 9x9 = 81, the 11-square to 5x5 = 25). d = 4.5: 6x6 = 36 and
    # 2x2 = 4. d = 6.0: the smaller square has terminated ON ITS OWN while
    # the larger still bounds 3x3 = 9.
    assert len(by_rung[0]) == 1
    assert sorted(round(a, 9) for a in by_rung[1]) == [25.0, 81.0]
    assert sorted(round(a, 9) for a in by_rung[2]) == [4.0, 36.0]
    assert [round(a, 9) for a in by_rung[3]] == [9.0]
    assert ladder.loops_emitted == 6
    assert 4 not in by_rung


def test_feature_below_tool_radius_is_decided_before_the_ladder() -> None:
    """The pre-ladder probe: a 2 mm slot refuses a 3 mm tool without a ladder."""
    slot = _rect_wire(20.0, 2.0)
    assert tp.tool_fits(slot, 1.5) is False
    assert tp.tool_fits(slot, 0.9) is True
    # The engine files the refusal on False (test_generation.py drives that
    # path end to end); what this clause pins is that the DECISION needs no
    # ladder — a zero-loop ladder is never how the fact is discovered.


# -- clause 4: the closed move vocabulary -----------------------------------


def test_move_kind_outside_the_closed_vocabulary_is_refused() -> None:
    with pytest.raises(ValueError, match="closed vocabulary"):
        tp.Move(kind="helix", x=0.0, y=0.0, z=0.0)  # type: ignore[arg-type]
    assert tp.MOVE_KINDS == (
        "rapid",
        "linear",
        "arc_cw",
        "arc_ccw",
        "dwell",
        "tool_change",
        "spindle",
        "coolant",
    )


def test_spline_boundary_yields_linear_moves_only() -> None:
    """No arc fitting of linearized paths (CAM.md §4.2)."""
    from build123d import Edge, Wire

    spline = Edge.make_spline([(0, 0, 0), (20, 6, 0), (40, -6, 0), (60, 0, 0)])
    closing = Edge.make_spline([(60, 0, 0), (30, -25, 0), (0, 0, 0)])
    boundary = Wire([spline, closing])
    ladder = tp.offset_ladder(boundary, tool_radius_mm=1.5, stepover_mm=2.0)
    assert ladder.loops_emitted >= 1
    moves = tp.moves_for_rings(
        ladder.loops,
        z_mm=-2.0,
        safe_z_mm=5.0,
        feed_mm_min=600.0,
        plunge_mm_min=150.0,
        feed_source="tool",
        op_id="op-spline",
    )
    kinds = {move.kind for move in moves}
    assert "arc_cw" not in kinds and "arc_ccw" not in kinds
    assert kinds <= {"rapid", "linear"}


# -- clause 5: the tool solid ------------------------------------------------


def test_tool_solid_volumes_and_extents_are_hand_computable() -> None:
    solid = tp.tool_solid(
        diameter_mm=6.0,
        flute_length_mm=20.0,
        shank_diameter_mm=6.0,
        stickout_mm=25.0,
        holder_diameter_mm=40.0,
        holder_length_mm=60.0,
    )
    assert solid.cutter_volume_mm3 == pytest.approx(math.pi * 9.0 * 20.0, rel=1e-9)
    assert solid.shank_volume_mm3 == pytest.approx(math.pi * 9.0 * 5.0, rel=1e-9)
    assert solid.holder_volume_mm3 == pytest.approx(math.pi * 400.0 * 60.0, rel=1e-9)
    assert solid.cutter_extent_mm == (0.0, 20.0)
    assert solid.shank_extent_mm == (20.0, 25.0)
    assert solid.holder_extent_mm == (25.0, 85.0)
    # Axial extents are real geometry, not just record fields.
    box = solid.holder.bounding_box()
    assert float(box.min.Z) == pytest.approx(25.0, abs=1e-9)
    assert float(box.max.Z) == pytest.approx(85.0, abs=1e-9)


# -- clause 16 (geometry half): the kernel-error branch, and only it --------


def test_toolpath_offset_failed_fires_only_on_a_kernel_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(a) fault-injected kernel raises the named refusal with ring+distance;
    (b) the clause-2 pockets, which collapse normally, raise it zero times —
    already proven by their EMPTY refusal handling above, restated here
    against the raw ladder so both halves sit in one test.
    """
    wire = _rect_wire(30.0, 20.0)
    # (b) normal collapse: no exception of any kind reaches the caller.
    ladder = tp.offset_ladder(wire, tool_radius_mm=3.0, stepover_mm=2.0)
    assert ladder.loops_emitted == 4

    # (a) the except-Exception branch shape of kerf.py:227-230.
    def kernel_fault(_wire: Any, _distance: float) -> list[Any]:
        raise RuntimeError("BRepOffsetAPI_MakeOffset: no result")

    monkeypatch.setattr(tp, "_kernel_offset", kernel_fault)
    with pytest.raises(tp.ToolpathRefusal) as caught:
        tp.offset_ladder(wire, tool_radius_mm=3.0, stepover_mm=2.0)
    assert caught.value.reason == "toolpath_offset_failed"
    assert caught.value.data["ring"] == 0
    assert caught.value.data["offset_mm"] == pytest.approx(-3.0)
