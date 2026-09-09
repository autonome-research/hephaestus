"""``compare_solids`` (J-build-state-4, tool half): a crashed child is its own token.

``CompareOps.compare_solids`` used to catch ``CompareTimeout`` by name, so a
crashed comparison — reported by ``core/project_compare.py`` as
``CompareChildDied`` — would fall through to the generic ``except
CompareRefusal`` branch, which maps by ``exc.reason`` through a dict with no
``compare_child_died`` entry, defaulting to ``invalid_params``. That would have
told the model the wrong story twice over: the token says "your parameters are
bad" for a kernel crash, and the ``partial``/``lost`` evidence a crash still
has would be dropped along with it. The fix catches
``CompareCutShort`` (the base both ``CompareTimeout`` and ``CompareChildDied``
share) so neither reason can be missed by the tool layer, and carries the
exit code on the death branch, the ceiling on the timeout branch, never both.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import hephaestus.core.project_compare as project_compare
import pytest
from hephaestus.agent_bridge.cad_ops._base import CadOpError
from hephaestus.testing.tools_fixture import Project, make_project

PID_FILE_ENV = "HEPHAESTUS_TEST_CAD_OPS_COMPARE_PID_FILE"


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Project]:
    p = make_project(tmp_path / "proj")
    try:
        yield p
    finally:
        p.close()


def _report_pid() -> None:
    pid_file = os.environ.get(PID_FILE_ENV)
    if pid_file:
        Path(pid_file).write_text(str(os.getpid()), encoding="utf-8")


def _dying_diff_child(conn: Any, a_path: str, b_path: str, align: str) -> None:
    _ = (a_path, b_path, align)
    _report_pid()
    conn.close()
    os._exit(5)


def _grinding_diff_child(conn: Any, a_path: str, b_path: str, align: str) -> None:
    _ = (a_path, b_path, align)
    _report_pid()
    time.sleep(600.0)


def _assert_child_dead(pid_file: Path) -> None:
    pid = int(pid_file.read_text(encoding="utf-8"))
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_a_crashed_compare_child_is_its_own_token_with_the_exit_code_not_invalid_params(
    project: Project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project.build("widget", "bracket")
    pid_file = tmp_path / "child.pid"
    monkeypatch.setattr(project_compare, "_diff_child", _dying_diff_child)
    monkeypatch.setenv(PID_FILE_ENV, str(pid_file))

    with pytest.raises(CadOpError) as excinfo:
        project.cad.compare_solids("widget", "part:bracket")

    error = excinfo.value
    assert error.reason == "compare_child_died", (
        "a crash must not fall through to the generic invalid_params mapping"
    )
    assert error.data["exit_code"] == 5
    assert "timeout_s" not in error.data, "no ceiling fired — asserting one is dishonest"
    assert "partial" in error.data
    assert "lost" in error.data
    _assert_child_dead(pid_file)


def test_a_genuine_compare_ceiling_still_carries_the_ceiling_not_an_exit_code(
    project: Project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other half of the split at the tool layer: a real ceiling keeps its
    own token and its own (ceiling) field, proving the two are discriminated
    rather than the crash having quietly taken over the timeout's shape."""
    project.build("widget", "bracket")
    pid_file = tmp_path / "child.pid"
    monkeypatch.setattr(project_compare, "_diff_child", _grinding_diff_child)
    monkeypatch.setenv(PID_FILE_ENV, str(pid_file))
    monkeypatch.setenv(project_compare.COMPARE_TIMEOUT_ENV, "8.0")

    with pytest.raises(CadOpError) as excinfo:
        project.cad.compare_solids("widget", "part:bracket")

    error = excinfo.value
    assert error.reason == "compare_timeout"
    assert error.data["timeout_s"] == 8.0
    assert "exit_code" not in error.data
    _assert_child_dead(pid_file)


def test_compare_solids_still_answers_a_completed_comparison(project: Project) -> None:
    """Sanity guard: neither refusal path is exercised on the ordinary case."""
    project.build("widget", "bracket")

    result = project.cad.compare_solids("widget", "part:bracket")

    assert result["status"] == "ok"
