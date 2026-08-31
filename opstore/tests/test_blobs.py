"""Tests for opstore.blobs: put/get/dedup, pointers cas_swap, fsync path, crash injection."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from _optest import CrashRunner, FakeClock
from hypothesis import given
from hypothesis import strategies as st
from opstore.blobs import (
    CRASH_AFTER_DB_INSERT,
    CRASH_AFTER_DIR_FSYNC,
    CRASH_AFTER_FILE_FSYNC,
    CRASH_AFTER_RENAME,
    BlobStore,
)
from opstore.db import Database
from opstore.errors import ConflictedError, NotFoundError
from opstore.hashing import hex_of, sha256_bytes


@pytest.fixture
def blobs(store_root: Path, db: Database, fake_clock: FakeClock) -> BlobStore:
    return BlobStore(store_root, db, clock=fake_clock)


def test_put_get_roundtrip(blobs: BlobStore) -> None:
    data = b"hello opstore"
    blob_hash = blobs.put(data)
    assert blob_hash == sha256_bytes(data)
    assert blobs.get(blob_hash) == data
    assert blobs.has(blob_hash)
    assert blobs.size(blob_hash) == len(data)
    assert blobs.retention_class(blob_hash) == "default"
    with blobs.open_stream(blob_hash) as fh:
        assert fh.read() == data


def test_blob_path_layout_and_no_temp_leftovers(blobs: BlobStore, store_root: Path) -> None:
    blob_hash = blobs.put(b"payload")
    digest = hex_of(blob_hash)
    expected = store_root / "blobs" / "sha256" / digest[:2] / digest
    assert blobs.path_for(blob_hash) == expected
    assert expected.is_file()
    assert expected.read_bytes() == b"payload"
    leftovers = [p for p in expected.parent.iterdir() if p.name.startswith(".")]
    assert leftovers == []


def test_concurrent_puts_of_the_same_bytes_do_not_raise(
    blobs: BlobStore, store_root: Path, db: Database
) -> None:
    """Two threads putting the same hash must both return, not FileExistsError.

    ``Publisher.freeze_inputs`` releases the part lock before geometry runs, so
    two sessions may build the same part at once and both ``put`` the same
    artifact bytes. The temp file used to be ``.{digest}.{pid}.tmp`` — unique
    across processes, not across threads — and the second ``O_CREAT|O_EXCL``
    crashed ``test_two_concurrent_runs_each_read_their_own_request``.
    """
    lock = threading.Lock()
    last_hash = ""
    for index in range(40):
        # Fresh bytes each pair so both threads still race on a missing file.
        # Repeating one payload would make iteration 2+ a no-op exists() check.
        payload = f"identical concurrent artifact {index}".encode()
        failures: list[BaseException] = []
        hashes: list[str] = []
        both_in = threading.Barrier(2, timeout=10)

        def turn(data: bytes = payload, gate: threading.Barrier = both_in) -> None:
            gate.wait()
            try:
                blob_hash = blobs.put(data)
            except BaseException as exc:  # pragma: no cover - the regression itself
                with lock:
                    failures.append(exc)
                return
            with lock:
                hashes.append(blob_hash)

        threads = [threading.Thread(target=turn) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        assert failures == [], repr(failures[0])
        assert len(hashes) == 2
        assert hashes[0] == hashes[1] == sha256_bytes(payload)
        last_hash = hashes[0]

    digest = hex_of(last_hash)
    final = store_root / "blobs" / "sha256" / digest[:2] / digest
    assert final.is_file()
    leftovers = [
        p for p in (store_root / "blobs").rglob("*") if p.is_file() and p.name.startswith(".")
    ]
    assert leftovers == []
    rows = db.conn.execute("SELECT hash FROM blobs WHERE hash = ?", (last_hash,)).fetchall()
    assert len(rows) == 1


def test_dedup_single_file_single_row(
    blobs: BlobStore, fake_clock: FakeClock, db: Database
) -> None:
    first = blobs.put(b"same bytes")
    created_at = db.conn.execute(
        "SELECT created_at FROM blobs WHERE hash = ?", (first,)
    ).fetchone()["created_at"]
    fake_clock.advance(100.0)
    second = blobs.put(b"same bytes", retention_class="preview")
    assert first == second
    rows = db.conn.execute("SELECT * FROM blobs").fetchall()
    assert len(rows) == 1
    # Dedup keeps the original row (created_at and retention_class unchanged).
    assert rows[0]["created_at"] == created_at
    assert rows[0]["retention_class"] == "default"


def test_retention_class_recorded(blobs: BlobStore) -> None:
    blob_hash = blobs.put(b"preview bytes", retention_class="preview")
    assert blobs.retention_class(blob_hash) == "preview"


def test_missing_blob_errors(blobs: BlobStore) -> None:
    missing = sha256_bytes(b"never stored")
    assert not blobs.has(missing)
    for call in (blobs.get, blobs.open_stream, blobs.size, blobs.retention_class):
        with pytest.raises(NotFoundError) as excinfo:
            call(missing)
        assert excinfo.value.code == "not_found"


def test_remove_for_gc(blobs: BlobStore) -> None:
    blob_hash = blobs.put(b"doomed")
    blobs.remove(blob_hash)
    assert not blobs.has(blob_hash)
    assert not blobs.path_for(blob_hash).exists()
    with pytest.raises(NotFoundError):
        blobs.size(blob_hash)


def test_cas_swap_create_read_swap(blobs: BlobStore) -> None:
    a = blobs.put(b"a")
    b = blobs.put(b"b")
    assert blobs.read_pointer("current") is None
    blobs.cas_swap("current", None, a)
    assert blobs.read_pointer("current") == a
    blobs.cas_swap("current", a, b)
    assert blobs.read_pointer("current") == b


def test_cas_swap_mismatch_conflicts_without_change(blobs: BlobStore) -> None:
    a = blobs.put(b"a")
    b = blobs.put(b"b")
    blobs.cas_swap("ptr", None, a)
    with pytest.raises(ConflictedError) as excinfo:
        blobs.cas_swap("ptr", b, b)  # stale expectation
    assert excinfo.value.code == "conflicted"
    assert blobs.read_pointer("ptr") == a
    with pytest.raises(ConflictedError):
        blobs.cas_swap("ptr", None, b)  # expected-absent but present
    with pytest.raises(ConflictedError):
        blobs.cas_swap("other", a, b)  # expected-present but absent
    assert blobs.read_pointer("other") is None


def test_cas_swap_delete(blobs: BlobStore) -> None:
    a = blobs.put(b"a")
    blobs.cas_swap("ptr", None, a)
    with pytest.raises(ConflictedError):
        blobs.cas_swap("ptr", None, None)
    blobs.cas_swap("ptr", a, None)
    assert blobs.read_pointer("ptr") is None


@given(st.lists(st.binary(min_size=0, max_size=2048), max_size=8))
def test_put_get_property(tmp_path_factory: pytest.TempPathFactory, payloads: list[bytes]) -> None:
    root = tmp_path_factory.mktemp("blobprop")
    with Database.connect(root / "state.db") as db:
        store = BlobStore(root, db)
        hashes = [store.put(p) for p in payloads]
        for payload, blob_hash in zip(payloads, hashes, strict=True):
            assert blob_hash == sha256_bytes(payload)
            assert store.get(blob_hash) == payload
            assert store.size(blob_hash) == len(payload)
        unique_rows = db.conn.execute("SELECT COUNT(*) FROM blobs").fetchone()[0]
        assert unique_rows == len(set(hashes))


CRASH_SCRIPT = """
from pathlib import Path
from opstore.blobs import BlobStore
from opstore.db import Database
from opstore.types import EnvCrashHook
root = Path({root!r})
with Database.connect(root / "state.db") as db:
    BlobStore(root, db, crash_hook=EnvCrashHook()).put(b"crash payload")
"""


@pytest.mark.parametrize(
    ("point", "file_expected", "row_expected"),
    [
        (CRASH_AFTER_FILE_FSYNC, False, False),
        (CRASH_AFTER_RENAME, True, False),
        (CRASH_AFTER_DIR_FSYNC, True, False),
        (CRASH_AFTER_DB_INSERT, True, True),
    ],
)
def test_crash_injection_put_then_recover(
    store_root: Path,
    run_crash_subprocess: CrashRunner,
    point: str,
    file_expected: bool,
    row_expected: bool,
) -> None:
    data = b"crash payload"
    blob_hash = sha256_bytes(data)
    script = CRASH_SCRIPT.format(root=str(store_root))
    proc = run_crash_subprocess(script, crash_point=point)
    assert proc.returncode == 42, proc.stderr

    with Database.connect(store_root / "state.db") as db:
        store = BlobStore(store_root, db)
        assert store.path_for(blob_hash).exists() == file_expected
        row = db.conn.execute("SELECT 1 FROM blobs WHERE hash = ?", (blob_hash,)).fetchone()
        assert (row is not None) == row_expected
        assert store.has(blob_hash) == (file_expected and row_expected)
        # Recovery = re-put: identical outcome regardless of crash point.
        assert store.put(data) == blob_hash
        assert store.has(blob_hash)
        assert store.get(blob_hash) == data
        assert store.size(blob_hash) == len(data)


def test_crash_subprocess_completes_without_crash_point(
    store_root: Path, run_crash_subprocess: CrashRunner
) -> None:
    script = CRASH_SCRIPT.format(root=str(store_root))
    proc = run_crash_subprocess(script, crash_point=None)
    assert proc.returncode == 0, proc.stderr
    with Database.connect(store_root / "state.db") as db:
        store = BlobStore(store_root, db)
        assert store.get(sha256_bytes(b"crash payload")) == b"crash payload"
