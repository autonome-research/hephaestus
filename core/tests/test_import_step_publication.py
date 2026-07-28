"""Imported files as build inputs: freeze, revalidation, staleness, drift.

``INGEST.md`` §1 makes an imported STEP file *content-addressed build input*:
``input_hashes.imports`` records it, a changed file fails current-pointer
revalidation, its consumers go stale, and a lost-response retry replays the
ORIGINAL bytes exactly as it does for the frozen script text. §5.3 drift
fingerprints are the ONLY warning when a replacement moves a tagged face, so
they are load-bearing here rather than optional — both halves are asserted: it
warns on a moved face and stays silent on identical bytes.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from hephaestus.core.executor.fingerprint import FingerprintBaseline
from hephaestus.core.executor.runner import BuildRequest, UnpublishedBuild, run_build
from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend
from hephaestus.core.project_store.layout import ProjectLayout, open_store
from hephaestus.core.project_store.publication import FrozenBuildInputs, Publisher
from test_project_store_helpers import make_project

from opstore import OpStore, sha256_bytes

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "step"
PLATE = FIXTURES / "plate.step"
PLATE_TALLER = FIXTURES / "plate_taller.step"
BOSS = FIXTURES / "boss.step"

PART = "bracket"
SCRIPT = (
    'base = import_step("plate.step")\n'
    'tag(base.faces().sort_by(Axis.Z)[-1], "plate_top")\n'
    "part.geometry = base\n"
)


@pytest.fixture
def layout(tmp_path: Path) -> ProjectLayout:
    root = tmp_path / "proj"
    project = make_project(root, parts={PART: SCRIPT})
    imports = root / "imports"
    imports.mkdir()
    shutil.copy(PLATE, imports / "plate.step")
    return project


@pytest.fixture
def opstore(layout: ProjectLayout) -> Iterator[OpStore]:
    store = open_store(layout)
    yield store
    store.close()


@pytest.fixture
def publisher(layout: ProjectLayout, opstore: OpStore) -> Publisher:
    return Publisher(layout, opstore)


def run(
    inputs: FrozenBuildInputs,
    out_dir: Path,
    *,
    baseline: FingerprintBaseline | None = None,
) -> UnpublishedBuild:
    """One build straight from frozen inputs (the CLI's own request shape)."""
    request = BuildRequest(
        part=inputs.part,
        script=inputs.script,
        globals_source=inputs.globals_source,
        imports=dict(inputs.imports),
        import_errors=dict(inputs.import_errors),
    )
    return run_build(request, backend=UnsafeLocalBackend(), out_dir=out_dir, baseline=baseline)


def replace_import(layout: ProjectLayout, source: Path) -> None:
    shutil.copy(source, layout.imports_dir / "plate.step")


class TestFreeze:
    def test_freezes_declared_import_bytes_and_refs(self, publisher: Publisher) -> None:
        frozen = publisher.freeze_inputs(PART)
        assert frozen.imports == {"plate.step": PLATE.read_bytes()}
        assert frozen.import_errors == {}
        assert frozen.import_refs["plate.step"].endswith(sha256_bytes(PLATE.read_bytes()))
        assert publisher.locks.held() == ()

    def test_freezes_only_what_the_script_declares(
        self, layout: ProjectLayout, publisher: Publisher
    ) -> None:
        shutil.copy(BOSS, layout.imports_dir / "boss.step")
        assert set(publisher.freeze_inputs(PART).imports) == {"plate.step"}

    def test_a_missing_import_is_recorded_not_raised(
        self, layout: ProjectLayout, publisher: Publisher
    ) -> None:
        (layout.imports_dir / "plate.step").unlink()
        frozen = publisher.freeze_inputs(PART)
        assert frozen.imports == {}
        assert "does not exist" in frozen.import_errors["plate.step"]

    def test_a_traversing_import_is_recorded_not_raised(
        self, layout: ProjectLayout, publisher: Publisher
    ) -> None:
        layout.part_path(PART).write_text(
            'part.geometry = import_step("../parts/bracket.py")\n', encoding="utf-8"
        )
        frozen = publisher.freeze_inputs(PART)
        assert frozen.imports == {}
        assert "traverse" in frozen.import_errors["../parts/bracket.py"]

    def test_frozen_bytes_survive_a_replacement_on_disk(
        self, layout: ProjectLayout, publisher: Publisher, tmp_path: Path
    ) -> None:
        """A retry replays the ORIGINAL bytes, not whatever is on disk now."""
        frozen = publisher.freeze_inputs(PART)
        replace_import(layout, PLATE_TALLER)
        built = run(frozen, tmp_path / "out")
        assert built.result.status == "ok", built.result.error
        metrics = built.result.metrics
        assert metrics is not None
        # 5 mm, the frozen plate — not the 8 mm replacement now on disk.
        assert metrics.bbox_mm[2] == pytest.approx(5.0, abs=1e-6)
        assert built.result.input_hashes.imports == {"plate.step": sha256_bytes(PLATE.read_bytes())}


class TestRevalidation:
    def test_publication_records_the_import_hashes(
        self, publisher: Publisher, tmp_path: Path
    ) -> None:
        outcome = publisher.publish_build(
            run(publisher.freeze_inputs(PART), tmp_path / "out"), op_id="pub-1"
        )
        assert outcome.kind == "current"
        assert outcome.result.input_hashes.imports == {
            "plate.step": sha256_bytes(PLATE.read_bytes())
        }
        projection = publisher.projections.state().projections[PART]
        assert projection.imports == {"plate.step": sha256_bytes(PLATE.read_bytes())}

    def test_a_replaced_file_refuses_the_current_flip(
        self, layout: ProjectLayout, publisher: Publisher, tmp_path: Path
    ) -> None:
        frozen = publisher.freeze_inputs(PART)
        built = run(frozen, tmp_path / "out")
        replace_import(layout, PLATE_TALLER)
        outcome = publisher.publish_build(built, op_id="pub-raced")
        assert outcome.kind == "raced"
        assert any(detail.startswith("imports[plate.step]") for detail in outcome.details)
        assert publisher.current_result(PART) is None

    def test_a_deleted_file_refuses_the_current_flip(
        self, layout: ProjectLayout, publisher: Publisher, tmp_path: Path
    ) -> None:
        built = run(publisher.freeze_inputs(PART), tmp_path / "out")
        (layout.imports_dir / "plate.step").unlink()
        outcome = publisher.publish_build(built, op_id="pub-raced-gone")
        assert outcome.kind == "raced"
        assert any("unreadable" in detail for detail in outcome.details)

    def test_retry_of_a_published_build_replays(self, publisher: Publisher, tmp_path: Path) -> None:
        built = run(publisher.freeze_inputs(PART), tmp_path / "out")
        first = publisher.publish_build(built, op_id="pub-retry")
        again = publisher.publish_build(built, op_id="pub-retry")
        assert first.kind == "current"
        assert again.kind == "current"
        assert again.replayed
        assert again.record_blob == first.record_blob


class TestStaleness:
    def test_a_replaced_import_marks_its_consumer_stale(
        self, layout: ProjectLayout, publisher: Publisher, tmp_path: Path
    ) -> None:
        publisher.publish_build(run(publisher.freeze_inputs(PART), tmp_path / "out"), op_id="pub-1")
        assert publisher.sync_import_state() is None  # unchanged tree: no revision bump
        assert publisher.projections.state().stale == {}

        replace_import(layout, PLATE_TALLER)
        report = publisher.sync_import_state()
        assert report is not None
        assert report.stale == (PART,)
        stale = publisher.projections.state().stale
        assert PART in stale
        assert "plate.step" in stale[PART]

    def test_an_unimported_file_invalidates_nobody(
        self, layout: ProjectLayout, publisher: Publisher, tmp_path: Path
    ) -> None:
        publisher.publish_build(run(publisher.freeze_inputs(PART), tmp_path / "out"), op_id="pub-1")
        publisher.sync_import_state()
        shutil.copy(BOSS, layout.imports_dir / "boss.step")
        report = publisher.sync_import_state()
        assert report is not None
        assert report.stale == ()
        assert publisher.projections.state().stale == {}

    def test_rebuilding_clears_the_stale_marker(
        self, layout: ProjectLayout, publisher: Publisher, tmp_path: Path
    ) -> None:
        publisher.publish_build(run(publisher.freeze_inputs(PART), tmp_path / "out"), op_id="pub-1")
        replace_import(layout, PLATE_TALLER)
        publisher.sync_import_state()
        assert PART in publisher.projections.state().stale
        outcome = publisher.publish_build(
            run(publisher.freeze_inputs(PART), tmp_path / "out2"), op_id="pub-2"
        )
        assert outcome.kind == "current"
        assert publisher.projections.state().stale == {}


class TestDriftAcrossReimports:
    """§5.3 fingerprints are the only warning that a replacement moved a face."""

    def test_a_moved_tagged_face_warns_with_the_baseline(
        self, layout: ProjectLayout, publisher: Publisher, tmp_path: Path
    ) -> None:
        first = publisher.publish_build(
            run(publisher.freeze_inputs(PART), tmp_path / "out"), op_id="pub-1"
        )
        assert first.kind == "current"
        replace_import(layout, PLATE_TALLER)
        publisher.sync_import_state()
        baseline = publisher.baseline_for(PART)
        assert baseline is not None
        rebuilt = run(publisher.freeze_inputs(PART), tmp_path / "out2", baseline=baseline)
        assert rebuilt.result.status == "ok", rebuilt.result.error
        drift = [w for w in rebuilt.result.warnings if w.kind == "tag_descriptor_changed"]
        assert [w.tag for w in drift] == ["plate_top"]
        assert drift[0].detail

    def test_an_identical_reimport_is_silent(
        self, layout: ProjectLayout, publisher: Publisher, tmp_path: Path
    ) -> None:
        publisher.publish_build(run(publisher.freeze_inputs(PART), tmp_path / "out"), op_id="pub-1")
        # Re-copy the very same fixture: identical bytes, identical geometry.
        replace_import(layout, PLATE)
        baseline = publisher.baseline_for(PART)
        rebuilt = run(publisher.freeze_inputs(PART), tmp_path / "out2", baseline=baseline)
        assert rebuilt.result.status == "ok", rebuilt.result.error
        assert [w.kind for w in rebuilt.result.warnings] == []
