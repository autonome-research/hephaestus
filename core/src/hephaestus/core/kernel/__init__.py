"""hephaestus.core.kernel: geometry metrics and measurement services.

Pure functions over built build123d geometry (architecture §3.2), shared by
tools and checks. Re-exports the full public surface of
:mod:`hephaestus.core.kernel.metrics` and
:mod:`hephaestus.core.kernel.measure`.
"""

from hephaestus.core.kernel.measure import (
    OVERLAP_EPS_MM3,
    clearance,
    distance,
    interference,
    interference_pairs,
    mass,
    section,
)
from hephaestus.core.kernel.metrics import (
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
    "OVERLAP_EPS_MM3",
    "AnyShape",
    "bbox_mm",
    "clearance",
    "distance",
    "genus",
    "geometry_index",
    "interference",
    "interference_pairs",
    "is_sealed",
    "labeled_nodes",
    "mass",
    "metrics",
    "section",
    "shape_volume",
]
