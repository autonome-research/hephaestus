"""``heph bench run`` / ``heph bench score`` CLI verbs (Tier 3 benchmark).

Registered exactly like the Stage 1 render verbs (``cli_render.add_subparsers``)
so the bench stack — provider config, the Node sidecar, the CAD grading path — is
imported only when a bench verb actually runs.

- ``heph bench run --provider FILE --model ID [--tasks a,b] [--spec S] [--seeds N]
  [--results-dir DIR] [--no-review] [--dry-run] [--json]`` runs the public corpus
  against the model named by ``--model`` (which must be declared by the provider
  file) and archives every run under ``bench/results/<model>/<date>/``. The
  ``VALIDATION.md`` §5/§6 termination-review ladder runs on every run unless
  ``--no-review`` is passed. ``--dry-run`` lists the planned (task, seed) prompts
  and makes **no** model call.
- ``heph bench cadgenbench {fetch,convert,run,package,score}`` is the external
  evaluation adapter (``EXTERNAL_EVAL.md`` §2); see
  :mod:`hephaestus.bench.cadgenbench`.
- ``heph bench score DIR [--model ID] [--date D] [--out FILE] [--json]`` scores an
  archived run directory and writes ``bench/results/<model>/<date>.json``, plus
  the ``VALIDATION.md`` §1 split table (prose and seeded, never averaged; the
  gate names the prose split) and the §8 validation metrics.
- ``heph bench leaderboard [--results-dir DIR] [--out FILE] [--check]``
  regenerates the Stage 7H model-leaderboard page from those artifacts; see
  :mod:`hephaestus.bench.leaderboard`. ``--check`` writes nothing and exits 1 on
  drift, which is how CI notices a scored run whose page was never regenerated.

Exit codes: 0 success (for ``score``: the gate is met), 1 error / gate not met,
2 usage. ``run`` exits 1 when any run failed so CI surfaces a red bench.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:  # pragma: no cover - typing only
    from hephaestus.bench import scoring
    from hephaestus.bench.harness import RunRecord
    from hephaestus.bench.metrics import ValidationMetrics

__all__ = ["add_subparsers", "main"]

#: Subcommand handler signature (``argparse`` namespace -> process exit code).
Handler = Callable[[argparse.Namespace], int]


def _tasks_argument(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    ids = [item.strip() for item in raw.split(",") if item.strip()]
    return ids or None


def _cmd_run(args: argparse.Namespace) -> int:
    from hephaestus.bench import harness

    task_filter = _tasks_argument(cast("str | None", args.tasks))
    seeds = int(cast("int", args.seeds))
    # VALIDATION.md §1: the two spec splits are reported and gated separately, so
    # they must also be *runnable* separately. --tasks names ids outright.
    spec = str(cast("str", args.spec))
    specs = harness.SPECS if spec == "all" else (spec,)
    try:
        tasks = harness.load_tasks(task_filter, specs=specs)
    except (FileNotFoundError, ValueError) as exc:
        print(f"heph bench run: {exc}", file=sys.stderr)
        return 2
    if not tasks:
        print("heph bench run: no corpus tasks selected", file=sys.stderr)
        return 2

    if bool(args.dry_run):
        plan = harness.dry_run(tasks, seeds=seeds)
        if bool(args.json):
            print(json.dumps(plan, indent=2, sort_keys=True))
        else:
            for entry in plan:
                budget = entry["budget_tool_calls"]
                print(f"{entry['task_id']} seed={entry['seed']} budget={budget}")
        return 0

    provider_path = cast("str | None", args.provider)
    if provider_path is None:
        print("heph bench run: --provider is required (or use --dry-run)", file=sys.stderr)
        return 2
    try:
        provider = harness.ProviderConfig.load(
            Path(provider_path), model=cast("str | None", args.model)
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"heph bench run: {exc}", file=sys.stderr)
        return 2

    results_dir = cast("str | None", args.results_dir)
    # VALIDATION.md §5: the agent may not self-declare done, so the termination
    # review runs by default. --no-review is an escape hatch for debugging a
    # model's own loop; it leaves §8's requirement_coverage / review_catch_rate
    # unmeasured, which is the honest reading of a bench that never reviewed.
    review = None if bool(args.no_review) else harness.default_review_hook
    run = harness.run_bench(
        tasks,
        provider=provider,
        seeds=seeds,
        results_dir=None if results_dir is None else Path(results_dir),
        review=review,
        on_record=None if bool(args.json) else _print_record,
        parallel=int(args.parallel),
        enforce_budget=bool(args.enforce_budget),
    )
    if bool(args.json):
        print(json.dumps(run.to_json(), indent=2, sort_keys=True))
    else:
        passed = sum(1 for record in run.records if record.passed)
        print(f"{passed}/{len(run.records)} runs passed; archive {run.archive_dir}")
    return 0 if all(record.passed for record in run.records) else 1


def _print_record(record: RunRecord) -> None:
    verdict = "PASS" if record.passed else "FAIL"
    reasons = "" if record.passed else f" ({', '.join(record.reasons[:3])})"
    print(
        f"{verdict} {record.task_id} seed={record.seed} "
        f"tool_calls={record.tool_calls}/{record.budget_tool_calls}{reasons}"
    )


def _cmd_score(args: argparse.Namespace) -> int:
    from hephaestus.bench import scoring

    directory = Path(cast("str", args.directory))
    if not directory.is_dir():
        print(f"heph bench score: {directory} is not a directory", file=sys.stderr)
        return 2
    try:
        score = scoring.score_directory(
            directory, model=cast("str | None", args.model), date=cast("str | None", args.date)
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"heph bench score: {exc}", file=sys.stderr)
        return 1
    out = cast("str | None", args.out)
    target = Path(out) if out is not None else directory.parent / f"{score.date}.json"
    scoring.write_score(score, target)
    # VALIDATION.md §1: the seeded split is baselined on its first measurement and
    # never re-baselined; writing it is a record, not a gate input.
    baseline = scoring.record_seeded_baseline(
        score, directory.parent / scoring.SEEDED_BASELINE_FILENAME
    )
    # PARTS_STORE.md G11C clause 12: the component family is baselined the same
    # way, on its own first measurement and at >= 3 seeds. A too-thin first
    # measurement is refused BY NAME and nothing is written — printed here rather
    # than swallowed, because a family whose baseline was skipped must not look
    # like a family that was never run.
    component_path = directory.parent / scoring.COMPONENT_BASELINE_FILENAME
    try:
        component = scoring.record_component_baseline(score, component_path)
    except ValueError as exc:
        print(f"heph bench score: component baseline not written: {exc}", file=sys.stderr)
        component = None
    if bool(args.json):
        print(json.dumps(score.to_json(), indent=2, sort_keys=True))
    else:
        print(f"model {score.model} date {score.date}: {score.passes_total}/{score.n_total} passed")
        _print_splits(score, baseline, component, component_path)
        for task_id, row in sorted(score.per_task.items()):
            calls = "-" if row.mean_tool_calls is None else f"{row.mean_tool_calls:.1f}"
            print(f"  {task_id:<24} {row.passes}/{row.n}  mean_tool_calls={calls}")
        _print_metrics(score.metrics)
        if score.perfect_task_failures:
            print(f"  required-perfect tasks failed: {', '.join(score.perfect_task_failures)}")
        print(f"wrote {target}")
    return 0 if score.meets_gate else 1


def _cmd_leaderboard(args: argparse.Namespace) -> int:
    from hephaestus.bench import leaderboard

    results_dir = Path(cast("str", args.results_dir))
    out_path = Path(cast("str", args.out))
    text = leaderboard.render(leaderboard.load_rows(results_dir))
    if bool(args.check):
        # The page is a committed artifact; drift means someone scored a run and
        # did not regenerate. Say which file, and do not rewrite it.
        current = out_path.read_text(encoding="utf-8") if out_path.is_file() else None
        if current == text:
            print(f"{out_path}: up to date")
            return 0
        missing = "does not exist" if current is None else "is out of date"
        print(
            f"heph bench leaderboard: {out_path} {missing}; "
            f"regenerate with `heph bench leaderboard --out {out_path}`",
            file=sys.stderr,
        )
        return 1
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    print(f"wrote {out_path}")
    return 0


def _rate(value: float | None) -> str:
    """Rates that were never measured print as ``-``, never as ``0.000``."""
    return "-" if value is None else f"{value:.3f}"


def _print_splits(
    score: scoring.BenchScore,
    baseline: dict[str, Any] | None,
    component: dict[str, Any] | None = None,
    component_path: Path | None = None,
) -> None:
    """The §1 split table: every split, side by side, never averaged.

    Family splits (``PARTS_STORE.md`` G11C clause 12) print in the same table as
    the two spec splits and under the same rule — a threshold of ``-`` is not a
    formatting choice, it is the fact that nothing gates them.

    An archive that measured **no** family task says so in a named line rather
    than printing nothing (clause 12, "the measurement"). Silence is what let a
    2026-08-29 verifier observe that a reader of a green gate matrix would
    reasonably conclude the component family had been baselined when no
    ``component_baseline.json`` exists anywhere. Absence of measurement is a
    fact about the evidence, so the tool that reads the evidence states it.
    """
    from hephaestus.bench.metrics import SPEC_PROSE, SPEC_SEEDED
    from hephaestus.bench.scoring import COMPONENT_FAMILY_TASKS, FAMILY_COMPONENT

    ordered = [SPEC_PROSE, SPEC_SEEDED, *sorted(set(score.splits) - {SPEC_PROSE, SPEC_SEEDED})]
    print("split            n   passes  pass_rate  wilson_lower_90  threshold  min_seeds")
    for spec in ordered:
        row = score.splits[spec]
        threshold = "-" if row.threshold is None else f"{row.threshold:.2f}"
        print(
            f"{spec:<15} {row.n:>3}   {row.passes:>4}      {row.pass_rate:.3f}"
            f"            {row.wilson_lower_90:.4f}       {threshold:<9}  "
            f"{row.min_seeds_per_task}"
        )
    print(f"interpretation_gap (seeded - prose): {_rate(score.interpretation_gap)}")
    print(f"gate: {SPEC_PROSE} split only (the historical baseline)")
    if baseline is not None:
        print(
            f"seeded baseline (first measurement, not a gate): "
            f"{baseline.get('passes')}/{baseline.get('n')} "
            f"wilson_lower_90={baseline.get('wilson_lower_90')}"
        )
    if component is not None:
        rows = cast("dict[str, Any]", component.get("splits", {}))
        for name, row in sorted(rows.items()):
            entry = cast("dict[str, Any]", row)
            print(
                f"{name} baseline (first measurement, not a gate): "
                f"{entry.get('passes')}/{entry.get('n')} "
                f"wilson_lower_90={entry.get('wilson_lower_90')}"
            )
    else:
        family = FAMILY_COMPONENT
        measured = sum(score.family_split(family, spec).n for spec in (SPEC_PROSE, SPEC_SEEDED))
        recorded = component_path is not None and component_path.is_file()
        if measured:
            # The refusal itself went to stderr with its name and its numbers;
            # this is the stdout table refusing to look complete without it.
            print(
                f"{family} family: {measured} runs measured, NOT BASELINED — "
                f"see the refusal above; nothing was written to {component_path}."
            )
        elif recorded:
            print(
                f"{family} family: not measured in this archive; "
                f"baseline already recorded in {component_path}."
            )
        else:
            tasks = ", ".join(COMPONENT_FAMILY_TASKS)
            print(
                f"{family} family: NOT MEASURED — no {tasks} runs in this archive "
                f"and no {component_path}. PARTS_STORE.md G11C clause 12's "
                f"reference-model baseline is outstanding."
            )


def _print_metrics(metrics: ValidationMetrics) -> None:
    """The §8 metric table (``-`` where there is no evidence)."""
    print("validation metrics (VALIDATION.md §8):")
    print(f"  error_recovery_rate     {_rate(metrics.error_recovery_rate)}")
    print(f"  requirement_coverage    {_rate(metrics.requirement_coverage)}")
    print(f"  clarification_rate      {_rate(metrics.clarification_rate)}")
    print(
        f"  review_catch_rate       {_rate(metrics.review_catch_rate)}"
        f"  (vision {_rate(metrics.review_catch_rate_vision)}"
        f" / numeric {_rate(metrics.review_catch_rate_numeric)})"
    )
    print(f"  spec_tampering_rate     {_rate(metrics.spec_tampering_rate)}")
    # Reported next to the rest, but it measures *us*: harness errors are never
    # charged to the model, so a non-zero number here is our bug to fix.
    harness_errors = metrics.counts.get("harness_error_runs", 0)
    print(
        f"  harness_error_rate      {_rate(metrics.harness_error_rate)}"
        f"  ({harness_errors}/{metrics.n} runs, harness fault, not charged)"
    )


def add_subparsers(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
) -> None:
    """Register the ``bench`` verb (with its ``run``/``score`` subcommands)."""
    bench = sub.add_parser("bench", help="Tier 3 golden-prompt benchmark (corpus tasks)")
    inner = bench.add_subparsers(dest="bench_command", required=True)

    run = inner.add_parser("run", help="run corpus tasks against a configured model")
    run.add_argument("--provider", help="JSON provider config (providers/credentials)")
    run.add_argument("--model", help="model id declared by the provider config")
    run.add_argument("--tasks", help="comma-separated task ids (default: the whole corpus)")
    run.add_argument(
        "--spec",
        choices=["prose", "seeded", "all"],
        default="all",
        help="corpus spec split to run (default: both, reported separately)",
    )
    run.add_argument("--seeds", type=int, default=3, help="seeds per task (default 3)")
    run.add_argument(
        "--enforce-budget",
        action="store_true",
        help=(
            "cancel a run the moment it exceeds its budget (default: observe — "
            "let it finish so the true call count is measured; grading is "
            "identical either way)"
        ),
    )
    run.add_argument(
        "--parallel",
        type=int,
        default=1,
        help="concurrent (task, seed) runs; each run is fully isolated (default 1)",
    )
    run.add_argument("--results-dir", help="archive root (default bench/results)")
    run.add_argument(
        "--no-review",
        action="store_true",
        help=(
            "skip the VALIDATION.md §5/§6 termination review (it runs by default); "
            "leaves requirement_coverage and review_catch_rate unmeasured"
        ),
    )
    run.add_argument("--dry-run", action="store_true", help="list planned runs; no model calls")
    run.add_argument("--json", action="store_true", help="emit JSON")
    run.set_defaults(func=_cmd_run)

    # EXTERNAL_EVAL.md §2: the external adapter rides the same `heph bench`
    # surface. Registering it is cheap — every working import inside it is
    # deferred into a handler, so `heph bench --help` still pulls in nothing.
    from hephaestus.bench.cadgenbench._cli import add_parser as add_cadgenbench_parser

    add_cadgenbench_parser(inner)

    score = inner.add_parser("score", help="score an archived run directory")
    score.add_argument("directory", help="bench/results/<model>/<date> directory")
    score.add_argument("--model", help="override the model id in the artifact")
    score.add_argument("--date", help="override the date in the artifact")
    score.add_argument("--out", help="output path (default <dir>/../<date>.json)")
    score.add_argument("--json", action="store_true", help="emit JSON")
    score.set_defaults(func=_cmd_score)

    board = inner.add_parser(
        "leaderboard",
        help="regenerate the model-leaderboard page from archived result artifacts",
    )
    board.add_argument(
        "--results-dir",
        default="bench/results",
        help="archive root holding <model>/<date>.json (default bench/results)",
    )
    board.add_argument(
        "--out",
        default="docs/leaderboard.md",
        help="page to write (default docs/leaderboard.md)",
    )
    board.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if the page on disk differs from the generated page; write nothing",
    )
    board.set_defaults(func=_cmd_leaderboard)


def main(argv: list[str] | None = None) -> int:
    """Standalone entry point: ``python -m hephaestus.bench.cli_bench run …``."""
    parser = argparse.ArgumentParser(prog="heph", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    add_subparsers(sub)
    args = parser.parse_args(argv)
    handler = cast("Handler | None", getattr(args, "func", None))
    if handler is None:  # pragma: no cover - argparse requires a subcommand
        parser.error("no command")
        return 2
    return handler(args)


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
