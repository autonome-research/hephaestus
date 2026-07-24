"""Tests for opstore.leases: shared/exclusive semantics, heartbeat, liveness
reclaim, break_stale takeover, artifact_expired, cross-process contention,
crash injection, and a hypothesis state machine over lease sequences."""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path

import pytest
from conftest import REPO_ROOT, CrashRunner, FakeClock, FakeLiveness
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import (
    RuleBasedStateMachine,
    invariant,
    rule,
    run_state_machine_as_test,  # pyright: ignore[reportUnknownVariableType]
)
from opstore.db import Database
from opstore.errors import ArtifactExpiredError, LeaseExpiredError, LeaseHeldError
from opstore.leases import (
    CRASH_AFTER_ACQUIRE_COMMIT,
    TAKEOVER_META_PREFIX,
    Lease,
    LeaseManager,
)
from opstore.types import CRASH_ENV_VAR, LeaseMode, OwnerId

O1 = OwnerId(pid=101, pid_start_ns=1)
O2 = OwnerId(pid=102, pid_start_ns=2)
O3 = OwnerId(pid=103, pid_start_ns=3)


@pytest.fixture
def leases(db: Database, fake_clock: FakeClock, fake_liveness: FakeLiveness) -> LeaseManager:
    return LeaseManager(db, clock=fake_clock, liveness=fake_liveness)


def lease_rows(db: Database, ref: str) -> list[str]:
    rows = db.conn.execute("SELECT lease_id FROM leases WHERE ref = ?", (ref,)).fetchall()
    return [str(row["lease_id"]) for row in rows]


class TestAcquireSemantics:
    def test_shared_shared_coexist(self, leases: LeaseManager, db: Database) -> None:
        a = leases.acquire_shared("ref", O1, ttl_s=60.0)
        b = leases.acquire_shared("ref", O2, ttl_s=60.0)
        assert a.lease_id != b.lease_id
        assert a.mode is LeaseMode.SHARED and b.mode is LeaseMode.SHARED
        assert set(lease_rows(db, "ref")) == {a.lease_id, b.lease_id}

    def test_shared_blocks_exclusive(self, leases: LeaseManager) -> None:
        leases.acquire_shared("ref", O1, ttl_s=60.0)
        with pytest.raises(LeaseHeldError) as excinfo:
            leases.acquire_exclusive("ref", O2, ttl_s=60.0)
        assert excinfo.value.code == "lease_held"

    def test_exclusive_blocks_shared_and_exclusive(self, leases: LeaseManager) -> None:
        leases.acquire_exclusive("ref", O1, ttl_s=60.0)
        with pytest.raises(LeaseHeldError):
            leases.acquire_shared("ref", O2, ttl_s=60.0)
        with pytest.raises(LeaseHeldError):
            leases.acquire_exclusive("ref", O2, ttl_s=60.0)

    def test_refs_are_independent(self, leases: LeaseManager) -> None:
        leases.acquire_exclusive("ref-a", O1, ttl_s=60.0)
        other = leases.acquire_exclusive("ref-b", O2, ttl_s=60.0)
        assert other.ref == "ref-b"

    def test_release_unblocks(self, leases: LeaseManager, db: Database) -> None:
        held = leases.acquire_exclusive("ref", O1, ttl_s=60.0)
        assert leases.release(held.lease_id) is True
        assert leases.release(held.lease_id) is False  # already gone
        assert lease_rows(db, "ref") == []
        leases.acquire_exclusive("ref", O2, ttl_s=60.0)

    def test_negative_ttl_rejected(self, leases: LeaseManager) -> None:
        with pytest.raises(ValueError):
            leases.acquire_shared("ref", O1, ttl_s=-1.0)

    def test_get_and_holders(self, leases: LeaseManager) -> None:
        held = leases.acquire_shared("ref", O1, ttl_s=60.0)
        assert leases.get(held.lease_id) == held
        assert leases.get("missing") is None
        assert leases.holders("ref") == [held]
        assert leases.holders("other") == []


class TestHeartbeat:
    def test_heartbeat_extends(
        self,
        leases: LeaseManager,
        fake_clock: FakeClock,
        fake_liveness: FakeLiveness,
    ) -> None:
        held = leases.acquire_exclusive("ref", O1, ttl_s=10.0)
        fake_clock.advance(8.0)
        refreshed = leases.heartbeat(held.lease_id)
        assert refreshed.heartbeat_at == fake_clock.now()
        assert refreshed.expires_at() == fake_clock.now() + 10.0
        # 16s after acquisition: past the original TTL, within the extended one.
        fake_clock.advance(8.0)
        with pytest.raises(LeaseHeldError):
            leases.acquire_exclusive("ref", O2, ttl_s=10.0)  # O1 dead per FakeLiveness, but live

    def test_without_heartbeat_dead_owner_is_reclaimed(
        self, leases: LeaseManager, fake_clock: FakeClock
    ) -> None:
        leases.acquire_exclusive("ref", O1, ttl_s=10.0)
        fake_clock.advance(16.0)
        leases.acquire_exclusive("ref", O2, ttl_s=10.0)

    def test_heartbeat_after_release_expired(self, leases: LeaseManager) -> None:
        held = leases.acquire_shared("ref", O1, ttl_s=10.0)
        leases.release(held.lease_id)
        with pytest.raises(LeaseExpiredError) as excinfo:
            leases.heartbeat(held.lease_id)
        assert excinfo.value.code == "lease_expired"

    def test_heartbeat_after_reclaim_expired(
        self, leases: LeaseManager, fake_clock: FakeClock
    ) -> None:
        held = leases.acquire_exclusive("ref", O1, ttl_s=5.0)
        fake_clock.advance(10.0)
        leases.acquire_exclusive("ref", O2, ttl_s=60.0)  # reclaims dead O1
        with pytest.raises(LeaseExpiredError):
            leases.heartbeat(held.lease_id)


class TestLivenessReclaim:
    def test_dead_owner_reclaimed_after_ttl(
        self, leases: LeaseManager, fake_clock: FakeClock, db: Database
    ) -> None:
        stale = leases.acquire_exclusive("ref", O1, ttl_s=5.0)
        fake_clock.advance(6.0)
        fresh = leases.acquire_exclusive("ref", O2, ttl_s=60.0)
        assert lease_rows(db, "ref") == [fresh.lease_id]
        assert leases.get(stale.lease_id) is None

    def test_live_owner_not_reclaimed_past_ttl(
        self, leases: LeaseManager, fake_clock: FakeClock, fake_liveness: FakeLiveness
    ) -> None:
        fake_liveness.alive.add(O1)
        leases.acquire_exclusive("ref", O1, ttl_s=5.0)
        fake_clock.advance(1_000.0)
        with pytest.raises(LeaseHeldError) as excinfo:
            leases.acquire_exclusive("ref", O2, ttl_s=60.0)
        assert "alive" in excinfo.value.message

    def test_dead_owner_within_ttl_not_reclaimed(
        self, leases: LeaseManager, fake_clock: FakeClock
    ) -> None:
        leases.acquire_exclusive("ref", O1, ttl_s=60.0)  # O1 not in alive-set at all
        fake_clock.advance(30.0)
        with pytest.raises(LeaseHeldError):
            leases.acquire_exclusive("ref", O2, ttl_s=60.0)

    def test_stale_dead_shared_reclaimed_by_exclusive(
        self, leases: LeaseManager, fake_clock: FakeClock, db: Database
    ) -> None:
        leases.acquire_shared("ref", O1, ttl_s=5.0)
        leases.acquire_shared("ref", O2, ttl_s=5.0)
        fake_clock.advance(6.0)
        fresh = leases.acquire_exclusive("ref", O3, ttl_s=60.0)
        assert lease_rows(db, "ref") == [fresh.lease_id]

    def test_shared_does_not_reclaim_stale_shared(
        self, leases: LeaseManager, fake_clock: FakeClock, db: Database
    ) -> None:
        stale = leases.acquire_shared("ref", O1, ttl_s=5.0)
        fake_clock.advance(6.0)
        fresh = leases.acquire_shared("ref", O2, ttl_s=60.0)
        assert set(lease_rows(db, "ref")) == {stale.lease_id, fresh.lease_id}

    def test_live_holders_reflects_liveness(
        self, leases: LeaseManager, fake_clock: FakeClock, fake_liveness: FakeLiveness
    ) -> None:
        fake_liveness.alive.add(O1)
        a = leases.acquire_shared("ref", O1, ttl_s=5.0)
        b = leases.acquire_shared("ref", O2, ttl_s=5.0)
        assert {lease.lease_id for lease in leases.live_holders("ref")} == {
            a.lease_id,
            b.lease_id,
        }
        fake_clock.advance(6.0)  # both past TTL; only O1 is alive
        assert [lease.lease_id for lease in leases.live_holders("ref")] == [a.lease_id]


class TestBreakStale:
    def test_break_stale_records_takeover(
        self,
        leases: LeaseManager,
        fake_clock: FakeClock,
        fake_liveness: FakeLiveness,
        db: Database,
    ) -> None:
        fake_liveness.alive.add(O1)
        stale = leases.acquire_exclusive("ref", O1, ttl_s=5.0)
        fake_clock.advance(6.0)
        with pytest.raises(LeaseHeldError):
            leases.acquire_exclusive("ref", O2, ttl_s=60.0)  # alive owner: normal path refuses
        taken = leases.break_stale("ref", LeaseMode.EXCLUSIVE, O2, ttl_s=60.0)
        assert lease_rows(db, "ref") == [taken.lease_id]
        record = leases.takeover_record(taken.lease_id)
        assert isinstance(record, dict)
        assert record["ref"] == "ref"
        assert record["taker_pid"] == O2.pid
        assert record["at"] == fake_clock.now()
        broken = record["broken"]
        assert isinstance(broken, list) and len(broken) == 1
        entry = broken[0]
        assert isinstance(entry, dict)
        assert entry["lease_id"] == stale.lease_id
        assert entry["owner_pid"] == O1.pid
        row = db.conn.execute(
            "SELECT value FROM meta WHERE key = ?",
            (TAKEOVER_META_PREFIX + taken.lease_id,),
        ).fetchone()
        assert row is not None  # durably recorded

    def test_break_stale_refuses_fresh_lease(
        self, leases: LeaseManager, fake_clock: FakeClock
    ) -> None:
        leases.acquire_exclusive("ref", O1, ttl_s=60.0)
        fake_clock.advance(30.0)
        with pytest.raises(LeaseHeldError):
            leases.break_stale("ref", LeaseMode.EXCLUSIVE, O2, ttl_s=60.0)

    def test_break_stale_without_conflict_records_nothing(self, leases: LeaseManager) -> None:
        taken = leases.break_stale("ref", LeaseMode.SHARED, O1, ttl_s=60.0)
        assert leases.takeover_record(taken.lease_id) is None
        assert leases.takeover_record("unknown") is None


class TestArtifactExpired:
    def test_ref_gone_before_acquisition(self, leases: LeaseManager, db: Database) -> None:
        for acquire in (leases.acquire_shared, leases.acquire_exclusive):
            with pytest.raises(ArtifactExpiredError) as excinfo:
                acquire("ref", O1, 60.0, ref_exists=lambda ref: False)
            assert excinfo.value.code == "artifact_expired"
        assert lease_rows(db, "ref") == []  # no lease row leaked

    def test_ref_present_acquires(self, leases: LeaseManager) -> None:
        seen: list[str] = []

        def oracle(ref: str) -> bool:
            seen.append(ref)
            return True

        held = leases.acquire_shared("ref", O1, ttl_s=60.0, ref_exists=oracle)
        assert seen == ["ref"]
        assert held.ref == "ref"


CONTEND_SCRIPT = """
import time
from pathlib import Path
from opstore.db import Database
from opstore.errors import LeaseHeldError
from opstore.leases import LeaseManager
from opstore.types import current_owner

root = Path({root!r})
sync = root / "sync"
winner_marker = sync / "winner"
release_marker = sync / "release"
with Database.connect(root / "state.db") as db:
    mgr = LeaseManager(db)
    lease = None
    deadline = time.monotonic() + 60.0
    while time.monotonic() < deadline:
        try:
            lease = mgr.acquire_exclusive("artifact", current_owner(), ttl_s=300.0)
            break
        except LeaseHeldError:
            if winner_marker.exists():
                break
            time.sleep(0.01)
    if lease is not None:
        winner_marker.write_text(str(current_owner().pid))
        print("WIN", flush=True)
        while not release_marker.exists():
            time.sleep(0.02)
        mgr.release(lease.lease_id)
    else:
        print("HELD", flush=True)
"""


def test_cross_process_exclusive_contention(store_root: Path) -> None:
    """Two real subprocesses contend for one exclusive lease; exactly one wins."""
    Database.connect(store_root / "state.db").close()  # pre-migrate once
    sync = store_root / "sync"
    sync.mkdir()
    env = dict(os.environ)
    env.pop(CRASH_ENV_VAR, None)
    script = CONTEND_SCRIPT.format(root=str(store_root))
    procs = [
        subprocess.Popen(
            ["uv", "run", "python", "-c", script],
            cwd=REPO_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    try:
        deadline = time.monotonic() + 60.0
        while not (sync / "winner").exists():
            assert time.monotonic() < deadline, "no process won the lease in time"
            time.sleep(0.02)
        (sync / "release").write_text("go")
        outputs = [proc.communicate(timeout=60) for proc in procs]
    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.kill()
    assert all(proc.returncode == 0 for proc in procs), [err for _, err in outputs]
    results = sorted(out.strip() for out, _ in outputs)
    assert results == ["HELD", "WIN"]
    with Database.connect(store_root / "state.db") as db:
        assert db.conn.execute("SELECT COUNT(*) FROM leases").fetchone()[0] == 0


CRASH_SCRIPT = """
from pathlib import Path
from opstore.db import Database
from opstore.leases import LeaseManager
from opstore.types import EnvCrashHook, current_owner

root = Path({root!r})
with Database.connect(root / "state.db") as db:
    mgr = LeaseManager(db, crash_hook=EnvCrashHook())
    mgr.acquire_exclusive("artifact", current_owner(), ttl_s={ttl!r})
"""


def test_crash_after_acquire_leaves_reclaimable_lease(
    store_root: Path, run_crash_subprocess: CrashRunner
) -> None:
    """Crash right after commit: durable row, dead owner; liveness reclaim recovers."""
    proc = run_crash_subprocess(
        CRASH_SCRIPT.format(root=str(store_root), ttl=0.5),
        crash_point=CRASH_AFTER_ACQUIRE_COMMIT,
    )
    assert proc.returncode == 42, proc.stderr
    with Database.connect(store_root / "state.db") as db:
        orphan_rows = db.conn.execute("SELECT * FROM leases WHERE ref = 'artifact'").fetchall()
        assert len(orphan_rows) == 1  # the crashed process's lease survived durably
        time.sleep(0.7)  # let the real-clock TTL elapse

        class AlwaysAlive:
            def is_alive(self, owner: OwnerId) -> bool:
                return True

        pretending = LeaseManager(db, liveness=AlwaysAlive())
        with pytest.raises(LeaseHeldError):
            pretending.acquire_exclusive("artifact", O2, ttl_s=60.0)
        # Default liveness sees the crashed pid as dead: reclaim succeeds.
        recovered = LeaseManager(db).acquire_exclusive("artifact", O2, ttl_s=60.0)
        assert lease_rows(db, "artifact") == [recovered.lease_id]


def test_crash_subprocess_completes_without_crash_point(
    store_root: Path, run_crash_subprocess: CrashRunner
) -> None:
    proc = run_crash_subprocess(CRASH_SCRIPT.format(root=str(store_root), ttl=300.0))
    assert proc.returncode == 0, proc.stderr
    with Database.connect(store_root / "state.db") as db:
        assert len(lease_rows(db, "artifact")) == 1


REFS = st.sampled_from(["ref-a", "ref-b"])
OWNERS = st.sampled_from([O1, O2, O3])
MODES = st.sampled_from([LeaseMode.SHARED, LeaseMode.EXCLUSIVE])
TTLS = st.sampled_from([5.0, 20.0])


class LeaseStateMachine(RuleBasedStateMachine):
    """Random acquire/heartbeat/release/expire/liveness sequences.

    Invariants: per ref, never two live exclusive leases, and a live exclusive
    never coexists with any other live lease. "Live" = within heartbeat TTL, or
    past TTL with an alive owner (spec's reclaimability rule inverted).
    """

    def __init__(self) -> None:
        super().__init__()
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database.connect(Path(self._tmp.name) / "state.db")
        self.clock = FakeClock()
        self.liveness = FakeLiveness()
        self.liveness.alive.update({O1, O2, O3})
        self.mgr = LeaseManager(self.db, clock=self.clock, liveness=self.liveness)
        self.known: list[str] = []

    def teardown(self) -> None:
        self.db.close()
        self._tmp.cleanup()

    def _live(self, ref: str) -> list[Lease]:
        now = self.clock.now()
        return [
            lease
            for lease in self.mgr.holders(ref)
            if lease.expires_at() >= now or self.liveness.is_alive(lease.owner)
        ]

    def _blocked(self, ref: str, mode: LeaseMode) -> bool:
        return any(
            mode is LeaseMode.EXCLUSIVE or held.mode is LeaseMode.EXCLUSIVE
            for held in self._live(ref)
        )

    @rule(ref=REFS, owner=OWNERS, mode=MODES, ttl=TTLS)
    def attempt_acquire(self, ref: str, owner: OwnerId, mode: LeaseMode, ttl: float) -> None:
        blocked = self._blocked(ref, mode)
        try:
            if mode is LeaseMode.SHARED:
                lease = self.mgr.acquire_shared(ref, owner, ttl)
            else:
                lease = self.mgr.acquire_exclusive(ref, owner, ttl)
        except LeaseHeldError:
            assert blocked, f"acquisition of {mode} on {ref} blocked with no live conflict"
        else:
            assert not blocked, f"acquisition of {mode} on {ref} succeeded past a live conflict"
            self.known.append(lease.lease_id)

    @rule(data=st.data())
    def heartbeat_some(self, data: st.DataObject) -> None:
        if not self.known:
            return
        lease_id = data.draw(st.sampled_from(self.known))
        exists = self.mgr.get(lease_id) is not None
        try:
            refreshed = self.mgr.heartbeat(lease_id)
        except LeaseExpiredError:
            assert not exists
        else:
            assert exists
            assert refreshed.heartbeat_at == self.clock.now()

    @rule(data=st.data())
    def release_some(self, data: st.DataObject) -> None:
        if not self.known:
            return
        lease_id = data.draw(st.sampled_from(self.known))
        exists = self.mgr.get(lease_id) is not None
        assert self.mgr.release(lease_id) is exists

    @rule(seconds=st.sampled_from([1.0, 6.0, 30.0]))
    def advance_clock(self, seconds: float) -> None:
        self.clock.advance(seconds)

    @rule(owner=OWNERS)
    def kill_owner(self, owner: OwnerId) -> None:
        self.liveness.alive.discard(owner)

    @rule(owner=OWNERS)
    def revive_owner(self, owner: OwnerId) -> None:
        self.liveness.alive.add(owner)

    @invariant()
    def no_conflicting_live_leases(self) -> None:
        for ref in ("ref-a", "ref-b"):
            live = self._live(ref)
            exclusives = [lease for lease in live if lease.mode is LeaseMode.EXCLUSIVE]
            assert len(exclusives) <= 1, f"two live exclusive leases on {ref}"
            if exclusives:
                assert len(live) == 1, f"live exclusive coexists with other live leases on {ref}"


def test_lease_state_machine() -> None:
    run_state_machine_as_test(
        LeaseStateMachine,
        settings=settings(max_examples=40, stateful_step_count=40, deadline=None),
    )
