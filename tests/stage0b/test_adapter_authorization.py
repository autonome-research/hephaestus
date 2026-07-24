"""G0B adapter clause: authorization and exact attempted snapshots.

Architecture §3.5: writes carry the base content hash they were computed
against; a stale hash is a conflict returned with current content/hash and
content-addressed refs for the base and the **exact attempted candidate**.
Reads register immutable hash-addressed snapshots so the store can construct
that candidate after the live file changes. Privileged transitions (clearing
stale state, exporting) demand their authorization preconditions.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from _adapter_helpers import DEFAULT_SCRIPT, make_project, make_unpublished
from hephaestus.core.errors import AddressingError, ConflictError, ValidationError
from hephaestus.core.project_store.layout import ProjectLayout, open_store
from hephaestus.core.project_store.publication import Publisher
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


class TestSnapshotRegisteringReads:
    def test_read_registers_immutable_content_addressed_snapshot(
        self, parts: ProjectStore, store: OpStore
    ) -> None:
        snapshot = parts.read_part("widget")
        assert snapshot.content == DEFAULT_SCRIPT
        assert snapshot.content_hash == sha256_bytes(DEFAULT_SCRIPT.encode())
        assert snapshot.snapshot_ref.endswith(snapshot.content_hash)
        # The registered snapshot is durably stored, byte-exact.
        assert store.blobs.get(snapshot.content_hash) == DEFAULT_SCRIPT.encode()

    def test_missing_part_is_addressing_error_with_candidates(self, parts: ProjectStore) -> None:
        with pytest.raises(AddressingError) as excinfo:
            parts.read_part("wodget")
        assert excinfo.value.code == "addressing_error"
        assert "widget" in excinfo.value.candidates


class TestExactAttemptedSnapshots:
    def test_stale_base_conflict_carries_live_base_and_attempted(
        self, parts: ProjectStore, layout: ProjectLayout, store: OpStore
    ) -> None:
        base = parts.read_part("widget")
        # A cooperating writer lands first.
        interloper = "part.geometry = None  # interloper\n"
        parts.write_part("widget", interloper, base_hash=base.content_hash, op_id="w-interloper")
        # Our write was computed against the old base: refused, nothing written.
        attempted = "part.geometry = None  # attempted-on-stale-base\n"
        with pytest.raises(WriteConflictError) as excinfo:
            parts.write_part("widget", attempted, base_hash=base.content_hash, op_id="w-stale")
        conflict = excinfo.value
        assert conflict.code == "conflict"
        assert conflict.live_content == interloper
        assert conflict.live_hash == sha256_bytes(interloper.encode())
        assert conflict.base_ref is not None
        assert conflict.base_ref.endswith(base.content_hash)
        # The exact attempted candidate is reconstructible from its ref.
        attempted_blob = blob_hash_of_ref(conflict.attempted_ref)
        assert store.blobs.get(attempted_blob) == attempted.encode()
        # And the live registered snapshot matches the observed version.
        assert conflict.live_snapshot_ref is not None
        assert store.blobs.get(blob_hash_of_ref(conflict.live_snapshot_ref)) == (
            interloper.encode()
        )
        # Nothing was written to the live tree.
        assert layout.part_path("widget").read_text(encoding="utf-8") == interloper

    def test_create_conflicts_when_the_file_already_exists(self, parts: ProjectStore) -> None:
        with pytest.raises(WriteConflictError) as excinfo:
            parts.write_part("widget", "part.geometry = None\n", base_hash=None, op_id="w-create")
        assert excinfo.value.live_hash is not None
        assert excinfo.value.base_ref is None

    def test_successful_cas_write_commits_and_replays(
        self, parts: ProjectStore, layout: ProjectLayout
    ) -> None:
        base = parts.read_part("widget")
        content = "part.geometry = None  # v2\n"
        outcome = parts.write_part("widget", content, base_hash=base.content_hash, op_id="w-ok")
        assert not outcome.replayed
        assert layout.part_path("widget").read_text(encoding="utf-8") == content
        retry = parts.write_part("widget", content, base_hash=base.content_hash, op_id="w-ok")
        assert retry.replayed  # committed retry replays, never re-executes
        assert retry.snapshot.content_hash == outcome.snapshot.content_hash

    def test_preimage_journal_entry_written(
        self, parts: ProjectStore, layout: ProjectLayout, store: OpStore
    ) -> None:
        base = parts.read_part("widget")
        parts.write_part(
            "widget",
            "part.geometry = None  # v2\n",
            base_hash=base.content_hash,
            op_id="w-journal",
        )
        entries = list(layout.journal_dir.glob("*.json"))
        assert entries, "accepted overwrite must journal its preimage"
        import json

        recorded = [json.loads(p.read_text(encoding="utf-8")) for p in entries]
        ours = [e for e in recorded if e.get("op_id") == "w-journal"]
        assert len(ours) == 1
        preimage_blob = ours[0]["preimage_blob"]
        assert store.blobs.get(preimage_blob) == DEFAULT_SCRIPT.encode()


class TestPrivilegedTransitions:
    def test_clearing_stale_requires_publication_locks(
        self, layout: ProjectLayout, store: OpStore
    ) -> None:
        publisher = Publisher(layout, store)
        with pytest.raises(AssertionError):
            publisher.projections.record_current(
                "widget",
                consumed={},
                artifact_ref="artifact:build:sha256:" + "0" * 64,
            )

    def test_export_authorizes_only_durably_stored_sources(
        self, layout: ProjectLayout, store: OpStore, tmp_path: Path
    ) -> None:
        publisher = Publisher(layout, store)
        with pytest.raises(ConflictError):
            publisher.publish_export(
                name="widget.step",
                data=b"x",
                source_artifact_ref="artifact:build:sha256:" + "f" * 64,
                op_id="exp-unauthorized",
            )
        # After a real current publication the same export is authorized.
        build = make_unpublished(
            "widget",
            layout.part_path("widget").read_text(encoding="utf-8"),
            tmp_path / "out",
        )
        published = publisher.publish_build(build, op_id="pub-1")
        assert published.kind == "current"
        assert published.artifact_ref is not None
        outcome = publisher.publish_export(
            name="widget.step",
            data=b"exported",
            source_artifact_ref=published.artifact_ref,
            op_id="exp-authorized",
        )
        assert outcome.pinned
        assert outcome.path.read_bytes() == b"exported"

    def test_export_rejects_path_traversal_names(
        self, layout: ProjectLayout, store: OpStore
    ) -> None:
        publisher = Publisher(layout, store)
        for name in ("../escape.step", "a/b.step", "..", ""):
            with pytest.raises(ValidationError):
                publisher.publish_export(
                    name=name,
                    data=b"x",
                    source_artifact_ref="artifact:build:sha256:" + "f" * 64,
                    op_id="exp-bad",
                )

    def test_malformed_artifact_refs_are_refused(self) -> None:
        for ref in ("artifact:build:md5:abc", "blob:sha256:abc", "artifact:build:sha256:"):
            with pytest.raises(ValidationError):
                blob_hash_of_ref(ref)
