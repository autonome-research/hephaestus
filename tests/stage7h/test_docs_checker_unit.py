# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit assertions over the docs checker's two widened rules.

The widened run is itself the test — the checker runs in CI over fifty
documents — but two of its rules are worth pinning directly, because both were
*silently* wrong rather than absent, and a rule that returns "no problem" for
the wrong reason is indistinguishable from a passing one:

* **package-relative resolution** (J-mirrors-and-dx-33). The path rule refused
  to resolve any token whose first segment is not a repository top-level entry,
  so ``src/tokens.css`` in ``web/README.md`` — a real dead reference, the file
  is one directory deeper — did not flag even once the document was in the set.
* **the command form** (J-mirrors-and-dx-29). Four documents taught
  ``pnpm --dir``, which the two authoritative install documents each spend a
  paragraph explaining will not carry the version pin.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import docs_check  # noqa: E402
import pytest  # noqa: E402


@pytest.fixture
def scratch_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the checker's repository root at a throwaway tree.

    The checker reports positions as repository-relative paths, so a document
    outside the checkout cannot be checked without moving the root with it.
    """
    monkeypatch.setattr(docs_check, "REPO_ROOT", tmp_path)
    return tmp_path


def test_a_package_relative_path_resolves_against_its_own_document() -> None:
    """The fallback the rule was missing: try the document's own directory."""
    doc = REPO / "web" / "README.md"
    assert docs_check._resolves_beside(doc, "src/system/tokens.css")
    assert not docs_check._resolves_beside(doc, "src/tokens.css")


def test_the_dead_reference_the_audit_found_would_be_flagged(scratch_repo: Path) -> None:
    """The exact defect: `src/tokens.css` beside `web/README.md`, one level off.

    Written against a throwaway document rather than the (now fixed) README, so
    the assertion keeps proving the RULE after the instance is gone.
    """
    package = scratch_repo / "web"
    (package / "src" / "system").mkdir(parents=True)
    (package / "src" / "system" / "tokens.css").write_text("", encoding="utf-8")
    doc = package / "README.md"
    doc.write_text("| `src/tokens.css` | the design tokens |\n", encoding="utf-8")

    problems: list[str] = []
    docs_check._check_code_paths(doc, problems, frozenset({"web"}))
    assert len(problems) == 1, problems
    assert "src/tokens.css" in problems[0]

    doc.write_text("| `src/system/tokens.css` | the design tokens |\n", encoding="utf-8")
    problems = []
    docs_check._check_code_paths(doc, problems, frozenset({"web"}))
    assert problems == []


def test_a_command_block_teaching_the_flag_form_is_flagged(scratch_repo: Path) -> None:
    doc = scratch_repo / "GUIDE.md"
    doc.write_text("```console\n$ pnpm --dir web build\n```\n", encoding="utf-8")
    problems: list[str] = []
    docs_check._check_command_forms(doc, problems)
    assert len(problems) == 1, problems
    assert "pnpm --dir" in problems[0]


def test_activating_the_pin_first_makes_the_flag_form_legitimate(scratch_repo: Path) -> None:
    """Exactly what the one corepack CI lane does, and why it is not a defect."""
    doc = scratch_repo / "GUIDE.md"
    doc.write_text(
        "```console\n$ corepack prepare pnpm@10.34.5 --activate\n$ pnpm --dir web build\n```\n",
        encoding="utf-8",
    )
    problems: list[str] = []
    docs_check._check_command_forms(doc, problems)
    assert problems == []


def test_prose_describing_the_flag_form_is_not_a_command(scratch_repo: Path) -> None:
    """A fenced tree diagram that mentions the form is describing it."""
    doc = scratch_repo / "GUIDE.md"
    doc.write_text(
        "```\nweb/    (Stage 4: driven as `pnpm --dir web …` with its own lockfile)\n```\n",
        encoding="utf-8",
    )
    problems: list[str] = []
    docs_check._check_command_forms(doc, problems)
    assert problems == []


def test_every_command_form_exclusion_carries_a_reason() -> None:
    """The repository's documented-exclusion standard, applied to this list."""
    assert docs_check.COMMAND_FORM_EXCLUSIONS
    for name, reason in docs_check.COMMAND_FORM_EXCLUSIONS.items():
        assert (REPO / name).is_file(), f"{name} is excluded but does not exist"
        assert len(reason) > 30, f"{name}'s exclusion reason is not a reason"


def test_a_self_clearing_exclusion_still_has_the_defect_it_excuses() -> None:
    """An exclusion may not outlive the thing it excuses.

    Four of the entries are documents this lane does not own, each awaiting a
    one-line edit in the pass that does. Those say so with the word
    "Self-clearing", and this asserts the promise: when the edit lands, the
    document stops matching and the entry has to go — rather than sitting there
    quietly exempting a file that is already correct.
    """
    stale: list[str] = []
    for name, reason in docs_check.COMMAND_FORM_EXCLUSIONS.items():
        if "Self-clearing" not in reason:
            continue
        text = (REPO / name).read_text(encoding="utf-8")
        if not docs_check._INLINE_DIR_FORM_RE.search(text):
            stale.append(name)
    assert not stale, (
        "these documents no longer teach the flag form — delete their entries from "
        f"COMMAND_FORM_EXCLUSIONS so they are checked like every other one: {stale}"
    )


def test_a_prose_sentence_about_the_flag_is_not_a_command_that_teaches_it() -> None:
    """The discriminator, both directions, on the two real shapes.

    `CONTRIBUTING.md` and `README.md` each spend a paragraph explaining why the
    flag is wrong, and both have to name it to do so. A span naming the FORM has
    nothing to run; a span that is a complete invocation is what a reader copies.
    """
    describing = "run from **inside** `agent/`, rather than with `pnpm --dir web`: it moves"
    prescribing = "**Gate G2**: `pnpm --dir agent test` and `uv run pytest -q` both exit 0"
    assert docs_check._INLINE_DIR_FORM_RE.search(describing) is None
    assert docs_check._INLINE_DIR_FORM_RE.search(prescribing) is not None


def test_every_excluded_document_carries_a_reason() -> None:
    for name, reason in docs_check.EXCLUDED_DOCS.items():
        assert (REPO / name).is_file(), f"{name} is excluded but does not exist"
        assert len(reason) > 20, f"{name}'s exclusion reason is not a reason"


def test_the_specification_and_the_package_readmes_are_in_the_checked_set() -> None:
    """The two gaps that compounded: a hand-listed root set, and no README."""
    checked = {path.relative_to(REPO).as_posix() for path in docs_check._documents()}
    for name in ("INTERFACE.md", "web/README.md", "agent/README.md", "docker/ci/README.md"):
        assert name in checked, f"{name} is outside the docs checker's set"
