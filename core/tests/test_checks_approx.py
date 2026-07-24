"""approx comparator semantics (§6), including elementwise tuple/bbox forms."""

from __future__ import annotations

import pytest
from hephaestus.core.checks.approx import Triple, approx


class TestScalarEquality:
    def test_within_tolerance(self) -> None:
        assert approx(0, abs=1e-6) == 0.0
        measured = 1e-7
        assert measured == approx(0, abs=1e-6)  # reflected form used by CHECKS
        assert approx(0, abs=1e-6) == measured

    def test_outside_tolerance(self) -> None:
        measured = 2e-6
        assert (measured == approx(0, abs=1e-6)) is False
        assert (approx(0, abs=1e-6) == measured) is False

    def test_boundary_inclusive(self) -> None:
        assert approx(0, abs=1e-6) == 1e-6

    def test_int_and_float_mix(self) -> None:
        assert approx(5.0, abs=0.0) == 5

    def test_bool_is_not_a_number(self) -> None:
        assert (approx(1.0, abs=0.5) == True) is False  # noqa: E712

    def test_non_number_operand(self) -> None:
        assert (approx(1.0, abs=0.5) == "1.0") is False


class TestScalarOrdering:
    def test_le_upper_bound_with_tolerance(self) -> None:
        measured = 6000.9
        assert measured <= approx(6.0e3, abs=1.0)  # reflected form used by CHECKS
        assert approx(6.0e3, abs=1.0) >= 6000.0
        assert not (approx(6.0e3, abs=1.0) >= 6001.1)

    def test_ge_lower_bound_with_tolerance(self) -> None:
        measured = 1.95
        assert measured >= approx(2.0, abs=0.1)  # reflected form used by CHECKS
        assert approx(2.0, abs=0.1) <= 2.0
        assert not (approx(2.0, abs=0.1) <= 1.85)

    def test_approx_on_left(self) -> None:
        assert approx(2.0, abs=0.1) <= 1.95  # 2.0 - 0.1 <= 1.95
        assert approx(2.0, abs=0.1) >= 2.05


class TestTupleForms:
    def test_tuple_equality_elementwise(self) -> None:
        assert approx((1.0, 2.0, 3.0), abs=1e-9) == (1.0, 2.0, 3.0)
        assert approx((1.0, 2.0, 3.0), abs=0.1) == (1.05, 1.95, 3.0)
        assert (approx((1.0, 2.0, 3.0), abs=0.1) == (1.2, 2.0, 3.0)) is False

    def test_shape_mismatch_is_false(self) -> None:
        assert (approx((1.0, 2.0, 3.0), abs=0.1) == (1.0, 2.0)) is False
        assert not (approx((1.0, 2.0, 3.0), abs=0.1) >= (1.0, 2.0))

    def test_tuple_ordering(self) -> None:
        assert approx((380.5, 280.5, 250.5), abs=0.0) >= (380.0, 280.0, 250.0)
        assert not (approx((380.5, 280.5, 250.5), abs=0.0) >= (381.0, 280.0, 250.0))


class TestTripleBbox:
    def test_elementwise_not_lexicographic(self) -> None:
        # Lexicographic tuple ordering would call (1, 999, 1) <= (2, 1, 2) True.
        assert not (Triple(1.0, 999.0, 1.0) <= (2.0, 1.0, 2.0))
        assert Triple(380.0, 280.0, 250.0) <= (380.5, 280.5, 250.5)

    def test_ge_and_strict(self) -> None:
        assert Triple(3.0, 3.0, 3.0) >= (2.0, 3.0, 1.0)
        assert Triple(3.0, 3.0, 3.0) > (2.0, 2.0, 2.0)
        assert not (Triple(3.0, 3.0, 3.0) > (2.0, 3.0, 2.0))
        assert Triple(1.0, 2.0, 3.0) < (2.0, 3.0, 4.0)

    def test_reflected_plain_tuple(self) -> None:
        assert Triple(2.0, 2.0, 2.0) >= (1.0, 1.0, 1.0)
        assert not (Triple(2.0, 2.0, 2.0) >= (1.0, 5.0, 1.0))

    def test_triple_vs_approx(self) -> None:
        assert Triple(380.4, 280.4, 250.4) <= approx((380.0, 280.0, 250.0), abs=0.5)
        assert not (Triple(381.0, 280.0, 250.0) <= approx((380.0, 280.0, 250.0), abs=0.5))
        assert Triple(380.0, 280.0, 250.0) == approx((380.2, 279.8, 250.0), abs=0.3)

    def test_equality_is_plain_tuple_equality(self) -> None:
        assert Triple(1.0, 2.0, 3.0) == (1.0, 2.0, 3.0)


class TestDeterminismAndHygiene:
    def test_deterministic(self) -> None:
        results = [bool(approx(0, abs=0.1) == 0.05) for _ in range(100)]
        assert results == [True] * 100

    def test_unhashable(self) -> None:
        with pytest.raises(TypeError):
            hash(approx(1.0, abs=0.1))

    def test_invalid_tolerance(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            approx(1.0, abs=-0.1)

    def test_invalid_value(self) -> None:
        with pytest.raises(ValueError, match="number"):
            approx("nope", abs=0.1)  # type: ignore[arg-type]

    def test_repr(self) -> None:
        assert "approx" in repr(approx(1.0, abs=0.1))
        assert repr(Triple(1.0, 2.0, 3.0)) == "Triple(1.0, 2.0, 3.0)"
