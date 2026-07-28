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
    #: INGEST.md §1: ``{imports/ path: sha256}`` this build actually consumed.
    #: The import analogue of ``consumed``: only a part that imported a file
    #: goes stale when that file changes.
    imports: Mapping[str, str] = field(default_factory=dict[str, str])

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "part": self.part,
            "consumed": dict(self.consumed),
            "artifact_ref": self.artifact_ref,
            "audit_revision": self.audit_revision,
            "imports": {name: self.imports[name] for name in sorted(self.imports)},
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
        imports_raw = data.get("imports", {})
        if not isinstance(imports_raw, dict):
            raise ValidationError("part projection imports must be an object", kind="contract")
        imports: dict[str, str] = {}
        for name, value in imports_raw.items():
            if not isinstance(value, str):
                raise ValidationError("import hashes must be strings", kind="contract")
            imports[name] = value
        return cls(
            part=part,
            consumed=dict(consumed),
            artifact_ref=artifact,
            audit_revision=revision,
            imports=imports,
        )


@dataclass(frozen=True)
class ProjectionState:
    """The persisted projection state behind the ``project-state`` pointer."""

    audit_revision: int = 0
    hc_state: Mapping[str, JSONValue] = field(default_factory=dict[str, "JSONValue"])
    stale: Mapping[str, str] = field(default_factory=dict[str, str])
    projections: Mapping[str, PartProjection] = field(default_factory=dict[str, PartProjection])
    #: INGEST.md §1: the live ``{imports/ path: sha256}`` tree state, the import
    #: analogue of ``hc_state``.
    import_state: Mapping[str, str] = field(default_factory=dict[str, str])

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "audit_revision": self.audit_revision,
            "hc_state": dict(self.hc_state),
            "stale": dict(self.stale),
            "projections": {
                part: self.projections[part].to_json() for part in sorted(self.projections)
            },
            "import_state": {name: self.import_state[name] for name in sorted(self.import_state)},
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
        import_state_raw = data.get("import_state", {})
        if not isinstance(import_state_raw, dict):
            raise ValidationError("import_state must be an object", kind="contract")
        import_state: dict[str, str] = {}
        for name, value in import_state_raw.items():
            if not isinstance(value, str):
                raise ValidationError("import hashes must be strings", kind="contract")
            import_state[name] = value
        return cls(
            audit_revision=revision,
            hc_state=dict(hc_state),
            stale=stale_map,
            projections=projections,
            import_state=import_state,
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

    def apply_import_state(
        self,
        import_state: Mapping[str, str],
        *,
        reason: str = "imported file changed",
    ) -> StaleReport:
        """Advance the audit revision to a new live ``imports/`` tree state.

        The import twin of :meth:`apply_hc_state`, and deliberately the same
        shape: marks stale **exactly** the parts whose recorded imports differ
        under the new state (a file no part imported invalidates nobody; a part
        that imports nothing is never stale from here). Same lock order —
        project-config, then the affected part locks lexically.
        """
        self._locks.acquire(PROJECT_CONFIG_LOCK)
        try:
            state, pointer = self._load()
            changed: dict[str, tuple[str, ...]] = {}
            for part in sorted(state.projections):
                projection = state.projections[part]
                names = tuple(
                    sorted(
                        path
                        for path, digest in projection.imports.items()
                        if import_state.get(path) != digest
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
                    hc_state=dict(state.hc_state),
                    stale=stale,
                    projections=dict(state.projections),
                    import_state=dict(import_state),
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
        imports: Mapping[str, str] | None = None,
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
        recorded_imports = dict(imports or {})
        projections[part] = PartProjection(
            part=part,
            consumed=dict(consumed),
            artifact_ref=artifact_ref,
            audit_revision=state.audit_revision,
            imports=recorded_imports,
        )
        stale = {name: why for name, why in state.stale.items() if name != part}
        # The published build's import hashes ARE live at this point (publication
        # revalidated them under these locks), so folding them into the live
        # import state keeps a first-ever build from marking itself stale on the
        # next sync.
        import_state = dict(state.import_state)
        import_state.update(recorded_imports)
        new_state = ProjectionState(
            audit_revision=state.audit_revision,
            hc_state=dict(state.hc_state),
            stale=stale,
            projections=projections,
            import_state=import_state,
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
