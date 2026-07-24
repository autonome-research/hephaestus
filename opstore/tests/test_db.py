"""Tests for opstore.db: pragmas, schema installation, migrations, transactions."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from opstore.db import SCHEMA_VERSION, Database

EXPECTED_TABLES = {
    "meta",
    "operations",
    "tombstones",
    "pointers",
    "blobs",
    "leases",
    "admissions",
    "resume_queue",
    "terminals",
    "pins",
    "links",
}


def table_names(db: Database) -> set[str]:
    rows = db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {str(row["name"]) for row in rows}


def test_connect_creates_file_and_full_schema(db: Database, store_root: Path) -> None:
    assert (store_root / "state.db").exists()
    assert table_names(db) == EXPECTED_TABLES
    assert db.schema_version() == SCHEMA_VERSION


def test_pragmas(db: Database) -> None:
    assert db.conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert db.conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    assert db.conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_reopen_is_idempotent(store_root: Path) -> None:
    path = store_root / "state.db"
    with Database.connect(path) as first:
        first.conn.execute("SELECT 1")
    with Database.connect(path) as again:
        assert table_names(again) == EXPECTED_TABLES
        assert again.schema_version() == SCHEMA_VERSION


def test_schema_columns_match_design(db: Database) -> None:
    def cols(table: str) -> list[str]:
        return [str(r["name"]) for r in db.conn.execute(f"PRAGMA table_info({table})")]

    assert cols("operations") == [
        "op_key",
        "raw_id",
        "key_id",
        "ts",
        "payload_hash",
        "state",
        "target_path",
        "before_hash",
        "after_hash",
        "preimage_blob",
        "candidate_blob",
        "intended_outcome",
        "response",
        "created_at",
        "committed_at",
    ]
    assert cols("tombstones") == [
        "op_key",
        "payload_hash",
        "terminal_state",
        "commit_hash",
        "created_at",
        "expires_at",
    ]
    assert cols("pointers") == ["name", "blob_hash", "updated_at"]
    assert cols("blobs") == ["hash", "size", "created_at", "retention_class"]
    assert cols("leases") == [
        "lease_id",
        "ref",
        "mode",
        "owner_pid",
        "owner_start_ns",
        "ttl_s",
        "heartbeat_at",
        "created_at",
    ]
    assert cols("admissions") == [
        "run_id",
        "state",
        "suspended",
        "deadline_at",
        "admitted_at",
        "terminal_id",
        "terminal_acked_at",
        "owner_pid",
        "owner_start_ns",
    ]
    assert cols("resume_queue") == ["seq", "run_id", "requested_at"]
    assert cols("terminals") == [
        "run_id",
        "kind",
        "terminal_id",
        "payload_hash",
        "payload",
        "created_at",
    ]
    assert cols("pins") == ["ref", "created_at"]
    assert cols("links") == ["from_ref", "to_ref"]


def test_state_check_constraints(db: Database) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        db.conn.execute(
            "INSERT INTO operations(op_key, raw_id, key_id, ts, payload_hash, state, created_at) "
            "VALUES('k', 'r', 'kid', 0, 'h', 'BOGUS', 0)"
        )
    with pytest.raises(sqlite3.IntegrityError):
        db.conn.execute(
            "INSERT INTO leases(lease_id, ref, mode, owner_pid, owner_start_ns, ttl_s, "
            "heartbeat_at, created_at) VALUES('l', 'r', 'bogus', 1, 1, 1, 0, 0)"
        )
    with pytest.raises(sqlite3.IntegrityError):
        db.conn.execute(
            "INSERT INTO admissions(run_id, state, admitted_at) VALUES('r', 'BOGUS', 0)"
        )


def test_transaction_commit_and_rollback(db: Database) -> None:
    with db.transaction() as conn:
        conn.execute("INSERT INTO pins(ref, created_at) VALUES('a', 0)")
    assert db.conn.execute("SELECT COUNT(*) FROM pins").fetchone()[0] == 1

    with pytest.raises(RuntimeError), db.transaction() as conn:
        conn.execute("INSERT INTO pins(ref, created_at) VALUES('b', 0)")
        raise RuntimeError("boom")
    assert db.conn.execute("SELECT COUNT(*) FROM pins").fetchone()[0] == 1
    assert not db.conn.in_transaction


def test_transaction_uses_begin_immediate(db: Database, store_root: Path) -> None:
    other = Database.connect(store_root / "state.db")
    try:
        other.conn.execute("PRAGMA busy_timeout=50")
        with db.transaction(), pytest.raises(sqlite3.OperationalError):
            other.conn.execute("BEGIN IMMEDIATE")
    finally:
        other.close()


def test_nested_transaction_rejected(db: Database) -> None:
    with db.transaction(), pytest.raises(sqlite3.OperationalError), db.transaction():
        pass  # pragma: no cover
    assert not db.conn.in_transaction


def test_cross_process_visibility(db: Database, store_root: Path) -> None:
    with db.transaction() as conn:
        conn.execute("INSERT INTO pins(ref, created_at) VALUES('shared', 1)")
    with Database.connect(store_root / "state.db") as other:
        row = other.conn.execute("SELECT created_at FROM pins WHERE ref = 'shared'").fetchone()
        assert row is not None and row["created_at"] == 1
