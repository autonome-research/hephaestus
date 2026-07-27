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

from hephaestus.core.cutfile import CUT_LAYER, LAYER_COLORS, Mark, solid_marks
from hephaestus.core.dfm import TopologyDescriptor, descriptors_from_source_map
from hephaestus.core.errors import AddressingError, ValidationError
from hephaestus.core.executor.artifact_geometry import load_brep_shape
from hephaestus.core.kerf import (
    KerfDecision,
    KerfRefusal,
    kerf_compensated_shape,
    resolve_kerf,
)
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
from hephaestus.core.types import BuildResult
from opstore.types import JSONValue

from opstore import OpStore, canonical_json, sha256_bytes, sha256_canonical_json

from ._base import CadOpError, CadOpsState
from ._dfm import DfmOps, script_metadata

#: Export formats and the file extension each produces.
EXPORT_FORMATS: Final[dict[str, str]] = {
    "step": "step",
    "dxf": "dxf",
    "svg": "svg",
    "gltf": "glb",
    "3mf": "3mf",
    "stl": "stl",
}

#: Formats whose bytes a machine drives a cutter along, and therefore the only
#: ones kerf compensation means anything for. A STEP or an STL is a *model*: it
#: must stay nominal, because whatever consumes it applies its own allowances.
CUT_PATH_FORMATS: Final[frozenset[str]] = frozenset({"dxf", "svg"})

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
# what the frozen artifact's own script said about it
#
# A published BRep carries topology and geometry and nothing else: no build123d
# labels, no §5.3 tags, no §5.2 metadata. Every export that wants to say what a
# solid *is* — a 3MF object name, a drawing's title block, a cut file's engrave
# layer — has to recover those facts from the build that produced exactly these
# bytes, and must decline when it cannot. These three readers are that rule, in
# one place, for every format writer and document generator.


def solid_labels(result: BuildResult | None, count: int) -> tuple[str, ...]:
    """Per-solid labels recovered from the build's ``geometries`` rows.

    A published BRep carries no build123d labels, so the label namespace comes
    from the build result: its rows are the geometry tree in order and each row
    states how many solids it owns, which partitions ``shape.solids()``. When
    the rows do not account for exactly the artifact's solids (a historical
    artifact, a mismatched result) the solids are named positionally instead of
    being given labels that might belong to different geometry.
    """
    if result is None:
        return tuple(f"solid#{i + 1}" for i in range(count))
    rows = [(entry.label, entry.solids) for entry in result.geometries]
    if sum(solids for _, solids in rows) != count:
        return tuple(f"solid#{i + 1}" for i in range(count))
    labels: list[str] = []
    for label, solids in rows:
        for offset in range(solids):
            labels.append(label if solids == 1 else f"{label}[{offset + 1}]")
    return tuple(labels)


class FrozenMetadataOps(CadOpsState):
    """Reading a frozen artifact's authored metadata, labels and tags."""

    def frozen_script_metadata(self, name: str, source_ref: str) -> Mapping[str, str]:
        """§5.2 metadata of the script that produced ``source_ref`` (else empty).

        Manufacturing metadata is authored in the part script and is not carried
        by a published BRep, so it is read statically from the source — and only
        while that source still hashes to the artifact's frozen script input. A
        drifted or historical artifact yields no metadata rather than a title
        block (or a bill of materials, or a 3MF package) describing a part these
        bytes are not.
        """
        publisher = self._publisher()
        result = publisher.current_result(name)
        if result is None or result.artifact_ref != source_ref:
            return {}
        try:
            snapshot = publisher.parts.read_part(name)
        except AddressingError:  # pragma: no cover - a deleted script is not a failure here
            return {}
        if snapshot.content_hash != result.input_hashes.script:
            return {}
        return script_metadata(snapshot.content)

    def frozen_result(self, name: str, source_ref: str) -> BuildResult | None:
        """The published build result that produced ``source_ref``, if it is current."""
        result = self._publisher().current_result(name)
        return result if result is not None and result.artifact_ref == source_ref else None

    def artifact_tags(
        self, result: BuildResult | None, source_ref: str
    ) -> Mapping[str, TopologyDescriptor]:
        """Tag names bound to artifact topology, from the build's source map.

        A reloaded BRep has no tags of its own; the source map is the only thing
        that can put the script's names back onto this artifact's topology, and
        it is only used when it belongs to exactly these bytes.
        """
        if result is None or result.source_map_ref is None or result.artifact_ref != source_ref:
            return {}
        blob = blob_hash_of_ref(result.source_map_ref)
        if not self._store.blobs.has(blob):
            return {}
        loaded: object = json.loads(self._store.blobs.get(blob).decode("utf-8"))
        if not isinstance(loaded, dict):
            return {}
        return descriptors_from_source_map(cast("Mapping[str, JSONValue]", loaded))


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


@dataclass(frozen=True)
class MeshObject:
    """One 3MF ``<object>``: a named mesh that is a whole labelled solid.

    3MF's advantage over STL is precisely that a build is a *set of named
    objects* rather than one anonymous triangle soup. ``name`` is the geometry
    label the part script authored (recovered by :func:`solid_labels`), so a
    box-and-lid part opens in a slicer as two selectable objects called ``box``
    and ``lid`` instead of one merged shell nobody can assign a material to.
    """

    name: str
    vertices: tuple[tuple[float, float, float], ...]
    triangles: tuple[tuple[int, int, int], ...]


#: 3MF core metadata names a package may carry at model level. Everything else
#: MUST be namespace-qualified per the core spec, which is why the part's §5.2
#: manufacturing fields are emitted under :data:`THREEMF_NS_PREFIX` below.
THREEMF_CORE_METADATA: Final[tuple[str, ...]] = (
    "Title",
    "Designer",
    "Description",
    "Application",
)

#: Namespace for the §5.2 fields 3MF has no reserved name for (material,
#: process, stock form, tolerance, finish). Declared on ``<model>`` so the
#: package stays conformant instead of inventing bare metadata names.
THREEMF_NS_PREFIX: Final[str] = "heph"
THREEMF_NS_URI: Final[str] = "https://hephaestus.dev/3mf/2026/01"

#: §5.2 metadata field -> the namespaced 3MF metadata name it becomes.
THREEMF_METADATA_FIELDS: Final[tuple[tuple[str, str], ...]] = (
    ("material_spec", "Material"),
    ("process", "Process"),
    ("stock_form", "StockForm"),
    ("general_tolerance", "Tolerance"),
    ("finish", "Finish"),
)


def three_mf_metadata(
    part: str, project: str, metadata: Mapping[str, str]
) -> tuple[tuple[str, str], ...]:
    """Model-level 3MF metadata for one part, in a fixed order.

    ``Title`` is the part, ``Designer`` the project that authored it,
    ``Description`` the part's own §5.2 description and ``Application`` this
    engine. The remaining §5.2 fields — material above all, which is what a
    slicer or a shop actually needs and what an STL can never carry — follow
    under the ``heph:`` namespace, and a field the part never declared is
    simply absent rather than present and empty.
    """
    out: list[tuple[str, str]] = [("Title", part)]
    if project:
        out.append(("Designer", project))
    description = metadata.get("description", "").strip()
    if description:
        out.append(("Description", description))
    out.append(("Application", "Hephaestus"))
    for field_name, label in THREEMF_METADATA_FIELDS:
        value = metadata.get(field_name, "").strip()
        if value:
            out.append((f"{THREEMF_NS_PREFIX}:{label}", value))
    return tuple(out)


def _write_3mf(objects: Sequence[MeshObject], *, metadata: Sequence[tuple[str, str]] = ()) -> bytes:
    """A deterministic 3MF core-spec package: one ``<object>`` per mesh.

    Every object is referenced by the ``<build>`` section — an object no build
    item names is resource the consumer never places, which is a silently
    dropped part — and carries its label as the ``name`` attribute. Model
    metadata is written in the given order. Stdlib ``zipfile``/string
    templating only: trimesh's 3MF writer needs ``lxml``, which is not in the
    dependency set, and a production format is not worth a new dependency.
    """
    from xml.sax.saxutils import escape, quoteattr

    if not objects:  # pragma: no cover - callers always pass at least one mesh
        raise CadOpError("export_failed", "3mf export has no solid to write")
    resources: list[str] = []
    items: list[str] = []
    for index, obj in enumerate(objects, start=1):
        verts = "".join(
            f'<vertex x="{x:.6f}" y="{y:.6f}" z="{z:.6f}"/>' for x, y, z in obj.vertices
        )
        tris = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in obj.triangles)
        resources.append(
            f'<object id="{index}" type="model" name={quoteattr(obj.name)}><mesh>'
            f"<vertices>{verts}</vertices><triangles>{tris}</triangles>"
            "</mesh></object>"
        )
        items.append(f'<item objectid="{index}"/>')
    meta = "".join(
        f"<metadata name={quoteattr(name)}>{escape(value)}</metadata>" for name, value in metadata
    )
    model = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<model unit="millimeter" xml:lang="en-US" '
        'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
        f'xmlns:{THREEMF_NS_PREFIX}="{THREEMF_NS_URI}">'
        f"{meta}"
        f"<resources>{''.join(resources)}</resources>"
        f"<build>{''.join(items)}</build>"
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


def _solid_mesh(solid: object, path: Path) -> tuple[_Vertices, _Triangles]:
    """One solid tessellated to (vertices, triangles) through a binary STL."""
    import importlib

    e3: Any = importlib.import_module("build123d.exporters3d")
    e3.export_stl(cast("Any", solid), path, ascii_format=False)
    if not path.is_file():  # pragma: no cover - the exporter raises first
        raise CadOpError("export_failed", "stl exporter produced no mesh for a solid")
    return _binary_stl_mesh(path.read_bytes())


def three_mf_objects(shape: object, labels: Sequence[str], scratch: Path) -> tuple[MeshObject, ...]:
    """One :class:`MeshObject` per solid of ``shape``, named by ``labels``.

    ``labels`` is :func:`solid_labels` over the same artifact, so index *i* here
    and index *i* there are the same solid: ``shape.solids()`` is the order both
    the build result's geometry rows and the tag descriptors address. A solid
    the labels do not reach is named positionally rather than borrowing its
    neighbour's name.
    """
    solids: list[Any] = list(cast("Any", shape).solids())
    return tuple(
        MeshObject(
            name=labels[index] if index < len(labels) else f"solid#{index + 1}",
            vertices=tuple(vertices),
            triangles=tuple(triangles),
        )
        for index, (vertices, triangles) in (
            (i, _solid_mesh(solid, scratch / f"solid-{i}.stl")) for i, solid in enumerate(solids)
        )
    )


def _as_built_dxf(shape: object, marks: Sequence[Mark], target: Path) -> None:
    """The as-built +Z projection as a DXF, on the cut-file layers.

    The hidden-line ``Drawing`` projection is the through-cut outline and goes
    on ``CUT``; the part's own ``engrave_*``/``score_*`` tagged topology, already
    projected onto XY by :func:`~hephaestus.core.cutfile.solid_marks`, is
    re-emitted as flat polylines on its layer. Only layers that receive geometry
    are declared, so a part that tagged nothing produces a plain single-layer
    cut file rather than three empty job entries.
    """
    import importlib

    e2: Any = importlib.import_module("build123d.exporters")
    drawing: Any = e2.Drawing(
        cast("Any", shape), look_from=(0, 0, 1), look_up=(0, 1, 0), with_hidden=False
    )
    exporter: Any = e2.ExportDXF(unit=e2.Unit.MM)
    exporter.add_layer(CUT_LAYER, color=e2.ColorIndex(LAYER_COLORS[CUT_LAYER]))
    exporter.add_shape(drawing.visible_lines, layer=CUT_LAYER)
    for layer in sorted({mark.layer for mark in marks}):
        exporter.add_layer(layer, color=e2.ColorIndex(LAYER_COLORS[layer]))
    for mark in marks:
        exporter.add_shape(_mark_shape(mark), layer=mark.layer)
    exporter.write(target)


def _shape_marks(shape: object, tags: Mapping[str, TopologyDescriptor]) -> tuple[Mark, ...]:
    """Every ``engrave_*``/``score_*`` contour of a whole shape, projected on XY.

    The as-built layout looks down +Z, so a tagged face or edge projects by
    dropping its Z — the same projection the hidden-line ``Drawing`` applies to
    the outline it puts on ``CUT``.
    """
    solids: list[Any] = list(cast("Any", shape).solids())
    return tuple(
        mark for index, solid in enumerate(solids) for mark in solid_marks(solid, tags, index)
    )


def _mark_shape(mark: Mark) -> object:
    """A mark's polyline as flat build123d geometry (z = 0), closed or open."""
    from build123d import Polyline

    points = [*mark.points, mark.points[0]] if mark.closed else list(mark.points)
    return Polyline(*[(x, y, 0.0) for x, y in points])


def _export_bytes(shape: object, fmt: str, scratch: Path, *, marks: Sequence[Mark] = ()) -> bytes:
    """Render one export format's bytes from a reloaded BRep shape.

    build123d's exporter signatures are generic over an unparameterized ``Shape``,
    so the interop surface is deliberately confined to this function's explicitly
    ``Any``-typed locals rather than leaking partially-unknown types outward.
    STEP / STL / GLB come from ``exporters3d``; DXF / SVG project the solid with
    the hidden-line ``Drawing`` first (``as_built`` = the +Z profile), the DXF
    onto the cut-file layers. 3MF is not written here — it is per *labelled
    solid* and therefore needs the build result, so ``ExportOps`` writes it.
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
    elif fmt == "dxf":
        _as_built_dxf(typed, marks, target)
    elif fmt == "svg":
        drawing: Any = e2.Drawing(typed, look_from=(0, 0, 1), look_up=(0, 1, 0), with_hidden=False)
        exporter: Any = e2.ExportSVG()
        exporter.add_shape(drawing.visible_lines)
        exporter.write(target)
    else:  # pragma: no cover - 3mf is routed away and the enum is schema-constrained
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


class ExportOps(FrozenMetadataOps):
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
        kerf_mm: float | None = None,
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
        if kerf_mm is not None and fmt not in CUT_PATH_FORMATS:
            raise CadOpError(
                "invalid_params",
                f"kerf_mm compensates a cut path: it applies to dxf/svg, not {fmt!r}",
            )
        payload_hash = sha256_canonical_json(
            {
                "kind": "export_part",
                "part": name,
                "format": fmt,
                "layout": layout,
                "artifact_ref": artifact_ref,
                "target": target,
                "blank": _blank_payload(blank),
                "kerf_mm": None if kerf_mm is None else float(kerf_mm),
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
        kerf = self._kerf_decision(name, source_ref, kerf_mm) if fmt in CUT_PATH_FORMATS else None
        with self._scratch("heph-export-") as scratch:
            shape = load_brep_shape(self._store.blobs.get(source_blob), scratch_dir=Path(scratch))
            result = self.frozen_result(name, source_ref)
            tags: Mapping[str, TopologyDescriptor] = self.artifact_tags(result, source_ref)
            # The source map's topology indices address the *nominal* artifact.
            # Compensation rebuilds each flat pattern, so tags are resolved on
            # the shape they were recorded against and only the cut path moves.
            nominal = shape
            if kerf is not None and kerf.compensates:
                shape, kerf = self._compensated(name, layout, shape, kerf)
            if layout == "nested_sheet":
                data = self._nested_sheet_bytes(name, fmt, source_ref, blank, shape, tags, nominal)
            elif fmt == "3mf":
                data = self._three_mf_bytes(name, source_ref, shape, result, Path(scratch))
            else:
                marks = _shape_marks(nominal, tags) if fmt == "dxf" else ()
                data = _export_bytes(shape, fmt, Path(scratch), marks=marks)
        return self._commit_export(
            op_id=op_id,
            part=name,
            source_ref=source_ref,
            outputs=(ExportOutput(EXPORT_FORMATS[fmt], data),),
            target=target,
            stem=name,
            extra={} if kerf is None else {"kerf": kerf.to_json()},
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
        tags: Mapping[str, TopologyDescriptor] = {},
        nominal: object | None = None,
    ) -> bytes:
        """``layout="nested_sheet"``: flat profiles packed onto the declared blank.

        Deterministic shelf packing, no rotation (mission rule 5 defers
        rotation- and yield-aware auto-nesting). ``shape`` arrives already kerf
        compensated when a kerf resolved, so the packed outlines are the cut
        path and the blank's spacing is measured between compensated profiles.
        Anything that will not fit is a structured refusal naming the profile
        and the blank — never a silent overlap and never a clipped part.

        ``tags`` carries the build's §5.3 names onto this artifact's topology so
        the writer can separate through-cuts from the part's own ``engrave_*``
        and ``score_*`` geometry (:mod:`hephaestus.core.cutfile`); ``nominal`` is
        the pre-compensation shape those names were recorded against. Empty tags
        mean every contour is a through-cut, which is the safe reading.
        """
        resolved = self._resolve_blank(name, source_ref, blank)
        try:
            profiles = flat_profiles(shape, prefix=name, tags=tags, tag_shape=nominal)
            nested = shelf_nest(profiles, resolved)
        except NestingRefusal as exc:
            raise CadOpError(exc.reason, exc.message, data=exc.data) from exc
        return layout_to_dxf(nested) if fmt == "dxf" else layout_to_svg(nested)

    # -- 3mf ---------------------------------------------------------------

    def _three_mf_bytes(
        self,
        name: str,
        source_ref: str,
        shape: object,
        result: BuildResult | None,
        scratch: Path,
    ) -> bytes:
        """``3mf``: one ``<object>`` per labelled solid, plus the part's metadata.

        A 3MF that merges a box and its lid into one mesh has thrown away the
        only thing it has over an STL. Each of the artifact's solids becomes its
        own build object carrying the geometry label the script authored, and
        the model metadata carries the part's §5.2 manufacturing fields — so the
        package states what it is, who made it, and what it is made of.
        """
        labels = solid_labels(result, len(list(cast("Any", shape).solids())))
        objects = three_mf_objects(shape, labels, scratch)
        if not objects:
            raise CadOpError(
                "export_failed",
                f"part {name!r} has no solid to write into a 3mf package",
                data={"part": name, "source_artifact_ref": source_ref},
            )
        metadata = three_mf_metadata(
            name, self._layout.manifest.name, self.frozen_script_metadata(name, source_ref)
        )
        return _write_3mf(objects, metadata=metadata)

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
        """``part.blank_size`` of the script that produced ``source_ref``, or None."""
        script = self._trusted_script(name, source_ref)
        return None if script is None else blank_size_literal(script)

    def _trusted_script(self, name: str, source_ref: str) -> str | None:
        """The part source that still hashes to ``source_ref``'s frozen input.

        §5.2 manufacturing metadata — the blank size, the process, the material —
        is authored in the script and is not carried by a published BRep, so it
        is read statically from the part source. It is only *trustworthy* while
        that source still hashes to the exported artifact's own script input:
        exporting a historical artifact, or one whose script has since been
        edited, yields None so the caller refuses (or reports that nothing was
        resolved) rather than applying a drifted intent to geometry that never
        had it.
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
        return snapshot.content

    # -- kerf compensation -------------------------------------------------

    def _kerf_decision(self, name: str, source_ref: str, kerf_mm: float | None) -> KerfDecision:
        """Which kerf this export compensates by, and where it came from.

        The order is fixed by :func:`~hephaestus.core.kerf.resolve_kerf`: the
        explicit argument, else the ``kerf_mm`` parameter of the DFM pack for
        the process the *frozen* script declares, else nothing at all. Every
        link that can be missing — a drifted script, no declared process, a
        process with no rule pack, a pack with no kerf parameter — names itself
        in the reported ``reason`` instead of falling through to an invented
        default, because a cut file compensated by a number nobody declared is
        indistinguishable from a correct one until the part is measured.
        """
        pack_kerf: float | None = None
        unavailable: str | None = None
        # The declared process is reported either way — an explicit kerf is
        # still a kerf *for* a process, and a reader comparing the two wants to
        # see which one the caller overrode.
        script = self._trusted_script(name, source_ref)
        process = (script_metadata(script).get("process") or "").strip() or None if script else None
        if kerf_mm is None:
            if script is None:
                unavailable = "source_script_unavailable"
            elif process is None:
                unavailable = "no_process"
            else:
                pack_kerf, unavailable = self._pack_kerf(process)
        try:
            return resolve_kerf(
                explicit_mm=kerf_mm,
                process=process,
                pack_kerf_mm=pack_kerf,
                unavailable=unavailable,
            )
        except ValidationError as exc:
            raise CadOpError("invalid_params", str(exc)) from exc

    def _pack_kerf(self, process: str) -> tuple[float | None, str | None]:
        """``(kerf_mm, why-not)`` from the DFM pack of one process."""
        if not isinstance(self, DfmOps):  # pragma: no cover - CadOps is DfmOps
            return None, "no_dfm_registry"
        try:
            pack = self.registries().dfm.get(process)
        except Exception:
            # A process with no rule pack is a legitimate design (an unusual
            # machine, a fork nobody published); it simply declares no kerf.
            return None, "no_dfm_pack"
        param = pack.params.get("kerf_mm")
        if param is None:
            return None, "pack_declares_no_kerf"
        return float(param.value), None

    def _compensated(
        self, name: str, layout: str, shape: object, decision: KerfDecision
    ) -> tuple[object, KerfDecision]:
        """``shape`` grown onto the waste side, or a refusal naming the profile.

        The one fallback is deliberate and narrow: an ``as_built`` projection of
        a part with no flat pattern at all (a turned boss, a printed bracket that
        merely declares a process) was never a cut path, so it keeps its
        uncompensated projection and *says so* in the result. An explicit
        ``kerf_mm`` never falls back — the caller asked for a compensated path
        and must be told it could not be produced — and a boundary that fails to
        offset (``kerf_offset_failed``) never falls back either, in any layout:
        that is exactly the silently-undersized part this whole module exists to
        prevent.
        """
        applied = decision.applied_mm
        if applied is None:  # pragma: no cover - guarded by decision.compensates
            return shape, decision
        try:
            return kerf_compensated_shape(shape, applied, prefix=name), decision
        except KerfRefusal as exc:
            fallback = (
                layout == "as_built"
                and decision.source != "explicit"
                and exc.reason in ("not_a_sheet_profile", "no_profiles")
            )
            if fallback:
                return shape, decision.uncompensated(exc.reason)
            raise CadOpError(exc.reason, exc.message, data=exc.data) from exc

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
