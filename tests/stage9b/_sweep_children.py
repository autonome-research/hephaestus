# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""Spawn-child stand-ins for the bounded sweep tests (``KINEMATICS.md`` §4).

Not a test module — these are ``multiprocessing`` spawn targets, so they live
at module scope in an importable file and deliberately import stdlib only: the
child must start (and misbehave) well inside the small ceilings the tests set,
which a ``build123d`` import would blow on its own. The ``_bounded_grind``
pattern from the ``COMPARE.md`` §5 suite, applied to the sweep child's own
message protocol (``("sample", …)*`` then ``("done"|"refusal", …)``).
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

__all__ = [
    "PID_FILE_ENV",
    "STREAMED_SAMPLES",
    "dying_child",
    "grinding_child",
    "silent_child",
]

#: Env var naming the file a child writes its pid to, so a test can prove the
#: subprocess is dead after the ceiling kill.
PID_FILE_ENV = "HEPHAESTUS_TEST_SWEEP_PID_FILE"

#: The per-sample facts a misbehaving child streams before it stops answering —
#: shaped exactly like the real child's ``("sample", (values, measured))``.
STREAMED_SAMPLES: list[tuple[dict[str, float], float]] = [
    ({"j-hinge": -10.0}, 0.1),
    ({"j-hinge": 0.0}, 0.1),
]


def _report_pid() -> None:
    pid_file = os.environ.get(PID_FILE_ENV)
    if pid_file:
        Path(pid_file).write_text(str(os.getpid()), encoding="utf-8")


def grinding_child(conn: Any, spec: Any) -> None:
    """Streams two per-sample facts, then grinds past any ceiling a test sets."""
    _ = spec
    _report_pid()
    for fact in STREAMED_SAMPLES:
        conn.send(("sample", fact))
    time.sleep(600.0)


def dying_child(conn: Any, spec: Any) -> None:
    """Streams two per-sample facts, then dies the way a segfaulting kernel does."""
    _ = spec
    _report_pid()
    for fact in STREAMED_SAMPLES:
        conn.send(("sample", fact))
    os._exit(7)


def silent_child(conn: Any, spec: Any) -> None:
    """Never answers at all: the refusal must carry zero samples, not a guess."""
    _ = (conn, spec)
    _report_pid()
    time.sleep(600.0)
