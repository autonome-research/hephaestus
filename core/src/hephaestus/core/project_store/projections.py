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
from dataclasses import dataclass, field, replace
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
    "AssemblyProjection",
    "MotionProjection",
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


def _restale_assembly(
    assembly: AssemblyProjection | None, part: str, artifact_ref: str
) -> AssemblyProjection | None:
    """Mark the assembly projection stale when a constrained part's build moves.

    ``ASSEMBLY.md`` §2: rebuilding any part a constraint anchors marks the
    assembly projection stale. Only the anchored parts matter (a constraint set
    that never mentions a part is not invalidated by building it), and only a
    *different* artifact ref counts — the same selectivity ``apply_hc_state``
    applies to consumed names.
    """
    if assembly is None or part not in assembly.parts:
        return assembly
    if assembly.parts[part] == artifact_ref or part in assembly.stale:
        return assembly
    return replace(assembly, stale=tuple(sorted({*assembly.stale, part})))


def _restale_motion(
    motion: MotionProjection | None, part: str, artifact_ref: str
) -> MotionProjection | None:
    """Mark the motion projection stale when a jointed part's build moves.

    ``KINEMATICS.md`` §2, stated as the ``AssemblyProjection`` precedent and
    implemented as it: rebuilding any part in the joint forest marks the motion
    projection stale. Only the forest's parts matter (a joint set that never
    mentions a part is not invalidated by building it), and only a *different*
    artifact ref counts — the same selectivity ``apply_hc_state`` applies to
    consumed names.
    """
    if motion is None or part not in motion.parts:
        return motion
    if motion.parts[part] == artifact_ref or part in motion.stale:
        return motion
    return replace(motion, stale=tuple(sorted({*motion.stale, part})))


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
class AssemblyProjection:
    """The last evaluated assembly status, and what it was computed against.

    ``ASSEMBLY.md`` §2: constraint status is recomputed on demand and PROJECTED
    at publication, so a status a reader sees is either fresh or **named
    stale** — never quietly out of date. ``parts`` records the artifact ref each
    anchored part contributed at evaluation time (``""`` when the part had no
    current build then, which is itself a fact the next build invalidates), and
    :attr:`stale` names every anchored part whose current build has moved since.

    Staleness here is the same rule ``hc``/import staleness follows: a *changed*
    input, not merely a rebuild — republishing byte-identical geometry moves no
    artifact ref and therefore invalidates nothing.
    """

    status_blob: str
    generation: int
    audit_revision: int
    parts: Mapping[str, str] = field(default_factory=dict[str, str])
    stale: tuple[str, ...] = ()

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "status_blob": self.status_blob,
            "generation": self.generation,
            "audit_revision": self.audit_revision,
            "parts": {name: self.parts[name] for name in sorted(self.parts)},
            "stale": list(self.stale),
        }

    @classmethod
    def from_json(cls, data: Mapping[str, JSONValue]) -> AssemblyProjection:
        status_blob = data.get("status_blob")
        generation = data.get("generation")
        revision = data.get("audit_revision")
        if (
            not isinstance(status_blob, str)
            or not isinstance(generation, int)
            or isinstance(generation, bool)
            or not isinstance(revision, int)
            or isinstance(revision, bool)
        ):
            raise ValidationError("malformed assembly projection record", kind="contract")
        parts_raw = data.get("parts", {})
        if not isinstance(parts_raw, dict):
            raise ValidationError("assembly projection parts must be an object", kind="contract")
        parts: dict[str, str] = {}
        for name, value in cast("Mapping[str, JSONValue]", parts_raw).items():
            if not isinstance(value, str):
                raise ValidationError("assembly projection refs must be strings", kind="contract")
            parts[name] = value
        stale_raw = data.get("stale", [])
        stale: tuple[str, ...] = ()
        if isinstance(stale_raw, list):
            stale = tuple(
                item for item in cast("list[JSONValue]", stale_raw) if isinstance(item, str)
            )
        return cls(
            status_blob=status_blob,
            generation=generation,
            audit_revision=revision,
            parts=parts,
            stale=stale,
        )


@dataclass(frozen=True)
class MotionProjection:
    """The last evaluated motion status, and what it was computed against.

    ``KINEMATICS.md`` §2: motion status (joint and pose outcomes) is recomputed
    on demand and PROJECTED at publication — the same *rule* as ``hc``/import/
    assembly staleness, implemented as its own projection on the
    :class:`AssemblyProjection` precedent, field for field. ``parts`` records
    the artifact ref each joint-forest part contributed at evaluation time
    (``""`` when the part had no current build then, which is itself a fact the
    next build invalidates); :attr:`stale` names every forest part whose
    current build has moved since, so a stale status never reads as fresh —
    and, via the GC edge :meth:`Projections._swap` records, never as "never
    evaluated" either. Two generations rather than one because a
    ``MotionStatus`` is measured against both sets at once (§2).

    Stage 9B rides the SAME projection rather than growing a second one
    (``KINEMATICS.md`` §7 names the motion projection field as the one piece
    of non-ledger persistence Stage 9 adds): :attr:`results_blob` points at
    the last full motion-check evaluation's sweep-results document (§4) and
    :attr:`check_generation` records which motion-check generation it was
    measured against, both ``None``/``0`` before checks were ever evaluated —
    which is *never evaluated*, not a pass. The check anchors' parts join
    :attr:`parts`, so rebuilding a part only a sweep measures restales the
    results exactly like rebuilding a forest part restales the status.
    """

    status_blob: str
    joint_generation: int
    pose_generation: int
    audit_revision: int
    parts: Mapping[str, str] = field(default_factory=dict[str, str])
    stale: tuple[str, ...] = ()
    results_blob: str | None = None
    check_generation: int = 0

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "status_blob": self.status_blob,
            "joint_generation": self.joint_generation,
            "pose_generation": self.pose_generation,
            "audit_revision": self.audit_revision,
            "parts": {name: self.parts[name] for name in sorted(self.parts)},
            "stale": list(self.stale),
            "results_blob": self.results_blob,
            "check_generation": self.check_generation,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, JSONValue]) -> MotionProjection:
        status_blob = data.get("status_blob")
        joint_generation = data.get("joint_generation")
        pose_generation = data.get("pose_generation")
        revision = data.get("audit_revision")
        if (
            not isinstance(status_blob, str)
            or not isinstance(joint_generation, int)
            or isinstance(joint_generation, bool)
            or not isinstance(pose_generation, int)
            or isinstance(pose_generation, bool)
            or not isinstance(revision, int)
            or isinstance(revision, bool)
        ):
            raise ValidationError("malformed motion projection record", kind="contract")
        parts_raw = data.get("parts", {})
        if not isinstance(parts_raw, dict):
            raise ValidationError("motion projection parts must be an object", kind="contract")
        parts: dict[str, str] = {}
        for name, value in cast("Mapping[str, JSONValue]", parts_raw).items():
            if not isinstance(value, str):
                raise ValidationError("motion projection refs must be strings", kind="contract")
            parts[name] = value
        stale_raw = data.get("stale", [])
        stale: tuple[str, ...] = ()
        if isinstance(stale_raw, list):
            stale = tuple(
                item for item in cast("list[JSONValue]", stale_raw) if isinstance(item, str)
            )
        results_blob = data.get("results_blob")
        if results_blob is not None and not isinstance(results_blob, str):
            raise ValidationError(
                "motion projection results_blob must be a string", kind="contract"
            )
        check_generation = data.get("check_generation", 0)
        if not isinstance(check_generation, int) or isinstance(check_generation, bool):
            raise ValidationError(
                "motion projection check_generation must be an integer", kind="contract"
            )
        return cls(
            status_blob=status_blob,
            joint_generation=joint_generation,
            pose_generation=pose_generation,
            audit_revision=revision,
            parts=parts,
            stale=stale,
            results_blob=results_blob,
            check_generation=check_generation,
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
    #: ASSEMBLY.md §2: the projected assembly status, or ``None`` before the
    #: first evaluation (an unevaluated constraint set is not a passing one).
    assembly: AssemblyProjection | None = None
    #: KINEMATICS.md §2: the projected motion status, or ``None`` before the
    #: first evaluation (an unevaluated joint set is not a resolved one).
    motion: MotionProjection | None = None

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "audit_revision": self.audit_revision,
            "hc_state": dict(self.hc_state),
            "stale": dict(self.stale),
            "projections": {
                part: self.projections[part].to_json() for part in sorted(self.projections)
            },
            "import_state": {name: self.import_state[name] for name in sorted(self.import_state)},
            "assembly": None if self.assembly is None else self.assembly.to_json(),
            "motion": None if self.motion is None else self.motion.to_json(),
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
        assembly_raw = data.get("assembly")
        assembly: AssemblyProjection | None = None
        if isinstance(assembly_raw, dict):
            assembly = AssemblyProjection.from_json(cast("Mapping[str, JSONValue]", assembly_raw))
        # Tolerant of pre-Stage-9 records (like ``import_state`` above, and like
        # ``BuildResult.metadata`` before it): a state blob written before the
        # motion field existed simply has no motion projection yet.
        motion_raw = data.get("motion")
        motion: MotionProjection | None = None
        if isinstance(motion_raw, dict):
            motion = MotionProjection.from_json(cast("Mapping[str, JSONValue]", motion_raw))
        return cls(
            audit_revision=revision,
            hc_state=dict(hc_state),
            stale=stale_map,
            projections=projections,
            import_state=import_state,
            assembly=assembly,
            motion=motion,
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
        # ASSEMBLY.md §2: the projected status document hangs off the
        # projection-state blob, which is the protected GC root. The edge has to
        # be re-recorded on EVERY swap, not only on record_assembly: the pointer
        # moves to a new blob on each rebuild, and an edge left behind on the
        # previous one would leave the status the project still points at
        # unreachable — collected at the retention horizon, after which a stale
        # status reads as "never evaluated", which is a different (and false)
        # claim about the project.
        if new_state.assembly is not None:
            self._store.gc.link(blob, new_state.assembly.status_blob)
        # KINEMATICS.md §2: the motion status blob rides the same edge for the
        # same reason as the assembly edge above — a stale status that got
        # collected would read as "never evaluated", a different (and false)
        # claim about the project.
        if new_state.motion is not None:
            self._store.gc.link(blob, new_state.motion.status_blob)
            # KINEMATICS.md §4 (Stage 9B): the sweep-results document is
            # evidence exactly like the status document, and a collected one
            # would read as "checks never evaluated" — the same false claim.
            if new_state.motion.results_blob is not None:
                self._store.gc.link(blob, new_state.motion.results_blob)
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
                    # Carried, not recomputed: an ``hc`` change is not an
                    # imports/ change and not an assembly or motion
                    # evaluation, and dropping any of them here would silently
                    # reset live state that this call knows nothing about.
                    import_state=dict(state.import_state),
                    assembly=state.assembly,
                    motion=state.motion,
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
                    assembly=state.assembly,
                    motion=state.motion,
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
            assembly=_restale_assembly(state.assembly, part, artifact_ref),
            motion=_restale_motion(state.motion, part, artifact_ref),
        )
        self._swap(new_state, pointer)
        return new_state

    def record_assembly(self, projection: AssemblyProjection) -> ProjectionState:
        """Project one evaluated assembly status (``ASSEMBLY.md`` §2).

        Replaces any previous projection: the status a project carries is the
        last one actually computed, and it starts life fresh (``stale=()``)
        because it was just measured against the refs it records. Publication
        marks it stale again when a part it anchors is rebuilt into different
        geometry. Takes the project-config lock, like every other state swap.
        """
        already_held = self._locks.holds(PROJECT_CONFIG_LOCK)
        if not already_held:
            self._locks.acquire(PROJECT_CONFIG_LOCK)
        try:
            state, pointer = self._load()
            new_state = ProjectionState(
                audit_revision=state.audit_revision,
                hc_state=dict(state.hc_state),
                stale=dict(state.stale),
                projections=dict(state.projections),
                import_state=dict(state.import_state),
                assembly=projection,
                motion=state.motion,
            )
            # ``_swap`` records the status document's reachability edge (it has
            # to do so on every swap, not just this one) — see its comment.
            self._swap(new_state, pointer)
            return new_state
        finally:
            if not already_held:
                self._locks.release(PROJECT_CONFIG_LOCK)

    def record_motion(self, projection: MotionProjection) -> ProjectionState:
        """Project one evaluated motion status (``KINEMATICS.md`` §2).

        The motion twin of :meth:`record_assembly`, deliberately the same
        shape: replaces any previous projection (the status a project carries
        is the last one actually computed), starts life fresh (``stale=()``)
        because it was just measured against the refs it records, and is
        marked stale again by publication when a joint-forest part is rebuilt
        into different geometry. Takes the project-config lock, like every
        other state swap.
        """
        already_held = self._locks.holds(PROJECT_CONFIG_LOCK)
        if not already_held:
            self._locks.acquire(PROJECT_CONFIG_LOCK)
        try:
            state, pointer = self._load()
            new_state = ProjectionState(
                audit_revision=state.audit_revision,
                hc_state=dict(state.hc_state),
                stale=dict(state.stale),
                projections=dict(state.projections),
                import_state=dict(state.import_state),
                assembly=state.assembly,
                motion=projection,
            )
            # ``_swap`` records the status document's reachability edge — see
            # its comment at the assembly edge; the motion edge shares it.
            self._swap(new_state, pointer)
            return new_state
        finally:
            if not already_held:
                self._locks.release(PROJECT_CONFIG_LOCK)

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
