"""Tests for opstore.types and opstore.errors: clocks, liveness, crash hook, config."""

from __future__ import annotations

import os
import subprocess
import time

import pytest
from conftest import CrashRunner, FakeClock, FakeLiveness
from opstore.types import (
    CRASH_ENV_VAR,
    Clock,
    CrashHook,
    DefaultLiveness,
    EnvCrashHook,
    Liveness,
    NoopCrashHook,
    OwnerId,
    StoreConfig,
    SystemClock,
    current_owner,
)

from opstore import errors

DAY = 86_400


def test_system_clock_tracks_time() -> None:
    clock = SystemClock()
    before = time.time()
    now = clock.now()
    after = time.time()
    assert before <= now <= after


def test_protocol_conformance() -> None:
    assert isinstance(SystemClock(), Clock)
    assert isinstance(FakeClock(), Clock)
    assert isinstance(DefaultLiveness(), Liveness)
    assert isinstance(FakeLiveness(), Liveness)
    assert isinstance(NoopCrashHook(), CrashHook)
    assert isinstance(EnvCrashHook(), CrashHook)


def test_current_owner_and_self_liveness() -> None:
    owner = current_owner()
    assert owner.pid > 0
    assert DefaultLiveness().is_alive(owner)


def test_liveness_dead_pid() -> None:
    # An exited, reaped child pid must read as not alive.
    child = subprocess.Popen(["true"])
    child.wait()
    assert not DefaultLiveness().is_alive(OwnerId(pid=child.pid, pid_start_ns=0))


def test_liveness_rejects_recycled_pid_start_time() -> None:
    owner = current_owner()
    if owner.pid_start_ns == 0:
        pytest.skip("/proc start time unavailable on this platform")
    imposter = OwnerId(pid=owner.pid, pid_start_ns=owner.pid_start_ns + 1)
    assert not DefaultLiveness().is_alive(imposter)


def test_current_owner_start_zero_when_proc_stat_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    # A reaped child has no /proc/<pid>/stat; the OSError path must fall back to 0.
    child = subprocess.Popen(["true"])
    child.wait()
    monkeypatch.setattr(os, "getpid", lambda: child.pid)
    owner = current_owner()
    assert owner.pid == child.pid
    assert owner.pid_start_ns == 0


def test_current_owner_start_zero_when_sysconf_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken_sysconf(_name: str | int) -> int:
        raise OSError("sysconf unavailable")

    monkeypatch.setattr(os, "sysconf", broken_sysconf)
    assert current_owner().pid_start_ns == 0


def test_current_owner_start_zero_when_tick_nonpositive(monkeypatch: pytest.MonkeyPatch) -> None:
    def zero_tick(_name: str | int) -> int:
        return 0

    monkeypatch.setattr(os, "sysconf", zero_tick)
    assert current_owner().pid_start_ns == 0


def test_liveness_permission_error_means_alive(monkeypatch: pytest.MonkeyPatch) -> None:
    # EPERM: the process exists but belongs to another user.
    def deny(_pid: int, _sig: int) -> None:
        raise PermissionError("not ours")

    monkeypatch.setattr(os, "kill", deny)
    # pid_start_ns == 0 also exercises the cannot-distinguish-reuse branch.
    assert DefaultLiveness().is_alive(OwnerId(pid=os.getpid(), pid_start_ns=0))


def test_liveness_unexpected_oserror_means_dead(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(_pid: int, _sig: int) -> None:
        raise OSError("kernel says no")

    monkeypatch.setattr(os, "kill", broken)
    assert not DefaultLiveness().is_alive(OwnerId(pid=os.getpid(), pid_start_ns=0))


def test_noop_crash_hook_never_crashes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CRASH_ENV_VAR, "anything")
    NoopCrashHook().maybe_crash("anything")


def test_env_crash_hook_ignores_other_points(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CRASH_ENV_VAR, "point.a")
    EnvCrashHook().maybe_crash("point.b")  # must not exit
    monkeypatch.delenv(CRASH_ENV_VAR)
    EnvCrashHook().maybe_crash("point.a")  # must not exit


def test_env_crash_hook_exits_42_in_subprocess(run_crash_subprocess: CrashRunner) -> None:
    script = (
        'from opstore.types import EnvCrashHook; EnvCrashHook().maybe_crash("p.x"); print("ok")'
    )
    crashed = run_crash_subprocess(script, crash_point="p.x")
    assert crashed.returncode == 42
    assert "ok" not in crashed.stdout
    clean = run_crash_subprocess(script, crash_point=None)
    assert clean.returncode == 0
    assert "ok" in clean.stdout


def test_store_config_defaults() -> None:
    config = StoreConfig()
    assert config.idempotency_window_s == 30 * DAY
    assert config.tombstone_margin_s == 7 * DAY
    assert config.run_slots == 16
    assert config.quota_bytes == 10 * 1024**3
    assert config.retention_s == 30 * DAY
    assert config.preview_retention_s == 7 * DAY
    assert config.freshness_skew_s == 300
    assert config.key_retirement_retention_s == 37 * DAY
    with pytest.raises(AttributeError):
        config.run_slots = 8  # type: ignore[misc]  # frozen


def test_error_codes_stable() -> None:
    expected = {
        errors.KeyExpiredError: "key_expired",
        errors.KeyPayloadMismatchError: "key_payload_mismatch",
        errors.KeyTimestampSkewError: "key_timestamp_skew",
        errors.KeyringMissingError: "keyring_missing",
        errors.KeyringCorruptError: "keyring_corrupt",
        errors.BusyError: "busy",
        errors.ArtifactExpiredError: "artifact_expired",
        errors.ProtectedQuotaExceededError: "protected_quota_exceeded",
        errors.ConflictedError: "conflicted",
        errors.LeaseHeldError: "lease_held",
        errors.LeaseExpiredError: "lease_expired",
        errors.TerminalConflictError: "terminal_conflict",
        errors.NotFoundError: "not_found",
    }
    for exc_type, code in expected.items():
        exc = exc_type("msg")
        assert exc.code == code
        assert isinstance(exc, errors.OpStoreError)
        assert exc.message == "msg"
    assert issubclass(errors.KeyringMissingError, errors.KeyringError)
    assert issubclass(errors.KeyringCorruptError, errors.KeyringError)
