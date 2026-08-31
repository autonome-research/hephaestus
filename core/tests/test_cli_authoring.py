"""Agent-shaped ``heph part`` / ``script`` / ``params`` / ``prompt`` verbs.

Create and write go through ``ProjectStore.write_part`` — the same
``create_part`` / ``write_part`` contract the tool dispatcher uses. These tests
stay in-process and spawn no geometry worker.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from typing import Any, cast

import pytest
from hephaestus.core.cli import main
from hephaestus.core.part_templates import PART_TEMPLATES
from hephaestus.core.project_store.layout import load_project, open_store
from hephaestus.core.project_store.listing import list_parts_projection
from hephaestus.core.project_store.store import ProjectStore
from opstore.types import JSONValue

SPACER = (
    'PARAMS = {"width": Param(10.0, min=5, max=20)}\n'
    "plate = Box(p.width, 10, 2)\n"
    "part.geometry = plate\n"
    'part.description = "spacer"\n'
    'part.process = "cnc_router"\n'
)

SPACER_V2 = (
    'PARAMS = {"width": Param(12.0, min=5, max=20)}\n'
    "plate = Box(p.width, 10, 2)\n"
    "part.geometry = plate\n"
    'part.description = "spacer v2"\n'
    'part.process = "cnc_router"\n'
)


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "parts").mkdir(parents=True)
    (root / "hephaestus.toml").write_text(
        '[project]\nname = "proj"\n\n[params]\nsheet_t = 6.0\n',
        encoding="utf-8",
    )
    (root / "globals.py").write_text(
        'PARAMS = {"sheet_t": Param(6.0, min=3, max=12)}\n', encoding="utf-8"
    )
    (root / "parts" / "plate.py").write_text(SPACER, encoding="utf-8")
    return root


def run(root: Path, monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    monkeypatch.chdir(root)
    return main(list(argv))


def load_json(capsys: pytest.CaptureFixture[str]) -> dict[str, JSONValue]:
    parsed: object = json.loads(capsys.readouterr().out)
    assert isinstance(parsed, dict)
    return cast("dict[str, JSONValue]", parsed)


class TestPartList:
    def test_json_matches_the_shared_projection(
        self, project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert run(project, monkeypatch, "part", "list", "--json") == 0
        reported = load_json(capsys)
        layout = load_project(project)
        store = open_store(layout)
        try:
            expected = list_parts_projection(project, ProjectStore(layout, store))
        finally:
            store.close()
        assert reported == expected
        parts = cast("list[dict[str, Any]]", reported["parts"])
        assert [entry["name"] for entry in parts] == ["plate"]
        assert parts[0]["path"] == "parts/plate.py"
        assert str(parts[0]["content_hash"]).startswith("sha256:")


class TestPartCreate:
    def test_template_writes_the_same_bytes_as_create_part(
        self, project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert run(project, monkeypatch, "part", "create", "blanked", "--json") == 0
        created = load_json(capsys)
        assert created["status"] == "ok"
        assert created["path"] == "parts/blanked.py"
        assert created["initial_script"] == PART_TEMPLATES["blank"]
        assert (project / "parts" / "blanked.py").read_text(encoding="utf-8") == PART_TEMPLATES[
            "blank"
        ]
        assert created["replayed"] is False

    def test_create_from_file(
        self, project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        source = project.parent / "spacer.py"
        source.write_text(SPACER, encoding="utf-8")
        assert (
            run(project, monkeypatch, "part", "create", "spacer", "--file", str(source), "--json")
            == 0
        )
        created = load_json(capsys)
        assert created["status"] == "ok"
        assert created["path"] == "parts/spacer.py"
        assert created["initial_script"] == SPACER
        assert (project / "parts" / "spacer.py").read_text(encoding="utf-8") == SPACER

    def test_create_from_stdin(
        self, project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(sys, "stdin", io.StringIO(SPACER))
        rc = run(project, monkeypatch, "part", "create", "from_stdin", "--file", "-", "--json")
        assert rc == 0
        created = load_json(capsys)
        assert created["initial_script"] == SPACER
        assert (project / "parts" / "from_stdin.py").read_text(encoding="utf-8") == SPACER

    def test_already_exists_is_refused_without_mutation(
        self, project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        before = (project / "parts" / "plate.py").read_text(encoding="utf-8")
        assert run(project, monkeypatch, "part", "create", "plate", "--json") == 1
        created = load_json(capsys)
        assert created == {"part": "plate", "status": "already_exists"}
        assert (project / "parts" / "plate.py").read_text(encoding="utf-8") == before

    def test_invalid_name_exits_2(self, project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        assert run(project, monkeypatch, "part", "create", "not-an-id") == 2


class TestScriptWrite:
    def test_write_replaces_when_hash_matches(
        self, project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert run(project, monkeypatch, "script", "show", "plate", "--json") == 0
        shown = load_json(capsys)
        hash_ = str(shown["content_hash"])
        incoming = project.parent / "v2.py"
        incoming.write_text(SPACER_V2, encoding="utf-8")
        assert (
            run(
                project,
                monkeypatch,
                "script",
                "write",
                "plate",
                "--file",
                str(incoming),
                "--expected-hash",
                hash_,
                "--json",
            )
            == 0
        )
        written = load_json(capsys)
        assert written["applied"] is True
        assert written["path"] == "parts/plate.py"
        assert (project / "parts" / "plate.py").read_text(encoding="utf-8") == SPACER_V2
        assert written["content_hash"] != hash_

    def test_write_from_stdin(
        self, project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert run(project, monkeypatch, "script", "show", "plate", "--json") == 0
        hash_ = str(load_json(capsys)["content_hash"])
        monkeypatch.setattr(sys, "stdin", io.StringIO(SPACER_V2))
        assert (
            run(
                project,
                monkeypatch,
                "script",
                "write",
                "plate",
                "--file",
                "-",
                "--expected-hash",
                hash_,
                "--json",
            )
            == 0
        )
        assert load_json(capsys)["applied"] is True
        assert (project / "parts" / "plate.py").read_text(encoding="utf-8") == SPACER_V2

    def test_stale_hash_is_a_discriminated_conflict(
        self, project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        incoming = project.parent / "v2.py"
        incoming.write_text(SPACER_V2, encoding="utf-8")
        before = (project / "parts" / "plate.py").read_text(encoding="utf-8")
        assert (
            run(
                project,
                monkeypatch,
                "script",
                "write",
                "plate",
                "--file",
                str(incoming),
                "--expected-hash",
                "sha256:" + "ab" * 32,
                "--json",
            )
            == 1
        )
        result = load_json(capsys)
        assert result["applied"] is False
        conflict = cast("dict[str, JSONValue]", result["conflict"])
        assert conflict["current_script"] == before
        assert str(conflict["current_hash"]).startswith("sha256:")
        assert (project / "parts" / "plate.py").read_text(encoding="utf-8") == before

    def test_missing_expected_hash_is_usage(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        incoming = project.parent / "v2.py"
        incoming.write_text(SPACER_V2, encoding="utf-8")
        assert run(project, monkeypatch, "script", "write", "plate", "--file", str(incoming)) == 2

    def test_write_missing_part_exits_2(
        self,
        project: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        incoming = project.parent / "v2.py"
        incoming.write_text(SPACER_V2, encoding="utf-8")
        assert (
            run(
                project,
                monkeypatch,
                "script",
                "write",
                "absent",
                "--file",
                str(incoming),
                "--expected-hash",
                "sha256:" + "ab" * 32,
            )
            == 2
        )
        err = capsys.readouterr().err
        assert "absent" in err
        assert "plate" in err


class TestPartShowAndParams:
    def test_show_unbuilt_is_a_named_absence(
        self, project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert run(project, monkeypatch, "part", "show", "plate", "--json") == 0
        shown = load_json(capsys)
        assert shown == {"current": False, "part": "plate", "status": "not_built"}

    def test_params_json_from_script_literals(
        self, project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert run(project, monkeypatch, "params", "plate", "--json") == 0
        body = load_json(capsys)
        assert body["status"] == "ok"
        assert body["part"] == "plate"
        rows = cast("list[dict[str, JSONValue]]", body["params"])
        assert rows[0]["name"] == "width"
        assert rows[0]["default"] == 10.0
        assert rows[0]["min"] == 5
        assert rows[0]["max"] == 20
        assert rows[0]["scope"] == "part"


class TestPrompt:
    def test_set_and_show_roundtrip(
        self, project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        request = project.parent / "request.txt"
        request.write_text("40 mm spacer, 6 mm plate\n", encoding="utf-8")
        assert run(project, monkeypatch, "prompt", "set", "--file", str(request), "--json") == 0
        stored = load_json(capsys)
        assert stored["status"] == "ok"
        assert stored["text"] == "40 mm spacer, 6 mm plate\n"
        assert stored["path"] == ".heph/request.txt"
        assert (project / ".heph" / "request.txt").read_text(encoding="utf-8") == stored["text"]

        assert run(project, monkeypatch, "prompt", "--json") == 0
        shown = load_json(capsys)
        assert shown["text"] == stored["text"]
        assert shown["status"] == "ok"

    def test_empty_show_is_named(
        self, project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert run(project, monkeypatch, "prompt", "show", "--json") == 0
        shown = load_json(capsys)
        assert shown["status"] == "empty"
        assert shown["text"] == ""
