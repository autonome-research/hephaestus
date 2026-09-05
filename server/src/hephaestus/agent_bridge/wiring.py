# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""One owner for the :class:`~.dispatch.ToolDispatcher`'s capability set.

``ToolDispatcher`` takes its registry / delegation / snapshot capabilities as
optional injections that each fail *closed*: absent means the tools in that
family answer ``not_implemented`` or ``capability_not_available``. That is the
right shape for the dispatcher — it must never guess at a capability — but it
means the question "which capabilities does a shipped runtime have?" was
answered independently at four call sites, and all four answered "none"
(audit-2026-09-04-broken.md B-2: nine model-visible tools unwired in
``heph agent``, ``heph serve --web`` and ``heph mcp`` alike, while
``agent/session/profiles.ts`` instructs the model to call ``load_skill`` on its
first uncertainty).

So the answer is given **once**, here, and every shipped runtime calls
:func:`build_dispatcher`. A fifth runtime gets the capability set by
construction instead of by copying a constructor call that predates it.

Two capabilities are deliberately *not* decided here, because they need a live
sidecar rather than a project on disk: the ``query_snapshot`` vision child and
the delegation coordinator. Those arrive later through
:meth:`~.dispatch.ToolDispatcher.bind_runtime`, once ``Supervisor.start`` has
succeeded.

Failure policy: opening the registries can legitimately fail (a pinned tree that
no longer hashes to its pin — ``RegistrySet.open`` raises by design, and that
refusal is the whole point of pinning). A runtime must **not** die of it. The
registry is dropped, the reason is carried into the dispatcher, and the five
registry tools keep a typed refusal that names why.
"""

from __future__ import annotations

from dataclasses import dataclass

from hephaestus.core.errors import HephaestusError
from hephaestus.core.executor.sandbox.base import ExecBackend
from hephaestus.core.project_store.layout import ProjectLayout
from hephaestus.core.project_store.store import ProjectStore
from hephaestus.core.registry import RegistryOps, RegistrySet
from opstore.types import Clock

from opstore import OpStore

from .cad_ops import CadOps
from .delegation import DelegationService, Delivery, RejectionReason
from .dispatch import ToolDispatcher
from .session_edges import SessionEdgeStore

__all__ = [
    "PartExistsGate",
    "RegistryResolution",
    "build_dispatcher",
    "resolve_registry",
]


@dataclass(frozen=True, slots=True)
class RegistryResolution:
    """The project's registry tools, or the reason there are none."""

    ops: RegistryOps | None
    #: ``None`` when :attr:`ops` is present; otherwise a stable-token-prefixed
    #: sentence ("registry_integrity: …") suitable for a tool refusal message.
    unavailable: str | None


class PartExistsGate:
    """Pre-admission delegation policy: the named part must exist.

    :class:`~.delegation.DelegationService` defaults to a gate that never
    rejects — correct for a state machine that is unit-tested standalone, and
    dangerous the moment a shipped runtime constructs one, because
    ``delegate_part_agent("does_not_exist", …)`` would then be *admitted*: a
    child run id minted, an admission slot reserved, and a terminal reported for
    a part that was never there. ``RejectionReason.INVALID_PART`` exists for
    exactly this and had no producer.

    What this gate deliberately does **not** decide: ``part_busy`` /
    ``session_busy`` / ``queue_full`` are facts about live *sessions*, which the
    session service owns and this layer cannot see; ``no_run_slot`` is decided
    by admission itself inside :meth:`~.delegation.DelegationService.delegate`;
    and ``scope_denied`` is already enforced ahead of the state machine by
    :meth:`~.dispatch.ToolDispatcher._authorize` (delegation is orchestrator
    only). Answering those here from stale or absent knowledge would be a guess,
    and a guessed rejection is worse than none.
    """

    def __init__(self, project_store: ProjectStore) -> None:
        self._project = project_store

    def classify(self, parent_run_id: str, part: str, delivery: Delivery) -> RejectionReason | None:
        # Read the parts directory per call rather than caching: a part created
        # earlier in the same run (``create_part`` then delegate to it) is a
        # normal orchestrator sequence, and a cached listing would reject it.
        if part not in self._project.list_parts():
            return RejectionReason.INVALID_PART
        return None


def resolve_registry(
    layout: ProjectLayout, store: OpStore, *, backend: ExecBackend | None = None
) -> RegistryResolution:
    """Open the project's pinned registries; never raise.

    ``RegistrySet.open`` reads the ``[registries]`` pins from the manifest, falls
    back to the bundled trees, and verifies each Merkle digest — the same call
    ``heph registry`` and ``cad_ops/_dfm.py`` already make. It had simply never
    been made from an agent runtime.

    ``backend`` is the backend registry *generators* run under
    (``instance_store_part``). An **unsafe** backend is dropped rather than
    passed through: ``core/executor/sandbox/probe.py``'s ``refuse_unsafe``
    states that registry content may never run unsandboxed, and
    ``RegistryOps`` with ``backend=None`` reports ``capability_not_available``
    — an honest refusal instead of a sandbox escape. This is the single place
    that decision is made, so no runtime can reach it by a different route.
    """
    if backend is not None and getattr(backend, "unsafe", False):
        backend = None
    try:
        registries = RegistrySet.open(layout.root)
    except (HephaestusError, OSError) as exc:
        reason = getattr(exc, "reason", None)
        prefix = f"{reason}: " if isinstance(reason, str) else ""
        return RegistryResolution(None, f"{prefix}{exc}")
    return RegistryResolution(RegistryOps(registries, store, backend=backend), None)


def build_dispatcher(
    layout: ProjectLayout,
    store: OpStore,
    project_store: ProjectStore,
    cad: CadOps,
    *,
    backend: ExecBackend | None = None,
    edges: SessionEdgeStore | None = None,
    clock: Clock | None = None,
    delegation: bool = True,
) -> ToolDispatcher:
    """The dispatcher every shipped runtime uses, with its capabilities resolved.

    ``delegation=False`` is for a runtime with **no sidecar** (``heph mcp``):
    there is no process that could ever run a child part agent, so no delegation
    service is constructed and the family keeps its typed ``not_implemented``
    rather than admitting a delegation nothing will execute. That asymmetry is
    deliberate and is pinned by a test.

    The delegation service is built *without* a runner. With
    ``delegation_runner`` absent, ``ToolDispatcher._delegate`` synthesizes
    exactly one durable ``INTERRUPTED`` terminal instead of inventing a
    completion — a well-formed, discriminated outcome the model can read, and
    the safe intermediate state until ``py.*`` dispatch moves off the
    supervisor's single reader thread (``supervisor.py``: a ``py.*`` handler
    that issues ``Supervisor.call`` waits on a response only the thread it is
    blocking can deliver). A runtime that acquires a real coordinator binds it
    later through :meth:`~.dispatch.ToolDispatcher.bind_runtime`.
    """
    registry = resolve_registry(layout, store, backend=backend)
    service: DelegationService | None = None
    if delegation:
        service = DelegationService(
            store.admission,
            store.db,
            # A real gate, not the permissive default: see :class:`PartExistsGate`.
            gate=PartExistsGate(project_store),
            clock=clock,
            # INTERFACE.md §2.8: the parent/child edge is recorded at PREPARED
            # and nowhere else, so a runtime that delegates must hand the state
            # machine an edge store or the reopened thread reads `unlinked`.
            edges=edges if edges is not None else SessionEdgeStore(store.db),
        )
    return ToolDispatcher(
        project_store,
        cad=cad,
        registry=registry.ops,
        registry_unavailable=registry.unavailable,
        delegation=service,
    )
