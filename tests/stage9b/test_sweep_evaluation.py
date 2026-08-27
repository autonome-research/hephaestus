# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""G9B: sampled sweep evaluation (``KINEMATICS.md`` §4), verdicts verbatim.

The engine-side gate clauses of the motion-check half:

* *each kind on both sides of its threshold, with ALL FIVE verdict spellings
  asserted verbatim* — ``holds_at_samples`` / ``violated`` for the universal
  kinds (never "holds": all-good samples only evidence), ``satisfied`` /
  ``not_reached_at_samples`` for ``reach`` (one achieving sample IS proof;
  samples not reaching are evidence, so the failure carries the closest
  sample's parameters and the miss distance), and ``unresolvable``;
* *worst-sample facts in every result* — ``samples_evaluated`` (the grid
  total), the worst sample's parameter values, and its measured value;
* *the multi-joint grid* — ``samples`` is per-axis and the evaluated total is
  the product;
* *bounded execution* (``COMPARE.md`` §5 pattern, both legs) — the grid runs
  in a killable spawned subprocess under ``MOTION_TIMEOUT_S`` (env
  ``HEPHAESTUS_MOTION_TIMEOUT_S``), per-sample facts stream as they land, and
  a ceiling kill is the named ``motion_timeout`` refusal CARRYING the samples
  already evaluated (fault-injected slow/dying/silent children, the
  ``_bounded_grind`` pattern).

Everything runs against real published artifacts (``_g9b``): anchors resolve
through the 8C path, forward kinematics places reloaded BReps, and the geom
primitives measure them — the numbers asserted are the fixture's pinned
mechanism facts, not mocks.
"""

from __future__ import annotations

import os
from pathlib import Path

import hephaestus.core.motion as motion_module
import pytest
from _g9b import (
    NOMINAL_RADIAL_AIR_MM,
    PADDLE_STOP_OVERLAP_MM3,
    REACH_MISS_AT_SMALL_ANGLES_MM,
    REACH_TARGET_MM,
    assumed,
    open_sweep_project,
)
from _sweep_children import (
    PID_FILE_ENV,
    STREAMED_SAMPLES,
    dying_child,
    grinding_child,
    silent_child,
)
from hephaestus.core.errors import AddressingError
from hephaestus.core.motion import (
    MOTION_TIMEOUT_ENV,
    MOTION_TIMEOUT_S,
    SWEEP_VERDICTS,
    MotionTimeout,
    SweepEvaluator,
    SweepResult,
    motion_timeout_s,
)
from hephaestus.core.project_store.kinematics import JointSet, MotionCheckSet
from hephaestus.core.project_store.layout import ProjectLayout

from opstore import OpStore


@pytest.fixture(scope="module")
def project(tmp_path_factory: pytest.TempPathFactory) -> tuple[ProjectLayout, OpStore]:
    layout, store = open_sweep_project(tmp_path_factory.mktemp("sweep-proj"))
    joints = JointSet(layout, store)
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
    return layout, store


@pytest.fixture(scope="module")
def evaluator(project: tuple[ProjectLayout, OpStore]) -> SweepEvaluator:
    return SweepEvaluator(*project)


@pytest.fixture(scope="module")
def checks(evaluator: SweepEvaluator) -> MotionCheckSet:
    return evaluator.checks


def one(evaluator: SweepEvaluator, check_id: str) -> SweepResult:
    """Evaluate exactly one check by id (the run still resolves once)."""
    results = evaluator.evaluate([check_id])
    assert [r.id for r in results] == [check_id]
    return results[0]


def assert_worst_facts(result: SweepResult) -> None:
    """The §4 record rule: worst-sample parameter values and measured value."""
    assert result.worst is not None
    assert result.worst.values, "worst sample must carry parameter values"
    assert isinstance(result.worst.measured, float)
    document = result.to_json()
    worst = document["worst"]
    assert isinstance(worst, dict)
    assert set(worst) == {"values", "measured"}
    assert document["samples_evaluated"] == result.samples_evaluated


# ==========================================================================
# the vocabulary is ONE closed set, stated once


def test_the_verdict_vocabulary_is_closed_and_spelled_exactly() -> None:
    assert SWEEP_VERDICTS == (
        "holds_at_samples",
        "satisfied",
        "not_reached_at_samples",
        "violated",
        "unresolvable",
    )


# ==========================================================================
# sweep_clearance: both sides of min_mm


class TestSweepClearance:
    def test_holds_at_samples_below_the_radial_air(
        self, evaluator: SweepEvaluator, checks: MotionCheckSet
    ) -> None:
        """Pin/bore air is 0.1 mm at every angle; a 0.05 mm floor holds — and
        the verdict says *at samples*, never "holds"."""
        checks.declare(
            {
                "id": "mc-clear-holds",
                "kind": "sweep_clearance",
                "a": "arm",
                "b": "base",
                "sweep": {"j-hinge": {"from": -10.0, "to": 10.0}},
                "min_mm": 0.05,
                "samples": 3,
                "provenance": {"requirement": "r-1"},
            }
        )
        result = one(evaluator, "mc-clear-holds")
        assert result.verdict == "holds_at_samples"
        assert result.samples_evaluated == result.grid_total == 3
        assert result.unit == "mm"
        assert result.worst is not None
        assert set(result.worst.values) == {"j-hinge"}
        assert result.worst.measured == pytest.approx(NOMINAL_RADIAL_AIR_MM, abs=1e-6)
        assert result.min_mm == 0.05
        assert_worst_facts(result)

    def test_violated_above_the_radial_air(
        self, evaluator: SweepEvaluator, checks: MotionCheckSet
    ) -> None:
        checks.declare(
            {
                "id": "mc-clear-viol",
                "kind": "sweep_clearance",
                "a": "arm",
                "b": "base",
                "sweep": {"j-hinge": {"from": -10.0, "to": 10.0}},
                "min_mm": 0.2,
                "samples": 3,
                "provenance": {"requirement": "r-1"},
            }
        )
        result = one(evaluator, "mc-clear-viol")
        assert result.verdict == "violated"
        assert result.worst is not None
        assert result.worst.measured == pytest.approx(NOMINAL_RADIAL_AIR_MM, abs=1e-6)
        assert result.worst.measured < 0.2
        assert_worst_facts(result)


# ==========================================================================
# sweep_no_interference: both sides (a clean swing, and the paddle-on-stop hit)


class TestSweepNoInterference:
    def test_holds_at_samples_over_the_clean_swing(
        self, evaluator: SweepEvaluator, checks: MotionCheckSet
    ) -> None:
        checks.declare(
            {
                "id": "mc-nointf-holds",
                "kind": "sweep_no_interference",
                "a": "arm",
                "b": "base",
                "sweep": {"j-hinge": {"from": -10.0, "to": 10.0}},
                "samples": 3,
                "provenance": assumed(),
            }
        )
        result = one(evaluator, "mc-nointf-holds")
        assert result.verdict == "holds_at_samples"
        assert result.unit == "mm3"
        assert result.worst is not None
        assert result.worst.measured == 0.0
        assert_worst_facts(result)

    def test_violated_where_the_paddle_meets_the_stop(
        self, evaluator: SweepEvaluator, checks: MotionCheckSet
    ) -> None:
        """One falsifying sample decides, and the worst sample IS the -90 deg
        one: the paddle lands footprint-identical on the stop (198 mm³)."""
        checks.declare(
            {
                "id": "mc-nointf-viol",
                "kind": "sweep_no_interference",
                "a": "arm",
                "b": "base",
                "sweep": {"j-hinge": {"from": -100.0, "to": -80.0}},
                "samples": 3,
                "provenance": assumed(),
            }
        )
        result = one(evaluator, "mc-nointf-viol")
        assert result.verdict == "violated"
        assert result.worst is not None
        assert result.worst.values == {"j-hinge": -90.0}
        assert result.worst.measured == pytest.approx(PADDLE_STOP_OVERLAP_MM3, rel=1e-6)
        assert_worst_facts(result)


# ==========================================================================
# reach: satisfied WITH achieving parameters, not-reached WITH the miss


class TestReach:
    def test_satisfied_carries_the_achieving_parameters(
        self, evaluator: SweepEvaluator, checks: MotionCheckSet
    ) -> None:
        """One sample touching the target IS proof: the -90 deg sample puts
        the paddle's outer face through the target plane."""
        checks.declare(
            {
                "id": "mc-reach-sat",
                "kind": "reach",
                "anchor": "arm",
                "target_point_mm": list(REACH_TARGET_MM),
                "tol_mm": 0.01,
                "sweep": {"j-hinge": {"from": -180.0, "to": 0.0}},
                "samples": 3,
                "provenance": {"requirement": "r-2"},
            }
        )
        result = one(evaluator, "mc-reach-sat")
        assert result.verdict == "satisfied"
        assert result.worst is not None
        assert result.worst.values == {"j-hinge": -90.0}  # the achieving sample
        assert result.worst.measured <= 0.01
        assert result.miss_mm is None
        assert_worst_facts(result)

    def test_not_reached_carries_the_closest_sample_and_the_miss_distance(
        self, evaluator: SweepEvaluator, checks: MotionCheckSet
    ) -> None:
        """Small swings never bring the arm near the +X target: the closest
        geometry is the pin surface at 11.1 mm, and the verdict says *at
        samples* — samples not reaching are evidence, not proof, and the
        result carries the closest sample's parameters and the miss."""
        checks.declare(
            {
                "id": "mc-reach-miss",
                "kind": "reach",
                "anchor": "arm",
                "target_point_mm": list(REACH_TARGET_MM),
                "tol_mm": 1.0,
                "sweep": {"j-hinge": {"from": -10.0, "to": 10.0}},
                "samples": 3,
                "provenance": {"requirement": "r-2"},
            }
        )
        result = one(evaluator, "mc-reach-miss")
        assert result.verdict == "not_reached_at_samples"
        assert result.worst is not None  # the CLOSEST sample
        assert set(result.worst.values) == {"j-hinge"}
        assert result.worst.measured == pytest.approx(REACH_MISS_AT_SMALL_ANGLES_MM, abs=1e-6)
        assert result.miss_mm == pytest.approx(REACH_MISS_AT_SMALL_ANGLES_MM - 1.0, abs=1e-6)
        assert_worst_facts(result)


# ==========================================================================
# the multi-joint grid: samples is per-axis, the total is the product


class TestMultiJointGrid:
    def test_the_grid_product_is_evaluated_and_the_worst_names_both_axes(
        self, evaluator: SweepEvaluator, checks: MotionCheckSet
    ) -> None:
        """2 per axis over two joints = 4 evaluated samples; the slider/base
        gap is 0.5 + travel, so the worst sample is travel 0 (the hinge axis
        cannot move the slider, and the tie goes to the first sample)."""
        checks.declare(
            {
                "id": "mc-grid",
                "kind": "sweep_clearance",
                "a": "slider",
                "b": "base",
                "sweep": {
                    "j-hinge": {"from": -10.0, "to": 10.0},
                    "j-slide": {"from": 0.0, "to": 2.0},
                },
                "min_mm": 1.0,
                "samples": 2,
                "provenance": assumed(),
            }
        )
        result = one(evaluator, "mc-grid")
        assert result.samples_evaluated == result.grid_total == 4
        assert result.samples_per_axis == 2
        assert result.verdict == "violated"
        assert result.worst is not None
        assert result.worst.values == {"j-hinge": -10.0, "j-slide": 0.0}
        assert result.worst.measured == pytest.approx(0.5, abs=1e-6)
        assert_worst_facts(result)


# ==========================================================================
# unresolvable: named, never skipped, partial evidence kept


class TestUnresolvable:
    def test_an_unbuilt_anchor_is_unresolvable_by_name(
        self, evaluator: SweepEvaluator, checks: MotionCheckSet
    ) -> None:
        checks.declare(
            {
                "id": "mc-unbuilt",
                "kind": "sweep_clearance",
                "a": "unbuilt",
                "b": "base",
                "sweep": {"j-hinge": {"from": -10.0, "to": 10.0}},
                "min_mm": 1.0,
                "samples": 2,
                "provenance": assumed(),
            }
        )
        result = one(evaluator, "mc-unbuilt")
        assert result.verdict == "unresolvable"
        assert result.reason == "no_current_build"
        assert result.detail is not None and "anchor a" in result.detail
        assert result.samples_evaluated == 0 and result.worst is None

    def test_a_joint_withdrawn_later_is_orphaned_sweep_naming_it(
        self, evaluator: SweepEvaluator, checks: MotionCheckSet
    ) -> None:
        """The orphaned_pose rule restated for sweeps: withdrawal is not a
        failure and does not erase the check — the check reports it, per-check,
        by name."""
        joints = evaluator.joints
        joints.declare(
            {
                "id": "j-aux",
                "kind": "revolute",
                "parent": "base:hinge_bore",
                "child": "unbuilt",
                "limits": {"min": -10.0, "max": 10.0},
                "provenance": assumed("temporary fixture joint"),
            }
        )
        checks.declare(
            {
                "id": "mc-orphan",
                "kind": "sweep_clearance",
                "a": "arm",
                "b": "base",
                "sweep": {"j-aux": {"from": -5.0, "to": 5.0}},
                "min_mm": 1.0,
                "samples": 2,
                "provenance": assumed(),
            }
        )
        joints.withdraw("j-aux", "the aux pivot was dropped from the design")
        result = one(evaluator, "mc-orphan")
        assert result.verdict == "unresolvable"
        assert result.reason == "orphaned_sweep"
        assert result.detail is not None and "j-aux" in result.detail

    def test_a_range_walking_out_of_limits_keeps_its_partial_samples(
        self, evaluator: SweepEvaluator, checks: MotionCheckSet
    ) -> None:
        """Limits are checked per sample and never clamped: the in-limits
        samples are measured and KEPT, the first offending one refuses by
        geom's own name, and the verdict stays unresolvable — partial
        evidence, never a pass over a partial grid."""
        checks.declare(
            {
                "id": "mc-limit",
                "kind": "sweep_clearance",
                "a": "arm",
                "b": "base",
                "sweep": {"j-hinge": {"from": 0.0, "to": 200.0}},
                "min_mm": 0.05,
                "samples": 3,
                "provenance": assumed(),
            }
        )
        result = one(evaluator, "mc-limit")
        assert result.verdict == "unresolvable"
        assert result.reason == "joint_limit_exceeded"
        assert result.samples_evaluated == 2  # 0 and 100 measured; 200 refused
        assert result.grid_total == 3
        assert result.worst is not None  # the partial samples' worst, kept
        assert result.worst.measured == pytest.approx(NOMINAL_RADIAL_AIR_MM, abs=1e-6)


# ==========================================================================
# selection: ids narrow, unknown ids refuse, withdrawn are never evaluated


class TestSelection:
    def test_an_unknown_id_is_an_addressing_error(self, evaluator: SweepEvaluator) -> None:
        with pytest.raises(AddressingError):
            evaluator.evaluate(["mc-ghost"])

    def test_a_withdrawn_check_is_never_evaluated(
        self, evaluator: SweepEvaluator, checks: MotionCheckSet
    ) -> None:
        checks.declare(
            {
                "id": "mc-retired",
                "kind": "sweep_clearance",
                "a": "arm",
                "b": "base",
                "sweep": {"j-hinge": {"from": -10.0, "to": 10.0}},
                "min_mm": 0.05,
                "samples": 2,
                "provenance": assumed(),
            }
        )
        checks.withdraw("mc-retired", "superseded by mc-clear-holds")
        assert evaluator.evaluate(["mc-retired"]) == ()


# ==========================================================================
# bounded execution: the ceiling, the streamed facts, the named refusal
# (fault-injected children, the COMPARE.md §5 test pattern verbatim)


#: Test ceiling for the fault-injected children (seconds). The deadline clock
#: starts at ``proc.start()``, so the ceiling must dominate the spawn
#: interpreter's bootstrap even on a loaded machine — a 2-3 s ceiling has been
#: observed losing that race under parallel suite runs, killing the child
#: before it could write its pid file (the death proof) or stream a sample.
#: The assertions are unchanged by the value; only the wait is.
TEST_CEILING_S = 10.0


def _assert_child_dead(pid_file: Path) -> None:
    """The killed subprocess must be gone — reaped by join, not orphaned."""
    pid = int(pid_file.read_text(encoding="utf-8"))
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def _timeout_probe_id(checks: MotionCheckSet) -> str:
    """A well-formed check the parent-side pre-resolution passes for."""
    if "mc-timeout-probe" not in checks.state().by_id:
        checks.declare(
            {
                "id": "mc-timeout-probe",
                "kind": "sweep_clearance",
                "a": "arm",
                "b": "base",
                "sweep": {"j-hinge": {"from": -10.0, "to": 10.0}},
                "min_mm": 0.05,
                "samples": 3,
                "provenance": assumed(),
            }
        )
    return "mc-timeout-probe"


class TestBoundedExecution:
    def test_a_ceiling_kill_is_a_named_refusal_carrying_the_streamed_samples(
        self,
        evaluator: SweepEvaluator,
        checks: MotionCheckSet,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """The §4 sentence executable: a grinder that streamed two per-sample
        facts is killed at the (env-overridden) deadline; the refusal is
        ``motion_timeout`` CARRYING those samples, and the subprocess is
        provably dead."""
        check_id = _timeout_probe_id(checks)
        pid_file = tmp_path / "child.pid"
        monkeypatch.setattr(motion_module, "_sweep_child", grinding_child)
        monkeypatch.setenv(MOTION_TIMEOUT_ENV, str(TEST_CEILING_S))
        monkeypatch.setenv(PID_FILE_ENV, str(pid_file))

        with pytest.raises(MotionTimeout) as excinfo:
            evaluator.evaluate([check_id])

        refusal = excinfo.value
        assert refusal.reason == "motion_timeout"
        assert refusal.check_id == check_id
        assert refusal.timeout_s == TEST_CEILING_S  # the env override, resolved per call
        assert refusal.samples_evaluated == 2
        assert refusal.grid_total == 3
        assert [(dict(s.values), s.measured) for s in refusal.partial] == STREAMED_SAMPLES
        document = refusal.to_json()
        assert document["status"] == "motion_timeout"
        assert document["samples_evaluated"] == 2
        partial = document["partial"]
        assert isinstance(partial, list) and len(partial) == 2
        assert "2 of 3" in refusal.message
        _assert_child_dead(pid_file)

    def test_a_child_death_is_the_same_named_refusal_with_the_facts_kept(
        self,
        evaluator: SweepEvaluator,
        checks: MotionCheckSet,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        check_id = _timeout_probe_id(checks)
        pid_file = tmp_path / "child.pid"
        monkeypatch.setattr(motion_module, "_sweep_child", dying_child)
        monkeypatch.setenv(PID_FILE_ENV, str(pid_file))

        with pytest.raises(MotionTimeout) as excinfo:
            evaluator.evaluate([check_id], timeout_s=120.0)

        refusal = excinfo.value
        assert "died" in refusal.message and "exit code 7" in refusal.message
        assert refusal.samples_evaluated == 2
        assert [(dict(s.values), s.measured) for s in refusal.partial] == STREAMED_SAMPLES
        _assert_child_dead(pid_file)

    def test_a_silent_child_carries_zero_samples_not_a_guess(
        self,
        evaluator: SweepEvaluator,
        checks: MotionCheckSet,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        check_id = _timeout_probe_id(checks)
        pid_file = tmp_path / "child.pid"
        monkeypatch.setattr(motion_module, "_sweep_child", silent_child)
        monkeypatch.setenv(PID_FILE_ENV, str(pid_file))

        with pytest.raises(MotionTimeout) as excinfo:
            evaluator.evaluate([check_id], timeout_s=TEST_CEILING_S)

        refusal = excinfo.value
        assert refusal.partial == ()
        assert refusal.samples_evaluated == 0
        assert "0 of 3" in refusal.message
        _assert_child_dead(pid_file)

    def test_the_ceiling_is_env_overridable_and_falls_back_on_nonsense(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(MOTION_TIMEOUT_ENV, raising=False)
        assert motion_timeout_s() == MOTION_TIMEOUT_S == 300.0
        monkeypatch.setenv(MOTION_TIMEOUT_ENV, "17.5")
        assert motion_timeout_s() == 17.5
        monkeypatch.setenv(MOTION_TIMEOUT_ENV, "not-a-number")
        assert motion_timeout_s() == MOTION_TIMEOUT_S
