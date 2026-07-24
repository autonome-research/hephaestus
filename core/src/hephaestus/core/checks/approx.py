"""Deterministic tolerance comparator for CHECKS predicates (§6).

``approx(value, abs=tol)`` builds a comparator usable on either side of
``==``, ``<=`` and ``>=`` against numbers and against fixed-length number
tuples (e.g. a bbox triple). Semantics are pure float arithmetic — the same
inputs always compare identically, with no environment or ordering
dependence:

- ``measured == approx(target, abs=tol)`` — ``|measured - target| <= tol``
  (elementwise for tuples, shapes must match).
- ``measured <= approx(limit, abs=tol)`` — ``measured <= limit + tol``.
- ``measured >= approx(floor, abs=tol)`` — ``measured >= floor - tol``.

:class:`Triple` is the bbox value type returned by the measurement facade:
a ``tuple[float, float, float]`` whose ordering comparisons are elementwise
(``m.bbox("part") <= (380.5, 280.5, 250.5)`` holds iff every axis fits),
never lexicographic. Shape mismatches compare ``False`` rather than raising
so a malformed check fails its report deterministically.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast, final

__all__ = ["Approx", "Triple", "approx"]

#: Default absolute tolerance when ``abs`` is not given.
DEFAULT_ABS_TOL = 1e-9


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _as_number_tuple(value: object) -> tuple[float, ...] | None:
    """``value`` as a tuple of floats when it is a non-string number sequence."""
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return None
    items = cast("Sequence[object]", value)
    out: list[float] = []
    for item in items:
        if not _is_number(item):
            return None
        out.append(float(cast("int | float", item)))
    return tuple(out)


@final
class Triple(tuple[float, float, float]):
    """A bbox triple whose ordering comparisons are elementwise, not lexicographic."""

    __slots__ = ()

    def __new__(cls, x: float, y: float, z: float) -> Triple:
        return super().__new__(cls, (float(x), float(y), float(z)))

    def _elementwise(self, other: object, op: str) -> bool:
        values = _as_number_tuple(other)
        if values is None or len(values) != 3:
            return NotImplemented  # type: ignore[return-value]
        if op == "le":
            return all(a <= b for a, b in zip(self, values, strict=True))
        if op == "ge":
            return all(a >= b for a, b in zip(self, values, strict=True))
        if op == "lt":
            return all(a < b for a, b in zip(self, values, strict=True))
        return all(a > b for a, b in zip(self, values, strict=True))

    def __le__(self, other: object) -> bool:
        if isinstance(other, Approx):
            return NotImplemented  # type: ignore[return-value]
        return self._elementwise(other, "le")

    def __ge__(self, other: object) -> bool:
        if isinstance(other, Approx):
            return NotImplemented  # type: ignore[return-value]
        return self._elementwise(other, "ge")

    def __lt__(self, other: object) -> bool:
        if isinstance(other, Approx):
            return NotImplemented  # type: ignore[return-value]
        return self._elementwise(other, "lt")

    def __gt__(self, other: object) -> bool:
        if isinstance(other, Approx):
            return NotImplemented  # type: ignore[return-value]
        return self._elementwise(other, "gt")

    def __repr__(self) -> str:
        return f"Triple({self[0]!r}, {self[1]!r}, {self[2]!r})"


@final
class Approx:
    """Tolerance comparator; construct via :func:`approx`. Unhashable by design."""

    __slots__ = ("_abs", "_value")

    def __init__(self, value: float | Sequence[float], abs_tol: float) -> None:
        if not _is_number(abs_tol) or abs_tol < 0:
            raise ValueError(f"approx abs tolerance must be a non-negative number, got {abs_tol!r}")
        if _is_number(value):
            self._value: float | tuple[float, ...] = float(cast("int | float", value))
        else:
            values = _as_number_tuple(value)
            if values is None:
                raise ValueError(f"approx value must be a number or a number tuple, got {value!r}")
            self._value = values
        self._abs = float(abs_tol)

    @property
    def value(self) -> float | tuple[float, ...]:
        return self._value

    @property
    def tolerance(self) -> float:
        return self._abs

    def __repr__(self) -> str:
        return f"approx({self._value!r}, abs={self._abs!r})"

    def _pairs(self, other: object) -> list[tuple[float, float]] | None:
        """(self_component, other_component) pairs, or None when shapes mismatch."""
        if isinstance(self._value, tuple):
            values = _as_number_tuple(other)
            if values is None or len(values) != len(self._value):
                return None
            return list(zip(self._value, values, strict=True))
        if not _is_number(other):
            return None
        return [(self._value, float(cast("int | float", other)))]

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Approx):
            return self._value == other._value and self._abs == other._abs
        pairs = self._pairs(other)
        if pairs is None:
            return False  # unsupported operand or shape mismatch: deterministic fail
        return all(abs(mine - theirs) <= self._abs for mine, theirs in pairs)

    def __le__(self, other: object) -> bool:
        """``approx(v) <= x`` (and ``x >= approx(v)``): ``x >= v - tol`` elementwise."""
        pairs = self._pairs(other)
        if pairs is None:
            return False  # unsupported operand or shape mismatch: deterministic fail
        return all(mine - self._abs <= theirs for mine, theirs in pairs)

    def __ge__(self, other: object) -> bool:
        """``approx(v) >= x`` (and ``x <= approx(v)``): ``x <= v + tol`` elementwise."""
        pairs = self._pairs(other)
        if pairs is None:
            return False  # unsupported operand or shape mismatch: deterministic fail
        return all(mine + self._abs >= theirs for mine, theirs in pairs)

    def __hash__(self) -> int:
        raise TypeError("approx objects are unhashable (tolerance equality is not transitive)")


def approx(value: float | Sequence[float], *, abs: float = DEFAULT_ABS_TOL) -> Approx:
    """The §6 comparator: ``approx(value, abs=tol)`` for ``==``/``<=``/``>=``."""
    return Approx(value, abs)
