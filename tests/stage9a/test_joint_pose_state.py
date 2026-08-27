# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""G9A: joints and poses as ledger state, and the motion projection's staleness.

Four gate clauses, all below the tool surface (dispatch and the CLI have their
own suites):

* *generational declare/update/withdraw with provenance compulsion
  (``invalid_joint``)* — every act is an immutable generation replayable from
  the artifact ref handed out at the time, a refusal writes NOTHING, and a
  withdrawal keeps the entry with its reason (``KINEMATICS.md`` §1);
* *the anchor-grammar refusal of a slash-bearing anchor and
  ``cyclic_joint_graph``* — joint anchors are EXACTLY the 8C grammar (no
  second naming scheme), and the joint graph is a forest with cycles refused
  at declaration, the cycle named (§1);
* *named poses, including the unknown-joint refusal at declaration* — a pose
  binding an undeclared or already-withdrawn joint is refused
  ``invalid_pose``; a joint withdrawn LATER leaves the pose stored and
  editable, because ``orphaned_pose`` is a per-pose *evaluation* state, not a
  declaration one (§3);
* *staleness* — rebuilding a joint-forest part into different geometry
  restales the motion projection field of ``ProjectionState`` (the
  ``AssemblyProjection`` precedent, §2), the GC edge keeps a stale status
  blob readable, and a pre-Stage-9 state record still loads with no motion
  field at all.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from hephaestus.core.errors import AddressingError
from hephaestus.core.project_store.kinematics import (
    JointError,
    JointSet,
    PoseError,
    PoseSet,
)
from hephaestus.core.project_store.layout import ProjectLayout, ProjectManifest, open_store
from hephaestus.core.project_store.locks import (
    PROJECT_CONFIG_LOCK,
    LockManager,
    part_lock,
)
from hephaestus.core.project_store.projections import (
    STATE_POINTER,
    MotionProjection,
    Projections,
    ProjectionState,
)

from opstore import OpStore


@pytest.fixture
def store_env(tmp_path: Path) -> tuple[JointSet, PoseSet, OpStore]:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "hephaestus.toml").write_text('name = "kin"\n', encoding="utf-8")
    layout = ProjectLayout(root=root, manifest=ProjectManifest(name="kin"))
    store = open_store(layout)
    joints = JointSet(layout, store)
    return joints, PoseSet(layout, store, joints), store


@pytest.fixture
def joints(store_env: tuple[JointSet, PoseSet, OpStore]) -> JointSet:
    return store_env[0]


@pytest.fixture
def poses(store_env: tuple[JointSet, PoseSet, OpStore]) -> PoseSet:
    return store_env[1]


def elbow(**overrides: Any) -> dict[str, Any]:
    """The §1 worked-example entry with fields replaced (or removed via None)."""
    out: dict[str, Any] = {
        "id": "j-elbow",
        "kind": "revolute",
        "parent": "arm_upper:elbow_bore",
        "child": "arm_fore:elbow_pin",
        "limits": {"min": -5.0, "max": 150.0},
        "zero": "as_built",
        "provenance": {"requirement": "r-3"},
        "note": "elbow travel per spec table 2",
    }
    for key, value in overrides.items():
        if value is None:
            out.pop(key, None)
        else:
            out[key] = value
    return out


def assumed(reason: str = "no requirement covers this travel") -> dict[str, Any]:
    return {"assumed": True, "reason": reason}


# ==========================================================================
# generations: three acts, three generations, nothing erased


class TestJointGenerations:
    def test_declare_update_withdraw_replay_from_their_own_refs(self, joints: JointSet) -> None:
        declared = joints.declare(elbow())
        revised = joints.update(
            "j-elbow", {"limits": {"min": -5.0, "max": 135.0}}, "hard stop added at 135"
        )
        withdrawn = joints.withdraw("j-elbow", "the elbow was redesigned as a flexure")
        assert [declared.generation, revised.generation, withdrawn.generation] == [1, 2, 3]

        # Each act recorded WHAT it was and WHY, with its own immutable ref.
        assert declared.change is not None and declared.change.kind == "declare"
        assert revised.change is not None and revised.change.reason == "hard stop added at 135"
        assert withdrawn.change is not None and withdrawn.change.kind == "withdraw"
        refs = [state.artifact_ref for state in (declared, revised, withdrawn)]
        assert len({ref for ref in refs if ref is not None}) == 3
        assert all(ref is not None and ref.startswith("artifact:joints:sha256:") for ref in refs)

        # Replay: the generation each ref names still says what it said then.
        replayed = [joints.generation(ref) for ref in refs if ref is not None]
        assert [state.generation for state in replayed] == [1, 2, 3]
        first_limits = replayed[0].entries[0].limits
        second_limits = replayed[1].entries[0].limits
        assert first_limits is not None and first_limits.max == pytest.approx(150.0)
        assert second_limits is not None and second_limits.max == pytest.approx(135.0)
        assert replayed[0].entries[0].withdrawn is False
        # Withdrawn, never erased: the entry and the reason stay in the record.
        assert replayed[2].entries[0].withdrawn is True
        assert replayed[2].entries[0].withdrawn_reason == "the elbow was redesigned as a flexure"
        assert replayed[2].active == ()
        # …and the parent chain walks back to the first generation unbroken.
        assert [state.generation for state in joints.history()] == [1, 2, 3]

    def test_a_repeated_id_is_refused_not_replaced(self, joints: JointSet) -> None:
        joints.declare(elbow())
        with pytest.raises(JointError) as excinfo:
            joints.declare(elbow(limits={"min": 0.0, "max": 90.0}))
        assert excinfo.value.reason == "invalid_joint"
        assert joints.state().generation == 1

    def test_an_unknown_id_is_its_own_refusal_token(self, joints: JointSet) -> None:
        joints.declare(elbow())
        with pytest.raises(JointError) as patching:
            joints.update("j-ghost", {"note": "x"}, "y")
        assert patching.value.reason == "unknown_joint"
        assert "j-elbow" in patching.value.args[0]
        with pytest.raises(AddressingError):
            joints.get("j-ghost")

    def test_update_and_withdrawal_require_reasons(self, joints: JointSet) -> None:
        joints.declare(elbow())
        with pytest.raises(JointError):
            joints.update("j-elbow", {"note": "x"}, "   ")
        with pytest.raises(JointError):
            joints.withdraw("j-elbow", "")
        assert joints.state().generation == 1


# ==========================================================================
# provenance is compelled (VALIDATION.md §2's taxonomy, applied to motion)


class TestJointProvenance:
    @pytest.mark.parametrize(
        ("case", "provenance"),
        [
            ("no provenance at all", None),
            ("an empty provenance object", {}),
            ("assumed with no reason", {"assumed": True}),
            ("cited and assumed at once", {"requirement": "r-3", "assumed": True}),
        ],
    )
    def test_an_entry_that_says_nothing_about_intent_is_refused(
        self, joints: JointSet, case: str, provenance: Mapping[str, Any] | None
    ) -> None:
        """Travel limits ARE interpretations of intent, so they say whose — or refuse."""
        with pytest.raises(JointError) as excinfo:
            joints.declare(elbow(provenance=provenance))
        assert excinfo.value.reason == "invalid_joint", case
        # Nothing written: the set is still at generation 0 with no entries.
        assert (joints.state().generation, joints.state().entries) == (0, ()), case

    def test_both_honest_provenances_are_accepted_and_kept(self, joints: JointSet) -> None:
        joints.declare(elbow(provenance=assumed()))
        entry = joints.get("j-elbow")
        assert entry.provenance.assumed is True
        assert entry.provenance.reason == "no requirement covers this travel"


# ==========================================================================
# entry validation: anchors, kinds, limits, zero


class TestJointValidation:
    @pytest.mark.parametrize(
        ("field", "anchor"),
        [
            ("parent", "arm_upper/elbow_bore"),  # the §7 cross-part selector form
            ("child", "arm_fore:pin/face"),  # a slash smuggled into the selector
        ],
    )
    def test_a_slash_bearing_anchor_is_refused_invalid_joint(
        self, joints: JointSet, field: str, anchor: str
    ) -> None:
        """One grammar per string: joint anchors are the 8C colon form, exactly."""
        with pytest.raises(JointError) as excinfo:
            joints.declare(elbow(**{field: anchor}))
        assert excinfo.value.reason == "invalid_joint"
        assert "slash" in excinfo.value.args[0]
        assert joints.state().generation == 0

    def test_an_unknown_kind_is_refused_naming_the_closed_set(self, joints: JointSet) -> None:
        with pytest.raises(JointError) as excinfo:
            joints.declare(elbow(kind="ball"))
        assert excinfo.value.reason == "invalid_joint"
        assert "revolute" in excinfo.value.args[0]

    def test_a_fixed_joint_takes_no_limits(self, joints: JointSet) -> None:
        joints.declare(elbow(id="j-mount", kind="fixed", limits=None))
        entry = joints.get("j-mount")
        assert (entry.limits, entry.rotation, entry.translation) == (None, None, None)
        with pytest.raises(JointError) as excinfo:
            joints.declare(elbow(id="j-bad", kind="fixed", child="arm_hand:mount"))
        assert "0 DOF" in excinfo.value.args[0]

    def test_a_dof_bearing_kind_requires_limits(self, joints: JointSet) -> None:
        with pytest.raises(JointError) as excinfo:
            joints.declare(elbow(limits=None))
        assert "limits" in excinfo.value.args[0]

    def test_inverted_limits_are_refused(self, joints: JointSet) -> None:
        with pytest.raises(JointError) as excinfo:
            joints.declare(elbow(limits={"min": 150.0, "max": -5.0}))
        assert "min < max" in excinfo.value.args[0]

    def test_cylindrical_carries_exactly_two_named_pairs(self, joints: JointSet) -> None:
        joints.declare(
            elbow(
                id="j-spindle",
                kind="cylindrical",
                limits={
                    "rotation": {"min": -180.0, "max": 180.0},
                    "translation": {"min": 0.0, "max": 25.0},
                },
            )
        )
        entry = joints.get("j-spindle")
        assert entry.rotation is not None and entry.rotation.max == pytest.approx(180.0)
        assert entry.translation is not None and entry.translation.max == pytest.approx(25.0)
        # …and the single-pair shape is refused for it, by name.
        with pytest.raises(JointError) as excinfo:
            joints.declare(elbow(id="j-bad", kind="cylindrical", limits={"min": 0.0, "max": 1.0}))
        assert "rotation" in excinfo.value.args[0]

    def test_zero_admits_only_as_built_in_9a(self, joints: JointSet) -> None:
        with pytest.raises(JointError) as excinfo:
            joints.declare(elbow(zero=90.0))
        assert "as_built" in excinfo.value.args[0]

    def test_a_kind_change_cannot_smuggle_the_old_limit_shape(self, joints: JointSet) -> None:
        joints.declare(elbow())
        with pytest.raises(JointError) as excinfo:
            joints.update("j-elbow", {"kind": "cylindrical"}, "the pin now slides too")
        assert "cylindrical" in excinfo.value.args[0]
        # Supplying the new kind's own shape in the same patch succeeds.
        revised = joints.update(
            "j-elbow",
            {
                "kind": "cylindrical",
                "limits": {
                    "rotation": {"min": -5.0, "max": 150.0},
                    "translation": {"min": 0.0, "max": 4.0},
                },
            },
            "the pin now slides too",
        )
        assert revised.by_id["j-elbow"].kind == "cylindrical"


# ==========================================================================
# the forest rule


class TestJointForest:
    def _declare(self, joints: JointSet, joint_id: str, parent: str, child: str) -> None:
        joints.declare(
            elbow(
                id=joint_id,
                parent=parent,
                child=child,
                limits={"min": 0.0, "max": 90.0},
                provenance=assumed(),
                note=None,
            )
        )

    def test_a_cycle_is_refused_at_declaration_with_the_cycle_named(self, joints: JointSet) -> None:
        self._declare(joints, "j-ab", "part_a:bore", "part_b:pin")
        self._declare(joints, "j-bc", "part_b:bore", "part_c:pin")
        before = joints.state().generation
        with pytest.raises(JointError) as excinfo:
            self._declare(joints, "j-ca", "part_c:bore", "part_a:pin")
        assert excinfo.value.reason == "cyclic_joint_graph"
        message = excinfo.value.args[0]
        for name in ("part_a", "part_b", "part_c", "j-ca"):
            assert name in message
        # Refused means nothing written: still the two-joint chain.
        assert joints.state().generation == before

    def test_a_self_loop_is_a_cycle(self, joints: JointSet) -> None:
        with pytest.raises(JointError) as excinfo:
            self._declare(joints, "j-self", "part_a:bore", "part_a:pin")
        assert excinfo.value.reason == "cyclic_joint_graph"

    def test_a_part_rides_at_most_one_joint(self, joints: JointSet) -> None:
        self._declare(joints, "j-ab", "part_a:bore", "part_b:pin")
        with pytest.raises(JointError) as excinfo:
            self._declare(joints, "j-cb", "part_c:bore", "part_b:pin")
        assert excinfo.value.reason == "invalid_joint"
        assert "j-ab" in excinfo.value.args[0]

    def test_withdrawal_frees_the_edge(self, joints: JointSet) -> None:
        """Withdrawn entries contribute no edges: never evaluated, per the 8C rule."""
        self._declare(joints, "j-ab", "part_a:bore", "part_b:pin")
        joints.withdraw("j-ab", "wrong bore; redeclaring from part_c")
        self._declare(joints, "j-cb", "part_c:bore", "part_b:pin")
        assert [entry.id for entry in joints.state().active] == ["j-cb"]
        assert joints.state().parts == ("part_b", "part_c")

    def test_a_reparenting_update_is_forest_checked(self, joints: JointSet) -> None:
        self._declare(joints, "j-ab", "part_a:bore", "part_b:pin")
        self._declare(joints, "j-bc", "part_b:bore", "part_c:pin")
        with pytest.raises(JointError) as excinfo:
            joints.update("j-ab", {"parent": "part_c:bore"}, "swap the base")
        assert excinfo.value.reason == "cyclic_joint_graph"


# ==========================================================================
# named poses (§3)


class TestPoses:
    def _joints(self, joints: JointSet) -> None:
        joints.declare(elbow())
        joints.declare(
            elbow(
                id="j-wrist",
                kind="revolute",
                parent="arm_fore:wrist_bore",
                child="arm_hand:wrist_pin",
                limits={"min": -90.0, "max": 90.0},
                provenance=assumed("wrist travel is a guess pending r-4"),
                note=None,
            )
        )

    def test_declare_update_withdraw_replay_from_their_own_refs(
        self, joints: JointSet, poses: PoseSet
    ) -> None:
        self._joints(joints)
        declared = poses.declare(
            {
                "id": "p-closed",
                "joints": {"j-elbow": 0.0, "j-wrist": -90.0},
                "provenance": {"requirement": "r-3"},
            }
        )
        revised = poses.update(
            "p-closed", {"joints": {"j-elbow": 5.0}}, "closed now rests on the new stop"
        )
        withdrawn = poses.withdraw("p-closed", "closure is measured at p-latched instead")
        assert [declared.generation, revised.generation, withdrawn.generation] == [1, 2, 3]
        refs = [state.artifact_ref for state in (declared, revised, withdrawn)]
        assert all(ref is not None and ref.startswith("artifact:poses:sha256:") for ref in refs)
        replayed = [poses.generation(ref) for ref in refs if ref is not None]
        assert dict(replayed[0].entries[0].joints) == {"j-elbow": 0.0, "j-wrist": -90.0}
        assert dict(replayed[1].entries[0].joints) == {"j-elbow": 5.0}
        assert replayed[2].entries[0].withdrawn is True
        assert replayed[2].entries[0].withdrawn_reason == (
            "closure is measured at p-latched instead"
        )
        assert [state.generation for state in poses.history()] == [1, 2, 3]

    def test_an_unknown_joint_id_is_refused_at_declaration(
        self, joints: JointSet, poses: PoseSet
    ) -> None:
        self._joints(joints)
        with pytest.raises(PoseError) as excinfo:
            poses.declare(
                {"id": "p-bad", "joints": {"j-ghost": 1.0}, "provenance": {"requirement": "r-3"}}
            )
        assert excinfo.value.reason == "invalid_pose"
        assert "j-ghost" in excinfo.value.args[0]
        assert "j-elbow" in excinfo.value.args[0]  # the ids that DO exist are named
        assert poses.state().generation == 0

    def test_a_withdrawn_joint_cannot_be_newly_bound(
        self, joints: JointSet, poses: PoseSet
    ) -> None:
        """A pose born orphaned is a claim about nothing — refused, by name."""
        self._joints(joints)
        joints.withdraw("j-wrist", "the wrist became a fixed mount")
        with pytest.raises(PoseError) as excinfo:
            poses.declare({"id": "p-bad", "joints": {"j-wrist": 0.0}, "provenance": assumed("x")})
        assert excinfo.value.reason == "invalid_pose"
        assert "withdrawn" in excinfo.value.args[0]

    def test_a_pose_outliving_its_joint_is_kept_not_re_refused(
        self, joints: JointSet, poses: PoseSet
    ) -> None:
        """``orphaned_pose`` is a per-pose EVALUATION state (§2/§3): the stored
        entry survives the withdrawal untouched, stays readable, and stays
        editable — only its evaluation reports it orphaned, naming the joint."""
        self._joints(joints)
        poses.declare(
            {"id": "p-open", "joints": {"j-wrist": 45.0}, "provenance": {"requirement": "r-3"}}
        )
        joints.withdraw("j-wrist", "the wrist became a fixed mount")
        entry = poses.get("p-open")
        assert entry.withdrawn is False
        assert dict(entry.joints) == {"j-wrist": 45.0}
        # A note edit does not re-validate the untouched binding…
        poses.update("p-open", {"note": "orphaned pending the wrist redesign"}, "bookkeeping")
        # …but a NEW binding is a fresh claim, validated afresh.
        with pytest.raises(PoseError):
            poses.update("p-open", {"joints": {"j-wrist": 30.0}}, "narrow the open pose")

    @pytest.mark.parametrize(
        ("case", "provenance"),
        [
            ("no provenance at all", None),
            ("an empty provenance object", {}),
            ("assumed with no reason", {"assumed": True}),
        ],
    )
    def test_pose_provenance_is_compelled(
        self, joints: JointSet, poses: PoseSet, case: str, provenance: Mapping[str, Any] | None
    ) -> None:
        self._joints(joints)
        entry: dict[str, Any] = {"id": "p-closed", "joints": {"j-elbow": 0.0}}
        if provenance is not None:
            entry["provenance"] = provenance
        with pytest.raises(PoseError) as excinfo:
            poses.declare(entry)
        assert excinfo.value.reason == "invalid_pose", case
        assert (poses.state().generation, poses.state().entries) == (0, ()), case

    def test_the_zero_pose_is_legal(self, joints: JointSet, poses: PoseSet) -> None:
        """§3: joints omitted take their zero value — the empty binding means
        "everything as built", which is a meaningful configuration to name."""
        self._joints(joints)
        state = poses.declare(
            {"id": "p-as-built", "joints": {}, "provenance": assumed("the reference config")}
        )
        assert dict(state.entries[0].joints) == {}


# ==========================================================================
# the motion projection field (§2, the AssemblyProjection precedent)


class TestMotionProjection:
    def _projections(self, tmp_path: Path) -> tuple[Projections, LockManager, OpStore]:
        root = tmp_path / "proj"
        root.mkdir()
        (root / "hephaestus.toml").write_text('name = "kin"\n', encoding="utf-8")
        layout = ProjectLayout(root=root, manifest=ProjectManifest(name="kin"))
        store = open_store(layout)
        locks = LockManager(store)
        return Projections(store, locks=locks), locks, store

    def _record(
        self,
        projections: Projections,
        locks: LockManager,
        part: str,
        artifact_ref: str,
    ) -> None:
        locks.acquire(PROJECT_CONFIG_LOCK)
        locks.acquire(part_lock(part))
        try:
            projections.record_current(part, consumed={}, artifact_ref=artifact_ref)
        finally:
            locks.release(part_lock(part))
            locks.release(PROJECT_CONFIG_LOCK)

    def _motion(self, store: OpStore, parts: dict[str, str]) -> MotionProjection:
        blob = store.blobs.put(b'{"joints": [], "poses": []}')
        return MotionProjection(
            status_blob=blob,
            joint_generation=3,
            pose_generation=1,
            audit_revision=0,
            parts=parts,
        )

    def test_rebuilding_a_forest_part_restales_the_projection(self, tmp_path: Path) -> None:
        projections, locks, store = self._projections(tmp_path)
        self._record(projections, locks, "arm_upper", "artifact:build:sha256:upper1")
        self._record(projections, locks, "arm_fore", "artifact:build:sha256:fore1")
        state = projections.record_motion(
            self._motion(
                store,
                {
                    "arm_upper": "artifact:build:sha256:upper1",
                    "arm_fore": "artifact:build:sha256:fore1",
                },
            )
        )
        assert state.motion is not None and state.motion.stale == ()

        # A DIFFERENT artifact ref for a forest part marks the projection stale…
        self._record(projections, locks, "arm_fore", "artifact:build:sha256:fore2")
        motion = projections.state().motion
        assert motion is not None and motion.stale == ("arm_fore",)
        # …and the recorded evaluation-time refs are untouched (what it was
        # measured against is a historical fact, not live state).
        assert motion.parts["arm_fore"] == "artifact:build:sha256:fore1"

    def test_a_byte_identical_rebuild_restales_nothing(self, tmp_path: Path) -> None:
        projections, locks, store = self._projections(tmp_path)
        self._record(projections, locks, "arm_upper", "artifact:build:sha256:upper1")
        projections.record_motion(
            self._motion(store, {"arm_upper": "artifact:build:sha256:upper1"})
        )
        self._record(projections, locks, "arm_upper", "artifact:build:sha256:upper1")
        motion = projections.state().motion
        assert motion is not None and motion.stale == ()

    def test_a_part_outside_the_forest_restales_nothing(self, tmp_path: Path) -> None:
        projections, locks, store = self._projections(tmp_path)
        projections.record_motion(
            self._motion(store, {"arm_upper": "artifact:build:sha256:upper1"})
        )
        self._record(projections, locks, "enclosure", "artifact:build:sha256:enc1")
        motion = projections.state().motion
        assert motion is not None and motion.stale == ()

    def test_the_gc_edge_keeps_a_stale_status_readable(self, tmp_path: Path) -> None:
        """§2: GC-linked from the state blob, so a stale status never reads as
        "never evaluated" — the edge must ride EVERY swap, not just the
        recording one (the assembly edge's rationale, shared)."""
        projections, locks, store = self._projections(tmp_path)
        self._record(projections, locks, "arm_upper", "artifact:build:sha256:upper1")
        motion = self._motion(store, {"arm_upper": "artifact:build:sha256:upper1"})
        projections.record_motion(motion)

        # Restale it: the pointer moves to a NEW state blob…
        self._record(projections, locks, "arm_upper", "artifact:build:sha256:upper2")
        state_blob = store.blobs.read_pointer(STATE_POINTER)
        assert state_blob is not None
        # …which re-records the reachability edge to the (now stale) status.
        assert (state_blob, motion.status_blob) in store.gc.links()
        assert store.blobs.has(motion.status_blob)
        live = projections.state().motion
        assert live is not None and live.stale == ("arm_upper",)

    def test_a_pre_stage9_state_record_still_loads(self, tmp_path: Path) -> None:
        """Tolerant of pre-field records, like ``BuildResult.metadata`` was."""
        pre_field: dict[str, Any] = {
            "audit_revision": 4,
            "hc_state": {"sheet_t": 6.0},
            "stale": {},
            "projections": {},
        }
        state = ProjectionState.from_json(pre_field)
        assert state.motion is None
        assert state.assembly is None
        # …and a round-trip through to_json keeps the absent field as null.
        assert ProjectionState.from_json(state.to_json()).motion is None

    def test_the_motion_projection_round_trips_and_is_carried(self, tmp_path: Path) -> None:
        """apply_hc_state is not a motion evaluation: the field is carried."""
        projections, _locks, store = self._projections(tmp_path)
        recorded = self._motion(store, {"arm_upper": "artifact:build:sha256:upper1"})
        projections.record_motion(recorded)
        projections.apply_hc_state({"sheet_t": 9.0})
        motion = projections.state().motion
        assert motion is not None
        assert motion == recorded
        assert MotionProjection.from_json(motion.to_json()) == motion
