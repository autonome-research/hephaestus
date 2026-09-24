# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""G14C clauses 13 and 16: bounded execution and reproducibility.

Clause 13 is the ``COMPARE.md`` §5 gate-addendum shape applied to the removal
simulation: a fault-injected slow boolean under a short ceiling returns the
named ``cam_sim_timeout`` refusal CARRYING the moves already simulated,
naming the lost halves, with the cheap facts present — and the subprocess is
provably dead afterwards, by pid.

Clause 16 is the §4.4/§8 reproducibility posture: two FRESH interpreters give
identical move lists, sample grids and simulation records; the golden's
provenance sidecar names the (container image, OCCT version) pair and is
asserted against the running one — the golden binds only where its sidecar
matches, exactly as render goldens bind to their rasterizer.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from _g14c import check_kwargs, declare_drill_setup
from hephaestus.core.cam_check import check_setup, simulation_provenance
from hephaestus.core.project_store.cam import CamState

HERE = Path(__file__).resolve().parent
GOLDEN = HERE / "goldens" / "simulation.json"
SIDECAR = HERE / "goldens" / "simulation.sidecar.json"


# -- clause 13: cam_sim_timeout with partial facts and a dead subprocess ----


def test_a_slow_boolean_is_cam_sim_timeout_with_the_cheap_facts_and_a_dead_child(
    bench_copy: tuple[Any, Any], tmp_path: Path
) -> None:
    layout, store = bench_copy
    declare_drill_setup(CamState(layout, store))
    pid_file = tmp_path / "child.pid"
    status = check_setup(
        layout,
        store,
        "s-op1",
        **check_kwargs(),
        timeout_s=10.0,
        fault={"slow_boolean_s": 120, "pid_file": str(pid_file)},
    )
    refusal = next(r for r in status.refusals if r["reason"] == "cam_sim_timeout")
    # The moves already simulated: the per-op progress streamed BEFORE the
    # boolean, so a ceiling kill costs the boolean, never the evidence.
    assert refusal["ops_simulated"] == [{"op": "op-drill", "samples": 37, "moves": 3}]
    assert refusal["moves_simulated"] == 3
    # Which halves were lost, by name.
    assert refusal["lost"] == ["removal_boolean", "surface_sampling"]
    assert refusal["timeout_s"] == 10.0
    assert "HEPHAESTUS_CAM_SIM_TIMEOUT_S" in str(refusal["message"])
    # The cheap facts are present — on the refusal AND as the record's own
    # coverage/round-trip halves (§5.8: computed first, streamed first).
    assert refusal["cheap"]["coverage"] == "covered"
    assert refusal["cheap"]["round_trip"] == "round_trip_identical"
    assert status.coverage is not None and status.round_trip is not None
    assert status.simulation is None
    # And the subprocess is dead afterwards: the pid it wrote no longer exists.
    pid = int(pid_file.read_text(encoding="utf-8"))
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


# -- clause 16: two processes, one record; the sidecar names the world ------


def _run_document(root: Path) -> str:
    completed = subprocess.run(
        [sys.executable, str(HERE / "_g14c_run.py"), str(root)],
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", "replace")[-2000:]
    return completed.stdout.decode("utf-8")


def test_two_processes_give_identical_moves_grids_and_simulation_records(
    ref_root: Path,
) -> None:
    first = _run_document(ref_root)
    second = _run_document(ref_root)
    assert first == second, "two fresh interpreters disagree on the same setup"
    document = json.loads(first)
    assert document["moves"] > 0 and len(document["grid"]) > 0
    assert document["simulation"]["verdict"] == "matches_at_samples"


def test_the_goldens_sidecar_names_the_image_and_occt_and_matches_or_pins(
    ref_root: Path,
) -> None:
    """The golden binds to a (container image, OCCT version) pair (§8): its
    sidecar is asserted against the running provenance, and where the running
    world is a different pair the comparison is SKIPPED naming the pinned
    condition — never silently passed, never fabricated."""
    sidecar = json.loads(SIDECAR.read_text(encoding="utf-8"))
    running = simulation_provenance()
    assert set(sidecar) == {"container_image", "occt_version"}
    if sidecar != running:
        pytest.skip(
            f"simulation golden is pinned to {sidecar} and this run is {running}; "
            "the golden binds only inside its pinned image (CAM.md §8)"
        )
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    fresh = json.loads(_run_document(ref_root))["simulation"]
    assert fresh == golden, "the pinned-image simulation record drifted from its golden"
