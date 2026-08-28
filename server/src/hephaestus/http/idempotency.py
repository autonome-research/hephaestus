# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""REST mutation idempotency: the header rule, the ladder, and the replay shape.

``INTERFACE.md`` §2.5 and §2.3. G5.19 requires REST mutation idempotency tested
**independently of MCP-over-HTTP**. Both paths share one HMAC-bound
normalized-key store (the project keyring, ``architecture.md`` §3.5, 30-day
horizon). They differ only in key derivation: REST follows the **header rule**,
on the route set §2.3 enumerates and no other; MCP keeps its own derivation
(session identity + canonical request id) and explicitly does not follow the
header rule. Two derivations, one store, two independent test lanes.

**The key is payload-independent, exactly as MCP's is.** The raw id is
``(WorkspacePrincipal token/route identity, Idempotency-Key header value)``,
carried as ``Invocation.entry_id`` so that ``Invocation.op_id`` stays *derived*
rather than assigned — ``op_id`` is a ``@property`` over
``session_id|entry_id|ordinal|provider_call_id`` (``dispatch.py``:246-273) and
cannot be handed anything. The canonical JSON body goes only into the separate
:func:`hephaestus.mcp.idempotency.payload_hash` digest and **never into the
key**. That separation is what makes ``key_payload_mismatch`` reachable at all:
folding the body into the key would give two different payloads two different
keys, both executing as first sights, and the row would be structurally dead.

**The ladder** (§2.5), in the order this module applies it:

===================================================  =========================
Situation                                            Response
===================================================  =========================
absent on a key-required route                       400 ``idempotency_key_required``, no execution
absent on a session-control route                    proceed; a supplied one is ignored
present but not a UUIDv7                             400 ``idempotency_key_malformed``, no execution
first sight, timestamp outside ±300 s                409 ``key_timestamp_skew``, no execution
recognized inside the 30-day horizon                 replay; **freshness is not re-checked**
same key, different payload                          409 ``key_payload_mismatch``
presented after the 30-day horizon                   409 ``key_expired``, no execution
===================================================  =========================

The freshness asymmetry is a documented trap and is restated here so a test
author trips over it in the source too: **replay tests must not re-assert
freshness.**

**The replay shape** is REST's own (§2.5 TIGHTENING): a recognized key on a
committed mutation replays the stored response body **byte-for-byte**, with
envelope field ``"replayed": true`` (normative) and header
``Idempotency-Replayed: true`` (advisory). It does *not* degrade to the bridge's
``{applied: false, conflict:{current_hash}}`` shape — that shape exists because
the retrying principal is a *model* being told a live hash it does not hold,
while a REST replay is the same operator client re-sending its own committed
call. The two families that return a discriminated result rather than a bare
success (``edit_part``/``write_part`` → ``conflict``; project-check →
``already_exists`` / ``conflict(kind="stale_hash")``) are unaffected: their
discriminated result *is* the stored response and replays as such.

**The ledger extension (§19 item 7).** ``POST /project/config/dfm`` and
``POST /git/tag`` are config and output mutations with **no tool behind them** —
no ``ToolDecl``, no ``Invocation``, no recorded-outcome row to replay — so the
recorded-outcome ledger is extended to cover non-tool REST operations under the
*same key space*: ``(project keyring HMAC, route, Idempotency-Key)``. The
operation identity is the route and the stored value is the response body.
Without this, those two rows would be a header requirement with nothing behind
them, which is precisely the defect §2.3's table exists to remove.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Final

from hephaestus.agent_bridge.dispatch import Invocation
from hephaestus.mcp.idempotency import FRESHNESS_SKEW_S, payload_hash
from opstore.errors import OpStoreError

from opstore import OpStore

__all__ = [
    "FRESHNESS_SKEW_S",
    "KEY_REQUIRED_ROUTES",
    "NON_TOOL_KEY_ROUTES",
    "REPLAYED_FIELD",
    "REPLAYED_HEADER",
    "SESSION_CONTROL_ROUTES",
    "Replayed",
    "RestKeyError",
    "RestLedger",
    "require_key",
    "requires_key",
    "rest_invocation",
    "rest_payload_hash",
    "route_identity",
    "validate_key",
]

#: §2.5 TIGHTENING — the normative envelope field on a replayed body.
REPLAYED_FIELD: Final[str] = "replayed"

#: …and the advisory response header beside it.
REPLAYED_HEADER: Final[str] = "Idempotency-Replayed"

#: ``INTERFACE.md`` §2.3, first table — ``Idempotency-Key`` **required**,
#: replayed byte-for-byte. Enumerated, never derived from ``MUTATION_TOOLS``:
#: that rule was withdrawn because it decides nothing for a route with no
#: ``ToolDecl``, and a rule that silently exempts the routes a reader most
#: expects it to cover is worse than no rule.
#:
#: Each entry is ``(method, template)`` — the *route identity*, which is what
#: the key space is scoped by, not the concrete path.
KEY_REQUIRED_ROUTES: Final[tuple[tuple[str, str], ...]] = (
    ("PUT", "/parts/{part}/script"),
    ("PATCH", "/parts/{part}/script"),
    ("POST", "/parts/{part}/params"),
    ("POST", "/parts/{part}/build"),
    ("POST", "/parts/{part}/dfm"),
    ("POST", "/project/config/dfm"),
    ("POST", "/git/tag"),
)

#: The two key-required routes with **no tool behind them** (§19 item 7): a
#: project-config write and a git tag. Their recorded outcome is the response
#: body itself, keyed by route identity.
NON_TOOL_KEY_ROUTES: Final[tuple[tuple[str, str], ...]] = (
    ("POST", "/project/config/dfm"),
    ("POST", "/git/tag"),
)

#: ``INTERFACE.md`` §2.3, second table — session control. A key is **not
#: required** and a supplied one is **ignored rather than honoured**: §2.5's
#: byte-for-byte replay is incoherent for a route whose whole meaning is a side
#: effect on a live run, and ``tool_schema.md``'s key clause (source/config/
#: output mutations) does not reach session control at all.
SESSION_CONTROL_ROUTES: Final[tuple[tuple[str, str], ...]] = (
    ("POST", "/sessions"),
    ("POST", "/sessions/{id}/prompt"),
    ("POST", "/sessions/{id}/answer"),
    ("POST", "/runs/{run_id}/cancel"),
    ("POST", "/parts/{part}/quick_edit"),
)


class RestKeyError(Exception):
    """A key-ladder refusal; ``reason`` is the §2.4 machine token."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


def route_identity(method: str, template: str) -> str:
    """``"POST /parts/{part}/build"`` — what the key space is scoped by.

    The *template*, never the concrete path: two builds of two parts under one
    header value are the same operation identity by design, and the payload hash
    is what separates them into a ``key_payload_mismatch``. Scoping by the
    concrete path instead would let one key commit a write to every part in the
    project, one part at a time, and never trip the mismatch row.
    """
    return f"{method.upper()} {template}"


def requires_key(method: str, template: str) -> bool:
    """True for exactly the seven routes of §2.3's first table."""
    return (method.upper(), template) in KEY_REQUIRED_ROUTES


def validate_key(header: str | None, *, method: str, template: str) -> str | None:
    """Apply the first two ladder rungs; return the key to use, or ``None``.

    ``None`` means "no key governs this call" — the session-control case, where
    a supplied header is deliberately dropped on the floor rather than honoured.
    Raises :class:`RestKeyError` for the two **no execution** rungs, which is why
    this runs before anything touches the store.
    """
    required = requires_key(method, template)
    if header is None or not header.strip():
        if required:
            raise RestKeyError(
                "idempotency_key_required",
                f"{route_identity(method, template)} requires an Idempotency-Key header",
            )
        return None
    if not required:
        # §2.3: "sending one is ignored rather than honoured".
        return None
    key = header.strip()
    if _uuid7_timestamp(key) is None:
        raise RestKeyError(
            "idempotency_key_malformed",
            f"Idempotency-Key {key!r} is not a UUIDv7",
        )
    return key


def require_key(header: str | None, *, method: str, template: str) -> str:
    """:func:`validate_key` for a route that must have one; never returns ``None``.

    The narrowing is a guard rather than an assertion because assertions are
    stripped under ``-O``, and "this route requires a key" is a contract, not an
    invariant the author is merely confident about.
    """
    key = validate_key(header, method=method, template=template)
    if key is None:  # pragma: no cover - only reachable via a mis-declared route
        raise RestKeyError(
            "idempotency_key_required",
            f"{route_identity(method, template)} requires an Idempotency-Key header",
        )
    return key


def rest_invocation(session_id: str, key: str, *, method: str, template: str) -> Invocation:
    """The trusted invocation for one keyed REST mutation.

    ``entry_id`` carries the route identity and the header value and **nothing
    from the body**; ``Invocation.op_id`` derives the raw id from it, so the
    opstore opkeys/WAL layer the Pi bridge and MCP already use keys this
    mutation too. Nothing about core idempotency is reimplemented for REST.
    """
    return Invocation(
        session_id=session_id,
        entry_id=f"rest:{route_identity(method, template)}:{key}",
        ordinal=0,
        provider_call_id="rest",
    )


def rest_payload_hash(*, project: str, method: str, template: str, body: dict[str, Any]) -> str:
    """The separate payload digest — canonical JSON, never folded into the key.

    Reuses :func:`hephaestus.mcp.idempotency.payload_hash` verbatim (one hashing
    contract for both transports, mission rule 6): the route identity takes the
    ``tool`` slot because for a non-tool row the route *is* the operation. It is
    byte-faithful — no Unicode normalization, so NFC and NFD are different
    payloads.
    """
    return payload_hash(
        project=project,
        tool=route_identity(method, template),
        arguments=body,
        target=None,
    )


def _uuid7_timestamp(key: str) -> float | None:
    """Unix seconds embedded in a UUIDv7 key, or ``None`` for any other shape."""
    try:
        parsed = uuid.UUID(key)
    except ValueError:
        return None
    if parsed.version != 7:
        return None
    return (parsed.int >> 80) / 1000.0


@dataclass(frozen=True)
class Replayed:
    """A recognized key's recorded outcome: the body that must be re-returned."""

    op_id: str
    response: Any


#: The raw-id namespace this ledger claims in ``opstore.opkeys``. Distinct from
#: the ``Invocation.op_id`` a tool-backed route hands to dispatch, so the REST
#: ladder claim and the core WAL claim are two rows and neither shadows the
#: other.
_RAW_ID_PREFIX: Final[str] = "rest-key|"

_TABLE: Final[str] = "rest_idempotency"
_CREATE_TABLE: Final[str] = f"""
CREATE TABLE IF NOT EXISTS {_TABLE}(
  op_id TEXT PRIMARY KEY,
  payload_hash TEXT NOT NULL,
  response TEXT NOT NULL,
  created_at REAL NOT NULL)
"""


class RestLedger:
    """The recorded-outcome ledger for keyed REST mutations (§2.5, §19 item 7).

    Two halves, and the split is the point:

    * **The ladder** is :meth:`opstore.opkeys.OpKeys.begin` — the very
      HMAC-bound, timestamp-prefixed, project-keyring-scoped store §2.5 names,
      with the real 30-day idempotency window and 7-day tombstone margin. It
      raises ``key_timestamp_skew`` on a first-sight skew, ``key_payload_
      mismatch`` on a same-key-different-payload presentation, and
      ``key_expired`` past the horizon — the engine's own strings, verbatim.
      Nothing about freshness, mismatch, or expiry is reimplemented here, which
      is what makes the REST lane "identical in kind" to MCP's rather than
      merely similar in prose.
    * **The recorded response** is this module's own table beside it, exactly as
      :mod:`hephaestus.mcp.idempotency` keeps one beside the core WAL. ``opkeys``
      stores a response column that only ``wal.py`` fills at publish time, and a
      REST config write or a git tag has no WAL to fill it — which is precisely
      the gap §19 item 7 names. So the body is recorded here, and the key space
      it is recorded under is the route identity's, not a tool's.

    A row claimed but never committed (a crash, or a refusal raised mid-flight)
    does not block a retry: for a tool-backed route the durable mutation
    authority is the core WAL keyed by the invocation id, and for a non-tool
    route there was no durable effect to protect. The ladder claim is made under
    a **namespaced** raw id (:data:`_RAW_ID_PREFIX`) distinct from the
    ``Invocation.op_id`` a tool-backed route hands to dispatch, so the REST claim
    and the core WAL claim are two rows and neither shadows the other — a single
    shared row would resolve a retry to ``PendingRecovery`` and confuse the WAL's
    own recovery path.

    KNOWN GROWTH, recorded because a reader will eventually ask: the ladder rows
    stay ``PREPARED`` forever (only ``wal.py`` commits an ``operations`` row, and
    a REST mutation's WAL claim is the *other* row), and
    :meth:`opstore.opkeys.OpKeys.purge` collapses only ``COMMITTED``/
    ``CONFLICTED`` rows. So one small row per keyed REST mutation persists, as
    does one response row here. That is the same shape
    :mod:`hephaestus.mcp.idempotency` already has for MCP — not a new class of
    problem — and it is load-bearing rather than accidental: the post-horizon
    ``key_expired`` refusal is computed from that row's timestamp, so deleting it
    would turn an expired key back into a first sight and re-execute it.
    """

    def __init__(self, store: OpStore) -> None:
        self._store = store
        self._store.db.conn.execute(_CREATE_TABLE)

    def begin(self, op_id: str, digest: str, *, key: str) -> Replayed | None:
        """Run the ladder; return the recorded outcome when this is a replay.

        Freshness is checked **on first sight only** — a recognized key replays
        for the full horizon without re-checking it (§2.5's documented trap).
        """
        try:
            self._store.opkeys.begin(_RAW_ID_PREFIX + op_id, digest, ts=_uuid7_timestamp(key))
        except OpStoreError as exc:
            raise RestKeyError(exc.code, exc.message) from exc
        row = self._store.db.conn.execute(
            f"SELECT response FROM {_TABLE} WHERE op_id = ?", (op_id,)
        ).fetchone()
        if row is None:
            return None
        return Replayed(op_id=op_id, response=json.loads(str(row["response"])))

    def commit(self, op_id: str, digest: str, response: Any) -> None:
        """Record the exact body returned for ``op_id`` (idempotently)."""
        with self._store.db.transaction() as conn:
            conn.execute(
                f"INSERT OR REPLACE INTO {_TABLE}(op_id, payload_hash, response, created_at) "
                "VALUES(?, ?, ?, ?)",
                (
                    op_id,
                    digest,
                    json.dumps(response, sort_keys=True, ensure_ascii=False),
                    time.time(),
                ),
            )
