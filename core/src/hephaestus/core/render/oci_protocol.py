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
from collections.abc import Mapping
from typing import Literal, NotRequired, TypedDict, cast

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


Operation = Literal["rgb", "mask", "selection", "section", "gltf"]
Kind = Literal["solid", "face", "edge"]


class ProbeRequest(TypedDict):
    version: int
    operation: Literal["probe"]


class Solid(TypedDict):
    label: str | None
    color: list[int] | None


class Placement(TypedDict):
    tag: str
    kind: Kind
    solid_index: int
    topology_index: int


class Section(TypedDict):
    axis: str
    sign: int
    offset: float


class Links(TypedDict):
    bundle_ref: str
    selection_table_ref: str


class RenderRequest(TypedDict):
    version: int
    operation: Operation
    source_ref: str
    brep_sha256: str
    solids: list[Solid]
    placements: list[Placement]
    view: str
    width: int
    height: int
    section: Section | None
    links: Links | None


Request = ProbeRequest | RenderRequest


class Topology(TypedDict):
    faces: int
    edges: int


class Entry(TypedDict):
    kind: Kind
    solid_index: int
    topology_index: int
    label: NotRequired[str]
    tag: NotRequired[str]


class Image(TypedDict):
    channels: int
    pixels: str
    sha256: str


class Measurements(TypedDict):
    faces: int
    area_mm2: float


class Glb(TypedDict):
    data: str
    sha256: str


class Response(TypedDict):
    version: int
    operation: Literal["probe"] | Operation
    request_sha256: str
    source_ref: str | None
    gl_renderer: str
    topology: list[Topology]
    entries: dict[str, Entry]
    images: dict[str, Image]
    section: Measurements | None
    glb: Glb | None


def manifest_bytes(inventory: object = None) -> bytes:
    import json

    record = manifest_record()
    limits = record["limits"]
    if not isinstance(limits, dict):
        raise ValueError("renderer manifest limits object")
    record["limits"] = {
        **limits,
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


def _object(value: object, keys: set[str]) -> Mapping[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError("renderer closed object schema")
    # Only the checked string keys are exposed; values remain untrusted objects.
    return cast(Mapping[str, object], value)


def _integer(value: object, lo: int, hi: int) -> int:
    if type(value) is not int or not lo <= value <= hi:
        raise ValueError("renderer integer bound")
    return value


def _text(value: object) -> str | None:
    if value is not None and (
        not isinstance(value, str)
        or not 1 <= len(value.encode()) <= 256
        or any(ord(c) < 32 for c in value)
    ):
        raise ValueError("renderer metadata string")
    return value


def _number(value: object, lo: float, hi: float) -> float:
    if (
        (type(value) is not int and type(value) is not float)
        or not math.isfinite(value)
        or not lo <= value <= hi
    ):
        raise ValueError("renderer finite numeric bound")
    return value


def validate_request(value: object) -> Request:
    if not isinstance(value, dict):
        raise ValueError("renderer request object")
    if type(value.get("version")) is not int or value["version"] != RENDER_VERSION:
        raise ValueError("renderer version mismatch")
    operation = value.get("operation")
    if operation not in OPERATIONS:
        raise ValueError("renderer operation not allowed")
    if operation == "probe":
        _object(value, {"version", "operation"})
        return {"version": RENDER_VERSION, "operation": "probe"}
    if operation not in ("rgb", "mask", "selection", "section", "gltf"):
        raise ValueError("renderer operation not allowed")
    value = _object(
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
    raw_links = value["links"]
    links: Links | None = None
    if operation == "gltf":
        link_record = _object(raw_links, {"bundle_ref", "selection_table_ref"})
        checked_links: dict[str, str] = {}
        for key, kind in (
            ("bundle_ref", "selection-bundle"),
            ("selection_table_ref", "selection-table"),
        ):
            link = link_record[key]
            if (
                not isinstance(link, str)
                or re.fullmatch("artifact:" + kind + r":sha256:[0-9a-f]{64}", link) is None
            ):
                raise ValueError("renderer GLB link")
            checked_links[key] = link
        links = {
            "bundle_ref": checked_links["bundle_ref"],
            "selection_table_ref": checked_links["selection_table_ref"],
        }
    elif raw_links is not None:
        raise ValueError("renderer unexpected links")
    digest = value["brep_sha256"]
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ValueError("renderer BREP digest")
    # Build artifact refs address BREP bytes, not arbitrary labels supplied by a job.
    if value["source_ref"] != "artifact:build:sha256:" + digest:
        raise ValueError("renderer source ref does not identify BREP")
    view = value["view"]
    if not isinstance(view, str) or view not in VIEWS:
        raise ValueError("renderer view not allowed")
    width = _integer(value["width"], 16, 512)
    height = _integer(value["height"], 16, 512)
    raw_solids = value["solids"]
    if not isinstance(raw_solids, list) or not 1 <= len(raw_solids) <= MAX_SOLIDS:
        raise ValueError("renderer solid metadata bound")
    solids: list[Solid] = []
    for raw_solid in raw_solids:
        solid = _object(raw_solid, {"label", "color"})
        label = _text(solid["label"])
        color = solid["color"]
        checked_color: list[int] | None = None
        if color is not None:
            if not isinstance(color, list) or len(color) != 4:
                raise ValueError("renderer color schema")
            checked_color = [_integer(c, 0, 255) for c in color]
        solids.append({"label": label, "color": checked_color})
    raw_placements = value["placements"]
    if not isinstance(raw_placements, list) or len(raw_placements) > MAX_TOPOLOGY:
        raise ValueError("renderer placements bound")
    names: set[str] = set()
    occurrences: set[tuple[Kind, int, int]] = set()
    placements: list[Placement] = []
    for raw_placement in raw_placements:
        placement = _object(raw_placement, {"tag", "kind", "solid_index", "topology_index"})
        tag = _text(placement["tag"])
        if tag is None or tag in names or placement["kind"] not in ("solid", "face", "edge"):
            raise ValueError("renderer placement identity")
        kind = placement["kind"]
        names.add(tag)
        s = _integer(placement["solid_index"], 0, len(solids) - 1)
        t = _integer(placement["topology_index"], 0, MAX_TOPOLOGY - 1)
        occurrence = (kind, s, t)
        if occurrence in occurrences or (placement["kind"] == "solid" and t != s):
            raise ValueError("renderer duplicate/invalid placement")
        occurrences.add(occurrence)
        placements.append({"tag": tag, "kind": kind, "solid_index": s, "topology_index": t})
    raw_section = value["section"]
    section: Section | None = None
    if operation == "section":
        section_record = _object(raw_section, {"axis", "sign", "offset"})
        axis = section_record["axis"]
        if not isinstance(axis, str) or axis not in ("X", "Y", "Z"):
            raise ValueError("renderer section axis")
        sign = _integer(section_record["sign"], -1, 1)
        if sign == 0:
            raise ValueError("renderer section sign")
        offset = _number(section_record["offset"], -1e6, 1e6)
        section = {"axis": axis, "sign": sign, "offset": offset}
    elif raw_section is not None:
        raise ValueError("renderer unexpected section")
    return {
        "version": RENDER_VERSION,
        "operation": operation,
        "source_ref": "artifact:build:sha256:" + digest,
        "brep_sha256": digest,
        "solids": solids,
        "placements": placements,
        "view": view,
        "width": width,
        "height": height,
        "section": section,
        "links": links,
    }


def request_bytes(value: object) -> bytes:
    validate_request(value)
    return encode(value, MAX_REQUEST)


def read_request(data: bytes) -> Request:
    if len(data) > MAX_REQUEST:
        raise ValueError("renderer request byte limit")
    return validate_request(unique_json(data))


def request_hash(value: object) -> str:
    return hashlib.sha256(request_bytes(value)).hexdigest()


def validate_response(data: bytes, request: object) -> Response:
    """Validate exact dimensions, canonical namespace, metadata and every ID pixel.

    A valid response is not publication/provenance authorization. The backend
    additionally requires its fresh trusted image identity and terminal cleanup.
    """
    # Hash the original wire representation (e.g. integer vs float offsets),
    # not the typed record reconstructed at admission.
    digest = request_hash(request)
    request = validate_request(request)
    if len(data) > MAX_RESULT:
        raise ValueError("renderer result byte limit")
    value = _object(
        unique_json(data),
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
        or value["request_sha256"] != digest
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
    response: Response = {
        "version": RENDER_VERSION,
        "operation": operation,
        "request_sha256": digest,
        "source_ref": request["source_ref"] if request["operation"] != "probe" else None,
        "gl_renderer": renderer,
        "topology": [],
        "entries": {},
        "images": {},
        "section": None,
        "glb": None,
    }
    if request["operation"] == "probe":
        if (
            any(value[k] != {} for k in ("entries", "images"))
            or value["topology"] != []
            or value["section"] is not None
            or value["glb"] is not None
        ):
            raise ValueError("renderer probe payload")
        return response
    raw_topology = value["topology"]
    if not isinstance(raw_topology, list) or len(raw_topology) != len(request["solids"]):
        raise ValueError("renderer topology/solid count")
    total = 0
    topology: list[Topology] = []
    for raw_record in raw_topology:
        record = _object(raw_record, {"faces", "edges"})
        faces = _integer(record["faces"], 1, MAX_TOPOLOGY)
        edges = _integer(record["edges"], 1, MAX_TOPOLOGY)
        total += 1 + faces + edges
        topology.append({"faces": faces, "edges": edges})
    response["topology"] = topology
    if total > MAX_TOPOLOGY:
        raise ValueError("renderer topology bound")
    tags = {
        (p["kind"], p["solid_index"], p["topology_index"]): p["tag"] for p in request["placements"]
    }
    occurrences: set[tuple[Kind, int, int]] = set()
    expected: dict[str, Entry] = {}
    next_id = 1
    for s, record in enumerate(topology):
        for kind in ("solid", "face", "edge"):
            indices = (
                [s]
                if kind == "solid"
                else range(record["faces"] if kind == "face" else record["edges"])
            )
            for t in indices:
                occurrence = (kind, s, t)
                occurrences.add(occurrence)
                entry: Entry = {"kind": kind, "solid_index": s, "topology_index": t}
                label = request["solids"][s]["label"]
                if label is not None:
                    entry["label"] = label
                if occurrence in tags:
                    entry["tag"] = tags[occurrence]
                expected[str(next_id)] = entry
                next_id += 1
    if not tags.keys() <= occurrences:
        raise ValueError("renderer placement outside topology")
    if operation == "mask":
        expected = {}
        for s, meta in enumerate(request["solids"]):
            entry = {"kind": "solid", "solid_index": s, "topology_index": s}
            label = meta["label"]
            if label is not None:
                entry["label"] = label
            expected[str(s)] = entry
    elif operation not in ("selection", "gltf"):
        expected = {}
    # Canonical encoding prevents bool/int and float/int equality coercions.
    if encode(value["entries"]) != encode(expected):
        raise ValueError("renderer selection table mismatch")
    response["entries"] = expected
    images = value["images"]
    kinds = (
        {"solid", "face", "edge", "preview"}
        if operation == "selection"
        else ({operation} if operation != "gltf" else set())
    )
    if not isinstance(images, dict) or set(images) != kinds:
        raise ValueError("renderer image set")
    for kind, raw_image in images.items():
        image = _object(raw_image, {"channels", "pixels", "sha256"})
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
        response["images"][kind] = {
            "channels": channels,
            "pixels": text,
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        if operation in ("selection", "mask") and kind != "preview":
            from hephaestus.core.render.palette import rgb_to_id

            for i in range(0, len(raw), channels):
                rgb = (raw[i], raw[i + 1], raw[i + 2])
                if channels == 4 and raw[i + 3] != 255:
                    raise ValueError("renderer mask alpha")
                if rgb == (0, 0, 0):
                    continue
                pixel_entry = expected.get(str(rgb_to_id(rgb)))
                if pixel_entry is None or pixel_entry["kind"] != (
                    kind if operation == "selection" else "solid"
                ):
                    raise ValueError("renderer pixel outside exact palette/kind")
    if operation == "section":
        section = _object(value["section"], {"faces", "area_mm2"})
        count = _integer(section["faces"], 0, MAX_TOPOLOGY)
        area = _number(section["area_mm2"], 0, 1e18)
        if (count == 0) != (area == 0):
            raise ValueError("renderer section measurements inconsistent")
        response["section"] = {"faces": count, "area_mm2": area}
    elif value["section"] is not None:
        raise ValueError("renderer unexpected section measurements")
    if operation == "gltf":
        glb = _object(value["glb"], {"data", "sha256"})
        glb_data = glb["data"]
        if not isinstance(glb_data, str) or len(glb_data) > 4 * ((MAX_GLB + 2) // 3):
            raise ValueError("renderer GLB size")
        raw = base64.b64decode(glb_data, validate=True)
        if (
            len(raw) > MAX_GLB
            or base64.b64encode(raw).decode() != glb["data"]
            or hashlib.sha256(raw).hexdigest() != glb["sha256"]
        ):
            raise ValueError("renderer GLB digest/encoding")
        from hephaestus.core.render.glb_gate import validate_linked_glb

        links = request["links"]
        if links is None:
            raise ValueError("renderer GLB links missing")
        validate_linked_glb(
            raw,
            source_ref=request["source_ref"],
            entries=expected,
            experimental=True,
            bundle_ref=links["bundle_ref"],
            selection_table_ref=links["selection_table_ref"],
        )
        response["glb"] = {"data": glb_data, "sha256": hashlib.sha256(raw).hexdigest()}
    elif value["glb"] is not None:
        raise ValueError("renderer unexpected GLB")
    return response
