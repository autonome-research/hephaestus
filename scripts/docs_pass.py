#!/usr/bin/env python3
# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Plan a ``projectdocumentation/`` maintenance pass.

Reads the ``Verified against <commit>`` stamp every document in
``projectdocumentation/`` carries, finds the oldest one, and reports what has
changed in the tree since — mapped to the documents that describe it.

**It reports; it never edits.** Updating a document means re-running the checks
that produced its claims (``projectdocumentation/06-operations/verification-runbook.md``),
and a tool that moved a stamp without re-verifying would be manufacturing exactly
the false confidence the stamp exists to prevent.

Usage::

    uv run python scripts/docs_pass.py            # plan a pass from the oldest stamp
    uv run python scripts/docs_pass.py --since HEAD~20
    uv run python scripts/docs_pass.py --stamps   # just print the stamps

Exit codes: ``0`` nothing to do, ``1`` a pass is due, ``2`` the tree is
unreadable (not a git checkout, no documents, an unstamped document).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOC_ROOT = REPO_ROOT / "projectdocumentation"

#: The stamp every document carries, on its own line near the top.
STAMP_RE = re.compile(r"^>\s*\*\*Verified against\*\*\s*`([0-9a-f]{7,40})`", re.MULTILINE)

#: Changed path prefix -> the documents that describe it. Ordered; the first
#: matching prefix wins, and a path matching nothing lands in "unmapped", which
#: is reported rather than silently dropped — an unmapped path is either a new
#: subsystem or a gap in this table, and both want a human.
ROUTES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("core/src/hephaestus/core/cli", ("04-reference/cli.md", "02-tutorial/your-first-part.md")),
    ("core/src/hephaestus/core/executor", ("05-architecture/building-blocks.md",)),
    ("core/src/hephaestus/core/checks", ("05-architecture/runtime-view.md",)),
    ("core/src/hephaestus/core/project_store", ("04-reference/data-model.md",)),
    ("core/src", ("05-architecture/building-blocks.md",)),
    ("opstore/src", ("04-reference/data-model.md",)),
    ("server/src/hephaestus/http", ("04-reference/http-api.md",)),
    (
        "server/src/hephaestus/agent_bridge",
        ("04-reference/bridge-protocol.md", "04-reference/agent-tools.md"),
    ),
    ("server/src/hephaestus/mcp", ("04-reference/agent-tools.md",)),
    ("contract/src", ("04-reference/agent-tools.md",)),
    ("agent/src", ("04-reference/bridge-protocol.md", "03-how-to/work-on-the-sidecar.md")),
    ("web/src", ("04-reference/web-client.md",)),
    ("bench/src", ("05-architecture/quality-and-risks.md",)),
    ("schemas/", ("04-reference/limits-and-configuration.md", "04-reference/agent-tools.md")),
    (".github/workflows", ("05-architecture/deployment-view.md", "03-how-to/run-the-tests.md")),
    ("scripts/", ("03-how-to/run-the-tests.md", "06-operations/documentation-maintenance.md")),
    ("packaging/", ("03-how-to/release-and-package.md",)),
    ("pyproject.toml", ("03-how-to/run-the-tests.md",)),
)

#: Enumerations that must be re-derived whenever anything they count moves.
ENUMERATION_CHECKS: tuple[tuple[str, str], ...] = (
    ("CLI verbs", "uv run heph --help"),
    ("agent tools", "ls schemas/tools/ | wc -l"),
    ("bridge limits", "cat schemas/bridge_limits.json"),
    (
        "HTTP routes",
        "uv run python -c 'from hephaestus.http.app import ROUTE_TABLE;print(len(ROUTE_TABLE))'",
    ),
    (
        "HTTP reasons",
        "uv run python -c 'from hephaestus.http.errors import REASON_STATUS;"
        "print(len(REASON_STATUS))'",
    ),
    ("references", "uv run python scripts/docs_check.py"),
)


def _git(*args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        raise SystemExit(f"docs_pass: git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def stamps() -> dict[Path, str]:
    """Every document's stamped commit, keyed by path relative to the doc root."""
    found: dict[Path, str] = {}
    unstamped: list[Path] = []
    for path in sorted(DOC_ROOT.rglob("*.md")):
        match = STAMP_RE.search(path.read_text(encoding="utf-8"))
        if match is None:
            unstamped.append(path.relative_to(REPO_ROOT))
        else:
            found[path.relative_to(DOC_ROOT)] = match.group(1)
    if unstamped:
        names = "\n  ".join(str(p) for p in unstamped)
        raise SystemExit(f"docs_pass: document(s) with no `Verified against` stamp:\n  {names}")
    if not found:
        raise SystemExit(f"docs_pass: no documents under {DOC_ROOT}")
    return found


def oldest(found: dict[Path, str]) -> tuple[str, list[Path]]:
    """The stamp furthest back in history, and every document carrying it."""
    order = _git("rev-list", "--topo-order", "HEAD").split()
    rank = {sha: i for i, sha in enumerate(order)}

    def depth(short: str) -> int:
        full = _git("rev-parse", short).strip()
        if full not in rank:
            raise SystemExit(f"docs_pass: stamp {short} is not an ancestor of HEAD")
        return rank[full]

    worst = max(set(found.values()), key=depth)
    return worst, sorted(p for p, sha in found.items() if sha == worst)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="docs_pass", description="Plan a documentation pass.")
    parser.add_argument("--since", help="diff from this ref instead of the oldest stamp")
    parser.add_argument("--stamps", action="store_true", help="print every stamp and exit")
    args = parser.parse_args(argv)

    found = stamps()
    if args.stamps:
        for path, sha in sorted(found.items(), key=lambda kv: (kv[1], str(kv[0]))):
            print(f"{sha}  {path}")
        return 0

    base, behind = (args.since, []) if args.since else oldest(found)
    head = _git("rev-parse", "--short", "HEAD").strip()
    if _git("rev-parse", base).strip() == _git("rev-parse", "HEAD").strip():
        print(f"docs_pass: every document is stamped at HEAD ({head}); nothing to do.")
        return 0

    log = _git("log", "--oneline", f"{base}..HEAD").strip()
    changed = sorted(set(_git("diff", "--name-only", f"{base}..HEAD").split()))
    changed = [p for p in changed if not p.startswith("projectdocumentation/")]

    print(f"docs_pass: {len(log.splitlines())} commit(s) since {base} (HEAD is {head})\n")
    if behind:
        print("Documents stamped at that commit:")
        for path in behind:
            print(f"  {path}")
        print()

    if not changed:
        # A documentation-only range needs no pass: there is nothing new to
        # verify against. The stamps stay where they are, which is why the
        # oldest one can legitimately sit behind HEAD.
        print("Only projectdocumentation/ changed in this range; no pass is due.")
        return 0

    hits: dict[str, list[str]] = {}
    unmapped: list[str] = []
    for path in changed:
        for prefix, docs in ROUTES:
            if path.startswith(prefix):
                for doc in docs:
                    hits.setdefault(doc, []).append(path)
                break
        else:
            unmapped.append(path)

    print(f"{len(changed)} changed path(s) map to {len(hits)} document(s):\n")
    for doc in sorted(hits):
        paths = hits[doc]
        print(f"  {doc}")
        for path in paths[:6]:
            print(f"      {path}")
        if len(paths) > 6:
            print(f"      … and {len(paths) - 6} more")
    if unmapped:
        print(f"\n{len(unmapped)} changed path(s) matched no route — decide by hand:")
        for path in unmapped[:20]:
            print(f"  {path}")
        if len(unmapped) > 20:
            print(f"  … and {len(unmapped) - 20} more")

    print("\nRe-derive the enumerations before editing anything:")
    for label, command in ENUMERATION_CHECKS:
        print(f"  {label:<14} {command}")

    print(
        "\nThen: re-run each affected document's own checks (see "
        "projectdocumentation/06-operations/verification-runbook.md), edit, move "
        f"each re-verified stamp to {head}, and commit as one `docs:` commit.\n"
        "A document you did NOT re-check keeps its old stamp. That is the signal."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
