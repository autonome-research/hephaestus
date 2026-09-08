# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""One free-port helper, with the retry that makes the race recoverable.

Picking a port by binding zero, reading the number and closing the socket is
inherently racy: between the close and the server's own bind, anything on the
machine can take it. The race cannot be closed — there is no way to make the two
binds atomic — so the property worth having is *recovery*, and recovery is
exactly what four byte-identical copies of the picker made too expensive to add
(J-mirrors-and-dx-21). One copy is one place to put the retry.

Two shapes, deliberately:

* :func:`free_port` picks a number, for the one or two callers that genuinely
  need only a number and start nothing;
* :func:`with_free_port` picks a number, calls the caller's start function with
  it, and picks a new one if the start fails on a bind collision — so the retry
  actually covers the window rather than sitting next to it.

``tests/stage3`` deliberately keeps its own copy: the Gate G3 client toolkit
must import no ``hephaestus`` code at all and a test enforces that structurally,
so importing this module there would break the gate it exists to prove.
"""

from __future__ import annotations

import errno
import socket
from collections.abc import Callable
from typing import TypeVar

__all__ = ["free_port", "with_free_port"]

T = TypeVar("T")

#: How many times :func:`with_free_port` re-picks before giving up. The window
#: is milliseconds wide, so a second collision is already implausible and a
#: third means something on the machine is claiming ports faster than we can.
_ATTEMPTS = 5


def free_port() -> int:
    """A port that was free a moment ago on the loopback interface."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _is_bind_collision(exc: Exception) -> bool:
    """Is ``exc`` "somebody else took the port" rather than a real failure?

    Narrow on purpose. Retrying a start that failed for any other reason would
    turn one clear error into the same error five times.
    """
    if isinstance(exc, OSError) and exc.errno in {errno.EADDRINUSE, errno.EADDRNOTAVAIL}:
        return True
    return "address already in use" in str(exc).lower()


def with_free_port(start: Callable[[int], T]) -> T:
    """Call ``start(port)`` on a free port, re-picking on a bind collision.

    The caller passes its own start closure rather than a port, because the
    retry is only meaningful on the far side of the bind: a helper that returns
    a number has already let go of it.
    """
    last: Exception | None = None
    for _ in range(_ATTEMPTS):
        port = free_port()
        try:
            return start(port)
        except Exception as exc:  # re-raised below unless it is the bind race
            if not _is_bind_collision(exc):
                raise
            last = exc
    raise AssertionError(
        f"could not start on a free port after {_ATTEMPTS} attempts; last failure: {last}"
    )
