"""In-process ``heph`` pipeline tests over the public assembly fixture.

``test_integration.py`` drives the CLI as a subprocess; here ``main()`` runs
in-process (workers still run sandboxed subprocesses via the unsafe backend's
explicit flag) so the command bodies — build/publish plumbing, human output,
``--stale`` sync, ``heph check`` — are exercised directly. Tests in this
module share one project and run in file order.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import cast

import pytest
from hephaestus.core.cli import main
from opstore.types import JSONValue

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "corpus" / "public_fixtures"

UNSAFE = "--unsafe-local-executor"

BROKEN_PART = (
    "plate = Box(50.0, 30.0, 6.0)\n"
    "slot = Box(20.0, 8.0, 6.0)\n"
    "notched = plate - slot\n"
    "bad = fillet(notched.edges().filter_by(Axis.Z), radius=40.0)\n"
    "part.geometry = bad\n"
)


@pytest.fixture(scope="module")
def project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    target = tmp_path_factory.mktemp("cli-pipeline") / "assembly"
    shutil.copytree(FIXTURES / "assembly", target)
    return target


def one_json(out: str) -> dict[str, JSONValue]:
    lines = [line for line in out.strip().splitlines() if line.startswith("{")]
    assert len(lines) == 1, out
    parsed = json.loads(lines[0])
    assert isinstance(parsed, dict)
    return cast("dict[str, JSONValue]", parsed)


def test_build_by_path_emits_build_result_json(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["build", str(project / "parts" / "primary.py"), "--json", UNSAFE])
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    result = one_json(captured.out)
    assert result["part"] == "primary"
    assert result["status"] == "ok"
    assert result["current"] is True


def test_build_by_name_human_output(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(project)
    rc = main(["build", "bracket", UNSAFE])
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert "bracket: ok (current) artifact=artifact:build:" in captured.out
    assert "WITHOUT OS sandboxing" in captured.err


def test_check_project_coherent(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(project)
    rc = main(["check", "--project", "--json"])
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    report = one_json(captured.out)
    checks = report["checks"]
    assert isinstance(checks, dict) and checks, report
    for outcome in checks.values():
        assert isinstance(outcome, dict) and outcome["pass"] is True


def test_check_human_output(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(project)
    rc = main(["check"])
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert ": pass (measured:" in captured.out


def test_param_override_builds_a_preview(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(project)
    rc = main(["build", "bracket", "--param", "wing=50.0", UNSAFE])
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert "bracket: ok (preview)" in captured.out


def test_failed_build_prints_error_record(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (project / "parts" / "broken.py").write_text(BROKEN_PART, encoding="utf-8")
    monkeypatch.chdir(project)
    rc = main(["build", "broken", UNSAFE])
    captured = capsys.readouterr()
    assert rc == 1
    assert "broken: FAILED" in captured.out
    assert "built through line 3" in captured.out
    assert "last good:" in captured.out
    assert "last_good_artifact_ref: artifact:build-checkpoint:" in captured.out
    assert "hint:" in captured.out


def test_check_project_incoherent_after_failed_part(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(project)
    rc = main(["check", "--project"])
    captured = capsys.readouterr()
    assert rc == 1
    assert "incoherent" in captured.err


def test_stale_rebuild_after_globals_edit(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # broken.py never becomes current and never consumes hc; drop it so the
    # stale sweep converges back to a coherent project.
    (project / "parts" / "broken.py").unlink()
    globals_path = project / "globals.py"
    globals_path.write_text(
        globals_path.read_text(encoding="utf-8").replace("shelf_w = 180.0", "shelf_w = 200.0"),
        encoding="utf-8",
    )
    monkeypatch.chdir(project)
    rc = main(["build", "--stale", "--json", UNSAFE])
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    rebuilt = {
        cast("str", json.loads(line)["part"])
        for line in captured.out.strip().splitlines()
        if line.startswith("{")
    }
    assert "primary" in rebuilt  # primary consumes hc.shelf_w


def test_stale_with_nothing_stale_is_a_noop(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(project)
    rc = main(["build", "--stale", UNSAFE])
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert "no stale parts" in captured.out
