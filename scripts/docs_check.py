# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""The docs build: resolve every reference in the documentation set.

Gate G7H requires that "headless docs build without warnings", and
`verification.md` separately requires "a docs-layout/link check [that] verifies
every repository path and section reference in the normative root documents".
Those are the same job, so this is one tool.

The docs are plain Markdown, so "building" them is checking them. Three classes
of reference are resolved, and any unresolved one is an error — there is no
warning level, because a warning nobody has to fix is how a link rots:

1. **Relative links** — ``[text](path)`` and ``[text](path#anchor)`` must name a
   file that exists, and the anchor must match a heading in it.
2. **Backticked repository paths** — a token like ``core/src/...`` whose first
   segment is a real top-level entry of the repository must exist. Anchoring on
   the first segment is what keeps ``ctx.holes()`` and ``p.wing`` out of the
   check: only things that start at a real repository directory are treated as
   repository paths.
3. **Document and section references** — ``VALIDATION.md`` must exist, and
   ``VALIDATION.md`` §8 must name a numbered heading that document actually has.

4. **Command form** — a console block in a governed document may not teach
   ``pnpm --dir``, which does not carry the version pin, unless the block
   activates the pin first (:func:`_check_command_forms`).

Placeholders are skipped by shape, not by allowlist: a path containing ``<``,
``*``, ``…``, ``$`` or a brace expansion is a template
(``bench/results/<model>/<date>.json``), and a path under ``.heph/`` is runtime
state that exists in a user's project rather than in this repository.

**The checked set is discovered, not listed** (J-mirrors-and-dx-33). Root
markdown, everything under ``docs/``, and every tracked README or design
document, minus :data:`EXCLUDED_DOCS`. A hand-maintained list leaves a new root
document uncovered by default, which is how the largest specification in the
repository sat outside "the docs build" while the workflow file claimed it was
the reference check.

Usage::

    uv run python scripts/docs_check.py            # the whole discovered set
    uv run python scripts/docs_check.py --list     # which files are checked
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Final

sys.path.insert(0, str(Path(__file__).resolve().parent))

import legal_review_check

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]

#: Documents deliberately OUTSIDE the checked set, each with a written reason.
#: Discovery replaced a hand-maintained root list (J-mirrors-and-dx-33), because
#: a hand-maintained list makes a new root document uncovered BY DEFAULT — which
#: is how the largest specification in the repository was never checked. The
#: repository's own documented-exclusion standard applies: an entry with no
#: reason beside it is an oversight, not a decision.
EXCLUDED_DOCS: Final[dict[str, str]] = {
    # Deliberately ahead of the code: they describe surfaces not yet built, so
    # their references are forward statements rather than rot. Ten problems, all
    # of that kind, measured 2026-09-04.
    "PHYSICS.md": "forward-looking design; describes surfaces not yet built",
    "CAM.md": "forward-looking design; describes surfaces not yet built",
    # Recorded evidence, not documentation: the bytes are the fixture.
    "server/tests/fixtures/README.md": "recorded evidence; reformatting it edits it",
    "tests/stage11a/fixtures/pre_item19_parts/README.md": (
        "frozen legacy registry content pinned by a Merkle root"
    ),
}

#: Markdown inline/reference link target, e.g. ``[install](install.md#verifying)``.
_LINK_RE: Final[re.Pattern[str]] = re.compile(r"\[[^\]^]*\]\(([^)\s]+)\)")

#: Anything inside single backticks.
_CODE_RE: Final[re.Pattern[str]] = re.compile(r"`([^`\n]+)`")

#: A fenced code block, whose contents are examples rather than references.
_FENCE_RE: Final[re.Pattern[str]] = re.compile(r"^\s*```")

#: ``…`` `DOC.md` `` §7`` — a section reference into a sibling document.
_SECTION_RE: Final[re.Pattern[str]] = re.compile(r"`([A-Za-z_][A-Za-z0-9_.-]*\.md)`\s*§\s*(\d+)")

#: A bare document name in backticks, e.g. ``VALIDATION.md``.
_DOCNAME_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*\.md$")

#: Markdown ATX heading.
_HEADING_RE: Final[re.Pattern[str]] = re.compile(r"^(#{1,6})\s+(.*?)\s*#*$")

#: A heading that opens a numbered section, e.g. ``## 8. Reported metrics``.
_NUMBERED_HEADING_RE: Final[re.Pattern[str]] = re.compile(r"^(\d+)[.)]?\s")

#: Shapes that make a token a template or runtime path rather than a repo path.
#: Braces are shell expansion — ``corpus/public_fixtures/{a,b,c}`` names three
#: directories in one token, so the literal path deliberately does not exist.
_PLACEHOLDER_CHARS: Final[str] = "<>*…$?{}"

#: References the normative documents make to things that deliberately do not
#: exist in this checkout. Each is listed with why, so that "unresolved" keeps
#: meaning "broken" — an empty allowance is how a link check stays worth running.
FORWARD_REFERENCES: Final[dict[str, str]] = {
    # Stage 4 (web workspace) has not landed; 7H is the headless release.
    "server/http": "Stage 4 deliverable, not part of v0.1.0-headless",
    # `repo_conventions.md`: private reference fixtures are fetched only inside
    # the isolated verifier and are gitignored, pending the Stage 7 legal review.
    "corpus/reference/": "private CI fixtures, gitignored by policy",
    # The Stage 7 legal review that gates publishing those fixtures. It gates the
    # full release, explicitly not G7H.
    "LEGAL-REVIEW.md": "Stage 7 legal review, not a G7H blocker",
}


class Problem(Exception):
    """Raised only to carry a message; the checker collects strings instead."""


def _top_level_entries() -> frozenset[str]:
    """Names directly under the repository root — the anchor for path detection."""
    return frozenset(p.name for p in REPO_ROOT.iterdir() if not p.name.startswith("."))


def _slug(heading: str) -> str:
    """GitHub's anchor slug: lowercase, punctuation dropped, spaces to hyphens."""
    text = heading.strip().lower()
    text = re.sub(r"`|\*|_", "", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"\s+", "-", text).strip("-")


def _headings(path: Path) -> tuple[list[str], list[str]]:
    """Return ``(anchor slugs, heading texts)`` for a markdown file."""
    slugs: list[str] = []
    texts: list[str] = []
    in_fence = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = _HEADING_RE.match(line)
        if match is None:
            continue
        texts.append(match.group(2))
        slugs.append(_slug(match.group(2)))
    return slugs, texts


def _prose_lines(path: Path) -> Iterator[tuple[int, str]]:
    """Yield ``(lineno, text)`` for lines outside fenced code blocks.

    Fenced blocks hold examples — a console transcript naming ``/tmp/demo`` or a
    TOML sample naming ``vendor/acme-skills`` is illustrating, not referring.
    """
    in_fence = False
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            yield lineno, line


def _gitignored(path: str) -> bool:
    """Is ``path`` matched by the repository's gitignore rules?

    Probed twice: the path itself, and a hypothetical child. A directory
    pattern like ``dist/`` cannot match a NON-EXISTENT path (git has no way
    to know it would be a directory) — which is exactly the case this helper
    exists for on a bare CI checkout — but any child of an ignored directory
    is ignored, so the child probe answers for the directory.
    """
    for candidate in (path, path.rstrip("/") + "/_probe"):
        proc = subprocess.run(
            ["git", "check-ignore", "-q", "--", candidate],
            cwd=REPO_ROOT,
            capture_output=True,
            check=False,
        )
        if proc.returncode == 0:
            return True
    return False


def _resolves(token: str) -> bool:
    """Does ``token`` name something in the repository?

    Beyond the literal path, two conventions the normative documents use are
    honoured. A trailing ``::symbol`` names a definition inside a file
    (``spikes/cad_kernel/box_build.py::normalize_step``), so it is stripped. And
    a *module shorthand* like ``core/project_store`` or ``server/mcp`` names an
    import path inside a workspace package, not a directory at the repository
    root — those documents describe the system's module structure, and rewriting
    them into ``core/src/hephaestus/core/project_store`` would make them worse
    to read in exchange for making this checker simpler.
    """
    path = token.split("::", 1)[0].rstrip("/")
    # Design documents often cite an exact source line or range. The suffix is
    # provenance, not part of the filesystem path (``module.py:12-18`` and
    # ``module.py:12,19`` are both common in the specification set).
    path = re.sub(r":\d+(?:[-,]\d+)*$", "", path)
    if not path:
        return True
    if (REPO_ROOT / path).exists():
        return True
    # A path that is absent but GITIGNORED is a declared build output
    # (agent/dist/, the staged sidecar, dist/ wheels): packaging docs must be
    # able to name those, and they never exist on the bare checkout CI runs
    # this checker on (run 30758817258 failed exactly there). git is the
    # authority on what counts as build output; nothing is hard-coded here.
    if _gitignored(path):
        return True
    head, _, rest = path.partition("/")
    if not rest:
        return False
    candidates = (
        REPO_ROOT / head / "src" / "hephaestus" / head / rest,
        REPO_ROOT / head / "src" / "hephaestus" / rest,
        # A workspace member whose package is NOT under the `hephaestus`
        # namespace: `opstore/gc.py` is `opstore/src/opstore/gc.py`. Missing this
        # candidate is why two live references in INTERFACE.md read as rot.
        REPO_ROOT / head / "src" / head / rest,
        REPO_ROOT / head / "src" / rest,
    )
    return any(candidate.exists() for candidate in candidates)


def _is_placeholder(token: str) -> bool:
    if any(ch in token for ch in _PLACEHOLDER_CHARS):
        return True
    return token.startswith((".heph/", "~", "/", "http://", "https://"))


def _resolves_beside(document: Path, token: str) -> bool:
    """Does ``token`` name something relative to ``document``'s own directory?"""
    cleaned = token.split("::", 1)[0].rstrip("/")
    cleaned = re.sub(r":\d+(?:[-,]\d+)*$", "", cleaned)
    if not cleaned:
        return False
    return (document.parent / cleaned).exists()


def _looks_like_a_package_path(document: Path, token: str) -> bool:
    """Is an unresolved package-relative token a REFERENCE or just prose?

    Only a token whose first segment names a real directory beside the document
    is treated as a claim about the tree — ``src/system/token.css`` in
    ``web/README.md`` is, ``ctx.holes()/2`` is not. Without that guard the
    widened check would report every prose slash in fifty documents.
    """
    head = token.split("/", 1)[0]
    if not head or head.startswith(("~", ".", "@")):
        return False
    return (document.parent / head).is_dir()


def _check_links(path: Path, problems: list[str], top_level: frozenset[str]) -> None:
    del top_level
    for lineno, line in _prose_lines(path):
        # An inline code span holds an example of markdown, not a link: the
        # specification explains that `![alt](src)` renders as its own
        # characters, and following that "link" would be following the sentence
        # rather than a reference.
        for target in _LINK_RE.findall(_CODE_RE.sub("", line)):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            anchor = ""
            relpath = target
            if "#" in target:
                relpath, _, anchor = target.partition("#")
            where = f"{path.relative_to(REPO_ROOT)}:{lineno}"
            if not relpath:
                resolved = path
            else:
                resolved = (path.parent / relpath).resolve()
                if not resolved.exists():
                    problems.append(f"{where}: link target does not exist: {target}")
                    continue
            if anchor and resolved.suffix == ".md":
                slugs, _ = _headings(resolved)
                if anchor not in slugs:
                    problems.append(f"{where}: no heading matches anchor #{anchor} in {relpath}")


def _check_code_paths(path: Path, problems: list[str], top_level: frozenset[str]) -> None:
    for lineno, line in _prose_lines(path):
        for token in _CODE_RE.findall(line):
            token = token.strip()
            where = f"{path.relative_to(REPO_ROOT)}:{lineno}"
            if _is_placeholder(token) or " " in token or token in FORWARD_REFERENCES:
                continue
            if "/" in token:
                head = token.split("/", 1)[0]
                if head not in top_level:
                    # J-mirrors-and-dx-33: a token whose first segment is not a
                    # repository top-level entry is not automatically prose. In a
                    # package README it is usually a path relative to the
                    # DOCUMENT's own directory (`src/system/tokens.css` in
                    # web/README.md), and refusing to resolve it is how a dead
                    # reference survived — the anchor exists to keep prose
                    # containing a slash out of the check, and skipping is the
                    # wrong fallback. Try the document's own directory first, as
                    # the link check and the document-name branch already do, and
                    # only then give up.
                    if _resolves_beside(path, token):
                        continue
                    if _looks_like_a_package_path(path, token):
                        problems.append(
                            f"{where}: path does not exist beside this document: {token}"
                        )
                    continue
                if not _resolves(token):
                    problems.append(f"{where}: repository path does not exist: {token}")
                continue
            if _DOCNAME_RE.match(token) and not (REPO_ROOT / token).exists():
                sibling = path.parent / token
                if not sibling.exists():
                    problems.append(f"{where}: document does not exist: {token}")


#: Shell-command fence languages. A ``yaml`` fence quoting a workflow is not a
#: command a reader types, so the command-form check does not read it.
_SHELL_FENCES: Final[frozenset[str]] = frozenset({"console", "sh", "shell", "bash", ""})

#: The broken invocation form (J-mirrors-and-dx-29), matched only where the line
#: is a COMMAND: an optional prompt, optional environment assignments, then
#: ``pnpm``. Prose inside a fenced tree diagram ("driven as `pnpm --dir web …`")
#: is describing the form, not teaching it.
_DIR_FORM_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?:\$\s*)?(?:[A-Z_][A-Z0-9_]*=\S+\s+)*pnpm\s+(?:--dir|-C)\b"
)

#: The same form written as an inline code span in PROSE, where the span is a
#: COMPLETE invocation — the flag, the package directory, and a script. That is
#: the discriminator between teaching the form and discussing it, and it is the
#: whole reason this check can exist at all: `CONTRIBUTING.md` and `README.md`
#: both spend a paragraph on why the flag is wrong, and both name it as
#: `pnpm --dir` / `pnpm --dir web` — a form, with nothing to run. A sentence
#: that hands the reader something runnable ("Gate G2 … `pnpm --dir agent test`
#: … exit 0") is the site that matters most, because it is the one a reader
#: copies, and it is invisible to the fenced-block scan above.
_INLINE_DIR_FORM_RE: Final[re.Pattern[str]] = re.compile(
    r"`\s*pnpm\s+(?:--dir|-C)\s+[\w./-]+\s+[\w:./-]+"
)

#: What makes the flag form safe in a block: corepack has been told which pnpm
#: to run, so the ``packageManager`` walk-up the flag does not move is moot.
_ACTIVATION = "corepack prepare"

#: Command blocks that keep the flag form, each with a written reason. The
#: repository's documented-exclusion standard again: an unexplained entry here
#: is the defect this check exists to catch.
COMMAND_FORM_EXCLUSIONS: Final[dict[str, str]] = {
    "PACKAGING.md": (
        "spec-owned; the edit is drafted in docs/audit-2026-09-04-janky.md's L9 "
        "handoff and lands in the single spec pass (J-mirrors-and-dx-29)"
    ),
    "web/test/fixtures/README.md": (
        "owned by the web lane (L7); the one-line edit is drafted in this lane's "
        "handoff (J-mirrors-and-dx-29)"
    ),
    "repo_conventions.md": (
        "spec-owned, and the audit's PRIMARY edit for this item; the exact "
        "replacement text for all six sites is drafted in docs/audit-2026-09-04-"
        "janky.md's L9 handoff and lands in the single spec pass "
        "(J-mirrors-and-dx-29). Self-clearing: a unit test asserts this document "
        "still HAS the defect, so the entry cannot outlive it"
    ),
    "mission_plan.md": (
        "spec-owned; two of its GATE DEFINITIONS are written in the flag form "
        "(Gate G2's agent commands, Gate G4's browser suite), which is the most "
        "authoritative site in the tree because it is the command a reader "
        "copies. Amendment drafted for the spec pass (J-mirrors-and-dx-29). "
        "Self-clearing, like the entry above"
    ),
    "agent/DESIGN.md": (
        "owned by the agent lane, not this one; line 267 lists Gate G2's two "
        "commands in the flag form. One-line edit, drafted in the L9 handoff "
        "(J-mirrors-and-dx-29). Self-clearing, like the entries above"
    ),
    "corpus/public_fixtures/workspace/README.md": (
        "the committed Gate G4 fixture's own README, owned by the fixture lane; "
        "line 11 names the e2e command in the flag form. Drafted in the L9 "
        "handoff (J-mirrors-and-dx-29). Self-clearing, like the entries above"
    ),
    "RELEASE_FACTS.md": (
        "a verbatim excerpt of .github/workflows/ci.yml, where the flag is safe: "
        "the stock lanes install pnpm with an action that honours the manifest "
        "field, and the one corepack lane activates the pin explicitly first"
    ),
}


def _check_command_forms(path: Path, problems: list[str]) -> None:
    """No governed command block teaches ``pnpm --dir`` (J-mirrors-and-dx-29).

    ``CONTRIBUTING.md`` and ``docs/install.md`` each spend a paragraph on why the
    flag does not carry the version pin: corepack resolves ``packageManager`` by
    walking up from the current directory, ``--dir`` does not move that search,
    and there is deliberately no root manifest. Four documents taught the flag
    form anyway — and nothing could have flagged it, because none of them was in
    this checker's set until J-mirrors-and-dx-33 widened it.

    A block that activates the pin first is fine, which is exactly what the one
    corepack CI lane does.
    """
    relative = path.relative_to(REPO_ROOT).as_posix()
    if relative in COMMAND_FORM_EXCLUSIONS:
        return
    fence = ""
    in_fence = False
    block: list[tuple[int, str]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if _FENCE_RE.match(line):
            if in_fence:
                _report_dir_form(relative, block, problems)
                block = []
            else:
                fence = line.strip().lstrip("`").strip().lower()
            in_fence = not in_fence
            continue
        if in_fence and fence in _SHELL_FENCES:
            block.append((lineno, line))
    if in_fence:
        _report_dir_form(relative, block, problems)
    for lineno, line in _prose_lines(path):
        if _ACTIVATION in line or not _INLINE_DIR_FORM_RE.search(line):
            continue
        problems.append(
            f"{relative}:{lineno}: prose prescribes `pnpm --dir`, which does not carry "
            "the version pin (CONTRIBUTING.md, 'pnpm: the pin'). Write the command as "
            "pnpm run from inside the package directory."
        )


def _report_dir_form(relative: str, block: list[tuple[int, str]], problems: list[str]) -> None:
    text = "\n".join(line for _, line in block)
    if _ACTIVATION in text:
        return
    for lineno, line in block:
        if _DIR_FORM_RE.search(line):
            problems.append(
                f"{relative}:{lineno}: command block teaches `pnpm --dir`, which does not "
                "carry the version pin (CONTRIBUTING.md, 'pnpm: the pin'). Run pnpm from "
                f"inside the package directory, or activate the pin first ({_ACTIVATION})."
            )


def _check_sections(path: Path, problems: list[str]) -> None:
    for lineno, line in _prose_lines(path):
        for doc, number in _SECTION_RE.findall(line):
            where = f"{path.relative_to(REPO_ROOT)}:{lineno}"
            target = REPO_ROOT / doc
            if not target.exists():
                target = path.parent / doc
            if not target.exists():
                problems.append(f"{where}: section reference into a missing document: {doc}")
                continue
            _, texts = _headings(target)
            numbers = {
                match.group(1)
                for match in (_NUMBERED_HEADING_RE.match(text) for text in texts)
                if match is not None
            }
            if number not in numbers:
                problems.append(f"{where}: {doc} has no section §{number}")


def _tracked_markdown() -> list[str]:
    """Every markdown file git tracks, or ``[]`` outside a checkout."""
    proc = subprocess.run(
        ["git", "ls-files", "-z", "--", "*.md"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return []
    return [name for name in proc.stdout.split("\0") if name]


def _documents() -> list[Path]:
    """The checked set, DISCOVERED rather than listed (J-mirrors-and-dx-33).

    Root markdown, everything under ``docs/`` and ``projectdocumentation/``, and
    every tracked README or design document — minus :data:`EXCLUDED_DOCS`.
    Discovery is the point: a hand-maintained list leaves a new document
    uncovered by default, which is how ``INTERFACE.md`` — the largest
    specification in the repository — was outside the check while the workflow
    file claimed "the docs build is the reference check".

    ``projectdocumentation/`` is discovered by its own prefix rather than by the
    ``named`` set below, which would have caught only its ``README.md`` and left
    every other file in the set unchecked — the same shape of gap this function
    exists to close.
    """
    #: Package documents that carry normative prose rather than fixture bytes.
    named = {"README.md", "DESIGN.md", "PUBLISHING.md", "STAGE2_DIGEST.md"}
    #: Directory trees checked in full.
    trees = {"docs", "projectdocumentation"}
    chosen: list[str] = []
    for name in _tracked_markdown():
        if name in EXCLUDED_DOCS:
            continue
        head, _, rest = name.partition("/")
        if not rest or head in trees or Path(name).name in named:
            chosen.append(name)
    return [REPO_ROOT / name for name in sorted(set(chosen)) if (REPO_ROOT / name).is_file()]


def check(documents: Iterable[Path]) -> list[str]:
    """Return every unresolved reference found in ``documents``, in file order."""
    top_level = _top_level_entries()
    problems: list[str] = []
    for path in documents:
        _check_links(path, problems, top_level)
        _check_code_paths(path, problems, top_level)
        _check_sections(path, problems)
        _check_command_forms(path, problems)
    # `mission_plan.md:646` says "CI checks the file's schema" about
    # `LEGAL-REVIEW.md`, and until PARTS_STORE.md §7.5's item 33 that sentence
    # described nothing. It is joined here rather than run as a second CI step so
    # that the claim becomes true on the run that already makes the docs claim
    # true. The file is absent by design in this checkout, so this contributes
    # nothing until Stage 7 lands it — and then contributes without an edit.
    problems.extend(legal_review_check.check_repository(REPO_ROOT))
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="docs_check", description=__doc__)
    parser.add_argument("--list", action="store_true", help="print the checked files and exit")
    args = parser.parse_args(argv)

    documents = _documents()
    if bool(args.list):
        for path in documents:
            print(path.relative_to(REPO_ROOT))
        return 0

    problems = check(documents)
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        print(f"\ndocs_check: {len(problems)} unresolved reference(s)", file=sys.stderr)
        return 1
    print(f"docs_check: {len(documents)} documents, all references resolve")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
