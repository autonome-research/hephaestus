# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""G13B clauses 21 and 27-30, 38: refusals are not verdicts, and each has a name.

``core/motion.py:1489-1498``'s rule copied exactly: a killed sweep decided
nothing, and giving the kill a verdict spelling would let a timeout be read as
an outcome. Every clause here asserts a **name**, not a failure — and for the
run-time family, that the refusal carries the partial evidence it has rather
than a bare token.

The clause worth reading twice is 21. ``not_an_objective_kind`` is the one
refusal that reports a mathematical fact about the kind rather than a mistake
in the request: ``clearance_min`` and ``no_interference`` are identically flat
over a whole region, ``distance`` is a kernel extremum whose witness pair
switches discontinuously, and ``fit`` measures a quantity no rigid motion
changes. Each is refused **with its own reason**, because a solver that
"optimised" any of them silently would not work and a caller told only "no"
would not know why.
"""

from __future__ import annotations

import json
import multiprocessing
import os
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any, cast

import pytest
from _g13b import placement_request
from hephaestus.core.placement import (
    SOLVE_ITER_MAX_ENV,
    SOLVE_REQUEST_REFUSALS,
    SOLVE_RESOLUTION_REFUSALS,
    SOLVE_RUNTIME_REFUSALS,
    SOLVE_TIMEOUT_ENV,
    TRANSFORM_SOLVE_VERDICTS,
    VERIFY_TIMEOUT_ENV,
    InvalidSolveRequest,
    SolveRunRefusal,
    SolveStart,
    propose_placement,
)
from hephaestus.geom.solve import SOLUTION_DISTINCT_EPS

if TYPE_CHECKING:
    from hephaestus.core.project_store.layout import ProjectLayout

    from opstore import OpStore

TOL = 1e-4

SEATED = ("c-seat", "c-bore", "c-face")


@pytest.fixture
def env() -> Iterator[dict[str, str]]:
    """Restore every Stage 13 environment override, whatever a clause set."""
    names = (
        SOLVE_ITER_MAX_ENV,
        SOLVE_TIMEOUT_ENV,
        VERIFY_TIMEOUT_ENV,
        "HEPHAESTUS_SOLVE_SO3_FAULT",
    )
    saved = {name: os.environ.get(name) for name in names}
    try:
        yield {}
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


# ==========================================================================
# clause 21: not_an_objective_kind, with its reason, and nothing written


@pytest.mark.parametrize(
    ("constraint_id", "reason"),
    [
        ("c-clear", "plateau"),
        ("c-gap", "plateau"),
        ("c-reach", "kernel_extremum"),
        ("c-fit", "pose_invariant"),
    ],
)
def test_a_kind_that_carries_no_gradient_is_refused_with_its_reason(
    bench: tuple[ProjectLayout, OpStore], constraint_id: str, reason: str
) -> None:
    """Clause 21: each of the four, by name and with its reason string.

    Refused at REQUEST time, before any geometry is read, so a malformed
    request costs nothing and reports everything — and nothing is written,
    asserted by the proposal generation being unmoved.
    """
    from hephaestus.core.project_store.proposals import ProposalSet

    layout, store = bench
    before = ProposalSet(layout, store).state().generation
    with pytest.raises(InvalidSolveRequest) as excinfo:
        propose_placement(layout, store, placement_request((constraint_id,), tol=TOL))
    assert excinfo.value.reason == "not_an_objective_kind"
    assert excinfo.value.sub_reason == reason
    assert excinfo.value.subject == constraint_id
    assert reason in excinfo.value.message
    assert ProposalSet(layout, store).state().generation == before, "a refusal wrote something"
    # A refusal is never a verdict.
    assert excinfo.value.reason not in TRANSFORM_SOLVE_VERDICTS


# ==========================================================================
# clause 27: the six transform-space request refusals, each by name


def test_no_ground_part(bench: tuple[ProjectLayout, OpStore]) -> None:
    """Every part the constraints anchor declared free: nothing is held still.

    A system with no ground has a six-dimensional trivial null space, so every
    reported solution would be an arbitrary member of it — a fact about the
    arithmetic rather than about the geometry.
    """
    layout, store = bench
    with pytest.raises(InvalidSolveRequest) as excinfo:
        propose_placement(
            layout, store, placement_request(("c-seat",), free=("base", "lug"), tol=TOL)
        )
    assert excinfo.value.reason == "no_ground_part"


def test_free_part_is_jointed(bench: tuple[ProjectLayout, OpStore]) -> None:
    """A part forward kinematics owns may not also be claimed by a transform.

    ``hinge_b`` rides the declared joint ``j-hinge``. Letting a transform and a
    joint both claim one part would create a second home for its position
    inside a single evaluation — the P3 failure ``SOLVER.md`` §1.2 names —
    so it is refused here and solved in pose space instead.
    """
    layout, store = bench
    with pytest.raises(InvalidSolveRequest) as excinfo:
        propose_placement(layout, store, placement_request(("c-seat",), free=("hinge_b",), tol=TOL))
    assert excinfo.value.reason == "free_part_is_jointed"
    assert excinfo.value.subject == "hinge_b"
    assert "j-hinge" in excinfo.value.message


def test_pose_bound_constraint_in_transform_space(bench: tuple[ProjectLayout, OpStore]) -> None:
    """A pose-bound constraint's residual is already a function of an assignment."""
    layout, store = bench
    with pytest.raises(InvalidSolveRequest) as excinfo:
        propose_placement(layout, store, placement_request(("c-posed",), tol=TOL))
    assert excinfo.value.reason == "pose_bound_constraint_in_transform_space"
    assert excinfo.value.subject == "c-posed"
    assert "p-open" in excinfo.value.message


def test_free_part_in_no_constraint(bench: tuple[ProjectLayout, OpStore]) -> None:
    """Six all-zero Jacobian columns is not an answer, it is a start echoed back."""
    layout, store = bench
    with pytest.raises(InvalidSolveRequest) as excinfo:
        propose_placement(layout, store, placement_request(("c-seat",), free=("sleeve",), tol=TOL))
    assert excinfo.value.reason == "free_part_in_no_constraint"
    assert excinfo.value.subject == "sleeve"


def test_unknown_constraint(bench: tuple[ProjectLayout, OpStore]) -> None:
    layout, store = bench
    with pytest.raises(InvalidSolveRequest) as excinfo:
        propose_placement(layout, store, placement_request(("c-nope",), tol=TOL))
    assert excinfo.value.reason == "unknown_constraint"
    assert excinfo.value.subject == "c-nope"


def test_withdrawn_constraint(bench: tuple[ProjectLayout, OpStore]) -> None:
    """Solving towards a claim the project stopped making would invent the intent."""
    layout, store = bench
    with pytest.raises(InvalidSolveRequest) as excinfo:
        propose_placement(layout, store, placement_request(("c-old",), tol=TOL))
    assert excinfo.value.reason == "withdrawn_constraint"
    assert excinfo.value.subject == "c-old"


def test_every_request_refusal_here_writes_nothing(bench: tuple[ProjectLayout, OpStore]) -> None:
    """Clause 27's shared half: **nothing written**, for all six at once."""
    from hephaestus.core.project_store.proposals import ProposalSet

    layout, store = bench
    before = ProposalSet(layout, store).state().generation
    requests = [
        placement_request(("c-seat",), free=("base", "lug"), tol=TOL),
        placement_request(("c-seat",), free=("hinge_b",), tol=TOL),
        placement_request(("c-posed",), tol=TOL),
        placement_request(("c-seat",), free=("sleeve",), tol=TOL),
        placement_request(("c-nope",), tol=TOL),
        placement_request(("c-old",), tol=TOL),
    ]
    for request in requests:
        with pytest.raises(InvalidSolveRequest):
            propose_placement(layout, store, request)
    assert ProposalSet(layout, store).state().generation == before


# ==========================================================================
# clause 28: non_rigid_iterate


def test_a_drifted_rotation_block_is_refused_rather_than_placed(
    bench: tuple[ProjectLayout, OpStore], env: dict[str, str]
) -> None:
    """Clause 28: fault-inject past ``SO3_REPROJECT_EPS`` and the iterate is refused.

    Nothing in the codebase checked a ``RigidTransform``'s rotation block
    before Stage 13 (``geom/kinematics.py:423-448`` is a raw 3x4 dataclass), and
    the exponential parametrisation makes every iterate orthonormal by
    construction — so without the fault hook this safeguard is unreachable, and
    a safeguard no test can fire is a safeguard nobody knows works.

    A drifted iterate is not a placement: it would shear or scale the part it
    names. So it is a named refusal carrying the deviation, never a transform
    with a caveat.
    """
    del env
    layout, store = bench
    os.environ["HEPHAESTUS_SOLVE_SO3_FAULT"] = "0.01"
    with pytest.raises(SolveRunRefusal) as excinfo:
        propose_placement(layout, store, placement_request(SEATED, tol=TOL))
    assert excinfo.value.reason == "non_rigid_iterate"
    assert excinfo.value.reason in SOLVE_RUNTIME_REFUSALS
    assert excinfo.value.reason not in TRANSFORM_SOLVE_VERDICTS
    payload = excinfo.value.to_json()
    detail = cast("dict[str, Any]", payload["detail"])
    assert float(cast("float", detail["deviation"])) > float(
        cast("float", detail["so3_reproject_eps"])
    )


# ==========================================================================
# clause 29: weighting is a declared choice that changes the answer


def test_weighting_changes_the_solution_and_every_weight_is_echoed(
    bench: tuple[ProjectLayout, OpStore],
) -> None:
    """Clause 29: three weightings, weights echoed PER COMPONENT.

    The fixture is a genuine millimetre-against-degree trade. ``c-seat`` wants
    the lug's bottom face against the plate's top, ``c-lid`` wants its top face
    against the plate's underside; the two gaps are 10 mm apart and can both be
    closed only by turning the lug over, at which point both class predicates
    are as wrong as they can be. So the answer is a trade, and which side it
    lands on is decided by the declared weights — which is exactly why §3.4
    refuses to pick one and ``COMPARE.md:34-36`` calls alignment "a declared
    choice, NEVER a silent normalization".

    Both declared runs are asserted different from each other, and the
    millimetre-heavy one different from ``unit_scaled_v1``. The
    degree-heavy run agreeing with ``unit_scaled_v1`` is arithmetic rather than
    an oversight: both weight ratios sit on the same side of this fixture's
    switch (the trade turns over at mm/deg ~= 23, and ``unit_scaled_v1``
    computes 1 : 15), and asserting a difference that the cost surface does not
    have would be asserting a coincidence.
    """
    layout, store = bench
    starts = (SolveStart(), SolveStart(id="tilt90", values={"lug.rx": 90.0}))
    answers: dict[str, tuple[float, ...]] = {}
    cases: tuple[tuple[str, dict[str, Any]], ...] = (
        ("unit", {"weighting": "unit_scaled_v1"}),
        ("mm_heavy", {"weighting": "declared", "weights": (10.0, 0.01)}),
        ("deg_heavy", {"weighting": "declared", "weights": (0.01, 10.0)}),
    )
    for label, extra in cases:
        record = propose_placement(
            layout,
            store,
            placement_request(("c-seat", "c-lid"), tol=TOL, starts=starts, **extra),
        )
        core = cast("dict[str, Any]", record.solver_core)
        answers[label] = tuple(float(v) for v in cast("list[Any]", core["x"]))

        # Echoed PER COMPONENT: a `coincident` term contributes two weighted
        # rows, one mm and one deg, because both class bounds are 1e-3 deg —
        # three orders tighter than a typical tol_mm — so folding them into one
        # weight would let the tight bound dominate every step or vanish
        # entirely depending on the declared numbers.
        weights = {
            str(cast("dict[str, Any]", w)["key"]): cast("dict[str, Any]", w)
            for w in cast("list[Any]", core["weights"])
        }
        assert set(weights) == {
            "c-seat:gap",
            "c-seat:normals",
            "c-lid:gap",
            "c-lid:normals",
        }, weights
        assert weights["c-seat:gap"]["unit"] == "mm"
        assert weights["c-seat:normals"]["unit"] == "deg"
        assert core["weighting"] == extra["weighting"]

        if label == "unit":
            # unit_scaled_v1 records the radius it computed: a weight nobody can
            # see is a silent normalization.
            radius = float(cast("float", core["characteristic_radius_mm"]))
            assert radius == pytest.approx(15.0, abs=1e-6), radius
            assert weights["c-seat:normals"]["weight"] == pytest.approx(radius, rel=1e-9)
        else:
            assert core["characteristic_radius_mm"] is None

    def apart(a: str, b: str) -> float:
        return max(abs(x - y) for x, y in zip(answers[a], answers[b], strict=True))

    assert apart("mm_heavy", "deg_heavy") > SOLUTION_DISTINCT_EPS
    assert apart("mm_heavy", "unit") > SOLUTION_DISTINCT_EPS


def test_a_request_omitting_weighting_is_refused(bench: tuple[ProjectLayout, OpStore]) -> None:
    """Clause 29's negative: a residual vector mixing mm and deg has no canonical norm."""
    layout, store = bench
    with pytest.raises(InvalidSolveRequest) as excinfo:
        propose_placement(layout, store, placement_request(SEATED, tol=TOL, weighting=""))
    assert excinfo.value.reason == "undeclared_weighting"
    # And "declared" without the pair is the same refusal, not a default.
    with pytest.raises(InvalidSolveRequest) as excinfo:
        propose_placement(layout, store, placement_request(SEATED, tol=TOL, weighting="declared"))
    assert excinfo.value.reason == "undeclared_weighting"


# ==========================================================================
# clause 30: regularisation is echoed, and required


def test_regularization_is_echoed_and_a_request_omitting_it_is_refused(
    bench: tuple[ProjectLayout, OpStore],
) -> None:
    """Clause 30: ``min_norm_from_start`` is the only member and is still required.

    The Jacobian is rank-deficient by construction in this space (a lone mate
    of any analytic kind leaves a positive-dimensional solution set), so which
    null-space member comes back is a design decision, not a numerical detail.
    A required-and-echoed choice is how the record says which one was made.
    """
    layout, store = bench
    record = propose_placement(layout, store, placement_request(("c-bore",), tol=TOL))
    assert record.solver_core["regularization"] == "min_norm_from_start"
    assert record.request["regularization"] == "min_norm_from_start"
    with pytest.raises(InvalidSolveRequest) as excinfo:
        propose_placement(layout, store, placement_request(SEATED, tol=TOL, regularization="none"))
    assert excinfo.value.reason == "undeclared_regularization"


def test_a_tolerance_tighter_than_the_determinism_floor_is_refused(
    bench: tuple[ProjectLayout, OpStore],
) -> None:
    """The floor is a DETERMINISM floor, and the name says so.

    1e-9 is what two processes in the pinned image are gated to agree to
    (``ASSEMBLY.md:152-153``). Nothing in this repo has measured the kernel's
    accuracy against ground truth, so a tighter tolerance would be a claim
    nobody computed — and the earlier spelling
    ``tolerance_below_measurement_floor`` claimed exactly that.
    """
    layout, store = bench
    with pytest.raises(InvalidSolveRequest) as excinfo:
        propose_placement(layout, store, placement_request(SEATED, tol=1e-12))
    assert excinfo.value.reason == "tolerance_below_determinism_floor"
    assert "tolerance_below_measurement_floor" not in excinfo.value.message


# ==========================================================================
# clause 38: bounded execution — every ceiling is a NAMED refusal with evidence


def test_the_iteration_ceiling_fires_by_name_and_carries_its_best_iterate(
    bench: tuple[ProjectLayout, OpStore],
) -> None:
    """Clause 38: ``SOLVE_ITER_MAX`` produces a refusal, not a verdict.

    The budget ran out, so nothing was decided — and the refusal carries the
    best iterate and its **independently re-measured** residuals, because a
    ceiling that threw away the partial evidence would be the hang this
    vocabulary exists to replace.
    """
    layout, store = bench
    with pytest.raises(SolveRunRefusal) as excinfo:
        propose_placement(layout, store, placement_request(SEATED, tol=TOL, ceiling=1))
    assert excinfo.value.reason == "iteration_ceiling"
    assert excinfo.value.reason not in TRANSFORM_SOLVE_VERDICTS
    payload = excinfo.value.to_json()
    assert payload["iteration_ceiling"] == 1
    assert payload["best_iterate"], payload
    verified = cast("dict[str, Any]", payload["verified"])
    assert verified["determinism_tier"] == "D2"
    assert cast("list[Any]", verified["constraints"]), "the refusal carries no re-measurement"


def test_the_wall_clock_ceiling_fires_by_name(
    bench: tuple[ProjectLayout, OpStore], env: dict[str, str]
) -> None:
    """Clause 38: ``SOLVE_TIMEOUT_S``, env-overridable on the local-floor pattern."""
    del env
    layout, store = bench
    os.environ[SOLVE_TIMEOUT_ENV] = "0.000001"
    with pytest.raises(SolveRunRefusal) as excinfo:
        propose_placement(layout, store, placement_request(SEATED, tol=TOL))
    assert excinfo.value.reason == "solver_timeout"
    assert excinfo.value.reason not in TRANSFORM_SOLVE_VERDICTS


def test_the_verification_subprocess_is_dead_after_its_ceiling(
    bench: tuple[ProjectLayout, OpStore], env: dict[str, str]
) -> None:
    """Clause 38: the killable verification pass, and no survivor.

    ``COMPARE.md:152-176`` is the pattern and its measurement is the warning: a
    single boolean ground for ~19 h on a pathological B-rep, and five of six
    live-run infrastructure deaths ended on an unanswered ``compare_solids``.
    So the pass that touches the kernel runs in a process this one can kill,
    and the clause asserts the corpse is buried rather than only that the call
    returned.
    """
    del env
    layout, store = bench
    os.environ[VERIFY_TIMEOUT_ENV] = "0.001"
    with pytest.raises(SolveRunRefusal) as excinfo:
        propose_placement(layout, store, placement_request(SEATED, tol=TOL))
    assert excinfo.value.reason == "solver_timeout"
    assert not multiprocessing.active_children(), "a verification process outlived its ceiling"


def test_no_refusal_name_is_a_verdict_spelling() -> None:
    """Clause 38's last half, and §6.3's rule stated as an assertion.

    ``MotionTimeout`` is "deliberately NOT a ``SWEEP_VERDICTS`` member: a killed
    sweep decided nothing, and giving the kill a verdict spelling would let a
    timeout be read as an outcome". Stage 13 copies that rule exactly, in all
    three refusal families at once.
    """
    verdicts = set(TRANSFORM_SOLVE_VERDICTS)
    for family in (SOLVE_REQUEST_REFUSALS, SOLVE_RUNTIME_REFUSALS):
        assert not (set(family) & verdicts), set(family) & verdicts
    # `unresolvable` is the one name that is BOTH, and deliberately: it is a
    # verdict because "not checked" is a state a status reports, and a refusal
    # because the fix is to rerun rather than to read a number.
    assert set(SOLVE_RESOLUTION_REFUSALS) & verdicts == set()
    assert "unresolvable" in verdicts
    assert json.dumps(list(TRANSFORM_SOLVE_VERDICTS)).count("_") > 0
