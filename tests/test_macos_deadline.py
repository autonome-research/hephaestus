# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Injected suspend progression only; NOT physical Mac suspend certification."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from hephaestus.core import deadline as clocks
from hephaestus.core.deadline import Deadline
from macos_milestone_smoke import Smoke
from macos_workspace import DeadlineGate, expire_session


@pytest.mark.parametrize("kind", ["http", "websocket"])
@pytest.mark.parametrize("expired", [False, True])
def test_admission_does_not_depend_on_expiry_task_order(monkeypatch, kind, expired):
    now = [0]
    monkeypatch.setattr(clocks, "continuous_ns", lambda: now[0])
    budget = Deadline.after(10)
    admitted, sent = [], []

    async def app(scope, receive, send):
        admitted.append(scope["type"])

    async def send(message):
        sent.append(message)

    if expired:
        now[0] += 10_000_000_000
    # No expiry task is running: the request boundary must independently refuse.
    asyncio.run(DeadlineGate(app, budget)({"type": kind}, None, send))
    assert bool(admitted) is not expired
    if expired:
        assert sent[0] == (
            {"type": "websocket.close", "code": 1001}
            if kind == "websocket"
            else {"type": "http.response.start", "status": 503, "headers": []}
        )


def test_expiry_task_requests_shutdown_at_resume(monkeypatch):
    from types import SimpleNamespace

    now = [0]
    monkeypatch.setattr(clocks, "continuous_ns", lambda: now[0])
    budget = Deadline.after(10)
    server = SimpleNamespace(should_exit=False)

    async def advance(seconds):
        assert seconds <= 0.1
        assert server.should_exit is False
        now[0] += 10_000_000_000

    monkeypatch.setattr(asyncio, "sleep", advance)
    asyncio.run(expire_session(server, budget))
    assert server.should_exit


def test_smoke_ceiling_not_loosened_and_cleanup_is_separate(tmp_path, monkeypatch):
    now = [0]
    monkeypatch.setattr(clocks, "continuous_ns", lambda: now[0])
    smoke = Smoke(tmp_path)
    marker = tmp_path / "launched"
    now[0] += 2400_000_000_000
    with pytest.raises(TimeoutError):
        smoke.command((sys.executable, "-c", f"open({str(marker)!r}, 'w').close()"))
    assert not marker.exists()
    assert smoke.report["commands"] == []
    smoke.cleanup()
    assert smoke.cleanup_deadline.remaining() == 120
    assert smoke.deadline.expired()
    now[0] += 120_000_000_000
    with pytest.raises(TimeoutError):
        smoke.command((sys.executable, "-c", "pass"))
    # Re-entering cleanup does not replenish its allowance.
    smoke.cleanup()
    assert smoke.cleanup_deadline.expired()


def test_browser_cleanup_never_signals_a_group_after_late_reap(tmp_path, monkeypatch):
    import macos_workspace_check as check

    smoke = SimpleNamespace(deadline=Deadline.after(30), report={}, save=lambda: None)
    signals = []
    waits = []

    def wait(process, deadline):
        waits.append(process)
        if len(waits) == 1:
            # Work expires while the owned child is still alive.
            raise subprocess.TimeoutExpired(process.args, 0)
        process.wait(timeout=5)  # TERM completed and wait REAPED the child.
        raise subprocess.TimeoutExpired(process.args, 0)  # resume/late-result check

    monkeypatch.setattr(check, "wait_process", wait)
    monkeypatch.setattr(check.os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    with pytest.raises((subprocess.TimeoutExpired, check.StageFailure)):
        check.run_browser_client(
            smoke, (sys.executable, "-c", "import time; time.sleep(30)"), tmp_path
        )
    assert signals == []  # the numeric PGID is no longer safe authority to signal
    assert len(waits) == 2
    assert waits[-1].returncode is not None


@pytest.mark.parametrize("expired", [False, True])
def test_owned_cleanup_still_kills_only_waitable_child(monkeypatch, expired):
    import macos_workspace_check as check

    process = SimpleNamespace(pid=123, returncode=None, terminate=lambda: None)
    signals, waits = [], []

    def wait(child, deadline):
        waits.append(child)
        if expired and len(waits) == 1:
            raise subprocess.TimeoutExpired("owned-double", 0)
        child.returncode = 0
        return 0

    monkeypatch.setattr(check, "wait_process", wait)
    monkeypatch.setattr(check.os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    assert check.terminate_owned_process(process) is not expired
    assert signals == ([(123, check.signal.SIGKILL)] if expired else [])
    assert process.returncode == 0


def test_browser_child_budget_cannot_restart_parent_allowance(tmp_path, monkeypatch):
    import macos_workspace_check as check

    now = [0]
    monkeypatch.setattr(clocks, "continuous_ns", lambda: now[0])
    smoke = SimpleNamespace(deadline=Deadline.after(10), report={}, save=lambda: None)
    original_after = Deadline.after

    def after(cls, seconds):
        now[0] = 11_000_000_000  # progression between relative cap and child creation
        return original_after(seconds)

    def forbidden(*args, **kwargs):
        pytest.fail("expired parent must not launch a browser child")

    monkeypatch.setattr(Deadline, "after", classmethod(after))
    monkeypatch.setattr(check.subprocess, "Popen", forbidden)
    with pytest.raises(TimeoutError, match="deadline expired"):
        check.run_browser_client(smoke, ("must-not-launch",), tmp_path)
