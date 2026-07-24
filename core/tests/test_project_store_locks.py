"""Lock tests: canonical total order, violation asserts, no-inversion race."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from hephaestus.core.checks.engine import LOCK_REF as ENGINE_LOCK_REF
from hephaestus.core.project_store.layout import open_store
from hephaestus.core.project_store.locks import (
    CHECK_SET_LOCK,
    PROJECT_CONFIG_LOCK,
    LockManager,
    lock_rank,
    ordered,
    part_lock,
)
from hephaestus.core.project_store.projections import Projections
from test_project_store_helpers import make_project

from opstore import LeaseHeldError, OpStore


@pytest.fixture
def store(tmp_path: Path) -> Iterator[OpStore]:
    layout = make_project(tmp_path / "proj")
    opstore = open_store(layout)
    yield opstore
    opstore.close()


class TestOrder:
    def test_canonical_ranks(self) -> None:
        ranks = [
            lock_rank(PROJECT_CONFIG_LOCK),
            lock_rank(CHECK_SET_LOCK),
            lock_rank(part_lock("alpha")),
            lock_rank(part_lock("beta")),
        ]
        assert ranks == sorted(ranks)
        assert len(set(ranks)) == 4

    def test_check_set_lock_is_the_engine_lease_ref(self) -> None:
        # CheckSet (checks engine) and LockManager must contend on one ref.
        assert CHECK_SET_LOCK == ENGINE_LOCK_REF

    def test_unknown_ref_rejected(self) -> None:
        with pytest.raises(ValueError, match="canonical lock order"):
            lock_rank("some-other-lock")

    def test_ordered_sorts_canonically(self) -> None:
        refs = [part_lock("b"), PROJECT_CONFIG_LOCK, part_lock("a"), CHECK_SET_LOCK]
        assert ordered(refs) == (
            PROJECT_CONFIG_LOCK,
            CHECK_SET_LOCK,
            part_lock("a"),
            part_lock("b"),
        )

    def test_ordered_rejects_duplicates(self) -> None:
        with pytest.raises(AssertionError, match="duplicate"):
            ordered([part_lock("a"), part_lock("a")])


class TestLockManager:
    def test_in_order_acquisition(self, store: OpStore) -> None:
        manager = LockManager(store)
        manager.acquire(PROJECT_CONFIG_LOCK)
        manager.acquire(CHECK_SET_LOCK)
        manager.acquire(part_lock("alpha"))
        manager.acquire(part_lock("beta"))
        assert manager.held() == (
            PROJECT_CONFIG_LOCK,
            CHECK_SET_LOCK,
            part_lock("alpha"),
            part_lock("beta"),
        )
        assert manager.holds(part_lock("alpha"))
        manager.release_all()
        assert manager.held() == ()

    @pytest.mark.parametrize(
        ("first", "second"),
        [
            (part_lock("alpha"), PROJECT_CONFIG_LOCK),  # part before project-config
            (part_lock("alpha"), CHECK_SET_LOCK),  # part before check-set
            (CHECK_SET_LOCK, PROJECT_CONFIG_LOCK),  # check-set before project-config
            (part_lock("beta"), part_lock("alpha")),  # parts out of lexical order
            (PROJECT_CONFIG_LOCK, PROJECT_CONFIG_LOCK),  # re-acquiring the same lock
        ],
    )
    def test_out_of_order_acquisition_asserts(
        self, store: OpStore, first: str, second: str
    ) -> None:
        manager = LockManager(store)
        manager.acquire(first)
        with pytest.raises(AssertionError, match="lock order violation"):
            manager.acquire(second)
        # The violating acquisition never waited nor took the lease.
        assert manager.held() == (first,)
        manager.release_all()

    def test_release_unheld_asserts(self, store: OpStore) -> None:
        manager = LockManager(store)
        with pytest.raises(AssertionError, match="not held"):
            manager.release(PROJECT_CONFIG_LOCK)

    def test_cross_manager_exclusion(self, store: OpStore) -> None:
        holder = LockManager(store)
        holder.acquire(part_lock("alpha"))
        contender = LockManager(store, timeout_s=0.05)
        with pytest.raises(LeaseHeldError):
            contender.acquire(part_lock("alpha"))
        holder.release_all()
        contender.acquire(part_lock("alpha"))  # free again
        contender.release_all()

    def test_holding_context_sorts_and_releases(self, store: OpStore) -> None:
        manager = LockManager(store)
        with manager.holding(part_lock("b"), PROJECT_CONFIG_LOCK, part_lock("a")):
            assert manager.held() == (
                PROJECT_CONFIG_LOCK,
                part_lock("a"),
                part_lock("b"),
            )
        assert manager.held() == ()

    def test_holding_releases_on_error(self, store: OpStore) -> None:
        manager = LockManager(store)
        with pytest.raises(RuntimeError), manager.holding(PROJECT_CONFIG_LOCK):
            raise RuntimeError("boom")
        assert manager.held() == ()

    def test_snapshot_release_reacquire_cycle(self, store: OpStore) -> None:
        # The §3.5 build discipline: brief snapshot hold, free during
        # geometry, reacquire in the same order for publication.
        manager = LockManager(store)
        for _ in range(3):
            with manager.holding(PROJECT_CONFIG_LOCK, part_lock("widget")):
                pass  # snapshot
            with manager.holding(PROJECT_CONFIG_LOCK, part_lock("widget")):
                pass  # publication
        assert manager.held() == ()


class TestNoInversionRace:
    def test_param_edit_vs_build_completes_without_deadlock(self, tmp_path: Path) -> None:
        """Two clients follow the canonical order concurrently: no inversion.

        Thread A repeatedly advances the project-param state (project-config
        lock, then affected part locks). Thread B repeatedly runs the build
        lock cycle (project-config + part for snapshot, release, reacquire
        for publication). Both must complete: with a consistent total order
        there is no hold-and-wait cycle.
        """
        layout = make_project(tmp_path / "proj")
        seed_store = open_store(layout)
        seed_locks = LockManager(seed_store)
        seed_projections = Projections(seed_store, locks=seed_locks)
        with seed_locks.holding(PROJECT_CONFIG_LOCK, part_lock("widget")):
            seed_projections.record_current(
                "widget",
                consumed={"t": 0},
                artifact_ref="artifact:build:sha256:" + "0" * 64,
            )
        seed_store.close()

        errors: list[BaseException] = []
        iterations = 12

        def edit_params() -> None:
            store = open_store(layout)
            try:
                projections = Projections(store, locks=LockManager(store, timeout_s=60.0))
                for i in range(iterations):
                    # Changes the consumed value -> marks 'widget' stale,
                    # taking project-config then the part lock.
                    projections.apply_hc_state({"t": i + 1})
            except BaseException as exc:
                errors.append(exc)
            finally:
                store.close()

        def build_cycle() -> None:
            store = open_store(layout)
            try:
                manager = LockManager(store, timeout_s=60.0)
                for _ in range(iterations):
                    with manager.holding(PROJECT_CONFIG_LOCK, part_lock("widget")):
                        pass  # snapshot
                    with manager.holding(PROJECT_CONFIG_LOCK, part_lock("widget")):
                        pass  # publication
            except BaseException as exc:
                errors.append(exc)
            finally:
                store.close()

        threads = [
            threading.Thread(target=edit_params, name="param-editor"),
            threading.Thread(target=build_cycle, name="builder"),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=120.0)
        assert not any(thread.is_alive() for thread in threads), "deadlocked"
        assert errors == []

        verify_store = open_store(layout)
        state = Projections(verify_store, locks=LockManager(verify_store)).state()
        assert state.audit_revision == iterations
        assert state.stale == {"widget": "project constants changed: t"}
        verify_store.close()
