# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""J-http-limits-5: the materialized workspace fixture must not commit its
build store — or, worse, a live bearer token.

``materialize_workspace_fixture`` (``server/src/hephaestus/testing/workspace_fixture.py``)
copies the committed fixture, replays requirements through the production
writer, replays the transcript, and THEN runs ``git init && git add -A && git
commit``. Two of those middle steps (``record_requirements``,
``install_transcript``) open the opstore, which creates ``.heph/`` — the
project's gitignored-repository-wide build store — before the commit ever
runs. The materialiser writes no ``.gitignore`` of its own (unlike
``heph init``'s scaffolder), so ``git add -A`` picks up everything the store
just wrote, including a signing key, the state database, and — on a checkout
that has ever served the fixture — a live serve bearer token, and commits it
all into the fixture's own git history.

These tests exercise :func:`materialize_workspace_fixture` directly (a
real, if minimal, materialisation — the transcript half is skipped, since it
needs a built sidecar and is orthogonal to what gets committed) and assert
the fixed shape: an ignore file matching the scaffolder's own constant, no
tracked path inside the build store, no serve token anywhere, and a clean
``git status`` after one further runtime open and close.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from hephaestus.core.cli_init import GITIGNORE
from hephaestus.testing.workspace import WORKSPACE_TOKEN, WorkspaceRuntime


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
        env={
            "PATH": "/usr/bin:/bin",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "HOME": str(root),
        },
    )
    return proc.stdout


@pytest.fixture
def materialized(tmp_path: Path) -> Path:
    from hephaestus.testing.workspace_fixture import materialize_workspace_fixture

    root = tmp_path / "workspace"
    # transcript=False: the transcript replay needs a built sidecar and is
    # irrelevant to what this test is about — whether the BUILD STORE ends up
    # committed. record_requirements() (which does not need a sidecar) still
    # runs, and it is enough on its own to create `.heph/` before the commit
    # (the exact ordering this item's root cause names).
    materialize_workspace_fixture(root, transcript=False)
    return root


def test_the_materialised_fixture_carries_the_scaffolders_own_ignore_file(
    materialized: Path,
) -> None:
    """Written by IMPORTING the scaffolder's constant, never restating it, so
    the fixture and `heph init` cannot silently disagree about what the build
    store is called."""
    ignore = materialized / ".gitignore"
    assert ignore.is_file(), (
        "materialize_workspace_fixture wrote no .gitignore — unlike heph init's "
        "scaffolder, this is the one project in the repository built by a "
        "second, divergent scaffolder"
    )
    assert ignore.read_text(encoding="utf-8") == GITIGNORE, (
        "the fixture's .gitignore does not match hephaestus.core.cli_init.GITIGNORE "
        "— it must be written by importing the constant, not restating its text"
    )


def test_no_tracked_path_is_inside_the_build_store(materialized: Path) -> None:
    tracked = _git(materialized, "ls-files").splitlines()
    assert tracked, "the fixture commit tracks no files at all — materialisation is broken"
    in_store = [p for p in tracked if p == ".heph" or p.startswith(".heph/")]
    assert not in_store, (
        f"these tracked paths are inside the gitignored build store: {in_store}. "
        "record_requirements()/install_transcript() create .heph/ before the "
        "commit; the ignore file must be written and `git add` run BEFORE (or "
        "with `.heph/` excluded from) those steps."
    )


def test_no_serve_token_exists_anywhere_under_the_materialised_root(
    materialized: Path,
) -> None:
    """The specific, worst-case instance: a live bearer written into a git
    object. Checked against the filesystem, not just `git ls-files` — an
    untracked-but-present token would still be the "developer's stale store"
    case the fix's own notes say is acceptable, so this only fails if one
    exists AT ALL right after a fresh materialisation, which it should not:
    nothing in `materialize_workspace_fixture` serves the project."""
    tokens = list(materialized.rglob("serve.token"))
    assert not tokens, f"a serve token exists on a freshly materialised fixture: {tokens}"


def test_a_stray_build_store_in_the_committed_fixture_source_is_never_copied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exact reproduction this item names: "the fixture materialiser copies
    whatever build store the developer's checkout happens to hold". A real
    checkout's `corpus/public_fixtures/workspace/` is gitignore-exempt from
    tracking `.heph/` but NOT exempt from physically holding one, left behind
    by a prior `heph serve`/build against that exact directory — this
    checkout's own `corpus/public_fixtures/workspace/.heph/` is untracked but
    present right now, which is precisely the hazard. Rather than depend on
    (or mutate) the real, shared fixture source, this plants the same shape in
    a private copy and points the materialiser at it via
    :func:`hephaestus.testing.workspace_fixture.fixture_source`, so the
    assertion is deterministic regardless of what this checkout happens to
    hold today.
    """
    import hephaestus.testing.workspace_fixture as wf

    real_source = wf.fixture_source()
    stray_source = tmp_path / "stray-source"
    import shutil as _shutil

    _shutil.copytree(real_source, stray_source)
    store = stray_source / ".heph"
    store.mkdir(exist_ok=True)
    (store / "serve.token").write_text("super-secret-bearer\n", encoding="utf-8")
    (store / "state.db").write_bytes(b"not a real sqlite file, just a stand-in\n")

    monkeypatch.setattr(wf, "fixture_source", lambda: stray_source)
    dest = tmp_path / "materialised-from-stray"
    wf.materialize_workspace_fixture(dest, transcript=False)

    assert not (dest / ".heph" / "serve.token").exists(), (
        "the stray source's serve token was copied verbatim into the materialised "
        "fixture — a live bearer, physically present, byte-identical to the source"
    )
    tracked = _git(dest, "ls-files").splitlines()
    assert not any(p.startswith(".heph/") for p in tracked), (
        "the stray source's build store was committed into the fixture's own git history"
    )


def test_git_status_is_clean_after_one_runtime_open_and_close(materialized: Path) -> None:
    """Ties the fixture to the workspace's own dirty-marker clause (§13.1): a
    project that has merely been opened and closed — no edits — must show no
    dirty build-store entries, which is only true if the store stays
    gitignored through real runtime activity, not just at commit time."""
    before = _git(materialized, "status", "--porcelain")
    assert before == "", f"the fixture is dirty immediately after materialisation:\n{before}"

    runtime = WorkspaceRuntime.open(materialized, token=WORKSPACE_TOKEN, serve_mode=False)
    runtime.close()

    after = _git(materialized, "status", "--porcelain")
    assert after == "", (
        f"git status is dirty after a plain runtime open+close:\n{after}\n"
        "— the build store the runtime touched is not fully covered by .gitignore"
    )


def test_the_ignore_string_has_exactly_one_definition_in_the_repository() -> None:
    """A guard against a second, independently-typed copy of the ignore text
    drifting from `hephaestus.core.cli_init.GITIGNORE` the way this fixture's
    own missing-ignore-file did: any Python source that writes a `.gitignore`
    must do it by writing (or importing) this exact string, not a fresh copy
    of the comment + `.heph/` pattern."""
    # The literal ESCAPED form, as it appears in Python source (GITIGNORE's own
    # runtime value contains real newline bytes, which never occur verbatim in
    # a one-line string-literal source file).
    needle = GITIGNORE.strip().encode("unicode_escape").decode("ascii")
    repo = Path(__file__).resolve().parents[2]
    defining_files: list[str] = []
    for path in repo.glob("**/*.py"):
        parts = path.relative_to(repo).parts
        if any(p in {"node_modules", ".venv", "__pycache__"} for p in parts):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if needle in text:
            defining_files.append(str(path.relative_to(repo)))
    assert defining_files == ["core/src/hephaestus/core/cli_init.py"], (
        f"the exact GITIGNORE content is written out literally in more places than "
        f"its one definition: {defining_files}. Every other writer must `import "
        f"GITIGNORE` from cli_init.py instead."
    )
