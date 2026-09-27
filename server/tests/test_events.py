"""Event pump: coalescing, 1024 bound, durable single-terminal ack, backpressure."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from hephaestus.agent_bridge.events import (
    BUFFERED_EVENTS_MAX,
    EventPump,
    HephaestusEvent,
    PerClientQueue,
    coalesce_key,
)
from opstore.admission import AdmissionControl

from opstore import OpStore


@pytest.fixture
def store(tmp_path: Path) -> Iterator[OpStore]:
    s = OpStore.create(tmp_path / "store")
    try:
        yield s
    finally:
        s.close()


# -- per-client queue coalescing -------------------------------------------


def test_progress_coalesces_durable_never_drops() -> None:
    q = PerClientQueue(bound=BUFFERED_EVENTS_MAX)
    for seq in range(100):
        q.push(HephaestusEvent(run_id="r", seq=seq, kind="progress", tool_call_id="t1"))
    q.push(HephaestusEvent(run_id="r", seq=100, kind="audit"))
    q.push(HephaestusEvent(run_id="r", seq=101, kind="tool_result", tool_call_id="t1"))
    drained = q.drain()
    kinds = [e.kind for e in drained]
    # 100 progress events for one key collapse to a single latest
    assert kinds.count("progress") == 1
    assert kinds.count("audit") == 1
    assert kinds.count("tool_result") == 1
    latest_progress = next(e for e in drained if e.kind == "progress")
    assert latest_progress.seq == 99


def test_coalesce_key_distinguishes_tool_call_id() -> None:
    a = HephaestusEvent(run_id="r", seq=1, kind="progress", tool_call_id="t1")
    b = HephaestusEvent(run_id="r", seq=2, kind="progress", tool_call_id="t2")
    assert coalesce_key(a) != coalesce_key(b)
    q = PerClientQueue()
    q.push(a)
    q.push(b)
    assert len([e for e in q.drain() if e.kind == "progress"]) == 2


def test_durable_bound_overflow_signals_without_exceeding_the_bound() -> None:
    q = PerClientQueue(bound=4)
    fits = [q.push(HephaestusEvent(run_id="r", seq=i, kind="audit")) for i in range(6)]
    assert fits[:3] == [True, True, True]
    assert fits[3:] == [False, False, False]
    assert q.overflowed
    assert q.size == 3  # one slot remains available for the authoritative terminal


def test_distinct_progress_keys_keep_total_queue_memory_bounded() -> None:
    q = PerClientQueue(bound=4)
    for seq in range(100):
        assert q.push(
            HephaestusEvent(run_id="r", seq=seq, kind="progress", tool_call_id=f"tool-{seq}")
        )
        assert q.size <= q.bound
    drained = q.drain()
    assert len(drained) == 3
    assert [event.seq for event in drained] == [97, 98, 99]


def test_overflow_latches_and_only_the_terminal_uses_the_reserved_slot() -> None:
    q = PerClientQueue(bound=4)
    for seq in range(3):
        assert q.push(HephaestusEvent(run_id="r", seq=seq, kind="audit"))
    assert not q.push(HephaestusEvent(run_id="r", seq=3, kind="tool_result"))
    for seq in range(4, 100):
        assert not q.push(HephaestusEvent(run_id="r", seq=seq, kind="audit"))
        assert q.size == 3
    assert q.push(HephaestusEvent(run_id="r", seq=2**62, kind="terminal"))
    assert q.size == q.bound
    assert [event.kind for event in q.drain()][-1] == "terminal"


# -- flood: coalescing preserves every never-drop event --------------------


def test_flood_coalescing_preserves_all_critical_events(store: OpStore) -> None:
    pump = EventPump(AdmissionControl(store.db))
    q = pump.add_client("client-1")
    critical = 0
    for seq in range(5000):
        if seq % 10 == 0:
            pump.on_event(HephaestusEvent(run_id="r", seq=seq, kind="audit"))
            critical += 1
        else:
            pump.on_event(HephaestusEvent(run_id="r", seq=seq, kind="progress", tool_call_id="tc"))
    drained = q.drain()
    assert sum(1 for e in drained if e.kind == "audit") == critical
    assert sum(1 for e in drained if e.kind == "progress") == 1  # one key -> latest only


def test_observer_distinct_progress_flood_is_bounded_without_run_cancellation(
    store: OpStore,
) -> None:
    cancelled: list[str] = []
    pump = EventPump(AdmissionControl(store.db), cancel_run=cancelled.append, bound=8)
    observer = pump.add_observer("slow")
    for seq in range(100):
        pump.on_event(
            HephaestusEvent(
                run_id="run-progress",
                seq=seq,
                kind="progress",
                tool_call_id=f"tool-{seq}",
            )
        )
        assert observer.queue.size <= 8
    assert not observer.resync_required
    assert cancelled == []


# -- durable terminal + ack ------------------------------------------------


def test_terminal_durably_acked_once(store: OpStore) -> None:
    admission = AdmissionControl(store.db)
    admission.admit("run-1")
    acks: list[tuple[str, str]] = []
    pump = EventPump(admission, ack_terminal=lambda r, t: acks.append((r, t)))
    ingest = pump.on_terminal(
        {"run_id": "run-1", "terminal_id": "term-1", "state": "completed", "payload": {}}
    )
    assert ingest.acked is True
    assert ingest.duplicate is False
    # durable: the admission slot is released (acked)
    row = admission.get("run-1")
    assert row.terminal_acked_at is not None
    assert acks == [("run-1", "term-1")]
    # exactly one terminal record survives
    term = admission.get_terminal("run-1")
    assert term is not None and term.terminal_id == "term-1"


def test_duplicate_terminal_replays_same_state(store: OpStore) -> None:
    admission = AdmissionControl(store.db)
    admission.admit("run-2")
    pump = EventPump(admission)
    first = pump.on_terminal({"run_id": "run-2", "terminal_id": "t", "state": "completed"})
    second = pump.on_terminal({"run_id": "run-2", "terminal_id": "t", "state": "completed"})
    assert first.record.terminal_id == second.record.terminal_id
    assert second.duplicate is True
    # a distinct second terminal cannot displace the first
    third = pump.on_terminal({"run_id": "run-2", "terminal_id": "OTHER", "state": "failed"})
    assert third.record.terminal_id == "t"
    assert third.record.state.value == "completed"


def test_stalled_consumer_still_one_durable_ack_per_run(store: OpStore) -> None:
    admission = AdmissionControl(store.db)
    pump = EventPump(admission)
    # a stalled client never drains its queue
    pump.add_client("stalled")
    for i in range(16):
        admission.admit(f"run-{i}")
    for i in range(16):
        pump.on_terminal({"run_id": f"run-{i}", "terminal_id": f"t-{i}", "state": "completed"})
    for i in range(16):
        row = admission.get(f"run-{i}")
        assert row.terminal_acked_at is not None
        assert pump.acked_terminals[f"run-{i}"] == f"t-{i}"


def test_terminal_only_saturation_detaches_client_for_explicit_resync(store: OpStore) -> None:
    admission = AdmissionControl(store.db)
    pump = EventPump(admission, bound=2)
    stalled = pump.add_client("stalled")
    for i in range(3):
        admission.admit(f"run-{i}")
        pump.on_terminal({"run_id": f"run-{i}", "terminal_id": f"t-{i}", "state": "completed"})

    # Every terminal is durable and acknowledged, while the finite queue names
    # its incomplete view and is no longer registered as if it were complete.
    assert stalled.overflowed
    assert [event.run_id for event in stalled.drain()] == ["run-0", "run-1"]
    for i in range(3):
        row = admission.get(f"run-{i}")
        assert row.terminal_acked_at is not None
        assert pump.acked_terminals[f"run-{i}"] == f"t-{i}"
    replacement = pump.add_client("stalled")
    assert replacement is not stalled
    assert replacement.size == 0
    assert not replacement.overflowed


# -- backpressure-cancel ---------------------------------------------------


def test_backpressure_cancels_run_and_routes_terminal(store: OpStore) -> None:
    admission = AdmissionControl(store.db)
    admission.admit("run-bp")
    cancelled: list[str] = []
    pump = EventPump(
        admission,
        cancel_run=cancelled.append,
        bound=8,
    )
    queue = pump.add_client("stalled")
    # flood non-droppable events past the bound
    for seq in range(50):
        pump.on_event(HephaestusEvent(run_id="run-bp", seq=seq, kind="tool_result"))
    assert cancelled == ["run-bp"]
    drained = queue.drain()
    assert len(drained) == 8
    assert drained[-1].kind == "terminal"
    # The overflowing client was detached after receiving the terminal, so
    # post-overflow durable events cannot regrow its queue.
    pump.on_event(HephaestusEvent(run_id="another-run", seq=100, kind="audit"))
    assert queue.size == 0
    term = admission.get_terminal("run-bp")
    assert term is not None
    assert term.state.value == "failed"
    assert term.data == {"reason": "backpressure_cancel"}


def test_notification_sink_dispatch(store: OpStore) -> None:
    admission = AdmissionControl(store.db)
    admission.admit("run-n")
    pump = EventPump(admission)
    q = pump.add_client("c")
    pump.on_notification("event", {"run_id": "run-n", "seq": 1, "kind": "audit"})
    pump.on_notification("terminal", {"run_id": "run-n", "terminal_id": "tn", "state": "completed"})
    kinds = [e.kind for e in q.drain()]
    assert "audit" in kinds
    assert "terminal" in kinds
