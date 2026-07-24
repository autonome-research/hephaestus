"""Store tests: snapshot-registering reads, WAL CAS writes, drift conflicts.

Also holds the import-graph guard: project_store modules must import their
WAL/lease/CAS machinery from ``opstore`` and never reimplement it beside
(no ``sqlite3``, no ``fcntl``).
"""

from __future__ import annotations

import importlib
import json
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from hephaestus.core.errors import AddressingError
from hephaestus.core.project_store.layout import ProjectLayout, open_store
from hephaestus.core.project_store.store import (
    SNAPSHOT_REF_PREFIX,
    ProjectStore,
    WriteConflictError,
    artifact_ref,
    blob_hash_of_ref,
)
from test_project_store_helpers import make_project

from opstore import KeyPayloadMismatchError, OpStore, sha256_bytes

SCRIPT_V1 = "WIDTH = 100\n"
SCRIPT_V2 = "WIDTH = 120\n"
SCRIPT_EXTERNAL = "WIDTH = 999  # external editor\n"


@pytest.fixture
def layout(tmp_path: Path) -> ProjectLayout:
    return make_project(
        tmp_path / "proj",
        parts={"widget": SCRIPT_V1, "bracket": "L = 3\n"},
        globals_source="G = 1\n",
    )


@pytest.fixture
def opstore(layout: ProjectLayout) -> Iterator[OpStore]:
    store = open_store(layout)
    yield store
    store.close()


@pytest.fixture
def store(layout: ProjectLayout, opstore: OpStore) -> ProjectStore:
    return ProjectStore(layout, opstore)


class TestRefs:
    def test_roundtrip(self) -> None:
        blob = "sha256:" + "ab" * 32
        ref = artifact_ref("build", blob)
        assert ref == f"artifact:build:{blob}"
        assert blob_hash_of_ref(ref) == blob

    @pytest.mark.parametrize(
        "bad", ["", "sha256:abc", "artifact:build:md5:00", "artifact:sha256:00"]
    )
    def test_malformed_ref_rejected(self, bad: str) -> None:
        from hephaestus.core.errors import ValidationError

        with pytest.raises(ValidationError):
            blob_hash_of_ref(bad)


class TestReads:
    def test_read_part_registers_snapshot(self, store: ProjectStore, opstore: OpStore) -> None:
        snapshot = store.read_part("widget")
        assert snapshot.content == SCRIPT_V1
        assert snapshot.content_hash == sha256_bytes(SCRIPT_V1.encode())
        assert snapshot.snapshot_ref == SNAPSHOT_REF_PREFIX + snapshot.content_hash
        assert re.fullmatch(r"artifact:part-snapshot:sha256:[0-9a-f]{64}", snapshot.snapshot_ref)
        # The snapshot content is immutably registered in the CAS.
        assert opstore.blobs.get(snapshot.content_hash) == SCRIPT_V1.encode()

    def test_read_missing_part_lists_candidates(self, store: ProjectStore) -> None:
        with pytest.raises(AddressingError) as exc_info:
            store.read_part("gusset")
        assert exc_info.value.code == "addressing_error"
        assert exc_info.value.candidates == ("bracket", "widget")

    def test_read_globals(self, store: ProjectStore) -> None:
        snapshot = store.read_globals()
        assert snapshot is not None
        assert snapshot.content == "G = 1\n"

    def test_read_globals_absent(self, tmp_path: Path) -> None:
        layout = make_project(tmp_path / "bare")
        with open_store(layout) as opstore:
            assert ProjectStore(layout, opstore).read_globals() is None

    def test_list_parts(self, store: ProjectStore) -> None:
        assert store.list_parts() == ("bracket", "widget")


class TestWrites:
    def test_create_and_update(self, layout: ProjectLayout, store: ProjectStore) -> None:
        outcome = store.write_part("gusset", SCRIPT_V1, base_hash=None, op_id="w-create")
        assert not outcome.replayed
        assert layout.part_path("gusset").read_text() == SCRIPT_V1

        updated = store.write_part(
            "gusset",
            SCRIPT_V2,
            base_hash=outcome.snapshot.content_hash,
            op_id="w-update",
        )
        assert layout.part_path("gusset").read_text() == SCRIPT_V2
        assert updated.snapshot.content_hash == sha256_bytes(SCRIPT_V2.encode())

    def test_write_journals_preimage(
        self, layout: ProjectLayout, store: ProjectStore, opstore: OpStore
    ) -> None:
        base = store.read_part("widget")
        store.write_part("widget", SCRIPT_V2, base_hash=base.content_hash, op_id="w-journal")
        entries = list(layout.journal_dir.glob("*.json"))
        assert entries, "preimage journal entry missing"
        payloads = [json.loads(entry.read_text()) for entry in entries]
        entry = next(p for p in payloads if p["op_id"] == "w-journal")
        assert entry["part"] == "widget"
        assert entry["before_hash"] == base.content_hash
        assert entry["after_hash"] == sha256_bytes(SCRIPT_V2.encode())
        # The journaled preimage blob reconstructs the overwritten content.
        assert opstore.blobs.get(entry["preimage_blob"]) == SCRIPT_V1.encode()

    def test_committed_retry_replays(self, layout: ProjectLayout, store: ProjectStore) -> None:
        base = store.read_part("widget")
        first = store.write_part("widget", SCRIPT_V2, base_hash=base.content_hash, op_id="w-retry")
        again = store.write_part("widget", SCRIPT_V2, base_hash=base.content_hash, op_id="w-retry")
        assert not first.replayed
        assert again.replayed
        assert again.snapshot.content_hash == first.snapshot.content_hash
        assert layout.part_path("widget").read_text() == SCRIPT_V2

    def test_op_id_reuse_with_other_payload_fails(self, store: ProjectStore) -> None:
        base = store.read_part("widget")
        store.write_part("widget", SCRIPT_V2, base_hash=base.content_hash, op_id="w-reuse")
        with pytest.raises(KeyPayloadMismatchError):
            store.write_part(
                "widget",
                "WIDTH = 777\n",
                base_hash=sha256_bytes(SCRIPT_V2.encode()),
                op_id="w-reuse",
            )

    def test_stale_base_conflict_evidence(
        self, layout: ProjectLayout, store: ProjectStore, opstore: OpStore
    ) -> None:
        base = store.read_part("widget")
        # A cooperating writer lands first.
        store.write_part("widget", SCRIPT_V2, base_hash=base.content_hash, op_id="w-a")
        with pytest.raises(WriteConflictError) as exc_info:
            store.write_part("widget", "WIDTH = 111\n", base_hash=base.content_hash, op_id="w-b")
        conflict = exc_info.value
        assert conflict.code == "conflict"
        assert conflict.part == "widget"
        assert conflict.live_hash == sha256_bytes(SCRIPT_V2.encode())
        assert conflict.live_content == SCRIPT_V2
        assert conflict.base_ref == SNAPSHOT_REF_PREFIX + base.content_hash
        # The exact attempted candidate is content-addressed and recoverable.
        assert conflict.attempted_ref is not None
        attempted_blob = blob_hash_of_ref(conflict.attempted_ref)
        assert opstore.blobs.get(attempted_blob) == b"WIDTH = 111\n"
        # Nothing was written.
        assert layout.part_path("widget").read_text() == SCRIPT_V2

    def test_external_drift_conflict(self, layout: ProjectLayout, store: ProjectStore) -> None:
        base = store.read_part("widget")
        # A third-party editor bypasses the store API entirely.
        layout.part_path("widget").write_text(SCRIPT_EXTERNAL)
        with pytest.raises(WriteConflictError) as exc_info:
            store.write_part("widget", SCRIPT_V2, base_hash=base.content_hash, op_id="w-drift")
        assert exc_info.value.live_hash == sha256_bytes(SCRIPT_EXTERNAL.encode())
        assert layout.part_path("widget").read_text() == SCRIPT_EXTERNAL


class TestExternalDrift:
    def test_unchanged_returns_none(self, store: ProjectStore) -> None:
        snapshot = store.read_part("widget")
        assert store.external_drift("widget", snapshot.content_hash) is None

    def test_drift_reports_live_snapshot(
        self, layout: ProjectLayout, store: ProjectStore, opstore: OpStore
    ) -> None:
        snapshot = store.read_part("widget")
        layout.part_path("widget").write_text(SCRIPT_EXTERNAL)
        evidence = store.external_drift("widget", snapshot.content_hash)
        assert evidence is not None
        assert evidence.recorded_hash == snapshot.content_hash
        assert evidence.live_hash == sha256_bytes(SCRIPT_EXTERNAL.encode())
        assert evidence.live_snapshot_ref is not None
        assert (
            opstore.blobs.get(blob_hash_of_ref(evidence.live_snapshot_ref))
            == SCRIPT_EXTERNAL.encode()
        )

    def test_deleted_file_reports_gone(self, layout: ProjectLayout, store: ProjectStore) -> None:
        snapshot = store.read_part("widget")
        layout.part_path("widget").unlink()
        evidence = store.external_drift("widget", snapshot.content_hash)
        assert evidence is not None
        assert evidence.live_hash is None
        assert evidence.live_snapshot_ref is None


class TestImportGraph:
    """opstore is imported, never reimplemented beside (DESIGN non-negotiable)."""

    MODULES = (
        "hephaestus.core.project_store.layout",
        "hephaestus.core.project_store.locks",
        "hephaestus.core.project_store.store",
        "hephaestus.core.project_store.projections",
        "hephaestus.core.project_store.publication",
    )

    def _source(self, module_name: str) -> str:
        module = importlib.import_module(module_name)
        assert module.__file__ is not None
        return Path(module.__file__).read_text(encoding="utf-8")

    @pytest.mark.parametrize("module_name", MODULES)
    def test_no_locking_or_db_reimplementation(self, module_name: str) -> None:
        source = self._source(module_name)
        assert "import sqlite3" not in source, "must not talk to SQLite directly"
        assert "fcntl" not in source, "must not build file locks beside opstore leases"
        assert "flock" not in source
        assert "lockf" not in source

    @pytest.mark.parametrize("module_name", MODULES)
    def test_imports_opstore(self, module_name: str) -> None:
        source = self._source(module_name)
        assert "from opstore" in source or "import opstore" in source

    def test_durability_machinery_comes_from_opstore(self) -> None:
        # Leases for locks, WAL for writes/publication, CAS for pointers.
        assert "leases.acquire_exclusive" in self._source("hephaestus.core.project_store.locks")
        assert "wal.execute" in self._source("hephaestus.core.project_store.store")
        publication = self._source("hephaestus.core.project_store.publication")
        assert "wal.publish" in publication
        assert "wal.execute" in publication
        assert "cas_swap" in self._source("hephaestus.core.project_store.projections")
