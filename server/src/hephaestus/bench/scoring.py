"""Bench scoring: the one-sided lower 90% Wilson bound + the per-task table.

The Stage 2 gate is **not** the raw pass fraction — it is the lower bound of a
one-sided 90% Wilson score interval over the aggregate pass rate, so tiny-n luck
cannot pass a stage (verification.md Tier 3, digest §8). With ``n`` runs,
``p = passes / n`` and ``z = z(0.90) ~ 1.281552``:

    lower = [p + z^2/(2n) - z*sqrt(p(1-p)/n + z^2/(4n^2))] / (1 + z^2/n)

:data:`G2_AGGREGATE_THRESHOLD` is 0.60 over 8 tasks x >= 3 seeds (n >= 24), plus
``repair-fillet`` at 3/3 seeds (:data:`PERFECT_TASKS`). Thresholds are
mission-tunable *upward only*.

This module deliberately imports nothing from the agent bridge: scoring an
archived run directory never needs Node, a provider, or the CAD stack.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

__all__ = [
    "G2_AGGREGATE_THRESHOLD",
    "PERFECT_TASKS",
    "RUNS_FILENAME",
    "Z_LOWER_90",
    "BenchScore",
    "TaskScore",
    "load_run_records",
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
class BenchScore:
    """The scoring artifact written to ``bench/results/<model>/<date>.json``."""

    model: str
    date: str
    n: int
    passes: int
    aggregate: float
    wilson_lower_90: float
    per_task: Mapping[str, TaskScore]
    threshold: float = G2_AGGREGATE_THRESHOLD
    perfect_tasks: tuple[str, ...] = PERFECT_TASKS

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
        }


def _mean(values: Sequence[float]) -> float | None:
    return None if not values else sum(values) / len(values)


def score_records(
    records: Iterable[Mapping[str, Any]],
    *,
    model: str | None = None,
    date: str | None = None,
) -> BenchScore:
    """Aggregate run records (``RunRecord.to_json()`` shape) into a :class:`BenchScore`."""
    per_task_n: dict[str, int] = {}
    per_task_passes: dict[str, int] = {}
    per_task_calls: dict[str, list[float]] = {}
    per_task_tokens: dict[str, list[float]] = {}
    per_task_budget: dict[str, int | None] = {}
    models: list[str] = []
    dates: list[str] = []
    total = 0
    passes = 0
    for record in records:
        task_id = str(record.get("task_id", ""))
        if not task_id:
            raise ValueError(f"run record without a task_id: {record!r}")
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
    return BenchScore(
        model=resolved_model,
        date=resolved_date,
        n=total,
        passes=passes,
        aggregate=(passes / total) if total else 0.0,
        wilson_lower_90=wilson_lower_bound(passes, total),
        per_task=per_task,
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
    )


def write_score(score: BenchScore, path: Path) -> Path:
    """Write ``score`` as the deliverable JSON artifact; returns the path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(score.to_json(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
