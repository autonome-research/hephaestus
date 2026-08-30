"""Import resolution and staging: ``imports/`` -> hashed bytes -> staged BRep.

``INGEST.md`` §1: a part script may name an existing STEP file as a term in its
expression (``base = import_step("bracket.step")``). The script never performs
I/O for it. This module is the PROJECT side of that promise — everything
``hephaestus.geom.step_io`` deliberately refuses to know:

1. **Declaration scan** (:func:`declared_imports`). The argument of every
   ``import_step`` call is read statically out of the script's ``ast``. It MUST
   be a string literal: a computed path cannot be frozen, hashed or staged
   before the build runs, so a dynamic one is a §8 build error naming the
   statement (:class:`DynamicImportPathError`, surfaced by the worker at the
   offending line).
2. **Confinement + read** (:func:`read_import`). Each declared path is resolved
   strictly beneath ``<project>/imports/`` by walking one directory descriptor
   per component with ``O_NOFOLLOW`` — the ``openat2
   RESOLVE_BENEATH|RESOLVE_NO_SYMLINKS``-class recheck the export path already
   uses. Traversal, absolute paths and symlinks (including a racing parent
   symlink) fail the walk instead of redirecting the read; nothing is
   preflight-trusted.
3. **Staging** (:func:`stage_import`). The bytes the caller hashed are converted
   ONCE, outside the sandbox, and written read-only into the worker's input
   area under the build's out dir. The worker deserializes BRep and never sees
   a project path: ``import_step`` inside the sandbox is a dictionary lookup,
   not a file open.

Every refusal is a named :class:`ImportResolutionError` carrying a stable
``reason`` code, so the caller can turn it into the build error at the right
statement rather than guessing from message text.
"""

from __future__ import annotations

import ast
import hashlib
import os
import stat as stat_module
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Final, Literal

from hephaestus.core.errors import ValidationError

__all__ = [
    "DIFF_METHOD_NAME",
    "DIFF_TARGET_PREFIX",
    "IMPORTS_DIRNAME",
    "IMPORT_CALL_NAMES",
    "MESH_SUFFIXES",
    "SCAN_DIFF_METHOD_NAME",
    "SCAN_TARGET_PREFIX",
    "STAGE_DIRNAME",
    "DynamicImportPathError",
    "ImportDeclaration",
    "ImportKind",
    "ImportPayload",
    "ImportResolutionError",
    "ImportResolutionReason",
    "declared_imports",
    "diff_import_targets",
    "import_mesh_name",
    "import_point_cloud_name",
    "import_step_name",
    "max_bytes_for_kind",
    "max_bytes_for_path",
    "read_import",
    "scan_diff_targets",
    "stage_dir",
    "stage_import",
    "staged_filename",
    "staged_key",
    "staged_paths",
    "static_import_declarations",
    "static_import_paths",
]

#: Project-root directory holding importable STEP files (``INGEST.md`` §1).
IMPORTS_DIRNAME = "imports"
#: The worker's input area, relative to the build out dir.
STAGE_DIRNAME = "inputs"
#: The §2 injected name whose argument declares an import.
import_step_name = "import_step"
#: The two ``MESH_INGEST.md`` §1.1 injected names. They are import terms on
#: exactly the ``INGEST.md`` §1 terms — harness-resolved, string-literal path,
#: never script I/O — and differ from ``import_step`` in one respect only: the
#: file they name carries no unit, so they require one (§1.3).
import_mesh_name = "import_mesh"
import_point_cloud_name = "import_point_cloud"

#: The closed set :func:`_is_import_call` tests against, name -> declared kind.
#: A closed set rather than a growing chain of ``or`` tests, because the
#: declaration scan, the freeze and the staging must all agree about what an
#: import call *is* (mission rule 6).
IMPORT_CALL_NAMES: Final[Mapping[str, ImportKind]] = {
    import_step_name: "step",
    import_mesh_name: "mesh",
    import_point_cloud_name: "points",
}

#: The §6 measurement-facade method whose target may name an import
#: (``COMPARE.md`` §2: ``m.diff("part", "import:target.step")``).
DIFF_METHOD_NAME = "diff"
#: Prefix marking a ``m.diff`` target as an ``imports/`` file.
DIFF_TARGET_PREFIX = "import:"

#: The §6 measurement-facade method whose target may name a SCAN
#: (``MESH_INGEST.md`` §7.3: ``m.scan_diff("socket", "scan:limb-l.stl")``).
SCAN_DIFF_METHOD_NAME = "scan_diff"
#: Prefix marking a ``m.scan_diff`` target as a scan beneath ``imports/``.
SCAN_TARGET_PREFIX = "scan:"

#: What kind of thing a declaration names. ``step`` is a B-rep import (Stage
#: 8A); ``mesh`` and ``points`` are *mesh assets*, a different kind and not a
#: further STEP-like format (``MESH_INGEST.md`` §1, ``INGEST.md`` §1 as amended).
ImportKind = Literal["step", "mesh", "points"]

#: Staged-file suffix per kind (§1.5.1). Two suffixes, not one, because a point
#: cloud must never deserialize as a mesh with zero triangles.
MESH_SUFFIXES: Final[Mapping[str, str]] = {
    "step": ".brep",
    "mesh": ".hmesh",
    "points": ".hpts",
}

#: ``MESH_INGEST.md`` §1.7: five Stage 8A codes plus the eleven this stage adds.
#: The set is CLOSED — a refusal with no code here is a defect in the spec, to
#: be fixed by adding a code rather than by widening an existing one.
ImportResolutionReason = Literal[
    "invalid_import_path",
    "import_not_found",
    "path_confinement",
    "unreadable_import",
    "unreadable_step",
    "mesh_format_unsupported",
    "mesh_format_mismatch",
    "mesh_unreadable",
    "mesh_empty",
    "mesh_multi_object",
    "mesh_not_finite",
    "mesh_degenerate_only",
    "mesh_units_undeclared",
    "mesh_units_unsupported",
    "mesh_units_conflict",
    "mesh_import_too_large",
    "scan_target_ambiguous_units",
]


#: The subset of :data:`ImportResolutionReason` this stage added — the
#: ``MESH_INGEST.md`` §1.7 vocabulary. Only these get the derived code suffix
#: below; the five Stage 8A codes keep their message text byte-for-byte, because
#: G8A pins that text and this stage amends the mesh half of the vocabulary, not
#: the STEP half (`mission_plan.md` — other stages' gate text is never edited).
MESH_RESOLUTION_REASONS: Final[frozenset[str]] = frozenset(
    {
        "mesh_format_unsupported",
        "mesh_format_mismatch",
        "mesh_unreadable",
        "mesh_empty",
        "mesh_multi_object",
        "mesh_not_finite",
        "mesh_degenerate_only",
        "mesh_units_undeclared",
        "mesh_units_unsupported",
        "mesh_units_conflict",
        "mesh_import_too_large",
        # §1.5.1's ambiguity, named. It is NOT one of the eleven §1.7 admission
        # codes (nothing is wrong with the FILE — the script declared one path
        # at two units and a check named it without saying which), so it is not
        # in ``geom.mesh.MESH_REFUSALS``; it is here because it is decided while
        # resolving a declared import and because a refusal this stage leaves
        # unnamed is a refusal its own house rule forbids. Added by the third
        # repair pass, with MESH_INGEST.md §10 and §1.5.1 amended to match.
        "scan_target_ambiguous_units",
    }
)


class ImportResolutionError(ValidationError):
    """A declared import could not be resolved, read, or converted.

    ``reason`` is the stable code; ``path`` is the declared relative path as
    written in the script.

    For a §1.7 mesh reason the code is appended to the message here rather than
    written by hand at the raise site, for the reason
    :class:`~hephaestus.geom.mesh.MeshReadError` states: the ``reason`` object
    does not survive the crossing into the §8 build error record, so a message
    that named its own code could keep saying one thing while ``reason=`` said
    another. Deriving it makes them one fact. A message that already carries its
    code — because it was composed by ``MeshReadError`` and re-wrapped here — is
    left alone rather than stuttering it twice.
    """

    def __init__(self, message: str, *, reason: ImportResolutionReason, path: str) -> None:
        if reason in MESH_RESOLUTION_REASONS and f"[{reason}]" not in message:
            message = f"{message} [{reason}]"
        super().__init__(message, kind="contract")
        self.reason: ImportResolutionReason = reason
        self.path = path


class DynamicImportPathError(ValidationError):
    """``import_step`` was called with something other than a string literal."""

    def __init__(self, message: str, *, lineno: int, col: int, statement: str) -> None:
        super().__init__(message, kind="contract")
        self.lineno = lineno
        self.col = col
        self.statement = statement


@dataclass(frozen=True)
class ImportDeclaration:
    """One statically declared import call site.

    ``kind`` and ``units`` exist because the staged form differs per kind
    (``MESH_INGEST.md`` §1.5) and because the declared unit is baked into the
    staged geometry (§1.5.1) — a declared unit that stops at the AST is a
    declared unit the geometry never sees. ``units`` is ``None`` for STEP and
    for a mesh declaration that omitted it, which is a *refusal*
    (``mesh_units_undeclared``) taken at the statement, not a grammar error.
    """

    path: str
    lineno: int
    col: int
    statement_index: int
    kind: ImportKind = "step"
    units: str | None = None


@dataclass(frozen=True)
class ImportPayload:
    """The frozen bytes of one ``imports/`` file plus what was declared about it.

    ``BuildRequest.imports`` used to be ``Mapping[str, bytes]``; the declared
    kind and unit had nowhere to ride, so they stopped at the AST
    (``MESH_INGEST.md`` §1.1, §12 item 6a).

    ``units`` is a **tuple**, and the reason is a defect the singular form in
    §1.1 cannot represent: one script may declare the same path at two
    different units, and §1.5.1's own reuse property ("same bytes at a different
    declared unit ⇒ a different staged file") requires both to exist at once. A
    single ``units`` field would silently hand the second declaration the first
    one's geometry — precisely the wrong-by-25.4 failure §1.5.1 exists to
    forbid, one level up. The tuple is sorted and deduplicated; it is empty for
    STEP, which declares no unit.
    """

    data: bytes
    kind: ImportKind = "step"
    units: tuple[str, ...] = ()


def _is_import_call(node: ast.expr) -> ImportKind | None:
    """The declared kind of ``node`` when it is an import call, else ``None``."""
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
        return None
    return IMPORT_CALL_NAMES.get(node.func.id)


def declared_imports(
    module: ast.Module, *, source: str | None = None
) -> tuple[ImportDeclaration, ...]:
    """Every import declaration in ``module``, in source order.

    Raises :class:`DynamicImportPathError` at the first call whose argument is
    not a single string literal — including one built by concatenation, an
    f-string, a variable, or a keyword. The error names the statement so the
    worker can report it at its own line with the standard §8 frame.

    ``MESH_INGEST.md`` §1.1 widens the grammar by exactly one thing: the two
    mesh terms accept a ``units=`` keyword whose value must **itself** be a
    string literal. The static-literal rule is not relaxed — a computed path
    *or a computed unit* is still :class:`DynamicImportPathError` at the
    offending line, for the same reason: a value the freeze cannot read cannot
    be frozen. ``import_step`` keeps the no-keyword rule exactly as it is.
    """
    lines = (source or "").splitlines()
    out: list[ImportDeclaration] = []
    for index, top in enumerate(module.body):
        for node in ast.walk(top):
            kind = _is_import_call(node) if isinstance(node, ast.Call) else None
            if kind is None or not isinstance(node, ast.Call):
                continue
            name = node.func.id if isinstance(node.func, ast.Name) else import_step_name
            statement = lines[node.lineno - 1].strip() if 0 < node.lineno <= len(lines) else ""

            def _refuse(
                detail: str, *, at: ast.Call = node, text: str = statement
            ) -> DynamicImportPathError:
                # ``at`` and ``text`` are bound as defaults rather than closed
                # over: this runs inside the declaration loop, and a closure
                # would report whichever call the loop reached last.
                return DynamicImportPathError(
                    detail, lineno=at.lineno, col=at.col_offset, statement=text
                )

            literal = (
                node.args[0]
                if len(node.args) == 1 and isinstance(node.args[0], ast.Constant)
                else None
            )
            if literal is None or not isinstance(literal.value, str):
                raise _refuse(
                    f"{name}() requires a string literal path so the file can be "
                    "frozen and hashed before the build runs; a computed path cannot be "
                    "resolved (INGEST.md §1)"
                )
            units: str | None = None
            if kind == "step":
                if node.keywords:
                    raise _refuse(
                        f"{name}() requires a string literal path so the file can be "
                        "frozen and hashed before the build runs; a computed path cannot be "
                        "resolved (INGEST.md §1)"
                    )
            else:
                for keyword in node.keywords:
                    if keyword.arg != "units":
                        raise _refuse(
                            f"{name}() accepts one string literal path and the keyword "
                            f"units=; {keyword.arg or '**kwargs'} is not part of the "
                            "declaration grammar (MESH_INGEST.md §1.1)"
                        )
                    value = keyword.value
                    if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
                        raise _refuse(
                            f"{name}(units=…) requires a string literal unit: the declared "
                            "unit is baked into the staged geometry before the build runs, "
                            "so a computed unit cannot be frozen (MESH_INGEST.md §1.1, §1.3)"
                        )
                    units = value.value
            out.append(
                ImportDeclaration(
                    path=literal.value,
                    lineno=node.lineno,
                    col=node.col_offset,
                    statement_index=index,
                    kind=kind,
                    units=units,
                )
            )
    return tuple(out)


def diff_import_targets(module: ast.Module) -> tuple[str, ...]:
    """``imports/`` paths named by ``m.diff(..., "import:<path>")`` in ``module``.

    ``COMPARE.md`` §2 lets a ``CHECKS`` predicate compare the built part against
    a file under ``imports/``. That file is then a **build input** exactly as an
    ``import_step`` argument is: the check's verdict changes when the bytes
    change, so it must be frozen, hashed and staged with the rest (INGEST.md §1)
    rather than read live at check time from inside the sandbox — which the §2
    namespace forbids anyway.

    Only string literals are collected, and only ones that are arguments of a
    ``.diff(...)`` call. A computed target is not an error here: unlike
    ``import_step`` it is not a statement the build must run, and the facade
    refuses it at check time with an unresolvable-target message.
    """
    out: list[str] = []
    for node in ast.walk(module):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != DIFF_METHOD_NAME:
            continue
        arguments: list[ast.expr] = [*node.args, *(kw.value for kw in node.keywords)]
        for argument in arguments:
            if not isinstance(argument, ast.Constant) or not isinstance(argument.value, str):
                continue
            if argument.value.startswith(DIFF_TARGET_PREFIX):
                out.append(argument.value[len(DIFF_TARGET_PREFIX) :])
    return tuple(out)


def scan_diff_targets(module: ast.Module) -> tuple[str, ...]:
    """``imports/`` paths named by ``m.scan_diff(..., "scan:<path>")`` in ``module``.

    The ``MESH_INGEST.md`` §7.3 analogue of :func:`diff_import_targets`, and it
    exists for the same freeze argument (``script_contract.md`` §6): the check's
    verdict changes when the scan's bytes change, so the scan is a **build
    input** — frozen, hashed and staged with the script's own imports — rather
    than something read live at check time from inside the sandbox, which the §2
    namespace forbids anyway.

    One thing this cannot collect is the declared UNIT: a ``scan:`` target is a
    string, and §1.3 forbids inferring a unit from anything. The path therefore
    freezes here as a mesh declaration with no unit, and the unit is taken from
    the script's own ``import_mesh`` of the same path. A script that names a scan
    target it never imported gets ``mesh_units_undeclared`` at check time — a
    named refusal rather than a guessed scale.
    """
    out: list[str] = []
    for node in ast.walk(module):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != SCAN_DIFF_METHOD_NAME:
            continue
        arguments: list[ast.expr] = [*node.args, *(kw.value for kw in node.keywords)]
        for argument in arguments:
            if not isinstance(argument, ast.Constant) or not isinstance(argument.value, str):
                continue
            if argument.value.startswith(SCAN_TARGET_PREFIX):
                out.append(argument.value[len(SCAN_TARGET_PREFIX) :])
    return tuple(out)


def static_import_declarations(script: str) -> tuple[ImportDeclaration, ...]:
    """Declared imports of ``script`` — declarations, not path strings.

    The freeze threads *these* rather than their ``path`` strings
    (``MESH_INGEST.md`` §1.1), because the declared kind and unit have to reach
    the staging code and a path string carries neither. ``m.diff`` import
    targets join as STEP declarations at line 0: they are build inputs by the
    same freeze argument (``COMPARE.md`` §2) but they are not statements the
    build runs.

    Tolerant on purpose, exactly as :func:`static_import_paths` was: a syntax
    error or a dynamic path yields ``()``. Freezing must not raise on a script
    the build itself is about to reject at the offending statement with a full
    §8 error record.
    """
    try:
        module = ast.parse(script)
    except SyntaxError:
        return ()
    try:
        declarations = declared_imports(module, source=script)
    except DynamicImportPathError:
        return ()
    out: list[ImportDeclaration] = list(declarations)
    known = {(d.path, d.kind, d.units) for d in declarations}
    for path in diff_import_targets(module):
        if (path, "step", None) in known:
            continue
        known.add((path, "step", None))
        out.append(ImportDeclaration(path=path, lineno=0, col=0, statement_index=0))
    # ``MESH_INGEST.md`` §7.3: a ``scan:`` check target is a build input on the
    # same terms, declared as a MESH so the §1.6 byte ceiling that reads it is
    # the mesh one. It carries no unit — the freeze unions in whatever unit the
    # script's own ``import_mesh`` declared for the same path — because a unit
    # inferred from a check-target string would be exactly the guess §1.3
    # forbids.
    for path in scan_diff_targets(module):
        if any(declared == path and kind == "mesh" for declared, kind, _u in known):
            continue
        known.add((path, "mesh", None))
        out.append(ImportDeclaration(path=path, lineno=0, col=0, statement_index=0, kind="mesh"))
    return tuple(out)


def static_import_paths(script: str) -> tuple[str, ...]:
    """Declared import paths of ``script``, deduplicated, in source order."""
    seen: dict[str, None] = {}
    for declaration in static_import_declarations(script):
        seen.setdefault(declaration.path, None)
    return tuple(seen)


def max_bytes_for_kind(kind: ImportKind) -> int | None:
    """The §1.6 byte ceiling a *declared* import is read under.

    ``None`` for STEP — an over-large STEP simply fails to parse, which is the
    reasoning ``INGEST.md`` already relies on — so no existing STEP behaviour
    moves. A mesh is different: an OBJ can be gigabytes of ASCII and an XYZ can
    be 10⁸ points, and neither fails to parse; it just spends the memory.
    """
    if kind == "step":
        return None
    from hephaestus.geom.mesh import mesh_max_bytes

    return mesh_max_bytes()


def max_bytes_for_path(path: str) -> int | None:
    """The §1.6 byte ceiling for a file **no declaration covers**.

    ``PartStore.import_hash`` reads every regular file beneath ``imports/`` for
    staleness, declared or not, and there is no ``ImportDeclaration`` on that
    path — so a ceiling supplied "from the declaration's kind" can never fire
    there and an undeclared 40 GB scan would be read whole into the parent by
    the next staleness sync. The extension is the only thing available, so the
    extension is what resolves it: an admitted mesh/point-cloud extension gets
    the mesh ceiling, and everything else keeps STEP's ``None``.
    """
    from hephaestus.geom.mesh import extension_kind

    kind = extension_kind(path)
    return None if kind is None else max_bytes_for_kind(kind)


def _validate_relative(path: str) -> PurePosixPath:
    """A plain relative path beneath ``imports/`` (else ``invalid_import_path``)."""
    if not path or path != path.strip():
        raise ImportResolutionError(
            "import path must be a non-empty relative path", reason="invalid_import_path", path=path
        )
    if "\\" in path or "\x00" in path:
        raise ImportResolutionError(
            f"import path {path!r} contains a rejected character",
            reason="invalid_import_path",
            path=path,
        )
    candidate = PurePosixPath(path)
    if candidate.is_absolute():
        raise ImportResolutionError(
            f"import path {path!r} must be relative to {IMPORTS_DIRNAME}/ "
            "(absolute paths are refused)",
            reason="invalid_import_path",
            path=path,
        )
    parts = candidate.parts
    if not parts or any(part in (".", "..") for part in parts):
        raise ImportResolutionError(
            f"import path {path!r} must not traverse outside {IMPORTS_DIRNAME}/",
            reason="path_confinement",
            path=path,
        )
    return candidate


def read_import(imports_dir: Path, path: str, *, max_bytes: int | None) -> bytes:
    """Read ``imports_dir/path`` with no-follow/beneath semantics, under a ceiling.

    Confinement is rechecked at read time by walking one directory descriptor
    per component with ``O_NOFOLLOW``: a symlinked component (or a symlinked
    leaf, however it got there) fails the walk rather than redirecting the read
    outside the project. A missing file is ``import_not_found``; anything else
    the kernel refuses is ``path_confinement``.

    ``max_bytes`` is the ``MESH_INGEST.md`` §1.6 ceiling and is **required at
    every call site**, with no default, so a third caller is a type error until
    it states its ceiling rather than silently inheriting an unbounded read. Its
    *value* may still be ``None``, which means "no ceiling" and is what STEP
    passes. A file over the ceiling refuses ``mesh_import_too_large`` **before**
    ``read()``: this function ends in a single unbounded ``stream.read()`` and is
    the freeze path's only reader, so a ceiling checked "before the parser"
    would be checked after a multi-gigabyte OBJ was already resident in the
    parent and already in CAS — which is not a ceiling, because that memory and
    that store are the resource it protects.

    The size is read off the already-open, ``O_NOFOLLOW``-opened descriptor
    rather than by re-``stat``ing the path, so there is no TOCTOU window and the
    confinement property is exactly what it was.
    """
    relative = _validate_relative(path)
    dir_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
    try:
        root_fd = os.open(imports_dir, dir_flags)
    except FileNotFoundError as exc:
        raise ImportResolutionError(
            f"no {IMPORTS_DIRNAME}/ directory in this project; {path!r} cannot be imported",
            reason="import_not_found",
            path=path,
        ) from exc
    except OSError as exc:
        raise ImportResolutionError(
            f"{IMPORTS_DIRNAME}/ is not a readable directory ({exc.strerror})",
            reason="path_confinement",
            path=path,
        ) from exc
    opened: list[int] = [root_fd]
    fd = root_fd
    try:
        for component in relative.parts[:-1]:
            try:
                nxt = os.open(component, dir_flags | os.O_NOFOLLOW, dir_fd=fd)
            except FileNotFoundError as exc:
                raise ImportResolutionError(
                    f"import {path!r}: no directory {component!r} beneath {IMPORTS_DIRNAME}/",
                    reason="import_not_found",
                    path=path,
                ) from exc
            except OSError as exc:
                raise ImportResolutionError(
                    f"import {path!r}: path component {component!r} is not a real directory "
                    f"beneath {IMPORTS_DIRNAME}/ ({exc.strerror})",
                    reason="path_confinement",
                    path=path,
                ) from exc
            opened.append(nxt)
            fd = nxt
        leaf = relative.parts[-1]
        try:
            handle = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
        except FileNotFoundError as exc:
            raise ImportResolutionError(
                f"import {path!r} does not exist under {IMPORTS_DIRNAME}/",
                reason="import_not_found",
                path=path,
            ) from exc
        except OSError as exc:
            raise ImportResolutionError(
                f"import {path!r} is not a regular file beneath {IMPORTS_DIRNAME}/ "
                f"({exc.strerror}); symlinks are never followed",
                reason="path_confinement",
                path=path,
            ) from exc
        try:
            info = os.fstat(handle)
            if not stat_module.S_ISREG(info.st_mode):
                raise ImportResolutionError(
                    f"import {path!r} is not a regular file",
                    reason="path_confinement",
                    path=path,
                )
            if max_bytes is not None and info.st_size > max_bytes:
                # §1.6: nothing is read, nothing is hashed, and nothing reaches
                # the opstore blob store. This is the only place that property
                # can hold — one line further on, the bytes are resident.
                from hephaestus.geom.mesh import MESH_MAX_BYTES_ENV

                raise ImportResolutionError(
                    f"import {path!r} is {info.st_size} bytes, over the {max_bytes}-byte "
                    f"ceiling for its kind; raise {MESH_MAX_BYTES_ENV} to allow more "
                    "(MESH_INGEST.md §1.6)",
                    reason="mesh_import_too_large",
                    path=path,
                )
            with os.fdopen(os.dup(handle), "rb") as stream:
                return stream.read()
        except OSError as exc:
            raise ImportResolutionError(
                f"import {path!r} could not be read ({exc.strerror})",
                reason="unreadable_import",
                path=path,
            ) from exc
        finally:
            os.close(handle)
    finally:
        for handle in reversed(opened):
            os.close(handle)


def stage_dir(out_dir: Path) -> Path:
    """The worker's input area for one build (created on demand)."""
    return out_dir / STAGE_DIRNAME


def staged_filename(
    content_hash: str, *, kind: ImportKind = "step", units: str | None = None
) -> str:
    """Content-addressed name of a staged artifact, per kind (§1.5.1).

    ::

        # bare = content_hash.removeprefix("sha256:") — the hex digits alone.
        staged_filename(h, kind="step")             = bare[:32] + ".brep"
        staged_filename(h, kind=mesh|points, u)     = sha256(bare + "\\x00" + u)[:32] + ext

    The STEP branch is written as the **existing** expression — the content
    hash's own hex prefix — and not as a hash *of* the content hash, because
    those are different names: a formula that re-hashed would silently rename
    every staged STEP artifact in the tree while claiming to change nothing.

    For a mesh the unit joins the identity, and it must. Step 3 of §1.5 bakes
    the unit scale **into** the canonical blob, while ``stage_import`` returns
    the existing file when the name exists — so under the unmodified,
    unit-blind formula two byte-identical files declared ``units="mm"`` and
    ``units="in"`` would hash to one staged name, the second declaration would
    silently receive the first's geometry, and the build would be wrong by a
    factor of 25.4 with nothing recording it. That is not a hypothetical; it is
    what the unmodified function does. The NUL separator is a byte no unit
    token can contain, so the reuse property is literally true as stated: same
    bytes plus same declared unit ⇒ same staged file; same bytes at a different
    declared unit ⇒ a different staged file.
    """
    bare = content_hash.removeprefix("sha256:")
    suffix = MESH_SUFFIXES[kind]
    if kind == "step":
        return bare[:32] + suffix
    digest = hashlib.sha256(f"{bare}\x00{units or ''}".encode()).hexdigest()
    return digest[:32] + suffix


def staged_key(path: str, units: str | None) -> str:
    """The key one staged artifact is addressed by, in the parent and the worker.

    ``path`` alone for STEP, ``path`` plus the declared unit for a mesh. It has
    to carry the unit for the same reason :func:`staged_filename` does: one
    script may declare one path at two units, and a path-only key would hand
    the second declaration the first one's geometry. ``input_hashes.imports``
    is keyed by the **path** and is unaffected — build identity is the file's
    identity (§1.4), and two units over one file are two staged geometries of
    one input, not two inputs.
    """
    return path if units is None else f"{path}\x00{units}"


def _facts_filename(staged: Path) -> Path:
    """The ``.hmesh.facts`` sidecar beside a staged canonical blob (§1.5.2)."""
    return staged.with_name(staged.name + ".facts")


def stage_import(
    data: bytes,
    *,
    path: str,
    content_hash: str,
    out_dir: Path,
    kind: ImportKind = "step",
    units: str | None = None,
) -> Path:
    """Convert ``data`` ONCE and stage it read-only for the worker.

    ``data`` is exactly the bytes ``content_hash`` was taken over — the parse
    never re-reads the file, so the geometry the worker sees is the geometry the
    build record identifies. Returns the staged path.

    For STEP that conversion is ``read_step_bytes`` -> ``shape_to_brep``. For a
    mesh it is the ``MESH_INGEST.md`` §1.5 pipeline, and it emits **two** files:
    the canonical blob, which is the geometry and the identity, and a
    ``.facts`` JSON sidecar carrying exactly what canonicalization observed and
    destroyed (§1.5.2). The sidecar exists because ``welded_vertex_pairs``,
    ``degenerate_triangles_dropped`` and ``vertex_count_as_read`` are
    differences between the as-read mesh and the canonical one, and the blob is
    post-weld: a deserializer inside the sandbox cannot recover them from it, by
    construction. It is deliberately **not** part of ``mesh_canonical_hash`` —
    the hash names geometry, the sidecar reports history.
    """
    staged = stage_dir(out_dir) / staged_filename(content_hash, kind=kind, units=units)
    if staged.exists():
        # Content-addressed: two declarations naming the same bytes at the same
        # declared unit (or a retried staging) resolve to the one
        # already-staged, read-only file.
        return staged
    if kind == "step":
        payload, sidecar = _convert_step(data, path=path), None
    else:
        payload, sidecar = _convert_mesh(data, path=path, kind=kind, units=units)
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_bytes(payload)
    staged.chmod(0o444)
    if sidecar is not None:
        facts = _facts_filename(staged)
        facts.write_text(sidecar, encoding="utf-8")
        facts.chmod(0o444)
    return staged


def _convert_step(data: bytes, *, path: str) -> bytes:
    from hephaestus.geom.step_io import StepReadError, read_step_bytes, shape_to_brep

    try:
        return shape_to_brep(read_step_bytes(data, source=path))
    except StepReadError as exc:
        raise ImportResolutionError(
            f"import {path!r} is not a readable STEP part: {exc.message}",
            reason="unreadable_step",
            path=path,
        ) from exc


def _convert_mesh(
    data: bytes, *, path: str, kind: ImportKind, units: str | None
) -> tuple[bytes, str | None]:
    """The §1.5 canonicalization, with every geom refusal renamed to a resolution.

    ``MeshReadError.reason`` and ``ImportResolutionReason`` share the §1.7
    vocabulary by construction, so this is a re-wrap and never a re-decision:
    the geom layer names the defect, the executor lands it at the
    ``import_mesh`` statement.
    """
    from hephaestus.geom.mesh import (
        MeshReadError,
        canonicalize_mesh,
        canonicalize_points,
        facts_to_json,
        points_facts_to_json,
    )

    try:
        if kind == "points":
            cloud = canonicalize_points(path, data, units)
            return cloud.blob, points_facts_to_json(cloud)
        canonical = canonicalize_mesh(path, data, units)
    except MeshReadError as exc:
        raise ImportResolutionError(exc.message, reason=exc.reason, path=path) from exc
    return canonical.blob, facts_to_json(canonical)


def staged_paths(out_dir: Path, staged: Mapping[str, str]) -> dict[str, Path]:
    """Resolve a job's ``{import path: staged filename}`` map to absolute paths."""
    area = stage_dir(out_dir)
    return {name: area / filename for name, filename in staged.items()}
