"""Gate G2 — bridge bounds proved through the running bridge, not its validators.

Everything here drives the real Python bridge (framing → protocol → supervisor →
event pump → opstore admission) against a scripted wire peer
(``tests/stage2/_g2b_peer.py``) so the assertions are about *runtime* behaviour:

* 16 concurrent runs under **stalled consumption** — no client ever drains its
  queue — each produce exactly one durably acknowledged terminal, the 17th
  admission is refused while they are outstanding, and the admission +
  terminal-ack rows survive a restart of the store;
* a progress flood far past the 1024-event buffer coalesces to one event per
  ``(run_id, event_kind, tool_call_id)`` while **every** audit / tool call /
  tool result / question / answer / terminal survives;
* cancelling one run terminates only that run: its sibling on the same
  multiplexed bridge keeps streaming and completes normally.

``server/tests/test_events.py`` proves the pump's algebra in-process and
``server/tests/test_supervisor.py`` proves the framing/watchdog paths; what is
new here is those two halves wired together over a real process boundary.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from _g2b import FakeClock, open_bridge_store
from hephaestus.agent_bridge.admission import BRIDGE_RUN_SLOTS, BridgeAdmission
from hephaestus.agent_bridge.events import BUFFERED_EVENTS_MAX, EventPump, PerClientQueue
from hephaestus.agent_bridge.supervisor import Supervisor, SupervisorConfig, pid_alive
from opstore.errors import BusyError
from opstore.types import TerminalState

from opstore import OpStore

_PEER = Path(__file__).with_name("_g2b_peer.py")


class Bridge:
    """The real Python bridge halves over one scripted peer process."""

    def __init__(self, root: Path, *, clock: FakeClock | None = None) -> None:
        self.root = root
        self.store: OpStore = open_bridge_store(root, clock=clock)
        self.admission = BridgeAdmission(self.store.admission)
        self.pump = EventPump(
            self.store.admission,
            ack_terminal=lambda run_id, terminal_id: self.sup.notify(
                "terminal.ack", {"run_id": run_id, "terminal_id": terminal_id}
            ),
            cancel_run=lambda run_id: self.sup.notify("cancel", {"run_id": run_id}),
        )
        self.sup = Supervisor(
            SupervisorConfig(argv=[sys.executable, str(_PEER)], default_timeout_s=30.0),
            notification_sink=self.pump.on_notification,
        )
        self.sup.start()
        self.pids = [self.sup.child_pid]

    def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        return self.sup.call(method, params)

    def close(self) -> None:
        try:
            self.sup.close()
        finally:
            self.store.close()

    def assert_no_orphans(self) -> None:
        for pid in self.pids:
            assert not pid_alive(pid), f"peer pid {pid} outlived its supervisor"


@pytest.fixture
def bridge(tmp_path: Path) -> Iterator[Bridge]:
    b = Bridge(tmp_path / "heph")
    try:
        yield b
    finally:
        b.close()
        b.assert_no_orphans()


def wait_for(predicate: Any, *, timeout: float = 30.0, what: str = "condition") -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {what}")


# ---------------------------------------------------------------------------
# 1. 16 concurrent runs, stalled consumption, restart survival


def test_bridge_bounds_sixteen_stalled_runs_each_ack_one_terminal(tmp_path: Path) -> None:
    root = tmp_path / "heph"
    bridge = Bridge(root)
    runs = [f"run-{i:02d}" for i in range(BRIDGE_RUN_SLOTS)]
    try:
        # A registered client that NEVER drains: consumption is stalled for the
        # whole scenario, yet the terminal channel must still make progress.
        queue = bridge.pump.add_client("stalled")
        for run_id in runs:
            bridge.admission.admit_run(run_id)

        # All 16 slots are taken; the 17th run is refused, not queued forever.
        assert bridge.admission.capacity() == 0
        with pytest.raises(BusyError):
            bridge.admission.admit_run("run-17")

        # The peer emits all 16 terminals before any ack is processed.
        assert bridge.call("emit_terminals", {"runs": runs, "state": "completed"})["count"] == 16
        wait_for(
            lambda: len(bridge.pump.acked_terminals) == len(runs),
            what="16 durable terminal acks",
        )

        # Exactly one durable terminal per run, each named back to the peer once.
        acks = cast("dict[str, Any]", bridge.call("acks"))["acks"]
        assert sorted(str(entry["run_id"]) for entry in acks) == sorted(runs)
        assert len(acks) == len(runs), "a terminal was acknowledged more than once"
        for run_id in runs:
            record = bridge.admission.get_terminal(run_id)
            assert record is not None and record.state is TerminalState.COMPLETED
            assert bridge.pump.acked_terminals[run_id] == record.terminal_id

        # The stalled client still holds every never-dropped terminal event.
        assert queue.size >= len(runs)
        drained = queue.drain()
        assert sum(1 for ev in drained if ev.kind == "terminal") == len(runs)

        # Slots were released only by the durable acknowledgment.
        assert bridge.admission.capacity() == BRIDGE_RUN_SLOTS
    finally:
        bridge.close()
        bridge.assert_no_orphans()

    # Restart: the admission + terminal-ack rows are durable, and occupancy is
    # reconstructed as the union of the unfinished sets (here: empty).
    store = open_bridge_store(root)
    try:
        after = BridgeAdmission(store.admission)
        report = store.admission.startup_reconstruct()
        assert report.occupied_run_ids == frozenset()
        assert report.available_slots == BRIDGE_RUN_SLOTS
        for run_id in runs:
            record = after.get_terminal(run_id)
            assert record is not None and record.state is TerminalState.COMPLETED
            assert store.admission.get(run_id).terminal_acked_at is not None
    finally:
        store.close()


def test_bridge_bounds_unacked_terminals_still_occupy_their_slots(tmp_path: Path) -> None:
    """Completed-but-unacknowledged runs keep the 17th admission busy."""
    store = open_bridge_store(tmp_path / "heph")
    try:
        admission = BridgeAdmission(store.admission)
        for i in range(BRIDGE_RUN_SLOTS):
            admission.admit_run(f"r{i}")
            admission.ingest_terminal(f"r{i}", f"t{i}", TerminalState.COMPLETED)
        # 16 terminals, zero acks: the queue+running+unacked union is still 16.
        assert admission.active_count() == BRIDGE_RUN_SLOTS
        with pytest.raises(BusyError):
            admission.admit_run("r16")
        admission.acknowledge("r0", "t0")
        admission.admit_run("r16")
        assert admission.active_count() == BRIDGE_RUN_SLOTS
    finally:
        store.close()


# ---------------------------------------------------------------------------
# 2. progress flood coalescing


def test_bridge_bounds_progress_flood_coalesces_and_never_drops_durable_events(
    bridge: Bridge,
) -> None:
    queue = bridge.pump.add_client("cli")
    bridge.admission.admit_run("flood")

    progress = BUFFERED_EVENTS_MAX * 4
    keys = ["c0", "c1", "c2"]
    result = cast(
        "dict[str, Any]",
        bridge.call(
            "flood",
            {
                "run_id": "flood",
                "progress": progress,
                "tool_call_ids": keys,
            },
        ),
    )
    critical = int(result["critical"])
    assert progress > BUFFERED_EVENTS_MAX, "the flood must exceed the buffered-event bound"

    wait_for(lambda: queue.size >= critical, what="every critical event to arrive")
    # Give any straggling progress deltas a moment; they must not overflow.
    time.sleep(0.2)

    assert queue.overflowed is False, "coalescing must absorb a progress flood"
    drained = queue.drain()
    kinds = [ev.kind for ev in drained]

    # Progress collapsed to at most one event per (run_id, kind, tool_call_id)…
    assert kinds.count("progress") <= len(keys)
    # …while every never-droppable class survived in full.
    for kind in ("audit", "tool_call", "tool_result", "question", "answer"):
        assert kinds.count(kind) == critical // 5, kind
    assert len(drained) - kinds.count("progress") == critical
    # Ordering is preserved by sequence number.
    seqs = [ev.seq for ev in drained]
    assert seqs == sorted(seqs)

    # The run was never backpressure-cancelled: no terminal was synthesized.
    assert bridge.admission.get_terminal("flood") is None


def test_bridge_bounds_overflow_past_coalescing_cancels_only_that_run(bridge: Bridge) -> None:
    """When even coalescing cannot save the queue, the run is cancelled and its
    final error is routed through the terminal channel."""
    # A deliberately tiny client bound makes the durable backlog overflow.
    pump = EventPump(
        bridge.store.admission,
        ack_terminal=lambda run_id, terminal_id: None,
        cancel_run=lambda run_id: None,
        bound=4,
    )
    pump.add_client("tiny")
    bridge.admission.admit_run("over")
    bridge.admission.admit_run("safe")
    for seq in range(16):
        pump.on_notification(
            "event",
            {"run_id": "over", "seq": seq, "kind": "audit", "payload": {"i": seq}},
        )
    terminal = bridge.admission.get_terminal("over")
    assert terminal is not None and terminal.state is TerminalState.FAILED
    assert cast("dict[str, Any]", terminal.data)["reason"] == "backpressure_cancel"
    # The multiplexed sibling is untouched.
    assert bridge.admission.get_terminal("safe") is None


# ---------------------------------------------------------------------------
# 3. per-session cancellation isolation


def test_bridge_bounds_cancelling_one_run_leaves_its_sibling_healthy(bridge: Bridge) -> None:
    bridge.pump.add_client("cli")
    for run_id in ("run-a", "run-b"):
        bridge.admission.admit_run(run_id)
        bridge.call("hold", {"run_id": run_id})
    assert cast("dict[str, Any]", bridge.call("held"))["held"] == ["run-a", "run-b"]

    # Cancel exactly one run: its own abort controller ends only its stream.
    bridge.admission.request_cancel("run-a")
    bridge.sup.notify("cancel", {"run_id": "run-a"})
    wait_for(
        lambda: bridge.admission.get_terminal("run-a") is not None,
        what="the cancelled run's terminal",
    )
    cancelled = bridge.admission.get_terminal("run-a")
    assert cancelled is not None and cancelled.state is TerminalState.CANCELLED

    # The sibling never saw a terminal and still completes on request.
    assert bridge.admission.get_terminal("run-b") is None
    assert cast("dict[str, Any]", bridge.call("held"))["held"] == ["run-b"]
    bridge.call("complete", {"run_id": "run-b"})
    wait_for(
        lambda: bridge.admission.get_terminal("run-b") is not None,
        what="the sibling's terminal",
    )
    completed = bridge.admission.get_terminal("run-b")
    assert completed is not None and completed.state is TerminalState.COMPLETED

    # One terminal each, both acknowledged exactly once.
    acks = cast("dict[str, Any]", bridge.call("acks"))["acks"]
    assert sorted(str(entry["run_id"]) for entry in acks) == ["run-a", "run-b"]
    assert len(acks) == 2


def test_bridge_bounds_a_client_queue_bound_is_the_declared_event_budget() -> None:
    assert PerClientQueue().bound == BUFFERED_EVENTS_MAX
