"""MCP mutation idempotency: derived keys + the recorded-outcome ledger.

Stock MCP clients send no custom metadata, so ``tool_schema.md`` (conventions)
makes the *protocol* carry the key: the server derives it from the MCP session
identity plus the **canonical JSON-RPC request id**, preserving the id's type as
well as its value (``int:7`` and ``str:"7"`` are different keys). Hephaestus
therefore advertises that mutating request ids must be unique within an MCP
session — same-id/same-payload is a replay, same-id/different-payload is an
error. A client that needs cross-request reconciliation MAY instead send
``_meta["hephaestus.dev/idempotency-key"]``; when that key is a UUIDv7 its
embedded timestamp must be within five minutes of server time *on first sight*,
after which the recognized key replays for the full horizon without re-checking.

The derived raw id is the ``op_id`` handed to
:class:`~hephaestus.agent_bridge.dispatch.Invocation`, so the *same* opstore
opkeys/WAL machinery the Pi bridge uses keys the mutation itself: nothing about
core idempotency is reimplemented here. This module adds only the MCP-visible
half — a durable record of the exact tool result that was returned for a key, so
a replay returns the recorded result rather than merely a semantically
equivalent one, and so a replay under a *different* payload is rejected before
any core work starts. It mirrors the export WAL in
:mod:`hephaestus.agent_bridge.cad_ops`: its own table in the project's
``state.db``, keyed by the same trusted invocation id.

A ``PREPARED`` row whose attempt never reached a terminal (crash, or a refusal
raised mid-flight) does not block a retry: the durable mutation authority is the
core WAL keyed by the identical id, which replays or recovers the write.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import Any, Final

from hephaestus.agent_bridge.dispatch import Invocation
from opstore.hashing import sha256_canonical_json
from opstore.types import JSONValue

from opstore import OpStore

__all__ = [
    "IDEMPOTENCY_META_KEY",
    "SURFACE_VERSION",
    "IdempotencyError",
    "IdempotencyLedger",
    "Recorded",
    "derive_raw_id",
    "explicit_key_timestamp",
    "mcp_invocation",
    "payload_hash",
]

#: Optional client-supplied key (MCP ``_meta``); honored when present.
IDEMPOTENCY_META_KEY: Final[str] = "hephaestus.dev/idempotency-key"

#: Version of the MCP tool surface; part of every idempotency payload hash.
SURFACE_VERSION: Final[int] = 1

#: First-sight freshness window for an explicit UUIDv7 key (tool_schema.md).
FRESHNESS_SKEW_S: Final[float] = 300.0

_TABLE: Final[str] = "mcp_idempotency"
_CREATE_TABLE: Final[str] = f"""
CREATE TABLE IF NOT EXISTS {_TABLE}(
  op_id TEXT PRIMARY KEY,
  payload_hash TEXT NOT NULL,
  state TEXT NOT NULL,
  response TEXT,
  created_at REAL NOT NULL)
"""


class IdempotencyError(Exception):
    """A key was reused with another payload, or presented outside its window."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


@dataclass(frozen=True)
class Recorded:
    """The outcome recorded for a recognized key; the operation must not re-run."""

    op_id: str
    response: Any


def canonical_request_id(request_id: int | str) -> str:
    """``"int:7"`` / ``"str:7"`` — the JSON-RPC id's *type and* value."""
    if isinstance(request_id, bool):  # pragma: no cover - not a JSON-RPC id type
        raise IdempotencyError(
            "invalid_request_id", "JSON-RPC request id must be a number or string"
        )
    if isinstance(request_id, int):
        return f"int:{request_id}"
    return f"str:{request_id}"


def mcp_invocation(
    session_id: str, request_id: int | str, *, explicit_key: str | None = None
) -> Invocation:
    """The trusted invocation metadata for one MCP tool call.

    ``Invocation.op_id`` is the raw idempotency id the core opkeys/WAL layer
    keys on, so the MCP and Pi boundaries share one key space and one machinery.
    """
    entry = f"meta:{explicit_key}" if explicit_key is not None else canonical_request_id(request_id)
    return Invocation(
        session_id=f"mcp:{session_id}", entry_id=entry, ordinal=0, provider_call_id="mcp"
    )


def derive_raw_id(
    session_id: str, request_id: int | str, *, explicit_key: str | None = None
) -> str:
    """The normalized-before-HMAC raw operation id for this MCP call."""
    return mcp_invocation(session_id, request_id, explicit_key=explicit_key).op_id


def explicit_key_timestamp(key: str) -> float | None:
    """Unix seconds embedded in a UUIDv7 key, or ``None`` for other key shapes."""
    try:
        parsed = uuid.UUID(key)
    except ValueError:
        return None
    if parsed.version != 7:
        return None
    return (parsed.int >> 80) / 1000.0


def payload_hash(
    *, project: str, tool: str, arguments: dict[str, Any], target: str | None = None
) -> str:
    """Canonical payload hash: surface version, project, tool, target, arguments.

    Arguments are the *normalized* document (schema defaults materialized) and
    are hashed as canonical JSON with sorted keys. Strings are never Unicode-
    normalized, so NFC/NFD-different bytes are different payloads.
    """
    document: JSONValue = {
        "surface_version": SURFACE_VERSION,
        "project": project,
        "tool": tool,
        "target": target,
        "arguments": arguments,
    }
    return sha256_canonical_json(document)


class IdempotencyLedger:
    """Durable ``op_id -> (payload hash, recorded MCP result)`` for mutations."""

    def __init__(self, store: OpStore) -> None:
        self._store = store
        self._store.db.conn.execute(_CREATE_TABLE)

    def begin(
        self,
        op_id: str,
        payload_digest: str,
        *,
        key_ts: float | None = None,
        now: float | None = None,
    ) -> Recorded | None:
        """Claim ``op_id``; return the recorded outcome when this is a replay.

        ``key_ts`` is the timestamp embedded in an explicit client key; on first
        sight it must be within :data:`FRESHNESS_SKEW_S` of server time.
        """
        current = time.time() if now is None else now
        with self._store.db.transaction() as conn:
            row = self._row(conn, op_id)
            if row is None:
                if key_ts is not None and abs(key_ts - current) > FRESHNESS_SKEW_S:
                    raise IdempotencyError(
                        "key_timestamp_skew",
                        f"idempotency key timestamp is outside the {FRESHNESS_SKEW_S:.0f}s "
                        "freshness window",
                    )
                conn.execute(
                    f"INSERT INTO {_TABLE}(op_id, payload_hash, state, response, created_at) "
                    "VALUES(?, ?, 'PREPARED', NULL, ?)",
                    (op_id, payload_digest, current),
                )
                return None
            if str(row["payload_hash"]) != payload_digest:
                raise IdempotencyError(
                    "idempotency_key_reuse",
                    f"MCP request id {op_id!r} was already used with a different payload; "
                    "mutating request ids must be unique within an MCP session",
                )
            if str(row["state"]) != "COMMITTED":
                # A prior attempt never reached a terminal; the core WAL keyed by
                # this same id replays or recovers the write, so let it proceed.
                return None
            recorded = row["response"]
            return Recorded(
                op_id=op_id, response=None if recorded is None else json.loads(str(recorded))
            )

    def commit(self, op_id: str, response: Any) -> None:
        """Record the exact result returned for ``op_id`` (idempotently)."""
        with self._store.db.transaction() as conn:
            conn.execute(
                f"UPDATE {_TABLE} SET state = 'COMMITTED', response = ? WHERE op_id = ?",
                (json.dumps(response, sort_keys=True, ensure_ascii=False), op_id),
            )

    def abort(self, op_id: str) -> None:
        """Drop an unfinished claim so a corrected retry may re-present the id."""
        with self._store.db.transaction() as conn:
            conn.execute(f"DELETE FROM {_TABLE} WHERE op_id = ? AND state <> 'COMMITTED'", (op_id,))

    def _row(self, conn: sqlite3.Connection, op_id: str) -> sqlite3.Row | None:
        cursor = conn.execute(f"SELECT * FROM {_TABLE} WHERE op_id = ?", (op_id,))
        return cursor.fetchone()
