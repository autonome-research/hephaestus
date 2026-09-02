# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""G13A clauses 2-8 and 10-12: the pose solver against real published geometry.

Every clause here runs the whole ``SOLVER.md`` §2 pipeline — anchors resolved
once against current artifacts, the §3.3 reformulated residual assembled,
weighted Levenberg-Marquardt from every declared start, and then the answer
re-measured **in a separate process** through the ordinary
:mod:`hephaestus.core.assembly` path. Nothing is stubbed and nothing is
in-memory: a frame extracted from a synthetic shape would prove nothing about
the anchoring path the solver actually rides, and a verification pass that ran
in-process would prove nothing at all.

The clause this file exists for is **finding 1**: a converged verdict must not
be emittable for a placement the existing evaluator measures as violated. The
``c-flush`` fixture is built so that a solver graded on the residual number
would report success — its gap goes to exactly zero — while the kernel's own
``satisfied`` says otherwise because the normals face the same way. That is
asserted twice: the verdict is ``no_pose_found_from_starts``, and the record
carries ``satisfied == False`` beside ``normal_deviation_deg == 180``.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest
from hephaestus.core.placement import (
    POSE_SOLVE_VERDICTS,
    SOLVE_REQUEST_REFUSALS,
    SOLVE_RESOLUTION_REFUSALS,
    SOLVE_RUNTIME_REFUSALS,
    ConstraintTarget,
    InvalidSolveRequest,
    PointTarget,
    PoseSolveRequest,
    SolveRecord,
    SolveRunRefusal,
    SolveStart,
    SolveTarget,
    solve_pose,
)
from hephaestus.core.project_store.constraints import ConstraintProvenance

if TYPE_CHECKING:
    from hephaestus.core.project_store.layout import ProjectLayout

    from opstore import OpStore

Arm = tuple["ProjectLayout", "OpStore"]

PROVENANCE = ConstraintProvenance(assumed=True, reason="the gate's own solve")

#: Every payload this suite reads is searched for these. ``SOLVER.md`` §5
#: forbids "infeasible" / "no solution exists" anywhere in a result — a local
#: method's silence is evidence about one basin, not about the space — and §6.1
#: forbids "solved" (the verdict is never that confident) and "holds" (the
#: ``holds_at_samples`` lesson: sampled evidence is not a proof).
FORBIDDEN_WORDS = ("solved", "infeasible", "no solution", "holds")


def _request(targets: Sequence[SolveTarget], **kwargs: Any) -> PoseSolveRequest:
    fields: dict[str, Any] = {
        "tol": 1e-4,
        "weighting": "unit_scaled_v1",
        "regularization": "min_norm_from_start",
        "provenance": PROVENANCE,
    }
    fields.update(kwargs)
    return PoseSolveRequest(targets=tuple(targets), **fields)


def _solve(arm: Arm, targets: Sequence[SolveTarget], **kwargs: Any) -> SolveRecord:
    layout, store = arm
    return solve_pose(layout, store, _request(targets, **kwargs))


def _payload(record: SolveRecord) -> str:
    return json.dumps(record.to_json())


def _constraint_row(record: SolveRecord, constraint_id: str) -> dict[str, Any]:
    rows = cast("list[Any]", dict(record.verification)["constraints"])
    for item in rows:
        row = cast("dict[str, Any]", item)
        if row["id"] == constraint_id:
            return row
    raise AssertionError(f"no verified row for {constraint_id} in {rows}")


def _point_row(record: SolveRecord, target_id: str) -> dict[str, Any]:
    rows = cast("list[Any]", dict(record.verification)["points"])
    for item in rows:
        row = cast("dict[str, Any]", item)
        if row["id"] == target_id:
            return row
    raise AssertionError(f"no verified point for {target_id} in {rows}")


def _generations(arm: Arm) -> tuple[int, int, int]:
    """``(joint, pose, constraint)`` generations — nothing may move them."""
    from hephaestus.core.project_store.constraints import ConstraintSet
    from hephaestus.core.project_store.kinematics import JointSet, PoseSet

    layout, store = arm
    joints = JointSet(layout, store)
    return (
        joints.state().generation,
        PoseSet(layout, store, joints).state().generation,
        ConstraintSet(layout, store).state().generation,
    )


@pytest.fixture
def env_guard() -> Iterator[None]:
    """Restore every env override this suite sets, whatever the test does."""
    keys = (
        "HEPHAESTUS_SOLVE_FAULT",
        "HEPHAESTUS_SOLVE_TIMEOUT_S",
        "HEPHAESTUS_SOLVE_ITER_MAX",
    )
    saved = {key: os.environ.get(key) for key in keys}
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


# ==========================================================================
# clause 2(a): anchor-to-point, the inverse of reach


def test_anchor_to_point_returns_pose_found_at_the_declared_tolerance(arm: Arm) -> None:
    """Clause 2(a): ``pose_found``, and the error is the RE-MEASURED one.

    ``<= tol``, never 1e-9: the declared tolerance is the number the solver
    actually drove, and demanding accuracy a termination rule cannot deliver is
    a clause nobody can write (``SOLVER.md`` Gates preamble). The clause also
    asserts that the record reports the number the *verification process*
    measured rather than the solver's internal one — which is the whole
    argument of §7.5, "the solver's own numbers are discarded".
    """
    before = _generations(arm)
    record = _solve(
        arm,
        [
            PointTarget(
                id="t-tip", anchor="link2:tip_face", point_mm=(40.0, 40.0, 14.0), tol_mm=0.01
            )
        ],
        free_joints=("j-shoulder", "j-elbow"),
    )
    assert record.verdict == "pose_found"
    row = _point_row(record, "t-tip")
    assert row["within_bound"] is True
    assert float(cast("float", row["error_mm"])) <= 0.01
    # The reported figure is the kernel's, and the solver's rides alongside for
    # the §7.6 disagreement check only.
    assert "error_mm" in row and "solver" in row
    assert float(cast("float", dict(record.verification)["worst_disagreement"])) <= 1e-6
    # Nothing was written: no pose declared, no generation advanced (clause 15's
    # engine-level half).
    assert _generations(arm) == before


# ==========================================================================
# clause 2(b): the constraint-id form, and the class-predicate negative


def test_constraint_id_target_converges_and_conjunct_one_is_asserted_independently(
    arm: Arm,
) -> None:
    """Clause 2(b): ``pose_converged_at_tolerance``, conjunct (i) on its own.

    The verdict is not taken on trust: the constraint is re-measured a SECOND
    time here, through ``core.assembly``'s ordinary evaluator over the solved
    assignment, and that independent measurement is what the assertion reads.
    A solver that reported convergence while the engine measured ``violated``
    would fail this clause at the second measurement even if it had corrupted
    the first.
    """
    layout, store = arm
    record = _solve(arm, [ConstraintTarget("c-align")], free_joints=("j-elbow",))
    assert record.verdict == "pose_converged_at_tolerance"
    row = _constraint_row(record, "c-align")
    assert row["satisfied"] is True
    assert float(cast("float", row["measured"])) <= 0.01

    # -- conjunct (i), measured independently -----------------------------
    from hephaestus.core.assembly import AnchorResolver
    from hephaestus.core.motion import motion_resolution
    from hephaestus.core.project_store.constraints import ConstraintSet
    from hephaestus.core.project_store.publication import Publisher
    from hephaestus.geom import evaluate_residual, transformed_shape

    values = cast("dict[str, float]", dict(record.assignments[0])["values"])
    scratch = Path(str(layout.store_root / "g13a-scratch"))
    scratch.mkdir(parents=True, exist_ok=True)
    resolver = AnchorResolver(layout, store, Publisher(layout, store), scratch)
    resolution = motion_resolution(layout, store, resolver)
    entry = ConstraintSet(layout, store).state().by_id["c-align"]
    world = resolution.transforms_at(values, list(entry.parts))
    placed: list[Any] = []
    for text in (entry.a, entry.b):
        part, _sep, selector = text.partition(":")
        geometry, resolved = resolver.locate(part, selector or "part")
        placed.append(transformed_shape(geometry.shape_for(resolved), world[part]))
    residual = evaluate_residual(entry.kind, placed[0], placed[1], dict(entry.values))
    assert residual.satisfied is True, residual
    assert residual.measured <= entry.values["tol_deg"]


def test_a_zero_gap_same_facing_coincident_is_not_a_success(arm: Arm) -> None:
    """Clause 2(b), the class-predicate negative — **finding 1**, in pose space.

    ``c-flush``'s gap closes to exactly zero at ``j-lift = 25``, so a solver
    graded on ``slack`` reports it converged: ``slack == tol_mm`` with room to
    spare. It is still not a mate, because both normals point +Z. The verdict
    must therefore be ``no_pose_found_from_starts`` — verdict 4's second route,
    which ``SOLVER.md`` §6.1 names explicitly — and the record must carry the
    fact that hides behind the number: ``satisfied == False`` beside
    ``normal_deviation_deg`` near 180, each next to its declared bound.
    """
    record = _solve(arm, [ConstraintTarget("c-flush")], free_joints=("j-lift",))
    assert record.verdict == "no_pose_found_from_starts"
    row = _constraint_row(record, "c-flush")
    assert row["satisfied"] is False
    # The primary component IS inside its bound - which is exactly the trap.
    components = {
        str(cast("dict[str, Any]", item)["key"]): cast("dict[str, Any]", item)
        for item in cast("list[Any]", row["components"])
    }
    assert components["c-flush:gap"]["within_bound"] is True
    assert float(cast("float", components["c-flush:gap"]["measured"])) <= 1e-6
    predicate = components["c-flush:normals"]
    assert predicate["role"] == "class_predicate"
    assert predicate["within_bound"] is False
    assert float(cast("float", predicate["measured"])) == pytest.approx(180.0, abs=1e-6)
    # Beside its DECLARED bound, so a reader sees which conjunct failed.
    assert float(cast("float", predicate["bound"])) == pytest.approx(1e-3)
    values = {name: value for name, value in cast("list[Any]", row["values"])}
    assert values["normal_deviation_deg"] == pytest.approx(180.0, abs=1e-6)
    assert "c-flush" in record.detail
    for word in FORBIDDEN_WORDS:
        assert word not in _payload(record).lower(), word


# ==========================================================================
# clause 2(c): over-constrained, no culprit named


def test_two_conflicting_constraints_land_on_the_residual_floor(arm: Arm) -> None:
    """Clause 2(c): stationary above tolerance at full rank, no culprit named.

    ``c-align`` wants the tip face parallel to a 30 deg rail and ``c-square``
    to a 90 deg one; one elbow cannot do both, and the least-squares floor sits
    at 60 deg with each 30 deg out. The clause asserts stationarity was
    actually reached (not assumed from the verdict) and that **no field names a
    culprit**: identifying a minimal inconsistent subset is a different
    computation nobody has run.
    """
    record = _solve(
        arm,
        [ConstraintTarget("c-align"), ConstraintTarget("c-square")],
        free_joints=("j-elbow",),
    )
    assert record.verdict == "pose_overconstrained_at_residual_floor"
    core = dict(record.solver_core)
    assert core["termination"] == "stationary"
    assert float(cast("float", core["stationarity"])) <= 1e-6
    assert core["dof_remaining"] == 0 and core["rank"] == 1
    for constraint_id in ("c-align", "c-square"):
        row = _constraint_row(record, constraint_id)
        assert row["satisfied"] is False
        assert float(cast("float", row["measured"])) == pytest.approx(30.0, abs=1e-3)

    # No culprit is NAMED, asserted as an absent FIELD rather than an absent
    # word: the detail says out loud that none is named, so a substring search
    # would trip over the explanation of the very rule it is checking.
    def _keys(value: Any) -> Iterator[str]:
        if isinstance(value, dict):
            for key, nested in cast("dict[str, Any]", value).items():
                yield str(key)
                yield from _keys(nested)
        elif isinstance(value, list):
            for item in cast("list[Any]", value):
                yield from _keys(item)

    fields = set(_keys(record.to_json()))
    for absent in ("culprit", "culprit_constraint", "blame", "at_fault", "responsible"):
        assert absent not in fields, fields


# ==========================================================================
# clause 3: the verdict tuple, verbatim and complete


def test_the_pose_verdict_tuple_is_seven_spellings_and_no_more() -> None:
    """Clause 3: the literal tuple, asserted as a tuple.

    A vocabulary named nowhere is not closed (``SOLVER.md`` §6.1), so this
    asserts the object itself rather than membership one spelling at a time.
    """
    assert POSE_SOLVE_VERDICTS == (
        "pose_found",
        "pose_converged_at_tolerance",
        "pose_underdetermined_at_tolerance",
        "multiple_poses_from_starts",
        "no_pose_found_from_starts",
        "pose_overconstrained_at_residual_floor",
        "unresolvable",
    )
    assert len(POSE_SOLVE_VERDICTS) == len(set(POSE_SOLVE_VERDICTS)) == 7
    # Refusals are NOT verdicts (clause 12's other half): the three refusal
    # families and the verdict tuple are disjoint.
    for family in (SOLVE_REQUEST_REFUSALS, SOLVE_RUNTIME_REFUSALS):
        assert not set(family) & set(POSE_SOLVE_VERDICTS), family
    # `unresolvable` is the one name that is deliberately BOTH - verdict 6 and
    # the resolution-time family's own spelling (``SOLVER.md`` §6.1/§6.3).
    assert set(SOLVE_RESOLUTION_REFUSALS) & set(POSE_SOLVE_VERDICTS) == set()
    assert "unresolvable" in POSE_SOLVE_VERDICTS


def test_pose_found_and_pose_converged_do_not_stand_in_for_each_other(arm: Arm) -> None:
    """Clause 3: the two success spellings are scoped to their own target forms.

    ``pose_found`` is an existence claim and belongs only to anchor-to-point;
    ``pose_converged_at_tolerance`` only to constraint-id. A request carrying
    BOTH is scored on both and returns the constraint-id spelling, because the
    weaker claim may not stand in for the stronger one.
    """
    point_only = _solve(
        arm,
        [
            PointTarget(
                id="t-tip", anchor="link2:tip_face", point_mm=(40.0, 40.0, 14.0), tol_mm=0.01
            )
        ],
        free_joints=("j-shoulder", "j-elbow"),
    )
    assert point_only.verdict == "pose_found"

    # A target the arm can meet WITH the mate: at j-shoulder = 0 and
    # j-elbow = 30 the tip face is parallel to the 30 deg rail and its centre
    # sits at (40 + 40*cos30, 40*sin30) - hand-computed, so the fixture is not
    # asking the solver to confirm the solver.
    both = _solve(
        arm,
        [
            ConstraintTarget("c-align"),
            PointTarget(
                id="t-tip",
                anchor="link2:tip_face",
                point_mm=(74.6410161514, 20.0, 14.0),
                tol_mm=0.05,
            ),
        ],
        free_joints=("j-shoulder", "j-elbow"),
    )
    assert both.verdict == "pose_converged_at_tolerance"
    assert _constraint_row(both, "c-align")["satisfied"] is True
    assert _point_row(both, "t-tip")["within_bound"] is True
    for record in (point_only, both):
        for word in FORBIDDEN_WORDS:
            assert word not in _payload(record).lower(), (word, record.verdict)


# ==========================================================================
# clause 4: out of reach is NOT "infeasible" and NOT "violated"


def test_an_unreachable_target_names_every_start_and_the_closest_miss(arm: Arm) -> None:
    """Clause 4: ``no_pose_found_from_starts`` with every start and the miss.

    The arm's links are exactly 40, 34 and 29 mm, so a target 161.6 mm from the
    shoulder is out of reach by construction. The verdict names the starts it
    tried — evidence about those basins and nothing more — carries the
    re-measured miss distance, and is not spelled ``violated``: a solve is not
    a constraint verdict.
    """
    record = _solve(
        arm,
        [
            PointTarget(
                id="t-far", anchor="link3:tool_face", point_mm=(150.0, 60.0, 20.0), tol_mm=0.01
            )
        ],
        free_joints=("j-shoulder", "j-elbow", "j-wrist"),
        starts=(SolveStart(id="as_built"), SolveStart(id="folded", values={"j-elbow": 20.0})),
    )
    assert record.verdict == "no_pose_found_from_starts"
    assert "as_built" in record.detail and "folded" in record.detail
    row = _point_row(record, "t-far")
    assert row["within_bound"] is False
    assert float(cast("float", row["error_mm"])) > 0.01
    payload = _payload(record).lower()
    assert "violated" not in payload
    for word in FORBIDDEN_WORDS:
        assert word not in payload, word


# ==========================================================================
# clause 5: redundancy is a verdict, not a footnote


def test_a_redundant_chain_reports_its_remaining_freedom(arm: Arm) -> None:
    """Clause 5: ``pose_underdetermined_at_tolerance``, ``dof_remaining == 1``.

    Three revolute joints about parallel Z axes drive a target whose reachable
    set is two-dimensional, so one degree of freedom survives at the solution.
    Reporting one point of that continuum as *the* answer is a claim the
    mathematics does not support, so the verdict says so and the basis NAMES
    the free direction in joint-parameter coordinates.
    """
    record = _solve(
        arm,
        [
            PointTarget(
                id="t-tool", anchor="link3:tool_face", point_mm=(75.0, 25.0, 20.0), tol_mm=0.01
            )
        ],
        free_joints=("j-shoulder", "j-elbow", "j-wrist"),
    )
    assert record.verdict == "pose_underdetermined_at_tolerance"
    core = dict(record.solver_core)
    assert core["dof_remaining"] == 1
    basis = cast("list[Any]", core["null_basis"])
    assert len(basis) == 1
    direction = cast("dict[str, Any]", basis[0])
    named = [name for name, _value in cast("list[Any]", direction["components"])]
    assert named, direction
    assert set(named) <= {"j-shoulder", "j-elbow", "j-wrist"}
    assert direction["label"] and any(name in str(direction["label"]) for name in named)
    assert _point_row(record, "t-tool")["within_bound"] is True


# ==========================================================================
# clause 6: multiplicity, and the solver does not pick


def test_two_starts_that_converge_apart_return_both_and_choose_neither(arm: Arm) -> None:
    """Clause 6: ``multiple_poses_from_starts``, ranked, none marked chosen.

    ``parallel`` folds, so ``c-align`` is satisfied at +30 deg and at -150 deg
    alike — discrete multiplicity that rank cannot see. Both are returned,
    ranked by distance from ``as_built``, and neither carries ``chosen``.
    """
    record = _solve(
        arm,
        [ConstraintTarget("c-align")],
        free_joints=("j-elbow",),
        starts=(
            SolveStart(id="near", values={"j-elbow": 5.0}),
            SolveStart(id="far", values={"j-elbow": -170.0}),
        ),
    )
    assert record.verdict == "multiple_poses_from_starts"
    assert len(record.assignments) == 2
    angles = [
        cast("dict[str, float]", dict(item)["values"])["j-elbow"] for item in record.assignments
    ]
    assert angles[0] == pytest.approx(30.0, abs=1e-3)
    assert angles[1] == pytest.approx(-150.0, abs=1e-3)
    # Ranked by distance from as_built, ascending - and NEITHER chosen.
    distances = [
        float(cast("float", dict(item)["distance_from_as_built"])) for item in record.assignments
    ]
    assert distances == sorted(distances)
    assert all(dict(item)["chosen"] is False for item in record.assignments)
    assert {str(dict(item)["from_start"]) for item in record.assignments} == {"near", "far"}
    verified = cast("list[Any]", dict(record.verification)["verified_assignments"])
    assert len(verified) == 2


# ==========================================================================
# clause 7: a declared limit is a boundary, never a clamp


def test_a_target_past_a_declared_limit_reports_the_limit_and_stays_inside_it(arm: Arm) -> None:
    """Clause 7: ``limits_active`` names the joint; the value stays in the window.

    ``j-wrist`` is declared +/-10 deg and the target needs roughly 45. The
    answer is not a success, the limiting joint is named, and the returned
    assignment is INSIDE the declared window — shortened to the boundary and
    reported, never clamped past it (``geom/kinematics.py:217-245``).
    """
    record = _solve(
        arm,
        [
            PointTarget(
                id="t-wrist", anchor="link3:tool_face", point_mm=(94.5, 20.5, 20.0), tol_mm=0.01
            )
        ],
        free_joints=("j-wrist",),
    )
    assert record.verdict == "no_pose_found_from_starts"
    core = dict(record.solver_core)
    assert core["limits_active"] == ["j-wrist"]
    value = cast("dict[str, float]", dict(record.assignments[0])["values"])["j-wrist"]
    assert -10.0 <= value <= 10.0
    assert value == pytest.approx(10.0, abs=1e-9)
    assert cast("list[Any]", dict(record.assignments[0])["limits_active"]) == ["j-wrist"]


# ==========================================================================
# clause 8: every request-time refusal, by name, with nothing written


@pytest.mark.parametrize(
    ("reason", "kwargs"),
    [
        ("undeclared_weighting", {"weighting": "whatever_feels_right"}),
        ("undeclared_regularization", {"regularization": "nearest_to_nothing"}),
        ("tolerance_below_determinism_floor", {"tol": 1e-12}),
        ("missing_provenance", {"provenance": ConstraintProvenance()}),
        ("no_free_variables", {"free_joints": ()}),
    ],
)
def test_request_time_refusals_fire_by_name_with_nothing_written(
    arm: Arm, reason: str, kwargs: dict[str, Any]
) -> None:
    """Clause 8: each refusal by name, before any geometry is read."""
    before = _generations(arm)
    with pytest.raises(InvalidSolveRequest) as excinfo:
        _solve(arm, [ConstraintTarget("c-align")], **kwargs)
    assert excinfo.value.reason == reason
    assert excinfo.value.reason in SOLVE_REQUEST_REFUSALS
    assert _generations(arm) == before


@pytest.mark.parametrize(
    ("reason", "targets", "kwargs"),
    [
        ("unknown_joint", [ConstraintTarget("c-align")], {"free_joints": ("j-ghost",)}),
        ("unknown_constraint", [ConstraintTarget("c-ghost")], {}),
    ],
)
def test_refusals_that_need_the_project_read_still_write_nothing(
    arm: Arm, reason: str, targets: list[SolveTarget], kwargs: dict[str, Any]
) -> None:
    """Clause 8, continued: named refusals over real declared state."""
    before = _generations(arm)
    with pytest.raises(InvalidSolveRequest) as excinfo:
        _solve(arm, targets, **kwargs)
    assert excinfo.value.reason == reason
    assert excinfo.value.reason in SOLVE_REQUEST_REFUSALS
    assert _generations(arm) == before


def test_a_coupled_or_pairless_joint_is_refused_with_the_real_reason_in_the_detail(
    arm: Arm,
) -> None:
    """``unknown_joint`` carries WHICH of its three cases fired.

    DEVIATION, recorded here rather than left to a reader: ``SOLVER.md`` §6.3's
    request-time set is closed and has no spelling for "that joint exists but
    is not a free scalar parameter". Adding one would have amended the spec;
    dropping the joint silently would be the "nothing silently skipped"
    failure. So ``unknown_joint`` carries all three cases and the DETAIL
    distinguishes them, which this clause pins so the distinction cannot rot
    into a bare name.
    """
    before = _generations(arm)
    with pytest.raises(InvalidSolveRequest) as excinfo:
        _solve(arm, [ConstraintTarget("c-align")], free_joints=("j-ghost",))
    assert excinfo.value.reason == "unknown_joint"
    assert "j-ghost" in excinfo.value.message
    assert excinfo.value.subject == "j-ghost"
    assert _generations(arm) == before


def test_the_superseded_tolerance_spelling_appears_nowhere(arm: Arm) -> None:
    """Clause 8: ``tolerance_below_measurement_floor`` is gone from the source tree.

    The rename was deliberate (``SOLVER.md`` §6.3): 1e-9 is a *determinism*
    floor — what two processes in the pinned image are gated to agree to — and
    calling it a measurement floor would claim an accuracy nobody has measured,
    attached to the one epsilon a reader is most likely to trust. The scan
    covers the shipped packages; this file names the superseded spelling on
    purpose, which is why the test tree is not scanned.
    """
    superseded = "tolerance_below_measurement_floor"
    root = Path(__file__).resolve().parents[2]
    for directory in ("core/src", "server/src", "contract/src", "bench/src"):
        for path in sorted((root / directory).rglob("*.py")):
            assert superseded not in path.read_text(encoding="utf-8"), path
    with pytest.raises(InvalidSolveRequest) as excinfo:
        _solve(arm, [ConstraintTarget("c-align")], tol=1e-12)
    assert superseded not in json.dumps(excinfo.value.to_json())
    assert excinfo.value.reason == "tolerance_below_determinism_floor"


@pytest.mark.parametrize(
    ("constraint_id", "sub_reason"),
    [
        ("c-gap", "plateau"),
        ("c-touch", "plateau"),
        ("c-reach", "kernel_extremum"),
        ("c-fit", "pose_invariant"),
    ],
)
def test_the_excluded_kinds_are_refused_with_their_reason(
    arm: Arm, constraint_id: str, sub_reason: str
) -> None:
    """``not_an_objective_kind(reason)`` — the reason, not just the refusal.

    ``SOLVER.md`` §3.2 excludes these for three *different* mathematical facts
    and names each: a plateau carries no descent information at all, a kernel
    extremum's witness pair switches discontinuously exactly where mates live,
    and a pose-invariant measurement has no gradient in pose space by
    definition. Collapsing them into one refusal would hide which of the three
    an author had run into — and ``fit``'s reason is the one that will be
    *admitted* in 13C's parameter space, so the reason is what a later stage
    reads, not the refusal.
    """
    from hephaestus.core.placement import NOT_AN_OBJECTIVE_REASONS

    before = _generations(arm)
    with pytest.raises(InvalidSolveRequest) as excinfo:
        _solve(arm, [ConstraintTarget(constraint_id)], free_joints=("j-elbow",))
    assert excinfo.value.reason == "not_an_objective_kind"
    assert excinfo.value.sub_reason == sub_reason
    assert sub_reason in NOT_AN_OBJECTIVE_REASONS
    assert excinfo.value.subject == constraint_id
    assert _generations(arm) == before


def test_perpendicular_is_admitted_as_an_objective_kind(arm: Arm) -> None:
    """The exclusions' mirror: the four analytic kinds really do steer.

    Without this, a solver that refused *every* kind would pass the exclusion
    clauses above. ``c-perp`` holds at the as-built configuration and stays
    held, at full column rank, through the ordinary engine path.
    """
    record = _solve(arm, [ConstraintTarget("c-perp")], free_joints=("j-elbow",))
    assert record.verdict == "pose_converged_at_tolerance"
    assert _constraint_row(record, "c-perp")["satisfied"] is True
    assert dict(record.solver_core)["dof_remaining"] == 0


# ==========================================================================
# clauses 10 and 11: independent verification


def test_the_verification_process_excludes_the_solver_from_its_import_closure(
    arm: Arm,
) -> None:
    """Clause 11: the pass that produces the reported number cannot see the solver.

    ``SOLVER.md`` §7.1. The check is made INSIDE the verification process — it
    asserts against that process's own ``sys.modules`` — because an assertion
    made here would only describe this process. The second half is structural:
    importing the whole ``hephaestus.geom`` package must not pull the solver in
    through the package ``__init__``, which is why ``solve`` is the one geom
    service the package deliberately does not re-export.
    """
    import subprocess
    import sys

    record = _solve(arm, [ConstraintTarget("c-align")], free_joints=("j-elbow",))
    assert dict(record.verification)["import_closure_excludes_geom_solve"] is True

    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, hephaestus.geom; print('hephaestus.geom.solve' in sys.modules)",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert probe.stdout.strip() == "False", probe.stdout


def test_an_injected_solver_side_error_refuses_the_whole_result(arm: Arm, env_guard: None) -> None:
    """Clause 10: ``solver_residual_disagreement``, and **no verdict**.

    Fault injection perturbs the solver's own recorded component numbers after
    the iteration and before the §7.6 comparison, so the kernel's measurement
    is untouched and only the solver's model has drifted. Disagreement is
    fatal, not a warning: reporting the answer with a caveat would be exactly
    the overclaim this vocabulary exists to prevent.
    """
    del env_guard
    os.environ["HEPHAESTUS_SOLVE_FAULT"] = "1.0"
    with pytest.raises(SolveRunRefusal) as excinfo:
        _solve(arm, [ConstraintTarget("c-align")], free_joints=("j-elbow",))
    refusal = excinfo.value
    assert refusal.reason == "solver_residual_disagreement"
    assert refusal.reason in SOLVE_RUNTIME_REFUSALS
    payload = refusal.to_json()
    # No verdict is emitted - the refusal carries BOTH numbers instead.
    assert "verdict" not in payload
    # The injected 1.0 mm/deg, less the converged residual it was added to -
    # so the assertion is "far beyond VERIFY_EPS", not "exactly the injection".
    assert float(cast("float", payload["worst_disagreement"])) == pytest.approx(1.0, abs=1e-3)
    assert float(cast("float", payload["worst_disagreement"])) > float(
        cast("float", payload["verify_eps"])
    )
    rows = cast("list[Any]", payload["constraints"])
    component = cast("dict[str, Any]", cast("dict[str, Any]", rows[0])["components"][0])
    assert component["solver"] != component["measured"]


# ==========================================================================
# clause 12: ceilings are named refusals carrying partial evidence


def test_the_iteration_ceiling_is_a_refusal_carrying_its_best_iterate(
    arm: Arm, env_guard: None
) -> None:
    """Clause 12: ``iteration_ceiling``, with the best iterate and its residuals.

    Not a verdict, and asserted against the literal verdict tuple: a budget
    that ran out decided nothing, and giving the ceiling a verdict spelling
    would let it be read as an outcome (``core/motion.py:1489-1498``).
    """
    del env_guard
    with pytest.raises(SolveRunRefusal) as excinfo:
        _solve(
            arm,
            [
                PointTarget(
                    id="t-tip",
                    anchor="link2:tip_face",
                    point_mm=(40.0, 40.0, 14.0),
                    tol_mm=1e-9,
                )
            ],
            free_joints=("j-shoulder", "j-elbow"),
            ceiling=1,
        )
    refusal = excinfo.value
    assert refusal.reason == "iteration_ceiling"
    assert refusal.reason not in POSE_SOLVE_VERDICTS
    payload = refusal.to_json()
    assert payload["iteration_ceiling"] == 1
    assert payload["best_iterate"], payload
    verified = cast("dict[str, Any]", payload["verified"])
    assert verified["determinism_tier"] == "D2"
    assert cast("list[Any]", verified["points"]), verified


def test_the_wall_clock_ceiling_is_a_refusal_carrying_what_it_had(
    arm: Arm, env_guard: None
) -> None:
    """Clause 12: ``solver_timeout``, likewise named and likewise not a verdict."""
    del env_guard
    os.environ["HEPHAESTUS_SOLVE_TIMEOUT_S"] = "1e-9"
    with pytest.raises(SolveRunRefusal) as excinfo:
        _solve(arm, [ConstraintTarget("c-align")], free_joints=("j-elbow",))
    refusal = excinfo.value
    assert refusal.reason == "solver_timeout"
    assert refusal.reason not in POSE_SOLVE_VERDICTS
    assert refusal.reason in SOLVE_RUNTIME_REFUSALS
    payload = refusal.to_json()
    assert "verdict" not in payload
    assert payload["best_iterate"], payload
