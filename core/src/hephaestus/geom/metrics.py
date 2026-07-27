# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
# ^ OCP/build123d bindings are untyped at the member level. These four rules
#   were relaxed for this module by the `core/src/hephaestus/core/kernel`
#   pyright executionEnvironment before the move to `hephaestus.geom`; the
#   relaxation is pinned per-file here so it stays scoped to the modules that
#   touch the kernel bindings and does not leak to the rest of the package.
"""Geometry metrics service: pure functions over built build123d geometry.

``metrics(shape)`` produces the §8 :class:`~hephaestus.core.types.Metrics`
record (bbox, volume, area, solid/face/edge counts, ``sealed``, ``genus``).
This module also builds the addressing-layer
:class:`~hephaestus.core.addressing.GeometryIndex` from a labeled part
compound so selectors resolve against real geometry.

Genus limits (documented, by design):

- ``genus`` is computed from the Euler characteristic of each **closed**
  shell: ``chi = V - E + F - H`` where ``V``/``E``/``F`` are the shell's
  unique vertices, non-degenerate unique edges, and faces, and ``H`` is the
  total count of inner (hole) wires across faces — a face with ``k`` wires
  contributes ``2 - k`` to ``chi``. Per closed shell, ``genus = (2 - chi)
  // 2``; the shape's genus is the sum over its closed shells (a solid with
  an internal cavity therefore reports the sum of its boundary shells'
  genera). Open shells contribute nothing.
- The value is only meaningful when the shape is ``sealed``; on unsealed
  geometry the closed-shell sum is still returned but makes no topological
  claim about the open parts.
- Degenerate edges (e.g. sphere pole seams) are skipped, matching OCCT's
  own manifoldness bookkeeping. Non-orientable or self-intersecting shells
  are outside the model; for them the Euler formula may yield an odd
  ``2 - chi``, which floor-divides (never raises).

``sealed`` means: the shape contains at least one solid, every shell in the
shape is closed, and every non-degenerate edge is used by exactly two face
occurrences. Edge use is counted with seam multiplicity (OCCT
``MapShapesAndAncestors``, which records a face twice when an edge appears
twice in it) so periodic closed surfaces — sphere, torus, cylinder side —
count correctly where build123d 0.11's ``is_manifold`` (distinct-face count)
falsely reports a lone sphere as open. A stray open face or shell anywhere
in the compound makes the whole shape unsealed.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, TypeAlias, cast

from build123d.topology import Shape
from hephaestus.core.addressing import GeometryIndex
from hephaestus.core.types import Metrics
from OCP.BRep import BRep_Tool  # pyright: ignore[reportAttributeAccessIssue]
from OCP.TopAbs import TopAbs_ShapeEnum  # pyright: ignore[reportAttributeAccessIssue]
from OCP.TopExp import TopExp  # pyright: ignore[reportAttributeAccessIssue]
from OCP.TopoDS import TopoDS  # pyright: ignore[reportAttributeAccessIssue]
from OCP.TopTools import (
    TopTools_IndexedDataMapOfShapeListOfShape,  # pyright: ignore[reportAttributeAccessIssue]
)

#: Any build123d shape (solid, compound, shell, face, edge...). build123d's
#: ``Shape`` is generic over its wrapped TopoDS type; kernel services accept
#: them all.
AnyShape: TypeAlias = Shape[Any]

__all__ = [
    "AnyShape",
    "bbox_mm",
    "genus",
    "geometry_index",
    "is_sealed",
    "labeled_nodes",
    "metrics",
    "shape_volume",
]


def shape_volume(shape: AnyShape) -> float:
    """Enclosed volume (mm³) of a shape; 0.0 for faces/edges/wires."""
    return float(cast(Any, shape).volume)


def bbox_mm(shape: AnyShape) -> tuple[float, float, float]:
    """Axis-aligned bounding-box size ``(x, y, z)`` in mm."""
    size = shape.bounding_box().size
    return (float(size.X), float(size.Y), float(size.Z))


def _shell_closed(shell: AnyShape) -> bool:
    return bool(BRep_Tool.IsClosed_s(shell.wrapped))


def _every_edge_two_face_uses(shape: AnyShape) -> bool:
    """Every non-degenerate edge has exactly two face uses (seam-aware)."""
    amap = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(
        shape.wrapped,
        TopAbs_ShapeEnum.TopAbs_EDGE,
        TopAbs_ShapeEnum.TopAbs_FACE,
        amap,
    )
    for i in range(1, amap.Extent() + 1):
        edge = TopoDS.Edge_s(amap.FindKey(i))
        if BRep_Tool.Degenerated_s(edge):
            continue
        if amap.FindFromIndex(i).Size() != 2:
            return False
    return True


def is_sealed(shape: AnyShape) -> bool:
    """True when the shape is watertight (see module docstring for the rule)."""
    if not shape.solids():
        return False
    shells = shape.shells()
    if not shells:
        return False
    if not all(_shell_closed(s) for s in shells):
        return False
    return _every_edge_two_face_uses(shape)


def _shell_genus(shell: AnyShape) -> int | None:
    """Genus of one shell via Euler characteristic; None when the shell is open."""
    if not _shell_closed(shell):
        return None
    faces = shell.faces()
    edges = [e for e in shell.edges() if not BRep_Tool.Degenerated_s(e.wrapped)]
    vertices = shell.vertices()
    inner_wires = sum(len(f.wires()) - 1 for f in faces)
    chi = len(vertices) - len(edges) + len(faces) - inner_wires
    return (2 - chi) // 2


def genus(shape: AnyShape) -> int:
    """Sum of per-closed-shell genera (module docstring documents the limits)."""
    total = 0
    for shell in shape.shells():
        g = _shell_genus(shell)
        if g is not None:
            total += g
    return total


def metrics(shape: AnyShape) -> Metrics:
    """Full §8 metrics record for a built shape or compound.

    Deterministic: the same shape yields metric values stable to 1e-6 mm
    across processes (contract-tested). ``edges`` and ``area_mm2`` are the
    optional extended fields of :class:`Metrics` and are always populated
    here; drop them (``edges=None, area_mm2=None``) for exact-§8 output.
    """
    return Metrics(
        solids=len(shape.solids()),
        faces=len(shape.faces()),
        bbox_mm=bbox_mm(shape),
        volume_mm3=shape_volume(shape),
        sealed=is_sealed(shape),
        genus=genus(shape),
        edges=len(shape.edges()),
        area_mm2=float(shape.area),
    )


def labeled_nodes(shape: AnyShape) -> tuple[tuple[str, AnyShape], ...]:
    """Every labeled node of the geometry tree, pre-order (deterministic).

    Walks the anytree children of ``shape`` (the root included) depth-first
    in child order and collects ``(label, node)`` for every node with a
    non-empty ``.label``. Duplicates are preserved in tree order — the i-th
    entry is exactly what a label-kind ``Resolution`` occurrence index ``i``
    (into ``GeometryIndex.labels``) addresses, so callers map resolutions
    back to concrete shapes by indexing this tuple.
    """
    out: list[tuple[str, AnyShape]] = []

    def walk(node: AnyShape) -> None:
        label = node.label
        if label:
            out.append((label, node))
        for child in node.children:
            walk(child)

    walk(shape)
    return tuple(out)


def geometry_index(
    shape: AnyShape,
    *,
    bindings: Mapping[str, int] | None = None,
    tags: Iterable[str] = (),
) -> GeometryIndex:
    """Build the addressing :class:`GeometryIndex` for a built part compound.

    ``labels`` are the tree-order labels from :func:`labeled_nodes` (raw,
    duplicates meaningful — addressing dedups for display). ``bindings``
    (source-map binding name -> element count) and ``tags`` come from the
    executor; the kernel contributes the geometry-tree label set.
    """
    labels = tuple(label for label, _ in labeled_nodes(shape))
    return GeometryIndex(
        labels=labels,
        bindings=dict(bindings) if bindings is not None else {},
        tags=frozenset(tags),
    )
