"""Selection-mode rendering: three palette-exact machine-ID passes (arch §3.3).

For one built compound this module assigns **one global selection-id namespace**
over every selectable topology occurrence — each solid, each ``(solid, face)``,
and each ``(solid, edge)`` — and renders, per view, three separate
non-antialiased ID passes plus one shared global selection table (tool_schema
``inspect_part`` / ``channel="mask", mask_mode="selection"``):

- **solid pass** — every face of a solid painted that solid's single ID colour;
- **face pass** — every face painted its own ``(solid, face)`` ID colour,
  including untagged faces;
- **edge pass** — every edge polyline drawn as an ID-coloured line over the
  neutral ``(0, 0, 0)`` background.

Pixels never mix kinds within a pass (each pass paints only its kind's IDs), so
:func:`hephaestus.core.render.palette.rgb_to_id` decodes a pass pixel straight to
a table ID. The table maps every ID to ``{kind, solid_index, topology_index,
tag/label, source build artifact_ref}`` and is published, with the three passes
and at most one non-decodable composite preview, as an immutable per-view
:class:`~hephaestus.core.render.bundle.SelectionBundle`.

Determinism. IDs are assigned in solid/face/edge topology order (shared with the
executor tag layer and kernel metrics); tessellation and the flat SEG passes are
byte-deterministic on the software rasterizer; PNGs are encoded with a fixed
metadata-free PIL encoder (:func:`encode_png`). Same build + view => byte-
identical pass PNGs on this platform tier.
"""

# pygltflib/pyrender/trimesh/PIL ship no type stubs; the Unknown* relaxations
# are declared for this whole package in root pyproject executionEnvironments
# (render dir), mirroring kernel/executor. See interface notes.
# pyright: reportMissingTypeStubs=false

from __future__ import annotations

import io
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from hephaestus.core.executor.tags import TagPlacement, TagRegistry, resolve_placements
from hephaestus.core.kernel.metrics import labeled_nodes
from hephaestus.core.render.bundle import RenderStore, SelectionBundle
from hephaestus.core.render.cameras import camera_framing, parse_view
from hephaestus.core.render.offscreen import (
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    ColoredMesh,
    OffscreenSession,
    line_mesh,
)
from hephaestus.core.render.palette import SelectionEntry, id_to_rgb
from hephaestus.core.render.tessellate import Tessellation, face_trimesh, tessellate
from numpy.typing import NDArray

from opstore import OpStore

__all__ = [
    "SelectionCatalog",
    "SelectionPassArrays",
    "build_selection_catalog",
    "encode_png",
    "publish_selection_bundles",
    "render_edge_pass",
    "render_face_pass",
    "render_preview",
    "render_selection_view",
    "render_solid_pass",
    "solid_labels",
]


@dataclass(frozen=True)
class SelectionCatalog:
    """The global selection-id assignment for one built compound.

    ``entries`` is the shared global table (ID -> descriptor) published verbatim
    into every per-view bundle. The lookup maps drive the three render passes:
    the solid pass colours by ``solid_ids[s]``, the face pass by
    ``face_ids[(s, f)]``, and the edge pass by ``edge_ids[(s, e)]``.
    """

    entries: dict[int, SelectionEntry]
    solid_ids: dict[int, int]
    face_ids: dict[tuple[int, int], int]
    edge_ids: dict[tuple[int, int], int]


@dataclass(frozen=True)
class SelectionPassArrays:
    """The raw ``(H, W, 3)`` uint8 ID passes for one view (pre-PNG-encoding).

    ``preview`` is the optional ``(H, W, 4)`` composite shaded RGBA render —
    human/model viewable and explicitly **not** palette-decodable.
    """

    solid: NDArray[np.uint8]
    face: NDArray[np.uint8]
    edge: NDArray[np.uint8]
    preview: NDArray[np.uint8] | None = None


def solid_labels(shape: Any) -> dict[int, str]:
    """Map each ``solids()`` index to its owning geometry-tree label (if any).

    Walks the labeled nodes (pre-order, root first) and matches each node's
    solids to the compound's ``solids()`` order by ``IsSame``; deeper (later,
    more specific) labels overwrite, so a leaf solid gets its own label rather
    than an enclosing compound's. Solids with no labeled ancestor are absent.
    """
    solids = list(shape.solids()) if hasattr(shape, "solids") else []
    labels: dict[int, str] = {}
    for label, node in labeled_nodes(shape):
        if not label:
            continue
        node_solids = list(node.solids()) if hasattr(node, "solids") else []
        for node_solid in node_solids:
            for index, solid in enumerate(solids):
                if solid.wrapped.IsSame(node_solid.wrapped):
                    labels[index] = label
    return labels


def _tag_by_placement(placements: Mapping[str, TagPlacement]) -> dict[tuple[str, int, int], str]:
    """Reverse the tag placements into ``(kind, solid, topo) -> tag name``.

    Placements whose topology was not located in the final compound
    (``solid_index``/``topo_index`` ``None``) are skipped — they colour no pass.
    """
    out: dict[tuple[str, int, int], str] = {}
    for name, placement in placements.items():
        if placement.solid_index is None or placement.topo_index is None:
            continue
        out[(placement.kind, placement.solid_index, placement.topo_index)] = name
    return out


def build_selection_catalog(
    tess: Tessellation,
    *,
    placements: Mapping[str, TagPlacement] = {},
    labels: Mapping[int, str] | None = None,
    start_id: int = 1,
) -> SelectionCatalog:
    """Assign one global selection ID to every solid/face/edge occurrence.

    IDs are handed out in ``solid, its faces, its edges`` order per solid, in
    ``tess.solids`` order — exactly the executor/kernel topology indexing — so
    the assignment is deterministic and shared across the engine. Each ID's
    :class:`SelectionEntry` carries the occurrence kind, its solid/topology
    index, any tag placed there, and the owning solid's label.
    """
    tag_at = _tag_by_placement(placements)
    label_of = dict(labels) if labels is not None else {}
    entries: dict[int, SelectionEntry] = {}
    solid_ids: dict[int, int] = {}
    face_ids: dict[tuple[int, int], int] = {}
    edge_ids: dict[tuple[int, int], int] = {}
    next_id = start_id
    for solid in tess.solids:
        s = solid.solid_index
        label = label_of.get(s)
        solid_ids[s] = next_id
        entries[next_id] = SelectionEntry(
            kind="solid",
            solid_index=s,
            topology_index=s,
            tag=tag_at.get(("solid", s, s)),
            label=label,
        )
        next_id += 1
        for face in solid.faces:
            f = face.face_index
            face_ids[(s, f)] = next_id
            entries[next_id] = SelectionEntry(
                kind="face",
                solid_index=s,
                topology_index=f,
                tag=tag_at.get(("face", s, f)),
                label=label,
            )
            next_id += 1
        for edge in solid.edges:
            e = edge.edge_index
            edge_ids[(s, e)] = next_id
            entries[next_id] = SelectionEntry(
                kind="edge",
                solid_index=s,
                topology_index=e,
                tag=tag_at.get(("edge", s, e)),
                label=label,
            )
            next_id += 1
    return SelectionCatalog(
        entries=entries, solid_ids=solid_ids, face_ids=face_ids, edge_ids=edge_ids
    )


def _face_meshes(
    tess: Tessellation, color_for: Callable[[int, int], tuple[int, int, int]]
) -> list[ColoredMesh]:
    items: list[ColoredMesh] = []
    for solid in tess.solids:
        for face in solid.faces:
            if face.triangles.shape[0] == 0:
                continue
            rgb = color_for(solid.solid_index, face.face_index)
            items.append(ColoredMesh(mesh=face_trimesh(face), rgb=rgb))
    return items


def render_solid_pass(
    session: OffscreenSession,
    tess: Tessellation,
    catalog: SelectionCatalog,
    framing: Any,
) -> NDArray[np.uint8]:
    """Flat pass painting every face of a solid that solid's single ID colour."""
    items = _face_meshes(tess, lambda s, _f: id_to_rgb(catalog.solid_ids[s]))
    return session.render_flat(items, framing)


def render_face_pass(
    session: OffscreenSession,
    tess: Tessellation,
    catalog: SelectionCatalog,
    framing: Any,
) -> NDArray[np.uint8]:
    """Flat pass painting every face its own ``(solid, face)`` ID colour."""
    items = _face_meshes(tess, lambda s, f: id_to_rgb(catalog.face_ids[(s, f)]))
    return session.render_flat(items, framing)


def render_edge_pass(
    session: OffscreenSession,
    tess: Tessellation,
    catalog: SelectionCatalog,
    framing: Any,
) -> NDArray[np.uint8]:
    """Flat line pass drawing every edge polyline its ``(solid, edge)`` ID colour."""
    items: list[ColoredMesh] = []
    for solid in tess.solids:
        for edge in solid.edges:
            if edge.points.shape[0] < 2:
                continue
            rgb = id_to_rgb(catalog.edge_ids[(solid.solid_index, edge.edge_index)])
            items.append(ColoredMesh(mesh=line_mesh(edge.points), rgb=rgb))
    return session.render_flat_lines(items, framing)


def render_preview(
    session: OffscreenSession,
    tess: Tessellation,
    framing: Any,
) -> NDArray[np.uint8]:
    """Composite shaded RGBA preview (human/model viewable, not decodable)."""
    meshes = [
        face_trimesh(face)
        for solid in tess.solids
        for face in solid.faces
        if face.triangles.shape[0] != 0
    ]
    return session.render_shaded(meshes, framing)


def render_selection_view(
    session: OffscreenSession,
    tess: Tessellation,
    catalog: SelectionCatalog,
    framing: Any,
    *,
    include_preview: bool = True,
) -> SelectionPassArrays:
    """Render the three ID passes (and optional preview) for one framed view."""
    return SelectionPassArrays(
        solid=render_solid_pass(session, tess, catalog, framing),
        face=render_face_pass(session, tess, catalog, framing),
        edge=render_edge_pass(session, tess, catalog, framing),
        preview=render_preview(session, tess, framing) if include_preview else None,
    )


def encode_png(array: NDArray[np.uint8]) -> bytes:
    """Encode an ``(H, W, 3|4)`` uint8 array as deterministic PNG bytes.

    Uses a fixed PIL encoder with no timestamp/text metadata and a fixed
    compression level, so byte-identical framebuffers yield byte-identical PNGs
    (the caller-side half of the render determinism contract).
    """
    from PIL import Image

    if array.ndim != 3 or array.shape[2] not in (3, 4):
        raise ValueError(f"expected an (H, W, 3|4) image, got shape {array.shape!r}")
    contiguous = np.ascontiguousarray(array, dtype=np.uint8)
    mode = "RGBA" if contiguous.shape[2] == 4 else "RGB"
    image = Image.fromarray(contiguous, mode=mode)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=False, compress_level=6)
    return buffer.getvalue()


def publish_selection_bundles(
    store: OpStore,
    shape: Any,
    *,
    source_artifact_ref: str,
    views: Sequence[str],
    tag_registry: TagRegistry | None = None,
    placements: Mapping[str, TagPlacement] | None = None,
    labels: Mapping[int, str] | None = None,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    include_preview: bool = True,
    session: OffscreenSession | None = None,
) -> list[SelectionBundle]:
    """Render + publish one immutable selection bundle per view for ``shape``.

    Builds one shared :class:`SelectionCatalog` (global ID namespace + table),
    then for each view renders the three ID passes and an optional composite
    preview and publishes them through
    :meth:`hephaestus.core.render.bundle.RenderStore.publish_selection_bundle`,
    binding every render to ``source_artifact_ref`` (the exact build the geometry
    came from). Pass an :class:`OffscreenSession` to reuse one GL context across
    many builds/views; otherwise one is created and closed here.
    """
    tess = tessellate(shape)
    if placements is None:
        placements = resolve_placements(tag_registry, shape) if tag_registry is not None else {}
    if labels is None:
        labels = solid_labels(shape)
    catalog = build_selection_catalog(tess, placements=placements, labels=labels)

    own_session = session is None
    active = session if session is not None else OffscreenSession(width, height)
    render_store = RenderStore(store)
    try:
        bounds = tess.bounds()
        bundles: list[SelectionBundle] = []
        for view in views:
            framing = camera_framing(
                *bounds, parse_view(view), width=active.width, height=active.height
            )
            arrays = render_selection_view(
                active, tess, catalog, framing, include_preview=include_preview
            )
            preview_png = encode_png(arrays.preview) if arrays.preview is not None else None
            bundle = render_store.publish_selection_bundle(
                view=view,
                source_artifact_ref=source_artifact_ref,
                solid_png=encode_png(arrays.solid),
                face_png=encode_png(arrays.face),
                edge_png=encode_png(arrays.edge),
                entries=catalog.entries,
                preview_png=preview_png,
            )
            bundles.append(bundle)
    finally:
        if own_session:
            active.close()
    return bundles
