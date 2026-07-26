"""Supervisor lifecycle, env minimality, watchdog, crash recovery, orphan-free."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

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

#: The two knobs the fake sidecar reads for the respawn regression; they travel
#: through the credential allowlist because the sidecar env is minimal by design.
_FAKE_ENV_NAMES = frozenset({"FAKE_SIDECAR_REQUIRE_CONFIGURE", "FAKE_SIDECAR_CONFIGURE_LOG"})


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


# -- a respawned child is re-configured ------------------------------------
#
# The bug this covers: the sidecar's `runtime.configure` state lives in the
# *process*. A watchdog respawn produced a blank child that nothing
# re-configured, so every later session.create/session.prompt failed with
# `-32600 runtime.configure has not run yet` — silently, long after the restart.


_CONFIGURE_PAYLOAD: dict[str, Any] = {
    "providers": [{"id": "fake", "kind": "openai", "base_url": "http://127.0.0.1:9/v1"}],
    "credentials": {"FAKE_KEY": "secret-value"},
}


def _wedging_supervisor(log: Path) -> Supervisor:
    """A supervisor over a fake sidecar that *refuses* an unconfigured session.

    Timeouts are short so the watchdog fires quickly; the configure call itself
    is given a generous timeout so the watchdog never mistakes it for a wedge.
    """
    source = dict(os.environ)
    source["FAKE_SIDECAR_REQUIRE_CONFIGURE"] = "1"
    source["FAKE_SIDECAR_CONFIGURE_LOG"] = str(log)
    return Supervisor(
        SupervisorConfig(
            argv=_argv(),
            credential_allowlist=_FAKE_ENV_NAMES,
            env_source=source,
            default_timeout_s=0.3,
            watchdog_grace_s=0.2,
            watchdog_interval_s=0.05,
        ),
        spawn_hook=lambda sup: sup.call("runtime.configure", _CONFIGURE_PAYLOAD, timeout=5),
    )


def _configure_log(log: Path) -> list[str]:
    if not log.is_file():
        return []
    return [line for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]


def _wedge_until_respawned(sup: Supervisor, log: Path) -> None:
    """Wedge the sidecar mid-session and wait for the re-configured replacement."""
    with pytest.raises(SupervisorError):
        sup.call("sleep", {})  # never answered -> the watchdog kills the child
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and len(_configure_log(log)) < 2:
        time.sleep(0.02)


def test_respawned_sidecar_is_reconfigured_before_the_next_session(tmp_path: Path) -> None:
    log = tmp_path / "configure.jsonl"
    sup = _wedging_supervisor(log)
    sup.start()
    first_pid = sup.child_pid
    try:
        assert sup.call("session.create", {"profile": "orchestrator"}, timeout=5)["session_id"]
        _wedge_until_respawned(sup, log)
        assert sup.child_pid != first_pid, "the watchdog must have respawned the sidecar"
        # The whole regression in one line: without the replay this raises
        # SupervisorError carrying "runtime.configure has not run yet".
        result = sup.call("session.create", {"profile": "orchestrator"}, timeout=5)
        assert result["session_id"]
        assert sup.call("session.prompt", {"run_id": "run-after", "prompt": "hi"}, timeout=5)
        assert not sup.spawn_errors, sup.spawn_errors
        assert sup.spawn_count >= 2
    finally:
        sup.close()


def test_replayed_configure_payload_is_identical_to_the_initial_one(tmp_path: Path) -> None:
    log = tmp_path / "configure.jsonl"
    sup = _wedging_supervisor(log)
    sup.start()
    try:
        _wedge_until_respawned(sup, log)
        lines = _configure_log(log)
        assert len(lines) == 2, f"expected one configure per child, got {lines}"
        assert lines[0] == lines[1], "the respawn must replay the *same* payload"
        assert json.loads(lines[0]) == _CONFIGURE_PAYLOAD
    finally:
        sup.close()


def test_bridge_runtime_replays_its_own_configure_payload_on_every_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The app half: one payload, replayed by the supervisor's spawn hook.

    Runs the scripted sidecar *as* the sidecar (``HEPHAESTUS_NODE`` + a python
    ``dist_main``) so this exercises the real :class:`BridgeRuntime` wiring
    without Node or a provider.
    """
    from hephaestus.agent_bridge.app import BridgeRuntime
    from hephaestus.testing.projects import scaffold_project

    log = tmp_path / "configure.jsonl"
    monkeypatch.setenv("HEPHAESTUS_NODE", sys.executable)
    monkeypatch.setenv("FAKE_SIDECAR_REQUIRE_CONFIGURE", "1")
    monkeypatch.setenv("FAKE_SIDECAR_CONFIGURE_LOG", str(log))
    project = scaffold_project(tmp_path / "proj", name="respawn")
    runtime = BridgeRuntime(
        project_root=project,
        providers=[{"id": "fake", "kind": "openai", "base_url": "http://127.0.0.1:9/v1"}],
        credentials={"FAKE_KEY": "secret-value"},
        credential_allowlist=sorted(_FAKE_ENV_NAMES),
        dist_main=FAKE,
    )
    payload = runtime.configure_payload
    runtime.start()
    try:
        assert runtime.create_session("orchestrator")
        runtime.restart()
        # The fresh child refuses sessions unless it was re-configured.
        assert runtime.create_session("orchestrator")
        lines = _configure_log(log)
        assert len(lines) == 2, lines
        assert lines[0] == lines[1]
        assert json.loads(lines[0]) == payload
    finally:
        runtime.close()


def test_spawn_hook_failure_is_recorded_and_raises_to_the_caller() -> None:
    """An explicit start whose re-configuration fails must fail loudly."""

    def hook(_sup: Supervisor) -> None:
        raise RuntimeError("configure refused")

    sup = Supervisor(SupervisorConfig(argv=_argv()), spawn_hook=hook)
    try:
        with pytest.raises(RuntimeError):
            sup.start()
        assert sup.spawn_errors and "configure refused" in sup.spawn_errors[0]
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
