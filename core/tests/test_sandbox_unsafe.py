"""UnsafeLocalBackend execution-contract tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import cast

from hephaestus.core.executor.runner import BuildRequest, run_build
from hephaestus.core.executor.sandbox.base import ExecOutcome, Rlimits, SandboxSpec
from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend


def test_backend_selects_python_and_uses_staging_dir_as_cwd(tmp_path: Path) -> None:
    spec = SandboxSpec(
        worker_args=(
            "-c",
            (
                "import json, pathlib, sys; "
                "pathlib.Path('artifact.txt').write_text('ok'); "
                "result = {'executable': sys.executable, 'cwd': str(pathlib.Path.cwd())}; "
                "print(json.dumps(result))"
            ),
        ),
        ro_binds=(),
        rw_out_dir=tmp_path,
        rlimits=Rlimits(cpu_seconds=5, address_space_bytes=1 << 30, nproc=8),
        wall_clock_s=10.0,
    )

    outcome = UnsafeLocalBackend().execute(spec, json.dumps({"origin": "local"}).encode())

    assert outcome.exit_code == 0, outcome.stderr.decode(errors="replace")
    result: object = json.loads(outcome.stdout)
    assert isinstance(result, dict)
    record = cast("dict[str, object]", result)
    executable = record.get("executable")
    cwd = record.get("cwd")
    assert isinstance(executable, str) and Path(executable).samefile(sys.executable)
    assert isinstance(cwd, str) and Path(cwd).samefile(tmp_path)
    assert (tmp_path / "artifact.txt").read_text() == "ok"


def test_build_job_uses_backend_neutral_worker_contract(tmp_path: Path) -> None:
    class RecordingUnsafeBackend(UnsafeLocalBackend):
        def __init__(self) -> None:
            self.invocation: tuple[SandboxSpec, bytes] | None = None

        def execute(self, spec: SandboxSpec, stdin_payload: bytes) -> ExecOutcome:
            self.invocation = (spec, stdin_payload)
            return super().execute(spec, stdin_payload)

    backend = RecordingUnsafeBackend()
    built = run_build(
        BuildRequest(part="box", script="part.geometry = Box(2, 3, 4)\n"),
        backend=backend,
        out_dir=tmp_path,
    )

    assert built.result.status == "ok"
    assert built.result.artifact_ref is not None
    assert backend.invocation is not None
    spec, payload = backend.invocation
    assert spec.worker_args == ("-m", "hephaestus.core.executor.worker")
    assert spec.ro_binds == ()
    assert spec.rw_out_dir == tmp_path
    job: object = json.loads(payload)
    assert isinstance(job, dict)
    assert cast("dict[str, object]", job).get("out_dir") == "."
    assert str(spec.rw_out_dir) not in payload.decode("utf-8")
    assert built.artifact_files
    assert all(path.is_file() for path in built.artifact_files.values())
