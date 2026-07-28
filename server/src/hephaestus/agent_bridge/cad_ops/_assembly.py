"""The ``ASSEMBLY.md`` §3 constraint quartet, as thin ops over the engine layer.

``declare_constraint`` / ``update_constraint`` / ``read_constraints`` /
``check_assembly``. Everything these do lives one layer down and is deliberately
not reimplemented here:

* :class:`~hephaestus.core.project_store.constraints.ConstraintSet` owns the
  generational state — validation, the compelled provenance, the CAS swap under
  the project-config lock, and the idempotent WAL write keyed on the invocation
  id (``ASSEMBLY.md`` §1, the requirement ledger's pattern);
* :class:`~hephaestus.core.assembly.AssemblyEvaluator` owns anchor resolution
  against the parts' current build artifacts, the residuals, and the
  ``satisfied | violated | unresolvable`` naming (§2).

What this module adds is exactly the tool surface: argument shapes, the two
stable refusal tokens (``invalid_constraint`` / ``unknown_constraint``), and the
one result projection all four tools share.

**Declaring is model-writable, on purpose** (§3). Unlike the reference registry —
where registration is operator-only because a reference is evidence the model
cannot manufacture — a constraint is cheap, reversible and *checked*: what a
model declares is measured against geometry it did not get to choose, so a
dishonest constraint fails loudly rather than passing quietly. What the model
cannot do is erase: ``update_constraint`` with ``withdrawn: true`` records a new
generation carrying the reason, and every earlier generation stays readable.

**Reading never measures.** ``read_constraints`` reports the LAST evaluation
(``assembly: null`` when there has never been one — which is not a pass), and
``check_assembly`` is the only thing that measures. Keeping them apart is what
lets a status carry honest staleness: a projected status that a rebuild has since
invalidated says so, instead of being silently recomputed under the reader.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

from hephaestus.core.assembly import AssemblyEvaluator, AssemblyStatus
from hephaestus.core.errors import AddressingError
from hephaestus.core.project_store.constraints import (
    ConstraintError,
    ConstraintSet,
    ConstraintState,
)
from opstore.types import JSONValue

from ._base import CadOpError, CadOpsState

__all__ = ["AssemblyOps"]


def _refusal(exc: ConstraintError) -> CadOpError:
    """The engine's stable refusal token, carried through unchanged.

    ``ConstraintError.reason`` is already the machine token the tool contract
    documents (``invalid_constraint`` / ``unknown_constraint``), so the tool layer
    forwards it rather than re-deciding what a refusal means.
    """
    return CadOpError(exc.reason, exc.message)


def _clean(data: Mapping[str, Any]) -> dict[str, JSONValue]:
    """Drop ``null`` arguments so a schema default reads as "not supplied".

    The generated schemas give every optional field ``default: null``, and a
    caller (or the MCP/REST path) may send them explicitly. A ``null`` tolerance
    is not a tolerance of zero and not a malformed entry — it is an absent field,
    and the validators below must see it as one.
    """
    out: dict[str, JSONValue] = {}
    for key, value in data.items():
        if value is None:
            continue
        if isinstance(value, dict):
            nested = _clean(cast("Mapping[str, Any]", value))
            out[key] = cast("JSONValue", nested)
            continue
        out[key] = cast("JSONValue", value)
    return out


class AssemblyOps(CadOpsState):
    """The four constraint tools (``ASSEMBLY.md`` §3)."""

    # -- seams -------------------------------------------------------------

    def constraint_set(self) -> ConstraintSet:
        """The project's constraint set (generational state, §1)."""
        return ConstraintSet(self.layout, self._store)

    def assembly_evaluator(self) -> AssemblyEvaluator:
        """The engine evaluator (§2) — also what the §5 reviewer reads."""
        return AssemblyEvaluator(self.layout, self._store)

    def assembly_status(self) -> AssemblyStatus | None:
        """The last projected status, or ``None`` for *never evaluated*.

        ``None`` is not "nothing to check": the §5 reviewer treats an unevaluated
        constraint set exactly as it treats an unchecked constraint.
        """
        return self.assembly_evaluator().projected()

    # -- writes ------------------------------------------------------------

    def declare_constraint(self, entry: Mapping[str, Any], *, op_id: str) -> dict[str, JSONValue]:
        """Declare one constraint; advances one generation.

        A repeated id is refused rather than replaced: revising a claim is
        ``update_constraint``, which records why.
        """
        try:
            state = self.constraint_set().declare(_clean(entry), op_id=op_id)
        except ConstraintError as exc:
            raise _refusal(exc) from exc
        return self._set_result(state)

    def update_constraint(
        self, constraint_id: str, patch: Mapping[str, Any], reason: str, *, op_id: str
    ) -> dict[str, JSONValue]:
        """Revise **or withdraw** one constraint; advances one generation.

        ``patch = {"withdrawn": true}`` is the withdrawal path of ``ASSEMBLY.md``
        §3 — one act with one recorded reason, routed to the set's own withdrawal
        so a withdrawn entry stops being evaluated while staying stored. It is not
        expressible as an ordinary field patch, because "stop claiming this" is a
        different act from "the tolerance was wrong".
        """
        cleaned = _clean(patch)
        withdrawn = cleaned.pop("withdrawn", None)
        constraints = self.constraint_set()
        try:
            if withdrawn is True:
                if cleaned:
                    raise CadOpError(
                        "invalid_constraint",
                        f"constraint {constraint_id}: a withdrawal records only its reason — "
                        f"patch also carries {sorted(cleaned)}; withdraw it, then declare the "
                        "replacement, so the two acts stay separately readable",
                    )
                state = constraints.withdraw(constraint_id, reason, op_id=op_id)
            else:
                state = constraints.update(constraint_id, cleaned, reason, op_id=op_id)
        except ConstraintError as exc:
            raise _refusal(exc) from exc
        return self._set_result(state)

    # -- reads -------------------------------------------------------------

    def read_constraints(self) -> dict[str, JSONValue]:
        """The current generation plus the latest evaluation (nothing measured)."""
        return self._set_result(self.constraint_set().state())

    def check_assembly(self, ids: Sequence[str] | None = None) -> dict[str, JSONValue]:
        """Evaluate now (``ASSEMBLY.md`` §2) and return the ``AssemblyStatus``.

        A full evaluation is recorded and projected, so a later read — and the §5
        reviewer — sees it. A named subset is evaluated but deliberately not
        projected, and says so with ``partial: true``.
        """
        evaluator = self.assembly_evaluator()
        try:
            status = evaluator.evaluate(ids)
        except AddressingError as exc:
            # An unknown id is the constraint-set half of the same refusal a bad
            # patch gets; reporting it as a part-addressing failure would name the
            # wrong namespace.
            raise CadOpError(
                "unknown_constraint",
                f"{exc.message} (declared: {', '.join(exc.candidates) or 'none'})",
            ) from exc
        partial = ids is not None
        return {
            "status": "ok",
            "assembly": cast("JSONValue", status.to_json()),
            "artifact_ref": None if partial else evaluator.projected_ref(),
            "partial": partial,
        }

    # -- the shared projection ---------------------------------------------

    def _set_result(self, state: ConstraintState) -> dict[str, JSONValue]:
        """The result all three constraint-set tools share.

        The evaluation rides along as *evidence already taken*: the projection is
        read, never computed, so a write cannot quietly become a measurement and
        a reader can see that the last status predates the entry it is looking at.
        """
        evaluator = self.assembly_evaluator()
        status = evaluator.projected()
        return {
            "status": "ok",
            "generation": state.generation,
            "artifact_ref": state.artifact_ref,
            "change": None if state.change is None else cast("JSONValue", state.change.to_json()),
            "entries": [cast("JSONValue", entry.to_json()) for entry in state.entries],
            "assembly": None if status is None else cast("JSONValue", status.to_json()),
            "assembly_ref": evaluator.projected_ref(),
        }
