# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""G13C clauses 53-55: the ``solve-*`` corpus family, and the Tier 3 mechanism.

``SOLVER.md`` Gate G13C:

53. the family graded **through the engine path**: the reference solutions pass
    their own acceptance (Tier 1), and a run that produces a correct proposal
    **without rebuilding** fails the task — asserted directly, because it is the
    clause that keeps the loop broken;
54. each new task ships prose + seeded variants and a second independent
    solution that also passes; corpus-count pins repointed with this stage
    cited;
55. the Tier 3 bench clause on the corpus-family mechanism — its own splits, its
    own first measurement at >= 3 seeds, never averaged into the v1/v2/v3
    baselines, ``insufficient_solve_seeds`` refusing a thinner one and writing
    nothing.

**Tier 3 is machinery only.** The live reference-model sweep is a detached run
this repository cannot take and does not fake, so what these clauses assert is
the mechanism and its refusal, and the honest statement of clause 55's status is
*machinery closed, measurement outstanding* — which ``heph bench score`` prints,
in both directions, and which the last test here asserts it prints.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

import pytest
from hephaestus.bench.harness import load_tasks
from hephaestus.bench.harness._grade import grade, grade_reference_solution
from hephaestus.bench.harness._seed import seed_project

REPO = Path(__file__).resolve().parents[2]
CORPUS_VARIANTS: Path = REPO / "server" / "tests" / "fixtures" / "corpus_variants"

#: The Stage 13C corpus pair, stated here so this gate suite owns its own count
#: clause rather than trusting another suite's constant.
SOLVE_PAIR: frozenset[str] = frozenset({"solve-shelf-height", "solve-boss-fit"})

#: The public corpus after this stage: twenty-three (v5) plus the solve pair.
CORPUS_SIZE_V6: int = 25


@pytest.fixture(scope="module")
def tasks() -> Mapping[str, Any]:
    return {task.id: task for task in load_tasks(specs=("prose",))}


# ==========================================================================
# clause 53 — graded through the engine path, on the REBUILT part


@pytest.mark.parametrize("task_id", sorted(SOLVE_PAIR))
def test_the_reference_solution_passes_its_own_acceptance(
    tasks: Mapping[str, Any], task_id: str, tmp_path: Path
) -> None:
    """The CI meta-test behind every task: a task no reference solution passes is broken."""
    report = grade_reference_solution(tasks[task_id], tmp_path / "project")
    assert report.passed, report.reasons


@pytest.mark.parametrize("task_id", sorted(SOLVE_PAIR))
def test_a_correct_proposal_without_rebuilding_fails_the_task(
    tasks: Mapping[str, Any], task_id: str, tmp_path: Path
) -> None:
    """**The clause that keeps the loop broken**, asserted directly.

    The project is seeded and built and NOTHING else is done — which is exactly
    the state a run is in after it has called ``propose_placement``, read a
    perfectly correct proposal, and stopped. A proposal is a measurement
    artifact that nothing applies, so the geometry is still the seed's and the
    task's own constraints still measure violated.

    The reason token says which acceptance failed and what actually failed
    about it: ``proposal_not_applied``, not ``constraint_violated``. A run that
    computed the answer and did not author it did not fail to compute.
    """
    project = tmp_path / "project"
    seed_project(tasks[task_id], project)
    report = grade(tasks[task_id], project)
    assert not report.passed
    unapplied = [reason for reason in report.reasons if reason.startswith("proposal_not_applied:")]
    assert unapplied, report.reasons
    ids = {reason.split(":")[1] for reason in unapplied}
    assert ids == {requirement.id for requirement in tasks[task_id].proposals}


@pytest.mark.parametrize("task_id", sorted(SOLVE_PAIR))
def test_the_grader_never_reads_a_proposal(
    tasks: Mapping[str, Any], task_id: str, tmp_path: Path
) -> None:
    """It would score identically if the run had never called the tool.

    Grading the computation instead of the geometry is ``VALIDATION.md`` §1's
    self-referential trap one level up, so the grader's own source is asserted
    free of the proposal store — and the graded project is asserted to carry no
    proposal generation, which is the same fact from the other side.
    """
    from hephaestus.core.project_store.layout import load_project, open_store
    from hephaestus.core.project_store.proposals import ProposalSet

    source = (REPO / "bench" / "src" / "hephaestus" / "bench" / "harness" / "_grade.py").read_text(
        encoding="utf-8"
    )
    # Calls and imports, not mentions. The grader's docstrings SAY what a
    # proposal is and why this pass does not read one — which is the point, and
    # a clause that banned the word would delete the explanation. What it may
    # not do is reach the proposal store or the tool, so those are what is
    # asserted absent, with comments and docstrings stripped first.
    code = re.sub(r'"""[\s\S]*?"""', "", source)
    code = "\n".join(line for line in code.splitlines() if not line.lstrip().startswith("#"))
    for call in ("ProposalSet(", "proposal_views(", "propose_placement(", "read_proposals("):
        assert call not in code, f"the grader calls {call}: it grades the computation"
    assert "project_store.proposals" not in code, "the grader imports the proposal store"

    project = tmp_path / "project"
    report = grade_reference_solution(tasks[task_id], project)
    assert report.passed, report.reasons
    layout = load_project(project)
    store = open_store(layout)
    try:
        assert ProposalSet(layout, store).state().generation == 0
    finally:
        store.close()


@pytest.mark.parametrize("task_id", sorted(SOLVE_PAIR))
def test_the_acceptance_is_evaluated_through_the_engine_path(
    tasks: Mapping[str, Any], task_id: str, tmp_path: Path
) -> None:
    """Each requirement comes back with the outcome ``check_assembly`` reports.

    The task's entries are installed over whatever the run declared — the same
    rule the required CHECKS follow — so a run cannot pass by declaring a
    weaker mate, or none.
    """
    report = grade_reference_solution(tasks[task_id], tmp_path / "project")
    assert report.proposals, "a solve task graded no proposal requirement"
    for record in report.proposals:
        outcome = cast("Mapping[str, Any]", record["outcome"])
        assert outcome["state"] == "satisfied", outcome
        # The row carries the engine's own number, not a boolean: a grader that
        # reported only pass/fail would leave an author with nothing to act on.
        # It is `ConstraintOutcome.residual` — `dataclasses.asdict` of geom's own
        # `ConstraintResidual` (`core/assembly.py`'s `_measure`) — so the number
        # is read where the 8C wire shape actually puts it rather than at a
        # top-level key no outcome has ever carried.
        residual = cast("Mapping[str, Any]", outcome["residual"])
        assert isinstance(residual["measured"], float)
        # And the predicate the verdict was read from, beside it: `satisfied` is
        # stored rather than derived, which is the whole of SOLVER.md §3.1.
        assert residual["satisfied"] is True


def test_the_proposal_vocabulary_is_closed_and_carries_no_expect_field() -> None:
    """One kind, and no ``expect``: only "the delivered geometry satisfies it".

    ``ConstraintRequirement`` admits ``violated`` and ``unresolvable`` because a
    task may legitimately require a mate be *checkable*. Here an entry that
    could pass while the mate stayed violated would be a solve task a proposal
    alone could clear, which is the one thing this family exists to prevent.
    """
    from hephaestus.bench.harness._tasks import PROPOSAL_CHECK_KINDS, ProposalRequirement

    assert PROPOSAL_CHECK_KINDS == ("constraint_satisfied",)
    entry: Mapping[str, Any] = {"id": "c", "kind": "coincident", "a": "a:t", "b": "b:t"}
    assert not hasattr(ProposalRequirement(entry), "expect")
    with pytest.raises(ValueError, match="vocabulary is closed"):
        ProposalRequirement.from_json(
            {"entry": {"id": "c", "kind": "coincident", "a": "a:t", "b": "b:t"}, "kind": "expect"}
        )
    with pytest.raises(ValueError, match="needs an 'entry' object"):
        ProposalRequirement.from_json({"kind": "constraint_satisfied"})
    for field in ("id", "kind", "a", "b"):
        entry = {"id": "c", "kind": "coincident", "a": "a:t", "b": "b:t"}
        del entry[field]
        with pytest.raises(ValueError, match=f"missing {field!r}"):
            ProposalRequirement.from_json({"entry": entry})


def test_a_proposal_requirement_round_trips_through_its_json_form() -> None:
    from hephaestus.bench.harness._tasks import ProposalRequirement

    payload = {
        "entry": {"id": "c-x", "kind": "fit", "a": "a:bore", "b": "b:shaft"},
        "kind": "constraint_satisfied",
        "note": "graded on the rebuilt part",
    }
    requirement = ProposalRequirement.from_json(payload)
    assert requirement.to_json() == payload
    assert requirement.id == "c-x"
    assert requirement.declaration()["provenance"] == {
        "assumed": True,
        "reason": "declared by the bench task's acceptance spec",
    }


# ==========================================================================
# clause 54 — both variants, a second independent solution, and the pins


def test_the_public_corpus_is_twenty_five_with_the_solve_pair() -> None:
    prose = {task.id for task in load_tasks(specs=("prose",))}
    assert len(prose) == CORPUS_SIZE_V6
    assert prose >= SOLVE_PAIR
    seeded = {task.id for task in load_tasks(specs=("seeded",))}
    assert {f"{task_id}@seeded" for task_id in SOLVE_PAIR} <= seeded
    assert len(seeded) == CORPUS_SIZE_V6


@pytest.mark.parametrize("task_id", sorted(SOLVE_PAIR))
def test_the_independent_second_solution_passes_the_same_acceptance(
    tasks: Mapping[str, Any], task_id: str, tmp_path: Path
) -> None:
    """``VALIDATION.md`` §1: a check written from one implementation cannot
    detect that it demands that implementation; only a second, deliberately
    different one can.

    The two solutions here differ in the **authoring act** as well as in the
    construction — the reference applies the proposal through ``set_params``,
    the variant edits the declaration itself — which is the pair of ordinary
    edit paths §0 names, exercised rather than described.
    """
    report = grade_reference_solution(
        tasks[task_id], tmp_path / "project", solutions_dir=CORPUS_VARIANTS
    )
    assert report.passed, report.reasons


@pytest.mark.parametrize("task_id", sorted(SOLVE_PAIR))
def test_the_two_solutions_are_genuinely_different(task_id: str) -> None:
    """Different files, different values, different authoring paths."""
    reference = REPO / "corpus" / "solutions" / task_id
    variant = CORPUS_VARIANTS / task_id
    assert reference.is_dir() and variant.is_dir()
    reference_files = {p.relative_to(reference) for p in reference.rglob("*") if p.is_file()}
    variant_files = {p.relative_to(variant) for p in variant.rglob("*") if p.is_file()}
    assert reference_files != variant_files, (
        "the two solutions apply the proposal the same way; §1 asks for a "
        "deliberately different implementation"
    )
    assert (reference / "params.json").is_file(), "the reference applies through set_params"
    assert not (variant / "params.json").exists(), "the variant edits the declaration instead"


@pytest.mark.parametrize(
    ("path", "needle"),
    [
        ("tests/stage6/test_g6_corpus_v1.py", "CORPUS_SIZE = 25"),
        ("server/tests/test_bench_corpus.py", "CORPUS_V6_ADDITIONS"),
        ("tests/stage9c/test_corpus_mechanisms.py", "corpus v6 is twenty-five public tasks"),
        ("tests/stage11c/test_g11c_corpus.py", "CORPUS_SIZE_NOW: int = 25"),
        ("tests/stage12c/test_g12c_ladder_and_corpus.py", "CORPUS_ADDED_AFTER_V5"),
    ],
)
def test_every_repointed_count_pin_cites_this_stage(path: str, needle: str) -> None:
    """ "Repointed **with this stage cited**" — the citation is the clause.

    A count silently edited from 23 to 25 is indistinguishable from a count that
    drifted. Each pin must carry the amendment that moved it, so a reader who
    finds the number surprising can find out why.
    """
    source = (REPO / path).read_text(encoding="utf-8")
    assert needle in source, f"{path}: pin not repointed"
    window = source[max(0, source.index(needle) - 1800) : source.index(needle) + 800]
    assert "SOLVER.md" in window and "2026-08-30" in window, (
        f"{path}: the repointed pin does not cite the Stage 13C amendment that moved it"
    )


def test_each_new_task_carries_a_dated_hand_count_budget_derivation() -> None:
    """``VALIDATION.md`` §7: a new task may not ship a bare guess."""
    for task_id in sorted(SOLVE_PAIR):
        notes = json.loads(
            (REPO / "corpus" / "tasks" / task_id / "task.json").read_text(encoding="utf-8")
        )["notes"]
        assert "hand-count" in notes
        assert "2026-08-25" in notes, "the measured-budget policy's own date"
        assert "SOLVER.md" in notes, "and the amendment that added the task"


def test_each_new_task_states_the_closed_loop_break_in_its_own_notes() -> None:
    """The family's whole reason, said where a task is read and not only in the spec."""
    for task_id in sorted(SOLVE_PAIR):
        notes = json.loads(
            (REPO / "corpus" / "tasks" / task_id / "task.json").read_text(encoding="utf-8")
        )["notes"]
        assert "never on the proposal" in notes
        assert "without rebuilding" in notes.lower() or "WITHOUT rebuilding" in notes


def test_each_new_task_tells_the_run_that_nothing_applies_the_proposal() -> None:
    """The prompt has to say it: a run cannot be graded on a rule it was not given."""
    for task_id in sorted(SOLVE_PAIR):
        prompt = json.loads(
            (REPO / "corpus" / "tasks" / task_id / "task.json").read_text(encoding="utf-8")
        )["prompt"]
        assert "nothing applies it" in prompt
        assert "graded on the rebuilt geometry" in prompt
        assert 'space="parameters"' in prompt


# ==========================================================================
# clause 55 — the Tier 3 bench clause, on the corpus-family mechanism


def test_the_solve_family_is_the_corpus_pair_and_the_vocabulary_is_closed() -> None:
    """The split cannot drift away from the corpus it claims to measure."""
    from hephaestus.bench.scoring import CORPUS_FAMILIES, FAMILY_SOLVE, SOLVE_FAMILY_TASKS

    assert set(SOLVE_FAMILY_TASKS) == set(SOLVE_PAIR)
    assert FAMILY_SOLVE in CORPUS_FAMILIES
    assert CORPUS_FAMILIES[FAMILY_SOLVE] == SOLVE_FAMILY_TASKS


@pytest.mark.parametrize("spec", ["prose", "seeded"])
def test_a_solve_run_lands_in_its_own_split_in_both_specs(spec: str) -> None:
    """Its own split — and one per spec, never merged (the G9C precedent)."""
    from hephaestus.bench.scoring import FAMILY_SOLVE, SOLVE_FAMILY_TASKS, split_name

    for task_id in SOLVE_FAMILY_TASKS:
        assert split_name(task_id, spec) == f"{FAMILY_SOLVE}-{spec}"
    assert split_name("bracket-101", spec) == spec


def _run(task_id: str, seed: int, *, passed: bool = True, spec: str = "prose") -> dict[str, Any]:
    return {
        "task_id": task_id if spec == "prose" else f"{task_id}@seeded",
        "spec": spec,
        "seed": seed,
        "passed": passed,
        "model": "reference-model",
        "date": "2026-08-30",
    }


def test_the_solve_family_is_neither_compared_against_nor_averaged_into_the_prose_bar() -> None:
    """The 0.70 bar keys on its own coverage constant and is not diluted.

    The carve-out is mechanical: ``split_name`` moves these runs out **before**
    the aggregate is formed, so a sweep over the whole corpus cannot fold them
    in through the plumbing either — which is the dilution arriving by accident
    rather than by decision.
    """
    from hephaestus.bench.scoring import FAMILY_SOLVE, score_records

    records = [_run("bracket-101", seed) for seed in (1, 2, 3)]
    records += [_run("solve-shelf-height", seed, passed=False) for seed in (1, 2, 3)]
    score = score_records(records)

    assert score.prose.n == 3, "only the non-family runs are in the gated split"
    assert score.prose.pass_rate == pytest.approx(1.0)
    family = score.family_split(FAMILY_SOLVE, "prose")
    assert family.n == 3
    assert family.pass_rate == pytest.approx(0.0)
    assert family.threshold is None and family.meets_threshold is None
    assert score.n_total == 6, "carved out, never dropped"


def test_the_family_is_baselined_on_its_first_measurement_and_never_again(
    tmp_path: Path,
) -> None:
    """Its own first measurement, at >= 3 seeds, and never re-taken."""
    from hephaestus.bench.scoring import (
        SOLVE_BASELINE_MIN_SEEDS,
        record_solve_baseline,
        score_records,
    )

    records = [
        _run(task_id, seed, spec=spec)
        for task_id in sorted(SOLVE_PAIR)
        for seed in (1, 2, 3)
        for spec in ("prose", "seeded")
    ]
    path = tmp_path / "solve_baseline.json"
    baseline = record_solve_baseline(score_records(records), path)
    assert baseline is not None
    assert baseline["family"] == "solve"
    assert baseline["min_seeds"] == SOLVE_BASELINE_MIN_SEEDS == 3
    assert baseline["threshold"] is None, "a baseline is a record, never a gate"
    splits = cast("dict[str, Any]", baseline["splits"])
    assert set(splits) == {"solve-prose", "solve-seeded"}
    for row in splits.values():
        assert cast("dict[str, Any]", row)["threshold"] is None
    assert "not a gate" in str(baseline["note"])

    again = record_solve_baseline(
        score_records([_run(task_id, 1, passed=False) for task_id in sorted(SOLVE_PAIR)]), path
    )
    assert again == baseline


def test_a_first_measurement_thinner_than_three_seeds_is_refused_by_name(
    tmp_path: Path,
) -> None:
    """Named, not silent: the alternative is a file that looks like evidence.

    A family is baselined on its FIRST measurement and never re-baselined, so a
    thin first run would enshrine noise as the family's permanent reference
    number. Asserted directly rather than by inspecting a written baseline —
    nothing is written.
    """
    from hephaestus.bench.scoring import (
        INSUFFICIENT_SOLVE_SEEDS,
        record_solve_baseline,
        score_records,
    )

    thin = [_run(task_id, seed) for task_id in sorted(SOLVE_PAIR) for seed in (1, 2)]
    path = tmp_path / "solve_baseline.json"
    with pytest.raises(ValueError) as caught:
        record_solve_baseline(score_records(thin), path)
    assert INSUFFICIENT_SOLVE_SEEDS in str(caught.value)
    assert "SOLVER.md §11 Gate G13C clause 55" in str(caught.value)
    assert not path.exists(), "nothing is written when the measurement is refused"


def test_insufficient_solve_seeds_is_a_bench_refusal_and_not_a_solve_one() -> None:
    """§6.3's closure note, asserted from both sides.

    ``insufficient_solve_seeds`` is deliberately absent from Stage 13's three
    closed solve-refusal lists: it is raised by ``bench``, never by a solve. No
    solve request can produce it and no proposal record carries it. Conflating
    the two vocabularies would make either one unfalsifiable.
    """
    from hephaestus.bench.scoring import INSUFFICIENT_SOLVE_SEEDS
    from hephaestus.core.placement import (
        SOLVE_REQUEST_REFUSALS,
        SOLVE_RESOLUTION_REFUSALS,
        SOLVE_RUNTIME_REFUSALS,
    )

    for family in (SOLVE_REQUEST_REFUSALS, SOLVE_RESOLUTION_REFUSALS, SOLVE_RUNTIME_REFUSALS):
        assert INSUFFICIENT_SOLVE_SEEDS not in family
    for module in ("core/src/hephaestus/core/placement.py", "core/src/hephaestus/geom/solve.py"):
        source = (REPO / module).read_text(encoding="utf-8")
        assert INSUFFICIENT_SOLVE_SEEDS not in source, f"{module} emits a bench-harness refusal"


def test_an_unmeasured_solve_family_is_said_out_loud_by_the_tool(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Absence of measurement is a fact about the evidence, so the tool says it.

    The live reference-model sweep is a detached run this repository cannot take
    and does not fake, so the honest statement of clause 55's status is
    *machinery closed, measurement outstanding* — and ``heph bench score`` prints
    exactly that on any archive that ran no solve task.
    """
    from hephaestus.bench import cli_bench
    from hephaestus.bench.scoring import SOLVE_BASELINE_FILENAME

    archive = tmp_path / "reference-model" / "2026-08-30"
    archive.mkdir(parents=True)
    (archive / "runs.jsonl").write_text(
        "".join(json.dumps(_run("bracket-101", seed)) + "\n" for seed in (1, 2, 3)),
        encoding="utf-8",
    )
    cli_bench.main(["bench", "score", str(archive)])
    out = capsys.readouterr().out

    assert "solve family: NOT MEASURED" in out
    for task_id in sorted(SOLVE_PAIR):
        assert task_id in out
    assert "SOLVER.md §11 Gate G13C clause 55" in out
    assert "outstanding" in out
    assert not (archive.parent / SOLVE_BASELINE_FILENAME).exists()


def test_a_measured_but_thin_solve_family_says_that_too(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The other direction, and it is a different sentence for a different fact.

    "Not measured" and "measured but not baselined" call for different actions —
    take the sweep, versus take a wider one — so the tool distinguishes them
    rather than printing one line for both.
    """
    from hephaestus.bench import cli_bench
    from hephaestus.bench.scoring import SOLVE_BASELINE_FILENAME

    archive = tmp_path / "reference-model" / "2026-08-30"
    archive.mkdir(parents=True)
    rows: Sequence[dict[str, Any]] = [
        *(_run("bracket-101", seed) for seed in (1, 2, 3)),
        *(_run(task_id, seed) for task_id in sorted(SOLVE_PAIR) for seed in (1, 2)),
    ]
    (archive / "runs.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    cli_bench.main(["bench", "score", str(archive)])
    captured = capsys.readouterr()

    assert "insufficient_solve_seeds" in captured.err
    assert "solve family: 4 runs measured, NOT BASELINED" in captured.out
    assert not (archive.parent / SOLVE_BASELINE_FILENAME).exists()


def test_the_family_mechanism_is_one_implementation_over_three_families() -> None:
    """Mission rule 6: one recorder, one seed floor, one never-re-baseline rule.

    A second copy per family would be a second place for the floor and the
    permanence rule to drift apart — and with three families now sharing it,
    the argument is no longer hypothetical.
    """
    import inspect

    from hephaestus.bench import scoring

    body = inspect.getsource(scoring.record_solve_baseline)
    assert "_record_family_baseline" in body
    assert len(body.splitlines()) < 30, (
        "record_solve_baseline grew its own logic; it is meant to be one call"
    )
    assert set(scoring.CORPUS_FAMILIES) == {"component", "scan", "solve"}
