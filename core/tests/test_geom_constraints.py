"""Constraint-residual tests (``ASSEMBLY.md`` §2): both sides of every tolerance.

Each of the eight 8C kinds is evaluated twice against fixture geometry built so
the answer is hand-computable — a 0.2 mm gap between two flush faces, a 0.1 mm
radial window on a 3.0/2.9 hole-and-shaft, a 3° tilt — and the residual is
asserted to a *named* tolerance, so a regression shows up as a wrong number and
not merely a changed one. The refusal tests are the load-bearing ones: a kind
asked of the wrong class of shape must come back as a named
:class:`ConstraintShapeError`, because a plausible-looking number for
"concentricity of two boxes" would be worse than no answer at all.

There is no solver here and there is nothing to solve: every fixture is posed
where the script would have posed it, and the constraint only measures.
"""

# Mirror of the kernel executionEnvironment relaxations for untyped
# build123d surfaces (root pyproject [tool.pyright]); everything else strict.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import asdict
from typing import Any

import pytest
from build123d import Box, Cylinder, GeomType, Pos, Rot, Sphere
from hephaestus.geom import (
    CONSTRAINT_KINDS,
    INTERFERENCE_TOL_MM3,
    OPTIONAL_PARAMS,
    REQUIRED_PARAMS,
    SHAPE_REFUSALS,
    AnyShape,
    ConstraintDeclarationError,
    ConstraintResidual,
    ConstraintShapeError,
    clearance_min_residual,
    coincident_residual,
    concentric_residual,
    distance_residual,
    evaluate_residual,
    fit_residual,
    no_interference_residual,
    parallel_residual,
    perpendicular_residual,
)

#: Distances and angles that a rigid, axis-aligned fixture makes exact. OCCT
#: reproduces these to ~1e-13; anything outside this band is a real drift.
EXACT_TOL_MM = 1e-9
EXACT_TOL_DEG = 1e-9

#: A boolean intersection volume carries more round-off than a bounding-box
#: distance does; 500 mm³ of overlap is reproduced to well inside this.
VOLUME_TOL_MM3 = 1e-6

#: Cross-process agreement demanded by ``ASSEMBLY.md`` Gate G8C.
DETERMINISM_TOL = 1e-9

CUBE = 10.0
BORE_R = 3.0
SHAFT_R = 2.9
PLATE_XY, PLATE_Z = 20.0, 10.0

#: The declared slip-fit window the fixture pair sits inside (radial mm).
FIT_MIN_MM, FIT_MAX_MM = 0.05, 0.2

#: The interference (press) window: a shaft *larger* than its bore is a
#: legitimate declared intent, not a refusal.
PRESS_MIN_MM, PRESS_MAX_MM = -0.05, -0.01


# --------------------------------------------------------------------------
# fixtures (module level: the determinism subprocess imports them by name)


def cube() -> AnyShape:
    """A 10 mm cube centred on the origin."""
    return Box(CUBE, CUBE, CUBE)


def plate_with_bore() -> AnyShape:
    """A 20x20x10 plate with a Ø6 through bore on the Z axis."""
    return Box(PLATE_XY, PLATE_XY, PLATE_Z) - Cylinder(BORE_R, PLATE_Z * 2)


def shaft(radius: float = SHAFT_R) -> AnyShape:
    """A Z-axis cylinder long enough to pass right through the plate."""
    return Cylinder(radius, PLATE_Z * 3)


def plane_face(shape: AnyShape, axis: str, sign: float) -> AnyShape:
    """The extreme planar face of ``shape`` along ``axis`` (``sign`` picks end)."""
    index = {"x": 0, "y": 1, "z": 2}[axis]
    faces = [face for face in shape.faces() if face.geom_type == GeomType.PLANE]
    ordered = sorted(faces, key=lambda f: sign * _center(f)[index])
    return ordered[-1]


def cylinder_face(shape: AnyShape) -> AnyShape:
    """The first cylindrical face of ``shape`` in enumeration order."""
    return next(face for face in shape.faces() if face.geom_type == GeomType.CYLINDER)


def _center(face: Any) -> tuple[float, float, float]:
    point = face.center()
    return (float(point.X), float(point.Y), float(point.Z))


def bore_face() -> AnyShape:
    return cylinder_face(plate_with_bore())


def shaft_face(radius: float = SHAFT_R, *, offset_mm: float = 0.0) -> AnyShape:
    return cylinder_face(Pos(offset_mm, 0, 0) * shaft(radius))


# --------------------------------------------------------------------------
# no_interference


class TestNoInterference:
    def test_disjoint_solids_are_satisfied_with_zero_overlap(self) -> None:
        residual = no_interference_residual(cube(), Pos(2 * CUBE, 0, 0) * cube())
        assert residual.kind == "no_interference"
        assert residual.unit == "mm3"
        assert residual.measured == pytest.approx(0.0, abs=VOLUME_TOL_MM3)
        assert residual.satisfied
        assert residual.slack > 0.0
        assert residual.worst_points == ()

    def test_flush_faces_are_not_an_interference(self) -> None:
        """The named noise floor exists so a designed flush joint is not a hit."""
        residual = no_interference_residual(cube(), Pos(CUBE, 0, 0) * cube())
        assert residual.measured == pytest.approx(0.0, abs=VOLUME_TOL_MM3)
        assert residual.satisfied

    def test_overlap_reports_its_volume_and_where_it_is(self) -> None:
        """A 5 mm intrusion of a 10 mm cube is exactly 500 mm³, centred at x=2.5."""
        residual = no_interference_residual(cube(), Pos(CUBE / 2, 0, 0) * cube())
        assert not residual.satisfied
        assert residual.measured == pytest.approx(500.0, abs=VOLUME_TOL_MM3)
        assert residual.slack == pytest.approx(INTERFERENCE_TOL_MM3 - 500.0, abs=VOLUME_TOL_MM3)
        assert len(residual.worst_points) == 1
        x, y, z = residual.worst_points[0]
        assert (x, y, z) == pytest.approx((2.5, 0.0, 0.0), abs=EXACT_TOL_MM)

    def test_declared_floor_is_restated(self) -> None:
        residual = no_interference_residual(cube(), cube(), tol_mm3=2000.0)
        assert dict(residual.declared) == {"tol_mm3": 2000.0}
        assert residual.satisfied, "a 1000 mm³ self-overlap is under a 2000 mm³ floor"


# --------------------------------------------------------------------------
# clearance_min


class TestClearanceMin:
    def test_gap_above_the_floor_is_satisfied_with_positive_slack(self) -> None:
        residual = clearance_min_residual(cube(), Pos(2 * CUBE, 0, 0) * cube(), value_mm=5.0)
        assert residual.unit == "mm"
        assert residual.measured == pytest.approx(CUBE, abs=EXACT_TOL_MM)
        assert residual.slack == pytest.approx(5.0, abs=EXACT_TOL_MM)
        assert residual.satisfied
        assert len(residual.worst_points) == 2

    def test_gap_below_the_floor_is_violated_by_the_shortfall(self) -> None:
        residual = clearance_min_residual(cube(), Pos(2 * CUBE, 0, 0) * cube(), value_mm=12.0)
        assert not residual.satisfied
        assert residual.slack == pytest.approx(-2.0, abs=EXACT_TOL_MM)

    def test_tolerance_widens_the_floor_downwards_only(self) -> None:
        """``tol_mm`` lowers the floor; it is not a two-sided window."""
        residual = clearance_min_residual(
            cube(), Pos(2 * CUBE, 0, 0) * cube(), value_mm=12.0, tol_mm=2.0
        )
        assert dict(residual.values)["floor_mm"] == pytest.approx(10.0, abs=EXACT_TOL_MM)
        assert residual.satisfied
        assert residual.slack == pytest.approx(0.0, abs=EXACT_TOL_MM)

    def test_overlapping_solids_measure_zero_clearance(self) -> None:
        residual = clearance_min_residual(cube(), Pos(CUBE / 2, 0, 0) * cube(), value_mm=0.1)
        assert residual.measured == 0.0
        assert not residual.satisfied


# --------------------------------------------------------------------------
# distance


class TestDistance:
    def test_distance_on_target_is_satisfied(self) -> None:
        residual = distance_residual(
            cube(), Pos(2 * CUBE, 0, 0) * cube(), value_mm=10.0, tol_mm=0.1
        )
        assert residual.measured == pytest.approx(CUBE, abs=EXACT_TOL_MM)
        assert dict(residual.values)["deviation_mm"] == pytest.approx(0.0, abs=EXACT_TOL_MM)
        assert residual.slack == pytest.approx(0.1, abs=EXACT_TOL_MM)
        assert residual.satisfied

    def test_distance_off_target_is_violated_on_either_side(self) -> None:
        far = distance_residual(cube(), Pos(2 * CUBE, 0, 0) * cube(), value_mm=9.5, tol_mm=0.1)
        near = distance_residual(cube(), Pos(2 * CUBE, 0, 0) * cube(), value_mm=10.5, tol_mm=0.1)
        for residual in (far, near):
            assert not residual.satisfied
            assert dict(residual.values)["deviation_mm"] == pytest.approx(0.5, abs=EXACT_TOL_MM)
            assert residual.slack == pytest.approx(-0.4, abs=EXACT_TOL_MM)


# --------------------------------------------------------------------------
# coincident


class TestCoincident:
    def test_flush_opposed_faces_are_coincident(self) -> None:
        residual = coincident_residual(
            plane_face(cube(), "x", 1.0),
            plane_face(Pos(CUBE, 0, 0) * cube(), "x", -1.0),
            tol_mm=0.05,
        )
        assert residual.measured == pytest.approx(0.0, abs=EXACT_TOL_MM)
        assert dict(residual.values)["normal_deviation_deg"] == pytest.approx(
            0.0, abs=EXACT_TOL_DEG
        )
        assert residual.satisfied
        assert len(residual.worst_points) == 2

    def test_a_gap_beyond_tolerance_is_violated_by_the_gap(self) -> None:
        residual = coincident_residual(
            plane_face(cube(), "x", 1.0),
            plane_face(Pos(CUBE + 0.2, 0, 0) * cube(), "x", -1.0),
            tol_mm=0.05,
        )
        assert not residual.satisfied
        assert residual.measured == pytest.approx(0.2, abs=1e-6)
        assert residual.slack == pytest.approx(-0.15, abs=1e-6)

    def test_coplanar_faces_pointing_the_same_way_are_not_mated(self) -> None:
        """Opposition is part of the kind: same-facing coplanar faces fail with slack."""
        residual = coincident_residual(
            plane_face(cube(), "x", 1.0),
            plane_face(Pos(-2.5, 0, 0) * Box(15.0, 4.0, 4.0), "x", 1.0),
            tol_mm=0.05,
        )
        assert residual.measured == pytest.approx(0.0, abs=EXACT_TOL_MM)
        assert residual.slack > 0.0, "the distance bound holds..."
        assert not residual.satisfied, "...but the normals are not opposed"
        assert dict(residual.values)["normal_deviation_deg"] == pytest.approx(
            180.0, abs=EXACT_TOL_DEG
        )


# --------------------------------------------------------------------------
# concentric


class TestConcentric:
    def test_coaxial_bore_and_shaft_are_concentric(self) -> None:
        residual = concentric_residual(bore_face(), shaft_face(), tol_mm=0.01)
        assert residual.measured == pytest.approx(0.0, abs=EXACT_TOL_MM)
        assert dict(residual.values)["axis_angle_deg"] == pytest.approx(0.0, abs=EXACT_TOL_DEG)
        assert dict(residual.values)["radius_a_mm"] == pytest.approx(BORE_R, abs=EXACT_TOL_MM)
        assert dict(residual.values)["radius_b_mm"] == pytest.approx(SHAFT_R, abs=EXACT_TOL_MM)
        assert residual.satisfied

    def test_an_offset_axis_is_violated_by_the_offset(self) -> None:
        residual = concentric_residual(bore_face(), shaft_face(offset_mm=0.5), tol_mm=0.1)
        assert not residual.satisfied
        assert residual.measured == pytest.approx(0.5, abs=EXACT_TOL_MM)
        assert residual.slack == pytest.approx(-0.4, abs=EXACT_TOL_MM)

    def test_a_tilted_axis_is_unsatisfied_and_says_so_in_degrees(self) -> None:
        tilted = cylinder_face(Rot(0, 5, 0) * shaft())
        residual = concentric_residual(bore_face(), tilted, tol_mm=0.1)
        assert not residual.satisfied
        assert dict(residual.values)["axis_angle_deg"] == pytest.approx(5.0, abs=1e-9)


# --------------------------------------------------------------------------
# parallel / perpendicular


class TestAngularKinds:
    def test_parallel_faces_measure_zero(self) -> None:
        residual = parallel_residual(
            plane_face(cube(), "x", 1.0),
            plane_face(Pos(3 * CUBE, 0, 0) * cube(), "x", 1.0),
            tol_deg=0.001,
        )
        assert residual.unit == "deg"
        assert residual.measured == pytest.approx(0.0, abs=EXACT_TOL_DEG)
        assert residual.satisfied

    def test_parallel_is_about_lines_not_arrows(self) -> None:
        """Anti-parallel normals fold to 0: the two faces of one slab are parallel."""
        residual = parallel_residual(
            plane_face(cube(), "x", 1.0), plane_face(cube(), "x", -1.0), tol_deg=0.001
        )
        assert residual.measured == pytest.approx(0.0, abs=EXACT_TOL_DEG)
        assert residual.satisfied

    def test_a_three_degree_tilt_violates_a_one_degree_tolerance(self) -> None:
        residual = parallel_residual(
            plane_face(cube(), "x", 1.0),
            plane_face(Rot(0, 0, 3) * cube(), "x", 1.0),
            tol_deg=1.0,
        )
        assert not residual.satisfied
        assert residual.measured == pytest.approx(3.0, abs=1e-9)
        assert residual.slack == pytest.approx(-2.0, abs=1e-9)

    def test_square_faces_measure_zero_deviation(self) -> None:
        residual = perpendicular_residual(
            plane_face(cube(), "x", 1.0), plane_face(cube(), "y", 1.0), tol_deg=0.001
        )
        assert residual.measured == pytest.approx(0.0, abs=EXACT_TOL_DEG)
        assert dict(residual.values)["angle_deg"] == pytest.approx(90.0, abs=EXACT_TOL_DEG)
        assert residual.satisfied

    def test_three_degrees_out_of_square_is_violated(self) -> None:
        residual = perpendicular_residual(
            plane_face(cube(), "x", 1.0),
            plane_face(Rot(0, 0, 3) * cube(), "y", 1.0),
            tol_deg=1.0,
        )
        assert not residual.satisfied
        assert residual.measured == pytest.approx(3.0, abs=1e-9)
        assert dict(residual.values)["angle_deg"] == pytest.approx(87.0, abs=1e-9)

    def test_a_cylinder_axis_is_square_to_the_plate_face(self) -> None:
        """The direction precedence is documented: plane normal vs cylinder axis."""
        residual = perpendicular_residual(
            plane_face(plate_with_bore(), "x", 1.0), bore_face(), tol_deg=0.001
        )
        assert residual.measured == pytest.approx(0.0, abs=EXACT_TOL_DEG)
        assert residual.satisfied


# --------------------------------------------------------------------------
# fit


class TestFit:
    def test_a_slip_fit_inside_the_window_is_satisfied(self) -> None:
        residual = fit_residual(bore_face(), shaft_face(), min_mm=FIT_MIN_MM, max_mm=FIT_MAX_MM)
        assert residual.measured == pytest.approx(BORE_R - SHAFT_R, abs=EXACT_TOL_MM)
        assert residual.slack == pytest.approx(0.05, abs=EXACT_TOL_MM)
        assert residual.satisfied
        values = dict(residual.values)
        assert values["hole_radius_mm"] == pytest.approx(BORE_R, abs=EXACT_TOL_MM)
        assert values["shaft_radius_mm"] == pytest.approx(SHAFT_R, abs=EXACT_TOL_MM)
        assert values["hole_is_a"] == 1.0
        assert values["axis_offset_mm"] == pytest.approx(0.0, abs=EXACT_TOL_MM)

    def test_too_tight_for_the_window_is_violated_by_the_shortfall(self) -> None:
        residual = fit_residual(bore_face(), shaft_face(2.98), min_mm=FIT_MIN_MM, max_mm=FIT_MAX_MM)
        assert not residual.satisfied
        assert residual.measured == pytest.approx(0.02, abs=1e-9)
        assert residual.slack == pytest.approx(-0.03, abs=1e-9)

    def test_too_loose_for_the_window_is_violated_from_the_other_side(self) -> None:
        residual = fit_residual(bore_face(), shaft_face(2.7), min_mm=FIT_MIN_MM, max_mm=FIT_MAX_MM)
        assert not residual.satisfied
        assert residual.measured == pytest.approx(0.3, abs=1e-9)
        assert residual.slack == pytest.approx(-0.1, abs=1e-9)

    def test_a_press_fit_is_a_declared_negative_window_not_an_error(self) -> None:
        residual = fit_residual(
            bore_face(), shaft_face(3.02), min_mm=PRESS_MIN_MM, max_mm=PRESS_MAX_MM
        )
        assert residual.measured == pytest.approx(-0.02, abs=1e-9)
        assert residual.satisfied

    def test_roles_are_read_from_the_faces_not_the_argument_order(self) -> None:
        forwards = fit_residual(bore_face(), shaft_face(), min_mm=FIT_MIN_MM, max_mm=FIT_MAX_MM)
        backwards = fit_residual(shaft_face(), bore_face(), min_mm=FIT_MIN_MM, max_mm=FIT_MAX_MM)
        assert backwards.measured == pytest.approx(forwards.measured, abs=EXACT_TOL_MM)
        assert dict(forwards.values)["hole_is_a"] == 1.0
        assert dict(backwards.values)["hole_is_a"] == 0.0

    def test_a_misaligned_fit_still_reports_the_misalignment(self) -> None:
        """A diameter window says nothing about coaxiality; the fact rides along."""
        residual = fit_residual(
            bore_face(), shaft_face(offset_mm=0.5), min_mm=FIT_MIN_MM, max_mm=FIT_MAX_MM
        )
        assert residual.satisfied, "the radial window holds"
        assert dict(residual.values)["axis_offset_mm"] == pytest.approx(0.5, abs=EXACT_TOL_MM)


# --------------------------------------------------------------------------
# wrong class: named refusals, never a garbage number


class TestShapeRefusals:
    def test_concentric_on_planar_faces_is_not_cylindrical(self) -> None:
        with pytest.raises(ConstraintShapeError) as excinfo:
            concentric_residual(plane_face(cube(), "x", 1.0), bore_face(), tol_mm=0.1)
        assert excinfo.value.reason == "not_cylindrical"
        assert excinfo.value.side == "a"
        assert excinfo.value.kind == "concentric"

    def test_coincident_on_a_cylindrical_face_is_not_planar(self) -> None:
        with pytest.raises(ConstraintShapeError) as excinfo:
            coincident_residual(bore_face(), plane_face(cube(), "x", 1.0), tol_mm=0.1)
        assert excinfo.value.reason == "not_planar"
        assert excinfo.value.side == "a"

    def test_a_whole_solid_does_not_name_one_plane(self) -> None:
        with pytest.raises(ConstraintShapeError) as excinfo:
            coincident_residual(cube(), plane_face(cube(), "x", 1.0), tol_mm=0.1)
        assert excinfo.value.reason == "ambiguous_plane"

    def test_two_different_bores_do_not_name_one_axis(self) -> None:
        twin = (
            Box(PLATE_XY, PLATE_XY, PLATE_Z)
            - Cylinder(BORE_R, PLATE_Z * 2)
            - Pos(8, 0, 0) * Cylinder(2.0, PLATE_Z * 2)
        )
        with pytest.raises(ConstraintShapeError) as excinfo:
            concentric_residual(twin, shaft(), tol_mm=0.1)
        assert excinfo.value.reason == "ambiguous_cylinder"

    def test_a_split_bore_still_names_one_cylinder(self) -> None:
        """Coplanar/coaxial face sets merge; only disagreement refuses."""
        split = plate_with_bore() - Box(PLATE_XY * 2, 0.5, PLATE_Z * 2)
        residual = concentric_residual(split, shaft(), tol_mm=0.01)
        assert residual.satisfied
        assert dict(residual.values)["radius_a_mm"] == pytest.approx(BORE_R, abs=EXACT_TOL_MM)

    def test_interference_of_a_face_has_no_volume_to_measure(self) -> None:
        with pytest.raises(ConstraintShapeError) as excinfo:
            no_interference_residual(plane_face(cube(), "x", 1.0), cube())
        assert excinfo.value.reason == "not_solid"
        assert excinfo.value.side == "a"

    def test_a_sphere_has_no_direction(self) -> None:
        with pytest.raises(ConstraintShapeError) as excinfo:
            parallel_residual(Sphere(5).faces()[0], plane_face(cube(), "x", 1.0), tol_deg=1.0)
        assert excinfo.value.reason == "not_directional"

    @pytest.mark.parametrize("pair", ["shafts", "bores"])
    def test_a_fit_needs_one_hole_and_one_shaft(self, pair: str) -> None:
        if pair == "shafts":
            a, b = shaft_face(), shaft_face(2.0, offset_mm=30.0)
        else:
            a, b = bore_face(), cylinder_face(Pos(0, 40, 0) * plate_with_bore())
        with pytest.raises(ConstraintShapeError) as excinfo:
            fit_residual(a, b, min_mm=FIT_MIN_MM, max_mm=FIT_MAX_MM)
        assert excinfo.value.reason == "fit_needs_hole_and_shaft"
        assert excinfo.value.side == "both"

    def test_every_refusal_reason_is_declared_and_exercised(self) -> None:
        """The taxonomy is closed: no reason invented at a raise site."""
        raised: set[str] = set()
        for call in _refusing_calls():
            with pytest.raises(ConstraintShapeError) as excinfo:
                call()
            raised.add(excinfo.value.reason)
        assert raised == set(SHAPE_REFUSALS)

    def test_refusals_are_value_errors(self) -> None:
        """Callers that only know ``ValueError`` still fail loudly, never numerically."""
        with pytest.raises(ValueError):
            concentric_residual(cube(), cube(), tol_mm=0.1)


def _refusing_calls() -> tuple[Any, ...]:
    plane = plane_face(cube(), "x", 1.0)
    twin = (
        Box(PLATE_XY, PLATE_XY, PLATE_Z)
        - Cylinder(BORE_R, PLATE_Z * 2)
        - Pos(8, 0, 0) * Cylinder(2.0, PLATE_Z * 2)
    )
    return (
        lambda: no_interference_residual(plane, cube()),
        lambda: coincident_residual(bore_face(), plane, tol_mm=0.1),
        lambda: concentric_residual(plane, bore_face(), tol_mm=0.1),
        lambda: coincident_residual(cube(), plane, tol_mm=0.1),
        lambda: concentric_residual(twin, shaft(), tol_mm=0.1),
        lambda: parallel_residual(Sphere(5).faces()[0], plane, tol_deg=1.0),
        lambda: fit_residual(shaft_face(), shaft_face(2.0, offset_mm=30.0), min_mm=0.0, max_mm=1.0),
    )


# --------------------------------------------------------------------------
# dispatch by kind name


class TestDispatch:
    def test_the_kind_vocabulary_matches_the_parameter_tables(self) -> None:
        assert set(CONSTRAINT_KINDS) == set(REQUIRED_PARAMS)
        assert set(CONSTRAINT_KINDS) == set(OPTIONAL_PARAMS)
        assert len(CONSTRAINT_KINDS) == 8, "ASSEMBLY.md §1 declares eight 8C kinds"

    def test_dispatch_matches_the_direct_call(self) -> None:
        direct = fit_residual(bore_face(), shaft_face(), min_mm=FIT_MIN_MM, max_mm=FIT_MAX_MM)
        dispatched = evaluate_residual(
            "fit", bore_face(), shaft_face(), {"min_mm": FIT_MIN_MM, "max_mm": FIT_MAX_MM}
        )
        assert asdict(dispatched) == asdict(direct)

    def test_every_kind_is_dispatchable_with_its_required_parameters(self) -> None:
        for kind, residual in residual_suite().items():
            assert residual.kind == kind
        assert set(residual_suite()) == set(CONSTRAINT_KINDS)

    def test_unknown_kind_is_refused_by_name(self) -> None:
        with pytest.raises(ConstraintDeclarationError) as excinfo:
            evaluate_residual("welded", cube(), cube(), {})
        assert excinfo.value.reason == "unknown_kind"

    def test_missing_parameter_is_named(self) -> None:
        with pytest.raises(ConstraintDeclarationError) as excinfo:
            evaluate_residual("fit", bore_face(), shaft_face(), {"min_mm": 0.0})
        assert excinfo.value.reason == "missing_parameter"
        assert excinfo.value.params == ("max_mm",)

    def test_unknown_parameter_is_named(self) -> None:
        with pytest.raises(ConstraintDeclarationError) as excinfo:
            evaluate_residual(
                "clearance_min", cube(), Pos(30, 0, 0) * cube(), {"value_mm": 1.0, "tol_deg": 1.0}
            )
        assert excinfo.value.reason == "unknown_parameter"
        assert excinfo.value.params == ("tol_deg",)


# --------------------------------------------------------------------------
# determinism


def residual_suite() -> dict[str, ConstraintResidual]:
    """One residual per kind over the fixtures — the determinism payload."""
    far = Pos(2 * CUBE, 0, 0) * cube()
    plane_a = plane_face(cube(), "x", 1.0)
    plane_b = plane_face(Pos(CUBE, 0, 0) * cube(), "x", -1.0)
    tilted = plane_face(Rot(0, 0, 3) * cube(), "x", 1.0)
    return {
        "no_interference": no_interference_residual(cube(), Pos(CUBE / 2, 0, 0) * cube()),
        "clearance_min": clearance_min_residual(cube(), far, value_mm=5.0, tol_mm=0.5),
        "distance": distance_residual(cube(), far, value_mm=9.5, tol_mm=0.1),
        "coincident": coincident_residual(plane_a, plane_b, tol_mm=0.05),
        "concentric": concentric_residual(bore_face(), shaft_face(offset_mm=0.5), tol_mm=0.1),
        "parallel": parallel_residual(plane_a, tilted, tol_deg=1.0),
        "perpendicular": perpendicular_residual(plane_a, tilted, tol_deg=1.0),
        "fit": fit_residual(bore_face(), shaft_face(), min_mm=FIT_MIN_MM, max_mm=FIT_MAX_MM),
    }


def _payload() -> dict[str, Any]:
    return {kind: asdict(residual) for kind, residual in residual_suite().items()}


class TestDeterminism:
    def test_repeated_evaluation_is_bit_identical(self) -> None:
        assert _payload() == _payload()

    def test_a_fresh_interpreter_agrees_to_1e_9(self) -> None:
        here = _flatten(_payload())
        there = _flatten(_subprocess_payload())
        assert sorted(here) == sorted(there)
        for key, value in here.items():
            other = there[key]
            if isinstance(value, float):
                assert other == pytest.approx(value, abs=DETERMINISM_TOL), key
            else:
                assert other == value, key


def _flatten(record: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Every scalar in the payload under a dotted/indexed path.

    Recurses through nested sequences (``declared``/``values`` are pairs and
    ``worst_points`` are triples) so each float is compared to
    :data:`DETERMINISM_TOL` individually rather than a whole tuple being
    compared for exact equality.
    """
    out: dict[str, Any] = {}
    for key, value in record.items():
        out.update(_flatten_value(f"{prefix}{key}", value))
    return out


def _flatten_value(name: str, value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return _flatten(value, prefix=f"{name}.")  # pyright: ignore[reportUnknownArgumentType]
    if isinstance(value, (list, tuple)):
        out: dict[str, Any] = {}
        for index, item in enumerate(value):  # pyright: ignore[reportUnknownVariableType]
            out.update(_flatten_value(f"{name}[{index}]", item))
        return out
    return {name: value}


_SUBPROCESS_PROGRAM = """
import json, sys
sys.path.insert(0, {tests!r})
from test_geom_constraints import _payload
print(json.dumps(_payload()))
"""


def _subprocess_payload() -> dict[str, Any]:
    """The same residuals computed in a fresh interpreter (Gate G8C determinism)."""
    from pathlib import Path

    program = _SUBPROCESS_PROGRAM.format(tests=str(Path(__file__).resolve().parent))
    result = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload: dict[str, Any] = json.loads(result.stdout)
    return payload
