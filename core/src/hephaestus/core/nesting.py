"""Compatibility facade: this module moved to :mod:`hephaestus.geom.nesting`.

Flat-pattern extraction, shelf packing and the DXF/SVG cut-file writers are
now geometry services usable without the executor; see :mod:`hephaestus.geom`.

Compatibility only — re-exports the moved public surface unchanged so existing
``hephaestus.core.nesting`` imports keep working. New code should import from
:mod:`hephaestus.geom.nesting`.
"""

from hephaestus.geom.nesting import (
    BLANK_LAYER,
    COORD_DECIMALS,
    CURVE_SEGMENT_MM,
    CUT_LAYER,
    DEFAULT_MARGIN_MM,
    DEFAULT_SPACING_MM,
    ENGRAVE_LAYER,
    LAYER_COLORS,
    MAX_CURVE_SEGMENTS,
    MIN_CURVE_SEGMENTS,
    PROFILE_LAYER,
    SCORE_LAYER,
    Blank,
    Mark,
    NestedLayout,
    NestingRefusal,
    Placement,
    Profile,
    blank_from_metadata,
    blank_size_literal,
    flat_profiles,
    layout_layers,
    layout_to_dxf,
    layout_to_svg,
    shelf_nest,
)

__all__ = [
    "BLANK_LAYER",
    "COORD_DECIMALS",
    "CURVE_SEGMENT_MM",
    "CUT_LAYER",
    "DEFAULT_MARGIN_MM",
    "DEFAULT_SPACING_MM",
    "ENGRAVE_LAYER",
    "LAYER_COLORS",
    "MAX_CURVE_SEGMENTS",
    "MIN_CURVE_SEGMENTS",
    "PROFILE_LAYER",
    "SCORE_LAYER",
    "Blank",
    "Mark",
    "NestedLayout",
    "NestingRefusal",
    "Placement",
    "Profile",
    "blank_from_metadata",
    "blank_size_literal",
    "flat_profiles",
    "layout_layers",
    "layout_to_dxf",
    "layout_to_svg",
    "shelf_nest",
]
