"""§5.3 tag-descriptor fingerprints: exact threshold matrix and baseline rules."""

from __future__ import annotations

import math
from pathlib import Path

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
    descriptors_from_json,
    descriptors_to_json,
    rel_delta,
)

BASE_REF = "artifact:build:sha256:" + "0" * 64

FACE = TagDescriptor(kind="face", point=(0.0, 0.0, 10.0), scalar=100.0, normal=(0.0, 0.0, 1.0))
EDGE = TagDescriptor(kind="edge", point=(5.0, 0.0, 0.0), scalar=20.0)
SOLID = TagDescriptor(kind="solid", point=(0.0, 0.0, 0.0), scalar=1000.0)


def baseline(**tags: TagDescriptor) -> FingerprintBaseline:
    return FingerprintBaseline(descriptors=dict(tags), artifact_ref=BASE_REF)


def moved(descriptor: TagDescriptor, dz: float) -> TagDescriptor:
    x, y, z = descriptor.point
    return TagDescriptor(
        kind=descriptor.kind,
        point=(x, y, z + dz),
        scalar=descriptor.scalar,
        normal=descriptor.normal,
    )


def scaled(descriptor: TagDescriptor, factor: float) -> TagDescriptor:
    return TagDescriptor(
        kind=descriptor.kind,
        point=descriptor.point,
        scalar=descriptor.scalar * factor,
        normal=descriptor.normal,
    )


def tilted(descriptor: TagDescriptor, degrees: float) -> TagDescriptor:
    rad = math.radians(degrees)
    return TagDescriptor(
        kind=descriptor.kind,
        point=descriptor.point,
        scalar=descriptor.scalar,
        normal=(math.sin(rad), 0.0, math.cos(rad)),
    )


class TestRelDelta:
    def test_formula(self) -> None:
        assert rel_delta(102.0, 100.0) == 0.02
        assert rel_delta(98.0, 100.0) == 0.02

    def test_zero_old_guard(self) -> None:
        assert rel_delta(1e-6, 0.0) == 1e-6 / 1e-9


class TestFaceThresholds:
    def test_centroid_over_warns_alone(self) -> None:
        warnings = compare({"t": moved(FACE, FACE_CENTROID_MM * 1.001)}, baseline(t=FACE))
        assert len(warnings) == 1
        assert warnings[0].kind == "tag_descriptor_changed"
        assert warnings[0].tag == "t"

    def test_centroid_epsilon_below_silent(self) -> None:
        assert compare({"t": moved(FACE, FACE_CENTROID_MM * 0.999)}, baseline(t=FACE)) == ()

    def test_centroid_exactly_at_threshold_silent(self) -> None:
        assert compare({"t": moved(FACE, FACE_CENTROID_MM)}, baseline(t=FACE)) == ()

    def test_normal_over_warns_alone(self) -> None:
        warnings = compare({"t": tilted(FACE, FACE_NORMAL_DEG + 0.1)}, baseline(t=FACE))
        assert len(warnings) == 1

    def test_normal_epsilon_below_silent(self) -> None:
        assert compare({"t": tilted(FACE, FACE_NORMAL_DEG - 0.1)}, baseline(t=FACE)) == ()

    def test_area_over_warns_alone(self) -> None:
        warnings = compare({"t": scaled(FACE, 1 + FACE_AREA_REL * 1.05)}, baseline(t=FACE))
        assert len(warnings) == 1

    def test_area_epsilon_below_silent(self) -> None:
        assert compare({"t": scaled(FACE, 1 + FACE_AREA_REL * 0.95)}, baseline(t=FACE)) == ()


class TestEdgeThresholds:
    def test_midpoint_over_warns(self) -> None:
        warnings = compare({"e": moved(EDGE, EDGE_MIDPOINT_MM * 1.001)}, baseline(e=EDGE))
        assert len(warnings) == 1

    def test_midpoint_below_silent(self) -> None:
        assert compare({"e": moved(EDGE, EDGE_MIDPOINT_MM * 0.999)}, baseline(e=EDGE)) == ()

    def test_length_over_warns(self) -> None:
        warnings = compare({"e": scaled(EDGE, 1 + EDGE_LENGTH_REL * 1.05)}, baseline(e=EDGE))
        assert len(warnings) == 1

    def test_length_below_silent(self) -> None:
        assert compare({"e": scaled(EDGE, 1 + EDGE_LENGTH_REL * 0.95)}, baseline(e=EDGE)) == ()


class TestSolidThresholds:
    def test_centroid_over_warns(self) -> None:
        warnings = compare({"s": moved(SOLID, SOLID_CENTROID_MM * 1.001)}, baseline(s=SOLID))
        assert len(warnings) == 1

    def test_volume_over_warns(self) -> None:
        warnings = compare({"s": scaled(SOLID, 1 + SOLID_VOLUME_REL * 1.05)}, baseline(s=SOLID))
        assert len(warnings) == 1

    def test_volume_below_silent(self) -> None:
        assert compare({"s": scaled(SOLID, 1 + SOLID_VOLUME_REL * 0.95)}, baseline(s=SOLID)) == ()


class TestBaselineRules:
    def test_no_baseline_no_warning(self) -> None:
        assert compare({"t": moved(FACE, 50.0)}, None) == ()

    def test_identical_descriptors_silent(self) -> None:
        assert compare({"t": FACE, "e": EDGE, "s": SOLID}, baseline(t=FACE, e=EDGE, s=SOLID)) == ()

    def test_new_tag_never_warns(self) -> None:
        assert compare({"brand_new": moved(FACE, 50.0)}, baseline(t=FACE)) == ()

    def test_removed_tag_never_warns(self) -> None:
        assert compare({}, baseline(t=FACE)) == ()

    def test_warning_carries_baseline_ref_and_deltas(self) -> None:
        warnings = compare({"t": moved(FACE, 2.0)}, baseline(t=FACE))
        evidence = warnings[0].evidence
        assert evidence is not None
        assert evidence["baseline_ref"] == BASE_REF
        deltas = evidence["deltas"]
        assert isinstance(deltas, dict)
        assert "centroid_displacement" in deltas

    def test_warning_never_claims_identity(self) -> None:
        warnings = compare({"t": moved(FACE, 2.0)}, baseline(t=FACE))
        detail = warnings[0].detail
        assert "identity verdict" in detail  # explicit heuristic disclaimer
        assert "identity changed" not in detail

    def test_kind_change_warns_without_identity_claim(self) -> None:
        warnings = compare({"t": EDGE}, baseline(t=FACE))
        assert len(warnings) == 1
        assert warnings[0].kind == "tag_descriptor_changed"
        assert "identity changed" not in warnings[0].detail


class TestSerialization:
    def test_round_trip(self) -> None:
        descriptors = {"t": FACE, "e": EDGE, "s": SOLID}
        rebuilt = descriptors_from_json(descriptors_to_json(descriptors))
        assert rebuilt == descriptors

    def test_face_normal_serialized(self) -> None:
        data = descriptors_to_json({"t": FACE})
        entry = data["t"]
        assert isinstance(entry, dict)
        assert entry["normal"] == [0.0, 0.0, 1.0]


TAGGED_SCRIPT = """\
_h = {height}
plate = Box(40, 30, _h)  {comment}
tag(plate.faces().sort_by(Axis.Z)[-1], "tread_top")
part.geometry = plate
"""


def descriptors_of(script: str, tmp_path: Path) -> dict[str, TagDescriptor]:
    """Build in-process (worker code path, no subprocess) and fingerprint tags."""
    from hephaestus.core.executor.worker import execute_job

    result = execute_job(
        {
            "part": "fp",
            "script": script,
            "globals_source": None,
            "part_overrides": {},
            "project_overrides": {},
            "out_dir": str(tmp_path),
        }
    )
    assert result["status"] == "ok"
    fingerprints = result["tag_fingerprints"]
    assert isinstance(fingerprints, dict)
    return descriptors_from_json(fingerprints)


class TestEndToEnd:
    def test_noop_refactor_does_not_warn(self, tmp_path: Path) -> None:
        original = TAGGED_SCRIPT.format(height=6.0, comment="")
        refactor = TAGGED_SCRIPT.format(height=6.0, comment="# manufacturing note")
        base = descriptors_of(original, tmp_path / "a")
        current = descriptors_of(refactor, tmp_path / "b")
        assert compare(current, FingerprintBaseline(base, BASE_REF)) == ()

    def test_threshold_crossing_displacement_warns_with_evidence(self, tmp_path: Path) -> None:
        original = TAGGED_SCRIPT.format(height=6.0, comment="")
        thicker = TAGGED_SCRIPT.format(height=10.0, comment="")  # top face rises 2 mm
        base = descriptors_of(original, tmp_path / "a")
        current = descriptors_of(thicker, tmp_path / "b")
        warnings = compare(current, FingerprintBaseline(base, BASE_REF))
        assert len(warnings) == 1
        warning = warnings[0]
        assert warning.kind == "tag_descriptor_changed"
        assert warning.tag == "tread_top"
        assert warning.evidence is not None
        assert warning.evidence["baseline_ref"] == BASE_REF
        assert "identity changed" not in warning.detail
