"""Session execution/settlement evidence, using only a local fake sidecar."""

# White-box race tests inject admissions and notifications between transport steps.
# pyright: reportPrivateUsage=false

import copy
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from hephaestus.agent_bridge.app import BridgeRuntime, _Run
from hephaestus.agent_bridge.events import HephaestusEvent
from hephaestus.agent_bridge.sessions import RunInFlightError
from hephaestus.agent_bridge.supervisor import SupervisorError
from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend
from hephaestus.testing.projects import scaffold_project
from opstore.types import TerminalState


@pytest.fixture
def runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[BridgeRuntime]:
    monkeypatch.setenv("HEPHAESTUS_NODE", sys.executable)
    runtime = BridgeRuntime(
        project_root=scaffold_project(tmp_path / "project", name="evidence"),
        backend=UnsafeLocalBackend(),  # Explicit test-only executor; no default posture.
        providers=[{"id": "fake", "kind": "openai", "base_url": "http://127.0.0.1:9/v1"}],
        dist_main=Path(__file__).with_name("fake_sidecar.py"),
    )
    runtime.start()
    try:
        yield runtime
    finally:
        runtime.close()


def test_crash_and_conflicting_terminal_project_the_durable_winner(runtime: BridgeRuntime) -> None:
    sid = runtime.create_session("orchestrator", session_id="evidence-session")
    try:
        runtime._admit_turn(_Run(run_id="zero-event-run", session_id=sid), None)
        runtime._admission.admit_run("zero-event-run")
        runtime._sup.track_run("zero-event-run")
        assert runtime.sessions()[0]["execution"]["active_run_id"] == "zero-event-run"
        with pytest.raises(SupervisorError):
            runtime._sup.call("crash", {})
        evidence = runtime.sessions()[0]["execution"]
        assert evidence["terminal"]["state"] == "interrupted"
        assert evidence["active_run_id"] is None
        # Terminal does NOT silently clear the per-session runtime guard.
        assert evidence["admission_available"] is False
        observed: list[HephaestusEvent] = []
        runtime._pump.add_tap(observed.append)
        runtime._on_notification(
            "terminal",
            {
                "run_id": "zero-event-run",
                "terminal_id": "late-success",
                "state": "completed",
                "payload": {},
            },
        )
        assert observed[-1].payload is not None
        assert observed[-1].payload["state"] == "interrupted"
        assert observed[-1].payload["terminal_id"] == "interrupted:zero-event-run"
        assert runtime.sessions()[0]["execution"]["terminal"] == evidence["terminal"]
        assert runtime._runs["zero-event-run"].terminal == evidence["terminal"]
    finally:
        runtime._runs.pop("zero-event-run", None)


def test_late_previous_terminal_cannot_replace_current_ownership(runtime: BridgeRuntime) -> None:
    sid = runtime.create_session("orchestrator", session_id="ordering-session")
    empty = runtime.sessions()[0]["execution"]
    assert empty["run_id"] is None
    assert empty["terminal"] is None
    assert empty["admission_available"] is True
    runtime.prompt(sid, "local fake turn", run_id="old")
    settled = runtime.sessions()[0]["execution"]
    runtime._admit_turn(_Run(run_id="new", session_id=sid), None)
    runtime._admission.admit_run("new")
    active = runtime.sessions()[0]["execution"]
    runtime._on_notification(
        "terminal",
        {
            "run_id": "old",
            "terminal_id": "late-old",
            "state": "failed",
            "payload": {},
        },
    )
    current = runtime.sessions()[0]["execution"]
    assert current["run_id"] == current["active_run_id"] == "new"
    assert current["terminal"] is None
    assert current["admission_available"] is False
    assert empty["version"] < settled["version"] < active["version"] < current["version"]
    assert empty["epoch"] == current["epoch"]
    with pytest.raises(RunInFlightError):
        runtime.prompt(sid, "must not be sent", run_id="refused")
    assert runtime.sessions()[0]["execution"]["run_id"] == "new"


def test_cancel_request_is_not_a_terminal_and_capacity_is_reported(runtime: BridgeRuntime) -> None:
    sid = runtime.create_session("orchestrator", session_id="capacity-session")
    runtime._admit_turn(_Run(run_id="active", session_id=sid), None)
    runtime._admission.admit_run("active")
    runtime.cancel("active")
    execution = runtime.sessions()[0]["execution"]
    assert execution["active_run_id"] == "active"
    assert execution["terminal"] is None
    other = runtime.create_session("part", part="widget", session_id="other-session")
    for i in range(runtime._admission.capacity()):
        runtime._admission.admit_run(f"occupy-{i}")
    rows = {row["session_id"]: row["execution"] for row in runtime.sessions()}
    assert rows[other]["active_run_id"] is None
    assert rows[other]["admission_available"] is False


def test_blocking_response_uses_durable_winner_not_late_rpc_status(
    runtime: BridgeRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid = runtime.create_session("orchestrator", session_id="response-session")

    def reply(method: str, params: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        assert method == "session.prompt"
        rid = params["run_id"]
        runtime._on_notification(
            "terminal",
            {
                "run_id": rid,
                "terminal_id": "winner",
                "state": "failed",
                "payload": {"reason": "backpressure_cancel"},
            },
        )
        runtime._on_notification(
            "terminal",
            {
                "run_id": rid,
                "terminal_id": "late",
                "state": "completed",
                "payload": {},
            },
        )
        return {"status": "completed"}

    monkeypatch.setattr(runtime, "_call_for_session", reply)
    result = runtime.prompt(sid, "local only", run_id="conflict")
    assert result.status == "failed"
    assert result.terminal == runtime.sessions()[0]["execution"]["terminal"]
    assert result.terminal is not None
    assert result.terminal["terminal_id"] == "winner"
    assert result.terminal["payload"] == {"reason": "backpressure_cancel"}


@pytest.mark.parametrize("state", list(TerminalState))
def test_history_refresh_overlays_only_explicitly_linked_durable_evidence(
    runtime: BridgeRuntime,
    monkeypatch: pytest.MonkeyPatch,
    state: TerminalState,
) -> None:
    sid = runtime.create_session("orchestrator", session_id="history-session")
    runtime._admit_turn(_Run(run_id="linked", session_id=sid), None)
    runtime._admission.admit_run("linked")
    original: dict[str, Any] = {
        "events": [],
        "cursor": None,
        "end_cursor": "opaque",
        "done": True,
        "user_prompts": [
            {
                "turn": 0,
                "seq": 0,
                "text": "go",
                "run_id": "linked",
                "outcome": {"state": "completed"},
            },
            {"turn": 1, "seq": 0, "text": "legacy unknown"},
            {"turn": 2, "seq": 0, "text": "same text", "run_id": "unsettled"},
        ],
    }

    def page(method: str, params: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        assert method == "history.page"
        assert params == {"session_id": sid, "after": "opaque"}
        return copy.deepcopy(original)

    monkeypatch.setattr(runtime, "_call_for_session", page)
    active = runtime.history_page(sid, after="opaque")
    assert all("outcome" not in prompt for prompt in active["user_prompts"])
    runtime._admission.ingest_terminal("linked", "winner", state, {"reason": "recorded reason"})
    settled = runtime.history_page(sid, after="opaque")
    assert settled["events"] == []
    assert settled["end_cursor"] == "opaque"
    assert settled["user_prompts"][0]["outcome"] == {
        "state": "error" if state == TerminalState.FAILED else str(state),
        "message": "recorded reason",
    }
    assert all("outcome" not in prompt for prompt in settled["user_prompts"][1:])
