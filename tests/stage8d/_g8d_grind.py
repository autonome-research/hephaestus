"""Spawn-child stand-in for the G8D uncharged-fault clause (``EXTERNAL_EVAL.md`` §5).

Not a test module — a ``multiprocessing`` spawn target, so it lives at module
scope in an importable file and imports stdlib only: the child must start and
stream its facts well inside the small ceiling the test sets, which importing
the product (or ``build123d``) would blow on its own.
"""

from __future__ import annotations

import time
from typing import Any

__all__ = ["CHEAP_FACTS", "grinding_child"]

#: The cheap first look the grinder streams before it stops answering — shaped
#: like the real child's census+bboxes+volumes message.
CHEAP_FACTS: dict[str, Any] = {
    "topology": {
        "solids_delta": 0,
        "faces_delta": 0,
        "edges_delta": 0,
        "genus_delta": 0,
        "sealed_changed": False,
    },
    "a_bbox_mm": [20.0, 6.0, 4.0],
    "b_bbox_mm": [20.0, 10.0, 4.0],
    "a_volume_mm3": 480.0,
    "b_volume_mm3": 800.0,
}


def grinding_child(conn: Any, a_path: str, b_path: str, align: str) -> None:
    """Streams the cheap facts, then grinds past any ceiling a test would set."""
    _ = (a_path, b_path, align)
    conn.send(("cheap", CHEAP_FACTS))
    time.sleep(600.0)
