"""Gate G2 — delegation crash injection at every step of the state machine.

``server/tests/test_delegation_crash.py`` proves one point (a kill after the
terminal transaction commits). The gate clause asks for the whole set: a crash
**before enqueue, after admission, after dispatch, after the child terminal, and
before the parent response** must each leave *at most one child* and *exactly one
semantically distinct terminal*, and the survivor must resolve the row by the
fixed recovery precedence:

1. an existing child/delegation terminal wins untouched;
2. ``CANCEL_REQUESTED`` finishes as ``cancelled`` — never redispatched, and it
   beats confirmed owner loss;
3. an elapsed deadline finishes as ``timed_out``;
4. ``PREPARED`` re-reserves and ``ADMITTED``/``DISPATCHED`` recover **under the
   persisted child id** — this precedence *over* generic interruption synthesis
   is what stops a live child being declared interrupted;
5. only confirmed owner loss yields ``interrupted``.

Every scenario dies in a real subprocess at a real durability boundary (the
opstore ``CrashHook``, or an explicit ``_exit`` for the two boundaries the store
does not own), then reopens ``state.db`` from a survivor process.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from _g2b import FakeClock, FakeLiveness, delegation_service, open_bridge_store
from _g2b_crash import ARTIFACT, INVOCATION, PARENT_RUN, PROMPT, expected_ref
from hephaestus.agent_bridge.delegation import (
    DelegationPhase,
    DelegationService,
    Delivery,
    Rejected,
)
from opstore.types import CRASH_EXIT_CODE, TerminalState

from opstore import OpStore

_HELPER = Path(__file__).with_name("_g2b_crash.py")

#: ``stage -> (delivery, OPSTORE_CRASH_POINT or None)``.
CRASH_MATRIX: dict[str, tuple[str, str | None]] = {
    "before_enqueue": ("follow_up", None),
    "after_admission": ("follow_up", "admission.after_admit"),
    "after_admission_suspended": ("prompt", "admission.after_suspend"),
    "after_dispatch": ("follow_up", None),
    "after_child_terminal": ("follow_up", "admission.after_terminal_insert"),
    "before_parent_response": ("prompt", None),
}

#: The durable phase the survivor must find, per stage. ``after_admission`` is
#: still ``PREPARED``: the child's slot is reserved in the opstore transaction
#: *before* the WAL row is advanced, which is exactly why the recovery pass has
#: to re-reserve idempotently under the persisted child id instead of minting one.
EXPECTED_PHASE: dict[str, DelegationPhase] = {
    "before_enqueue": DelegationPhase.PREPARED,
    "after_admission": DelegationPhase.PREPARED,
    "after_admission_suspended": DelegationPhase.PREPARED,
    "after_dispatch": DelegationPhase.DISPATCHED,
    "after_child_terminal": DelegationPhase.TERMINAL,
    "before_parent_response": DelegationPhase.TERMINAL,
}


def crash(root: Path, stage: str) -> None:
    """Run the helper to its armed crash point; assert it really died there."""
    delivery, point = CRASH_MATRIX[stage]
    env = dict(os.environ)
    env.pop("OPSTORE_CRASH_POINT", None)
    env.pop("G2B_CRASH_POINT", None)
    if point is not None:
        # Armed by the helper only once the *parent* run is durably admitted.
        env["G2B_CRASH_POINT"] = point
    helper_stage = stage.removesuffix("_suspended")
    proc = subprocess.run(
        [sys.executable, str(_HELPER), str(root), helper_stage, delivery],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == CRASH_EXIT_CODE, f"{stage}: {proc.returncode}\n{proc.stderr}"
    assert "NO_CRASH" not in proc.stdout, f"{stage}: the injection never fired"


def survivor(root: Path, *, clock: FakeClock | None = None, liveness: object = None) -> OpStore:
    return open_bridge_store(root, clock=clock, liveness=liveness)  # type: ignore[arg-type]


def child_terminals(store: OpStore, child_run_id: str) -> int:
    """How many terminal rows exist for the child (the contract says ≤ 1)."""
    row = store.db.conn.execute(
        "SELECT COUNT(*) FROM terminals WHERE run_id = ?", (child_run_id,)
    ).fetchone()
    return int(row[0])


def delegation_rows(store: OpStore) -> int:
    row = store.db.conn.execute("SELECT COUNT(*) FROM tp_delegations").fetchone()
    return int(row[0])


# ---------------------------------------------------------------------------
# 1. at most one child, at most one terminal — at every crash boundary


@pytest.mark.parametrize("stage", list(CRASH_MATRIX))
def test_delegation_crash_leaves_at_most_one_child_and_one_terminal(
    tmp_path: Path, stage: str
) -> None:
    root = tmp_path / "heph"
    crash(root, stage)

    ref = expected_ref("dg-")
    child = expected_ref("cr-")
    store = survivor(root)
    try:
        service = DelegationService(store.admission, store.db)
        # Exactly one delegation row, carrying the id derived from the invocation.
        assert delegation_rows(store) == 1
        row = service.get(ref)
        assert row.child_run_id == child
        assert row.invocation_key == INVOCATION
        assert row.phase is EXPECTED_PHASE[stage]
        # At most one terminal, ever.
        assert child_terminals(store, child) <= 1

        # Replaying the *same* trusted invocation never enqueues a second child.
        replay = service.delegate(
            PARENT_RUN, row.part, PROMPT, delivery=Delivery(row.delivery), invocation=INVOCATION
        )
        assert not isinstance(replay, Rejected)
        assert replay.child_run_id == child
        assert delegation_rows(store) == 1
        assert child_terminals(store, child) <= 1
    finally:
        store.close()


# ---------------------------------------------------------------------------
# 2. recovery precedence


def test_delegation_crash_before_enqueue_recovers_the_persisted_child_id(
    tmp_path: Path,
) -> None:
    """(4) A ``PREPARED`` row re-reserves under the id it already persisted."""
    root = tmp_path / "heph"
    crash(root, "before_enqueue")
    child = expected_ref("cr-")
    store = survivor(root)
    try:
        service = DelegationService(store.admission, store.db)
        # Nothing was reserved before the crash…
        assert store.admission.occupied_run_ids() == frozenset({PARENT_RUN})
        recovered = service.recover(expected_ref("dg-"))
        # …and recovery reserves *that* child, not a freshly minted one.
        assert recovered.phase is DelegationPhase.ADMITTED
        assert recovered.child_run_id == child
        assert recovered.terminal_state is None
        assert child in store.admission.occupied_run_ids()
        assert child_terminals(store, child) == 0
    finally:
        store.close()


def test_delegation_crash_after_admission_recovers_live_before_synthesizing(
    tmp_path: Path,
) -> None:
    """(4) beats (5): an ``ADMITTED`` child whose owner is alive is not interrupted."""
    root = tmp_path / "heph"
    crash(root, "after_admission")
    ref, child = expected_ref("dg-"), expected_ref("cr-")

    # A survivor that still sees the owner as live must NOT synthesize a terminal.
    store = survivor(root, liveness=FakeLiveness(default=True))
    try:
        service = DelegationService(store.admission, store.db)
        recovered = service.recover(ref)
        assert recovered.phase is DelegationPhase.ADMITTED
        assert recovered.terminal_state is None
        assert child_terminals(store, child) == 0
    finally:
        store.close()

    # Only once owner loss is *confirmed* does recovery synthesize interrupted.
    store = survivor(root)
    try:
        service = DelegationService(store.admission, store.db)
        recovered = service.recover(ref)
        assert recovered.terminal_state is TerminalState.INTERRUPTED
        assert child_terminals(store, child) == 1
        # Idempotent: a second recovery pass adds nothing.
        assert service.recover(ref).terminal_state is TerminalState.INTERRUPTED
        assert child_terminals(store, child) == 1
    finally:
        store.close()


def test_delegation_crash_after_dispatch_synthesizes_one_interrupted_terminal(
    tmp_path: Path,
) -> None:
    """(5) A dispatched child whose process is gone is interrupted exactly once."""
    root = tmp_path / "heph"
    crash(root, "after_dispatch")
    ref, child = expected_ref("dg-"), expected_ref("cr-")
    store = survivor(root)
    try:
        service = DelegationService(store.admission, store.db)
        assert service.get(ref).phase is DelegationPhase.DISPATCHED
        recovered = service.recover(ref)
        assert recovered.terminal_state is TerminalState.INTERRUPTED
        assert child_terminals(store, child) == 1
        # A terminal forbids dispatch.
        assert service.recover(ref).phase is DelegationPhase.TERMINAL
    finally:
        store.close()


def test_delegation_crash_with_cancel_requested_recovers_only_to_cancelled(
    tmp_path: Path,
) -> None:
    """(2) beats (5): ``CANCEL_REQUESTED`` finishes as ``cancelled``, never redispatched."""
    root = tmp_path / "heph"
    crash(root, "after_admission")
    ref, child = expected_ref("dg-"), expected_ref("cr-")
    store = survivor(root)
    try:
        service = DelegationService(store.admission, store.db)
        # The coordinator asked for cancellation before the recovery pass ran.
        assert store.admission.request_cancel(child) is True
        recovered = service.recover(ref)
        assert recovered.terminal_state is TerminalState.CANCELLED
        assert child_terminals(store, child) == 1
        assert recovered.phase is DelegationPhase.TERMINAL
    finally:
        store.close()


def test_delegation_crash_after_child_terminal_beats_cancel_and_deadline(
    tmp_path: Path,
) -> None:
    """(1) The durable child terminal wins over both cancellation and expiry."""
    root = tmp_path / "heph"
    crash(root, "after_child_terminal")
    ref, child = expected_ref("dg-"), expected_ref("cr-")

    # A clock far past the persisted deadline: expiry must still not win.
    clock = FakeClock(start=2_000_000_000.0)
    store = survivor(root, clock=clock)
    try:
        service = delegation_service(store, clock)
        row = service.get(ref)
        assert row.terminal_state is TerminalState.COMPLETED
        assert row.result_artifact_ref == ARTIFACT
        assert row.deadline_at is not None and clock.now() > row.deadline_at

        terminal = store.admission.get_terminal(child)
        assert terminal is not None
        original_id = terminal.terminal_id

        assert service.cancel(ref).terminal_state is TerminalState.COMPLETED
        assert service.check_deadline(ref).terminal_state is TerminalState.COMPLETED
        assert service.recover(ref).terminal_state is TerminalState.COMPLETED

        # One terminal, unchanged identity, after all three racing resolvers.
        assert child_terminals(store, child) == 1
        after = store.admission.get_terminal(child)
        assert after is not None and after.terminal_id == original_id
    finally:
        store.close()


def test_delegation_crash_before_parent_response_resumes_the_parent_once(
    tmp_path: Path,
) -> None:
    """A crash between the child terminal and the parent's answer loses nothing."""
    root = tmp_path / "heph"
    crash(root, "before_parent_response")
    ref, child = expected_ref("dg-"), expected_ref("cr-")
    store = survivor(root)
    try:
        service = DelegationService(store.admission, store.db)
        # The parent is still durably suspended; the child terminal is durable.
        assert store.admission.get(PARENT_RUN).suspended is True
        assert service.get(ref).terminal_state is TerminalState.COMPLETED
        assert child_terminals(store, child) == 1

        resumed = service.resume_parent(ref)
        assert resumed.status() == "completed"
        assert resumed.result_artifact_ref == ARTIFACT
        assert store.admission.get(PARENT_RUN).suspended is False
        # The synchronous answer is replayable and creates no second terminal.
        assert service.resume_parent(ref).status() == "completed"
        assert child_terminals(store, child) == 1
    finally:
        store.close()
