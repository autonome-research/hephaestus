# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""``heph solve`` / ``heph proposals``: the operator's half of Stage 13.

``SOLVER.md`` §11, operator-CLI bullet:

- ``heph solve pose [--json]`` (13A) solves declared free joint parameters for
  declared targets and prints the **solve record** — the verdict, every
  returned assignment (all of them when the outcome is multiplicity, none
  marked chosen), the independently re-measured residuals, and the two blocks'
  determinism tiers.
- ``heph solve placement [--json]`` (13B) proposes a rigid transform per
  declared free part and prints the same record plus the proposal id and ref
  it was recorded as, with each transform decomposed into a translation and an
  axis-angle **for a person to read** — nobody reads a 3x4 matrix, and nobody
  can author one either.
- ``heph solve params [--json]`` (13C) proposes a value per declared free
  ``Param`` and prints the same record plus the proposal id and ref, with each
  value beside the ``min``/``max`` the author declared for it — and with the
  ``distance`` terms named as the local models they are.
- ``heph proposals [--json]`` lists recorded proposals with their read-time
  staleness, withdrawn ones included with their reasons.

**Nothing here applies anything** (``mission_plan.md`` §"Stage 13",
2026-08-30). ``solve pose`` writes nothing at all; ``solve placement`` and
``solve params`` write exactly one thing, an immutable proposal document, and
that document is a measurement. ``solve params`` additionally issues **preview**
builds — that is how a candidate is evaluated at all (``SOLVER.md`` §2C) — and a
preview is never current and never persists an override, so the project's own
geometry and parameters are exactly where they were when the verb started. No
proposal artifact is republished as geometry, no pose is
declared, no parameter is set, no build is made current. There is deliberately
no ``--apply``, no ``--declare-pose``, no ``--write`` and no ``--accept`` flag
on any of these verbs, and there is no inverse from a solved assignment or a
proposed transform to a script expression — writeback is refused, and the
refusal is structural rather than a promise this file could break later.
Turning a proposal into project state is an explicit authoring act through
``declare_pose`` / ``edit_part`` / ``set_params``, where it shows up in git as
a normal diff carrying the author's intent.

Kept out of :mod:`hephaestus.core.cli` for the same reason the assembly,
joints and motion verbs are: the solver's verification pass binds the geometry
kernel, and every other verb must stay free of that cost.

Exit codes match ``heph motion``: 0 success, 1 an outcome that is not a
success — every verdict but ``pose_found`` and ``pose_converged_at_tolerance``,
**including** ``pose_underdetermined_at_tolerance`` and
``multiple_poses_from_starts``, because "here is one member of a continuum" and
"here are two answers and I will not pick" are not passes; a named refusal is
also 1, with its partial evidence on stderr or in the ``--json`` form — and 2
usage. A refusal is never printed as a verdict: a killed or refused solve
decided nothing (``core/motion.py:1489-1498``).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any, TypeVar, cast

from hephaestus.core.cli_errors import CliUsageError, guard, project_root_or_refuse
from hephaestus.core.project_store.layout import load_project, open_store

if TYPE_CHECKING:  # the placement engine binds the geometry kernel; verbs load it lazily
    from hephaestus.core.placement import SolveRecord

__all__ = ["add_proposal_subparser", "add_subparsers"]

#: The two spellings that are a pass for the exit code. Everything else — an
#: under-determined answer, multiplicity, no pose found, an over-constrained
#: floor, unresolvable — is a fact the operator has to read, so a script that
#: gates on ``heph solve pose`` gates on an answer and not on "it ran".
_SUCCESS_VERDICTS = frozenset(
    {"pose_found", "pose_converged_at_tolerance", "converged_at_tolerance"}
)

_T = TypeVar("_T")


class _ArgumentProblems(CliUsageError):
    """Several bad specs in ONE repeatable flag, banked as one refusal.

    A flag taking ``action="append"`` can be wrong several times in a single
    invocation, and a parser that raises on the first spec hides the rest: three
    malformed ``--bound`` specs cost three runs to learn about three mistakes.
    The ledger asks for one refusal listing all of them
    (J-cli-robustness-17), and the per-flag banking in :func:`_collect` only
    delivers that if each parser reports every spec it rejected rather than the
    first. A ``CliUsageError`` subclass, so a caller that does not bank still
    sees the ordinary refusal with the ordinary exit code.
    """

    def __init__(self, problems: Sequence[str]) -> None:
        self.problems: tuple[str, ...] = tuple(problems)
        super().__init__(_joined(self.problems))


def _joined(problems: Sequence[str]) -> str:
    """One problem as itself; several as a bulleted list under one heading."""
    if len(problems) == 1:
        return problems[0]
    return "several arguments are wrong:\n  - " + "\n  - ".join(problems)


def _targets(args: argparse.Namespace) -> list[Any]:
    """The declared targets from ``--constraint`` and ``--point`` (order kept)."""
    from hephaestus.core.placement import ConstraintTarget, PointTarget

    out: list[Any] = []
    problems: list[str] = []
    for constraint_id in cast("Sequence[str]", args.constraint or ()):
        out.append(ConstraintTarget(constraint_id=constraint_id))
    for index, spec in enumerate(cast("Sequence[str]", args.point or ())):
        parts = spec.split(",")
        if len(parts) != 5:
            problems.append(
                f"--point {spec!r} must be ANCHOR,X,Y,Z,TOL_MM "
                "(the anchor, the world-mm target point, and the tolerance)"
            )
            continue
        try:
            x, y, z, tol = (float(value) for value in parts[1:])
        except ValueError:
            problems.append(f"--point {spec!r}: X, Y, Z and TOL_MM must be numbers")
            continue
        out.append(PointTarget(id=f"t{index}", anchor=parts[0], point_mm=(x, y, z), tol_mm=tol))
    if problems:
        raise _ArgumentProblems(problems)
    if not out:
        raise CliUsageError(
            "declare at least one target: --constraint ID or --point ANCHOR,X,Y,Z,TOL_MM"
        )
    return out


def _starts(args: argparse.Namespace, *, what: str = "JOINT") -> list[Any]:
    """The declared starts; absent, the single ``as_built`` start (``SOLVER.md`` §5).

    Both separators are compulsory, for the reason they are in :func:`_box`
    (ledger J-cli-robustness-17). ``--start nonsense`` used to partition into an
    id with an empty body, iterate no pairs, and become a second ``as_built``
    start under a name nobody meant — a *declared* start declaring nothing,
    accepted in silence, while the flag's own metavar says the id, the ``=`` and
    a ``VAR:VALUE`` pair. The empty assignment is meaningful (it is exactly what
    ``as_built`` is), which is why it has to be the default rather than
    something a typo can reach: the record would otherwise name a start whose
    values the operator never wrote. ``what`` is the flag's own noun — joints
    for a pose solve, variables for a placement, params for a params solve — so
    the refusal quotes the metavar the operator read.
    """
    from hephaestus.core.placement import SolveStart

    specs = cast("Sequence[str]", args.start or ())
    if not specs:
        return [SolveStart()]
    form = f"expected ID={what}:VALUE[,{what}:VALUE...]"
    out: list[Any] = []
    problems: list[str] = []
    for spec in specs:
        name, sep, body = spec.partition("=")
        if not sep or not name or not body:
            problems.append(
                f"--start {spec!r}: {form} - the id, '=' and at least one "
                f"{what}:VALUE pair are required (the default start is as_built)"
            )
            continue
        values: dict[str, float] = {}
        bad = False
        for pair in body.split(","):
            variable, colon, raw = pair.partition(":")
            if not colon or not variable:
                problems.append(f"--start {spec!r}: {form} - {pair!r} is not a {what}:VALUE pair")
                bad = True
                break
            try:
                values[variable] = float(raw)
            except ValueError:
                problems.append(f"--start {spec!r}: {form} - {raw!r} is not a number")
                bad = True
                break
        if not bad:
            out.append(SolveStart(id=name, values=values))
    if problems:
        raise _ArgumentProblems(problems)
    return out


def _cmd_pose(args: argparse.Namespace) -> int:
    """Solve free joint parameters for the declared targets, and write nothing."""
    from hephaestus.core.placement import (
        InvalidSolveRequest,
        PoseSolveRequest,
        SolveRunRefusal,
        SolveUnresolvable,
        solve_pose,
    )
    from hephaestus.core.project_store.constraints import ConstraintProvenance

    # Same ordering rule as `solve placement` (ledger J-cli-robustness-17).
    problems = _declaration_problems(args)
    targets = _collect(lambda: _targets(args), problems)
    starts = _collect(lambda: _starts(args), problems)
    _refuse_arguments(problems)
    weights = (
        (float(args.weight_mm), float(args.weight_deg)) if args.weighting == "declared" else None
    )
    request = PoseSolveRequest(
        targets=tuple(targets or ()),
        tol=float(args.tol),
        weighting=str(args.weighting),
        weights=weights,
        regularization=str(args.regularization),
        provenance=ConstraintProvenance(
            requirement=args.requirement,
            assumed=bool(args.assumed),
            reason=args.reason,
        ),
        free_joints=tuple(cast("Sequence[str]", args.joint)) if args.joint else None,
        starts=tuple(starts or ()),
        ceiling=int(args.ceiling) if args.ceiling is not None else None,
    )
    root = project_root_or_refuse()
    layout = load_project(root)
    store = open_store(layout)
    try:
        record = solve_pose(layout, store, request)
    except InvalidSolveRequest as exc:
        return _refused(bool(args.json), exc.to_json(), exc.message)
    except SolveUnresolvable as exc:  # pragma: no cover - verdict 6 rides the record
        return _refused(bool(args.json), exc.to_json(), exc.message)
    except SolveRunRefusal as exc:
        return _refused(bool(args.json), exc.to_json(), exc.message)
    finally:
        store.close()
    if args.json:
        print(json.dumps({"status": "ok", **record.to_json()}, sort_keys=True))
        return 0 if record.verdict in _SUCCESS_VERDICTS else 1
    return _emit(record)


def _refused(json_out: bool, payload: dict[str, Any], message: str) -> int:
    """A named refusal, never a verdict (``SOLVER.md`` §6.3)."""
    if json_out:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(f"heph: {message}", file=sys.stderr)
    return 1


def _emit(record: SolveRecord) -> int:
    """The human form: the verdict, why, and every assignment it is showing."""
    print(f"verdict: {record.verdict}")
    if record.reason:
        print(f"reason: {record.reason}" + (f" ({record.subject})" if record.subject else ""))
    if record.detail:
        print(record.detail)
    for index, assignment in enumerate(record.assignments):
        values = cast("dict[str, float]", assignment.get("values") or {})
        rendered = ", ".join(f"{name}={values[name]:g}" for name in sorted(values))
        active = cast("Sequence[str]", assignment.get("limits_active") or ())
        limits = f"  limits active: {', '.join(active)}" if active else ""
        print(f"  [{index}] from {assignment.get('from_start')}: {rendered}{limits}")
    verification = cast("dict[str, Any]", record.verification)
    for row in cast("Sequence[dict[str, Any]]", verification.get("constraints") or ()):
        state = "satisfied" if row["satisfied"] else "violated"
        print(f"  {row['id']} ({row['kind']}): {state}, measured {row['measured']:g} {row['unit']}")
        for component in cast("Sequence[dict[str, Any]]", row.get("components") or ()):
            if component["role"] == "class_predicate":
                print(
                    f"      {component['key']}: {component['measured']:g} "
                    f"{component['unit']} against a declared bound of "
                    f"{component['bound']:g}"
                )
    for point in cast("Sequence[dict[str, Any]]", verification.get("points") or ()):
        print(
            f"  {point['id']}: re-measured error {point['error_mm']:g} mm "
            f"against a declared {point['bound']:g} mm"
        )
    print("\nnothing was written: applying this is an authoring act (declare_pose)")
    return 0 if record.verdict in _SUCCESS_VERDICTS else 1


def add_subparsers(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
) -> None:
    """Register the ``solve`` verb group on an existing subparser set."""
    solve = sub.add_parser(
        "solve",
        help="propose values for declared free variables (writes nothing)",
    )
    verbs = solve.add_subparsers(dest="solve_command", required=True)
    pose = verbs.add_parser(
        "pose", help="solve free joint parameters for declared targets (SOLVER.md §2A)"
    )
    pose.add_argument(
        "--constraint",
        action="append",
        metavar="ID",
        help="drive motion until this declared 8C constraint measures satisfied",
    )
    pose.add_argument(
        "--point",
        action="append",
        metavar="ANCHOR,X,Y,Z,TOL_MM",
        help="drive an anchor's reference point to a world-mm point (the inverse of reach)",
    )
    pose.add_argument(
        "--joint",
        action="append",
        metavar="JOINT_ID",
        help="a free joint parameter (default: every resolvable free scalar joint)",
    )
    pose.add_argument(
        "--start",
        action="append",
        metavar="ID=JOINT:VALUE[,JOINT:VALUE]",
        help="a declared start (default: the single as_built start; no random restarts)",
    )
    pose.add_argument("--tol", type=float, required=True, help="declared tolerance")
    pose.add_argument(
        "--weighting",
        choices=("unit_scaled_v1", "declared"),
        required=True,
        help="how mm and deg rows compare - a declared choice, never a silent default",
    )
    pose.add_argument("--weight-mm", type=float, default=None)
    pose.add_argument("--weight-deg", type=float, default=None)
    pose.add_argument(
        "--regularization",
        choices=("min_norm_from_start",),
        required=True,
        help="which member of a positive-dimensional solution set is returned",
    )
    pose.add_argument("--requirement", default=None, help="the requirement id this solve serves")
    pose.add_argument("--assumed", action="store_true", help="declare this solve an assumption")
    pose.add_argument("--reason", default=None, help="why the assumption is believed")
    pose.add_argument("--ceiling", type=int, default=None, help="iteration ceiling")
    pose.add_argument("--json", action="store_true", help="emit the machine form")
    pose.set_defaults(func=guard(_cmd_pose))

    placement = verbs.add_parser(
        "placement",
        help="propose a rigid transform per declared free part (SOLVER.md §2B)",
    )
    placement.add_argument(
        "--constraint",
        action="append",
        metavar="ID",
        help="a declared 8C constraint the proposal is solved towards",
    )
    placement.add_argument(
        "--free",
        action="append",
        metavar="PART",
        help="a part whose placement is proposed (every other part is ground)",
    )
    placement.add_argument(
        "--ground",
        action="append",
        metavar="PART",
        help="assert a part is held still (default: every part these constraints anchor)",
    )
    placement.add_argument(
        "--start",
        action="append",
        metavar="ID=VAR:VALUE[,VAR:VALUE]",
        help="a declared start (default: the single as_built start; no random restarts)",
    )
    placement.add_argument(
        "--bound",
        action="append",
        metavar="VAR=MIN:MAX",
        help="bound one free variable (<part>.tx|ty|tz|rx|ry|rz); never clamped in silence",
    )
    placement.add_argument("--tol", type=float, required=True, help="declared tolerance")
    placement.add_argument(
        "--weighting",
        choices=("unit_scaled_v1", "declared"),
        required=True,
        help="how mm and deg rows compare - a declared choice, never a silent default",
    )
    placement.add_argument("--weight-mm", type=float, default=None)
    placement.add_argument("--weight-deg", type=float, default=None)
    placement.add_argument(
        "--regularization",
        choices=("min_norm_from_start",),
        required=True,
        help="which member of a positive-dimensional solution set is returned",
    )
    placement.add_argument(
        "--requirement", default=None, help="the requirement id this solve serves"
    )
    placement.add_argument(
        "--assumed", action="store_true", help="declare this solve an assumption"
    )
    placement.add_argument("--reason", default=None, help="why the assumption is believed")
    placement.add_argument("--ceiling", type=int, default=None, help="iteration ceiling")
    placement.add_argument("--json", action="store_true", help="emit the machine form")
    placement.set_defaults(func=guard(_cmd_placement))

    params = verbs.add_parser(
        "params",
        help="propose a value per declared free Param (SOLVER.md §2C)",
    )
    params.add_argument(
        "--constraint",
        action="append",
        metavar="ID",
        help="a declared 8C constraint the proposal is solved towards",
    )
    params.add_argument(
        "--free",
        action="append",
        metavar="PARAM",
        help="a free Param: '<part>.<param>' or 'hc.<param>' (the script's own spelling)",
    )
    params.add_argument(
        "--start",
        action="append",
        metavar="ID=PARAM:VALUE[,PARAM:VALUE]",
        help="a declared start (default: the single as_built start; no random restarts)",
    )
    params.add_argument("--tol", type=float, required=True, help="declared tolerance")
    params.add_argument(
        "--weighting",
        choices=("unit_scaled_v1", "declared"),
        required=True,
        help="how mm and deg rows compare - a declared choice, never a silent default",
    )
    params.add_argument("--weight-mm", type=float, default=None)
    params.add_argument("--weight-deg", type=float, default=None)
    params.add_argument(
        "--regularization",
        choices=("min_norm_from_start",),
        required=True,
        help="which member of a positive-dimensional solution set is returned",
    )
    params.add_argument("--requirement", default=None, help="the requirement id this solve serves")
    params.add_argument("--assumed", action="store_true", help="declare this solve an assumption")
    params.add_argument("--reason", default=None, help="why the assumption is believed")
    params.add_argument("--ceiling", type=int, default=None, help="iteration ceiling")
    params.add_argument(
        "--build-budget",
        type=int,
        default=None,
        help="cap on total preview builds this solve's iteration may issue (SOLVER.md §10)",
    )
    params.add_argument("--json", action="store_true", help="emit the machine form")
    params.set_defaults(func=guard(_cmd_params))


def add_proposal_subparser(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
) -> None:
    """Register ``heph proposals`` on an existing subparser set."""
    proposals = sub.add_parser(
        "proposals",
        help="list recorded placement proposals and their staleness (writes nothing)",
    )
    proposals.add_argument(
        "--id", action="append", metavar="PROPOSAL_ID", help="restrict to these proposals"
    )
    proposals.add_argument("--json", action="store_true", help="emit the machine form")
    proposals.set_defaults(func=guard(_cmd_proposals))


def _cmd_placement(args: argparse.Namespace) -> int:
    """Propose placements for the declared free parts, and apply nothing."""
    from hephaestus.core.placement import (
        TRANSFORM_AXES,
        InvalidSolveRequest,
        PlacementSolveRequest,
        SolveRunRefusal,
        SolveUnresolvable,
        propose_placement,
    )
    from hephaestus.core.project_store.constraints import ConstraintProvenance

    # Every pure-argument check runs BEFORE the request is built and before the
    # project is opened, and they are collected so several bad flags produce one
    # refusal listing all of them (ledger J-cli-robustness-17).
    problems = _declaration_problems(args)
    constraints = tuple(cast("Sequence[str]", args.constraint or ()))
    free = tuple(cast("Sequence[str]", args.free or ()))
    if not constraints:
        problems.append("declare at least one --constraint ID to solve towards")
    if not free:
        problems.append("declare at least one --free PART whose placement is proposed")
    box = _collect(lambda: _box(args), problems)
    starts = _collect(lambda: _starts(args, what="VAR"), problems)
    problems.extend(_bound_scope_problems(box, free, TRANSFORM_AXES))
    _refuse_arguments(problems)
    weights = (
        (float(args.weight_mm), float(args.weight_deg)) if args.weighting == "declared" else None
    )
    request = PlacementSolveRequest(
        constraints=constraints,
        free=free,
        ground=tuple(cast("Sequence[str]", args.ground)) if args.ground else None,
        tol=float(args.tol),
        weighting=str(args.weighting),
        weights=weights,
        regularization=str(args.regularization),
        provenance=ConstraintProvenance(
            requirement=args.requirement, assumed=bool(args.assumed), reason=args.reason
        ),
        starts=tuple(starts or ()),
        box=box,
        ceiling=int(args.ceiling) if args.ceiling is not None else None,
    )
    root = project_root_or_refuse()
    layout = load_project(root)
    store = open_store(layout)
    try:
        record = propose_placement(layout, store, request)
    except (InvalidSolveRequest, SolveUnresolvable, SolveRunRefusal) as exc:
        return _refused(bool(args.json), exc.to_json(), exc.message)
    finally:
        store.close()
    if args.json:
        print(json.dumps({"status": "ok", **record.to_json()}, sort_keys=True))
        return 0 if record.verdict in _SUCCESS_VERDICTS else 1
    return _emit_placement(record)


def _box(args: argparse.Namespace) -> dict[str, tuple[float | None, float | None]] | None:
    """``--bound VAR=MIN:MAX`` pairs, or ``None`` for an unbounded solve.

    Both separators are required. The parser used to raise only on a failed
    float conversion, so ``--bound bogus`` partitioned into an empty window,
    partitioned that into two empty bounds, and became an unbounded window on a
    variable nobody declared — a flag whose own help says "never clamped in
    silence", silently ignored (ledger J-cli-robustness-17). A genuinely
    half-open window still parses: it is the *separators* that are compulsory,
    not the numbers.
    """
    specs = cast("Sequence[str]", args.bound or ())
    if not specs:
        return None
    out: dict[str, tuple[float | None, float | None]] = {}
    problems: list[str] = []
    for spec in specs:
        name, sep, window = spec.partition("=")
        low, colon, high = window.partition(":")
        if not sep or not colon or not name:
            problems.append(
                f"--bound {spec!r}: expected VAR=MIN:MAX (either bound may be empty "
                "for a half-open window, but VAR, '=' and ':' are required)"
            )
            continue
        try:
            out[name] = (
                None if low in ("", "none") else float(low),
                None if high in ("", "none") else float(high),
            )
        except ValueError:
            problems.append(f"--bound {spec!r}: MIN and MAX must be numbers (either may be empty)")
    if problems:
        raise _ArgumentProblems(problems)
    return out


def _collect(build: Callable[[], _T], problems: list[str]) -> _T | None:
    """Run one argument parser, banking its refusal instead of raising it.

    Argument-shape errors were reported one per run and *after* the request was
    built, so a user fixing several bad flags paid a full solve setup per
    mistake — and a malformed ``--bound`` was never reported at all, because the
    semantic checks fired first (ledger J-cli-robustness-17).
    """
    try:
        return build()
    except _ArgumentProblems as exc:
        # A repeatable flag reports every spec it rejected, and they join the
        # shared list individually so the refusal reads as one flat inventory
        # rather than a list with a list nested inside it.
        problems.extend(exc.problems)
        return None
    except CliUsageError as exc:
        problems.append(str(exc))
        return None


def _refuse_arguments(problems: Sequence[str]) -> None:
    """Raise one refusal listing every bad argument, or return if there are none."""
    if not problems:
        return
    raise CliUsageError(_joined(problems))


def _declaration_problems(args: argparse.Namespace) -> list[str]:
    """What the invocation must declare about itself, checked without opening anything.

    Provenance (``SOLVER.md`` §1 / ``ASSEMBLY.md`` §1: a solve must say why it
    is believed) and the weights a declared weighting needs. Both are pure
    namespace reads, so they belong in the collected set ahead of the request
    (ledger J-cli-robustness-17) — and the weighting check has to run before
    ``float(args.weight_mm)`` is evaluated at all.
    """
    problems: list[str] = []
    if args.requirement is None and not args.assumed:
        problems.append(
            "provenance is compulsory: cite --requirement ID, or pass --assumed with "
            "--reason TEXT. A solve is an interpretation of intent for the same "
            "reason a constraint is (ASSEMBLY.md §1)"
        )
    if args.assumed and not args.reason:
        problems.append("--assumed requires --reason TEXT (why is this solve believed?)")
    if args.weighting == "declared" and (args.weight_mm is None or args.weight_deg is None):
        problems.append("--weighting declared requires --weight-mm and --weight-deg")
    return problems


def _bound_scope_problems(
    box: dict[str, tuple[float | None, float | None]] | None,
    free: Sequence[str],
    axes: Sequence[str],
) -> list[str]:
    """A ``--bound`` on a variable this request does not have clamps nothing.

    A placement request's free *variables* are ``<part>.<axis>`` over the six
    transform axes, not the ``--free`` part names themselves, so the membership
    test has to decompose the spelling — comparing ``bracket.tx`` against
    ``bracket`` would refuse every legitimate bound there is. The engine already
    refuses a stray box with ``no_free_variables`` once the free set is
    resolved (``placement.py``, ``SOLVER.md`` §6.3); this is the same fact
    reported before the project is opened, in the one refusal that also carries
    the other bad flags (ledger J-cli-robustness-17), and it deliberately says
    nothing the engine's refusal does not.
    """
    if not box or not free:
        return []
    known = {f"{part}.{axis}" for part in free for axis in axes}
    unknown = sorted(set(box) - known)
    if not unknown:
        return []
    return [
        f"--bound names {', '.join(unknown)}, which is not a free variable of this "
        f"request: they are named '<part>.{'|'.join(axes)}' over the declared "
        f"--free parts ({', '.join(free)})"
    ]


def _emit_placement(record: SolveRecord) -> int:
    """The human form: the verdict, the proposal it was recorded as, and what it says."""
    print(f"verdict: {record.verdict}")
    if record.reason:
        print(f"reason: {record.reason}" + (f" ({record.subject})" if record.subject else ""))
    if record.detail:
        print(record.detail)
    if record.proposal_id:
        print(f"proposal: {record.proposal_id} ({record.proposal_ref})")
    for index, placement in enumerate(record.placements):
        start = placement.get("from_start")
        print(f"  [{index}] from {start}:")
        for entry in cast("Sequence[dict[str, Any]]", placement.get("parts") or ()):
            translation = cast("Sequence[float]", entry["translation_mm"])
            axis = cast("Sequence[float]", entry["axis"])
            print(
                f"      {entry['part']}: move ("
                f"{translation[0]:+.4g}, {translation[1]:+.4g}, {translation[2]:+.4g}) mm, "
                f"turn {float(entry['angle_deg']):.4g} deg about "
                f"[{axis[0]:.4g}, {axis[1]:.4g}, {axis[2]:.4g}]"
            )
    verification = cast("dict[str, Any]", record.verification)
    for row in cast("Sequence[dict[str, Any]]", verification.get("constraints") or ()):
        state = "satisfied" if row["satisfied"] else "violated"
        print(f"  {row['id']} ({row['kind']}): {state}, measured {row['measured']:g} {row['unit']}")
        for component in cast("Sequence[dict[str, Any]]", row.get("components") or ()):
            if component["role"] == "class_predicate":
                print(
                    f"      {component['key']}: {component['measured']:g} "
                    f"{component['unit']} against a declared bound of {component['bound']:g}"
                )
    for row in cast("Sequence[dict[str, Any]]", verification.get("collateral") or ()):
        state = "satisfied" if row["satisfied"] else "violated"
        print(f"  (not an objective term) {row['id']} ({row['kind']}): {state}")
    print(
        "\nnothing was applied: this is a measurement. Authoring the edit "
        "(edit_part / set_params) is how a placement becomes geometry"
    )
    return 0 if record.verdict in _SUCCESS_VERDICTS else 1


def _cmd_params(args: argparse.Namespace) -> int:
    """Propose values for the declared free ``Param``s, and set none of them.

    The one verb here that spends kernel time on purpose: every candidate is a
    preview build (``SOLVER.md`` §2C), so a run costs builds rather than
    arithmetic and ``--build-budget`` is what bounds it. What it writes is what
    ``solve placement`` writes — one immutable proposal document — and what it
    does NOT write is every parameter it proposed: there is no ``--apply`` and
    no ``--set``, because turning a proposed value into project state is an
    authoring act through ``set_params`` or an edit to the declaration, and
    which of those the author meant is not this verb's to guess.
    """
    from hephaestus.core.placement import (
        InvalidSolveRequest,
        PlacementSolveRequest,
        SolveRunRefusal,
        SolveUnresolvable,
        propose_placement,
    )
    from hephaestus.core.project_store.constraints import ConstraintProvenance

    # Same ordering rule as `solve placement` (ledger J-cli-robustness-17).
    problems = _declaration_problems(args)
    constraints = tuple(cast("Sequence[str]", args.constraint or ()))
    free = tuple(cast("Sequence[str]", args.free or ()))
    if not constraints:
        problems.append("declare at least one --constraint ID to solve towards")
    if not free:
        problems.append("declare at least one --free PARAM whose value is proposed")
    starts = _collect(lambda: _starts(args, what="PARAM"), problems)
    _refuse_arguments(problems)
    weights = (
        (float(args.weight_mm), float(args.weight_deg)) if args.weighting == "declared" else None
    )
    request = PlacementSolveRequest(
        constraints=constraints,
        free=free,
        tol=float(args.tol),
        weighting=str(args.weighting),
        weights=weights,
        regularization=str(args.regularization),
        provenance=ConstraintProvenance(
            requirement=args.requirement, assumed=bool(args.assumed), reason=args.reason
        ),
        starts=tuple(starts or ()),
        ceiling=int(args.ceiling) if args.ceiling is not None else None,
        space="parameters",
        build_budget=int(args.build_budget) if args.build_budget is not None else None,
    )
    root = project_root_or_refuse()
    layout = load_project(root)
    store = open_store(layout)
    try:
        record = propose_placement(layout, store, request)
    except (InvalidSolveRequest, SolveUnresolvable, SolveRunRefusal) as exc:
        return _refused(bool(args.json), exc.to_json(), exc.message)
    finally:
        store.close()
    if args.json:
        print(json.dumps({"status": "ok", **record.to_json()}, sort_keys=True))
        return 0 if record.verdict in _SUCCESS_VERDICTS else 1
    return _emit_params(record)


def _emit_params(record: SolveRecord) -> int:
    """The human form: the verdict, the proposal, and every value beside its box."""
    print(f"verdict: {record.verdict}")
    if record.reason:
        print(f"reason: {record.reason}" + (f" ({record.subject})" if record.subject else ""))
    if record.detail:
        print(record.detail)
    if record.proposal_id:
        print(f"proposal: {record.proposal_id} ({record.proposal_ref})")
    for index, placement in enumerate(record.placements):
        print(f"  [{index}] from {placement.get('from_start')}:")
        for entry in cast("Sequence[dict[str, Any]]", placement.get("parameters") or ()):
            flag = " (an INTEGER Param: this value is not rounded)" if entry.get("integral") else ""
            print(
                f"      {entry['name']} = {float(entry['value']):.6g}  "
                f"[declared {float(entry['min']):g} .. {float(entry['max']):g}]{flag}"
            )
        active = cast("Sequence[str]", placement.get("bounds_active") or ())
        if active:
            print(f"      on its declared bound: {', '.join(active)}")
    verification = cast("dict[str, Any]", record.verification)
    for row in cast("Sequence[dict[str, Any]]", verification.get("constraints") or ()):
        state = "satisfied" if row["satisfied"] else "violated"
        print(f"  {row['id']} ({row['kind']}): {state}, measured {row['measured']:g} {row['unit']}")
    for row in cast("Sequence[dict[str, Any]]", verification.get("collateral") or ()):
        state = "satisfied" if row["satisfied"] else "violated"
        print(f"  (not an objective term) {row['id']} ({row['kind']}): {state}")
    if record.nonsmooth_terms:
        print(f"  nonsmooth terms: {', '.join(record.nonsmooth_terms)}")
        print("  (a `distance` term is a LOCAL model - SOLVER.md §3.2)")
    builds = record.solver_core.get("builds_issued")
    if builds is not None:
        print(f"  preview builds issued: {builds} (none of them current, none persisted)")
    print(
        "\nnothing was applied: this is a measurement. Authoring the change "
        "(set_params / edit_part) is how a proposed value becomes geometry"
    )
    return 0 if record.verdict in _SUCCESS_VERDICTS else 1


def _cmd_proposals(args: argparse.Namespace) -> int:
    """List recorded proposals with their read-time staleness (``SOLVER.md`` §8)."""
    from hephaestus.core.project_store.proposals import (
        ProposalError,
        ProposalSet,
        proposal_views,
    )
    from hephaestus.core.project_store.publication import Publisher

    root = project_root_or_refuse()
    layout = load_project(root)
    store = open_store(layout)
    try:
        proposals = ProposalSet(layout, store)
        state = proposals.state()
        publisher = Publisher(layout, store)

        def current(part: str) -> str | None:
            result = publisher.current_result(part)
            return None if result is None else result.artifact_ref

        try:
            views = proposal_views(
                state, current, ids=list(cast("Sequence[str]", args.id)) if args.id else None
            )
        except ProposalError as exc:
            payload: dict[str, Any] = {
                "status": exc.reason,
                "reason": exc.reason,
                "message": exc.message,
            }
            return _refused(bool(args.json), payload, exc.message)
    finally:
        store.close()
    if args.json:
        print(
            json.dumps(
                {
                    "status": "ok",
                    "generation": state.generation,
                    "artifact_ref": state.artifact_ref,
                    "proposals": views,
                },
                sort_keys=True,
            )
        )
        return 0
    print(f"generation: {state.generation}")
    if not views:
        print("no placement proposals recorded")
        return 0
    for view in views:
        flags: list[str] = []
        if view.get("stale"):
            flags.append(f"stale ({', '.join(cast('Sequence[str]', view['changed_refs']))})")
        if view.get("withdrawn"):
            flags.append(f"withdrawn: {view.get('withdrawn_reason')}")
        suffix = ("  [" + "; ".join(flags) + "]") if flags else ""
        parts = ", ".join(cast("Sequence[str]", view.get("parts") or ()))
        print(f"  {view['id']}  {view['verdict']}  {view['space']}  parts: {parts}{suffix}")
    return 0
