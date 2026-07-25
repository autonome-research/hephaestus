"""``export_part``: the §7 export contract — WAL, confinement, pins, formats.

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
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import struct
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any, Final, cast

from hephaestus.core.errors import AddressingError
from hephaestus.core.executor.artifact_geometry import load_brep_shape
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
  state TEXT NOT NULL)
"""


def ensure_exports_table(store: OpStore) -> None:
    """Create the export write-ahead table if this project has never exported."""
    store.db.conn.execute(_CREATE_EXPORTS_TABLE)


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
