# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""G9A: 8C constraints evaluated at named poses (``KINEMATICS.md`` §3).

Two halves, both gate clauses:

* **The unbound path is untouched, byte for byte.** ``data/
  g8c_unbound_status.json`` is the canonical JSON of a real evaluated status,
  recorded from the SAME fixture project BEFORE Stage 9A touched
  ``hephaestus.core.assembly``. Rebuilding that project and re-evaluating must
  reproduce those exact bytes — every existing constraint keeps its meaning
  and its evidence.
* **The pose-bound path extends the record explicitly.** A ``clearance_min``
  between the base and the arm measures the pin/bore radial air (0.1 mm) at
  zero and exactly 0.0 mm at the -90 deg limit pose, where the paddle lands on
  the stop: satisfied at zero, violated at the limit pose, with the worst
  pose's residual in the singular slot and one ``(pose_id, verdict,
  residual)`` row per bound pose. An unresolvable pose makes the row
  ``unresolvable_pose`` while the table keeps the partial evidence.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest
from _g9a import (
    ARM_PADDLE_CLEARANCE_AT_SWING_MM,
    NOMINAL_RADIAL_AIR_MM,
    assumed,
    make_wire_project,
    open_hinge_project,
)
from hephaestus.core.assembly import AssemblyEvaluator, AssemblyStatus, ConstraintOutcome
from hephaestus.core.project_store.constraints import ConstraintError, ConstraintSet
from hephaestus.core.project_store.kinematics import JointSet, PoseSet
from hephaestus.core.project_store.layout import ProjectLayout
from opstore.types import JSONValue

from opstore import OpStore, canonical_json

RECORDED_8C_STATUS = Path(__file__).parent / "data" / "g8c_unbound_status.json"


@pytest.fixture(scope="module")
def hinged(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[ProjectLayout, OpStore]]:
    """``base`` + ``arm`` built, the hinge declared, three poses named."""
    layout, store = open_hinge_project(tmp_path_factory.mktemp("hinge") / "proj")
    joints = JointSet(layout, store)
    poses = PoseSet(layout, store, joints)
    joints.declare(
        {
            "id": "j-hinge",
            "kind": "revolute",
            "parent": "base:hinge_bore",
            "child": "arm:hinge_pin",
            "limits": {"min": -90.0, "max": 90.0},
            "provenance": {"requirement": "r-1"},
        }
    )
    poses.declare({"id": "p-zero", "joints": {}, "provenance": assumed()})
    poses.declare({"id": "p-swung", "joints": {"j-hinge": -90.0}, "provenance": assumed()})
    poses.declare({"id": "p-over", "joints": {"j-hinge": 120.0}, "provenance": assumed()})
    # The orphan source: declared, bound, withdrawn.
    joints.declare(
        {
            "id": "j-temp",
            "kind": "revolute",
            "parent": "base:hinge_bore",
            "child": "phantom:pin",
            "limits": {"min": -10.0, "max": 10.0},
            "provenance": assumed(),
        }
    )
    poses.declare({"id": "p-orphan", "joints": {"j-temp": 1.0}, "provenance": assumed()})
    joints.withdraw("j-temp", "the temporary hinge was dropped from the design")
    yield layout, store
    store.close()


def _declare(
    layout: ProjectLayout, store: OpStore, entry: Mapping[str, JSONValue]
) -> ConstraintSet:
    constraints = ConstraintSet(layout, store)
    constraints.declare(entry)
    return constraints


def _outcome(status: AssemblyStatus, constraint_id: str) -> ConstraintOutcome:
    return next(item for item in status.constraints if item.id == constraint_id)


def _clearance(
    constraint_id: str, poses: list[str] | None, value_mm: float = 0.05
) -> dict[str, JSONValue]:
    entry: dict[str, JSONValue] = {
        "id": constraint_id,
        "kind": "clearance_min",
        "a": "base",
        "b": "arm",
        "value_mm": value_mm,
        "provenance": assumed(),
    }
    if poses is not None:
        entry["poses"] = list(poses)
    return entry


# ==========================================================================
# the unbound wire regression (byte for byte against recorded 8C evidence)


class TestUnboundWireRegression:
    def test_unbound_status_reproduces_the_recorded_8c_bytes(self, tmp_path: Path) -> None:
        recorded = RECORDED_8C_STATUS.read_text(encoding="utf-8").strip()
        layout, store = make_wire_project(tmp_path / "proj")
        try:
            status = AssemblyEvaluator(layout, store).evaluate(record=False)
            assert canonical_json(status.to_json()) == recorded
        finally:
            store.close()

    def test_the_recorded_evidence_has_no_stage9_keys(self) -> None:
        """The pinned document is genuinely the 8C shape: no pose vocabulary."""
        recorded = RECORDED_8C_STATUS.read_text(encoding="utf-8")
        assert '"pose_residuals"' not in recorded
        assert '"poses"' not in recorded

    def test_unbound_entries_stay_unchanged_next_to_bound_ones(
        self, hinged: tuple[ProjectLayout, OpStore]
    ) -> None:
        layout, store = hinged
        constraints = ConstraintSet(layout, store)
        constraints.declare(_clearance("c-plain", None))
        constraints.declare(_clearance("c-plain-bound", ["p-zero"]))
        status = AssemblyEvaluator(layout, store).evaluate(record=False)
        plain = _outcome(status, "c-plain").to_json()
        assert "pose_residuals" not in plain
        assert "poses" not in plain
        assert plain["state"] == "satisfied"
        bound = _outcome(status, "c-plain-bound").to_json()
        assert "pose_residuals" in bound


# ==========================================================================
# declaration: the poses field is validated, structurally


class TestPosesFieldDeclaration:
    def test_a_bound_entry_round_trips_through_the_generation(self, tmp_path: Path) -> None:
        layout, store = make_wire_project(tmp_path / "proj")
        try:
            constraints = ConstraintSet(layout, store)
            state = constraints.declare(
                {
                    "id": "c-bound",
                    "kind": "no_interference",
                    "a": "base",
                    "b": "pin",
                    "poses": ["p-a", "p-b"],
                    "provenance": assumed(),
                }
            )
            entry = state.by_id["c-bound"]
            assert entry.poses == ("p-a", "p-b")
            assert constraints.state().by_id["c-bound"].poses == ("p-a", "p-b")
        finally:
            store.close()

    @pytest.mark.parametrize(
        ("poses", "fragment"),
        [
            ([], "binds no pose"),
            (["p-a", "p-a"], "bound twice"),
            (["not an id!"], "must match"),
            ("p-a", "array of pose ids"),
        ],
    )
    def test_malformed_bindings_are_refused_by_name(
        self, tmp_path: Path, poses: Any, fragment: str
    ) -> None:
        layout, store = make_wire_project(tmp_path / "proj")
        try:
            constraints = ConstraintSet(layout, store)
            before = constraints.state().generation
            with pytest.raises(ConstraintError, match=fragment) as excinfo:
                constraints.declare(
                    {
                        "id": "c-bad",
                        "kind": "no_interference",
                        "a": "base",
                        "b": "pin",
                        "poses": poses,
                        "provenance": assumed(),
                    }
                )
            assert excinfo.value.reason == "invalid_constraint"
            # A refusal writes NOTHING.
            assert constraints.state().generation == before
        finally:
            store.close()


# ==========================================================================
# evaluation at poses: the extended outcome shape


class TestPoseBoundEvaluation:
    def test_satisfied_at_zero_violated_at_the_limit_pose(
        self, hinged: tuple[ProjectLayout, OpStore]
    ) -> None:
        layout, store = hinged
        _declare(layout, store, _clearance("c-swing", ["p-zero", "p-swung"]))
        status = AssemblyEvaluator(layout, store).evaluate(record=False)
        outcome = _outcome(status, "c-swing")

        # Violated at ANY bound pose is violated.
        assert outcome.state == "violated"
        assert outcome.reason is None

        # One (pose_id, verdict, residual) row per bound pose, in order.
        assert [(row.pose_id, row.verdict) for row in outcome.pose_residuals] == [
            ("p-zero", "satisfied"),
            ("p-swung", "violated"),
        ]
        at_zero, at_swing = outcome.pose_residuals
        assert at_zero.residual is not None and at_swing.residual is not None
        # At zero the arm/base clearance is the pin/bore radial air...
        measured_zero = at_zero.residual["measured"]
        assert isinstance(measured_zero, float)
        assert measured_zero == pytest.approx(NOMINAL_RADIAL_AIR_MM, abs=1e-9)
        # ...and at -90 deg the paddle lands exactly on the stop.
        measured_swing = at_swing.residual["measured"]
        assert isinstance(measured_swing, float)
        assert measured_swing == pytest.approx(ARM_PADDLE_CLEARANCE_AT_SWING_MM, abs=1e-9)

        # The singular residual slot carries the WORST pose's residual.
        assert outcome.residual == at_swing.residual
        assert outcome.residual != at_zero.residual
        assert status.blocking() == ("c-swing",) or "c-swing" in status.blocking()

    def test_a_row_satisfied_at_every_pose_is_satisfied(
        self, hinged: tuple[ProjectLayout, OpStore]
    ) -> None:
        layout, store = hinged
        _declare(layout, store, _clearance("c-easy", ["p-zero"], value_mm=0.05))
        status = AssemblyEvaluator(layout, store).evaluate(record=False)
        outcome = _outcome(status, "c-easy")
        assert outcome.state == "satisfied"
        assert [row.verdict for row in outcome.pose_residuals] == ["satisfied"]
        assert outcome.residual == outcome.pose_residuals[0].residual

    def test_wire_shape_of_a_bound_row_is_the_extended_record(
        self, hinged: tuple[ProjectLayout, OpStore]
    ) -> None:
        layout, store = hinged
        _declare(layout, store, _clearance("c-wire", ["p-zero", "p-swung"]))
        status = AssemblyEvaluator(layout, store).evaluate(record=False)
        row = _outcome(status, "c-wire").to_json()
        table = row["pose_residuals"]
        assert isinstance(table, list) and len(table) == 2
        for item in table:
            assert isinstance(item, dict)
            assert set(item) == {"pose_id", "verdict", "residual", "reason", "detail"}
        # ...and the round trip preserves it.
        rebuilt = ConstraintOutcome.from_json(row)
        assert rebuilt.to_json() == row


# ==========================================================================
# unresolvable poses make the row unresolvable — named, with partial evidence


class TestUnresolvablePoses:
    def test_unknown_pose(self, hinged: tuple[ProjectLayout, OpStore]) -> None:
        layout, store = hinged
        _declare(layout, store, _clearance("c-ghost", ["p-ghost"]))
        status = AssemblyEvaluator(layout, store).evaluate(record=False)
        outcome = _outcome(status, "c-ghost")
        assert outcome.state == "unresolvable"
        assert outcome.reason == "unresolvable_pose"
        assert outcome.detail is not None and "unknown_pose" in outcome.detail
        assert outcome.residual is None
        assert outcome.pose_residuals[0].verdict == "unresolvable"
        assert outcome.pose_residuals[0].reason == "unknown_pose"

    def test_orphaned_pose_names_the_withdrawn_joint(
        self, hinged: tuple[ProjectLayout, OpStore]
    ) -> None:
        layout, store = hinged
        _declare(layout, store, _clearance("c-orphan", ["p-orphan"]))
        status = AssemblyEvaluator(layout, store).evaluate(record=False)
        outcome = _outcome(status, "c-orphan")
        assert outcome.state == "unresolvable"
        assert outcome.reason == "unresolvable_pose"
        assert outcome.detail is not None
        assert "orphaned_pose" in outcome.detail and "j-temp" in outcome.detail

    def test_out_of_limit_pose_is_refused_never_clamped(
        self, hinged: tuple[ProjectLayout, OpStore]
    ) -> None:
        layout, store = hinged
        _declare(layout, store, _clearance("c-over", ["p-over"]))
        status = AssemblyEvaluator(layout, store).evaluate(record=False)
        outcome = _outcome(status, "c-over")
        assert outcome.state == "unresolvable"
        assert outcome.reason == "unresolvable_pose"
        assert outcome.detail is not None and "joint_limit_exceeded" in outcome.detail

    def test_partial_evidence_is_kept_in_the_pose_table(
        self, hinged: tuple[ProjectLayout, OpStore]
    ) -> None:
        layout, store = hinged
        _declare(layout, store, _clearance("c-mixed", ["p-zero", "p-ghost"]))
        status = AssemblyEvaluator(layout, store).evaluate(record=False)
        outcome = _outcome(status, "c-mixed")
        assert outcome.state == "unresolvable"
        # The evaluable pose's verdict is still recorded — partial evidence,
        # never discarded — while the row itself claims no measurement.
        assert [(row.pose_id, row.verdict) for row in outcome.pose_residuals] == [
            ("p-zero", "satisfied"),
            ("p-ghost", "unresolvable"),
        ]
        assert outcome.residual is None

    def test_shape_refusal_is_row_level_not_per_pose(
        self, hinged: tuple[ProjectLayout, OpStore]
    ) -> None:
        """A rigid placement changes no face's class, so a wrong-class pair is
        the same fault at every pose: reported once, exactly as unbound."""
        layout, store = hinged
        constraints = ConstraintSet(layout, store)
        constraints.declare(
            {
                "id": "c-shape",
                "kind": "concentric",
                "a": "base:slide_face",  # planar: no cylinder to be concentric
                "b": "arm:hinge_pin",
                "tol_mm": 0.1,
                "poses": ["p-zero"],
                "provenance": assumed(),
            }
        )
        status = AssemblyEvaluator(layout, store).evaluate(record=False)
        outcome = _outcome(status, "c-shape")
        assert outcome.state == "unresolvable"
        assert outcome.reason == "shape_refused"
        assert outcome.pose_residuals == ()
