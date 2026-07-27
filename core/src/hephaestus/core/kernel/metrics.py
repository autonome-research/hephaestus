"""Compatibility facade: this module moved to :mod:`hephaestus.geom.metrics`.

Geometry metrics (``Metrics`` record, geometry index) are now a geometry
service usable without the executor; see :mod:`hephaestus.geom`.

Compatibility only — re-exports the moved public surface unchanged so existing
``hephaestus.core.kernel.metrics`` imports keep working. New code should import from
:mod:`hephaestus.geom.metrics`.
"""

from hephaestus.geom.metrics import (
    AnyShape,
    bbox_mm,
    genus,
    geometry_index,
    is_sealed,
    labeled_nodes,
    metrics,
    shape_volume,
)

__all__ = [
    "AnyShape",
    "bbox_mm",
    "genus",
    "geometry_index",
    "is_sealed",
    "labeled_nodes",
    "metrics",
    "shape_volume",
]
