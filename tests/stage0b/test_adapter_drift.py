"""G0B adapter clause: external-drift conflicts.

Architecture §3.5: direct third-party filesystem writes bypass advisory
locking; a watcher snapshots observed external versions best-effort and
reports drift, but cannot provide filesystem compare-and-swap. Cooperative
writes computed against a drifted base conflict, and a build raced by an
external edit is never published current.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from _adapter_helpers import DEFAULT_SCRIPT, make_project, make_unpublished
from hephaestus.core.project_store.layout import ProjectLayout, open_store
from hephaestus.core.project_store.publication import Publisher, current_pointer
from hephaestus.core.project_store.store import (
    ProjectStore,
    WriteConflictError,
    blob_hash_of_ref,
)

from opstore import OpStore, sha256_bytes


@pytest.fixture
def layout(tmp_path: Path) -> ProjectLayout:
    return make_project(tmp_path / "proj")


@pytest.fixture
def store(layout: ProjectLayout) -> Iterator[OpStore]:
    handle = open_store(layout)
    yield handle
    handle.close()


@pytest.fixture
def parts(layout: ProjectLayout, store: OpStore) -> ProjectStore:
    return ProjectStore(layout, store)


EXTERNAL = "part.geometry = None  # third-party editor\n"


class TestDriftDetection:
    def test_unchanged_file_reports_no_drift(self, parts: ProjectStore) -> None:
        snapshot = parts.read_part("widget")
        assert parts.external_drift("widget", snapshot.content_hash) is None

    def test_external_write_reports_evidence_with_registered_snapshot(
        self, parts: ProjectStore, layout: ProjectLayout, store: OpStore
    ) -> None:
        snapshot = parts.read_part("widget")
        layout.part_path("widget").write_text(EXTERNAL, encoding="utf-8")
        evidence = parts.external_drift("widget", snapshot.content_hash)
        assert evidence is not None
        assert evidence.part == "widget"
        assert evidence.recorded_hash == snapshot.content_hash
        assert evidence.live_hash == sha256_bytes(EXTERNAL.encode())
        # The observed external version is registered immutably, byte-exact.
        assert evidence.live_snapshot_ref is not None
        assert store.blobs.get(blob_hash_of_ref(evidence.live_snapshot_ref)) == (EXTERNAL.encode())

    def test_externally_deleted_file_reports_gone(
        self, parts: ProjectStore, layout: ProjectLayout
    ) -> None:
        snapshot = parts.read_part("widget")
        layout.part_path("widget").unlink()
        evidence = parts.external_drift("widget", snapshot.content_hash)
        assert evidence is not None
        assert evidence.live_hash is None
        assert evidence.live_snapshot_ref is None


class TestDriftConflictsWrites:
    def test_write_against_externally_drifted_base_conflicts(
        self, parts: ProjectStore, layout: ProjectLayout
    ) -> None:
        base = parts.read_part("widget")
        layout.part_path("widget").write_text(EXTERNAL, encoding="utf-8")
        with pytest.raises(WriteConflictError) as excinfo:
            parts.write_part(
                "widget",
                "part.geometry = None  # cooperative edit\n",
                base_hash=base.content_hash,
                op_id="w-drifted",
            )
        conflict = excinfo.value
        assert conflict.live_content == EXTERNAL
        # The external version stays untouched: no filesystem CAS is claimed.
        assert layout.part_path("widget").read_text(encoding="utf-8") == EXTERNAL

    def test_write_computed_against_the_drifted_version_succeeds(
        self, parts: ProjectStore, layout: ProjectLayout
    ) -> None:
        parts.read_part("widget")
        layout.part_path("widget").write_text(EXTERNAL, encoding="utf-8")
        drifted_hash = sha256_bytes(EXTERNAL.encode())
        outcome = parts.write_part(
            "widget",
            "part.geometry = None  # rebased edit\n",
            base_hash=drifted_hash,
            op_id="w-rebased",
        )
        assert not outcome.replayed


class TestDriftConflictsPublication:
    def test_externally_edited_script_makes_the_build_raced(
        self, layout: ProjectLayout, store: OpStore, tmp_path: Path
    ) -> None:
        publisher = Publisher(layout, store)
        inputs = publisher.freeze_inputs("widget")
        assert inputs.script == DEFAULT_SCRIPT
        build = make_unpublished("widget", inputs.script, tmp_path / "out")
        # Third-party edit lands between snapshot freeze and publication.
        layout.part_path("widget").write_text(EXTERNAL, encoding="utf-8")
        outcome = publisher.publish_build(build, op_id="pub-drifted")
        assert outcome.kind == "raced"
        assert outcome.result.current is False
        assert any("script" in detail for detail in outcome.details)
        # Never current: the pointer is unmoved and nothing was cleared.
        assert store.blobs.read_pointer(current_pointer("widget")) is None
        # The superseded artifact stays content-addressed for audit.
        assert outcome.artifact_ref is not None
        assert store.blobs.has(blob_hash_of_ref(outcome.artifact_ref))

    def test_prior_current_survives_a_drift_raced_rebuild(
        self, layout: ProjectLayout, store: OpStore, tmp_path: Path
    ) -> None:
        publisher = Publisher(layout, store)
        first = publisher.publish_build(
            make_unpublished("widget", DEFAULT_SCRIPT, tmp_path / "o1"), op_id="pub-1"
        )
        assert first.kind == "current"
        inputs = publisher.freeze_inputs("widget")
        build = make_unpublished("widget", inputs.script, tmp_path / "o2")
        layout.part_path("widget").write_text(EXTERNAL, encoding="utf-8")
        raced = publisher.publish_build(build, op_id="pub-2")
        assert raced.kind == "raced"
        assert store.blobs.read_pointer(current_pointer("widget")) == first.record_blob
        stored = publisher.current_result("widget")
        assert stored is not None
        assert stored.artifact_ref == first.artifact_ref
