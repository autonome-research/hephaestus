"""Delegation state-machine matrix: rejections, prompt/follow_up, cancel, deadline,
recovery precedence, idempotency, NFC/NFD, saturation."""

from __future__ import annotations

import unicodedata

import pytest
from conftest import FakeClock, FakeLiveness, owner
from hephaestus.agent_bridge.delegation import (
    DEADLINE_DEFAULT_S,
    PROMPT_MAX_UTF8_BYTES,
    DelegationGate,
    DelegationPhase,
    DelegationRow,
    DelegationService,
    DelegationValidationError,
    Delivery,
    Rejected,
    RejectionReason,
)
from opstore.types import TerminalState

from opstore import OpStore


class RejectGate:
    """A gate that always returns a fixed reason."""

    def __init__(self, reason: RejectionReason) -> None:
        self._reason = reason

    def classify(self, parent_run_id: str, part: str, delivery: Delivery) -> RejectionReason | None:
        return self._reason


def _svc(store: OpStore, clock: FakeClock, gate: DelegationGate | None = None) -> DelegationService:
    return DelegationService(store.admission, store.db, gate=gate, clock=clock)


def _ref(out: DelegationRow | Rejected) -> str:
    assert isinstance(out, DelegationRow)
    return out.delegation_ref


# -- follow_up -----------------------------------------------------------------


def test_follow_up_queues_and_reserves_slot(store: OpStore, clock: FakeClock) -> None:
    svc = _svc(store, clock)
    store.admission.admit("orch")  # parent keeps its own slot
    out = svc.delegate("orch", "partA", "make it", delivery=Delivery.FOLLOW_UP, invocation="inv-1")
    assert not out.rejected
    assert out.status() == "queued"
    row = svc.get(_ref(out))
    assert row.phase is DelegationPhase.ADMITTED
    assert row.deadline_at == clock.now() + DEADLINE_DEFAULT_S
    # Parent slot + child slot both occupied.
    assert store.admission.active_count() == 2


def test_follow_up_no_run_slot_rejection_has_no_child(store: OpStore, clock: FakeClock) -> None:
    svc = _svc(store, clock)
    for i in range(16):
        store.admission.admit(f"run-{i}")
    out = svc.delegate("run-0", "partA", "x", delivery=Delivery.FOLLOW_UP, invocation="inv-x")
    assert isinstance(out, Rejected)
    assert out.reason is RejectionReason.NO_RUN_SLOT
    # No delegation row persisted for a rejection.
    assert svc.get_by_invocation("inv-x") is None


# -- prompt (synchronous) ------------------------------------------------------


def test_prompt_suspends_parent_and_reserves_child(store: OpStore, clock: FakeClock) -> None:
    svc = _svc(store, clock)
    store.admission.admit("orch")
    assert store.admission.active_count() == 1
    out = svc.delegate("orch", "partA", "build", delivery=Delivery.PROMPT, invocation="inv-2")
    assert not out.rejected
    parent = store.admission.get("orch")
    assert parent.suspended is True
    # Net occupancy unchanged: child occupies, suspended parent does not.
    assert store.admission.active_count() == 1
    row = svc.get(_ref(out))
    assert row.status() == "running"


def test_prompt_terminal_then_resume_parent(store: OpStore, clock: FakeClock) -> None:
    svc = _svc(store, clock)
    store.admission.admit("orch")
    out = svc.delegate("orch", "partA", "build", delivery=Delivery.PROMPT, invocation="inv-3")
    ref = _ref(out)
    svc.dispatch(ref)
    svc.ingest_terminal(ref, TerminalState.COMPLETED, result_artifact_ref="art-1")
    resumed = svc.resume_parent(ref)
    assert resumed.status() == "completed"
    assert resumed.result_artifact_ref == "art-1"
    parent = store.admission.get("orch")
    assert parent.suspended is False  # reacquired its slot
    assert store.admission.active_count() == 1


# -- rejection taxonomy --------------------------------------------------------


@pytest.mark.parametrize(
    "reason",
    [
        RejectionReason.PART_BUSY,
        RejectionReason.SESSION_BUSY,
        RejectionReason.INVALID_PART,
        RejectionReason.SCOPE_DENIED,
        RejectionReason.QUEUE_FULL,
    ],
)
def test_gate_rejections_have_no_child(
    store: OpStore, clock: FakeClock, reason: RejectionReason
) -> None:
    svc = _svc(store, clock, gate=RejectGate(reason))
    store.admission.admit("orch")
    out = svc.delegate("orch", "partA", "hi", invocation="inv-gate")
    assert isinstance(out, Rejected)
    assert out.reason is reason
    assert svc.get_by_invocation("inv-gate") is None


def test_prompt_too_large_rejected_not_truncated(store: OpStore, clock: FakeClock) -> None:
    svc = _svc(store, clock)
    store.admission.admit("orch")
    at_limit = "a" * PROMPT_MAX_UTF8_BYTES
    over = "a" * (PROMPT_MAX_UTF8_BYTES + 1)
    ok = svc.delegate("orch", "partA", at_limit, invocation="inv-ok")
    assert not ok.rejected
    out = svc.delegate("orch", "partA", over, invocation="inv-over")
    assert isinstance(out, Rejected)
    assert out.reason is RejectionReason.PROMPT_TOO_LARGE


def test_deadline_out_of_range_is_validation_error(store: OpStore, clock: FakeClock) -> None:
    svc = _svc(store, clock)
    store.admission.admit("orch")
    with pytest.raises(DelegationValidationError):
        svc.delegate("orch", "partA", "x", deadline_seconds=0, invocation="inv-d0")
    with pytest.raises(DelegationValidationError):
        svc.delegate("orch", "partA", "x", deadline_seconds=1201, invocation="inv-d2")


# -- idempotency / NFC-NFD -----------------------------------------------------


def test_idempotent_replay_same_invocation(store: OpStore, clock: FakeClock) -> None:
    svc = _svc(store, clock)
    store.admission.admit("orch")
    a = svc.delegate("orch", "partA", "build", delivery=Delivery.FOLLOW_UP, invocation="inv-r")
    b = svc.delegate("orch", "partA", "build", delivery=Delivery.FOLLOW_UP, invocation="inv-r")
    assert _ref(a) == _ref(b)
    # Only one child slot reserved despite two calls.
    assert store.admission.active_count() == 2  # parent + one child


def test_same_key_different_payload_fails(store: OpStore, clock: FakeClock) -> None:
    svc = _svc(store, clock)
    store.admission.admit("orch")
    svc.delegate("orch", "partA", "build", delivery=Delivery.FOLLOW_UP, invocation="inv-k")
    with pytest.raises(DelegationValidationError) as exc:
        svc.delegate("orch", "partA", "DIFFERENT", delivery=Delivery.FOLLOW_UP, invocation="inv-k")
    assert exc.value.code == "key_payload_mismatch"


def test_nfc_nfd_are_distinct_payloads(store: OpStore, clock: FakeClock) -> None:
    svc = _svc(store, clock)
    store.admission.admit("orch")
    nfc = unicodedata.normalize("NFC", "café")
    nfd = unicodedata.normalize("NFD", "café")
    assert nfc != nfd and nfc.encode() != nfd.encode()
    svc.delegate("orch", "partA", nfc, delivery=Delivery.FOLLOW_UP, invocation="inv-n")
    # Same invocation key, NFD bytes = a different payload -> mismatch.
    with pytest.raises(DelegationValidationError) as exc:
        svc.delegate("orch", "partA", nfd, delivery=Delivery.FOLLOW_UP, invocation="inv-n")
    assert exc.value.code == "key_payload_mismatch"


# -- cancel / deadline / terminal-wins -----------------------------------------


def test_cancel_queued_follow_up_by_ref(store: OpStore, clock: FakeClock) -> None:
    svc = _svc(store, clock)
    store.admission.admit("orch")
    out = svc.delegate("orch", "partA", "x", delivery=Delivery.FOLLOW_UP, invocation="inv-c")
    ref = _ref(out)
    row = svc.cancel(ref)
    assert row.status() == "cancelled"
    assert row.terminal_state is TerminalState.CANCELLED
    # Idempotent: cancel again returns the unchanged terminal.
    again = svc.cancel(ref)
    assert again.terminal_state is TerminalState.CANCELLED


def test_child_terminal_wins_over_cancel(store: OpStore, clock: FakeClock) -> None:
    svc = _svc(store, clock)
    store.admission.admit("orch")
    out = svc.delegate("orch", "partA", "x", delivery=Delivery.FOLLOW_UP, invocation="inv-w")
    ref = _ref(out)
    svc.ingest_terminal(ref, TerminalState.COMPLETED, result_artifact_ref="done")
    # A completed terminal already exists; cancel must return it unchanged.
    row = svc.cancel(ref)
    assert row.terminal_state is TerminalState.COMPLETED
    assert row.result_artifact_ref == "done"


def test_deadline_only_times_out(store: OpStore, clock: FakeClock) -> None:
    svc = _svc(store, clock)
    store.admission.admit("orch")
    out = svc.delegate(
        "orch", "partA", "x", delivery=Delivery.FOLLOW_UP, deadline_seconds=10, invocation="inv-t"
    )
    ref = _ref(out)
    # Before the deadline: unchanged.
    assert svc.check_deadline(ref).phase is DelegationPhase.ADMITTED
    clock.advance(11)
    row = svc.check_deadline(ref)
    assert row.terminal_state is TerminalState.TIMED_OUT


# -- recovery precedence -------------------------------------------------------


def test_cancel_requested_recovers_only_to_cancelled(store: OpStore, clock: FakeClock) -> None:
    svc = _svc(store, clock)
    store.admission.admit("orch")
    out = svc.delegate("orch", "partA", "x", delivery=Delivery.FOLLOW_UP, invocation="inv-cr")
    ref = _ref(out)
    row = svc.get(ref)
    assert store.admission.request_cancel(row.child_run_id) is True
    recovered = svc.recover(ref)
    assert recovered.terminal_state is TerminalState.CANCELLED


def test_admitted_recovery_precedence_over_interruption(
    store: OpStore, clock: FakeClock, liveness: FakeLiveness
) -> None:
    svc = _svc(store, clock)
    store.admission.admit("orch")
    out = svc.delegate(
        "orch",
        "partA",
        "x",
        delivery=Delivery.FOLLOW_UP,
        invocation="inv-adm",
        child_owner=owner(4242),
    )
    ref = _ref(out)
    # Owner alive: an ADMITTED child is recovered live (no synthesized terminal).
    recovered = svc.recover(ref)
    assert recovered.phase is DelegationPhase.ADMITTED
    assert recovered.terminal_state is None
    # Owner lost: now recovery synthesizes interrupted.
    liveness.kill(owner(4242))
    recovered2 = svc.recover(ref)
    assert recovered2.terminal_state is TerminalState.INTERRUPTED


def test_prepared_recovery_reserves_child(store: OpStore, clock: FakeClock) -> None:
    # Simulate a crash after PREPARED insert but before reservation by writing a
    # PREPARED row directly, then recovering it.
    svc = _svc(store, clock)
    store.admission.admit("orch")
    store.db.conn.execute(
        "INSERT INTO tp_delegations(delegation_ref, invocation_key, parent_run_id, part, "
        "delivery, prompt_hash, deadline_seconds, child_run_id, phase, created_at) "
        "VALUES('dg-x','inv-p','orch','partA','follow_up','h',600,'cr-x','PREPARED',?)",
        (clock.now(),),
    )
    recovered = svc.recover("dg-x")
    assert recovered.phase is DelegationPhase.ADMITTED
    assert store.admission.get("cr-x").state.value == "ADMITTED"


# -- dispatch ------------------------------------------------------------------


def test_dispatch_then_terminal_forbids_redispatch(store: OpStore, clock: FakeClock) -> None:
    from opstore.errors import TerminalConflictError

    svc = _svc(store, clock)
    store.admission.admit("orch")
    out = svc.delegate("orch", "partA", "x", delivery=Delivery.FOLLOW_UP, invocation="inv-dz")
    ref = _ref(out)
    assert svc.dispatch(ref).phase is DelegationPhase.DISPATCHED
    svc.ingest_terminal(ref, TerminalState.COMPLETED)
    with pytest.raises(TerminalConflictError):
        svc.dispatch(ref)


# -- saturation ----------------------------------------------------------------


def test_sixteen_parents_each_delegate_no_starvation(store: OpStore, clock: FakeClock) -> None:
    svc = _svc(store, clock)
    parents = [f"orch-{i}" for i in range(16)]
    for p in parents:
        store.admission.admit(p)
    assert store.admission.active_count() == 16
    refs: list[str] = []
    for i, p in enumerate(parents):
        out = svc.delegate(p, f"part-{i}", "build", delivery=Delivery.PROMPT, invocation=f"inv-{i}")
        assert not out.rejected, f"parent {p} delegation was rejected"
        refs.append(_ref(out))
    # All 16 children admitted; net occupancy still 16 (parents suspended).
    assert store.admission.active_count() == 16
    # Each child completes, each parent resumes — no BusyError / starvation.
    for ref in refs:
        svc.dispatch(ref)
        svc.ingest_terminal(ref, TerminalState.COMPLETED, result_artifact_ref="ok")
        resumed = svc.resume_parent(ref)
        assert resumed.status() == "completed"
    # All parents resumed and occupy their slots again; all children acked.
    assert store.admission.active_count() == 16
    for p in parents:
        assert store.admission.get(p).suspended is False
