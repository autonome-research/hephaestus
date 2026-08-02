"""Tests for opstore.gc: pins/links reachability, retention classes, deletion leases,
quota guard, dry-run explanations, crash injection, and the no-reachable-loss property."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest
from _optest import REPO_ROOT, CrashRunner, FakeClock, FakeLiveness
from hypothesis import given, settings
from hypothesis import strategies as st
from opstore.blobs import BlobStore
from opstore.db import Database
from opstore.errors import ProtectedQuotaExceededError
from opstore.gc import (
    CRASH_AFTER_LEASE,
    CRASH_AFTER_RECHECK,
    CRASH_AFTER_ROW_DELETE,
    CRASH_AFTER_UNLINK,
    Gc,
    GcAction,
    GcReport,
    ProtectedRoots,
    PurgeHook,
)
from opstore.types import CRASH_ENV_VAR, StoreConfig

DAY = 86_400.0


@pytest.fixture
def blobs(store_root: Path, db: Database, fake_clock: FakeClock) -> BlobStore:
    return BlobStore(store_root, db, clock=fake_clock)


def make_gc(
    store_root: Path,
    db: Database,
    fake_clock: FakeClock,
    fake_liveness: FakeLiveness,
    *,
    config: StoreConfig | None = None,
    protected_roots: ProtectedRoots | None = None,
    purge_hooks: tuple[PurgeHook, ...] = (),
) -> Gc:
    return Gc(
        store_root,
        db,
        config,
        clock=fake_clock,
        liveness=fake_liveness,
        protected_roots=protected_roots,
        purge_hooks=purge_hooks,
    )


def actions_by_ref(report: GcReport) -> dict[str, GcAction]:
    return {c.ref: c.action for c in report.candidates}


def test_pin_link_roundtrip_idempotent(
    store_root: Path, db: Database, fake_clock: FakeClock, fake_liveness: FakeLiveness
) -> None:
    gc = make_gc(store_root, db, fake_clock, fake_liveness)
    gc.pin("a")
    gc.pin("a")
    assert gc.pins() == {"a"}
    gc.link("a", "b")
    gc.link("a", "b")
    assert gc.links() == {("a", "b")}
    assert gc.reachable() == {"a", "b"}
    gc.unpin("a")
    gc.unpin("a")
    assert gc.pins() == frozenset()
    gc.unlink("a", "b")
    gc.unlink("a", "b")
    assert gc.links() == frozenset()
    assert gc.reachable() == frozenset()


def test_transitive_pin_retains_chain(
    store_root: Path,
    db: Database,
    fake_clock: FakeClock,
    fake_liveness: FakeLiveness,
    blobs: BlobStore,
) -> None:
    a = blobs.put(b"chain-a")
    b = blobs.put(b"chain-b")
    c = blobs.put(b"chain-c")
    d = blobs.put(b"unrelated-d")
    gc = make_gc(store_root, db, fake_clock, fake_liveness)
    gc.pin(a)
    gc.link(a, b)
    gc.link(b, c)
    fake_clock.advance(31 * DAY)
    report = gc.collect()
    assert actions_by_ref(report) == {d: GcAction.COLLECTED}
    for retained in (a, b, c):
        assert blobs.has(retained)
    assert not blobs.has(d)
    assert report.reclaimed_bytes == len(b"unrelated-d")


def test_link_cycles_terminate(
    store_root: Path, db: Database, fake_clock: FakeClock, fake_liveness: FakeLiveness
) -> None:
    gc = make_gc(store_root, db, fake_clock, fake_liveness)
    gc.pin("x")
    gc.link("x", "y")
    gc.link("y", "x")
    gc.link("y", "z")
    assert gc.reachable() == {"x", "y", "z"}


def test_unreachable_young_retained(
    store_root: Path,
    db: Database,
    fake_clock: FakeClock,
    fake_liveness: FakeLiveness,
    blobs: BlobStore,
) -> None:
    ref = blobs.put(b"young and unreachable")
    gc = make_gc(store_root, db, fake_clock, fake_liveness)
    fake_clock.advance(29 * DAY)
    report = gc.collect()
    assert report.candidates == ()
    assert blobs.has(ref)


def test_unreachable_old_collected(
    store_root: Path,
    db: Database,
    fake_clock: FakeClock,
    fake_liveness: FakeLiveness,
    blobs: BlobStore,
) -> None:
    data = b"old and unreachable"
    ref = blobs.put(data)
    gc = make_gc(store_root, db, fake_clock, fake_liveness)
    fake_clock.advance(31 * DAY)
    report = gc.collect()
    assert actions_by_ref(report) == {ref: GcAction.COLLECTED}
    assert report.reclaimed_bytes == len(data)
    assert not blobs.has(ref)
    assert not blobs.path_for(ref).exists()
    assert db.conn.execute("SELECT COUNT(*) FROM blobs").fetchone()[0] == 0
    assert db.conn.execute("SELECT COUNT(*) FROM leases").fetchone()[0] == 0


def test_preview_class_collected_at_seven_days_not_before(
    store_root: Path,
    db: Database,
    fake_clock: FakeClock,
    fake_liveness: FakeLiveness,
    blobs: BlobStore,
) -> None:
    preview = blobs.put(b"preview blob", retention_class="preview")
    default = blobs.put(b"default blob")
    gc = make_gc(store_root, db, fake_clock, fake_liveness)

    fake_clock.advance(6 * DAY)
    assert gc.collect().candidates == ()
    assert blobs.has(preview)

    fake_clock.advance(2 * DAY)  # age 8d: preview past 7d, default well under 30d
    report = gc.collect()
    assert actions_by_ref(report) == {preview: GcAction.COLLECTED}
    assert not blobs.has(preview)
    assert blobs.has(default)

    fake_clock.advance(23 * DAY)  # age 31d: default past 30d
    report = gc.collect()
    assert actions_by_ref(report) == {default: GcAction.COLLECTED}
    assert not blobs.has(default)


def test_dry_run_explains_and_deletes_nothing(
    store_root: Path,
    db: Database,
    fake_clock: FakeClock,
    fake_liveness: FakeLiveness,
    blobs: BlobStore,
) -> None:
    ref = blobs.put(b"doomed eventually")
    purges: list[int] = []
    gc = make_gc(store_root, db, fake_clock, fake_liveness, purge_hooks=(lambda: purges.append(1),))
    fake_clock.advance(31 * DAY)
    report = gc.collect(dry_run=True)
    assert report.dry_run is True
    assert report.reclaimed_bytes == 0
    assert purges == []
    (candidate,) = report.candidates
    assert candidate.ref == ref
    assert candidate.action is GcAction.WOULD_COLLECT
    assert candidate.retention_class == "default"
    assert "unreachable" in candidate.reason
    assert "retention" in candidate.reason
    assert candidate.age_s == pytest.approx(31 * DAY)
    assert blobs.has(ref)

    report = gc.collect()
    assert purges == [1]
    assert actions_by_ref(report) == {ref: GcAction.COLLECTED}
    assert not blobs.has(ref)


def test_dry_run_reports_live_lease(
    store_root: Path,
    db: Database,
    fake_clock: FakeClock,
    fake_liveness: FakeLiveness,
    blobs: BlobStore,
) -> None:
    ref = blobs.put(b"leased blob")
    gc = make_gc(store_root, db, fake_clock, fake_liveness)
    fake_clock.advance(31 * DAY)
    db.conn.execute(
        "INSERT INTO leases(lease_id, ref, mode, owner_pid, owner_start_ns, "
        "ttl_s, heartbeat_at, created_at) VALUES('l1', ?, 'shared', 1, 0, 3600.0, ?, ?)",
        (ref, fake_clock.now(), fake_clock.now()),
    )
    report = gc.collect(dry_run=True)
    assert actions_by_ref(report) == {ref: GcAction.LEASE_HELD}
    assert blobs.has(ref)


def test_recheck_saves_blob_pinned_between_selection_and_deletion(
    store_root: Path,
    db: Database,
    fake_clock: FakeClock,
    fake_liveness: FakeLiveness,
    blobs: BlobStore,
) -> None:
    ref = blobs.put(b"pinned mid-collect")
    calls = {"n": 0}

    def roots() -> list[str]:
        calls["n"] += 1
        if calls["n"] == 1:
            # Concurrent pin arriving after candidate selection but before deletion.
            db.conn.execute(
                "INSERT OR IGNORE INTO pins(ref, created_at) VALUES(?, ?)",
                (ref, fake_clock.now()),
            )
        return []

    gc = make_gc(store_root, db, fake_clock, fake_liveness, protected_roots=roots)
    fake_clock.advance(31 * DAY)
    report = gc.collect()
    assert actions_by_ref(report) == {ref: GcAction.SAVED_BY_RECHECK}
    assert report.reclaimed_bytes == 0
    assert blobs.has(ref)
    assert db.conn.execute("SELECT COUNT(*) FROM leases").fetchone()[0] == 0


def test_protected_roots_are_transitive(
    store_root: Path,
    db: Database,
    fake_clock: FakeClock,
    fake_liveness: FakeLiveness,
    blobs: BlobStore,
) -> None:
    root_blob = blobs.put(b"protected root")
    child = blobs.put(b"child of protected")
    orphan = blobs.put(b"orphan")
    gc = make_gc(store_root, db, fake_clock, fake_liveness, protected_roots=lambda: [root_blob])
    gc.link(root_blob, child)
    fake_clock.advance(31 * DAY)
    report = gc.collect()
    assert actions_by_ref(report) == {orphan: GcAction.COLLECTED}
    assert blobs.has(root_blob)
    assert blobs.has(child)


def test_protected_quota_exceeded_and_admission_guard(
    store_root: Path,
    db: Database,
    fake_clock: FakeClock,
    fake_liveness: FakeLiveness,
    blobs: BlobStore,
) -> None:
    big = blobs.put(b"x" * 100)
    loose = blobs.put(b"y" * 40)
    config = StoreConfig(quota_bytes=64)
    gc = make_gc(store_root, db, fake_clock, fake_liveness, config=config)
    gc.pin(big)

    with pytest.raises(ProtectedQuotaExceededError) as excinfo:
        gc.admission_guard()
    assert excinfo.value.code == "protected_quota_exceeded"

    usage = gc.usage()
    assert usage.protected_bytes == 100
    assert usage.total_bytes == 140
    assert usage.quota_bytes == 64

    # Nothing protected is deleted even while over quota.
    fake_clock.advance(31 * DAY)
    report = gc.collect()
    assert actions_by_ref(report) == {loose: GcAction.COLLECTED}
    assert blobs.has(big)
    with pytest.raises(ProtectedQuotaExceededError):
        gc.admission_guard()

    # Unpinning clears the guard before collection even runs.
    gc.unpin(big)
    usage = gc.admission_guard()
    assert usage.protected_bytes == 0


def test_admission_guard_passes_under_quota(
    store_root: Path,
    db: Database,
    fake_clock: FakeClock,
    fake_liveness: FakeLiveness,
    blobs: BlobStore,
) -> None:
    ref = blobs.put(b"small")
    gc = make_gc(store_root, db, fake_clock, fake_liveness)
    gc.pin(ref)
    usage = gc.admission_guard()
    assert usage.protected_bytes == len(b"small")


def test_purge_hooks_run_only_on_real_collect(
    store_root: Path, db: Database, fake_clock: FakeClock, fake_liveness: FakeLiveness
) -> None:
    purges: list[int] = []
    gc = make_gc(store_root, db, fake_clock, fake_liveness, purge_hooks=(lambda: purges.append(1),))
    gc.collect(dry_run=True)
    assert purges == []
    gc.collect()
    gc.collect()
    assert purges == [1, 1]


# -- hypothesis: no reachable ref is ever collected -------------------------


@st.composite
def pin_link_graphs(
    draw: st.DrawFn,
) -> tuple[int, set[int], set[int], set[tuple[int, int]]]:
    n = draw(st.integers(min_value=1, max_value=6))
    indices = st.integers(min_value=0, max_value=n - 1)
    pins = set(draw(st.lists(indices, max_size=n)))
    protected = set(draw(st.lists(indices, max_size=n)))
    links = set(draw(st.lists(st.tuples(indices, indices), max_size=12)))
    return n, pins, protected, links


@settings(deadline=None, max_examples=30)
@given(graph=pin_link_graphs())
def test_property_no_reachable_ref_collected(
    tmp_path_factory: pytest.TempPathFactory,
    graph: tuple[int, set[int], set[int], set[tuple[int, int]]],
) -> None:
    n, pins, protected, links = graph
    root = tmp_path_factory.mktemp("gcprop")
    clock = FakeClock()
    liveness = FakeLiveness()
    with Database.connect(root / "state.db") as db:
        store = BlobStore(root, db, clock=clock)
        refs = [store.put(f"blob-{i}".encode()) for i in range(n)]
        protected_refs = [refs[i] for i in sorted(protected)]
        gc = Gc(
            root,
            db,
            clock=clock,
            liveness=liveness,
            protected_roots=lambda: protected_refs,
        )
        for i in sorted(pins):
            gc.pin(refs[i])
        for i, j in sorted(links):
            gc.link(refs[i], refs[j])

        # Independent closure computation.
        expected = {refs[i] for i in pins | protected}
        changed = True
        while changed:
            changed = False
            for i, j in links:
                if refs[i] in expected and refs[j] not in expected:
                    expected.add(refs[j])
                    changed = True

        clock.advance(31 * DAY)
        report = gc.collect()
        collected = {c.ref for c in report.candidates if c.action is GcAction.COLLECTED}
        assert collected == set(refs) - expected
        for ref in refs:
            assert store.has(ref) == (ref in expected)
        assert gc.reachable() >= expected


# -- deletion-lease race with a subprocess reader ---------------------------

READER_SCRIPT = """
import os
import time
import uuid
from pathlib import Path
from opstore.blobs import BlobStore
from opstore.db import Database
root = Path({root!r})
ref = {ref!r}
hb = {hb!r}
flag = root / "reader_acquired"
proceed = root / "reader_proceed"
with Database.connect(root / "state.db") as db:
    with db.transaction() as conn:
        row = conn.execute("SELECT 1 FROM blobs WHERE hash = ?", (ref,)).fetchone()
        excl = conn.execute(
            "SELECT 1 FROM leases WHERE ref = ? AND mode = 'exclusive'", (ref,)
        ).fetchone()
        if row is None or excl is not None:
            print("artifact_expired")
            raise SystemExit(0)
        conn.execute(
            "INSERT INTO leases(lease_id, ref, mode, owner_pid, owner_start_ns, "
            "ttl_s, heartbeat_at, created_at) VALUES(?, ?, 'shared', ?, 0, 3600.0, ?, ?)",
            (uuid.uuid4().hex, ref, os.getpid(), hb, hb),
        )
    flag.write_text("acquired")
    deadline = time.time() + 60.0
    while not proceed.exists():
        if time.time() > deadline:
            raise SystemExit(3)
        time.sleep(0.05)
    data = BlobStore(root, db).get(ref)
    with db.transaction() as conn:
        conn.execute("DELETE FROM leases WHERE ref = ? AND mode = 'shared'", (ref,))
    print("complete:" + str(len(data)))
"""


def _spawn_reader(store_root: Path, ref: str, hb: float) -> subprocess.Popen[str]:
    env = dict(os.environ)
    env.pop(CRASH_ENV_VAR, None)
    script = READER_SCRIPT.format(root=str(store_root), ref=ref, hb=hb)
    return subprocess.Popen(
        ["uv", "run", "python", "-c", script],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def test_reader_shared_lease_blocks_unlink_never_partial(
    store_root: Path,
    db: Database,
    fake_clock: FakeClock,
    fake_liveness: FakeLiveness,
    blobs: BlobStore,
) -> None:
    data = b"lease-guarded artifact bytes"
    ref = blobs.put(data)
    gc = make_gc(store_root, db, fake_clock, fake_liveness)
    fake_clock.advance(31 * DAY)

    reader = _spawn_reader(store_root, ref, fake_clock.now())
    try:
        flag = store_root / "reader_acquired"
        deadline = time.time() + 60.0
        while not flag.exists():
            assert reader.poll() is None, reader.communicate()[1]
            assert time.time() < deadline, "reader never acquired its shared lease"
            time.sleep(0.05)

        # A live shared lease blocks the deletion lease: blob survives collect.
        report = gc.collect()
        assert actions_by_ref(report) == {ref: GcAction.LEASE_HELD}
        assert blobs.has(ref)
        assert blobs.path_for(ref).read_bytes() == data

        (store_root / "reader_proceed").write_text("go")
        stdout, stderr = reader.communicate(timeout=60)
        assert reader.returncode == 0, stderr
        assert stdout.strip() == f"complete:{len(data)}"  # full read, never partial
    finally:
        if reader.poll() is None:
            reader.kill()
            reader.communicate()

    # Lease released: the next pass collects the blob.
    report = gc.collect()
    assert actions_by_ref(report) == {ref: GcAction.COLLECTED}
    assert not blobs.has(ref)

    # A reader arriving after deletion observes artifact_expired, never partial bytes.
    late = _spawn_reader(store_root, ref, fake_clock.now())
    stdout, stderr = late.communicate(timeout=60)
    assert late.returncode == 0, stderr
    assert stdout.strip() == "artifact_expired"


# -- crash injection --------------------------------------------------------

CRASH_SCRIPT = """
from pathlib import Path
from opstore.db import Database
from opstore.gc import Gc
from opstore.types import DefaultLiveness, EnvCrashHook
root = Path({root!r})
with Database.connect(root / "state.db") as db:
    gc = Gc(
        root,
        db,
        crash_hook=EnvCrashHook(),
        liveness=DefaultLiveness(),
        deletion_lease_ttl_s=0.0,
    )
    gc.collect()
"""


def _seed_old_unreachable_blob(store_root: Path, data: bytes) -> str:
    clock = FakeClock()  # 2023: far older than any retention horizon vs real now
    with Database.connect(store_root / "state.db") as db:
        return BlobStore(store_root, db, clock=clock).put(data)


@pytest.mark.parametrize(
    ("point", "file_expected", "row_expected"),
    [
        (CRASH_AFTER_LEASE, True, True),
        (CRASH_AFTER_RECHECK, True, True),
        (CRASH_AFTER_UNLINK, False, True),
        (CRASH_AFTER_ROW_DELETE, False, False),
    ],
)
def test_crash_injection_collect_then_recover(
    store_root: Path,
    run_crash_subprocess: CrashRunner,
    point: str,
    file_expected: bool,
    row_expected: bool,
) -> None:
    ref = _seed_old_unreachable_blob(store_root, b"crash candidate")
    script = CRASH_SCRIPT.format(root=str(store_root))
    proc = run_crash_subprocess(script, crash_point=point)
    assert proc.returncode == 42, proc.stderr

    with Database.connect(store_root / "state.db") as db:
        store = BlobStore(store_root, db)
        assert store.path_for(ref).exists() == file_expected
        row = db.conn.execute("SELECT 1 FROM blobs WHERE hash = ?", (ref,)).fetchone()
        assert (row is not None) == row_expected
        # The crashed collector's exclusive deletion lease is left behind.
        leases = db.conn.execute("SELECT mode FROM leases").fetchall()
        assert [str(lease["mode"]) for lease in leases] == ["exclusive"]

        # Recovery = re-collect: identical end state regardless of crash point.
        gc = Gc(store_root, db)
        report = gc.collect()
        assert not store.path_for(ref).exists()
        assert db.conn.execute("SELECT COUNT(*) FROM blobs").fetchone()[0] == 0
        assert db.conn.execute("SELECT COUNT(*) FROM leases").fetchone()[0] == 0
        if row_expected:
            assert actions_by_ref(report) == {ref: GcAction.COLLECTED}
        else:
            assert report.candidates == ()


def test_crash_subprocess_completes_without_crash_point(
    store_root: Path, run_crash_subprocess: CrashRunner
) -> None:
    ref = _seed_old_unreachable_blob(store_root, b"crash candidate")
    script = CRASH_SCRIPT.format(root=str(store_root))
    proc = run_crash_subprocess(script, crash_point=None)
    assert proc.returncode == 0, proc.stderr
    with Database.connect(store_root / "state.db") as db:
        assert not BlobStore(store_root, db).has(ref)
        assert db.conn.execute("SELECT COUNT(*) FROM leases").fetchone()[0] == 0
