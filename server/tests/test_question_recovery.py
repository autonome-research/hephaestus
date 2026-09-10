# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Live registry authority, HTTP boundary and deterministic durable interleavings."""

# pyright: reportPrivateUsage=false
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from typing import Any

import pytest
from hephaestus.agent_bridge.app import BridgeRuntime, _Run
from hephaestus.agent_bridge.session_edges import SessionEdgeStore
from hephaestus.http.sessions import (
    AskAbandoned,
    PendingQuestion,
    PendingQuestions,
    WorkspaceSessions,
)
from hephaestus.testing.workspace import workspace
from opstore.types import TerminalState
from test_execution_evidence import runtime as runtime

PARAMS: dict[str, Any] = {
    "question": "Which stock?",
    "options": [{"label": "Use 6 mm", "consequence": "Increase slot width to 6 mm"}, "Keep 5.5 mm"],
    "allow_free_text": False,
    "multi": False,
}


def owned(runtime: BridgeRuntime) -> tuple[WorkspaceSessions, str, PendingQuestion]:
    sid = runtime.create_session("orchestrator", session_id="question-owner")
    sessions = WorkspaceSessions(runtime, SessionEdgeStore(runtime._store.db))
    runtime._admit_turn(
        _Run(run_id="question-run", session_id=sid), sessions.questions.answerer(sid)
    )
    runtime._admission.admit_run("question-run")
    q = PendingQuestion("question-id", sid, "question-run", dict(PARAMS))
    sessions.questions._by_id[q.question_id] = q
    return sessions, sid, q


def test_http_recovery_is_authenticated_selected_read_only_and_byte_faithful(
    tmp_path: Path,
) -> None:
    with workspace(tmp_path / "proj", agent=True) as web:
        agent, sessions = web.agent, web.runtime.sessions
        assert agent is not None and sessions is not None
        sid = agent.create_session("orchestrator")
        other = agent.create_session("part", part="widget")
        agent._active_models[sid] = "r"
        agent._run_sessions["r"] = sid
        q = PendingQuestion("q", sid, "r", dict(PARAMS))
        sessions.questions._by_id["q"] = q
        for token in (None, "wrong"):
            assert web.get(f"/sessions/{sid}/model", token=token).status_code == 401
            assert (
                web.post(
                    f"/sessions/{sid}/answer",
                    token=token,
                    json={"question_id": "q", "answer": "Use 6 mm"},
                ).status_code
                == 401
            )
        assert web.get("/sessions/missing/model").status_code == 404
        read = web.get(f"/sessions/{sid}/model", key="ignored-key")
        assert read.status_code == 200
        assert read.headers["cache-control"] == "no-store"
        projected = read.json()["live_questions"]["pending"][0]
        assert projected == {
            **PARAMS,
            "session_id": sid,
            "run_id": "r",
            "question_id": "q",
            "answered": False,
        }
        assert web.get(f"/sessions/{other}/model").json()["live_questions"]["pending"] == []
        for path, body in (
            (other, {"question_id": "q", "answer": "private"}),
            (sid, {"question_id": "q", "answer": "private", "run_id": "r"}),
        ):
            refusal = web.post(f"/sessions/{path}/answer", json=body)
            assert refusal.status_code in (400, 404)
            assert "answer" not in refusal.json()
        assert not q.answered and not q.ready.is_set()
        assert agent.prompts == agent.cancelled == agent.restarts == []
        accepted = web.post(
            f"/sessions/{sid}/answer",
            key="ignored-key",
            json={"question_id": "q", "answer": "Use 6 mm"},
        )
        assert accepted.json()["accepted"] is True
        # Answered entry deliberately still in the live map: no cleanup race.
        assert web.get(f"/sessions/{sid}/model").json()["live_questions"]["pending"] == []
        sessions.questions._settled["q"] = sessions.questions._by_id.pop("q")
        foreign = web.post(f"/sessions/{other}/answer", json={"question_id": "q", "answer": "x"})
        assert foreign.status_code == 404 and "answer" not in foreign.json()
        assert (
            web.post(f"/sessions/{sid}/answer", json={"question_id": "q", "answer": "x"}).json()[
                "answer"
            ]
            == "Use 6 mm"
        )


def test_model_rpc_finishes_before_coherent_execution_and_registry_read(
    runtime: BridgeRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions, sid, q = owned(runtime)
    original = runtime.session_model

    def read_then_close(session_id: str) -> Any:
        document = original(session_id)
        assert document["execution"]["active_run_id"] == q.run_id
        runtime._admission.ingest_terminal(
            q.run_id, "between-read-and-compose", TerminalState.FAILED
        )
        return document

    monkeypatch.setattr(runtime, "session_model", read_then_close)
    document = sessions.session_model(sid)
    assert document["execution"]["active_run_id"] is None
    assert document["execution"]["terminal"]["terminal_id"] == "between-read-and-compose"
    assert document["live_questions"]["pending"] == []
    assert not q.answered


def test_registry_copy_abandonment_duplicate_address_and_ambiguity() -> None:
    registry = PendingQuestions()
    q = PendingQuestion("q", "s", "r", dict(PARAMS))
    registry._by_id["q"] = q
    doc = registry.snapshot("s", "r")
    doc["pending"][0]["options"][0]["label"] = "changed client copy"
    assert q.params["options"][0]["label"] == "Use 6 mm"
    with pytest.raises(AskAbandoned, match="duplicate"):
        registry.ask("s", {"question_id": "q", "run_id": "r"}, timeout=0)
    assert registry.get("q") is q
    registry._by_id["second"] = PendingQuestion("second", "s", "r", dict(PARAMS))
    assert registry.snapshot("s", "r")["unavailable_reason"] == "ambiguous_question"
    with pytest.raises(KeyError):
        registry.answer("q", "x", session_id="s", eligible_run="r")
    registry.abandon_run("r")
    assert registry.snapshot("s", "r")["pending"] == []
    with pytest.raises(KeyError):
        registry.answer("q", "x")
    assert not q.answered and q.selection is None
    assert registry.snapshot("s", "r")["revision"] > doc["revision"]


@pytest.mark.parametrize(
    "fault", ["binding", "latest", "missing_admission", "child", "no_answerer", "ambiguous_holder"]
)
def test_runtime_refuses_missing_stale_child_or_ambiguous_authority(
    runtime: BridgeRuntime, fault: str
) -> None:
    sessions, sid, q = owned(runtime)
    if fault == "binding":
        runtime._run_sessions.pop(q.run_id)
    elif fault == "latest":
        runtime._latest_runs[sid] = "successor"
    elif fault == "missing_admission":
        with runtime._store.db.transaction() as conn:
            conn.execute("DELETE FROM admissions WHERE run_id = ?", (q.run_id,))
    elif fault == "child":
        child = runtime.create_session("part", part="widget", session_id="actual-child")
        sessions.edges.record(
            child_session_id=child, parent_session_id=sid, kind="delegation", origin={}
        )
        runtime._runs[q.run_id].session_id = child
        runtime._run_sessions[q.run_id] = child
    elif fault == "no_answerer":
        runtime._answerers.pop(q.run_id)
    else:
        runtime._runs["second"] = _Run(run_id="second", session_id=sid)
    snapshot = runtime.question_state(
        sid, lambda e, eligible: sessions.questions.snapshot(sid, eligible)
    )
    assert snapshot["pending"] == []
    assert snapshot["unavailable_reason"] == "run_authority_unavailable"
    with pytest.raises(KeyError):
        sessions.answer_question(sid, q.question_id, "Use 6 mm")
    assert not q.ready.is_set() and q.selection is None


@pytest.mark.parametrize("closure", ["cancel", "terminal", "abandon"])
def test_closure_first_forbids_fresh_acceptance(runtime: BridgeRuntime, closure: str) -> None:
    sessions, sid, q = owned(runtime)
    if closure == "cancel":
        runtime._admission.request_cancel(q.run_id)
    elif closure == "terminal":
        # Independent durable writer, not HTTP Stop or event delivery.
        runtime._admission.ingest_terminal(q.run_id, "winner", TerminalState.FAILED)
    else:
        sessions.questions.abandon_run(q.run_id)
    with pytest.raises(KeyError):
        sessions.answer_question(sid, q.question_id, "Use 6 mm")
    assert not q.answered and q.selection is None
    assert (
        runtime.question_state(sid, lambda e, eligible: sessions.questions.snapshot(sid, eligible))[
            "pending"
        ]
        == []
    )


@pytest.mark.parametrize("closure", ["cancel", "terminal"])
def test_answer_reservation_orders_against_durable_writer_without_deadlock(
    runtime: BridgeRuntime, closure: str
) -> None:
    sessions, sid, q = owned(runtime)
    inside, release, writer_started, writer_done = Event(), Event(), Event(), Event()

    def reserve(_execution: Any, eligible: str | None) -> Any:
        inside.set()
        assert release.wait(5)
        return sessions.questions.answer(
            q.question_id, "Use 6 mm", session_id=sid, eligible_run=eligible
        )

    def close() -> None:
        writer_started.set()
        if closure == "terminal":
            runtime._admission.ingest_terminal(q.run_id, "terminal", TerminalState.COMPLETED)
        else:
            runtime._admission.request_cancel(q.run_id)
        writer_done.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        answer = pool.submit(runtime.question_state, sid, reserve)
        assert inside.wait(5)
        writer = pool.submit(close)
        assert writer_started.wait(5)
        try:
            assert not writer_done.wait(0.05), "durable writer crossed the acceptance read point"
        finally:
            release.set()
        assert answer.result(timeout=5)[1] is True
        writer.result(timeout=5)
    assert q.answered and q.selection == "Use 6 mm"
    loser = sessions.answer_question(sid, q.question_id, "Keep 5.5 mm")
    assert loser["accepted"] is False and loser["answer"] == "Use 6 mm"


def test_two_concurrent_answers_reserve_exactly_once(runtime: BridgeRuntime) -> None:
    sessions, sid, q = owned(runtime)

    def answer(value: str) -> dict[str, Any]:
        return sessions.answer_question(sid, q.question_id, value)

    with ThreadPoolExecutor(max_workers=2) as pool:
        answers = list(pool.map(answer, ["Use 6 mm", "Keep 5.5 mm"]))
    assert sorted(a["accepted"] for a in answers) == [False, True]
    assert answers[0]["answer"] == answers[1]["answer"] == q.selection
    sessions.questions.abandon_run(q.run_id)
    assert q.answered and not q.abandoned
