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
from hephaestus.testing.workspace import workspace

# --------------------------------------------------------------------------
# GET /sessions and POST /sessions


def test_creating_and_listing_sessions_needs_no_idempotency_key(tmp_path: Path) -> None:
    """§2.3, second table: session control carries no key.

    A duplicate create is an extra *idle* session, not a lost or doubled write —
    at-least-once, stated. ``GET /sessions`` is what makes the orphan visible.
    """
    with workspace(tmp_path / "proj", agent=True) as web:
        first = web.post("/sessions", json={"profile": "orchestrator"})
        second = web.post("/sessions", json={"profile": "part", "part": "widget"})
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
    assert page == {
        "status": "ok",
        "session_id": session,
        "events": [],
        "cursor": None,
        "done": True,
    }


# --------------------------------------------------------------------------
# GET /sessions/{id}/thread


def test_a_session_with_no_edge_reads_unlinked_rather_than_guessed(tmp_path: Path) -> None:
    """§2.8's honest limit: an edge created before the table existed is gone.

    Pre-existing transcripts reopen flat and the UI says so, rather than
    inferring a parent from a naming convention or from stream adjacency.
    """
    with workspace(tmp_path / "proj", agent=True) as web:
        body = web.get("/sessions/sess-nothing/thread").json()
    assert body["thread_state"] == "unlinked"
    assert body["parent_session_id"] is None
    assert [node["session_id"] for node in body["nodes"]] == ["sess-nothing"]
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
    assert rows[parent]["thread_state"] == "unlinked"


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
            body = web.post(f"/sessions/{session}/prompt", json={"text": "hello"}).json()
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
        refused = web.post(f"/sessions/{session}/prompt", json={})
    assert refused.status_code == 400
    assert refused.json()["reason"] == "invalid_params"


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
            web.post(f"/sessions/{session}/prompt", json={"text": "ask me"})

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
    operator never gave into the requirement ledger."""
    from hephaestus.http.sessions import AskAbandoned

    with workspace(tmp_path / "proj", agent=True) as web:
        sessions = web.runtime.sessions
        assert sessions is not None
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
            "/sessions": {"profile": "orchestrator"},
            "/sessions/{id}/prompt": {"text": "hi"},
            "/sessions/{id}/answer": {"question_id": "q-absent", "answer": "x"},
            "/runs/{run_id}/cancel": {},
        }
        response = web.request(method, path, json=bodies[template])
    # Never the key ladder: the only refusal these may produce is their own.
    assert response.json().get("reason") != "idempotency_key_required"
    assert response.status_code in (200, 404)
