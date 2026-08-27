"""Forward-kinematics tests (``KINEMATICS.md`` §2): hand-computed transforms.

Every FK assertion in this file is against a matrix worked out by hand — a 90°
turn about an off-origin z axis, a 7 mm slide, a quarter-turn-plus-travel on
one axis — to 1e-9, so a regression shows up as a wrong number and not merely
a changed one. The refusal tests are the load-bearing ones: an out-of-limits
parameter must come back as a named :class:`JointLimitError` carrying the id,
the value and the limit it broke — NEVER a clamped evaluation, which would be
a fact about a configuration nobody declared — and a malformed forest (a
cycle, two parents, a value for a 0-DOF joint) is a
:class:`JointDeclarationError` naming its reason.

There is no solver here and nothing to solve: the frames are stated in
as-built world coordinates (``zero: "as_built"``, the only 9A reference
configuration) and :func:`transformed_shape` only places copies — the
non-mutation test pins that the caller's shape is untouched.
"""

# Mirror of the kernel executionEnvironment relaxations for untyped
# build123d surfaces (root pyproject [tool.pyright]); everything else strict.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from typing import Any, cast

import pytest
from build123d import Box, Pos
from hephaestus.geom import (
    IDENTITY_TRANSFORM,
    JOINT_FRAME_EPS_DEG,
    JOINT_FRAME_EPS_MM,
    JOINT_KINDS,
    JOINT_REFUSALS,
    JointDeclarationError,
    JointFrame,
    JointLimitError,
    JointLimits,
    RigidTransform,
    forward_kinematics,
    frame_axis_angle_deg,
    frame_radial_offset_mm,
    joint_transform,
    transform_point,
    transformed_shape,
)

ABS = 1e-9


def center_of(shape: object) -> tuple[float, float, float]:
    """World-mm centre of ``shape`` (build123d's ``center`` is untyped on ``Shape``)."""
    center = cast("Any", shape).center()
    return (float(center.X), float(center.Y), float(center.Z))


def volume_of(shape: object) -> float:
    return float(cast("Any", shape).volume)


def assert_rows(transform: RigidTransform, expected: tuple[tuple[float, ...], ...]) -> None:
    """Every entry of ``[R | t]`` against a hand-computed matrix, to 1e-9."""
    for row, want in zip(transform.rows, expected, strict=True):
        for got, value in zip(row, want, strict=True):
            assert got == pytest.approx(value, abs=ABS), (transform.rows, expected)


def revolute(
    joint_id: str,
    parent: str,
    child: str,
    point: tuple[float, float, float],
    direction: tuple[float, float, float],
    limits: JointLimits | None = None,
) -> JointFrame:
    return JointFrame(
        id=joint_id,
        kind="revolute",
        parent=parent,
        child=child,
        point=point,
        direction=direction,
        limits=limits,
    )


# ==========================================================================
# FK per kind, against hand-computed transforms


def test_fixed_is_the_identity() -> None:
    joint = JointFrame(
        id="j-weld",
        kind="fixed",
        parent="base",
        child="bracket",
        point=(0.0, 0.0, 0.0),
        direction=(0.0, 0.0, 0.0),  # fixed needs no axis
    )
    world = forward_kinematics([joint], {})
    assert world["base"] == IDENTITY_TRANSFORM
    assert_rows(
        world["bracket"],
        ((1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0)),
    )


def test_revolute_about_an_off_origin_axis() -> None:
    """90° about the z line through (10, 0, 0): R = Rz(90), t = p - R p.

    Hand computation: ``R p = (0, 10, 0)`` so ``t = (10, -10, 0)`` — the
    translation is what distinguishes an off-origin axis from one through the
    origin, which is exactly what this fixture pins.
    """
    joint = revolute("j-elbow", "arm_upper", "arm_fore", (10.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    world = forward_kinematics([joint], {"j-elbow": 90.0})
    assert_rows(
        world["arm_fore"],
        ((0.0, -1.0, 0.0, 10.0), (1.0, 0.0, 0.0, -10.0), (0.0, 0.0, 1.0, 0.0)),
    )
    # The axis is fixed by its own points; the world origin sweeps around it.
    assert transform_point(world["arm_fore"], (10.0, 0.0, 0.0)) == pytest.approx(
        (10.0, 0.0, 0.0), abs=ABS
    )
    assert transform_point(world["arm_fore"], (0.0, 0.0, 0.0)) == pytest.approx(
        (10.0, -10.0, 0.0), abs=ABS
    )


def test_prismatic_slides_along_the_direction() -> None:
    """7 mm along y, declared with a non-unit direction (0, 2, 0)."""
    joint = JointFrame(
        id="j-slide",
        kind="prismatic",
        parent="rail",
        child="carriage",
        point=(3.0, 4.0, 5.0),  # the axis point is irrelevant to a pure slide
        direction=(0.0, 2.0, 0.0),
        limits=JointLimits(min=-10.0, max=10.0),
    )
    world = forward_kinematics([joint], {"j-slide": 7.0})
    assert_rows(
        world["carriage"],
        ((1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 7.0), (0.0, 0.0, 1.0, 0.0)),
    )


def test_cylindrical_turns_and_slides_on_one_axis() -> None:
    """(90°, 3 mm) on the z line through (0, 0, 5): Rz(90) then +3 z.

    The rotation axis passes through (0, 0, 5) but is the z direction, so the
    rotation alone leaves the origin's x/y untouched and the travel stacks on
    z — hand rows below.
    """
    joint = JointFrame(
        id="j-spindle",
        kind="cylindrical",
        parent="housing",
        child="spindle",
        point=(0.0, 0.0, 5.0),
        direction=(0.0, 0.0, 1.0),
        limits=JointLimits(min=-360.0, max=360.0),
        travel_limits=JointLimits(min=0.0, max=12.0),
    )
    world = forward_kinematics([joint], {"j-spindle": (90.0, 3.0)})
    assert_rows(
        world["spindle"],
        ((0.0, -1.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0), (0.0, 0.0, 1.0, 3.0)),
    )


def test_a_chain_of_three_composes_root_to_leaf() -> None:
    """Revolute 90° at the root, a 5 mm slide riding it, a fixed tip.

    The slide's as-built direction is +x; carried through the parent's 90°
    turn it moves the fore part to (0, 5, 0) — composition order is the
    assertion here, because leaf-to-root would put it at (5, 0, 0) turned.
    """
    joints = [
        revolute("j-shoulder", "base", "arm", (0.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
        JointFrame(
            id="j-extend",
            kind="prismatic",
            parent="arm",
            child="fore",
            point=(0.0, 0.0, 0.0),
            direction=(1.0, 0.0, 0.0),
        ),
        JointFrame(
            id="j-cap",
            kind="fixed",
            parent="fore",
            child="tip",
            point=(0.0, 0.0, 0.0),
            direction=(0.0, 0.0, 0.0),
        ),
    ]
    world = forward_kinematics(joints, {"j-shoulder": 90.0, "j-extend": 5.0})
    assert world["base"] == IDENTITY_TRANSFORM
    assert_rows(
        world["arm"],
        ((0.0, -1.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0)),
    )
    expected_fore = ((0.0, -1.0, 0.0, 0.0), (1.0, 0.0, 0.0, 5.0), (0.0, 0.0, 1.0, 0.0))
    assert_rows(world["fore"], expected_fore)
    # A fixed joint is a rigid ride: the tip shares its parent's transform.
    assert_rows(world["tip"], expected_fore)
    assert transform_point(world["fore"], (1.0, 0.0, 0.0)) == pytest.approx(
        (0.0, 6.0, 0.0), abs=ABS
    )


def test_a_forest_with_a_static_part() -> None:
    """Two independent trees; a part in no joint entry is simply absent."""
    joints = [
        revolute("j-a", "base_a", "arm_a", (0.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
        JointFrame(
            id="j-b",
            kind="prismatic",
            parent="base_b",
            child="slide_b",
            point=(0.0, 0.0, 0.0),
            direction=(0.0, 0.0, 1.0),
        ),
    ]
    world = forward_kinematics(joints, {"j-a": 45.0, "j-b": 2.0})
    assert sorted(world) == ["arm_a", "base_a", "base_b", "slide_b"]
    # ``bystander`` is static exactly by not being in the forest: FK states
    # transforms only for parts a joint names, and never invents one.
    assert "bystander" not in world
    assert world["base_a"] == IDENTITY_TRANSFORM
    assert world["base_b"] == IDENTITY_TRANSFORM
    assert_rows(
        world["slide_b"],
        ((1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 1.0, 2.0)),
    )


def test_omitted_joints_evaluate_at_zero() -> None:
    """§3: joints absent from the assignment take their zero value."""
    joints = [
        revolute(
            "j-elbow",
            "arm_upper",
            "arm_fore",
            (10.0, 0.0, 0.0),
            (0.0, 0.0, 1.0),
            JointLimits(min=-5.0, max=150.0),
        )
    ]
    world = forward_kinematics(joints, {})
    assert world["arm_fore"] == IDENTITY_TRANSFORM


# ==========================================================================
# limits: refused by name, never clamped


def test_out_of_limits_is_a_named_refusal_with_id_value_and_limit() -> None:
    joint = revolute(
        "j-elbow",
        "arm_upper",
        "arm_fore",
        (10.0, 0.0, 0.0),
        (0.0, 0.0, 1.0),
        JointLimits(min=-5.0, max=150.0),
    )
    with pytest.raises(JointLimitError) as excinfo:
        forward_kinematics([joint], {"j-elbow": 150.5})
    error = excinfo.value
    assert error.reason == "joint_limit_exceeded"
    assert error.code == "joint_limit_exceeded"
    assert error.joint_id == "j-elbow"
    assert error.value == 150.5
    assert error.limit == JointLimits(min=-5.0, max=150.0)
    assert error.axis == "rotation"


def test_limits_are_inclusive_and_the_low_side_refuses_too() -> None:
    joint = JointFrame(
        id="j-slide",
        kind="prismatic",
        parent="rail",
        child="carriage",
        point=(0.0, 0.0, 0.0),
        direction=(1.0, 0.0, 0.0),
        limits=JointLimits(min=0.0, max=25.0),
    )
    # Both endpoints evaluate (inclusive window)…
    forward_kinematics([joint], {"j-slide": 0.0})
    forward_kinematics([joint], {"j-slide": 25.0})
    # …and one step past the floor is the same named refusal as the ceiling.
    with pytest.raises(JointLimitError) as excinfo:
        forward_kinematics([joint], {"j-slide": -0.001})
    assert excinfo.value.axis == "translation"
    assert excinfo.value.value == -0.001


def test_cylindrical_checks_both_limit_pairs() -> None:
    joint = JointFrame(
        id="j-spindle",
        kind="cylindrical",
        parent="housing",
        child="spindle",
        point=(0.0, 0.0, 0.0),
        direction=(0.0, 0.0, 1.0),
        limits=JointLimits(min=-180.0, max=180.0),
        travel_limits=JointLimits(min=0.0, max=10.0),
    )
    with pytest.raises(JointLimitError) as rotation:
        forward_kinematics([joint], {"j-spindle": (181.0, 5.0)})
    assert rotation.value.axis == "rotation"
    with pytest.raises(JointLimitError) as translation:
        forward_kinematics([joint], {"j-spindle": (90.0, 10.5)})
    assert translation.value.axis == "translation"


def test_an_implied_zero_outside_the_window_is_refused_not_clamped() -> None:
    """A window excluding zero cannot be silently evaluated at zero."""
    joint = revolute(
        "j-detent",
        "base",
        "lever",
        (0.0, 0.0, 0.0),
        (0.0, 0.0, 1.0),
        JointLimits(min=5.0, max=15.0),
    )
    with pytest.raises(JointLimitError) as excinfo:
        forward_kinematics([joint], {})
    assert excinfo.value.value == 0.0


# ==========================================================================
# malformed forests and assignments: closed-set named refusals


def reason_of(excinfo: pytest.ExceptionInfo[JointDeclarationError]) -> str:
    reason = excinfo.value.reason
    assert reason in JOINT_REFUSALS  # the set is closed, and every reason is in it
    return reason


def test_a_cycle_is_refused_with_the_cycle_named() -> None:
    joints = [
        revolute("j-1", "a", "b", (0.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
        revolute("j-2", "b", "c", (0.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
        revolute("j-3", "c", "a", (0.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    ]
    with pytest.raises(JointDeclarationError) as excinfo:
        forward_kinematics(joints, {})
    assert reason_of(excinfo) == "cyclic_joint_graph"
    assert set(excinfo.value.parts) >= {"a", "b", "c"}


def test_a_self_joint_is_the_length_one_cycle() -> None:
    joint = revolute("j-self", "a", "a", (0.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    with pytest.raises(JointDeclarationError) as excinfo:
        forward_kinematics([joint], {})
    assert reason_of(excinfo) == "cyclic_joint_graph"


def test_two_parents_for_one_part_break_the_forest() -> None:
    joints = [
        revolute("j-1", "a", "c", (0.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
        revolute("j-2", "b", "c", (0.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    ]
    with pytest.raises(JointDeclarationError) as excinfo:
        forward_kinematics(joints, {})
    assert reason_of(excinfo) == "multiple_parents"
    assert excinfo.value.parts == ("c",)


def test_assignment_and_shape_refusals_are_named() -> None:
    fixed = JointFrame(
        id="j-weld",
        kind="fixed",
        parent="a",
        child="b",
        point=(0.0, 0.0, 0.0),
        direction=(0.0, 0.0, 0.0),
    )
    spin = JointFrame(
        id="j-spin",
        kind="cylindrical",
        parent="b",
        child="c",
        point=(0.0, 0.0, 0.0),
        direction=(0.0, 0.0, 1.0),
    )
    turn = revolute("j-turn", "c", "d", (0.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    forest = [fixed, spin, turn]

    cases: list[tuple[dict[str, float | tuple[float, float]], str]] = [
        ({"j-ghost": 1.0}, "unknown_joint"),
        ({"j-weld": 0.0}, "value_for_fixed_joint"),
        ({"j-spin": 1.0}, "pair_value_required"),
        ({"j-turn": (1.0, 2.0)}, "scalar_value_required"),
    ]
    for values, expected in cases:
        with pytest.raises(JointDeclarationError) as excinfo:
            forward_kinematics(forest, values)
        assert reason_of(excinfo) == expected, values


def test_declaration_refusals_are_named() -> None:
    degenerate = revolute("j-flat", "a", "b", (0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    with pytest.raises(JointDeclarationError) as excinfo:
        forward_kinematics([degenerate], {"j-flat": 10.0})
    assert reason_of(excinfo) == "degenerate_direction"

    inverted = revolute(
        "j-back", "a", "b", (0.0, 0.0, 0.0), (0.0, 0.0, 1.0), JointLimits(min=5.0, max=-5.0)
    )
    with pytest.raises(JointDeclarationError) as excinfo:
        forward_kinematics([inverted], {})
    assert reason_of(excinfo) == "inverted_limits"

    spurious = JointFrame(
        id="j-weld",
        kind="fixed",
        parent="a",
        child="b",
        point=(0.0, 0.0, 0.0),
        direction=(0.0, 0.0, 0.0),
        limits=JointLimits(min=0.0, max=1.0),
    )
    with pytest.raises(JointDeclarationError) as excinfo:
        forward_kinematics([spurious], {})
    assert reason_of(excinfo) == "spurious_limits"

    twice = [
        revolute("j-dup", "a", "b", (0.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
        revolute("j-dup", "b", "c", (0.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    ]
    with pytest.raises(JointDeclarationError) as excinfo:
        forward_kinematics(twice, {})
    assert reason_of(excinfo) == "duplicate_joint_id"


def test_the_kind_set_is_the_closed_stage9_four() -> None:
    assert JOINT_KINDS == ("fixed", "revolute", "prismatic", "cylindrical")
    unknown = JointFrame(
        id="j-ball",
        kind=cast("Any", "ball"),  # deliberately outside the closed set
        parent="a",
        child="b",
        point=(0.0, 0.0, 0.0),
        direction=(0.0, 0.0, 1.0),
    )
    with pytest.raises(JointDeclarationError) as excinfo:
        forward_kinematics([unknown], {})
    assert reason_of(excinfo) == "unknown_kind"


# ==========================================================================
# applying a transform to a shape: rigid placement, never mutation


def test_transformed_shape_places_a_copy_and_never_mutates_the_input() -> None:
    shape = Pos(10.0, 0.0, 0.0) * Box(2.0, 2.0, 2.0)
    before_center = center_of(shape)
    before_volume = volume_of(shape)
    before_bbox = (tuple(shape.bounding_box().min), tuple(shape.bounding_box().max))

    turn = joint_transform(revolute("j-elbow", "a", "b", (0.0, 0.0, 0.0), (0.0, 0.0, 1.0)), 90.0)
    placed = transformed_shape(shape, turn)

    # The copy is where the hand-computed transform says: (10,0,0) -> (0,10,0).
    assert center_of(placed) == pytest.approx((0.0, 10.0, 0.0), abs=1e-6)
    assert volume_of(placed) == pytest.approx(before_volume, abs=1e-6)
    # The input still measures exactly as before — same center, volume, bbox.
    assert center_of(shape) == pytest.approx(before_center, abs=ABS)
    assert volume_of(shape) == pytest.approx(before_volume, abs=ABS)
    after_bbox = (tuple(shape.bounding_box().min), tuple(shape.bounding_box().max))
    for after_corner, before_corner in zip(after_bbox, before_bbox, strict=True):
        assert after_corner == pytest.approx(before_corner, abs=ABS)
    # And it is a distinct object, not the same shape handed back.
    assert placed is not shape


def test_transformed_shape_is_reusable_across_poses() -> None:
    """One loaded artifact, many poses: each placement starts from as-built."""
    shape = Pos(5.0, 0.0, 0.0) * Box(1.0, 1.0, 1.0)
    frame = revolute("j-turn", "a", "b", (0.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    at_90 = transformed_shape(shape, joint_transform(frame, 90.0))
    at_180 = transformed_shape(shape, joint_transform(frame, 180.0))
    assert center_of(at_90) == pytest.approx((0.0, 5.0, 0.0), abs=1e-6)
    assert center_of(at_180) == pytest.approx((-5.0, 0.0, 0.0), abs=1e-6)
    assert center_of(shape) == pytest.approx((5.0, 0.0, 0.0), abs=1e-6)


# ==========================================================================
# frame comparison: the numbers the engine compares against the epsilons


def test_frame_helpers_measure_axis_angle_and_radial_offset() -> None:
    # A 3-4-5 tilt in the x-z plane: hand angle = atan2(3, 4).
    import math

    angle = frame_axis_angle_deg((0.0, 0.0, 4.0), (3.0, 0.0, 4.0))
    assert angle == pytest.approx(math.degrees(math.atan2(3.0, 4.0)), abs=ABS)
    # Folded: an anti-parallel authored axis is the same line.
    assert frame_axis_angle_deg((0.0, 0.0, 1.0), (0.0, 0.0, -1.0)) == pytest.approx(0.0, abs=ABS)
    # Radial offset of (3, 4, 7) from the z line through the origin is 5.
    offset = frame_radial_offset_mm((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), (3.0, 4.0, 7.0))
    assert offset == pytest.approx(5.0, abs=ABS)
    # The named epsilons the engine's ``misaligned_joint_anchors`` keys on.
    assert JOINT_FRAME_EPS_DEG == 1e-3
    assert JOINT_FRAME_EPS_MM == 1e-3


# ==========================================================================
# determinism: two processes, identical transforms


_DETERMINISM_PROGRAM = textwrap.dedent(
    """
    import json

    from hephaestus.geom import JointFrame, JointLimits, forward_kinematics

    joints = [
        JointFrame(id="j-shoulder", kind="revolute", parent="base", child="arm",
                   point=(10.0, -2.0, 3.0), direction=(0.3, 0.4, 0.5),
                   limits=JointLimits(min=-90.0, max=90.0)),
        JointFrame(id="j-extend", kind="prismatic", parent="arm", child="fore",
                   point=(0.0, 0.0, 0.0), direction=(1.0, 2.0, 3.0),
                   limits=JointLimits(min=0.0, max=50.0)),
        JointFrame(id="j-wrist", kind="cylindrical", parent="fore", child="hand",
                   point=(1.0, 1.0, 1.0), direction=(0.0, 1.0, 0.0),
                   limits=JointLimits(min=-360.0, max=360.0),
                   travel_limits=JointLimits(min=-5.0, max=5.0)),
    ]
    world = forward_kinematics(
        joints, {"j-shoulder": 37.5, "j-extend": 12.25, "j-wrist": (-71.0, 2.5)}
    )
    print(json.dumps({part: t.rows for part, t in world.items()}, sort_keys=True))
    """
)


def test_two_processes_compute_identical_transforms() -> None:
    """Byte-identical printed matrices from two fresh interpreters."""
    runs = [
        subprocess.run(
            [sys.executable, "-c", _DETERMINISM_PROGRAM],
            capture_output=True,
            text=True,
            check=False,
        )
        for _ in range(2)
    ]
    for run in runs:
        assert run.returncode == 0, run.stderr
    assert runs[0].stdout == runs[1].stdout
    document = cast("dict[str, Any]", json.loads(runs[0].stdout))
    assert sorted(document) == ["arm", "base", "fore", "hand"]
