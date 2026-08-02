"""Rebuild measurement geometry from published BRep artifacts (parent side).

A published build artifact is the BRep of the part's final compound. BRep
serialization preserves topology/geometry but not build123d labels, tag
references, or source-map bindings — those exist only in the worker that
built the shape. A reloaded artifact therefore supports exactly the
``"part"`` selector (§7 rule 1): enough for project-scoped cross-part checks
(``checks/*.py`` measure ``"<part>/part"`` interference/clearance/bbox/...),
while label/tag/binding selectors raise the §7 addressing error listing the
(empty) candidate namespace rather than guessing.

Used by ``heph check`` to measure current artifacts lock-free without
re-executing any part script in the parent process.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from hephaestus.core.addressing import GeometryIndex, Resolution
from hephaestus.core.checks.facade import MappedGeometry

__all__ = [
    "artifact_source",
    "load_brep_shape",
    "part_only_source",
    "write_brep_shape",
]


def load_brep_shape(data: bytes, *, scratch_dir: Path | None = None) -> object:
    """Deserialize BRep bytes into a build123d shape (via a scratch file).

    OCCT's BRep reader is file-based; the temporary file lives in
    ``scratch_dir`` (or the system tmp dir) and is removed afterwards.
    """
    from build123d import importers

    if scratch_dir is not None:
        scratch_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".brep", dir=scratch_dir, delete=False) as handle:
        handle.write(data)
        path = Path(handle.name)
    try:
        return importers.import_brep(path)
    finally:
        path.unlink(missing_ok=True)


def write_brep_shape(shape: object, path: Path) -> None:
    """Serialize a build123d shape to BRep at ``path`` (the loader's inverse).

    OCCT's native BRep text format is lossless — the same writer the worker
    uses for build artifacts — which is what lets the bounded comparison path
    (``COMPARE.md`` §5) hand a shape to a killable subprocess and still produce
    exactly the numbers the direct in-process diff would have.
    """
    from OCP.BRepTools import BRepTools  # pyright: ignore[reportAttributeAccessIssue]

    wrapped = shape.wrapped  # pyright: ignore[reportAttributeAccessIssue]
    if not BRepTools.Write_s(wrapped, str(path)):
        raise OSError(f"failed to write BRep to {path}")


def part_only_source(shape: object) -> MappedGeometry:
    """A GeometrySource resolving only ``"part"`` (reloaded-artifact scope)."""
    index = GeometryIndex(labels=(), bindings={}, tags=frozenset())

    def resolver(resolution: Resolution) -> object:
        # The empty index admits only the "part" selector; addressing.py has
        # already rejected everything else with candidates.
        return shape

    return MappedGeometry(index=index, resolver=resolver)


def artifact_source(data: bytes, *, scratch_dir: Path | None = None) -> MappedGeometry:
    """Part-level GeometrySource over one published build artifact's bytes."""
    return part_only_source(load_brep_shape(data, scratch_dir=scratch_dir))
