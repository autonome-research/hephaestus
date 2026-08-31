"""``heph init``: scaffold, build the stub part end to end, refuse non-empty.

The scaffolding verb writes the four-file design-project convention
(``repo_conventions.md``: ``hephaestus.toml``, ``globals.py``, ``parts/``,
``.gitignore`` ignoring ``.heph/``) plus ``checks/`` seeded with the safe
cross-part template shared with ``create_project_check``. The contract under
test: what ``heph init`` writes is a REAL project — the example part builds
through the real CLI with nothing edited — and the verb never overwrites (a
non-empty target, including an already-initialized one, is refused with the
named ``init_target_not_empty`` error and exit code 1).
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from hephaestus.core.checks.template import CHECK_TEMPLATE_HEADER, check_template
from hephaestus.core.cli import main
from hephaestus.core.cli_init import InitTargetNotEmptyError, scaffold


class TestScaffold:
    def test_init_writes_the_documented_convention(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        target = tmp_path / "gadget"
        assert main(["init", str(target)]) == 0
        out = capsys.readouterr().out
        assert "gadget" in out

        manifest = tomllib.loads((target / "hephaestus.toml").read_text(encoding="utf-8"))
        assert manifest["project"]["name"] == "gadget"
        # globals.py is empty apart from its one-line comment.
        globals_lines = (target / "globals.py").read_text(encoding="utf-8").strip().splitlines()
        assert len(globals_lines) == 1 and globals_lines[0].startswith("#")
        assert (target / "parts" / "example.py").is_file()
        assert ".heph/" in (target / ".gitignore").read_text(encoding="utf-8")
        # checks/ carries the SAME safe template create_project_check installs.
        check_src = (target / "checks" / "project.py").read_text(encoding="utf-8")
        assert check_src == check_template("scaffolded by heph init")
        assert CHECK_TEMPLATE_HEADER.splitlines()[-2] in check_src  # the placeholder entry

    def test_scaffolded_example_part_builds_and_checks_via_the_real_cli(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """End to end: `heph init` -> `heph build example` -> `heph check`, green.

        The whole first-run path a new operator takes, with nothing edited: the
        scaffolded project builds its example part AND the scaffolded ``checks/``
        template runs green through the real check verb — a template that only
        parsed but did not *run* would be a broken first project.
        """
        target = tmp_path / "widgets"
        assert main(["init", str(target)]) == 0
        example = (target / "parts" / "example.py").read_text(encoding="utf-8")
        assert 'part.process = "cnc_router"' in example
        monkeypatch.chdir(target)
        assert main(["build", "example", "--unsafe-local-executor"]) == 0
        assert (target / ".heph").is_dir()  # the ignored build store appeared
        assert main(["check"]) == 0

    def test_init_defaults_to_the_current_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        empty = tmp_path / "fresh"
        empty.mkdir()
        monkeypatch.chdir(empty)
        assert main(["init"]) == 0
        manifest = tomllib.loads((empty / "hephaestus.toml").read_text(encoding="utf-8"))
        assert manifest["project"]["name"] == "fresh"


class TestRefusals:
    def test_non_empty_target_is_refused_by_name(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        target = tmp_path / "occupied"
        target.mkdir()
        (target / "notes.txt").write_text("already here\n", encoding="utf-8")
        assert main(["init", str(target)]) == 1
        err = capsys.readouterr().err
        assert "init_target_not_empty" in err
        assert "notes.txt" in err
        # Nothing was written into the refused target.
        assert not (target / "hephaestus.toml").exists()

    def test_second_init_of_the_same_directory_is_refused(self, tmp_path: Path) -> None:
        """Idempotency refusal: init never overwrites an initialized project."""
        target = tmp_path / "once"
        assert main(["init", str(target)]) == 0
        assert main(["init", str(target)]) == 1

    def test_scaffold_names_the_error_and_the_entries(self, tmp_path: Path) -> None:
        target = tmp_path / "busy"
        target.mkdir()
        (target / "a.txt").write_text("x", encoding="utf-8")
        with pytest.raises(InitTargetNotEmptyError) as excinfo:
            scaffold(target)
        assert excinfo.value.code == "init_target_not_empty"
        assert excinfo.value.entries == ("a.txt",)

    def test_a_file_target_is_refused(self, tmp_path: Path) -> None:
        target = tmp_path / "afile"
        target.write_text("not a directory\n", encoding="utf-8")
        assert main(["init", str(target)]) == 1
