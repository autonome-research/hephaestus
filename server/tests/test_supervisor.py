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

#: The knobs the fake sidecar reads for the respawn regressions; they travel
#: through the credential allowlist because the sidecar env is minimal by design.
_FAKE_ENV_NAMES = frozenset(
    {
        "FAKE_SIDECAR_REQUIRE_CONFIGURE",
        "FAKE_SIDECAR_CONFIGURE_LOG",
        "FAKE_SIDECAR_DIE_AFTER_S",
        "FAKE_SIDECAR_SPAWN_LOG",
        "FAKE_SIDECAR_CONFIGURE_FAILS",
    }
)


#: The payload the spawn hook replays onto every child (see the respawn tests).
_CONFIGURE_PAYLOAD: dict[str, Any] = {
    "providers": [{"id": "fake", "kind": "openai", "base_url": "http://127.0.0.1:9/v1"}],
    "credentials": {"FAKE_KEY": "secret-value"},
}


def _argv() -> list[str]:
    return [sys.executable, str(FAKE)]


def _configure_log(log: Path) -> list[str]:
    if not log.is_file():
        return []
    return [line for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]


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


# -- crash mid-call -> structured error + recovery hook + bounded respawn ---
#
# The bug this covers (bench `gpt-5.6-sol/knob-loft-s2`, `review_error:
# SupervisorError: sidecar is not running`): a crash used to leave the
# supervisor permanently childless, because only the watchdog respawned and the
# watchdog only fires while a call is pending. The contract now is: the in-flight
# call still fails, recovery still runs *before* anything is respawned, and the
# NEXT call finds a fresh, re-configured child.


def _crashy_supervisor(
    log: Path,
    *,
    recovery_hook: Any = None,
    spawn_log: Path | None = None,
    die_after_s: float | None = None,
    **config: Any,
) -> Supervisor:
    """A supervisor whose fake sidecar refuses sessions until re-configured."""
    source = dict(os.environ)
    source["FAKE_SIDECAR_REQUIRE_CONFIGURE"] = "1"
    source["FAKE_SIDECAR_CONFIGURE_LOG"] = str(log)
    if spawn_log is not None:
        source["FAKE_SIDECAR_SPAWN_LOG"] = str(spawn_log)
    if die_after_s is not None:
        source["FAKE_SIDECAR_DIE_AFTER_S"] = str(die_after_s)
    return Supervisor(
        SupervisorConfig(
            argv=_argv(),
            credential_allowlist=_FAKE_ENV_NAMES,
            env_source=source,
            **config,
        ),
        recovery_hook=recovery_hook,
        spawn_hook=lambda sup: sup.call("runtime.configure", _CONFIGURE_PAYLOAD, timeout=5),
    )


def test_crash_midcall_fails_call_and_fires_recovery(tmp_path: Path) -> None:
    log = tmp_path / "configure.jsonl"
    events: list[ProcessLossEvent] = []
    #: (spawn_count, is_running) sampled *inside* the hook: proof of ordering.
    at_recovery: list[tuple[int, bool]] = []
    sup: Supervisor

    def on_loss(event: ProcessLossEvent) -> None:
        at_recovery.append((sup.spawn_count, sup.is_running()))
        events.append(event)

    sup = _crashy_supervisor(log, recovery_hook=on_loss, respawn_backoff_s=0.05)
    sup.start()
    sup.track_run("run-live")
    first_pid = sup.child_pid
    try:
        with pytest.raises(SupervisorError):
            sup.call("crash", {})
        assert events, "recovery hook must fire before terminal synthesis"
        assert events[0].reason == "crash"
        assert "run-live" in events[0].tracked_run_ids
        # Recovery ran before any respawn: still one spawn, still no child.
        assert at_recovery == [(1, False)]
        # The next call transparently lands on a fresh, re-configured child.
        assert sup.call("session.create", {"profile": "orchestrator"}, timeout=5)["session_id"]
        assert sup.child_pid != first_pid
        assert sup.auto_respawns == 1
        assert sup.spawn_count == 2
        assert not sup.spawn_errors, sup.spawn_errors
        assert sup.respawn_failure is None
        lines = _configure_log(log)
        assert len(lines) == 2, lines
        assert lines[0] == lines[1], "the respawn must replay the *same* payload"
    finally:
        sup.close()


def test_crash_loop_is_bounded_and_ends_durably_dead(tmp_path: Path) -> None:
    """A sidecar that cannot stay up fails loudly instead of thrashing."""
    log = tmp_path / "configure.jsonl"
    spawns = tmp_path / "spawns.log"
    events: list[ProcessLossEvent] = []
    sup = _crashy_supervisor(
        log,
        recovery_hook=events.append,
        spawn_log=spawns,
        # Comfortably longer than a spawn + `runtime.configure` round trip
        # (measured 20-60 ms on this fake sidecar), so each child is fully up
        # before it dies: the test measures the respawn bound, not a race
        # between the suicide timer and the spawn hook.
        die_after_s=0.5,
        respawn_max_attempts=3,
        respawn_backoff_s=0.05,
        respawn_cooldown_s=30.0,
    )
    sup.start()
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and sup.respawn_failure is None:
            time.sleep(0.02)
        failure = sup.respawn_failure
        assert failure is not None, "the crash loop must terminate in a durable failure"
        assert "3 attempts" in failure
        assert not sup.is_running()
        # Bounded: the initial spawn plus exactly `respawn_max_attempts` retries.
        assert sup.spawn_count == 4, sup.spawn_count
        assert len(_configure_log(spawns)) == 4
        assert len(events) == 4, [e.reason for e in events]
        # Every later call fails with the same clear, attempt-naming error.
        with pytest.raises(SupervisorError) as excinfo:
            sup.call("echo", {"n": 1}, timeout=1)
        assert "3 attempts" in str(excinfo.value)
        # No thrash: the state stays dead, nothing spawns behind our back.
        time.sleep(0.5)
        assert sup.spawn_count == 4
    finally:
        sup.close()


def test_respawn_gives_up_when_the_spawn_hook_keeps_failing(tmp_path: Path) -> None:
    """A child that starts but cannot be configured is no better than a dead one.

    The replacement is only useful once ``runtime.configure`` has been replayed
    onto it, so a spawn hook that raises must consume an attempt, take the
    half-built child down with it (never leaving an unconfigured sidecar behind),
    and end in the same durable death naming the attempt count.
    """
    log = tmp_path / "configure.jsonl"
    spawns = tmp_path / "spawns.log"
    sup = _crashy_supervisor(log, spawn_log=spawns, respawn_backoff_s=0.05, respawn_max_attempts=3)
    source = sup.config.env_source
    assert source is not None
    sup.start()
    try:
        # Read at every spawn, so only the *replacements* refuse to configure.
        source["FAKE_SIDECAR_CONFIGURE_FAILS"] = "1"
        with pytest.raises(SupervisorError):
            sup.call("crash", {})
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and sup.respawn_failure is None:
            time.sleep(0.02)
        failure = sup.respawn_failure
        assert failure is not None, "a permanently unconfigurable child must fail loudly"
        assert "3 attempts" in failure
        assert "configure refused" in failure, failure
        assert len(sup.spawn_errors) == 3, sup.spawn_errors
        assert sup.auto_respawns == 0, "a child the hook could not configure is not a success"
        assert sup.spawn_count == 4, sup.spawn_count
        assert len(_configure_log(spawns)) == 4
        # No half-built child survives: each failed attempt was discarded.
        assert not sup.is_running()
        assert not pid_alive(sup.child_pid)
    finally:
        sup.close()


def test_close_never_respawns(tmp_path: Path) -> None:
    """A deliberate shutdown is not a crash, whatever the child's exit code."""
    log = tmp_path / "configure.jsonl"
    spawns = tmp_path / "spawns.log"
    events: list[ProcessLossEvent] = []
    sup = _crashy_supervisor(
        log, recovery_hook=events.append, spawn_log=spawns, respawn_backoff_s=0.05
    )
    sup.start()
    sup.close()
    time.sleep(0.5)
    assert sup.spawn_count == 1
    assert sup.auto_respawns == 0
    assert len(_configure_log(spawns)) == 1
    assert not events, "close() is not a process-loss event"
    assert not sup.is_running()


def test_explicit_restart_clears_a_durable_respawn_failure(tmp_path: Path) -> None:
    """Operator intent beats the exhausted budget; the child comes back healthy."""
    log = tmp_path / "configure.jsonl"
    env = dict(os.environ)
    env["FAKE_SIDECAR_REQUIRE_CONFIGURE"] = "1"
    env["FAKE_SIDECAR_CONFIGURE_LOG"] = str(log)
    env["FAKE_SIDECAR_DIE_AFTER_S"] = "0.5"
    sup = Supervisor(
        SupervisorConfig(
            argv=_argv(),
            credential_allowlist=_FAKE_ENV_NAMES,
            env_source=env,
            respawn_max_attempts=2,
            respawn_backoff_s=0.05,
        ),
        spawn_hook=lambda s: s.call("runtime.configure", _CONFIGURE_PAYLOAD, timeout=5),
    )
    sup.start()
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and sup.respawn_failure is None:
            time.sleep(0.02)
        assert sup.respawn_failure is not None
        # A sidecar that can stay up plus an explicit restart resurrects it.
        env.pop("FAKE_SIDECAR_DIE_AFTER_S")
        sup.restart(reason="manual")
        assert sup.respawn_failure is None
        assert sup.call("session.create", {"profile": "orchestrator"}, timeout=5)["session_id"]
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
