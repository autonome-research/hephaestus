# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""§2.3/§2.4/§2.8(6), amended 2026-09-03: re-adopt once, then refuse by name.

W2's finding: a sidecar respawn empties the Node-side session map while
``BridgeRuntime._principals`` — never pruned — still lists every session this
process ever opened. Before this amendment every route for such a session
failed ``INVALID_PARAMS: unknown session``, and ``http/errors.py`` had no
branch for a bare :class:`~hephaestus.agent_bridge.supervisor.SupervisorError`,
so it fell through to the module's own ``raise exc`` and reached the client as
an unnamed 500 — forever, over a transcript sitting intact on disk.

This is modeled on ``test_e2e_fake_model.py``'s
``test_kill9_restart_and_session_resume`` (kills -9 the real packaged sidecar,
waits for the pid to die, drives it back up) but goes one step further: that
test *hand-calls* ``resume_session`` before its second prompt
(``test_e2e_fake_model.py:401``). Nothing here ever calls ``resume_session``
directly — the whole point of §2.8(6) is that the runtime does it, once, on the
caller's behalf, silently on success and by a named refusal on failure. Every
call here goes through the **real HTTP app** (``build_app`` over a real
``WorkspaceRuntime`` with a real ``BridgeRuntime`` attached), because the
re-adoption story is a route-to-sidecar round trip and a fake backend cannot
lose its session map the way a respawned child genuinely does.

Where a genuine "resume itself fails" repro would require corrupting Pi's own
on-disk session format (out of this suite's ownership, and not guaranteed
stable), (c)/(d)/(e) below fault-inject at the one seam §2.8(6) specifies as
the retry boundary: ``BridgeRuntime.resume_session`` for "this session cannot
be re-adopted", and ``Supervisor.start`` for "no sidecar can be started at
all". Both are documented, narrow, and exercise exactly the code path the
notes for the server implementer name (``agent_bridge/app.py``'s
``_call_for_session`` / ``_refuse_by_name`` / ``_readopt_once``).
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from hephaestus.agent_bridge.app import BridgeRuntime, repo_root
from hephaestus.agent_bridge.sidecar import resolve_sidecar
from hephaestus.agent_bridge.supervisor import SupervisorError, pid_alive
from hephaestus.http.app import build_app
from hephaestus.http.runtime import WorkspaceRuntime
from hephaestus.testing.fake_openai import FakeOpenAI, start_fake_openai
from hephaestus.testing.ledger import seed_minimal_ledger
from hephaestus.testing.sidecar import build_agent_dist, node_executable
from hephaestus.testing.stream_assertions import text
from hephaestus.testing.tools_fixture import scaffold as scaffold_tools_project
from starlette.testclient import TestClient

#: A fixed test bearer, mirroring ``hephaestus.testing.workspace.WORKSPACE_TOKEN``
#: — fixed rather than random so a failing assertion is readable, and never
#: written to disk.
TOKEN = "test-readopt-token"

#: Generous bounds on the real timing this suite waits on:
#: * a real ``kill -9`` + the supervisor's own auto-respawn (first backoff is
#:   0.5s; §2.4's own comment on ``respawn_max_attempts`` calls <4s "loud");
#: * three respawn attempts giving up entirely (0.5 + 1.0 + 2.0s of backoff).
#: 30s leaves ample headroom on a loaded CI box without masking a real hang.
WAIT_TIMEOUT_S = 30.0


@pytest.fixture(scope="session")
def sidecar_dist() -> Path:
    """The packaged sidecar's ``main.js``; skip cleanly when Node is absent.

    Prefers :func:`build_agent_dist` (the ``pnpm --dir agent run bundle`` path
    every other e2e suite uses), but this environment has no ``pnpm`` on
    ``PATH`` — only ``node`` — so it falls back to the two commands this
    repo's tooling notes name explicitly: ``node agent/scripts/bundle.mjs``
    from the repo root, then ``scripts/stage_sidecar.py`` to stage the bundle
    where :func:`resolve_sidecar` (and therefore a plain ``BridgeRuntime()``
    with no ``dist_main`` override) expects it. Either path ends at the same
    staged bundle; this one just does not require ``pnpm`` to reach it.
    """
    built = build_agent_dist()
    if built is not None:
        return built[0]
    if node_executable() is None:
        pytest.skip("node unavailable; re-adoption needs the packaged sidecar")
    bundle_script = repo_root() / "agent" / "scripts" / "bundle.mjs"
    stage_script = repo_root() / "scripts" / "stage_sidecar.py"
    if not bundle_script.is_file() or not stage_script.is_file():
        pytest.skip("no agent/ source tree to bundle from (installed wheel)")
    subprocess.run(
        [str(node_executable()), str(bundle_script)],
        check=True,
        cwd=repo_root(),
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [sys.executable, str(stage_script)],
        check=True,
        cwd=repo_root(),
        capture_output=True,
        text=True,
    )
    return resolve_sidecar().main


class ReadoptHarness:
    """A real Starlette app, over a real ``BridgeRuntime``, over a real sidecar.

    Deliberately not ``hephaestus.testing.workspace.workspace()``: that helper's
    ``agent=True`` attaches a :class:`~hephaestus.testing.fake_agent.FakeAgent`,
    whose session map cannot be "forgotten" by a respawn the way a real Node
    child's can — the bug this suite is about is a property of the real
    supervisor/sidecar seam, not of ``WorkspaceSessions``. So this harness
    builds the same real objects ``http/agent_attach.py`` does (a real
    ``BridgeRuntime`` sharing the workspace's one store / project store / CAD /
    dispatcher) without going through ``providers.json`` — the fake OpenAI
    provider stands in exactly as it does in ``test_e2e_fake_model.py``.
    """

    def __init__(self, root: Path, dist_main: Path) -> None:
        scaffold_tools_project(root)
        self.runtime = WorkspaceRuntime.open(root, token=TOKEN, serve_mode=False)
        seed_minimal_ledger(self.runtime.cad)
        self.fake: FakeOpenAI = start_fake_openai([])
        self.bridge = BridgeRuntime(
            project_root=self.runtime.root,
            providers=[self.fake.provider_spec()],
            dist_main=dist_main,
            store=self.runtime.store,
            project_store=self.runtime.project_store,
            cad=self.runtime.cad,
            dispatcher=self.runtime.dispatcher,
        )
        self.bridge.start()
        self.runtime.attach_sessions(self.bridge)
        self.app = build_app(self.runtime)
        self.client: httpx.Client = TestClient(self.app, raise_server_exceptions=False)
        self.child_pids: list[int] = [self.bridge.child_pid]

    # -- HTTP, mirroring hephaestus.testing.workspace.Workspace.request -----

    def get(self, path: str, **kw: Any) -> httpx.Response:
        return self.client.get(f"/api/v1{path}", headers=self._headers(), **kw)

    def post(self, path: str, *, json: Any = None, **kw: Any) -> httpx.Response:
        return self.client.post(f"/api/v1{path}", json=json, headers=self._headers(), **kw)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {TOKEN}"}

    # -- fault injection: a real kill, real auto-respawn -------------------

    def create_and_prompt(self, reply: str) -> str:
        """A session with one real, persisted turn — through the real routes."""
        session_id = self.post("/sessions", json={"profile": "orchestrator"}).json()["session_id"]
        self.fake.set_script([text(reply)])
        prompted = self.post(f"/sessions/{session_id}/prompt", json={"text": "hello"})
        assert prompted.status_code == 200, prompted.text
        return str(session_id)

    def kill_and_wait_for_respawn(self) -> None:
        """``kill -9`` the child and wait for the supervisor's OWN auto-respawn.

        Nothing here calls ``restart()`` or ``resume_session`` — the whole
        subject of this suite is what happens when a caller reaches a freshly
        respawned child that never heard of a session the runtime still lists,
        so the respawn has to be the ordinary, unprompted one
        (``Supervisor._auto_respawn``, fired by the watchdog within
        ``watchdog_interval_s`` of the reader thread noticing the exit).
        """
        old_pid = self.bridge.child_pid
        os.kill(old_pid, 9)
        deadline = time.monotonic() + WAIT_TIMEOUT_S
        while time.monotonic() < deadline and pid_alive(old_pid):
            time.sleep(0.02)
        assert not pid_alive(old_pid), f"sidecar pid {old_pid} survived kill -9"
        sup = self.bridge._sup  # pyright: ignore[reportPrivateUsage]
        while time.monotonic() < deadline:
            try:
                new_pid = self.bridge.child_pid
            except SupervisorError:
                new_pid = None
            # ``new_pid`` alone is not "ready": ``Supervisor.start`` sets
            # ``self.proc`` (what ``child_pid`` reads) BEFORE it fires the spawn
            # hook that replays ``runtime.configure`` — a call sent to the child
            # in that window gets back the sidecar's own ``INVALID_REQUEST:
            # "runtime.configure has not run yet"``. ``_respawning`` flips back
            # to ``False`` only once ``start()`` has returned, i.e. once the hook
            # has actually completed, so waiting on it (rather than only on the
            # pid) is what makes this deterministic instead of racy.
            if (
                new_pid is not None
                and new_pid != old_pid
                and pid_alive(new_pid)
                and not sup._respawning  # pyright: ignore[reportPrivateUsage]
            ):
                self.child_pids.append(new_pid)
                return
            time.sleep(0.02)
        raise AssertionError("the sidecar did not auto-respawn after kill -9")

    def break_every_future_spawn(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Make every respawn attempt fail, standing in for "no sidecar starts".

        §2.4's new ``agent_unavailable`` row is reached when "no sidecar can
        serve a session route — none attached, or one that cannot be started".
        Reproducing "cannot be started" against the *real* packaged sidecar
        deterministically (as opposed to racing the watchdog's own timing) means
        making the one thing that starts it fail: ``Supervisor.start`` is
        exactly what both the first spawn and every automatic respawn attempt
        call, so patching it here breaks them identically to a missing/broken
        Node the way ``ATTACH_CAUSES``' ``node_missing`` would.
        """

        def _refuse(*_a: Any, **_kw: Any) -> None:
            raise OSError("simulated: no sidecar can be started")

        monkeypatch.setattr(self.bridge._sup, "start", _refuse)  # pyright: ignore[reportPrivateUsage]

    def wait_for_permanent_give_up(self) -> None:
        """Block until ``Supervisor``'s own respawn budget is exhausted.

        ``respawn_max_attempts`` (default 3) with its own doubling backoff is
        designed, per its own comment in ``supervisor.py``, to fail loudly in
        under ~4s — this just waits for that durable-dead state rather than
        guessing a sleep.
        """
        sup = self.bridge._sup  # pyright: ignore[reportPrivateUsage]
        deadline = time.monotonic() + WAIT_TIMEOUT_S
        while time.monotonic() < deadline:
            if sup._respawn_failure is not None:  # pyright: ignore[reportPrivateUsage]
                return
            time.sleep(0.02)
        raise AssertionError("the supervisor did not give up respawning in time")

    # -- teardown ------------------------------------------------------------

    def close(self) -> None:
        try:
            self.bridge.close()
        finally:
            self.fake.close()
            self.client.close()
            self.runtime.close()

    def assert_no_orphans(self) -> None:
        for pid in self.child_pids:
            assert not pid_alive(pid), f"sidecar pid {pid} outlived the harness"


@pytest.fixture
def harness(tmp_path: Path, sidecar_dist: Path) -> Iterator[ReadoptHarness]:
    h = ReadoptHarness(tmp_path / "proj", sidecar_dist)
    try:
        yield h
    finally:
        h.close()
        h.assert_no_orphans()


# ---------------------------------------------------------------------------
# (a) history survives a respawn: re-adoption is silent on success


def test_history_survives_a_kill_via_silent_readoption(harness: ReadoptHarness) -> None:
    """§2.8(6): "the server resumes the session once and retries" — silently.

    A client that only ever calls ``GET history`` never learns the sidecar was
    replaced underneath it: the transcript this turn wrote is still readable
    once the runtime has re-adopted the session on the fresh child.
    """
    session_id = harness.create_and_prompt("pong")
    harness.kill_and_wait_for_respawn()

    page = harness.get(f"/sessions/{session_id}/history")

    assert page.status_code == 200, page.text
    body = page.json()
    assert body["status"] == "ok"
    assert body["session_id"] == session_id
    kinds = [str(ev["kind"]) for ev in body["events"]]
    assert "text_delta" in kinds, kinds
    streamed = "".join(
        str(ev.get("payload", {}).get("text", ""))
        for ev in body["events"]
        if ev["kind"] == "text_delta"
    )
    assert "pong" in streamed, streamed

    # And the listing agrees the session is fine — the read that just succeeded
    # is what clears any mark, so there is nothing to clear here in the first
    # place: the very first call after the respawn already healed silently.
    listed = harness.get("/sessions").json()
    row = next(r for r in listed["sessions"] if r["session_id"] == session_id)
    assert row["readable"] is True
    assert row["unreadable_reason"] is None


# ---------------------------------------------------------------------------
# (b) the same for POST prompt


def test_a_second_prompt_survives_a_kill_via_silent_readoption(harness: ReadoptHarness) -> None:
    """§2.8(6) reaches ``session.prompt`` too, not only the read side.

    Mirrors ``test_e2e_fake_model.py``'s ``test_kill9_restart_and_session_resume``
    (a second prompt completing after the kill) but through the real HTTP route
    and with **no hand-called** ``resume_session`` — that call is exactly what
    this amendment makes the runtime perform on the caller's behalf.
    """
    session_id = harness.create_and_prompt("first turn recorded")
    harness.kill_and_wait_for_respawn()

    harness.fake.set_script([text("still here after the respawn")])
    second = harness.post(f"/sessions/{session_id}/prompt", json={"text": "are you alive?"})

    assert second.status_code == 200, second.text
    body = second.json()
    assert body["run_status"] == "completed"
    streamed = "".join(
        str(ev.get("payload", {}).get("text", ""))
        for ev in body["events"]
        if ev["kind"] == "text_delta"
    )
    assert "still here after the respawn" in streamed, streamed


# ---------------------------------------------------------------------------
# (c) a resume that itself fails: refused BY NAME and marked, not a 500


def test_when_resume_itself_fails_history_is_refused_unknown_session(
    harness: ReadoptHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§2.8(6)'s "if that fails" half.

    The FIRST failure — the fresh child not knowing this session — is the real,
    organic one a kill produces. What is faked is only the *second* one:
    ``resume_session`` is made to raise, standing in for a persisted transcript
    the sidecar could not re-open, so the retry the runtime attempts on the
    caller's behalf genuinely does not recover it. §2.4: this must be a NAMED
    404 ``unknown_session`` (data carrying ``session_id``) — never the unnamed
    500 an unmapped ``SupervisorError`` produced before this amendment — and
    §2.3: the session stays LISTED (never delisted) and is MARKED.
    """
    session_id = harness.create_and_prompt("pong")
    harness.kill_and_wait_for_respawn()

    def _resume_fails(*_a: Any, **_kw: Any) -> str:
        # No ``error=`` envelope: this is the shape a resume that could not even
        # complete takes (``Supervisor.call``'s "no process" / write-failure /
        # timeout raise sites all construct exactly this bare form).
        raise SupervisorError(f"resume of {session_id!r} could not re-open its transcript")

    monkeypatch.setattr(harness.bridge, "resume_session", _resume_fails)

    page = harness.get(f"/sessions/{session_id}/history")

    assert page.status_code == 404, page.text
    body = page.json()
    assert body["status"] == "error"
    assert body["reason"] == "unknown_session"
    assert body.get("session_id") == session_id

    listed = harness.get("/sessions").json()
    row = next(r for r in listed["sessions"] if r["session_id"] == session_id)
    assert row["readable"] is False
    assert row["unreadable_reason"] == "unknown_session"

    # §2.3: never delisted. The row is still there, merely marked.
    assert session_id in {r["session_id"] for r in listed["sessions"]}


def test_when_resume_itself_fails_a_prompt_is_also_refused_by_name(
    harness: ReadoptHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same failure, reached through ``POST /sessions/{id}/prompt``.

    §2.4's two new rows are named for "a session route", not for history
    specifically — a prompt for a session the runtime cannot re-adopt must
    refuse exactly the same way, not silently open a new, empty conversation
    under the same id.
    """
    session_id = harness.create_and_prompt("pong")
    harness.kill_and_wait_for_respawn()

    def _resume_fails(*_a: Any, **_kw: Any) -> str:
        raise SupervisorError(f"resume of {session_id!r} could not re-open its transcript")

    monkeypatch.setattr(harness.bridge, "resume_session", _resume_fails)

    harness.fake.set_script([text("should never be reached")])
    prompted = harness.post(f"/sessions/{session_id}/prompt", json={"text": "hello again"})

    assert prompted.status_code == 404, prompted.text
    assert prompted.json()["reason"] == "unknown_session"


# ---------------------------------------------------------------------------
# (d) no sidecar can be started at all: agent_unavailable, not unknown_session


def test_a_sidecar_that_cannot_restart_yields_agent_unavailable(
    harness: ReadoptHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§2.4's OTHER new row: *this runtime*, not *this session*.

    With every future spawn attempt broken, the supervisor's own respawn budget
    is genuinely exhausted (``Supervisor._give_up_locked``) — there is no
    process to answer *any* session route, for *any* session, which is the
    condition §2.4 names ``agent_unavailable`` rather than ``unknown_session``:
    the remedy is "fix the runtime", not "open another session".
    """
    session_id = harness.create_and_prompt("pong")
    harness.break_every_future_spawn(monkeypatch)
    old_pid = harness.bridge.child_pid
    os.kill(old_pid, 9)
    deadline = time.monotonic() + WAIT_TIMEOUT_S
    while time.monotonic() < deadline and pid_alive(old_pid):
        time.sleep(0.02)
    assert not pid_alive(old_pid)
    harness.wait_for_permanent_give_up()

    page = harness.get(f"/sessions/{session_id}/history")

    assert page.status_code == 503, page.text
    body = page.json()
    assert body["status"] == "error"
    assert body["reason"] == "agent_unavailable"
    # §7A.8's closed cause vocabulary: this path's cause is `sidecar_failed`,
    # reused rather than widened (INTERFACE.md §2.4 amendment note).
    assert body.get("cause") == "sidecar_failed"


# ---------------------------------------------------------------------------
# (e) listing consistency: every readable:true row really is readable


def test_every_row_the_listing_marks_readable_is_readable_by_history(
    harness: ReadoptHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """W2's own goal, stated as a round-trip: a session the runtime lists must
    be readable, or must be refused by name and marked in the listing.

    One shared respawn (the sidecar is one process) leaves three sessions
    unknown to the fresh child. Two are genuinely recoverable and re-adopt
    silently; the third's resume is made to fail. After touching each once,
    the listing and a fresh history read must agree for every row, in both
    directions — a readable row that then 404s, or an unreadable row that then
    200s, are both the split-brain this amendment exists to close.
    """
    good_a = harness.create_and_prompt("alpha")
    good_b = harness.create_and_prompt("bravo")
    bad = harness.create_and_prompt("charlie")
    harness.kill_and_wait_for_respawn()

    original_resume = harness.bridge.resume_session

    def _selective_resume(profile: str, session_id: str, *, part: str | None = None) -> str:
        if session_id == bad:
            raise SupervisorError(f"resume of {session_id!r} could not re-open its transcript")
        return original_resume(profile, session_id, part=part)

    monkeypatch.setattr(harness.bridge, "resume_session", _selective_resume)

    # Touch every session once so the listing's cache-of-a-failure is actually
    # populated (§2.3: "the listing never probes" — nothing is known until a
    # real call for that session has been made).
    first_pass = {
        sid: harness.get(f"/sessions/{sid}/history").status_code for sid in (good_a, good_b, bad)
    }
    assert first_pass[good_a] == 200, first_pass
    assert first_pass[good_b] == 200, first_pass
    assert first_pass[bad] == 404, first_pass

    listed = harness.get("/sessions").json()["sessions"]
    rows = {row["session_id"]: row for row in listed}
    assert rows[good_a]["readable"] is True
    assert rows[good_b]["readable"] is True
    assert rows[bad]["readable"] is False
    assert rows[bad]["unreadable_reason"] == "unknown_session"

    # The round trip: every row this pass marks readable must be readable by a
    # SECOND, independent history call — and every row marked unreadable must
    # still refuse. Restricted to the three sessions this test created, since
    # `tmp_path` is per-test and nothing else could be listed here.
    for row in listed:
        sid = row["session_id"]
        if sid not in (good_a, good_b, bad):
            continue  # pragma: no cover - defensive; this project has no others
        again = harness.get(f"/sessions/{sid}/history")
        if row["readable"]:
            assert again.status_code == 200, (sid, again.text)
        else:
            assert again.status_code != 200, (sid, again.text)
            assert again.json().get("reason") == row["unreadable_reason"]


# ---------------------------------------------------------------------------
# (f) a session id this runtime never opened: no re-adoption is even attempted


def test_a_session_id_this_runtime_never_opened_is_refused_without_claiming_a_readopt(
    harness: ReadoptHarness,
) -> None:
    """§2.8(6)'s two failure sentences must not blur together.

    ``_call_for_session`` (``agent_bridge/app.py``) takes two different paths to
    the same ``unknown_session`` reason: a session this runtime never had a
    ``Principal`` for (a mistyped id, a foreign id, one from another workspace)
    never attempts a re-adoption at all — there is nothing retained to re-open
    — while a session that DID have one and whose resume then failed genuinely
    tried and lost. Round 2's fix (``_refuse_by_name(..., readopted=bool)``)
    keeps the two sentences apart; this pins the no-principal half at the HTTP
    boundary, with no kill needed, since ``_principal_of`` returns ``None`` for
    an id ``create_session`` never minted regardless of sidecar health.
    """
    made_up_id = "00000000-0000-0000-0000-000000000000"

    page = harness.get(f"/sessions/{made_up_id}/history")

    assert page.status_code == 404, page.text
    body = page.json()
    assert body["reason"] == "unknown_session"
    assert body.get("session_id") == made_up_id
    # The sentence must not claim an attempt that never ran (round 2's finding).
    assert "re-adoption attempt" not in body["message"]

    # And the listing never learns of an id it never had a principal for in the
    # first place — §2.3's mark lives on the retained principal, and there is
    # none to mark.
    listed = harness.get("/sessions").json()["sessions"]
    assert made_up_id not in {row["session_id"] for row in listed}
