"""Explicit request-scoped cancellation across async -> synchronous execution.

Cancelling the await delivers a stop to the worker's scope, then waits for its
bounded cleanup. No lock/temporary directory is released while its thread runs.
Native backends without a cancellation consumer still finish before unwinding;
this module does not pretend that cancellation of to_thread stops them.
"""

from __future__ import annotations

import asyncio
import contextvars
import socket
import threading
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


class ExecutionCancelled(Exception):
    """Delivered stop (reason retained), distinct from worker wall timeout/failure."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.stdout = b""
        self.stderr = b""


class Cancellation:
    def __init__(self) -> None:
        self.reader, self.writer = socket.socketpair()
        self._lock = threading.Lock()
        self.reason: str | None = None

    def cancel(self, reason: str = "user_cancel") -> None:
        with self._lock:
            if self.reason is None:
                self.reason = reason
                self.writer.sendall(b"!")

    def check(self) -> None:
        if self.reason is not None:
            raise ExecutionCancelled(self.reason)

    def close(self) -> None:
        self.reader.close()
        self.writer.close()

    def __enter__(self) -> Cancellation:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


current_cancellation: contextvars.ContextVar[Cancellation | None] = contextvars.ContextVar(
    "execution_cancellation", default=None
)


async def run_cancellable(call: Callable[[], T]) -> T:
    """Supported async boundary for one synchronous dispatch/build operation."""
    with Cancellation() as control:
        token = current_cancellation.set(control)
        try:
            task = asyncio.create_task(asyncio.to_thread(call))
        finally:
            current_cancellation.reset(token)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            # An asyncio cancellation may also be a caller deadline/disconnect.
            # Only cancel_active() explicitly requests a user stop for acceptance.
            control.cancel("caller_cancel")
            # Repeated cancellation must not abandon cleanup or the operation lock.
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
                except ExecutionCancelled:
                    break
            if not task.cancelled():
                error = task.exception()
                if error is not None and not isinstance(error, ExecutionCancelled):
                    raise error from None  # cleanup uncertainty must not be hidden
            raise
