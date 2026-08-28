# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""``tp_session_edges`` — durable parent/child threading (``INTERFACE.md`` §2.8).

The table is asserted at the two sites that write it, not only through its own
API, because §2.8's claim is that threading is recorded **where the relationship
is created** — the quick-edit spawn and the delegation WAL's ``PREPARED``
transition — and never inferred from the event stream afterwards.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hephaestus.agent_bridge.delegation import DelegationService, Delivery
from hephaestus.agent_bridge.session_edges import EDGE_KINDS, MAX_THREAD_DEPTH, SessionEdgeStore
from hephaestus.agent_bridge.sessions import (
    QuickEditRequest,
    ResolvedSelection,
    SessionService,
)
from hephaestus.testing.workspace import workspace
from opstore.types import current_owner

from opstore import OpStore


class _Resolver:
    """A stand-in for the Stage-1 selection resolver (§19 item 8 is not built)."""

    def resolve(self, request: QuickEditRequest) -> ResolvedSelection:
        return ResolvedSelection(
            part=request.part,
            source=request.build_artifact_ref,
            provenance="tread_top",
            crop_artifact_ref="artifact:selection-crop:c1",
        )


def _store(tmp_path: Path) -> OpStore:
    from hephaestus.agent_bridge.admission import bridge_store_config

    return OpStore.create(tmp_path / "store", bridge_store_config())


def test_the_kind_vocabulary_is_closed(tmp_path: Path) -> None:
    """A client contract that must be sniffed for unknown kinds is no contract."""
    store = _store(tmp_path)
    edges = SessionEdgeStore(store.db)
    assert {"quick_edit", "delegation"} == EDGE_KINDS
    with pytest.raises(ValueError, match="unknown session-edge kind"):
        edges.record(child_session_id="c", parent_session_id="p", kind="invented", origin={})
    store.close()


def test_a_session_cannot_be_its_own_parent(tmp_path: Path) -> None:
    store = _store(tmp_path)
    edges = SessionEdgeStore(store.db)
    with pytest.raises(ValueError, match="own parent"):
        edges.record(child_session_id="s", parent_session_id="s", kind="delegation", origin={})
    store.close()


def test_the_first_edge_for_a_child_wins(tmp_path: Path) -> None:
    """The child id is the primary key because a session is created once.

    A second write is a re-assertion of an existing session's origin, not a new
    relationship, and it must not rewrite the parent the session was actually
    created by.
    """
    store = _store(tmp_path)
    edges = SessionEdgeStore(store.db)
    edges.record(
        child_session_id="part:widget",
        parent_session_id="orch-a",
        kind="delegation",
        origin={"delegation_ref": "dg-1"},
    )
    again = edges.record(
        child_session_id="part:widget",
        parent_session_id="orch-b",
        kind="delegation",
        origin={"delegation_ref": "dg-2"},
    )
    assert again.parent_session_id == "orch-a"
    assert again.origin["delegation_ref"] == "dg-1"
    store.close()


def test_the_walk_is_bounded_and_survives_a_malformed_cycle(tmp_path: Path) -> None:
    """The primary key makes a cycle unreachable through well-formed writes; a
    hand-edited table must still be a bounded read, not a hung request."""
    store = _store(tmp_path)
    edges = SessionEdgeStore(store.db)
    with store.db.transaction() as conn:
        for child, parent in (("a", "b"), ("b", "a")):
            conn.execute(
                "INSERT INTO tp_session_edges"
                "(child_session_id, parent_session_id, kind, origin, created_at) "
                "VALUES(?, ?, 'delegation', '{}', 0.0)",
                (child, parent),
            )
    nodes = edges.thread("a")
    assert [node.session_id for node in nodes] == ["a", "b"]
    assert max(node.depth for node in nodes) < MAX_THREAD_DEPTH
    store.close()


def test_spawn_quick_edit_records_the_edge_the_spec_enumerates(tmp_path: Path) -> None:
    """§2.8: ``quick_edit → {part, source_artifact_ref, selection_id, provenance,
    crop_artifact_ref}`` — the enumerated origin, written by the spawn itself."""
    store = _store(tmp_path)
    edges = SessionEdgeStore(store.db)
    service = SessionService(store.leases, edges=edges)
    request = QuickEditRequest(
        part="widget",
        build_artifact_ref="artifact:build:a1",
        selection_artifact_ref="artifact:selection:s1",
        selection_id="face-7",
    )
    _lease, context = service.spawn_quick_edit(
        request,
        _Resolver(),
        parent_session_id="part:widget",
        child_session_id="qe-1",
        owner=current_owner(),
        ttl_s=30.0,
    )
    edge = edges.get("qe-1")
    assert edge is not None
    assert edge.parent_session_id == context.parent_session_id == "part:widget"
    assert edge.kind == "quick_edit"
    assert edge.origin == {
        "part": "widget",
        "source_artifact_ref": "artifact:build:a1",
        "selection_id": "face-7",
        "provenance": "tread_top",
        "crop_artifact_ref": "artifact:selection-crop:c1",
    }
    store.close()


def test_a_service_with_no_edge_store_threads_nothing_rather_than_guessing(
    tmp_path: Path,
) -> None:
    """The store is optional, and its absence is *unlinked*, never inferred."""
    store = _store(tmp_path)
    service = SessionService(store.leases)
    _lease, context = service.spawn_quick_edit(
        QuickEditRequest("widget", "artifact:build:a1", "artifact:selection:s1", "face-7"),
        _Resolver(),
        parent_session_id="part:widget",
        child_session_id="qe-2",
        owner=current_owner(),
        ttl_s=30.0,
    )
    assert context.parent_session_id == "part:widget"
    assert SessionEdgeStore(store.db).get("qe-2") is None
    store.close()


def test_the_delegation_wal_records_its_edge_at_prepared(tmp_path: Path) -> None:
    """§2.8's second writer, with §2.8's enumerated delegation origin."""
    store = _store(tmp_path)
    edges = SessionEdgeStore(store.db)
    service = DelegationService(store.admission, store.db, edges=edges)
    store.admission.admit("parent-run")
    outcome = service.delegate(
        "parent-run",
        "widget",
        "add a chamfer",
        delivery=Delivery.FOLLOW_UP,
        invocation="orch-1|entry-1|0|call-1",
        parent_session_id="orch-1",
        child_session_id="part:widget",
    )
    edge = edges.get("part:widget")
    assert edge is not None
    assert edge.parent_session_id == "orch-1"
    assert edge.kind == "delegation"
    assert set(edge.origin) == {"delegation_ref", "parent_run_id", "child_run_id"}
    assert edge.origin["parent_run_id"] == "parent-run"
    assert edge.origin["delegation_ref"] == getattr(outcome, "delegation_ref", None)
    store.close()


def test_a_rejected_delegation_creates_no_edge(tmp_path: Path) -> None:
    """A rejection has no child ref, so it must have no child *session* either."""
    from hephaestus.agent_bridge.delegation import RejectionReason

    class _Gate:
        def classify(self, parent_run_id: str, part: str, delivery: Delivery) -> RejectionReason:
            return RejectionReason.PART_BUSY

    store = _store(tmp_path)
    edges = SessionEdgeStore(store.db)
    service = DelegationService(store.admission, store.db, gate=_Gate(), edges=edges)
    service.delegate(
        "parent-run",
        "widget",
        "go",
        delivery=Delivery.FOLLOW_UP,
        invocation="orch-1|entry-9|0|call-9",
        parent_session_id="orch-1",
        child_session_id="part:widget",
    )
    assert edges.get("part:widget") is None
    store.close()


def test_the_table_lives_in_the_projects_state_db(tmp_path: Path) -> None:
    """§2.8 puts the edge in ``state.db`` on the ``tp_delegations`` precedent —
    not in Pi JSONL, which is never the source of truth for the edge."""
    with workspace(tmp_path / "proj", agent=True) as web:
        web.runtime.edges.record(
            child_session_id="qe-9",
            parent_session_id="part:widget",
            kind="quick_edit",
            origin={"part": "widget"},
        )
        rows = web.runtime.store.db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='tp_session_edges'"
        ).fetchall()
        # Survives a reopen of the same project — the whole point of "durably".
        reopened = web.runtime.edges.get("qe-9")
    assert len(rows) == 1
    assert reopened is not None and reopened.parent_session_id == "part:widget"
