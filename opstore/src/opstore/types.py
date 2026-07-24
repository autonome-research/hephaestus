"""Core injectable protocols, dataclasses, and enums for opstore.

Contract (DESIGN.md "Core conventions"):

- ``Clock.now() -> float`` unix seconds; production default ``SystemClock``.
- ``Liveness.is_alive(owner) -> bool`` with ``OwnerId = (pid, pid_start_ns)``;
  ``DefaultLiveness`` combines ``os.kill(pid, 0)`` with the ``/proc/<pid>/stat``
  start time when available so a recycled pid is not mistaken for the owner.
- ``CrashHook.maybe_crash(point)`` is called at every documented crash point;
  production default is a no-op, ``EnvCrashHook`` reads ``OPSTORE_CRASH_POINT``
  and calls ``os._exit(42)`` when the named point is reached.
- ``StoreConfig`` carries every tunable horizon/limit with the fixed defaults.
"""

from __future__ import annotations

import enum
import os
import time
from dataclasses import dataclass
from typing import NamedTuple, Protocol, runtime_checkable

JSONValue = None | bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"]

CRASH_ENV_VAR = "OPSTORE_CRASH_POINT"
CRASH_EXIT_CODE = 42


class OwnerId(NamedTuple):
    """Cross-process owner identity: pid plus process start time in nanoseconds.

    ``pid_start_ns == 0`` means the start time could not be determined (no
    ``/proc``); liveness then degrades to pid-existence only.
    """

    pid: int
    pid_start_ns: int


@runtime_checkable
class Clock(Protocol):
    """Injectable time source (unix seconds)."""

    def now(self) -> float: ...


class SystemClock:
    """Production clock backed by ``time.time()``."""

    def now(self) -> float:
        return time.time()


@runtime_checkable
class Liveness(Protocol):
    """Injectable owner-liveness oracle."""

    def is_alive(self, owner: OwnerId) -> bool: ...


def _proc_start_ns(pid: int) -> int | None:
    """Start time of ``pid`` in ns since boot from ``/proc/<pid>/stat``, or None."""
    try:
        with open(f"/proc/{pid}/stat", "rb") as fh:
            raw = fh.read()
    except OSError:
        return None
    # comm (field 2) may contain spaces/parens; fields resume after the last ')'.
    try:
        rest = raw.rsplit(b")", 1)[1].split()
        starttime_ticks = int(rest[19])  # stat field 22 (1-indexed)
        tick_hz = os.sysconf("SC_CLK_TCK")
    except (IndexError, ValueError, OSError):
        return None
    if tick_hz <= 0:
        return None
    return (starttime_ticks * 1_000_000_000) // tick_hz


def current_owner() -> OwnerId:
    """OwnerId for the calling process (start time 0 when /proc is unavailable)."""
    pid = os.getpid()
    return OwnerId(pid=pid, pid_start_ns=_proc_start_ns(pid) or 0)


class DefaultLiveness:
    """Production liveness: signal-0 pid probe plus /proc start-time comparison."""

    def is_alive(self, owner: OwnerId) -> bool:
        try:
            os.kill(owner.pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            pass  # process exists but is not ours
        except OSError:
            return False
        start_ns = _proc_start_ns(owner.pid)
        if start_ns is None or owner.pid_start_ns == 0:
            return True  # cannot distinguish reuse; pid exists
        return start_ns == owner.pid_start_ns


@runtime_checkable
class CrashHook(Protocol):
    """Injectable crash-injection point; called with a documented point name."""

    def maybe_crash(self, point: str) -> None: ...


class NoopCrashHook:
    """Production crash hook: never crashes."""

    def maybe_crash(self, point: str) -> None:
        return None


class EnvCrashHook:
    """Test crash hook: ``os._exit(42)`` when ``OPSTORE_CRASH_POINT`` names the point."""

    def maybe_crash(self, point: str) -> None:
        if os.environ.get(CRASH_ENV_VAR) == point:
            os._exit(CRASH_EXIT_CODE)


_DAY_S = 86_400.0


@dataclass(frozen=True, slots=True)
class StoreConfig:
    """Tunable horizons and limits (DESIGN.md defaults)."""

    idempotency_window_s: float = 30 * _DAY_S
    tombstone_margin_s: float = 7 * _DAY_S
    run_slots: int = 16
    quota_bytes: int = 10 * 1024**3
    retention_s: float = 30 * _DAY_S
    preview_retention_s: float = 7 * _DAY_S
    freshness_skew_s: float = 300.0
    key_retirement_retention_s: float = 37 * _DAY_S


class OperationState(enum.StrEnum):
    """WAL operation-row states."""

    PREPARED = "PREPARED"
    COMMITTED = "COMMITTED"
    CONFLICTED = "CONFLICTED"


class AdmissionState(enum.StrEnum):
    """Admission-row states (``SUSPENDED_WAIT`` is the separate durable flag)."""

    ADMITTED = "ADMITTED"
    DISPATCHED = "DISPATCHED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    TERMINAL = "TERMINAL"


class TerminalState(enum.StrEnum):
    """Terminal outcomes for runs."""

    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    INTERRUPTED = "interrupted"


class LeaseMode(enum.StrEnum):
    """Lease acquisition modes."""

    SHARED = "shared"
    EXCLUSIVE = "exclusive"
