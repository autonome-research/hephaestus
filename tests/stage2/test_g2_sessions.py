"""G2 session isolation matrix.

Gate clause: *"Session tests prove per-part isolation, project delegation,
quick-edit parentage, one leased cross-process writer per Pi JSONL with safe
stale-owner recovery, app-owned credentials/resources, and that no built-in
coding tool, ambient extension, unapproved provider environment key, or global
config is active."*

The matrix, in the order the clause lists it:

1. **per-part isolation** — two persistent part sessions live in one sidecar,
   each with its own persisted Pi JSONL directory and its own authz principal;
2. **project orchestration** — only the orchestrator can hand work to a part
   session, and the child's terminal evidence comes back to it;
3. **quick-edit parentage** — the scoped child is threaded to its parent part
   session, carries artifact-bound context, and gets no orchestrator tools;
4. **single writer** — one leased owner per session; a second *process* is
   refused with structured ``session_busy``, a live owner past TTL is still
   refused, and only a confirmed-dead owner's lease is reclaimed;
5. **app-owned everything** — a hostile ambient environment (global Pi config
   dir, ambient provider keys, an attempt to redirect the agent dir) changes
   nothing: auth/model state stays under the project, the model is offered only
   the generated CAD tools, and no built-in coding tool or ambient extension is
   active.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from _g2 import (
    FakeClock,
    FakeLiveness,
    G2Harness,
    RequestInfo,
    owner,
    text,
    tool_call,
)
from hephaestus.agent_bridge.admission import bridge_store_config
from hephaestus.agent_bridge.sessions import (
    QuickEditRequest,
    ResolvedSelection,
    SessionBusyError,
    SessionProfile,
    SessionService,
    profile_for,
    session_ref,
)
from hephaestus.agent_bridge.supervisor import BASE_ENV_VARS, build_minimal_env

from opstore import OpStore

WIDGET = """PARAMS = {"w": Param(20.0, min=5.0, max=50.0)}

body = Box(p.w, 10.0, 4.0)
body.label = "body"
part.geometry = body
"""


# --------------------------------------------------------------------------
# 1. per-part isolation


def test_two_part_sessions_are_isolated_in_one_sidecar(harness: G2Harness) -> None:
    for name in ("widget", "bracket"):
        (harness.project_root / "parts" / f"{name}.py").write_text(WIDGET, encoding="utf-8")

    widget = harness.create_session("part", part="widget", session_id="g2-part-widget")
    bracket = harness.create_session("part", part="bracket", session_id="g2-part-bracket")
    assert widget != bracket

    harness.set_script([tool_call("read_part", {"name": "widget"}, "call_0"), text("widget ok")])
    first = harness.prompt(widget, "read your part", timeout=300)
    harness.set_script([tool_call("read_part", {"name": "bracket"}, "call_0"), text("bracket ok")])
    second = harness.prompt(bracket, "read your part", timeout=300)

    assert first.status == "completed" and second.status == "completed"
    records = harness.recorder.by_tool("read_part")
    assert [record.session_id for record in records] == [widget, bracket]
    assert [record.arguments["name"] for record in records] == ["widget", "bracket"]
    assert all(record.ok for record in records)
    # Each persistent session owns a separate Pi JSONL directory.
    sessions_dir = harness.project_root / ".heph" / "sessions"
    assert (sessions_dir / widget).is_dir()
    assert (sessions_dir / bracket).is_dir()
    # The two runs never share a run id, so their events never cross.
    assert first.run_id != second.run_id


# --------------------------------------------------------------------------
# 2. project orchestration: only the orchestrator hands work to a part


def test_orchestrator_hands_work_to_a_part_session(harness: G2Harness) -> None:
    (harness.project_root / "parts" / "widget.py").write_text(WIDGET, encoding="utf-8")
    seen: dict[str, Any] = {}

    def after(info: RequestInfo) -> dict[str, Any]:
        from _g2 import last_tool_result

        seen["result"] = last_tool_result(info)
        return text("handed off")

    harness.set_script(
        [
            tool_call(
                "delegate_part_agent",
                {"part": "widget", "prompt": "make it 30 mm wide", "delivery": "prompt"},
                "call_0",
            ),
            after,
        ]
    )
    session_id = harness.create_session("orchestrator", session_id="g2-orch-handoff")
    result = harness.prompt(session_id, "hand the widget to its part agent", timeout=600)

    assert result.status == "completed"
    outcome = seen["result"]
    assert outcome["status"] == "completed"
    assert outcome["part_session_id"] == "part:widget"
    assert outcome["child_run_id"] and outcome["delegation_ref"]
    assert outcome["result_artifact_ref"], "the parent must receive child terminal evidence"


# --------------------------------------------------------------------------
# 3. quick-edit parentage


class _Resolver:
    """Stage-1 selection resolution stand-in: artifact-bound source + crop."""

    def __init__(self, part: str) -> None:
        self.part = part

    def resolve(self, request: QuickEditRequest) -> ResolvedSelection:
        return ResolvedSelection(
            part=self.part,
            source="# artifact-bound source, not live geometry\n",
            provenance="tag:top_face",
            crop_artifact_ref="artifact:render:sha256:" + "c" * 64,
        )


def test_quick_edit_child_is_threaded_to_its_parent_part_session(tmp_path: Path) -> None:
    clock = FakeClock()
    store = OpStore.create(tmp_path / "heph", bridge_store_config(), clock=clock)
    try:
        service = SessionService(store.leases, clock=clock)
        lease, context = service.spawn_quick_edit(
            QuickEditRequest(
                part="widget",
                build_artifact_ref="artifact:build:sha256:" + "b" * 64,
                selection_artifact_ref="artifact:bundle:sha256:" + "e" * 64,
                selection_id="sel-7",
            ),
            _Resolver("widget"),
            parent_session_id="part:widget",
            child_session_id="quick:widget:1",
            owner=owner(4242),
            ttl_s=60,
        )
        assert lease.profile is SessionProfile.QUICK_EDIT
        assert context.parent_session_id == "part:widget"
        assert context.part == "widget"
        assert "artifact-bound" in context.source
        assert context.provenance == "tag:top_face"
        assert context.crop_artifact_ref.startswith("artifact:render:")
        # The child holds its own single-writer lease, distinct from the parent's.
        assert service.owner("quick:widget:1") == owner(4242)
        assert service.owner("part:widget") is None
        assert session_ref("quick:widget:1") == "session:quick:widget:1"
        # A quick-edit child is a scoped, non-delegating profile.
        assert profile_for(SessionProfile.QUICK_EDIT).can_delegate is False
        assert profile_for(SessionProfile.QUICK_EDIT).tools_profile == "quick_edit"
    finally:
        store.close()


def test_quick_edit_child_session_runs_scoped_on_the_real_bridge(harness: G2Harness) -> None:
    (harness.project_root / "parts" / "widget.py").write_text(WIDGET, encoding="utf-8")
    parent = harness.create_session("part", part="widget", session_id="g2-qe-parent")
    child = harness.create_session("quick_edit", part="widget", session_id="g2-qe-child")
    assert parent != child

    harness.set_script([tool_call("read_part", {"name": "widget"}, "call_0"), text("scoped")])
    result = harness.prompt(child, "look at the selected face", timeout=300)
    assert result.status == "completed"
    record = harness.recorder.first("read_part")
    assert record.session_id == child and record.ok
    # Both sessions persist independently under .heph/sessions.
    sessions_dir = harness.project_root / ".heph" / "sessions"
    assert (sessions_dir / parent).is_dir() and (sessions_dir / child).is_dir()


# --------------------------------------------------------------------------
# 4. one leased writer per Pi JSONL + stale-owner recovery


def test_single_leased_writer_and_stale_owner_recovery(tmp_path: Path) -> None:
    clock = FakeClock()
    liveness = FakeLiveness()
    first_process = OpStore.create(
        tmp_path / "heph", bridge_store_config(), clock=clock, liveness=liveness
    )
    # A SECOND connection to the same state.db models a second process.
    second_process = OpStore.open(
        first_process.root, first_process.config, clock=clock, liveness=liveness
    )
    try:
        owner_a = SessionService(first_process.leases, clock=clock)
        owner_b = SessionService(second_process.leases, clock=clock)

        held = owner_a.acquire("part:widget", SessionProfile.PART, owner(101), ttl_s=30)
        assert owner_a.owner("part:widget") == owner(101)

        # Second process: structured session_busy, never a second writer.
        with pytest.raises(SessionBusyError) as exc:
            owner_b.acquire("part:widget", SessionProfile.PART, owner(202), ttl_s=30)
        assert exc.value.code == "session_busy"
        assert exc.value.session_id == "part:widget"

        # A LIVE owner past its TTL is still the owner (liveness, not clock, decides).
        clock.advance(120)
        with pytest.raises(SessionBusyError):
            owner_b.acquire("part:widget", SessionProfile.PART, owner(202), ttl_s=30)

        # Only a confirmed-dead owner's stale lease is reclaimed.
        liveness.kill(owner(101))
        recovered = owner_b.acquire("part:widget", SessionProfile.PART, owner(202), ttl_s=30)
        assert recovered.session_id == "part:widget"
        assert owner_b.owner("part:widget") == owner(202)

        # The dead owner's heartbeat cannot resurrect its writer role.
        with pytest.raises(Exception):  # noqa: B017 - any structured refusal is fine
            owner_a.heartbeat(held)
    finally:
        second_process.close()
        first_process.close()


# --------------------------------------------------------------------------
# 5. app-owned credentials/resources; no ambient anything


def test_minimal_env_drops_every_unapproved_variable() -> None:
    env = build_minimal_env(
        frozenset({"HEPH_APPROVED_KEY"}),
        source={
            "PATH": "/usr/bin",
            "HOME": "/home/u",
            "LANG": "C",
            "HEPH_APPROVED_KEY": "approved",
            "ANTHROPIC_API_KEY": "ambient-must-not-leak",
            "OPENAI_API_KEY": "ambient-must-not-leak",
            "PI_CODING_AGENT_DIR": "/hostile/pi",
            "XDG_CONFIG_HOME": "/hostile/xdg",
            "NODE_OPTIONS": "--require /hostile/preload.js",
            "HEPHAESTUS_AGENT_DIR": "/hostile/agent",
        },
        extra={"HEPHAESTUS_AGENT_DIR": "/app/owned"},
    )
    assert set(env) <= set(BASE_ENV_VARS) | {"HEPH_APPROVED_KEY", "HEPHAESTUS_AGENT_DIR"}
    assert {"PATH", "HOME", "LANG"} <= set(env)
    assert env["HEPH_APPROVED_KEY"] == "approved"
    assert env["HEPHAESTUS_AGENT_DIR"] == "/app/owned"  # app-owned value wins
    for hostile in (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "PI_CODING_AGENT_DIR",
        "XDG_CONFIG_HOME",
        "NODE_OPTIONS",
    ):
        assert hostile not in env


def test_hostile_ambient_config_changes_nothing(
    tmp_path: Path, sidecar_dist: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A planted global Pi config + ambient keys are inert for a real run."""
    from _g2 import scaffold_project

    hostile_home = tmp_path / "ambient-home"
    pi_agent = hostile_home / ".pi" / "agent"
    pi_agent.mkdir(parents=True)
    (pi_agent / "auth.json").write_text('{"anthropic": {"apiKey": "hostile"}}', encoding="utf-8")
    (pi_agent / "models-store.json").write_text('{"providers": []}', encoding="utf-8")
    extensions = hostile_home / ".pi" / "extensions"
    extensions.mkdir(parents=True)
    (extensions / "hostile.js").write_text(
        "export default { tools: [{ name: 'hostile_tool' }] };\n", encoding="utf-8"
    )
    (hostile_home / ".pi" / "config.json").write_text(
        '{"tools": {"bash": true}, "extensions": ["hostile"]}', encoding="utf-8"
    )

    monkeypatch.setenv("HOME", str(hostile_home))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ambient-must-not-leak")
    monkeypatch.setenv("OPENAI_API_KEY", "ambient-must-not-leak")
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(pi_agent))
    monkeypatch.setenv("HEPHAESTUS_AGENT_DIR", str(hostile_home / "hijack"))

    project = scaffold_project(tmp_path / "clean-project")
    harness = G2Harness(project, sidecar_dist)
    try:
        offered: dict[str, Any] = {}

        def capture(info: RequestInfo) -> dict[str, Any]:
            offered["tools"] = sorted(info.tool_names)
            offered["body"] = info.body_text
            return text("clean")

        harness.set_script([capture])
        session_id = harness.create_session("orchestrator", session_id="g2-hostile")
        result = harness.prompt(session_id, "who are you?", timeout=300)
        assert result.status == "completed"

        # Only the generated CAD surface — no built-in coding tools, no hostile
        # extension tool, and nothing from the planted global config.
        from hephaestus.core import tools_decl

        assert offered["tools"] == sorted(
            name
            for name in tools_decl.tool_names()
            if "orchestrator" in tools_decl.get_tool(name).profiles
        )
        body = str(offered["body"])
        assert "hostile_tool" not in body
        assert str(hostile_home) not in body
        assert '"name":"bash"' not in body

        # App-owned agent dir: auth/model state landed under the project, and the
        # hostile HOME/PI_CODING_AGENT_DIR store was never written to.
        app_agent_dir = project / ".heph" / "agent"
        assert (app_agent_dir / "auth.json").exists()
        assert (pi_agent / "auth.json").read_text(encoding="utf-8") == (
            '{"anthropic": {"apiKey": "hostile"}}'
        )
        assert not (hostile_home / "hijack").exists()

        # The sidecar we spawned is the packaged artifact, never a global binary.
        assert str(sidecar_dist).endswith("agent/dist/main.js")
    finally:
        harness.close()
        harness.assert_no_orphans()
