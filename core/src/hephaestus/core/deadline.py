# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Suspend-inclusive, boot-local deadlines; never adjustable calendar time.

Darwin >= 10.12: mach_continuous_time ticks * mach_timebase_info numer/denom
are nanoseconds. Linux >= 2.6.39: clock_gettime(CLOCK_BOOTTIME) is nanoseconds.
Missing facilities fail closed. Values must not be persisted across reboot or
compared across hosts (including a host and its VM). Waiting primitives merely
schedule checks; they are NOT the authority for expiry.
"""

from __future__ import annotations

import ctypes
import math
import subprocess
import sys
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

POLL_SECONDS = 0.1


class ClockUnavailable(RuntimeError):
    """No supported suspend-inclusive clock; do not admit bounded work."""


@lru_cache(maxsize=1)
def clock_source() -> tuple[str, Callable[[], int]]:
    """Acquire the platform facility and its explicit nanosecond conversion."""
    if sys.platform == "darwin":

        class Timebase(ctypes.Structure):
            _fields_ = [("numer", ctypes.c_uint32), ("denom", ctypes.c_uint32)]

        try:
            lib = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
            ticks = lib.mach_continuous_time
            ticks.argtypes = []
            ticks.restype = ctypes.c_uint64
            info = lib.mach_timebase_info
            info.argtypes = [ctypes.POINTER(Timebase)]
            info.restype = ctypes.c_int
            scale = Timebase()
            if info(ctypes.byref(scale)) != 0 or not scale.numer or not scale.denom:
                raise ClockUnavailable("invalid Darwin mach timebase")
        except (OSError, AttributeError) as exc:
            raise ClockUnavailable(
                "mach_continuous_time unavailable (requires macOS 10.12+)"
            ) from exc
        numer, denom = int(scale.numer), int(scale.denom)
        return f"mach_continuous_time * {numer}/{denom} ns", lambda: int(ticks()) * numer // denom
    if sys.platform == "linux" and hasattr(time, "CLOCK_BOOTTIME"):
        return "clock_gettime_ns(CLOCK_BOOTTIME)", lambda: time.clock_gettime_ns(
            time.CLOCK_BOOTTIME
        )
    raise ClockUnavailable("suspend-inclusive deadlines require Darwin or Linux CLOCK_BOOTTIME")


def continuous_ns() -> int:
    try:
        value = clock_source()[1]()
    except (OSError, ValueError) as exc:
        raise ClockUnavailable("continuous clock read failed") from exc
    if value < 0:
        raise ClockUnavailable("invalid continuous clock value")
    return value


def continuous_seconds() -> float:
    return continuous_ns() / 1_000_000_000


def clock_description() -> str:
    continuous_ns()  # availability includes an actual read, not just a symbol lookup
    return clock_source()[0]


@dataclass(frozen=True)
class Deadline:
    """Absolute nanoseconds on THIS boot's continuous clock. Not UTC."""

    end_ns: int

    @classmethod
    def after(cls, seconds: float) -> Deadline:
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("deadline duration must be finite and nonnegative")
        return cls(continuous_ns() + int(seconds * 1_000_000_000))

    def remaining(self) -> float:
        remaining = self.end_ns - continuous_ns()
        if remaining <= 0:
            raise TimeoutError("suspend-inclusive deadline expired")
        return remaining / 1_000_000_000

    def expired(self) -> bool:
        return continuous_ns() >= self.end_ns

    def cap(self, seconds: float) -> float:
        return min(seconds, self.remaining())


transport_deadline: ContextVar[Deadline | None] = ContextVar("transport_deadline", default=None)


@contextmanager
def transport_budget(deadline: Deadline | None) -> Generator[None]:
    """Carry an absolute host deadline through synchronous evidence wrappers.

    Relative timeout conversion alone would restart the allowance if the host
    slept while a wrapper was recording evidence before the actual launch.
    Cleanup calls enter explicitly with their separate deadline.
    """
    token = transport_deadline.set(deadline)
    try:
        yield
    finally:
        transport_deadline.reset(token)


def wait_process(process: subprocess.Popen[Any], deadline: Deadline) -> int:
    """Bounded polling; caller owns signalling, reaping and cleanup policy.

    Recheck AFTER wait: a ready result on wake does not trump expiration.
    Preserve subprocess.TimeoutExpired for existing lifecycle handlers.
    """
    while True:
        try:
            remaining = deadline.remaining()
        except TimeoutError as exc:
            raise subprocess.TimeoutExpired(process.args, 0) from exc
        try:
            code = process.wait(timeout=min(POLL_SECONDS, remaining))
        except subprocess.TimeoutExpired:
            continue
        if deadline.expired():
            raise subprocess.TimeoutExpired(process.args, 0)
        return code
