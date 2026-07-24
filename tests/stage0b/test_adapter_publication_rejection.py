"""G0B adapter clause: stale/failed/preview publication rejection.

Architecture §3.5: failed builds and transient-parameter previews always have
``current=false``, preserve the prior successful current artifact, and never
clear stale state; a build whose frozen inputs went stale before publication
is raced — it may retain a content-addressed superseded artifact for audit
but cannot become current.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from _adapter_helpers import make_project, make_unpublished
from hephaestus.core.project_store.layout import ProjectLayout, open_store
from hephaestus.core.project_store.publication import Publisher, current_pointer
from hephaestus.core.project_store.store import blob_hash_of_ref

from opstore import OpStore


@pytest.fixture
def layout(tmp_path: Path) -> ProjectLayout:
    return make_project(tmp_path / "proj", globals_source="T = 6\n")


@pytest.fixture
def store(layout: ProjectLayout) -> Iterator[OpStore]:
    handle = open_store(layout)
    yield handle
    handle.close()


@pytest.fixture
def publisher(layout: ProjectLayout, store: OpStore) -> Publisher:
    return Publisher(layout, store)


@pytest.fixture
def seeded(publisher: Publisher, layout: ProjectLayout, tmp_path: Path) -> tuple[Publisher, str]:
    """widget current at hc {T: 6}; returns (publisher, current bundle blob)."""
    publisher.projections.apply_hc_state({"T": 6})
    build = make_unpublished(
        "widget",
        layout.part_path("widget").read_text(encoding="utf-8"),
        tmp_path / "seed",
        consumed={"T": 6},
    )
    outcome = publisher.publish_build(build, op_id="seed-current")
    assert outcome.kind == "current", outcome.details
    return publisher, outcome.record_blob


class TestFailedRejection:
    def test_failed_build_is_evidence_only(
        self,
        seeded: tuple[Publisher, str],
        layout: ProjectLayout,
        store: OpStore,
        tmp_path: Path,
    ) -> None:
        publisher, bundle = seeded
        publisher.projections.apply_hc_state({"T": 8})
        assert set(publisher.projections.state().stale) == {"widget"}
        failed = make_unpublished(
            "widget",
            layout.part_path("widget").read_text(encoding="utf-8"),
            tmp_path / "fail",
            consumed={"T": 8},
            status="failed",
        )
        outcome = publisher.publish_build(failed, op_id="pub-failed")
        assert outcome.kind == "failed"
        assert outcome.result.current is False
        # Checkpoint evidence is durably published...
        assert outcome.evidence_refs
        for ref in outcome.evidence_refs:
            assert store.blobs.has(blob_hash_of_ref(ref))
        # ...while the prior current artifact, baseline, and stale survive.
        assert store.blobs.read_pointer(current_pointer("widget")) == bundle
        assert set(publisher.projections.state().stale) == {"widget"}
        assert publisher.baseline_for("widget") is not None
        stored = publisher.current_result("widget")
        assert stored is not None
        assert stored.status == "ok"

    def test_failed_build_reports_last_good_artifact_ref(
        self, seeded: tuple[Publisher, str], layout: ProjectLayout, tmp_path: Path
    ) -> None:
        publisher, _ = seeded
        failed = make_unpublished(
            "widget",
            layout.part_path("widget").read_text(encoding="utf-8"),
            tmp_path / "fail",
            consumed={"T": 6},
            status="failed",
        )
        outcome = publisher.publish_build(failed, op_id="pub-failed-2")
        error = outcome.result.error
        assert error is not None
        assert error.last_good_artifact_ref in outcome.evidence_refs


class TestPreviewRejection:
    def test_preview_never_current_never_clears_stale(
        self,
        seeded: tuple[Publisher, str],
        layout: ProjectLayout,
        store: OpStore,
        tmp_path: Path,
    ) -> None:
        publisher, bundle = seeded
        publisher.projections.apply_hc_state({"T": 8})
        preview = make_unpublished(
            "widget",
            layout.part_path("widget").read_text(encoding="utf-8"),
            tmp_path / "preview",
            consumed={"T": 8},
            effective={"width": 999},
        )
        outcome = publisher.publish_build(preview, op_id="pub-preview", preview=True)
        assert outcome.kind == "preview"
        assert outcome.result.current is False
        assert store.blobs.read_pointer(current_pointer("widget")) == bundle
        assert set(publisher.projections.state().stale) == {"widget"}
        # The preview evidence is still durably retrievable (7d class).
        assert outcome.artifact_ref is not None
        assert store.blobs.has(blob_hash_of_ref(outcome.artifact_ref))

    def test_preview_does_not_move_the_fingerprint_baseline(
        self, seeded: tuple[Publisher, str], layout: ProjectLayout, tmp_path: Path
    ) -> None:
        publisher, _ = seeded
        baseline_before = publisher.baseline_for("widget")
        assert baseline_before is not None
        preview = make_unpublished(
            "widget",
            layout.part_path("widget").read_text(encoding="utf-8"),
            tmp_path / "preview",
            consumed={"T": 6},
            effective={"width": 999},
        )
        publisher.publish_build(preview, op_id="pub-preview-2", preview=True)
        baseline_after = publisher.baseline_for("widget")
        assert baseline_after is not None
        assert baseline_after.artifact_ref == baseline_before.artifact_ref


class TestStaleRejection:
    def test_build_frozen_before_hc_change_is_raced_not_current(
        self,
        seeded: tuple[Publisher, str],
        layout: ProjectLayout,
        store: OpStore,
        tmp_path: Path,
    ) -> None:
        publisher, bundle = seeded
        # Frozen against the old projection...
        outdated = make_unpublished(
            "widget",
            layout.part_path("widget").read_text(encoding="utf-8"),
            tmp_path / "old",
            consumed={"T": 6},
        )
        # ...then the project moves on before publication.
        publisher.projections.apply_hc_state({"T": 8})
        stale_before = dict(publisher.projections.state().stale)
        assert stale_before
        outcome = publisher.publish_build(outdated, op_id="pub-stale")
        assert outcome.kind == "raced"
        assert outcome.result.current is False
        assert any("hc_dependencies" in detail for detail in outcome.details)
        # Rejected publication changes nothing: pointer and stale untouched.
        assert store.blobs.read_pointer(current_pointer("widget")) == bundle
        assert dict(publisher.projections.state().stale) == stale_before
        # The superseded artifact is retained content-addressed for audit.
        assert outcome.artifact_ref is not None
        assert store.blobs.has(blob_hash_of_ref(outcome.artifact_ref))

    def test_raced_retry_replays_from_its_original_frozen_snapshot(
        self, seeded: tuple[Publisher, str], layout: ProjectLayout, tmp_path: Path
    ) -> None:
        publisher, _ = seeded
        outdated = make_unpublished(
            "widget",
            layout.part_path("widget").read_text(encoding="utf-8"),
            tmp_path / "old",
            consumed={"T": 6},
        )
        publisher.projections.apply_hc_state({"T": 8})
        first = publisher.publish_build(outdated, op_id="pub-stale-retry")
        second = publisher.publish_build(outdated, op_id="pub-stale-retry")
        assert first.kind == "raced"
        assert second.kind == "raced"
        assert second.result.current is False
