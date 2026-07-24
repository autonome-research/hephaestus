"""Fast in-process unit tests for the ``heph`` CLI surface (no geometry).

Usage-error exit codes (2), lint command behavior, and argument parsing.
Everything that spawns a worker lives in ``test_integration.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from hephaestus.core.cli import main
from opstore.types import JSONValue

CLEAN_PART = (
    'PARAMS = {"width": Param(10.0, min=5, max=20)}\n'
    "plate = Box(p.width, 10, 2)\n"
    "part.geometry = plate\n"
    'part.description = "clean plate"\n'
    'part.process = "cnc_router"\n'
)


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "parts").mkdir(parents=True)
    (root / "hephaestus.toml").write_text('name = "proj"\n', encoding="utf-8")
    (root / "globals.py").write_text(
        'PARAMS = {"sheet_t": Param(6.0, min=3, max=12)}\n', encoding="utf-8"
    )
    (root / "parts" / "plate.py").write_text(CLEAN_PART, encoding="utf-8")
    return root


class TestUsageErrors:
    def test_unknown_command_exits_2(self) -> None:
        with pytest.raises(SystemExit) as excinfo:
            main(["frobnicate"])
        assert excinfo.value.code == 2

    def test_build_without_part_or_stale(self, tmp_path: Path) -> None:
        assert main(["build"]) == 2

    def test_build_outside_project_exits_2(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        assert main(["build", "plate", "--unsafe-local-executor"]) == 2

    def test_bad_param_syntax_exits_2(self, project: Path) -> None:
        assert main(["build", "plate", "--param", "notakv"]) == 2

    def test_invalid_part_name_exits_2(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(project)
        assert main(["build", "not-an-identifier", "--unsafe-local-executor"]) == 2

    def test_unknown_part_exits_2_with_candidates(
        self,
        project: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.chdir(project)
        assert main(["build", "missing", "--unsafe-local-executor"]) == 2
        err = capsys.readouterr().err
        assert "missing" in err
        assert "plate" in err  # candidate listing (§7-style, never a guess)

    def test_script_path_outside_parts_dir_exits_2(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stray = project / "stray.py"
        stray.write_text(CLEAN_PART, encoding="utf-8")
        monkeypatch.chdir(project)
        assert main(["build", "stray.py", "--unsafe-local-executor"]) == 2

    def test_missing_script_path_exits_2(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(project)
        assert main(["build", "parts/absent.py", "--unsafe-local-executor"]) == 2

    def test_check_outside_project_exits_2(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        assert main(["check"]) == 2


class TestLintCommand:
    def test_clean_part_exits_0(self, project: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["lint", str(project / "parts" / "plate.py")]) == 0
        assert "clean" in capsys.readouterr().out

    def test_shadowed_param_is_error_exit_1(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        shadow = project / "parts" / "shadow.py"
        shadow.write_text(
            'PARAMS = {"sheet_t": Param(6.0, min=3, max=12)}\n'
            "part.geometry = Box(10, 10, p.sheet_t)\n"
            'part.description = "d"\n'
            'part.process = "cnc_router"\n',
            encoding="utf-8",
        )
        assert main(["lint", str(shadow), "--json"]) == 1
        findings_raw = cast("list[JSONValue]", json.loads(capsys.readouterr().out))
        assert isinstance(findings_raw, list)
        findings = [cast("dict[str, JSONValue]", entry) for entry in findings_raw]
        shadowed = [f for f in findings if f["code"] == "shadowed-param"]
        assert len(shadowed) == 1
        assert shadowed[0]["severity"] == "error"
        assert shadowed[0]["name"] == "sheet_t"

    def test_warnings_only_exit_0(self, project: Path, capsys: pytest.CaptureFixture[str]) -> None:
        warned = project / "parts" / "warned.py"
        warned.write_text(
            "part.geometry = Box(10, 10, 2)\n",  # missing description/process
            encoding="utf-8",
        )
        assert main(["lint", str(warned)]) == 0
        out = capsys.readouterr().out
        assert "missing-metadata" in out

    def test_syntax_error_exit_1(self, project: Path) -> None:
        broken = project / "parts" / "broken.py"
        broken.write_text("def (:\n", encoding="utf-8")
        assert main(["lint", str(broken)]) == 1

    def test_standalone_script_lints_without_project(self, tmp_path: Path) -> None:
        script = tmp_path / "standalone.py"
        script.write_text(CLEAN_PART, encoding="utf-8")
        assert main(["lint", str(script)]) == 0

    def test_missing_file_exits_2(self, tmp_path: Path) -> None:
        assert main(["lint", str(tmp_path / "absent.py")]) == 2
