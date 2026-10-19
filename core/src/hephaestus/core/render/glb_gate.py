"""Bounded stdlib validation of the canonical self-contained selection GLB.

No geometry decoding or GPU context on the host. This is intentionally narrower
than general glTF: external resources, extensions, animation and transforms are
not outputs of our exporter and cannot reach a browser through this gate.
"""

from __future__ import annotations

import math
import struct
from typing import Any

from hephaestus.core.executor.sandbox.oci_transfer import encode, unique_json


def _int(value: Any, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError("GLB integer/range")
    return value


def parse_glb(data: object, *, experimental: bool = False) -> tuple[dict[str, Any], bytes]:
    """Parse shared linkage; OCI transport admission is explicitly opt-in."""
    if not isinstance(data, bytes) or len(data) < 28 or (experimental and len(data) > 4 * 1024**2):
        raise ValueError("GLB byte bound")
    magic, version, length = struct.unpack_from("<4sII", data)
    if (magic, version, length) != (b"glTF", 2, len(data)):
        raise ValueError("GLB header")
    size, kind = struct.unpack_from("<I4s", data, 12)
    if (
        kind != b"JSON"
        or size % 4
        or not 0 < size <= len(data) - 28
        or (experimental and size > 1024**2)
    ):
        raise ValueError("GLB JSON chunk")
    doc = unique_json(data[20 : 20 + size])
    if not isinstance(doc, dict):
        raise ValueError("GLB JSON object")
    offset = 20 + size
    size, kind = struct.unpack_from("<I4s", data, offset)
    if kind != b"BIN\0" or size % 4 or offset + 8 + size != len(data):
        raise ValueError("GLB binary chunk/trailing bytes")
    return doc, data[offset + 8 :]


def validate_linked_glb(
    data: bytes,
    *,
    source_ref: str,
    bundle_ref: str,
    selection_table_ref: str,
    entries: dict[str, Any],
    experimental: bool = False,
) -> dict[str, Any]:
    try:
        return _validate_linked_glb(
            data, source_ref, bundle_ref, selection_table_ref, entries, experimental
        )
    except (KeyError, IndexError, TypeError, AttributeError, struct.error) as exc:
        raise ValueError("malformed canonical GLB") from exc


def _validate_linked_glb(
    data: bytes,
    source_ref: str,
    bundle_ref: str,
    selection_table_ref: str,
    entries: dict[str, Any],
    experimental: bool,
) -> dict[str, Any]:
    doc, binary = parse_glb(data, experimental=experimental)
    if set(doc) - {
        "asset",
        "accessors",
        "bufferViews",
        "buffers",
        "materials",
        "meshes",
        "nodes",
        "scene",
        "scenes",
    }:
        raise ValueError("GLB unsupported resources/extensions")
    asset = doc["asset"]
    if asset.get("version") != "2.0" or asset.get("extras") != {
        "selection_bundle_ref": bundle_ref,
        "source_artifact_ref": source_ref,
        "selection_table_ref": selection_table_ref,
    }:
        raise ValueError("GLB source/bundle/table references")
    buffers = doc["buffers"]
    if len(buffers) != 1 or set(buffers[0]) != {"byteLength"}:
        raise ValueError("GLB external/extra buffer")
    declared = _int(buffers[0]["byteLength"], 1, len(binary))
    if len(binary) - declared > 3 or any(binary[declared:]):
        raise ValueError("GLB binary padding")
    views = doc["bufferViews"]
    accessors = doc["accessors"]
    if not views or not accessors or (experimental and max(len(views), len(accessors)) > 4096):
        raise ValueError("GLB geometry count bound")
    for view in views:
        if (
            set(view) - {"buffer", "byteOffset", "byteLength", "target"}
            or type(view.get("buffer")) is not int
            or view["buffer"] != 0
        ):
            raise ValueError("GLB buffer view")
        start = _int(view.get("byteOffset", 0), 0, declared)
        length = _int(view["byteLength"], 1, declared - start)
        if start % 4 or length % 4:
            raise ValueError("GLB buffer alignment")
    decoded = []
    for accessor in accessors:
        if (
            set(accessor)
            - {
                "bufferView",
                "byteOffset",
                "componentType",
                "count",
                "type",
                "min",
                "max",
                "normalized",
            }
            or accessor.get("normalized", False) is not False
        ):
            raise ValueError("GLB accessor format")
        view = views[_int(accessor["bufferView"], 0, len(views) - 1)]
        kind = (accessor["componentType"], accessor["type"])
        if type(accessor["componentType"]) is not int or kind not in (
            (5126, "VEC3"),
            (5125, "SCALAR"),
        ):
            raise ValueError("GLB component format")
        elements = 3 if kind[0] == 5126 else 1
        count = _int(accessor["count"], 1, 1024**2 if experimental else declared // 4)
        start = _int(accessor.get("byteOffset", 0), 0, view["byteLength"])
        size = count * elements * 4
        if start % 4 or start + size > view["byteLength"]:
            raise ValueError("GLB accessor bounds")
        start += view.get("byteOffset", 0)
        values = tuple(
            v[0]
            for v in struct.iter_unpack(
                "<f" if elements == 3 else "<I", binary[start : start + size]
            )
        )
        if elements == 3 and not all(math.isfinite(v) for v in values):
            raise ValueError("GLB nonfinite vertices")
        decoded.append((kind, count, values))
    solids = {int(k): v for k, v in entries.items() if v["kind"] == "solid"}
    meshes = doc["meshes"]
    if not meshes or len(meshes) != len(solids):
        raise ValueError("GLB mesh count differs from selection solid count")
    used_faces = set()
    for s, mesh in enumerate(meshes):
        if set(mesh) - {"name", "extras", "primitives"}:
            raise ValueError("GLB mesh fields")
        extra = mesh["extras"]
        sid = _int(
            extra["selection_id"], 1 if experimental else 0, 2048 if experimental else 0xFFFFFE
        )
        if (
            sid not in solids
            or solids[sid]["solid_index"] != s
            or extra.get("kind") != "solid"
            or type(extra.get("solid_index")) is not int
            or extra["solid_index"] != s
            or extra.get("label") != solids[sid].get("label")
        ):
            raise ValueError("GLB solid table binding")
        offset = extra.get("explode_offset")
        if (
            not isinstance(offset, list)
            or len(offset) != 3
            or any(type(x) not in (int, float) or not math.isfinite(x) for x in offset)
        ):
            raise ValueError("GLB explode offset")
        if not mesh["primitives"]:
            raise ValueError("GLB empty mesh")
        for primitive in mesh["primitives"]:
            if (
                set(primitive) - {"attributes", "indices", "mode", "material", "extras"}
                or type(primitive.get("mode", 4)) is not int
                or primitive.get("mode", 4) != 4
                or set(primitive["attributes"]) != {"POSITION"}
            ):
                raise ValueError("GLB primitive format")
            e = primitive["extras"]
            fid = _int(
                e["selection_id"], 1 if experimental else 0, 2048 if experimental else 0xFFFFFE
            )
            entry = entries.get(str(fid))
            if (
                not entry
                or entry["kind"] != "face"
                or entry["solid_index"] != s
                or encode(e)
                != encode(
                    {
                        "selection_id": fid,
                        "kind": "face",
                        "solid_index": s,
                        "face_index": entry["topology_index"],
                    }
                )
                or fid in used_faces
            ):
                raise ValueError("GLB face table binding")
            used_faces.add(fid)
            pk, count, _ = decoded[_int(primitive["attributes"]["POSITION"], 0, len(decoded) - 1)]
            ik, _, indices = decoded[_int(primitive["indices"], 0, len(decoded) - 1)]
            if (
                pk != (5126, "VEC3")
                or ik != (5125, "SCALAR")
                or len(indices) % 3
                or max(indices) >= count
            ):
                raise ValueError("GLB triangle index bounds")
            _int(primitive["material"], 0, len(doc["materials"]) - 1)
    # Materials must not smuggle a texture/URI through an otherwise local mesh.
    for material in doc["materials"]:
        if set(material) - {
            "name",
            "pbrMetallicRoughness",
            "doubleSided",
            "alphaMode",
            "alphaCutoff",
            "emissiveFactor",
        }:
            raise ValueError("GLB material resource")
        if set(material.get("pbrMetallicRoughness", {})) - {
            "baseColorFactor",
            "metallicFactor",
            "roughnessFactor",
        }:
            raise ValueError("GLB texture resource")
    if (
        encode(doc["nodes"]) != encode([{"mesh": s} for s in range(len(meshes))])
        or type(doc["scene"]) is not int
        or doc["scene"] != 0
        or encode(doc["scenes"]) != encode([{"nodes": list(range(len(meshes)))}])
    ):
        raise ValueError("GLB scene/node binding")
    return {
        "mesh_count": len(meshes),
        "primitive_count": len(used_faces),
        "face_ids": sorted(used_faces),
    }
