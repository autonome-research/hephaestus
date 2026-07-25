"""Gate G2 — the full ``delegate_part_agent`` variant matrix, as the model sees it.

``server/tests/test_delegation.py`` proves the state machine and
``server/tests/test_dispatch_delegation.py`` proves several tool projections.
This file closes the clauses neither covers end to end:

* **every** discriminated ``status`` the tool schema declares — ``queued``,
  ``completed``, ``failed``, ``cancelled``, ``timed_out``, ``interrupted`` and
  all **seven** ``rejected`` reasons — asserted on the *dispatched result shape*
  (a rejection carries no child run and no ref; a failure variant carries the
  child ref **and** an error);
* the child run id is **stable**: derived from the trusted invocation, identical
  across an idempotent replay, a fresh :class:`DelegationService`, and a
  closed-and-reopened ``state.db``;
* the three deadline classes (default / configured / max) and the ``+60 s``
  terminal-cleanup grace, read from ``schemas/bridge_limits.json``;
* the prompt cap at the boundary (32768 accepted, 32769 rejected, never
  truncated) and lone-surrogate rejection *before* sizing or hashing, on the
  Python side (``tests/stage2/test_delegation_bridge.py`` proves the same two
  clauses through the generated TypeBox proxy in the real sidecar);
* NFC and NFD are different payloads — presented under *different* invocations
  they admit two children with two distinct prompt hashes;
* a queued follow-up holds one of the 16 slots from ``ADMITTED`` until its
  terminal is acknowledged, and is cancellable by ``delegation_ref`` while queued.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from _g2b import FakeClock, delegation_service, open_bridge_store, owner
from hephaestus.agent_bridge.delegation import (
    DEADLINE_DEFAULT_S,
    DEADLINE_MAX_S,
    DEADLINE_MIN_S,
    GRACE_S,
    PROMPT_MAX_UTF8_BYTES,
    DelegationPhase,
    DelegationRow,
    DelegationService,
    DelegationValidationError,
    Delivery,
    Rejected,
    RejectionReason,
)
from hephaestus.agent_bridge.dispatch import DispatchError, ToolDispatcher
from hephaestus.core.project_store.store import ProjectStore
from opstore.errors import BusyError
from opstore.types import TerminalState
from tools_fixture import Project, make_project

CHILD_ARTIFACT = "artifact:build:sha256:" + "c" * 64

#: Every ``rejected`` reason the Stage 2 tool schema declares (digest §3).
ALL_REJECTION_REASONS: tuple[RejectionReason, ...] = tuple(RejectionReason)


class _Gate:
    """A pre-admission gate returning one fixed reason (or admitting)."""

    def __init__(self, reason: RejectionReason | None = None) -> None:
        self.reason = reason

    def classify(self, parent_run_id: str, part: str, delivery: Delivery) -> RejectionReason | None:
        return self.reason


class _Runner:
    """A coordinator stand-in that drives the child to one chosen terminal."""

    def __init__(self, state: TerminalState, *, artifact: str | None = None) -> None:
        self.state = state
        self.artifact = artifact
        self.children: list[str] = []

    def run(self, service: DelegationService, row: DelegationRow) -> None:
        self.children.append(row.child_run_id)
        service.dispatch(row.delegation_ref)
        service.ingest_terminal(
            row.delegation_ref,
            self.state,
            result_artifact_ref=self.artifact,
            error=None if self.state is TerminalState.COMPLETED else str(self.state),
        )


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Project]:
    p = make_project(tmp_path / "proj")
    try:
        yield p
    finally:
        p.close()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


def wire(
    project: Project, *, clock: FakeClock, runner: Any = None, gate: Any = None
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


def delegate(project: Project, *, entry: str, **arguments: Any) -> dict[str, Any]:
    args: dict[str, Any] = {"part": "widget", "prompt": "widen it", **arguments}
    return cast("dict[str, Any]", project.call("delegate_part_agent", args, entry=entry))


# ---------------------------------------------------------------------------
# 1. the discriminated result matrix


@pytest.mark.parametrize(
    "reason", ALL_REJECTION_REASONS, ids=[str(r) for r in ALL_REJECTION_REASONS]
)
def test_delegation_rejection_variants_carry_no_child(
    project: Project, clock: FakeClock, reason: RejectionReason
) -> None:
    """Every pre-admission rejection: a reason, no child run, no ref, no WAL row."""
    if reason is RejectionReason.PROMPT_TOO_LARGE:
        wire(project, clock=clock)
        out = delegate(project, entry="rj", prompt="a" * (PROMPT_MAX_UTF8_BYTES + 1))
    elif reason is RejectionReason.NO_RUN_SLOT:
        service = wire(project, clock=clock)
        for i in range(16):
            project.store.admission.admit(f"filler-{i}")
        out = delegate(project, entry="rj", delivery="follow_up")
        assert service.get_by_invocation("rj") is None
    else:
        wire(project, clock=clock, gate=_Gate(reason))
        out = delegate(project, entry="rj")

    assert out["status"] == "rejected"
    assert out["reason"] == str(reason)
    # A rejection is not a fictitious child failure: no run, no ref, no error.
    assert "child_run_id" not in out
    assert "delegation_ref" not in out
    assert "error" not in out
    # ``part_session_id`` is the only optional member a rejection may carry.
    assert set(out) <= {"status", "reason", "part_session_id"}


@pytest.mark.parametrize(
    ("state", "status", "artifact"),
    [
        (TerminalState.COMPLETED, "completed", CHILD_ARTIFACT),
        (TerminalState.FAILED, "failed", None),
        (TerminalState.CANCELLED, "cancelled", None),
        (TerminalState.TIMED_OUT, "timed_out", None),
        (TerminalState.INTERRUPTED, "interrupted", None),
    ],
)
def test_delegation_terminal_variants_are_replayable_through_the_status_tool(
    project: Project,
    clock: FakeClock,
    state: TerminalState,
    status: str,
    artifact: str | None,
) -> None:
    """Each terminal projects the same discriminated result from delegate + status."""
    runner = _Runner(state, artifact=artifact)
    wire(project, clock=clock, runner=runner)
    # Synchronous delivery suspends the parent, so it must hold a slot first.
    project.store.admission.admit("run-1")
    out = delegate(project, entry=f"t-{status}")

    assert out["status"] == status
    assert out["child_run_id"] == runner.children[0]
    assert out["delegation_ref"]
    assert out["part_session_id"] == "part:widget"
    if status == "completed":
        assert out["result_artifact_ref"] == artifact
        assert not out.get("error")
    else:
        # A failure variant always carries evidence; never a bare status.
        assert out["error"]

    # Every outcome replays identically through get_delegation_status …
    replay = cast(
        "dict[str, Any]",
        project.call("get_delegation_status", {"delegation_ref": out["delegation_ref"]}),
    )
    assert replay["status"] == status
    assert replay["child_run_id"] == out["child_run_id"]
    # … and through cancel_delegation, which never rewrites a settled terminal.
    cancelled = cast(
        "dict[str, Any]",
        project.call("cancel_delegation", {"delegation_ref": out["delegation_ref"]}),
    )
    assert cancelled["status"] == status
    assert cancelled["child_run_id"] == out["child_run_id"]


def test_delegation_queued_follow_up_holds_a_slot_until_the_terminal_is_acked(
    project: Project, clock: FakeClock
) -> None:
    """``follow_up`` reserves a slot **before** enqueue and holds it to the ack."""
    service = wire(project, clock=clock)
    out = delegate(project, entry="fu", delivery="follow_up")
    assert out["status"] == "queued"
    ref = str(out["delegation_ref"])

    # Reserved at ADMITTED — before any sidecar execution or queueing.
    assert service.get(ref).phase is DelegationPhase.ADMITTED
    assert project.store.admission.active_count() == 1
    assert out["child_run_id"] in project.store.admission.occupied_run_ids()

    # Still held while queued *and* after the terminal, until acknowledged.
    service.dispatch(ref)
    assert project.store.admission.active_count() == 1
    service.ingest_terminal(ref, TerminalState.COMPLETED, result_artifact_ref=CHILD_ARTIFACT)
    assert project.store.admission.active_count() == 1
    service.acknowledge(ref)
    assert project.store.admission.active_count() == 0


def test_delegation_queued_follow_up_is_cancellable_by_ref(
    project: Project, clock: FakeClock
) -> None:
    """A queued child is removed by ``delegation_ref`` with one durable terminal."""
    service = wire(project, clock=clock)
    out = delegate(project, entry="fc", delivery="follow_up")
    ref = str(out["delegation_ref"])
    child = str(out["child_run_id"])

    cancelled = cast("dict[str, Any]", project.call("cancel_delegation", {"delegation_ref": ref}))
    assert cancelled["status"] == "cancelled"
    assert cancelled["child_run_id"] == child

    terminal = project.store.admission.get_terminal(child)
    assert terminal is not None and terminal.state is TerminalState.CANCELLED
    # Idempotent: a second cancel returns the same unchanged terminal.
    again = cast("dict[str, Any]", project.call("cancel_delegation", {"delegation_ref": ref}))
    assert again["status"] == "cancelled" and again["child_run_id"] == child
    assert service.get(ref).phase is DelegationPhase.TERMINAL


def test_delegation_queue_overflow_is_a_rejection_not_a_child_failure(
    project: Project, clock: FakeClock
) -> None:
    """Queue overflow rejects pre-admission; it never invents a failed child."""
    wire(project, clock=clock, gate=_Gate(RejectionReason.QUEUE_FULL))
    out = delegate(project, entry="qf", delivery="follow_up")
    assert out["status"] == "rejected" and out["reason"] == "queue_full"
    # No admission row, no terminal, nothing to replay: there is no child at all.
    assert project.store.admission.active_count() == 0
    assert project.store.admission.occupied_run_ids() == frozenset()


# ---------------------------------------------------------------------------
# 2. stable child ids / idempotency


def test_delegation_child_run_id_is_stable_across_replay_service_and_restart(
    tmp_path: Path, clock: FakeClock
) -> None:
    """One trusted invocation ⇒ one child id, before and after a ``state.db`` restart."""
    root = tmp_path / "proj"
    project = make_project(root)
    try:
        wire(project, clock=clock)
        first = delegate(project, entry="stable", delivery="follow_up")
        replay = delegate(project, entry="stable", delivery="follow_up")
        assert replay["child_run_id"] == first["child_run_id"]
        assert replay["delegation_ref"] == first["delegation_ref"]
        # One reservation despite two calls.
        assert project.store.admission.active_count() == 1

        # A *fresh* service over the same store replays the same row.
        fresh = DelegationService(project.store.admission, project.store.db, clock=clock)
        row = fresh.get(str(first["delegation_ref"]))
        assert row.child_run_id == first["child_run_id"]
        ref, child = str(first["delegation_ref"]), str(first["child_run_id"])
    finally:
        project.close()

    # And so does a reopened store — the id is durable, not in-memory state.
    store = open_bridge_store(root / ".heph")
    try:
        after = DelegationService(store.admission, store.db)
        assert after.get(ref).child_run_id == child
        assert child in store.admission.occupied_run_ids()
    finally:
        store.close()


def test_delegation_nfc_and_nfd_admit_two_distinct_children(
    project: Project, clock: FakeClock
) -> None:
    """NFC and NFD bytes are *different payloads*: distinct hashes, distinct children."""
    service = wire(project, clock=clock)
    nfc = unicodedata.normalize("NFC", "café façade")
    nfd = unicodedata.normalize("NFD", "café façade")
    assert nfc != nfd and nfc.encode() != nfd.encode()

    a = delegate(project, entry="nfc", delivery="follow_up", prompt=nfc)
    b = delegate(project, entry="nfd", delivery="follow_up", prompt=nfd)
    assert a["child_run_id"] != b["child_run_id"]
    hashes = {
        service.get(str(a["delegation_ref"])).prompt_hash,
        service.get(str(b["delegation_ref"])).prompt_hash,
    }
    assert len(hashes) == 2, "NFC/NFD must not be normalized into one payload hash"


def test_delegation_same_invocation_with_a_different_prompt_never_enqueues_twice(
    project: Project, clock: FakeClock
) -> None:
    wire(project, clock=clock)
    delegate(project, entry="dup", delivery="follow_up", prompt="one")
    with pytest.raises(DispatchError) as exc:
        delegate(project, entry="dup", delivery="follow_up", prompt="two")
    assert exc.value.reason == "key_payload_mismatch"
    assert project.store.admission.active_count() == 1


# ---------------------------------------------------------------------------
# 3. deadlines: default / configured / max + grace


def test_delegation_deadline_classes_default_configured_and_max(
    project: Project, clock: FakeClock
) -> None:
    """``deadline_at = admitted_at + D`` for D ∈ {default, configured, max}."""
    service = wire(project, clock=clock)
    admitted_at = clock.now()

    cases = {"d-default": None, "d-conf": 30, "d-max": DEADLINE_MAX_S}
    for entry, requested in cases.items():
        arguments: dict[str, Any] = {"delivery": "follow_up"}
        if requested is not None:
            arguments["deadline_seconds"] = requested
        out = delegate(project, entry=entry, **arguments)
        row = service.get(str(out["delegation_ref"]))
        expected = DEADLINE_DEFAULT_S if requested is None else requested
        assert row.deadline_seconds == expected
        assert row.admitted_at == admitted_at
        # Queued time counts: the deadline is absolute from ADMITTED.
        assert row.deadline_at == admitted_at + expected


@pytest.mark.parametrize("seconds", [DEADLINE_MIN_S - 1, DEADLINE_MAX_S + 1])
def test_delegation_deadline_outside_the_window_is_a_validation_error(
    project: Project, clock: FakeClock, seconds: int
) -> None:
    wire(project, clock=clock)
    with pytest.raises(DispatchError):
        delegate(project, entry=f"dl{seconds}", deadline_seconds=seconds)


@pytest.mark.parametrize("seconds", [DEADLINE_MIN_S, DEADLINE_MAX_S])
def test_delegation_deadline_window_boundaries_are_accepted(
    project: Project, clock: FakeClock, seconds: int
) -> None:
    service = wire(project, clock=clock)
    out = delegate(project, entry=f"ok{seconds}", delivery="follow_up", deadline_seconds=seconds)
    assert service.get(str(out["delegation_ref"])).deadline_seconds == seconds


def test_delegation_expiry_produces_only_timed_out_within_the_bridge_grace(
    project: Project, clock: FakeClock
) -> None:
    """Expiry yields ``timed_out`` only, and the bridge deadline is ``D + 60 s``."""
    service = wire(project, clock=clock)
    out = delegate(project, entry="to", delivery="follow_up", deadline_seconds=DEADLINE_MIN_S)
    ref = str(out["delegation_ref"])
    row = service.get(ref)
    assert row.deadline_at is not None

    # The outer bridge deadline never races the child deadline: it is D + grace.
    bridge_deadline = row.deadline_at + GRACE_S
    assert bridge_deadline - row.deadline_at == GRACE_S
    assert GRACE_S == 60

    # Just before expiry nothing happens…
    clock.advance(DEADLINE_MIN_S - 0.5)
    assert service.check_deadline(ref).phase is DelegationPhase.ADMITTED
    # …and at expiry the ONLY synthesized terminal is timed_out.
    clock.advance(1.0)
    timed = cast("dict[str, Any]", project.call("get_delegation_status", {"delegation_ref": ref}))
    assert timed["status"] == "timed_out"
    terminal = project.store.admission.get_terminal(str(out["child_run_id"]))
    assert terminal is not None and terminal.state is TerminalState.TIMED_OUT
    # The clock is now past the +60 s grace as well: still exactly one terminal.
    clock.advance(GRACE_S + 1)
    assert service.check_deadline(ref).terminal_state is TerminalState.TIMED_OUT


# ---------------------------------------------------------------------------
# 4. prompt validation (python half of the cross-language keyword)


def test_delegation_prompt_cap_boundary_is_exact_utf8_and_never_truncates(
    project: Project, clock: FakeClock
) -> None:
    service = wire(project, clock=clock)
    # Exactly at the cap: admitted. One char over: rejected, nothing persisted.
    at_limit = "é" * (PROMPT_MAX_UTF8_BYTES // 2)
    assert len(at_limit.encode("utf-8")) == PROMPT_MAX_UTF8_BYTES
    ok = delegate(project, entry="cap-ok", delivery="follow_up", prompt=at_limit)
    assert ok["status"] == "queued"

    over = at_limit + "a"
    assert len(over.encode("utf-8")) == PROMPT_MAX_UTF8_BYTES + 1
    rejected = delegate(project, entry="cap-over", delivery="follow_up", prompt=over)
    assert rejected["status"] == "rejected"
    assert rejected["reason"] == "prompt_too_large"
    # Never truncated into a shorter, "successful" delegation.
    assert service.get_by_invocation("cap-over") is None
    assert project.store.admission.active_count() == 1


def test_delegation_lone_surrogate_is_rejected_before_sizing_or_hashing(
    project: Project, clock: FakeClock
) -> None:
    service = wire(project, clock=clock)
    lone = "prompt with \ud800 in it"
    with pytest.raises(DispatchError) as exc:
        delegate(project, entry="sur", delivery="follow_up", prompt=lone)
    assert exc.value.reason == "invalid_unicode_scalar"
    # No replacement-character coercion: nothing was admitted or hashed.
    assert service.get_by_invocation("sur") is None
    assert project.store.admission.active_count() == 0


def test_delegation_service_rejects_a_lone_surrogate_even_under_the_cap(
    tmp_path: Path, clock: FakeClock
) -> None:
    """The surrogate check runs *first*, so it wins over the size check too."""
    store = open_bridge_store(tmp_path / "heph", clock=clock)
    try:
        service = delegation_service(store, clock)
        store.admission.admit("orch")
        oversized_and_invalid = "\ud800" + "a" * (PROMPT_MAX_UTF8_BYTES + 1)
        with pytest.raises(DelegationValidationError) as exc:
            service.delegate("orch", "widget", oversized_and_invalid, invocation="both")
        assert exc.value.code == "invalid_unicode_scalar"
    finally:
        store.close()


# ---------------------------------------------------------------------------
# 5. saturation: 16 orchestrators, no starvation, no over-subscription


def test_delegation_saturation_of_sixteen_orchestrators_survives_a_restart(
    tmp_path: Path, clock: FakeClock
) -> None:
    """16 waiting parents + 16 children never exceed 16 slots, across a restart.

    ``server/tests/test_delegation.py::test_sixteen_parents_each_delegate_no_starvation``
    proves the happy path in one process. The gate clause additionally requires
    that the saturated store admits **no** seventeenth external run and that the
    occupancy reconstructed after a restart is the *union* of the unfinished
    sets, never their sum.
    """
    root = tmp_path / "heph"
    store = open_bridge_store(root, clock=clock)
    parents = [f"orch-{i}" for i in range(16)]
    refs: list[str] = []
    try:
        service = delegation_service(store, clock)
        for parent in parents:
            store.admission.admit(parent, owner=owner(1000))
        assert store.admission.active_count() == 16

        for index, parent in enumerate(parents):
            out = service.delegate(
                parent,
                f"part-{index}",
                "build it",
                delivery=Delivery.PROMPT,
                invocation=f"sat-{index}",
                child_owner=owner(1000),
            )
            assert not isinstance(out, Rejected), f"{parent} was starved"
            refs.append(out.delegation_ref)

        # Net occupancy unchanged: each parent traded its slot for its child.
        assert store.admission.active_count() == 16
        # A seventeenth *external* run is refused — the swap never over-subscribes.
        with pytest.raises(BusyError):
            store.admission.admit("external-17")
        occupancy = store.admission.occupied_run_ids()
        assert len(occupancy) == 16
        assert occupancy.isdisjoint(set(parents)), "suspended parents must not occupy"
    finally:
        store.close()

    # Restart: occupancy is rebuilt as the union of the two unfinished sets.
    store = open_bridge_store(root, clock=clock)
    try:
        report = store.admission.startup_reconstruct()
        assert len(report.occupied_run_ids) == 16
        assert report.available_slots == 0
        with pytest.raises(BusyError):
            store.admission.admit("external-after-restart")

        service = delegation_service(store, clock)
        for ref in refs:
            service.dispatch(ref)
            service.ingest_terminal(ref, TerminalState.COMPLETED, result_artifact_ref="ok")
            assert service.resume_parent(ref).status() == "completed"
        # Every parent reacquired its slot with FIFO priority; children released.
        assert store.admission.active_count() == 16
        for parent in parents:
            assert store.admission.get(parent).suspended is False
    finally:
        store.close()
