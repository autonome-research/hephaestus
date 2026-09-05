"""Rebuild measurement geometry from published BRep artifacts (parent side).

A published build artifact is the BRep of the part's final compound. BRep
serialization preserves topology/geometry but not build123d labels, tag
references, or source-map bindings — those exist only in the worker that
built the shape. What a reloaded artifact admits therefore depends entirely on
what publication recorded **beside** it:

* with the build's bundle in hand (its §7 ``geometry_index``, the §8
  ``geometries`` label rows and the source map's tag placements),
  :func:`published_artifact_source` resolves the whole §7 grammar — ``"part"``,
  tags, labels with their ``#k``/``#*`` dedup selectors, and binding names —
  through the single join in
  :mod:`hephaestus.core.executor.published_geometry`;
* with no bundle stored, :func:`part_only_source` is the honest fallback: it
  admits ``"part"`` (§7 rule 1) and nothing else, and its ``namespace_recorded``
  flag says *why*, so a caller can refuse ``namespace_unrecorded`` rather than
  report a real selector as resolving to nothing against an empty namespace.

Until 2026-09-04 the empty index was the only thing this module built, so
``measure``, ``heph check`` and project-scope ``run_checks`` addressed the
literal ``"part"`` selector and nothing else — while the same selectors
resolved inside that part's own ``CHECKS`` during the build, and while
constraint anchors and ``inspect_part(focus=…)`` resolved them against the very
same artifact (audit-2026-09-04 B-1).
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from hephaestus.core.addressing import GeometryIndex, Resolution
from hephaestus.core.checks.facade import GeometrySource
from hephaestus.core.executor.published_geometry import (
    part_geometry,
    published_index,
    tag_placements,
)
from hephaestus.core.executor.tags import TagPlacement
from hephaestus.core.project_store.store import blob_hash_of_ref
from hephaestus.core.types import BuildResult
from opstore.types import JSONValue

from opstore import OpStore

__all__ = [
    "ArtifactGeometry",
    "artifact_source",
    "load_brep_shape",
    "part_only_source",
    "published_artifact_source",
    "published_source_for",
    "write_brep_shape",
]


@dataclass(frozen=True)
class ArtifactGeometry:
    """A :class:`GeometrySource` over one reloaded published build artifact.

    ``namespace_recorded`` is the one honest limit left after B-1: an artifact
    whose build bundle is not stored (published before bundles were durable, or
    already collected) genuinely has no recorded §7 namespace. Saying so is a
    different fact from "that selector matches nothing", and the two must not
    be spelled the same way — an empty candidate set was exactly the symptom
    that hid this defect for fourteen months.
    """

    index: GeometryIndex
    resolver: Callable[[Resolution], object]
    #: True when :attr:`index` is the build's own recorded §7 namespace.
    namespace_recorded: bool

    def shape(self, resolution: Resolution) -> object:
        return self.resolver(resolution)


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


def part_only_source(shape: object) -> ArtifactGeometry:
    """A GeometrySource resolving only ``"part"`` (no recorded namespace).

    The fallback, never the default for an artifact whose bundle IS stored:
    :func:`published_source_for` picks between the two.
    """
    index = GeometryIndex(labels=(), bindings={}, tags=frozenset())

    def resolver(resolution: Resolution) -> object:
        # The empty index admits only the "part" selector; addressing.py has
        # already rejected everything else with candidates.
        return shape

    return ArtifactGeometry(index=index, resolver=resolver, namespace_recorded=False)


def artifact_source(data: bytes, *, scratch_dir: Path | None = None) -> ArtifactGeometry:
    """Part-level GeometrySource over one artifact's bytes, with no bundle.

    Bytes alone carry no namespace, so this is :func:`part_only_source` over the
    reloaded shape. A caller that can name the *build* those bytes came from
    wants :func:`published_source_for` instead.
    """
    return part_only_source(load_brep_shape(data, scratch_dir=scratch_dir))


def published_artifact_source(
    shape: object,
    *,
    index: GeometryIndex,
    placements: Mapping[str, TagPlacement],
    result: BuildResult,
    part: str | None = None,
    artifact_ref: str | None = None,
) -> ArtifactGeometry:
    """Full-§7 GeometrySource over one published build (``ASSEMBLY.md`` §2 join).

    ``index`` is the bundle's recorded namespace (:func:`published_index`) and
    ``placements`` the source map's tag table (:func:`tag_placements`); the
    label→solid runs come from ``result``'s §8 ``geometries`` rows. A selector
    that resolves in the namespace but cannot be located in the artifact raises
    :class:`~hephaestus.core.executor.published_geometry.UnresolvableAnchorError`
    — the same named refusal constraint anchors already get, because it is the
    same object doing the resolving.

    ``part`` / ``artifact_ref`` default to the build's own, and exist only so a
    caller measuring one part's artifact under another name (never done today)
    could still produce truthful refusal text.
    """
    geometry = part_geometry(
        part=part if part is not None else result.part,
        artifact_ref=artifact_ref if artifact_ref is not None else (result.artifact_ref or ""),
        shape=shape,
        index=index,
        placements=placements,
        result=result,
    )
    return ArtifactGeometry(index=index, resolver=geometry.shape_for, namespace_recorded=True)


def published_source_for(
    store: OpStore,
    *,
    artifact_ref: str,
    part: str | None = None,
    bundle: Mapping[str, JSONValue] | None,
    scratch_dir: Path | None = None,
) -> ArtifactGeometry:
    """One published build, as an addressable source, from the store alone.

    The joint every parent-side measurement goes through — ``measure``,
    project-scope ``run_checks`` and ``heph check`` — so the three cannot drift
    apart about which selectors an artifact admits. ``bundle`` is the build's
    published bundle document (``Publisher.bundle_for_artifact``); ``None``
    means it was never stored or has been collected, and the result is the
    honest ``"part"``-only fallback rather than a guess. ``part`` names the part
    the caller is measuring, for refusal text; absent, the bundle's own part
    name is used.
    """
    blob = blob_hash_of_ref(artifact_ref)
    shape = load_brep_shape(store.blobs.get(blob), scratch_dir=scratch_dir)
    if bundle is None:
        return part_only_source(shape)
    raw_result = bundle.get("result")
    if not isinstance(raw_result, dict):  # pragma: no cover - our own canonical JSON
        return part_only_source(shape)
    result = BuildResult.from_json(cast("Mapping[str, JSONValue]", raw_result))
    return published_artifact_source(
        shape,
        index=published_index(bundle, result),
        placements=tag_placements(_source_map(store, result)),
        result=result,
        part=part,
        artifact_ref=artifact_ref,
    )


def _source_map(store: OpStore, result: BuildResult) -> Mapping[str, JSONValue] | None:
    """The build's stored source-map document, or ``None`` when unavailable."""
    ref = result.source_map_ref
    if ref is None:
        return None
    blob = blob_hash_of_ref(ref)
    if not store.blobs.has(blob):
        return None
    raw: Any = json.loads(store.blobs.get(blob).decode("utf-8"))
    if not isinstance(raw, dict):  # pragma: no cover - our own canonical JSON
        return None
    return cast("Mapping[str, JSONValue]", raw)


# ``ArtifactGeometry`` is a structural :class:`GeometrySource`; asserted here so
# a change on either side is a type error rather than a runtime surprise at the
# facade boundary.
_SATISFIES_GEOMETRY_SOURCE: type[GeometrySource] = ArtifactGeometry
