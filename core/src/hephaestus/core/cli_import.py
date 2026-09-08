"""``heph import`` CLI verbs: add, list (project ingress into ``imports/``).

Kernel import already exists: ``import_step`` (``INGEST.md`` §1) and
``import_mesh`` / ``import_point_cloud`` (``MESH_INGEST.md``) resolve files
that live under ``imports/``. ``heph reference add`` is the operator-side
home for documents. This verb group is the geometry counterpart — admit a
vendor STEP or a scan into the project without hand-copying — and nothing
else. It does not reconstruct a surface, recognise features, or paint the
browser. ``INTERFACE.md`` §15.37 still defers viewport drop.

- ``heph import add FILE [--units {mm,cm,m,in}] [--name NAME] [--part NAME]
  [--json]`` copies the file into ``imports/`` (path confinement, no symlink
  escape, original untouched) and optionally seeds ``parts/<name>.py`` through
  the same ``create_part`` contract as ``heph part create``. For a mesh that
  seed is the Stage 12 path (``import_mesh`` + ``mesh_to_solid``); a point
  cloud refuses ``point_cloud_has_no_solid``. Reconstruction is not a verb.
- ``heph import list [--json]`` lists admitted files under ``imports/``.
- After a mesh ``--part`` seed the operator path is ``heph build`` then
  ``heph scan`` / ``heph scan check``. ``mesh_to_solid`` may refuse
  ``mesh_solid_invalid`` (MESH_INGEST.md §4.3). Viewport drop stays deferred.

Exit codes match the engine CLI: 0 success, 1 the operation ran and the
answer was no, 2 usage.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import stat as stat_module
import sys
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final, cast

from hephaestus.core.cli_errors import (
    CliUsageError,
    guard,
    json_listing,
    project_root_or_refuse,
    require_input_file,
)
from hephaestus.core.errors import ValidationError
from hephaestus.core.executor.imports import (
    IMPORTS_DIRNAME,
    ImportKind,
    ImportResolutionError,
    max_bytes_for_kind,
    read_import,
    validate_import_path,
)
from hephaestus.core.project_store.layout import ProjectLayout, load_project, open_store
from hephaestus.core.project_store.locks import PROJECT_CONFIG_LOCK, LockManager
from hephaestus.core.project_store.store import ProjectStore, WriteConflictError
from opstore.types import JSONValue

from opstore import OpStore, canonical_json, sha256_bytes

__all__ = [
    "ADMISSIONS_POINTER",
    "STEP_SUFFIXES",
    "AdmissionIndex",
    "ImportAdmission",
    "add_subparsers",
    "classify_import_name",
    "seed_part_script",
    "write_import_copy",
]

_PART_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

#: STEP application-protocol suffixes (AP203/AP214). Case-insensitive at
#: classify time; the copied name is stored as the operator wrote it.
STEP_SUFFIXES: Final[frozenset[str]] = frozenset({".step", ".stp"})


class ImportIngressError(ValidationError):
    """Named refusal at project ingress (suffix, units, or seed).

    ``reason`` is the stable code. It is appended to the message the same way
    :class:`~hephaestus.core.executor.imports.ImportResolutionError` does for
    mesh refusals, so a caller that only sees the §8-style printed line still
    has the name.
    """

    def __init__(self, message: str, *, reason: str) -> None:
        if f"[{reason}]" not in message:
            message = f"{message} [{reason}]"
        super().__init__(message, kind="contract")
        self.reason = reason


def classify_import_name(name: str) -> ImportKind:
    """``step`` / ``mesh`` / ``points`` for an admitted filename, or a named refusal."""
    suffix = Path(name).suffix.lower()
    if suffix in STEP_SUFFIXES:
        return "step"
    from hephaestus.geom.mesh import MESH_EXTENSIONS, extension_kind

    kind = extension_kind(name)
    if kind is not None:
        return kind
    supported = sorted({*STEP_SUFFIXES, *MESH_EXTENSIONS})
    raise ImportIngressError(
        f"import {name!r}: unsupported extension {suffix!r} "
        f"(supported: {supported}); this is project ingress, not a new kernel",
        reason="unsupported_import_suffix",
    )


def seed_part_script(copied_name: str, *, kind: ImportKind, units: str | None) -> str:
    """The ``create_part`` script that names the copied file with the injected term.

    STEP is the exact assignment ``part.geometry = import_step("…")``. Mesh is
    ``import_mesh`` plus ``mesh_to_solid`` with the declared unit. A point
    cloud has no solid conversion without surface reconstruction, which this
    verb does not invent.
    """
    injected = json.dumps(copied_name)
    if kind == "step":
        return f"part.geometry = import_step({injected})\n"
    if kind == "mesh":
        if units is None:  # pragma: no cover - callers validate first
            raise ImportIngressError(
                "units= is required on a mesh import", reason="mesh_units_undeclared"
            )
        unit = json.dumps(units)
        return (
            f"scan = import_mesh({injected}, units={unit})\n"
            f'part.geometry = mesh_to_solid(scan, intent="measurement_target")\n'
        )
    raise ImportIngressError(
        "a point cloud cannot seed a part: mesh_to_solid needs a mesh, and "
        "surface reconstruction is out of scope (MESH_INGEST.md §3)",
        reason="point_cloud_has_no_solid",
    )


def _require_units(kind: ImportKind, units: str | None) -> str | None:
    """STEP forbids ``--units``; mesh and points require one of the closed set."""
    if kind == "step":
        if units is not None:
            raise ImportIngressError(
                "STEP carries its own units (AP203/AP214); --units is only for "
                "STL/PLY/OBJ/OFF/XYZ, which carry none (INGEST.md §1, MESH_INGEST.md §1.3)",
                reason="step_units_not_applicable",
            )
        return None
    if units is None:
        from hephaestus.core.types import MESH_UNITS

        raise ImportIngressError(
            "units= is required on a mesh import: STL, PLY, OBJ, OFF and XYZ carry no "
            "unit, and the engine is millimetres throughout. Declare one of "
            f"{', '.join(MESH_UNITS)} (MESH_INGEST.md §1.3)",
            reason="mesh_units_undeclared",
        )
    return units


def write_import_copy(imports_dir: Path, path: str, data: bytes) -> Path:
    """Write ``data`` at ``imports_dir/path`` with the Stage 8A/12A walk.

    One directory descriptor per component, ``O_NOFOLLOW``: a symlink (leaf or
    parent) fails the walk rather than redirecting the write outside the
    project. The payload is written to an exclusive temp inode in the dest
    parent and ``rename``d onto the dest name — never ``O_TRUNC`` of an
    existing dest. A planted hardlink is a regular file; truncating it would
    write through the inode to a file outside the project. Rename replaces
    the directory entry; the outside name keeps its bytes.

    A dest that is already a symlink is still refused (``O_NOFOLLOW``), so
    this verb never plants or follows an escape hatch.
    """
    try:
        relative = validate_import_path(path)
    except ImportResolutionError as exc:
        raise ImportIngressError(exc.message, reason=exc.reason) from exc
    if imports_dir.exists() and (imports_dir.is_symlink() or not imports_dir.is_dir()):
        raise ImportIngressError(
            f"{IMPORTS_DIRNAME}/ is not a real directory; refusing to write {path!r}",
            reason="path_confinement",
        )
    imports_dir.mkdir(parents=True, exist_ok=True)
    if imports_dir.is_symlink():
        raise ImportIngressError(
            f"{IMPORTS_DIRNAME}/ resolved through a symlink; refusing to write {path!r}",
            reason="path_confinement",
        )
    dir_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
    try:
        root_fd = os.open(imports_dir, dir_flags)
    except OSError as exc:
        raise ImportIngressError(
            f"{IMPORTS_DIRNAME}/ is not a writable directory ({exc.strerror})",
            reason="path_confinement",
        ) from exc
    opened: list[int] = [root_fd]
    fd = root_fd
    tmp_name: str | None = None
    handle: int | None = None
    try:
        for component in relative.parts[:-1]:
            try:
                os.mkdir(component, dir_fd=fd)
            except FileExistsError:
                pass
            except OSError as exc:
                raise ImportIngressError(
                    f"import {path!r}: cannot create directory {component!r} "
                    f"beneath {IMPORTS_DIRNAME}/ ({exc.strerror})",
                    reason="path_confinement",
                ) from exc
            try:
                nxt = os.open(component, dir_flags | os.O_NOFOLLOW, dir_fd=fd)
            except OSError as exc:
                raise ImportIngressError(
                    f"import {path!r}: path component {component!r} is not a real "
                    f"directory beneath {IMPORTS_DIRNAME}/ ({exc.strerror}); "
                    "symlinks are never followed",
                    reason="path_confinement",
                ) from exc
            opened.append(nxt)
            fd = nxt
        leaf = relative.parts[-1]
        tmp_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
        for _ in range(8):
            candidate = f".heph-import-{uuid.uuid4().hex}.tmp"
            try:
                handle = os.open(candidate, tmp_flags, 0o644, dir_fd=fd)
            except FileExistsError:
                continue
            tmp_name = candidate
            break
        if handle is None or tmp_name is None:
            raise ImportIngressError(
                f"import {path!r} could not create an exclusive temp under {IMPORTS_DIRNAME}/",
                reason="path_confinement",
            )
        try:
            info = os.fstat(handle)
            if not stat_module.S_ISREG(info.st_mode):
                raise ImportIngressError(
                    f"import {path!r} temp is not a regular file",
                    reason="path_confinement",
                )
            with os.fdopen(os.dup(handle), "wb") as stream:
                stream.write(data)
        except OSError as exc:
            raise ImportIngressError(
                f"import {path!r} could not be written ({exc.strerror})",
                reason="unreadable_import",
            ) from exc
        finally:
            os.close(handle)
            handle = None
        try:
            dest_info = os.stat(leaf, dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            dest_info = None
        except OSError as exc:
            raise ImportIngressError(
                f"import {path!r} cannot be replaced beneath {IMPORTS_DIRNAME}/ "
                f"({exc.strerror}); symlinks are never followed",
                reason="path_confinement",
            ) from exc
        if dest_info is not None and stat_module.S_ISLNK(dest_info.st_mode):
            raise ImportIngressError(
                f"import {path!r} is not a regular file beneath {IMPORTS_DIRNAME}/ "
                "(symlinks are never followed)",
                reason="path_confinement",
            )
        if dest_info is not None and not stat_module.S_ISREG(dest_info.st_mode):
            raise ImportIngressError(
                f"import {path!r} is not a regular file",
                reason="path_confinement",
            )
        try:
            os.replace(tmp_name, leaf, src_dir_fd=fd, dst_dir_fd=fd)
        except OSError as exc:
            raise ImportIngressError(
                f"import {path!r} cannot be written beneath {IMPORTS_DIRNAME}/ "
                f"({exc.strerror}); symlinks are never followed",
                reason="path_confinement",
            ) from exc
        tmp_name = None
    finally:
        if handle is not None:
            os.close(handle)
        if tmp_name is not None:
            with contextlib.suppress(OSError):
                os.unlink(tmp_name, dir_fd=fd)
        for opened_fd in reversed(opened):
            os.close(opened_fd)
    return Path(imports_dir, *relative.parts)


def _iter_import_relpaths(imports_dir: Path) -> tuple[str, ...]:
    """Regular files beneath ``imports/``, no symlink components, posix-relative."""
    if not imports_dir.is_dir() or imports_dir.is_symlink():
        return ()
    found: list[str] = []

    def walk(rel: str) -> None:
        current = imports_dir if rel == "" else imports_dir / rel
        if current.is_symlink() or not current.is_dir():
            return
        for child in sorted(current.iterdir(), key=lambda item: item.name):
            name = child.name if rel == "" else f"{rel}/{child.name}"
            if child.is_symlink():
                continue
            if child.is_dir():
                walk(name)
            elif child.is_file():
                found.append(name)

    walk("")
    return tuple(found)


#: Opstore pointer naming the current admission-index generation. The index is
#: the *declaration* record, distinct from the projection's ``import_state``
#: (which is the live ``{path: sha256}`` build input tree): a unit is not
#: recoverable from a mesh file, which is exactly why ``--units`` is compulsory
#: (``MESH_INGEST.md``), so discarding it after admission is the failure that
#: clause guards against (ledger J-cli-robustness-8).
ADMISSIONS_POINTER: Final[str] = "imports-admissions"


@dataclass(frozen=True)
class ImportAdmission:
    """One recorded ``heph import add``: what was admitted, and as what."""

    name: str
    kind: ImportKind
    sha256: str
    units: str | None = None

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "name": self.name,
            "kind": self.kind,
            "sha256": self.sha256,
            "units": self.units,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, JSONValue]) -> ImportAdmission:
        name = data.get("name")
        kind = data.get("kind")
        digest = data.get("sha256")
        if not (isinstance(name, str) and isinstance(digest, str)):
            raise ValidationError("import admission is malformed", kind="contract")
        if kind not in ("step", "mesh", "points"):
            raise ValidationError(f"import admission {name}: unknown kind", kind="contract")
        units = data.get("units")
        return cls(
            name=name,
            kind=kind,
            sha256=digest,
            units=units if isinstance(units, str) else None,
        )


@dataclass(frozen=True)
class AdmissionState:
    """One immutable admission-index generation."""

    generation: int
    entries: tuple[ImportAdmission, ...]
    blob: str | None
    parent: str | None = None

    @property
    def by_name(self) -> dict[str, ImportAdmission]:
        return {entry.name: entry for entry in self.entries}

    def document(self) -> JSONValue:
        return {
            "generation": self.generation,
            "parent": self.parent,
            "entries": [entry.to_json() for entry in self.entries],
        }

    @classmethod
    def from_document(cls, data: Mapping[str, JSONValue], blob: str) -> AdmissionState:
        generation = data.get("generation")
        if not isinstance(generation, int) or isinstance(generation, bool):
            raise ValidationError("admission index generation must be an integer", kind="contract")
        raw = data.get("entries")
        if not isinstance(raw, list):
            raise ValidationError("admission index entries must be an array", kind="contract")
        parent = data.get("parent")
        return cls(
            generation=generation,
            entries=tuple(
                ImportAdmission.from_json(cast("Mapping[str, JSONValue]", item))
                for item in cast("list[JSONValue]", raw)
                if isinstance(item, dict)
            ),
            blob=blob,
            parent=parent if isinstance(parent, str) else None,
        )


_EMPTY_ADMISSIONS: Final[AdmissionState] = AdmissionState(
    generation=0, entries=(), blob=None, parent=None
)


class AdmissionIndex:
    """What ``heph import add`` declared, kept as an immutable generation chain.

    The same generation-under-lock shape
    :class:`hephaestus.core.project_store.references.ReferenceRegistry` uses, and
    for the same reason: an admission is an operator claim that later work is
    checked against, so it needs a parent chain rather than a mutable file. It
    is deliberately *not* the projection's ``import_state`` — that records the
    live bytes of every file under ``imports/`` and is what makes an importer
    stale; this records what an operator said those bytes *are*.
    """

    def __init__(self, layout: ProjectLayout, store: OpStore) -> None:
        self.layout = layout
        self._store = store

    def state(self) -> AdmissionState:
        """The current generation (empty generation 0 when nothing was recorded)."""
        blob = self._store.blobs.read_pointer(ADMISSIONS_POINTER)
        if blob is None:
            return _EMPTY_ADMISSIONS
        raw = json.loads(self._store.blobs.get(blob).decode("utf-8"))
        if not isinstance(raw, dict):  # pragma: no cover - our own canonical JSON
            raise ValidationError("admission index document is malformed", kind="contract")
        return AdmissionState.from_document(cast("Mapping[str, JSONValue]", raw), blob)

    def get(self, name: str) -> ImportAdmission | None:
        """The recorded admission for ``name``, or ``None`` for a hand-copied file."""
        return self.state().by_name.get(name)

    def record(self, admission: ImportAdmission) -> AdmissionState:
        """Publish one new generation carrying ``admission`` (upsert by name)."""
        locks = LockManager(self._store)
        with locks.holding(PROJECT_CONFIG_LOCK):
            current = self.state()
            kept = tuple(entry for entry in current.entries if entry.name != admission.name)
            candidate = AdmissionState(
                generation=current.generation + 1,
                entries=tuple(sorted((*kept, admission), key=lambda item: item.name)),
                blob=None,
                parent=current.blob,
            )
            new_blob = self._store.blobs.put(canonical_json(candidate.document()).encode("utf-8"))
            self._store.gc.pin(new_blob)
            self._store.blobs.cas_swap(ADMISSIONS_POINTER, current.blob, new_blob)
            return replace(candidate, blob=new_blob)


def _record(
    name: str,
    *,
    kind: ImportKind,
    digest: str,
    units: str | None,
    recorded: bool = True,
) -> dict[str, JSONValue]:
    """One ``heph import list`` row.

    ``units`` is always present — ``null`` for a STEP (where the flag is
    forbidden) and for a file hand-copied into ``imports/`` — and ``recorded``
    says which of those two a ``null`` is: a listing that hides an
    unrecorded file would be worse than one that admits it does not know.
    """
    return {
        "kind": kind,
        "name": name,
        "path": f"{IMPORTS_DIRNAME}/{name}",
        "recorded": recorded,
        "sha256": digest,
        "units": units,
    }


def _copy_source(source: Path) -> bytes:
    """Read the operator's file as bytes. The original is never modified.

    A symlink source is followed for the read (the operator pointed at a path)
    and the destination write plants a regular file, so ``imports/`` never
    gains an escape hatch.
    """
    require_input_file(source, what="import source")
    return source.read_bytes()


def _refuse_contradictory_readmission(
    prior: ImportAdmission, *, digest: str, units: str | None
) -> None:
    """Re-admitting the same name with different bytes or a different unit refuses.

    Identical bytes under an identical declaration is an idempotent success —
    the copy helper is idempotent by rename, so re-running the command is a
    legitimate no-op. Anything else silently rewrites geometry that earlier work
    depends on, and (before the admission index existed) left nothing to audit
    it against, so it is refused by name with ``--redeclare`` as the explicit
    escape (ledger J-cli-robustness-9).
    """
    if prior.sha256 != digest:
        raise ImportIngressError(
            f"import {prior.name!r} was admitted as {prior.sha256} and these bytes are "
            f"{digest}; pass --redeclare to replace it (importing parts go stale)",
            reason="import_bytes_conflict",
        )
    if prior.units != units:
        raise ImportIngressError(
            f"import {prior.name!r} was admitted with units={prior.units!r} and this "
            f"declares units={units!r}; pass --redeclare to replace the declaration",
            reason="import_unit_conflict",
        )


def _cmd_add(args: argparse.Namespace) -> int:
    source = Path(cast("str", args.path))
    data = _copy_source(source)
    dest_name = cast("str | None", args.name) or source.name
    kind = classify_import_name(dest_name)
    units = _require_units(kind, cast("str | None", args.units))
    part_name = cast("str | None", args.part)
    if part_name is not None and not _PART_NAME_RE.match(part_name):
        raise CliUsageError(f"invalid part name {part_name!r}")
    script = None if part_name is None else seed_part_script(dest_name, kind=kind, units=units)

    layout = load_project(project_root_or_refuse())
    readmitted = False
    if part_name is not None and layout.part_path(part_name).is_file():
        payload = {"part": part_name, "status": "already_exists"}
        if bool(args.json):
            print(json.dumps(payload, sort_keys=True))
        else:
            print(
                f"heph: error (already_exists): part {part_name!r} already exists",
                file=sys.stderr,
            )
        return 1

    digest = sha256_bytes(data)
    opstore_for_index = open_store(layout)
    try:
        index = AdmissionIndex(layout, opstore_for_index)
        prior = index.get(dest_name)
        redeclare = bool(args.redeclare)
        if prior is not None and not redeclare:
            _refuse_contradictory_readmission(prior, digest=digest, units=units)
            # Nothing to conflict with means nothing changed: same bytes, same
            # unit, same name.
            readmitted = True
        write_import_copy(layout.imports_dir, dest_name, data)
        if not readmitted:
            # An idempotent re-run advances no generation. The chain is the
            # audit trail of what an operator *declared*, so a link that
            # records "someone re-ran the same command" is noise in the one
            # place a reader goes to ask when a unit last changed.
            index.record(ImportAdmission(name=dest_name, kind=kind, sha256=digest, units=units))
        if prior is not None and redeclare and prior.sha256 != digest:
            # INGEST.md §1: a replaced imports/ file is a changed build input,
            # so its importers go stale now rather than at the next build.
            from hephaestus.core.project_store.publication import Publisher

            Publisher(layout, opstore_for_index).sync_import_state()
    finally:
        opstore_for_index.close()
    record = _record(dest_name, kind=kind, digest=digest, units=units)

    if part_name is not None and script is not None:
        opstore = open_store(layout)
        try:
            try:
                ProjectStore(layout, opstore).write_part(
                    part_name,
                    script,
                    base_hash=None,
                    op_id=f"heph-import-add-{uuid.uuid4().hex}",
                )
            except WriteConflictError:
                payload = {"part": part_name, "status": "already_exists"}
                if bool(args.json):
                    print(json.dumps(payload, sort_keys=True))
                else:
                    print(
                        f"heph: error (already_exists): part {part_name!r} already exists",
                        file=sys.stderr,
                    )
                return 1
        finally:
            opstore.close()

    if bool(args.json):
        print(json.dumps(record, sort_keys=True))
    else:
        extra = "" if units is None else f", units={units}"
        # An identical re-admission is a success, but saying "copied" about a
        # no-op hides that the prior declaration is what still governs.
        verb = "already admitted" if readmitted else "copied"
        print(f"{verb} {dest_name} ({kind}{extra}) {digest} -> {IMPORTS_DIRNAME}/{dest_name}")
        if part_name is not None:
            print(f"created parts/{part_name}.py")
            if kind == "mesh":
                print(
                    f"scan-to-part: heph build {part_name}; "
                    f"heph scan check {part_name} {dest_name} --units {units} "
                    "(Stage 12; no reconstruction)"
                )
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    layout = load_project(project_root_or_refuse())
    opstore = open_store(layout)
    try:
        admitted = AdmissionIndex(layout, opstore).state().by_name
    finally:
        opstore.close()
    records: list[dict[str, JSONValue]] = []
    # The filesystem walk stays the source of truth for *what is there*; the
    # index supplies what was *declared*. A file copied in by hand is still
    # listed, with a null unit and recorded=false, rather than hidden.
    for name in _iter_import_relpaths(layout.imports_dir):
        try:
            kind = classify_import_name(name)
        except ImportIngressError:
            continue
        data = read_import(layout.imports_dir, name, max_bytes=max_bytes_for_kind(kind))
        digest = sha256_bytes(data)
        prior = admitted.get(name)
        records.append(
            _record(
                name,
                kind=kind,
                digest=digest,
                units=None if prior is None or prior.sha256 != digest else prior.units,
                recorded=prior is not None and prior.sha256 == digest,
            )
        )
    if bool(args.json):
        # One listing envelope, never a bare array (ledger J-cli-robustness-7).
        print(json_listing("imports", records))
        return 0
    if not records:
        print("no imports")
        return 0
    for entry in records:
        units = entry["units"]
        suffix = "" if not isinstance(units, str) else f"\tunits={units}"
        print(f"{entry['name']}\t{entry['kind']}\t{entry['sha256']}{suffix}")
    return 0


def add_subparsers(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
) -> None:
    """Register the ``import`` verb group on an existing subparser set."""
    # `core.types`, not `geom.mesh`: registration runs on every `heph`
    # invocation, and the geometry package's own `__init__` eagerly re-exports
    # build123d, OCP, scikit-learn, scipy and sympy — 1.7 s of the CLI's 2.9 s
    # startup, spent to read a four-string tuple (ledger J-cli-startup-5). The
    # constant is defined in `core.types` and re-exported from `geom.mesh`, so
    # this is the same object, not a copy of it.
    from hephaestus.core.types import MESH_UNITS

    group = sub.add_parser("import", help="admit a STEP, mesh, or point cloud into imports/")
    verbs = group.add_subparsers(dest="import_command", required=True)

    add = verbs.add_parser(
        "add", help="copy a file into imports/ (and optionally seed a part script)"
    )
    add.add_argument("path", help="file to copy (original is left untouched)")
    add.add_argument(
        "--name",
        default=None,
        help="store under this imports/-relative name (default: filename)",
    )
    add.add_argument(
        "--units",
        default=None,
        choices=list(MESH_UNITS),
        help="required for STL/PLY/OBJ/OFF/XYZ; refused for STEP (never inferred)",
    )
    add.add_argument(
        "--part",
        default=None,
        help=(
            "create parts/<name>.py via create_part (refuse if it exists; no force). "
            "STEP seeds import_step; mesh seeds import_mesh + mesh_to_solid; "
            "a point cloud is point_cloud_has_no_solid (no reconstruction)"
        ),
    )
    add.add_argument(
        "--redeclare",
        action="store_true",
        help=(
            "replace a prior admission of this name whose bytes or units differ "
            "(importing parts go stale); without it a contradiction is refused"
        ),
    )
    add.add_argument(
        "--json",
        action="store_true",
        help="emit {name, kind, sha256, path, units, recorded}",
    )
    add.set_defaults(func=guard(_cmd_add))

    listing = verbs.add_parser("list", help="list admitted files under imports/")
    listing.add_argument("--json", action="store_true", help="emit JSON records")
    listing.set_defaults(func=guard(_cmd_list))
