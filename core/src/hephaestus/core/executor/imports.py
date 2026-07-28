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
import os
import stat as stat_module
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

from hephaestus.core.errors import ValidationError

__all__ = [
    "DIFF_METHOD_NAME",
    "DIFF_TARGET_PREFIX",
    "IMPORTS_DIRNAME",
    "STAGE_DIRNAME",
    "DynamicImportPathError",
    "ImportDeclaration",
    "ImportResolutionError",
    "ImportResolutionReason",
    "declared_imports",
    "diff_import_targets",
    "import_step_name",
    "read_import",
    "stage_dir",
    "stage_import",
    "staged_filename",
    "staged_paths",
    "static_import_paths",
]

#: Project-root directory holding importable STEP files (``INGEST.md`` §1).
IMPORTS_DIRNAME = "imports"
#: The worker's input area, relative to the build out dir.
STAGE_DIRNAME = "inputs"
#: The §2 injected name whose argument declares an import.
import_step_name = "import_step"
#: The §6 measurement-facade method whose target may name an import
#: (``COMPARE.md`` §2: ``m.diff("part", "import:target.step")``).
DIFF_METHOD_NAME = "diff"
#: Prefix marking a ``m.diff`` target as an ``imports/`` file.
DIFF_TARGET_PREFIX = "import:"

ImportResolutionReason = Literal[
    "invalid_import_path",
    "import_not_found",
    "path_confinement",
    "unreadable_import",
    "unreadable_step",
]


class ImportResolutionError(ValidationError):
    """A declared import could not be resolved, read, or converted.

    ``reason`` is the stable code; ``path`` is the declared relative path as
    written in the script.
    """

    def __init__(self, message: str, *, reason: ImportResolutionReason, path: str) -> None:
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
    """One statically declared ``import_step("...")`` call site."""

    path: str
    lineno: int
    col: int
    statement_index: int


def _is_import_call(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == import_step_name
    )


def declared_imports(
    module: ast.Module, *, source: str | None = None
) -> tuple[ImportDeclaration, ...]:
    """Every ``import_step`` declaration in ``module``, in source order.

    Raises :class:`DynamicImportPathError` at the first call whose argument is
    not a single string literal — including one built by concatenation, an
    f-string, a variable, or a keyword. The error names the statement so the
    worker can report it at its own line with the standard §8 frame.
    """
    lines = (source or "").splitlines()
    out: list[ImportDeclaration] = []
    for index, top in enumerate(module.body):
        for node in ast.walk(top):
            if not isinstance(node, ast.Call) or not _is_import_call(node):
                continue
            statement = lines[node.lineno - 1].strip() if 0 < node.lineno <= len(lines) else ""
            literal = (
                node.args[0]
                if len(node.args) == 1
                and not node.keywords
                and isinstance(node.args[0], ast.Constant)
                else None
            )
            if literal is None or not isinstance(literal.value, str):
                raise DynamicImportPathError(
                    f"{import_step_name}() requires a string literal path so the file can be "
                    "frozen and hashed before the build runs; a computed path cannot be "
                    "resolved (INGEST.md §1)",
                    lineno=node.lineno,
                    col=node.col_offset,
                    statement=statement,
                )
            out.append(
                ImportDeclaration(
                    path=literal.value,
                    lineno=node.lineno,
                    col=node.col_offset,
                    statement_index=index,
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


def static_import_paths(script: str) -> tuple[str, ...]:
    """Declared import paths of ``script``, deduplicated, in source order.

    Both declaration sites count: every ``import_step`` argument (INGEST.md §1)
    and every ``m.diff`` import target in the script's ``CHECKS``
    (:func:`diff_import_targets`). Tolerant on purpose: a syntax error or a
    dynamic path yields the declarations found so far (``()`` in the
    syntax-error case). Freezing must not raise on a script that the build
    itself is about to reject at the offending statement with a full §8 error
    record.
    """
    try:
        module = ast.parse(script)
    except SyntaxError:
        return ()
    seen: dict[str, None] = {}
    try:
        declarations = declared_imports(module, source=script)
    except DynamicImportPathError:
        return ()
    for declaration in declarations:
        seen.setdefault(declaration.path, None)
    for path in diff_import_targets(module):
        seen.setdefault(path, None)
    return tuple(seen)


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


def read_import(imports_dir: Path, path: str) -> bytes:
    """Read ``imports_dir/path`` with no-follow/beneath semantics.

    Confinement is rechecked at read time by walking one directory descriptor
    per component with ``O_NOFOLLOW``: a symlinked component (or a symlinked
    leaf, however it got there) fails the walk rather than redirecting the read
    outside the project. A missing file is ``import_not_found``; anything else
    the kernel refuses is ``path_confinement``.
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


def staged_filename(content_hash: str) -> str:
    """Content-addressed name of a staged BRep (same bytes ⇒ same staged file)."""
    return f"{content_hash.removeprefix('sha256:')[:32]}.brep"


def stage_import(data: bytes, *, path: str, content_hash: str, out_dir: Path) -> Path:
    """Convert ``data`` to BRep once and stage it read-only for the worker.

    ``data`` is exactly the bytes ``content_hash`` was taken over — the parse
    never re-reads the file, so the geometry the worker sees is the geometry the
    build record identifies. Returns the staged path.
    """
    from hephaestus.geom.step_io import StepReadError, read_step_bytes, shape_to_brep

    staged = stage_dir(out_dir) / staged_filename(content_hash)
    if staged.exists():
        # Content-addressed: two declarations naming the same bytes (or a
        # retried staging) resolve to the one already-staged, read-only file.
        return staged
    try:
        shape = read_step_bytes(data, source=path)
        brep = shape_to_brep(shape)
    except StepReadError as exc:
        raise ImportResolutionError(
            f"import {path!r} is not a readable STEP part: {exc.message}",
            reason="unreadable_step",
            path=path,
        ) from exc
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_bytes(brep)
    staged.chmod(0o444)
    return staged


def staged_paths(out_dir: Path, staged: Mapping[str, str]) -> dict[str, Path]:
    """Resolve a job's ``{import path: staged filename}`` map to absolute paths."""
    area = stage_dir(out_dir)
    return {name: area / filename for name, filename in staged.items()}
