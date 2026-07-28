"""Shared state, persisted-override storage and the error taxonomy for CadOps.

Every domain mixin in this package derives from :class:`CadOpsState`, which owns
the three things the operations share — the project layout, the opstore and the
execution backend — plus the helpers built directly on them: publisher/render/
check-set constructors, scratch and build directories, the sandboxed build call,
and geometry resolution from artifact or project-snapshot refs.

Also here, because they sit *below* every domain: :class:`CadOpError` (the stable
machine-token refusal every op raises), :class:`ParamStore` (the CAS-pointer
override document each scope persists, journaled and idempotent on the trusted
invocation id) and the JSON decoding helpers that read worker results and
WAL-recorded outcomes.
"""

from __future__ import annotations

import contextlib
import json
import shutil
import tempfile
import uuid
from collections.abc import Generator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, cast

from hephaestus.core.checks.engine import CheckSet
from hephaestus.core.checks.facade import GeometrySource
from hephaestus.core.executor.artifact_geometry import artifact_source
from hephaestus.core.executor.runner import BuildRequest, UnpublishedBuild, run_build
from hephaestus.core.executor.sandbox.base import ExecBackend
from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend
from hephaestus.core.project_store.layout import ProjectLayout
from hephaestus.core.project_store.projections import PROJECT_SNAPSHOT_REF_PREFIX
from hephaestus.core.project_store.publication import Publisher
from hephaestus.core.project_store.store import (
    artifact_ref as make_artifact_ref,
)
from hephaestus.core.project_store.store import (
    blob_hash_of_ref,
)
from hephaestus.core.render.inspect import RenderProject
from opstore.types import JSONValue

from opstore import (
    Fresh,
    OpStore,
    PendingRecovery,
    Replay,
    canonical_json,
    sha256_canonical_json,
)

#: CAS pointer holding a part's persisted parameter-override document.
PART_PARAMS_POINTER_PREFIX: Final[str] = "part-params:"
#: CAS pointer holding the project's persisted parameter-override document.
PROJECT_PARAMS_POINTER: Final[str] = "project-params"


class CadOpError(Exception):
    """A core-backed operation refused; ``reason`` is a stable machine token."""

    def __init__(
        self, reason: str, message: str, *, data: Mapping[str, JSONValue] | None = None
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.data: dict[str, JSONValue] = dict(data or {})


# --------------------------------------------------------------------------
# JSON decoding helpers


def recorded_ref(response: str | None, key: str, fallback: str) -> str:
    """A field of a WAL-recorded ``intended_outcome`` (used on replay)."""
    if response is None:  # tombstone replay: only the terminal state survives
        return fallback
    try:
        decoded = cast("Mapping[str, JSONValue]", json.loads(response))
    except (ValueError, TypeError):  # pragma: no cover - responses are our own JSON
        return fallback
    value = decoded.get(key)
    return value if isinstance(value, str) else fallback


def numeric_map(raw: JSONValue | None) -> dict[str, int | float]:
    out: dict[str, int | float] = {}
    if not isinstance(raw, dict):
        return out
    for name, value in cast("Mapping[str, JSONValue]", raw).items():
        if isinstance(value, bool) or not isinstance(value, int | float):
            continue
        out[name] = value
    return out


def json_map(raw: JSONValue | None) -> dict[str, JSONValue]:
    if not isinstance(raw, dict):
        return {}
    return dict(cast("Mapping[str, JSONValue]", raw))


# --------------------------------------------------------------------------
# persisted parameter overrides


def params_pointer(scope: str, name: str | None) -> str:
    """The CAS pointer holding one scope's persisted override document."""
    if scope == "project":
        return PROJECT_PARAMS_POINTER
    if not name:
        raise CadOpError("invalid_params", "part scope requires a part name")
    return PART_PARAMS_POINTER_PREFIX + name


@dataclass(frozen=True)
class ParamState:
    """A scope's persisted override document plus its optimistic state hash."""

    scope: str
    name: str | None
    values: Mapping[str, int | float]
    state_hash: str
    blob: str | None  # pointer target the state was read from (None = unset)

    def to_json(self) -> dict[str, JSONValue]:
        return {"scope": self.scope, "name": self.name, "values": dict(self.values)}


class ParamConflict(CadOpError):
    """A stale ``expected_state_hash``: carries the live state, nothing written."""

    def __init__(self, current: ParamState) -> None:
        super().__init__(
            "stale_state_hash",
            f"parameter state for {current.scope} {current.name!r} moved to {current.state_hash}",
        )
        self.current = current


def _override_document(values: Mapping[str, int | float]) -> JSONValue:
    return {"values": {name: values[name] for name in sorted(values)}}


class ParamStore:
    """Durable, journaled, idempotent parameter-override documents over opstore."""

    def __init__(self, layout: ProjectLayout, store: OpStore) -> None:
        self._layout = layout
        self._store = store

    def read(self, scope: str, name: str | None) -> ParamState:
        """The persisted overrides for one scope (empty when never written)."""
        pointer = params_pointer(scope, name)
        blob = self._store.blobs.read_pointer(pointer)
        values: dict[str, int | float] = {}
        if blob is not None:
            raw = json.loads(self._store.blobs.get(blob).decode("utf-8"))
            recorded = cast("Mapping[str, JSONValue]", raw).get("values")
            if isinstance(recorded, dict):
                for key, value in cast("Mapping[str, JSONValue]", recorded).items():
                    if isinstance(value, bool) or not isinstance(value, int | float):
                        continue
                    values[key] = value
        return ParamState(
            scope=scope,
            name=name,
            values=values,
            state_hash=sha256_canonical_json(_override_document(values)),
            blob=blob,
        )

    def write(
        self,
        scope: str,
        name: str | None,
        values: Mapping[str, int | float],
        *,
        expected_state_hash: str,
        op_id: str,
    ) -> tuple[ParamState, str]:
        """CAS the override document; returns the new state and its journal ref.

        Raises :class:`ParamConflict` when ``expected_state_hash`` is stale
        (nothing is written). Idempotent on ``op_id``.
        """
        pointer = params_pointer(scope, name)
        current = self.read(scope, name)
        document = _override_document(values)
        new_blob = self._store.blobs.put(canonical_json(document).encode("utf-8"))
        # The idempotency payload is the *request* (presented base + candidate),
        # never the live state — otherwise a retry after a committed write would
        # hash differently and be misreported as a payload mismatch.
        payload: JSONValue = {
            "kind": "param_write",
            "scope": scope,
            "name": name,
            "expected_state_hash": expected_state_hash,
            "after": new_blob,
        }
        payload_hash = sha256_canonical_json(payload)
        outcome = self._store.opkeys.begin(op_id, payload_hash)
        if isinstance(outcome, PendingRecovery):
            self._store.wal.recover(outcome.op_key)
            outcome = self._store.opkeys.begin(op_id, payload_hash)
        if isinstance(outcome, Replay):
            # The recorded response names the journal entry of the original write.
            return self.read(scope, name), recorded_ref(
                outcome.response, "journal", make_artifact_ref("param-journal", new_blob)
            )
        if not isinstance(outcome, Fresh):
            raise CadOpError(
                "conflict", f"parameter write {op_id!r} cannot proceed: prior state {outcome!r}"
            )
        if current.state_hash != expected_state_hash:
            self._store.wal.recover(outcome.op_key)  # abort the fresh skeleton
            raise ParamConflict(current)
        journal_ref = self._journal(scope, name, current, new_blob)
        self._store.wal.publish(
            outcome,
            pointer,
            current.blob,
            new_blob,
            intended_outcome=canonical_json({"published": new_blob, "journal": journal_ref}),
        )
        return self.read(scope, name), journal_ref

    def _journal(self, scope: str, name: str | None, before: ParamState, after_blob: str) -> str:
        """Journal the previous override document under ``.heph/journal/``."""
        entry: JSONValue = {
            "kind": "param_write",
            "scope": scope,
            "name": name,
            "before": dict(before.values),
            "before_state_hash": before.state_hash,
            "after_blob": after_blob,
        }
        payload = canonical_json(entry).encode("utf-8")
        blob = self._store.blobs.put(payload)
        self._layout.journal_dir.mkdir(parents=True, exist_ok=True)
        (self._layout.journal_dir / f"params-{blob.removeprefix('sha256:')[:32]}.json").write_bytes(
            payload
        )
        return make_artifact_ref("param-journal", blob)


# --------------------------------------------------------------------------
# the state every domain mixin shares


class CadOpsState:
    """The layout/opstore/backend triple and the helpers built on top of it."""

    def __init__(
        self,
        layout: ProjectLayout,
        store: OpStore,
        *,
        backend: ExecBackend | None = None,
    ) -> None:
        self._layout = layout
        self._store = store
        # Default to the unsafe local backend (no OS sandbox) for fast tests;
        # production wiring passes a probed secure backend.
        self._backend: ExecBackend = backend or UnsafeLocalBackend()
        self.params = ParamStore(layout, store)
        self._request_text: str | None = None

    @property
    def layout(self) -> ProjectLayout:
        return self._layout

    # -- the original request (VALIDATION.md §4 / §5) -----------------------

    @property
    def request_text(self) -> str | None:
        """The request this project is working from, or None when unknown.

        ``VALIDATION.md`` §4 diffs the numbers in the request against the built
        geometry, and §5 hands the reviewer the request verbatim; both need the
        text to reach the ops layer, which the bridge does by binding it on the
        run's prompt. Unknown is a first-class state: a critique with no request
        **omits** ``prompt_number_diff`` rather than inventing one.
        """
        return self._request_text

    def set_request_text(self, text: str | None) -> None:
        """Bind the request text (the latest user turn is the live request)."""
        cleaned = text.strip() if text is not None else None
        self._request_text = cleaned or None

    def _publisher(self) -> Publisher:
        return Publisher(self._layout, self._store)

    def _render_project(self) -> RenderProject:
        return RenderProject(layout=self._layout, store=self._store)

    def _check_set(self) -> CheckSet:
        return CheckSet(self._layout.checks_dir, self._store)

    def _scratch(self, prefix: str) -> tempfile.TemporaryDirectory[str]:
        self._layout.store_root.mkdir(parents=True, exist_ok=True)
        return tempfile.TemporaryDirectory(prefix=prefix, dir=self._layout.store_root)

    def _project_overrides(self) -> dict[str, int | float | str]:
        """Manifest ``[params]`` merged under the persisted project overrides."""
        merged: dict[str, int | float | str] = dict(self._layout.manifest.params)
        merged.update(self.params.read("project", None).values)
        return merged

    def _sync_projections(self, publisher: Publisher, hc_state: Mapping[str, JSONValue]) -> None:
        """Advance the audit revision to a worker-computed live ``hc`` projection."""
        live = publisher.projections.state().hc_state
        if canonical_json(dict(live)) != canonical_json(dict(hc_state)):
            publisher.projections.apply_hc_state(
                hc_state, reason="globals.py or project parameters changed"
            )

    @contextlib.contextmanager
    def _build_dir(self, part: str) -> Generator[Path]:
        """A scratch output directory that outlives the build until publication.

        Artifact *files* live here until the publisher installs them as
        content-addressed blobs, so the tree may only be removed after the caller
        is done with ``UnpublishedBuild.artifact_files``.
        """
        out_dir = self._layout.store_root / "builds" / f"{part}-{uuid.uuid4().hex[:12]}"
        try:
            yield out_dir
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)

    def _run(
        self,
        part: str,
        script: str,
        globals_source: str | None,
        *,
        out_dir: Path,
        part_overrides: Mapping[str, int | float | str],
        project_overrides: Mapping[str, int | float | str],
        baseline: object = None,
        imports: Mapping[str, bytes] | None = None,
        import_errors: Mapping[str, str] | None = None,
    ) -> UnpublishedBuild:
        request = BuildRequest(
            part=part,
            script=script,
            globals_source=globals_source,
            part_overrides=dict(part_overrides),
            project_overrides=dict(project_overrides),
            origin="local",
            # INGEST.md §1: the frozen import bytes travel with the request, so
            # a retry replays the original content rather than whatever is on
            # disk now.
            imports=dict(imports or {}),
            import_errors=dict(import_errors or {}),
        )
        return run_build(
            request,
            backend=self._backend,
            out_dir=out_dir,
            baseline=cast("Any", baseline),
        )

    # -- geometry resolution (measure and project checks share this) --------

    def _snapshot_sources(
        self, snapshot_ref: str, scratch: Path
    ) -> tuple[dict[str, GeometrySource], list[str]]:
        if not snapshot_ref.startswith(PROJECT_SNAPSHOT_REF_PREFIX):
            raise CadOpError("invalid_params", f"{snapshot_ref} is not a project-snapshot ref")
        blob = blob_hash_of_ref(snapshot_ref)
        if not self._store.blobs.has(blob):
            raise CadOpError(
                "invalid_params", f"project snapshot {snapshot_ref} is not durably stored"
            )
        manifest = cast(
            "Mapping[str, JSONValue]", json.loads(self._store.blobs.get(blob).decode("utf-8"))
        )
        parts_raw = manifest.get("parts")
        if not isinstance(parts_raw, dict):
            raise CadOpError("invalid_params", f"project snapshot {snapshot_ref} is malformed")
        sources: dict[str, GeometrySource] = {}
        refs: list[str] = [snapshot_ref]
        for name, entry in sorted(cast("Mapping[str, JSONValue]", parts_raw).items()):
            if not isinstance(entry, dict):
                continue
            ref = cast("Mapping[str, JSONValue]", entry).get("artifact_ref")
            if not isinstance(ref, str):
                continue
            sources[name] = self._artifact_geometry(ref, scratch)
            refs.append(ref)
        return sources, refs

    def _artifact_geometry(self, ref: str, scratch: Path) -> GeometrySource:
        blob = blob_hash_of_ref(ref)
        if not self._store.blobs.has(blob):
            raise CadOpError("invalid_params", f"artifact {ref} is not durably stored")
        return artifact_source(self._store.blobs.get(blob), scratch_dir=scratch)
