# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
# ^ OCP/build123d bindings are untyped at the member level. The relaxation is
#   pinned per-file so it stays scoped to the modules that touch the kernel
#   bindings (same convention as ``geom.measure`` / ``geom.constraints``).
"""Forward kinematics: declared joint values to rigid transforms, as facts.

``KINEMATICS.md`` §2, first bullet. The ninth geom service and, like its eight
siblings, pure functions over frames and shapes the caller already holds: no
executor, no store, no project, no knowledge of where a joint frame came from.
The engine (``hephaestus.core.motion``) resolves ``part[:selector]`` anchors
into the frames this module consumes and owns the outcome vocabulary
(``resolved | unresolvable(reason)``); this module answers exactly one
question — *where does each part sit at this parameter assignment?* — and
applies the answer to shapes for measurement.

**Posed evaluation, not a solver** (``KINEMATICS.md`` §0). Nothing here moves
what a script authored: a transform exists only in the caller's hands, and
:func:`transformed_shape` returns a *placed copy* via OCP's rigid placement
(``gp_Trsf`` wrapped in a ``TopLoc_Location``) — no tessellation, no boolean,
and never a mutation of the input shape.

The forest and its evaluation
-----------------------------
A :class:`JointFrame` carries what §1 resolution produces: the kind, the
**parent** anchor's frame (axis point and direction in as-built world mm —
the parent-frame rule; the child anchor never defines the frame), and the
declared limits. :func:`forward_kinematics` takes a forest of frames plus a
parameter assignment ``{joint_id: value}`` and returns one
:class:`RigidTransform` per part, composed root-to-leaf: a child's world
transform is its parent part's world transform following the joint's own
local transform, so a moved parent carries its children's axes with it.
Parts in no joint entry are simply absent — static, as today.

Kinds are the closed Stage 9 set (``KINEMATICS.md`` §1): ``fixed`` (0 DOF,
takes no value), ``revolute`` (degrees about the parent axis), ``prismatic``
(mm along the parent direction), ``cylindrical`` (a ``(degrees, mm)`` pair on
one axis, two limit pairs). ``zero: "as_built"`` is the only 9A reference
configuration, which is why frames are stated in as-built world coordinates
and an omitted joint evaluates at zero.

Out of limits is a refusal, never a clamp
-----------------------------------------
A parameter outside its declared limits raises :class:`JointLimitError`
(reason ``joint_limit_exceeded``) carrying the joint id, the offending value
and the limit pair it broke. Clamping would silently measure a configuration
nobody asked about — exactly the dishonesty the validation ladder exists to
prevent. A malformed forest or assignment (unknown kind, degenerate
direction, a part with two parents, a cycle, a value for a 0-DOF joint) is a
:class:`JointDeclarationError` naming its reason from
:data:`JOINT_REFUSALS` — closed sets, nothing silently skipped.

Frame comparison lives here, the verdict does not
-------------------------------------------------
:func:`frame_axis_angle_deg` and :func:`frame_radial_offset_mm` measure how
far a child anchor's frame diverges from the parent's, against the named
epsilons :data:`JOINT_FRAME_EPS_DEG` / :data:`JOINT_FRAME_EPS_MM` (the
``CONCENTRIC_AXIS_EPS_DEG`` convention). Whether a divergence beyond them is
``misaligned_joint_anchors`` is the engine's unresolvable vocabulary, not
this module's — measurement never decides anywhere else in this package.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from hephaestus.geom.metrics import AnyShape
from hephaestus.geom.topology import Vec3

__all__ = [
    "IDENTITY_TRANSFORM",
    "JOINT_DIRECTION_EPS",
    "JOINT_FRAME_EPS_DEG",
    "JOINT_FRAME_EPS_MM",
    "JOINT_KINDS",
    "JOINT_REFUSALS",
    "JointDeclarationError",
    "JointFrame",
    "JointKind",
    "JointLimitError",
    "JointLimits",
    "JointValue",
    "RigidTransform",
    "compose_transforms",
    "forward_kinematics",
    "frame_axis_angle_deg",
    "frame_radial_offset_mm",
    "joint_transform",
    "transform_point",
    "transformed_shape",
]

# --------------------------------------------------------------------------
# vocabulary

JointKind = Literal["fixed", "revolute", "prismatic", "cylindrical"]

#: The Stage 9 kind set (``KINEMATICS.md`` §1); ball, planar and gear joints
#: are deliberately absent, so this tuple is the closed vocabulary this module
#: answers for and each later kind is a contract amendment.
JOINT_KINDS: Final[tuple[JointKind, ...]] = (
    "fixed",
    "revolute",
    "prismatic",
    "cylindrical",
)

#: A parameter value: degrees (``revolute``), mm (``prismatic``), or a
#: ``(degrees, mm)`` pair (``cylindrical``). ``fixed`` takes none.
JointValue = float | tuple[float, float]

#: Named refusal reasons for a malformed forest or parameter assignment.
JOINT_REFUSALS: Final[frozenset[str]] = frozenset(
    {
        "unknown_kind",
        "degenerate_direction",
        "inverted_limits",
        "spurious_limits",
        "duplicate_joint_id",
        "multiple_parents",
        "cyclic_joint_graph",
        "unknown_joint",
        "value_for_fixed_joint",
        "scalar_value_required",
        "pair_value_required",
    }
)

# --------------------------------------------------------------------------
# named constants

#: Cap on the axis angle (deg, folded into [0, 90]) between a joint's parent
#: frame and its child anchor's own frame before the pair no longer names one
#: joint. Same magnitude and reasoning as
#: :data:`hephaestus.geom.constraints.CONCENTRIC_AXIS_EPS_DEG`: ``as_built``
#: authoring makes the two frames coaxial by discipline, so divergence is
#: kernel round-off, not a design allowance. The engine turns a breach into
#: ``misaligned_joint_anchors``; this module only measures.
JOINT_FRAME_EPS_DEG: Final[float] = 1e-3

#: Cap on the radial offset (mm) of the child anchor's axis point from the
#: parent frame's axis line, companion to :data:`JOINT_FRAME_EPS_DEG`.
JOINT_FRAME_EPS_MM: Final[float] = 1e-3

#: Directions shorter than this carry no axis and are refused
#: ``degenerate_direction`` (the :data:`hephaestus.geom.constraints.DIRECTION_EPS`
#: convention, restated here so the refusal cites a local named constant).
JOINT_DIRECTION_EPS: Final[float] = 1e-12


# --------------------------------------------------------------------------
# refusals


class JointDeclarationError(ValueError):
    """The forest or the assignment is malformed — a named refusal, not a guess.

    ``reason`` is one of :data:`JOINT_REFUSALS`; ``joint_id`` names the
    offending entry where one entry is at fault, and ``parts`` names the
    offending parts (the cycle, in walk order, for ``cyclic_joint_graph``;
    the twice-parented part for ``multiple_parents``). Whether a *well-formed*
    forest is a good one (provenance, sane travel) is the engine's question,
    not this module's.
    """

    code = "joint_declaration_error"

    def __init__(
        self,
        reason: str,
        message: str,
        *,
        joint_id: str = "",
        parts: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.joint_id = joint_id
        self.parts = parts


class JointLimitError(ValueError):
    """A parameter is outside its declared limits — refused, NEVER clamped.

    Carries the joint id, the offending value, the limit pair it broke and
    which axis of a ``cylindrical`` joint was at fault (``"rotation"`` for the
    1-DOF rotational kinds, ``"translation"`` for prismatic travel). An
    evaluation at a clamped value would be a fact about a configuration
    nobody declared, which is why this is an error and not a correction.
    """

    code = "joint_limit_exceeded"

    def __init__(
        self,
        message: str,
        *,
        joint_id: str,
        value: float,
        limit: JointLimits,
        axis: Literal["rotation", "translation"],
    ) -> None:
        super().__init__(message)
        self.reason = "joint_limit_exceeded"
        self.message = message
        self.joint_id = joint_id
        self.value = value
        self.limit = limit
        self.axis = axis


# --------------------------------------------------------------------------
# the records


@dataclass(frozen=True)
class JointLimits:
    """One declared travel window, inclusive on both ends.

    Degrees for a rotational axis, mm for a translational one — the unit is
    the joint kind's, stated in ``KINEMATICS.md`` §1, never inferred by a
    reader from the numbers.
    """

    min: float
    max: float

    def contains(self, value: float) -> bool:
        return self.min <= value <= self.max


@dataclass(frozen=True)
class JointFrame:
    """One resolved joint: what §1 anchor resolution hands forward kinematics.

    Attributes:
        id: the declared joint id (``j-elbow``).
        kind: one of :data:`JOINT_KINDS`.
        parent: the parent PART name — the frame owner. The parent anchor's
            frame IS the joint frame (``KINEMATICS.md`` §1); the child anchor
            only names what rides the joint, which is why no child frame
            appears here.
        child: the child part name — the part this joint's transform moves.
        point: a point on the joint axis, as-built world mm.
        direction: the axis direction (need not be unit length; shorter than
            :data:`JOINT_DIRECTION_EPS` is refused for the kinds that need
            one). Ignored by ``fixed``.
        limits: the rotational window (deg) for ``revolute``/``cylindrical``,
            the travel window (mm) for ``prismatic``; ``None`` is unlimited.
            ``fixed`` must declare none.
        travel_limits: the translational window (mm) of a ``cylindrical``
            joint's second DOF; refused ``spurious_limits`` on every other
            kind.
    """

    id: str
    kind: JointKind
    parent: str
    child: str
    point: Vec3
    direction: Vec3
    limits: JointLimits | None = None
    travel_limits: JointLimits | None = None


@dataclass(frozen=True)
class RigidTransform:
    """A rigid placement ``x -> R x + t`` as three rows of ``[R | t]``.

    Plain floats rather than a kernel handle, so a transform can be asserted
    against a hand-computed matrix, serialized, and compared across processes
    without OCP in the loop; :func:`transformed_shape` converts to ``gp_Trsf``
    only at the moment a shape is placed.
    """

    rows: tuple[
        tuple[float, float, float, float],
        tuple[float, float, float, float],
        tuple[float, float, float, float],
    ]


#: The identity placement: every root part's world transform, and every
#: joint's transform at its zero value.
IDENTITY_TRANSFORM: Final[RigidTransform] = RigidTransform(
    rows=(
        (1.0, 0.0, 0.0, 0.0),
        (0.0, 1.0, 0.0, 0.0),
        (0.0, 0.0, 1.0, 0.0),
    )
)


# --------------------------------------------------------------------------
# small vector helpers (world mm, right-handed, +Z up)


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _scale(a: Vec3, k: float) -> Vec3:
    return (a[0] * k, a[1] * k, a[2] * k)


def _norm(a: Vec3) -> float:
    return math.sqrt(_dot(a, a))


def _unit(direction: Vec3, *, joint_id: str) -> Vec3:
    length = _norm(direction)
    if length <= JOINT_DIRECTION_EPS:
        raise JointDeclarationError(
            "degenerate_direction",
            f"{joint_id!r}: direction {direction!r} is shorter than "
            f"JOINT_DIRECTION_EPS, so it names no axis",
            joint_id=joint_id,
        )
    return _scale(direction, 1.0 / length)


# --------------------------------------------------------------------------
# transforms


def compose_transforms(outer: RigidTransform, inner: RigidTransform) -> RigidTransform:
    """``outer`` after ``inner``: the map ``x -> outer(inner(x))``.

    Root-to-leaf composition uses exactly this orientation: a child part's
    world transform is ``compose_transforms(parent_world, joint_local)``, so
    the joint's as-built axis is carried into the parent's current pose.
    """
    a = outer.rows
    b = inner.rows
    out: list[tuple[float, float, float, float]] = []
    for i in range(3):
        row = tuple(a[i][0] * b[0][j] + a[i][1] * b[1][j] + a[i][2] * b[2][j] for j in range(3))
        t = a[i][0] * b[0][3] + a[i][1] * b[1][3] + a[i][2] * b[2][3] + a[i][3]
        out.append((row[0], row[1], row[2], t))
    return RigidTransform(rows=(out[0], out[1], out[2]))


def transform_point(transform: RigidTransform, point: Vec3) -> Vec3:
    """``point`` under ``transform``, in world mm."""
    r = transform.rows
    return (
        r[0][0] * point[0] + r[0][1] * point[1] + r[0][2] * point[2] + r[0][3],
        r[1][0] * point[0] + r[1][1] * point[1] + r[1][2] * point[2] + r[1][3],
        r[2][0] * point[0] + r[2][1] * point[1] + r[2][2] * point[2] + r[2][3],
    )


def _rotation_about(point: Vec3, direction: Vec3, angle_deg: float) -> RigidTransform:
    """Rodrigues rotation by ``angle_deg`` about the line through ``point``."""
    theta = math.radians(angle_deg)
    c = math.cos(theta)
    s = math.sin(theta)
    dx, dy, dz = direction
    rot = (
        (c + (1.0 - c) * dx * dx, (1.0 - c) * dx * dy - s * dz, (1.0 - c) * dx * dz + s * dy),
        ((1.0 - c) * dy * dx + s * dz, c + (1.0 - c) * dy * dy, (1.0 - c) * dy * dz - s * dx),
        ((1.0 - c) * dz * dx - s * dy, (1.0 - c) * dz * dy + s * dx, c + (1.0 - c) * dz * dz),
    )
    # A rotation about an off-origin axis translates by ``p - R p``.
    rp = (
        rot[0][0] * point[0] + rot[0][1] * point[1] + rot[0][2] * point[2],
        rot[1][0] * point[0] + rot[1][1] * point[1] + rot[1][2] * point[2],
        rot[2][0] * point[0] + rot[2][1] * point[1] + rot[2][2] * point[2],
    )
    t = _sub(point, rp)
    return RigidTransform(
        rows=(
            (rot[0][0], rot[0][1], rot[0][2], t[0]),
            (rot[1][0], rot[1][1], rot[1][2], t[1]),
            (rot[2][0], rot[2][1], rot[2][2], t[2]),
        )
    )


def _translation_along(direction: Vec3, travel_mm: float) -> RigidTransform:
    t = _scale(direction, travel_mm)
    return RigidTransform(
        rows=(
            (1.0, 0.0, 0.0, t[0]),
            (0.0, 1.0, 0.0, t[1]),
            (0.0, 0.0, 1.0, t[2]),
        )
    )


def _check_limit(
    joint: JointFrame,
    value: float,
    limit: JointLimits | None,
    axis: Literal["rotation", "translation"],
) -> None:
    if limit is not None and not limit.contains(value):
        unit = "deg" if axis == "rotation" else "mm"
        raise JointLimitError(
            f"joint {joint.id!r}: {axis} value {value} {unit} is outside "
            f"[{limit.min}, {limit.max}] — refused, not clamped",
            joint_id=joint.id,
            value=value,
            limit=limit,
            axis=axis,
        )


def _scalar_value(joint: JointFrame, value: JointValue) -> float:
    if isinstance(value, tuple):
        raise JointDeclarationError(
            "scalar_value_required",
            f"joint {joint.id!r} ({joint.kind}) takes one scalar value, got a pair",
            joint_id=joint.id,
        )
    return float(value)


def joint_transform(joint: JointFrame, value: JointValue | None) -> RigidTransform:
    """The joint's own local transform at ``value`` (``None`` means zero).

    ``fixed`` refuses any value (0 DOF); ``revolute`` takes degrees,
    ``prismatic`` mm, ``cylindrical`` a ``(degrees, mm)`` pair — a scalar for
    a pair kind or vice versa is refused by name, and every value is checked
    against the declared limits *including the implied zero* of an omitted
    joint: a window that excludes zero cannot be silently evaluated at it.
    """
    _validate_frame(joint)
    if joint.kind == "fixed":
        if value is not None:
            raise JointDeclarationError(
                "value_for_fixed_joint",
                f"joint {joint.id!r} is fixed (0 DOF) and takes no parameter",
                joint_id=joint.id,
            )
        return IDENTITY_TRANSFORM
    direction = _unit(joint.direction, joint_id=joint.id)
    if joint.kind == "revolute":
        angle = _scalar_value(joint, value) if value is not None else 0.0
        _check_limit(joint, angle, joint.limits, "rotation")
        return _rotation_about(joint.point, direction, angle)
    if joint.kind == "prismatic":
        travel = _scalar_value(joint, value) if value is not None else 0.0
        _check_limit(joint, travel, joint.limits, "translation")
        return _translation_along(direction, travel)
    # cylindrical
    if value is None:
        angle, travel = 0.0, 0.0
    elif isinstance(value, tuple):
        angle, travel = float(value[0]), float(value[1])
    else:
        raise JointDeclarationError(
            "pair_value_required",
            f"joint {joint.id!r} (cylindrical) takes a (degrees, mm) pair, got a scalar",
            joint_id=joint.id,
        )
    _check_limit(joint, angle, joint.limits, "rotation")
    _check_limit(joint, travel, joint.travel_limits, "translation")
    # Translation along the rotation axis commutes with the rotation, so the
    # composition order is not a modeling choice.
    return compose_transforms(
        _translation_along(direction, travel),
        _rotation_about(joint.point, direction, angle),
    )


# --------------------------------------------------------------------------
# forest validation and forward kinematics


def _validate_frame(joint: JointFrame) -> None:
    if joint.kind not in JOINT_KINDS:
        raise JointDeclarationError(
            "unknown_kind",
            f"joint {joint.id!r}: unknown kind {joint.kind!r}; known: {', '.join(JOINT_KINDS)}",
            joint_id=joint.id,
        )
    for limits, axis in ((joint.limits, "rotation"), (joint.travel_limits, "translation")):
        if limits is not None and limits.min > limits.max:
            raise JointDeclarationError(
                "inverted_limits",
                f"joint {joint.id!r}: {axis} limits [{limits.min}, {limits.max}] "
                "have min above max",
                joint_id=joint.id,
            )
    if joint.kind == "fixed" and (joint.limits is not None or joint.travel_limits is not None):
        raise JointDeclarationError(
            "spurious_limits",
            f"joint {joint.id!r} is fixed (0 DOF) and can declare no limits",
            joint_id=joint.id,
        )
    if joint.kind in ("revolute", "prismatic") and joint.travel_limits is not None:
        raise JointDeclarationError(
            "spurious_limits",
            f"joint {joint.id!r} ({joint.kind}) has one DOF; "
            "travel_limits belongs to cylindrical only",
            joint_id=joint.id,
        )


def _parent_map(joints: Sequence[JointFrame]) -> dict[str, JointFrame]:
    """``{child part: its joint}`` with the forest shape refusals applied."""
    seen_ids: set[str] = set()
    by_child: dict[str, JointFrame] = {}
    for joint in joints:
        _validate_frame(joint)
        if joint.id in seen_ids:
            raise JointDeclarationError(
                "duplicate_joint_id",
                f"joint id {joint.id!r} appears twice in the forest",
                joint_id=joint.id,
            )
        seen_ids.add(joint.id)
        if joint.child in by_child:
            raise JointDeclarationError(
                "multiple_parents",
                f"part {joint.child!r} is the child of both "
                f"{by_child[joint.child].id!r} and {joint.id!r}; "
                "the joint graph must be a forest",
                joint_id=joint.id,
                parts=(joint.child,),
            )
        by_child[joint.child] = joint
    # Cycle detection: walk each part's ancestor chain; revisiting a part on
    # the current walk names the cycle (a self-joint is the length-1 case).
    resolved: set[str] = set()
    for start in sorted(by_child):
        path: list[str] = []
        on_path: set[str] = set()
        part = start
        while part in by_child and part not in resolved:
            if part in on_path:
                cycle = (*path[path.index(part) :], part)
                raise JointDeclarationError(
                    "cyclic_joint_graph",
                    "the joint graph is not a forest; cycle: " + " -> ".join(cycle),
                    parts=cycle,
                )
            path.append(part)
            on_path.add(part)
            part = by_child[part].parent
        resolved.update(on_path)
    return by_child


def forward_kinematics(
    joints: Sequence[JointFrame],
    values: Mapping[str, JointValue],
) -> dict[str, RigidTransform]:
    """World transform per part in the forest at the assignment ``values``.

    Root parts (parents that are nobody's child) carry
    :data:`IDENTITY_TRANSFORM`; each child carries its parent part's world
    transform composed with its joint's local transform at the assigned value
    (zero when omitted — ``KINEMATICS.md`` §3). Parts named by no joint are
    static and simply absent from the result. A value naming a joint id not
    in the forest is refused ``unknown_joint``, never ignored: an assignment
    that cannot bind would otherwise silently evaluate a different
    configuration than the caller declared.

    Deterministic: the result maps part names in sorted order, and every
    number is plain float arithmetic over the declared frames.
    """
    by_child = _parent_map(joints)
    by_id = {joint.id: joint for joint in joints}
    unknown = sorted(set(values) - set(by_id))
    if unknown:
        raise JointDeclarationError(
            "unknown_joint",
            "assignment names joint id(s) not in the forest: " + ", ".join(unknown),
            joint_id=unknown[0],
        )
    local = {joint.id: joint_transform(joint, values.get(joint.id)) for joint in joints}

    world: dict[str, RigidTransform] = {}

    def _world_of(part: str) -> RigidTransform:
        cached = world.get(part)
        if cached is not None:
            return cached
        joint = by_child.get(part)
        placed = (
            IDENTITY_TRANSFORM
            if joint is None
            else compose_transforms(_world_of(joint.parent), local[joint.id])
        )
        world[part] = placed
        return placed

    parts = sorted({joint.parent for joint in joints} | set(by_child))
    return {part: _world_of(part) for part in parts}


# --------------------------------------------------------------------------
# applying a transform to a shape, and frame comparison


def transformed_shape(shape: AnyShape, transform: RigidTransform) -> AnyShape:
    """A *placed copy* of ``shape`` under ``transform`` — the input is untouched.

    OCP rigid placement only: the rows become a ``gp_Trsf`` wrapped in a
    ``TopLoc_Location`` (via build123d's ``Location``) and the shape is
    ``moved`` — no tessellation, no boolean, no rebuild, and never a mutation
    of the caller's shape, so the same artifact can be measured at many poses
    from one load.
    """
    from build123d import Location
    from OCP.gp import gp_Trsf  # pyright: ignore[reportAttributeAccessIssue]

    r = transform.rows
    trsf = gp_Trsf()
    trsf.SetValues(
        r[0][0], r[0][1], r[0][2], r[0][3],
        r[1][0], r[1][1], r[1][2], r[1][3],
        r[2][0], r[2][1], r[2][2], r[2][3],
    )  # fmt: skip
    return shape.moved(Location(trsf))


def frame_axis_angle_deg(a_direction: Vec3, b_direction: Vec3) -> float:
    """Angle (deg, folded into [0, 90]) between two frame axis *lines*.

    The number the engine compares against :data:`JOINT_FRAME_EPS_DEG` when a
    child anchor's frame is measured against the parent's. Folded, because an
    anti-parallel authored axis is the same line; degenerate input is the
    same named refusal as everywhere else in this module.
    """
    a = _unit(a_direction, joint_id="frame a")
    b = _unit(b_direction, joint_id="frame b")
    angle = math.degrees(math.acos(max(-1.0, min(1.0, _dot(a, b)))))
    return min(angle, 180.0 - angle)


def frame_radial_offset_mm(axis_point: Vec3, axis_direction: Vec3, point: Vec3) -> float:
    """Radial distance (mm) from ``point`` to the axis line through ``axis_point``.

    The companion measurement to :func:`frame_axis_angle_deg`, compared
    engine-side against :data:`JOINT_FRAME_EPS_MM`.
    """
    direction = _unit(axis_direction, joint_id="frame axis")
    offset = _sub(point, axis_point)
    along = _dot(offset, direction)
    foot = _add(axis_point, _scale(direction, along))
    return _norm(_sub(point, foot))
