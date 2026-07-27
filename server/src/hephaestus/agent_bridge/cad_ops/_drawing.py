"""``generate_drawing``: dimensioned / assembly / exploded sheets (PDF + SVG).

A drawing is a *manufacturing document*, so everything on it is derived from
evidence the engine already holds and nothing on it is decorative:

* the **views** come from the Stage 1 render service
  (:mod:`hephaestus.core.render.channels`) over the frozen build artifact, in
  the same deterministic framing ``inspect_part`` uses — the exploded kind is
  literally the ``explode`` channel, so an exploded sheet cannot silently be an
  assembled one;
* the **dimensions** are measured on that same reloaded artifact (overall
  extents, material thickness from opposing faces, bore diameters, and the
  lengths/diameters of *tagged* features recovered through the build's source
  map) and are drawn as leader-and-text annotations in a real PDF text layer —
  never rasterized, because a drawing whose dimensions cannot be extracted is
  not a drawing;
* the **title block** is the part's §5.2 metadata plus the project name and the
  build provenance (source artifact ref and script hash), so the sheet says
  which bytes it describes.

Both files are one deliverable produced through the §7 export contract
(:meth:`~._exports.ExportOps.wal_export`): create-only confined targets,
provenance hashes, GC-root pins, and one replayable WAL row.

Composition is a two-step: everything is placed once onto a device-independent
:class:`Sheet` display list in PDF points (origin bottom-left), then emitted to
PDF via reportlab and to SVG by flipping the Y axis. There is therefore exactly
one layout, and the two files carry the same annotations by construction.
"""

from __future__ import annotations

import base64
import io
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, cast
from xml.sax.saxutils import escape, quoteattr

import numpy as np
from hephaestus.core.dfm import TopologyDescriptor
from hephaestus.core.executor.artifact_geometry import load_brep_shape
from hephaestus.core.kernel.topology import cylindrical_faces, opposing_planar_pairs
from hephaestus.core.project_store.store import blob_hash_of_ref
from hephaestus.core.render.cameras import DEFAULT_MARGIN, ViewSpec, camera_framing, parse_view
from hephaestus.core.types import BuildResult
from opstore.types import JSONValue

from ._base import CadOpError
from ._exports import ExportOps, ExportOutput, FrozenMetadataOps, solid_labels

__all__ = [
    "DRAWING_KINDS",
    "SHEET_SIZES",
    "TITLE_BLOCK_FIELDS",
    "UNSTATED",
    "Dimension",
    "DrawingOps",
    "FrozenMetadataOps",
    "Sheet",
    "dimension_text",
    "principal_dimensions",
    "sheet_to_pdf",
    "sheet_to_svg",
    "solid_labels",
]

#: The three sheet sizes ``tool_schema`` declares, landscape, in PDF points.
SHEET_SIZES: Final[dict[str, tuple[float, float]]] = {
    "A4": (841.89, 595.28),
    "A3": (1190.55, 841.89),
    "letter": (792.0, 612.0),
}

#: Drawing kinds and the render channel each one's primary view uses.
DRAWING_KINDS: Final[dict[str, str]] = {
    "dimensioned": "rgb",
    "assembly": "rgb",
    "exploded": "explode",
}

#: Title-block rows: ``(caption, metadata field)``. Metadata fields are §5.2
#: part attributes; the remaining rows are filled from project/provenance.
TITLE_BLOCK_FIELDS: Final[tuple[tuple[str, str], ...]] = (
    ("PROJECT", "project"),
    ("PART", "part"),
    ("DESCRIPTION", "description"),
    ("MATERIAL", "material_spec"),
    ("PROCESS", "process"),
    ("TOLERANCE", "general_tolerance"),
    ("FINISH", "finish"),
    ("DRAWING", "drawing"),
    ("SOURCE ARTIFACT", "source_artifact_ref"),
    ("SCRIPT SHA-256", "script_hash"),
)

#: Placeholder for a title-block field the part never declared. A blank cell
#: would read as "no requirement"; this reads as "not stated", which is true.
UNSTATED: Final[str] = "NOT STATED"

#: Per-sheet caps: a schedule is a drawing, not a database dump.
MAX_FEATURE_DIMENSIONS: Final[int] = 12
MAX_SOLID_DIMENSIONS: Final[int] = 4

#: Rendered view pixel size (the sheet scales it; PNGs stay small and fast).
VIEW_WIDTH: Final[int] = 900
VIEW_HEIGHT: Final[int] = 640

# --------------------------------------------------------------------------
# dimensions


@dataclass(frozen=True)
class Dimension:
    """One measured dimension and the exact string the sheet prints for it."""

    id: str
    label: str
    value: float
    kind: str  # "linear" | "diameter" | "thickness"
    unit: str = "mm"

    @property
    def text(self) -> str:
        return dimension_text(self.value, self.kind)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "id": self.id,
            "label": self.label,
            "text": self.text,
            "value": round(self.value, 4),
            "unit": self.unit,
            "kind": self.kind,
        }


def dimension_text(value: float, kind: str) -> str:
    """The printed form of a dimension: one decimal, ``Ø`` for a diameter.

    Fixed on purpose: the G6 gate extracts these strings from the PDF text
    layer, so the format is part of the contract rather than a rendering
    detail. ``Ø`` is U+00D8, which every PDF base font encodes.
    """
    return f"Ø{value:.1f}" if kind == "diameter" else f"{value:.1f}"


def _bbox(shape: Any) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    box = shape.bounding_box()
    return (
        (float(box.min.X), float(box.min.Y), float(box.min.Z)),
        (float(box.max.X), float(box.max.Y), float(box.max.Z)),
    )


def principal_dimensions(
    shape: Any,
    *,
    labels: Sequence[str] = (),
    tags: Mapping[str, TopologyDescriptor] | None = None,
) -> tuple[Dimension, ...]:
    """The dimensions a sheet prints, in a fixed order.

    Overall extents first (they are what a reader looks for), then the material
    thickness, then bore diameters, then each labeled solid's footprint, then
    the tagged features. Everything is measured on the reloaded artifact, and
    every list is capped and deterministically ordered so two runs over the same
    bytes print the same sheet.
    """
    lo, hi = _bbox(shape)
    out: list[Dimension] = [
        Dimension(f"overall_{axis}", f"OVERALL {axis.upper()}", hi[i] - lo[i], "linear")
        for i, axis in enumerate("xyz")
    ]
    solids: list[Any] = list(shape.solids())
    thickness = _material_thickness(solids)
    if thickness is not None:
        out.append(Dimension("thickness", "MATERIAL THICKNESS", thickness, "thickness"))
    for index, diameter in enumerate(_bore_diameters(solids)):
        out.append(Dimension(f"bore_{index + 1}", "BORE", diameter, "diameter"))
    for position, solid in enumerate(solids[:MAX_SOLID_DIMENSIONS]):
        label = labels[position] if position < len(labels) else f"solid#{position + 1}"
        slo, shi = _bbox(solid)
        for i, axis in enumerate("xy"):
            out.append(
                Dimension(
                    f"solid{position + 1}_{axis}",
                    f"{label.upper()} {axis.upper()}",
                    shi[i] - slo[i],
                    "linear",
                )
            )
    out.extend(_tag_dimensions(solids, tags or {}))
    return tuple(out[: 3 + MAX_FEATURE_DIMENSIONS])


def _material_thickness(solids: Sequence[Any]) -> float | None:
    """The thinnest opposing-face wall across the artifact's solids."""
    best: float | None = None
    for solid in solids:
        pairs, _truncated = opposing_planar_pairs(solid)
        for pair in pairs:
            if best is None or pair.thickness_mm < best:
                best = pair.thickness_mm
    return best


def _bore_diameters(solids: Sequence[Any]) -> tuple[float, ...]:
    """Distinct through/blind bore diameters (full internal cylinders), sorted."""
    seen: list[float] = []
    for solid in solids:
        for cylinder in cylindrical_faces(solid):
            if not (cylinder.internal and cylinder.full):
                continue
            diameter = 2.0 * cylinder.radius
            if not any(abs(diameter - existing) < 1e-6 for existing in seen):
                seen.append(diameter)
    return tuple(sorted(seen))[:4]


def _tag_dimensions(
    solids: Sequence[Any], tags: Mapping[str, TopologyDescriptor]
) -> tuple[Dimension, ...]:
    """Lengths of tagged edges and diameters of tagged cylindrical faces.

    Tags are the script's own names for features, so a tagged dimension is the
    one the author cared about. Face tags that are not cylindrical carry an area
    rather than a length and are left off the sheet instead of being printed as
    if they were a size.
    """
    out: list[Dimension] = []
    for name in sorted(tags):
        descriptor = tags[name]
        if descriptor.solid_id < 0 or descriptor.solid_id >= len(solids):
            continue
        solid = solids[descriptor.solid_id]
        if descriptor.kind == "edge":
            edges: list[Any] = list(solid.edges())
            if 0 <= descriptor.topology_index < len(edges):
                length = float(edges[descriptor.topology_index].length)
                out.append(Dimension(f"tag:{name}", name.upper(), length, "linear"))
        elif descriptor.kind == "face":
            for cylinder in cylindrical_faces(solid):
                if cylinder.index == descriptor.topology_index:
                    out.append(
                        Dimension(f"tag:{name}", name.upper(), 2.0 * cylinder.radius, "diameter")
                    )
                    break
    return tuple(out)


# --------------------------------------------------------------------------
# the device-independent sheet


@dataclass(frozen=True)
class _Text:
    x: float
    y: float
    value: str
    size: float
    anchor: str  # "start" | "middle" | "end"
    bold: bool


@dataclass(frozen=True)
class _Line:
    x1: float
    y1: float
    x2: float
    y2: float
    weight: float


@dataclass(frozen=True)
class _Rect:
    x: float
    y: float
    width: float
    height: float
    weight: float


@dataclass(frozen=True)
class _Image:
    x: float
    y: float
    width: float
    height: float
    png: bytes


@dataclass
class Sheet:
    """A page as an ordered display list in PDF points (origin bottom-left)."""

    width: float
    height: float
    title: str
    items: list[_Text | _Line | _Rect | _Image] = field(
        default_factory=list["_Text | _Line | _Rect | _Image"]
    )

    def text(
        self,
        x: float,
        y: float,
        value: str,
        *,
        size: float = 7.5,
        anchor: str = "start",
        bold: bool = False,
    ) -> None:
        if value:
            self.items.append(_Text(x, y, value, size, anchor, bold))

    def line(self, x1: float, y1: float, x2: float, y2: float, *, weight: float = 0.5) -> None:
        self.items.append(_Line(x1, y1, x2, y2, weight))

    def rect(self, x: float, y: float, width: float, height: float, *, weight: float = 0.7) -> None:
        self.items.append(_Rect(x, y, width, height, weight))

    def image(self, x: float, y: float, width: float, height: float, png: bytes) -> None:
        self.items.append(_Image(x, y, width, height, png))

    def texts(self) -> tuple[str, ...]:
        return tuple(item.value for item in self.items if isinstance(item, _Text))


def sheet_to_pdf(sheet: Sheet) -> bytes:
    """Render a sheet to a single-page PDF with a real (extractable) text layer.

    ``invariant=1`` fixes reportlab's document id and dates, so the same sheet
    produces the same bytes — an export's content hash has to mean something.
    """
    try:
        from reportlab.lib.utils import ImageReader
        from reportlab.pdfgen.canvas import Canvas
    except ImportError as exc:  # pragma: no cover - reportlab is a core dependency
        raise CadOpError(
            "capability_not_available",
            f"PDF composition needs reportlab, which is not importable ({exc})",
            data={"code": "capability_not_available"},
        ) from exc

    buffer = io.BytesIO()
    # reportlab ships no type stubs for the canvas surface; the interop stays
    # inside this function's explicitly Any-typed local.
    canvas: Any = Canvas(buffer, pagesize=(sheet.width, sheet.height), invariant=1)
    canvas.setTitle(sheet.title)
    canvas.setAuthor("Hephaestus")
    canvas.setSubject("Manufacturing drawing")
    for item in sheet.items:
        if isinstance(item, _Text):
            canvas.setFont("Helvetica-Bold" if item.bold else "Helvetica", item.size)
            if item.anchor == "middle":
                canvas.drawCentredString(item.x, item.y, item.value)
            elif item.anchor == "end":
                canvas.drawRightString(item.x, item.y, item.value)
            else:
                canvas.drawString(item.x, item.y, item.value)
        elif isinstance(item, _Line):
            canvas.setLineWidth(item.weight)
            canvas.line(item.x1, item.y1, item.x2, item.y2)
        elif isinstance(item, _Rect):
            canvas.setLineWidth(item.weight)
            canvas.rect(item.x, item.y, item.width, item.height, stroke=1, fill=0)
        else:
            canvas.drawImage(
                ImageReader(io.BytesIO(item.png)),
                item.x,
                item.y,
                width=item.width,
                height=item.height,
                preserveAspectRatio=True,
                anchor="c",
                mask="auto",
            )
    canvas.showPage()
    canvas.save()
    return buffer.getvalue()


def sheet_to_svg(sheet: Sheet) -> bytes:
    """Render the same sheet to standalone SVG (Y flipped, images inlined)."""

    def fy(y: float) -> float:
        return sheet.height - y

    parts: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'width="{sheet.width:.2f}pt" height="{sheet.height:.2f}pt" '
        f'viewBox="0 0 {sheet.width:.2f} {sheet.height:.2f}">',
        f"<title>{escape(sheet.title)}</title>",
        f'<rect x="0" y="0" width="{sheet.width:.2f}" height="{sheet.height:.2f}" fill="#ffffff"/>',
    ]
    for item in sheet.items:
        if isinstance(item, _Text):
            weight = ' font-weight="bold"' if item.bold else ""
            parts.append(
                f'<text x="{item.x:.2f}" y="{fy(item.y):.2f}" '
                f'font-family="Helvetica, Arial, sans-serif" font-size="{item.size:.2f}" '
                f'text-anchor="{item.anchor}"{weight} fill="#111111">{escape(item.value)}</text>'
            )
        elif isinstance(item, _Line):
            parts.append(
                f'<line x1="{item.x1:.2f}" y1="{fy(item.y1):.2f}" x2="{item.x2:.2f}" '
                f'y2="{fy(item.y2):.2f}" stroke="#111111" stroke-width="{item.weight:.2f}"/>'
            )
        elif isinstance(item, _Rect):
            parts.append(
                f'<rect x="{item.x:.2f}" y="{fy(item.y + item.height):.2f}" '
                f'width="{item.width:.2f}" height="{item.height:.2f}" fill="none" '
                f'stroke="#111111" stroke-width="{item.weight:.2f}"/>'
            )
        else:
            encoded = base64.b64encode(item.png).decode("ascii")
            href = quoteattr(f"data:image/png;base64,{encoded}")
            parts.append(
                f'<image x="{item.x:.2f}" y="{fy(item.y + item.height):.2f}" '
                f'width="{item.width:.2f}" height="{item.height:.2f}" '
                f'preserveAspectRatio="xMidYMid meet" xlink:href={href}/>'
            )
    parts.append("</svg>")
    return ("\n".join(parts) + "\n").encode("utf-8")


# --------------------------------------------------------------------------
# composition


@dataclass(frozen=True)
class _ViewImage:
    """One rendered view plus where the geometry's extents land inside it."""

    name: str
    caption: str
    png: bytes
    #: Fraction of the image occupied by the bbox silhouette, per axis.
    u_fraction: float
    v_fraction: float


def _extent_fractions(
    lo: tuple[float, float, float], hi: tuple[float, float, float], view: ViewSpec
) -> tuple[float, float]:
    """How much of the framed image the bbox silhouette actually spans.

    The render service fits the camera to the box plus :data:`DEFAULT_MARGIN`
    and to the viewport aspect, so the geometry never fills the frame. Recomputing
    that fit here is what lets a dimension line be drawn *on the geometry's
    edges* instead of on the image border.
    """
    framing = camera_framing(lo, hi, view, width=VIEW_WIDTH, height=VIEW_HEIGHT)
    centre = np.array([(lo[i] + hi[i]) / 2.0 for i in range(3)], dtype=np.float64)
    corners = np.array(
        [[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])],
        dtype=np.float64,
    )
    rel = corners - centre
    half_u = float(np.max(np.abs(rel @ framing.pose[:3, 0])))
    half_v = float(np.max(np.abs(rel @ framing.pose[:3, 1])))
    return (
        min(1.0, half_u / framing.xmag if framing.xmag > 0 else 1.0),
        min(1.0, half_v / framing.ymag if framing.ymag > 0 else 1.0),
    )


def _draw_border(sheet: Sheet, margin: float) -> None:
    sheet.rect(margin, margin, sheet.width - 2 * margin, sheet.height - 2 * margin, weight=1.0)


def _draw_title_block(sheet: Sheet, fields: Mapping[str, str], *, margin: float) -> float:
    """The bottom-right title block; returns its top edge (the drawing floor)."""
    rows = len(TITLE_BLOCK_FIELDS)
    row_h = 12.0
    width = min(330.0, sheet.width - 2 * margin)
    height = rows * row_h
    x = sheet.width - margin - width
    y = margin
    sheet.rect(x, y, width, height, weight=0.9)
    for index, (caption, key) in enumerate(reversed(TITLE_BLOCK_FIELDS)):
        row_y = y + index * row_h
        if index:
            sheet.line(x, row_y, x + width, row_y, weight=0.4)
        sheet.text(x + 5.0, row_y + 3.6, caption, size=6.0, bold=True)
        sheet.text(x + 96.0, row_y + 3.6, fields.get(key, UNSTATED), size=7.0)
    sheet.line(x + 92.0, y, x + 92.0, y + height, weight=0.4)
    return y + height


def _draw_view(
    sheet: Sheet, image: _ViewImage, x: float, y: float, width: float, height: float
) -> tuple[float, float, float, float]:
    """Place one view and return the rectangle its geometry silhouette spans."""
    sheet.rect(x, y, width, height, weight=0.4)
    sheet.text(x + 3.0, y + height - 9.0, image.caption, size=7.0, bold=True)
    if image.png:
        sheet.image(x, y, width, height, image.png)
    else:
        sheet.text(x + width / 2.0, y + height / 2.0, "VIEW UNAVAILABLE", anchor="middle", size=8.0)
    cx, cy = x + width / 2.0, y + height / 2.0
    half_w = width * image.u_fraction / 2.0
    half_h = height * image.v_fraction / 2.0
    return (cx - half_w, cy - half_h, cx + half_w, cy + half_h)


def _draw_horizontal_dimension(
    sheet: Sheet, x1: float, x2: float, y: float, text: str, label: str
) -> None:
    sheet.line(x1, y, x2, y)
    for x in (x1, x2):
        sheet.line(x, y - 3.0, x, y + 3.0)
    sheet.text((x1 + x2) / 2.0, y + 3.5, text, anchor="middle", size=8.0, bold=True)
    sheet.text((x1 + x2) / 2.0, y - 9.5, label, anchor="middle", size=5.5)


def _draw_vertical_dimension(
    sheet: Sheet, y1: float, y2: float, x: float, text: str, label: str
) -> None:
    sheet.line(x, y1, x, y2)
    for y in (y1, y2):
        sheet.line(x - 3.0, y, x + 3.0, y)
    sheet.text(x - 4.0, (y1 + y2) / 2.0 + 1.0, text, anchor="end", size=8.0, bold=True)
    sheet.text(x - 4.0, (y1 + y2) / 2.0 - 7.0, label, anchor="end", size=5.5)


def _draw_schedule(
    sheet: Sheet,
    dimensions: Sequence[Dimension],
    *,
    x: float,
    top: float,
    bottom: float,
    anchor: tuple[float, float],
) -> None:
    """The feature-dimension schedule: one leader per row back to the view."""
    sheet.text(x, top, "FEATURE DIMENSIONS", size=7.0, bold=True)
    row_y = top - 13.0
    for dimension in dimensions:
        if row_y < bottom:
            break
        sheet.line(anchor[0], anchor[1], x - 6.0, row_y + 2.0, weight=0.35)
        sheet.line(x - 6.0, row_y + 2.0, x - 2.0, row_y + 2.0, weight=0.35)
        sheet.text(x, row_y, dimension.text, size=7.5, bold=True)
        sheet.text(x + 42.0, row_y, dimension.label, size=6.5)
        row_y -= 11.0


def compose_sheet(
    *,
    sheet_name: str,
    kind: str,
    title: str,
    views: Sequence[_ViewImage],
    dimensions: Sequence[Dimension],
    title_block: Mapping[str, str],
) -> Sheet:
    """Lay out one drawing sheet: border, views, dimensions, title block."""
    width, height = SHEET_SIZES[sheet_name]
    sheet = Sheet(width=width, height=height, title=title)
    margin = 18.0
    _draw_border(sheet, margin)
    block_top = _draw_title_block(sheet, title_block, margin=margin)

    schedule_x = width - margin - 150.0
    field_left = margin + 46.0
    field_right = schedule_x - 24.0
    field_bottom = block_top + 34.0
    field_top = height - margin - 22.0
    sheet.text(margin + 6.0, field_top + 8.0, title, size=9.0, bold=True)

    primary = views[0] if views else _ViewImage("iso", "VIEW", b"", 1.0, 1.0)
    secondary = views[1] if len(views) > 1 else None
    if secondary is None:
        frame = _draw_view(
            sheet,
            primary,
            field_left,
            field_bottom,
            field_right - field_left,
            field_top - field_bottom,
        )
        second_frame = None
    else:
        split = (field_right - field_left) * 0.62
        frame = _draw_view(
            sheet, primary, field_left, field_bottom, split - 10.0, field_top - field_bottom
        )
        second_frame = _draw_view(
            sheet,
            secondary,
            field_left + split,
            field_bottom,
            field_right - field_left - split,
            field_top - field_bottom,
        )

    by_id = {dimension.id: dimension for dimension in dimensions}
    if kind == "dimensioned":
        x_dim, y_dim, z_dim = (by_id.get(f"overall_{axis}") for axis in "xyz")
        if x_dim is not None:
            _draw_horizontal_dimension(
                sheet, frame[0], frame[2], frame[1] - 16.0, x_dim.text, x_dim.label
            )
        if y_dim is not None:
            _draw_vertical_dimension(
                sheet, frame[1], frame[3], frame[0] - 12.0, y_dim.text, y_dim.label
            )
        if z_dim is not None and second_frame is not None:
            _draw_vertical_dimension(
                sheet,
                second_frame[1],
                second_frame[3],
                second_frame[0] - 12.0,
                z_dim.text,
                z_dim.label,
            )
        remaining = [d for d in dimensions if d.id not in {"overall_x", "overall_y", "overall_z"}]
    else:
        remaining = list(dimensions)
    _draw_schedule(
        sheet,
        remaining,
        x=schedule_x,
        top=field_top,
        bottom=field_bottom,
        anchor=((frame[0] + frame[2]) / 2.0, (frame[1] + frame[3]) / 2.0),
    )
    return sheet


# --------------------------------------------------------------------------
# the operation


class DrawingOps(ExportOps, FrozenMetadataOps):
    """``generate_drawing``: render, measure, compose, export (PDF + SVG)."""

    def generate_drawing(
        self,
        name: str,
        kind: str,
        *,
        sheet: str = "A4",
        artifact_ref: str | None = None,
        target: str | None = None,
        op_id: str,
    ) -> dict[str, Any]:
        """A dimensioned / assembly / exploded sheet of one frozen artifact."""
        if kind not in DRAWING_KINDS:
            raise CadOpError(
                "invalid_params",
                f"unknown drawing kind {kind!r} (expected {', '.join(sorted(DRAWING_KINDS))})",
            )
        if sheet not in SHEET_SIZES:
            raise CadOpError(
                "invalid_params",
                f"unknown sheet {sheet!r} (expected {', '.join(SHEET_SIZES)})",
            )

        def produce(
            source_ref: str, scratch: Path
        ) -> tuple[Sequence[ExportOutput], Mapping[str, Any]]:
            return self._compose(name, kind, sheet, source_ref, scratch)

        result = self.wal_export(
            op_id=op_id,
            part=name,
            operation="generate_drawing",
            variant=f"{kind}:{sheet}",
            payload={"sheet": sheet},
            artifact_ref=artifact_ref,
            target=target,
            stem=f"{name}-{kind}",
            produce=produce,
        )
        # Name each file by what it is: the schema promises ``pdf`` and ``svg``
        # next to the generic ``paths`` every export result carries.
        for path in cast("list[str]", result.get("paths", [])):
            result["pdf" if path.endswith(".pdf") else "svg"] = path
        return result

    def _compose(
        self, name: str, kind: str, sheet_name: str, source_ref: str, scratch: Path
    ) -> tuple[Sequence[ExportOutput], Mapping[str, Any]]:
        """Measure and draw the frozen artifact; returns the PDF + SVG pair."""
        shape: Any = load_brep_shape(
            self._store.blobs.get(blob_hash_of_ref(source_ref)), scratch_dir=scratch
        )
        result = self.frozen_result(name, source_ref)
        solids: list[Any] = list(shape.solids())
        labels = solid_labels(result, len(solids))
        dimensions = principal_dimensions(
            shape, labels=labels, tags=self.artifact_tags(result, source_ref)
        )
        views = self._render_views(shape, kind)
        metadata = self.frozen_script_metadata(name, source_ref)
        title = f"{name.upper()} — {kind.upper()}"
        block = self._title_block(name, kind, sheet_name, source_ref, result, metadata)
        composed = compose_sheet(
            sheet_name=sheet_name,
            kind=kind,
            title=title,
            views=views,
            dimensions=dimensions,
            title_block=block,
        )
        outputs = (
            ExportOutput("pdf", sheet_to_pdf(composed)),
            ExportOutput("svg", sheet_to_svg(composed)),
        )
        extra: dict[str, Any] = {
            "status": "ok",
            "kind": kind,
            "sheet": sheet_name,
            "views": [view.name for view in views if view.png],
            "dimensions": [dimension.to_json() for dimension in dimensions],
            "title_block": dict(block),
        }
        return outputs, extra

    # -- inputs ------------------------------------------------------------

    def _title_block(
        self,
        name: str,
        kind: str,
        sheet_name: str,
        source_ref: str,
        result: BuildResult | None,
        metadata: Mapping[str, str],
    ) -> dict[str, str]:
        fields: dict[str, str] = {
            "project": self._layout.manifest.name,
            "part": name,
            "drawing": f"{kind} / {sheet_name} / mm / NOT TO SCALE",
            "source_artifact_ref": source_ref,
            "script_hash": (
                result.input_hashes.script if result is not None else "unavailable (historical)"
            ),
        }
        for _, key in TITLE_BLOCK_FIELDS:
            if key in fields:
                continue
            value = metadata.get(key, "")
            fields[key] = value.strip() or UNSTATED
        return fields

    # -- views -------------------------------------------------------------

    def _render_views(self, shape: Any, kind: str) -> tuple[_ViewImage, ...]:
        """The sheet's views, from the Stage 1 render service.

        A dimensioned sheet gets the two orthographic views its dimension lines
        are drawn against (top carries X and Y, front carries Z); assembly and
        exploded sheets get the isometric the reader actually wants plus a top
        view for orientation. A renderer that cannot start yields empty images
        and a sheet that says so: the measured dimensions and the title block
        are still true, and refusing the whole document would destroy evidence
        that does not depend on a GPU.
        """
        wanted: tuple[tuple[str, str], ...] = (
            (("+Z", "TOP (X-Y)"), ("+Y", "FRONT (X-Z)"))
            if kind == "dimensioned"
            else (("iso", "ISOMETRIC"), ("+Z", "TOP (X-Y)"))
        )
        lo, hi = _bbox(shape)
        fractions = {name: _extent_fractions(lo, hi, parse_view(name)) for name, _ in wanted}
        pngs = self._render_pngs(shape, kind, tuple(name for name, _ in wanted))
        return tuple(
            _ViewImage(
                name=name,
                caption=caption if name in pngs else f"{caption} (UNAVAILABLE)",
                png=pngs.get(name, b""),
                u_fraction=fractions[name][0],
                v_fraction=fractions[name][1],
            )
            for name, caption in wanted
        )

    def _render_pngs(self, shape: Any, kind: str, views: Sequence[str]) -> dict[str, bytes]:
        """Deterministic PNGs for ``views``; empty when the renderer is unavailable."""
        from hephaestus.core.render.channels import (
            RenderOptions,
            render_channel,
            scene_from_shape,
        )

        channel = DRAWING_KINDS[kind]
        options = RenderOptions(
            width=VIEW_WIDTH, height=VIEW_HEIGHT, margin=DEFAULT_MARGIN, explode_t=1.0
        )
        try:
            scene = scene_from_shape(shape)
            rendered = render_channel(scene, list(views), cast("Any", channel), options)
        except Exception:
            # An offscreen renderer that will not start (no llvmpipe, no EGL) is
            # a missing capability, not a broken drawing: see _render_views.
            return {}
        return {name: view.png() for name, view in rendered.items()}
