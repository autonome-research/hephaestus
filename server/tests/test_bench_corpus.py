"""The corpus meta-test: every public task is validated by a reference solution.

verification.md Tier 3 / digest §8: *"Every task must be validated by a
``solutions/`` reference implementation passing its own checks in CI — a task no
reference solution passes is a broken task, not a hard task."* These tests are
that rule, executed. For each of the eight public v0 tasks they seed a fresh
project from ``corpus/tasks/<id>/seed/``, overlay ``corpus/solutions/<id>/``
(scripts and/or a ``params.json`` applied through the real ``set_params`` path),
and run the *same* grading path a benchmarked model run is graded by: build every
part, install the task's required CHECKS, run them project-scoped, then validate
the required exports and renders.

They also pin the corpus itself: the eight ids and their tool-call budgets are the
ones the digest fixes, and ``repair-fillet`` is the task the gate requires perfect.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import pytest
from hephaestus.bench.harness import (
    BenchTask,
    corpus_solutions_dir,
    grade_reference_solution,
    load_tasks,
    restore_protected,
    seed_project,
    seeded_prompt,
    task_ids,
)
from hephaestus.bench.scoring import PERFECT_TASKS

#: The public corpus v0, difficulty-ordered with the budgets fixed by
#: ``agent/STAGE2_DIGEST.md`` §8 / ``verification.md`` Tier 3.
CORPUS: tuple[tuple[str, int], ...] = (
    ("bracket-101", 20),
    ("sheet-box", 32),
    ("cat-step", 52),
    ("store-hardware", 27),
    ("repair-fillet", 12),
    ("param-retune", 10),
    ("knob-loft", 26),
    ("enclosure-bosses", 38),
)

#: A single reference solution must build and grade well inside this; the digest's
#: working budget is 30 s per solution build, and the whole grading pass (build +
#: checks + exports + renders) is measured here with generous headroom so the
#: assertion catches a pathological regression, not CI jitter.
GRADE_SECONDS_CEILING = 120.0


@pytest.fixture(scope="session")
def tasks() -> Mapping[str, BenchTask]:
    """Every corpus task, loaded once (the spec parse is itself a validation)."""
    return {task.id: task for task in load_tasks()}


def test_corpus_is_the_eight_public_tasks() -> None:
    prose = {task_id for task_id, _ in CORPUS}
    # The historically baselined split is still exactly the eight public tasks…
    assert set(task_ids(specs=("prose",))) == prose
    # …and VALIDATION.md §1 ships each of them a second time as a seeded variant,
    # never collapsed into the prose split.
    assert set(task_ids(specs=("seeded",))) == {f"{task_id}@seeded" for task_id in prose}
    assert set(task_ids()) == prose | {f"{task_id}@seeded" for task_id in prose}


@pytest.mark.parametrize(("task_id", "_budget"), CORPUS)
def test_seeded_variant_installs_the_acceptance_checks_as_a_protected_spec(
    task_id: str, _budget: int, tasks: Mapping[str, BenchTask], tmp_path: Path
) -> None:
    """VALIDATION.md §1: seeded seeds ``checks/``; prose must not."""
    prose = tasks[task_id]
    seeded = tasks[f"{task_id}@seeded"]

    assert prose.spec == "prose" and seeded.spec == "seeded"
    # Same task: same prompt, same budget, same acceptance checks.
    assert (seeded.prompt, seeded.budget_tool_calls) == (prose.prompt, prose.budget_tool_calls)
    assert seeded.required_checks == prose.required_checks
    assert seeded.base_id == prose.id

    prose_root = seed_project(prose, tmp_path / "prose")
    seeded_root = seed_project(seeded, tmp_path / "seeded")
    assert list((prose_root / "checks").glob("*.py")) == [], "a prose task must seed no spec"
    for name in seeded.required_checks:
        installed = seeded_root / "checks" / f"{name}.py"
        assert installed.is_file()
        assert installed.read_text(encoding="utf-8") == seeded.check_sources()[name]
        assert f"checks/{name}.py" in seeded.protected_paths

    # Tampering with the seeded spec is restored (and reported for §8 scoring).
    target = seeded_root / "checks" / f"{seeded.required_checks[0]}.py"
    target.write_text("CHECKS = {}\n", encoding="utf-8")
    assert restore_protected(seeded, seeded_root) == [f"checks/{seeded.required_checks[0]}.py"]
    assert target.read_text(encoding="utf-8") == seeded.check_sources()[seeded.required_checks[0]]
    assert restore_protected(prose, prose_root) == []


@pytest.mark.parametrize(("task_id", "budget"), CORPUS)
def test_task_spec_matches_the_digest(
    task_id: str, budget: int, tasks: Mapping[str, BenchTask]
) -> None:
    task = tasks[task_id]
    assert task.budget_tool_calls == budget
    assert task.required_checks, f"{task_id}: a task with no required checks cannot be graded"
    # Every required CHECKS file resolves (BenchTask.load already fails fast, but
    # this keeps the intent explicit) and every protected path is really seeded.
    assert set(task.check_sources()) == set(task.required_checks)
    for rel in task.protected_paths:
        assert (task.seed_dir / rel).is_file(), f"{task_id}: protected {rel} is not in seed/"
    assert (corpus_solutions_dir() / task_id).is_dir(), f"{task_id}: no reference solution"


def test_repair_fillet_is_the_gate_perfect_task() -> None:
    assert PERFECT_TASKS == ("repair-fillet",)


def test_seeded_prompts_are_deterministic_and_requirement_free(
    tasks: Mapping[str, BenchTask],
) -> None:
    for task in tasks.values():
        for seed in (1, 2, 3):
            prompt = seeded_prompt(task, seed)
            assert prompt == seeded_prompt(task, seed), "seeded prompts must be deterministic"
            assert prompt.startswith(task.prompt.rstrip())
        # Seeds vary the closing instruction, never the task requirements.
        variants = {seeded_prompt(task, seed) for seed in range(1, 12)}
        assert len(variants) > 1, f"{task.id}: seeds do not vary the prompt at all"


@pytest.mark.parametrize(("task_id", "_budget"), CORPUS)
def test_reference_solution_passes_its_own_checks(
    task_id: str, _budget: int, tasks: Mapping[str, BenchTask], tmp_path: Path
) -> None:
    task = tasks[task_id]
    started = time.monotonic()
    report = grade_reference_solution(task, tmp_path / "project")
    elapsed = time.monotonic() - started

    assert report.passed, f"{task_id} reference solution failed: {report.reasons}"
    assert report.check_status == "ok"
    assert report.checks, f"{task_id}: the required checks produced no results"
    for name, value in report.checks.items():
        entry = cast("Mapping[str, Any]", value)
        assert entry.get("pass") is True, f"{task_id}: check {name} did not pass: {entry}"
    # Nothing in a reference solution may touch a protected task file.
    assert report.restored_protected == ()
    # Every declared export/render really was produced from the graded geometry.
    assert len(report.exports) == len(task.exports)
    for record in report.exports:
        assert "invalid" not in record, record
        assert int(cast("int", record.get("bytes", 0))) > 0
    assert len(report.renders) == len(task.renders)
    for record in report.renders:
        assert record.get("status") == "ok", record
        assert record.get("render_artifact_refs"), record
    assert elapsed < GRADE_SECONDS_CEILING, f"{task_id}: grading took {elapsed:.1f}s"


def test_export_and_render_requirements_are_covered_by_the_corpus(
    tasks: Mapping[str, BenchTask],
) -> None:
    """The corpus must exercise the export and render halves of the grader."""
    formats = {req.fmt for task in tasks.values() for req in task.exports}
    assert {"step", "dxf", "3mf"} <= formats
    profile_counts = [req.profile_count for task in tasks.values() for req in task.exports]
    assert 5 in profile_counts, "sheet-box must require the 5-profile as_built DXF"
    sections = [
        req.section_plane for task in tasks.values() for req in task.renders if req.section_plane
    ]
    assert "+Z@c" in sections, "enclosure-bosses must require the +Z midplane section"
