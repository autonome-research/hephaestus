# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""G9B: the motion-check set as ledger state (``KINEMATICS.md`` §4).

The declaration-side gate clauses, all below the engine (evaluation has its
own suite in ``test_sweep_evaluation.py``):

* *generational declare/update/withdraw with provenance compulsion
  (``invalid_motion_check``)* — every act is an immutable generation
  replayable from the artifact ref handed out at the time, a refusal writes
  NOTHING, and a withdrawal keeps the entry with its reason (the joint set's
  ledger contract, third rider);
* *the grid-total sample cap* — ``samples`` is the PER-AXIS request and the
  cap is on the computed product: a multi-joint entry whose per-axis count is
  under ``SWEEP_SAMPLES_MAX`` but whose product is over it is refused at
  declaration, the refusal NAMING the computed total (§4);
* *anchors under the 8C grammar* — a slash-bearing anchor is refused
  ``invalid_motion_check`` (the two-grammars rule), and per-kind fields are a
  closed shape: a ``reach`` smuggling ``min_mm`` (or a sweep missing its
  threshold) is refused by name, never ignored;
* *sweep ranges over declared joint ids* — undeclared, withdrawn, and
  scalar-unsweepable (``fixed`` / ``cylindrical``) joints are refused at
  declaration; a joint withdrawn LATER leaves the check stored and editable,
  because ``orphaned_sweep`` is an evaluation state, not corruption.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from hephaestus.core.errors import AddressingError
from hephaestus.core.project_store.kinematics import (
    SWEEP_SAMPLES_DEFAULT,
    SWEEP_SAMPLES_MAX,
    JointSet,
    MotionCheckError,
    MotionCheckSet,
    MotionCheckState,
)
from hephaestus.core.project_store.layout import ProjectLayout, ProjectManifest, open_store

from opstore import OpStore


@pytest.fixture
def store_env(tmp_path: Path) -> tuple[JointSet, MotionCheckSet, OpStore]:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "hephaestus.toml").write_text('name = "kin"\n', encoding="utf-8")
    layout = ProjectLayout(root=root, manifest=ProjectManifest(name="kin"))
    store = open_store(layout)
    joints = JointSet(layout, store)
    joints.declare(
        {
            "id": "j-elbow",
            "kind": "revolute",
            "parent": "arm_upper:elbow_bore",
            "child": "arm_fore:elbow_pin",
            "limits": {"min": -5.0, "max": 150.0},
            "provenance": {"requirement": "r-3"},
        }
    )
    joints.declare(
        {
            "id": "j-wrist",
            "kind": "revolute",
            "parent": "arm_fore:wrist_bore",
            "child": "hand:wrist_pin",
            "limits": {"min": -90.0, "max": 90.0},
            "provenance": {"requirement": "r-3"},
        }
    )
    joints.declare(
        {
            "id": "j-mount",
            "kind": "fixed",
            "parent": "frame:boss",
            "child": "clip",
            "provenance": {"assumed": True, "reason": "clip is bolted"},
        }
    )
    joints.declare(
        {
            "id": "j-spindle",
            "kind": "cylindrical",
            "parent": "frame:spindle_bore",
            "child": "spindle:shaft",
            "limits": {
                "rotation": {"min": -360.0, "max": 360.0},
                "translation": {"min": 0.0, "max": 12.0},
            },
            "provenance": {"requirement": "r-9"},
        }
    )
    return joints, MotionCheckSet(layout, store, joints), store


@pytest.fixture
def joints(store_env: tuple[JointSet, MotionCheckSet, OpStore]) -> JointSet:
    return store_env[0]


@pytest.fixture
def checks(store_env: tuple[JointSet, MotionCheckSet, OpStore]) -> MotionCheckSet:
    return store_env[1]


def clear(**overrides: Any) -> dict[str, Any]:
    """The §4 worked-example entry with fields replaced (or removed via None)."""
    out: dict[str, Any] = {
        "id": "mc-elbow-clear",
        "kind": "sweep_clearance",
        "a": "arm_fore",
        "b": "arm_upper:wire_channel",
        "sweep": {"j-elbow": {"from": -5.0, "to": 150.0}},
        "min_mm": 2.0,
        "samples": 64,
        "provenance": {"requirement": "r-5"},
    }
    for key, value in overrides.items():
        if value is None:
            out.pop(key, None)
        else:
            out[key] = value
    return out


def reach(**overrides: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": "mc-tip-reach",
        "kind": "reach",
        "anchor": "hand:tip",
        "target_point_mm": [120.0, 0.0, 40.0],
        "tol_mm": 1.5,
        "sweep": {"j-elbow": {"from": -5.0, "to": 150.0}, "j-wrist": {"from": -90.0, "to": 90.0}},
        "samples": 8,
        "provenance": {"requirement": "r-6"},
    }
    for key, value in overrides.items():
        if value is None:
            out.pop(key, None)
        else:
            out[key] = value
    return out


def assumed(reason: str = "no requirement covers this sweep") -> dict[str, Any]:
    return {"assumed": True, "reason": reason}


# ==========================================================================
# generations: three acts, three generations, nothing erased


class TestGenerations:
    def test_declare_update_withdraw_replay_from_their_own_refs(
        self, checks: MotionCheckSet
    ) -> None:
        declared = checks.declare(clear())
        revised = checks.update(
            "mc-elbow-clear", {"min_mm": 1.5}, "wire gauge reduced per r-5 revision"
        )
        withdrawn = checks.withdraw("mc-elbow-clear", "the channel was redesigned away")
        assert [declared.generation, revised.generation, withdrawn.generation] == [1, 2, 3]

        # Each act recorded WHAT it was and WHY, with its own immutable ref.
        assert declared.change is not None and declared.change.kind == "declare"
        assert revised.change is not None
        assert revised.change.reason == "wire gauge reduced per r-5 revision"
        assert withdrawn.change is not None and withdrawn.change.kind == "withdraw"

        # Every generation stays readable from the ref it handed out.
        for state in (declared, revised, withdrawn):
            assert state.artifact_ref is not None
            replayed = checks.generation(state.artifact_ref)
            assert replayed.generation == state.generation
            assert [e.to_json() for e in replayed.entries] == [e.to_json() for e in state.entries]

        # The withdrawal kept the entry, its reason, and its declared numbers.
        final = checks.state().by_id["mc-elbow-clear"]
        assert final.withdrawn is True
        assert final.withdrawn_reason == "the channel was redesigned away"
        assert final.min_mm == 1.5
        assert checks.state().active == ()

        # History replays oldest-first.
        history = checks.history()
        assert [s.generation for s in history] == [1, 2, 3]

    def test_a_refusal_writes_nothing(self, checks: MotionCheckSet) -> None:
        checks.declare(clear())
        before = checks.state()
        with pytest.raises(MotionCheckError):
            checks.declare(clear())  # repeated id: revising is update()
        with pytest.raises(MotionCheckError):
            checks.update("mc-elbow-clear", {}, "patches nothing")
        with pytest.raises(MotionCheckError):
            checks.update("mc-elbow-clear", {"min_mm": 3.0}, "   ")
        with pytest.raises(MotionCheckError):
            checks.update("mc-elbow-clear", {"id": "mc-2"}, "ids are not patchable")
        after = checks.state()
        assert after.generation == before.generation
        assert after.blob == before.blob

    def test_unknown_ids_are_their_own_refusal(self, checks: MotionCheckSet) -> None:
        with pytest.raises(MotionCheckError) as excinfo:
            checks.update("mc-ghost", {"min_mm": 1.0}, "no such check")
        assert excinfo.value.reason == "unknown_motion_check"
        with pytest.raises(MotionCheckError) as excinfo:
            checks.withdraw("mc-ghost", "no such check")
        assert excinfo.value.reason == "unknown_motion_check"
        with pytest.raises(AddressingError):
            checks.get("mc-ghost")

    def test_withdrawing_twice_is_refused(self, checks: MotionCheckSet) -> None:
        checks.declare(clear())
        checks.withdraw("mc-elbow-clear", "superseded")
        with pytest.raises(MotionCheckError):
            checks.withdraw("mc-elbow-clear", "again")

    def test_same_op_id_replays_the_committed_generation(self, checks: MotionCheckSet) -> None:
        first = checks.declare(clear(), op_id="op-mc-1")
        again = checks.declare(clear(), op_id="op-mc-1")
        assert again.generation == first.generation
        assert again.blob == first.blob


# ==========================================================================
# provenance compulsion (invalid_motion_check)


class TestProvenance:
    def test_absent_provenance_is_refused(self, checks: MotionCheckSet) -> None:
        with pytest.raises(MotionCheckError) as excinfo:
            checks.declare(clear(provenance=None))
        assert excinfo.value.reason == "invalid_motion_check"
        assert "provenance" in str(excinfo.value)

    def test_assumed_without_reason_is_refused(self, checks: MotionCheckSet) -> None:
        with pytest.raises(MotionCheckError):
            checks.declare(clear(provenance={"assumed": True}))

    def test_requirement_and_assumed_together_are_refused(self, checks: MotionCheckSet) -> None:
        with pytest.raises(MotionCheckError):
            checks.declare(
                clear(provenance={"requirement": "r-5", "assumed": True, "reason": "both"})
            )

    def test_an_assumed_entry_with_a_reason_is_admitted(self, checks: MotionCheckSet) -> None:
        state = checks.declare(clear(provenance=assumed()))
        assert state.by_id["mc-elbow-clear"].provenance.assumed is True


# ==========================================================================
# anchors: the 8C grammar, and the closed per-kind field shape


class TestEntryShape:
    def test_a_slash_bearing_anchor_is_refused(self, checks: MotionCheckSet) -> None:
        with pytest.raises(MotionCheckError) as excinfo:
            checks.declare(clear(b="arm_upper/wire_channel"))
        assert excinfo.value.reason == "invalid_motion_check"
        assert "slash" in str(excinfo.value)

    def test_a_malformed_anchor_is_refused(self, checks: MotionCheckSet) -> None:
        with pytest.raises(MotionCheckError):
            checks.declare(clear(a="Not An Ident"))

    def test_the_kind_set_is_closed(self, checks: MotionCheckSet) -> None:
        with pytest.raises(MotionCheckError) as excinfo:
            checks.declare(clear(kind="sweep_envelope"))
        message = str(excinfo.value)
        assert "sweep_clearance" in message and "reach" in message

    def test_kind_foreign_fields_are_refused_not_ignored(self, checks: MotionCheckSet) -> None:
        with pytest.raises(MotionCheckError):
            checks.declare(reach(min_mm=2.0))  # a reach carrying a clearance threshold
        with pytest.raises(MotionCheckError):
            checks.declare(clear(target_point_mm=[0.0, 0.0, 0.0]))

    def test_required_kind_fields_are_compelled(self, checks: MotionCheckSet) -> None:
        with pytest.raises(MotionCheckError) as excinfo:
            checks.declare(clear(min_mm=None))
        assert "min_mm" in str(excinfo.value)
        with pytest.raises(MotionCheckError):
            checks.declare(reach(target_point_mm=None))
        with pytest.raises(MotionCheckError):
            checks.declare(reach(tol_mm=None))

    def test_sweep_ranges_are_validated(self, checks: MotionCheckSet) -> None:
        with pytest.raises(MotionCheckError):
            checks.declare(clear(sweep={}))
        with pytest.raises(MotionCheckError):
            checks.declare(clear(sweep={"j-elbow": {"from": 10.0, "to": 10.0}}))
        with pytest.raises(MotionCheckError):
            checks.declare(clear(sweep={"j-elbow": {"from": 10.0, "to": -10.0}}))
        with pytest.raises(MotionCheckError):
            checks.declare(clear(sweep={"j-elbow": {"lo": 0.0, "hi": 1.0}}))


# ==========================================================================
# sweep ranges over DECLARED joint ids (§4)


class TestSweepBindings:
    def test_an_undeclared_joint_is_refused_naming_the_declared_ones(
        self, checks: MotionCheckSet
    ) -> None:
        with pytest.raises(MotionCheckError) as excinfo:
            checks.declare(clear(sweep={"j-ghost": {"from": 0.0, "to": 1.0}}))
        message = str(excinfo.value)
        assert "j-ghost" in message and "j-elbow" in message

    def test_a_withdrawn_joint_is_refused_at_declaration(
        self, joints: JointSet, checks: MotionCheckSet
    ) -> None:
        joints.withdraw("j-wrist", "wrist redesigned as a flexure")
        with pytest.raises(MotionCheckError) as excinfo:
            checks.declare(clear(sweep={"j-wrist": {"from": 0.0, "to": 10.0}}))
        assert "withdrawn" in str(excinfo.value)

    def test_zero_scalar_dof_joints_are_refused(self, checks: MotionCheckSet) -> None:
        with pytest.raises(MotionCheckError) as excinfo:
            checks.declare(clear(sweep={"j-mount": {"from": 0.0, "to": 1.0}}))
        assert "fixed" in str(excinfo.value)
        with pytest.raises(MotionCheckError) as excinfo:
            checks.declare(clear(sweep={"j-spindle": {"from": 0.0, "to": 1.0}}))
        assert "cylindrical" in str(excinfo.value)

    def test_a_joint_withdrawn_later_leaves_the_check_stored_and_editable(
        self, joints: JointSet, checks: MotionCheckSet
    ) -> None:
        checks.declare(clear())
        joints.withdraw("j-elbow", "elbow redesigned")
        # The stored check is NOT re-refused (orphaned_sweep is an evaluation
        # state), and a patch that leaves the sweep alone still lands.
        state = checks.update("mc-elbow-clear", {"min_mm": 3.0}, "tightened while orphaned")
        assert state.by_id["mc-elbow-clear"].min_mm == 3.0
        # A patch that supplies a NEW sweep is a fresh claim: validated live.
        with pytest.raises(MotionCheckError):
            checks.update(
                "mc-elbow-clear",
                {"sweep": {"j-elbow": {"from": 0.0, "to": 10.0}}},
                "rebind to the withdrawn joint",
            )


# ==========================================================================
# sampling: the per-axis request and THE GRID-TOTAL CAP (§4)


class TestSampleCap:
    def test_samples_defaults_to_the_named_constant(self, checks: MotionCheckSet) -> None:
        state = checks.declare(clear(samples=None))
        entry = state.by_id["mc-elbow-clear"]
        assert entry.samples == SWEEP_SAMPLES_DEFAULT == 64
        assert entry.grid_total == 64
        assert entry.to_json()["samples"] == 64

    def test_samples_must_be_an_integer_of_at_least_two(self, checks: MotionCheckSet) -> None:
        with pytest.raises(MotionCheckError):
            checks.declare(clear(samples=1))
        with pytest.raises(MotionCheckError):
            checks.declare(clear(samples=True))
        with pytest.raises(MotionCheckError):
            checks.declare(clear(samples=6.4))

    def test_the_cap_is_on_the_computed_grid_total_and_the_refusal_names_it(
        self, checks: MotionCheckSet
    ) -> None:
        """The gate clause verbatim: 65 per axis is well under 4096, but the
        two-joint product 65^2 = 4225 is over it — refused at declaration,
        the computed total in the refusal, nothing written."""
        before = checks.state()
        with pytest.raises(MotionCheckError) as excinfo:
            checks.declare(reach(samples=65))  # two swept joints
        message = str(excinfo.value)
        assert excinfo.value.reason == "invalid_motion_check"
        assert "4225" in message  # the COMPUTED total, named
        assert str(SWEEP_SAMPLES_MAX) in message
        assert checks.state().blob == before.blob  # refused = not written

        # The same per-axis count over ONE joint is under the cap: admitted.
        state = checks.declare(clear(samples=65))
        assert state.by_id["mc-elbow-clear"].grid_total == 65

    def test_a_grid_exactly_at_the_cap_is_admitted(self, checks: MotionCheckSet) -> None:
        state = checks.declare(reach(samples=64))  # 64^2 == 4096 == the cap
        assert state.by_id["mc-tip-reach"].grid_total == SWEEP_SAMPLES_MAX

    def test_an_update_cannot_smuggle_a_grid_past_the_cap(self, checks: MotionCheckSet) -> None:
        checks.declare(reach(samples=8))
        with pytest.raises(MotionCheckError) as excinfo:
            checks.update("mc-tip-reach", {"samples": 65}, "denser grid")
        assert "4225" in str(excinfo.value)


# ==========================================================================
# updates revalidate the whole merged entry


class TestUpdate:
    def test_a_kind_change_drops_the_old_kinds_fields(self, checks: MotionCheckSet) -> None:
        checks.declare(clear())
        state = checks.update(
            "mc-elbow-clear",
            {
                "kind": "reach",
                "anchor": "arm_fore:tip",
                "target_point_mm": [100.0, 0.0, 0.0],
                "tol_mm": 2.0,
            },
            "the requirement is reach, not clearance",
        )
        entry = state.by_id["mc-elbow-clear"]
        assert entry.kind == "reach"
        assert entry.min_mm is None and entry.a is None and entry.b is None
        # Round-trips through its own generation document.
        assert (
            entry.to_json()
            == MotionCheckState.from_document(
                {"generation": 1, "entries": [entry.to_json()]}, "blob"
            )
            .entries[0]
            .to_json()
        )

    def test_an_update_that_breaks_the_kind_shape_is_refused(self, checks: MotionCheckSet) -> None:
        checks.declare(clear())
        with pytest.raises(MotionCheckError):
            checks.update("mc-elbow-clear", {"tol_mm": 0.5}, "tolerance on a clearance check")
