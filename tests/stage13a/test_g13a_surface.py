# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""G13A clauses 15 and 16: the surface a model and an operator actually meet.

* **clause 15** — ``solve_pose`` through the **real dispatcher** on both
  declared profiles, returning the solved assignment, with **no pose declared**
  as a side effect: the pose-set generation is unchanged afterwards. That last
  half is the clause, not decoration. The whole reversal ``ASSEMBLY.md`` §1 was
  spent on bought *proposing*; if a solve quietly declared its own answer, the
  authoring act would have moved from the author to the model and the diff
  would stop carrying intent.
* **clause 16** — ``heph solve pose`` in human and ``--json`` form, including
  the exit code, because a script gates on it.

The reviewer profile is asserted refused for the same reason the 8C quartet is:
the reviewer receives measurements, and a reviewer that could commission one
would be judging its own evidence.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from _g13a import ARM_PARTS, CONSTRAINTS, JOINTS, make_project
from hephaestus.agent_bridge.cad_ops import CadOps
from hephaestus.agent_bridge.dispatch import DispatchError, Principal, ToolDispatcher
from hephaestus.core.project_store.layout import load_project, open_store
from hephaestus.core.project_store.store import ProjectStore
from hephaestus.testing.tools_fixture import Project

ORCH = Principal(session_id="orch", profile="orchestrator", part=None)
PART_LINK2 = Principal(session_id="p2", profile="part", part="link2")
REVIEWER = Principal(session_id="rv", profile="reviewer", part=None)

#: The one request every clause here drives: one elbow, one declared mate.
REQUEST: dict[str, Any] = {
    "targets": [{"form": "constraint", "constraint_id": "c-align"}],
    "free_joints": ["j-elbow"],
    "tol": 1e-4,
    "weighting": "unit_scaled_v1",
    "regularization": "min_norm_from_start",
    "provenance": {"assumed": True, "reason": "the gate's own solve"},
}


def _make(root: Path) -> Project:
    """The arm cast behind the REAL dispatcher, built through the model's own tool.

    Scaffolded here rather than reusing the engine suite's session fixture: a
    dispatch clause has to drive the parts through ``build_part`` on the tool
    surface, which is a different path from the engine-side publisher the other
    file uses, and a gate assertion must not be satisfiable by a change made in
    the other one.
    """
    from hephaestus.testing.ledger import seed_minimal_ledger

    make_project(root, ARM_PARTS)
    layout = load_project(root)
    store = open_store(layout)
    cad = CadOps(layout, store)
    dispatcher = ToolDispatcher(ProjectStore(layout, store), cad=cad)
    seed_minimal_ledger(cad)
    return Project(root=root, layout=layout, store=store, cad=cad, dispatcher=dispatcher, _n=[0])


@pytest.fixture(scope="module")
def wired(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Project]:
    """Every part built through ``build_part``, joints and constraints declared."""
    project = _make(tmp_path_factory.mktemp("g13a-surface") / "proj")
    try:
        for name in ARM_PARTS:
            result = cast("dict[str, Any]", project.call("build_part", {"name": name}))
            assert result["status"] == "ok", result
        for entry in JOINTS:
            project.call("declare_joint", dict(entry))
        for entry in CONSTRAINTS:
            project.call("declare_constraint", dict(entry))
        yield project
    finally:
        project.close()


def _pose_generation(project: Project) -> int:
    read = cast("dict[str, Any]", project.call("read_poses", {}))
    return int(cast("int", read["generation"]))


# ==========================================================================
# clause 15: both profiles, and NO pose declared


@pytest.mark.parametrize("principal", [ORCH, PART_LINK2])
def test_solve_pose_dispatches_on_both_declared_profiles(
    wired: Project, principal: Principal
) -> None:
    """Clause 15: the tool really drives from a part session and the orchestrator.

    The part principal is ``link2`` and the solve moves ``link2`` through a
    joint it does not own — which is the point, and the same 8C quartet
    decision the joint tools ride: a cross-part measurement cannot be scoped to
    one part without gutting it.
    """
    result = cast("dict[str, Any]", wired.call("solve_pose", REQUEST, principal=principal))
    assert result["status"] == "ok"
    assert result["verdict"] == "pose_converged_at_tolerance"
    assignments = cast("list[Any]", result["assignments"])
    values = cast("dict[str, float]", cast("dict[str, Any]", assignments[0])["values"])
    assert values["j-elbow"] == pytest.approx(30.0, abs=1e-3)
    # The two blocks and their per-block tiers reach the model, not just the
    # engine (``SOLVER.md`` §9: a reader never has to infer which claim applies
    # to which number).
    assert cast("dict[str, Any]", result["solver_core"])["determinism_tier"] == "D1"
    assert cast("dict[str, Any]", result["verification"])["determinism_tier"] == "D2"


def test_the_reviewer_cannot_commission_a_solve(wired: Project) -> None:
    """The profile negative: a reviewer judging evidence may not order it."""
    with pytest.raises(DispatchError) as excinfo:
        wired.call("solve_pose", REQUEST, principal=REVIEWER)
    assert excinfo.value.reason == "scope_denied"


def test_a_solve_declares_no_pose_and_advances_no_generation(wired: Project) -> None:
    """Clause 15: **no pose is declared as a side effect**.

    ``SOLVER.md`` §2A: "13A does not auto-declare a pose — the solved
    assignment is returned, and ``declare_pose`` remains an explicit act."
    Asserted on the generation, because that is the thing a silent write would
    move.
    """
    before = _pose_generation(wired)
    joints_before = cast("dict[str, Any]", wired.call("read_joints", {}))["generation"]
    result = cast("dict[str, Any]", wired.call("solve_pose", REQUEST))
    assert result["verdict"] == "pose_converged_at_tolerance"
    assert _pose_generation(wired) == before
    assert cast("dict[str, Any]", wired.call("read_joints", {}))["generation"] == joints_before
    # And the record itself offers no source text and no edit to apply.
    payload = json.dumps(result)
    for absent in ("suggested_edit", "script_fragment", "patch", "source"):
        assert f'"{absent}"' not in payload, absent


def test_a_refusal_reaches_the_model_by_name_and_never_as_a_verdict(wired: Project) -> None:
    """The refusal half of the surface: a stable token, not a transport failure.

    ``invalid_solve_request`` is a machine token a model can branch on, exactly
    as ``invalid_constraint`` is — and it is not one of the seven verdict
    spellings, because a request that was never solved decided nothing.
    """
    from hephaestus.core.placement import POSE_SOLVE_VERDICTS

    bad = {**REQUEST, "weighting": "whatever_feels_right"}
    with pytest.raises(DispatchError) as excinfo:
        wired.call("solve_pose", bad)
    assert excinfo.value.reason not in POSE_SOLVE_VERDICTS
    assert "weighting" in str(excinfo.value)


# ==========================================================================
# clause 16: heph solve pose, human and --json


def _cli(root: Path, argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    """``(exit code, stdout, stderr)`` - both streams, captured exactly once.

    Draining ``readouterr`` here and returning both is not tidiness: a helper
    that consumed stdout and left the caller to fetch stderr would hand the
    caller an empty string, and a clause asserting on a refusal message would
    then pass for the wrong reason.
    """
    import os

    from hephaestus.core.cli import main

    cwd = Path.cwd()
    os.chdir(root)
    try:
        code = main(argv)
    finally:
        os.chdir(cwd)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


_ARGV = [
    "solve",
    "pose",
    "--constraint",
    "c-align",
    "--joint",
    "j-elbow",
    "--tol",
    "1e-4",
    "--weighting",
    "unit_scaled_v1",
    "--regularization",
    "min_norm_from_start",
    "--assumed",
    "--reason",
    "the gate's own solve",
]


def test_heph_solve_pose_human_form(wired: Project, capsys: pytest.CaptureFixture[str]) -> None:
    """Clause 16: the human form names the verdict and says nothing was written."""
    code, out, _err = _cli(wired.root, _ARGV, capsys)
    assert code == 0, out
    assert "verdict: pose_converged_at_tolerance" in out
    assert "j-elbow=30" in out
    assert "c-align (parallel): satisfied" in out
    assert "nothing was written" in out


def test_heph_solve_pose_json_form(wired: Project, capsys: pytest.CaptureFixture[str]) -> None:
    """Clause 16: the machine form is the whole solve record."""
    code, out, _err = _cli(wired.root, [*_ARGV, "--json"], capsys)
    assert code == 0, out
    payload = cast("dict[str, Any]", json.loads(out.strip().splitlines()[-1]))
    assert payload["status"] == "ok"
    assert payload["verdict"] == "pose_converged_at_tolerance"
    assert payload["space"] == "pose"
    assert cast("dict[str, Any]", payload["solver_core"])["determinism_tier"] == "D1"
    assert cast("dict[str, Any]", payload["verification"])["determinism_tier"] == "D2"
    assert payload["artifact_refs"], payload


def test_heph_solve_pose_exits_non_zero_on_an_outcome_that_is_not_a_pass(
    wired: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    """Clause 16: the exit code gates on an ANSWER, not on "it ran".

    ``c-flush`` closes its gap to zero with same-facing normals, so the verdict
    is ``no_pose_found_from_starts``; a CLI that exited 0 there would let a
    script treat "the gap is zero and it is still not a mate" as a pass.
    """
    argv = [
        "solve",
        "pose",
        "--constraint",
        "c-flush",
        "--joint",
        "j-lift",
        "--tol",
        "1e-4",
        "--weighting",
        "unit_scaled_v1",
        "--regularization",
        "min_norm_from_start",
        "--assumed",
        "--reason",
        "the gate's own solve",
    ]
    code, out, _err = _cli(wired.root, argv, capsys)
    assert code == 1, out
    assert "verdict: no_pose_found_from_starts" in out
    assert "c-flush (coincident): violated" in out
    assert "normal_deviation_deg" in out or "c-flush:normals" in out


def test_heph_solve_pose_refuses_a_request_without_provenance(
    wired: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    """Clause 16: provenance is compulsory at the operator surface too."""
    argv = [
        "solve",
        "pose",
        "--constraint",
        "c-align",
        "--tol",
        "1e-4",
        "--weighting",
        "unit_scaled_v1",
        "--regularization",
        "min_norm_from_start",
    ]
    code, _out, err = _cli(wired.root, argv, capsys)
    assert code == 2
    assert "provenance is compulsory" in err


def test_there_is_no_apply_verb(wired: Project) -> None:
    """The absence that carries the stage: no ``--apply``, no ``--write``.

    Asserted against the parser rather than the docs, because the docs are a
    promise and the parser is the surface. Applying a proposal stays an
    authoring act through ``declare_pose``.
    """
    del wired
    from hephaestus.core.cli import build_parser

    parser = build_parser()
    text = parser.format_help()
    assert "solve" in text
    for forbidden in ("--apply", "--write", "--declare-pose", "--writeback"):
        assert forbidden not in text, forbidden
