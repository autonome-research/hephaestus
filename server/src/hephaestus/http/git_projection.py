# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""``server/http/git_projection.py`` — one narrow read-mostly view of the repo.

``INTERFACE.md`` §2.9. **NEW WORK**: no git machinery exists in ``core/`` or
``server/`` today; ``architecture.md`` §3.5 pins the semantics and nothing
implements them. This module shells to ``git`` in the project root with a
**fixed argv, never a shell string** — every argument below is a literal or a
validated identifier, and no user text reaches a shell.

* ``status --porcelain=v2`` → ``{dirty: [{path, part?, index, worktree}], clean,
  head, branch}``. Dirtiness is a fact about ``parts/*.py`` in the working tree.
* ``log --follow -- parts/<part>.py`` → the version list.
* ``diff`` between two revisions for one part, bounded to the ``text_result``
  caps (51200 bytes / 2000 lines) with an **explicit truncation marker**; never
  silently cut.
* ``tag -l``, and annotated tag creation (§13.2).

**Refusals, named:** no commit, push, checkout, reset, branch, stash, or merge
from the workspace. It can *see* history and *mark* a publication; it cannot
rewrite the human's repository. A dirty tree is reported, never cleaned. The
allowed verbs are enumerated in :data:`ALLOWED_SUBCOMMANDS` and
:func:`_git` refuses anything else *before* it spawns, so a future route cannot
reach a mutating verb by passing it through.

§13.1: ``.heph/journal/`` is gitignored and contributes nothing, so **dirtiness
is entirely disjoint from artifact and publication state** — a part can be clean
and unbuilt, or dirty and current. The two axes are reported separately and this
module knows nothing about the other one.

§13.2: ``POST /git/tag`` creates an **annotated tag on HEAD**. It warns without
blocking when the tree is dirty (the caller renders the warning), because a tag
on a dirty tree records a commit that is not what the user sees. Whether a human
may tag over a blocking termination-review finding is deliberately **not decided
in Stage 4/5** — no operator-waiver surface exists anywhere in the product, and
building one here would invent a governance mechanism ahead of its stage.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any, Final

from hephaestus.agent_bridge.limits import LIMITS

from .errors import HttpRefusal

__all__ = [
    "ALLOWED_SUBCOMMANDS",
    "DIFF_MAX_BYTES",
    "DIFF_MAX_LINES",
    "GitUnavailable",
    "git_diff",
    "git_log",
    "git_status",
    "git_tag_create",
    "git_tags",
    "is_work_tree",
]

#: The complete set of git verbs this module may run. Everything that could
#: rewrite the human's repository is absent **by enumeration**, and
#: :func:`_git` enforces the list rather than trusting its callers.
ALLOWED_SUBCOMMANDS: Final[frozenset[str]] = frozenset(
    {"rev-parse", "status", "log", "diff", "tag"}
)

#: §2.9: the diff is bounded to the ``text_result`` caps, from
#: ``schemas/bridge_limits.json`` — the same numbers every other bounded text
#: surface uses, not a second pair of literals.
DIFF_MAX_BYTES: Final[int] = int(LIMITS["text_result"]["max_bytes"])
DIFF_MAX_LINES: Final[int] = int(LIMITS["text_result"]["max_lines"])

#: A revision the caller may name. Deliberately narrow: hex shas, tags, and
#: branch-ish names. It exists to keep an argument that *looks* like an option
#: (``--upload-pack=…``) out of the argv, which a fixed argv alone does not stop.
_REVISION_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/\-]{0,199}$")

#: Tag names: the same shape, minus the ``..`` and trailing-lock forms git itself
#: rejects. Validated here so the refusal is ours and named.
_TAG_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/\-]{0,199}$")

_PART_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_LOG_FORMAT: Final[str] = "%H%x1f%h%x1f%s%x1f%aI%x1f%D"


class GitUnavailable(Exception):
    """The project root is not a git work tree, or ``git`` is not installed."""


def _git(root: Path, *args: str, check: bool = True) -> str:
    """Run one allowed git subcommand with a **fixed argv**; return stdout.

    ``shell=False`` is not enough on its own — the guard that matters is that
    ``args[0]`` is checked against :data:`ALLOWED_SUBCOMMANDS` here, so the
    module cannot grow a mutating verb by accident, and every other element is
    either a literal in this file or a value one of the validators above
    accepted.
    """
    if not args or args[0] not in ALLOWED_SUBCOMMANDS:
        raise HttpRefusal(
            403,
            "git_verb_refused",
            f"the workspace may not run 'git {args[0] if args else ''}'",
            data={"allowed": sorted(ALLOWED_SUBCOMMANDS)},
        )
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:  # pragma: no cover - git absent from the image
        raise GitUnavailable("git is not installed") from exc
    if check and completed.returncode != 0:
        raise HttpRefusal(
            400,
            "git_failed",
            completed.stderr.strip() or f"git {args[0]} failed",
            data={"argv": ["git", *args], "returncode": completed.returncode},
        )
    return completed.stdout


def is_work_tree(root: Path) -> bool:
    """Whether ``root`` is inside a git work tree (drives ``capabilities.git``)."""
    try:
        out = _git(root, "rev-parse", "--is-inside-work-tree", check=False)
    except GitUnavailable:
        return False
    return out.strip() == "true"


def _require_work_tree(root: Path) -> None:
    if not is_work_tree(root):
        raise HttpRefusal(404, "not_a_git_repository", f"{root} is not inside a git work tree")


def git_status(root: Path) -> dict[str, Any]:
    """``GET /git/status`` — ``{dirty[], clean, head, branch}`` (§13.1).

    Parsed from ``--porcelain=v2 --branch``, whose format is stable and
    machine-first (the v1 short format is explicitly not). ``part`` is filled
    only for a path under ``parts/`` ending in ``.py``, because that is what
    §13.1 says dirtiness is a fact *about*; an edit to ``globals.py`` is dirty
    and simply has no part.
    """
    _require_work_tree(root)
    raw = _git(root, "status", "--porcelain=v2", "--branch", "--untracked-files=all")
    dirty: list[dict[str, Any]] = []
    head: str | None = None
    branch: str | None = None
    for line in raw.splitlines():
        if line.startswith("# branch.oid "):
            head = line[len("# branch.oid ") :].strip()
            continue
        if line.startswith("# branch.head "):
            branch = line[len("# branch.head ") :].strip()
            continue
        entry = _porcelain_entry(line)
        if entry is not None:
            dirty.append(entry)
    dirty.sort(key=lambda row: str(row["path"]))
    return {
        "status": "ok",
        "dirty": dirty,
        "clean": not dirty,
        "head": None if head in (None, "(initial)") else head,
        "branch": branch,
    }


def _porcelain_entry(line: str) -> dict[str, Any] | None:
    """One ``--porcelain=v2`` record → a dirty row, or ``None`` for a header."""
    if not line or line.startswith("#"):
        return None
    code = line[0]
    if code == "1":
        # 1 <XY> <sub> <mH> <mI> <mW> <hH> <hI> <path>
        fields = line.split(" ", 8)
        if len(fields) < 9:
            return None
        xy, path = fields[1], fields[8]
        index, worktree = xy[0], xy[1]
    elif code == "2":
        # 2 <XY> <sub> <mH> <mI> <mW> <hH> <hI> <X><score> <path><sep><origPath>
        #
        # One field MORE than a "1" record (the rename score), and its path field
        # carries the original path after a tab. Parsing it with "1"'s field count
        # yields "R100 parts/x.py" as the path — a row that names no part and
        # matches no file, which is exactly the kind of quiet wrongness a dirty
        # marker must not have.
        fields = line.split(" ", 9)
        if len(fields) < 10:
            return None
        xy, path = fields[1], fields[9].split("\t", 1)[0]
        index, worktree = xy[0], xy[1]
    elif code == "u":
        fields = line.split(" ", 10)
        if len(fields) < 11:
            return None
        xy, path = fields[1], fields[10]
        index, worktree = xy[0], xy[1]
    elif code == "?":
        path = line[2:]
        index, worktree = ".", "?"
    else:
        return None
    row: dict[str, Any] = {"path": path, "index": index, "worktree": worktree}
    part = _part_of(path)
    if part is not None:
        row["part"] = part
    return row


def _part_of(path: str) -> str | None:
    """``parts/<name>.py`` → ``<name>``; anything else → ``None`` (§13.1)."""
    if not path.startswith("parts/") or not path.endswith(".py"):
        return None
    stem = path[len("parts/") : -len(".py")]
    return stem if _PART_RE.match(stem) else None


def git_log(root: Path, part: str | None = None) -> dict[str, Any]:
    """``GET /git/log?part=`` — ``[{sha, short, subject, author_date, tags[]}]``.

    ``--follow`` is used for a named part so a rename does not truncate its
    history. It is a per-file option and git refuses it without a pathspec, so
    the project-wide listing simply does not pass it.
    """
    _require_work_tree(root)
    args = ["log", f"--format={_LOG_FORMAT}", "--date-order"]
    if part is not None:
        _require_part(part)
        args += ["--follow", "--", f"parts/{part}.py"]
    raw = _git(root, *args, check=False)
    commits: list[dict[str, Any]] = []
    for line in raw.splitlines():
        fields = line.split("\x1f")
        if len(fields) != 5:
            continue
        sha, short, subject, author_date, decoration = fields
        commits.append(
            {
                "sha": sha,
                "short": short,
                "subject": subject,
                "author_date": author_date,
                "tags": _tags_from_decoration(decoration),
            }
        )
    return {"status": "ok", "commits": commits}


def _tags_from_decoration(decoration: str) -> list[str]:
    """``%D`` → the tag names on that commit (refs that are not tags dropped)."""
    tags: list[str] = []
    for item in decoration.split(", "):
        item = item.strip()
        if item.startswith("tag: "):
            tags.append(item[len("tag: ") :])
    return tags


def git_diff(root: Path, *, part: str, from_rev: str, to_rev: str | None = None) -> dict[str, Any]:
    """``GET /git/diff?part=&from=&to=`` — a bounded unified diff for one part.

    Bounded to the ``text_result`` caps and **never silently cut**: when the diff
    exceeds either cap the body is truncated at a line boundary and the result
    carries ``truncated: true`` with both counts, so a reader can tell a short
    diff from a shortened one. ``to`` defaults to the working tree, which is the
    view the dirty markers are about.
    """
    _require_work_tree(root)
    _require_part(part)
    _require_revision(from_rev, "from")
    args = ["diff", from_rev]
    if to_rev is not None:
        _require_revision(to_rev, "to")
        args.append(to_rev)
    args += ["--", f"parts/{part}.py"]
    raw = _git(root, *args)
    return _bounded_text(raw)


def _bounded_text(raw: str) -> dict[str, Any]:
    lines = raw.splitlines(keepends=True)
    truncated = False
    if len(lines) > DIFF_MAX_LINES:
        lines = lines[:DIFF_MAX_LINES]
        truncated = True
    text = "".join(lines)
    encoded = text.encode("utf-8")
    if len(encoded) > DIFF_MAX_BYTES:
        # Cut at a line boundary inside the byte cap so the marker never lands
        # mid-hunk; a diff sliced mid-line reads as a diff with a corrupt hunk.
        kept: list[str] = []
        size = 0
        for line in lines:
            step = len(line.encode("utf-8"))
            if size + step > DIFF_MAX_BYTES:
                break
            kept.append(line)
            size += step
        text = "".join(kept)
        truncated = True
    return {
        "status": "ok",
        "diff": text,
        "truncated": truncated,
        "total_bytes": len(raw.encode("utf-8")),
        "total_lines": raw.count("\n"),
        "max_bytes": DIFF_MAX_BYTES,
        "max_lines": DIFF_MAX_LINES,
    }


def git_tags(root: Path) -> dict[str, Any]:
    """``GET /git/tags`` — the ``git tag -l`` projection."""
    _require_work_tree(root)
    fmt = "%(refname:short)%09%(objectname:short)%09%(contents:subject)"
    raw = _git(root, "tag", "-l", "--sort=-creatordate", f"--format={fmt}")
    tags: list[dict[str, Any]] = []
    for line in raw.splitlines():
        fields = line.split("\t")
        if not fields[0]:
            continue
        tags.append(
            {
                "name": fields[0],
                "object": fields[1] if len(fields) > 1 else "",
                "subject": fields[2] if len(fields) > 2 else "",
            }
        )
    return {"status": "ok", "tags": tags}


def git_tag_create(root: Path, *, name: str, message: str) -> dict[str, Any]:
    """``POST /git/tag`` — an **annotated** tag on HEAD (§13.2, "Tag release").

    Annotated and not lightweight: a release marker that carries no author,
    date, or message is not a record of anything. The dirty set rides back in
    the result so the caller can *warn without blocking* — a tag on a dirty tree
    records a commit that is not what the user sees, which is worth saying and
    is not the workspace's decision to veto.

    This is the one git write the workspace has, and the enumeration in
    :data:`ALLOWED_SUBCOMMANDS` is what keeps it the only one.
    """
    _require_work_tree(root)
    if not _TAG_RE.match(name):
        raise HttpRefusal(400, "invalid_params", f"invalid tag name {name!r}")
    if not message.strip():
        raise HttpRefusal(400, "invalid_params", "an annotated tag requires a message")
    status = git_status(root)
    head = _git(root, "rev-parse", "HEAD").strip()
    _git(root, "tag", "-a", name, "-m", message)
    return {
        "status": "ok",
        "tag": name,
        "head": head,
        "message": message,
        "dirty": status["dirty"],
        "dirty_warning": not status["clean"],
    }


def _require_part(part: str) -> None:
    if not _PART_RE.match(part):
        raise HttpRefusal(400, "invalid_part", f"invalid part name {part!r}")


def _require_revision(rev: str, label: str) -> None:
    if not _REVISION_RE.match(rev):
        raise HttpRefusal(400, "invalid_params", f"invalid {label} revision {rev!r}")
