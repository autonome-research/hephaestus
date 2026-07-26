"""Kernel topology service: the geometric facts DFM rules are written against.

Pure functions over one built solid (architecture §3.2), in the same spirit as
:mod:`hephaestus.core.kernel.metrics`: they measure, they never decide. Each
record carries the face's ``index`` within that solid's ``faces()``
enumeration, which is exactly the ``topology_index`` an artifact-bound
descriptor reports, so a measurement can always be pointed at.

Four primitives, chosen because they are the ones every manufacturing rule pack
needs and none of them should re-derive:

* :func:`planar_faces` — centre, outward normal, area.
* :func:`cylindrical_faces` — radius, axis, angular sweep, and two
  classifications: *internal* (the outward normal points towards the axis, so
  material is outside the surface: a bore or a concave corner round) and *full*
  (the surface closes a 2π sweep: a bore rather than a corner round).
* :func:`opposing_planar_pairs` — anti-parallel planar faces with material
  between them and the thickness of it. The pair test is not "parallel": the
  faces' true minimum separation must equal the normal-projected distance,
  which holds only when they actually overlap when projected onto their common
  plane. That is the minimum-wall measurement.
* :func:`downward_faces` — every face with a downward-facing component and the
  angle from vertical, exact for a plane and worst-of-a-parameter-grid for a
  curved surface (flagged ``sampled``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Final

__all__ = [
    "OVERHANG_SAMPLES",
    "PARALLEL_EPS",
    "WALL_FACE_LIMIT",
    "CylinderRecord",
    "DownwardFace",
    "OpposingPair",
    "PlanarFaceRecord",
    "Vec3",
    "cylindrical_faces",
    "downward_faces",
    "opposing_planar_pairs",
    "planar_faces",
    "solid_z_min",
]

Vec3 = tuple[float, float, float]

#: Per-solid cap on the planar faces considered when pairing walls. Beyond it
#: the largest faces are kept and the caller is told the search was truncated,
#: rather than quietly measuring a subset of a pathological solid.
WALL_FACE_LIMIT: Final[int] = 96

#: Parameter-grid resolution when sampling a curved face's overhang angle.
OVERHANG_SAMPLES: Final[int] = 5

#: Direction cosines within this of ±1 count as parallel / anti-parallel.
PARALLEL_EPS: Final[float] = 1e-6

_FULL_SWEEP_EPS: Final[float] = 1e-6
_FACING_EPS_MM: Final[float] = 1e-6


def _v(value: Any) -> Vec3:
    return (float(value.X), float(value.Y), float(value.Z))


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


@dataclass(frozen=True)
class PlanarFaceRecord:
    """A planar face of one solid: where it is, which way it faces, how big."""

    index: int
    center: Vec3
    normal: Vec3
    area: float


@dataclass(frozen=True)
class CylinderRecord:
    """A cylindrical face of one solid, classified internal/external, full/partial."""

    index: int
    radius: float
    axis: Vec3
    axis_point: Vec3
    sweep_rad: float
    internal: bool
    full: bool
    area: float


@dataclass(frozen=True)
class OpposingPair:
    """Two anti-parallel planar faces with ``thickness_mm`` of material between."""

    a: int
    b: int
    thickness_mm: float


@dataclass(frozen=True)
class DownwardFace:
    """A face with a downward-facing component and its angle from vertical.

    ``angle_deg`` is 0 for a vertical surface and 90 for a horizontal downward
    one. ``sampled`` marks a curved face, whose angle is the worst of a
    parameter-grid sample rather than an exact extremum.
    """

    index: int
    angle_deg: float
    normal: Vec3
    point: Vec3
    area: float
    sampled: bool


def solid_z_min(solid: Any) -> float:
    """The solid's lowest Z (its contact plane when it sits on the plate)."""
    return float(solid.bounding_box().min.Z)


def planar_faces(solid: Any) -> tuple[PlanarFaceRecord, ...]:
    """Every planar face of ``solid``, in ``faces()`` enumeration order."""
    from build123d import GeomType

    out: list[PlanarFaceRecord] = []
    for index, face in enumerate(solid.faces()):
        if face.geom_type != GeomType.PLANE:
            continue
        center = face.center()
        out.append(
            PlanarFaceRecord(
                index=index,
                center=_v(center),
                normal=_v(face.normal_at(center)),
                area=float(face.area),
            )
        )
    return tuple(out)


def cylindrical_faces(solid: Any) -> tuple[CylinderRecord, ...]:
    """Every cylindrical face of ``solid``, with its radius, axis and sweep."""
    from build123d import GeomType
    from OCP.BRepAdaptor import BRepAdaptor_Surface  # pyright: ignore[reportAttributeAccessIssue]

    out: list[CylinderRecord] = []
    for index, face in enumerate(solid.faces()):
        if face.geom_type != GeomType.CYLINDER:
            continue
        adaptor = BRepAdaptor_Surface(face.wrapped)
        cylinder = adaptor.Cylinder()
        axis = cylinder.Axis()
        direction = axis.Direction()
        location = axis.Location()
        axis_dir: Vec3 = (float(direction.X()), float(direction.Y()), float(direction.Z()))
        axis_point: Vec3 = (float(location.X()), float(location.Y()), float(location.Z()))
        center = _v(face.center())
        normal = _v(face.normal_at(face.center()))
        offset = _sub(center, axis_point)
        along = _dot(offset, axis_dir)
        radial: Vec3 = (
            offset[0] - along * axis_dir[0],
            offset[1] - along * axis_dir[1],
            offset[2] - along * axis_dir[2],
        )
        sweep = float(adaptor.LastUParameter() - adaptor.FirstUParameter())
        out.append(
            CylinderRecord(
                index=index,
                radius=float(cylinder.Radius()),
                axis=axis_dir,
                axis_point=axis_point,
                sweep_rad=sweep,
                internal=_dot(normal, radial) < 0.0,
                full=abs(sweep - 2.0 * math.pi) <= _FULL_SWEEP_EPS,
                area=float(face.area),
            )
        )
    return tuple(out)


def opposing_planar_pairs(
    solid: Any,
    *,
    face_limit: int = WALL_FACE_LIMIT,
) -> tuple[tuple[OpposingPair, ...], bool]:
    """``(pairs, truncated)`` — anti-parallel planar faces and the wall between.

    ``truncated`` is True when the solid had more planar faces than
    ``face_limit`` and only its largest were paired; a caller that reports a
    minimum must say so rather than imply it searched everything.
    """
    faces = planar_faces(solid)
    truncated = len(faces) > face_limit
    if truncated:
        faces = tuple(sorted(faces, key=lambda f: -f.area))[:face_limit]
    shapes = list(solid.faces())
    out: list[OpposingPair] = []
    for first in range(len(faces)):
        for second in range(first + 1, len(faces)):
            a = faces[first]
            b = faces[second]
            if abs(_dot(a.normal, b.normal) + 1.0) > PARALLEL_EPS:
                continue
            signed = _dot(_sub(b.center, a.center), a.normal)
            if signed >= -_FACING_EPS_MM:
                continue
            thickness = -signed
            separation = float(shapes[a.index].distance_to(shapes[b.index]))
            if abs(separation - thickness) > 1e-6 + 1e-9 * max(1.0, thickness):
                continue
            out.append(OpposingPair(a=a.index, b=b.index, thickness_mm=thickness))
    return tuple(out), truncated


def downward_faces(solid: Any, *, samples: int = OVERHANG_SAMPLES) -> tuple[DownwardFace, ...]:
    """Every face of ``solid`` with a downward-facing component (+Z is up)."""
    planar = {record.index: record for record in planar_faces(solid)}
    out: list[DownwardFace] = []
    for index, face in enumerate(solid.faces()):
        flat = planar.get(index)
        if flat is not None:
            normal, point, area, sampled = flat.normal, flat.center, flat.area, False
        else:
            curved = _worst_downward_sample(face, samples)
            if curved is None:
                continue
            normal, point = curved
            area, sampled = float(face.area), True
        down = -normal[2]
        if down <= PARALLEL_EPS:
            continue
        out.append(
            DownwardFace(
                index=index,
                angle_deg=math.degrees(math.asin(max(0.0, min(1.0, down)))),
                normal=normal,
                point=point,
                area=area,
                sampled=sampled,
            )
        )
    return tuple(out)


def _worst_downward_sample(face: Any, samples: int) -> tuple[Vec3, Vec3] | None:
    """The (normal, point) of the most downward-facing grid sample of a face."""
    worst: tuple[Vec3, Vec3] | None = None
    best = -2.0
    steps = max(1, samples)
    for i in range(steps):
        u = (i + 0.5) / steps
        for j in range(steps):
            v = (j + 0.5) / steps
            try:
                normal = _v(face.normal_at(u=u, v=v))
                point = _v(face.position_at(u, v))
            except Exception:
                continue
            if -normal[2] > best:
                best = -normal[2]
                worst = (normal, point)
    return worst
