# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""Run the reference page's own console examples (J-cli-robustness-18/-19).

``tests/stage7h/test_docs_set.py`` asserts that every registered verb *appears*
in the documentation set. That is a coverage gate, and it cannot catch a wrong
claim about a verb that exists — which is the whole class this closes:
``docs/cli.md`` documented a build-everything mode the CLI refuses, quoted two
empty-state transcripts that had been reworded, and stated an explode range the
engine does not enforce. Each was documentation written against a behaviour that
later moved, and each was invisible to a presence check.

So the page's own blocks are extracted and RUN. The read-only subset only: this
is a documentation gate, not a build gate, and a runner that publishes artifacts
would be asserting the engine rather than the page. The expected exit code is
derived from the block itself — a transcript whose output opens with ``heph:``
is showing a refusal, which is exit 2; anything else is exit 0 — so the page
cannot drift from the runner either.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CLI_DOC = REPO / "docs" / "cli.md"
FIXTURE = REPO / "corpus" / "public_fixtures" / "assembly"

#: Invocations this runner executes. Read-only by construction: nothing here
#: builds, publishes, mutates the project or reaches the network. Widening the
#: set is welcome; widening it past that line is not, because a docs gate that
#: takes minutes stops being run.
READ_ONLY: frozenset[str] = frozenset(
    {
        "--version",
        "--help",
        "build",  # bare: the usage refusal the page now quotes
        "joints",
        "motion",
        "parts",
    }
)

#: A ``$ heph …`` line inside a fenced ``console`` block.
_PROMPT_RE = re.compile(r"^\$\s+(?:uv run )?heph\b(.*)$")


def _examples() -> list[tuple[int, list[str], list[str]]]:
    """``(line number, argv, following output lines)`` for each runnable example."""
    lines = CLI_DOC.read_text(encoding="utf-8").splitlines()
    found: list[tuple[int, list[str], list[str]]] = []
    in_console = False
    for index, line in enumerate(lines):
        if line.strip().startswith("```"):
            in_console = line.strip().lower() == "```console"
            continue
        if not in_console:
            continue
        match = _PROMPT_RE.match(line.strip())
        if match is None:
            continue
        argv = match.group(1).split()
        head = argv[0] if argv else ""
        if head not in READ_ONLY:
            continue
        if head == "build" and argv[1:]:
            # Only the BARE form is reproducible here: a named target belongs to
            # whatever project its surrounding walkthrough created, and this
            # runner opens one fixture. The bare form is the one the audit
            # found misdocumented, and it is the one that runs.
            continue
        if any(token in {">", "|", "&&", ";"} for token in argv):
            continue
        output: list[str] = []
        for follow in lines[index + 1 :]:
            stripped = follow.strip()
            if stripped.startswith("```") or stripped.startswith("$ "):
                break
            output.append(follow)
        found.append((index + 1, argv, output))
    return found


#: Transcript detail a runner must not pin: content addresses, temporary paths,
#: elisions and JSON bodies all move for reasons that are not documentation rot.
_UNSTABLE: tuple[str, ...] = ("…", "...", "sha256:", "artifact=", "/", "{", "\\")


def _is_stable(line: str) -> bool:
    return not any(marker in line for marker in _UNSTABLE)


def _expected_exit(output: list[str]) -> int:
    """The code the block itself shows: a ``heph:`` line is a refusal (2)."""
    for line in output:
        if line.strip():
            return 2 if line.strip().startswith("heph:") else 0
    return 0


@pytest.fixture(scope="module")
def fresh_fixture(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The page's own opening command: a fresh copy of the public fixture.

    Fresh matters. The page's empty-state transcripts are true of a copy with no
    build store, which is what a reader gets, because the store is gitignored —
    the fact J-cli-robustness-19 found the page silent about.
    """
    root = tmp_path_factory.mktemp("cli-doc") / "demo"
    shutil.copytree(FIXTURE, root)
    return root


def _run(argv: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "hephaestus.core.cli", *argv],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )


def test_the_page_has_runnable_examples() -> None:
    """A runner that extracts nothing is a green gate asserting nothing."""
    argvs = [" ".join(argv) for _, argv, _ in _examples()]
    assert argvs, "no runnable console example was extracted from docs/cli.md"
    # The three the audit found wrong, by name, so a rewrite cannot drop them
    # from the runner's reach without failing here.
    assert "build" in argvs, "the bare `heph build` refusal is no longer shown"
    assert "joints" in argvs, "the joints empty state is no longer shown"
    assert "motion" in argvs, "the motion empty state is no longer shown"


@pytest.mark.parametrize(
    ("lineno", "argv", "output"),
    [
        pytest.param(*example, id=f"L{example[0]}:{' '.join(example[1]) or 'heph'}")
        for example in _examples()
    ],
)
def test_a_documented_invocation_behaves_as_the_page_shows(
    lineno: int, argv: list[str], output: list[str], fresh_fixture: Path
) -> None:
    expected = _expected_exit(output)
    proc = _run(argv, fresh_fixture)
    assert proc.returncode == expected, (
        f"docs/cli.md:{lineno} shows `heph {' '.join(argv)}` "
        f"{'refusing' if expected else 'succeeding'}, but it exited {proc.returncode}.\n"
        f"stdout: {proc.stdout.strip()[:400]}\nstderr: {proc.stderr.strip()[:400]}"
    )
    # The quoted TEXT is part of the claim, not decoration: a page showing a
    # sentence the CLI no longer prints is the same defect one layer down, and
    # it is exactly what happened to the joints and motion empty states. Only
    # stable lines are compared — anything carrying a hash, a path, an ellipsis
    # or a JSON body is transcript detail this runner has no business pinning.
    combined = proc.stdout + proc.stderr
    for line in output:
        quoted = line.strip()
        if not quoted or not _is_stable(quoted):
            continue
        assert quoted in combined, (
            f"docs/cli.md:{lineno} quotes {quoted!r} for `heph {' '.join(argv)}`, "
            f"which the CLI no longer prints.\nactual: {combined.strip()[:400]}"
        )


# --------------------------------------------------------------------------
# J-cli-robustness-19: the page promises a NAMED refusal the CLI cannot give
#
# `docs/cli.md` says `principal` "is refused by name, because a limb scan is
# always partial and the sampled region's principal axes are not the object's",
# and `cli_scan.py`'s own `--align` help text says the same. Neither is true
# today: the flag is an argparse `choices=` list, and a `choices=` rejection
# cannot carry a reason — every value that is not `as_posed` or `declared` gets
# one generic sentence. The reference page therefore documents an intended
# behaviour rather than the shipped one.
#
# The fix is in `core/src/hephaestus/core/cli_scan.py` (drop `choices=`, validate
# in the handler, refuse `principal` with the message already written in the help
# and anything else with the generic list, exit 2 either way), which belongs to
# the CLI lane rather than this one. Recorded here so the gap is a mechanism
# instead of a line in a report: the assertion is SELF-CLEARING — it describes
# the defect, so the moment the CLI lane lands the handler-side refusal this goes
# red and forces the page, the help text and the golden to be reconciled together.


def test_the_named_alignment_refusal_is_still_only_a_promise() -> None:
    done = subprocess.run(
        [sys.executable, "-m", "hephaestus.core.cli", "scan", "check", "-h"],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO,
    )
    help_text = done.stdout
    page = (REPO / "docs" / "cli.md").read_text(encoding="utf-8")
    assert "refused by name" in page, (
        "docs/cli.md no longer promises a named refusal for `--align principal`; "
        "delete this test with the promise"
    )
    assert "{as_posed,declared}" in help_text, (
        "`heph scan check --align` no longer offers an argparse choices list, so the "
        "handler-side refusal J-cli-robustness-19 asks for has landed. Delete this "
        "test, and check in the same change that `docs/cli.md`'s named-refusal "
        "sentence and cli_scan.py's help text now describe what actually happens."
    )


# --------------------------------------------------------------------------
# J-cli-robustness-19, second half: the explode contract now differs by layer
#
# The item asks for ONE explode contract, stated the same way everywhere. The
# engine's is `render/inspect.py`'s validator: any finite value `>= 0`, so `2.0`
# is accepted and exaggerates the view. `docs/cli.md` has been reconciled to
# that. `cli_render.py`'s `--explode` help still advertises the OLD, narrower
# contract (`explode factor in [0, 1]`), and that string is pinned byte-for-byte
# in `tests/stage0a/goldens/help_render.txt`, so a reader of `heph render -h`
# is told a bound the CLI does not enforce — the same page-versus-help split one
# layer down.
#
# The code half is the CLI lane's (`cli_render.py` is not this lane's file), so
# this is recorded as a SELF-CLEARING mechanism rather than a line in a report:
# it asserts the defect still exists, and goes red the moment the help text is
# reconciled — with a message naming the golden that must be re-recorded in the
# same change.


def test_the_explode_help_still_advertises_a_bound_the_engine_does_not_enforce() -> None:
    page = (REPO / "docs" / "cli.md").read_text(encoding="utf-8")
    assert "any finite value `>= 0`" in page, (
        "docs/cli.md no longer states the finite/`>= 0` explode contract that "
        "`render/inspect.py` actually enforces; if the contract itself changed, "
        "this test and the help text below change with it"
    )

    source = (REPO / "core" / "src" / "hephaestus" / "core" / "cli_render.py").read_text(
        encoding="utf-8"
    )
    assert "explode factor in [0, 1]" in source, (
        "`cli_render.py`'s `--explode` help no longer claims the [0, 1] bound, so "
        "J-cli-robustness-19's explode half has landed. Delete this test, and in "
        "the SAME change re-record tests/stage0a/goldens/help_render.txt, which "
        "pins the old string byte-for-byte, and re-read docs/cli.md:383 so all "
        "three layers state one contract."
    )

    golden = (REPO / "tests" / "stage0a" / "goldens" / "help_render.txt").read_text(
        encoding="utf-8"
    )
    assert "explode factor in [0, 1]" in golden, (
        "the help golden and cli_render.py disagree about `--explode`, which means "
        "one of them was changed without the other; tests/stage0a re-records it"
    )
