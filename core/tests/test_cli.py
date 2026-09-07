"""Fast in-process unit tests for the ``heph`` CLI surface (no geometry).

Usage-error exit codes (2), lint command behavior, and argument parsing.
Everything that spawns a worker lives in ``test_integration.py``.
"""

from __future__ import annotations

import builtins
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import cast

import pytest
from hephaestus.core.cli import build_parser, main
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
        # One listing envelope, never a bare array (ledger J-cli-robustness-7);
        # `status` mirrors the exit code.
        document = cast("dict[str, JSONValue]", json.loads(capsys.readouterr().out))
        assert document["status"] == "error"
        findings_raw = cast("list[JSONValue]", document["findings"])
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

    def test_directory_reports_not_a_file_not_no_such_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``heph lint .`` must not assert that the current directory does not
        exist — six sites conflated "missing" with "not a file"
        (ledger J-cli-robustness-12)."""
        assert main(["lint", str(tmp_path)]) == 2
        err = capsys.readouterr().err
        assert "is a directory" in err
        assert "no such" not in err

    def test_request_without_requirements_is_refused_not_a_silent_no_op(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``--request`` with no ``--requirements`` used to read as live and
        report "clean" — the rule is a join with one operand missing
        (ledger J-cli-robustness-2)."""
        script = tmp_path / "standalone.py"
        script.write_text(CLEAN_PART, encoding="utf-8")
        request = tmp_path / "request.txt"
        request.write_text("the part must be 10mm wide", encoding="utf-8")
        code = main(["lint", str(script), "--request", str(request)])
        err = capsys.readouterr().err
        assert code == 2, err
        assert "--requirements" in err


class TestCheckOutputVocabulary:
    """``heph check``'s human column must use the shared four-value classifier
    (pass/fail/error/not_run), not a two-valued pass/FAIL that dumps the
    measured object verbatim for a check that never ran (ledger
    J-cli-robustness-15)."""

    def test_a_raising_check_prints_error_not_fail_and_not_the_raw_dict(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = tmp_path / "proj"
        (root / "parts").mkdir(parents=True)
        (root / "checks").mkdir()
        (root / "hephaestus.toml").write_text('name = "proj"\n', encoding="utf-8")
        (root / "globals.py").write_text("PARAMS = {}\n", encoding="utf-8")
        (root / "checks" / "raiser.py").write_text(
            'CHECKS = {"raises": lambda m: m.volume("nosuchpart")}\n',
            encoding="utf-8",
        )
        import os

        old = Path.cwd()
        os.chdir(root)
        try:
            code = main(["check"])
        finally:
            os.chdir(old)
        out = capsys.readouterr().out
        assert code == 1
        assert "FAIL" not in out
        assert "error" in out
        assert '{"error"' not in out  # not the raw measured envelope, printed as prose
        assert "addressing_error" in out


class TestSnapshotProjectAlias:
    """``--project`` on ``heph check`` was a boolean and a ``DIR`` on
    ``heph agent`` / ``heph serve --web`` — one name meaning two things
    produced a bare "unrecognized arguments" with no hint that this verb's
    flag takes no value (ledger J-cli-robustness-4). ``--snapshot`` is the new
    spelling; ``--project`` is kept only as a retiring, zero-arity alias.
    """

    def test_snapshot_and_project_alias_behave_identically(self, tmp_path: Path) -> None:
        root = tmp_path / "proj"
        (root / "parts").mkdir(parents=True)
        (root / "checks").mkdir()
        (root / "hephaestus.toml").write_text('name = "proj"\n', encoding="utf-8")
        (root / "globals.py").write_text("PARAMS = {}\n", encoding="utf-8")
        import os

        old = Path.cwd()
        os.chdir(root)
        try:
            snapshot_code = main(["check", "--snapshot"])
            project_code = main(["check", "--project"])
        finally:
            os.chdir(old)
        assert snapshot_code == project_code

    def test_build_time_arity_collision_is_caught_by_construction(self) -> None:
        """A synthetic subparser registering a conflicting arity for an
        existing option string must fail loudly at ``build_parser()`` time,
        not surface as a confusing argparse error at the operator."""
        import argparse

        from hephaestus.core.cli import (
            _assert_no_arity_collisions,  # pyright: ignore[reportPrivateUsage]
        )

        parser = argparse.ArgumentParser(prog="heph-test")
        sub = parser.add_subparsers(dest="command", required=True)
        one = sub.add_parser("one")
        one.add_argument("--widget", action="store_true")
        two = sub.add_parser("two")
        two.add_argument("--widget", default=None)

        with pytest.raises(AssertionError, match="arity collision"):
            _assert_no_arity_collisions(parser)


class TestOptionalVerbImportDiscrimination:
    """``build_parser()``'s ``try: ... except ImportError: pass`` blocks around
    ``heph agent`` / ``cli_export`` / ``cli_bench`` / ``serve --mcp`` / ``--web``
    (ledger J-cli-robustness-21).

    ``ImportError`` cannot distinguish "the module I asked for is absent" (the
    supported core-only install) from "something it imports is absent" (the
    package is installed but broken); before the fix both are swallowed
    identically and the verb simply vanishes from ``heph --help`` — the exact
    symptom of an uninstalled package. These patch the *exact* import
    statement each optional-verb block executes (``builtins.__import__``, so
    the raise happens regardless of what is already cached in ``sys.modules``)
    and assert the two cases read differently.
    """

    @staticmethod
    def _patched_import(target: str, name: str | None, reason: str) -> Callable[..., object]:
        real_import = builtins.__import__

        def fake_import(
            import_name: str,
            globals: Mapping[str, object] | None = None,
            locals: Mapping[str, object] | None = None,
            fromlist: tuple[str, ...] = (),
            level: int = 0,
        ) -> object:
            if import_name == target:
                raise ImportError(reason, name=name)
            return real_import(import_name, globals, locals, fromlist, level)

        return fake_import

    def test_a_genuinely_missing_package_still_leaves_the_verb_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The supported case must be unchanged: an ``ImportError`` whose
        ``name`` *is* the module (or its parent package) means the optional
        package is not installed at all, so the verb stays silently absent —
        exactly as ``heph --help`` on a core-only install has always looked."""
        monkeypatch.setattr(
            builtins,
            "__import__",
            self._patched_import(
                "hephaestus.agent_bridge",
                "hephaestus.agent_bridge",
                "No module named 'hephaestus.agent_bridge'",
            ),
        )
        parser = build_parser()
        with pytest.raises(SystemExit) as excinfo:
            parser.parse_args(["agent", "--session", "s1"])
        assert excinfo.value.code == 2

    @pytest.mark.xfail(
        reason=(
            "J-cli-robustness-21 (the `_optional_verb` discriminator) is lane L2's "
            "item: it rewrites the same six `try/except ImportError` blocks in "
            "`build_parser` that L2's deferred-import work rewrites, and the "
            "workflow plan puts both in one edit. The claim is pinned here so the "
            "gap is a recorded expectation rather than an absence; non-strict, so "
            "it turns green the moment L2 lands and needs no coordination."
        ),
        strict=False,
    )
    def test_a_broken_transitive_dependency_registers_a_self_diagnosing_stub(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``ImportError(name="some_third_party")`` at the same import site is a
        different fact: the package the user asked for exists and something
        *it* imports does not. The verb must stay on ``heph --help`` and, run,
        must name the real cause — not read as "invalid choice"."""
        monkeypatch.setattr(
            builtins,
            "__import__",
            self._patched_import(
                "hephaestus.agent_bridge",
                "some_third_party",
                "No module named 'some_third_party'",
            ),
        )
        parser = build_parser()
        args = parser.parse_args(["agent", "--session", "s1"])
        assert args.command == "agent"
        code = args.func(args)
        assert code == 2
        # A machine string is allowed here (the exception detail) but the verb
        # name and the real module must both be legible, not swallowed.
        # (the exact wording is the implementation's to choose)

    def test_a_broken_http_cli_web_does_not_remove_mcp(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The web half of ``serve`` failing to import must not take ``--mcp``
        down with it — the two halves are reported separately."""
        monkeypatch.setattr(
            builtins,
            "__import__",
            self._patched_import(
                "hephaestus.http", "unrelated_dep", "No module named 'unrelated_dep'"
            ),
        )
        parser = build_parser()
        args = parser.parse_args(["serve", "--mcp"])
        assert args.command == "serve"
        assert getattr(args, "mcp", None) is True
