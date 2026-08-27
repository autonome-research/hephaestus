# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""``heph joints`` CLI verb: the operator's view of the joint and pose sets.

``KINEMATICS.md`` §6, operator-CLI bullet — the Stage 9A subset. One verb,
deliberately read-only:

- ``heph joints [--json]`` prints the declared joint and pose entries —
  withdrawn ones included, marked with their recorded reasons, because
  generational state is honest only if every generation stays readable — joined
  with the **latest projected** ``MotionStatus`` per-joint and per-pose
  outcomes, plus which forest parts have been rebuilt since (``stale``). It
  computes nothing, so it is instant and safe to run anywhere.

There is no ``check`` sub-verb here: re-evaluation is the ``check_motion``
model tool in 9A, and the operator-side evaluate verb is ``heph motion check``
(Stage 9B, with the sweep results this verb deliberately does not claim).

Kept out of :mod:`hephaestus.core.cli` for the same reason the assembly verbs
are: the motion evaluator binds the geometry kernel, and every other verb must
stay free of that cost.

Exit codes match ``heph assembly``: 0 success, 1 error — including a status
with an ``unresolvable`` joint or pose, so a script can gate on motion state
the way it gates on assembly state — 2 usage. A project that has never
evaluated its motion state is reported as such and exits 0: "not measured" is
a fact about the project, not a CLI failure.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import TYPE_CHECKING

from hephaestus.core.project_store.layout import find_project_root, load_project, open_store

if TYPE_CHECKING:  # the motion module binds the geometry kernel; the verb loads it lazily
    from hephaestus.core.motion import MotionStatus
    from hephaestus.core.project_store.kinematics import JointEntry, JointState, PoseState

__all__ = ["add_subparsers"]

_JOINT_HEADER = ("id", "kind", "parent", "child", "limits", "provenance", "state", "detail")
_POSE_HEADER = ("id", "joints", "provenance", "state", "detail")


def _cmd_joints(args: argparse.Namespace) -> int:
    """Print the declared sets with the projected status (no evaluation)."""
    from hephaestus.core.motion import MotionEvaluator

    root = find_project_root(Path.cwd())
    layout = load_project(root)
    store = open_store(layout)
    try:
        evaluator = MotionEvaluator(layout, store)
        status = evaluator.projected()
        motion_ref = evaluator.projected_ref()
        joint_state = evaluator.joints.state()
        pose_state = evaluator.poses.state()
    finally:
        store.close()
    json_out = bool(args.json)
    if status is None:
        if json_out:
            print(
                json.dumps(
                    {
                        "status": "not_evaluated",
                        "joint_generation": joint_state.generation,
                        "pose_generation": pose_state.generation,
                        "joints": [entry.to_json() for entry in joint_state.entries],
                        "poses": [entry.to_json() for entry in pose_state.entries],
                    },
                    sort_keys=True,
                )
            )
        elif not joint_state.entries and not pose_state.entries:
            print("no joints or poses declared")
        else:
            print(
                f"{len(joint_state.active)} joint(s) and {len(pose_state.active)} pose(s) "
                "declared, never evaluated — run the check_motion tool "
                "('heph motion check' is Stage 9B)"
            )
        return 0
    if json_out:
        print(
            json.dumps(
                {
                    "status": "ok",
                    "joint_generation": joint_state.generation,
                    "pose_generation": pose_state.generation,
                    "joints": [entry.to_json() for entry in joint_state.entries],
                    "poses": [entry.to_json() for entry in pose_state.entries],
                    "motion": status.to_json(),
                    "motion_ref": motion_ref,
                },
                sort_keys=True,
            )
        )
        return 1 if status.blocking() else 0
    return _emit(joint_state, pose_state, status)


def _emit(joint_state: JointState, pose_state: PoseState, status: MotionStatus) -> int:
    """The two tables, the counts line, and the staleness note.

    Every declared entry gets a row: a withdrawn one carries its reason, an
    active one carries the projected outcome, and one declared since the last
    evaluation says ``not measured`` — nothing is silently skipped.
    """
    joint_outcomes = {outcome.id: outcome for outcome in status.joints}
    pose_outcomes = {outcome.id: outcome for outcome in status.poses}

    if not joint_state.entries:
        print("no joints declared")
    else:
        print("joints:")
        rows: list[tuple[str, ...]] = [_JOINT_HEADER]
        for entry in joint_state.entries:
            if entry.withdrawn:
                state, detail = "WITHDRAWN", entry.withdrawn_reason or ""
            elif (outcome := joint_outcomes.get(entry.id)) is not None:
                state = outcome.state if outcome.state == "resolved" else outcome.state.upper()
                detail = outcome.detail or outcome.note or ""
            else:
                state, detail = "not measured", ""
            rows.append(
                (
                    entry.id,
                    entry.kind,
                    entry.parent,
                    entry.child,
                    _limits_cell(entry),
                    _provenance_cell(entry.provenance.requirement),
                    state,
                    detail,
                )
            )
        _print_table(rows)

    if not pose_state.entries:
        print("\nno poses declared")
    else:
        print("\nposes:")
        rows = [_POSE_HEADER]
        for pose in pose_state.entries:
            if pose.withdrawn:
                state, detail = "WITHDRAWN", pose.withdrawn_reason or ""
            elif (outcome := pose_outcomes.get(pose.id)) is not None:
                state = outcome.state if outcome.state == "resolved" else outcome.state.upper()
                detail = outcome.detail or outcome.note or ""
            else:
                state, detail = "not measured", ""
            binding = ", ".join(f"{name}={pose.joints[name]:g}" for name in sorted(pose.joints))
            rows.append(
                (
                    pose.id,
                    binding or "(zero)",
                    _provenance_cell(pose.provenance.requirement),
                    state,
                    detail,
                )
            )
        _print_table(rows)

    counts = status.counts
    print(
        f"\njoint generation {joint_state.generation}, "
        f"pose generation {pose_state.generation}: "
        f"joints {counts['joints']['resolved']} resolved, "
        f"{counts['joints']['unresolvable']} unresolvable; "
        f"poses {counts['poses']['resolved']} resolved, "
        f"{counts['poses']['unresolvable']} unresolvable"
    )
    if status.stale:
        print(
            f"stale: {', '.join(status.stale)} rebuilt since this status was measured — "
            "re-evaluate with check_motion"
        )
    return 1 if status.blocking() else 0


def _limits_cell(entry: JointEntry) -> str:
    """The declared travel in the kind's own unit (``fixed``: 0 DOF, none)."""
    if entry.rotation is not None and entry.translation is not None:
        return (
            f"rot [{entry.rotation.min:g}, {entry.rotation.max:g}] deg, "
            f"trans [{entry.translation.min:g}, {entry.translation.max:g}] mm"
        )
    if entry.limits is not None:
        unit = "deg" if entry.kind == "revolute" else "mm"
        return f"[{entry.limits.min:g}, {entry.limits.max:g}] {unit}"
    return ""


def _provenance_cell(requirement: str | None) -> str:
    """The cited requirement id, or the word the honesty rule leaves: assumed."""
    return requirement if requirement is not None else "assumed"


def _print_table(rows: list[tuple[str, ...]]) -> None:
    widths = [max(len(row[column]) for row in rows) for column in range(len(rows[0]))]
    for row in rows:
        print("  ".join(cell.ljust(widths[column]) for column, cell in enumerate(row)).rstrip())


def add_subparsers(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
) -> None:
    """Register the ``joints`` verb on an existing subparser set."""
    joints = sub.add_parser(
        "joints", help="show declared joints and poses with their latest motion outcomes"
    )
    joints.add_argument("--json", action="store_true", help="emit the machine form")
    joints.set_defaults(func=_cmd_joints)
