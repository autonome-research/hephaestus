"""Byte-level acceptance tests for exported CAD payloads.

Grading does not trust an exporter's success status: it reads the bytes back and
checks that each format's structural invariants hold (an ISO-10303 header, a
consistent STL triangle count, a 3MF part containing triangles, and so on). For
flat sheet layouts it additionally counts the outermost closed profiles a
nesting or CAM step would see, and for a drawing sheet it reads the PDF's **text
layer** — a dimension that was rasterized into the view image is not a dimension
a shop can read, and it must not be able to pass a drawing task.

:func:`pdf_text` is deliberately dependency-free (``pypdf`` is a dev-only
extra, and grading ships with the wheel): it decodes the page content streams
and collects the operands of the text-showing operators. It is not a general PDF
reader — it reads the PDFs *this* project generates, and
``test_bench_corpus.py::test_the_graders_pdf_reader_agrees_with_pypdf`` pins it
against pypdf (which ``server/tests/test_drawings_docs.py`` uses for the same
claim) so the two can never drift apart unnoticed.
"""

from __future__ import annotations

import base64
import importlib
import io
import itertools
import re
import struct
import tempfile
import zipfile
import zlib
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Final, cast

__all__ = [
    "dxf_layer_extents",
    "dxf_profile_count",
    "pdf_text",
    "validate_export_bytes",
]


def _closed_loop_components(
    segments: Sequence[tuple[tuple[float, float], tuple[float, float]]],
) -> list[tuple[float, float, float, float]]:
    """Connected components of a 2D segment soup, as ``(xmin, ymin, xmax, ymax)``."""
    parent: dict[tuple[float, float], tuple[float, float]] = {}

    def find(node: tuple[float, float]) -> tuple[float, float]:
        parent.setdefault(node, node)
        root = node
        while parent[root] != root:
            root = parent[root]
        while parent[node] != root:
            parent[node], node = root, parent[node]
        return root

    def union(a: tuple[float, float], b: tuple[float, float]) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for start, end in segments:
        union(start, end)
    groups: dict[tuple[float, float], list[tuple[float, float]]] = {}
    for node in list(parent):
        groups.setdefault(find(node), []).append(node)
    boxes: list[tuple[float, float, float, float]] = []
    for points in groups.values():
        xs = [x for x, _ in points]
        ys = [y for _, y in points]
        boxes.append((min(xs), min(ys), max(xs), max(ys)))
    return boxes


def _dxf_segments(
    data: bytes, *, layer: str | None
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Every drawn segment of a DXF (optionally restricted to one layer)."""
    # Imported lazily (only DXF exports need ezdxf) and through an Any-typed
    # module handle: ezdxf ships no complete public typing surface.
    ezdxf: Any = importlib.import_module("ezdxf")
    dxf_error: type[Exception] = cast(
        "type[Exception]", importlib.import_module("ezdxf.lldxf.const").DXFStructureError
    )

    def key(x: float, y: float) -> tuple[float, float]:
        return (round(float(x), 3), round(float(y), 3))

    segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
    with tempfile.TemporaryDirectory(prefix="heph-bench-dxf-") as scratch:
        path = Path(scratch) / "layout.dxf"
        path.write_bytes(data)
        try:
            doc: Any = ezdxf.readfile(str(path))
        except (dxf_error, OSError) as exc:  # pragma: no cover - malformed export
            raise ValueError(f"unreadable DXF export: {exc}") from exc
        for entity in doc.modelspace():
            if layer is not None and str(entity.dxf.layer) != layer:
                continue
            kind = str(entity.dxftype())
            points: list[tuple[float, float]] = []
            if kind == "LINE":
                start = entity.dxf.start
                end = entity.dxf.end
                points = [key(start.x, start.y), key(end.x, end.y)]
            elif kind in ("ARC", "CIRCLE", "ELLIPSE", "SPLINE"):
                points = [key(p[0], p[1]) for p in entity.flattening(0.05)]
            elif kind == "LWPOLYLINE":
                points = [key(p[0], p[1]) for p in entity.get_points()]
            elif kind == "POLYLINE":
                points = [key(v.dxf.location.x, v.dxf.location.y) for v in entity.vertices]
            else:  # pragma: no cover - exporters emit only the geometry above
                continue
            segments.extend(itertools.pairwise(points))
            closed = kind in ("CIRCLE", "ELLIPSE") or bool(getattr(entity, "closed", False))
            if closed and len(points) > 2:
                segments.append((points[-1], points[0]))
    return segments


def dxf_profile_count(data: bytes, *, layer: str | None = None) -> int:
    """Count outermost closed profiles in a DXF cut layout.

    The ``as_built`` DXF of a flat sheet layout is a hidden-line projection: each
    panel outline becomes one connected component of line/arc segments. Components
    fully contained in another component's bounding box (mortises, holes) are
    *interior* loops and are not counted, so the number returned is the number of
    cut profiles a nesting/CAM step would see.

    ``layer`` restricts the count to one DXF layer. A ``nested_sheet`` layout
    draws the stock rectangle on its own layer and that rectangle encloses every
    profile, so counting across all layers there would report exactly one —
    nested layouts pass the profile layer.
    """
    boxes = _closed_loop_components(_dxf_segments(data, layer=layer))
    outer = 0
    for index, box in enumerate(boxes):
        nested = any(
            other[0] <= box[0]
            and other[1] <= box[1]
            and other[2] >= box[2]
            and other[3] >= box[3]
            and (other[2] - other[0], other[3] - other[1]) != (box[2] - box[0], box[3] - box[1])
            for j, other in enumerate(boxes)
            if j != index
        )
        if not nested:
            outer += 1
    return outer


def dxf_layer_extents(data: bytes, layer: str) -> tuple[float, float, float, float] | None:
    """``(min_x, min_y, max_x, max_y)`` of everything drawn on ``layer`` (or None)."""
    points = [point for segment in _dxf_segments(data, layer=layer) for point in segment]
    if not points:
        return None
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    return (min(xs), min(ys), max(xs), max(ys))


#: Text-showing operators of a PDF content stream, with their string operand(s).
#: ``Tj``/``'``/``"`` take one string; ``TJ`` takes an array of strings and
#: kerning numbers. reportlab emits ``Tj``, but the array form is cheap to read.
_PDF_STREAM_RE: Final[re.Pattern[bytes]] = re.compile(rb"stream\r?\n(.*?)endstream", re.S)
_PDF_SHOW_RE: Final[re.Pattern[bytes]] = re.compile(rb"(\((?:\\.|[^\\()])*\))\s*(?:Tj|TJ|'|\")")
_PDF_ESCAPES: Final[dict[bytes, bytes]] = {
    b"n": b"\n",
    b"r": b"\r",
    b"t": b"\t",
    b"b": b"\b",
    b"f": b"\f",
    b"(": b"(",
    b")": b")",
    b"\\": b"\\",
}


def _pdf_decode_literal(raw: bytes) -> str:
    """One PDF literal string ``(...)`` -> text (octal + backslash escapes)."""
    out = bytearray()
    index = 0
    body = raw[1:-1]
    while index < len(body):
        char = body[index : index + 1]
        if char != b"\\":
            out += char
            index += 1
            continue
        nxt = body[index + 1 : index + 2]
        if nxt in _PDF_ESCAPES:
            out += _PDF_ESCAPES[nxt]
            index += 2
            continue
        if nxt.isdigit():
            digits = b""
            while len(digits) < 3:
                nibble = body[index + 1 + len(digits) : index + 2 + len(digits)]
                if not nibble.isdigit():
                    break
                digits += nibble
            out.append(int(digits, 8) & 0xFF)
            index += 1 + len(digits)
            continue
        out += nxt
        index += 2
    # Base-14 fonts are written in WinAnsiEncoding, which agrees with latin-1
    # over every character a drawing sheet prints (``Ø`` is 0xD8 in both).
    return out.decode("latin-1")


def _pdf_streams(data: bytes) -> list[bytes]:
    """Every decoded content stream of a PDF (ASCII85 + Flate, Flate, or raw)."""

    def ascii85_flate(payload: bytes) -> bytes:
        return zlib.decompress(base64.a85decode(payload, adobe=True))

    def identity(payload: bytes) -> bytes:
        return payload

    decoders: tuple[Callable[[bytes], bytes], ...] = (
        ascii85_flate,
        zlib.decompress,
        identity,
    )
    decoded: list[bytes] = []
    for match in _PDF_STREAM_RE.finditer(data):
        raw = match.group(1).strip()
        for decode in decoders:
            try:
                decoded.append(decode(raw))
            except Exception:  # a stream we cannot decode carries no text for us
                continue
            break
    return decoded


def pdf_text(data: bytes) -> str:
    """The text a PDF's content streams actually show, newline-separated.

    Only real text operators are read, so a "dimension" that was baked into a
    rasterized view image contributes nothing — which is precisely the claim a
    drawing task is making when it says the sheet is dimensioned.
    """
    shown: list[str] = []
    for stream in _pdf_streams(data):
        for match in _PDF_SHOW_RE.finditer(stream):
            shown.append(_pdf_decode_literal(match.group(1)))
    return "\n".join(shown)


def validate_export_bytes(fmt: str, data: bytes) -> str | None:
    """``None`` when ``data`` is a well-formed ``fmt`` payload, else the reason."""
    if not data:
        return "empty_export"
    if fmt == "step":
        head = data[:256]
        if b"ISO-10303-21" not in head:
            return "step_missing_iso10303_header"
    elif fmt == "stl":
        if len(data) < 84:
            return "stl_truncated"
        (count,) = struct.unpack_from("<I", data, 80)
        if count == 0 or len(data) < 84 + count * 50:
            return "stl_triangle_count_mismatch"
    elif fmt == "gltf":
        if data[:4] != b"glTF":
            return "gltf_missing_magic"
    elif fmt == "3mf":
        if not zipfile.is_zipfile(io.BytesIO(data)):
            return "3mf_not_a_zip"
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = set(zf.namelist())
            if "3D/3dmodel.model" not in names:
                return "3mf_missing_model_part"
            model = zf.read("3D/3dmodel.model")
        if b"<triangle" not in model:
            return "3mf_model_has_no_triangles"
    elif fmt == "dxf":
        if b"SECTION" not in data or b"ENTITIES" not in data:
            return "dxf_missing_entities_section"
    elif fmt == "svg":
        if b"<svg" not in data[:2048]:
            return "svg_missing_root_element"
    return None
