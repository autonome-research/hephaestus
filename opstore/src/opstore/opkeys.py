"""Operation keys: HMAC-bound idempotency verification and tombstone horizons.

Contract (DESIGN.md "opkeys.py" + architecture.md §3.5):

- Normalized key ``v1.<ts>.<key_id>.<mac>`` where ``mac`` is HMAC-SHA256 over
  ``<raw_id>|<ts>`` under the named keyring key and ``<ts>`` is the trusted
  embedded timestamp (``repr`` of unix seconds, round-trip exact).
- ``begin(raw_id, payload_hash, ts=None)`` outcomes:
  - unknown key inside the freshness window registers a skeleton ``PREPARED``
    row and returns ``Fresh`` (wal.py fills the row at prepare/publish time);
  - a recognized ``COMMITTED``/``CONFLICTED`` row or a live tombstone with the
    same payload returns ``Replay``; a recognized ``PREPARED`` row returns
    ``PendingRecovery`` (resolve via ``wal.recover(op_key)`` first);
  - key reuse with a different canonical payload hash raises
    ``KeyPayloadMismatchError``; first-seen keys with an embedded timestamp
    outside ±``freshness_skew_s`` (5 min) of the server clock raise
    ``KeyTimestampSkewError``; keys older than the idempotency window (first
    seen) or at/past the tombstone horizon (recognized) raise
    ``KeyExpiredError`` without execution. Recognized keys replay through the
    full window without the freshness check.
- Outcome GC: ``purge()`` collapses ``COMMITTED``/``CONFLICTED`` rows older
  than the window into tombstones ``(op_key, payload_hash, terminal_state,
  commit_hash)`` expiring at ``ts + window + tombstone_margin_s`` (7 days), and
  deletes expired tombstones; post-horizon presentation → ``KeyExpiredError``.
"""

from __future__ import annotations

import hmac
import sqlite3
from dataclasses import dataclass

from opstore.db import Database
from opstore.errors import (
    KeyExpiredError,
    KeyPayloadMismatchError,
    KeyTimestampSkewError,
    NotFoundError,
)
from opstore.keyring import Keyring
from opstore.types import Clock, OperationState, StoreConfig, SystemClock

KEY_VERSION = "v1"


@dataclass(frozen=True, slots=True)
class ParsedKey:
    """Fields embedded in a normalized operation key."""

    ts: float
    key_id: str
    mac_hex: str


@dataclass(frozen=True, slots=True)
class Fresh:
    """New operation key: skeleton row registered; proceed to wal prepare/publish."""

    op_key: str
    raw_id: str
    key_id: str
    ts: float
    payload_hash: str


@dataclass(frozen=True, slots=True)
class Replay:
    """Recognized key with a terminal outcome; the operation must not re-execute.

    ``response`` is the recorded response for full rows and ``None`` for
    tombstone replays, which carry only ``terminal_state`` and ``commit_hash``.
    """

    op_key: str
    payload_hash: str
    terminal_state: str
    response: str | None
    commit_hash: str | None
    from_tombstone: bool


@dataclass(frozen=True, slots=True)
class PendingRecovery:
    """Recognized key still ``PREPARED``; run ``wal.recover(op_key)`` then retry."""

    op_key: str


BeginOutcome = Fresh | Replay | PendingRecovery


@dataclass(frozen=True, slots=True)
class PurgeReport:
    """Outcome-GC report: rows collapsed to tombstones and tombstones deleted."""

    collapsed: tuple[str, ...]
    deleted: tuple[str, ...]


def format_ts(ts: float) -> str:
    """Canonical embedded-timestamp text (``repr`` round-trips float64 exactly)."""
    return repr(float(ts))


def parse_key(op_key: str) -> ParsedKey:
    """Split a normalized key into its embedded fields (``ValueError`` if malformed)."""
    parts = op_key.split(".")
    if len(parts) < 4 or parts[0] != KEY_VERSION:
        raise ValueError(f"malformed operation key: {op_key!r}")
    ts_str = ".".join(parts[1:-2])
    try:
        ts = float(ts_str)
    except ValueError as exc:
        raise ValueError(f"malformed operation key timestamp: {op_key!r}") from exc
    return ParsedKey(ts=ts, key_id=parts[-2], mac_hex=parts[-1])


def _mac_data(raw_id: str, ts_str: str) -> bytes:
    return f"{raw_id}|{ts_str}".encode()


class OpKeys:
    """Idempotency layer over the ``operations`` and ``tombstones`` tables."""

    def __init__(
        self,
        db: Database,
        keyring: Keyring,
        clock: Clock | None = None,
        config: StoreConfig | None = None,
    ) -> None:
        self._db = db
        self._keyring = keyring
        self._clock = clock or SystemClock()
        self._config = config or StoreConfig()

    def normalize(self, raw_id: str, ts: float, key_id: str | None = None) -> str:
        """Normalized HMAC-bound key for ``raw_id`` at embedded timestamp ``ts``."""
        resolved_key_id = key_id or self._keyring.active_key_id
        ts_str = format_ts(ts)
        mac_hex = self._keyring.mac(resolved_key_id, _mac_data(raw_id, ts_str))
        return f"{KEY_VERSION}.{ts_str}.{resolved_key_id}.{mac_hex}"

    def verify_key(self, op_key: str, raw_id: str) -> bool:
        """True iff ``op_key`` is a well-formed key HMAC-bound to ``raw_id``."""
        try:
            parsed = parse_key(op_key)
        except ValueError:
            return False
        try:
            expected = self._keyring.mac(parsed.key_id, _mac_data(raw_id, format_ts(parsed.ts)))
        except NotFoundError:
            return False
        return hmac.compare_digest(expected, parsed.mac_hex)

    def begin(self, raw_id: str, payload_hash: str, ts: float | None = None) -> BeginOutcome:
        """Verify/register ``raw_id`` for execution (see module contract for outcomes).

        ``ts`` is the embedded timestamp a retrying caller extracted from the
        presented normalized key; ``None`` means first presentation now.
        """
        now = self._clock.now()
        window = self._config.idempotency_window_s
        horizon = window + self._config.tombstone_margin_s
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT op_key, ts, payload_hash, state, after_hash, response "
                "FROM operations WHERE raw_id = ? LIMIT 1",
                (raw_id,),
            ).fetchone()
            if row is not None:
                return self._resolve_row(row, payload_hash, now, horizon)
            tomb = self._find_tombstone(conn, raw_id)
            if tomb is not None:
                return self._resolve_tombstone(tomb, payload_hash, now)
            key_ts = now if ts is None else float(ts)
            if now - key_ts > window:
                raise KeyExpiredError(
                    f"operation key for {raw_id!r} is older than the idempotency window"
                )
            if abs(key_ts - now) > self._config.freshness_skew_s:
                raise KeyTimestampSkewError(
                    f"first-seen key for {raw_id!r} has timestamp outside the freshness window"
                )
            key_id = self._keyring.active_key_id
            op_key = self.normalize(raw_id, key_ts, key_id)
            conn.execute(
                "INSERT INTO operations(op_key, raw_id, key_id, ts, payload_hash, state, "
                "created_at) VALUES(?, ?, ?, ?, ?, 'PREPARED', ?)",
                (op_key, raw_id, key_id, key_ts, payload_hash, now),
            )
            return Fresh(
                op_key=op_key,
                raw_id=raw_id,
                key_id=key_id,
                ts=key_ts,
                payload_hash=payload_hash,
            )

    def purge(self, now: float | None = None) -> PurgeReport:
        """Outcome GC: collapse rows older than the window; drop expired tombstones."""
        current = self._clock.now() if now is None else now
        window = self._config.idempotency_window_s
        margin = self._config.tombstone_margin_s
        collapsed: list[str] = []
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT op_key, ts, payload_hash, state, after_hash FROM operations "
                "WHERE state IN ('COMMITTED', 'CONFLICTED') AND ts < ? ORDER BY ts, op_key",
                (current - window,),
            ).fetchall()
            for row in rows:
                op_key = str(row["op_key"])
                after = row["after_hash"]
                conn.execute(
                    "INSERT INTO tombstones(op_key, payload_hash, terminal_state, commit_hash, "
                    "created_at, expires_at) VALUES(?, ?, ?, ?, ?, ?)",
                    (
                        op_key,
                        str(row["payload_hash"]),
                        str(row["state"]),
                        None if after is None else str(after),
                        current,
                        float(row["ts"]) + window + margin,
                    ),
                )
                conn.execute("DELETE FROM operations WHERE op_key = ?", (op_key,))
                collapsed.append(op_key)
            expired = conn.execute(
                "SELECT op_key FROM tombstones WHERE expires_at <= ? ORDER BY expires_at, op_key",
                (current,),
            ).fetchall()
            deleted = tuple(str(row["op_key"]) for row in expired)
            conn.execute("DELETE FROM tombstones WHERE expires_at <= ?", (current,))
        return PurgeReport(collapsed=tuple(collapsed), deleted=deleted)

    def _resolve_row(
        self, row: sqlite3.Row, payload_hash: str, now: float, horizon: float
    ) -> BeginOutcome:
        op_key = str(row["op_key"])
        if str(row["payload_hash"]) != payload_hash:
            raise KeyPayloadMismatchError(
                f"operation key {op_key} reused with a different payload hash"
            )
        if now - float(row["ts"]) >= horizon:
            raise KeyExpiredError(f"operation key {op_key} is past the tombstone horizon")
        state = OperationState(str(row["state"]))
        if state is OperationState.PREPARED:
            return PendingRecovery(op_key=op_key)
        response = row["response"]
        after = row["after_hash"]
        return Replay(
            op_key=op_key,
            payload_hash=payload_hash,
            terminal_state=state.value,
            response=None if response is None else str(response),
            commit_hash=None if after is None else str(after),
            from_tombstone=False,
        )

    def _resolve_tombstone(self, tomb: sqlite3.Row, payload_hash: str, now: float) -> Replay:
        op_key = str(tomb["op_key"])
        if str(tomb["payload_hash"]) != payload_hash:
            raise KeyPayloadMismatchError(
                f"operation key {op_key} (tombstone) reused with a different payload hash"
            )
        if now >= float(tomb["expires_at"]):
            raise KeyExpiredError(f"operation key {op_key} is past the tombstone horizon")
        commit = tomb["commit_hash"]
        return Replay(
            op_key=op_key,
            payload_hash=payload_hash,
            terminal_state=str(tomb["terminal_state"]),
            response=None,
            commit_hash=None if commit is None else str(commit),
            from_tombstone=True,
        )

    def _find_tombstone(self, conn: sqlite3.Connection, raw_id: str) -> sqlite3.Row | None:
        rows = conn.execute(
            "SELECT op_key, payload_hash, terminal_state, commit_hash, expires_at FROM tombstones"
        ).fetchall()
        for tomb in rows:
            if self.verify_key(str(tomb["op_key"]), raw_id):
                return tomb
        return None
