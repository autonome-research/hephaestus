# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""A delegation completes end to end, through a real part session on a real sidecar.

audit-2026-09-04 J-agent-wiring-6, unblocked by J-agent-wiring-13.

``delegate_part_agent`` was wired to a state machine with **no runner**: a
synchronous delegation reached ``PREPARED → ADMITTED``, found no coordinator, and
was finalized as a durable ``interrupted`` terminal. That was the honest
intermediate state, and the blocker was structural — executing a child part agent
means prompting it over the very bridge the ``py.delegate`` request arrived on,
and the request was being handled inline on the supervisor's single reader
thread, so the child's every frame would have been waiting on the thread that was
waiting for the child. ``py.*`` dispatch now runs on a bounded worker pool, so
this test can exist at all.

Nothing between the orchestrator's tool call and the child part agent's own tool
calls is stubbed: the scripted fake provider serves both turns, one real sidecar
process holds both sessions, and the delegation WAL, the admission substrate and
the event pump are the shipped ones. What the test asserts is the whole of the
ledger's claim: a delegation to an existing part **completes**, a delegation to a
part that does not exist is **rejected before any child run exists**, and the
rejection reasons come from the shipped gate rather than from a permissive
default no production runtime replaced.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from hephaestus.agent_bridge.app import BridgeRuntime, repo_root
from hephaestus.agent_bridge.supervisor import pid_alive
from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend
from hephaestus.testing.fake_openai import FakeOpenAI, RequestInfo, start_fake_openai
from hephaestus.testing.projects import scaffold_project
from hephaestus.testing.sidecar import build_agent_dist
from hephaestus.testing.stream_assertions import last_tool_result, text, tool_call
from opstore.types import TerminalState

WIDGET_SCRIPT = """PARAMS = {
    "width": Param(40.0, min=10.0, max=80.0),
}

body = Box(p.width, 20.0, 6.0)
body.label = "widget_body"
part.geometry = body
part.description = "A part a delegated child agent works on"
"""


@pytest.fixture(scope="session")
def sidecar_dist() -> Path:
    built = build_agent_dist()
    if built is None:
        pytest.skip("node/pnpm unavailable; a delegation needs the packaged sidecar")
    return built[0]


class Harness:
    """A started :class:`BridgeRuntime` over a project that already has a part."""

    def __init__(self, project_root: Path, dist_main: Path) -> None:
        self.project_root = project_root
        self.fake: FakeOpenAI = start_fake_openai([])
        self.runtime = BridgeRuntime(
            backend=UnsafeLocalBackend(),
            project_root=project_root,
            providers=[self.fake.provider_spec()],
            dist_main=dist_main,
        )
        self.runtime.start()
        self.child_pid = self.runtime.child_pid

    def close(self) -> None:
        try:
            self.runtime.close()
        finally:
            self.fake.close()

    def assert_no_orphans(self) -> None:
        assert not pid_alive(self.child_pid), "sidecar outlived the supervisor"


@pytest.fixture
def harness(tmp_path: Path, sidecar_dist: Path) -> Iterator[Harness]:
    root = scaffold_project(
        tmp_path / "proj",
        name="deleg",
        globals_src="# Project-shared namespace.\nPARAMS = {}\n",
    )
    (root / "parts").mkdir(exist_ok=True)
    (root / "parts" / "widget.py").write_text(WIDGET_SCRIPT, encoding="utf-8")
    h = Harness(root, sidecar_dist)
    try:
        yield h
    finally:
        h.close()
        h.assert_no_orphans()


def test_a_delegation_to_a_real_part_session_completes_end_to_end(harness: Harness) -> None:
    """The orchestrator delegates, a child part session runs, the parent resumes.

    Three turns cross the fake provider in order: the orchestrator's tool call,
    the CHILD part agent's own turn (a different session, prompted by the
    delegation runner while the orchestrator's turn is suspended), and the
    orchestrator's closing sentence. The middle one is the proof that a part
    session really ran — before this it did not exist.
    """
    seen: dict[str, Any] = {}

    def child_turn(info: RequestInfo) -> dict[str, Any]:
        # This turn belongs to the CHILD: the delegation runner opened
        # `part:widget` and prompted it with the orchestrator's hand-off text.
        seen["child_prompt_seen"] = "widen the widget" in info.body_text
        return text("widened it")

    def orchestrator_finish(info: RequestInfo) -> dict[str, Any]:
        delegated = last_tool_result(info)
        seen["delegation"] = delegated
        return text("the part agent finished")

    harness.fake.set_script(
        [
            tool_call(
                "delegate_part_agent",
                {"part": "widget", "prompt": "widen the widget", "delivery": "prompt"},
                "d0",
            ),
            child_turn,
            orchestrator_finish,
        ]
    )

    session_id = harness.runtime.create_session("orchestrator", session_id="deleg-main")
    result = harness.runtime.prompt(session_id, "hand the widget to a part agent", timeout=600)
    harness.fake.raise_script_error()

    assert result.status == "completed"
    delegation = seen["delegation"]
    # THE assertion this whole item is about: `completed`, not `interrupted`.
    assert delegation["status"] == "completed", delegation
    assert delegation["part_session_id"] == "part:widget"
    assert delegation["child_run_id"]
    assert delegation["delegation_ref"]
    assert seen["child_prompt_seen"] is True, "the child was never prompted with the hand-off"

    # The child run's terminal is durable and its slot released; the parent's
    # own turn came back out of SUSPENDED_WAIT to answer.
    terminal = harness.runtime.admission.get_terminal(delegation["child_run_id"])
    assert terminal is not None
    assert terminal.state is TerminalState.COMPLETED


def test_a_delegation_to_a_part_that_does_not_exist_is_rejected_with_no_child(
    harness: Harness,
) -> None:
    """The gate refuses before admission: no child run, no ref, no durable row.

    ``RejectionReason.INVALID_PART`` had no producer — the delegation service
    defaulted to a gate that never rejects and no shipped runtime replaced it —
    so delegating to a name absent from the project minted a child run id and
    reported work on a part that was never there.
    """
    seen: dict[str, Any] = {}

    def finish(info: RequestInfo) -> dict[str, Any]:
        seen["delegation"] = last_tool_result(info)
        return text("no such part")

    harness.fake.set_script(
        [
            tool_call(
                "delegate_part_agent",
                {"part": "not_a_part", "prompt": "do something", "delivery": "prompt"},
                "d0",
            ),
            finish,
        ]
    )

    session_id = harness.runtime.create_session("orchestrator", session_id="deleg-missing")
    result = harness.runtime.prompt(session_id, "delegate to a part that is not there", timeout=300)
    harness.fake.raise_script_error()

    assert result.status == "completed"
    delegation = seen["delegation"]
    assert delegation["status"] == "rejected"
    assert delegation["reason"] == "invalid_part"
    # §2.6: a rejection before admission has NO child run and NO reference.
    assert "child_run_id" not in delegation
    assert "delegation_ref" not in delegation


def test_the_repo_root_fixture_is_the_shipped_one() -> None:
    """Guard against this file drifting off the packaged sidecar resolution."""
    assert (repo_root() / "schemas" / "bridge_limits.json").is_file()
