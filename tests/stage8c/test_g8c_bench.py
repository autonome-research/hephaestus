"""G8C: an external scorer grading an assembly on its declared fits.

Gate clause: *a bench task with declared constraints graded through the engine
path*.

``ASSEMBLY.md`` §3's promise is that an assembly task scores on **declared fits
holding**, not on a volume window — so the grader has to reach the same
``AssemblyEvaluator`` the ``check_assembly`` tool reaches, over the run's real
published artifacts, and produce the same three states. That is exactly what is
asserted here: the same project graded against three different task
declarations, with the verdict changing only because the task's claim changed.

The other half of the clause is whose claim is graded. The entries are the
TASK's, installed over whatever the run declared — the rule the required CHECKS
already follow, and for the same reason: a run that declares a weaker mate (or
none at all) must not be able to score on it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from _g8c import declare
from hephaestus.bench.harness import BenchTask, grade
from hephaestus.testing.tools_fixture import Project

#: The register fit as an acceptance constraint: the boss must clear the bore by
#: 0.05-0.25 mm. The fixture's geometry measures 0.15 mm.
FIT_ENTRY: dict[str, Any] = {
    "id": "c-register-fit",
    "kind": "fit",
    "a": "base:register_slot",
    "b": "lid:register_wall",
    "min_mm": 0.05,
    "max_mm": 0.25,
}


def task_with(directory: Path, *requirements: Mapping[str, Any]) -> BenchTask:
    """One bench task whose whole acceptance spec is its declared constraints."""
    (directory / "checks").mkdir(parents=True, exist_ok=True)
    spec: dict[str, Any] = {
        # A task's id is its directory name (the harness pins the two together).
        "id": directory.name,
        "prompt": "a lid that registers into a base with a slip fit",
        "budget_tool_calls": 50,
        "constraint_requirements": [dict(requirement) for requirement in requirements],
    }
    (directory / "task.json").write_text(json.dumps(spec), encoding="utf-8")
    return BenchTask.load(directory)


def outcomes(report: Any) -> dict[str, str]:
    """``{constraint id: state}`` out of the grade report's constraint records."""
    out: dict[str, str] = {}
    for record in cast("Sequence[Mapping[str, Any]]", report.constraints):
        entry = cast("Mapping[str, Any]", cast("Mapping[str, Any]", record["requirement"])["entry"])
        outcome = record.get("outcome")
        out[str(entry["id"])] = (
            str(cast("Mapping[str, Any]", outcome)["state"]) if outcome is not None else "error"
        )
    return out


def test_a_task_declared_fit_is_graded_through_the_engine(pair: Project, tmp_path: Path) -> None:
    """The scorer measures the mate itself, and says what it measured."""
    pair.close()  # grading opens the project on its own

    report = grade(task_with(tmp_path / "ok", {"entry": FIT_ENTRY}), pair.root)

    assert outcomes(report) == {"c-register-fit": "satisfied"}
    assert [reason for reason in report.reasons if reason.startswith("constraint_")] == []
    # The residual rides along in the report, so a score is auditable without
    # re-running anything: 0.15 mm against the declared window.
    record = cast("Mapping[str, Any]", report.constraints[0])
    residual = cast("Mapping[str, Any]", cast("Mapping[str, Any]", record["outcome"])["residual"])
    assert abs(float(cast("Any", residual["measured"])) - 0.15) < 1e-9
    # The task's own provenance is recorded: an acceptance constraint is the
    # task's assumption, never a citation of a requirement the project lacks.
    entry = cast("Mapping[str, Any]", cast("Mapping[str, Any]", record["requirement"])["entry"])
    assert entry["id"] == "c-register-fit"


def test_a_fit_the_geometry_misses_fails_the_run_by_name(pair: Project, tmp_path: Path) -> None:
    pair.close()

    tight = dict(FIT_ENTRY, min_mm=0.30, max_mm=0.40)
    report = grade(task_with(tmp_path / "tight", {"entry": tight}), pair.root)

    assert outcomes(report) == {"c-register-fit": "violated"}
    assert report.passed is False
    # The reason names the failure AND the measurement behind it, so a bench
    # result is diagnosable without opening the project.
    reason = next(r for r in report.reasons if r.startswith("constraint_violated:"))
    assert reason.startswith("constraint_violated:c-register-fit:0.15")


def test_a_mate_that_cannot_be_measured_is_not_scored_as_a_failure_of_geometry(
    pair: Project, tmp_path: Path
) -> None:
    """The third state survives the scorer: unresolvable has its own reason token."""
    pair.close()

    dangling = dict(FIT_ENTRY, b="lid:no_such_tag")
    report = grade(task_with(tmp_path / "dangling", {"entry": dangling}), pair.root)

    assert outcomes(report) == {"c-register-fit": "unresolvable"}
    assert report.passed is False
    assert any(
        reason.startswith("constraint_unresolvable:c-register-fit:dangling_selector")
        for reason in report.reasons
    ), report.reasons
    assert not any(reason.startswith("constraint_violated:") for reason in report.reasons)


def test_the_task_owns_the_acceptance_constraint_the_run_does_not(
    pair: Project, tmp_path: Path
) -> None:
    """A run cannot pass by declaring a mate it trivially meets under the same id."""
    declare(
        pair,
        "c-register-fit",
        "fit",
        "base:register_slot",
        "lid:register_wall",
        min_mm=0.0,
        max_mm=100.0,
    )
    pair.close()

    tight = dict(FIT_ENTRY, min_mm=0.30, max_mm=0.40)
    report = grade(task_with(tmp_path / "replaced", {"entry": tight}), pair.root)

    assert outcomes(report) == {"c-register-fit": "violated"}
    assert report.passed is False


def test_a_task_may_require_that_a_mate_be_checkable(pair: Project, tmp_path: Path) -> None:
    """``expect`` is spelled out, because "could not measure" is a real outcome.

    A task that declares ``expect: "unresolvable"`` is asserting the absence of
    evidence, and the grader scores it as declared rather than treating an
    unmeasurable mate as a quiet pass anywhere else.
    """
    pair.close()

    dangling = dict(FIT_ENTRY, b="lid:no_such_tag")
    report = grade(
        task_with(tmp_path / "expected", {"entry": dangling, "expect": "unresolvable"}), pair.root
    )

    assert outcomes(report) == {"c-register-fit": "unresolvable"}
    assert [reason for reason in report.reasons if reason.startswith("constraint_")] == []
