"""Compatibility facade: this module moved to :mod:`hephaestus.geom.topology`.

The face-level topology descriptors DFM rule packs measure against are now a
geometry service usable without the executor; see :mod:`hephaestus.geom`.

Compatibility only — re-exports the moved public surface unchanged so existing
``hephaestus.core.kernel.topology`` imports keep working. New code should import from
:mod:`hephaestus.geom.topology`.
"""

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
    "PARALLEL_EPS",
    "WALL_FACE_LIMIT",
    "CylinderRecord",
    "DownwardFace",
    "OpposingPair",
    "PlanarFaceRecord",
    "Vec3",
    "cylindrical_faces",
    "downward_faces",
    "opposing_planar_pairs",
    "planar_faces",
    "solid_z_min",
]
