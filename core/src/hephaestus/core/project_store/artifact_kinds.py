# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""``tp_artifact_kinds`` — the kind a blob was published under (§2.6 CORRECTION).

``INTERFACE.md`` §2.6's **CORRECTION (2026-08-28 review)** and §19.24.

**The defect this closes.** An artifact ref is ``artifact:<kind>:sha256:<hex>``
and the store has only ever verified the *hash* half of it. ``blob_hash_of_ref``
resolves bytes; the kind segment was read straight out of the caller-supplied
string and believed. Export outputs live in the same blob store as builds and
renders (``Publisher._commit_export`` and ``cad_ops/_exports.py`` both
``blobs.put`` → ``gc.pin`` → ``gc.link``), so a ref whose *label* says ``build``
and whose *hash* names an export served the export's bytes. Every refusal
written in terms of the kind segment — §15.17's export refusal, §2.6's byte-route
enumeration — therefore refused a naming convention rather than a reachability
boundary, and relabelling is free.

**What is recorded.** One row per (blob, kind) at publication: the kind is a fact
the *publisher* knows and the reader must not have to take from the reader's own
input. A reader resolves the recorded kinds for a blob and refuses a ref whose
label is not among them.

**WHY (blob, kind) is a set and not a column on the blob.** The store is
content-addressed and dedups by content hash, so two publications of *identical
bytes* under two kinds are one blob. A single-valued column would have to pick a
winner, and the loser — a legitimately published artifact — would become
unservable through its own ref. A set says what is true: these are the kinds this
blob has been published under. It also keeps the record append-only, which is
what makes recording idempotent under the WAL replay every publication path
already performs.

**Honest limit, surfaced rather than guessed** (the ``tp_session_edges``
precedent, ``agent_bridge/session_edges.py``). A blob published before this table
existed, or by a path not yet instrumented, has **no** rows. That is reported as
the empty set and a reader must treat it as *unverified* — not as "no kind
matches", which would make every pre-existing artifact unreadable, and not as
"any kind matches", which would be this module lying. The caller decides what an
unverified blob may do; :mod:`hephaestus.http.artifacts` states its own answer.

The table is a ``tp_``-prefixed table on the shared opstore ``state.db``
connection, created idempotently on first write — the same shape ``tp_jobstore``,
``tp_delegations``, ``tp_session_edges`` and ``tp_exports`` already use, because
the artifact *kind* vocabulary is Hephaestus's and not opstore's, and opstore's
migration list is not the place to teach a generic blob store about builds.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from typing import Final

from hephaestus.core.project_store.store import artifact_kind_of_ref, blob_hash_of_ref

from opstore import OpStore

__all__ = [
    "ARTIFACT_KINDS_TABLE",
    "record_artifact_kind",
    "record_artifact_refs",
    "recorded_kinds",
]

#: The durable record, on the ``tp_`` convention for Hephaestus-owned tables in
#: the opstore ``state.db``.
ARTIFACT_KINDS_TABLE: Final[str] = "tp_artifact_kinds"

_CREATE_TABLE: Final[str] = f"""
CREATE TABLE IF NOT EXISTS {ARTIFACT_KINDS_TABLE}(
  blob_hash TEXT NOT NULL,
  kind TEXT NOT NULL,
  recorded_at REAL NOT NULL,
  PRIMARY KEY(blob_hash, kind))
"""


def record_artifact_kind(store: OpStore, kind: str, blob_hash: str) -> None:
    """Record that ``blob_hash`` was published under ``kind`` (idempotent).

    Called from the publication paths themselves, next to the ``blobs.put`` that
    creates the blob, so the record and the bytes are written by the same code
    that knows which kind is being published. Idempotent because every one of
    those paths is replayable: a WAL recovery re-runs the completion steps and
    must converge, not accumulate.
    """
    with store.db.transaction() as conn:
        conn.execute(_CREATE_TABLE)
        conn.execute(
            f"INSERT INTO {ARTIFACT_KINDS_TABLE}(blob_hash, kind, recorded_at) "
            "VALUES(?, ?, ?) ON CONFLICT(blob_hash, kind) DO NOTHING",
            (blob_hash, kind, time.time()),
        )


def record_artifact_refs(store: OpStore, refs: Iterable[str]) -> None:
    """Record every ``artifact:<kind>:sha256:<hex>`` ref in one transaction.

    The ref-shaped entry point, for the publication paths that already hold refs
    rather than a (kind, blob) pair — ``Publisher._install_evidence`` iterates
    ``build.artifact_files`` keyed by ref, and re-splitting each one at the call
    site would be the grammar parsed in a third place (mission rule 6).
    """
    rows = [(blob_hash_of_ref(ref), artifact_kind_of_ref(ref)) for ref in refs]
    if not rows:
        return
    now = time.time()
    with store.db.transaction() as conn:
        conn.execute(_CREATE_TABLE)
        conn.executemany(
            f"INSERT INTO {ARTIFACT_KINDS_TABLE}(blob_hash, kind, recorded_at) "
            "VALUES(?, ?, ?) ON CONFLICT(blob_hash, kind) DO NOTHING",
            [(blob, kind, now) for blob, kind in rows],
        )


def recorded_kinds(store: OpStore, blob_hash: str) -> frozenset[str]:
    """Every kind ``blob_hash`` has been published under; empty if unrecorded.

    Read-only and transaction-free on purpose: this is on the request path of
    ``GET /artifacts/{ref}/…`` and ``Database.transaction`` is ``BEGIN
    IMMEDIATE``, so ensuring the table here would take a write lock on every
    artifact read. The table's absence is asked about rather than caught as an
    ``OperationalError``, because "no publication has ever recorded a kind" is a
    state this module has an answer for — the empty set — and not an error.
    """
    exists = store.db.conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (ARTIFACT_KINDS_TABLE,),
    ).fetchone()
    if exists is None:
        return frozenset()
    rows = store.db.conn.execute(
        f"SELECT kind FROM {ARTIFACT_KINDS_TABLE} WHERE blob_hash = ?", (blob_hash,)
    ).fetchall()
    return frozenset(str(row["kind"]) for row in rows)
