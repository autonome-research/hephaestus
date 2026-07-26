"""Bench scoring: the one-sided lower 90% Wilson bound + the per-task table.

The Stage 2 gate is **not** the raw pass fraction — it is the lower bound of a
one-sided 90% Wilson score interval over the aggregate pass rate, so tiny-n luck
cannot pass a stage (verification.md Tier 3, digest §8). With ``n`` runs,
``p = passes / n`` and ``z = z(0.90) ~ 1.281552``:

    lower = [p + z^2/(2n) - z*sqrt(p(1-p)/n + z^2/(4n^2))] / (1 + z^2/n)

:data:`G2_AGGREGATE_THRESHOLD` is 0.60 over 8 tasks x >= 3 seeds (n >= 24), plus
``repair-fillet`` at 3/3 seeds (:data:`PERFECT_TASKS`). Thresholds are
mission-tunable *upward only*.

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

Every run also contributes to the §8 metric table
(:mod:`hephaestus.bench.metrics`), reported per split for the same reason.

This module deliberately imports nothing from the agent bridge: scoring an
archived run directory never needs Node, a provider, or the CAD stack.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from .metrics import (
    SPEC_PROSE,
    SPEC_SEEDED,
    RunMetrics,
    ValidationMetrics,
    aggregate_metrics,
    record_spec,
    run_metrics,
)

__all__ = [
    "G2_AGGREGATE_THRESHOLD",
    "PERFECT_TASKS",
    "RUNS_FILENAME",
    "SEEDED_BASELINE_FILENAME",
    "SPEC_PROSE",
    "SPEC_SEEDED",
    "Z_LOWER_90",
    "BenchScore",
    "SplitScore",
    "TaskScore",
    "load_run_records",
    "record_seeded_baseline",
    "score_directory",
    "score_records",
    "wilson_lower_bound",
    "write_score",
]

#: One-sided z for a 90% lower confidence bound (digest §8 fixes this constant).
Z_LOWER_90 = 1.281552

#: Gate G2 aggregate lower-bound threshold (mission-tunable upward only).
G2_AGGREGATE_THRESHOLD = 0.60

#: Tasks the gate additionally requires at 100% of their seeds.
PERFECT_TASKS: tuple[str, ...] = ("repair-fillet",)

#: The per-date run index the harness appends to (one RunRecord JSON per line).
RUNS_FILENAME = "runs.jsonl"

#: Where the seeded split's first measurement is recorded (never a gate input).
SEEDED_BASELINE_FILENAME = "seeded_baseline.json"


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
    against the prose baseline.
    """

    spec: str
    n: int
    passes: int
    pass_rate: float
    wilson_lower_90: float
    metrics: ValidationMetrics = field(default_factory=ValidationMetrics)
    threshold: float | None = None

    @property
    def meets_threshold(self) -> bool | None:
        """``None`` when this split has no threshold — never ``False``."""
        if self.threshold is None:
            return None
        return self.wilson_lower_90 >= self.threshold

    def to_json(self) -> dict[str, Any]:
        return {
            "spec": self.spec,
            "n": self.n,
            "passes": self.passes,
            "pass_rate": self.pass_rate,
            "wilson_lower_90": self.wilson_lower_90,
            "threshold": self.threshold,
            "meets_threshold": self.meets_threshold,
            "metrics": self.metrics.to_json(),
        }


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
    """
    per_task_n: dict[str, int] = {}
    per_task_passes: dict[str, int] = {}
    per_task_calls: dict[str, list[float]] = {}
    per_task_tokens: dict[str, list[float]] = {}
    per_task_budget: dict[str, int | None] = {}
    models: list[str] = []
    dates: list[str] = []
    by_spec: dict[str, list[Mapping[str, Any]]] = {SPEC_PROSE: [], SPEC_SEEDED: []}
    metrics_by_spec: dict[str, list[RunMetrics]] = {SPEC_PROSE: [], SPEC_SEEDED: []}
    total = 0
    passes = 0
    for record in records:
        task_id = str(record.get("task_id", ""))
        if not task_id:
            raise ValueError(f"run record without a task_id: {record!r}")
        spec = record_spec(record)
        by_spec.setdefault(spec, []).append(record)
        metrics_by_spec.setdefault(spec, []).append(
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
    splits = {
        SPEC_PROSE: _split_score(
            SPEC_PROSE,
            by_spec[SPEC_PROSE],
            metrics_by_spec[SPEC_PROSE],
            threshold=G2_AGGREGATE_THRESHOLD,
        ),
        # §1: the seeded split is baselined on first measurement, so it carries
        # no threshold at all — there is nothing here to compare it against.
        SPEC_SEEDED: _split_score(
            SPEC_SEEDED, by_spec[SPEC_SEEDED], metrics_by_spec[SPEC_SEEDED], threshold=None
        ),
    }
    prose = splits[SPEC_PROSE]
    all_metrics = [m for rows in metrics_by_spec.values() for m in rows]
    return BenchScore(
        model=resolved_model,
        date=resolved_date,
        # The gate has always named the prose split; these four stay its numbers.
        n=prose.n,
        passes=prose.passes,
        aggregate=prose.pass_rate,
        wilson_lower_90=prose.wilson_lower_90,
        per_task=per_task,
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


def write_score(score: BenchScore, path: Path) -> Path:
    """Write ``score`` as the deliverable JSON artifact; returns the path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(score.to_json(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
