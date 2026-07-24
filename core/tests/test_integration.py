"""End-to-end engine integration through the ``heph`` CLI (subprocess).

Covers the full pipeline on the public fixtures: secure-sandboxed builds when
the bwrap probe passes on this machine (it re-probes per run and falls back
to ``--unsafe-local-executor`` with the fallback recorded in the test id
output when it cannot be proven), schema-valid ``--json`` BuildResult output,
current publication, in-worker §6 checks, cross-part ``heph check``, stale
propagation from a globals.py edit plus ``--stale`` rebuild, the failure
fixture's §8 error record, and ``heph lint``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest
from opstore.types import JSONValue

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "corpus" / "public_fixtures"
SCHEMA = cast(
    "dict[str, JSONValue]",
    json.loads((REPO / "core" / "schemas" / "build_result.schema.json").read_text()),
)

CLI_TIMEOUT_S = 300.0

#: Bracket volume at defaults (joint_clear=0.3) and after the 0.5 edit.
BRACKET_VOLUME_DEFAULT = 48.0 * 48.0 * 6.0 + 48.0 * 6.0 * 40.0 - (18.0 + 0.3) * 6.0 * 10.0
BRACKET_VOLUME_EDITED = 48.0 * 48.0 * 6.0 + 48.0 * 6.0 * 40.0 - (18.0 + 0.5) * 6.0 * 10.0


@pytest.fixture(scope="session")
def backend_flags(tmp_path_factory: pytest.TempPathFactory) -> list[str]:
    """[] when the secure bwrap sandbox proves out here; else the unsafe flag.

    bwrap is expected on this machine, so the secure path is the normal one;
    the fallback exists so the suite still exercises the pipeline (minus OS
    isolation) where bwrap is unavailable, per the integration brief.
    """
    from hephaestus.core.executor.sandbox.probe import cached_probe

    report = cached_probe(tmp_path_factory.mktemp("probe-store"))
    return [] if report.available else ["--unsafe-local-executor"]


def run_cli(
    args: list[str], cwd: Path, *, timeout: float = CLI_TIMEOUT_S
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "hephaestus.core.cli", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def json_lines(stdout: str) -> list[dict[str, JSONValue]]:
    out: list[dict[str, JSONValue]] = []
    for line in stdout.strip().splitlines():
        if line.startswith("{"):
            parsed = json.loads(line)
            assert isinstance(parsed, dict)
            out.append(cast("dict[str, JSONValue]", parsed))
    return out


def one_result(completed: subprocess.CompletedProcess[str]) -> dict[str, JSONValue]:
    lines = json_lines(completed.stdout)
    assert len(lines) == 1, completed.stdout + completed.stderr
    return lines[0]


def checks_of(result: dict[str, JSONValue]) -> dict[str, dict[str, JSONValue]]:
    raw = result["checks"]
    assert isinstance(raw, dict)
    return {
        name: cast("dict[str, JSONValue]", entry)
        for name, entry in raw.items()
        if isinstance(entry, dict)
    }


def make_assembly(tmp_dir: Path) -> Path:
    project = tmp_dir / "assembly"
    shutil.copytree(FIXTURES / "assembly", project)
    return project


@pytest.fixture(scope="module")
def assembly(
    tmp_path_factory: pytest.TempPathFactory, backend_flags: list[str]
) -> dict[str, object]:
    """Fresh assembly project with primary (by path) and bracket (by name) built."""
    project = make_assembly(tmp_path_factory.mktemp("assembly-project"))
    primary = run_cli(["build", "parts/primary.py", "--json", *backend_flags], project)
    assert primary.returncode == 0, primary.stderr
    bracket = run_cli(["build", "bracket", "--json", *backend_flags], project)
    assert bracket.returncode == 0, bracket.stderr
    return {
        "dir": project,
        "primary": one_result(primary),
        "bracket": one_result(bracket),
    }


class TestBuildViaCli:
    def test_primary_json_is_schema_valid(self, assembly: dict[str, object]) -> None:
        jsonschema = pytest.importorskip("jsonschema")
        result = cast("dict[str, JSONValue]", assembly["primary"])
        jsonschema.validate(result, SCHEMA)

    def test_primary_published_current(self, assembly: dict[str, object]) -> None:
        result = cast("dict[str, JSONValue]", assembly["primary"])
        assert result["part"] == "primary"
        assert result["status"] == "ok"
        assert result["current"] is True
        artifact_ref = result["artifact_ref"]
        assert isinstance(artifact_ref, str)
        assert artifact_ref.startswith("artifact:build:sha256:")
        assert isinstance(result["source_map_ref"], str)

    def test_primary_checks_ran_in_build(self, assembly: dict[str, object]) -> None:
        checks = checks_of(cast("dict[str, JSONValue]", assembly["primary"]))
        assert set(checks) == {
            "deck_volume",
            "envelope",
            "posts_clear_top_deck",
            "sealed_frame",
        }
        assert all(entry["pass"] is True for entry in checks.values())
        assert checks["deck_volume"]["measured"] == pytest.approx(180.0 * 120.0 * 6.0, abs=1e-6)
        assert checks["posts_clear_top_deck"]["measured"] == pytest.approx(0.0, abs=1e-6)

    def test_primary_geometries_and_params(self, assembly: dict[str, object]) -> None:
        result = cast("dict[str, JSONValue]", assembly["primary"])
        geometries = result["geometries"]
        assert isinstance(geometries, list)
        labels = [cast("dict[str, JSONValue]", entry)["label"] for entry in geometries]
        assert labels == ["bottom_deck", "top_deck", "post", "post#2", "post#3", "post#4"]
        assert result["params"] == {"post_inset": 15.0}

    def test_bracket_published_current(self, assembly: dict[str, object]) -> None:
        jsonschema = pytest.importorskip("jsonschema")
        result = cast("dict[str, JSONValue]", assembly["bracket"])
        jsonschema.validate(result, SCHEMA)
        assert result["status"] == "ok"
        assert result["current"] is True
        metrics = cast("dict[str, JSONValue]", result["metrics"])
        assert metrics["volume_mm3"] == pytest.approx(BRACKET_VOLUME_DEFAULT, abs=1e-6)

    def test_cross_part_check_passes(self, assembly: dict[str, object]) -> None:
        project = cast("Path", assembly["dir"])
        completed = run_cli(["check", "--project", "--json"], project)
        assert completed.returncode == 0, completed.stderr
        report = one_result(completed)
        assert isinstance(report["project_snapshot_ref"], str)
        checks = checks_of(report)
        assert set(checks) == {
            "fit:bracket_clears_frame",
            "fit:bracket_seats_at_joint_clearance",
        }
        assert checks["fit:bracket_clears_frame"]["pass"] is True
        assert checks["fit:bracket_clears_frame"]["measured"] == pytest.approx(0.0, abs=1e-6)
        assert checks["fit:bracket_seats_at_joint_clearance"]["measured"] == pytest.approx(
            0.3, abs=0.01
        )

    def test_lint_clean_fixture_exits_zero(self, assembly: dict[str, object]) -> None:
        project = cast("Path", assembly["dir"])
        completed = run_cli(["lint", "parts/primary.py"], project)
        assert completed.returncode == 0, completed.stdout + completed.stderr

    def test_transient_override_is_preview_not_current(
        self, assembly: dict[str, object], backend_flags: list[str]
    ) -> None:
        project = cast("Path", assembly["dir"])
        completed = run_cli(
            ["build", "primary", "--param", "post_inset=20", "--json", *backend_flags],
            project,
        )
        assert completed.returncode == 0, completed.stderr
        result = one_result(completed)
        assert result["status"] == "ok"
        assert result["current"] is False  # §8: transient overrides => preview
        assert result["params"] == {"post_inset": 20.0}

    def test_out_of_bounds_override_fails(
        self, assembly: dict[str, object], backend_flags: list[str]
    ) -> None:
        project = cast("Path", assembly["dir"])
        completed = run_cli(
            ["build", "primary", "--param", "post_inset=999", "--json", *backend_flags],
            project,
        )
        assert completed.returncode == 1
        result = one_result(completed)
        assert result["status"] == "failed"
        error = cast("dict[str, JSONValue]", result["error"])
        assert "post_inset" in str(error["message"])


@pytest.fixture(scope="module")
def stale_project(tmp_path_factory: pytest.TempPathFactory, backend_flags: list[str]) -> Path:
    project = make_assembly(tmp_path_factory.mktemp("assembly-stale"))
    for target in ("primary", "bracket"):
        completed = run_cli(["build", target, "--json", *backend_flags], project)
        assert completed.returncode == 0, completed.stderr
    # Edit the joint_clear project param default: consumed by bracket only.
    globals_path = project / "globals.py"
    text = globals_path.read_text(encoding="utf-8")
    assert "Param(0.3, min=0, max=0.8)" in text
    globals_path.write_text(
        text.replace("Param(0.3, min=0, max=0.8)", "Param(0.5, min=0, max=0.8)"),
        encoding="utf-8",
    )
    # Rebuilding primary applies the new hc projection; primary does not
    # consume joint_clear so it stays current, while bracket goes stale.
    completed = run_cli(["build", "primary", "--json", *backend_flags], project)
    assert completed.returncode == 0, completed.stderr
    assert one_result(completed)["current"] is True
    return project


class TestStalePropagation:
    """Edit a consumed global -> only its consumers go stale -> --stale rebuilds."""

    def test_consumer_is_stale_and_snapshot_incoherent(self, stale_project: Path) -> None:
        completed = run_cli(["check", "--project"], stale_project)
        assert completed.returncode == 1
        assert "incoherent_project_snapshot" in completed.stderr
        assert "bracket" in completed.stderr
        assert "joint_clear" in completed.stderr

    def test_stale_rebuild_reconverges(self, stale_project: Path, backend_flags: list[str]) -> None:
        completed = run_cli(["build", "--stale", "--json", *backend_flags], stale_project)
        assert completed.returncode == 0, completed.stderr
        results = json_lines(completed.stdout)
        assert [result["part"] for result in results] == ["bracket"]
        rebuilt = results[0]
        assert rebuilt["status"] == "ok"
        assert rebuilt["current"] is True
        metrics = cast("dict[str, JSONValue]", rebuilt["metrics"])
        assert metrics["volume_mm3"] == pytest.approx(BRACKET_VOLUME_EDITED, abs=1e-6)

    def test_snapshot_coherent_and_drift_caught_by_check(self, stale_project: Path) -> None:
        completed = run_cli(["check", "--project", "--json"], stale_project)
        # The snapshot is coherent again, and the persistent cross-part check
        # correctly FAILS: the bracket now seats 0.5 mm away, not 0.3.
        assert completed.returncode == 1
        report = one_result(completed)
        assert isinstance(report["project_snapshot_ref"], str)
        checks = checks_of(report)
        assert checks["fit:bracket_clears_frame"]["pass"] is True
        seat = checks["fit:bracket_seats_at_joint_clearance"]
        assert seat["pass"] is False
        assert seat["measured"] == pytest.approx(0.5, abs=0.01)

    def test_stale_with_no_stale_parts_is_noop(
        self, stale_project: Path, backend_flags: list[str]
    ) -> None:
        completed = run_cli(["build", "--stale", "--json", *backend_flags], stale_project)
        assert completed.returncode == 0, completed.stderr
        assert json_lines(completed.stdout) == []


@pytest.fixture(scope="module")
def failed_result(
    tmp_path_factory: pytest.TempPathFactory, backend_flags: list[str]
) -> dict[str, JSONValue]:
    project = tmp_path_factory.mktemp("failure-project") / "failure"
    shutil.copytree(FIXTURES / "failure_fillet", project)
    (project / "hephaestus.toml").write_text('name = "failure"\n', encoding="utf-8")
    completed = run_cli(["build", "broken", "--json", *backend_flags], project)
    assert completed.returncode == 1
    return one_result(completed)


@pytest.fixture(scope="module")
def manifest() -> dict[str, JSONValue]:
    raw = json.loads((FIXTURES / "failure_fillet" / "fixture.json").read_text())
    assert isinstance(raw, dict)
    return cast("dict[str, JSONValue]", raw)


class TestFailureFixtureViaCli:
    def test_failed_result_schema_valid(self, failed_result: dict[str, JSONValue]) -> None:
        jsonschema = pytest.importorskip("jsonschema")
        jsonschema.validate(failed_result, SCHEMA)
        assert failed_result["status"] == "failed"
        assert failed_result["current"] is False

    def test_error_record_matches_manifest(
        self, failed_result: dict[str, JSONValue], manifest: dict[str, JSONValue]
    ) -> None:
        error = cast("dict[str, JSONValue]", failed_result["error"])
        assert error["line"] == manifest["fail_line"]
        assert error["type"] == manifest["error_type"]
        assert error["built_through"] == manifest["built_through"]
        frame = cast("list[JSONValue]", error["frame"])
        marked = [line for line in frame if str(line).startswith("> ")]
        assert len(marked) == 1
        assert str(marked[0]).startswith(f"> {manifest['fail_line']} | ")
        assert isinstance(error["hint"], str) and error["hint"]

    def test_last_good_populated(
        self, failed_result: dict[str, JSONValue], manifest: dict[str, JSONValue]
    ) -> None:
        error = cast("dict[str, JSONValue]", failed_result["error"])
        last_good = cast("dict[str, JSONValue]", error["last_good"])
        expected = cast("dict[str, JSONValue]", manifest["last_good"])
        assert last_good["solids"] == expected["solids"]
        assert last_good["volume_mm3"] == pytest.approx(
            cast("float", expected["volume_mm3"]), abs=1e-6
        )
        assert last_good["sealed"] == expected["sealed"]
        assert last_good["genus"] == expected["genus"]
        ref = error["last_good_artifact_ref"]
        assert isinstance(ref, str)
        assert ref.startswith("artifact:build-checkpoint:sha256:")


class TestLintMessyFixture:
    @pytest.fixture()
    def messy_project(self, tmp_path: Path) -> Path:
        project = tmp_path / "messy"
        (project / "parts").mkdir(parents=True)
        (project / "hephaestus.toml").write_text('name = "messy"\n', encoding="utf-8")
        (project / "globals.py").write_text(
            'PARAMS = {"sheet_t": Param(6.0, min=3, max=12)}\n', encoding="utf-8"
        )
        (project / "parts" / "messy.py").write_text(
            "PARAMS = {\n"
            '    "sheet_t": Param(6.0, min=3, max=12),\n'
            '    "unused": Param(1.0, min=0, max=2),\n'
            "}\n"
            "plate = Box(10, 10, p.sheet_t)\n"
            "orphan = Box(5, 5, 5)\n"
            'tag(plate.faces().sort_by(Axis.Z)[-1], "never_used")\n'
            "part.geometry = plate\n",
            encoding="utf-8",
        )
        return project

    def test_messy_script_findings_and_exit_code(self, messy_project: Path) -> None:
        completed = run_cli(["lint", "parts/messy.py", "--json"], messy_project)
        assert completed.returncode == 1  # shadowed-param is error severity
        findings_raw = cast("list[JSONValue]", json.loads(completed.stdout))
        assert isinstance(findings_raw, list)
        findings = [cast("dict[str, JSONValue]", f) for f in findings_raw]
        by_code: dict[str, list[dict[str, JSONValue]]] = {}
        for finding in findings:
            by_code.setdefault(str(finding["code"]), []).append(finding)
        assert set(by_code) >= {
            "shadowed-param",
            "unread-param",
            "unreachable-geometry",
            "missing-metadata",
        }
        assert by_code["shadowed-param"][0]["severity"] == "error"
        assert by_code["shadowed-param"][0]["name"] == "sheet_t"
        assert by_code["unread-param"][0]["name"] == "unused"

    def test_lint_missing_file_is_usage_error(self, messy_project: Path) -> None:
        completed = run_cli(["lint", "parts/nope.py"], messy_project)
        assert completed.returncode == 2
