"""Tests for opstore.admission: slots, suspension/resume FIFO, terminals, recovery, crashes."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

import pytest
from conftest import REPO_ROOT, CrashRunner, FakeClock, FakeLiveness
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import (
    RuleBasedStateMachine,
    invariant,
    rule,
    run_state_machine_as_test,  # pyright: ignore[reportUnknownVariableType]
)
from opstore.admission import (
    CRASH_AFTER_ACK,
    CRASH_AFTER_ADMIT,
    CRASH_AFTER_SUSPEND,
    CRASH_AFTER_TERMINAL_INSERT,
    AdmissionControl,
    RecoveryReason,
)
from opstore.db import Database
from opstore.errors import BusyError, ConflictedError, NotFoundError, TerminalConflictError
from opstore.types import (
    CRASH_ENV_VAR,
    AdmissionState,
    OwnerId,
    StoreConfig,
    TerminalState,
)

SLOTS = StoreConfig().run_slots  # 16 per DESIGN.md


@pytest.fixture
def control(db: Database, fake_clock: FakeClock, fake_liveness: FakeLiveness) -> AdmissionControl:
    return AdmissionControl(db, clock=fake_clock, liveness=fake_liveness)


def small_control(
    db: Database, slots: int, fake_clock: FakeClock, fake_liveness: FakeLiveness
) -> AdmissionControl:
    return AdmissionControl(
        db, config=StoreConfig(run_slots=slots), clock=fake_clock, liveness=fake_liveness
    )


def finish(control: AdmissionControl, run_id: str) -> None:
    record = control.insert_terminal(run_id, f"t-{run_id}", TerminalState.COMPLETED, None)
    control.acknowledge_terminal(run_id, record.terminal_id)


def terminal_count(db: Database, run_id: str | None = None) -> int:
    if run_id is None:
        row = db.conn.execute("SELECT COUNT(*) FROM terminals").fetchone()
    else:
        row = db.conn.execute(
            "SELECT COUNT(*) FROM terminals WHERE run_id = ?", (run_id,)
        ).fetchone()
    return int(row[0])


# --- slot rule -------------------------------------------------------------


def test_fill_all_slots_then_busy(control: AdmissionControl) -> None:
    for i in range(SLOTS):
        row = control.admit(f"run-{i}")
        assert row.state is AdmissionState.ADMITTED
    assert control.active_count() == SLOTS
    assert control.available_slots() == 0
    with pytest.raises(BusyError) as excinfo:
        control.admit("run-overflow")
    assert excinfo.value.code == "busy"


def test_completed_but_unacked_still_occupies(control: AdmissionControl) -> None:
    for i in range(SLOTS):
        control.admit(f"run-{i}")
    record = control.insert_terminal("run-0", "t-0", TerminalState.COMPLETED, {"ok": True})
    # Terminal inserted but NOT acked: the slot is still held.
    with pytest.raises(BusyError):
        control.admit("run-new")
    assert control.active_count() == SLOTS
    control.acknowledge_terminal("run-0", record.terminal_id)
    # Slot released only after the ack is durable.
    assert control.active_count() == SLOTS - 1
    assert control.admit("run-new").state is AdmissionState.ADMITTED


def test_admit_idempotent_and_deadline_persisted(
    control: AdmissionControl, fake_clock: FakeClock
) -> None:
    deadline = fake_clock.now() + 50.0
    owner = OwnerId(pid=1234, pid_start_ns=5678)
    row = control.admit("run-a", deadline_at=deadline, owner=owner)
    assert row.deadline_at == deadline
    assert row.owner == owner
    assert row.admitted_at == fake_clock.now()
    again = control.admit("run-a", deadline_at=deadline + 999.0)
    assert again == row  # idempotent replay returns the persisted row
    assert control.active_count() == 1
    assert control.get("run-a").deadline_at == deadline


def test_get_unknown_run_not_found(control: AdmissionControl) -> None:
    with pytest.raises(NotFoundError) as excinfo:
        control.get("nope")
    assert excinfo.value.code == "not_found"


# --- dispatch --------------------------------------------------------------


def test_dispatch_transitions_and_guards(control: AdmissionControl) -> None:
    control.admit("run-a")
    owner = OwnerId(pid=99, pid_start_ns=1)
    row = control.dispatch("run-a", owner=owner)
    assert row.state is AdmissionState.DISPATCHED
    assert row.owner == owner
    # Idempotent re-dispatch.
    assert control.dispatch("run-a").state is AdmissionState.DISPATCHED

    control.admit("run-b")
    assert control.request_cancel("run-b") is True
    with pytest.raises(ConflictedError):
        control.dispatch("run-b")

    control.admit("run-c")
    control.insert_terminal("run-c", "t-c", TerminalState.FAILED, None)
    with pytest.raises(TerminalConflictError):
        control.dispatch("run-c")

    with pytest.raises(NotFoundError):
        control.dispatch("run-missing")


# --- suspension ------------------------------------------------------------


def test_suspend_releases_slot_and_reserves_child(control: AdmissionControl) -> None:
    for i in range(SLOTS):
        control.admit(f"run-{i}")
    control.dispatch("run-0")
    child = control.suspend("run-0", "child-0")
    assert child.state is AdmissionState.ADMITTED
    assert control.get("run-0").suspended is True
    # Net occupancy unchanged: still full, new admissions still Busy.
    assert control.active_count() == SLOTS
    with pytest.raises(BusyError):
        control.admit("run-new")


def test_suspend_replay_and_guards(control: AdmissionControl) -> None:
    control.admit("p")
    control.admit("other")
    child = control.suspend("p", "c")
    # Idempotent replay of the same suspension returns the same child.
    assert control.suspend("p", "c") == child
    # A suspended parent naming a nonexistent child is a conflict.
    with pytest.raises(ConflictedError):
        control.suspend("p", "c2")
    # Child id colliding with an existing admission is a conflict.
    with pytest.raises(ConflictedError):
        control.suspend("other", "c")
    # Terminal parent cannot suspend.
    control.insert_terminal("other", "t-other", TerminalState.COMPLETED, None)
    with pytest.raises(TerminalConflictError):
        control.suspend("other", "c3")
    # Cancel-requested parent cannot suspend.
    control.admit("cx")
    control.request_cancel("cx")
    with pytest.raises(ConflictedError):
        control.suspend("cx", "c4")
    with pytest.raises(NotFoundError):
        control.suspend("missing", "c5")


def test_no_double_count_suspended_parent_plus_child(
    db: Database, fake_clock: FakeClock, fake_liveness: FakeLiveness
) -> None:
    control = small_control(db, 2, fake_clock, fake_liveness)
    control.admit("p1")
    control.suspend("p1", "c1")
    assert control.active_count() == 1  # parent excluded, child counted — never 2
    control.admit("p2")
    assert control.active_count() == 2
    assert control.occupied_run_ids() == frozenset({"c1", "p2"})
    with pytest.raises(BusyError):
        control.admit("p3")


# --- resume FIFO priority --------------------------------------------------


def test_resume_reservation_has_priority_over_new_admits(
    db: Database, fake_clock: FakeClock, fake_liveness: FakeLiveness
) -> None:
    control = small_control(db, 1, fake_clock, fake_liveness)
    control.admit("p")
    control.suspend("p", "c")
    finish(control, "c")
    assert control.active_count() == 0
    control.resume_request("p")
    # The queued resume reserves the only free slot ahead of new admissions.
    assert control.pending_resume_count() == 1
    with pytest.raises(BusyError):
        control.admit("new")
    resumed = control.resume("p")
    assert resumed.suspended is False
    assert control.active_count() == 1
    with pytest.raises(BusyError):
        control.admit("new")


def test_resume_fifo_order_between_parents(
    db: Database, fake_clock: FakeClock, fake_liveness: FakeLiveness
) -> None:
    control = small_control(db, 2, fake_clock, fake_liveness)
    control.admit("p1")
    control.admit("p2")
    control.suspend("p1", "c1")
    control.suspend("p2", "c2")
    finish(control, "c1")  # one slot free; c2 still active
    control.resume_request("p1")
    control.resume_request("p2")
    # p2 queued behind p1: the single free slot belongs to p1 first.
    with pytest.raises(BusyError):
        control.resume("p2")
    assert control.resume("p1").suspended is False
    with pytest.raises(BusyError):
        control.resume("p2")
    finish(control, "c2")
    assert control.resume("p2").suspended is False


def test_resume_guards_and_idempotency(control: AdmissionControl) -> None:
    control.admit("p")
    control.suspend("p", "c")
    with pytest.raises(ConflictedError):
        control.resume("p")  # not requested
    control.resume_request("p")
    control.resume_request("p")  # idempotent
    assert control.pending_resume_count() == 1
    row = control.resume("p")
    assert row.suspended is False
    assert control.resume("p") == row  # idempotent once resumed
    control.resume_request("p")  # no-op on a resumed run
    assert control.pending_resume_count() == 0

    control.insert_terminal("p", "t-p", TerminalState.COMPLETED, None)
    with pytest.raises(TerminalConflictError):
        control.resume_request("p")
    with pytest.raises(TerminalConflictError):
        control.resume("p")
    with pytest.raises(NotFoundError):
        control.resume("missing")
    with pytest.raises(NotFoundError):
        control.resume_request("missing")


def test_terminal_prunes_resume_queue_reservation(
    db: Database, fake_clock: FakeClock, fake_liveness: FakeLiveness
) -> None:
    control = small_control(db, 1, fake_clock, fake_liveness)
    control.admit("p")
    control.suspend("p", "c")
    finish(control, "c")
    control.resume_request("p")
    with pytest.raises(BusyError):
        control.admit("new")
    # Cancelling the suspended parent and recovering it to a terminal drops the
    # queued reservation, freeing the slot for new admissions.
    control.request_cancel("p")
    result = control.recover("p")
    assert result.synthesized
    assert control.pending_resume_count() == 0
    assert control.admit("new").state is AdmissionState.ADMITTED


# --- cancel ---------------------------------------------------------------


def test_request_cancel_cas_only_without_terminal(control: AdmissionControl) -> None:
    control.admit("r")
    assert control.request_cancel("r") is True
    assert control.get("r").state is AdmissionState.CANCEL_REQUESTED
    assert control.request_cancel("r") is True  # idempotent
    control.admit("done")
    control.insert_terminal("done", "t-done", TerminalState.COMPLETED, None)
    assert control.request_cancel("done") is False
    with pytest.raises(NotFoundError):
        control.request_cancel("missing")


# --- terminal uniqueness / idempotency ------------------------------------


def test_insert_terminal_idempotent_same_rejects_distinct(
    control: AdmissionControl, db: Database
) -> None:
    control.admit("r")
    first = control.insert_terminal("r", "t-1", TerminalState.COMPLETED, {"n": 1})
    replay = control.insert_terminal("r", "t-1", TerminalState.COMPLETED, {"n": 1})
    assert replay == first
    assert terminal_count(db, "r") == 1
    with pytest.raises(TerminalConflictError) as excinfo:
        control.insert_terminal("r", "t-2", TerminalState.FAILED, {"n": 2})
    assert excinfo.value.code == "terminal_conflict"
    with pytest.raises(TerminalConflictError):
        control.insert_terminal("r", "t-1", TerminalState.COMPLETED, {"n": 999})
    assert terminal_count(db, "r") == 1
    assert control.get("r").state is AdmissionState.TERMINAL
    assert control.get("r").terminal_id == "t-1"
    with pytest.raises(NotFoundError):
        control.insert_terminal("missing", "t-x", TerminalState.COMPLETED, None)


def test_terminal_transaction_projects_atomically(
    control: AdmissionControl, db: Database, fake_clock: FakeClock
) -> None:
    control.admit("r")
    with control.terminal_transaction("r", "t-r", TerminalState.COMPLETED, {"ok": True}) as conn:
        conn.execute("INSERT INTO pins(ref, created_at) VALUES(?, ?)", ("proj", fake_clock.now()))
    assert terminal_count(db, "r") == 1
    assert db.conn.execute("SELECT 1 FROM pins WHERE ref = 'proj'").fetchone() is not None

    control.admit("r2")
    with (
        pytest.raises(RuntimeError),
        control.terminal_transaction("r2", "t-r2", TerminalState.FAILED, None) as conn,
    ):
        conn.execute("INSERT INTO pins(ref, created_at) VALUES(?, ?)", ("proj2", fake_clock.now()))
        raise RuntimeError("projection failed")
    # Both the terminal and the projection rolled back together.
    assert terminal_count(db, "r2") == 0
    assert db.conn.execute("SELECT 1 FROM pins WHERE ref = 'proj2'").fetchone() is None
    assert control.get("r2").state is AdmissionState.ADMITTED


def test_terminal_unique_under_concurrent_threads(
    store_root: Path, db: Database, control: AdmissionControl
) -> None:
    control.admit("race")
    n = 8
    results: list[str] = []
    results_lock = threading.Lock()
    barrier = threading.Barrier(n)

    def worker(i: int) -> None:
        with Database.connect(store_root / "state.db") as tdb:
            ac = AdmissionControl(tdb)
            barrier.wait()
            try:
                ac.insert_terminal("race", f"t-{i}", TerminalState.COMPLETED, {"i": i})
                outcome = "won"
            except TerminalConflictError:
                outcome = "conflict"
        with results_lock:
            results.append(outcome)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert results.count("won") == 1
    assert results.count("conflict") == n - 1
    assert terminal_count(db, "race") == 1


RACE_SCRIPT = """
from pathlib import Path
from opstore.admission import AdmissionControl
from opstore.db import Database
from opstore.errors import TerminalConflictError
from opstore.types import TerminalState
root = Path({root!r})
with Database.connect(root / "state.db") as db:
    ac = AdmissionControl(db)
    try:
        ac.insert_terminal("race-sub", {tid!r}, TerminalState.COMPLETED, {{"who": {tid!r}}})
        print("won")
    except TerminalConflictError:
        print("conflict")
"""


def test_terminal_unique_under_concurrent_subprocesses(
    store_root: Path, db: Database, control: AdmissionControl
) -> None:
    control.admit("race-sub")
    env = {k: v for k, v in os.environ.items() if k != CRASH_ENV_VAR}
    procs = [
        subprocess.Popen(
            ["uv", "run", "python", "-c", RACE_SCRIPT.format(root=str(store_root), tid=tid)],
            cwd=REPO_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for tid in ("t-proc-a", "t-proc-b")
    ]
    outcomes: list[str] = []
    for proc in procs:
        out, err = proc.communicate(timeout=120)
        assert proc.returncode == 0, err
        outcomes.append(out.strip())
    assert sorted(outcomes) == ["conflict", "won"]
    assert terminal_count(db, "race-sub") == 1


# --- acknowledgment --------------------------------------------------------


def test_ack_idempotent_and_guards(
    control: AdmissionControl, db: Database, fake_clock: FakeClock
) -> None:
    control.admit("r")
    with pytest.raises(NotFoundError):
        control.acknowledge_terminal("r", "t-r")  # no terminal yet
    control.insert_terminal("r", "t-r", TerminalState.COMPLETED, None)
    control.acknowledge_terminal("r", "t-r")
    first_ack = control.get("r").terminal_acked_at
    assert first_ack == fake_clock.now()
    fake_clock.advance(100.0)
    control.acknowledge_terminal("r", "t-r")  # idempotent: timestamp preserved
    assert control.get("r").terminal_acked_at == first_ack
    with pytest.raises(TerminalConflictError):
        control.acknowledge_terminal("r", "t-wrong")
    with pytest.raises(NotFoundError):
        control.acknowledge_terminal("missing", "t-x")
    assert terminal_count(db, "r") == 1


# --- startup reconstruction (union, not sum) -------------------------------


def test_startup_union_not_sum_with_overlapping_sets(
    control: AdmissionControl, db: Database
) -> None:
    control.admit("a")  # admitted-nonterminal only
    control.admit("b")
    control.insert_terminal("b", "t-b", TerminalState.COMPLETED, None)  # terminal-unacked
    control.admit("c")
    control.insert_terminal("c", "t-c", TerminalState.COMPLETED, None)
    # Simulate divergence: c is in BOTH the admitted-nonterminal set and the
    # terminal-unacked set (as after a partial legacy write).
    db.conn.execute(
        "UPDATE admissions SET state = 'DISPATCHED', terminal_id = NULL WHERE run_id = 'c'"
    )
    control.admit("d")
    finish(control, "d")  # acked: occupies nothing

    report = control.startup_reconstruct()
    # Union: c counted once, never twice; d released.
    assert report.occupied_run_ids == frozenset({"a", "b", "c"})
    assert report.available_slots == SLOTS - 3
    assert report.resolved_run_ids == frozenset({"c"})
    repaired = control.get("c")
    assert repaired.state is AdmissionState.TERMINAL
    assert repaired.terminal_id == "t-c"


def test_startup_reconstruct_empty_store(control: AdmissionControl) -> None:
    report = control.startup_reconstruct()
    assert report.occupied_run_ids == frozenset()
    assert report.available_slots == SLOTS
    assert report.resolved_run_ids == frozenset()


# --- recovery precedence ---------------------------------------------------


def test_recover_existing_terminal_wins(
    control: AdmissionControl, db: Database, fake_clock: FakeClock
) -> None:
    dead_owner = OwnerId(pid=4242, pid_start_ns=7)  # not in FakeLiveness.alive
    control.admit("r", deadline_at=fake_clock.now() - 1.0, owner=dead_owner)
    control.insert_terminal("r", "t-r", TerminalState.COMPLETED, None)
    # Even with a cancel-looking state, an elapsed deadline, and a dead owner,
    # the existing terminal wins and nothing new is synthesized.
    db.conn.execute("UPDATE admissions SET state = 'CANCEL_REQUESTED' WHERE run_id = 'r'")
    result = control.recover("r")
    assert result.reason is RecoveryReason.EXISTING_TERMINAL
    assert not result.synthesized
    assert result.terminal is not None
    assert result.terminal.terminal_id == "t-r"
    assert result.terminal.state is TerminalState.COMPLETED
    assert terminal_count(db, "r") == 1


def test_recover_cancel_beats_deadline_and_owner_loss(
    control: AdmissionControl, db: Database, fake_clock: FakeClock
) -> None:
    dead_owner = OwnerId(pid=4242, pid_start_ns=7)
    control.admit("r", deadline_at=fake_clock.now() + 10.0, owner=dead_owner)
    fake_clock.advance(100.0)  # deadline elapsed AND owner dead
    assert control.request_cancel("r") is True
    result = control.recover("r")
    assert result.reason is RecoveryReason.CANCEL_REQUESTED
    assert result.synthesized
    assert result.terminal is not None
    assert result.terminal.state is TerminalState.CANCELLED
    # Exactly one synthesized terminal, ever.
    again = control.recover("r")
    assert again.reason is RecoveryReason.EXISTING_TERMINAL
    assert not again.synthesized
    assert terminal_count(db, "r") == 1


def test_recover_deadline_beats_owner_loss(
    control: AdmissionControl, db: Database, fake_clock: FakeClock
) -> None:
    dead_owner = OwnerId(pid=4242, pid_start_ns=7)
    control.admit("r", deadline_at=fake_clock.now() + 10.0, owner=dead_owner)
    control.dispatch("r")
    fake_clock.advance(100.0)
    result = control.recover("r")
    assert result.reason is RecoveryReason.DEADLINE
    assert result.synthesized
    assert result.terminal is not None
    assert result.terminal.state is TerminalState.TIMED_OUT
    assert terminal_count(db, "r") == 1


def test_recover_confirmed_owner_loss_interrupted(
    control: AdmissionControl, db: Database, fake_clock: FakeClock
) -> None:
    dead_owner = OwnerId(pid=4242, pid_start_ns=7)
    control.admit("r", deadline_at=fake_clock.now() + 1000.0, owner=dead_owner)
    result = control.recover("r")
    assert result.reason is RecoveryReason.OWNER_LOSS
    assert result.terminal is not None
    assert result.terminal.state is TerminalState.INTERRUPTED
    assert terminal_count(db, "r") == 1


def test_recover_live_run_untouched(
    control: AdmissionControl,
    db: Database,
    fake_clock: FakeClock,
    fake_liveness: FakeLiveness,
) -> None:
    live_owner = OwnerId(pid=77, pid_start_ns=88)
    fake_liveness.alive.add(live_owner)
    control.admit("r", deadline_at=fake_clock.now() + 1000.0, owner=live_owner)
    result = control.recover("r")
    assert result.reason is RecoveryReason.LIVE
    assert result.terminal is None
    assert not result.synthesized
    # A run with neither owner nor deadline is also live (loss unconfirmable).
    control.admit("bare")
    assert control.recover("bare").reason is RecoveryReason.LIVE
    assert terminal_count(db) == 0
    with pytest.raises(NotFoundError):
        control.recover("missing")


# --- crash injection -------------------------------------------------------

ADMIT_SCRIPT = """
from pathlib import Path
from opstore.admission import AdmissionControl
from opstore.db import Database
from opstore.types import EnvCrashHook
root = Path({root!r})
with Database.connect(root / "state.db") as db:
    AdmissionControl(db, crash_hook=EnvCrashHook()).admit("crash-run")
"""

SUSPEND_SCRIPT = """
from pathlib import Path
from opstore.admission import AdmissionControl
from opstore.db import Database
from opstore.types import EnvCrashHook
root = Path({root!r})
with Database.connect(root / "state.db") as db:
    ac = AdmissionControl(db, crash_hook=EnvCrashHook())
    ac.admit("crash-parent")
    ac.suspend("crash-parent", "crash-child")
"""

TERMINAL_SCRIPT = """
from pathlib import Path
from opstore.admission import AdmissionControl
from opstore.db import Database
from opstore.types import EnvCrashHook, TerminalState
root = Path({root!r})
with Database.connect(root / "state.db") as db:
    ac = AdmissionControl(db, crash_hook=EnvCrashHook())
    ac.admit("crash-run")
    ac.insert_terminal("crash-run", "t-crash", TerminalState.COMPLETED, {{"ok": True}})
"""

ACK_SCRIPT = """
from pathlib import Path
from opstore.admission import AdmissionControl
from opstore.db import Database
from opstore.types import EnvCrashHook, TerminalState
root = Path({root!r})
with Database.connect(root / "state.db") as db:
    ac = AdmissionControl(db, crash_hook=EnvCrashHook())
    ac.admit("crash-run")
    ac.insert_terminal("crash-run", "t-crash", TerminalState.COMPLETED, {{"ok": True}})
    ac.acknowledge_terminal("crash-run", "t-crash")
"""


def test_crash_after_admit(store_root: Path, run_crash_subprocess: CrashRunner) -> None:
    proc = run_crash_subprocess(ADMIT_SCRIPT.format(root=str(store_root)), CRASH_AFTER_ADMIT)
    assert proc.returncode == 42, proc.stderr
    with Database.connect(store_root / "state.db") as db:
        control = AdmissionControl(db)
        report = control.startup_reconstruct()
        assert report.occupied_run_ids == frozenset({"crash-run"})
        assert report.available_slots == SLOTS - 1
        assert terminal_count(db) == 0  # no terminal was ever created
        # Re-admit after restart is an idempotent replay, not a second slot.
        control.admit("crash-run")
        assert control.active_count() == 1


def test_crash_after_suspend(store_root: Path, run_crash_subprocess: CrashRunner) -> None:
    proc = run_crash_subprocess(SUSPEND_SCRIPT.format(root=str(store_root)), CRASH_AFTER_SUSPEND)
    assert proc.returncode == 42, proc.stderr
    with Database.connect(store_root / "state.db") as db:
        control = AdmissionControl(db)
        report = control.startup_reconstruct()
        # Parent durably SUSPENDED_WAIT, child durably admitted: occupancy is 1.
        assert report.occupied_run_ids == frozenset({"crash-child"})
        assert control.get("crash-parent").suspended is True
        assert control.get("crash-child").state is AdmissionState.ADMITTED
        assert terminal_count(db) == 0
        # The suspended parent can complete its lifecycle after restart.
        finish(control, "crash-child")
        control.resume_request("crash-parent")
        assert control.resume("crash-parent").suspended is False


def test_crash_after_terminal_insert(store_root: Path, run_crash_subprocess: CrashRunner) -> None:
    proc = run_crash_subprocess(
        TERMINAL_SCRIPT.format(root=str(store_root)), CRASH_AFTER_TERMINAL_INSERT
    )
    assert proc.returncode == 42, proc.stderr
    with Database.connect(store_root / "state.db") as db:
        control = AdmissionControl(db)
        report = control.startup_reconstruct()
        # Terminal durable but unacked: the slot is still occupied.
        assert report.occupied_run_ids == frozenset({"crash-run"})
        assert terminal_count(db, "crash-run") == 1
        # Recovery finds the existing terminal and synthesizes NO extra one.
        result = control.recover("crash-run")
        assert result.reason is RecoveryReason.EXISTING_TERMINAL
        assert not result.synthesized
        assert terminal_count(db, "crash-run") == 1
        control.acknowledge_terminal("crash-run", "t-crash")
        assert control.occupied_run_ids() == frozenset()


def test_crash_after_ack(store_root: Path, run_crash_subprocess: CrashRunner) -> None:
    proc = run_crash_subprocess(ACK_SCRIPT.format(root=str(store_root)), CRASH_AFTER_ACK)
    assert proc.returncode == 42, proc.stderr
    with Database.connect(store_root / "state.db") as db:
        control = AdmissionControl(db)
        report = control.startup_reconstruct()
        # Ack was durable before the crash: the slot is released, nothing occupied.
        assert report.occupied_run_ids == frozenset()
        assert report.available_slots == SLOTS
        assert terminal_count(db, "crash-run") == 1
        acked_at = control.get("crash-run").terminal_acked_at
        assert acked_at is not None
        control.acknowledge_terminal("crash-run", "t-crash")  # idempotent replay
        assert control.get("crash-run").terminal_acked_at == acked_at
        assert terminal_count(db, "crash-run") == 1


def test_crash_scripts_complete_without_crash_point(
    store_root: Path, run_crash_subprocess: CrashRunner
) -> None:
    proc = run_crash_subprocess(ACK_SCRIPT.format(root=str(store_root)), None)
    assert proc.returncode == 0, proc.stderr
    with Database.connect(store_root / "state.db") as db:
        control = AdmissionControl(db)
        assert control.startup_reconstruct().occupied_run_ids == frozenset()
        assert terminal_count(db, "crash-run") == 1


# --- hypothesis state machine ---------------------------------------------


@dataclass
class ModelRun:
    state: str
    suspended: bool = False
    terminal_id: str | None = None
    acked: bool = False
    queued: bool = False


class AdmissionMachine(RuleBasedStateMachine):
    """Random admit/suspend/resume/cancel/terminal/ack sequences vs. a reference model."""

    SLOTS = 3

    def __init__(self) -> None:
        super().__init__()
        self._dir = tempfile.mkdtemp(prefix="admission-machine-")
        self.db = Database.connect(Path(self._dir) / "state.db")
        self.clock = FakeClock()
        self.control = AdmissionControl(
            self.db, config=StoreConfig(run_slots=self.SLOTS), clock=self.clock
        )
        self.model: dict[str, ModelRun] = {}
        self.queue_order: list[str] = []
        self.next_id = 0

    def teardown(self) -> None:
        self.db.close()
        shutil.rmtree(self._dir, ignore_errors=True)

    def _model_active(self) -> set[str]:
        return {rid for rid, r in self.model.items() if not r.acked and not r.suspended}

    def _model_pending(self) -> int:
        return sum(
            1
            for r in self.model.values()
            if r.queued and r.suspended and r.terminal_id is None and not r.acked
        )

    def _pick(self, index: int, runs: list[str]) -> str | None:
        return None if not runs else sorted(runs)[index % len(runs)]

    def _fresh_id(self, prefix: str) -> str:
        self.next_id += 1
        return f"{prefix}-{self.next_id}"

    @rule()
    def admit_new(self) -> None:
        rid = self._fresh_id("run")
        if len(self._model_active()) + self._model_pending() >= self.SLOTS:
            with pytest.raises(BusyError):
                self.control.admit(rid)
        else:
            row = self.control.admit(rid)
            assert row.state is AdmissionState.ADMITTED
            self.model[rid] = ModelRun(state="ADMITTED")

    @rule(index=st.integers(min_value=0, max_value=10**6))
    def dispatch(self, index: int) -> None:
        rid = self._pick(
            index,
            [
                r
                for r, m in self.model.items()
                if m.state == "ADMITTED" and m.terminal_id is None and not m.suspended
            ],
        )
        if rid is None:
            return
        assert self.control.dispatch(rid).state is AdmissionState.DISPATCHED
        self.model[rid].state = "DISPATCHED"

    @rule(index=st.integers(min_value=0, max_value=10**6))
    def suspend(self, index: int) -> None:
        rid = self._pick(
            index,
            [
                r
                for r, m in self.model.items()
                if m.state in ("ADMITTED", "DISPATCHED")
                and m.terminal_id is None
                and not m.suspended
                and not m.acked
            ],
        )
        if rid is None:
            return
        child = self._fresh_id("child")
        row = self.control.suspend(rid, child)
        assert row.state is AdmissionState.ADMITTED
        self.model[rid].suspended = True
        self.model[child] = ModelRun(state="ADMITTED")

    @rule(index=st.integers(min_value=0, max_value=10**6))
    def cancel(self, index: int) -> None:
        rid = self._pick(index, list(self.model))
        if rid is None:
            return
        outcome = self.control.request_cancel(rid)
        if self.model[rid].terminal_id is None:
            assert outcome is True
            self.model[rid].state = "CANCEL_REQUESTED"
        else:
            assert outcome is False

    @rule(index=st.integers(min_value=0, max_value=10**6))
    def insert_terminal(self, index: int) -> None:
        rid = self._pick(index, [r for r, m in self.model.items() if m.terminal_id is None])
        if rid is None:
            return
        tid = f"t-{rid}"
        record = self.control.insert_terminal(rid, tid, TerminalState.COMPLETED, {"run": rid})
        assert record.terminal_id == tid
        run = self.model[rid]
        run.terminal_id = tid
        run.state = "TERMINAL"
        run.queued = False
        if rid in self.queue_order:
            self.queue_order.remove(rid)

    @rule(index=st.integers(min_value=0, max_value=10**6))
    def second_distinct_terminal_rejected(self, index: int) -> None:
        rid = self._pick(index, [r for r, m in self.model.items() if m.terminal_id is not None])
        if rid is None:
            return
        with pytest.raises(TerminalConflictError):
            self.control.insert_terminal(rid, f"other-{rid}", TerminalState.FAILED, None)

    @rule(index=st.integers(min_value=0, max_value=10**6))
    def ack(self, index: int) -> None:
        rid = self._pick(index, [r for r, m in self.model.items() if m.terminal_id is not None])
        if rid is None:
            return
        terminal_id = self.model[rid].terminal_id
        assert terminal_id is not None
        self.control.acknowledge_terminal(rid, terminal_id)
        self.model[rid].acked = True

    @rule(index=st.integers(min_value=0, max_value=10**6))
    def resume_request(self, index: int) -> None:
        rid = self._pick(
            index,
            [r for r, m in self.model.items() if m.suspended and m.terminal_id is None],
        )
        if rid is None:
            return
        self.control.resume_request(rid)
        if not self.model[rid].queued:
            self.model[rid].queued = True
            self.queue_order.append(rid)

    @rule(index=st.integers(min_value=0, max_value=10**6))
    def resume(self, index: int) -> None:
        rid = self._pick(
            index,
            [
                r
                for r, m in self.model.items()
                if m.queued and m.suspended and m.terminal_id is None
            ],
        )
        if rid is None:
            return
        run = self.model[rid]
        ahead = 0
        for other in self.queue_order:
            if other == rid:
                break
            m = self.model[other]
            if m.queued and m.suspended and m.terminal_id is None and not m.acked:
                ahead += 1
        free = self.SLOTS - len(self._model_active())
        if free <= ahead:
            with pytest.raises(BusyError):
                self.control.resume(rid)
        else:
            row = self.control.resume(rid)
            assert row.suspended is False
            run.suspended = False
            run.queued = False
            self.queue_order.remove(rid)

    @invariant()
    def slot_accounting_matches_model(self) -> None:
        active = self._model_active()
        assert len(active) <= self.SLOTS
        assert self.control.active_count() == len(active)
        assert self.control.occupied_run_ids() == frozenset(active)
        assert self.control.pending_resume_count() == self._model_pending()

    @invariant()
    def at_most_one_terminal_per_run(self) -> None:
        rows = self.db.conn.execute(
            "SELECT run_id, COUNT(*) AS n FROM terminals GROUP BY run_id"
        ).fetchall()
        stored = {str(row["run_id"]): int(row["n"]) for row in rows}
        assert all(n == 1 for n in stored.values())
        expected = {rid for rid, m in self.model.items() if m.terminal_id is not None}
        assert set(stored) == expected

    @invariant()
    def startup_union_matches_model(self) -> None:
        report = self.control.startup_reconstruct()
        assert report.occupied_run_ids == frozenset(self._model_active())
        assert report.available_slots == self.SLOTS - len(self._model_active())


def test_admission_state_machine() -> None:
    run_state_machine_as_test(
        AdmissionMachine,
        settings=settings(max_examples=25, stateful_step_count=40, deadline=None),
    )
