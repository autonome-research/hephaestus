# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""The CAM.md §3 declared-state quartet families, as thin ops over the ledgers.

``declare_setup`` / ``update_setup`` / ``read_setups`` and the four sibling
families (stock, fixtures, WCS, operations). Everything these do lives one
layer down and is deliberately not reimplemented here:
:class:`~hephaestus.core.project_store.cam.CamState` owns the generational
state — validation, the compelled provenance, the declaration-time refusal
taxonomy (``invalid_*``, ``tag_prefix_*``, ``duplicate_feature_claim``,
``no_declared_tolerance``, ``budget_missing_rejects``,
``op_sample_bound_exceeded``), the CAS swap under the project-config lock and
the idempotent WAL write keyed on the invocation id.

**Declaring is model-writable, on purpose** (CAM.md §1.4): a setup
declaration is cheap, reversible, generational, and measured against geometry
the model did not choose. What the model cannot do is erase — ``update_*``
with ``withdrawn: true`` records a new generation carrying the reason — and
what NOTHING on this surface can do is cause a runnable program to reach the
filesystem: there is no emission tool, structurally, and ``check_program``
(14C) simulates and returns no program text.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from hephaestus.core.errors import AddressingError
from hephaestus.core.project_store.cam import CamError, CamLedger, CamLedgerState, CamState
from opstore.types import JSONValue

from ._base import CadOpError, CadOpsState

__all__ = ["CamOps"]


def _refusal(exc: CamError) -> CadOpError:
    """The ledger's stable refusal token, carried through unchanged."""
    return CadOpError(exc.reason, exc.message, data=exc.data)


def _clean(data: Mapping[str, Any]) -> dict[str, JSONValue]:
    """Drop ``null`` arguments so a schema default reads as "not supplied"."""
    out: dict[str, JSONValue] = {}
    for key, value in data.items():
        if value is None:
            continue
        if isinstance(value, dict):
            out[key] = cast("JSONValue", _clean(cast("Mapping[str, Any]", value)))
            continue
        out[key] = cast("JSONValue", value)
    return out


class CamOps(CadOpsState):
    """The fifteen CAM declared-state tools (CAM.md §3/§9, Stage 14B)."""

    # -- seams -------------------------------------------------------------

    def cam_state(self) -> CamState:
        """The project's five CAM ledgers (generational state, CAM.md §3)."""
        return CamState(self.layout, self._store)

    def _cam_ledger(self, kind: str) -> CamLedger:
        cam = self.cam_state()
        return {
            "setup": cam.setups,
            "stock": cam.stock,
            "fixture": cam.fixtures,
            "wcs": cam.wcs,
            "operation": cam.operations,
        }[kind]

    @staticmethod
    def _cam_result(state: CamLedgerState) -> dict[str, JSONValue]:
        return {"status": "ok", **state.to_json()}

    # -- the one shape all fifteen tools share ------------------------------

    def cam_declare(
        self, kind: str, entry: Mapping[str, Any], *, op_id: str
    ) -> dict[str, JSONValue]:
        """Declare one entry; advances one generation. Repeated ids are refused."""
        try:
            state = self._cam_ledger(kind).declare(_clean(entry), op_id=op_id)
        except CamError as exc:
            raise _refusal(exc) from exc
        return self._cam_result(state)

    def cam_update(
        self, kind: str, entry_id: str, patch: Mapping[str, Any], reason: str, *, op_id: str
    ) -> dict[str, JSONValue]:
        """Revise **or withdraw** one entry; one generation, nothing erased.

        ``patch = {"withdrawn": true}`` routes to the ledger's own withdrawal:
        "stop claiming this" is a different act from "the number was wrong",
        and both record their reason on the generation (the 8C rule).
        """
        cleaned = _clean(patch)
        withdrawn = cleaned.pop("withdrawn", None)
        ledger = self._cam_ledger(kind)
        try:
            if withdrawn is True:
                if cleaned:
                    raise CadOpError(
                        ledger.INVALID_REASON,
                        f"{kind} {entry_id}: a withdrawal patches nothing else — "
                        "withdraw first, then declare the replacement",
                    )
                state = ledger.withdraw(entry_id, reason, op_id=op_id)
            else:
                state = ledger.update(entry_id, cleaned, reason, op_id=op_id)
        except CamError as exc:
            raise _refusal(exc) from exc
        return self._cam_result(state)

    def cam_read(self, kind: str) -> dict[str, JSONValue]:
        """The current generation, withdrawn entries included with their reasons."""
        return self._cam_result(self._cam_ledger(kind).state())

    # -- check_program (CAM.md §5.9/§9, Stage 14C) ---------------------------

    def check_program(self, setup_ids: Sequence[str] | None = None) -> dict[str, JSONValue]:
        """Simulate and verify now (CAM.md §5): per-setup ``ProgramStatus``.

        The one measuring verb on the CAM surface, and it writes no file and
        returns no program text — the D2 mandate is structural here. A full
        run is recorded onto the program-status projection so a later read —
        and the reviewer — sees it; a named subset is evaluated but not
        projected (``partial: true``, the ``check_assembly``/``check_motion``
        rule). A removal-simulation ceiling kill is FILED in that setup's
        record as the named ``cam_sim_timeout`` refusal with the cheap facts
        present, never an empty-handed error.
        """
        from hephaestus.core.cam_check import check_program as engine_check

        registries = self.registries()
        with self._scratch("heph-cam-check-") as scratch:
            try:
                statuses, partial = engine_check(
                    self.layout,
                    self._store,
                    setup_ids,
                    tools=registries.tools,
                    materials=registries.materials,
                    scratch=Path(scratch),
                )
            except AddressingError as exc:
                raise CadOpError(
                    "unknown_setup",
                    f"{exc.message} (declared: {', '.join(exc.candidates) or 'none'})",
                ) from exc
        return {
            "status": "ok",
            "programs": [cast("JSONValue", status.to_json()) for status in statuses],
            "partial": partial,
        }
