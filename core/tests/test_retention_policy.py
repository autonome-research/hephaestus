"""§3.5 default protected-roots policy: current + most-recent-failure survive GC."""

from __future__ import annotations

from pathlib import Path

import pytest
from hephaestus.core.project_store.layout import ProjectLayout, open_store
from hephaestus.core.project_store.publication import Publisher, current_pointer
from hephaestus.core.project_store.retention import (
    DefaultProtectedRoots,
    last_failure_pointer,
    protected_pointer_names,
)
from hephaestus.core.project_store.store import blob_hash_of_ref
from test_project_store_helpers import DEFAULT_SCRIPT, make_project, make_unpublished

DAY_S = 86_400.0


class FakeClock:
    def __init__(self, start: float = 1_000_000.0) -> None:
        self._now = start

    def now(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


@pytest.fixture()
def layout(tmp_path: Path) -> ProjectLayout:
    return make_project(tmp_path / "proj")


class TestDefaultProtectedRoots:
    def test_pointer_names_cover_parts_and_projections(self, layout: ProjectLayout) -> None:
        names = protected_pointer_names(layout)
        assert current_pointer("widget") in names
        assert last_failure_pointer("widget") in names
        assert "project-state" in names
        assert "project-snapshot" in names
        assert "check-set" in names

    def test_unbound_policy_reports_no_roots(self, layout: ProjectLayout) -> None:
        assert DefaultProtectedRoots(layout)() == ()

    def test_current_publication_survives_gc(self, layout: ProjectLayout, tmp_path: Path) -> None:
        clock = FakeClock()
        store = open_store(layout, clock=clock)
        try:
            publisher = Publisher(layout, store)
            build = make_unpublished("widget", DEFAULT_SCRIPT, tmp_path / "o1")
            outcome = publisher.publish_build(build, op_id="pub-1")
            assert outcome.kind == "current"
            assert outcome.artifact_ref is not None
            clock.advance(45 * DAY_S)
            store.gc.collect(dry_run=False)
            assert store.blobs.has(outcome.record_blob)
            assert store.blobs.has(blob_hash_of_ref(outcome.artifact_ref))
        finally:
            store.close()

    def test_most_recent_failure_is_protected_older_failures_age_out(
        self, layout: ProjectLayout, tmp_path: Path
    ) -> None:
        clock = FakeClock()
        store = open_store(layout, clock=clock)
        try:
            publisher = Publisher(layout, store)
            first = publisher.publish_build(
                make_unpublished("widget", DEFAULT_SCRIPT, tmp_path / "f1", status="failed"),
                op_id="fail-1",
            )
            assert first.kind == "failed"
            clock.advance(1 * DAY_S)
            second = publisher.publish_build(
                make_unpublished(
                    "widget",
                    DEFAULT_SCRIPT,
                    tmp_path / "f2",
                    effective={"width": 9.0},
                    status="failed",
                ),
                op_id="fail-2",
            )
            assert second.kind == "failed"
            assert store.blobs.read_pointer(last_failure_pointer("widget")) == second.record_blob
            clock.advance(45 * DAY_S)
            store.gc.collect(dry_run=False)
            # The most recent failure record (and its linked evidence) survive;
            # the superseded failure follows normal evidence retention.
            assert store.blobs.has(second.record_blob)
            assert not store.blobs.has(first.record_blob)
        finally:
            store.close()
