"""The corpus meta-test: every public task is validated by a reference solution.

verification.md Tier 3 / digest §8: *"Every task must be validated by a
``solutions/`` reference implementation passing its own checks in CI — a task no
reference solution passes is a broken task, not a hard task."* These tests are
that rule, executed. For each of the **nineteen** public tasks they seed a fresh
project from ``corpus/tasks/<id>/seed/``, overlay ``corpus/solutions/<id>/``
(scripts and/or a ``params.json`` applied through the real ``set_params`` path),
and run the *same* grading path a benchmarked model run is graded by: build every
part, install the task's required CHECKS, run them project-scoped, then validate
the required exports, renders, DFM verdicts, drawing sheets and declared
constraints (ASSEMBLY.md §3).

They also pin the corpus itself: the ids are the ones the digest (v0),
mission_plan.md Stage 6 (v1) and the 2026-08-25 corpus-v2 operator decision
(the ingest and assembly pairs; see :data:`CORPUS_V2_ADDITIONS`) fix, the tool-call
budgets are those numbers as recalibrated/derived by the 2026-08-25
measured-budget amendment (VALIDATION.md §7 "Budgets are calibrated from
measurement", derivations in each task.json's ``notes``), ``repair-fillet``
is the task the gate requires perfect, and covering corpus v1 is what raises the
aggregate Wilson bound from 0.60 to G6's 0.70 on the gated prose split (v2 is a
superset, so a v2 sweep reads the same bound).
"""

from __future__ import annotations

import ast
import io
import json
import math
import re
import shutil
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
    DfmRequirement,
    corpus_solutions_dir,
    grade,
    grade_reference_solution,
    load_tasks,
    open_cad,
    pdf_text,
    restore_protected,
    results_root,
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
#: ``agent/STAGE2_DIGEST.md`` §8 / ``verification.md`` Tier 3, recalibrated by
#: the 2026-08-25 measured-budget amendment (VALIDATION.md §7 "Budgets are
#: calibrated from measurement"): ceil(1.3 x max(hand-counted reference path,
#: observed passing max over the archived gpt-5.6-sol observe-mode journals)),
#: with tasks already at or above the derived number keeping theirs
#: (``cat-step`` 52, ``repair-fillet`` 12). Each task.json's ``notes`` carries
#: the per-task derivation; no archived artifact was re-scored.
CORPUS_V0: tuple[tuple[str, int], ...] = (
    ("bracket-101", 25),
    ("sheet-box", 42),
    ("cat-step", 52),
    ("store-hardware", 32),
    ("repair-fillet", 12),
    ("param-retune", 13),
    ("knob-loft", 33),
    ("enclosure-bosses", 43),
)

#: The four Stage 6 additions that make corpus v1 (mission_plan.md Stage 6:
#: "corpus expanded to 12 tasks ... including a DFM-repair task and a drawing
#: task"). Budgets follow the 2026-08-25 measured-budget amendment above —
#: ``print-bracket`` already met the derived number and kept 26 — and every
#: one of them is justified in the task's own ``notes``.
CORPUS_V1_ADDITIONS: tuple[tuple[str, int], ...] = (
    ("dfm-repair", 16),
    ("drawing-shelf", 24),
    ("nest-gusset", 23),
    ("print-bracket", 26),
)

#: Corpus v1: the twelve tasks the G6 bench clause was measured over. The G6
#: closure (bench/results/gpt-5.6-sol/2026-08-13.json) stands on exactly these.
CORPUS_V1: tuple[tuple[str, int], ...] = CORPUS_V0 + CORPUS_V1_ADDITIONS

#: The corpus-v2 additions (2026-08-25 operator decision, post-G6): two public
#: ingest tasks exercising the two shapes INGEST.md §2 names as the substrate
#: for external benchmarks — ``flange-edit`` (editing: a seeded vendor STEP
#: under ``imports/``, acceptance measured with ``m.diff`` against the import
#: per COMPARE.md §2) and ``plate-from-drawing`` (generation: a seeded drawing
#: image under ``references/``, the vision-citation ledger path) — plus two
#: public Stage 8C assembly tasks, the first corpus tasks scored on declared
#: constraints through the engine path (ASSEMBLY.md §3 "assembly tasks score
#: on declared fits holding, not on volume windows"): ``hinge-mate``
#: (concentric pin bores, coincident knuckle mate faces, a clearance_min swing
#: gap) and ``shaft-coupler`` (a real hole/shaft ``fit`` window as the
#: acceptance centrepiece, plus no_interference and a seat-height distance).
#: They expand the corpus without touching any gate: ``aggregate_threshold``
#: reads the v1 coverage (a superset still gates at 0.70), and no archived
#: artifact is re-scored. Budgets are hand-count derivations per the
#: 2026-08-25 measured-budget policy — no observe-mode journal data exists for
#: new tasks yet, and each task.json's ``notes`` says so.
CORPUS_V2_ADDITIONS: tuple[tuple[str, int], ...] = (
    ("flange-edit", 16),
    ("plate-from-drawing", 19),
    ("hinge-mate", 19),
    ("shaft-coupler", 16),
)

#: Every task graded on declared constraints through the engine path: the
#: corpus-v2 assembly pair, plus the corpus-v3 mechanism tasks that carry
#: constraint entries beside their kinematic acceptance (``gripper-jaws``'s
#: pose-bound closure fit, ``leadscrew-actuator``'s screw register,
#: ``hinge-travel``'s pose-bound open-limit stand-clear).
CONSTRAINT_TASKS: frozenset[str] = frozenset(
    {"hinge-mate", "shaft-coupler", "gripper-jaws", "leadscrew-actuator", "hinge-travel"}
)

#: Corpus v3 (2026-08-27, KINEMATICS.md §6 Stage 9C): the mechanism tasks,
#: graded through the engine motion path (joints, poses and motion checks
#: installed by the grader; the lead-screw's coupling deliberately the run's
#: own to declare). Budgets are dated hand-count derivations per the
#: 2026-08-25 measured-budget policy — no observe-mode journals exist for
#: mechanism tasks yet, and each task.json's ``notes`` carries the derivation.
# Budgets recalibrated 2026-08-27 from the first archived observe-mode sweep
# (bench/results/gpt-5.6-sol/2026-08-27/runs.jsonl) per VALIDATION.md §7 incl.
# its zero-passing first-measurement rule — every failure's sole reason was
# budget_exceeded, 0 correctness failures; derivations in each task.json notes.
CORPUS_V3_ADDITIONS: tuple[tuple[str, int], ...] = (
    ("gripper-jaws", 34),
    ("hinge-travel", 52),
    ("leadscrew-actuator", 41),
)

#: The whole public split as it stands (v1 + the v2 and v3 additions).
CORPUS: tuple[tuple[str, int], ...] = CORPUS_V1 + CORPUS_V2_ADDITIONS + CORPUS_V3_ADDITIONS

#: Tasks whose acceptance re-runs a DFM rule pack. Predicates are registry
#: content and execute only under a probed secure sandbox (architecture §3.6), so
#: grading them needs one — exactly like ``server/tests/test_dfm_tool.py``.
DFM_TASKS: frozenset[str] = frozenset({"dfm-repair", "print-bracket"})

requires_bwrap = pytest.mark.skipif(
    sys.platform != "linux" or find_bwrap() is None,
    reason="DFM rule predicates execute only under a probed secure sandbox (bubblewrap)",
)

#: Independently authored *second* implementations of the tasks the 2026-07-26
#: corpus audit re-authored. ``corpus/solutions`` proves a task is passable;
#: these prove it is passable by something other than the reference geometry,
#: which is the only way to show a check grades correctness and not reproduction.
CORPUS_VARIANTS: Path = Path(__file__).parent / "fixtures" / "corpus_variants"
VARIANT_TASKS: frozenset[str] = frozenset(
    {
        "enclosure-bosses",
        "drawing-shelf",
        "cat-step",
        # Corpus-v2 (2026-08-25): every NEW task ships its independent second
        # implementation from day one (VALIDATION.md §1 — a check written from
        # one implementation cannot detect that it demands that implementation).
        "flange-edit",
        "plate-from-drawing",
        "hinge-mate",
        "shaft-coupler",
        # Corpus-v3 (2026-08-27, Stage 9C): the mechanism tasks follow the
        # same rule — each ships its independent second implementation, and a
        # mechanism acceptance graded through the engine motion path must pass
        # on geometry the reference author never saw.
        "gripper-jaws",
        "hinge-travel",
        "leadscrew-actuator",
    }
)

#: The constants of the checks the audit retired, kept so the guards can measure
#: that a correct variant really would have failed them.
RETIRED_LID_VOLUME = 22625.26
RETIRED_MATERIAL_TEXT = "18 mm Baltic birch plywood"
SHELL_GAUGE_VOLUME = 20112.384
#: ``cat-step``: the tread's intended volume, and the window the audit replaced.
TREAD_VOLUME = 1075171.46
RETIRED_TREAD_WINDOW = 400.0
TREAD_WINDOW = 600.0

#: A required drawing text must be a dimension as ``dimension_text`` prints one
#: (``600.0``, ``Ø8.0``, ``R4.0``) — never a sentence out of a title block.
DIMENSION_TEXT_RE = re.compile(r"[ØR]?\d+(?:\.\d+)?(?:\s*mm)?")

#: Words in a check name that promise a *fit* — a relation between two bodies.
#: A check named with one of these must be measured as one (``m.clearance`` /
#: ``m.interference`` against the other body or a seeded gauge), never as one
#: part's volume. ``lid_register_clearance`` broke exactly this rule.
FIT_WORDS: tuple[str, ...] = (
    "clearance",
    "clears",
    "contact",
    "fit",
    "flush",
    "gap",
    "interfere",
    "mates",
    "seat",
    "touch",
)


def _check_predicates(source: str) -> dict[str, str]:
    """``{check name: predicate source}`` for a ``CHECKS = {...}`` module."""
    module = ast.parse(source)
    found: dict[str, str] = {}
    for node in ast.walk(module):
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "CHECKS" for target in node.targets
        ):
            continue
        value = node.value
        if not isinstance(value, ast.Dict):
            continue
        for key, predicate in zip(value.keys, value.values, strict=True):
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                found[key.value] = ast.get_source_segment(source, predicate) or ""
    return found


#: A single reference solution must build and grade well inside this; the digest's
#: working budget is 30 s per solution build, and the whole grading pass (build +
#: checks + exports + renders) is measured here with generous headroom so the
#: assertion catches a pathological regression, not CI jitter.
GRADE_SECONDS_CEILING = 120.0


@pytest.fixture(scope="session")
def tasks() -> Mapping[str, BenchTask]:
    """Every corpus task, loaded once (the spec parse is itself a validation)."""
    return {task.id: task for task in load_tasks()}


def test_corpus_is_the_nineteen_public_tasks() -> None:
    """Corpus v3: the twelve v1 tasks plus the v2 and v3 additions.

    Repointed from "twelve" by the corpus-v2 amendment (2026-08-25 operator
    decision, recorded in mission_plan.md's Stage 6 status): the corpus grew by
    the ingest pair (``flange-edit``, ``plate-from-drawing``) and the Stage 8C
    assembly pair (``hinge-mate``, ``shaft-coupler``). Repointed again from
    "sixteen" by the Stage 9C corpus-v3 amendment (2026-08-27, KINEMATICS.md
    §6): the mechanism tasks ``gripper-jaws``, ``hinge-travel`` and
    ``leadscrew-actuator``. The
    v1 pin it used to carry is kept below as a subset assertion — the G6
    evidence's corpus is unchanged inside v2/v3, and the four Stage 6
    additions are still exactly :data:`CORPUS_V1_TASKS`.
    """
    prose = {task_id for task_id, _ in CORPUS}
    assert len(prose) == 19, (
        "corpus v3 is nineteen public tasks (v1 + the ingest and assembly pairs "
        "+ the Stage 9C mechanism trio)"
    )
    # The gated split is exactly the public tasks…
    assert set(task_ids(specs=("prose",))) == prose
    # …and VALIDATION.md §1 ships each of them a second time as a seeded variant,
    # never collapsed into the prose split. Expanding the corpus must not have
    # opened a hole in that: the new tasks ship both variants too.
    assert set(task_ids(specs=("seeded",))) == {f"{task_id}@seeded" for task_id in prose}
    assert set(task_ids()) == prose | {f"{task_id}@seeded" for task_id in prose}
    # The v0 and v1 splits are still present and unchanged inside v2.
    assert {task_id for task_id, _ in CORPUS_V0} <= prose
    assert {task_id for task_id, _ in CORPUS_V1} <= prose
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


#: The measured-budget policy's headroom factor, restated independently of the
#: harness so a drive-by edit to the policy constant cannot quietly relax this
#: floor along with the budgets (VALIDATION.md §7 "Budgets are calibrated from
#: measurement": budget = ceil(1.3 x max(hand-counted path, observed passing max))).
BUDGET_HEADROOM = 1.3


def _archived_passing_max() -> dict[str, int]:
    """``{base task id: observed passing max}``, recomputed from the archive.

    The independent recomputation of VALIDATION.md §7's "observed passing max":
    the largest ``tool_calls`` recorded by any *passing* run in the archived
    corpus journals (``bench/results/<model>/<date>/runs.jsonl``). Seeded and
    prose records fold onto the base id because the variants share one budget by
    construction (pinned above). Passing runs carry true counts in both modes —
    an enforce-mode run that passed was never cancelled — so no mode filter is
    needed; the observe-mode distinction only matters for *failed* runs, which
    are censored and excluded here anyway.
    """
    observed: dict[str, int] = {}
    for journal in sorted(results_root().glob("*/*/runs.jsonl")):
        for line in journal.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = cast("Mapping[str, Any]", json.loads(line))
            if not record.get("passed"):
                continue
            base = str(record["task_id"]).split("@", 1)[0]
            calls = int(cast("int", record["tool_calls"]))
            observed[base] = max(observed.get(base, 0), calls)
    return observed


def test_every_budget_meets_the_measured_calibration_floor(
    tasks: Mapping[str, BenchTask],
) -> None:
    """VALIDATION.md §7, enforced against an independent recomputation.

    A budget hand-edited below ``ceil(1.3 x observed passing max)`` fails here
    loudly, because the floor is re-derived from the archived journals at test
    time rather than trusted from the task's own ``notes``. The archive is
    read-only evidence: this test never writes under ``bench/results/``.

    Tasks with no archived passing run yet (the corpus-v2 additions) have no
    measured floor to hold; the policy's other half — a dated hand-count
    derivation in the task's ``notes`` — is asserted for them instead, so a new
    task cannot ship a bare guess either.
    """
    observed = _archived_passing_max()
    assert observed, "no archived corpus journals found; the floor cannot be recomputed"
    unmeasured = {task_id for task_id, _ in CORPUS_V2_ADDITIONS + CORPUS_V3_ADDITIONS}
    for task_id, _budget in CORPUS:
        budget = tasks[task_id].budget_tool_calls
        if task_id not in observed:
            assert task_id in unmeasured, (
                f"{task_id}: a corpus-v1 task lost its archived passing runs; the "
                "measured floor can no longer be recomputed"
            )
            notes = tasks[task_id].notes
            assert "hand-count" in notes and "2026-08-25" in notes, (
                f"{task_id}: no archived measurement and no dated hand-count "
                "derivation in task.json notes — the budget is a bare guess"
            )
            continue
        floor = math.ceil(BUDGET_HEADROOM * observed[task_id])
        assert budget >= floor, (
            f"{task_id}: budget {budget} is below the measured calibration floor "
            f"ceil({BUDGET_HEADROOM} x {observed[task_id]}) = {floor} "
            "(VALIDATION.md §7: calibration raises budgets measurement shows are "
            "too tight; a standing budget is never hand-tightened below the floor)"
        )


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
    # …and the §5.2 metadata a task requires was authored and resolves.
    assert len(report.metadata) == len(task.metadata)
    for record, requirement in zip(report.metadata, task.metadata, strict=True):
        assert record.get("missing_fields") == [], record
        if requirement.material_id is not None:
            assert record.get("material_id") == requirement.material_id, record
    # Corpus v2 (ASSEMBLY.md §3): every declared constraint was evaluated
    # through the engine path and landed in the state the task expects.
    assert len(report.constraints) == len(task.constraints)
    for record, constraint in zip(report.constraints, task.constraints, strict=True):
        assert "error" not in record, record
        outcome = cast("Mapping[str, Any]", record.get("outcome"))
        assert outcome.get("state") == constraint.expect, record
    assert elapsed < GRADE_SECONDS_CEILING, f"{task_id}: grading took {elapsed:.1f}s"


@pytest.mark.parametrize("task_id", sorted(VARIANT_TASKS))
def test_a_different_but_correct_solution_also_passes(
    task_id: str, tasks: Mapping[str, BenchTask], tmp_path: Path
) -> None:
    """The audit's own guard: correctness must pass, not reproduction.

    ``corpus/solutions`` validates that a task is *passable*; it cannot show
    that the task grades the engineering rather than the author's geometry,
    because the checks were authored from that very solution. These variants are
    the second, independent implementation each re-authored task needs: same
    specification, different construction order, different in-spec dimensions,
    different wording. A check that demands the reference back fails here.
    """
    report = grade_reference_solution(
        tasks[task_id], tmp_path / "project", solutions_dir=CORPUS_VARIANTS
    )
    assert report.passed, f"{task_id} variant solution failed: {report.reasons}"
    for name, value in report.checks.items():
        entry = cast("Mapping[str, Any]", value)
        assert entry.get("pass") is True, f"{task_id}: variant failed check {name}: {entry}"
    assert report.restored_protected == ()
    for record in report.drawings:
        assert record.get("missing_texts") == [], record


def test_the_enclosure_variant_would_have_failed_the_retired_checks(
    tasks: Mapping[str, BenchTask], tmp_path: Path
) -> None:
    """Why ``enclosure-bosses`` was re-authored, measured on the variant lid.

    The retired ``lid_register_clearance`` was ``volume("lid/part") ==
    approx(22625.26, abs=20.0)`` — a 0.09% window on a lid whose lip the task
    lets you model as a solid block *or* a peripheral rib. The variant is the
    rib, and it is ~6800 mm^3 lighter: functionally a correct lid, arithmetically
    a different one. The retired ``min_wall_1p6`` window (±5 mm^3) is measured
    the same way against the variant's 0.3 mm base chamfer.
    """
    root = tmp_path / "project"
    report = grade_reference_solution(
        tasks["enclosure-bosses"], root, solutions_dir=CORPUS_VARIANTS
    )
    assert report.passed, report.reasons

    with open_cad(root) as cad:
        measured = cad.measure(
            "volume", "lid/part", None, part=None, artifact_ref=None, project_snapshot_ref=None
        )
    lid_volume = float(cast("float", measured["value"]))
    assert abs(lid_volume - RETIRED_LID_VOLUME) > 1000.0, (
        "the variant lid must really differ from the reference lid, or this guard proves nothing"
    )

    shell = float(cast("float", report.checks["enclosure_bosses:min_wall_1p6"]["measured"]))
    assert 5.0 < abs(shell - SHELL_GAUGE_VOLUME) < 40.0, (
        "the variant's base chamfer must land outside the retired ±5 mm^3 min-wall window "
        "and inside the re-authored ±40 one"
    )


def test_the_cat_step_variant_would_have_failed_the_retired_window(
    tasks: Mapping[str, BenchTask], tmp_path: Path
) -> None:
    """Why the material budgets were widened, measured on the flagship task.

    ``cat-step`` fixes every dimension it asks for, so the freedom a correct run
    really has is the *unrequested* detailing — and on a ply cat step that means
    easing the edges the cat lands on. The variant breaks the tread's top edges
    by 1 mm: ~490 mm^3, outside the retired +/-400 identity window and inside the
    +/-600 budget. The old check would have failed a better tread than the
    reference's.
    """
    report = grade_reference_solution(
        tasks["cat-step"], tmp_path / "project", solutions_dir=CORPUS_VARIANTS
    )
    assert report.passed, report.reasons

    measured = float(
        cast("float", report.checks["cat_step:tread_material_pins_r25_corners"]["measured"])
    )
    delta = abs(measured - TREAD_VOLUME)
    assert RETIRED_TREAD_WINDOW < delta < TREAD_WINDOW, (
        f"the eased tread is {delta:.1f} mm^3 off nominal: it must land outside the retired "
        "window and inside the re-authored one, or this guard proves nothing"
    )


@pytest.mark.parametrize(
    ("mutation", "replacement", "failing_checks"),
    [
        pytest.param(
            "_clear = 0.3",
            "_clear = 0.0",
            {"lid_register_clears_the_opening"},
            id="press-fit-lip",
        ),
        pytest.param(
            "body = plate + rib",
            "body = plate + Pos(0, 0, _lip_z) * Box(20.0, 20.0, hc.lid_lip_h)",
            {"lid_register_clears_the_opening", "lid_closes_and_registers"},
            id="token-lip-that-registers-nothing",
        ),
    ],
)
def test_the_re_authored_register_checks_bite(
    mutation: str,
    replacement: str,
    failing_checks: set[str],
    tasks: Mapping[str, BenchTask],
    tmp_path: Path,
) -> None:
    """A fit check that nothing can fail is decoration. These are the mutations.

    A lip with no clearance is a press fit on a printed box; a lip that does not
    run round the opening registers nothing. Both build, both keep the envelope,
    the topology and the rim contact — under the retired volume check the first
    was caught only incidentally (it moved the number) and the second, at the
    right volume, not at all.
    """
    task = tasks["enclosure-bosses"]
    root = tmp_path / "mutant"
    seed_project(task, root)
    source = (CORPUS_VARIANTS / "enclosure-bosses" / "parts" / "lid.py").read_text(encoding="utf-8")
    assert mutation in source
    (root / "parts" / "lid.py").write_text(source.replace(mutation, replacement), encoding="utf-8")
    shutil.copy2(CORPUS_VARIANTS / "enclosure-bosses" / "parts" / "enclosure.py", root / "parts")
    report = grade(task, root)

    assert not report.passed
    failed = {name.split(":", 1)[1] for name in report.reasons if name.startswith("check_failed:")}
    assert {f"enclosure_bosses:{name}" for name in failing_checks} <= failed, report.reasons


def test_the_unedited_vendor_flange_fails_the_editing_checks_by_name(
    tasks: Mapping[str, BenchTask], tmp_path: Path
) -> None:
    """The corpus-v2 editing task's negative control (2026-08-25).

    ``flange-edit`` grades through ``m.diff`` against the seeded import — the
    first acceptance predicate in the corpus that resolves an ``import:``
    target at grade time (COMPARE.md §2), through the resolver wired into
    project-scope ``run_checks`` for exactly this task. So the failing
    direction is asserted, not assumed: a run that imports the vendor file and
    ships it back UNEDITED — geometry identical to the comparison target, iou
    1.0 — must fail on the checks that name the edit, and on nothing else.
    """
    task = tasks["flange-edit"]
    root = tmp_path / "unedited"
    seed_project(task, root)
    (root / "parts").mkdir(exist_ok=True)
    (root / "parts" / "flange.py").write_text(
        "# The vendor file, imported and shipped back without the edit.\n"
        'part.geometry = import_step("flange.step")\n',
        encoding="utf-8",
    )
    report = grade(task, root)

    assert not report.passed
    failed = {name for name in report.reasons if name.startswith("check_failed:")}
    assert failed == {
        "check_failed:flange_edit:bore_enlarged_by_the_specified_annulus",
        "check_failed:flange_edit:go_pin_passes_the_new_bore",
        "check_failed:flange_edit:go_pin_clearance",
    }, report.reasons
    # …and only the checks: the export and the build are fine, so nothing else
    # is charged. An unedited flange is a check failure, not a broken project.
    assert [r for r in report.reasons if not r.startswith("check_failed:")] == []


def test_the_assembly_pair_covers_the_constraint_half_of_the_grader(
    tasks: Mapping[str, BenchTask],
) -> None:
    """Corpus v2 (2026-08-25): ASSEMBLY.md §3's bench clause, made corpus reality.

    :data:`CONSTRAINT_TASKS` are the only tasks with declared constraints, and
    between them they exercise six of the eight 8C kinds — including ``fit``,
    the hole/shaft window the DFM fits vocabulary speaks. (Repointed
    2026-08-27, Stage 9C corpus v3: the mechanism tasks joined the set — their
    constraint entries ride the same grader half, ``gripper-jaws``'s bound to
    the poses its motion acceptance declares.) Every anchor names a part the
    task declares (so the grader builds it), and every entry expects
    ``satisfied``: these tasks assert mates that hold, not the absence of
    evidence.
    """
    constrained = {task.id for task in tasks.values() if task.spec == "prose" and task.constraints}
    assert constrained == CONSTRAINT_TASKS
    kinds = {
        str(constraint.entry["kind"])
        for task_id in CONSTRAINT_TASKS
        for constraint in tasks[task_id].constraints
    }
    assert kinds == {
        "concentric",
        "coincident",
        "clearance_min",
        "fit",
        "no_interference",
        "distance",
    }
    for task_id in sorted(CONSTRAINT_TASKS):
        task = tasks[task_id]
        declared = task.declared_parts()
        for constraint in task.constraints:
            assert constraint.expect == "satisfied", constraint.id
            for side in ("a", "b"):
                anchor = str(constraint.entry[side])
                assert anchor.split(":", 1)[0] in declared, f"{task_id}: {anchor}"
        # The prompt names every anchor tag it grades through, so a run can
        # only fail a constraint it was really asked to satisfy.
        for constraint in task.constraints:
            for side in ("a", "b"):
                anchor = str(constraint.entry[side])
                if ":" in anchor:
                    assert f"`{anchor.split(':', 1)[1]}`" in task.prompt, f"{task_id}: {anchor}"


def test_a_misaligned_pin_bore_fails_the_declared_concentricity_by_name(
    tasks: Mapping[str, BenchTask], tmp_path: Path
) -> None:
    """The constraint path bites: a 0.2 mm bore offset is a named violation.

    ``leaf_b``'s pin bore is drilled 0.2 mm off the hinge axis — a hinge that
    will not take its pin. The declared ``concentric`` entry (tol 0.05) fails
    under its own reason token, carrying the measured offset, exactly as
    ASSEMBLY.md §3 promises: a violated fit is a named constraint failure, not
    an interference a CHECKS block happens to catch.
    """
    task = tasks["hinge-mate"]
    root = tmp_path / "offset-bore"
    seed_project(task, root)
    (root / "parts").mkdir(exist_ok=True)
    shutil.copy2(corpus_solutions_dir() / "hinge-mate" / "parts" / "leaf_a.py", root / "parts")
    source = (corpus_solutions_dir() / "hinge-mate" / "parts" / "leaf_b.py").read_text(
        encoding="utf-8"
    )
    mutation = "bore = (\n    Pos(_x_mid, 0.0, _axis_z)"
    assert mutation in source
    (root / "parts" / "leaf_b.py").write_text(
        source.replace(mutation, "bore = (\n    Pos(_x_mid, 0.2, _axis_z)"), encoding="utf-8"
    )
    report = grade(task, root)

    assert not report.passed
    violated = [r for r in report.reasons if r.startswith("constraint_violated:")]
    assert violated and violated[0].startswith("constraint_violated:c-pin-bores-concentric:"), (
        report.reasons
    )
    # The reason carries the measurement: the 0.2 mm offset that was authored.
    assert abs(float(violated[0].rsplit(":", 1)[1]) - 0.2) < 0.01, violated[0]
    # Nothing came back unresolvable: the mate was measured and found wrong.
    assert not any(r.startswith("constraint_unresolvable:") for r in report.reasons)


def test_a_line_to_line_coupler_fails_the_declared_fit_by_name(
    tasks: Mapping[str, BenchTask], tmp_path: Path
) -> None:
    """The fit window's floor is real: zero clearance is a violation, not a pass.

    The coupler is re-bored at exactly the spindle's diameter — the mistake the
    prompt warns against in as many words. The measured radial clearance is
    0.0, under the declared 0.02 minimum, and the run fails on the ``fit``
    constraint by name (``no_interference`` stays satisfied: line-to-line
    contact shares no volume, which is exactly why a fit needs its own kind).
    """
    task = tasks["shaft-coupler"]
    root = tmp_path / "line-to-line"
    seed_project(task, root)
    (root / "parts").mkdir(exist_ok=True)
    shutil.copy2(corpus_solutions_dir() / "shaft-coupler" / "parts" / "shaft.py", root / "parts")
    source = (corpus_solutions_dir() / "shaft-coupler" / "parts" / "coupler.py").read_text(
        encoding="utf-8"
    )
    mutation = "_bore_r = hc.spindle_d / 2.0 + 0.04"
    assert mutation in source
    (root / "parts" / "coupler.py").write_text(
        source.replace(mutation, "_bore_r = hc.spindle_d / 2.0"), encoding="utf-8"
    )
    report = grade(task, root)

    assert not report.passed
    violated = [r for r in report.reasons if r.startswith("constraint_violated:")]
    assert violated and violated[0].startswith("constraint_violated:c-sliding-fit:"), report.reasons
    # The reason carries the measurement: a line-to-line 0.0, under the floor.
    assert abs(float(violated[0].rsplit(":", 1)[1])) < 0.005, violated[0]
    assert not any("c-no-interference" in r for r in violated)


def test_an_untagged_interface_is_unresolvable_never_a_quiet_pass(
    tasks: Mapping[str, BenchTask], tmp_path: Path
) -> None:
    """The third state survives corpus grading: no tag, no measurement, no pass.

    ``leaf_b`` never tags its ``mate_face``. The coincidence cannot be
    measured, and the run fails as ``constraint_unresolvable`` with the
    dangling-selector reason — never conflated with ``violated``, and never
    scored as though an unmeasurable mate held.
    """
    task = tasks["hinge-mate"]
    root = tmp_path / "untagged"
    seed_project(task, root)
    (root / "parts").mkdir(exist_ok=True)
    shutil.copy2(corpus_solutions_dir() / "hinge-mate" / "parts" / "leaf_a.py", root / "parts")
    source = (corpus_solutions_dir() / "hinge-mate" / "parts" / "leaf_b.py").read_text(
        encoding="utf-8"
    )
    lines = [line for line in source.splitlines() if '"mate_face"' not in line]
    assert len(lines) < len(source.splitlines())
    (root / "parts" / "leaf_b.py").write_text("\n".join(lines) + "\n", encoding="utf-8")
    report = grade(task, root)

    assert not report.passed
    assert any(
        r.startswith("constraint_unresolvable:c-knuckles-flush:dangling_selector")
        for r in report.reasons
    ), report.reasons
    assert not any(r.startswith("constraint_violated:c-knuckles-flush") for r in report.reasons)


def test_drawing_requirements_gate_dimensions_and_metadata_gates_material(
    tasks: Mapping[str, BenchTask],
) -> None:
    """A drawing sheet is gated on its dimensions; its metadata is gated structurally.

    ``required_texts`` was carrying a title-block sentence
    (``"18 mm Baltic birch plywood"``), so a correct shelf failed on wording.
    The rule now: every required drawing text is a dimension string, and
    manufacturing metadata is a ``metadata_requirements`` entry — a registry id
    the free-text spec must *resolve* to, and a process pack token.
    """
    for task in tasks.values():
        for requirement in task.drawings:
            for text in requirement.required_texts:
                assert DIMENSION_TEXT_RE.fullmatch(text), (
                    f"{task.id}: required drawing text {text!r} is not a dimension — "
                    "gate document prose through metadata_requirements instead"
                )
    shelf = tasks["drawing-shelf"]
    assert len(shelf.metadata) == 1
    requirement = shelf.metadata[0]
    assert requirement.part == "shelf"
    assert requirement.process == "laser_cut"
    assert requirement.material_id == "plywood-baltic-birch"
    assert "material_spec" in requirement.required_fields


def test_the_metadata_requirement_gates_the_material_not_its_wording(
    tasks: Mapping[str, BenchTask], tmp_path: Path
) -> None:
    """Both halves of the replacement, measured: it passes prose and fails a wrong stock."""
    task = tasks["drawing-shelf"]
    variant = (CORPUS_VARIANTS / "drawing-shelf" / "parts" / "shelf.py").read_text(encoding="utf-8")
    # The variant states the same stock in different words — and would have
    # failed the retired verbatim title-block match.
    assert RETIRED_MATERIAL_TEXT not in variant
    root = tmp_path / "wrong-material"
    seed_project(task, root)
    (root / "parts").mkdir(exist_ok=True)
    (root / "parts" / "shelf.py").write_text(
        variant.replace("Baltic birch plywood, 18 mm, BB/BB grade", "6061 aluminium plate"),
        encoding="utf-8",
    )
    report = grade(task, root)

    assert not report.passed
    assert "metadata_material:shelf:al-6061!=plywood-baltic-birch" in report.reasons
    # …and only that: the geometry is untouched, so nothing else fails.
    assert [reason for reason in report.reasons if not reason.startswith("metadata_")] == []


def test_no_required_check_names_a_fit_and_measures_a_volume(
    tasks: Mapping[str, BenchTask],
) -> None:
    """The audit's naming rule, pinned where it was broken.

    ``lid_register_clearance`` measured ``volume("lid/part")``: a name promising
    a fit over a check demanding an identity. The register is now measured as a
    clearance against a seeded cavity-opening gauge, and no check in the task
    reads the lid's volume at all.
    """
    source = tasks["enclosure-bosses"].check_sources()["enclosure_bosses"]
    assert 'm.clearance("lid/part", "register_gauge/part")' in source
    assert 'm.interference("lid/part", "lid_go_gauge/part")' in source
    assert 'm.volume("lid/part")' not in source
    assert "lid_register_clearance" not in source

    # …and the rule generalised over the whole corpus, so the next task cannot
    # reintroduce it: a check whose NAME promises a fit may not be implemented as
    # a single part's volume. Whether a design fits is a relation between two
    # bodies; a volume is an identity, and no window on it measures a fit.
    offenders: list[str] = []
    for task in tasks.values():
        if task.spec != "prose":
            continue
        for stem, check_source in task.check_sources().items():
            for name, predicate in _check_predicates(check_source).items():
                promises_fit = any(word in name for word in FIT_WORDS)
                if promises_fit and "m.volume(" in predicate:
                    offenders.append(f"{task.id}:{stem}:{name}")
    assert offenders == [], (
        f"checks naming a fit but measuring a volume: {offenders} — measure it against a "
        "gauge with m.clearance/m.interference, or rename it to the material budget it is"
    )


def test_every_volume_window_is_a_named_documented_constant(
    tasks: Mapping[str, BenchTask],
) -> None:
    """The audit's second rule: a volume window must be *named*, never inline.

    A volume check is only ever a **material budget** — the corpus has no way to
    ask for an exact solid, and asking for one is what ``lid_register_clearance``
    did. A budget needs a stated reason: how wide, and what deviation it is set
    below. Requiring the window to be a module-level constant is the mechanical
    half of that (an ``abs=20.0`` written inline carries no paragraph), and every
    such constant in the corpus is introduced by the comment that justifies it.
    """
    offenders: list[str] = []
    for task in tasks.values():
        if task.spec != "prose":
            continue
        for stem, check_source in task.check_sources().items():
            for name, predicate in _check_predicates(check_source).items():
                if "m.volume(" not in predicate:
                    continue
                if not re.search(r"abs=_[A-Z0-9_]*WINDOW\b", predicate):
                    offenders.append(f"{task.id}:{stem}:{name}")
    assert offenders == [], (
        f"volume checks with an unnamed tolerance: {offenders} — give the window a module "
        "constant and a comment saying which deviation it is set below"
    )


def test_the_audited_material_checks_are_named_as_budgets(
    tasks: Mapping[str, BenchTask],
) -> None:
    """The renames the 2026-07-26 audit made, pinned so they cannot drift back.

    ``tread_corner_radius`` measured a volume; so did ``gusset_is_triangular``.
    A name that states a shape fact over an arithmetic identity is the same trap
    as a name that states a fit, one step milder — it hides from the reader that
    the check will reject any other correct way of reaching that shape.
    """
    expected = {
        "bracket-101": {"material_budget"},
        "cat-step": {"tread_material_pins_r25_corners", "gusset_material_pins_triangular_profile"},
        "param-retune": {
            "tread_material_pins_r25_corners",
            "gusset_material_pins_triangular_profile",
        },
        "knob-loft": {"material_budget"},
        "drawing-shelf": {"shelf_material_budget"},
        "enclosure-bosses": {"box_material_budget"},
    }
    for task_id, names in expected.items():
        found: set[str] = set()
        for check_source in tasks[task_id].check_sources().values():
            found |= set(_check_predicates(check_source))
        assert names <= found, f"{task_id}: expected material-budget checks {names - found}"
    # …and the retired names are gone from the corpus entirely.
    retired = {"tread_corner_radius", "gusset_is_triangular", "material_volume", "shelf_material"}
    for task in tasks.values():
        for check_source in task.check_sources().values():
            assert retired.isdisjoint(_check_predicates(check_source)), task.id


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
    assert nested[0].profile_layer == "CUT"
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


def test_every_dfm_requirement_names_its_own_process(
    tasks: Mapping[str, BenchTask],
) -> None:
    """The 2026-07-26 bench defect, closed at the spec level.

    ``print-bracket`` declared no ``process`` on its DFM requirement, so the pack
    ran only against ``part.process``. ``run_dfm`` refuses to guess a process —
    correctly — so a run that never authored the field failed as
    ``dfm_failed:bracket`` and the three fdm rules the task exists to measure
    never evaluated. Grading a task on different properties depending on whether
    the model remembered a metadata line is not grading. A DFM requirement must
    therefore name the pack itself, and the parser refuses one that does not.
    """
    for task in tasks.values():
        for requirement in task.dfm:
            assert requirement.process, (
                f"{task.id}: DFM requirement for {requirement.part!r} names no process"
            )
            assert all(
                rule.startswith(f"{requirement.process}.") for rule in requirement.clean_rules
            ), f"{task.id}: clean_rules are not all from the {requirement.process} pack"

    with pytest.raises(ValueError, match="declares no process"):
        DfmRequirement.from_json({"part": "bracket", "clean_rules": ["fdm.overhang_angle"]})


@requires_bwrap
def test_dfm_rules_are_graded_even_when_the_part_omits_its_process(
    tasks: Mapping[str, BenchTask], tmp_path: Path
) -> None:
    """The defect, reproduced on the geometry that exposed it, and then absent.

    ``gpt-5.6-sol`` authored ``part.process = "fdm"`` on ``print-bracket`` seed 1
    and omitted it on seed 2 — same model, same correct ramped bracket, and seed
    2 was scored on an unresolvable-process refusal instead of on printability.
    Here the reference solution is stripped of exactly that one line: the fdm
    pack must still run and still come back clean on all three named rules, and
    the *only* thing that fails is the metadata declaration the prompt separately
    asks for, under a name that says so.
    """
    task = tasks["print-bracket"]
    root = tmp_path / "no-process"
    seed_project(task, root)
    source = (corpus_solutions_dir() / "print-bracket" / "parts" / "bracket.py").read_text(
        encoding="utf-8"
    )
    assert 'part.process = "fdm"\n' in source
    (root / "parts").mkdir(exist_ok=True)
    (root / "parts" / "bracket.py").write_text(
        source.replace('part.process = "fdm"\n', ""), encoding="utf-8"
    )
    report = grade(task, root)

    # The DFM pack evaluated on the graded geometry and found nothing…
    assert len(report.dfm) == 1
    record = report.dfm[0]
    assert "error" not in record, record
    assert record.get("process") == "fdm"
    assert record.get("source_artifact_ref"), record
    assert [reason for reason in report.reasons if reason.startswith("dfm_")] == []
    # …and the geometry checks are untouched, so the run fails on one thing only:
    # the §5.2 process declaration, named as itself.
    assert not report.passed
    assert "metadata_missing:bracket:process" in report.reasons
    assert "metadata_process:bracket:unstated!=fdm" in report.reasons
    assert [reason for reason in report.reasons if not reason.startswith("metadata_")] == []


def test_prompted_metadata_is_gated_by_a_named_metadata_check(
    tasks: Mapping[str, BenchTask],
) -> None:
    """Where a prompt asks for §5.2 metadata, something must check it.

    ``print-bracket`` and ``nest-gusset`` both ask for the manufacturing metadata
    in as many words and gated none of it: the bracket's process was reachable
    only as a precondition of the DFM check, and the gusset's ``blank_size`` only
    as a nesting failure inside the DXF export. Both are now requirements in
    their own right. The fields listed are the ones the prompt names and no
    others — a metadata requirement is not a place to add spec.
    """
    expected = {
        "print-bracket": ("bracket", {"description", "material_spec", "process", "stock_form"}),
        "nest-gusset": (
            "gusset",
            {"description", "material_spec", "process", "stock_form", "blank_size"},
        ),
        "drawing-shelf": (
            "shelf",
            {
                "description",
                "material_spec",
                "process",
                "stock_form",
                "general_tolerance",
                "finish",
            },
        ),
    }
    for task_id, (part, fields) in expected.items():
        task = tasks[task_id]
        assert len(task.metadata) == 1, f"{task_id}: expected exactly one metadata requirement"
        requirement = task.metadata[0]
        assert requirement.part == part
        assert set(requirement.required_fields) == fields, task_id
        assert requirement.process, f"{task_id}: the prompt names a process; gate it"
        assert requirement.material_id, f"{task_id}: the prompt names a material; gate it"

    # dfm-repair is the other side of the same rule: its prompt asks the run to
    # *preserve* the declared process ("repair-only ... the design intent does not
    # change"), not to author metadata, so that one field is all it gates.
    repair = tasks["dfm-repair"].metadata
    assert len(repair) == 1
    assert repair[0].part == "vent_panel"
    assert repair[0].process == "laser_cut"
    assert repair[0].required_fields == () and repair[0].material_id is None


def test_corpus_v1_raises_the_aggregate_threshold_to_the_g6_bound() -> None:
    """G6: lower-90% Wilson >= 0.70 on the gated (prose) split, over 12 tasks."""
    assert G6_AGGREGATE_THRESHOLD == 0.70
    assert G6_AGGREGATE_THRESHOLD > G2_AGGREGATE_THRESHOLD, "thresholds tune upward only"

    v0_ids = [task_id for task_id, _ in CORPUS_V0]
    v1_ids = [task_id for task_id, _ in CORPUS_V1]
    v2_ids = [task_id for task_id, _ in CORPUS]
    # A v0 archive keeps the bound it was baselined under…
    assert aggregate_threshold(v0_ids) == G2_AGGREGATE_THRESHOLD
    # …and covering corpus v1 is itself what raises it — including via the
    # seeded ids, whose variant suffix is not a different task.
    assert aggregate_threshold(v1_ids) == G6_AGGREGATE_THRESHOLD
    assert aggregate_threshold(f"{task_id}@seeded" for task_id in v1_ids) == (
        G6_AGGREGATE_THRESHOLD
    )
    # Corpus v2 (2026-08-25) is a superset of v1, so a v2 sweep still reads the
    # G6 bound: expanding the corpus never relaxed a threshold.
    assert aggregate_threshold(v2_ids) == G6_AGGREGATE_THRESHOLD
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
    # 19 corpus-v3 tasks x 3 seeds, one knob-loft failure (2026-08-25/2026-08-27
    # repoints: the sweep shape grew from 36 runs with the corpus, the bound
    # did not).
    assert (score.prose.n, score.prose.passes) == (57, 56)
    assert score.meets_gate  # 56/57 clears 0.70 and repair-fillet is 3/3
    assert score.seeded.threshold is None
    assert score.seeded.meets_threshold is None
    # Dropping the four v1 tasks leaves a sweep that no longer covers corpus
    # v1, so it is read at the v0 bound — the threshold is a fact about the v1
    # coverage, and the v2 additions neither raise nor relax it.
    without_v1 = [r for r in records if r["task_id"] not in set(CORPUS_V1_TASKS)]
    assert score_records(without_v1).threshold == G2_AGGREGATE_THRESHOLD
