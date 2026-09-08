"""``core.motion``'s bounded sweep (J-build-state-4, motion half): death != ceiling.

``core/motion.py:_bounded_sweep`` used to report a dead sweep subprocess as
``MotionTimeout`` — the same reason, and the same 300 s-class ceiling, a
ceiling kill gets — even though no ceiling fired and the child died after
however long it took. ``MotionChildDied`` is the sibling this item adds,
sharing the ``MotionCutShort`` carriage with ``MotionTimeout`` so every
existing catch (the check engine's ``unverifiable`` mapping, the tool
mapping) sees both without having to be told about the new reason by name.

These tests drive ``_bounded_sweep`` directly with a stand-in for
``_sweep_child`` (module-scope, stdlib-only, the ``_bounded_grind.py``
precedent) rather than a real motion check, to keep the fixture cheap and the
subject narrow: this item is about which exception a cut-short sweep raises,
not about sweep evaluation itself (covered elsewhere, in ``tests/stage9b``).
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, cast

import hephaestus.core.motion as motion
import pytest
from hephaestus.core.motion import (
    MOTION_TIMEOUT_ENV,
    MotionChildDied,
    MotionCutShort,
    MotionTimeout,
    _bounded_sweep,  # pyright: ignore[reportPrivateUsage]
)

PID_FILE_ENV = "HEPHAESTUS_TEST_MOTION_SWEEP_PID_FILE"


def _report_pid() -> None:
    pid_file = os.environ.get(PID_FILE_ENV)
    if pid_file:
        Path(pid_file).write_text(str(os.getpid()), encoding="utf-8")


def _streaming_then_dying_child(conn: Any, spec: Any) -> None:
    """Streams two samples, then dies (the sweep's SIGSEGV mode)."""
    _ = spec
    _report_pid()
    conn.send(("sample", ({"x": 0.0}, 1.0)))
    conn.send(("sample", ({"x": 1.0}, 2.0)))
    conn.close()
    os._exit(4)


def _streaming_then_grinding_child(conn: Any, spec: Any) -> None:
    """Streams one sample, then grinds past any ceiling a test sets."""
    _ = spec
    _report_pid()
    conn.send(("sample", ({"x": 0.0}, 1.0)))
    time.sleep(600.0)


def _assert_child_dead(pid_file: Path) -> None:
    pid = int(pid_file.read_text(encoding="utf-8"))
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_a_dead_sweep_child_is_motion_child_died_not_a_timeout_with_a_false_ceiling(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pid_file = tmp_path / "child.pid"
    monkeypatch.setattr(motion, "_sweep_child", _streaming_then_dying_child)
    monkeypatch.setenv(PID_FILE_ENV, str(pid_file))

    with pytest.raises(MotionChildDied) as excinfo:
        _bounded_sweep({}, check_id="reach_check", grid_total=9, timeout_s=120.0)

    refusal = excinfo.value
    assert isinstance(refusal, MotionCutShort)
    assert not isinstance(refusal, MotionTimeout)
    assert refusal.reason == "motion_child_died"
    assert refusal.exit_code == 4
    assert refusal.check_id == "reach_check"
    assert refusal.grid_total == 9
    assert refusal.samples_evaluated == 2
    document = refusal.to_json()
    assert document["reason"] == "motion_child_died"
    assert document["exit_code"] == 4
    assert "timeout_s" not in document, "no ceiling fired — asserting one is dishonest"
    assert len(cast("list[Any]", document["partial"])) == 2
    _assert_child_dead(pid_file)


def test_a_genuine_sweep_ceiling_still_reports_the_ceiling(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The other half: a still-alive grinder is ``MotionTimeout``, with its
    ceiling — proving the split discriminates rather than having renamed the
    only reason there used to be."""
    pid_file = tmp_path / "child.pid"
    monkeypatch.setattr(motion, "_sweep_child", _streaming_then_grinding_child)
    monkeypatch.setenv(PID_FILE_ENV, str(pid_file))

    with pytest.raises(MotionTimeout) as excinfo:
        _bounded_sweep({}, check_id="reach_check", grid_total=9, timeout_s=1.0)

    refusal = excinfo.value
    assert isinstance(refusal, MotionCutShort)
    assert refusal.reason == "motion_timeout"
    assert refusal.timeout_s == 1.0
    assert refusal.samples_evaluated == 1
    document = refusal.to_json()
    assert document["timeout_s"] == 1.0
    assert "exit_code" not in document, "the ceiling fired — there is no exit code to report"
    assert MOTION_TIMEOUT_ENV in refusal.message
    _assert_child_dead(pid_file)


def test_a_predicate_whose_sweep_child_dies_is_unverifiable_and_diagnosable_by_reason() -> None:
    """The check engine catches ``MotionCutShort`` (the carriage), so a dead
    sweep lands as ``unverifiable`` exactly like a ceiling kill would, with the
    entry's own reason saying which one it was."""
    from collections.abc import Callable

    from hephaestus.core.checks.engine import run_checks
    from hephaestus.core.checks.facade import Measurement

    def predicate(_measurement: object) -> bool:
        raise MotionChildDied(
            "motion check reach_check: sweep subprocess died (exit code 4) before "
            "the grid finished",
            check_id="reach_check",
            exit_code=4,
            grid_total=9,
            partial=(),
        )

    results = run_checks(
        {"reach_check": predicate},
        measurement_factory=cast("Callable[[], Measurement]", lambda: object()),
    )

    result = results["reach_check"]
    assert result.passed is False
    measured = cast("dict[str, Any]", result.measured)
    unverifiable = cast("dict[str, Any]", measured["unverifiable"])
    assert unverifiable["reason"] == "motion_child_died"
    assert unverifiable["exit_code"] == 4


# ==========================================================================
# J-agent-results-8a, the read half: both encodings of "no artifact" load


def test_motion_status_from_json_accepts_null_and_empty_artifact_refs() -> None:
    """A status round-tripped through the reader keeps every part it named.

    The write half of 8a made the model-facing document say ``null`` for a
    part that contributed no artifact, because the store's own sentinel — the
    empty string — reads to a model as "this part HAS an artifact whose id
    happens to be empty". The reader kept only ``str`` values, so the null it
    now emits was DROPPED: the key vanished, which says something different
    again ("that part was never mentioned"). Both encodings must load, and the
    ledger's fix clause says so in as many words: "accept both encodings on
    read so a status written before the change still loads".
    """
    from hephaestus.core.motion import MotionStatus

    status = MotionStatus.from_json(
        {
            "joint_generation": 3,
            "pose_generation": 1,
            "joints": [],
            "poses": [],
            "artifact_refs": {
                "widget": "artifact:part:sha256:" + "a" * 64,
                "bracket": None,
                "legacy": "",
            },
            "stale": [],
        }
    )

    assert set(status.artifact_refs) == {"widget", "bracket", "legacy"}
    assert status.artifact_refs["widget"].startswith("artifact:part:")
    # Null and the legacy empty string are the same fact — "this part
    # contributed no artifact" — and both survive the read as the store's own
    # in-memory spelling of it.
    assert status.artifact_refs["bracket"] == ""
    assert status.artifact_refs["legacy"] == ""
