# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""G6: corpus v1 — twelve tasks, twelve passing reference solutions, one bound.

Two gate obligations live here.

*The corpus itself.* mission_plan.md Stage 6 expands the corpus to **12 tasks**
(public/private split maintained, including a DFM-repair task and a drawing
task) and verification.md Tier 3 makes every task answerable: *"a task no
reference solution passes is a broken task, not a hard task"*. So each of the
twelve is seeded fresh, has its reference solution overlaid, and is graded by
the same path a benchmarked model run is graded by — checks, exports, renders,
DFM verdicts and drawing sheets.

*The bound, not the measurement.* The G6 clause "bench on corpus v1 lower-90%
Wilson bound >= 0.70 (12 tasks x >= 3 seeds) with the reference model" needs a
live model and is the orchestrator's step; it is deliberately **not** run here.
What is asserted here is the plumbing that step is read through: covering corpus
v1 makes the gated prose split's threshold 0.70, the seeded split still carries
no threshold, and ``meets_gate`` is decided against that number.

Tasks whose acceptance re-runs a DFM rule pack execute registry content and so
need a probed secure sandbox; on a machine without one they skip rather than
grade a clause they cannot evaluate.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import pytest
from hephaestus.bench.harness import (
    BenchTask,
    corpus_solutions_dir,
    grade_reference_solution,
    load_tasks,
    task_ids,
)
from hephaestus.bench.scoring import (
    COMPONENT_FAMILY_TASKS,
    FAMILY_COMPONENT,
    G2_AGGREGATE_THRESHOLD,
    G6_AGGREGATE_THRESHOLD,
    aggregate_threshold,
    score_records,
    task_family,
)
from hephaestus.core.executor.sandbox.bwrap import find_bwrap

#: The public corpus as it stands: the twelve tasks corpus v1 is
#: (mission_plan.md Stage 6 — what the G6 clause was measured over) plus the
#: four corpus-v2 additions (2026-08-25 operator decision, recorded in
#: mission_plan.md's Stage 6 status): the ingest pair ``flange-edit`` and
#: ``plate-from-drawing`` (INGEST.md §2) and the assembly pair ``hinge-mate``
#: and ``shaft-coupler`` (ASSEMBLY.md §3). The G6 evidence is unchanged — v2
#: is a superset, and ``aggregate_threshold`` still reads 0.70 off the v1
#: coverage below. Repointed 2026-08-27 (Stage 9C, KINEMATICS.md §6 corpus
#: v3): the mechanism additions ``gripper-jaws``, ``hinge-travel`` and
#: ``leadscrew-actuator`` bring the public corpus to nineteen — the count
#: moved, the clause did not, and ``aggregate_threshold`` still keys 0.70 on
#: the v1 coverage. Repointed again 2026-08-29 (Stage 11, PARTS_STORE.md G11C
#: clause 13, "corpus-count pins repointed with this stage cited"): the
#: component-bearing pair ``bearing-shaft`` and ``motor-plate`` brings it to
#: twenty-one. Same clause, same 0.70 bar on the same v1 coverage — G11C
#: clause 12 keeps the component family in its OWN split for exactly that
#: reason.
CORPUS_SIZE = 21

#: The Stage 6 additions the clause names by role.
DFM_REPAIR_TASK = "dfm-repair"
DRAWING_TASK = "drawing-shelf"


@pytest.fixture(scope="module")
def tasks() -> Mapping[str, BenchTask]:
    """Every corpus task, loaded once — the spec parse is itself a validation."""
    return {task.id: task for task in load_tasks()}


def _prose(tasks: Mapping[str, BenchTask]) -> list[BenchTask]:
    return [task for task in tasks.values() if task.spec == "prose"]


# ==========================================================================
# the corpus loads, and it is corpus v1


def test_the_public_corpus_loads_with_a_reference_solution_each(
    tasks: Mapping[str, BenchTask],
) -> None:
    """Repointed 2026-08-25 (corpus v2) and 2026-08-27 (Stage 9C corpus v3).

    The clause this test pins — every public task loads and has a reference
    solution — is unchanged; only the count moved: sixteen with the corpus-v2
    additions (the ingest pair and the assembly pair), nineteen with the
    corpus-v3 mechanism tasks (KINEMATICS.md §6), twenty-one with the
    corpus-v4 component pair (2026-08-29, PARTS_STORE.md G11C clause 13). The
    v1 dozen the G6 measurement stands on are all still present (the
    meta-suite asserts the subset).
    """
    prose = _prose(tasks)
    assert len(prose) == CORPUS_SIZE
    assert {task.id for task in prose} == set(task_ids(specs=("prose",)))
    for task in prose:
        assert task.prompt.strip(), f"{task.id}: a task with no prompt cannot be run"
        assert task.budget_tool_calls > 0
        assert task.required_checks, f"{task.id}: a task with no checks cannot be graded"
        assert (corpus_solutions_dir() / task.id).is_dir(), f"{task.id}: no reference solution"

    # The public/private split is maintained: every public task also ships its
    # seeded variant, and the two are never collapsed into one split.
    assert set(task_ids(specs=("seeded",))) == {f"{task.id}@seeded" for task in prose}


def test_the_expansion_includes_a_dfm_repair_task_and_a_drawing_task(
    tasks: Mapping[str, BenchTask],
) -> None:
    """The two named Stage 6 additions exist and really assert their subject."""
    repair = tasks[DFM_REPAIR_TASK]
    assert repair.dfm, "the DFM-repair task must carry a DFM requirement"
    assert {rule for req in repair.dfm for rule in req.clean_rules}, "no rule is required clean"

    drawing = tasks[DRAWING_TASK]
    assert drawing.drawings, "the drawing task must carry a drawing requirement"
    required = set(drawing.drawings[0].required_texts)
    # The G6 clause: the five principal dimensions in the extracted PDF text.
    assert {"600.0", "250.0", "218.0", "18.0", "Ø8.0"} <= required
    # …and *only* dimensions. The 2026-07-26 corpus audit removed a title-block
    # sentence from this set: a drawing requirement gates what the shop reads off
    # the sheet, never the wording of the sheet. The manufacturing metadata it
    # used to carry is gated structurally instead — the free-text material spec
    # must resolve in the materials registry, so any wording naming the right
    # stock passes and a wrong stock does not.
    assert not any(" " in text for text in required), (
        f"{DRAWING_TASK}: required drawing texts must be dimensions, not prose: {required}"
    )
    assert drawing.metadata, "the drawing task must gate its manufacturing metadata"
    requirement = drawing.metadata[0]
    assert requirement.part == "shelf"
    assert requirement.material_id == "plywood-baltic-birch"
    assert requirement.process == "laser_cut"
    assert "material_spec" in requirement.required_fields


# ==========================================================================
# every reference solution passes its own checks


@pytest.mark.parametrize("task_id", sorted(task_ids(specs=("prose",))))
def test_every_reference_solution_passes_its_own_task(
    task_id: str, tasks: Mapping[str, BenchTask], tmp_path: Path
) -> None:
    task = tasks[task_id]
    if task.dfm and (sys.platform != "linux" or find_bwrap() is None):
        pytest.skip("DFM acceptance re-runs registry content, which needs a probed sandbox")

    report = grade_reference_solution(task, tmp_path / "project")

    assert report.passed, f"{task_id} reference solution failed: {report.reasons}"
    assert report.check_status == "ok"
    assert report.checks, f"{task_id}: the required checks produced no results"
    for name, value in report.checks.items():
        entry = cast("Mapping[str, Any]", value)
        assert entry.get("pass") is True, f"{task_id}: check {name} did not pass: {entry}"
    # A reference solution never edits a protected task file to pass.
    assert report.restored_protected == ()
    # Every declared deliverable of the task really was produced and accepted.
    assert len(report.exports) == len(task.exports)
    assert len(report.renders) == len(task.renders)
    assert len(report.dfm) == len(task.dfm)
    assert len(report.drawings) == len(task.drawings)
    for record in report.dfm:
        assert "error" not in record, record
    for record in report.drawings:
        assert record.get("missing_texts") == [], record


# ==========================================================================
# the threshold plumbing (the measurement is the orchestrator's step)


def test_covering_corpus_v1_reads_the_prose_threshold_as_070() -> None:
    prose = task_ids(specs=("prose",))
    assert aggregate_threshold(prose) == pytest.approx(0.70)
    assert pytest.approx(0.70) == G6_AGGREGATE_THRESHOLD
    # …and a v0-only archive is still read at the corpus-v0 bound, so the
    # tightening is a property of what was measured, never of the file's age.
    v0 = [
        task
        for task in prose
        if task not in {"dfm-repair", "drawing-shelf", "nest-gusset", "print-bracket"}
    ]
    assert aggregate_threshold(v0) == pytest.approx(G2_AGGREGATE_THRESHOLD)


def test_a_corpus_v1_archive_is_gated_against_070_on_the_prose_split_alone(
    tasks: Mapping[str, BenchTask],
) -> None:
    """The G6 statistic is the prose split's; seeded runs cannot move it.

    **Repointed 2026-08-29**, citing ``PARTS_STORE.md`` Gate G11C clause 12's
    amendment (and item 34), which is where a corpus *family* was introduced.
    Stage 11 added ``bearing-shaft`` and ``motor-plate`` to the public corpus,
    and the clause forbids averaging them into the v1/v2 baselines — so their
    runs are carved out of the gated prose split into ``component-prose``. The
    gate's shape is therefore every public task **outside a declared family** x
    3 seeds; the number this asserts moved because the corpus grew under a rule
    that says it must not move the bar, which is the amendment working.

    The pin is strengthened rather than relaxed in the same edit: the carved-out
    runs are followed to where they went, so "not in the gate" can never quietly
    become "not measured at all".
    """
    prose = sorted(task_ids(specs=("prose",)))
    gated = sorted(task for task in prose if task_family(task) is None)
    assert set(prose) - set(gated) == set(COMPONENT_FAMILY_TASKS), (
        "the only tasks outside the gated split are the declared component family"
    )
    records: list[dict[str, Any]] = []
    for task_id in prose:
        for seed in (1, 2, 3):
            records.append(
                {
                    "task_id": task_id,
                    "spec": "prose",
                    "seed": seed,
                    "passed": True,
                    "model": "reference-model",
                    "date": "2026-07-26",
                    "tool_calls": 5,
                    "budget_tool_calls": tasks[task_id].budget_tool_calls,
                }
            )
    score = score_records(records)

    assert score.threshold == pytest.approx(0.70)
    assert score.n == len(gated) * 3, (
        "every public task outside a declared family x 3 seeds is the gate's own shape "
        "(PARTS_STORE.md G11C clause 12, amended 2026-08-29)"
    )
    assert score.prose.threshold == pytest.approx(0.70)
    assert score.splits["seeded"].threshold is None, "the seeded split gates nothing"
    assert score.meets_gate is (score.wilson_lower_90 >= 0.70)
    # Carved out, not dropped: the family's runs are all present, in their own
    # thresholdless split, and the archive total still accounts for every one.
    family = score.family_split(FAMILY_COMPONENT, "prose")
    assert family.n == len(COMPONENT_FAMILY_TASKS) * 3
    assert family.threshold is None and family.meets_threshold is None
    assert score.n_total == len(prose) * 3


def test_the_gate_bound_is_not_satisfied_by_a_mediocre_corpus_v1_archive() -> None:
    """A negative control: 0.70 is a real bar, not a formality the plumbing passes."""
    prose = sorted(task_ids(specs=("prose",)))
    records = [
        {
            "task_id": task_id,
            "spec": "prose",
            "seed": seed,
            "passed": seed == 1,  # one run in three
            "model": "reference-model",
            "date": "2026-07-26",
        }
        for task_id in prose
        for seed in (1, 2, 3)
    ]
    score = score_records(records)
    assert score.threshold == pytest.approx(0.70)
    assert score.aggregate == pytest.approx(1 / 3, abs=1e-6)
    assert not score.meets_gate
