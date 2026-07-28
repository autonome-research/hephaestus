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

import json
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal, cast

from hephaestus.core.errors import ConflictError, ValidationError
from hephaestus.core.executor.fingerprint import (
    FingerprintBaseline,
    descriptors_from_json,
    descriptors_to_json,
)
from hephaestus.core.executor.imports import ImportResolutionError, static_import_paths
from hephaestus.core.executor.runner import UnpublishedBuild
from hephaestus.core.hashing import consumed_hc_hash, toolchain_hash
from hephaestus.core.project_store.layout import ProjectLayout
from hephaestus.core.project_store.locks import PROJECT_CONFIG_LOCK, LockManager, part_lock
from hephaestus.core.project_store.projections import Projections, StaleReport
from hephaestus.core.project_store.retention import last_failure_pointer
from hephaestus.core.project_store.store import (
    ProjectStore,
    SourceSnapshot,
    blob_hash_of_ref,
)
from hephaestus.core.types import BuildResult
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
    "CURRENT_POINTER_PREFIX",
    "EXPORT_REF_PREFIX",
    "ExportOutcome",
    "FrozenBuildInputs",
    "PublicationKind",
    "PublicationOutcome",
    "Publisher",
    "current_pointer",
]

#: CAS pointer prefix for per-part current-build bundles.
CURRENT_POINTER_PREFIX = "part-current:"
#: Ref prefix for published exports.
EXPORT_REF_PREFIX = "artifact:export:"

SOURCE_MAP_REF_PREFIX = "artifact:source-map:"

PublicationKind = Literal["current", "preview", "failed", "raced"]


def current_pointer(part: str) -> str:
    """The CAS pointer name holding ``part``'s current bundle blob hash."""
    return CURRENT_POINTER_PREFIX + part


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
    #: text so a lost-response retry replays the original content.
    imports: Mapping[str, bytes] = field(default_factory=dict[str, bytes])
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
        """
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
    ) -> tuple[dict[str, bytes], dict[str, str], dict[str, str]]:
        """Read + register every ``import_step`` declaration of ``script``.

        The declarations are read statically from the script (INGEST.md §1), so
        the freeze covers exactly the files this build will use — no directory
        scan, no file the script never names. A refusal is RECORDED, never
        raised: a missing or unreadable import must surface as the §8 build
        error at its own statement, with a frame and a built-through, not as an
        exception out of the freeze.
        """
        imports: dict[str, bytes] = {}
        errors: dict[str, str] = {}
        refs: dict[str, str] = {}
        for path in static_import_paths(script):
            try:
                snapshot = self.parts.read_import(path)
            except ImportResolutionError as exc:
                errors[path] = exc.message
                continue
            imports[path] = snapshot.data
            refs[path] = snapshot.snapshot_ref
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

    def current_result(self, part: str) -> BuildResult | None:
        """The last published current BuildResult of ``part`` (lock-free read)."""
        bundle = self._current_bundle(part)
        if bundle is None:
            return None
        result_raw = bundle.get("result")
        if not isinstance(result_raw, dict):
            raise ValidationError("current bundle has no result record", kind="contract")
        return BuildResult.from_json(result_raw)

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
                # the build cannot become current and clears nothing.
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
        return tuple(refs), tuple(blobs)

    def _revalidate(self, build: UnpublishedBuild) -> tuple[str, ...]:
        """Recheck script/part-param/toolchain/consumed-hc hashes under locks."""
        part = build.result.part
        expected = build.result.input_hashes
        mismatches: list[str] = []
        script_path = self.layout.part_path(part)
        live_script = sha256_bytes(script_path.read_bytes()) if script_path.is_file() else None
        if live_script != expected.script:
            mismatches.append(f"script: frozen {expected.script}, live {live_script}")
        live_toolchain = toolchain_hash()
        if live_toolchain != expected.toolchain:
            mismatches.append(f"toolchain: frozen {expected.toolchain}, live {live_toolchain}")
        declaration = build.worker_result.get("params_declaration")
        if not isinstance(declaration, dict):
            mismatches.append("part_params: build carries no params declaration")
        else:
            declared = sha256_canonical_json(declaration)
            if declared != expected.part_params:
                mismatches.append(f"part_params: frozen {expected.part_params}, live {declared}")
        # INGEST.md §1: a changed import file is a changed input. Revalidation
        # compares the live bytes against the frozen hashes, so a build that
        # raced a replaced STEP file can never flip the current pointer.
        for path, frozen in sorted(expected.imports.items()):
            live_import = self.parts.import_hash(path)
            if live_import != frozen:
                mismatches.append(
                    f"imports[{path}]: frozen {frozen}, live {live_import or 'unreadable'}"
                )
        live_hc = self.projections.state().hc_state
        missing = sorted(name for name in build.consumed_hc if name not in live_hc)
        if missing:
            mismatches.append(
                f"hc_dependencies: consumed names no longer defined: {', '.join(missing)}"
            )
        else:
            live_projection = {name: live_hc[name] for name in build.consumed_hc}
            live_hash = consumed_hc_hash(live_projection)
            if live_hash != expected.hc_dependencies:
                mismatches.append(
                    f"hc_dependencies: frozen {expected.hc_dependencies}, live {live_hash}"
                )
        return tuple(mismatches)

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
        bundle: JSONValue = {
            "kind": "build_bundle",
            "part": part,
            "result": published.to_json(),
            "artifact_ref": published.artifact_ref,
            "tag_fingerprints": descriptors_to_json(build.tag_fingerprints),
            # ASSEMBLY.md §2: the §7 namespace this build published. Recorded
            # beside the fingerprints because both answer the same question
            # about a *reloaded* artifact — which selectors it admits — that the
            # BRep bytes themselves cannot: constraint anchors are resolved
            # against a current build long after the worker that knew its labels
            # and tags has exited.
            "geometry_index": dict(build.geometry_index_json or {}),
            "consumed_hc": dict(build.consumed_hc),
            "audit_revision": self.projections.state().audit_revision,
        }
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
        self.projections.record_current(
            part,
            consumed=build.consumed_hc,
            artifact_ref=artifact_ref,
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
        return ExportOutcome(
            name=name,
            path=target,
            export_ref=EXPORT_REF_PREFIX + export_blob,
            blob_hash=export_blob,
            source_artifact_ref=source_artifact_ref,
            pinned=True,
            replayed=replayed,
        )
