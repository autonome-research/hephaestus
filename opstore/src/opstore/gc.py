"""Pins, reachability links, retention/quota accounting, and blob garbage collection.

Contract (DESIGN.md "gc.py" + architecture.md §3.5 "Artifact lifecycle"):

- Reachability = ``pins`` union caller-protected roots (injected callback),
  **transitive over ``links``** (pinning A with A→B→C retains B and C).
- ``collect(dry_run=...)``: candidates are unreachable blobs older than their
  retention-class horizon (``default`` 30 d, ``preview`` 7 d, from
  ``StoreConfig``). Per real candidate: exclusive deletion lease → fresh
  reachability **recheck** → unlink file → delete accounting row → release.
  Dry-run explains every candidate and deletes nothing. The report explains
  each candidate either way.
- Deletion leases follow the leases-table semantics: an exclusive lease is
  acquirable only when no live holder exists; a holder past its heartbeat TTL
  is reclaimable only once ``Liveness.is_alive(owner)`` is false. Readers
  holding a shared lease on a ref therefore block unlink; a reader arriving
  after deletion observes ``artifact_expired``, never partial bytes.
- Soft quota: if protected+pinned (reachable) bytes alone exceed
  ``config.quota_bytes``, ``admission_guard()`` raises
  ``ProtectedQuotaExceededError`` so new artifact-producing work fails before
  execution. Nothing protected is ever deleted.
- Outcome/tombstone horizons run here too: ``purge_hooks`` (e.g.
  ``opkeys.purge``) are invoked by every non-dry ``collect``.
- Crash points: ``gc.collect.after_lease``, ``gc.collect.after_recheck``,
  ``gc.collect.after_unlink``, ``gc.collect.after_row_delete``. Recovery is
  re-``collect()``: the end state (no file, no row, no lease) is identical
  regardless of crash point.
"""

from __future__ import annotations

import enum
import os
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from opstore.blobs import BlobStore
from opstore.db import Database
from opstore.errors import LeaseHeldError, ProtectedQuotaExceededError
from opstore.leases import LeaseManager
from opstore.types import (
    Clock,
    CrashHook,
    DefaultLiveness,
    Liveness,
    NoopCrashHook,
    OwnerId,
    StoreConfig,
    SystemClock,
    current_owner,
)

CRASH_AFTER_LEASE = "gc.collect.after_lease"
CRASH_AFTER_RECHECK = "gc.collect.after_recheck"
CRASH_AFTER_UNLINK = "gc.collect.after_unlink"
CRASH_AFTER_ROW_DELETE = "gc.collect.after_row_delete"

PREVIEW_RETENTION_CLASS = "preview"

ProtectedRoots = Callable[[], Iterable[str]]
PurgeHook = Callable[[], object]


class GcAction(enum.StrEnum):
    """Per-candidate outcome recorded in the collect report."""

    COLLECTED = "collected"
    WOULD_COLLECT = "would_collect"
    LEASE_HELD = "lease_held"
    SAVED_BY_RECHECK = "saved_by_recheck"


@dataclass(frozen=True, slots=True)
class GcCandidate:
    """One GC candidate with its explanation."""

    ref: str
    size: int
    age_s: float
    retention_class: str
    retention_s: float
    action: GcAction
    reason: str


@dataclass(frozen=True, slots=True)
class GcUsage:
    """Quota accounting snapshot."""

    total_bytes: int
    protected_bytes: int
    quota_bytes: int

    def to_json(self) -> dict[str, int]:
        """The three numbers, for a refusal payload or a CLI's ``--json``."""
        return {
            "total_bytes": self.total_bytes,
            "protected_bytes": self.protected_bytes,
            "quota_bytes": self.quota_bytes,
        }


@dataclass(frozen=True, slots=True)
class GcReport:
    """Audit report for one ``collect`` pass."""

    dry_run: bool
    candidates: tuple[GcCandidate, ...]
    reclaimed_bytes: int
    usage: GcUsage


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class Gc:
    """Reachability GC over the blobs table with deletion leases and quota accounting."""

    def __init__(
        self,
        root: Path,
        db: Database,
        config: StoreConfig | None = None,
        *,
        clock: Clock | None = None,
        liveness: Liveness | None = None,
        crash_hook: CrashHook | None = None,
        protected_roots: ProtectedRoots | None = None,
        purge_hooks: Sequence[PurgeHook] = (),
        deletion_lease_ttl_s: float = 60.0,
    ) -> None:
        self._db = db
        self._config = config or StoreConfig()
        self._clock = clock or SystemClock()
        self._liveness = liveness or DefaultLiveness()
        self._crash = crash_hook or NoopCrashHook()
        self._protected_roots: ProtectedRoots = protected_roots or (lambda: ())
        self._purge_hooks = tuple(purge_hooks)
        self._deletion_lease_ttl_s = deletion_lease_ttl_s
        self._blobs = BlobStore(root, db, clock=self._clock)
        self._leases = LeaseManager(db, clock=self._clock, liveness=self._liveness)

    # -- pins and links -----------------------------------------------------

    def pin(self, ref: str) -> None:
        """Record ``ref`` as a GC root (idempotent)."""
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO pins(ref, created_at) VALUES(?, ?) ON CONFLICT(ref) DO NOTHING",
                (ref, self._clock.now()),
            )

    def unpin(self, ref: str) -> None:
        """Remove the pin on ``ref`` (idempotent)."""
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM pins WHERE ref = ?", (ref,))

    def pins(self) -> frozenset[str]:
        """All pinned refs."""
        with self._db.reading() as conn:
            rows = conn.execute("SELECT ref FROM pins").fetchall()
        return frozenset(str(row["ref"]) for row in rows)

    def link(self, from_ref: str, to_ref: str) -> None:
        """Record a reachability edge ``from_ref → to_ref`` (idempotent)."""
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO links(from_ref, to_ref) VALUES(?, ?) "
                "ON CONFLICT(from_ref, to_ref) DO NOTHING",
                (from_ref, to_ref),
            )

    def unlink(self, from_ref: str, to_ref: str) -> None:
        """Remove a reachability edge (idempotent)."""
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM links WHERE from_ref = ? AND to_ref = ?", (from_ref, to_ref))

    def links(self) -> frozenset[tuple[str, str]]:
        """All reachability edges."""
        with self._db.reading() as conn:
            rows = conn.execute("SELECT from_ref, to_ref FROM links").fetchall()
        return frozenset((str(row["from_ref"]), str(row["to_ref"])) for row in rows)

    # -- reachability and quota --------------------------------------------

    def reachable(self) -> frozenset[str]:
        """Pins union caller-protected roots, closed transitively over links.

        One ``reading()`` over the whole closure: the pin set, the caller's
        protected roots (which read the store too) and the edge set are three
        reads that have to agree, and taking the connection lock once is what
        keeps a concurrent writer from committing between them.
        """
        with self._db.reading():
            roots = set(self.pins())
            roots.update(self._protected_roots())
            edges: dict[str, list[str]] = {}
            for from_ref, to_ref in self.links():
                edges.setdefault(from_ref, []).append(to_ref)
        seen = set(roots)
        stack = list(roots)
        while stack:
            for target in edges.get(stack.pop(), ()):
                if target not in seen:
                    seen.add(target)
                    stack.append(target)
        return frozenset(seen)

    def usage(self) -> GcUsage:
        """Quota accounting: total stored bytes and protected+pinned (reachable) bytes.

        Under one ``reading()`` because :meth:`admission_guard` compares the two
        numbers this returns, and a comparison of two numbers read either side
        of somebody else's commit is not a comparison of anything. It is also
        the read that made the lock necessary: with the guard wired into
        ``Publisher.freeze_inputs`` (INTERFACE.md §19.40) this runs on every
        build, and builds run concurrently.
        """
        with self._db.reading() as conn:
            reachable = self.reachable()
            total = 0
            protected = 0
            rows = conn.execute("SELECT hash, size FROM blobs").fetchall()
        for row in rows:
            size = int(row["size"])
            total += size
            if str(row["hash"]) in reachable:
                protected += size
        return GcUsage(
            total_bytes=total, protected_bytes=protected, quota_bytes=self._config.quota_bytes
        )

    def admission_guard(self) -> GcUsage:
        """Fail new artifact-producing work when protected bytes alone exceed the quota.

        Raises ``ProtectedQuotaExceededError`` (code ``protected_quota_exceeded``)
        when protected+pinned bytes exceed ``config.quota_bytes``; otherwise
        returns the usage snapshot.
        """
        usage = self.usage()
        if usage.protected_bytes > usage.quota_bytes:
            raise ProtectedQuotaExceededError(
                f"protected+pinned bytes {usage.protected_bytes} exceed "
                f"quota {usage.quota_bytes}; raise the quota or unpin data",
                usage=usage.to_json(),
            )
        return usage

    # -- collection ---------------------------------------------------------

    def retention_for(self, retention_class: str) -> float:
        """Retention horizon (seconds) for a blob retention class."""
        if retention_class == PREVIEW_RETENTION_CLASS:
            return self._config.preview_retention_s
        return self._config.retention_s

    def collect(self, dry_run: bool = False) -> GcReport:
        """One GC pass; returns the per-candidate audit report.

        Real passes additionally invoke the configured purge hooks (outcome /
        tombstone horizons, e.g. ``opkeys.purge``) and clean up stale deletion
        leases left behind by crashed collectors.
        """
        if not dry_run:
            for hook in self._purge_hooks:
                hook()
            self._reap_orphan_leases()
        now = self._clock.now()
        reachable = self.reachable()
        candidates: list[GcCandidate] = []
        reclaimed = 0
        with self._db.reading() as conn:
            rows = conn.execute(
                "SELECT hash, size, created_at, retention_class FROM blobs ORDER BY created_at"
            ).fetchall()
        for row in rows:
            ref = str(row["hash"])
            if ref in reachable:
                continue
            retention_class = str(row["retention_class"])
            retention_s = self.retention_for(retention_class)
            age_s = now - float(row["created_at"])
            if age_s <= retention_s:
                continue
            size = int(row["size"])
            reason = (
                f"unreachable; age {age_s:.0f}s exceeds retention {retention_s:.0f}s "
                f"(class {retention_class!r})"
            )
            if dry_run:
                action = (
                    GcAction.LEASE_HELD if self._has_live_lease(ref) else GcAction.WOULD_COLLECT
                )
            else:
                action = self._delete_candidate(ref)
                if action is GcAction.COLLECTED:
                    reclaimed += size
            candidates.append(
                GcCandidate(
                    ref=ref,
                    size=size,
                    age_s=age_s,
                    retention_class=retention_class,
                    retention_s=retention_s,
                    action=action,
                    reason=reason,
                )
            )
        return GcReport(
            dry_run=dry_run,
            candidates=tuple(candidates),
            reclaimed_bytes=reclaimed,
            usage=self.usage(),
        )

    def _delete_candidate(self, ref: str) -> GcAction:
        try:
            lease_id = self._acquire_deletion_lease(ref)
        except LeaseHeldError:
            return GcAction.LEASE_HELD
        try:
            self._crash.maybe_crash(CRASH_AFTER_LEASE)
            if ref in self.reachable():
                return GcAction.SAVED_BY_RECHECK
            self._crash.maybe_crash(CRASH_AFTER_RECHECK)
            path = self._blobs.path_for(ref)
            path.unlink(missing_ok=True)
            if path.parent.is_dir():
                _fsync_dir(path.parent)
            self._crash.maybe_crash(CRASH_AFTER_UNLINK)
            with self._db.transaction() as conn:
                conn.execute("DELETE FROM blobs WHERE hash = ?", (ref,))
            self._crash.maybe_crash(CRASH_AFTER_ROW_DELETE)
            return GcAction.COLLECTED
        finally:
            self._release_lease(lease_id)

    # -- deletion leases (leases-table semantics; see leases.py contract) ---

    def _lease_expired(self, heartbeat_at: float, ttl_s: float, now: float) -> bool:
        return now > heartbeat_at + ttl_s

    def _has_live_lease(self, ref: str) -> bool:
        return bool(self._leases.live_holders(ref))

    def _acquire_deletion_lease(self, ref: str) -> str:
        """Exclusive deletion lease on ``ref`` via leases.py (stale dead-owner rows reclaimed).

        Raises ``LeaseHeldError`` when any live shared or exclusive holder remains.
        """
        lease = self._leases.acquire_exclusive(ref, current_owner(), self._deletion_lease_ttl_s)
        return lease.lease_id

    def _release_lease(self, lease_id: str) -> None:
        self._leases.release(lease_id)

    def _reap_orphan_leases(self) -> None:
        """Drop stale leases whose ref no longer has a blob row (crashed deletions)."""
        with self._db.transaction() as conn:
            now = self._clock.now()
            rows = conn.execute(
                "SELECT lease_id, owner_pid, owner_start_ns, ttl_s, heartbeat_at "
                "FROM leases WHERE ref NOT IN (SELECT hash FROM blobs)"
            ).fetchall()
            for row in rows:
                holder = OwnerId(pid=int(row["owner_pid"]), pid_start_ns=int(row["owner_start_ns"]))
                expired = self._lease_expired(float(row["heartbeat_at"]), float(row["ttl_s"]), now)
                if expired and not self._liveness.is_alive(holder):
                    conn.execute("DELETE FROM leases WHERE lease_id = ?", (str(row["lease_id"]),))
