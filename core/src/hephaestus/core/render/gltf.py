"""GLTF (GLB) export with embedded selection IDs bound to a bundle (arch §3.3).

Exports a built compound as a self-contained binary glTF (``.glb``) in which the
selection namespace of :mod:`hephaestus.core.render.selection` is carried on the
geometry so a client raycast resolves the same IDs as the mask passes:

- one **mesh per solid** (``len(meshes) == solid count`` — a Gate G1 assertion),
  the mesh ``extras`` carrying the solid's selection ID/descriptor **and its
  ``explode_offset``** (``INTERFACE.md`` §5.1);
- one **primitive per face** inside its solid's mesh, the primitive ``extras``
  carrying that ``(solid, face)`` selection ID;
- the immutable **linked selection bundle ref** (plus source build + table refs)
  in ``asset.extras``.

``extras.explode_offset`` is the float3 displacement at ``t = 1`` —
:func:`hephaestus.core.render.channels._explode_offset` with ``t=1.0``, called
rather than reimplemented (``INTERFACE.md`` §5.1 makes that literal). The client
translates a solid's node by ``explode_offset · t`` and computes nothing else: it
does not take centroids, does not normalize, and does not reconstruct a
magnitude, because §1's closed list makes every one of those a server number. A
server-side pytest asserts the byte-equivalence of ``offset · t`` and
``_explode_offset(scene, solid, t)`` for every solid and several ``t`` — without
it the viewport and ``heph render --explode`` drift silently.

**No glTF extension is introduced.** Everything needed rides in ``extras``; an
extension would drag a new artifact into the ``tool_schema.md`` ↔ JSON-Schema ↔
TypeBox ↔ MCP drift suite for no capability.

A raycast hit (mesh index, optional primitive index) is resolved **only through
that linked bundle**: :func:`resolve_gltf_pick` reads the hit's embedded ID, then
resolves the bundle via :func:`hephaestus.core.render.bundle.resolve_selection`
and returns the table entry — so a stale/expired/mismatched bundle yields a
structured ``stale_selection`` exactly as the mask path does, and the GLTF can
never authorize a selection its bundle no longer backs.

:func:`validate_gltf` covers the gate's structural assertions (parse, accessor/
bufferView bounds, mesh-count == solid-count). The Khronos ``gltf-validator``
binary is a separate, non-Python tool; this validator asserts the structural
invariants the gate names without requiring it.
"""

# pygltflib ships no type stubs; the Unknown* relaxations are declared for this
# whole package in root pyproject executionEnvironments (render dir). See notes.
# pyright: reportMissingTypeStubs=false

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

import numpy as np
from hephaestus.core.errors import ValidationError
from hephaestus.core.render.bundle import StaleSelection, StaleSelectionError, resolve_selection
from hephaestus.core.render.channels import RenderScene, _explode_offset, scene_from_shape
from hephaestus.core.render.palette import SelectionEntry, id_to_rgb
from hephaestus.core.render.selection import SelectionCatalog
from hephaestus.core.render.tessellate import Tessellation
from opstore.types import JSONValue

from opstore import OpStore

__all__ = [
    "BUNDLE_REF_KEY",
    "EXPLODE_OFFSET_KEY",
    "SOURCE_REF_KEY",
    "TABLE_REF_KEY",
    "GltfValidation",
    "export_gltf",
    "resolve_gltf_pick",
    "validate_gltf",
]

#: ``asset.extras`` keys binding the GLTF to its immutable selection bundle.
BUNDLE_REF_KEY = "selection_bundle_ref"
SOURCE_REF_KEY = "source_artifact_ref"
TABLE_REF_KEY = "selection_table_ref"

#: Per-**mesh** ``extras`` key carrying the solid's explode displacement at
#: ``t = 1`` (``INTERFACE.md`` §5.1). A float3, in the model's own units and
#: coordinate frame — the same frame the baked vertices are in — so the client's
#: node translation is ``explode_offset · t`` and nothing more.
EXPLODE_OFFSET_KEY = "explode_offset"

# glTF componentType / accessor-type constants and their byte/element sizes.
_COMPONENT_FLOAT = 5126
_COMPONENT_UINT = 5125
_TARGET_ARRAY_BUFFER = 34962
_TARGET_ELEMENT_ARRAY_BUFFER = 34963
_MODE_TRIANGLES = 4
_COMPONENT_BYTES: dict[int, int] = {_COMPONENT_FLOAT: 4, _COMPONENT_UINT: 4}
_TYPE_ELEMENTS: dict[str, int] = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


@dataclass(frozen=True)
class GltfValidation:
    """Structural summary of a parsed GLB (see :func:`validate_gltf`)."""

    mesh_count: int
    primitive_count: int
    accessor_count: int
    buffer_length: int
    bundle_ref: str | None
    source_artifact_ref: str | None
    #: Per-mesh ``extras.explode_offset``, in mesh order (§5.1). Every mesh has
    #: one or :func:`validate_gltf` refuses the GLB, so this is always as long as
    #: ``mesh_count``.
    explode_offsets: tuple[tuple[float, float, float], ...] = ()


def export_gltf(
    shape: Any,
    catalog: SelectionCatalog,
    *,
    bundle_ref: str,
    source_artifact_ref: str,
    selection_table_ref: str,
    tess: Tessellation | None = None,
    labels: Mapping[int, str] | None = None,
    scene: RenderScene | None = None,
) -> bytes:
    """Export ``shape`` as a GLB with selection IDs bound to ``bundle_ref``.

    Vertices are baked in world coordinates (identity node transforms), coloured
    per solid by the solid's palette colour. ``catalog`` supplies the global IDs
    embedded in mesh/primitive ``extras``; they match the bundle's selection
    table exactly. Each mesh also carries :data:`EXPLODE_OFFSET_KEY`, the float3
    ``_explode_offset(scene, solid, t=1.0)`` (§5.1). Deterministic: same
    tessellation + catalog => same bytes.

    ``scene`` is the :class:`~hephaestus.core.render.channels.RenderScene` the
    explode displacements are taken from; pass one to avoid a second meshing of
    ``shape`` (a caller that already built a scene has already paid for it). Omit
    it and one is built here. ``tess`` still wins for the geometry itself, so an
    existing caller's tessellation is never re-derived.
    """
    from pygltflib import (
        GLTF2,
        Accessor,
        Asset,
        Attributes,
        Buffer,
        BufferView,
        Material,
        Mesh,
        Node,
        PbrMetallicRoughness,
        Primitive,
        Scene,
    )

    render_scene = scene if scene is not None else scene_from_shape(shape)
    meshed = (
        tess
        if tess is not None
        else Tessellation(solids=tuple(s.tessellation for s in render_scene.solids))
    )
    label_of = dict(labels) if labels is not None else {}
    # One lookup per solid index: the scene's solid order *is* ``shape.solids()``
    # order, the same order the catalog and the tag layer index by, but a dict
    # keyed by ``solid_index`` says so instead of relying on position.
    scene_solids = {s.solid_index: s for s in render_scene.solids}

    blob = bytearray()
    accessors: list[Any] = []
    buffer_views: list[Any] = []
    meshes: list[Any] = []
    materials: list[Any] = []
    nodes: list[Any] = []

    def _add_accessor(data: np.ndarray[Any, Any], *, component: int, kind: str, target: int) -> int:
        raw = data.tobytes()
        view_index = len(buffer_views)
        buffer_views.append(
            BufferView(buffer=0, byteOffset=len(blob), byteLength=len(raw), target=target)
        )
        blob.extend(raw)
        elements = _TYPE_ELEMENTS[kind]
        count = data.size // elements
        # glTF requires accessor min/max on POSITION; leave them off integer
        # index accessors (optional, and avoids int-as-float serialisation).
        minimum: list[float] | None = None
        maximum: list[float] | None = None
        if kind != "SCALAR" and data.size:
            reshaped = data.reshape(-1, elements)
            minimum = [float(x) for x in reshaped.min(axis=0)]
            maximum = [float(x) for x in reshaped.max(axis=0)]
        accessor_index = len(accessors)
        accessors.append(
            Accessor(
                bufferView=view_index,
                byteOffset=0,
                componentType=component,
                count=count,
                type=kind,
                min=minimum,
                max=maximum,
            )
        )
        return accessor_index

    for solid in meshed.solids:
        s = solid.solid_index
        solid_id = catalog.solid_ids[s]
        colour = id_to_rgb(solid_id)
        materials.append(
            Material(
                name=f"solid_{s}",
                pbrMetallicRoughness=PbrMetallicRoughness(
                    baseColorFactor=[colour[0] / 255, colour[1] / 255, colour[2] / 255, 1.0],
                    metallicFactor=0.0,
                    roughnessFactor=1.0,
                ),
            )
        )
        material_index = len(materials) - 1
        label = label_of.get(s)
        primitives: list[Any] = []
        for face in solid.faces:
            if face.triangles.shape[0] == 0 or face.vertices.shape[0] == 0:
                continue
            f = face.face_index
            face_id = catalog.face_ids[(s, f)]
            positions = np.ascontiguousarray(face.vertices, dtype=np.float32)
            indices = np.ascontiguousarray(face.triangles.reshape(-1), dtype=np.uint32)
            position_accessor = _add_accessor(
                positions, component=_COMPONENT_FLOAT, kind="VEC3", target=_TARGET_ARRAY_BUFFER
            )
            index_accessor = _add_accessor(
                indices,
                component=_COMPONENT_UINT,
                kind="SCALAR",
                target=_TARGET_ELEMENT_ARRAY_BUFFER,
            )
            primitives.append(
                Primitive(
                    attributes=Attributes(POSITION=position_accessor),
                    indices=index_accessor,
                    material=material_index,
                    mode=_MODE_TRIANGLES,
                    extras={
                        "selection_id": face_id,
                        "kind": "face",
                        "solid_index": s,
                        "face_index": f,
                    },
                )
            )
        scene_solid = scene_solids.get(s)
        if scene_solid is None:  # pragma: no cover - a tess/scene mismatch
            raise ValidationError(
                f"solid {s} is in the tessellation but not in the render scene", kind="contract"
            )
        offset = _explode_offset(render_scene, scene_solid, 1.0)
        mesh_extras: dict[str, JSONValue] = {
            "selection_id": solid_id,
            "kind": "solid",
            "solid_index": s,
            # §5.1: the displacement vector at t = 1, NOT a unit axis plus a
            # scalar. §5.2 states why: the transform is a homothety about the
            # assembly centroid, and a unit axis with the only `explode_scale`
            # that exists (the global 1.0) moves every solid the same distance —
            # a different transform that can fail G4.6 outright.
            EXPLODE_OFFSET_KEY: [float(offset[0]), float(offset[1]), float(offset[2])],
        }
        if label is not None:
            mesh_extras["label"] = label
        meshes.append(Mesh(primitives=primitives, extras=mesh_extras, name=label or f"solid_{s}"))
        nodes.append(Node(mesh=len(meshes) - 1))

    gltf = GLTF2()
    gltf.asset = Asset(
        version="2.0",
        generator="hephaestus.core.render.gltf",
        extras={
            BUNDLE_REF_KEY: bundle_ref,
            SOURCE_REF_KEY: source_artifact_ref,
            TABLE_REF_KEY: selection_table_ref,
        },
    )
    gltf.scenes = [Scene(nodes=list(range(len(nodes))))]
    gltf.scene = 0
    gltf.nodes = nodes
    gltf.meshes = meshes
    gltf.materials = materials
    gltf.accessors = accessors
    gltf.bufferViews = buffer_views
    gltf.buffers = [Buffer(byteLength=len(blob))]
    gltf.set_binary_blob(bytes(blob))
    return b"".join(gltf.save_to_bytes())


def _load(data: bytes) -> Any:
    from pygltflib import GLTF2

    try:
        return GLTF2.load_from_bytes(data)
    except Exception as exc:
        raise ValidationError(f"could not parse GLB: {exc}", kind="contract") from exc


def validate_gltf(data: bytes, *, expected_solid_count: int | None = None) -> GltfValidation:
    """Structurally validate a GLB and return its :class:`GltfValidation`.

    Asserts the gate invariants: it parses, every bufferView lies within its
    buffer, every accessor's elements fit within its bufferView, and — when
    ``expected_solid_count`` is given — the mesh count equals the solid count.
    Raises ``validation_error`` on any structural violation.
    """
    gltf = _load(data)
    blob = gltf.binary_blob() or b""
    buffer_length = len(blob)
    buffers = gltf.buffers or []
    if not buffers:
        raise ValidationError("GLB has no buffer", kind="contract")
    declared = int(buffers[0].byteLength)
    if declared > buffer_length:
        raise ValidationError(
            f"buffer byteLength {declared} exceeds embedded blob {buffer_length}", kind="contract"
        )

    buffer_views = gltf.bufferViews or []
    for i, view in enumerate(buffer_views):
        if view.buffer != 0:
            raise ValidationError(
                f"bufferView {i} references buffer {view.buffer}", kind="contract"
            )
        offset = int(view.byteOffset or 0)
        end = offset + int(view.byteLength)
        if offset < 0 or end > buffer_length:
            raise ValidationError(
                f"bufferView {i} range [{offset}, {end}) escapes buffer of {buffer_length}",
                kind="contract",
            )

    accessors = gltf.accessors or []
    for i, accessor in enumerate(accessors):
        if accessor.bufferView is None or not 0 <= accessor.bufferView < len(buffer_views):
            raise ValidationError(f"accessor {i} has no valid bufferView", kind="contract")
        component_bytes = _COMPONENT_BYTES.get(int(accessor.componentType))
        elements = _TYPE_ELEMENTS.get(str(accessor.type))
        if component_bytes is None or elements is None:
            raise ValidationError(
                f"accessor {i} has unsupported component/type "
                f"{accessor.componentType}/{accessor.type}",
                kind="contract",
            )
        needed = int(accessor.count) * component_bytes * elements
        view = buffer_views[accessor.bufferView]
        available = int(view.byteLength) - int(accessor.byteOffset or 0)
        if needed > available:
            raise ValidationError(
                f"accessor {i} needs {needed} bytes but bufferView {accessor.bufferView} "
                f"offers {available}",
                kind="contract",
            )

    meshes = gltf.meshes or []
    mesh_count = len(meshes)
    primitive_count = sum(len(mesh.primitives or []) for mesh in meshes)
    if expected_solid_count is not None and mesh_count != expected_solid_count:
        raise ValidationError(
            f"mesh count {mesh_count} != solid count {expected_solid_count}", kind="contract"
        )

    offsets = tuple(_mesh_explode_offset(mesh.extras, i) for i, mesh in enumerate(meshes))

    extras = cast("Mapping[str, JSONValue]", gltf.asset.extras or {})
    bundle_ref = extras.get(BUNDLE_REF_KEY)
    source_ref = extras.get(SOURCE_REF_KEY)
    return GltfValidation(
        mesh_count=mesh_count,
        primitive_count=primitive_count,
        accessor_count=len(accessors),
        buffer_length=buffer_length,
        bundle_ref=bundle_ref if isinstance(bundle_ref, str) else None,
        source_artifact_ref=source_ref if isinstance(source_ref, str) else None,
        explode_offsets=offsets,
    )


def _mesh_explode_offset(extras: object, mesh_index: int) -> tuple[float, float, float]:
    """One mesh's ``extras.explode_offset``, or ``validation_error`` (§5.1).

    Structural, not optional: a GLB whose meshes carry no displacement leaves the
    client with nothing to translate by and no legal way to derive one (§1's
    closed list forbids it computing centroids), so the absence is a malformed
    GLB rather than a feature the viewport degrades around.
    """
    if not isinstance(extras, Mapping):
        raise ValidationError(f"mesh {mesh_index} carries no extras", kind="contract")
    raw = cast("Mapping[str, JSONValue]", extras).get(EXPLODE_OFFSET_KEY)
    if not isinstance(raw, list) or len(cast("list[JSONValue]", raw)) != 3:
        raise ValidationError(
            f"mesh {mesh_index} has no float3 {EXPLODE_OFFSET_KEY}", kind="contract"
        )
    values = cast("list[JSONValue]", raw)
    out: list[float] = []
    for component in values:
        if isinstance(component, bool) or not isinstance(component, (int, float)):
            raise ValidationError(
                f"mesh {mesh_index} {EXPLODE_OFFSET_KEY} component is not a number",
                kind="contract",
            )
        out.append(float(component))
    return (out[0], out[1], out[2])


def _embedded_id(extras: object, ref: str) -> int:
    if not isinstance(extras, Mapping):
        raise StaleSelectionError(
            StaleSelection("malformed", ref, "picked geometry carries no selection extras")
        )
    value = cast("Mapping[str, JSONValue]", extras).get("selection_id")
    if not isinstance(value, int) or isinstance(value, bool):
        raise StaleSelectionError(
            StaleSelection("malformed", ref, "picked geometry has no integer selection_id")
        )
    return value


def resolve_gltf_pick(
    store: OpStore,
    data: bytes,
    mesh_index: int,
    primitive_index: int | None = None,
    *,
    expected_source_artifact_ref: str | None = None,
) -> SelectionEntry:
    """Resolve a GLTF raycast hit to its table entry **through the linked bundle**.

    ``mesh_index`` (a solid) with no ``primitive_index`` resolves the solid's ID;
    with ``primitive_index`` it resolves that face's ID. The embedded ID is
    looked up in the selection table obtained by resolving the GLB's linked
    bundle ref, so a stale/expired/mismatched bundle raises
    :class:`~hephaestus.core.render.bundle.StaleSelectionError` — the GLTF alone
    never authorizes a selection.
    """
    gltf = _load(data)
    extras = cast("Mapping[str, JSONValue]", gltf.asset.extras or {})
    bundle_ref = extras.get(BUNDLE_REF_KEY)
    if not isinstance(bundle_ref, str):
        raise StaleSelectionError(
            StaleSelection(
                "malformed", "<gltf>", "GLB asset carries no linked selection bundle ref"
            )
        )

    meshes = gltf.meshes or []
    if not 0 <= mesh_index < len(meshes):
        raise StaleSelectionError(
            StaleSelection("malformed", bundle_ref, f"mesh index {mesh_index} out of range")
        )
    mesh = meshes[mesh_index]
    if primitive_index is None:
        selection_id = _embedded_id(mesh.extras, bundle_ref)
    else:
        primitives = mesh.primitives or []
        if not 0 <= primitive_index < len(primitives):
            raise StaleSelectionError(
                StaleSelection(
                    "malformed", bundle_ref, f"primitive index {primitive_index} out of range"
                )
            )
        selection_id = _embedded_id(primitives[primitive_index].extras, bundle_ref)

    resolution = resolve_selection(
        store, bundle_ref, expected_source_artifact_ref=expected_source_artifact_ref
    )
    entry = resolution.entries.get(selection_id)
    if entry is None:
        raise StaleSelectionError(
            StaleSelection(
                "mismatched",
                bundle_ref,
                f"selection id {selection_id} is not in the linked bundle's table",
            )
        )
    return entry
