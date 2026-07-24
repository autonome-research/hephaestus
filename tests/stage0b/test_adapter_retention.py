"""G0B adapter clause: quota/retention policy (preview 7-day class, protected roots).

Architecture §3.5 artifact lifecycle: transient-parameter previews carry the
7-day retention class while ordinary evidence gets 30 days; the current
successful artifact is protected from GC; protected roots pass through the
adapter into reachability; and when protected bytes alone exceed the soft
quota, new artifact-producing operations fail with
``protected_quota_exceeded`` — nothing protected is silently removed.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _adapter_helpers import FakeClock, make_project, make_unpublished
from hephaestus.core.project_store.layout import ProjectLayout, open_store
from hephaestus.core.project_store.publication import Publisher, current_pointer
from hephaestus.core.project_store.store import blob_hash_of_ref
from opstore.gc import PREVIEW_RETENTION_CLASS
from opstore.types import StoreConfig

from opstore import GcAction, OpStore, ProtectedQuotaExceededError

DAY_S = 86_400.0


@pytest.fixture
def layout(tmp_path: Path) -> ProjectLayout:
    return make_project(tmp_path / "proj")


def _publish_current(publisher: Publisher, layout: ProjectLayout, out_dir: Path, op_id: str) -> str:
    build = make_unpublished(
        "widget", layout.part_path("widget").read_text(encoding="utf-8"), out_dir
    )
    outcome = publisher.publish_build(build, op_id=op_id)
    assert outcome.kind == "current", outcome.details
    assert outcome.artifact_ref is not None
    return outcome.artifact_ref


class TestRetentionClasses:
    def test_preview_evidence_carries_the_7d_class(
        self, layout: ProjectLayout, tmp_path: Path
    ) -> None:
        store = open_store(layout)
        try:
            publisher = Publisher(layout, store)
            _publish_current(publisher, layout, tmp_path / "o1", "pub-current")
            preview = make_unpublished(
                "widget",
                layout.part_path("widget").read_text(encoding="utf-8"),
                tmp_path / "o2",
                effective={"width": 999},  # transient override
            )
            outcome = publisher.publish_build(preview, op_id="pub-preview", preview=True)
            assert outcome.kind == "preview"
            assert store.blobs.retention_class(outcome.record_blob) == (PREVIEW_RETENTION_CLASS)
            assert outcome.artifact_ref is not None
            assert (
                store.blobs.retention_class(blob_hash_of_ref(outcome.artifact_ref))
                == PREVIEW_RETENTION_CLASS
            )
            # Ordinary current evidence stays in the default (30d) class.
            bundle = store.blobs.read_pointer(current_pointer("widget"))
            assert bundle is not None
            assert store.blobs.retention_class(bundle) == "default"
        finally:
            store.close()

    def test_retention_horizons_are_7_and_30_days(self, layout: ProjectLayout) -> None:
        store = open_store(layout)
        try:
            assert store.gc.retention_for(PREVIEW_RETENTION_CLASS) == 7 * DAY_S
            assert store.gc.retention_for("default") == 30 * DAY_S
        finally:
            store.close()

    def test_stale_preview_ages_out_after_7_days_but_not_before(
        self, layout: ProjectLayout, tmp_path: Path
    ) -> None:
        clock = FakeClock()
        store = open_store(layout, clock=clock)
        try:
            publisher = Publisher(layout, store)
            preview = make_unpublished(
                "widget",
                layout.part_path("widget").read_text(encoding="utf-8"),
                tmp_path / "o1",
                effective={"width": 999},
            )
            outcome = publisher.publish_build(preview, op_id="pub-preview", preview=True)
            assert outcome.kind == "preview"
            assert outcome.artifact_ref is not None
            preview_blob = blob_hash_of_ref(outcome.artifact_ref)

            clock.advance(6 * DAY_S)
            report = store.gc.collect(dry_run=True)
            assert preview_blob not in {c.ref for c in report.candidates}

            clock.advance(2 * DAY_S)  # now 8 days old
            report = store.gc.collect(dry_run=True)
            actions = {c.ref: c.action for c in report.candidates}
            assert actions.get(preview_blob) == GcAction.WOULD_COLLECT
        finally:
            store.close()


class TestProtectedRoots:
    def test_protected_roots_pass_through_the_adapter_into_reachability(
        self, layout: ProjectLayout
    ) -> None:
        clock = FakeClock()
        roots: list[str] = []
        store = open_store(layout, clock=clock, protected_roots=lambda: list(roots))
        try:
            protected = store.blobs.put(b"protected artifact bytes")
            unprotected = store.blobs.put(b"unprotected artifact bytes")
            roots.append(protected)
            clock.advance(40 * DAY_S)
            report = store.gc.collect(dry_run=False)
            collected = {c.ref for c in report.candidates if c.action is GcAction.COLLECTED}
            assert unprotected in collected
            assert protected not in collected
            assert store.blobs.get(protected) == b"protected artifact bytes"
        finally:
            store.close()

    def test_current_publication_survives_gc_past_default_retention(
        self, layout: ProjectLayout, tmp_path: Path
    ) -> None:
        """The current successful artifact and its bundle are protected refs.

        Architecture §3.5: "The current successful artifact ... per part are
        protected"; GC "never deletes protected refs". Aging the store past
        the default retention horizon must not collect the live current
        bundle, its BuildResult record, or the current artifact bytes.
        """
        clock = FakeClock()
        store = open_store(layout, clock=clock)
        try:
            publisher = Publisher(layout, store)
            artifact_ref = _publish_current(publisher, layout, tmp_path / "o1", "pub-1")
            bundle = store.blobs.read_pointer(current_pointer("widget"))
            assert bundle is not None
            clock.advance(40 * DAY_S)
            store.gc.collect(dry_run=False)
            # The current pointer still resolves to a complete bundle...
            assert store.blobs.read_pointer(current_pointer("widget")) == bundle
            assert store.blobs.has(bundle), (
                "current bundle was garbage-collected: the adapter must "
                "register current publications as protected roots"
            )
            # ...and the current artifact bytes are still readable.
            assert store.blobs.has(blob_hash_of_ref(artifact_ref))
            stored = publisher.current_result("widget")
            assert stored is not None
            assert stored.artifact_ref == artifact_ref
        finally:
            store.close()


class TestQuota:
    def test_soft_quota_defaults_to_10_gib(self, layout: ProjectLayout) -> None:
        store = open_store(layout)
        try:
            assert store.config.quota_bytes == 10 * 1024**3
        finally:
            store.close()

    def test_protected_roots_exceeding_quota_fail_new_work_loudly(
        self, layout: ProjectLayout
    ) -> None:
        layout.store_root.mkdir(parents=True, exist_ok=True)
        seed = open_store(layout)
        seed.close()
        roots: list[str] = []
        store = OpStore.open(
            layout.store_root,
            StoreConfig(quota_bytes=64),
            protected_roots=lambda: list(roots),
        )
        try:
            big = store.blobs.put(b"x" * 4096)
            roots.append(big)
            with pytest.raises(ProtectedQuotaExceededError) as excinfo:
                store.gc.admission_guard()
            assert excinfo.value.code == "protected_quota_exceeded"
            # Nothing protected is silently removed even by a real GC pass.
            store.gc.collect(dry_run=False)
            assert store.blobs.has(big)
        finally:
            store.close()
