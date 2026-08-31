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
  the same ``create_part`` contract as ``heph part create``.
- ``heph import list [--json]`` lists admitted files under ``imports/``.

Exit codes match the engine CLI: 0 success, 1 the operation ran and the
answer was no, 2 usage.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat as stat_module
import sys
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Final, cast

from hephaestus.core.errors import ValidationError
from hephaestus.core.executor.imports import (
    IMPORTS_DIRNAME,
    ImportKind,
    ImportResolutionError,
    max_bytes_for_kind,
    read_import,
    validate_import_path,
)
from hephaestus.core.project_store.layout import find_project_root, load_project, open_store
from hephaestus.core.project_store.store import ProjectStore, WriteConflictError
from opstore.types import JSONValue

from opstore import sha256_bytes

__all__ = [
    "STEP_SUFFIXES",
    "add_subparsers",
    "classify_import_name",
    "seed_part_script",
    "write_import_copy",
]

_PART_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

#: STEP application-protocol suffixes (AP203/AP214). Case-insensitive at
#: classify time; the copied name is stored as the operator wrote it.
STEP_SUFFIXES: Final[frozenset[str]] = frozenset({".step", ".stp"})


class _UsageError(Exception):
    """CLI misuse: reported on stderr with exit code 2."""


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
        from hephaestus.geom.mesh import MESH_UNITS

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
    project. The destination is always a regular file — never a symlink — so
    a later ``import_step`` cannot escape through a link this verb planted.
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
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW | os.O_CLOEXEC
        try:
            handle = os.open(leaf, flags, 0o644, dir_fd=fd)
        except OSError as exc:
            raise ImportIngressError(
                f"import {path!r} cannot be written beneath {IMPORTS_DIRNAME}/ "
                f"({exc.strerror}); symlinks are never followed",
                reason="path_confinement",
            ) from exc
        try:
            info = os.fstat(handle)
            if not stat_module.S_ISREG(info.st_mode):
                raise ImportIngressError(
                    f"import {path!r} is not a regular file",
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
    finally:
        for handle in reversed(opened):
            os.close(handle)
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


def _record(name: str, *, kind: ImportKind, digest: str, units: str | None) -> dict[str, JSONValue]:
    out: dict[str, JSONValue] = {
        "kind": kind,
        "name": name,
        "path": f"{IMPORTS_DIRNAME}/{name}",
        "sha256": digest,
    }
    if units is not None:
        out["units"] = units
    return out


def _copy_source(source: Path) -> bytes:
    """Read the operator's file as bytes. The original is never modified.

    A symlink source is followed for the read (the operator pointed at a path)
    and the destination write plants a regular file, so ``imports/`` never
    gains an escape hatch.
    """
    if not source.is_file():
        raise _UsageError(f"no such file: {source}")
    return source.read_bytes()


def _cmd_add(args: argparse.Namespace) -> int:
    source = Path(cast("str", args.path))
    data = _copy_source(source)
    dest_name = cast("str | None", args.name) or source.name
    kind = classify_import_name(dest_name)
    units = _require_units(kind, cast("str | None", args.units))
    part_name = cast("str | None", args.part)
    if part_name is not None and not _PART_NAME_RE.match(part_name):
        raise _UsageError(f"invalid part name {part_name!r}")
    script = None if part_name is None else seed_part_script(dest_name, kind=kind, units=units)

    layout = load_project(find_project_root(Path.cwd()))
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

    write_import_copy(layout.imports_dir, dest_name, data)
    digest = sha256_bytes(data)
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
        print(f"copied {dest_name} ({kind}{extra}) {digest} -> {IMPORTS_DIRNAME}/{dest_name}")
        if part_name is not None:
            print(f"created parts/{part_name}.py")
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    layout = load_project(find_project_root(Path.cwd()))
    records: list[dict[str, JSONValue]] = []
    for name in _iter_import_relpaths(layout.imports_dir):
        try:
            kind = classify_import_name(name)
        except ImportIngressError:
            continue
        data = read_import(layout.imports_dir, name, max_bytes=max_bytes_for_kind(kind))
        records.append(_record(name, kind=kind, digest=sha256_bytes(data), units=None))
    if bool(args.json):
        print(json.dumps(records, sort_keys=True))
        return 0
    if not records:
        print("no imports")
        return 0
    for entry in records:
        print(f"{entry['name']}\t{entry['kind']}\t{entry['sha256']}")
    return 0


def _guard(command: Callable[[argparse.Namespace], int]) -> Callable[[argparse.Namespace], int]:
    def run(args: argparse.Namespace) -> int:
        try:
            return command(args)
        except _UsageError as exc:
            print(f"heph: {exc}", file=sys.stderr)
            return 2

    return run


def add_subparsers(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
) -> None:
    """Register the ``import`` verb group on an existing subparser set."""
    from hephaestus.geom.mesh import MESH_UNITS

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
        help="create parts/<name>.py via create_part (refuse if it exists; no force)",
    )
    add.add_argument("--json", action="store_true", help="emit {name, kind, sha256, path, units?}")
    add.set_defaults(func=_guard(_cmd_add))

    listing = verbs.add_parser("list", help="list admitted files under imports/")
    listing.add_argument("--json", action="store_true", help="emit JSON records")
    listing.set_defaults(func=_guard(_cmd_list))
