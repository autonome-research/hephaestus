"""``heph bench cadgenbench …`` — the five verbs of ``EXTERNAL_EVAL.md`` §2.

``fetch`` (download the public inputs into an out-of-repo cache and record the
revision), ``convert`` (samples -> bench tasks), ``run`` (converted tasks
through the standard session harness), ``package`` (the submission ZIP plus the
benchmark's own sanity check) and ``score`` (the local floor).

Every import of the adapter's working parts is deferred into a handler, exactly
as :mod:`hephaestus.bench.cli_bench` defers the bench stack: registering the
parser must not drag ``huggingface_hub``, the geometry kernel or the Node
sidecar into a process that only wanted ``--help``.

Exit codes match the rest of the bench CLI: 0 success, 1 error / refusal, 2
usage.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

__all__ = ["add_parser"]


def _samples_argument(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    ids = [item.strip() for item in raw.split(",") if item.strip()]
    return ids or None


def _optional_path(raw: str | None) -> Path | None:
    return None if raw is None else Path(raw)


def _emit(args: argparse.Namespace, document: dict[str, Any], lines: Sequence[str]) -> None:
    if bool(getattr(args, "json", False)):
        print(json.dumps(document, indent=2, sort_keys=True))
        return
    for line in lines:
        print(line)


# -- fetch -----------------------------------------------------------------


def _cmd_fetch(args: argparse.Namespace) -> int:
    from ._fetch import fetch_dataset

    try:
        record = fetch_dataset(
            _optional_path(cast("str | None", args.dest)),
            revision=cast("str | None", args.revision),
        )
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"heph bench cadgenbench fetch: {exc}", file=sys.stderr)
        return 1
    _emit(
        args,
        record.to_json(),
        [
            f"{record.repo_id} @ {record.revision}",
            f"{len(record.sample_ids)} samples at {record.snapshot_root}",
            record.attribution,
        ],
    )
    return 0


# -- convert ---------------------------------------------------------------


def _tasks_dir(raw: str | None) -> Path:
    return Path(raw) if raw else Path("cadgenbench-tasks")


def _convert(args: argparse.Namespace) -> tuple[Any, int]:
    """Shared by ``convert`` and ``run``: resolve the source, convert, report."""
    from ._convert import convert_samples
    from ._fetch import resolve_dataset_root

    root = resolve_dataset_root(_optional_path(cast("str | None", args.source)))
    budget = cast("int | None", args.budget)
    report = convert_samples(
        root,
        _tasks_dir(cast("str | None", args.tasks_dir)),
        ids=_samples_argument(cast("str | None", args.samples)),
        budget_tool_calls=None if budget is None else int(budget),
    )
    for refusal in report.refusals:
        print(f"refused {refusal.sample_id}: {refusal.reason} {refusal.detail}", file=sys.stderr)
    return report, (0 if report.ok else 1)


def _cmd_convert(args: argparse.Namespace) -> int:
    try:
        report, code = _convert(args)
    except (OSError, ValueError) as exc:
        print(f"heph bench cadgenbench convert: {exc}", file=sys.stderr)
        return 1
    _emit(
        args,
        cast("dict[str, Any]", report.to_json()),
        [
            f"converted {len(report.tasks)} samples into {report.dest}",
            f"refused {len(report.refusals)}",
        ],
    )
    return code


# -- run -------------------------------------------------------------------


def _cmd_run(args: argparse.Namespace) -> int:
    from hephaestus.bench.harness import ProviderConfig

    from ._run import run_converted

    try:
        report, code = _convert(args)
    except (OSError, ValueError) as exc:
        print(f"heph bench cadgenbench run: {exc}", file=sys.stderr)
        return 1
    if code != 0:
        # A refused sample is a refusal of the whole pass: converting 80 of 81
        # and running anyway would report on a corpus nobody chose.
        return code
    if not report.tasks:
        print("heph bench cadgenbench run: no samples selected", file=sys.stderr)
        return 2
    try:
        provider = ProviderConfig.load(
            Path(cast("str", args.provider)), model=cast("str | None", args.model)
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"heph bench cadgenbench run: {exc}", file=sys.stderr)
        return 2
    run, outcome = run_converted(
        report.tasks,
        provider=provider,
        outputs_dir=Path(cast("str", args.outputs)),
        results_dir=_optional_path(cast("str | None", args.results_dir)),
        seeds=int(cast("int", args.seeds)),
        parallel=int(cast("int", args.parallel)),
        enforce_budget=bool(args.enforce_budget),
    )
    document = outcome.to_json()
    document["archive_dir"] = str(run.archive_dir)
    passed = sum(1 for record in run.records if record.passed)
    _emit(
        args,
        document,
        [
            f"{passed}/{len(run.records)} runs passed; archive {run.archive_dir}",
            f"{document['n_solved']}/{document['n_samples']} samples produced a STEP "
            f"in {outcome.outputs_dir}",
        ],
    )
    return 0 if document["n_solved"] else 1


# -- package ---------------------------------------------------------------


def _sample_set(args: argparse.Namespace) -> list[str]:
    from ._fetch import resolve_dataset_root
    from ._samples import discover_samples

    explicit = _samples_argument(cast("str | None", args.samples))
    if explicit is not None:
        return explicit
    root = resolve_dataset_root(_optional_path(cast("str | None", args.source)))
    return list(discover_samples(root))


def _cmd_package(args: argparse.Namespace) -> int:
    from ._package import PackagingError, SubmissionMeta, package_submission, resolve_sanity_check
    from ._salvage import salvage_from_archive

    if not bool(args.agree_to_publish):
        print(
            "heph bench cadgenbench package: --agree-to-publish is required. "
            "meta.json's agree_to_publish is the leaderboard's only consent gate "
            "and it is the operator's declaration to make, not the harness's.",
            file=sys.stderr,
        )
        return 2
    try:
        sample_ids = _sample_set(args)
    except (OSError, ValueError) as exc:
        print(f"heph bench cadgenbench package: {exc}", file=sys.stderr)
        return 1

    salvage = None
    from_archive = _optional_path(cast("str | None", args.from_archive))
    if from_archive is not None:
        # EXTERNAL_EVAL.md §5 salvage: a sample whose run built a current,
        # successful deliverable but never exported gets its STEP from the
        # archived artifact. Refusals are named per sample; the report (with
        # every artifact ref) lands in salvage.json and the packaging output.
        salvage = salvage_from_archive(
            from_archive, Path(cast("str", args.outputs)), sample_ids=sample_ids
        )
        for entry in salvage.exported:
            print(f"salvaged {entry.sample_id} from {entry.artifact_ref}", file=sys.stderr)
        for entry in salvage.refusals:
            detail = f" ({entry.detail})" if entry.detail else ""
            print(
                f"salvage refused {entry.sample_id}: {entry.status}{detail}", file=sys.stderr
            )

    sanity: Path | None = None
    if not bool(args.skip_sanity_check):
        explicit = _optional_path(cast("str | None", args.sanity_check))
        if explicit is not None:
            sanity = explicit
        else:
            try:
                sanity = resolve_sanity_check(
                    dataset_root=_optional_path(cast("str | None", args.source))
                )
            except (OSError, ValueError, ImportError) as exc:
                print(f"heph bench cadgenbench package: {exc}", file=sys.stderr)
                return 1

    meta = SubmissionMeta(
        submitter_name=cast("str", args.submitter),
        submission_name=cast("str", args.submission),
        agent_url=cast("str | None", args.agent_url),
        notes=cast("str | None", args.notes),
        agree_to_publish=True,
    )
    try:
        report = package_submission(
            Path(cast("str", args.outputs)),
            sample_ids,
            meta,
            Path(cast("str", args.out)),
            sanity_check=sanity,
            allow_missing=bool(args.allow_missing),
        )
    except PackagingError as exc:
        for reason in exc.reasons:
            print(f"heph bench cadgenbench package: {reason}", file=sys.stderr)
        return 1
    document = report.to_json()
    lines = [
        f"wrote {report.zip_path}",
        f"{report.n_solved}/{len(report.entries)} samples carry a candidate "
        f"(sanity check: {report.sanity_check})",
    ]
    if salvage is not None:
        document["salvage"] = salvage.to_json()
        lines.append(
            f"salvaged {len(salvage.exported)} from archive; "
            f"refused {len(salvage.refusals)} (see salvage.json)"
        )
    _emit(args, document, lines)
    return 0


# -- score -----------------------------------------------------------------


def _cmd_score(args: argparse.Namespace) -> int:
    from ._fetch import resolve_dataset_root
    from ._score import score_outputs

    try:
        sample_ids = _sample_set(args)
    except (OSError, ValueError) as exc:
        print(f"heph bench cadgenbench score: {exc}", file=sys.stderr)
        return 1
    dataset_root: Path | None
    try:
        dataset_root = resolve_dataset_root(_optional_path(cast("str | None", args.source)))
    except (OSError, ValueError):
        # Scoring the floor never needs the dataset; only the editing-start
        # facts do, and their absence is reported per sample, not fatal.
        dataset_root = None
    policy: dict[str, Any] = {"align": cast("str", args.align)}
    if args.iou_min is not None:
        policy["iou_min"] = float(cast("float", args.iou_min))
    if args.chamfer_max_mm is not None:
        policy["chamfer_max_mm"] = float(cast("float", args.chamfer_max_mm))
    floor = score_outputs(
        Path(cast("str", args.outputs)), sample_ids, dataset_root=dataset_root, policy=policy
    )
    lines = [
        floor.label,
        f"valid {floor.n_valid}  invalid {floor.n_invalid}  missing {floor.n_missing}"
        f"  of {len(floor.entries)}",
    ]
    for entry in floor.entries:
        detail = ""
        if entry.validity is not None and entry.validity.failures:
            detail = f"  ({', '.join(entry.validity.failures)})"
        lines.append(f"  {entry.sample_id:<8} {entry.status}{detail}")
    _emit(args, floor.to_json(), lines)
    return 0


# -- registration ----------------------------------------------------------


def _add_source(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source", help="dataset snapshot root (default: the fetched cache)")
    parser.add_argument("--samples", help="comma-separated sample ids (default: all)")


def add_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:  # pyright: ignore[reportPrivateUsage]
    """Register ``cadgenbench`` under the ``heph bench`` verb."""
    from ._convert import DEFAULT_BUDGET_TOOL_CALLS, EDITING_BUDGET_TOOL_CALLS

    budget_help = (
        "tool-call budget per task (default: "
        f"{DEFAULT_BUDGET_TOOL_CALLS} generation / {EDITING_BUDGET_TOOL_CALLS} editing)"
    )
    parser = sub.add_parser(
        "cadgenbench", help="external evaluation: the CADGenBench adapter (EXTERNAL_EVAL.md §2)"
    )
    inner = parser.add_subparsers(dest="cadgenbench_command", required=True)

    fetch = inner.add_parser("fetch", help="download the public dataset into a local cache")
    fetch.add_argument("--dest", help="cache directory (default ~/.cache/hephaestus/cadgenbench)")
    fetch.add_argument("--revision", help="dataset revision to pin (default: the repo's main)")
    fetch.add_argument("--json", action="store_true", help="emit JSON")
    fetch.set_defaults(func=_cmd_fetch)

    convert = inner.add_parser("convert", help="convert samples into bench tasks")
    _add_source(convert)
    convert.add_argument("--tasks-dir", help="where converted tasks are written")
    convert.add_argument("--budget", type=int, default=None, help=budget_help)
    convert.add_argument("--json", action="store_true", help="emit JSON")
    convert.set_defaults(func=_cmd_convert)

    run = inner.add_parser("run", help="run converted tasks through the session harness")
    _add_source(run)
    run.add_argument("--tasks-dir", help="where converted tasks are written")
    run.add_argument("--budget", type=int, default=None, help=budget_help)
    run.add_argument("--provider", required=True, help="JSON provider config")
    run.add_argument("--model", help="model id declared by the provider config")
    run.add_argument("--outputs", default="cadgenbench-outputs", help="submission outputs root")
    run.add_argument("--results-dir", help="archive root (default bench/results)")
    run.add_argument("--seeds", type=int, default=1, help="seeds per sample (default 1)")
    run.add_argument("--parallel", type=int, default=1, help="concurrent runs (default 1)")
    run.add_argument(
        "--enforce-budget",
        action="store_true",
        help="cancel a run the moment it exceeds its budget (default: observe)",
    )
    run.add_argument("--json", action="store_true", help="emit JSON")
    run.set_defaults(func=_cmd_run)

    package = inner.add_parser("package", help="assemble and validate the submission ZIP")
    _add_source(package)
    package.add_argument("--outputs", required=True, help="submission outputs root")
    package.add_argument("--out", required=True, help="ZIP path to write")
    package.add_argument("--submitter", required=True, help="meta.json submitter_name")
    package.add_argument("--submission", required=True, help="meta.json submission_name")
    package.add_argument("--agent-url", help="meta.json agent_url (may be omitted -> null)")
    package.add_argument("--notes", help="meta.json notes (<= 500 chars normalized)")
    package.add_argument(
        "--agree-to-publish",
        action="store_true",
        help="declare meta.json agree_to_publish=true (required; operator consent)",
    )
    package.add_argument("--sanity-check", help="path to sanity_check_submission.py")
    package.add_argument(
        "--skip-sanity-check",
        action="store_true",
        help="do not run the benchmark's own checker (recorded as skipped)",
    )
    package.add_argument(
        "--allow-missing",
        action="store_true",
        help="record a sample with no output folder as unsolved instead of failing",
    )
    package.add_argument(
        "--from-archive",
        help=(
            "bench results archive dir (bench/results/<model>/<date>): a sample "
            "with no exported candidate whose run holds a CURRENT successful "
            "deliverable build is exported from the archived artifact; a failed "
            "or absent build is refused by name (EXTERNAL_EVAL.md §5)"
        ),
    )
    package.add_argument("--json", action="store_true", help="emit JSON")
    package.set_defaults(func=_cmd_package)

    score = inner.add_parser("score", help="the local floor over produced candidates")
    _add_source(score)
    score.add_argument("--outputs", required=True, help="submission outputs root")
    score.add_argument("--iou-min", type=float, help="score_step_files iou_min threshold")
    score.add_argument("--chamfer-max-mm", type=float, help="score_step_files chamfer threshold")
    score.add_argument(
        "--align", choices=["as_posed", "principal"], default="as_posed", help="alignment mode"
    )
    score.add_argument("--json", action="store_true", help="emit JSON")
    score.set_defaults(func=_cmd_score)
