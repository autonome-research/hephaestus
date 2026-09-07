# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""J-http-envelope-11, J-http-envelope-14, J-http-limits-6 — the git subprocess
boundary (``server/src/hephaestus/http/git_projection.py``, §2.9).

Three defects share one file and one root mechanism: ``_git`` is the single
choke point for every git route, and it runs its subprocess with no timeout, no
containment on the failure message, and four hardcoded statuses the shared
§2.4 table does not know about.

* **J-http-limits-6** — no ``timeout=`` is passed to ``subprocess.run``, so a
  ``git`` that hangs blocks the calling thread (and, through
  ``GET /project``'s inline capability probe, the event loop itself — see
  ``test_http_limits.py`` for the cross-route concurrency assertion that pins
  the two items together) for as long as the child does.
* **J-http-envelope-11** — a failing subcommand's refusal carries the full
  argv and git's raw, unfiltered stderr, with no truncation and no redaction —
  a channel straight from a subprocess to a browser, unlike the sibling
  boundaries in ``agent_attach.py`` and ``agent_credentials.py``.
* **J-http-envelope-14** — the four git reasons (``git_verb_refused``,
  ``git_failed``, ``git_unavailable``, ``not_a_git_repository``) are raised
  with hardcoded statuses at their call sites and have no row in
  ``REASON_STATUS``, so ``status_for_reason`` — the shared table every other
  reason in the codebase resolves through — disagrees with the wire for two of
  the four. That divergence is invisible until something computes the status
  generically instead of reading the literal at the raise site, which is
  exactly what makes it a latent defect rather than an observed one.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from hephaestus.http.errors import REASON_STATUS, HttpRefusal, status_for_reason
from hephaestus.http.git_projection import (
    _git,  # pyright: ignore[reportPrivateUsage]
    git_status,
)
from hephaestus.testing.workspace import Workspace, workspace


def _init_git(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=root, check=True)
    (root / ".gitignore").write_text(".heph/\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=root, check=True)


@pytest.fixture
def repo(tmp_path: Path) -> Iterator[Workspace]:
    root = tmp_path / "proj"
    with workspace(root) as web:
        _init_git(root)
        yield web


# --------------------------------------------------------------------------
# J-http-limits-6 — no timeout on the one request-path subprocess with none


def test_the_git_subprocess_is_called_with_an_explicit_timeout(
    repo: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The structural guard: every ``subprocess.run`` this module makes must
    carry a ``timeout=`` keyword. Today it does not — ``git_projection.py``'s
    ``_git`` calls ``subprocess.run(["git", ...], capture_output=True,
    text=True, check=False)`` with no ``timeout`` at all, so a hung ``git``
    blocks the calling thread forever.
    """
    calls: list[dict[str, object]] = []
    real_run = subprocess.run

    def spy(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(kwargs)
        return real_run(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(subprocess, "run", spy)
    git_status(repo.root)
    assert calls, "no subprocess.run call was observed"
    for kwargs in calls:
        assert "timeout" in kwargs and isinstance(kwargs["timeout"], (int, float)), (
            f"every git subprocess call must carry an explicit timeout: {kwargs}"
        )
        assert kwargs["timeout"] > 0


def test_a_git_timeout_expiry_is_refused_by_name_not_left_to_hang(
    repo: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A deadline that actually expires must become a NAMED refusal
    (``git_timeout``, 504) carrying the subcommand and the ceiling — never an
    unbounded ``subprocess.TimeoutExpired`` propagating as an unclassified 500,
    and never a silent hang.
    """

    def timed_out(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd=["git", "status"], timeout=5.0)

    monkeypatch.setattr(subprocess, "run", timed_out)
    with pytest.raises(HttpRefusal) as caught:
        git_status(repo.root)
    assert caught.value.status == 504
    assert caught.value.reason == "git_timeout"
    assert "did not finish" in caught.value.message
    assert caught.value.data.get("subcommand")


# --------------------------------------------------------------------------
# J-http-envelope-11 — argv and raw stderr reach the wire verbatim


def test_git_failed_does_not_echo_the_argv_or_git_s_raw_stderr(
    repo: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failing subcommand's refusal must be built from the subcommand and the
    exit code, with git's stderr moved into a bounded, reduced ``detail`` — the
    same containment ``agent_attach.reduce_detail`` already applies to a
    sidecar failure. Today ``git_projection.py:120-126`` raises with
    ``completed.stderr`` as the message and the argv in ``data`` — both
    unreduced.
    """
    sensitive_path = "/home/definitely-a-real-operator/.ssh/id_rsa"

    def fake_failure(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            argv, 128, stdout="", stderr=f"fatal: could not read {sensitive_path}\n"
        )

    monkeypatch.setattr(subprocess, "run", fake_failure)
    with pytest.raises(HttpRefusal) as caught:
        _git(repo.root, "log", check=True)
    refusal = caught.value
    assert refusal.reason == "git_failed"
    body = refusal.body()
    assert "argv" not in body, "the full argv must not reach the wire"
    assert sensitive_path not in refusal.message, "raw git stderr must not reach message verbatim"
    assert refusal.message == "git log failed with exit status 128"
    # `detail` MAY carry the (bounded) stderr text — the containment this item
    # asks for is "never the argv, never raw stderr AS THE MESSAGE, always
    # bounded", not that every substring is redacted: `reduce_text` bounds
    # length and redacts KNOWN secrets, and git's stderr carries none of the
    # bearer's own secrets `agent_credentials` worries about.
    assert isinstance(body.get("detail"), str)


def test_a_long_stderr_is_truncated_to_a_shared_bound(
    repo: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The message (or its `detail`) must be bounded — not just redacted — so a
    verbose git failure cannot amplify into an oversized refusal body.
    """
    huge = "fatal: " + ("x" * 20_000)

    def fake_failure(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr=huge)

    monkeypatch.setattr(subprocess, "run", fake_failure)
    with pytest.raises(HttpRefusal) as caught:
        _git(repo.root, "log", check=True)
    assert len(caught.value.body()) < 2000, "the refusal body must be bounded, not the raw stderr"


# --------------------------------------------------------------------------
# J-http-envelope-14 — four git reasons, hardcoded statuses, no table row


@pytest.mark.parametrize(
    ("reason", "wire_status"),
    [
        ("git_verb_refused", 403),
        ("git_failed", 400),
        ("git_unavailable", 503),
        ("not_a_git_repository", 404),
    ],
)
def test_every_git_reason_has_a_table_row_agreeing_with_its_wire_status(
    reason: str, wire_status: int
) -> None:
    """The standing guard the ledger asks for: ``status_for_reason`` — the
    ONE shared function every other reason in the codebase resolves its status
    through — must agree with what the git routes actually send on the wire.
    Today none of the four is in ``REASON_STATUS``; two of them (``git_failed``
    → the 400 family fallback happens to agree, ``not_a_git_repository`` → the
    family fallback gives 400, disagreeing with the wire's 404) diverge from
    what the raise sites hardcode, and the divergence is invisible precisely
    because nothing computes the status through the table today.
    """
    assert status_for_reason(reason) == wire_status, (
        f"{reason!r} resolves to {status_for_reason(reason)} through the shared "
        f"table but the wire sends {wire_status}"
    )
    assert reason in REASON_STATUS, f"{reason!r} has no row in the closed table"


def test_git_timeout_is_also_tabulated_at_504(monkeypatch: pytest.MonkeyPatch) -> None:
    """``git_timeout`` (J-http-limits-6) joins the same table, at 504 beside the
    bridge's own ``timeout`` reason — the same status, the same remedy (wait
    or retry), for what a client experiences identically.
    """
    assert status_for_reason("git_timeout") == 504
    assert "git_timeout" in REASON_STATUS


def test_a_disallowed_verb_refuses_before_any_process_is_spawned(
    repo: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The allow-list guard, and its status agrees with the table (once the
    table has the row): 403, never a generic 400.
    """
    spawned = False
    real_run = subprocess.run

    def spy(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal spawned
        spawned = True
        return real_run(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(subprocess, "run", spy)
    with pytest.raises(HttpRefusal) as caught:
        _git(repo.root, "reset", "--hard")
    assert not spawned, "a disallowed verb must refuse before a process is spawned"
    assert caught.value.reason == "git_verb_refused"
    assert caught.value.status == status_for_reason("git_verb_refused")
