"""``heph assembly`` CLI verbs: the operator's view of the constraint set.

``ASSEMBLY.md`` §3. Two verbs, deliberately asymmetric:

- ``heph assembly [--json]`` prints the constraint table with the **latest
  projected** residuals — what the project last measured, plus which parts have
  been rebuilt since (``stale``). It computes nothing, so it is instant and safe
  to run anywhere.
- ``heph assembly check [--id ID]... [--json]`` re-evaluates now against the
  parts' current build artifacts and projects the result.

Kept out of :mod:`hephaestus.core.cli` for the same reason the reference and
diff verbs are: evaluation loads the geometry kernel, and every other verb must
stay free of that cost.

Exit codes match the engine CLI: 0 success, 1 error — including a status with a
``violated`` or ``unresolvable`` constraint, so a script can gate on assembly
state the way it gates on ``heph check`` — 2 usage. A project that has never
evaluated its constraints is reported as such and exits 0: "not measured" is a
fact about the project, not a CLI failure.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, cast

from hephaestus.core.project_store.layout import find_project_root, load_project, open_store

if TYPE_CHECKING:  # the assembly module binds the geometry kernel; verbs load it lazily
    from hephaestus.core.assembly import AssemblyStatus

__all__ = ["add_subparsers"]

_HEADER = ("id", "kind", "a", "b", "state", "measured", "detail")


class _UsageError(Exception):
    """CLI misuse: reported on stderr with exit code 2."""


def _cmd_assembly(args: argparse.Namespace) -> int:
    """Print the projected status (no evaluation)."""
    from hephaestus.core.assembly import AssemblyEvaluator

    root = find_project_root(Path.cwd())
    layout = load_project(root)
    store = open_store(layout)
    try:
        evaluator = AssemblyEvaluator(layout, store)
        status = evaluator.projected()
        declared = evaluator.constraints.state()
    finally:
        store.close()
    if status is None:
        if bool(args.json):
            print(
                json.dumps(
                    {
                        "status": "not_evaluated",
                        "generation": declared.generation,
                        "constraints": [entry.to_json() for entry in declared.entries],
                    },
                    sort_keys=True,
                )
            )
        elif declared.active:
            print(
                f"{len(declared.active)} constraint(s) declared, never evaluated — "
                "run 'heph assembly check'"
            )
        else:
            print("no constraints declared")
        return 0
    return _emit(status, json_out=bool(args.json), stale_note=True)


def _cmd_check(args: argparse.Namespace) -> int:
    """Re-evaluate now against the parts' current builds, and project it."""
    from hephaestus.core.assembly import AssemblyEvaluator

    ids = cast("Sequence[str]", args.id) or None
    root = find_project_root(Path.cwd())
    layout = load_project(root)
    store = open_store(layout)
    try:
        status = AssemblyEvaluator(layout, store).evaluate(ids)
    finally:
        store.close()
    return _emit(status, json_out=bool(args.json), stale_note=False)


def _emit(status: AssemblyStatus, *, json_out: bool, stale_note: bool) -> int:
    if json_out:
        print(json.dumps(status.to_json(), sort_keys=True))
        return 1 if status.blocking() else 0
    if not status.constraints:
        print("no constraints declared")
        return 0
    rows: list[tuple[str, ...]] = [_HEADER]
    for outcome in status.constraints:
        measured = "" if outcome.measured is None else f"{outcome.measured:.6g}"
        unit = outcome.unit or ""
        rows.append(
            (
                outcome.id,
                outcome.kind,
                outcome.a.anchor,
                outcome.b.anchor,
                outcome.state.upper() if outcome.state != "satisfied" else outcome.state,
                f"{measured} {unit}".strip(),
                outcome.detail or outcome.note or "",
            )
        )
    widths = [max(len(row[column]) for row in rows) for column in range(len(_HEADER))]
    for row in rows:
        print("  ".join(cell.ljust(widths[column]) for column, cell in enumerate(row)).rstrip())
    counts = status.counts
    print(
        f"\ngeneration {status.generation}: "
        f"{counts['satisfied']} satisfied, {counts['violated']} violated, "
        f"{counts['unresolvable']} unresolvable"
    )
    if stale_note and status.stale:
        print(
            f"stale: {', '.join(status.stale)} rebuilt since this status was measured — "
            "run 'heph assembly check'"
        )
    return 1 if status.blocking() else 0


def _guard(command: Callable[[argparse.Namespace], int]) -> Callable[[argparse.Namespace], int]:
    """Report assembly-verb misuse as exit 2 regardless of the entry point."""

    def run(args: argparse.Namespace) -> int:
        try:
            return command(args)
        except _UsageError as exc:
            print(f"heph: {exc}", file=sys.stderr)
            return 2

    return run


def add_subparsers(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
) -> None:
    """Register the ``assembly`` verb group on an existing subparser set."""
    assembly = sub.add_parser(
        "assembly", help="show declared constraints and their latest residuals"
    )
    assembly.add_argument("--json", action="store_true", help="emit the AssemblyStatus JSON")
    assembly.set_defaults(func=_guard(_cmd_assembly))

    verbs = assembly.add_subparsers(dest="assembly_command", required=False)
    check = verbs.add_parser("check", help="re-evaluate every constraint against current builds")
    check.add_argument(
        "--id",
        action="append",
        default=[],
        metavar="CONSTRAINT_ID",
        help="evaluate only this constraint (repeatable; not projected)",
    )
    check.add_argument("--json", action="store_true", help="emit the AssemblyStatus JSON")
    check.set_defaults(func=_guard(_cmd_check))
