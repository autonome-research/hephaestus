"""Bridge run-admission policy: a thin layer over ``opstore.admission``.

The durable state machine (``ADMITTED → DISPATCHED → TERMINAL`` plus
``SUSPENDED_WAIT`` and terminal acknowledgment) lives in
:class:`opstore.admission.AdmissionControl`. This module supplies only the
*bridge policy* on top of it (architecture.md §5, DESIGN.md ``admission.py``):

* the slot count comes from ``schemas/bridge_limits.json`` (``admission.run_slots``
  = 16), never a duplicated literal — see :func:`bridge_store_config`;
* ``admit_run`` / ``dispatch`` wire a stable bridge run id into the durable row;
* terminal ingestion + acknowledgment are wired so a queued/running/
  completed-but-unacknowledged run all keep occupying a slot — the 17th admission
  raises the structured ``busy`` error (``opstore`` counts terminal-unacked rows
  as occupied);
* :meth:`startup_reconstruct` re-derives occupancy as the **union** (never the
  sum) of admitted-nonterminal and terminal-unacknowledged run ids.

The :class:`opstore.OpStore` (and therefore its ``state.db``) is owned by the
integration agent; construct it with :func:`bridge_store_config` so the 16-slot
budget is honoured, then hand its ``admission`` to :class:`BridgeAdmission`.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Final

from opstore.admission import (
    AdmissionControl,
    AdmissionRow,
    RecoveryResult,
    StartupReport,
    TerminalRecord,
)
from opstore.types import JSONValue, OwnerId, StoreConfig, TerminalState

from .limits import LIMITS

__all__ = [
    "BRIDGE_RUN_SLOTS",
    "BridgeAdmission",
    "bridge_store_config",
]

BRIDGE_RUN_SLOTS: Final[int] = int(LIMITS["admission"]["run_slots"])


def bridge_store_config(**overrides: object) -> StoreConfig:
    """A :class:`~opstore.types.StoreConfig` whose ``run_slots`` is the bridge's 16.

    The value is read from ``schemas/bridge_limits.json`` (``admission.run_slots``);
    no slot literal is duplicated in code. Any other ``StoreConfig`` field may be
    overridden by keyword for tests.
    """
    base = StoreConfig(run_slots=BRIDGE_RUN_SLOTS)
    if not overrides:
        return base
    valid = {f.name for f in dataclasses.fields(StoreConfig)}
    changes: dict[str, Any] = {k: v for k, v in overrides.items() if k in valid}
    return dataclasses.replace(base, **changes)


class BridgeAdmission:
    """Bridge policy over one :class:`~opstore.admission.AdmissionControl`.

    Every method delegates to the durable substrate; the value added here is the
    bridge vocabulary and the guarantee that ``admit_run`` fails closed with the
    structured ``busy`` error when all 16 slots (including completed-but-unacked
    runs) are occupied.
    """

    def __init__(self, admission: AdmissionControl) -> None:
        self._admission = admission

    @property
    def admission(self) -> AdmissionControl:
        """The wrapped durable admission controller (for atomic projections)."""
        return self._admission

    def admit_run(
        self,
        run_id: str,
        *,
        deadline_at: float | None = None,
        owner: OwnerId | None = None,
    ) -> AdmissionRow:
        """Durably admit a bridge run (idempotent on ``run_id``).

        Raises :class:`opstore.errors.BusyError` (code ``busy``) when no slot is
        free — this includes the case of 16 completed-but-unacknowledged runs.
        """
        return self._admission.admit(run_id, deadline_at=deadline_at, owner=owner)

    def dispatch(self, run_id: str, *, owner: OwnerId | None = None) -> AdmissionRow:
        """CAS ``ADMITTED → DISPATCHED`` for a bridge run (idempotent)."""
        return self._admission.dispatch(run_id, owner=owner)

    def ingest_terminal(
        self,
        run_id: str,
        terminal_id: str,
        state: TerminalState,
        data: JSONValue = None,
    ) -> TerminalRecord:
        """Record the run's unique terminal (idempotent; distinct second rejected)."""
        return self._admission.insert_terminal(run_id, terminal_id, state, data)

    def acknowledge(self, run_id: str, terminal_id: str) -> None:
        """Durably acknowledge the named terminal, releasing its slot."""
        self._admission.acknowledge_terminal(run_id, terminal_id)

    def capacity(self) -> int:
        """Slots a new admission could take right now (for ``py.admission_capacity``)."""
        return self._admission.available_slots()

    def active_count(self) -> int:
        """Occupied slots (terminal-unacked included, ``SUSPENDED_WAIT`` excluded)."""
        return self._admission.active_count()

    def occupancy(self) -> frozenset[str]:
        """Run ids occupying a slot: union of nonterminal and terminal-unacked ids."""
        return self._admission.occupied_run_ids()

    def get(self, run_id: str) -> AdmissionRow:
        """Current durable admission row (or ``NotFoundError``)."""
        return self._admission.get(run_id)

    def get_terminal(self, run_id: str) -> TerminalRecord | None:
        """The run's terminal record, if one was inserted."""
        return self._admission.get_terminal(run_id)

    def request_cancel(self, run_id: str) -> bool:
        """CAS to ``CANCEL_REQUESTED`` unless a terminal already won."""
        return self._admission.request_cancel(run_id)

    def startup_reconstruct(self) -> StartupReport:
        """Rebuild occupancy after restart as the union of the two unfinished sets."""
        return self._admission.startup_reconstruct()

    def recover(self, run_id: str) -> RecoveryResult:
        """Resolve a generic bridge run by the fixed recovery precedence."""
        return self._admission.recover(run_id)
