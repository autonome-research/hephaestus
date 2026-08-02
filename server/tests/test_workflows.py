"""The thread-phase workflow layer, Python half (arch §4.5, digest §5, Gate G2).

Two tiers:

* **Pure Python** — :class:`~hephaestus.agent_bridge.workflows.WorkflowBridge`
  answers the runner process's ``py.*`` requests (jobstore persistence, live
  admission capacity, branch-admitted delegation, project-scoped tool dispatch),
  and :class:`~hephaestus.agent_bridge.workflows.WorkflowService` projects the
  durable job/event/checkpoint rows: replay that survives a store restart,
  orphaned ``RUNNING`` jobs projected as ``interrupted``, and one interrupted
  terminal when the runner process is confirmed lost.
* **Through the REAL Node runner** (``node <sidecar>/workflows/runner.js`` — the
  bundled, integrity-manifested artifact the wheel ships, built and staged by
  :func:`hephaestus.testing.sidecar.build_agent_dist`) over the private framed
  bridge, against a real opstore-backed project:
  - a workflow run to a durable terminal whose events replay identically after
    both processes are gone;
  - cooperative cancellation of a run that is blocked inside a delegation;
  - a crashed runner leaving a ``RUNNING`` job, its projection as ``interrupted``,
    and a resume that skips only the phases whose checkpoints verify;
  - **the G2 scenario**: a capped two-part cross-check/repair workflow driven by
    the scripted fake model through the real *main* sidecar — part A builds, part
    B interferes, one repair round moves it clear, cross-part checks go green —
    with the fan-out bound never above the live admission capacity;
  - a direct multimodal prompt (``inspect_part`` images) that bypasses the
    workflow layer entirely: **zero** job rows.

Every Node-backed scenario asserts no orphan process survives its supervisor.
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from hephaestus.agent_bridge.dispatch import DispatchError, Principal
from hephaestus.agent_bridge.jobstore import JobStore
from hephaestus.agent_bridge.protocol import ErrorCode, ProtocolError
from hephaestus.agent_bridge.supervisor import (
    Supervisor,
    SupervisorConfig,
    SupervisorError,
    pid_alive,
)
from hephaestus.agent_bridge.workflows import (
    CHECKPOINTS_NAMESPACE,
    EVENTS_NAMESPACE,
    INTERRUPTED_FAILURE_CLASS,
    JOBS_NAMESPACE,
    CadWorkflowRequest,
    JobRow,
    PartPromptOutcome,
    WorkflowBridge,
    WorkflowError,
    WorkflowRun,
    WorkflowRunnerProcess,
    WorkflowService,
)
from hephaestus.testing.fake_openai import (
    FakeOpenAI,
    RequestInfo,
    TurnResolver,
    start_fake_openai,
)
from hephaestus.testing.sidecar import build_agent_dist, node_executable
from hephaestus.testing.workflow_harness import (
    ORCH,
    SHELF_CLEAR_SRC,
    SHELF_INTERFERING_SRC,
    RunnerHarness,
    Wiring,
    completing_prompter,
    request_for,
    scaffold_workflow_project,
)
from opstore.types import TerminalState


class ScriptedTransport:
    """A :class:`WorkflowTransport` whose answers (or faults) are scripted."""

    def __init__(self, answers: dict[str, Any]) -> None:
        self.answers = answers
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.notifications: list[tuple[str, dict[str, Any]]] = []

    def call(
        self, method: str, params: dict[str, Any] | None = None, *, timeout: float | None = None
    ) -> Any:
        self.calls.append((method, dict(params or {})))
        answer = self.answers.get(method)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self.notifications.append((method, dict(params or {})))


@pytest.fixture
def wiring(tmp_path: Path) -> Iterator[Wiring]:
    scaffold_workflow_project(tmp_path / "proj")
    w = Wiring(tmp_path / "proj", prompter=completing_prompter())
    try:
        yield w
    finally:
        w.close()


def invocation(entry: str) -> dict[str, Any]:
    return {
        "session_id": ORCH.session_id,
        "entry_id": entry,
        "ordinal": 1,
        "provider_call_id": "wf:call",
    }


# ==========================================================================
# 1. the py.* bridge the runner process talks to


def test_bridge_answers_every_jobstore_method(wiring: Wiring) -> None:
    bridge = wiring.bridge()
    row: dict[str, Any] = {"namespace": "tp:jobs", "key": "j1", "value": {"id": "j1"}}
    assert bridge.handle("py.jobstore_put", row) == {"ok": True}
    assert bridge.handle("py.jobstore_get", {"namespace": "tp:jobs", "key": "j1"}) == {
        "value": {"id": "j1"}
    }
    listing = bridge.handle("py.jobstore_list", {"namespace": "tp:jobs"})
    assert listing == {"items": [{"key": "j1", "value": {"id": "j1"}}]}
    checkpoint = bridge.handle(
        "py.jobstore_checkpoint",
        {
            "job_id": "j1",
            "checkpoint_key": "cad:decompose@1",
            "workflow_version": "cad_project@1",
            "input_hash": "a" * 64,
            "output_hash": "b" * 64,
            "value": {"parts": ["bracket"]},
        },
    )
    assert checkpoint["ok"] is True
    stored = wiring.jobs.get_checkpoint("j1", "cad:decompose@1")
    assert stored is not None and stored.workflow_version == "cad_project@1"
    assert bridge.handle("py.jobstore_delete", {"namespace": "tp:jobs", "key": "j1"}) == {
        "deleted": True
    }


def test_bridge_reports_live_admission_capacity(wiring: Wiring) -> None:
    bridge = wiring.bridge()
    free = int(bridge.handle("py.admission_capacity", {})["capacity"])
    wiring.admission.admit_run("run-holder")
    assert int(bridge.handle("py.admission_capacity", {})["capacity"]) == free - 1


def test_bridge_rejects_an_unknown_py_method(wiring: Wiring) -> None:
    with pytest.raises(ProtocolError) as ei:
        wiring.bridge().handle("py.nope", {})
    assert ei.value.code == ErrorCode.METHOD_NOT_FOUND


# -- delegation (never the model-visible tool) -----------------------------


def test_bridge_delegate_admits_a_branch_run_and_settles_it(wiring: Wiring) -> None:
    bridge = wiring.bridge()
    before = wiring.admission.active_count()
    result = bridge.handle(
        "py.delegate",
        {
            "parent_run_id": "wf-run:bracket:0",
            "part": "bracket",
            "prompt": "build the bracket",
            "delivery": "prompt",
            "deadline_seconds": 600,
            "invocation": invocation("job#delegate:0"),
        },
    )
    assert result["status"] == "completed"
    assert result["result_artifact_ref"].startswith("artifact:build:")
    assert bridge.branch_runs == ["wf-run:bracket:0"]
    # The branch was admitted before the delegation and settled after it, so the
    # slot it borrowed is released and its terminal is durable + acknowledged.
    assert wiring.admission.active_count() == before
    terminal = wiring.admission.get_terminal("wf-run:bracket:0")
    assert terminal is not None and terminal.state is TerminalState.COMPLETED
    # The prompt is handed to the runner out-of-band and forgotten afterwards
    # (the WAL stores only its hash).
    assert wiring.prompts.get(f"{ORCH.session_id}|job#delegate:0|1|wf:call") is None


def test_bridge_delegate_rejects_with_no_child_when_no_slot_is_free(wiring: Wiring) -> None:
    for i in range(16):
        wiring.admission.admit_run(f"filler-{i}")
    result = wiring.bridge().handle(
        "py.delegate",
        {
            "parent_run_id": "wf-run:bracket:0",
            "part": "bracket",
            "prompt": "build the bracket",
            "invocation": invocation("job#delegate:0"),
        },
    )
    assert result == {"status": "rejected", "reason": "no_run_slot", "part_session_id": None}


def test_bridge_delegate_requires_a_parent_run_id(wiring: Wiring) -> None:
    with pytest.raises(DispatchError) as ei:
        wiring.bridge().handle("py.delegate", {"part": "bracket", "prompt": "x"})
    assert ei.value.reason == "invalid_params"


# -- project-scoped tool dispatch ------------------------------------------


def test_bridge_tool_dispatch_runs_project_checks_as_the_orchestrator(wiring: Wiring) -> None:
    wiring.build("bracket", "shelf")
    result = wiring.bridge().handle(
        "py.tool_dispatch",
        {
            "session_id": ORCH.session_id,
            "run_id": "wf-run",
            "tool": "run_checks",
            "arguments": {"scope": "project"},
            "invocation": invocation("job#run_checks:0"),
        },
    )
    assert result["status"] == "ok"
    assert result["checks"]["assembly:shelf_placement"]["pass"] is True


def test_bridge_tool_dispatch_refuses_a_foreign_session(wiring: Wiring) -> None:
    with pytest.raises(DispatchError) as ei:
        wiring.bridge().handle(
            "py.tool_dispatch",
            {
                "session_id": "someone-else",
                "tool": "run_checks",
                "arguments": {"scope": "project"},
                "invocation": invocation("x"),
            },
        )
    assert ei.value.reason == "scope_denied"


def test_bridge_without_a_dispatcher_refuses_rather_than_inventing_work(wiring: Wiring) -> None:
    bare = WorkflowBridge(wiring.jobs, wiring.admission)
    with pytest.raises(DispatchError) as ei:
        bare.handle("py.delegate", {"parent_run_id": "r", "part": "bracket", "prompt": "x"})
    assert ei.value.reason == "not_implemented"
    # …but the durable/administrative halves still work without one.
    assert bare.handle("py.admission_capacity", {})["capacity"] >= 0


# ==========================================================================
# 2. durable projections: replay, orphans, confirmed process loss


def store_job(
    jobs: JobStore,
    job_id: str,
    *,
    status: str = "RUNNING",
    pid: int | None = None,
    events: int = 0,
) -> None:
    """Write a job row exactly as the sidecar's JobStore adapter would."""
    row: dict[str, Any] = {
        "id": job_id,
        "name": "cad_project",
        "input": {"parts": ["bracket"]},
        "status": status,
        "result": None,
        "error": None,
        "eventCount": events,
        "createdAt": "2026-07-24T10:00:00.000Z",
        "startedAt": "2026-07-24T10:00:01.000Z",
        "completedAt": None,
        "hostname": socket.gethostname(),
    }
    if pid is not None:
        row["pid"] = pid
    jobs.put(JOBS_NAMESPACE, job_id, cast("Any", row))


def store_event(jobs: JobStore, job_id: str, event_id: int, kind: str) -> None:
    jobs.put(
        EVENTS_NAMESPACE,
        f"{job_id}#{event_id:012d}",
        cast(
            "Any",
            {
                "id": event_id,
                "jobId": job_id,
                "eventType": kind,
                "data": {"type": kind, "phase": "delegate"},
                "createdAt": "2026-07-24T10:00:02.000Z",
            },
        ),
    )


def test_replay_is_ordered_and_survives_a_store_restart(tmp_path: Path) -> None:
    root = scaffold_workflow_project(tmp_path / "proj")
    first = Wiring(root, prompter=completing_prompter())
    # The sidecar wrote its job + event log through the bridge…
    bridge = first.bridge()
    store_job(first.jobs, "job-1", status="COMPLETED")
    for event_id, kind in ((3, "phase_complete"), (1, "phase"), (2, "data")):
        bridge.handle(
            "py.jobstore_put",
            {
                "namespace": EVENTS_NAMESPACE,
                "key": f"job-1#{event_id:012d}",
                "value": {
                    "id": event_id,
                    "jobId": "job-1",
                    "eventType": kind,
                    "data": {"type": kind},
                    "createdAt": f"2026-07-24T10:00:0{event_id}Z",
                },
            },
        )
    store_event(first.jobs, "job-2", 7, "phase")
    first.close()

    # …and both processes are now gone. A fresh service replays the same events.
    second = Wiring(root, prompter=completing_prompter())
    try:
        service = WorkflowService(second.jobs, ScriptedTransport({}), second.admission)
        replayed = service.replay("job-1")
        assert [event.id for event in replayed] == [1, 2, 3]
        assert [event.event_type for event in replayed] == ["phase", "data", "phase_complete"]
        # Cursored replay resumes from a high-water mark, and never crosses jobs.
        assert [event.id for event in service.replay("job-1", after_id=2)] == [3]
        assert [event.id for event in service.replay("job-2")] == [7]
        row = service.status("job-1")
        assert row is not None and row.projected_status() == "completed"
    finally:
        second.close()


def test_orphaned_running_jobs_are_projected_as_interrupted(wiring: Wiring) -> None:
    service = WorkflowService(wiring.jobs, ScriptedTransport({}), wiring.admission)
    store_job(wiring.jobs, "job-orphan", pid=999_999)
    store_job(wiring.jobs, "job-live", pid=os.getpid())
    store_job(wiring.jobs, "job-done", status="COMPLETED", pid=999_999)

    interrupted = service.reconcile_orphans(live_pids=frozenset({os.getpid()}))
    assert interrupted == ["job-orphan"]

    orphan = service.status("job-orphan")
    assert orphan is not None
    assert orphan.status == "FAILED"
    assert orphan.failure_class == INTERRUPTED_FAILURE_CLASS
    # An unowned job never keeps appearing live, and partial output is not success.
    assert orphan.projected_status() == "interrupted"
    assert orphan.live is False
    # The interruption is in the durable event log too, so clients replay it.
    events = service.replay("job-orphan")
    assert [event.event_type for event in events] == ["error"]

    # The live-owner row is untouched; the terminal row is never re-terminated.
    live = service.status("job-live")
    assert live is not None and live.status == "RUNNING"
    assert service.status("job-done") is not None

    # Idempotent: a second startup pass finds nothing new and adds no events.
    assert service.reconcile_orphans(live_pids=frozenset({os.getpid()})) == []
    assert len(service.replay("job-orphan")) == 1


def test_reconcile_treats_a_job_from_another_host_as_orphaned(wiring: Wiring) -> None:
    service = WorkflowService(wiring.jobs, ScriptedTransport({}), wiring.admission)
    row: dict[str, Any] = {
        "id": "job-remote",
        "name": "cad_project",
        "input": None,
        "status": "RUNNING",
        "result": None,
        "error": None,
        "eventCount": 0,
        "createdAt": "2026-07-24T10:00:00.000Z",
        "startedAt": None,
        "completedAt": None,
        "pid": os.getpid(),
        "hostname": "some-other-host",
    }
    wiring.jobs.put(JOBS_NAMESPACE, "job-remote", cast("Any", row))
    assert service.reconcile_orphans(live_pids=frozenset({os.getpid()})) == ["job-remote"]


def test_confirmed_process_loss_yields_one_interrupted_terminal(wiring: Wiring) -> None:
    transport = ScriptedTransport({"workflow.run": SupervisorError("sidecar exited (rc=137)")})
    service = WorkflowService(wiring.jobs, transport, wiring.admission)
    store_job(wiring.jobs, "job-x")
    with pytest.raises(WorkflowError) as ei:
        service.launch({"parts": []}, job_id="job-x", run_id="run-x")
    assert ei.value.code == "process_down"
    terminal = wiring.admission.get_terminal("run-x")
    assert terminal is not None and terminal.state is TerminalState.INTERRUPTED
    row = service.status("job-x")
    assert row is not None and row.projected_status() == "interrupted"
    # The slot was released: the terminal was acknowledged before the raise.
    assert wiring.admission.active_count() == 0


def test_launch_records_a_terminal_and_releases_the_slot(wiring: Wiring) -> None:
    transport = ScriptedTransport(
        {
            "workflow.run": {
                "job_id": "job-ok",
                "status": "completed",
                "summary": {"status": "completed", "eventCount": 9},
                "resumed_from": None,
                "skipped_phases": [],
            }
        }
    )
    service = WorkflowService(wiring.jobs, transport, wiring.admission)
    run = service.launch({"parts": []}, job_id="job-ok", run_id="run-ok")
    assert run.status == "completed"
    assert run.job_id == "job-ok"
    method, params = transport.calls[0]
    assert method == "workflow.run"
    # The run id the launch admitted is threaded into the workflow input, so every
    # delegation branch is rooted in (and charged to) this run.
    assert params["input"]["parent_run_id"] == "run-ok"
    terminal = wiring.admission.get_terminal("run-ok")
    assert terminal is not None and terminal.state is TerminalState.COMPLETED
    assert wiring.admission.active_count() == 0


def test_cancel_is_forwarded_and_survives_a_dead_transport(wiring: Wiring) -> None:
    ok = ScriptedTransport({"workflow.cancel": {"job_id": "job-1", "cancelled": True}})
    assert WorkflowService(wiring.jobs, ok, wiring.admission).cancel("job-1") is True
    dead = ScriptedTransport({"workflow.cancel": SupervisorError("down")})
    assert WorkflowService(wiring.jobs, dead, wiring.admission).cancel("job-1") is False


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("completed", TerminalState.COMPLETED),
        ("stopped", TerminalState.COMPLETED),
        ("cancelled", TerminalState.CANCELLED),
        ("interrupted", TerminalState.INTERRUPTED),
        ("failed", TerminalState.FAILED),
    ],
)
def test_workflow_run_projects_its_bridge_terminal_state(
    status: str, expected: TerminalState
) -> None:
    run = WorkflowRun(
        job_id="j", run_id="r", status=status, summary={}, resumed_from=None, skipped_phases=()
    )
    assert run.terminal_state is expected


def test_job_row_projects_abandoned_and_tagged_failures_as_interrupted() -> None:
    def row(status: str, failure_class: str | None = None) -> JobRow:
        raw: dict[str, Any] = {"id": "j", "status": status}
        if failure_class is not None:
            raw["failureClass"] = failure_class
        parsed = JobRow.from_json(raw)
        assert parsed is not None
        return parsed

    assert row("ABANDONED").projected_status() == "interrupted"
    assert row("FAILED", INTERRUPTED_FAILURE_CLASS).projected_status() == "interrupted"
    assert row("FAILED").projected_status() == "failed"
    assert row("PENDING").projected_status() == "queued"
    assert row("RUNNING").projected_status() == "running"
    assert JobRow.from_json({"status": "RUNNING"}) is None


def test_cad_workflow_request_builds_the_runner_payload() -> None:
    payload = CadWorkflowRequest(
        project_root="/p",
        session_id="orch",
        parts=[("bracket", "build it", None), ("shelf", "build it", "fix it")],
        max_repair_rounds=1,
        max_concurrency=2,
    ).payload()
    assert payload["parts"] == [
        {"part": "bracket", "prompt": "build it"},
        {"part": "shelf", "prompt": "build it", "repair_prompt": "fix it"},
    ]
    assert payload["max_repair_rounds"] == 1
    assert payload["max_concurrency"] == 2
    assert "deadline_seconds" not in payload


# ==========================================================================
# 3. through the REAL Node workflow-runner process


@pytest.fixture(scope="session")
def agent_dist() -> Path:
    """Build the packaged sidecar once; skip cleanly when Node/pnpm are absent.

    Delegates to :func:`hephaestus.testing.sidecar.build_agent_dist`, the one
    place that knows how to produce the artifact a release ships. This fixture
    used to derive the agent workspace as
    ``default_workflow_runner_main().parents[2]`` — a fourth independent copy of
    the "the runner lives at ``<repo>/agent/dist/workflows/runner.js``"
    assumption, which stopped being true the moment the runner moved into the
    packaged sidecar.
    """
    built = build_agent_dist()
    if built is None:
        pytest.skip("node/pnpm are required to run the packaged workflow runner")
    return built[1]


def test_workflow_runs_to_a_durable_terminal_and_replays_after_both_processes_die(
    tmp_path: Path, agent_dist: Path
) -> None:
    root = scaffold_workflow_project(tmp_path / "proj")
    harness = RunnerHarness(root, agent_dist, completing_prompter())
    harness.wiring.build("bracket", "shelf")
    try:
        run = harness.service.launch(request_for(root), timeout=900)
        assert run.status == "completed", run.summary
        job = harness.service.status(run.job_id)
        assert job is not None and job.status == "COMPLETED"
        result = cast("dict[str, Any]", job.result)
        assert result["verified"] is True
        assert result["repair_rounds"] == 0
        assert result["parts"] == ["bracket", "shelf"]
        # Delegation went out over py.delegate — never the model-visible tool.
        assert harness.bridge.methods.count("py.delegate") == 2
        assert "py.tool_dispatch" in harness.bridge.methods
        assert harness.bridge.branch_runs == [
            f"{run.run_id}:bracket:0",
            f"{run.run_id}:shelf:0",
        ]
        # One durable, acknowledged bridge terminal; every slot released.
        terminal = harness.wiring.admission.get_terminal(run.run_id)
        assert terminal is not None and terminal.state is TerminalState.COMPLETED
        assert harness.wiring.admission.active_count() == 0
        # Every phase checkpointed with the workflow version + input/output hashes.
        checkpoints = harness.service.checkpoints(run.job_id)
        assert {record.checkpoint_key for record in checkpoints} == {
            "cad:decompose@1",
            "cad:delegate@1",
            "cad:cross_checks@1",
            "cad:repair@1",
            "cad:verify@1",
        }
        for record in checkpoints:
            assert record.workflow_version == "cad_project@1"
            assert len(record.input_hash) == 64 and len(record.output_hash) == 64
        live_replay = [event.event_type for event in harness.service.replay(run.job_id)]
        assert live_replay.count("phase_complete") == 5
        job_id = run.job_id
    finally:
        harness.close()
        harness.assert_no_orphans()

    # Both processes are gone: the durable log replays identically from state.db.
    after = Wiring(root, prompter=completing_prompter())
    try:
        service = WorkflowService(after.jobs, ScriptedTransport({}), after.admission)
        assert [event.event_type for event in service.replay(job_id)] == live_replay
        row = service.status(job_id)
        assert row is not None and row.projected_status() == "completed"
        # A restart projects no orphan: the job already holds its terminal.
        assert service.reconcile_orphans(live_pids=frozenset()) == []
    finally:
        after.close()


def test_cooperative_cancellation_stops_a_running_workflow(
    tmp_path: Path, agent_dist: Path
) -> None:
    root = scaffold_workflow_project(tmp_path / "proj")
    started = threading.Event()
    delegated: list[str] = []
    parts = [(f"p{i}", f"PART p{i}: build it.", f"REPAIR p{i}") for i in range(6)]

    def slow_prompter(part: str, text: str, child_run_id: str) -> PartPromptOutcome:
        delegated.append(part)
        started.set()
        time.sleep(0.25)
        return PartPromptOutcome(TerminalState.COMPLETED, result_artifact_ref="artifact:x")

    harness = RunnerHarness(root, agent_dist, slow_prompter)
    try:
        # One part at a time, so cancellation can actually cut the fan-out cursor.
        handle = harness.service.start(
            request_for(root, parts=parts, max_concurrency=1), timeout=900
        )
        assert started.wait(timeout=60), "the delegation phase never started"
        assert harness.service.cancel(handle.job_id, reason="operator") is True
        run = handle.result(timeout=120)
        assert run.status == "cancelled", run.summary
        job = harness.service.status(run.job_id)
        assert job is not None and job.status == "CANCELLED"
        assert job.projected_status() == "cancelled"
        # A cancelled run never claims verification…
        assert not job.result
        # …and its bridge terminal is cancelled, exactly once.
        terminal = harness.wiring.admission.get_terminal(run.run_id)
        assert terminal is not None and terminal.state is TerminalState.CANCELLED
        # Cooperative: the fan-out stopped early and verification never ran.
        assert 0 < len(delegated) < len(parts), delegated
        replayed = [event.event_type for event in harness.service.replay(run.job_id)]
        assert replayed.count("cancelled") == 1
        assert "phase_complete" in replayed  # decompose still committed its work
        assert not any(
            str(cast("dict[str, Any]", event.data).get("phase")) == "verify"
            for event in harness.service.replay(run.job_id)
        )
        # The runner process survived its cancelled job.
        assert harness.process.supervisor.is_running()
    finally:
        harness.close()
        harness.assert_no_orphans()


def test_orphaned_run_is_interrupted_then_resumes_from_verified_checkpoints(
    tmp_path: Path, agent_dist: Path
) -> None:
    root = scaffold_workflow_project(tmp_path / "proj")
    released = threading.Event()
    started = threading.Event()

    def blocking_prompter(part: str, text: str, child_run_id: str) -> PartPromptOutcome:
        started.set()
        released.wait(timeout=120)
        return PartPromptOutcome(TerminalState.COMPLETED, result_artifact_ref="artifact:x")

    harness = RunnerHarness(root, agent_dist, blocking_prompter)
    harness.wiring.build("bracket", "shelf")
    try:
        handle = harness.service.start(request_for(root), timeout=900)
        assert started.wait(timeout=60), "the delegation phase never started"
        # Kill the runner mid-delegation: the job row is left RUNNING with no owner.
        doomed = harness.process.child_pid
        os.kill(doomed, 9)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and pid_alive(doomed):
            time.sleep(0.05)
        released.set()
        with pytest.raises(WorkflowError) as ei:
            handle.result(timeout=120)
        assert ei.value.code == "process_down"

        prior = handle.job_id
        # Confirmed owner loss: exactly one interrupted bridge terminal…
        terminal = harness.wiring.admission.get_terminal(handle.run_id)
        assert terminal is not None and terminal.state is TerminalState.INTERRUPTED
        # …and the startup pass projects the orphaned job the same way.
        row = harness.service.status(prior)
        assert row is not None
        assert row.projected_status() == "interrupted"
        assert row.failure_class == INTERRUPTED_FAILURE_CLASS
        assert harness.service.reconcile_orphans(live_pids=frozenset()) == []
        # The decompose phase checkpointed before the crash; delegate did not.
        keys = {record.checkpoint_key for record in harness.service.checkpoints(prior)}
        assert "cad:decompose@1" in keys
        assert "cad:delegate@1" not in keys

        # Resume: only verified checkpoints are skipped, everything else re-runs.
        harness.restart()
        resumed = harness.service.resume(prior, payload=request_for(root), timeout=900)
        assert resumed.status == "completed", resumed.summary
        assert resumed.resumed_from == prior
        assert resumed.skipped_phases == ("decompose",)
        assert resumed.job_id != prior
        job = harness.service.status(resumed.job_id)
        assert job is not None and job.status == "COMPLETED"
        assert cast("dict[str, Any]", job.result)["verified"] is True
        # The interrupted row keeps its own terminal: success is never back-dated.
        stale = harness.service.status(prior)
        assert stale is not None and stale.projected_status() == "interrupted"
    finally:
        released.set()
        harness.close()
        harness.assert_no_orphans()


# ==========================================================================
# 4. THE G2 SCENARIO: two parts, cross-part checks, one capped repair round,
#    driven by the scripted fake model through the real main sidecar.


def messages_of(info: RequestInfo) -> list[dict[str, Any]]:
    body = cast("dict[str, Any]", json.loads(info.body_text))
    raw = body.get("messages")
    out: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for entry in cast("list[Any]", raw):
            if isinstance(entry, dict):
                out.append(cast("dict[str, Any]", entry))
    return out


def last_index(messages: list[dict[str, Any]], role: str) -> int:
    found = -1
    for index, message in enumerate(messages):
        if message.get("role") == role:
            found = index
    return found


def message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    return content if isinstance(content, str) else json.dumps(content)


def last_tool_result(messages: list[dict[str, Any]]) -> dict[str, Any]:
    index = last_index(messages, "tool")
    if index < 0:
        return {}
    raw = message_text(messages[index]).lstrip()
    try:
        parsed, _end = json.JSONDecoder().raw_decode(raw)
    except json.JSONDecodeError:
        return {}
    return cast("dict[str, Any]", parsed) if isinstance(parsed, dict) else {}


def tool_call(name: str, arguments: dict[str, Any], call_id: str) -> dict[str, Any]:
    return {"kind": "tool_calls", "calls": [{"name": name, "arguments": arguments, "id": call_id}]}


def part_agent_turn(info: RequestInfo) -> dict[str, Any]:
    """The scripted part agent: build; on a REPAIR prompt, read → write → build.

    Deterministic and concurrency-safe: the turn is a pure function of the
    conversation the model was handed, never of a shared cursor.
    """
    messages = messages_of(info)
    user_index = last_index(messages, "user")
    fresh = user_index > last_index(messages, "tool")
    instruction = message_text(messages[user_index]) if user_index >= 0 else ""
    part = "shelf" if "shelf" in instruction else "bracket"
    if fresh:
        if "REPAIR" in instruction:
            return tool_call("read_part", {"name": part}, "t-read")
        if "INSPECT" in instruction:
            return tool_call("inspect_part", {"name": part, "views": ["iso"]}, "t-inspect")
        return tool_call("build_part", {"name": part}, "t-build")
    result = last_tool_result(messages)
    if "script" in result:  # the read_part result: author the repaired shelf
        return tool_call(
            "write_part",
            {"name": part, "expected_hash": result["content_hash"], "script": SHELF_CLEAR_SRC},
            "t-write",
        )
    if "applied" in result:  # the write_part result: rebuild
        return tool_call("build_part", {"name": part}, "t-rebuild")
    return {"kind": "text", "chunks": [f"{part}: done"]}


class PartAgents:
    """The real main sidecar hosting one persistent Pi session per part.

    The workflow never touches this: it delegates through Python, and the
    delegation runner prompts the part session here — digest §3's "thread-phase
    calls the session service directly, never the model-visible tool".
    """

    def __init__(self, root: Path, dist_main: Path, wiring: Wiring, fake: FakeOpenAI) -> None:
        node = node_executable()
        assert node is not None
        self.root = root
        self.wiring = wiring
        self.fake = fake
        self.sessions: dict[str, str] = {}
        self.principals: dict[str, Principal] = {}
        self.artifacts: dict[str, str] = {}
        self.events: list[dict[str, Any]] = []
        self.prompted: list[tuple[str, str]] = []
        self._lock = threading.Lock()
        agent_dir = root / ".heph" / "agent"
        agent_dir.mkdir(parents=True, exist_ok=True)
        self.sup = Supervisor(
            SupervisorConfig(
                argv=[node, str(dist_main)],
                extra_env={"HEPHAESTUS_AGENT_DIR": str(agent_dir)},
                cwd=str(root),
                default_timeout_s=900.0,
            ),
            py_handler=self._on_py,
            notification_sink=self._on_notification,
        )
        self.sup.start()
        self.pid = self.sup.child_pid
        self.sup.call("runtime.configure", {"providers": [fake.provider_spec()], "credentials": {}})

    # -- bridge callbacks --------------------------------------------------

    def _on_py(self, method: str, params: dict[str, Any]) -> Any:
        if method == "py.tool_dispatch":
            session_id = str(params.get("session_id", ""))
            principal = self.principals.get(session_id)
            if principal is None:
                raise ProtocolError(ErrorCode.INVALID_PARAMS, f"unknown session {session_id!r}")
            result: Any = self.wiring.dispatcher.dispatch(principal, params)
            if str(params.get("tool")) == "build_part" and principal.part is not None:
                ref = cast("dict[str, Any]", result).get("artifact_ref")
                if isinstance(ref, str):
                    self.artifacts[principal.part] = ref
            return result
        if method == "py.admission_capacity":
            return {"capacity": self.wiring.admission.capacity()}
        raise ProtocolError(ErrorCode.METHOD_NOT_FOUND, f"unhandled py request: {method}")

    def _on_notification(self, method: str, params: dict[str, Any]) -> None:
        if method == "event":
            self.events.append(dict(params))

    # -- the part prompter -------------------------------------------------

    def session_for(self, part: str) -> str:
        with self._lock:
            existing = self.sessions.get(part)
            if existing is not None:
                return existing
            result = self.sup.call(
                "session.create",
                {"profile": "part", "part": part, "project_root": str(self.root)},
            )
            session_id = str(result["session_id"])
            self.sessions[part] = session_id
            self.principals[session_id] = Principal(
                session_id=session_id, profile="part", part=part
            )
            return session_id

    def prompt(self, part: str, text: str, child_run_id: str) -> PartPromptOutcome:
        """Run one part-agent turn; the delegation runner turns it into a terminal."""
        self.prompted.append((part, text))
        session_id = self.session_for(part)
        result = self.sup.call(
            "session.prompt",
            {"session_id": session_id, "run_id": child_run_id, "prompt": text},
            timeout=900,
        )
        status = str(result.get("status", "completed"))
        if status == "completed":
            return PartPromptOutcome(
                TerminalState.COMPLETED, result_artifact_ref=self.artifacts.get(part)
            )
        if status == "cancelled":
            return PartPromptOutcome(TerminalState.CANCELLED, error="cancelled")
        return PartPromptOutcome(TerminalState.FAILED, error=status)

    def close(self) -> None:
        try:
            self.sup.close()
        finally:
            self.fake.close()


class G2Harness:
    """Main sidecar (part agents) + workflow runner process over one project."""

    def __init__(self, root: Path, runner_main: Path, *, shelf: str) -> None:
        node = node_executable()
        assert node is not None
        scaffold_workflow_project(root, shelf=shelf)
        script: list[TurnResolver] = [part_agent_turn] * 64
        self.fake = start_fake_openai(script)
        holder: dict[str, PartAgents] = {}
        self.wiring = Wiring(
            root,
            prompter=lambda part, text, run_id: holder["agents"].prompt(part, text, run_id),
        )
        self.agents = PartAgents(root, runner_main.parents[1] / "main.js", self.wiring, self.fake)
        holder["agents"] = self.agents
        self.bridge = self.wiring.bridge()
        self.process = WorkflowRunnerProcess(
            self.bridge, node=node, runner_main=runner_main, cwd=root, default_timeout_s=900.0
        )
        self.process.start()
        self.pids = [self.process.child_pid, self.agents.pid]
        self.service = WorkflowService(self.wiring.jobs, self.process, self.wiring.admission)

    def close(self) -> None:
        try:
            self.process.close()
        finally:
            try:
                self.agents.close()
            finally:
                self.wiring.close()

    def assert_no_orphans(self) -> None:
        for pid in self.pids:
            assert not pid_alive(pid), f"pid {pid} outlived its supervisor"


@pytest.fixture
def g2(tmp_path: Path, agent_dist: Path) -> Iterator[G2Harness]:
    harness = G2Harness(tmp_path / "proj", agent_dist, shelf=SHELF_INTERFERING_SRC)
    try:
        yield harness
    finally:
        harness.close()
        harness.assert_no_orphans()


def test_g2_capped_two_part_cross_check_repair_workflow(g2: G2Harness) -> None:
    # Part A and part B are both authored and built by their own scripted agents;
    # B's initial placement interferes, so the cross-part check fails and exactly
    # one capped repair round fixes it.
    run = g2.service.launch(request_for(g2.wiring.root), timeout=900)
    assert run.status == "completed", run.summary

    job = g2.service.status(run.job_id)
    assert job is not None and job.status == "COMPLETED"
    result = cast("dict[str, Any]", job.result)

    # -- the repair actually happened, once, and only for the shelf ----------
    assert result["repair_rounds"] == 1
    assert result["checks"]["passed"] is True
    assert result["verification"]["passed"] is True
    assert result["verified"] is True
    repair_prompts = [text for _part, text in g2.agents.prompted if "REPAIR" in text]
    assert [part for part, text in g2.agents.prompted if "REPAIR" in text] == ["shelf"]
    assert repair_prompts and "move it clear" in repair_prompts[0]

    # -- the geometry, not the log, is the truth -----------------------------
    assert "Pos(0.0, 0.0, 20.0)" in (g2.wiring.root / "parts" / "shelf.py").read_text(
        encoding="utf-8"
    )
    checks = g2.wiring.dispatcher.dispatch(
        ORCH,
        {
            "session_id": ORCH.session_id,
            "run_id": "verify",
            "tool": "run_checks",
            "arguments": {"scope": "project"},
            "invocation": invocation("verify-1"),
        },
    )
    assert checks["checks"]["assembly:shelf_placement"]["pass"] is True

    # -- delegation went through Python, never the model-visible tool --------
    assert g2.bridge.methods.count("py.delegate") == 3  # bracket, shelf, shelf-repair
    assert g2.bridge.branch_runs == [
        f"{run.run_id}:bracket:0",
        f"{run.run_id}:shelf:0",
        f"{run.run_id}:shelf:1",
    ]
    assert not any("delegate_part_agent" in text for _part, text in g2.agents.prompted)

    # -- fan-out never exceeded the live admission capacity ------------------
    fanout = [int(value) for value in cast("list[Any]", result["fanout_concurrency"])]
    assert fanout == [2, 1]  # two parts in round 0, only the shelf in the repair
    sampled = g2.bridge.capacities
    assert len(sampled) >= len(fanout)
    for bound, capacity in zip(fanout, sampled, strict=False):
        assert bound <= capacity, (fanout, sampled)
    assert max(sampled) <= 16

    # -- one durable acknowledged terminal; every slot released --------------
    terminal = g2.wiring.admission.get_terminal(run.run_id)
    assert terminal is not None and terminal.state is TerminalState.COMPLETED
    assert g2.wiring.admission.active_count() == 0

    # -- the orchestration history is durable and ordered --------------------
    replay = g2.service.replay(run.job_id)
    assert [event.id for event in replay] == sorted(event.id for event in replay)
    phases = [
        str(cast("dict[str, Any]", event.data).get("phase"))
        for event in replay
        if event.event_type == "phase"
    ]
    assert phases == ["decompose", "delegate", "cross_checks", "repair", "verify"]
    assert len([event for event in replay if event.event_type == "phase_complete"]) == 5


def test_direct_multimodal_prompt_bypasses_the_workflow_layer(g2: G2Harness) -> None:
    # A direct part-session prompt that returns renders is ordinary interactive
    # work: it must never touch thread-phase (mission rule 6 / digest §5 bypass).
    g2.wiring.build("bracket")
    outcome = g2.agents.prompt("bracket", "INSPECT the bracket, please.", "run-direct")
    assert outcome.state is TerminalState.COMPLETED

    kinds = [str(event.get("kind")) for event in g2.agents.events]
    assert "image" in kinds, kinds  # the render really reached the model inline

    assert g2.service.jobs() == []
    assert g2.wiring.jobs.list(JOBS_NAMESPACE) == []
    assert g2.wiring.jobs.list(EVENTS_NAMESPACE) == []
    assert g2.wiring.jobs.list(CHECKPOINTS_NAMESPACE) == []
