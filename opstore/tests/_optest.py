"""Shared opstore test helpers: fake clock/liveness, crash-runner protocol.

Lives under a unique basename (not ``conftest``): test modules import these
by name, and a ``conftest`` module import collides across suites when pytest
runs several test roots in one invocation (prepend import mode keys modules
by basename, so whichever suite's ``conftest.py`` loads first wins).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Protocol

from opstore.types import OwnerId

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
