"""Parent-side build orchestration: job -> worker -> UnpublishedBuild.

Builds the worker job, launches the worker through an :class:`ExecBackend`
(never directly), collects the one-JSON result, computes the §8 input/audit
hashes via :mod:`hephaestus.core.hashing`, and assembles a
:class:`hephaestus.core.types.BuildResult`. Publication policy (current
pointer, snapshots, stale markers) belongs to ``core/project_store`` — the
runner returns an :class:`UnpublishedBuild` with ``current=False``,
``project_snapshot_ref=None``, and the artifact files + deterministic
content refs the store needs to install them.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Final, Literal, cast

from hephaestus.core.addressing import GeometryIndex
from hephaestus.core.errors import SandboxDeniedError, ValidationError
from hephaestus.core.executor.artifacts import ARTIFACT_NAMES, read_artifact
from hephaestus.core.executor.fingerprint import (
    FingerprintBaseline,
    TagDescriptor,
    compare,
    descriptors_from_json,
)
from hephaestus.core.executor.identity import (
    IDENTITY_METADATA_KEY,
    ExecutionIdentity,
    backend_execution_identity,
)
from hephaestus.core.executor.imports import (
    ImportPayload,
    ImportResolutionError,
    stage_import,
    staged_key,
)
from hephaestus.core.executor.sandbox.base import ExecBackend, Rlimits, SandboxSpec
from hephaestus.core.executor.sandbox.oci_storage_policy import StoragePolicy
from hephaestus.core.executor.sandbox.oci_transfer import InputAdmission
from hephaestus.core.hashing import (
    consumed_hc_hash,
    effective_params_hash,
    hash_text,
    sha256_bytes,
    sha256_canonical_json,
    toolchain_hash,
)
from hephaestus.core.limits import limits_document
from hephaestus.core.types import (
    AuditHashes,
    BuildResult,
    CheckResult,
    ErrorRecord,
    GeometryEntry,
    InputHashes,
    Metrics,
    StatementCheckpoint,
    Warning,
)
from opstore.types import JSONValue

from opstore import canonical_json

#: Default worker resource limits (bounded, generous for CAD kernels).
#: nproc must exceed the invoking user's live kernel task ucount or bwrap's
#: userns clone fails EAGAIN (see sandbox/bwrap.py); 4096 is the standard
#: fork-bomb cap that clears real desktop task counts.
DEFAULT_RLIMITS = Rlimits(
    cpu_seconds=120,
    address_space_bytes=6 * 1024**3,
    nproc=4096,
)


def cad_build_wall_clock_s() -> float:
    """The build's wall-clock ceiling: ``timeouts.cad_build_seconds`` (arch §5).

    Read from ``schemas/bridge_limits.json`` — the same key the sidecar's tool
    proxy selects the CAD timeout class from — rather than restated as a
    literal here (J-http-limits-8). The two numbers agreed at 300 by
    coincidence, and a duplicated budget is one an operator can only half
    change: raising the shared limit left the executor killing the build at
    the old one. Resolved per call, the ``compare_timeout_s`` local-floor
    pattern, so an override document (``HEPHAESTUS_BRIDGE_LIMITS``) governs a
    live process instead of only a fresh interpreter.
    """
    return float(limits_document()["timeouts"]["cad_build_seconds"])


#: The shipped value of that budget, for readers who want the number rather
#: than the resolver. Never the source of truth — :func:`cad_build_wall_clock_s`
#: is, and the request's default calls it per build.
DEFAULT_WALL_CLOCK_S: Final[float] = cad_build_wall_clock_s()

BuildOrigin = Literal["local", "registry"]


def worker_args() -> tuple[str, ...]:
    """Interpreter-independent arguments selecting the build worker module."""
    return ("-m", "hephaestus.core.executor.worker")


@dataclass(frozen=True)
class BuildRequest:
    """One build invocation's frozen inputs."""

    part: str
    script: str
    globals_source: str | None = None
    part_overrides: Mapping[str, int | float | str] = field(
        default_factory=dict[str, "int | float | str"]
    )
    project_overrides: Mapping[str, int | float | str] = field(
        default_factory=dict[str, "int | float | str"]
    )
    origin: BuildOrigin = "local"
    wall_clock_s: float = field(default_factory=cad_build_wall_clock_s)
    #: INGEST.md §1: the FROZEN bytes of each declared ``imports/`` file, keyed
    #: by the path as written in the script. Bytes rather than paths so a
    #: lost-response retry replays the original content even if the file has
    #: since been replaced — exactly as the frozen script text does. Since
    #: Stage 12 each value is an :class:`ImportPayload`, carrying the declared
    #: kind and units beside the bytes (``MESH_INGEST.md`` §1.1): the staged
    #: *form* differs per kind and the staged *identity* includes the unit, so
    #: neither can stop at the AST.
    imports: Mapping[str, ImportPayload] = field(default_factory=dict[str, "ImportPayload"])
    #: Declared imports the resolver refused (path -> named refusal). Surfaced
    #: as a build error at the ``import_step`` statement, not before it.
    import_errors: Mapping[str, str] = field(default_factory=dict[str, str])


@dataclass(frozen=True)
class UnpublishedBuild:
    """A completed build before publication (project_store publishes it).

    ``result`` always has ``current=False`` and ``project_snapshot_ref=None``;
    part-scope ``checks`` are evaluated by the worker (§6) and already merged
    into ``result``. ``artifact_files`` retains staging locations for diagnostics;
    ``artifact_bytes`` holds the validated snapshot used for publication (source
    maps are canonical JSON). ``check_names`` are the collected CHECKS names.
    """

    result: BuildResult
    out_dir: Path
    artifact_files: Mapping[str, Path] = field(default_factory=dict[str, Path])
    #: Validated immutable bytes; publication must not reopen worker-writable paths.
    artifact_bytes: Mapping[str, bytes] | None = None
    source_map: Mapping[str, JSONValue] | None = None
    geometry_index_json: Mapping[str, JSONValue] | None = None
    tag_fingerprints: Mapping[str, TagDescriptor] = field(default_factory=dict[str, TagDescriptor])
    consumed_hc: Mapping[str, JSONValue] = field(default_factory=dict[str, "JSONValue"])
    check_names: tuple[str, ...] = ()
    worker_result: Mapping[str, JSONValue] = field(default_factory=dict[str, "JSONValue"])
    execution_identity: ExecutionIdentity | None = None

    def geometry_index(self) -> GeometryIndex:
        """The addressing GeometryIndex reconstructed from the worker output."""
        return geometry_index_from_json(self.geometry_index_json or {})


def _artifact_ref(kind: str, data: bytes) -> str:
    return f"artifact:{kind}:{sha256_bytes(data)}"


def geometry_index_from_json(data: Mapping[str, JSONValue]) -> GeometryIndex:
    """Rebuild the addressing :class:`GeometryIndex` from the worker's JSON form."""
    labels_raw = data.get("labels", [])
    labels: tuple[str, ...] = ()
    if isinstance(labels_raw, list):
        labels = tuple(str(label) for label in labels_raw)
    bindings_raw = data.get("bindings", {})
    bindings: dict[str, int] = {}
    if isinstance(bindings_raw, dict):
        for name, count in bindings_raw.items():
            if isinstance(count, int) and not isinstance(count, bool):
                bindings[name] = count
    tags_raw = data.get("tags", [])
    tags: frozenset[str] = frozenset()
    if isinstance(tags_raw, list):
        tags = frozenset(str(tag) for tag in tags_raw)
    return GeometryIndex(labels=labels, bindings=bindings, tags=tags)


def _require_dict(value: JSONValue, what: str) -> dict[str, JSONValue]:
    if not isinstance(value, dict):
        raise ValidationError(f"worker result: {what} must be an object", kind="evaluation")
    return value


def _checkpoints_from_worker(
    raw: JSONValue | None,
    last_good_ref: str | None,
    error: ErrorRecord | None,
) -> tuple[StatementCheckpoint, ...]:
    """Lift the worker's per-statement checkpoints onto the §8 record.

    The worker records index/span/bound/shapes (and, from this change, line +
    verbatim statement text). Publication mints at most one checkpoint blob —
    the last-good BRep of a failed build — and that ref is attached to the
    checkpoint whose line is ``error.built_through.line``. Intermediate stops
    carry ``artifact_ref=null``: mission rule 4 keeps per-statement BRep writes
    lazy, and inventing a ref the store does not hold would be a lie.
    """
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValidationError("worker result: checkpoints must be a list", kind="evaluation")
    parsed: list[StatementCheckpoint] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValidationError("worker result: checkpoints must be objects", kind="evaluation")
        record = dict(cast("dict[str, JSONValue]", item))
        span = record.get("span")
        if "line" not in record and isinstance(span, list) and span:
            first = span[0]
            if isinstance(first, int) and not isinstance(first, bool):
                record["line"] = first
        record.setdefault("statement", "")
        record.setdefault("artifact_ref", None)
        parsed.append(StatementCheckpoint.from_json(record))
    if last_good_ref is None or error is None or error.built_through is None:
        return tuple(parsed)
    line = error.built_through.line
    attached = False
    out: list[StatementCheckpoint] = []
    for checkpoint in parsed:
        if not attached and checkpoint.line == line:
            out.append(replace(checkpoint, artifact_ref=last_good_ref))
            attached = True
        else:
            out.append(checkpoint)
    if not attached and out:
        out[-1] = replace(out[-1], artifact_ref=last_good_ref)
    return tuple(out)


def import_hashes(request: BuildRequest) -> dict[str, str]:
    """§8 ``input_hashes.imports``: ``{declared path: sha256}`` of the frozen bytes.

    Byte-for-byte what it was before Stage 12: the RAW file bytes, keyed by the
    declared path, with nothing normalized before hashing. ``MESH_INGEST.md``
    §1.4 keeps that authority in the raw bytes deliberately — a re-exported scan
    with a new banner comment is a NEW build, because the harness cannot know
    the re-export is geometrically identical until it has parsed it, and the
    freeze runs before the parse. The geometry-identity hash
    (``mesh_canonical_hash``) is a second, separately named fact and never
    substitutes for this one in freeze, revalidation or staleness.
    """
    return {path: sha256_bytes(payload.data) for path, payload in sorted(request.imports.items())}


def stage_request_imports(
    request: BuildRequest, out_dir: Path, *, admission: InputAdmission | None = None
) -> tuple[dict[str, str], dict[str, str]]:
    """Convert every frozen import ONCE and stage it read-only for the worker.

    Returns ``({staged key: staged filename}, {staged key: refusal})``, where
    the key is the declared path for STEP and path-plus-unit for a mesh
    (:func:`~hephaestus.core.executor.imports.staged_key`). Conversion happens
    here, in the parent, outside the sandbox: the worker receives BRep or a
    canonical mesh blob in its own input area and never a project path
    (``INGEST.md`` §1). A payload the reader cannot handle is not raised — it
    joins ``import_errors`` so the build fails at the ``import_step`` /
    ``import_mesh`` statement that named it, with the full §8 error record.

    A mesh declared with no ``units=`` lands here as a payload with no declared
    unit, and is refused ``mesh_units_undeclared`` at its statement. It is a
    refusal and not a grammar error on purpose: the declaration is perfectly
    readable, it is the *file* that cannot be admitted without one (§1.3).
    """
    if admission is not None:
        policy = admission.policy
        if (
            len(request.imports) > policy.input_files
            or sum(len(p.data) for p in request.imports.values()) > policy.input_bytes
            or sum(
                max(1, len(p.units)) * (1 if p.kind == "step" else 2)
                for p in request.imports.values()
            )
            > policy.input_files
        ):
            raise SandboxDeniedError("OCI raw input aggregate exceeds staging limits")
    staged: dict[str, str] = {}
    errors: dict[str, str] = dict(request.import_errors)
    for path, payload in sorted(request.imports.items()):
        if path in errors:
            continue
        content_hash = sha256_bytes(payload.data)
        declared: tuple[str | None, ...] = payload.units or (None,)
        for unit in declared:
            key = staged_key(path, unit)
            if payload.kind != "step" and unit is None:
                from hephaestus.geom.mesh import MESH_UNITS

                # Composed through ``ImportResolutionError`` rather than as a
                # bare string so the §1.7 code lands in the message by the same
                # derivation every other mesh refusal uses: one code, one place
                # it comes from, and no message that can drift away from its
                # ``reason=`` (G12A.2).
                errors[key] = ImportResolutionError(
                    f"import {path!r}: units= is required on a mesh import — STL, PLY, "
                    "OBJ, OFF and XYZ carry no unit and the engine is millimetres "
                    f"throughout. Declare one of {', '.join(MESH_UNITS)} "
                    "(MESH_INGEST.md §1.3)",
                    reason="mesh_units_undeclared",
                    path=path,
                ).message
                continue
            try:
                file = stage_import(
                    payload.data,
                    path=path,
                    content_hash=content_hash,
                    out_dir=out_dir,
                    kind=payload.kind,
                    units=unit,
                    admission=admission,
                )
            except ImportResolutionError as exc:
                errors[key] = exc.message
                continue
            staged[key] = file.name
    return staged, errors


def run_build(
    request: BuildRequest,
    *,
    backend: ExecBackend,
    out_dir: Path,
    baseline: FingerprintBaseline | None = None,
    rlimits: Rlimits = DEFAULT_RLIMITS,
    native_toolchain_hash: Callable[[], str] | None = None,
) -> UnpublishedBuild:
    """Run one build through ``backend`` and assemble the BuildResult.

    ``baseline`` is the prior successful-current build's tag fingerprints
    (plus its artifact ref); when given and the build succeeds, §5.3
    ``tag_descriptor_changed`` warnings are appended. Secure callers must
    have verified ``backend.probe()`` — an unavailable backend fails closed
    here with ``sandbox_denied``.
    """
    report = backend.probe()
    if not report.available:
        raise SandboxDeniedError(
            f"execution backend {report.backend!r} unavailable: {report.reason}"
        )
    identity = backend_execution_identity(backend)
    out_dir.mkdir(parents=True, exist_ok=True)
    policy = getattr(backend, "storage_policy", None)
    admission = InputAdmission(policy) if isinstance(policy, StoragePolicy) else None
    staged, import_errors = stage_request_imports(request, out_dir, admission=admission)
    job: dict[str, JSONValue] = {
        "part": request.part,
        "script": request.script,
        "globals_source": request.globals_source,
        "part_overrides": {k: v for k, v in request.part_overrides.items()},
        "project_overrides": {k: v for k, v in request.project_overrides.items()},
        # Backends expose the host staging directory as the worker cwd. Keep
        # the protocol path relative so it is valid for native and image-based
        # backends alike.
        "out_dir": ".",
        "origin": request.origin,
        "mode": "build",
        "imports": cast("dict[str, JSONValue]", dict(staged)),
        "import_errors": cast("dict[str, JSONValue]", dict(import_errors)),
    }
    payload = json.dumps(job).encode("utf-8")
    spec = SandboxSpec(
        worker_args=worker_args(),
        ro_binds=(),
        rw_out_dir=out_dir,
        rlimits=rlimits,
        wall_clock_s=request.wall_clock_s,
        input_files=tuple(sorted(admission.names)) if admission else (),
    )
    outcome = backend.execute(spec, payload)
    if outcome.execution_identity != identity or backend_execution_identity(backend) != identity:
        raise SandboxDeniedError("build outcome execution identity missing or changed")
    if outcome.timed_out:
        raise ValidationError(
            f"build worker exceeded the wall clock ({request.wall_clock_s:g}s)",
            kind="evaluation",
        )
    if outcome.exit_code != 0:
        stderr = outcome.stderr.decode("utf-8", errors="replace").strip()
        raise ValidationError(
            f"build worker exited with code {outcome.exit_code}: {stderr[-2000:]}",
            kind="evaluation",
        )
    try:
        parsed: object = json.loads(outcome.stdout.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValidationError(
            f"build worker produced invalid result JSON: {exc}", kind="evaluation"
        ) from exc
    if not isinstance(parsed, dict):
        raise ValidationError("build worker result must be a JSON object", kind="evaluation")
    worker_result = cast("dict[str, JSONValue]", parsed)
    return assemble_build(
        request,
        worker_result,
        out_dir=out_dir,
        baseline=baseline,
        execution_identity=identity,
        native_toolchain_hash=native_toolchain_hash,
    )


def assemble_build(
    request: BuildRequest,
    worker_result: Mapping[str, JSONValue],
    *,
    out_dir: Path,
    baseline: FingerprintBaseline | None = None,
    execution_identity: ExecutionIdentity | None = None,
    native_toolchain_hash: Callable[[], str] | None = None,
) -> UnpublishedBuild:
    """Assemble using host-owned identity, never a worker-supplied fingerprint.

    Omitting identity retains native toolchain hashing for native callers.
    OCI callers must use the identity carried by their trusted backend outcome.
    """
    status_raw = worker_result.get("status")
    if status_raw not in ("ok", "failed"):
        raise ValidationError(f"worker result: invalid status {status_raw!r}", kind="evaluation")
    status: Literal["ok", "failed"] = "ok" if status_raw == "ok" else "failed"

    consumed = _require_dict(worker_result.get("consumed_hc", {}), "consumed_hc")
    declaration = _require_dict(worker_result.get("params_declaration", {}), "params_declaration")
    effective_raw = _require_dict(worker_result.get("effective_params", {}), "effective_params")
    effective: dict[str, int | float] = {}
    for name, value in effective_raw.items():
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValidationError(
                f"worker result: effective param {name!r} must be a number",
                kind="evaluation",
            )
        effective[name] = value
    project_effective_raw = _require_dict(
        worker_result.get("project_effective_params", {}), "project_effective_params"
    )
    project_effective: dict[str, int | float] = {}
    for name, value in project_effective_raw.items():
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValidationError(
                f"worker result: project param {name!r} must be a number",
                kind="evaluation",
            )
        project_effective[name] = value

    artifacts = _require_dict(worker_result.get("artifacts", {}), "artifacts")
    if any(
        key not in ARTIFACT_NAMES or value != ARTIFACT_NAMES[key]
        for key, value in artifacts.items()
    ):
        raise ValidationError("worker artifact schema/filename mismatch", kind="evaluation")
    expected_keys = {"build", "source_map"} if status == "ok" else {"last_good"}
    if (status == "ok" and set(artifacts) != expected_keys) or not set(artifacts) <= expected_keys:
        raise ValidationError("worker artifact set is incomplete or invalid", kind="evaluation")
    validated = {key: read_artifact(out_dir, ARTIFACT_NAMES[key]) for key in artifacts}
    source_map_raw = worker_result.get("source_map")
    if "source_map" in validated:
        try:
            disk_map = json.loads(validated["source_map"])
        except (ValueError, UnicodeError) as exc:
            raise ValidationError("worker source map is malformed", kind="evaluation") from exc
        if not isinstance(source_map_raw, dict) or canonical_json(disk_map) != canonical_json(
            source_map_raw
        ):
            raise ValidationError("worker source map disagrees with artifact", kind="evaluation")

    input_hashes = InputHashes(
        script=hash_text(request.script),
        hc_dependencies=consumed_hc_hash(consumed),
        part_params=sha256_canonical_json(declaration),
        effective_params=effective_params_hash(effective),
        toolchain=(
            (native_toolchain_hash or toolchain_hash)()
            if execution_identity is None
            else execution_identity.toolchain_hash
        ),
        imports=import_hashes(request),
    )
    audit_hashes = AuditHashes(
        globals_source=hash_text(request.globals_source or ""),
        project_param_state=effective_params_hash(project_effective),
    )

    artifact_files: dict[str, Path] = {}
    artifact_bytes: dict[str, bytes] = {}
    artifact_ref: str | None = None
    source_map_ref: str | None = None
    last_good_ref: str | None = None
    build_file = artifacts.get("build")
    if isinstance(build_file, str):
        path = out_dir / build_file
        artifact_ref = _artifact_ref("build", validated["build"])
        artifact_files[artifact_ref] = path
        artifact_bytes[artifact_ref] = validated["build"]
    last_good_file = artifacts.get("last_good")
    if isinstance(last_good_file, str):
        path = out_dir / last_good_file
        last_good_ref = _artifact_ref("build-checkpoint", validated["last_good"])
        artifact_files[last_good_ref] = path
        artifact_bytes[last_good_ref] = validated["last_good"]

    source_map: dict[str, JSONValue] | None = None
    if isinstance(source_map_raw, dict):
        source_map = source_map_raw
        source_map_ref = f"artifact:source-map:{sha256_canonical_json(source_map)}"
        source_map_file = artifacts.get("source_map")
        if isinstance(source_map_file, str):
            artifact_files[source_map_ref] = out_dir / source_map_file
            artifact_bytes[source_map_ref] = canonical_json(source_map).encode("utf-8")

    metrics_raw = worker_result.get("metrics")
    metrics: Metrics | None = None
    if isinstance(metrics_raw, dict):
        metrics = Metrics.from_json(metrics_raw)

    error_raw = worker_result.get("error")
    error: ErrorRecord | None = None
    if isinstance(error_raw, dict):
        patched: dict[str, JSONValue] = dict(error_raw)
        patched["last_good_artifact_ref"] = last_good_ref
        error = ErrorRecord.from_json(patched)

    geometries_raw = worker_result.get("geometries", [])
    geometries: list[GeometryEntry] = []
    if isinstance(geometries_raw, list):
        for item in geometries_raw:
            if isinstance(item, dict):
                geometries.append(GeometryEntry.from_json(item))

    warnings: list[Warning] = []
    warnings_raw = worker_result.get("warnings", [])
    if isinstance(warnings_raw, list):
        for item in warnings_raw:
            if isinstance(item, dict):
                warnings.append(Warning.from_json(item))

    fingerprints_raw = _require_dict(worker_result.get("tag_fingerprints", {}), "tag_fingerprints")
    descriptors = descriptors_from_json(fingerprints_raw)
    if status == "ok":
        warnings.extend(compare(descriptors, baseline))

    check_names_raw = worker_result.get("check_names", [])
    check_names: tuple[str, ...] = ()
    if isinstance(check_names_raw, list):
        check_names = tuple(str(name) for name in check_names_raw)

    # §6: the worker evaluates part-scope CHECKS against the live geometry
    # (the predicates only exist in its namespace); carry the results into
    # the §8 record. Absent key (older workers / fakes) => no checks ran.
    checks_raw = worker_result.get("checks", {})
    checks: dict[str, CheckResult] = {}
    if isinstance(checks_raw, dict):
        for name, item in checks_raw.items():
            if isinstance(item, dict):
                checks[name] = CheckResult.from_json(item)

    result = BuildResult(
        part=request.part,
        status=status,
        current=False,
        artifact_ref=artifact_ref,
        project_snapshot_ref=None,
        input_hashes=input_hashes,
        audit_hashes=audit_hashes,
        metrics=metrics,
        checks=checks,
        geometries=tuple(geometries),
        params=effective,
        source_map_ref=source_map_ref,
        warnings=tuple(warnings),
        error=error,
        metadata={
            **{
                str(k): str(v)
                for k, v in cast(
                    "dict[str, object]",
                    worker_result.get("metadata") or {},
                ).items()
                if isinstance(v, str) and k != IDENTITY_METADATA_KEY
            },
            **({IDENTITY_METADATA_KEY: execution_identity.canonical} if execution_identity else {}),
        },
        checkpoints=_checkpoints_from_worker(
            worker_result.get("checkpoints"), last_good_ref, error
        ),
    )
    geometry_index_raw = worker_result.get("geometry_index")
    geometry_index_json = geometry_index_raw if isinstance(geometry_index_raw, dict) else None
    return UnpublishedBuild(
        result=result,
        out_dir=out_dir,
        artifact_files=artifact_files,
        artifact_bytes=artifact_bytes,
        source_map=source_map,
        geometry_index_json=geometry_index_json,
        tag_fingerprints=descriptors,
        consumed_hc=consumed,
        check_names=check_names,
        worker_result=dict(worker_result),
        execution_identity=execution_identity,
    )
