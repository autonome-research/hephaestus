# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""G7H: "headless docs build without warnings" and the Apache-2.0 header rule.

`test_docs_set.py` asserts the docs set *covers the CLI*; `test_release_lanes.py`
asserts the workflows *invoke* the two checkers. Neither runs them, so on a
developer machine both clauses were previously provable only by reading YAML —
and a checker that has rotted into vacuous passing looks identical to a green
gate from there.

So this module runs the build. Two halves, because "the check passes" and "the
check would catch a violation" are different claims and only the pair is worth
anything:

* the repository half runs `scripts/docs_check.py` and
  `scripts/license_headers.py --check` as the release gate runs them, through
  their real entry points, and requires a clean exit with a clean stderr;
* the sensitivity half plants each class of defect the checkers exist to catch
  in a synthetic tree and requires it to be reported.

The synthetic tree is built under `tmp_path` with the checker's ``REPO_ROOT``
monkeypatched onto it. That is why `docs_check.check()` and
`license_headers.governed_files()` take their inputs the way they do; the
alternative — planting a broken link in the real `docs/` and deleting it —
leaves a broken repository behind whenever the assertion fails.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest

REPO: Final[Path] = Path(__file__).resolve().parents[2]
SCRIPTS: Final[Path] = REPO / "scripts"

sys.path.insert(0, str(SCRIPTS))

import docs_check  # noqa: E402
import license_headers  # noqa: E402


def _run(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Run a checker exactly as the `docs` CI job and the release gate do."""
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script), *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(REPO),
    )


# --------------------------------------------------------------------------
# the build itself


def test_the_docs_build_resolves_every_reference() -> None:
    """`docs_check.py` exits 0 over the whole documentation set.

    This is the G7H clause verbatim. The checker has no warning level by design,
    so "without warnings" and "exit 0" are the same statement; the stderr
    assertion keeps it that way, since a checker that started *printing*
    problems while still exiting 0 would silently become advisory.
    """
    proc = _run("docs_check.py")
    assert proc.returncode == 0, f"the docs build reported unresolved references:\n{proc.stderr}"
    assert proc.stderr.strip() == "", f"the docs build emitted diagnostics:\n{proc.stderr}"
    assert "all references resolve" in proc.stdout


def test_the_docs_build_covers_the_deliverable_pages_and_the_normative_set() -> None:
    """The build is over the pages G7H ships, not over an empty file list.

    A link checker pointed at nothing passes. `--list` is the checker's own
    statement of what it checked, so assert against that rather than re-deriving
    the set here.
    """
    proc = _run("docs_check.py", "--list")
    assert proc.returncode == 0, proc.stderr
    checked = {line.strip() for line in proc.stdout.splitlines() if line.strip()}

    # Every page the Stage 7H deliverable sentence names.
    for page in (
        "install.md",
        "cli.md",
        "mcp.md",
        "conventions.md",
        "registry-pinning.md",
        "registry-contributions.md",
        "leaderboard.md",
    ):
        assert f"docs/{page}" in checked, f"the docs build does not check docs/{page}"

    # And the normative root documents `verification.md` requires it to cover.
    for doc in ("README.md", "CONTRIBUTING.md", "repo_conventions.md", "verification.md"):
        assert doc in checked, f"the docs build does not check {doc}"


def test_every_governed_file_carries_the_apache_header() -> None:
    """`license_headers.py --check` exits 0 — the "Apache-2.0 headers" clause."""
    proc = _run("license_headers.py", "--check")
    assert proc.returncode == 0, f"files are missing their Apache-2.0 header:\n{proc.stderr}"
    assert proc.stderr.strip() == ""
    assert "all carry the header" in proc.stdout


def test_the_header_rule_governs_the_files_stage_7h_ships() -> None:
    """The governed set is the shipped-away-from-the-tree set, not a sample.

    `CONTRIBUTING.md` states the rule; this pins the three families it names so
    that narrowing the rule to make a red check green has to happen here, in
    public, rather than by quietly editing a glob.
    """
    governed = {p.relative_to(REPO).as_posix() for p in license_headers.governed_files(REPO)}
    assert "README.md" in governed, "root Markdown is governed"
    assert "CONTRIBUTING.md" in governed
    assert "docs/install.md" in governed, "the docs set is governed"
    assert "scripts/docs_check.py" in governed, "release machinery is governed"
    assert any(p.endswith("hatch_build.py") for p in governed), "build hooks are governed"

    # Evidence and pinned trees are deliberately outside the rule: a header in
    # registries/ is a digest change that breaks every consumer's pin.
    assert not any(p.startswith(("registries/", "corpus/", "bench/results/")) for p in governed)


# --------------------------------------------------------------------------
# sensitivity: each checker catches what it exists to catch


@pytest.fixture
def synthetic_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A minimal tree that both checkers are re-rooted onto."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "real.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "VALIDATION.md").write_text("# V\n\n## 8. Reported metrics\n", encoding="utf-8")
    monkeypatch.setattr(docs_check, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(license_headers, "REPO_ROOT", tmp_path)
    return tmp_path


def _doc(root: Path, body: str) -> Path:
    path = root / "docs" / "page.md"
    path.write_text(body, encoding="utf-8")
    return path


def test_a_broken_relative_link_is_an_error(synthetic_repo: Path) -> None:
    page = _doc(synthetic_repo, "# Page\n\nSee [the guide](missing.md).\n")
    problems = docs_check.check([page])
    assert any("link target does not exist" in p and "missing.md" in p for p in problems), problems


def test_a_link_to_a_heading_that_does_not_exist_is_an_error(synthetic_repo: Path) -> None:
    (synthetic_repo / "docs" / "other.md").write_text("# Other\n\n## Present\n", encoding="utf-8")
    page = _doc(synthetic_repo, "# Page\n\n[jump](other.md#absent)\n")
    problems = docs_check.check([page])
    assert any("#absent" in p for p in problems), problems


def test_a_repository_path_that_does_not_exist_is_an_error(synthetic_repo: Path) -> None:
    page = _doc(synthetic_repo, "# Page\n\nEdit `core/gone.py` to change it.\n")
    problems = docs_check.check([page])
    assert any("repository path does not exist" in p for p in problems), problems

    ok = _doc(synthetic_repo, "# Page\n\nEdit `core/real.py` to change it.\n")
    assert docs_check.check([ok]) == []


def test_a_section_reference_past_the_end_of_a_document_is_an_error(
    synthetic_repo: Path,
) -> None:
    """`VALIDATION.md` §8 is a real reference in the shipped docs; §99 is not."""
    page = _doc(synthetic_repo, "# Page\n\nSee `VALIDATION.md` §99 for the gap column.\n")
    problems = docs_check.check([page])
    assert any("no section §99" in p for p in problems), problems

    ok = _doc(synthetic_repo, "# Page\n\nSee `VALIDATION.md` §8 for the gap column.\n")
    assert docs_check.check([ok]) == []


def test_an_example_inside_a_fence_is_not_a_reference(synthetic_repo: Path) -> None:
    """Fenced blocks illustrate; they do not refer.

    Without this the install page could not show `pipx install hephaestus-cad`
    output, and the pressure would be to weaken the checker instead.
    """
    page = _doc(synthetic_repo, "# Page\n\n```\ncat core/not-real.py\n```\n")
    assert docs_check.check([page]) == []


def test_a_new_docs_page_without_a_header_is_reported(synthetic_repo: Path) -> None:
    """The rule applies to files added later, which is the only time it matters."""
    fresh = synthetic_repo / "docs" / "new-page.md"
    fresh.write_text("# New\n\nBody.\n", encoding="utf-8")
    governed = license_headers.governed_files(synthetic_repo)
    assert fresh in governed
    assert fresh in list(license_headers.missing(governed))

    assert license_headers.apply_header(fresh) is True
    assert list(license_headers.missing([fresh])) == []
    # Idempotent: a second pass must not stack a second header.
    assert license_headers.apply_header(fresh) is False
    assert fresh.read_text(encoding="utf-8").count("SPDX-License-Identifier") == 1


def test_a_header_buried_below_the_top_of_a_file_does_not_count(synthetic_repo: Path) -> None:
    """A header is a statement at the top, not a string somewhere in the file."""
    buried = synthetic_repo / "docs" / "buried.md"
    body = "\n".join(f"line {n}" for n in range(20))
    buried.write_text(
        f"# Doc\n\n{body}\n\n<!--\n{license_headers.COPYRIGHT_LINE}\n"
        f"{license_headers.SPDX_LINE}\n-->\n",
        encoding="utf-8",
    )
    assert buried in list(license_headers.missing([buried]))


def test_a_shebang_survives_the_applied_header(synthetic_repo: Path) -> None:
    """`scripts/*.py` may be executable; inserting above the shebang breaks them."""
    script = synthetic_repo / "scripts"
    script.mkdir()
    tool = script / "tool.py"
    tool.write_text("#!/usr/bin/env python3\nprint('hi')\n", encoding="utf-8")
    assert license_headers.apply_header(tool) is True
    text = tool.read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env python3\n")
    assert license_headers.has_header(text)
