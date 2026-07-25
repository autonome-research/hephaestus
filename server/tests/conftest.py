"""Shared fixtures/helpers for agent_bridge tests: real opstore on tmp roots."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from hephaestus.agent_bridge.admission import bridge_store_config
from opstore.types import OwnerId

from opstore import OpStore


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
    return OwnerId(pid=pid, pid_start_ns=start)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def liveness() -> FakeLiveness:
    return FakeLiveness()


@pytest.fixture
def store(tmp_path: Path, clock: FakeClock, liveness: FakeLiveness) -> Iterator[OpStore]:
    """A fresh opstore rooted in tmp with the 16-slot bridge config + fake clock."""
    st = OpStore.create(
        tmp_path / "heph",
        bridge_store_config(),
        clock=clock,
        liveness=liveness,
    )
    try:
        yield st
    finally:
        st.close()
