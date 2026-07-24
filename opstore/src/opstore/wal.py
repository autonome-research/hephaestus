"""Generic file-mutation WAL: prepare/commit with crash points and recovery.

Contract (DESIGN.md "wal.py" + architecture.md §3.5). Per-operation state
machine over rows in ``operations`` (skeleton rows registered by
``opkeys.begin``):

1. write+fsync preimage blob, candidate blob, and a same-directory candidate
   temp file  [crash point ``after_blob_fsync``]
2. ``PREPARED`` row recorded transactionally with op key, payload hash,
   before/after hashes, target path, intended outcome; an optional ``validate``
   callable runs inside that transaction  [``after_prepared``]
3. atomic rename candidate→target, fsync file + parent dir  [``after_install``,
   ``after_dir_fsync``]
4. ``COMMITTED`` + response recorded  [``after_committed``]

Recovery (``recover(op_key)`` / startup ``recover_all()``) runs under the
caller-provided per-target lock (``LockProvider`` hook): live hash ==
candidate → complete the commit; == preimage → reapply; any third hash → mark
``CONFLICTED`` **without overwriting**. Committed retries replay the recorded
response. The recovery outcome is identical regardless of crash point; the
recorded response is always the ``intended_outcome`` fixed at prepare time so
replay equality holds across crashes.

Pointer-CAS publication variant: ``publish(fresh, pointer_name,
expected_pointer_hash, bundle_hash)`` under the same PREPARED/COMMITTED
discipline with crash points ``publish.after_prepared``, ``publish.after_swap``,
``publish.after_committed``; recovery completes the swap, reapplies it, or
marks ``CONFLICTED`` when the pointer holds a third hash.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

from opstore.blobs import BlobStore
from opstore.db import Database
from opstore.errors import ConflictedError, NotFoundError
from opstore.hashing import hex_of, sha256_bytes, sha256_file
from opstore.opkeys import Fresh
from opstore.types import Clock, CrashHook, NoopCrashHook, OperationState, SystemClock

CRASH_AFTER_BLOB_FSYNC = "after_blob_fsync"
CRASH_AFTER_PREPARED = "after_prepared"
CRASH_AFTER_INSTALL = "after_install"
CRASH_AFTER_DIR_FSYNC = "after_dir_fsync"
CRASH_AFTER_COMMITTED = "after_committed"
CRASH_PUBLISH_AFTER_PREPARED = "publish.after_prepared"
CRASH_PUBLISH_AFTER_SWAP = "publish.after_swap"
CRASH_PUBLISH_AFTER_COMMITTED = "publish.after_committed"

FILE_CRASH_POINTS: tuple[str, ...] = (
    CRASH_AFTER_BLOB_FSYNC,
    CRASH_AFTER_PREPARED,
    CRASH_AFTER_INSTALL,
    CRASH_AFTER_DIR_FSYNC,
    CRASH_AFTER_COMMITTED,
)
PUBLISH_CRASH_POINTS: tuple[str, ...] = (
    CRASH_PUBLISH_AFTER_PREPARED,
    CRASH_PUBLISH_AFTER_SWAP,
    CRASH_PUBLISH_AFTER_COMMITTED,
)

POINTER_TARGET_PREFIX = "pointer:"
_TEMP_SUFFIX = ".wal"

Action = Literal["committed", "completed", "reapplied", "replayed", "conflicted", "aborted"]


@runtime_checkable
class LockProvider(Protocol):
    """Caller-provided per-target lock hook used during recovery."""

    def lock(self, target: str) -> AbstractContextManager[None]: ...


class NullLockProvider:
    """Default lock provider: no cross-process locking."""

    def lock(self, target: str) -> AbstractContextManager[None]:
        return nullcontext()


@dataclass(frozen=True, slots=True)
class PreparedOp:
    """Durable prepare record for a file mutation (input to ``commit``)."""

    op_key: str
    target: Path
    candidate_temp: Path
    before_hash: str | None
    after_hash: str
    preimage_blob: str | None
    candidate_blob: str
    intended_outcome: str


@dataclass(frozen=True, slots=True)
class PublishOp:
    """Durable prepare record for a pointer-CAS publication."""

    op_key: str
    pointer_name: str
    expected_pointer_hash: str | None
    bundle_hash: str
    intended_outcome: str


@dataclass(frozen=True, slots=True)
class WalOutcome:
    """Result of commit/publish/recovery for one operation."""

    op_key: str
    action: Action
    state: OperationState | None
    response: str | None
    after_hash: str | None


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _fsync_file(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_file_fsync(path: Path, data: bytes) -> None:
    path.unlink(missing_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)


def _temp_path(target: Path, after_hash: str) -> Path:
    return target.parent / f".{target.name}.{hex_of(after_hash)[:16]}{_TEMP_SUFFIX}"


def _cleanup_temps(target: Path) -> None:
    prefix = f".{target.name}."
    try:
        entries = list(target.parent.iterdir())
    except FileNotFoundError:
        return
    for entry in entries:
        if entry.name.startswith(prefix) and entry.name.endswith(_TEMP_SUFFIX):
            entry.unlink(missing_ok=True)


class Wal:
    """Crash-recoverable file mutations and pointer publications."""

    def __init__(
        self,
        db: Database,
        blobs: BlobStore,
        clock: Clock | None = None,
        crash_hook: CrashHook | None = None,
        lock_provider: LockProvider | None = None,
    ) -> None:
        self._db = db
        self._blobs = blobs
        self._clock = clock or SystemClock()
        self._crash = crash_hook or NoopCrashHook()
        self._locks = lock_provider or NullLockProvider()

    def prepare(
        self,
        fresh: Fresh,
        target: Path,
        candidate: bytes,
        *,
        intended_outcome: str,
        validate: Callable[[PreparedOp], None] | None = None,
    ) -> PreparedOp:
        """Steps 1-2: durable preimage/candidate blobs + PREPARED row.

        ``intended_outcome`` is the response that will be recorded at commit
        (fixed here so crash recovery replays an identical response).
        ``validate`` runs inside the PREPARED transaction; raising rolls the
        row back to its skeleton state without touching the target.
        """
        self._require_skeleton(fresh.op_key)
        before_hash: str | None = None
        preimage_blob: str | None = None
        if target.exists():
            preimage = target.read_bytes()
            before_hash = sha256_bytes(preimage)
            preimage_blob = self._blobs.put(preimage)
        after_hash = sha256_bytes(candidate)
        candidate_blob = self._blobs.put(candidate)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = _temp_path(target, after_hash)
        _write_file_fsync(temp, candidate)
        _fsync_dir(target.parent)
        self._crash.maybe_crash(CRASH_AFTER_BLOB_FSYNC)
        prepared = PreparedOp(
            op_key=fresh.op_key,
            target=target,
            candidate_temp=temp,
            before_hash=before_hash,
            after_hash=after_hash,
            preimage_blob=preimage_blob,
            candidate_blob=candidate_blob,
            intended_outcome=intended_outcome,
        )
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE operations SET target_path = ?, before_hash = ?, after_hash = ?, "
                "preimage_blob = ?, candidate_blob = ?, intended_outcome = ? "
                "WHERE op_key = ? AND state = 'PREPARED'",
                (
                    str(target),
                    before_hash,
                    after_hash,
                    preimage_blob,
                    candidate_blob,
                    intended_outcome,
                    fresh.op_key,
                ),
            )
            if validate is not None:
                validate(prepared)
        self._crash.maybe_crash(CRASH_AFTER_PREPARED)
        return prepared

    def commit(self, prepared: PreparedOp) -> WalOutcome:
        """Steps 3-4: atomic install + COMMITTED row.

        Rechecks the live target hash immediately before rename; an intervening
        third version marks the operation ``CONFLICTED`` without overwriting
        and raises ``ConflictedError``.
        """
        target = prepared.target
        live = sha256_file(target) if target.exists() else None
        if live == prepared.after_hash:
            prepared.candidate_temp.unlink(missing_ok=True)  # content already live
        else:
            if live != prepared.before_hash:
                self._mark_conflicted(prepared.op_key)
                _cleanup_temps(target)
                raise ConflictedError(
                    f"target {target} changed underneath operation {prepared.op_key}"
                )
            if not prepared.candidate_temp.exists():
                _write_file_fsync(prepared.candidate_temp, self._blobs.get(prepared.candidate_blob))
            os.rename(prepared.candidate_temp, target)
        self._crash.maybe_crash(CRASH_AFTER_INSTALL)
        _fsync_file(target)
        _fsync_dir(target.parent)
        self._crash.maybe_crash(CRASH_AFTER_DIR_FSYNC)
        self._record_committed(prepared.op_key, prepared.intended_outcome)
        self._crash.maybe_crash(CRASH_AFTER_COMMITTED)
        _cleanup_temps(target)
        return WalOutcome(
            op_key=prepared.op_key,
            action="committed",
            state=OperationState.COMMITTED,
            response=prepared.intended_outcome,
            after_hash=prepared.after_hash,
        )

    def execute(
        self,
        fresh: Fresh,
        target: Path,
        candidate: bytes,
        *,
        intended_outcome: str,
        validate: Callable[[PreparedOp], None] | None = None,
    ) -> WalOutcome:
        """Convenience: prepare then commit."""
        return self.commit(
            self.prepare(
                fresh, target, candidate, intended_outcome=intended_outcome, validate=validate
            )
        )

    def publish(
        self,
        fresh: Fresh,
        pointer_name: str,
        expected_pointer_hash: str | None,
        bundle_hash: str,
        *,
        intended_outcome: str,
        validate: Callable[[PublishOp], None] | None = None,
    ) -> WalOutcome:
        """Pointer-CAS publication of an already-stored bundle blob."""
        if not self._blobs.has(bundle_hash):
            raise NotFoundError(f"bundle blob {bundle_hash} is not durably stored")
        self._require_skeleton(fresh.op_key)
        op = PublishOp(
            op_key=fresh.op_key,
            pointer_name=pointer_name,
            expected_pointer_hash=expected_pointer_hash,
            bundle_hash=bundle_hash,
            intended_outcome=intended_outcome,
        )
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE operations SET target_path = ?, before_hash = ?, after_hash = ?, "
                "candidate_blob = ?, intended_outcome = ? WHERE op_key = ? AND state = 'PREPARED'",
                (
                    POINTER_TARGET_PREFIX + pointer_name,
                    expected_pointer_hash,
                    bundle_hash,
                    bundle_hash,
                    intended_outcome,
                    fresh.op_key,
                ),
            )
            if validate is not None:
                validate(op)
        self._crash.maybe_crash(CRASH_PUBLISH_AFTER_PREPARED)
        try:
            self._blobs.cas_swap(pointer_name, expected_pointer_hash, bundle_hash)
        except ConflictedError:
            self._mark_conflicted(fresh.op_key)
            raise
        self._crash.maybe_crash(CRASH_PUBLISH_AFTER_SWAP)
        self._record_committed(fresh.op_key, intended_outcome)
        self._crash.maybe_crash(CRASH_PUBLISH_AFTER_COMMITTED)
        return WalOutcome(
            op_key=fresh.op_key,
            action="committed",
            state=OperationState.COMMITTED,
            response=intended_outcome,
            after_hash=bundle_hash,
        )

    def recover(self, op_key: str) -> WalOutcome:
        """Resolve one operation after crash/retry (see module contract)."""
        row = self._db.conn.execute(
            "SELECT * FROM operations WHERE op_key = ?", (op_key,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"operation {op_key} not found")
        state = OperationState(str(row["state"]))
        raw_target = row["target_path"]
        if raw_target is not None and not str(raw_target).startswith(POINTER_TARGET_PREFIX):
            resolved_temps = Path(str(raw_target))
        else:
            resolved_temps = None
        if state is OperationState.COMMITTED:
            if resolved_temps is not None:
                _cleanup_temps(resolved_temps)
            response = row["response"]
            after = row["after_hash"]
            return WalOutcome(
                op_key=op_key,
                action="replayed",
                state=state,
                response=None if response is None else str(response),
                after_hash=None if after is None else str(after),
            )
        if state is OperationState.CONFLICTED:
            if resolved_temps is not None:
                _cleanup_temps(resolved_temps)
            return WalOutcome(
                op_key=op_key, action="conflicted", state=state, response=None, after_hash=None
            )
        if row["target_path"] is None:
            self._abort_skeleton(op_key)
            return WalOutcome(
                op_key=op_key, action="aborted", state=None, response=None, after_hash=None
            )
        target_path = str(row["target_path"])
        if target_path.startswith(POINTER_TARGET_PREFIX):
            return self._recover_pointer(op_key, row, target_path)
        return self._recover_file(op_key, row, target_path)

    def recover_all(self) -> tuple[WalOutcome, ...]:
        """Startup recovery: resolve every PREPARED operation."""
        rows = self._db.conn.execute(
            "SELECT op_key FROM operations WHERE state = 'PREPARED' ORDER BY created_at, op_key"
        ).fetchall()
        return tuple(self.recover(str(row["op_key"])) for row in rows)

    def _recover_file(self, op_key: str, row: sqlite3.Row, target_path: str) -> WalOutcome:
        target = Path(target_path)
        before = None if row["before_hash"] is None else str(row["before_hash"])
        after = str(row["after_hash"])
        candidate_blob = str(row["candidate_blob"])
        raw_intended = row["intended_outcome"]
        intended = "" if raw_intended is None else str(raw_intended)
        with self._locks.lock(target_path):
            live = sha256_file(target) if target.exists() else None
            if live == after:
                action: Action = "completed"
                _fsync_file(target)
                _fsync_dir(target.parent)
            elif live == before:
                target.parent.mkdir(parents=True, exist_ok=True)
                temp = _temp_path(target, after)
                _write_file_fsync(temp, self._blobs.get(candidate_blob))
                _fsync_dir(target.parent)
                os.rename(temp, target)
                _fsync_file(target)
                _fsync_dir(target.parent)
                action = "reapplied"
            else:
                self._mark_conflicted(op_key)
                _cleanup_temps(target)
                return WalOutcome(
                    op_key=op_key,
                    action="conflicted",
                    state=OperationState.CONFLICTED,
                    response=None,
                    after_hash=None,
                )
            self._record_committed(op_key, intended)
            _cleanup_temps(target)
            return WalOutcome(
                op_key=op_key,
                action=action,
                state=OperationState.COMMITTED,
                response=intended,
                after_hash=after,
            )

    def _recover_pointer(self, op_key: str, row: sqlite3.Row, target_path: str) -> WalOutcome:
        name = target_path[len(POINTER_TARGET_PREFIX) :]
        before = None if row["before_hash"] is None else str(row["before_hash"])
        after = str(row["after_hash"])
        raw_intended = row["intended_outcome"]
        intended = "" if raw_intended is None else str(raw_intended)
        with self._locks.lock(target_path):
            current = self._blobs.read_pointer(name)
            if current == after:
                action: Action = "completed"
            elif current == before:
                self._blobs.cas_swap(name, before, after)
                action = "reapplied"
            else:
                self._mark_conflicted(op_key)
                return WalOutcome(
                    op_key=op_key,
                    action="conflicted",
                    state=OperationState.CONFLICTED,
                    response=None,
                    after_hash=None,
                )
            self._record_committed(op_key, intended)
            return WalOutcome(
                op_key=op_key,
                action=action,
                state=OperationState.COMMITTED,
                response=intended,
                after_hash=after,
            )

    def _require_skeleton(self, op_key: str) -> None:
        row = self._db.conn.execute(
            "SELECT state, target_path FROM operations WHERE op_key = ?", (op_key,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"operation {op_key} not registered; call begin() first")
        if str(row["state"]) != "PREPARED" or row["target_path"] is not None:
            raise ConflictedError(
                f"operation {op_key} is not a fresh registration; recover or replay it"
            )

    def _record_committed(self, op_key: str, response: str) -> None:
        with self._db.transaction() as conn:
            cur = conn.execute(
                "UPDATE operations SET state = 'COMMITTED', response = ?, committed_at = ? "
                "WHERE op_key = ? AND state = 'PREPARED'",
                (response, self._clock.now(), op_key),
            )
            if cur.rowcount != 1:
                raise ConflictedError(f"operation {op_key} is no longer PREPARED")

    def _mark_conflicted(self, op_key: str) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE operations SET state = 'CONFLICTED' "
                "WHERE op_key = ? AND state = 'PREPARED'",
                (op_key,),
            )

    def _abort_skeleton(self, op_key: str) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "DELETE FROM operations WHERE op_key = ? AND state = 'PREPARED' "
                "AND target_path IS NULL",
                (op_key,),
            )
