"""``EXTERNAL_EVAL.md`` §5: the supervisor keeps the sidecar's own evidence.

The 2026-07-29 sweep's restarts were diagnosable only by inference from
event-stream shape — the supervisor knew every restart and drained the child's
stderr into nothing. Now it writes both down where the bench archive can read
them after ``close()``: every child loss with its reason
(:attr:`Supervisor.restart_events`) and a **bounded** rolling stderr tail
(:attr:`Supervisor.stderr_tail` — a tail, not the firehose).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from hephaestus.agent_bridge.supervisor import (
    STDERR_TAIL_LINE_CHARS,
    STDERR_TAIL_LINES,
    Supervisor,
    SupervisorConfig,
    SupervisorError,
)

FAKE = Path(__file__).with_name("fake_sidecar.py")


def _argv() -> list[str]:
    import sys

    return [sys.executable, str(FAKE)]


@pytest.fixture
def supervisor() -> Iterator[Supervisor]:
    sup = Supervisor(SupervisorConfig(argv=_argv(), respawn_backoff_s=0.05))
    sup.start()
    try:
        yield sup
    finally:
        sup.close()


def _wait_for(predicate: Callable[[], object], *, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition not reached in time")


def test_an_explicit_restart_is_recorded_with_its_reason(supervisor: Supervisor) -> None:
    assert supervisor.restart_events == []

    supervisor.restart(reason="watchdog")

    (event,) = supervisor.restart_events
    assert event["reason"] == "watchdog"
    assert event["restart_generation"] == 1
    assert isinstance(event["at"], str) and event["at"]


def test_a_crash_is_recorded_with_its_returncode(supervisor: Supervisor) -> None:
    with pytest.raises(SupervisorError):
        supervisor.call("crash", {})
    _wait_for(lambda: bool(supervisor.restart_events))

    event = supervisor.restart_events[0]
    assert event["reason"] == "crash"
    assert event["returncode"] is not None
    # …and the record survives close(): that is when the bench archive reads it.
    supervisor.close()
    assert supervisor.restart_events[0]["reason"] == "crash"


def test_the_stderr_tail_is_retained_and_bounded(supervisor: Supervisor) -> None:
    # The fake sidecar announces itself on stderr at startup.
    _wait_for(lambda: any("fake-sidecar" in line for line in supervisor.stderr_tail))

    assert supervisor.stderr_tail.maxlen == STDERR_TAIL_LINES
    assert all(len(line) <= STDERR_TAIL_LINE_CHARS for line in supervisor.stderr_tail)
