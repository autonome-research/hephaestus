"""Tag descriptor fingerprints and the §5.3 descriptor-change heuristic.

Every tagged topology is fingerprinted at build time. Comparing against the
prior *successful current* build's fingerprints yields
``tag_descriptor_changed`` warnings — a drift heuristic with explicit exact
thresholds, never an identity verdict:

- face: centroid displacement > 1.0 mm, normal angle > 5.0°, or relative
  area delta > 2%
- edge: midpoint displacement > 1.0 mm or relative length delta > 2%
- solid: centroid displacement > 1.0 mm or relative volume delta > 2%

Relative delta is ``abs(new-old)/max(abs(old), 1e-9)``. The baseline is the
successful current artifact only (its opaque ref is carried in warning
evidence); with no baseline, no warning. A no-op refactor produces identical
descriptors and therefore never warns.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from hephaestus.core.errors import ValidationError
from hephaestus.core.types import Warning
from opstore.types import JSONValue

#: Exact §5.3 thresholds (strictly-exceeds warns; equality does not).
FACE_CENTROID_MM = 1.0
FACE_NORMAL_DEG = 5.0
FACE_AREA_REL = 0.02
EDGE_MIDPOINT_MM = 1.0
EDGE_LENGTH_REL = 0.02
SOLID_CENTROID_MM = 1.0
SOLID_VOLUME_REL = 0.02

#: Relative-delta guard: ``abs(new-old)/max(abs(old), REL_EPS)``.
REL_EPS = 1e-9

_KINDS = ("face", "edge", "solid", "wire", "vertex", "other")

#: The closed surface/curve label ``PARTS_STORE.md`` §2.3 needs and nothing else
#: crossed the sandbox boundary carrying. ``kind`` is a three-way face/edge/solid
#: label, so four of the five declared interface classes — ``planar_face`` vs
#: ``cylindrical_face``, ``circular_edge`` vs ``linear_edge`` — are invisible to
#: it. This is a §8 worker result protocol change, not a sandbox-contract
#: change: it is computed **in the worker**, where the shape lives.
GEOM_TYPES = ("PLANE", "CYLINDER", "CIRCLE", "LINE", "OTHER")


def rel_delta(new: float, old: float) -> float:
    """§5.3 relative delta: ``abs(new-old)/max(abs(old), 1e-9)``."""
    return abs(new - old) / max(abs(old), REL_EPS)


def _displacement(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return math.dist(a, b)


def _angle_deg(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True)) / (na * nb)
    return math.degrees(math.acos(max(-1.0, min(1.0, dot))))


@dataclass(frozen=True)
class TagDescriptor:
    """Geometric fingerprint of one tagged topology.

    ``point`` is the face centroid / edge midpoint / solid centroid;
    ``normal`` is set for faces only; ``scalar`` is area (face, mm^2),
    length (edge, mm), or volume (solid, mm^3).

    ``geom_type`` is the surface/curve class read off the OCP adaptor
    (``PARTS_STORE.md`` §2.3). ``OTHER`` for a solid is *by definition*, not by
    failure: a solid has no single adaptor, so ``("solid", "OTHER")`` is a
    positive verification of the declared ``solid`` class rather than a
    fallthrough.
    """

    kind: str
    point: tuple[float, float, float]
    scalar: float
    normal: tuple[float, float, float] | None = None
    geom_type: str = "OTHER"

    def __post_init__(self) -> None:
        if self.kind not in _KINDS:
            raise ValidationError(f"invalid descriptor kind {self.kind!r}", kind="contract")
        if self.geom_type not in GEOM_TYPES:
            raise ValidationError(
                f"invalid descriptor geom_type {self.geom_type!r}; the closed set is "
                + ", ".join(GEOM_TYPES),
                kind="contract",
            )

    def to_json(self) -> dict[str, JSONValue]:
        out: dict[str, JSONValue] = {
            "kind": self.kind,
            "point": list(self.point),
            "scalar": self.scalar,
            "geom_type": self.geom_type,
        }
        if self.normal is not None:
            out["normal"] = list(self.normal)
        return out

    @classmethod
    def from_json(cls, data: Mapping[str, JSONValue]) -> TagDescriptor:
        kind = data.get("kind")
        point = data.get("point")
        scalar = data.get("scalar")
        if not isinstance(kind, str):
            raise ValidationError("descriptor 'kind' must be a string", kind="contract")
        if not isinstance(point, list) or len(point) != 3:
            raise ValidationError("descriptor 'point' must be [x, y, z]", kind="contract")
        if isinstance(scalar, bool) or not isinstance(scalar, int | float):
            raise ValidationError("descriptor 'scalar' must be a number", kind="contract")
        coords: list[float] = []
        for value in point:
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise ValidationError("descriptor 'point' must be numeric", kind="contract")
            coords.append(float(value))
        normal_raw = data.get("normal")
        normal: tuple[float, float, float] | None = None
        if normal_raw is not None:
            if not isinstance(normal_raw, list) or len(normal_raw) != 3:
                raise ValidationError("descriptor 'normal' must be [x, y, z]", kind="contract")
            axes: list[float] = []
            for value in normal_raw:
                if isinstance(value, bool) or not isinstance(value, int | float):
                    raise ValidationError("descriptor 'normal' must be numeric", kind="contract")
                axes.append(float(value))
            normal = (axes[0], axes[1], axes[2])
        # Absent => OTHER: a build bundle published before this stage carries no
        # `geom_type`, and refusing to read one would make an existing project's
        # fingerprint baseline unloadable. An out-of-set *value* is still refused
        # (in __post_init__), which is the drift the gate cares about.
        geom_type_raw = data.get("geom_type", "OTHER")
        if not isinstance(geom_type_raw, str):
            raise ValidationError("descriptor 'geom_type' must be a string", kind="contract")
        return cls(
            kind=kind,
            point=(coords[0], coords[1], coords[2]),
            scalar=float(scalar),
            normal=normal,
            geom_type=geom_type_raw,
        )


@dataclass(frozen=True)
class FingerprintBaseline:
    """The prior successful-current build's fingerprints plus its artifact ref."""

    descriptors: Mapping[str, TagDescriptor]
    artifact_ref: str

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, FingerprintBaseline):
            return NotImplemented
        return (
            dict(self.descriptors) == dict(other.descriptors)
            and self.artifact_ref == other.artifact_ref
        )

    def __hash__(self) -> int:
        return hash((self.artifact_ref, tuple(sorted(self.descriptors))))


def _surface_type(face: object) -> str:
    """``PLANE`` / ``CYLINDER`` / ``OTHER`` for a build123d Face.

    A torus, a cone or a B-spline classifies ``OTHER`` and therefore matches no
    declared interface class. That is meant: this stage's consumers (8C
    ``coincident`` / ``concentric`` / ``fit``, Stage 9 ``revolute`` /
    ``prismatic``) accept none of them, and admitting a class the consumers
    cannot use is how ``mating_features`` happened. Adding one is a contract
    amendment, the ``ASSEMBLY.md:45`` convention.
    """
    try:
        from OCP.BRepAdaptor import (
            BRepAdaptor_Surface,  # pyright: ignore[reportAttributeAccessIssue]
        )
        from OCP.GeomAbs import (
            GeomAbs_SurfaceType,  # pyright: ignore[reportAttributeAccessIssue]
        )

        surface_type = BRepAdaptor_Surface(cast("Any", face).wrapped).GetType()
    except Exception:  # pragma: no cover - a shape with no usable adaptor
        return "OTHER"
    if surface_type == GeomAbs_SurfaceType.GeomAbs_Plane:
        return "PLANE"
    if surface_type == GeomAbs_SurfaceType.GeomAbs_Cylinder:
        return "CYLINDER"
    return "OTHER"


def _curve_type(edge: object) -> str:
    """``CIRCLE`` / ``LINE`` / ``OTHER`` for a build123d Edge."""
    try:
        from OCP.BRepAdaptor import (
            BRepAdaptor_Curve,  # pyright: ignore[reportAttributeAccessIssue]
        )
        from OCP.GeomAbs import (
            GeomAbs_CurveType,  # pyright: ignore[reportAttributeAccessIssue]
        )

        curve_type = BRepAdaptor_Curve(cast("Any", edge).wrapped).GetType()
    except Exception:  # pragma: no cover - a shape with no usable adaptor
        return "OTHER"
    if curve_type == GeomAbs_CurveType.GeomAbs_Circle:
        return "CIRCLE"
    if curve_type == GeomAbs_CurveType.GeomAbs_Line:
        return "LINE"
    return "OTHER"


def descriptor_for(shape: object) -> TagDescriptor:
    """Compute the fingerprint descriptor of a build123d Face/Edge/Solid.

    Called from the worker (``worker.py``'s ``tag_fingerprints`` block), which
    is the only place the shape exists: the scratch tree holding the BRep is
    deleted in a ``finally`` before any caller sees it, so a surface or curve
    type computed anywhere else would have nothing to read.
    """
    from build123d import Edge, Face, Solid

    if isinstance(shape, Face):
        center = shape.center()
        point = (float(center.X), float(center.Y), float(center.Z))
        normal = shape.normal_at(center)
        return TagDescriptor(
            kind="face",
            point=point,
            scalar=float(shape.area),
            normal=(float(normal.X), float(normal.Y), float(normal.Z)),
            geom_type=_surface_type(shape),
        )
    if isinstance(shape, Edge):
        mid = shape.position_at(0.5)
        return TagDescriptor(
            kind="edge",
            point=(float(mid.X), float(mid.Y), float(mid.Z)),
            scalar=float(shape.length),
            geom_type=_curve_type(shape),
        )
    if isinstance(shape, Solid):
        center = shape.center()
        return TagDescriptor(
            kind="solid",
            point=(float(center.X), float(center.Y), float(center.Z)),
            scalar=float(shape.volume),
            geom_type="OTHER",
        )
    center_of = getattr(shape, "center", None)
    volume = getattr(shape, "volume", 0.0)
    if callable(center_of):
        center = cast("Any", center_of())
        point = (float(center.X), float(center.Y), float(center.Z))
    else:
        point = (0.0, 0.0, 0.0)
    return TagDescriptor(kind="other", point=point, scalar=float(volume))


def descriptors_to_json(descriptors: Mapping[str, TagDescriptor]) -> dict[str, JSONValue]:
    return {name: descriptors[name].to_json() for name in sorted(descriptors)}


def descriptors_from_json(data: Mapping[str, JSONValue]) -> dict[str, TagDescriptor]:
    out: dict[str, TagDescriptor] = {}
    for name, raw in data.items():
        if not isinstance(raw, dict):
            raise ValidationError(f"descriptor {name!r}: expected object", kind="contract")
        out[name] = TagDescriptor.from_json(raw)
    return out


def _deltas(new: TagDescriptor, old: TagDescriptor) -> list[tuple[str, float, float, str]]:
    """Exceeded thresholds as (measure, measured, threshold, unit) rows."""
    rows: list[tuple[str, float, float, str]] = []
    if new.kind == "face":
        displacement = _displacement(new.point, old.point)
        if displacement > FACE_CENTROID_MM:
            rows.append(("centroid_displacement", displacement, FACE_CENTROID_MM, "mm"))
        if new.normal is not None and old.normal is not None:
            angle = _angle_deg(new.normal, old.normal)
            if angle > FACE_NORMAL_DEG:
                rows.append(("normal_angle", angle, FACE_NORMAL_DEG, "deg"))
        area_delta = rel_delta(new.scalar, old.scalar)
        if area_delta > FACE_AREA_REL:
            rows.append(("area_rel_delta", area_delta, FACE_AREA_REL, "rel"))
    elif new.kind == "edge":
        displacement = _displacement(new.point, old.point)
        if displacement > EDGE_MIDPOINT_MM:
            rows.append(("midpoint_displacement", displacement, EDGE_MIDPOINT_MM, "mm"))
        length_delta = rel_delta(new.scalar, old.scalar)
        if length_delta > EDGE_LENGTH_REL:
            rows.append(("length_rel_delta", length_delta, EDGE_LENGTH_REL, "rel"))
    elif new.kind == "solid":
        displacement = _displacement(new.point, old.point)
        if displacement > SOLID_CENTROID_MM:
            rows.append(("centroid_displacement", displacement, SOLID_CENTROID_MM, "mm"))
        volume_delta = rel_delta(new.scalar, old.scalar)
        if volume_delta > SOLID_VOLUME_REL:
            rows.append(("volume_rel_delta", volume_delta, SOLID_VOLUME_REL, "rel"))
    return rows


def compare(
    current: Mapping[str, TagDescriptor],
    baseline: FingerprintBaseline | None,
) -> tuple[Warning, ...]:
    """Emit ``tag_descriptor_changed`` warnings for tags whose descriptor drifted.

    With no baseline (no prior successful current artifact) no warning is
    emitted. Tags new in ``current`` or removed since the baseline never
    warn. The warning text reports each measured delta against its threshold
    and recommends inspection or a stronger persistent CHECK — it never
    claims topology identity changed.
    """
    if baseline is None:
        return ()
    warnings: list[Warning] = []
    for name in current:
        old = baseline.descriptors.get(name)
        if old is None:
            continue
        new = current[name]
        if new.kind != old.kind:
            detail = (
                f"tag {name!r}: tagged topology kind is now {new.kind!r} "
                f"(baseline {old.kind!r}); the selector may resolve differently — "
                "inspect the part or add a stronger persistent CHECK"
            )
            warnings.append(
                Warning(
                    kind="tag_descriptor_changed",
                    tag=name,
                    detail=detail,
                    evidence={
                        "baseline_ref": baseline.artifact_ref,
                        "kind": new.kind,
                        "baseline_kind": old.kind,
                    },
                )
            )
            continue
        rows = _deltas(new, old)
        if not rows:
            continue
        measured: dict[str, JSONValue] = {
            measure: {"measured": value, "threshold": threshold, "unit": unit}
            for measure, value, threshold, unit in rows
        }
        listing = "; ".join(
            f"{measure}={value:.6g} {unit} (threshold {threshold:g})"
            for measure, value, threshold, unit in rows
        )
        detail = (
            f"tag {name!r}: descriptor changed against the prior successful current "
            f"build — {listing}. This is a drift heuristic, not an identity verdict; "
            "inspect the selection or add a stronger persistent CHECK."
        )
        warnings.append(
            Warning(
                kind="tag_descriptor_changed",
                tag=name,
                detail=detail,
                evidence={"baseline_ref": baseline.artifact_ref, "deltas": measured},
            )
        )
    return tuple(warnings)
