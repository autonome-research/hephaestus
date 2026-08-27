# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""``heph motion`` CLI verbs: the operator's view of the motion-check state.

``KINEMATICS.md`` §6, operator-CLI bullet — the Stage 9B/9C subset. Two
verbs, deliberately asymmetric (the ``heph assembly`` shape):

- ``heph motion [--json]`` prints the projected ``MotionStatus`` counts, the
  motion-check table joined with the **latest projected** sweep results —
  what the project last measured, withdrawn entries included with their
  recorded reasons, plus which parts have been rebuilt since (``stale``) —
  and the **coupling table** (Stage 9C, ``KINEMATICS.md`` §5/§6): every
  declared ``child = ratio * parent + offset`` relationship, withdrawn
  entries included with their reasons, because generational state is honest
  only if every generation stays readable. It computes nothing, so it is
  instant and safe to run anywhere. ``results: null`` / ``not measured`` is
  said out loud: checks that were never evaluated are not passing ones.
- ``heph motion check [ID ...] [--json]`` re-evaluates now — the full
  ``MotionStatus`` plus every named (default: every active) motion check's
  bounded grid — and projects a full run's results so a later ``heph
  motion`` (and the §5 reviewer) sees them. A named subset is evaluated but
  deliberately not projected (the ``check_assembly`` rule), and says so.

Kept out of :mod:`hephaestus.core.cli` for the same reason the assembly and
joints verbs are: the motion evaluator binds the geometry kernel, and every
other verb must stay free of that cost.

Exit codes match ``heph assembly``: 0 success, 1 error — including any motion
check in a non-success verdict (``violated``, ``not_reached_at_samples``,
``unresolvable``) or an ``unresolvable`` joint or pose, the §6 never-green
rule, so a script can gate on motion state — 2 usage (including naming an
undeclared check id). A project that has never evaluated its motion checks is
reported as such and exits 0: "not measured" is a fact about the project, not
a CLI failure. A sweep hitting the §4 wall-clock ceiling is the named
``motion_timeout`` refusal on stderr, its partial per-sample facts carried in
the ``--json`` form, exit 1 — partial evidence, never a hang and never a
silent pass.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, cast

from hephaestus.core.project_store.layout import find_project_root, load_project, open_store

if TYPE_CHECKING:  # the motion module binds the geometry kernel; verbs load it lazily
    from hephaestus.core.motion import MotionStatus, SweepResult
    from hephaestus.core.project_store.kinematics import CouplingState, MotionCheckState
    from hephaestus.core.project_store.layout import ProjectLayout

    from opstore import OpStore

__all__ = ["add_subparsers"]

_CHECK_HEADER = ("id", "kind", "subject", "sweep", "verdict", "worst", "detail")
_COUPLING_HEADER = ("id", "child", "=", "provenance", "state", "detail")

#: The §4 success spellings; every other verdict is blocking for the CLI exit
#: code exactly as it is for the §6 termination reviewer.
_SUCCESS_VERDICTS = frozenset({"holds_at_samples", "satisfied"})


class _UsageError(Exception):
    """CLI misuse: reported on stderr with exit code 2."""


def _cmd_motion(args: argparse.Namespace) -> int:
    """Print the projected status and latest sweep results (no evaluation)."""
    from hephaestus.core.motion import MotionEvaluator, SweepEvaluator

    root = find_project_root(Path.cwd())
    layout = load_project(root)
    store = open_store(layout)
    try:
        evaluator = MotionEvaluator(layout, store)
        sweeps = SweepEvaluator(layout, store)
        status = evaluator.projected()
        motion_ref = evaluator.projected_ref()
        results = sweeps.projected_results()
        results_ref = sweeps.projected_results_ref()
        check_state = sweeps.checks.state()
        check_generation = sweeps.projected_check_generation()
        coupling_state = sweeps.couplings.state()
    finally:
        store.close()
    json_out = bool(args.json)
    if json_out:
        # The coupling table (KINEMATICS.md §5/§6, Stage 9C): the declared
        # set restated verbatim — withdrawn entries included with their
        # reasons — on the check-table precedent (generation + entries).
        payload = {
            "status": "ok" if status is not None else "not_evaluated",
            "check_generation": check_state.generation,
            "checks": [entry.to_json() for entry in check_state.entries],
            "results": (None if results is None else [result.to_json() for result in results]),
            "results_ref": results_ref,
            "results_check_generation": check_generation,
            "coupling_generation": coupling_state.generation,
            "couplings": [entry.to_json() for entry in coupling_state.entries],
            "motion": None if status is None else status.to_json(),
            "motion_ref": motion_ref,
        }
        print(json.dumps(payload, sort_keys=True))
        return _exit_code(status, results)
    if status is None and not check_state.entries and not coupling_state.entries:
        print("no motion checks declared, motion state never evaluated")
        return 0
    if status is not None:
        counts = status.counts
        print(
            f"joints {counts['joints']['resolved']} resolved, "
            f"{counts['joints']['unresolvable']} unresolvable; "
            f"poses {counts['poses']['resolved']} resolved, "
            f"{counts['poses']['unresolvable']} unresolvable"
            + (f"; blocking: {', '.join(status.blocking())}" if status.blocking() else "")
        )
    else:
        print(_NEVER_EVALUATED)
    _emit_checks(check_state, results)
    _emit_couplings(coupling_state)
    if status is not None and status.stale:
        print(
            f"\nstale: {', '.join(status.stale)} rebuilt since this state was measured — "
            "re-evaluate with 'heph motion check'"
        )
    return _exit_code(status, results)


_NEVER_EVALUATED = "motion state never evaluated — run 'heph motion check'"


def _cmd_check(args: argparse.Namespace) -> int:
    """Re-evaluate now against the parts' current builds, and project a full run."""
    from hephaestus.core.errors import AddressingError
    from hephaestus.core.motion import MotionTimeout, check_motion_with_results

    ids = cast("Sequence[str]", args.ids) or None
    root = find_project_root(Path.cwd())
    layout = load_project(root)
    store = open_store(layout)
    try:
        try:
            status, results, partial = check_motion_with_results(layout, store, ids=ids)
        except AddressingError as exc:
            raise _UsageError(
                f"{exc.message} (declared: {', '.join(exc.candidates) or 'none'})"
            ) from exc
        except MotionTimeout as exc:
            # §4: the ceiling kill is a named refusal carrying partial
            # per-sample facts — printed, never dressed as a verdict.
            if bool(args.json):
                print(json.dumps(exc.to_json(), sort_keys=True))
            print(f"heph: motion_timeout: {exc.message}", file=sys.stderr)
            return 1
        check_state = _check_state(layout, store)
    finally:
        store.close()
    if bool(args.json):
        payload = {
            "status": "ok",
            "motion": status.to_json(),
            "results": [result.to_json() for result in results],
            "partial": partial,
        }
        print(json.dumps(payload, sort_keys=True))
        return _exit_code(status, results)
    counts = status.counts
    print(
        f"joints {counts['joints']['resolved']} resolved, "
        f"{counts['joints']['unresolvable']} unresolvable; "
        f"poses {counts['poses']['resolved']} resolved, "
        f"{counts['poses']['unresolvable']} unresolvable"
    )
    _emit_checks(check_state, results, only_evaluated=partial)
    if partial:
        print("\npartial: a named subset was evaluated and deliberately not projected")
    return _exit_code(status, results)


def _check_state(layout: ProjectLayout, store: OpStore) -> MotionCheckState:
    """The declared check set (a tiny seam so both verbs share one read)."""
    from hephaestus.core.project_store.kinematics import JointSet, MotionCheckSet

    return MotionCheckSet(layout, store, JointSet(layout, store)).state()


def _emit_checks(
    check_state: MotionCheckState,
    results: Sequence[SweepResult] | None,
    *,
    only_evaluated: bool = False,
) -> None:
    """The check table: every declared entry gets a row, nothing silently skipped.

    A withdrawn entry carries its recorded reason, an evaluated one its §4
    result record, and one declared since the last evaluation says ``not
    measured``. With ``only_evaluated`` (a partial ``heph motion check`` run)
    the table is exactly the evaluated subset, because the run measured
    nothing else.
    """
    by_id = {result.id: result for result in results or ()}
    if not check_state.entries:
        print("no motion checks declared")
        return
    print("\nmotion checks:")
    rows: list[tuple[str, ...]] = [_CHECK_HEADER]
    for entry in check_state.entries:
        result = by_id.get(entry.id)
        if only_evaluated and result is None:
            continue
        subject = entry.anchor if entry.kind == "reach" else f"{entry.a} / {entry.b}"
        sweep = ", ".join(
            f"{joint_id} [{entry.sweep[joint_id].start:g}, {entry.sweep[joint_id].stop:g}]"
            for joint_id in sorted(entry.sweep)
        )
        if entry.withdrawn:
            verdict, worst, detail = "WITHDRAWN", "", entry.withdrawn_reason or ""
        elif result is not None:
            verdict = (
                result.verdict if result.verdict in _SUCCESS_VERDICTS else result.verdict.upper()
            )
            worst = (
                "" if result.worst is None else f"{result.worst.measured:.6g} {result.unit}".strip()
            )
            detail = result.detail or result.note or ""
        else:
            verdict, worst, detail = "not measured", "", ""
        rows.append((entry.id, entry.kind, subject or "", sweep, verdict, worst, detail))
    widths = [max(len(row[column]) for row in rows) for column in range(len(_CHECK_HEADER))]
    for row in rows:
        print("  ".join(cell.ljust(widths[column]) for column, cell in enumerate(row)).rstrip())


def _emit_couplings(coupling_state: CouplingState) -> None:
    """The §5 coupling table: every declared entry, nothing silently skipped.

    ``child = ratio * parent + offset`` spelled out per row, withdrawn
    entries carrying their recorded reasons. A project with no couplings
    prints no table — there is no claim to report, so nothing is skipped.
    """
    if not coupling_state.entries:
        return
    print("\ncouplings:")
    rows: list[tuple[str, ...]] = [_COUPLING_HEADER]
    for entry in coupling_state.entries:
        if entry.withdrawn:
            state, detail = "WITHDRAWN", entry.withdrawn_reason or ""
        else:
            state, detail = "declared", entry.note or ""
        requirement = entry.provenance.requirement
        rows.append(
            (
                entry.id,
                entry.child,
                f"{entry.ratio:g} * {entry.parent} + {entry.offset:g}",
                requirement if requirement is not None else "assumed",
                state,
                detail,
            )
        )
    widths = [max(len(row[column]) for row in rows) for column in range(len(_COUPLING_HEADER))]
    for row in rows:
        print("  ".join(cell.ljust(widths[column]) for column, cell in enumerate(row)).rstrip())


def _exit_code(status: MotionStatus | None, results: Sequence[SweepResult] | None) -> int:
    """The never-green rule over both sections and every check result."""
    if status is not None and status.blocking():
        return 1
    for result in results or ():
        if result.verdict not in _SUCCESS_VERDICTS:
            return 1
    return 0


def _guard(command: Callable[[argparse.Namespace], int]) -> Callable[[argparse.Namespace], int]:
    """Report motion-verb misuse as exit 2 regardless of the entry point."""

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
    """Register the ``motion`` verb group on an existing subparser set."""
    motion = sub.add_parser(
        "motion",
        help="show declared motion checks, their latest sweep results, and couplings",
    )
    motion.add_argument("--json", action="store_true", help="emit the machine form")
    motion.set_defaults(func=_guard(_cmd_motion))

    verbs = motion.add_subparsers(dest="motion_command", required=False)
    check = verbs.add_parser(
        "check", help="re-evaluate joints, poses and motion checks against current builds"
    )
    check.add_argument(
        "ids",
        nargs="*",
        metavar="CHECK_ID",
        help="evaluate only these motion checks (a named subset is not projected)",
    )
    check.add_argument("--json", action="store_true", help="emit the machine form")
    check.set_defaults(func=_guard(_cmd_check))
