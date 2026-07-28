"""Solid-comparison tests (``COMPARE.md`` §1): known deltas, declared frames, determinism.

Every fixture here has a hand-computable answer — a self-diff is zero, a rigid
copy is the same solid, a drilled hole removes exactly a cylinder — so a
regression shows up as a wrong *number*, not just a changed one. The alignment
tests are the load-bearing ones: they pin that ``as_posed`` and ``principal``
answer different questions and that the record always says which was asked.
"""

# Mirror of the kernel executionEnvironment relaxations for untyped
# build123d surfaces (root pyproject [tool.pyright]); everything else strict.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false

from __future__ import annotations

import json
import math
import subprocess
import sys
from dataclasses import asdict
from typing import Any

import pytest
from build123d import Align, Box, Cylinder, Pos, Rot
from hephaestus.geom import (
    MAX_FACE_SAMPLES,
    MIN_FACE_SAMPLES,
    AlignMode,
    AnyShape,
    principal_alignment,
    solid_diff,
    surface_distance,
    topology_diff,
    volume_diff,
)

#: A self-diff must be exactly zero to numerical noise, not approximately zero.
IDENTITY_TOL_MM3 = 1e-9
IDENTITY_TOL_MM = 1e-9

#: Booleans on a rigidly transformed copy accumulate kernel round-off; this is
#: the band inside which "the same solid, moved" must still measure the same.
RIGID_TOL_MM3 = 1e-6
RIGID_TOL_MM = 1e-6

#: The drilled-hole delta is an exact cylinder volume; OCCT reproduces it to
#: well inside this (observed ~1e-11 mm³ on a 170 mm³ hole).
HOLE_TOL_MM3 = 1e-6

#: Cross-process agreement demanded by ``COMPARE.md`` Gate G8B.
DETERMINISM_TOL = 1e-9

PLATE_X, PLATE_Y, PLATE_Z = 40.0, 30.0, 6.0
HOLE_R = 3.0


def bracket() -> AnyShape:
    """An L-bracket with an off-centre through hole.

    Deliberately asymmetric in two of its three principal directions (so the
    principal frame is non-degenerate) while keeping one mirror plane (so the
    "weakest skew is derived" tie-break rule is actually exercised by the rigid
    -copy test rather than skipped).
    """
    base = Box(40.0, 20.0, 6.0, align=(Align.MIN, Align.MIN, Align.MIN))
    wall = Pos(0, 0, 6.0) * Box(6.0, 20.0, 18.0, align=(Align.MIN, Align.MIN, Align.MIN))
    return (base + wall) - Pos(30.0, 10.0, 3.0) * Cylinder(radius=3.0, height=20.0)


def plate() -> AnyShape:
    return Box(PLATE_X, PLATE_Y, PLATE_Z)


def drilled_plate() -> AnyShape:
    return plate() - Cylinder(radius=HOLE_R, height=PLATE_Z)


def moved(shape: AnyShape) -> AnyShape:
    """The same solid under a rigid transform (rotation then translation)."""
    return Rot(12.0, 25.0, 40.0) * Pos(7.0, -3.0, 11.0) * shape


class TestIdentity:
    def test_self_diff_is_zero(self) -> None:
        diff = solid_diff(bracket(), bracket())
        assert diff.volume.a_only_mm3 == pytest.approx(0.0, abs=IDENTITY_TOL_MM3)
        assert diff.volume.b_only_mm3 == pytest.approx(0.0, abs=IDENTITY_TOL_MM3)
        assert diff.volume.iou == pytest.approx(1.0, abs=1e-12)
        assert diff.surface.chamfer_mm == pytest.approx(0.0, abs=IDENTITY_TOL_MM)
        assert diff.surface.max_deviation_mm == pytest.approx(0.0, abs=IDENTITY_TOL_MM)

    def test_self_diff_topology_deltas_are_zero(self) -> None:
        census = topology_diff(bracket(), bracket())
        assert census.faces_delta == 0
        assert census.edges_delta == 0
        assert census.solids_delta == 0
        assert census.cylindrical_faces_delta == 0
        assert census.genus_delta == 0
        assert not census.sealed_changed
        assert census.a == census.b

    def test_bundle_carries_bboxes_and_volumes(self) -> None:
        diff = solid_diff(plate(), drilled_plate())
        assert diff.a_bbox_mm == pytest.approx((PLATE_X, PLATE_Y, PLATE_Z))
        assert diff.b_bbox_mm == pytest.approx((PLATE_X, PLATE_Y, PLATE_Z))
        assert diff.a_volume_mm3 == pytest.approx(PLATE_X * PLATE_Y * PLATE_Z)
        assert diff.b_volume_mm3 == pytest.approx(
            PLATE_X * PLATE_Y * PLATE_Z - math.pi * HOLE_R**2 * PLATE_Z
        )

    def test_sample_counts_are_reported_and_bounded(self) -> None:
        surface = surface_distance(plate(), plate())
        faces = len(plate().faces())
        assert surface.a_samples == surface.b_samples
        assert faces * MIN_FACE_SAMPLES <= surface.a_samples <= faces * MAX_FACE_SAMPLES


class TestAlignment:
    def test_rigid_copy_disagrees_as_posed(self) -> None:
        diff = solid_diff(bracket(), moved(bracket()))
        assert diff.align == "as_posed"
        assert diff.volume.align == "as_posed"
        assert diff.surface.align == "as_posed"
        assert diff.volume.iou < 0.5
        assert diff.surface.max_deviation_mm > 1.0

    def test_rigid_copy_agrees_under_principal(self) -> None:
        diff = solid_diff(bracket(), moved(bracket()), align="principal")
        assert diff.align == "principal"
        assert diff.volume.align == "principal"
        assert diff.surface.align == "principal"
        assert diff.volume.iou == pytest.approx(1.0, abs=1e-9)
        assert diff.volume.a_only_mm3 == pytest.approx(0.0, abs=RIGID_TOL_MM3)
        assert diff.volume.b_only_mm3 == pytest.approx(0.0, abs=RIGID_TOL_MM3)
        assert diff.surface.chamfer_mm == pytest.approx(0.0, abs=RIGID_TOL_MM)
        assert diff.surface.max_deviation_mm == pytest.approx(0.0, abs=RIGID_TOL_MM)

    def test_topology_is_pose_invariant(self) -> None:
        census = topology_diff(bracket(), moved(bracket()))
        assert census.faces_delta == 0
        assert census.genus_delta == 0

    def test_alignment_of_the_asymmetric_bracket_is_not_degenerate(self) -> None:
        here = principal_alignment(bracket())
        there = principal_alignment(moved(bracket()))
        assert not here.degenerate
        assert not there.degenerate
        # Moments are invariants of the solid: the rigid copy reports the same
        # three, in the same (ascending) order.
        assert here.moments == pytest.approx(there.moments, rel=1e-9)
        assert list(here.moments) == sorted(here.moments)

    def test_axes_are_orthonormal_and_right_handed(self) -> None:
        first, second, third = principal_alignment(bracket()).axes
        for axis in (first, second, third):
            assert sum(c * c for c in axis) == pytest.approx(1.0, abs=1e-9)
        cross = (
            first[1] * second[2] - first[2] * second[1],
            first[2] * second[0] - first[0] * second[2],
            first[0] * second[1] - first[1] * second[0],
        )
        assert cross == pytest.approx(third, abs=1e-9)

    def test_no_volume_has_no_inertia_frame(self) -> None:
        with pytest.raises(ValueError, match="volume"):
            principal_alignment(plate().faces()[0])


class TestKnownEdit:
    def test_drilled_hole_delta_is_the_cylinder_volume(self) -> None:
        diff = volume_diff(plate(), drilled_plate())
        expected = math.pi * HOLE_R**2 * PLATE_Z
        assert diff.a_only_mm3 == pytest.approx(expected, abs=HOLE_TOL_MM3)
        assert diff.b_only_mm3 == pytest.approx(0.0, abs=HOLE_TOL_MM3)
        assert diff.common_mm3 == pytest.approx(
            PLATE_X * PLATE_Y * PLATE_Z - expected, abs=HOLE_TOL_MM3
        )
        assert diff.iou == pytest.approx(
            (PLATE_X * PLATE_Y * PLATE_Z - expected) / (PLATE_X * PLATE_Y * PLATE_Z),
            abs=1e-9,
        )

    def test_chamfer_localizes_the_deviation(self) -> None:
        surface = surface_distance(plate(), drilled_plate())
        # The hole wall is the only place the surfaces disagree, so the max
        # deviation sits an order of magnitude above the mean: a local edit.
        assert surface.max_deviation_mm > 1.0
        assert surface.chamfer_mm < surface.max_deviation_mm / 10.0
        assert surface.b_to_a_mean_mm > surface.a_to_b_mean_mm > 0.0

    def test_topology_census_names_the_hole(self) -> None:
        census = topology_diff(plate(), drilled_plate())
        assert census.cylindrical_faces_delta == 1
        assert census.planar_faces_delta == 0
        assert census.faces_delta == 1
        assert census.genus_delta == 1
        assert census.a.sealed and census.b.sealed
        assert not census.sealed_changed

    def test_topology_diff_alone_needs_no_boolean(self) -> None:
        # Two shapes with nothing in common still yield a census: the cheap
        # first look COMPARE.md §1 asks for.
        far = Pos(500, 0, 0) * Cylinder(radius=2.0, height=9.0)
        census = topology_diff(Box(1.0, 1.0, 1.0), far)
        assert census.solids_delta == 0
        assert census.planar_faces_delta == -4
        assert census.cylindrical_faces_delta == 1


class TestDeterminism:
    def test_symmetric_part_tie_break_is_stable(self) -> None:
        cube = Box(10.0, 10.0, 10.0)
        first = principal_alignment(cube)
        assert first.degenerate  # three tied moments: the frame is a choice
        for _ in range(3):
            assert principal_alignment(Box(10.0, 10.0, 10.0)) == first

    def test_symmetric_part_diff_repeats_exactly(self) -> None:
        a, b = Box(10.0, 10.0, 10.0), Box(10.0, 10.0, 10.0)
        assert solid_diff(a, b, align="principal") == solid_diff(a, b, align="principal")

    def test_same_process_repeats_exactly(self) -> None:
        first = solid_diff(bracket(), drilled_plate(), align="principal")
        second = solid_diff(bracket(), drilled_plate(), align="principal")
        assert first == second

    @pytest.mark.parametrize("align", ["as_posed", "principal"])
    def test_subprocess_agrees_to_1e_9(self, align: AlignMode) -> None:
        here = _flatten(asdict(solid_diff(bracket(), drilled_plate(), align=align)))
        there = _flatten(_subprocess_diff(align))
        assert sorted(here) == sorted(there)
        for key, value in here.items():
            other = there[key]
            if isinstance(value, float):
                assert other == pytest.approx(value, abs=DETERMINISM_TOL), key
            else:
                assert other == value, key

    @pytest.mark.parametrize("align", ["as_posed", "principal"])
    def test_subprocess_sample_counts_match(self, align: AlignMode) -> None:
        here = solid_diff(bracket(), drilled_plate(), align=align).surface
        there = _subprocess_diff(align)["surface"]
        assert (here.a_samples, here.b_samples) == (there["a_samples"], there["b_samples"])


def _flatten(record: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in record.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            out.update(_flatten(value, prefix=f"{name}."))  # pyright: ignore[reportUnknownArgumentType]
        elif isinstance(value, (list, tuple)):
            for index, item in enumerate(value):  # pyright: ignore[reportUnknownVariableType]
                out[f"{name}[{index}]"] = item
        else:
            out[name] = value
    return out


_SUBPROCESS_PROGRAM = """
import json, sys
from dataclasses import asdict
sys.path.insert(0, {tests!r})
from test_geom_compare import bracket, drilled_plate
from hephaestus.geom import solid_diff
print(json.dumps(asdict(solid_diff(bracket(), drilled_plate(), align=sys.argv[1]))))
"""


def _subprocess_diff(align: AlignMode) -> dict[str, Any]:
    """The same diff computed in a fresh interpreter (determinism, not caching)."""
    from pathlib import Path

    program = _SUBPROCESS_PROGRAM.format(tests=str(Path(__file__).resolve().parent))
    result = subprocess.run(
        [sys.executable, "-c", program, align],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload: dict[str, Any] = json.loads(result.stdout)
    return payload
