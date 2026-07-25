"""``heph bench run`` / ``heph bench score`` CLI verbs (Tier 3 benchmark).

Registered exactly like the Stage 1 render verbs (``cli_render.add_subparsers``)
so the bench stack — provider config, the Node sidecar, the CAD grading path — is
imported only when a bench verb actually runs.

- ``heph bench run --provider FILE --model ID [--tasks a,b] [--seeds N]
  [--results-dir DIR] [--dry-run] [--json]`` runs the public corpus against the
  model named by ``--model`` (which must be declared by the provider file) and
  archives every run under ``bench/results/<model>/<date>/``. ``--dry-run`` lists
  the planned (task, seed) prompts and makes **no** model call.
- ``heph bench score DIR [--model ID] [--date D] [--out FILE] [--json]`` scores an
  archived run directory and writes ``bench/results/<model>/<date>.json``.

Exit codes: 0 success (for ``score``: the gate is met), 1 error / gate not met,
2 usage. ``run`` exits 1 when any run failed so CI surfaces a red bench.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:  # pragma: no cover - typing only
    from hephaestus.bench.harness import RunRecord

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
    try:
        tasks = harness.load_tasks(task_filter)
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
    run = harness.run_bench(
        tasks,
        provider=provider,
        seeds=seeds,
        results_dir=None if results_dir is None else Path(results_dir),
        on_record=None if bool(args.json) else _print_record,
        parallel=int(args.parallel),
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
    if bool(args.json):
        print(json.dumps(score.to_json(), indent=2, sort_keys=True))
    else:
        print(f"model {score.model} date {score.date}: {score.passes}/{score.n} passed")
        print(f"aggregate {score.aggregate:.4f}  wilson_lower_90 {score.wilson_lower_90:.4f}")
        for task_id, row in sorted(score.per_task.items()):
            calls = "-" if row.mean_tool_calls is None else f"{row.mean_tool_calls:.1f}"
            print(f"  {task_id:<18} {row.passes}/{row.n}  mean_tool_calls={calls}")
        if score.perfect_task_failures:
            print(f"  required-perfect tasks failed: {', '.join(score.perfect_task_failures)}")
        print(f"wrote {target}")
    return 0 if score.meets_gate else 1


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
    run.add_argument("--seeds", type=int, default=3, help="seeds per task (default 3)")
    run.add_argument(
        "--parallel",
        type=int,
        default=1,
        help="concurrent (task, seed) runs; each run is fully isolated (default 1)",
    )
    run.add_argument("--results-dir", help="archive root (default bench/results)")
    run.add_argument("--dry-run", action="store_true", help="list planned runs; no model calls")
    run.add_argument("--json", action="store_true", help="emit JSON")
    run.set_defaults(func=_cmd_run)

    score = inner.add_parser("score", help="score an archived run directory")
    score.add_argument("directory", help="bench/results/<model>/<date> directory")
    score.add_argument("--model", help="override the model id in the artifact")
    score.add_argument("--date", help="override the date in the artifact")
    score.add_argument("--out", help="output path (default <dir>/../<date>.json)")
    score.add_argument("--json", action="store_true", help="emit JSON")
    score.set_defaults(func=_cmd_score)


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
