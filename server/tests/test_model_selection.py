"""Model wire/admission races with local fakes only; no provider probes."""

# White-box tests exercise the admission boundary rather than a UI disable flag.
# pyright: reportPrivateUsage=false
from __future__ import annotations

import copy
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from hephaestus.agent_bridge.app import BridgeRuntime
from hephaestus.agent_bridge.model_selection import (
    ModelSelectionError,
    SessionModelState,
    model_ref,
    model_state,
    revision,
)
from hephaestus.agent_bridge.protocol import ErrorCode
from hephaestus.agent_bridge.sessions import RunInFlightError
from hephaestus.agent_bridge.supervisor import SupervisorError
from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend
from hephaestus.http.errors import refusal_for
from hephaestus.testing.projects import scaffold_project
from hephaestus.testing.workspace import workspace

TEXT = {"provider_id": "fake", "model_id": "text"}
VISION = {"provider_id": "fake", "model_id": "vision"}


def initial_state() -> SessionModelState:
    return {
        "revision": {"epoch": "child-one", "version": 0},
        "current": {"provider_id": "fake", "model_id": "text", "name": "Text", "input": ["text"]},
        "selected": model_ref(TEXT),
        "pending_selection": None,
        "state": "ready",
        "reason": None,
    }


class SidecarDouble:
    def __init__(self) -> None:
        self.state = initial_state()
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls: list[str] = []
        self.hold: str | None = None
        self.fail: str | None = None

    def call(self, method: str, params: dict[str, Any], **_: Any) -> dict[str, Any]:
        self.calls.append(method)
        if method == "session.create":
            return {
                "session_id": params.get("session_id", "s"),
                "model_state": copy.deepcopy(self.state),
            }
        if method == "session.model.get":
            return {"model_state": copy.deepcopy(self.state)}
        if method == "session.model.set":
            self.state["state"] = "changing"
            self.state["revision"]["version"] += 1
            self.state["pending_selection"] = params["model"]
            if self.fail == "timeout":
                raise SupervisorError("session.model.set timed out after 1s with no response")
        if self.hold == method:
            self.entered.set()
            assert self.release.wait(5), "test must release the held operation"
        if method == "session.model.set":
            self.state["state"] = "ready"
            self.state["revision"]["version"] += 1
            self.state["selected"] = params["model"]
            self.state["current"] = {
                "provider_id": "fake",
                "model_id": "vision",
                "name": "Vision",
                "input": ["text", "image"],
            }
            self.state["pending_selection"] = None
            return {"model_state": copy.deepcopy(self.state)}
        if method == "session.prompt":
            if self.fail == "revision":
                raise SupervisorError(
                    "model changed",
                    error={
                        "code": ErrorCode.INVALID_PARAMS,
                        "message": "model changed",
                        "data": {"reason": "model_changed", "model_state": self.state},
                    },
                )
            return {"status": "completed"}
        raise AssertionError(method)


@pytest.fixture
def bridge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("HEPHAESTUS_NODE", sys.executable)
    runtime = BridgeRuntime(
        project_root=scaffold_project(tmp_path / "proj", name="models"),
        backend=UnsafeLocalBackend(),
        providers=[],
        dist_main=Path(__file__).with_name("fake_sidecar.py"),
    )
    sidecar = SidecarDouble()
    monkeypatch.setattr(runtime._sup, "call", sidecar.call)
    runtime.create_session("orchestrator", session_id="s", model=model_ref(TEXT))
    try:
        yield runtime, sidecar
    finally:
        sidecar.release.set()
        runtime.close()


@pytest.mark.parametrize("version", [True, False, -1, 1.2, "1", 2**53])
def test_revision_is_strict(version: Any) -> None:
    with pytest.raises(ModelSelectionError):
        revision({"epoch": "x", "version": version})


def test_wire_requires_named_absences_and_never_splits_model_labels() -> None:
    assert model_ref({"provider_id": "p/q", "model_id": "a/b"}) == {
        "provider_id": "p/q",
        "model_id": "a/b",
    }
    with pytest.raises(ModelSelectionError):
        model_state({"revision": {"epoch": "x", "version": 0}})
    with pytest.raises(ModelSelectionError):
        model_ref({"provider_id": "p", "model_id": "m", "effort": "high"})


def test_selection_reservation_refuses_send_and_second_selector_immediately(bridge: Any) -> None:
    runtime, sidecar = bridge
    sidecar.hold = "session.model.set"
    expected = revision(sidecar.state["revision"])
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(runtime.select_session_model, "s", VISION, expected)
        assert sidecar.entered.wait(5)
        try:
            document = runtime.session_model("s")
            assert document["model_state"]["state"] == "changing"
            assert not document["execution"]["admission_available"]
            with pytest.raises(ModelSelectionError, match="model change in progress"):
                runtime.prompt("s", "draft", expected_model_revision=expected)
            with pytest.raises(ModelSelectionError, match="model change in progress"):
                runtime.select_session_model("s", TEXT, expected)
            # A different session is not locked behind the selection.
            runtime.create_session("orchestrator", session_id="other", model=TEXT)
        finally:
            sidecar.release.set()
        assert pending.result(5)["model_state"]["current"]["input"] == ["text", "image"]
    assert "session.prompt" not in sidecar.calls
    with pytest.raises(ModelSelectionError, match="Review it before sending"):
        runtime.prompt("s", "draft", expected_model_revision=expected)


def test_prompt_wins_including_awaiting_user_and_cleanup(bridge: Any) -> None:
    runtime, sidecar = bridge
    sidecar.hold = "session.prompt"
    expected = revision(sidecar.state["revision"])
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(
            runtime.prompt, "s", "question", run_id="holding", expected_model_revision=expected
        )
        assert sidecar.entered.wait(5)
        try:
            with pytest.raises(RunInFlightError) as exc:
                runtime.select_session_model("s", VISION, expected)
            assert exc.value.run_id == "holding"
            assert exc.value.scope == "session"
        finally:
            sidecar.release.set()
        pending.result(5)
    assert "session.model.set" not in sidecar.calls


def test_timeout_does_not_release_or_replay_uncancellable_selection(bridge: Any) -> None:
    runtime, sidecar = bridge
    sidecar.fail = "timeout"
    expected = revision(sidecar.state["revision"])
    with pytest.raises(SupervisorError):
        runtime.select_session_model("s", VISION, expected)
    assert runtime.session_model("s")["model_state"]["state"] == "changing"
    with pytest.raises(ModelSelectionError):
        runtime.prompt("s", "unsafe")
    assert sidecar.calls.count("session.model.set") == 1
    # Only actual settlement reported by a fresh GET releases the reservation.
    sidecar.state["state"] = "uncertain"
    sidecar.state["reason"] = "model_selection_uncertain"
    sidecar.state["revision"]["version"] += 1
    document = runtime.session_model("s")
    assert not document["execution"]["admission_available"]
    with pytest.raises(ModelSelectionError, match="model selection uncertain"):
        runtime.prompt("s", "still unsafe")
    assert sidecar.calls.count("session.model.set") == 1


def test_sidecar_preflight_refusal_releases_admission_without_terminal_or_transcript(
    bridge: Any,
) -> None:
    runtime, sidecar = bridge
    sidecar.fail = "revision"
    before = runtime._admission.capacity()
    with pytest.raises(SupervisorError) as exc:
        runtime.prompt(
            "s",
            "stale",
            run_id="refused",
            expected_model_revision=revision(sidecar.state["revision"]),
        )
    assert runtime._admission.capacity() == before
    assert runtime._admission.get_terminal("refused") is None
    assert runtime.session_for_run("refused") is None
    assert not runtime._runs
    assert refusal_for(exc.value).reason == "model_changed"


def test_late_preselection_get_cannot_overwrite_committed_model_state(
    bridge: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, sidecar = bridge
    captured, release = threading.Event(), threading.Event()
    call = sidecar.call

    def delayed(method: str, params: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        result = call(method, params, **kwargs)
        if method == "session.model.get":
            captured.set()
            assert release.wait(5), "release the stale read"
        return result

    monkeypatch.setattr(runtime._sup, "call", delayed)
    with ThreadPoolExecutor(max_workers=1) as pool:
        old_read = pool.submit(runtime.session_model, "s")
        assert captured.wait(5)
        try:
            selected = runtime.select_session_model(
                "s", VISION, revision(sidecar.state["revision"])
            )
        finally:
            release.set()
        late = old_read.result(5)
    assert late["model_state"] == selected["model_state"]
    assert late["model_state"]["current"]["model_id"] == "vision"
    assert late["execution"]["admission_available"]


def test_new_model_errors_survive_unknown_session_recovery_classification(bridge: Any) -> None:
    runtime, _ = bridge
    exc = SupervisorError(
        "blocked",
        error={"code": ErrorCode.INVALID_PARAMS, "data": {"reason": "model_selection_uncertain"}},
    )
    assert runtime._refuse_by_name("s", exc, readopted=True, fallback="unknown_session") is exc


def test_http_explicit_choice_revision_and_keyless_switch(tmp_path: Path) -> None:
    with workspace(tmp_path / "http", agent=True) as web:
        assert web.post("/sessions", json={"profile": "orchestrator"}).status_code == 400
        catalog = web.get("/providers/models").json()
        proposal = catalog["proposed_default"]
        assert proposal["input"] == ["text"]
        created = web.post("/sessions", json={"profile": "orchestrator", "model": TEXT})
        assert created.status_code == 200, created.text
        body = created.json()
        sid = body["session_id"]
        expected = body["model_state"]["revision"]
        assert body["execution"]["admission_available"]
        assert web.post(f"/sessions/{sid}/prompt", json={"text": "draft"}).status_code == 428
        assert (
            web.request("PUT", f"/sessions/{sid}/model", json={"model": VISION}).status_code == 428
        )
        switched = web.request(
            "PUT",
            f"/sessions/{sid}/model",
            json={"model": VISION, "expected_model_revision": expected},
            key="ignored-even-if-not-a-uuid",
        )
        assert switched.status_code == 200, switched.text
        assert switched.json()["model_state"]["current"]["input"] == ["text", "image"]
        duplicate = web.request(
            "PUT",
            f"/sessions/{sid}/model",
            json={"model": VISION, "expected_model_revision": expected},
            key="ignored-even-if-not-a-uuid",
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["reason"] == "model_changed"  # never key replay
        extra = web.request(
            "PUT",
            f"/sessions/{sid}/model",
            json={
                "model": TEXT,
                "expected_model_revision": switched.json()["model_state"]["revision"],
                "effort": "high",
            },
        )
        assert extra.status_code == 400
        assert extra.json()["reason"] == "invalid_params"
        stale = web.post(
            f"/sessions/{sid}/prompt", json={"text": "draft", "expected_model_revision": expected}
        )
        assert stale.status_code == 409
        assert stale.json()["reason"] == "model_changed"
        assert stale.json()["model_state"]["current"]["model_id"] == "vision"
        assert "execution" in stale.json()
        assert "data" not in stale.json()
        assert web.agent is not None and web.agent.prompts == []
        assert (
            web.post(
                "/sessions",
                json={"profile": "orchestrator", "resume": True, "session_id": sid, "model": TEXT},
            ).status_code
            == 400
        )
        # No model ID parsing, unknown fields, or boolean revision coercion.
        invalid = web.request(
            "PUT",
            f"/sessions/{sid}/model",
            json={"model": VISION, "expected_model_revision": {"epoch": "x", "version": True}},
        )
        assert invalid.status_code == 400
        unknown = web.request(
            "PUT",
            f"/sessions/{sid}/model",
            json={
                "model": {"provider_id": "fake", "model_id": "absent"},
                "expected_model_revision": switched.json()["model_state"]["revision"],
            },
        )
        assert unknown.status_code == 404
        assert unknown.json()["reason"] == "model_unknown"
