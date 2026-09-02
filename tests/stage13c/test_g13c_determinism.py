# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""G13C clause 50: D2 in **both** blocks, and the four bindings that survive.

``SOLVER.md`` §9 makes the determinism tier a property of a BLOCK and puts the
seam at *kernel-touched versus not*. A 2C iteration is kernel-touched by
construction — each iterate is a preview build, and OCP output is not claimed
bit-stable across environments — so a 2C ``solver_core`` is **D2** like every
``verification`` block in every space. Neither claims byte identity of any
digit, and this suite asserts that in both directions: it compares the four
things §9 says ARE reproducible, and it asserts that no 2C block of either kind
claims D1.

Two processes, because the claim is about processes. Anything cheaper would
assert a property nobody doubted.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import pytest
from _g13c import SOLVE_TOL

#: One parameter-space solve in a fresh interpreter, printed as canonical JSON.
#: It takes the unsafe backend for the same reason every fixture does — the
#: sandbox probe is not what this clause is about — while the VERIFICATION pass
#: inside it builds its own probed secure backend and takes nothing from here.
_CHILD = f"""
import json, sys
from pathlib import Path
from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend
from hephaestus.core.placement import PlacementSolveRequest, propose_placement
from hephaestus.core.project_store.constraints import ConstraintProvenance
from hephaestus.core.project_store.layout import load_project, open_store

layout = load_project(Path(sys.argv[1]))
store = open_store(layout)
record = propose_placement(
    layout,
    store,
    PlacementSolveRequest(
        constraints=("c-seat", "c-lift"),
        free=("hc.shelf_z", "post.post_h"),
        tol={SOLVE_TOL!r},
        weighting="unit_scaled_v1",
        regularization="min_norm_from_start",
        provenance=ConstraintProvenance(assumed=True, reason="the gate's own solve"),
        space="parameters",
    ),
    backend=UnsafeLocalBackend(),
)
store.close()
print(json.dumps(record.to_json(), sort_keys=True))
"""


def _run(root: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, "-c", _CHILD, str(root)], capture_output=True, text=True, check=True
    )
    return cast("dict[str, Any]", json.loads(completed.stdout.strip().splitlines()[-1]))


@pytest.fixture(scope="module")
def two_processes(bench_root: Path, tmp_path_factory: pytest.TempPathFactory) -> Any:
    """The same solve, run twice, in two fresh interpreters.

    Each gets its OWN byte copy of the project. A proposal is a generational
    write, so two runs sharing one store would be comparing a first solve
    against a second solve of a project that had moved — which is a different
    claim from the one §9 makes.
    """
    import shutil

    first_root = tmp_path_factory.mktemp("g13c-det-a") / "proj"
    second_root = tmp_path_factory.mktemp("g13c-det-b") / "proj"
    shutil.copytree(bench_root, first_root)
    shutil.copytree(bench_root, second_root)
    return _run(first_root), _run(second_root)


def _rows_by_id(record: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    verification = cast("Mapping[str, Any]", record["verification"])
    return {
        str(cast("Mapping[str, Any]", row)["id"]): cast("Mapping[str, Any]", row)
        for row in cast("list[Any]", verification["constraints"])
    }


def test_both_blocks_of_a_2c_record_carry_D2(two_processes: Any) -> None:
    """The tier is per BLOCK, and in this space both blocks are the same one."""
    first, second = two_processes
    for record in (first, second):
        assert cast("Mapping[str, Any]", record["solver_core"])["determinism_tier"] == "D2"
        assert cast("Mapping[str, Any]", record["verification"])["determinism_tier"] == "D2"


def test_no_2c_block_of_either_kind_claims_D1(two_processes: Any) -> None:
    """Asserted in both directions, which is what §9 asks for.

    No ``verification`` block ever claims D1, in any space, because it is
    kernel measurement. No 2C ``solver_core`` does either, because each of its
    iterates is a preview build. A block that claimed D1 here would be
    promising byte-identical digits out of the boolean kernel, which is the one
    thing §9 exists to refuse.
    """
    first, second = two_processes
    for record in (first, second):
        blocks = [record["solver_core"], record["verification"]]
        for entry in cast("list[Any]", record["verification"].get("verified_placements") or []):
            blocks.append(entry)
        for block in blocks:
            assert cast("Mapping[str, Any]", block).get("determinism_tier") != "D1"


def test_binding_1_the_verdict_spelling_is_identical(two_processes: Any) -> None:
    """§9's D2 binding (1): the answer's NAME does not move between processes."""
    first, second = two_processes
    assert first["verdict"] == second["verdict"] == "converged_at_tolerance"
    assert first["space"] == second["space"] == "parameters"


def test_binding_2_the_remeasured_residuals_agree_within_tolerance(two_processes: Any) -> None:
    """§9's D2 binding (2): within tolerance, on the same side of it, same flags.

    The last clause is the one that has teeth: a run that flips ``satisfied``
    has flipped the answer, tolerance or no tolerance, and no amount of
    agreement in the digits would make that acceptable.
    """
    first, second = two_processes
    rows_a, rows_b = _rows_by_id(first), _rows_by_id(second)
    assert set(rows_a) == set(rows_b) == {"c-seat", "c-lift"}
    for constraint_id, row_a in rows_a.items():
        row_b = rows_b[constraint_id]
        assert row_a["satisfied"] == row_b["satisfied"], constraint_id
        assert (
            abs(float(cast("float", row_a["measured"])) - float(cast("float", row_b["measured"])))
            <= SOLVE_TOL
        ), constraint_id
        assert (float(cast("float", row_a["slack"])) >= 0.0) == (
            float(cast("float", row_b["slack"])) >= 0.0
        ), f"{constraint_id}: the two runs are on opposite sides of the declared bound"


def test_binding_3_the_active_bounds_and_dof_remaining_are_identical(
    two_processes: Any,
) -> None:
    """§9's D2 binding (3): the SET of active bounds/limits, and ``dof_remaining``.

    These are facts about which constraints and bounds are binding at the
    answer — a structural claim, not a numeric one — so they are compared
    exactly while the digits beside them are not compared at all.
    """
    first, second = two_processes
    core_a = cast("Mapping[str, Any]", first["solver_core"])
    core_b = cast("Mapping[str, Any]", second["solver_core"])
    assert core_a["limits_active"] == core_b["limits_active"]
    assert core_a["dof_remaining"] == core_b["dof_remaining"]
    assert core_a["rank"] == core_b["rank"]
    place_a = cast("Mapping[str, Any]", cast("list[Any]", first["placements"])[0])
    place_b = cast("Mapping[str, Any]", cast("list[Any]", second["placements"])[0])
    assert place_a["bounds_active"] == place_b["bounds_active"]
    assert place_a["dof_remaining"] == place_b["dof_remaining"]


def test_binding_4_the_bound_input_refs_are_identical(two_processes: Any) -> None:
    """§9's D2 binding (4): two runs are provably about the same geometry.

    Without this the other three are claims about two different designs. The
    refs bound here are the parts' CURRENT artifact refs — not the preview
    refs a 2C solve measured on, which necessarily differ per run and are
    reported separately for exactly that reason.
    """
    first, second = two_processes
    assert first["artifact_refs"] == second["artifact_refs"]
    assert set(first["artifact_refs"]) == {"post", "shelf"}
    for ref in cast("Mapping[str, str]", first["artifact_refs"]).values():
        assert ref.startswith("artifact:build:sha256:")


def test_the_clause_asserts_no_digit_equality_anywhere(two_processes: Any) -> None:
    """Stated as an assertion rather than left as an absence in the file.

    §9 is explicit that iteration counts, step sizes and the returned digits
    themselves are **not** gated in D2, and a suite that happened to compare
    them and happened to pass would be making a claim the spec refuses. So the
    two records are asserted to be *permitted* to differ: the comparison above
    would still hold if they did.
    """
    first, second = two_processes
    core_a = cast("Mapping[str, Any]", first["solver_core"])
    core_b = cast("Mapping[str, Any]", second["solver_core"])
    # Nothing here asserts equality of x, of the residual norms, of the
    # iteration count or of the build count. What is asserted is that the
    # comparison this suite makes does not depend on them: each is present,
    # each is a number, and none of them appears in a binding above.
    for block in (core_a, core_b):
        assert isinstance(block["x"], list)
        assert isinstance(block["iterations"], int)
        assert isinstance(block["weighted_inf_norm"], float)
        assert isinstance(block["builds_issued"], int)
    # The needles are ASSEMBLED rather than written out, because a literal
    # spelling of the forbidden text would appear in this file — as the needle
    # — and the clause would fail on its own statement of what it forbids. The
    # halves below are each harmless; only their concatenation is the assertion
    # §9 refuses.
    lhs, rhs, digits, count = "core_a[", "core_b[", '"x"]', '"iterations"]'
    forbidden = (
        f"{lhs}{digits} == {rhs}{digits}",
        f"{lhs}{count} == {rhs}{count}",
        f"{count} == {rhs}",
    )
    source = Path(__file__).read_text(encoding="utf-8")
    for needle in forbidden:
        assert needle not in source, (
            "a digit-equality assertion crept into the D2 clause; §9 does not gate it"
        )


def test_the_verification_pass_excluded_the_solver_from_its_import_closure(
    two_processes: Any,
) -> None:
    """§7.1 holds in 2C too, where the pass also BUILDS.

    The parameter-space verification branch imports the executor and the
    publisher so it can rebuild candidates. That is a wider closure than the
    other spaces', which makes the exclusion worth re-asserting here rather
    than inheriting: a solver bug still cannot reach the number reported.
    """
    first, second = two_processes
    for record in (first, second):
        verification = cast("Mapping[str, Any]", record["verification"])
        assert verification["import_closure_excludes_geom_solve"] is True
