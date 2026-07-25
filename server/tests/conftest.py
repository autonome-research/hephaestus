"""Pytest fixtures for the agent_bridge tests: a real opstore on a tmp root.

The clock/liveness doubles themselves live in
:mod:`hephaestus.testing.doubles` so ``tests/stage2`` can use the same ones;
this file only binds them to fixture names.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from hephaestus.agent_bridge.admission import bridge_store_config
from hephaestus.testing.doubles import FakeClock, FakeLiveness

from opstore import OpStore


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
