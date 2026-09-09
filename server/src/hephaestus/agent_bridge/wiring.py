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
from typing import Protocol, runtime_checkable

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
    "LiveRunView",
    "PartExistsGate",
    "ProjectDelegationGate",
    "RegistryResolution",
    "build_dispatcher",
    "part_session_id",
    "resolve_registry",
]


@dataclass(frozen=True, slots=True)
class RegistryResolution:
    """The project's registry tools, or the reason there are none."""

    ops: RegistryOps | None
    #: ``None`` when :attr:`ops` is present; otherwise a stable-token-prefixed
    #: sentence ("registry_integrity: …") suitable for a tool refusal message.
    unavailable: str | None


@runtime_checkable
class LiveRunView(Protocol):
    """The live-turn facts the delegation gate needs, read from the runtime.

    Two reads, both side-effect free, which is what
    :class:`~.delegation.DelegationGate` requires. Injected rather than reached
    for: the gate is built by :func:`build_dispatcher`, which runs before any
    sidecar exists, while the answers only exist once one does.
    """

    def session_for_run(self, run_id: str) -> str | None:
        """The session a live (or recently bound) run belongs to."""
        ...

    def live_sessions(self) -> frozenset[str]:
        """Session ids with a turn in flight right now."""
        ...


def part_session_id(part: str) -> str:
    """The conventional per-part session id (mirrors ``dispatch._part_session_id``)."""
    return f"part:{part}"


class ProjectDelegationGate:
    """Pre-admission delegation policy, decided from the project and live runs.

    :class:`~.delegation.DelegationService` used to DEFAULT to a gate that never
    rejects — correct for a state machine that is unit-tested standalone, and
    dangerous the moment a shipped runtime constructs one, because
    ``delegate_part_agent("does_not_exist", …)`` was then *admitted*: a child run
    id minted, an admission slot reserved, and a terminal reported for a part
    that was never there. ``RejectionReason.INVALID_PART`` existed for exactly
    this and had no producer (audit-2026-09-04 J-agent-wiring-6). Both halves of
    that item are closed: this class is the producer, and the permissive default
    is gone — ``gate`` is a required argument and the allow-everything gate lives
    in ``hephaestus.testing.delegation_gates``, so a runtime that forgets one
    does not compile rather than silently admitting everything.

    Three of the declared reasons are produced here, all from reads:

    * ``invalid_part`` — the name is not a legal part identifier (a traversal
      attempt, an empty string, an uppercase name) or names no part in this
      project. Resolved through the project layout's own validator and the
      store's listing, so the delegation refuses exactly what ``read_part``
      refuses rather than by a second, weaker rule.
    * ``part_busy`` — that part's own session already has a turn in flight.
      Delegating anyway would put two interleaved turns on one transcript,
      which the per-session admission guard exists to prevent
      (``app.py._admit_turn``), and the refusal there would arrive *after* a
      child run had been minted.
    * ``scope_denied`` — self-delegation: the parent run is already running on
      the very session this delegation would prompt. INTERFACE.md's delegation
      clause is about handing work to *another* session.

    What this gate still does **not** decide, and why: ``no_run_slot`` is
    decided by admission itself inside
    :meth:`~.delegation.DelegationService.delegate`; ``queue_full`` describes a
    prompt queue that does not exist (J-http-limits-10 removed its limit);
    ``prompt_too_large`` is enforced by the state machine's own byte check. And
    ``session_busy`` — a session held by a *foreign* live owner — has no
    observable producer on this runtime: the per-session lease layer it belongs
    to was superseded in production by a coarser process-level record, so the
    only ownership this process can see is its own, which ``part_busy`` already
    covers. Answering it from absent knowledge would be a guess, and a guessed
    rejection is worse than none.

    ``live`` is optional so the three non-sidecar runtimes (``heph mcp``, the
    CLI's project-only construction) keep the part-existence check without
    claiming knowledge of live turns they do not have.
    """

    def __init__(self, project_store: ProjectStore, *, live: LiveRunView | None = None) -> None:
        self._project = project_store
        self._live = live

    def classify(self, parent_run_id: str, part: str, delivery: Delivery) -> RejectionReason | None:
        # Read the parts directory per call rather than caching: a part created
        # earlier in the same run (``create_part`` then delegate to it) is a
        # normal orchestrator sequence, and a cached listing would reject it.
        try:
            self._project.layout.part_path(part)
        except HephaestusError:
            return RejectionReason.INVALID_PART
        if part not in self._project.list_parts():
            return RejectionReason.INVALID_PART
        live = self._live
        if live is None:
            return None
        child_session = part_session_id(part)
        if live.session_for_run(parent_run_id) == child_session:
            return RejectionReason.SCOPE_DENIED
        if child_session in live.live_sessions():
            return RejectionReason.PART_BUSY
        return None


#: Superseded name kept as an alias: the gate grew two reasons and a live-run
#: view, and renaming it without one would break the shipped-wiring assertions
#: that name it. New code should use :class:`ProjectDelegationGate`.
PartExistsGate = ProjectDelegationGate


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
    live_runs: LiveRunView | None = None,
) -> ToolDispatcher:
    """The dispatcher every shipped runtime uses, with its capabilities resolved.

    ``delegation=False`` is for a runtime with **no sidecar** (``heph mcp``):
    there is no process that could ever run a child part agent, so no delegation
    service is constructed and the family keeps its typed ``not_implemented``
    rather than admitting a delegation nothing will execute. That asymmetry is
    deliberate and is pinned by a test.

    The delegation service is built *without* a runner, because a runner needs a
    live sidecar and this function runs before one exists. With
    ``delegation_runner`` absent, ``ToolDispatcher._delegate`` synthesizes
    exactly one durable ``INTERRUPTED`` terminal instead of inventing a
    completion — a well-formed, discriminated outcome the model can read, and
    the right answer for a runtime that will never have a child process
    (``heph mcp``). :class:`~.app.BridgeRuntime` binds a real one through
    :meth:`~.dispatch.ToolDispatcher.bind_runtime` the moment its sidecar is up
    (audit-2026-09-04 J-agent-wiring-6); that became possible when ``py.*``
    dispatch moved off the supervisor's single reader thread onto a bounded
    worker pool (J-agent-wiring-13), since a runner prompts the child over the
    same bridge the delegation request arrived on.

    ``live_runs`` is the runtime's view of turns in flight, handed to the
    delegation gate so it can refuse ``part_busy`` and self-delegation. Absent
    on a runtime with no sessions, where the gate keeps the part-existence check
    alone rather than claiming knowledge it does not have.
    """
    registry = resolve_registry(layout, store, backend=backend)
    service: DelegationService | None = None
    if delegation:
        service = DelegationService(
            store.admission,
            store.db,
            # Required since J-agent-wiring-6 — there is no permissive
            # default any more, so this argument cannot be forgotten by a
            # future call site: see :class:`ProjectDelegationGate`.
            gate=ProjectDelegationGate(project_store, live=live_runs),
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
