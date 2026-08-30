# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
# ^ OCP/build123d bindings are untyped at the member level. The relaxation is
#   pinned per-file so it stays scoped to the modules that touch the kernel
#   bindings (same convention as ``geom.measure`` / ``geom.step_io``).
"""Solid comparison: how far apart two shapes are, as facts.

``COMPARE.md`` §1. The seventh geom service and, like its six siblings, a set
of pure functions over shapes the caller already holds: no executor, no store,
no project. Two things need exactly this and nothing else — an editing loop
that wants a convergence signal ("how far is my part from the target?") and an
external benchmark scoring one STEP file against another where the engine does
not exist — so the facts are computed once, here, and the verdicts are built
elsewhere.

Four measurements and a bundle:

* :func:`volume_diff` — the boolean symmetric difference: shared volume, the
  volume unique to each side, and ``iou`` (intersection over union).
* :func:`surface_distance` — directed and symmetric **chamfer** means plus a
  **max deviation** (a Hausdorff estimate), from a deterministic parameter-grid
  sample of each face. Sample counts are part of the record so a score is never
  quietly built on a coarse grid.
* :func:`principal_alignment` — the canonical pose of one shape (centroid +
  principal axes of inertia), with the tie-breaking below.
* :func:`topology_diff` — census deltas (solid/face/edge counts, face kinds,
  ``genus``, ``is_sealed``); the cheap first look before any boolean runs.
* :func:`solid_diff` — one call, one :class:`SolidDiff` holding all of the
  above plus both bounding boxes and volumes and the alignment mode used.

**Thresholds do not live here.** "iou >= 0.99 is a pass" is a claim owned by a
``CHECKS`` predicate, a DFM rule or a bench task policy. This module measures.

Alignment is a declared choice, never a silent normalization
------------------------------------------------------------
``volume_diff``/``surface_distance``/``solid_diff`` take ``align``:

``"as_posed"``
    Compare the shapes where they sit. An editing task that must preserve pose
    wants this: a translated part *is* wrong.
``"principal"``
    Move each shape independently into its own canonical frame first (centroid
    to the origin, principal axes of inertia onto X/Y/Z) so a rigid transform
    of the same solid compares equal. A generation score that should not punish
    an arbitrary pose wants this.

The mode used is recorded on every record it affects, so a number can never be
read without knowing which question it answered.

Deterministic tie-breaking (symmetric solids)
---------------------------------------------
Principal axes are only unique when the three moments of inertia differ and
the solid is not symmetric about an axis; a cube or a cylinder has a whole
family of valid frames. No RNG resolves that here — the frame is fixed by
documented rules, in order:

1. Axes are sorted by their moment of inertia, ascending. Moments equal to
   within :data:`MOMENT_TIE_REL` (relative) count as tied, and ties are broken
   by the lexicographic order of the axis *line* — the direction signed by its
   first component above :data:`AXIS_EPS`, rounded to :data:`AXIS_DECIMALS` —
   which is sign-independent, so rule 2 cannot disturb the ordering.
2. Each axis' sign is chosen by the skew of the material along it: the
   dimensionless area-weighted third moment of the face centres, so the axis
   points towards the heavier tail. A skew of ``0`` means a mirror plane
   perpendicular to that axis and carries no sign information, so the axis with
   the **weakest** skew is not signed at all — the least reliable decision is
   the one never made.
3. That weakest axis is then *derived* as the cross product of the other two,
   which both fixes its sign and forces a right-handed frame: an alignment may
   rotate a shape, it may never mirror it.

The consequence is stated plainly rather than hidden: this makes the frame a
*function of the shape* (the same shape always yields the same frame, in this
process and the next), and it makes ``principal`` pose-invariant for solids
with distinct moments and at most one mirror plane. For a shape with tied
moments, or with two or more axes whose skew is within :data:`SKEW_EPS` of
zero, the frame is still deterministic but two rigid copies may canonicalize
into different frames — :attr:`Alignment.degenerate` says so, and a caller that
needs a verdict must decide what to do about it.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal, NoReturn, TypeAlias, TypeVar, cast

from hephaestus.core.errors import ValidationError
from hephaestus.geom.measure import OVERLAP_EPS_MM3, interference
from hephaestus.geom.metrics import AnyShape, bbox_mm, genus, is_sealed, shape_volume
from hephaestus.geom.topology import Vec3

_T = TypeVar("_T")

__all__ = [
    "AXIS_DECIMALS",
    "AXIS_EPS",
    "MAX_FACE_SAMPLES",
    "MIN_FACE_SAMPLES",
    "MOMENT_TIE_REL",
    "RIGID_EPS",
    "SAMPLES_PER_MM2",
    "SCAN_ALIGN_MODES",
    "SCAN_DIRECTION_PART_TO_SCAN",
    "SCAN_DIRECTION_SCAN_TO_PART",
    "SCAN_REFUSALS",
    "SCAN_VERTEX_SAMPLE_MAX",
    "SKEW_EPS",
    "AlignMode",
    "Alignment",
    "CompareBooleanError",
    "ScanAlignMode",
    "ScanCompareError",
    "ScanDistance",
    "ScanProgress",
    "ScanRefusalReason",
    "SolidDiff",
    "SurfaceDistance",
    "TopologyCensus",
    "TopologyDiff",
    "VolumeDiff",
    "principal_alignment",
    "refuse_scan_principal",
    "scan_distance",
    "scan_iou",
    "solid_diff",
    "surface_distance",
    "topology_diff",
    "validate_declared_transform",
    "volume_diff",
]

#: The two comparison frames (``COMPARE.md`` §1).
AlignMode: TypeAlias = Literal["as_posed", "principal"]

#: Nominal surface-sample density, samples per mm² of face area. A face gets
#: ``area * SAMPLES_PER_MM2`` samples, clamped to the two caps below: dense
#: enough that a 10 mm face is not judged by its corners, cheap enough that a
#: hundred-face part still measures in seconds.
SAMPLES_PER_MM2: Final[float] = 0.25

#: Floor on per-face samples — even a sliver face is sampled on a 2x2 grid.
MIN_FACE_SAMPLES: Final[int] = 4

#: Cap on per-face samples — a large face is sampled on a 16x16 grid and no
#: finer, so cost stays bounded and the count is reported either way.
MAX_FACE_SAMPLES: Final[int] = 256

#: Moments of inertia within this *relative* difference count as tied (see the
#: module docstring's tie-breaking rules).
MOMENT_TIE_REL: Final[float] = 1e-9

#: Decimals the axis direction is rounded to when a moment tie is broken
#: lexicographically.
AXIS_DECIMALS: Final[int] = 9

#: Direction components at or below this magnitude are treated as zero when
#: choosing an axis' sign.
AXIS_EPS: Final[float] = 1e-9

#: Dimensionless skews (third moment / bbox-diagonal³) at or below this count
#: as symmetric along that axis, i.e. as carrying no sign information.
SKEW_EPS: Final[float] = 1e-9

#: Parametric tolerance used when classifying a ``(u, v)`` sample against the
#: face's trimming wires.
_UV_CLASS_TOL: Final[float] = 1e-7


@dataclass(frozen=True)
class VolumeDiff:
    """The boolean symmetric difference of two shapes, in mm³.

    ``iou`` is ``common / (common + a_only + b_only)`` — 1.0 exactly when the
    two solids occupy the same space (and, by convention, when neither encloses
    any volume at all, since two empty regions do coincide).
    """

    common_mm3: float
    a_only_mm3: float
    b_only_mm3: float
    iou: float
    align: AlignMode


@dataclass(frozen=True)
class SurfaceDistance:
    """Chamfer means and max deviation between two shapes' surfaces, in mm.

    ``a_to_b_mean_mm`` is the mean distance from a sample of A's surface to B
    (and vice versa); ``chamfer_mm`` is their mean, the symmetric figure.
    ``max_deviation_mm`` is the largest single sampled distance in either
    direction — a Hausdorff *estimate*, bounded below by the true value because
    it is sampled. ``a_samples``/``b_samples`` are the counts behind those
    means: a number computed from four points is not the same claim as one
    computed from four thousand, and the record says which it is.
    """

    a_to_b_mean_mm: float
    b_to_a_mean_mm: float
    chamfer_mm: float
    max_deviation_mm: float
    a_samples: int
    b_samples: int
    align: AlignMode


@dataclass(frozen=True)
class Alignment:
    """A shape's canonical pose: centroid, principal axes, moments.

    ``axes`` are unit vectors ordered by ascending ``moments`` and forced
    right-handed; ``degenerate`` is True when a moment tie or a zero skew meant
    a tie-break rule had to choose, i.e. when the frame is reproducible for
    *this* shape but not necessarily shared with a rigid copy of it.
    """

    centroid: Vec3
    axes: tuple[Vec3, Vec3, Vec3]
    moments: tuple[float, float, float]
    degenerate: bool


@dataclass(frozen=True)
class TopologyCensus:
    """The counted topology of one shape (no comparison, no verdict)."""

    solids: int
    faces: int
    edges: int
    planar_faces: int
    cylindrical_faces: int
    other_faces: int
    genus: int
    sealed: bool


@dataclass(frozen=True)
class TopologyDiff:
    """Census deltas between two shapes; every delta is ``b - a``.

    ``sealed_changed`` is True when exactly one of the two shapes is sealed —
    the one topology fact that is a flag rather than a count.
    """

    a: TopologyCensus
    b: TopologyCensus
    solids_delta: int
    faces_delta: int
    edges_delta: int
    planar_faces_delta: int
    cylindrical_faces_delta: int
    other_faces_delta: int
    genus_delta: int
    sealed_changed: bool


@dataclass(frozen=True)
class SolidDiff:
    """Everything :mod:`hephaestus.geom.compare` knows about two shapes.

    The bundle ``COMPARE.md`` §1 specifies: volume, surface, topology, both
    bounding-box sizes, both volumes, and the alignment mode the volume and
    surface figures were computed in.
    """

    align: AlignMode
    volume: VolumeDiff
    surface: SurfaceDistance
    topology: TopologyDiff
    a_bbox_mm: tuple[float, float, float]
    b_bbox_mm: tuple[float, float, float]
    a_volume_mm3: float
    b_volume_mm3: float


# --------------------------------------------------------------------------
# alignment
# --------------------------------------------------------------------------


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _neg(a: Vec3) -> Vec3:
    return (-a[0], -a[1], -a[2])


def _vec(raw: Any) -> Vec3:
    """A ``gp_Vec``/``gp_Dir`` as a plain triple."""
    return (float(raw.X()), float(raw.Y()), float(raw.Z()))


def _rounded(a: Vec3) -> tuple[float, float, float]:
    return (round(a[0], AXIS_DECIMALS), round(a[1], AXIS_DECIMALS), round(a[2], AXIS_DECIMALS))


def _volume_props(shape: AnyShape) -> Any:
    from OCP.BRepGProp import BRepGProp  # pyright: ignore[reportAttributeAccessIssue]
    from OCP.GProp import GProp_GProps  # pyright: ignore[reportAttributeAccessIssue]

    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape.wrapped, props)
    return props


def _line_canonical(axis: Vec3) -> Vec3:
    """The axis *line* as a direction, signed by its first non-zero component.

    Sign-independent by construction, so it is a stable tie-break key: two
    opposite readings of the same principal axis reduce to one direction.
    """
    for component in axis:
        if abs(component) > AXIS_EPS:
            return axis if component > 0.0 else _neg(axis)
    return axis


def _skew(shape: AnyShape, centroid: Vec3, axis: Vec3, scale: float) -> float:
    """Dimensionless area-weighted third moment of face centres along ``axis``.

    The cheap, deterministic "which end is heavier" test used to fix an axis'
    sign. Face centres carry the shape's asymmetry without a second boolean,
    and the result is divided by ``scale**3`` (the bounding-box diagonal cubed)
    so :data:`SKEW_EPS` is a shape-size-independent threshold: a mirror plane
    perpendicular to the axis gives exactly zero, and "nearly zero" means
    "nearly mirror-symmetric" whatever the part is measured in.
    """
    total = 0.0
    weight = 0.0
    for face in shape.faces():
        area = float(face.area)
        if area <= 0.0:
            continue
        center = face.center()
        offset = (
            float(center.X) - centroid[0],
            float(center.Y) - centroid[1],
            float(center.Z) - centroid[2],
        )
        along = _dot(offset, axis)
        total += area * along * along * along
        weight += area
    if weight <= 0.0 or scale <= 0.0:
        return 0.0
    return total / weight / (scale * scale * scale)


def principal_alignment(shape: AnyShape) -> Alignment:
    """The canonical pose of ``shape``: centroid, principal axes, moments.

    Axes come from the volume's inertia tensor, then rules 1-3 of the module
    docstring make the frame a deterministic function of the shape. Raises
    :class:`ValueError` for a shape with no volume — there is no inertia frame
    for a face or an empty compound, and inventing one would be a verdict.
    """
    if not shape.solids() or shape_volume(shape) <= OVERLAP_EPS_MM3:
        raise ValueError("principal_alignment needs a shape with volume")

    props = _volume_props(shape)
    com = props.CentreOfMass()
    centroid: Vec3 = (float(com.X()), float(com.Y()), float(com.Z()))
    principal = props.PrincipalProperties()
    raw_moments = tuple(float(m) for m in principal.Moments())
    raw_axes = (
        principal.FirstAxisOfInertia(),
        principal.SecondAxisOfInertia(),
        principal.ThirdAxisOfInertia(),
    )

    # Rule 1: sort by moment, ascending. The key quantises the moment against
    # the largest one so "tied" is a relative test, and the tie-break is the
    # rounded axis *line* — sign-independent, so rule 2 cannot disturb it.
    moment_scale = max((abs(m) for m in raw_moments), default=1.0) or 1.0
    quantum = MOMENT_TIE_REL * moment_scale
    unordered: list[tuple[float, tuple[float, float, float], float, Vec3]] = []
    for moment, raw in zip(raw_moments, raw_axes, strict=True):
        line = _line_canonical(_vec(raw))
        unordered.append((round(moment / quantum) * quantum, _rounded(line), moment, line))
    ordered = sorted(unordered, key=lambda e: (e[0], e[1]))
    tied = any(ordered[i][0] == ordered[i + 1][0] for i in range(len(ordered) - 1))

    # Rule 2: sign each axis by the skew of the material along it. The axis
    # with the *weakest* skew is not signed at all — it is derived in rule 3,
    # so the least reliable sign decision is the one never made. (Signing a
    # mirror-symmetric axis and then deriving a well-determined one is what
    # would make two rigid copies of a symmetric part canonicalize differently.)
    size = bbox_mm(shape)
    span = math.sqrt(size[0] ** 2 + size[1] ** 2 + size[2] ** 2)
    lines = [entry[3] for entry in ordered]
    skews = [_skew(shape, centroid, line, span) for line in lines]
    symmetric = [abs(s) <= SKEW_EPS for s in skews]
    derived = min(range(3), key=lambda i: (abs(skews[i]), i))

    axes = [line if symmetric[i] or skews[i] > 0.0 else _neg(line) for i, line in enumerate(lines)]
    # Rule 3: the derived axis closes a right-handed frame (never a mirror).
    axes[derived] = _cross(axes[(derived + 1) % 3], axes[(derived + 2) % 3])

    return Alignment(
        centroid=centroid,
        axes=(axes[0], axes[1], axes[2]),
        moments=(ordered[0][2], ordered[1][2], ordered[2][2]),
        degenerate=tied or sum(symmetric) > 1,
    )


def _canonical_location(alignment: Alignment) -> Any:
    """The rigid move that takes ``alignment``'s frame to the world frame."""
    from build123d import Location
    from OCP.gp import gp_Trsf  # pyright: ignore[reportAttributeAccessIssue]

    (ax, ay, az) = alignment.axes
    c = alignment.centroid
    trsf = gp_Trsf()
    trsf.SetValues(
        ax[0], ax[1], ax[2], -_dot(ax, c),
        ay[0], ay[1], ay[2], -_dot(ay, c),
        az[0], az[1], az[2], -_dot(az, c),
    )  # fmt: skip
    return Location(trsf)


def _posed(shape: AnyShape, align: AlignMode) -> AnyShape:
    """``shape`` in the requested comparison frame (never mutated in place)."""
    if align == "as_posed":
        return shape
    return shape.moved(_canonical_location(principal_alignment(shape)))


def _aligned_pair(a: AnyShape, b: AnyShape, align: AlignMode) -> tuple[AnyShape, AnyShape]:
    return _posed(a, align), _posed(b, align)


# --------------------------------------------------------------------------
# volume
# --------------------------------------------------------------------------


class CompareBooleanError(ValueError):
    """An OCCT boolean produced a null shape, so no volume fact can be stated.

    OCCT signals a failed boolean by handing back a null ``TopoDS_Shape``
    (surfaced by build123d as ``ValueError("Null TopoDS_Shape object")`` deep
    in ``downcast``). Reporting 0.0 for that would state a fact the kernel
    never computed, so the comparison refuses with the operation named —
    the same honesty rule as ``ConstraintShapeError``. First seen on
    CADGenBench editing sample geometry (2026-07-29).
    """

    def __init__(self, op: str) -> None:
        super().__init__(f"boolean {op!r} produced a null TopoDS shape (OCCT boolean failure)")
        self.op = op


def _null_guard(op: str, fn: Callable[[], _T]) -> _T:
    """Run one boolean op, converting build123d's null-shape ValueError."""
    try:
        return fn()
    except ValueError as exc:
        if "Null TopoDS_Shape" in str(exc):
            raise CompareBooleanError(op) from exc
        raise


def _boolean_volume(result: object) -> float:
    """Volume of a boolean result, with ``measure.interference``'s guards.

    ``None`` (empty result) is 0.0; a ``ShapeList`` of pieces is their sum;
    negative numerical noise is clamped away.
    """
    from build123d.topology import Shape

    if result is None:
        return 0.0
    if isinstance(result, Shape):
        return max(0.0, shape_volume(result))
    pieces: Any = result
    return max(0.0, sum(shape_volume(piece) for piece in pieces))


def _cut_volume(a: AnyShape, b: AnyShape) -> float:
    """Volume of ``a - b`` (mm³), guarding the operand-has-no-solid cases."""
    if not a.solids():
        return 0.0
    if not b.solids():
        return max(0.0, shape_volume(a))
    return _boolean_volume(_null_guard("cut", lambda: a.cut(b)))


def volume_diff(a: AnyShape, b: AnyShape, *, align: AlignMode = "as_posed") -> VolumeDiff:
    """Boolean symmetric difference of ``a`` and ``b`` (``COMPARE.md`` §1)."""
    pa, pb = _aligned_pair(a, b, align)
    common = _null_guard("common", lambda: interference(pa, pb))
    a_only = _cut_volume(pa, pb)
    b_only = _cut_volume(pb, pa)
    union = common + a_only + b_only
    iou = 1.0 if union <= OVERLAP_EPS_MM3 else common / union
    return VolumeDiff(
        common_mm3=common,
        a_only_mm3=a_only,
        b_only_mm3=b_only,
        iou=iou,
        align=align,
    )


# --------------------------------------------------------------------------
# surface
# --------------------------------------------------------------------------


def _face_grid_steps(area: float) -> int:
    """Grid resolution for a face of ``area`` mm² (density between the caps)."""
    wanted = round(max(0.0, area) * SAMPLES_PER_MM2)
    wanted = min(MAX_FACE_SAMPLES, max(MIN_FACE_SAMPLES, wanted))
    return math.isqrt(wanted - 1) + 1  # ceil(sqrt(wanted)), wanted >= 4


def _face_samples(face: Any) -> list[Vec3]:
    """Deterministic parameter-grid samples inside one trimmed face.

    Cell centres of an ``n x n`` grid over the face's own ``(u, v)`` bounds,
    each classified against the trimming wires so a sample never lands on the
    untrimmed surface extension (which would report a deviation where there is
    no material). A face whose grid misses the trimmed region entirely — a
    sliver, a narrow annulus — falls back to its centre, so every face
    contributes at least one sample and no surface is silently skipped.
    """
    from OCP.BRepAdaptor import BRepAdaptor_Surface  # pyright: ignore[reportAttributeAccessIssue]
    from OCP.BRepTopAdaptor import (
        BRepTopAdaptor_FClass2d,  # pyright: ignore[reportAttributeAccessIssue]
    )
    from OCP.gp import gp_Pnt2d  # pyright: ignore[reportAttributeAccessIssue]
    from OCP.TopAbs import TopAbs_State  # pyright: ignore[reportAttributeAccessIssue]

    adaptor = BRepAdaptor_Surface(face.wrapped)
    u0, u1 = float(adaptor.FirstUParameter()), float(adaptor.LastUParameter())
    v0, v1 = float(adaptor.FirstVParameter()), float(adaptor.LastVParameter())
    if not all(math.isfinite(p) for p in (u0, u1, v0, v1)):
        center = face.center()
        return [(float(center.X), float(center.Y), float(center.Z))]

    steps = _face_grid_steps(float(face.area))
    classifier = BRepTopAdaptor_FClass2d(face.wrapped, _UV_CLASS_TOL)
    out: list[Vec3] = []
    for i in range(steps):
        u = u0 + (u1 - u0) * (i + 0.5) / steps
        for j in range(steps):
            v = v0 + (v1 - v0) * (j + 0.5) / steps
            state = classifier.Perform(gp_Pnt2d(u, v))
            if state == TopAbs_State.TopAbs_OUT:
                continue
            point = adaptor.Value(u, v)
            out.append((float(point.X()), float(point.Y()), float(point.Z())))
    if not out:
        center = face.center()
        out.append((float(center.X), float(center.Y), float(center.Z)))
    return out


def _surface_samples(shape: AnyShape) -> list[Vec3]:
    """Every face's grid samples, in ``faces()`` enumeration order."""
    out: list[Vec3] = []
    for face in shape.faces():
        out.extend(_face_samples(face))
    return out


def _point_distances(points: list[Vec3], target: AnyShape) -> list[float]:
    """Distance (mm) from each point to ``target``'s boundary."""
    from OCP.BRepBuilderAPI import (
        BRepBuilderAPI_MakeVertex,  # pyright: ignore[reportAttributeAccessIssue]
    )
    from OCP.BRepExtrema import (
        BRepExtrema_DistShapeShape,  # pyright: ignore[reportAttributeAccessIssue]
    )
    from OCP.gp import gp_Pnt  # pyright: ignore[reportAttributeAccessIssue]

    out: list[float] = []
    for point in points:
        vertex = BRepBuilderAPI_MakeVertex(gp_Pnt(*point)).Vertex()
        extrema = BRepExtrema_DistShapeShape(vertex, target.wrapped)
        out.append(float(extrema.Value()) if extrema.IsDone() else math.inf)
    return out


def surface_distance(
    a: AnyShape,
    b: AnyShape,
    *,
    align: AlignMode = "as_posed",
) -> SurfaceDistance:
    """Chamfer means and sampled max deviation between two surfaces (mm).

    Sampling is on the B-rep (no meshing): each face of each shape is sampled
    on its own parameter grid, at a density proportional to face area between
    :data:`MIN_FACE_SAMPLES` and :data:`MAX_FACE_SAMPLES` — no RNG, so the same
    pair of shapes yields the same numbers in every process. Both shapes must
    have faces; a shape with none yields zeros and zero counts, which the
    counts make visible.
    """
    pa, pb = _aligned_pair(a, b, align)
    a_points = _surface_samples(pa)
    b_points = _surface_samples(pb)
    if not a_points or not b_points:
        return SurfaceDistance(
            a_to_b_mean_mm=0.0,
            b_to_a_mean_mm=0.0,
            chamfer_mm=0.0,
            max_deviation_mm=0.0,
            a_samples=len(a_points),
            b_samples=len(b_points),
            align=align,
        )
    a_to_b = _point_distances(a_points, pb)
    b_to_a = _point_distances(b_points, pa)
    mean_a = sum(a_to_b) / len(a_to_b)
    mean_b = sum(b_to_a) / len(b_to_a)
    return SurfaceDistance(
        a_to_b_mean_mm=mean_a,
        b_to_a_mean_mm=mean_b,
        chamfer_mm=0.5 * (mean_a + mean_b),
        max_deviation_mm=max(max(a_to_b), max(b_to_a)),
        a_samples=len(a_points),
        b_samples=len(b_points),
        align=align,
    )


# --------------------------------------------------------------------------
# topology
# --------------------------------------------------------------------------


def _census(shape: AnyShape) -> TopologyCensus:
    from build123d import GeomType

    planar = 0
    cylindrical = 0
    other = 0
    for face in shape.faces():
        if face.geom_type == GeomType.PLANE:
            planar += 1
        elif face.geom_type == GeomType.CYLINDER:
            cylindrical += 1
        else:
            other += 1
    return TopologyCensus(
        solids=len(shape.solids()),
        faces=planar + cylindrical + other,
        edges=len(shape.edges()),
        planar_faces=planar,
        cylindrical_faces=cylindrical,
        other_faces=other,
        genus=genus(shape),
        sealed=is_sealed(shape),
    )


def topology_diff(a: AnyShape, b: AnyShape) -> TopologyDiff:
    """Census deltas between two shapes (``b - a``); no boolean is run.

    Alignment does not apply: counts and genus are pose-invariant, so there is
    no mode to declare and none is recorded.
    """
    census_a = _census(a)
    census_b = _census(b)
    return TopologyDiff(
        a=census_a,
        b=census_b,
        solids_delta=census_b.solids - census_a.solids,
        faces_delta=census_b.faces - census_a.faces,
        edges_delta=census_b.edges - census_a.edges,
        planar_faces_delta=census_b.planar_faces - census_a.planar_faces,
        cylindrical_faces_delta=census_b.cylindrical_faces - census_a.cylindrical_faces,
        other_faces_delta=census_b.other_faces - census_a.other_faces,
        genus_delta=census_b.genus - census_a.genus,
        sealed_changed=census_a.sealed != census_b.sealed,
    )


# --------------------------------------------------------------------------
# the bundle
# --------------------------------------------------------------------------


def solid_diff(a: AnyShape, b: AnyShape, *, align: AlignMode = "as_posed") -> SolidDiff:
    """Every comparison fact about ``a`` and ``b`` in one record.

    The alignment mode is applied to the volume and surface measurements and
    recorded on :attr:`SolidDiff.align`; the bounding boxes and volumes are the
    shapes' own, as posed by the caller.
    """
    return SolidDiff(
        align=align,
        volume=volume_diff(a, b, align=align),
        surface=surface_distance(a, b, align=align),
        topology=topology_diff(a, b),
        a_bbox_mm=bbox_mm(a),
        b_bbox_mm=bbox_mm(b),
        a_volume_mm3=shape_volume(a),
        b_volume_mm3=shape_volume(b),
    )


# --------------------------------------------------------------------------
# §6 — scoring against a scan target
#
# A scan is not a solid, so this is NOT ``solid_diff`` with a mesh operand: it
# is a different record type, reporting what a triangle soup can support and
# refusing by name what it cannot. ``COMPARE.md`` §1's discipline transfers
# wholesale and is not reimplemented here — sample counts ride the record,
# thresholds stay in the caller's predicate, and the alignment mode is declared
# on every number it affects.

#: The scan comparison's own refusal vocabulary (``MESH_INGEST.md`` §10). A
#: THIRD group, disjoint from ``MESH_REFUSALS`` (admission) and
#: ``MESH_OPERATION_REFUSALS`` (conversion): a comparison that cannot be made is
#: a different fact from a file that cannot be read, and a reader who greps a
#: log for one must not land in the other.
#:
#: ``declared_transform_not_rigid`` is a **tightening**: §6.5 requires a
#: declared transform to be refused when it is not rigid and does not spell the
#: code, and an unnamed refusal in a document whose whole subject is named
#: refusals would be the defect one level down.
SCAN_REFUSALS: Final[tuple[str, ...]] = (
    "scan_target_unsupported",
    "scan_principal_unavailable",
    "scan_iou_unavailable",
    "scan_neighborhood_overflow",
    "scan_timeout",
    "scan_unmeasurable",
    "declared_transform_not_rigid",
)

ScanRefusalReason = Literal[
    "scan_target_unsupported",
    "scan_principal_unavailable",
    "scan_iou_unavailable",
    "scan_neighborhood_overflow",
    "scan_timeout",
    "scan_unmeasurable",
    "declared_transform_not_rigid",
]

#: ``COMPARE.md`` §1's alignment rule with its third declared mode (§6.5).
#: ``principal`` is deliberately absent: it is refused, not defaulted away.
ScanAlignMode: TypeAlias = Literal["as_posed", "declared"]
SCAN_ALIGN_MODES: Final[tuple[str, ...]] = ("as_posed", "declared")

#: Tolerance the declared transform's rotation block is checked at (§6.5): the
#: same 1e-9 G8B already uses for record equality across processes.
RIGID_EPS: Final[float] = 1e-9

#: Ceiling on how many scan vertices direction A measures against the B-rep.
#: Above it the sample is a deterministic even stride through canonical vertex
#: order — no RNG, and ``ScanDistance.scan_samples`` reports the count, because
#: a number computed from four points is not the same claim as one computed
#: from four thousand (``compare.py`` sample-count rule, ``COMPARE.md`` §1).
SCAN_VERTEX_SAMPLE_MAX: Final[int] = 20_000


class ScanCompareError(ValidationError):
    """A scan comparison was refused; ``reason`` is from :data:`SCAN_REFUSALS`.

    Its own class rather than a widened :class:`CompareBooleanError` or a bare
    ``ValueError`` for the reason the vocabulary is a third group: "this target
    is not a scan target", "no IoU exists against a scan" and "the neighbourhood
    overflowed" are facts a caller branches on, and a comparison that returned a
    plausible number instead would be the failure this whole stage exists to
    prevent.
    """

    def __init__(self, message: str, *, reason: ScanRefusalReason) -> None:
        # Derived here, on :class:`~hephaestus.geom.mesh.MeshReadError`'s rule
        # and for its reason: a raise site that hand-wrote its own code into its
        # own prose could keep the prose and move ``reason=`` underneath it, and
        # every message-level assertion downstream would stay green while the
        # vocabulary drifted. The third repair pass found this class had the
        # attribute without the derivation, so the comparison third of §10 was
        # open drift while the admission third was closed.
        super().__init__(f"{message} [{reason}]", kind="contract")
        self.reason: ScanRefusalReason = reason


def scan_iou(target: str = "scan") -> NoReturn:
    """Always refuses ``scan_iou_unavailable`` (§6.4), citing why.

    Not an oversight and not a TODO: ``volume_diff`` needs solids on both sides,
    getting one from a scan costs a sew at 196-221 µs/tri plus two OCCT booleans
    on a 10⁵-face solid, and the sewn solid's own ``BRepCheck_Analyzer`` verdict
    is False for real scans — so the boolean's answer would be untrustworthy
    even when it returned. The field is omitted and the refusal is named.
    """
    raise ScanCompareError(
        f"no intersection-over-union exists against {target!r}. "
        "volume_diff needs a solid on both sides; a scan yields one only through a "
        "sew whose validity gate refuses most real scans, so the number would be "
        "computed from an object nobody should trust (MESH_INGEST.md §6.4)",
        reason="scan_iou_unavailable",
    )


def refuse_scan_principal(target: str) -> NoReturn:
    """Always refuses ``scan_principal_unavailable`` (§6.5), with both reasons."""
    raise ScanCompareError(
        f"align='principal' is refused against {target!r}. "
        "principal_alignment needs a shape with volume, which an unsewn scan shell "
        "and a point cloud can never satisfy — and a limb scan is always PARTIAL, so "
        "the principal axes of the sampled region are not the principal axes of the "
        "object and the mode would be a silent lie even where it ran. Alignment is "
        "'as_posed' or a declared rigid transform (MESH_INGEST.md §6.5)",
        reason="scan_principal_unavailable",
    )


def validate_declared_transform(raw: Sequence[float] | None) -> tuple[float, ...]:
    """A declared alignment as a validated row-major 4x4 (``MESH_INGEST.md`` §6.5).

    Rigid or refused: the rotation block must be orthonormal to :data:`RIGID_EPS`
    with determinant **+1** (a mirror is not a pose), and the last row must be
    ``0 0 0 1``. There is no fitted registration anywhere in this stage — no ICP
    exists in the pinned stack and none is added — so a transform is declared,
    validated and echoed on the record, or it is refused by name.
    """
    if raw is None or len(tuple(raw)) != 16:
        raise ScanCompareError(
            "align='declared' requires a row-major 4x4 "
            "transform as 16 numbers (MESH_INGEST.md §6.5)",
            reason="declared_transform_not_rigid",
        )
    values = tuple(float(value) for value in raw)
    if any(not math.isfinite(value) for value in values):
        raise ScanCompareError(
            "the declared transform carries a non-finite entry (MESH_INGEST.md §6.5)",
            reason="declared_transform_not_rigid",
        )
    rows: list[Vec3] = [
        (values[0], values[1], values[2]),
        (values[4], values[5], values[6]),
        (values[8], values[9], values[10]),
    ]
    for i in range(3):
        for j in range(3):
            expected = 1.0 if i == j else 0.0
            if abs(_dot(rows[i], rows[j]) - expected) > RIGID_EPS:
                raise ScanCompareError(
                    "the declared transform's rotation "
                    f"block is not orthonormal to {RIGID_EPS:g} (row {i} . row {j} = "
                    f"{_dot(rows[i], rows[j])!r}) (MESH_INGEST.md §6.5)",
                    reason="declared_transform_not_rigid",
                )
    det = _dot(rows[0], _cross(rows[1], rows[2]))
    if abs(det - 1.0) > RIGID_EPS:
        raise ScanCompareError(
            f"determinant {det!r} is not +1 — a rigid "
            "alignment may rotate a scan, never mirror or scale it "
            "(MESH_INGEST.md §6.5)",
            reason="declared_transform_not_rigid",
        )
    if (values[12], values[13], values[14], values[15]) != (0.0, 0.0, 0.0, 1.0):
        raise ScanCompareError(
            "the last row of a rigid 4x4 is 0 0 0 1 (MESH_INGEST.md §6.5)",
            reason="declared_transform_not_rigid",
        )
    return values


@dataclass(frozen=True)
class ScanDistance:
    """How far an authored part is from a scan, in both directions (§6.4).

    A different record type from :class:`SolidDiff`, and the fields it LACKS are
    the design:

    * **no ``iou``** — see :func:`scan_iou`;
    * **no ``chamfer_mm``** — ``SurfaceDistance.chamfer_mm`` is the mean of two
      directed means, and here one of the two directions may be an upper bound.
      Averaging an exact number with a bound produces a number with no defined
      meaning, so the two directions are reported separately, always, and any
      symmetric figure is the caller's to form from fields whose methods it can
      read.

    ``part_to_scan_mean_mm`` and ``part_to_scan_max_mm`` move together — they
    are one measurement's mean and maximum, and a record carrying one without
    the other would describe a computation that never ran — and
    ``part_to_scan_upper_bound_mm`` is the complement of both. Never two
    populated where one is exact and one a bound; never all three absent.

    Two fields beyond the §6.4 code block, both named in §6.3's own prose:
    ``part_to_scan_bias`` (``"exact"`` | ``"over"``) and
    ``part_to_scan_refusal``, which carries ``scan_neighborhood_overflow`` when
    the exact refinement was abandoned. The alternative was an abandonment
    "named" only in a method string a reader has to know how to decode.
    """

    align: ScanAlignMode
    declared_transform: tuple[float, ...] | None
    scan_to_part_mean_mm: float
    scan_to_part_max_mm: float
    #: The CLOSEST any sampled scan vertex came to the part. Not in §6.4's field
    #: list, and added because §7.5's own acceptance vocabulary is written
    #: against it — "the socket wall clears the scan by >= 1.5 mm **at every
    #: sampled scan vertex**" is a statement about the minimum, and a record
    #: carrying only a mean and a maximum cannot express it. Direction A is
    #: exact, so a minimum here is a measurement rather than a bound; direction
    #: B deliberately gets no counterpart, because a minimum taken from a
    #: ``vertex_nn_upper_bound`` would be the smallest of a set of over-estimates
    #: and would read as a clearance nobody measured.
    scan_to_part_min_mm: float
    scan_samples: int
    part_to_scan_mean_mm: float | None
    part_to_scan_max_mm: float | None
    part_to_scan_upper_bound_mm: float | None
    part_to_scan_method: str
    part_to_scan_bias: str
    part_to_scan_refusal: str | None
    part_samples: int
    scan_canonical_hash: str
    part_artifact_ref: str

    def to_json(self) -> dict[str, Any]:
        """The wire form: ``dataclasses.asdict`` with the tuple as a list."""
        import dataclasses

        raw = dataclasses.asdict(self)
        transform = raw.get("declared_transform")
        raw["declared_transform"] = None if transform is None else list(transform)
        return raw


def _scan_vertex_sample(vertices: Any, limit: int) -> Any:
    """A deterministic sample of the scan's welded vertices (no RNG, ever).

    Canonical vertex order is a documented function of the geometry (§1.5 step
    6), so an even stride through it is reproducible in this process and the
    next — which is what the Tier 2 clause binds.
    """
    import numpy as np

    count = int(vertices.shape[0])
    if count <= limit:
        return vertices
    step = int(np.ceil(count / limit))
    return vertices[::step]


def _apply_transform(points: Any, transform: tuple[float, ...] | None) -> Any:
    """``points`` moved by a validated row-major 4x4 (identity when ``None``)."""
    import numpy as np

    if transform is None:
        return points
    matrix = np.asarray(transform, dtype=np.float64).reshape(4, 4)
    return points @ matrix[:3, :3].T + matrix[:3, 3]


#: What one completed direction looks like when it is handed to ``progress``
#: below: the record's own field names, mapped to the values that direction
#: measured. Deliberately the record's names and not a second vocabulary — a
#: partial result a caller has to translate is a partial result a caller will
#: translate wrongly.
ScanProgress = Callable[[str, "Mapping[str, float | int | str]"], None]

#: The direction names ``progress`` reports under. Closed, and the same two
#: strings ``MESH_INGEST.md`` §6.2/§6.3 use and that the §7.3 refusal names in
#: its ``lost`` tuple, so "completed" and "lost" partition one vocabulary.
SCAN_DIRECTION_SCAN_TO_PART: Final[str] = "scan_to_part"
SCAN_DIRECTION_PART_TO_SCAN: Final[str] = "part_to_scan"


def scan_distance(
    part: AnyShape,
    scan_vertices: Any,
    scan_faces: Any | None,
    *,
    align: ScanAlignMode = "as_posed",
    declared_transform: Sequence[float] | None = None,
    scan_canonical_hash: str = "",
    part_artifact_ref: str = "",
    candidate_max: int | None = None,
    vertex_sample_max: int = SCAN_VERTEX_SAMPLE_MAX,
    progress: ScanProgress | None = None,
) -> ScanDistance:
    """Both directed distances between an authored part and a scan (§6.2-§6.4).

    Direction A (scan → part) is exact and free today: ``_point_distances``
    already measures raw points against the true B-rep surface with
    ``BRepExtrema_DistShapeShape`` at 0.05 ms/pt. Direction B (part → scan)
    cannot use that path — measured at 54.6 ms/pt against a 4002-face target,
    ~515 s for one direction of one small mesh — so it samples the part's faces
    on the existing deterministic parameter grid and measures those samples
    mesh-side (:func:`hephaestus.geom.mesh.point_mesh_distances`).

    ``align="declared"`` moves the SCAN by the validated transform; the part
    stays where the build put it, because the part is the thing under
    authorship. ``align="principal"`` does not exist here at all — it is refused
    by :func:`refuse_scan_principal` at the caller's boundary, by name.

    ``progress``, when given, is called once per direction the moment that
    direction finishes, with ``(direction name, its own record fields)``. It
    exists because the §7.3 ceiling kills the process this runs in: direction A
    is exact and cheap and direction B is the expensive one, so a kill during B
    would otherwise throw away a measurement that had already been taken. A
    callback keeps this function pure — it computes nothing extra and knows
    nothing about pipes, processes or deadlines; the caller that owns the
    deadline decides what a completed direction is worth. It is never called
    with a partial direction, and a direction it reports is one the caller may
    state as measured.
    """
    import numpy as np
    from hephaestus.geom.mesh import point_mesh_distances

    if align not in SCAN_ALIGN_MODES:
        raise ScanCompareError(
            f"scan alignment must be one of {', '.join(SCAN_ALIGN_MODES)}, got {align!r}",
            reason="scan_target_unsupported",
        )
    transform = validate_declared_transform(declared_transform) if align == "declared" else None
    if align == "as_posed" and declared_transform is not None:
        raise ScanCompareError(
            "a transform was supplied with align='as_posed', "
            "which would apply a normalization the record does not declare "
            "(MESH_INGEST.md §6.5)",
            reason="declared_transform_not_rigid",
        )

    vertices = _apply_transform(np.asarray(scan_vertices, dtype=np.float64), transform)
    faces = None if scan_faces is None else np.asarray(scan_faces, dtype=np.int64)

    # §6.4/§10 ``scan_unmeasurable``, spent BEFORE either direction is — a
    # comparison with nothing to sample on one side is refused, never averaged.
    #
    # This is the defect the third repair pass's verifier reproduced end to end
    # through the product's own tool: a part authored as a bare ``Line`` has no
    # faces, ``_surface_samples`` returned ``[]``, and the record came back with
    # ``part_to_scan_upper_bound_mm = 0.0``, ``part_samples = 0`` and
    # ``part_to_scan_method = "kdtree_bound_exact_triangle"`` — the name §6.3
    # reserves for the EXACT route — with no refusal spent. §6.4 says the exact
    # pair is ``None`` "exactly when the exact refinement was abandoned"; here
    # nothing was abandoned, there was simply nothing to measure, and the
    # record's own vocabulary has no way to say so. Worse, the §6.4 invariant
    # (G12C.37) is *satisfied* by that record, so the clause that exists to
    # police these three fields cannot see it, and a CHECKS predicate reading
    # ``.part_to_scan_upper_bound_mm <= tol`` PASSES on a comparison that
    # sampled nothing — the very "absence is not a zero" failure ``§10``
    # consolidates this code for, arriving from the producer instead of from a
    # missing field.
    #
    # A refusal rather than a fourth record state on purpose: §6.4's invariant
    # is "never all three absent", so the record cannot represent "this
    # direction had nothing to measure" without breaking the clause that makes
    # its ``None``s mean something. The honest shape is the named refusal.
    part_points = _surface_samples(part)
    if not part_points:
        raise ScanCompareError(
            "the part has no faces to sample, so the part -> scan direction "
            "measured nothing. A distance of 0.0 from zero samples is not a "
            "measurement of coincidence — it is the absence of a measurement, and "
            "reporting it beside the exact method's name would be a plausible "
            "wrong number of exactly the kind this stage refuses. Give the part "
            "geometry with surface (a Line, a Wire or an empty part has none) "
            "(MESH_INGEST.md §6.4, §10)",
            reason="scan_unmeasurable",
        )
    sampled = _scan_vertex_sample(vertices, vertex_sample_max)
    points: list[Vec3] = [(float(x), float(y), float(z)) for x, y, z in sampled.tolist()]
    if not points:
        raise ScanCompareError(
            "the scan carries no points, so the scan -> part direction measured "
            "nothing. Admission refuses an empty payload by name (mesh_empty, "
            "§1.7), so this is unreachable through a build today and is refused "
            "here anyway: geom is a pure service any caller may hand arrays to, "
            "and a mean over zero samples is an absent measurement, not a zero "
            "(MESH_INGEST.md §6.4, §10)",
            reason="scan_unmeasurable",
        )
    scan_to_part = _point_distances(points, part)
    # No ``if scan_to_part else 0.0`` fallbacks here any more: the refusal above
    # already made the empty case impossible, and a fallback that cannot fire is
    # a fallback nobody re-reads before trusting.
    direction_a: dict[str, float | int | str] = {
        "align": align,
        "scan_to_part_mean_mm": sum(scan_to_part) / len(scan_to_part),
        "scan_to_part_max_mm": max(scan_to_part),
        "scan_to_part_min_mm": min(scan_to_part),
        "scan_samples": len(scan_to_part),
    }
    if progress is not None:
        progress(SCAN_DIRECTION_SCAN_TO_PART, direction_a)

    measured = point_mesh_distances(
        vertices,
        faces,
        np.asarray(part_points, dtype=np.float64).reshape(-1, 3),
        candidate_max=candidate_max,
    )
    values = measured.distances
    if not values.size:
        raise ScanCompareError(
            f"the part -> scan direction returned no distances for {len(part_points)} "
            "sampled points, so there is nothing to report in that direction. The "
            "record has no state for a direction that did not run — its Nones mean "
            "'the exact refinement was abandoned' — so this is a refusal rather "
            "than a zero (MESH_INGEST.md §6.4, §10)",
            reason="scan_unmeasurable",
        )
    exact = bool(measured.exact)
    mean = float(values.mean())
    largest = float(values.max())
    if progress is not None:
        direction_b: dict[str, float | int | str] = {
            "part_to_scan_method": measured.method,
            "part_to_scan_bias": "exact" if exact else "over",
            "part_samples": len(part_points),
        }
        # The §6.4 invariant travels with the partial: an exact pair or a bound,
        # never one beside the other, so a caller reading a killed comparison's
        # completed half cannot read a bound as a measurement.
        if exact:
            direction_b["part_to_scan_mean_mm"] = mean
            direction_b["part_to_scan_max_mm"] = largest
        else:
            direction_b["part_to_scan_upper_bound_mm"] = largest
        progress(SCAN_DIRECTION_PART_TO_SCAN, direction_b)
    return ScanDistance(
        align=align,
        declared_transform=transform,
        scan_to_part_mean_mm=cast("float", direction_a["scan_to_part_mean_mm"]),
        scan_to_part_max_mm=cast("float", direction_a["scan_to_part_max_mm"]),
        scan_to_part_min_mm=cast("float", direction_a["scan_to_part_min_mm"]),
        scan_samples=len(scan_to_part),
        part_to_scan_mean_mm=mean if exact else None,
        part_to_scan_max_mm=largest if exact else None,
        part_to_scan_upper_bound_mm=None if exact else largest,
        part_to_scan_method=measured.method,
        part_to_scan_bias="exact" if exact else "over",
        part_to_scan_refusal=measured.refusal,
        part_samples=len(part_points),
        scan_canonical_hash=scan_canonical_hash,
        part_artifact_ref=part_artifact_ref,
    )
