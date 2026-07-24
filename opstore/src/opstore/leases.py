"""Cross-process shared/exclusive leases with heartbeat and liveness-checked expiry.

Contract (DESIGN.md "leases.py" + architecture.md §3.5):

- ``acquire_shared(ref, owner, ttl_s)`` / ``acquire_exclusive(ref, owner, ttl_s)``:
  shared leases coexist; an exclusive lease requires no live shared or exclusive
  holder, and any live lease blocks a new exclusive. A conflicting live lease
  raises ``LeaseHeldError`` (code ``lease_held``).
- Expiry is liveness-checked: a lease past its heartbeat TTL is reclaimed during
  a conflicting acquisition only when ``Liveness.is_alive(owner)`` is false. A
  live owner is never reclaimed, however stale its heartbeat. ``break_stale``
  forces takeover of TTL-elapsed leases regardless of liveness and durably
  records the takeover (in ``meta`` under ``lease_takeover:<new_lease_id>``; the
  fixed schema has no dedicated audit table).
- ``heartbeat(lease_id)`` extends the lease; ``release(lease_id)`` drops it.
  A heartbeat on a reclaimed/released lease raises ``LeaseExpiredError``.
- ``artifact_expired`` path: acquisition accepts a ``ref_exists`` oracle that is
  evaluated inside the same ``BEGIN IMMEDIATE`` transaction that inserts the
  lease row; a ref gone before acquisition raises ``ArtifactExpiredError``
  (code ``artifact_expired``), so a reader either holds a lease on a present ref
  or gets the structured error — never a partial read (GC deletes only under an
  exclusive deletion lease, which the reader's shared lease blocks).
- Crash point (``CrashHook``): ``leases.acquire.after_commit`` — a crash there
  leaves a durable lease row owned by a dead process; recovery is liveness
  reclaim by the next conflicting acquisition.

All decisions happen inside single ``BEGIN IMMEDIATE`` transactions; correctness
across processes relies on SQLite, not in-process locks.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from opstore.db import Database
from opstore.errors import ArtifactExpiredError, LeaseExpiredError, LeaseHeldError
from opstore.types import (
    Clock,
    CrashHook,
    DefaultLiveness,
    JSONValue,
    LeaseMode,
    Liveness,
    NoopCrashHook,
    OwnerId,
    SystemClock,
)

CRASH_AFTER_ACQUIRE_COMMIT = "leases.acquire.after_commit"

TAKEOVER_META_PREFIX = "lease_takeover:"


@dataclass(frozen=True, slots=True)
class Lease:
    """A held (or observed) lease row."""

    lease_id: str
    ref: str
    mode: LeaseMode
    owner: OwnerId
    ttl_s: float
    heartbeat_at: float
    created_at: float

    def expires_at(self) -> float:
        return self.heartbeat_at + self.ttl_s


def _row_to_lease(row: sqlite3.Row) -> Lease:
    return Lease(
        lease_id=str(row["lease_id"]),
        ref=str(row["ref"]),
        mode=LeaseMode(str(row["mode"])),
        owner=OwnerId(pid=int(row["owner_pid"]), pid_start_ns=int(row["owner_start_ns"])),
        ttl_s=float(row["ttl_s"]),
        heartbeat_at=float(row["heartbeat_at"]),
        created_at=float(row["created_at"]),
    )


class LeaseManager:
    """Shared/exclusive cross-process leases recorded in ``state.db``."""

    def __init__(
        self,
        db: Database,
        clock: Clock | None = None,
        liveness: Liveness | None = None,
        crash_hook: CrashHook | None = None,
    ) -> None:
        self._db = db
        self._clock = clock or SystemClock()
        self._liveness = liveness or DefaultLiveness()
        self._crash = crash_hook or NoopCrashHook()

    def acquire_shared(
        self,
        ref: str,
        owner: OwnerId,
        ttl_s: float,
        *,
        ref_exists: Callable[[str], bool] | None = None,
    ) -> Lease:
        """Acquire a shared lease; blocked only by a live exclusive lease."""
        return self._acquire(ref, LeaseMode.SHARED, owner, ttl_s, ref_exists, force_stale=False)

    def acquire_exclusive(
        self,
        ref: str,
        owner: OwnerId,
        ttl_s: float,
        *,
        ref_exists: Callable[[str], bool] | None = None,
    ) -> Lease:
        """Acquire an exclusive lease; blocked by any live shared or exclusive lease."""
        return self._acquire(ref, LeaseMode.EXCLUSIVE, owner, ttl_s, ref_exists, force_stale=False)

    def break_stale(
        self,
        ref: str,
        mode: LeaseMode,
        owner: OwnerId,
        ttl_s: float,
        *,
        ref_exists: Callable[[str], bool] | None = None,
    ) -> Lease:
        """Acquire, forcibly reclaiming TTL-elapsed conflicting leases (liveness ignored).

        Leases within their heartbeat TTL still block. Broken leases are recorded
        durably as a takeover record readable via ``takeover_record``.
        """
        return self._acquire(ref, mode, owner, ttl_s, ref_exists, force_stale=True)

    def heartbeat(self, lease_id: str) -> Lease:
        """Extend the lease's TTL window from now; ``LeaseExpiredError`` if gone."""
        now = self._clock.now()
        with self._db.transaction() as conn:
            cursor = conn.execute(
                "UPDATE leases SET heartbeat_at = ? WHERE lease_id = ?", (now, lease_id)
            )
            if cursor.rowcount == 0:
                raise LeaseExpiredError(
                    f"lease {lease_id} no longer exists (released or reclaimed)"
                )
            row = conn.execute("SELECT * FROM leases WHERE lease_id = ?", (lease_id,)).fetchone()
        return _row_to_lease(row)

    def release(self, lease_id: str) -> bool:
        """Drop the lease. Returns False if it was already released or reclaimed."""
        with self._db.transaction() as conn:
            cursor = conn.execute("DELETE FROM leases WHERE lease_id = ?", (lease_id,))
        return cursor.rowcount > 0

    def get(self, lease_id: str) -> Lease | None:
        """The lease row if it still exists (regardless of expiry), else None."""
        row = self._db.conn.execute(
            "SELECT * FROM leases WHERE lease_id = ?", (lease_id,)
        ).fetchone()
        return None if row is None else _row_to_lease(row)

    def holders(self, ref: str) -> list[Lease]:
        """All lease rows on ``ref`` (including expired-but-unreclaimed ones)."""
        rows = self._db.conn.execute(
            "SELECT * FROM leases WHERE ref = ? ORDER BY created_at, lease_id", (ref,)
        ).fetchall()
        return [_row_to_lease(row) for row in rows]

    def live_holders(self, ref: str) -> list[Lease]:
        """Lease rows on ``ref`` that currently block a conflicting acquisition."""
        now = self._clock.now()
        return [
            lease
            for lease in self.holders(ref)
            if lease.expires_at() >= now or self._liveness.is_alive(lease.owner)
        ]

    def takeover_record(self, lease_id: str) -> JSONValue | None:
        """The recorded takeover for a lease acquired via ``break_stale``, if any."""
        row = self._db.conn.execute(
            "SELECT value FROM meta WHERE key = ?", (TAKEOVER_META_PREFIX + lease_id,)
        ).fetchone()
        return None if row is None else cast(JSONValue, json.loads(str(row["value"])))

    def _acquire(
        self,
        ref: str,
        mode: LeaseMode,
        owner: OwnerId,
        ttl_s: float,
        ref_exists: Callable[[str], bool] | None,
        force_stale: bool,
    ) -> Lease:
        if ttl_s < 0:
            raise ValueError(f"ttl_s must be non-negative, got {ttl_s}")
        now = self._clock.now()
        lease_id = uuid.uuid4().hex
        with self._db.transaction() as conn:
            if ref_exists is not None and not ref_exists(ref):
                raise ArtifactExpiredError(f"ref {ref!r} is gone; cannot acquire {mode} lease")
            rows = conn.execute("SELECT * FROM leases WHERE ref = ?", (ref,)).fetchall()
            reclaimed: list[Lease] = []
            for row in rows:
                held = _row_to_lease(row)
                conflicts = mode is LeaseMode.EXCLUSIVE or held.mode is LeaseMode.EXCLUSIVE
                if not conflicts:
                    continue
                if held.expires_at() >= now:
                    raise LeaseHeldError(
                        f"{held.mode} lease {held.lease_id} on {ref!r} is live "
                        f"(heartbeat within TTL); cannot acquire {mode}"
                    )
                if not force_stale and self._liveness.is_alive(held.owner):
                    raise LeaseHeldError(
                        f"{held.mode} lease {held.lease_id} on {ref!r} is past TTL but its "
                        f"owner pid {held.owner.pid} is alive; not reclaiming"
                    )
                reclaimed.append(held)
            for held in reclaimed:
                conn.execute("DELETE FROM leases WHERE lease_id = ?", (held.lease_id,))
            conn.execute(
                "INSERT INTO leases(lease_id, ref, mode, owner_pid, owner_start_ns, "
                "ttl_s, heartbeat_at, created_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                (lease_id, ref, str(mode), owner.pid, owner.pid_start_ns, ttl_s, now, now),
            )
            if force_stale and reclaimed:
                record: JSONValue = {
                    "ref": ref,
                    "mode": str(mode),
                    "taker_pid": owner.pid,
                    "taker_start_ns": owner.pid_start_ns,
                    "at": now,
                    "broken": [
                        {
                            "lease_id": held.lease_id,
                            "mode": str(held.mode),
                            "owner_pid": held.owner.pid,
                            "owner_start_ns": held.owner.pid_start_ns,
                            "heartbeat_at": held.heartbeat_at,
                            "ttl_s": held.ttl_s,
                        }
                        for held in reclaimed
                    ],
                }
                conn.execute(
                    "INSERT INTO meta(key, value) VALUES(?, ?)",
                    (TAKEOVER_META_PREFIX + lease_id, json.dumps(record, sort_keys=True)),
                )
        self._crash.maybe_crash(CRASH_AFTER_ACQUIRE_COMMIT)
        return Lease(
            lease_id=lease_id,
            ref=ref,
            mode=mode,
            owner=owner,
            ttl_s=ttl_s,
            heartbeat_at=now,
            created_at=now,
        )
