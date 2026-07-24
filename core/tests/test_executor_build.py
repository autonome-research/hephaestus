"""Golden multi-statement build through the runner + unsafe backend.

Covers: checkpoints, metrics correctness, geometry index / §8 geometries
dedup, source-map loop bindings per iteration with call sites, boolean
statement attribution, tag placements, hc consumption hashing, and
two-subprocess determinism to 1e-6.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from hephaestus.core.executor.runner import (
    BuildRequest,
    UnpublishedBuild,
    run_build,
)
from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend
from hephaestus.core.hashing import consumed_hc_hash
from opstore.types import JSONValue

GLOBALS_SOURCE = """\
PARAMS = {
    "sheet_t": Param(6.0, min=3.0, max=12.0),
}
clearance = 0.3
unused_const = 123.0
"""

GOLDEN_SCRIPT = """\
PARAMS = {
    "post_count": Param(2, min=1, max=4),
    "width": Param(60.0, min=20.0, max=120.0),
}
_t = hc.sheet_t
base = Box(p.width, 40, _t)
cutter = Box(20, 10, _t)
slotted = base - cutter
slotted.label = "slotted_base"
def make_post(x):
    post = Pos(x, 0, _t) * Box(6, 6, 12)
    return post
posts = []
for i in range(p.post_count):
    posts.append(make_post(-20 + i * 20))
tag(slotted.faces().sort_by(Axis.Z)[-1], "top_face")
part.geometry = Compound(children=[slotted, *posts])
part.description = "golden multi-statement fixture"
part.process = "cnc_router"
CHECKS = {"sealed": lambda m: m.sealed("part")}
"""

#: 60x40x6 plate minus a 20x10 through slot, plus two 6x6x12 posts.
EXPECTED_VOLUME = (60.0 * 40.0 * 6.0) - (20.0 * 10.0 * 6.0) + 2 * (6.0 * 6.0 * 12.0)
STATEMENT_COUNT = 14


def build_once(tmp_dir: Path) -> UnpublishedBuild:
    request = BuildRequest(
        part="golden",
        script=GOLDEN_SCRIPT,
        globals_source=GLOBALS_SOURCE,
        part_overrides={},
        project_overrides={},
    )
    return run_build(request, backend=UnsafeLocalBackend(), out_dir=tmp_dir)


@pytest.fixture(scope="module")
def golden(tmp_path_factory: pytest.TempPathFactory) -> UnpublishedBuild:
    return build_once(tmp_path_factory.mktemp("golden"))


@pytest.fixture(scope="module")
def golden_again(tmp_path_factory: pytest.TempPathFactory) -> UnpublishedBuild:
    return build_once(tmp_path_factory.mktemp("golden-again"))


def source_map_of(build: UnpublishedBuild) -> dict[str, JSONValue]:
    assert build.source_map is not None
    return dict(build.source_map)


class TestGoldenBuild:
    def test_status_ok_with_artifacts(self, golden: UnpublishedBuild) -> None:
        result = golden.result
        assert result.status == "ok"
        assert result.error is None
        assert not result.current  # publication is project_store's decision
        assert result.artifact_ref is not None
        assert result.artifact_ref.startswith("artifact:build:sha256:")
        assert result.source_map_ref is not None
        assert result.source_map_ref.startswith("artifact:source-map:sha256:")
        assert (golden.out_dir / "final.brep").is_file()

    def test_metrics_correct(self, golden: UnpublishedBuild) -> None:
        metrics = golden.result.metrics
        assert metrics is not None
        assert metrics.solids == 3
        assert metrics.volume_mm3 == pytest.approx(EXPECTED_VOLUME, abs=1e-6)
        assert metrics.bbox_mm[0] == pytest.approx(60.0, abs=1e-6)
        assert metrics.bbox_mm[1] == pytest.approx(40.0, abs=1e-6)
        assert metrics.sealed is True
        assert metrics.genus == 1  # the through slot

    def test_checkpoints_cover_every_statement(self, golden: UnpublishedBuild) -> None:
        checkpoints_raw = golden.worker_result["checkpoints"]
        assert isinstance(checkpoints_raw, list)
        checkpoints = [cast("dict[str, JSONValue]", c) for c in checkpoints_raw]
        assert [c["index"] for c in checkpoints] == list(range(STATEMENT_COUNT))
        by_bound: dict[str, list[str]] = {}
        for checkpoint in checkpoints:
            bound = checkpoint["bound"]
            assert isinstance(bound, list)
            index = checkpoint["index"]
            for name in bound:
                by_bound.setdefault(str(name), []).append(str(index))
        assert "base" in by_bound and "slotted" in by_bound and "posts" in by_bound

    def test_checkpoint_spans_are_exact(self, golden: UnpublishedBuild) -> None:
        checkpoints_raw = golden.worker_result["checkpoints"]
        assert isinstance(checkpoints_raw, list)
        first = cast("dict[str, JSONValue]", checkpoints_raw[0])
        assert first["span"] == [1, 0, 4, 1]  # the PARAMS dict literal

    def test_geometries_dedup_in_tree_order(self, golden: UnpublishedBuild) -> None:
        labels = [entry.label for entry in golden.result.geometries]
        assert labels == ["slotted_base", "posts", "posts#2"]
        assert all(entry.solids == 1 for entry in golden.result.geometries)

    def test_geometry_index_for_addressing(self, golden: UnpublishedBuild) -> None:
        index = golden.geometry_index()
        assert index.labels == ("slotted_base", "posts", "posts")
        assert index.bindings["posts"] == 2
        assert index.bindings["base"] == 1
        assert index.bindings["slotted"] == 1
        assert "top_face" in index.tags

    def test_params_effective_values(self, golden: UnpublishedBuild) -> None:
        assert dict(golden.result.params) == {"post_count": 2, "width": 60.0}

    def test_hc_consumption_projection(self, golden: UnpublishedBuild) -> None:
        assert dict(golden.consumed_hc) == {"sheet_t": 6.0}
        expected = consumed_hc_hash({"sheet_t": 6.0})
        assert golden.result.input_hashes.hc_dependencies == expected

    def test_check_names_collected(self, golden: UnpublishedBuild) -> None:
        assert golden.check_names == ("sealed",)
        # §6: the worker evaluates part-scope CHECKS on every build.
        assert set(golden.result.checks) == {"sealed"}
        assert golden.result.checks["sealed"].passed is True
        assert golden.result.checks["sealed"].measured is True

    def test_schema_validates(self, golden: UnpublishedBuild) -> None:
        jsonschema = pytest.importorskip("jsonschema")
        schema_path = Path(__file__).resolve().parents[1] / "schemas" / "build_result.schema.json"
        schema = cast("dict[str, JSONValue]", json.loads(schema_path.read_text()))
        jsonschema.validate(golden.result.to_json(), schema)


class TestSourceMap:
    def test_loop_bindings_recorded_per_iteration(self, golden: UnpublishedBuild) -> None:
        smap = source_map_of(golden)
        bindings = cast("dict[str, JSONValue]", smap["bindings"])
        post_events = cast("list[JSONValue]", bindings["post"])
        assert len(post_events) == 2  # one per loop iteration through make_post
        events = [cast("dict[str, JSONValue]", event) for event in post_events]
        assert [event["iteration"] for event in events] == [1, 2]
        assert all(event["line"] == 11 for event in events)  # post = ... in make_post
        assert all(event["call_site"] == 15 for event in events)  # the append call line

    def test_module_level_bindings_have_no_call_site(self, golden: UnpublishedBuild) -> None:
        smap = source_map_of(golden)
        bindings = cast("dict[str, JSONValue]", smap["bindings"])
        base_raw = cast("list[JSONValue]", bindings["base"])
        base_events = [cast("dict[str, JSONValue]", e) for e in base_raw]
        assert len(base_events) == 1
        assert base_events[0]["call_site"] is None
        assert base_events[0]["line"] == 6

    def test_boolean_attributed_to_statement(self, golden: UnpublishedBuild) -> None:
        smap = source_map_of(golden)
        booleans_raw = cast("list[JSONValue]", smap["booleans"])
        booleans = [cast("dict[str, JSONValue]", b) for b in booleans_raw]
        subtraction = [b for b in booleans if b["target"] == "slotted"]
        assert len(subtraction) == 1
        assert subtraction[0]["op"] == "-"
        operands = subtraction[0]["operands"]
        assert isinstance(operands, list)
        assert set(map(str, operands)) == {"base", "cutter"}
        assert subtraction[0]["line"] == 8

    def test_tag_placement_recorded(self, golden: UnpublishedBuild) -> None:
        smap = source_map_of(golden)
        tags = cast("dict[str, JSONValue]", smap["tags"])
        top_face = cast("dict[str, JSONValue]", tags["top_face"])
        assert top_face["kind"] == "face"
        assert top_face["solid"] == 0
        assert isinstance(top_face["topo_index"], int)
        assert top_face["line"] == 16

    def test_source_map_file_written(self, golden: UnpublishedBuild) -> None:
        assert (golden.out_dir / "source_map.json").is_file()


class TestDeterminism:
    """Same script + params across two subprocess runs: metrics identical to 1e-6."""

    def test_metrics_identical(
        self, golden: UnpublishedBuild, golden_again: UnpublishedBuild
    ) -> None:
        first = golden.result.metrics
        second = golden_again.result.metrics
        assert first is not None and second is not None
        assert first.solids == second.solids
        assert first.faces == second.faces
        assert first.genus == second.genus
        assert first.sealed == second.sealed
        assert first.volume_mm3 == pytest.approx(second.volume_mm3, abs=1e-6)
        for a, b in zip(first.bbox_mm, second.bbox_mm, strict=True):
            assert a == pytest.approx(b, abs=1e-6)

    def test_input_hashes_identical(
        self, golden: UnpublishedBuild, golden_again: UnpublishedBuild
    ) -> None:
        assert golden.result.input_hashes == golden_again.result.input_hashes
        assert golden.result.audit_hashes == golden_again.result.audit_hashes

    def test_source_map_and_fingerprints_identical(
        self, golden: UnpublishedBuild, golden_again: UnpublishedBuild
    ) -> None:
        assert golden.source_map == golden_again.source_map
        assert dict(golden.tag_fingerprints) == dict(golden_again.tag_fingerprints)
