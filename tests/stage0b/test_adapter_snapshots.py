"""G0B adapter clause: coherent project-snapshot manifests.

Architecture §3.5: a coherent manifest atomically maps every addressed part
to a successful artifact whose consumed-``hc`` projection matches the live
values; unchanged parts may contribute artifacts from an **older** audit
revision. Mixed generations are rejected with the structured
``incoherent_project_snapshot`` error until every addressed part is coherent
again; a published manifest ref is immutable and accepted afterwards.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from _adapter_helpers import make_project, make_unpublished
from hephaestus.core.checks.engine import CheckSet, run_bundle
from hephaestus.core.project_store.layout import ProjectLayout, open_store
from hephaestus.core.project_store.projections import (
    PROJECT_SNAPSHOT_REF_PREFIX,
    SnapshotRejectedError,
)
from hephaestus.core.project_store.publication import Publisher
from opstore.types import JSONValue

from opstore import OpStore, canonical_json


@pytest.fixture
def layout(tmp_path: Path) -> ProjectLayout:
    return make_project(
        tmp_path / "proj",
        parts={
            "bracket": "part.geometry = None\n",
            "shelf": "part.geometry = None\n",
        },
    )


@pytest.fixture
def store(layout: ProjectLayout) -> Iterator[OpStore]:
    handle = open_store(layout)
    yield handle
    handle.close()


@pytest.fixture
def publisher(layout: ProjectLayout, store: OpStore) -> Publisher:
    return Publisher(layout, store)


def _publish(
    publisher: Publisher,
    layout: ProjectLayout,
    part: str,
    consumed: dict[str, JSONValue],
    out_dir: Path,
    op_id: str,
) -> str:
    build = make_unpublished(
        part,
        layout.part_path(part).read_text(encoding="utf-8"),
        out_dir,
        consumed=consumed,
    )
    outcome = publisher.publish_build(build, op_id=op_id)
    assert outcome.kind == "current", outcome.details
    assert outcome.artifact_ref is not None
    return outcome.artifact_ref


class TestCoherentManifest:
    def test_all_current_parts_assemble(
        self, publisher: Publisher, layout: ProjectLayout, tmp_path: Path
    ) -> None:
        publisher.projections.apply_hc_state({"sheet_t": 9.0})
        shelf_ref = _publish(publisher, layout, "shelf", {"sheet_t": 9.0}, tmp_path / "o1", "p1")
        bracket_ref = _publish(
            publisher, layout, "bracket", {"sheet_t": 9.0}, tmp_path / "o2", "p2"
        )
        snapshot = publisher.projections.assemble_snapshot(["shelf", "bracket"])
        assert snapshot.ref.startswith(PROJECT_SNAPSHOT_REF_PREFIX)
        parts = snapshot.manifest["parts"]
        assert isinstance(parts, dict)
        assert parts["shelf"]["artifact_ref"] == shelf_ref
        assert parts["bracket"]["artifact_ref"] == bracket_ref

    def test_older_but_projection_valid_artifact_accepted(
        self, publisher: Publisher, layout: ProjectLayout, tmp_path: Path
    ) -> None:
        publisher.projections.apply_hc_state({"sheet_t": 9.0, "clearance": 0.5})
        shelf_ref = _publish(publisher, layout, "shelf", {"sheet_t": 9.0}, tmp_path / "o1", "p1")
        old_revision = publisher.projections.state().audit_revision
        # An unrelated-name change advances the revision; shelf is untouched.
        publisher.projections.apply_hc_state({"sheet_t": 9.0, "clearance": 0.8})
        _publish(publisher, layout, "bracket", {"clearance": 0.8}, tmp_path / "o2", "p2")
        new_revision = publisher.projections.state().audit_revision
        assert new_revision > old_revision

        snapshot = publisher.projections.assemble_snapshot(["shelf", "bracket"])
        parts = snapshot.manifest["parts"]
        assert isinstance(parts, dict)
        # shelf contributes its older-audit-revision artifact — accepted
        # because its consumed projection still matches the live values.
        assert parts["shelf"]["artifact_ref"] == shelf_ref
        assert parts["shelf"]["audit_revision"] == old_revision
        assert parts["bracket"]["audit_revision"] == new_revision
        assert snapshot.manifest["audit_revision"] == new_revision

    def test_mixed_generation_rejected_until_coherent_again(
        self, publisher: Publisher, layout: ProjectLayout, tmp_path: Path
    ) -> None:
        publisher.projections.apply_hc_state({"sheet_t": 9.0})
        _publish(publisher, layout, "shelf", {"sheet_t": 9.0}, tmp_path / "o1", "p1")
        _publish(publisher, layout, "bracket", {"sheet_t": 9.0}, tmp_path / "o2", "p2")
        # The shared name changes: both consumers are now a mixed generation.
        publisher.projections.apply_hc_state({"sheet_t": 12.0})
        with pytest.raises(SnapshotRejectedError) as excinfo:
            publisher.projections.assemble_snapshot(["shelf", "bracket"])
        error = excinfo.value
        assert error.code == "incoherent_project_snapshot"
        assert {issue.part for issue in error.issues} == {"shelf", "bracket"}
        assert all(issue.kind == "stale" for issue in error.issues)

        # Rebuilding only one part is still a mixed generation.
        _publish(publisher, layout, "shelf", {"sheet_t": 12.0}, tmp_path / "o3", "p3")
        with pytest.raises(SnapshotRejectedError) as excinfo:
            publisher.projections.assemble_snapshot(["shelf", "bracket"])
        assert {issue.part for issue in excinfo.value.issues} == {"bracket"}

        # Once every addressed part is rebuilt the atomic manifest exists.
        _publish(publisher, layout, "bracket", {"sheet_t": 12.0}, tmp_path / "o4", "p4")
        snapshot = publisher.projections.assemble_snapshot(["shelf", "bracket"])
        parts = snapshot.manifest["parts"]
        assert isinstance(parts, dict)
        assert parts["shelf"]["consumed"] == {"sheet_t": 12.0}
        assert parts["bracket"]["consumed"] == {"sheet_t": 12.0}

    def test_never_built_part_is_missing(
        self, publisher: Publisher, layout: ProjectLayout, tmp_path: Path
    ) -> None:
        publisher.projections.apply_hc_state({"sheet_t": 9.0})
        _publish(publisher, layout, "shelf", {"sheet_t": 9.0}, tmp_path / "o1", "p1")
        with pytest.raises(SnapshotRejectedError) as excinfo:
            publisher.projections.assemble_snapshot(["shelf", "bracket"])
        issues = excinfo.value.issues
        assert [(issue.part, issue.kind) for issue in issues] == [("bracket", "missing")]

    def test_shared_names_carry_equal_canonical_values(
        self, publisher: Publisher, layout: ProjectLayout, tmp_path: Path
    ) -> None:
        publisher.projections.apply_hc_state({"sheet_t": 9.0})
        _publish(publisher, layout, "shelf", {"sheet_t": 9.0}, tmp_path / "o1", "p1")
        _publish(publisher, layout, "bracket", {"sheet_t": 9.0}, tmp_path / "o2", "p2")
        snapshot = publisher.projections.assemble_snapshot(["shelf", "bracket"])
        parts = snapshot.manifest["parts"]
        assert isinstance(parts, dict)
        shelf_consumed = parts["shelf"]["consumed"]
        bracket_consumed = parts["bracket"]["consumed"]
        assert isinstance(shelf_consumed, dict) and isinstance(bracket_consumed, dict)
        assert canonical_json(shelf_consumed["sheet_t"]) == canonical_json(
            bracket_consumed["sheet_t"]
        )


class TestImmutableSnapshotRef:
    def test_manifest_ref_is_content_addressed_and_immutable(
        self, publisher: Publisher, layout: ProjectLayout, store: OpStore, tmp_path: Path
    ) -> None:
        publisher.projections.apply_hc_state({"sheet_t": 9.0})
        _publish(publisher, layout, "shelf", {"sheet_t": 9.0}, tmp_path / "o1", "p1")
        _publish(publisher, layout, "bracket", {"sheet_t": 9.0}, tmp_path / "o2", "p2")
        first = publisher.projections.assemble_snapshot(["shelf", "bracket"])
        first_blob = first.ref.removeprefix(PROJECT_SNAPSHOT_REF_PREFIX)
        first_bytes = store.blobs.get(first_blob)
        assert json.loads(first_bytes.decode("utf-8")) == first.manifest

        # The world moves on: new values, new builds, a new manifest.
        publisher.projections.apply_hc_state({"sheet_t": 12.0})
        _publish(publisher, layout, "shelf", {"sheet_t": 12.0}, tmp_path / "o3", "p3")
        _publish(publisher, layout, "bracket", {"sheet_t": 12.0}, tmp_path / "o4", "p4")
        second = publisher.projections.assemble_snapshot(["shelf", "bracket"])
        assert second.ref != first.ref
        # The old immutable ref still resolves to byte-identical content.
        assert store.blobs.get(first_blob) == first_bytes

    def test_supplied_snapshot_ref_accepted_by_check_reports(
        self, publisher: Publisher, layout: ProjectLayout, store: OpStore, tmp_path: Path
    ) -> None:
        publisher.projections.apply_hc_state({"sheet_t": 9.0})
        _publish(publisher, layout, "shelf", {"sheet_t": 9.0}, tmp_path / "o1", "p1")
        _publish(publisher, layout, "bracket", {"sheet_t": 9.0}, tmp_path / "o2", "p2")
        snapshot = publisher.projections.assemble_snapshot(["shelf", "bracket"])
        # A caller holding the immutable ref runs project checks against it,
        # even after the live projection has moved on (mixed generation now).
        publisher.projections.apply_hc_state({"sheet_t": 12.0})
        (layout.checks_dir).mkdir(exist_ok=True)
        (layout.checks_dir / "fit.py").write_text(
            "CHECKS = {'trivially_true': lambda m: True}\n", encoding="utf-8"
        )
        bundle = CheckSet(layout.checks_dir, store).capture()
        report = run_bundle(bundle, {}, part="proj", project_snapshot_ref=snapshot.ref)
        assert report.project_snapshot_ref == snapshot.ref
        assert report.checks["fit:trivially_true"].passed
