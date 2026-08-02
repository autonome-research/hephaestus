"""Spawn-child stand-in for the G8B bounded-execution clauses (``COMPARE.md`` §5).

Not a test module — a ``multiprocessing`` spawn target, so it lives at module
scope in an importable file and imports stdlib only: the child must start and
stream its facts well inside the small ceilings the tests set, which importing
the product (or ``build123d``) would blow on its own.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

__all__ = ["CHEAP_FACTS", "PID_FILE_ENV", "grinding_child"]

#: Env var naming the file the child writes its pid to, so the gate can prove
#: the subprocess is dead after the ceiling kill (COMPARE.md §5 addendum).
PID_FILE_ENV = "HEPHAESTUS_TEST_DIFF_PID_FILE"

#: The cheap first look the grinder streams before it stops answering — shaped
#: like the real child's census+bboxes+volumes message.
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


def grinding_child(conn: Any, a_path: str, b_path: str, align: str) -> None:
    """Streams the cheap facts, then grinds past any ceiling a test would set."""
    _ = (a_path, b_path, align)
    pid_file = os.environ.get(PID_FILE_ENV)
    if pid_file:
        Path(pid_file).write_text(str(os.getpid()), encoding="utf-8")
    conn.send(("cheap", CHEAP_FACTS))
    time.sleep(600.0)
