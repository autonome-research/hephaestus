# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""G9B: the reviewer motion surface (``KINEMATICS.md`` §6, ``VALIDATION.md`` §5).

The ladder-integration gate clause, on the Stage 8C reviewer-test precedent
(FakeModel harness): *reviewer context carrying ``MotionStatus``, worst-sample
numeric facts, and posed-scene renders, with each non-success verdict producing
a blocking finding by rule*.

The reviewer here is a FakeModel that passes confidently on everything it is
shown — including the motion-check ids themselves. That is the adversarial case
the §5 amendment was written for: the blocking finding has to come from the
engine's own sampled measurement, so no amount of agreement between the agent
and the reviewer can talk a colliding sweep (or a never-evaluated one) closed.

Everything runs against real published artifacts — the ``_g9b`` mechanism cast
authored through the real tool dispatcher's ``build_part`` — so the numeric
facts asserted (0.1 mm pin/bore air, the -90 deg paddle-on-stop hit, the reach
miss) are the fixture's pinned mechanism facts measured through the whole
engine path, not mocks. Each blocking clause withdraws its own entry afterwards
(a new generation, nothing erased) so the clauses stay independent claims over
one built mechanism rather than re-paying four executor builds per test.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any, cast

import hephaestus.core.motion as motion_module
import pytest
from _g9b import (
    NOMINAL_RADIAL_AIR_MM,
    REACH_MISS_AT_SMALL_ANGLES_MM,
    REACH_TARGET_MM,
    SWEEP_PARTS,
    assumed,
)
from _sweep_children import grinding_child
from hephaestus.agent_bridge.cad_ops import CadOps
from hephaestus.agent_bridge.dispatch import ToolDispatcher
from hephaestus.agent_bridge.review import (
    REVIEW_VIEWS,
    ReviewerResponse,
    ReviewReport,
    ReviewRequest,
    TerminalReport,
    TerminationReviewService,
)
from hephaestus.core.motion import MOTION_TIMEOUT_ENV
from hephaestus.core.project_store.layout import load_project, open_store
from hephaestus.core.project_store.store import ProjectStore
from hephaestus.testing.ledger import seed_minimal_ledger
from hephaestus.testing.tools_fixture import Project


def make_mechanism_project(root: Path) -> Project:
    """The ``_g9b`` cast behind a real dispatcher (the ``_g8c`` factory rule).

    Scaffolded here rather than through another suite's fixture so a gate
    assertion cannot be satisfied by a change to someone else's parts. The
    minimal ledger is seeded because ``VALIDATION.md`` §2 refuses ``build_part``
    without one — a precondition of these clauses, never their subject.
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / "parts").mkdir(exist_ok=True)
    (root / "checks").mkdir(exist_ok=True)
    (root / "hephaestus.toml").write_text('[project]\nname = "mechanism"\n', encoding="utf-8")
    for name, src in SWEEP_PARTS.items():
        (root / "parts" / f"{name}.py").write_text(src, encoding="utf-8")
    layout = load_project(root)
    store = open_store(layout)
    cad = CadOps(layout, store)
    dispatcher = ToolDispatcher(ProjectStore(layout, store), cad=cad)
    seed_minimal_ledger(cad)
    return Project(root=root, layout=layout, store=store, cad=cad, dispatcher=dispatcher, _n=[0])


class FakeReviewer:
    """A reviewer child that passes everything it is shown, confidently.

    ``extra_ids`` also come back as ``pass`` — the ids of motion checks and
    joints, whose verdicts must count for nothing: no verdict is solicited for
    a motion id and none is accepted (``KINEMATICS.md`` §6, the ``ASSEMBLY.md``
    §3 rule extended).
    """

    def __init__(self, extra_ids: Sequence[str] = ()) -> None:
        self.requests: list[ReviewRequest] = []
        self._extra_ids = tuple(extra_ids)

    def call(self, request: ReviewRequest) -> ReviewerResponse:
        self.requests.append(request)
        findings = [
            {
                "id": str(cast("Mapping[str, Any]", entry)["id"]),
                "verdict": "pass",
                "evidence": "measured it, looks right",
                "channel": "numeric",
            }
            for entry in request.context.requirements
        ]
        findings.extend(
            {
                "id": extra,
                "verdict": "pass",
                "evidence": "the mechanism swings freely",
                "channel": "vision",
            }
            for extra in self._extra_ids
        )
        return ReviewerResponse(findings=tuple(findings))


def review(project: Project, extra_ids: Sequence[str] = ()) -> tuple[ReviewReport, FakeReviewer]:
    reviewer = FakeReviewer(extra_ids)
    report = TerminationReviewService(project.cad, reviewer).review(
        request="a hinged paddle mechanism with a slider",
        run_id="run-1",
    )
    return report, reviewer


def terminal(project: Project, report: ReviewReport) -> TerminalReport:
    return TerminalReport.of(
        report,
        cycles=1,
        reason="stop state",
        entries=project.cad.ledger_state().entries,
    )


@pytest.fixture(scope="module")
def run(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Project]:
    """The built mechanism with its joints, poses, and one holding sweep check.

    ``unbuilt`` stays deliberately unbuilt — the ``no_current_build`` cases bind
    to it — and no joint touches it, so the baseline motion status is clean.
    """
    project = make_mechanism_project(tmp_path_factory.mktemp("motion-review"))
    try:
        for part in ("base", "arm", "slider"):
            result = cast("dict[str, Any]", project.call("build_part", {"name": part}))
            assert result["status"] == "ok", result
        joints = project.cad.joint_set()
        joints.declare(
            {
                "id": "j-hinge",
                "kind": "revolute",
                "parent": "base:hinge_bore",
                "child": "arm:hinge_pin",
                "limits": {"min": -180.0, "max": 180.0},
                "provenance": {"requirement": "r-1"},
            }
        )
        joints.declare(
            {
                "id": "j-slide",
                "kind": "prismatic",
                "parent": "base:slide_face",
                "child": "slider:foot_face",
                "limits": {"min": -1.0, "max": 20.0},
                "provenance": assumed("slide travel is a fixture assumption"),
            }
        )
        poses = project.cad.pose_set()
        poses.declare(
            {"id": "p-zero", "joints": {"j-hinge": 0.0}, "provenance": {"requirement": "r-1"}}
        )
        poses.declare(
            {"id": "p-swing", "joints": {"j-hinge": -90.0}, "provenance": {"requirement": "r-1"}}
        )
        project.cad.motion_check_set().declare(
            {
                "id": "mc-ok",
                "kind": "sweep_clearance",
                "a": "arm",
                "b": "base",
                "sweep": {"j-hinge": {"from": -10.0, "to": 10.0}},
                "min_mm": 0.05,
                "samples": 3,
                "provenance": {"requirement": "r-1"},
            }
        )
        yield project
    finally:
        project.close()


# ==========================================================================
# the context: MotionStatus + worst-sample numeric facts + posed renders


def test_the_reviewer_context_carries_motion_status_worst_samples_and_posed_renders(
    run: Project,
) -> None:
    report, reviewer = review(run)
    assert report.green is True, "a clean mechanism does not block"

    context = reviewer.requests[0].context
    # The FULL motion status, measured at review time — never a summary.
    assert context.motion is not None
    assert set(context.motion.resolved_joints) == {"j-hinge", "j-slide"}
    assert set(context.motion.resolved_poses) == {"p-zero", "p-swing"}
    assert context.motion.blocking() == ()
    assert context.motion_ref is not None
    # Every motion-check result, with the worst sample's parameter values and
    # measured value as numeric facts (the pinned pin/bore air).
    assert [result.id for result in context.motion_checks] == ["mc-ok"]
    ok = context.motion_checks[0]
    assert ok.verdict == "holds_at_samples"
    assert ok.samples_evaluated == ok.grid_total == 3
    assert ok.worst is not None
    assert set(ok.worst.values) == {"j-hinge"}
    assert ok.worst.measured == pytest.approx(NOMINAL_RADIAL_AIR_MM, abs=1e-6)
    # Posed-scene renders at each declared pose and at the sweep's worst sample
    # (the explicit-assignment form), one per review view, all published refs.
    by_pose = {render.pose_id for render in context.posed_renders if render.pose_id}
    assert by_pose == {"p-zero", "p-swing"}
    worst_renders = [render for render in context.posed_renders if render.check_id == "mc-ok"]
    assert len(worst_renders) == len(REVIEW_VIEWS)
    assert worst_renders[0].assignment["j-hinge"] == ok.worst.values["j-hinge"]
    assert worst_renders[0].pose_id is None, "a worst sample is not a named pose"
    assert len(context.posed_renders) == 3 * len(REVIEW_VIEWS)
    assert all(render.artifact_ref and render.scene_ref for render in context.posed_renders)
    # The context says what it is handing over, and the prompt says the rule.
    blob = context.to_json()
    assert isinstance(blob["motion"], dict) and isinstance(blob["motion_checks"], list)
    assert isinstance(blob["posed_renders"], list) and len(blob["posed_renders"]) == 6
    prompt = context.prompt()
    assert "motion" in prompt and "posed_renders" in prompt
    assert "non-success motion state blocks termination" in prompt


def test_a_success_only_motion_state_does_not_block(run: Project) -> None:
    """``holds_at_samples`` and ``satisfied`` are the two success verdicts —
    a status carrying only those (and no unresolvable joint/pose) is green."""
    checks = run.cad.motion_check_set()
    checks.declare(
        {
            "id": "mc-reach-ok",
            "kind": "reach",
            "anchor": "arm",
            "target_point_mm": list(REACH_TARGET_MM),
            "tol_mm": 0.01,
            "sweep": {"j-hinge": {"from": -100.0, "to": -80.0}},
            "samples": 3,
            "provenance": assumed(),
        }
    )
    report, _reviewer = review(run)

    verdicts = {result.id: result.verdict for result in report.motion_checks}
    assert verdicts == {"mc-ok": "holds_at_samples", "mc-reach-ok": "satisfied"}
    assert report.motion is not None and report.motion.blocking() == ()
    assert report.green is True
    assert terminal(run, report).status == "green"


# ==========================================================================
# each non-success verdict blocks by RULE, whatever the reviewer says


def test_a_violated_sweep_blocks_however_it_is_reviewed(run: Project) -> None:
    checks = run.cad.motion_check_set()
    checks.declare(
        {
            "id": "mc-viol",
            "kind": "sweep_clearance",
            "a": "arm",
            "b": "base",
            "sweep": {"j-hinge": {"from": -10.0, "to": 10.0}},
            "min_mm": 0.2,
            "samples": 3,
            "provenance": {"requirement": "r-1"},
        }
    )
    try:
        report, reviewer = review(run, extra_ids=("mc-viol",))

        # The reviewer passed everything, and its verdict for the check id was
        # neither asked for nor accepted.
        assert "mc-viol" in report.unknown_ids
        blocking = report.by_id["mc-viol"]
        assert blocking.verdict == "fail"
        assert blocking.harness is True, "the finding is stamped by rule, not solicited"
        assert "violated" in blocking.evidence
        assert "min_mm=0.2" in (blocking.expected or "")
        assert "measured" in (blocking.observed or "")
        # The finding's numeric facts trace to the worst sample the engine
        # measured: 0.1 mm of air against the declared 0.2 mm floor.
        result = next(r for r in report.motion_checks if r.id == "mc-viol")
        assert result.worst is not None
        assert result.worst.measured == pytest.approx(NOMINAL_RADIAL_AIR_MM, abs=1e-6)
        assert str(result.worst.measured) in (blocking.observed or "")
        assert report.green is False

        open_items = terminal(run, report)
        assert open_items.status == "unresolved_requirements"
        item = next(entry for entry in open_items.unresolved if entry.id == "mc-viol")
        assert item.source == "motion"
        assert "violated" in item.text
        # The reviewer really was shown the failure it passed anyway, renders
        # of the worst sample included.
        context = reviewer.requests[0].context
        assert any(render.check_id == "mc-viol" for render in context.posed_renders)
    finally:
        checks.withdraw("mc-viol", "clause finished; withdrawal is not erasure")


def test_not_reached_blocks_and_carries_the_closest_sample(run: Project) -> None:
    """``not_reached_at_samples`` is not ``violated`` — samples not reaching are
    evidence, not proof of unreachability — and it is not a pass either."""
    checks = run.cad.motion_check_set()
    checks.declare(
        {
            "id": "mc-miss",
            "kind": "reach",
            "anchor": "arm",
            "target_point_mm": list(REACH_TARGET_MM),
            "tol_mm": 0.01,
            "sweep": {"j-hinge": {"from": -10.0, "to": 10.0}},
            "samples": 3,
            "provenance": assumed(),
        }
    )
    try:
        report, reviewer = review(run)

        blocking = report.by_id["mc-miss"]
        assert blocking.verdict == "fail" and blocking.harness is True
        assert "not_reached_at_samples" in blocking.evidence
        assert "violated" not in blocking.evidence
        result = next(r for r in reviewer.requests[0].context.motion_checks if r.id == "mc-miss")
        assert result.verdict == "not_reached_at_samples"
        assert result.worst is not None
        assert result.worst.measured == pytest.approx(REACH_MISS_AT_SMALL_ANGLES_MM, abs=1e-3)
        assert result.miss_mm == pytest.approx(REACH_MISS_AT_SMALL_ANGLES_MM - 0.01, abs=1e-3)
        assert str(result.miss_mm) in blocking.evidence
        assert report.green is False
        assert terminal(run, report).status == "unresolved_requirements"
    finally:
        checks.withdraw("mc-miss", "clause finished")


def test_an_unmeasurable_motion_check_blocks_under_its_own_name(run: Project) -> None:
    """``unresolvable`` is not ``violated``, and it is not a pass either."""
    checks = run.cad.motion_check_set()
    checks.declare(
        {
            "id": "mc-ghost",
            "kind": "sweep_clearance",
            "a": "unbuilt",
            "b": "base",
            "sweep": {"j-hinge": {"from": -10.0, "to": 10.0}},
            "min_mm": 1.0,
            "samples": 3,
            "provenance": assumed(),
        }
    )
    try:
        report, _reviewer = review(run)

        blocking = report.by_id["mc-ghost"]
        assert blocking.verdict == "fail" and blocking.harness is True
        assert "could NOT be evaluated" in blocking.evidence
        assert "no_current_build" in blocking.evidence
        # Nothing was measured, so nothing is claimed to have been.
        assert blocking.observed is None
        assert report.green is False
    finally:
        checks.withdraw("mc-ghost", "clause finished")


def test_an_unresolvable_joint_blocks_and_is_never_rendered_past(run: Project) -> None:
    """A declared joint that was never evaluated is not a working one — and no
    posed scene is guessed around it (a render failure costs the render, never
    the review; the blocking finding is stamped from the measured status)."""
    joints = run.cad.joint_set()
    joints.declare(
        {
            "id": "j-broken",
            "kind": "fixed",
            "parent": "base",
            "child": "unbuilt",
            "provenance": assumed("attachment claimed before the part was built"),
        }
    )
    try:
        report, reviewer = review(run)

        context = reviewer.requests[0].context
        assert context.motion is not None
        assert "j-broken" in context.motion.blocking()
        blocking = report.by_id["j-broken"]
        assert blocking.verdict == "fail" and blocking.harness is True
        assert "could NOT be resolved" in blocking.evidence
        assert "no_current_build" in blocking.evidence
        assert report.green is False

        open_items = terminal(run, report)
        item = next(entry for entry in open_items.unresolved if entry.id == "j-broken")
        assert item.source == "motion"
        assert "declared joint j-broken" in item.text
    finally:
        joints.withdraw("j-broken", "clause finished")


def test_a_sweep_ceiling_timeout_blocks_with_its_partial_facts(
    run: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A killed sweep decided nothing: the timeout is never dressed as a result
    record, its partial per-sample facts ride the context, and it blocks —
    an unchecked motion claim is not a passing one."""
    monkeypatch.setattr(motion_module, "_sweep_child", grinding_child)
    # Must dominate spawn bootstrap on a loaded machine (see TEST_CEILING_S in
    # test_sweep_evaluation.py) or the children die before streaming a sample.
    monkeypatch.setenv(MOTION_TIMEOUT_ENV, "10.0")

    report, reviewer = review(run)

    context = reviewer.requests[0].context
    # Every active check ground past the ceiling; none produced a result record.
    assert context.motion_checks == ()
    assert {str(timeout["id"]) for timeout in context.motion_timeouts} == {
        "mc-ok",
        "mc-reach-ok",
    }
    timeout = next(t for t in context.motion_timeouts if t["id"] == "mc-ok")
    assert timeout["reason"] == "motion_timeout"
    assert timeout["samples_evaluated"] == 2, "the streamed partial facts are on the record"
    blocking = report.by_id["mc-ok"]
    assert blocking.verdict == "fail" and blocking.harness is True
    assert "ceiling" in blocking.evidence
    assert report.green is False
    assert terminal(run, report).status == "unresolved_requirements"
