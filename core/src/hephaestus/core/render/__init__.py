"""Render service foundation (arch §3.3): cameras, tessellation, offscreen
software rendering, the bijective selection palette/legend, and immutable
render/selection-bundle artifacts over ``opstore``.

The heavier submodules (:mod:`tessellate`, :mod:`offscreen`) import the OCP /
trimesh / pyrender stacks and are imported lazily by callers rather than
re-exported here, so importing :mod:`hephaestus.core.render` for the pure
palette/camera/bundle types does not pull the renderer.
"""

from __future__ import annotations

from hephaestus.core.render.cameras import (
    DEFAULT_MARGIN,
    STANDARD_VIEWS,
    CameraFraming,
    ViewSpec,
    camera_framing,
    parse_view,
    standard_view_names,
)
from hephaestus.core.render.palette import (
    BACKGROUND_RGB,
    MAX_SELECTION_ID,
    SelectionEntry,
    SelectionKind,
    build_legend,
    hex_to_rgb,
    id_to_hex,
    id_to_rgb,
    legend_to_entries,
    rgb_to_hex,
    rgb_to_id,
)

__all__ = [
    "BACKGROUND_RGB",
    "DEFAULT_MARGIN",
    "MAX_SELECTION_ID",
    "STANDARD_VIEWS",
    "CameraFraming",
    "SelectionEntry",
    "SelectionKind",
    "ViewSpec",
    "build_legend",
    "camera_framing",
    "hex_to_rgb",
    "id_to_hex",
    "id_to_rgb",
    "legend_to_entries",
    "parse_view",
    "rgb_to_hex",
    "rgb_to_id",
    "standard_view_names",
]
