# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""G13A clauses 1 and 9, plus the §3.3 identities: pure arithmetic, no kernel.

Two gate clauses live here because both are claims about *arithmetic with no
iteration in it*, which is the only kind of claim the ``SOLVER.md`` Gates
preamble lets a clause assert to **1e-9**:

* **clause 1** — ``forward_kinematics`` at *fixed given* joint values
  reproduces a hand-computed transform for a two-revolute chain, with no
  solver anywhere in the call (the G9A clause shape, restated so this suite
  owns it);
* **clause 9** — ``rank_undecidable`` fires on a Jacobian constructed to
  straddle ``RANK_TOL_REL``, and does **not** fire on either side of that
  straddle. A guessed rank silently decides whether an answer is unique, which
  is the one thing ``SOLVER.md`` §6 exists to prevent.

The §3.3 identity assertions ride along. They are formally G13B clause 19, but
the identities are what make the whole verification argument work — if the
reformulation and the measurement disagree, the solver is optimising something
other than the constraint — and asserting them here costs nothing and closes
the gap between "13A ships the reformulation" and "a gate proves it is the
same measurement".
"""

from __future__ import annotations

import math

import pytest
from hephaestus.geom import solve as gs
from hephaestus.geom.kinematics import JointFrame, JointLimits, forward_kinematics

#: The one 1e-9 this gate permits, and it is a claim about arithmetic
#: (``SOLVER.md`` Gates preamble: never of a *solved* quantity).
PURE_EPS = 1e-9


def _chain() -> tuple[JointFrame, ...]:
    """A two-revolute planar chain: Z axes through x = 0 and x = 40."""
    return (
        JointFrame(
            id="j1",
            kind="revolute",
            parent="a",
            child="b",
            point=(0.0, 0.0, 0.0),
            direction=(0.0, 0.0, 1.0),
            limits=JointLimits(min=-180.0, max=180.0),
        ),
        JointFrame(
            id="j2",
            kind="revolute",
            parent="b",
            child="c",
            point=(40.0, 0.0, 0.0),
            direction=(0.0, 0.0, 1.0),
            limits=JointLimits(min=-180.0, max=180.0),
        ),
    )


def test_forward_kinematics_reproduces_the_hand_computed_chain() -> None:
    """Clause 1: FK as a PURE FUNCTION at fixed given values, to 1e-9.

    Hand-computed, and small enough to check by eye. At ``j1 = +90``,
    ``j2 = -90`` the two rotations cancel, so ``c``'s rotation block is the
    identity; its translation is ``R(90) applied to (40, 40, 0)``, the second
    joint's own off-axis translation, which is ``(-40, 40, 0)``. No solver is
    anywhere in this call — the module under test here is Stage 9's, unchanged.
    """
    world = forward_kinematics(_chain(), {"j1": 90.0, "j2": -90.0})
    expected = (
        (1.0, 0.0, 0.0, -40.0),
        (0.0, 1.0, 0.0, 40.0),
        (0.0, 0.0, 1.0, 0.0),
    )
    for row, want in zip(world["c"].rows, expected, strict=True):
        for got, target in zip(row, want, strict=True):
            assert abs(got - target) <= PURE_EPS, (world["c"].rows, expected)
    # And the intermediate link, so a wrong composition ORDER cannot pass by
    # cancelling in the leaf: `b` is a pure +90 rotation about the origin.
    assert abs(world["b"].rows[0][1] + 1.0) <= PURE_EPS
    assert abs(world["b"].rows[1][0] - 1.0) <= PURE_EPS
    assert all(abs(world["b"].rows[i][3]) <= PURE_EPS for i in range(3))


# --------------------------------------------------------------------------
# clause 9: the rank has to be DECIDED, or refused


def _diagonal(*values: float) -> list[list[float]]:
    return [
        [value if i == j else 0.0 for j in range(len(values))] for i, value in enumerate(values)
    ]


def test_rank_undecidable_fires_on_a_pivot_that_straddles_the_threshold() -> None:
    """Clause 9: a pivot inside ``RANK_MARGIN_REL`` of the threshold is refused.

    The threshold is ``RANK_TOL_REL`` relative to the largest pivot. A second
    pivot at five times the threshold is *above* it — so a naive reader would
    call the matrix full rank — but it sits inside the declared margin, and
    calling it either way would silently answer "is this solution unique?".
    """
    threshold = gs.RANK_TOL_REL
    with pytest.raises(gs.SolveRefused) as excinfo:
        gs.null_space(_diagonal(1.0, 5.0 * threshold), ["u", "v"])
    assert excinfo.value.reason == "rank_undecidable"
    assert "RANK_MARGIN_REL" in excinfo.value.message


def test_rank_is_decided_on_both_sides_of_the_straddle() -> None:
    """The negative's mirror: the refusal is not simply always on.

    Without this, a solver that refused every rank would pass the clause above
    while being useless — the refusal has to be a discrimination, not a mood.
    """
    rank, basis, kappa = gs.null_space(_diagonal(1.0, 1.0), ["u", "v"])
    assert (rank, basis) == (2, ())
    assert kappa == pytest.approx(1.0)

    rank, basis, _kappa = gs.null_space(_diagonal(1.0, 1e-14), ["u", "v"])
    assert rank == 1
    assert len(basis) == 1
    # The free direction is NAMED, not merely counted (``SOLVER.md`` §6.1
    # verdict 2): a reader has to see what is free.
    assert basis[0].components[0][0] == "v"
    assert "v" in basis[0].label


def test_a_wide_system_reports_its_null_space_rather_than_a_unique_answer() -> None:
    """Two equations, three unknowns: one free direction, named."""
    rows = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
    rank, basis, _kappa = gs.null_space(rows, ["x", "y", "z"])
    assert rank == 2
    assert len(basis) == 1
    assert [name for name, _value in basis[0].components] == ["z"]


# --------------------------------------------------------------------------
# the §3.3 identities: the reformulation IS the same measurement


def _norm(vector: tuple[float, ...]) -> float:
    return math.sqrt(sum(value * value for value in vector))


def test_the_coincident_gap_identity_recovers_the_engine_number() -> None:
    """``|r| == measured`` for the signed plane gap."""
    residual = gs.residual_coincident_gap((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), (3.0, 4.0, -2.5))
    assert gs.recover_measurement("abs", residual) == pytest.approx(2.5, abs=PURE_EPS)


@pytest.mark.parametrize("deviation_deg", [0.0, 1e-3, 7.5, 90.0, 179.0, 180.0])
def test_the_coincident_normal_identity_recovers_normal_deviation_deg(
    deviation_deg: float,
) -> None:
    """``2*degrees(asin(‖n_a + n_b‖/2)) == normal_deviation_deg``.

    ``normal_deviation_deg`` is the engine's distance from a true 180 deg
    (``geom/constraints.py:658``), so the fixture builds normals at exactly
    that separation and asks the identity for the number back.
    """
    angle = math.radians(180.0 - deviation_deg)
    n_a = (0.0, 0.0, 1.0)
    n_b = (math.sin(angle), 0.0, math.cos(angle))
    residual = gs.residual_coincident_normals(n_a, n_b)
    assert gs.recover_measurement("asin_norm_half2", residual) == pytest.approx(
        deviation_deg, abs=1e-8
    )


@pytest.mark.parametrize("folded_deg", [0.0, 1e-3, 12.0, 45.0, 89.0, 90.0])
def test_the_angular_identities_recover_the_engine_numbers(folded_deg: float) -> None:
    """``parallel`` reads the folded angle; ``perpendicular`` reads |90 - folded|."""
    angle = math.radians(folded_deg)
    d_a = (1.0, 0.0, 0.0)
    d_b = (math.cos(angle), math.sin(angle), 0.0)
    parallel = gs.residual_cross(d_a, d_b)
    assert gs.recover_measurement("asin_norm", parallel) == pytest.approx(folded_deg, abs=1e-8)
    square = gs.residual_perpendicular(d_a, d_b)
    assert gs.recover_measurement("asin_abs", square) == pytest.approx(
        abs(90.0 - folded_deg), abs=1e-8
    )


def test_the_concentric_offset_identity_is_the_engine_norm() -> None:
    """``‖r‖ == measured``: the 2-vector in the axis's perpendicular frame."""
    axis = (0.0, 0.0, 1.0)
    u, v = gs.orthonormal_complement(axis, (1.0, 0.0, 0.0))
    residual = gs.residual_concentric_offset((0.0, 0.0, 0.0), u, v, (3.0, 4.0, 17.0))
    assert gs.recover_measurement("norm", residual) == pytest.approx(5.0, abs=PURE_EPS)
    # The axial component is invisible to it, which is what "radial" means.
    assert _norm(residual) == pytest.approx(5.0, abs=PURE_EPS)


def test_the_coincident_normal_scale_is_the_derivative_at_zero_not_the_spec_parenthetical() -> None:
    """DEVIATION, recorded as a clause: ``SOLVER.md`` §3.3's ``2*180/pi`` is wrong.

    The leading factor of a reformulated component is the derivative of its
    identity at zero. For ``2*degrees(asin(‖r‖/2))`` that is
    ``2 * (180/pi) * (1/2) == 180/pi`` — the outer 2 and the inner ``/2``
    cancel. §3.3's parenthetical "``or 2*180/pi`` for the coincident normal
    pair" double-counts the 2, and a solver that used it would weight a
    ``coincident`` normal residual at twice its own degrees: exactly the silent
    normalization §3.4 forbids. This clause pins the arithmetic so the
    deviation cannot be quietly reverted to match the prose.
    """
    assert gs.component_scale("asin_norm_half2") == pytest.approx(180.0 / math.pi)
    for identity in ("asin_norm", "asin_abs"):
        assert gs.component_scale(identity) == pytest.approx(180.0 / math.pi)
    for identity in ("abs", "norm"):
        assert gs.component_scale(identity) == 1.0
    # And the derivative claim itself, measured rather than asserted.
    step = 1e-7
    measured = gs.recover_measurement("asin_norm_half2", (step, 0.0, 0.0))
    assert measured / step == pytest.approx(180.0 / math.pi, rel=1e-6)
