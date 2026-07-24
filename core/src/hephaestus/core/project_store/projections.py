"""Dependency projections, audit revisions, and coherent project snapshots.

Architecture §3.5: every project/global change increments an **audit
revision** and recomputes dependency projections. A part's projection is the
exact set of ``hc`` names it read plus their canonical values (produced by
the executor's read-tracking ``hc`` namespace). Only parts whose consumed
names/values actually changed become stale — an edit to an unconsumed name
invalidates nobody.

A **coherent project-snapshot manifest** atomically maps every addressed part
to a successful artifact whose consumed-``hc`` projection matches the current
live projection; unchanged parts may contribute artifacts from an older audit
revision. Manifests are content-addressed blobs whose live pointer is
compare-and-swapped (opstore pointer CAS) while the project-config lock
holds. An incoherent request is the structured
``incoherent_project_snapshot`` rejection with per-part stale/missing/
mismatch details.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, cast

from hephaestus.core.errors import IncoherentProjectSnapshotError, ValidationError
from hephaestus.core.project_store.locks import PROJECT_CONFIG_LOCK, LockManager, part_lock
from hephaestus.core.project_store.store import blob_hash_of_ref
from opstore.types import JSONValue

from opstore import OpStore, canonical_json

__all__ = [
    "PROJECT_SNAPSHOT_REF_PREFIX",
    "SNAPSHOT_POINTER",
    "STATE_POINTER",
    "PartProjection",
    "ProjectSnapshot",
    "ProjectionState",
    "Projections",
    "SnapshotIssue",
    "SnapshotRejectedError",
    "StaleReport",
]

#: CAS pointer holding the current projection-state blob.
STATE_POINTER = "project-state"
#: CAS pointer holding the current coherent project-snapshot manifest blob.
SNAPSHOT_POINTER = "project-snapshot"
#: Ref prefix for immutable project-snapshot manifests.
PROJECT_SNAPSHOT_REF_PREFIX = "artifact:project-snapshot:"


def _same_value(a: JSONValue, b: JSONValue) -> bool:
    """Canonical-JSON equality (keeps ``5`` and ``5.0`` distinct, like hashing)."""
    return canonical_json(a) == canonical_json(b)


@dataclass(frozen=True)
class PartProjection:
    """One part's recorded consumed-``hc`` projection + its successful artifact."""

    part: str
    consumed: Mapping[str, JSONValue]
    artifact_ref: str
    audit_revision: int

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "part": self.part,
            "consumed": dict(self.consumed),
            "artifact_ref": self.artifact_ref,
            "audit_revision": self.audit_revision,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, JSONValue]) -> PartProjection:
        part = data.get("part")
        artifact = data.get("artifact_ref")
        revision = data.get("audit_revision")
        consumed = data.get("consumed")
        if (
            not isinstance(part, str)
            or not isinstance(artifact, str)
            or not isinstance(revision, int)
            or isinstance(revision, bool)
            or not isinstance(consumed, dict)
        ):
            raise ValidationError("malformed part projection record", kind="contract")
        return cls(
            part=part,
            consumed=dict(consumed),
            artifact_ref=artifact,
            audit_revision=revision,
        )


@dataclass(frozen=True)
class ProjectionState:
    """The persisted projection state behind the ``project-state`` pointer."""

    audit_revision: int = 0
    hc_state: Mapping[str, JSONValue] = field(default_factory=dict[str, "JSONValue"])
    stale: Mapping[str, str] = field(default_factory=dict[str, str])
    projections: Mapping[str, PartProjection] = field(default_factory=dict[str, PartProjection])

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "audit_revision": self.audit_revision,
            "hc_state": dict(self.hc_state),
            "stale": dict(self.stale),
            "projections": {
                part: self.projections[part].to_json() for part in sorted(self.projections)
            },
        }

    @classmethod
    def from_json(cls, data: Mapping[str, JSONValue]) -> ProjectionState:
        revision = data.get("audit_revision")
        hc_state = data.get("hc_state")
        stale = data.get("stale")
        projections_raw = data.get("projections")
        if (
            not isinstance(revision, int)
            or isinstance(revision, bool)
            or not isinstance(hc_state, dict)
            or not isinstance(stale, dict)
            or not isinstance(projections_raw, dict)
        ):
            raise ValidationError("malformed projection state record", kind="contract")
        stale_map: dict[str, str] = {}
        for part, reason in stale.items():
            if not isinstance(reason, str):
                raise ValidationError("stale reasons must be strings", kind="contract")
            stale_map[part] = reason
        projections: dict[str, PartProjection] = {}
        for part, raw in projections_raw.items():
            if not isinstance(raw, dict):
                raise ValidationError("part projections must be objects", kind="contract")
            projections[part] = PartProjection.from_json(raw)
        return cls(
            audit_revision=revision,
            hc_state=dict(hc_state),
            stale=stale_map,
            projections=projections,
        )


@dataclass(frozen=True)
class StaleReport:
    """Outcome of one audit-revision advance."""

    audit_revision: int
    stale: tuple[str, ...]  # parts newly marked stale, lexical order
    changed: Mapping[str, tuple[str, ...]]  # part -> consumed names that changed


SnapshotIssueKind = Literal["missing", "stale", "mismatch"]


@dataclass(frozen=True)
class SnapshotIssue:
    """One reason a project snapshot request is incoherent."""

    part: str
    kind: SnapshotIssueKind
    detail: str
    names: tuple[str, ...] = ()

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "part": self.part,
            "kind": self.kind,
            "detail": self.detail,
            "names": list(self.names),
        }


class SnapshotRejectedError(IncoherentProjectSnapshotError):
    """``incoherent_project_snapshot`` with structured per-part issues."""

    def __init__(self, message: str, *, issues: tuple[SnapshotIssue, ...]) -> None:
        super().__init__(message)
        self.issues = issues


@dataclass(frozen=True)
class ProjectSnapshot:
    """A published coherent manifest: its immutable ref plus decoded content."""

    ref: str
    manifest: Mapping[str, JSONValue]


class Projections:
    """Audit revisions, selective staleness, and snapshot assembly over opstore."""

    def __init__(self, store: OpStore, *, locks: LockManager) -> None:
        self._store = store
        self._locks = locks

    # -- persisted state ----------------------------------------------------

    def _load(self) -> tuple[ProjectionState, str | None]:
        pointer = self._store.blobs.read_pointer(STATE_POINTER)
        if pointer is None:
            return ProjectionState(), None
        raw = json.loads(self._store.blobs.get(pointer).decode("utf-8"))
        return ProjectionState.from_json(cast("Mapping[str, JSONValue]", raw)), pointer

    def _swap(self, new_state: ProjectionState, expected_pointer: str | None) -> str:
        blob = self._store.blobs.put(canonical_json(new_state.to_json()).encode("utf-8"))
        self._store.blobs.cas_swap(STATE_POINTER, expected_pointer, blob)
        return blob

    def state(self) -> ProjectionState:
        """The current projection state (lock-free read)."""
        state, _ = self._load()
        return state

    # -- audit revisions + selective staleness ------------------------------

    def apply_hc_state(
        self,
        hc_state: Mapping[str, JSONValue],
        *,
        reason: str = "project constants changed",
    ) -> StaleReport:
        """Advance the audit revision to a new live ``hc`` projection.

        Marks stale **exactly** the parts whose recorded consumed names/values
        differ under the new state; unconsumed changes invalidate nobody.
        Holds the project-config lock, then the affected part locks in lexical
        order while stale markers change (architecture §3.5 write order).
        """
        self._locks.acquire(PROJECT_CONFIG_LOCK)
        try:
            state, pointer = self._load()
            changed: dict[str, tuple[str, ...]] = {}
            for part in sorted(state.projections):
                projection = state.projections[part]
                names = tuple(
                    sorted(
                        name
                        for name, value in projection.consumed.items()
                        if name not in hc_state or not _same_value(hc_state[name], value)
                    )
                )
                if names:
                    changed[part] = names
            stale = dict(state.stale)
            part_refs = [part_lock(part) for part in sorted(changed)]
            for ref in part_refs:
                self._locks.acquire(ref)
            try:
                for part, names in changed.items():
                    stale[part] = f"{reason}: {', '.join(names)}"
                new_state = ProjectionState(
                    audit_revision=state.audit_revision + 1,
                    hc_state=dict(hc_state),
                    stale=stale,
                    projections=dict(state.projections),
                )
                self._swap(new_state, pointer)
            finally:
                for ref in reversed(part_refs):
                    self._locks.release(ref)
            return StaleReport(
                audit_revision=new_state.audit_revision,
                stale=tuple(sorted(changed)),
                changed=changed,
            )
        finally:
            self._locks.release(PROJECT_CONFIG_LOCK)

    def record_current(
        self,
        part: str,
        *,
        consumed: Mapping[str, JSONValue],
        artifact_ref: str,
    ) -> ProjectionState:
        """Record a successful current publication's projection; clears its stale.

        Publication-only: the caller **must already hold** the project-config
        and the part's lock (enforced by assertion) — this is the one path
        allowed to clear a stale marker.
        """
        if not self._locks.holds(PROJECT_CONFIG_LOCK) or not self._locks.holds(part_lock(part)):
            raise AssertionError(
                "record_current requires the project-config and part locks to be held"
            )
        state, pointer = self._load()
        projections = dict(state.projections)
        projections[part] = PartProjection(
            part=part,
            consumed=dict(consumed),
            artifact_ref=artifact_ref,
            audit_revision=state.audit_revision,
        )
        stale = {name: why for name, why in state.stale.items() if name != part}
        new_state = ProjectionState(
            audit_revision=state.audit_revision,
            hc_state=dict(state.hc_state),
            stale=stale,
            projections=projections,
        )
        self._swap(new_state, pointer)
        return new_state

    # -- coherent snapshot manifests ----------------------------------------

    def assemble_snapshot(self, parts: Sequence[str]) -> ProjectSnapshot:
        """Assemble and publish a coherent manifest over ``parts``.

        Every addressed part must map to a successful artifact whose consumed
        projection matches the live values (an older audit revision is fine
        when projection-valid). Otherwise raises the structured
        ``incoherent_project_snapshot`` rejection. Publication is a pointer
        CAS of the content-addressed manifest under the project-config lock.
        """
        already_held = self._locks.holds(PROJECT_CONFIG_LOCK)
        if not already_held:
            self._locks.acquire(PROJECT_CONFIG_LOCK)
        try:
            return self._assemble_locked(parts)
        finally:
            if not already_held:
                self._locks.release(PROJECT_CONFIG_LOCK)

    def _assemble_locked(self, parts: Sequence[str]) -> ProjectSnapshot:
        state, _ = self._load()
        issues: list[SnapshotIssue] = []
        for part in sorted(parts):
            projection = state.projections.get(part)
            if projection is None:
                issues.append(
                    SnapshotIssue(
                        part=part,
                        kind="missing",
                        detail="no successful artifact projection recorded",
                    )
                )
                continue
            if part in state.stale:
                issues.append(SnapshotIssue(part=part, kind="stale", detail=state.stale[part]))
                continue
            mismatched = tuple(
                sorted(
                    name
                    for name, value in projection.consumed.items()
                    if name not in state.hc_state or not _same_value(state.hc_state[name], value)
                )
            )
            if mismatched:
                issues.append(
                    SnapshotIssue(
                        part=part,
                        kind="mismatch",
                        detail="consumed-hc projection no longer matches live values",
                        names=mismatched,
                    )
                )
        if issues:
            detail = canonical_json([issue.to_json() for issue in issues])
            raise SnapshotRejectedError(
                f"project snapshot is incoherent: {detail}", issues=tuple(issues)
            )
        manifest: JSONValue = {
            "version": 1,
            "audit_revision": state.audit_revision,
            "parts": {
                part: {
                    "artifact_ref": state.projections[part].artifact_ref,
                    "audit_revision": state.projections[part].audit_revision,
                    "consumed": dict(state.projections[part].consumed),
                }
                for part in sorted(parts)
            },
        }
        blob = self._store.blobs.put(canonical_json(manifest).encode("utf-8"))
        expected = self._store.blobs.read_pointer(SNAPSHOT_POINTER)
        if expected != blob:
            self._store.blobs.cas_swap(SNAPSHOT_POINTER, expected, blob)
        for part in sorted(parts):
            self._store.gc.link(blob, blob_hash_of_ref(state.projections[part].artifact_ref))
        return ProjectSnapshot(
            ref=PROJECT_SNAPSHOT_REF_PREFIX + blob,
            manifest=cast("Mapping[str, JSONValue]", manifest),
        )
