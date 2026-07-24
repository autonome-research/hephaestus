"""End-to-end facade test: one OpStore instance drives WAL, admission, and GC.

Covers the integration contract:

- ``OpStore.create`` wires Database/Keyring/Blobs/OpKeys/Wal/Leases/Admission/Gc
  over one root and one connection;
- an idempotent WAL mutation replays (same key + payload → recorded response,
  never re-execution);
- a full admit → dispatch → terminal → ack slot cycle;
- a pin + GC cycle (pinned blob survives, unreachable expired blob is
  collected, opkeys purge hook runs) — all across ONE OpStore instance;
- ``create``/``open`` honor the keyring fail-closed contract.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from opstore import (
    ConflictedError,
    Fresh,
    KeyringMissingError,
    NotFoundError,
    OpStore,
    Replay,
    StoreConfig,
    TerminalState,
    sha256_bytes,
    sha256_canonical_json,
)


class FakeClock:
    """Deterministic injectable clock (advance() ages blobs past retention)."""

    def __init__(self, start: float = 1_700_000_000.0) -> None:
        self._now = start

    def now(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


def test_end_to_end_single_instance(tmp_path: Path) -> None:
    clock = FakeClock()
    config = StoreConfig(retention_s=100.0, preview_retention_s=10.0)
    store = OpStore.create(tmp_path / "store", config, clock=clock)
    try:
        # -- idempotent WAL mutation with replay ---------------------------
        payload = {"path": "parts/shelf.py", "content": "WIDTH = 420\n"}
        payload_hash = sha256_canonical_json(payload)
        fresh = store.opkeys.begin("tool-call-1", payload_hash)
        assert isinstance(fresh, Fresh)
        target = tmp_path / "files" / "shelf.py"
        outcome = store.wal.execute(
            fresh, target, b"WIDTH = 420\n", intended_outcome='{"ok": true}'
        )
        assert outcome.action == "committed"
        assert target.read_bytes() == b"WIDTH = 420\n"

        retry = store.opkeys.begin("tool-call-1", payload_hash)
        assert isinstance(retry, Replay)
        assert retry.response == '{"ok": true}'
        assert retry.commit_hash == sha256_bytes(b"WIDTH = 420\n")
        assert target.read_bytes() == b"WIDTH = 420\n"  # no re-execution

        # -- admission / terminal / ack cycle ------------------------------
        store.admission.admit("run-1", deadline_at=clock.now() + 3600.0)
        store.admission.dispatch("run-1")
        assert store.admission.active_count() == 1
        record = store.admission.insert_terminal(
            "run-1", "terminal-1", TerminalState.COMPLETED, {"artifacts": 1}
        )
        assert store.admission.active_count() == 1  # unacked terminal still occupies
        store.admission.acknowledge_terminal("run-1", record.terminal_id)
        assert store.admission.active_count() == 0
        assert store.admission.occupied_run_ids() == frozenset()

        # -- pin + GC cycle -------------------------------------------------
        pinned = store.blobs.put(b"pinned artifact")
        doomed = store.blobs.put(b"unreachable artifact")
        store.gc.pin(pinned)
        clock.advance(200.0)  # past retention_s=100 for both blobs

        report = store.gc.collect()
        assert not report.dry_run
        collected = {c.ref for c in report.candidates if c.action.value == "collected"}
        assert doomed in collected
        assert pinned not in collected
        assert store.blobs.has(pinned)
        assert not store.blobs.has(doomed)
        assert store.blobs.get(pinned) == b"pinned artifact"

        # replay still works after GC (operation row inside idempotency window)
        again = store.opkeys.begin("tool-call-1", payload_hash)
        assert isinstance(again, Replay)
        assert again.response == '{"ok": true}'
    finally:
        store.close()

    # -- reopen + startup recovery over the same root ----------------------
    reopened = OpStore.open(tmp_path / "store", config, clock=clock)
    try:
        recovery = reopened.recover()
        assert recovery.wal == ()
        assert recovery.admission.available_slots == config.run_slots
        assert reopened.keyring.active_key_id == reopened.keyring.key_ids()[0]
    finally:
        reopened.close()


def test_create_refuses_existing_store(tmp_path: Path) -> None:
    root = tmp_path / "store"
    OpStore.create(root).close()
    with pytest.raises(ConflictedError):
        OpStore.create(root)


def test_open_requires_existing_state(tmp_path: Path) -> None:
    with pytest.raises(NotFoundError):
        OpStore.open(tmp_path / "missing")


def test_open_fails_closed_without_keyring(tmp_path: Path) -> None:
    root = tmp_path / "store"
    OpStore.create(root).close()
    shutil.rmtree(root / "keys")  # simulate lost keyring with existing state
    with pytest.raises(KeyringMissingError):
        OpStore.open(root)
