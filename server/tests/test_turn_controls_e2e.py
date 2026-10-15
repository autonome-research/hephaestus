"""Real HTTP -> packaged sidecar -> pinned Pi -> Python, with loopback replies.

No CAD calls: Plan attempts create_part (must never dispatch), Modeling creates
only a source file. The fixture and all child/provider processes are owned here.
This supplements, and does not replace, the renderer-pinned G4 browser suite.
"""

from pathlib import Path

import pytest
from hephaestus.agent_bridge.app import BridgeRuntime
from hephaestus.agent_bridge.supervisor import pid_alive
from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend
from hephaestus.testing.fake_openai import TurnResolver, start_fake_openai
from hephaestus.testing.sidecar import build_agent_dist
from hephaestus.testing.workspace import workspace


def test_http_turn_controls_through_packaged_sidecar(tmp_path: Path) -> None:
    built = build_agent_dist()
    if built is None:
        pytest.skip("node/pnpm unavailable; packaged sidecar required")
    fake = start_fake_openai([])
    try:
        with workspace(tmp_path / "proj") as web:
            project_config = (web.root / "hephaestus.toml").read_bytes()
            provider = fake.provider_spec()
            provider["models"][0]["reasoning"] = True
            bridge = BridgeRuntime(
                project_root=web.root,
                backend=UnsafeLocalBackend(),
                providers=[provider],
                dist_main=built[0],
            )
            bridge.start()
            pid = bridge.child_pid
            try:
                web.runtime.attach_sessions(bridge)
                created = web.post(
                    "/sessions",
                    json={
                        "profile": "orchestrator",
                        "model": {"provider_id": fake.provider_id, "model_id": fake.model_id},
                    },
                )
                assert created.status_code == 200, created.text
                sid = created.json()["session_id"]
                revision = web.get(f"/sessions/{sid}/model").json()["model_state"]["revision"]
                route = f"/sessions/{sid}/prompt"
                body = {
                    "text": "make 12 mm",
                    "expected_model_revision": revision,
                    "interaction_mode": "plan",
                    "dfm_mode": "sheet_metal",
                    "thinking_level": "high",
                }
                assert web.post(route, json=body, token=None).status_code == 401
                assert web.post(route, json={**body, "dfm_mode": "invalid"}).status_code == 400
                assert fake.requests == []
                script: list[TurnResolver] = [
                    {
                        "kind": "tool_calls",
                        "calls": [
                            {"name": "create_part", "arguments": {"name": "planned"}},
                            {"name": "read_part", "arguments": {"name": "widget"}},
                        ],
                    },
                    {"kind": "text", "chunks": ["done"]},
                ]
                fake.set_script(script)
                refused_tool = web.post(route, json=body)
                assert refused_tool.status_code == 200, refused_tool.text
                assert refused_tool.json()["run_status"] == "completed"
                assert not (web.root / "parts" / "planned.py").exists()
                assert any(
                    event["kind"] == "tool_result"
                    and event["payload"].get("toolName") == "read_part"
                    and event["payload"].get("isError") is False
                    for event in refused_tool.json()["events"]
                )
                assert "create_part" not in fake.requests[0].tool_names
                assert "Tool create_part not found" in fake.requests[1].body_text
                assert '"reasoning_effort":"high"' in fake.requests[0].body_text
                assert "sheet metal" in fake.requests[0].body_text
                history = web.get(f"/sessions/{sid}/history").json()
                assert history["user_prompts"][0]["text"] == "make 12 mm"
                assert history["user_prompts"][0]["envelope"] is None
                assert history["user_prompts"][0]["turn_controls"] == {
                    key: body[key] for key in ("interaction_mode", "dfm_mode", "thinking_level")
                }

                fake.set_script(script)
                # Older callers omit controls: Modeling/off/medium, not last turn's choices.
                response = web.post(
                    route, json={"text": "make 12 mm", "expected_model_revision": revision}
                )
                assert response.status_code == 200, response.text
                assert response.json()["run_status"] == "completed"
                assert (web.root / "parts" / "planned.py").is_file()
                assert "create_part" in fake.requests[2].tool_names
                assert '"reasoning_effort":"medium"' in fake.requests[2].body_text
                assert len(fake.requests) == 4
                assert (web.root / "hephaestus.toml").read_bytes() == project_config
                fake.raise_script_error()
            finally:
                bridge.close()
                assert not pid_alive(pid), "owned sidecar outlived close"
    finally:
        fake.close()
