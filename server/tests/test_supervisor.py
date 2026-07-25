"""Supervisor lifecycle, env minimality, watchdog, crash recovery, orphan-free."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from hephaestus.agent_bridge.supervisor import (
    BASE_ENV_VARS,
    ProcessLossEvent,
    Supervisor,
    SupervisorConfig,
    SupervisorError,
    build_minimal_env,
    pid_alive,
)

FAKE = Path(__file__).with_name("fake_sidecar.py")
ORPHAN_PARENT = Path(__file__).with_name("orphan_parent.py")


def _argv() -> list[str]:
    return [sys.executable, str(FAKE)]


@pytest.fixture
def supervisor() -> Iterator[Supervisor]:
    sup = Supervisor(SupervisorConfig(argv=_argv()))
    sup.start()
    try:
        yield sup
    finally:
        sup.close()


# -- env minimality --------------------------------------------------------


def test_build_minimal_env_drops_ambient_credentials() -> None:
    source = {
        "PATH": "/usr/bin",
        "HOME": "/home/x",
        "LANG": "C",
        "ANTHROPIC_API_KEY": "secret",
        "OPENAI_API_KEY": "secret2",
        "MY_APPROVED_KEY": "ok",
    }
    env = build_minimal_env(frozenset({"MY_APPROVED_KEY"}), source=source)
    assert env["PATH"] == "/usr/bin"
    assert env["MY_APPROVED_KEY"] == "ok"
    assert "ANTHROPIC_API_KEY" not in env
    assert "OPENAI_API_KEY" not in env


def test_base_env_vars_are_the_only_non_credential_names() -> None:
    assert set(BASE_ENV_VARS) == {"PATH", "HOME", "LANG", "TMPDIR"}


def test_sidecar_sees_only_minimal_env() -> None:
    source = dict(os.environ)
    source["ANTHROPIC_API_KEY"] = "should-not-propagate"
    source["MY_CRED"] = "approved"
    sup = Supervisor(
        SupervisorConfig(
            argv=_argv(),
            credential_allowlist=frozenset({"MY_CRED"}),
            env_source=source,
        )
    )
    sup.start()
    try:
        result = sup.call(
            "env_probe", {"names": ["PATH", "ANTHROPIC_API_KEY", "MY_CRED"]}, timeout=5
        )
        env = result["env"]
        assert env["PATH"]  # base var forwarded
        assert env["ANTHROPIC_API_KEY"] is None  # ambient key dropped
        assert env["MY_CRED"] == "approved"  # allowlisted key forwarded
    finally:
        sup.close()


# -- request/response ------------------------------------------------------


def test_echo_round_trip(supervisor: Supervisor) -> None:
    assert supervisor.call("echo", {"x": 1, "y": "z"}) == {"x": 1, "y": "z"}


def test_method_not_found_is_structured_error(supervisor: Supervisor) -> None:
    with pytest.raises(SupervisorError):
        supervisor.call("no_such_method", {})


def test_session_prompt_streams_events_to_sink() -> None:
    seen: list[tuple[str, dict[str, object]]] = []
    sup = Supervisor(
        SupervisorConfig(argv=_argv()),
        notification_sink=lambda m, p: seen.append((m, p)),
    )
    sup.start()
    try:
        sup.call("session.prompt", {"run_id": "run-A", "prompt": "hi"})
        # give the notifications a moment to arrive
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and len(seen) < 2:
            time.sleep(0.02)
        methods = [m for m, _ in seen]
        assert "event" in methods
        assert "terminal" in methods
    finally:
        sup.close()


# -- py.* handler round trip ----------------------------------------------


def test_py_request_from_sidecar_is_handled() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def handler(method: str, params: dict[str, object]) -> dict[str, object]:
        calls.append((method, params))
        return {"ok": True, "tool": params.get("tool")}

    sup = Supervisor(SupervisorConfig(argv=_argv()), py_handler=handler)
    sup.start()
    try:
        result = sup.call("ask_py", {"tool": "read_part", "arguments": {"name": "widget"}})
        assert result["py"]["result"] == {"ok": True, "tool": "read_part"}
        assert calls and calls[0][0] == "py.tool_dispatch"
    finally:
        sup.close()


def test_py_handler_exception_becomes_error_frame() -> None:
    def handler(method: str, params: dict[str, object]) -> dict[str, object]:
        raise RuntimeError("boom")

    sup = Supervisor(SupervisorConfig(argv=_argv()), py_handler=handler)
    sup.start()
    try:
        result = sup.call("ask_py", {"tool": "read_part"})
        assert "error" in result["py"]
        assert result["py"]["error"]["code"] == -32603  # INTERNAL_ERROR
    finally:
        sup.close()


# -- crash mid-call -> structured error + recovery hook + restart ----------


def test_crash_midcall_fails_call_and_fires_recovery() -> None:
    events: list[ProcessLossEvent] = []
    sup = Supervisor(
        SupervisorConfig(argv=_argv()),
        recovery_hook=events.append,
    )
    sup.start()
    sup.track_run("run-live")
    try:
        with pytest.raises(SupervisorError):
            sup.call("crash", {})
        assert events, "recovery hook must fire before terminal synthesis"
        assert events[0].reason == "crash"
        assert "run-live" in events[0].tracked_run_ids
        assert not sup.is_running()
        # manual restart brings a fresh sidecar back
        sup.restart(reason="manual")
        assert sup.is_running()
        assert sup.call("echo", {"n": 1}) == {"n": 1}
    finally:
        sup.close()


# -- watchdog: unresponsive process -> kill + restart ----------------------


def test_watchdog_kills_unresponsive_sidecar() -> None:
    events: list[ProcessLossEvent] = []
    sup = Supervisor(
        SupervisorConfig(
            argv=_argv(),
            default_timeout_s=0.2,
            watchdog_grace_s=0.2,
            watchdog_interval_s=0.05,
        ),
        recovery_hook=events.append,
    )
    sup.start()
    first_pid = sup.child_pid
    try:
        with pytest.raises(SupervisorError):
            sup.call("sleep", {})  # never answered -> watchdog fires
        assert any(e.reason == "watchdog" for e in events)
        # a fresh sidecar was started
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not sup.is_running():
            time.sleep(0.02)
        assert sup.is_running()
        assert sup.child_pid != first_pid
    finally:
        sup.close()


# -- oversized inbound frame fails closed ----------------------------------


def test_oversized_inbound_frame_fails_closed() -> None:
    sup = Supervisor(SupervisorConfig(argv=_argv()))
    sup.start()
    try:
        with pytest.raises(SupervisorError):
            sup.call("big", {"bytes": 70 * 1024 * 1024}, timeout=10)
        assert sup.frame_errors, "an oversized inbound frame is recorded and fails closed"
    finally:
        sup.close()


# -- orphan-free: no sidecar survives the supervisor -----------------------


def test_no_orphan_when_supervisor_is_killed() -> None:
    if sys.platform != "linux":
        pytest.skip("die-with-parent relies on PR_SET_PDEATHSIG (Linux)")
    proc = subprocess.Popen(
        [sys.executable, str(ORPHAN_PARENT)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    assert proc.stdout is not None
    child_pid_line = proc.stdout.readline().decode().strip()
    child_pid = int(child_pid_line)
    assert pid_alive(child_pid)
    # SIGKILL the supervisor process; the sidecar must die with it.
    os.kill(proc.pid, signal.SIGKILL)
    proc.wait(timeout=5)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and pid_alive(child_pid):
        time.sleep(0.05)
    assert not pid_alive(child_pid), "sidecar orphaned after supervisor death"
