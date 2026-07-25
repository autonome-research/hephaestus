"""Gate G2 — thread-phase clauses the Stage 2A workflow suite does not close.

``server/tests/test_workflows.py`` already proves durable replay across a restart
of both processes, cooperative cancellation, orphan interruption with
checkpoint-verified resume, the capped two-part cross-check/repair scenario, and
the multimodal bypass. Two clauses it does **not** pin down are the ones that
only bite under pressure, and they are what this file adds — both through the
real ``node agent/dist/workflows/runner.js`` process:

* **fan-out is derived from live admission capacity, not from the request.**
  The existing scenario runs against an idle store, where the requested
  concurrency is always the smaller number. Here the store is deliberately
  saturated first, so the bound the workflow actually uses must collapse to the
  capacity ``py.admission_capacity`` reported at fan-out time — strictly below
  both the requested concurrency and the number of parts.
* **the repair cap is a real cap.** When the cross-part check can never be
  repaired, the workflow must stop after exactly ``MAX_REPAIR_ROUNDS`` rounds
  with ``verified: false`` — never loop, and never report success from a
  partially repaired assembly.

Both reuse the package-local harnesses (``Wiring`` / ``RunnerHarness``) rather
than re-deriving them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
from _g2b import build_agent_dist
from hephaestus.agent_bridge.workflows import CHECKPOINTS_NAMESPACE, JOBS_NAMESPACE
from opstore.types import TerminalState
from test_workflows import (
    SHELF_INTERFERING_SRC,
    RunnerHarness,
    completing_prompter,
    request_for,
    scaffold_project,
)

#: An extra part that participates in no check — fan-out ballast.
BALLAST_SRC = """body = Pos(0.0, 0.0, {z}) * Box(8.0, 8.0, 4.0)
body.label = "ballast_body"
part.geometry = body
part.description = "Fan-out ballast"
"""

#: The declared repair cap (``agent/src/workflows/cad_workflow.ts``).
MAX_REPAIR_ROUNDS = 2


@pytest.fixture(scope="module")
def runner_main() -> Path:
    built = build_agent_dist()
    if built is None:
        pytest.skip("node/pnpm are required to run the packaged workflow runner")
    return built[1]


def four_part_project(root: Path) -> Path:
    scaffold_project(root)
    for index, name in enumerate(("gusset", "plate")):
        (root / "parts" / f"{name}.py").write_text(
            BALLAST_SRC.format(z=40.0 + 10.0 * index), encoding="utf-8"
        )
    return root


def test_workflow_fanout_collapses_to_the_live_admission_capacity(
    tmp_path: Path, runner_main: Path
) -> None:
    root = four_part_project(tmp_path / "proj")
    harness = RunnerHarness(root, runner_main, completing_prompter())
    harness.wiring.build("bracket", "shelf", "gusset", "plate")
    parts = [
        (name, f"PART {name}: build it.", f"REPAIR PART {name}: fix it.")
        for name in ("bracket", "shelf", "gusset", "plate")
    ]
    # Saturate the store: the workflow run itself takes one more slot, leaving a
    # capacity strictly below both the requested concurrency and the part count.
    held = [f"hold-{i}" for i in range(12)]
    try:
        for run_id in held:
            harness.wiring.admission.admit_run(run_id)

        run = harness.service.launch(request_for(root, parts=parts, max_concurrency=8), timeout=900)
        assert run.status == "completed", run.summary

        job = harness.service.status(run.job_id)
        assert job is not None
        result = cast("dict[str, Any]", job.result)
        fanout = [int(value) for value in cast("list[Any]", result["fanout_concurrency"])]
        sampled = harness.bridge.capacities
        assert sampled, "the workflow never probed py.admission_capacity"

        # The bound is min(requested ceiling, capacity sampled at fan-out time)…
        assert fanout[0] == min(8, sampled[0]), (fanout, sampled)
        # …and here that is the capacity, not the request or the part count.
        assert fanout[0] == sampled[0]
        assert fanout[0] < 8 and fanout[0] < len(parts)
        assert 1 <= fanout[0] <= 16 - len(held)
        # No branch ever exceeded the derived bound.
        assert all(bound <= capacity for bound, capacity in zip(fanout, sampled, strict=False))

        # All four parts were still delegated, one branch run each, in order.
        assert harness.bridge.methods.count("py.delegate") == len(parts)
        assert harness.bridge.branch_runs == [f"{run.run_id}:{name}:0" for name, _p, _r in parts]

        # The workflow's own terminal is durable and every branch slot is back.
        terminal = harness.wiring.admission.get_terminal(run.run_id)
        assert terminal is not None and terminal.state is TerminalState.COMPLETED
        assert harness.wiring.admission.active_count() == len(held)
    finally:
        harness.close()
        harness.assert_no_orphans()


def test_workflow_repair_cap_stops_without_claiming_verification(
    tmp_path: Path, runner_main: Path
) -> None:
    root = tmp_path / "proj"
    # The shelf interferes and the scripted part agent never fixes it, so the
    # cross-part check can never go green.
    scaffold_project(root, shelf=SHELF_INTERFERING_SRC)
    harness = RunnerHarness(root, runner_main, completing_prompter())
    harness.wiring.build("bracket", "shelf")
    try:
        run = harness.service.launch(
            request_for(root, max_repair_rounds=MAX_REPAIR_ROUNDS), timeout=900
        )
        # A clean halt, not a failure and not a success.
        assert run.status == "stopped", run.summary

        job = harness.service.status(run.job_id)
        assert job is not None and job.status == "COMPLETED"
        result = cast("dict[str, Any]", job.result)
        assert result["verified"] is False
        assert result["checks"]["passed"] is False
        assert result["verification"]["passed"] is False
        # Exactly the capped number of repair rounds — it never loops.
        assert result["repair_rounds"] == MAX_REPAIR_ROUNDS

        # One initial delegation per part, then one repair delegation per round,
        # attributed to the failing part only.
        rounds = [entry.split(":")[-1] for entry in harness.bridge.branch_runs]
        assert rounds == ["0", "0", "1", "2"], harness.bridge.branch_runs
        assert [entry.split(":")[1] for entry in harness.bridge.branch_runs] == [
            "bracket",
            "shelf",
            "shelf",
            "shelf",
        ]

        # Every phase still checkpointed, and the terminal is durable+released.
        keys = {record.checkpoint_key for record in harness.service.checkpoints(run.job_id)}
        assert keys == {
            "cad:decompose@1",
            "cad:delegate@1",
            "cad:cross_checks@1",
            "cad:repair@1",
            "cad:verify@1",
        }
        terminal = harness.wiring.admission.get_terminal(run.run_id)
        assert terminal is not None and terminal.state is TerminalState.COMPLETED
        assert harness.wiring.admission.active_count() == 0

        # The durable record is the honest one: a stopped run keeps its job row
        # and its unresolved verification in the replayable log.
        replay = harness.service.replay(run.job_id)
        details = " ".join(
            str(cast("dict[str, Any]", event.data).get("detail", "")) for event in replay
        )
        assert "unresolved" in details, details
        assert harness.wiring.jobs.list(JOBS_NAMESPACE)
        assert harness.wiring.jobs.list(CHECKPOINTS_NAMESPACE)
    finally:
        harness.close()
        harness.assert_no_orphans()
