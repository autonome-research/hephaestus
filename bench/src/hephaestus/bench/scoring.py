"""Bench scoring: the one-sided lower 90% Wilson bound + the per-task table.

The Stage 2 gate is **not** the raw pass fraction — it is the lower bound of a
one-sided 90% Wilson score interval over the aggregate pass rate, so tiny-n luck
cannot pass a stage (verification.md Tier 3, digest §8). With ``n`` runs,
``p = passes / n`` and ``z = z(0.90) ~ 1.281552``:

    lower = [p + z^2/(2n) - z*sqrt(p(1-p)/n + z^2/(4n^2))] / (1 + z^2/n)

:data:`G2_AGGREGATE_THRESHOLD` is 0.60 over the 8 corpus-v0 tasks x >= 3 seeds
(n >= 24), plus ``repair-fillet`` at 3/3 seeds (:data:`PERFECT_TASKS`).
:data:`G6_AGGREGATE_THRESHOLD` is 0.70 over corpus **v1** — the same 8 tasks plus
the four Stage 6 additions (:data:`CORPUS_V1_TASKS`), 12 tasks x >= 3 seeds
(n >= 36). Thresholds are mission-tunable *upward only*, and which one applies is
read off the corpus the archive actually covers (:func:`aggregate_threshold`)
rather than configured: a v0 archive keeps being scored against the bound it was
measured under, and a v1 run cannot be scored against the easier one.

**The two corpus splits are scored separately and never averaged**
(``VALIDATION.md`` §1). A :class:`BenchScore`'s headline numbers — ``n``,
``passes``, ``aggregate``, ``wilson_lower_90``, ``meets_gate`` — are the
**prose** split alone, because that is the split the corpus-v0 baseline was
measured on and the one the gate has always named. The seeded split is scored in
its own :class:`SplitScore`, carries **no threshold**, and is *baselined on first
measurement* (:func:`record_seeded_baseline`): a post-seeding number compared
against the pre-2026-07-26 baseline would be a category error, so the code never
offers the comparison. ``interpretation_gap`` (seeded - prose) is the first-class
column: the interpretation tax this project exists to reduce.

**Corpus families are carved out of the gated split** (``PARTS_STORE.md`` Gate
G11C clause 12, following ``KINEMATICS.md:392-398``). A family
(:data:`CORPUS_FAMILIES`) measures a capability the historical baselines never
covered, so its runs get ``<family>-<spec>`` splits of their own, carry no
threshold, and are baselined on their own first measurement at >= 3 seeds
(:func:`record_component_baseline`). Without the carve-out, a sweep over the
whole corpus would fold the new tasks into the number compared against 0.70 —
dilution arriving through the plumbing rather than through a decision.

Every run also contributes to the §8 metric table
(:mod:`hephaestus.bench.metrics`), reported per split for the same reason.

This module deliberately imports nothing from the agent bridge: scoring an
archived run directory never needs Node, a provider, or the CAD stack.

:func:`score_step_files` (``COMPARE.md`` §3) is the other kind of scoring the
same module owns: two STEP files, a task-declared threshold policy, a verdict
with every underlying fact attached. Its only engine dependency is
``hephaestus.geom`` — no executor, no project store, no bridge — because an
external benchmark (CADGenBench) scores a submitted file where none of those
exist. ``tests/stage8b/test_g8b_scoring.py`` proves the reach.
"""

from __future__ import annotations

import dataclasses
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from .metrics import (
    SEEDED_SUFFIX,
    SPEC_PROSE,
    SPEC_SEEDED,
    RunMetrics,
    ValidationMetrics,
    aggregate_metrics,
    record_spec,
    run_metrics,
)

__all__ = [
    "COMPONENT_BASELINE_FILENAME",
    "COMPONENT_BASELINE_MIN_SEEDS",
    "COMPONENT_FAMILY_TASKS",
    "CORPUS_FAMILIES",
    "CORPUS_V1_TASKS",
    "DEFAULT_STEP_POLICY",
    "FAMILY_COMPONENT",
    "FAMILY_SCAN",
    "G2_AGGREGATE_THRESHOLD",
    "G6_AGGREGATE_THRESHOLD",
    "INSUFFICIENT_COMPONENT_SEEDS",
    "INSUFFICIENT_SCAN_SEEDS",
    "PERFECT_TASKS",
    "RUNS_FILENAME",
    "SCAN_BASELINE_FILENAME",
    "SCAN_BASELINE_MIN_SEEDS",
    "SCAN_FAMILY_TASKS",
    "SEEDED_BASELINE_FILENAME",
    "SPEC_PROSE",
    "SPEC_SEEDED",
    "Z_LOWER_90",
    "BenchScore",
    "SplitScore",
    "StepFileScore",
    "StepScorePolicy",
    "TaskScore",
    "aggregate_threshold",
    "base_task_id",
    "family_split_name",
    "load_run_records",
    "record_component_baseline",
    "record_scan_baseline",
    "record_seeded_baseline",
    "score_directory",
    "score_records",
    "score_step_files",
    "split_family",
    "split_name",
    "task_family",
    "wilson_lower_bound",
    "write_score",
]

#: One-sided z for a 90% lower confidence bound (digest §8 fixes this constant).
Z_LOWER_90 = 1.281552

#: Gate G2 aggregate lower-bound threshold, corpus v0 (mission-tunable up only).
G2_AGGREGATE_THRESHOLD = 0.60

#: Gate G6 aggregate lower-bound threshold, corpus v1 (12 tasks x >= 3 seeds).
G6_AGGREGATE_THRESHOLD = 0.70

#: The tasks corpus v1 adds to v0 (mission_plan.md Stage 6: "corpus expanded to
#: 12 tasks ... including a DFM-repair task and a drawing task"). An archive that
#: covers all of them is a corpus-v1 run and is gated at
#: :data:`G6_AGGREGATE_THRESHOLD`.
CORPUS_V1_TASKS: tuple[str, ...] = ("dfm-repair", "drawing-shelf", "nest-gusset", "print-bracket")

#: Tasks the gate additionally requires at 100% of their seeds.
PERFECT_TASKS: tuple[str, ...] = ("repair-fillet",)

#: The per-date run index the harness appends to (one RunRecord JSON per line).
RUNS_FILENAME = "runs.jsonl"

#: Where the seeded split's first measurement is recorded (never a gate input).
SEEDED_BASELINE_FILENAME = "seeded_baseline.json"

# --------------------------------------------------------------------------
# Corpus families (PARTS_STORE.md Gate G11C clause 12, amended 2026-08-29)
#
# A *family* is a set of corpus tasks that measures a capability the historical
# baselines never covered. It is orthogonal to the ``VALIDATION.md`` §1 spec
# split: a family task exists in both prose and seeded form, and the two are
# still never averaged with each other. What the family adds is the second
# carve-out the G9C precedent (``KINEMATICS.md:392-398``) states and Stage 11
# amends into code: **a family's runs are not part of the number the gate
# compares against 0.70.** Before this, "its own split" was prose only, and a
# detached bench run over the whole corpus would have silently folded the new
# tasks into the corpus-v1 aggregate — which is exactly the dilution the rule
# forbids, arriving through the plumbing rather than through a decision.

#: The Stage 11 component-bearing mechanism family (Named new work item 34,
#: corpus v4): a bearing-supported shaft with a declared ``fit`` and a
#: motor-mounted plate with a declared ``coincident`` and bolt-circle
#: ``concentric``, both anchored on tags a store component's own generator
#: emitted. Closed vocabulary: a task joins the family by being named here.
COMPONENT_FAMILY_TASKS: tuple[str, ...] = ("bearing-shaft", "motor-plate")

#: The component family's name, and the prefix of its split names.
FAMILY_COMPONENT = "component"

#: The Stage 12 scan family (``MESH_INGEST.md`` §7.5, Named new work item 34,
#: corpus v5): a cuff authored against a synthesized limb scan and a relief
#: frame around a scanned boss, both graded on distance to the scan through the
#: engine's own ``compare_to_scan`` path. Closed vocabulary, same as above: a
#: task joins the family by being named here.
SCAN_FAMILY_TASKS: tuple[str, ...] = ("scan-socket-cuff", "scan-boss-relief")

#: The scan family's name, and the prefix of its split names.
FAMILY_SCAN = "scan"

#: The closed family vocabulary. G9C's mechanism family is deliberately absent:
#: its split is G9C's own gate text to amend, and folding it in here would be
#: this stage rewriting another stage's baseline rule.
CORPUS_FAMILIES: Mapping[str, tuple[str, ...]] = {
    FAMILY_COMPONENT: COMPONENT_FAMILY_TASKS,
    FAMILY_SCAN: SCAN_FAMILY_TASKS,
}

#: Where the component family's first measurement is recorded (never a gate
#: input, and never comparable to the v1/v2 baselines).
COMPONENT_BASELINE_FILENAME = "component_baseline.json"

#: G11C clause 12's floor: the family is baselined on its FIRST measurement and
#: never re-baselined, so a first measurement thinner than this would enshrine
#: noise as the family's permanent reference number.
COMPONENT_BASELINE_MIN_SEEDS = 3

#: The named refusal a too-thin first measurement gets. Named, not silent: the
#: alternative is a baseline file that looks like evidence and is not.
INSUFFICIENT_COMPONENT_SEEDS = "insufficient_component_seeds"

#: Where the scan family's first measurement is recorded (never a gate input,
#: and never comparable to the v1/v2 baselines) — ``MESH_INGEST.md`` §7.5,
#: following the same G9C precedent Stage 11 followed.
SCAN_BASELINE_FILENAME = "scan_baseline.json"

#: The scan family's seed floor and its named refusal. Same numbers and the same
#: reasoning as the component family's: a first measurement is permanent, so a
#: thin one would enshrine noise.
SCAN_BASELINE_MIN_SEEDS = 3
INSUFFICIENT_SCAN_SEEDS = "insufficient_scan_seeds"


def base_task_id(task_id: str) -> str:
    """The prose id behind a run's task id (the seeded variant's stem)."""
    return task_id.split(SEEDED_SUFFIX, 1)[0]


def task_family(task_id: str) -> str | None:
    """The corpus family ``task_id`` belongs to, or ``None`` for the base corpus."""
    base = base_task_id(task_id)
    for family, members in CORPUS_FAMILIES.items():
        if base in members:
            return family
    return None


def family_split_name(family: str, spec: str) -> str:
    """The split name for one family and one spec, e.g. ``component-prose``."""
    return f"{family}-{spec}"


def split_family(split: str) -> str | None:
    """The family a *split name* belongs to, or ``None`` for a §1 spec split.

    The inverse of :func:`family_split_name`, and the one place that reads a
    split name back into a family. It exists because the scoring artifact is
    archived evidence (mission rule 2): a key that means something only for a
    family split must be emitted only on family splits, or re-scoring an archive
    measured before Stage 11 silently rewrites its stored artifact.
    """
    family, _, spec = split.partition("-")
    if spec in (SPEC_PROSE, SPEC_SEEDED) and family in CORPUS_FAMILIES:
        return family
    return None


def split_name(task_id: str, spec: str) -> str:
    """The split a run belongs to: its family's when it has one, else its spec.

    This is the single place the carve-out happens, so there is exactly one
    answer to "which split is this run in" and no caller can arrive at another.
    """
    family = task_family(task_id)
    return spec if family is None else family_split_name(family, spec)


def aggregate_threshold(task_ids: Iterable[str]) -> float:
    """The gate threshold for a run set covering ``task_ids``.

    Corpus v1 (every task in :data:`CORPUS_V1_TASKS` present) is gated at
    :data:`G6_AGGREGATE_THRESHOLD`; anything less is still the v0 corpus and
    keeps :data:`G2_AGGREGATE_THRESHOLD`, the bound it was baselined under. The
    threshold is therefore a fact about the evidence, not a knob: a v1 archive
    cannot be scored against the easier bound by passing a different flag.
    """
    covered = {task_id.split(SEEDED_SUFFIX, 1)[0] for task_id in task_ids}
    if set(CORPUS_V1_TASKS) <= covered:
        return G6_AGGREGATE_THRESHOLD
    return G2_AGGREGATE_THRESHOLD


def wilson_lower_bound(passes: int, n: int, *, z: float = Z_LOWER_90) -> float:
    """Lower bound of the one-sided Wilson score interval for ``passes``/``n``.

    ``n <= 0`` scores 0.0 (no evidence never passes a gate). The result is
    clamped into ``[0, 1]`` — the closed form can stray a few 1e-17 outside it.
    """
    if n <= 0:
        return 0.0
    if passes < 0 or passes > n:
        raise ValueError(f"passes={passes} is outside 0..n for n={n}")
    p = passes / n
    z2 = z * z
    centre = p + z2 / (2 * n)
    spread = z * math.sqrt(p * (1.0 - p) / n + z2 / (4 * n * n))
    lower = (centre - spread) / (1.0 + z2 / n)
    return min(1.0, max(0.0, lower))


@dataclass(frozen=True)
class TaskScore:
    """One task's row of the leaderboard table."""

    task_id: str
    n: int
    passes: int
    pass_rate: float
    mean_tool_calls: float | None
    budget_tool_calls: int | None
    mean_tokens: float | None

    def to_json(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "passes": self.passes,
            "pass_rate": self.pass_rate,
            "mean_tool_calls": self.mean_tool_calls,
            "budget_tool_calls": self.budget_tool_calls,
            "mean_tokens": self.mean_tokens,
        }


@dataclass(frozen=True)
class SplitScore:
    """One corpus split's numbers (``VALIDATION.md`` §1), scored on its own.

    ``threshold`` is ``None`` for the seeded split: it is baselined on first
    measurement and does not gate anything yet, and a ``None`` threshold is the
    only representation in which no arithmetic can accidentally compare it
    against the prose baseline. Every corpus-family split
    (:data:`CORPUS_FAMILIES`) carries ``None`` for the same reason.

    ``spec`` is the split's *name*: a ``VALIDATION.md`` §1 spec for the two base
    splits, and ``<family>-<spec>`` for a family's (:func:`split_name`).

    ``min_seeds_per_task`` is the smallest number of distinct seeds any task in
    the split was run at — the honest reading of "at >= 3 seeds", since a mean
    would let one thoroughly measured task cover for one measured once. A run
    record carrying no ``seed`` contributes no seed, so a hand-assembled archive
    reads low rather than inventing coverage it does not have.

    It is computed for **every** split (the ``heph bench score`` table prints
    it for all of them) but serialised only for **family** splits, and that
    asymmetry is deliberate rather than an oversight. G11C clause 12(b) claims
    that an archive measured before Stage 11 re-scores to byte-identical
    output; emitting an informational key on the two §1 spec splits made that
    claim false, which a 2026-08-29 verifier demonstrated by re-scoring
    ``bench/results/gpt-5.6-sol/2026-08-03`` and finding exactly one added key
    per split. The key is a gate input for exactly one reader —
    :func:`record_component_baseline`'s >= 3-seed floor — so it is written
    exactly where that reader looks, and every stored artifact stays the file
    its run produced. A future amendment that wants it on the spec splits adds
    it deliberately and re-records the archives; it does not arrive as a side
    effect. ``tests/stage11c`` asserts both halves against the real archives.
    """

    spec: str
    n: int
    passes: int
    pass_rate: float
    wilson_lower_90: float
    metrics: ValidationMetrics = field(default_factory=ValidationMetrics)
    threshold: float | None = None
    min_seeds_per_task: int = 0

    @property
    def meets_threshold(self) -> bool | None:
        """``None`` when this split has no threshold — never ``False``."""
        if self.threshold is None:
            return None
        return self.wilson_lower_90 >= self.threshold

    def to_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "spec": self.spec,
            "n": self.n,
            "passes": self.passes,
            "pass_rate": self.pass_rate,
            "wilson_lower_90": self.wilson_lower_90,
            "threshold": self.threshold,
            "meets_threshold": self.meets_threshold,
            "metrics": self.metrics.to_json(),
        }
        # Only a family split serialises the seed floor's input — see the class
        # docstring: the artifact of an archive that measured no family task is
        # the file that archive has always produced.
        if split_family(self.spec) is not None:
            payload["min_seeds_per_task"] = self.min_seeds_per_task
        return payload


@dataclass(frozen=True)
class BenchScore:
    """The scoring artifact written to ``bench/results/<model>/<date>.json``.

    ``n``/``passes``/``aggregate``/``wilson_lower_90``/``meets_gate`` are the
    **prose** split (the historically baselined one the corpus-v0 gate names);
    the seeded split lives in :attr:`splits` and gates nothing.
    """

    model: str
    date: str
    n: int
    passes: int
    aggregate: float
    wilson_lower_90: float
    per_task: Mapping[str, TaskScore]
    threshold: float = G2_AGGREGATE_THRESHOLD
    perfect_tasks: tuple[str, ...] = PERFECT_TASKS
    splits: Mapping[str, SplitScore] = field(default_factory=dict[str, SplitScore])
    metrics: ValidationMetrics = field(default_factory=ValidationMetrics)
    #: Every run in the archive, both splits (the prose-only ``n`` is the gate).
    n_total: int = 0
    passes_total: int = 0

    @property
    def prose(self) -> SplitScore:
        return self.splits.get(
            SPEC_PROSE,
            SplitScore(
                spec=SPEC_PROSE,
                n=0,
                passes=0,
                pass_rate=0.0,
                wilson_lower_90=0.0,
                threshold=self.threshold,
            ),
        )

    @property
    def seeded(self) -> SplitScore:
        return self.splits.get(
            SPEC_SEEDED,
            SplitScore(spec=SPEC_SEEDED, n=0, passes=0, pass_rate=0.0, wilson_lower_90=0.0),
        )

    def family_split(self, family: str, spec: str) -> SplitScore:
        """One corpus family's split, or an empty one when it was not run.

        A family that was not measured reads as ``n == 0`` — never as a missing
        key a caller might paper over, and never as a fabricated zero pass rate
        with a threshold attached (:attr:`SplitScore.threshold` stays ``None``).
        """
        name = family_split_name(family, spec)
        return self.splits.get(
            name, SplitScore(spec=name, n=0, passes=0, pass_rate=0.0, wilson_lower_90=0.0)
        )

    @property
    def pass_rate_prose(self) -> float | None:
        """``None`` when the split was not run — never a fabricated zero."""
        return self.prose.pass_rate if self.prose.n else None

    @property
    def pass_rate_seeded(self) -> float | None:
        return self.seeded.pass_rate if self.seeded.n else None

    @property
    def interpretation_gap(self) -> float | None:
        """seeded - prose: the interpretation tax (``None`` unless both ran)."""
        prose = self.pass_rate_prose
        seeded = self.pass_rate_seeded
        if prose is None or seeded is None:
            return None
        return seeded - prose

    @property
    def perfect_task_failures(self) -> tuple[str, ...]:
        """Required-perfect tasks that did not pass every one of their seeds."""
        missed: list[str] = []
        for task_id in self.perfect_tasks:
            row = self.per_task.get(task_id)
            if row is None or row.n == 0 or row.passes != row.n:
                missed.append(task_id)
        return tuple(missed)

    @property
    def meets_gate(self) -> bool:
        """Gate G2: aggregate lower bound at/above threshold and perfect tasks perfect."""
        return self.wilson_lower_90 >= self.threshold and not self.perfect_task_failures

    def to_json(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "date": self.date,
            "n": self.n,
            "passes": self.passes,
            "aggregate": self.aggregate,
            "wilson_lower_90": self.wilson_lower_90,
            "z": Z_LOWER_90,
            "threshold": self.threshold,
            "perfect_tasks": list(self.perfect_tasks),
            "perfect_task_failures": list(self.perfect_task_failures),
            "meets_gate": self.meets_gate,
            "per_task": {task_id: row.to_json() for task_id, row in sorted(self.per_task.items())},
            # VALIDATION.md §1/§8: the splits and the metric table.
            "gated_split": SPEC_PROSE,
            "n_total": self.n_total,
            "passes_total": self.passes_total,
            "pass_rate_prose": self.pass_rate_prose,
            "pass_rate_seeded": self.pass_rate_seeded,
            "interpretation_gap": self.interpretation_gap,
            "splits": {spec: row.to_json() for spec, row in sorted(self.splits.items())},
            "metrics": self.metrics.to_json(),
        }


def _mean(values: Sequence[float]) -> float | None:
    return None if not values else sum(values) / len(values)


def _run_dir(archive_dir: Path | None, record: Mapping[str, Any]) -> Path | None:
    """Where this run's event stream lives, when the archive was relocated.

    An archive downloaded by CI sits at a different absolute path than the one
    the record recorded, so the directory being scored wins when it actually
    holds the run; otherwise :func:`~.metrics.run_metrics` falls back to the
    record's own ``archive_dir``.
    """
    if archive_dir is None:
        return None
    candidate = archive_dir / f"{record.get('task_id', '')}-s{record.get('seed', 1)}"
    return candidate if candidate.is_dir() else None


def _min_seeds_per_task(records: Sequence[Mapping[str, Any]]) -> int:
    """The smallest distinct-seed count over the tasks present in ``records``."""
    seeds: dict[str, set[int]] = {}
    for record in records:
        bucket = seeds.setdefault(str(record.get("task_id", "")), set())
        seed = record.get("seed")
        if isinstance(seed, int) and not isinstance(seed, bool):
            bucket.add(seed)
    return min((len(values) for values in seeds.values()), default=0)


def _split_score(
    spec: str,
    records: Sequence[Mapping[str, Any]],
    metrics: Sequence[RunMetrics],
    *,
    threshold: float | None,
) -> SplitScore:
    n = len(records)
    passes = sum(1 for record in records if bool(record.get("passed")))
    return SplitScore(
        spec=spec,
        n=n,
        passes=passes,
        pass_rate=(passes / n) if n else 0.0,
        wilson_lower_90=wilson_lower_bound(passes, n),
        metrics=aggregate_metrics(metrics),
        threshold=threshold,
        min_seeds_per_task=_min_seeds_per_task(records),
    )


def score_records(
    records: Iterable[Mapping[str, Any]],
    *,
    model: str | None = None,
    date: str | None = None,
    archive_dir: Path | None = None,
) -> BenchScore:
    """Aggregate run records (``RunRecord.to_json()`` shape) into a :class:`BenchScore`.

    The two spec splits are tallied separately and never averaged together: the
    returned score's headline numbers are the prose split, and the seeded split
    is a sibling entry in :attr:`BenchScore.splits`.

    Corpus-family runs (:data:`CORPUS_FAMILIES`) are carved out of *both* spec
    splits into their own ``<family>-<spec>`` entries, so the gated number keeps
    covering exactly the corpus it was baselined over. A family split appears in
    :attr:`BenchScore.splits` only when it actually has runs — an archive that
    measured no family task produces the artifact it always produced.
    """
    per_task_n: dict[str, int] = {}
    per_task_passes: dict[str, int] = {}
    per_task_calls: dict[str, list[float]] = {}
    per_task_tokens: dict[str, list[float]] = {}
    per_task_budget: dict[str, int | None] = {}
    models: list[str] = []
    dates: list[str] = []
    by_split: dict[str, list[Mapping[str, Any]]] = {SPEC_PROSE: [], SPEC_SEEDED: []}
    metrics_by_split: dict[str, list[RunMetrics]] = {SPEC_PROSE: [], SPEC_SEEDED: []}
    total = 0
    passes = 0
    for record in records:
        task_id = str(record.get("task_id", ""))
        if not task_id:
            raise ValueError(f"run record without a task_id: {record!r}")
        split = split_name(task_id, record_spec(record))
        by_split.setdefault(split, []).append(record)
        metrics_by_split.setdefault(split, []).append(
            run_metrics(record, archive_dir=_run_dir(archive_dir, record))
        )
        total += 1
        per_task_n[task_id] = per_task_n.get(task_id, 0) + 1
        per_task_passes.setdefault(task_id, 0)
        per_task_budget.setdefault(task_id, None)
        if bool(record.get("passed")):
            passes += 1
            per_task_passes[task_id] += 1
        calls = record.get("tool_calls")
        if isinstance(calls, int | float) and not isinstance(calls, bool):
            per_task_calls.setdefault(task_id, []).append(float(calls))
        tokens = record.get("tokens")
        if isinstance(tokens, int | float) and not isinstance(tokens, bool):
            per_task_tokens.setdefault(task_id, []).append(float(tokens))
        budget = record.get("budget_tool_calls")
        if isinstance(budget, int) and not isinstance(budget, bool):
            per_task_budget[task_id] = budget
        model_id = record.get("model")
        if isinstance(model_id, str) and model_id and model_id not in models:
            models.append(model_id)
        run_date = record.get("date")
        if isinstance(run_date, str) and run_date and run_date not in dates:
            dates.append(run_date)
    per_task = {
        task_id: TaskScore(
            task_id=task_id,
            n=count,
            passes=per_task_passes[task_id],
            pass_rate=per_task_passes[task_id] / count if count else 0.0,
            mean_tool_calls=_mean(per_task_calls.get(task_id, [])),
            budget_tool_calls=per_task_budget.get(task_id),
            mean_tokens=_mean(per_task_tokens.get(task_id, [])),
        )
        for task_id, count in sorted(per_task_n.items())
    }
    resolved_model = model or (models[0] if models else "unknown-model")
    resolved_date = date or (dates[0] if dates else datetime.now(UTC).date().isoformat())
    # The corpus the *gated* split covers decides the bound (v0: 0.60, v1: 0.70).
    threshold = aggregate_threshold(
        str(record.get("task_id", "")) for record in by_split[SPEC_PROSE]
    )
    splits = {
        SPEC_PROSE: _split_score(
            SPEC_PROSE,
            by_split[SPEC_PROSE],
            metrics_by_split[SPEC_PROSE],
            threshold=threshold,
        ),
        # §1: the seeded split is baselined on first measurement, so it carries
        # no threshold at all — there is nothing here to compare it against.
        SPEC_SEEDED: _split_score(
            SPEC_SEEDED, by_split[SPEC_SEEDED], metrics_by_split[SPEC_SEEDED], threshold=None
        ),
    }
    # G11C clause 12: each family split stands alone, with no threshold, so no
    # arithmetic anywhere can compare it against a baseline it does not share.
    for name in sorted(by_split):
        if name in splits or not by_split[name]:
            continue
        splits[name] = _split_score(name, by_split[name], metrics_by_split[name], threshold=None)
    prose = splits[SPEC_PROSE]
    all_metrics = [m for rows in metrics_by_split.values() for m in rows]
    return BenchScore(
        model=resolved_model,
        date=resolved_date,
        # The gate has always named the prose split; these four stay its numbers.
        n=prose.n,
        passes=prose.passes,
        aggregate=prose.pass_rate,
        wilson_lower_90=prose.wilson_lower_90,
        per_task=per_task,
        threshold=threshold,
        splits=splits,
        metrics=aggregate_metrics(all_metrics),
        n_total=total,
        passes_total=passes,
    )


def load_run_records(directory: Path) -> list[dict[str, Any]]:
    """Read run records from an archive directory.

    Prefers the ``runs.jsonl`` index the harness appends to; falls back to the
    per-run ``*/result.json`` files so a partially-archived (or hand-assembled)
    directory still scores.
    """
    index = directory / RUNS_FILENAME
    records: list[dict[str, Any]] = []
    if index.is_file():
        for line in index.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text:
                continue
            parsed = json.loads(text)
            if not isinstance(parsed, dict):
                raise ValueError(f"{index}: run record is not a JSON object")
            records.append(cast("dict[str, Any]", parsed))
        return records
    for result in sorted(directory.glob("*/result.json")):
        parsed = json.loads(result.read_text(encoding="utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError(f"{result}: run record is not a JSON object")
        records.append(cast("dict[str, Any]", parsed))
    return records


def score_directory(
    directory: Path, *, model: str | None = None, date: str | None = None
) -> BenchScore:
    """Score one archived ``bench/results/<model>/<date>/`` run directory."""
    records = load_run_records(directory)
    # A ``<model>/<date>/`` archive names both facts in its path; those names are
    # only used when the records themselves carry none (hand-assembled archives).
    has_model = any(isinstance(r.get("model"), str) and r.get("model") for r in records)
    has_date = any(isinstance(r.get("date"), str) and r.get("date") for r in records)
    return score_records(
        records,
        model=model or (None if has_model else directory.parent.name),
        date=date or (None if has_date else directory.name),
        archive_dir=directory,
    )


def record_seeded_baseline(score: BenchScore, path: Path) -> dict[str, Any] | None:
    """Baseline the seeded split on its **first** measurement, and never re-baseline.

    ``VALIDATION.md`` §1: the seeded split gets its own threshold, baselined on
    first measurement, and post-seeding numbers are never compared against the
    pre-2026-07-26 prose baseline. So this records the first seeded measurement
    and returns whatever was already recorded thereafter — it writes a fact, sets
    no threshold, and is not consulted by :attr:`BenchScore.meets_gate`. Returns
    ``None`` when there is no seeded run to baseline.
    """
    seeded = score.seeded
    if seeded.n == 0:
        return None
    if path.is_file():
        stored = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(stored, dict):
            raise ValueError(f"{path}: seeded baseline is not a JSON object")
        return cast("dict[str, Any]", stored)
    baseline: dict[str, Any] = {
        "spec": SPEC_SEEDED,
        "model": score.model,
        "date": score.date,
        "n": seeded.n,
        "passes": seeded.passes,
        "pass_rate": seeded.pass_rate,
        "wilson_lower_90": seeded.wilson_lower_90,
        "threshold": None,
        "note": (
            "VALIDATION.md §1: baselined on first measurement; not a gate, and "
            "never comparable to the pre-2026-07-26 prose baseline."
        ),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(baseline, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return baseline


def _record_family_baseline(
    score: BenchScore,
    path: Path,
    *,
    family: str,
    tasks: tuple[str, ...],
    min_seeds: int,
    refusal: str,
    citation: str,
) -> dict[str, Any] | None:
    """One corpus family baselined on its **first** measurement, at ``min_seeds``.

    The G9C precedent (``KINEMATICS.md:392-398``) as both Stage 11 and Stage 12
    apply it: a family is its own split per spec, baselined on its own first
    measurement with the reference model at >= ``min_seeds`` seeds, **neither
    compared against nor averaged into the v1/v2 baselines**. Three properties,
    each mechanical here rather than promised:

    * *Its own split* — :func:`split_name` carved the family's runs out of the
      gated prose split before this function ever sees them, so the number
      written here shares no run with the 0.70 bar.
    * *Its own first measurement* — an existing file is returned unchanged, as
      :func:`record_seeded_baseline` does. A baseline that could be re-taken is
      not a baseline.
    * *At >= min_seeds* — refused by name below, because "first measurement" and
      "never re-baselined" together mean a thin first run would enshrine noise
      permanently. This is the one place the seed floor can still be enforced.

    The prose and seeded halves are recorded side by side and never averaged
    with each other either; the payload carries no threshold, and nothing reads
    it back into a verdict. Returns ``None`` when the family was not run.

    This is ONE function over a family vocabulary rather than one per family
    (mission rule 6): a second copy would be a second place for the seed floor
    and the never-re-baseline rule to drift apart.

    :raises ValueError: ``refusal`` when a measured half ran some task at fewer
        than ``min_seeds`` distinct seeds. Nothing is written; the caller is told
        which half and how thin it was.
    """
    rows = {spec: score.family_split(family, spec) for spec in (SPEC_PROSE, SPEC_SEEDED)}
    measured = {spec: row for spec, row in rows.items() if row.n}
    if not measured:
        return None
    if path.is_file():
        stored = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(stored, dict):
            raise ValueError(f"{path}: {family} baseline is not a JSON object")
        return cast("dict[str, Any]", stored)
    thin = {
        spec: row.min_seeds_per_task
        for spec, row in measured.items()
        if row.min_seeds_per_task < min_seeds
    }
    if thin:
        detail = ", ".join(
            f"{family_split_name(family, spec)}={seeds}" for spec, seeds in sorted(thin.items())
        )
        raise ValueError(
            f"{refusal}: the {family} family is baselined on its "
            f"first measurement and never re-baselined, so it will not be baselined "
            f"below {min_seeds} seeds per task ({detail}); {citation}"
        )
    baseline: dict[str, Any] = {
        "family": family,
        "tasks": list(tasks),
        "model": score.model,
        "date": score.date,
        "min_seeds": min_seeds,
        "threshold": None,
        "splits": {
            family_split_name(family, spec): {
                "n": row.n,
                "passes": row.passes,
                "pass_rate": row.pass_rate,
                "wilson_lower_90": row.wilson_lower_90,
                "min_seeds_per_task": row.min_seeds_per_task,
                "threshold": None,
            }
            for spec, row in sorted(measured.items())
        },
        "note": (
            f"{citation} (the KINEMATICS.md:392-398 G9C precedent): baselined on its "
            f"own first measurement at >= {min_seeds} seeds; not a gate, and neither "
            "compared against nor averaged into the corpus v1/v2 baselines. "
            "Re-baselining any combined bar is its own future amendment."
        ),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(baseline, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return baseline


def record_component_baseline(score: BenchScore, path: Path) -> dict[str, Any] | None:
    """The component family's first measurement (``PARTS_STORE.md`` G11C clause 12)."""
    return _record_family_baseline(
        score,
        path,
        family=FAMILY_COMPONENT,
        tasks=COMPONENT_FAMILY_TASKS,
        min_seeds=COMPONENT_BASELINE_MIN_SEEDS,
        refusal=INSUFFICIENT_COMPONENT_SEEDS,
        citation="PARTS_STORE.md Gate G11C clause 12",
    )


def record_scan_baseline(score: BenchScore, path: Path) -> dict[str, Any] | None:
    """The scan family's first measurement (``MESH_INGEST.md`` §7.5, G12C.51).

    Its own split, its own first measurement, its own threshold — and the
    existing 0.70 prose bar keys on its own coverage constant and is not
    diluted, because :func:`split_name` never let these runs into it.
    """
    return _record_family_baseline(
        score,
        path,
        family=FAMILY_SCAN,
        tasks=SCAN_FAMILY_TASKS,
        min_seeds=SCAN_BASELINE_MIN_SEEDS,
        refusal=INSUFFICIENT_SCAN_SEEDS,
        citation="MESH_INGEST.md §7.5 Gate G12C clause 51",
    )


def write_score(score: BenchScore, path: Path) -> Path:
    """Write ``score`` as the deliverable JSON artifact; returns the path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(score.to_json(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# External STEP scoring (COMPARE.md §3 — the 8D substrate)


#: The policy applied when a task declares none: compare where the solids sit
#: and assert nothing. A policy that names no tolerance yields **no verdict**
#: (:attr:`StepFileScore.passed` is ``None``) rather than a free pass — an
#: unstated threshold is a missing claim, not a satisfied one.
DEFAULT_STEP_POLICY: Mapping[str, Any] = {"align": "as_posed"}


@dataclass(frozen=True)
class StepScorePolicy:
    """A task's declared thresholds for scoring one STEP file against another.

    Every field is optional and every one is a *claim the task owns*
    (``COMPARE.md`` §1: thresholds do not live in the geometry layer). ``align``
    is part of the policy because it decides which question is being asked: a
    generation task that must not punish an arbitrary pose declares
    ``"principal"``; an editing task that must preserve pose leaves it
    ``"as_posed"``.
    """

    iou_min: float | None = None
    chamfer_max_mm: float | None = None
    align: str = "as_posed"

    @classmethod
    def from_json(cls, raw: Mapping[str, Any] | None) -> StepScorePolicy:
        """Read a task-declared policy document (absent fields stay unclaimed)."""
        data = dict(raw or {})
        align = data.get("align", "as_posed")
        if align not in ("as_posed", "principal"):
            raise ValueError(f"policy align must be as_posed or principal, got {align!r}")
        return cls(
            iou_min=_optional_number(data, "iou_min"),
            chamfer_max_mm=_optional_number(data, "chamfer_max_mm"),
            align=str(align),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "iou_min": self.iou_min,
            "chamfer_max_mm": self.chamfer_max_mm,
            "align": self.align,
        }

    @property
    def declares_threshold(self) -> bool:
        return self.iou_min is not None or self.chamfer_max_mm is not None


def _optional_number(raw: Mapping[str, Any], key: str) -> float | None:
    value = raw.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"policy {key} must be a number, got {value!r}")
    return float(value)


@dataclass(frozen=True)
class StepFileScore:
    """One scored candidate: the verdict, the criteria behind it, every fact.

    ``passed`` is ``None`` when the policy declared no threshold — there is
    nothing to have passed. ``criteria`` shows each declared threshold against
    the number that was actually measured, so a score is auditable without
    re-running it, and ``diff`` carries the whole ``SolidDiff`` beneath.

    ``notes`` records the facts that make a number less trustworthy than it
    looks: a canonical frame that two rigid copies might not share, or a
    chamfer computed from an empty surface sample. They never change the
    verdict — reporting them and deciding are different jobs.
    """

    passed: bool | None
    policy: StepScorePolicy
    diff: Mapping[str, Any] = field(default_factory=dict[str, Any])
    criteria: tuple[Mapping[str, Any], ...] = ()
    notes: tuple[str, ...] = ()
    error: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "policy": self.policy.to_json(),
            "criteria": [dict(row) for row in self.criteria],
            "notes": list(self.notes),
            "error": self.error,
            "diff": dict(self.diff),
        }


def _criterion(name: str, threshold: float, measured: float, passed: bool) -> dict[str, Any]:
    return {"name": name, "threshold": threshold, "measured": measured, "passed": passed}


def score_step_files(
    candidate: Path | str,
    truth: Path | str,
    policy: Mapping[str, Any] | StepScorePolicy | None = None,
) -> StepFileScore:
    """Score one STEP file against a ground-truth STEP file (``COMPARE.md`` §3).

    Reads both through ``geom.step_io``, produces one ``SolidDiff``, applies the
    task-declared policy, and returns the verdict with every underlying fact
    attached. The candidate is the ``a`` side, so ``a_only_mm3`` is material the
    submission added and ``b_only_mm3`` is material it is missing.

    An unreadable candidate is a **failed score, not an exception**: a benchmark
    must be able to score a broken submission alongside the others. An
    unreadable *ground truth* is a broken task, so that one does raise.

    The only engine dependency is :mod:`hephaestus.geom`: no executor, no
    project store, no agent bridge — CADGenBench scoring runs where those do not
    exist.
    """
    from hephaestus.geom.compare import (
        AlignMode,
        CompareBooleanError,
        principal_alignment,
        solid_diff,
    )
    from hephaestus.geom.step_io import StepReadError, read_step

    resolved = policy if isinstance(policy, StepScorePolicy) else StepScorePolicy.from_json(policy)
    # Paths arrive as strings from a harness argv as often as from a Path; the
    # scorer is an external entry point, so it takes either.
    truth_shape = read_step(Path(truth))
    try:
        candidate_shape = read_step(Path(candidate))
    except StepReadError as exc:
        # A submission that will not parse scores 0, with the reason recorded.
        return StepFileScore(passed=False, policy=resolved, error=exc.message)

    align = cast("AlignMode", resolved.align)
    notes: list[str] = []
    if align == "principal":
        try:
            degenerate = any(
                principal_alignment(shape).degenerate for shape in (candidate_shape, truth_shape)
            )
        except ValueError as exc:
            return StepFileScore(passed=False, policy=resolved, error=str(exc))
        if degenerate:
            # COMPARE.md §1: the frame is reproducible for each shape, but a
            # symmetric solid may canonicalize two rigid copies differently —
            # so a `principal` iou here is worth less than it looks.
            notes.append("degenerate_principal_frame")

    try:
        record = solid_diff(candidate_shape, truth_shape, align=align)
    except CompareBooleanError as exc:
        # A candidate whose boolean against the reference fails in the kernel
        # scores 0 with the reason — the same rule as an unparseable one.
        return StepFileScore(passed=False, policy=resolved, error=str(exc))
    diff = cast("Mapping[str, Any]", dataclasses.asdict(record))
    if record.surface.a_samples == 0 or record.surface.b_samples == 0:
        # A 0.0 chamfer from an empty sample is not agreement.
        notes.append("empty_surface_sample")

    criteria: list[Mapping[str, Any]] = []
    if resolved.iou_min is not None:
        criteria.append(
            _criterion(
                "iou_min",
                resolved.iou_min,
                record.volume.iou,
                record.volume.iou >= resolved.iou_min,
            )
        )
    if resolved.chamfer_max_mm is not None:
        criteria.append(
            _criterion(
                "chamfer_max_mm",
                resolved.chamfer_max_mm,
                record.surface.chamfer_mm,
                record.surface.chamfer_mm <= resolved.chamfer_max_mm,
            )
        )
    passed = all(bool(row["passed"]) for row in criteria) if resolved.declares_threshold else None
    return StepFileScore(
        passed=passed,
        policy=resolved,
        diff=diff,
        criteria=tuple(criteria),
        notes=tuple(notes),
    )
