# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""G9C Tier 1: the corpus v3 mechanism tasks grade through the engine path.

``KINEMATICS.md`` §6 (bench) and Gate G9C: corpus v3's mechanism tasks are
graded through the same engine path ``check_motion`` uses — the task-owned
joints, poses and motion checks installed by the grader
(:mod:`hephaestus.bench.harness._grade`), pose-bound constraints through the
8C constraint path — and Tier 1 is the meta-rule of ``verification.md``
applied to them: *a task no reference solution passes is a broken task, not a
hard task*. Corpus v2 sharpened that rule for every NEW task: one passing
solution proves passability, and only a second, independently authored
implementation proves the acceptance grades the engineering rather than the
reference geometry back (``VALIDATION.md`` §1) — so BOTH solutions are graded
here, through :func:`grade_reference_solution`, the exact function a
benchmarked run's project is graded by.

This module covers the **hinge** task (``hinge-travel``: a lid on a revolute
hinge with declared 0..110 degree travel limits, a ``sweep_clearance`` against
the base's wire channel over the full travel, and a pose-bound constraint at
the open limit) and the **gripper** task (``gripper-jaws``: a sliding jaw on
a prismatic joint with declared 0..25 mm travel, pose-bound closure-fit
constraints at both ends of it, and a ``sweep_no_interference`` over the full
stroke — plus a mis-built-jaw negative control proving the acceptance bites
under the engine's own reason tokens) and the **lead-screw** task
(``leadscrew-actuator``: a §5 coupling driving a carriage from a motor joint,
a ``reach`` to the top-of-stroke handoff point and a ``sweep_no_interference``
over the stroke — plus a no-coupling negative control proving the acceptance
exercises the transmission rather than trusting its declaration). Each case's
clauses pin the numbers the task's own ``notes`` derive by hand, so a
regression in FK, sweep sampling or pose-bound constraint evaluation moves a
*known* number, loudly.

DELIBERATELY NOT IN THIS SUITE — the Gate G9C Tier 3 bench clause (the
``tests/stage7h/CI_ONLY.md`` precedent: a clause is either covered by a test
here or *named* with the machinery that produces its evidence — never a
silent absence, never a skip dressed up as a pass). The live reference-model
measurement of the mechanism splits is a detached bench run after this change
lands, and its rule is the spec's own-split baselining language (Gate G9C,
following the Stage 2V split rule of ``VALIDATION.md`` §1 verbatim):
*mechanism-prose and mechanism-seeded are each their own split, each
baselined on its own first measurement with the reference model at >=3
seeds, neither compared against nor averaged into the v1/v2 baselines* — the
existing 0.70 prose bar keys on its own coverage and is not diluted. No
local pytest can create that machine state; what THIS suite proves is the
Tier 1 half the spec puts before it: the tasks are gradeable through the
engine path and passable by their own dual solutions.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import pytest
from hephaestus.bench.harness import (
    BenchTask,
    GradeReport,
    corpus_solutions_dir,
    grade,
    grade_reference_solution,
    load_tasks,
    seed_project,
)

#: The independently authored second implementations (the corpus-variant
#: fixture tree the server meta-suite grades from; one home, not a copy).
CORPUS_VARIANTS: Path = (
    Path(__file__).resolve().parents[2] / "server" / "tests" / "fixtures" / "corpus_variants"
)

#: The hinge task's hand-derived governing numbers (task.json ``notes``):
#: the swing clearance bottoms out interior to the travel — the plate's
#: front-bottom corner edge (radius sqrt(38^2 + 7^2) about the hinge axis)
#: against the rib's near top corner (radius sqrt(40^2 + 4^2)) — so the
#: 56-sample grid's worst sample lands at 4.0 degrees, NOT at either travel
#: end, measuring 40 - (38 cos 4 + 7 sin 4) exactly.
HINGE_WORST_SAMPLE_DEG = 4.0
HINGE_WORST_CLEARANCE_MM = 1.604270773917797
HINGE_OPEN_ACCESS_MM = 34.03


@pytest.fixture(scope="module")
def hinge_task() -> BenchTask:
    (task,) = load_tasks(["hinge-travel"])
    return task


def _mapping(value: Any) -> Mapping[str, Any]:
    assert isinstance(value, dict), f"expected a mapping record, got {value!r}"
    return cast("Mapping[str, Any]", value)


#: The Stage 9C corpus-v3 additions (KINEMATICS.md §6 bench bullet), stated
#: here so the gate suite owns its own count clause.
MECHANISM_TRIO: frozenset[str] = frozenset({"gripper-jaws", "hinge-travel", "leadscrew-actuator"})


def test_the_corpus_count_pin_is_nineteen_with_the_mechanism_trio() -> None:
    """Gate G9C: "corpus-count pins repointed with this stage cited".

    The repointed pins live where the counts were pinned —
    ``tests/stage6/test_g6_corpus_v1.py`` (``CORPUS_SIZE`` 16 -> 19) and
    ``server/tests/test_bench_corpus.py`` (``CORPUS_V3_ADDITIONS`` and the
    nineteen-task composition test) — each citing the Stage 9C corpus-v3
    amendment (KINEMATICS.md §6). This gate-owned restatement pins the same
    fact from stage9c so G9C cannot read green while the corpus it graded
    has drifted: nineteen public tasks, the mechanism trio among them, each
    trio member shipped in BOTH spec variants (prose + seeded, the
    VALIDATION.md §1 rule corpus expansion must not breach).

    Count repointed 2026-08-29 by PARTS_STORE.md Stage 11 (G11C clause 13),
    which adds the component-bearing pair; the mechanism assertions below are
    untouched.
    """
    prose = {task.id for task in load_tasks(specs=("prose",))}
    # Repointed 2026-08-29 (PARTS_STORE.md Stage 11, G11C clause 13): corpus v4
    # adds the component-bearing pair `bearing-shaft` and `motor-plate`. What
    # THIS clause pins is unchanged — the mechanism trio is still present, in
    # both spec variants — so only the total moved, and it is asserted as the
    # total rather than as "nineteen".
    # Repointed again 2026-08-29 (MESH_INGEST.md §7.5, Stage 12C / G12C clause
    # 50): corpus v5 adds the scan family `scan-socket-cuff` and
    # `scan-boss-relief`. What THIS clause pins is still unchanged.
    assert len(prose) == 23, "corpus v5 is twenty-three public tasks (MESH_INGEST.md Stage 12)"
    assert prose >= MECHANISM_TRIO
    seeded = {task.id for task in load_tasks(specs=("seeded",))}
    assert {f"{task_id}@seeded" for task_id in MECHANISM_TRIO} <= seeded
    assert len(seeded) == 23


def _assert_hinge_acceptance(task: BenchTask, report: GradeReport) -> None:
    """Every clause of the hinge task's acceptance, judged on one grade."""
    assert report.passed, f"hinge-travel solution failed: {report.reasons}"
    assert report.check_status == "ok"
    for name, value in report.checks.items():
        assert _mapping(value).get("pass") is True, f"check {name} did not pass: {value}"

    # The declared mechanism resolved through the engine path (§2): the joint
    # frame came off the run's own tagged bore, the pose off the joint.
    assert len(report.joints) == len(task.joints) == 1
    joint_outcome = _mapping(_mapping(report.joints[0]).get("outcome"))
    assert joint_outcome.get("id") == "j-lid"
    assert joint_outcome.get("state") == "resolved"
    parent = _mapping(joint_outcome.get("parent"))
    assert parent.get("anchor") == "base:hinge_bore"
    assert parent.get("artifact_ref"), "the joint frame must bind the graded artifact"
    assert len(report.poses) == len(task.poses) == 1
    pose_outcome = _mapping(_mapping(report.poses[0]).get("outcome"))
    assert pose_outcome.get("id") == "p-open"
    assert pose_outcome.get("state") == "resolved"
    assert pose_outcome.get("joints") == {"j-lid": 110.0}

    # The sweep: verdict spelled ``holds_at_samples`` verbatim (§4 — samples
    # are evidence, never a continuous guarantee), the full grid evaluated,
    # and the worst sample the hand derivation names: interior to the travel,
    # at the 4-degree sample, to FK precision.
    assert len(report.motion_checks) == len(task.motion_checks) == 1
    sweep_result = _mapping(_mapping(report.motion_checks[0]).get("result"))
    assert sweep_result.get("id") == "mc-lid-swing"
    assert sweep_result.get("verdict") == "holds_at_samples"
    assert sweep_result.get("samples_evaluated") == 56
    worst = _mapping(sweep_result.get("worst"))
    assert worst.get("values") == {"j-lid": HINGE_WORST_SAMPLE_DEG}
    assert worst.get("measured") == pytest.approx(HINGE_WORST_CLEARANCE_MM, abs=1e-9)
    assert cast("float", worst.get("measured")) >= 1.2, "the declared bar itself"

    # The constraints: the unbound 8C entry keeps its meaning, and the
    # pose-bound entry carries the §3 extended shape — a ``pose_residuals``
    # table with the p-open row — measuring the stand-clear the notes derive
    # (~34.03 mm), which at zero would be 2.0 mm: the binding is load-bearing.
    assert len(report.constraints) == len(task.constraints) == 2
    outcomes = {
        str(_mapping(_mapping(record).get("outcome")).get("id")): _mapping(
            _mapping(record).get("outcome")
        )
        for record in report.constraints
    }
    assert outcomes["c-hinge-concentric"].get("state") == "satisfied"
    open_access = outcomes["c-open-access"]
    assert open_access.get("state") == "satisfied"
    rows = cast("list[Any]", open_access.get("pose_residuals"))
    assert [str(_mapping(row).get("pose_id")) for row in rows] == ["p-open"]
    row = _mapping(rows[0])
    assert row.get("verdict") == "satisfied"
    residual = _mapping(row.get("residual"))
    assert cast("float", residual.get("measured")) == pytest.approx(HINGE_OPEN_ACCESS_MM, abs=0.01)

    # Both exports were produced from the graded geometry, nothing tampered.
    assert len(report.exports) == len(task.exports) == 2
    for record in report.exports:
        assert "invalid" not in record, record
    assert report.restored_protected == ()


def test_hinge_reference_solution_passes_its_own_acceptance(
    hinge_task: BenchTask, tmp_path: Path
) -> None:
    """Tier 1, first half: the task is passable — by its reference solution.

    The reference declares its own mechanism through ``kinematics.json`` (the
    real declare-tool path a run would take), so the grader's install pass
    exercises the REPLACE branch: the task's acceptance entries land as
    recorded update generations over the solution's same-id declarations.
    """
    report = grade_reference_solution(hinge_task, tmp_path / "project")
    _assert_hinge_acceptance(hinge_task, report)


def test_hinge_variant_solution_passes_the_same_acceptance(
    hinge_task: BenchTask, tmp_path: Path
) -> None:
    """Tier 1, second half: a different, correct build passes too.

    The variant is independently constructed (tube-first lugs, align-based
    layout, chamfered outer corners the reference does not have) and declares
    NO mechanism of its own, so the grader's install pass exercises the
    DECLARE branch — and the acceptance numbers still land on the same
    hand-derived values, because they are properties of the interface
    geometry, not of the reference's construction order.
    """
    report = grade_reference_solution(
        hinge_task, tmp_path / "project", solutions_dir=CORPUS_VARIANTS
    )
    _assert_hinge_acceptance(hinge_task, report)


# ==========================================================================
# the GRIPPER case (gripper-jaws: jaw travel + posed closure fit)

#: The gripper's hand-computed numbers, restated independently of the task
#: files so a drive-by edit to ``globals.py`` cannot quietly move the gate.
GRIPPER_OPEN_GAP_MM = 28.0
GRIPPER_CLOSED_GAP_MM = 3.0
GRIPPER_TRAVEL_MM = 25.0
GRIPPER_SWEEP_SAMPLES = 26
#: The mutant jaw is authored 5 mm too far closed: at full travel it buries
#: itself 2 mm into the fixed jaw across the full 30 x 20 face = 1200 mm^3.
GRIPPER_MUTANT_OVERLAP_MM3 = 1200.0


@pytest.fixture(scope="module")
def gripper() -> BenchTask:
    (task,) = load_tasks(["gripper-jaws"])
    return task


class TestGripperAcceptanceShape:
    def test_the_acceptance_is_declared_mechanism_state(self, gripper: BenchTask) -> None:
        """The task grades a mechanism, stated as one: a prismatic joint with
        the full declared travel, both poses at its ends, and a sweep whose
        success is spelled ``holds_at_samples`` — §4's evidence spelling,
        never a continuous claim."""
        (joint,) = gripper.joints
        assert joint.entry["kind"] == "prismatic"
        limits = _mapping(joint.entry["limits"])
        assert (limits["min"], limits["max"]) == (0.0, GRIPPER_TRAVEL_MM)
        assert {pose.id for pose in gripper.poses} == {"p-open", "p-closed"}
        (check,) = gripper.motion_checks
        assert check.entry["kind"] == "sweep_no_interference"
        assert check.expect == "holds_at_samples"
        sweep = _mapping(check.entry["sweep"])
        assert _mapping(sweep["j-jaw"])["to"] == GRIPPER_TRAVEL_MM

    def test_the_closure_fit_is_pose_bound_through_the_constraint_path(
        self, gripper: BenchTask
    ) -> None:
        """KINEMATICS.md §3's vocabulary, used as designed: the same 8C
        ``distance`` kind, bound to the declared pose ids — 28 mm at
        ``p-open``, the 3 mm grip envelope at ``p-closed``."""
        declared_poses = {pose.id for pose in gripper.poses}
        by_id = {constraint.id: constraint for constraint in gripper.constraints}
        assert set(by_id) == {"c-open-gap", "c-closure-fit"}
        for constraint in gripper.constraints:
            assert constraint.expect == "satisfied"
            bound = cast("list[str]", constraint.entry["poses"])
            assert set(bound) <= declared_poses
        assert by_id["c-open-gap"].entry["value_mm"] == GRIPPER_OPEN_GAP_MM
        assert by_id["c-closure-fit"].entry["value_mm"] == GRIPPER_CLOSED_GAP_MM

    def test_the_mechanism_parts_are_the_tasks_deliverables(self, gripper: BenchTask) -> None:
        """Joint and sweep anchors declare parts exactly as constraint anchors
        do — the grader must build what the mechanism rides on."""
        assert gripper.declared_parts() == frozenset({"body", "jaw"})


def _assert_gripper_acceptance(label: str, report: GradeReport) -> None:
    """The whole gripper mechanism acceptance, read off one grade report."""
    assert report.passed, f"{label} solution failed: {report.reasons}"
    for name, value in report.checks.items():
        assert _mapping(value).get("pass") is True, f"{label}: check {name} did not pass: {value}"
    # The joint resolved through the run's tagged geometry (frame evidence
    # carries the artifact refs it was extracted from).
    (joint_record,) = report.joints
    outcome = _mapping(_mapping(joint_record).get("outcome"))
    assert outcome["state"] == "resolved"
    for side in ("parent", "child"):
        assert _mapping(outcome[side]).get("artifact_ref"), outcome
    # Both poses resolved — the geometry really takes the full declared travel.
    for pose_record in report.poses:
        assert _mapping(_mapping(pose_record).get("outcome"))["state"] == "resolved"
    # The sweep evaluated its whole grid and holds AT THE SAMPLES, worst
    # sample restated with its parameter values (the §4 record).
    (check_record,) = report.motion_checks
    result = _mapping(_mapping(check_record).get("result"))
    assert result["verdict"] == "holds_at_samples"
    assert result["samples_evaluated"] == GRIPPER_SWEEP_SAMPLES
    worst = _mapping(result["worst"])
    assert worst["measured"] == pytest.approx(0.0, abs=1e-9)
    assert "j-jaw" in _mapping(worst["values"])
    # The posed closure fit: each constraint satisfied with its bound pose's
    # residual row carrying the hand-computed gap exactly.
    expected_gap = {"c-open-gap": GRIPPER_OPEN_GAP_MM, "c-closure-fit": GRIPPER_CLOSED_GAP_MM}
    assert len(report.constraints) == len(expected_gap)
    for record in report.constraints:
        outcome = _mapping(_mapping(record).get("outcome"))
        assert outcome["state"] == "satisfied", outcome
        (row,) = cast("list[Any]", outcome["pose_residuals"])
        residual = _mapping(_mapping(row)["residual"])
        want = expected_gap[str(outcome["id"])]
        assert cast("float", residual["measured"]) == pytest.approx(want, abs=1e-6)


class TestGripperTier1BothSolutionsPass:
    def test_the_reference_solution_passes_its_own_acceptance(
        self, gripper: BenchTask, tmp_path: Path
    ) -> None:
        report = grade_reference_solution(gripper, tmp_path / "project")
        _assert_gripper_acceptance("reference", report)

    def test_the_independent_second_solution_passes_the_same_acceptance(
        self, gripper: BenchTask, tmp_path: Path
    ) -> None:
        """A different build (corner-aligned layout, pocketed jaw, chamfered
        crowns) with the same interface planes: the acceptance grades the
        mechanism, not the reference geometry back (VALIDATION.md §1)."""
        report = grade_reference_solution(
            gripper, tmp_path / "project", solutions_dir=CORPUS_VARIANTS
        )
        _assert_gripper_acceptance("variant", report)


class TestGripperAcceptanceBites:
    def test_a_jaw_authored_too_far_closed_fails_under_the_named_motion_reasons(
        self, gripper: BenchTask, tmp_path: Path
    ) -> None:
        """The negative control: the jaw is authored 5 mm toward the fixed jaw
        (envelope unchanged, so only the mechanism can catch it). At full
        travel it buries 2 mm into the body: the sweep is ``violated`` with
        the worst sample's overlap volume, and both pose-bound gaps fail as
        ``constraint_violated`` carrying their measured distances — engine
        reason tokens, never a CHECKS coincidence."""
        root = tmp_path / "mutant"
        seed_project(gripper, root)
        (root / "parts").mkdir(exist_ok=True)
        solutions = corpus_solutions_dir() / "gripper-jaws" / "parts"
        shutil.copy2(solutions / "body.py", root / "parts")
        source = (solutions / "jaw.py").read_text(encoding="utf-8")
        mutation = "_face_x = hc.jaw_face_x"
        assert mutation in source
        (root / "parts" / "jaw.py").write_text(
            source.replace(mutation, "_face_x = hc.jaw_face_x + 5.0"), encoding="utf-8"
        )
        report = grade(gripper, root)

        assert not report.passed
        assert f"motion_check_violated:mc-jaw-travel:{GRIPPER_MUTANT_OVERLAP_MM3}" in report.reasons
        violated = {
            reason.rsplit(":", 1)[0]
            for reason in report.reasons
            if reason.startswith("constraint_violated:")
        }
        assert violated == {
            "constraint_violated:c-open-gap",
            "constraint_violated:c-closure-fit",
        }, report.reasons
        # The worst sample is the deepest configuration, restated by value.
        (check_record,) = report.motion_checks
        worst = _mapping(_mapping(_mapping(check_record)["result"])["worst"])
        assert _mapping(worst["values"])["j-jaw"] == GRIPPER_TRAVEL_MM
        assert cast("float", worst["measured"]) == pytest.approx(
            GRIPPER_MUTANT_OVERLAP_MM3, abs=1e-6
        )
        # And nothing was unresolvable: the wrong mechanism was measured wrong.
        assert not any("unresolvable" in reason for reason in report.reasons)


# ==========================================================================
# the LEAD-SCREW case (leadscrew-actuator: a §5 coupling driving a linear axis)
#
# The task owns the joints (travel limits included) and the two stroke sweeps;
# the COUPLING is deliberately the run's to declare — the reach check sweeps
# only the free motor parameter, so the transmission claim is *measured*: a
# solution that never declares ``cp-leadscrew`` leaves the carriage parked at
# zero and misses the top-of-stroke handoff point by the whole 20 mm stroke.
# Solutions declare their mechanism through ``kinematics.json``, applied by
# ``apply_solution`` through the same real ``CadOps`` declare paths a run's
# tool calls take (the ``params.json`` precedent).

#: The lead-screw hand numbers, restated independently of the task files.
LEADSCREW_LEAD_MM_PER_DEG = 2.0 / 360.0
LEADSCREW_MOTOR_TRAVEL_DEG = 3600.0
LEADSCREW_STROKE_MM = 20.0
LEADSCREW_REACH_TOL_MM = 0.25
LEADSCREW_SAMPLES = 41


@pytest.fixture(scope="module")
def leadscrew() -> BenchTask:
    (task,) = load_tasks(["leadscrew-actuator"])
    return task


def _leadscrew_motion_records(report: GradeReport) -> dict[str, Mapping[str, Any]]:
    """``{check id: record}`` out of a grade report's motion-check records."""
    out: dict[str, Mapping[str, Any]] = {}
    for record in report.motion_checks:
        entry = _mapping(_mapping(_mapping(record)["requirement"])["entry"])
        out[str(entry["id"])] = _mapping(record)
    return out


def _assert_leadscrew_acceptance(label: str, report: GradeReport) -> None:
    """The green-path shape both solutions must produce, nothing skipped."""
    assert report.passed, f"{label} solution failed: {report.reasons}"
    for name, value in report.checks.items():
        assert _mapping(value).get("pass") is True, f"{label}: check {name} did not pass: {value}"
    # Both task joints resolved through the run's tagged geometry.
    assert len(report.joints) == 2
    for joint_record in report.joints:
        assert _mapping(_mapping(joint_record).get("outcome"))["state"] == "resolved"
    records = _leadscrew_motion_records(report)
    # The reach: the coupling carries the nose to the handoff point, and the
    # achieving sample assigns ONLY the free motor parameter — the carriage is
    # derived by the run's own coupling, which is the §5 point.
    reach = _mapping(records["mc-stroke-reach"].get("result"))
    assert reach["verdict"] == "satisfied"
    worst = _mapping(reach["worst"])
    values = _mapping(worst["values"])
    assert set(values) == {"j-motor"}
    assert cast("float", values["j-motor"]) == pytest.approx(LEADSCREW_MOTOR_TRAVEL_DEG)
    assert cast("float", worst["measured"]) == pytest.approx(0.0, abs=1e-6)
    # The stroke sweep: every sample clean, the grid total restated.
    clear = _mapping(records["mc-stroke-clear"].get("result"))
    assert clear["verdict"] == "holds_at_samples"
    assert clear["samples_evaluated"] == LEADSCREW_SAMPLES


class TestLeadscrewAcceptanceShape:
    def test_the_task_owns_joints_and_sweeps_but_never_the_coupling(
        self, leadscrew: BenchTask
    ) -> None:
        """Structural pins so the acceptance cannot silently lose its subject:
        the task installs both joints and both stroke sweeps; the coupling is
        deliberately NOT a task requirement, because a task-declared coupling
        would grade the task's own transmission rather than the run's."""
        assert {joint.id for joint in leadscrew.joints} == {"j-motor", "j-carriage"}
        kinds = {joint.id: str(joint.entry["kind"]) for joint in leadscrew.joints}
        assert kinds == {"j-motor": "revolute", "j-carriage": "prismatic"}
        expects = {check.id: check.expect for check in leadscrew.motion_checks}
        assert expects == {
            "mc-stroke-reach": "satisfied",
            "mc-stroke-clear": "holds_at_samples",
        }
        # Both sweeps assign only the free motor parameter, over the full
        # ten-turn window; the carriage limits cover the derived stroke.
        for check in leadscrew.motion_checks:
            sweep = _mapping(check.entry["sweep"])
            assert set(sweep) == {"j-motor"}
            window = _mapping(sweep["j-motor"])
            assert (window["from"], window["to"]) == (0.0, LEADSCREW_MOTOR_TRAVEL_DEG)
        carriage = next(j for j in leadscrew.joints if j.id == "j-carriage")
        limits = _mapping(carriage.entry["limits"])
        assert (
            cast("float", limits["max"]) >= LEADSCREW_LEAD_MM_PER_DEG * LEADSCREW_MOTOR_TRAVEL_DEG
        )
        assert leadscrew.declared_parts() == frozenset({"frame", "screw", "carriage"})

    def test_both_solutions_declare_the_metric_lead_transmission(
        self, leadscrew: BenchTask
    ) -> None:
        """The dual solutions really both claim the 2 mm/rev coupling — from
        their own ``kinematics.json``, the state a run would declare by tool."""
        for solutions in (corpus_solutions_dir(), CORPUS_VARIANTS):
            kinematics = _mapping(
                json.loads(
                    (solutions / "leadscrew-actuator" / "kinematics.json").read_text(
                        encoding="utf-8"
                    )
                )
            )
            (coupling,) = cast("list[Any]", kinematics["couplings"])
            entry = _mapping(coupling)
            assert entry["id"] == "cp-leadscrew"
            assert (entry["parent"], entry["child"]) == ("j-motor", "j-carriage")
            assert cast("float", entry["ratio"]) == pytest.approx(LEADSCREW_LEAD_MM_PER_DEG)

    def test_the_seeded_variant_derives_with_the_mechanism_acceptance(
        self, leadscrew: BenchTask
    ) -> None:
        """Corpus v3 ships both spec variants (VALIDATION.md §1): the seeded
        twin derives from the same directory with the acceptance checks
        protected — and the same kinematic requirements, never a drifted copy."""
        (seeded,) = load_tasks(["leadscrew-actuator@seeded"])
        assert seeded.spec == "seeded"
        assert seeded.base_id == leadscrew.id
        assert "checks/leadscrew_actuator.py" in seeded.protected_paths
        assert seeded.joints == leadscrew.joints
        assert seeded.motion_checks == leadscrew.motion_checks


class TestLeadscrewTier1BothSolutionsPass:
    def test_the_reference_solution_passes_its_own_acceptance(
        self, leadscrew: BenchTask, tmp_path: Path
    ) -> None:
        """The whole engine path: parts built, the task's joints installed
        over the solution's, the solution's own coupling deriving the
        carriage, the reach hit exactly at the top-of-stroke sample."""
        report = grade_reference_solution(leadscrew, tmp_path / "project")
        _assert_leadscrew_acceptance("reference", report)

    def test_the_independent_second_solution_passes_the_same_acceptance(
        self, leadscrew: BenchTask, tmp_path: Path
    ) -> None:
        """A different build (extruded frame, revolved screw, MIN-aligned
        carriage) with the same interfaces: the acceptance grades the
        mechanism, not the reference geometry back (VALIDATION.md §1)."""
        report = grade_reference_solution(
            leadscrew, tmp_path / "project", solutions_dir=CORPUS_VARIANTS
        )
        _assert_leadscrew_acceptance("variant", report)


class TestLeadscrewCouplingIsExercised:
    def test_a_solution_that_declares_no_coupling_fails_the_reach(
        self, leadscrew: BenchTask, tmp_path: Path
    ) -> None:
        """The negative control the gate demands: the acceptance must EXERCISE
        the coupling, not trust its declaration. The mutated fixture is the
        reference solution minus its ``couplings`` section — same geometry,
        same joints — so the only thing that changes is the transmission: the
        reach sweeping the free motor leaves the carriage parked at zero and
        misses by the whole stroke, under §4's honest not-reached spelling.
        The no-interference sweep still holds (a parked carriage collides with
        nothing), so the failure is attributable to the coupling's absence and
        nothing else — asserted against the engine result, never by trusting
        the grader's bookkeeping."""
        mutated_solutions = tmp_path / "solutions"
        target = mutated_solutions / "leadscrew-actuator"
        shutil.copytree(corpus_solutions_dir() / "leadscrew-actuator", target)
        kinematics_path = target / "kinematics.json"
        kinematics = dict(_mapping(json.loads(kinematics_path.read_text(encoding="utf-8"))))
        del kinematics["couplings"]
        kinematics_path.write_text(json.dumps(kinematics), encoding="utf-8")

        report = grade_reference_solution(
            leadscrew, tmp_path / "project", solutions_dir=mutated_solutions
        )

        assert report.passed is False
        assert (
            "motion_check_state:mc-stroke-reach:not_reached_at_samples!=satisfied" in report.reasons
        ), report.reasons
        # The reach record carries the honest miss evidence: the closest
        # sample is the whole stroke away, less the declared tolerance.
        records = _leadscrew_motion_records(report)
        reach = _mapping(records["mc-stroke-reach"].get("result"))
        assert reach["verdict"] == "not_reached_at_samples"
        assert cast("float", reach["miss_mm"]) == pytest.approx(
            LEADSCREW_STROKE_MM - LEADSCREW_REACH_TOL_MM, abs=0.01
        )
        # The interference sweep is NOT the failing clause, and the geometry
        # checks all still pass: this failure isolates the coupling.
        clear = _mapping(records["mc-stroke-clear"].get("result"))
        assert clear["verdict"] == "holds_at_samples"
        assert not any(
            reason.startswith("motion_check_state:mc-stroke-clear")
            or reason.startswith("check_failed:")
            for reason in report.reasons
        ), report.reasons
