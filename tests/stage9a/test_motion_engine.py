# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""G9A: engine-side motion evaluation (``KINEMATICS.md`` §2).

The clauses under test are the ones that distinguish a ``MotionStatus`` from a
loop over forward kinematics:

* joint frames extract through every anchor form (tag, label, binding, whole
  part) and every frame source (cylindrical face, circular edge, planar face,
  linear edge), against REAL reloaded artifacts;
* the parent-frame rule: a deliberately offset child anchor *within* the named
  epsilons does not move the frame — the transform is the parent axis's, to
  1e-9 — and divergence *beyond* either epsilon is ``misaligned_joint_anchors``
  on exactly that side;
* every way of failing to resolve is NAMED and distinct, and the extended
  shape-class refusals ride ``shape_refused`` with their own reason tokens;
* per-POSE outcomes are their own section: ``orphaned_pose`` names the
  withdrawn joint, an unresolvable joint poisons exactly the poses that bind
  it, out-of-limit values are refused with geom's spelling, never clamped;
* evaluation records the ``MotionProjection`` and a rebuild of a forest part
  restales it (the ``AssemblyProjection`` precedent);
* two fresh processes measure identical statuses and identical transforms.

The joint forest below is wide on purpose: every child part rides exactly one
joint (the store enforces the forest), so each clause gets its own edge.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest
from _g9a import assumed, build_part, open_hinge_project, open_motion_project
from hephaestus.core.assembly import AnchorResolver
from hephaestus.core.motion import (
    JOINT_UNRESOLVABLE_REASONS,
    MotionEvaluator,
    MotionStatus,
    motion_resolution,
)
from hephaestus.core.project_store.kinematics import JointSet, PoseSet
from hephaestus.core.project_store.layout import ProjectLayout
from hephaestus.core.project_store.publication import Publisher

from opstore import OpStore

# --------------------------------------------------------------------------
# the declared mechanism (one forest, every clause its own edge)


def _declare_all(layout: ProjectLayout, store: OpStore) -> None:
    joints = JointSet(layout, store)
    poses = PoseSet(layout, store, joints)

    def joint(entry: dict[str, Any]) -> None:
        entry.setdefault("provenance", assumed())
        joints.declare(entry)

    # A joint declared, bound by a pose, then withdrawn: the orphan source.
    joint(
        {
            "id": "j-temp",
            "kind": "revolute",
            "parent": "base:hinge_bore",
            "child": "phantom_f:pin",
            "limits": {"min": -10.0, "max": 10.0},
        }
    )
    poses.declare({"id": "p-orphan", "joints": {"j-temp": 5.0}, "provenance": assumed()})
    joints.withdraw("j-temp", "the temporary hinge was dropped from the design")

    # Resolvable joints: every anchor form and every frame source.
    joint(
        {
            "id": "j-hinge",
            "kind": "revolute",
            "parent": "base:hinge_bore",  # tag -> cylindrical face
            "child": "arm:hinge_pin",  # tag -> cylindrical face, coaxial
            "limits": {"min": -90.0, "max": 90.0},
        }
    )
    joint(
        {
            "id": "j-off",
            "kind": "revolute",
            "parent": "base:base_body",  # label -> the bored solid's one axis
            "child": "probe_off:pin_face",  # 4e-4 mm off axis: inside EPS_MM
            "limits": {"min": -180.0, "max": 180.0},
        }
    )
    joint(
        {
            "id": "j-far",
            "kind": "revolute",
            "parent": "base:hinge_bore",
            "child": "probe_far:pin_face",  # 0.5 mm off axis: beyond EPS_MM
            "limits": {"min": -10.0, "max": 10.0},
        }
    )
    joint(
        {
            "id": "j-tilt",
            "kind": "revolute",
            "parent": "base:hinge_bore",
            "child": "probe_tilt:pin_face",  # 0.05 deg tilt: beyond EPS_DEG
            "limits": {"min": -10.0, "max": 10.0},
        }
    )
    joint(
        {
            "id": "j-teps",
            "kind": "cylindrical",
            "parent": "base:hinge_bore",
            "child": "probe_teps:pin_face",  # 5e-4 deg tilt: inside EPS_DEG
            "limits": {
                "rotation": {"min": -180.0, "max": 180.0},
                "translation": {"min": -5.0, "max": 5.0},
            },
        }
    )
    joint(
        {
            "id": "j-slide",
            "kind": "prismatic",
            "parent": "base:slide_face",  # tag -> planar face (normal +Z)
            "child": "slider:foot_face",  # planar face (normal -Z, folded 0)
            "limits": {"min": 0.0, "max": 10.0},
        }
    )
    joint(
        {
            "id": "j-edge",
            "kind": "prismatic",
            "parent": "base:slide_edge",  # tag -> linear edge (Z tangent)
            "child": "slider2:foot_face",
            "limits": {"min": 0.0, "max": 10.0},
        }
    )
    joint(
        {
            "id": "j-knob",
            "kind": "revolute",
            "parent": "base:bore_rim",  # tag -> CIRCULAR EDGE (axis form)
            "child": "knob:knob_body",  # binding, label-filled (§5.1)
            "limits": {"min": -180.0, "max": 180.0},
        }
    )
    joint({"id": "j-fix", "kind": "fixed", "parent": "base", "child": "clip"})

    # Unresolvable joints: each reason its own edge, each fault the FIRST one.
    joint(
        {
            "id": "j-ghost",
            "kind": "revolute",
            "parent": "ghost:hinge_bore",  # no such part
            "child": "phantom_a:pin",
            "limits": {"min": 0.0, "max": 1.0},
        }
    )
    joint(
        {
            "id": "j-unbuilt",
            "kind": "revolute",
            "parent": "base:hinge_bore",
            "child": "unbuilt:pin",  # declared part, never built
            "limits": {"min": 0.0, "max": 1.0},
        }
    )
    joint(
        {
            "id": "j-dangle",
            "kind": "revolute",
            "parent": "base:no_such_tag",  # dangling selector
            "child": "phantom_b:pin",
            "limits": {"min": 0.0, "max": 1.0},
        }
    )
    joint(
        {
            "id": "j-plane",
            "kind": "revolute",
            # The stop cube's top: a pure rectangle, no cylindrical face and
            # no circular edge, so it names no axis. (``slide_face`` would
            # NOT do: the bore's rim is a circular edge of that face, and a
            # bored face legitimately names its bore's axis.)
            "parent": "base:stop_top",
            "child": "phantom_c:pin",
            "limits": {"min": 0.0, "max": 1.0},
        }
    )
    joint(
        {
            "id": "j-baddir",
            "kind": "prismatic",
            "parent": "base:hinge_bore",  # cylindrical face names no direction
            "child": "phantom_d:pin",
            "limits": {"min": 0.0, "max": 1.0},
        }
    )
    joint(
        {
            "id": "j-ambig",
            "kind": "revolute",
            "parent": "arm",  # whole part: pin axis AND spike axis
            "child": "phantom_e:pin",
            "limits": {"min": 0.0, "max": 1.0},
        }
    )

    poses.declare({"id": "p-zero", "joints": {}, "provenance": assumed()})
    poses.declare({"id": "p-swung", "joints": {"j-hinge": -90.0}, "provenance": assumed()})
    poses.declare({"id": "p-lift", "joints": {"j-slide": 4.0}, "provenance": assumed()})
    poses.declare({"id": "p-probe", "joints": {"j-off": 90.0}, "provenance": assumed()})
    poses.declare({"id": "p-over", "joints": {"j-hinge": 120.0}, "provenance": assumed()})
    poses.declare({"id": "p-broken", "joints": {"j-far": 0.0}, "provenance": assumed()})
    poses.declare({"id": "p-cyl", "joints": {"j-teps": 10.0}, "provenance": assumed()})


@pytest.fixture(scope="module")
def project(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[ProjectLayout, OpStore]]:
    layout, store = open_motion_project(tmp_path_factory.mktemp("mech") / "proj")
    _declare_all(layout, store)
    yield layout, store
    store.close()


@pytest.fixture(scope="module")
def status(project: tuple[ProjectLayout, OpStore]) -> MotionStatus:
    layout, store = project
    return MotionEvaluator(layout, store).evaluate()


def _joint(status: MotionStatus, joint_id: str) -> Any:
    return next(outcome for outcome in status.joints if outcome.id == joint_id)


def _pose(status: MotionStatus, pose_id: str) -> Any:
    return next(outcome for outcome in status.poses if outcome.id == pose_id)


# ==========================================================================
# frame extraction: every anchor form, every frame source


class TestFrameExtraction:
    def test_tag_anchored_axis_joint_resolves(self, status: MotionStatus) -> None:
        outcome = _joint(status, "j-hinge")
        assert outcome.state == "resolved"
        assert outcome.reason is None and outcome.detail is None
        assert outcome.parent.rule == "tag" and outcome.child.rule == "tag"
        assert outcome.parent.artifact_ref is not None
        assert outcome.child.artifact_ref is not None

    def test_label_anchor_supplies_the_frame(self, status: MotionStatus) -> None:
        outcome = _joint(status, "j-off")
        assert outcome.state == "resolved"
        assert outcome.parent.rule == "label"

    def test_binding_anchor_and_circular_edge_supply_the_frame(self, status: MotionStatus) -> None:
        outcome = _joint(status, "j-knob")
        assert outcome.state == "resolved"
        assert outcome.parent.rule == "tag"  # the tag names a CIRCULAR EDGE
        assert outcome.child.rule in ("label", "binding")  # §5.1 label-fill

    def test_prismatic_direction_from_planar_face_and_linear_edge(
        self, status: MotionStatus
    ) -> None:
        assert _joint(status, "j-slide").state == "resolved"
        assert _joint(status, "j-edge").state == "resolved"

    def test_cylindrical_kind_resolves(self, status: MotionStatus) -> None:
        assert _joint(status, "j-teps").state == "resolved"

    def test_fixed_accepts_any_resolvable_anchor(self, status: MotionStatus) -> None:
        outcome = _joint(status, "j-fix")
        assert outcome.state == "resolved"
        assert outcome.parent.rule == "part" and outcome.child.rule == "part"


# ==========================================================================
# the parent-frame rule and its epsilons


class TestParentFrameRule:
    def test_offset_child_within_epsilon_does_not_move_the_frame(
        self, project: tuple[ProjectLayout, OpStore]
    ) -> None:
        """``j-off``'s child axis sits 4e-4 mm off the bore axis; the frame is
        the PARENT's, so a 90 deg turn is a rotation about the exact bore axis
        (through the origin, +Z) — not about the child's offset axis, which
        would displace the translation column by ~8e-4 mm."""
        layout, store = project
        with tempfile.TemporaryDirectory() as tmp:
            resolver = AnchorResolver(layout, store, Publisher(layout, store), Path(tmp))
            resolution = motion_resolution(layout, store, resolver)
            placed = resolution.transforms("p-probe", ("probe_off", "base"))
        expected = ((0.0, -1.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0))
        for row, want in zip(placed["probe_off"].rows, expected, strict=True):
            for value, target in zip(row, want, strict=True):
                assert value == pytest.approx(target, abs=1e-9)
        # The root part is static: the identity, exactly.
        assert placed["base"].rows == (
            (1.0, 0.0, 0.0, 0.0),
            (0.0, 1.0, 0.0, 0.0),
            (0.0, 0.0, 1.0, 0.0),
        )

    def test_hinge_and_slide_transforms_match_hand_matrices(
        self, project: tuple[ProjectLayout, OpStore]
    ) -> None:
        layout, store = project
        with tempfile.TemporaryDirectory() as tmp:
            resolver = AnchorResolver(layout, store, Publisher(layout, store), Path(tmp))
            resolution = motion_resolution(layout, store, resolver)
            swung = resolution.transforms("p-swung", ("arm",))["arm"]
            lifted = resolution.transforms("p-lift", ("slider",))["slider"]
        # R(-90 deg) about +Z through the origin: t = p - Rp = 0.
        expected = ((0.0, 1.0, 0.0, 0.0), (-1.0, 0.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0))
        for row, want in zip(swung.rows, expected, strict=True):
            for value, target in zip(row, want, strict=True):
                assert value == pytest.approx(target, abs=1e-9)
        # 4 mm along the slide face's +Z normal: a pure translation.
        expected_lift = ((1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 1.0, 4.0))
        for row, want in zip(lifted.rows, expected_lift, strict=True):
            for value, target in zip(row, want, strict=True):
                assert value == pytest.approx(target, abs=1e-9)

    def test_misaligned_on_both_sides_of_both_epsilons(self, status: MotionStatus) -> None:
        # mm epsilon: 0.5 mm beyond refuses, 4e-4 mm within resolves.
        far = _joint(status, "j-far")
        assert far.state == "unresolvable"
        assert far.reason == "misaligned_joint_anchors"
        assert far.detail is not None and "radial offset" in far.detail
        assert "JOINT_FRAME_EPS_MM" in far.detail
        assert _joint(status, "j-off").state == "resolved"
        # deg epsilon: 0.05 deg beyond refuses, 5e-4 deg within resolves.
        tilt = _joint(status, "j-tilt")
        assert tilt.state == "unresolvable"
        assert tilt.reason == "misaligned_joint_anchors"
        assert tilt.detail is not None and "axis angle" in tilt.detail
        assert "JOINT_FRAME_EPS_DEG" in tilt.detail
        assert _joint(status, "j-teps").state == "resolved"


# ==========================================================================
# unresolvable joints: every reason named, every reason distinct


class TestUnresolvableJoints:
    def test_each_reason_is_named_and_distinct(self, status: MotionStatus) -> None:
        reasons = {
            joint_id: _joint(status, joint_id).reason
            for joint_id in ("j-ghost", "j-unbuilt", "j-dangle", "j-plane", "j-baddir", "j-ambig")
        }
        assert reasons == {
            "j-ghost": "missing_part",
            "j-unbuilt": "no_current_build",
            "j-dangle": "dangling_selector",
            "j-plane": "shape_refused",
            "j-baddir": "shape_refused",
            "j-ambig": "shape_refused",
        }
        assert set(reasons.values()) <= set(JOINT_UNRESOLVABLE_REASONS)

    def test_shape_refusals_carry_the_extended_taxonomy(self, status: MotionStatus) -> None:
        assert "not_axial" in (_joint(status, "j-plane").detail or "")
        assert "not_directional" in (_joint(status, "j-baddir").detail or "")
        assert "ambiguous_axis" in (_joint(status, "j-ambig").detail or "")

    def test_faults_name_the_side_that_failed(self, status: MotionStatus) -> None:
        assert (_joint(status, "j-unbuilt").detail or "").startswith("anchor child")
        assert (_joint(status, "j-dangle").detail or "").startswith("anchor parent")
        # Parent-first: the frame owner's refusal fires before the child part
        # (which does not even exist) is looked at.
        assert (_joint(status, "j-plane").detail or "").startswith("anchor parent")

    def test_withdrawn_joints_are_never_evaluated(self, status: MotionStatus) -> None:
        assert "j-temp" not in {outcome.id for outcome in status.joints}


# ==========================================================================
# per-pose outcomes: the second section of the status


class TestPoseOutcomes:
    def test_resolvable_poses_resolve(self, status: MotionStatus) -> None:
        for pose_id in ("p-zero", "p-swung", "p-lift", "p-probe"):
            assert _pose(status, pose_id).state == "resolved", pose_id

    def test_out_of_limit_value_is_refused_never_clamped(self, status: MotionStatus) -> None:
        outcome = _pose(status, "p-over")
        assert outcome.state == "unresolvable"
        assert outcome.reason == "joint_limit_exceeded"
        assert "120" in (outcome.detail or "") and "not clamped" in (outcome.detail or "")

    def test_unresolvable_joint_poisons_exactly_the_poses_that_bind_it(
        self, status: MotionStatus
    ) -> None:
        outcome = _pose(status, "p-broken")
        assert outcome.state == "unresolvable"
        assert outcome.reason == "unresolvable_joint"
        assert "j-far" in (outcome.detail or "")
        # ...and no further: p-zero binds nothing and stays resolved above.

    def test_orphaned_pose_names_the_withdrawn_joint(self, status: MotionStatus) -> None:
        outcome = _pose(status, "p-orphan")
        assert outcome.state == "unresolvable"
        assert outcome.reason == "orphaned_pose"
        assert "j-temp" in (outcome.detail or "")

    def test_scalar_binding_of_a_cylindrical_joint_is_refused_by_name(
        self, status: MotionStatus
    ) -> None:
        outcome = _pose(status, "p-cyl")
        assert outcome.state == "unresolvable"
        assert outcome.reason == "invalid_pose"
        assert "pair" in (outcome.detail or "")

    def test_blocking_lists_every_unresolvable_id(self, status: MotionStatus) -> None:
        blocking = set(status.blocking())
        assert {"j-far", "j-tilt", "j-ghost", "p-over", "p-broken", "p-orphan"} <= blocking
        assert "j-hinge" not in blocking and "p-zero" not in blocking


# ==========================================================================
# projection: recorded, readable, restaled by a forest part's rebuild


class TestProjection:
    def test_evaluate_records_a_readable_projection(
        self, project: tuple[ProjectLayout, OpStore], status: MotionStatus
    ) -> None:
        layout, store = project
        evaluator = MotionEvaluator(layout, store)
        ref = evaluator.projected_ref()
        assert ref is not None and ref.startswith("artifact:motion-status:sha256:")
        projected = evaluator.projected()
        assert projected is not None
        assert projected.joint_generation == status.joint_generation
        assert projected.pose_generation == status.pose_generation
        assert {o.id: o.state for o in projected.joints} == {o.id: o.state for o in status.joints}

    def test_rebuilding_a_forest_part_restales_the_projection(
        self, project: tuple[ProjectLayout, OpStore], status: MotionStatus
    ) -> None:
        layout, store = project
        # slider2 rides j-edge, so its rebuild into DIFFERENT geometry moves
        # its artifact ref and must restale the motion projection.
        script = (layout.root / "parts" / "slider2.py").read_text(encoding="utf-8")
        (layout.root / "parts" / "slider2.py").write_text(
            script.replace("Pos(12.0, -14.0, 5.5)", "Pos(12.5, -14.0, 5.5)"), encoding="utf-8"
        )
        build_part(Publisher(layout, store), layout, "slider2")
        projected = MotionEvaluator(layout, store).projected()
        assert projected is not None
        assert projected.stale == ("slider2",)
        # The stale status is still READABLE — stale never reads as "never
        # evaluated" (the GC edge from the state blob keeps the document).
        assert {o.id for o in projected.joints} == {o.id for o in status.joints}


# ==========================================================================
# determinism: two fresh processes, identical statuses, identical transforms

_DETERMINISM_PROGRAM = """
import json, sys
from pathlib import Path

from hephaestus.core.assembly import AnchorResolver
from hephaestus.core.motion import check_motion, motion_resolution
from hephaestus.core.project_store.layout import load_project, open_store
from hephaestus.core.project_store.publication import Publisher
from opstore import canonical_json
import tempfile

layout = load_project(Path(sys.argv[1]))
store = open_store(layout)
status = check_motion(layout, store, record=False)
with tempfile.TemporaryDirectory() as tmp:
    resolver = AnchorResolver(layout, store, Publisher(layout, store), Path(tmp))
    resolution = motion_resolution(layout, store, resolver)
    placed = resolution.transforms("p-swung", ("arm", "base"))
document = {
    "status": status.to_json(),
    "transforms": {part: list(list(row) for row in placed[part].rows) for part in sorted(placed)},
}
print(canonical_json(document))
store.close()
"""


def test_two_processes_compute_identical_statuses_and_transforms(tmp_path: Path) -> None:
    layout, store = open_hinge_project(tmp_path / "proj")
    joints = JointSet(layout, store)
    poses = PoseSet(layout, store, joints)
    joints.declare(
        {
            "id": "j-hinge",
            "kind": "revolute",
            "parent": "base:hinge_bore",
            "child": "arm:hinge_pin",
            "limits": {"min": -90.0, "max": 90.0},
            "provenance": assumed(),
        }
    )
    poses.declare({"id": "p-swung", "joints": {"j-hinge": -90.0}, "provenance": assumed()})
    store.close()  # the subprocesses open the same store

    def run() -> str:
        result = subprocess.run(
            [sys.executable, "-c", _DETERMINISM_PROGRAM, str(layout.root)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout

    first, second = run(), run()
    # Byte-identical is the strongest form of the clause: nothing between the
    # published artifact and the printed transform may vary run to run.
    assert first == second
    document: Mapping[str, Any] = json.loads(first)
    assert document["status"]["joints"][0]["state"] == "resolved"
    rows = document["transforms"]["arm"]
    expected = [[0.0, 1.0, 0.0, 0.0], [-1.0, 0.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0]]
    for row, want in zip(rows, expected, strict=True):
        for value, target in zip(row, want, strict=True):
            assert value == pytest.approx(target, abs=1e-9)
