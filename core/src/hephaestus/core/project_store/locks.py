"""Canonical project lock order over opstore leases (architecture §3.5).

The global total order is **project-config → check-set → lexical part
locks**; no code may wait for an earlier lock while holding a later one.
:class:`LockManager` provides advisory cross-process locks as exclusive
opstore leases and *enforces acquisition order in-process*: acquiring a lock
that does not rank strictly after every currently-held lock raises
``AssertionError`` immediately (a programming error, never a runtime wait).

The check-set lock ref is shared with :mod:`hephaestus.core.checks.engine`
(``CheckSet`` acquires the same lease ref internally), so cooperative mutual
exclusion holds across both implementations. Builds acquire project-config +
target-part locks briefly to capture a snapshot, release both during geometry
computation, then reacquire them in the same order for publication — that
usage lives in :mod:`hephaestus.core.project_store.publication`.
"""

from __future__ import annotations

import itertools
import time
from collections.abc import Generator, Iterable
from contextlib import contextmanager

from hephaestus.core.checks.engine import LOCK_REF as CHECK_SET_LOCK
from opstore.types import OwnerId

from opstore import LeaseHeldError, OpStore, current_owner

__all__ = [
    "CHECK_SET_LOCK",
    "PART_LOCK_PREFIX",
    "PROJECT_CONFIG_LOCK",
    "LockManager",
    "lock_rank",
    "ordered",
    "part_lock",
]

#: Lease ref of the project-config lock (first in the canonical order).
PROJECT_CONFIG_LOCK = "project-config-lock"
#: Lease ref prefix of per-part advisory locks (last, ordered lexically).
PART_LOCK_PREFIX = "part-lock:"


def part_lock(part: str) -> str:
    """The lease ref of one part's advisory lock."""
    return PART_LOCK_PREFIX + part


def lock_rank(ref: str) -> tuple[int, str]:
    """Position of ``ref`` in the canonical total order (sortable key).

    Unknown refs are rejected — every lock this package waits on must have a
    defined place in the order, or the no-inversion guarantee is vacuous.
    """
    if ref == PROJECT_CONFIG_LOCK:
        return (0, "")
    if ref == CHECK_SET_LOCK:
        return (1, "")
    if ref.startswith(PART_LOCK_PREFIX):
        return (2, ref[len(PART_LOCK_PREFIX) :])
    raise ValueError(f"lock ref {ref!r} has no place in the canonical lock order")


def ordered(refs: Iterable[str]) -> tuple[str, ...]:
    """``refs`` sorted into canonical acquisition order; duplicates are rejected."""
    seq = sorted(refs, key=lock_rank)
    for earlier, later in itertools.pairwise(seq):
        if lock_rank(earlier) == lock_rank(later):
            raise AssertionError(f"duplicate lock ref in acquisition set: {later!r}")
    return tuple(seq)


class LockManager:
    """Ordered advisory locks for one client, backed by exclusive opstore leases.

    One instance tracks the locks *this* client holds and asserts the
    canonical order on every acquisition. Cross-process exclusion comes from
    the opstore lease table; liveness-checked expiry reclaims leases of dead
    holders. ``timeout_s`` bounds how long an acquisition polls a held lease.
    """

    def __init__(
        self,
        store: OpStore,
        *,
        owner: OwnerId | None = None,
        lease_ttl_s: float = 60.0,
        timeout_s: float = 30.0,
    ) -> None:
        self._store = store
        self._owner = owner or current_owner()
        self._lease_ttl_s = lease_ttl_s
        self._timeout_s = timeout_s
        self._held: dict[str, str] = {}  # ref -> lease_id, in acquisition order

    def held(self) -> tuple[str, ...]:
        """Currently-held lock refs in acquisition order."""
        return tuple(self._held)

    def holds(self, ref: str) -> bool:
        """True iff this manager currently holds ``ref``."""
        return ref in self._held

    def acquire(self, ref: str) -> None:
        """Acquire ``ref``, waiting for other holders up to ``timeout_s``.

        Raises ``AssertionError`` on a lock-order violation (waiting for an
        earlier lock while holding a later or equal one) — that is a
        programming error and never waits. Raises ``LeaseHeldError`` when the
        holder stays live past the timeout.
        """
        rank = lock_rank(ref)
        for held_ref in self._held:
            if lock_rank(held_ref) >= rank:
                raise AssertionError(
                    f"lock order violation: acquiring {ref!r} while holding {held_ref!r} "
                    "(canonical order: project-config -> check-set -> lexical part locks)"
                )
        deadline = time.monotonic() + self._timeout_s
        while True:
            try:
                lease = self._store.leases.acquire_exclusive(ref, self._owner, self._lease_ttl_s)
            except LeaseHeldError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.005)
            else:
                self._held[ref] = lease.lease_id
                return

    def release(self, ref: str) -> None:
        """Release a held lock; releasing an unheld ref is an ``AssertionError``."""
        lease_id = self._held.pop(ref, None)
        if lease_id is None:
            raise AssertionError(f"releasing lock {ref!r} that is not held")
        self._store.leases.release(lease_id)

    def release_all(self) -> None:
        """Release every held lock in reverse acquisition order."""
        for ref in reversed(list(self._held)):
            self.release(ref)

    @contextmanager
    def holding(self, *refs: str) -> Generator[None]:
        """Acquire ``refs`` in canonical order, yield, release in reverse order."""
        seq = ordered(refs)
        acquired: list[str] = []
        try:
            for ref in seq:
                self.acquire(ref)
                acquired.append(ref)
            yield
        finally:
            for ref in reversed(acquired):
                self.release(ref)
