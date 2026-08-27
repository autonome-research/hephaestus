"""The ``KINEMATICS.md`` §6 Stage 9A kinematics tools, as thin ops over the engine.

``declare_joint`` / ``update_joint`` / ``read_joints``, ``declare_pose`` /
``update_pose`` / ``read_poses``, and ``check_motion``. Everything these do
lives one layer down and is deliberately not reimplemented here (the
``_assembly`` precedent, applied verbatim):

* :class:`~hephaestus.core.project_store.kinematics.JointSet` and
  :class:`~hephaestus.core.project_store.kinematics.PoseSet` own the
  generational state — validation, the compelled provenance, the forest check,
  the CAS swap under the project-config lock, and the idempotent WAL write
  keyed on the invocation id (``KINEMATICS.md`` §1/§3, the ledger's pattern);
* :class:`~hephaestus.core.motion.MotionEvaluator` owns anchor and frame
  resolution against the parts' current build artifacts and the
  ``resolved | unresolvable`` naming of both ``MotionStatus`` sections (§2).

What this module adds is exactly the tool surface: argument shapes, the stable
refusal tokens carried through from the sets (``invalid_joint`` /
``unknown_joint`` / ``cyclic_joint_graph``, ``invalid_pose`` /
``unknown_pose``), and the one result projection each triplet shares.

**Declaring is model-writable, on purpose** — the 8C quartet decision and its
recorded rationale applied unchanged (``KINEMATICS.md`` §6): a joint or pose is
cheap, reversible and *checked* against geometry the model did not get to
choose, so a dishonest declaration fails loudly rather than passing quietly.
What the model cannot do is erase: ``update_joint``/``update_pose`` with
``withdrawn: true`` record a new generation carrying the reason, and every
earlier generation stays readable.

**Reading never measures.** ``read_joints``/``read_poses`` report the LAST
motion evaluation (``motion: null`` when there has never been one — which is
not a pass), and ``check_motion`` is the only thing that measures. Motion
CHECKS (sweeps, reach) are Stage 9B: ``check_motion`` returns the
``MotionStatus`` alone, with no per-check results yet, and says so in its
contract rather than reserving dead result fields.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from hephaestus.core.motion import MotionEvaluator, MotionStatus
from hephaestus.core.project_store.kinematics import (
    JointError,
    JointSet,
    JointState,
    PoseError,
    PoseSet,
    PoseState,
)
from opstore.types import JSONValue

from ._base import CadOpError, CadOpsState

__all__ = ["MotionOps"]


def _refusal(exc: JointError | PoseError) -> CadOpError:
    """The engine's stable refusal token, carried through unchanged.

    ``JointError.reason`` / ``PoseError.reason`` are already the machine tokens
    the tool contract documents (``invalid_joint`` / ``unknown_joint`` /
    ``cyclic_joint_graph``, ``invalid_pose`` / ``unknown_pose``), so the tool
    layer forwards them rather than re-deciding what a refusal means.
    """
    return CadOpError(exc.reason, exc.message)


def _clean(data: Mapping[str, Any]) -> dict[str, JSONValue]:
    """Drop ``null`` arguments so a schema default reads as "not supplied".

    The generated schemas give every optional field ``default: null``, and a
    caller (or the MCP/REST path) may send them explicitly. ``limits: null`` is
    an absent field, not a declared zero-travel range, and the set validators
    must see it as one. Nested objects are cleaned shallowly per level, the
    ``_assembly`` rule.
    """
    out: dict[str, JSONValue] = {}
    for key, value in data.items():
        if value is None:
            continue
        if isinstance(value, dict):
            nested = _clean(cast("Mapping[str, Any]", value))
            out[key] = cast("JSONValue", nested)
            continue
        out[key] = cast("JSONValue", value)
    return out


class MotionOps(CadOpsState):
    """The seven Stage 9A kinematics tools (``KINEMATICS.md`` §6)."""

    # -- seams -------------------------------------------------------------

    def joint_set(self) -> JointSet:
        """The project's joint set (generational state, §1)."""
        return JointSet(self.layout, self._store)

    def pose_set(self) -> PoseSet:
        """The project's pose set (§3), validating bindings against the joints."""
        return PoseSet(self.layout, self._store, self.joint_set())

    def motion_evaluator(self) -> MotionEvaluator:
        """The engine evaluator (§2) — also what the 9B reviewer will read."""
        return MotionEvaluator(self.layout, self._store)

    def motion_status(self) -> MotionStatus | None:
        """The last projected status, or ``None`` for *never evaluated*."""
        return self.motion_evaluator().projected()

    # -- joint writes ------------------------------------------------------

    def declare_joint(self, entry: Mapping[str, Any], *, op_id: str) -> dict[str, JSONValue]:
        """Declare one joint; advances one generation.

        A repeated id is refused rather than replaced: revising a claim is
        ``update_joint``, which records why. The candidate edge set is
        forest-checked before anything is written (§1).
        """
        try:
            state = self.joint_set().declare(_clean(entry), op_id=op_id)
        except JointError as exc:
            raise _refusal(exc) from exc
        return self._joint_result(state)

    def update_joint(
        self, joint_id: str, patch: Mapping[str, Any], reason: str, *, op_id: str
    ) -> dict[str, JSONValue]:
        """Revise **or withdraw** one joint; advances one generation.

        ``patch = {"withdrawn": true}`` is the withdrawal path: one act with one
        recorded reason, routed to the set's own withdrawal so a withdrawn
        entry stops being evaluated while staying stored. A pose that binds the
        joint is deliberately untouched — it becomes ``orphaned_pose`` at
        evaluation (§2/§3), never an erasure and never a joint failure.
        """
        cleaned = _clean(patch)
        withdrawn = cleaned.pop("withdrawn", None)
        joints = self.joint_set()
        try:
            if withdrawn is True:
                if cleaned:
                    raise CadOpError(
                        "invalid_joint",
                        f"joint {joint_id}: a withdrawal records only its reason — patch "
                        f"also carries {sorted(cleaned)}; withdraw it, then declare the "
                        "replacement, so the two acts stay separately readable",
                    )
                state = joints.withdraw(joint_id, reason, op_id=op_id)
            else:
                state = joints.update(joint_id, cleaned, reason, op_id=op_id)
        except JointError as exc:
            raise _refusal(exc) from exc
        return self._joint_result(state)

    # -- pose writes -------------------------------------------------------

    def declare_pose(self, entry: Mapping[str, Any], *, op_id: str) -> dict[str, JSONValue]:
        """Declare one named pose; advances one generation.

        Every bound joint id must be declared and unwithdrawn *now* (§3) —
        refused ``invalid_pose`` otherwise; a pose born orphaned would be a
        claim about nothing.
        """
        try:
            state = self.pose_set().declare(_clean(entry), op_id=op_id)
        except PoseError as exc:
            raise _refusal(exc) from exc
        return self._pose_result(state)

    def update_pose(
        self, pose_id: str, patch: Mapping[str, Any], reason: str, *, op_id: str
    ) -> dict[str, JSONValue]:
        """Revise **or withdraw** one pose; advances one generation."""
        cleaned = _clean(patch)
        withdrawn = cleaned.pop("withdrawn", None)
        poses = self.pose_set()
        try:
            if withdrawn is True:
                if cleaned:
                    raise CadOpError(
                        "invalid_pose",
                        f"pose {pose_id}: a withdrawal records only its reason — patch "
                        f"also carries {sorted(cleaned)}; withdraw it, then declare the "
                        "replacement, so the two acts stay separately readable",
                    )
                state = poses.withdraw(pose_id, reason, op_id=op_id)
            else:
                state = poses.update(pose_id, cleaned, reason, op_id=op_id)
        except PoseError as exc:
            raise _refusal(exc) from exc
        return self._pose_result(state)

    # -- reads -------------------------------------------------------------

    def read_joints(self) -> dict[str, JSONValue]:
        """The current joint generation plus the latest evaluation (nothing measured)."""
        return self._joint_result(self.joint_set().state())

    def read_poses(self) -> dict[str, JSONValue]:
        """The current pose generation plus the latest evaluation (nothing measured)."""
        return self._pose_result(self.pose_set().state())

    def check_motion(self) -> dict[str, JSONValue]:
        """Evaluate now (``KINEMATICS.md`` §2) and return the ``MotionStatus``.

        Both sections, against CURRENT artifacts, recorded and projected so a
        later read — and the 9B-amended reviewer — sees it. Per-check results
        (sweeps, reach) are Stage 9B and deliberately absent, not empty.
        """
        evaluator = self.motion_evaluator()
        status = evaluator.evaluate()
        return {
            "status": "ok",
            "motion": cast("JSONValue", status.to_json()),
            "artifact_ref": evaluator.projected_ref(),
        }

    # -- the shared projections --------------------------------------------

    def _joint_result(self, state: JointState) -> dict[str, JSONValue]:
        """The result all three joint-set tools share (the 8C `_set_result` rule).

        The evaluation rides along as *evidence already taken*: the projection
        is read, never computed, so a write cannot quietly become a measurement.
        """
        evaluator = self.motion_evaluator()
        status = evaluator.projected()
        return {
            "status": "ok",
            "generation": state.generation,
            "artifact_ref": state.artifact_ref,
            "change": None if state.change is None else cast("JSONValue", state.change.to_json()),
            "entries": [cast("JSONValue", entry.to_json()) for entry in state.entries],
            "motion": None if status is None else cast("JSONValue", status.to_json()),
            "motion_ref": evaluator.projected_ref(),
        }

    def _pose_result(self, state: PoseState) -> dict[str, JSONValue]:
        """The result all three pose-set tools share."""
        evaluator = self.motion_evaluator()
        status = evaluator.projected()
        return {
            "status": "ok",
            "generation": state.generation,
            "artifact_ref": state.artifact_ref,
            "change": None if state.change is None else cast("JSONValue", state.change.to_json()),
            "entries": [cast("JSONValue", entry.to_json()) for entry in state.entries],
            "motion": None if status is None else cast("JSONValue", status.to_json()),
            "motion_ref": evaluator.projected_ref(),
        }
