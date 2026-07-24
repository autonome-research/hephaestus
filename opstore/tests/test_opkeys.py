"""Tests for opstore.opkeys: key normalization, begin outcomes, tombstone horizons."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import FakeClock
from hypothesis import given, settings
from hypothesis import strategies as st
from opstore.db import Database
from opstore.errors import (
    KeyExpiredError,
    KeyPayloadMismatchError,
    KeyTimestampSkewError,
)
from opstore.hashing import sha256_bytes
from opstore.keyring import Keyring
from opstore.opkeys import (
    Fresh,
    OpKeys,
    PendingRecovery,
    Replay,
    format_ts,
    parse_key,
)
from opstore.types import StoreConfig

CONFIG = StoreConfig()
WINDOW = CONFIG.idempotency_window_s
MARGIN = CONFIG.tombstone_margin_s
SKEW = CONFIG.freshness_skew_s

PAYLOAD = sha256_bytes(b"payload-a")
OTHER_PAYLOAD = sha256_bytes(b"payload-b")
COMMIT_HASH = sha256_bytes(b"committed contents")


@pytest.fixture
def keyring(store_root: Path, fake_clock: FakeClock) -> Keyring:
    return Keyring.create(store_root, clock=fake_clock)


@pytest.fixture
def opkeys(db: Database, keyring: Keyring, fake_clock: FakeClock) -> OpKeys:
    return OpKeys(db, keyring, clock=fake_clock)


def _mark_committed(
    db: Database, op_key: str, response: str = "resp", after_hash: str | None = COMMIT_HASH
) -> None:
    with db.transaction() as conn:
        conn.execute(
            "UPDATE operations SET state = 'COMMITTED', response = ?, after_hash = ?, "
            "committed_at = ts WHERE op_key = ?",
            (response, after_hash, op_key),
        )


def _mark_conflicted(db: Database, op_key: str) -> None:
    with db.transaction() as conn:
        conn.execute("UPDATE operations SET state = 'CONFLICTED' WHERE op_key = ?", (op_key,))


def test_fresh_registers_skeleton_row(
    opkeys: OpKeys, db: Database, keyring: Keyring, fake_clock: FakeClock
) -> None:
    outcome = opkeys.begin("raw-1", PAYLOAD)
    assert isinstance(outcome, Fresh)
    assert outcome.raw_id == "raw-1"
    assert outcome.key_id == keyring.active_key_id
    assert outcome.ts == fake_clock.now()
    row = db.conn.execute("SELECT * FROM operations WHERE op_key = ?", (outcome.op_key,)).fetchone()
    assert row is not None
    assert row["raw_id"] == "raw-1"
    assert row["state"] == "PREPARED"
    assert row["payload_hash"] == PAYLOAD
    assert row["target_path"] is None
    parsed = parse_key(outcome.op_key)
    assert parsed.ts == outcome.ts
    assert parsed.key_id == keyring.active_key_id
    assert opkeys.verify_key(outcome.op_key, "raw-1")
    assert not opkeys.verify_key(outcome.op_key, "raw-other")


def test_normalize_deterministic_and_key_format(opkeys: OpKeys, fake_clock: FakeClock) -> None:
    ts = fake_clock.now() + 0.5
    key_a = opkeys.normalize("raw-x", ts)
    key_b = opkeys.normalize("raw-x", ts)
    assert key_a == key_b
    assert key_a.startswith(f"v1.{format_ts(ts)}.")
    assert key_a != opkeys.normalize("raw-y", ts)
    assert key_a != opkeys.normalize("raw-x", ts + 1.0)


def test_parse_key_rejects_malformed(opkeys: OpKeys) -> None:
    for bad in ("", "v2.1.0.k.mac", "v1.notafloat.k.mac", "v1.1.0"):
        with pytest.raises(ValueError):
            parse_key(bad)
        assert not opkeys.verify_key(bad, "raw")


def test_replay_committed_row(opkeys: OpKeys, db: Database) -> None:
    fresh = opkeys.begin("raw-1", PAYLOAD)
    assert isinstance(fresh, Fresh)
    _mark_committed(db, fresh.op_key, response="the-response")
    replay = opkeys.begin("raw-1", PAYLOAD)
    assert isinstance(replay, Replay)
    assert replay.op_key == fresh.op_key
    assert replay.terminal_state == "COMMITTED"
    assert replay.response == "the-response"
    assert replay.commit_hash == COMMIT_HASH
    assert not replay.from_tombstone


def test_payload_mismatch_on_row(opkeys: OpKeys, db: Database) -> None:
    fresh = opkeys.begin("raw-1", PAYLOAD)
    assert isinstance(fresh, Fresh)
    with pytest.raises(KeyPayloadMismatchError) as excinfo:
        opkeys.begin("raw-1", OTHER_PAYLOAD)
    assert excinfo.value.code == "key_payload_mismatch"
    _mark_committed(db, fresh.op_key)
    with pytest.raises(KeyPayloadMismatchError):
        opkeys.begin("raw-1", OTHER_PAYLOAD)


def test_prepared_row_returns_pending_recovery(opkeys: OpKeys) -> None:
    fresh = opkeys.begin("raw-1", PAYLOAD)
    assert isinstance(fresh, Fresh)
    again = opkeys.begin("raw-1", PAYLOAD)
    assert isinstance(again, PendingRecovery)
    assert again.op_key == fresh.op_key


def test_conflicted_row_replays_terminal_state(opkeys: OpKeys, db: Database) -> None:
    fresh = opkeys.begin("raw-1", PAYLOAD)
    assert isinstance(fresh, Fresh)
    _mark_conflicted(db, fresh.op_key)
    replay = opkeys.begin("raw-1", PAYLOAD)
    assert isinstance(replay, Replay)
    assert replay.terminal_state == "CONFLICTED"
    assert replay.response is None


def test_first_seen_skew_boundary(opkeys: OpKeys, fake_clock: FakeClock) -> None:
    now = fake_clock.now()
    ok_past = opkeys.begin("raw-past", PAYLOAD, ts=now - SKEW)
    assert isinstance(ok_past, Fresh)
    ok_future = opkeys.begin("raw-future", PAYLOAD, ts=now + SKEW)
    assert isinstance(ok_future, Fresh)
    with pytest.raises(KeyTimestampSkewError) as excinfo:
        opkeys.begin("raw-past-skew", PAYLOAD, ts=now - SKEW - 0.001)
    assert excinfo.value.code == "key_timestamp_skew"
    with pytest.raises(KeyTimestampSkewError):
        opkeys.begin("raw-future-skew", PAYLOAD, ts=now + SKEW + 0.001)


def test_first_seen_inside_window_but_stale_is_skew(opkeys: OpKeys, fake_clock: FakeClock) -> None:
    with pytest.raises(KeyTimestampSkewError):
        opkeys.begin("raw-1", PAYLOAD, ts=fake_clock.now() - 8 * 86_400.0)


def test_first_seen_older_than_window_is_expired(opkeys: OpKeys, fake_clock: FakeClock) -> None:
    with pytest.raises(KeyExpiredError) as excinfo:
        opkeys.begin("raw-1", PAYLOAD, ts=fake_clock.now() - WINDOW - 1.0)
    assert excinfo.value.code == "key_expired"


def test_recognized_key_replays_through_full_window(
    opkeys: OpKeys, db: Database, fake_clock: FakeClock
) -> None:
    fresh = opkeys.begin("raw-1", PAYLOAD)
    assert isinstance(fresh, Fresh)
    _mark_committed(db, fresh.op_key, response="old-response")
    fake_clock.advance(WINDOW)  # exactly the 30d window edge: still replayable
    replay = opkeys.begin("raw-1", PAYLOAD)
    assert isinstance(replay, Replay)
    assert replay.response == "old-response"
    # An explicit stale ts is fine for recognized keys (no freshness check).
    replay = opkeys.begin("raw-1", PAYLOAD, ts=fresh.ts)
    assert isinstance(replay, Replay)


def test_purge_window_edge_and_collapse(
    opkeys: OpKeys, db: Database, fake_clock: FakeClock
) -> None:
    start = fake_clock.now()
    fresh = opkeys.begin("raw-1", PAYLOAD)
    assert isinstance(fresh, Fresh)
    _mark_committed(db, fresh.op_key, response="resp")
    fake_clock.set(start + WINDOW)  # not strictly older than the window yet
    report = opkeys.purge()
    assert report.collapsed == ()
    assert report.deleted == ()
    fake_clock.set(start + WINDOW + 1.0)
    report = opkeys.purge()
    assert report.collapsed == (fresh.op_key,)
    assert db.conn.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 0
    tomb = db.conn.execute("SELECT * FROM tombstones WHERE op_key = ?", (fresh.op_key,)).fetchone()
    assert tomb is not None
    assert tomb["payload_hash"] == PAYLOAD
    assert tomb["terminal_state"] == "COMMITTED"
    assert tomb["commit_hash"] == COMMIT_HASH
    assert tomb["expires_at"] == pytest.approx(start + WINDOW + MARGIN)


def test_tombstone_replay_and_mismatch(opkeys: OpKeys, db: Database, fake_clock: FakeClock) -> None:
    fresh = opkeys.begin("raw-1", PAYLOAD)
    assert isinstance(fresh, Fresh)
    _mark_committed(db, fresh.op_key)
    fake_clock.advance(WINDOW + 1.0)
    opkeys.purge()
    replay = opkeys.begin("raw-1", PAYLOAD)
    assert isinstance(replay, Replay)
    assert replay.from_tombstone
    assert replay.op_key == fresh.op_key
    assert replay.terminal_state == "COMMITTED"
    assert replay.commit_hash == COMMIT_HASH
    assert replay.response is None  # tombstones retain terminal state + commit hash only
    with pytest.raises(KeyPayloadMismatchError):
        opkeys.begin("raw-1", OTHER_PAYLOAD)


def test_tombstone_horizon_edges(opkeys: OpKeys, db: Database, fake_clock: FakeClock) -> None:
    start = fake_clock.now()
    fresh = opkeys.begin("raw-1", PAYLOAD)
    assert isinstance(fresh, Fresh)
    _mark_committed(db, fresh.op_key)
    fake_clock.set(start + WINDOW + 1.0)
    opkeys.purge()
    fake_clock.set(start + WINDOW + MARGIN - 1.0)  # just inside the 30d+7d horizon
    replay = opkeys.begin("raw-1", PAYLOAD)
    assert isinstance(replay, Replay)
    fake_clock.set(start + WINDOW + MARGIN)  # exactly at the horizon: expired
    with pytest.raises(KeyExpiredError):
        opkeys.begin("raw-1", PAYLOAD)
    report = opkeys.purge()
    assert report.deleted == (fresh.op_key,)
    assert db.conn.execute("SELECT COUNT(*) FROM tombstones").fetchone()[0] == 0
    # Post-horizon presentation of the original key -> key_expired.
    with pytest.raises(KeyExpiredError) as excinfo:
        opkeys.begin("raw-1", PAYLOAD, ts=fresh.ts)
    assert excinfo.value.code == "key_expired"


def test_row_past_horizon_expires_even_before_purge(
    opkeys: OpKeys, db: Database, fake_clock: FakeClock
) -> None:
    fresh = opkeys.begin("raw-1", PAYLOAD)
    assert isinstance(fresh, Fresh)
    _mark_committed(db, fresh.op_key)
    fake_clock.advance(WINDOW + MARGIN)
    with pytest.raises(KeyExpiredError):
        opkeys.begin("raw-1", PAYLOAD)


def test_purge_leaves_prepared_rows(opkeys: OpKeys, db: Database, fake_clock: FakeClock) -> None:
    fresh = opkeys.begin("raw-1", PAYLOAD)
    assert isinstance(fresh, Fresh)
    fake_clock.advance(WINDOW + MARGIN + 1.0)
    report = opkeys.purge()
    assert report.collapsed == ()
    row = db.conn.execute(
        "SELECT state FROM operations WHERE op_key = ?", (fresh.op_key,)
    ).fetchone()
    assert row is not None and row["state"] == "PREPARED"


def test_replay_survives_key_rotation(
    opkeys: OpKeys, db: Database, keyring: Keyring, fake_clock: FakeClock
) -> None:
    fresh = opkeys.begin("raw-1", PAYLOAD)
    assert isinstance(fresh, Fresh)
    _mark_committed(db, fresh.op_key, response="pre-rotation")
    keyring.rotate()
    replay = opkeys.begin("raw-1", PAYLOAD)
    assert isinstance(replay, Replay)
    assert replay.response == "pre-rotation"
    # Tombstone lookup verifies the HMAC with the retired key as well.
    fake_clock.advance(WINDOW + 1.0)
    opkeys.purge()
    tomb_replay = opkeys.begin("raw-1", PAYLOAD)
    assert isinstance(tomb_replay, Replay)
    assert tomb_replay.from_tombstone


def test_forged_tombstone_key_is_not_recognized(
    opkeys: OpKeys, db: Database, keyring: Keyring, fake_clock: FakeClock
) -> None:
    now = fake_clock.now()
    forged = f"v1.{format_ts(now)}.{keyring.active_key_id}.{'0' * 64}"
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO tombstones(op_key, payload_hash, terminal_state, commit_hash, "
            "created_at, expires_at) VALUES(?, ?, 'COMMITTED', NULL, ?, ?)",
            (forged, PAYLOAD, now, now + WINDOW),
        )
    outcome = opkeys.begin("raw-1", PAYLOAD)
    assert isinstance(outcome, Fresh)  # forged MAC never matches; key treated as first-seen


@settings(max_examples=25, deadline=None)
@given(
    ops=st.lists(
        st.tuples(
            st.text(
                alphabet=st.characters(min_codepoint=33, max_codepoint=126),
                min_size=1,
                max_size=24,
            ),
            st.sampled_from([PAYLOAD, OTHER_PAYLOAD]),
        ),
        min_size=1,
        max_size=8,
        unique_by=lambda t: t[0],
    )
)
def test_property_uniqueness_replay_mismatch(
    tmp_path_factory: pytest.TempPathFactory, ops: list[tuple[str, str]]
) -> None:
    root = tmp_path_factory.mktemp("opkeysprop")
    keyring = Keyring.create(root)
    with Database.connect(root / "state.db") as db:
        opkeys = OpKeys(db, keyring)
        seen: dict[str, str] = {}
        for raw_id, payload_hash in ops:
            fresh = opkeys.begin(raw_id, payload_hash)
            assert isinstance(fresh, Fresh)
            assert fresh.op_key not in seen.values()
            seen[raw_id] = fresh.op_key
            _mark_committed(db, fresh.op_key, response=f"resp:{raw_id}")
        assert len(set(seen.values())) == len(ops)
        for raw_id, payload_hash in ops:
            replay = opkeys.begin(raw_id, payload_hash)
            assert isinstance(replay, Replay)
            assert replay.op_key == seen[raw_id]
            assert replay.response == f"resp:{raw_id}"
            other = OTHER_PAYLOAD if payload_hash == PAYLOAD else PAYLOAD
            with pytest.raises(KeyPayloadMismatchError):
                opkeys.begin(raw_id, other)
