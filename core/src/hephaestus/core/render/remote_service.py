"""Host store adapter for the explicit OCI renderer; no kernel or EGL imports.

The host resolves builds and owns publication/GC. Only a bounded BREP and closed
metadata cross the worker boundary. Unsupported native options refuse explicitly.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import struct
import zlib
from typing import TYPE_CHECKING

from hephaestus.core.errors import ValidationError
from hephaestus.core.executor.identity import (
    backend_execution_identity,
    recorded_execution_identity,
)
from hephaestus.core.project_store.store import blob_hash_of_ref
from hephaestus.core.render.bundle import RenderStore
from hephaestus.core.render.oci_protocol import RENDER_VERSION, validate_response
from hephaestus.core.render.palette import SelectionEntry, build_legend

from opstore import canonical_json

if TYPE_CHECKING:
    from hephaestus.core.render.inspect import RenderProject, RenderSource


def frozen_request(
    project: RenderProject,
    source: RenderSource,
    operation: str,
    view: str,
    width: int,
    height: int,
    *,
    section=None,
    links=None,
) -> dict:
    from hephaestus.core.render.inspect import build_solid_labels, tag_placements_from_source_map

    result = source.result
    if (
        result is None
        or result.artifact_ref != source.source_artifact_ref
        or source.source_map is None
    ):
        raise ValidationError(
            "OCI rendering requires a published build with source-map provenance", kind="contract"
        )
    recorded = recorded_execution_identity(dict(result.metadata), result.input_hashes.toolchain)
    live = backend_execution_identity(project.backend)
    if recorded is None or live != recorded:
        raise ValidationError(
            "OCI render source executor identity unavailable/mismatched", kind="contract"
        )
    from hephaestus.core.project_store.artifact_kinds import recorded_kinds

    for ref, kind in ((source.source_artifact_ref, "build"), (result.source_map_ref, "source-map")):
        if ref is None or kind not in recorded_kinds(project.store, blob_hash_of_ref(ref)):
            raise ValidationError("OCI render source artifact kind unverified", kind="contract")
    count = sum(max(g.solids, 0) for g in result.geometries)
    labels = build_solid_labels(result, count)
    placements = tag_placements_from_source_map(source.source_map)
    return {
        "version": RENDER_VERSION,
        "operation": operation,
        "source_ref": source.source_artifact_ref,
        "brep_sha256": hashlib.sha256(source.brep).hexdigest(),
        "solids": [{"label": labels.get(i), "color": None} for i in range(count)],
        "placements": [
            {
                "tag": tag,
                "kind": p.kind,
                "solid_index": p.solid_index,
                "topology_index": p.topo_index,
            }
            for tag, p in sorted(placements.items())
        ],
        "view": view,
        "width": width,
        "height": height,
        "section": section,
        "links": links,
    }


def execute(project, source, request):
    result = project.renderer.render(request, source.brep)
    # Validate again at publication admission, even for alternate service implementations.
    response = validate_response(result.data, request)
    provenance = {
        "kind": "render_provenance",
        "version": 1,
        "source_artifact_ref": source.source_artifact_ref,
        "source_map_ref": source.result.source_map_ref,
        "build_input_hashes": source.result.input_hashes.to_json(),
        "executor_identity": recorded_execution_identity(
            dict(source.result.metadata), source.result.input_hashes.toolchain
        ).to_json(),
        "renderer_identity": result.identity.to_json(),
        "request": request,
        "response_sha256": hashlib.sha256(result.data).hexdigest(),
        "gl_renderer": response["gl_renderer"],
        "section": response["section"],
    }
    return response, provenance


def png(image: dict, width: int, height: int) -> bytes:
    """Lossless encoding only, of already validated real worker pixels."""
    raw = base64.b64decode(image["pixels"], validate=True)
    channels = image["channels"]
    if channels not in (3, 4) or len(raw) != width * height * channels:
        raise ValueError("PNG input dimensions")

    def chunk(kind, data):
        return (
            struct.pack("!I", len(data)) + kind + data + struct.pack("!I", zlib.crc32(kind + data))
        )

    stride = width * channels
    rows = b"".join(b"\0" + raw[i : i + stride] for i in range(0, len(raw), stride))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(
            b"IHDR", struct.pack("!IIBBBBB", width, height, 8, 2 if channels == 3 else 6, 0, 0, 0)
        )
        + chunk(b"IDAT", zlib.compress(rows, 9))
        + chunk(b"IEND", b"")
    )


def link_provenance(store, refs, provenance):
    blob = store.blobs.put(canonical_json(provenance).encode())
    for ref in refs:
        store.gc.link(blob_hash_of_ref(ref), blob)
    for key in ("source_artifact_ref", "source_map_ref"):
        store.gc.link(blob, blob_hash_of_ref(provenance[key]))
    return blob


def selection_bundle(project, source, view, width, height):
    request = frozen_request(project, source, "selection", view, width, height)
    response, provenance = execute(project, source, request)
    images = response["images"]
    bundle = RenderStore(project.store).publish_selection_bundle(
        view=view,
        source_artifact_ref=source.source_artifact_ref,
        entries={int(k): SelectionEntry.from_json(v) for k, v in response["entries"].items()},
        solid_png=png(images["solid"], width, height),
        face_png=png(images["face"], width, height),
        edge_png=png(images["edge"], width, height),
        preview_png=png(images["preview"], width, height),
        provenance=provenance,
    )
    link_provenance(project.store, [bundle.bundle_ref], provenance)
    return bundle, response, provenance


def inspect_remote(project, source, views, channel, mode, section_plane, width, height):
    from hephaestus.core.render.inspect import (
        InspectImage,
        InspectResult,
        SelectionBundleView,
        _publish_legend,
    )

    images, refs, bundles = [], [], []
    table_ref, entries = None, None
    section = None
    if channel == "section":
        match = re.fullmatch(r"([+-])([XYZ])@([+-]?(?:\d+(?:\.\d*)?|\.\d+))", section_plane or "")
        if match is None:
            raise ValidationError(
                "OCI section requires signed axis@numeric mm offset", kind="contract"
            )
        section = {
            "axis": match[2],
            "sign": 1 if match[1] == "+" else -1,
            "offset": float(match[3]),
        }
    for view in views:
        if channel == "mask" and mode == "selection":
            bundle, response, _ = selection_bundle(project, source, view, width, height)
            data = png(response["images"]["preview"], width, height)
            ref = bundle.preview_ref
            table_ref = bundle.selection_table_ref
            bundles.append(SelectionBundleView(view, bundle.bundle_ref, bundle.pass_refs))
            refs.extend([ref, *bundle.pass_refs.as_tuple()])
        else:
            request = frozen_request(project, source, channel, view, width, height, section=section)
            response, provenance = execute(project, source, request)
            data = png(response["images"][channel], width, height)
            ref = RenderStore(project.store).publish_render(data).ref
            link_provenance(project.store, [ref], provenance)
            refs.append(ref)
        images.append(InspectImage(view, channel, ref, data, channel == "mask" and mode == "solid"))
        entries = {int(k): SelectionEntry.from_json(v) for k, v in response["entries"].items()}
    legend, legend_ref, truncated = None, None, False
    if channel == "mask":
        legend, legend_ref, truncated = _publish_legend(
            project.store, build_legend(entries), force_ref=mode == "selection"
        )
    return InspectResult(
        "ok",
        source.source_artifact_ref,
        channel,
        mode,
        tuple(images),
        tuple(refs),
        truncated,
        legend,
        legend_ref,
        table_ref,
        tuple(bundles) if bundles else None,
    )


def export_remote(project, source, bundle, view, width, height):
    request = frozen_request(
        project,
        source,
        "gltf",
        view,
        width,
        height,
        links={"bundle_ref": bundle.bundle_ref, "selection_table_ref": bundle.selection_table_ref},
    )
    response, provenance = execute(project, source, request)
    # A new worker's catalog must equal the already published table, not merely
    # an internally consistent but unrelated table returned beside its GLB.
    table = json.loads(project.store.blobs.get(blob_hash_of_ref(bundle.selection_table_ref)))
    if response["entries"] != table["entries"]:
        raise ValidationError("GLB catalog differs from minted selection bundle", kind="contract")
    return base64.b64decode(response["glb"]["data"], validate=True), provenance
