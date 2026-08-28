"""Delegation service: the ``delegate_part_agent`` state machine (digest §3).

A durable, non-filesystem WAL in the opstore ``state.db`` (table
``tp_delegations``, keyed by the **trusted parent invocation**) drives one child
part-agent run through ``PREPARED → ADMITTED → DISPATCHED → TERMINAL``. It sits
on the opstore admission substrate:

* the **stable child run id** is derived deterministically from the invocation and
  persisted at ``ADMITTED``; dispatch and queueing are idempotent on it, so a
  crash at enqueue / dispatch / cancellation / terminal insertion / parent
  response produces **at most one child and exactly one terminal**;
* synchronous ``delivery="prompt"`` atomically suspends the parent into durable
  ``SUSPENDED_WAIT`` and reserves the child admission in one opstore
  transaction (:meth:`opstore.admission.AdmissionControl.suspend`) — net
  occupancy is unchanged, so 16 waiting orchestrators cannot starve 16 children;
* ``delivery="follow_up"`` reserves one of the 16 global slots before enqueue and
  returns ``queued`` immediately;
* the child terminal and the delegation-row terminal projection are written in
  **one** transaction (:meth:`opstore.admission.AdmissionControl.terminal_transaction`);
* cancellation/deadline/recovery follow the fixed precedence, always checking the
  child terminal first (an existing terminal wins) before any CAS.

Prompt limits (``x-hephaestus-maxUtf8Bytes = 32768``), the 1-1200 s deadline
window, and the +60 s grace are read from ``schemas/bridge_limits.json`` — no
literal is duplicated. NFC vs NFD prompts hash differently (exact code points).

Pre-admission classification (part validity / scope / session availability) is a
policy the session service owns; it is injected as :class:`DelegationGate` so the
state machine stays decoupled and unit-testable. A gate rejection yields a
``rejected`` outcome with **no** child run or ref.
"""

from __future__ import annotations

import enum
import hashlib
from dataclasses import dataclass
from typing import Any, Final, Protocol, cast, runtime_checkable

from opstore.admission import AdmissionControl
from opstore.db import Database
from opstore.errors import BusyError, NotFoundError
from opstore.types import Clock, JSONValue, OwnerId, SystemClock, TerminalState

from .limits import LIMITS, LimitError, enforce_max_utf8_bytes
from .session_edges import SessionEdgeStore

__all__ = [
    "DEADLINE_DEFAULT_S",
    "DEADLINE_MAX_S",
    "DEADLINE_MIN_S",
    "GRACE_S",
    "PROMPT_MAX_UTF8_BYTES",
    "DelegationError",
    "DelegationGate",
    "DelegationPhase",
    "DelegationRow",
    "DelegationService",
    "DelegationValidationError",
    "Delivery",
    "RejectionReason",
]

_D: Final[dict[str, Any]] = LIMITS["timeouts"]["delegation"]
DEADLINE_DEFAULT_S: Final[int] = int(_D["deadline_default_seconds"])
DEADLINE_MIN_S: Final[int] = int(_D["deadline_min_seconds"])
DEADLINE_MAX_S: Final[int] = int(_D["deadline_max_seconds"])
GRACE_S: Final[int] = int(_D["grace_seconds"])
PROMPT_MAX_UTF8_BYTES: Final[int] = int(LIMITS["prompt"]["max_utf8_bytes"])

_TABLE = "tp_delegations"
_CREATE_TABLE: Final[str] = f"""
CREATE TABLE IF NOT EXISTS {_TABLE}(
  delegation_ref TEXT PRIMARY KEY,
  invocation_key TEXT NOT NULL UNIQUE,
  parent_run_id TEXT NOT NULL,
  part TEXT NOT NULL,
  delivery TEXT NOT NULL,
  prompt_hash TEXT NOT NULL,
  deadline_seconds INTEGER NOT NULL,
  child_run_id TEXT NOT NULL,
  phase TEXT NOT NULL,
  deadline_at REAL,
  admitted_at REAL,
  terminal_state TEXT,
  result_artifact_ref TEXT,
  error TEXT,
  created_at REAL NOT NULL)
"""


class Delivery(enum.StrEnum):
    """Delegation delivery mode."""

    PROMPT = "prompt"
    FOLLOW_UP = "follow_up"


class DelegationPhase(enum.StrEnum):
    """Durable delegation-row phase."""

    PREPARED = "PREPARED"
    ADMITTED = "ADMITTED"
    DISPATCHED = "DISPATCHED"
    TERMINAL = "TERMINAL"


class RejectionReason(enum.StrEnum):
    """Pre-admission rejection reasons (no child run/ref is created)."""

    PART_BUSY = "part_busy"
    QUEUE_FULL = "queue_full"
    NO_RUN_SLOT = "no_run_slot"
    PROMPT_TOO_LARGE = "prompt_too_large"
    SCOPE_DENIED = "scope_denied"
    SESSION_BUSY = "session_busy"
    INVALID_PART = "invalid_part"


class DelegationError(Exception):
    """A delegation operation failed with a stable ``code``."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class DelegationValidationError(DelegationError):
    """Input violated a hard validation rule (maps to ``INVALID_PARAMS``)."""


@runtime_checkable
class DelegationGate(Protocol):
    """Pre-admission policy oracle owned by the session service.

    Returns a :class:`RejectionReason` when the delegation must be rejected
    *before* any child run is created (invalid/foreign/busy part, scope denial,
    prompt-queue overflow), or ``None`` when admission may proceed. Implementations
    must be side-effect free.
    """

    def classify(
        self, parent_run_id: str, part: str, delivery: Delivery
    ) -> RejectionReason | None: ...


class _AllowAllGate:
    """Default gate that never rejects (tests inject their own)."""

    def classify(self, parent_run_id: str, part: str, delivery: Delivery) -> RejectionReason | None:
        return None


@dataclass(frozen=True, slots=True)
class DelegationRow:
    """Snapshot of one durable delegation row."""

    delegation_ref: str
    invocation_key: str
    parent_run_id: str
    part: str
    delivery: Delivery
    prompt_hash: str
    deadline_seconds: int
    child_run_id: str
    phase: DelegationPhase
    deadline_at: float | None
    admitted_at: float | None
    terminal_state: TerminalState | None
    result_artifact_ref: str | None
    error: str | None
    created_at: float

    @property
    def rejected(self) -> bool:
        return False

    def status(self) -> str:
        """The ``delegate_part_agent`` result ``status`` for this row."""
        if self.phase is DelegationPhase.TERMINAL and self.terminal_state is not None:
            if self.terminal_state is TerminalState.COMPLETED:
                return "completed"
            return str(self.terminal_state)
        return "queued" if self.delivery is Delivery.FOLLOW_UP else "running"


@dataclass(frozen=True, slots=True)
class Rejected:
    """A pre-admission rejection: a reason and no child run/ref."""

    reason: RejectionReason

    @property
    def rejected(self) -> bool:
        return True

    def status(self) -> str:
        return "rejected"


DelegationOutcome = DelegationRow | Rejected


def _invocation_key(invocation: object) -> str:
    """Canonical trusted-invocation key from a str or a JSON-ish mapping."""
    if isinstance(invocation, str):
        return invocation
    if isinstance(invocation, dict):
        from opstore.hashing import canonical_json

        return canonical_json(cast(JSONValue, invocation))
    return str(invocation)


def _digest(*, prefix: str, key: str) -> str:
    return prefix + hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]


class DelegationService:
    """Durable delegation state machine over one opstore admission controller."""

    def __init__(
        self,
        admission: AdmissionControl,
        db: Database,
        *,
        gate: DelegationGate | None = None,
        clock: Clock | None = None,
        edges: SessionEdgeStore | None = None,
    ) -> None:
        self._admission = admission
        # INTERFACE.md §2.8: the parent/child *session* edge is recorded at the
        # PREPARED transition — the moment this WAL first admits the relationship
        # exists — and nowhere else. Optional because the delegation state machine
        # is unit-tested standalone and threading is not its subject; when it is
        # absent, no edge is written and the reopened tree reads `unlinked`
        # rather than being guessed at.
        self._edges = edges
        # Same connection the admission controller uses, so the delegation-row
        # projection commits atomically with the child terminal insertion.
        self._db = db
        self._gate = gate or _AllowAllGate()
        self._clock = clock or SystemClock()
        self._db.conn.execute(_CREATE_TABLE)

    # -- read ------------------------------------------------------------------

    def get(self, delegation_ref: str) -> DelegationRow:
        """The delegation row, or :class:`DelegationError` (``not_found``)."""
        row = self._fetch_ref(delegation_ref)
        if row is None:
            raise DelegationError("not_found", f"no delegation {delegation_ref}")
        return row

    def _fetch_ref(self, delegation_ref: str) -> DelegationRow | None:
        raw = self._db.conn.execute(
            f"SELECT * FROM {_TABLE} WHERE delegation_ref = ?", (delegation_ref,)
        ).fetchone()
        return None if raw is None else _to_row(raw)

    def get_by_invocation(self, invocation_key: str) -> DelegationRow | None:
        """The delegation row for a trusted invocation key, if one exists."""
        return self._fetch_invocation(invocation_key)

    def _fetch_invocation(self, invocation_key: str) -> DelegationRow | None:
        raw = self._db.conn.execute(
            f"SELECT * FROM {_TABLE} WHERE invocation_key = ?", (invocation_key,)
        ).fetchone()
        return None if raw is None else _to_row(raw)

    # -- delegate --------------------------------------------------------------

    def delegate(
        self,
        parent_run_id: str,
        part: str,
        prompt: str,
        *,
        delivery: Delivery = Delivery.PROMPT,
        deadline_seconds: int = DEADLINE_DEFAULT_S,
        invocation: object,
        child_owner: OwnerId | None = None,
        parent_session_id: str | None = None,
        child_session_id: str | None = None,
    ) -> DelegationOutcome:
        """Admit (or reject) a delegation; idempotent on the trusted invocation.

        Returns a :class:`DelegationRow` (``running`` for ``prompt`` / ``queued``
        for ``follow_up``) or a :class:`Rejected` outcome carrying one
        :class:`RejectionReason` and no child ref.

        ``parent_session_id`` / ``child_session_id`` are the two ids
        ``INTERFACE.md`` §2.8's edge is *about*. They are passed in rather than
        derived here because this state machine is keyed by **runs**, not
        sessions: the caller (``ToolDispatcher._delegate``) is the layer that
        holds both the trusted invocation's session and the conventional part
        session id. With either absent no edge is written — a rejected
        delegation creates no child, so it must create no edge either.
        """
        # 1. Validate the prompt (exact UTF-8; unpaired surrogate first).
        try:
            enforce_max_utf8_bytes(prompt, PROMPT_MAX_UTF8_BYTES, field="prompt")
        except LimitError as exc:
            if exc.code == "prompt_too_large":
                return Rejected(RejectionReason.PROMPT_TOO_LARGE)
            raise DelegationValidationError(exc.code, exc.message) from exc

        # 2. Validate the deadline window.
        if not (DEADLINE_MIN_S <= deadline_seconds <= DEADLINE_MAX_S):
            raise DelegationValidationError(
                "invalid_params",
                f"deadline_seconds {deadline_seconds} outside [{DEADLINE_MIN_S}, {DEADLINE_MAX_S}]",
            )

        invocation_key = _invocation_key(invocation)
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()

        # 3. Idempotency: a prior row for this invocation replays; a different
        #    payload for the same key is a hard error.
        existing = self._fetch_invocation(invocation_key)
        if existing is not None:
            if existing.prompt_hash != prompt_hash:
                raise DelegationValidationError(
                    "key_payload_mismatch",
                    "same invocation key presented a different prompt",
                )
            return self._advance_if_prepared(existing, child_owner)

        # 4. Pre-admission gate (invalid_part / scope_denied / *_busy / queue_full).
        reason = self._gate.classify(parent_run_id, part, delivery)
        if reason is not None:
            return Rejected(reason)

        # 5. Persist PREPARED intent, then reserve the slot (idempotent on child id).
        delegation_ref = _digest(prefix="dg-", key=invocation_key)
        child_run_id = _digest(prefix="cr-", key=invocation_key)
        now = self._clock.now()
        with self._db.transaction() as conn:
            conn.execute(
                f"INSERT INTO {_TABLE}(delegation_ref, invocation_key, parent_run_id, part, "
                "delivery, prompt_hash, deadline_seconds, child_run_id, phase, created_at) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    delegation_ref,
                    invocation_key,
                    parent_run_id,
                    part,
                    str(delivery),
                    prompt_hash,
                    deadline_seconds,
                    child_run_id,
                    DelegationPhase.PREPARED.value,
                    now,
                ),
            )
        self._record_edge(
            delegation_ref=delegation_ref,
            parent_run_id=parent_run_id,
            child_run_id=child_run_id,
            parent_session_id=parent_session_id,
            child_session_id=child_session_id,
        )
        return self._reserve(delegation_ref, child_owner)

    def _record_edge(
        self,
        *,
        delegation_ref: str,
        parent_run_id: str,
        child_run_id: str,
        parent_session_id: str | None,
        child_session_id: str | None,
    ) -> None:
        """Write §2.8's ``delegation`` session edge for a PREPARED delegation.

        Deliberately **not** inside the PREPARED transaction above. That
        transaction is the delegation WAL's own durability contract — the thing
        that guarantees at most one child and exactly one terminal — and
        threading is a projection for a UI panel. A failed edge write must not
        roll back an admitted delegation, so it is a separate write; the cost is
        that a crash between the two leaves the child unlinked, which is exactly
        the state §2.8 already names and renders (``unlinked``).
        """
        if self._edges is None or parent_session_id is None or child_session_id is None:
            return
        if parent_session_id == child_session_id:
            return
        self._edges.record(
            child_session_id=child_session_id,
            parent_session_id=parent_session_id,
            kind="delegation",
            origin={
                "delegation_ref": delegation_ref,
                "parent_run_id": parent_run_id,
                "child_run_id": child_run_id,
            },
        )

    def _advance_if_prepared(
        self, row: DelegationRow, child_owner: OwnerId | None
    ) -> DelegationOutcome:
        """Idempotent replay: resume a PREPARED row's reservation, else return it."""
        if row.phase is DelegationPhase.PREPARED:
            return self._reserve(row.delegation_ref, child_owner)
        return row

    def _reserve(self, delegation_ref: str, child_owner: OwnerId | None) -> DelegationOutcome:
        row = self.get(delegation_ref)
        now = self._clock.now()
        deadline_at = now + row.deadline_seconds
        if row.delivery is Delivery.PROMPT:
            # Atomic: parent → SUSPENDED_WAIT, child reserved (net occupancy 0).
            self._admission.suspend(
                row.parent_run_id,
                row.child_run_id,
                child_deadline_at=deadline_at,
                child_owner=child_owner,
            )
        else:
            try:
                self._admission.admit(row.child_run_id, deadline_at=deadline_at, owner=child_owner)
            except BusyError:
                # Rejection has no child ref: drop the PREPARED intent.
                with self._db.transaction() as conn:
                    conn.execute(
                        f"DELETE FROM {_TABLE} WHERE delegation_ref = ?", (delegation_ref,)
                    )
                return Rejected(RejectionReason.NO_RUN_SLOT)
        with self._db.transaction() as conn:
            conn.execute(
                f"UPDATE {_TABLE} SET phase = ?, deadline_at = ?, admitted_at = ? "
                "WHERE delegation_ref = ?",
                (DelegationPhase.ADMITTED.value, deadline_at, now, delegation_ref),
            )
        return self.get(delegation_ref)

    # -- dispatch --------------------------------------------------------------

    def dispatch(self, delegation_ref: str, *, owner: OwnerId | None = None) -> DelegationRow:
        """CAS the child ``ADMITTED → DISPATCHED`` (idempotent). Terminal forbids it."""
        row = self.get(delegation_ref)
        self._admission.dispatch(row.child_run_id, owner=owner)
        with self._db.transaction() as conn:
            conn.execute(
                f"UPDATE {_TABLE} SET phase = ? WHERE delegation_ref = ? AND phase != ?",
                (
                    DelegationPhase.DISPATCHED.value,
                    delegation_ref,
                    DelegationPhase.TERMINAL.value,
                ),
            )
        return self.get(delegation_ref)

    # -- terminal --------------------------------------------------------------

    def ingest_terminal(
        self,
        delegation_ref: str,
        state: TerminalState,
        *,
        result_artifact_ref: str | None = None,
        error: str | None = None,
    ) -> DelegationRow:
        """Project the child terminal and delegation row in ONE transaction.

        Idempotent for the same terminal; a distinct second terminal for a run
        that already terminated raises ``terminal_conflict``.
        """
        row = self.get(delegation_ref)
        if row.phase is DelegationPhase.TERMINAL:
            return row
        terminal_id = f"deleg:{row.child_run_id}:{state}"
        data: JSONValue = {
            "result_artifact_ref": result_artifact_ref,
            "error": error,
        }
        with self._admission.terminal_transaction(
            row.child_run_id, terminal_id, state, data
        ) as conn:
            conn.execute(
                f"UPDATE {_TABLE} SET phase = ?, terminal_state = ?, "
                "result_artifact_ref = ?, error = ? WHERE delegation_ref = ?",
                (
                    DelegationPhase.TERMINAL.value,
                    str(state),
                    result_artifact_ref,
                    error,
                    delegation_ref,
                ),
            )
        return self.get(delegation_ref)

    def acknowledge(self, delegation_ref: str) -> None:
        """Durably acknowledge the child terminal, releasing its slot."""
        row = self.get(delegation_ref)
        terminal = self._admission.get_terminal(row.child_run_id)
        if terminal is None:
            raise DelegationError("not_found", f"{delegation_ref} has no child terminal")
        self._admission.acknowledge_terminal(row.child_run_id, terminal.terminal_id)

    def resume_parent(self, delegation_ref: str) -> DelegationRow:
        """For ``prompt`` delivery: ack the child, reacquire the parent's slot.

        The parent leaves ``SUSPENDED_WAIT`` with FIFO priority over new
        admissions; returns the projected delegation row (the synchronous result).
        """
        row = self.get(delegation_ref)
        if row.delivery is not Delivery.PROMPT:
            raise DelegationError("conflicted", "resume_parent is prompt-delivery only")
        if row.phase is not DelegationPhase.TERMINAL:
            raise DelegationError("conflicted", f"{delegation_ref} child not yet terminal")
        # Free the child slot, then reacquire the parent's with FIFO priority.
        terminal = self._admission.get_terminal(row.child_run_id)
        if terminal is not None:
            self._admission.acknowledge_terminal(row.child_run_id, terminal.terminal_id)
        self._admission.resume_request(row.parent_run_id)
        self._admission.resume(row.parent_run_id)
        return row

    # -- cancel ----------------------------------------------------------------

    def cancel(self, delegation_ref: str) -> DelegationRow:
        """Cancel: terminal-wins check, then CAS to ``cancelled`` (idempotent).

        An already-terminal child returns its unchanged terminal state; otherwise
        the child is CAS'd to ``CANCEL_REQUESTED`` and finalized as the single
        durable ``cancelled`` terminal.
        """
        row = self.get(delegation_ref)
        if row.phase is DelegationPhase.TERMINAL:
            return row
        won = self._admission.request_cancel(row.child_run_id)
        if not won:
            # A terminal beat us; project it and return unchanged.
            return self._project_from_terminal(delegation_ref)
        return self.ingest_terminal(delegation_ref, TerminalState.CANCELLED, error="cancelled")

    # -- deadline / recovery ---------------------------------------------------

    def check_deadline(self, delegation_ref: str) -> DelegationRow:
        """If the persisted deadline has elapsed, finalize as ``timed_out`` only."""
        row = self.get(delegation_ref)
        if row.phase is DelegationPhase.TERMINAL:
            return row
        if row.deadline_at is None or self._clock.now() < row.deadline_at:
            return row
        won = self._admission.get_terminal(row.child_run_id) is None
        if not won:
            return self._project_from_terminal(delegation_ref)
        return self.ingest_terminal(delegation_ref, TerminalState.TIMED_OUT, error="timed_out")

    def recover(self, delegation_ref: str, *, child_owner: OwnerId | None = None) -> DelegationRow:
        """Resolve a delegation by the fixed precedence, synthesizing ≤ 1 terminal.

        (1) existing child/delegation terminal wins; (2) ``CANCEL_REQUESTED`` →
        ``cancelled``; (3) elapsed deadline → ``timed_out``; (4) a ``PREPARED`` row
        re-reserves with the persisted child id, an ``ADMITTED``/``DISPATCHED`` row
        is recovered under the persisted id (this precedence over generic
        interruption); (5) confirmed owner loss → ``interrupted``.
        """
        row = self.get(delegation_ref)
        if row.phase is DelegationPhase.TERMINAL:
            return row
        if row.phase is DelegationPhase.PREPARED:
            # Precedence (4): resume the PREPARED reservation idempotently.
            outcome = self._reserve(delegation_ref, child_owner)
            if isinstance(outcome, Rejected):
                return self.get(delegation_ref)
            row = outcome
        try:
            result = self._admission.recover(row.child_run_id)
        except NotFoundError:
            return row
        if result.terminal is not None:
            return self._project_from_terminal(delegation_ref)
        return row

    # -- projection helpers ----------------------------------------------------

    def _project_from_terminal(self, delegation_ref: str) -> DelegationRow:
        """Idempotently mirror the authoritative child terminal onto the row."""
        row = self.get(delegation_ref)
        terminal = self._admission.get_terminal(row.child_run_id)
        if terminal is None:
            return row
        data = terminal.data if isinstance(terminal.data, dict) else {}
        result_ref = data.get("result_artifact_ref")
        error = data.get("error")
        with self._db.transaction() as conn:
            conn.execute(
                f"UPDATE {_TABLE} SET phase = ?, terminal_state = ?, "
                "result_artifact_ref = COALESCE(result_artifact_ref, ?), "
                "error = COALESCE(error, ?) WHERE delegation_ref = ?",
                (
                    DelegationPhase.TERMINAL.value,
                    str(terminal.state),
                    None if result_ref is None else str(result_ref),
                    None if error is None else str(error),
                    delegation_ref,
                ),
            )
        return self.get(delegation_ref)


def _to_row(raw: Any) -> DelegationRow:
    ts = raw["terminal_state"]
    return DelegationRow(
        delegation_ref=str(raw["delegation_ref"]),
        invocation_key=str(raw["invocation_key"]),
        parent_run_id=str(raw["parent_run_id"]),
        part=str(raw["part"]),
        delivery=Delivery(str(raw["delivery"])),
        prompt_hash=str(raw["prompt_hash"]),
        deadline_seconds=int(raw["deadline_seconds"]),
        child_run_id=str(raw["child_run_id"]),
        phase=DelegationPhase(str(raw["phase"])),
        deadline_at=None if raw["deadline_at"] is None else float(raw["deadline_at"]),
        admitted_at=None if raw["admitted_at"] is None else float(raw["admitted_at"]),
        terminal_state=None if ts is None else TerminalState(str(ts)),
        result_artifact_ref=(
            None if raw["result_artifact_ref"] is None else str(raw["result_artifact_ref"])
        ),
        error=None if raw["error"] is None else str(raw["error"]),
        created_at=float(raw["created_at"]),
    )
