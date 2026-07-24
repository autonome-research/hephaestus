"""Durable admission slots, suspension, terminal records, and acknowledgment.

Contract (DESIGN.md "admission.py", architecture.md §3.5/§5):

- Admission rows keyed by caller-supplied stable ``run_id``; states
  ``ADMITTED → DISPATCHED → TERMINAL`` plus ``CANCEL_REQUESTED`` and the durable
  ``SUSPENDED_WAIT`` flag (``suspended``). The absolute ``deadline_at`` is
  persisted at admission (queued time counts against it).
- Slot rule: active = rows without a durable terminal **acknowledgment**,
  excluding rows durably in ``SUSPENDED_WAIT``. A new admission succeeds only
  while active + pending resume reservations < ``config.run_slots``; otherwise
  the structured ``busy`` error. Queued resume requests therefore have FIFO
  priority over new admissions.
- ``suspend`` releases the parent's slot and reserves the child admission in ONE
  transaction (net occupancy unchanged); ``resume_request``/``resume`` reacquire
  through the FIFO ``resume_queue``.
- Terminals are unique per ``(run_id, 'terminal')``. ``insert_terminal`` is
  idempotent for the same terminal (id + payload hash) and rejects a distinct
  second terminal (``terminal_conflict``). ``terminal_transaction`` exposes the
  insertion transaction so callers project their own state atomically with it.
- ``acknowledge_terminal`` is durable + idempotent; the slot is released only
  once the ack is durable (a terminal-unacknowledged run keeps occupying).
- Startup occupancy = **union** (never the sum) of admitted-nonterminal and
  terminal-unacknowledged run ids; ``startup_reconstruct`` repairs admission
  rows against persisted terminals before reporting available slots.
- ``recover`` applies the fixed precedence: existing terminal wins >
  ``CANCEL_REQUESTED`` → ``cancelled`` > elapsed deadline → ``timed_out`` >
  confirmed owner loss → ``interrupted``. At most one terminal is ever
  synthesized per run; a crash after insertion or ack creates no extra terminal.
- Crash points (``CrashHook``): ``admission.after_admit``,
  ``admission.after_suspend``, ``admission.after_terminal_insert``,
  ``admission.after_ack``.
"""

from __future__ import annotations

import enum
import json
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass

from opstore.db import Database
from opstore.errors import BusyError, ConflictedError, NotFoundError, TerminalConflictError
from opstore.hashing import canonical_json, sha256_bytes
from opstore.types import (
    AdmissionState,
    Clock,
    CrashHook,
    DefaultLiveness,
    JSONValue,
    Liveness,
    NoopCrashHook,
    OwnerId,
    StoreConfig,
    SystemClock,
    TerminalState,
)

CRASH_AFTER_ADMIT = "admission.after_admit"
CRASH_AFTER_SUSPEND = "admission.after_suspend"
CRASH_AFTER_TERMINAL_INSERT = "admission.after_terminal_insert"
CRASH_AFTER_ACK = "admission.after_ack"

_TERMINAL_KIND = "terminal"

_OCCUPIED_SQL = """
SELECT run_id FROM admissions
 WHERE terminal_acked_at IS NULL AND suspended = 0
UNION
SELECT t.run_id FROM terminals t JOIN admissions a ON a.run_id = t.run_id
 WHERE t.kind = 'terminal' AND a.terminal_acked_at IS NULL AND a.suspended = 0
"""

_ACTIVE_COUNT_SQL = f"SELECT COUNT(*) FROM ({_OCCUPIED_SQL})"

_PENDING_RESUME_SQL = """
SELECT COUNT(*) FROM resume_queue q JOIN admissions a ON a.run_id = q.run_id
 WHERE a.suspended = 1 AND a.terminal_acked_at IS NULL AND a.state != 'TERMINAL'
   AND NOT EXISTS (SELECT 1 FROM terminals t
                   WHERE t.run_id = q.run_id AND t.kind = 'terminal')
"""

_PENDING_AHEAD_SQL = _PENDING_RESUME_SQL + " AND q.seq < ?"


class RecoveryReason(enum.StrEnum):
    """Which precedence branch ``recover`` resolved a run through."""

    EXISTING_TERMINAL = "existing_terminal"
    CANCEL_REQUESTED = "cancel_requested"
    DEADLINE = "deadline"
    OWNER_LOSS = "owner_loss"
    LIVE = "live"


@dataclass(frozen=True, slots=True)
class AdmissionRow:
    """Snapshot of one durable admission row."""

    run_id: str
    state: AdmissionState
    suspended: bool
    deadline_at: float | None
    admitted_at: float
    terminal_id: str | None
    terminal_acked_at: float | None
    owner: OwnerId | None


@dataclass(frozen=True, slots=True)
class TerminalRecord:
    """One durable terminal record (unique per run)."""

    run_id: str
    terminal_id: str
    state: TerminalState
    data: JSONValue
    payload_hash: str
    created_at: float


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    """Outcome of ``recover``: the winning precedence branch and its terminal."""

    reason: RecoveryReason
    terminal: TerminalRecord | None
    synthesized: bool


@dataclass(frozen=True, slots=True)
class StartupReport:
    """Occupancy reconstructed at startup (union of the two unfinished sets)."""

    occupied_run_ids: frozenset[str]
    available_slots: int
    resolved_run_ids: frozenset[str]


def _count(conn: sqlite3.Connection, sql: str, params: tuple[object, ...] = ()) -> int:
    row = conn.execute(sql, params).fetchone()
    return int(row[0])


def _to_admission(row: sqlite3.Row) -> AdmissionRow:
    owner_pid = row["owner_pid"]
    owner = None if owner_pid is None else OwnerId(int(owner_pid), int(row["owner_start_ns"] or 0))
    deadline = row["deadline_at"]
    acked_at = row["terminal_acked_at"]
    terminal_id = row["terminal_id"]
    return AdmissionRow(
        run_id=str(row["run_id"]),
        state=AdmissionState(str(row["state"])),
        suspended=bool(row["suspended"]),
        deadline_at=None if deadline is None else float(deadline),
        admitted_at=float(row["admitted_at"]),
        terminal_id=None if terminal_id is None else str(terminal_id),
        terminal_acked_at=None if acked_at is None else float(acked_at),
        owner=owner,
    )


def _to_terminal(row: sqlite3.Row) -> TerminalRecord:
    wrapped: dict[str, JSONValue] = json.loads(str(row["payload"]))
    return TerminalRecord(
        run_id=str(row["run_id"]),
        terminal_id=str(row["terminal_id"]),
        state=TerminalState(str(wrapped["state"])),
        data=wrapped.get("data"),
        payload_hash=str(row["payload_hash"]),
        created_at=float(row["created_at"]),
    )


class AdmissionControl:
    """Durable run admission, suspension, terminal, and acknowledgment manager."""

    def __init__(
        self,
        db: Database,
        config: StoreConfig | None = None,
        clock: Clock | None = None,
        liveness: Liveness | None = None,
        crash_hook: CrashHook | None = None,
    ) -> None:
        self._db = db
        self._config = config or StoreConfig()
        self._clock = clock or SystemClock()
        self._liveness = liveness or DefaultLiveness()
        self._crash = crash_hook or NoopCrashHook()

    def _fetch_admission(self, conn: sqlite3.Connection, run_id: str) -> sqlite3.Row | None:
        return conn.execute("SELECT * FROM admissions WHERE run_id = ?", (run_id,)).fetchone()

    def _fetch_terminal(self, conn: sqlite3.Connection, run_id: str) -> sqlite3.Row | None:
        return conn.execute(
            "SELECT * FROM terminals WHERE run_id = ? AND kind = ?", (run_id, _TERMINAL_KIND)
        ).fetchone()

    def get(self, run_id: str) -> AdmissionRow:
        """Current admission row, or ``NotFoundError``."""
        raw = self._fetch_admission(self._db.conn, run_id)
        if raw is None:
            raise NotFoundError(f"run {run_id} has no admission row")
        return _to_admission(raw)

    def get_terminal(self, run_id: str) -> TerminalRecord | None:
        """The run's terminal record, or None if no terminal was inserted."""
        raw = self._fetch_terminal(self._db.conn, run_id)
        return None if raw is None else _to_terminal(raw)

    def occupied_run_ids(self) -> frozenset[str]:
        """Run ids occupying a slot: union of nonterminal and terminal-unacked ids."""
        rows = self._db.conn.execute(_OCCUPIED_SQL).fetchall()
        return frozenset(str(row["run_id"]) for row in rows)

    def active_count(self) -> int:
        """Number of occupied slots (terminal-unacked included, SUSPENDED_WAIT excluded)."""
        return _count(self._db.conn, _ACTIVE_COUNT_SQL)

    def pending_resume_count(self) -> int:
        """Queued resume requests that reserve a slot ahead of new admissions."""
        return _count(self._db.conn, _PENDING_RESUME_SQL)

    def available_slots(self) -> int:
        """Slots a NEW admission could take right now (resume reservations excluded)."""
        free = self._config.run_slots - self.active_count() - self.pending_resume_count()
        return max(0, free)

    def admit(
        self,
        run_id: str,
        *,
        deadline_at: float | None = None,
        owner: OwnerId | None = None,
    ) -> AdmissionRow:
        """Admit a new run, persisting ``deadline_at``; idempotent on ``run_id``.

        Raises ``BusyError`` when active occupancy plus queued resume
        reservations leave no free slot.
        """
        with self._db.transaction() as conn:
            existing = self._fetch_admission(conn, run_id)
            if existing is not None:
                row = _to_admission(existing)
            else:
                active = _count(conn, _ACTIVE_COUNT_SQL)
                pending = _count(conn, _PENDING_RESUME_SQL)
                if active + pending >= self._config.run_slots:
                    raise BusyError(
                        f"no admission slot for {run_id}: {active} active + {pending} "
                        f"queued resumes >= {self._config.run_slots} run_slots"
                    )
                now = self._clock.now()
                conn.execute(
                    "INSERT INTO admissions(run_id, state, suspended, deadline_at, "
                    "admitted_at, owner_pid, owner_start_ns) VALUES(?, ?, 0, ?, ?, ?, ?)",
                    (
                        run_id,
                        AdmissionState.ADMITTED.value,
                        deadline_at,
                        now,
                        None if owner is None else owner.pid,
                        None if owner is None else owner.pid_start_ns,
                    ),
                )
                row = AdmissionRow(
                    run_id=run_id,
                    state=AdmissionState.ADMITTED,
                    suspended=False,
                    deadline_at=deadline_at,
                    admitted_at=now,
                    terminal_id=None,
                    terminal_acked_at=None,
                    owner=owner,
                )
        self._crash.maybe_crash(CRASH_AFTER_ADMIT)
        return row

    def dispatch(self, run_id: str, *, owner: OwnerId | None = None) -> AdmissionRow:
        """CAS ``ADMITTED → DISPATCHED`` (idempotent when already dispatched).

        Any terminal forbids dispatch (``terminal_conflict``); so does
        ``CANCEL_REQUESTED`` (``conflicted``).
        """
        with self._db.transaction() as conn:
            raw = self._fetch_admission(conn, run_id)
            if raw is None:
                raise NotFoundError(f"run {run_id} has no admission row")
            row = _to_admission(raw)
            has_terminal = self._fetch_terminal(conn, run_id) is not None
            if has_terminal or row.state is AdmissionState.TERMINAL:
                raise TerminalConflictError(f"run {run_id} is terminal; dispatch forbidden")
            if row.state is AdmissionState.CANCEL_REQUESTED:
                raise ConflictedError(f"run {run_id} is CANCEL_REQUESTED; dispatch forbidden")
            if row.state is AdmissionState.ADMITTED:
                if owner is None:
                    conn.execute(
                        "UPDATE admissions SET state = ? WHERE run_id = ?",
                        (AdmissionState.DISPATCHED.value, run_id),
                    )
                else:
                    conn.execute(
                        "UPDATE admissions SET state = ?, owner_pid = ?, owner_start_ns = ? "
                        "WHERE run_id = ?",
                        (AdmissionState.DISPATCHED.value, owner.pid, owner.pid_start_ns, run_id),
                    )
        return self.get(run_id)

    def suspend(
        self,
        parent_run_id: str,
        child_run_id: str,
        *,
        child_deadline_at: float | None = None,
        child_owner: OwnerId | None = None,
    ) -> AdmissionRow:
        """Move the parent to durable SUSPENDED_WAIT and reserve the child admission.

        One transaction: the parent's slot is released and the child's reserved
        atomically, so net occupancy never changes and no ``Busy`` is possible.
        Idempotent replay: an already-suspended parent with the same existing
        child returns that child's row. Returns the child admission row.
        """
        with self._db.transaction() as conn:
            parent_raw = self._fetch_admission(conn, parent_run_id)
            if parent_raw is None:
                raise NotFoundError(f"parent run {parent_run_id} has no admission row")
            parent = _to_admission(parent_raw)
            has_terminal = self._fetch_terminal(conn, parent_run_id) is not None
            if has_terminal or parent.state is AdmissionState.TERMINAL:
                raise TerminalConflictError(
                    f"parent run {parent_run_id} is terminal; suspend forbidden"
                )
            child_raw = self._fetch_admission(conn, child_run_id)
            if parent.suspended:
                if child_raw is None:
                    raise ConflictedError(
                        f"parent {parent_run_id} already suspended without child {child_run_id}"
                    )
                child = _to_admission(child_raw)
            else:
                if parent.state is AdmissionState.CANCEL_REQUESTED:
                    raise ConflictedError(
                        f"parent run {parent_run_id} is CANCEL_REQUESTED; suspend forbidden"
                    )
                if child_raw is not None:
                    raise ConflictedError(f"child run {child_run_id} is already admitted")
                now = self._clock.now()
                conn.execute(
                    "UPDATE admissions SET suspended = 1 WHERE run_id = ?", (parent_run_id,)
                )
                conn.execute(
                    "INSERT INTO admissions(run_id, state, suspended, deadline_at, "
                    "admitted_at, owner_pid, owner_start_ns) VALUES(?, ?, 0, ?, ?, ?, ?)",
                    (
                        child_run_id,
                        AdmissionState.ADMITTED.value,
                        child_deadline_at,
                        now,
                        None if child_owner is None else child_owner.pid,
                        None if child_owner is None else child_owner.pid_start_ns,
                    ),
                )
                child = AdmissionRow(
                    run_id=child_run_id,
                    state=AdmissionState.ADMITTED,
                    suspended=False,
                    deadline_at=child_deadline_at,
                    admitted_at=now,
                    terminal_id=None,
                    terminal_acked_at=None,
                    owner=child_owner,
                )
        self._crash.maybe_crash(CRASH_AFTER_SUSPEND)
        return child

    def resume_request(self, run_id: str) -> None:
        """Enqueue a suspended parent for FIFO-prioritized slot reacquisition.

        Idempotent: re-requesting or requesting an already-resumed run is a
        no-op. A run with a terminal cannot resume (``terminal_conflict``).
        """
        with self._db.transaction() as conn:
            raw = self._fetch_admission(conn, run_id)
            if raw is None:
                raise NotFoundError(f"run {run_id} has no admission row")
            row = _to_admission(raw)
            has_terminal = self._fetch_terminal(conn, run_id) is not None
            if has_terminal or row.state is AdmissionState.TERMINAL:
                raise TerminalConflictError(f"run {run_id} is terminal; resume forbidden")
            if not row.suspended:
                return
            conn.execute(
                "INSERT INTO resume_queue(run_id, requested_at) VALUES(?, ?) "
                "ON CONFLICT(run_id) DO NOTHING",
                (run_id, self._clock.now()),
            )

    def resume(self, run_id: str) -> AdmissionRow:
        """Reacquire an active slot for a queued suspended parent (FIFO priority).

        Succeeds only when a free slot exists after every earlier-queued
        eligible resume request is accounted for; otherwise ``BusyError``.
        Idempotent once resumed.
        """
        with self._db.transaction() as conn:
            raw = self._fetch_admission(conn, run_id)
            if raw is None:
                raise NotFoundError(f"run {run_id} has no admission row")
            row = _to_admission(raw)
            has_terminal = self._fetch_terminal(conn, run_id) is not None
            if has_terminal or row.state is AdmissionState.TERMINAL:
                raise TerminalConflictError(f"run {run_id} is terminal; resume forbidden")
            queue_row = conn.execute(
                "SELECT seq FROM resume_queue WHERE run_id = ?", (run_id,)
            ).fetchone()
            if not row.suspended:
                if queue_row is not None:
                    conn.execute("DELETE FROM resume_queue WHERE run_id = ?", (run_id,))
                return row
            if queue_row is None:
                raise ConflictedError(f"resume of {run_id} was not requested")
            active = _count(conn, _ACTIVE_COUNT_SQL)
            free = self._config.run_slots - active
            ahead = _count(conn, _PENDING_AHEAD_SQL, (int(queue_row["seq"]),))
            if free <= ahead:
                raise BusyError(
                    f"no slot to resume {run_id}: {active} active, "
                    f"{ahead} earlier resume requests, {self._config.run_slots} run_slots"
                )
            conn.execute("DELETE FROM resume_queue WHERE run_id = ?", (run_id,))
            conn.execute("UPDATE admissions SET suspended = 0 WHERE run_id = ?", (run_id,))
        return self.get(run_id)

    def request_cancel(self, run_id: str) -> bool:
        """CAS the run to ``CANCEL_REQUESTED`` iff no terminal exists.

        Returns True when the run is (now) CANCEL_REQUESTED, False when a
        terminal already exists (the terminal wins).
        """
        with self._db.transaction() as conn:
            raw = self._fetch_admission(conn, run_id)
            if raw is None:
                raise NotFoundError(f"run {run_id} has no admission row")
            row = _to_admission(raw)
            has_terminal = self._fetch_terminal(conn, run_id) is not None
            if has_terminal or row.state is AdmissionState.TERMINAL:
                return False
            conn.execute(
                "UPDATE admissions SET state = ? WHERE run_id = ?",
                (AdmissionState.CANCEL_REQUESTED.value, run_id),
            )
        return True

    def _insert_terminal_locked(
        self,
        conn: sqlite3.Connection,
        run_id: str,
        terminal_id: str,
        state: TerminalState,
        data: JSONValue,
    ) -> TerminalRecord:
        if self._fetch_admission(conn, run_id) is None:
            raise NotFoundError(f"run {run_id} has no admission row")
        payload_text = canonical_json({"state": str(state), "data": data})
        payload_hash = sha256_bytes(payload_text.encode("utf-8"))
        existing = self._fetch_terminal(conn, run_id)
        if existing is not None:
            record = _to_terminal(existing)
            if record.terminal_id == terminal_id and record.payload_hash == payload_hash:
                return record
            raise TerminalConflictError(
                f"run {run_id} already has terminal {record.terminal_id}; "
                f"distinct terminal {terminal_id} rejected"
            )
        now = self._clock.now()
        conn.execute(
            "INSERT INTO terminals(run_id, kind, terminal_id, payload_hash, payload, "
            "created_at) VALUES(?, ?, ?, ?, ?, ?)",
            (run_id, _TERMINAL_KIND, terminal_id, payload_hash, payload_text, now),
        )
        conn.execute(
            "UPDATE admissions SET state = ?, terminal_id = ? WHERE run_id = ?",
            (AdmissionState.TERMINAL.value, terminal_id, run_id),
        )
        conn.execute("DELETE FROM resume_queue WHERE run_id = ?", (run_id,))
        return TerminalRecord(
            run_id=run_id,
            terminal_id=terminal_id,
            state=state,
            data=data,
            payload_hash=payload_hash,
            created_at=now,
        )

    @contextmanager
    def terminal_transaction(
        self,
        run_id: str,
        terminal_id: str,
        state: TerminalState,
        data: JSONValue = None,
    ) -> Generator[sqlite3.Connection]:
        """Insert the run's terminal and run the caller's projection in ONE transaction.

        The terminal row (and the admission row's TERMINAL projection) is
        written first, then the connection is yielded so the caller can project
        its own state atomically. Idempotent for the same terminal; a distinct
        second terminal raises ``TerminalConflictError`` before the caller's
        projection runs.
        """
        with self._db.transaction() as conn:
            self._insert_terminal_locked(conn, run_id, terminal_id, state, data)
            yield conn
        self._crash.maybe_crash(CRASH_AFTER_TERMINAL_INSERT)

    def insert_terminal(
        self,
        run_id: str,
        terminal_id: str,
        state: TerminalState,
        data: JSONValue = None,
    ) -> TerminalRecord:
        """Insert the run's unique terminal (idempotent; distinct second rejected)."""
        with self._db.transaction() as conn:
            record = self._insert_terminal_locked(conn, run_id, terminal_id, state, data)
        self._crash.maybe_crash(CRASH_AFTER_TERMINAL_INSERT)
        return record

    def acknowledge_terminal(self, run_id: str, terminal_id: str) -> None:
        """Durably + idempotently acknowledge the named terminal, releasing the slot.

        The slot is only released once the ack row is durable (committed); the
        first ack timestamp is preserved on replay. Naming a different terminal
        id raises ``TerminalConflictError``; a missing terminal ``NotFoundError``.
        """
        with self._db.transaction() as conn:
            raw = self._fetch_terminal(conn, run_id)
            if raw is None:
                raise NotFoundError(f"run {run_id} has no terminal to acknowledge")
            recorded = str(raw["terminal_id"])
            if recorded != terminal_id:
                raise TerminalConflictError(
                    f"run {run_id} terminal is {recorded}; ack of {terminal_id} rejected"
                )
            conn.execute(
                "UPDATE admissions SET terminal_acked_at = COALESCE(terminal_acked_at, ?), "
                "state = ?, terminal_id = ? WHERE run_id = ?",
                (self._clock.now(), AdmissionState.TERMINAL.value, terminal_id, run_id),
            )
        self._crash.maybe_crash(CRASH_AFTER_ACK)

    def startup_reconstruct(self) -> StartupReport:
        """Reconstruct occupancy after restart: union of the two unfinished sets.

        Repairs admission rows that diverged from persisted terminals (state or
        terminal id), prunes resume-queue entries for terminal runs, and
        reports occupancy as the UNION (never the sum) of admitted-nonterminal
        and terminal-unacknowledged run ids.
        """
        with self._db.transaction() as conn:
            stale = conn.execute(
                "SELECT t.run_id AS run_id, t.terminal_id AS terminal_id "
                "FROM terminals t JOIN admissions a ON a.run_id = t.run_id "
                "WHERE t.kind = ? AND (a.state != ? OR a.terminal_id IS NULL "
                "OR a.terminal_id != t.terminal_id)",
                (_TERMINAL_KIND, AdmissionState.TERMINAL.value),
            ).fetchall()
            for row in stale:
                conn.execute(
                    "UPDATE admissions SET state = ?, terminal_id = ? WHERE run_id = ?",
                    (AdmissionState.TERMINAL.value, str(row["terminal_id"]), str(row["run_id"])),
                )
            conn.execute(
                "DELETE FROM resume_queue WHERE run_id IN "
                "(SELECT run_id FROM terminals WHERE kind = ?)",
                (_TERMINAL_KIND,),
            )
            occupied = frozenset(
                str(row["run_id"]) for row in conn.execute(_OCCUPIED_SQL).fetchall()
            )
        return StartupReport(
            occupied_run_ids=occupied,
            available_slots=max(0, self._config.run_slots - len(occupied)),
            resolved_run_ids=frozenset(str(row["run_id"]) for row in stale),
        )

    def recover(self, run_id: str) -> RecoveryResult:
        """Resolve a run by the fixed recovery precedence, synthesizing ≤ 1 terminal.

        Precedence: (1) an existing terminal wins untouched; (2)
        ``CANCEL_REQUESTED`` finishes as ``cancelled``; (3) an elapsed
        persisted deadline as ``timed_out``; (4) confirmed owner loss as
        ``interrupted``; otherwise the run is live and nothing is synthesized.
        The check and any synthesis share one transaction, so concurrent
        recoverers cannot produce a second terminal.
        """
        with self._db.transaction() as conn:
            raw = self._fetch_admission(conn, run_id)
            if raw is None:
                raise NotFoundError(f"run {run_id} has no admission row")
            row = _to_admission(raw)
            existing = self._fetch_terminal(conn, run_id)
            if existing is not None:
                return RecoveryResult(
                    reason=RecoveryReason.EXISTING_TERMINAL,
                    terminal=_to_terminal(existing),
                    synthesized=False,
                )
            if row.state is AdmissionState.CANCEL_REQUESTED:
                reason = RecoveryReason.CANCEL_REQUESTED
                terminal_state = TerminalState.CANCELLED
            elif row.deadline_at is not None and self._clock.now() >= row.deadline_at:
                reason = RecoveryReason.DEADLINE
                terminal_state = TerminalState.TIMED_OUT
            elif row.owner is not None and not self._liveness.is_alive(row.owner):
                reason = RecoveryReason.OWNER_LOSS
                terminal_state = TerminalState.INTERRUPTED
            else:
                return RecoveryResult(reason=RecoveryReason.LIVE, terminal=None, synthesized=False)
            record = self._insert_terminal_locked(
                conn,
                run_id,
                f"recovery:{run_id}:{terminal_state}",
                terminal_state,
                {"reason": str(reason)},
            )
        self._crash.maybe_crash(CRASH_AFTER_TERMINAL_INSERT)
        return RecoveryResult(reason=reason, terminal=record, synthesized=True)
