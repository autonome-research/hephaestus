# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""Every public fixture builds; failure and fingerprint manifests hold.

- assembly/: primary + bracket build through the unsafe backend (subprocess),
  their labels/tags/metrics match hand-computed values, their own CHECKS pass
  through the facade, and checks/fit.py's cross-part clearance checks pass.
- failure_fillet/: broken.py fails at exactly the line recorded in
  fixture.json with the manifested built-through/last-good values.
- fingerprint/: variants warn / stay silent exactly as fixture.json says.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import cast

import pytest
from hephaestus.core.addressing import Resolution
from hephaestus.core.checks.engine import collect_checks, load_check_module, run_checks
from hephaestus.core.checks.facade import MappedGeometry, part_measurement, project_measurement
from hephaestus.core.executor.fingerprint import FingerprintBaseline, compare
from hephaestus.core.executor.globals_exec import execute_globals
from hephaestus.core.executor.namespace import (
    CheckRegistry,
    ParamState,
    PartOutput,
    build_namespace,
)
from hephaestus.core.executor.runner import BuildRequest, UnpublishedBuild, run_build
from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend
from hephaestus.core.executor.splitter import (
    PART_FILENAME,
    compile_statement,
    parse_module,
    split_statements,
)
from hephaestus.core.executor.tags import TagRegistry
from hephaestus.geom import AnyShape, geometry_index, labeled_nodes
from opstore.types import JSONValue

FIXTURES = Path(__file__).resolve().parents[2] / "corpus" / "public_fixtures"
ASSEMBLY = FIXTURES / "assembly"

#: Per-part build budget from the fixture brief (subprocess incl. OCP import).
BUILD_BUDGET_S = 10.0


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def build_fixture(
    part: str, script_path: Path, tmp_dir: Path, *, globals_path: Path | None = None
) -> tuple[UnpublishedBuild, float]:
    request = BuildRequest(
        part=part,
        script=read(script_path),
        globals_source=read(globals_path) if globals_path is not None else None,
    )
    started = time.monotonic()
    built = run_build(request, backend=UnsafeLocalBackend(), out_dir=tmp_dir)
    return built, time.monotonic() - started


# --- in-process execution (real shapes for facade-backed check runs) --------


class ExecutedPart:
    """A part script executed in-process: shapes + tags for facade checks."""

    def __init__(self, script: str, globals_source: str | None) -> None:
        globals_result = execute_globals(globals_source)
        param_state = ParamState(scope="part", overrides={})
        self.part = PartOutput()
        self.tag_registry = TagRegistry()
        self.namespace = build_namespace(
            param_state=param_state,
            hc=globals_result.hc_namespace(),
            part=self.part,
            tag_registry=self.tag_registry,
            check_registry=CheckRegistry(),
        )
        module = parse_module(script, filename=PART_FILENAME)
        statements = split_statements(script, filename=PART_FILENAME)
        for statement, node in zip(statements, module.body, strict=True):
            self.tag_registry.set_statement(statement.index, statement.lineno)
            code = compile_statement(node, filename=PART_FILENAME)
            exec(code, self.namespace)
            if not param_state.published and "PARAMS" in self.namespace:
                param_state.publish(self.namespace)
        param_state.finalize()
        geometry = self.part.geometry_value
        assert geometry is not None
        self.shape = cast("AnyShape", geometry)

    def source(self) -> MappedGeometry:
        nodes = labeled_nodes(self.shape)
        index = geometry_index(self.shape, tags=self.tag_registry.names())
        records = self.tag_registry.records()
        shape = self.shape

        def resolver(resolution: Resolution) -> object:
            if resolution.kind == "part":
                return shape
            if resolution.kind == "tag":
                return records[resolution.name].shape
            if resolution.kind == "label":
                picked = [nodes[i][1] for i in resolution.occurrences]
                if len(picked) == 1 and not resolution.fused:
                    return picked[0]
                fused = picked[0]
                for extra in picked[1:]:
                    fused = fused + extra
                return fused
            raise AssertionError(f"fixture resolver does not support {resolution.kind!r}")

        return MappedGeometry(index=index, resolver=resolver)


@pytest.fixture(scope="module")
def primary(tmp_path_factory: pytest.TempPathFactory) -> tuple[UnpublishedBuild, float]:
    return build_fixture(
        "primary",
        ASSEMBLY / "parts" / "primary.py",
        tmp_path_factory.mktemp("primary"),
        globals_path=ASSEMBLY / "globals.py",
    )


@pytest.fixture(scope="module")
def bracket(tmp_path_factory: pytest.TempPathFactory) -> tuple[UnpublishedBuild, float]:
    return build_fixture(
        "bracket",
        ASSEMBLY / "parts" / "bracket.py",
        tmp_path_factory.mktemp("bracket"),
        globals_path=ASSEMBLY / "globals.py",
    )


@pytest.fixture(scope="module")
def executed_primary() -> ExecutedPart:
    return ExecutedPart(read(ASSEMBLY / "parts" / "primary.py"), read(ASSEMBLY / "globals.py"))


@pytest.fixture(scope="module")
def executed_bracket() -> ExecutedPart:
    return ExecutedPart(read(ASSEMBLY / "parts" / "bracket.py"), read(ASSEMBLY / "globals.py"))


#: Hand-computed assembly values (defaults: sheet_t=6, joint_clear=0.3).
DECK_VOLUME = 180.0 * 120.0 * 6.0
POST_VOLUME = 18.0 * 18.0 * 90.0
PRIMARY_VOLUME = 2.0 * DECK_VOLUME + 4.0 * POST_VOLUME
BRACKET_VOLUME = 48.0 * 48.0 * 6.0 + 48.0 * 6.0 * 40.0 - (3.0 * 6.0 + 0.3) * 6.0 * 10.0


class TestAssemblyPrimary:
    def test_builds_ok_within_budget(self, primary: tuple[UnpublishedBuild, float]) -> None:
        built, elapsed = primary
        assert built.result.status == "ok"
        assert built.result.error is None
        assert elapsed < BUILD_BUDGET_S

    def test_metrics_match_hand_computed(self, primary: tuple[UnpublishedBuild, float]) -> None:
        metrics = primary[0].result.metrics
        assert metrics is not None
        assert metrics.solids == 6
        assert metrics.bbox_mm == pytest.approx((180.0, 120.0, 102.0), abs=1e-6)
        assert metrics.volume_mm3 == pytest.approx(PRIMARY_VOLUME, abs=1e-6)
        assert metrics.sealed is True
        assert metrics.genus == 0

    def test_duplicate_labels_dedup(self, primary: tuple[UnpublishedBuild, float]) -> None:
        labels = [entry.label for entry in primary[0].result.geometries]
        assert labels == ["bottom_deck", "top_deck", "post", "post#2", "post#3", "post#4"]
        assert all(entry.solids == 1 for entry in primary[0].result.geometries)

    def test_tags_and_checks_collected(self, primary: tuple[UnpublishedBuild, float]) -> None:
        built = primary[0]
        assert set(built.geometry_index().tags) == {"deck_top", "base_bottom"}
        assert built.check_names == (
            "deck_volume",
            "envelope",
            "posts_clear_top_deck",
            "sealed_frame",
        )

    def test_consumed_hc_projection(self, primary: tuple[UnpublishedBuild, float]) -> None:
        consumed = set(primary[0].consumed_hc)
        assert {"sheet_t", "shelf_w", "shelf_d", "post_h", "post_side", "frame_h"} <= consumed

    def test_own_checks_pass_through_facade(self, executed_primary: ExecutedPart) -> None:
        checks = collect_checks(executed_primary.namespace)
        source = executed_primary.source()
        results = run_checks(checks, lambda: part_measurement("primary", source))
        assert set(results) == set(checks)
        failures = {name: r.measured for name, r in results.items() if not r.passed}
        assert failures == {}


class TestAssemblyBracket:
    def test_builds_ok_within_budget(self, bracket: tuple[UnpublishedBuild, float]) -> None:
        built, elapsed = bracket
        assert built.result.status == "ok"
        assert elapsed < BUILD_BUDGET_S

    def test_metrics_match_hand_computed(self, bracket: tuple[UnpublishedBuild, float]) -> None:
        metrics = bracket[0].result.metrics
        assert metrics is not None
        assert metrics.solids == 1
        assert metrics.bbox_mm == pytest.approx((48.0, 48.0, 46.0), abs=1e-6)
        assert metrics.volume_mm3 == pytest.approx(BRACKET_VOLUME, abs=1e-6)
        assert metrics.sealed is True
        assert metrics.genus == 0

    def test_consumes_multiple_hc_names(self, bracket: tuple[UnpublishedBuild, float]) -> None:
        consumed = set(bracket[0].consumed_hc)
        assert {"sheet_t", "post_side", "joint_clear", "shelf_w"} <= consumed
        assert len(consumed) >= 2

    def test_tag_recorded(self, bracket: tuple[UnpublishedBuild, float]) -> None:
        assert set(bracket[0].geometry_index().tags) == {"frame_face"}
        assert "frame_face" in bracket[0].tag_fingerprints

    def test_own_checks_pass_through_facade(self, executed_bracket: ExecutedPart) -> None:
        checks = collect_checks(executed_bracket.namespace)
        source = executed_bracket.source()
        results = run_checks(checks, lambda: part_measurement("bracket", source))
        failures = {name: r.measured for name, r in results.items() if not r.passed}
        assert failures == {}


class TestCrossPartFit:
    def test_fit_checks_pass(
        self, executed_primary: ExecutedPart, executed_bracket: ExecutedPart
    ) -> None:
        checks = load_check_module(read(ASSEMBLY / "checks" / "fit.py"), filename="checks/fit.py")
        sources = {
            "primary": executed_primary.source(),
            "bracket": executed_bracket.source(),
        }
        results = run_checks(checks, lambda: project_measurement(sources))
        assert set(results) == {"bracket_clears_frame", "bracket_seats_at_joint_clearance"}
        failures = {name: r.measured for name, r in results.items() if not r.passed}
        assert failures == {}
        assert results["bracket_clears_frame"].measured == pytest.approx(0.0, abs=1e-6)
        assert results["bracket_seats_at_joint_clearance"].measured == pytest.approx(0.3, abs=0.01)


@pytest.fixture(scope="module")
def manifest() -> dict[str, JSONValue]:
    data = json.loads(read(FIXTURES / "failure_fillet" / "fixture.json"))
    assert isinstance(data, dict)
    return cast("dict[str, JSONValue]", data)


@pytest.fixture(scope="module")
def failed(
    tmp_path_factory: pytest.TempPathFactory, manifest: dict[str, JSONValue]
) -> UnpublishedBuild:
    script_rel = str(manifest["script"])
    built, _ = build_fixture(
        str(manifest["part"]),
        FIXTURES / "failure_fillet" / script_rel,
        tmp_path_factory.mktemp("failure-fillet"),
    )
    return built


class TestFailureFixtureManifest:
    def test_fails_at_manifest_line(
        self, failed: UnpublishedBuild, manifest: dict[str, JSONValue]
    ) -> None:
        assert failed.result.status == "failed"
        error = failed.result.error
        assert error is not None
        assert error.line == manifest["fail_line"]
        assert error.type == manifest["error_type"]
        marked = [line for line in error.frame if line.startswith("> ")]
        assert len(marked) == 1 and marked[0].startswith(f"> {manifest['fail_line']} | ")

    def test_built_through_matches_manifest(
        self, failed: UnpublishedBuild, manifest: dict[str, JSONValue]
    ) -> None:
        expected = cast("dict[str, JSONValue]", manifest["built_through"])
        built_through = failed.result.error and failed.result.error.built_through
        assert built_through is not None
        assert built_through.line == expected["line"]
        assert built_through.statement == expected["statement"]

    def test_last_good_matches_hand_computed_manifest(
        self, failed: UnpublishedBuild, manifest: dict[str, JSONValue]
    ) -> None:
        expected = cast("dict[str, JSONValue]", manifest["last_good"])
        error = failed.result.error
        assert error is not None
        last_good = error.last_good
        assert last_good is not None
        assert last_good.bodies == expected["bodies"]
        assert last_good.solids == expected["solids"]
        assert last_good.size_mm == pytest.approx(
            cast("list[float]", expected["size_mm"]), abs=1e-6
        )
        assert last_good.volume_mm3 == pytest.approx(
            cast("float", expected["volume_mm3"]), abs=1e-6
        )
        assert last_good.sealed == expected["sealed"]
        assert last_good.genus == expected["genus"]
        assert error.last_good_artifact_ref is not None
        assert error.last_good_artifact_ref.startswith("artifact:build-checkpoint:sha256:")


@pytest.fixture(scope="module")
def fp_manifest() -> dict[str, JSONValue]:
    data = json.loads(read(FIXTURES / "fingerprint" / "fixture.json"))
    assert isinstance(data, dict)
    return cast("dict[str, JSONValue]", data)


@pytest.fixture(scope="module")
def baseline(
    tmp_path_factory: pytest.TempPathFactory, fp_manifest: dict[str, JSONValue]
) -> tuple[FingerprintBaseline, UnpublishedBuild]:
    built, _ = build_fixture(
        "fingerprint_base",
        FIXTURES / "fingerprint" / str(fp_manifest["base"]),
        tmp_path_factory.mktemp("fp-base"),
    )
    assert built.result.status == "ok"
    artifact_ref = built.result.artifact_ref
    assert artifact_ref is not None
    return FingerprintBaseline(
        descriptors=dict(built.tag_fingerprints), artifact_ref=artifact_ref
    ), built


class TestFingerprintFixtureManifest:
    def test_base_records_manifest_tags(
        self,
        baseline: tuple[FingerprintBaseline, UnpublishedBuild],
        fp_manifest: dict[str, JSONValue],
    ) -> None:
        assert set(baseline[0].descriptors) == set(cast("list[str]", fp_manifest["tags"]))

    @pytest.mark.parametrize("variant", ["displaced.py", "refactor.py", "swapped.py"])
    def test_variant_warns_exactly_as_manifested(
        self,
        variant: str,
        baseline: tuple[FingerprintBaseline, UnpublishedBuild],
        fp_manifest: dict[str, JSONValue],
        tmp_path: Path,
    ) -> None:
        variants = cast("dict[str, JSONValue]", fp_manifest["variants"])
        spec = cast("dict[str, JSONValue]", variants[variant])
        built, _ = build_fixture(
            f"fingerprint_{variant.removesuffix('.py')}",
            FIXTURES / "fingerprint" / variant,
            tmp_path,
        )
        assert built.result.status == "ok"
        warnings = compare(dict(built.tag_fingerprints), baseline[0])
        assert {w.tag for w in warnings} == set(cast("list[str]", spec["warn"]))
        for warning in warnings:
            assert warning.kind == "tag_descriptor_changed"
            # a drift heuristic, never an identity verdict (script contract §5.3)
            assert "not an identity verdict" in warning.detail
            evidence = warning.evidence
            assert evidence is not None
            assert evidence["baseline_ref"] == baseline[0].artifact_ref

    def test_displaced_delta_measured_as_manifested(
        self,
        baseline: tuple[FingerprintBaseline, UnpublishedBuild],
        tmp_path: Path,
    ) -> None:
        built, _ = build_fixture(
            "fingerprint_displaced", FIXTURES / "fingerprint" / "displaced.py", tmp_path
        )
        warnings = compare(dict(built.tag_fingerprints), baseline[0])
        by_tag = {w.tag: w for w in warnings}
        assert set(by_tag) == {"rib_crest"}
        evidence = by_tag["rib_crest"].evidence
        assert evidence is not None
        deltas = cast("dict[str, JSONValue]", evidence["deltas"])
        centroid = cast("dict[str, JSONValue]", deltas["centroid_displacement"])
        assert centroid["measured"] == pytest.approx(2.0, abs=1e-6)
        assert centroid["threshold"] == 1.0
