"""The evaluation context a DFM predicate receives — geometry made measurable.

A rule predicate is untrusted registry content executing under the part-script
sandbox and the §2 injected namespace, so everything it needs must arrive as
*data and pure measurement*, never as new capability. That is what
:class:`DfmContext` is: the artifact's topology enumerated in the artifact's own
deterministic order (so every measurement can be reported as an artifact-bound
:class:`~hephaestus.core.dfm.types.TopologyDescriptor`), plus the part's §5.2
metadata, the resolved materials record, and exactly the pack parameters the
rule declared it reads.

The geometry itself is measured by :mod:`hephaestus.core.kernel.topology`; this
module's job is to bind each measurement to the handle that addresses it, so a
predicate that finds a thin wall or an undersized bore can point at it:

* :meth:`DfmContext.cylinders` / :meth:`~DfmContext.holes` /
  :meth:`~DfmContext.internal_rounds` — bores and concave corner rounds;
* :meth:`DfmContext.planar_faces` — centre, outward normal, area;
* :meth:`DfmContext.opposing_faces` — wall thickness between facing planes;
* :meth:`DfmContext.overhangs` — overhang angle from vertical, with the faces
  resting on the build plate marked as supported.

Predicates report through :meth:`DfmContext.report`; the rule id, title and
severity are attached afterwards from the rule declaration, so a predicate can
neither invent a rule id nor downgrade its own severity.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from hephaestus.core.dfm.types import TopologyDescriptor, TopologyKind
from hephaestus.core.errors import ValidationError
from hephaestus.core.kernel.topology import (
    OVERHANG_SAMPLES,
    WALL_FACE_LIMIT,
    Vec3,
    cylindrical_faces,
    downward_faces,
    opposing_planar_pairs,
    planar_faces,
    solid_z_min,
)
from opstore.types import JSONValue

__all__ = [
    "OVERHANG_SAMPLES",
    "WALL_FACE_LIMIT",
    "CylindricalFace",
    "DfmContext",
    "OpposingFaces",
    "Overhang",
    "PlanarFace",
    "RawFinding",
    "TopologyHandle",
    "Vec3",
    "build_context",
]

#: Z tolerance (mm) for deciding a downward face rests on the build plate.
_PLATE_EPS_MM = 1e-6


@dataclass(frozen=True)
class TopologyHandle:
    """One topology of the artifact: its address plus the live shape object."""

    kind: TopologyKind
    solid_id: int
    topology_index: int
    tag: str | None
    shape: object

    def descriptor(self) -> TopologyDescriptor:
        """The artifact-bound descriptor a finding reports."""
        return TopologyDescriptor(
            kind=self.kind,
            solid_id=self.solid_id,
            topology_index=self.topology_index,
            tag=self.tag,
        )


@dataclass(frozen=True)
class PlanarFace:
    """A planar face with its outward normal, centre and area (mm)."""

    ref: TopologyHandle
    center: Vec3
    normal: Vec3
    area: float


@dataclass(frozen=True)
class CylindricalFace:
    """A cylindrical face: radius, axis, and whether it is internal / closed.

    ``internal`` is True when the face's outward normal points *towards* the
    cylinder axis — material lies outside the surface, i.e. a bore or a concave
    corner round. ``full`` is True when the surface sweeps a closed 2π: a bore
    rather than a corner round.
    """

    ref: TopologyHandle
    radius: float
    axis: Vec3
    axis_point: Vec3
    sweep_rad: float
    internal: bool
    full: bool
    area: float


@dataclass(frozen=True)
class OpposingFaces:
    """Two anti-parallel planar faces with material between them (a wall)."""

    a: TopologyHandle
    b: TopologyHandle
    thickness_mm: float


@dataclass(frozen=True)
class Overhang:
    """A downward-facing face and its overhang angle from vertical (degrees).

    ``angle_deg`` is 0 for a vertical wall and 90 for a horizontal downward
    face (a bridge). ``on_build_plate`` marks the faces resting on the plate,
    which are supported by definition. For a curved face the angle is the worst
    of a parameter-grid sample rather than an exact extremum, and ``sampled``
    says so — a rule that reports it should not claim more precision than that.
    """

    ref: TopologyHandle
    angle_deg: float
    normal: Vec3
    center: Vec3
    area: float
    on_build_plate: bool
    sampled: bool = False


@dataclass(frozen=True)
class RawFinding:
    """What a predicate reported, before the rule declaration is attached."""

    message: str
    tags: tuple[str, ...]
    topology: tuple[TopologyDescriptor, ...]
    measured: JSONValue
    suggested_bound: float | None

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "message": self.message,
            "tags": list(self.tags),
            "topology": [descriptor.to_json() for descriptor in self.topology],
            "measured": self.measured,
            "suggested_bound": self.suggested_bound,
        }


class DfmContext:
    """The typed evaluation context handed to one rule predicate.

    Construct with :func:`build_context` inside the worker; predicates only ever
    read from it and call :meth:`report`.
    """

    def __init__(
        self,
        *,
        part: str,
        process: str,
        source_artifact_ref: str,
        geometry: object,
        params: Mapping[str, float],
        metadata: Mapping[str, str],
        material: Mapping[str, JSONValue] | None,
        tags: Mapping[str, TopologyDescriptor],
    ) -> None:
        self._part = part
        self._process = process
        self._artifact = source_artifact_ref
        self._geometry = geometry
        self._params = dict(params)
        self._metadata = dict(metadata)
        self._material = dict(material) if material is not None else None
        self._tag_descriptors = dict(tags)
        self._findings: list[RawFinding] = []
        self.truncated = False
        self._solids: list[Any] = list(cast("Any", geometry).solids())
        self._tag_by_address: dict[tuple[str, int, int], str] = {
            (d.kind, d.solid_id, d.topology_index): name
            for name, d in sorted(self._tag_descriptors.items())
        }
        self._faces_cache: dict[int, list[Any]] = {}
        self._edges_cache: dict[int, list[Any]] = {}

    # -- part facts --------------------------------------------------------

    @property
    def part(self) -> str:
        """The part name this artifact belongs to."""
        return self._part

    @property
    def process(self) -> str:
        """The manufacturing process whose pack is running."""
        return self._process

    @property
    def source_artifact_ref(self) -> str:
        """The immutable artifact every measurement here is bound to."""
        return self._artifact

    @property
    def params(self) -> Mapping[str, float]:
        """Exactly the pack parameters this rule declared in ``reads``."""
        return dict(self._params)

    def param(self, name: str) -> float:
        """One declared parameter; an undeclared name is a contract error."""
        if name not in self._params:
            declared = ", ".join(sorted(self._params)) or "(none)"
            raise ValidationError(
                f"DFM rule read undeclared parameter {name!r}; the rule declares: {declared}",
                kind="contract",
            )
        return self._params[name]

    @property
    def metadata(self) -> Mapping[str, str]:
        """The part's §5.2 manufacturing-metadata fields (free text)."""
        return dict(self._metadata)

    @property
    def material(self) -> Mapping[str, JSONValue] | None:
        """The resolved materials-registry record, or None when unresolved."""
        return dict(self._material) if self._material is not None else None

    @property
    def geometry(self) -> object:
        """The artifact's root shape (build123d)."""
        return self._geometry

    def bbox(self) -> Vec3:
        """Axis-aligned bounding-box extents (mm) of the whole artifact."""
        size = cast("Any", self._geometry).bounding_box().size
        return (float(size.X), float(size.Y), float(size.Z))

    def sheet_thickness(self) -> float:
        """The artifact's smallest bounding-box extent (mm) — sheet thickness."""
        return min(self.bbox())

    def tag_names(self) -> tuple[str, ...]:
        """Every §5.3 tag that resolved to topology in this artifact."""
        return tuple(sorted(self._tag_descriptors))

    def tag(self, name: str) -> TopologyHandle:
        """The tagged topology by name; an unknown tag lists the known ones."""
        descriptor = self._tag_descriptors.get(name)
        if descriptor is None:
            known = ", ".join(self.tag_names()) or "(none)"
            raise ValidationError(
                f"no tag {name!r} in this artifact; tags: {known}", kind="contract"
            )
        return self._handle(descriptor.kind, descriptor.solid_id, descriptor.topology_index)

    # -- topology enumeration ---------------------------------------------

    def solid_count(self) -> int:
        """How many solids the artifact compound holds."""
        return len(self._solids)

    def solids(self) -> tuple[TopologyHandle, ...]:
        """Every solid, in the artifact compound's own order."""
        return tuple(
            TopologyHandle(
                kind="solid",
                solid_id=index,
                topology_index=index,
                tag=self._tag_by_address.get(("solid", index, index)),
                shape=solid,
            )
            for index, solid in enumerate(self._solids)
        )

    def faces(self, solid_id: int | None = None) -> tuple[TopologyHandle, ...]:
        """Every face (of one solid, or of all of them) in enumeration order."""
        out: list[TopologyHandle] = []
        for index in self._solid_ids(solid_id):
            out.extend(
                self._face_handle(index, position)
                for position in range(len(self._face_shapes(index)))
            )
        return tuple(out)

    def edges(self, solid_id: int | None = None) -> tuple[TopologyHandle, ...]:
        """Every edge (of one solid, or of all of them) in enumeration order."""
        out: list[TopologyHandle] = []
        for index in self._solid_ids(solid_id):
            for position, shape in enumerate(self._edge_shapes(index)):
                out.append(
                    TopologyHandle(
                        kind="edge",
                        solid_id=index,
                        topology_index=position,
                        tag=self._tag_by_address.get(("edge", index, position)),
                        shape=shape,
                    )
                )
        return tuple(out)

    def _face_shapes(self, solid_id: int) -> list[Any]:
        cached = self._faces_cache.get(solid_id)
        if cached is None:
            cached = list(self._solids[solid_id].faces())
            self._faces_cache[solid_id] = cached
        return cached

    def _edge_shapes(self, solid_id: int) -> list[Any]:
        cached = self._edges_cache.get(solid_id)
        if cached is None:
            cached = list(self._solids[solid_id].edges())
            self._edges_cache[solid_id] = cached
        return cached

    def _face_handle(self, solid_id: int, position: int) -> TopologyHandle:
        return TopologyHandle(
            kind="face",
            solid_id=solid_id,
            topology_index=position,
            tag=self._tag_by_address.get(("face", solid_id, position)),
            shape=self._face_shapes(solid_id)[position],
        )

    def _solid_ids(self, solid_id: int | None) -> Sequence[int]:
        if solid_id is None:
            return range(len(self._solids))
        if solid_id < 0 or solid_id >= len(self._solids):
            raise ValidationError(
                f"solid {solid_id} is out of range (the artifact has {len(self._solids)} solids)",
                kind="contract",
            )
        return (solid_id,)

    def _handle(self, kind: str, solid_id: int, topology_index: int) -> TopologyHandle:
        if kind == "face":
            return self._face_handle(solid_id, topology_index)
        if kind == "edge":
            shapes = self._edge_shapes(solid_id)
            return TopologyHandle(
                kind="edge",
                solid_id=solid_id,
                topology_index=topology_index,
                tag=self._tag_by_address.get(("edge", solid_id, topology_index)),
                shape=shapes[topology_index],
            )
        return TopologyHandle(
            kind=cast("TopologyKind", kind),
            solid_id=solid_id,
            topology_index=topology_index,
            tag=self._tag_by_address.get((kind, solid_id, topology_index)),
            shape=self._solids[solid_id],
        )

    # -- derived geometry primitives --------------------------------------

    def planar_faces(self, solid_id: int | None = None) -> tuple[PlanarFace, ...]:
        """Planar faces with centre, outward normal and area."""
        out: list[PlanarFace] = []
        for index in self._solid_ids(solid_id):
            for record in planar_faces(self._solids[index]):
                out.append(
                    PlanarFace(
                        ref=self._face_handle(index, record.index),
                        center=record.center,
                        normal=record.normal,
                        area=record.area,
                    )
                )
        return tuple(out)

    def cylinders(self, solid_id: int | None = None) -> tuple[CylindricalFace, ...]:
        """Cylindrical faces classified internal/external and full/partial."""
        out: list[CylindricalFace] = []
        for index in self._solid_ids(solid_id):
            for record in cylindrical_faces(self._solids[index]):
                out.append(
                    CylindricalFace(
                        ref=self._face_handle(index, record.index),
                        radius=record.radius,
                        axis=record.axis,
                        axis_point=record.axis_point,
                        sweep_rad=record.sweep_rad,
                        internal=record.internal,
                        full=record.full,
                        area=record.area,
                    )
                )
        return tuple(out)

    def holes(self, solid_id: int | None = None) -> tuple[CylindricalFace, ...]:
        """Closed internal bores (full-sweep internal cylinders)."""
        return tuple(c for c in self.cylinders(solid_id) if c.internal and c.full)

    def internal_rounds(self, solid_id: int | None = None) -> tuple[CylindricalFace, ...]:
        """Concave corner rounds (partial-sweep internal cylinders)."""
        return tuple(c for c in self.cylinders(solid_id) if c.internal and not c.full)

    def opposing_faces(self, solid_id: int | None = None) -> tuple[OpposingFaces, ...]:
        """Anti-parallel planar face pairs with material between them.

        A pair qualifies when the two outward normals are anti-parallel, the
        second face lies *behind* the first, and the faces' true minimum
        separation equals that normal-projected distance — which is exactly the
        condition that they overlap when projected onto their common plane
        rather than merely being parallel somewhere else on the part. The
        reported thickness is the wall between them. When a solid has more
        planar faces than :data:`WALL_FACE_LIMIT` only its largest are paired
        and :attr:`truncated` is set.
        """
        out: list[OpposingFaces] = []
        for index in self._solid_ids(solid_id):
            pairs, truncated = opposing_planar_pairs(self._solids[index])
            self.truncated = self.truncated or truncated
            for pair in pairs:
                out.append(
                    OpposingFaces(
                        a=self._face_handle(index, pair.a),
                        b=self._face_handle(index, pair.b),
                        thickness_mm=pair.thickness_mm,
                    )
                )
        return tuple(out)

    def overhangs(self, solid_id: int | None = None) -> tuple[Overhang, ...]:
        """Downward-facing faces with their overhang angle from vertical.

        The build direction is +Z (the §5.2 convention for an FDM part sitting
        on the plate). A planar face is measured exactly from its one normal; a
        curved face is sampled on an :data:`OVERHANG_SAMPLES`-square parameter
        grid and reported at its worst sample, flagged ``sampled=True``.
        """
        out: list[Overhang] = []
        for index in self._solid_ids(solid_id):
            z_min = solid_z_min(self._solids[index])
            for record in downward_faces(self._solids[index]):
                on_plate = (
                    not record.sampled
                    and abs(-record.normal[2] - 1.0) <= _PLATE_EPS_MM
                    and abs(record.point[2] - z_min) <= _PLATE_EPS_MM
                )
                out.append(
                    Overhang(
                        ref=self._face_handle(index, record.index),
                        angle_deg=record.angle_deg,
                        normal=record.normal,
                        center=record.point,
                        area=record.area,
                        on_build_plate=on_plate,
                        sampled=record.sampled,
                    )
                )
        return tuple(out)

    # -- reporting ---------------------------------------------------------

    def report(
        self,
        message: str,
        *,
        refs: Iterable[TopologyHandle] = (),
        tags: Iterable[str] = (),
        measured: JSONValue = None,
        suggested_bound: float | None = None,
    ) -> None:
        """Record one violation.

        ``refs`` are the offending topologies — each becomes an artifact-bound
        descriptor, and any tag carried by one is added to the finding's tag
        list automatically, so the offending tags are never forgotten.
        """
        if not message:
            raise ValidationError("a DFM finding needs a non-empty message", kind="contract")
        handles = tuple(refs)
        descriptors = tuple(handle.descriptor() for handle in handles)
        named = {tag for tag in tags if tag} | {
            handle.tag for handle in handles if handle.tag is not None
        }
        bound = None if suggested_bound is None else float(suggested_bound)
        if bound is not None and not math.isfinite(bound):
            raise ValidationError("suggested_bound must be finite", kind="contract")
        self._findings.append(
            RawFinding(
                message=message,
                tags=tuple(sorted(named)),
                topology=descriptors,
                measured=measured,
                suggested_bound=bound,
            )
        )

    def collected(self) -> tuple[RawFinding, ...]:
        """Everything the predicate reported, in report order."""
        return tuple(self._findings)


def build_context(
    *,
    part: str,
    process: str,
    source_artifact_ref: str,
    geometry: object,
    params: Mapping[str, float],
    metadata: Mapping[str, str],
    material: Mapping[str, JSONValue] | None,
    tags: Mapping[str, TopologyDescriptor],
) -> DfmContext:
    """Construct the per-rule evaluation context (worker side)."""
    return DfmContext(
        part=part,
        process=process,
        source_artifact_ref=source_artifact_ref,
        geometry=geometry,
        params=params,
        metadata=metadata,
        material=material,
        tags=tags,
    )
