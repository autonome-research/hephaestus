"""Core-backed CAD operations behind ``py.tool_dispatch`` (the whole tool surface).

The dispatcher (:mod:`hephaestus.agent_bridge.dispatch`) authorizes a tool and
routes the *file-CRUD* family through
:class:`~hephaestus.core.project_store.store.ProjectStore`. Everything that needs
geometry, parameters, checks, artifacts or exports is factored here behind one
:class:`CadOps` seam the dispatcher holds optionally: when absent those tools
report ``not_implemented`` (the Stage 2A behaviour), when present the real engine
runs.

What lives here, and the core machinery each op stands on:

``build_part``       freeze → sandboxed build → hc-projection sync → publish
                     (mirrors ``hephaestus.core.cli._build_and_publish``).
                     Persisted overrides (see ``set_params``) are ordinary build
                     inputs; only *transient* tool-argument overrides make a
                     build a preview.
``inspect_part``     ``core.render.inspect`` with the full tool-schema result
                     (channels/modes, mask legend inline-or-ref paging, selection
                     bundles) and every image checked against the §5 image
                     budgets by a bounded header parse before it is handed on.
``set_params``       a durable override document per scope behind an opstore CAS
                     pointer, bounds-validated against the *declaration* the
                     sandboxed worker reports, all-or-nothing, journaled, and
                     idempotent on the trusted invocation id. Project scope
                     re-evaluates ``globals.py`` in the sandbox and advances the
                     audit revision, so ``stale_parts`` is real dependency
                     tracking (``Projections.apply_hc_state``).
``edit_globals``     CAS write of ``globals.py`` with the candidate validated in
                     the *sandbox* against the persisted overrides — a removed
                     parameter or a bound tightened around a live override is the
                     discriminated ``invalid_overrides`` failure.
project checks       ``core.checks.engine.CheckSet`` generations: create is
                     no-replace from a safe template, edits validate in the check
                     sandbox, listing pages an immutable frozen bundle manifest.
``measure``          ``core.checks.facade`` over artifact-reloaded geometry, with
                     single-part / coherent-snapshot / explicit-ref resolution.
``run_checks``       part scope re-executes the part's ``CHECKS`` through the
                     worker (published as a *preview*, so nothing becomes
                     current); project scope freezes the authorized bundle and
                     fails closed on an invalid generation.
``read_artifact``    UTF-8-boundary-safe byte-cursor paging over model-readable
                     artifacts; binary artifacts return metadata only.
``export_part``      the §7 export contract: a WAL row freezes the source
                     artifact on first sight and every retry reuses it,
                     create-only targets beneath ``.heph/exports/`` written
                     through a directory-descriptor walk with no-follow/beneath
                     semantics and ``O_EXCL``, GC-root pinning, and
                     source-input/exported-byte provenance hashes.

Every mutation is idempotent on the trusted invocation id through opstore
opkeys; a committed retry replays its recorded outcome and a same-id/
different-payload presentation is a hard mismatch.
"""

from __future__ import annotations

import base64
import contextlib
import io
import json
import os
import shutil
import struct
import tempfile
import uuid
import zipfile
from collections.abc import Generator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Final, cast

from hephaestus.core.checks.engine import CheckSet, CheckSetState, load_check_module, run_bundle
from hephaestus.core.checks.facade import GeometrySource, project_measurement
from hephaestus.core.errors import (
    AddressingError,
    HephaestusError,
    InvalidCheckGenerationError,
    ValidationError,
)
from hephaestus.core.executor.artifact_geometry import artifact_source, load_brep_shape
from hephaestus.core.executor.runner import BuildRequest, UnpublishedBuild, run_build
from hephaestus.core.executor.sandbox.base import ExecBackend
from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend
from hephaestus.core.params import Param, merge_overrides
from hephaestus.core.project_store.layout import ProjectLayout
from hephaestus.core.project_store.projections import (
    PROJECT_SNAPSHOT_REF_PREFIX,
    SnapshotRejectedError,
)
from hephaestus.core.project_store.publication import Publisher
from hephaestus.core.project_store.store import (
    artifact_ref as make_artifact_ref,
)
from hephaestus.core.project_store.store import (
    blob_hash_of_ref,
)
from hephaestus.core.render.inspect import RenderProject, inspect_part, prepare_render_bundle
from hephaestus.core.types import BuildResult
from opstore.types import JSONValue

from opstore import (
    Fresh,
    LeaseHeldError,
    OpStore,
    PendingRecovery,
    Replay,
    canonical_json,
    sha256_bytes,
    sha256_canonical_json,
)

from .limits import MAX_IMAGES_PER_RESULT, parse_image_header

__all__ = [
    "BINARY_ARTIFACT_KINDS",
    "CHECK_DESCRIPTION_SENTINEL",
    "CHECK_TEMPLATE_HEADER",
    "EXPORT_FORMATS",
    "PART_PARAMS_POINTER_PREFIX",
    "PROJECT_PARAMS_POINTER",
    "SYNC_PART",
    "TEXT_ARTIFACT_MIME",
    "CadOpError",
    "CadOps",
    "ParamConflict",
    "ParamProbe",
    "ParamState",
    "ParamStore",
    "check_template",
    "params_pointer",
]

#: Minimal probe part used to evaluate ``globals.py`` alone in the sandbox.
SYNC_PART: Final[str] = "__hc_sync__"
_SYNC_SCRIPT: Final[str] = "part.geometry = Box(1.0, 1.0, 1.0)\n"

#: CAS pointer holding a part's persisted parameter-override document.
PART_PARAMS_POINTER_PREFIX: Final[str] = "part-params:"
#: CAS pointer holding the project's persisted parameter-override document.
PROJECT_PARAMS_POINTER: Final[str] = "project-params"

#: Artifact kinds whose blobs are binary: ``read_artifact`` returns metadata only.
BINARY_ARTIFACT_KINDS: Final[frozenset[str]] = frozenset(
    {
        "build",
        "build-checkpoint",
        "render",
        "export",
        "selection-solid",
        "selection-face",
        "selection-edge",
        "selection-preview",
        "gltf",
    }
)

#: Artifact kinds with a known model-readable mime type.
TEXT_ARTIFACT_MIME: Final[dict[str, str]] = {
    "part-snapshot": "text/x-python",
    "mask-legend": "application/json",
    "source-map": "application/json",
    "check-bundle": "application/json",
    "check-diagnostics": "application/json",
    "project-snapshot": "application/json",
    "selection-table": "application/json",
    "snapshot-issues": "application/json",
    "build-result": "application/json",
    "check-report": "application/json",
}

#: The safe cross-part check template (``create_project_check``). The sentinel is
#: substituted, not ``str.format``-ed, because the body itself contains braces.
CHECK_DESCRIPTION_SENTINEL: Final[str] = "__DESCRIPTION__"
CHECK_TEMPLATE_HEADER: Final[str] = (
    f"# Project check{CHECK_DESCRIPTION_SENTINEL}\n"
    "#\n"
    "# Checks receive the measurement facade `m` and the pure `approx` helper\n"
    '# only. Address another part as "<part>/<selector>".\n'
    "\n"
    "CHECKS = {\n"
    '    "placeholder": lambda m: True,\n'
    "}\n"
)


def check_template(description: str) -> str:
    """The initial script ``create_project_check`` installs (no-replace)."""
    suffix = f": {description}" if description else ""
    return CHECK_TEMPLATE_HEADER.replace(CHECK_DESCRIPTION_SENTINEL, suffix)


#: Export formats and the file extension each produces.
EXPORT_FORMATS: Final[dict[str, str]] = {
    "step": "step",
    "dxf": "dxf",
    "svg": "svg",
    "gltf": "glb",
    "3mf": "3mf",
    "stl": "stl",
}

_MEASURE_UNITS: Final[dict[str, str]] = {
    "interference": "mm^3",
    "clearance": "mm",
    "distance": "mm",
    "bbox": "mm",
    "volume": "mm^3",
    "mass": "g",
    "sealed": "bool",
    "genus": "count",
}

_BINARY_MEASURE_KINDS: Final[frozenset[str]] = frozenset({"interference", "clearance", "distance"})

#: ``summary`` cap for ``list_project_checks`` items (tool_schema: 512 UTF-8 bytes).
_SUMMARY_MAX_BYTES: Final[int] = 512

_EXPORTS_TABLE: Final[str] = "tp_exports"
_CREATE_EXPORTS_TABLE: Final[str] = f"""
CREATE TABLE IF NOT EXISTS {_EXPORTS_TABLE}(
  op_id TEXT PRIMARY KEY,
  payload_hash TEXT NOT NULL,
  part TEXT NOT NULL,
  format TEXT NOT NULL,
  layout TEXT NOT NULL,
  source_artifact_ref TEXT NOT NULL,
  requested_target TEXT,
  rel_path TEXT,
  export_blob TEXT,
  source_input_hashes TEXT,
  state TEXT NOT NULL)
"""


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


def _diff_line(old_str: str, new_str: str) -> str:
    """A minimal one-hunk diff rendering of an exact-match replacement."""
    return f"-{old_str.rstrip(chr(10))}\n+{new_str.rstrip(chr(10))}"


def _globals_failure_kind(error_type: str | None, message: str) -> str:
    """Map a sandboxed ``globals.py`` failure onto the edit_globals ``kind`` set."""
    if error_type == "ParamOutOfBoundsError":
        return "invalid_overrides"
    if error_type == "SyntaxError":
        return "syntax"
    if error_type == "ValidationError":
        lowered = message.lower()
        if "unknown parameter" in lowered or "declares no params" in lowered:
            return "invalid_overrides"
        if "sandbox" in lowered:
            return "sandbox"
        return "contract"
    if error_type == "SandboxDeniedError":
        return "sandbox"
    return "evaluation"


def _recorded_ref(response: str | None, key: str, fallback: str) -> str:
    """A field of a WAL-recorded ``intended_outcome`` (used on replay)."""
    if response is None:  # tombstone replay: only the terminal state survives
        return fallback
    try:
        decoded = cast("Mapping[str, JSONValue]", json.loads(response))
    except (ValueError, TypeError):  # pragma: no cover - responses are our own JSON
        return fallback
    value = decoded.get(key)
    return value if isinstance(value, str) else fallback


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
            return self.read(scope, name), _recorded_ref(
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
# probe results


@dataclass(frozen=True)
class ParamProbe:
    """A sandboxed probe of one scope: the declaration, plus any failure."""

    declaration: Mapping[str, Param]
    effective: Mapping[str, int | float]
    hc_state: Mapping[str, JSONValue]
    error_type: str | None = None
    error_message: str = ""

    @property
    def ok(self) -> bool:
        return self.error_type is None


def _params_from_declaration(raw: Mapping[str, JSONValue]) -> dict[str, Param]:
    """Rebuild ``{name: Param}`` from the worker's declaration JSON."""
    out: dict[str, Param] = {}
    for name, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        decl = cast("Mapping[str, JSONValue]", entry)
        default = decl.get("default")
        minimum = decl.get("min")
        maximum = decl.get("max")
        bounds = (default, minimum, maximum)
        if any(isinstance(v, bool) or not isinstance(v, int | float) for v in bounds):
            continue
        doc = decl.get("doc")
        raw_step = decl.get("step")
        numeric_step = isinstance(raw_step, int | float) and not isinstance(raw_step, bool)
        out[name] = Param(
            default=cast("int | float", default),
            min=cast("int | float", minimum),
            max=cast("int | float", maximum),
            doc=doc if isinstance(doc, str) else "",
            step=cast("int | float", raw_step) if numeric_step else None,
        )
    return out


def _numeric_map(raw: JSONValue | None) -> dict[str, int | float]:
    out: dict[str, int | float] = {}
    if not isinstance(raw, dict):
        return out
    for name, value in cast("Mapping[str, JSONValue]", raw).items():
        if isinstance(value, bool) or not isinstance(value, int | float):
            continue
        out[name] = value
    return out


def _json_map(raw: JSONValue | None) -> dict[str, JSONValue]:
    if not isinstance(raw, dict):
        return {}
    return dict(cast("Mapping[str, JSONValue]", raw))


# --------------------------------------------------------------------------
# path confinement for exports


def _validate_relative_target(target: str) -> PurePosixPath:
    """A create-only relative filename beneath ``.heph/exports/`` (else refuse)."""
    if not target or target != target.strip():
        raise CadOpError("invalid_target", "target must be a non-empty relative path")
    if "\\" in target or "\x00" in target:
        raise CadOpError("invalid_target", f"target {target!r} contains a rejected character")
    candidate = PurePosixPath(target)
    if candidate.is_absolute():
        raise CadOpError("invalid_target", f"target {target!r} must be relative")
    parts = candidate.parts
    if not parts or any(part in (".", "..") for part in parts):
        raise CadOpError("invalid_target", f"target {target!r} must not traverse")
    return candidate


def _create_confined(exports_dir: Path, rel: PurePosixPath, data: bytes) -> None:
    """Atomically create ``exports_dir/rel`` with no-follow/beneath semantics.

    Confinement is rechecked *at operation time* by walking one directory
    descriptor per component with ``O_NOFOLLOW`` (an ``openat2
    RESOLVE_BENEATH|RESOLVE_NO_SYMLINKS``-class recheck): a racing parent symlink
    fails the walk instead of redirecting the write. Creation itself is
    ``O_CREAT|O_EXCL`` — a pre-existing target is never overwritten.
    """
    exports_dir.mkdir(parents=True, exist_ok=True)
    dir_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
    fd = os.open(exports_dir, dir_flags)
    opened: list[int] = [fd]
    try:
        for component in rel.parts[:-1]:
            with contextlib.suppress(FileExistsError):
                os.mkdir(component, 0o755, dir_fd=fd)
            try:
                nxt = os.open(component, dir_flags | os.O_NOFOLLOW, dir_fd=fd)
            except OSError as exc:
                raise CadOpError(
                    "path_confinement",
                    f"export path component {component!r} is not a real directory beneath "
                    f"{exports_dir} ({exc.strerror})",
                ) from exc
            opened.append(nxt)
            fd = nxt
        leaf = rel.parts[-1]
        try:
            handle = os.open(
                leaf,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o644,
                dir_fd=fd,
            )
        except FileExistsError as exc:
            raise CadOpError(
                "target_exists",
                f"export target {rel.as_posix()!r} already exists and is never overwritten",
            ) from exc
        except OSError as exc:
            raise CadOpError(
                "path_confinement",
                f"export target {rel.as_posix()!r} could not be created ({exc.strerror})",
            ) from exc
        try:
            os.write(handle, data)
            os.fsync(handle)
        finally:
            os.close(handle)
        os.fsync(fd)
    finally:
        for handle in reversed(opened):
            os.close(handle)


# --------------------------------------------------------------------------
# format conversion


_Vertices = list[tuple[float, float, float]]
_Triangles = list[tuple[int, int, int]]


def _binary_stl_mesh(data: bytes) -> tuple[_Vertices, _Triangles]:
    """Vertices + triangles decoded from binary STL (stdlib only)."""
    if len(data) < 84:
        raise CadOpError("export_failed", "binary STL payload is truncated")
    (count,) = struct.unpack_from("<I", data, 80)
    expected = 84 + count * 50
    if len(data) < expected:
        raise CadOpError("export_failed", "binary STL triangle count exceeds payload")
    index: dict[tuple[float, float, float], int] = {}
    vertices: _Vertices = []
    triangles: _Triangles = []
    offset = 84
    for _ in range(count):
        raw = struct.unpack_from("<12fH", data, offset)
        offset += 50
        corners: list[int] = []
        for i in range(3):
            vertex = (float(raw[3 + i * 3]), float(raw[4 + i * 3]), float(raw[5 + i * 3]))
            position = index.get(vertex)
            if position is None:
                position = len(vertices)
                index[vertex] = position
                vertices.append(vertex)
            corners.append(position)
        triangles.append((corners[0], corners[1], corners[2]))
    return vertices, triangles


def _write_3mf(
    vertices: Sequence[tuple[float, float, float]], triangles: Sequence[tuple[int, int, int]]
) -> bytes:
    """A minimal, deterministic 3MF core-spec package (stdlib zipfile only)."""
    from xml.sax.saxutils import escape

    verts = "".join(f'<vertex x="{x:.6f}" y="{y:.6f}" z="{z:.6f}"/>' for x, y, z in vertices)
    tris = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in triangles)
    model = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<model unit="millimeter" xml:lang="en-US" '
        'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
        f'<metadata name="Application">{escape("Hephaestus")}</metadata>'
        "<resources>"
        '<object id="1" type="model"><mesh>'
        f"<vertices>{verts}</vertices><triangles>{tris}</triangles>"
        "</mesh></object>"
        "</resources>"
        '<build><item objectid="1"/></build>'
        "</model>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
        'relationships+xml"/>'
        '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-'
        '3dmodel+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/'
        '3dmanufacturing/2013/01/3dmodel"/>'
        "</Relationships>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, payload in (
            ("[Content_Types].xml", content_types),
            ("_rels/.rels", rels),
            ("3D/3dmodel.model", model),
        ):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, payload)
    return buffer.getvalue()


def _export_bytes(shape: object, fmt: str, scratch: Path) -> bytes:
    """Render one export format's bytes from a reloaded BRep shape.

    build123d's exporter signatures are generic over an unparameterized ``Shape``,
    so the interop surface is deliberately confined to this function's explicitly
    ``Any``-typed locals rather than leaking partially-unknown types outward.
    STEP / STL / GLB come from ``exporters3d``; DXF / SVG project the solid with
    the hidden-line ``Drawing`` first (``as_built`` = the +Z profile); 3MF is
    written from the binary-STL mesh by :func:`_write_3mf` (no extra dependency —
    trimesh's 3MF writer needs ``lxml``, which is not in the dependency set).
    """
    import importlib

    e3: Any = importlib.import_module("build123d.exporters3d")
    e2: Any = importlib.import_module("build123d.exporters")
    typed: Any = shape
    target = scratch / f"export.{EXPORT_FORMATS[fmt]}"
    if fmt == "step":
        e3.export_step(typed, target)
    elif fmt == "stl":
        e3.export_stl(typed, target, ascii_format=False)
    elif fmt == "gltf":
        e3.export_gltf(typed, target, binary=True)
    elif fmt in ("dxf", "svg"):
        drawing: Any = e2.Drawing(typed, look_from=(0, 0, 1), look_up=(0, 1, 0), with_hidden=False)
        exporter: Any = e2.ExportDXF() if fmt == "dxf" else e2.ExportSVG()
        exporter.add_shape(drawing.visible_lines)
        exporter.write(target)
    elif fmt == "3mf":
        stl_path = scratch / "mesh.stl"
        e3.export_stl(typed, stl_path, ascii_format=False)
        vertices, triangles = _binary_stl_mesh(stl_path.read_bytes())
        return _write_3mf(vertices, triangles)
    else:  # pragma: no cover - schema-constrained enum
        raise CadOpError("invalid_params", f"unsupported export format {fmt!r}")
    if not target.is_file():
        raise CadOpError("export_failed", f"{fmt} exporter produced no output")
    return target.read_bytes()


# --------------------------------------------------------------------------
# the facade


class CadOps:
    """Core-backed operations for one project's layout, opstore and backend."""

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
        self._store.db.conn.execute(_CREATE_EXPORTS_TABLE)

    # -- shared helpers ----------------------------------------------------

    @property
    def layout(self) -> ProjectLayout:
        return self._layout

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
    ) -> UnpublishedBuild:
        request = BuildRequest(
            part=part,
            script=script,
            globals_source=globals_source,
            part_overrides=dict(part_overrides),
            project_overrides=dict(project_overrides),
            origin="local",
        )
        return run_build(
            request,
            backend=self._backend,
            out_dir=out_dir,
            baseline=cast("Any", baseline),
        )

    # -- build -------------------------------------------------------------

    def build_part(
        self,
        name: str,
        params: Mapping[str, Any] | None = None,
        *,
        op_id: str | None = None,
    ) -> dict[str, Any]:
        """Build + publish ``name``; return the BuildResult projection.

        Transient ``params`` overrides make the build a preview (never current),
        matching the engine's request-local override semantics. Persisted
        ``set_params`` overrides are ordinary inputs and never force a preview.

        ``op_id`` is the trusted invocation id: the current-pointer flip is
        idempotent on it, so a lost-response retry of the *same* build replays the
        recorded publication instead of re-flipping the pointer (``build_part`` is
        an idempotency-contract member). Omitted, each call publishes under a
        fresh id (the engine-CLI behaviour).
        """
        transient = {k: str(v) for k, v in (params or {}).items()}
        preview = bool(transient)
        publisher = self._publisher()
        try:
            inputs = publisher.freeze_inputs(name)
        except LeaseHeldError as exc:
            # Another build (possibly a just-cancelled run's worker still tearing
            # down) holds the part lock: surface the contractual busy refusal
            # instead of an internal crash. The caller may retry.
            raise CadOpError("part_busy", f"part {name!r} is being built: {exc}") from exc
        part_overrides: dict[str, int | float | str] = dict(self.params.read("part", name).values)
        part_overrides.update(transient)
        with self._build_dir(name) as out_dir:
            build = self._run(
                name,
                inputs.script,
                inputs.globals_source,
                out_dir=out_dir,
                part_overrides=part_overrides,
                project_overrides=self._project_overrides(),
                baseline=publisher.baseline_for(name),
            )
            if build.result.status == "ok":
                # Persist the live hc projection this build observed so consumers
                # of changed names go stale and publication revalidation sees the
                # current state (mirrors the engine CLI).
                self._sync_projections(publisher, _json_map(build.worker_result.get("hc_state")))
            outcome = publisher.publish_build(
                build,
                op_id=op_id or f"heph-build-{uuid.uuid4().hex}",
                preview=preview,
            )
        result = outcome.result
        # Optional string members are OMITTED when absent rather than sent as
        # null: the generated result schema types them as strings, and the
        # sidecar proxy fails a result closed if it does not validate.
        payload: dict[str, Any] = {
            "status": "ok" if result.status == "ok" else "error",
            "current": result.current,
            "effective_params": dict(result.params),
        }
        if result.artifact_ref is not None:
            payload["artifact_ref"] = result.artifact_ref
        if result.project_snapshot_ref is not None:
            payload["project_snapshot_ref"] = result.project_snapshot_ref
        if result.error is not None:
            # The canonical §8 error record (line/col/type/message/frame/
            # built_through/last_good/hint) — the repair loop reads exactly this.
            payload["error"] = result.error.to_json()
        return payload

    # -- inspect -----------------------------------------------------------

    def inspect_part(
        self,
        name: str,
        *,
        views: Sequence[str] | None = None,
        channel: str = "rgb",
        mask_mode: str = "solid",
        section_plane: str | None = None,
        explode: float = 0.0,
        last_good: bool = False,
        artifact_ref: str | None = None,
        focus: str | None = None,
    ) -> dict[str, Any]:
        """Render the part; return base64 image blocks, refs, legend and bundles."""
        result = inspect_part(
            self._render_project(),
            name,
            views=list(views) if views else ["iso"],
            channel=channel,
            mask_mode=mask_mode,
            section_plane=section_plane,
            explode=explode,
            last_good=last_good,
            artifact_ref=artifact_ref,
            focus=focus,
        )
        if len(result.images) > MAX_IMAGES_PER_RESULT:  # pragma: no cover - schema-capped
            raise CadOpError(
                "too_many_images",
                f"{len(result.images)} images exceeds the per-result budget "
                f"{MAX_IMAGES_PER_RESULT}",
            )
        images: list[dict[str, Any]] = []
        for image in result.images:
            # Bounded header parse BEFORE anything decodes the payload (§5).
            parse_image_header(image.png)
            images.append(
                {
                    "data": base64.b64encode(image.png).decode("ascii"),
                    "mime_type": "image/png",
                    "view": image.view,
                    "channel": image.channel,
                    "render_artifact_ref": image.render_ref,
                    "palette_decodable": image.palette_decodable,
                }
            )
        payload: dict[str, Any] = {
            "status": "ok",
            "source_artifact_ref": result.source_artifact_ref,
            "render_artifact_refs": list(result.render_artifact_refs),
            "images": images,
            "mask_legend_truncated": result.mask_legend_truncated,
        }
        if result.mask_legend is not None:
            payload["mask_legend"] = json.dumps(dict(result.mask_legend), sort_keys=True)
        if result.mask_legend_ref is not None:
            payload["mask_legend_ref"] = result.mask_legend_ref
        if result.selection_table_ref is not None:
            payload["selection_table_ref"] = result.selection_table_ref
        if result.selection_bundles is not None:
            payload["selection_bundles"] = [b.to_json() for b in result.selection_bundles]
        return payload

    def render_bundle(
        self, name: str, views: Sequence[str], artifact_ref: str | None
    ) -> dict[str, JSONValue]:
        """Stage 1 ``prepare_render_bundle`` for the ``query_snapshot`` child."""
        return prepare_render_bundle(
            self._render_project(),
            name,
            views=list(views) if views else ["iso"],
            artifact_ref=artifact_ref,
        )

    # -- parameter probes --------------------------------------------------

    def probe_part_params(self, name: str) -> ParamProbe:
        """Sandbox-evaluate ``name`` to recover its ``PARAMS`` declaration."""
        publisher = self._publisher()
        inputs = publisher.freeze_inputs(name)
        with self._build_dir(name) as out_dir:
            build = self._run(
                name,
                inputs.script,
                inputs.globals_source,
                out_dir=out_dir,
                part_overrides=dict(self.params.read("part", name).values),
                project_overrides=self._project_overrides(),
            )
            return self._probe_from(build, declaration_key="params_declaration")

    def probe_globals(
        self,
        *,
        source: str | None = None,
        overrides: Mapping[str, int | float | str] | None = None,
    ) -> ParamProbe:
        """Sandbox-evaluate ``globals.py`` alone (candidate source optional)."""
        publisher = self._publisher()
        if source is None:
            snapshot = publisher.parts.read_globals()
            source = None if snapshot is None else snapshot.content
        merged: dict[str, int | float | str] = dict(self._layout.manifest.params)
        merged.update(self.params.read("project", None).values if overrides is None else overrides)
        with self._build_dir(SYNC_PART) as out_dir:
            build = self._run(
                SYNC_PART,
                _SYNC_SCRIPT,
                source,
                out_dir=out_dir,
                part_overrides={},
                project_overrides=merged,
            )
            return self._probe_from(build, declaration_key="project_params_declaration")

    @staticmethod
    def _probe_from(build: UnpublishedBuild, *, declaration_key: str) -> ParamProbe:
        worker = build.worker_result
        declaration = _params_from_declaration(_json_map(worker.get(declaration_key)))
        part_scope = declaration_key == "params_declaration"
        effective_key = "effective_params" if part_scope else "project_effective_params"

        error = build.result.error
        return ParamProbe(
            declaration=declaration,
            effective=_numeric_map(worker.get(effective_key)),
            hc_state=_json_map(worker.get("hc_state")),
            error_type=None if error is None else error.type,
            error_message="" if error is None else error.message,
        )

    # -- set_params --------------------------------------------------------

    def set_params(
        self,
        scope: str,
        name: str | None,
        values: Mapping[str, Any],
        *,
        expected_state_hash: str,
        op_id: str,
    ) -> dict[str, Any]:
        """Persist bounds-validated overrides for one scope, all-or-nothing."""
        probe = (
            self.probe_globals()
            if scope == "project"
            else self.probe_part_params(cast("str", name))
        )
        declaration = probe.declaration
        current = self.params.read(scope, name)
        rejected: list[dict[str, Any]] = []
        merged: dict[str, int | float] = dict(current.values)
        for key, raw in values.items():
            param = declaration.get(key)
            if param is None:
                rejected.append(
                    {
                        "name": key,
                        "reason": "unknown_parameter",
                        "declared": sorted(declaration),
                    }
                )
                continue
            if raw is None:
                merged.pop(key, None)
                continue
            if isinstance(raw, bool) or not isinstance(raw, int | float):
                rejected.append({"name": key, "reason": "not_a_number", "value": repr(raw)})
                continue
            try:
                coerced = param.coerce(raw, name=key)
            except ValidationError as exc:
                rejected.append({"name": key, "reason": "wrong_type", "detail": exc.message})
                continue
            if not param.in_bounds(coerced):
                rejected.append(
                    {
                        "name": key,
                        "reason": "out_of_bounds",
                        "value": coerced,
                        "min": param.min,
                        "max": param.max,
                    }
                )
                continue
            merged[key] = coerced
        if rejected:
            # All-or-nothing: nothing is persisted and no state hash moves.
            return {
                "effective": self._effective(declaration, current.values),
                "rejected": rejected,
                "stale_parts": [],
                "state_hash": current.state_hash,
            }
        new_state, journal_ref = self.params.write(
            scope, name, merged, expected_state_hash=expected_state_hash, op_id=op_id
        )
        stale_parts: list[str] = []
        if scope == "project":
            after = self.probe_globals(overrides=merged)
            if after.ok:
                publisher = self._publisher()
                before = publisher.projections.state().hc_state
                if canonical_json(dict(before)) != canonical_json(dict(after.hc_state)):
                    report = publisher.projections.apply_hc_state(
                        after.hc_state, reason="project parameters changed"
                    )
                    stale_parts = list(report.stale)
                else:
                    stale_parts = sorted(publisher.projections.state().stale)
        return {
            "effective": self._effective(declaration, new_state.values),
            "rejected": [],
            "stale_parts": stale_parts,
            "state_hash": new_state.state_hash,
            "journal_ref": journal_ref,
        }

    @staticmethod
    def _effective(
        declaration: Mapping[str, Param], values: Mapping[str, int | float]
    ) -> dict[str, int | float]:
        try:
            return merge_overrides(declaration, values)
        except HephaestusError:  # pragma: no cover - validated above
            return dict(values)

    def param_state_hash(self, scope: str, name: str | None) -> str:
        """The optimistic ``expected_state_hash`` a client must present."""
        return self.params.read(scope, name).state_hash

    # -- globals -----------------------------------------------------------

    def edit_globals(
        self, *, expected_hash: str, old_str: str, new_str: str, op_id: str
    ) -> dict[str, Any]:
        """``edit_globals``: opkey-first CAS write of ``globals.py`` (tool_schema).

        The idempotency payload is the *request* (presented base hash + the exact
        old/new strings), and the opkey is claimed **before** the live hash is
        read: a lost-response retry therefore replays ``applied`` instead of
        reporting the conflict its own committed write created. The candidate must
        parse/evaluate in the **secure globals sandbox** against the persisted
        project overrides — a removed parameter or a bound tightened around a live
        override is the discriminated ``invalid_overrides`` failure and commits
        nothing (distinct from ``conflict(kind="stale_hash")``).
        """
        path = self._layout.globals_path
        payload: JSONValue = {
            "kind": "globals_edit",
            "base": expected_hash,
            "old": old_str,
            "new": new_str,
        }
        payload_hash = sha256_canonical_json(payload)
        outcome = self._store.opkeys.begin(op_id, payload_hash)
        if isinstance(outcome, PendingRecovery):
            self._store.wal.recover(outcome.op_key)
            outcome = self._store.opkeys.begin(op_id, payload_hash)
        if isinstance(outcome, Replay):
            after = _recorded_ref(outcome.response, "globals", "")
            return {
                "status": "applied",
                "diff": _diff_line(old_str, new_str),
                "content_hash": after,
                "snapshot_ref": make_artifact_ref("part-snapshot", after),
                "journal_ref": _recorded_ref(outcome.response, "journal", after),
                "replayed": True,
            }
        if not isinstance(outcome, Fresh):
            raise CadOpError(
                "conflict", f"globals edit {op_id!r} cannot proceed: prior state {outcome!r}"
            )
        abort = outcome.op_key
        live = path.read_bytes() if path.is_file() else None
        if live is None:
            self._store.wal.recover(abort)
            raise AddressingError(
                "project has no globals.py to edit",
                selector="globals",
                candidates=self._layout.part_names(),
            )
        live_hash = sha256_bytes(live)
        script = live.decode("utf-8")
        if live_hash != expected_hash:
            self._store.wal.recover(abort)
            snapshot_ref = make_artifact_ref("part-snapshot", self._store.blobs.put(live))
            return {
                "status": "conflict",
                "kind": "stale_hash",
                "current_hash": live_hash,
                "current_script": script,
                "current_truncated": False,
                "current_oversized_line": False,
                "current_snapshot_ref": snapshot_ref,
                "base_snapshot_ref": make_artifact_ref("part-snapshot", expected_hash),
                "attempted_snapshot_ref": snapshot_ref,
            }
        occurrences = script.count(old_str)
        if occurrences != 1:
            self._store.wal.recover(abort)
            return {
                "status": "validation_error",
                "kind": "contract",
                "diagnostics": (
                    f"old_str occurs {occurrences} times in globals.py; it must be unique"
                ),
            }
        candidate = script.replace(old_str, new_str, 1)
        probe = self.probe_globals(source=candidate)
        if not probe.ok:
            self._store.wal.recover(abort)
            return {
                "status": "validation_error",
                "kind": _globals_failure_kind(probe.error_type, probe.error_message),
                "diagnostics": f"{probe.error_type}: {probe.error_message}",
            }
        overrides = self.params.read("project", None).values
        missing = sorted(key for key in overrides if key not in probe.declaration)
        if missing:
            self._store.wal.recover(abort)
            return {
                "status": "validation_error",
                "kind": "invalid_overrides",
                "diagnostics": (
                    "persisted project overrides are no longer declared: " + ", ".join(missing)
                ),
                "invalid_overrides": missing,
            }
        raw = candidate.encode("utf-8")
        after_hash = sha256_bytes(raw)
        journal_ref = self._journal_globals(op_id, path, live_hash, live, after_hash)
        self._store.wal.execute(
            outcome,
            path,
            raw,
            intended_outcome=canonical_json({"globals": after_hash, "journal": journal_ref}),
        )
        self._store.blobs.put(raw)
        # The audit revision advances to the projection the candidate evaluates to,
        # so exactly the consumers of changed hc names go stale.
        self.sync_globals_projection(probe.hc_state)
        return {
            "status": "applied",
            "diff": _diff_line(old_str, new_str),
            "content_hash": after_hash,
            "snapshot_ref": make_artifact_ref("part-snapshot", after_hash),
            "journal_ref": journal_ref,
        }

    def _journal_globals(
        self, op_id: str, path: Path, before_hash: str, preimage: bytes, after_hash: str
    ) -> str:
        """Durable preimage journal entry for a ``globals.py`` overwrite."""
        entry: JSONValue = {
            "kind": "globals_write",
            "op_id": op_id,
            "target": str(path),
            "before_hash": before_hash,
            "preimage_blob": self._store.blobs.put(preimage),
            "after_hash": after_hash,
        }
        payload = canonical_json(entry).encode("utf-8")
        blob = self._store.blobs.put(payload)
        self._layout.journal_dir.mkdir(parents=True, exist_ok=True)
        (
            self._layout.journal_dir / f"globals-{blob.removeprefix('sha256:')[:32]}.json"
        ).write_bytes(payload)
        return make_artifact_ref("globals-journal", blob)

    def sync_globals_projection(self, hc_state: Mapping[str, JSONValue]) -> list[str]:
        """Advance the audit revision after a globals edit; return newly stale parts."""
        publisher = self._publisher()
        before = publisher.projections.state().hc_state
        if canonical_json(dict(before)) == canonical_json(dict(hc_state)):
            return sorted(publisher.projections.state().stale)
        report = publisher.projections.apply_hc_state(hc_state, reason="globals.py changed")
        return list(report.stale)

    # -- project checks ----------------------------------------------------

    def check_state(self) -> CheckSetState:
        """The current check-set generation (after recovery/reconciliation)."""
        return self._check_set().current()

    def check_diagnostics_ref(self, state: CheckSetState) -> str | None:
        return (
            None
            if state.diagnostics is None
            else make_artifact_ref("check-diagnostics", state.diagnostics)
        )

    def read_check(self, name: str) -> tuple[str, str, str]:
        """``(script, content_hash, snapshot_ref)`` for ``checks/<name>.py``."""
        path = self._layout.checks_dir / f"{name}.py"
        if not path.is_file():
            raise AddressingError(
                f"project check {name!r} does not exist under {self._layout.checks_dir}",
                selector=name,
                candidates=self.check_names(),
            )
        raw = path.read_bytes()
        blob = self._store.blobs.put(raw)
        return raw.decode("utf-8"), blob, make_artifact_ref("part-snapshot", blob)

    def check_names(self) -> tuple[str, ...]:
        directory = self._layout.checks_dir
        if not directory.is_dir():
            return ()
        return tuple(sorted(path.stem for path in directory.glob("*.py")))

    def write_check(self, name: str, content: str, *, op_id: str) -> CheckSetState:
        """Cooperative create/edit of ``checks/<name>.py`` (generation advance)."""
        return self._check_set().write_check(f"{name}.py", content, op_id=op_id)

    def check_bundle_items(self, bundle_ref: str) -> list[dict[str, JSONValue]]:
        """The frozen lexical check index behind ``check_set_ref`` (paging source)."""
        blob = blob_hash_of_ref(bundle_ref)
        if not self._store.blobs.has(blob):
            raise CadOpError("invalid_cursor", f"check-set index {bundle_ref} is not stored")
        manifest = cast(
            "Mapping[str, JSONValue]",
            json.loads(self._store.blobs.get(blob).decode("utf-8")),
        )
        entries = manifest.get("files")
        items: list[dict[str, JSONValue]] = []
        if not isinstance(entries, list):
            return items
        for entry in cast("list[JSONValue]", entries):
            if not isinstance(entry, dict):
                continue
            record = cast("Mapping[str, JSONValue]", entry)
            path = record.get("path")
            content_hash = record.get("hash")
            if not isinstance(path, str) or not isinstance(content_hash, str):
                continue
            items.append(
                {
                    "name": Path(path).stem,
                    "content_hash": content_hash,
                    "summary": self._check_summary(content_hash),
                }
            )
        return items

    def _check_summary(self, content_hash: str) -> str:
        """First comment/docstring line of a check file, capped at 512 UTF-8 bytes."""
        if not self._store.blobs.has(content_hash):
            return ""
        try:
            text = self._store.blobs.get(content_hash).decode("utf-8")
        except UnicodeDecodeError:  # pragma: no cover - checks are UTF-8 sources
            return ""
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            summary = stripped.lstrip("#").strip().strip('"').strip("'")
            if not summary:
                continue
            encoded = summary.encode("utf-8")[:_SUMMARY_MAX_BYTES]
            # Truncate at a valid code-point boundary; never embed source.
            return encoded.decode("utf-8", errors="ignore")
        return ""

    @staticmethod
    def validate_check_source(name: str, content: str) -> str | None:
        """``None`` when the candidate is valid, else the failure ``kind``."""
        try:
            load_check_module(content, filename=f"{name}.py")
        except ValidationError as exc:
            return exc.kind
        return None

    # -- measure -----------------------------------------------------------

    def measure(
        self,
        kind: str,
        a: str,
        b: str | None,
        *,
        part: str | None,
        artifact_ref: str | None,
        project_snapshot_ref: str | None,
    ) -> dict[str, Any]:
        """The ``m`` facade as a tool: resolve geometry, measure, report refs."""
        if kind not in _MEASURE_UNITS:
            raise CadOpError("invalid_params", f"unknown measure kind {kind!r}")
        if (kind in _BINARY_MEASURE_KINDS) != (b is not None):
            raise CadOpError(
                "invalid_params",
                f"measure kind {kind!r} "
                + ("requires" if kind in _BINARY_MEASURE_KINDS else "forbids")
                + " selector 'b'",
            )
        if artifact_ref is not None and project_snapshot_ref is not None:
            raise CadOpError(
                "invalid_params", "artifact_ref and project_snapshot_ref are mutually exclusive"
            )
        selectors = [a] + ([b] if b is not None else [])
        qualified = {s.split("/", 1)[0] for s in selectors if "/" in s}
        current = part or (sorted(qualified)[0] if qualified else None)
        with self._scratch("heph-measure-") as scratch:
            sources, refs = self._measure_sources(
                selectors,
                qualified,
                current,
                artifact_ref=artifact_ref,
                project_snapshot_ref=project_snapshot_ref,
                scratch=Path(scratch),
            )
            measurement = project_measurement(sources, current_part=current)
            value: JSONValue
            if kind == "interference":
                value = measurement.interference(a, cast("str", b))
            elif kind == "clearance":
                value = measurement.clearance(a, cast("str", b))
            elif kind == "distance":
                value = measurement.distance(a, cast("str", b))
            elif kind == "bbox":
                triple = measurement.bbox(a)
                value = [triple[0], triple[1], triple[2]]
            elif kind == "volume":
                value = measurement.volume(a)
            elif kind == "mass":
                value = measurement.mass(a)
            elif kind == "sealed":
                value = measurement.sealed(a)
            else:
                value = measurement.genus(a)
        return {
            "value": value,
            "units": _MEASURE_UNITS[kind],
            "detail": {
                "kind": kind,
                "args": selectors,
                "measured": measurement.measured_json(),
                "parts": sorted(sources),
            },
            "resolved_artifact_refs": refs,
        }

    def _measure_sources(
        self,
        selectors: Sequence[str],
        qualified: set[str],
        current: str | None,
        *,
        artifact_ref: str | None,
        project_snapshot_ref: str | None,
        scratch: Path,
    ) -> tuple[dict[str, GeometrySource], list[str]]:
        """Resolve the geometry each selector needs, plus the exact refs used."""
        publisher = self._publisher()
        unqualified = any("/" not in s for s in selectors)
        addressed: set[str] = set(qualified)
        if unqualified and current is not None:
            addressed.add(current)
        if artifact_ref is not None:
            if len(addressed) > 1:
                raise CadOpError(
                    "invalid_params",
                    "artifact_ref selects one part; cross-part selectors need a snapshot",
                )
            name = current or (sorted(addressed)[0] if addressed else None)
            if name is None:
                raise CadOpError("invalid_params", "artifact_ref requires a part context")
            return ({name: self._artifact_geometry(artifact_ref, scratch)}, [artifact_ref])
        if project_snapshot_ref is not None:
            return self._snapshot_sources(project_snapshot_ref, scratch)
        if len(addressed) <= 1:
            name = current or (sorted(addressed)[0] if addressed else None)
            if name is None:
                raise CadOpError("invalid_params", "measure requires a part context")
            result = publisher.current_result(name)
            if result is None or result.artifact_ref is None:
                raise AddressingError(
                    f"part {name!r} has no current successful build to measure",
                    selector=name,
                    candidates=self._layout.part_names(),
                )
            return (
                {name: self._artifact_geometry(result.artifact_ref, scratch)},
                [result.artifact_ref],
            )
        # Cross-part: one coherent project-snapshot manifest.
        try:
            snapshot = publisher.projections.assemble_snapshot(self._layout.part_names())
        except SnapshotRejectedError as exc:
            raise CadOpError(
                "incoherent_project_snapshot",
                exc.message,
                data={"issues": [issue.to_json() for issue in exc.issues]},
            ) from exc
        return self._snapshot_sources(snapshot.ref, scratch)

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

    # -- run_checks --------------------------------------------------------

    def run_part_checks(self, name: str) -> dict[str, Any]:
        """Re-execute ``name``'s persistent ``CHECKS`` (published as a preview)."""
        publisher = self._publisher()
        inputs = publisher.freeze_inputs(name)
        with self._build_dir(name) as out_dir:
            build = self._run(
                name,
                inputs.script,
                inputs.globals_source,
                out_dir=out_dir,
                part_overrides=dict(self.params.read("part", name).values),
                project_overrides=self._project_overrides(),
                baseline=publisher.baseline_for(name),
            )
            # preview=True: evidence is durable (refs resolve) but nothing becomes
            # current and no stale marker is cleared — run_checks is not a mutation.
            outcome = publisher.publish_build(
                build, op_id=f"heph-run-checks-{uuid.uuid4().hex}", preview=True
            )
        result: BuildResult = outcome.result
        payload: dict[str, Any] = {
            "status": "ok" if result.status == "ok" else "error",
            "scope": "part",
            "part": name,
            "checks": {check_name: check.to_json() for check_name, check in result.checks.items()},
        }
        if result.artifact_ref is not None:
            payload["artifact_ref"] = result.artifact_ref
        if result.error is not None:
            payload["error"] = result.error.to_json()
        return payload

    def run_project_checks(self, project_snapshot_ref: str | None) -> dict[str, Any]:
        """Freeze the authorized cross-part bundle and run it (fails closed)."""
        check_set = self._check_set()
        bundle = check_set.capture()
        state = bundle.state
        if state.status == "invalid":
            payload: dict[str, Any] = {
                "status": "invalid_check_generation",
                "check_set_generation": str(state.generation),
                "check_set_ref": state.bundle_ref,
            }
            diagnostics = self.check_diagnostics_ref(state)
            if diagnostics is not None:
                payload["diagnostics_ref"] = diagnostics
            return payload
        publisher = self._publisher()
        with self._scratch("heph-checks-") as scratch:
            if project_snapshot_ref is None:
                try:
                    snapshot = publisher.projections.assemble_snapshot(self._layout.part_names())
                except SnapshotRejectedError as exc:
                    raise CadOpError(
                        "incoherent_project_snapshot",
                        exc.message,
                        data={"issues": [issue.to_json() for issue in exc.issues]},
                    ) from exc
                resolved_ref = snapshot.ref
            else:
                resolved_ref = project_snapshot_ref
            sources, _refs = self._snapshot_sources(resolved_ref, Path(scratch))
            try:
                report = run_bundle(
                    bundle,
                    sources,
                    part=self._layout.manifest.name,
                    project_snapshot_ref=resolved_ref,
                )
            except InvalidCheckGenerationError as exc:  # pragma: no cover - captured above
                raise CadOpError("invalid_check_generation", exc.message) from exc
        payload = dict(report.to_json())
        payload["status"] = "ok"
        payload["scope"] = "project"
        payload["check_set_generation"] = str(state.generation)
        payload["check_set_ref"] = state.bundle_ref
        return payload

    # -- read_artifact -----------------------------------------------------

    def read_artifact(self, ref: str, offset_bytes: int, max_bytes: int) -> dict[str, Any]:
        """UTF-8-boundary-safe byte-cursor page over a model-readable artifact."""
        parts = ref.split(":")
        if len(parts) != 4 or parts[0] != "artifact":
            raise CadOpError("invalid_ref", f"{ref!r} is not an artifact reference")
        kind = parts[1]
        blob = blob_hash_of_ref(ref)
        if not self._store.blobs.has(blob):
            raise CadOpError("invalid_ref", f"artifact {ref} is not durably stored")
        data = self._store.blobs.get(blob)
        total = len(data)
        if kind in BINARY_ARTIFACT_KINDS:
            # Binary artifacts return metadata only; they are consumed by their
            # dedicated render/export path.
            return {
                "content": "",
                "mime_type": "application/octet-stream",
                "offset_bytes": 0,
                "total_bytes": total,
                "truncated": False,
            }
        mime = TEXT_ARTIFACT_MIME.get(kind)
        if mime is None:
            try:
                data.decode("utf-8")
            except UnicodeDecodeError:
                return {
                    "content": "",
                    "mime_type": "application/octet-stream",
                    "offset_bytes": 0,
                    "total_bytes": total,
                    "truncated": False,
                }
            mime = "text/plain"
        if offset_bytes > total or (
            offset_bytes not in (0, total) and (data[offset_bytes] & 0xC0) == 0x80
        ):
            return {
                "error": "invalid_utf8_offset",
                "offset_bytes": offset_bytes,
                "total_bytes": total,
            }
        end = min(offset_bytes + max_bytes, total)
        # Shorten the page end to the preceding code-point boundary...
        while end > offset_bytes and end < total and (data[end] & 0xC0) == 0x80:
            end -= 1
        if end == offset_bytes and offset_bytes < total:
            # ...but always guarantee cursor progress: extend over one code point.
            end = offset_bytes + 1
            while end < total and (data[end] & 0xC0) == 0x80:
                end += 1
        payload: dict[str, Any] = {
            "content": data[offset_bytes:end].decode("utf-8"),
            "mime_type": mime,
            "offset_bytes": offset_bytes,
            "total_bytes": total,
            "truncated": end < total,
        }
        if end < total:
            payload["next_offset_bytes"] = end
        return payload

    # -- export ------------------------------------------------------------

    def export_part(
        self,
        name: str,
        fmt: str,
        *,
        artifact_ref: str | None,
        target: str | None,
        layout: str,
        op_id: str,
    ) -> dict[str, Any]:
        """The §7 export contract: frozen source, create-only target, pinned root."""
        if layout != "as_built":
            raise CadOpError(
                "capability_not_available",
                f"layout={layout!r} is reserved until Stage 6 (Stage 2 supports as_built)",
                data={"code": "capability_not_available"},
            )
        if fmt not in EXPORT_FORMATS:
            raise CadOpError("invalid_params", f"unsupported export format {fmt!r}")
        payload_hash = sha256_canonical_json(
            {
                "kind": "export_part",
                "part": name,
                "format": fmt,
                "layout": layout,
                "artifact_ref": artifact_ref,
                "target": target,
            }
        )
        row = self._export_row(op_id)
        if row is not None:
            if str(row["payload_hash"]) != payload_hash:
                raise CadOpError(
                    "key_payload_mismatch",
                    f"export invocation {op_id!r} was already used with a different payload",
                )
            if str(row["state"]) == "COMMITTED":
                return self._replay_export(row)
            source_ref = str(row["source_artifact_ref"])
        else:
            source_ref = self._freeze_export_source(name, artifact_ref)
            with self._store.db.transaction() as conn:
                conn.execute(
                    f"INSERT INTO {_EXPORTS_TABLE}(op_id, payload_hash, part, format, layout, "
                    "source_artifact_ref, requested_target, state) "
                    "VALUES(?, ?, ?, ?, ?, ?, ?, 'FROZEN')",
                    (op_id, payload_hash, name, fmt, layout, source_ref, target),
                )
        source_blob = blob_hash_of_ref(source_ref)
        with self._scratch("heph-export-") as scratch:
            shape = load_brep_shape(self._store.blobs.get(source_blob), scratch_dir=Path(scratch))
            data = _export_bytes(shape, fmt, Path(scratch))
        if target is not None:
            rel = _validate_relative_target(target)
        else:
            digest = sha256_bytes(data).removeprefix("sha256:")[:16]
            rel = PurePosixPath(f"{name}-{digest}.{EXPORT_FORMATS[fmt]}")
        _create_confined(self._layout.exports_dir, rel, data)
        export_blob = self._store.blobs.put(data)
        # Every successful export is a GC root until explicit unpin/delete, and
        # links its immutable source so provenance stays reachable.
        self._store.gc.pin(export_blob)
        self._store.gc.link(export_blob, source_blob)
        input_hashes = self._source_input_hashes(name, source_ref)
        with self._store.db.transaction() as conn:
            conn.execute(
                f"UPDATE {_EXPORTS_TABLE} SET rel_path = ?, export_blob = ?, "
                "source_input_hashes = ?, state = 'COMMITTED' WHERE op_id = ?",
                (
                    rel.as_posix(),
                    export_blob,
                    canonical_json(cast("JSONValue", input_hashes)),
                    op_id,
                ),
            )
        return {
            "paths": [str(Path(".heph") / "exports" / rel.as_posix())],
            "source_artifact_ref": source_ref,
            "source_input_hashes": input_hashes,
            "export_hashes": {rel.as_posix(): sha256_bytes(data)},
        }

    def _export_row(self, op_id: str) -> Mapping[str, Any] | None:
        raw = self._store.db.conn.execute(
            f"SELECT * FROM {_EXPORTS_TABLE} WHERE op_id = ?", (op_id,)
        ).fetchone()
        return None if raw is None else cast("Mapping[str, Any]", raw)

    def _replay_export(self, row: Mapping[str, Any]) -> dict[str, Any]:
        """A committed retry reconciles to the recorded source/outputs exactly."""
        rel = str(row["rel_path"])
        export_blob = str(row["export_blob"])
        source_ref = str(row["source_artifact_ref"])
        raw_hashes = row["source_input_hashes"]
        input_hashes = cast(
            "dict[str, Any]",
            json.loads(str(raw_hashes)) if raw_hashes is not None else {},
        )
        # Reapply the idempotent completion steps so recovery converges from any
        # crash point between install, pin and link.
        self._store.gc.pin(export_blob)
        self._store.gc.link(export_blob, blob_hash_of_ref(source_ref))
        return {
            "paths": [str(Path(".heph") / "exports" / rel)],
            "source_artifact_ref": source_ref,
            "source_input_hashes": input_hashes,
            "export_hashes": {rel: export_blob},
            "replayed": True,
        }

    def _freeze_export_source(self, name: str, artifact_ref: str | None) -> str:
        """Resolve (and authorize) the immutable source the export freezes."""
        publisher = self._publisher()
        if artifact_ref is None:
            stale = publisher.projections.state().stale
            if name in stale:
                raise CadOpError(
                    "stale_source",
                    f"part {name!r} is stale ({stale[name]}); rebuild before exporting",
                )
            result = publisher.current_result(name)
            if result is None or result.status != "ok" or result.artifact_ref is None:
                raise AddressingError(
                    f"part {name!r} has no current successful build to export",
                    selector=name,
                    candidates=self._layout.part_names(),
                )
            return result.artifact_ref
        kind = artifact_ref.split(":")[1] if artifact_ref.count(":") == 3 else ""
        if kind != "build":
            raise CadOpError(
                "invalid_source",
                f"{artifact_ref} is not a successful build artifact "
                "(failed/checkpoint-only refs are rejected)",
            )
        blob = blob_hash_of_ref(artifact_ref)
        if not self._store.blobs.has(blob):
            raise CadOpError("invalid_source", f"artifact {artifact_ref} is not durably stored")
        return artifact_ref

    def _source_input_hashes(self, name: str, source_ref: str) -> dict[str, Any]:
        result = self._publisher().current_result(name)
        if result is not None and result.artifact_ref == source_ref:
            return dict(result.input_hashes.to_json())
        return {"source_artifact": blob_hash_of_ref(source_ref)}

    def unpin_export(self, export_blob: str) -> None:
        """``heph export unpin``: drop the GC-root pin on an exported blob."""
        self._store.gc.unpin(export_blob)
