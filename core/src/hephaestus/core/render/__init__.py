"""Render service foundation (arch §3.3): cameras, tessellation, offscreen
software rendering, the bijective selection palette/legend, and immutable
render/selection-bundle artifacts over ``opstore``.

Heavy modules and NumPy-backed camera exports are lazy. The experimental OCI
host boundary can therefore import its closed protocol without installing any
native CAD/numerical/render stack. Existing public camera exports are preserved.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
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


def __getattr__(name: str) -> Any:
    if name in {
        "DEFAULT_MARGIN",
        "STANDARD_VIEWS",
        "CameraFraming",
        "ViewSpec",
        "camera_framing",
        "parse_view",
        "standard_view_names",
    }:
        from hephaestus.core.render import cameras

        return getattr(cameras, name)
    raise AttributeError(name)


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
