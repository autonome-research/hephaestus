# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Fresh host call-graph acceptance over actual executor and renderer artifacts."""

from __future__ import annotations

import hashlib
import json
import struct
import zlib

from hephaestus.core.project_store.artifact_kinds import recorded_kinds
from hephaestus.core.project_store.layout import load_project, open_store
from hephaestus.core.project_store.store import blob_hash_of_ref
from hephaestus.core.render.bundle import StaleSelectionError, resolve_selection
from hephaestus.core.render.glb_gate import validate_linked_glb
from hephaestus.core.render.gltf_publish import publish_gltf_for_build
from hephaestus.core.render.inspect import RenderProject, inspect_part
from macos_executor_live import document, require


def pixels(png, width=128, height=96):
    require(png[:8] == b"\x89PNG\r\n\x1a\n", "actual PNG signature")
    require(struct.unpack_from("!II", png, 16) == (width, height), "PNG dimensions")
    channels = {2: 3, 6: 4}[png[25]]
    offset, compressed = 8, bytearray()
    while offset < len(png):
        size = struct.unpack_from("!I", png, offset)[0]
        kind, data = png[offset + 4 : offset + 8], png[offset + 8 : offset + 8 + size]
        require(
            zlib.crc32(kind + data) == struct.unpack_from("!I", png, offset + 8 + size)[0],
            "PNG CRC",
        )
        if kind == b"IDAT":
            compressed.extend(data)
        offset += size + 12
    raw = zlib.decompress(compressed)
    stride = width * channels + 1
    require(
        len(raw) == stride * height and all(raw[i] == 0 for i in range(0, len(raw), stride)),
        "lossless PNG rows",
    )
    return b"".join(raw[i + 1 : i + stride] for i in range(0, len(raw), stride)), channels


def require_fixture_faces(validation, entries):
    """The authored two-cuboid fixture must retain every one of its 12 faces."""
    faces = {key: entry for key, entry in entries.items() if entry.kind == "face"}
    require(
        len(faces) == 12
        and {(e.solid_index, e.topology_index) for e in faces.values()}
        == {(solid, face) for solid in range(2) for face in range(6)}
        and validation["primitive_count"] == 12
        and set(validation["face_ids"]) == set(faces),
        "complete two-cuboid GLB face set (12 primitives)",
    )


def integrated(smoke, root, backend, renderer):
    layout = load_project(root)
    evidence = {}
    with open_store(layout) as store:
        project = RenderProject(layout, store, renderer=renderer, backend=backend)
        current = project.publisher().current_result("two_solids")
        require(
            current is not None and project.publisher().freshness("two_solids").fresh,
            "fresh published CAD source",
        )
        source = current.artifact_ref
        require("build" in recorded_kinds(store, blob_hash_of_ref(source)), "source artifact kind")
        for channel, mode, section in (
            ("rgb", "solid", None),
            ("mask", "solid", None),
            ("mask", "selection", None),
            ("section", "solid", "+Z@0"),
        ):
            result = inspect_part(
                project,
                "two_solids",
                views=["iso" if not section else "+Z"],
                channel=channel,
                mask_mode=mode,
                section_plane=section,
                width=128,
                height=96,
            )
            require(result.source_artifact_ref == source, "inspection source binding")
            name = channel + "-" + mode
            for image in result.images:
                raw, channels = pixels(image.png)
                require(
                    len(set(raw[i : i + 3] for i in range(0, len(raw), channels))) > 1,
                    "empty actual render",
                )
                (smoke.directory / (name + ".png")).write_bytes(image.png)
                require(
                    store.blobs.get(blob_hash_of_ref(image.render_ref)) == image.png,
                    "published PNG bytes",
                )
            evidence[name] = result.to_json()
            document(smoke.directory / (name + "-inspect.json"), result.to_json())
            if mode == "selection":
                bundle = result.selection_bundles[0]
                resolved = resolve_selection(
                    store, bundle.bundle_ref, expected_source_artifact_ref=source
                )
                require(len(resolved.entries) == 38, "selection table topology count")
                visible = {}
                for kind, ref in resolved.pass_refs.to_json().items():
                    require(
                        "selection-pass" in recorded_kinds(store, blob_hash_of_ref(ref)),
                        "selection pass kind",
                    )
                    raw, channels = pixels(store.blobs.get(blob_hash_of_ref(ref)))
                    ids = {
                        int.from_bytes(raw[i : i + 3], "big") - 1
                        for i in range(0, len(raw), channels)
                    } - {-1}
                    require(
                        ids
                        and all(
                            i in resolved.entries and resolved.entries[i].kind == kind for i in ids
                        ),
                        "exact visible palette/table IDs",
                    )
                    visible[kind] = sorted(ids)
                require(
                    len(visible["solid"]) == 2 and len(visible["edge"]) == 24,
                    "known fixture solid/edge mask coverage",
                )
                evidence["visible_ids"] = visible
                try:
                    resolve_selection(
                        store,
                        bundle.bundle_ref,
                        expected_source_artifact_ref="artifact:build:sha256:" + "0" * 64,
                    )
                except StaleSelectionError:
                    evidence["stale_source_refused"] = True
                else:
                    raise RuntimeError("stale source selection accepted")
                smoke.check(
                    "selection_masks",
                    "passed",
                    "inspect_part publishes exact solid/face/edge IDs "
                    "resolving through real tables and GC links",
                )
            if channel == "section":
                blob = blob_hash_of_ref(result.images[0].render_ref)
                records = [json.loads(store.blobs.get(t)) for s, t in store.gc.links() if s == blob]
                p = next(p for p in records if p.get("kind") == "render_provenance")
                require(
                    p["section"]["faces"] == 2 and abs(p["section"]["area_mm2"] - 26) < 1e-8,
                    "measured kernel section faces/area",
                )
                require(
                    p["source_artifact_ref"] == source
                    and p["renderer_identity"] == renderer.supervisor.execution_identity().to_json()
                    and p["executor_identity"] == backend.execution_identity().to_json(),
                    "section execution provenance",
                )
                evidence["kernel_section"] = p
                smoke.check(
                    "kernel_section",
                    "passed",
                    "inspect_part kernel cut: 2 faces, 26 mm2; "
                    "provenance-linked measurement and raster",
                )
            if channel == "rgb":
                smoke.check(
                    "rgb", "passed", "inspect_part actual nonempty 128x96 RGB and stored bytes"
                )
        glb = publish_gltf_for_build(project, source, width=128, height=96)
        require(glb.minted and glb.mesh_count == 2, "fresh GLB publication/mesh count")
        resolution = resolve_selection(store, glb.bundle_ref, expected_source_artifact_ref=source)
        validation = validate_linked_glb(
            glb.data,
            source_ref=source,
            bundle_ref=glb.bundle_ref,
            selection_table_ref=glb.selection_table_ref,
            entries={str(k): v.to_json() for k, v in resolution.entries.items()},
        )
        require_fixture_faces(validation, resolution.entries)
        require("gltf" in recorded_kinds(store, glb.blob_hash), "published GLB kind")
        links = set(store.gc.links())
        require(
            (glb.blob_hash, blob_hash_of_ref(source)) in links
            and (glb.blob_hash, blob_hash_of_ref(glb.bundle_ref)) in links,
            "GLB GC provenance chain",
        )
        require(
            publish_gltf_for_build(project, source, width=128, height=96).minted is False,
            "linked GLB cache resolution",
        )
        (smoke.directory / "linked.glb").write_bytes(glb.data)
        evidence["linked_glb"] = {
            "ref": glb.ref,
            "source": source,
            "bundle": glb.bundle_ref,
            "table": glb.selection_table_ref,
            "sha256": hashlib.sha256(glb.data).hexdigest(),
            **validation,
        }
        document(smoke.directory / "integration.json", evidence)
        smoke.check(
            "linked_glb",
            "passed",
            "fresh _mint_bundle and worker GLB; validated mesh/face IDs, "
            "source/bundle/table refs and GC links",
        )
    smoke.report["render_integration"] = evidence
    smoke.save()
