# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""The ``SOLVER.md`` §11 solving tools (Stage 13A/13B/13C), as thin ops over the engine.

``solve_pose``, ``propose_placement`` and ``read_proposals``. Everything they do
lives one layer down and is deliberately
not reimplemented here (the ``_motion`` precedent, applied verbatim):
:mod:`hephaestus.core.placement` owns the request grammar and its refusal set,
the frame-extraction-once pipeline over the shared ``AnchorResolver``, the
independent verification pass in its own process, and the closed verdict
vocabulary. What this module adds is exactly the tool surface: the argument
shapes, and the mapping from the three refusal families onto stable machine
tokens the model can branch on.

**Nothing here applies anything, and that is the tools' whole contract**
(``mission_plan.md`` §"Stage 13", 2026-08-30). ``solve_pose`` writes nothing at
all. ``propose_placement`` writes exactly one thing — an immutable,
content-addressed proposal document and its index generation — and that
document is a *measurement*: no script, no parameter, no republished artifact,
no build made current, and no path by which a model reaches geometry through
either tool. Applying a solved assignment or a proposed placement stays an
authoring act through ``declare_pose`` / ``edit_part`` / ``set_params``, where
it shows up in git as a normal diff carrying the author's intent.

**Writeback is refused, structurally.** There is no inverse from a transform to
a script expression, so none is computed, offered or guessed: the proposal
document schema is ``additionalProperties: false`` at every level and is
validated before any write, so a ``suggested_edit`` field cannot be emitted,
and every tool input schema in this repo is ``additionalProperties: false``, so
one cannot be requested either. The refusal is a schema fact rather than a
runtime name, because a refusal nobody can trigger is not a safeguard.

**A refusal is not a verdict.** ``invalid_solve_request``, ``unresolvable`` and
the run-time family (``iteration_ceiling``, ``solver_timeout``,
``rank_undecidable``, ``solver_residual_disagreement``) each come back as a
``CadOpError`` with its own token and its partial evidence attached — never as
a member of the seven-spelling pose verdict tuple, the ``motion_timeout`` rule
(``core/motion.py:1489-1498``) copied exactly.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

from hephaestus.core.placement import (
    ConstraintTarget,
    InvalidSolveRequest,
    PlacementSolveRequest,
    PointTarget,
    PoseSolveRequest,
    SolveRunRefusal,
    SolveStart,
    SolveTarget,
    SolveUnresolvable,
    propose_placement,
    solve_pose,
)
from hephaestus.core.project_store.constraints import ConstraintProvenance
from hephaestus.core.project_store.proposals import ProposalSet, proposal_views
from opstore.types import JSONValue

from ._base import CadOpError, CadOpsState

__all__ = ["SolveOps"]


def _targets(raw: Any) -> tuple[SolveTarget, ...]:
    """The declared targets, both forms, refused by name rather than guessed."""
    if not isinstance(raw, list) or not raw:
        raise CadOpError(
            "invalid_solve_request",
            "solve_pose needs a non-empty targets array; a solve with nothing to "
            "drive towards has no answer to report",
        )
    out: list[SolveTarget] = []
    for item in cast("list[Any]", raw):
        if not isinstance(item, dict):
            raise CadOpError("invalid_solve_request", "each target must be an object")
        entry = cast("Mapping[str, Any]", item)
        form = entry.get("form")
        if form == "constraint":
            out.append(ConstraintTarget(constraint_id=str(entry["constraint_id"])))
            continue
        if form == "anchor_point":
            point = cast("Sequence[float]", entry["point_mm"])
            out.append(
                PointTarget(
                    id=str(entry["id"]),
                    anchor=str(entry["anchor"]),
                    point_mm=(float(point[0]), float(point[1]), float(point[2])),
                    tol_mm=float(entry["tol_mm"]),
                )
            )
            continue
        raise CadOpError(
            "invalid_solve_request",
            f"unknown target form {form!r}; the two forms are 'anchor_point' "
            "(the inverse of reach) and 'constraint' (a declared 8C constraint id)",
        )
    return tuple(out)


def _starts(raw: Any) -> tuple[SolveStart, ...]:
    """The declared starts, defaulting to the single ``as_built`` start (§5)."""
    if raw is None:
        return (SolveStart(),)
    if not isinstance(raw, list) or not raw:
        raise CadOpError("invalid_solve_request", "starts must be a non-empty array")
    out: list[SolveStart] = []
    for item in cast("list[Any]", raw):
        entry = cast("Mapping[str, Any]", item)
        values = cast("Mapping[str, Any]", entry.get("values") or {})
        out.append(
            SolveStart(
                id=str(entry["id"]),
                values={str(k): float(v) for k, v in values.items()},
            )
        )
    return tuple(out)


def _provenance(raw: Any) -> ConstraintProvenance:
    """The compulsory 8C provenance, read without repair.

    A solve is an interpretation of intent for the same reason a constraint is
    (``ASSEMBLY.md:52-54``), so a request with neither a requirement id nor
    ``assumed`` is refused ``missing_provenance`` one layer down — not
    defaulted here to ``assumed``, which would invent the interpretation this
    field exists to attribute.
    """
    entry = cast("Mapping[str, Any]", raw or {})
    return ConstraintProvenance(
        requirement=(str(entry["requirement"]) if entry.get("requirement") is not None else None),
        assumed=bool(entry.get("assumed") or False),
        reason=(str(entry["reason"]) if entry.get("reason") is not None else None),
    )


def _weights(raw: Any) -> tuple[float, float] | None:
    if not isinstance(raw, dict):
        return None
    pair = cast("Mapping[str, Any]", raw)
    return (float(pair["mm"]), float(pair["deg"]))


def _box(raw: Any) -> dict[str, tuple[float | None, float | None]] | None:
    """The declared box (``SOLVER.md`` §4.2 step 4), or ``None`` for unbounded."""
    if not isinstance(raw, dict):
        return None
    out: dict[str, tuple[float | None, float | None]] = {}
    for name, bounds in cast("Mapping[str, Any]", raw).items():
        pair = cast("Sequence[Any]", bounds)
        out[str(name)] = (
            None if pair[0] is None else float(pair[0]),
            None if pair[1] is None else float(pair[1]),
        )
    return out


class SolveOps(CadOpsState):
    """The ``SOLVER.md`` §11 Stage 13A/13B/13C tools."""

    def solve_pose(self, arguments: Mapping[str, Any]) -> dict[str, JSONValue]:
        """Solve free joint parameters for the declared targets (``SOLVER.md`` §2A).

        Returns the **solve record** inline: the verdict, every returned
        assignment (all of them when the outcome is multiplicity, none marked
        chosen), the ``solver_core`` and ``verification`` blocks with their
        per-block determinism tier, and the independently re-measured
        residuals. It writes nothing — no proposal artifact, no pose
        declaration, no generation — so a caller that wants this assignment to
        become project state declares it, explicitly, through ``declare_pose``.
        """
        weights = _weights(arguments.get("weights"))
        provenance = _provenance(arguments.get("provenance"))
        free_raw = arguments.get("free_joints")
        request = PoseSolveRequest(
            targets=_targets(arguments.get("targets")),
            tol=float(arguments["tol"]),
            weighting=str(arguments["weighting"]),
            weights=weights,
            regularization=str(arguments["regularization"]),
            provenance=provenance,
            free_joints=(
                tuple(str(name) for name in cast("Sequence[Any]", free_raw))
                if isinstance(free_raw, list)
                else None
            ),
            starts=_starts(arguments.get("starts")),
            ceiling=(
                int(cast("int", arguments["ceiling"]))
                if arguments.get("ceiling") is not None
                else None
            ),
        )
        try:
            record = solve_pose(self.layout, self._store, request)
        except InvalidSolveRequest as exc:
            raise CadOpError("invalid_solve_request", exc.message, data=exc.to_json()) from exc
        except SolveUnresolvable as exc:  # pragma: no cover - defence in depth
            # ``unresolvable`` is verdict 6 and comes back INSIDE the record;
            # this catch exists so a future path that raises it past the engine
            # still names it rather than escaping as a transport error.
            raise CadOpError("unresolvable", exc.message, data=exc.to_json()) from exc
        except SolveRunRefusal as exc:
            # The refusal's own name, not a generic one: a ceiling, a timeout,
            # an undecidable rank and a solver/kernel disagreement call for four
            # different fixes, and collapsing them would be the conflation
            # SOLVER.md §6.3 exists to prevent.
            raise CadOpError(exc.reason, exc.message, data=exc.to_json()) from exc
        return {"status": "ok", **record.to_json()}

    def propose_placement(self, arguments: Mapping[str, Any]) -> dict[str, JSONValue]:
        """Propose placements for declared free parts or Params (``SOLVER.md`` §2B/§2C).

        ``space`` picks which: ``"transform"`` proposes a rigid transform per
        free part, ``"parameters"`` proposes a value per declared free
        ``Param``. It is an enum value on one tool rather than a fourth tool
        (§11's 8A/8B lever, the ``layout="nested_sheet"`` precedent), and the
        tool count is unchanged at 57.

        Returns the proposal's id and ref, the verdict, every returned
        placement (all of them when the outcome is multiplicity, none marked
        ``chosen``), and the ``solver_core`` / ``verification`` blocks with
        their per-block determinism tier — **D2 in both blocks** for a
        parameter solve, whose every iterate is a preview build. The proposal
        is a **measurement**:
        the ``AssemblyStatus`` row it was solved against keeps saying
        ``violated`` until a rebuilt script measures otherwise, no tool accepts
        this id where a constraint id is expected, and no path from here
        reaches a script, a parameter or a published artifact.
        """
        starts_raw = arguments.get("starts")
        request = PlacementSolveRequest(
            constraints=tuple(
                str(name) for name in cast("Sequence[Any]", arguments.get("constraints") or ())
            ),
            free=tuple(str(name) for name in cast("Sequence[Any]", arguments.get("free") or ())),
            ground=(
                tuple(str(name) for name in cast("Sequence[Any]", arguments["ground"]))
                if isinstance(arguments.get("ground"), list)
                else None
            ),
            tol=float(arguments["tol"]),
            weighting=str(arguments["weighting"]),
            weights=_weights(arguments.get("weights")),
            regularization=str(arguments["regularization"]),
            provenance=_provenance(arguments.get("provenance")),
            starts=_starts(starts_raw),
            box=_box(arguments.get("box")),
            ceiling=(
                int(cast("int", arguments["ceiling"]))
                if arguments.get("ceiling") is not None
                else None
            ),
            space=str(arguments.get("space") or "transform"),
            build_budget=(
                int(cast("int", arguments["build_budget"]))
                if arguments.get("build_budget") is not None
                else None
            ),
        )
        try:
            record = propose_placement(self.layout, self._store, request)
        except InvalidSolveRequest as exc:
            raise CadOpError("invalid_solve_request", exc.message, data=exc.to_json()) from exc
        except SolveUnresolvable as exc:  # pragma: no cover - verdict 6 rides the record
            raise CadOpError("unresolvable", exc.message, data=exc.to_json()) from exc
        except SolveRunRefusal as exc:
            raise CadOpError(exc.reason, exc.message, data=exc.to_json()) from exc
        return {"status": "ok", **record.to_json()}

    def read_proposals(
        self, ids: Sequence[str] | None = None, *, include_documents: bool = False
    ) -> dict[str, JSONValue]:
        """Read recorded proposals with their read-time staleness (``SOLVER.md`` §8).

        Reading never measures and never re-solves. ``stale`` is computed by
        comparing each proposal's **bound** artifact refs against the parts'
        current ones, so it is a fact about two generations rather than a
        stored projection — and it is never a refusal: a proposal whose inputs
        have moved stays readable, with ``changed_refs`` naming which parts
        moved so a reader knows what to re-run.

        Withdrawn proposals come back with their reasons, on the 8C read-tool
        shape: generational state is honest only if every generation stays
        readable.
        """
        from hephaestus.core.project_store.proposals import ProposalError
        from hephaestus.core.project_store.publication import Publisher

        proposals = ProposalSet(self.layout, self._store)
        state = proposals.state()
        publisher = Publisher(self.layout, self._store)

        def current(part: str) -> str | None:
            result = publisher.current_result(part)
            return None if result is None else result.artifact_ref

        try:
            views = proposal_views(state, current, ids=None if ids is None else list(ids))
        except ProposalError as exc:
            raise CadOpError(exc.reason, exc.message) from exc
        out: dict[str, JSONValue] = {
            "status": "ok",
            "generation": state.generation,
            "artifact_ref": state.artifact_ref,
            "proposals": cast("JSONValue", views),
        }
        if include_documents:
            out["documents"] = cast(
                "JSONValue",
                {
                    str(view["id"]): cast("JSONValue", dict(proposals.document(str(view["id"]))))
                    for view in views
                },
            )
        return out
