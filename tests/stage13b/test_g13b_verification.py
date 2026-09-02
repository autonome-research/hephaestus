# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""G13B clauses 31 and 37: why the answer is believed, and what is reproducible.

``SOLVER.md`` §7 is the mechanical reason §1's amendment is safe: **a solved
placement is never trusted because the solver said so.** It is re-measured in a
separate process whose import closure excludes :mod:`hephaestus.geom.solve`,
through the ordinary :mod:`hephaestus.core.assembly` path, and the verdict is
read from ``ConstraintResidual.satisfied`` rather than from the residual
number. If the solver's own figure and the kernel's ever disagree beyond
``VERIFY_EPS``, the whole result is refused and **no verdict is emitted**.

§9 then splits the determinism claim honestly. The tier is a property of a
BLOCK, not of a solve, and the seam is kernel-touched versus not — a seam that
runs *through* every solve. ``solver_core`` is D1 and byte-compared, but only
after the frames it is conditional on are asserted equal; ``verification`` is
unconditionally D2 and is held to §9's four bindings instead, because it is
kernel measurement and its digits are not claimed stable.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest
from _g13b import placement_request
from hephaestus.core.placement import (
    SOLVER_FAULT_ENV,
    VERIFY_EPS,
    SolveRunRefusal,
    propose_placement,
)

if TYPE_CHECKING:
    from hephaestus.core.project_store.layout import ProjectLayout

    from opstore import OpStore

TOL = 1e-4
SEATED = ("c-seat", "c-bore", "c-face", "c-square")


# ==========================================================================
# clause 31: the independent verification pass


def test_the_verification_pass_excludes_the_solver_from_its_own_import_closure(
    bench: tuple[ProjectLayout, OpStore],
) -> None:
    """Clause 31: a separate process, and the closure assertion made INSIDE it.

    The flag is computed in the child, after every import that pass needs, and
    is carried back in the record — so a solver bug cannot reach the number
    that is reported. The half this repo discovered at 13A and inherits here:
    :mod:`hephaestus.geom` must NOT re-export ``solve``, because the
    verification pass imports the package for ``evaluate_residual`` and
    ``transformed_shape``, and an eager re-export would pull the solver into
    the very closure this clause excludes — while every other test still
    passed. The omission IS the guarantee, so both halves are asserted.
    """
    layout, store = bench
    record = propose_placement(layout, store, placement_request(SEATED, tol=TOL))
    verification = cast("dict[str, Any]", record.verification)
    assert verification["import_closure_excludes_geom_solve"] is True

    # The other half, in a process of its own: importing the package alone does
    # not load the solver.
    probe = "import sys, hephaestus.geom; print('hephaestus.geom.solve' in sys.modules)"
    completed = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )
    assert completed.stdout.strip().splitlines()[-1] == "False"


def test_all_eight_kinds_are_evaluated_at_the_solution(
    bench: tuple[ProjectLayout, OpStore],
) -> None:
    """Clause 31: all eight kinds, not the four that steered.

    The plateau and pose-invariant kinds cannot carry the iteration — a solver
    that "optimised" a flat plateau silently does not work — but they are
    *measured* at whatever solution is reached and reported. Dropping them
    would let a proposal that satisfies four mates and drives two solids
    together look clean.
    """
    layout, store = bench
    record = propose_placement(layout, store, placement_request(SEATED, tol=TOL))
    verification = cast("dict[str, Any]", record.verification)
    kinds = {
        str(cast("dict[str, Any]", row)["kind"])
        for row in [
            *cast("list[Any]", verification["constraints"]),
            *cast("list[Any]", verification["collateral"]),
        ]
    }
    assert kinds == {
        "coincident",
        "concentric",
        "parallel",
        "perpendicular",
        "no_interference",
        "clearance_min",
        "distance",
        "fit",
    }


def test_every_value_is_recorded_beside_the_bound_it_was_tested_against(
    bench: tuple[ProjectLayout, OpStore],
) -> None:
    """Clause 31: the **satisfaction read** (§7.4), not a residual read.

    For each objective constraint the pass reads the whole re-measured
    ``ConstraintResidual`` — ``measured``, ``slack``, every entry of ``values``,
    and ``satisfied`` — and every class-predicate value is recorded beside its
    own declared bound, so a reader can see WHICH conjunct failed rather than
    inferring it from a number.

    This is the clause that closes the gap the disagreement check alone cannot:
    a same-facing ``coincident`` pair has a genuinely zero gap, so the solver's
    number and the kernel's agree perfectly and §7.6 passes. The only thing
    that catches it is reading the predicate the kernel already evaluated.
    """
    layout, store = bench
    record = propose_placement(layout, store, placement_request(SEATED, tol=TOL))
    rows = {
        str(cast("dict[str, Any]", row)["id"]): cast("dict[str, Any]", row)
        for row in cast("list[Any]", cast("dict[str, Any]", record.verification)["constraints"])
    }
    seat = rows["c-seat"]
    assert {"measured", "slack", "satisfied", "declared", "values", "components"} <= set(seat)
    declared = dict(cast("list[Any]", seat["declared"]))
    assert "tol_mm" in declared and "normal_eps_deg" in declared
    predicate = next(
        cast("dict[str, Any]", component)
        for component in cast("list[Any]", seat["components"])
        if cast("dict[str, Any]", component)["role"] == "class_predicate"
    )
    # The bound it was tested against, beside the value, in its own unit.
    assert predicate["bound"] == pytest.approx(float(cast("float", declared["normal_eps_deg"])))
    assert predicate["unit"] == "deg"
    assert predicate["within_bound"] is True

    bore = rows["c-bore"]
    axes = next(
        cast("dict[str, Any]", component)
        for component in cast("list[Any]", bore["components"])
        if cast("dict[str, Any]", component)["role"] == "class_predicate"
    )
    assert axes["bound"] == pytest.approx(
        float(cast("float", dict(cast("list[Any]", bore["declared"]))["axis_eps_deg"]))
    )


def test_a_solver_whose_model_has_drifted_is_refused_with_both_numbers(
    bench: tuple[ProjectLayout, OpStore],
) -> None:
    """Clause 31: fault-inject an internal residual and get ``solver_residual_disagreement``.

    Disagreement is **fatal, not a warning**. A solver whose model of the
    geometry has drifted from the kernel's is not producing evidence, and
    reporting its answer with a caveat would be exactly the overclaim this
    project's vocabulary exists to prevent — so no verdict is emitted at all,
    and the refusal carries both numbers so a reader can see the size of the
    drift rather than being told only that there was one.
    """
    layout, store = bench
    saved = os.environ.get(SOLVER_FAULT_ENV)
    os.environ[SOLVER_FAULT_ENV] = "0.5"
    try:
        with pytest.raises(SolveRunRefusal) as excinfo:
            propose_placement(layout, store, placement_request(SEATED, tol=TOL))
    finally:
        if saved is None:
            os.environ.pop(SOLVER_FAULT_ENV, None)
        else:
            os.environ[SOLVER_FAULT_ENV] = saved
    assert excinfo.value.reason == "solver_residual_disagreement"
    payload = excinfo.value.to_json()
    assert "verdict" not in payload, "a disagreement emitted a verdict"
    assert float(cast("float", payload["worst_disagreement"])) > VERIFY_EPS
    assert payload["verify_eps"] == VERIFY_EPS
    # Both numbers, per component, so the drift is legible.
    row = cast("dict[str, Any]", cast("list[Any]", payload["constraints"])[0])
    component = cast("dict[str, Any]", cast("list[Any]", row["components"])[0])
    assert component["solver"] != component["measured"]


# ==========================================================================
# clause 37: determinism, per block, with the precondition asserted first


#: One transform-space solve in a fresh interpreter, printed as canonical JSON.
#: A separate PROCESS, because the claim §9 makes is about processes and
#: anything cheaper would assert a property nobody doubted.
_CHILD = """
import json, sys
from pathlib import Path
from hephaestus.core.placement import PlacementSolveRequest, propose_placement
from hephaestus.core.project_store.constraints import ConstraintProvenance
from hephaestus.core.project_store.layout import load_project, open_store

layout = load_project(Path(sys.argv[1]))
store = open_store(layout)
record = propose_placement(
    layout,
    store,
    PlacementSolveRequest(
        constraints=("c-seat", "c-bore", "c-face", "c-square"),
        free=("lug",),
        tol=1e-4,
        weighting="unit_scaled_v1",
        regularization="min_norm_from_start",
        provenance=ConstraintProvenance(assumed=True, reason="the gate's own solve"),
    ),
)
store.close()
print(json.dumps(record.to_json(), sort_keys=True))
"""


def _run(root: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, "-c", _CHILD, str(root)], capture_output=True, text=True, check=True
    )
    return cast("dict[str, Any]", json.loads(completed.stdout.strip().splitlines()[-1]))


def _canonical(block: Any) -> str:
    """Canonical JSON minus timestamps.

    There are none to strip: ``solver_core`` deliberately carries no clock
    reading, because a block whose bytes are claimed identical across processes
    cannot contain a number that differs between them by construction. The
    filter runs anyway, and is named, so the clause reads as the spec writes it
    rather than relying on an absence a later edit could end.
    """
    if isinstance(block, dict):
        block = {
            key: value
            for key, value in cast("dict[str, Any]", block).items()
            if "timestamp" not in key and not key.endswith("_at")
        }
    return json.dumps(block, sort_keys=True, separators=(",", ":"))


def test_two_processes_agree_on_solver_core_with_the_frames_asserted_first(
    bench_root: Path,
) -> None:
    """Clause 37: frames equal, THEN ``solver_core`` byte-identical at D1.

    Frame extraction is a kernel call and is not claimed bit-stable, so two
    runs whose recorded frames differ are D2-comparable only and the byte
    comparison below would be meaningless. That is exactly why §9 puts the
    frames INSIDE the block: the D1 claim is conditional on them, and a reader
    must be able to check the condition instead of taking it on faith.
    """
    first = _run(bench_root)
    second = _run(bench_root)
    core_a = cast("dict[str, Any]", first["solver_core"])
    core_b = cast("dict[str, Any]", second["solver_core"])

    assert _canonical(core_a["frames"]) == _canonical(core_b["frames"]), (
        "the extracted frames differ, so the D1 byte claim does not apply"
    )
    assert _canonical(core_a["pivots"]) == _canonical(core_b["pivots"])
    assert core_a["determinism_tier"] == core_b["determinism_tier"] == "D1"
    assert _canonical(core_a) == _canonical(core_b)


def test_the_verification_block_is_held_to_the_four_d2_bindings(bench_root: Path) -> None:
    """Clause 37: ``verification`` is D2, and is deliberately NOT byte-compared.

    §9 explicitly does not gate the returned digits in D2 — iteration counts,
    step sizes and the digits themselves are out. What it binds are the four
    things a reader would be misled by if they moved.
    """
    first = _run(bench_root)
    second = _run(bench_root)
    tol = 1e-4

    # 1. the verdict spelling
    assert first["verdict"] == second["verdict"] == "converged_at_tolerance"

    # 2. the re-measured residuals: within tolerance, same side of it, and with
    #    identical `satisfied` flags — a run that flips `satisfied` has flipped
    #    the answer, tolerance or no tolerance.
    rows_a = _rows_by_id(first)
    rows_b = _rows_by_id(second)
    assert set(rows_a) == set(rows_b) and rows_a
    for constraint_id, row_a in rows_a.items():
        row_b = rows_b[constraint_id]
        assert row_a["satisfied"] == row_b["satisfied"]
        assert abs(float(row_a["measured"]) - float(row_b["measured"])) <= tol
        assert (float(row_a["measured"]) <= tol) == (float(row_b["measured"]) <= tol)

    # 3. the active bounds and the remaining DOF
    core_a = cast("dict[str, Any]", first["solver_core"])
    core_b = cast("dict[str, Any]", second["solver_core"])
    assert core_a["limits_active"] == core_b["limits_active"]
    assert core_a["dof_remaining"] == core_b["dof_remaining"]

    # 4. the bound input refs, so two runs are provably about the same geometry
    assert first["artifact_refs"] == second["artifact_refs"]
    assert first["artifact_refs"], first

    for record in (first, second):
        assert cast("dict[str, Any]", record["verification"])["determinism_tier"] == "D2"


def test_no_verification_block_ever_claims_the_bit_reproducible_tier(
    bench_root: Path,
) -> None:
    """Clause 37, the negative in the other direction.

    A ``verification`` block claiming D1 would be a byte-identity claim about
    digits that come out of kernel measurement, which is the one thing §9
    exists to refuse — and the gates assert in both directions.
    """
    record = _run(bench_root)
    verification = cast("dict[str, Any]", record["verification"])
    assert verification["determinism_tier"] == "D2"
    for nested in cast("list[Any]", verification.get("verified_placements") or ()):
        assert cast("dict[str, Any]", nested)["determinism_tier"] == "D2"
    assert '"D1"' not in json.dumps(verification)


def test_the_same_request_records_the_same_proposal_rather_than_a_second_one(
    bench_root: Path,
) -> None:
    """Content addressing, asserted where it is load-bearing.

    A proposal id is derived from the document's own hash, so re-running an
    identical solve records the identical proposal instead of a second one —
    which is what makes "a proposal ref is a claim about bytes" true, and what
    keeps the determinism clause above from being a claim about two different
    artifacts that happen to agree.
    """
    first = _run(bench_root)
    second = _run(bench_root)
    assert first["proposal_id"] == second["proposal_id"]
    assert first["proposal_ref"] == second["proposal_ref"]
    assert str(first["proposal_ref"]).startswith("artifact:placement-proposal:sha256:")


def _rows_by_id(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(cast("dict[str, Any]", row)["id"]): cast("dict[str, Any]", row)
        for row in cast("list[Any]", cast("dict[str, Any]", record["verification"])["constraints"])
    }


def test_the_run_trace_is_stored_beside_the_proposal_and_never_inside_it(
    bench: tuple[ProjectLayout, OpStore],
) -> None:
    """§9's last sentence, asserted: a ``solver_trace_ref`` exists and is separate.

    A trace is **evidence about a run, never about the design**. It is stored
    as its own content-addressed blob and referenced from the proposal, not
    folded into ``solver_core`` — whose byte-identity claim is about the
    ANSWER, not about how the iteration reached it. Nothing reads it to decide
    anything, and the clause asserts that too: it carries iterations and
    residual norms, and no verdict.
    """
    import json as _json

    from hephaestus.core.project_store.proposals import ProposalSet
    from hephaestus.core.project_store.store import blob_hash_of_ref

    layout, store = bench
    record = propose_placement(layout, store, placement_request(SEATED, tol=TOL))
    document = ProposalSet(layout, store).document(record.proposal_id)
    ref = str(document["solver_trace_ref"])
    assert ref.startswith("artifact:solve-trace:sha256:")
    assert "solver_trace_ref" not in cast("dict[str, Any]", record.solver_core)

    trace = cast(
        "dict[str, Any]", _json.loads(store.blobs.get(blob_hash_of_ref(ref)).decode("utf-8"))
    )
    starts = cast("list[Any]", trace["starts"])
    assert starts, trace
    first = cast("dict[str, Any]", starts[0])
    assert first["from_start"] == "as_built"
    assert first["termination"] == "tolerance"
    steps = cast("list[Any]", first["steps"])
    assert steps, "a converged run recorded no accepted step"
    assert {"iteration", "damping", "weighted_inf_norm", "cost"} == set(
        cast("dict[str, Any]", steps[0])
    )
    # Evidence about a run: no verdict anywhere in it.
    assert "verdict" not in _json.dumps(trace)
