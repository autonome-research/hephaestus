# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""G13C clauses 44-47: the parameter solve, its disclosure, and its previews.

``SOLVER.md`` Gate G13C:

44. a two-``Param`` solve reaches a hand-computed optimum to ``PARAM_MATCH_EPS``
    — never to 1e-9 — and ``fit`` is admitted here, asserted against 13B's
    refusal of the same kind;
45. ``nonsmooth_terms`` lists every ``distance`` term and the record states the
    local-model caveat;
46. every candidate build is a preview: ``current == false`` on all of them,
    the parts' current artifact refs unchanged, no override persisted;
47. ``no_free_variable_affects`` names the constraint no free parameter moves.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

import pytest
from _g13c import (
    FIXTURE_KAPPA,
    KAPPA_MATCH_REL,
    OPTIMUM,
    PARAM_MATCH_FACTOR,
    SOLVE_TOL,
    kappa_reads_outside_the_pin,
    param_request,
    param_values,
    proposal_document,
)
from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend
from hephaestus.core.placement import (
    NONSMOOTH_CAVEAT,
    OBJECTIVE_EXCLUSIONS,
    PARAM_OBJECTIVE_EXCLUSIONS,
    SolveUnresolvable,
    propose_placement,
)
from hephaestus.core.project_store.layout import load_project, open_store


def _rows(block: Any, key: str) -> Sequence[Mapping[str, Any]]:
    return cast("Sequence[Mapping[str, Any]]", cast("Mapping[str, Any]", block).get(key) or ())


# ==========================================================================
# clause 44 — the hand-computed optimum, to PARAM_MATCH_EPS and never to 1e-9


def test_a_two_param_solve_reaches_the_hand_computed_optimum(optimum_record: Any) -> None:
    """``shelf_z = post_h = 32.0``, derived on paper in ``_g13c``'s docstring.

    The pair is linear and determined: ``c-seat`` gives ``shelf_z - post_h = 0``
    and ``c-lift`` gives ``shelf_z + plate_t = 38``. The assertion is against
    that arithmetic, not against whatever the solver produced.
    """
    record, _root = optimum_record
    assert record.verdict == "converged_at_tolerance", record.detail
    assert record.space == "parameters"
    values = param_values(record)
    assert set(values) == set(OPTIMUM)
    eps = param_match_eps(record)
    for name, wanted in OPTIMUM.items():
        assert values[name] == pytest.approx(wanted, abs=eps), (
            f"{name}: solved {values[name]!r} against the hand-computed {wanted!r}"
        )


def param_match_eps(record: Any) -> float:
    """``PARAM_MATCH_EPS`` = ``tol * PARAM_MATCH_FACTOR * kappa`` (``SOLVER.md`` § Gates).

    ``kappa`` is :data:`_g13c.FIXTURE_KAPPA` — the fixture's own condition number
    of the weighted Jacobian at the optimum, **recorded there** beside the answer
    it qualifies and derived on paper from the fixture's two rows. It is not the
    number the solver reported.

    **Repaired 2026-09-01**: this function used to read
    ``record.solver_core["kappa"]``, which handed the solver control of the
    accuracy budget it was being graded against — the self-grading shape §7's
    independent verification exists to refuse, arriving through the gate's own
    arithmetic. The solver's report is now *held to* the recorded number instead,
    by :func:`test_the_solver_s_reported_conditioning_matches_the_recorded_one`.
    """
    # The tolerance comes off the REQUEST — a declared input, not a solver
    # output — and the conditioning comes off the fixture. Neither half is the
    # solver's to choose.
    return float(record.request["tol"]) * PARAM_MATCH_FACTOR * FIXTURE_KAPPA


def test_the_solver_s_reported_conditioning_matches_the_recorded_one(optimum_record: Any) -> None:
    """The epsilon's ``kappa`` is the fixture's; the solver is held to it, not asked.

    Clause 44 derives ``PARAM_MATCH_EPS`` from "the fixture's recorded
    conditioning", and a recording nothing checks would drift silently away from
    the system it claims to describe. So the recording is asserted in both
    directions at once: the solver's reported conditioning is within
    :data:`_g13c.KAPPA_MATCH_REL` of :data:`_g13c.FIXTURE_KAPPA`, which fails
    both if the fixture's paper derivation is wrong and if the solver inflates
    the number to widen its own tolerance.

    The band is not 1e-9 and may not be: ``kappa`` comes off the weighted
    Jacobian at a *solved* iterate, and in parameter space that Jacobian is a
    finite difference over rebuilt geometry (§2C). 7e-12 is what it delivers.
    """
    record, _root = optimum_record
    reported = float(cast("Mapping[str, Any]", record.solver_core)["kappa"])
    assert reported == pytest.approx(FIXTURE_KAPPA, rel=KAPPA_MATCH_REL), (
        f"the solver reports kappa {reported!r} against the fixture's recorded "
        f"{FIXTURE_KAPPA!r}; PARAM_MATCH_EPS is derived from the RECORDED one"
    )


def test_the_parameter_epsilon_is_derived_and_is_not_vacuous(optimum_record: Any) -> None:
    """It is a *derived* bound, and one a wrong answer could not slip through.

    Three halves now, and all three matter. It is derived from the declared
    tolerance and the fixture's **recorded** conditioning rather than picked; it
    is derived from the recording rather than from the record, so a solver
    reporting a different ``kappa`` changes nothing about the bound it is graded
    against; and it stays far below the 22 mm the as-built start sits from the
    answer, so "reached the optimum" cannot degrade into "moved in roughly the
    right direction".
    """
    record, _root = optimum_record
    eps = param_match_eps(record)
    assert eps == pytest.approx(SOLVE_TOL * PARAM_MATCH_FACTOR * FIXTURE_KAPPA)
    # Derived from the recording, NOT from the record: perturbing what the solver
    # reported must not move the bound by one bit.
    inflated = _WidenedKappa(record, FIXTURE_KAPPA * 1000.0)
    assert param_match_eps(inflated) == eps, (
        "PARAM_MATCH_EPS moved when the solver's reported kappa did; the epsilon "
        "is the fixture's to declare and never the solver's to widen"
    )
    assert 0.0 < eps < 1.0, f"PARAM_MATCH_EPS {eps!r} is not a bound that discriminates"
    # And the start really is that far away, so the clause is measuring a solve.
    assert abs(10.0 - OPTIMUM["hc.shelf_z"]) > 20.0 * eps


def test_no_epsilon_in_this_suite_is_derived_from_the_solver_s_own_kappa() -> None:
    """Clause 44's epsilon, asserted as a RULE and not only at one call site.

    The 13B twin of this scan (``tests/stage13b/test_g13b_solve.py``) says why:
    an epsilon of the form ``tol * FACTOR * kappa`` belongs to whoever supplies
    ``kappa``, and the Gates preamble gives that to the fixture. Until
    2026-09-01 both suites read it off the record instead.
    """
    offenders = kappa_reads_outside_the_pin(Path(__file__).resolve().parent)
    assert not offenders, (
        "the solver's own reported kappa is read outside the pin that holds it to "
        "the fixture's recorded one:\n" + "\n".join(offenders)
    )


class _WidenedKappa:
    """One record with an inflated ``solver_core["kappa"]``, and nothing else changed.

    The negative half of the repair above: a solver that reports a thousandfold
    conditioning must not thereby widen the tolerance it is graded against. Only
    the two attributes :func:`param_match_eps` could reach are provided, so a
    future version that started reading the record again would fail here rather
    than pass on a stub that answered everything.
    """

    def __init__(self, record: Any, kappa: float) -> None:
        self.solver_core = {**cast("Mapping[str, Any]", record.solver_core), "kappa": kappa}
        self.request = record.request


def test_no_clause_here_asserts_1e_9_of_a_solved_quantity(optimum_record: Any) -> None:
    """The Gates preamble's rule, asserted rather than merely observed.

    A gate clause may assert 1e-9 of a pure function at fixed given inputs; it
    may never assert 1e-9 of a *solved* quantity, because the solver terminates
    on the declared tolerance and a tolerance tighter than the determinism
    floor is refused by name. The measured distance from the optimum here is
    orders above 1e-9, which is what makes the rule a fact about this stage
    rather than a preference.
    """
    record, _root = optimum_record
    values = param_values(record)
    worst = max(abs(values[name] - wanted) for name, wanted in OPTIMUM.items())
    assert worst > 1e-9, (
        "the solved values happen to be within 1e-9 of the optimum; if a future "
        "fixture makes that reliable it still may not be ASSERTED - the solver "
        "terminates on the declared tolerance and cannot promise more"
    )
    assert worst < param_match_eps(record)


def test_the_verified_residuals_all_measure_satisfied(optimum_record: Any) -> None:
    """Conjunct (i): read from the kernel's ``satisfied``, never from a residual."""
    record, _root = optimum_record
    rows = _rows(record.verification, "constraints")
    assert {row["id"] for row in rows} == {"c-seat", "c-lift"}
    for row in rows:
        assert row["satisfied"] is True, row


def test_fit_is_an_objective_term_here_and_refused_in_transform_space(
    fit_record: Any, bench: Any
) -> None:
    """Clause 44's second half: the same kind, admitted here, refused there.

    ``fit`` measures ``hole_radius - shaft_radius``, which no rigid motion
    changes — so it carries no gradient in transform space and is refused
    ``not_an_objective_kind(pose_invariant)``. A ``Param`` change is exactly
    what does move it. That asymmetry is why §3.2 names a *reason* per
    exclusion rather than listing kinds, and it is asserted here from both
    sides rather than from one.
    """
    from hephaestus.core.placement import InvalidSolveRequest

    record, _root = fit_record
    assert record.verdict == "converged_at_tolerance", record.detail
    row = next(r for r in _rows(record.verification, "constraints") if r["id"] == "c-fit")
    assert row["satisfied"] is True
    assert 0.15 <= float(cast("float", row["measured"])) <= 0.35

    # The other side: the same constraint id, the same project, transform space.
    layout, store = bench
    with pytest.raises(InvalidSolveRequest) as caught:
        propose_placement(
            layout,
            store,
            param_request(("c-fit",), ("cap",), space="transform"),
            backend=UnsafeLocalBackend(),
        )
    assert caught.value.reason == "not_an_objective_kind"
    assert caught.value.sub_reason == "pose_invariant"

    # And the two tables say so structurally, so the asymmetry cannot drift.
    assert OBJECTIVE_EXCLUSIONS["fit"] == "pose_invariant"
    assert OBJECTIVE_EXCLUSIONS["distance"] == "kernel_extremum"
    assert "fit" not in PARAM_OBJECTIVE_EXCLUSIONS
    assert "distance" not in PARAM_OBJECTIVE_EXCLUSIONS
    # The two plateau kinds stay refused in BOTH: a flat region carries no
    # descent information in any space.
    assert PARAM_OBJECTIVE_EXCLUSIONS == {"no_interference": "plateau", "clearance_min": "plateau"}


def test_a_fit_window_is_a_window_and_not_a_point(fit_record: Any) -> None:
    """The deadband is the shape the constraint claims (``SOLVER.md`` §3.3).

    A ``fit``'s bound is ``min_mm <= measured <= max_mm``, so any value inside
    is satisfied and driving to one particular clearance would be the solver
    inventing an intent the declaration does not carry. The component's own
    bound is therefore 0 on the *excess outside the window*, which is exactly
    the kernel's ``satisfied``.
    """
    record, _root = fit_record
    row = next(r for r in _rows(record.verification, "constraints") if r["id"] == "c-fit")
    component = next(c for c in _rows(row, "components") if c["key"] == "c-fit:window")
    assert component["bound"] == 0.0
    assert component["within_bound"] is True
    assert float(cast("float", component["measured"])) == pytest.approx(0.0, abs=1e-9)
    declared = dict(cast("Sequence[tuple[str, float]]", row["declared"]))
    assert declared == {"min_mm": 0.15, "max_mm": 0.35}


# ==========================================================================
# clause 45 — nonsmooth_terms, and the caveat stated in the record


def test_nonsmooth_terms_lists_every_distance_term(optimum_record: Any, bench: Any) -> None:
    """Every ``distance`` term, and only those (``SOLVER.md`` §3.2)."""
    record, root = optimum_record
    assert record.nonsmooth_terms == ("c-lift",)
    layout = load_project(root)
    store = open_store(layout)
    try:
        document = proposal_document(layout, store, record)
    finally:
        store.close()
    assert document["nonsmooth_terms"] == ["c-lift"]


def test_the_record_states_the_local_model_caveat(optimum_record: Any) -> None:
    """The caveat travels with the record, not only with the spec.

    A descent over a function with a kink in it is a LOCAL model: the numbers
    are real and the neighbourhood they are real in is smaller than a smooth
    term's. A reader who has only the proposal has to be able to see that.
    """
    record, root = optimum_record
    layout = load_project(root)
    store = open_store(layout)
    try:
        document = proposal_document(layout, store, record)
    finally:
        store.close()
    caveat = str(document["nonsmooth_caveat"])
    assert caveat == NONSMOOTH_CAVEAT
    assert "LOCAL model" in caveat
    assert "kernel extremum" in caveat


def test_a_solve_with_no_distance_term_carries_neither(fit_record: Any) -> None:
    """No ``distance`` term, no list and no caveat — not an empty one.

    A caveat printed unconditionally is a caveat nobody reads. This solve's
    only term is a ``fit``, which is smooth in its parameter, so the record
    says nothing about nonsmoothness at all.
    """
    record, root = fit_record
    assert record.nonsmooth_terms == ()
    layout = load_project(root)
    store = open_store(layout)
    try:
        document = proposal_document(layout, store, record)
    finally:
        store.close()
    assert document["nonsmooth_terms"] == []
    assert "nonsmooth_caveat" not in document


# ==========================================================================
# clause 46 — every candidate build is a preview


def test_every_build_the_solve_issued_is_a_preview(optimum_record: Any) -> None:
    """``current == false`` on **every** one, read off publication's own answer.

    This is the property the whole space rests on: a 2C solve evaluates
    candidates by BUILDING them, and it is allowed to do that only because a
    transient-override build "create[s] a preview artifact and therefore always
    return[s] ``current=false``".
    """
    record, _root = optimum_record
    builds = _rows(record.solver_core, "preview_builds")
    assert builds, "a parameter solve that issued no build measured nothing"
    for row in builds:
        assert row["current"] is False, row
    assert int(record.solver_core["builds_issued"]) == len(builds)


def test_the_verifying_process_only_previews_too(optimum_record: Any) -> None:
    """And the same holds on the side that re-measures (``SOLVER.md`` §7.2).

    The verification pass rebuilds every measured part at the proposed values
    in its own process. If *it* could make a build current, the guarantee would
    hold on the solver's side and leak on the checker's.
    """
    record, _root = optimum_record
    builds = _rows(record.verification, "preview_builds")
    assert builds, "a 2C verification pass that built nothing measured nothing"
    assert {str(row["part"]) for row in builds} == {"post", "shelf"}
    for row in builds:
        assert row["current"] is False, row


def test_the_parts_current_artifact_refs_are_unchanged_by_the_solve(
    optimum_record: Any,
) -> None:
    """The published design is exactly where it was when the solve started."""
    from hephaestus.core.project_store.publication import Publisher

    record, root = optimum_record
    layout = load_project(root)
    store = open_store(layout)
    try:
        publisher = Publisher(layout, store)
        for part, bound in record.artifact_refs.items():
            current = publisher.current_result(part)
            assert current is not None
            assert current.artifact_ref == bound, (
                f"{part}: the current pointer moved during a solve that proposes only"
            )
            assert current.current is True
    finally:
        store.close()


def test_no_parameter_override_is_persisted_by_a_solve(optimum_record: Any) -> None:
    """The project's parameter state hash is byte-identical afterwards.

    Read through the same ``ParamStore`` ``set_params`` writes, so this is the
    state a later ``set_params`` would present as its ``expected_state_hash``:
    a solve that had persisted anything would move it.
    """
    from hephaestus.agent_bridge.cad_ops._base import ParamStore

    _record, root = optimum_record
    layout = load_project(root)
    store = open_store(layout)
    try:
        params = ParamStore(layout, store)
        project = params.read("project", None)
        assert project.values == {}
        assert project.blob is None, "a solve wrote a project override document"
        for part in ("post", "shelf"):
            scoped = params.read("part", part)
            assert scoped.values == {}
            assert scoped.blob is None, f"a solve wrote a part override document for {part}"
    finally:
        store.close()


def test_the_as_built_start_is_what_the_current_builds_recorded(optimum_record: Any) -> None:
    """``as_built`` means as built, not "the declaration's defaults".

    The distance from as-built is the weighted distance from (10, 20) — the
    values the published artifacts carry — to the answer, and it is reported so
    a reader can see how far the proposal moves the design.
    """
    import math

    record, _root = optimum_record
    moved = float(cast("float", record.placements[0]["distance_from_as_built"]))
    expected = math.hypot(OPTIMUM["hc.shelf_z"] - 10.0, OPTIMUM["post.post_h"] - 20.0)
    assert moved == pytest.approx(expected, abs=param_match_eps(record) * 2)


# ==========================================================================
# clause 47 — no_free_variable_affects, naming the constraint


def test_a_constraint_no_free_parameter_moves_is_refused_by_name(bench_copy: Any) -> None:
    """``SOLVER.md`` §2C: parameter space can only reach what the author knobbed.

    ``c-square`` asks two parallel horizontal faces to be perpendicular. It is
    unsatisfiable at any value, and — the point of the clause — no free
    parameter moves it: the spigot's radius changes the cap, and the cap is not
    in this constraint at all. A mate nobody made a knob for is unreachable,
    and the report says which mate rather than iterating to a floor and blaming
    the geometry.
    """
    layout, store = bench_copy
    record = propose_placement(
        layout,
        store,
        param_request(("c-square",), ("cap.spigot_r",)),
        backend=UnsafeLocalBackend(),
    )
    assert record.verdict == "unresolvable"
    assert record.reason == "no_free_variable_affects"
    assert record.subject == "c-square"
    assert "c-square" in record.detail
    assert "SENSITIVITY_EPS" in record.detail


def test_the_unresolvable_record_carries_no_blocks_and_no_proposal(bench_copy: Any) -> None:
    """A computation that never ran claims no determinism tier and writes nothing.

    ``unresolvable`` is the one name that is both a verdict and a refusal, and
    the record says so by carrying nothing: no ``solver_core``, no
    ``verification``, no proposal. Storing a proposal that proposes nothing
    would make the proposal set answer a question it was never asked.
    """
    from hephaestus.core.project_store.proposals import ProposalSet

    layout, store = bench_copy
    record = propose_placement(
        layout,
        store,
        param_request(("c-square",), ("cap.spigot_r",)),
        backend=UnsafeLocalBackend(),
    )
    assert record.solver_core == {}
    assert record.verification == {}
    assert record.proposal_id == "" and record.proposal_ref == ""
    state = ProposalSet(layout, store).state()
    assert state.generation == 0
    assert state.entries == ()


def test_a_satisfied_insensitive_constraint_is_NOT_refused(bench_copy: Any) -> None:
    """The second conjunct, and the whole reason it exists.

    ``c-coax`` is coaxial at as-built and stays coaxial at every value of the
    spigot's radius — flat in every free variable, exactly like ``c-square``.
    But it is *satisfied*: it is not unreachable, it is reached. Refusing a
    solve over a constraint that holds would name a failure that is not there,
    and a ``fit`` inside its declared window has the same shape by
    construction, so the one-conjunct reading would refuse a whole class of
    legitimate solves.
    """
    layout, store = bench_copy
    record = propose_placement(
        layout,
        store,
        param_request(("c-coax",), ("cap.spigot_r",)),
        backend=UnsafeLocalBackend(),
    )
    assert record.verdict != "unresolvable", record.detail
    assert record.reason == ""
    row = next(r for r in _rows(record.verification, "constraints") if r["id"] == "c-coax")
    assert row["satisfied"] is True


def test_the_refusal_is_resolution_time_and_names_a_closed_reason() -> None:
    """It is ``unresolvable(reason)``, not a run-time refusal (``SOLVER.md`` §6.3)."""
    from hephaestus.core.placement import (
        SOLVE_REQUEST_REFUSALS,
        SOLVE_RESOLUTION_REFUSALS,
        SOLVE_RUNTIME_REFUSALS,
    )

    assert "no_free_variable_affects" in SOLVE_RESOLUTION_REFUSALS
    assert "no_free_variable_affects" not in SOLVE_REQUEST_REFUSALS
    assert "no_free_variable_affects" not in SOLVE_RUNTIME_REFUSALS
    assert issubclass(SolveUnresolvable, Exception)
