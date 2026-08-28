# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""``tp_session_edges`` — parent/child session threading, recorded durably.

``INTERFACE.md`` §2.8 ("NEW WORK (binds G4.10) — parent/child threading") and
§19 item 6.

**Why threading lives outside the event stream.** ``HephaestusEvent`` carries no
parent linkage, ``history.page`` is per-session, and a quick-edit child is a
separate ``session_id`` with its own Pi JSONL. :class:`~hephaestus.agent_bridge.
sessions.QuickEditContext` holds ``parent_session_id`` **in memory and persists
it nowhere**, so a reopened project had no way to reconstruct the tree §7.1
renders. The relationship is therefore recorded here — durably in ``state.db``,
on the ``tp_delegations`` precedent — at the two sites that already create it:

* ``SessionService.spawn_quick_edit`` (kind ``quick_edit``), and
* the delegation WAL's ``PREPARED`` transition (kind ``delegation``).

**The event vocabulary is untouched and Pi JSONL is never the source of truth
for the edge** (mission rule 6, ``architecture.md`` §4.1). Reopening
reconstructs threading from this table and pages each session's history
independently.

**Honest limit, surfaced rather than guessed.** An edge created before this
table existed cannot be recovered. A session with no row reads as
:data:`THREAD_UNLINKED` — "this transcript predates the edge table" — and the UI
says so (``data-thread-state="unlinked"``) rather than inferring a parent from
naming conventions or from adjacency in the event stream.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Final, cast

from opstore.db import Database

__all__ = [
    "EDGE_KINDS",
    "MAX_THREAD_DEPTH",
    "THREAD_LINKED",
    "THREAD_UNLINKED",
    "SessionEdge",
    "SessionEdgeStore",
    "ThreadNode",
]

_TABLE: Final[str] = "tp_session_edges"
_CREATE_TABLE: Final[str] = f"""
CREATE TABLE IF NOT EXISTS {_TABLE}(
  child_session_id TEXT PRIMARY KEY,
  parent_session_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  origin TEXT NOT NULL,
  created_at REAL NOT NULL)
"""
_CREATE_INDEX: Final[str] = (
    f"CREATE INDEX IF NOT EXISTS {_TABLE}_parent ON {_TABLE}(parent_session_id)"
)

#: The closed edge vocabulary (§2.8). Two relationships exist and no third is
#: minted here: a quick-edit child of a part session, and a delegated part agent
#: of an orchestrator. A caller naming anything else is refused by
#: :meth:`SessionEdgeStore.record`, not silently stored.
EDGE_KINDS: Final[frozenset[str]] = frozenset({"quick_edit", "delegation"})

#: ``GET /sessions/{id}/thread`` thread states — also a closed pair.
THREAD_LINKED: Final[str] = "linked"
THREAD_UNLINKED: Final[str] = "unlinked"

#: Descent bound. The real tree is three levels (§7.1: orchestrator → part →
#: quick edit); this exists so a corrupted or hand-edited table cannot spin the
#: walk forever. Cycles are additionally impossible-by-construction below.
MAX_THREAD_DEPTH: Final[int] = 32


@dataclass(frozen=True, slots=True)
class SessionEdge:
    """One durable parent→child session relationship."""

    child_session_id: str
    parent_session_id: str
    kind: str
    origin: dict[str, Any]
    created_at: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "child_session_id": self.child_session_id,
            "parent_session_id": self.parent_session_id,
            "kind": self.kind,
            "origin": dict(self.origin),
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class ThreadNode:
    """One node of the transitive tree ``GET /sessions/{id}/thread`` returns."""

    session_id: str
    parent_session_id: str | None
    kind: str | None
    origin: dict[str, Any]
    created_at: float | None
    depth: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "parent_session_id": self.parent_session_id,
            "kind": self.kind,
            "origin": dict(self.origin),
            "created_at": self.created_at,
            "depth": self.depth,
        }


class SessionEdgeStore:
    """Read/write access to ``tp_session_edges`` in one project's ``state.db``."""

    def __init__(self, db: Database) -> None:
        self._db = db
        with db.transaction() as conn:
            conn.execute(_CREATE_TABLE)
            conn.execute(_CREATE_INDEX)

    # -- writing -----------------------------------------------------------

    def record(
        self,
        *,
        child_session_id: str,
        parent_session_id: str,
        kind: str,
        origin: Mapping[str, Any],
        created_at: float | None = None,
    ) -> SessionEdge:
        """Record one edge; **the first edge for a child wins**.

        ``child_session_id`` is the primary key because a session is created
        once, by one parent, and that origin is the durable fact §2.8 wants. A
        second write for the same child — two orchestrators delegating the same
        part, a quick edit respawned after a crash — is therefore a *re-assertion
        of an existing session's origin*, not a new relationship, and it does not
        overwrite the first: the recorded parent stays the one the session was
        actually created by. The stored row is returned either way, so a caller
        can see which edge won.

        A ``kind`` outside :data:`EDGE_KINDS` raises. The vocabulary is closed
        because ``GET /sessions/{id}/thread`` is a client contract, and a client
        that must sniff for unknown kinds has no contract at all.
        """
        if kind not in EDGE_KINDS:
            raise ValueError(
                f"unknown session-edge kind {kind!r}; expected one of {sorted(EDGE_KINDS)}"
            )
        if child_session_id == parent_session_id:
            raise ValueError(f"a session cannot be its own parent: {child_session_id!r}")
        payload = json.dumps(dict(origin), sort_keys=True, ensure_ascii=False)
        stamp = time.time() if created_at is None else created_at
        with self._db.transaction() as conn:
            conn.execute(
                f"INSERT OR IGNORE INTO {_TABLE}"
                "(child_session_id, parent_session_id, kind, origin, created_at) "
                "VALUES(?, ?, ?, ?, ?)",
                (child_session_id, parent_session_id, kind, payload, stamp),
            )
        stored = self.get(child_session_id)
        assert stored is not None  # just inserted or already present
        return stored

    # -- reading -----------------------------------------------------------

    def get(self, child_session_id: str) -> SessionEdge | None:
        """The edge naming ``child_session_id``'s parent, if one was recorded."""
        row = self._db.conn.execute(
            f"SELECT * FROM {_TABLE} WHERE child_session_id = ?", (child_session_id,)
        ).fetchone()
        return None if row is None else _edge(row)

    def children(self, parent_session_id: str) -> list[SessionEdge]:
        """Direct children of ``parent_session_id``, oldest first."""
        rows = self._db.conn.execute(
            f"SELECT * FROM {_TABLE} WHERE parent_session_id = ? "
            "ORDER BY created_at, child_session_id",
            (parent_session_id,),
        ).fetchall()
        return [_edge(row) for row in rows]

    def thread(self, session_id: str) -> list[ThreadNode]:
        """The transitive tree rooted at ``session_id``, breadth-first.

        The root is always present (depth 0) even when nothing links it — a
        session with no edges is a one-node tree, which is the honest answer for
        a transcript that predates this table, not an error and not an empty
        list. Its own ``parent_session_id`` is carried so a client handed a child
        id can walk *up* as well as down.

        Descent is bounded by :data:`MAX_THREAD_DEPTH` and guarded by a visited
        set: the primary key makes a cycle unreachable through well-formed
        writes, and the guard makes a malformed table a bounded read rather than
        a hung request.
        """
        root_edge = self.get(session_id)
        nodes = [
            ThreadNode(
                session_id=session_id,
                parent_session_id=None if root_edge is None else root_edge.parent_session_id,
                kind=None if root_edge is None else root_edge.kind,
                origin={} if root_edge is None else dict(root_edge.origin),
                created_at=None if root_edge is None else root_edge.created_at,
                depth=0,
            )
        ]
        seen = {session_id}
        frontier = [session_id]
        depth = 1
        while frontier and depth <= MAX_THREAD_DEPTH:
            next_frontier: list[str] = []
            for parent in frontier:
                for edge in self.children(parent):
                    if edge.child_session_id in seen:
                        continue
                    seen.add(edge.child_session_id)
                    next_frontier.append(edge.child_session_id)
                    nodes.append(
                        ThreadNode(
                            session_id=edge.child_session_id,
                            parent_session_id=edge.parent_session_id,
                            kind=edge.kind,
                            origin=dict(edge.origin),
                            created_at=edge.created_at,
                            depth=depth,
                        )
                    )
            frontier = next_frontier
            depth += 1
        return nodes

    def __iter__(self) -> Iterator[SessionEdge]:
        rows = self._db.conn.execute(f"SELECT * FROM {_TABLE} ORDER BY created_at").fetchall()
        return iter([_edge(row) for row in rows])


def _edge(row: Any) -> SessionEdge:
    loaded: Any = json.loads(str(row["origin"]))
    origin = cast("dict[str, Any]", loaded) if isinstance(loaded, dict) else {}
    return SessionEdge(
        child_session_id=str(row["child_session_id"]),
        parent_session_id=str(row["parent_session_id"]),
        kind=str(row["kind"]),
        origin=origin,
        created_at=float(row["created_at"]),
    )
