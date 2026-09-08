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

J-mirrors-and-dx-14: the two interleaving tests below are the tripwire for the
lock-leak regression they were born from, so a *recurrence* has to fail loudly
rather than hang. Before this fix each spun on ``done.is_set()`` with no
deadline of its own and then called ``worker.join()`` with no timeout — doubly
unbounded, so a leaked lock (the worker blocks forever inside
``LockManager.acquire``'s own timeout-bounded wait, or, pre-fix, past it) turned
the test into a silent job-timeout with no test name attached. Both loops now
carry the repository's own deadline idiom (``server/tests/test_supervisor.py``)
and fail by name — naming the still-alive worker thread — rather than hanging.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import pytest
from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend
from hephaestus.core.project_store.locks import PROJECT_CONFIG_LOCK, LockManager, part_lock
from hephaestus.testing.tools_fixture import Project, make_project

from opstore import LeaseHeldError

#: Generous bound for the spin-wait a cancel-racing test does before joining its
#: worker thread. The interleaving itself is sub-second (300 lock cycles, or one
#: ``build_part``); this is a regression tripwire, not a performance ceiling.
_SPIN_DEADLINE_S = 20.0
#: Bound for the final ``Thread.join()``. If the worker is still alive after the
#: spin deadline fired, it is well past done and something is genuinely stuck —
#: this catches that case by name instead of blocking the suite forever.
_JOIN_DEADLINE_S = 10.0


def _wait_bounded(
    done: threading.Event,
    worker: threading.Thread,
    *,
    label: str,
    on_tick: Any = None,
) -> None:
    """Spin on ``done`` with a deadline, then join with a deadline, or fail by name.

    ``on_tick``, when given, is called once per spin iteration (before the
    sleep) — the interleaving tests need to keep issuing cancels while they
    wait, and folding that into this helper keeps there being exactly one
    bounded spin-then-join shape rather than two copies of it.

    Replaces an unbounded ``while not done.is_set(): sleep(...)`` followed by an
    unbounded ``worker.join()`` — the shape J-mirrors-and-dx-14 names as a
    regression test that hangs instead of failing when the lock it guards
    against leaks again.
    """
    spin_deadline = time.monotonic() + _SPIN_DEADLINE_S
    while not done.is_set():
        if time.monotonic() >= spin_deadline:
            worker.join(timeout=1.0)
            pytest.fail(
                f"{label}: worker thread did not signal completion within "
                f"{_SPIN_DEADLINE_S}s — the lock it drives is likely leaked "
                f"(worker still alive: {worker.is_alive()})"
            )
        if on_tick is not None:
            on_tick()
        time.sleep(0.0005)  # yield so the worker thread makes progress
    worker.join(timeout=_JOIN_DEADLINE_S)
    if worker.is_alive():
        pytest.fail(
            f"{label}: worker thread signalled done but did not exit within "
            f"{_JOIN_DEADLINE_S}s of join() — it is stuck past its own completion flag"
        )


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
        _wait_bounded(
            done,
            worker,
            label="test_lock_cycles_survive_concurrent_admission_writes",
            on_tick=lambda: store.admission.request_cancel("run-cancel"),
        )
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
        _wait_bounded(
            done,
            worker,
            label="test_cancelled_run_admission_writes_mid_build_leave_lock_reacquirable",
            on_tick=lambda: store.admission.request_cancel("run-budget"),
        )
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


def test_cancel_after_close_is_a_quiet_noop(tmp_path: Path) -> None:
    """A daemon-thread cancel that loses the race with close() must not write.

    Regression (2026-07-28/29 long-sweep SIGSEGV): the bench budget guard
    cancels via ``threading.Thread(target=runtime.cancel, daemon=True)``, and
    a cancel still in flight while ``BridgeRuntime.close()`` closed the
    opstore executed on a freed sqlite connection — a native use-after-free.
    ``cancel`` after ``close`` now returns without touching the store, and
    ``opstore.db.Database.close`` additionally waits out any in-flight
    transaction under the transaction lock (covered in opstore/tests).
    """
    from hephaestus.agent_bridge.app import BridgeRuntime

    project = make_project(tmp_path / "proj")
    # dist_main bypasses sidecar resolution (the documented harness escape
    # hatch): this test never starts the runtime, and a bare CI checkout has
    # no built sidecar to resolve.
    fake_main = tmp_path / "fake-sidecar.js"
    fake_main.write_text("// never spawned\n")
    runtime = BridgeRuntime(
        backend=UnsafeLocalBackend(),
        project_root=project.root,
        dist_main=fake_main,
        providers=[
            {
                "id": "fake",
                "kind": "openai_compatible",
                "baseUrl": "http://127.0.0.1:9",
                "credential": "X",
                "models": [{"id": "m"}],
            }
        ],
        credentials={"X": "unused"},
    )
    # Never started: close() must still be safe, and a straggler cancel after
    # it must be a no-op rather than an admission write through a closed store.
    runtime.close()
    runtime.cancel("any-run-id")  # must not raise, must not touch the store
    runtime.cancel("any-run-id")  # idempotent
