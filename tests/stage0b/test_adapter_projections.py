"""G0B adapter clause: selective consumed-``hc`` dependency projections.

Architecture §3.5: project/global changes increment an audit revision and
recompute dependency projections; **only** parts whose consumed names/values
changed become stale — an edit to an unconsumed name invalidates nobody.
Stale markers are cleared exclusively by a successful current publication.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from _adapter_helpers import make_project, make_unpublished
from hephaestus.core.project_store.layout import ProjectLayout, open_store
from hephaestus.core.project_store.publication import Publisher
from opstore.types import JSONValue

from opstore import OpStore


@pytest.fixture
def layout(tmp_path: Path) -> ProjectLayout:
    return make_project(
        tmp_path / "proj",
        parts={
            "bracket": "part.geometry = None  # consumes clearance\n",
            "shelf": "part.geometry = None  # consumes sheet_t\n",
            "standalone": "part.geometry = None  # consumes nothing\n",
        },
    )


@pytest.fixture
def publisher(layout: ProjectLayout, tmp_path: Path) -> Iterator[Publisher]:
    store: OpStore = open_store(layout)
    yield Publisher(layout, store)
    store.close()


def _publish(
    publisher: Publisher,
    layout: ProjectLayout,
    part: str,
    consumed: dict[str, JSONValue],
    out_dir: Path,
    op_id: str,
) -> None:
    build = make_unpublished(
        part,
        layout.part_path(part).read_text(encoding="utf-8"),
        out_dir,
        consumed=consumed,
    )
    outcome = publisher.publish_build(build, op_id=op_id)
    assert outcome.kind == "current", outcome.details


@pytest.fixture
def seeded(publisher: Publisher, layout: ProjectLayout, tmp_path: Path) -> Publisher:
    """Three parts current: two consumers of distinct names, one non-consumer."""
    publisher.projections.apply_hc_state({"sheet_t": 9.0, "clearance": 0.5, "unused": 1})
    _publish(publisher, layout, "shelf", {"sheet_t": 9.0}, tmp_path / "o1", "seed-shelf")
    _publish(publisher, layout, "bracket", {"clearance": 0.5}, tmp_path / "o2", "seed-bracket")
    _publish(publisher, layout, "standalone", {}, tmp_path / "o3", "seed-standalone")
    assert publisher.projections.state().stale == {}
    return publisher


class TestSelectiveStaleness:
    def test_changed_name_marks_exactly_its_consumers_stale(self, seeded: Publisher) -> None:
        before = seeded.projections.state().audit_revision
        report = seeded.projections.apply_hc_state({"sheet_t": 12.0, "clearance": 0.5, "unused": 1})
        assert report.audit_revision == before + 1
        assert report.stale == ("shelf",)
        assert dict(report.changed) == {"shelf": ("sheet_t",)}
        state = seeded.projections.state()
        assert set(state.stale) == {"shelf"}
        assert "sheet_t" in state.stale["shelf"]

    def test_unconsumed_name_change_invalidates_nobody(self, seeded: Publisher) -> None:
        before = seeded.projections.state().audit_revision
        report = seeded.projections.apply_hc_state({"sheet_t": 9.0, "clearance": 0.5, "unused": 2})
        # The audit revision advances, but no consumer is invalidated.
        assert report.audit_revision == before + 1
        assert report.stale == ()
        assert seeded.projections.state().stale == {}

    def test_removed_consumed_name_marks_its_consumer_stale(self, seeded: Publisher) -> None:
        report = seeded.projections.apply_hc_state({"sheet_t": 9.0, "unused": 1})
        assert report.stale == ("bracket",)
        assert dict(report.changed) == {"bracket": ("clearance",)}

    def test_identical_reapply_marks_nothing(self, seeded: Publisher) -> None:
        report = seeded.projections.apply_hc_state({"sheet_t": 9.0, "clearance": 0.5, "unused": 1})
        assert report.stale == ()
        assert seeded.projections.state().stale == {}

    def test_multiple_changed_names_reported_per_consumer(
        self, publisher: Publisher, layout: ProjectLayout, tmp_path: Path
    ) -> None:
        publisher.projections.apply_hc_state({"a": 1, "b": 2})
        _publish(publisher, layout, "shelf", {"a": 1, "b": 2}, tmp_path / "o", "seed")
        report = publisher.projections.apply_hc_state({"a": 10, "b": 20})
        assert dict(report.changed) == {"shelf": ("a", "b")}

    def test_canonical_value_comparison_distinguishes_int_from_float(
        self, publisher: Publisher, layout: ProjectLayout, tmp_path: Path
    ) -> None:
        # Canonical-JSON comparison (the same rule the hashes use): 5 != 5.0.
        publisher.projections.apply_hc_state({"n": 5})
        _publish(publisher, layout, "shelf", {"n": 5}, tmp_path / "o", "seed")
        report = publisher.projections.apply_hc_state({"n": 5.0})
        assert report.stale == ("shelf",)


class TestStaleLifecycle:
    def test_only_current_publication_clears_stale(
        self, seeded: Publisher, layout: ProjectLayout, tmp_path: Path
    ) -> None:
        seeded.projections.apply_hc_state({"sheet_t": 12.0, "clearance": 0.5, "unused": 1})
        assert set(seeded.projections.state().stale) == {"shelf"}
        # A failed rebuild does not clear the marker...
        failed = make_unpublished(
            "shelf",
            layout.part_path("shelf").read_text(encoding="utf-8"),
            tmp_path / "fail",
            consumed={"sheet_t": 12.0},
            status="failed",
        )
        outcome = seeded.publish_build(failed, op_id="rebuild-failed")
        assert outcome.kind == "failed"
        assert set(seeded.projections.state().stale) == {"shelf"}
        # ...a successful current rebuild against the new values does.
        _publish(seeded, layout, "shelf", {"sheet_t": 12.0}, tmp_path / "ok", "rebuild-ok")
        assert seeded.projections.state().stale == {}
        projection = seeded.projections.state().projections["shelf"]
        assert projection.consumed == {"sheet_t": 12.0}

    def test_projection_records_artifact_and_revision(self, seeded: Publisher) -> None:
        state = seeded.projections.state()
        for part in ("shelf", "bracket", "standalone"):
            projection = state.projections[part]
            assert projection.part == part
            assert projection.artifact_ref.startswith("artifact:build:sha256:")
            assert projection.audit_revision <= state.audit_revision

    def test_unauthorized_record_current_is_refused(self, seeded: Publisher) -> None:
        # Clearing stale state is publication-only: without the project-config
        # and part locks held the adapter refuses outright.
        with pytest.raises(AssertionError, match="locks"):
            seeded.projections.record_current(
                "shelf", consumed={"sheet_t": 9.0}, artifact_ref="artifact:build:sha256:" + "0" * 64
            )
