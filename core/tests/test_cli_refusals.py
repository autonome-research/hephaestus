# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""The shared CLI refusal boundary, exercised across the whole verb surface.

``docs/cli.md``'s exit-code contract is three-valued (0/1/2) and "not a
Hephaestus project" is exit 2's canonical example. Before ``cli_errors`` this
one condition reached the operator as exit 1 with an
``error (validation_error):`` prefix on some verbs and exit 2 with a bare
``heph:`` prefix on others (ledger J-cli-robustness-5), ``--json`` was ignored
on every refusal (J-cli-robustness-6), and a module ``main()`` mapped nothing
at all (J-cli-robustness-20). These tests drive the *real* ``heph`` entry point
(:func:`hephaestus.core.cli.main`) over a representative verb from each verb
group, so the parity is asserted where an operator actually meets it.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, cast

import pytest
from hephaestus.core.cli import build_parser, main

# One minimal, syntactically valid invocation per verb group that reaches
# project resolution before anything else — no part needs to exist, no file
# needs to be on disk, so the only thing under test is "not a project".
# ``--json`` is appended by ``test_json_refusals_are_one_envelope_on_stderr``
# for every entry here (every one of these verb groups registers the flag).
#
# The *set* of verbs this covers is asserted against ``build_parser()`` by
# ``test_no_project_table_covers_every_verb_build_parser_registers`` below
# (ledger J-cli-robustness-5 / -6 ask for the coverage to be derived so a new
# verb group cannot silently escape the taxonomy); the invocation *shape* for
# each verb stays this explicit table on purpose — argparse arity and each
# verb's own pre-project usage checks (``solve pose``'s compulsory provenance
# and target, for one) are not something a generic walk can synthesize.
NO_PROJECT_INVOCATIONS: list[tuple[str, ...]] = [
    ("build", "widget"),
    ("check",),
    ("part", "list"),
    ("script", "show", "widget"),
    ("params",),
    ("prompt",),
    ("render", "widget"),
    ("diff", "widget", "part:other"),
    ("scan", "imports/scan.stl", "--units", "mm"),
    ("proposals",),
    ("import", "list"),
    ("reference", "list"),
    ("export", "list"),
    ("assembly",),
    ("joints",),
    ("motion",),
    ("registry", "list"),
    ("cam", "emit", "widget"),
    # `solve pose`'s own usage checks (a declared target, a declared
    # provenance) run before `project_root_or_refuse` on purpose
    # (J-cli-robustness-17), so a minimal invocation must clear those first or
    # it exercises a different refusal than the one this table is about.
    (
        "solve",
        "pose",
        "--tol",
        "0.1",
        "--weighting",
        "unit_scaled_v1",
        "--regularization",
        "min_norm_from_start",
        "--point",
        "anchor,0,0,0,0.1",
        "--assumed",
        "--reason",
        "test",
    ),
]

#: Verb groups ``build_parser()`` registers that never resolve a project at
#: all, so they have no "not a project" case for this table to carry — each
#: reason is load-bearing, not a shrug:
#:
#: - ``init`` scaffolds a project; there is nothing yet to refuse.
#: - ``lint`` catches the project-resolution ``ValidationError`` itself and
#:   falls back to linting the script standalone (``cli.py::_cmd_lint``) — a
#:   part script outside any project is a supported mode, not a refusal.
#: - ``goldens``' bare (verify) mode reads the repo's own golden corpus, never
#:   the current directory's project — `heph goldens` outside a project
#:   reports drift/clean, not "not a project" (`cli_render.py::_cmd_goldens`).
#: - ``bench`` is a benchmark harness verb with no project concept at all (no
#:   call to `project_root_or_refuse` anywhere in `cli_bench.py`).
#: - ``serve``'s bare form (neither ``--mcp`` nor ``--web``) refuses with its
#:   own "--mcp is required" usage message before any project is resolved;
#:   only `serve --web` resolves one.
#: - ``agent`` DOES resolve a project first thing (`_cmd_agent`) and belongs in
#:   the taxonomy, but registers no ``--json`` flag at all — unlike every row
#:   in the table above, so it cannot share
#:   ``test_json_refusals_are_one_envelope_on_stderr_stdout_stays_empty``'s
#:   blanket ``[*argv, "--json"]``. Its "not a project" refusal (this exact
#:   message, this exact exit code) and its parity with `serve --web`
#:   (J-cli-robustness-22) are covered directly in
#:   ``server/tests/test_cli_agent.py`` and ``test_http_serve.py`` instead.
PROJECT_EXEMPT_VERBS: frozenset[str] = frozenset(
    {"init", "lint", "goldens", "bench", "serve", "agent"}
)


def _top_level_verbs(parser: argparse.ArgumentParser) -> set[str]:
    """Every verb name ``sub.add_parser(...)`` registered, read off the built parser.

    Mirrors ``cli.py::_walk_parsers``' use of the private ``_SubParsersAction``
    API (there is no public walk over a built parser tree) but only one level
    deep — this table is about the top-level verb *groups*, not their nested
    subcommands.
    """
    verbs: set[str] = set()
    for action in parser._actions:  # pyright: ignore[reportPrivateUsage]
        if isinstance(action, argparse._SubParsersAction):  # pyright: ignore[reportPrivateUsage]
            children = cast(
                "dict[str, argparse.ArgumentParser]",
                action.choices,  # pyright: ignore[reportUnknownMemberType]
            )
            verbs.update(children.keys())
    return verbs


def _ident(argv: tuple[str, ...]) -> str:
    return " ".join(argv)


def test_no_project_table_covers_every_verb_build_parser_registers() -> None:
    """A verb group ``build_parser()`` grows must land in this table or the exemptions.

    ``NO_PROJECT_INVOCATIONS`` was a closed list of 18 hand-picked verbs; the
    ledger asks for the *coverage* to be derived from ``build_parser()`` so it
    self-maintains (J-cli-robustness-5/-6) rather than silently stop covering
    a verb nobody remembered to add — the failure mode RC-10 names. This does
    not synthesize invocations (each verb's own arity and pre-project usage
    checks are too particular for that, which is why the table above stays
    explicit); it only asserts every registered verb is *accounted for*, one
    way or the other, so a new verb group forces a conscious entry in one of
    the two sets rather than escaping both.
    """
    registered = _top_level_verbs(build_parser())
    tested = {argv[0] for argv in NO_PROJECT_INVOCATIONS}
    accounted_for = tested | PROJECT_EXEMPT_VERBS
    missing = registered - accounted_for
    assert not missing, (
        f"verb group(s) {sorted(missing)} are registered by build_parser() but neither "
        "tested in NO_PROJECT_INVOCATIONS nor exempted in PROJECT_EXEMPT_VERBS above — "
        "add a minimal invocation to the table, or an exemption with a load-bearing reason"
    )
    # And the reverse: an exemption or a table row naming a verb build_parser()
    # no longer registers is a stale entry, not a passing test.
    stale = accounted_for - registered
    plural = "y" if len(stale) == 1 else "ies"
    assert not stale, f"stale entr{plural} for {sorted(stale)}: no such verb in build_parser()"


@pytest.fixture()
def outside_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A directory that is not, and is not inside, a Hephaestus project."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.mark.parametrize("argv", NO_PROJECT_INVOCATIONS, ids=_ident)
def test_every_verb_refuses_no_project_as_exit_2_with_the_bare_shape(
    argv: tuple[str, ...],
    outside_project: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """One condition, one exit code, one message shape — across the whole surface.

    ``docs/cli.md`` and ``hephaestus.core.cli``'s own module docstring fix exit
    2 for "no project"; before J-cli-robustness-5 four call sites re-raised it
    through a local ``_UsageError`` (exit 2) while everything else let the bare
    ``ValidationError`` reach ``main()`` (exit 1, ``error (validation_error):``
    prefix). Every verb here must land on exit 2 with the bare ``heph: ``
    prefix and nothing on stdout.
    """
    code = main(list(argv))
    out, err = capsys.readouterr()
    assert code == 2, f"{argv}: expected exit 2, got {code} (stdout={out!r} stderr={err!r})"
    assert out == "", f"{argv}: stdout must stay empty on a refusal, got {out!r}"
    assert err.startswith("heph: "), f"{argv}: {err!r}"
    assert "error (validation_error):" not in err, (
        f"{argv}: the exit-1 message shape leaked through: {err!r}"
    )
    assert "no hephaestus.toml found at or above" in err, f"{argv}: {err!r}"


@pytest.mark.parametrize("argv", NO_PROJECT_INVOCATIONS, ids=_ident)
def test_json_refusals_are_one_envelope_on_stderr_stdout_stays_empty(
    argv: tuple[str, ...],
    outside_project: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--json`` must not be silently ignored on a refusal (J-cli-robustness-6).

    A caller piping stdout into a parser must see either the result document or
    nothing — never prose — so it can tell "refused" from "crashed" without
    scraping stderr. The refusal itself still goes to stderr (docs/cli.md: an
    exit-2 usage error has no result to report), but as one parseable JSON
    object rather than a prose line, carrying the same facts a human refusal
    carries: ``status``, ``code``, ``message``.
    """
    code = main([*argv, "--json"])
    out, err = capsys.readouterr()
    assert code == 2, f"{argv}: expected exit 2, got {code} (stdout={out!r} stderr={err!r})"
    assert out == "", f"{argv} --json: stdout must stay empty on a refusal, got {out!r}"
    payload = cast("dict[str, Any]", json.loads(err))
    assert payload["status"] == "refused", f"{argv} --json: {payload}"
    assert isinstance(payload["code"], str) and payload["code"], f"{argv} --json: {payload}"
    assert "hephaestus.toml" in payload["message"], f"{argv} --json: {payload}"


# --------------------------------------------------------------------------
# J-cli-robustness-20: a module ``main()`` maps the same taxonomy as ``heph``


def test_cli_render_module_entry_point_refuses_rather_than_tracebacks(
    outside_project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``python -m hephaestus.core.cli_render`` must answer like the real CLI.

    ``cli_render.main`` builds its own parser and calls ``args.func(args)``
    with no ``try/except`` of its own; the taxonomy must therefore already be
    baked into ``args.func`` (``cli_errors.guard``), not bolted onto this
    ``main`` — otherwise the module entry point observes a different program
    than ``heph`` (ledger J-cli-robustness-20).
    """
    from hephaestus.core import cli_render

    code = cli_render.main(["render", "widget"])
    err = capsys.readouterr().err
    assert code == 2, err
    assert "Traceback" not in err
    assert err.startswith("heph: "), err


def test_cli_registry_module_entry_point_refuses_rather_than_tracebacks(
    outside_project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Same claim as above, for ``python -m hephaestus.core.cli_registry``."""
    from hephaestus.core import cli_registry

    code = cli_registry.main(["registry", "list"])
    err = capsys.readouterr().err
    assert code == 2, err
    assert "Traceback" not in err
    assert err.startswith("heph: "), err


# --------------------------------------------------------------------------
# J-cli-robustness-10 — the diff-level half: an unknown part is exit 2 with
# candidates, not a downgraded exit-1 addressing error. The message-conflation
# half (render/inspect.py deciding "does not exist" vs "no current build") is
# covered in ``test_render_inspect_cli.py``; this is the exit-code half that
# lives on ``cli_diff``'s own dispatch wiring.


def test_diff_on_an_unknown_part_is_exit_2_with_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``heph diff`` must not downgrade an addressing refusal to exit 1.

    ``core/src/hephaestus/core/project_compare.py`` raises ``AddressingError``
    for a part that does not exist; ``docs/cli.md`` and
    ``core/src/hephaestus/core/cli.py``'s own taxonomy put every addressing
    refusal at exit 2 with its candidate list, exactly as
    ``heph part show nosuch`` already reports it. A local broad
    ``except HephaestusError`` on ``cli_diff`` would report exit 1 instead and
    drop the candidates (ledger J-cli-robustness-10 / RC-4).
    """
    root = tmp_path / "proj"
    (root / "parts").mkdir(parents=True)
    (root / "hephaestus.toml").write_text('name = "proj"\n', encoding="utf-8")
    (root / "globals.py").write_text("PARAMS = {}\n", encoding="utf-8")
    (root / "parts" / "bracket.py").write_text("part.geometry = Box(1, 1, 1)\n", encoding="utf-8")
    monkeypatch.chdir(root)
    build_code = main(["build", "bracket", "--unsafe-local-executor"])
    capsys.readouterr()
    assert build_code == 0, "bracket must build so the refusal is about the *other* side"

    code = main(["diff", "bracket", "part:nosuch"])
    err = capsys.readouterr().err
    assert code == 2, err
    assert "nosuch" in err
    assert "bracket" in err  # candidate listing, never a guess


@pytest.mark.xfail(
    reason=(
        "J-cli-robustness-10's message half lives in "
        "core/src/hephaestus/core/project_compare.py, which this lane does not own: "
        "part_operand() still tests build state without first asking whether the part "
        "exists. The exit-code half (above) is fixed here."
    ),
    strict=True,
)
def test_diff_on_an_unknown_part_says_it_does_not_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A part that does not exist must not be told it has no build.

    "has no current successful build" is true only of a part that *exists* and
    was never built; `assembly.py`'s vocabulary keeps the two apart because the
    fix differs, and ASSEMBLY.md forbids conflating them.
    `core/src/hephaestus/core/project_compare.py:288-296` asks about build state
    without first asking about existence — the same conflation
    `core/src/hephaestus/core/render/inspect.py` no longer has.
    """
    root = tmp_path / "proj"
    (root / "parts").mkdir(parents=True)
    (root / "hephaestus.toml").write_text('name = "proj"\n', encoding="utf-8")
    (root / "globals.py").write_text("PARAMS = {}\n", encoding="utf-8")
    (root / "parts" / "bracket.py").write_text("part.geometry = Box(1, 1, 1)\n", encoding="utf-8")
    monkeypatch.chdir(root)
    assert main(["build", "bracket", "--unsafe-local-executor"]) == 0
    capsys.readouterr()

    assert main(["diff", "bracket", "part:nosuch"]) == 2
    err = capsys.readouterr().err
    assert "does not exist" in err, err
    assert "has no current successful build" not in err, err


# -- J-cli-robustness-10, the reporting half: a candidate list is a set of
# -- ALTERNATIVES, so it never contains the name it is offered for ----------


def test_candidates_are_dropped_when_the_selector_is_one_of_them(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A refusal about a name that resolved has no alternatives to offer.

    Two engine sites still raise "has no current successful build" with the
    whole part list attached (``project_compare.py``, ``scan_compare.py`` — the
    message half of J-cli-robustness-10, which another lane owns), and a third
    could be written tomorrow. The invariant is a property of the vocabulary
    rather than of any one raise site — ``core/errors.py`` defines candidates
    as the near-misses "when nothing matched" — so the boundary enforces it for
    every verb at once.
    """
    from hephaestus.core.cli_errors import dispatch
    from hephaestus.core.errors import AddressingError

    def command(_args: argparse.Namespace) -> int:
        raise AddressingError(
            "part 'primary' has no current successful build to compare",
            selector="primary",
            candidates=("bracket", "example", "primary"),
        )

    code = dispatch(command, argparse.Namespace(json=False))
    err = capsys.readouterr().err
    assert code == 2, err
    assert "candidates" not in err, err


def test_an_ambiguous_selector_keeps_the_things_it_matched(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The guard on the guard. ``reason="ambiguous"`` means the candidates are
    the several things the selector really did match, and it may legitimately
    be one of them — dropping those would delete the only actionable half of
    the refusal (``core/DESIGN.md`` §7)."""
    from hephaestus.core.cli_errors import dispatch
    from hephaestus.core.errors import AddressingError

    def command(_args: argparse.Namespace) -> int:
        raise AddressingError(
            "selector 'face' is ambiguous",
            selector="face",
            candidates=("face", "face@2"),
            reason="ambiguous",
        )

    code = dispatch(command, argparse.Namespace(json=False))
    err = capsys.readouterr().err
    assert code == 2, err
    assert "face@2" in err, err


def test_a_json_refusal_omits_the_candidates_key_when_there_are_none(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The machine form must not carry an empty or self-referential list either:
    a consumer branching on ``candidates`` would offer the operator their own
    part back as a suggestion."""
    from hephaestus.core.cli_errors import dispatch
    from hephaestus.core.errors import AddressingError

    def command(_args: argparse.Namespace) -> int:
        raise AddressingError(
            "part 'primary' has no current successful build to inspect",
            selector="primary",
            candidates=("bracket", "primary"),
        )

    code = dispatch(command, argparse.Namespace(json=True))
    captured = capsys.readouterr()
    assert code == 2, captured.err
    assert captured.out == ""
    payload = cast("dict[str, Any]", json.loads(captured.err))
    assert "candidates" not in payload, payload
    assert payload["status"] == "refused"
