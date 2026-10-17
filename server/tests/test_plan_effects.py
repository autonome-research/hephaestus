"""Plan's real sidecar/dispatch/store effects over synthetic stored geometry.

Only pixels/geometry are synthetic (the explicit refusing-executor fixture).
Publication, deadline finalization and the pinned Pi tool gate are real. This is
not CAD/raster acceptance; no kernel, container or external provider is started.
"""

import json
from pathlib import Path

import pytest
from _plan_render_fixture import current_source, render_project
from hephaestus.agent_bridge.app import BridgeRuntime
from hephaestus.agent_bridge.cad_ops import CadOps
from hephaestus.agent_bridge.delegation import DelegationRow, DelegationService, Delivery
from hephaestus.agent_bridge.dispatch import ToolDispatcher
from hephaestus.agent_bridge.supervisor import pid_alive
from hephaestus.agent_bridge.turn_controls import InteractionMode, TurnControls
from hephaestus.core.project_store.store import ProjectStore, blob_hash_of_ref
from hephaestus.testing.delegation_gates import AllowAllGate
from hephaestus.testing.doubles import FakeClock
from hephaestus.testing.fake_openai import start_fake_openai
from hephaestus.testing.ledger import seed_minimal_ledger
from hephaestus.testing.sidecar import build_agent_dist
from opstore.types import TerminalState


def test_plan_publishes_evidence_and_finalizes_deadline_without_modeling_writes(
    tmp_path: Path,
) -> None:
    built = build_agent_dist()
    if built is None:
        pytest.fail("packaged sidecar required for Plan effects regression")
    with render_project(tmp_path) as (project, backend, renderer):
        store, root = project.store, project.layout.root
        cad = CadOps(
            project.layout,
            store,
            backend=backend,
            renderer=renderer,
            render_size=(16, 16),
        )
        seed_minimal_ledger(cad)
        clock = FakeClock()
        service = DelegationService(store.admission, store.db, gate=AllowAllGate(), clock=clock)
        # Existing work, admitted BEFORE Plan. Status must never dispatch it.
        row = service.delegate(
            "prior-parent",
            "widget",
            "prior modeling request",
            delivery=Delivery.FOLLOW_UP,
            deadline_seconds=1,
            invocation="prior-invocation",
            parent_session_id="planner",
        )
        assert isinstance(row, DelegationRow)
        assert store.admission.get_terminal(row.child_run_id) is None
        clock.advance(2)
        project_store = ProjectStore(project.layout, store)
        dispatcher = ToolDispatcher(project_store, cad=cad, delegation=service)
        source_ref = current_source(project)
        source_bytes = store.blobs.get(blob_hash_of_ref(source_ref))

        def inputs() -> dict[str, bytes]:
            return {
                str(p.relative_to(root)): p.read_bytes()
                for p in root.rglob("*")
                if p.is_file() and ".heph" not in p.relative_to(root).parts
            }

        assert not store.db.conn.execute(
            "SELECT 1 FROM tp_artifact_kinds WHERE kind = 'render'"
        ).fetchall()
        before_inputs = inputs()
        # All live CAS pointers, including build, parameter and requirements state.
        before_pointers = list(store.db.conn.execute("SELECT * FROM pointers ORDER BY name"))
        fake = start_fake_openai([])
        bridge = BridgeRuntime(
            project_root=root,
            providers=[fake.provider_spec()],
            dist_main=built[0],
            store=store,
            project_store=project_store,
            cad=cad,
            dispatcher=dispatcher,
        )
        try:
            bridge.start()
            pid = bridge.child_pid
            assert pid_alive(pid)
            sid = bridge.create_session("orchestrator", session_id="planner")
            fake.set_script(
                [
                    {
                        "kind": "tool_calls",
                        "calls": [
                            {
                                "name": "inspect_part",
                                "arguments": {"name": "widget", "views": ["iso"]},
                            },
                            {
                                "name": "get_delegation_status",
                                "arguments": {"delegation_ref": row.delegation_ref},
                            },
                            {
                                "name": "query_snapshot",
                                "arguments": {"name": "widget", "question": "describe"},
                            },
                            {"name": "create_part", "arguments": {"name": "forbidden"}},
                            {
                                "name": "set_params",
                                "arguments": {"scope": "project", "values": {"wall": 3}},
                            },
                            {
                                "name": "delegate_part_agent",
                                "arguments": {
                                    "part": "widget",
                                    "prompt": "change geometry",
                                    "delivery": "follow_up",
                                },
                            },
                            {"name": "build_part", "arguments": {"name": "widget"}},
                            {"name": "record_requirements", "arguments": {"entries": []}},
                        ],
                    },
                    {"kind": "text", "chunks": ["inspection finished"]},
                ]
            )
            result = bridge.prompt(
                sid, "inspect only", turn_controls=TurnControls(InteractionMode.PLAN)
            )
            assert result.status == "completed"
            assert len(fake.requests) == 2  # no vision or delegated modeling request
            for name in (
                "create_part",
                "set_params",
                "delegate_part_agent",
                "build_part",
                "record_requirements",
            ):
                assert f"Tool {name} not found" in fake.requests[-1].body_text
            assert "capability_not_available" in fake.requests[-1].body_text
            assert renderer.operations == ["rgb"]
            assert "timed_out" in fake.requests[-1].body_text
            terminal = store.admission.get_terminal(row.child_run_id)
            assert terminal is not None and terminal.state is TerminalState.TIMED_OUT
            assert service.get(row.delegation_ref).terminal_state is TerminalState.TIMED_OUT
            # Terminal still holds the old child's slot pending acknowledgment.
            assert store.admission.active_count() == 1
            for event in result.events:
                if event["kind"] == "tool_result" and event["payload"].get("toolName") in (
                    "inspect_part",
                    "get_delegation_status",
                ):
                    assert event["payload"].get("isError") is False, event["payload"]
            refs = [
                ref
                for event in result.events
                if event["kind"] == "tool_result"
                if event["payload"].get("toolName") == "inspect_part"
                for ref in json.loads(event["payload"]["text"])["render_artifact_refs"]
            ]
            assert refs, result.events
            for ref in refs:
                assert (
                    store.db.conn.execute(
                        "SELECT 1 FROM tp_artifact_kinds WHERE kind = 'render' AND blob_hash = ?",
                        (blob_hash_of_ref(ref),),
                    ).fetchone()
                    is not None
                )
            evidence = {ref: store.blobs.get(blob_hash_of_ref(ref)) for ref in refs}
            assert all(data.startswith(b"\x89PNG\r\n\x1a\n") for data in evidence.values())
            assert inputs() == before_inputs
            assert (
                list(store.db.conn.execute("SELECT * FROM pointers ORDER BY name"))
                == before_pointers
            )
            assert current_source(project) == source_ref
            assert store.blobs.get(blob_hash_of_ref(source_ref)) == source_bytes
            # Repeated inspection/status is immutable and terminal-idempotent.
            again = cad.inspect_part("widget", views=["iso"])
            assert again["render_artifact_refs"] == refs
            assert {ref: store.blobs.get(blob_hash_of_ref(ref)) for ref in refs} == evidence
            assert (
                service.check_deadline(row.delegation_ref).terminal_state is TerminalState.TIMED_OUT
            )
            assert store.admission.get_terminal(row.child_run_id) == terminal
            fake.raise_script_error()
        finally:
            bridge.close()
            fake.close()
        assert not pid_alive(pid)
