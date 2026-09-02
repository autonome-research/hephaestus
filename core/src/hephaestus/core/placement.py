# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Solving: proposals, verified independently, that nothing applies.

``SOLVER.md`` §§2A, 2B, 4.1, 6, 7, 8 and 9 — the engine half of Stage 13,
mirroring the ``constraints.py`` <-> ``assembly.py`` and ``kinematics.py``
<-> ``motion.py`` split exactly. Two spaces live here and they share
everything but their variables: :func:`solve_pose` (13A) solves declared joint
parameters and writes nothing at all, and :func:`propose_placement` (13B)
solves a rigid transform per declared-free part and writes exactly one thing,
an immutable proposal document that **nothing applies**. :mod:`hephaestus.geom.solve` answers "what
assignment makes this residual vector small?" over frames and numbers a caller
already holds; this module answers the three questions geometry cannot: *which*
frames a ``part[:selector]`` anchor names, what an answer that could not be
computed is called, and — the one that carries the whole stage — **whether the
answer is believed**.

THE SOLVER PROPOSES (``mission_plan.md`` §"Stage 13", 2026-08-30)
-----------------------------------------------------------------
Nothing here writes a script, writes a parameter, republishes a transformed
artifact, or makes any build current. :func:`solve_pose` returns a **solve
record** and writes nothing at all — no proposal artifact, no pose
declaration, no generation. :func:`propose_placement` records a **proposal**,
which is a measurement: the constraint it was solved against keeps its
``violated`` row until a rebuilt script measures otherwise, and no tool
accepts the proposal id where a constraint id is expected. Applying either
answer stays an authoring act, performed through the existing
``declare_pose`` / ``edit_part`` / ``set_params`` surface, so scripts remain
the sole authority on position and the diff keeps carrying intent.
**Writeback is refused**: no inverse from a transform to a script expression
is computed, offered or guessed, and the refusal is structural rather than a
promise — the proposal document schema is ``additionalProperties: false`` at
every level and validated before any write, so a ``suggested_edit`` field is
not rejected by name, it is unrepresentable.

The four module contracts that say "no solver" today
(``geom/constraints.py:17-18``, ``geom/kinematics.py:17-21``,
``core/assembly.py:27-34``, ``core/motion.py:106-110``) are **not weakened**,
and this module restates them: nothing below moves what a script authored.

Why the answer is believed (``SOLVER.md`` §7)
---------------------------------------------
Never because the solver said it converged. Every returned assignment is
re-measured in a **separate process** whose import closure excludes
:mod:`hephaestus.geom.solve`, through the ordinary
:mod:`hephaestus.core.assembly` path — anchors resolved against current
artifacts, shapes placed by
:func:`~hephaestus.geom.kinematics.transformed_shape`, residuals from
:func:`~hephaestus.geom.constraints.evaluate_residual`. The verdict is then
read from :attr:`~hephaestus.geom.constraints.ConstraintResidual.satisfied`,
**not** from the residual number: a ``coincident`` pair lying flush in the
right plane and facing the wrong way measures ``gap == 0.0`` with
``satisfied == False``, and a solver graded on the number would call that
converged while the ``AssemblyStatus`` row still reads ``violated``. And if
the solver's own number and the kernel's ever disagree by more than
:data:`VERIFY_EPS`, the whole result is refused
``solver_residual_disagreement`` with no verdict emitted: a solver whose model
of the geometry has drifted from the kernel's is not producing evidence.

Honest states, each with its own name (``SOLVER.md`` §6)
--------------------------------------------------------
Convergence, non-convergence, over- and under-constrained systems, and
MULTIPLICITY are five different facts and they get five different spellings
(:data:`POSE_SOLVE_VERDICTS`, seven with ``pose_found`` and ``unresolvable``).
A system with many solutions is never silently resolved: two starts that
converge apart return ``multiple_poses_from_starts`` carrying **all** of them,
ranked by distance from ``as_built`` and none marked chosen. A rank-deficient
system returns ``pose_underdetermined_at_tolerance`` with its remaining
degrees of freedom named, because reporting one point of a continuum as *the*
answer is a claim the mathematics does not support. And refusals are not
verdicts — the ``core/motion.py:1489-1498`` rule copied exactly: a killed
solve decided nothing.
"""

from __future__ import annotations

import dataclasses
import math
import multiprocessing
import os
import re
import shutil
import tempfile
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal, cast

from hephaestus.core.assembly import (
    UNRESOLVABLE_REASONS,
    AnchorResolver,
    PublishedBuild,
    UnresolvableAnchorError,
)
from hephaestus.core.errors import ValidationError
from hephaestus.core.project_store.artifact_kinds import record_artifact_kind
from hephaestus.core.project_store.constraints import (
    WHOLE_PART_SELECTOR,
    ConstraintEntry,
    ConstraintProvenance,
    ConstraintSet,
    parse_anchor,
)
from hephaestus.core.project_store.layout import ProjectLayout
from hephaestus.core.project_store.publication import Publisher, build_bundle
from hephaestus.core.project_store.store import artifact_ref as make_artifact_ref
from opstore.types import JSONValue

from opstore import OpStore, canonical_json

__all__ = [
    "NOT_AN_OBJECTIVE_REASONS",
    "OBJECTIVE_EXCLUSIONS",
    "POSE_SOLVE_VERDICTS",
    "SO3_FAULT_ENV",
    "SOLVER_FAULT_ENV",
    "SOLVE_ITER_MAX",
    "SOLVE_ITER_MAX_ENV",
    "SOLVE_REQUEST_REFUSALS",
    "SOLVE_RESOLUTION_REFUSALS",
    "SOLVE_RUNTIME_REFUSALS",
    "SOLVE_TIMEOUT_ENV",
    "SOLVE_TIMEOUT_S",
    "TRANSFORM_AXES",
    "TRANSFORM_DOF",
    "TRANSFORM_SOLVE_VERDICTS",
    "VERIFY_EPS",
    "VERIFY_TIMEOUT_ENV",
    "VERIFY_TIMEOUT_S",
    "ConstraintTarget",
    "InvalidSolveRequest",
    "PlacementSolveRequest",
    "PointTarget",
    "PoseSolveRequest",
    "PoseSolveVerdict",
    "SolveRecord",
    "SolveRunRefusal",
    "SolveStart",
    "SolveTarget",
    "SolveUnresolvable",
    "SolveVerdict",
    "TransformSolveVerdict",
    "VerifiedComponent",
    "VerifiedConstraint",
    "propose_placement",
    "solve_iter_max",
    "solve_pose",
    "solve_timeout_s",
    "verify_timeout_s",
]

# --------------------------------------------------------------------------
# vocabulary

PoseSolveVerdict = Literal[
    "pose_found",
    "pose_converged_at_tolerance",
    "pose_underdetermined_at_tolerance",
    "multiple_poses_from_starts",
    "no_pose_found_from_starts",
    "pose_overconstrained_at_residual_floor",
    "unresolvable",
]

#: The pose-space verdict tuple, closed at **seven** (``SOLVER.md`` §6.1): the
#: six pose spellings plus ``pose_found``, the anchor-to-point existence claim
#: taken straight from ``KINEMATICS.md:209-222``'s asymmetry — one achieving
#: assignment IS proof, so its success spelling is an existence spelling.
#:
#: ``pose_found`` is emitted **only** for anchor-to-point targets and
#: ``pose_converged_at_tolerance`` **only** for constraint-id targets; a
#: request carrying both is scored on both and returns the constraint-id
#: spelling, because the weaker claim may not stand in for the stronger one.
#:
#: The words "solved", "infeasible", "no solution exists" and "holds" appear in
#: no member and in no payload this module produces. A local method's silence
#: is not infeasibility (``SOLVER.md`` §5), and calling it that would be a
#: claim about the whole configuration space from evidence about one basin.
POSE_SOLVE_VERDICTS: Final[tuple[PoseSolveVerdict, ...]] = (
    "pose_found",
    "pose_converged_at_tolerance",
    "pose_underdetermined_at_tolerance",
    "multiple_poses_from_starts",
    "no_pose_found_from_starts",
    "pose_overconstrained_at_residual_floor",
    "unresolvable",
)

TransformSolveVerdict = Literal[
    "converged_at_tolerance",
    "underdetermined_at_tolerance",
    "multiple_solutions_from_starts",
    "no_placement_found_from_starts",
    "overconstrained_at_residual_floor",
    "unresolvable",
]

#: The transform/parameter-space verdict tuple, closed at **six**
#: (``SOLVER.md`` §6.1). No ``found`` spelling here and the asymmetry is
#: deliberate: an anchor-to-point target is an existence claim and one
#: achieving assignment is proof of it, but a transform-space solve is scored
#: against declared 8C constraints, whose success test is the three-conjunct
#: one — every objective constraint re-measuring ``satisfied is True`` through
#: the ordinary engine path included. The weaker claim may not stand in for
#: the stronger one, so it is not in the vocabulary at all.
#:
#: ``converged_at_tolerance`` is never spelled "solved". The words
#: "infeasible", "impossible" and "no solution exists" appear in no member and
#: in no payload this module produces: a local method's silence is evidence
#: about one basin (``SOLVER.md`` §5).
TRANSFORM_SOLVE_VERDICTS: Final[tuple[TransformSolveVerdict, ...]] = (
    "converged_at_tolerance",
    "underdetermined_at_tolerance",
    "multiple_solutions_from_starts",
    "no_placement_found_from_starts",
    "overconstrained_at_residual_floor",
    "unresolvable",
)

SolveVerdict = PoseSolveVerdict | TransformSolveVerdict

#: The solve spaces ``propose_placement`` accepts, closed (``SOLVER.md`` §2).
#: Parameter space landed at 13C as an **enum value on the existing tool**
#: rather than a fourth tool: the 8A/8B lever (``SOLVER.md`` §11) says put the
#: capability in an existing enum, on the ``layout="nested_sheet"`` precedent
#: (``tool_schema.md:1409-1433``), because each tool costs five generated
#: drift-tested artifacts, a per-profile decision and a normative heading.
#:
#: Pose space (§2A) is deliberately absent: it is ``solve_pose``'s, it writes
#: nothing, and folding it in here would put a tool that records a proposal and
#: a tool that records nothing behind one name.
SOLVE_SPACES: Final[tuple[str, ...]] = ("transform", "parameters")

#: The verdict set is the SAME six in both proposal spaces (``SOLVER.md`` §6.1
#: opens "For 2B and 2C"). Named separately so a 2C gate clause can assert
#: against a name that says parameter space, and asserted equal to the
#: transform tuple so the two can never drift into two vocabularies.
PARAM_SOLVE_VERDICTS: Final[tuple[TransformSolveVerdict, ...]] = TRANSFORM_SOLVE_VERDICTS

#: Why a kind is refused as an objective term (``SOLVER.md`` §3.2). Each names
#: a different mathematical fact, not a preference:
#:
#: * ``plateau`` — ``clearance_min`` and ``no_interference`` are identically
#:   flat over a whole region (``geom/measure.py:62-71``, ``:92-101``), so a
#:   solver started there has no descent information at all and one that
#:   "optimises" them silently does not work.
#: * ``kernel_extremum`` — ``distance`` is ``a.distance_to(b)``, piecewise
#:   smooth with a witness pair that switches discontinuously as surfaces
#:   slide, and the kink sits exactly where mates live.
#: * ``pose_invariant`` — ``fit`` measures ``hole_radius - shaft_radius``,
#:   which no rigid motion changes, so it carries no gradient in pose space.
#:   (It is a legitimate term in 13C's parameter space, and that difference is
#:   the reason the reason is named rather than the kind merely excluded.)
NOT_AN_OBJECTIVE_REASONS: Final[tuple[str, ...]] = (
    "plateau",
    "kernel_extremum",
    "pose_invariant",
)

#: Which 8C kinds are not objective terms in pose space, and why. The four
#: absent from this table — ``coincident``, ``concentric``, ``parallel``,
#: ``perpendicular`` — are the analytic kinds whose ``measured`` is closed-form
#: in the transform (``SOLVER.md`` §3.2).
OBJECTIVE_EXCLUSIONS: Final[Mapping[str, str]] = {
    "no_interference": "plateau",
    "clearance_min": "plateau",
    "distance": "kernel_extremum",
    "fit": "pose_invariant",
}

#: The same table for **parameter space** (``SOLVER.md`` §3.2's second column),
#: and the difference between the two is the whole reason §3.2 names a *reason*
#: per exclusion rather than merely listing kinds.
#:
#: * ``fit`` is excluded from 2B as ``pose_invariant`` — ``hole_radius -
#:   shaft_radius`` is unchanged by any rigid motion, so it carries no gradient
#:   there — and **admitted in 2C**, where a ``Param`` change is exactly what
#:   does move it.
#: * ``distance`` is excluded from 2B as ``kernel_extremum`` and **admitted in
#:   2C**, disclosed: every 2C derivative is a finite difference anyway, and
#:   every result naming a ``distance`` term lists it in ``nonsmooth_terms``.
#: * The two plateau kinds stay excluded in **both**. They are feasibility
#:   filters, never objective terms: a flat region carries no descent
#:   information in any space, and a finite difference of a constant is zero in
#:   parameter space just as an analytic derivative of one is in transform
#:   space. They are still EVALUATED at the returned solution (§7.3).
PARAM_OBJECTIVE_EXCLUSIONS: Final[Mapping[str, str]] = {
    "no_interference": "plateau",
    "clearance_min": "plateau",
}

#: Which exclusion table each proposal space reads.
OBJECTIVE_EXCLUSIONS_BY_SPACE: Final[Mapping[str, Mapping[str, str]]] = {
    "transform": OBJECTIVE_EXCLUSIONS,
    "parameters": PARAM_OBJECTIVE_EXCLUSIONS,
}

#: Request-time refusals (``SOLVER.md`` §6.3), raised before anything is read
#: and with nothing written. Closed: a name outside this tuple is a spec
#: amendment, not an implementation detail.
#:
#: Two of these carry more than their literal reading, deliberately, and the
#: alternative would have been worse. ``unknown_joint`` covers three cases —
#: no such joint; a joint that IS declared but is a coupled child, which
#: ``KINEMATICS.md`` §5 makes a dependent parameter that a pose never assigns;
#: and a joint with no scalar parameter to solve for (``fixed``, 0 DOF, and
#: ``cylindrical``, whose pair a pose entry cannot express since
#: ``PoseEntry.joints`` is scalar-valued). The detail distinguishes them.
#: Adding a spelling would have amended ``SOLVER.md`` §6.3's closed set, which
#: this stage has no mandate for; dropping the joint silently would be the
#: "nothing silently skipped" failure. Naming the real reason in the detail is
#: the least-bad of the three and is recorded here rather than left to a
#: reader to discover.
SOLVE_REQUEST_REFUSALS: Final[tuple[str, ...]] = (
    "no_free_variables",
    "no_ground_part",
    "free_part_is_jointed",
    "free_part_in_no_constraint",
    "undeclared_weighting",
    "undeclared_regularization",
    "not_an_objective_kind",
    "pose_bound_constraint_in_transform_space",
    "unknown_constraint",
    "withdrawn_constraint",
    "unknown_param",
    "unbounded_param",
    "unknown_joint",
    "missing_provenance",
    "tolerance_below_determinism_floor",
)

#: Resolution-time refusals (``SOLVER.md`` §6.3): the nine
#: :data:`~hephaestus.core.assembly.UNRESOLVABLE_REASONS` verbatim — same
#: failure, same fix, same name, exactly as ``core/motion.py:225-249`` already
#: does — plus the two Stage 13 additions. A joint that will not resolve, or a
#: solved value outside a declared limit, lands on 8C's own
#: ``unresolvable_pose``, which already means "riding an unresolvable joint"
#: and "out of a joint's declared limits": reusing it beats inventing a
#: parallel spelling for the same fact.
SOLVE_RESOLUTION_REFUSALS: Final[tuple[str, ...]] = (
    *UNRESOLVABLE_REASONS,
    "stale_proposal_inputs",
    "no_free_variable_affects",
)

#: Run-time refusals (``SOLVER.md`` §6.3), each carrying the best iterate and
#: its independently re-measured residuals. **None of them is a verdict** —
#: the ``MotionTimeout`` rule (``core/motion.py:1489-1498``) copied exactly: a
#: killed solve decided nothing, and giving the kill a verdict spelling would
#: let a ceiling be read as an outcome.
SOLVE_RUNTIME_REFUSALS: Final[tuple[str, ...]] = (
    "solver_timeout",
    "iteration_ceiling",
    "build_budget_exhausted",
    "unbuildable_parameter_iterate",
    "non_rigid_iterate",
    "rank_undecidable",
    "solver_residual_disagreement",
)

#: How many Levenberg-Marquardt iterations one start may take before the
#: solve is refused ``iteration_ceiling`` carrying its best iterate.
SOLVE_ITER_MAX: Final[int] = 200

#: Environment override for :data:`SOLVE_ITER_MAX`.
SOLVE_ITER_MAX_ENV: Final[str] = "HEPHAESTUS_SOLVE_ITER_MAX"

#: Wall-clock ceiling on one solve's iteration (``SOLVER.md`` §10). A pose
#: iteration touches no kernel, so this is a backstop rather than the primary
#: bound; the primary bound is :data:`SOLVE_ITER_MAX`.
SOLVE_TIMEOUT_S: Final[float] = 60.0

#: Environment override for :data:`SOLVE_TIMEOUT_S` (seconds, float).
SOLVE_TIMEOUT_ENV: Final[str] = "HEPHAESTUS_SOLVE_TIMEOUT_S"

#: Wall-clock ceiling on ONE verification pass (``SOLVER.md`` §10). The
#: verification pass *does* touch the kernel, so it runs in a killable
#: subprocess under this ceiling — the ``core/motion.py`` sweep pattern, for
#: the same reason: a single boolean has ground for ~19 h on a pathological
#: B-rep (``COMPARE.md:152-176``).
VERIFY_TIMEOUT_S: Final[float] = 300.0

#: Environment override for :data:`VERIFY_TIMEOUT_S` (seconds, float).
VERIFY_TIMEOUT_ENV: Final[str] = "HEPHAESTUS_VERIFY_TIMEOUT_S"

#: Cap on the **total preview builds one parameter-space solve's ITERATION may
#: issue** (``SOLVER.md`` §10, 2C). Every 2C residual evaluation is a build per
#: measured part and every finite-difference Jacobian is a further two
#: evaluations per free variable, so an unbounded 2C solve is an unbounded
#: number of kernel evaluations — the exact shape ``COMPARE.md:152-176``
#: measured at ~19 h on one pathological boolean. Exhaustion is the named
#: refusal ``build_budget_exhausted``, carrying the best iterate and its
#: independently re-measured residuals; it is never a verdict.
#:
#: **What it does NOT cover, stated rather than left to be discovered.** The §7
#: verification pass builds too, and its builds are not charged here: §10 gives
#: that pass its own bound (``VERIFY_TIMEOUT_S``, per pass, in a killable
#: subprocess), and charging one ceiling's budget against another's would let a
#: solve that spent its iteration honestly be refused for the cost of checking
#: it. The record reports both counts separately for the same reason.
SOLVE_BUILD_BUDGET: Final[int] = 240

#: Environment override for :data:`SOLVE_BUILD_BUDGET` (integer).
SOLVE_BUILD_BUDGET_ENV: Final[str] = "HEPHAESTUS_SOLVE_BUILD_BUDGET"

#: How far the solver's own component number may sit from the kernel's
#: re-measured one before the whole result is refused
#: ``solver_residual_disagreement`` (``SOLVER.md`` §7.6). Disagreement is
#: fatal, not a warning: reporting the answer with a caveat would be exactly
#: the overclaim this project's vocabulary exists to prevent.
VERIFY_EPS: Final[float] = 1e-6

#: What a record says beside its ``nonsmooth_terms`` (``SOLVER.md`` §3.2). The
#: caveat is carried in the record rather than left to the reader, because a
#: descent over a function with a kink in it is a LOCAL model: the numbers are
#: real and the neighbourhood they are real in is smaller than a smooth term's.
NONSMOOTH_CAVEAT: Final[str] = (
    "these terms are a LOCAL model: `distance` is a kernel extremum whose witness "
    "pair switches discontinuously as surfaces slide (geom/measure.py:87-89, "
    "SOLVER.md §3.2), so the descent that reached this iterate is valid in a "
    "neighbourhood of it and claims nothing beyond one. The residuals reported here "
    "are still the engine's own, independently re-measured at the returned values."
)

#: Artifact kind of the per-run replay trace (``SOLVER.md`` §9). A trace is
#: **evidence about a run, never about the design**: nothing reads it to decide
#: anything, it is stored beside the proposal rather than inside it, and the
#: ``solver_core`` block's byte-identity claim is deliberately about the answer
#: rather than about how the iteration reached it.
_TRACE_KIND: Final[str] = "solve-trace"


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0.0 else default


def solve_iter_max() -> int:
    """The effective iteration ceiling: :data:`SOLVE_ITER_MAX_ENV` else the default."""
    raw = os.environ.get(SOLVE_ITER_MAX_ENV)
    if raw is None:
        return SOLVE_ITER_MAX
    try:
        value = int(raw)
    except ValueError:
        return SOLVE_ITER_MAX
    return value if value > 0 else SOLVE_ITER_MAX


def solve_timeout_s() -> float:
    """The effective solve ceiling (the ``motion_timeout_s`` local-floor pattern)."""
    return _env_float(SOLVE_TIMEOUT_ENV, SOLVE_TIMEOUT_S)


def solve_build_budget() -> int:
    """The effective 2C preview-build budget (:data:`SOLVE_BUILD_BUDGET_ENV`)."""
    raw = os.environ.get(SOLVE_BUILD_BUDGET_ENV)
    if raw is None:
        return SOLVE_BUILD_BUDGET
    try:
        value = int(raw)
    except ValueError:
        return SOLVE_BUILD_BUDGET
    return value if value > 0 else SOLVE_BUILD_BUDGET


def verify_timeout_s() -> float:
    """The effective verification-pass ceiling, resolved per call."""
    return _env_float(VERIFY_TIMEOUT_ENV, VERIFY_TIMEOUT_S)


# --------------------------------------------------------------------------
# refusals


class InvalidSolveRequest(ValidationError):
    """The request cannot be solved as written — a named refusal, nothing written.

    ``reason`` is one of :data:`SOLVE_REQUEST_REFUSALS`; ``detail`` carries the
    ``not_an_objective_kind`` sub-reason (:data:`NOT_AN_OBJECTIVE_REASONS`)
    and the offending id where there is one. Refused before any geometry is
    read, so a malformed request costs nothing and reports everything.
    """

    code = "invalid_solve_request"

    def __init__(
        self,
        reason: str,
        message: str,
        *,
        subject: str = "",
        sub_reason: str = "",
    ) -> None:
        super().__init__(message, kind="contract")
        self.reason = reason
        self.subject = subject
        self.sub_reason = sub_reason

    def to_json(self) -> dict[str, JSONValue]:
        out: dict[str, JSONValue] = {
            "status": "invalid_solve_request",
            "reason": self.reason,
            "message": self.message,
        }
        if self.subject:
            out["subject"] = self.subject
        if self.sub_reason:
            out["sub_reason"] = self.sub_reason
        return out


class SolveUnresolvable(ValidationError):
    """The solve could not be resolved against current artifacts.

    ``reason`` is one of :data:`SOLVE_RESOLUTION_REFUSALS`. Not a verdict and
    not a violation: an unresolved solve was never computed, and reporting
    "not computed" as "no pose found" would be as dishonest as reporting it as
    a success — the ``core/assembly.py:20-25`` rule, restated.
    """

    code = "unresolvable"

    def __init__(self, reason: str, detail: str, *, subject: str = "") -> None:
        super().__init__(detail, kind="evaluation")
        self.reason = reason
        self.detail = detail
        self.subject = subject

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "status": "unresolvable",
            "reason": self.reason,
            "subject": self.subject,
            "message": self.message,
        }


class SolveRunRefusal(ValidationError):
    """A ceiling fired, or the solver disagreed with the kernel — never a verdict.

    ``reason`` is one of :data:`SOLVE_RUNTIME_REFUSALS`, and ``payload``
    CARRIES the best iterate and its independently re-measured residuals where
    one exists: partial evidence, never a hang and never a silent pass
    (``core/motion.py:1489-1498``).
    """

    code = "solve_refused"

    def __init__(
        self,
        reason: str,
        message: str,
        *,
        payload: Mapping[str, JSONValue] | None = None,
    ) -> None:
        super().__init__(message, kind="contract")
        self.reason = reason
        self.payload: Mapping[str, JSONValue] = dict(payload or {})

    def to_json(self) -> dict[str, JSONValue]:
        out: dict[str, JSONValue] = {
            "status": "solve_refused",
            "reason": self.reason,
            "message": self.message,
        }
        out.update(self.payload)
        return out


# --------------------------------------------------------------------------
# the request


@dataclass(frozen=True)
class PointTarget:
    """Drive one anchor's reference point to a world point (``SOLVER.md`` §2A).

    The inverse of ``reach`` (``KINEMATICS.md:203-208``). It touches no
    constraint set, which is why this target form needed no amendment to the
    no-solver rule: it is arithmetic over declared joint parameters, and a
    solved assignment is a pose.
    """

    id: str
    anchor: str
    point_mm: tuple[float, float, float]
    tol_mm: float

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "form": "anchor_point",
            "id": self.id,
            "anchor": self.anchor,
            "point_mm": list(self.point_mm),
            "tol_mm": self.tol_mm,
        }


@dataclass(frozen=True)
class ConstraintTarget:
    """Drive joint motion until a declared 8C constraint measures satisfied.

    This is the target form the ``ASSEMBLY.md`` §1 amendment was spent on: as
    written before 2026-08-30 the rule said a constraint requiring motion to
    satisfy "is simply unsatisfied", so a solve against a constraint id was
    prohibited outright. It is legal now, scoped: the solver proposes an
    assignment and nothing applies it, and the constraint's own verdict is
    still produced only by measuring delivered geometry.
    """

    constraint_id: str

    def to_json(self) -> dict[str, JSONValue]:
        return {"form": "constraint", "constraint_id": self.constraint_id}


SolveTarget = PointTarget | ConstraintTarget


@dataclass(frozen=True)
class SolveStart:
    """One declared start, named so every result can say which produced it.

    ``zero: "as_built"`` (``KINEMATICS.md:110-114``) makes the authored
    configuration a genuinely good start, which is what makes a local method
    defensible — so ``as_built`` (the empty assignment) is the default. But
    the interesting failures are exactly where that is false, so starts are a
    LIST, every result names its own, and non-convergence names every start
    tried. There are no random restarts: an RNG would break the D1 determinism
    tier and would let a rerun quietly change the answer.
    """

    id: str = "as_built"
    values: Mapping[str, float] = dataclasses.field(default_factory=lambda: {})

    def to_json(self) -> dict[str, JSONValue]:
        return {"id": self.id, "values": {k: self.values[k] for k in sorted(self.values)}}


@dataclass(frozen=True)
class PoseSolveRequest:
    """Everything a pose solve is, stated once and echoed in the record."""

    targets: tuple[SolveTarget, ...]
    tol: float
    weighting: str
    regularization: str
    provenance: ConstraintProvenance
    free_joints: tuple[str, ...] | None = None
    starts: tuple[SolveStart, ...] = (SolveStart(),)
    weights: tuple[float, float] | None = None
    ceiling: int | None = None

    def to_json(self) -> dict[str, JSONValue]:
        out: dict[str, JSONValue] = {
            "space": "pose",
            "targets": [target.to_json() for target in self.targets],
            "tol": self.tol,
            "weighting": self.weighting,
            "regularization": self.regularization,
            "provenance": cast("JSONValue", self.provenance.to_json()),
            "free_joints": list(self.free_joints) if self.free_joints is not None else None,
            "starts": [start.to_json() for start in self.starts],
            "weights": (
                {"mm": self.weights[0], "deg": self.weights[1]}
                if self.weights is not None
                else None
            ),
            "ceiling": self.ceiling,
        }
        return out

    def validated(self) -> PoseSolveRequest:
        """The ``SOLVER.md`` §6.3 request-time refusals, all of them, up front."""
        from hephaestus.core.project_store.constraints import ConstraintError
        from hephaestus.geom.solve import DETERMINISM_FLOOR

        if not self.targets:
            raise InvalidSolveRequest(
                "no_free_variables",
                "a solve request declares at least one target; a solve with nothing "
                "to drive towards has no answer to report (SOLVER.md §2A)",
            )
        if self.weighting not in ("unit_scaled_v1", "declared"):
            raise InvalidSolveRequest(
                "undeclared_weighting",
                f"weighting {self.weighting!r} is not declared; a residual vector "
                'mixing mm and deg has no canonical norm, so "unit_scaled_v1" or '
                '"declared" is required and echoed (SOLVER.md §3.4, on the '
                "COMPARE.md:34-36 precedent)",
            )
        if self.weighting == "declared" and self.weights is None:
            raise InvalidSolveRequest(
                "undeclared_weighting",
                'weighting "declared" requires an explicit {"mm": w, "deg": w} pair '
                "(SOLVER.md §3.4)",
            )
        if self.regularization != "min_norm_from_start":
            raise InvalidSolveRequest(
                "undeclared_regularization",
                f"regularization {self.regularization!r} is not declared; "
                '"min_norm_from_start" is the only Stage 13 member and is still '
                "required, because the Jacobian is rank-deficient by construction "
                "and which null-space member is returned is a design decision "
                "(SOLVER.md §3.5)",
            )
        if self.tol < DETERMINISM_FLOOR:
            raise InvalidSolveRequest(
                "tolerance_below_determinism_floor",
                f"declared tolerance {self.tol!r} is tighter than the determinism "
                f"floor {DETERMINISM_FLOOR}: the number two processes in the pinned "
                "image are gated to agree to (ASSEMBLY.md:152-153). Nothing here has "
                "measured the kernel's accuracy against ground truth, so a tighter "
                "tolerance would be a claim nobody computed (SOLVER.md §6.3)",
            )
        try:
            self.provenance.validated("solve")
        except ConstraintError as exc:
            raise InvalidSolveRequest("missing_provenance", exc.message) from exc
        seen: set[str] = set()
        for target in self.targets:
            key = (
                target.constraint_id
                if isinstance(target, ConstraintTarget)
                else f"point:{target.id}"
            )
            if key in seen:
                raise InvalidSolveRequest(
                    "unknown_constraint",
                    f"target {key!r} is declared twice; a duplicated target would "
                    "weight one constraint twice without saying so",
                    subject=key,
                )
            seen.add(key)
            if isinstance(target, PointTarget) and target.tol_mm < DETERMINISM_FLOOR:
                raise InvalidSolveRequest(
                    "tolerance_below_determinism_floor",
                    f"target {target.id!r}: tol_mm {target.tol_mm!r} is tighter than "
                    f"the determinism floor {DETERMINISM_FLOOR}",
                    subject=target.id,
                )
        if self.free_joints is not None and not self.free_joints:
            raise InvalidSolveRequest(
                "no_free_variables",
                "the free joint set is empty; there is nothing to solve for",
            )
        return self


# --------------------------------------------------------------------------
# the verified half of the solve record


@dataclass(frozen=True)
class VerifiedComponent:
    """One re-measured component beside the bound it was tested against.

    ``SOLVER.md`` §7.4 and §8: every class-predicate value is recorded next to
    its declared bound, so a reader can see WHICH conjunct failed rather than
    inferring it from a number. ``solver`` is the solver's own figure for the
    same component, kept only for the §7.6 disagreement check and never the
    reported one.
    """

    key: str
    role: str
    unit: str
    measured: float
    bound: float
    within_bound: bool
    solver: float

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "key": self.key,
            "role": self.role,
            "unit": self.unit,
            "measured": self.measured,
            "bound": self.bound,
            "within_bound": self.within_bound,
            "solver": self.solver,
        }


@dataclass(frozen=True)
class VerifiedConstraint:
    """One constraint re-measured through the ordinary engine path.

    :attr:`satisfied` is what the verdict is read from — not :attr:`measured`
    and not :attr:`slack`. A ``coincident`` pair with a genuinely zero gap and
    same-facing normals makes the solver's number and the kernel's agree
    perfectly, so the §7.6 disagreement check passes; the only thing that
    catches it is reading the predicate the kernel already evaluated.
    """

    id: str
    kind: str
    measured: float
    unit: str
    slack: float
    satisfied: bool
    declared: tuple[tuple[str, float], ...]
    values: tuple[tuple[str, float], ...]
    components: tuple[VerifiedComponent, ...]

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "id": self.id,
            "kind": self.kind,
            "measured": self.measured,
            "unit": self.unit,
            "slack": self.slack,
            "satisfied": self.satisfied,
            "declared": [[name, value] for name, value in self.declared],
            "values": [[name, value] for name, value in self.values],
            "components": [component.to_json() for component in self.components],
        }


@dataclass(frozen=True)
class SolveRecord:
    """The solve record (``SOLVER.md`` §7.0): two blocks, each with its own tier.

    13A carries it inline in the ``solve_pose`` result and writes nothing; from
    13B on the same shape is also serialised as the proposal document. Stating
    it this way round is deliberate: making the blocks a property of the
    proposal document would make G13A's determinism clauses depend on a store
    13B ships, which is the forward reach ``KINEMATICS.md:25-29`` forbids.

    :attr:`solver_core` carries the extracted frames the iteration consumed —
    **inside** the block, not upstream of it — because the D1 byte-identity
    claim is conditional on them: frame extraction is a kernel call and is not
    claimed bit-stable, so a reader comparing two blocks can see whether the
    condition held instead of taking it on faith.
    """

    verdict: SolveVerdict
    space: str
    request: Mapping[str, JSONValue]
    solver_core: Mapping[str, JSONValue]
    verification: Mapping[str, JSONValue]
    assignments: tuple[Mapping[str, JSONValue], ...]
    constraint_generation: int
    joint_generation: int
    artifact_refs: Mapping[str, str]
    #: Transform space only (``SOLVER.md`` §2B): one entry per returned
    #: solution, each naming every free part's proposed transform. Empty in
    #: pose space, where the answer is an ``assignments`` entry instead - the
    #: two are the same fact in the two spaces' own coordinates and neither is
    #: derived from the other.
    placements: tuple[Mapping[str, JSONValue], ...] = ()
    #: Parameter space only (``SOLVER.md`` §2C): the requested constraint ids
    #: whose objective term is a **local model** rather than a global one —
    #: every ``distance`` term, whose witness pair switches discontinuously as
    #: surfaces slide (§3.2). Disclosed rather than absorbed: a solve that used
    #: one is reporting a descent over a function with a kink in it, and a
    #: reader is entitled to know which term that was.
    nonsmooth_terms: tuple[str, ...] = ()
    #: The stored proposal this record was serialised as (13B on). Empty in
    #: 13A, which writes nothing at all, and empty for a verdict that computed
    #: no placement to propose.
    proposal_ref: str = ""
    proposal_id: str = ""
    #: Where this run's per-iteration replay evidence was stored
    #: (``SOLVER.md`` §9). Surfaced beside the proposal ref so a reader does
    #: not have to open the document to find it; empty in 13A, which stores
    #: nothing, and on any path that computed no iterate.
    solver_trace_ref: str = ""
    detail: str = ""
    #: Set only on the ``unresolvable`` verdict, from
    #: :data:`SOLVE_RESOLUTION_REFUSALS`. A solve that could not be resolved was
    #: never computed, and "not computed" is not "no pose found" - the
    #: ``core/assembly.py:20-25`` rule, which is why ``unresolvable`` is both a
    #: verdict spelling (``SOLVER.md`` §6.1, verdict 6) and a resolution-time
    #: refusal name (§6.3): it is the one state that is both.
    reason: str = ""
    subject: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "verdict": self.verdict,
            "space": self.space,
            "request": dict(self.request),
            "solver_core": dict(self.solver_core),
            "verification": dict(self.verification),
            "assignments": [dict(item) for item in self.assignments],
            "placements": [dict(item) for item in self.placements],
            "nonsmooth_terms": list(self.nonsmooth_terms),
            "proposal_ref": self.proposal_ref,
            "proposal_id": self.proposal_id,
            "solver_trace_ref": self.solver_trace_ref,
            "constraint_generation": self.constraint_generation,
            "joint_generation": self.joint_generation,
            "artifact_refs": {k: self.artifact_refs[k] for k in sorted(self.artifact_refs)},
            "detail": self.detail,
            "reason": self.reason,
            "subject": self.subject,
        }

    def canonical(self) -> str:
        """Canonical JSON, the form two processes compare byte for byte (§9)."""
        return canonical_json(cast("JSONValue", self.to_json()))


# --------------------------------------------------------------------------
# extraction: frames once, then no kernel inside the iteration


Vec3 = tuple[float, float, float]

_WORLD_AXES: Final[tuple[Vec3, Vec3, Vec3]] = (
    (1.0, 0.0, 0.0),
    (0.0, 1.0, 0.0),
    (0.0, 0.0, 1.0),
)


def _least_aligned_axis(direction: Vec3) -> Vec3:
    """The world axis furthest from ``direction`` — a deterministic reference.

    Used once, at extraction, to build ``concentric``'s perpendicular frame in
    as-built coordinates (``SOLVER.md`` §3.3). Chosen by smallest ``|dot|``
    with the index as the tie-break, so the frame never depends on
    enumeration luck and two processes pick the same one.
    """
    best = 0
    for index in range(1, 3):
        if abs(_dot(_WORLD_AXES[index], direction)) < abs(_dot(_WORLD_AXES[best], direction)):
            best = index
    return _WORLD_AXES[best]


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


@dataclass(frozen=True)
class _Term:
    """One objective term's extracted frames, in as-built world mm."""

    source_id: str
    kind: str
    part_a: str
    part_b: str
    point_a: Vec3
    dir_a: Vec3
    u_a: Vec3
    v_a: Vec3
    point_b: Vec3
    dir_b: Vec3
    target: Vec3

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "id": self.source_id,
            "kind": self.kind,
            "part_a": self.part_a,
            "part_b": self.part_b,
            "point_a": list(self.point_a),
            "dir_a": list(self.dir_a),
            "u_a": list(self.u_a),
            "v_a": list(self.v_a),
            "point_b": list(self.point_b),
            "dir_b": list(self.dir_b),
            "target": list(self.target),
        }


def _apply(rows: Sequence[Sequence[float]], point: Vec3) -> Vec3:
    return (
        rows[0][0] * point[0] + rows[0][1] * point[1] + rows[0][2] * point[2] + rows[0][3],
        rows[1][0] * point[0] + rows[1][1] * point[1] + rows[1][2] * point[2] + rows[1][3],
        rows[2][0] * point[0] + rows[2][1] * point[1] + rows[2][2] * point[2] + rows[2][3],
    )


def _rot(rows: Sequence[Sequence[float]], direction: Vec3) -> Vec3:
    return (
        rows[0][0] * direction[0] + rows[0][1] * direction[1] + rows[0][2] * direction[2],
        rows[1][0] * direction[0] + rows[1][1] * direction[1] + rows[1][2] * direction[2],
        rows[2][0] * direction[0] + rows[2][1] * direction[1] + rows[2][2] * direction[2],
    )


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


_ZERO: Final[Vec3] = (0.0, 0.0, 0.0)


#: One term's six placed primitives, in a fixed order every model shares:
#: ``(point_a, dir_a, u_a, v_a, point_b, dir_b)``.
_Placed = tuple[Vec3, Vec3, Vec3, Vec3, Vec3, Vec3]


def _term_residuals(term: _Term, placed: _Placed) -> list[tuple[float, ...]]:
    """The §3.3 reformulated rows one term contributes, in :attr:`_Problem.specs` order.

    Shared by every solve space (mission rule 6). What differs between pose
    space and transform space is only *how* the primitives got where they are —
    an FK composition or a candidate rigid transform — and the residual is a
    function of the primitives alone. Writing it twice would let the two spaces
    disagree about what a ``coincident`` term measures, which is exactly the
    drift the ``constraints.py`` <-> ``assembly.py`` split exists to prevent.
    """
    from hephaestus.geom.solve import (
        residual_coincident_gap,
        residual_coincident_normals,
        residual_concentric_offset,
        residual_cross,
        residual_perpendicular,
        residual_point_target,
    )

    point_a, dir_a, u_a, v_a, point_b, dir_b = placed
    if term.kind == "coincident":
        return [
            tuple(residual_coincident_gap(point_a, dir_a, point_b)),
            tuple(residual_coincident_normals(dir_a, dir_b)),
        ]
    if term.kind == "concentric":
        return [
            tuple(residual_concentric_offset(point_a, u_a, v_a, point_b)),
            tuple(residual_cross(dir_a, dir_b)),
        ]
    if term.kind == "parallel":
        return [tuple(residual_cross(dir_a, dir_b))]
    if term.kind == "perpendicular":
        return [tuple(residual_perpendicular(dir_a, dir_b))]
    return [tuple(residual_point_target(point_a, term.target))]  # anchor_point


def _term_derivative(term: _Term, placed: _Placed, deltas: _Placed) -> list[float]:
    """One term's Jacobian entries for one variable, given the primitives' velocities.

    The twin of :func:`_term_residuals` and shared for the same reason: a
    Jacobian written once per space is a Jacobian that can disagree with itself
    between spaces, and G13B clause 19 holds this arithmetic against a central
    finite difference **within one declared tolerance of the solution** — the
    neighbourhood where a second copy would be least likely to be tested and
    most likely to be wrong.
    """
    from hephaestus.geom.solve import (
        d_coincident_gap,
        d_coincident_normals,
        d_concentric_offset,
        d_cross,
        d_perpendicular,
    )

    point_a, dir_a, u_a, v_a, point_b, dir_b = placed
    d_point_a, d_dir_a, d_u_a, d_v_a, d_point_b, d_dir_b = deltas
    if term.kind == "coincident":
        return [
            *d_coincident_gap(point_a, dir_a, point_b, d_point_a, d_dir_a, d_point_b),
            *d_coincident_normals(d_dir_a, d_dir_b),
        ]
    if term.kind == "concentric":
        return [
            *d_concentric_offset(point_a, u_a, v_a, point_b, d_point_a, d_u_a, d_v_a, d_point_b),
            *d_cross(dir_a, dir_b, d_dir_a, d_dir_b),
        ]
    if term.kind == "parallel":
        return list(d_cross(dir_a, dir_b, d_dir_a, d_dir_b))
    if term.kind == "perpendicular":
        return list(d_perpendicular(dir_a, dir_b, d_dir_a, d_dir_b))
    return list(d_point_a)  # anchor_point: the reference point's own velocity


class _PoseModel:
    """The pose-space residual model (``SOLVER.md`` §2A) over extracted frames.

    Implements :class:`hephaestus.geom.solve.ResidualModel`. Frames are
    extracted ONCE by :func:`_extract` and transported here in closed form, so
    **no kernel call occurs inside an iteration** — which is what makes the
    ``solver_core`` block's D1 tier claimable at all (``SOLVER.md`` §9).

    The Jacobian is analytic (NW4) and it is a Jacobian **of the
    reformulation**, never of the engine's ``measured``. Each free joint
    contributes one twist in the CURRENT configuration — an angular velocity
    about the joint's transported axis line for a revolute, a linear velocity
    along its transported direction for a prismatic — and the six component
    derivatives of :mod:`hephaestus.geom.solve` carry those twists into
    residual rows. A finite difference would have worked numerically and been
    a worse answer: it would probe outside the declared limit box at a
    boundary solution, and probing a configuration nobody declared is the
    dishonesty ``geom/kinematics.py:217-245`` refuses to commit.
    """

    def __init__(
        self,
        resolution: Any,
        terms: Sequence[_Term],
        specs: Sequence[Any],
        variables: Sequence[Any],
        parts: Sequence[str],
    ) -> None:
        self._resolution = resolution
        self._terms = tuple(terms)
        self._specs = tuple(specs)
        self._variables = tuple(variables)
        anchored = tuple(sorted(set(parts)))
        self._affects: dict[str, tuple[str, ...]] = {
            part: tuple(resolution.chain_joints([part])) for part in anchored
        }
        # Every chain joint's PARENT part comes along, because a joint's own
        # axis lives in its parent's current frame (``KINEMATICS.md`` §1: the
        # parent anchor's frame IS the joint frame), so the twist below cannot
        # be written without the parent's transform. The anchored parts alone
        # would leave a root out and the Jacobian would silently lose a column.
        needed = set(anchored)
        for joints in self._affects.values():
            for joint_id in joints:
                needed.add(resolution.frame(joint_id).parent)
        self._parts = tuple(sorted(needed))
        self._anchored = anchored

    @property
    def variables(self) -> tuple[Any, ...]:
        return self._variables

    @property
    def components(self) -> tuple[Any, ...]:
        return self._specs

    def assignment(self, x: Sequence[float]) -> dict[str, float]:
        """``x`` as the joint assignment a pose would carry (``KINEMATICS.md`` §3)."""
        return {variable.name: float(x[index]) for index, variable in enumerate(self._variables)}

    def _world(self, x: Sequence[float]) -> dict[str, Any]:
        return self._resolution.transforms_at(self.assignment(x), self._parts)

    def _placed(self, term: _Term, world: Mapping[str, Any]) -> _Placed:
        rows_a = world[term.part_a].rows
        rows_b = world[term.part_b].rows
        return (
            _apply(rows_a, term.point_a),
            _rot(rows_a, term.dir_a),
            _rot(rows_a, term.u_a),
            _rot(rows_a, term.v_a),
            _apply(rows_b, term.point_b),
            _rot(rows_b, term.dir_b),
        )

    def evaluate(self, x: Sequence[float]) -> tuple[tuple[float, ...], ...]:
        world = self._world(x)
        out: list[tuple[float, ...]] = []
        for term in self._terms:
            out.extend(_term_residuals(term, self._placed(term, world)))
        return tuple(out)

    def _velocity(
        self, joint_id: str, part: str, world: Mapping[str, Any], point: Vec3, direction: Vec3
    ) -> tuple[Vec3, Vec3]:
        """``(dp/dq, dd/dq)`` of a point and a direction rigidly attached to ``part``.

        Zero when ``joint_id`` is not on ``part``'s parent chain: a joint moves
        its own subtree and nothing else, which is the whole content of
        ``KINEMATICS.md`` §2's root-to-leaf composition.
        """
        if joint_id not in self._affects.get(part, ()):
            return _ZERO, _ZERO
        frame = self._resolution.frame(joint_id)
        parent_rows = world[frame.parent].rows
        axis = _unit(frame.direction)
        axis_world = _unit(_rot(parent_rows, axis))
        if frame.kind == "prismatic":
            return axis_world, _ZERO
        # revolute: a screw about the transported axis line, in radians per
        # DEGREE because that is the unit the declared parameter is in.
        point_world = _apply(parent_rows, frame.point)
        omega = tuple(value * (math.pi / 180.0) for value in axis_world)
        omega3: Vec3 = (omega[0], omega[1], omega[2])
        return _cross(omega3, _sub(point, point_world)), _cross(omega3, direction)

    def jacobian(self, x: Sequence[float]) -> tuple[tuple[float, ...], ...] | None:
        world = self._world(x)
        columns: list[list[float]] = []
        for variable in self._variables:
            column: list[float] = []
            for term in self._terms:
                placed = self._placed(term, world)
                point_a, dir_a, u_a, v_a, point_b, dir_b = placed
                d_point_a, d_dir_a = self._velocity(
                    variable.name, term.part_a, world, point_a, dir_a
                )
                _pa, d_u_a = self._velocity(variable.name, term.part_a, world, point_a, u_a)
                _pb, d_v_a = self._velocity(variable.name, term.part_a, world, point_a, v_a)
                d_point_b, d_dir_b = self._velocity(
                    variable.name, term.part_b, world, point_b, dir_b
                )
                column.extend(
                    _term_derivative(
                        term, placed, (d_point_a, d_dir_a, d_u_a, d_v_a, d_point_b, d_dir_b)
                    )
                )
            columns.append(column)
        rows = len(columns[0]) if columns else 0
        return tuple(tuple(column[i] for column in columns) for i in range(rows))


def _unit(direction: Sequence[float]) -> Vec3:
    length = math.sqrt(sum(value * value for value in direction))
    if length <= 0.0:
        return _ZERO
    return (direction[0] / length, direction[1] / length, direction[2] / length)


# --------------------------------------------------------------------------
# extraction: which frames the targets name, resolved ONCE


@dataclass(frozen=True)
class _Problem:
    """Everything the iteration needs, extracted before it starts."""

    terms: tuple[_Term, ...]
    specs: tuple[Any, ...]
    variables: tuple[Any, ...]
    parts: tuple[str, ...]
    characteristic_radius_mm: float
    artifact_refs: Mapping[str, str]
    entries: Mapping[str, ConstraintEntry]
    collateral: tuple[str, ...]


def _scalar_kind(kind: str) -> bool:
    """Whether this joint kind has exactly one scalar parameter a pose can bind.

    ``PoseEntry.joints`` is ``Mapping[str, float]``, so the declared pose
    surface already speaks only scalars — and ``SOLVER.md`` §2A's output is
    "precisely the shape a named pose already has". A ``cylindrical`` joint's
    ``(deg, mm)`` pair has no pose spelling to be the answer of, and a
    ``fixed`` joint has no parameter at all.
    """
    return kind in ("revolute", "prismatic")


def _free_variables(resolution: Any, joint_state: Any, request: PoseSolveRequest) -> list[Any]:
    from hephaestus.geom.solve import SolveVariable

    declared = joint_state.by_id
    resolved = {outcome.id for outcome in resolution.joint_outcomes if outcome.state == "resolved"}
    if request.free_joints is None:
        names = [
            entry.id
            for entry in joint_state.active
            if entry.id in resolved
            and _scalar_kind(entry.kind)
            and resolution.coupled_driver(entry.id) is None
        ]
    else:
        names = list(request.free_joints)
    variables: list[Any] = []
    for name in names:
        entry = declared.get(name)
        if entry is None or entry.withdrawn:
            raise InvalidSolveRequest(
                "unknown_joint",
                f"joint {name!r} is not an active declared joint "
                f"(declared: {', '.join(sorted(declared)) or 'none'})",
                subject=name,
            )
        if resolution.coupled_driver(name) is not None:
            driver = resolution.coupled_driver(name)
            raise InvalidSolveRequest(
                "unknown_joint",
                f"joint {name!r} is a coupled child (coupling {driver.id!r}), so it is a "
                "DEPENDENT parameter: KINEMATICS.md §5 says a pose assigns only free "
                "ones, and a solved assignment is a pose. Solve for its driver "
                f"{driver.parent!r} instead",
                subject=name,
            )
        if not _scalar_kind(entry.kind):
            raise InvalidSolveRequest(
                "unknown_joint",
                f"joint {name!r} is {entry.kind!r}, which has no single scalar "
                "parameter a pose can bind (PoseEntry.joints is scalar-valued), so "
                "there is no free variable here to solve for",
                subject=name,
            )
        if name not in resolved:
            failure = resolution.joint_failure(name)
            raise SolveUnresolvable(
                "unresolvable_pose",
                f"joint {name!r} is unresolvable ({failure[0]}): {failure[1]}"
                if failure
                else f"joint {name!r} did not resolve",
                subject=name,
            )
        frame = resolution.frame(name)
        limits = frame.limits
        variables.append(
            SolveVariable(
                name=name,
                unit="deg" if entry.kind == "revolute" else "mm",
                lower=None if limits is None else limits.min,
                upper=None if limits is None else limits.max,
            )
        )
    if not variables:
        raise InvalidSolveRequest(
            "no_free_variables",
            "no free joint parameter is available to solve for: every declared joint "
            "is withdrawn, unresolvable, coupled, or has no scalar parameter",
        )
    return variables


def _locate(resolver: AnchorResolver, text: str, *, field: str) -> tuple[str, Any, str]:
    """``(part, shape, artifact_ref)`` for one anchor, or a named refusal."""
    anchor = parse_anchor(text, field=field)
    try:
        geometry, resolved = resolver.locate(anchor.part, anchor.selector)
        shape = geometry.shape_for(resolved)
    except UnresolvableAnchorError as exc:
        raise SolveUnresolvable(exc.reason, f"anchor {text!r}: {exc.detail}", subject=text) from exc
    return anchor.part, shape, geometry.artifact_ref


def component_specs(entry: ConstraintEntry) -> list[Any]:
    """One constraint's objective components, with the bounds it declared.

    ``SOLVER.md`` §3.1's table, in one place because all three solve spaces
    read it (mission rule 6). Every bound is taken from the entry's own
    ``values`` and never assumed — a constraint that overrode ``normal_eps_deg``
    is solved against the number it declared, exactly as
    ``ConstraintResidual.declared`` echoes bounds
    (``geom/constraints.py:318-320``).

    The last two kinds are parameter space's alone (§3.2): ``fit`` carries no
    gradient under a rigid transform and ``distance``'s witness pair switches
    discontinuously as surfaces slide, so both are refused as objective terms
    in 2B and admitted in 2C, where every derivative is a finite difference
    anyway and a ``distance`` term is disclosed in ``nonsmooth_terms``.
    """
    from hephaestus.geom.constraints import (
        COINCIDENT_NORMAL_EPS_DEG,
        CONCENTRIC_AXIS_EPS_DEG,
    )
    from hephaestus.geom.solve import ComponentSpec

    kind = entry.kind
    declared = dict(entry.values)
    if kind == "coincident":
        return [
            ComponentSpec(
                key=f"{entry.id}:gap",
                source_id=entry.id,
                kind=kind,
                role="primary",
                unit="mm",
                dim=1,
                bound=declared["tol_mm"],
                identity="abs",
            ),
            ComponentSpec(
                key=f"{entry.id}:normals",
                source_id=entry.id,
                kind=kind,
                role="class_predicate",
                unit="deg",
                dim=3,
                bound=declared.get("normal_eps_deg", COINCIDENT_NORMAL_EPS_DEG),
                identity="asin_norm_half2",
            ),
        ]
    if kind == "concentric":
        return [
            ComponentSpec(
                key=f"{entry.id}:offset",
                source_id=entry.id,
                kind=kind,
                role="primary",
                unit="mm",
                dim=2,
                bound=declared["tol_mm"],
                identity="norm",
            ),
            ComponentSpec(
                key=f"{entry.id}:axes",
                source_id=entry.id,
                kind=kind,
                role="class_predicate",
                unit="deg",
                dim=3,
                bound=declared.get("axis_eps_deg", CONCENTRIC_AXIS_EPS_DEG),
                identity="asin_norm",
            ),
        ]
    if kind == "parallel":
        return [
            ComponentSpec(
                key=f"{entry.id}:angle",
                source_id=entry.id,
                kind=kind,
                role="primary",
                unit="deg",
                dim=3,
                bound=declared["tol_deg"],
                identity="asin_norm",
            )
        ]
    if kind == "perpendicular":
        return [
            ComponentSpec(
                key=f"{entry.id}:square",
                source_id=entry.id,
                kind=kind,
                role="primary",
                unit="deg",
                dim=1,
                bound=declared["tol_deg"],
                identity="asin_abs",
            )
        ]
    if kind == "distance":
        return [
            ComponentSpec(
                key=f"{entry.id}:deviation",
                source_id=entry.id,
                kind=kind,
                role="primary",
                unit="mm",
                dim=1,
                bound=declared["tol_mm"],
                identity="abs",
            )
        ]
    # ``fit``: the bound is a WINDOW, so the component's bound is zero and the
    # residual is the signed excess outside it (``geom.solve.residual_window``).
    # ``|excess| <= 0`` is exactly ``min_mm <= measured <= max_mm``, which is the
    # kernel's own ``satisfied`` for this kind — the window is not flattened into
    # a one-sided tolerance anywhere.
    return [
        ComponentSpec(
            key=f"{entry.id}:window",
            source_id=entry.id,
            kind=kind,
            role="primary",
            unit="mm",
            dim=1,
            bound=0.0,
            identity="abs",
        )
    ]


def _frames_of(resolver: AnchorResolver, entry: ConstraintEntry) -> _Term:
    """One analytic constraint's extracted frames, in the resolved world mm.

    Split out of :func:`_extract` because parameter space needs it too and for
    a different rhythm: 2B extracts once and transports the records in closed
    form, while 2C re-extracts at every iterate because the geometry itself
    changed. Two copies of this would be two definitions of what a
    ``coincident`` term measures.
    """
    from hephaestus.geom import ConstraintShapeError, cylinder_of, direction_of, plane_of
    from hephaestus.geom.solve import orthonormal_complement

    kind = entry.kind
    try:
        part_a, shape_a, _ref_a = _locate(resolver, entry.a, field="a")
        part_b, shape_b, _ref_b = _locate(resolver, entry.b, field="b")
        if kind == "coincident":
            plane_a = plane_of(shape_a, kind=kind, side="a")
            plane_b = plane_of(shape_b, kind=kind, side="b")
            point_a, dir_a = plane_a.center, plane_a.normal
            point_b, dir_b = plane_b.center, plane_b.normal
        elif kind == "concentric":
            cyl_a = cylinder_of(shape_a, kind=kind, side="a")
            cyl_b = cylinder_of(shape_b, kind=kind, side="b")
            point_a, dir_a = cyl_a.axis_point, cyl_a.axis
            point_b, dir_b = cyl_b.axis_point, cyl_b.axis
        else:  # parallel / perpendicular
            dir_a, _what_a = direction_of(shape_a, kind=kind, side="a")
            dir_b, _what_b = direction_of(shape_b, kind=kind, side="b")
            point_a = point_b = (0.0, 0.0, 0.0)
    except ConstraintShapeError as exc:
        raise SolveUnresolvable(
            "shape_refused",
            f"constraint {entry.id}: {exc.reason} — {exc.message}",
            subject=entry.id,
        ) from exc
    u_a, v_a = orthonormal_complement(dir_a, _least_aligned_axis(dir_a))
    return _Term(
        source_id=entry.id,
        kind=kind,
        part_a=part_a,
        part_b=part_b,
        point_a=point_a,
        dir_a=dir_a,
        u_a=u_a,
        v_a=v_a,
        point_b=point_b,
        dir_b=dir_b,
        target=(0.0, 0.0, 0.0),
    )


def _extract(
    resolver: AnchorResolver,
    entries: Mapping[str, ConstraintEntry],
    targets: Sequence[SolveTarget],
    variables: Sequence[Any],
    moved_of: Callable[[Sequence[str]], set[str]],
    all_entries: Sequence[ConstraintEntry],
) -> _Problem:
    """Resolve every target's anchors ONCE and reduce them to numbers.

    ``SOLVER.md`` §4.2 step 1. After this function returns, the iteration is
    plain-float arithmetic over the records below: no shape, no kernel, no
    store. That is the precondition of the D1 determinism tier, and it is why
    the extracted frames are recorded INSIDE the ``solver_core`` block rather
    than upstream of it — the claim is conditional on them, so a reader must
    be able to check the condition (``SOLVER.md`` §9).

    ``moved_of`` is the one thing the two solve spaces disagree about: which of
    the anchored parts this request can actually move — the ones on a free
    joint's chain in pose space, the declared free set in transform space. It
    is a parameter rather than a branch so that the extraction itself, and with
    it the collateral set of §7.3, is one implementation and not two.
    """
    from hephaestus.core.motion import anchor_center
    from hephaestus.geom.solve import ComponentSpec

    terms: list[_Term] = []
    specs: list[Any] = []
    parts: list[str] = []
    for target in targets:
        if isinstance(target, PointTarget):
            part, shape, _ref = _locate(resolver, target.anchor, field="anchor")
            centre = anchor_center(shape)
            terms.append(
                _Term(
                    source_id=target.id,
                    kind="anchor_point",
                    part_a=part,
                    part_b=part,
                    point_a=centre,
                    dir_a=(0.0, 0.0, 1.0),
                    u_a=(1.0, 0.0, 0.0),
                    v_a=(0.0, 1.0, 0.0),
                    point_b=centre,
                    dir_b=(0.0, 0.0, 1.0),
                    target=target.point_mm,
                )
            )
            specs.append(
                ComponentSpec(
                    key=f"{target.id}:point",
                    source_id=target.id,
                    kind="anchor_point",
                    role="target",
                    unit="mm",
                    dim=3,
                    bound=target.tol_mm,
                    identity="norm",
                )
            )
            parts.append(part)
            continue
        entry = entries[target.constraint_id]
        term = _frames_of(resolver, entry)
        terms.append(term)
        parts.extend((term.part_a, term.part_b))
        specs.extend(component_specs(entry))
    unique_parts = tuple(sorted(set(parts)))
    moved = moved_of(unique_parts)
    radius = _characteristic_radius(resolver, moved or set(unique_parts))
    # §7.3: the kinds excluded from the objective are still EVALUATED at the
    # solution. A proposal that satisfies four mates and drives two parts into
    # each other is reported with `no_interference` violated, which is the
    # honest answer and the reason those kinds are not silently dropped.
    named = {term.source_id for term in terms}
    collateral = tuple(
        sorted(
            entry.id
            for entry in all_entries
            if entry.id not in named and set(entry.parts) & moved and not entry.poses
        )
    )
    return _Problem(
        terms=tuple(terms),
        specs=tuple(specs),
        variables=tuple(variables),
        parts=unique_parts,
        characteristic_radius_mm=radius,
        artifact_refs=dict(resolver.artifact_refs()),
        entries=dict(entries),
        collateral=collateral,
    )


def _characteristic_radius(resolver: AnchorResolver, parts: set[str]) -> float:
    """``unit_scaled_v1``'s radius: bounding-box centre to corner, over free parts.

    ``SOLVER.md`` §3.4 — so one degree of tilt costs what that tilt moves at
    the part's extremity, which is the only reading of "a degree is worth a
    millimetre" that is about the geometry rather than about taste. The
    computed number is recorded in the result, because a weight nobody can see
    is a silent normalization.
    """
    worst = 0.0
    for part in sorted(parts):
        try:
            geometry, resolved = resolver.locate(part, WHOLE_PART_SELECTOR)
            shape = geometry.shape_for(resolved)
        except UnresolvableAnchorError:  # pragma: no cover - the anchors already resolved
            continue
        box = shape.bounding_box()
        half = (
            (float(box.max.X) - float(box.min.X)) / 2.0,
            (float(box.max.Y) - float(box.min.Y)) / 2.0,
            (float(box.max.Z) - float(box.min.Z)) / 2.0,
        )
        worst = max(worst, math.sqrt(half[0] ** 2 + half[1] ** 2 + half[2] ** 2))
    return worst if worst > 0.0 else 1.0


# --------------------------------------------------------------------------
# independent verification (``SOLVER.md`` §7)

#: Fault-injection hook for the ``SOLVER.md`` §7.6 disagreement check
#: (G13A clause 10, G13B clause 31). When set to a float, the solver's own
#: recorded component numbers are perturbed by that amount **after** the
#: iteration and before the comparison, so a gate can prove that a solver
#: whose model has drifted from the kernel's is refused rather than reported
#: with a caveat. It changes no iterate and produces no verdict; there is no
#: production path that sets it.
SOLVER_FAULT_ENV: Final[str] = "HEPHAESTUS_SOLVE_FAULT"


def _solver_fault() -> float:
    raw = os.environ.get(SOLVER_FAULT_ENV)
    if raw is None:
        return 0.0
    try:
        return float(raw)
    except ValueError:  # pragma: no cover - a malformed override is simply off
        return 0.0


def _verify_child(conn: Any, spec: Mapping[str, Any]) -> None:  # pragma: no cover
    """Re-measure one assignment through the ORDINARY engine path, elsewhere.

    Runs in a fresh spawned process whose only inputs are the serialised solve
    record and the project store. It imports :mod:`hephaestus.core.assembly`,
    :mod:`hephaestus.core.motion` and :mod:`hephaestus.geom.constraints` — and
    **not** :mod:`hephaestus.geom.solve`, which it asserts before sending
    anything. A solver bug therefore cannot reach the number that is reported.
    """
    import sys

    try:
        from hephaestus.core.assembly import AnchorResolver as _Resolver
        from hephaestus.core.motion import anchor_center
        from hephaestus.core.project_store.constraints import ConstraintSet as _Constraints
        from hephaestus.core.project_store.layout import load_project, open_store
        from hephaestus.core.project_store.publication import Publisher as _Publisher
        from hephaestus.core.project_store.publication import build_bundle
        from hephaestus.geom import evaluate_residual, transform_point, transformed_shape
        from hephaestus.geom.kinematics import IDENTITY_TRANSFORM, RigidTransform

        root = Path(cast("str", spec["root"]))
        scratch = Path(cast("str", spec["scratch"]))
        layout = load_project(root)
        store = open_store(layout)
        publisher = _Publisher(layout, store)
        resolver = _Resolver(layout, store, publisher, scratch)
        constraint_state = _Constraints(layout, store).state()
        # Every part any row will place, gathered BEFORE the walk: a constraint
        # anchored on a part the solve never moves still has to be measured at
        # its own (identity) placement, and reaching for a transform that was
        # never asked for is how a verification pass ends up quietly skipping a
        # row it was supposed to report.
        needed = set(cast("Sequence[str]", spec["parts"]))
        #: Parameter space only: the CURRENT refs (for the staleness
        #: comparison) and the PREVIEW builds this pass actually measured. The
        #: two are deliberately different maps — a 2C verification measures
        #: geometry no published artifact carries, and reporting the preview
        #: refs as the bound ones would make every 2C proposal look stale.
        current_refs: dict[str, str] = {}
        verified_builds: list[dict[str, Any]] = []
        for constraint_id in cast("Sequence[str]", spec["constraints"]):
            needed.update(constraint_state.by_id[constraint_id].parts)
        for target in cast("Sequence[Mapping[str, Any]]", spec["points"]):
            needed.add(cast("str", target["anchor"]).partition(":")[0])
        if spec.get("space") == "transform":
            # ``SOLVER.md`` §2B: every part not in the declared free set is
            # GROUND, which in transform space means exactly where its script
            # put it - the identity. Forward kinematics is deliberately not
            # consulted: a free part may not ride a joint
            # (``free_part_is_jointed``), so composing an FK transform with a
            # proposed one would make the returned number attributable to
            # neither, which is the same reason §2B refuses a pose-bound
            # constraint here.
            proposed = cast("Mapping[str, Any]", spec["transforms"])
            world = {
                part: (
                    RigidTransform(
                        rows=cast(
                            "Any",
                            tuple(
                                tuple(float(value) for value in row)
                                for row in cast("Sequence[Sequence[float]]", proposed[part])
                            ),
                        )
                    )
                    if part in proposed
                    else IDENTITY_TRANSFORM
                )
                for part in sorted(needed)
            }
        elif spec.get("space") == "parameters":
            # ``SOLVER.md`` §7.2, verbatim: "in 2C it is literally a preview
            # build followed by the ordinary evaluation". This process rebuilds
            # every measured part at the proposed parameter values with its OWN
            # executor — the secure probed backend, never one the caller chose —
            # and then measures the result through the same evaluator every
            # other space's verification uses. Nothing here imports the solver,
            # so a solver bug cannot reach the number reported; and every build
            # it issues is a preview, so a verification pass cannot make a
            # candidate current either.
            from hephaestus.core.executor.runner import BuildRequest, run_build
            from hephaestus.core.executor.sandbox.probe import cached_probe, secure_backend

            backend = secure_backend(layout.store_root)
            cached_probe(layout.store_root, backend)
            part_overrides = cast("Mapping[str, Mapping[str, float]]", spec["part_overrides"])
            project_overrides = cast("Mapping[str, float]", spec["project_overrides"])
            merged_project: dict[str, Any] = dict(layout.manifest.params)
            merged_project.update(dict(project_overrides))
            rebuilt: dict[str, Any] = {}
            for part in sorted(needed):
                # The CURRENT ref first, and BEFORE any build: it is what
                # ``stale_proposal_inputs`` compares against, so it has to be
                # the published design's ref rather than the preview one this
                # pass is about to make.
                current = publisher.current_result(part)
                current_refs[part] = "" if current is None else (current.artifact_ref or "")
                publisher.sync_import_state()
                frozen = publisher.freeze_inputs(part)
                out_dir = layout.store_root / "builds" / f"verify-{part}-{uuid.uuid4().hex[:12]}"
                try:
                    built = run_build(
                        BuildRequest(
                            part=part,
                            script=frozen.script,
                            globals_source=frozen.globals_source,
                            part_overrides=dict(part_overrides.get(part, {})),
                            project_overrides=merged_project,
                            origin="local",
                            imports=dict(frozen.imports),
                            import_errors=dict(frozen.import_errors),
                        ),
                        backend=backend,
                        out_dir=out_dir,
                        baseline=publisher.baseline_for(part),
                    )
                    outcome = publisher.publish_build(
                        built, op_id=f"heph-verify-{uuid.uuid4().hex}", preview=True
                    )
                finally:
                    shutil.rmtree(out_dir, ignore_errors=True)
                if outcome.result.status != "ok" or outcome.result.artifact_ref is None:
                    failure = outcome.result.error
                    why = "no error record" if failure is None else failure.message
                    raise RuntimeError(
                        f"part {part!r} does not build at the proposed parameters ({why})"
                    )
                verified_builds.append(
                    {
                        "part": part,
                        "params": dict(part_overrides.get(part, {})),
                        "current": outcome.result.current,
                        "artifact_ref": outcome.result.artifact_ref,
                    }
                )
                rebuilt[part] = PublishedBuild(
                    result=outcome.result,
                    bundle=cast(
                        "Mapping[str, JSONValue]",
                        build_bundle(
                            built, outcome.result, publisher.projections.state().audit_revision
                        ),
                    ),
                )
            resolver = _Resolver(layout, store, publisher, scratch, builds=rebuilt)
            # Parameter space moves no part: the geometry itself changed, and
            # every placement is the identity. Composing a transform here would
            # be measuring something no build produced.
            world = {part: IDENTITY_TRANSFORM for part in sorted(needed)}
        else:
            from hephaestus.core.motion import motion_resolution

            values = cast("Mapping[str, float]", spec["values"])
            world = motion_resolution(layout, store, resolver).transforms_at(values, sorted(needed))
        rows: list[dict[str, Any]] = []
        for constraint_id in cast("Sequence[str]", spec["constraints"]):
            entry = constraint_state.by_id[constraint_id]
            placed: list[Any] = []
            for text in (entry.a, entry.b):
                part, _sep, selector = text.partition(":")
                geometry, resolved = resolver.locate(part, selector or "part")
                shape = geometry.shape_for(resolved)
                # A PLACED COPY (``geom/kinematics.py:763-782``): the loaded
                # artifact is never mutated, so the same bytes measure the same
                # way at any assignment, and nothing this process touches
                # outlives it.
                placed.append(transformed_shape(shape, world[part]))
            residual = evaluate_residual(entry.kind, placed[0], placed[1], dict(entry.values))
            rows.append(
                {
                    "id": entry.id,
                    "kind": entry.kind,
                    "measured": residual.measured,
                    "unit": residual.unit,
                    "slack": residual.slack,
                    "satisfied": residual.satisfied,
                    "declared": [[name, value] for name, value in residual.declared],
                    "values": [[name, value] for name, value in residual.values],
                }
            )
        points: list[dict[str, Any]] = []
        for target in cast("Sequence[Mapping[str, Any]]", spec["points"]):
            text = cast("str", target["anchor"])
            part, _sep, selector = text.partition(":")
            geometry, resolved = resolver.locate(part, selector or "part")
            centre = anchor_center(geometry.shape_for(resolved))
            moved = transform_point(world[part], centre)
            goal = cast("Sequence[float]", target["point_mm"])
            error = math.sqrt(sum((moved[i] - goal[i]) ** 2 for i in range(3)))
            points.append({"id": target["id"], "error_mm": error, "point_mm": list(moved)})
        closure_clean = "hephaestus.geom.solve" not in sys.modules
        conn.send(
            (
                "done",
                {
                    "constraints": rows,
                    "points": points,
                    "artifact_refs": (
                        current_refs if current_refs else dict(resolver.artifact_refs())
                    ),
                    "preview_builds": verified_builds,
                    "closure_clean": closure_clean,
                },
            )
        )
    except Exception as exc:
        reason = "invalid_constraint"
        if type(exc).__name__ == "BoundPoseError":
            # A solved value outside a declared limit, or a chain joint that
            # will not resolve. 8C's own ``unresolvable_pose`` already means
            # exactly that ("out of a joint's declared limits", "riding an
            # unresolvable joint"), so it is reused rather than re-spelled.
            reason = "unresolvable_pose"
        conn.send(("refusal", (reason, f"{type(exc).__name__}: {exc}")))
    finally:
        conn.close()


def _verify(spec: Mapping[str, Any], *, timeout_s: float) -> Mapping[str, Any]:
    """Run one verification pass under its own wall-clock ceiling (``SOLVER.md`` §10).

    The ``core/motion.py`` bounded-sweep loop, with one terminal message
    instead of a stream: the pass either answers or is killed, and a kill is a
    named refusal (``solver_timeout``), never a hang and never a verdict.
    """
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=_verify_child, args=(child, dict(spec)))
    proc.start()
    child.close()
    outcome: tuple[str, Any] | None = None
    deadline = time.monotonic() + timeout_s
    try:
        while outcome is None and time.monotonic() < deadline:
            try:
                if parent.poll(0.05):
                    outcome = cast("tuple[str, Any]", parent.recv())
                elif not proc.is_alive():
                    break
            except EOFError:
                proc.join(5.0)
                break
    finally:
        if proc.is_alive():
            proc.kill()
        proc.join()
        parent.close()
    if outcome is None:
        raise SolveRunRefusal(
            "solver_timeout",
            f"the independent verification pass did not finish within {timeout_s:g}s "
            f"(SOLVER.md §7, §10; ceiling via {VERIFY_TIMEOUT_ENV}) or its process "
            f"died (exit code {proc.exitcode}); nothing was measured, so nothing is "
            "reported and no verdict is emitted",
        )
    kind, payload = outcome
    if kind == "refusal":
        reason, detail = cast("tuple[str, str]", payload)
        raise SolveUnresolvable(
            reason,
            f"the verification pass could not re-measure this assignment: {detail}",
        )
    return cast("Mapping[str, Any]", payload)


# --------------------------------------------------------------------------
# the driver


_COMPONENT_SOURCE: Final[Mapping[str, str]] = {
    "gap": "measured",
    "normals": "normal_deviation_deg",
    "offset": "measured",
    "axes": "axis_angle_deg",
    "angle": "measured",
    "square": "measured",
    # Parameter space's two extra components (``SOLVER.md`` §2C). Both are
    # compared against a number the kernel's own row already carries, so the
    # §7.6 disagreement check has the same teeth here as anywhere else:
    # ``distance`` against ``deviation_mm``, and ``fit`` against the excess
    # outside its window, which is ``max(0, -slack)`` of the engine's own
    # ``slack = min(measured - min_mm, max_mm - measured)``.
    "deviation": "deviation_mm",
    "window": "@window",
}


def _kernel_number(spec: Any, row: Mapping[str, Any]) -> float:
    """The kernel's own figure for one reformulated component (``SOLVER.md`` §7.6).

    The comparison is per COMPONENT, over the §3.3 identities: the primary
    components read ``measured``, the class predicates read their own entry of
    ``values``. Comparing whole constraints instead would let a reformulation
    bug in the class predicate hide behind an agreeing primary, which is the
    one place §7.6 alone cannot catch anything (§7.4).
    """
    field = _COMPONENT_SOURCE[spec.key.rsplit(":", 1)[1]]
    if field == "measured":
        return float(cast("float", row["measured"]))
    if field == "@window":
        # A ``fit``'s bound is a window, so its "distance from satisfied" is
        # not one of the row's named values but the row's own slack read the
        # other way: zero inside the window, the overshoot outside it.
        return max(0.0, -float(cast("float", row["slack"])))
    values = {name: value for name, value in cast("Sequence[Any]", row["values"])}
    return float(values[field])


def _verified_rows(
    problem: _Problem,
    iterate: Any,
    measured: Mapping[str, Any],
) -> tuple[tuple[VerifiedConstraint, ...], tuple[Mapping[str, JSONValue], ...], float]:
    """Zip the kernel's rows against the solver's, and find the worst disagreement."""
    fault = _solver_fault()
    by_key = {value.key: value for value in iterate.values}
    by_id = {cast("str", row["id"]): row for row in cast("Sequence[Any]", measured["constraints"])}
    worst = 0.0
    rows: list[VerifiedConstraint] = []
    for source_id in dict.fromkeys(spec.source_id for spec in problem.specs):
        row = by_id.get(source_id)
        if row is None:
            continue
        components: list[VerifiedComponent] = []
        for spec in problem.specs:
            if spec.source_id != source_id:
                continue
            solver_value = by_key[spec.key].measured + fault
            kernel_value = _kernel_number(spec, row)
            worst = max(worst, abs(solver_value - kernel_value))
            components.append(
                VerifiedComponent(
                    key=spec.key,
                    role=spec.role,
                    unit=spec.unit,
                    measured=kernel_value,
                    bound=spec.bound,
                    within_bound=kernel_value <= spec.bound,
                    solver=solver_value,
                )
            )
        rows.append(
            VerifiedConstraint(
                id=source_id,
                kind=cast("str", row["kind"]),
                measured=float(cast("float", row["measured"])),
                unit=cast("str", row["unit"]),
                slack=float(cast("float", row["slack"])),
                satisfied=bool(row["satisfied"]),
                declared=tuple(
                    (str(name), float(value))
                    for name, value in cast("Sequence[Any]", row["declared"])
                ),
                values=tuple(
                    (str(name), float(value))
                    for name, value in cast("Sequence[Any]", row["values"])
                ),
                components=tuple(components),
            )
        )
    points: list[Mapping[str, JSONValue]] = []
    for entry in cast("Sequence[Mapping[str, Any]]", measured["points"]):
        target_id = cast("str", entry["id"])
        spec = next(item for item in problem.specs if item.source_id == target_id)
        solver_value = by_key[spec.key].measured + fault
        kernel_value = float(cast("float", entry["error_mm"]))
        worst = max(worst, abs(solver_value - kernel_value))
        points.append(
            {
                "id": target_id,
                "error_mm": kernel_value,
                "bound": spec.bound,
                "within_bound": kernel_value <= spec.bound,
                "solver": solver_value,
                "point_mm": cast("JSONValue", list(cast("Sequence[float]", entry["point_mm"]))),
            }
        )
    return tuple(rows), tuple(points), worst


def _collateral_rows(measured: Mapping[str, Any], named: set[str]) -> list[JSONValue]:
    return [
        cast("JSONValue", dict(row))
        for row in cast("Sequence[Mapping[str, Any]]", measured["constraints"])
        if cast("str", row["id"]) not in named
    ]


@dataclass(frozen=True)
class _Verified:
    """One iterate plus what an independent process measured about it."""

    iterate: Any
    constraints: tuple[VerifiedConstraint, ...]
    points: tuple[Mapping[str, JSONValue], ...]
    collateral: tuple[JSONValue, ...]
    disagreement: float
    closure_clean: bool
    #: Parameter space only: the preview builds THIS verification pass issued,
    #: each with the ``current`` flag publication returned for it. Empty in the
    #: other two spaces, whose verification builds nothing. It is recorded
    #: because §2C's whole safety argument is that a candidate is a preview —
    #: an argument a reader should be able to check on the verifying side too,
    #: not only on the solver's.
    preview_builds: tuple[JSONValue, ...] = ()

    @property
    def all_satisfied(self) -> bool:
        """Conjunct (i): every objective constraint re-measures ``satisfied is True``.

        Read from the kernel's own ``satisfied``, never derived from a
        residual: ``SOLVER.md`` §6.1 is explicit that (i) is not redundant
        with (ii), because a zero-gap same-facing ``coincident`` pair passes
        (ii) with room to spare and fails (i).
        """
        return all(row.satisfied for row in self.constraints) and all(
            bool(point["within_bound"]) for point in self.points
        )

    def unsatisfied(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                [row.id for row in self.constraints if not row.satisfied]
                + [str(point["id"]) for point in self.points if not point["within_bound"]]
            )
        )

    def to_json(self) -> dict[str, JSONValue]:
        out: dict[str, JSONValue] = {
            "constraints": [row.to_json() for row in self.constraints],
            "points": [dict(point) for point in self.points],
            "collateral": list(self.collateral),
            "import_closure_excludes_geom_solve": self.closure_clean,
            "worst_disagreement": self.disagreement,
            # ``SOLVER.md`` §9: **every** verification block is D2, in every
            # space including 2A, because it is kernel measurement. There is no
            # branch here and there is not meant to be one.
            "determinism_tier": "D2",
        }
        if self.preview_builds:
            out["preview_builds"] = list(self.preview_builds)
        return out


def _assignment_json(
    model: _PoseModel, iterate: Any, best_of: Sequence[float]
) -> dict[str, JSONValue]:
    from hephaestus.geom.solve import weighted_distance

    values = model.assignment(iterate.x)
    return {
        "from_start": iterate.from_start,
        "values": {name: values[name] for name in sorted(values)},
        "distance_from_as_built": weighted_distance(iterate.x, best_of, model.variables),
        "iterations": iterate.iterations,
        "limits_active": list(iterate.bounds_active),
        "dof_remaining": iterate.dof_remaining,
        "chosen": False,
    }


def _remeasure(
    *,
    problem: _Problem,
    entries: set[str],
    iterate: Any,
    spec: Mapping[str, Any],
) -> _Verified:
    """One iterate, re-measured in another process, or a named refusal.

    ``SOLVER.md`` §7, and shared by both solve spaces because every clause of
    §7 is about the *record*, not about which variables produced it. Used by
    every path that reports numbers — the verdict paths and the run-time
    refusals alike — because §6.3 makes a refusal carry "the best iterate and
    its independently re-measured residuals", not a bare name.

    Two things can go wrong here and each has its own name and its own reason
    for being where it is. ``stale_proposal_inputs`` is RESOLUTION-time: a
    concurrent build republished geometry between frame extraction and this
    pass, so the iterate was computed against frames that no longer describe
    any current artifact, the fix is to rerun rather than to read a number, and
    re-measuring anyway would silently mix two generations.
    ``solver_residual_disagreement`` is RUN-time and fatal: a solver whose
    model has drifted from the kernel's is not producing evidence, and
    reporting its answer with a caveat would be exactly the overclaim this
    vocabulary exists to prevent.
    """
    measured = _verify(spec, timeout_s=verify_timeout_s())
    refs = cast("Mapping[str, str]", measured["artifact_refs"])
    drifted = sorted(
        part
        for part, ref in refs.items()
        if part in problem.artifact_refs and problem.artifact_refs[part] != ref
    )
    if drifted:
        raise SolveUnresolvable(
            "stale_proposal_inputs",
            "a concurrent build republished geometry underneath this solve: "
            f"{', '.join(drifted)} moved between frame extraction and "
            "verification, so the iterate was computed against frames that no "
            "longer describe any current artifact. Refused rather than "
            "re-measured, because mixing two generations silently would be the "
            "one thing a proposal must never do",
        )
    rows, points, disagreement = _verified_rows(problem, iterate, measured)
    if disagreement > VERIFY_EPS:
        raise SolveRunRefusal(
            "solver_residual_disagreement",
            "the solver's own number and the kernel's re-measured one differ by "
            f"{disagreement:.6g}, beyond VERIFY_EPS ({VERIFY_EPS}). No verdict is "
            "emitted: a solver whose model of the geometry has drifted from the "
            "kernel's is not producing evidence, and reporting its answer with a "
            "caveat would be exactly the overclaim this vocabulary exists to "
            "prevent (SOLVER.md §7.6)",
            payload={
                "from_start": iterate.from_start,
                "worst_disagreement": disagreement,
                "verify_eps": VERIFY_EPS,
                "constraints": [row.to_json() for row in rows],
                "points": [dict(point) for point in points],
            },
        )
    return _Verified(
        iterate=iterate,
        constraints=rows,
        points=points,
        collateral=tuple(_collateral_rows(measured, entries)),
        disagreement=disagreement,
        closure_clean=bool(measured["closure_clean"]),
        preview_builds=tuple(
            cast("JSONValue", dict(row))
            for row in cast("Sequence[Mapping[str, Any]]", measured.get("preview_builds", ()))
        ),
    )


def solve_pose(
    layout: ProjectLayout,
    store: OpStore,
    request: PoseSolveRequest,
    *,
    scratch: Path | None = None,
) -> SolveRecord:
    """Solve for joint parameter values and hand back a **verified proposal**.

    ``SOLVER.md`` §2A. Nothing is written: no proposal artifact, no pose
    declaration, no generation, no artifact republished, no build made
    current. ``declare_pose`` remains an explicit act, and applying this
    answer is an authoring act through the ordinary surface.

    The pipeline is ``SOLVER.md`` §2's five steps, in order: **resolve**
    anchors once against current artifacts, **assemble** the reformulated
    residual vector of §3.3, **iterate** with weighted Levenberg-Marquardt
    from every declared start, **re-measure independently** in a separate
    process through :mod:`hephaestus.core.assembly`, and **record** the result
    as a solve record whose two blocks each state their own determinism tier.

    Every failure has its own name and none of them is a verdict: request-time
    refusals are :class:`InvalidSolveRequest`, resolution failures are
    :class:`SolveUnresolvable`, and ceilings and kernel disagreement are
    :class:`SolveRunRefusal` carrying the best iterate and its verified
    residuals.
    """
    request = request.validated()
    try:
        if scratch is not None:
            return _solve_pose_in(layout, store, request, scratch)
        layout.store_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="heph-solve-", dir=layout.store_root) as tmp:
            return _solve_pose_in(layout, store, request, Path(tmp))
    except SolveUnresolvable as exc:
        # ``unresolvable(reason)`` is verdict SIX (``SOLVER.md`` §6.1), not an
        # exception the caller has to know about, and it is the one name that
        # is both a verdict spelling and a resolution-time refusal (§6.3). 8C
        # made the same call for the same reason: "not checked" is a state a
        # status REPORTS, because an unchecked constraint is not a passing one
        # and hiding it behind a transport error would make it easier to miss
        # than a failure.
        return _unresolvable_record(request, exc)


def _unresolvable_record(request: PoseSolveRequest, exc: SolveUnresolvable) -> SolveRecord:
    """Verdict 6, with NO blocks — because nothing was computed to tier.

    ``SOLVER.md`` §9 tiers a block by how it was produced; an unresolvable
    solve produced neither, so it claims neither. Emitting an empty
    ``solver_core`` that said ``D1`` would be a determinism claim about
    arithmetic that never ran, which is the overclaim the tiering exists to
    prevent.
    """
    return SolveRecord(
        verdict="unresolvable",
        space="pose",
        request=request.to_json(),
        solver_core={},
        verification={},
        assignments=(),
        constraint_generation=-1,
        joint_generation=-1,
        artifact_refs={},
        detail=exc.detail,
        reason=exc.reason,
        subject=exc.subject,
    )


def _solve_pose_in(
    layout: ProjectLayout,
    store: OpStore,
    request: PoseSolveRequest,
    scratch: Path,
) -> SolveRecord:
    """The whole pipeline, inside one scratch directory and one resolver."""
    from hephaestus.core.motion import BoundPoseError, motion_resolution
    from hephaestus.core.project_store.kinematics import JointSet
    from hephaestus.geom.solve import (
        SolveRefused,
        WeightPolicy,
        distinct_solutions,
        solve_least_squares,
        weighted_distance,
    )

    resolver = AnchorResolver(layout, store, Publisher(layout, store), scratch)
    resolution = motion_resolution(layout, store, resolver)
    joint_state = JointSet(layout, store).state()
    constraint_state = ConstraintSet(layout, store).state()

    entries: dict[str, ConstraintEntry] = {}
    for target in request.targets:
        if not isinstance(target, ConstraintTarget):
            continue
        entry = constraint_state.by_id.get(target.constraint_id)
        if entry is None:
            raise InvalidSolveRequest(
                "unknown_constraint",
                f"no constraint {target.constraint_id!r} is declared "
                f"(declared: {', '.join(sorted(constraint_state.by_id)) or 'none'})",
                subject=target.constraint_id,
            )
        if entry.withdrawn:
            raise InvalidSolveRequest(
                "withdrawn_constraint",
                f"constraint {entry.id!r} is withdrawn ({entry.withdrawn_reason}); the "
                "project stopped claiming it, and solving towards a claim nobody "
                "makes would be inventing the intent",
                subject=entry.id,
            )
        excluded = OBJECTIVE_EXCLUSIONS.get(entry.kind)
        if excluded is not None:
            raise InvalidSolveRequest(
                "not_an_objective_kind",
                f"constraint {entry.id!r} is {entry.kind!r}, which is not an objective "
                f"term in pose space ({excluded}) — SOLVER.md §3.2. It is still "
                "EVALUATED at whatever solution a solve reaches; it just cannot steer "
                "the iteration, and a solver that 'optimised' it silently would not "
                "work",
                subject=entry.id,
                sub_reason=excluded,
            )
        entries[entry.id] = entry

    variables = _free_variables(resolution, joint_state, request)

    def _moved(parts: Sequence[str]) -> set[str]:
        return {
            part
            for part in parts
            if any(variable.name in resolution.chain_joints([part]) for variable in variables)
        }

    problem = _extract(
        resolver, entries, request.targets, variables, _moved, constraint_state.active
    )
    model = _PoseModel(resolution, problem.terms, problem.specs, problem.variables, problem.parts)
    policy = (
        WeightPolicy.unit_scaled_v1(problem.characteristic_radius_mm)
        if request.weighting == "unit_scaled_v1"
        else WeightPolicy.declared(
            mm=cast("tuple[float, float]", request.weights)[0],
            deg=cast("tuple[float, float]", request.weights)[1],
        )
    )
    ceiling = request.ceiling if request.ceiling is not None else solve_iter_max()
    limit = time.monotonic() + solve_timeout_s()
    as_built = [0.0] * len(problem.variables)

    def _measure(iterate: Any) -> _Verified:
        """Re-measure one iterate elsewhere, and refuse rather than absorb drift."""
        return _remeasure(
            problem=problem,
            entries=set(entries),
            iterate=iterate,
            spec={
                "root": str(layout.root),
                "scratch": str(scratch),
                "space": "pose",
                "values": model.assignment(iterate.x),
                "parts": list(problem.parts),
                "constraints": sorted({*entries, *problem.collateral}),
                "points": [
                    target.to_json()
                    for target in request.targets
                    if isinstance(target, PointTarget)
                ],
            },
        )

    iterates: list[Any] = []
    for start in request.starts:
        unknown = sorted(set(start.values) - {v.name for v in problem.variables})
        if unknown:
            raise InvalidSolveRequest(
                "unknown_joint",
                f"start {start.id!r} assigns joint(s) {', '.join(unknown)}, which are "
                "not in the free set; a start names the free variables it starts from",
                subject=unknown[0],
            )
        x0 = [float(start.values.get(v.name, 0.0)) for v in problem.variables]
        for index, variable in enumerate(problem.variables):
            below = variable.lower is not None and x0[index] < variable.lower
            above = variable.upper is not None and x0[index] > variable.upper
            if below or above:
                raise SolveUnresolvable(
                    "unresolvable_pose",
                    f"start {start.id!r} places joint {variable.name!r} at "
                    f"{x0[index]:g}, outside its declared limits "
                    f"[{variable.lower}, {variable.upper}] - refused, not clamped "
                    "(geom/kinematics.py:217-245)",
                    subject=variable.name,
                )
        try:
            iterates.append(
                solve_least_squares(
                    model,
                    x0,
                    policy=policy,
                    tol=request.tol,
                    iteration_ceiling=ceiling,
                    start_id=start.id,
                    deadline=lambda: time.monotonic() > limit,
                )
            )
        except SolveRefused as exc:
            raise _run_refusal(exc, start.id, model, _measure) from exc
        except BoundPoseError as exc:
            # An iterate the box should have kept inside a declared limit got
            # out anyway. That is a bug's shape, not a verdict's: report it as
            # unresolvable naming the joint, never as "no pose found", because
            # a pose nobody may evaluate was not searched for and failed - it
            # was never a candidate at all.
            raise SolveUnresolvable(
                "unresolvable_pose",
                f"start {start.id!r}: {exc.detail}",
                subject=exc.pose_id,
            ) from exc

    converged = [item for item in iterates if item.termination == "tolerance"]
    if converged:
        candidates = distinct_solutions(converged, problem.variables)
    else:
        candidates = (min(iterates, key=lambda item: item.weighted_inf_norm),)
    if not converged and all(item.termination == "iteration_ceiling" for item in iterates):
        best = _measure(candidates[0])
        raise SolveRunRefusal(
            "iteration_ceiling",
            f"every declared start spent its whole budget of {ceiling} iterations "
            "without reaching tolerance or stationarity. This is a refusal, NOT a "
            "verdict: the budget ran out, so nothing was decided, and giving the "
            "ceiling a verdict spelling would let it be read as an outcome "
            "(core/motion.py:1489-1498)",
            payload={
                "from_start": best.iterate.from_start,
                "iterations": best.iterate.iterations,
                "iteration_ceiling": ceiling,
                "best_iterate": cast("JSONValue", model.assignment(best.iterate.x)),
                "verified": cast("JSONValue", best.to_json()),
            },
        )

    verified = [_measure(iterate) for iterate in candidates]
    good = [item for item in verified if item.all_satisfied] if converged else []
    has_constraints = bool(entries)
    verdict, detail, shown = _decide(
        verified=verified,
        good=good,
        iterates=iterates,
        has_constraints=has_constraints,
    )
    assignments = tuple(
        _assignment_json(model, item.iterate, as_built)
        for item in sorted(
            shown, key=lambda item: weighted_distance(item.iterate.x, as_built, model.variables)
        )
    )
    primary = shown[0]
    return SolveRecord(
        verdict=verdict,
        space="pose",
        request=request.to_json(),
        solver_core=_solver_core(problem, policy, primary.iterate, request, ceiling),
        verification={
            **primary.to_json(),
            "verified_assignments": [item.to_json() for item in shown],
        },
        assignments=assignments,
        constraint_generation=constraint_state.generation,
        joint_generation=joint_state.generation,
        artifact_refs=problem.artifact_refs,
        detail=detail,
    )


@dataclass(frozen=True)
class _PartialIterate:
    """The iterate a refusal happened at, dressed as one for reporting only.

    It carries no rank, no null space and no termination, because none was
    computed — a refusal that invented them would be exactly the overclaim the
    refusal exists to avoid. What it does carry is what the run actually
    reached, so the refusal is not empty-handed.
    """

    x: tuple[float, ...]
    values: tuple[Any, ...]
    from_start: str
    iterations: int = 0


def _run_refusal(
    exc: Any,
    start_id: str,
    model: _PoseModel,
    measure: Any,
) -> SolveRunRefusal:
    """Turn a :class:`~hephaestus.geom.solve.SolveRefused` into a carried refusal."""
    from hephaestus.geom.solve import component_values

    payload: dict[str, JSONValue] = {
        "from_start": start_id,
        "detail": cast("JSONValue", dict(exc.detail)),
    }
    if exc.x:
        partial = _PartialIterate(
            x=tuple(exc.x), values=component_values(model, exc.x), from_start=start_id
        )
        payload["best_iterate"] = cast("JSONValue", model.assignment(exc.x))
        try:
            payload["verified"] = cast("JSONValue", measure(partial).to_json())
        except (SolveUnresolvable, SolveRunRefusal):  # pragma: no cover - defensive
            payload["verified"] = None
    return SolveRunRefusal(exc.reason, exc.message, payload=payload)


#: How one outcome is spelled in each solve space (``SOLVER.md`` §6.1). The
#: DECISION is one function - the facts it distinguishes are identical in every
#: space, and a second copy per space would be a second chance to get the
#: convergence/multiplicity/over-constrained distinction wrong. Only the
#: spellings and the noun differ, so only they are data.
_POSE_SPELLINGS: Final[Mapping[str, str]] = {
    "multiple": "multiple_poses_from_starts",
    "underdetermined": "pose_underdetermined_at_tolerance",
    "converged": "pose_converged_at_tolerance",
    "found": "pose_found",
    "overconstrained": "pose_overconstrained_at_residual_floor",
    "none": "no_pose_found_from_starts",
    "noun": "assignment",
}

#: Transform space, whose set is the six of :data:`TRANSFORM_SOLVE_VERDICTS`.
#: ``found`` is mapped onto ``converged_at_tolerance`` and is unreachable: a
#: transform-space solve always has constraint targets (a request with a free
#: part in no constraint is refused ``free_part_in_no_constraint``), so the
#: existence spelling has no request that could produce it.
_TRANSFORM_SPELLINGS: Final[Mapping[str, str]] = {
    "multiple": "multiple_solutions_from_starts",
    "underdetermined": "underdetermined_at_tolerance",
    "converged": "converged_at_tolerance",
    "found": "converged_at_tolerance",
    "overconstrained": "overconstrained_at_residual_floor",
    "none": "no_placement_found_from_starts",
    "noun": "placement",
}


def _decide(
    *,
    verified: Sequence[_Verified],
    good: Sequence[_Verified],
    iterates: Sequence[Any],
    has_constraints: bool,
    spellings: Mapping[str, str] = _POSE_SPELLINGS,
) -> tuple[SolveVerdict, str, tuple[_Verified, ...]]:
    """Name the outcome (``SOLVER.md`` §6.1) — never "solved", never "infeasible".

    The order matters and each branch is a different fact:

    * two or more verified, distinct, satisfying members → multiplicity, and
      **all** of them are returned with none marked chosen. A bracket flipped
      180° about a bore satisfies the same mates and rank tells you nothing
      about it, so discrete multiplicity has to surface here or nowhere.
    * one, at full column rank → converged (or ``pose_found`` for an
      anchor-to-point request, whose success IS an existence claim).
    * one, rank-deficient → ``pose_underdetermined_at_tolerance`` with the
      remaining DOF named. This is a distinct verdict, not a footnote on
      success: reporting one point of a continuum as *the* answer is a claim
      the mathematics does not support.
    * none, stationary at full rank with a constraint-id target → the declared
      constraints disagree with each other over the declared free variables,
      and **no culprit is named**: identifying a minimal inconsistent subset
      is a different computation nobody has run.
    * otherwise → this start did not get there. Never "infeasible": a local
      method's silence is evidence about one basin, not about the space.
    """
    say = cast("Any", spellings.__getitem__)
    noun = spellings["noun"]
    if len(good) > 1:
        return (
            say("multiple"),
            f"{len(good)} declared starts converged to solutions further apart than "
            "SOLUTION_DISTINCT_EPS; all are returned, ranked by distance from "
            "as_built, and none is chosen — picking one would be a design decision "
            "the mathematics does not make",
            tuple(good),
        )
    if len(good) == 1:
        item = good[0]
        if item.iterate.dof_remaining > 0:
            names = "; ".join(direction.label for direction in item.iterate.null_basis)
            return (
                say("underdetermined"),
                f"{item.iterate.dof_remaining} degree(s) of freedom remain at the "
                f"returned {noun}; one member of a positive-dimensional solution "
                f"set is being shown. Free directions: {names}",
                (item,),
            )
        if has_constraints:
            return (
                say("converged"),
                "every objective constraint re-measures satisfied through the "
                "ordinary engine path, every residual is inside the declared "
                "tolerance, and the Jacobian has full column rank at the solution. "
                "Evidence about this iterate from this start; it claims nothing "
                "about uniqueness beyond the local basin",
                (item,),
            )
        return (
            say("found"),
            "an achieving assignment was found and independently re-measured. An "
            "anchor-to-point target is an EXISTENCE claim, so one verified achieving "
            "assignment is proof (KINEMATICS.md:209-222)",
            (item,),
        )
    best = verified[0]
    stationary = any(item.termination == "stationary" for item in iterates)
    full_rank = best.iterate.dof_remaining == 0
    # Verdict 4's SECOND route, checked before verdict 5 because the two are
    # not alternatives: a run that reached tolerance on every primary and
    # target component while an objective constraint still re-measures
    # ``satisfied is False`` did not find a disagreement between constraints -
    # it found the class-predicate case of SOLVER.md §3.1, "the gap is zero and
    # it is still not a mate". Calling that over-constrained would blame the
    # declaration for a fact about the normals, and §6.1 verdict 4 names it
    # explicitly as one of its two routes.
    primary_ok = all(
        component.within_bound
        for row in best.constraints
        for component in row.components
        if component.role in ("primary", "target")
    ) and all(bool(point["within_bound"]) for point in best.points)
    if primary_ok and not best.all_satisfied:
        return (
            say("none"),
            "a start reached tolerance on the primary components while an objective "
            "constraint still re-measures satisfied is False - the class-predicate "
            f"case of SOLVER.md §3.1: {', '.join(best.unsatisfied())}. The gap is "
            "zero and it is still not a mate, which is exactly the fact an author "
            "needs and the fact a residual number hides. Starts tried: "
            + ", ".join(item.from_start for item in iterates),
            (best,),
        )
    if stationary and full_rank and has_constraints:
        return (
            say("overconstrained"),
            "a start reached a stationary point whose weighted residual is still "
            f"above tolerance, at full column rank (stationarity "
            f"{best.iterate.stationarity:.6g}): the declared constraints disagree "
            "with each other over the declared free variables. No culprit constraint "
            "is named — identifying a minimal inconsistent subset is a different "
            "computation nobody has run, and naming one on a whim would be a verdict "
            "about the author's intent. It does not claim global infeasibility, only "
            "that this start's basin has none",
            (best,),
        )
    unsatisfied = best.unsatisfied()
    route = (
        "a start reached tolerance on the primary components while an objective "
        "constraint still re-measures satisfied is False (the class-predicate case "
        f"of SOLVER.md §3.1): {', '.join(unsatisfied)}"
        if best.iterate.termination == "tolerance"
        else "no declared start reached the declared tolerance"
    )
    starts = ", ".join(item.from_start for item in iterates)
    return (
        say("none"),
        f"{route}. Starts tried: {starts}. This is evidence about these starts' "
        "basins and nothing more",
        (best,),
    )


def _solver_core(
    problem: _Problem,
    policy: Any,
    iterate: Any,
    request: PoseSolveRequest,
    ceiling: int,
) -> dict[str, JSONValue]:
    """The ``solver_core`` block (``SOLVER.md`` §9), and why it can claim D1.

    A pose solve's iteration is kernel-free: frames are extracted once and
    everything after that is fixed-order plain-float arithmetic in
    :mod:`hephaestus.geom.solve`. **Given identical extracted frames**, an
    identical request, and the pinned image, this block is byte-identical
    across processes — so the frames are carried INSIDE it, not upstream of
    it, because the claim is conditional on them and a reader must be able to
    check the condition rather than take it on faith. No timestamp appears
    here for the same reason.

    The tier is written as a constant here because in POSE space it is one:
    every 2A iteration is kernel-free. **A later space may not reuse this.**
    ``SOLVER.md`` §9 makes 2C's ``solver_core`` unconditionally D2 (each of its
    iterates is a preview build), and a 2B solve is D1 only while every
    objective term is analytic. Whoever adds those must make this value a
    decision rather than inherit a constant that happened to be true once.
    """
    return {
        "determinism_tier": "D1",
        "frames": [term.to_json() for term in problem.terms],
        "variables": [
            {
                "name": variable.name,
                "unit": variable.unit,
                "lower": variable.lower,
                "upper": variable.upper,
            }
            for variable in problem.variables
        ],
        "weights": [
            {"key": spec.key, "unit": spec.unit, "weight": policy.applied(spec)}
            for spec in problem.specs
        ],
        "weighting": policy.mode,
        "characteristic_radius_mm": policy.characteristic_radius_mm,
        "regularization": request.regularization,
        "iteration_ceiling": ceiling,
        "from_start": iterate.from_start,
        "iterations": iterate.iterations,
        "termination": iterate.termination,
        "weighted_inf_norm": iterate.weighted_inf_norm,
        "stationarity": iterate.stationarity,
        "rank": iterate.rank,
        "dof_remaining": iterate.dof_remaining,
        "kappa": iterate.kappa,
        "limits_active": list(iterate.bounds_active),
        "null_basis": [
            {
                "label": direction.label,
                "components": [[name, value] for name, value in direction.components],
            }
            for direction in iterate.null_basis
        ],
        "solver_residuals": [
            {"key": value.key, "measured": value.measured, "within_bound": value.within_bound}
            for value in iterate.values
        ],
    }


# --------------------------------------------------------------------------
# transform space (``SOLVER.md`` §2B) — the placement PROPOSAL


#: How many free scalars one free part contributes: three mm of translation and
#: three degrees of rotation vector (``geom.solve``'s SE(3) parametrisation).
TRANSFORM_DOF: Final[int] = 6

#: The per-part variable suffixes, in the fixed order every vector uses.
TRANSFORM_AXES: Final[tuple[str, ...]] = ("tx", "ty", "tz", "rx", "ry", "rz")

#: Fault-injection hook for ``SOLVER.md`` §4.2 step 5 (G13B clause 28). When
#: set to a float, every candidate iterate's rotation block is perturbed by
#: that amount before the SO(3) validity check, so a gate can prove that an
#: iterate which is not a rigid placement is REFUSED rather than used to place
#: geometry. The exponential parametrisation makes every rotation orthonormal
#: by construction, so without this hook the check is unreachable — and a
#: safeguard no test can fire is a safeguard nobody knows works. There is no
#: production path that sets it.
SO3_FAULT_ENV: Final[str] = "HEPHAESTUS_SOLVE_SO3_FAULT"


def _so3_fault() -> float:
    raw = os.environ.get(SO3_FAULT_ENV)
    if raw is None:
        return 0.0
    try:
        return float(raw)
    except ValueError:  # pragma: no cover - a malformed override is simply off
        return 0.0


@dataclass(frozen=True)
class PlacementSolveRequest:
    """A transform-space solve, stated once and echoed in the proposal.

    ``constraints`` are declared 8C constraint ids — there is no
    anchor-to-point form here, because a point target drives one anchor's
    reference point and a free rigid transform can satisfy any such target
    exactly, which would make the answer a statement about the request rather
    than about the design.

    ``free`` names the parts whose placement is being proposed. Everything
    else is ground, and **at least one part must be** (``no_ground_part``): a
    system with no ground has a six-dimensional trivial null space, so every
    reported solution would be an arbitrary member of it and the report would
    be about the arithmetic rather than about the geometry.
    """

    constraints: tuple[str, ...]
    free: tuple[str, ...]
    tol: float
    weighting: str
    regularization: str
    provenance: ConstraintProvenance
    ground: tuple[str, ...] | None = None
    starts: tuple[SolveStart, ...] = (SolveStart(),)
    weights: tuple[float, float] | None = None
    ceiling: int | None = None
    space: str = "transform"
    #: The optional declared box (``SOLVER.md`` §4.2 step 4: "2B is unbounded
    #: unless the request declares a box"), keyed by variable name
    #: ``"<part>.tx|ty|tz|rx|ry|rz"`` and valued ``(lower, upper)`` with
    #: ``None`` for unbounded on that side. Bounds are never clamped in
    #: silence: a step that would leave the box is shortened to the boundary
    #: and every variable sitting on one comes back in ``bounds_active``,
    #: because a solution on a bound is a boundary solution and not a
    #: stationary point (``geom/kinematics.py:217-245``).
    box: Mapping[str, tuple[float | None, float | None]] | None = None
    #: ``SOLVER.md`` §10's 2C budget slot (§11's ``budgets?``), named for the
    #: one budget parameter space actually has. ``None`` takes
    #: :func:`solve_build_budget`. Ignored in transform space, whose iteration
    #: issues no builds at all — and refused there rather than ignored, because
    #: a declared budget nobody spends is a limit a reader would believe was
    #: enforced.
    build_budget: int | None = None

    def to_json(self, *, ground: Sequence[str] = ()) -> dict[str, JSONValue]:
        """The echoed request. ``ground`` is the RESOLVED set, not the declared one.

        A request may leave ``ground`` implicit — everything not free — and a
        record that echoed the omission would leave a reader to re-derive
        which parts were held still. The resolved set is a fact about the
        solve, so the solve states it.
        """
        return {
            "space": self.space,
            "constraints": list(self.constraints),
            "free": list(self.free),
            "ground": list(ground if ground else (self.ground or ())),
            "tol": self.tol,
            "weighting": self.weighting,
            "weights": (
                {"mm": self.weights[0], "deg": self.weights[1]}
                if self.weights is not None
                else None
            ),
            "regularization": self.regularization,
            "provenance": cast("JSONValue", self.provenance.to_json()),
            "starts": [start.to_json() for start in self.starts],
            "ceiling": self.ceiling,
            "box": (
                None
                if self.box is None
                else {name: list(self.box[name]) for name in sorted(self.box)}
            ),
            "build_budget": self.build_budget,
        }

    def validated(self) -> PlacementSolveRequest:
        """The ``SOLVER.md`` §6.3 request-time refusals that need no geometry."""
        from hephaestus.core.project_store.constraints import ConstraintError
        from hephaestus.geom.solve import DETERMINISM_FLOOR

        if self.space not in SOLVE_SPACES:
            # An unrecognised space is refused rather than silently solved as a
            # transform, because a request that asked for one space and got
            # another is worse than one that was refused.
            raise InvalidSolveRequest(
                "no_free_variables",
                f"space {self.space!r} is not solvable here; the closed set is "
                f"{', '.join(SOLVE_SPACES)} (SOLVER.md §11)",
                subject=self.space,
            )
        if self.space == "parameters":
            # Parameter space's box is the DECLARED ``Param`` min/max (§2C) and
            # its ground concept does not exist: there is no part being held
            # still, only knobs the author declared. Both are refused rather
            # than ignored, and both reuse a name from §6.3's CLOSED
            # request-time set rather than inventing a spelling this stage has
            # no mandate for — the 13B stray-box precedent, same rule, with the
            # real fact in the message.
            if self.box is not None:
                raise InvalidSolveRequest(
                    "no_free_variables",
                    "a parameter-space solve does not take a declared box: a "
                    "``Param``'s own min/max IS its box (SOLVER.md §2C), and a "
                    "second one would be a bound the author never declared "
                    "silently overriding the one they did",
                )
            if self.ground:
                raise InvalidSolveRequest(
                    "no_ground_part",
                    "a parameter-space solve declares no ground: nothing is being "
                    "held still, the variables are named Params, and every part the "
                    "requested constraints anchor is rebuilt at each candidate "
                    "(SOLVER.md §2C)",
                    subject=self.ground[0],
                )
        elif self.build_budget is not None:
            raise InvalidSolveRequest(
                "no_free_variables",
                "a transform-space iteration issues no builds at all (SOLVER.md §4.2 "
                "step 1: frames once, then plain-float arithmetic), so a declared "
                "build budget would be a limit nothing spends and a reader would "
                "believe was enforced. It is 2C's budget (SOLVER.md §10)",
            )
        if not self.free:
            raise InvalidSolveRequest(
                "no_free_variables",
                "a placement solve declares at least one free part; with nothing free "
                "there is no variable to solve for and no placement to propose",
            )
        duplicates = sorted({name for name in self.free if self.free.count(name) > 1})
        if duplicates:
            raise InvalidSolveRequest(
                "no_free_variables",
                f"part(s) {', '.join(duplicates)} are declared free twice; a duplicated "
                "free part would contribute its six variables twice without saying so",
                subject=duplicates[0],
            )
        if self.ground is not None:
            overlap = sorted(set(self.ground) & set(self.free))
            if overlap:
                raise InvalidSolveRequest(
                    "no_ground_part",
                    f"part(s) {', '.join(overlap)} are declared both free and ground; a "
                    "part is one or the other, and letting it be both would make the "
                    "returned transform attributable to neither",
                    subject=overlap[0],
                )
        if self.weighting not in ("unit_scaled_v1", "declared"):
            raise InvalidSolveRequest(
                "undeclared_weighting",
                f"weighting {self.weighting!r} is not declared; a residual vector "
                'mixing mm and deg has no canonical norm, so "unit_scaled_v1" or '
                '"declared" is required and echoed (SOLVER.md §3.4, on the '
                "COMPARE.md:34-36 precedent)",
            )
        if self.weighting == "declared" and self.weights is None:
            raise InvalidSolveRequest(
                "undeclared_weighting",
                'weighting "declared" requires an explicit {"mm": w, "deg": w} pair '
                "(SOLVER.md §3.4)",
            )
        if self.regularization != "min_norm_from_start":
            raise InvalidSolveRequest(
                "undeclared_regularization",
                f"regularization {self.regularization!r} is not declared; "
                '"min_norm_from_start" is the only Stage 13 member and is still '
                "required, because the Jacobian is rank-deficient by construction in "
                "this space (SOLVER.md §6.1 verdict 2) and which null-space member is "
                "returned is a design decision (SOLVER.md §3.5)",
            )
        if self.tol < DETERMINISM_FLOOR:
            raise InvalidSolveRequest(
                "tolerance_below_determinism_floor",
                f"declared tolerance {self.tol!r} is tighter than the determinism "
                f"floor {DETERMINISM_FLOOR}: the number two processes in the pinned "
                "image are gated to agree to (ASSEMBLY.md:152-153). Nothing here has "
                "measured the kernel's accuracy against ground truth, so a tighter "
                "tolerance would be a claim nobody computed (SOLVER.md §6.3)",
            )
        try:
            self.provenance.validated("solve")
        except ConstraintError as exc:
            raise InvalidSolveRequest("missing_provenance", exc.message) from exc
        seen: set[str] = set()
        for constraint_id in self.constraints:
            if constraint_id in seen:
                raise InvalidSolveRequest(
                    "unknown_constraint",
                    f"constraint {constraint_id!r} is declared twice; a duplicated "
                    "target would weight one constraint twice without saying so",
                    subject=constraint_id,
                )
            seen.add(constraint_id)
        return self


class _TransformModel:
    """The transform-space residual model (``SOLVER.md`` §2B).

    One rigid transform per free part, as six scalars: a translation in mm and
    a rotation vector in degrees about the part's own bounding-box centre. The
    pivot changes only the parametrisation — the returned 3x4 is the same
    either way — but it is what keeps a bracket 500 mm from the world origin
    steppable at the same scale as one sitting on it.

    Frames are extracted ONCE (:func:`_extract`) and transported here in closed
    form, so **no kernel call occurs inside an iteration**: the precondition of
    the ``solver_core`` block's D1 tier (``SOLVER.md`` §9), and the reason
    ``geom.solve`` never sees a shape and the kernel-extremum kinds are
    excluded from this space structurally rather than by taste (§3.2).

    The Jacobian is analytic (NW4) and is a Jacobian **of the reformulation**:
    a translation component moves a point by a basis vector and a direction not
    at all; a rotation component carries both through the exact derivative of
    the exponential map (:func:`~hephaestus.geom.solve.rotation_derivatives`).
    """

    def __init__(
        self,
        terms: Sequence[_Term],
        specs: Sequence[Any],
        variables: Sequence[Any],
        free: Sequence[str],
        pivots: Mapping[str, Vec3],
    ) -> None:
        self._terms = tuple(terms)
        self._specs = tuple(specs)
        self._variables = tuple(variables)
        self._free = tuple(free)
        self._pivots = dict(pivots)
        self._offset = {part: index * TRANSFORM_DOF for index, part in enumerate(self._free)}

    @property
    def variables(self) -> tuple[Any, ...]:
        return self._variables

    @property
    def components(self) -> tuple[Any, ...]:
        return self._specs

    def transforms(self, x: Sequence[float]) -> dict[str, tuple[tuple[float, ...], ...]]:
        """The candidate transform per free part, checked for rigidity (§4.2 step 5)."""
        from hephaestus.geom.solve import (
            SO3_EPS,
            SO3_REPROJECT_EPS,
            SolveRefused,
            is_rotation,
            reproject_rotation,
            rigid_rows,
        )

        fault = _so3_fault()
        out: dict[str, tuple[tuple[float, ...], ...]] = {}
        for part, offset in self._offset.items():
            rows: tuple[tuple[float, ...], ...] = tuple(
                tuple(value for value in row)
                for row in rigid_rows(
                    (x[offset], x[offset + 1], x[offset + 2]),
                    (x[offset + 3], x[offset + 4], x[offset + 5]),
                    self._pivots.get(part, _ZERO),
                )
            )
            if fault:
                rows = tuple(
                    tuple(
                        value + (fault if column < 3 else 0.0) for column, value in enumerate(row)
                    )
                    for row in rows
                )
            deviation = is_rotation(rows)
            if deviation > SO3_REPROJECT_EPS:
                raise SolveRefused(
                    "non_rigid_iterate",
                    f"the candidate transform for part {part!r} has a rotation block "
                    f"{deviation:.6g} from orthonormal, beyond SO3_REPROJECT_EPS "
                    f"({SO3_REPROJECT_EPS}). It is not a rigid placement, so it is not "
                    "a placement: proposing it would hand back a 'transform' that "
                    "shears or scales the part it names (SOLVER.md §4.2 step 5)",
                    detail={"deviation": deviation, "so3_reproject_eps": SO3_REPROJECT_EPS},
                )
            if deviation > SO3_EPS:
                rows = reproject_rotation(rows)
            out[part] = rows
        return out

    def _placed(self, term: _Term, transforms: Mapping[str, Sequence[Sequence[float]]]) -> _Placed:
        rows_a = transforms.get(term.part_a)
        rows_b = transforms.get(term.part_b)
        point_a = _apply(rows_a, term.point_a) if rows_a is not None else term.point_a
        dir_a = _rot(rows_a, term.dir_a) if rows_a is not None else term.dir_a
        u_a = _rot(rows_a, term.u_a) if rows_a is not None else term.u_a
        v_a = _rot(rows_a, term.v_a) if rows_a is not None else term.v_a
        point_b = _apply(rows_b, term.point_b) if rows_b is not None else term.point_b
        dir_b = _rot(rows_b, term.dir_b) if rows_b is not None else term.dir_b
        return (point_a, dir_a, u_a, v_a, point_b, dir_b)

    def evaluate(self, x: Sequence[float]) -> tuple[tuple[float, ...], ...]:
        transforms = self.transforms(x)
        out: list[tuple[float, ...]] = []
        for term in self._terms:
            out.extend(_term_residuals(term, self._placed(term, transforms)))
        return tuple(out)

    def jacobian(self, x: Sequence[float]) -> tuple[tuple[float, ...], ...] | None:
        from hephaestus.geom.solve import rotation_derivatives

        transforms = self.transforms(x)
        derivatives = {
            part: rotation_derivatives((x[offset + 3], x[offset + 4], x[offset + 5]))
            for part, offset in self._offset.items()
        }
        columns: list[list[float]] = []
        for part in self._free:
            pivot = self._pivots.get(part, _ZERO)
            for axis in range(TRANSFORM_DOF):
                column: list[float] = []
                for term in self._terms:
                    placed = self._placed(term, transforms)

                    def delta(
                        owner: str,
                        base: Vec3,
                        *,
                        point: bool,
                        axis: int = axis,
                        part: str = part,
                        pivot: Vec3 = pivot,
                    ) -> Vec3:
                        if owner != part:
                            # A free transform moves its own part and nothing
                            # else. There is no chain here: a part that rides a
                            # joint may not be free (``free_part_is_jointed``),
                            # which is exactly what makes this a zero rather
                            # than a forward-kinematics walk.
                            return _ZERO
                        if axis < 3:
                            return (
                                (
                                    1.0 if axis == 0 else 0.0,
                                    1.0 if axis == 1 else 0.0,
                                    1.0 if axis == 2 else 0.0,
                                )
                                if point
                                else _ZERO
                            )
                        rows = derivatives[part][axis - 3]
                        target = _sub(base, pivot) if point else base
                        return (
                            _dot(rows[0], target),
                            _dot(rows[1], target),
                            _dot(rows[2], target),
                        )

                    deltas: _Placed = (
                        delta(term.part_a, term.point_a, point=True),
                        delta(term.part_a, term.dir_a, point=False),
                        delta(term.part_a, term.u_a, point=False),
                        delta(term.part_a, term.v_a, point=False),
                        delta(term.part_b, term.point_b, point=True),
                        delta(term.part_b, term.dir_b, point=False),
                    )
                    column.extend(_term_derivative(term, placed, deltas))
                columns.append(column)
        rows_count = len(columns[0]) if columns else 0
        return tuple(tuple(column[i] for column in columns) for i in range(rows_count))


def _transform_variables(
    free: Sequence[str], box: Mapping[str, tuple[float | None, float | None]] | None = None
) -> list[Any]:
    """Six scalars per free part, bounded only by a DECLARED box (§4.2 step 4).

    Unbounded by default, and that is a fact rather than an omission: a part's
    placement has no declared limit the way a joint parameter or a ``Param``
    does, so inventing one would be a constraint nobody wrote. A caller that
    genuinely means "this part may translate but not turn" says so in the box,
    the bound comes back in ``bounds_active``, and the record shows which
    directions were denied rather than leaving a reader to wonder why the
    answer did not use them.
    """
    from hephaestus.geom.solve import SolveVariable

    limits = dict(box or {})
    out: list[Any] = []
    for part in free:
        for axis in TRANSFORM_AXES:
            name = f"{part}.{axis}"
            lower, upper = limits.get(name, (None, None))
            out.append(
                SolveVariable(
                    name=name,
                    unit="mm" if axis.startswith("t") else "deg",
                    lower=lower,
                    upper=upper,
                )
            )
    return out


def _pivots(resolver: AnchorResolver, parts: Sequence[str]) -> dict[str, Vec3]:
    """Each free part's bounding-box centre, in world mm (the rotation pivot)."""
    out: dict[str, Vec3] = {}
    for part in parts:
        try:
            geometry, resolved = resolver.locate(part, WHOLE_PART_SELECTOR)
            shape = geometry.shape_for(resolved)
        except UnresolvableAnchorError as exc:
            raise SolveUnresolvable(
                exc.reason, f"free part {part!r}: {exc.detail}", subject=part
            ) from exc
        box = shape.bounding_box()
        out[part] = (
            (float(box.min.X) + float(box.max.X)) / 2.0,
            (float(box.min.Y) + float(box.max.Y)) / 2.0,
            (float(box.min.Z) + float(box.max.Z)) / 2.0,
        )
    return out


def propose_placement(
    layout: ProjectLayout,
    store: OpStore,
    request: PlacementSolveRequest,
    *,
    scratch: Path | None = None,
    backend: Any | None = None,
) -> SolveRecord:
    """Propose placements for declared free parts or Params (``SOLVER.md`` §2B/§2C).

    The output is a **measurement artifact**: an immutable, content-addressed
    proposal document carrying the candidate transforms and every residual an
    independent process re-measured for them. **Nothing applies it.** No tool,
    CLI verb or agent path in Stage 13 writes a part script, writes a
    parameter, republishes a transformed artifact, or makes a build current;
    the ``AssemblyStatus`` row keeps saying ``violated`` until a rebuilt script
    measures otherwise; and **writeback is refused** — no inverse from a
    transform to a script expression is computed, offered or guessed. That
    refusal is structural rather than a promise this function could break
    later: the proposal document schema is ``additionalProperties: false`` at
    every level and is validated before any write, so a ``suggested_edit``
    field is not rejected by name, it is unrepresentable.

    Applying a proposal is an authoring act. An operator or agent reads the
    proposed translation and axis-angle, decides which *statement* expresses
    that intent — an ``hc`` name, a ``Param``, a literal — and makes the edit
    through the ordinary ``edit_part`` / ``set_params`` surface, where it lands
    in git as a diff a reviewer can read. Stage 13 refuses to guess which of
    those four edits the author meant, because three of them change other
    parts.

    Every failure has its own name and none of them is a verdict:
    :class:`InvalidSolveRequest` at request time,
    :class:`SolveUnresolvable` for resolution (returned INSIDE the record as
    verdict 6, the one spelling that is both), and :class:`SolveRunRefusal`
    for a ceiling, a non-rigid iterate or a solver/kernel disagreement, each
    carrying the best iterate and its independently re-measured residuals.
    """
    request = request.validated()
    run = _propose_placement_in if request.space == "transform" else _propose_params_in
    try:
        if scratch is not None:
            return run(layout, store, request, scratch, backend)
        layout.store_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="heph-solve-", dir=layout.store_root) as tmp:
            return run(layout, store, request, Path(tmp), backend)
    except SolveUnresolvable as exc:
        return SolveRecord(
            verdict="unresolvable",
            space=request.space,
            request=request.to_json(),
            solver_core={},
            verification={},
            assignments=(),
            constraint_generation=-1,
            joint_generation=-1,
            artifact_refs={},
            detail=exc.detail,
            reason=exc.reason,
            subject=exc.subject,
        )


def _placement_entries(
    constraint_state: Any, request: PlacementSolveRequest
) -> dict[str, ConstraintEntry]:
    """The requested constraints as objective terms, or a named refusal each."""
    entries: dict[str, ConstraintEntry] = {}
    for constraint_id in request.constraints:
        entry = cast("ConstraintEntry | None", constraint_state.by_id.get(constraint_id))
        if entry is None:
            raise InvalidSolveRequest(
                "unknown_constraint",
                f"no constraint {constraint_id!r} is declared "
                f"(declared: {', '.join(sorted(constraint_state.by_id)) or 'none'})",
                subject=constraint_id,
            )
        if entry.withdrawn:
            raise InvalidSolveRequest(
                "withdrawn_constraint",
                f"constraint {entry.id!r} is withdrawn ({entry.withdrawn_reason}); the "
                "project stopped claiming it, and solving towards a claim nobody "
                "makes would be inventing the intent",
                subject=entry.id,
            )
        excluded = OBJECTIVE_EXCLUSIONS_BY_SPACE[request.space].get(entry.kind)
        if excluded is not None:
            where = "transform space" if request.space == "transform" else "parameter space"
            raise InvalidSolveRequest(
                "not_an_objective_kind",
                f"constraint {entry.id!r} is {entry.kind!r}, which is not an objective "
                f"term in {where} ({excluded}) — SOLVER.md §3.2. It is still "
                "EVALUATED at whatever solution a solve reaches; it just cannot steer "
                "the iteration, and a solver that 'optimised' it silently would not "
                "work",
                subject=entry.id,
                sub_reason=excluded,
            )
        if entry.poses:
            raise InvalidSolveRequest(
                "pose_bound_constraint_in_transform_space",
                f"constraint {entry.id!r} is bound to pose(s) {', '.join(entry.poses)} "
                "(ASSEMBLY.md §3 / KINEMATICS.md §3), so its residual is already a "
                "function of a pose assignment. Composing a free transform with a "
                "forward-kinematics transform would make the returned number "
                "attributable to neither — solve it in pose space, or unbind it "
                "(SOLVER.md §2B)",
                subject=entry.id,
            )
        entries[entry.id] = entry
    return entries


def _partition_parts(
    entries: Mapping[str, ConstraintEntry],
    joint_state: Any,
    request: PlacementSolveRequest,
    known_parts: Sequence[str],
) -> tuple[str, ...]:
    """The ground set, with §2B's three free-set refusals raised first.

    Returns the parts the requested constraints anchor that are **not** free —
    the ground set — after refusing, by name:

    * a free part that is not a known part of this project;
    * a free part that rides a declared joint (``free_part_is_jointed``);
    * a free part no requested constraint anchors
      (``free_part_in_no_constraint``);
    * a system with nothing left to hold still (``no_ground_part``).
    """
    anchored: set[str] = set()
    for entry in entries.values():
        anchored.update(entry.parts)
    jointed: dict[str, str] = {}
    for entry in joint_state.active:
        parent, child = entry.parts[0], entry.parts[-1]
        jointed.setdefault(child, entry.id)
        jointed.setdefault(parent, entry.id)
    for part in request.free:
        if part not in known_parts:
            raise SolveUnresolvable(
                "missing_part",
                f"no part {part!r} in this project (parts: {', '.join(known_parts)})",
                subject=part,
            )
        if part in jointed:
            # Both joint roles refuse, and the wider reading is deliberate.
            # ``SOLVER.md`` §2B names the child case — a part riding a joint
            # has its position owned by forward kinematics from its parent, and
            # letting a transform and a joint both claim it is the second-home
            # failure P3 describes inside one evaluation. The PARENT case is
            # the same failure seen from the other end: moving a parent freely
            # while its subtree stays where FK put it would propose a placement
            # that no kinematic chain can realise. Refusing both is stricter
            # than the sentence and is named, which is the pair of properties a
            # widening needs.
            raise InvalidSolveRequest(
                "free_part_is_jointed",
                f"part {part!r} is named by declared joint {jointed[part]!r}, so its "
                "placement is owned by forward kinematics and not by this request. "
                "Letting a transform and a joint both claim one part would create a "
                "second home for its position inside a single evaluation — solve it "
                "in pose space instead (SOLVER.md §2A/§2B)",
                subject=part,
            )
        if part not in anchored:
            raise InvalidSolveRequest(
                "free_part_in_no_constraint",
                f"part {part!r} is declared free but no requested constraint anchors "
                "it, so no residual is a function of its six variables. The Jacobian "
                "would carry six all-zero columns and the answer for this part would "
                "be whatever the start happened to be, reported as a solution",
                subject=part,
            )
    ground = tuple(sorted(anchored - set(request.free)))
    if not ground:
        raise InvalidSolveRequest(
            "no_ground_part",
            "every part these constraints anchor is declared free, so the system has "
            "a six-dimensional trivial null space and every reported solution would "
            "be an arbitrary member of it. At least one part must be ground "
            "(SOLVER.md §2B)",
        )
    if request.ground is not None:
        missing = sorted(set(request.ground) - anchored)
        if missing:
            raise InvalidSolveRequest(
                "no_ground_part",
                f"part(s) {', '.join(missing)} are declared ground but no requested "
                "constraint anchors them; a ground declaration names what is being "
                "held still in THIS system, not the whole project",
                subject=missing[0],
            )
    return ground


def _propose_placement_in(
    layout: ProjectLayout,
    store: OpStore,
    request: PlacementSolveRequest,
    scratch: Path,
    backend: Any | None = None,
) -> SolveRecord:
    """The whole §2 pipeline in transform space, inside one scratch directory.

    ``backend`` is accepted and unused: a 2B iteration issues no build at all
    (§4.2 step 1), so the executor has nothing to do here. It is in the
    signature because the dispatcher hands both spaces the same arguments, and
    a space that quietly took a different call would be a second calling
    convention to keep in step.
    """
    _ = backend
    from hephaestus.core.hashing import toolchain_hash
    from hephaestus.core.project_store.kinematics import JointSet
    from hephaestus.core.project_store.proposals import ProposalSet
    from hephaestus.geom.solve import (
        SOLVE_VERSION,
        SolveRefused,
        WeightPolicy,
        distinct_solutions,
        solve_least_squares,
        weighted_distance,
    )

    resolver = AnchorResolver(layout, store, Publisher(layout, store), scratch)
    joint_state = JointSet(layout, store).state()
    constraint_state = ConstraintSet(layout, store).state()

    entries = _placement_entries(constraint_state, request)
    ground = _partition_parts(entries, joint_state, request, layout.part_names())
    free = tuple(request.free)
    variables = _transform_variables(free, request.box)

    def _moved(parts: Sequence[str]) -> set[str]:
        return {part for part in parts if part in set(free)}

    problem = _extract(
        resolver,
        entries,
        tuple(ConstraintTarget(constraint_id) for constraint_id in request.constraints),
        variables,
        _moved,
        constraint_state.active,
    )
    pivots = _pivots(resolver, free)
    model = _TransformModel(problem.terms, problem.specs, problem.variables, free, pivots)
    policy = (
        WeightPolicy.unit_scaled_v1(problem.characteristic_radius_mm)
        if request.weighting == "unit_scaled_v1"
        else WeightPolicy.declared(
            mm=cast("tuple[float, float]", request.weights)[0],
            deg=cast("tuple[float, float]", request.weights)[1],
        )
    )
    ceiling = request.ceiling if request.ceiling is not None else solve_iter_max()
    limit = time.monotonic() + solve_timeout_s()
    as_built = [0.0] * len(problem.variables)
    request_json = request.to_json(ground=ground)

    def _measure(iterate: Any) -> _Verified:
        return _remeasure(
            problem=problem,
            entries=set(entries),
            iterate=iterate,
            spec={
                "root": str(layout.root),
                "scratch": str(scratch),
                "space": "transform",
                "transforms": {
                    part: [list(row) for row in rows]
                    for part, rows in model.transforms(iterate.x).items()
                },
                "parts": list(problem.parts),
                "constraints": sorted({*entries, *problem.collateral}),
                "points": [],
            },
        )

    iterates: list[Any] = []
    names = {variable.name for variable in problem.variables}
    stray = sorted(set(request.box or {}) - names)
    if stray:
        # ``SOLVER.md`` §6.3's request-time set is CLOSED, so a bound naming a
        # variable this request does not have reuses ``no_free_variables``
        # rather than inventing a spelling this stage has no mandate for - the
        # ``unknown_joint`` overload of 13A, same rule, and the detail carries
        # the real fact. Dropping the entry silently would be the "nothing
        # silently skipped" failure, and a box nobody applied is a limit a
        # reader would believe was enforced.
        raise InvalidSolveRequest(
            "no_free_variables",
            f"the declared box bounds {', '.join(stray)}, which are not free "
            f"variables of this request (they are named "
            f"'<part>.{'|'.join(TRANSFORM_AXES)}' over the declared free parts)",
            subject=stray[0],
        )
    for start in request.starts:
        unknown = sorted(set(start.values) - names)
        if unknown:
            raise InvalidSolveRequest(
                "no_free_variables",
                f"start {start.id!r} assigns {', '.join(unknown)}, which are not free "
                f"variables of this request (they are named "
                f"'<part>.{'|'.join(TRANSFORM_AXES)}')",
                subject=unknown[0],
            )
        x0 = [float(start.values.get(v.name, 0.0)) for v in problem.variables]
        try:
            iterates.append(
                solve_least_squares(
                    model,
                    x0,
                    policy=policy,
                    tol=request.tol,
                    iteration_ceiling=ceiling,
                    start_id=start.id,
                    deadline=lambda: time.monotonic() > limit,
                )
            )
        except SolveRefused as exc:
            raise _run_refusal_transform(exc, start.id, model, _measure) from exc

    converged = [item for item in iterates if item.termination == "tolerance"]
    if converged:
        candidates = distinct_solutions(converged, problem.variables)
    else:
        candidates = (min(iterates, key=lambda item: item.weighted_inf_norm),)
    if not converged and all(item.termination == "iteration_ceiling" for item in iterates):
        best = _measure(candidates[0])
        raise SolveRunRefusal(
            "iteration_ceiling",
            f"every declared start spent its whole budget of {ceiling} iterations "
            "without reaching tolerance or stationarity. This is a refusal, NOT a "
            "verdict: the budget ran out, so nothing was decided, and giving the "
            "ceiling a verdict spelling would let it be read as an outcome "
            "(core/motion.py:1489-1498)",
            payload={
                "from_start": best.iterate.from_start,
                "iterations": best.iterate.iterations,
                "iteration_ceiling": ceiling,
                "best_iterate": cast("JSONValue", _placement_parts(model, best.iterate)),
                "verified": cast("JSONValue", best.to_json()),
            },
        )

    verified = [_measure(iterate) for iterate in candidates]
    good = [item for item in verified if item.all_satisfied] if converged else []
    verdict, detail, shown = _decide(
        verified=verified,
        good=good,
        iterates=iterates,
        has_constraints=True,
        spellings=_TRANSFORM_SPELLINGS,
    )
    placements = tuple(
        {
            "from_start": item.iterate.from_start,
            "parts": cast("JSONValue", _placement_parts(model, item.iterate)),
            "distance_from_as_built": weighted_distance(item.iterate.x, as_built, model.variables),
            "iterations": item.iterate.iterations,
            "dof_remaining": item.iterate.dof_remaining,
            "bounds_active": list(item.iterate.bounds_active),
            # ``SOLVER.md`` §6.1 verdict 3: all solutions are returned and NONE
            # is chosen. The field is written rather than omitted so the
            # absence of a choice is stated, not inferred from a missing key.
            "chosen": False,
        }
        for item in sorted(
            shown, key=lambda item: weighted_distance(item.iterate.x, as_built, model.variables)
        )
    )
    primary = shown[0]
    solver_core = _transform_solver_core(problem, policy, primary.iterate, request, ceiling, pivots)
    verification: dict[str, JSONValue] = {
        **primary.to_json(),
        "verified_placements": [item.to_json() for item in shown],
    }
    document: dict[str, JSONValue] = {
        "space": "transform",
        "verdict": verdict,
        "detail": detail,
        "request": cast("JSONValue", request_json),
        "provenance": cast("JSONValue", request.provenance.to_json()),
        "solver_core": cast("JSONValue", solver_core),
        "verification": cast("JSONValue", verification),
        "placements": [dict(item) for item in placements],
        "constraint_generation": constraint_state.generation,
        "joint_generation": joint_state.generation,
        "artifact_refs": {
            part: problem.artifact_refs[part] for part in sorted(problem.artifact_refs)
        },
        "toolchain": toolchain_hash(),
        "solver_version": SOLVE_VERSION,
    }
    trace_ref = _store_trace(store, request_json, iterates)
    document["solver_trace_ref"] = trace_ref
    _state, entry = ProposalSet(layout, store).record(document)
    return SolveRecord(
        verdict=verdict,
        space="transform",
        request=request_json,
        solver_core=solver_core,
        verification=verification,
        assignments=(),
        placements=placements,
        proposal_ref=entry.ref,
        proposal_id=entry.id,
        solver_trace_ref=trace_ref,
        constraint_generation=constraint_state.generation,
        joint_generation=joint_state.generation,
        artifact_refs=problem.artifact_refs,
        detail=detail,
    )


def _store_trace(store: OpStore, request: Mapping[str, JSONValue], iterates: Sequence[Any]) -> str:
    """Store every start's per-iteration trace and return its artifact ref.

    ``SOLVER.md`` §9's last sentence, made real: a ``solver_trace_ref``
    (iterates, damping, residual norms) is stored for replay. It is a separate
    content-addressed blob rather than a section of the proposal because of
    what it is — evidence about a RUN. Putting it inside ``solver_core`` would
    fold "how the iteration got there" into a block whose whole claim is about
    the answer; putting it nowhere would leave a normative sentence describing
    machinery that does not exist, which is the drift ``KINEMATICS.md:25-29``
    names.

    Pinned like every other generation document, so a proposal's replay
    evidence cannot be collected out from under it while the proposal itself
    stays readable.
    """
    payload: JSONValue = {
        "kind": _TRACE_KIND,
        "request": dict(request),
        "starts": [
            {
                "from_start": iterate.from_start,
                "termination": iterate.termination,
                "iterations": iterate.iterations,
                "steps": [step.to_json() for step in iterate.trace],
            }
            for iterate in iterates
        ],
    }
    blob = store.blobs.put(canonical_json(payload).encode("utf-8"))
    store.gc.pin(blob)
    record_artifact_kind(store, _TRACE_KIND, blob)
    return make_artifact_ref(_TRACE_KIND, blob)


def _placement_parts(model: _TransformModel, iterate: Any) -> list[JSONValue]:
    """Each free part's proposed transform, as rows AND as a decomposition.

    ``SOLVER.md`` §8: "the record names the part and the transform, decomposed
    into translation (mm) plus axis-angle (axis, degrees) for human legibility,
    and says nothing about which statement to edit". Both forms are carried
    because they answer different questions — the rows are what a verification
    pass places geometry with, the decomposition is what a person reads — and
    neither is a source expression.
    """
    from hephaestus.geom.solve import decompose_rigid

    out: list[JSONValue] = []
    for part, rows in sorted(model.transforms(iterate.x).items()):
        translation, axis, angle = decompose_rigid(rows)
        out.append(
            {
                "part": part,
                "rows": [list(row) for row in rows],
                "translation_mm": list(translation),
                "axis": list(axis),
                "angle_deg": angle,
            }
        )
    return out


def _run_refusal_transform(
    exc: Any, start_id: str, model: _TransformModel, measure: Any
) -> SolveRunRefusal:
    """A :class:`~hephaestus.geom.solve.SolveRefused` carried out with its evidence."""
    from hephaestus.geom.solve import component_values

    payload: dict[str, JSONValue] = {
        "from_start": start_id,
        "detail": cast("JSONValue", dict(exc.detail)),
    }
    if exc.x:
        try:
            partial = _PartialIterate(
                x=tuple(exc.x), values=component_values(model, exc.x), from_start=start_id
            )
            payload["best_iterate"] = cast("JSONValue", _placement_parts(model, partial))
            payload["verified"] = cast("JSONValue", measure(partial).to_json())
        except (SolveUnresolvable, SolveRunRefusal, ValueError):
            # A refusal whose own iterate cannot be evaluated - a non-rigid one,
            # for instance - carries what it has and says nothing it cannot
            # support. Inventing residuals for an iterate the model refuses to
            # place would be the overclaim the refusal exists to avoid.
            payload["verified"] = None
    return SolveRunRefusal(exc.reason, exc.message, payload=payload)


def _transform_solver_core(
    problem: _Problem,
    policy: Any,
    iterate: Any,
    request: PlacementSolveRequest,
    ceiling: int,
    pivots: Mapping[str, Vec3],
) -> dict[str, JSONValue]:
    """The ``solver_core`` block for a transform solve, and why it claims D1.

    ``SOLVER.md`` §9: the tier is a property of a BLOCK and the seam is
    kernel-touched versus not. A 2B iteration is kernel-free **while every
    objective term is analytic**, which here it is by construction — the four
    admitted kinds are exactly the closed-form ones (§3.2), and the three the
    kernel would have to answer are refused at request time with their reasons.
    So this block is D1, conditionally: given identical extracted frames, an
    identical request and the pinned image, its canonical JSON is byte-
    identical across processes.

    The frames and the pivots are recorded INSIDE the block, not upstream of
    it, because the claim is conditional on them: frame extraction is a kernel
    call and is not claimed bit-stable, so a reader comparing two blocks can
    check the condition instead of taking it on faith. No timestamp appears
    here for the same reason.
    """
    return {
        "determinism_tier": "D1",
        "frames": [term.to_json() for term in problem.terms],
        "pivots": {part: list(pivots[part]) for part in sorted(pivots)},
        "variables": [
            {
                "name": variable.name,
                "unit": variable.unit,
                "lower": variable.lower,
                "upper": variable.upper,
            }
            for variable in problem.variables
        ],
        "weights": [
            {"key": spec.key, "unit": spec.unit, "weight": policy.applied(spec)}
            for spec in problem.specs
        ],
        "weighting": policy.mode,
        "characteristic_radius_mm": policy.characteristic_radius_mm,
        "regularization": request.regularization,
        "iteration_ceiling": ceiling,
        "from_start": iterate.from_start,
        "iterations": iterate.iterations,
        "termination": iterate.termination,
        "weighted_inf_norm": iterate.weighted_inf_norm,
        "stationarity": iterate.stationarity,
        "rank": iterate.rank,
        "dof_remaining": iterate.dof_remaining,
        "kappa": iterate.kappa,
        "limits_active": list(iterate.bounds_active),
        "null_basis": [
            {
                "label": direction.label,
                "components": [[name, value] for name, value in direction.components],
            }
            for direction in iterate.null_basis
        ],
        "solver_residuals": [
            {"key": value.key, "measured": value.measured, "within_bound": value.within_bound}
            for value in iterate.values
        ],
        "x": [float(value) for value in iterate.x],
    }


# --------------------------------------------------------------------------
# parameter space (``SOLVER.md`` §2C) — declared ``Param``s, preview builds
#
# The space that costs nothing from §1.2: the variables are bounded, named,
# one-home-each, already inputs to ``input_hashes``, and already settable
# without touching source through transient overrides. So the solver can
# *evaluate* candidates while writing nothing at all — every candidate is a
# preview build (``tool_schema.md:238-240``: a transient-override build
# "create[s] a preview artifact and therefore always return[s] ``current =
# false``"), the current pointer never moves, and no override is persisted.
#
# Its cost is stated as a limitation rather than routed around: **it can only
# reach placements the author parameterised.** A mate nobody made a knob for is
# unreachable, and that unreachability comes back by name
# (``no_free_variable_affects``), never worked around by inventing a transform.


#: How a free parameter is spelled in a request: ``<part>.<param>`` for a
#: part's own ``PARAMS`` and ``hc.<param>`` for ``globals.py``'s — the two
#: spellings a script already uses to READ them (``script_contract.md``
#: §3, §4), so a request names a knob the way the author's own code does.
PARAM_VARIABLE_PATTERN: Final[str] = r"^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$"

#: The left-hand side that means ``globals.py``'s project parameters.
PROJECT_PARAM_PREFIX: Final[str] = "hc"


@dataclass(frozen=True)
class _ParamVariable:
    """One free ``Param``: where it lives, and the box it declared."""

    name: str
    scope: str  # "part" | "project"
    part: str  # "" for project scope
    param: str
    lower: float
    upper: float
    #: True when the declaration is an integer ``Param``. Recorded rather than
    #: acted on: this solver does not round, and a proposal over an integer
    #: knob says so in the record instead of quietly presenting 4.37 as a
    #: count. Applying a proposal is an authoring act either way (§0).
    integral: bool


class _PreviewBuilder:
    """Issues, caches and counts the preview builds one 2C solve consumes.

    Three jobs that must not drift apart, so they are one object:

    * **Every build is a preview.** ``publish_build(preview=True)`` is not a
      hint here — it is clause 46's guarantee, and the rows this object records
      are the evidence for it: each carries the ``current`` flag publication
      actually returned, so "nothing was made current" is a fact a reader can
      check rather than a promise this module makes about itself.
    * **The budget is spent here or nowhere.** ``SOLVE_BUILD_BUDGET``
      (``SOLVER.md`` §10) caps total preview builds across the solve's
      iteration, because a 2C solve is otherwise an unbounded number of kernel
      evaluations. Exhaustion is the named refusal ``build_budget_exhausted``.
    * **Identical inputs are built once.** A finite-difference Jacobian revisits
      the base point, a rejected trial step revisits the point it came from,
      and a part whose parameters this step did not touch has not changed.
      Rebuilding those would spend kernel time to recompute bytes already in
      hand. The cache is per-solve and keyed on the exact override document, so
      it can only ever return the build those inputs produced.
    """

    def __init__(
        self,
        layout: ProjectLayout,
        store: OpStore,
        publisher: Publisher,
        backend: Any,
        *,
        budget: int,
    ) -> None:
        self._layout = layout
        self._store = store
        self._publisher = publisher
        self._backend = backend
        self._budget = budget
        self._cache: dict[str, Any] = {}
        self.issued = 0
        self.rows: list[dict[str, JSONValue]] = []

    @property
    def budget(self) -> int:
        return self._budget

    def build(
        self,
        part: str,
        part_overrides: Mapping[str, float],
        project_overrides: Mapping[str, float],
    ) -> Any:
        """One part at one parameter assignment, as a published PREVIEW build.

        Raises :class:`~hephaestus.geom.solve.SolveRefused` — never a verdict —
        for the two ceilings this can hit: ``build_budget_exhausted`` when the
        §10 cap is reached, and ``unbuildable_parameter_iterate`` carrying the
        build's own §8 error record when a candidate does not build. A
        parameter assignment that produces no geometry is a fact about the
        candidate, and inventing residuals for it would be the overclaim the
        refusal exists to avoid.
        """
        from hephaestus.core.executor.runner import BuildRequest, run_build
        from hephaestus.geom.solve import SolveRefused

        key = canonical_json(
            cast(
                "JSONValue",
                {
                    "part": part,
                    "part_overrides": {k: part_overrides[k] for k in sorted(part_overrides)},
                    "project_overrides": {
                        k: project_overrides[k] for k in sorted(project_overrides)
                    },
                },
            )
        )
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        if self.issued >= self._budget:
            raise SolveRefused(
                "build_budget_exhausted",
                f"this parameter-space solve reached its budget of {self._budget} "
                "preview builds (SOLVER.md §10; override with "
                f"{SOLVE_BUILD_BUDGET_ENV}). This is a refusal, NOT a verdict: the "
                "budget ran out, so nothing was decided, and giving a spent ceiling "
                "a verdict spelling would let it be read as an outcome "
                "(core/motion.py:1489-1498)",
                detail={"budget": self._budget, "builds_issued": self.issued},
            )
        self._publisher.sync_import_state()
        inputs = self._publisher.freeze_inputs(part)
        merged_project: dict[str, int | float | str] = dict(self._layout.manifest.params)
        merged_project.update({name: value for name, value in project_overrides.items()})
        out_dir = self._layout.store_root / "builds" / f"solve-{part}-{uuid.uuid4().hex[:12]}"
        try:
            try:
                build = run_build(
                    BuildRequest(
                        part=part,
                        script=inputs.script,
                        globals_source=inputs.globals_source,
                        part_overrides={name: value for name, value in part_overrides.items()},
                        project_overrides=merged_project,
                        origin="local",
                        imports=dict(inputs.imports),
                        import_errors=dict(inputs.import_errors),
                    ),
                    backend=self._backend,
                    out_dir=out_dir,
                    baseline=self._publisher.baseline_for(part),
                )
            except ValidationError as exc:
                # A candidate whose build DIED rather than reporting an error,
                # and it is the same refusal for the same reason. ``run_build``
                # returns a failed ``BuildResult`` when the *script* raises, and
                # raises ``ValidationError`` when the worker itself exits
                # non-zero or overruns its wall clock — but §6.3's
                # ``unbuildable_parameter_iterate`` is "a candidate whose
                # preview build failed", and both of those are that. The case is
                # real and reachable: a degenerate candidate can build geometry
                # the kernel then refuses to FINGERPRINT (``StdFail_NotDone``
                # out of ``normal_at`` on a zero-radius cylinder's side face),
                # which kills the worker at a seam the script-error path never
                # sees. Letting the raw exception escape would give a NAMED case
                # an unnamed failure, and a solve that dies with an executor
                # error has told the caller nothing about the candidate.
                #
                # ``SandboxDeniedError`` is deliberately NOT caught: it is a
                # ``HephaestusError`` and not a ``ValidationError``, it says the
                # backend is unavailable rather than that this candidate is
                # unbuildable, and dressing an infrastructure refusal as a fact
                # about the geometry is the overclaim this vocabulary exists to
                # prevent. ``publish_build`` below is outside this handler for
                # the same reason: a store that will not record a successful
                # build is not a parameter assignment that produced no geometry.
                self.issued += 1
                self.rows.append(
                    {
                        "part": part,
                        "params": {name: part_overrides[name] for name in sorted(part_overrides)},
                        "project_params": {
                            name: project_overrides[name] for name in sorted(project_overrides)
                        },
                        "status": "error",
                        "current": False,
                        "artifact_ref": "",
                    }
                )
                raise SolveRefused(
                    "unbuildable_parameter_iterate",
                    f"part {part!r} does not build at this candidate's parameters: "
                    f"the build worker itself failed — {exc}",
                    detail={
                        "part": part,
                        "params": {name: part_overrides[name] for name in sorted(part_overrides)},
                        "project_params": {
                            name: project_overrides[name] for name in sorted(project_overrides)
                        },
                        # NOT an §8 ``ErrorRecord``: the worker died before it
                        # could write one, so the fields it would have
                        # attributed — ``line``, ``col``, the frame — are stated
                        # absent rather than invented, and ``source`` says which
                        # seam produced this so a reader never mistakes it for a
                        # script error.
                        "error": {
                            "source": "build_worker",
                            "type": type(exc).__name__,
                            "message": str(exc),
                            "line": None,
                            "col": None,
                        },
                    },
                ) from exc
            self.issued += 1
            # The hc PROJECTION is deliberately not synced. A transient-override
            # build must not touch it (``core/cli.py:266-271``), and a solve that
            # moved the project's live projection would have changed the design
            # while measuring it.
            outcome = self._publisher.publish_build(
                build, op_id=f"heph-solve-{uuid.uuid4().hex}", preview=True
            )
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)
        result = outcome.result
        self.rows.append(
            {
                "part": part,
                "params": {name: part_overrides[name] for name in sorted(part_overrides)},
                "project_params": {
                    name: project_overrides[name] for name in sorted(project_overrides)
                },
                "status": result.status,
                # Clause 46's own field: publication's answer, not ours.
                "current": result.current,
                "artifact_ref": result.artifact_ref or "",
            }
        )
        if result.status != "ok" or result.artifact_ref is None:
            error = result.error
            raise SolveRefused(
                "unbuildable_parameter_iterate",
                f"part {part!r} does not build at this candidate's parameters: "
                + (f"{error.type} at line {error.line}: {error.message}" if error else "no build"),
                detail={
                    "part": part,
                    "params": {name: part_overrides[name] for name in sorted(part_overrides)},
                    "project_params": {
                        name: project_overrides[name] for name in sorted(project_overrides)
                    },
                    "error": cast("JSONValue", error.to_json()) if error else None,
                },
            )
        # A PREVIEW publication stores the §8 ``BuildResult`` and stops there —
        # only a current-pointer flip writes the bundle document. The §7
        # geometry index a tag anchor resolves through lives in that bundle, so
        # it is assembled here from the same build, through publication's own
        # :func:`~hephaestus.core.project_store.publication.build_bundle`.
        # Reading ``record_blob`` instead would hand the resolver a bare result
        # with no namespace, and every tag anchor in a 2C solve would come back
        # ``unaddressable_anchor`` for a tag the build had certainly placed.
        published = PublishedBuild(
            result=result,
            bundle=cast(
                "Mapping[str, JSONValue]",
                build_bundle(build, result, self._publisher.projections.state().audit_revision),
            ),
        )
        self._cache[key] = (published, build.worker_result)
        return self._cache[key]


class _ParamModel:
    """The parameter-space residual model (``SOLVER.md`` §2C).

    Implements :class:`hephaestus.geom.solve.ResidualModel`, and it is the one
    model whose ``evaluate`` touches the kernel: a candidate is a set of
    ``Param`` values, and the only way to learn what geometry they produce is
    to build it. So every evaluation is *a preview build per measured part,
    followed by the ordinary evaluation* — which is exactly what ``SOLVER.md``
    §7.2 says verification does in this space, and exactly why a 2C
    ``solver_core`` block is **D2**: OCP output is not claimed bit-stable
    across environments, so no digit here is byte-reproducible and the record
    says so rather than inheriting 2B's claim.

    The residual rows themselves are the SAME rows the other two spaces build
    (:func:`_term_residuals` over :func:`_frames_of`) for the four analytic
    kinds, so what a ``coincident`` term measures does not depend on which
    space is solving for it. ``fit`` and ``distance`` — admitted here and
    nowhere else (§3.2) — are read straight off the engine's own
    ``ConstraintResidual`` through :func:`~hephaestus.geom.evaluate_residual`
    and reformulated by :func:`~hephaestus.geom.solve.residual_window` /
    :func:`~hephaestus.geom.solve.residual_signed_offset`.
    """

    def __init__(
        self,
        *,
        builder: _PreviewBuilder,
        layout: ProjectLayout,
        store: OpStore,
        publisher: Publisher,
        scratch: Path,
        variables: Sequence[_ParamVariable],
        solve_variables: Sequence[Any],
        entries: Sequence[ConstraintEntry],
        specs: Sequence[Any],
        parts: Sequence[str],
        base_part_params: Mapping[str, Mapping[str, float]],
        base_project_params: Mapping[str, float],
    ) -> None:
        self.builder = builder
        self._layout = layout
        self._store = store
        self._publisher = publisher
        self._scratch = scratch
        self._params = tuple(variables)
        self._variables = tuple(solve_variables)
        self._entries = tuple(entries)
        self._specs = tuple(specs)
        self._parts = tuple(parts)
        self._base_part = {part: dict(values) for part, values in base_part_params.items()}
        self._base_project = dict(base_project_params)
        self._rows: dict[str, tuple[tuple[float, ...], ...]] = {}
        self._frames: dict[str, tuple[_Term, ...]] = {}
        self._refs: dict[str, dict[str, str]] = {}
        #: The lowest-residual assignment any evaluation reached, so a ceiling
        #: refusal can carry "the best iterate" (§6.3) rather than a bare name.
        self.best_x: tuple[float, ...] = ()
        self._best_cost = float("inf")

    @property
    def variables(self) -> tuple[Any, ...]:
        return self._variables

    @property
    def components(self) -> tuple[Any, ...]:
        return self._specs

    @property
    def parts(self) -> tuple[str, ...]:
        return self._parts

    def assignment(self, x: Sequence[float]) -> dict[str, float]:
        """``{variable name: value}`` at one iterate, in declaration order."""
        return {variable.name: float(x[index]) for index, variable in enumerate(self._params)}

    def overrides(self, x: Sequence[float]) -> tuple[dict[str, dict[str, float]], dict[str, float]]:
        """The ``(part overrides, project overrides)`` one iterate builds with.

        The base is what the CURRENT artifacts were built with — each part's
        recorded effective ``params`` and the live ``hc`` projection's values
        for the declared project ``Param``s — so the ``as_built`` start really
        is as built, and a candidate differs from the published design in
        exactly the variables the request declared free and in nothing else.
        """
        part_values = {part: dict(values) for part, values in self._base_part.items()}
        project_values = dict(self._base_project)
        for index, variable in enumerate(self._params):
            if variable.scope == "project":
                project_values[variable.param] = float(x[index])
            else:
                part_values.setdefault(variable.part, {})[variable.param] = float(x[index])
        return part_values, project_values

    def frames(self, x: Sequence[float]) -> tuple[_Term, ...]:
        """The extracted frames at one iterate (empty for the non-analytic kinds)."""
        self.evaluate(x)
        return self._frames[self._key(x)]

    def artifact_refs(self, x: Sequence[float]) -> dict[str, str]:
        """The PREVIEW artifact refs one iterate was measured on."""
        self.evaluate(x)
        return dict(self._refs[self._key(x)])

    @staticmethod
    def _key(x: Sequence[float]) -> str:
        return canonical_json(cast("JSONValue", [float(value) for value in x]))

    def evaluate(self, x: Sequence[float]) -> tuple[tuple[float, ...], ...]:
        """Build every measured part at ``x`` and measure the residual rows."""
        from hephaestus.geom import evaluate_residual
        from hephaestus.geom.solve import residual_signed_offset, residual_window

        key = self._key(x)
        cached = self._rows.get(key)
        if cached is not None:
            return cached
        part_values, project_values = self.overrides(x)
        builds: dict[str, PublishedBuild] = {}
        for part in self._parts:
            published, _worker = self.builder.build(part, part_values.get(part, {}), project_values)
            builds[part] = published
        resolver = AnchorResolver(
            self._layout, self._store, self._publisher, self._scratch, builds=builds
        )
        rows: list[tuple[float, ...]] = []
        terms: list[_Term] = []
        for entry in self._entries:
            if entry.kind in ("fit", "distance"):
                _part_a, shape_a, _ref_a = _locate(resolver, entry.a, field="a")
                _part_b, shape_b, _ref_b = _locate(resolver, entry.b, field="b")
                declared = dict(entry.values)
                residual = evaluate_residual(entry.kind, shape_a, shape_b, declared)
                if entry.kind == "fit":
                    rows.append(
                        residual_window(residual.measured, declared["min_mm"], declared["max_mm"])
                    )
                else:
                    rows.append(residual_signed_offset(residual.measured, declared["value_mm"]))
                continue
            term = _frames_of(resolver, entry)
            terms.append(term)
            placed: _Placed = (
                term.point_a,
                term.dir_a,
                term.u_a,
                term.v_a,
                term.point_b,
                term.dir_b,
            )
            rows.extend(_term_residuals(term, placed))
        out = tuple(rows)
        self._rows[key] = out
        self._frames[key] = tuple(terms)
        self._refs[key] = {part: builds[part].result.artifact_ref or "" for part in sorted(builds)}
        cost = max((abs(value) for row in out for value in row), default=0.0)
        if cost < self._best_cost:
            self._best_cost = cost
            self.best_x = tuple(float(value) for value in x)
        return out

    def jacobian(self, x: Sequence[float]) -> tuple[tuple[float, ...], ...] | None:
        """The finite-difference Jacobian (NW11), at parameter space's own step.

        There is no analytic alternative and the spec does not pretend
        otherwise: a ``Param`` reaches the geometry through a *script*, and
        nothing in this repo differentiates one. The shared driver is used
        rather than a private loop (mission rule 6) so that the step, the box
        clipping and the divisor have exactly one definition — and it is the
        same driver G13B's clause 19 holds the analytic Jacobians against.
        """
        from hephaestus.geom.solve import PARAM_FD_STEP, central_difference_jacobian

        return central_difference_jacobian(self, x, step=PARAM_FD_STEP)


def _param_variables(
    request: PlacementSolveRequest,
    declarations: Mapping[str, Mapping[str, Any]],
    hc_state: Mapping[str, Any],
    known_parts: Sequence[str],
) -> list[_ParamVariable]:
    """The declared free ``Param``s, or ``SOLVER.md`` §6.3's refusals by name.

    ``declarations`` is ``{"hc": {...}} | {part: {...}}`` of the ``Param``
    objects each scope declared, read from the probe build's own
    ``params_declaration`` / ``project_params_declaration`` — the executor's
    answer, never a static parse of the script.

    Three refusals, and the third is the one worth reading twice:

    * ``unknown_param`` — nothing of that name is declared in that scope.
    * ``unknown_param`` again, for a name whose scope cannot be decided:
      ``hc.x`` in a project that also has a *part* called ``hc``. Guessing
      which the author meant would put a variable in a scope they did not
      choose.
    * ``unbounded_param`` — ``globals.py`` holds two kinds of name
      (``script_contract.md`` §4): declared ``Param``s, which are bounded, and
      derived constants, which are not. A derived constant is a real, readable
      ``hc`` name with no ``min``/``max``, so it is exactly "a parameter with
      no declared box" — and §2C requires every 2C variable to sit *strictly
      inside its declared min/max*. Solving over one would be inventing bounds
      the author never wrote, so it is refused by name rather than given a
      default range.
    """
    from hephaestus.core.params import Param

    variables: list[_ParamVariable] = []
    seen: set[str] = set()
    for name in request.free:
        if name in seen:
            raise InvalidSolveRequest(
                "no_free_variables",
                f"parameter {name!r} is declared free twice; a duplicated variable "
                "would contribute its column twice without saying so",
                subject=name,
            )
        seen.add(name)
        if re.match(PARAM_VARIABLE_PATTERN, name) is None:
            raise InvalidSolveRequest(
                "unknown_param",
                f"free variable {name!r} is not a parameter name; parameter space "
                "names a part's own knob '<part>.<param>' or a project one "
                "'hc.<param>', which is how a script already reads them "
                "(script_contract.md §3, §4)",
                subject=name,
            )
        scope_name, _dot, param_name = name.partition(".")
        if scope_name == PROJECT_PARAM_PREFIX and scope_name in known_parts:
            raise InvalidSolveRequest(
                "unknown_param",
                f"variable {name!r} is ambiguous: this project has a part called "
                f"{PROJECT_PARAM_PREFIX!r} as well as the globals namespace that name "
                "means, and guessing which scope the author intended would put a "
                "variable in a scope nobody chose",
                subject=name,
            )
        project_scope = scope_name == PROJECT_PARAM_PREFIX
        if not project_scope and scope_name not in known_parts:
            raise InvalidSolveRequest(
                "unknown_param",
                f"variable {name!r} names part {scope_name!r}, which this project does "
                f"not have (parts: {', '.join(known_parts) or 'none'})",
                subject=name,
            )
        scope_key = PROJECT_PARAM_PREFIX if project_scope else scope_name
        declared = declarations.get(scope_key, {})
        param = cast("Param | None", declared.get(param_name))
        if param is None:
            if project_scope and param_name in hc_state:
                raise InvalidSolveRequest(
                    "unbounded_param",
                    f"{name!r} is a derived constant of globals.py, not a declared "
                    "Param: it has no min/max, and SOLVER.md §2C requires every "
                    "parameter-space variable to stay strictly inside its declared "
                    "bounds. Solving over it would be inventing a range the author "
                    "never wrote — declare it as a Param, or solve for the Params it "
                    "is derived from",
                    subject=name,
                )
            where = "globals.py" if project_scope else f"part {scope_name!r}"
            raise InvalidSolveRequest(
                "unknown_param",
                f"no parameter {param_name!r} is declared by {where} "
                f"(declared: {', '.join(sorted(declared)) or 'none'})",
                subject=name,
            )
        if param.min >= param.max:
            raise InvalidSolveRequest(
                "no_free_variables",
                f"parameter {name!r} declares min == max ({param.min!r}), so its box "
                "is a single point and it is not a free variable at all; a solve over "
                "it would report the start as the answer",
                subject=name,
            )
        variables.append(
            _ParamVariable(
                name=name,
                scope="project" if project_scope else "part",
                part="" if project_scope else scope_name,
                param=param_name,
                lower=float(param.min),
                upper=float(param.max),
                integral=param.type == "int",
            )
        )
    if not variables:
        raise InvalidSolveRequest(
            "no_free_variables",
            "a parameter solve declares at least one free Param; with nothing free "
            "there is no variable to solve for and no placement to propose",
        )
    return variables


def _as_built_parameters(
    layout: ProjectLayout,
    publisher: Publisher,
    builder: _PreviewBuilder,
    parts: Sequence[str],
) -> tuple[
    dict[str, dict[str, float]], dict[str, float], dict[str, Mapping[str, Any]], dict[str, Any]
]:
    """What the CURRENT artifacts were built with, plus the ``Param`` declarations.

    ``SOLVER.md`` §5: ``as_built`` is a genuinely good start, so it has to be
    the values the published geometry actually carries — not the defaults, and
    not a guess. Both halves are read from what the build system already
    recorded rather than re-derived:

    * a part's effective ``params`` come off its own current ``BuildResult``,
      which is the merge of defaults with whatever ``set_params`` persisted;
    * the project's come off the live ``hc`` projection
      (``core/assembly.py``'s ``AssemblyProjection`` sibling), restricted to
      the names ``globals.py`` declares as ``Param``s — the projection also
      carries derived constants, which are ``unbounded_param`` and not
      variables (§2C).

    Both are then passed to every candidate build as explicit overrides, so a
    candidate differs from the published design in the free variables and in
    nothing else — and so every candidate build is a preview, which is the
    property clause 46 rests on.

    Returns ``(part values, project values, declarations, hc projection)``. The
    declarations come from ONE probe build per part: the executor's own answer
    (``params_declaration`` / ``project_params_declaration``), never a static
    parse of the script, because a ``Param`` whose bounds are computed from
    ``hc`` has no static form to parse.
    """
    part_values: dict[str, dict[str, float]] = {}
    for part in parts:
        current = publisher.current_result(part)
        if current is None or current.status != "ok":
            raise SolveUnresolvable(
                "no_current_build",
                f"part {part!r} has no current successful build, so there is no "
                "as-built parameter assignment to start from",
                subject=part,
            )
        part_values[part] = {name: float(value) for name, value in current.params.items()}
    hc_state = dict(publisher.projections.state().hc_state)
    declarations: dict[str, Mapping[str, Any]] = {}
    # One probe with no project override, to learn what globals.py DECLARES.
    # Which names are ``Param``s cannot be known before a build: a ``Param``
    # whose bounds are computed from ``hc`` has no static form to parse.
    _probe, worker = builder.build(parts[0], part_values[parts[0]], {})
    declared_project = _declared_params(worker.get("project_params_declaration"))
    declarations[PROJECT_PARAM_PREFIX] = declared_project
    fallback = {
        name: float(cast("float", value))
        for name, value in cast(
            "Mapping[str, Any]", worker.get("project_effective_params", {})
        ).items()
        if isinstance(value, int | float) and not isinstance(value, bool)
    }
    # The as-built project values: the LIVE hc projection where it has the name
    # (which is where a persisted ``set_params`` override shows up), and the
    # probe's own effective value otherwise. Every one of them is then passed
    # to every candidate build explicitly, which is what makes each candidate a
    # preview AND makes it differ from the published design in the free
    # variables and in nothing else.
    project_values: dict[str, float] = {}
    for name in declared_project:
        live = hc_state.get(name)
        if isinstance(live, int | float) and not isinstance(live, bool):
            project_values[name] = float(live)
        elif name in fallback:
            project_values[name] = fallback[name]
    for part in parts:
        _published, part_worker = builder.build(part, part_values[part], project_values)
        declarations[part] = _declared_params(part_worker.get("params_declaration"))
    return part_values, project_values, declarations, hc_state


def _declared_params(raw: Any) -> dict[str, Any]:
    """``{name: Param}`` from a worker result's declaration block."""
    from hephaestus.core.params import Param

    out: dict[str, Any] = {}
    if not isinstance(raw, dict):
        return out
    for name, entry in cast("Mapping[str, Any]", raw).items():
        if not isinstance(entry, dict):
            continue
        body = cast("Mapping[str, Any]", entry)
        try:
            out[name] = Param(
                default=cast("float", body["default"]),
                min=cast("float", body["min"]),
                max=cast("float", body["max"]),
                doc=str(body.get("doc", "")),
                step=cast("float | None", body.get("step")),
            )
        except (KeyError, ValidationError):  # pragma: no cover - our own JSON
            continue
    return out


def _param_values_json(
    model: _ParamModel, iterate: Any, variables: Sequence[_ParamVariable]
) -> list[JSONValue]:
    """One returned solution's parameter values, each beside the box it declared.

    ``SOLVER.md`` §8's "the record names the part and the transform ... and says
    nothing about which statement to edit", in parameter space's own
    coordinates: the record names the ``Param`` and the value. It still says
    nothing about which statement to edit — a ``Param`` value is applied
    through ``set_params``, or by editing the declaration, and which of those
    the author meant is an authoring decision Stage 13 refuses to guess.
    """
    assignment = model.assignment(iterate.x)
    out: list[JSONValue] = []
    for variable in variables:
        out.append(
            {
                "name": variable.name,
                "scope": variable.scope,
                "part": variable.part,
                "param": variable.param,
                "value": assignment[variable.name],
                "min": variable.lower,
                "max": variable.upper,
                # An integer Param whose proposal is fractional says so rather
                # than being rounded: rounding would be the solver choosing a
                # value it did not verify.
                "integral": variable.integral,
            }
        )
    return out


def _run_refusal_param(
    exc: Any, start_id: str, model: _ParamModel, variables: Sequence[_ParamVariable], measure: Any
) -> SolveRunRefusal:
    """A :class:`~hephaestus.geom.solve.SolveRefused` carried out with its evidence.

    ``SOLVER.md`` §6.3: a run-time refusal carries "the best iterate and its
    independently re-measured residuals", never a bare name. The best iterate
    is the lowest-residual assignment any evaluation actually reached — which,
    for ``build_budget_exhausted``, is the whole point: the budget ran out, and
    what the solve had got to by then is the evidence it owes the caller.
    """
    from hephaestus.geom.solve import component_values

    payload: dict[str, JSONValue] = {
        "from_start": start_id,
        "detail": cast("JSONValue", dict(exc.detail)),
        "builds_issued": model.builder.issued,
        "build_budget": model.builder.budget,
    }
    best = tuple(exc.x) or model.best_x
    if best:
        try:
            partial = _PartialIterate(
                x=best, values=component_values(model, best), from_start=start_id
            )
            payload["best_iterate"] = cast(
                "JSONValue", _param_values_json(model, partial, variables)
            )
            payload["verified"] = cast("JSONValue", measure(partial).to_json())
        except (SolveUnresolvable, SolveRunRefusal, ValueError):
            # An iterate whose own evaluation cannot be completed carries what
            # it has and says nothing it cannot support.
            payload["verified"] = None
    return SolveRunRefusal(exc.reason, exc.message, payload=payload)


def _param_solver_core(
    model: _ParamModel,
    problem: _Problem,
    policy: Any,
    iterate: Any,
    request: PlacementSolveRequest,
    ceiling: int,
    variables: Sequence[_ParamVariable],
) -> dict[str, JSONValue]:
    """The ``solver_core`` block for a parameter solve, and why it claims **D2**.

    ``SOLVER.md`` §9 makes the tier a property of a BLOCK and puts the seam at
    kernel-touched versus not. A 2C iteration is kernel-touched by
    construction — *each iterate is a preview build* — and OCP boolean output
    is not claimed bit-stable across environments, so this block claims no
    byte-identity at all. The constant is written out rather than inherited
    from the transform-space writer for exactly that reason: 13A's block says
    ``"D1"`` unconditionally and is right to in pose space, and a shared
    helper would have made this one silently wrong.

    What IS reproducible here is what §9's D2 list names and what the gate
    binds to: the verdict spelling, the independently re-measured residuals
    within tolerance and on the same side of it with identical ``satisfied``
    flags, the active bounds and ``dof_remaining``, and the bound input refs.
    The digits are not, and nothing here claims they are.
    """
    return {
        "determinism_tier": "D2",
        # Frames at the RETURNED iterate rather than at the start: in this
        # space the geometry itself moved, so "the frames the iteration
        # consumed" is not one set. Recording the returned one keeps the block
        # about the answer, and the block claims nothing byte-stable about
        # them either.
        "frames": [term.to_json() for term in model.frames(iterate.x)],
        "variables": [
            {
                "name": variable.name,
                "unit": variable.unit,
                "lower": variable.lower,
                "upper": variable.upper,
            }
            for variable in problem.variables
        ],
        "weights": [
            {"key": spec.key, "unit": spec.unit, "weight": policy.applied(spec)}
            for spec in problem.specs
        ],
        "weighting": policy.mode,
        "characteristic_radius_mm": policy.characteristic_radius_mm,
        "regularization": request.regularization,
        "iteration_ceiling": ceiling,
        "from_start": iterate.from_start,
        "iterations": iterate.iterations,
        "termination": iterate.termination,
        "weighted_inf_norm": iterate.weighted_inf_norm,
        "stationarity": iterate.stationarity,
        "rank": iterate.rank,
        "dof_remaining": iterate.dof_remaining,
        "kappa": iterate.kappa,
        "limits_active": list(iterate.bounds_active),
        "null_basis": [
            {
                "label": direction.label,
                "components": [[name, value] for name, value in direction.components],
            }
            for direction in iterate.null_basis
        ],
        "solver_residuals": [
            {"key": value.key, "measured": value.measured, "within_bound": value.within_bound}
            for value in iterate.values
        ],
        "x": [float(value) for value in iterate.x],
        # Clause 46's evidence, on the solver's side: every build this solve
        # issued, with the ``current`` flag publication returned for it.
        "preview_builds": [dict(row) for row in model.builder.rows],
        "builds_issued": model.builder.issued,
        "build_budget": model.builder.budget,
    }


def _propose_params_in(
    layout: ProjectLayout,
    store: OpStore,
    request: PlacementSolveRequest,
    scratch: Path,
    backend: Any | None = None,
) -> SolveRecord:
    """The whole §2 pipeline in parameter space, inside one scratch directory.

    The order is forced by what each step needs and every step is named:

    1. Resolve the requested constraints (``unknown_constraint``,
       ``withdrawn_constraint``, ``not_an_objective_kind`` — 2C's table, which
       admits ``fit`` and ``distance`` and still refuses the two plateau kinds).
    2. Read the as-built parameter assignment and the ``Param`` declarations off
       one probe build per measured part (:func:`_as_built_parameters`).
    3. Decide the free variables (``unknown_param``, ``unbounded_param``).
    4. Extract the objective components and the as-built frames.
    5. Probe sensitivity — ``no_free_variable_affects`` for a constraint no free
       parameter moves and that does not already hold (§2C).
    6. Iterate, verify in another process, decide, record.

    Step 2 issues preview builds before step 3's refusals can fire, and that is
    worth saying out loud rather than leaving to be discovered: a ``Param``'s
    bounds are the executor's answer, not a static fact about the script, so
    ``unknown_param`` cannot be decided without a build. "Nothing written"
    still holds where it matters — no proposal, no generation, no current
    pointer, no persisted override — and a preview build is exactly the
    write-nothing evaluation §2C is built on.
    """
    from hephaestus.core.executor.sandbox.probe import cached_probe, secure_backend
    from hephaestus.core.hashing import toolchain_hash
    from hephaestus.core.project_store.kinematics import JointSet
    from hephaestus.core.project_store.proposals import ProposalSet
    from hephaestus.geom.solve import (
        SENSITIVITY_EPS,
        SOLVE_VERSION,
        SolveRefused,
        SolveVariable,
        WeightPolicy,
        distinct_solutions,
        insensitive_sources,
        solve_least_squares,
        weighted_distance,
    )

    publisher = Publisher(layout, store)
    joint_state = JointSet(layout, store).state()
    constraint_state = ConstraintSet(layout, store).state()
    entries = _placement_entries(constraint_state, request)
    measured_parts = tuple(sorted({part for entry in entries.values() for part in entry.parts}))
    unknown = sorted(set(measured_parts) - set(layout.part_names()))
    if unknown:
        raise SolveUnresolvable(
            "missing_part",
            f"no part {unknown[0]!r} in this project (parts: {', '.join(layout.part_names())})",
            subject=unknown[0],
        )
    if backend is None:
        backend = secure_backend(layout.store_root)
        cached_probe(layout.store_root, backend)
    budget = request.build_budget if request.build_budget is not None else solve_build_budget()
    builder = _PreviewBuilder(layout, store, publisher, backend, budget=budget)

    # The parts to PROBE are the measured ones plus any part a free variable
    # names, which need not overlap. A free variable on a part no requested
    # constraint anchors is a legitimate request with a knowable answer — its
    # Jacobian column is all zero, so the constraint is unreachable from it and
    # `no_free_variable_affects` says so by name. Refusing it `unknown_param`
    # because its declaration was never read would blame the request for the
    # order this function happens to work in. Probed, never ITERATED on: only
    # the measured parts are rebuilt per candidate.
    named_parts = {
        name.partition(".")[0]
        for name in request.free
        if name.partition(".")[0] in set(layout.part_names())
    }
    probe_parts = tuple(sorted(set(measured_parts) | named_parts))
    try:
        base_part, base_project, declarations, hc_state = _as_built_parameters(
            layout, publisher, builder, probe_parts
        )
    except SolveRefused as exc:
        raise SolveUnresolvable(
            "no_current_build"
            if exc.reason == "unbuildable_parameter_iterate"
            else "shape_refused",
            f"the project does not build at its own as-built parameters: {exc.message}",
        ) from exc
    variables = _param_variables(request, declarations, hc_state, layout.part_names())
    solve_variables = [
        SolveVariable(
            name=variable.name,
            # A ``Param`` declares no unit (``script_contract.md`` §3 is
            # ``default``/``min``/``max``/``doc``/``step``), so claiming one
            # here would be inventing a fact. ``"param"`` says exactly that:
            # the variable is in its own declared numeric scale, and the
            # weighting §3.4 applies is per RESIDUAL COMPONENT anyway, where
            # the units are the engine's mm and deg.
            unit="param",
            lower=variable.lower,
            upper=variable.upper,
        )
        for variable in variables
    ]
    ordered = [entries[constraint_id] for constraint_id in request.constraints]
    specs = [spec for entry in ordered for spec in component_specs(entry)]

    as_built = [
        (base_project if variable.scope == "project" else base_part.get(variable.part, {})).get(
            variable.param, 0.0
        )
        for variable in variables
    ]
    model = _ParamModel(
        builder=builder,
        layout=layout,
        store=store,
        publisher=publisher,
        scratch=scratch,
        variables=variables,
        solve_variables=solve_variables,
        entries=ordered,
        specs=specs,
        parts=measured_parts,
        base_part_params=base_part,
        base_project_params=base_project,
    )
    # The as-built frames, for the characteristic radius and for §7.3's
    # collateral set: the constraints this solve does NOT steer on but does
    # evaluate at whatever solution it reaches.
    current_refs: dict[str, str] = {}
    for part in measured_parts:
        current = publisher.current_result(part)
        current_refs[part] = "" if current is None else (current.artifact_ref or "")
    radius = _param_characteristic_radius(model, as_built, scratch, layout, store, publisher)
    named = set(entries)
    collateral = tuple(
        sorted(
            entry.id
            for entry in constraint_state.active
            if entry.id not in named and set(entry.parts) & set(measured_parts) and not entry.poses
        )
    )
    problem = _Problem(
        terms=(),
        specs=tuple(specs),
        variables=tuple(solve_variables),
        parts=measured_parts,
        characteristic_radius_mm=radius,
        artifact_refs=current_refs,
        entries=dict(entries),
        collateral=collateral,
    )
    policy = (
        WeightPolicy.unit_scaled_v1(radius)
        if request.weighting == "unit_scaled_v1"
        else WeightPolicy.declared(
            mm=cast("tuple[float, float]", request.weights)[0],
            deg=cast("tuple[float, float]", request.weights)[1],
        )
    )
    ceiling = request.ceiling if request.ceiling is not None else solve_iter_max()
    limit = time.monotonic() + solve_timeout_s()
    request_json = request.to_json(ground=())
    nonsmooth = tuple(sorted(entry.id for entry in ordered if entry.kind == "distance"))

    def _measure(iterate: Any) -> _Verified:
        part_values, project_values = model.overrides(iterate.x)
        return _remeasure(
            problem=problem,
            entries=set(entries),
            iterate=iterate,
            spec={
                "root": str(layout.root),
                "scratch": str(scratch),
                "space": "parameters",
                "part_overrides": {
                    part: dict(values) for part, values in sorted(part_values.items())
                },
                "project_overrides": dict(project_values),
                "parts": list(measured_parts),
                "constraints": sorted({*entries, *collateral}),
                "points": [],
            },
        )

    # §2C's own limitation, named: a constraint no free parameter moves and
    # that does not already hold is UNREACHABLE from these knobs, and saying so
    # beats iterating to a floor and blaming the geometry.
    try:
        # The BASE point first, and the order is load-bearing rather than
        # stylistic. §6.3 says a run-time refusal carries "the best iterate and
        # its independently re-measured residuals", and ``model.best_x`` — the
        # only thing such a refusal can carry — is recorded by ``evaluate``,
        # never by a probe that raised. Every build this call needs is already
        # in the builder's cache from :func:`_as_built_parameters`, so it costs
        # nothing; deriving the Jacobian first spent the whole budget on
        # probes and left ``build_budget_exhausted`` with no iterate to show,
        # which is the bare name §6.3 exists to forbid.
        base_values = model.evaluate(as_built)
        base_rows = model.jacobian(as_built) or ()
    except SolveRefused as exc:
        raise _run_refusal_param(exc, "as_built", model, variables, _measure) from exc
    from hephaestus.geom.solve import component_values as _component_values

    flat = insensitive_sources(
        specs, base_rows, _component_values(model, as_built), eps=SENSITIVITY_EPS
    )
    if flat:
        raise SolveUnresolvable(
            "no_free_variable_affects",
            f"constraint(s) {', '.join(flat)} are not satisfied and no declared free "
            f"parameter moves them (below SENSITIVITY_EPS = {SENSITIVITY_EPS}). "
            "Parameter space can only reach placements the author parameterised, and "
            "a mate nobody made a knob for is unreachable — reported by name rather "
            "than worked around by inventing a transform (SOLVER.md §2C)",
            subject=flat[0],
        )
    _ = base_values

    iterates: list[Any] = []
    names = {variable.name for variable in variables}
    for start in request.starts:
        stray = sorted(set(start.values) - names)
        if stray:
            raise InvalidSolveRequest(
                "unknown_param",
                f"start {start.id!r} assigns {', '.join(stray)}, which are not free "
                "variables of this request",
                subject=stray[0],
            )
        x0 = [
            float(start.values.get(variable.name, as_built[index]))
            for index, variable in enumerate(variables)
        ]
        outside = [
            variable.name
            for index, variable in enumerate(variables)
            if not (variable.lower <= x0[index] <= variable.upper)
        ]
        if outside:
            raise InvalidSolveRequest(
                "unbounded_param",
                f"start {start.id!r} places {', '.join(sorted(outside))} outside its "
                "declared min/max; §2C requires every parameter-space variable to stay "
                "strictly inside the bounds the author wrote, at the start as much as "
                "at the answer",
                subject=sorted(outside)[0],
            )
        try:
            iterates.append(
                solve_least_squares(
                    model,
                    x0,
                    policy=policy,
                    tol=request.tol,
                    iteration_ceiling=ceiling,
                    start_id=start.id,
                    deadline=lambda: time.monotonic() > limit,
                )
            )
        except SolveRefused as exc:
            raise _run_refusal_param(exc, start.id, model, variables, _measure) from exc

    converged = [item for item in iterates if item.termination == "tolerance"]
    if converged:
        candidates = distinct_solutions(converged, problem.variables)
    else:
        candidates = (min(iterates, key=lambda item: item.weighted_inf_norm),)
    if not converged and all(item.termination == "iteration_ceiling" for item in iterates):
        best = _measure(candidates[0])
        raise SolveRunRefusal(
            "iteration_ceiling",
            f"every declared start spent its whole budget of {ceiling} iterations "
            "without reaching tolerance or stationarity. This is a refusal, NOT a "
            "verdict: the budget ran out, so nothing was decided",
            payload={
                "from_start": best.iterate.from_start,
                "iterations": best.iterate.iterations,
                "iteration_ceiling": ceiling,
                "best_iterate": cast(
                    "JSONValue", _param_values_json(model, best.iterate, variables)
                ),
                "verified": cast("JSONValue", best.to_json()),
            },
        )

    verified = [_measure(iterate) for iterate in candidates]
    good = [item for item in verified if item.all_satisfied] if converged else []
    verdict, detail, shown = _decide(
        verified=verified,
        good=good,
        iterates=iterates,
        has_constraints=True,
        spellings=_TRANSFORM_SPELLINGS,
    )
    placements = tuple(
        {
            "from_start": item.iterate.from_start,
            "parameters": cast("JSONValue", _param_values_json(model, item.iterate, variables)),
            "distance_from_as_built": weighted_distance(item.iterate.x, as_built, model.variables),
            "iterations": item.iterate.iterations,
            "dof_remaining": item.iterate.dof_remaining,
            "bounds_active": list(item.iterate.bounds_active),
            "chosen": False,
        }
        for item in sorted(
            shown, key=lambda item: weighted_distance(item.iterate.x, as_built, model.variables)
        )
    )
    primary = shown[0]
    solver_core = _param_solver_core(
        model, problem, policy, primary.iterate, request, ceiling, variables
    )
    verification: dict[str, JSONValue] = {
        **primary.to_json(),
        "verified_placements": [item.to_json() for item in shown],
    }
    document: dict[str, JSONValue] = {
        "space": "parameters",
        "verdict": verdict,
        "detail": detail,
        "request": cast("JSONValue", request_json),
        "provenance": cast("JSONValue", request.provenance.to_json()),
        "solver_core": cast("JSONValue", solver_core),
        "verification": cast("JSONValue", verification),
        "placements": [dict(item) for item in placements],
        "nonsmooth_terms": list(nonsmooth),
        "constraint_generation": constraint_state.generation,
        "joint_generation": joint_state.generation,
        "artifact_refs": {part: current_refs[part] for part in sorted(current_refs)},
        "toolchain": toolchain_hash(),
        "solver_version": SOLVE_VERSION,
    }
    if nonsmooth:
        document["nonsmooth_caveat"] = NONSMOOTH_CAVEAT
    trace_ref = _store_trace(store, request_json, iterates)
    document["solver_trace_ref"] = trace_ref
    _state, entry = ProposalSet(layout, store).record(document)
    return SolveRecord(
        verdict=verdict,
        space="parameters",
        request=request_json,
        solver_core=solver_core,
        verification=verification,
        assignments=(),
        placements=placements,
        nonsmooth_terms=nonsmooth,
        proposal_ref=entry.ref,
        proposal_id=entry.id,
        solver_trace_ref=trace_ref,
        constraint_generation=constraint_state.generation,
        joint_generation=joint_state.generation,
        artifact_refs=current_refs,
        detail=detail,
    )


def _param_characteristic_radius(
    model: _ParamModel,
    x: Sequence[float],
    scratch: Path,
    layout: ProjectLayout,
    store: OpStore,
    publisher: Publisher,
) -> float:
    """``unit_scaled_v1``'s radius over the parts this solve measures.

    The same bounding-box centre-to-corner number §3.4 defines, taken on the
    as-built preview geometry rather than on the current artifacts, because
    that is the geometry the solve's first residual was measured on and a
    weight derived from different geometry than the residual it weights would
    be a silent normalization of exactly the kind ``COMPARE.md:34-36`` refuses.
    """
    builds: dict[str, PublishedBuild] = {}
    part_values, project_values = model.overrides(x)
    for part in model.parts:
        published, _worker = model.builder.build(part, part_values.get(part, {}), project_values)
        builds[part] = published
    resolver = AnchorResolver(layout, store, publisher, scratch, builds=builds)
    return _characteristic_radius(resolver, set(model.parts))
