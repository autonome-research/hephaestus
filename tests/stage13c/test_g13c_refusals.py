# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""G13C clauses 48-49: the parameter refusals, the box, and the two ceilings.

``SOLVER.md`` Gate G13C:

48. ``unknown_param`` and ``unbounded_param`` refused by name; a solve never
    proposes a value outside a declared ``min``/``max``, and a solution on a
    bound reports it in ``bounds_active``;
49. ``unbuildable_parameter_iterate`` carrying the build error when a candidate
    fails to build; ``build_budget_exhausted`` carrying the best iterate and its
    verified residuals.

Every refusal here is a **name**, never a verdict — the ``MotionTimeout`` rule
(``core/motion.py:1489-1498``) copied exactly: a killed or refused solve decided
nothing, and giving a spent ceiling a verdict spelling would let it be read as
an outcome.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

import pytest
from _g13c import param_request
from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend
from hephaestus.core.placement import (
    SOLVE_REQUEST_REFUSALS,
    SOLVE_RUNTIME_REFUSALS,
    InvalidSolveRequest,
    SolveRunRefusal,
    propose_placement,
)


def _solve(bench: Any, request: Any) -> Any:
    layout, store = bench
    return propose_placement(layout, store, request, backend=UnsafeLocalBackend())


def _rows(block: Any, key: str) -> Sequence[Mapping[str, Any]]:
    return cast("Sequence[Mapping[str, Any]]", cast("Mapping[str, Any]", block).get(key) or ())


# ==========================================================================
# clause 48 — unknown_param, unbounded_param, and the box that is never clamped


@pytest.mark.parametrize(
    ("free", "subject"),
    [
        ("post.no_such_knob", "post.no_such_knob"),
        ("no_such_part.h", "no_such_part.h"),
        ("hc.no_such_global", "hc.no_such_global"),
        ("post_h", "post_h"),
    ],
)
def test_a_name_that_is_not_a_declared_param_is_refused_unknown_param(
    bench: Any, free: str, subject: str
) -> None:
    """Four ways to name nothing, all one refusal, all naming what was named.

    A part that does not exist, a part that does but has no such knob, a
    globals name nobody declared, and a bare name with no scope at all — the
    last is refused too rather than guessed into a scope, because "which part
    did you mean" is not a question this stage answers by picking.
    """
    with pytest.raises(InvalidSolveRequest) as caught:
        _solve(bench, param_request(("c-seat",), (free,)))
    assert caught.value.reason == "unknown_param"
    assert caught.value.subject == subject
    assert "unknown_param" in SOLVE_REQUEST_REFUSALS


def test_a_globals_derived_constant_is_refused_unbounded_param(bench: Any) -> None:
    """``hc.plate_t`` is real, readable, numeric — and has no declared box.

    ``globals.py`` holds two kinds of public name (``script_contract.md`` §4):
    declared ``Param``s, which carry ``min``/``max``, and derived constants,
    which do not. §2C requires every parameter-space variable to stay strictly
    inside its declared bounds, so solving over a constant would be inventing a
    range the author never wrote. Refused by name, not given a default — which
    is also what keeps ``unbounded_param`` from being a refusal nothing can
    reach, since every ``Param`` proper is bounded by construction.
    """
    with pytest.raises(InvalidSolveRequest) as caught:
        _solve(bench, param_request(("c-seat",), ("hc.plate_t",)))
    assert caught.value.reason == "unbounded_param"
    assert caught.value.subject == "hc.plate_t"
    assert "derived constant" in caught.value.message
    assert "unbounded_param" in SOLVE_REQUEST_REFUSALS


def test_the_two_param_refusals_are_reachable_and_distinct(bench: Any) -> None:
    """They name different fixes, so they may not collapse into one spelling.

    ``unknown_param`` says "there is no such knob"; ``unbounded_param`` says
    "there is, and it has no bounds". The first is fixed by naming a different
    variable, the second by declaring a ``Param``.
    """
    with pytest.raises(InvalidSolveRequest) as unknown:
        _solve(bench, param_request(("c-seat",), ("hc.shelf_zz",)))
    with pytest.raises(InvalidSolveRequest) as unbounded:
        _solve(bench, param_request(("c-seat",), ("hc.shelf_w",)))
    assert unknown.value.reason != unbounded.value.reason
    assert unbounded.value.reason == "unbounded_param"


def test_a_solve_never_proposes_a_value_outside_the_declared_bounds(bench_copy: Any) -> None:
    """``cap.spigot_r`` is bounded 6..8 and the fit wants it at 7.65..7.85.

    The assertion is the general one and not the fixture's: every proposed
    value in every returned solution sits inside the ``min``/``max`` the record
    itself echoes beside it, so a reader can check the claim against the
    document rather than against this test.
    """
    record = _solve(bench_copy, param_request(("c-fit",), ("cap.spigot_r",)))
    assert record.verdict == "converged_at_tolerance", record.detail
    for placement in record.placements:
        for entry in _rows(placement, "parameters"):
            value = float(cast("float", entry["value"]))
            assert (
                float(cast("float", entry["min"])) <= value <= float(cast("float", entry["max"]))
            ), entry
            assert (float(cast("float", entry["min"])), float(cast("float", entry["max"]))) == (
                6.0,
                8.0,
            )


def test_a_solution_on_a_bound_reports_it_rather_than_clamping_in_silence(
    bench_copy: Any,
) -> None:
    """The refusal-never-clamp rule (``geom/kinematics.py:217-245``) in 2C.

    ``c-tall`` wants the shelf's top face 100 mm above the post's base, which
    needs ``shelf_z = 94`` — and ``shelf_z`` is declared ``0..60``. The step is
    shortened to the boundary, the variable comes back **named** in
    ``bounds_active``, and the verdict is verdict 4, because a solution sitting
    on a bound is a boundary solution and not a stationary point. The value
    proposed is inside the declared box, not the 94 the arithmetic wanted:
    parameter space never proposes a value the author's own declaration
    forbids.
    """
    record = _solve(bench_copy, param_request(("c-tall",), ("hc.shelf_z",)))
    assert record.verdict == "no_placement_found_from_starts", record.detail
    placement = record.placements[0]
    assert list(cast("Sequence[str]", placement["bounds_active"])) == ["hc.shelf_z"]
    entry = _rows(placement, "parameters")[0]
    assert float(cast("float", entry["value"])) == pytest.approx(60.0, abs=1e-6)
    assert float(cast("float", entry["max"])) == 60.0
    assert cast("Mapping[str, Any]", record.solver_core)["limits_active"] == ["hc.shelf_z"]
    # And the honest control: a solve whose answer is INSIDE its box reports an
    # empty list rather than a decorative one.
    inside = _solve(bench_copy, param_request(("c-lift",), ("hc.shelf_z",)))
    assert inside.verdict == "converged_at_tolerance", inside.detail
    assert inside.placements[0]["bounds_active"] == []


def _start(name: str, values: Mapping[str, float]) -> Any:
    from hephaestus.core.placement import SolveStart

    return SolveStart(id=name, values=dict(values))


def test_a_start_outside_the_declared_bounds_is_refused_by_name(bench: Any) -> None:
    """§2C's "strictly inside its declared min/max" holds at the start too.

    Clamping the start silently would make the reported ``from_start`` a lie
    about where the iteration began, and refusing it later would spend builds
    to reach a conclusion the request already stated.
    """
    with pytest.raises(InvalidSolveRequest) as caught:
        _solve(
            bench,
            param_request(
                ("c-seat",),
                ("post.post_h",),
                starts=(_start("too_tall", {"post.post_h": 99.0}),),
            ),
        )
    assert caught.value.reason == "unbounded_param"
    assert caught.value.subject == "post.post_h"


def test_a_parameter_space_request_refuses_a_declared_box_and_a_ground_set(bench: Any) -> None:
    """Both are transform space's, and both are refused rather than ignored.

    A ``Param``'s own ``min``/``max`` IS its box, so a second one would be a
    bound the author never declared silently overriding the one they did; and
    parameter space holds no part still, so a ground set names nothing. A
    declared limit nobody spends is a limit a reader would believe was
    enforced.
    """
    with pytest.raises(InvalidSolveRequest) as boxed:
        _solve(
            bench,
            param_request(("c-seat",), ("post.post_h",), box={"post.post_h": (5.0, 9.0)}),
        )
    assert "Param" in boxed.value.message
    with pytest.raises(InvalidSolveRequest) as grounded:
        _solve(bench, param_request(("c-seat",), ("post.post_h",), ground=("shelf",)))
    assert grounded.value.reason == "no_ground_part"


def test_a_transform_space_request_refuses_a_build_budget(bench: Any) -> None:
    """The mirror image: a 2B iteration issues no build, so it spends no budget."""
    with pytest.raises(InvalidSolveRequest) as caught:
        _solve(
            bench,
            param_request(("c-seat",), ("shelf",), space="transform", build_budget=4),
        )
    assert "build budget" in caught.value.message


def test_an_unrecognised_space_is_refused_rather_than_solved_as_a_transform(
    bench: Any,
) -> None:
    """A request that asked for one space and got another is worse than a refusal."""
    from hephaestus.core.placement import SOLVE_SPACES

    assert SOLVE_SPACES == ("transform", "parameters")
    with pytest.raises(InvalidSolveRequest) as caught:
        _solve(bench, param_request(("c-seat",), ("post.post_h",), space="poses"))
    assert caught.value.subject == "poses"


# ==========================================================================
# clause 49 — the two 2C ceilings, each carrying its evidence


def test_a_candidate_that_does_not_build_is_refused_with_the_build_error(
    bench_copy: Any,
) -> None:
    """``unbuildable_parameter_iterate``, carrying the candidate's own §8 error.

    ``pin.pin_r``'s declared floor is 0.0 and a zero-radius cylinder is not
    geometry, so a start on the floor is a candidate the kernel refuses. That
    is a fact about the candidate, and inventing residuals for it would be the
    overclaim the refusal exists to avoid — so the refusal carries the build's
    own error record rather than a bare name.
    """
    with pytest.raises(SolveRunRefusal) as caught:
        _solve(
            bench_copy,
            param_request(
                ("c-coax",),
                ("pin.pin_r",),
                starts=(_start("degenerate", {"pin.pin_r": 0.0}),),
            ),
        )
    assert caught.value.reason == "unbuildable_parameter_iterate"
    assert "unbuildable_parameter_iterate" in SOLVE_RUNTIME_REFUSALS
    payload = cast("Mapping[str, Any]", caught.value.payload)
    detail = cast("Mapping[str, Any]", payload["detail"])
    assert detail["part"] == "pin"
    assert cast("Mapping[str, Any]", detail["params"])["pin_r"] == 0.0
    error = detail["error"]
    assert isinstance(error, dict), "the refusal dropped the build error it exists to carry"
    assert cast("Mapping[str, Any]", error)["message"]


def test_a_spent_build_budget_is_refused_with_the_best_iterate(bench_copy: Any) -> None:
    """``build_budget_exhausted``, carrying the best iterate and its residuals.

    ``SOLVER.md`` §10: a 2C solve is otherwise an unbounded number of kernel
    evaluations, which is the shape ``COMPARE.md:152-176`` measured at ~19 h on
    one pathological boolean. The budget is spent on the ITERATION's builds; the
    §7 verification pass has its own wall-clock bound, which is why the refusal
    can still afford to re-measure what it carries.
    """
    with pytest.raises(SolveRunRefusal) as caught:
        _solve(
            bench_copy,
            param_request(("c-seat", "c-lift"), ("hc.shelf_z", "post.post_h"), build_budget=3),
        )
    assert caught.value.reason == "build_budget_exhausted"
    assert "build_budget_exhausted" in SOLVE_RUNTIME_REFUSALS
    payload = cast("Mapping[str, Any]", caught.value.payload)
    assert payload["build_budget"] == 3
    assert int(cast("int", payload["builds_issued"])) <= 3
    best = _rows(payload, "best_iterate")
    assert best, "a ceiling refusal that carried no iterate carried no evidence"
    verified = cast("Mapping[str, Any]", payload["verified"])
    assert verified["determinism_tier"] == "D2"
    assert _rows(verified, "constraints"), "the best iterate's residuals were not re-measured"


def test_neither_ceiling_is_a_verdict(bench_copy: Any) -> None:
    """The ``MotionTimeout`` rule, copied exactly (``SOLVER.md`` §6.3).

    A spent ceiling decided nothing. Giving it a verdict spelling would let a
    refusal be read as an outcome, so the run-time names are asserted absent
    from both proposal-space verdict tuples.
    """
    from hephaestus.core.placement import PARAM_SOLVE_VERDICTS, TRANSFORM_SOLVE_VERDICTS

    for name in SOLVE_RUNTIME_REFUSALS:
        assert name not in PARAM_SOLVE_VERDICTS
        assert name not in TRANSFORM_SOLVE_VERDICTS
    assert PARAM_SOLVE_VERDICTS == TRANSFORM_SOLVE_VERDICTS, (
        "SOLVER.md §6.1 opens 'For 2B and 2C': one vocabulary, not two"
    )


def test_a_refused_solve_records_no_proposal_and_moves_no_generation(bench_copy: Any) -> None:
    """A refusal writes nothing the proposal set can be read out of."""
    from hephaestus.core.project_store.proposals import ProposalSet

    layout, store = bench_copy
    with pytest.raises(SolveRunRefusal):
        _solve(
            bench_copy,
            param_request(("c-seat", "c-lift"), ("hc.shelf_z", "post.post_h"), build_budget=3),
        )
    state = ProposalSet(layout, store).state()
    assert state.generation == 0
    assert state.entries == ()


def test_the_build_budget_is_env_overridable_on_the_local_floor_pattern() -> None:
    """``SOLVER.md`` §10: every ceiling is a named constant, env-overridable."""
    import os

    from hephaestus.core.placement import (
        SOLVE_BUILD_BUDGET,
        SOLVE_BUILD_BUDGET_ENV,
        solve_build_budget,
    )

    assert solve_build_budget() == SOLVE_BUILD_BUDGET
    previous = os.environ.get(SOLVE_BUILD_BUDGET_ENV)
    try:
        os.environ[SOLVE_BUILD_BUDGET_ENV] = "7"
        assert solve_build_budget() == 7
        # A malformed or non-positive override is simply off, never a crash and
        # never an unbounded solve.
        os.environ[SOLVE_BUILD_BUDGET_ENV] = "nonsense"
        assert solve_build_budget() == SOLVE_BUILD_BUDGET
        os.environ[SOLVE_BUILD_BUDGET_ENV] = "0"
        assert solve_build_budget() == SOLVE_BUILD_BUDGET
    finally:
        if previous is None:
            os.environ.pop(SOLVE_BUILD_BUDGET_ENV, None)
        else:
            os.environ[SOLVE_BUILD_BUDGET_ENV] = previous
