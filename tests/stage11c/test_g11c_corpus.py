"""G11C clauses 11-13: the component corpus family, Tier 1 and its pins.

**Clause 11, Tier 1.** ``verification.md``'s meta-rule applied to two new tasks:
*a task no reference solution passes is a broken task, not a hard task.* Corpus
v2 sharpened it for every NEW task — one passing solution proves passability, and
only a second, independently authored implementation proves the acceptance grades
the engineering rather than the reference geometry back (``VALIDATION.md`` §1) —
so both are graded here, through :func:`grade_reference_solution`, the exact
function a benchmarked run's project is graded by.

What is new about these two, and why the stage needed them: **both anchor their
constraints on tags a store COMPONENT's own generator emitted**, at a non-zero
``pos``. ``bearing-shaft`` declares a ``fit`` against ``bearing_608``'s
``brg_a__bore``; ``motor-plate`` declares a ``coincident`` against
``stepper_nema17_frame``'s ``motor__mount_face`` and a ``concentric`` against its
``motor__bolt_1``, with the motor turned 45 degrees. Nothing in either task
retypes a bolt coordinate or a bore diameter, which is precisely the difference
from the ``mating_features`` field §1 retired.

**Clause 12, Tier 3, named not skipped** (amended 2026-08-29). The live
reference-model *numbers* are a detached bench run, not a pytest — no local test
can create that machine state, and this suite fabricates none. But an
independent verifier scored the clause uncovered, correctly: pinning the rule's
prose is not evidence about the rule's subject. The cause turned out not to be
the missing run at all. **There was no component split to measure.**
``score_records`` split runs by ``VALIDATION.md`` §1 spec alone, so a detached
sweep over the whole corpus would have folded ``bearing-shaft`` and
``motor-plate`` into the very number compared against 0.70 — the dilution the
clause forbids, arriving through the plumbing rather than through a decision.

So the clause was tightened (mission rule 1: tighten, never waive) into three
halves this suite gates: the family is a first-class split *per spec*
(``component-prose`` / ``component-seeded``, the G9C shape) carrying no
threshold; the carve-out makes non-dilution structural, proved by scoring a
corpus-v1 archive with and without a perfect family sweep and finding the gate
statistic unmoved; and the >= 3-seed floor is the named refusal
``insufficient_component_seeds`` on a baseline that, being the first and only
one, would otherwise enshrine noise forever. What the detached run still owns is
the numbers; what it can no longer get wrong is the shape.

**Clause 13.** Corpus-count pins repointed with this stage cited.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import pytest
from hephaestus.bench.harness import BenchTask, GradeReport, grade_reference_solution, load_tasks

REPO: Path = Path(__file__).resolve().parents[2]

#: The independently authored second implementations (one home, not a copy —
#: the same tree the server meta-suite grades from).
CORPUS_VARIANTS: Path = REPO / "server" / "tests" / "fixtures" / "corpus_variants"

#: The Stage 11 corpus-v4 additions, stated here so the gate suite owns its own
#: count clause rather than trusting another suite's constant.
COMPONENT_PAIR: frozenset[str] = frozenset({"bearing-shaft", "motor-plate"})

#: The public corpus after this stage: nineteen (v3) plus the component pair.
CORPUS_SIZE_V4: int = 21

#: What the corpus is TODAY. The v4 constant above is what Stage 11 added and is
#: what this suite's clause is about; the live count moved again on 2026-08-29
#: when MESH_INGEST.md §7.5 (Stage 12C, G12C clause 50) added the scan family.
#: Both are kept: a clause that asserted only the live total would stop saying
#: what this stage contributed.
CORPUS_SIZE_NOW: int = 23


def _mapping(value: Any) -> Mapping[str, Any]:
    assert isinstance(value, dict), f"expected a mapping record, got {value!r}"
    return cast("Mapping[str, Any]", value)


@pytest.fixture(scope="module")
def component_tasks() -> dict[str, BenchTask]:
    return {task.id: task for task in load_tasks(sorted(COMPONENT_PAIR))}


# ==========================================================================
# clause 11 — Tier 1, both tasks, both solutions


def _assert_acceptance(label: str, task: BenchTask, report: GradeReport) -> None:
    """The whole acceptance, judged on one grade report."""
    assert report.passed, f"{label} solution failed: {report.reasons}"
    for name, value in report.checks.items():
        assert _mapping(value).get("pass") is True, f"{label}: check {name} did not pass: {value}"
    assert len(report.constraints) == len(task.constraints)
    for record, constraint in zip(report.constraints, task.constraints, strict=True):
        outcome = _mapping(_mapping(record).get("outcome"))
        assert outcome.get("state") == constraint.expect, record
        # Every constraint resolved against the run's OWN built geometry, not
        # against a declaration: the anchor records carry the artifact they were
        # extracted from.
        for side in ("a", "b"):
            assert _mapping(outcome[side]).get("artifact_ref"), outcome
    assert report.restored_protected == ()


class TestBearingShaftIsGradedThroughTheEnginePath:
    def test_the_acceptance_declares_a_fit_on_the_stores_own_bore_tags(
        self, component_tasks: dict[str, BenchTask]
    ) -> None:
        """Structural pin: the anchors are emitted tag names, not retyped numbers.

        ``brg_a__bore`` is the ``<instance>__<name>`` form §2.2 fixes, and it
        exists only because the store's interface region emitted it during the
        run's own build. A task that named ``shaft:journal_a`` on both sides
        would grade the run against itself.
        """
        task = component_tasks["bearing-shaft"]
        by_id = {constraint.id: constraint for constraint in task.constraints}
        assert set(by_id) == {"c-fit-a", "c-fit-b"}
        for constraint in task.constraints:
            assert constraint.entry["kind"] == "fit"
            assert constraint.expect == "satisfied"
            assert str(constraint.entry["a"]).startswith("bearings:brg_")
            assert "__bore" in str(constraint.entry["a"])
            assert str(constraint.entry["b"]).startswith("shaft:journal_")
        assert task.declared_parts() == frozenset({"bearings", "shaft"})

    def test_the_reference_solution_passes_its_own_acceptance(
        self, component_tasks: dict[str, BenchTask], tmp_path: Path
    ) -> None:
        task = component_tasks["bearing-shaft"]
        _assert_acceptance("reference", task, grade_reference_solution(task, tmp_path / "project"))

    def test_the_independent_second_solution_passes_the_same_acceptance(
        self, component_tasks: dict[str, BenchTask], tmp_path: Path
    ) -> None:
        """A different build of the shaft — extruded sketches, top-down, different
        selectors — with the same interface: the acceptance grades the fit, not
        the reference geometry back (``VALIDATION.md`` §1)."""
        task = component_tasks["bearing-shaft"]
        _assert_acceptance(
            "variant",
            task,
            grade_reference_solution(task, tmp_path / "project", solutions_dir=CORPUS_VARIANTS),
        )

    def test_the_fit_really_measures_the_clearance(
        self, component_tasks: dict[str, BenchTask], tmp_path: Path
    ) -> None:
        """The graded number, restated independently of the task files.

        A 608 bore is 4.0 mm in radius; the task's journal is turned 0.02 mm
        undersize, so the radial clearance is 0.01 mm. If the engine ever
        started reporting a diametral clearance, or the journal drifted to
        nominal, this moves a *known* number rather than merely failing.
        """
        task = component_tasks["bearing-shaft"]
        report = grade_reference_solution(task, tmp_path / "project")
        for record in report.constraints:
            residual = _mapping(_mapping(_mapping(record)["outcome"])["residual"])
            assert residual["measured"] == pytest.approx(0.01, abs=1e-9)
            values = dict(cast("Any", residual["values"]))
            assert values["hole_radius_mm"] == pytest.approx(4.0)
            assert values["shaft_radius_mm"] == pytest.approx(3.99)


class TestMotorPlateIsGradedThroughTheEnginePath:
    def test_the_acceptance_declares_a_coincident_and_a_bolt_circle_concentric(
        self, component_tasks: dict[str, BenchTask]
    ) -> None:
        task = component_tasks["motor-plate"]
        kinds = {constraint.id: str(constraint.entry["kind"]) for constraint in task.constraints}
        assert kinds == {"c-mount-flush": "coincident", "c-bolt-circle": "concentric"}
        anchors = {constraint.id: str(constraint.entry["a"]) for constraint in task.constraints}
        assert anchors["c-mount-flush"] == "motor:motor__mount_face"
        assert anchors["c-bolt-circle"] == "motor:motor__bolt_1"
        assert task.declared_parts() == frozenset({"motor", "plate"})

    def test_the_reference_solution_passes_its_own_acceptance(
        self, component_tasks: dict[str, BenchTask], tmp_path: Path
    ) -> None:
        task = component_tasks["motor-plate"]
        _assert_acceptance("reference", task, grade_reference_solution(task, tmp_path / "project"))

    def test_the_independent_second_solution_passes_the_same_acceptance(
        self, component_tasks: dict[str, BenchTask], tmp_path: Path
    ) -> None:
        """A plate built as one extruded profile with the holes cut in the sketch,
        and both tags found by different selectors. Same interface, different
        construction."""
        task = component_tasks["motor-plate"]
        _assert_acceptance(
            "variant",
            task,
            grade_reference_solution(task, tmp_path / "project", solutions_dir=CORPUS_VARIANTS),
        )


@pytest.mark.parametrize("task_id", sorted(COMPONENT_PAIR))
def test_the_component_is_instanced_at_a_non_zero_pos(task_id: str) -> None:
    """Clause 11's own words: "both instanced at a non-zero ``pos``".

    Read off the reference solution's pasted fragment rather than asserted about
    the task, because the *placement* is what §2.3's second verification build
    exists for: a store interface verified only in the generator's pos-free
    frame verifies the wrong thing. A fragment placed at the origin would make
    both tasks pass while proving nothing about placement.
    """
    solutions = REPO / "corpus" / "solutions" / task_id / "parts"
    # `render_fragment` emits the placement as `_<instance> = Pos(...) [* Rot(...)] *
    # _<instance>_<root>` — the one line whose left side is the instance name the
    # tag literals are scoped by. Matching that shape rather than any `Pos(` is
    # what keeps a solution's own construction out of the scan.
    placement = re.compile(
        r"^_(?P<inst>\w+) = (?:Pos|Rot)\([^)]*\)"
        r"(?: \* (?:Pos|Rot)\([^)]*\))* \* _(?P=inst)_"
    )
    placements = [
        line
        for path in sorted(solutions.glob("*.py"))
        for line in path.read_text(encoding="utf-8").splitlines()
        if placement.match(line)
    ]
    assert placements, f"{task_id}: no store instance placement found"
    for line in placements:
        numbers = [float(token) for token in re.findall(r"-?\d+\.\d+", line)]
        assert numbers, f"{task_id}: placement carries no literals: {line}"
        assert any(value != 0.0 for value in numbers), f"{task_id}: placed at the origin: {line}"


def test_the_motor_is_placed_under_a_rotation_as_well_as_a_translation() -> None:
    """The stronger half of "non-zero pos", and the one §2.1 is really about.

    A pure translation cannot distinguish a measure-ordered selector from an
    axis-ordered one. The 45 degree ``Rot`` can, and does: it is what makes
    ``motor-plate`` evidence that the shipped generator's selectors survive a
    consumer's placement rather than merely evidence that they run.
    """
    source = (REPO / "corpus" / "solutions" / "motor-plate" / "parts" / "motor.py").read_text(
        encoding="utf-8"
    )
    assert "Rot(0.0, 0.0, 45.0)" in source


# ==========================================================================
# clause 12 — Tier 3, named not skipped


def test_the_tier_3_rule_is_recorded_in_the_spec_and_follows_the_g9c_precedent() -> None:
    """Named, not skipped: the clause's own text, pinned.

    No local pytest can produce a live reference-model measurement, so this one
    asserts that the rule governing it still says what it said. The three
    properties that must survive: the component family is **its own split**,
    baselined on **its own first measurement** with the reference model at
    **>= 3 seeds**, and **neither compared against nor averaged into** the v1/v2
    baselines — so the existing 0.70 prose bar keys on its own coverage and is
    not diluted. Re-baselining any combined bar is its own future amendment, and
    a run that quietly averaged the splits would be exactly the dilution
    ``VALIDATION.md`` §1 forbids.

    The 2026-08-29 amendment is pinned here too, in the same breath, because it
    is what turned those words into machinery: this test used to be the ONLY
    evidence behind the clause, which is why a verifier scored it uncovered. It
    is now the smallest of the clause's cases, not the whole of it — but the
    amendment's own terms have to stay in the spec, or the machinery below could
    be deleted with nothing in the document objecting.
    """
    spec = (REPO / "PARTS_STORE.md").read_text(encoding="utf-8")
    raw = spec.split("12. **Corpus, Tier 3, named not skipped.**", 1)[1].split("13.", 1)[0]
    # The spec is hard-wrapped, so every phrase below would otherwise be split
    # across a newline and an indent: match the prose, not the line breaks.
    clause = " ".join(raw.split())
    assert "its own split" in clause
    assert "its own first measurement" in clause
    assert "3 seeds" in clause
    assert "neither compared against nor averaged into" in clause
    assert "0.70" in clause
    assert "KINEMATICS.md" in clause, "the clause follows the G9C precedent by name"
    # The 2026-08-29 amendment's own terms: the closed family vocabulary, the
    # per-spec split shape, the carve-out that makes non-dilution structural,
    # and the named refusal that guards the >= 3-seed floor.
    assert "Amendment, 2026-08-29" in clause
    assert "CORPUS_FAMILIES" in clause
    assert "component-prose" in clause and "component-seeded" in clause
    assert "carved out" in clause
    assert "insufficient_component_seeds" in clause
    assert "record_component_baseline" in clause
    # The 2026-08-29 repair pass's own two terms. (b)'s byte-identity sentence
    # was false as first written and is now both true and asserted, and the
    # measurement's status is stated in the clause rather than inferred from a
    # green matrix — the two findings this clause was reopened for.
    assert "byte for byte" in clause
    assert "measurement outstanding" in clause
    assert "NOT MEASURED" in clause


def test_the_component_split_is_not_gated_by_the_existing_aggregate_bar() -> None:
    """The dilution the rule forbids, checked where it would actually happen.

    ``aggregate_threshold`` reads the G6 bound off *corpus-v1 coverage*. Adding
    two tasks must not have changed which sweeps clear it — and a sweep of only
    the component pair covers no v1 task, so it is read at the v0 bound rather
    than being scored against 0.70.
    """
    from hephaestus.bench.scoring import aggregate_threshold

    component_only = aggregate_threshold(sorted(COMPONENT_PAIR))
    v1_covering = aggregate_threshold(task.id for task in load_tasks(specs=("prose",)))
    assert component_only < v1_covering, (
        "a component-only sweep covers no corpus-v1 task, so it cannot be read at the "
        "G6 bound — averaging it into the v1 baseline is what G11C clause 12 forbids"
    )


# --------------------------------------------------------------------------
# clause 12, amended 2026-08-29: the split is machinery, not a promise.
#
# The verifier that scored this clause uncovered was right, and the cause was
# not the missing bench run: **there was no component split to measure.**
# ``score_records`` split by ``VALIDATION.md`` §1 spec alone, so a detached
# sweep of the whole corpus would have folded the two new tasks into the number
# compared against 0.70 — the dilution the clause forbids, arriving through the
# plumbing. The cases below gate the three halves the amendment adds: the split
# exists per spec and carries no threshold; the carve-out makes non-dilution
# structural; and the >= 3-seed floor is a named refusal on the first (and only)
# baselining. The live reference-model numbers stay a detached run, and this
# repository fabricates none of them.


def _run(task_id: str, seed: int, *, passed: bool = True, spec: str = "prose") -> dict[str, Any]:
    """One run record in ``RunRecord.to_json()`` shape — the unit scoring reads."""
    return {
        "task_id": task_id,
        "spec": spec,
        "seed": seed,
        "passed": passed,
        "model": "reference-model",
        "date": "2026-08-29",
    }


def _seeded(task_id: str) -> str:
    from hephaestus.bench.metrics import SEEDED_SUFFIX

    return task_id + SEEDED_SUFFIX


def test_the_component_family_is_the_corpus_pair_and_the_vocabulary_is_closed() -> None:
    """The split cannot drift away from the corpus it claims to measure.

    ``COMPONENT_FAMILY_TASKS`` is what the scorer carves out; ``COMPONENT_PAIR``
    is what this stage added to the corpus. If those two ever disagree, either a
    new component task is being averaged into the 0.70 bar or the bar is losing
    a task it was baselined over — both silent, both exactly what clause 12
    exists to prevent. And ``CORPUS_FAMILIES`` is closed: G9C's mechanism family
    is deliberately NOT in it, because that split is G9C's gate text to amend.

    Repointed 2026-08-29 (MESH_INGEST.md §7.5, Stage 12C / G12C clause 51),
    which registers a SECOND family — the scan pair — under the same rule and
    with its own baseline file. The vocabulary is still closed and is still
    asserted as an exact mapping, so a third family added silently fails here;
    what moved is the enumeration, not the clause. G9C's mechanism family is
    still deliberately absent, for the reason above.
    """
    from hephaestus.bench.scoring import (
        COMPONENT_FAMILY_TASKS,
        CORPUS_FAMILIES,
        FAMILY_COMPONENT,
        FAMILY_SCAN,
        SCAN_FAMILY_TASKS,
    )

    assert set(COMPONENT_FAMILY_TASKS) == set(COMPONENT_PAIR)
    assert dict(CORPUS_FAMILIES) == {
        FAMILY_COMPONENT: COMPONENT_FAMILY_TASKS,
        FAMILY_SCAN: SCAN_FAMILY_TASKS,
    }


@pytest.mark.parametrize("spec", ["prose", "seeded"])
def test_a_component_run_lands_in_its_own_split_in_both_specs(spec: str) -> None:
    """Its own split — and, per the G9C precedent, one per spec, never merged.

    A single family split holding both specs would satisfy the clause's sentence
    while breaking ``VALIDATION.md`` §1, so the family is split the way G9C
    splits its mechanism family: ``component-prose`` and ``component-seeded``.
    """
    from hephaestus.bench.scoring import FAMILY_COMPONENT, family_split_name, score_records

    task_id = "bearing-shaft" if spec == "prose" else _seeded("bearing-shaft")
    score = score_records([_run(task_id, seed, spec=spec) for seed in (1, 2, 3)])
    row = score.family_split(FAMILY_COMPONENT, spec)
    assert (row.n, row.passes) == (3, 3)
    assert row.spec == family_split_name(FAMILY_COMPONENT, spec)
    # Nothing gates it, so nothing can compare it: never False, always None.
    assert row.threshold is None
    assert row.meets_threshold is None
    # …and the base splits it was carved out of saw none of those runs.
    assert (score.prose.n, score.seeded.n) == (0, 0)
    assert score.n == 0 and score.meets_gate is False


def test_component_runs_are_not_averaged_into_the_gated_v1_number() -> None:
    """The forbidden averaging, checked where a real sweep would perform it.

    A corpus-v1-covering archive is scored, then scored again with a perfect
    sweep of the component family added. Under the pre-amendment splitter the
    family's runs were ``prose`` runs and every one of these numbers moved. The
    gate statistic must not move by a digit, or the 0.70 bar has stopped keying
    on its own coverage.
    """
    from hephaestus.bench.scoring import FAMILY_COMPONENT, score_records

    v1 = [
        _run(task_id, seed, passed=seed < 3)
        for task_id in sorted(
            {task.id for task in load_tasks(specs=("prose",))} - set(COMPONENT_PAIR)
        )
        for seed in (1, 2, 3)
    ]
    before = score_records(v1)
    family = [_run(task_id, seed) for task_id in sorted(COMPONENT_PAIR) for seed in (1, 2, 3)]
    after = score_records([*v1, *family])

    assert before.threshold == pytest.approx(0.70), "the fixture really is a v1 archive"
    assert after.threshold == before.threshold
    assert (after.n, after.passes) == (before.n, before.passes)
    assert after.aggregate == before.aggregate
    assert after.wilson_lower_90 == before.wilson_lower_90
    assert after.meets_gate is before.meets_gate
    # The runs were not dropped on the floor — they went somewhere, and the
    # whole-archive totals still account for every one of them.
    assert after.family_split(FAMILY_COMPONENT, "prose").n == len(family)
    assert after.n_total == before.n_total + len(family)


def test_an_archive_without_the_family_scores_exactly_as_it_did_before() -> None:
    """The carve-out is invisible to every archive measured before this stage.

    ``bench/results`` and ``bench/archive`` predate the component tasks, so the
    amendment must not add a key, a row or a number to their artifacts. A family
    split appears only when it has runs — asserted here on the artifact itself,
    because that is the file the leaderboard and every future reader consume.

    Asserted on the **whole** split payload, not on the set of split names.
    That earlier, weaker assertion is why clause 12(b)'s "byte-identical" claim
    could be false while this test was green: a 2026-08-29 verifier found
    ``min_seeds_per_task`` added to every split, which adds no row and moves no
    number but does change the file. The key now serialises on family splits
    only (``scoring.SplitScore.to_json``), and the fixed split payloads are
    pinned here key by key so the next such addition fails loudly.
    """
    from hephaestus.bench.scoring import score_records

    payload = score_records([_run("bracket-101", seed) for seed in (1, 2, 3)]).to_json()
    splits = cast("dict[str, Any]", payload["splits"])
    assert set(splits) == {"prose", "seeded"}
    fixed = {
        "spec",
        "n",
        "passes",
        "pass_rate",
        "wilson_lower_90",
        "threshold",
        "meets_threshold",
        "metrics",
    }
    for name, row in splits.items():
        assert set(_mapping(row)) == fixed, f"the {name} split's artifact shape moved"

    # The other side of the asymmetry: a family split *does* carry the seed
    # floor's input, because that is the one row whose baseline reads it. Pinned
    # here so "emit it nowhere" is not an equally passing way to satisfy this.
    with_family = score_records(
        [
            *[_run("bracket-101", seed) for seed in (1, 2, 3)],
            *[_run(task_id, seed) for task_id in sorted(COMPONENT_PAIR) for seed in (1, 2, 3)],
        ]
    ).to_json()
    family_rows = cast("dict[str, Any]", with_family["splits"])
    assert set(_mapping(family_rows["component-prose"])) == fixed | {"min_seeds_per_task"}
    assert _mapping(family_rows["component-prose"])["min_seeds_per_task"] == 3
    assert set(_mapping(family_rows["prose"])) == fixed


#: The archives whose stored artifact the current scorer reproduces exactly.
#: The other three in ``bench/results`` diverged *before* Stage 11 — a
#: ``--date``-named directory (``2026-08-27-mechanism-baseline``) and two
#: artifacts written by scorers older than the §8 metric block — and this stage
#: neither caused nor repairs that; naming the two clean witnesses is the honest
#: scope for a claim about what this stage changed.
BYTE_STABLE_ARCHIVES: tuple[str, ...] = (
    "gpt-5.6-sol/2026-08-03",
    "gpt-5.6-sol/2026-08-13",
)


@pytest.mark.parametrize("archive", BYTE_STABLE_ARCHIVES)
def test_a_pre_stage_archive_re_scores_to_the_byte_identical_artifact(archive: str) -> None:
    """Clause 12(b), the sentence itself, against the real checked-in evidence.

    Mission rule 2 makes ``bench/results/<model>/<date>.json`` archived evidence.
    An amendment that quietly rewrites it on the next re-score has damaged the
    record even when no number moves, so the claim is asserted on **bytes** —
    the same comparison :func:`scoring.write_score` would perform — over
    archives that predate the component family entirely. Nothing is written:
    the artifact is rendered in memory and compared against the file.
    """
    from hephaestus.bench.scoring import score_directory

    directory = REPO / "bench" / "results" / archive
    # EVIDENCE-BOUND, and it must say so rather than pass by luck. Several §8
    # metrics (build_failures, build_recoveries, clarification_refusals) are
    # derived from the PER-RUN directories beside `runs.jsonl`, and those are
    # deliberately not committed — `git ls-files` finds one tracked file here
    # against 74 on a machine that ran the sweep. Re-scoring without them
    # yields zeros for exactly those fields, so this comparison can only ever
    # hold where the complete archive exists. It passed locally and failed in
    # CI for that reason alone (run 33274622760): the assertion was reading
    # evidence CI never had. A skip here is a statement about the evidence,
    # not about the claim; the guard below pins that the skip can fire for no
    # other reason.
    per_run = [child for child in directory.iterdir() if child.is_dir()]
    if not per_run:
        pytest.skip(
            f"{archive} carries runs.jsonl without its per-run directories; "
            "clause 12(b)'s byte comparison is asserted only where the complete "
            "archive exists (see the CI scope note)"
        )
    stored = (REPO / "bench" / "results" / f"{archive}.json").read_text(encoding="utf-8")
    rendered = json.dumps(score_directory(directory).to_json(), indent=2, sort_keys=True) + "\n"
    assert rendered == stored, f"re-scoring {archive} no longer reproduces its stored artifact"


@pytest.mark.parametrize("archive", BYTE_STABLE_ARCHIVES)
def test_the_byte_comparison_skips_only_for_a_missing_per_run_archive(archive: str) -> None:
    """The skip above may mean one thing and one thing only.

    A conditional skip is a hole in a gate unless its condition is itself
    pinned: without this, "the archive is incomplete" could silently become
    "any environment where the test is inconvenient". `runs.jsonl` is tracked
    in every case, so its presence is what distinguishes an incomplete archive
    from a missing one, and a missing one is a failure rather than a skip.
    """
    directory = REPO / "bench" / "results" / archive
    assert directory.is_dir(), f"{archive} is absent entirely, which is not a skip condition"
    assert (directory / "runs.jsonl").is_file(), (
        f"{archive} has no runs.jsonl; the archive is broken rather than incomplete"
    )


def test_no_archive_in_the_repository_grows_a_family_row() -> None:
    """The other half of 12(b), over *every* archive rather than two.

    Byte identity cannot be claimed for the three archives that had already
    drifted, but the property this clause actually protects can be, and is: no
    archive in ``bench/results`` carries a component-family run, so none of them
    grows a family split row and none of their gate-bearing numbers is computed
    over a run the 0.70 bar was not baselined over.
    """
    from hephaestus.bench.scoring import FAMILY_COMPONENT, score_directory, split_family

    results = REPO / "bench" / "results"
    archives = sorted(p for p in results.glob("*/*") if p.is_dir() and (p / "runs.jsonl").is_file())
    assert archives, "bench/results carries no archive; this test would prove nothing"
    for directory in archives:
        score = score_directory(directory)
        assert set(score.splits) == {"prose", "seeded"}, f"{directory} grew a split"
        assert all(split_family(name) is None for name in score.splits)
        for spec in ("prose", "seeded"):
            assert score.family_split(FAMILY_COMPONENT, spec).n == 0


def test_the_component_baseline_is_written_once_and_never_re_baselined(tmp_path: Path) -> None:
    """Its own first measurement: recorded once, and later runs cannot move it.

    The payload carries no threshold and says in its own text that it is neither
    compared against nor averaged into the v1/v2 baselines — so a reader who
    finds the file without the spec still cannot mistake it for a gate.
    """
    from hephaestus.bench.scoring import (
        COMPONENT_BASELINE_FILENAME,
        record_component_baseline,
        score_records,
    )

    path = tmp_path / COMPONENT_BASELINE_FILENAME
    first = score_records(
        [
            _run(task_id, seed, passed=seed < 3)
            for task_id in sorted(COMPONENT_PAIR)
            for seed in (1, 2, 3)
        ]
    )
    baseline = record_component_baseline(first, path)
    assert baseline is not None
    assert baseline["family"] == "component"
    assert sorted(cast("list[str]", baseline["tasks"])) == sorted(COMPONENT_PAIR)
    assert baseline["threshold"] is None
    assert baseline["model"] == "reference-model"
    rows = cast("dict[str, Any]", baseline["splits"])
    assert set(rows) == {"component-prose"}
    prose_row = _mapping(rows["component-prose"])
    assert (prose_row["n"], prose_row["passes"]) == (6, 4)
    assert prose_row["min_seeds_per_task"] == 3
    note = cast("str", baseline["note"])
    assert "neither compared against nor averaged into" in note
    assert "G11C clause 12" in note

    better = score_records(
        [_run(task_id, seed) for task_id in sorted(COMPONENT_PAIR) for seed in (1, 2, 3)]
    )
    assert record_component_baseline(better, path) == baseline
    assert json.loads(path.read_text(encoding="utf-8")) == baseline


def test_both_specs_are_baselined_side_by_side_and_never_averaged(tmp_path: Path) -> None:
    """Two halves, two rows, no mean anywhere in the file."""
    from hephaestus.bench.scoring import (
        COMPONENT_BASELINE_FILENAME,
        record_component_baseline,
        score_records,
    )

    score = score_records(
        [
            *[_run(t, s, passed=False) for t in sorted(COMPONENT_PAIR) for s in (1, 2, 3)],
            *[
                _run(_seeded(t), s, spec="seeded")
                for t in sorted(COMPONENT_PAIR)
                for s in (1, 2, 3)
            ],
        ]
    )
    baseline = record_component_baseline(score, tmp_path / COMPONENT_BASELINE_FILENAME)
    assert baseline is not None
    rows = cast("dict[str, Any]", baseline["splits"])
    assert set(rows) == {"component-prose", "component-seeded"}
    assert _mapping(rows["component-prose"])["pass_rate"] == 0.0
    assert _mapping(rows["component-seeded"])["pass_rate"] == 1.0
    # 0.5 is the mean of the two halves; it must appear nowhere in the artifact.
    assert "0.5" not in json.dumps(baseline)


@pytest.mark.parametrize("seeds", [(1,), (1, 2)])
def test_a_first_measurement_below_three_seeds_is_refused_by_name(
    tmp_path: Path, seeds: tuple[int, ...]
) -> None:
    """The >= 3-seed floor, enforced where it is still enforceable.

    "Baselined on its FIRST measurement" and "never re-baselined" together mean
    a thin first run becomes the family's permanent reference number. So a
    baseline below three distinct seeds per task is refused BY NAME and nothing
    is written — a refusal, never a quietly recorded number.
    """
    from hephaestus.bench.scoring import (
        COMPONENT_BASELINE_FILENAME,
        INSUFFICIENT_COMPONENT_SEEDS,
        record_component_baseline,
        score_records,
    )

    path = tmp_path / COMPONENT_BASELINE_FILENAME
    score = score_records(
        [_run(task_id, seed) for task_id in sorted(COMPONENT_PAIR) for seed in seeds]
    )
    with pytest.raises(ValueError) as excinfo:
        record_component_baseline(score, path)
    message = str(excinfo.value)
    assert message.startswith(INSUFFICIENT_COMPONENT_SEEDS)
    assert f"component-prose={len(seeds)}" in message, "the refusal names how thin it was"
    assert not path.exists(), "a refused baseline writes nothing"


def test_one_thinly_measured_task_cannot_hide_behind_a_thick_one(tmp_path: Path) -> None:
    """The floor is per task, not a mean over the family.

    Six seeds of ``bearing-shaft`` and one of ``motor-plate`` average to 3.5 and
    are still not a >= 3-seed measurement of the family.
    """
    from hephaestus.bench.scoring import (
        COMPONENT_BASELINE_FILENAME,
        INSUFFICIENT_COMPONENT_SEEDS,
        record_component_baseline,
        score_records,
    )

    path = tmp_path / COMPONENT_BASELINE_FILENAME
    score = score_records(
        [
            *[_run("bearing-shaft", seed) for seed in range(6)],
            _run("motor-plate", 1),
        ]
    )
    with pytest.raises(ValueError, match=INSUFFICIENT_COMPONENT_SEEDS):
        record_component_baseline(score, path)
    assert not path.exists()


def test_exactly_three_seeds_is_enough_and_a_repeated_seed_is_not(tmp_path: Path) -> None:
    """The boundary, both sides — and seeds are counted distinct, not tallied.

    Three runs of one seed is one seed measured three times; treating it as three
    would let a re-run of the same seed buy the floor.
    """
    from hephaestus.bench.scoring import (
        COMPONENT_BASELINE_FILENAME,
        INSUFFICIENT_COMPONENT_SEEDS,
        record_component_baseline,
        score_records,
    )

    at_floor = score_records(
        [_run(task_id, seed) for task_id in sorted(COMPONENT_PAIR) for seed in (1, 2, 3)]
    )
    assert record_component_baseline(at_floor, tmp_path / COMPONENT_BASELINE_FILENAME) is not None

    repeated = score_records(
        [_run(task_id, 1) for task_id in sorted(COMPONENT_PAIR) for _ in range(3)]
    )
    path = tmp_path / "repeated" / COMPONENT_BASELINE_FILENAME
    with pytest.raises(ValueError, match=INSUFFICIENT_COMPONENT_SEEDS):
        record_component_baseline(repeated, path)
    assert not path.exists()


def test_an_unmeasured_family_is_no_baseline_rather_than_a_zero(tmp_path: Path) -> None:
    """No runs is an absence of evidence, and never a recorded 0.0."""
    from hephaestus.bench.scoring import (
        COMPONENT_BASELINE_FILENAME,
        record_component_baseline,
        score_records,
    )

    path = tmp_path / COMPONENT_BASELINE_FILENAME
    score = score_records([_run("bracket-101", seed) for seed in (1, 2, 3)])
    assert record_component_baseline(score, path) is None
    assert not path.exists()


def test_the_bench_score_command_writes_the_component_baseline(tmp_path: Path) -> None:
    """The detached run's own path: nobody has to remember to call it.

    ``heph bench score`` is what a bench run's operator invokes, so the baseline
    is written there or it is not written at all.
    """
    from hephaestus.bench import cli_bench
    from hephaestus.bench.scoring import COMPONENT_BASELINE_FILENAME, SEEDED_BASELINE_FILENAME

    archive = tmp_path / "reference-model" / "2026-08-29"
    archive.mkdir(parents=True)
    rows = [
        *[_run(task_id, seed) for task_id in sorted(COMPONENT_PAIR) for seed in (1, 2, 3)],
        *[_run("bracket-101", seed) for seed in (1, 2, 3)],
    ]
    (archive / "runs.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    cli_bench.main(["bench", "score", str(archive)])
    written = json.loads((archive.parent / COMPONENT_BASELINE_FILENAME).read_text(encoding="utf-8"))
    assert _mapping(_mapping(written["splits"])["component-prose"])["n"] == 6
    # The seeded baseline is a different measurement in a different file.
    assert not (archive.parent / SEEDED_BASELINE_FILENAME).exists()


def test_a_refused_component_baseline_is_reported_not_swallowed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A family whose baseline was refused must not look like one never run."""
    from hephaestus.bench import cli_bench
    from hephaestus.bench.scoring import COMPONENT_BASELINE_FILENAME, INSUFFICIENT_COMPONENT_SEEDS

    archive = tmp_path / "reference-model" / "2026-08-29"
    archive.mkdir(parents=True)
    rows = [
        *[_run(task_id, 1) for task_id in sorted(COMPONENT_PAIR)],
        *[_run("bracket-101", seed) for seed in (1, 2, 3)],
    ]
    (archive / "runs.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    cli_bench.main(["bench", "score", str(archive)])
    captured = capsys.readouterr()
    assert INSUFFICIENT_COMPONENT_SEEDS in captured.err
    assert not (archive.parent / COMPONENT_BASELINE_FILENAME).exists()
    # And the stdout table does not quietly look complete: a measured-but-
    # unbaselined family is named there too, next to the numbers a reader reads.
    assert "NOT BASELINED" in captured.out


def _score_a_family_free_archive(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> tuple[str, Path]:
    """Score an archive that measured no family task; return (stdout, baseline path)."""
    from hephaestus.bench import cli_bench
    from hephaestus.bench.scoring import COMPONENT_BASELINE_FILENAME

    archive = tmp_path / "reference-model" / "2026-08-29"
    archive.mkdir(parents=True)
    (archive / "runs.jsonl").write_text(
        "".join(json.dumps(_run("bracket-101", seed)) + "\n" for seed in (1, 2, 3)),
        encoding="utf-8",
    )
    cli_bench.main(["bench", "score", str(archive)])
    return capsys.readouterr().out, archive.parent / COMPONENT_BASELINE_FILENAME


def test_an_unmeasured_family_is_said_out_loud_by_the_tool_that_reads_the_evidence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Clause 12, "the measurement": absence is reported, never left silent.

    The live reference-model numbers are a detached run this repository cannot
    take and does not fake, so the honest statement of clause 12's status is
    *machinery closed, measurement outstanding*. A 2026-08-29 verifier's
    strongest objection was not that the run is missing but that nothing says
    so: an operator reading a green matrix would infer a baseline that does not
    exist. So ``heph bench score`` states it on every archive that measured no
    family task, naming the tasks and the file that would hold the answer.
    """
    out, path = _score_a_family_free_archive(tmp_path, capsys)
    assert not path.exists()
    assert "component family: NOT MEASURED" in out
    for task_id in sorted(COMPONENT_PAIR):
        assert task_id in out
    assert "outstanding" in out


def test_a_recorded_baseline_stops_the_outstanding_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The negative control, so the line reports the world rather than a constant.

    Once ``component_baseline.json`` exists, an archive that simply did not run
    the family says exactly that and points at the recorded measurement — the
    same test that proves the warning fires proves it stops firing, or it is a
    banner rather than a report.

    Scoped to THIS family's line on 2026-08-29 (MESH_INGEST.md §7.5, Stage 12C):
    a second family now reports its own outstanding line in the same table, and
    a bare "NOT MEASURED" not in out would have made this clause assert that no
    OTHER family may be outstanding — which is not what it is about, and would
    make every future family land as a failure here.
    """
    from hephaestus.bench.scoring import COMPONENT_BASELINE_FILENAME

    (tmp_path / "reference-model").mkdir(parents=True)
    (tmp_path / "reference-model" / COMPONENT_BASELINE_FILENAME).write_text(
        json.dumps({"family": "component"}), encoding="utf-8"
    )
    out, path = _score_a_family_free_archive(tmp_path, capsys)
    assert path.is_file()
    assert "component family: NOT MEASURED" not in out
    assert "component family: not measured in this archive" in out
    assert "baseline already recorded in" in out


# ==========================================================================
# clause 13 — corpus-count pins repointed with this stage cited


def test_the_public_corpus_is_twenty_one_with_the_component_pair() -> None:
    prose = {task.id for task in load_tasks(specs=("prose",))}
    assert len(prose) == CORPUS_SIZE_NOW
    assert prose >= COMPONENT_PAIR
    assert CORPUS_SIZE_NOW - CORPUS_SIZE_V4 == 2, (
        "the only movement since Stage 11 is the Stage 12C scan pair "
        "(MESH_INGEST.md §7.5, G12C clause 50)"
    )
    seeded = {task.id for task in load_tasks(specs=("seeded",))}
    assert {f"{task_id}@seeded" for task_id in COMPONENT_PAIR} <= seeded
    assert len(seeded) == CORPUS_SIZE_NOW


@pytest.mark.parametrize(
    ("path", "needle"),
    [
        (
            "tests/stage6/test_g6_corpus_v1.py",
            "clause 12 keeps the component family in its OWN split",
        ),
        ("server/tests/test_bench_corpus.py", "CORPUS_V4_ADDITIONS"),
        ("tests/stage9c/test_corpus_mechanisms.py", "PARTS_STORE.md Stage 11, G11C clause 13"),
    ],
)
def test_every_repointed_count_pin_cites_this_stage(path: str, needle: str) -> None:
    """ "Repointed **with this stage cited**" — the citation is the clause.

    A count silently edited from 19 to 21 is indistinguishable from a count that
    drifted. Each of the three pins must carry the amendment that moved it, so a
    reader who finds the number surprising can find out why.
    """
    source = (REPO / path).read_text(encoding="utf-8")
    assert needle in source, f"{path}: pin not repointed"
    window = source[max(0, source.index(needle) - 1400) : source.index(needle) + 400]
    assert "PARTS_STORE.md" in window and "2026-08-29" in window, (
        f"{path}: the repointed pin does not cite the Stage 11 amendment that moved it"
    )


def test_each_new_task_carries_a_dated_hand_count_budget_derivation() -> None:
    """``VALIDATION.md`` §7: a new task may not ship a bare guess.

    No archived observe-mode journal exists for either task, so the measured
    floor cannot be recomputed for them yet; the policy's other half is a dated
    hand-count derivation in ``task.json``'s ``notes``, and the meta-suite
    asserts exactly those two substrings.
    """
    for task_id in sorted(COMPONENT_PAIR):
        notes = json.loads(
            (REPO / "corpus" / "tasks" / task_id / "task.json").read_text(encoding="utf-8")
        )["notes"]
        assert "hand-count" in notes
        assert "2026-08-25" in notes, "the measured-budget policy's own date"
        assert "PARTS_STORE.md" in notes, "and the amendment that added the task"
