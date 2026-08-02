# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""The headless docs set covers the CLI it documents, and keeps covering it.

Stage 7H ships "a headless docs set (install, `heph` verbs, MCP client
configuration, project conventions, registry pinning)". The clause that rots
fastest is "`heph` verbs": a verb added in a later stage lands with its
implementation and its tests, and nothing about that change makes anyone open
`docs/cli.md`. The result is a released tool with an undocumented verb, which
looks exactly like a working tool until a user needs the verb.

So the coverage claim is derived from the parser rather than maintained by hand.
Every subcommand and sub-subcommand `build_parser()` registers must appear as a
worked invocation somewhere in `docs/`. Prose describing a verb is not enough —
the mission text asks for "one honest example", and an example is what a reader
copies.

The check is deliberately over the whole `docs/` set, not over `cli.md` alone:
the registry sub-verbs are documented where pinning is explained, which is where
someone looking for them will be, and forcing every example into one file would
make the reference page worse to satisfy a test.

Two things this test does not do. It does not check option flags — flag-level
drift is what `--help` is for, and mirroring every flag into prose creates a
second, staler help text. And it does not run the examples: several mutate a
project or spawn a sidecar, and `docs_check.py` already resolves every path they
name.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Final

import pytest
from hephaestus.core.cli import build_parser

REPO: Final[Path] = Path(__file__).resolve().parents[2]
DOCS: Final[Path] = REPO / "docs"

#: The pages Stage 7H names as deliverables, each with the subject it must cover.
REQUIRED_PAGES: Final[dict[str, str]] = {
    "install.md": "install",
    "cli.md": "heph verbs",
    "mcp.md": "MCP client configuration",
    "conventions.md": "project conventions",
    "registry-pinning.md": "registry pinning",
    "registry-contributions.md": "registry contribution guide",
    "leaderboard.md": "model leaderboard",
}


def _docs_text() -> str:
    return "\n".join(sorted(path.read_text(encoding="utf-8") for path in DOCS.glob("**/*.md")))


def _invocations() -> list[str]:
    """Every ``heph …`` invocation the parser registers, as documentation must show it."""
    parser = build_parser()
    (top,) = (a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    found: list[str] = []
    for verb, subparser in sorted(top.choices.items()):
        inner = [a for a in subparser._actions if isinstance(a, argparse._SubParsersAction)]
        if not inner:
            found.append(f"heph {verb}")
            continue
        # A verb with sub-verbs is documented through them, not as a bare word.
        for sub in sorted(inner[0].choices):
            found.append(f"heph {verb} {sub}")
    return found


@pytest.mark.parametrize("page", sorted(REQUIRED_PAGES))
def test_every_deliverable_page_is_present_and_not_empty(page: str) -> None:
    """The docs set named in `mission_plan.md` §"Stage 7H" exists on disk."""
    path = DOCS / page
    assert path.is_file(), f"{page} ({REQUIRED_PAGES[page]}) is missing from docs/"
    assert path.read_text(encoding="utf-8").strip(), f"{page} is empty"


@pytest.mark.parametrize("invocation", _invocations())
def test_every_registered_verb_has_a_worked_example(invocation: str) -> None:
    """Each verb the CLI registers appears as a copyable invocation in docs/.

    Failure means a verb shipped without documentation. The fix is a two-line
    example in the page where a reader would look for it — not an exemption.
    """
    assert invocation in _docs_text(), (
        f"`{invocation}` is registered by build_parser() but no page under docs/ shows it being run"
    )


def test_the_docs_set_documents_no_verb_the_cli_does_not_have() -> None:
    """The reference page does not promise verbs that were renamed or dropped.

    `RELEASE_FACTS.md` §5 recorded exactly this failure in the other direction —
    `repo_conventions.md` naming a `heph export` verb that was never registered.
    A docs set that invents a verb is worse than one that omits it: the user
    follows it and gets an argparse error.
    """
    registered = {line.split()[1] for line in _invocations()}
    text = (DOCS / "cli.md").read_text(encoding="utf-8")
    documented = {
        line.split("`heph ")[1].split("`")[0].split()[0].strip("{},")
        for line in text.splitlines()
        if line.startswith("### `heph ")
    }
    unknown = documented - registered
    assert not unknown, f"docs/cli.md documents unregistered verb(s): {sorted(unknown)}"
