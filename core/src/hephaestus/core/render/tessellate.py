"""Deterministic OCP -> per-solid triangle/edge tessellation (arch §3.3).

Meshes a built build123d/OCP shape into structured geometry that preserves
topology so the render passes can colour by selectable occurrence:

- solids enumerate in ``shape.solids()`` order (solid index ``s``);
- within a solid, faces enumerate in ``solid.faces()`` order (face index ``f``)
  and edges in ``solid.edges()`` order (edge index ``e``);

which is **exactly** the indexing
:func:`hephaestus.core.executor.tags.resolve_placements` uses, so a tag placed
at ``(solid s, topology index t)`` addresses the same face/edge group here, and
the per-solid counts agree with :func:`hephaestus.geom.metrics.metrics`.

Tessellation deflection is fixed by the module constants below (linear in mm,
angular in radians). They are part of the determinism contract and the golden
provenance: the same shape tessellates to byte-identical vertex/triangle arrays
across processes, and changing a constant invalidates render goldens.
"""

# trimesh ships no type stubs; the OCP reportUnknown* relaxations are declared
# for this package in root pyproject executionEnvironments (see interface notes).
# pyright: reportMissingTypeStubs=false

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray
from OCP.BRep import BRep_Tool  # pyright: ignore[reportAttributeAccessIssue]
from OCP.BRepAdaptor import BRepAdaptor_Curve  # pyright: ignore[reportAttributeAccessIssue]
from OCP.BRepMesh import BRepMesh_IncrementalMesh  # pyright: ignore[reportAttributeAccessIssue]
from OCP.GCPnts import GCPnts_QuasiUniformDeflection  # pyright: ignore[reportAttributeAccessIssue]
from OCP.TopAbs import TopAbs_Orientation  # pyright: ignore[reportAttributeAccessIssue]
from OCP.TopLoc import TopLoc_Location  # pyright: ignore[reportAttributeAccessIssue]

__all__ = [
    "ANGULAR_DEFLECTION",
    "LINEAR_DEFLECTION",
    "EdgeTessellation",
    "FaceTessellation",
    "SolidTessellation",
    "Tessellation",
    "face_trimesh",
    "tessellate",
]

#: Linear tessellation deflection in mm (max chord deviation). Determinism +
#: golden constant.
LINEAR_DEFLECTION = 0.1
#: Angular tessellation deflection in radians. Determinism + golden constant.
ANGULAR_DEFLECTION = 0.5


@dataclass(frozen=True, eq=False)
class FaceTessellation:
    """One face's triangle group with its stable topology index."""

    solid_index: int
    face_index: int
    vertices: NDArray[np.float64]  # (n, 3)
    triangles: NDArray[np.int64]  # (m, 3) indices into ``vertices``


@dataclass(frozen=True, eq=False)
class EdgeTessellation:
    """One edge's polyline with its stable topology index."""

    solid_index: int
    edge_index: int
    points: NDArray[np.float64]  # (k, 3), k >= 2


@dataclass(frozen=True, eq=False)
class SolidTessellation:
    """All face groups and edge polylines of one solid, in topology order."""

    solid_index: int
    faces: tuple[FaceTessellation, ...]
    edges: tuple[EdgeTessellation, ...]


@dataclass(frozen=True, eq=False)
class Tessellation:
    """A whole shape's tessellation, solids in ``shape.solids()`` order."""

    solids: tuple[SolidTessellation, ...]

    def face(self, solid_index: int, face_index: int) -> FaceTessellation:
        """The face group at ``(solid_index, face_index)``."""
        return self.solids[solid_index].faces[face_index]

    def edge(self, solid_index: int, edge_index: int) -> EdgeTessellation:
        """The edge polyline at ``(solid_index, edge_index)``."""
        return self.solids[solid_index].edges[edge_index]

    def bounds(self) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        """Axis-aligned ``(min, max)`` over every tessellated vertex."""
        mins: list[NDArray[np.float64]] = []
        maxs: list[NDArray[np.float64]] = []
        for solid in self.solids:
            for face in solid.faces:
                if face.vertices.size:
                    mins.append(face.vertices.min(axis=0))
                    maxs.append(face.vertices.max(axis=0))
            for edge in solid.edges:
                if edge.points.size:
                    mins.append(edge.points.min(axis=0))
                    maxs.append(edge.points.max(axis=0))
        if not mins:
            return ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
        lo = np.min(np.vstack(mins), axis=0)
        hi = np.max(np.vstack(maxs), axis=0)
        return (
            (float(lo[0]), float(lo[1]), float(lo[2])),
            (float(hi[0]), float(hi[1]), float(hi[2])),
        )


def _face_tessellation(face: Any, solid_index: int, face_index: int) -> FaceTessellation:
    location = TopLoc_Location()
    triangulation = BRep_Tool.Triangulation_s(face.wrapped, location)
    if triangulation is None:
        return FaceTessellation(
            solid_index=solid_index,
            face_index=face_index,
            vertices=np.zeros((0, 3), dtype=np.float64),
            triangles=np.zeros((0, 3), dtype=np.int64),
        )
    transform = location.Transformation()
    node_count = triangulation.NbNodes()
    vertices = np.empty((node_count, 3), dtype=np.float64)
    for i in range(1, node_count + 1):
        point = triangulation.Node(i).Transformed(transform)
        vertices[i - 1] = (point.X(), point.Y(), point.Z())
    reversed_face = face.wrapped.Orientation() == TopAbs_Orientation.TopAbs_REVERSED
    triangle_count = triangulation.NbTriangles()
    triangles = np.empty((triangle_count, 3), dtype=np.int64)
    for i in range(1, triangle_count + 1):
        a, b, c = triangulation.Triangle(i).Get()
        if reversed_face:
            a, c = c, a
        triangles[i - 1] = (a - 1, b - 1, c - 1)
    return FaceTessellation(
        solid_index=solid_index,
        face_index=face_index,
        vertices=vertices,
        triangles=triangles,
    )


def _edge_tessellation(
    edge: Any, solid_index: int, edge_index: int, linear: float
) -> EdgeTessellation:
    curve = BRepAdaptor_Curve(edge.wrapped)
    sampler = GCPnts_QuasiUniformDeflection(curve, linear)
    count = sampler.NbPoints() if sampler.IsDone() else 0
    if count < 2:
        # Fall back to the parametric endpoints so every edge is a real segment.
        first = curve.FirstParameter()
        last = curve.LastParameter()
        params = [first, last]
    else:
        params = [sampler.Parameter(i) for i in range(1, count + 1)]
    points = np.empty((len(params), 3), dtype=np.float64)
    for i, parameter in enumerate(params):
        point = curve.Value(parameter)
        points[i] = (point.X(), point.Y(), point.Z())
    return EdgeTessellation(solid_index=solid_index, edge_index=edge_index, points=points)


def tessellate(
    shape: Any,
    *,
    linear: float = LINEAR_DEFLECTION,
    angular: float = ANGULAR_DEFLECTION,
) -> Tessellation:
    """Tessellate ``shape`` into per-solid face groups and edge polylines.

    ``shape`` is any built build123d shape/compound. Solids, faces, and edges
    enumerate in the same order as the executor tag/source-map layer and the
    kernel metrics, so topology indices are shared across the whole engine.
    """
    solids: list[SolidTessellation] = []
    for solid_index, solid in enumerate(shape.solids()):
        # Mesh the whole solid once; per-face triangulations are then read back.
        BRepMesh_IncrementalMesh(solid.wrapped, linear, False, angular, True)
        faces = tuple(
            _face_tessellation(face, solid_index, face_index)
            for face_index, face in enumerate(solid.faces())
        )
        edges = tuple(
            _edge_tessellation(edge, solid_index, edge_index, linear)
            for edge_index, edge in enumerate(solid.edges())
        )
        solids.append(SolidTessellation(solid_index=solid_index, faces=faces, edges=edges))
    return Tessellation(solids=tuple(solids))


def face_trimesh(face: FaceTessellation) -> Any:
    """Build a processed-free ``trimesh.Trimesh`` for one face group.

    Kept lazy (``trimesh`` imported on call) so importing the tessellation
    layer does not pull the renderer stack.
    """
    import trimesh

    return trimesh.Trimesh(vertices=face.vertices, faces=face.triangles, process=False)
