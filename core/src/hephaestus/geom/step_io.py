# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
# ^ OCP/build123d bindings are untyped at the member level; the relaxation is
#   pinned per-file so it stays scoped to the modules that touch the kernel
#   bindings (same convention as ``geom.measure`` / ``geom.nesting``).
"""STEP <-> shape conversion: the ingest half of the geometry layer.

``INGEST.md`` §1 makes an imported solid *a term in the expression*: the part
script says ``base = import_step("bracket.step")`` and the harness supplies the
shape. This module is the pure conversion underneath that — bytes of an
AP203/AP214 STEP part in, one build123d ``Shape`` out — and nothing else. It
holds no policy: it does not know where files live, does not resolve or confine
paths, does not hash, and never touches a project. Path resolution, content
addressing and staging are PROJECT concerns and live executor-side
(:mod:`hephaestus.core.executor.imports`), which is what keeps
``hephaestus.geom`` executor-free and reusable (an external benchmark scoring a
submitted STEP file needs exactly this function and none of the rest).

Reading goes through ``STEPControl_Reader`` on an in-memory stream: the bytes
the caller already hashed are the bytes parsed, with no second filesystem read
between the hash and the geometry. Every failure mode OCCT signals by a return
status or a null shape is turned into an explicit :class:`StepReadError` —
silence (an empty compound for an unreadable file) would be indistinguishable
from a legitimately empty part and would let a corrupt import build "fine".

**Feature recognition is out of scope** (``INGEST.md`` §1): this returns the
B-rep as it is, with no inference of parameters or design intent.
"""

from __future__ import annotations

import contextlib
import io
import os
import sys
import threading
from collections.abc import Generator
from pathlib import Path

from hephaestus.core.errors import ValidationError
from hephaestus.geom.metrics import AnyShape

__all__ = [
    "STEP_SCHEMAS",
    "StepReadError",
    "kernel_quiet",
    "quiet_messenger",
    "read_step",
    "read_step_bytes",
    "shape_from_brep",
    "shape_to_brep",
    "write_step",
]

#: The STEP application protocols read in Stage 8A. IGES/BREP may follow, each
#: as an explicit contract amendment (``INGEST.md`` §1).
STEP_SCHEMAS: tuple[str, ...] = ("AP203", "AP214")


class StepReadError(ValidationError):
    """A STEP payload could not be parsed into a shape (named, never silent)."""

    def __init__(self, message: str) -> None:
        super().__init__(message, kind="contract")


# --------------------------------------------------------------------------
# keeping the kernel off stdout


_messenger_quieted = False


def quiet_messenger() -> None:
    """Move OCCT's default printer off C++ ``std::cout`` onto ``std::cerr``.

    OCCT reports parse diagnostics through ``Message_Messenger``, whose default
    :class:`Message_PrinterOStream` writes to ``std::cout`` — fd 1, shared with
    Python and invisible to ``contextlib.redirect_stdout`` or any other
    Python-level rebinding, because the write never passes through
    ``sys.stdout``. ``docs/cli.md`` makes stdout the ``--json`` document and,
    under ``heph serve --mcp``, the JSON-RPC transport itself, and says
    diagnostics go to stderr always: a ``**** ERR StepFile ...`` line on fd 1 is
    corruption, not noise.

    The printer is *replaced*, never dropped: the same messages at the same
    gravity land on ``std::cerr``, so a malformed import is still diagnosable.
    Idempotent, and deliberately tolerant of a binding that does not expose
    ``Message`` — :func:`kernel_quiet` is the second layer precisely so this one
    is allowed to be best-effort.
    """
    global _messenger_quieted
    if _messenger_quieted:
        return
    _messenger_quieted = True
    try:
        from OCP.Message import (
            Message,  # pyright: ignore[reportAttributeAccessIssue]
            Message_Gravity,  # pyright: ignore[reportAttributeAccessIssue]
            Message_PrinterOStream,  # pyright: ignore[reportAttributeAccessIssue]
        )

        messenger = Message.DefaultMessenger_s()
        printers = messenger.Printers()
        for index in range(printers.Size(), 0, -1):
            messenger.RemovePrinter(printers.Value(index))
        # ``"cerr"`` is OCCT's own reserved stream name for ``std::cerr`` (the
        # filename overload special-cases it); ``Message_Info`` is the gravity
        # the printer we just removed carried, so nothing is silenced, only
        # moved.
        messenger.AddPrinter(Message_PrinterOStream("cerr", False, Message_Gravity.Message_Info))
    except Exception:  # pragma: no cover - binding shape is version-sensitive
        # A messenger API that has moved is not a reason to fail a STEP read;
        # the fd-level guard below still keeps stdout byte-clean.
        pass


@contextlib.contextmanager
def kernel_quiet() -> Generator[None]:
    """Point fd 1 at fd 2 for the duration of an in-parent kernel call.

    The second and load-bearing layer of the same rule. A C++ write to fd 1 is
    reachable by no Python-level redirection, so the only correct guard is at
    the descriptor: ``dup2(2, 1)`` for the call and a restore in ``finally``.
    Applied **unconditionally**, never "only when ``--json``" — the same code
    then serves the CLI, the MCP stdio transport and an embedding host, and
    there is no mode in which a kernel diagnostic on stdout is wanted.

    ``sys.stdout`` is flushed on both edges so nothing Python buffered before
    the call is emitted into the redirect, and nothing written during it is
    held back until after the restore.

    The descriptor layer is **process-wide**, so it is taken only when this is
    the sole thread: in a threaded host (``heph serve --mcp`` dispatches tools
    on worker threads while its reader thread writes JSON-RPC to fd 1) the
    redirect would send another thread's protocol bytes to stderr for the
    duration of the kernel call. There the messenger layer above, which is
    per-process state OCCT itself consults, is the guard, and it is sufficient
    on its own (``core/tests/test_step_io.py`` pins that a malformed STEP read
    leaves the real stdout byte-clean with the messenger alone).
    """
    quiet_messenger()
    if threading.active_count() != 1 or threading.current_thread() is not threading.main_thread():
        yield
        return
    stdout = sys.stdout
    if stdout is not None:
        with contextlib.suppress(ValueError, OSError):  # a closed or detached stdout
            stdout.flush()
    try:
        saved = os.dup(1)
    except OSError:  # pragma: no cover - no fd 1 (a fully detached embedding)
        yield
        return
    try:
        os.dup2(2, 1)
        yield
    finally:
        if stdout is not None:
            with contextlib.suppress(ValueError, OSError):  # see above
                stdout.flush()
        os.dup2(saved, 1)
        os.close(saved)


def _wrap(topods: object) -> AnyShape:
    """Wrap a raw ``TopoDS_Shape`` in its build123d class."""
    from build123d.importers import topods_lut
    from build123d.topology import downcast

    lowered = downcast(topods)
    wrapper = topods_lut.get(type(lowered))
    if wrapper is None:  # pragma: no cover - lut covers every TopoDS subclass
        raise StepReadError(f"unsupported STEP topology {type(lowered).__name__}")
    return wrapper(lowered)


def read_step_bytes(data: bytes, *, source: str = "<step>") -> AnyShape:
    """Parse STEP ``data`` into one build123d shape.

    ``source`` names the payload in error messages only (the caller's relative
    path, typically) — nothing is read from it. A file OCCT refuses, or one
    that transfers no root entity, raises :class:`StepReadError`; the caller
    turns that into the §8 build error at the ``import_step`` statement.
    """
    from OCP.IFSelect import IFSelect_ReturnStatus  # pyright: ignore[reportAttributeAccessIssue]
    from OCP.STEPControl import STEPControl_Reader  # pyright: ignore[reportAttributeAccessIssue]

    if not data:
        raise StepReadError(f"{source}: STEP payload is empty")
    # Under ``kernel_quiet``: OCCT narrates a malformed payload on fd 1, and
    # this function runs in the CLI process (import staging and ``heph diff``
    # both convert in the harness, not in the sandboxed worker), where fd 1 is
    # the ``--json`` document or the MCP transport.
    with kernel_quiet():
        reader = STEPControl_Reader()
        status = reader.ReadStream(source, io.BytesIO(data))
        if status != IFSelect_ReturnStatus.IFSelect_RetDone:
            raise StepReadError(
                f"{source}: not a readable STEP file "
                f"({str(status).rpartition('.')[2]}; expected {'/'.join(STEP_SCHEMAS)})"
            )
        roots = reader.TransferRoots()
        if roots < 1:
            raise StepReadError(f"{source}: STEP file transfers no root entity")
        topods = reader.OneShape()
        if topods.IsNull():
            raise StepReadError(f"{source}: STEP file yielded a null shape")
        return _wrap(topods)


def read_step(path: Path) -> AnyShape:
    """Parse the STEP file at ``path`` (a convenience over :func:`read_step_bytes`).

    Confinement, hashing and staging are the caller's business: this reads the
    path it is given, exactly as given.
    """
    return read_step_bytes(path.read_bytes(), source=path.name)


def write_step(shape: AnyShape, path: Path) -> None:
    """Write ``shape`` to ``path`` as AP214 STEP (build123d's exporter)."""
    from build123d.exporters3d import export_step

    with kernel_quiet():
        export_step(shape, path)  # pyright: ignore[reportArgumentType]


def shape_to_brep(shape: AnyShape) -> bytes:
    """Serialize a shape to OCCT BRep bytes (the staged interchange form).

    BRep is the kernel's own lossless serialization: converting a STEP payload
    once and handing the worker BRep is what lets the sandbox deserialize an
    import without a STEP parser, a filesystem path, or a second read of bytes
    that could have changed underneath the hash.
    """
    from OCP.BRepTools import BRepTools  # pyright: ignore[reportAttributeAccessIssue]

    stream = io.BytesIO()
    with kernel_quiet():
        BRepTools.Write_s(shape.wrapped, stream)
    return stream.getvalue()


def shape_from_brep(data: bytes, *, source: str = "<brep>") -> AnyShape:
    """Deserialize OCCT BRep bytes back into a build123d shape."""
    from OCP.BRep import BRep_Builder  # pyright: ignore[reportAttributeAccessIssue]
    from OCP.BRepTools import BRepTools  # pyright: ignore[reportAttributeAccessIssue]
    from OCP.TopoDS import TopoDS_Shape  # pyright: ignore[reportAttributeAccessIssue]

    topods = TopoDS_Shape()
    with kernel_quiet():
        try:
            # The stream overload signals failure by leaving the shape null (only
            # the filename overload returns a status), so the null check below is
            # the real verdict for both a malformed payload and an empty one.
            BRepTools.Read_s(topods, io.BytesIO(data), BRep_Builder())
        except Exception as exc:  # OCCT raises Standard_Failure on some garbage
            raise StepReadError(f"{source}: staged BRep payload is unreadable: {exc}") from exc
        if topods.IsNull():
            raise StepReadError(f"{source}: staged BRep payload is a null shape")
        return _wrap(topods)
