# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""G8D addendum (``EXTERNAL_EVAL.md`` §5): the editing-harness fixes.

Two of the four fixes live at surfaces this suite owns:

* **deliverable-scoped grading** — a converted task names its deliverable
  (``candidate``), and the grader fails on THAT part's build/export only: a
  broken scratch part plus an ok candidate passes, with the scratch failure
  recorded as a fact under the grade's non-charging key. Corpus grading is
  untouched — the same project graded without a deliverable still fails.
* **the calibrated editing budget** — editing samples convert with the
  measured 100-call budget; generation keeps 60; an explicit override wins.

(The uncharged harness-fault call and the archived sidecar evidence are proven
unit-level in ``server/tests/test_bench_harness_faults.py`` /
``test_supervisor_evidence.py``, colocated with the guard and the supervisor,
and end-to-end — on real FakeModel runs — in ``test_g8d_harness_run.py``;
the from-archive salvage in ``test_g8d_salvage.py``.)
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

from _g8d import DATASET
from hephaestus.bench import harness
from hephaestus.bench.cadgenbench import (
    DEFAULT_BUDGET_TOOL_CALLS,
    EDITING_BUDGET_TOOL_CALLS,
    PART_NAME,
    convert_sample,
    load_sample,
)

CANDIDATE_SRC = "# The plate the drawing shows.\npart.geometry = Box(20.0, 10.0, 4.0)\n"
SCRATCH_SRC = '# A probe the model used and abandoned.\nraise RuntimeError("scratch probe")\n'


# --------------------------------------------------------------------------
# the calibrated editing budget (measured, not guessed)


def test_editing_samples_convert_with_the_calibrated_budget(tmp_path: Path) -> None:
    """Editing gets the measured 100 (2026-07-29 distribution); generation keeps 60."""
    generation = convert_sample(load_sample(DATASET / "101"), tmp_path / "tasks")
    editing = convert_sample(load_sample(DATASET / "201"), tmp_path / "tasks")

    assert generation.budget_tool_calls == DEFAULT_BUDGET_TOOL_CALLS == 60
    assert editing.budget_tool_calls == EDITING_BUDGET_TOOL_CALLS == 100


def test_an_explicit_budget_overrides_both_splits(tmp_path: Path) -> None:
    generation = convert_sample(load_sample(DATASET / "101"), tmp_path / "g", budget_tool_calls=7)
    editing = convert_sample(load_sample(DATASET / "201"), tmp_path / "e", budget_tool_calls=7)

    assert generation.budget_tool_calls == editing.budget_tool_calls == 7


# --------------------------------------------------------------------------
# deliverable-scoped grading


def test_a_converted_task_declares_its_deliverable(tmp_path: Path) -> None:
    """The converter marks ``candidate``; the strict loader carries it through."""
    task = convert_sample(load_sample(DATASET / "101"), tmp_path / "tasks")

    assert task.deliverable == PART_NAME
    spec = json.loads((task.directory / "task.json").read_text(encoding="utf-8"))
    assert spec["deliverable"] == PART_NAME


def test_a_broken_scratch_part_is_a_fact_not_a_fail_reason(tmp_path: Path) -> None:
    """§5's gate clause: broken scratch part + ok candidate ⇒ pass, failure recorded."""
    task = convert_sample(load_sample(DATASET / "101"), tmp_path / "tasks")
    project = tmp_path / "project"
    harness.seed_project(task, project)
    (project / "parts" / f"{PART_NAME}.py").write_text(CANDIDATE_SRC, encoding="utf-8")
    (project / "parts" / "scratch.py").write_text(SCRATCH_SRC, encoding="utf-8")

    report = harness.grade(task, project)

    assert report.passed, report.reasons
    # The scratch failure is written down — as a fact, outside the reasons.
    assert "build_failed:scratch" in report.other_build_failures
    assert not any("scratch" in reason for reason in report.reasons)
    document = report.to_json()
    assert document["other_build_failures"] == ["build_failed:scratch"]
    # …and the deliverable's export still came out of the graded geometry.
    export = cast("dict[str, Any]", document["exports"][0])
    assert "invalid" not in export and "error" not in export


def test_without_a_deliverable_the_same_project_still_fails(tmp_path: Path) -> None:
    """Corpus grading is untouched: no deliverable means every part is graded."""
    task = convert_sample(load_sample(DATASET / "101"), tmp_path / "tasks")
    corpus_scope = replace(task, deliverable=None)
    project = tmp_path / "project"
    harness.seed_project(corpus_scope, project)
    (project / "parts" / f"{PART_NAME}.py").write_text(CANDIDATE_SRC, encoding="utf-8")
    (project / "parts" / "scratch.py").write_text(SCRATCH_SRC, encoding="utf-8")

    report = harness.grade(corpus_scope, project)

    assert not report.passed
    assert "build_failed:scratch" in report.reasons
    assert report.other_build_failures == ()


def test_a_deliverable_that_was_never_authored_fails_by_name(tmp_path: Path) -> None:
    """Scoping the grade to one part must not let 'no part at all' pass."""
    task = convert_sample(load_sample(DATASET / "101"), tmp_path / "tasks")
    project = tmp_path / "project"
    harness.seed_project(task, project)
    (project / "parts" / "scratch.py").write_text(SCRATCH_SRC, encoding="utf-8")

    report = harness.grade(task, project)

    assert not report.passed
    assert f"deliverable_not_authored:{PART_NAME}" in report.reasons
