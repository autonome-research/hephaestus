"""Compatibility facade: the kernel geometry services now live in ``hephaestus.geom``.

The metrics, measurement and topology services moved out of the engine package
so they can be used without the executor or the project store; see
:mod:`hephaestus.geom` for the package contract. This module re-exports that
surface unchanged so existing ``hephaestus.core.kernel`` imports keep working.
Compatibility only — new code should import from :mod:`hephaestus.geom`.
"""

from hephaestus.geom.measure import (
    OVERLAP_EPS_MM3,
    clearance,
    distance,
    interference,
    interference_pairs,
    mass,
    section,
)
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
from hephaestus.geom.topology import (
    OVERHANG_SAMPLES,
    PARALLEL_EPS,
    WALL_FACE_LIMIT,
    CylinderRecord,
    DownwardFace,
    OpposingPair,
    PlanarFaceRecord,
    Vec3,
    cylindrical_faces,
    downward_faces,
    opposing_planar_pairs,
    planar_faces,
    solid_z_min,
)

__all__ = [
    "OVERHANG_SAMPLES",
    "OVERLAP_EPS_MM3",
    "PARALLEL_EPS",
    "WALL_FACE_LIMIT",
    "AnyShape",
    "CylinderRecord",
    "DownwardFace",
    "OpposingPair",
    "PlanarFaceRecord",
    "Vec3",
    "bbox_mm",
    "clearance",
    "cylindrical_faces",
    "distance",
    "downward_faces",
    "genus",
    "geometry_index",
    "interference",
    "interference_pairs",
    "is_sealed",
    "labeled_nodes",
    "mass",
    "metrics",
    "opposing_planar_pairs",
    "planar_faces",
    "section",
    "shape_volume",
    "solid_z_min",
]
