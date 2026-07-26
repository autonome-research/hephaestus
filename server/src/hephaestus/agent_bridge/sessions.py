"""Session service: profile assignment, single-writer leases, quick-edit seeding.

Architecture §4.2/§4.4, digest §2/§4. Each persistent Pi session (one per part,
one project orchestrator, plus scoped quick-edit children) is guarded by a
**leased, heartbeat-backed** single-writer lock under ``.heph/locks/`` — modelled
on the opstore :class:`~opstore.leases.LeaseManager` exclusive lease keyed by
``session:<id>``. A second process that tries to open the same session must route
through the owner or fail with the structured ``session_busy`` error; a lease is
reclaimed **only after** an owner-liveness check (opstore reclaims a dead owner's
TTL-elapsed lease on the conflicting acquisition, and never a live one).

Quick-edit children (§4.4) are spawned with bounded, *artifact-bound* context:
the selection reference is validated through Stage 1 bundle resolution (bundle /
pass layer / GLTF whose immutable metadata links the bundle only) — RGB, unlinked
GLTF, and mismatched refs are rejected and never fall back to current geometry;
an expired/mismatched selection yields ``stale_selection``. Selection resolution
itself is Stage 1 machinery, injected here as :class:`SelectionResolver` so the
spawn/seeding logic is unit-testable; the resolver returns the artifact-bound
source, resolved provenance, and the crop centered on the selected topology.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from opstore.errors import LeaseHeldError
from opstore.leases import Lease, LeaseManager
from opstore.types import Clock, OwnerId, SystemClock

__all__ = [
    "QuickEditContext",
    "QuickEditRequest",
    "ResolvedSelection",
    "SelectionResolver",
    "SessionBusyError",
    "SessionLease",
    "SessionProfile",
    "SessionService",
    "StaleSelectionError",
    "profile_for",
    "session_ref",
]


class SessionProfile(enum.StrEnum):
    """The session profiles (arch §4.1/§4.2/§4.4, VALIDATION.md §5)."""

    PART = "part"
    ORCHESTRATOR = "orchestrator"
    QUICK_EDIT = "quick_edit"
    QUERY_SNAPSHOT = "query_snapshot"
    #: The independent termination reviewer: ephemeral, read-only, own budget.
    REVIEWER = "reviewer"


@dataclass(frozen=True, slots=True)
class ProfileSpec:
    """Static capabilities of a session profile.

    ``tools_profile`` names the generated tool-availability profile the sidecar's
    registry uses (``orchestrator`` gets delegation + project-check + globals
    tools; ``part``/``quick_edit`` are single-part scoped; ``query_snapshot`` gets
    an **empty** allowlist; ``reviewer`` gets the read-only measurement/render
    subset). ``persistent`` marks whether the Pi JSONL is kept.
    """

    profile: SessionProfile
    tools_profile: str | None
    persistent: bool
    can_delegate: bool


_SPECS: dict[SessionProfile, ProfileSpec] = {
    SessionProfile.ORCHESTRATOR: ProfileSpec(
        SessionProfile.ORCHESTRATOR, "orchestrator", persistent=True, can_delegate=True
    ),
    SessionProfile.PART: ProfileSpec(
        SessionProfile.PART, "part", persistent=True, can_delegate=False
    ),
    SessionProfile.QUICK_EDIT: ProfileSpec(
        SessionProfile.QUICK_EDIT, "quick_edit", persistent=True, can_delegate=False
    ),
    SessionProfile.QUERY_SNAPSHOT: ProfileSpec(
        SessionProfile.QUERY_SNAPSHOT, None, persistent=False, can_delegate=False
    ),
    SessionProfile.REVIEWER: ProfileSpec(
        SessionProfile.REVIEWER, "reviewer", persistent=False, can_delegate=False
    ),
}


def profile_for(profile: SessionProfile) -> ProfileSpec:
    """The static :class:`ProfileSpec` for a profile."""
    return _SPECS[profile]


def session_ref(session_id: str) -> str:
    """The opstore lease ref for a session's single-writer lock."""
    return f"session:{session_id}"


class SessionBusyError(Exception):
    """The session is held by a live foreign owner. ``code = 'session_busy'``."""

    code = "session_busy"

    def __init__(self, session_id: str) -> None:
        super().__init__(f"session {session_id} is owned by another live process")
        self.session_id = session_id


class StaleSelectionError(Exception):
    """A quick-edit selection ref is expired or does not resolve. ``code``."""

    code = "stale_selection"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True, slots=True)
class SessionLease:
    """A held session lease plus its assigned profile."""

    session_id: str
    profile: SessionProfile
    lease: Lease

    @property
    def lease_id(self) -> str:
        return self.lease.lease_id


@dataclass(frozen=True, slots=True)
class QuickEditRequest:
    """Client request to spawn a quick-edit child (arch §4.4)."""

    part: str
    build_artifact_ref: str
    selection_artifact_ref: str
    selection_id: str


@dataclass(frozen=True, slots=True)
class ResolvedSelection:
    """Stage-1 resolution of a quick-edit selection: artifact-bound context."""

    part: str
    source: str
    provenance: str
    crop_artifact_ref: str


@dataclass(frozen=True, slots=True)
class QuickEditContext:
    """Seeded context for a spawned quick-edit child session."""

    session_id: str
    part: str
    source: str
    provenance: str
    crop_artifact_ref: str
    parent_session_id: str


@runtime_checkable
class SelectionResolver(Protocol):
    """Stage-1 selection resolution (injected; the real impl lives in core).

    Must follow immutable pass/GLTF links and validate bundle association, the
    exact source build, the id kind/table entry, and the layer before returning
    provenance/crop. RGB refs, unlinked GLTF, and unrelated mask refs must raise
    :class:`StaleSelectionError`; it must never fall back to current geometry.
    """

    def resolve(self, request: QuickEditRequest) -> ResolvedSelection: ...


class SessionService:
    """Leased single-writer session registry over one opstore ``LeaseManager``."""

    def __init__(self, leases: LeaseManager, *, clock: Clock | None = None) -> None:
        self._leases = leases
        self._clock = clock or SystemClock()

    def acquire(
        self,
        session_id: str,
        profile: SessionProfile,
        owner: OwnerId,
        ttl_s: float,
    ) -> SessionLease:
        """Acquire the single-writer lease for ``session_id`` and assign ``profile``.

        A conflicting **live** owner raises :class:`SessionBusyError`; a dead
        owner's TTL-elapsed lease is reclaimed automatically by this acquisition.
        """
        try:
            lease = self._leases.acquire_exclusive(session_ref(session_id), owner, ttl_s)
        except LeaseHeldError as exc:
            raise SessionBusyError(session_id) from exc
        return SessionLease(session_id=session_id, profile=profile, lease=lease)

    def heartbeat(self, session: SessionLease) -> SessionLease:
        """Extend the session lease's TTL window."""
        lease = self._leases.heartbeat(session.lease_id)
        return SessionLease(session.session_id, session.profile, lease)

    def release(self, session: SessionLease) -> bool:
        """Release the session lease; ``False`` if already gone."""
        return self._leases.release(session.lease_id)

    def owner(self, session_id: str) -> OwnerId | None:
        """The live owner of ``session_id``'s lease, if any."""
        live = self._leases.live_holders(session_ref(session_id))
        return live[0].owner if live else None

    def spawn_quick_edit(
        self,
        request: QuickEditRequest,
        resolver: SelectionResolver,
        *,
        parent_session_id: str,
        child_session_id: str,
        owner: OwnerId,
        ttl_s: float,
    ) -> tuple[SessionLease, QuickEditContext]:
        """Validate the selection, then spawn a scoped quick-edit child session.

        Resolution runs first (``stale_selection`` propagates before any lease is
        taken); the child is bound to the single part with no orchestrator tools
        and threaded to its parent part session.
        """
        resolved = resolver.resolve(request)
        if resolved.part != request.part:
            raise StaleSelectionError(
                f"resolved part {resolved.part!r} != requested {request.part!r}"
            )
        session = self.acquire(child_session_id, SessionProfile.QUICK_EDIT, owner, ttl_s)
        context = QuickEditContext(
            session_id=child_session_id,
            part=resolved.part,
            source=resolved.source,
            provenance=resolved.provenance,
            crop_artifact_ref=resolved.crop_artifact_ref,
            parent_session_id=parent_session_id,
        )
        return session, context
