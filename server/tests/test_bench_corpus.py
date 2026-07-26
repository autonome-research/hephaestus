"""The corpus meta-test: every public task is validated by a reference solution.

verification.md Tier 3 / digest §8: *"Every task must be validated by a
``solutions/`` reference implementation passing its own checks in CI — a task no
reference solution passes is a broken task, not a hard task."* These tests are
that rule, executed. For each of the **twelve** public tasks they seed a fresh
project from ``corpus/tasks/<id>/seed/``, overlay ``corpus/solutions/<id>/``
(scripts and/or a ``params.json`` applied through the real ``set_params`` path),
and run the *same* grading path a benchmarked model run is graded by: build every
part, install the task's required CHECKS, run them project-scoped, then validate
the required exports, renders, DFM verdicts and drawing sheets.

They also pin the corpus itself: the twelve ids and their tool-call budgets are
the ones the digest (v0) and mission_plan.md Stage 6 (v1) fix, ``repair-fillet``
is the task the gate requires perfect, and covering corpus v1 is what raises the
aggregate Wilson bound from 0.60 to G6's 0.70 on the gated prose split.
"""

from __future__ import annotations

import io
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import pytest
from hephaestus.agent_bridge.cad_ops import dimension_text
from hephaestus.agent_bridge.cad_ops._drawing import Sheet, sheet_to_pdf
from hephaestus.bench.harness import (
    BenchTask,
    corpus_solutions_dir,
    grade,
    grade_reference_solution,
    load_tasks,
    pdf_text,
    restore_protected,
    seed_project,
    seeded_prompt,
    task_ids,
)
from hephaestus.bench.scoring import (
    CORPUS_V1_TASKS,
    G2_AGGREGATE_THRESHOLD,
    G6_AGGREGATE_THRESHOLD,
    PERFECT_TASKS,
    aggregate_threshold,
    score_records,
    wilson_lower_bound,
)
from hephaestus.core.executor.sandbox.bwrap import find_bwrap
from pypdf import PdfReader

#: The public corpus v0, difficulty-ordered with the budgets fixed by
#: ``agent/STAGE2_DIGEST.md`` §8 / ``verification.md`` Tier 3.
CORPUS_V0: tuple[tuple[str, int], ...] = (
    ("bracket-101", 20),
    ("sheet-box", 32),
    ("cat-step", 52),
    ("store-hardware", 27),
    ("repair-fillet", 12),
    ("param-retune", 10),
    ("knob-loft", 26),
    ("enclosure-bosses", 38),
)

#: The four Stage 6 additions that make corpus v1 (mission_plan.md Stage 6:
#: "corpus expanded to 12 tasks ... including a DFM-repair task and a drawing
#: task"). Budgets are calibrated to each reference solution's call path with
#: headroom, and every one of them is justified in the task's own ``notes``.
CORPUS_V1_ADDITIONS: tuple[tuple[str, int], ...] = (
    ("dfm-repair", 12),
    ("drawing-shelf", 18),
    ("nest-gusset", 20),
    ("print-bracket", 26),
)

#: Corpus v1: the whole public split, and what the G6 bench clause is run over.
CORPUS: tuple[tuple[str, int], ...] = CORPUS_V0 + CORPUS_V1_ADDITIONS

#: Tasks whose acceptance re-runs a DFM rule pack. Predicates are registry
#: content and execute only under a probed secure sandbox (architecture §3.6), so
#: grading them needs one — exactly like ``server/tests/test_dfm_tool.py``.
DFM_TASKS: frozenset[str] = frozenset({"dfm-repair", "print-bracket"})

requires_bwrap = pytest.mark.skipif(
    sys.platform != "linux" or find_bwrap() is None,
    reason="DFM rule predicates execute only under a probed secure sandbox (bubblewrap)",
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


def test_corpus_is_the_twelve_public_tasks() -> None:
    prose = {task_id for task_id, _ in CORPUS}
    assert len(prose) == 12, "corpus v1 is twelve public tasks (mission_plan.md Stage 6)"
    # The gated split is exactly the twelve public tasks…
    assert set(task_ids(specs=("prose",))) == prose
    # …and VALIDATION.md §1 ships each of them a second time as a seeded variant,
    # never collapsed into the prose split. Expanding the corpus must not have
    # opened a hole in that: the four new tasks ship both variants too.
    assert set(task_ids(specs=("seeded",))) == {f"{task_id}@seeded" for task_id in prose}
    assert set(task_ids()) == prose | {f"{task_id}@seeded" for task_id in prose}
    # The v0 split is still present and unchanged inside v1.
    assert {task_id for task_id, _ in CORPUS_V0} <= prose
    assert set(CORPUS_V1_TASKS) == {task_id for task_id, _ in CORPUS_V1_ADDITIONS}


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
    if task.dfm and (sys.platform != "linux" or find_bwrap() is None):
        pytest.skip("DFM acceptance needs a probed secure sandbox (bubblewrap)")
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
    # Stage 6: the DFM verdicts and drawing sheets were produced and are clean.
    assert len(report.dfm) == len(task.dfm)
    for record in report.dfm:
        assert "error" not in record, record
        assert record.get("source_artifact_ref"), record
    assert len(report.drawings) == len(task.drawings)
    for record in report.drawings:
        assert "error" not in record and "invalid" not in record, record
        assert record.get("missing_texts") == [], record
        assert int(cast("int", record.get("bytes", 0))) > 0
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


def test_stage6_requirements_are_covered_by_the_corpus(
    tasks: Mapping[str, BenchTask],
) -> None:
    """Corpus v1 must exercise every Stage 6 acceptance surface, both processes."""
    prose = [task for task in tasks.values() if task.spec == "prose"]
    dfm_tasks = {task.id for task in prose if task.dfm}
    assert dfm_tasks == DFM_TASKS
    rules = {rule for task in prose for req in task.dfm for rule in req.clean_rules}
    # Both shipped packs, and the three rules the G6 clause names for each.
    assert {"laser_cut.min_feature_vs_kerf", "laser_cut.min_internal_radius"} <= rules
    assert {
        "fdm.min_wall_thickness",
        "fdm.min_hole_diameter",
        "fdm.overhang_angle",
    } <= rules

    drawings = [req for task in prose for req in task.drawings]
    assert [req.part for req in drawings] == ["shelf"]
    # The G6 clause: the five principal dimensions in the extracted PDF text
    # (three overall extents, the material thickness, the bore diameter).
    assert {"600.0", "250.0", "218.0", "18.0", "Ø8.0"} <= set(drawings[0].required_texts)

    nested = [req for task in prose for req in task.exports if req.layout == "nested_sheet"]
    assert len(nested) == 1, "nest-gusset is the nested_sheet task"
    assert nested[0].profile_count == 3
    assert nested[0].profile_layer == "PROFILES"
    assert nested[0].blank_mm == (210.0, 125.0), "G6 names the 210 x 125 blank"


def test_the_graders_pdf_reader_agrees_with_pypdf() -> None:
    """The drawing requirement stands on :func:`pdf_text`, so it is cross-checked.

    ``pypdf`` is a dev-only dependency and grading ships with the wheel, so the
    grader reads the text layer itself. That is only safe while the two readers
    agree — including on the exact strings a dimensioned sheet prints (``Ø`` is
    the one non-ASCII character in the set).
    """
    sheet = Sheet(width=595.0, height=842.0, title="agreement")
    printed = (
        dimension_text(600.0, "linear"),
        dimension_text(8.0, "diameter"),
        dimension_text(18.0, "thickness"),
        "18 mm Baltic birch plywood",
        "TOL +/-0.25 mm (paren) \\ backslash",
    )
    for index, value in enumerate(printed):
        sheet.text(20.0, 40.0 + 12.0 * index, value)
    data = sheet_to_pdf(sheet)

    ours = pdf_text(data)
    theirs = "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(data)).pages)
    for value in printed:
        assert value in ours, f"{value!r} missing from the grader's read"
        assert value in theirs, f"{value!r} missing from pypdf's read"
    assert ours.split("\n") == [line for line in theirs.split("\n") if line]


@requires_bwrap
def test_the_dfm_repair_seed_really_violates_its_named_rules(
    tasks: Mapping[str, BenchTask], tmp_path: Path
) -> None:
    """A repair task whose seed is already clean would grade everything green.

    So the negative control is asserted, not assumed: the *unrepaired* seed —
    the project a run is handed — fails the very rule ids the task requires
    clean, and fails the volume check that pins the two repaired feature sizes.
    """
    task = tasks["dfm-repair"]
    root = tmp_path / "unrepaired"
    seed_project(task, root)  # no reference solution overlaid: the seed as shipped
    report = grade(task, root)

    assert not report.passed
    assert "dfm_findings:vent_panel:laser_cut.min_feature_vs_kerf:1" in report.reasons
    assert "dfm_findings:vent_panel:laser_cut.min_internal_radius:2" in report.reasons
    assert "check_failed:dfm_repair:vent_and_corners_at_size" in report.reasons
    # The findings name the design's own tag, not a bare mask id (G6).
    findings = cast("list[Mapping[str, Any]]", report.dfm[0]["findings"])
    tagged = [f for f in findings if "vent_bore" in cast("list[str]", f.get("tags", []))]
    assert tagged, findings


def test_corpus_v1_raises_the_aggregate_threshold_to_the_g6_bound() -> None:
    """G6: lower-90% Wilson >= 0.70 on the gated (prose) split, over 12 tasks."""
    assert G6_AGGREGATE_THRESHOLD == 0.70
    assert G6_AGGREGATE_THRESHOLD > G2_AGGREGATE_THRESHOLD, "thresholds tune upward only"

    v0_ids = [task_id for task_id, _ in CORPUS_V0]
    v1_ids = [task_id for task_id, _ in CORPUS]
    # A v0 archive keeps the bound it was baselined under…
    assert aggregate_threshold(v0_ids) == G2_AGGREGATE_THRESHOLD
    # …and covering corpus v1 is itself what raises it — including via the
    # seeded ids, whose variant suffix is not a different task.
    assert aggregate_threshold(v1_ids) == G6_AGGREGATE_THRESHOLD
    assert aggregate_threshold(f"{task_id}@seeded" for task_id in v1_ids) == (
        G6_AGGREGATE_THRESHOLD
    )
    # 12 tasks x >= 3 seeds = 36 runs: 29 passes clear the bound and 28 do not,
    # so the gate is a real constraint on a full v1 sweep (80.6% vs 77.8% raw).
    assert wilson_lower_bound(29, 36) >= G6_AGGREGATE_THRESHOLD
    assert wilson_lower_bound(28, 36) < G6_AGGREGATE_THRESHOLD


def test_scoring_a_corpus_v1_sweep_gates_at_the_g6_bound() -> None:
    """The plumbing, end to end: a v1 archive is scored against 0.70.

    The seeded split still carries no threshold (VALIDATION.md §1: recorded and
    baselined separately, never gated), so expanding the corpus raised the bound
    on exactly one split.
    """
    records = [
        {
            "task_id": task_id,
            "seed": seed,
            "spec": spec,
            "passed": passed,
            "model": "reference-model",
            "date": "2026-07-26",
        }
        for spec in ("prose", "seeded")
        for task_id, _budget in CORPUS
        for seed, passed in ((1, True), (2, True), (3, task_id != "knob-loft"))
    ]
    score = score_records(records)

    assert score.threshold == G6_AGGREGATE_THRESHOLD
    assert score.prose.threshold == G6_AGGREGATE_THRESHOLD
    assert (score.prose.n, score.prose.passes) == (36, 35)
    assert score.meets_gate  # 35/36 clears 0.70 and repair-fillet is 3/3
    assert score.seeded.threshold is None
    assert score.seeded.meets_threshold is None
    # Dropping the four v1 tasks is a v0 sweep again, at the v0 bound.
    v0_only = [r for r in records if r["task_id"] not in set(CORPUS_V1_TASKS)]
    assert score_records(v0_only).threshold == G2_AGGREGATE_THRESHOLD
