# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Least-squares solving over declared residuals: candidates, never verdicts.

``SOLVER.md`` §§3-6, the **tenth** pure geom service. Like its nine siblings
this module is pure functions over frames and numbers the caller already
holds: no executor, no store, no project, and — the part that matters most
here — **no verdicts**. It answers one question, *what assignment of the
declared free variables makes the declared residual vector small?*, and hands
back the iterate together with everything a reader needs to distrust it: the
rank, the null space, which bounds went active, how the iteration terminated.
Deciding whether that iterate is a solution is
:mod:`hephaestus.core.placement`'s job, and it decides it by re-measuring
through :mod:`hephaestus.geom.constraints` in another process (``SOLVER.md``
§7), never by reading anything below.

**NO SOLVER MOVES GEOMETRY** (``ASSEMBLY.md`` §1 as scoped on 2026-08-30,
``SOLVER.md`` §1). Nothing here writes a script, a parameter or an artifact.
The module contracts of :mod:`hephaestus.geom.constraints` and
:mod:`hephaestus.geom.kinematics` are unamended and this module restates them:
a transform computed here exists only in the caller's hands, exactly as a
posed transform already does.

The reformulation, and why the engine's numbers are not iterated on
------------------------------------------------------------------
``SOLVER.md`` §3.3 is the sharp edge. All four analytic 8C kinds compute
``measured`` in a form that is non-smooth or singular **at their own
solutions** — ``coincident``'s ``abs`` gap kinks at the mate, ``concentric``'s
norm-to-a-line is non-differentiable at offset 0, ``parallel``'s ``acos`` has
unbounded derivative at parallel, ``perpendicular`` kinks twice at square.
Iterating on those is iterating on a function whose gradient does not exist
where the answer is. So this module iterates on a **reformulation** per
component — signed gap, offset vector, normal sum, cross product, dot product
— each zero exactly where ``measured`` is zero, smooth around that zero, and
each carrying a closed-form :data:`IDENTITIES` map back into the engine's
measurement domain. :func:`recover_measurement` is that map. It is not a
convenience: it is what lets the verification pass compare the solver's model
against the kernel's number per component, so a reformulation bug is caught
rather than absorbed.

What is NOT here
----------------
No global optimisation, no random restarts, no RNG, no BLAS (``SOLVER.md``
§4.2 and §9 — a threaded, dispatch-dependent backend would forfeit the one
determinism tier worth having). The linear algebra is fixed-order plain-float
Householder QR with column pivoting, written out below, so a ``solver_core``
block is byte-identical across processes given identical extracted frames.

Multiplicity is never resolved silently
---------------------------------------
:func:`solve_least_squares` returns ONE iterate from ONE start and says so.
Rank deficiency comes back as :attr:`SolveIterate.dof_remaining` plus a named
null-space basis, never as a converged answer; a rank the pivots cannot decide
is the refusal :class:`SolveRefused` (``rank_undecidable``), because a guessed
rank silently decides whether the answer is unique. Comparing several starts
and naming discrete multiplicity is :func:`distinct_solutions`, and it too
returns every member rather than choosing one.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal, Protocol

from hephaestus.geom.topology import CylinderRecord, PlanarFaceRecord, Vec3

__all__ = [
    "DETERMINISM_FLOOR",
    "IDENTITIES",
    "JACOBIAN_FD_STEP",
    "PARAM_FD_STEP",
    "RANK_MARGIN_REL",
    "RANK_TOL_REL",
    "SENSITIVITY_EPS",
    "SO3_EPS",
    "SO3_REPROJECT_EPS",
    "SOLUTION_DISTINCT_EPS",
    "SOLVE_VERSION",
    "STATIONARITY_EPS",
    "ComponentSpec",
    "ComponentValue",
    "Identity",
    "NullDirection",
    "ResidualModel",
    "SolveIterate",
    "SolveRefused",
    "SolveVariable",
    "Termination",
    "TraceStep",
    "WeightPolicy",
    "central_difference_jacobian",
    "component_scale",
    "component_values",
    "d_coincident_gap",
    "d_coincident_normals",
    "d_concentric_offset",
    "d_cross",
    "d_perpendicular",
    "decompose_rigid",
    "distinct_solutions",
    "insensitive_sources",
    "is_rotation",
    "null_space",
    "orthonormal_complement",
    "perpendicular_component",
    "rank_revealing_qr",
    "recover_measurement",
    "reproject_rotation",
    "residual_coincident_gap",
    "residual_coincident_normals",
    "residual_concentric_offset",
    "residual_cross",
    "residual_perpendicular",
    "residual_point_target",
    "residual_signed_offset",
    "residual_window",
    "rigid_rows",
    "rotation_derivatives",
    "rotation_from_vector",
    "solve_least_squares",
    "transform_cylinder",
    "transform_plane",
    "weighted_distance",
]

# --------------------------------------------------------------------------
# named constants

#: Relative pivot threshold below which a column of the weighted Jacobian is
#: discarded from the rank. Relative to the largest pivot, so the number is
#: about conditioning rather than about units.
#:
#: Deliberately far above double-precision epsilon, and the reason is a
#: measurement fact rather than a numerical taste. The Jacobian's entries are
#: built from frames the KERNEL extracted, and two axes a script authored
#: coaxial come back agreeing only to about
#: :data:`~hephaestus.geom.kinematics.JOINT_FRAME_EPS_DEG` - a joint forest is
#: *accepted* at 1e-3 deg of frame divergence. A threshold at 1e-16 would
#: therefore call a structurally dependent direction independent whenever the
#: kernel's round-off tilted it, and report a redundant arm as uniquely
#: determined: full rank claimed from noise. 1e-6 sits above the noise and far
#: below any direction a design actually has.
RANK_TOL_REL: Final[float] = 1e-6

#: How far the smallest retained and largest discarded pivots must sit from
#: :data:`RANK_TOL_REL` before the rank counts as decided. Pivots that straddle
#: the threshold more tightly than this factor make the rank a coin flip, and a
#: guessed rank silently decides whether the answer is unique — which is the
#: one thing ``SOLVER.md`` §6 exists to prevent, so the solve is refused
#: ``rank_undecidable`` instead (``SOLVER.md`` §4.2 step 3).
RANK_MARGIN_REL: Final[float] = 10.0

#: ``‖Jᵀ W r‖∞``, relative to ``max(1, ‖W r‖∞)``, at or below which an iterate
#: counts as stationary. Stationary with a residual still above tolerance is
#: what separates "the declared constraints disagree with each other"
#: (over-constrained, verdict 5) from "this start did not get there"
#: (verdict 4) — two different facts that must not share a spelling.
STATIONARITY_EPS: Final[float] = 1e-8

#: Weighted distance beyond which two converged iterates are *different*
#: solutions rather than the same one reached twice (``SOLVER.md`` §5). Above
#: it the outcome is multiplicity and every member is returned; the solver
#: never picks.
SOLUTION_DISTINCT_EPS: Final[float] = 1e-6

#: How far a rotation block may sit from orthonormal before it is re-projected.
SO3_EPS: Final[float] = 1e-12

#: How far a rotation block may sit from orthonormal and still be re-projected
#: at all. Beyond it the iterate is not a rigid placement and is refused
#: ``non_rigid_iterate`` by the engine (``SOLVER.md`` §4.2 step 5).
SO3_REPROJECT_EPS: Final[float] = 1e-6

#: The determinism floor (``ASSEMBLY.md:152-153``): what two processes in the
#: pinned image are gated to agree to. A declared tolerance tighter than this
#: is refused, because no termination rule here can deliver it. It is a
#: *determinism* floor and deliberately not called a measurement floor —
#: nothing in this repo has measured the kernel's accuracy against ground
#: truth, and naming it that would claim a number nobody computed
#: (``SOLVER.md`` §6.3).
DETERMINISM_FLOOR: Final[float] = 1e-9

#: Relative step of the central finite difference used where a model supplies
#: no analytic Jacobian. Central rather than forward: the reformulated
#: residuals of §3.3 are smooth at their solutions, and a one-sided difference
#: would throw that away for no saving worth having.
JACOBIAN_FD_STEP: Final[float] = 1e-6

#: The relative step ``SOLVER.md`` §2C's parameter space differences at, and it
#: is two orders LOOSER than :data:`JACOBIAN_FD_STEP` for a measured reason.
#: A 2B difference is taken of plain-float arithmetic over frames already in
#: hand, so 1e-6 costs nothing. A 2C difference is taken of **two preview
#: builds**: the geometry is re-tessellated, re-published and re-measured by
#: the kernel, and the residual difference a 1e-6 step produces is only a few
#: orders above what the kernel's own round-off contributes to it. Differencing
#: there would report noise as a gradient — and a gradient made of noise is how
#: a solver walks confidently in a direction nothing supports. 1e-4 keeps the
#: difference well clear of that floor while staying small enough that the
#: truncation error of a central difference is negligible against the declared
#: tolerances a solve terminates on.
PARAM_FD_STEP: Final[float] = 1e-4

#: Below this, a finite-difference column block counts as **all zero**: the
#: free variables move this constraint's own measurement by nothing. Paired
#: with "and the constraint is not already satisfied", that is
#: ``no_free_variable_affects`` (``SOLVER.md`` §2C) — "a mate nobody made a
#: knob for is unreachable, and that unreachability is reported by name".
#:
#: The second half of the pair is not a softening and it is why the number
#: alone is not the test. A constraint that is *already satisfied* and moves
#: for nothing is not unreachable — it is reached, and the honest report of it
#: is the satisfied row a converged solve already carries. Refusing the whole
#: solve for it would be naming a failure over a constraint that holds.
SENSITIVITY_EPS: Final[float] = 1e-9

#: The version stamp a proposal binds beside the toolchain hash
#: (``SOLVER.md`` §8). It names the ARITHMETIC, not the release: a change to
#: the residual reformulation, an identity, a Jacobian or the iteration would
#: make two proposals with the same request incomparable, and a reader has to
#: be able to see that from the document rather than infer it from a date.
SOLVE_VERSION: Final[str] = "geom.solve/1"

_DEG_PER_RAD: Final[float] = 180.0 / math.pi


# --------------------------------------------------------------------------
# the §3.3 identities: reformulated residual -> the engine's own number

Identity = Literal["abs", "norm", "asin_norm", "asin_norm_half2", "asin_abs"]

#: Every identity this module knows, closed. ``SOLVER.md`` §3.3 tabulates one
#: per objective component and each is a gate clause: if a reformulation and
#: the engine's measurement ever disagree, the solver is optimising something
#: other than the constraint, and no amount of convergence would make its
#: answer evidence.
#:
#: * ``abs`` — the signed ``coincident`` plane gap; ``|r| == measured`` (mm).
#: * ``norm`` — the ``concentric`` radial-offset vector, and an anchor-to-point
#:   error; ``‖r‖ == measured`` (mm).
#: * ``asin_norm`` — ``cross(a, b)`` for ``concentric``'s axes and for
#:   ``parallel``; ``degrees(asin(clamp(‖r‖))) == measured`` (deg).
#: * ``asin_norm_half2`` — the ``coincident`` normal sum ``n_a + n_b``;
#:   ``2·degrees(asin(clamp(‖r‖/2))) == normal_deviation_deg`` (deg).
#: * ``asin_abs`` — ``dot(d_a, d_b)`` for ``perpendicular``;
#:   ``degrees(asin(clamp(|r|))) == measured`` (deg).
IDENTITIES: Final[tuple[Identity, ...]] = (
    "abs",
    "norm",
    "asin_norm",
    "asin_norm_half2",
    "asin_abs",
)


def _clamp(value: float) -> float:
    """``max(-1, min(1, value))`` — the guard ``_angle_deg`` already applies."""
    return max(-1.0, min(1.0, value))


def recover_measurement(identity: Identity, raw: Sequence[float]) -> float:
    """The engine's own measured number, recovered from a reformulated residual.

    The closed-form half of ``SOLVER.md`` §3.3. ``raw`` is the reformulation's
    vector (dimension 1, 2 or 3 depending on the component); the return is the
    quantity :class:`~hephaestus.geom.constraints.ConstraintResidual` would
    report for that component, in mm or deg. Every caller of this function is
    asserting the identity rather than trusting it: the verification pass
    (``SOLVER.md`` §7.6) compares the number this returns against the kernel's
    per component and refuses ``solver_residual_disagreement`` on a mismatch.
    """
    if identity == "abs":
        return abs(raw[0])
    if identity == "asin_abs":
        return math.degrees(math.asin(_clamp(abs(raw[0]))))
    length = math.sqrt(sum(component * component for component in raw))
    if identity == "norm":
        return length
    if identity == "asin_norm":
        return math.degrees(math.asin(_clamp(length)))
    # asin_norm_half2: ‖n_a + n_b‖ == 2·sin(deviation/2)
    return 2.0 * math.degrees(math.asin(_clamp(length / 2.0)))


def component_scale(identity: Identity) -> float:
    """The factor carrying a reformulated component into its measurement domain.

    ``SOLVER.md`` §3.3, second consequence: the reformulated components are
    dimensionless where the engine's are degrees, so they are scaled by the
    identity's leading factor **before** ``SOLVER.md`` §3.4's weights apply,
    and a weight declared in ``deg`` means what it says.

    The leading factor is the derivative of :func:`recover_measurement` at
    zero. For ``asin_norm_half2`` that is ``2 · (180/π) · (1/2) == 180/π`` —
    **not** the ``2·180/π`` ``SOLVER.md`` §3.3 writes in its parenthetical,
    which double-counts the outer 2 against the ``/2`` inside the ``asin``.
    Using the spec's number would make a ``coincident`` normal residual read
    twice its own degrees, which is precisely the silent normalization
    ``COMPARE.md:34-36`` forbids, so the arithmetic wins and the deviation is
    recorded here rather than propagated.
    """
    if identity in ("abs", "norm"):
        return 1.0
    return _DEG_PER_RAD


# --------------------------------------------------------------------------
# small vector helpers (world mm, right-handed, +Z up)


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _scale(a: Vec3, k: float) -> Vec3:
    return (a[0] * k, a[1] * k, a[2] * k)


def _norm(a: Vec3) -> float:
    return math.sqrt(_dot(a, a))


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _unit_or_zero(a: Vec3) -> Vec3:
    length = _norm(a)
    if length <= 0.0:
        return (0.0, 0.0, 0.0)
    return _scale(a, 1.0 / length)


# --------------------------------------------------------------------------
# transporting extracted frames under a candidate transform


def _apply(rows: Sequence[Sequence[float]], point: Vec3) -> Vec3:
    return (
        rows[0][0] * point[0] + rows[0][1] * point[1] + rows[0][2] * point[2] + rows[0][3],
        rows[1][0] * point[0] + rows[1][1] * point[1] + rows[1][2] * point[2] + rows[1][3],
        rows[2][0] * point[0] + rows[2][1] * point[1] + rows[2][2] * point[2] + rows[2][3],
    )


def _rotate(rows: Sequence[Sequence[float]], direction: Vec3) -> Vec3:
    return (
        rows[0][0] * direction[0] + rows[0][1] * direction[1] + rows[0][2] * direction[2],
        rows[1][0] * direction[0] + rows[1][1] * direction[1] + rows[1][2] * direction[2],
        rows[2][0] * direction[0] + rows[2][1] * direction[1] + rows[2][2] * direction[2],
    )


def transform_plane(record: PlanarFaceRecord, rows: Sequence[Sequence[float]]) -> PlanarFaceRecord:
    """``record`` carried under a rigid transform, in closed form.

    ``SOLVER.md`` §4.2 step 1: frames resolve once and are transported
    analytically, so **no kernel call occurs inside an iteration**. The centre
    rides the full affine map and the normal rides the rotation block only;
    area and index are properties of the face, not of where it sits, and are
    carried through unchanged.
    """
    return PlanarFaceRecord(
        index=record.index,
        area=record.area,
        center=_apply(rows, record.center),
        normal=_unit_or_zero(_rotate(rows, record.normal)),
    )


def transform_cylinder(record: CylinderRecord, rows: Sequence[Sequence[float]]) -> CylinderRecord:
    """``record`` carried under a rigid transform (the :func:`transform_plane` rule)."""
    return CylinderRecord(
        index=record.index,
        area=record.area,
        radius=record.radius,
        axis_point=_apply(rows, record.axis_point),
        axis=_unit_or_zero(_rotate(rows, record.axis)),
        sweep_rad=record.sweep_rad,
        internal=record.internal,
        full=record.full,
    )


# --------------------------------------------------------------------------
# SO(3) validity (``SOLVER.md`` §4.2 step 5)


def is_rotation(rows: Sequence[Sequence[float]]) -> float:
    """How far ``rows``' rotation block sits from orthonormal, as one number.

    ``max |RᵀR - I|`` over the nine entries. Nothing in the codebase checks
    this today — :class:`~hephaestus.geom.kinematics.RigidTransform` is a raw
    3x4 dataclass — and a drifted iterate would produce a "transform" that is
    not a placement, which is why the engine turns a deviation beyond
    :data:`SO3_REPROJECT_EPS` into the named refusal ``non_rigid_iterate``
    rather than quietly placing geometry with it. The deviation is the fact
    returned here; thresholding it is deliberately the caller's decision, the
    same "measurement never decides" split every other geom service keeps.
    """
    worst = 0.0
    for i in range(3):
        for j in range(3):
            entry = sum(rows[k][i] * rows[k][j] for k in range(3))
            target = 1.0 if i == j else 0.0
            worst = max(worst, abs(entry - target))
    return worst


def reproject_rotation(rows: Sequence[Sequence[float]]) -> tuple[tuple[float, ...], ...]:
    """``rows`` with its rotation block re-orthonormalised (Gram-Schmidt).

    Fixed order — first column, then second against the first, then the cross
    product — so two processes re-project identically. The translation column
    is untouched: a drifted rotation says nothing about where the part sits.
    """
    c0 = _unit_or_zero((rows[0][0], rows[1][0], rows[2][0]))
    raw1: Vec3 = (rows[0][1], rows[1][1], rows[2][1])
    c1 = _unit_or_zero(_sub(raw1, _scale(c0, _dot(c0, raw1))))
    c2 = _cross(c0, c1)
    return tuple((c0[i], c1[i], c2[i], rows[i][3]) for i in range(3))


# --------------------------------------------------------------------------
# SE(3) as six numbers: the exponential map, its derivative, and its inverse
#
# ``SOLVER.md`` NEW WORK 1 and §2B. Transform space's free variable per part is
# a rigid transform, and a solver needs it as a VECTOR - six scalars it can
# step, bound and difference. The parametrisation is
# ``(tx, ty, tz, rx, ry, rz)``: a translation in mm, and a rotation vector in
# DEGREES whose direction is the axis and whose magnitude is the angle, applied
# about a declared pivot the caller supplies.
#
# Why degrees rather than radians: every declared bound, every reported number
# and every weight in this stage is in the measurement domain a reviewer reads
# (``SOLVER.md`` §3.4), and a variable secretly in radians would make a
# ``declared`` weight of 1.0 per deg mean 57.3 of them. The conversion lives
# here, once, rather than at each of the four call sites that would otherwise
# have to remember it.
#
# Why a pivot: rotating about the world origin couples a part's orientation to
# how far it happens to sit from (0,0,0), so a bracket 500 mm out would need a
# 0.001 deg step where one at the origin needs 0.1. The pivot is the part's own
# bounding-box centre, recorded in the solve record beside the frames, and it
# changes only the PARAMETRISATION - the returned transform is the same 3x4
# either way, which is why a gate may hand-compute one without knowing it.


def rotation_from_vector(rotation_deg: Vec3) -> tuple[Vec3, Vec3, Vec3]:
    """Rodrigues: the rotation matrix (three rows) of a degree-valued rotation vector.

    Zero vector gives the identity exactly, with no division: the small-angle
    branch is taken on an exact comparison rather than a tolerance, because the
    series and the closed form agree to well past double precision everywhere
    else and a tolerance here would be a second, undocumented epsilon.
    """
    theta = math.sqrt(sum(value * value for value in rotation_deg)) * math.pi / 180.0
    if theta == 0.0:
        return ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    axis = _scale(rotation_deg, 1.0 / (theta * 180.0 / math.pi))
    c = math.cos(theta)
    s = math.sin(theta)
    t = 1.0 - c
    x, y, z = axis
    return (
        (t * x * x + c, t * x * y - s * z, t * x * z + s * y),
        (t * x * y + s * z, t * y * y + c, t * y * z - s * x),
        (t * x * z - s * y, t * y * z + s * x, t * z * z + c),
    )


def rotation_derivatives(
    rotation_deg: Vec3,
) -> tuple[tuple[Vec3, Vec3, Vec3], tuple[Vec3, Vec3, Vec3], tuple[Vec3, Vec3, Vec3]]:
    """``dR/dr_i`` for each of the three rotation-vector components, PER DEGREE.

    The exact derivative of the exponential map in exponential coordinates
    (Gallego & Yezzi 2014)::

        dR/dv_i = ( v_i [v]x + [ v x (I - R) e_i ]x ) / ||v||^2  ·  R

    with the ``v -> 0`` limit ``dR/dv_i = [e_i]x``, in radians, then scaled by
    ``pi/180`` because the variable is degrees.

    Analytic rather than differenced, and the reason is ``SOLVER.md`` §3.3's:
    the Jacobian must be a Jacobian **of the reformulation**, exact where the
    reformulation is smooth, so a gate can hold it against a central difference
    *within one declared tolerance of the solution* — the neighbourhood where a
    sloppy derivative is exactly as convincing as a right one and exactly as
    wrong.
    """
    scale = math.pi / 180.0
    v: Vec3 = (rotation_deg[0] * scale, rotation_deg[1] * scale, rotation_deg[2] * scale)
    norm2 = _dot(v, v)
    rows = rotation_from_vector(rotation_deg)
    out: list[tuple[Vec3, Vec3, Vec3]] = []
    for index in range(3):
        if norm2 == 0.0:
            basis: Vec3 = (
                1.0 if index == 0 else 0.0,
                1.0 if index == 1 else 0.0,
                1.0 if index == 2 else 0.0,
            )
            generator = _skew(basis)
        else:
            # ``(I - R) e_i`` is the i-th column of ``I - R``.
            column: Vec3 = (
                (1.0 if index == 0 else 0.0) - rows[0][index],
                (1.0 if index == 1 else 0.0) - rows[1][index],
                (1.0 if index == 2 else 0.0) - rows[2][index],
            )
            left = _skew(_scale(v, v[index]))
            right = _skew(_cross(v, column))
            factor = _matrix3(
                [[(left[i][j] + right[i][j]) / norm2 for j in range(3)] for i in range(3)]
            )
            generator = _matrix3(
                [
                    [sum(factor[i][k] * rows[k][j] for k in range(3)) for j in range(3)]
                    for i in range(3)
                ]
            )
        out.append(_matrix3([[value * scale for value in row] for row in generator]))
    return (out[0], out[1], out[2])


def _matrix3(values: Sequence[Sequence[float]]) -> tuple[Vec3, Vec3, Vec3]:
    """Three rows of three floats as the fixed-shape tuple the callers pass around."""
    return (
        (values[0][0], values[0][1], values[0][2]),
        (values[1][0], values[1][1], values[1][2]),
        (values[2][0], values[2][1], values[2][2]),
    )


def _skew(vector: Vec3) -> tuple[Vec3, Vec3, Vec3]:
    """``[v]x``, the matrix with ``[v]x u == cross(v, u)``."""
    x, y, z = vector
    return ((0.0, -z, y), (z, 0.0, -x), (-y, x, 0.0))


def rigid_rows(
    translation_mm: Vec3, rotation_deg: Vec3, pivot: Vec3
) -> tuple[tuple[float, float, float, float], ...]:
    """The 3x4 rows of ``p -> R (p - pivot) + pivot + t``.

    The returned rows are an ordinary
    :class:`~hephaestus.geom.kinematics.RigidTransform` payload: the pivot has
    been folded into the translation column, so nothing downstream needs to
    know it was ever parametrised that way.
    """
    r = rotation_from_vector(rotation_deg)
    offset = _add(_sub(pivot, _rotate3(r, pivot)), translation_mm)
    return tuple((r[i][0], r[i][1], r[i][2], offset[i]) for i in range(3))


def _rotate3(rows: tuple[Vec3, Vec3, Vec3], direction: Vec3) -> Vec3:
    return (
        _dot(rows[0], direction),
        _dot(rows[1], direction),
        _dot(rows[2], direction),
    )


def decompose_rigid(rows: Sequence[Sequence[float]]) -> tuple[Vec3, Vec3, float]:
    """``(translation_mm, axis, angle_deg)`` — the log map, for REPORTING.

    ``SOLVER.md`` NEW WORK 1 and §8: a proposal "names the part and the
    transform, decomposed into translation (mm) plus axis-angle (axis,
    degrees) for human legibility". :mod:`hephaestus.geom.kinematics` is
    forward-only and has no inverse, so this is it.

    The translation is the transform's own translation column, not a
    pivot-relative one: what a reader wants to know is where the origin went.
    The angle is folded into ``[0, 180]`` and the axis is a unit vector, or
    ``(0, 0, 1)`` with a zero angle when the rotation block is the identity —
    an arbitrary axis for a zero rotation is not a fact, and picking one
    silently would dress a non-fact as a measurement.
    """
    trace = rows[0][0] + rows[1][1] + rows[2][2]
    angle = math.acos(_clamp((trace - 1.0) / 2.0))
    translation: Vec3 = (rows[0][3], rows[1][3], rows[2][3])
    if angle == 0.0:
        return translation, (0.0, 0.0, 1.0), 0.0
    sin_angle = math.sin(angle)
    if abs(sin_angle) > 1e-9:
        axis = _scale(
            (
                rows[2][1] - rows[1][2],
                rows[0][2] - rows[2][0],
                rows[1][0] - rows[0][1],
            ),
            1.0 / (2.0 * sin_angle),
        )
        return translation, _unit_or_zero(axis), math.degrees(angle)
    # angle == pi: the antisymmetric part vanishes, so the axis comes out of
    # R + I, whose columns are all parallel to it. The largest one is taken so
    # the normalisation never divides by a rounding artefact.
    candidates = [
        (rows[0][0] + 1.0, rows[1][0], rows[2][0]),
        (rows[0][1], rows[1][1] + 1.0, rows[2][1]),
        (rows[0][2], rows[1][2], rows[2][2] + 1.0),
    ]
    best = max(candidates, key=lambda column: _dot(column, column))
    return translation, _unit_or_zero(best), math.degrees(angle)


# --------------------------------------------------------------------------
# the reformulated residuals (``SOLVER.md`` §3.3), and their derivatives
#
# Stated over PRIMITIVES - a point and a direction per side - rather than over
# :class:`~hephaestus.geom.topology.PlanarFaceRecord` /
# :class:`~hephaestus.geom.topology.CylinderRecord`, because the four analytic
# kinds differ only in which primitive plays which role and a per-record
# signature would make the same arithmetic appear four times. The records are
# carried under a candidate transform by :func:`transform_plane` /
# :func:`transform_cylinder`; what the iteration consumes is the primitives.
#
# Each residual is paired with its analytic derivative, taking the geometric
# velocities of the same primitives. That pairing is what ``SOLVER.md`` §4.2
# step 2 asks for and what makes the Jacobian a Jacobian OF THE REFORMULATION
# (NW4) rather than of the engine's non-smooth ``measured``.


def residual_coincident_gap(center_a: Vec3, normal_a: Vec3, center_b: Vec3) -> tuple[float]:
    """Signed plane gap ``dot(c_b - c_a, n_a)`` - **no** ``abs``.

    The engine's ``coincident`` gap is ``abs`` of exactly this
    (``geom/constraints.py:657``), whose kink is at the mate. Dropping the
    ``abs`` moves the kink out of the answer and keeps the identity trivial:
    ``|r| == measured``.
    """
    return (_dot(_sub(center_b, center_a), normal_a),)


def d_coincident_gap(
    center_a: Vec3,
    normal_a: Vec3,
    center_b: Vec3,
    d_center_a: Vec3,
    d_normal_a: Vec3,
    d_center_b: Vec3,
) -> tuple[float]:
    """``d/dt`` of :func:`residual_coincident_gap` - the product rule, written out."""
    return (
        _dot(_sub(d_center_b, d_center_a), normal_a) + _dot(_sub(center_b, center_a), d_normal_a),
    )


def residual_coincident_normals(normal_a: Vec3, normal_b: Vec3) -> Vec3:
    """``n_a + n_b`` - zero exactly when the normals are opposed.

    The class predicate as an objective term, which is what gives a solver the
    gradient that flips a same-facing part. Keeping it out of the objective and
    catching it at verification instead would refuse a whole fixture class
    unconditionally (``SOLVER.md`` §3.1, "the alternative that lost").
    """
    return _add(normal_a, normal_b)


def d_coincident_normals(d_normal_a: Vec3, d_normal_b: Vec3) -> Vec3:
    """``d/dt`` of :func:`residual_coincident_normals`."""
    return _add(d_normal_a, d_normal_b)


def perpendicular_component(direction: Vec3, reference: Vec3) -> Vec3:
    """``reference`` with its ``direction`` component removed, unit length."""
    rejected = _sub(reference, _scale(direction, _dot(direction, reference)))
    return _unit_or_zero(rejected)


def orthonormal_complement(direction: Vec3, reference: Vec3) -> tuple[Vec3, Vec3]:
    """``(u, v)``: an orthonormal basis of the plane perpendicular to ``direction``.

    Computed ONCE, at frame extraction, in the as-built frame - and then
    carried under the candidate transform with the axis it complements, so
    ``u`` and ``v`` stay exactly perpendicular to the axis for free and their
    derivatives are the same rigid velocity the axis has. Recomputing the
    complement at every iterate from a fixed world reference would work too,
    but it would put a Gram-Schmidt division into the Jacobian for no gain,
    and a "smallest component" rule would put a discontinuity there.
    """
    u = perpendicular_component(direction, reference)
    return u, _cross(direction, u)


def residual_concentric_offset(
    point_a: Vec3, u_a: Vec3, v_a: Vec3, point_b: Vec3
) -> tuple[float, float]:
    """The radial offset as a 2-vector in ``a``'s perpendicular frame.

    ``SOLVER.md`` §3.3: the engine's number is a Euclidean norm to a line
    (``geom/constraints.py:378-386``), non-differentiable at offset ``0`` - the
    mate. The vector form is smooth there and ``‖r‖ == measured`` exactly,
    because ``u`` and ``v`` are perpendicular to ``a``'s axis, so the two
    components of ``p_b - p_a`` along them ARE the components of the rejection
    the engine measures the length of.
    """
    delta = _sub(point_b, point_a)
    return (_dot(delta, u_a), _dot(delta, v_a))


def d_concentric_offset(
    point_a: Vec3,
    u_a: Vec3,
    v_a: Vec3,
    point_b: Vec3,
    d_point_a: Vec3,
    d_u_a: Vec3,
    d_v_a: Vec3,
    d_point_b: Vec3,
) -> tuple[float, float]:
    """``d/dt`` of :func:`residual_concentric_offset`, moving frame included."""
    delta = _sub(point_b, point_a)
    d_delta = _sub(d_point_b, d_point_a)
    return (
        _dot(d_delta, u_a) + _dot(delta, d_u_a),
        _dot(d_delta, v_a) + _dot(delta, d_v_a),
    )


def residual_cross(a: Vec3, b: Vec3) -> Vec3:
    """``cross(d_a, d_b)`` - zero for parallel *and* anti-parallel directions.

    Which is exactly what folding the angle means
    (``geom/constraints.py:372-375``), so the reformulation reproduces the
    engine's folded number rather than a stricter one. It serves both
    ``concentric``'s axis-alignment class predicate and ``parallel``'s primary
    component: the two are the same arithmetic on different primitives, and
    ``SOLVER.md`` §3.3 gives them the same identity.
    """
    return _cross(a, b)


def d_cross(a: Vec3, b: Vec3, d_a: Vec3, d_b: Vec3) -> Vec3:
    """``d/dt`` of :func:`residual_cross`."""
    return _add(_cross(d_a, b), _cross(a, d_b))


def residual_perpendicular(a: Vec3, b: Vec3) -> tuple[float]:
    """``dot(d_a, d_b)`` - signed, smooth everywhere, zero exactly at square."""
    return (_dot(a, b),)


def d_perpendicular(a: Vec3, b: Vec3, d_a: Vec3, d_b: Vec3) -> tuple[float]:
    """``d/dt`` of :func:`residual_perpendicular`."""
    return (_dot(d_a, b) + _dot(a, d_b),)


def residual_signed_offset(measured: float, value: float) -> tuple[float]:
    """``measured - value`` — a ``distance`` term's error, signed (``SOLVER.md`` §2C).

    The 2C-only companion to the four §3.3 reformulations, and it is a
    reformulation for the same reason they are: the engine reports
    ``deviation_mm = |measured - value_mm|`` (``geom/constraints.py:650-653``),
    whose kink sits exactly at the declared separation — the solution. The
    signed form is zero in the same place, smooth through it, and ``abs``
    recovers the engine's own ``deviation_mm`` exactly, which is the identity
    the verification pass compares per component.

    ``distance`` is admitted as an objective term **only** in parameter space
    (§3.2): its witness pair switches discontinuously as surfaces slide, so it
    is a local model rather than a global one, and every result naming one
    lists it in ``nonsmooth_terms``.
    """
    return (measured - value,)


def residual_window(measured: float, low: float, high: float) -> tuple[float]:
    """How far ``measured`` sits OUTSIDE ``[low, high]``, signed; zero inside.

    A ``fit``'s declared bound is a window rather than a tolerance
    (``geom/constraints.py:790-800``: ``satisfied`` is
    ``min_mm <= measured <= max_mm``), so its residual is a **deadband**:
    negative below the window, positive above it, and exactly ``0.0`` anywhere
    inside. That is the shape the constraint actually claims — a fit asks for a
    clearance in a range, not for one particular clearance — and driving to a
    single value inside the window would be the solver inventing an intent the
    declaration does not carry.

    ``abs`` recovers ``max(0.0, -slack)``, which is what the verification pass
    compares against the kernel's own row. The deadband's flat interior is the
    reason the sensitivity test of :func:`insensitive_sources` asks about
    satisfaction as well as about the derivative: inside the window this column
    block is legitimately zero, and a solve must not be refused for it.
    """
    if measured < low:
        return (measured - low,)
    if measured > high:
        return (measured - high,)
    return (0.0,)


def residual_point_target(point: Vec3, target: Vec3) -> Vec3:
    """``p - target`` - an anchor-to-point target's error, in world mm.

    The inverse of ``reach`` (``KINEMATICS.md:203-208``) taken on the anchor's
    REFERENCE POINT rather than on the shape-to-point extremum ``reach``
    itself measures. The extremum is ``kernel_extremum`` by ``SOLVER.md``
    §3.2's own taxonomy - a witness pair that switches discontinuously as
    surfaces slide - so driving it would be exactly the defect §3.2 excludes
    ``distance`` for. The reference-point error is smooth, and it is a
    STRICTER claim: it is never smaller than the shape-to-point distance, so a
    solve that reaches it has reached the point in the ``reach`` sense too and
    ``pose_found`` cannot overclaim.
    """
    return _sub(point, target)


# --------------------------------------------------------------------------
# the residual model a caller assembles


ComponentRole = Literal["primary", "class_predicate", "target"]


@dataclass(frozen=True)
class ComponentSpec:
    """One row block of the residual vector, with the bound it is judged by.

    Attributes:
        key: unique within a model — ``"c-mate:gap"``, ``"c-mate:normals"``.
        source_id: the constraint id or target id this component belongs to.
        kind: the 8C kind, or ``"anchor_point"`` for an anchor-to-point target.
        role: ``primary`` (the kind's headline quantity), ``class_predicate``
            (``coincident``'s opposed normals, ``concentric``'s axis
            alignment — the components residual-within-tolerance does **not**
            imply, ``SOLVER.md`` §3.1) or ``target``.
        unit: ``mm`` or ``deg`` — the measurement domain, never inferred.
        dim: how many raw rows the component contributes.
        bound: the declared bound in the measurement domain. For a class
            predicate this is the entry's own ``normal_eps_deg`` /
            ``axis_eps_deg``, read from what was declared and never assumed.
        identity: which :data:`IDENTITIES` member maps ``raw`` to ``measured``.
    """

    key: str
    source_id: str
    kind: str
    role: ComponentRole
    unit: Literal["mm", "deg"]
    dim: int
    bound: float
    identity: Identity

    @property
    def scale(self) -> float:
        """This component's measurement-domain factor (:func:`component_scale`)."""
        return component_scale(self.identity)


@dataclass(frozen=True)
class ComponentValue:
    """One component evaluated at one iterate: the raw vector and its meaning."""

    key: str
    raw: tuple[float, ...]
    #: The engine-domain number :func:`recover_measurement` gives for ``raw``.
    measured: float
    #: ``measured <= bound``. NOT a verdict: the verdict is read from the
    #: kernel's own ``ConstraintResidual.satisfied`` after re-measurement
    #: (``SOLVER.md`` §7.4), and this flag only steers the iteration.
    within_bound: bool


@dataclass(frozen=True)
class SolveVariable:
    """One free scalar, with the box it may not silently leave.

    ``lower``/``upper`` are the DECLARED limits (a joint's ``JointLimits``, a
    ``Param``'s ``min``/``max``); ``None`` is unbounded. A step that would
    leave the box is shortened to the boundary and the variable is reported in
    ``bounds_active`` — never clamped in silence, the refusal-never-clamp rule
    of ``geom/kinematics.py:217-245``.
    """

    name: str
    unit: str
    lower: float | None = None
    upper: float | None = None


class ResidualModel(Protocol):
    """What :func:`solve_least_squares` needs from a solve space.

    Deliberately tiny: the spaces (pose in 13A, transform and parameters
    later) differ only in what a variable vector means, so the iteration is
    written once and each space supplies :meth:`evaluate`. A model that can
    differentiate itself returns rows from :meth:`jacobian`; one that cannot
    returns ``None`` and gets a central finite difference of the SAME
    reformulated residual.
    """

    @property
    def variables(self) -> tuple[SolveVariable, ...]:
        """The free scalars, in the fixed order every vector below uses."""
        ...

    @property
    def components(self) -> tuple[ComponentSpec, ...]:
        """The residual's row blocks, in a fixed order."""
        ...

    def evaluate(self, x: Sequence[float]) -> tuple[tuple[float, ...], ...]:
        """The raw reformulated vector per component, in :attr:`components` order."""
        ...

    def jacobian(self, x: Sequence[float]) -> tuple[tuple[float, ...], ...] | None:
        """Rows of ``∂raw/∂x``, or ``None`` to take a central difference."""
        ...


@dataclass(frozen=True)
class WeightPolicy:
    """How mm and deg rows are made comparable — a declared choice, never a default.

    ``SOLVER.md`` §3.4 on the ``COMPARE.md:34-36`` precedent: "Alignment is a
    declared choice, NEVER a silent normalization." ``unit_scaled_v1`` weights
    length rows 1.0 per mm and angular rows by
    ``characteristic_radius_mm * π/180``, so one degree of tilt costs what that
    tilt moves at the part's extremity; ``declared`` takes the pair from the
    caller. Either way :meth:`applied` is echoed in the record beside the
    residuals, per component.
    """

    mode: Literal["unit_scaled_v1", "declared"]
    mm: float
    deg: float
    characteristic_radius_mm: float | None = None

    @classmethod
    def unit_scaled_v1(cls, characteristic_radius_mm: float) -> WeightPolicy:
        return cls(
            mode="unit_scaled_v1",
            mm=1.0,
            deg=characteristic_radius_mm * math.pi / 180.0,
            characteristic_radius_mm=characteristic_radius_mm,
        )

    @classmethod
    def declared(cls, *, mm: float, deg: float) -> WeightPolicy:
        return cls(mode="declared", mm=mm, deg=deg)

    def applied(self, spec: ComponentSpec) -> float:
        """The weight this component's rows carry.

        Class-predicate components carry their OWN weight rather than a share
        of the primary's (``SOLVER.md`` §3.4): both class bounds are 1e-3 deg,
        three orders tighter than a typical ``tol_mm``, so folding them into
        one weight would let the tight bound dominate every step or vanish
        entirely depending on the declared numbers.
        """
        return (self.mm if spec.unit == "mm" else self.deg) * spec.scale


# --------------------------------------------------------------------------
# refusals


class SolveRefused(ValueError):
    """A named refusal from the iteration — never a verdict.

    ``SOLVER.md`` §6.3 copies ``core/motion.py:1489-1498``'s rule exactly: "a
    killed sweep decided nothing, and giving the kill a verdict spelling would
    let a timeout be read as an outcome". ``reason`` is the name; the engine
    carries it out with whatever partial evidence exists.
    """

    code = "solve_refused"

    def __init__(
        self,
        reason: str,
        message: str,
        *,
        detail: Mapping[str, object] | None = None,
        x: Sequence[float] = (),
    ):
        super().__init__(message)
        self.reason = reason
        self.message = message
        #: Whatever the refusal knows, as plain JSON-shaped data. Widened from
        #: numbers alone at 13C, because ``unbuildable_parameter_iterate``
        #: carries the candidate's own build error record (``SOLVER.md`` §6.3:
        #: "a candidate whose preview build failed, carrying the build error"),
        #: and a refusal that had to drop the error to fit its own type would
        #: be a named refusal without the fact it exists to name.
        self.detail: Mapping[str, object] = dict(detail or {})
        #: The iterate the refusal happened AT, when there is one. A refusal
        #: that threw away the partial evidence would be the hang this
        #: vocabulary exists to replace: ``core/motion.py:1489-1498`` makes
        #: carrying what was already computed part of what a named refusal is.
        self.x: tuple[float, ...] = tuple(x)


# --------------------------------------------------------------------------
# fixed-order linear algebra (no BLAS, no RNG — ``SOLVER.md`` §9)

Matrix = list[list[float]]


def _zeros(rows: int, cols: int) -> Matrix:
    return [[0.0] * cols for _ in range(rows)]


def rank_revealing_qr(a: Sequence[Sequence[float]]) -> tuple[Matrix, list[int], list[float]]:
    """Householder QR with column pivoting: ``(R, pivots, pivot magnitudes)``.

    Fixed order throughout — the pivot is the column of largest remaining
    norm, ties broken by the lower column index — so two processes produce the
    same factorisation bit for bit. Written out here rather than delegated to
    ``numpy`` because its BLAS backend is threaded and dispatch-dependent,
    which ``SOLVER.md`` §9 shows would forfeit the D1 tier.
    """
    rows = len(a)
    cols = len(a[0]) if rows else 0
    r: Matrix = [list(row) for row in a]
    pivots = list(range(cols))
    magnitudes: list[float] = []
    norms = [math.sqrt(sum(r[i][j] * r[i][j] for i in range(rows))) for j in range(cols)]
    for k in range(min(rows, cols)):
        best = k
        for j in range(k + 1, cols):
            if norms[j] > norms[best] * (1.0 + 1e-15):
                best = j
        if best != k:
            for row in r:
                row[k], row[best] = row[best], row[k]
            pivots[k], pivots[best] = pivots[best], pivots[k]
            norms[k], norms[best] = norms[best], norms[k]
        alpha = math.sqrt(sum(r[i][k] * r[i][k] for i in range(k, rows)))
        magnitudes.append(alpha)
        if alpha == 0.0:
            for j in range(k, cols):
                norms[j] = math.sqrt(sum(r[i][j] * r[i][j] for i in range(k + 1, rows)))
            continue
        if r[k][k] > 0.0:
            alpha = -alpha
        v = [0.0] * rows
        for i in range(k, rows):
            v[i] = r[i][k]
        v[k] -= alpha
        vnorm2 = sum(v[i] * v[i] for i in range(k, rows))
        if vnorm2 > 0.0:
            for j in range(k, cols):
                dot = sum(v[i] * r[i][j] for i in range(k, rows))
                factor = 2.0 * dot / vnorm2
                for i in range(k, rows):
                    r[i][j] -= factor * v[i]
        for j in range(k + 1, cols):
            norms[j] = math.sqrt(sum(r[i][j] * r[i][j] for i in range(k + 1, rows)))
    for i in range(rows):
        for j in range(min(i, cols)):
            r[i][j] = 0.0
    return r, pivots, magnitudes


def _decide_rank(magnitudes: Sequence[float], cols: int) -> int:
    """The rank the pivots decide, or ``rank_undecidable`` when they cannot.

    ``SOLVER.md`` §4.2 step 3: pivots that straddle ``RANK_TOL_REL`` more
    tightly than :data:`RANK_MARGIN_REL` do not decide anything, and picking
    one anyway would silently answer "is this solution unique?".
    """
    if not magnitudes:
        return 0
    largest = max(abs(value) for value in magnitudes)
    if largest == 0.0:
        return 0
    threshold = largest * RANK_TOL_REL
    retained = [abs(value) for value in magnitudes if abs(value) > threshold]
    discarded = [abs(value) for value in magnitudes if abs(value) <= threshold]
    # Columns beyond the number of rows are structurally absent from the
    # factorisation and count as discarded with magnitude zero.
    if len(magnitudes) < cols:
        discarded.append(0.0)
    smallest_retained = min(retained) if retained else math.inf
    largest_discarded = max(discarded) if discarded else 0.0
    if smallest_retained < threshold * RANK_MARGIN_REL:
        raise SolveRefused(
            "rank_undecidable",
            f"the smallest retained pivot {smallest_retained:.6g} sits within "
            f"RANK_MARGIN_REL ({RANK_MARGIN_REL}) of the rank threshold "
            f"{threshold:.6g}; the rank is not decided and a guessed rank would "
            "silently decide whether this answer is unique (SOLVER.md §4.2)",
            detail={"threshold": threshold, "smallest_retained": smallest_retained},
        )
    if largest_discarded > threshold / RANK_MARGIN_REL:
        raise SolveRefused(
            "rank_undecidable",
            f"the largest discarded pivot {largest_discarded:.6g} sits within "
            f"RANK_MARGIN_REL ({RANK_MARGIN_REL}) of the rank threshold "
            f"{threshold:.6g}; the rank is not decided (SOLVER.md §4.2)",
            detail={"threshold": threshold, "largest_discarded": largest_discarded},
        )
    return len(retained)


@dataclass(frozen=True)
class NullDirection:
    """One free direction of an under-determined solution set, named.

    ``SOLVER.md`` §6.1 verdict 2 requires the basis to be *named*, not merely
    counted: a reader has to see what is free. :attr:`label` is the
    human-readable form and :attr:`components` the numbers behind it, so the
    naming is checkable rather than decorative.
    """

    label: str
    components: tuple[tuple[str, float], ...]


def null_space(
    a: Sequence[Sequence[float]], names: Sequence[str]
) -> tuple[int, tuple[NullDirection, ...], float]:
    """``(rank, named null-space basis, conditioning surrogate)`` of ``a``.

    Raises :class:`SolveRefused` (``rank_undecidable``) when the pivots do not
    decide the rank. The conditioning surrogate is the ratio of largest to
    smallest retained pivot — the ``kappa`` a fixture records beside its
    hand-computed answer, so a gate can say whether it is asserting residual
    accuracy or solution accuracy (``SOLVER.md`` Gates).
    """
    cols = len(names)
    if not a or cols == 0:
        return 0, (), 1.0
    r, pivots, magnitudes = rank_revealing_qr(a)
    rank = _decide_rank(magnitudes, cols)
    retained = [abs(value) for value in magnitudes[:rank]]
    kappa = (max(retained) / min(retained)) if retained else 1.0
    directions: list[NullDirection] = []
    for free in range(rank, cols):
        vector = [0.0] * cols
        vector[pivots[free]] = 1.0
        # Back-substitute R[:rank,:rank] z = -R[:rank, free].
        z = [0.0] * rank
        for i in range(rank - 1, -1, -1):
            accumulated = -r[i][free]
            for j in range(i + 1, rank):
                accumulated -= r[i][j] * z[j]
            z[i] = accumulated / r[i][i] if r[i][i] != 0.0 else 0.0
        for i in range(rank):
            vector[pivots[i]] = z[i]
        length = math.sqrt(sum(value * value for value in vector))
        if length > 0.0:
            vector = [value / length for value in vector]
        terms = tuple(
            (names[index], value) for index, value in enumerate(vector) if abs(value) > 1e-12
        )
        label = " + ".join(f"{value:+.6g} * {name}" for name, value in terms) or "(degenerate)"
        directions.append(NullDirection(label=label, components=terms))
    return rank, tuple(directions), kappa


def _solve_spd(matrix: Sequence[Sequence[float]], rhs: Sequence[float]) -> list[float] | None:
    """``LDLᵀ`` solve of a symmetric positive-(semi)definite system, fixed order."""
    n = len(rhs)
    lower: Matrix = _zeros(n, n)
    diagonal = [0.0] * n
    for i in range(n):
        for j in range(i):
            accumulated = matrix[i][j]
            for k in range(j):
                accumulated -= lower[i][k] * lower[j][k] * diagonal[k]
            lower[i][j] = accumulated / diagonal[j] if diagonal[j] != 0.0 else 0.0
        accumulated = matrix[i][i]
        for k in range(i):
            accumulated -= lower[i][k] * lower[i][k] * diagonal[k]
        if accumulated <= 0.0:
            return None
        diagonal[i] = accumulated
        lower[i][i] = 1.0
    y = [0.0] * n
    for i in range(n):
        accumulated = rhs[i]
        for k in range(i):
            accumulated -= lower[i][k] * y[k]
        y[i] = accumulated
    z = [y[i] / diagonal[i] for i in range(n)]
    out = [0.0] * n
    for i in range(n - 1, -1, -1):
        accumulated = z[i]
        for k in range(i + 1, n):
            accumulated -= lower[k][i] * out[k]
        out[i] = accumulated
    return out


# --------------------------------------------------------------------------
# the iteration


Termination = Literal["tolerance", "stationary", "stalled", "iteration_ceiling"]


@dataclass(frozen=True)
class TraceStep:
    """One accepted iteration, for replay (``SOLVER.md`` §9).

    Evidence about a RUN, never about the design: nothing downstream reads it
    to decide anything, and the engine stores it beside the proposal rather
    than inside the ``solver_core`` block precisely so that the block's
    byte-identity claim is about the answer and not about how the iteration
    happened to get there.
    """

    iteration: int
    #: The Levenberg-Marquardt damping accepted at this step.
    damping: float
    #: ``||weighted r||inf`` after the step.
    weighted_inf_norm: float
    #: The weighted sum of squares after the step.
    cost: float

    def to_json(self) -> dict[str, float | int]:
        return {
            "iteration": self.iteration,
            "damping": self.damping,
            "weighted_inf_norm": self.weighted_inf_norm,
            "cost": self.cost,
        }


@dataclass(frozen=True)
class SolveIterate:
    """One start's answer, with everything needed to distrust it.

    This is a CANDIDATE and the type says so by carrying no verdict field. The
    verdict is decided by :mod:`hephaestus.core.placement` after re-measuring
    through the ordinary engine path in another process (``SOLVER.md`` §7);
    ``SOLVER.md`` §4.2 step 6 calls the termination test below "a *candidate*
    test only".
    """

    x: tuple[float, ...]
    values: tuple[ComponentValue, ...]
    termination: Termination
    iterations: int
    weighted_inf_norm: float
    stationarity: float
    rank: int
    dof_remaining: int
    null_basis: tuple[NullDirection, ...]
    bounds_active: tuple[str, ...]
    kappa: float
    from_start: str
    #: Per-iteration replay evidence (``SOLVER.md`` §9). Empty is a legitimate
    #: value: a start that terminated on its first evaluation took no step.
    trace: tuple[TraceStep, ...] = ()

    @property
    def all_within_bounds(self) -> bool:
        """Every component inside its own declared bound (``SOLVER.md`` §4.2 step 6)."""
        return all(value.within_bound for value in self.values)


def _stacked(
    specs: Sequence[ComponentSpec], raw: Sequence[Sequence[float]], policy: WeightPolicy
) -> list[float]:
    out: list[float] = []
    for spec, vector in zip(specs, raw, strict=True):
        weight = policy.applied(spec)
        out.extend(value * weight for value in vector)
    return out


def central_difference_jacobian(
    model: ResidualModel, x: Sequence[float], *, step: float = JACOBIAN_FD_STEP
) -> tuple[tuple[float, ...], ...]:
    """``∂raw/∂x`` by central difference of the SAME reformulated residual.

    The fallback for a model that supplies no analytic rows, and — with
    ``step=PARAM_FD_STEP`` — the *only* derivative parameter space has, since a
    ``Param`` reaches the geometry through a build and nothing here can
    differentiate a script (``SOLVER.md`` §2C, NW11). One driver rather than
    two: a second finite difference would be a second place for the step, the
    box handling and the divisor to drift apart, and it would be least tested
    exactly where §3.3 says a derivative matters most.

    The step is relative to the variable's own magnitude with an absolute
    floor, so a parameter in mm and one in degrees are differenced at
    comparable precision.

    **Probes stay inside the declared box.** A variable sitting on its
    ``Param`` min (or a joint limit) cannot be probed outward: the build would
    be refused ``param_out_of_bounds``, and reporting that as an unbuildable
    iterate would blame the design for the differencing. So each probe is
    clipped to the box and the divisor is the span actually taken — a one-sided
    difference at a bound, a central one everywhere else. A variable whose box
    is a single point yields a zero column, which is the truth about it.
    """
    base = list(x)
    variables = model.variables
    height = sum(spec.dim for spec in model.components)
    columns: list[list[float]] = []
    for index in range(len(base)):
        variable = variables[index]
        reach = step * max(1.0, abs(base[index]))
        high = base[index] + reach
        low = base[index] - reach
        if variable.upper is not None:
            high = min(high, variable.upper)
        if variable.lower is not None:
            low = max(low, variable.lower)
        span = high - low
        if span <= 0.0:
            # A box that is a single point. The column is zero and the row
            # count comes from the component shapes rather than from an
            # evaluation: spending a preview build to learn a length already
            # declared would be paying kernel time for arithmetic.
            columns.append([0.0] * height)
            continue
        forward = list(base)
        forward[index] = high
        backward = list(base)
        backward[index] = low
        plus = [value for vector in model.evaluate(forward) for value in vector]
        minus = [value for vector in model.evaluate(backward) for value in vector]
        columns.append([(a - b) / span for a, b in zip(plus, minus, strict=True)])
    rows = len(columns[0]) if columns else 0
    return tuple(tuple(column[i] for column in columns) for i in range(rows))


def insensitive_sources(
    specs: Sequence[ComponentSpec],
    rows: Sequence[Sequence[float]],
    values: Sequence[ComponentValue],
    *,
    eps: float = SENSITIVITY_EPS,
) -> tuple[str, ...]:
    """The sources no free variable moves and that are not already satisfied.

    ``SOLVER.md`` §2C's ``no_free_variable_affects``, as the pure half: "a
    constraint whose residual is insensitive to every free parameter, detected
    as an all-zero Jacobian column block beyond ``SENSITIVITY_EPS``". Parameter
    space's cost is stated as a limitation rather than routed around — **it can
    only reach placements the author parameterised** — and this is how the
    unreachable case gets a name instead of a shrug.

    Two conditions, both required, and the second is the correction the naive
    reading needs. A ``fit`` inside its window contributes an identically flat
    deadband (:func:`residual_window`) and so does any component already at its
    bound in a design where nothing moves it; those are constraints that
    **hold**, and refusing a solve over a constraint that holds would name a
    failure that is not there. So a source is reported here only when every one
    of its rows is flat in every free variable **and** at least one of its
    components is outside its own declared bound: nothing can move it and it is
    not where it needs to be.

    ``rows`` is the Jacobian in :func:`central_difference_jacobian`'s shape —
    one row per scalar residual entry, in ``specs`` order — and ``values`` are
    the same components evaluated at the same iterate.
    """
    if not rows:
        return ()
    by_key = {value.key: value for value in values}
    flat: list[str] = []
    unsatisfied: set[str] = set()
    sensitive: set[str] = set()
    index = 0
    for spec in specs:
        block = rows[index : index + spec.dim]
        index += spec.dim
        value = by_key.get(spec.key)
        if value is not None and not value.within_bound:
            unsatisfied.add(spec.source_id)
        if any(abs(entry) > eps for row in block for entry in row):
            sensitive.add(spec.source_id)
    for source_id in dict.fromkeys(spec.source_id for spec in specs):
        if source_id not in sensitive and source_id in unsatisfied:
            flat.append(source_id)
    return tuple(flat)


def _values_of(
    specs: Sequence[ComponentSpec], raw: Sequence[Sequence[float]]
) -> tuple[ComponentValue, ...]:
    out: list[ComponentValue] = []
    for spec, vector in zip(specs, raw, strict=True):
        measured = recover_measurement(spec.identity, vector)
        out.append(
            ComponentValue(
                key=spec.key,
                raw=tuple(vector),
                measured=measured,
                within_bound=measured <= spec.bound,
            )
        )
    return tuple(out)


def component_values(model: ResidualModel, x: Sequence[float]) -> tuple[ComponentValue, ...]:
    """Every component's raw vector, engine-domain number and bound test at ``x``.

    The public form of what the iteration computes each step. The engine needs
    it for an iterate a REFUSAL happened at - a timed-out or ceiling-stopped
    run still has to carry its best iterate and that iterate's numbers
    (``core/motion.py:1489-1498``), and re-deriving them from the outside
    would be a second implementation of the same arithmetic.
    """
    return _values_of(model.components, model.evaluate(x))


def _clip_to_box(
    variables: Sequence[SolveVariable], x: Sequence[float], step: Sequence[float]
) -> tuple[list[float], list[str]]:
    """``step`` projected onto the declared box, with the bounds it went to.

    ``SOLVER.md`` §4.2 step 4: bounds are never clamped silently. A step that
    would leave the box is *shortened to the boundary* and every variable
    sitting on its bound afterwards is named, because a solution on a bound is
    a boundary solution and not a stationary point.

    Shortened **per variable**, not by scaling the whole step down. Scaling
    preserves the step direction, which is prettier, and it DEADLOCKS: once one
    variable sits on its bound and the step pushes further out, the scale
    factor is zero, so nothing moves at all, no trial ever lowers the cost, and
    the run reports a stall while the remaining degrees of freedom still had
    somewhere to go. The projected step is the honest one — it moves what can
    move, refuses to move what cannot, and says which.
    """
    moved = list(x)
    active: list[str] = []
    for index, variable in enumerate(variables):
        target = x[index] + step[index]
        if variable.lower is not None and target < variable.lower:
            target = variable.lower
        if variable.upper is not None and target > variable.upper:
            target = variable.upper
        moved[index] = target
        at_lower = variable.lower is not None and target <= variable.lower + 1e-12
        at_upper = variable.upper is not None and target >= variable.upper - 1e-12
        if at_lower or at_upper:
            active.append(variable.name)
    return moved, active


def solve_least_squares(
    model: ResidualModel,
    start: Sequence[float],
    *,
    policy: WeightPolicy,
    tol: float,
    iteration_ceiling: int,
    start_id: str = "as_built",
    deadline: Callable[[], bool] | None = None,
) -> SolveIterate:
    """Weighted Levenberg-Marquardt from one declared start (``SOLVER.md`` §4.2).

    Returns the iterate it reached and how it terminated. It does **not**
    return a verdict, and the three terminations are facts about the
    iteration, not claims about the geometry: ``tolerance`` means the weighted
    residual is inside ``tol`` *and* every component is inside its own declared
    bound (step 6 — ``‖weighted r‖∞ <= tol`` alone was the earlier draft's
    mistake); ``stationary`` means the gradient vanished with the residual
    still above tolerance; ``iteration_ceiling`` means neither happened in the
    budget, which the engine turns into a named refusal carrying this iterate.

    ``deadline`` is the wall-clock ceiling the engine owns
    (``SOLVER.md`` §10): called once per iteration, and a ``True`` return
    raises :class:`SolveRefused` (``solver_timeout``) carrying nothing, because
    the engine holds the partial evidence.

    Raises :class:`SolveRefused` (``rank_undecidable``) when the rank at the
    returned iterate is not decidable.
    """
    variables = model.variables
    specs = model.components
    names = [variable.name for variable in variables]
    x = list(start)
    lam = 1e-3
    iterations = 0
    stalled = False
    trace: list[TraceStep] = []
    bounds_active: list[str] = []
    raw = model.evaluate(x)
    weighted = _stacked(specs, raw, policy)
    cost = sum(value * value for value in weighted)
    for iterations in range(1, iteration_ceiling + 1):
        if deadline is not None and deadline():
            raise SolveRefused(
                "solver_timeout",
                f"the wall-clock ceiling fired after {iterations - 1} iterations "
                "(SOLVER.md §10); a killed solve decided nothing",
                x=x,
            )
        values = _values_of(specs, raw)
        inf_norm = max((abs(value) for value in weighted), default=0.0)
        if inf_norm <= tol and all(value.within_bound for value in values):
            iterations -= 1
            break
        jac = model.jacobian(x) or central_difference_jacobian(model, x)
        wj = _weight_rows(specs, jac, policy)
        gradient = [
            sum(wj[row][col] * weighted[row] for row in range(len(weighted)))
            for col in range(len(names))
        ]
        gradient_norm = max((abs(value) for value in gradient), default=0.0)
        if gradient_norm <= STATIONARITY_EPS * max(1.0, inf_norm):
            iterations -= 1
            break
        hessian = [
            [
                sum(wj[row][i] * wj[row][j] for row in range(len(weighted)))
                for j in range(len(names))
            ]
            for i in range(len(names))
        ]
        stepped = False
        for _attempt in range(24):
            damped = [
                [
                    hessian[i][j] + (lam * max(hessian[i][i], 1e-12) if i == j else 0.0)
                    for j in range(len(names))
                ]
                for i in range(len(names))
            ]
            step = _solve_spd(damped, [-value for value in gradient])
            if step is None:
                lam *= 4.0
                continue
            moved, active = _clip_to_box(variables, x, step)
            trial_raw = model.evaluate(moved)
            trial_weighted = _stacked(specs, trial_raw, policy)
            trial_cost = sum(value * value for value in trial_weighted)
            if trial_cost < cost:
                x, raw, weighted, cost = moved, trial_raw, trial_weighted, trial_cost
                bounds_active = active
                trace.append(
                    TraceStep(
                        iteration=iterations,
                        damping=lam,
                        weighted_inf_norm=max((abs(v) for v in weighted), default=0.0),
                        cost=cost,
                    )
                )
                lam = max(lam / 3.0, 1e-12)
                stepped = True
                break
            lam *= 4.0
        if not stepped:
            stalled = True
            break
    else:
        iterations = iteration_ceiling
    values = _values_of(specs, raw)
    weighted = _stacked(specs, raw, policy)
    inf_norm = max((abs(value) for value in weighted), default=0.0)
    jac = model.jacobian(x) or central_difference_jacobian(model, x)
    wj = _weight_rows(specs, jac, policy)
    gradient = [
        sum(wj[row][col] * weighted[row] for row in range(len(weighted)))
        for col in range(len(names))
    ]
    gradient_norm = max((abs(value) for value in gradient), default=0.0)
    try:
        rank, basis, kappa = null_space(wj, names)
    except SolveRefused as exc:
        exc.x = tuple(x)
        raise
    converged = inf_norm <= tol and all(value.within_bound for value in values)
    stationary = gradient_norm <= STATIONARITY_EPS * max(1.0, inf_norm)
    termination: Termination
    if converged:
        termination = "tolerance"
    elif stationary:
        termination = "stationary"
    elif stalled:
        # No damped step improved the cost. The budget was NOT spent, so
        # calling this ``iteration_ceiling`` would let the engine raise a
        # ceiling refusal for a run that never hit one - a refusal naming the
        # wrong cause is worse than the fact it hides.
        termination = "stalled"
    else:
        termination = "iteration_ceiling"
    if converged and rank < len(names):
        x, raw, values, weighted, inf_norm = _pull_to_start(
            model, specs, policy, x, list(start), basis, names, tol
        )
    return SolveIterate(
        x=tuple(x),
        values=values,
        termination=termination,
        iterations=iterations,
        weighted_inf_norm=inf_norm,
        stationarity=gradient_norm,
        rank=rank,
        dof_remaining=len(names) - rank,
        null_basis=basis,
        bounds_active=tuple(sorted(set(bounds_active))),
        kappa=kappa,
        from_start=start_id,
        trace=tuple(trace),
    )


def _pull_to_start(
    model: ResidualModel,
    specs: Sequence[ComponentSpec],
    policy: WeightPolicy,
    x: Sequence[float],
    start: Sequence[float],
    basis: Sequence[NullDirection],
    names: Sequence[str],
    tol: float,
) -> tuple[
    list[float],
    tuple[tuple[float, ...], ...],
    tuple[ComponentValue, ...],
    list[float],
    float,
]:
    """``min_norm_from_start``: the member of the solution set nearest the start.

    ``SOLVER.md`` §3.5. The regularisation is the only member of its
    vocabulary in Stage 13 and it is still *required and echoed*, because §6
    shows the Jacobian is rank-deficient by construction and choosing which
    null-space member to return is a design decision, not a numerical detail.
    "Nearest to what the author already wrote" is the only choice that
    respects P4 (``SOLVER.md`` §1.2): a reviewer reads a diff, and the
    smallest diff that satisfies the mate is the one they can read.

    Applied once, and only kept when the pulled iterate is still inside
    tolerance — a regularisation that walked out of the solution set would be
    trading the answer for tidiness.
    """
    index_of = {name: index for index, name in enumerate(names)}
    delta = [x[i] - start[i] for i in range(len(names))]
    pulled = list(x)
    for direction in basis:
        vector = [0.0] * len(names)
        for name, value in direction.components:
            vector[index_of[name]] = value
        projection = sum(vector[i] * delta[i] for i in range(len(names)))
        for i in range(len(names)):
            pulled[i] -= projection * vector[i]
    # The pull is a step like any other and obeys the same box: sliding along
    # the null space out of a declared limit would return an assignment nobody
    # may evaluate, which is the clamp ``geom/kinematics.py:217-245`` refuses
    # wearing a regularisation's clothes.
    pulled, _active = _clip_to_box(model.variables, pulled, [0.0] * len(names))
    raw = model.evaluate(pulled)
    values = _values_of(specs, raw)
    weighted = _stacked(specs, raw, policy)
    inf_norm = max((abs(value) for value in weighted), default=0.0)
    if inf_norm <= tol and all(value.within_bound for value in values):
        return pulled, raw, values, weighted, inf_norm
    raw = model.evaluate(x)
    values = _values_of(specs, raw)
    weighted = _stacked(specs, raw, policy)
    return list(x), raw, values, weighted, max((abs(v) for v in weighted), default=0.0)


def _weight_rows(
    specs: Sequence[ComponentSpec],
    jac: Sequence[Sequence[float]],
    policy: WeightPolicy,
) -> Matrix:
    out: Matrix = []
    row = 0
    for spec in specs:
        weight = policy.applied(spec)
        for _ in range(spec.dim):
            out.append([value * weight for value in jac[row]])
            row += 1
    return out


def weighted_distance(
    a: Sequence[float], b: Sequence[float], variables: Sequence[SolveVariable]
) -> float:
    """Euclidean distance between two assignments, in the variables' own units.

    Used for :func:`distinct_solutions` and for ranking multiple solutions by
    distance from ``as_built``. Deliberately unweighted across units: a pose
    assignment's variables are already in one unit per joint, and inventing a
    cross-unit weight for a *comparison* would be the silent normalization
    ``SOLVER.md`` §3.4 refuses for the objective.
    """
    del variables
    return math.sqrt(sum((x - y) * (x - y) for x, y in zip(a, b, strict=True)))


def distinct_solutions(
    iterates: Sequence[SolveIterate],
    variables: Sequence[SolveVariable],
    *,
    eps: float = SOLUTION_DISTINCT_EPS,
) -> tuple[SolveIterate, ...]:
    """The distinct members among converged iterates — every one of them.

    ``SOLVER.md`` §5: when two or more declared starts converge to solutions
    separated by more than :data:`SOLUTION_DISTINCT_EPS`, ALL of them are
    returned and the solver does not pick. Order is by first appearance, which
    the caller then re-ranks by distance from ``as_built``; nothing here marks
    one as chosen, because a bracket flipped 180° about a bore satisfies the
    same mates and rank tells you nothing about it.
    """
    kept: list[SolveIterate] = []
    for candidate in iterates:
        if all(weighted_distance(candidate.x, other.x, variables) > eps for other in kept):
            kept.append(candidate)
    return tuple(kept)
