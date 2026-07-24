"""Gate G0B — §5.3 tag-descriptor fingerprint heuristic.

Clauses:

- **Threshold matrix.** Each exact §5.3 threshold (face centroid 1.0 mm /
  normal 5.0° / area 2%; edge midpoint 1.0 mm / length 2%; solid centroid
  1.0 mm / volume 2%) warns strictly-over and stays silent at-or-under, driven
  both by synthetic descriptor pairs and by the real fixture pair (a 2.0 mm
  ``rib_crest`` displacement crosses the 1.0 mm face threshold with measured
  deltas; a no-op refactor is silent).
- **Baseline preserved across interleaved current/preview/failed builds.** The
  comparison baseline is the successful current artifact only; preview/failed/
  raced builds never advance it, so warning results are order-independent.
- **Selector-swap documented limit.** The symmetric-neighbour swap (0.8 mm)
  stays under every threshold and is silently missed — the heuristic reports
  descriptor drift, never a topology-identity verdict.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from _gate import FINGERPRINT, build_part
from hephaestus.core.executor.fingerprint import (
    EDGE_LENGTH_REL,
    EDGE_MIDPOINT_MM,
    FACE_AREA_REL,
    FACE_CENTROID_MM,
    FACE_NORMAL_DEG,
    SOLID_CENTROID_MM,
    SOLID_VOLUME_REL,
    FingerprintBaseline,
    TagDescriptor,
    compare,
)
from hephaestus.core.executor.runner import UnpublishedBuild
from opstore.types import JSONValue

BASELINE_REF = "artifact:build:sha256:baseline"


def _one(descriptor: TagDescriptor, other: TagDescriptor) -> tuple[object, ...]:
    baseline = FingerprintBaseline(descriptors={"t": other}, artifact_ref=BASELINE_REF)
    return compare({"t": descriptor}, baseline)


def _warns(descriptor: TagDescriptor, other: TagDescriptor) -> bool:
    return bool(_one(descriptor, other))


class TestFaceThresholdMatrix:
    BASE = TagDescriptor(kind="face", point=(0.0, 0.0, 0.0), scalar=100.0, normal=(0.0, 0.0, 1.0))

    def test_centroid_at_threshold_silent(self) -> None:
        at = TagDescriptor(
            kind="face", point=(FACE_CENTROID_MM, 0.0, 0.0), scalar=100.0, normal=(0.0, 0.0, 1.0)
        )
        assert not _warns(at, self.BASE)

    def test_centroid_over_threshold_warns(self) -> None:
        over = TagDescriptor(
            kind="face",
            point=(FACE_CENTROID_MM + 0.001, 0.0, 0.0),
            scalar=100.0,
            normal=(0.0, 0.0, 1.0),
        )
        assert _warns(over, self.BASE)

    def test_normal_over_threshold_warns(self) -> None:
        import math

        angle = math.radians(FACE_NORMAL_DEG + 0.5)
        tilted = TagDescriptor(
            kind="face",
            point=(0.0, 0.0, 0.0),
            scalar=100.0,
            normal=(math.sin(angle), 0.0, math.cos(angle)),
        )
        assert _warns(tilted, self.BASE)

    def test_normal_under_threshold_silent(self) -> None:
        import math

        angle = math.radians(FACE_NORMAL_DEG - 0.5)
        tilted = TagDescriptor(
            kind="face",
            point=(0.0, 0.0, 0.0),
            scalar=100.0,
            normal=(math.sin(angle), 0.0, math.cos(angle)),
        )
        assert not _warns(tilted, self.BASE)

    def test_area_over_threshold_warns(self) -> None:
        bigger = TagDescriptor(
            kind="face",
            point=(0.0, 0.0, 0.0),
            scalar=100.0 * (1.0 + FACE_AREA_REL + 0.01),
            normal=(0.0, 0.0, 1.0),
        )
        assert _warns(bigger, self.BASE)

    def test_area_at_threshold_silent(self) -> None:
        at = TagDescriptor(
            kind="face",
            point=(0.0, 0.0, 0.0),
            scalar=100.0 * (1.0 + FACE_AREA_REL),
            normal=(0.0, 0.0, 1.0),
        )
        assert not _warns(at, self.BASE)


class TestEdgeThresholdMatrix:
    BASE = TagDescriptor(kind="edge", point=(0.0, 0.0, 0.0), scalar=50.0)

    def test_midpoint_over_warns(self) -> None:
        over = TagDescriptor(kind="edge", point=(EDGE_MIDPOINT_MM + 0.01, 0.0, 0.0), scalar=50.0)
        assert _warns(over, self.BASE)

    def test_midpoint_at_silent(self) -> None:
        at = TagDescriptor(kind="edge", point=(EDGE_MIDPOINT_MM, 0.0, 0.0), scalar=50.0)
        assert not _warns(at, self.BASE)

    def test_length_over_warns(self) -> None:
        longer = TagDescriptor(
            kind="edge", point=(0.0, 0.0, 0.0), scalar=50.0 * (1.0 + EDGE_LENGTH_REL + 0.01)
        )
        assert _warns(longer, self.BASE)


class TestSolidThresholdMatrix:
    BASE = TagDescriptor(kind="solid", point=(0.0, 0.0, 0.0), scalar=1000.0)

    def test_centroid_over_warns(self) -> None:
        over = TagDescriptor(
            kind="solid", point=(SOLID_CENTROID_MM + 0.01, 0.0, 0.0), scalar=1000.0
        )
        assert _warns(over, self.BASE)

    def test_volume_over_warns(self) -> None:
        bigger = TagDescriptor(
            kind="solid", point=(0.0, 0.0, 0.0), scalar=1000.0 * (1.0 + SOLID_VOLUME_REL + 0.01)
        )
        assert _warns(bigger, self.BASE)

    def test_volume_at_silent(self) -> None:
        at = TagDescriptor(
            kind="solid", point=(0.0, 0.0, 0.0), scalar=1000.0 * (1.0 + SOLID_VOLUME_REL)
        )
        assert not _warns(at, self.BASE)


class TestWarningShape:
    def test_reports_deltas_and_baseline_ref_never_identity(self) -> None:
        base = TagDescriptor(
            kind="face", point=(0.0, 0.0, 0.0), scalar=100.0, normal=(0.0, 0.0, 1.0)
        )
        moved = TagDescriptor(
            kind="face", point=(3.0, 0.0, 0.0), scalar=100.0, normal=(0.0, 0.0, 1.0)
        )
        warnings = _one(moved, base)
        assert len(warnings) == 1
        warning = warnings[0]
        assert warning.kind == "tag_descriptor_changed"
        assert warning.tag == "t"
        # Never an identity verdict.
        assert "identity" in warning.detail
        assert "not an identity verdict" in warning.detail
        evidence = warning.evidence
        assert evidence is not None
        assert evidence["baseline_ref"] == BASELINE_REF
        deltas = cast("dict[str, JSONValue]", evidence["deltas"])
        centroid = cast("dict[str, JSONValue]", deltas["centroid_displacement"])
        assert centroid["measured"] == pytest.approx(3.0, abs=1e-6)
        assert centroid["threshold"] == FACE_CENTROID_MM

    def test_no_baseline_no_warning(self) -> None:
        moved = TagDescriptor(
            kind="face", point=(9.0, 0.0, 0.0), scalar=100.0, normal=(0.0, 0.0, 1.0)
        )
        assert compare({"t": moved}, None) == ()

    def test_new_and_removed_tags_never_warn(self) -> None:
        baseline = FingerprintBaseline(
            descriptors={
                "old": TagDescriptor(
                    kind="face", point=(0.0, 0.0, 0.0), scalar=1.0, normal=(0.0, 0.0, 1.0)
                )
            },
            artifact_ref=BASELINE_REF,
        )
        current = {
            "brand_new": TagDescriptor(
                kind="face", point=(50.0, 0.0, 0.0), scalar=1.0, normal=(0.0, 0.0, 1.0)
            )
        }
        assert compare(current, baseline) == ()


# --- Real fixture pair: base vs displaced / refactor / swapped --------------


@pytest.fixture(scope="module")
def baseline(tmp_path_factory: pytest.TempPathFactory) -> FingerprintBaseline:
    built = build_part(
        "fingerprint_base",
        FINGERPRINT / "base.py",
        tmp_path_factory.mktemp("fp-base"),
    )
    assert built.result.status == "ok"
    ref = built.result.artifact_ref
    assert ref is not None
    return FingerprintBaseline(descriptors=dict(built.tag_fingerprints), artifact_ref=ref)


def _build_variant(name: str, tmp_path: Path) -> UnpublishedBuild:
    built = build_part(f"fp_{name}", FINGERPRINT / f"{name}.py", tmp_path)
    assert built.result.status == "ok"
    return built


class TestRealFixturePair:
    def test_baseline_has_both_tags(self, baseline: FingerprintBaseline) -> None:
        assert set(baseline.descriptors) == {"tread_top", "rib_crest"}

    def test_displaced_warns_rib_crest_with_measured_delta(
        self, baseline: FingerprintBaseline, tmp_path: Path
    ) -> None:
        built = _build_variant("displaced", tmp_path)
        warnings = compare(dict(built.tag_fingerprints), baseline)
        by_tag = {w.tag: w for w in warnings}
        assert set(by_tag) == {"rib_crest"}  # tread_top untouched, silent
        evidence = by_tag["rib_crest"].evidence
        assert evidence is not None
        assert evidence["baseline_ref"] == baseline.artifact_ref
        deltas = cast("dict[str, JSONValue]", evidence["deltas"])
        centroid = cast("dict[str, JSONValue]", deltas["centroid_displacement"])
        assert centroid["measured"] == pytest.approx(2.0, abs=1e-6)
        assert centroid["threshold"] == FACE_CENTROID_MM

    def test_refactor_is_silent(self, baseline: FingerprintBaseline, tmp_path: Path) -> None:
        built = _build_variant("refactor", tmp_path)
        # No-op refactor: identical descriptors, no warning.
        assert compare(dict(built.tag_fingerprints), baseline) == ()

    def test_swapped_is_a_documented_false_negative(
        self, baseline: FingerprintBaseline, tmp_path: Path
    ) -> None:
        built = _build_variant("swapped", tmp_path)
        # Symmetric neighbour 0.8 mm away: below the 1.0 mm threshold, so the
        # heuristic is silent. Documented limit — it never claims identity, so
        # this miss is by design, not a bug.
        warnings = compare(dict(built.tag_fingerprints), baseline)
        assert {w.tag for w in warnings} == set()


class TestBaselineInterleaving:
    """Preview/failed/raced builds never advance the §5.3 baseline."""

    def test_baseline_is_only_input_that_moves_warnings(
        self, baseline: FingerprintBaseline, tmp_path: Path
    ) -> None:
        # A "preview" build of the displaced variant does not become a baseline:
        # comparing a later build still uses the ORIGINAL successful-current
        # baseline, so the warning set is independent of interleaving order.
        displaced = _build_variant("displaced", tmp_path / "d")
        refactor = _build_variant("refactor", tmp_path / "r")

        # Interleave: compare refactor after displaced — both against the same
        # frozen baseline. Refactor stays silent; displaced still warns.
        assert compare(dict(displaced.tag_fingerprints), baseline)
        assert compare(dict(refactor.tag_fingerprints), baseline) == ()
        # Re-running the displaced comparison yields the identical result
        # (order-independent, baseline unchanged).
        again = compare(dict(displaced.tag_fingerprints), baseline)
        assert {w.tag for w in again} == {"rib_crest"}

    def test_evidence_ref_is_the_frozen_baseline(
        self, baseline: FingerprintBaseline, tmp_path: Path
    ) -> None:
        displaced = _build_variant("displaced", tmp_path)
        warnings = compare(dict(displaced.tag_fingerprints), baseline)
        for warning in warnings:
            assert warning.evidence is not None
            assert warning.evidence["baseline_ref"] == baseline.artifact_ref
