"""Session service tests: single-writer leases, session_busy, stale recovery, quick-edit."""

from __future__ import annotations

import pytest
from conftest import FakeClock, FakeLiveness, owner
from hephaestus.agent_bridge.sessions import (
    QuickEditRequest,
    ResolvedSelection,
    SessionBusyError,
    SessionProfile,
    SessionService,
    StaleSelectionError,
    profile_for,
    session_ref,
)

from opstore import OpStore


def _svc(store: OpStore, clock: FakeClock) -> SessionService:
    return SessionService(store.leases, clock=clock)


def test_profiles_capabilities() -> None:
    assert profile_for(SessionProfile.ORCHESTRATOR).can_delegate is True
    assert profile_for(SessionProfile.PART).can_delegate is False
    assert profile_for(SessionProfile.QUERY_SNAPSHOT).tools_profile is None
    assert profile_for(SessionProfile.QUERY_SNAPSHOT).persistent is False


def test_acquire_and_release(store: OpStore, clock: FakeClock) -> None:
    svc = _svc(store, clock)
    lease = svc.acquire("sess-1", SessionProfile.PART, owner(100), ttl_s=60)
    assert lease.session_id == "sess-1"
    assert lease.profile is SessionProfile.PART
    assert svc.owner("sess-1") == owner(100)
    assert svc.release(lease) is True


def test_two_process_race_one_owner(
    store: OpStore, clock: FakeClock, liveness: FakeLiveness
) -> None:
    # Two separate connections to the SAME state.db model two processes.
    svc_a = _svc(store, clock)
    reopened = OpStore.open(store.root, store.config, clock=clock, liveness=liveness)
    try:
        svc_b = SessionService(reopened.leases, clock=clock)
        svc_a.acquire("sess", SessionProfile.PART, owner(1), ttl_s=100)
        with pytest.raises(SessionBusyError) as exc:
            svc_b.acquire("sess", SessionProfile.PART, owner(2), ttl_s=100)
        assert exc.value.code == "session_busy"
    finally:
        reopened.close()


def test_live_owner_past_ttl_still_busy(
    store: OpStore, clock: FakeClock, liveness: FakeLiveness
) -> None:
    svc = _svc(store, clock)
    svc.acquire("sess", SessionProfile.PART, owner(1), ttl_s=10)
    clock.advance(50)  # past TTL, but owner 1 remains alive
    with pytest.raises(SessionBusyError):
        svc.acquire("sess", SessionProfile.PART, owner(2), ttl_s=10)


def test_crash_owner_stale_recovery(
    store: OpStore, clock: FakeClock, liveness: FakeLiveness
) -> None:
    svc = _svc(store, clock)
    svc.acquire("sess", SessionProfile.PART, owner(1), ttl_s=10)
    clock.advance(50)  # past TTL
    liveness.kill(owner(1))  # confirmed dead
    # A new owner reclaims the stale, dead-owner lease.
    lease = svc.acquire("sess", SessionProfile.PART, owner(2), ttl_s=10)
    assert lease.session_id == "sess"
    assert svc.owner("sess") == owner(2)


def test_session_ref_namespacing() -> None:
    assert session_ref("abc") == "session:abc"


# -- quick-edit ----------------------------------------------------------------


class GoodResolver:
    def __init__(self, part: str = "partA") -> None:
        self._part = part

    def resolve(self, request: QuickEditRequest) -> ResolvedSelection:
        return ResolvedSelection(
            part=self._part,
            source="# artifact-bound source",
            provenance="tag:top_face",
            crop_artifact_ref="crop-ref-1",
        )


class StaleResolver:
    def resolve(self, request: QuickEditRequest) -> ResolvedSelection:
        raise StaleSelectionError("RGB ref is not a bundle/pass/GLTF-linked selection")


def _req(part: str = "partA") -> QuickEditRequest:
    return QuickEditRequest(
        part=part,
        build_artifact_ref="build-1",
        selection_artifact_ref="bundle-1",
        selection_id="sel-1",
    )


def test_quick_edit_spawns_scoped_child(store: OpStore, clock: FakeClock) -> None:
    svc = _svc(store, clock)
    lease, ctx = svc.spawn_quick_edit(
        _req(),
        GoodResolver(),
        parent_session_id="part:partA",
        child_session_id="qe:partA:1",
        owner=owner(9),
        ttl_s=60,
    )
    assert lease.profile is SessionProfile.QUICK_EDIT
    assert ctx.part == "partA"
    assert ctx.source == "# artifact-bound source"
    assert ctx.provenance == "tag:top_face"
    assert ctx.crop_artifact_ref == "crop-ref-1"
    assert ctx.parent_session_id == "part:partA"  # threaded to parent


def test_quick_edit_stale_selection_before_lease(store: OpStore, clock: FakeClock) -> None:
    svc = _svc(store, clock)
    with pytest.raises(StaleSelectionError):
        svc.spawn_quick_edit(
            _req(),
            StaleResolver(),
            parent_session_id="part:partA",
            child_session_id="qe:partA:1",
            owner=owner(9),
            ttl_s=60,
        )
    # No lease was taken (resolution failed first).
    assert svc.owner("qe:partA:1") is None


def test_quick_edit_part_mismatch_rejected(store: OpStore, clock: FakeClock) -> None:
    svc = _svc(store, clock)
    with pytest.raises(StaleSelectionError):
        svc.spawn_quick_edit(
            _req(part="partA"),
            GoodResolver(part="partB"),  # resolves outside the requested part
            parent_session_id="part:partA",
            child_session_id="qe:partA:1",
            owner=owner(9),
            ttl_s=60,
        )
