"""Content-addressed blob store under ``<root>/blobs/`` plus named CAS pointers.

Contract (DESIGN.md "blobs.py" + fsync discipline):

- ``put(data) -> "sha256:<hex>"`` dedups by content hash and stores at
  ``<root>/blobs/sha256/<first2>/<hex>``. Writes go to a same-directory temp
  file which is fsynced, atomically renamed into place, and followed by a
  parent-directory fsync before the accounting row is committed. Blob files are
  deleted only by gc.py.
- Crash points (``CrashHook``): ``blobs.put.after_file_fsync``,
  ``blobs.put.after_rename``, ``blobs.put.after_dir_fsync``,
  ``blobs.put.after_db_insert``. Recovery is re-``put``: a durable file without
  a row is adopted; a temp orphan is invisible and rewritten.
- Named pointers: ``cas_swap(name, expected_hash | None, new_hash | None)``
  compare-and-swaps inside ``BEGIN IMMEDIATE``; a stale expectation raises
  ``ConflictedError`` (code ``conflicted``). ``new_hash=None`` deletes.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO

from opstore.db import Database
from opstore.errors import ConflictedError, NotFoundError
from opstore.hashing import hex_of, sha256_bytes
from opstore.types import Clock, CrashHook, NoopCrashHook, SystemClock

BLOBS_DIRNAME = "blobs"

CRASH_AFTER_FILE_FSYNC = "blobs.put.after_file_fsync"
CRASH_AFTER_RENAME = "blobs.put.after_rename"
CRASH_AFTER_DIR_FSYNC = "blobs.put.after_dir_fsync"
CRASH_AFTER_DB_INSERT = "blobs.put.after_db_insert"


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class BlobStore:
    """CAS blob storage with fsync discipline, dedup, and named pointers."""

    def __init__(
        self,
        root: Path,
        db: Database,
        clock: Clock | None = None,
        crash_hook: CrashHook | None = None,
    ) -> None:
        self._root = root
        self._db = db
        self._clock = clock or SystemClock()
        self._crash = crash_hook or NoopCrashHook()

    def path_for(self, blob_hash: str) -> Path:
        """Filesystem path a (well-formed) blob hash addresses."""
        digest = hex_of(blob_hash)
        return self._root / BLOBS_DIRNAME / "sha256" / digest[:2] / digest

    def put(self, data: bytes, retention_class: str = "default") -> str:
        """Store ``data``; returns its hash. Idempotent (content-addressed dedup)."""
        blob_hash = sha256_bytes(data)
        final = self.path_for(blob_hash)
        if not final.exists():
            final.parent.mkdir(parents=True, exist_ok=True)
            tmp = final.parent / f".{final.name}.{os.getpid()}.tmp"
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            try:
                os.write(fd, data)
                os.fsync(fd)
            finally:
                os.close(fd)
            self._crash.maybe_crash(CRASH_AFTER_FILE_FSYNC)
            os.rename(tmp, final)
            self._crash.maybe_crash(CRASH_AFTER_RENAME)
            _fsync_dir(final.parent)
            self._crash.maybe_crash(CRASH_AFTER_DIR_FSYNC)
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO blobs(hash, size, created_at, retention_class) "
                "VALUES(?, ?, ?, ?) ON CONFLICT(hash) DO NOTHING",
                (blob_hash, len(data), self._clock.now(), retention_class),
            )
        self._crash.maybe_crash(CRASH_AFTER_DB_INSERT)
        return blob_hash

    def has(self, blob_hash: str) -> bool:
        """True iff the blob is fully committed (accounting row and file both exist)."""
        row = self._db.conn.execute("SELECT 1 FROM blobs WHERE hash = ?", (blob_hash,)).fetchone()
        return row is not None and self.path_for(blob_hash).exists()

    def get(self, blob_hash: str) -> bytes:
        """Blob contents, or ``NotFoundError``."""
        with self.open_stream(blob_hash) as fh:
            return fh.read()

    def open_stream(self, blob_hash: str) -> BinaryIO:
        """Open the blob for streamed reading, or ``NotFoundError``."""
        try:
            return self.path_for(blob_hash).open("rb")
        except FileNotFoundError as exc:
            raise NotFoundError(f"blob {blob_hash} not found") from exc

    def size(self, blob_hash: str) -> int:
        """Recorded blob size in bytes, or ``NotFoundError``."""
        row = self._db.conn.execute(
            "SELECT size FROM blobs WHERE hash = ?", (blob_hash,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"blob {blob_hash} not found")
        return int(row["size"])

    def retention_class(self, blob_hash: str) -> str:
        """Recorded retention class, or ``NotFoundError``."""
        row = self._db.conn.execute(
            "SELECT retention_class FROM blobs WHERE hash = ?", (blob_hash,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"blob {blob_hash} not found")
        return str(row["retention_class"])

    def read_pointer(self, name: str) -> str | None:
        """Current blob hash the named pointer addresses, or None."""
        row = self._db.conn.execute(
            "SELECT blob_hash FROM pointers WHERE name = ?", (name,)
        ).fetchone()
        return None if row is None else str(row["blob_hash"])

    def cas_swap(self, name: str, expected_hash: str | None, new_hash: str | None) -> None:
        """Compare-and-swap the named pointer inside one ``BEGIN IMMEDIATE``.

        ``expected_hash=None`` requires the pointer to be absent (create);
        ``new_hash=None`` deletes the pointer. A stale expectation raises
        ``ConflictedError`` without modifying anything.
        """
        with self._db.transaction() as conn:
            row = conn.execute("SELECT blob_hash FROM pointers WHERE name = ?", (name,)).fetchone()
            current: str | None = None if row is None else str(row["blob_hash"])
            if current != expected_hash:
                raise ConflictedError(
                    f"pointer {name!r} is {current!r}, expected {expected_hash!r}"
                )
            if new_hash is None:
                conn.execute("DELETE FROM pointers WHERE name = ?", (name,))
            else:
                conn.execute(
                    "INSERT INTO pointers(name, blob_hash, updated_at) VALUES(?, ?, ?) "
                    "ON CONFLICT(name) DO UPDATE SET "
                    "blob_hash = excluded.blob_hash, updated_at = excluded.updated_at",
                    (name, new_hash, self._clock.now()),
                )

    def remove(self, blob_hash: str) -> None:
        """Unlink a blob file and drop its row. FOR gc.py ONLY (deletion-lease holder)."""
        path = self.path_for(blob_hash)
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM blobs WHERE hash = ?", (blob_hash,))
        path.unlink(missing_ok=True)
        if path.parent.is_dir():
            _fsync_dir(path.parent)
