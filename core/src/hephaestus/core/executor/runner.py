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
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal, cast

from hephaestus.core.addressing import GeometryIndex
from hephaestus.core.errors import SandboxDeniedError, ValidationError
from hephaestus.core.executor.fingerprint import (
    FingerprintBaseline,
    TagDescriptor,
    compare,
    descriptors_from_json,
)
from hephaestus.core.executor.imports import (
    ImportPayload,
    ImportResolutionError,
    stage_import,
    staged_key,
)
from hephaestus.core.executor.sandbox.base import ExecBackend, Rlimits, SandboxSpec
from hephaestus.core.executor.sandbox.bwrap import interpreter_ro_binds
from hephaestus.core.hashing import (
    consumed_hc_hash,
    effective_params_hash,
    hash_text,
    sha256_bytes,
    sha256_canonical_json,
    toolchain_hash,
)
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

#: Default worker resource limits (bounded, generous for CAD kernels).
#: nproc must exceed the invoking user's live kernel task ucount or bwrap's
#: userns clone fails EAGAIN (see sandbox/bwrap.py); 4096 is the standard
#: fork-bomb cap that clears real desktop task counts.
DEFAULT_RLIMITS = Rlimits(
    cpu_seconds=120,
    address_space_bytes=6 * 1024**3,
    nproc=4096,
)
DEFAULT_WALL_CLOCK_S = 300.0

BuildOrigin = Literal["local", "registry"]


def worker_command() -> tuple[str, ...]:
    """argv of the build worker: this interpreter running the worker module."""
    return (sys.executable, "-m", "hephaestus.core.executor.worker")


def worker_ro_binds() -> tuple[Path, ...]:
    """Read-only binds a sandboxed worker needs to start.

    The interpreter roots (venv prefix + the install root its symlinks target)
    plus the import roots of the ``hephaestus``/``opstore`` packages —
    editable installs resolve through ``.pth`` files to source trees OUTSIDE
    the venv prefix, which must be identity-bound too or the worker dies with
    ``ModuleNotFoundError`` inside the sandbox. Non-editable installs resolve
    under the venv prefix and dedup away.
    """
    import hephaestus.core as _core_pkg

    import opstore as _opstore_pkg

    binds: list[Path] = list(interpreter_ro_binds())
    for module in (_core_pkg, _opstore_pkg):
        file = getattr(module, "__file__", None)
        if not isinstance(file, str):  # pragma: no cover - namespace edge
            continue
        root = Path(file).resolve().parents[len(module.__name__.split("."))]
        if root not in binds:
            binds.append(root)
    return tuple(binds)


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
    wall_clock_s: float = DEFAULT_WALL_CLOCK_S
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
    into ``result``. ``artifact_files`` maps each deterministic content ref to
    the file under ``out_dir`` whose bytes hash to it; ``check_names`` are the
    collected CHECKS names.
    """

    result: BuildResult
    out_dir: Path
    artifact_files: Mapping[str, Path] = field(default_factory=dict[str, Path])
    source_map: Mapping[str, JSONValue] | None = None
    geometry_index_json: Mapping[str, JSONValue] | None = None
    tag_fingerprints: Mapping[str, TagDescriptor] = field(default_factory=dict[str, TagDescriptor])
    consumed_hc: Mapping[str, JSONValue] = field(default_factory=dict[str, "JSONValue"])
    check_names: tuple[str, ...] = ()
    worker_result: Mapping[str, JSONValue] = field(default_factory=dict[str, "JSONValue"])

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
    request: BuildRequest, out_dir: Path
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
    from hephaestus.geom.mesh import MESH_UNITS

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
    out_dir.mkdir(parents=True, exist_ok=True)
    staged, import_errors = stage_request_imports(request, out_dir)
    job: dict[str, JSONValue] = {
        "part": request.part,
        "script": request.script,
        "globals_source": request.globals_source,
        "part_overrides": {k: v for k, v in request.part_overrides.items()},
        "project_overrides": {k: v for k, v in request.project_overrides.items()},
        "out_dir": str(out_dir),
        "origin": request.origin,
        "mode": "build",
        "imports": cast("dict[str, JSONValue]", dict(staged)),
        "import_errors": cast("dict[str, JSONValue]", dict(import_errors)),
    }
    payload = json.dumps(job).encode("utf-8")
    spec = SandboxSpec(
        worker_cmd=worker_command(),
        ro_binds=worker_ro_binds(),
        rw_out_dir=out_dir,
        rlimits=rlimits,
        wall_clock_s=request.wall_clock_s,
    )
    outcome = backend.execute(spec, payload)
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
    return assemble_build(request, worker_result, out_dir=out_dir, baseline=baseline)


def assemble_build(
    request: BuildRequest,
    worker_result: Mapping[str, JSONValue],
    *,
    out_dir: Path,
    baseline: FingerprintBaseline | None = None,
) -> UnpublishedBuild:
    """Turn a worker result record into an :class:`UnpublishedBuild`."""
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

    input_hashes = InputHashes(
        script=hash_text(request.script),
        hc_dependencies=consumed_hc_hash(consumed),
        part_params=sha256_canonical_json(declaration),
        effective_params=effective_params_hash(effective),
        toolchain=toolchain_hash(),
        imports=import_hashes(request),
    )
    audit_hashes = AuditHashes(
        globals_source=hash_text(request.globals_source or ""),
        project_param_state=effective_params_hash(project_effective),
    )

    artifacts = _require_dict(worker_result.get("artifacts", {}), "artifacts")
    artifact_files: dict[str, Path] = {}
    artifact_ref: str | None = None
    source_map_ref: str | None = None
    last_good_ref: str | None = None
    build_file = artifacts.get("build")
    if isinstance(build_file, str):
        path = out_dir / build_file
        artifact_ref = _artifact_ref("build", path.read_bytes())
        artifact_files[artifact_ref] = path
    last_good_file = artifacts.get("last_good")
    if isinstance(last_good_file, str):
        path = out_dir / last_good_file
        last_good_ref = _artifact_ref("build-checkpoint", path.read_bytes())
        artifact_files[last_good_ref] = path

    source_map_raw = worker_result.get("source_map")
    source_map: dict[str, JSONValue] | None = None
    if isinstance(source_map_raw, dict):
        source_map = source_map_raw
        source_map_ref = f"artifact:source-map:{sha256_canonical_json(source_map)}"
        source_map_file = artifacts.get("source_map")
        if isinstance(source_map_file, str):
            artifact_files[source_map_ref] = out_dir / source_map_file

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
            str(k): str(v)
            for k, v in cast(
                "dict[str, object]",
                worker_result.get("metadata") or {},
            ).items()
            if isinstance(v, str)
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
        source_map=source_map,
        geometry_index_json=geometry_index_json,
        tag_fingerprints=descriptors,
        consumed_hc=consumed,
        check_names=check_names,
        worker_result=dict(worker_result),
    )
