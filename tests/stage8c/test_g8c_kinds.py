"""G8C: every 8C kind, on both sides of its own tolerance, over real geometry.

Gate clause: *every kind evaluated against fixture geometry on both sides of its
tolerance (satisfied and violated, residual values asserted to named
tolerances)*.

Both sides of the SAME geometry, wherever the fixture allows it: the pair of
constraints for a kind is usually one pair of shapes measured twice against two
different declarations, so what flips the verdict is demonstrably the claim and
not the model. That is the whole premise of ``ASSEMBLY.md`` §2 — geom restates
the caller's declared numbers against a measurement and decides nothing else —
and it is only visible when the measurement is held fixed.

The declared numbers are asserted back out of the residual (``declared``), the
measured value to 1e-9 of the number the fixture was authored to produce, and
the defaults to the **named constants** ``geom.constraints`` exports, so a
silently changed epsilon fails here rather than quietly widening a mate.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, cast

import pytest
from _g8c import (
    BASE_BRACKET_GAP_MM,
    NOMINAL_CLEARANCE_MM,
    PIN_OFFSET_MM,
    PLUG_OVERLAP_MM3,
    REGISTER_RADIUS_MM,
    RIM_TO_FLOOR_MM,
    build_all,
    check,
    declare,
    make_assembly_project,
    outcome,
)
from hephaestus.testing.tools_fixture import Project

#: Every kind twice: the declaration the geometry meets, and the one it misses.
#: ``(id, kind, a, b, declared numbers)`` — the fixture's shapes are held fixed
#: across each pair wherever the kind's class rules allow.
DECLARATIONS: tuple[tuple[str, str, str, str, dict[str, float]], ...] = (
    # no_interference: the bracket is 15 mm of air away; the plug bites into the
    # base ring. Both are whole-part anchors, so this is a volume of overlap.
    ("ok-no_interference", "no_interference", "base", "bracket", {}),
    ("no-no_interference", "no_interference", "base", "plug", {}),
    # clearance_min: one measurement (15.0 mm), two floors.
    ("ok-clearance_min", "clearance_min", "base", "bracket", {"value_mm": 10.0}),
    ("no-clearance_min", "clearance_min", "base", "bracket", {"value_mm": 20.0}),
    # distance: the same 15.0 mm against a value it hits and one it misses.
    ("ok-distance", "distance", "base", "bracket", {"value_mm": 15.0, "tol_mm": 0.5}),
    ("no-distance", "distance", "base", "bracket", {"value_mm": 10.0, "tol_mm": 0.5}),
    # coincident: the lid really is seated flush on the rim; the base's own rim
    # and floor are parallel, opposed and 10 mm apart — a flush claim they miss.
    ("ok-coincident", "coincident", "base:rim_top", "lid:seat_face", {"tol_mm": 0.01}),
    ("no-coincident", "coincident", "base:rim_top", "base:floor_face", {"tol_mm": 0.01}),
    # concentric: the boss shares the bore's axis, the pin sits 2 mm off it.
    ("ok-concentric", "concentric", "base:register_slot", "lid:register_wall", {"tol_mm": 0.01}),
    ("no-concentric", "concentric", "base:register_slot", "pin", {"tol_mm": 0.01}),
    # parallel / perpendicular: one horizontal face against a horizontal and a
    # vertical one — each pair satisfies exactly one of the two kinds.
    ("ok-parallel", "parallel", "base:rim_top", "lid:seat_face", {"tol_deg": 0.01}),
    ("no-parallel", "parallel", "base:rim_top", "bracket:inner_face", {"tol_deg": 0.01}),
    ("ok-perpendicular", "perpendicular", "base:rim_top", "bracket:inner_face", {"tol_deg": 0.01}),
    ("no-perpendicular", "perpendicular", "base:rim_top", "lid:seat_face", {"tol_deg": 0.01}),
    # fit: the register pair measures 0.15 mm of radial clearance.
    ("ok-fit", "fit", "base:register_slot", "lid:register_wall", {"min_mm": 0.05, "max_mm": 0.25}),
    ("no-fit", "fit", "base:register_slot", "lid:register_wall", {"min_mm": 0.20, "max_mm": 0.30}),
)


@pytest.fixture(scope="module")
def measured(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Mapping[str, Any]]:
    """One built project, one ``check_assembly``, sixteen declarations.

    Module-scoped because the geometry is the constant here: every clause below
    reads the same status document, which is also the honest way to assert that
    two contradictory claims about ONE pair of shapes come back with two
    different verdicts and the same measurement.
    """
    root = cast("Path", tmp_path_factory.mktemp("kinds")) / "proj"
    project: Project = make_assembly_project(root)
    try:
        build_all(project, "base", "lid", "bracket", "plug", "pin")
        for constraint_id, kind, a, b, values in DECLARATIONS:
            declare(project, constraint_id, kind, a, b, **values)
        yield check(project)
    finally:
        project.close()


def declared(row: Mapping[str, Any]) -> dict[str, float]:
    """The residual's ``declared`` pairs as a mapping (geom's own record shape)."""
    residual = cast("Mapping[str, Any]", row["residual"])
    return {
        str(cast("list[Any]", pair)[0]): float(cast("list[Any]", pair)[1])
        for pair in cast("list[Any]", residual["declared"])
    }


def values(row: Mapping[str, Any]) -> dict[str, float]:
    """The residual's secondary measured facts as a mapping."""
    residual = cast("Mapping[str, Any]", row["residual"])
    return {
        str(cast("list[Any]", pair)[0]): float(cast("list[Any]", pair)[1])
        for pair in cast("list[Any]", residual["values"])
    }


def both(measured: Mapping[str, Any], kind: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """The satisfied and the violated row for one kind, checked to be exactly that."""
    ok = outcome(measured, f"ok-{kind}")
    no = outcome(measured, f"no-{kind}")
    assert (ok["kind"], no["kind"]) == (kind, kind)
    assert ok["state"] == "satisfied", ok
    assert no["state"] == "violated", no
    # A violated constraint carries a residual and no unresolvable reason: it was
    # measured, and saying otherwise would conflate "wrong" with "unchecked".
    assert no["reason"] is None and no["detail"] is None
    assert cast("Mapping[str, Any]", no["residual"])["satisfied"] is False
    assert cast("Mapping[str, Any]", ok["residual"])["satisfied"] is True
    return ok, no


def test_no_interference_measures_the_overlap_volume(measured: Mapping[str, Any]) -> None:
    from hephaestus.geom.constraints import INTERFERENCE_TOL_MM3

    ok, no = both(measured, "no_interference")
    assert cast("Mapping[str, Any]", ok["residual"])["unit"] == "mm3"
    assert cast("Mapping[str, Any]", ok["residual"])["measured"] == pytest.approx(0.0, abs=1e-9)
    # The plug takes a ring out of the base: pi * (12^2 - 10^2) * 4 mm^3.
    assert cast("Mapping[str, Any]", no["residual"])["measured"] == pytest.approx(
        PLUG_OVERLAP_MM3, abs=1e-6
    )
    # The default noise floor is the named constant, echoed so a reader of the
    # residual never has to know this module's defaults.
    assert declared(ok) == {"tol_mm3": INTERFERENCE_TOL_MM3}
    # …and a real interference says WHERE: the intersection's centroid.
    assert len(cast("list[Any]", cast("Mapping[str, Any]", no["residual"])["worst_points"])) == 1
    assert len(cast("list[Any]", cast("Mapping[str, Any]", ok["residual"])["worst_points"])) == 0


def test_clearance_min_measures_the_gap_against_a_floor(measured: Mapping[str, Any]) -> None:
    ok, no = both(measured, "clearance_min")
    for row in (ok, no):
        assert cast("Mapping[str, Any]", row["residual"])["measured"] == pytest.approx(
            BASE_BRACKET_GAP_MM, abs=1e-9
        )
    assert values(ok)["floor_mm"] == pytest.approx(10.0, abs=1e-9)
    assert cast("Mapping[str, Any]", ok["residual"])["slack"] == pytest.approx(5.0, abs=1e-9)
    assert cast("Mapping[str, Any]", no["residual"])["slack"] == pytest.approx(-5.0, abs=1e-9)
    # The optional tolerance defaults to 0 and is echoed: it widens the floor
    # downwards, so a reader can tell a bare declaration from a slack one.
    assert declared(ok) == {"value_mm": 10.0, "tol_mm": 0.0}


def test_distance_is_two_sided_around_the_declared_value(measured: Mapping[str, Any]) -> None:
    ok, no = both(measured, "distance")
    for row in (ok, no):
        assert cast("Mapping[str, Any]", row["residual"])["measured"] == pytest.approx(
            BASE_BRACKET_GAP_MM, abs=1e-9
        )
    assert values(ok)["deviation_mm"] == pytest.approx(0.0, abs=1e-9)
    assert values(no)["deviation_mm"] == pytest.approx(5.0, abs=1e-9)
    assert declared(no) == {"value_mm": 10.0, "tol_mm": 0.5}


def test_coincident_needs_both_flush_and_opposed(measured: Mapping[str, Any]) -> None:
    from hephaestus.geom.constraints import COINCIDENT_NORMAL_EPS_DEG

    ok, no = both(measured, "coincident")
    assert cast("Mapping[str, Any]", ok["residual"])["measured"] == pytest.approx(0.0, abs=1e-9)
    # The rim and the floor of the base ARE opposed and parallel; what they are
    # not is flush, and the out-of-plane gap is the plate's own thickness.
    assert cast("Mapping[str, Any]", no["residual"])["measured"] == pytest.approx(
        RIM_TO_FLOOR_MM, abs=1e-9
    )
    assert values(no)["normal_deviation_deg"] == pytest.approx(0.0, abs=1e-9)
    assert declared(ok) == {"tol_mm": 0.01, "normal_eps_deg": COINCIDENT_NORMAL_EPS_DEG}
    # The mating face centres are reported, so the operator can go look.
    assert len(cast("list[Any]", cast("Mapping[str, Any]", ok["residual"])["worst_points"])) == 2


def test_concentric_measures_the_radial_offset_of_two_axes(measured: Mapping[str, Any]) -> None:
    from hephaestus.geom.constraints import CONCENTRIC_AXIS_EPS_DEG

    ok, no = both(measured, "concentric")
    assert cast("Mapping[str, Any]", ok["residual"])["measured"] == pytest.approx(0.0, abs=1e-9)
    assert cast("Mapping[str, Any]", no["residual"])["measured"] == pytest.approx(
        PIN_OFFSET_MM, abs=1e-9
    )
    # Both pairs are axis-aligned: the offset is the only thing that differs, so
    # the verdict cannot be blamed on a tilted bore.
    assert values(ok)["axis_angle_deg"] == pytest.approx(0.0, abs=1e-12)
    assert values(no)["axis_angle_deg"] == pytest.approx(0.0, abs=1e-12)
    assert values(ok)["radius_a_mm"] == pytest.approx(REGISTER_RADIUS_MM, abs=1e-9)
    assert declared(ok) == {"tol_mm": 0.01, "axis_eps_deg": CONCENTRIC_AXIS_EPS_DEG}


def test_parallel_and_perpendicular_split_the_same_two_pairs(
    measured: Mapping[str, Any],
) -> None:
    """One horizontal pair and one horizontal/vertical pair, each kind both ways."""
    ok_parallel, no_parallel = both(measured, "parallel")
    ok_square, no_square = both(measured, "perpendicular")

    assert cast("Mapping[str, Any]", ok_parallel["residual"])["unit"] == "deg"
    assert cast("Mapping[str, Any]", ok_parallel["residual"])["measured"] == pytest.approx(
        0.0, abs=1e-9
    )
    # Folded into [0, 90]: the rim and the seat face each other, and parallelism
    # is a statement about lines, so anti-parallel normals read 0 and not 180.
    assert cast("Mapping[str, Any]", no_parallel["residual"])["measured"] == pytest.approx(
        90.0, abs=1e-9
    )
    # perpendicular reports the ERROR from square, so zero is square…
    assert cast("Mapping[str, Any]", ok_square["residual"])["measured"] == pytest.approx(
        0.0, abs=1e-9
    )
    assert values(ok_square)["angle_deg"] == pytest.approx(90.0, abs=1e-9)
    # …and the pair that is parallel is 90 deg away from it.
    assert cast("Mapping[str, Any]", no_square["residual"])["measured"] == pytest.approx(
        90.0, abs=1e-9
    )
    assert declared(ok_parallel) == {"tol_deg": 0.01}


def test_fit_measures_the_radial_window_of_a_hole_and_a_shaft(
    measured: Mapping[str, Any],
) -> None:
    """The register fit itself: one measurement, two windows (§1's worked example)."""
    ok, no = both(measured, "fit")
    for row in (ok, no):
        assert cast("Mapping[str, Any]", row["residual"])["measured"] == pytest.approx(
            NOMINAL_CLEARANCE_MM, abs=1e-9
        )
    assert values(ok)["hole_radius_mm"] == pytest.approx(REGISTER_RADIUS_MM, abs=1e-9)
    assert values(ok)["shaft_radius_mm"] == pytest.approx(
        REGISTER_RADIUS_MM - NOMINAL_CLEARANCE_MM, abs=1e-9
    )
    # Which side is the hole is read from the geometry, not from the argument
    # order: the bore is anchor a here, and the residual says so.
    assert values(ok)["hole_is_a"] == 1.0
    # A fit window says nothing about coaxiality, so the alignment rides along
    # as a fact rather than hiding behind a passing diameter.
    assert values(ok)["axis_offset_mm"] == pytest.approx(0.0, abs=1e-9)
    assert declared(no) == {"min_mm": 0.20, "max_mm": 0.30}
    assert cast("Mapping[str, Any]", no["residual"])["slack"] == pytest.approx(-0.05, abs=1e-9)


def test_the_status_counts_exactly_the_two_halves(measured: Mapping[str, Any]) -> None:
    """Eight kinds, sixteen declarations, and no third outcome anywhere."""
    counts = cast("Mapping[str, Any]", measured["counts"])
    assert counts == {"satisfied": 8, "violated": 8, "unresolvable": 0}
    # Every violated id blocks, in declaration order, and no satisfied one does.
    assert list(cast("list[Any]", measured["blocking"])) == [
        constraint_id for constraint_id, *_ in DECLARATIONS if constraint_id.startswith("no-")
    ]
