"""Bridge admission policy tests: 16-slot budget, terminal-unacked occupancy, union."""

from __future__ import annotations

import pytest
from hephaestus.agent_bridge.admission import (
    BRIDGE_RUN_SLOTS,
    BridgeAdmission,
    bridge_store_config,
)
from opstore.errors import BusyError
from opstore.types import TerminalState

from opstore import OpStore


def test_bridge_run_slots_is_sixteen_from_limits() -> None:
    assert BRIDGE_RUN_SLOTS == 16
    assert bridge_store_config().run_slots == 16


def test_admit_sixteen_then_seventeenth_is_busy(store: OpStore) -> None:
    adm = BridgeAdmission(store.admission)
    for i in range(BRIDGE_RUN_SLOTS):
        adm.admit_run(f"run-{i}")
    assert adm.capacity() == 0
    assert adm.active_count() == BRIDGE_RUN_SLOTS
    with pytest.raises(BusyError):
        adm.admit_run("run-16")


def test_completed_but_unacked_still_occupies_slot(store: OpStore) -> None:
    adm = BridgeAdmission(store.admission)
    for i in range(BRIDGE_RUN_SLOTS):
        adm.admit_run(f"run-{i}")
    # Terminate one WITHOUT acknowledging: it must still occupy its slot.
    adm.ingest_terminal("run-0", "t0", TerminalState.COMPLETED)
    assert adm.capacity() == 0
    with pytest.raises(BusyError):
        adm.admit_run("run-16")
    # Acknowledging releases the slot; now a new run fits.
    adm.acknowledge("run-0", "t0")
    assert adm.capacity() == 1
    adm.admit_run("run-16")
    assert adm.capacity() == 0


def test_admit_is_idempotent_on_run_id(store: OpStore) -> None:
    adm = BridgeAdmission(store.admission)
    first = adm.admit_run("run-x")
    again = adm.admit_run("run-x")
    assert first.run_id == again.run_id == "run-x"
    assert adm.active_count() == 1


def test_ingest_terminal_idempotent_distinct_rejected(store: OpStore) -> None:
    from opstore.errors import TerminalConflictError

    adm = BridgeAdmission(store.admission)
    adm.admit_run("run-1")
    adm.ingest_terminal("run-1", "t1", TerminalState.COMPLETED, {"a": 1})
    # Same terminal replays.
    adm.ingest_terminal("run-1", "t1", TerminalState.COMPLETED, {"a": 1})
    # A distinct terminal is rejected.
    with pytest.raises(TerminalConflictError):
        adm.ingest_terminal("run-1", "t2", TerminalState.FAILED)


def test_startup_reconstruct_union_not_sum(store: OpStore, tmp_path: object) -> None:
    adm = BridgeAdmission(store.admission)
    adm.admit_run("run-a")  # nonterminal
    adm.admit_run("run-b")
    adm.ingest_terminal("run-b", "tb", TerminalState.COMPLETED)  # terminal, unacked
    report = adm.startup_reconstruct()
    # run-b appears in BOTH the admitted-nonterminal repair scan and terminal set;
    # occupancy is the UNION (2), never the sum (3).
    assert report.occupied_run_ids == frozenset({"run-a", "run-b"})
    assert report.available_slots == BRIDGE_RUN_SLOTS - 2


def test_recover_cancel_requested_becomes_cancelled(store: OpStore) -> None:
    adm = BridgeAdmission(store.admission)
    adm.admit_run("run-c")
    assert adm.request_cancel("run-c") is True
    result = adm.recover("run-c")
    assert result.terminal is not None
    assert result.terminal.state is TerminalState.CANCELLED


def test_capacity_survives_restart(store: OpStore) -> None:
    adm = BridgeAdmission(store.admission)
    for i in range(3):
        adm.admit_run(f"run-{i}")
    adm.ingest_terminal("run-0", "t0", TerminalState.COMPLETED)
    root = store.root
    store.close()
    reopened = OpStore.open(root, bridge_store_config())
    try:
        adm2 = BridgeAdmission(reopened.admission)
        report = adm2.startup_reconstruct()
        # run-0 terminal-unacked + run-1,2 nonterminal = 3 occupied.
        assert len(report.occupied_run_ids) == 3
        assert adm2.capacity() == BRIDGE_RUN_SLOTS - 3
    finally:
        reopened.close()
