"""Layout tests: manifest parsing, root discovery, ``.heph/`` store init."""

from __future__ import annotations

from pathlib import Path

import pytest
from hephaestus.core.errors import ValidationError
from hephaestus.core.project_store.layout import (
    ProjectLayout,
    ProjectManifest,
    find_project_root,
    load_project,
    open_store,
    parse_manifest,
)
from test_project_store_helpers import make_project


class TestParseManifest:
    def test_full_manifest(self) -> None:
        manifest = parse_manifest(
            'name = "cat-steps"\nunits = "mm"\n\n[params]\nsheet_t = 18\nclearance = 0.2\n'
        )
        assert manifest == ProjectManifest(
            name="cat-steps", units="mm", params={"sheet_t": 18, "clearance": 0.2}
        )
        assert isinstance(manifest.params["sheet_t"], int)
        assert isinstance(manifest.params["clearance"], float)

    def test_units_default_mm(self) -> None:
        assert parse_manifest('name = "p"').units == "mm"

    def test_params_default_empty(self) -> None:
        assert parse_manifest('name = "p"').params == {}

    @pytest.mark.parametrize(
        "text",
        [
            "",  # no name
            'name = ""',  # empty name
            "name = 3",  # non-string name
            'name = "p"\nunits = 7',  # non-string units
            'name = "p"\nparams = 3',  # params not a table
            'name = "p"\n[params]\nt = true',  # bool is not a number
            'name = "p"\n[params]\nt = "big"',  # string is not a number
            "name = [unclosed",  # invalid TOML
        ],
    )
    def test_malformed_manifest_is_contract_error(self, text: str) -> None:
        with pytest.raises(ValidationError) as exc_info:
            parse_manifest(text)
        assert exc_info.value.kind == "contract"
        assert exc_info.value.code == "validation_error"


class TestLayout:
    def test_paths(self, tmp_path: Path) -> None:
        layout = make_project(tmp_path)
        assert layout.manifest_path == tmp_path / "hephaestus.toml"
        assert layout.globals_path == tmp_path / "globals.py"
        assert layout.parts_dir == tmp_path / "parts"
        assert layout.checks_dir == tmp_path / "checks"
        assert layout.store_root == tmp_path / ".heph"
        assert layout.journal_dir == tmp_path / ".heph" / "journal"
        assert layout.exports_dir == tmp_path / ".heph" / "exports"
        assert layout.part_path("widget") == tmp_path / "parts" / "widget.py"

    @pytest.mark.parametrize("bad", ["../escape", "a/b", "", "with space", "a.b"])
    def test_part_path_rejects_non_identifiers(self, tmp_path: Path, bad: str) -> None:
        layout = make_project(tmp_path)
        with pytest.raises(ValidationError) as exc_info:
            layout.part_path(bad)
        assert exc_info.value.kind == "contract"

    def test_part_names_sorted(self, tmp_path: Path) -> None:
        layout = make_project(tmp_path, parts={"zeta": "z = 1\n", "alpha": "a = 1\n"})
        assert layout.part_names() == ("alpha", "zeta")

    def test_part_names_empty_without_parts_dir(self, tmp_path: Path) -> None:
        layout = ProjectLayout(root=tmp_path, manifest=ProjectManifest(name="p"))
        assert layout.part_names() == ()


class TestDiscovery:
    def test_find_project_root_walks_up(self, tmp_path: Path) -> None:
        make_project(tmp_path)
        nested = tmp_path / "parts" / "deeper"
        nested.mkdir(parents=True)
        assert find_project_root(nested) == tmp_path.resolve()
        assert find_project_root(tmp_path) == tmp_path.resolve()

    def test_find_project_root_missing(self, tmp_path: Path) -> None:
        with pytest.raises(ValidationError) as exc_info:
            find_project_root(tmp_path)
        assert exc_info.value.kind == "contract"

    def test_load_project_reads_manifest(self, tmp_path: Path) -> None:
        make_project(tmp_path, name="shelving", manifest_extra="[params]\nt = 6\n")
        layout = load_project(tmp_path)
        assert layout.manifest.name == "shelving"
        assert layout.manifest.params == {"t": 6}

    def test_load_project_missing_manifest(self, tmp_path: Path) -> None:
        with pytest.raises(ValidationError):
            load_project(tmp_path)


class TestOpenStore:
    def test_create_then_reopen(self, tmp_path: Path) -> None:
        layout = make_project(tmp_path)
        store = open_store(layout)
        digest = store.blobs.put(b"hello")
        store.close()
        assert layout.journal_dir.is_dir()
        assert (layout.store_root / "state.db").is_file()

        reopened = open_store(layout)  # second open must not re-create
        assert reopened.blobs.get(digest) == b"hello"
        reopened.close()
