# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Clock arithmetic and owned-process controls, NOT physical suspend certification."""

from __future__ import annotations

import os
import selectors
import subprocess
import sys
import time
from pathlib import Path

import pytest
from hephaestus.core import deadline as clocks
from hephaestus.core.deadline import ClockUnavailable, Deadline
from hephaestus.core.executor.sandbox import oci
from hephaestus.core.executor.sandbox.oci_ownership import OwnershipJournal


def test_suspend_progression_not_utc_or_awake_uptime(monkeypatch: pytest.MonkeyPatch) -> None:
    continuous = [10_000_000_000]
    monkeypatch.setattr(clocks, "continuous_ns", lambda: continuous[0])
    monkeypatch.setattr(time, "monotonic", lambda: 123.0)
    monkeypatch.setattr(time, "perf_counter", lambda: 123.0)
    budget = Deadline.after(20)
    assert budget.end_ns == 30_000_000_000
    # Both directions of adjustable UTC are irrelevant; ordinary uptime is
    # deliberately held constant. Only injected suspend-inclusive time moves.
    for utc in (-(10**12), 10**12):
        monkeypatch.setattr(time, "time", lambda utc=utc: utc)
        assert budget.remaining() == 20
    continuous[0] += 19_999_999_999
    assert not budget.expired()
    continuous[0] += 1
    assert budget.expired()
    assert time.monotonic() == time.perf_counter() == 123.0
    with pytest.raises(TimeoutError):
        budget.remaining()
    cleanup = Deadline.after(5)
    assert cleanup.remaining() == 5  # fresh separate allowance, not revived work
    continuous[0] += 5_000_000_000
    with pytest.raises(TimeoutError):
        cleanup.remaining()


@pytest.mark.parametrize("seconds", [-1, float("nan"), float("inf")])
def test_invalid_duration_refuses(seconds: float) -> None:
    with pytest.raises(ValueError):
        Deadline.after(seconds)


def test_no_clock_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    clocks.clock_source.cache_clear()
    try:
        with monkeypatch.context() as patch:
            patch.setattr(sys, "platform", "unsupported")
            with pytest.raises(ClockUnavailable):
                Deadline.after(10)
    finally:
        clocks.clock_source.cache_clear()


def test_linux_boot_time_selection_and_failed_read(monkeypatch: pytest.MonkeyPatch) -> None:
    clocks.clock_source.cache_clear()
    seen: list[int] = []
    try:
        with monkeypatch.context() as patch:
            patch.setattr(sys, "platform", "linux")
            patch.setattr(time, "CLOCK_BOOTTIME", 7, raising=False)

            def read(clock: int) -> int:
                seen.append(clock)
                return 123_456_789

            patch.setattr(time, "clock_gettime_ns", read)
            assert clocks.continuous_ns() == 123_456_789
            assert seen == [7]

            def refused(clock: int) -> int:
                raise OSError("injected unavailable kernel clock")

            patch.setattr(time, "clock_gettime_ns", refused)
            with pytest.raises(ClockUnavailable, match="read failed"):
                clocks.continuous_ns()
    finally:
        clocks.clock_source.cache_clear()


def test_darwin_missing_facility_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    import ctypes

    def missing(path: str) -> None:
        raise OSError("injected missing mach facility")

    clocks.clock_source.cache_clear()
    try:
        with monkeypatch.context() as patch:
            patch.setattr(sys, "platform", "darwin")
            patch.setattr(ctypes, "CDLL", missing)
            with pytest.raises(ClockUnavailable, match="mach_continuous_time unavailable"):
                Deadline.after(10)
    finally:
        clocks.clock_source.cache_clear()


def test_absolute_budget_survives_a_pre_launch_wrapper_gap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [0]
    monkeypatch.setattr(clocks, "continuous_ns", lambda: now[0])
    budget = Deadline.after(20)
    marker = tmp_path / "not-launched"
    with clocks.transport_budget(budget):
        # Simulate sleep in an evidence/fsync wrapper AFTER the relative timeout
        # was selected but BEFORE the transport itself was entered.
        now[0] += 21_000_000_000
        with pytest.raises(oci.TransportTimeout):
            oci.SubprocessTransport().run(
                (sys.executable, "-c", f"open({str(marker)!r}, 'w').close()"),
                input=b"",
                timeout=20,
                stdout_limit=1024,
                stderr_limit=1024,
                env={},
            )
    assert not marker.exists()
    assert clocks.transport_deadline.get() is None


def test_real_platform_clock_is_acquired() -> None:
    description = clocks.clock_description()
    assert (
        "mach_continuous_time" in description
        if sys.platform == "darwin"
        else "BOOTTIME" in description
    )
    first = clocks.continuous_ns()
    second = clocks.continuous_ns()
    assert 0 < first <= second


@pytest.mark.parametrize("advance", [False, True])
def test_owned_process_ready_on_resume_cannot_beat_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, advance: bool
) -> None:
    """Real owned/reaped process + injected clock jump, NOT physical Mac sleep.

    Negative control runs the identical ready-result path without progression.
    The jump happens inside select, before it returns a ready stdout event.
    """
    real_clock = clocks.continuous_ns
    offset = [0]
    monkeypatch.setattr(clocks, "continuous_ns", lambda: real_clock() + offset[0])
    selector = selectors.DefaultSelector()
    real_select = selector.select
    progressed: list[bool] = []

    def select(timeout: float | None = None):
        events = real_select(timeout)
        if not progressed and any(key.data == "stdout" for key, _ in events):
            progressed.append(True)
            if advance:
                offset[0] += 21_000_000_000
        return events

    monkeypatch.setattr(selector, "select", select)
    monkeypatch.setattr(selectors, "DefaultSelector", lambda: selector)
    received: list[bytes] = []
    with OwnershipJournal(tmp_path / "ownership", {}) as journal:
        transport = oci.SubprocessTransport(ownership=journal)

        def run() -> oci.TransportResult:
            return transport.run(
                (sys.executable, "-c", "print('ready', flush=True)"),
                input=b"",
                timeout=20,
                stdout_limit=1024,
                stderr_limit=1024,
                env={"PATH": "/usr/bin:/bin"},
                stdout_consumer=received.append,
            )

        if advance:
            with pytest.raises(oci.TransportTimeout):
                run()
            assert received == []
        else:
            assert run().returncode == 0
            assert b"".join(received) == b"ready\n"
        assert progressed
        journal.require_clean()
        assert journal.state["clients"]
        for pid, record in journal.state["clients"].items():
            assert record["reaped"] is True
            with pytest.raises(ProcessLookupError):
                os.kill(int(pid), 0)


def test_zero_budget_never_launches(tmp_path: Path) -> None:
    marker = tmp_path / "must-not-exist"
    with pytest.raises(oci.TransportTimeout):
        oci.SubprocessTransport().run(
            (sys.executable, "-c", f"open({str(marker)!r}, 'w').close()"),
            input=b"",
            timeout=0,
            stdout_limit=1024,
            stderr_limit=1024,
            env={},
        )
    assert not marker.exists()


@pytest.mark.parametrize("late", [False, True])
def test_owner_reap_expiry_cannot_acknowledge_success(
    monkeypatch: pytest.MonkeyPatch, late: bool
) -> None:
    from hephaestus.core.executor.bounded_pass import OwnerRefusal, run_independent_owner

    real_clock = clocks.continuous_ns
    offset = [0]
    monkeypatch.setattr(clocks, "continuous_ns", lambda: real_clock() + offset[0])
    original_wait = subprocess.Popen[bytes].wait

    def wait(process: subprocess.Popen[bytes], timeout: float | None = None) -> int:
        code = original_wait(process, timeout=timeout)
        if late:
            offset[0] += 11_000_000_000
        return code

    monkeypatch.setattr(subprocess.Popen, "wait", wait)
    started: list[int] = []
    reaped: list[int] = []
    refused: list[bool] = []
    script = (
        "from multiprocessing.connection import Connection; import sys; "
        "c=Connection(int(sys.argv[1])); c.send_bytes(b'ok'); c.close()"
    )

    def run() -> bytes:
        return run_independent_owner(
            lambda fd: [sys.executable, "-c", script, str(fd)],
            env={"PATH": "/usr/bin:/bin"},
            timeout_s=20,
            maximum=1024,
            on_started=lambda pid, connection: started.append(pid),
            on_reaped=lambda pid, code: reaped.append(pid),
            on_unreaped=lambda: refused.append(True),
            on_cancel=lambda: None,
        )

    if late:
        with pytest.raises(OwnerRefusal, match="cleanup deadline"):
            run()
        assert not reaped and refused == [True]
    else:
        assert run() == b"ok"
        assert reaped == started and not refused
    assert len(started) == 1
    with pytest.raises(ProcessLookupError):
        os.kill(started[0], 0)


def test_wait_rechecks_after_ready_on_resume(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [0]
    monkeypatch.setattr(clocks, "continuous_ns", lambda: now[0])
    budget = Deadline.after(1)
    with subprocess.Popen([sys.executable, "-c", "pass"]) as process:
        original = process.wait

        def wait(timeout: float | None = None) -> int:
            code = original(timeout=timeout)
            now[0] = 1_000_000_000
            return code

        monkeypatch.setattr(process, "wait", wait)
        with pytest.raises(subprocess.TimeoutExpired):
            clocks.wait_process(process, budget)
        assert process.returncode == 0
