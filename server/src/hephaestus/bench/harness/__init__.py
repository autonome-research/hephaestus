"""Bench harness: run one ``corpus/`` task end to end and grade it.

The Tier 3 loop (verification.md §Tier 3, digest §8), one run at a time:

1. **seed** a fresh project from the task spec (``corpus/tasks/<id>/seed/`` copied
   into a scratch root; manifest/``globals.py``/``parts``/``checks`` guaranteed);
2. **prompt** a real orchestrator session — the packaged Node sidecar driven by
   :class:`~hephaestus.agent_bridge.app.BridgeRuntime` against a configurable
   provider — with the task's natural-language prompt plus a deterministic
   per-seed suffix. Normalized ``tool_call`` events are counted against the
   task's budget *live*: exceeding it cancels the run;
3. **grade** after the terminal: build every part in the project, install the
   task's required CHECKS as project checks, run them project-scoped, then
   validate the required exports (bytes sniffed per format, ``as_built`` DXF
   profile count where declared) and required renders. Pass = every required
   check passes AND every export/render validates AND the run stayed within
   budget;
4. **archive** normalized events (JSONL), the run record, the prompt and the
   grading evidence under ``bench/results/<model>/<date>/<task>-s<seed>/``.

The same grading path validates the ``corpus/solutions/`` reference
implementations (:func:`grade_reference_solution`) — a task no reference solution
passes is a broken task, not a hard task.

This module is the package facade; the implementation is split by stage:
:mod:`._tasks` (the corpus task model), :mod:`._seed` (project seeding, protected
restore, reference overlays), :mod:`._exports` (byte-level export acceptance),
:mod:`._grade` (the verdict), :mod:`._run` (provider config, budget guard, run
loop) and :mod:`._archive` (the results layout and its records).
"""

from __future__ import annotations

from ._archive import (
    ARCHIVE_EVENTS_FILENAME,
    ARCHIVE_RESULT_FILENAME,
    BENCH_RESULTS_DIRNAME,
    BenchRun,
    RunRecord,
    results_root,
    session_transcript_dir,
)
from ._exports import dxf_profile_count, validate_export_bytes
from ._grade import GradeReport, grade, grade_reference_solution
from ._run import (
    DEFAULT_PROMPT_TIMEOUT,
    DEFAULT_SEEDS,
    ProviderConfig,
    RunContext,
    RuntimeFactory,
    bench_answerer,
    default_runtime_factory,
    dry_run,
    run_bench,
    run_task,
)
from ._seed import apply_solution, open_cad, restore_protected, seed_project
from ._tasks import (
    PROMPT_SUFFIXES,
    BenchTask,
    ExportRequirement,
    RenderRequirement,
    corpus_solutions_dir,
    corpus_tasks_dir,
    load_tasks,
    seeded_prompt,
    solution_dir,
    task_ids,
)

__all__ = [
    "ARCHIVE_EVENTS_FILENAME",
    "ARCHIVE_RESULT_FILENAME",
    "BENCH_RESULTS_DIRNAME",
    "DEFAULT_PROMPT_TIMEOUT",
    "DEFAULT_SEEDS",
    "PROMPT_SUFFIXES",
    "BenchRun",
    "BenchTask",
    "ExportRequirement",
    "GradeReport",
    "ProviderConfig",
    "RenderRequirement",
    "RunContext",
    "RunRecord",
    "RuntimeFactory",
    "apply_solution",
    "bench_answerer",
    "corpus_solutions_dir",
    "corpus_tasks_dir",
    "default_runtime_factory",
    "dry_run",
    "dxf_profile_count",
    "grade",
    "grade_reference_solution",
    "load_tasks",
    "open_cad",
    "restore_protected",
    "results_root",
    "run_bench",
    "run_task",
    "seed_project",
    "seeded_prompt",
    "session_transcript_dir",
    "solution_dir",
    "task_ids",
    "validate_export_bytes",
]
