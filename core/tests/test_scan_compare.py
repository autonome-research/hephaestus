"""``core.scan_compare``'s bounded distance (J-build-state-5): the control, after adoption.

``bounded_scan_distance`` was the ONE correct copy of the four hand-copied
bounded-subprocess loops (J-build-state-5): the only one that drained the pipe
once more after the deadline, and the only one that recomputed the death flag
so a run that answered could never be reported as having died. It is the
reference the shared :func:`~hephaestus.core.executor.bounded_pass.run_bounded_pass`
helper is built from, so adopting the helper here should be *behaviour-
preserving* — the gate note calls this call site "the control" for exactly
that reason.

Unlike ``project_compare`` and ``motion`` (J-build-state-4), this item does
NOT split ``ScanTimeout`` into a ceiling reason and a death reason: J-build-
state-4 names only compare and motion for that split. A dead scan child and a
ceiling-killed one both stay ``scan_timeout`` here, distinguished only by the
message — and that is a deliberate scope boundary, not a gap, so this suite
pins it explicitly rather than silently assuming the same split landed here
too.
"""

from __future__ import annotations

import inspect
import os
import time
from pathlib import Path
from typing import Any

import hephaestus.core.scan_compare as scan_compare
import pytest
from build123d import Box
from hephaestus.core.scan_compare import (
    LOST_PART_TO_SCAN,
    LOST_SCAN_FACTS,
    LOST_SCAN_TO_PART,
    ScanTimeout,
    bounded_scan_distance,
)

PID_FILE_ENV = "HEPHAESTUS_TEST_SCAN_DISTANCE_PID_FILE"

#: Shaped like the real child's first message (``scan_cheap_facts``' output) —
#: only what these tests read out of ``partial`` matters.
CHEAP: dict[str, Any] = {"kind": "mesh", "source_path": "limb.stl"}


def _report_pid() -> None:
    pid_file = os.environ.get(PID_FILE_ENV)
    if pid_file:
        Path(pid_file).write_text(str(os.getpid()), encoding="utf-8")


def _dying_distance_child(conn: Any, *args: Any) -> None:
    _ = args
    _report_pid()
    conn.send(("cheap", CHEAP))
    conn.close()
    os._exit(6)


def _silent_distance_child(conn: Any, *args: Any) -> None:
    _ = (conn, args)
    _report_pid()
    time.sleep(600.0)


def _assert_child_dead(pid_file: Path) -> None:
    pid = int(pid_file.read_text(encoding="utf-8"))
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_scan_compare_adopts_the_shared_bounded_pass_helper_not_its_own_loop() -> None:
    """Structural half of the adoption: this module must call
    ``run_bounded_pass`` rather than carrying its own spawn/poll/deadline body
    — the whole point of J-build-state-5."""
    source = inspect.getsource(scan_compare)
    assert "run_bounded_pass(" in source
    assert "import multiprocessing" not in source, (
        "scan_compare.py must not import multiprocessing directly once it "
        "adopts core/executor/bounded_pass.py"
    )


def test_a_dead_scan_child_is_still_scan_timeout_by_deliberate_scope(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Pinned, not assumed: J-build-state-4 did not touch scan, so a dead scan
    child keeps the one ``scan_timeout`` reason — discriminated only by the
    message, unlike compare's ``CompareChildDied``/motion's ``MotionChildDied``."""
    pid_file = tmp_path / "child.pid"
    monkeypatch.setattr(scan_compare, "_distance_child", _dying_distance_child)
    monkeypatch.setenv(PID_FILE_ENV, str(pid_file))

    with pytest.raises(ScanTimeout) as excinfo:
        bounded_scan_distance(
            Box(10.0, 10.0, 10.0), b"blob", "{}", source="limb.stl", timeout_s=120.0
        )

    refusal = excinfo.value
    assert refusal.reason == "scan_timeout"
    assert "died" in refusal.message and "exit code 6" in refusal.message
    assert refusal.partial == CHEAP
    assert set(refusal.lost) == {LOST_SCAN_TO_PART, LOST_PART_TO_SCAN}
    assert LOST_SCAN_FACTS not in refusal.lost, "the cheap facts arrived before the death"
    _assert_child_dead(pid_file)


def test_a_genuine_scan_ceiling_still_names_the_ceiling_in_its_message(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pid_file = tmp_path / "child.pid"
    monkeypatch.setattr(scan_compare, "_distance_child", _silent_distance_child)
    monkeypatch.setenv(PID_FILE_ENV, str(pid_file))

    with pytest.raises(ScanTimeout) as excinfo:
        bounded_scan_distance(
            Box(10.0, 10.0, 10.0), b"blob", "{}", source="limb.stl", timeout_s=10.0
        )

    refusal = excinfo.value
    assert refusal.reason == "scan_timeout"
    assert "did not finish" in refusal.message and "killed" in refusal.message
    assert "died" not in refusal.message
    assert refusal.partial is None
    _assert_child_dead(pid_file)
