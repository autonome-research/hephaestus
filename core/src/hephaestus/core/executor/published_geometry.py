# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""§7 addressing over a *published* build artifact — one implementation.

A published build artifact is the BRep of a part's final compound. BRep
serialization preserves topology and geometry but **not** build123d labels, tag
references or source-map bindings: those existed only inside the worker that
built the shape. What makes a reloaded artifact addressable anyway is what
publication recorded *beside* it — the build's §7 ``geometry_index`` in the
bundle document (``ASSEMBLY.md`` §2), the §8 ``geometries`` label rows in the
:class:`~hephaestus.core.types.BuildResult` (which are consecutive runs of
solids in tree order), and the tag placements in the source map (§5.3).

This module is that join. It lives here rather than inside
:mod:`hephaestus.core.assembly` because four parent-side consumers need it and
three of them are not assemblies:

* constraint anchors (``ASSEMBLY.md`` §2) and joint anchors (``KINEMATICS.md``
  §2), through :class:`~hephaestus.core.assembly.AnchorResolver`, which
  re-exports every name below so its own imports and behaviour are unchanged;
* the §3.3 selection table in :mod:`hephaestus.core.render.inspect`, which needs
  only the placement decoder;
* every parent-side **measurement** — the ``measure`` tool, project-scope
  ``run_checks`` and ``heph check`` — which addressed the literal ``"part"``
  selector and nothing else until 2026-09-04, because it built its index empty
  instead of performing this join (audit-2026-09-04 B-1).

A selector that resolves in the namespace but cannot be located in the published
artifact is a named refusal (:class:`UnresolvableAnchorError`), never a guessed
face: §7 forbids the guess, and reporting "unaddressable" as a measurement would
be worse than reporting nothing. §7 rule 4 (binding names) is the one rule that
is structurally in that position here — publication records no binding-to-solid
mapping — so :func:`addressable_namespace` is what a caller advertises as
candidates, not the raw namespace.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal, cast

from hephaestus.core.addressing import GeometryIndex, Resolution, namespace, resolve
from hephaestus.core.errors import AddressingError
from hephaestus.core.executor.runner import geometry_index_from_json
from hephaestus.core.executor.tags import TagPlacement
from hephaestus.core.types import BuildResult
from opstore.types import JSONValue

__all__ = [
    "UNRESOLVABLE_REASONS",
    "PartGeometry",
    "UnresolvableAnchorError",
    "UnresolvableReason",
    "addressable_namespace",
    "part_geometry",
    "published_index",
    "solid_runs",
    "tag_placements",
]

UnresolvableReason = Literal[
    "missing_part",
    "no_current_build",
    "missing_artifact",
    "dangling_selector",
    "ambiguous_selector",
    "unaddressable_anchor",
    "shape_refused",
    "invalid_constraint",
    "unresolvable_pose",
]

#: Why a constraint could not be evaluated. Each names a different fix:
#:
#: * ``missing_part`` — the anchor names a part this project does not have.
#: * ``no_current_build`` — the part exists but has no current successful build
#:   (never built, or its last build failed): build it.
#: * ``missing_artifact`` — a current build is recorded but its artifact bytes
#:   are not durably stored: the evidence is gone, which is not the same as
#:   never having existed.
#: * ``dangling_selector`` — the selector resolves to nothing in that build's §7
#:   namespace: the tag or label the constraint was written against is gone,
#:   typically because the script was edited.
#: * ``ambiguous_selector`` — the selector matches several interpretations at
#:   one precedence level; §7 forbids guessing, so does this.
#: * ``unaddressable_anchor`` — the selector exists in the namespace but the
#:   published artifact cannot supply that geometry: an unplaced tag, a
#:   vertex/wire tag, or ANY §7 rule-4 binding — publication records label runs
#:   and tag placements and no binding-to-solid mapping, so a binding is
#:   locatable here only through the label §5.1 gave it.
#: * ``shape_refused`` — geometry was resolved but is the wrong class for the
#:   kind (``geom``'s :class:`~hephaestus.geom.ConstraintShapeError`, whose own
#:   reason is carried in the detail): concentricity between two boxes has no
#:   answer, and a plausible number for it would be worse than none.
#: * ``invalid_constraint`` — the stored entry is malformed for its kind. The
#:   declaration path refuses these, so reaching it here means a generation was
#:   written by an older or foreign writer; it is reported, never evaluated.
#: * ``unresolvable_pose`` — the entry binds a pose (``KINEMATICS.md`` §3) that
#:   could not be evaluated: unknown or withdrawn, orphaned by a withdrawn
#:   joint, out of a joint's declared limits, or riding an unresolvable joint.
#:   The detail names the pose and its own reason; the row is NOT checked, and
#:   the ``pose_residuals`` table says which poses were.
UNRESOLVABLE_REASONS: Final[tuple[UnresolvableReason, ...]] = (
    "missing_part",
    "no_current_build",
    "missing_artifact",
    "dangling_selector",
    "ambiguous_selector",
    "unaddressable_anchor",
    "shape_refused",
    "invalid_constraint",
    "unresolvable_pose",
)


class UnresolvableAnchorError(Exception):
    """An anchor could not be turned into geometry — a named reason plus detail.

    Public because ``KINEMATICS.md`` §2 makes joint-anchor resolution
    (:mod:`hephaestus.core.motion`) ride the shared anchoring path: the engine
    that shares :class:`~hephaestus.core.assembly.AnchorResolver` also has to
    catch its refusals.
    """

    def __init__(self, reason: UnresolvableReason, detail: str) -> None:
        super().__init__(detail)
        self.reason: UnresolvableReason = reason
        self.detail = detail


# --------------------------------------------------------------------------
# resolved geometry of one part's published artifact


@dataclass(frozen=True)
class PartGeometry:
    """One part's published artifact, plus everything needed to address into it."""

    part: str
    artifact_ref: str
    shape: Any
    index: GeometryIndex
    solids: tuple[Any, ...]
    #: ``(label, first solid index, solid count)`` runs in geometry-tree order.
    runs: tuple[tuple[str, int, int], ...]
    placements: Mapping[str, TagPlacement]
    #: False when the label rows do not partition the artifact's solids (nested
    #: labels double-count). Label/binding anchors are then unaddressable rather
    #: than resolved to a run that may not be the addressed node's.
    runs_partition: bool

    def shape_for(self, resolution: Resolution) -> Any:
        """The concrete geometry one resolution names, or ``UnresolvableAnchorError``."""
        if resolution.kind == "part":
            return self.shape
        if resolution.kind == "tag":
            return self._tag_shape(resolution.name)
        return self._run_shape(resolution)

    def _tag_shape(self, name: str) -> Any:
        placement = self.placements.get(name)
        if placement is None or placement.solid_index is None or placement.topo_index is None:
            raise UnresolvableAnchorError(
                "unaddressable_anchor",
                f"tag {name!r} is in {self.part}'s namespace but was not placed in the "
                "published artifact (it referenced topology outside part.geometry)",
            )
        if placement.solid_index >= len(self.solids):
            raise UnresolvableAnchorError(
                "unaddressable_anchor",
                f"tag {name!r} names solid {placement.solid_index} of {self.part}, which the "
                f"published artifact does not have ({len(self.solids)} solids)",
            )
        solid = self.solids[placement.solid_index]
        if placement.kind == "solid":
            return solid
        if placement.kind in ("face", "edge"):
            topologies = list(solid.faces() if placement.kind == "face" else solid.edges())
            if placement.topo_index >= len(topologies):
                raise UnresolvableAnchorError(
                    "unaddressable_anchor",
                    f"tag {name!r} names {placement.kind} {placement.topo_index} of solid "
                    f"{placement.solid_index}, which the published artifact does not have",
                )
            return topologies[placement.topo_index]
        raise UnresolvableAnchorError(
            "unaddressable_anchor",
            f"tag {name!r} is a {placement.kind}, which a published artifact cannot address "
            "(only solids, faces and edges are relocatable in reloaded BRep)",
        )

    def _run_shape(self, resolution: Resolution) -> Any:
        if resolution.kind == "binding":
            raise UnresolvableAnchorError(
                "unaddressable_anchor",
                f"binding {resolution.name!r} is in {self.part}'s recorded §7 namespace, but a "
                "published artifact carries label runs (§8 geometries) and tag placements "
                "(§5.3) and no binding-to-solid record, so rule 4 cannot be located against "
                "it — the binding's node was relabelled, or it never reached part.geometry. "
                "Address the node by its label: §5.1 label-fill means a geometry-bearing "
                "binding that was never relabelled already resolves under rule 3, by this "
                "same name",
            )
        if not self.runs_partition:
            raise UnresolvableAnchorError(
                "unaddressable_anchor",
                f"{self.part}'s published label rows do not partition its solids (nested "
                "labels), so a label anchor cannot be mapped to geometry without guessing",
            )
        picked: list[Any] = []
        for occurrence in resolution.occurrences:
            if occurrence >= len(self.runs):
                raise UnresolvableAnchorError(
                    "unaddressable_anchor",
                    f"label {resolution.name!r} occurrence {occurrence} is outside "
                    f"{self.part}'s published label rows",
                )
            _, start, count = self.runs[occurrence]
            picked.extend(self.solids[start : start + count])
        if not picked:
            raise UnresolvableAnchorError(
                "unaddressable_anchor",
                f"label {resolution.name!r} contributed no solid to {self.part}'s published "
                "geometry",
            )
        if len(picked) == 1:
            return picked[0]
        from build123d import Compound

        return Compound(children=picked)


def addressable_namespace(index: GeometryIndex) -> tuple[str, ...]:
    """The subset of ``index``'s §7 namespace a published artifact can answer.

    :func:`hephaestus.core.addressing.namespace` advertises everything the
    build's namespace *contains*, which is the right answer inside the worker
    that still holds the live bindings. Parent-side it is not: publication
    records label runs and tag placements, never binding-to-solid, so a rule-4
    selector whose node carries some other label is a refusal here no matter
    how it is spelled (:meth:`PartGeometry._run_shape`). Offering one as a
    candidate would send the caller from one refusal straight into the next,
    which is the shape of "help" B-1 already cost fourteen months.

    Nothing addressable is lost. §5.1 label-fill gives every geometry-bearing
    binding that was not explicitly relabelled its binding name AS a label, so
    those names stay in this list under rule 3 — only a binding whose node was
    relabelled drops out, and that node is still addressable by the label it
    was given.
    """
    out: list[str] = []
    for name in namespace(index):
        try:
            resolution = resolve(name, index)
        except AddressingError:  # pragma: no cover - namespace() is total
            out.append(name)
            continue
        if resolution.kind != "binding":
            out.append(name)
    return tuple(out)


# --------------------------------------------------------------------------
# the published namespace, and where it sits in the artifact


def published_index(bundle: Mapping[str, JSONValue], result: BuildResult) -> GeometryIndex:
    """The §7 namespace of a published build.

    Publication records the worker's own ``geometry_index``; a bundle written
    before that (``ASSEMBLY.md`` §2 added it) falls back to the §8 ``geometries``
    rows, which are the same label set in the same order with the display
    dedup suffix applied — enough to address labels and to report a dangling
    tag honestly, rather than pretending an old build has no namespace at all.
    """
    raw = bundle.get("geometry_index")
    if isinstance(raw, dict):
        index = geometry_index_from_json(cast("Mapping[str, JSONValue]", raw))
        if index.labels or index.tags or index.bindings:
            return index
    return GeometryIndex(labels=tuple(_raw_labels(result)), bindings={}, tags=frozenset())


def _raw_labels(result: BuildResult) -> Iterable[str]:
    """Undo the §7 display dedup (``name#2`` -> ``name``) on ``geometries`` rows."""
    for entry in result.geometries:
        base, separator, suffix = entry.label.rpartition("#")
        yield base if separator and suffix.isdigit() else entry.label


def solid_runs(
    index: GeometryIndex, result: BuildResult, solid_count: int
) -> tuple[tuple[tuple[str, int, int], ...], bool]:
    """Map each label row to its run of solids (tree order == solid order).

    The §3.3 selection table (:mod:`hephaestus.core.render.inspect`) reads a
    published artifact the same way: rows are consecutive runs of solids in
    tree order. That mapping only holds when the rows PARTITION the artifact's
    solids; a label on a compound *and* on its children counts the same solids
    twice, and the second return value says so, because guessing which run a
    nested label meant is exactly what §7 forbids.
    """
    counts = [max(entry.solids, 0) for entry in result.geometries]
    labels = list(index.labels)
    runs: list[tuple[str, int, int]] = []
    start = 0
    for position, label in enumerate(labels):
        count = counts[position] if position < len(counts) else 0
        runs.append((label, start, count))
        start += count
    return tuple(runs), start == solid_count and len(counts) == len(labels)


def tag_placements(source_map: Mapping[str, JSONValue] | None) -> dict[str, TagPlacement]:
    """Reconstruct ``{tag: TagPlacement}`` from a published source-map artifact.

    The one decoder for the §5.3 ``tags`` table as publication stored it. Anchor
    resolution and the §3.3 selection table both read it, and a second decoder
    is how the two would come to disagree about where a tag sits.
    """
    out: dict[str, TagPlacement] = {}
    if source_map is None:
        return out
    tags = source_map.get("tags")
    if not isinstance(tags, dict):
        return out
    for name, raw in cast("Mapping[str, JSONValue]", tags).items():
        if not isinstance(raw, dict):
            continue
        placement = cast("Mapping[str, JSONValue]", raw)
        kind = placement.get("kind")
        solid = placement.get("solid")
        topo = placement.get("topo_index")
        statement = placement.get("statement")
        line = placement.get("line")
        if not isinstance(kind, str):
            continue
        out[name] = TagPlacement(
            kind=kind,
            solid_index=solid if isinstance(solid, int) and not isinstance(solid, bool) else None,
            topo_index=topo if isinstance(topo, int) and not isinstance(topo, bool) else None,
            statement_index=(
                statement if isinstance(statement, int) and not isinstance(statement, bool) else -1
            ),
            line=line if isinstance(line, int) and not isinstance(line, bool) else 0,
        )
    return out


def part_geometry(
    *,
    part: str,
    artifact_ref: str,
    shape: Any,
    index: GeometryIndex,
    placements: Mapping[str, TagPlacement],
    result: BuildResult,
) -> PartGeometry:
    """Join one reloaded artifact with what publication recorded beside it.

    The single constructor of an addressable published artifact. ``index`` and
    ``placements`` are *facts of the publication* (:func:`published_index` and
    :func:`tag_placements` read them off the bundle and the source map); only
    the solid list and the label runs are derived here, and both are derived
    from the §8 record rather than from the BRep, which is exactly the
    information a reload does not carry.
    """
    solids = tuple(cast("list[Any]", shape.solids()))
    runs, partition = solid_runs(index, result, len(solids))
    return PartGeometry(
        part=part,
        artifact_ref=artifact_ref,
        shape=shape,
        index=index,
        solids=solids,
        runs=runs,
        placements=placements,
        runs_partition=partition,
    )
