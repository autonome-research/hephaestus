# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Sessions, history paging, threading, and question answering (§2.3/§2.7/§2.8).

Four contracts, each asserted where it can actually fail:

* **history is a passthrough.** The opaque cursor is forwarded and returned
  unmodified, the route exposes no page size, and a multi-page walk delivers
  every event exactly once over a frozen high-water mark.
* **the two identity namespaces stay disjoint.** A historical event names the
  SESSION in ``run_id`` with an ordinal from 0; a live event names the run. The
  two are never merged and a client can tell them apart from the separator alone.
* **threading comes from the durable edge table**, never from the event stream,
  and a session with no edge reads ``unlinked`` rather than being guessed at.
* **session control takes no idempotency key**, in both directions: the seven
  keyed routes still demand one, and these five accept a request without one.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import pytest
from hephaestus.http.event_identity import (
    historical_event_id,
    identity_surface,
    live_event_id,
)
from hephaestus.http.idempotency import KEY_REQUIRED_ROUTES, SESSION_CONTROL_ROUTES
from hephaestus.testing.fake_agent import HISTORY_PAGE_SIZE, decode_cursor
from hephaestus.testing.workspace import Workspace, workspace


def prompt(web: Workspace, session: str, body: dict[str, Any]) -> Any:
    revision = web.get(f"/sessions/{session}/model").json()["model_state"]["revision"]
    return web.post(
        f"/sessions/{session}/prompt", json={**body, "expected_model_revision": revision}
    )


# --------------------------------------------------------------------------
# GET /sessions and POST /sessions


def test_creating_and_listing_sessions_needs_no_idempotency_key(tmp_path: Path) -> None:
    """§2.3, second table: session control carries no key.

    A duplicate create is an extra *idle* session, not a lost or doubled write —
    at-least-once, stated. ``GET /sessions`` is what makes the orphan visible.
    """
    with workspace(tmp_path / "proj", agent=True) as web:
        first = web.post(
            "/sessions",
            json={"profile": "orchestrator", "model": {"provider_id": "fake", "model_id": "text"}},
        )
        second = web.post(
            "/sessions",
            json={
                "profile": "part",
                "part": "widget",
                "model": {"provider_id": "fake", "model_id": "text"},
            },
        )
        assert first.status_code == 200
        assert second.status_code == 200
        listed = web.get("/sessions").json()

    rows = {row["session_id"]: row for row in listed["sessions"]}
    assert set(rows) == {first.json()["session_id"], second.json()["session_id"]}
    assert rows[second.json()["session_id"]]["part"] == "widget"
    # Nothing threads them: they are two roots, and the panel is told so rather
    # than inferring a parent from creation order.
    assert {row["thread_state"] for row in listed["sessions"]} == {"unlinked"}


def test_the_profile_set_is_closed(tmp_path: Path) -> None:
    """ "profile from a closed set" (§2.3) — enumerated, not sniffed.

    ``query_snapshot`` and ``reviewer`` are runtime-internal profiles with their
    own budgets and empty/read-only allowlists; offering them to a client that
    could then prompt them would hand out a session the runtime owns.
    """
    with workspace(tmp_path / "proj", agent=True) as web:
        refused = web.post("/sessions", json={"profile": "reviewer"})
    assert refused.status_code == 400
    assert refused.json()["reason"] == "invalid_params"


# --------------------------------------------------------------------------
# B-11(b): resume is refused for a transcript that does not exist, and
# `resumed` reports what happened rather than echoing the request (§2.3/§2.4,
# amended 2026-09-04).


def test_resuming_a_transcript_that_does_not_exist_is_refused_unknown_session(
    tmp_path: Path,
) -> None:
    """The audit's repro, pinned: before this fix a never-used id came back 200
    ``resumed: true`` and the listing then showed a session nothing had opened —
    "the operator is told they reopened a transcript they did not."

    §2.4 already defines ``unknown_session`` at 404 for an id the runtime holds
    nothing for; this is that same refusal, reached from the create route
    rather than from an existing session route.
    """
    with workspace(tmp_path / "proj", agent=True) as web:
        response = web.post(
            "/sessions",
            json={"profile": "orchestrator", "session_id": "sess-nope", "resume": True},
        )
        listed = web.get("/sessions").json()

    assert response.status_code == 404
    body = response.json()
    assert body["reason"] == "unknown_session"
    assert body["session_id"] == "sess-nope"
    assert "sess-nope" not in {row["session_id"] for row in listed["sessions"]}


def test_resuming_a_persisted_transcript_reopens_it_and_is_not_over_tightened(
    tmp_path: Path,
) -> None:
    """The positive half, so the refusal above is not over-tightened: a session
    that genuinely persisted resumes 200 with ``resumed: true``, and its
    history is the transcript that was actually there — not a fresh empty one
    bearing the old name.
    """
    with workspace(tmp_path / "proj", agent=True) as web:
        agent = web.agent
        assert agent is not None
        session_id = agent.create_session("orchestrator", session_id="sess-real")
        agent.seed_history(session_id, 3)

        response = web.post(
            "/sessions",
            json={"profile": "orchestrator", "session_id": "sess-real", "resume": True},
        )
        history = web.get(f"/sessions/{session_id}/history").json()

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["session_id"] == "sess-real"
    assert body["resumed"] is True
    assert len(history["events"]) == 3


# --------------------------------------------------------------------------
# history


def test_history_is_a_passthrough_that_never_rewrites_the_cursor(tmp_path: Path) -> None:
    """§2.8: "the opaque base64url cursor is forwarded and returned unmodified"."""
    with workspace(tmp_path / "proj", agent=True) as web:
        agent = web.agent
        assert agent is not None
        session = agent.create_session("orchestrator")
        agent.seed_history(session, HISTORY_PAGE_SIZE + 40)

        page1 = web.get(f"/sessions/{session}/history").json()
        cursor = page1["cursor"]
        assert cursor is not None
        page2 = web.get(f"/sessions/{session}/history", params={"cursor": cursor}).json()

    # Forwarded byte-for-byte: the backend saw exactly what the client sent.
    assert agent.seen_cursors == [None, cursor]
    # And returned unmodified — the route re-serializes nothing.
    assert page1["cursor"] == cursor
    assert page2["cursor"] is None
    assert page2["done"] is True
    assert len(page1["events"]) == HISTORY_PAGE_SIZE
    assert len(page2["events"]) == 40
    # The frozen high-water mark is the sidecar's, not the route's.
    assert decode_cursor(cursor)["offset"] == HISTORY_PAGE_SIZE


def test_the_history_route_exposes_no_page_size(tmp_path: Path) -> None:
    """§2.8 TIGHTENING: a client-selectable page size would break restart
    stability and the frozen-mark guarantee, so the route has none.

    Asserted by *behaviour*: every plausible spelling of a size parameter is
    ignored, and the page is still the sidecar's own ``HISTORY_PAGE_SIZE``.
    """
    with workspace(tmp_path / "proj", agent=True) as web:
        agent = web.agent
        assert agent is not None
        session = agent.create_session("orchestrator")
        agent.seed_history(session, HISTORY_PAGE_SIZE + 10)
        for name in ("limit", "page_size", "pageSize", "max", "count"):
            page = web.get(f"/sessions/{session}/history", params={name: "3"}).json()
            assert len(page["events"]) == HISTORY_PAGE_SIZE, name


# --------------------------------------------------------------------------
# B-11(a): a malformed cursor is refused by name, never reported as a dead
# runtime (§2.4/§2.8, amended 2026-09-04). Driven against the FAKE backend, so
# the contract is pinned on the lane with no Node toolchain — the sidecar's own
# decoder is exercised separately by ``agent/test/session/history.test.ts``.


def test_a_malformed_cursor_is_refused_invalid_cursor_not_agent_unavailable(
    tmp_path: Path,
) -> None:
    """Every shape §2.8 names, each 400 ``invalid_cursor`` — never the 503
    ``agent_unavailable`` the audit found ("this server has no agent runtime
    attached, so there is nobody to send this to", over a live sidecar).

    Then an UNQUALIFIED read still returns 200: the pin that a malformed
    request never marks the runtime dead for the calls that follow it — the
    exact regression a message-based special case (rather than the structural
    "an answered refusal is never agent_unavailable" fix) would still allow for
    any input this branch does not happen to recognise.
    """
    import base64

    with workspace(tmp_path / "proj", agent=True) as web:
        agent = web.agent
        assert agent is not None
        session = agent.create_session("orchestrator")
        agent.seed_history(session, 5)

        def b64(payload: bytes) -> str:
            return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")

        malformed_params: list[dict[str, str]] = [
            {"cursor": "%%%"},  # not base64-shaped at all
            {"cursor": b64(b'{"foo": 1}')},  # well-formed base64, not a cursor
            {"after": b64(b'{"hw": "e1", "offset": 1.5}')},  # non-integer offset
            {"after": b64(b'{"hw": "e1", "offset": -1}')},  # negative offset
            # The audit's OWN four tokens, verbatim and unencoded. The four
            # above are base64-of-JSON payloads, which exercise the decoder one
            # layer in; these are what a hand-typed URL or a stale bookmark
            # actually carries, and `after` is a distinct parameter from
            # `cursor` with a distinct decode path — a fix that named only the
            # `cursor` shapes would leave half the ledger's reproduction
            # answering 503 over a live sidecar.
            {"cursor": "YWJj"},  # valid base64 ("abc"), not a cursor
            {"after": "abc"},  # not base64-shaped at all
            {"after": "-1"},  # an offset mistaken for a token
        ]
        for params in malformed_params:
            response = web.get(f"/sessions/{session}/history", params=params)
            assert response.status_code == 400, params
            body = response.json()
            assert body["reason"] == "invalid_cursor", params
            assert body["status"] == "error"
            # A malformed cursor is not an attach problem: `config_path` is the
            # attach refusal's key (§7A.8) and its presence here would send the
            # panel to the sign-in flow for a bad URL.
            assert "config_path" not in body, params

        # The sidecar was never considered dead: an unqualified read right
        # after every malformed one still succeeds.
        alive = web.get(f"/sessions/{session}/history")
        assert alive.status_code == 200
        assert len(alive.json()["events"]) == 5


def test_a_decodable_cursor_that_names_no_entry_is_also_invalid_cursor(
    tmp_path: Path,
) -> None:
    """J-http-envelope-9, mirrored onto the no-Node lane.

    The two refusals below are NOT decode failures — both tokens decode
    perfectly. They are the pair the item removed from
    ``agent/src/session/history.ts``: a mark naming no entry used to widen the
    frozen snapshot to the whole log, and an offset past its end used to slice
    to an empty page with ``done: true``. Composed, they handed a client walking
    a real session with a nonsense cursor *exactly* the shape a genuinely
    exhausted, quiet session returns — an empty transcript rendered as complete.

    The double (``testing/fake_agent.py``) carried the same leniency, so on this
    lane — the one with no sidecar — the refusals had no coverage at all and a
    client could have been certified against behaviour the real bridge no longer
    has. Both must reach the HTTP envelope as 400 ``invalid_cursor``, the same
    answer a token that fails to decode gets, because they are the same class of
    client mistake.

    The boundary is the point of the third case: an offset EQUAL to the
    snapshot's length is §2.8(5)'s "you are caught up" and stays a 200 with an
    empty page. Refusing it would break every polling client, which is the
    failure mode the strictness could plausibly have introduced.
    """
    import base64
    import json as _json

    with workspace(tmp_path / "proj", agent=True) as web:
        agent = web.agent
        assert agent is not None
        session = agent.create_session("orchestrator")
        agent.seed_history(session, 5)

        def cursor(hw: str, offset: int) -> str:
            raw = _json.dumps({"hw": hw, "offset": offset}).encode("utf-8")
            return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

        refused: list[dict[str, str]] = [
            # A mark that decodes and names no entry in a NON-empty log.
            {"cursor": cursor("e99", 0)},
            # An offset strictly beyond the snapshot the mark names.
            {"cursor": cursor("e4", 6)},
        ]
        for params in refused:
            response = web.get(f"/sessions/{session}/history", params=params)
            assert response.status_code == 400, params
            body = response.json()
            assert body["reason"] == "invalid_cursor", params
            assert body["status"] == "error"

        # …and the case that must NOT be refused: caught up, exactly.
        caught_up = web.get(f"/sessions/{session}/history", params={"cursor": cursor("e4", 5)})
        assert caught_up.status_code == 200
        page = caught_up.json()
        assert page["events"] == [] and page["done"] is True


def test_a_multi_page_walk_delivers_every_event_exactly_once(tmp_path: Path) -> None:
    """The bounded-read machinery, exercised through the route it is served by."""
    with workspace(tmp_path / "proj", agent=True) as web:
        agent = web.agent
        assert agent is not None
        session = agent.create_session("orchestrator")
        seeded = agent.seed_history(session, HISTORY_PAGE_SIZE * 2 + 7)

        collected: list[dict[str, Any]] = []
        cursor: str | None = None
        pages = 0
        while True:
            params = {} if cursor is None else {"cursor": cursor}
            page = web.get(f"/sessions/{session}/history", params=params).json()
            collected.extend(page["events"])
            pages += 1
            cursor = page["cursor"]
            if page["done"]:
                break
            assert pages < 10, "paging failed to terminate"

    assert pages == 3
    assert collected == seeded
    assert [e["seq"] for e in collected] == list(range(len(seeded)))


def test_history_events_carry_the_session_scoped_identity(tmp_path: Path) -> None:
    """§2.8's identity table, at the boundary that actually serves both.

    A historical event's identity is ``(session_id, ordinal)`` — ``run_id``
    carries the SESSION id, because ``main.ts`` passes the session id into the
    parameter ``history.ts`` names ``runId`` — while a live event carries the
    real run id. **The two are never merged**, so a live gap can never be closed
    from history: a dedupe on ``(run_id, seq)`` across them would never match.
    """
    with workspace(tmp_path / "proj", agent=True) as web:
        agent = web.agent
        assert agent is not None
        session = agent.create_session("orchestrator")
        agent.seed_history(session, 5)
        historical = web.get(f"/sessions/{session}/history").json()["events"]
        with web.events() as socket:
            agent.prompt(session, "go", run_id="run-live")
            agent.emit("run-live", 0, "text_delta", payload={"text": "live"})
            live = socket.receive_json()

    assert {event["run_id"] for event in historical} == {session}
    assert [event["seq"] for event in historical] == [0, 1, 2, 3, 4]
    assert live["run_id"] == "run-live"
    assert live["run_id"] != session

    # The same logical position in the two namespaces serializes differently, and
    # the separator alone tells a reader which surface a chip came from.
    assert historical_event_id(session, 0) == f"{session}@0"
    assert live_event_id("run-live", 0) == "run-live#0"
    assert identity_surface(historical_event_id(session, 0)) == "historical"
    assert identity_surface(live_event_id("run-live", 0)) == "live"
    assert historical_event_id(session, 0) != live_event_id("run-live", 0)


def test_an_empty_history_is_done_immediately(tmp_path: Path) -> None:
    with workspace(tmp_path / "proj", agent=True) as web:
        agent = web.agent
        assert agent is not None
        session = agent.create_session("orchestrator")
        page = web.get(f"/sessions/{session}/history").json()
    # §2.8(5): `end_cursor` is present even on an empty page and is never null,
    # so a client can always hand it back as `after` — the token itself stays
    # opaque and is asserted only for presence here.
    end_cursor = page.pop("end_cursor")
    assert isinstance(end_cursor, str) and end_cursor
    assert page == {
        "status": "ok",
        "session_id": session,
        "events": [],
        "user_prompts": [],
        "cursor": None,
        "done": True,
    }


# --------------------------------------------------------------------------
# GET /sessions/{id}/thread


def test_a_session_with_no_edge_reads_unlinked_rather_than_guessed(tmp_path: Path) -> None:
    """§2.8's honest limit: an edge created before the table existed is gone.

    Pre-existing transcripts reopen flat and the UI says so, rather than
    inferring a parent from a naming convention or from stream adjacency.

    UPDATED for J-http-envelope-8 (audit-2026-09-04): the route now requires
    the id to name something before projecting a tree — a session with no
    edge at all is no longer distinguishable from one that never existed, so
    this case is exercised over a session the backend actually knows about
    (via ``agent.create_session``, i.e. "currently listed"), which is exactly
    the honest-limit boundary the route's own docstring now states: a
    pre-existing, edgeless *transcript* with no live listing and no recorded
    edge is the one case this fix still cannot answer for, and is covered
    separately by ``test_a_thread_id_that_never_existed_anywhere_is_404_unknown_session``.
    """
    with workspace(tmp_path / "proj", agent=True) as web:
        agent = web.agent
        assert agent is not None
        session = agent.create_session("orchestrator")
        body = web.get(f"/sessions/{session}/thread").json()
    assert body["thread_state"] == "unlinked"
    assert body["parent_session_id"] is None
    assert [node["session_id"] for node in body["nodes"]] == [session]
    assert body["nodes"][0]["depth"] == 0


def test_the_thread_endpoint_reads_a_durable_table_with_or_without_an_agent(
    tmp_path: Path,
) -> None:
    """Threading survives the runtime that created it.

    ``tp_session_edges`` is durable in ``state.db``; refusing to answer "what was
    this session a child of" because no model is configured *today* would make a
    durable record unreadable for a reason that has nothing to do with it. The
    routes that genuinely need a live runtime still refuse by name.
    """
    root = tmp_path / "proj"
    with workspace(root, agent=True) as web:
        web.runtime.edges.record(
            child_session_id="qe-1",
            parent_session_id="part:widget",
            kind="quick_edit",
            origin={"part": "widget"},
        )
    # Reopened with NO agent runtime at all — the edge is still readable.
    with workspace(root, scaffold=False) as reopened:
        body = reopened.get("/sessions/qe-1/thread")
        listed = reopened.get("/sessions")
    assert body.status_code == 200
    assert body.json()["parent_session_id"] == "part:widget"
    assert listed.status_code == 503
    assert listed.json()["reason"] == "agent_unavailable"


def test_the_thread_is_the_transitive_tree_from_the_durable_edge_table(
    tmp_path: Path,
) -> None:
    """§7.1's three-level tree, sourced from ``tp_session_edges`` and never inferred."""
    with workspace(tmp_path / "proj", agent=True) as web:
        edges = web.runtime.edges
        edges.record(
            child_session_id="part:widget",
            parent_session_id="orchestrator",
            kind="delegation",
            origin={"delegation_ref": "dg-1", "parent_run_id": "r0", "child_run_id": "r1"},
            created_at=1.0,
        )
        edges.record(
            child_session_id="qe-1",
            parent_session_id="part:widget",
            kind="quick_edit",
            origin={
                "part": "widget",
                "source_artifact_ref": "artifact:build:a",
                "selection_id": "s7",
                "provenance": "tread_top",
                "crop_artifact_ref": "artifact:selection-crop:c",
            },
            created_at=2.0,
        )
        body = web.get("/sessions/orchestrator/thread").json()
        child = web.get("/sessions/qe-1/thread").json()

    assert body["thread_state"] == "linked"
    assert [(n["session_id"], n["depth"]) for n in body["nodes"]] == [
        ("orchestrator", 0),
        ("part:widget", 1),
        ("qe-1", 2),
    ]
    assert body["nodes"][1]["kind"] == "delegation"
    assert body["nodes"][2]["origin"]["provenance"] == "tread_top"
    # A client handed a leaf can walk UP: the root node carries its own parent.
    assert child["parent_session_id"] == "part:widget"
    assert child["thread_state"] == "linked"
    assert [n["session_id"] for n in child["nodes"]] == ["qe-1"]


def test_a_thread_id_that_never_existed_anywhere_is_404_unknown_session(
    tmp_path: Path,
) -> None:
    """J-http-envelope-8: the route must not fabricate a tree about nothing.

    ``session_edges.thread()`` always synthesises a depth-0 root for a session
    with no edges, which is correct for a session that **exists**. The route
    passes the path parameter straight through with no existence check at all,
    so ANY string — including one nothing ever created, listed, or recorded an
    edge for — gets a 200 one-node tree today. This id is deliberately touched
    by nothing: not `agent.create_session`, not `edges.record`, not the
    listing. Contrast with ``test_a_session_with_no_edge_reads_unlinked_rather_
    than_guessed``, which pins the SAME shape of call as correct — that
    existing test encodes exactly the bug this one is written against, and the
    two cannot both be right; see this lane's report for the reconciliation
    note.
    """
    with workspace(tmp_path / "proj", agent=True) as web:
        response = web.get("/sessions/sess-never-touched-at-all/thread")
    assert response.status_code == 404, response.text
    body = response.json()
    assert body["reason"] == "unknown_session"
    assert body.get("session_id") == "sess-never-touched-at-all"


def test_a_session_known_only_through_the_edge_table_still_answers_200(
    tmp_path: Path,
) -> None:
    """The positive case the fix must not over-tighten: existence via the
    DURABLE edge table alone, never through a live listing.
    """
    root = tmp_path / "proj"
    with workspace(root, agent=True) as web:
        web.runtime.edges.record(
            child_session_id="qe-durable",
            parent_session_id="part:widget",
            kind="quick_edit",
            origin={"part": "widget"},
        )
    with workspace(root, scaffold=False) as reopened:
        response = reopened.get("/sessions/qe-durable/thread")
    assert response.status_code == 200
    assert response.json()["parent_session_id"] == "part:widget"


def test_listed_sessions_carry_their_recorded_parent(tmp_path: Path) -> None:
    with workspace(tmp_path / "proj", agent=True) as web:
        agent = web.agent
        assert agent is not None
        parent = agent.create_session("orchestrator")
        child = agent.create_session("part", part="widget")
        web.runtime.edges.record(
            child_session_id=child,
            parent_session_id=parent,
            kind="delegation",
            origin={"delegation_ref": "dg-2"},
        )
        rows = {row["session_id"]: row for row in web.get("/sessions").json()["sessions"]}
    assert rows[child]["parent_session_id"] == parent
    assert rows[child]["thread_state"] == "linked"
    # UPDATED for J-http-envelope-7 (audit-2026-09-04): `thread_state` is now
    # ONE definition — "this session participates in a thread", parent or
    # children — shared by the listing and the thread route. A parent with a
    # child is manifestly not isolated, so it reads `linked` here too; before
    # the fix the listing derived the state from a parent edge alone and this
    # assertion read `"unlinked"`, which was the divergence
    # J-http-envelope-7 is about, not a fact worth preserving.
    assert rows[parent]["thread_state"] == "linked"


def test_a_parent_with_children_and_no_parent_of_its_own_reads_linked_everywhere(
    tmp_path: Path,
) -> None:
    """J-http-envelope-7: `thread_state` has two producers with two definitions.

    ``sessions.py``'s listing sets the state from the presence of a *parent*
    edge alone (``edges.get(session_id)``, keyed by CHILD id); the thread
    projection sets it from a parent **or any children**
    (``root.parent_session_id is not None or len(nodes) > 1``). A session that
    is a parent and not a child satisfies the second and not the first, so the
    SAME session reads ``linked`` on the thread route and ``unlinked`` on the
    listing — the exact divergence
    ``test_listed_sessions_carry_their_recorded_parent`` above pins as
    *correct* today (``rows[parent]["thread_state"] == "unlinked"``). The
    ledger's decided definition is "this session participates in a thread" —
    parent or children — because a session with children is manifestly not
    isolated; this test asserts that definition on both routes and is red
    until the listing's derivation is unified with the thread projection's.
    """
    with workspace(tmp_path / "proj", agent=True) as web:
        agent = web.agent
        assert agent is not None
        parent = agent.create_session("orchestrator")
        child = agent.create_session("part", part="widget")
        web.runtime.edges.record(
            child_session_id=child,
            parent_session_id=parent,
            kind="delegation",
            origin={"delegation_ref": "dg-linked"},
        )
        listed = {row["session_id"]: row for row in web.get("/sessions").json()["sessions"]}
        threaded = web.get(f"/sessions/{parent}/thread").json()
    assert threaded["thread_state"] == "linked"
    assert listed[parent]["thread_state"] == "linked", (
        "the listing and the thread route must report the SAME thread_state for the same session"
    )


# --------------------------------------------------------------------------
# prompt / cancel / answer


def test_prompt_runs_a_turn_and_streams_it_to_an_attached_observer(
    tmp_path: Path,
) -> None:
    """G4.8's shape: one runtime, so a CLI-started session *is* the one the
    browser attaches to, with no event forwarding to get wrong."""
    with workspace(tmp_path / "proj", agent=True) as web:
        agent = web.agent
        assert agent is not None
        session = agent.create_session("orchestrator")

        def script(a: Any, sid: str, run: str, text: str, answerer: Any) -> None:
            a.emit(run, 0, "text_delta", payload={"text": f"echo {text}"})

        agent.on_prompt = script
        with web.events() as socket:
            body = prompt(web, session, {"text": "hello"}).json()
            frame = socket.receive_json()

    assert body["status"] == "ok"
    assert body["run_status"] == "completed"
    assert frame["session_id"] == session
    assert frame["run_id"] == body["run_id"]
    assert frame["payload"] == {"text": "echo hello"}


def test_a_prompt_without_text_is_refused(tmp_path: Path) -> None:
    with workspace(tmp_path / "proj", agent=True) as web:
        agent = web.agent
        assert agent is not None
        session = agent.create_session("orchestrator")
        refused = prompt(web, session, {})
    assert refused.status_code == 400
    assert refused.json()["reason"] == "invalid_params"


def test_a_prompt_with_an_unknown_body_member_is_refused_by_name(tmp_path: Path) -> None:
    """J-http-envelope-10: the prompt route silently accepts unknown members.

    ``POST /context/preview`` already refuses an unexpected key by name
    (`app.py`'s ``unexpected = sorted(set(body) - {"context"})`` check); the
    prompt route reads ``text``, ``run_id`` and ``context`` and never compares
    the key set at all, so a misspelt member (``contxt`` instead of
    ``context``, most plausibly) is silently dropped and the run proceeds with
    no workspace context and no indication anything was lost. Today this is
    200; the fix is a shared `_closed_body` helper applied here too.
    """
    with workspace(tmp_path / "proj", agent=True) as web:
        agent = web.agent
        assert agent is not None
        session = agent.create_session("orchestrator")
        response = web.post(
            f"/sessions/{session}/prompt",
            json={"text": "hi", "contxt": {"part": "widget"}},
        )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body["reason"] == "invalid_params"
    assert "contxt" in str(body)


def test_cancelling_a_run_the_server_never_admitted_is_unknown_run(tmp_path: Path) -> None:
    """J-http-envelope-12: cancelling an unknown run refuses `not_found` on a
    real bridge, and the fake backend answers 200 for the identical request —
    so no in-process test can observe the real behaviour without the fake
    learning the same refusal (the ledger's own "load-bearing half"). Today
    ``FakeAgent.cancel`` is an unconditional no-op
    (``self.cancelled.append(run_id)``) with no admission lookup, so this
    route always answers 200 regardless of whether the run id was ever
    issued. Written against the target behaviour — 404 ``unknown_run`` — so it
    is red until the fake backend is taught the refusal alongside the real
    admission-miss mapping.
    """
    with workspace(tmp_path / "proj", agent=True) as web:
        agent = web.agent
        assert agent is not None
        agent.create_session("orchestrator")
        response = web.post("/runs/run-the-server-never-issued/cancel")
    assert response.status_code == 404, response.text
    body = response.json()
    assert body["reason"] == "unknown_run"
    assert body.get("run_id") == "run-the-server-never-issued"


def test_a_completed_runs_cancel_is_still_200_idempotent(tmp_path: Path) -> None:
    """The sibling the fix must not break: idempotence is about a run's
    LIFECYCLE, not a licence to accept an unknown address. A run this process
    actually issued and already finished stays 200.
    """
    with workspace(tmp_path / "proj", agent=True) as web:
        agent = web.agent
        assert agent is not None
        session = agent.create_session("orchestrator")
        prompted = prompt(web, session, {"text": "hi"})
        run_id = prompted.json()["run_id"]
        response = web.post(f"/runs/{run_id}/cancel")
    assert response.status_code == 200, response.text


def test_the_second_answerer_gets_not_accepted_with_the_winners_selection(
    tmp_path: Path,
) -> None:
    """J-agent-wiring-7: the second answerer of a question gets 404, not
    `accepted: false`.

    ``PendingQuestions.ask`` pops the entry from the live map in a ``finally``
    the instant the suspended tool call wakes — before this test's
    ``worker.join()`` returns, so by the time the second answer is posted the
    id is provably gone from the registry and the loser's ``accepted: false``
    branch (`sessions.py:327-328`) is unreachable. The fix adds a bounded
    SETTLED map the asker's `finally` moves the entry into rather than
    dropping it, so answering resolves to one of three outcomes: live (record,
    wake, accept), settled (return the WINNER'S selection, not accepted — both
    clients then agree on what the run was told), or neither (the 404 this
    test's sibling, ``test_answering_an_unknown_question_is_a_named_refusal``,
    already pins and which must stay truthful for an actually-abandoned
    question).
    """
    with workspace(tmp_path / "proj", agent=True) as web:
        agent = web.agent
        assert agent is not None
        session = agent.create_session("orchestrator")

        def script(a: Any, sid: str, run: str, text: str, answerer: Any) -> None:
            a.emit(run, 0, "question", payload={"question_id": "q-two", "question": "which?"})
            answerer({"run_id": run, "question_id": "q-two", "question": "which?"})

        agent.on_prompt = script

        def prompt_thread() -> None:
            prompt(web, session, {"text": "ask me"})

        worker = threading.Thread(target=prompt_thread)
        worker.start()
        sessions = web.runtime.sessions
        assert sessions is not None
        deadline = time.monotonic() + 5
        while not sessions.questions.open_questions(session) and time.monotonic() < deadline:
            time.sleep(0.01)

        first = web.post(
            f"/sessions/{session}/answer", json={"question_id": "q-two", "answer": "left"}
        )
        worker.join(timeout=5)
        # By construction: the asker's `finally` has already run by the time
        # `worker.join()` returns, so the entry is provably gone from the LIVE
        # map — the exact microsecond-wide window the ledger says the loser
        # "essentially always loses" is made deterministic here rather than
        # raced.
        second = web.post(
            f"/sessions/{session}/answer", json={"question_id": "q-two", "answer": "right"}
        )

    assert first.status_code == 200
    assert first.json()["accepted"] is True

    assert second.status_code == 200, (
        "the second answerer must be told the question was already answered, "
        f"not refused as though it never existed: got {second.status_code} {second.text}"
    )
    second_body = second.json()
    assert second_body["accepted"] is False
    assert second_body["answered_by"] == "other"
    assert second_body["answer"] == "left", "both clients must agree on what the run was told"


def test_cancel_is_idempotent_by_construction(tmp_path: Path) -> None:
    """§2.3: a repeated ``request_cancel`` changes nothing, so no key is taken."""
    with workspace(tmp_path / "proj", agent=True) as web:
        agent = web.agent
        assert agent is not None
        session = agent.create_session("orchestrator")
        agent.prompt(session, "x", run_id="run-c")
        first = web.post("/runs/run-c/cancel")
        second = web.post("/runs/run-c/cancel")
    assert first.status_code == second.status_code == 200
    assert first.json()["session_id"] == session
    assert agent.cancelled == ["run-c", "run-c"]


def test_ask_user_broadcasts_and_the_first_answer_wins(tmp_path: Path) -> None:
    """§2.7: idempotent on the question id; neither client is privileged.

    The second answerer is not refused — it is told, in its own response, that
    someone else won, so its widget can disable itself with
    ``data-answered-by="other"`` instead of silently overwriting the answer the
    run was already given.
    """
    with workspace(tmp_path / "proj", agent=True) as web:
        agent = web.agent
        assert agent is not None
        session = agent.create_session("orchestrator")
        selections: list[Any] = []

        def script(a: Any, sid: str, run: str, text: str, answerer: Any) -> None:
            a.emit(run, 0, "question", payload={"question_id": "q-1", "question": "which?"})
            selections.append(answerer({"run_id": run, "question_id": "q-1", "question": "which?"}))

        agent.on_prompt = script
        answers: list[Any] = []

        def prompt_thread() -> None:
            prompt(web, session, {"text": "ask me"})

        worker = threading.Thread(target=prompt_thread)
        worker.start()
        sessions = web.runtime.sessions
        assert sessions is not None
        deadline = time.monotonic() + 5
        while not sessions.questions.open_questions(session) and time.monotonic() < deadline:
            time.sleep(0.01)

        first = web.post(
            f"/sessions/{session}/answer", json={"question_id": "q-1", "answer": "left"}
        )
        answers.append(first.json())
        worker.join(timeout=5)

    assert first.status_code == 200
    assert answers[0]["accepted"] is True
    assert answers[0]["answered_by"] == "self"
    assert selections == ["left"], "the run receives the winning selection"


def test_answering_an_unknown_question_is_a_named_refusal(tmp_path: Path) -> None:
    with workspace(tmp_path / "proj", agent=True) as web:
        agent = web.agent
        assert agent is not None
        session = agent.create_session("orchestrator")
        refused = web.post(
            f"/sessions/{session}/answer", json={"question_id": "q-gone", "answer": "x"}
        )
    assert refused.status_code == 404
    assert refused.json()["reason"] == "unknown_question"


def test_cancelling_a_run_abandons_its_question_instead_of_fabricating_an_answer(
    tmp_path: Path,
) -> None:
    """A cancelled run whose question "answered itself" would write an answer the
    operator never gave into the requirement ledger.

    UPDATED for J-http-envelope-12 (audit-2026-09-04): cancelling a run this
    backend never issued is now a named 404 ``unknown_run``, so ``run-x`` must
    first be a run the fake backend actually admitted — this test is about
    cancellation abandoning a live question, not about the unknown-run
    refusal, which has its own coverage above.
    """
    from hephaestus.http.sessions import AskAbandoned

    with workspace(tmp_path / "proj", agent=True) as web:
        sessions = web.runtime.sessions
        assert sessions is not None
        agent = web.agent
        assert agent is not None
        agent._run_sessions["run-x"] = "sess-1"  # pyright: ignore[reportPrivateUsage]  # admitted, as a real prompt would
        outcome: list[str] = []

        def waiter() -> None:
            try:
                sessions.questions.ask("sess-1", {"run_id": "run-x", "question_id": "q-9"})
            except AskAbandoned:
                outcome.append("abandoned")

        worker = threading.Thread(target=waiter)
        worker.start()
        deadline = time.monotonic() + 5
        while not sessions.questions.get("q-9") and time.monotonic() < deadline:
            time.sleep(0.01)
        assert web.post("/runs/run-x/cancel").json()["abandoned_questions"] == 1
        worker.join(timeout=5)

    assert outcome == ["abandoned"]


# --------------------------------------------------------------------------
# the key policy, tested in both directions


@pytest.mark.parametrize(("method", "template"), SESSION_CONTROL_ROUTES)
def test_session_control_accepts_a_request_with_no_key(
    tmp_path: Path, method: str, template: str
) -> None:
    """G5.19's other direction: a missing key on these five is **accepted**.

    Together with the missing-key test over ``KEY_REQUIRED_ROUTES``, the policy
    is asserted in both directions and cannot rot into "whatever the
    implementation happens to check". A route not yet served (``quick_edit``,
    §12.5) is skipped by name rather than silently counted as passing.
    """
    served = {row[1] for row in KEY_REQUIRED_ROUTES} | {
        "/sessions",
        "/sessions/{id}/prompt",
        "/sessions/{id}/model",
        "/sessions/{id}/answer",
        "/runs/{run_id}/cancel",
    }
    if template not in served:
        pytest.skip(f"{template} is §12.5 work and is not served yet")
    with workspace(tmp_path / "proj", agent=True) as web:
        agent = web.agent
        assert agent is not None
        session = agent.create_session("orchestrator")
        path = template.replace("{id}", session).replace("{run_id}", "run-none")
        bodies: dict[str, Any] = {
            "/sessions": {
                "profile": "orchestrator",
                "model": {"provider_id": "fake", "model_id": "text"},
            },
            "/sessions/{id}/prompt": {
                "text": "hi",
                "expected_model_revision": agent.session_model(session)["model_state"]["revision"],
            },
            "/sessions/{id}/model": {
                "model": {"provider_id": "fake", "model_id": "vision"},
                "expected_model_revision": agent.session_model(session)["model_state"]["revision"],
            },
            "/sessions/{id}/answer": {"question_id": "q-absent", "answer": "x"},
            "/runs/{run_id}/cancel": {},
        }
        response = web.request(method, path, json=bodies[template])
    # Never the key ladder: the only refusal these may produce is their own.
    assert response.json().get("reason") != "idempotency_key_required"
    assert response.status_code in (200, 404)
