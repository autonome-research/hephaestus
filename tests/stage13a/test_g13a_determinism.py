# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""G13A clause 13: determinism, PER BLOCK, and the negative in both directions.

``SOLVER.md`` §9. The tier is a property of a **block**, not of a solve, and
the seam is kernel-touched versus not — a seam that runs *through* every solve
rather than between 2A and 2B. So the solve record carries two blocks and each
states its own claim:

* ``solver_core`` is **D1**, byte-reproducible, for a pose iteration, which is
  kernel-free after frame extraction. The claim is **conditional on the
  extracted frames**, and the frames are recorded INSIDE the block precisely so
  a reader can check the condition instead of taking it on faith. This clause
  therefore asserts frame equality **first**, as the explicit precondition, and
  only then byte-compares.
* ``verification`` is **D2** unconditionally, in every space including this
  one, because it is kernel measurement. It is deliberately NOT byte-compared:
  it is held to §9's four bindings — identical verdict spelling, re-measured
  residuals within tolerance and on the same side of it with identical
  ``satisfied`` flags, identical ``limits_active`` and ``dof_remaining``, and
  identical bound input refs.

The negative lands in both directions: no ``verification`` block in any record
claims ``"D1"``. It lands **here**, with the first record that carries a tier,
rather than two sub-stages later.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

#: Run one solve in a fresh interpreter and print its record as canonical JSON.
#: A separate PROCESS, not a separate thread and not a second call in this one:
#: the claim §9 makes is about processes, and anything cheaper would assert a
#: property nobody doubted.
_CHILD = """
import json, sys
from pathlib import Path
from hephaestus.core.placement import (
    ConstraintTarget, PoseSolveRequest, PointTarget, solve_pose,
)
from hephaestus.core.project_store.constraints import ConstraintProvenance
from hephaestus.core.project_store.layout import load_project, open_store

layout = load_project(Path(sys.argv[1]))
store = open_store(layout)
record = solve_pose(
    layout,
    store,
    PoseSolveRequest(
        targets=(ConstraintTarget("c-align"),),
        free_joints=("j-elbow",),
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
        [sys.executable, "-c", _CHILD, str(root)],
        capture_output=True,
        text=True,
        check=True,
    )
    return cast("dict[str, Any]", json.loads(completed.stdout.strip().splitlines()[-1]))


def _canonical(block: Any) -> str:
    """Canonical JSON minus timestamps.

    There are none to strip: ``solver_core`` deliberately carries no clock
    reading, because a block whose bytes are claimed identical across processes
    cannot contain a number that differs between them by construction. The
    filter is applied anyway, and named, so the clause reads as the spec writes
    it rather than relying on an absence a later edit could end.
    """
    if isinstance(block, dict):
        block = {
            key: value
            for key, value in cast("dict[str, Any]", block).items()
            if "timestamp" not in key and not key.endswith("_at")
        }
    return json.dumps(block, sort_keys=True, separators=(",", ":"))


def test_two_processes_agree_per_block_with_the_precondition_asserted_first(
    arm_root: Path,
) -> None:
    """Clause 13: frames equal, then ``solver_core`` byte-identical at D1."""
    first = _run(arm_root)
    second = _run(arm_root)

    core_a = cast("dict[str, Any]", first["solver_core"])
    core_b = cast("dict[str, Any]", second["solver_core"])

    # -- the PRECONDITION of the D1 claim, asserted before the claim ---------
    # Frame extraction is a kernel call and is not claimed bit-stable. Two runs
    # whose recorded frames differ are D2-comparable only, so the byte
    # comparison below is meaningless without this line - which is exactly why
    # §9 puts the frames inside the block.
    assert _canonical(core_a["frames"]) == _canonical(core_b["frames"]), (
        "the extracted frames differ, so the D1 byte claim does not apply"
    )

    assert core_a["determinism_tier"] == "D1"
    assert core_b["determinism_tier"] == "D1"
    assert _canonical(core_a) == _canonical(core_b)


def test_the_verification_block_is_held_to_the_four_d2_bindings(arm_root: Path) -> None:
    """Clause 13: ``verification`` is D2, and is NOT byte-compared.

    ``SOLVER.md`` §9 explicitly does not gate the returned digits in D2 —
    iteration counts, step sizes and the digits themselves are out. What it
    binds are the four things a reader would be misled by if they moved: the
    verdict spelling, the re-measured residuals (within tolerance, on the same
    side of it, with identical ``satisfied`` flags — a run that flips
    ``satisfied`` has flipped the answer, tolerance or no tolerance), the
    active limits and remaining DOF, and the bound input refs, so two runs are
    provably about the same geometry.
    """
    first = _run(arm_root)
    second = _run(arm_root)
    tol = 1e-4

    # 1. the verdict spelling
    assert first["verdict"] == second["verdict"] == "pose_converged_at_tolerance"

    # 2. the re-measured residuals: same side of the tolerance, same `satisfied`
    rows_a = {
        str(cast("dict[str, Any]", row)["id"]): cast("dict[str, Any]", row)
        for row in cast("list[Any]", cast("dict[str, Any]", first["verification"])["constraints"])
    }
    rows_b = {
        str(cast("dict[str, Any]", row)["id"]): cast("dict[str, Any]", row)
        for row in cast("list[Any]", cast("dict[str, Any]", second["verification"])["constraints"])
    }
    assert set(rows_a) == set(rows_b) and rows_a
    for constraint_id, row_a in rows_a.items():
        row_b = rows_b[constraint_id]
        assert row_a["satisfied"] == row_b["satisfied"]
        assert abs(float(row_a["measured"]) - float(row_b["measured"])) <= tol
        assert (float(row_a["measured"]) <= tol) == (float(row_b["measured"]) <= tol)

    # 3. the active limits and the remaining DOF
    core_a = cast("dict[str, Any]", first["solver_core"])
    core_b = cast("dict[str, Any]", second["solver_core"])
    assert core_a["limits_active"] == core_b["limits_active"]
    assert core_a["dof_remaining"] == core_b["dof_remaining"]

    # 4. the bound input refs - so two runs are provably about the same geometry
    assert first["artifact_refs"] == second["artifact_refs"]
    assert first["artifact_refs"], first

    # And the tier itself.
    for record in (first, second):
        assert cast("dict[str, Any]", record["verification"])["determinism_tier"] == "D2"


def test_no_verification_block_ever_claims_the_bit_reproducible_tier(
    arm_root: Path,
) -> None:
    """Clause 13, the negative in the other direction — landed with the FIRST record.

    A ``verification`` block claiming D1 would be a byte-identity claim about
    digits that come out of kernel measurement, which is the one thing §9
    exists to refuse. Asserting it here, rather than in 13B or 13C, is the
    point: the negative lands with the first record that carries a tier.
    """
    record = _run(arm_root)
    verification = cast("dict[str, Any]", record["verification"])
    assert verification["determinism_tier"] == "D2"
    for nested in cast("list[Any]", verification.get("verified_assignments") or ()):
        assert cast("dict[str, Any]", nested)["determinism_tier"] == "D2"
    # Nothing anywhere in the verification half says D1, however nested.
    assert '"D1"' not in json.dumps(verification)
