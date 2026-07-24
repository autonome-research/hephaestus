"""Projection tests: audit revisions, selective staleness, coherent manifests."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Mapping
from pathlib import Path

import pytest
from hephaestus.core.project_store.layout import open_store
from hephaestus.core.project_store.locks import (
    PROJECT_CONFIG_LOCK,
    LockManager,
    part_lock,
)
from hephaestus.core.project_store.projections import (
    PROJECT_SNAPSHOT_REF_PREFIX,
    SNAPSHOT_POINTER,
    Projections,
    ProjectionState,
    SnapshotRejectedError,
)
from hephaestus.core.project_store.store import blob_hash_of_ref
from opstore.types import JSONValue
from test_project_store_helpers import make_project

from opstore import OpStore

REF_A = "artifact:build:sha256:" + "a" * 64
REF_B = "artifact:build:sha256:" + "b" * 64


@pytest.fixture
def opstore(tmp_path: Path) -> Iterator[OpStore]:
    layout = make_project(tmp_path / "proj")
    store = open_store(layout)
    yield store
    store.close()


@pytest.fixture
def locks(opstore: OpStore) -> LockManager:
    return LockManager(opstore)


@pytest.fixture
def projections(opstore: OpStore, locks: LockManager) -> Projections:
    return Projections(opstore, locks=locks)


def record(
    projections: Projections,
    locks: LockManager,
    part: str,
    consumed: Mapping[str, JSONValue],
    ref: str,
) -> None:
    with locks.holding(PROJECT_CONFIG_LOCK, part_lock(part)):
        projections.record_current(part, consumed=consumed, artifact_ref=ref)


class TestState:
    def test_initial_state(self, projections: Projections) -> None:
        assert projections.state() == ProjectionState()
        assert projections.state().audit_revision == 0

    def test_state_roundtrips_through_blob(
        self, projections: Projections, locks: LockManager
    ) -> None:
        projections.apply_hc_state({"sheet_t": 6, "label": "birch"})
        record(projections, locks, "shelf", {"sheet_t": 6}, REF_A)
        state = projections.state()
        assert state == ProjectionState.from_json(state.to_json())

    def test_record_current_requires_locks(self, projections: Projections) -> None:
        with pytest.raises(AssertionError, match="locks"):
            projections.record_current("shelf", consumed={}, artifact_ref=REF_A)


class TestSelectiveStaleness:
    def test_only_consumers_of_changed_names_go_stale(
        self, projections: Projections, locks: LockManager
    ) -> None:
        projections.apply_hc_state({"sheet_t": 6, "clearance": 0.2})
        record(projections, locks, "shelf", {"sheet_t": 6}, REF_A)
        record(projections, locks, "gusset", {"clearance": 0.2}, REF_B)

        report = projections.apply_hc_state({"sheet_t": 8, "clearance": 0.2})
        assert report.stale == ("shelf",)
        assert dict(report.changed) == {"shelf": ("sheet_t",)}
        state = projections.state()
        assert set(state.stale) == {"shelf"}
        assert "sheet_t" in state.stale["shelf"]

    def test_unconsumed_change_stales_nobody(
        self, projections: Projections, locks: LockManager
    ) -> None:
        projections.apply_hc_state({"sheet_t": 6})
        record(projections, locks, "shelf", {"sheet_t": 6}, REF_A)
        report = projections.apply_hc_state({"sheet_t": 6, "brand_new": 42})
        assert report.stale == ()
        assert projections.state().stale == {}
        # ... but the audit revision still advanced.
        assert report.audit_revision == 2

    def test_removed_consumed_name_stales_consumer(
        self, projections: Projections, locks: LockManager
    ) -> None:
        projections.apply_hc_state({"sheet_t": 6})
        record(projections, locks, "shelf", {"sheet_t": 6}, REF_A)
        report = projections.apply_hc_state({})
        assert report.stale == ("shelf",)

    def test_int_float_distinction_is_a_change(
        self, projections: Projections, locks: LockManager
    ) -> None:
        projections.apply_hc_state({"sheet_t": 6})
        record(projections, locks, "shelf", {"sheet_t": 6}, REF_A)
        report = projections.apply_hc_state({"sheet_t": 6.0})
        assert report.stale == ("shelf",)  # 6 and 6.0 hash differently (§3 types)

    def test_republication_clears_stale(self, projections: Projections, locks: LockManager) -> None:
        projections.apply_hc_state({"sheet_t": 6})
        record(projections, locks, "shelf", {"sheet_t": 6}, REF_A)
        projections.apply_hc_state({"sheet_t": 8})
        assert projections.state().stale
        record(projections, locks, "shelf", {"sheet_t": 8}, REF_B)
        assert projections.state().stale == {}
        assert projections.state().projections["shelf"].artifact_ref == REF_B


class TestCoherentSnapshot:
    def test_accepts_and_publishes_manifest(
        self, opstore: OpStore, projections: Projections, locks: LockManager
    ) -> None:
        projections.apply_hc_state({"sheet_t": 6, "clearance": 0.2})
        record(projections, locks, "shelf", {"sheet_t": 6}, REF_A)
        record(projections, locks, "gusset", {"clearance": 0.2}, REF_B)
        snapshot = projections.assemble_snapshot(["shelf", "gusset"])
        assert re.fullmatch(r"artifact:project-snapshot:sha256:[0-9a-f]{64}", snapshot.ref)
        parts = snapshot.manifest["parts"]
        assert isinstance(parts, dict)
        assert set(parts) == {"shelf", "gusset"}
        # Published behind the pointer, decodable from the CAS.
        pointer = opstore.blobs.read_pointer(SNAPSHOT_POINTER)
        assert pointer is not None
        assert pointer == blob_hash_of_ref(snapshot.ref)
        stored = json.loads(opstore.blobs.get(pointer).decode())
        assert stored == snapshot.manifest
        assert snapshot.ref == PROJECT_SNAPSHOT_REF_PREFIX + pointer

    def test_older_audit_revision_is_acceptable_when_projection_valid(
        self, projections: Projections, locks: LockManager
    ) -> None:
        projections.apply_hc_state({"sheet_t": 6})
        record(projections, locks, "shelf", {"sheet_t": 6}, REF_A)  # revision 1
        projections.apply_hc_state({"sheet_t": 6, "unrelated": 1})  # revision 2
        projections.apply_hc_state({"sheet_t": 6, "unrelated": 2})  # revision 3
        snapshot = projections.assemble_snapshot(["shelf"])
        parts = snapshot.manifest["parts"]
        assert isinstance(parts, dict)
        shelf = parts["shelf"]
        assert isinstance(shelf, dict)
        assert shelf["audit_revision"] == 1  # older revision, still projection-valid
        assert snapshot.manifest["audit_revision"] == 3

    def test_rejects_stale_part(self, projections: Projections, locks: LockManager) -> None:
        projections.apply_hc_state({"sheet_t": 6})
        record(projections, locks, "shelf", {"sheet_t": 6}, REF_A)
        projections.apply_hc_state({"sheet_t": 8})
        with pytest.raises(SnapshotRejectedError) as exc_info:
            projections.assemble_snapshot(["shelf"])
        error = exc_info.value
        assert error.code == "incoherent_project_snapshot"
        assert [issue.kind for issue in error.issues] == ["stale"]
        assert error.issues[0].part == "shelf"

    def test_rejects_missing_part(self, projections: Projections) -> None:
        with pytest.raises(SnapshotRejectedError) as exc_info:
            projections.assemble_snapshot(["never_built"])
        assert [issue.kind for issue in exc_info.value.issues] == ["missing"]

    def test_rejects_mismatched_projection_with_names(
        self, projections: Projections, locks: LockManager
    ) -> None:
        projections.apply_hc_state({"sheet_t": 6})
        # A projection recorded against values that are not the live ones
        # (no stale marker involved) is still incoherent.
        record(projections, locks, "shelf", {"sheet_t": 99}, REF_A)
        with pytest.raises(SnapshotRejectedError) as exc_info:
            projections.assemble_snapshot(["shelf"])
        issue = exc_info.value.issues[0]
        assert issue.kind == "mismatch"
        assert issue.names == ("sheet_t",)

    def test_rejection_reports_every_part(
        self, projections: Projections, locks: LockManager
    ) -> None:
        projections.apply_hc_state({"sheet_t": 6})
        record(projections, locks, "shelf", {"sheet_t": 6}, REF_A)
        projections.apply_hc_state({"sheet_t": 8})
        with pytest.raises(SnapshotRejectedError) as exc_info:
            projections.assemble_snapshot(["shelf", "never_built"])
        kinds = {issue.part: issue.kind for issue in exc_info.value.issues}
        assert kinds == {"never_built": "missing", "shelf": "stale"}
