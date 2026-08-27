# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""Motion evaluation: declared joints and poses measured against current builds.

``KINEMATICS.md`` §2, second bullet — the engine half of Stage 9A.
:mod:`hephaestus.geom.kinematics` answers "where does each part sit at this
parameter assignment?" for joint frames a caller already holds; this module
answers the questions geometry cannot: *which* frame a ``part[:selector]``
anchor names, whether the two anchors of a joint actually agree on it, and
what a joint or pose that could not be evaluated is called.

The pipeline is one pass per joint, riding the 8C anchoring path verbatim
(:class:`hephaestus.core.assembly.AnchorResolver` — one implementation of "§7
against a published artifact", shared, not copied):

1. **Resolve** each anchor against the part's CURRENT successful build
   artifact.
2. **Extract the frame** from the PARENT anchor's geometry — a cylindrical
   face or circular edge names an axis (``revolute`` / ``cylindrical``), a
   planar face or linear edge names a direction (``prismatic``), any
   resolvable anchor serves ``fixed``. The wrong shape class is a named
   refusal (the ``ConstraintShapeError`` taxonomy extended with
   :data:`FRAME_SHAPE_REFUSALS`), never a guessed frame.
3. **Measure the child against the parent** (``KINEMATICS.md`` §1: the parent
   anchor's frame IS the joint frame; the child names what rides it).
   Divergence beyond ``JOINT_FRAME_EPS_DEG`` (axis angle) or
   ``JOINT_FRAME_EPS_MM`` (radial offset) is ``misaligned_joint_anchors`` —
   never a silently chosen frame, never an average of two frames. The radial
   check applies to the axis-bearing kinds only: a prismatic direction is a
   free vector, so a lateral offset between its anchors is geometry, not
   disagreement.

The result is a :class:`MotionStatus` with **two sections**, exactly as §2
demands. Per-JOINT outcomes are ``resolved | unresolvable(reason)`` with the
reasons in :data:`JOINT_UNRESOLVABLE_REASONS` — the 8C set plus the genuinely
joint-level extensions. Per-POSE outcomes are ``resolved |
unresolvable(reason)`` with the reasons in :data:`POSE_UNRESOLVABLE_REASONS`;
``orphaned_pose`` lives here, naming the withdrawn joint id in its detail,
because withdrawal follows the 8C rule (never evaluated, not a failure) and a
pose naming a withdrawn joint is therefore a fact about the POSE. An
unresolvable joint makes every pose that binds it unresolvable
(``unresolvable_joint``, the joint named) — named, never skipped, never
conflated with a violated check.

**Pose-bound constraints** (``KINEMATICS.md`` §3) reuse this module through
:func:`motion_resolution` / :meth:`MotionResolution.transforms`: the assembly
evaluator hands over its own :class:`AnchorResolver` so one evaluation loads
each part exactly once, then asks for the forward-kinematics placement of a
pose over exactly the joints on the anchored parts' parent chains. A pose that
cannot supply a placement raises :class:`BoundPoseError` with a reason from
:data:`BOUND_POSE_REFUSALS`, which the assembly row reports as
``unresolvable_pose``.

**Staleness** rides the :class:`~hephaestus.core.project_store.projections.
MotionProjection` field of ``ProjectionState`` (the ``AssemblyProjection``
precedent, stated as such in §2): :meth:`MotionEvaluator.evaluate` with
``record`` stores the status document and projects it, publication restales it
when a joint-forest part is rebuilt into different geometry, and the GC edge
keeps a stale status readable — stale never reads as "never evaluated".

**Sweeps** (Stage 9B, ``KINEMATICS.md`` §4) are sampled motion checks: the
declared grid (``samples`` per axis, endpoints inclusive, product capped at
declaration) is evaluated sample by sample — forward kinematics places the
anchors' parts, the existing geom primitives measure them (``clearance`` /
``interference`` / ``distance`` to the target point), and the verdict comes
from the one closed set :data:`SWEEP_VERDICTS`, stated once. Universal kinds
say ``holds_at_samples`` — never "holds" — because all-good samples only
evidence; ``reach`` says ``satisfied`` because one achieving sample IS proof,
and its failure is ``not_reached_at_samples`` carrying the closest sample and
the miss distance, because samples not reaching prove nothing. Every result
records ``samples_evaluated`` (the grid total), the worst sample's parameter
values, and its measured value. Execution is bounded on the ``COMPARE.md`` §5
pattern, both legs (:func:`bounded_solid_diff`'s spawn-kill loop and the
bench ``_score`` per-sample streaming, copied rather than reinvented): the
grid runs in a killable spawned subprocess under
:data:`MOTION_TIMEOUT_S` (env :data:`MOTION_TIMEOUT_ENV`), per-sample facts
stream to the parent as they land, and a ceiling kill raises
:class:`MotionTimeout` CARRYING the samples already evaluated — partial
evidence, never a hang and never a silent pass.

**The CHECKS read surfaces** (Stage 9B, ``KINEMATICS.md`` §4 last bullet) ride
:class:`SnapshotMotionContext`: the owner of a project-scope check run
constructs it from the run's frozen snapshot ref and threads its
:meth:`~SnapshotMotionContext.at_pose` / :meth:`~SnapshotMotionContext.sweep`
into ``run_bundle`` alongside the ``imports`` callback, so ``m.at_pose`` and
``m.sweep`` resolve against the SAME frozen snapshot and motion generations
as the rest of the run (§2, last bullet — never CURRENT mid-run, enforced by
a pinned resolver that refuses a republished part by name), and the report
records those generations so motion evidence replays like every other kind.

**No solver, no verdict.** Nothing here moves authored geometry (a transform
exists only inside an evaluation, ``KINEMATICS.md`` §0) and nothing here
decides what an unresolvable joint *means* at termination review — that is the
``VALIDATION.md`` §5 rule, extended to motion by the 9B amendment;
:meth:`MotionStatus.blocking` only says which ids the rule would name.
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
import multiprocessing
import os
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Literal, cast, final

from hephaestus.core.assembly import (
    AnchorRef,
    AnchorResolver,
    PartGeometry,
    UnresolvableAnchorError,
    UnresolvableReason,
)
from hephaestus.core.errors import AddressingError, ValidationError
from hephaestus.core.project_store.constraints import Anchor
from hephaestus.core.project_store.kinematics import (
    JointEntry,
    JointSet,
    JointState,
    LimitPair,
    MotionCheckEntry,
    MotionCheckSet,
    MotionCheckState,
    PoseEntry,
    PoseSet,
    PoseState,
)
from hephaestus.core.project_store.layout import ProjectLayout
from hephaestus.core.project_store.projections import (
    PROJECT_SNAPSHOT_REF_PREFIX,
    MotionProjection,
)
from hephaestus.core.project_store.publication import Publisher
from hephaestus.core.project_store.store import artifact_ref as make_artifact_ref
from hephaestus.core.project_store.store import blob_hash_of_ref
from opstore.types import JSONValue

from opstore import OpStore, canonical_json

if TYPE_CHECKING:
    from hephaestus.geom import JointFrame, RigidTransform
    from hephaestus.geom.topology import Vec3

__all__ = [
    "BOUND_POSE_REFUSALS",
    "FRAME_SHAPE_REFUSALS",
    "JOINT_UNRESOLVABLE_REASONS",
    "MOTION_ARTIFACT_KIND",
    "MOTION_OUTCOME_STATES",
    "MOTION_RESULTS_ARTIFACT_KIND",
    "MOTION_TIMEOUT_ENV",
    "MOTION_TIMEOUT_S",
    "POSE_UNRESOLVABLE_REASONS",
    "SWEEP_UNRESOLVABLE_REASONS",
    "SWEEP_VERDICTS",
    "BoundPoseError",
    "JointOutcome",
    "MotionEvaluator",
    "MotionOutcomeState",
    "MotionResolution",
    "MotionStatus",
    "MotionTimeout",
    "PoseOutcome",
    "SnapshotMotionContext",
    "SweepEvaluator",
    "SweepResult",
    "SweepSample",
    "SweepVerdict",
    "check_motion",
    "check_motion_with_results",
    "evaluate_motion_checks",
    "motion_resolution",
    "motion_timeout_s",
    "sweep_axis_values",
]

#: Artifact kind of a stored (projected) motion-status document.
MOTION_ARTIFACT_KIND: Final[str] = "motion-status"

#: Artifact kind of a stored (projected) sweep-results document — the last
#: FULL motion-check evaluation's per-check results (``KINEMATICS.md`` §4),
#: riding the same motion projection as the status (§7: one piece of
#: non-ledger persistence, not two).
MOTION_RESULTS_ARTIFACT_KIND: Final[str] = "motion-results"

MotionOutcomeState = Literal["resolved", "unresolvable"]

#: The two per-joint and per-pose states (``KINEMATICS.md`` §2). Closed on
#: purpose: a joint set has nothing to satisfy or violate — those are the
#: CONSTRAINT vocabulary — so "could not be evaluated" has exactly one
#: spelling here, and it is not a pass.
MOTION_OUTCOME_STATES: Final[tuple[MotionOutcomeState, ...]] = ("resolved", "unresolvable")

JointUnresolvableReason = Literal[
    "missing_part",
    "no_current_build",
    "missing_artifact",
    "dangling_selector",
    "ambiguous_selector",
    "unaddressable_anchor",
    "shape_refused",
    "invalid_joint",
    "cyclic_joint_graph",
    "misaligned_joint_anchors",
]

#: Why a joint could not be resolved (``KINEMATICS.md`` §2). The first seven
#: reuse the 8C :data:`hephaestus.core.assembly.UNRESOLVABLE_REASONS`
#: spellings verbatim — same failure, same fix, same name — with
#: ``shape_refused`` carrying the extended frame taxonomy
#: (:data:`FRAME_SHAPE_REFUSALS`) in its detail. The genuinely joint-level
#: extensions:
#:
#: * ``invalid_joint`` — the stored entry is malformed (the joint twin of 8C's
#:   ``invalid_constraint``): the declaration path refuses these, so reaching
#:   it here means a generation written by an older or foreign writer — for
#:   example a part riding two joints, which forward kinematics cannot
#:   compose. Reported, never evaluated.
#: * ``cyclic_joint_graph`` — the active edges close a cycle over parts. Also
#:   a declaration-time refusal (§1), re-detected here for the same
#:   foreign-writer reason, with the same spelling so one fault has one name.
#: * ``misaligned_joint_anchors`` — both anchors resolved and both frames
#:   exist, but the child's diverges from the parent's beyond the named
#:   epsilons: the two parts do not agree on where the joint is, and picking
#:   either frame (or averaging) would measure a mechanism nobody declared.
JOINT_UNRESOLVABLE_REASONS: Final[tuple[JointUnresolvableReason, ...]] = (
    "missing_part",
    "no_current_build",
    "missing_artifact",
    "dangling_selector",
    "ambiguous_selector",
    "unaddressable_anchor",
    "shape_refused",
    "invalid_joint",
    "cyclic_joint_graph",
    "misaligned_joint_anchors",
)

PoseUnresolvableReason = Literal[
    "orphaned_pose",
    "unresolvable_joint",
    "joint_limit_exceeded",
    "invalid_pose",
]

#: Why a pose could not be evaluated (``KINEMATICS.md`` §2/§3):
#:
#: * ``orphaned_pose`` — the pose binds a joint the set has since withdrawn
#:   (or, foreign-writer case, never carried). The detail names the joint id.
#:   A per-POSE state on purpose: withdrawal is not a failure and the joint is
#:   never evaluated, so the fact lives with the pose that still names it.
#: * ``unresolvable_joint`` — a bound joint is itself unresolvable; the detail
#:   names it and its reason. Named, never skipped.
#: * ``joint_limit_exceeded`` — a bound value is outside the joint's declared
#:   limits. Refused with geom's own spelling; an evaluation never clamps.
#: * ``invalid_pose`` — the binding cannot be handed to the joint (a scalar
#:   for a 2-DOF ``cylindrical`` joint — the 9A pose wire shape has no pair
#:   form — or any value for a ``fixed`` one). Refused by name, never guessed.
POSE_UNRESOLVABLE_REASONS: Final[tuple[PoseUnresolvableReason, ...]] = (
    "orphaned_pose",
    "unresolvable_joint",
    "joint_limit_exceeded",
    "invalid_pose",
)

#: What a bound pose inside a CONSTRAINT row can fail with
#: (``KINEMATICS.md`` §3): the pose reasons plus ``unknown_pose`` — an entry
#: naming a pose the pose set does not carry active, which per-pose status
#: rows can never exhibit (they only cover declared poses).
BOUND_POSE_REFUSALS: Final[tuple[str, ...]] = (*POSE_UNRESOLVABLE_REASONS, "unknown_pose")

#: The frame extensions of the ``ConstraintShapeError`` taxonomy
#: (``KINEMATICS.md`` §1: "the wrong shape class is a named refusal,
#: ``ConstraintShapeError`` taxonomy extended, never a guessed frame"):
#:
#: * ``not_axial`` — an axis kind's anchor has neither a cylindrical face nor
#:   a circular edge, so it names no axis.
#: * ``not_directional`` — a prismatic anchor has neither a planar face nor a
#:   straight edge, so it names no direction (the 8C spelling, same meaning).
#: * ``ambiguous_axis`` / ``ambiguous_direction`` — the anchor's faces or
#:   edges name several frames that do not agree; picking one is what §7
#:   forbids everywhere else.
FRAME_SHAPE_REFUSALS: Final[frozenset[str]] = frozenset(
    {"not_axial", "not_directional", "ambiguous_axis", "ambiguous_direction"}
)


class BoundPoseError(Exception):
    """A bound pose cannot supply a placement — a named reason plus detail.

    Raised by :meth:`MotionResolution.transforms` and mapped by the assembly
    evaluator to the row-level ``unresolvable_pose`` state; ``reason`` is one
    of :data:`BOUND_POSE_REFUSALS`.
    """

    def __init__(self, pose_id: str, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.pose_id = pose_id
        self.reason = reason
        self.detail = detail


# --------------------------------------------------------------------------
# the records


@dataclass(frozen=True)
class JointOutcome:
    """One joint's state at one evaluation, with the evidence behind it."""

    id: str
    kind: str
    parent: AnchorRef
    child: AnchorRef
    state: MotionOutcomeState
    reason: JointUnresolvableReason | None = None
    detail: str | None = None
    provenance: Mapping[str, JSONValue] = field(default_factory=dict[str, "JSONValue"])
    note: str | None = None

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "id": self.id,
            "kind": self.kind,
            "parent": cast("JSONValue", self.parent.to_json()),
            "child": cast("JSONValue", self.child.to_json()),
            "state": self.state,
            "reason": self.reason,
            "detail": self.detail,
            "provenance": cast("JSONValue", dict(self.provenance)),
            "note": self.note,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, JSONValue]) -> JointOutcome:
        state = data.get("state")
        if state not in MOTION_OUTCOME_STATES:
            raise ValidationError(f"invalid joint state {state!r}", kind="contract")
        reason = data.get("reason")
        provenance = data.get("provenance")
        return cls(
            id=str(data.get("id", "")),
            kind=str(data.get("kind", "")),
            parent=_anchor_ref_from_json(data.get("parent")),
            child=_anchor_ref_from_json(data.get("child")),
            state=state,
            reason=reason if reason in JOINT_UNRESOLVABLE_REASONS else None,
            detail=_opt_str(data.get("detail")),
            provenance=(
                cast("Mapping[str, JSONValue]", provenance) if isinstance(provenance, dict) else {}
            ),
            note=_opt_str(data.get("note")),
        )


@dataclass(frozen=True)
class PoseOutcome:
    """One pose's state at one evaluation, with its binding restated."""

    id: str
    joints: Mapping[str, float]
    state: MotionOutcomeState
    reason: PoseUnresolvableReason | None = None
    detail: str | None = None
    provenance: Mapping[str, JSONValue] = field(default_factory=dict[str, "JSONValue"])
    note: str | None = None

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "id": self.id,
            "joints": {name: self.joints[name] for name in sorted(self.joints)},
            "state": self.state,
            "reason": self.reason,
            "detail": self.detail,
            "provenance": cast("JSONValue", dict(self.provenance)),
            "note": self.note,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, JSONValue]) -> PoseOutcome:
        state = data.get("state")
        if state not in MOTION_OUTCOME_STATES:
            raise ValidationError(f"invalid pose state {state!r}", kind="contract")
        reason = data.get("reason")
        provenance = data.get("provenance")
        raw_joints = data.get("joints")
        joints: dict[str, float] = {}
        if isinstance(raw_joints, dict):
            for name, value in cast("Mapping[str, JSONValue]", raw_joints).items():
                if not isinstance(value, bool) and isinstance(value, int | float):
                    joints[name] = float(value)
        return cls(
            id=str(data.get("id", "")),
            joints=joints,
            state=state,
            reason=reason if reason in POSE_UNRESOLVABLE_REASONS else None,
            detail=_opt_str(data.get("detail")),
            provenance=(
                cast("Mapping[str, JSONValue]", provenance) if isinstance(provenance, dict) else {}
            ),
            note=_opt_str(data.get("note")),
        )


def _opt_str(value: JSONValue | None) -> str | None:
    return value if isinstance(value, str) else None


def _anchor_ref_from_json(data: JSONValue | None) -> AnchorRef:
    if not isinstance(data, dict):
        return AnchorRef(anchor="", part="", selector="")
    raw = cast("Mapping[str, JSONValue]", data)
    rule = raw.get("rule")
    ref = raw.get("artifact_ref")
    return AnchorRef(
        anchor=str(raw.get("anchor", "")),
        part=str(raw.get("part", "")),
        selector=str(raw.get("selector", "")),
        rule=rule if isinstance(rule, str) else None,
        artifact_ref=ref if isinstance(ref, str) else None,
    )


@dataclass(frozen=True)
class MotionStatus:
    """Every declared joint's and pose's state at one evaluation (§2)."""

    joint_generation: int
    pose_generation: int
    joints: tuple[JointOutcome, ...]
    poses: tuple[PoseOutcome, ...]
    #: ``{part: artifact_ref}`` actually read for the joint forest, ``""`` for
    #: an anchored part that had no current build — the refs the projection
    #: compares against on later publications.
    artifact_refs: Mapping[str, str] = field(default_factory=dict[str, str])
    #: Parts whose current build has moved since this status was computed.
    #: Empty at evaluation time; publication fills it in.
    stale: tuple[str, ...] = ()

    @property
    def resolved_joints(self) -> tuple[str, ...]:
        return tuple(o.id for o in self.joints if o.state == "resolved")

    @property
    def unresolvable_joints(self) -> tuple[str, ...]:
        return tuple(o.id for o in self.joints if o.state == "unresolvable")

    @property
    def resolved_poses(self) -> tuple[str, ...]:
        return tuple(o.id for o in self.poses if o.state == "resolved")

    @property
    def unresolvable_poses(self) -> tuple[str, ...]:
        return tuple(o.id for o in self.poses if o.state == "unresolvable")

    def blocking(self) -> tuple[str, ...]:
        """Ids the never-green rule would fire on, joints first, in order.

        A fact about this status; whether it becomes a blocking finding is the
        (9B-amended) reviewer's act, exactly as with the assembly status.
        """
        return (*self.unresolvable_joints, *self.unresolvable_poses)

    @property
    def counts(self) -> dict[str, dict[str, int]]:
        return {
            "joints": {
                "resolved": len(self.resolved_joints),
                "unresolvable": len(self.unresolvable_joints),
            },
            "poses": {
                "resolved": len(self.resolved_poses),
                "unresolvable": len(self.unresolvable_poses),
            },
        }

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "joint_generation": self.joint_generation,
            "pose_generation": self.pose_generation,
            "joints": [outcome.to_json() for outcome in self.joints],
            "poses": [outcome.to_json() for outcome in self.poses],
            "artifact_refs": {
                name: self.artifact_refs[name] for name in sorted(self.artifact_refs)
            },
            "stale": list(self.stale),
            "counts": cast("JSONValue", self.counts),
            "blocking": list(self.blocking()),
        }

    @classmethod
    def from_json(cls, data: Mapping[str, JSONValue]) -> MotionStatus:
        joint_generation = data.get("joint_generation")
        pose_generation = data.get("pose_generation")
        if (
            not isinstance(joint_generation, int)
            or isinstance(joint_generation, bool)
            or not isinstance(pose_generation, int)
            or isinstance(pose_generation, bool)
        ):
            raise ValidationError("motion status generations must be integers", kind="contract")
        raw_joints = data.get("joints")
        raw_poses = data.get("poses")
        if not isinstance(raw_joints, list) or not isinstance(raw_poses, list):
            raise ValidationError("motion status sections must be arrays", kind="contract")
        joints = tuple(
            JointOutcome.from_json(cast("Mapping[str, JSONValue]", item))
            for item in cast("list[JSONValue]", raw_joints)
            if isinstance(item, dict)
        )
        poses = tuple(
            PoseOutcome.from_json(cast("Mapping[str, JSONValue]", item))
            for item in cast("list[JSONValue]", raw_poses)
            if isinstance(item, dict)
        )
        refs_raw = data.get("artifact_refs", {})
        refs: dict[str, str] = {}
        if isinstance(refs_raw, dict):
            for name, value in cast("Mapping[str, JSONValue]", refs_raw).items():
                if isinstance(value, str):
                    refs[name] = value
        stale_raw = data.get("stale", [])
        stale: tuple[str, ...] = ()
        if isinstance(stale_raw, list):
            stale = tuple(
                item for item in cast("list[JSONValue]", stale_raw) if isinstance(item, str)
            )
        return cls(
            joint_generation=joint_generation,
            pose_generation=pose_generation,
            joints=joints,
            poses=poses,
            artifact_refs=refs,
            stale=stale,
        )


# --------------------------------------------------------------------------
# frame extraction (the ConstraintShapeError taxonomy, extended)


def _cylinder_axes(shape: Any) -> list[tuple[float, Vec3, Vec3]]:
    """``(area, axis_point, axis)`` per cylindrical face, largest first."""
    from hephaestus.geom.topology import cylindrical_faces

    records = sorted(cylindrical_faces(shape), key=lambda r: (-r.area, r.index))
    return [(record.area, record.axis_point, record.axis) for record in records]


def _circle_axes(shape: Any) -> list[tuple[float, Vec3, Vec3]]:
    """``(radius, center, axis)`` per circular edge, largest first.

    Circular edges are the frame form a bore rim or a bolt circle offers when
    no cylindrical face survives an anchor (``KINEMATICS.md`` §1). Read through
    the kernel's own curve adaptor, ordered by ``(-radius, index)`` so the
    answer never depends on enumeration luck.
    """
    from build123d import GeomType
    from OCP.BRepAdaptor import (  # pyright: ignore[reportMissingTypeStubs]
        BRepAdaptor_Curve,  # pyright: ignore[reportUnknownVariableType, reportAttributeAccessIssue]
    )

    out: list[tuple[float, int, Vec3, Vec3]] = []
    for index, edge in enumerate(list(shape.edges())):
        if edge.geom_type != GeomType.CIRCLE:
            continue
        adaptor = cast("Any", BRepAdaptor_Curve(edge.wrapped))
        circle = adaptor.Circle()
        axis = circle.Axis()
        location = axis.Location()
        direction = axis.Direction()
        center: Vec3 = (float(location.X()), float(location.Y()), float(location.Z()))
        axis_dir: Vec3 = (float(direction.X()), float(direction.Y()), float(direction.Z()))
        out.append((float(circle.Radius()), index, center, axis_dir))
    out.sort(key=lambda item: (-item[0], item[1]))
    return [(radius, center, axis_dir) for radius, _index, center, axis_dir in out]


def _axis_frame(shape: Any, *, kind: str, side: Literal["a", "b"]) -> tuple[Vec3, Vec3]:
    """``(point, direction)`` of the one axis ``shape`` names, or a refusal.

    Cylindrical faces are preferred; several are accepted only when they share
    one axis LINE (a stepped or split bore — the radii may differ, the line
    may not). Circular edges serve when no cylindrical face does, under the
    same one-line rule. Anything else is ``not_axial``: a revolute frame from
    a box would be a guess, and §1 forbids guessed frames by name.
    """
    from hephaestus.geom import (
        JOINT_FRAME_EPS_DEG,
        JOINT_FRAME_EPS_MM,
        ConstraintShapeError,
        frame_axis_angle_deg,
        frame_radial_offset_mm,
    )

    for candidates, flavour in ((_cylinder_axes(shape), "face"), (_circle_axes(shape), "edge")):
        if not candidates:
            continue
        _, point, direction = candidates[0]
        for _, other_point, other_direction in candidates[1:]:
            aligned = frame_axis_angle_deg(direction, other_direction) <= JOINT_FRAME_EPS_DEG
            on_line = frame_radial_offset_mm(point, direction, other_point) <= JOINT_FRAME_EPS_MM
            if not (aligned and on_line):
                noun = "cylindrical faces" if flavour == "face" else "circular edges"
                raise ConstraintShapeError(
                    "ambiguous_axis",
                    f"{kind}: side {side!r} has {len(candidates)} {noun} that do not "
                    "share one axis line, so it names no single joint axis",
                    kind=kind,
                    side=side,
                )
        return point, direction
    raise ConstraintShapeError(
        "not_axial",
        f"{kind}: side {side!r} has neither a cylindrical face nor a circular edge, "
        "so it names no axis",
        kind=kind,
        side=side,
    )


def _direction_frame(shape: Any, *, kind: str, side: Literal["a", "b"]) -> tuple[Vec3, Vec3]:
    """``(point, direction)`` of the one direction ``shape`` names, or a refusal.

    A planar face means its NORMAL (the documented 8C ``_direction_of``
    precedence, restated rather than reinvented); several planar faces must
    agree on one normal axis. Straight edges serve when no planar face does
    and must all be parallel. Anything else is ``not_directional``.
    """
    from hephaestus.geom import JOINT_FRAME_EPS_DEG, ConstraintShapeError, frame_axis_angle_deg
    from hephaestus.geom.topology import planar_faces

    records = sorted(planar_faces(shape), key=lambda r: (-r.area, r.index))
    if records:
        ref = records[0]
        for other in records[1:]:
            if frame_axis_angle_deg(ref.normal, other.normal) > JOINT_FRAME_EPS_DEG:
                raise ConstraintShapeError(
                    "ambiguous_direction",
                    f"{kind}: side {side!r} has {len(records)} planar faces whose "
                    "normals do not agree on one direction",
                    kind=kind,
                    side=side,
                )
        return ref.center, ref.normal
    line = _line_frame(shape, kind=kind, side=side)
    if line is not None:
        return line
    raise ConstraintShapeError(
        "not_directional",
        f"{kind}: side {side!r} has neither a planar face nor a straight edge, "
        "so it names no direction",
        kind=kind,
        side=side,
    )


def _line_frame(shape: Any, *, kind: str, side: Literal["a", "b"]) -> tuple[Vec3, Vec3] | None:
    """``(midpoint, tangent)`` of the shape's straight edges, or ``None``.

    All straight, all parallel, or the shape does not name one direction
    (``ambiguous_direction`` when straight edges disagree; ``None`` when there
    are none or a curved edge is among them, leaving the caller's
    ``not_directional`` to fire).
    """
    from build123d import GeomType
    from hephaestus.geom import JOINT_FRAME_EPS_DEG, ConstraintShapeError, frame_axis_angle_deg

    found: tuple[Vec3, Vec3] | None = None
    for count, edge in enumerate(list(shape.edges()), start=1):
        if edge.geom_type != GeomType.LINE:
            return None
        start = edge.start_point()
        end = edge.end_point()
        tangent: Vec3 = (
            float(end.X) - float(start.X),
            float(end.Y) - float(start.Y),
            float(end.Z) - float(start.Z),
        )
        midpoint: Vec3 = (
            (float(start.X) + float(end.X)) / 2.0,
            (float(start.Y) + float(end.Y)) / 2.0,
            (float(start.Z) + float(end.Z)) / 2.0,
        )
        if found is None:
            found = (midpoint, tangent)
        elif frame_axis_angle_deg(found[1], tangent) > JOINT_FRAME_EPS_DEG:
            raise ConstraintShapeError(
                "ambiguous_direction",
                f"{kind}: side {side!r} has {count} straight edges that are not "
                "parallel, so it names no single direction",
                kind=kind,
                side=side,
            )
    return found


def _anchor_center(shape: Any) -> Vec3:
    """A fixed anchor's reference point (its bounding-box centre)."""
    box = shape.bounding_box()
    return (
        (float(box.min.X) + float(box.max.X)) / 2.0,
        (float(box.min.Y) + float(box.max.Y)) / 2.0,
        (float(box.min.Z) + float(box.max.Z)) / 2.0,
    )


# --------------------------------------------------------------------------
# resolution


class MotionResolution:
    """One evaluation's resolved joint forest and pose set.

    Built over a shared :class:`AnchorResolver`, so the assembly evaluator's
    pose-bound path and :class:`MotionEvaluator` load each part exactly once
    per evaluation. Everything is resolved eagerly at construction — the two
    outcome sections are facts about ONE consistent read of the stores, not a
    lazy view that could straddle a concurrent write.
    """

    def __init__(
        self, joint_state: JointState, pose_state: PoseState, resolver: AnchorResolver
    ) -> None:
        self.joint_state = joint_state
        self.pose_state = pose_state
        self._frames: dict[str, JointFrame] = {}
        self._joint_failures: dict[str, tuple[JointUnresolvableReason, str]] = {}
        self._parent_of: dict[str, JointEntry] = {}
        self.joint_outcomes = self._resolve_joints(resolver)
        self._pose_failures: dict[str, tuple[PoseUnresolvableReason, str]] = {}
        self.pose_outcomes = self._resolve_poses()

    # -- joints -------------------------------------------------------------

    def _resolve_joints(self, resolver: AnchorResolver) -> tuple[JointOutcome, ...]:
        """Per-joint outcomes in declaration order (withdrawn: never evaluated)."""
        active = self.joint_state.active
        structural = self._structural_failures(active)
        outcomes: list[JointOutcome] = []
        for entry in active:
            parent_anchor, child_anchor = entry.anchors
            refs = [
                AnchorRef(anchor=anchor.text, part=anchor.part, selector=anchor.selector)
                for anchor in (parent_anchor, child_anchor)
            ]
            failure = structural.get(entry.id)
            if failure is None:
                failure = self._resolve_frames(entry, parent_anchor, child_anchor, refs, resolver)
            if failure is not None:
                self._joint_failures[entry.id] = failure
                reason, detail = failure
                outcomes.append(
                    JointOutcome(
                        id=entry.id,
                        kind=entry.kind,
                        parent=refs[0],
                        child=refs[1],
                        state="unresolvable",
                        reason=reason,
                        detail=detail,
                        provenance=entry.provenance.to_json(),
                        note=entry.note,
                    )
                )
                continue
            outcomes.append(
                JointOutcome(
                    id=entry.id,
                    kind=entry.kind,
                    parent=refs[0],
                    child=refs[1],
                    state="resolved",
                    provenance=entry.provenance.to_json(),
                    note=entry.note,
                )
            )
        return tuple(outcomes)

    def _structural_failures(
        self, active: tuple[JointEntry, ...]
    ) -> dict[str, tuple[JointUnresolvableReason, str]]:
        """Forest-shape refusals (§1), re-detected against stored generations.

        The declaration path already refuses these, so hitting one here means
        a generation written by an older or foreign writer — reported with the
        declaration path's own spellings, never evaluated. Every joint on a
        cycle is named, so no member of a broken loop reads as resolved.
        """
        failures: dict[str, tuple[JointUnresolvableReason, str]] = {}
        for entry in active:
            parent_part, child_part = entry.anchors[0].part, entry.anchors[1].part
            if parent_part == child_part:
                failures[entry.id] = (
                    "cyclic_joint_graph",
                    f"joint {entry.id} relates part {parent_part!r} to itself",
                )
                continue
            prior = self._parent_of.get(child_part)
            if prior is not None:
                failures[entry.id] = (
                    "invalid_joint",
                    f"part {child_part!r} already rides joint {prior.id!r}; the joint "
                    "graph must be a forest (KINEMATICS.md §1)",
                )
                continue
            self._parent_of[child_part] = entry
        for start in sorted(self._parent_of):
            path: list[str] = [start]
            joints: list[str] = []
            seen = {start}
            current = start
            while current in self._parent_of:
                entry = self._parent_of[current]
                joints.append(entry.id)
                current = entry.anchors[0].part
                if current in seen:
                    cycle = " -> ".join((*path[path.index(current) :], current))
                    for joint_id in joints:
                        failures.setdefault(
                            joint_id,
                            (
                                "cyclic_joint_graph",
                                f"the joint graph is not a forest; cycle: {cycle} "
                                f"(via joints {', '.join(joints)})",
                            ),
                        )
                    break
                path.append(current)
                seen.add(current)
        return failures

    def _resolve_frames(
        self,
        entry: JointEntry,
        parent_anchor: Anchor,
        child_anchor: Anchor,
        refs: list[AnchorRef],
        resolver: AnchorResolver,
    ) -> tuple[JointUnresolvableReason, str] | None:
        """Resolve and extract the parent frame first, then measure the child.

        Parent-first on purpose: the parent anchor's frame IS the joint frame
        (§1), so a joint whose frame owner cannot supply one is reported for
        THAT — a missing child part behind an unframeable parent is a second
        fault, not the first. On success the joint's
        :class:`~hephaestus.geom.JointFrame` (parent frame, per §1) lands in
        ``self._frames`` and ``None`` is returned; a failure is the
        ``(reason, detail)`` pair, with ``refs`` updated as far as resolution
        got.
        """
        from hephaestus.geom import (
            JOINT_FRAME_EPS_DEG,
            JOINT_FRAME_EPS_MM,
            ConstraintShapeError,
            JointFrame,
            frame_axis_angle_deg,
            frame_radial_offset_mm,
        )

        sides = ("parent", "child")
        shapes: list[Any] = []
        frames: list[tuple[Vec3, Vec3]] = []
        for position, anchor in enumerate((parent_anchor, child_anchor)):
            try:
                geometry, resolution = resolver.locate(anchor.part, anchor.selector)
            except UnresolvableAnchorError as exc:
                return _joint_reason(exc.reason), f"anchor {sides[position]}: {exc.detail}"
            refs[position] = dataclasses.replace(
                refs[position], rule=resolution.kind, artifact_ref=geometry.artifact_ref
            )
            try:
                shapes.append(geometry.shape_for(resolution))
            except UnresolvableAnchorError as exc:
                return _joint_reason(exc.reason), f"anchor {sides[position]}: {exc.detail}"
            if entry.kind == "fixed":
                # Any resolvable anchor serves a 0-DOF joint (§1); there is no
                # frame to extract and none to disagree on.
                continue
            side: Literal["a", "b"] = "a" if position == 0 else "b"
            try:
                if entry.kind == "prismatic":
                    frames.append(_direction_frame(shapes[position], kind=entry.kind, side=side))
                else:  # revolute / cylindrical
                    frames.append(_axis_frame(shapes[position], kind=entry.kind, side=side))
            except ConstraintShapeError as exc:
                return (
                    "shape_refused",
                    f"anchor {sides[position]}: {exc.reason} — {exc.message}",
                )
        if entry.kind == "fixed":
            self._frames[entry.id] = JointFrame(
                id=entry.id,
                kind="fixed",
                parent=parent_anchor.part,
                child=child_anchor.part,
                point=_anchor_center(shapes[0]),
                direction=(0.0, 0.0, 1.0),
            )
            return None
        (point, direction), (child_point, child_direction) = frames
        angle = frame_axis_angle_deg(direction, child_direction)
        if angle > JOINT_FRAME_EPS_DEG:
            return (
                "misaligned_joint_anchors",
                f"child frame diverges from the parent frame: axis angle "
                f"{angle:.6g} deg exceeds JOINT_FRAME_EPS_DEG ({JOINT_FRAME_EPS_DEG})",
            )
        # The radial check is for the kinds whose frame is an axis LINE. A
        # prismatic direction is a free vector — translation is the same
        # everywhere — so a lateral offset between its anchors is the
        # geometry of the slide, not a disagreement about the joint.
        if entry.kind in ("revolute", "cylindrical"):
            offset = frame_radial_offset_mm(point, direction, child_point)
            if offset > JOINT_FRAME_EPS_MM:
                return (
                    "misaligned_joint_anchors",
                    f"child frame diverges from the parent frame: radial offset "
                    f"{offset:.6g} mm exceeds JOINT_FRAME_EPS_MM ({JOINT_FRAME_EPS_MM})",
                )
        self._frames[entry.id] = JointFrame(
            id=entry.id,
            kind=cast("Any", entry.kind),
            parent=parent_anchor.part,
            child=child_anchor.part,
            point=point,
            direction=direction,
            limits=_geom_limits(entry.limits if entry.kind != "cylindrical" else entry.rotation),
            travel_limits=_geom_limits(entry.translation),
        )
        return None

    # -- poses --------------------------------------------------------------

    def _resolve_poses(self) -> tuple[PoseOutcome, ...]:
        """Per-pose outcomes in declaration order (withdrawn: never evaluated)."""
        outcomes: list[PoseOutcome] = []
        for pose in self.pose_state.active:
            failure = self._pose_failure(pose)
            if failure is not None:
                self._pose_failures[pose.id] = failure
            reason, detail = failure if failure is not None else (None, None)
            outcomes.append(
                PoseOutcome(
                    id=pose.id,
                    joints=dict(pose.joints),
                    state="resolved" if failure is None else "unresolvable",
                    reason=reason,
                    detail=detail,
                    provenance=pose.provenance.to_json(),
                    note=pose.note,
                )
            )
        return tuple(outcomes)

    def _pose_failure(self, pose: PoseEntry) -> tuple[PoseUnresolvableReason, str] | None:
        """The first (lexically by joint id) reason this pose cannot evaluate."""
        from hephaestus.geom import JointDeclarationError, JointLimitError, joint_transform

        declared = self.joint_state.by_id
        for joint_id in sorted(pose.joints):
            entry = declared.get(joint_id)
            if entry is None:
                return (
                    "orphaned_pose",
                    f"pose {pose.id} binds joint {joint_id!r}, which is not declared",
                )
            if entry.withdrawn:
                return (
                    "orphaned_pose",
                    f"pose {pose.id} binds withdrawn joint {joint_id!r} ({entry.withdrawn_reason})",
                )
            failure = self._joint_failures.get(joint_id)
            if failure is not None:
                return (
                    "unresolvable_joint",
                    f"pose {pose.id} binds joint {joint_id!r}, which is unresolvable "
                    f"({failure[0]}): {failure[1]}",
                )
            try:
                joint_transform(self._frames[joint_id], pose.joints[joint_id])
            except JointLimitError as exc:
                return "joint_limit_exceeded", exc.message
            except JointDeclarationError as exc:
                return "invalid_pose", exc.message
        return None

    # -- the sweep evaluator's read surface (§4) -----------------------------

    def joint_failure(self, joint_id: str) -> tuple[JointUnresolvableReason, str] | None:
        """Why ``joint_id`` is unresolvable at this evaluation, or ``None``."""
        return self._joint_failures.get(joint_id)

    def frame(self, joint_id: str) -> JointFrame:
        """The resolved :class:`~hephaestus.geom.JointFrame` of one resolved joint."""
        return self._frames[joint_id]

    def parent_joint(self, part: str) -> JointEntry | None:
        """The joint ``part`` rides (its one forest edge), or ``None`` if static."""
        return self._parent_of.get(part)

    # -- placements for pose-bound constraints (§3) --------------------------

    def transforms(self, pose_id: str, parts: Sequence[str]) -> dict[str, RigidTransform]:
        """World transform per requested part at one named pose.

        Exactly the joints on the parts' parent chains are evaluated (values
        from the pose, zero when omitted — including the limit check on
        implied zeros), so a broken joint elsewhere in the forest does not
        poison a row it cannot move. A part in no chain is static and comes
        back with the identity. Raises :class:`BoundPoseError` when the pose
        (or a chain joint) cannot supply a placement.
        """
        from hephaestus.geom import (
            IDENTITY_TRANSFORM,
            JointDeclarationError,
            JointLimitError,
            forward_kinematics,
        )

        pose = self.pose_state.by_id.get(pose_id)
        if pose is None:
            declared = ", ".join(sorted(self.pose_state.by_id)) or "(none)"
            raise BoundPoseError(
                pose_id,
                "unknown_pose",
                f"no pose {pose_id!r} is declared (declared poses: {declared})",
            )
        if pose.withdrawn:
            raise BoundPoseError(
                pose_id,
                "unknown_pose",
                f"pose {pose_id!r} is withdrawn ({pose.withdrawn_reason}); a withdrawn "
                "pose is never evaluated",
            )
        failure = self._pose_failures.get(pose_id)
        if failure is not None:
            raise BoundPoseError(pose_id, failure[0], failure[1])
        chain: dict[str, JointEntry] = {}
        for part in parts:
            current = part
            visited: set[str] = set()
            while current in self._parent_of:
                if current in visited:  # pragma: no cover - named structurally above
                    raise BoundPoseError(
                        pose_id, "unresolvable_joint", f"cyclic joint graph at part {current!r}"
                    )
                visited.add(current)
                entry = self._parent_of[current]
                joint_failure = self._joint_failures.get(entry.id)
                if joint_failure is not None:
                    raise BoundPoseError(
                        pose_id,
                        "unresolvable_joint",
                        f"part {part!r} rides joint {entry.id!r}, which is unresolvable "
                        f"({joint_failure[0]}): {joint_failure[1]}",
                    )
                chain[entry.id] = entry
                current = entry.anchors[0].part
        frames = tuple(self._frames[joint_id] for joint_id in chain)
        values = {joint_id: pose.joints[joint_id] for joint_id in chain if joint_id in pose.joints}
        try:
            world = forward_kinematics(frames, values)
        except JointLimitError as exc:
            raise BoundPoseError(pose_id, "joint_limit_exceeded", exc.message) from exc
        except JointDeclarationError as exc:  # pragma: no cover - frames are our own
            raise BoundPoseError(pose_id, "invalid_pose", exc.message) from exc
        return {part: world.get(part, IDENTITY_TRANSFORM) for part in parts}


def _joint_reason(reason: UnresolvableReason) -> JointUnresolvableReason:
    """An anchor-resolution reason under the joint vocabulary.

    The resolver only ever raises the anchor-level reasons the two sets share
    verbatim; the constraint-only spellings cannot reach here, and mapping
    them defensively to ``invalid_joint`` keeps that true by construction.
    """
    if reason in ("invalid_constraint", "unresolvable_pose"):  # pragma: no cover - defensive
        return "invalid_joint"
    return cast("JointUnresolvableReason", reason)


def _geom_limits(pair: LimitPair | None) -> Any:
    """A stored limit pair as geom's own record (``None`` stays ``None``)."""
    from hephaestus.geom import JointLimits

    if pair is None:
        return None
    return JointLimits(min=pair.min, max=pair.max)


def motion_resolution(
    layout: ProjectLayout, store: OpStore, resolver: AnchorResolver
) -> MotionResolution:
    """The current joint and pose sets resolved over ``resolver``.

    The entry point the assembly evaluator uses for pose-bound constraints
    (``KINEMATICS.md`` §3): handing over its own resolver is what makes
    "anchors resolved once" true across the two kinds of state.
    """
    joints = JointSet(layout, store)
    poses = PoseSet(layout, store, joints)
    return MotionResolution(joints.state(), poses.state(), resolver)


# --------------------------------------------------------------------------
# the evaluator


class MotionEvaluator:
    """Evaluates one project's joint and pose sets against its current builds."""

    def __init__(self, layout: ProjectLayout, store: OpStore) -> None:
        self.layout = layout
        self._store = store
        self.joints = JointSet(layout, store)
        self.poses = PoseSet(layout, store, self.joints)
        self._publisher = Publisher(layout, store)

    # -- reads --------------------------------------------------------------

    def projected(self) -> MotionStatus | None:
        """The last projected status, with its live staleness, or ``None``.

        ``None`` means *never evaluated* — which is not the same as "nothing
        to check", and readers must say so rather than print an empty table
        (the assembly precedent, verbatim).
        """
        projection = self._publisher.projections.state().motion
        if projection is None:
            return None
        blob = projection.status_blob
        if not self._store.blobs.has(blob):  # pragma: no cover - GC-linked to the state blob
            return None
        raw = json.loads(self._store.blobs.get(blob).decode("utf-8"))
        if not isinstance(raw, dict):  # pragma: no cover - our own canonical JSON
            return None
        status = MotionStatus.from_json(cast("Mapping[str, JSONValue]", raw))
        return dataclasses.replace(status, stale=tuple(projection.stale))

    def projected_ref(self) -> str | None:
        """``artifact:motion-status:sha256:…`` of the projected status, if any."""
        projection = self._publisher.projections.state().motion
        if projection is None:
            return None
        return make_artifact_ref(MOTION_ARTIFACT_KIND, projection.status_blob)

    # -- evaluation ---------------------------------------------------------

    def evaluate(self, *, record: bool = True, scratch: Path | None = None) -> MotionStatus:
        """Evaluate now, against CURRENT artifacts (§2: recomputed on demand).

        With ``record`` the status document is stored and projected
        (:class:`MotionProjection`), so a later read sees this evaluation and
        can be told when a rebuild has since invalidated it.
        """
        joint_state = self.joints.state()
        pose_state = self.poses.state()
        if scratch is not None:
            resolution, refs = self._resolve_in(joint_state, pose_state, scratch)
        else:
            self.layout.store_root.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(
                prefix="heph-motion-", dir=self.layout.store_root
            ) as tmp:
                resolution, refs = self._resolve_in(joint_state, pose_state, Path(tmp))
        status = MotionStatus(
            joint_generation=joint_state.generation,
            pose_generation=pose_state.generation,
            joints=resolution.joint_outcomes,
            poses=resolution.pose_outcomes,
            artifact_refs=refs,
        )
        if record:
            self._project(status)
        return status

    def _resolve_in(
        self, joint_state: JointState, pose_state: PoseState, scratch: Path
    ) -> tuple[MotionResolution, dict[str, str]]:
        resolver = AnchorResolver(self.layout, self._store, self._publisher, scratch)
        resolution = MotionResolution(joint_state, pose_state, resolver)
        return resolution, resolver.artifact_refs()

    # -- projection ---------------------------------------------------------

    def _project(self, status: MotionStatus) -> MotionProjection:
        """Store the status document and point the motion projection at it."""
        blob = self._store.blobs.put(canonical_json(status.to_json()).encode("utf-8"))
        projections = self._publisher.projections
        projection = MotionProjection(
            status_blob=blob,
            joint_generation=status.joint_generation,
            pose_generation=status.pose_generation,
            audit_revision=projections.state().audit_revision,
            parts=dict(status.artifact_refs),
        )
        projections.record_motion(projection)
        return projection


def check_motion(
    layout: ProjectLayout,
    store: OpStore,
    *,
    record: bool = True,
    scratch: Path | None = None,
) -> MotionStatus:
    """Evaluate ``MotionStatus`` now, against CURRENT artifacts.

    The engine-level entry point the tool surface (``check_motion``) and the
    operator CLI (``heph motion``) call — ``KINEMATICS.md`` §2/§6.
    """
    return MotionEvaluator(layout, store).evaluate(record=record, scratch=scratch)


# --------------------------------------------------------------------------
# sweeps: sampled motion checks (KINEMATICS.md §4)

SweepVerdict = Literal[
    "holds_at_samples",
    "satisfied",
    "not_reached_at_samples",
    "violated",
    "unresolvable",
]

#: THE result vocabulary, one closed set, stated once (``KINEMATICS.md`` §4).
#: The asymmetry is the honesty: universal kinds (``sweep_clearance``,
#: ``sweep_no_interference``) emit ``holds_at_samples`` on success — never
#: "holds", because one bad sample existentially falsifies them but all-good
#: samples only *evidence* — and ``violated`` on a falsifying sample. The
#: existence kind (``reach``) inverts: one achieving sample IS proof, so
#: success is ``satisfied``; failure is ``not_reached_at_samples`` (closest
#: sample and miss distance attached), never ``violated`` — a finite sample
#: not reaching is evidence, not proof of unreachability, and the name must
#: not claim more. ``unresolvable`` follows §2. For the termination reviewer
#: every non-success state is blocking alike.
SWEEP_VERDICTS: Final[tuple[SweepVerdict, ...]] = (
    "holds_at_samples",
    "satisfied",
    "not_reached_at_samples",
    "violated",
    "unresolvable",
)

SweepUnresolvableReason = Literal[
    "missing_part",
    "no_current_build",
    "missing_artifact",
    "dangling_selector",
    "ambiguous_selector",
    "unaddressable_anchor",
    "orphaned_sweep",
    "unresolvable_joint",
    "joint_limit_exceeded",
    "invalid_motion_check",
]

#: Why a motion check could not be evaluated. The first six are the 8C
#: anchor-resolution reasons verbatim (same failure, same fix, same name);
#: ``shape_refused`` is deliberately absent — clearance, interference and
#: point distance measure any resolvable geometry, so no frame class can
#: refuse them. The check-level extensions:
#:
#: * ``orphaned_sweep`` — the check sweeps a joint the set has since withdrawn
#:   (or, foreign-writer case, never carried); the detail names the joint id.
#:   The ``orphaned_pose`` rule restated: withdrawal is not a failure and the
#:   joint is never evaluated, so the fact lives with the check that still
#:   names it.
#: * ``unresolvable_joint`` — a swept joint, or a joint on an anchored part's
#:   parent chain, is itself unresolvable; the detail names it and its reason.
#: * ``joint_limit_exceeded`` — a grid sample falls outside a joint's declared
#:   limits (a range declared before the limits were tightened, or an omitted
#:   chain joint whose limits exclude zero). Geom's own spelling; an
#:   evaluation never clamps, so the samples already measured are kept and the
#:   rest are refused by name.
#: * ``invalid_motion_check`` — the stored entry cannot be evaluated as
#:   declared (the foreign-writer twin of the declaration refusals, e.g. a
#:   scalar sweep over a ``cylindrical`` joint's pair). Reported, never
#:   guessed at.
SWEEP_UNRESOLVABLE_REASONS: Final[tuple[SweepUnresolvableReason, ...]] = (
    "missing_part",
    "no_current_build",
    "missing_artifact",
    "dangling_selector",
    "ambiguous_selector",
    "unaddressable_anchor",
    "orphaned_sweep",
    "unresolvable_joint",
    "joint_limit_exceeded",
    "invalid_motion_check",
)

#: Wall-clock ceiling for ONE motion check's sweep, process-killed with no
#: retry (``KINEMATICS.md`` §4, the ``COMPARE.md`` §5 pattern applied to the
#: other unbounded kernel surface: a sweep is up to ``SWEEP_SAMPLES_MAX``
#: boolean/extrema measurements, any one of which can grind on a pathological
#: B-rep the way the 19-hour ``compare_solids`` sample did). Env-overridable
#: via :data:`MOTION_TIMEOUT_ENV`.
MOTION_TIMEOUT_S: Final[float] = 300.0

#: Environment override for :data:`MOTION_TIMEOUT_S` (seconds, float).
MOTION_TIMEOUT_ENV: Final[str] = "HEPHAESTUS_MOTION_TIMEOUT_S"


def motion_timeout_s() -> float:
    """The effective sweep ceiling: :data:`MOTION_TIMEOUT_ENV` else the default.

    Resolved per call (the :func:`~hephaestus.core.project_compare.
    compare_timeout_s` rule) so the env override applies to long-lived
    engines too, and nonsense falls back rather than crashing a check run.
    """
    raw = os.environ.get(MOTION_TIMEOUT_ENV)
    if raw is None:
        return MOTION_TIMEOUT_S
    try:
        return float(raw)
    except ValueError:
        return MOTION_TIMEOUT_S


@dataclass(frozen=True)
class SweepSample:
    """One evaluated grid sample: the parameter assignment and what it measured.

    The per-sample fact the child streams as it lands (§4 bounded execution)
    and the shape of every result's worst-sample record. ``measured`` is in
    the check kind's unit: mm for ``sweep_clearance`` and ``reach``, mm³ for
    ``sweep_no_interference``.
    """

    values: Mapping[str, float]
    measured: float

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "values": {name: self.values[name] for name in sorted(self.values)},
            "measured": self.measured,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, JSONValue]) -> SweepSample:
        raw_values = data.get("values")
        values: dict[str, float] = {}
        if isinstance(raw_values, dict):
            for name, value in cast("Mapping[str, JSONValue]", raw_values).items():
                if not isinstance(value, bool) and isinstance(value, int | float):
                    values[name] = float(value)
        measured = data.get("measured")
        if isinstance(measured, bool) or not isinstance(measured, int | float):
            raise ValidationError("sweep sample must record a measured number", kind="contract")
        return cls(values=values, measured=float(measured))


class MotionTimeout(ValidationError):
    """The sweep subprocess hit the wall-clock ceiling or died (§4).

    Not an empty-handed refusal: ``partial`` CARRIES every per-sample fact the
    child streamed before the kill, and ``samples_evaluated`` /
    ``grid_total`` say exactly how far the grid got — partial evidence, never
    a hang and never a silent pass. Deliberately NOT a :data:`SWEEP_VERDICTS`
    member: a killed sweep decided nothing, and giving the kill a verdict
    spelling would let a timeout be read as an outcome.
    """

    def __init__(
        self,
        message: str,
        *,
        check_id: str,
        timeout_s: float,
        grid_total: int,
        partial: tuple[SweepSample, ...],
    ) -> None:
        super().__init__(message, kind="contract")
        self.reason: str = "motion_timeout"
        self.check_id = check_id
        self.timeout_s = timeout_s
        self.grid_total = grid_total
        self.partial: tuple[SweepSample, ...] = partial

    @property
    def samples_evaluated(self) -> int:
        return len(self.partial)

    def to_json(self) -> dict[str, JSONValue]:
        """The refusal shape every surface carries (tool error data, CLI --json)."""
        return {
            "status": "motion_timeout",
            "reason": "motion_timeout",
            "id": self.check_id,
            "message": self.message,
            "timeout_s": self.timeout_s,
            "samples_evaluated": self.samples_evaluated,
            "grid_total": self.grid_total,
            "partial": [sample.to_json() for sample in self.partial],
        }


@dataclass(frozen=True)
class SweepResult:
    """One motion check's result: the §4 record, verdict from the closed set.

    Every result — success, failure, and unresolvable-with-partial-evidence
    alike — records ``samples_evaluated`` (the grid total on a completed run)
    and, whenever at least one sample was measured, the worst sample's
    parameter values and measured value in ``worst``. For ``reach`` the
    ``worst`` slot carries the CLOSEST sample (the §4 record: achieving
    parameters when ``satisfied`` — one sample is proof — and the closest
    sample when ``not_reached_at_samples``, with ``miss_mm`` carrying how far
    past ``tol_mm`` it stopped). The declared quantities are restated
    (``sweep``, ``samples_per_axis``, ``min_mm``/``tol_mm``/
    ``target_point_mm``) so the number can never be read without the claim it
    was measured against — the :class:`~hephaestus.geom.ConstraintResidual`
    rule.
    """

    id: str
    kind: str
    verdict: SweepVerdict
    samples_evaluated: int
    grid_total: int
    samples_per_axis: int
    #: ``{joint_id: (from, to)}`` — the declared ranges, restated.
    sweep: Mapping[str, tuple[float, float]]
    #: ``mm`` (clearance / reach distance) or ``mm3`` (interference volume).
    unit: str
    #: ``{"a": …, "b": …}`` or ``{"anchor": …}`` — resolution evidence per anchor.
    anchors: Mapping[str, AnchorRef] = field(default_factory=dict[str, AnchorRef])
    worst: SweepSample | None = None
    min_mm: float | None = None
    tol_mm: float | None = None
    target_point_mm: tuple[float, float, float] | None = None
    miss_mm: float | None = None
    reason: SweepUnresolvableReason | None = None
    detail: str | None = None
    provenance: Mapping[str, JSONValue] = field(default_factory=dict[str, "JSONValue"])
    note: str | None = None

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "id": self.id,
            "kind": self.kind,
            "verdict": self.verdict,
            "samples_evaluated": self.samples_evaluated,
            "grid_total": self.grid_total,
            "samples_per_axis": self.samples_per_axis,
            "sweep": {
                joint_id: {"from": self.sweep[joint_id][0], "to": self.sweep[joint_id][1]}
                for joint_id in sorted(self.sweep)
            },
            "unit": self.unit,
            "anchors": {
                name: cast("JSONValue", self.anchors[name].to_json())
                for name in sorted(self.anchors)
            },
            "worst": None if self.worst is None else cast("JSONValue", self.worst.to_json()),
            "min_mm": self.min_mm,
            "tol_mm": self.tol_mm,
            "target_point_mm": (
                None if self.target_point_mm is None else list(self.target_point_mm)
            ),
            "miss_mm": self.miss_mm,
            "reason": self.reason,
            "detail": self.detail,
            "provenance": cast("JSONValue", dict(self.provenance)),
            "note": self.note,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, JSONValue]) -> SweepResult:
        verdict = data.get("verdict")
        if verdict not in SWEEP_VERDICTS:
            raise ValidationError(f"invalid sweep verdict {verdict!r}", kind="contract")
        reason = data.get("reason")
        raw_sweep = data.get("sweep")
        sweep: dict[str, tuple[float, float]] = {}
        if isinstance(raw_sweep, dict):
            for joint_id, value in cast("Mapping[str, JSONValue]", raw_sweep).items():
                if isinstance(value, dict):
                    rng = cast("Mapping[str, JSONValue]", value)
                    start, stop = rng.get("from"), rng.get("to")
                    if isinstance(start, int | float) and isinstance(stop, int | float):
                        sweep[joint_id] = (float(start), float(stop))
        raw_anchors = data.get("anchors")
        anchors: dict[str, AnchorRef] = {}
        if isinstance(raw_anchors, dict):
            for name, value in cast("Mapping[str, JSONValue]", raw_anchors).items():
                anchors[name] = _anchor_ref_from_json(value)
        raw_worst = data.get("worst")
        worst = (
            SweepSample.from_json(cast("Mapping[str, JSONValue]", raw_worst))
            if isinstance(raw_worst, dict)
            else None
        )
        provenance = data.get("provenance")
        return cls(
            id=str(data.get("id", "")),
            kind=str(data.get("kind", "")),
            verdict=verdict,
            samples_evaluated=_as_int(data.get("samples_evaluated")),
            grid_total=_as_int(data.get("grid_total")),
            samples_per_axis=_as_int(data.get("samples_per_axis")),
            sweep=sweep,
            unit=str(data.get("unit", "")),
            anchors=anchors,
            worst=worst,
            min_mm=_as_opt_float(data.get("min_mm")),
            tol_mm=_as_opt_float(data.get("tol_mm")),
            target_point_mm=_as_opt_point(data.get("target_point_mm")),
            miss_mm=_as_opt_float(data.get("miss_mm")),
            reason=reason if reason in SWEEP_UNRESOLVABLE_REASONS else None,
            detail=_opt_str(data.get("detail")),
            provenance=(
                cast("Mapping[str, JSONValue]", provenance) if isinstance(provenance, dict) else {}
            ),
            note=_opt_str(data.get("note")),
        )


def _as_int(value: JSONValue | None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value


def _as_opt_float(value: JSONValue | None) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _as_opt_point(value: JSONValue | None) -> tuple[float, float, float] | None:
    if not isinstance(value, list):
        return None
    items = cast("list[JSONValue]", value)
    if len(items) != 3:
        return None
    out: list[float] = []
    for item in items:
        if isinstance(item, bool) or not isinstance(item, int | float):
            return None
        out.append(float(item))
    return (out[0], out[1], out[2])


# -- the bounded child (COMPARE.md §5 pattern, both legs) --------------------


def _sweep_child(conn: Any, spec: Mapping[str, Any]) -> None:  # pragma: no cover
    """One sweep's grid, measured where a kill cannot take the session down.

    Runs in a spawned subprocess. Message protocol, in order: zero or more
    ``("sample", (values, measured))`` — one per grid sample, streamed AS IT
    LANDS (the bench ``_score`` per-sample rule: a ceiling kill after the
    n-th send still leaves the caller holding n facts) — then exactly one of
    ``("done", None)`` or ``("refusal", (reason, detail))``. The child only
    measures; verdicts are the parent's, so a kill can never cost a decision,
    only samples.
    """
    from itertools import product

    from hephaestus.core.executor.artifact_geometry import load_brep_shape
    from hephaestus.geom import (
        IDENTITY_TRANSFORM,
        JointDeclarationError,
        JointLimitError,
        clearance,
        distance,
        forward_kinematics,
        interference,
        transformed_shape,
    )

    kind: str = spec["kind"]
    frames: Sequence[Any] = spec["frames"]
    axes: Sequence[tuple[str, Sequence[float]]] = spec["axes"]
    parts: Mapping[str, str] = spec["parts"]
    shapes: dict[str, Any] = {
        role: load_brep_shape(Path(path).read_bytes())
        for role, path in cast("Mapping[str, str]", spec["shapes"]).items()
    }
    target: Any = None
    if kind == "reach":
        from build123d import Vertex

        x, y, z = spec["target_point_mm"]
        target = Vertex(x, y, z)
    for combo in product(*[values for _, values in axes]):
        assignment = {joint_id: value for (joint_id, _), value in zip(axes, combo, strict=True)}
        try:
            world = forward_kinematics(cast("Any", frames), cast("Any", assignment))
        except JointLimitError as exc:
            conn.send(("refusal", ("joint_limit_exceeded", exc.message)))
            conn.close()
            return
        except JointDeclarationError as exc:
            conn.send(("refusal", ("invalid_motion_check", exc.message)))
            conn.close()
            return
        placed = {
            role: transformed_shape(shape, world.get(parts[role], IDENTITY_TRANSFORM))
            for role, shape in shapes.items()
        }
        if kind == "sweep_clearance":
            measured = clearance(placed["a"], placed["b"])
        elif kind == "sweep_no_interference":
            measured = interference(placed["a"], placed["b"])
        else:  # reach: distance-to-point through the existing distance primitive
            measured = distance(placed["anchor"], target)
        conn.send(("sample", (assignment, float(measured))))
    conn.send(("done", None))
    conn.close()


def _bounded_sweep(
    spec: dict[str, Any], *, check_id: str, grid_total: int, timeout_s: float
) -> tuple[tuple[SweepSample, ...], tuple[str, str] | None]:
    """Run one sweep's grid under the wall-clock ceiling (§4).

    Returns ``(samples, refusal)``: every per-sample fact that streamed in,
    and ``None`` on a completed grid or the child's named ``(reason,
    detail)`` refusal. A ceiling kill or a child death raises
    :class:`MotionTimeout` CARRYING the samples already evaluated — the
    :func:`~hephaestus.core.project_compare.bounded_solid_diff` loop with the
    bench's per-sample streaming in place of the cheap-facts-first split.
    """
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=_sweep_child, args=(child, spec))
    proc.start()
    child.close()

    samples: list[SweepSample] = []
    outcome: tuple[str, Any] | None = None
    died = False
    cut_short = f"did not finish within {timeout_s:g}s and was killed"
    deadline = time.monotonic() + timeout_s

    def _receive() -> bool:
        """Consume one message; True when it was terminal (done/refusal)."""
        nonlocal outcome
        kind, payload = parent.recv()
        if kind == "sample":
            values, measured = payload
            samples.append(
                SweepSample(values=dict(cast("Mapping[str, float]", values)), measured=measured)
            )
            return False
        outcome = (str(kind), payload)
        return True

    try:
        while outcome is None and time.monotonic() < deadline:
            try:
                if parent.poll(0.05):
                    _receive()
                elif not proc.is_alive():
                    # Death, not a deadline — drain what it sent first, so a
                    # result that raced the exit is never misread as a crash.
                    while parent.poll(0.2) and not _receive():
                        pass
                    died = outcome is None
                    break
            except EOFError:
                # The pipe closed before a terminal message: the child is
                # crashing. Let it finish dying so the refusal carries its
                # real exit code; a hang instead meets the kill in `finally`.
                proc.join(5.0)
                died = True
                break
    finally:
        if proc.is_alive():
            proc.kill()
        proc.join()
        parent.close()
    if died:
        cut_short = f"subprocess died (exit code {proc.exitcode})"

    if outcome is not None:
        kind, payload = outcome
        if kind == "done":
            return tuple(samples), None
        reason, detail = cast("tuple[str, str]", payload)
        return tuple(samples), (reason, detail)
    raise MotionTimeout(
        f"motion check {check_id}: sweep {cut_short} (KINEMATICS.md §4, ceiling "
        f"{timeout_s:g}s via {MOTION_TIMEOUT_ENV}); {len(samples)} of {grid_total} "
        "samples evaluated",
        check_id=check_id,
        timeout_s=timeout_s,
        grid_total=grid_total,
        partial=tuple(samples),
    )


# -- the sweep evaluator -----------------------------------------------------


class SweepEvaluator:
    """Evaluates declared motion checks against current builds (§4)."""

    def __init__(self, layout: ProjectLayout, store: OpStore) -> None:
        self.layout = layout
        self._store = store
        self.joints = JointSet(layout, store)
        self.poses = PoseSet(layout, store, self.joints)
        self.checks = MotionCheckSet(layout, store, self.joints)
        self._publisher = Publisher(layout, store)

    # -- reads (the projected results, never a re-measure) -------------------

    def projected_results(self) -> tuple[SweepResult, ...] | None:
        """The last FULL evaluation's per-check results, or ``None``.

        ``None`` means *checks never evaluated* — which is not the same as "no
        checks declared", and readers must say so rather than print an empty
        table (the :meth:`MotionEvaluator.projected` rule). Staleness is read
        off the shared motion projection: the projected :class:`MotionStatus`
        carries the ``stale`` part names, and the results were measured against
        the same recorded refs.
        """
        projection = self._publisher.projections.state().motion
        if projection is None or projection.results_blob is None:
            return None
        blob = projection.results_blob
        if not self._store.blobs.has(blob):  # pragma: no cover - GC-linked to the state blob
            return None
        raw = json.loads(self._store.blobs.get(blob).decode("utf-8"))
        if not isinstance(raw, dict):  # pragma: no cover - our own canonical JSON
            return None
        doc = cast("Mapping[str, JSONValue]", raw)
        items = doc.get("results")
        if not isinstance(items, list):  # pragma: no cover - our own canonical JSON
            return None
        return tuple(
            SweepResult.from_json(cast("Mapping[str, JSONValue]", item))
            for item in cast("list[JSONValue]", items)
            if isinstance(item, dict)
        )

    def projected_results_ref(self) -> str | None:
        """``artifact:motion-results:sha256:…`` of the projected results, if any."""
        projection = self._publisher.projections.state().motion
        if projection is None or projection.results_blob is None:
            return None
        return make_artifact_ref(MOTION_RESULTS_ARTIFACT_KIND, projection.results_blob)

    def projected_check_generation(self) -> int:
        """The motion-check generation the projected results were measured against."""
        projection = self._publisher.projections.state().motion
        if projection is None:
            return 0
        return projection.check_generation

    # -- evaluation ----------------------------------------------------------

    def evaluate(
        self,
        ids: Sequence[str] | None = None,
        *,
        record: bool = False,
        scratch: Path | None = None,
        timeout_s: float | None = None,
    ) -> tuple[SweepResult, ...]:
        """Every active motion check's result, in declaration order.

        ``ids`` narrows the run; an unknown id is ``addressing_error`` listing
        the declared ones, never a silently empty result. Withdrawn entries
        are never evaluated. Anchors and joint frames are resolved ONCE per
        run over one :class:`MotionResolution` (each part's artifact loaded at
        most once, the §2 rule); each check's grid then runs in its own
        killable subprocess under ``timeout_s`` (default
        :func:`motion_timeout_s`), and a ceiling kill raises
        :class:`MotionTimeout` naming the check and carrying its partial
        per-sample facts.

        With ``record`` (and only on a FULL run — a named subset is evaluated
        but deliberately never projected, the ``check_assembly`` rule: a
        projection covering some checks would report a set the project does
        not have) the results document is stored and recorded on the motion
        projection, so a later read — and the reviewer — sees this
        evaluation. Recording requires an already-projected
        :class:`MotionStatus` (``check_motion`` evaluates it first), because
        the results ride that projection's staleness.
        """
        state = self.checks.state()
        entries = _select_checks(state, ids)
        if timeout_s is None:
            timeout_s = motion_timeout_s()
        if scratch is not None:
            results, refs = self._evaluate_in(entries, scratch, timeout_s)
        else:
            self.layout.store_root.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(
                prefix="heph-sweep-", dir=self.layout.store_root
            ) as tmp:
                results, refs = self._evaluate_in(entries, Path(tmp), timeout_s)
        if record and ids is None:
            self._record(results, refs, state.generation)
        return results

    def _evaluate_in(
        self, entries: Sequence[MotionCheckEntry], scratch: Path, timeout_s: float
    ) -> tuple[tuple[SweepResult, ...], dict[str, str]]:
        resolver = AnchorResolver(self.layout, self._store, self._publisher, scratch)
        resolution = MotionResolution(self.joints.state(), self.poses.state(), resolver)
        results = tuple(
            _evaluate_check(entry, resolution, resolver, scratch=scratch, timeout_s=timeout_s)
            for entry in entries
        )
        return results, resolver.artifact_refs()

    def _record(
        self, results: tuple[SweepResult, ...], refs: Mapping[str, str], generation: int
    ) -> None:
        """Store the results document and record it on the motion projection.

        The check anchors' parts merge into the projection's ``parts`` map so a
        rebuild of a part only a sweep measures restales the projection — the
        results were measured against that geometry too. The projection's own
        ``stale`` list is preserved: recording results does not launder a
        staleness the status already declared.
        """
        projections = self._publisher.projections
        projection = projections.state().motion
        if projection is None:  # pragma: no cover - check_motion projects the status first
            raise ValidationError(
                "motion-check results cannot be recorded before a MotionStatus is projected "
                "(KINEMATICS.md §2: the results ride the motion projection's staleness)",
                kind="contract",
            )
        doc: dict[str, JSONValue] = {
            "check_generation": generation,
            "results": [result.to_json() for result in results],
        }
        blob = self._store.blobs.put(canonical_json(doc).encode("utf-8"))
        projections.record_motion(
            dataclasses.replace(
                projection,
                results_blob=blob,
                check_generation=generation,
                parts={**projection.parts, **refs},
            )
        )


def _select_checks(
    state: MotionCheckState, ids: Sequence[str] | None
) -> tuple[MotionCheckEntry, ...]:
    """The active entries to evaluate, in declaration order (the 8C rule)."""
    active = state.active
    if ids is None:
        return active
    by_id = state.by_id
    unknown = [name for name in ids if name not in by_id]
    if unknown:
        raise AddressingError(
            f"no motion check(s) {', '.join(unknown)} declared",
            selector=unknown[0],
            candidates=tuple(sorted(by_id)),
        )
    wanted = set(ids)
    return tuple(entry for entry in active if entry.id in wanted)


def _evaluate_check(
    entry: MotionCheckEntry,
    resolution: MotionResolution,
    resolver: AnchorResolver,
    *,
    scratch: Path,
    timeout_s: float,
) -> SweepResult:
    """One check: pre-resolve, run the bounded grid, decide from the samples.

    Failure precedence mirrors the joint resolver's parent-first rule: the
    swept joints are the check's subject, so an orphaned or unresolvable
    swept joint is reported before an anchor that also happens to be broken.
    """
    from hephaestus.core.executor.artifact_geometry import write_brep_shape

    anchors: dict[str, AnchorRef] = {
        name: AnchorRef(anchor=anchor.text, part=anchor.part, selector=anchor.selector)
        for name, anchor in entry.anchor_fields
    }
    # 1. Swept joints: declared, unwithdrawn, resolved (§4: ranges are claims
    #    about declared joints; withdrawal-later is the orphaned_pose rule).
    declared = resolution.joint_state.by_id
    frames: dict[str, Any] = {}
    for joint_id in sorted(entry.sweep):
        joint = declared.get(joint_id)
        if joint is None:
            return _sweep_unresolvable(
                entry,
                anchors,
                "orphaned_sweep",
                f"motion check {entry.id} sweeps joint {joint_id!r}, which is not declared",
            )
        if joint.withdrawn:
            return _sweep_unresolvable(
                entry,
                anchors,
                "orphaned_sweep",
                f"motion check {entry.id} sweeps withdrawn joint {joint_id!r} "
                f"({joint.withdrawn_reason})",
            )
        failure = resolution.joint_failure(joint_id)
        if failure is not None:
            return _sweep_unresolvable(
                entry,
                anchors,
                "unresolvable_joint",
                f"motion check {entry.id} sweeps joint {joint_id!r}, which is "
                f"unresolvable ({failure[0]}): {failure[1]}",
            )
        frames[joint_id] = resolution.frame(joint_id)
    # 2. Anchors, through the shared resolver (each part loaded once per run).
    shapes: dict[str, Any] = {}
    for name, anchor in entry.anchor_fields:
        try:
            geometry, resolved = resolver.locate(anchor.part, anchor.selector)
        except UnresolvableAnchorError as exc:
            return _sweep_unresolvable(
                entry, anchors, _sweep_reason(exc.reason), f"anchor {name}: {exc.detail}"
            )
        anchors[name] = dataclasses.replace(
            anchors[name], rule=resolved.kind, artifact_ref=geometry.artifact_ref
        )
        try:
            shapes[name] = geometry.shape_for(resolved)
        except UnresolvableAnchorError as exc:
            return _sweep_unresolvable(
                entry, anchors, _sweep_reason(exc.reason), f"anchor {name}: {exc.detail}"
            )
    # 3. Chain joints of the anchored parts: a broken joint that MOVES a
    #    measured part poisons the measurement even when it is not swept.
    parts = {name: anchor.part for name, anchor in entry.anchor_fields}
    for part in dict.fromkeys(parts.values()):
        current = part
        visited: set[str] = set()
        while True:
            chain_entry = resolution.parent_joint(current)
            if chain_entry is None or current in visited:
                break
            visited.add(current)
            failure = resolution.joint_failure(chain_entry.id)
            if failure is not None:
                return _sweep_unresolvable(
                    entry,
                    anchors,
                    "unresolvable_joint",
                    f"part {part!r} rides joint {chain_entry.id!r}, which is "
                    f"unresolvable ({failure[0]}): {failure[1]}",
                )
            frames.setdefault(chain_entry.id, resolution.frame(chain_entry.id))
            current = chain_entry.anchors[0].part
    # 4. The bounded grid (COMPARE.md §5 pattern): shapes cross as lossless
    #    BRep files, frames as plain records, and the child streams facts.
    check_dir = scratch / f"sweep-{entry.id}"
    check_dir.mkdir(parents=True, exist_ok=True)
    shape_paths: dict[str, str] = {}
    for name, shape in shapes.items():
        path = check_dir / f"{name}.brep"
        write_brep_shape(shape, path)
        shape_paths[name] = str(path)
    axes = [
        (joint_id, sweep_axis_values(rng.start, rng.stop, entry.samples))
        for joint_id, rng in sorted(entry.sweep.items())
    ]
    spec: dict[str, Any] = {
        "kind": entry.kind,
        "shapes": shape_paths,
        "parts": parts,
        "frames": tuple(frames.values()),
        "axes": axes,
        "target_point_mm": entry.target_point_mm,
    }
    samples, refusal = _bounded_sweep(
        spec, check_id=entry.id, grid_total=entry.grid_total, timeout_s=timeout_s
    )
    if refusal is not None:
        reason, detail = refusal
        return _sweep_unresolvable(
            entry,
            anchors,
            _sweep_reason(reason),
            detail,
            samples=samples,
        )
    return _decide(entry, anchors, samples)


def sweep_axis_values(start: float, stop: float, samples: int) -> list[float]:
    """``samples`` values from ``start`` to ``stop``, both endpoints EXACT (§4).

    Public because the swept-envelope publisher (``KINEMATICS.md`` §6,
    :mod:`hephaestus.core.render.posed`) must place the moving compound at
    EXACTLY the samples a sweep evaluates — two grid formulas would let an
    envelope be labeled with a sample count its geometry never visited.
    """
    step = (stop - start) / (samples - 1)
    return [start + step * i for i in range(samples - 1)] + [stop]


def _sweep_reason(reason: str) -> SweepUnresolvableReason:
    """An anchor/child reason under the sweep vocabulary (defensive twin of
    :func:`_joint_reason`: the constraint-only spellings cannot reach here)."""
    if reason in SWEEP_UNRESOLVABLE_REASONS:
        return reason
    return "invalid_motion_check"  # pragma: no cover - defensive


def _sweep_unit(kind: str) -> str:
    return "mm3" if kind == "sweep_no_interference" else "mm"


def _sweep_unresolvable(
    entry: MotionCheckEntry,
    anchors: Mapping[str, AnchorRef],
    reason: SweepUnresolvableReason,
    detail: str,
    *,
    samples: tuple[SweepSample, ...] = (),
) -> SweepResult:
    """An ``unresolvable`` result that keeps whatever evidence exists.

    ``samples`` are the per-sample facts that streamed in before the named
    refusal (a range that walks out of a joint's limits mid-grid): they are
    counted and their worst is kept — partial evidence is never discarded —
    but the verdict stays ``unresolvable``, never a pass over a partial grid.
    """
    worst, _miss = _worst_of(entry, samples)
    return SweepResult(
        id=entry.id,
        kind=entry.kind,
        verdict="unresolvable",
        samples_evaluated=len(samples),
        grid_total=entry.grid_total,
        samples_per_axis=entry.samples,
        sweep={joint_id: (rng.start, rng.stop) for joint_id, rng in entry.sweep.items()},
        unit=_sweep_unit(entry.kind),
        anchors=dict(anchors),
        worst=worst,
        min_mm=entry.min_mm,
        tol_mm=entry.tol_mm,
        target_point_mm=entry.target_point_mm,
        reason=reason,
        detail=detail,
        provenance=entry.provenance.to_json(),
        note=entry.note,
    )


def _worst_of(
    entry: MotionCheckEntry, samples: tuple[SweepSample, ...]
) -> tuple[SweepSample | None, float | None]:
    """``(worst sample, reach miss)`` per kind; first extremum wins a tie.

    "Worst" is the kind's own direction: minimum clearance, maximum
    interference volume, minimum distance to the target (for ``reach`` the
    closest sample — the achieving one when it reaches, the miss evidence
    when it does not, with the miss as ``closest - tol_mm``).
    """
    if not samples:
        return None, None
    if entry.kind == "sweep_no_interference":
        worst = max(samples, key=lambda sample: sample.measured)
        return worst, None
    worst = min(samples, key=lambda sample: sample.measured)
    if entry.kind == "reach":
        assert entry.tol_mm is not None  # required at declaration
        return worst, worst.measured - entry.tol_mm
    return worst, None


def _decide(
    entry: MotionCheckEntry,
    anchors: Mapping[str, AnchorRef],
    samples: tuple[SweepSample, ...],
) -> SweepResult:
    """The verdict, from the completed grid's facts — the §4 vocabulary exactly.

    Universal kinds: one falsifying sample is ``violated`` (existential
    falsification IS proof); a clean grid is ``holds_at_samples`` (evidence,
    and the name says so). ``reach``: one achieving sample is ``satisfied``
    (existential satisfaction IS proof, the achieving parameters in
    ``worst``); a grid that never reaches is ``not_reached_at_samples`` with
    the closest sample and its miss distance — never ``violated``.
    """
    from hephaestus.geom import INTERFERENCE_TOL_MM3

    worst, miss = _worst_of(entry, samples)
    assert worst is not None  # the grid total is >= 2 by declaration
    verdict: SweepVerdict
    miss_mm: float | None = None
    if entry.kind == "sweep_clearance":
        assert entry.min_mm is not None  # required at declaration
        verdict = "violated" if worst.measured < entry.min_mm else "holds_at_samples"
    elif entry.kind == "sweep_no_interference":
        verdict = "violated" if worst.measured > INTERFERENCE_TOL_MM3 else "holds_at_samples"
    else:  # reach
        assert entry.tol_mm is not None  # required at declaration
        if worst.measured <= entry.tol_mm:
            verdict = "satisfied"
        else:
            verdict = "not_reached_at_samples"
            miss_mm = miss
    return SweepResult(
        id=entry.id,
        kind=entry.kind,
        verdict=verdict,
        samples_evaluated=len(samples),
        grid_total=entry.grid_total,
        samples_per_axis=entry.samples,
        sweep={joint_id: (rng.start, rng.stop) for joint_id, rng in entry.sweep.items()},
        unit=_sweep_unit(entry.kind),
        anchors=dict(anchors),
        worst=worst,
        min_mm=entry.min_mm,
        tol_mm=entry.tol_mm,
        target_point_mm=entry.target_point_mm,
        miss_mm=miss_mm,
        provenance=entry.provenance.to_json(),
        note=entry.note,
    )


def evaluate_motion_checks(
    layout: ProjectLayout,
    store: OpStore,
    *,
    ids: Sequence[str] | None = None,
    scratch: Path | None = None,
    timeout_s: float | None = None,
) -> tuple[SweepResult, ...]:
    """Evaluate declared motion checks now, against CURRENT artifacts (§4).

    The engine-level entry point for the sweep half of ``check_motion`` and
    ``heph motion check`` — the sweep twin of :func:`check_motion`. Raises
    :class:`MotionTimeout` (named, partial per-sample facts attached) when a
    check's grid hits the wall-clock ceiling.
    """
    return SweepEvaluator(layout, store).evaluate(ids, scratch=scratch, timeout_s=timeout_s)


def check_motion_with_results(
    layout: ProjectLayout,
    store: OpStore,
    *,
    ids: Sequence[str] | None = None,
    record: bool = True,
    scratch: Path | None = None,
    timeout_s: float | None = None,
) -> tuple[MotionStatus, tuple[SweepResult, ...], bool]:
    """The whole ``check_motion`` measurement: status AND per-check results (§6).

    The one engine entry point the 9B ``check_motion`` tool and ``heph motion
    check`` share. Evaluates the :class:`MotionStatus` first (recording and
    projecting it on a full run, so the results have a projection to ride),
    then every selected motion check. Returns ``(status, results, partial)``
    where ``partial`` says a named subset was evaluated — a subset is never
    projected (the ``check_assembly`` rule: a projection covering some checks
    would report a set the project does not have). An unknown id is
    ``addressing_error`` naming the declared checks; a ceiling kill raises
    :class:`MotionTimeout` with its partial per-sample facts.
    """
    partial = ids is not None
    evaluator = MotionEvaluator(layout, store)
    sweeps = SweepEvaluator(layout, store)
    if scratch is not None:
        status = evaluator.evaluate(record=not partial, scratch=scratch)
        results = sweeps.evaluate(ids, record=not partial, scratch=scratch, timeout_s=timeout_s)
        return status, results, partial
    layout.store_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="heph-motion-", dir=layout.store_root) as tmp:
        status = evaluator.evaluate(record=not partial, scratch=Path(tmp))
        results = sweeps.evaluate(ids, record=not partial, scratch=Path(tmp), timeout_s=timeout_s)
    return status, results, partial


# --------------------------------------------------------------------------
# the CHECKS read surfaces over one frozen snapshot (KINEMATICS.md §4)


class _SnapshotAnchorResolver(AnchorResolver):
    """The 8C anchoring path pinned to one frozen project snapshot (§2).

    ``check_motion`` and ``heph motion`` resolve against CURRENT; inside a
    project-scope check run the rule inverts — every read must come from the
    SAME frozen snapshot the run's sources came from, never CURRENT mid-run.
    This resolver enforces that by name rather than by hope: a part outside
    the snapshot's manifest is refused ``missing_part`` (the snapshot IS the
    project this run may see), and a part whose current artifact has moved
    past the pinned ref is refused ``missing_artifact`` (the frozen build's
    addressable geometry — its §7 index, its tag placements — lives with the
    superseded publication and cannot be reconstructed, so measuring the NEW
    geometry would be exactly the CURRENT-mid-run read §2 forbids).
    :class:`SnapshotMotionContext` loads every pinned part at construction —
    while the snapshot is provably live — so a later republication cannot be
    observed through the cache.
    """

    def __init__(
        self,
        layout: ProjectLayout,
        store: OpStore,
        publisher: Publisher,
        scratch: Path,
        *,
        pinned: Mapping[str, str],
        snapshot_ref: str,
    ) -> None:
        super().__init__(layout, store, publisher, scratch)
        self._pinned = dict(pinned)
        self._snapshot_ref = snapshot_ref

    def _load_part(self, part: str) -> PartGeometry:
        pinned_ref = self._pinned.get(part)
        if pinned_ref is None:
            names = ", ".join(sorted(self._pinned)) or "none"
            raise UnresolvableAnchorError(
                "missing_part",
                f"no part {part!r} in this run's frozen project snapshot "
                f"{self._snapshot_ref} (snapshot parts: {names})",
            )
        geometry = super()._load_part(part)
        if geometry.artifact_ref != pinned_ref:
            raise UnresolvableAnchorError(
                "missing_artifact",
                f"part {part!r} was republished after this run's snapshot froze: current "
                f"artifact {geometry.artifact_ref} is not the pinned {pinned_ref}, and the "
                "frozen build's addressable geometry is no longer current — a check run "
                "never measures CURRENT mid-run (KINEMATICS.md §2)",
            )
        return geometry


@final
class _FrozenPosePlacement:
    """One pose's rigid placement over a frozen :class:`MotionResolution`.

    The engine-side implementation of the facade's ``PosedPlacement``
    protocol: ``place`` asks the frozen resolution for the part's world
    transform at this pose (exactly the joints on its parent chain, the §3
    rule) and returns a placed COPY through geom's rigid placement — the
    resolved shape is never mutated, so one loaded artifact serves many
    poses. A chain fault surfaces as the named :class:`BoundPoseError`, which
    the checks engine records as that predicate's failure.
    """

    def __init__(self, pose_id: str, resolution: MotionResolution) -> None:
        self._pose_id = pose_id
        self._resolution = resolution

    @property
    def pose_id(self) -> str:
        return self._pose_id

    def place(self, part: str, shape: object) -> object:
        from hephaestus.geom import transformed_shape

        transform = self._resolution.transforms(self._pose_id, (part,))[part]
        return transformed_shape(cast("Any", shape), transform)


@final
class SnapshotMotionContext:
    """The two §4 ``CHECKS`` read surfaces, bound to one frozen snapshot.

    ``KINEMATICS.md`` §2 (last bullet) / §4 (last bullet): inside a
    project-scope check run, ``m.at_pose`` and ``m.sweep`` must resolve
    against the SAME frozen snapshot the run's sources came from. This class
    is what the run's owner (the ``run_checks`` project scope, the bench
    grader) constructs from the snapshot ref and threads into
    :func:`~hephaestus.core.checks.engine.run_bundle` alongside the
    ``imports`` callback — :meth:`at_pose` is the posed-context factory,
    :meth:`sweep` the sweep-result resolver, :attr:`generations` the frozen
    motion generations the report records.

    Construction IS the freeze: the joint, pose, and motion-check states are
    read once, every snapshot part is loaded through the pinned resolver
    while the snapshot is provably live, and the joint forest is resolved
    eagerly (:class:`MotionResolution`'s own one-consistent-read rule) — so a
    part republished mid-run can change nothing a predicate later reads.
    Sweep grids alone run lazily, one bounded subprocess per first-asked
    check id (a run that never asks never pays), over the already-frozen
    resolver cache; results are memoized per id because one run has one
    motion state, so re-asking must restate the same facts.
    """

    def __init__(
        self,
        layout: ProjectLayout,
        store: OpStore,
        *,
        snapshot_ref: str,
        scratch: Path,
        timeout_s: float | None = None,
    ) -> None:
        self.snapshot_ref = snapshot_ref
        self._scratch = scratch
        self._timeout_s = timeout_s
        joints = JointSet(layout, store)
        poses = PoseSet(layout, store, joints)
        checks = MotionCheckSet(layout, store, joints)
        joint_state = joints.state()
        pose_state = poses.state()
        self._check_state = checks.state()
        pinned = _snapshot_parts(store, snapshot_ref)
        self._resolver = _SnapshotAnchorResolver(
            layout,
            store,
            Publisher(layout, store),
            scratch,
            pinned=pinned,
            snapshot_ref=snapshot_ref,
        )
        if joint_state.active or self._check_state.active:
            # Freeze while the snapshot is provably live. Skipped when no
            # active joint or motion check exists: nothing can ever ask the
            # resolver for geometry then, and a motion-free project must not
            # pay a second full artifact load per check run.
            for part in sorted(pinned):
                # A failed load is cached with its reason; the check that
                # touches that part gets the named refusal — never skipped,
                # and never re-read live.
                with contextlib.suppress(UnresolvableAnchorError):
                    self._resolver.locate(part, "part")
        self._resolution = MotionResolution(joint_state, pose_state, self._resolver)
        self._results: dict[str, SweepResult] = {}
        #: The frozen motion generations of this run, in the shape
        #: ``CheckReport.motion_generations`` records.
        self.generations: dict[str, int] = {
            "joints": joint_state.generation,
            "poses": pose_state.generation,
            "motion_checks": self._check_state.generation,
        }

    # -- the posed-context factory (m.at_pose) -------------------------------

    def at_pose(self, pose_id: str) -> _FrozenPosePlacement:
        """A ``PosedPlacement`` at one declared pose, or a named refusal.

        The pose is validated NOW (unknown, withdrawn, orphaned, limit- or
        joint-broken poses raise :class:`BoundPoseError` with their §2/§3
        reason at the ``m.at_pose`` call, where the predicate can be told
        which claim failed); per-part transforms are computed as the returned
        placement is asked, all from the frozen resolution.
        """
        self._resolution.transforms(pose_id, ())
        return _FrozenPosePlacement(pose_id, self._resolution)

    # -- the sweep-result resolver (m.sweep) ---------------------------------

    def sweep(self, check_id: str) -> Mapping[str, JSONValue]:
        """One declared motion check's §4 result record over the frozen state.

        An unknown id is ``addressing_error`` listing the declared ones
        (never a silently empty record); a withdrawn entry is refused by name
        — withdrawal is not a failure, but reading a withdrawn check as a
        result would be. The grid runs bounded exactly as
        :class:`SweepEvaluator` runs it, and a ceiling kill raises
        :class:`MotionTimeout`, which the checks engine records as that
        check's **unverifiable** outcome, partial per-sample facts attached.
        """
        result = self._results.get(check_id)
        if result is None:
            entry = self._check_state.by_id.get(check_id)
            if entry is None:
                raise AddressingError(
                    f"no motion check {check_id!r} declared",
                    selector=check_id,
                    candidates=tuple(sorted(self._check_state.by_id)),
                )
            if entry.withdrawn:
                raise ValidationError(
                    f"motion check {check_id!r} is withdrawn ({entry.withdrawn_reason}); "
                    "a withdrawn check is never evaluated (KINEMATICS.md §4)",
                    kind="contract",
                )
            timeout = self._timeout_s if self._timeout_s is not None else motion_timeout_s()
            result = _evaluate_check(
                entry,
                self._resolution,
                self._resolver,
                scratch=self._scratch,
                timeout_s=timeout,
            )
            self._results[check_id] = result
        return result.to_json()


def _snapshot_parts(store: OpStore, snapshot_ref: str) -> dict[str, str]:
    """``{part: artifact_ref}`` pinned by one stored snapshot manifest."""
    if not snapshot_ref.startswith(PROJECT_SNAPSHOT_REF_PREFIX):
        raise ValidationError(f"{snapshot_ref!r} is not a project-snapshot ref", kind="contract")
    blob = blob_hash_of_ref(snapshot_ref)
    if not store.blobs.has(blob):
        raise ValidationError(
            f"project snapshot {snapshot_ref} is not durably stored", kind="contract"
        )
    raw = cast("JSONValue", json.loads(store.blobs.get(blob).decode("utf-8")))
    parts_raw = cast("Mapping[str, JSONValue]", raw).get("parts") if isinstance(raw, dict) else None
    if not isinstance(parts_raw, dict):
        raise ValidationError(
            f"project snapshot {snapshot_ref} is malformed: no parts table", kind="contract"
        )
    pinned: dict[str, str] = {}
    for name, entry in cast("Mapping[str, JSONValue]", parts_raw).items():
        if not isinstance(entry, dict):
            continue
        ref = cast("Mapping[str, JSONValue]", entry).get("artifact_ref")
        if isinstance(ref, str):
            pinned[name] = ref
    return pinned
