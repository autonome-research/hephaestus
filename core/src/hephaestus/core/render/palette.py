"""Bijective selection-ID <-> RGB palette and legend construction (arch §3.3).

A **selection ID** is a non-negative integer naming one selectable topology
occurrence — a solid, a face-within-a-solid, or an edge-within-a-solid. The
mask/selection passes paint every pixel of an occurrence with exactly its ID's
RGB colour; decoding a pixel recovers the ID and, through the legend, the
occurrence's ``{kind, solid_index, topology_index, tag?}`` descriptor.

Bijection. ``id_to_rgb`` encodes ``n`` as the 24-bit big-endian integer
``n + 1`` so ID ``0`` maps to ``(0, 0, 1)`` and the pure-black background
``(0, 0, 0)`` is never a valid occurrence colour. ``rgb_to_id`` inverts it and
rejects the background. The mapping is collision-free and reversible over
``0 .. MAX_SELECTION_ID`` (16 777 214 IDs — far past the ≥100 000 requirement).

Flat, unlit, non-antialiased rendering contract. These colours are only exact
when the pass is rendered with **no lighting and no antialiasing** — every
pixel of an occurrence must be its palette colour verbatim and every silhouette
pixel must be either an exact occurrence colour or the exact background, never a
blend. :mod:`hephaestus.core.render.offscreen` renders these passes through
pyrender's segmentation path (MSAA disabled, per-node flat colour), which
satisfies this contract; ordinary shaded ``rgb`` renders must never be decoded
as a palette.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from hephaestus.core.errors import ValidationError
from opstore.types import JSONValue

__all__ = [
    "BACKGROUND_RGB",
    "MAX_SELECTION_ID",
    "SelectionEntry",
    "SelectionKind",
    "build_legend",
    "hex_to_rgb",
    "id_to_hex",
    "id_to_rgb",
    "legend_to_entries",
    "rgb_to_hex",
    "rgb_to_id",
]

#: The reserved background colour; never a valid occurrence colour.
BACKGROUND_RGB: tuple[int, int, int] = (0, 0, 0)

#: Largest encodable selection ID: ``2**24 - 2`` (``id + 1`` fits in 24 bits and
#: never equals the black background).
MAX_SELECTION_ID = 0xFFFFFF - 1

RGB = tuple[int, int, int]

SelectionKind = Literal["solid", "face", "edge"]


def id_to_rgb(selection_id: int) -> RGB:
    """Encode a selection ID as its unique 8-bit RGB triple (never black)."""
    if selection_id < 0 or selection_id > MAX_SELECTION_ID:
        raise ValidationError(
            f"selection id {selection_id} out of range [0, {MAX_SELECTION_ID}]",
            kind="contract",
        )
    value = selection_id + 1
    return ((value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF)


def rgb_to_id(rgb: RGB) -> int:
    """Decode an RGB triple back to its selection ID; the background raises.

    Inverse of :func:`id_to_rgb`. The pure-black background ``(0, 0, 0)`` is not
    a valid occurrence colour and raises ``validation_error``.
    """
    r, g, b = rgb
    for channel in (r, g, b):
        if channel < 0 or channel > 0xFF:
            raise ValidationError(f"channel {channel} outside [0, 255]", kind="contract")
    value = (r << 16) | (g << 8) | b
    if value == 0:
        raise ValidationError("(0, 0, 0) is the background, not a selection id", kind="contract")
    return value - 1


def rgb_to_hex(rgb: RGB) -> str:
    """``(r, g, b)`` -> ``"#rrggbb"`` (lowercase)."""
    r, g, b = rgb
    return f"#{r:02x}{g:02x}{b:02x}"


def hex_to_rgb(value: str) -> RGB:
    """``"#rrggbb"`` -> ``(r, g, b)``."""
    text = value.lstrip("#")
    if len(text) != 6:
        raise ValidationError(f"malformed hex colour {value!r}", kind="contract")
    try:
        r = int(text[0:2], 16)
        g = int(text[2:4], 16)
        b = int(text[4:6], 16)
    except ValueError as exc:
        raise ValidationError(f"malformed hex colour {value!r}", kind="contract") from exc
    return (r, g, b)


def id_to_hex(selection_id: int) -> str:
    """Selection ID -> ``"#rrggbb"`` palette colour."""
    return rgb_to_hex(id_to_rgb(selection_id))


@dataclass(frozen=True)
class SelectionEntry:
    """One selectable occurrence: the global-table / legend value.

    ``topology_index`` is the position within the owning solid's ``faces()`` /
    ``edges()`` list (or the solid's own index for ``kind="solid"``), matching
    :mod:`hephaestus.core.executor.tags` placement indexing. ``tag`` is the
    §5.3 tag name when the occurrence carries one; ``label`` is the owning
    solid's geometry label when known.
    """

    kind: SelectionKind
    solid_index: int
    topology_index: int
    tag: str | None = None
    label: str | None = None

    def to_json(self) -> dict[str, JSONValue]:
        out: dict[str, JSONValue] = {
            "kind": self.kind,
            "solid_index": self.solid_index,
            "topology_index": self.topology_index,
        }
        if self.tag is not None:
            out["tag"] = self.tag
        if self.label is not None:
            out["label"] = self.label
        return out

    @classmethod
    def from_json(cls, data: Mapping[str, JSONValue]) -> SelectionEntry:
        kind = data.get("kind")
        if kind not in ("solid", "face", "edge"):
            raise ValidationError(f"invalid selection kind {kind!r}", kind="contract")
        solid = data.get("solid_index")
        topo = data.get("topology_index")
        if not isinstance(solid, int) or isinstance(solid, bool):
            raise ValidationError("solid_index must be an int", kind="contract")
        if not isinstance(topo, int) or isinstance(topo, bool):
            raise ValidationError("topology_index must be an int", kind="contract")
        tag = data.get("tag")
        label = data.get("label")
        if tag is not None and not isinstance(tag, str):
            raise ValidationError("tag must be a string or absent", kind="contract")
        if label is not None and not isinstance(label, str):
            raise ValidationError("label must be a string or absent", kind="contract")
        return cls(kind=kind, solid_index=solid, topology_index=topo, tag=tag, label=label)


def build_legend(entries: Mapping[int, SelectionEntry]) -> dict[str, dict[str, JSONValue]]:
    """Legend ``{colour_hex: {kind, solid_index, topology_index, tag?, label?}}``.

    One row per selection ID; the key is that ID's palette colour. Because
    :func:`id_to_rgb` is bijective, distinct IDs never collide on a colour.
    """
    legend: dict[str, dict[str, JSONValue]] = {}
    for selection_id, entry in entries.items():
        colour = id_to_hex(selection_id)
        if colour in legend:  # pragma: no cover - bijection forbids this
            raise ValidationError(f"palette collision on {colour}", kind="contract")
        legend[colour] = entry.to_json()
    return legend


def legend_to_entries(legend: Mapping[str, Mapping[str, JSONValue]]) -> dict[int, SelectionEntry]:
    """Inverse of :func:`build_legend`: reconstruct ``{selection_id: entry}``."""
    entries: dict[int, SelectionEntry] = {}
    for colour, row in legend.items():
        selection_id = rgb_to_id(hex_to_rgb(colour))
        entries[selection_id] = SelectionEntry.from_json(row)
    return entries
