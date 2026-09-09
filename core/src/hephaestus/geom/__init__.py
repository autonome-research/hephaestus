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

Ten services, nine of them re-exported here as one public surface:

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
  kind is a named refusal rather than a plausible number;
* :mod:`hephaestus.geom.kinematics` — forward kinematics (``KINEMATICS.md``
  §2): declared joint values to rigid transforms over a forest of joint
  frames, applied to shapes as placed copies for posed measurement. No
  solver and no dynamics — posed evaluation only — and an out-of-limits
  parameter is a named refusal, never a clamp.
* :mod:`hephaestus.geom.solve` — least-squares solving over declared
  residuals (``SOLVER.md`` §§3-6): the reformulated residuals of §3.3 with the
  closed-form identities back to the engine's own numbers, fixed-order
  rank-revealing QR, and a weighted Levenberg-Marquardt iteration. It proposes
  and never decides: no verdict is spelled there, no geometry is moved, and
  the candidate it returns is believed only after
  :mod:`hephaestus.core.placement` re-measures it through
  :mod:`hephaestus.geom.constraints` in another process.

  **It is deliberately NOT re-exported below**, and it is the only service
  that is not. ``SOLVER.md`` §7.1 requires the verification pass to run in a
  process whose import closure EXCLUDES the solver — that is the whole reason
  its answer is worth anything — and that pass imports
  :mod:`hephaestus.geom`. Re-exporting ``solve`` here would pull it into the
  closure through the package ``__init__`` and quietly make the exclusion
  false while every test still passed. Import it as
  ``hephaestus.geom.solve``; the omission is the guarantee.

Historic import paths (``hephaestus.core.kernel``, ``hephaestus.core.kerf``,
``hephaestus.core.nesting``) still resolve: they are compatibility facades that
re-export from here.

**Every name below resolves on first access, not on import** (ledger
J-cli-startup-5's root cause RC-2, one layer down). Re-exporting the nine
services eagerly made *any* geom import cost all nine, and cost was not the
only price: it also closed a latent cycle into a real one. The cycle ran
:mod:`hephaestus.geom.nesting` -> :mod:`hephaestus.core.cutfile` ->
:mod:`hephaestus.core.dfm.types`, whose package ``__init__`` imports
:mod:`hephaestus.core.dfm.context`, which imports
:mod:`hephaestus.geom.topology` -> back here. ``python -c "import
hephaestus.core.cutfile"`` in a fresh interpreter raised ``cannot import name
'BLANK_LAYER' from partially initialized module``, and the only reason the
suites never saw it was that something always imported ``hephaestus.geom``
first.

Laziness removed one arc of that loop; the loop itself is now cut at its own
root, which is the arc that should never have existed: ``core.cutfile`` and
``geom.nesting`` need ``TopologyDescriptor`` for *annotations only*, so both
import it under ``TYPE_CHECKING``. ``core.cutfile`` is therefore genuinely the
leaf ``core/tests/test_geom_import_boundary.py`` already allowed it to be —
stdlib and nothing else — and ``import hephaestus.core.cutfile`` in a fresh
interpreter now reaches neither ``hephaestus.geom`` nor ``core.dfm`` at all,
in either import order. Both fixes are kept: the lazy table is about cost and
the leaf is about direction, and either one alone leaves the other's failure
mode live. The public surface is unchanged: ``__all__`` is the same list, and
``from hephaestus.geom import metrics`` (or any name in it) works exactly as
before and pays exactly once.

:mod:`hephaestus.geom.solve` stays out of the table below for the reason stated
above — an omission from ``__init__`` was the §7.1 guarantee when the imports
were eager, and it is the same guarantee now that they are lazy.
"""

import sys
from importlib import import_module
from types import ModuleType
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    # The type checker reads the real symbols from the real modules; only the
    # runtime defers. Nothing about the surface changes.
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
        cylinder_of,
        direction_of,
        distance_residual,
        evaluate_residual,
        fit_residual,
        no_interference_residual,
        parallel_residual,
        perpendicular_residual,
        plane_of,
    )
    from hephaestus.geom.kerf import (
        KERF_UNCOMPENSATED,
        KerfDecision,
        KerfRefusal,
        KerfSource,
        kerf_compensated_shape,
        resolve_kerf,
    )
    from hephaestus.geom.kinematics import (
        IDENTITY_TRANSFORM,
        JOINT_DIRECTION_EPS,
        JOINT_FRAME_EPS_DEG,
        JOINT_FRAME_EPS_MM,
        JOINT_KINDS,
        JOINT_REFUSALS,
        Coupling,
        JointDeclarationError,
        JointFrame,
        JointKind,
        JointLimitError,
        JointLimits,
        JointValue,
        RigidTransform,
        compose_transforms,
        derive_coupled_values,
        forward_kinematics,
        frame_axis_angle_deg,
        frame_radial_offset_mm,
        joint_transform,
        transform_point,
        transformed_shape,
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


#: Public name -> the geometry service module that defines it. This is the
#: whole re-export table, and ``__all__`` below is its sorted key set, so a
#: name cannot be promised here and be unreachable.
_EXPORTS: Final[dict[str, str]] = {
    "AXIS_DECIMALS": "compare",
    "AXIS_EPS": "compare",
    "AlignMode": "compare",
    "Alignment": "compare",
    "CompareBooleanError": "compare",
    "MAX_FACE_SAMPLES": "compare",
    "MIN_FACE_SAMPLES": "compare",
    "MOMENT_TIE_REL": "compare",
    "SAMPLES_PER_MM2": "compare",
    "SKEW_EPS": "compare",
    "SolidDiff": "compare",
    "SurfaceDistance": "compare",
    "TopologyCensus": "compare",
    "TopologyDiff": "compare",
    "VolumeDiff": "compare",
    "principal_alignment": "compare",
    "solid_diff": "compare",
    "surface_distance": "compare",
    "topology_diff": "compare",
    "volume_diff": "compare",
    "ANGLE_UNIT": "constraints",
    "AXIS_COINCIDENT_EPS_MM": "constraints",
    "COINCIDENT_NORMAL_EPS_DEG": "constraints",
    "CONCENTRIC_AXIS_EPS_DEG": "constraints",
    "CONSTRAINT_KINDS": "constraints",
    "ConstraintDeclarationError": "constraints",
    "ConstraintKind": "constraints",
    "ConstraintResidual": "constraints",
    "ConstraintShapeError": "constraints",
    "DIRECTION_EPS": "constraints",
    "INTERFERENCE_TOL_MM3": "constraints",
    "LENGTH_UNIT": "constraints",
    "OPTIONAL_PARAMS": "constraints",
    "PLANE_NORMAL_EPS": "constraints",
    "PLANE_OFFSET_EPS_MM": "constraints",
    "RADIUS_MATCH_EPS_MM": "constraints",
    "REQUIRED_PARAMS": "constraints",
    "ResidualUnit": "constraints",
    "SHAPE_REFUSALS": "constraints",
    "VOLUME_UNIT": "constraints",
    "clearance_min_residual": "constraints",
    "coincident_residual": "constraints",
    "concentric_residual": "constraints",
    "cylinder_of": "constraints",
    "direction_of": "constraints",
    "distance_residual": "constraints",
    "evaluate_residual": "constraints",
    "fit_residual": "constraints",
    "no_interference_residual": "constraints",
    "parallel_residual": "constraints",
    "perpendicular_residual": "constraints",
    "plane_of": "constraints",
    "KERF_UNCOMPENSATED": "kerf",
    "KerfDecision": "kerf",
    "KerfRefusal": "kerf",
    "KerfSource": "kerf",
    "kerf_compensated_shape": "kerf",
    "resolve_kerf": "kerf",
    "Coupling": "kinematics",
    "IDENTITY_TRANSFORM": "kinematics",
    "JOINT_DIRECTION_EPS": "kinematics",
    "JOINT_FRAME_EPS_DEG": "kinematics",
    "JOINT_FRAME_EPS_MM": "kinematics",
    "JOINT_KINDS": "kinematics",
    "JOINT_REFUSALS": "kinematics",
    "JointDeclarationError": "kinematics",
    "JointFrame": "kinematics",
    "JointKind": "kinematics",
    "JointLimitError": "kinematics",
    "JointLimits": "kinematics",
    "JointValue": "kinematics",
    "RigidTransform": "kinematics",
    "compose_transforms": "kinematics",
    "derive_coupled_values": "kinematics",
    "forward_kinematics": "kinematics",
    "frame_axis_angle_deg": "kinematics",
    "frame_radial_offset_mm": "kinematics",
    "joint_transform": "kinematics",
    "transform_point": "kinematics",
    "transformed_shape": "kinematics",
    "OVERLAP_EPS_MM3": "measure",
    "clearance": "measure",
    "distance": "measure",
    "interference": "measure",
    "interference_pairs": "measure",
    "mass": "measure",
    "section": "measure",
    "AnyShape": "metrics",
    "bbox_mm": "metrics",
    "genus": "metrics",
    "geometry_index": "metrics",
    "is_sealed": "metrics",
    "labeled_nodes": "metrics",
    "metrics": "metrics",
    "shape_volume": "metrics",
    "BLANK_LAYER": "nesting",
    "Blank": "nesting",
    "COORD_DECIMALS": "nesting",
    "CURVE_SEGMENT_MM": "nesting",
    "CUT_LAYER": "nesting",
    "DEFAULT_MARGIN_MM": "nesting",
    "DEFAULT_SPACING_MM": "nesting",
    "ENGRAVE_LAYER": "nesting",
    "LAYER_COLORS": "nesting",
    "MAX_CURVE_SEGMENTS": "nesting",
    "MIN_CURVE_SEGMENTS": "nesting",
    "Mark": "nesting",
    "NestedLayout": "nesting",
    "NestingRefusal": "nesting",
    "PROFILE_LAYER": "nesting",
    "Placement": "nesting",
    "Profile": "nesting",
    "SCORE_LAYER": "nesting",
    "blank_from_metadata": "nesting",
    "blank_size_literal": "nesting",
    "flat_profiles": "nesting",
    "layout_layers": "nesting",
    "layout_to_dxf": "nesting",
    "layout_to_svg": "nesting",
    "shelf_nest": "nesting",
    "STEP_SCHEMAS": "step_io",
    "StepReadError": "step_io",
    "read_step": "step_io",
    "read_step_bytes": "step_io",
    "shape_from_brep": "step_io",
    "shape_to_brep": "step_io",
    "write_step": "step_io",
    "CylinderRecord": "topology",
    "DownwardFace": "topology",
    "OVERHANG_SAMPLES": "topology",
    "OpposingPair": "topology",
    "PARALLEL_EPS": "topology",
    "PlanarFaceRecord": "topology",
    "Vec3": "topology",
    "WALL_FACE_LIMIT": "topology",
    "cylindrical_faces": "topology",
    "downward_faces": "topology",
    "opposing_planar_pairs": "topology",
    "planar_faces": "topology",
    "solid_z_min": "topology",
}

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
    "IDENTITY_TRANSFORM",
    "INTERFERENCE_TOL_MM3",
    "JOINT_DIRECTION_EPS",
    "JOINT_FRAME_EPS_DEG",
    "JOINT_FRAME_EPS_MM",
    "JOINT_KINDS",
    "JOINT_REFUSALS",
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
    "Coupling",
    "CylinderRecord",
    "DownwardFace",
    "JointDeclarationError",
    "JointFrame",
    "JointKind",
    "JointLimitError",
    "JointLimits",
    "JointValue",
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
    "RigidTransform",
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
    "compose_transforms",
    "concentric_residual",
    "cylinder_of",
    "cylindrical_faces",
    "derive_coupled_values",
    "direction_of",
    "distance",
    "distance_residual",
    "downward_faces",
    "evaluate_residual",
    "fit_residual",
    "flat_profiles",
    "forward_kinematics",
    "frame_axis_angle_deg",
    "frame_radial_offset_mm",
    "genus",
    "geometry_index",
    "interference",
    "interference_pairs",
    "is_sealed",
    "joint_transform",
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
    "plane_of",
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
    "transform_point",
    "transformed_shape",
    "volume_diff",
    "write_step",
]


#: The service modules the eager ``__init__`` also left bound as *attributes* of
#: this package, as a side effect of importing them. Attribute access
#: (``hephaestus.geom.nesting.shelf_nest``) worked before this file went lazy
#: and still has to, so the resolution below covers submodules too — the table
#: above wins where a name is both, which is how ``geom.metrics`` resolved to
#: the ``metrics`` *function* when the imports were eager and still does.
#: ``solve`` and ``mesh`` are absent deliberately: neither was ever bound here
#: (see ``solve``'s ``SOLVER.md`` §7.1 note above), and both are imported by
#: their full module path.
_SERVICE_MODULES: Final[frozenset[str]] = frozenset(set(_EXPORTS.values()))


#: The names that are BOTH a re-exported symbol and a service module —
#: ``metrics`` (the §8 record builder) is the only one today. Importing a
#: submodule binds it onto this package under its short name as a side effect
#: of the import system, so any import that reaches ``hephaestus.geom.metrics``
#: — ``geom.measure`` does, on its own first line — would shadow the symbol
#: with the module, and which one a caller got would depend on the order names
#: happened to be touched: ``from hephaestus.geom import clearance, metrics``
#: bound ``metrics`` to the MODULE and ``TypeError: 'module' object is not
#: callable`` was the next line. The eager version had no such order dependency
#: (its ``from .metrics import metrics`` ran after every submodule binding), so
#: neither may this one.
_SHADOWED: Final[frozenset[str]] = frozenset(
    name for name, module in _EXPORTS.items() if name == module
)


class _GeomPackage(ModuleType):
    """This package's own module type, resolving :data:`_SHADOWED` for good.

    A ``__getattr__`` cannot fix the collision, because it is consulted only
    when normal lookup FAILS — and after the import system has bound the
    submodule, normal lookup succeeds and returns the wrong object. Overriding
    ``__getattribute__`` puts the table back in charge of exactly those names,
    whatever import ran first, which is the property the eager version had for
    free and the property callers actually depend on.
    """

    def __getattribute__(self, name: str) -> object:
        if name in _SHADOWED:
            return getattr(import_module(f".{_EXPORTS[name]}", __name__), name)
        return super().__getattribute__(name)


sys.modules[__name__].__class__ = _GeomPackage


def __getattr__(name: str) -> object:
    """Resolve one re-exported name by importing the service that defines it."""
    module = _EXPORTS.get(name)
    if module is None:
        if name not in _SERVICE_MODULES:
            raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
        # A submodule asked for by attribute, not a re-exported name.
        value: object = import_module(f".{name}", __name__)
    else:
        service = import_module(f".{module}", __name__)
        value = getattr(service, name)
    globals()[name] = value  # bind it, so the next access is a plain lookup
    return value


def __dir__() -> list[str]:
    return sorted({*_EXPORTS, *_SERVICE_MODULES})
