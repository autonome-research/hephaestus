# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Spawn-child stand-in for the G12B sew-ceiling clause (``MESH_INGEST.md`` §4.1).

Not a test module — a ``multiprocessing`` spawn target, so it lives at module
scope in an importable file and imports stdlib only. The real child imports
build123d and OCP, which is exactly what makes the sew worth bounding; a
grinder that paid that import cost could not start inside the small ceilings
this clause sets, and the test would then be measuring an import rather than a
kill. Modelled on ``tests/stage8b/_g8b_grind.py``, the same pattern for the same
reason.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

__all__ = ["PID_FILE_ENV", "grinding_sew_child"]

#: Env var naming the file the child writes its pid to, so the gate can prove
#: the subprocess is dead after the ceiling kill (``COMPARE.md`` §5 addendum).
PID_FILE_ENV = "HEPHAESTUS_TEST_SEW_PID_FILE"


def grinding_sew_child(conn: Any, blob_path: str, brep_path: str, source: str) -> None:
    """Grinds past any ceiling a test would set, sending nothing at all.

    The real sew streams nothing before its single terminal message either —
    unlike the diff, there is no cheap first look to send, because the facts a
    sew timeout carries were computed in the PARENT during canonicalization and
    never crossed to the child. So this grinder is silent by design, and the
    refusal's ``partial`` proves the parent's own facts survived.
    """
    _ = (conn, blob_path, brep_path, source)
    pid_file = os.environ.get(PID_FILE_ENV)
    if pid_file:
        Path(pid_file).write_text(str(os.getpid()), encoding="utf-8")
    time.sleep(600.0)
