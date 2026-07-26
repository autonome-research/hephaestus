"""The §7 export contract — WAL, confinement, pins, formats.

An export is a two-phase durable operation over its own table
(``tp_exports``). The first sight of an invocation id freezes the immutable
source artifact in a ``FROZEN`` row; every retry of that id reuses the frozen
source, a same-id/different-payload presentation is a hard mismatch, and a
``COMMITTED`` retry reconciles to the recorded outputs while reapplying the
idempotent pin/link steps.

Targets are create-only files beneath ``.heph/exports/``, written through a
per-component directory-descriptor walk with no-follow/beneath semantics and
``O_CREAT|O_EXCL`` — a racing parent symlink fails the walk instead of
redirecting the write. Successful exports become GC roots linked to their source,
and the format writers here turn one reloaded BRep shape into bytes.

:meth:`ExportOps.wal_export` is that contract as one reusable operation: a
caller supplies the source resolution inputs and a ``produce`` callback that
turns the frozen artifact into one *or more* :class:`ExportOutput` files, and
gets back the frozen ref, the confined create-only paths, the provenance hashes
and the GC-root pins. ``export_part`` is its single-file caller; the Stage 6
document generators (``generate_drawing``, ``generate_doc``) are its multi-file
callers, so no second export path — and no second set of confinement or pin
rules — exists anywhere in the engine.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import struct
import zipfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Final, cast

from hephaestus.core.errors import AddressingError, ValidationError
from hephaestus.core.executor.artifact_geometry import load_brep_shape
from hephaestus.core.nesting import (
    DEFAULT_MARGIN_MM,
    DEFAULT_SPACING_MM,
    Blank,
    NestingRefusal,
    blank_from_metadata,
    blank_size_literal,
    flat_profiles,
    layout_to_dxf,
    layout_to_svg,
    shelf_nest,
)
from hephaestus.core.project_store.store import blob_hash_of_ref
from opstore.types import JSONValue

from opstore import OpStore, canonical_json, sha256_bytes, sha256_canonical_json

from ._base import CadOpError, CadOpsState

#: Export formats and the file extension each produces.
EXPORT_FORMATS: Final[dict[str, str]] = {
    "step": "step",
    "dxf": "dxf",
    "svg": "svg",
    "gltf": "glb",
    "3mf": "3mf",
    "stl": "stl",
}

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
  state TEXT NOT NULL,
  outputs TEXT,
  extra TEXT)
"""

#: Columns added after the table's first shipped shape. A project whose
#: ``tp_exports`` predates multi-file exports is migrated in place (ALTER TABLE
#: ADD COLUMN is a metadata-only change) rather than losing its export history.
_LATE_EXPORT_COLUMNS: Final[tuple[str, ...]] = ("outputs", "extra")


def ensure_exports_table(store: OpStore) -> None:
    """Create (or forward-migrate) the export write-ahead table."""
    conn = store.db.conn
    conn.execute(_CREATE_EXPORTS_TABLE)
    present = {str(row[1]) for row in conn.execute(f"PRAGMA table_info({_EXPORTS_TABLE})")}
    for column in _LATE_EXPORT_COLUMNS:
        if column not in present:
            conn.execute(f"ALTER TABLE {_EXPORTS_TABLE} ADD COLUMN {column} TEXT")


@dataclass(frozen=True)
class ExportOutput:
    """One file an export operation produces: its extension and its bytes.

    ``suffix`` is the extension without the dot. A single-output operation
    (``export_part``) names its file exactly as it always has; a multi-output
    one (a drawing's PDF + SVG) shares one stem and differs only by suffix, so
    the whole set is addressable as one deliverable.
    """

    suffix: str
    data: bytes


@dataclass(frozen=True)
class ExportCommit:
    """The committed result of one export: paths, provenance, and extra fields.

    ``extra`` is the per-operation result payload (a drawing's dimensions and
    title block, a document's markdown) recorded in the WAL alongside the paths,
    so a committed retry replays the *whole* result and not just its filenames.
    """

    paths: tuple[str, ...]
    source_artifact_ref: str
    source_input_hashes: Mapping[str, Any]
    export_hashes: Mapping[str, str]
    extra: Mapping[str, Any] = field(default_factory=dict[str, Any])
    replayed: bool = False

    def to_result(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "paths": list(self.paths),
            "source_artifact_ref": self.source_artifact_ref,
            "source_input_hashes": dict(self.source_input_hashes),
            "export_hashes": dict(self.export_hashes),
        }
        out.update(self.extra)
        if self.replayed:
            out["replayed"] = True
        return out


# --------------------------------------------------------------------------
# path confinement


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


def _output_paths(
    outputs: Sequence[ExportOutput], *, target: str | None, stem: str
) -> tuple[PurePosixPath, ...]:
    """The confined relative path of each output.

    A single-output operation with an explicit ``target`` uses it verbatim (the
    ``export_part`` contract). A multi-output operation treats ``target`` as the
    shared *stem* and appends each suffix, so one requested name yields one
    coherent set. Without a target the stem is content-addressed over the whole
    set, which keeps a drawing's PDF and SVG named as the pair they are.
    """
    if len(outputs) == 1 and target is not None:
        return (_validate_relative_target(target),)
    if target is not None:
        base = _validate_relative_target(target).as_posix()
        return tuple(_validate_relative_target(f"{base}.{o.suffix}") for o in outputs)
    digest = sha256_bytes(b"".join(o.data for o in outputs)).removeprefix("sha256:")[:16]
    return tuple(PurePosixPath(f"{stem}-{digest}.{o.suffix}") for o in outputs)


def _row_json(row: Mapping[str, Any], column: str, fallback: JSONValue) -> JSONValue:
    """One JSON-encoded WAL column, tolerant of a row written before it existed."""
    raw = row[column] if column in row.keys() else None  # noqa: SIM118 - sqlite3.Row
    if raw is None:
        return fallback
    try:
        return cast("JSONValue", json.loads(str(raw)))
    except ValueError:  # pragma: no cover - the writer is this module
        return fallback


def _recorded_outputs(row: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    """``[(rel_path, export_blob)]`` of a committed row (single-file rows too)."""
    recorded = _row_json(row, "outputs", None)
    if isinstance(recorded, list):
        out: list[tuple[str, str]] = []
        for item in cast("list[JSONValue]", recorded):
            if not isinstance(item, dict):
                continue
            entry = cast("Mapping[str, JSONValue]", item)
            path, blob = entry.get("path"), entry.get("blob")
            if isinstance(path, str) and isinstance(blob, str):
                out.append((path, blob))
        if out:
            return tuple(out)
    return ((str(row["rel_path"]), str(row["export_blob"])),)


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


def _blank_payload(blank: Mapping[str, Any] | None) -> JSONValue:
    """The blank as it enters the idempotency payload (name-sorted, numeric).

    Two presentations of the same invocation id must hash identically, so the
    argument is canonicalised here rather than trusted key-order-first.
    """
    if blank is None:
        return None
    out: dict[str, JSONValue] = {}
    for key in sorted(blank):
        value = blank[key]
        numeric = isinstance(value, int | float) and not isinstance(value, bool)
        out[str(key)] = float(cast("float", value)) if numeric else None
    return out


class ExportOps(CadOpsState):
    """Freeze a source artifact, write a confined target, pin the result."""

    def export_part(
        self,
        name: str,
        fmt: str,
        *,
        artifact_ref: str | None,
        target: str | None,
        layout: str,
        blank: Mapping[str, Any] | None = None,
        op_id: str,
    ) -> dict[str, Any]:
        """The §7 export contract: frozen source, create-only target, pinned root."""
        if layout not in ("as_built", "nested_sheet"):
            raise CadOpError("invalid_params", f"unsupported export layout {layout!r}")
        if layout == "nested_sheet" and fmt not in ("dxf", "svg"):
            raise CadOpError(
                "invalid_params",
                f"layout='nested_sheet' produces a flat cut file: format must be dxf or svg, "
                f"not {fmt!r}",
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
                "blank": _blank_payload(blank),
            }
        )
        source_ref, replay = self._begin_export(
            op_id=op_id,
            part=name,
            payload_hash=payload_hash,
            recorded_format=fmt,
            layout=layout,
            artifact_ref=artifact_ref,
            target=target,
        )
        if replay is not None:
            return replay.to_result()
        source_blob = blob_hash_of_ref(source_ref)
        with self._scratch("heph-export-") as scratch:
            shape = load_brep_shape(self._store.blobs.get(source_blob), scratch_dir=Path(scratch))
            if layout == "nested_sheet":
                data = self._nested_sheet_bytes(name, fmt, source_ref, blank, shape)
            else:
                data = _export_bytes(shape, fmt, Path(scratch))
        return self._commit_export(
            op_id=op_id,
            part=name,
            source_ref=source_ref,
            outputs=(ExportOutput(EXPORT_FORMATS[fmt], data),),
            target=target,
            stem=name,
        ).to_result()

    # -- the reusable §7 contract ------------------------------------------

    def wal_export(
        self,
        *,
        op_id: str,
        part: str,
        operation: str,
        variant: str,
        payload: Mapping[str, JSONValue],
        artifact_ref: str | None,
        target: str | None,
        stem: str,
        produce: Callable[[str, Path], tuple[Sequence[ExportOutput], Mapping[str, Any]]],
    ) -> dict[str, Any]:
        """One export operation end to end: freeze → produce → confine → pin.

        ``produce`` receives the frozen ``source_artifact_ref`` and a scratch
        directory and returns the files to install plus the operation-specific
        result fields. Everything around it — the idempotency payload, the WAL
        row, create-only confined installation, GC-root pinning, provenance
        hashes and committed-retry replay — is the same contract ``export_part``
        runs under, because it is literally the same code.
        """
        payload_hash = sha256_canonical_json(
            {
                "kind": operation,
                "part": part,
                "variant": variant,
                "artifact_ref": artifact_ref,
                "target": target,
                **dict(payload),
            }
        )
        source_ref, replay = self._begin_export(
            op_id=op_id,
            part=part,
            payload_hash=payload_hash,
            recorded_format=f"{operation}:{variant}",
            layout=operation,
            artifact_ref=artifact_ref,
            target=target,
        )
        if replay is not None:
            return replay.to_result()
        with self._scratch(f"heph-{operation.replace('_', '-')}-") as scratch:
            outputs, extra = produce(source_ref, Path(scratch))
        if not outputs:  # pragma: no cover - every generator produces a file
            raise CadOpError("export_failed", f"{operation} produced no output file")
        return self._commit_export(
            op_id=op_id,
            part=part,
            source_ref=source_ref,
            outputs=outputs,
            target=target,
            stem=stem,
            extra=extra,
        ).to_result()

    def _begin_export(
        self,
        *,
        op_id: str,
        part: str,
        payload_hash: str,
        recorded_format: str,
        layout: str,
        artifact_ref: str | None,
        target: str | None,
    ) -> tuple[str, ExportCommit | None]:
        """Freeze (or recover) this invocation's row: ``(source_ref, replay?)``."""
        row = self._export_row(op_id)
        if row is not None:
            if str(row["payload_hash"]) != payload_hash:
                raise CadOpError(
                    "key_payload_mismatch",
                    f"export invocation {op_id!r} was already used with a different payload",
                )
            if str(row["state"]) == "COMMITTED":
                return str(row["source_artifact_ref"]), self._replay_commit(row)
            return str(row["source_artifact_ref"]), None
        source_ref = self._freeze_export_source(part, artifact_ref)
        with self._store.db.transaction() as conn:
            conn.execute(
                f"INSERT INTO {_EXPORTS_TABLE}(op_id, payload_hash, part, format, layout, "
                "source_artifact_ref, requested_target, state) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, 'FROZEN')",
                (op_id, payload_hash, part, recorded_format, layout, source_ref, target),
            )
        return source_ref, None

    def _commit_export(
        self,
        *,
        op_id: str,
        part: str,
        source_ref: str,
        outputs: Sequence[ExportOutput],
        target: str | None,
        stem: str,
        extra: Mapping[str, Any] | None = None,
    ) -> ExportCommit:
        """Install every output create-only, pin it, and mark the row committed.

        The whole set installs or none of it does: a target that already exists
        rolls back the files this call created, so a refused multi-file export
        never leaves half a deliverable behind to block its own retry.
        """
        rels = _output_paths(outputs, target=target, stem=stem)
        created: list[PurePosixPath] = []
        try:
            for rel, output in zip(rels, outputs, strict=True):
                _create_confined(self._layout.exports_dir, rel, output.data)
                created.append(rel)
        except CadOpError:
            for rel in created:
                (self._layout.exports_dir / rel.as_posix()).unlink(missing_ok=True)
            raise
        source_blob = blob_hash_of_ref(source_ref)
        recorded: list[JSONValue] = []
        export_hashes: dict[str, str] = {}
        for rel, output in zip(rels, outputs, strict=True):
            export_blob = self._store.blobs.put(output.data)
            # Every successful export is a GC root until explicit unpin/delete,
            # and links its immutable source so provenance stays reachable.
            self._store.gc.pin(export_blob)
            self._store.gc.link(export_blob, source_blob)
            recorded.append({"path": rel.as_posix(), "blob": export_blob})
            export_hashes[rel.as_posix()] = export_blob
        input_hashes = self._source_input_hashes(part, source_ref)
        with self._store.db.transaction() as conn:
            conn.execute(
                f"UPDATE {_EXPORTS_TABLE} SET rel_path = ?, export_blob = ?, "
                "source_input_hashes = ?, outputs = ?, extra = ?, state = 'COMMITTED' "
                "WHERE op_id = ?",
                (
                    rels[0].as_posix(),
                    export_hashes[rels[0].as_posix()],
                    canonical_json(cast("JSONValue", input_hashes)),
                    canonical_json(cast("JSONValue", recorded)),
                    canonical_json(cast("JSONValue", dict(extra or {}))),
                    op_id,
                ),
            )
        return ExportCommit(
            paths=tuple(str(Path(".heph") / "exports" / rel.as_posix()) for rel in rels),
            source_artifact_ref=source_ref,
            source_input_hashes=input_hashes,
            export_hashes=export_hashes,
            extra=dict(extra or {}),
        )

    # -- nested_sheet ------------------------------------------------------

    def _nested_sheet_bytes(
        self,
        name: str,
        fmt: str,
        source_ref: str,
        blank: Mapping[str, Any] | None,
        shape: object,
    ) -> bytes:
        """``layout="nested_sheet"``: flat profiles packed onto the declared blank.

        Deterministic shelf packing, no rotation, no kerf compensation (mission
        rule 5 defers kerf-aware auto-nesting). Anything that will not fit is a
        structured refusal naming the profile and the blank — never a silent
        overlap and never a clipped part.
        """
        resolved = self._resolve_blank(name, source_ref, blank)
        try:
            profiles = flat_profiles(shape, prefix=name)
            nested = shelf_nest(profiles, resolved)
        except NestingRefusal as exc:
            raise CadOpError(exc.reason, exc.message, data=exc.data) from exc
        return layout_to_dxf(nested) if fmt == "dxf" else layout_to_svg(nested)

    def _resolve_blank(self, name: str, source_ref: str, blank: Mapping[str, Any] | None) -> Blank:
        """The declared blank: the explicit argument, else ``part.blank_size``."""
        if blank is not None:
            try:
                return Blank(
                    width_mm=float(cast("float", blank["width_mm"])),
                    height_mm=float(cast("float", blank["height_mm"])),
                    margin_mm=float(cast("float", blank.get("margin_mm", DEFAULT_MARGIN_MM))),
                    spacing_mm=float(cast("float", blank.get("spacing_mm", DEFAULT_SPACING_MM))),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise CadOpError(
                    "invalid_params", f"blank is not a usable stock size: {exc}"
                ) from exc
            except ValidationError as exc:
                raise CadOpError("invalid_params", str(exc)) from exc
        declared = self._declared_blank_size(name, source_ref)
        if declared is None:
            raise CadOpError(
                "blank_unknown",
                f"part {name!r} declares no part.blank_size for the exported artifact; pass "
                "blank={'width_mm': …, 'height_mm': …} to nest it",
                data={"part": name, "source_artifact_ref": source_ref},
            )
        parsed = blank_from_metadata(declared)
        if parsed is None:
            raise CadOpError(
                "blank_unknown",
                f"part.blank_size {declared!r} names no 'W x H' stock size; pass "
                "blank={'width_mm': …, 'height_mm': …} to nest it",
                data={"part": name, "blank_size": declared},
            )
        return parsed

    def _declared_blank_size(self, name: str, source_ref: str) -> str | None:
        """``part.blank_size`` of the script that produced ``source_ref``, or None.

        Manufacturing metadata is authored in the script and is not carried by a
        published BRep, so it is read statically from the part source — but only
        while that source still hashes to the exported artifact's frozen input.
        Exporting a historical artifact, or one whose script has since been
        edited, yields None and the caller must state the blank explicitly
        rather than have a drifted intent silently applied.
        """
        publisher = self._publisher()
        result = publisher.current_result(name)
        if result is None or result.artifact_ref != source_ref:
            return None
        try:
            snapshot = publisher.parts.read_part(name)
        except AddressingError:
            return None
        if snapshot.content_hash != result.input_hashes.script:
            return None
        return blank_size_literal(snapshot.content)

    def _export_row(self, op_id: str) -> Mapping[str, Any] | None:
        raw = self._store.db.conn.execute(
            f"SELECT * FROM {_EXPORTS_TABLE} WHERE op_id = ?", (op_id,)
        ).fetchone()
        return None if raw is None else cast("Mapping[str, Any]", raw)

    def _replay_export(self, row: Mapping[str, Any]) -> dict[str, Any]:
        """A committed retry reconciles to the recorded source/outputs exactly."""
        return self._replay_commit(row).to_result()

    def _replay_commit(self, row: Mapping[str, Any]) -> ExportCommit:
        """The recorded commit of a ``COMMITTED`` row, pins and links reapplied."""
        source_ref = str(row["source_artifact_ref"])
        recorded = _recorded_outputs(row)
        input_hashes = cast("dict[str, Any]", _row_json(row, "source_input_hashes", {}))
        extra = cast("dict[str, Any]", _row_json(row, "extra", {}))
        paths: list[str] = []
        export_hashes: dict[str, str] = {}
        for rel, export_blob in recorded:
            # Reapply the idempotent completion steps so recovery converges from
            # any crash point between install, pin and link.
            self._store.gc.pin(export_blob)
            self._store.gc.link(export_blob, blob_hash_of_ref(source_ref))
            paths.append(str(Path(".heph") / "exports" / rel))
            export_hashes[rel] = export_blob
        return ExportCommit(
            paths=tuple(paths),
            source_artifact_ref=source_ref,
            source_input_hashes=input_hashes,
            export_hashes=export_hashes,
            extra=extra,
            replayed=True,
        )

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
