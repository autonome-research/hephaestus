"""The ``KINEMATICS.md`` §6 kinematics tools (Stage 9A/9B), as thin ops over the engine.

``declare_joint`` / ``update_joint`` / ``read_joints``, ``declare_pose`` /
``update_pose`` / ``read_poses``, ``declare_motion_check`` /
``update_motion_check`` / ``read_motion_checks``, and ``check_motion``.
Everything these do lives one layer down and is deliberately not
reimplemented here (the ``_assembly`` precedent, applied verbatim):

* :class:`~hephaestus.core.project_store.kinematics.JointSet`,
  :class:`~hephaestus.core.project_store.kinematics.PoseSet` and
  :class:`~hephaestus.core.project_store.kinematics.MotionCheckSet` own the
  generational state — validation, the compelled provenance, the forest check,
  the §4 grid-total cap, the CAS swap under the project-config lock, and the
  idempotent WAL write keyed on the invocation id (``KINEMATICS.md``
  §1/§3/§4, the ledger's pattern);
* :class:`~hephaestus.core.motion.MotionEvaluator` owns anchor and frame
  resolution against the parts' current build artifacts and the
  ``resolved | unresolvable`` naming of both ``MotionStatus`` sections (§2);
* :class:`~hephaestus.core.motion.SweepEvaluator` owns the §4 bounded grids,
  the closed five-verdict result vocabulary, and the projection of a full
  run's results onto the motion projection.

What this module adds is exactly the tool surface: argument shapes, the stable
refusal tokens carried through from the sets (``invalid_joint`` /
``unknown_joint`` / ``cyclic_joint_graph``, ``invalid_pose`` /
``unknown_pose``, ``invalid_motion_check`` / ``unknown_motion_check``), the
``motion_timeout`` refusal shape (§4: the ceiling kill's partial per-sample
facts ride the error data, the ``compare_timeout`` rule), and the one result
projection each triplet shares.

**Declaring is model-writable, on purpose** — the 8C quartet decision and its
recorded rationale applied unchanged (``KINEMATICS.md`` §6): a joint or pose is
cheap, reversible and *checked* against geometry the model did not get to
choose, so a dishonest declaration fails loudly rather than passing quietly.
What the model cannot do is erase: ``update_joint``/``update_pose`` with
``withdrawn: true`` record a new generation carrying the reason, and every
earlier generation stays readable.

**Reading never measures.** ``read_joints``/``read_poses`` report the LAST
motion evaluation (``motion: null`` when there has never been one — which is
not a pass), ``read_motion_checks`` reports the LAST full run's sweep results
(``results: null`` for never evaluated, same rule), and ``check_motion`` is
the only thing that measures — now returning both the ``MotionStatus`` and
the per-check §4 results, exactly as its 9A contract said it would. ``ids``
narrows which motion checks run; a named subset is evaluated but never
projected (``partial: true``, the ``check_assembly`` rule).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

from hephaestus.core.errors import AddressingError
from hephaestus.core.motion import (
    MotionEvaluator,
    MotionStatus,
    MotionTimeout,
    SweepEvaluator,
    check_motion_with_results,
)
from hephaestus.core.project_store.kinematics import (
    JointError,
    JointSet,
    JointState,
    MotionCheckError,
    MotionCheckSet,
    MotionCheckState,
    PoseError,
    PoseSet,
    PoseState,
)
from hephaestus.core.render.posed import PosedSceneResult, render_posed_scene
from opstore.types import JSONValue

from ._base import CadOpError, CadOpsState

__all__ = ["MotionOps"]


def _refusal(exc: JointError | PoseError | MotionCheckError) -> CadOpError:
    """The engine's stable refusal token, carried through unchanged.

    ``JointError.reason`` / ``PoseError.reason`` / ``MotionCheckError.reason``
    are already the machine tokens the tool contract documents
    (``invalid_joint`` / ``unknown_joint`` / ``cyclic_joint_graph``,
    ``invalid_pose`` / ``unknown_pose``, ``invalid_motion_check`` /
    ``unknown_motion_check``), so the tool layer forwards them rather than
    re-deciding what a refusal means.
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
    """The ten ``KINEMATICS.md`` §6 kinematics tools (Stage 9A/9B)."""

    # -- seams -------------------------------------------------------------

    def joint_set(self) -> JointSet:
        """The project's joint set (generational state, §1)."""
        return JointSet(self.layout, self._store)

    def pose_set(self) -> PoseSet:
        """The project's pose set (§3), validating bindings against the joints."""
        return PoseSet(self.layout, self._store, self.joint_set())

    def motion_evaluator(self) -> MotionEvaluator:
        """The engine evaluator (§2) — also what the 9B reviewer reads."""
        return MotionEvaluator(self.layout, self._store)

    def motion_status(self) -> MotionStatus | None:
        """The last projected status, or ``None`` for *never evaluated*."""
        return self.motion_evaluator().projected()

    def motion_check_set(self) -> MotionCheckSet:
        """The project's motion-check set (§4), bindings checked against the joints."""
        return MotionCheckSet(self.layout, self._store, self.joint_set())

    def sweep_evaluator(self) -> SweepEvaluator:
        """The §4 sweep evaluator — what ``check_motion`` and the §5 reviewer run."""
        return SweepEvaluator(self.layout, self._store)

    def render_posed_scene(self, **kwargs: Any) -> PosedSceneResult:
        """The §6 posed-scene render over this project (the reviewer's seam).

        A thin pass-through to :func:`hephaestus.core.render.posed.render_posed_scene`
        so the review layer — which addresses the project only through these ops —
        can produce the posed renders ``VALIDATION.md`` §5 hands the reviewer
        without reaching into the store handle itself. Deliberately NOT a model
        tool and NOT dispatched (``KINEMATICS.md`` §6: the posed render is exposed
        through ``heph render --pose`` and the reviewer context only).
        """
        return render_posed_scene(self.layout, self._store, **kwargs)

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

    # -- motion-check writes (KINEMATICS.md §4, Stage 9B) -------------------

    def declare_motion_check(self, entry: Mapping[str, Any], *, op_id: str) -> dict[str, JSONValue]:
        """Declare one motion check; advances one generation.

        A repeated id is refused rather than replaced (revising is
        ``update_motion_check``, which records why); the set refuses a sweep
        over an undeclared, withdrawn or unsweepable joint, and a grid whose
        computed total exceeds the §4 cap, naming the total — nothing written
        on any refusal.
        """
        try:
            state = self.motion_check_set().declare(_clean(entry), op_id=op_id)
        except MotionCheckError as exc:
            raise _refusal(exc) from exc
        return self._motion_check_result(state)

    def update_motion_check(
        self, check_id: str, patch: Mapping[str, Any], reason: str, *, op_id: str
    ) -> dict[str, JSONValue]:
        """Revise **or withdraw** one motion check; advances one generation.

        ``patch = {"withdrawn": true}`` is the withdrawal path: one act with
        one recorded reason. A withdrawn check is never evaluated again, and
        its last recorded result stays readable exactly as measured — nothing
        erased, the 8C rule.
        """
        cleaned = _clean(patch)
        withdrawn = cleaned.pop("withdrawn", None)
        checks = self.motion_check_set()
        try:
            if withdrawn is True:
                if cleaned:
                    raise CadOpError(
                        "invalid_motion_check",
                        f"motion check {check_id}: a withdrawal records only its reason — "
                        f"patch also carries {sorted(cleaned)}; withdraw it, then declare "
                        "the replacement, so the two acts stay separately readable",
                    )
                state = checks.withdraw(check_id, reason, op_id=op_id)
            else:
                state = checks.update(check_id, cleaned, reason, op_id=op_id)
        except MotionCheckError as exc:
            raise _refusal(exc) from exc
        return self._motion_check_result(state)

    # -- reads -------------------------------------------------------------

    def read_joints(self) -> dict[str, JSONValue]:
        """The current joint generation plus the latest evaluation (nothing measured)."""
        return self._joint_result(self.joint_set().state())

    def read_poses(self) -> dict[str, JSONValue]:
        """The current pose generation plus the latest evaluation (nothing measured)."""
        return self._pose_result(self.pose_set().state())

    def read_motion_checks(self) -> dict[str, JSONValue]:
        """The current check generation plus the latest sweep results (nothing measured)."""
        return self._motion_check_result(self.motion_check_set().state())

    def check_motion(self, ids: Sequence[str] | None = None) -> dict[str, JSONValue]:
        """Evaluate now (``KINEMATICS.md`` §2/§4): ``MotionStatus`` + sweep results.

        Both status sections are always evaluated in full against CURRENT
        artifacts; ``ids`` narrows only which motion CHECKS run. A full run is
        recorded and projected so a later read — and the §5 reviewer — sees
        it; a named subset is evaluated but deliberately not projected, and
        says so with ``partial: true`` (the ``check_assembly`` rule). A check
        grid hitting the §4 wall-clock ceiling is the named ``motion_timeout``
        refusal, its partial per-sample facts riding the error data (the
        ``compare_timeout`` rule).
        """
        try:
            status, results, partial = check_motion_with_results(self.layout, self._store, ids=ids)
        except AddressingError as exc:
            # An unknown id is the motion-check-set half of the same refusal a
            # bad patch gets; reporting it as a part-addressing failure would
            # name the wrong namespace (the check_assembly rule).
            raise CadOpError(
                "unknown_motion_check",
                f"{exc.message} (declared: {', '.join(exc.candidates) or 'none'})",
            ) from exc
        except MotionTimeout as exc:
            raise CadOpError("motion_timeout", exc.message, data=exc.to_json()) from exc
        sweeps = self.sweep_evaluator()
        evaluator = self.motion_evaluator()
        return {
            "status": "ok",
            "motion": cast("JSONValue", status.to_json()),
            "artifact_ref": None if partial else evaluator.projected_ref(),
            "results": [cast("JSONValue", result.to_json()) for result in results],
            "results_ref": None if partial else sweeps.projected_results_ref(),
            "partial": partial,
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

    def _motion_check_result(self, state: MotionCheckState) -> dict[str, JSONValue]:
        """The result all three motion-check tools share.

        The results ride along as *evidence already taken*: the projection is
        read, never computed, so a write cannot quietly become a measurement —
        ``results: null`` means checks were never evaluated, which is not a
        pass. Re-measuring is ``check_motion``.
        """
        sweeps = self.sweep_evaluator()
        results = sweeps.projected_results()
        return {
            "status": "ok",
            "generation": state.generation,
            "artifact_ref": state.artifact_ref,
            "change": None if state.change is None else cast("JSONValue", state.change.to_json()),
            "entries": [cast("JSONValue", entry.to_json()) for entry in state.entries],
            "results": (
                None
                if results is None
                else [cast("JSONValue", result.to_json()) for result in results]
            ),
            "results_ref": sweeps.projected_results_ref(),
        }
