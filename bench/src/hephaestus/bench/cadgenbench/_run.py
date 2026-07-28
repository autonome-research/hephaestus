"""Driving converted tasks through the **existing** session harness.

``EXTERNAL_EVAL.md`` §2: *the standard session harness over converted tasks* —
same budgets machinery, observe mode by default, ``--parallel N``,
``--samples`` filter, and the part exported to STEP through the normal
``export_part`` path. So there is no runner here: :func:`run_converted` calls
:func:`hephaestus.bench.harness.run_bench` and then does the one job that is
CADGenBench-specific, which is copying each run's exported STEP into the
submission layout (``<sample>/output.step``).

The submission artifact is therefore a build artifact with full provenance: the
bytes come out of the graded geometry via the grader's own export requirement,
not from anything the model reported about itself. A run that produced no valid
export leaves an **empty** sample folder — a legal, scored-zero submission that
says so, rather than a folder quietly absent from the ZIP.
"""

from __future__ import annotations

import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from ._convert import sample_id_for_task
from ._package import SUBMISSION_CANDIDATE

if TYPE_CHECKING:  # pragma: no cover - typing only
    from hephaestus.bench.harness import BenchRun, BenchTask, ProviderConfig, RunRecord

__all__ = ["RunOutcome", "collect_outputs", "exported_step_path", "run_converted"]


def exported_step_path(grade: Mapping[str, Any] | None) -> Path | None:
    """The STEP the grader exported from the graded geometry, if it validated.

    Reads the grade record rather than the run's own account of itself: an
    export the grader marked ``invalid`` is not a submission candidate.
    """
    if not grade:
        return None
    for record in cast("Sequence[Any]", grade.get("exports", [])):
        if not isinstance(record, dict):
            continue
        entry = cast("dict[str, Any]", record)
        requirement = entry.get("requirement")
        fmt = requirement.get("format") if isinstance(requirement, dict) else None  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        if fmt != "step" or "invalid" in entry or "error" in entry:
            continue
        path = entry.get("path")
        if isinstance(path, str) and Path(path).is_file():
            return Path(path)
    return None


@dataclass(frozen=True)
class RunOutcome:
    """Where each sample's candidate ended up, and whether its run passed."""

    outputs_dir: Path
    entries: tuple[Mapping[str, Any], ...] = ()

    @property
    def sample_ids(self) -> tuple[str, ...]:
        return tuple(str(entry["sample_id"]) for entry in self.entries)

    def to_json(self) -> dict[str, Any]:
        solved = sum(1 for entry in self.entries if entry.get("output"))
        return {
            "outputs_dir": str(self.outputs_dir),
            "n_samples": len(self.entries),
            "n_solved": solved,
            "entries": [dict(entry) for entry in self.entries],
        }


def collect_outputs(records: Sequence[RunRecord], outputs_dir: Path) -> RunOutcome:
    """Lay the runs' exported STEPs out as ``<sample>/output.step``.

    Later seeds overwrite earlier ones only when they actually produced an
    export, so a passing seed is never replaced by a failing one's absence.
    """
    outputs_dir.mkdir(parents=True, exist_ok=True)
    entries: dict[str, dict[str, Any]] = {}
    for record in records:
        sample_id = sample_id_for_task(record.task_id)
        directory = outputs_dir / sample_id
        directory.mkdir(parents=True, exist_ok=True)
        exported = exported_step_path(record.grade)
        entry = entries.setdefault(
            sample_id,
            {
                "sample_id": sample_id,
                "task_id": record.task_id,
                "seed": record.seed,
                "passed": False,
                "output": None,
                "reasons": [],
            },
        )
        if exported is None:
            if not entry["output"]:
                entry["reasons"] = list(record.reasons)
                entry["passed"] = bool(record.passed)
                entry["seed"] = record.seed
            continue
        target = directory / SUBMISSION_CANDIDATE
        shutil.copy2(exported, target)
        entry["output"] = str(target)
        entry["passed"] = bool(record.passed)
        entry["seed"] = record.seed
        entry["reasons"] = list(record.reasons)
    ordered = tuple(entries[key] for key in sorted(entries, key=lambda k: (len(k), k)))
    return RunOutcome(outputs_dir=outputs_dir, entries=ordered)


def run_converted(
    tasks: Sequence[BenchTask],
    *,
    provider: ProviderConfig,
    outputs_dir: Path,
    results_dir: Path | None = None,
    seeds: int = 1,
    parallel: int = 1,
    enforce_budget: bool = False,
    **kwargs: Any,
) -> tuple[BenchRun, RunOutcome]:
    """Run converted tasks through the standard harness, then collect the STEPs.

    ``enforce_budget`` defaults to ``False`` — observe mode, exactly as the
    corpus harness does: the run finishes so the true call count is measured,
    and grading is identical either way.
    """
    from hephaestus.bench.harness import run_bench

    run = run_bench(
        tasks,
        provider=provider,
        seeds=seeds,
        results_dir=results_dir,
        parallel=parallel,
        enforce_budget=enforce_budget,
        **kwargs,
    )
    return run, collect_outputs(run.records, outputs_dir)
