"""Shared fixtures for opstore tests: tmp store root, fake clock/liveness, crash helper."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Protocol

import pytest
from opstore.db import Database
from opstore.types import CRASH_ENV_VAR, OwnerId

REPO_ROOT = Path(__file__).resolve().parents[2]


class FakeClock:
    """Deterministic injectable clock."""

    def __init__(self, start: float = 1_700_000_000.0) -> None:
        self._now = start

    def now(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds

    def set(self, at: float) -> None:
        self._now = at


class FakeLiveness:
    """Injectable liveness oracle backed by an explicit alive-set."""

    def __init__(self) -> None:
        self.alive: set[OwnerId] = set()

    def is_alive(self, owner: OwnerId) -> bool:
        return owner in self.alive


class CrashRunner(Protocol):
    """Runs a python snippet in a subprocess with OPSTORE_CRASH_POINT set."""

    def __call__(
        self, script: str, crash_point: str | None = None
    ) -> subprocess.CompletedProcess[str]: ...


@pytest.fixture
def store_root(tmp_path: Path) -> Path:
    root = tmp_path / "store"
    root.mkdir()
    return root


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def fake_liveness() -> FakeLiveness:
    return FakeLiveness()


@pytest.fixture
def db(store_root: Path) -> Iterator[Database]:
    database = Database.connect(store_root / "state.db")
    yield database
    database.close()


@pytest.fixture
def run_crash_subprocess() -> CrashRunner:
    """Spawn ``uv run python -c <script>`` with the named crash point armed.

    Returns the completed process; crash tests assert ``returncode == 42``
    then re-run recovery in-process against the same store root.
    """

    def run(script: str, crash_point: str | None = None) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        env.pop(CRASH_ENV_VAR, None)
        if crash_point is not None:
            env[CRASH_ENV_VAR] = crash_point
        return subprocess.run(
            ["uv", "run", "python", "-c", script],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )

    return run
