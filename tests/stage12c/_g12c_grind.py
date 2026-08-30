# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Spawn-child stand-in for the G12C scan-ceiling clause (``MESH_INGEST.md`` §7.3).

Not a test module — a ``multiprocessing`` spawn target, so it lives at module
scope in an importable file. It differs from ``tests/stage12b/_g12b_grind.py``
in one deliberate way, and the difference is the whole point of clause 44.

The sew grinder sends **nothing**: a sew timeout's partial facts were computed
in the parent and never crossed to the child, so a silent grinder is the honest
fault injection there. A scan timeout is the opposite. Its facts are computed in
the *child* — the cheap look at the scan first, then one directed distance, then
the other — and clause 44 asks for the refusal to carry "quality + bbox +
whichever direction completed". A grinder that sent nothing would prove only
that an empty refusal is empty.

So this one runs the **real child** and injects the fault *inside the geometry
call*, at a named stage: it replaces one directed-distance primitive with a
sleep and lets everything before it run for real. What the refusal then carries
is what the product actually measured, not what a stand-in decided to send.

* ``STAGE_SCAN_TO_PART`` — direction A grinds. The cheap facts stream and both
  directions are lost, which is the clause's first half.
* ``STAGE_PART_TO_SCAN`` — direction A completes for real and direction B
  grinds, which is the "whichever direction completed" half.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

__all__ = [
    "GRIND_STAGE_ENV",
    "PID_FILE_ENV",
    "STAGE_PART_TO_SCAN",
    "STAGE_SCAN_TO_PART",
    "grinding_distance_child",
]

#: Env var naming the file the child writes its pid to, so the gate can prove
#: the subprocess is dead after the ceiling kill (``COMPARE.md`` §5 addendum).
PID_FILE_ENV = "HEPHAESTUS_TEST_SCAN_PID_FILE"

#: Env var naming which direction to grind in.
GRIND_STAGE_ENV = "HEPHAESTUS_TEST_SCAN_GRIND_STAGE"

STAGE_SCAN_TO_PART = "scan_to_part"
STAGE_PART_TO_SCAN = "part_to_scan"

#: Long enough that no ceiling a test sets can be met, short enough that a
#: leaked child cannot outlive a CI job.
_GRIND_S = 600.0


def _grind(*_args: Any, **_kwargs: Any) -> Any:
    time.sleep(_GRIND_S)
    raise AssertionError("the grinder must be killed, never resumed")


def grinding_distance_child(conn: Any, *args: Any) -> None:
    """The real ``_distance_child`` with one directed distance replaced by a sleep.

    Patched inside the spawned child rather than in the parent, because ``spawn``
    re-imports every module fresh: a parent-side monkeypatch of a geom primitive
    would not survive the crossing, and a grinder that pretended it had would be
    asserting against its own stand-in.
    """
    pid_file = os.environ.get(PID_FILE_ENV)
    if pid_file:
        Path(pid_file).write_text(str(os.getpid()), encoding="utf-8")

    stage = os.environ.get(GRIND_STAGE_ENV, STAGE_PART_TO_SCAN)
    if stage == STAGE_SCAN_TO_PART:
        # Direction A: the exact scan→part measurement. Nothing but the cheap
        # facts can have arrived when this hangs.
        from hephaestus.geom import compare as geom_compare

        geom_compare._point_distances = _grind  # pyright: ignore[reportPrivateUsage]
    else:
        # Direction B: the mesh-side sampling. Direction A has completed and
        # been streamed by the time this hangs.
        from hephaestus.geom import mesh as geom_mesh

        geom_mesh.point_mesh_distances = _grind

    from hephaestus.core.scan_compare import _distance_child

    _distance_child(conn, *args)
