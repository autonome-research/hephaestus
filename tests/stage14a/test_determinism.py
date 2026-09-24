# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""G14A clauses 9 and 10: the sandbox boundary and determinism.

Clause 9 — a registry predicate attempting file IO is denied by the sandbox:
the G6 registry-integrity clause, re-run for the new packs, through the same
worker and injected-namespace whitelist. Clause 10 — determinism: **two
processes**, each a fresh interpreter running the real DFM worker over the
same job, produce identical ``DfmEvaluation`` records including
``registry_digest``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from _g14a import (
    DFM_ROOT,
    al6061_record,
    dfm_index,
    mill_fixture,
    mill_pack,
    requires_bwrap,
    run_in_process,
    worker_job,
)
from hephaestus.core.dfm.runner import DfmRequest, evaluate_pack, parse_evaluation
from hephaestus.core.executor.sandbox.bwrap import BwrapBackend
from hephaestus.core.registry import DfmPack, load_pack, load_registry
from opstore.types import JSONValue

# -- clause 9: predicate file IO is denied -----------------------------------


def _hostile_fork(tmp_path: Path, process: str) -> DfmPack:
    """A fork of a *shipped* machining pack with one file-reading rule added,
    so the denial is asserted for the new packs, not a synthetic one."""
    fork = tmp_path / process
    shutil.copytree(DFM_ROOT / process, fork)
    (fork / "reads_a_file.py").write_text(
        'def evaluate(ctx):\n    ctx.report(open("/etc/passwd").read()[:20])\n',
        encoding="utf-8",
    )
    manifest = fork / "pack.toml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8")
        + f'\n[[rules]]\nid = "{process}.reads_a_file"\ntitle = "hostile"\n'
        'predicate = "reads_a_file.py"\nreads = ["tool_diameter_mm"]\n',
        encoding="utf-8",
    )
    return load_pack(fork)


@pytest.mark.parametrize("process", ["cnc_mill", "cnc_router"])
def test_a_predicate_reaching_for_the_filesystem_is_denied(tmp_path: Path, process: str) -> None:
    from _g14a import brep_bytes
    from build123d import Box

    pack = _hostile_fork(tmp_path / "pack", process)
    outcomes = run_in_process(pack, brep_bytes(Box(30, 20, 10)), tmp_path)
    denied = outcomes[f"{process}.reads_a_file"]
    assert denied.status == "error"
    assert denied.error is not None
    assert "SandboxDeniedError" in denied.error
    assert "'open'" in denied.error
    assert not denied.findings
    # One hostile rule never hides the shipped rules: every other rule still ran.
    assert set(outcomes) == set(pack.rule_ids())


@requires_bwrap
@pytest.mark.parametrize("process", ["cnc_mill", "cnc_router"])
def test_the_denial_holds_under_the_secure_sandbox_too(tmp_path: Path, process: str) -> None:
    from _g14a import brep_bytes
    from build123d import Box

    pack = _hostile_fork(tmp_path / "pack", process)
    request = DfmRequest(
        part="block",
        process=process,
        brep=brep_bytes(Box(30, 20, 10)),
        source_artifact_ref="artifact:build:sha256:block",
    )
    evaluation = evaluate_pack(request, pack, backend=BwrapBackend(), scratch_root=tmp_path)
    denied = next(o for o in evaluation.outcomes if o.rule_id == f"{process}.reads_a_file")
    assert denied.error is not None and "SandboxDeniedError" in denied.error
    assert not denied.findings


# -- clause 10: two processes, identical evaluations -------------------------


def _worker_record(job: dict[str, JSONValue]) -> bytes:
    """Run the real DFM worker in a FRESH interpreter; return its stdout."""
    completed = subprocess.run(
        [sys.executable, "-m", "hephaestus.core.dfm.worker"],
        input=json.dumps(job).encode("utf-8"),
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", "replace")[-2000:]
    return completed.stdout


@pytest.mark.parametrize("process", ["cnc_mill", "cnc_router"])
def test_two_processes_produce_identical_evaluations_including_the_digest(
    tmp_path: Path, process: str
) -> None:
    """The same fixture, the same pack, two separate interpreters: the typed
    ``DfmEvaluation`` records are equal field for field, and both carry the
    bundled registry's own Merkle digest."""
    registry = load_registry(DFM_ROOT)
    pack = dfm_index().get(process)
    brep = mill_fixture()
    request = DfmRequest(
        part="block",
        process=process,
        brep=brep,
        source_artifact_ref="artifact:build:sha256:g14a-determinism",
        metadata={"material_spec": "6061 aluminium plate", "stock_form": "plate"},
        material=al6061_record(),
    )
    records: list[dict[str, JSONValue]] = []
    for run in ("a", "b"):
        job = worker_job(
            pack,
            brep,
            tmp_path / run,
            part=request.part,
            artifact_ref=request.source_artifact_ref,
            metadata=dict(request.metadata),
            material=al6061_record(),
        )
        evaluation = parse_evaluation(_worker_record(job), request=request, pack=pack)
        assert evaluation.registry_digest == registry.digest
        assert evaluation.registry_digest.startswith("sha256:")
        records.append(evaluation.to_json())
    assert records[0] == records[1], "two worker processes disagree on the same job"
    pack_block = records[0]["pack"]
    assert isinstance(pack_block, dict)
    assert pack_block["registry_digest"] == registry.digest


@requires_bwrap
def test_the_sandboxed_path_is_deterministic_too(tmp_path: Path) -> None:
    request = DfmRequest(
        part="block",
        process="cnc_mill",
        brep=mill_fixture(),
        source_artifact_ref="artifact:build:sha256:g14a-determinism",
        metadata={"material_spec": "6061 aluminium plate", "stock_form": "plate"},
        material=al6061_record(),
    )
    first = evaluate_pack(request, mill_pack(), backend=BwrapBackend(), scratch_root=tmp_path)
    second = evaluate_pack(request, mill_pack(), backend=BwrapBackend(), scratch_root=tmp_path)
    assert first.to_json() == second.to_json()
    assert first.registry_digest == load_registry(DFM_ROOT).digest
