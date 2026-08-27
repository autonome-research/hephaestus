# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""G9C: couplings — declared transmissions, composed through FK (``KINEMATICS.md`` §5).

The Gate G9C Tier 1 clauses this file carries (the Tier 3 bench clause is a
separate detached run, per the gate):

* *coupling composition through FK, against hand-computed derived values* —
  pure arithmetic at the geom seam (``derive_coupled_values``, chains
  included), a hand-built forest where the derived child value rides forward
  kinematics exactly, and the REAL path: a pose over published BReps whose
  coupled slider lands on the hand matrix to 1e-9, and a sweep whose measured
  clearance moves exactly as ``child = ratio * parent + offset`` predicts;
* *dependent-parameter assignment refusal* — a pose declaration AND a sweep
  declaration over a coupled child are refused naming the coupling (a pose or
  sweep assigns only FREE parameters), and a coupling declared AFTER a pose
  bound its child is the evaluation-time state instead (the ``orphaned_pose``
  philosophy: reported by name, never re-refused, never erased);
* *``cyclic_coupling`` with the cycle named*, at declaration and at update —
  a self-coupling being the length-1 case;
* *the one-driver rule* — a second coupling naming an already-coupled child
  is refused naming the first;
* *derived-value limit refusal naming the coupling* — coupled values are
  derived BEFORE limit checks, and a derived value outside the child's
  declared limits is ``joint_limit_exceeded`` with the coupling id in the
  detail, at pose evaluation and per sweep sample alike — never clamped;
* *generational declare/update/withdraw with provenance compulsion*
  (``invalid_coupling``), replayable from each generation's own artifact ref;
* *``read_couplings`` returning withdrawn entries with their reasons*,
  engine-side and through the tool;
* *the coupling triplet through dispatch on both declared profiles* (part +
  orchestrator, the 8C quartet decision unchanged; reviewer and quick-edit
  refused ``scope_denied``);
* *the coupling table in ``heph motion`` and its ``--json`` form*.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, cast

import pytest
from _g9c import (
    DRIVE_RATIO_MM_PER_DEG,
    SLIDER_BASE_GAP_MM,
    assumed,
    make_project,
    open_coupling_project,
)
from hephaestus.core.assembly import AnchorResolver
from hephaestus.core.motion import MotionEvaluator, MotionStatus, SweepEvaluator, motion_resolution
from hephaestus.core.project_store.kinematics import (
    CouplingError,
    CouplingSet,
    JointSet,
    MotionCheckError,
    MotionCheckSet,
    PoseError,
    PoseSet,
)
from hephaestus.core.project_store.layout import (
    ProjectLayout,
    ProjectManifest,
    open_store,
)
from hephaestus.core.project_store.publication import Publisher
from hephaestus.geom import (
    Coupling,
    JointDeclarationError,
    JointFrame,
    JointLimits,
    derive_coupled_values,
    forward_kinematics,
)

from opstore import OpStore

# ==========================================================================
# the geom seam: pure arithmetic, named structural refusals


class TestDeriveArithmetic:
    def test_hand_computed_derivation_including_a_chain(self) -> None:
        """child = ratio * parent + offset, composed driver-first (§5)."""
        couplings = (
            Coupling(id="cp-ab", parent="j-a", child="j-b", ratio=0.5, offset=2.0),
            Coupling(id="cp-bc", parent="j-b", child="j-c", ratio=2.0, offset=-1.0),
        )
        full = derive_coupled_values(couplings, {"j-a": 10.0})
        assert full == {"j-a": 10.0, "j-b": 7.0, "j-c": 13.0}

    def test_an_unassigned_parent_sits_at_its_zero(self) -> None:
        """§3: joints omitted take zero, so the child derives from 0.0 — an
        offset alone still moves it, which is why derivation cannot be skipped
        for poses that never mention the parent."""
        coupling = Coupling(id="cp-ab", parent="j-a", child="j-b", ratio=3.0, offset=1.5)
        assert derive_coupled_values((coupling,), {}) == {"j-b": 1.5}

    def test_assigning_a_coupled_child_is_refused_by_name(self) -> None:
        coupling = Coupling(id="cp-ab", parent="j-a", child="j-b", ratio=1.0, offset=0.0)
        with pytest.raises(JointDeclarationError) as excinfo:
            derive_coupled_values((coupling,), {"j-b": 4.0})
        assert excinfo.value.reason == "coupled_child_assigned"
        assert "cp-ab" in excinfo.value.message and "FREE" in excinfo.value.message

    def test_a_cycle_is_refused_with_the_cycle_named(self) -> None:
        couplings = (
            Coupling(id="cp-ab", parent="j-a", child="j-b", ratio=1.0, offset=0.0),
            Coupling(id="cp-ba", parent="j-b", child="j-a", ratio=1.0, offset=0.0),
        )
        with pytest.raises(JointDeclarationError) as excinfo:
            derive_coupled_values(couplings, {})
        assert excinfo.value.reason == "cyclic_coupling"
        for name in ("j-a", "j-b", "cp-ab", "cp-ba"):
            assert name in excinfo.value.message

    def test_one_driver_per_child(self) -> None:
        couplings = (
            Coupling(id="cp-1", parent="j-a", child="j-b", ratio=1.0, offset=0.0),
            Coupling(id="cp-2", parent="j-c", child="j-b", ratio=1.0, offset=0.0),
        )
        with pytest.raises(JointDeclarationError) as excinfo:
            derive_coupled_values(couplings, {})
        assert excinfo.value.reason == "duplicate_coupling_child"
        assert "cp-1" in excinfo.value.message and "cp-2" in excinfo.value.message

    def test_the_derived_value_rides_forward_kinematics(self) -> None:
        """Hand forest: a revolute driver and a prismatic child it drives.

        ``j-b = 2 * j-a + 1`` at ``j-a = 30`` is exactly 61 mm along +X, so
        the ram's world transform must be that pure translation — the §5
        composition through the SAME forest evaluation, nothing bespoke.
        """
        frames = (
            JointFrame(
                id="j-a",
                kind="revolute",
                parent="base",
                child="rotor",
                point=(0.0, 0.0, 0.0),
                direction=(0.0, 0.0, 1.0),
                limits=JointLimits(min=-180.0, max=180.0),
            ),
            JointFrame(
                id="j-b",
                kind="prismatic",
                parent="base",
                child="ram",
                point=(0.0, 0.0, 0.0),
                direction=(1.0, 0.0, 0.0),
                limits=JointLimits(min=-100.0, max=100.0),
            ),
        )
        coupling = Coupling(id="cp-feed", parent="j-a", child="j-b", ratio=2.0, offset=1.0)
        full = derive_coupled_values((coupling,), {"j-a": 30.0})
        assert full["j-b"] == pytest.approx(61.0)
        world = forward_kinematics(frames, cast("Mapping[str, Any]", full))
        assert world["ram"].rows == (
            (1.0, 0.0, 0.0, 61.0),
            (0.0, 1.0, 0.0, 0.0),
            (0.0, 0.0, 1.0, 0.0),
        )


# ==========================================================================
# the ledger: the fourth rider on the pattern


@pytest.fixture
def sets(tmp_path: Path) -> tuple[JointSet, PoseSet, MotionCheckSet, CouplingSet]:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "hephaestus.toml").write_text('name = "kin"\n', encoding="utf-8")
    layout = ProjectLayout(root=root, manifest=ProjectManifest(name="kin"))
    store = open_store(layout)
    joints = JointSet(layout, store)
    return (
        joints,
        PoseSet(layout, store, joints),
        MotionCheckSet(layout, store, joints),
        CouplingSet(layout, store, joints),
    )


def declare_scalar_joints(joints: JointSet, *ids: str) -> None:
    """Structurally-valid revolute joints, one per id, each on its own parts."""
    for index, joint_id in enumerate(ids):
        joints.declare(
            {
                "id": joint_id,
                "kind": "revolute",
                "parent": f"part{index}a:bore",
                "child": f"part{index}b:pin",
                "limits": {"min": -180.0, "max": 180.0},
                "provenance": assumed(),
            }
        )


def coupling_entry(**overrides: Any) -> dict[str, Any]:
    """The §5 worked-example shape with fields replaced (or removed via None)."""
    out: dict[str, Any] = {
        "id": "cp-wrist-drive",
        "parent": "j-motor",
        "child": "j-wrist",
        "ratio": 0.2,
        "offset": 0.0,
        "provenance": {"requirement": "r-8"},
    }
    for key, value in overrides.items():
        if value is None:
            out.pop(key, None)
        else:
            out[key] = value
    return out


class TestCouplingGenerations:
    def test_declare_update_withdraw_replay_from_their_own_refs(
        self, sets: tuple[JointSet, PoseSet, MotionCheckSet, CouplingSet]
    ) -> None:
        joints, _poses, _checks, couplings = sets
        declare_scalar_joints(joints, "j-motor", "j-wrist")
        declared = couplings.declare(coupling_entry())
        revised = couplings.update("cp-wrist-drive", {"ratio": 0.25}, "gearing revised to 4:1")
        withdrawn = couplings.withdraw("cp-wrist-drive", "the wrist is now direct-driven")
        assert [declared.generation, revised.generation, withdrawn.generation] == [1, 2, 3]

        # Each act recorded WHAT it was and WHY, with its own immutable ref.
        assert declared.change is not None and declared.change.kind == "declare"
        assert revised.change is not None and revised.change.reason == "gearing revised to 4:1"
        assert withdrawn.change is not None and withdrawn.change.kind == "withdraw"
        refs = [state.artifact_ref for state in (declared, revised, withdrawn)]
        assert len({ref for ref in refs if ref is not None}) == 3
        assert all(ref is not None and ref.startswith("artifact:couplings:sha256:") for ref in refs)

        # Replay: the generation each ref names still says what it said then.
        replayed = [couplings.generation(ref) for ref in refs if ref is not None]
        assert replayed[0].entries[0].ratio == pytest.approx(0.2)
        assert replayed[1].entries[0].ratio == pytest.approx(0.25)
        assert replayed[2].entries[0].withdrawn is True
        assert replayed[2].entries[0].withdrawn_reason == "the wrist is now direct-driven"
        assert replayed[2].active == ()
        assert [state.generation for state in couplings.history()] == [1, 2, 3]

    def test_a_repeated_id_is_refused_not_replaced(
        self, sets: tuple[JointSet, PoseSet, MotionCheckSet, CouplingSet]
    ) -> None:
        joints, _poses, _checks, couplings = sets
        declare_scalar_joints(joints, "j-motor", "j-wrist")
        couplings.declare(coupling_entry())
        with pytest.raises(CouplingError) as excinfo:
            couplings.declare(coupling_entry(ratio=0.5))
        assert excinfo.value.reason == "invalid_coupling"
        assert couplings.state().generation == 1

    def test_an_unknown_id_is_its_own_refusal_token(
        self, sets: tuple[JointSet, PoseSet, MotionCheckSet, CouplingSet]
    ) -> None:
        _joints, _poses, _checks, couplings = sets
        with pytest.raises(CouplingError) as patching:
            couplings.update("cp-ghost", {"ratio": 1.0}, "x")
        assert patching.value.reason == "unknown_coupling"
        with pytest.raises(CouplingError) as withdrawing:
            couplings.withdraw("cp-ghost", "x")
        assert withdrawing.value.reason == "unknown_coupling"

    @pytest.mark.parametrize(
        ("case", "provenance"),
        [
            ("no provenance at all", None),
            ("an empty provenance object", {}),
            ("assumed with no reason", {"assumed": True}),
            ("cited and assumed at once", {"requirement": "r-8", "assumed": True}),
        ],
    )
    def test_provenance_is_compelled(
        self,
        sets: tuple[JointSet, PoseSet, MotionCheckSet, CouplingSet],
        case: str,
        provenance: Mapping[str, Any] | None,
    ) -> None:
        """A ratio is an interpretation of intent, so it says whose — or refuses."""
        joints, _poses, _checks, couplings = sets
        declare_scalar_joints(joints, "j-motor", "j-wrist")
        with pytest.raises(CouplingError) as excinfo:
            couplings.declare(coupling_entry(provenance=provenance))
        assert excinfo.value.reason == "invalid_coupling", case
        assert (couplings.state().generation, couplings.state().entries) == (0, ()), case


class TestCouplingValidation:
    def test_joint_ids_not_anchors(
        self, sets: tuple[JointSet, PoseSet, MotionCheckSet, CouplingSet]
    ) -> None:
        """§5: parent/child are joint PARAMETERS — an anchor spelling is refused."""
        joints, _poses, _checks, couplings = sets
        declare_scalar_joints(joints, "j-motor", "j-wrist")
        with pytest.raises(CouplingError) as excinfo:
            couplings.declare(coupling_entry(parent="part0a:bore"))
        assert excinfo.value.reason == "invalid_coupling"
        assert "joint id" in excinfo.value.args[0]

    def test_unknown_and_withdrawn_joints_are_refused(
        self, sets: tuple[JointSet, PoseSet, MotionCheckSet, CouplingSet]
    ) -> None:
        joints, _poses, _checks, couplings = sets
        declare_scalar_joints(joints, "j-motor", "j-wrist")
        with pytest.raises(CouplingError) as unknown:
            couplings.declare(coupling_entry(child="j-ghost"))
        assert unknown.value.reason == "invalid_coupling"
        assert "j-motor" in unknown.value.args[0]  # the ids that DO exist are named
        joints.withdraw("j-wrist", "the wrist became a fixed mount")
        with pytest.raises(CouplingError) as withdrawn:
            couplings.declare(coupling_entry())
        assert withdrawn.value.reason == "invalid_coupling"
        assert "withdrawn" in withdrawn.value.args[0]

    @pytest.mark.parametrize(
        ("kind", "limits"),
        [
            ("fixed", None),
            (
                "cylindrical",
                {
                    "rotation": {"min": -180.0, "max": 180.0},
                    "translation": {"min": 0.0, "max": 10.0},
                },
            ),
        ],
    )
    def test_a_joint_without_one_scalar_dof_cannot_be_coupled(
        self,
        sets: tuple[JointSet, PoseSet, MotionCheckSet, CouplingSet],
        kind: str,
        limits: Mapping[str, Any] | None,
    ) -> None:
        joints, _poses, _checks, couplings = sets
        declare_scalar_joints(joints, "j-motor")
        entry: dict[str, Any] = {
            "id": "j-odd",
            "kind": kind,
            "parent": "odd_a:bore",
            "child": "odd_b:pin",
            "provenance": assumed(),
        }
        if limits is not None:
            entry["limits"] = limits
        joints.declare(entry)
        with pytest.raises(CouplingError) as excinfo:
            couplings.declare(coupling_entry(parent="j-motor", child="j-odd"))
        assert excinfo.value.reason == "invalid_coupling"
        assert kind in excinfo.value.args[0]

    def test_a_zero_ratio_is_refused(
        self, sets: tuple[JointSet, PoseSet, MotionCheckSet, CouplingSet]
    ) -> None:
        joints, _poses, _checks, couplings = sets
        declare_scalar_joints(joints, "j-motor", "j-wrist")
        with pytest.raises(CouplingError) as excinfo:
            couplings.declare(coupling_entry(ratio=0.0))
        assert "nonzero" in excinfo.value.args[0]

    def test_one_driver_per_joint(
        self, sets: tuple[JointSet, PoseSet, MotionCheckSet, CouplingSet]
    ) -> None:
        joints, _poses, _checks, couplings = sets
        declare_scalar_joints(joints, "j-motor", "j-wrist", "j-aux")
        couplings.declare(coupling_entry())
        before = couplings.state().generation
        with pytest.raises(CouplingError) as excinfo:
            couplings.declare(
                coupling_entry(id="cp-second", parent="j-aux", child="j-wrist", ratio=1.0)
            )
        assert excinfo.value.reason == "invalid_coupling"
        assert "cp-wrist-drive" in excinfo.value.args[0]  # the first driver is named
        assert couplings.state().generation == before

    def test_a_cycle_is_refused_at_declaration_with_the_cycle_named(
        self, sets: tuple[JointSet, PoseSet, MotionCheckSet, CouplingSet]
    ) -> None:
        joints, _poses, _checks, couplings = sets
        declare_scalar_joints(joints, "j-a", "j-b", "j-c")
        couplings.declare(coupling_entry(id="cp-ab", parent="j-a", child="j-b", ratio=2.0))
        couplings.declare(coupling_entry(id="cp-bc", parent="j-b", child="j-c", ratio=2.0))
        before = couplings.state().generation
        with pytest.raises(CouplingError) as excinfo:
            couplings.declare(coupling_entry(id="cp-ca", parent="j-c", child="j-a", ratio=2.0))
        assert excinfo.value.reason == "cyclic_coupling"
        message = excinfo.value.args[0]
        for name in ("j-a", "j-b", "j-c", "cp-ca"):
            assert name in message
        assert couplings.state().generation == before

    def test_a_self_coupling_is_the_length_one_cycle(
        self, sets: tuple[JointSet, PoseSet, MotionCheckSet, CouplingSet]
    ) -> None:
        joints, _poses, _checks, couplings = sets
        declare_scalar_joints(joints, "j-motor")
        with pytest.raises(CouplingError) as excinfo:
            couplings.declare(coupling_entry(parent="j-motor", child="j-motor"))
        assert excinfo.value.reason == "cyclic_coupling"

    def test_a_rechilding_update_is_cycle_checked(
        self, sets: tuple[JointSet, PoseSet, MotionCheckSet, CouplingSet]
    ) -> None:
        joints, _poses, _checks, couplings = sets
        declare_scalar_joints(joints, "j-a", "j-b", "j-c")
        couplings.declare(coupling_entry(id="cp-ab", parent="j-a", child="j-b", ratio=2.0))
        couplings.declare(coupling_entry(id="cp-bc", parent="j-b", child="j-c", ratio=2.0))
        with pytest.raises(CouplingError) as excinfo:
            couplings.update("cp-ab", {"parent": "j-c"}, "reroute the drive")
        assert excinfo.value.reason == "cyclic_coupling"

    def test_withdrawal_frees_the_child(
        self, sets: tuple[JointSet, PoseSet, MotionCheckSet, CouplingSet]
    ) -> None:
        joints, poses, _checks, couplings = sets
        declare_scalar_joints(joints, "j-motor", "j-wrist")
        couplings.declare(coupling_entry())
        couplings.withdraw("cp-wrist-drive", "direct drive now")
        # The child is a FREE parameter again: a pose may bind it…
        poses.declare({"id": "p-bent", "joints": {"j-wrist": 30.0}, "provenance": assumed()})
        # …and a new coupling may claim it.
        couplings.declare(coupling_entry(id="cp-take-two", ratio=0.5))
        assert [entry.id for entry in couplings.state().active] == ["cp-take-two"]


class TestDependentParameterDeclarations:
    def test_a_pose_may_not_bind_a_coupled_child(
        self, sets: tuple[JointSet, PoseSet, MotionCheckSet, CouplingSet]
    ) -> None:
        joints, poses, _checks, couplings = sets
        declare_scalar_joints(joints, "j-motor", "j-wrist")
        couplings.declare(coupling_entry())
        with pytest.raises(PoseError) as excinfo:
            poses.declare({"id": "p-bent", "joints": {"j-wrist": 30.0}, "provenance": assumed()})
        assert excinfo.value.reason == "invalid_pose"
        assert "cp-wrist-drive" in excinfo.value.args[0]  # the coupling is named
        assert poses.state().generation == 0
        # Binding the FREE parent is exactly what §5 asks for instead.
        poses.declare({"id": "p-bent", "joints": {"j-motor": 150.0}, "provenance": assumed()})

    def test_a_pose_update_binding_a_coupled_child_is_refused_too(
        self, sets: tuple[JointSet, PoseSet, MotionCheckSet, CouplingSet]
    ) -> None:
        joints, poses, _checks, couplings = sets
        declare_scalar_joints(joints, "j-motor", "j-wrist")
        couplings.declare(coupling_entry())
        poses.declare({"id": "p-run", "joints": {"j-motor": 90.0}, "provenance": assumed()})
        with pytest.raises(PoseError):
            poses.update("p-run", {"joints": {"j-wrist": 10.0}}, "retarget the wrist")

    def test_a_sweep_may_not_range_a_coupled_child(
        self, sets: tuple[JointSet, PoseSet, MotionCheckSet, CouplingSet]
    ) -> None:
        joints, _poses, checks, couplings = sets
        declare_scalar_joints(joints, "j-motor", "j-wrist")
        couplings.declare(coupling_entry())
        with pytest.raises(MotionCheckError) as excinfo:
            checks.declare(
                {
                    "id": "mc-wrist",
                    "kind": "sweep_no_interference",
                    "a": "part0a",
                    "b": "part1b",
                    "sweep": {"j-wrist": {"from": -10.0, "to": 10.0}},
                    "samples": 2,
                    "provenance": assumed(),
                }
            )
        assert excinfo.value.reason == "invalid_motion_check"
        assert "cp-wrist-drive" in excinfo.value.args[0]
        assert checks.state().generation == 0
        # Sweeping the FREE parent is the §5 spelling of the same intent.
        checks.declare(
            {
                "id": "mc-motor",
                "kind": "sweep_no_interference",
                "a": "part0a",
                "b": "part1b",
                "sweep": {"j-motor": {"from": -10.0, "to": 10.0}},
                "samples": 2,
                "provenance": assumed(),
            }
        )


# ==========================================================================
# the engine over REAL published geometry: composition, limits, statuses


@pytest.fixture(scope="module")
def mech(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[ProjectLayout, OpStore]]:
    """The _g9c cast built, the §5 drive declared over it.

    ``j-hinge`` (revolute, bore axis, ±180) drives ``j-slide`` (prismatic
    along the plate top's +Z normal, limits [-1, 20]) through ``cp-drive``
    (ratio 1/18 mm per degree, offset 0). Poses:

    * ``p-slid`` binds the child DIRECTLY and is declared BEFORE the coupling
      exists (legal then) — the coupled-later evaluation case;
    * ``p-up`` (+90 deg) derives ``j-slide = +5.0``, inside limits;
    * ``p-down`` (-90 deg) derives ``j-slide = -5.0``, OUTSIDE the child's
      [-1, 20] — the derived-limit refusal case.
    """
    layout, store = open_coupling_project(tmp_path_factory.mktemp("mech") / "proj")
    try:
        joints = JointSet(layout, store)
        poses = PoseSet(layout, store, joints)
        couplings = CouplingSet(layout, store, joints)
        joints.declare(
            {
                "id": "j-hinge",
                "kind": "revolute",
                "parent": "base:hinge_bore",
                "child": "arm:hinge_pin",
                "limits": {"min": -180.0, "max": 180.0},
                "provenance": assumed(),
            }
        )
        joints.declare(
            {
                "id": "j-slide",
                "kind": "prismatic",
                "parent": "base:slide_face",
                "child": "slider:foot_face",
                "limits": {"min": -1.0, "max": 20.0},
                "provenance": assumed(),
            }
        )
        poses.declare({"id": "p-slid", "joints": {"j-slide": 2.0}, "provenance": assumed()})
        couplings.declare(
            {
                "id": "cp-drive",
                "parent": "j-hinge",
                "child": "j-slide",
                "ratio": DRIVE_RATIO_MM_PER_DEG,
                "offset": 0.0,
                "provenance": assumed(),
            }
        )
        poses.declare({"id": "p-up", "joints": {"j-hinge": 90.0}, "provenance": assumed()})
        poses.declare({"id": "p-down", "joints": {"j-hinge": -90.0}, "provenance": assumed()})
        yield layout, store
    finally:
        store.close()


@pytest.fixture(scope="module")
def status(mech: tuple[ProjectLayout, OpStore]) -> MotionStatus:
    layout, store = mech
    return MotionEvaluator(layout, store).evaluate(record=True)


def _pose(status: MotionStatus, pose_id: str) -> Any:
    for outcome in status.poses:
        if outcome.id == pose_id:
            return outcome
    raise AssertionError(f"no pose {pose_id} in {status.poses}")


class TestCompositionThroughFK:
    def test_the_coupled_slider_lands_on_the_hand_matrix(
        self, mech: tuple[ProjectLayout, OpStore]
    ) -> None:
        """``p-up`` assigns only the FREE parent (+90 deg); the coupling
        derives ``j-slide = (1/18) * 90 = +5.0`` exactly, so the slider's
        world transform is a pure translation of 5 mm along the slide face's
        +Z normal — hand-computed, to 1e-9, on reloaded published BReps."""
        layout, store = mech
        with tempfile.TemporaryDirectory() as tmp:
            resolver = AnchorResolver(layout, store, Publisher(layout, store), Path(tmp))
            resolution = motion_resolution(layout, store, resolver)
            placed = resolution.transforms("p-up", ("slider", "base"))
        expected = ((1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 1.0, 5.0))
        for row, want in zip(placed["slider"].rows, expected, strict=True):
            for value, target in zip(row, want, strict=True):
                assert value == pytest.approx(target, abs=1e-9)
        # The root part is static: the identity, exactly.
        assert placed["base"].rows == (
            (1.0, 0.0, 0.0, 0.0),
            (0.0, 1.0, 0.0, 0.0),
            (0.0, 0.0, 1.0, 0.0),
        )

    def test_a_sweep_measures_the_derived_travel(self, mech: tuple[ProjectLayout, OpStore]) -> None:
        """Sweeping the FREE parent moves the coupled child's part: at 45 and
        90 deg the slider rises 2.5 and 5.0 mm, so the slider/base clearance
        is exactly ``0.5 + t`` — worst 3.0 mm at the 45 deg sample. Without
        the coupling both samples would measure 0.5 mm, so the number itself
        is the composition evidence."""
        layout, store = mech
        evaluator = SweepEvaluator(layout, store)
        evaluator.checks.declare(
            {
                "id": "mc-track",
                "kind": "sweep_clearance",
                "a": "slider",
                "b": "base",
                "sweep": {"j-hinge": {"from": 45.0, "to": 90.0}},
                "min_mm": 1.0,
                "samples": 2,
                "provenance": assumed(),
            }
        )
        [result] = evaluator.evaluate(["mc-track"])
        assert result.verdict == "holds_at_samples"
        assert result.samples_evaluated == 2
        assert result.worst is not None
        # The worst sample restates the FREE parameter values it was taken at.
        assert result.worst.values == {"j-hinge": 45.0}
        expected = SLIDER_BASE_GAP_MM + DRIVE_RATIO_MM_PER_DEG * 45.0
        assert result.worst.measured == pytest.approx(expected, abs=1e-6)


class TestDerivedLimitRefusal:
    def test_at_pose_evaluation_the_coupling_is_named(self, status: MotionStatus) -> None:
        """``p-down`` derives ``j-slide = -5.0``, outside [-1, 20]: refused
        ``joint_limit_exceeded`` with the coupling in the detail — derived
        before limit checks, never clamped (§5)."""
        outcome = _pose(status, "p-down")
        assert outcome.state == "unresolvable"
        assert outcome.reason == "joint_limit_exceeded"
        assert outcome.detail is not None
        for name in ("cp-drive", "j-slide", "-5"):
            assert name in outcome.detail

    def test_the_in_limits_pose_is_resolved(self, status: MotionStatus) -> None:
        assert _pose(status, "p-up").state == "resolved"

    def test_a_pose_bound_to_a_child_coupled_later_reports_the_coupling(
        self, status: MotionStatus
    ) -> None:
        """``p-slid`` was legal when declared; the coupling arrived later.
        The stored pose is not erased and not re-refused — its evaluation
        reports the dependency, naming the coupling (the ``orphaned_pose``
        philosophy applied to §5)."""
        outcome = _pose(status, "p-slid")
        assert outcome.state == "unresolvable"
        assert outcome.reason == "invalid_pose"
        assert outcome.detail is not None and "cp-drive" in outcome.detail

    def test_per_sweep_sample_the_coupling_is_named(
        self, mech: tuple[ProjectLayout, OpStore]
    ) -> None:
        """A grid whose first sample derives the child out of limits refuses
        by geom's own spelling with the coupling named — zero samples pass,
        none are clamped."""
        layout, store = mech
        evaluator = SweepEvaluator(layout, store)
        evaluator.checks.declare(
            {
                "id": "mc-over",
                "kind": "sweep_clearance",
                "a": "slider",
                "b": "base",
                "sweep": {"j-hinge": {"from": -90.0, "to": 0.0}},
                "min_mm": 0.1,
                "samples": 2,
                "provenance": assumed(),
            }
        )
        [result] = evaluator.evaluate(["mc-over"])
        assert result.verdict == "unresolvable"
        assert result.reason == "joint_limit_exceeded"
        assert result.detail is not None
        for name in ("cp-drive", "j-slide"):
            assert name in result.detail
        assert result.samples_evaluated == 0


# ==========================================================================
# read_couplings: every generation stays readable (engine-side shape)


class TestWithdrawnEntriesStayReadable:
    def test_the_state_returns_withdrawn_entries_with_reasons(
        self, sets: tuple[JointSet, PoseSet, MotionCheckSet, CouplingSet]
    ) -> None:
        joints, _poses, _checks, couplings = sets
        declare_scalar_joints(joints, "j-motor", "j-wrist")
        couplings.declare(coupling_entry())
        couplings.withdraw("cp-wrist-drive", "the wrist is now direct-driven")
        state = couplings.state()
        assert [entry.id for entry in state.entries] == ["cp-wrist-drive"]
        entry = state.entries[0]
        assert entry.withdrawn is True
        assert entry.withdrawn_reason == "the wrist is now direct-driven"
        document = entry.to_json()
        assert document["withdrawn"] is True
        assert document["withdrawn_reason"] == "the wrist is now direct-driven"
        # …and the dependency map excludes it: withdrawn is never evaluated.
        assert state.by_child == {}


# ==========================================================================
# the tool surface through dispatch on both profiles (KINEMATICS.md §6)

TRIPLET: tuple[str, ...] = ("declare_coupling", "update_coupling", "read_couplings")


@pytest.fixture
def dispatched(tmp_path: Path) -> Iterator[Any]:
    """The real dispatcher over a real project (the stage9a dispatch precedent).

    Joint and coupling declaration are structural, so no build is needed here
    — what this fixture proves is the surface a model actually meets.
    """
    from hephaestus.testing.tools_fixture import make_project

    project = make_project(tmp_path / "proj")
    try:
        for joint_id, parts in (("j-motor", ("motor", "rotor")), ("j-wrist", ("rotor", "hand"))):
            project.call(
                "declare_joint",
                {
                    "id": joint_id,
                    "kind": "revolute",
                    "parent": f"{parts[0]}:bore",
                    "child": f"{parts[1]}:pin",
                    "limits": {"min": -180.0, "max": 180.0},
                    "provenance": assumed(),
                },
            )
        yield project
    finally:
        project.close()


def test_the_triplet_is_reachable_on_both_declared_profiles(dispatched: Any) -> None:
    """All three coupling tools, driven by a part session and the orchestrator.

    A coupling relates joints that span parts by nature (the 8C quartet
    decision applied unchanged, ``KINEMATICS.md`` §6): the part session
    declares it, the orchestrator revises and withdraws it, and both read
    exactly the same generational record — withdrawn entries included with
    their reasons, because generational state is honest only if every
    generation stays readable.
    """
    from hephaestus.contract import tools_decl
    from hephaestus.testing.tools_fixture import PART_WIDGET

    for name in TRIPLET:
        assert tools_decl.get_tool(name).profiles == ("part", "orchestrator"), name

    # The part session declares the coupling…
    declared = cast(
        "dict[str, Any]",
        dispatched.call(
            "declare_coupling",
            {
                "id": "cp-drive",
                "parent": "j-motor",
                "child": "j-wrist",
                "ratio": 0.2,
                "offset": 0.0,
                "provenance": {"requirement": "R1"},
            },
            principal=PART_WIDGET,
        ),
    )
    assert declared["status"] == "ok" and declared["generation"] == 1
    assert str(declared["artifact_ref"]).startswith("artifact:couplings:sha256:")
    assert declared["motion"] is None  # never evaluated, which is not a pass

    # …the orchestrator revises it with a recorded reason…
    revised = cast(
        "dict[str, Any]",
        dispatched.call(
            "update_coupling",
            {
                "id": "cp-drive",
                "patch": {"ratio": 0.25},
                "reason": "gearing revised to 4:1",
            },
        ),
    )
    assert revised["generation"] == 2
    assert cast("dict[str, Any]", revised["change"])["reason"] == "gearing revised to 4:1"

    # …withdraws it (one act, one reason, nothing erased)…
    withdrawn = cast(
        "dict[str, Any]",
        dispatched.call(
            "update_coupling",
            {
                "id": "cp-drive",
                "patch": {"withdrawn": True},
                "reason": "the wrist is now direct-driven",
            },
        ),
    )
    assert withdrawn["generation"] == 3

    # …and BOTH profiles read the full record, withdrawn entry included.
    for principal in (PART_WIDGET, None):
        kwargs: dict[str, Any] = {} if principal is None else {"principal": principal}
        read = cast("dict[str, Any]", dispatched.call("read_couplings", {}, **kwargs))
        [entry] = [cast("dict[str, Any]", item) for item in cast("list[Any]", read["entries"])]
        assert entry["id"] == "cp-drive" and entry["ratio"] == 0.25
        assert entry["withdrawn"] is True
        assert entry["withdrawn_reason"] == "the wrist is now direct-driven"


@pytest.mark.parametrize("tool", TRIPLET)
def test_undeclared_profiles_are_refused(dispatched: Any, tool: str) -> None:
    """The reviewer is HANDED motion state, never authoring it; quick-edit
    interprets nothing — both are ``scope_denied`` (the 8C rule)."""
    from hephaestus.agent_bridge.dispatch import DispatchError, Principal
    from hephaestus.testing.tools_fixture import QUICK_WIDGET

    reviewer = Principal(session_id="rv", profile="reviewer", part=None)
    for principal in (reviewer, QUICK_WIDGET):
        with pytest.raises(DispatchError) as excinfo:
            dispatched.call(tool, {}, principal=principal)
        assert excinfo.value.reason == "scope_denied"


def test_refusal_tokens_carry_through_dispatch(dispatched: Any) -> None:
    """The set's stable machine tokens survive the tool layer unchanged."""
    from hephaestus.agent_bridge.dispatch import DispatchError

    with pytest.raises(DispatchError) as invalid:
        dispatched.call(
            "declare_coupling",
            {
                "id": "cp-bad",
                "parent": "j-motor",
                "child": "j-ghost",
                "ratio": 1.0,
                "provenance": assumed(),
            },
        )
    assert invalid.value.reason == "invalid_coupling"
    with pytest.raises(DispatchError) as cyclic:
        dispatched.call(
            "declare_coupling",
            {
                "id": "cp-self",
                "parent": "j-motor",
                "child": "j-motor",
                "ratio": 1.0,
                "provenance": assumed(),
            },
        )
    assert cyclic.value.reason == "cyclic_coupling"
    with pytest.raises(DispatchError) as unknown:
        dispatched.call(
            "update_coupling", {"id": "cp-ghost", "patch": {"ratio": 2.0}, "reason": "x"}
        )
    assert unknown.value.reason == "unknown_coupling"


# ==========================================================================
# the operator CLI: the coupling table in `heph motion` (+ --json)


class TestHephMotionCouplingTable:
    @pytest.fixture
    def declared(self, tmp_path: Path) -> ProjectLayout:
        """Joints, one active and one withdrawn coupling — nothing evaluated."""
        layout = make_project(tmp_path / "proj", {})
        store = open_store(layout)
        try:
            joints = JointSet(layout, store)
            couplings = CouplingSet(layout, store, joints)
            declare_scalar_joints(joints, "j-motor", "j-wrist")
            couplings.declare(
                coupling_entry(id="cp-old", ratio=0.5, provenance=assumed("first guess"))
            )
            couplings.withdraw("cp-old", "measured backlash demanded a new ratio")
            couplings.declare(coupling_entry())
        finally:
            store.close()
        return layout

    def run(self, root: Path, monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
        from hephaestus.core.cli import main

        monkeypatch.chdir(root)
        return main(list(argv))

    def test_the_json_form_carries_the_coupling_table(
        self,
        declared: ProjectLayout,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        assert self.run(declared.root, monkeypatch, "motion", "--json") == 0
        payload: dict[str, Any] = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert payload["coupling_generation"] == 3
        entries = [cast("dict[str, Any]", item) for item in cast("list[Any]", payload["couplings"])]
        assert [entry["id"] for entry in entries] == ["cp-old", "cp-wrist-drive"]
        # The withdrawn entry stays in the table WITH its recorded reason.
        assert entries[0]["withdrawn"] is True
        assert entries[0]["withdrawn_reason"] == "measured backlash demanded a new ratio"
        assert "withdrawn" not in entries[1]
        assert entries[1]["parent"] == "j-motor" and entries[1]["child"] == "j-wrist"
        assert entries[1]["ratio"] == pytest.approx(0.2)

    def test_the_human_table_spells_the_relationship_out(
        self,
        declared: ProjectLayout,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        assert self.run(declared.root, monkeypatch, "motion") == 0
        out = capsys.readouterr().out
        assert "couplings:" in out
        assert "0.2 * j-motor + 0" in out  # child = ratio * parent + offset
        assert "WITHDRAWN" in out
        assert "measured backlash demanded a new ratio" in out

    def test_an_undeclared_set_prints_no_dead_table(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        layout = make_project(tmp_path / "proj", {})
        assert self.run(layout.root, monkeypatch, "motion", "--json") == 0
        payload: dict[str, Any] = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert payload["coupling_generation"] == 0
        assert payload["couplings"] == []
