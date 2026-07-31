"""hephaestus.geom: pure geometry services over build123d/OCP shapes.

The geometry layer of the engine, usable **without** the executor. Everything
here is a function (or a small frozen record) over shapes the caller already
holds: nothing builds a script, opens a project, or talks to an agent. That is
what makes these services reusable outside the CAD pipeline — an external
benchmark scoring a submitted STEP file, a solid-diff tool, a rule pack under
test — where the executor and the store are not available and not wanted.

Contract for this package (enforced by
``core/tests/test_geom_import_boundary.py``):

- pure geometry services over build123d/OCP shapes;
- **no** executor, **no** project store, **no** ``opstore`` runtime, and
  nothing from the server or agent packages may be reachable from any module
  under ``hephaestus.geom``;
- measurement never decides. These modules report facts (volumes, clearances,
  face records, packed layouts); manufacturability verdicts belong to the DFM
  rule packs and the checks engine that consume them.

Eight services, re-exported here as one public surface:

* :mod:`hephaestus.geom.metrics` — the §8 ``Metrics`` record and the
  addressing-layer geometry index over a labeled part compound;
* :mod:`hephaestus.geom.measure` — interference, clearance, distance, mass,
  section;
* :mod:`hephaestus.geom.topology` — the face-level descriptors DFM rule packs
  are written against (planar/cylindrical faces, downward faces, opposing
  pairs);
* :mod:`hephaestus.geom.kerf` — cut-width compensation, resolved from declared
  process facts or refused;
* :mod:`hephaestus.geom.nesting` — flat-pattern extraction, shelf packing onto
  a blank, and the DXF/SVG cut-file writers;
* :mod:`hephaestus.geom.step_io` — STEP <-> shape conversion (``INGEST.md`` §1
  ingest), with no path, project or hashing policy attached;
* :mod:`hephaestus.geom.compare` — solid comparison (``COMPARE.md`` §1):
  volume/surface/topology diffs and the canonical principal pose, with the
  alignment mode always declared and never silently applied;
* :mod:`hephaestus.geom.constraints` — constraint residuals (``ASSEMBLY.md``
  §2): one evaluator per mate kind returning the measured value with the
  caller's declared numbers restated beside it. No solver — constraints
  verify, they never move geometry — and a shape of the wrong class for a
  kind is a named refusal rather than a plausible number.

Historic import paths (``hephaestus.core.kernel``, ``hephaestus.core.kerf``,
``hephaestus.core.nesting``) still resolve: they are compatibility facades that
re-export from here.
"""

from hephaestus.geom.compare import (
    AXIS_DECIMALS,
    AXIS_EPS,
    MAX_FACE_SAMPLES,
    MIN_FACE_SAMPLES,
    MOMENT_TIE_REL,
    SAMPLES_PER_MM2,
    SKEW_EPS,
    Alignment,
    AlignMode,
    CompareBooleanError,
    SolidDiff,
    SurfaceDistance,
    TopologyCensus,
    TopologyDiff,
    VolumeDiff,
    principal_alignment,
    solid_diff,
    surface_distance,
    topology_diff,
    volume_diff,
)
from hephaestus.geom.constraints import (
    ANGLE_UNIT,
    AXIS_COINCIDENT_EPS_MM,
    COINCIDENT_NORMAL_EPS_DEG,
    CONCENTRIC_AXIS_EPS_DEG,
    CONSTRAINT_KINDS,
    DIRECTION_EPS,
    INTERFERENCE_TOL_MM3,
    LENGTH_UNIT,
    OPTIONAL_PARAMS,
    PLANE_NORMAL_EPS,
    PLANE_OFFSET_EPS_MM,
    RADIUS_MATCH_EPS_MM,
    REQUIRED_PARAMS,
    SHAPE_REFUSALS,
    VOLUME_UNIT,
    ConstraintDeclarationError,
    ConstraintKind,
    ConstraintResidual,
    ConstraintShapeError,
    ResidualUnit,
    clearance_min_residual,
    coincident_residual,
    concentric_residual,
    distance_residual,
    evaluate_residual,
    fit_residual,
    no_interference_residual,
    parallel_residual,
    perpendicular_residual,
)
from hephaestus.geom.kerf import (
    KERF_UNCOMPENSATED,
    KerfDecision,
    KerfRefusal,
    KerfSource,
    kerf_compensated_shape,
    resolve_kerf,
)
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
from hephaestus.geom.step_io import (
    STEP_SCHEMAS,
    StepReadError,
    read_step,
    read_step_bytes,
    shape_from_brep,
    shape_to_brep,
    write_step,
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
    "ANGLE_UNIT",
    "AXIS_COINCIDENT_EPS_MM",
    "AXIS_DECIMALS",
    "AXIS_EPS",
    "BLANK_LAYER",
    "COINCIDENT_NORMAL_EPS_DEG",
    "CONCENTRIC_AXIS_EPS_DEG",
    "CONSTRAINT_KINDS",
    "COORD_DECIMALS",
    "CURVE_SEGMENT_MM",
    "CUT_LAYER",
    "DEFAULT_MARGIN_MM",
    "DEFAULT_SPACING_MM",
    "DIRECTION_EPS",
    "ENGRAVE_LAYER",
    "INTERFERENCE_TOL_MM3",
    "KERF_UNCOMPENSATED",
    "LAYER_COLORS",
    "LENGTH_UNIT",
    "MAX_CURVE_SEGMENTS",
    "MAX_FACE_SAMPLES",
    "MIN_CURVE_SEGMENTS",
    "MIN_FACE_SAMPLES",
    "MOMENT_TIE_REL",
    "OPTIONAL_PARAMS",
    "OVERHANG_SAMPLES",
    "OVERLAP_EPS_MM3",
    "PARALLEL_EPS",
    "PLANE_NORMAL_EPS",
    "PLANE_OFFSET_EPS_MM",
    "PROFILE_LAYER",
    "RADIUS_MATCH_EPS_MM",
    "REQUIRED_PARAMS",
    "SAMPLES_PER_MM2",
    "SCORE_LAYER",
    "SHAPE_REFUSALS",
    "SKEW_EPS",
    "STEP_SCHEMAS",
    "VOLUME_UNIT",
    "WALL_FACE_LIMIT",
    "AlignMode",
    "Alignment",
    "AnyShape",
    "Blank",
    "CompareBooleanError",
    "ConstraintDeclarationError",
    "ConstraintKind",
    "ConstraintResidual",
    "ConstraintShapeError",
    "CylinderRecord",
    "DownwardFace",
    "KerfDecision",
    "KerfRefusal",
    "KerfSource",
    "Mark",
    "NestedLayout",
    "NestingRefusal",
    "OpposingPair",
    "Placement",
    "PlanarFaceRecord",
    "Profile",
    "ResidualUnit",
    "SolidDiff",
    "StepReadError",
    "SurfaceDistance",
    "TopologyCensus",
    "TopologyDiff",
    "Vec3",
    "VolumeDiff",
    "bbox_mm",
    "blank_from_metadata",
    "blank_size_literal",
    "clearance",
    "clearance_min_residual",
    "coincident_residual",
    "concentric_residual",
    "cylindrical_faces",
    "distance",
    "distance_residual",
    "downward_faces",
    "evaluate_residual",
    "fit_residual",
    "flat_profiles",
    "genus",
    "geometry_index",
    "interference",
    "interference_pairs",
    "is_sealed",
    "kerf_compensated_shape",
    "labeled_nodes",
    "layout_layers",
    "layout_to_dxf",
    "layout_to_svg",
    "mass",
    "metrics",
    "no_interference_residual",
    "opposing_planar_pairs",
    "parallel_residual",
    "perpendicular_residual",
    "planar_faces",
    "principal_alignment",
    "read_step",
    "read_step_bytes",
    "resolve_kerf",
    "section",
    "shape_from_brep",
    "shape_to_brep",
    "shape_volume",
    "shelf_nest",
    "solid_diff",
    "solid_z_min",
    "surface_distance",
    "topology_diff",
    "volume_diff",
    "write_step",
]
