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
from dataclasses import dataclass
from typing import Any, Final, Literal, TypeAlias

from hephaestus.geom.measure import OVERLAP_EPS_MM3, interference
from hephaestus.geom.metrics import AnyShape, bbox_mm, genus, is_sealed, shape_volume
from hephaestus.geom.topology import Vec3

__all__ = [
    "AXIS_DECIMALS",
    "AXIS_EPS",
    "MAX_FACE_SAMPLES",
    "MIN_FACE_SAMPLES",
    "MOMENT_TIE_REL",
    "SAMPLES_PER_MM2",
    "SKEW_EPS",
    "AlignMode",
    "Alignment",
    "SolidDiff",
    "SurfaceDistance",
    "TopologyCensus",
    "TopologyDiff",
    "VolumeDiff",
    "principal_alignment",
    "solid_diff",
    "surface_distance",
    "topology_diff",
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
    return _boolean_volume(a.cut(b))


def volume_diff(a: AnyShape, b: AnyShape, *, align: AlignMode = "as_posed") -> VolumeDiff:
    """Boolean symmetric difference of ``a`` and ``b`` (``COMPARE.md`` §1)."""
    pa, pb = _aligned_pair(a, b, align)
    common = interference(pa, pb)
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
