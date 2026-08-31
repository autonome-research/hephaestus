"""Publication tests: current flips, never-current outcomes, crash recovery."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from collections.abc import Iterator
from pathlib import Path

import pytest
from hephaestus.core.errors import ConflictError, ValidationError
from hephaestus.core.executor.runner import UnpublishedBuild
from hephaestus.core.project_store.layout import ProjectLayout, open_store
from hephaestus.core.project_store.publication import (
    Publisher,
    current_pointer,
)
from hephaestus.core.project_store.store import blob_hash_of_ref
from opstore.gc import PREVIEW_RETENTION_CLASS
from test_project_store_helpers import (
    DEFAULT_SCRIPT,
    build_for_crash,
    make_project,
    make_unpublished,
)

from opstore import OpStore, sha256_bytes

GLOBALS_SOURCE = "T = 6\n"


@pytest.fixture
def layout(tmp_path: Path) -> ProjectLayout:
    return make_project(tmp_path / "proj", globals_source=GLOBALS_SOURCE)


@pytest.fixture
def opstore(layout: ProjectLayout) -> Iterator[OpStore]:
    store = open_store(layout)
    yield store
    store.close()


@pytest.fixture
def publisher(layout: ProjectLayout, opstore: OpStore) -> Publisher:
    return Publisher(layout, opstore)


def make_build(layout: ProjectLayout, out_dir: Path) -> UnpublishedBuild:
    script = layout.part_path("widget").read_text()
    return make_unpublished("widget", script, out_dir)


class TestFreezeInputs:
    def test_captures_snapshots_and_releases_locks(
        self, layout: ProjectLayout, publisher: Publisher
    ) -> None:
        frozen = publisher.freeze_inputs("widget")
        assert frozen.part == "widget"
        assert frozen.script == DEFAULT_SCRIPT
        assert frozen.script_hash == sha256_bytes(DEFAULT_SCRIPT.encode())
        assert frozen.script_snapshot_ref.endswith(frozen.script_hash)
        assert frozen.globals_source == GLOBALS_SOURCE
        assert frozen.globals_snapshot_ref is not None
        assert publisher.locks.held() == ()  # released before geometry


class TestCurrentPublication:
    def test_successful_build_becomes_current(
        self, layout: ProjectLayout, opstore: OpStore, publisher: Publisher, tmp_path: Path
    ) -> None:
        build = make_unpublished(
            "widget",
            layout.part_path("widget").read_text(),
            tmp_path / "out",
            consumed={"T": 6},
        )
        publisher.projections.apply_hc_state({"T": 6})
        outcome = publisher.publish_build(build, op_id="pub-1")
        assert outcome.kind == "current"
        assert not outcome.replayed
        assert outcome.result.current is True
        assert outcome.result.status == "ok"
        # Artifact bytes are installed content-addressed under their ref.
        assert outcome.artifact_ref is not None
        blob = blob_hash_of_ref(outcome.artifact_ref)
        assert opstore.blobs.get(blob) == (tmp_path / "out" / "final.brep").read_bytes()
        # The current pointer addresses the published bundle.
        assert opstore.blobs.read_pointer(current_pointer("widget")) == outcome.record_blob
        stored = publisher.current_result("widget")
        assert stored is not None
        assert stored.current is True
        assert stored.artifact_ref == outcome.artifact_ref
        # Publication recorded the projection and cleared nothing improperly.
        state = publisher.projections.state()
        assert state.projections["widget"].artifact_ref == outcome.artifact_ref
        assert state.stale == {}
        # Locks are fully released.
        assert publisher.locks.held() == ()

    def test_retry_replays_idempotently(
        self, layout: ProjectLayout, opstore: OpStore, publisher: Publisher, tmp_path: Path
    ) -> None:
        build = make_build(layout, tmp_path / "out")
        first = publisher.publish_build(build, op_id="pub-1")
        again = publisher.publish_build(build, op_id="pub-1")
        assert first.kind == "current"
        assert again.kind == "current"
        assert again.replayed
        assert again.record_blob == first.record_blob
        assert opstore.blobs.read_pointer(current_pointer("widget")) == first.record_blob

    def test_baseline_for_current(
        self, layout: ProjectLayout, publisher: Publisher, tmp_path: Path
    ) -> None:
        assert publisher.baseline_for("widget") is None
        outcome = publisher.publish_build(
            make_build(layout, tmp_path / "out"),
            op_id="pub-1",
        )
        baseline = publisher.baseline_for("widget")
        assert baseline is not None
        assert baseline.artifact_ref == outcome.artifact_ref
        assert dict(baseline.descriptors) == {}


class TestNeverCurrent:
    def _publish_current(self, layout: ProjectLayout, publisher: Publisher, out_dir: Path) -> str:
        publisher.projections.apply_hc_state({"T": 6})
        outcome = publisher.publish_build(
            make_unpublished(
                "widget",
                layout.part_path("widget").read_text(),
                out_dir,
                consumed={"T": 6},
            ),
            op_id="seed-current",
        )
        assert outcome.kind == "current"
        return outcome.record_blob

    def test_failed_build_publishes_evidence_only(
        self, layout: ProjectLayout, opstore: OpStore, publisher: Publisher, tmp_path: Path
    ) -> None:
        bundle = self._publish_current(layout, publisher, tmp_path / "out1")
        # A later project change marks the part stale...
        publisher.projections.apply_hc_state({"T": 8})
        assert publisher.projections.state().stale
        failed = make_unpublished(
            "widget",
            layout.part_path("widget").read_text(),
            tmp_path / "out2",
            consumed={"T": 8},
            status="failed",
        )
        outcome = publisher.publish_build(failed, op_id="pub-failed")
        assert outcome.kind == "failed"
        assert outcome.result.current is False
        recorded = publisher.last_failure_result("widget")
        assert recorded is not None
        assert recorded.status == "failed"
        assert recorded.artifact_ref is None
        # Checkpoint evidence blobs are published...
        assert len(outcome.evidence_refs) == 1
        checkpoint_ref = outcome.evidence_refs[0]
        assert checkpoint_ref.startswith("artifact:build-checkpoint:")
        assert opstore.blobs.has(blob_hash_of_ref(checkpoint_ref))
        # ...but the prior current artifact is preserved and stale persists.
        assert opstore.blobs.read_pointer(current_pointer("widget")) == bundle
        assert publisher.projections.state().stale
        assert publisher.baseline_for("widget") is not None

    def test_preview_never_current_and_uses_7d_retention(
        self, layout: ProjectLayout, opstore: OpStore, publisher: Publisher, tmp_path: Path
    ) -> None:
        bundle = self._publish_current(layout, publisher, tmp_path / "out1")
        publisher.projections.apply_hc_state({"T": 8})
        preview_build = make_unpublished(
            "widget",
            layout.part_path("widget").read_text(),
            tmp_path / "out2",
            consumed={"T": 8},
            effective={"width": 999},  # transient override
        )
        outcome = publisher.publish_build(preview_build, op_id="pub-preview", preview=True)
        assert outcome.kind == "preview"
        assert outcome.result.current is False
        assert opstore.blobs.read_pointer(current_pointer("widget")) == bundle
        assert publisher.projections.state().stale  # previews never clear stale
        # Preview evidence carries the 7-day retention class.
        assert opstore.blobs.retention_class(outcome.record_blob) == PREVIEW_RETENTION_CLASS
        assert outcome.artifact_ref is not None
        assert (
            opstore.blobs.retention_class(blob_hash_of_ref(outcome.artifact_ref))
            == PREVIEW_RETENTION_CLASS
        )

    def test_raced_script_edit_never_current(
        self, layout: ProjectLayout, opstore: OpStore, publisher: Publisher, tmp_path: Path
    ) -> None:
        build = make_build(layout, tmp_path / "out")
        # The script changes between snapshot and publication.
        layout.part_path("widget").write_text("part.geometry = 1  # racing edit\n")
        outcome = publisher.publish_build(build, op_id="pub-raced")
        assert outcome.kind == "raced"
        assert outcome.result.current is False
        assert any("script" in detail for detail in outcome.details)
        assert opstore.blobs.read_pointer(current_pointer("widget")) is None
        assert publisher.current_result("widget") is None
        # The superseded artifact is retained content-addressed for audit.
        assert outcome.artifact_ref is not None
        assert opstore.blobs.has(blob_hash_of_ref(outcome.artifact_ref))
        assert publisher.locks.held() == ()

    def test_raced_hc_change_never_current_and_keeps_stale(
        self, layout: ProjectLayout, opstore: OpStore, publisher: Publisher, tmp_path: Path
    ) -> None:
        publisher.projections.apply_hc_state({"T": 6})
        build = make_unpublished(
            "widget",
            layout.part_path("widget").read_text(),
            tmp_path / "out",
            consumed={"T": 6},
        )
        # Project params move after the snapshot was frozen.
        publisher.projections.apply_hc_state({"T": 8})
        stale_before = dict(publisher.projections.state().stale)
        outcome = publisher.publish_build(build, op_id="pub-raced-hc")
        assert outcome.kind == "raced"
        assert any("hc_dependencies" in detail for detail in outcome.details)
        assert opstore.blobs.read_pointer(current_pointer("widget")) is None
        assert dict(publisher.projections.state().stale) == stale_before


class TestExports:
    def test_export_installs_pins_and_links(
        self, layout: ProjectLayout, opstore: OpStore, publisher: Publisher, tmp_path: Path
    ) -> None:
        published = publisher.publish_build(
            make_build(layout, tmp_path / "out"),
            op_id="pub-1",
        )
        assert published.artifact_ref is not None
        data = b"solid widget\nendsolid widget\n"
        outcome = publisher.publish_export(
            name="widget.step",
            data=data,
            source_artifact_ref=published.artifact_ref,
            op_id="exp-1",
        )
        assert outcome.path == layout.exports_dir / "widget.step"
        assert outcome.path.read_bytes() == data
        assert outcome.pinned
        assert not outcome.replayed
        assert outcome.blob_hash == sha256_bytes(data)
        assert outcome.export_ref == f"artifact:export:{outcome.blob_hash}"
        # GC-root pin + provenance edge to the source build survive in opstore.
        assert outcome.blob_hash in opstore.gc.pins()
        assert (
            outcome.blob_hash,
            blob_hash_of_ref(published.artifact_ref),
        ) in opstore.gc.links()
        assert outcome.blob_hash in opstore.gc.reachable()

        retry = publisher.publish_export(
            name="widget.step",
            data=data,
            source_artifact_ref=published.artifact_ref,
            op_id="exp-1",
        )
        assert retry.replayed
        assert outcome.path.read_bytes() == data

    def test_export_requires_stored_source(self, publisher: Publisher) -> None:
        with pytest.raises(ConflictError):
            publisher.publish_export(
                name="widget.step",
                data=b"x",
                source_artifact_ref="artifact:build:sha256:" + "f" * 64,
                op_id="exp-missing",
            )

    def test_export_rejects_path_names(self, publisher: Publisher) -> None:
        with pytest.raises(ValidationError):
            publisher.publish_export(
                name="../escape.step",
                data=b"x",
                source_artifact_ref="artifact:build:sha256:" + "f" * 64,
                op_id="exp-bad",
            )


CRASH_RUNNER = textwrap.dedent(
    """
    import sys
    from pathlib import Path

    sys.path.insert(0, sys.argv[1])
    from test_project_store_helpers import build_for_crash

    from hephaestus.core.project_store.layout import load_project
    from hephaestus.core.project_store.locks import LockManager
    from hephaestus.core.project_store.publication import Publisher
    from opstore import OpStore
    from opstore.types import EnvCrashHook

    project_root = Path(sys.argv[2])
    out_dir = Path(sys.argv[3])
    op_id = sys.argv[4]
    layout = load_project(project_root)
    store = OpStore.open(layout.store_root, crash_hook=EnvCrashHook())
    # Short lease TTL: leases a crashed child leaves behind must expire so
    # the retrying parent can liveness-reclaim them.
    publisher = Publisher(layout, store, locks=LockManager(store, lease_ttl_s=0.5))
    build = build_for_crash(layout, out_dir)
    outcome = publisher.publish_build(build, op_id=op_id)
    store.close()
    print("no-crash", outcome.kind)
    """
).lstrip()

#: Every publication boundary: blob fsync, blob install, PREPARED,
#: pointer CAS, COMMITTED.
CRASH_POINTS = (
    "blobs.put.after_file_fsync",
    "blobs.put.after_rename",
    "publish.after_prepared",
    "publish.after_swap",
    "publish.after_committed",
)


class TestCrashRecovery:
    @pytest.mark.parametrize("point", CRASH_POINTS)
    def test_deterministic_single_outcome_from_every_boundary(
        self, tmp_path: Path, point: str
    ) -> None:
        layout = make_project(tmp_path / "proj")
        open_store(layout).close()  # initialize the store
        out_dir = tmp_path / "out"
        runner = tmp_path / "runner.py"
        runner.write_text(CRASH_RUNNER)
        tests_dir = Path(__file__).parent

        result = subprocess.run(
            [
                sys.executable,
                str(runner),
                str(tests_dir),
                str(layout.root),
                str(out_dir),
                "pub-crash",
            ],
            env={**os.environ, "OPSTORE_CRASH_POINT": point},
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert result.returncode == 42, result.stderr

        store = open_store(layout)
        try:
            recovery = store.recover()  # startup recovery resolves PREPARED rows
            assert all(o.action != "conflicted" for o in recovery.wal)
            pointer_before = store.blobs.read_pointer(current_pointer("widget"))

            publisher = Publisher(layout, store)
            build = build_for_crash(layout, out_dir)
            outcome = publisher.publish_build(build, op_id="pub-crash")
            assert outcome.kind == "current"
            pointer_after = store.blobs.read_pointer(current_pointer("widget"))
            # No partial publish: before the retry the pointer was either
            # untouched or already at the final bundle — never a third state.
            assert pointer_before in (None, pointer_after)
            assert pointer_after == outcome.record_blob
            # Deterministic single outcome, identical across crash points.
            stored = publisher.current_result("widget")
            assert stored is not None
            assert stored.current is True
            assert stored.artifact_ref == outcome.artifact_ref
            state = publisher.projections.state()
            assert state.projections["widget"].artifact_ref == outcome.artifact_ref
            assert state.stale == {}
            # And the retry is idempotent from here on.
            again = publisher.publish_build(build, op_id="pub-crash")
            assert again.kind == "current"
            assert again.replayed
            assert store.blobs.read_pointer(current_pointer("widget")) == pointer_after
        finally:
            store.close()


class TestEvidenceIntegrity:
    def test_corrupt_artifact_bytes_refused(
        self, layout: ProjectLayout, publisher: Publisher, tmp_path: Path
    ) -> None:
        build = make_build(layout, tmp_path / "out")
        # Corrupt the artifact file after hashing.
        (tmp_path / "out" / "final.brep").write_bytes(b"tampered")
        with pytest.raises(ConflictError, match="corrupt"):
            publisher.publish_build(build, op_id="pub-corrupt")
