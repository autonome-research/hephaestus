"""Closed experimental renderer API v2; stdlib-only host admission/validation.

Independent of CAD run requests. Containment stays executor profile 5; the
renderer manifest extends it with an exact, disjoint workload allowlist. Raw
pixels travel in bounded JSON inside the existing nonce/digest/EOF framing:
no archives, output paths, scripts, pickle or host image decoder is involved.
"""

from __future__ import annotations

import base64
import hashlib
import math
import re
from typing import Any

from hephaestus.core.executor.sandbox.oci_protocol import (
    PROBE_WORKER,
    manifest_record,
)
from hephaestus.core.executor.sandbox.oci_storage_policy import STORAGE_WORKER
from hephaestus.core.executor.sandbox.oci_transfer import encode, unique_json

RENDER_WORKER = "hephaestus.core.render.oci_worker"
RENDER_LAUNCHER = "hephaestus.core.render.oci_launcher"
RENDER_VERSION = 2
RENDER_MODULES = frozenset({RENDER_WORKER, PROBE_WORKER, STORAGE_WORKER})
OPERATIONS = ("probe", "rgb", "mask", "selection", "section", "gltf")
MAX_GLB = 4 * 1024 * 1024
MAX_BREP = 16 * 1024 * 1024
MAX_REQUEST = 128 * 1024
MAX_RESULT = 8 * 1024 * 1024
MAX_SOLIDS = 128
MAX_TOPOLOGY = 2048
VIEWS = ("iso", "+X", "-X", "+Y", "-Y", "+Z", "-Z")
RENDER_ENV = {
    "PYOPENGL_PLATFORM": "egl",
    "EGL_PLATFORM": "surfaceless",
    "LIBGL_ALWAYS_SOFTWARE": "1",
    "LP_NUM_THREADS": "1",
    "MESA_SHADER_CACHE_DISABLE": "true",
    "__EGL_VENDOR_LIBRARY_FILENAMES": (
        "/opt/hephaestus/native/usr/share/glvnd/egl_vendor.d/50_mesa.json"
    ),
    "LIBGL_DRIVERS_PATH": "/opt/hephaestus/native/usr/lib/aarch64-linux-gnu/dri",
}


def manifest_bytes(inventory: object = None) -> bytes:
    import json

    record = manifest_record()
    record["limits"] = {
        **record["limits"],
        "address_space_bytes_max": 2 * 1024**3,
        "nproc_max": 256,
    }
    record.update(
        workers=sorted(RENDER_MODULES),
        renderer={
            "name": "hephaestus.oci-renderer",
            "version": RENDER_VERSION,
            "manifest_version": 1,
            "operations": list(OPERATIONS),
            "environment": RENDER_ENV,
            "brep_max": MAX_BREP,
            "request_max": MAX_REQUEST,
            "result_max": MAX_RESULT,
            "dimension_max": 512,
            "solids_max": MAX_SOLIDS,
            "topology_max": MAX_TOPOLOGY,
            "views": list(VIEWS),
        },
        execution_identity=inventory,
    )
    return (
        json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    ).encode("ascii")


def _object(value: Any, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError("renderer closed object schema")
    return value


def _integer(value: Any, lo: int, hi: int) -> int:
    if type(value) is not int or not lo <= value <= hi:
        raise ValueError("renderer integer bound")
    return value


def _text(value: Any) -> str | None:
    if value is not None and (
        not isinstance(value, str)
        or not 1 <= len(value.encode()) <= 256
        or any(ord(c) < 32 for c in value)
    ):
        raise ValueError("renderer metadata string")
    return value


def _number(value: Any, lo: float, hi: float) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not lo <= value <= hi:
        raise ValueError("renderer finite numeric bound")
    return float(value)


def validate_request(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("renderer request object")
    if type(value.get("version")) is not int or value["version"] != RENDER_VERSION:
        raise ValueError("renderer version mismatch")
    operation = value.get("operation")
    if operation not in OPERATIONS:
        raise ValueError("renderer operation not allowed")
    if operation == "probe":
        return _object(value, {"version", "operation"})
    _object(
        value,
        {
            "version",
            "operation",
            "source_ref",
            "brep_sha256",
            "solids",
            "placements",
            "view",
            "width",
            "height",
            "section",
            "links",
        },
    )
    links = value["links"]
    if operation == "gltf":
        _object(links, {"bundle_ref", "selection_table_ref"})
        for key, kind in (
            ("bundle_ref", "selection-bundle"),
            ("selection_table_ref", "selection-table"),
        ):
            if (
                not isinstance(links[key], str)
                or re.fullmatch("artifact:" + kind + r":sha256:[0-9a-f]{64}", links[key]) is None
            ):
                raise ValueError("renderer GLB link")
    elif links is not None:
        raise ValueError("renderer unexpected links")
    digest = value["brep_sha256"]
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ValueError("renderer BREP digest")
    # Build artifact refs address BREP bytes, not arbitrary labels supplied by a job.
    if value["source_ref"] != "artifact:build:sha256:" + digest:
        raise ValueError("renderer source ref does not identify BREP")
    if value["view"] not in VIEWS:
        raise ValueError("renderer view not allowed")
    for key in ("width", "height"):
        _integer(value[key], 16, 512)
    solids = value["solids"]
    if not isinstance(solids, list) or not 1 <= len(solids) <= MAX_SOLIDS:
        raise ValueError("renderer solid metadata bound")
    for solid in solids:
        _object(solid, {"label", "color"})
        _text(solid["label"])
        color = solid["color"]
        if color is not None:
            if not isinstance(color, list) or len(color) != 4:
                raise ValueError("renderer color schema")
            for c in color:
                _integer(c, 0, 255)
    placements = value["placements"]
    if not isinstance(placements, list) or len(placements) > MAX_TOPOLOGY:
        raise ValueError("renderer placements bound")
    names, occurrences = set(), set()
    for placement in placements:
        _object(placement, {"tag", "kind", "solid_index", "topology_index"})
        tag = _text(placement["tag"])
        if tag is None or tag in names or placement["kind"] not in ("solid", "face", "edge"):
            raise ValueError("renderer placement identity")
        names.add(tag)
        s = _integer(placement["solid_index"], 0, len(solids) - 1)
        t = _integer(placement["topology_index"], 0, MAX_TOPOLOGY - 1)
        occurrence = (placement["kind"], s, t)
        if occurrence in occurrences or (placement["kind"] == "solid" and t != s):
            raise ValueError("renderer duplicate/invalid placement")
        occurrences.add(occurrence)
    section = value["section"]
    if operation == "section":
        _object(section, {"axis", "sign", "offset"})
        if section["axis"] not in ("X", "Y", "Z"):
            raise ValueError("renderer section axis")
        _integer(section["sign"], -1, 1)
        if section["sign"] == 0:
            raise ValueError("renderer section sign")
        _number(section["offset"], -1e6, 1e6)
    elif section is not None:
        raise ValueError("renderer unexpected section")
    return value


def request_bytes(value: Any) -> bytes:
    validate_request(value)
    return encode(value, MAX_REQUEST)


def read_request(data: bytes) -> dict[str, Any]:
    if len(data) > MAX_REQUEST:
        raise ValueError("renderer request byte limit")
    return validate_request(unique_json(data))


def request_hash(value: Any) -> str:
    return hashlib.sha256(request_bytes(value)).hexdigest()


def validate_response(data: bytes, request: dict[str, Any]) -> dict[str, Any]:
    """Validate exact dimensions, canonical namespace, metadata and every ID pixel.

    A valid response is not publication/provenance authorization. The backend
    additionally requires its fresh trusted image identity and terminal cleanup.
    """
    validate_request(request)
    if len(data) > MAX_RESULT:
        raise ValueError("renderer result byte limit")
    value = unique_json(data)
    _object(
        value,
        {
            "version",
            "operation",
            "request_sha256",
            "source_ref",
            "gl_renderer",
            "topology",
            "entries",
            "images",
            "section",
            "glb",
        },
    )
    if (
        type(value["version"]) is not int
        or value["version"] != RENDER_VERSION
        or value["operation"] != request["operation"]
        or value["request_sha256"] != request_hash(request)
        or value["source_ref"] != request.get("source_ref")
    ):
        raise ValueError("renderer response identity mismatch")
    renderer = value["gl_renderer"]
    if (
        not isinstance(renderer, str)
        or not 1 <= len(renderer) <= 256
        or not renderer.isascii()
        or any(ord(c) < 32 for c in renderer)
        or "llvmpipe" not in renderer.lower()
    ):
        raise ValueError("renderer is not llvmpipe")
    operation = request["operation"]
    if operation == "probe":
        if (
            any(value[k] != {} for k in ("entries", "images"))
            or value["topology"] != []
            or value["section"] is not None
            or value["glb"] is not None
        ):
            raise ValueError("renderer probe payload")
        return value
    topology = value["topology"]
    if not isinstance(topology, list) or len(topology) != len(request["solids"]):
        raise ValueError("renderer topology/solid count")
    total = 0
    for record in topology:
        _object(record, {"faces", "edges"})
        total += (
            1
            + _integer(record["faces"], 1, MAX_TOPOLOGY)
            + _integer(record["edges"], 1, MAX_TOPOLOGY)
        )
    if total > MAX_TOPOLOGY:
        raise ValueError("renderer topology bound")
    tags = {
        (p["kind"], p["solid_index"], p["topology_index"]): p["tag"] for p in request["placements"]
    }
    occurrences = set()
    expected = {}
    next_id = 1
    for s, record in enumerate(topology):
        for kind, indices in (
            ("solid", [s]),
            ("face", range(record["faces"])),
            ("edge", range(record["edges"])),
        ):
            for t in indices:
                occurrence = (kind, s, t)
                occurrences.add(occurrence)
                entry = {"kind": kind, "solid_index": s, "topology_index": t}
                if request["solids"][s]["label"] is not None:
                    entry["label"] = request["solids"][s]["label"]
                if occurrence in tags:
                    entry["tag"] = tags[occurrence]
                expected[str(next_id)] = entry
                next_id += 1
    if not tags.keys() <= occurrences:
        raise ValueError("renderer placement outside topology")
    if operation == "mask":
        expected = {
            str(s): {
                "kind": "solid",
                "solid_index": s,
                "topology_index": s,
                **({"label": meta["label"]} if meta["label"] is not None else {}),
            }
            for s, meta in enumerate(request["solids"])
        }
    elif operation not in ("selection", "gltf"):
        expected = {}
    # Canonical encoding prevents bool/int and float/int equality coercions.
    if encode(value["entries"]) != encode(expected):
        raise ValueError("renderer selection table mismatch")
    images = value["images"]
    kinds = (
        {"solid", "face", "edge", "preview"}
        if operation == "selection"
        else ({operation} if operation != "gltf" else set())
    )
    if not isinstance(images, dict) or set(images) != kinds:
        raise ValueError("renderer image set")
    for kind, image in images.items():
        _object(image, {"channels", "pixels", "sha256"})
        channels = 3 if operation == "selection" and kind != "preview" else 4
        if type(image["channels"]) is not int or image["channels"] != channels:
            raise ValueError("renderer pixel channels")
        size = request["width"] * request["height"] * channels
        text = image["pixels"]
        if not isinstance(text, str) or len(text) != 4 * ((size + 2) // 3):
            raise ValueError("renderer pixel length")
        raw = base64.b64decode(text, validate=True)
        if (
            len(raw) != size
            or base64.b64encode(raw).decode() != text
            or hashlib.sha256(raw).hexdigest() != image["sha256"]
        ):
            raise ValueError("renderer pixel digest/encoding")
        if operation in ("selection", "mask") and kind != "preview":
            from hephaestus.core.render.palette import rgb_to_id

            for i in range(0, len(raw), channels):
                rgb = tuple(raw[i : i + 3])
                if channels == 4 and raw[i + 3] != 255:
                    raise ValueError("renderer mask alpha")
                if rgb == (0, 0, 0):
                    continue
                entry = expected.get(str(rgb_to_id(rgb)))
                if entry is None or entry["kind"] != (
                    kind if operation == "selection" else "solid"
                ):
                    raise ValueError("renderer pixel outside exact palette/kind")
    if operation == "section":
        section = _object(value["section"], {"faces", "area_mm2"})
        count = _integer(section["faces"], 0, MAX_TOPOLOGY)
        area = _number(section["area_mm2"], 0, 1e18)
        if (count == 0) != (area == 0):
            raise ValueError("renderer section measurements inconsistent")
    elif value["section"] is not None:
        raise ValueError("renderer unexpected section measurements")
    if operation == "gltf":
        glb = _object(value["glb"], {"data", "sha256"})
        if not isinstance(glb["data"], str) or len(glb["data"]) > 4 * ((MAX_GLB + 2) // 3):
            raise ValueError("renderer GLB size")
        raw = base64.b64decode(glb["data"], validate=True)
        if (
            len(raw) > MAX_GLB
            or base64.b64encode(raw).decode() != glb["data"]
            or hashlib.sha256(raw).hexdigest() != glb["sha256"]
        ):
            raise ValueError("renderer GLB digest/encoding")
        from hephaestus.core.render.glb_gate import validate_linked_glb

        validate_linked_glb(
            raw,
            source_ref=request["source_ref"],
            entries=expected,
            experimental=True,
            **request["links"],
        )
    elif value["glb"] is not None:
        raise ValueError("renderer unexpected GLB")
    return value
