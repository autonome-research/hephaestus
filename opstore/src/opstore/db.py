"""SQLite connection management, transactions, and versioned migrations.

Contract (DESIGN.md): WAL journal mode, ``busy_timeout=5000``,
``foreign_keys=ON``; every multi-step transition runs inside ``BEGIN
IMMEDIATE``. This module owns the COMPLETE schema — no other module may issue
``CREATE TABLE``. Migrations are a versioned list applied under ``BEGIN
IMMEDIATE`` with the current version stored in ``meta['schema_version']``.
Cross-process correctness relies on SQLite transactions, not in-process locks.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from types import TracebackType

BUSY_TIMEOUT_MS = 5000

_SCHEMA_V1: tuple[str, ...] = (
    """
    CREATE TABLE operations(
      op_key TEXT PRIMARY KEY, raw_id TEXT NOT NULL, key_id TEXT NOT NULL,
      ts REAL NOT NULL, payload_hash TEXT NOT NULL,
      state TEXT NOT NULL CHECK(state IN ('PREPARED','COMMITTED','CONFLICTED')),
      target_path TEXT, before_hash TEXT, after_hash TEXT,
      preimage_blob TEXT, candidate_blob TEXT,
      intended_outcome TEXT, response TEXT,
      created_at REAL NOT NULL, committed_at REAL)
    """,
    """
    CREATE TABLE tombstones(
      op_key TEXT PRIMARY KEY, payload_hash TEXT NOT NULL,
      terminal_state TEXT NOT NULL, commit_hash TEXT,
      created_at REAL NOT NULL, expires_at REAL NOT NULL)
    """,
    """
    CREATE TABLE pointers(name TEXT PRIMARY KEY, blob_hash TEXT NOT NULL,
      updated_at REAL NOT NULL)
    """,
    """
    CREATE TABLE blobs(hash TEXT PRIMARY KEY, size INTEGER NOT NULL,
      created_at REAL NOT NULL, retention_class TEXT NOT NULL DEFAULT 'default')
    """,
    """
    CREATE TABLE leases(
      lease_id TEXT PRIMARY KEY, ref TEXT NOT NULL,
      mode TEXT NOT NULL CHECK(mode IN ('shared','exclusive')),
      owner_pid INTEGER NOT NULL, owner_start_ns INTEGER NOT NULL,
      ttl_s REAL NOT NULL, heartbeat_at REAL NOT NULL, created_at REAL NOT NULL)
    """,
    """
    CREATE TABLE admissions(
      run_id TEXT PRIMARY KEY,
      state TEXT NOT NULL CHECK(state IN
        ('ADMITTED','DISPATCHED','CANCEL_REQUESTED','TERMINAL')),
      suspended INTEGER NOT NULL DEFAULT 0,
      deadline_at REAL, admitted_at REAL NOT NULL,
      terminal_id TEXT, terminal_acked_at REAL,
      owner_pid INTEGER, owner_start_ns INTEGER)
    """,
    """
    CREATE TABLE resume_queue(
      seq INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL UNIQUE,
      requested_at REAL NOT NULL)
    """,
    """
    CREATE TABLE terminals(
      run_id TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'terminal',
      terminal_id TEXT NOT NULL, payload_hash TEXT NOT NULL, payload TEXT NOT NULL,
      created_at REAL NOT NULL, PRIMARY KEY(run_id, kind))
    """,
    """
    CREATE TABLE pins(ref TEXT PRIMARY KEY, created_at REAL NOT NULL)
    """,
    """
    CREATE TABLE links(from_ref TEXT NOT NULL, to_ref TEXT NOT NULL,
      PRIMARY KEY(from_ref, to_ref))
    """,
)

MIGRATIONS: tuple[tuple[int, tuple[str, ...]], ...] = ((1, _SCHEMA_V1),)

SCHEMA_VERSION = MIGRATIONS[-1][0]


class Database:
    """A single opstore SQLite connection with the fixed pragma/transaction discipline."""

    def __init__(self, conn: sqlite3.Connection, path: Path) -> None:
        self.conn = conn
        self.path = path

    @classmethod
    def connect(cls, path: Path) -> Database:
        """Open (creating if absent) ``path`` and apply pending migrations."""
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=FULL")
        db = cls(conn, path)
        db._migrate()
        return db

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection]:
        """``BEGIN IMMEDIATE`` transaction: commits on success, rolls back on error.

        Nesting is a programming error and raises ``sqlite3.OperationalError``.
        """
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.conn
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        else:
            self.conn.execute("COMMIT")

    def schema_version(self) -> int:
        row = self.conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
        return 0 if row is None else int(row["value"])

    def _migrate(self) -> None:
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        with self.transaction() as conn:
            current = self.schema_version()
            for version, statements in MIGRATIONS:
                if version <= current:
                    continue
                for statement in statements:
                    conn.execute(statement)
                conn.execute(
                    "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (str(version),),
                )
