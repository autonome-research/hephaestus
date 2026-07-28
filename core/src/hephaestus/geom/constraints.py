# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
# ^ OCP/build123d bindings are untyped at the member level. The relaxation is
#   pinned per-file so it stays scoped to the modules that touch the kernel
#   bindings (same convention as ``geom.measure`` / ``geom.compare``).
"""Constraint residuals: how far a declared mate is from holding, as facts.

``ASSEMBLY.md`` §2, first bullet. The eighth geom service and, like its seven
siblings, pure functions over shapes the caller already holds: no executor, no
store, no project, no knowledge of where an anchor came from. The engine
(``hephaestus.core.assembly``) resolves ``part[:selector]`` anchors through the
addressing layer and owns the verdict vocabulary
(``satisfied | violated | unresolvable``); this module answers exactly one
question per kind — *what does the geometry measure?* — and restates the
caller's own declared numbers next to it.

**NO SOLVER** (``ASSEMBLY.md`` §1, last bullet). Nothing here moves geometry.
A constraint that would need motion to hold simply measures as unsatisfied.

One record and eight evaluators
-------------------------------
Every evaluator returns a :class:`ConstraintResidual` carrying the measured
quantity, its unit, the signed :attr:`~ConstraintResidual.slack` (margin in the
measured domain: ``>= 0`` when the declared allowance is met), the declared
bounds it was compared against, secondary measured facts, and worst-point
locations where a point is meaningful:

* :func:`no_interference_residual` — overlap volume (mm³) of ``a ∩ b``, with
  the intersection's centroid as the worst point.
* :func:`clearance_min_residual` — minimum separation (mm) against a declared
  floor; closest boundary points.
* :func:`distance_residual` — raw separation (mm) against a declared value and
  tolerance; closest boundary points.
* :func:`coincident_residual` — planar faces with **opposed** normals: the
  out-of-plane gap (mm), with the normal opposition checked to a named
  epsilon.
* :func:`concentric_residual` — cylindrical faces: the radial offset (mm) of
  one axis from the other, with axis alignment checked to a named epsilon.
* :func:`parallel_residual` / :func:`perpendicular_residual` — the angle (deg)
  between the two shapes' characteristic directions.
* :func:`fit_residual` — the radial clearance (mm) of a cylindrical
  hole/shaft pair against a declared window (the fits vocabulary DFM already
  speaks); negative is an interference fit, not an error.

:func:`evaluate_residual` dispatches by kind name for callers holding a
constraint entry, and refuses a missing or unknown declared parameter by name.

Satisfaction is a restatement, not a policy
-------------------------------------------
:attr:`ConstraintResidual.satisfied` is the measured value compared with the
numbers **the caller declared** (defaults, where a bound has one, come from the
named module constants below and are recorded in
:attr:`~ConstraintResidual.declared` so a residual is always readable without
knowing this module's defaults). It is therefore a fact about arithmetic, not a
judgement about whether those numbers were the right ones to declare —
"unsatisfied means blocking" is a ``VALIDATION.md`` §5 rule and lives
engine-side, exactly as measurement never decides anywhere else in this
package.

Wrong class is a named refusal, never a number
----------------------------------------------
Asking for concentricity between two boxes, or a fit between two shafts, has no
answer — and a plausible-looking number for it would be worse than no answer.
Those raise :class:`ConstraintShapeError` (a :class:`ValueError`) whose
``reason`` is one of :data:`SHAPE_REFUSALS`, naming the offending side. A shape
whose planar/cylindrical faces do not agree on one plane or one axis is
``ambiguous_*``, not silently the largest face.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal, cast

from build123d import GeomType
from hephaestus.geom.measure import clearance as _clearance
from hephaestus.geom.measure import distance as _distance
from hephaestus.geom.measure import interference as _interference
from hephaestus.geom.metrics import AnyShape, shape_volume
from hephaestus.geom.topology import (
    CylinderRecord,
    PlanarFaceRecord,
    Vec3,
    cylindrical_faces,
    planar_faces,
)

__all__ = [
    "ANGLE_UNIT",
    "AXIS_COINCIDENT_EPS_MM",
    "COINCIDENT_NORMAL_EPS_DEG",
    "CONCENTRIC_AXIS_EPS_DEG",
    "CONSTRAINT_KINDS",
    "DIRECTION_EPS",
    "INTERFERENCE_TOL_MM3",
    "LENGTH_UNIT",
    "OPTIONAL_PARAMS",
    "PLANE_NORMAL_EPS",
    "PLANE_OFFSET_EPS_MM",
    "RADIUS_MATCH_EPS_MM",
    "REQUIRED_PARAMS",
    "SHAPE_REFUSALS",
    "VOLUME_UNIT",
    "ConstraintDeclarationError",
    "ConstraintKind",
    "ConstraintResidual",
    "ConstraintShapeError",
    "ResidualUnit",
    "clearance_min_residual",
    "coincident_residual",
    "concentric_residual",
    "distance_residual",
    "evaluate_residual",
    "fit_residual",
    "no_interference_residual",
    "parallel_residual",
    "perpendicular_residual",
]

# --------------------------------------------------------------------------
# vocabulary

ConstraintKind = Literal[
    "no_interference",
    "clearance_min",
    "distance",
    "coincident",
    "concentric",
    "parallel",
    "perpendicular",
    "fit",
]

#: The 8C kind set (``ASSEMBLY.md`` §1); each later kind is a contract
#: amendment, so this tuple is the closed vocabulary this module answers for.
CONSTRAINT_KINDS: Final[tuple[ConstraintKind, ...]] = (
    "no_interference",
    "clearance_min",
    "distance",
    "coincident",
    "concentric",
    "parallel",
    "perpendicular",
    "fit",
)

ResidualUnit = Literal["mm", "mm3", "deg"]

LENGTH_UNIT: Final[ResidualUnit] = "mm"
VOLUME_UNIT: Final[ResidualUnit] = "mm3"
ANGLE_UNIT: Final[ResidualUnit] = "deg"

#: Declared parameters each kind requires, in declaration order.
REQUIRED_PARAMS: Final[Mapping[ConstraintKind, tuple[str, ...]]] = {
    "no_interference": (),
    "clearance_min": ("value_mm",),
    "distance": ("value_mm", "tol_mm"),
    "coincident": ("tol_mm",),
    "concentric": ("tol_mm",),
    "parallel": ("tol_deg",),
    "perpendicular": ("tol_deg",),
    "fit": ("min_mm", "max_mm"),
}

#: Declared parameters each kind accepts on top of the required ones; each has
#: a default drawn from a named constant here and is always echoed back in
#: :attr:`ConstraintResidual.declared`.
OPTIONAL_PARAMS: Final[Mapping[ConstraintKind, tuple[str, ...]]] = {
    "no_interference": ("tol_mm3",),
    "clearance_min": ("tol_mm",),
    "distance": (),
    "coincident": ("normal_eps_deg",),
    "concentric": ("axis_eps_deg",),
    "parallel": (),
    "perpendicular": (),
    "fit": (),
}

#: Named refusal reasons for a shape of the wrong class for a kind.
SHAPE_REFUSALS: Final[frozenset[str]] = frozenset(
    {
        "not_solid",
        "not_planar",
        "not_cylindrical",
        "not_directional",
        "ambiguous_plane",
        "ambiguous_cylinder",
        "fit_needs_hole_and_shaft",
    }
)

# --------------------------------------------------------------------------
# named constants

#: Overlap volumes (mm³) at or below this count as boolean noise rather than
#: interference. Deliberately looser than
#: :data:`hephaestus.geom.measure.OVERLAP_EPS_MM3` (1e-9), which guards a
#: yes/no overlap test: two solids meant to touch face-to-face can leave a
#: sliver above that after a boolean, and calling a designed flush joint an
#: interference would be a false alarm. Overridable per constraint via
#: ``tol_mm3``.
INTERFERENCE_TOL_MM3: Final[float] = 1e-6

#: Default cap on how far two ``coincident`` faces' normals may be from truly
#: opposed (180°). A mate face is authored anti-parallel or it is not; this is
#: kernel round-off, not a design allowance.
COINCIDENT_NORMAL_EPS_DEG: Final[float] = 1e-3

#: Default cap on the angle between two ``concentric`` cylinder axes. Same
#: reasoning as :data:`COINCIDENT_NORMAL_EPS_DEG`: the radial offset the kind
#: reports is only meaningful for axes that are actually aligned, so a tilted
#: bore is unsatisfied rather than described by a misleading offset.
CONCENTRIC_AXIS_EPS_DEG: Final[float] = 1e-3

#: Direction cosines within this of ±1 count as (anti-)parallel when deciding
#: whether several faces of one shape agree on a plane or an axis.
PLANE_NORMAL_EPS: Final[float] = 1e-9

#: How far (mm) planar faces of one shape may sit out of a common plane, or
#: cylindrical faces off a common axis line, and still merge into one
#: reference instead of refusing ``ambiguous_*``.
PLANE_OFFSET_EPS_MM: Final[float] = 1e-9
AXIS_COINCIDENT_EPS_MM: Final[float] = 1e-9

#: How far (mm) cylindrical radii of one shape may differ and still merge.
RADIUS_MATCH_EPS_MM: Final[float] = 1e-9

#: Vectors shorter than this carry no direction (a degenerate edge, a face
#: centre exactly on its own axis).
DIRECTION_EPS: Final[float] = 1e-12


# --------------------------------------------------------------------------
# refusals


class ConstraintShapeError(ValueError):
    """A shape is the wrong class for the kind — a named refusal, not a number.

    ``reason`` is one of :data:`SHAPE_REFUSALS`; ``side`` names which anchor
    was at fault (``"a"``, ``"b"``, or ``"both"`` when the pair as a whole
    cannot play the roles the kind needs).
    """

    code = "constraint_shape_error"

    def __init__(
        self,
        reason: str,
        message: str,
        *,
        kind: str,
        side: Literal["a", "b", "both"],
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.kind = kind
        self.side = side


class ConstraintDeclarationError(ValueError):
    """A kind was dispatched with the wrong declared parameters.

    ``reason`` is ``unknown_kind``, ``missing_parameter`` or
    ``unknown_parameter``; ``params`` names every offending parameter. Whether
    a *well-formed* entry is a good one (provenance, sane numbers) is the
    engine's question, not this module's.
    """

    code = "constraint_declaration_error"

    def __init__(
        self,
        reason: str,
        message: str,
        *,
        kind: str,
        params: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.kind = kind
        self.params = params


# --------------------------------------------------------------------------
# the record


@dataclass(frozen=True)
class ConstraintResidual:
    """What the geometry measures for one constraint, next to what was declared.

    Attributes:
        kind: the 8C kind evaluated.
        measured: the kind's primary measured quantity, in :attr:`unit`.
        unit: ``mm``, ``mm3`` or ``deg`` — never inferred from the kind by a
            reader.
        slack: signed margin in the measured domain — how far *inside* the
            declared allowance the measurement sits. ``>= 0`` whenever the
            length/angle/volume bound holds; negative is the amount by which
            it is missed. Kinds with an additional class predicate
            (``coincident``'s opposed normals, ``concentric``'s axis
            alignment) can be unsatisfied with positive slack, which is why
            :attr:`satisfied` is stored rather than derived by the reader.
        satisfied: the declared numbers restated against the measurement — a
            fact about arithmetic. What to *do* about an unsatisfied
            constraint is the engine's and the reviewer's business.
        declared: every bound applied, in declaration order, including the
            defaults taken from this module's named constants.
        values: secondary measured facts (deviation, radii, angles), sorted by
            name.
        worst_points: 0, 1 or 2 locations in world mm where the measurement
            was taken — the closest-point pair, an interference centroid, the
            mating face centres. Empty when no single point is meaningful.
    """

    kind: ConstraintKind
    measured: float
    unit: ResidualUnit
    slack: float
    satisfied: bool
    declared: tuple[tuple[str, float], ...]
    values: tuple[tuple[str, float], ...]
    worst_points: tuple[Vec3, ...]


# --------------------------------------------------------------------------
# small vector helpers (world mm, right-handed, +Z up)


def _v(value: Any) -> Vec3:
    return (float(value.X), float(value.Y), float(value.Z))


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


def _unit(a: Vec3) -> Vec3 | None:
    length = _norm(a)
    if length <= DIRECTION_EPS:
        return None
    return _scale(a, 1.0 / length)


def _angle_deg(a: Vec3, b: Vec3) -> float:
    """Angle in [0, 180] between two unit-ish directions."""
    return math.degrees(math.acos(max(-1.0, min(1.0, _dot(a, b)))))


def _folded_angle_deg(a: Vec3, b: Vec3) -> float:
    """Angle in [0, 90] between two *lines* (direction sign is irrelevant)."""
    angle = _angle_deg(a, b)
    return min(angle, 180.0 - angle)


def _radial_offset(point: Vec3, axis_point: Vec3, axis_dir: Vec3) -> tuple[float, Vec3]:
    """``(distance, foot)`` from ``point`` to the line through ``axis_point``."""
    offset = _sub(point, axis_point)
    along = _dot(offset, axis_dir)
    foot = _add(axis_point, _scale(axis_dir, along))
    return _norm(_sub(point, foot)), foot


# --------------------------------------------------------------------------
# class resolution: which plane / cylinder / direction does this shape mean?


def _plane_of(shape: AnyShape, *, kind: str, side: Literal["a", "b"]) -> PlanarFaceRecord:
    """The one plane ``shape`` stands for, or a named refusal.

    Several planar faces are accepted only when they are coplanar and share an
    axis of normals (a split or trimmed mating face); the largest is returned
    as the representative, ties broken by face index so the answer never
    depends on enumeration luck.
    """
    records = planar_faces(shape)
    if not records:
        raise ConstraintShapeError(
            "not_planar",
            f"{kind}: side {side!r} has no planar face",
            kind=kind,
            side=side,
        )
    ordered = sorted(records, key=lambda r: (-r.area, r.index))
    ref = ordered[0]
    for other in ordered[1:]:
        parallel = abs(abs(_dot(other.normal, ref.normal)) - 1.0) <= PLANE_NORMAL_EPS
        coplanar = abs(_dot(_sub(other.center, ref.center), ref.normal)) <= PLANE_OFFSET_EPS_MM
        if not (parallel and coplanar):
            raise ConstraintShapeError(
                "ambiguous_plane",
                f"{kind}: side {side!r} has {len(records)} planar faces "
                "that do not lie in one plane",
                kind=kind,
                side=side,
            )
    return ref


def _cylinder_of(shape: AnyShape, *, kind: str, side: Literal["a", "b"]) -> CylinderRecord:
    """The one cylinder ``shape`` stands for, or a named refusal.

    Several cylindrical faces merge only when they share a radius and an axis
    *line* (a bore split into halves by a seam); otherwise the shape does not
    name one cylinder and the kind is refused rather than guessed.
    """
    records = cylindrical_faces(shape)
    if not records:
        raise ConstraintShapeError(
            "not_cylindrical",
            f"{kind}: side {side!r} has no cylindrical face",
            kind=kind,
            side=side,
        )
    ordered = sorted(records, key=lambda r: (-r.area, r.index))
    ref = ordered[0]
    for other in ordered[1:]:
        same_radius = abs(other.radius - ref.radius) <= RADIUS_MATCH_EPS_MM
        aligned = abs(abs(_dot(other.axis, ref.axis)) - 1.0) <= PLANE_NORMAL_EPS
        offset, _foot = _radial_offset(other.axis_point, ref.axis_point, ref.axis)
        if not (same_radius and aligned and offset <= AXIS_COINCIDENT_EPS_MM):
            raise ConstraintShapeError(
                "ambiguous_cylinder",
                f"{kind}: side {side!r} has {len(records)} cylindrical faces "
                "that do not share one axis and radius",
                kind=kind,
                side=side,
            )
    return ref


def _direction_of(shape: AnyShape, *, kind: str, side: Literal["a", "b"]) -> tuple[Vec3, str]:
    """``(direction, what)`` — the characteristic direction of ``shape``.

    Fixed, documented precedence, because "the direction of a shape" is
    otherwise a guess: a planar face means its **normal**, a cylindrical face
    its **axis**, a straight edge its **tangent**. Angular kinds compare those
    directions; a shape that is none of the three is refused
    ``not_directional`` rather than assigned an axis by convention.
    """
    if planar_faces(shape):
        return _plane_of(shape, kind=kind, side=side).normal, "plane_normal"
    if cylindrical_faces(shape):
        return _cylinder_of(shape, kind=kind, side=side).axis, "cylinder_axis"
    direction = _line_direction(shape)
    if direction is not None:
        return direction, "edge_tangent"
    raise ConstraintShapeError(
        "not_directional",
        f"{kind}: side {side!r} is neither a planar face, a cylindrical face "
        "nor a straight edge, so it has no direction",
        kind=kind,
        side=side,
    )


def _line_direction(shape: AnyShape) -> Vec3 | None:
    """The common direction of ``shape``'s straight edges, or ``None``."""
    found: Vec3 | None = None
    for edge in shape.edges():
        if edge.geom_type != GeomType.LINE:
            return None
        direction = _unit(_sub(_v(edge.end_point()), _v(edge.start_point())))
        if direction is None:
            continue
        if found is None:
            found = direction
        elif abs(abs(_dot(direction, found)) - 1.0) > PLANE_NORMAL_EPS:
            return None
    return found


def _require_solids(shape: AnyShape, *, kind: str, side: Literal["a", "b"]) -> None:
    if not shape.solids():
        raise ConstraintShapeError(
            "not_solid",
            f"{kind}: side {side!r} has no solid, so there is no volume to overlap",
            kind=kind,
            side=side,
        )


def _closest_points(a: AnyShape, b: AnyShape) -> tuple[Vec3, ...]:
    point_a, point_b = a.closest_points(b)
    return (_v(point_a), _v(point_b))


# --------------------------------------------------------------------------
# evaluators — one per 8C kind


def no_interference_residual(
    a: AnyShape,
    b: AnyShape,
    *,
    tol_mm3: float = INTERFERENCE_TOL_MM3,
) -> ConstraintResidual:
    """Overlap volume (mm³) of ``a ∩ b`` against a noise floor.

    ``measured`` is the intersection volume — 0.0 for disjoint or merely
    touching solids — and the worst point, when there is any overlap, is the
    intersection's centroid: where to look, not merely how much.
    """
    _require_solids(a, kind="no_interference", side="a")
    _require_solids(b, kind="no_interference", side="b")
    overlap = _interference(a, b)
    points: tuple[Vec3, ...] = ()
    if overlap > tol_mm3:
        points = _intersection_centroid(a, b)
    return ConstraintResidual(
        kind="no_interference",
        measured=overlap,
        unit=VOLUME_UNIT,
        slack=tol_mm3 - overlap,
        satisfied=overlap <= tol_mm3,
        declared=(("tol_mm3", tol_mm3),),
        values=(),
        worst_points=points,
    )


def _by_descending_volume(item: tuple[float, Vec3]) -> tuple[float, Vec3]:
    """Largest piece first, ties broken by position — no enumeration luck."""
    return (-item[0], item[1])


def _intersection_centroid(a: AnyShape, b: AnyShape) -> tuple[Vec3, ...]:
    """Centroid of ``a ∩ b`` as a one-point tuple, or ``()`` if unavailable."""
    from build123d.topology import Shape

    common = a.intersect(b)
    if common is None:
        return ()
    pieces: list[AnyShape] = (
        [cast(AnyShape, common)]
        if isinstance(common, Shape)
        else [cast(AnyShape, p) for p in common]
    )
    # Volume-weighted centroid, so a multi-piece interference reports one
    # honest location rather than an arbitrary piece's centre. Summed in
    # descending volume order: the same pieces always add up the same way.
    measured = [
        (shape_volume(piece), _v(cast(Any, piece).center())) for piece in pieces if piece.solids()
    ]
    total = 0.0
    weighted: Vec3 = (0.0, 0.0, 0.0)
    for volume, centre in sorted(measured, key=_by_descending_volume):
        if volume <= 0.0:
            continue
        total += volume
        weighted = _add(weighted, _scale(centre, volume))
    if total <= 0.0:
        return ()
    return (_scale(weighted, 1.0 / total),)


def clearance_min_residual(
    a: AnyShape,
    b: AnyShape,
    *,
    value_mm: float,
    tol_mm: float = 0.0,
) -> ConstraintResidual:
    """Minimum separation (mm) against a declared floor.

    ``measured`` is :func:`hephaestus.geom.measure.clearance` — 0.0 when the
    shapes touch or overlap, including strict containment — and the floor is
    ``value_mm - tol_mm``: the tolerance widens the allowance downwards, it is
    not a two-sided window (that is what ``distance`` is for). The worst points
    are the closest boundary points; when the shapes overlap, ``measured`` is
    the corrected 0.0 while those points still report the nearest *boundary*
    approach, so read them with the clearance, not instead of it.
    """
    floor = value_mm - tol_mm
    measured = _clearance(a, b)
    return ConstraintResidual(
        kind="clearance_min",
        measured=measured,
        unit=LENGTH_UNIT,
        slack=measured - floor,
        satisfied=measured >= floor,
        declared=(("value_mm", value_mm), ("tol_mm", tol_mm)),
        values=(("floor_mm", floor),),
        worst_points=_closest_points(a, b),
    )


def distance_residual(
    a: AnyShape,
    b: AnyShape,
    *,
    value_mm: float,
    tol_mm: float,
) -> ConstraintResidual:
    """Raw separation (mm) against a declared value, two-sided.

    ``measured`` is :func:`hephaestus.geom.measure.distance` (no overlap
    correction — a resolved feature pair is being placed, not checked for
    collision); ``deviation_mm`` is ``|measured - value_mm|`` and the slack is
    what is left of ``tol_mm``.
    """
    measured = _distance(a, b)
    deviation = abs(measured - value_mm)
    return ConstraintResidual(
        kind="distance",
        measured=measured,
        unit=LENGTH_UNIT,
        slack=tol_mm - deviation,
        satisfied=deviation <= tol_mm,
        declared=(("value_mm", value_mm), ("tol_mm", tol_mm)),
        values=(("deviation_mm", deviation),),
        worst_points=_closest_points(a, b),
    )


def coincident_residual(
    a: AnyShape,
    b: AnyShape,
    *,
    tol_mm: float,
    normal_eps_deg: float = COINCIDENT_NORMAL_EPS_DEG,
) -> ConstraintResidual:
    """Two planar faces flush and facing each other (``ASSEMBLY.md`` §1).

    ``measured`` is the out-of-plane gap: the distance from ``b``'s face centre
    to ``a``'s plane, which is the quantity a flush mate is authored to make
    zero. Coincidence also demands **opposed** normals — two faces of the same
    slab lying in one plane and facing the same way are not mated — so
    ``normal_deviation_deg`` (distance from a true 180°) is measured too and
    satisfaction requires both. That second predicate is why an unsatisfied
    coincidence can still carry positive slack.
    """
    plane_a = _plane_of(a, kind="coincident", side="a")
    plane_b = _plane_of(b, kind="coincident", side="b")
    gap = abs(_dot(_sub(plane_b.center, plane_a.center), plane_a.normal))
    deviation = 180.0 - _angle_deg(plane_a.normal, plane_b.normal)
    opposed = deviation <= normal_eps_deg
    return ConstraintResidual(
        kind="coincident",
        measured=gap,
        unit=LENGTH_UNIT,
        slack=tol_mm - gap,
        satisfied=gap <= tol_mm and opposed,
        declared=(("tol_mm", tol_mm), ("normal_eps_deg", normal_eps_deg)),
        values=(("normal_deviation_deg", deviation),),
        worst_points=(plane_a.center, plane_b.center),
    )


def concentric_residual(
    a: AnyShape,
    b: AnyShape,
    *,
    tol_mm: float,
    axis_eps_deg: float = CONCENTRIC_AXIS_EPS_DEG,
) -> ConstraintResidual:
    """Two cylindrical faces sharing an axis (``ASSEMBLY.md`` §1).

    ``measured`` is the radial offset of ``b``'s axis from ``a``'s axis line,
    taken at ``b``'s axis point. That number only means "concentricity" for
    axes that are actually aligned, so ``axis_angle_deg`` (between the axis
    *lines*, folded into [0, 90]) is measured too and satisfaction requires it
    within ``axis_eps_deg``: a tilted bore comes back unsatisfied rather than
    described by a flattering offset. The worst points are ``b``'s axis point
    and its foot on ``a``'s axis — the offset drawn.
    """
    cyl_a = _cylinder_of(a, kind="concentric", side="a")
    cyl_b = _cylinder_of(b, kind="concentric", side="b")
    offset, foot = _radial_offset(cyl_b.axis_point, cyl_a.axis_point, cyl_a.axis)
    angle = _folded_angle_deg(cyl_a.axis, cyl_b.axis)
    return ConstraintResidual(
        kind="concentric",
        measured=offset,
        unit=LENGTH_UNIT,
        slack=tol_mm - offset,
        satisfied=offset <= tol_mm and angle <= axis_eps_deg,
        declared=(("tol_mm", tol_mm), ("axis_eps_deg", axis_eps_deg)),
        values=(
            ("axis_angle_deg", angle),
            ("radius_a_mm", cyl_a.radius),
            ("radius_b_mm", cyl_b.radius),
        ),
        worst_points=(foot, cyl_b.axis_point),
    )


def parallel_residual(a: AnyShape, b: AnyShape, *, tol_deg: float) -> ConstraintResidual:
    """Angle (deg) between the two shapes' directions, folded into [0, 90].

    Direction is resolved by the documented precedence in
    :func:`_direction_of` (plane normal, else cylinder axis, else edge
    tangent). Folding means an anti-parallel pair reads 0: parallelism is a
    statement about lines, not arrows.
    """
    dir_a, _what_a = _direction_of(a, kind="parallel", side="a")
    dir_b, _what_b = _direction_of(b, kind="parallel", side="b")
    angle = _folded_angle_deg(dir_a, dir_b)
    return ConstraintResidual(
        kind="parallel",
        measured=angle,
        unit=ANGLE_UNIT,
        slack=tol_deg - angle,
        satisfied=angle <= tol_deg,
        declared=(("tol_deg", tol_deg),),
        values=(),
        worst_points=(),
    )


def perpendicular_residual(a: AnyShape, b: AnyShape, *, tol_deg: float) -> ConstraintResidual:
    """Deviation (deg) from square between the two shapes' directions.

    ``measured`` is ``|90 - angle|`` with the same folded angle
    :func:`parallel_residual` reports (also carried in ``angle_deg``), so the
    number is the error, and zero is square.
    """
    dir_a, _what_a = _direction_of(a, kind="perpendicular", side="a")
    dir_b, _what_b = _direction_of(b, kind="perpendicular", side="b")
    angle = _folded_angle_deg(dir_a, dir_b)
    deviation = abs(90.0 - angle)
    return ConstraintResidual(
        kind="perpendicular",
        measured=deviation,
        unit=ANGLE_UNIT,
        slack=tol_deg - deviation,
        satisfied=deviation <= tol_deg,
        declared=(("tol_deg", tol_deg),),
        values=(("angle_deg", angle),),
        worst_points=(),
    )


def fit_residual(
    a: AnyShape,
    b: AnyShape,
    *,
    min_mm: float,
    max_mm: float,
) -> ConstraintResidual:
    """Radial clearance (mm) of a cylindrical hole/shaft pair against a window.

    ``measured`` is ``hole_radius - shaft_radius``: positive is a clearance
    fit, negative an interference fit (a legitimate declared intent — press
    fits are declared with a negative window, not refused). Which side is the
    hole is read from the faces themselves — a bore's outward normal points
    towards its axis, the classification
    :class:`hephaestus.geom.topology.CylinderRecord` already carries — so a
    pair of two bores or two shafts cannot be scored and is refused
    ``fit_needs_hole_and_shaft`` instead of being ordered by radius.
    ``axis_offset_mm`` and ``axis_angle_deg`` ride along as facts: a fit window
    says nothing about whether the parts are also coaxial, and pretending
    otherwise would hide a misalignment behind a passing diameter.
    """
    cyl_a = _cylinder_of(a, kind="fit", side="a")
    cyl_b = _cylinder_of(b, kind="fit", side="b")
    if cyl_a.internal == cyl_b.internal:
        role = "bores" if cyl_a.internal else "shafts"
        raise ConstraintShapeError(
            "fit_needs_hole_and_shaft",
            f"fit: both sides are {role}; a fit needs one hole and one shaft",
            kind="fit",
            side="both",
        )
    hole, shaft = (cyl_a, cyl_b) if cyl_a.internal else (cyl_b, cyl_a)
    measured = hole.radius - shaft.radius
    offset, _foot = _radial_offset(shaft.axis_point, hole.axis_point, hole.axis)
    return ConstraintResidual(
        kind="fit",
        measured=measured,
        unit=LENGTH_UNIT,
        slack=min(measured - min_mm, max_mm - measured),
        satisfied=min_mm <= measured <= max_mm,
        declared=(("min_mm", min_mm), ("max_mm", max_mm)),
        values=(
            ("axis_angle_deg", _folded_angle_deg(hole.axis, shaft.axis)),
            ("axis_offset_mm", offset),
            ("hole_is_a", 1.0 if cyl_a.internal else 0.0),
            ("hole_radius_mm", hole.radius),
            ("shaft_radius_mm", shaft.radius),
        ),
        worst_points=(),
    )


# --------------------------------------------------------------------------
# dispatch

_EVALUATORS: Final[Mapping[ConstraintKind, Callable[..., ConstraintResidual]]] = {
    "no_interference": no_interference_residual,
    "clearance_min": clearance_min_residual,
    "distance": distance_residual,
    "coincident": coincident_residual,
    "concentric": concentric_residual,
    "parallel": parallel_residual,
    "perpendicular": perpendicular_residual,
    "fit": fit_residual,
}


def evaluate_residual(
    kind: str,
    a: AnyShape,
    b: AnyShape,
    declared: Mapping[str, float] | None = None,
) -> ConstraintResidual:
    """Evaluate one kind by name against a constraint entry's declared numbers.

    The convenience path for a caller holding an entry rather than a call site
    per kind. Unknown kinds and missing/unknown declared parameters raise
    :class:`ConstraintDeclarationError` naming them; the per-kind functions
    stay the primary API and are what the tests pin.
    """
    if kind not in CONSTRAINT_KINDS:
        raise ConstraintDeclarationError(
            "unknown_kind",
            f"unknown constraint kind {kind!r}; known: {', '.join(CONSTRAINT_KINDS)}",
            kind=kind,
        )
    known: ConstraintKind = kind  # pyright: ignore[reportAssignmentType]
    given = dict(declared or {})
    missing = tuple(name for name in REQUIRED_PARAMS[known] if name not in given)
    if missing:
        raise ConstraintDeclarationError(
            "missing_parameter",
            f"{kind}: missing declared parameter(s) {', '.join(missing)}",
            kind=kind,
            params=missing,
        )
    allowed = set(REQUIRED_PARAMS[known]) | set(OPTIONAL_PARAMS[known])
    unknown = tuple(sorted(set(given) - allowed))
    if unknown:
        raise ConstraintDeclarationError(
            "unknown_parameter",
            f"{kind}: unknown declared parameter(s) {', '.join(unknown)}",
            kind=kind,
            params=unknown,
        )
    return _EVALUATORS[known](a, b, **given)
