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

Placeholders are skipped by shape, not by allowlist: a path containing ``<``,
``*``, ``…`` or ``$`` is a template (``bench/results/<model>/<date>.json``), and
a path under ``.heph/`` is runtime state that exists in a user's project rather
than in this repository.

Usage::

    uv run python scripts/docs_check.py            # docs/ + root normative docs
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

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]

#: Root documents whose references are checked (the normative set plus README).
ROOT_DOCS: Final[tuple[str, ...]] = (
    "README.md",
    "CONTRIBUTING.md",
    "architecture.md",
    "script_contract.md",
    "tool_schema.md",
    "repo_conventions.md",
    "verification.md",
    "VALIDATION.md",
    "PACKAGING.md",
    "COMPARE.md",
    "ASSEMBLY.md",
    "INGEST.md",
    "EXTERNAL_EVAL.md",
    "mission_plan.md",
)

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
_PLACEHOLDER_CHARS: Final[str] = "<>*…$?"

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
        REPO_ROOT / head / "src" / rest,
    )
    return any(candidate.exists() for candidate in candidates)


def _is_placeholder(token: str) -> bool:
    if any(ch in token for ch in _PLACEHOLDER_CHARS):
        return True
    return token.startswith((".heph/", "~", "/", "http://", "https://"))


def _check_links(path: Path, problems: list[str], top_level: frozenset[str]) -> None:
    del top_level
    for lineno, line in _prose_lines(path):
        for target in _LINK_RE.findall(line):
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
                    continue
                if not _resolves(token):
                    problems.append(f"{where}: repository path does not exist: {token}")
                continue
            if _DOCNAME_RE.match(token) and not (REPO_ROOT / token).exists():
                sibling = path.parent / token
                if not sibling.exists():
                    problems.append(f"{where}: document does not exist: {token}")


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


def _documents() -> list[Path]:
    docs = [REPO_ROOT / name for name in ROOT_DOCS if (REPO_ROOT / name).is_file()]
    docs += sorted((REPO_ROOT / "docs").glob("*.md"))
    registries_guide = REPO_ROOT / "registries" / "PUBLISHING.md"
    if registries_guide.is_file():
        docs.append(registries_guide)
    return docs


def check(documents: Iterable[Path]) -> list[str]:
    """Return every unresolved reference found in ``documents``, in file order."""
    top_level = _top_level_entries()
    problems: list[str] = []
    for path in documents:
        _check_links(path, problems, top_level)
        _check_code_paths(path, problems, top_level)
        _check_sections(path, problems)
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
