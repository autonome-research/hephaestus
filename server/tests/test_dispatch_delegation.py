"""The delegation tools as dispatched: service wiring, terminals, idempotency.

The delegation *state machine* is covered by ``test_delegation.py``; this file
covers the ``py.tool_dispatch`` projection of it — the three orchestrator-only
tools mapped onto :class:`~hephaestus.agent_bridge.delegation.DelegationService`,
the discriminated result variants, the ``rejected`` shapes that carry no child,
and the "at most one child, exactly one terminal" contract under retry.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from hephaestus.agent_bridge.delegation import (
    DelegationRow,
    DelegationService,
    Delivery,
    RejectionReason,
)
from hephaestus.agent_bridge.dispatch import DispatchError, ToolDispatcher
from hephaestus.core.project_store.store import ProjectStore
from hephaestus.testing.doubles import FakeClock
from hephaestus.testing.tools_fixture import ORCH, PART_WIDGET, Project, make_project
from opstore.types import TerminalState

CHILD_ARTIFACT = "artifact:build:sha256:" + "a" * 64


class CompletingRunner:
    """A coordinator stand-in: dispatches the child and completes it."""

    def __init__(self, artifact: str = CHILD_ARTIFACT) -> None:
        self.artifact = artifact
        self.seen: list[str] = []

    def run(self, service: DelegationService, row: DelegationRow) -> None:
        self.seen.append(row.child_run_id)
        service.dispatch(row.delegation_ref)
        service.ingest_terminal(
            row.delegation_ref, TerminalState.COMPLETED, result_artifact_ref=self.artifact
        )


class RejectGate:
    """A pre-admission gate that always rejects with one fixed reason."""

    def __init__(self, reason: RejectionReason) -> None:
        self.reason = reason

    def classify(self, parent_run_id: str, part: str, delivery: Delivery) -> RejectionReason:
        return self.reason


def _wire(
    project: Project,
    *,
    clock: FakeClock,
    runner: Any = None,
    gate: Any = None,
) -> DelegationService:
    """Attach a real delegation service (over the project's opstore) to dispatch."""
    service = DelegationService(project.store.admission, project.store.db, gate=gate, clock=clock)
    project.dispatcher = ToolDispatcher(
        ProjectStore(project.layout, project.store),
        cad=project.cad,
        delegation=service,
        delegation_runner=runner,
    )
    return service


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Project]:
    p = make_project(tmp_path / "proj")
    try:
        yield p
    finally:
        p.close()


# -- follow_up -----------------------------------------------------------------


def test_follow_up_returns_queued_and_status_is_observable(
    project: Project, clock: FakeClock
) -> None:
    service = _wire(project, clock=clock)
    out = project.call(
        "delegate_part_agent",
        {"part": "widget", "prompt": "widen it", "delivery": "follow_up"},
        entry="fu",
    )
    assert out["status"] == "queued"
    assert out["part_session_id"] == "part:widget"
    assert out["child_run_id"] and out["delegation_ref"]
    status = project.call("get_delegation_status", {"delegation_ref": out["delegation_ref"]})
    assert status["status"] == "queued"
    assert status["child_run_id"] == out["child_run_id"]
    # The child's slot is reserved at ADMITTED, before any sidecar execution.
    assert project.store.admission.active_count() == 1
    assert service.get(out["delegation_ref"]).child_run_id == out["child_run_id"]


def test_follow_up_retry_on_the_same_invocation_creates_one_child(
    project: Project, clock: FakeClock
) -> None:
    _wire(project, clock=clock)
    args = {"part": "widget", "prompt": "widen it", "delivery": "follow_up"}
    first = project.call("delegate_part_agent", args, entry="idem")
    second = project.call("delegate_part_agent", args, entry="idem")
    assert second["child_run_id"] == first["child_run_id"]
    assert second["delegation_ref"] == first["delegation_ref"]
    assert project.store.admission.active_count() == 1


def test_same_invocation_different_prompt_is_a_payload_mismatch(
    project: Project, clock: FakeClock
) -> None:
    _wire(project, clock=clock)
    project.call(
        "delegate_part_agent",
        {"part": "widget", "prompt": "one", "delivery": "follow_up"},
        entry="mm",
    )
    with pytest.raises(DispatchError) as ei:
        project.call(
            "delegate_part_agent",
            {"part": "widget", "prompt": "two", "delivery": "follow_up"},
            entry="mm",
        )
    assert ei.value.reason == "key_payload_mismatch"


def test_cancel_delegation_is_idempotent(project: Project, clock: FakeClock) -> None:
    _wire(project, clock=clock)
    queued = project.call(
        "delegate_part_agent",
        {"part": "widget", "prompt": "x", "delivery": "follow_up"},
        entry="cancel",
    )
    ref = queued["delegation_ref"]
    first = project.call("cancel_delegation", {"delegation_ref": ref})
    assert first["status"] == "cancelled"
    second = project.call("cancel_delegation", {"delegation_ref": ref})
    assert second["status"] == "cancelled"
    assert second["child_run_id"] == first["child_run_id"]


def test_deadline_expiry_only_produces_timed_out(project: Project, clock: FakeClock) -> None:
    _wire(project, clock=clock)
    queued = project.call(
        "delegate_part_agent",
        {"part": "widget", "prompt": "x", "delivery": "follow_up", "deadline_seconds": 30},
        entry="dl",
    )
    clock.advance(31)
    out = project.call("get_delegation_status", {"delegation_ref": queued["delegation_ref"]})
    assert out["status"] == "timed_out"


# -- synchronous prompt delivery ----------------------------------------------


def test_prompt_delivery_with_a_runner_completes(project: Project, clock: FakeClock) -> None:
    runner = CompletingRunner()
    _wire(project, clock=clock, runner=runner)
    project.store.admission.admit("run-1")  # the waiting parent holds a slot
    out = project.call(
        "delegate_part_agent", {"part": "widget", "prompt": "build it"}, entry="sync"
    )
    assert out["status"] == "completed"
    assert out["result_artifact_ref"] == CHILD_ARTIFACT
    assert runner.seen == [out["child_run_id"]]
    # The parent reacquired its slot; the child's terminal was acknowledged.
    assert project.store.admission.active_count() == 1


def test_prompt_delivery_without_a_runner_synthesizes_one_interrupted_terminal(
    project: Project, clock: FakeClock
) -> None:
    service = _wire(project, clock=clock)
    project.store.admission.admit("run-1")
    out = project.call(
        "delegate_part_agent", {"part": "widget", "prompt": "build it"}, entry="norunner"
    )
    assert out["status"] == "interrupted"
    assert out["error"]["message"] == "no delegation runner configured"
    terminal = project.store.admission.get_terminal(out["child_run_id"])
    assert terminal is not None
    assert terminal.state is TerminalState.INTERRUPTED
    # Replaying the tool cannot create a second child or a second terminal.
    again = project.call(
        "delegate_part_agent", {"part": "widget", "prompt": "build it"}, entry="norunner"
    )
    assert again["child_run_id"] == out["child_run_id"]
    assert service.get(out["delegation_ref"]).terminal_state is TerminalState.INTERRUPTED


# -- rejections ----------------------------------------------------------------


def test_prompt_too_large_is_a_rejection_with_no_child(project: Project, clock: FakeClock) -> None:
    service = _wire(project, clock=clock)
    out = project.call(
        "delegate_part_agent",
        {"part": "widget", "prompt": "x" * 40_000, "delivery": "follow_up"},
        entry="big",
    )
    assert out == {
        "status": "rejected",
        "reason": "prompt_too_large",
        "part_session_id": "part:widget",
    }
    assert service.get_by_invocation("orch|big|1|call_0") is None


@pytest.mark.parametrize(
    "reason",
    [
        RejectionReason.PART_BUSY,
        RejectionReason.SESSION_BUSY,
        RejectionReason.INVALID_PART,
        RejectionReason.QUEUE_FULL,
    ],
)
def test_gate_rejections_carry_no_child_ref(
    project: Project, clock: FakeClock, reason: RejectionReason
) -> None:
    _wire(project, clock=clock, gate=RejectGate(reason))
    out = project.call(
        "delegate_part_agent",
        {"part": "widget", "prompt": "x", "delivery": "follow_up"},
        entry=f"gate-{reason}",
    )
    assert out["status"] == "rejected"
    assert out["reason"] == str(reason)
    assert "child_run_id" not in out
    assert "delegation_ref" not in out


def test_unknown_delegation_ref(project: Project, clock: FakeClock) -> None:
    _wire(project, clock=clock)
    with pytest.raises(DispatchError) as ei:
        project.call("get_delegation_status", {"delegation_ref": "dg-nope"})
    assert ei.value.reason == "not_found"


def test_delegation_tools_are_not_implemented_without_the_service(project: Project) -> None:
    for tool, args in (
        ("delegate_part_agent", {"part": "widget", "prompt": "x"}),
        ("get_delegation_status", {"delegation_ref": "dg-1"}),
        ("cancel_delegation", {"delegation_ref": "dg-1"}),
    ):
        with pytest.raises(DispatchError) as ei:
            project.call(tool, args)
        assert ei.value.reason == "not_implemented", tool


def test_delegation_stays_orchestrator_only(project: Project, clock: FakeClock) -> None:
    _wire(project, clock=clock)
    for tool, args in (
        ("delegate_part_agent", {"part": "widget", "prompt": "x"}),
        ("get_delegation_status", {"delegation_ref": "dg-1"}),
        ("cancel_delegation", {"delegation_ref": "dg-1"}),
    ):
        with pytest.raises(DispatchError) as ei:
            project.call(tool, args, principal=PART_WIDGET)
        assert ei.value.reason == "scope_denied", tool
    # ...and the orchestrator principal is the one that may use them.
    assert ORCH.is_orchestrator
