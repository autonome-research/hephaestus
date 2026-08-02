"""Spawn-child stand-ins for the bounded diff tests (``COMPARE.md`` §5).

Not a test module — these are ``multiprocessing`` spawn targets, so they live
at module scope in an importable file and deliberately import stdlib only: the
child must start (and misbehave) well inside the small ceilings the tests set,
which a ``build123d`` import would blow on its own.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

__all__ = ["CHEAP_FACTS", "PID_FILE_ENV", "dying_child", "grinding_child", "silent_child"]

#: Env var naming the file a child writes its pid to, so a test can prove the
#: subprocess is dead after the ceiling kill.
PID_FILE_ENV = "HEPHAESTUS_TEST_DIFF_PID_FILE"

#: The cheap first look a grinding child streams before it stops answering —
#: shaped like the real child's census+bboxes+volumes message.
CHEAP_FACTS: dict[str, Any] = {
    "topology": {
        "solids_delta": 0,
        "faces_delta": 3,
        "edges_delta": 6,
        "genus_delta": 1,
        "sealed_changed": False,
    },
    "a_bbox_mm": [40.0, 20.0, 5.0],
    "b_bbox_mm": [40.0, 20.0, 5.0],
    "a_volume_mm3": 4000.0,
    "b_volume_mm3": 3858.4,
}


def _report_pid() -> None:
    pid_file = os.environ.get(PID_FILE_ENV)
    if pid_file:
        Path(pid_file).write_text(str(os.getpid()), encoding="utf-8")


def grinding_child(conn: Any, a_path: str, b_path: str, align: str) -> None:
    """Streams the cheap facts, then grinds past any ceiling a test would set."""
    _ = (a_path, b_path, align)
    _report_pid()
    conn.send(("cheap", CHEAP_FACTS))
    time.sleep(600.0)


def dying_child(conn: Any, a_path: str, b_path: str, align: str) -> None:
    """Streams the cheap facts, then dies the way a segfaulting kernel does."""
    _ = (a_path, b_path, align)
    _report_pid()
    conn.send(("cheap", CHEAP_FACTS))
    os._exit(7)


def silent_child(conn: Any, a_path: str, b_path: str, align: str) -> None:
    """Never answers at all: the refusal must name every half as lost."""
    _ = (conn, a_path, b_path, align)
    _report_pid()
    time.sleep(600.0)
