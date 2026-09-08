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

import re
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


# --------------------------------------------------------------------------
# J-mirrors-and-dx-33 — the checked set is 29 documents; it should be ~50


def test_the_docs_build_covers_interface_md_and_the_package_readmes() -> None:
    """J-mirrors-and-dx-33: the largest specification and every package README
    are outside the hand-maintained `ROOT_DOCS` list and `docs/` glob, so a rot
    inside them is invisible to the one job that claims to be "the docs build".

    `INTERFACE.md` is the largest specification in the repository (§2.3's route
    table is what `server/tests/test_http_boundary.py`'s
    `test_the_unserved_spec_routes_are_a_named_disjoint_allowlist` needs this
    widening for — see that test's docstring). The package READMEs are real,
    tracked, linked-from-root documents (`README.md` and `CONTRIBUTING.md` both
    point into them) that happen to sit one level below the hand-listed set.
    """
    proc = _run("docs_check.py", "--list")
    assert proc.returncode == 0, proc.stderr
    checked = {line.strip() for line in proc.stdout.splitlines() if line.strip()}

    assert "INTERFACE.md" in checked, (
        "the docs build does not check INTERFACE.md — the largest specification "
        "in the repository rots invisibly, and server/tests/test_http_boundary.py "
        "names this as its own prerequisite (J-mirrors-and-dx-33)"
    )
    for readme in (
        "agent/README.md",
        "web/README.md",
        "web/e2e/README.md",
        "core/README.md",
        "server/README.md",
        "contract/README.md",
        "opstore/README.md",
        "docker/ci/README.md",
    ):
        assert readme in checked, f"the docs build does not check {readme}"


def test_a_package_relative_reference_is_checked_against_its_own_directory(
    synthetic_repo: Path,
) -> None:
    """J-mirrors-and-dx-33's second, independent bug: even a checked document's
    package-relative paths are invisible, because `_check_code_paths` only
    resolves a token whose first segment is a real repository TOP-LEVEL entry
    and silently skips everything else.

    `web/README.md` cites `` `src/tokens.css` `` meaning, from its own
    directory, `web/src/tokens.css` — which does not exist; the real file is
    one directory deeper, `web/src/system/tokens.css`. `"src"` is not a
    repository top-level entry, so today this reference is skipped rather than
    resolved-and-flagged, regardless of whether `web/README.md` is in the
    checked set at all. The fix tries the document's OWN directory first — the
    same thing `_check_links` already does for relative links — before
    concluding a package-relative-looking token is not a repository path.
    """
    # Pinned against a SYNTHETIC document rather than against the live page.
    # The live `web/README.md` reference this test was written from has since
    # been corrected to `src/system/tokens.css` (J-mirrors-and-dx-33 asks for
    # both: the rule AND the five real references it finally makes visible), so
    # asserting on the page would make this test evaporate the moment the defect
    # it describes was fixed. The shape is preserved exactly: a package README,
    # a first segment that is not a repository top-level entry, and a real file
    # one directory deeper than the one named.
    package = synthetic_repo / "web"
    (package / "src" / "system").mkdir(parents=True)
    (package / "src" / "system" / "tokens.css").write_text("", encoding="utf-8")
    readme = package / "README.md"
    readme.write_text("| `src/tokens.css` | the design tokens |\n", encoding="utf-8")

    problems = docs_check.check([readme])
    assert any("tokens.css" in problem for problem in problems), (
        "docs_check.check() does not flag a dead `src/tokens.css` reference: a "
        "package-relative path (first segment not a repository top-level entry) "
        "must be tried against the document's own directory before being "
        f"skipped. Reported problems: {problems}"
    )

    # The live page's own correctness is asserted by the whole-set run above
    # (`test_the_docs_build_resolves_every_reference`); it cannot be checked
    # here, because `synthetic_repo` moves the checker's repository root.


def test_a_package_relative_path_that_resolves_against_its_own_directory_passes(
    synthetic_repo: Path,
) -> None:
    """The positive half: once resolution tries the document's own directory,
    a package-relative reference that genuinely exists must NOT be flagged."""
    pkg = synthetic_repo / "core"
    (pkg / "sub").mkdir(parents=True)
    (pkg / "sub" / "real.py").write_text("x = 1\n", encoding="utf-8")
    readme = pkg / "README.md"
    readme.write_text("# core\n\nSee `sub/real.py` for the entry point.\n", encoding="utf-8")
    assert docs_check.check([readme]) == []


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


def test_source_line_citations_resolve_the_underlying_path(synthetic_repo: Path) -> None:
    page = _doc(
        synthetic_repo,
        "# Page\n\nSee `core/real.py:1`, `core/real.py:1-2`, and `core/real.py:1,3`.\n",
    )
    assert docs_check.check([page]) == []


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


# --------------------------------------------------------------------------
# J-mirrors-and-dx-29 — the flag form of `pnpm --dir` teaches a broken command


#: `CONTRIBUTING.md` and `docs/install.md` are the two documents that
#: established the corepack analysis; they are exempt because they are the
#: source of the reason, not a copy that needs to point back at it.
_GOVERNED_DOCS: Final[tuple[str, ...]] = (
    "agent/README.md",
    "web/README.md",
    "web/e2e/README.md",
    "repo_conventions.md",
)

#: A `pnpm --dir <pkg> …` invocation run from outside that package's own
#: directory silently drops the `packageManager` pin under corepack
#: (`CONTRIBUTING.md`'s "pnpm: the pin, and where its settings live"). It is
#: SAFE only immediately after an explicit `corepack prepare … --activate` (or
#: inside a fenced block that documents that activation) — J-mirrors-and-dx-34
#: names exactly this exemption for `ci.yml`.
_DIR_FLAG_RE: Final[re.Pattern[str]] = re.compile(r"pnpm --dir\s")
_ACTIVATION_HINT_RE: Final[re.Pattern[str]] = re.compile(
    r"corepack prepare|activates the (repository )?pin|corepack note"
)


#: Documents that still teach the flag form, with the reason each is not fixed
#: here. SELF-CLEARING: the test below asserts that every entry still HAS the
#: defect, so the entry cannot outlive it — fixing the document turns this red
#: and forces the entry out.
_FLAG_FORM_PENDING: dict[str, str] = {
    # A root specification. The audit calls `repo_conventions.md:167` the
    # primary edit (a conventions line prescribing the broken form) and the
    # exact replacement text is drafted in the L9 handoff for the single
    # specification pass that owns this file (J-mirrors-and-dx-29).
    "repo_conventions.md": "spec-owned; amendment drafted for the spec pass",
}


def test_a_pending_flag_form_document_still_has_the_defect() -> None:
    """An exclusion may not outlive the thing it excuses."""
    for relative in _FLAG_FORM_PENDING:
        lines = (REPO / relative).read_text(encoding="utf-8").splitlines()
        assert any(_DIR_FLAG_RE.search(line) for line in lines), (
            f"{relative} no longer teaches the flag form — delete its entry from "
            "_FLAG_FORM_PENDING so the document is checked like every other one"
        )


def test_no_governed_document_teaches_the_bare_pnpm_dir_flag_form() -> None:
    """J-mirrors-and-dx-29: `CONTRIBUTING.md` and `docs/install.md` each spend a
    paragraph establishing that `pnpm --dir <pkg> …` run from the clone root
    resolves no `packageManager` field under corepack and silently uses
    whatever is activated — which is why every documented step in those two
    files is written as `cd agent && pnpm …` / `(cd web && pnpm …)`. Four other
    governed documents were never updated to match, because nothing checked
    them (J-mirrors-and-dx-33): `agent/README.md`, `web/README.md`,
    `web/e2e/README.md`, and `repo_conventions.md:167` — the most
    authoritative of the four, a *conventions* line prescribing the broken
    form.

    A document earns an exemption only by mentioning the corepack activation
    near the flag (the way `ci.yml`'s corepack lane does) — mechanical,
    cheap, and exactly what stops this class from recurring per the fix's own
    words: "a console block in a governed document may not contain the flag
    form unless the same block or its preceding lines mention the
    activation".
    """
    offenders: dict[str, list[int]] = {}
    for relative in _GOVERNED_DOCS:
        if relative in _FLAG_FORM_PENDING:
            continue
        path = REPO / relative
        lines = path.read_text(encoding="utf-8").splitlines()
        bad_lines = []
        for lineno, line in enumerate(lines, start=1):
            if not _DIR_FLAG_RE.search(line):
                continue
            window = "\n".join(lines[max(0, lineno - 6) : lineno])
            if _ACTIVATION_HINT_RE.search(window):
                continue
            bad_lines.append(lineno)
        if bad_lines:
            offenders[relative] = bad_lines
    assert not offenders, (
        "these documents teach `pnpm --dir <pkg> …` with no nearby corepack-"
        f"activation note, which CONTRIBUTING.md's own analysis says will not "
        f"carry the version pin: {offenders}. Rewrite to the from-inside form "
        "(`cd agent && pnpm …`) with a pointer at the corepack note, the way "
        "docs/install.md and CONTRIBUTING.md already do."
    )
