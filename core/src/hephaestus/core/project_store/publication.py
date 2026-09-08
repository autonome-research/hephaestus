"""Typed build/check/synthetic-export publication over opstore (arch §3.5).

Build publication: freeze inputs under project-config + part locks, run the
build lock-free, then reacquire the same locks and **revalidate**
script/part-param/toolchain/consumed-``hc`` hashes before compare-and-swapping
the part's current pointer at an already-installed content-addressed bundle
(opstore WAL ``publish`` discipline — PREPARED row, pointer CAS, COMMITTED —
so crash recovery at any boundary reaches one deterministic outcome and
retries replay). Failed builds, transient-parameter previews (7-day retention
class), and raced builds publish their checkpoint/evidence blobs but are
**never current and never clear stale state**.

Synthetic exports exercise the export WAL path: authorize an immutable stored
source artifact, install the output file through the file WAL, and persist a
GC-root pin plus a provenance link to the source build.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Final, Literal, cast

from hephaestus.core.errors import ConflictError, ValidationError
from hephaestus.core.executor.fingerprint import (
    FingerprintBaseline,
    descriptors_from_json,
    descriptors_to_json,
)
from hephaestus.core.executor.imports import (
    ImportPayload,
    ImportResolutionError,
    static_import_declarations,
)
from hephaestus.core.executor.runner import UnpublishedBuild
from hephaestus.core.hashing import consumed_hc_hash, toolchain_hash
from hephaestus.core.project_store.artifact_kinds import (
    record_artifact_kind,
    record_artifact_refs,
)
from hephaestus.core.project_store.layout import ProjectLayout
from hephaestus.core.project_store.locks import PROJECT_CONFIG_LOCK, LockManager, part_lock
from hephaestus.core.project_store.projections import Projections, StaleReport
from hephaestus.core.project_store.retention import last_failure_pointer
from hephaestus.core.project_store.store import (
    ProjectStore,
    SourceSnapshot,
    blob_hash_of_ref,
)
from hephaestus.core.project_store.store import (
    artifact_ref as make_artifact_ref,
)
from hephaestus.core.types import BuildFreshness, BuildInput, BuildResult, InputHashes
from opstore.gc import PREVIEW_RETENTION_CLASS
from opstore.types import JSONValue, OwnerId

from opstore import (
    ConflictedError,
    Fresh,
    OpStore,
    PendingRecovery,
    Replay,
    canonical_json,
    sha256_bytes,
    sha256_canonical_json,
)

__all__ = [
    "BUILD_BUNDLE_ARTIFACT_KIND",
    "BUILD_BUNDLE_POINTER_PREFIX",
    "BUILD_BUNDLE_REF_PREFIX",
    "CURRENT_POINTER_PREFIX",
    "EXPORT_ARTIFACT_KIND",
    "EXPORT_REF_PREFIX",
    "ExportOutcome",
    "FrozenBuildInputs",
    "InputMismatch",
    "PublicationKind",
    "PublicationOutcome",
    "Publisher",
    "build_bundle",
    "build_bundle_pointer",
    "current_pointer",
    "input_mismatches",
]

#: CAS pointer prefix for per-part current-build bundles.
CURRENT_POINTER_PREFIX = "part-current:"
#: Artifact kind of a build bundle document.
BUILD_BUNDLE_ARTIFACT_KIND: Final[str] = "build-bundle"
#: Ref prefix naming one build's bundle document immutably.
BUILD_BUNDLE_REF_PREFIX = f"artifact:{BUILD_BUNDLE_ARTIFACT_KIND}:"
#: CAS pointer prefix for the bundle of ONE published build, keyed by part and
#: by the artifact blob it describes (audit-2026-09-04 B-1). The current pointer
#: answers "what is this part's namespace now"; this answers "what namespace did
#: THIS artifact publish", which is what a historical or preview ``artifact_ref``
#: needs and what ``measure`` had no way to ask.
BUILD_BUNDLE_POINTER_PREFIX = "build-bundle:"
#: The artifact kind every published export carries. Named rather than spelled
#: inline at each site, because §19.24 makes it a value the *store* records and
#: three places (here, ``cad_ops/_exports.py``, ``http/artifacts.py``) have to
#: mean the same four letters by it.
EXPORT_ARTIFACT_KIND: Final[str] = "export"
#: Ref prefix for published exports.
EXPORT_REF_PREFIX = f"artifact:{EXPORT_ARTIFACT_KIND}:"

SOURCE_MAP_REF_PREFIX = "artifact:source-map:"

PublicationKind = Literal["current", "preview", "failed", "raced"]


def build_bundle(build: UnpublishedBuild, published: BuildResult, audit_revision: int) -> JSONValue:
    """The bundle document publication records ABOUT one build.

    Extracted from the current-pointer flip at 13C because a **preview** build
    needs the same document and never got one: ``publish_build(preview=True)``
    stores the §8 ``BuildResult`` and returns, so a preview carried no §7
    geometry index — and ``SOLVER.md`` §2C measures candidates on exactly those
    previews (``core/assembly.py``'s ``PublishedBuild``). Without this, a
    parameter-space anchor resolved to nothing and the solve reported
    ``unaddressable_anchor`` for a tag the build had certainly placed.

    One definition rather than two: a second, preview-shaped bundle would be a
    second answer to "which selectors does this artifact admit", and the whole
    point of recording the index is that anchor resolution happens long after
    the worker that knew the labels has exited.
    """
    return {
        "kind": "build_bundle",
        "part": published.part,
        "result": published.to_json(),
        "artifact_ref": published.artifact_ref,
        "tag_fingerprints": descriptors_to_json(build.tag_fingerprints),
        # ASSEMBLY.md §2: the §7 namespace this build published. Recorded
        # beside the fingerprints because both answer the same question
        # about a *reloaded* artifact — which selectors it admits — that the
        # BRep bytes themselves cannot: constraint anchors are resolved
        # against a build long after the worker that knew its labels
        # and tags has exited.
        "geometry_index": dict(build.geometry_index_json or {}),
        "consumed_hc": dict(build.consumed_hc),
        # MESH_INGEST.md §1.4 / §12 item 15: the SECOND hash, recorded
        # beside the first rather than in place of it.
        # ``result.input_hashes.imports`` is the raw file bytes and stays
        # the invalidation key; this is geometry identity, and it is what
        # lets two builds of one part say "the file changed, the geometry
        # did not" instead of leaving a reader to guess from a moved input
        # hash. It is an explanatory fact and never an invalidation key —
        # reversing that would let a normalizer decide what counts as a
        # changed build, which is the authority INGEST.md §1 keeps in the
        # raw bytes.
        "mesh_canonical_hashes": _mesh_hashes(build),
        # MESH_INGEST.md §4.3: surfaced, never blocking. A reviewer must SEE
        # that a part's geometry came out of a scan; this spec adds no new
        # never-green rule for it.
        "geometry_source": _geometry_source(build),
        "audit_revision": audit_revision,
    }


def current_pointer(part: str) -> str:
    """The CAS pointer name holding ``part``'s current bundle blob hash."""
    return CURRENT_POINTER_PREFIX + part


def build_bundle_pointer(part: str, artifact_blob: str) -> str:
    """The CAS pointer holding the bundle of one published build.

    Keyed by **part and artifact blob**, not by the artifact alone. An artifact
    ref is content-addressed over the BRep bytes only, so two parts whose
    geometry happens to be identical share one artifact ref while their §7
    namespaces differ (one labels its box ``lid``, the other ``base``). An
    artifact-only key would hand the second part's selectors the first part's
    namespace — a silent wrong answer, which is the one outcome §7 forbids
    outright. Every caller already knows the part it is measuring, so the
    stronger key costs nothing.
    """
    return f"{BUILD_BUNDLE_POINTER_PREFIX}{part}:{artifact_blob}"


def _mesh_hashes(build: UnpublishedBuild) -> dict[str, JSONValue]:
    """``{staged key: mesh_canonical_hash}`` the worker reported, or ``{}``.

    Keyed by (path, declared unit) rather than by path, because two units over
    one file are two canonical geometries (``MESH_INGEST.md`` §1.5.1) and a
    path-keyed record would report one of them as if it were both. Absent from
    every build that imported no mesh, and from every record written before this
    stage — an empty map is the honest reading of "this build imported none".
    """
    raw = build.worker_result.get("mesh_canonical_hashes")
    if not isinstance(raw, dict):
        return {}
    return {str(key): value for key, value in cast("dict[str, JSONValue]", raw).items()}


#: ``MESH_INGEST.md`` §4.3's closed two-member set, declared where the bundle is
#: written so a third value cannot arrive by typo.
GEOMETRY_SOURCES: Final[tuple[str, ...]] = ("authored", "mesh_derived")


def _geometry_source(build: UnpublishedBuild) -> str:
    """``"authored"`` or ``"mesh_derived"`` for this build (``MESH_INGEST.md`` §4.3).

    Defaults to ``"authored"``, which is both the safe reading and the true one:
    a worker result with no such key came from a build that never called
    ``mesh_to_solid``. Importing a mesh and measuring against it is still
    authored — the scan was measurement data, not geometry — so this flips only
    where scan surface actually entered the part.
    """
    raw = build.worker_result.get("geometry_source")
    return raw if isinstance(raw, str) and raw in GEOMETRY_SOURCES else "authored"


@dataclass(frozen=True)
class InputMismatch:
    """One §8 build input whose live value no longer matches the recorded hash."""

    #: Which input moved — one of :data:`hephaestus.core.types.BuildInput`'s
    #: five names. A per-file import mismatch reports ``"imports"``: the closed
    #: vocabulary is what a chip and a context block can render, and the file
    #: that moved is named in :attr:`detail`.
    input: BuildInput
    #: The frozen-versus-live sentence publication records on a raced outcome.
    detail: str


def input_mismatches(
    expected: InputHashes,
    *,
    live_script: str | None,
    live_toolchain: str,
    live_part_params: str | None,
    live_imports: Mapping[str, str | None],
    consumed_hc: Mapping[str, JSONValue],
    live_hc: Mapping[str, JSONValue],
    compare_part_params: bool = True,
) -> tuple[InputMismatch, ...]:
    """Compare one build's recorded ``input_hashes`` against live values.

    The single comparison behind **both** halves of "are these still the inputs
    this build was computed from" — :meth:`Publisher._revalidate`, which asks it
    under locks before the current-pointer flip, and :meth:`Publisher.freshness`,
    which asks it on a lock-free read so a route can serve the answer
    (audit-2026-09-04 B-5). Extracting it is what keeps the read from being a
    *second* definition of staleness that agrees with publication today and
    drifts tomorrow.

    Pure: every live value is supplied by the caller, because the two callers
    read them from different places (a frozen ``UnpublishedBuild`` versus the
    published bundle) and because a function that read the filesystem itself
    could not be the shared one.

    ``compare_part_params=False`` drops the ``part_params`` leg for a caller
    that has no ``PARAMS`` declaration in hand — a read has none, and needs
    none, since the declaration is parsed out of the script and a changed
    declaration is therefore already a changed script. With the leg compared,
    ``live_part_params=None`` keeps publication's own reading: a build carrying
    no declaration is malformed and is refused as a mismatch rather than passed.

    ``live_imports`` maps each recorded import path to its live hash, ``None``
    for one that has become unreadable. Only paths the build recorded are
    compared — a new file in ``imports/`` that this build never read is not a
    changed input to it (``INGEST.md`` §1).
    """
    mismatches: list[InputMismatch] = []
    if live_script != expected.script:
        mismatches.append(
            InputMismatch("script", f"script: frozen {expected.script}, live {live_script}")
        )
    if live_toolchain != expected.toolchain:
        mismatches.append(
            InputMismatch(
                "toolchain", f"toolchain: frozen {expected.toolchain}, live {live_toolchain}"
            )
        )
    if compare_part_params:
        if live_part_params is None:
            mismatches.append(
                InputMismatch("part_params", "part_params: build carries no params declaration")
            )
        elif live_part_params != expected.part_params:
            mismatches.append(
                InputMismatch(
                    "part_params",
                    f"part_params: frozen {expected.part_params}, live {live_part_params}",
                )
            )
    # INGEST.md §1: a changed import file is a changed input. Revalidation
    # compares the live bytes against the frozen hashes, so a build that
    # raced a replaced STEP file can never flip the current pointer.
    for path, frozen in sorted(expected.imports.items()):
        live_import = live_imports.get(path)
        if live_import != frozen:
            mismatches.append(
                InputMismatch(
                    "imports",
                    f"imports[{path}]: frozen {frozen}, live {live_import or 'unreadable'}",
                )
            )
    missing = sorted(name for name in consumed_hc if name not in live_hc)
    if missing:
        mismatches.append(
            InputMismatch(
                "hc_dependencies",
                f"hc_dependencies: consumed names no longer defined: {', '.join(missing)}",
            )
        )
    else:
        live_projection = {name: live_hc[name] for name in consumed_hc}
        live_hash = consumed_hc_hash(live_projection)
        if live_hash != expected.hc_dependencies:
            mismatches.append(
                InputMismatch(
                    "hc_dependencies",
                    f"hc_dependencies: frozen {expected.hc_dependencies}, live {live_hash}",
                )
            )
    return tuple(mismatches)


@dataclass(frozen=True)
class FrozenBuildInputs:
    """Immutable inputs captured under locks before geometry computation."""

    part: str
    script: str
    script_hash: str
    script_snapshot_ref: str
    globals_source: str | None
    globals_snapshot_ref: str | None
    manifest_params: Mapping[str, int | float]
    #: INGEST.md §1: the frozen bytes of every ``imports/`` file the script
    #: declares, keyed by the path as written. Frozen exactly like the script
    #: text so a lost-response retry replays the original content. Since Stage
    #: 12 the value is an :class:`ImportPayload` rather than bare bytes, because
    #: the declared kind and unit have to reach the staging code — a declared
    #: unit that stops at the AST is a declared unit the geometry never sees
    #: (``MESH_INGEST.md`` §1.1).
    imports: Mapping[str, ImportPayload] = field(default_factory=dict[str, "ImportPayload"])
    #: Declared imports the resolver refused, path -> named refusal. Carried
    #: rather than raised: the build reports it at the ``import_step``
    #: statement with the full §8 error record.
    import_errors: Mapping[str, str] = field(default_factory=dict[str, str])
    #: ``{path: artifact:import:sha256:…}`` for each frozen import.
    import_refs: Mapping[str, str] = field(default_factory=dict[str, str])


@dataclass(frozen=True)
class PublicationOutcome:
    """Result of one build publication attempt."""

    kind: PublicationKind
    part: str
    result: BuildResult
    artifact_ref: str | None
    record_blob: str  # blob hash of the published bundle / evidence record
    evidence_refs: tuple[str, ...]
    details: tuple[str, ...] = ()
    replayed: bool = False


@dataclass(frozen=True)
class ExportOutcome:
    """Result of one synthetic-export publication."""

    name: str
    path: Path
    export_ref: str
    blob_hash: str
    source_artifact_ref: str
    pinned: bool
    replayed: bool = False


def _with_worker_facts(build: UnpublishedBuild) -> UnpublishedBuild:
    """Carry two facts the worker computed onto the §8 record before it is stored.

    RC-6, audit-2026-09-04 J-cli-startup-9 and -7. The worker has always
    emitted both ``check_names`` (the ``CHECKS`` names it registered) and
    ``params_declaration`` (the evaluated ``PARAMS`` bounds), and
    ``assemble_build`` keeps only the *hash* of the second and drops the first
    entirely — so an empty ``checks`` map was ambiguous between "this part
    declares no checks" and "it declares some that failed to register", and no
    reader could answer "what are this part's bounds?" without a multi-second
    sandboxed rebuild of a build that had already computed them.

    Applied here, at publication, rather than in the assembler: publication is
    what makes a record durable, and therefore what decides what a durable
    record says. Fields the record already carries are left exactly as they are.
    """
    result = build.result
    raw_names = build.worker_result.get("check_names")
    if not result.check_names and isinstance(raw_names, list):
        names = tuple(
            sorted(item for item in cast("list[JSONValue]", raw_names) if isinstance(item, str))
        )
        result = replace(result, check_names=names)
    raw_decl = build.worker_result.get("params_declaration")
    if not result.params_declaration and isinstance(raw_decl, dict):
        # Rebuilt through `BuildResult.from_json`'s own reader so the record and
        # the reader agree by construction; a malformed entry refuses here, at
        # publication, rather than at every later read.
        declaration = BuildResult.from_json(
            {**result.to_json(), "params_declaration": cast("JSONValue", raw_decl)}
        ).params_declaration
        result = replace(result, params_declaration=declaration)
    return build if result is build.result else replace(build, result=result)


class Publisher:
    """Build and export publication policy for one project over one opstore."""

    def __init__(
        self,
        layout: ProjectLayout,
        store: OpStore,
        *,
        locks: LockManager | None = None,
        owner: OwnerId | None = None,
    ) -> None:
        self.layout = layout
        self._store = store
        self.locks = locks or LockManager(store, owner=owner)
        self.parts = ProjectStore(layout, store, locks=self.locks)
        self.projections = Projections(store, locks=self.locks)

    # -- snapshot freeze ----------------------------------------------------

    def freeze_inputs(self, part: str) -> FrozenBuildInputs:
        """Capture the build's immutable inputs under project-config + part locks.

        Locks are held only for the capture and released before geometry
        computation (architecture §3.5 build lock discipline).

        **The store's admission guard runs first** (``INTERFACE.md`` §22.6's
        CORRECTION and the second half of §19.40). ``opstore/gc.py``'s contract
        is *"if protected+pinned (reachable) bytes alone exceed
        ``config.quota_bytes``, ``admission_guard()`` raises
        ``ProtectedQuotaExceededError`` so new artifact-producing work fails
        before execution"*, and until this call site that guard had **no
        production caller anywhere in the repo** — so the sentence described a
        protection nothing performed, and a project that pinned its way past the
        quota (which §22's export panel makes easy, since every export pins its
        outputs and its source build forever) grew without limit and refused
        nothing.

        WHY here and not at each of the four callers. This method is the single
        funnel every production build passes through before execution — the
        engine CLI's ``_build_and_publish``, ``build_part``, ``run_checks``'
        rebuild and ``set_params``' rebuild — and it is itself the first write of
        a build (it registers the script, globals and import snapshots). One seam
        rather than four is also what keeps the guard from being forgotten by the
        fifth caller.

        The refusal is the store's own ``ProtectedQuotaExceededError``, carrying
        its ``GcUsage`` snapshot: §22.6 is explicit that the reason is
        ``protected_quota_exceeded`` and not a second name invented for the same
        state, and §22.7 requires the numbers to travel with it.
        """
        self._store.gc.admission_guard()
        with self.locks.holding(PROJECT_CONFIG_LOCK, part_lock(part)):
            script = self.parts.read_part(part)
            globals_snapshot: SourceSnapshot | None = self.parts.read_globals()
            imports, import_errors, import_refs = self._freeze_imports(script.content)
        return FrozenBuildInputs(
            part=part,
            script=script.content,
            script_hash=script.content_hash,
            script_snapshot_ref=script.snapshot_ref,
            globals_source=None if globals_snapshot is None else globals_snapshot.content,
            globals_snapshot_ref=(
                None if globals_snapshot is None else globals_snapshot.snapshot_ref
            ),
            manifest_params=dict(self.layout.manifest.params),
            imports=imports,
            import_errors=import_errors,
            import_refs=import_refs,
        )

    def _freeze_imports(
        self, script: str
    ) -> tuple[dict[str, ImportPayload], dict[str, str], dict[str, str]]:
        """Read + register every import declaration of ``script``.

        The declarations are read statically from the script (INGEST.md §1), so
        the freeze covers exactly the files this build will use — no directory
        scan, no file the script never names. A refusal is RECORDED, never
        raised: a missing or unreadable import must surface as the §8 build
        error at its own statement, with a frame and a built-through, not as an
        exception out of the freeze.

        Declarations rather than path strings (``MESH_INGEST.md`` §1.1): the
        kind resolves the §1.6 byte ceiling this file is read under, and the
        declared unit rides along to staging, where §1.5 bakes it into the
        canonical geometry. One file may be declared at two units, so the
        payload's ``units`` is the sorted set of everything this script declared
        for that path, and staging (``runner.stage_request_imports``) makes one
        staged artifact per member.
        """
        imports: dict[str, ImportPayload] = {}
        errors: dict[str, str] = {}
        refs: dict[str, str] = {}
        units: dict[str, set[str]] = {}
        for declaration in static_import_declarations(script):
            path = declaration.path
            if declaration.units is not None:
                units.setdefault(path, set()).add(declaration.units)
            if path in errors or path in imports:
                continue
            try:
                snapshot = self.parts.read_import(path, kind=declaration.kind)
            except ImportResolutionError as exc:
                errors[path] = exc.message
                continue
            imports[path] = ImportPayload(data=snapshot.data, kind=declaration.kind)
            refs[path] = snapshot.snapshot_ref
        for path, payload in imports.items():
            imports[path] = ImportPayload(
                data=payload.data, kind=payload.kind, units=tuple(sorted(units.get(path, ())))
            )
        return imports, errors, refs

    def sync_import_state(self) -> StaleReport | None:
        """Advance the projection state to the live ``imports/`` hashes.

        A replaced import file is a changed build input, so its consumers go
        stale exactly as consumers of a changed ``hc`` name do (INGEST.md §1).
        Returns ``None`` when nothing moved — an unchanged tree must not bump
        the audit revision.
        """
        live = {path: self.parts.import_hash(path) or "" for path in self.parts.list_imports()}
        if dict(self.projections.state().import_state) == live:
            return None
        return self.projections.apply_import_state(live)

    # -- current bundle reads ------------------------------------------------

    def _current_bundle(self, part: str) -> Mapping[str, JSONValue] | None:
        pointer = self._store.blobs.read_pointer(current_pointer(part))
        if pointer is None:
            return None
        raw = json.loads(self._store.blobs.get(pointer).decode("utf-8"))
        return cast("Mapping[str, JSONValue]", raw)

    def current_bundle(self, part: str) -> Mapping[str, JSONValue] | None:
        """The published bundle document behind ``part``'s current pointer.

        Lock-free, and the only route to what publication recorded *about* a
        build — its §7 geometry index, its tag fingerprints — rather than to the
        §8 BuildResult inside it. ``ASSEMBLY.md`` §2 anchor resolution needs
        exactly that: the selector namespace of a build whose worker is long
        gone.
        """
        return self._current_bundle(part)

    def bundle_for_artifact(self, part: str, artifact_ref: str) -> Mapping[str, JSONValue] | None:
        """The bundle recorded for ONE published build of ``part``, or ``None``.

        Every parent-side measurement resolves its §7 namespace through this
        (audit-2026-09-04 B-1): ``measure``, project-scope ``run_checks`` and
        ``heph check`` had no route to it at all and addressed the literal
        ``"part"`` selector instead. ``None`` is a fact, not a failure — a build
        published before bundles were durable, or one whose bundle has been
        collected with its artifact — and the caller falls back to the
        ``"part"``-only source rather than inventing a namespace.
        """
        blob = self._bundle_blob_for_artifact(part, artifact_ref)
        if blob is None or not self._store.blobs.has(blob):
            return None
        raw = json.loads(self._store.blobs.get(blob).decode("utf-8"))
        if not isinstance(raw, dict):  # pragma: no cover - our own canonical JSON
            return None
        bundle = cast("Mapping[str, JSONValue]", raw)
        # The pointer is keyed by the artifact, but a bundle that names a
        # different one would be a store we should not read from: refuse rather
        # than resolve selectors against the wrong build.
        recorded = bundle.get("artifact_ref")
        if isinstance(recorded, str) and recorded != artifact_ref:  # pragma: no cover - defensive
            return None
        return bundle

    def bundle_ref_for_artifact(self, part: str, artifact_ref: str) -> str | None:
        """``artifact:build-bundle:sha256:…`` of one build's bundle, if stored.

        The immutable handle a *snapshot manifest* records beside each part's
        artifact ref, so a manifest read back later resolves the namespace of
        the build it actually froze rather than of whatever that part published
        since.
        """
        blob = self._bundle_blob_for_artifact(part, artifact_ref)
        if blob is None or not self._store.blobs.has(blob):
            return None
        return make_artifact_ref(BUILD_BUNDLE_ARTIFACT_KIND, blob)

    def _bundle_blob_for_artifact(self, part: str, artifact_ref: str) -> str | None:
        """The bundle blob for one build: the current pointer, else the durable one.

        The current pointer is consulted first, and only when it actually names
        ``artifact_ref``. Two reasons, and both are about not answering with the
        wrong build's namespace:

        * a build the part is currently publishing has exactly one authoritative
          bundle — the one behind ``part-current:``. A later PREVIEW of the same
          bytes (``run_checks`` republishes the current script) overwrites the
          durable pointer, and preferring the current pointer keeps
          ``measure`` reading the build the project is standing behind;
        * a store whose builds predate :func:`build_bundle_pointer` has no
          durable pointer at all, and this is what makes the change
          zero-migration: the CURRENT build — the default path of every
          measurement — resolves its namespace on the first run.

        The durable pointer then answers for exactly the refs the current
        pointer cannot: historical builds, previews, and raced builds.
        """
        current = self._store.blobs.read_pointer(current_pointer(part))
        if current is not None and self._store.blobs.has(current):
            raw = json.loads(self._store.blobs.get(current).decode("utf-8"))
            if isinstance(raw, dict):
                recorded = cast("Mapping[str, JSONValue]", raw).get("artifact_ref")
                if recorded == artifact_ref:
                    return current
        return self._store.blobs.read_pointer(
            build_bundle_pointer(part, blob_hash_of_ref(artifact_ref))
        )

    def _record_artifact_bundle(self, part: str, artifact_ref: str | None, bundle_blob: str) -> str:
        """Point ``build-bundle:<part>:<artifact>`` at ``bundle_blob`` (idempotent).

        GC-linked **from the artifact**: the namespace a build published is only
        meaningful while the geometry it describes still exists, so the bundle
        lives exactly as long as its artifact and is collected with it. Nothing
        new is pinned and no retention class is widened.
        """
        if artifact_ref is None:
            return bundle_blob
        artifact_blob = blob_hash_of_ref(artifact_ref)
        self._store.gc.link(artifact_blob, bundle_blob)
        record_artifact_kind(self._store, BUILD_BUNDLE_ARTIFACT_KIND, bundle_blob)
        pointer = build_bundle_pointer(part, artifact_blob)
        expected = self._store.blobs.read_pointer(pointer)
        if expected == bundle_blob:
            return bundle_blob
        # A concurrent publication of the same (part, artifact) may win the race;
        # both bundles describe the same bytes, so either answers the same
        # question and the loser has nothing to redo.
        with contextlib.suppress(ConflictedError):
            self._store.blobs.cas_swap(pointer, expected, bundle_blob)
        return bundle_blob

    def _install_artifact_bundle(
        self, build: UnpublishedBuild, retention: str = "default"
    ) -> str | None:
        """Store the bundle of a build that is NOT becoming current, and point at it.

        ``ASSEMBLY.md`` §2's bundle used to be written only by the current-pointer
        flip, so a preview or raced build published its geometry and nothing that
        said which selectors that geometry admits. B-1 makes the record
        unconditional: what a build published is a fact about that build, not
        about whether it won the pointer.
        """
        if build.result.artifact_ref is None:
            return None
        bundle = build_bundle(build, build.result, self.projections.state().audit_revision)
        blob = self._store.blobs.put(canonical_json(bundle).encode("utf-8"), retention)
        return self._record_artifact_bundle(build.result.part, build.result.artifact_ref, blob)

    def current_result(self, part: str) -> BuildResult | None:
        """The last published current BuildResult of ``part`` (lock-free read)."""
        bundle = self._current_bundle(part)
        if bundle is None:
            return None
        result_raw = bundle.get("result")
        if not isinstance(result_raw, dict):
            raise ValidationError("current bundle has no result record", kind="contract")
        return BuildResult.from_json(result_raw)

    def last_failure_result(self, part: str) -> BuildResult | None:
        """The most-recent failed BuildResult of ``part`` (lock-free read).

        Failed publishes store the §8 record (not a current bundle) at the
        last-failure pointer. ``None`` when no failed build has been published.
        """
        pointer = self._store.blobs.read_pointer(last_failure_pointer(part))
        if pointer is None:
            return None
        raw = json.loads(self._store.blobs.get(pointer).decode("utf-8"))
        if not isinstance(raw, dict):
            raise ValidationError("last-failure record is not an object", kind="contract")
        return BuildResult.from_json(cast("Mapping[str, JSONValue]", raw))

    def baseline_for(self, part: str) -> FingerprintBaseline | None:
        """§5.3 fingerprint baseline: the current bundle's descriptors + ref.

        ``None`` when no successful current build exists — failed, preview,
        and raced builds never move the baseline.
        """
        bundle = self._current_bundle(part)
        if bundle is None:
            return None
        fingerprints_raw = bundle.get("tag_fingerprints")
        artifact_ref = bundle.get("artifact_ref")
        if not isinstance(fingerprints_raw, dict) or not isinstance(artifact_ref, str):
            raise ValidationError("current bundle is malformed", kind="contract")
        return FingerprintBaseline(
            descriptors=descriptors_from_json(fingerprints_raw), artifact_ref=artifact_ref
        )

    # -- build publication ---------------------------------------------------

    def publish_build(
        self,
        build: UnpublishedBuild,
        *,
        op_id: str,
        preview: bool = False,
    ) -> PublicationOutcome:
        """Publish one completed build (see module docstring for the contract).

        ``preview=True`` marks a transient-parameter build: evidence blobs are
        installed under the 7-day retention class and the build can never
        become current. Idempotent on ``op_id`` for the current-pointer flip.
        """
        build = _with_worker_facts(build)
        part = build.result.part
        if build.result.status == "failed":
            kind: PublicationKind = "failed"
        elif preview:
            kind = "preview"
        else:
            kind = "current"
        retention = PREVIEW_RETENTION_CLASS if kind == "preview" else "default"
        evidence_refs, evidence_blobs = self._install_evidence(build, retention)
        record_blob = self._store.blobs.put(
            canonical_json(build.result.to_json()).encode("utf-8"), retention
        )
        for blob in evidence_blobs:
            self._store.gc.link(record_blob, blob)
        if kind != "current":
            # Failed builds and previews: evidence published, never current,
            # never clearing stale, prior current artifact preserved. The
            # most-recent failure record becomes the part's protected
            # last-good pointer (§3.5); older failures age out normally.
            if kind == "failed":
                self._set_last_failure(part, record_blob)
            # B-1: a preview's §7 namespace is recorded too, in its own
            # retention class and GC-linked to its own artifact. `run_checks`
            # publishes previews and then measures them; without this the
            # measurement could address only "part".
            self._install_artifact_bundle(build, retention)
            return PublicationOutcome(
                kind=kind,
                part=part,
                result=build.result,
                artifact_ref=build.result.artifact_ref,
                record_blob=record_blob,
                evidence_refs=evidence_refs,
            )
        # ``holding`` releases every lock actually acquired on all exit paths —
        # in particular, a part-lock acquisition failure must not leak the
        # already-acquired project-config lock (a leaked exclusive lease from a
        # live process is unreclaimable until the process dies).
        with self.locks.holding(PROJECT_CONFIG_LOCK, part_lock(part)):
            mismatches = self._revalidate(build)
            if mismatches:
                # Raced: inputs moved since the frozen snapshot. The
                # content-addressed superseded artifact stays for audit, but
                # the build cannot become current and clears nothing. Its
                # namespace is recorded all the same (B-1): the artifact is
                # citable evidence, and evidence nobody can address is evidence
                # nobody can check.
                self._install_artifact_bundle(build, retention)
                return PublicationOutcome(
                    kind="raced",
                    part=part,
                    result=build.result,
                    artifact_ref=build.result.artifact_ref,
                    record_blob=record_blob,
                    evidence_refs=evidence_refs,
                    details=mismatches,
                )
            return self._flip_current(
                build,
                op_id=op_id,
                record_blob=record_blob,
                evidence_refs=evidence_refs,
                evidence_blobs=evidence_blobs,
            )

    def _set_last_failure(self, part: str, record_blob: str) -> None:
        """Advance ``part``'s most-recent-failure pointer to ``record_blob``."""
        pointer = last_failure_pointer(part)
        while True:
            expected = self._store.blobs.read_pointer(pointer)
            if expected == record_blob:
                return
            try:
                self._store.blobs.cas_swap(pointer, expected, record_blob)
                return
            except ConflictedError:  # pragma: no cover - concurrent failure race
                continue

    def _install_evidence(
        self, build: UnpublishedBuild, retention: str
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Install every artifact file as a content-addressed blob; verify refs."""
        refs: list[str] = []
        blobs: list[str] = []
        for ref in sorted(build.artifact_files):
            path = build.artifact_files[ref]
            if ref.startswith(SOURCE_MAP_REF_PREFIX) and build.source_map is not None:
                data = canonical_json(dict(build.source_map)).encode("utf-8")
            else:
                data = path.read_bytes()
            stored = self._store.blobs.put(data, retention)
            expected = blob_hash_of_ref(ref)
            if stored != expected:
                raise ConflictError(
                    f"artifact bytes for {ref} hash to {stored}; evidence is corrupt"
                )
            refs.append(ref)
            blobs.append(stored)
        # §2.6's CORRECTION / §19.24: the kind is recorded where the blob is
        # installed. This loop already proves the ref's *hash* half against the
        # bytes; recording the *kind* half here is what lets a reader refuse a
        # ref that relabels these bytes as something else. Every build artifact
        # — `build`, `build-checkpoint`, `source-map` — is covered by
        # construction, because they are exactly the keys of `artifact_files`.
        record_artifact_refs(self._store, refs)
        return tuple(refs), tuple(blobs)

    def _revalidate(self, build: UnpublishedBuild) -> tuple[str, ...]:
        """Recheck script/part-param/toolchain/consumed-hc hashes under locks.

        A thin caller of :func:`input_mismatches` since audit-2026-09-04 B-5:
        the comparison itself is shared with :meth:`freshness`, which asks the
        same question on a **read** with no locks and no build in hand. One
        implementation rather than two is the whole point — a second copy would
        be a second answer to "are this build's inputs still the live ones", and
        the route would drift from the pointer flip the moment either changed.
        """
        part = build.result.part
        expected = build.result.input_hashes
        declaration = build.worker_result.get("params_declaration")
        script_path = self.layout.part_path(part)
        return tuple(
            mismatch.detail
            for mismatch in input_mismatches(
                expected,
                live_script=(
                    sha256_bytes(script_path.read_bytes()) if script_path.is_file() else None
                ),
                live_toolchain=toolchain_hash(),
                live_part_params=(
                    sha256_canonical_json(declaration) if isinstance(declaration, dict) else None
                ),
                live_imports={
                    path: self.parts.import_hash(path) for path in sorted(expected.imports)
                },
                consumed_hc=build.consumed_hc,
                live_hc=self.projections.state().hc_state,
            )
        )

    def recorded_check_names(self, part: str) -> tuple[str, ...] | None:
        """``part``'s current build's declared check names, or ``None`` if unstated.

        The distinction the dataclass field cannot make and that one caller
        needs: ``()`` on :class:`BuildResult` means both "this build registered
        no checks" and "this record was written before the field existed". Here
        the *stored document* is asked whether it carries the key at all, so
        ``run_checks``'s no-rebuild fast path acts on a recorded fact rather
        than on an inference from silence (audit-2026-09-04 J-cli-startup-9).
        """
        bundle = self._current_bundle(part)
        if bundle is None:
            return None
        result_raw = bundle.get("result")
        if not isinstance(result_raw, dict):
            return None
        record = cast("Mapping[str, JSONValue]", result_raw)
        if "check_names" not in record:
            return None
        return BuildResult.from_json(record).check_names

    def freshness(self, part: str) -> BuildFreshness | None:
        """Are ``part``'s current build's recorded inputs still the live ones?

        The read-time half of the comparison :meth:`_revalidate` runs under
        locks at publication, and the answer ``BuildResult.current`` cannot
        give: ``current`` is publication state, stamped once by the pointer flip
        and true forever after (``architecture.md`` §3.5), so a reader that
        renders it as "up to date" is stating something the record never claimed
        (audit-2026-09-04 B-5).

        Lock-free and never a rebuild — one pointer read, one blob read, one
        script hash. It is reconstructible from a pure read only because the
        bundle already records the consumed-``hc`` projection beside the §8
        input hashes; ``None`` where it does not (no current bundle at all, or a
        bundle written before that map existed), so a caller reports the absence
        of an answer rather than an invented "fresh".

        The ``part_params`` leg is not compared here and does not need to be:
        the ``PARAMS`` declaration is parsed out of the script, so a changed
        declaration is a changed script and the script leg already names it.
        """
        bundle = self._current_bundle(part)
        if bundle is None:
            return None
        consumed_raw = bundle.get("consumed_hc")
        result_raw = bundle.get("result")
        if not isinstance(consumed_raw, dict):
            return None
        if not isinstance(result_raw, dict):
            raise ValidationError("current bundle has no result record", kind="contract")
        expected = BuildResult.from_json(cast("Mapping[str, JSONValue]", result_raw)).input_hashes
        script_path = self.layout.part_path(part)
        live_script = sha256_bytes(script_path.read_bytes()) if script_path.is_file() else None
        mismatches = input_mismatches(
            expected,
            live_script=live_script,
            live_toolchain=toolchain_hash(),
            live_part_params=None,
            compare_part_params=False,
            live_imports={path: self.parts.import_hash(path) for path in sorted(expected.imports)},
            consumed_hc=cast("Mapping[str, JSONValue]", consumed_raw),
            live_hc=self.projections.state().hc_state,
        )
        return BuildFreshness(
            changed_inputs=tuple(dict.fromkeys(mismatch.input for mismatch in mismatches)),
            live_script_hash=live_script,
        )

    def _flip_current(
        self,
        build: UnpublishedBuild,
        *,
        op_id: str,
        record_blob: str,
        evidence_refs: tuple[str, ...],
        evidence_blobs: tuple[str, ...],
    ) -> PublicationOutcome:
        part = build.result.part
        published = replace(build.result, current=True)
        bundle = build_bundle(build, published, self.projections.state().audit_revision)
        bundle_blob = self._store.blobs.put(canonical_json(bundle).encode("utf-8"))
        payload: JSONValue = {
            "kind": "build_publication",
            "part": part,
            "bundle": bundle_blob,
        }
        payload_hash = sha256_canonical_json(payload)
        outcome = self._store.opkeys.begin(op_id, payload_hash)
        if isinstance(outcome, PendingRecovery):
            self._store.wal.recover(outcome.op_key)
            outcome = self._store.opkeys.begin(op_id, payload_hash)
        replayed = isinstance(outcome, Replay)
        if isinstance(outcome, Fresh):
            expected_pointer = self._store.blobs.read_pointer(current_pointer(part))
            try:
                self._store.wal.publish(
                    outcome,
                    current_pointer(part),
                    expected_pointer,
                    bundle_blob,
                    intended_outcome=canonical_json({"published": bundle_blob}),
                )
            except ConflictedError:
                # The bundle above says ``current: true``; this build did not
                # become current, so its namespace is recorded from the
                # non-current result instead. A raced build is still citable
                # evidence, and evidence nobody can address is evidence nobody
                # can check.
                self._install_artifact_bundle(build)
                return PublicationOutcome(
                    kind="raced",
                    part=part,
                    result=build.result,
                    artifact_ref=build.result.artifact_ref,
                    record_blob=record_blob,
                    evidence_refs=evidence_refs,
                    details=("current pointer moved during publication",),
                )
        elif not replayed:
            raise ConflictError(
                f"build publication {op_id!r} cannot proceed: prior state {outcome!r}"
            )
        # Idempotent completion (re-run on committed retries too, so a crash
        # between the pointer flip and these steps still converges):
        artifact_ref = published.artifact_ref
        if artifact_ref is None:  # pragma: no cover - ok builds always carry a ref
            raise ValidationError("successful build has no artifact ref", kind="contract")
        # B-1: the same bundle, additionally addressable by the artifact it
        # describes. The current pointer moves on every rebuild; this one does
        # not, so a ref naming THIS build keeps resolving its own namespace.
        self._record_artifact_bundle(part, artifact_ref, bundle_blob)
        self.projections.record_current(
            part,
            consumed=build.consumed_hc,
            artifact_ref=artifact_ref,
            bundle_ref=make_artifact_ref(BUILD_BUNDLE_ARTIFACT_KIND, bundle_blob),
            imports=published.input_hashes.imports,
        )
        for blob in (record_blob, *evidence_blobs):
            self._store.gc.link(bundle_blob, blob)
        return PublicationOutcome(
            kind="current",
            part=part,
            result=published,
            artifact_ref=artifact_ref,
            record_blob=bundle_blob,
            evidence_refs=evidence_refs,
            replayed=replayed,
        )

    # -- synthetic exports ---------------------------------------------------

    def publish_export(
        self,
        *,
        name: str,
        data: bytes,
        source_artifact_ref: str,
        op_id: str,
    ) -> ExportOutcome:
        """Publish an export file derived from a stored successful artifact.

        Authorizes the immutable source (its blob must be durably stored),
        installs the output under ``.heph/exports/`` through the file WAL,
        persists the export blob as a GC-root pin, and records the provenance
        link to its source build. Idempotent on ``op_id``; the pin and link
        are reapplied on retries so recovery converges from any crash point.
        """
        if "/" in name or "\\" in name or name in (".", "..") or not name:
            raise ValidationError(
                f"export name must be a plain filename, got {name!r}", kind="contract"
            )
        source_blob = blob_hash_of_ref(source_artifact_ref)
        if not self._store.blobs.has(source_blob):
            raise ConflictError(
                f"export source {source_artifact_ref} is not a durably stored artifact"
            )
        export_blob = self._store.blobs.put(data)
        target = self.layout.exports_dir / name
        payload: JSONValue = {
            "kind": "export",
            "name": name,
            "source": source_artifact_ref,
            "data": export_blob,
        }
        payload_hash = sha256_canonical_json(payload)
        outcome = self._store.opkeys.begin(op_id, payload_hash)
        if isinstance(outcome, PendingRecovery):
            self._store.wal.recover(outcome.op_key)
            outcome = self._store.opkeys.begin(op_id, payload_hash)
        replayed = isinstance(outcome, Replay)
        if isinstance(outcome, Fresh):
            self._store.wal.execute(
                outcome,
                target,
                data,
                intended_outcome=canonical_json({"export": export_blob, "name": name}),
            )
        elif not replayed:
            raise ConflictError(
                f"export publication {op_id!r} cannot proceed: prior state {outcome!r}"
            )
        self._store.gc.pin(export_blob)
        self._store.gc.link(export_blob, source_blob)
        # §19.24: an export blob is recorded as an `export`, so §15.17's refusal
        # is about these bytes rather than about the four letters a caller chose
        # to put in a ref. Recorded next to the pin because both are the
        # idempotent completion steps a replay re-runs.
        record_artifact_kind(self._store, EXPORT_ARTIFACT_KIND, export_blob)
        return ExportOutcome(
            name=name,
            path=target,
            export_ref=EXPORT_REF_PREFIX + export_blob,
            blob_hash=export_blob,
            source_artifact_ref=source_artifact_ref,
            pinned=True,
            replayed=replayed,
        )
