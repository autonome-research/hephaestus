"""Shared fixtures for opstore tests: tmp store root, fake clock/liveness, crash helper."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from _optest import REPO_ROOT, CrashRunner, FakeClock, FakeLiveness
from opstore.db import Database
from opstore.types import CRASH_ENV_VAR


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
