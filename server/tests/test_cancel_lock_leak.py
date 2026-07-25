"""Regression: a run cancelled mid-build must never leak the project-config lock.

The bench failure (enclosure-bosses-s3): the budget guard cancels a run from a
separate thread (``BridgeRuntime.cancel`` -> ``admission.request_cancel``) while
the supervisor reader thread is inside ``build_part`` on the SAME opstore
connection. Without in-process transaction serialization, the cancel thread's
COMMIT committed the build thread's half-open lease-acquire transaction (the
lease INSERT became durable) while the acquire itself raised ``OperationalError:
cannot commit - no transaction is active`` — so the LockManager never tracked
the lease, nothing released it, and liveness reclaim rightly refused (owner pid
alive). Grading then failed with ``part_busy`` until the retries ran out.

These tests drive exactly that interleaving in-process and prove the
project-config lock is immediately reacquirable afterwards.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import pytest
from hephaestus.core.project_store.locks import PROJECT_CONFIG_LOCK, LockManager, part_lock
from hephaestus.testing.tools_fixture import Project, make_project

from opstore import LeaseHeldError


def _assert_project_config_lock_reacquirable(project: Project) -> None:
    """The invariant every test here ends on: no orphan lease, instant acquire."""
    assert project.store.leases.holders(PROJECT_CONFIG_LOCK) == []
    probe = LockManager(project.store, timeout_s=0.5)
    probe.acquire(PROJECT_CONFIG_LOCK)
    probe.release(PROJECT_CONFIG_LOCK)


def test_lock_cycles_survive_concurrent_admission_writes(tmp_path: Path) -> None:
    """Tight lock/unlock cycles vs. a cancel-thread hammering admission writes.

    Pre-fix this reliably corrupted the shared connection's transactions
    (interleaved BEGIN/COMMIT) and left a committed-but-untracked lease row.
    """
    project = make_project(tmp_path / "proj")
    try:
        store = project.store
        store.admission.admit("run-cancel")
        errors: list[BaseException] = []
        done = threading.Event()

        def lock_cycles() -> None:
            try:
                locks = LockManager(store, timeout_s=5.0)
                for _ in range(300):
                    with locks.holding(PROJECT_CONFIG_LOCK, part_lock("widget")):
                        pass
            except BaseException as exc:  # pragma: no cover - the regression itself
                errors.append(exc)
            finally:
                done.set()

        worker = threading.Thread(target=lock_cycles)
        worker.start()
        while not done.is_set():
            store.admission.request_cancel("run-cancel")
            time.sleep(0.0005)  # yield so the lock cycles make progress
        worker.join()
        assert errors == []
        assert store.leases.holders(part_lock("widget")) == []
        _assert_project_config_lock_reacquirable(project)
    finally:
        project.close()


def test_cancelled_run_admission_writes_mid_build_leave_lock_reacquirable(
    tmp_path: Path,
) -> None:
    """The bench shape: budget-guard cancel racing a real ``build_part`` in-process.

    The build thread freezes inputs and publishes under the project-config +
    part locks while another thread performs the cancel's admission write on the
    same store. Afterwards the project-config lock must be free immediately and
    a grading-style rebuild must not see ``part_busy``.
    """
    project = make_project(tmp_path / "proj")
    try:
        store = project.store
        store.admission.admit("run-budget")
        outcome: dict[str, Any] = {}
        done = threading.Event()

        def build() -> None:
            try:
                outcome["build"] = project.cad.build_part("widget")
            except BaseException as exc:  # pragma: no cover - the regression itself
                outcome["error"] = exc
            finally:
                done.set()

        worker = threading.Thread(target=build)
        worker.start()
        while not done.is_set():
            store.admission.request_cancel("run-budget")
            time.sleep(0.0005)  # yield so the build thread makes progress
        worker.join()
        assert "error" not in outcome, f"build crashed: {outcome.get('error')!r}"
        assert outcome["build"]["status"] == "ok"
        _assert_project_config_lock_reacquirable(project)
        rebuilt = project.cad.build_part("widget")
        assert rebuilt["status"] == "ok"
    finally:
        project.close()


def test_holding_releases_project_config_lock_when_part_lock_is_busy(
    tmp_path: Path,
) -> None:
    """A part-lock acquisition failure must not leak the project-config lock.

    This is the ``publish_build`` reacquisition shape: project-config acquired
    first, then the part lock — if the part lock is held by a live holder, the
    already-acquired project-config lock has to be released on the failure path.
    """
    project = make_project(tmp_path / "proj")
    try:
        holder = LockManager(project.store, timeout_s=0.2)
        holder.acquire(PROJECT_CONFIG_LOCK)
        holder.acquire(part_lock("widget"))
        holder.release(PROJECT_CONFIG_LOCK)  # keep only the part lock held
        contender = LockManager(project.store, timeout_s=0.2)
        with (
            pytest.raises(LeaseHeldError),
            contender.holding(PROJECT_CONFIG_LOCK, part_lock("widget")),
        ):
            pass  # pragma: no cover - acquisition fails
        assert contender.held() == ()
        _assert_project_config_lock_reacquirable(project)
        holder.release(part_lock("widget"))
    finally:
        project.close()
