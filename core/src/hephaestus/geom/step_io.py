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

import io
from pathlib import Path

from hephaestus.core.errors import ValidationError
from hephaestus.geom.metrics import AnyShape

__all__ = [
    "STEP_SCHEMAS",
    "StepReadError",
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
    BRepTools.Write_s(shape.wrapped, stream)
    return stream.getvalue()


def shape_from_brep(data: bytes, *, source: str = "<brep>") -> AnyShape:
    """Deserialize OCCT BRep bytes back into a build123d shape."""
    from OCP.BRep import BRep_Builder  # pyright: ignore[reportAttributeAccessIssue]
    from OCP.BRepTools import BRepTools  # pyright: ignore[reportAttributeAccessIssue]
    from OCP.TopoDS import TopoDS_Shape  # pyright: ignore[reportAttributeAccessIssue]

    topods = TopoDS_Shape()
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
