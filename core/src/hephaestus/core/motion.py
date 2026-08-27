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

**No solver, no verdict.** Nothing here moves authored geometry (a transform
exists only inside an evaluation, ``KINEMATICS.md`` §0) and nothing here
decides what an unresolvable joint *means* at termination review — that is the
``VALIDATION.md`` §5 rule, extended to motion by the 9B amendment;
:meth:`MotionStatus.blocking` only says which ids the rule would name.
"""

from __future__ import annotations

import dataclasses
import json
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Literal, cast

from hephaestus.core.assembly import (
    AnchorRef,
    AnchorResolver,
    UnresolvableAnchorError,
    UnresolvableReason,
)
from hephaestus.core.errors import ValidationError
from hephaestus.core.project_store.constraints import Anchor
from hephaestus.core.project_store.kinematics import (
    JointEntry,
    JointSet,
    JointState,
    LimitPair,
    PoseEntry,
    PoseSet,
    PoseState,
)
from hephaestus.core.project_store.layout import ProjectLayout
from hephaestus.core.project_store.projections import MotionProjection
from hephaestus.core.project_store.publication import Publisher
from hephaestus.core.project_store.store import artifact_ref as make_artifact_ref
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
    "POSE_UNRESOLVABLE_REASONS",
    "BoundPoseError",
    "JointOutcome",
    "MotionEvaluator",
    "MotionOutcomeState",
    "MotionResolution",
    "MotionStatus",
    "PoseOutcome",
    "check_motion",
    "motion_resolution",
]

#: Artifact kind of a stored (projected) motion-status document.
MOTION_ARTIFACT_KIND: Final[str] = "motion-status"

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
