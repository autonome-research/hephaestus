"""Gate G0B — build determinism across separate worker processes.

Same script + params => metrics identical to 1e-6 and identical input hashes
(script/hc/part-param/effective-param/toolchain). Each ``run_build`` launches
the worker in its own subprocess, so two builds are genuinely separate
processes (mission_plan: "two builds ⇒ identical metrics"). Determinism is
asserted for a parameterised part (primary, consuming hc), a standalone part
(broken's last-good geometry), and under an explicit in-bounds override (the
effective-param hash must still be stable).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _gate import ASSEMBLY, FAILURE_FILLET, build_part
from hephaestus.core.executor.runner import UnpublishedBuild
from hephaestus.core.types import Metrics


def _metrics_tuple(metrics: Metrics) -> tuple[float, ...]:
    return (
        float(metrics.solids),
        float(metrics.faces),
        *metrics.bbox_mm,
        metrics.volume_mm3,
        float(metrics.genus),
        float(metrics.edges or 0),
        metrics.area_mm2 or 0.0,
    )


def _two_builds(
    tmp_path: Path,
    part: str,
    script_dir: Path,
    *,
    globals_path: Path | None = None,
    part_overrides: dict[str, int | float | str] | None = None,
) -> tuple[UnpublishedBuild, UnpublishedBuild]:
    first = build_part(
        part,
        script_dir / "parts" / f"{part}.py",
        tmp_path / "a",
        globals_path=globals_path,
        part_overrides=part_overrides,
    )
    second = build_part(
        part,
        script_dir / "parts" / f"{part}.py",
        tmp_path / "b",
        globals_path=globals_path,
        part_overrides=part_overrides,
    )
    return first, second


class TestPrimaryDeterminism:
    @staticmethod
    @pytest.fixture(scope="class")
    def pair(
        tmp_path_factory: pytest.TempPathFactory,
    ) -> tuple[UnpublishedBuild, UnpublishedBuild]:
        return _two_builds(
            tmp_path_factory.mktemp("det-primary"),
            "primary",
            ASSEMBLY,
            globals_path=ASSEMBLY / "globals.py",
        )

    def test_both_ok(self, pair: tuple[UnpublishedBuild, UnpublishedBuild]) -> None:
        assert pair[0].result.status == "ok"
        assert pair[1].result.status == "ok"

    def test_metrics_identical_to_1e6(
        self, pair: tuple[UnpublishedBuild, UnpublishedBuild]
    ) -> None:
        m0, m1 = pair[0].result.metrics, pair[1].result.metrics
        assert m0 is not None and m1 is not None
        assert _metrics_tuple(m0) == pytest.approx(_metrics_tuple(m1), abs=1e-6)
        assert m0.solids == m1.solids
        assert m0.faces == m1.faces
        assert m0.sealed == m1.sealed
        assert m0.genus == m1.genus

    def test_input_hashes_identical(self, pair: tuple[UnpublishedBuild, UnpublishedBuild]) -> None:
        h0 = pair[0].result.input_hashes
        h1 = pair[1].result.input_hashes
        assert h0.script == h1.script
        assert h0.hc_dependencies == h1.hc_dependencies
        assert h0.part_params == h1.part_params
        assert h0.effective_params == h1.effective_params
        assert h0.toolchain == h1.toolchain
        assert h0.to_json() == h1.to_json()

    def test_audit_hashes_identical(self, pair: tuple[UnpublishedBuild, UnpublishedBuild]) -> None:
        assert pair[0].result.audit_hashes.to_json() == pair[1].result.audit_hashes.to_json()

    def test_consumed_hc_identical(self, pair: tuple[UnpublishedBuild, UnpublishedBuild]) -> None:
        assert dict(pair[0].consumed_hc) == dict(pair[1].consumed_hc)

    def test_tag_fingerprints_identical(
        self, pair: tuple[UnpublishedBuild, UnpublishedBuild]
    ) -> None:
        a = {k: v.to_json() for k, v in pair[0].tag_fingerprints.items()}
        b = {k: v.to_json() for k, v in pair[1].tag_fingerprints.items()}
        assert a == b

    def test_geometries_identical(self, pair: tuple[UnpublishedBuild, UnpublishedBuild]) -> None:
        assert [g.to_json() for g in pair[0].result.geometries] == [
            g.to_json() for g in pair[1].result.geometries
        ]

    def test_artifact_ref_identical(self, pair: tuple[UnpublishedBuild, UnpublishedBuild]) -> None:
        # Content-addressed BRep: byte-identical geometry => identical ref.
        assert pair[0].result.artifact_ref == pair[1].result.artifact_ref


class TestOverrideDeterminism:
    def test_effective_param_hash_stable_under_override(self, tmp_path: Path) -> None:
        a, b = _two_builds(
            tmp_path,
            "primary",
            ASSEMBLY,
            globals_path=ASSEMBLY / "globals.py",
            part_overrides={"post_inset": 22},
        )
        assert a.result.status == "ok" and b.result.status == "ok"
        assert a.result.input_hashes.effective_params == b.result.input_hashes.effective_params
        assert a.result.params == b.result.params
        m0, m1 = a.result.metrics, b.result.metrics
        assert m0 is not None and m1 is not None
        assert m0.volume_mm3 == pytest.approx(m1.volume_mm3, abs=1e-6)


class TestFailedBuildDeterminism:
    def test_last_good_metrics_and_refs_identical(self, tmp_path: Path) -> None:
        a, b = _two_builds(tmp_path, "broken", FAILURE_FILLET)
        assert a.result.status == "failed" and b.result.status == "failed"
        ea, eb = a.result.error, b.result.error
        assert ea is not None and eb is not None
        assert ea.line == eb.line and ea.col == eb.col and ea.type == eb.type
        assert ea.last_good is not None and eb.last_good is not None
        assert ea.last_good.to_json() == eb.last_good.to_json()
        # Deterministic geometry => deterministic last-good checkpoint ref.
        assert ea.last_good_artifact_ref == eb.last_good_artifact_ref
        assert a.result.input_hashes.script == b.result.input_hashes.script
        assert a.result.input_hashes.toolchain == b.result.input_hashes.toolchain
