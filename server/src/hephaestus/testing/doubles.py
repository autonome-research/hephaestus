"""Deterministic clock/liveness doubles for opstore- and bridge-level tests.

:class:`FakeClock` replaces wall time so lease/deadline arithmetic is exercised
by advancing a number rather than by sleeping; :class:`FakeLiveness` replaces
the pid-liveness oracle so a test can declare an owner dead without killing a
process. Both are accepted by ``OpStore.create``/``OpStore.open`` wherever the
production clock and liveness oracle are.
"""

from __future__ import annotations

from opstore.types import OwnerId

__all__ = ["FakeClock", "FakeLiveness", "owner"]


class FakeClock:
    """A manually-advanced clock (unix seconds)."""

    def __init__(self, start: float = 1_000_000.0) -> None:
        self._t = start

    def now(self) -> float:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t += seconds

    def set(self, t: float) -> None:
        self._t = t


class FakeLiveness:
    """A liveness oracle whose per-owner verdicts are set by the test."""

    def __init__(self, *, default: bool = True) -> None:
        self._default = default
        self._dead: set[tuple[int, int]] = set()

    def kill(self, owner: OwnerId) -> None:
        self._dead.add((owner.pid, owner.pid_start_ns))

    def revive(self, owner: OwnerId) -> None:
        self._dead.discard((owner.pid, owner.pid_start_ns))

    def is_alive(self, owner: OwnerId) -> bool:
        if (owner.pid, owner.pid_start_ns) in self._dead:
            return False
        return self._default


def owner(pid: int, start: int = 1) -> OwnerId:
    """An :class:`~opstore.types.OwnerId` with an explicit pid start stamp."""
    return OwnerId(pid=pid, pid_start_ns=start)
