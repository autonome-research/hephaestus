"""§7A.10A HTTP admission: closed controls, immutable choices, exact request text."""

import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from hephaestus.agent_bridge.turn_controls import (
    DfmMode,
    InteractionMode,
    ThinkingLevel,
    TurnControls,
    parse_turn_controls,
)
from hephaestus.testing.workspace import workspace


@pytest.mark.parametrize("field", ["interaction_mode", "dfm_mode", "thinking_level"])
@pytest.mark.parametrize("value", [None, True, 1, [], {}, "", "unknown", "HIGH"])
def test_malformed_controls_refuse_before_admission(
    tmp_path: Path, field: str, value: object
) -> None:
    with workspace(tmp_path / "proj", agent=True) as web:
        agent = web.agent
        assert agent is not None
        sid = agent.create_session("orchestrator")
        revision = web.get(f"/sessions/{sid}/model").json()["model_state"]["revision"]
        result = web.post(
            f"/sessions/{sid}/prompt",
            json={"text": "make 12 mm", "expected_model_revision": revision, field: value},
        )
        assert result.status_code == 400
        assert result.json()["reason"] == "invalid_params"
        assert agent.prompts == []
        assert agent.turn_controls == []
        assert web.get(f"/sessions/{sid}/model").json()["execution"]["active_run_id"] is None


def test_controls_and_defaults_reach_backend_without_changing_text(tmp_path: Path) -> None:
    with workspace(tmp_path / "proj", agent=True) as web:
        agent = web.agent
        assert agent is not None
        sid = agent.create_session("orchestrator")
        revision = web.get(f"/sessions/{sid}/model").json()["model_state"]["revision"]
        choices = [TurnControls()]
        choices += [
            TurnControls(mode, dfm, effort)
            for mode in InteractionMode
            for dfm in DfmMode
            for effort in ThinkingLevel
        ]
        for i, controls in enumerate(choices):
            body = {"text": "make 12 mm", "expected_model_revision": revision}
            if i:
                body.update(controls.wire())
            response = web.post(f"/sessions/{sid}/prompt", json=body)
            assert response.status_code == 200, response.text
            assert agent.prompts[-1] == ("make 12 mm", None)
            assert agent.turn_controls[-1] == controls
        # These routes remain at-least-once: equal words/options are two turns.
        assert len(agent.prompts) == len(choices)
        refused = web.post(
            f"/sessions/{sid}/prompt",
            json={
                "text": "make 12 mm",
                "expected_model_revision": revision,
                "thinkingLevel": "low",
            },
        )
        assert refused.status_code == 400
        assert len(agent.prompts) == len(choices)


def test_bridge_forwards_admitted_controls_but_binds_only_operator_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hephaestus.agent_bridge.app import BridgeRuntime
    from hephaestus.agent_bridge.cad_ops import run_request_text
    from hephaestus.agent_bridge.supervisor import Supervisor
    from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend
    from hephaestus.testing.projects import scaffold_project

    monkeypatch.setenv("HEPHAESTUS_NODE", sys.executable)
    seen: list[dict[str, object]] = []
    original = Supervisor.call

    def capture(
        supervisor: Supervisor,
        method: str,
        params: dict[str, object] | None = None,
        *,
        timeout: float | None = None,
    ) -> object:
        if method == "session.prompt":
            assert params is not None
            assert run_request_text("control-run") == "operator 12 mm"
            seen.append(dict(params))
        return original(supervisor, method, params, timeout=timeout)

    monkeypatch.setattr(Supervisor, "call", capture)
    runtime = BridgeRuntime(
        # No tool calls or CAD execution: only the scripted Python IPC peer.
        backend=UnsafeLocalBackend(),
        project_root=scaffold_project(tmp_path / "proj", name="controls"),
        providers=[{"id": "fake", "kind": "openai", "base_url": "http://127.0.0.1:9/v1"}],
        dist_main=Path(__file__).with_name("fake_sidecar.py"),
    )
    controls = TurnControls(InteractionMode.PLAN, DfmMode.MACHINING, ThinkingLevel.HIGH)
    runtime.start()
    try:
        sid = runtime.create_session("orchestrator", session_id="control-session")
        result = runtime.prompt(
            sid,
            "operator 12 mm",
            run_id="control-run",
            context="workspace 99 mm",
            turn_controls=controls,
        )
        assert result.status == "completed"
        assert seen == [
            {
                "session_id": sid,
                "run_id": "control-run",
                "prompt": "operator 12 mm",
                "context": "workspace 99 mm",
                **controls.wire(),
            }
        ]
        assert run_request_text("control-run") is None
    finally:
        runtime.close()


def test_turn_controls_are_frozen() -> None:
    controls = parse_turn_controls({})
    assert controls.wire() == {
        "interaction_mode": "modeling",
        "dfm_mode": "off",
        "thinking_level": "medium",
    }
    for field in controls.wire():
        with pytest.raises(FrozenInstanceError):
            setattr(controls, field, "changed")
