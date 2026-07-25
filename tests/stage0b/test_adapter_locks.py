"""G0B adapter clause: canonical lock ordering, including no-inversion races.

Architecture §3.5: the global total order is project-config -> check-set ->
lexical part locks; no code may wait for an earlier lock while holding a
later one. Order violations are immediate programming errors (never waits),
cross-client exclusion comes from opstore leases, and concurrent writers all
acquiring in canonical order can never deadlock.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from _adapter_helpers import make_project
from hephaestus.core.project_store.layout import ProjectLayout, open_store
from hephaestus.core.project_store.locks import (
    CHECK_SET_LOCK,
    PROJECT_CONFIG_LOCK,
    LockManager,
    lock_rank,
    ordered,
    part_lock,
)
from opstore.types import OwnerId

from opstore import LeaseHeldError, OpStore


@pytest.fixture
def layout(tmp_path: Path) -> ProjectLayout:
    return make_project(tmp_path / "proj")


@pytest.fixture
def store(layout: ProjectLayout) -> Iterator[OpStore]:
    handle = open_store(layout)
    yield handle
    handle.close()


def _owner(n: int) -> OwnerId:
    # Distinct live owners for in-process contention tests: our own pid keeps
    # liveness true, distinct start_ns keeps the owners distinct.
    import os

    return OwnerId(pid=os.getpid(), pid_start_ns=1000 + n)


class TestCanonicalOrder:
    def test_total_order_is_project_config_then_check_set_then_lexical_parts(self) -> None:
        refs = [
            part_lock("bracket"),
            CHECK_SET_LOCK,
            part_lock("axle"),
            PROJECT_CONFIG_LOCK,
            part_lock("widget"),
        ]
        assert ordered(refs) == (
            PROJECT_CONFIG_LOCK,
            CHECK_SET_LOCK,
            part_lock("axle"),
            part_lock("bracket"),
            part_lock("widget"),
        )

    def test_ranks_are_strictly_increasing_along_the_order(self) -> None:
        seq = [PROJECT_CONFIG_LOCK, CHECK_SET_LOCK, part_lock("a"), part_lock("b")]
        ranks = [lock_rank(ref) for ref in seq]
        assert ranks == sorted(ranks)
        assert len(set(ranks)) == len(ranks)

    def test_unknown_lock_ref_has_no_place_in_the_order(self) -> None:
        with pytest.raises(ValueError, match="canonical lock order"):
            lock_rank("mystery-lock")

    def test_duplicate_acquisition_set_rejected(self) -> None:
        with pytest.raises(AssertionError):
            ordered([part_lock("widget"), part_lock("widget")])


class TestInversionIsImmediateError:
    """Waiting for an earlier lock while holding a later one must never happen."""

    @pytest.mark.parametrize(
        ("first", "second"),
        [
            (CHECK_SET_LOCK, PROJECT_CONFIG_LOCK),
            (part_lock("widget"), PROJECT_CONFIG_LOCK),
            (part_lock("widget"), CHECK_SET_LOCK),
            (part_lock("b"), part_lock("a")),  # non-lexical part order
            (part_lock("widget"), part_lock("widget")),  # equal rank re-entry
        ],
    )
    def test_out_of_order_acquisition_raises_without_waiting(
        self, store: OpStore, first: str, second: str
    ) -> None:
        manager = LockManager(store)
        manager.acquire(first)
        try:
            with pytest.raises(AssertionError, match="lock order violation"):
                manager.acquire(second)
        finally:
            manager.release_all()

    def test_canonical_direction_is_permitted(self, store: OpStore) -> None:
        manager = LockManager(store)
        with manager.holding(PROJECT_CONFIG_LOCK, CHECK_SET_LOCK, part_lock("widget")):
            assert manager.held() == (
                PROJECT_CONFIG_LOCK,
                CHECK_SET_LOCK,
                part_lock("widget"),
            )
        assert manager.held() == ()


class TestCrossClientExclusion:
    def test_second_client_blocks_until_timeout_while_first_holds(self, store: OpStore) -> None:
        holder = LockManager(store, owner=_owner(1))
        contender = LockManager(store, owner=_owner(2), timeout_s=0.2)
        holder.acquire(PROJECT_CONFIG_LOCK)
        try:
            with pytest.raises(LeaseHeldError):
                contender.acquire(PROJECT_CONFIG_LOCK)
        finally:
            holder.release_all()

    def test_release_hands_the_lock_to_the_contender(
        self, layout: ProjectLayout, store: OpStore
    ) -> None:
        # One OpStore handle wraps one SQLite connection and is not thread-safe;
        # the releasing thread must use its own handle on the shared store root.
        holder_store = open_store(layout)
        holder = LockManager(holder_store, owner=_owner(1))
        contender = LockManager(store, owner=_owner(2), timeout_s=5.0)
        holder.acquire(part_lock("widget"))
        release_timer = threading.Timer(0.05, holder.release_all)
        release_timer.start()
        try:
            contender.acquire(part_lock("widget"))  # must succeed once released
            assert contender.holds(part_lock("widget"))
        finally:
            release_timer.cancel()
            contender.release_all()
            holder_store.close()


class TestNoInversionRace:
    """Concurrent writers acquiring in canonical order never deadlock.

    Every worker repeatedly takes overlapping multi-lock sets (project-config,
    check-set, several part locks) through ``holding`` — since all follow the
    canonical order, the run must complete; a deadlock trips the join timeout.
    """

    WORKERS = 4
    ITERATIONS = 12

    def test_contended_multi_lock_workload_completes(
        self, layout: ProjectLayout, store: OpStore
    ) -> None:
        parts = ("axle", "bracket", "widget")
        errors: list[BaseException] = []
        barrier = threading.Barrier(self.WORKERS)

        def worker(n: int) -> None:
            # Each client opens its own store handle on the shared root —
            # cross-client exclusion comes from the lease table, exactly as
            # it would across processes.
            client = open_store(layout)
            manager = LockManager(client, owner=_owner(n), timeout_s=30.0)
            barrier.wait()
            try:
                for i in range(self.ITERATIONS):
                    # Rotate through overlapping lock sets in all rank classes.
                    picked = parts[(n + i) % 3], parts[(n + i + 1) % 3]
                    with manager.holding(
                        PROJECT_CONFIG_LOCK,
                        CHECK_SET_LOCK,
                        part_lock(picked[0]),
                        part_lock(picked[1]),
                    ):
                        assert list(manager.held()) == sorted(manager.held(), key=lock_rank)
            except BaseException as exc:
                errors.append(exc)
            finally:
                client.close()

        threads = [
            threading.Thread(target=worker, args=(n,), name=f"locker-{n}")
            for n in range(self.WORKERS)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60.0)
        assert not any(thread.is_alive() for thread in threads), (
            "lock workload deadlocked (thread still alive after 60s)"
        )
        assert errors == []
        # Every lease is released at the end.
        for ref in (PROJECT_CONFIG_LOCK, CHECK_SET_LOCK, *map(part_lock, parts)):
            assert store.leases.holders(ref) == []
