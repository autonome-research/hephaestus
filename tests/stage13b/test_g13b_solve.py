# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""G13B clauses 18-20 and 22-26: what the solver says, and what it refuses to say.

Every clause here is about a *named state*. Convergence, non-convergence,
under-determination, discrete multiplicity and an over-constrained floor are
five different facts about a system, and the whole of ``SOLVER.md`` §6 is that
they get five different spellings and that a system with many solutions is
never silently resolved into one.

The two clauses most worth reading are 18's third conjunct and 20. A solver
graded on the residual NUMBER would pass both of the fixtures 20 builds: a
``coincident`` pair lying flush in the right plane and facing the wrong way
measures a gap of exactly zero, and a ``concentric`` pair whose axes cross at
90 deg measures a radial offset of exactly zero. Both are ``satisfied is
False`` through the ordinary engine path, and both keep their
``AssemblyStatus`` row saying ``violated``. That is why §6.1's first conjunct
is read from ``ConstraintResidual.satisfied`` and never from ``measured``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest
from _g13b import (
    ACOS_CONDITIONING_EPS_DEG,
    FIXTURE_KAPPA,
    FULL_RANK_FIXTURES,
    IDENTITY_EPS,
    IDENTITY_PROBE_ROTATION_DEG,
    IDENTITY_PROBE_TRANSLATION_MM,
    JACOBIAN_FD_EPS,
    KAPPA_MATCH_REL,
    SEATED_ROWS,
    TRANSFORM_MATCH_FACTOR,
    kappa_reads_outside_the_pin,
    placement_request,
    rows_of,
    transform_match_eps,
    transform_model,
)
from hephaestus.core.placement import TRANSFORM_SOLVE_VERDICTS, SolveStart, propose_placement

if TYPE_CHECKING:
    from hephaestus.core.project_store.layout import ProjectLayout

    from opstore import OpStore

#: The tolerance every fixture here declares. Named once so the clauses that
#: derive an epsilon from it cannot drift from the one the solver terminated on.
TOL = 1e-4


def _rows(record: Any, part: str = "lug", solution: int = 0) -> tuple[tuple[float, ...], ...]:
    return rows_of(record, part, solution)


def _constraints(record: Any) -> dict[str, dict[str, Any]]:
    verification = cast("dict[str, Any]", record.verification)
    return {
        str(cast("dict[str, Any]", row)["id"]): cast("dict[str, Any]", row)
        for row in cast("list[Any]", verification["constraints"])
    }


def _collateral(record: Any) -> dict[str, dict[str, Any]]:
    verification = cast("dict[str, Any]", record.verification)
    return {
        str(cast("dict[str, Any]", row)["id"]): cast("dict[str, Any]", row)
        for row in cast("list[Any]", verification.get("collateral") or ())
    }


# ==========================================================================
# clause 18: each analytic kind on a FULL-COLUMN-RANK fixture


@pytest.mark.parametrize("kind", sorted(FULL_RANK_FIXTURES))
def test_each_analytic_kind_converges_to_the_hand_computed_transform(
    bench: tuple[ProjectLayout, OpStore], kind: str
) -> None:
    """Clause 18, in the order the clause states it.

    Rank first, and asserted **explicitly** rather than inferred from the
    verdict: a lone mate of any of these four kinds is rank-deficient by
    construction (§6.1 verdict 2, clause 23 below), so a fixture that did not
    remove the null space entirely would have no unique answer to hand-compute
    and this clause would be demanding one from a continuum.

    Then the verdict, then ``satisfied is True`` for **every** objective
    constraint as re-measured by §7 — class predicates included, which
    residual-within-tolerance does not imply — then the residual inside the
    declared tolerance, and only then the transform against the fixture's own
    arithmetic, to ``tol * TRANSFORM_MATCH_FACTOR * kappa`` with the **fixture's
    recorded** ``kappa``. Residual accuracy and solution accuracy are different
    quantities related by the conditioning, and this clause says which one it is
    asserting.

    The recorded ``kappa`` is :data:`_g13b.FIXTURE_KAPPA`, derived there from the
    fixture's own dimensions, and the solver's reported number is held to it
    before it is used for anything. Repaired 2026-09-01: this clause used to
    derive its epsilon from ``record.solver_core["kappa"]``, which let the solver
    set the accuracy budget it was being graded against — the self-grading shape
    §7's independent verification exists to refuse, arriving through the gate's
    own arithmetic instead of through the measurement.
    """
    layout, store = bench
    ids = FULL_RANK_FIXTURES[kind]
    record = propose_placement(layout, store, placement_request(ids, tol=TOL))
    core = cast("dict[str, Any]", record.solver_core)

    assert core["rank"] == 6, f"{kind}: the null space was not removed: {core['null_basis']}"
    assert core["dof_remaining"] == 0
    assert record.verdict == "converged_at_tolerance", record.detail

    rows = _constraints(record)
    assert set(rows) == set(ids)
    for constraint_id in ids:
        row = rows[constraint_id]
        assert row["satisfied"] is True, f"{constraint_id} re-measured unsatisfied: {row}"
        for component in cast("list[Any]", row["components"]):
            entry = cast("dict[str, Any]", component)
            assert entry["within_bound"] is True, entry
            assert float(entry["measured"]) <= float(entry["bound"])

    kappa = FIXTURE_KAPPA[kind]
    assert float(core["kappa"]) == pytest.approx(kappa, rel=KAPPA_MATCH_REL), (
        f"{kind}: the solver reports kappa {core['kappa']!r} against the fixture's "
        f"recorded {kappa!r}; the epsilon below is derived from the RECORDED one, "
        "and a solver whose conditioning has moved this far is not the solver this "
        "fixture's hand-computed answer was recorded for"
    )
    eps = transform_match_eps(kappa, TOL)
    proposed = _rows(record)
    worst = max(abs(proposed[i][j] - SEATED_ROWS[i][j]) for i in range(3) for j in range(4))
    assert worst <= eps, (
        f"{kind}: the proposed transform is {worst:.3g} from the hand-computed one, "
        f"beyond tol*{TRANSFORM_MATCH_FACTOR:.0f}*kappa = {eps:.3g}"
    )


def test_no_epsilon_in_this_suite_is_derived_from_the_solver_s_own_kappa() -> None:
    """Clause 18's sixth conjunct, asserted as a RULE and not only at one call site.

    ``TRANSFORM_MATCH_EPS`` is ``tol * TRANSFORM_MATCH_FACTOR * kappa``, so
    whoever supplies ``kappa`` sets the accuracy budget the gate grades against.
    The Gates preamble says the fixture supplies it — "recorded in the fixture
    beside its hand-computed answer" — and until 2026-09-01 this suite read it
    off ``record.solver_core["kappa"]`` instead, which let the solver widen its
    own tolerance with the gate still green.

    Fixing the one call site would leave the next one free to regress, so the
    rule is asserted over the suite's own source: a ``["kappa"]`` **subscript**
    may appear only inside a function that also names
    :data:`_g13b.KAPPA_MATCH_REL` — that is, only where the reported number is
    being *held to* the recorded one, never where an epsilon is derived from it.
    The scan is by AST rather than by substring so that prose about the rule
    (this docstring included) cannot trip it, and it reads only this directory's
    tracked files.
    """
    offenders = kappa_reads_outside_the_pin(Path(__file__).resolve().parent)
    assert not offenders, (
        "the solver's own reported kappa is read outside the pin that holds it to "
        "the fixture's recorded one:\n" + "\n".join(offenders)
    )


# ==========================================================================
# clause 19: the reformulation IS the measurement, and its Jacobian is right
# where it matters


@pytest.mark.parametrize("kind", sorted(FULL_RANK_FIXTURES))
def test_every_identity_recovers_the_engine_number_to_1e_9(
    bench: tuple[ProjectLayout, OpStore], kind: str, tmp_path: Path
) -> None:
    """Clause 19, first half: the identity, at **1e-9**, on every component.

    A PURE-FUNCTION claim over fixed inputs, which is the only kind of 1e-9
    ``SOLVER.md``'s Gates preamble permits. Both sides are computed from the
    SAME primitives: the two anchor shapes are placed under one rigid transform
    here, in this process; the engine's own
    :func:`~hephaestus.geom.evaluate_residual` measures them; the same placed
    shapes are re-read into the primitives §3.3 reformulates; and the
    reformulation is mapped back through its stated identity. If the two ever
    disagree, the solver is optimising something other than the constraint, and
    no amount of convergence would make its answer evidence.

    Evaluated at a placement a millimetre and a few degrees off the solved one,
    where **both** forms are well conditioned. That is not a dodge, it is the
    clause's own phrase — "a pure function evaluated at fixed given inputs" —
    taken seriously: at the solution the engine's ``acos`` form has lost the
    digits this comparison would need, which the next test measures rather than
    asserts away.
    """
    from hephaestus.geom.solve import rigid_rows

    layout, store = bench
    rows = rigid_rows(IDENTITY_PROBE_TRANSLATION_MM, IDENTITY_PROBE_ROTATION_DEG, (0.0, 0.0, 0.0))
    checked = _assert_identities(
        layout, store, tmp_path, FULL_RANK_FIXTURES[kind], rows, angular_eps=IDENTITY_EPS
    )
    assert checked >= len(FULL_RANK_FIXTURES[kind])


@pytest.mark.parametrize("kind", sorted(FULL_RANK_FIXTURES))
def test_at_the_solution_the_length_identities_stay_exact(
    bench: tuple[ProjectLayout, OpStore], kind: str, tmp_path: Path
) -> None:
    """Clause 19, first half, at the place it matters most — and its honest limit.

    At a converged solution the LENGTH identities (``abs`` for the
    ``coincident`` gap, ``norm`` for the ``concentric`` offset) still reproduce
    the engine's number to 1e-9: they involve no ``acos`` and no cancellation.

    The ANGULAR identities do not, and the reason is the pathology §3.3 exists
    to name. The engine measures an angle as ``degrees(acos(clamp(dot)))``;
    near a mate ``dot`` is within a few ulp of +/-1 and ``acos``'s derivative
    there is unbounded, so one ulp of ``dot`` becomes ``ulp / sin(theta)`` of
    angle. The reformulation has no such amplification — which is exactly why
    the solver iterates on it — so what this measures is the ENGINE's
    remaining precision, not the identity's. The bound is declared, measured
    (1.2e-8 deg at this gate's tightest fixture) and asserted to stay three
    orders below the tightest class-predicate bound any design declares, so it
    can never go vacuous.
    """
    from hephaestus.geom.constraints import COINCIDENT_NORMAL_EPS_DEG, CONCENTRIC_AXIS_EPS_DEG

    assert ACOS_CONDITIONING_EPS_DEG < COINCIDENT_NORMAL_EPS_DEG / 100.0
    assert ACOS_CONDITIONING_EPS_DEG < CONCENTRIC_AXIS_EPS_DEG / 100.0

    layout, store = bench
    ids = FULL_RANK_FIXTURES[kind]
    record = propose_placement(layout, store, placement_request(ids, tol=TOL))
    checked = _assert_identities(
        layout,
        store,
        tmp_path,
        ids,
        _rows(record),
        angular_eps=ACOS_CONDITIONING_EPS_DEG,
    )
    assert checked >= len(ids)


def _assert_identities(
    layout: ProjectLayout,
    store: OpStore,
    scratch: Path,
    ids: tuple[str, ...],
    rows: tuple[tuple[float, ...], ...],
    *,
    angular_eps: float,
) -> int:
    """Every §3.3 identity for ``ids``, at one rigid placement of the free part.

    Length identities are always held to :data:`IDENTITY_EPS`; angular ones to
    ``angular_eps``, which the two callers set to the same 1e-9 away from the
    solution and to the measured ``acos`` bound at it.
    """
    from hephaestus.core.project_store.constraints import ConstraintSet
    from hephaestus.geom import cylinder_of, direction_of, evaluate_residual, plane_of
    from hephaestus.geom.kinematics import RigidTransform
    from hephaestus.geom.solve import (
        orthonormal_complement,
        recover_measurement,
        residual_coincident_gap,
        residual_coincident_normals,
        residual_concentric_offset,
        residual_cross,
        residual_perpendicular,
    )

    transform = RigidTransform(rows=tuple(tuple(float(v) for v in row) for row in rows))  # pyright: ignore[reportArgumentType]
    entries = ConstraintSet(layout, store).state().by_id
    shapes = _placed_anchor_shapes(layout, store, scratch, entries, ids, transform)
    checked = 0
    for constraint_id in ids:
        entry = entries[constraint_id]
        shape_a, shape_b = shapes[constraint_id]
        residual = evaluate_residual(entry.kind, shape_a, shape_b, dict(entry.values))
        values = dict(residual.values)
        pairs: list[tuple[str, tuple[float, ...], float, float]]
        if entry.kind == "coincident":
            plane_a = plane_of(shape_a, kind=entry.kind, side="a")
            plane_b = plane_of(shape_b, kind=entry.kind, side="b")
            pairs = [
                (
                    "abs",
                    tuple(residual_coincident_gap(plane_a.center, plane_a.normal, plane_b.center)),
                    residual.measured,
                    IDENTITY_EPS,
                ),
                (
                    "asin_norm_half2",
                    tuple(residual_coincident_normals(plane_a.normal, plane_b.normal)),
                    float(values["normal_deviation_deg"]),
                    angular_eps,
                ),
            ]
        elif entry.kind == "concentric":
            cyl_a = cylinder_of(shape_a, kind=entry.kind, side="a")
            cyl_b = cylinder_of(shape_b, kind=entry.kind, side="b")
            # ANY orthonormal complement of a's axis gives the same norm, which
            # is why the identity is a property of the reformulation and not of
            # the frame the solver happened to transport.
            u_a, v_a = orthonormal_complement(cyl_a.axis, (0.0, 1.0, 0.0))
            pairs = [
                (
                    "norm",
                    tuple(residual_concentric_offset(cyl_a.axis_point, u_a, v_a, cyl_b.axis_point)),
                    residual.measured,
                    IDENTITY_EPS,
                ),
                (
                    "asin_norm",
                    tuple(residual_cross(cyl_a.axis, cyl_b.axis)),
                    float(values["axis_angle_deg"]),
                    angular_eps,
                ),
            ]
        else:
            dir_a, _what_a = direction_of(shape_a, kind=entry.kind, side="a")
            dir_b, _what_b = direction_of(shape_b, kind=entry.kind, side="b")
            parallel = entry.kind == "parallel"
            pairs = [
                (
                    "asin_norm" if parallel else "asin_abs",
                    tuple(
                        residual_cross(dir_a, dir_b)
                        if parallel
                        else residual_perpendicular(dir_a, dir_b)
                    ),
                    residual.measured,
                    angular_eps,
                ),
            ]
        for identity, raw, engine, eps in pairs:
            recovered = recover_measurement(cast("Any", identity), raw)
            assert abs(recovered - engine) <= eps, (
                f"{constraint_id} ({identity}): the reformulation recovers {recovered!r} "
                f"where the engine measured {engine!r}"
            )
            checked += 1
    return checked


def _placed_anchor_shapes(
    layout: ProjectLayout,
    store: OpStore,
    scratch: Path,
    entries: dict[str, Any],
    ids: tuple[str, ...],
    transform: Any,
) -> dict[str, tuple[Any, Any]]:
    """Both anchors of each constraint, placed under the proposal, in THIS process.

    The free part rides the proposed transform; every other part is ground and
    sits where its script put it. A **placed copy** either way
    (``geom/kinematics.py:763-782``): the loaded artifact is never mutated.
    """
    from hephaestus.core.assembly import AnchorResolver
    from hephaestus.core.project_store.publication import Publisher
    from hephaestus.geom import transformed_shape

    resolver = AnchorResolver(layout, store, Publisher(layout, store), scratch)
    out: dict[str, tuple[Any, Any]] = {}
    for constraint_id in ids:
        entry = entries[constraint_id]
        placed: list[Any] = []
        for text in (entry.a, entry.b):
            part, _sep, selector = str(text).partition(":")
            geometry, resolution = resolver.locate(part, selector or "part")
            shape = geometry.shape_for(resolution)
            placed.append(transformed_shape(shape, transform) if part == "lug" else shape)
        out[constraint_id] = (placed[0], placed[1])
    return out


@pytest.mark.parametrize("kind", sorted(FULL_RANK_FIXTURES))
def test_the_analytic_jacobian_agrees_with_a_difference_at_the_solution(
    bench: tuple[ProjectLayout, OpStore], kind: str, tmp_path: Path
) -> None:
    """Clause 19, second half: analytic vs central difference, AT the solution.

    Evaluated at a point **within one declared tolerance of the solution**,
    which is the neighbourhood the clause insists on and the reason it exists:
    the ``abs`` / ``acos`` / norm forms of ``geom/constraints.py`` are
    non-smooth or unbounded exactly there, so a Jacobian checked at a
    comfortable distance would have proved nothing about the place the
    iteration actually finishes.
    """
    layout, store = bench
    request = placement_request(FULL_RANK_FIXTURES[kind], tol=TOL)
    record = propose_placement(layout, store, request)
    solution = [float(value) for value in cast("list[Any]", record.solver_core["x"])]
    # Within one declared tolerance of it, and off-axis, so no column is
    # differenced at a point where its own residual happens to vanish.
    probe = [value + TOL * (0.4 if index % 2 else -0.6) for index, value in enumerate(solution)]

    model = transform_model(layout, store, request, tmp_path)
    analytic = model.jacobian(probe)
    assert analytic is not None, "the transform model must supply analytic rows (NW4)"

    step = 1e-7
    for column in range(len(probe)):
        plus = list(probe)
        plus[column] += step
        minus = list(probe)
        minus[column] -= step
        forward = [value for block in model.evaluate(plus) for value in block]
        backward = [value for block in model.evaluate(minus) for value in block]
        for row, (a, b) in enumerate(zip(forward, backward, strict=True)):
            difference = (a - b) / (2.0 * step)
            exact = float(analytic[row][column])
            scale = max(1.0, abs(exact), abs(difference))
            assert abs(exact - difference) / scale <= JACOBIAN_FD_EPS, (
                f"{kind}: row {row}, column {column}: analytic {exact!r} against "
                f"difference {difference!r}"
            )


# ==========================================================================
# clause 20: a class predicate is not a footnote


def test_a_zero_gap_with_same_facing_normals_is_not_a_success(
    bench: tuple[ProjectLayout, OpStore],
) -> None:
    """Clause 20, the negative: gap zero, normals same-facing, NOT converged.

    ``c-invert`` mates the plate's top face against the lug's TOP face, so the
    outward normals both point +Z and ``normal_deviation_deg`` is 180. Its gap
    closes perfectly by translation — a solver graded on the residual number
    reports success — and the rotations are boxed to zero, so no free degree of
    freedom can flip the part. The engine measures ``satisfied is False`` and
    the row would still read ``violated``.
    """
    layout, store = bench
    record = propose_placement(
        layout,
        store,
        placement_request(
            ("c-invert", "c-bore", "c-face", "c-square"),
            tol=TOL,
            box={f"lug.{axis}": (0.0, 0.0) for axis in ("rx", "ry", "rz")},
        ),
    )
    assert record.verdict == "no_placement_found_from_starts", record.detail
    assert record.verdict != "converged_at_tolerance"

    row = _constraints(record)["c-invert"]
    assert row["satisfied"] is False
    values = dict(cast("list[Any]", row["values"]))
    assert float(cast("float", values["normal_deviation_deg"])) == pytest.approx(180.0, abs=1e-6)
    # The primary closed: this is precisely the trap, not a solver that failed
    # to move.
    assert abs(float(cast("float", row["measured"]))) <= TOL

    # The declared bound is recorded BESIDE the value, so a reader sees which
    # conjunct failed rather than inferring it from a number (§7.4).
    predicate = next(
        cast("dict[str, Any]", component)
        for component in cast("list[Any]", row["components"])
        if cast("dict[str, Any]", component)["role"] == "class_predicate"
    )
    assert predicate["unit"] == "deg"
    assert predicate["bound"] == pytest.approx(1e-3)
    assert predicate["within_bound"] is False
    # And the bounds that denied the flip are named, never clamped in silence.
    assert set(cast("list[Any]", record.solver_core["limits_active"])) == {
        "lug.rx",
        "lug.ry",
        "lug.rz",
    }


def test_given_a_free_rotational_dof_the_solver_flips_the_part(
    bench: tuple[ProjectLayout, OpStore],
) -> None:
    """Clause 20, the mirror positive: the class predicate STEERS the iteration.

    The same fixture with the rotations released and a declared start a few
    degrees off the same-facing configuration. The solver turns the lug over
    and returns ``converged_at_tolerance`` with ``satisfied is True`` — which
    proves the normal-sum residual is in the objective (§3.1) rather than only
    failing the answer at verification. A solver blind to the normals would
    burn its whole budget converging on the gap and be refused every time, and
    a refusal produced unconditionally for a whole fixture class is a design
    error wearing a safety net's clothes.

    The declared start is not a workaround: the exactly-same-facing
    configuration is a stationary MAXIMUM of the normal term (its gradient is
    zero by symmetry), and §5 makes starts declared and reported precisely
    because a local method's basin is a fact about the request.
    """
    layout, store = bench
    record = propose_placement(
        layout,
        store,
        placement_request(
            ("c-invert", "c-bore", "c-face", "c-square"),
            tol=TOL,
            starts=(SolveStart(), SolveStart(id="tilted", values={"lug.rx": 15.0})),
        ),
    )
    assert record.verdict == "converged_at_tolerance", record.detail
    row = _constraints(record)["c-invert"]
    assert row["satisfied"] is True
    values = dict(cast("list[Any]", row["values"]))
    assert float(cast("float", values["normal_deviation_deg"])) == pytest.approx(0.0, abs=1e-6)
    # It really turned the part over: the rotation block's Z column is -Z.
    rows = _rows(record)
    assert rows[2][2] == pytest.approx(-1.0, abs=1e-9)
    assert cast("list[Any]", record.placements[0]["parts"])[0]["angle_deg"] == pytest.approx(
        180.0, abs=1e-6
    )


def test_the_concentric_analogue_zero_offset_with_tilted_axes(
    bench: tuple[ProjectLayout, OpStore],
) -> None:
    """Clause 20's ``concentric`` analogue, asserted alongside.

    The sleeve's bore runs along X and the plate's along Z. The radial offset
    closes to zero — the two axis LINES genuinely meet — while the axes stay 90
    deg apart, so ``satisfied`` is False with the primary inside tolerance.
    Same trap, other class predicate.
    """
    layout, store = bench
    record = propose_placement(
        layout,
        store,
        placement_request(
            ("c-tilt",),
            free=("sleeve",),
            tol=TOL,
            box={f"sleeve.{axis}": (0.0, 0.0) for axis in ("rx", "ry", "rz")},
        ),
    )
    assert record.verdict != "converged_at_tolerance"
    row = _constraints(record)["c-tilt"]
    assert row["satisfied"] is False
    assert abs(float(cast("float", row["measured"]))) <= TOL
    values = dict(cast("list[Any]", row["values"]))
    assert float(cast("float", values["axis_angle_deg"])) == pytest.approx(90.0, abs=1e-6)


# ==========================================================================
# clause 22: the excluded kinds are EVALUATED at the solution


def test_a_proposal_that_satisfies_four_mates_reports_the_interference_it_causes(
    bench: tuple[ProjectLayout, OpStore],
) -> None:
    """Clause 22: converged on all four analytic mates, ``no_interference`` violated.

    The plate's bore is Ø8 and the post standing in it is Ø9, so the four mates
    are satisfiable only by driving the lug's bore onto the post. The solve
    converges — every objective constraint re-measures ``satisfied is True`` —
    and the verification block reports ``c-clear`` violated beside them.

    That is the honest answer and the reason the plateau kinds are not silently
    dropped: they cannot steer the iteration (``measure.clearance`` is exactly
    0.0 over the whole overlapping region, so a solver started in penetration
    has no descent information at all), but they are measured at whatever
    solution is reached and reported.
    """
    layout, store = bench
    record = propose_placement(
        layout, store, placement_request(("c-seat", "c-bore", "c-face", "c-square"), tol=TOL)
    )
    assert record.verdict == "converged_at_tolerance", record.detail
    rows = _constraints(record)
    assert len(rows) == 4
    assert all(row["satisfied"] is True for row in rows.values()), rows

    collateral = _collateral(record)
    assert collateral["c-clear"]["kind"] == "no_interference"
    assert collateral["c-clear"]["satisfied"] is False, collateral["c-clear"]
    assert float(cast("float", collateral["c-clear"]["measured"])) > 0.0
    # All eight kinds reach the verification block, not the four that steered.
    assert {row["kind"] for row in [*rows.values(), *collateral.values()]} == {
        "coincident",
        "concentric",
        "parallel",
        "perpendicular",
        "no_interference",
        "clearance_min",
        "distance",
        "fit",
    }


# ==========================================================================
# clause 23: under-determination is where the single-kind systems land


def test_a_lone_concentric_pair_names_its_two_free_directions(
    bench: tuple[ProjectLayout, OpStore],
) -> None:
    """Clause 23: ``dof_remaining == 2``, axial translation and axial rotation.

    A lone ``concentric`` mate leaves the axis's own translation and its own
    rotation free — the mathematics, not the fixture's luck — so the verdict is
    ``underdetermined_at_tolerance`` and NOT ``converged_at_tolerance``. One
    member of a positive-dimensional solution set is being shown, and reporting
    it as *the* answer is a claim the mathematics does not support.

    The basis is asserted by its COMPONENTS rather than by its prose label: the
    plate's bore runs along Z, so "axial translation and axial rotation about
    the measured axis" is exactly ``lug.tz`` and ``lug.rz``, and nothing else.
    """
    layout, store = bench
    record = propose_placement(layout, store, placement_request(("c-bore",), tol=TOL))
    core = cast("dict[str, Any]", record.solver_core)
    assert record.verdict == "underdetermined_at_tolerance", record.detail
    assert core["dof_remaining"] == 2
    assert _named_directions(core) == {"lug.tz", "lug.rz"}
    row = _constraints(record)["c-bore"]
    assert row["satisfied"] is True
    assert abs(float(cast("float", row["measured"]))) <= TOL


def test_a_lone_coincident_pair_names_its_in_plane_se2(
    bench: tuple[ProjectLayout, OpStore],
) -> None:
    """Clause 23: ``dof_remaining == 3``, the in-plane ``SE(2)``.

    A lone ``coincident`` mate on a +Z plane leaves both in-plane translations
    and the rotation about the plane normal free. No unique transform is
    demanded of it anywhere in this gate, which is the point of separating this
    clause from clause 18.
    """
    layout, store = bench
    record = propose_placement(layout, store, placement_request(("c-seat",), tol=TOL))
    core = cast("dict[str, Any]", record.solver_core)
    assert record.verdict == "underdetermined_at_tolerance", record.detail
    assert core["dof_remaining"] == 3
    assert _named_directions(core) == {"lug.tx", "lug.ty", "lug.rz"}
    row = _constraints(record)["c-seat"]
    assert row["satisfied"] is True
    assert abs(float(cast("float", row["measured"]))) <= TOL


def _named_directions(core: dict[str, Any], *, eps: float = 1e-6) -> set[str]:
    """Which variables the reported null-space basis actually names."""
    out: set[str] = set()
    for direction in cast("list[Any]", core["null_basis"]):
        entry = cast("dict[str, Any]", direction)
        assert entry["label"], "a null direction with no label is a count, not a name"
        for name, value in cast("list[Any]", entry["components"]):
            if abs(float(cast("float", value))) > eps:
                out.add(str(name))
    return out


# ==========================================================================
# clause 24: discrete multiplicity, all returned, none chosen


def test_two_starts_that_converge_apart_return_both_and_choose_neither(
    bench: tuple[ProjectLayout, OpStore],
) -> None:
    """Clause 24: ``multiple_solutions_from_starts`` on the 180-degree flip.

    ``parallel`` folds, so the lug seated at 0 deg about the bore and the lug
    seated at 180 deg satisfy every declared mate identically. Rank tells you
    nothing about that — both solutions are full column rank — which is why
    discrete multiplicity has to surface here or nowhere.

    Both are returned, ranked by distance from as-built, and **neither is
    marked chosen**: picking one would be a design decision the mathematics
    does not make.
    """
    layout, store = bench
    record = propose_placement(
        layout,
        store,
        placement_request(
            ("c-seat", "c-bore", "c-face"),
            tol=TOL,
            starts=(SolveStart(), SolveStart(id="flipped", values={"lug.rz": 170.0})),
        ),
    )
    assert record.verdict == "multiple_solutions_from_starts", record.detail
    assert len(record.placements) == 2
    assert [placement["chosen"] for placement in record.placements] == [False, False]
    # Ranked by distance from as-built, nearest first.
    distances = [float(cast("float", p["distance_from_as_built"])) for p in record.placements]
    assert distances == sorted(distances)
    # And they really are two different placements, not one reported twice.
    assert _rows(record, solution=0)[0][0] == pytest.approx(1.0, abs=1e-6)
    assert _rows(record, solution=1)[0][0] == pytest.approx(-1.0, abs=1e-6)
    # Every start that produced one is named on it.
    assert {str(p["from_start"]) for p in record.placements} == {"as_built", "flipped"}


# ==========================================================================
# clause 25: over-constrained, at a floor, with no culprit named


def test_a_provably_inconsistent_pair_reports_a_floor_and_blames_nobody(
    bench: tuple[ProjectLayout, OpStore],
) -> None:
    """Clause 25: ``overconstrained_at_residual_floor``, stationarity asserted.

    ``c-face`` wants the lug's +X face parallel to the plate's +X face and
    ``c-cross`` wants it parallel to the plate's +Y face. One direction cannot
    be parallel to two perpendicular ones; the least-squares floor sits between
    them at full column rank, which is what separates "the declared constraints
    disagree with each other" from "this start did not get there".

    **No culprit constraint is named.** Identifying a minimal inconsistent
    subset is a different computation nobody has run, and naming one on a whim
    would be a verdict about the author's intent — so the clause asserts the
    absence as a field, not as a hope.
    """
    layout, store = bench
    record = propose_placement(
        layout, store, placement_request(("c-seat", "c-bore", "c-face", "c-cross"), tol=TOL)
    )
    core = cast("dict[str, Any]", record.solver_core)
    assert record.verdict == "overconstrained_at_residual_floor", record.detail
    assert core["rank"] == 6 and core["dof_remaining"] == 0
    assert core["termination"] == "stationary"
    assert float(cast("float", core["stationarity"])) <= 1e-5, core
    assert float(cast("float", core["weighted_inf_norm"])) > TOL

    # The per-constraint residuals at the floor are attached...
    rows = _constraints(record)
    assert set(rows) == {"c-seat", "c-bore", "c-face", "c-cross"}
    assert rows["c-cross"]["satisfied"] is False

    # ...and no FIELD anywhere names one. Asserted as an absent field rather
    # than as an absent word, because the detail says in prose that no culprit
    # is named, and a word search would trip on the disclaimer itself.
    document = record.to_json()
    for field in ("culprit", "culprits", "conflicting_constraint", "blame", "responsible"):
        assert field not in document, field
        assert field not in cast("dict[str, Any]", document["solver_core"]), field
        assert field not in cast("dict[str, Any]", document["verification"]), field
    assert "No culprit constraint is named" in record.detail


# ==========================================================================
# clause 26: a local method's silence is never infeasibility


def test_no_placement_found_names_every_start_and_never_says_infeasible(
    bench: tuple[ProjectLayout, OpStore],
) -> None:
    """Clause 26: verdict 4 from a deliberately distant start.

    Two declared starts, one of them 120 deg away, neither reaching the
    declared tolerance. The record names **every** start tried, because
    non-convergence is evidence about the basins that were searched and about
    nothing else — and the spellings "infeasible", "impossible" and "no
    solution exists" appear nowhere in the payload, because this run has not
    earned any of them.
    """
    layout, store = bench
    record = propose_placement(
        layout,
        store,
        placement_request(
            ("c-face", "c-cross"),
            tol=TOL,
            starts=(SolveStart(), SolveStart(id="far", values={"lug.rz": 120.0})),
        ),
    )
    assert record.verdict == "no_placement_found_from_starts", record.detail
    assert "as_built" in record.detail and "far" in record.detail
    blob = json.dumps(record.to_json()).lower()
    for forbidden in ("infeasible", "impossible", "no solution exists", "unsolvable"):
        assert forbidden not in blob, f"the payload says {forbidden!r}"
    # Still a member of the closed six, never a refusal spelling.
    assert record.verdict in TRANSFORM_SOLVE_VERDICTS


# ==========================================================================
# clause 43: 8C and Stage 9 wire shapes, byte-for-byte unchanged


#: The 8C / Stage 9 wire shapes as they stood before Stage 13, pinned as
#: literals. ``SOLVER.md`` §12: "No change to ``AssemblyStatus``,
#: ``MotionStatus``, or any wire shape either produces — 8C and Stage 9
#: evidence stays byte-for-byte valid." A stage that quietly added a field to
#: either would invalidate every recorded status those gates assert against,
#: and it would do it silently, which is why the pin is a literal set rather
#: than a comparison against something Stage 13 also produces.
ASSEMBLY_STATUS_KEYS = frozenset(
    {"artifact_refs", "blocking", "constraints", "counts", "generation", "stale"}
)
UNBOUND_OUTCOME_KEYS = frozenset(
    {"a", "b", "detail", "id", "kind", "note", "provenance", "reason", "residual", "state"}
)
MOTION_STATUS_KEYS = frozenset(
    {
        "artifact_refs",
        "blocking",
        "counts",
        "joint_generation",
        "joints",
        "pose_generation",
        "poses",
        "stale",
    }
)


def test_the_8c_and_stage_9_wire_shapes_are_unchanged(
    bench: tuple[ProjectLayout, OpStore],
) -> None:
    """Clause 43: Stage 13 added no field to either status.

    The ``pose_residuals`` rule is asserted in both directions, because it is
    the one field either shape ever grew and the 9A gate pinned its absence: an
    UNBOUND entry serialises without it (the byte-for-byte 8C outcome), and a
    pose-BOUND one carries it. A Stage 13 field on either would be invisible to
    a reader and fatal to every recorded status.
    """
    from hephaestus.core.assembly import AssemblyEvaluator
    from hephaestus.core.motion import check_motion

    layout, store = bench
    status = AssemblyEvaluator(layout, store).evaluate(["c-seat", "c-posed"]).to_json()
    assert set(status) == ASSEMBLY_STATUS_KEYS

    rows = {
        str(cast("dict[str, Any]", row)["id"]): cast("dict[str, Any]", row)
        for row in cast("list[Any]", status["constraints"])
    }
    assert set(rows["c-seat"]) == UNBOUND_OUTCOME_KEYS
    assert "pose_residuals" not in rows["c-seat"]
    assert set(rows["c-posed"]) == UNBOUND_OUTCOME_KEYS | {"pose_residuals"}

    assert set(check_motion(layout, store).to_json()) == MOTION_STATUS_KEYS
