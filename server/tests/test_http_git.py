# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""§2.9's git projection: it can see history and mark a publication, nothing else.

``INTERFACE.md`` §2.9, §13.1, §13.2. **NEW WORK**: no git machinery exists in
``core/`` or ``server/``; ``architecture.md`` §3.5 pins the semantics and nothing
implemented them. The refusals are the load-bearing part — *no commit, push,
checkout, reset, branch, stash, or merge from the workspace* — so they are
enumerated and tested rather than described.

§13.1's separation matters as much as the parsing: ``.heph/journal/`` is
gitignored and contributes nothing, so **dirtiness is entirely disjoint from
artifact and publication state**. A part can be clean and unbuilt, or dirty and
current, and the two axes never blur.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import cast

import pytest
from hephaestus.http.git_projection import (
    ALLOWED_SUBCOMMANDS,
    DIFF_MAX_BYTES,
    DIFF_MAX_LINES,
)
from hephaestus.testing.workspace import Workspace, uuid7, workspace


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Iterator[Workspace]:
    """A fixture project that is also a git repository with one commit."""
    root = tmp_path / "proj"
    with workspace(root) as web:
        _git(root, "init", "-q")
        _git(root, "config", "user.email", "test@example.invalid")
        _git(root, "config", "user.name", "test")
        (root / ".gitignore").write_text(".heph/\n", encoding="utf-8")
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", "initial")
        yield web


def test_the_allowed_verb_set_excludes_every_way_to_rewrite_the_repository() -> None:
    """§2.9's refusals, as an enumeration the module enforces before it spawns.

    ``shell=False`` alone would not stop a future route from passing ``"reset"``
    through; the allow-list is what does, and it is checked *before* the process
    is created rather than after.
    """
    assert {"rev-parse", "status", "log", "diff", "tag"} == ALLOWED_SUBCOMMANDS
    for forbidden in ("commit", "push", "checkout", "reset", "branch", "stash", "merge", "clean"):
        assert forbidden not in ALLOWED_SUBCOMMANDS


def test_a_refused_verb_never_reaches_a_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    """The refusal is *before* the spawn, not a check on the result."""
    from hephaestus.http import git_projection
    from hephaestus.http.errors import HttpRefusal

    def explode(*_: object, **__: object) -> None:
        raise AssertionError("a refused verb must never reach subprocess.run")

    # Reaching for the module-private runner is the point: the guard has to be
    # provable at the one function every route funnels through, not only at the
    # routes that happen to exist today.
    run_git = cast(
        "Callable[..., str]",
        getattr(git_projection, "_git"),  # noqa: B009
    )
    monkeypatch.setattr(subprocess, "run", explode)
    with pytest.raises(HttpRefusal) as caught:
        run_git(Path("/tmp"), "reset", "--hard")
    assert caught.value.reason == "git_verb_refused"
    assert caught.value.status == 403


def test_status_reports_a_clean_tree_with_head_and_branch(repo: Workspace) -> None:
    """§13.1: ``{dirty[], clean, head, branch}``, parsed from ``--porcelain=v2``."""
    body = repo.get("/git/status").json()
    assert body["clean"] is True
    assert body["dirty"] == []
    assert len(str(body["head"])) == 40
    assert body["branch"]


def test_dirtiness_names_the_part_for_a_parts_script_and_not_otherwise(
    repo: Workspace,
) -> None:
    """§13.1: dirtiness is a fact about ``parts/*.py`` in the working tree.

    An edit to ``globals.py`` is dirty and simply has **no part** — the row is
    still reported, because a dirty tree is reported and never hidden, but it
    carries no part attribution it cannot justify.
    """
    (repo.root / "parts" / "widget.py").write_text("part.geometry = Box(1, 1, 1)\n", "utf-8")
    (repo.root / "globals.py").write_text("PARAMS = {}\n", encoding="utf-8")
    rows = {row["path"]: row for row in repo.get("/git/status").json()["dirty"]}
    assert rows["parts/widget.py"]["part"] == "widget"
    assert "part" not in rows["globals.py"]


def test_dirtiness_is_disjoint_from_publication_state(repo: Workspace) -> None:
    """§13.1: the header shows the artifact axis; the rail shows the git axis.

    A part that is **current** (built and published) is still **clean** if its
    script is committed, because ``.heph/`` is gitignored and contributes
    nothing. The workspace must never blur the two, and the server must never
    give it the chance.
    """
    assert repo.post("/parts/widget/build", json={}, key=uuid7()).status_code == 200
    assert repo.get("/parts/widget/build").json()["current"] is True
    assert repo.get("/git/status").json()["clean"] is True


def test_log_follows_one_part_and_reports_its_tags(repo: Workspace) -> None:
    """``log --follow -- parts/<part>.py`` → the version list."""
    (repo.root / "parts" / "widget.py").write_text("part.geometry = Box(2, 2, 2)\n", "utf-8")
    _git(repo.root, "add", "-A")
    _git(repo.root, "commit", "-q", "-m", "widen the widget")
    _git(repo.root, "tag", "-a", "v0.1.0", "-m", "first")

    commits = repo.get("/git/log", params={"part": "widget"}).json()["commits"]
    assert [c["subject"] for c in commits] == ["widen the widget", "initial"]
    assert commits[0]["tags"] == ["v0.1.0"]
    assert len(commits[0]["sha"]) == 40


def test_log_for_an_invalid_part_name_is_refused(repo: Workspace) -> None:
    """A part name is validated before it becomes a pathspec."""
    response = repo.get("/git/log", params={"part": "../../etc/passwd"})
    assert response.status_code == 400
    assert response.json()["reason"] == "invalid_part"


def test_diff_is_bounded_to_the_text_result_caps_and_marks_truncation(
    repo: Workspace,
) -> None:
    """§2.9: bounded to 51200 bytes / 2000 lines, **never silently cut**.

    ``truncated`` plus both totals, so a reader can tell a short diff from a
    shortened one. The caps come from ``schemas/bridge_limits.json`` — the same
    numbers every other bounded text surface uses, not a second pair of literals.
    """
    assert (DIFF_MAX_BYTES, DIFF_MAX_LINES) == (51200, 2000)
    head = _git(repo.root, "rev-parse", "HEAD").strip()
    (repo.root / "parts" / "widget.py").write_text(
        "".join(f"# line {n}\n" for n in range(DIFF_MAX_LINES + 500)), encoding="utf-8"
    )
    body = repo.get("/git/diff", params={"part": "widget", "from": head}).json()
    assert body["truncated"] is True
    assert body["diff"].count("\n") <= DIFF_MAX_LINES
    assert len(body["diff"].encode("utf-8")) <= DIFF_MAX_BYTES
    assert body["total_lines"] > DIFF_MAX_LINES
    assert body["diff"].endswith("\n")  # cut at a line boundary, never mid-hunk


def test_a_small_diff_is_not_marked_truncated(repo: Workspace) -> None:
    """The marker means something only if it is absent when nothing was cut."""
    head = _git(repo.root, "rev-parse", "HEAD").strip()
    (repo.root / "parts" / "widget.py").write_text("part.geometry = Box(3, 3, 3)\n", "utf-8")
    body = repo.get("/git/diff", params={"part": "widget", "from": head}).json()
    assert body["truncated"] is False
    assert "Box(3, 3, 3)" in body["diff"]


def test_a_revision_that_looks_like_an_option_is_refused(repo: Workspace) -> None:
    """A fixed argv is not enough on its own; the revision is validated too.

    ``--upload-pack=…`` in a revision slot is an argument that *looks* like an
    option, which a fixed argv happily forwards. The validator is what stops it.
    """
    response = repo.get("/git/diff", params={"part": "widget", "from": "--upload-pack=/bin/sh"})
    assert response.status_code == 400
    assert response.json()["reason"] == "invalid_params"


def test_tag_creates_an_annotated_tag_on_head(repo: Workspace) -> None:
    """§13.2: "Tag release" is annotated — a marker with an author and a message.

    A lightweight tag carries no author, date, or message and is therefore not a
    record of anything.
    """
    response = repo.post(
        "/git/tag", json={"name": "v1.0.0", "message": "the first release"}, key=uuid7()
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["tag"] == "v1.0.0"
    assert body["dirty_warning"] is False
    assert _git(repo.root, "cat-file", "-t", "v1.0.0").strip() == "tag"  # annotated, not commit
    assert body["head"] == _git(repo.root, "rev-parse", "HEAD").strip()


def test_tag_warns_without_blocking_on_a_dirty_tree(repo: Workspace) -> None:
    """§13.2: **warns without blocking**.

    A tag on a dirty tree records a commit that is not what the user sees, which
    is worth saying — and is not the workspace's decision to veto. The dirty set
    rides back so the dialog can show exactly what is uncommitted.
    """
    (repo.root / "parts" / "widget.py").write_text("part.geometry = Box(4, 4, 4)\n", "utf-8")
    body = repo.post(
        "/git/tag", json={"name": "v1.1.0", "message": "on a dirty tree"}, key=uuid7()
    ).json()
    assert body["status"] == "ok"
    assert body["dirty_warning"] is True
    assert any(row["path"] == "parts/widget.py" for row in body["dirty"])


def test_tags_lists_what_git_tag_l_reports(repo: Workspace) -> None:
    """``GET /git/tags`` — the ``git tag -l`` projection."""
    created = repo.post("/git/tag", json={"name": "v2.0.0", "message": "two"}, key=uuid7())
    assert created.status_code == 200, created.text
    tags = repo.get("/git/tags").json()["tags"]
    assert [t["name"] for t in tags] == ["v2.0.0"]
    assert tags[0]["subject"] == "two"


def test_an_invalid_tag_name_or_empty_message_is_refused(repo: Workspace) -> None:
    """An annotated tag needs a name git accepts and a message worth recording."""
    bad_name = repo.post("/git/tag", json={"name": "-x", "message": "m"}, key=uuid7())
    assert bad_name.status_code == 400
    assert bad_name.json()["reason"] == "invalid_params"
    blank = repo.post("/git/tag", json={"name": "v3", "message": "   "}, key=uuid7())
    assert blank.status_code == 400


def test_a_project_that_is_not_a_git_work_tree_says_so(tmp_path: Path) -> None:
    """The git axis is a *capability*, and its absence is named, not empty.

    ``capabilities.git`` is false and the routes refuse, so the Versions panel is
    **absent** rather than showing an empty history that would read as "no
    commits yet".
    """
    with workspace(tmp_path / "proj") as web:
        assert web.get("/project").json()["capabilities"]["git"] is False
        response = web.get("/git/status")
    assert response.status_code == 404
    assert response.json()["reason"] == "not_a_git_repository"


def test_git_capability_is_true_inside_a_work_tree(repo: Workspace) -> None:
    """The other direction, so the capability is not a constant."""
    assert repo.get("/project").json()["capabilities"]["git"] is True


def test_a_renamed_part_is_parsed_from_the_rename_record(repo: Workspace) -> None:
    """``--porcelain=v2`` rename records carry one extra field and a tab.

    A ``2`` record is ``... <X><score> <path><sep><origPath>``: one field more
    than a ``1`` record, and its path field holds the *new* path followed by a
    tab and the original. Parsing it with the ordinary field count yields
    ``"R100 parts/renamed.py"`` — a row naming no part and matching no file,
    which is precisely the quiet wrongness a dirty marker must never have.
    """
    _git(repo.root, "mv", "parts/widget.py", "parts/renamed.py")
    rows = {row["path"]: row for row in repo.get("/git/status").json()["dirty"]}
    assert "parts/renamed.py" in rows, rows
    assert rows["parts/renamed.py"]["part"] == "renamed"
    assert not any(path.startswith("R") for path in rows)
