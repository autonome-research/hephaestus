"""Failure semantics: every §8 error-record field, denial, bounds, unsafe refusal.

The oversized-fillet fixture fails at a KNOWN line; assertions are
structural (which information is present), never string-equality against
reference-product prose.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hephaestus.core.errors import UnsafeRefusedError
from hephaestus.core.executor.runner import (
    BuildRequest,
    UnpublishedBuild,
    run_build,
)
from hephaestus.core.executor.sandbox.base import Rlimits, SandboxSpec
from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend
from hephaestus.core.types import ErrorRecord

#: The fillet at line 5 is oversized (radius 30 on a 50x40x6 plate).
FAILING_LINE = 5
FAIL_SCRIPT = """\
_t = 6.0
shelf = Box(50, 40, _t)
slot = Box(20, 10, _t)
slotted = shelf - slot
bad = fillet(slotted.edges().filter_by(Axis.Z), radius=30)
part.geometry = bad
"""

#: Independently computed last-good metrics for `slotted` (50x40x6 minus 20x10x6).
LAST_GOOD_VOLUME = 50.0 * 40.0 * 6.0 - 20.0 * 10.0 * 6.0


def build(script: str, tmp_dir: Path) -> UnpublishedBuild:
    request = BuildRequest(part="broken", script=script)
    return run_build(request, backend=UnsafeLocalBackend(), out_dir=tmp_dir)


@pytest.fixture(scope="module")
def failed(tmp_path_factory: pytest.TempPathFactory) -> UnpublishedBuild:
    return build(FAIL_SCRIPT, tmp_path_factory.mktemp("fillet-failure"))


def error_of(build_result: UnpublishedBuild) -> ErrorRecord:
    error = build_result.result.error
    assert error is not None
    return error


class TestFilletFailureRecord:
    def test_status_failed_no_build_artifact(self, failed: UnpublishedBuild) -> None:
        result = failed.result
        assert result.status == "failed"
        assert result.artifact_ref is None
        assert not result.current
        assert result.metrics is None

    def test_line_and_col(self, failed: UnpublishedBuild) -> None:
        error = error_of(failed)
        assert error.line == FAILING_LINE
        assert isinstance(error.col, int) and error.col >= 0

    def test_exception_type(self, failed: UnpublishedBuild) -> None:
        assert error_of(failed).type == "ValueError"

    def test_message_present(self, failed: UnpublishedBuild) -> None:
        assert "fillet" in error_of(failed).message.lower()

    def test_frame_spans_failing_statement_with_marker(self, failed: UnpublishedBuild) -> None:
        frame = error_of(failed).frame
        marked = [line for line in frame if line.startswith("> ")]
        assert len(marked) == 1
        assert marked[0].startswith(f"> {FAILING_LINE} | ")
        assert "fillet" in marked[0]
        # ±2 lines of context around the failing line, clipped at EOF
        assert frame[0].startswith(f"{FAILING_LINE - 2} | ")

    def test_built_through_prior_statement(self, failed: UnpublishedBuild) -> None:
        built_through = error_of(failed).built_through
        assert built_through is not None
        assert built_through.line == 4
        assert built_through.statement == "slotted = shelf - slot"

    def test_last_good_metrics_match_independent_values(self, failed: UnpublishedBuild) -> None:
        last_good = error_of(failed).last_good
        assert last_good is not None
        assert last_good.bodies == 1
        assert last_good.solids == 1
        assert last_good.volume_mm3 == pytest.approx(LAST_GOOD_VOLUME, abs=1e-6)
        assert last_good.size_mm[0] == pytest.approx(50.0, abs=1e-6)
        assert last_good.size_mm[1] == pytest.approx(40.0, abs=1e-6)
        assert last_good.size_mm[2] == pytest.approx(6.0, abs=1e-6)
        assert last_good.sealed is True
        assert last_good.genus == 1  # through slot

    def test_last_good_artifact_ref_and_file(self, failed: UnpublishedBuild) -> None:
        error = error_of(failed)
        ref = error.last_good_artifact_ref
        assert ref is not None
        assert ref.startswith("artifact:build-checkpoint:sha256:")
        assert ref in failed.artifact_files
        assert failed.artifact_files[ref].is_file()

    def test_hint_names_inspect_replay(self, failed: UnpublishedBuild) -> None:
        assert "inspect_part" in error_of(failed).hint

    def test_checkpoints_stop_at_failure(self, failed: UnpublishedBuild) -> None:
        checkpoints = failed.worker_result["checkpoints"]
        assert isinstance(checkpoints, list)
        assert len(checkpoints) == 4  # statements before the failing fillet


class TestNamespaceDenialBuildError:
    def test_open_attempt_is_build_error(self, tmp_path: Path) -> None:
        script = "data = open('/etc/passwd').read()\npart.geometry = Box(1, 1, 1)\n"
        result = build(script, tmp_path).result
        assert result.status == "failed"
        error = result.error
        assert error is not None
        assert error.type == "SandboxDeniedError"
        assert error.line == 1

    def test_import_attempt_is_build_error(self, tmp_path: Path) -> None:
        script = "import os\npart.geometry = Box(1, 1, 1)\n"
        result = build(script, tmp_path).result
        assert result.status == "failed"
        error = result.error
        assert error is not None
        assert error.type == "SandboxDeniedError"

    def test_syntax_error_record(self, tmp_path: Path) -> None:
        script = "base = Box(10, 10, 10\npart.geometry = base\n"
        result = build(script, tmp_path).result
        assert result.status == "failed"
        error = result.error
        assert error is not None
        assert error.type == "SyntaxError"
        assert error.built_through is None
        assert error.last_good is None


class TestParamBounds:
    def test_out_of_bounds_override_fails_naming_param(self, tmp_path: Path) -> None:
        script = (
            'PARAMS = {"width": Param(40.0, min=10.0, max=100.0)}\n'
            "base = Box(p.width, 10, 5)\n"
            "part.geometry = base\n"
        )
        request = BuildRequest(part="bounded", script=script, part_overrides={"width": 500})
        result = run_build(request, backend=UnsafeLocalBackend(), out_dir=tmp_path).result
        assert result.status == "failed"
        error = result.error
        assert error is not None
        assert error.type == "ParamOutOfBoundsError"
        assert "width" in error.message
        assert error.line == 1  # the PARAMS declaration statement

    def test_params_shadowing_hc_is_error(self, tmp_path: Path) -> None:
        script = (
            'PARAMS = {"sheet_t": Param(6.0, min=3.0, max=12.0)}\n'
            "part.geometry = Box(10, 10, p.sheet_t)\n"
        )
        request = BuildRequest(
            part="shadow",
            script=script,
            globals_source='PARAMS = {"sheet_t": Param(6.0, min=3.0, max=12.0)}\n',
        )
        result = run_build(request, backend=UnsafeLocalBackend(), out_dir=tmp_path).result
        assert result.status == "failed"
        error = result.error
        assert error is not None
        assert error.type == "ValidationError"
        assert "sheet_t" in error.message


class TestUnsafeRefusal:
    def test_registry_origin_refused_before_spawn(self, tmp_path: Path) -> None:
        request = BuildRequest(
            part="reg", script="part.geometry = Box(1, 1, 1)\n", origin="registry"
        )
        with pytest.raises(UnsafeRefusedError):
            run_build(request, backend=UnsafeLocalBackend(), out_dir=tmp_path)

    def test_unparseable_payload_refused(self, tmp_path: Path) -> None:
        backend = UnsafeLocalBackend()
        spec = SandboxSpec(
            worker_cmd=("true",),
            ro_binds=(),
            rw_out_dir=tmp_path,
            rlimits=Rlimits(cpu_seconds=1, address_space_bytes=1 << 30, nproc=8),
            wall_clock_s=5.0,
        )
        with pytest.raises(UnsafeRefusedError):
            backend.execute(spec, b"\xff not json")

    def test_probe_flags_every_isolation_feature_false(self) -> None:
        report = UnsafeLocalBackend().probe()
        assert report.available
        assert report.backend == "unsafe-local"
        assert report.features["unsafe"] is True
        for feature in (
            "os_isolation",
            "filesystem_isolation",
            "network_isolation",
            "process_isolation",
        ):
            assert report.features[feature] is False

    def test_warning_printed_on_execute(
        self, tmp_path: Path, capfd: pytest.CaptureFixture[str]
    ) -> None:
        build("part.geometry = Box(1, 1, 1)\n", tmp_path)
        captured = capfd.readouterr()
        assert "WITHOUT OS sandboxing" in captured.err
