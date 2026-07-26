"""hephaestus.core.kernel: geometry metrics and measurement services.

Pure functions over built build123d geometry (architecture §3.2), shared by
tools and checks. Re-exports the full public surface of
:mod:`hephaestus.core.kernel.metrics`, :mod:`hephaestus.core.kernel.measure`
and :mod:`hephaestus.core.kernel.topology` (the face-level facts DFM rule packs
measure against).
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
from hephaestus.core.kernel.topology import (
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
