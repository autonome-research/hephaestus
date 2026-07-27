"""Cut-file layer conventions: what a laser controller reads a layer as.

A DXF handed to a laser or router is not a drawing — it is a *machine program*.
Controllers (LightBurn, RDWorks, LaserCut, Ruida, Trotec JobControl…) do not
read geometry semantics; they map **layer name or colour** to a power/speed
pair. A file whose contours all sit on one layer therefore cannot say "cut this
through, engrave that, and only score the fold": the operator has to
re-separate the geometry by hand, and any mistake is destroyed material.

This module is the one place that decides which layer a contour belongs on, so
the nested-sheet writer (:mod:`hephaestus.geom.nesting`) and the as-built DXF
writer emit the *same* convention. It owns three things and nothing else:

* the four layer names and their standard ACI colours (:data:`LAYER_COLORS`);
* the **rule** that assigns a contour to a layer — never a guess, always the
  part's own semantics (:func:`layer_for_tag`);
* the discretisation of a wire or edge into the polyline a cut file carries
  (:func:`ring_points`, :func:`edge_points`, :func:`solid_marks`).

Packing, kerf and blank resolution are deliberately *not* here; ``nesting.py``
owns those and consumes this module through its exported names only.

## The convention

| layer | ACI | what a controller does with it | where the geometry comes from |
| --- | --- | --- | --- |
| ``CUT`` | 1 (red) | through-cut | every profile's outer ring and its inner rings (holes) |
| ``ENGRAVE`` | 5 (blue) | raster/marking pass, no penetration | topology tagged ``engrave_*`` |
| ``SCORE`` | 3 (green) | shallow scoring pass (fold/register lines) | topology tagged ``score_*`` |
| ``BLANK`` | 8 (grey) | reference only — not cut | the stock rectangle a sheet is packed on |

**Assignment is by rule.** A contour lands on ``ENGRAVE`` or ``SCORE`` only
because the part script tagged that topology with a name carrying the
documented prefix (``script_contract.md`` §5.3):

```python
tag(lid.faces().sort_by(Axis.Z)[-1], "engrave_logo")   # -> ENGRAVE
tag(panel.edges().group_by(Axis.X)[0], "score_fold")   # -> SCORE
```

Everything else is a through-cut. Nothing is inferred from geometry size,
depth or position — a heuristic that silently promotes a pocket to an engrave
pass is exactly the failure mode that scraps a sheet, so an untagged contour is
always cut.

A layer is written **only when it carries geometry**: a part with no tagged
engrave or score topology emits no ``ENGRAVE``/``SCORE`` layer at all, because
an empty layer in a controller's job list is an invitation to assign it a
power setting that then fires on nothing (or, worse, on the wrong pass).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from hephaestus.core.dfm.types import TopologyDescriptor

__all__ = [
    "BLANK_LAYER",
    "COORD_DECIMALS",
    "CURVE_SEGMENT_MM",
    "CUTFILE_LAYERS",
    "CUT_LAYER",
    "ENGRAVE_LAYER",
    "LAYER_COLORS",
    "LAYER_SVG_COLORS",
    "LAYER_TAG_PREFIXES",
    "MAX_CURVE_SEGMENTS",
    "MIN_CURVE_SEGMENTS",
    "SCORE_LAYER",
    "Mark",
    "Point",
    "edge_points",
    "layer_for_tag",
    "ring_points",
    "solid_marks",
]

Point = tuple[float, float]

#: Through-cut geometry: the profile outlines and their holes.
CUT_LAYER: Final[str] = "CUT"
#: Marking geometry that must not penetrate the stock.
ENGRAVE_LAYER: Final[str] = "ENGRAVE"
#: Shallow score lines (folds, register marks).
SCORE_LAYER: Final[str] = "SCORE"
#: The stock rectangle a nested sheet is packed on — reference, never cut.
BLANK_LAYER: Final[str] = "BLANK"

#: Every layer this project emits, in the order a file writes them.
CUTFILE_LAYERS: Final[tuple[str, ...]] = (BLANK_LAYER, CUT_LAYER, ENGRAVE_LAYER, SCORE_LAYER)

#: Standard AutoCAD Color Index per layer. Controllers that key on colour
#: rather than layer name (most Ruida-based ones) read the same intent.
LAYER_COLORS: Final[Mapping[str, int]] = {
    CUT_LAYER: 1,  # red
    ENGRAVE_LAYER: 5,  # blue
    SCORE_LAYER: 3,  # green
    BLANK_LAYER: 8,  # dark grey
}

#: The same four colours as SVG strokes, so the DXF and the SVG of one export
#: read identically when a human opens them side by side.
LAYER_SVG_COLORS: Final[Mapping[str, str]] = {
    CUT_LAYER: "#ff0000",
    ENGRAVE_LAYER: "#0000ff",
    SCORE_LAYER: "#00ff00",
    BLANK_LAYER: "#808080",
}

#: The §5.3 tag-name prefixes that move tagged topology off the cut layer.
#: Longest-prefix-first is irrelevant here (the prefixes are disjoint), but the
#: order is fixed so the rule is a lookup and never a search.
LAYER_TAG_PREFIXES: Final[tuple[tuple[str, str], ...]] = (
    ("engrave_", ENGRAVE_LAYER),
    ("score_", SCORE_LAYER),
)

#: Target chord length (mm) when discretising a curved edge. A 10 mm bore comes
#: out within ~0.03% of its true area, which is finer than any cutter's kerf.
CURVE_SEGMENT_MM: Final[float] = 0.5
#: Hard bounds on that segment count, so a hair-thin or enormous curve is still
#: a sane, deterministic polyline.
MIN_CURVE_SEGMENTS: Final[int] = 8
MAX_CURVE_SEGMENTS: Final[int] = 512
#: Decimal places every emitted coordinate is rounded to (determinism).
COORD_DECIMALS: Final[int] = 6


def layer_for_tag(tag: str) -> str | None:
    """The cut-file layer a §5.3 tag name names, or ``None`` for a through-cut.

    This is the whole assignment rule. ``"engrave_logo"`` is ``ENGRAVE``,
    ``"score_fold_a"`` is ``SCORE``, and every other tag — like every untagged
    contour — is cut. The prefix must be followed by something: a tag named
    exactly ``"engrave_"`` names no feature and is treated as untagged.
    """
    for prefix, layer in LAYER_TAG_PREFIXES:
        if tag.startswith(prefix) and len(tag) > len(prefix):
            return layer
    return None


@dataclass(frozen=True)
class Mark:
    """One non-cut contour: which layer it belongs on, and its polyline.

    ``closed`` distinguishes a tagged *face* (its outer boundary is a closed
    ring) from a tagged *edge* (an open path). A writer emits the former as a
    closed polyline and the latter as an open one, because a controller that
    closes a fold line cuts a slot the design does not have.
    """

    layer: str
    points: tuple[Point, ...]
    closed: bool

    def key(self) -> frozenset[Point]:
        """Order-independent identity of the contour (for coincidence tests)."""
        return frozenset(self.points)


def _segment_count(length: float) -> int:
    return min(MAX_CURVE_SEGMENTS, max(MIN_CURVE_SEGMENTS, math.ceil(length / CURVE_SEGMENT_MM)))


def _dedupe(points: list[Point], *, closed: bool) -> list[Point]:
    """Drop consecutive (and, when closed, wrap-around) duplicate points."""
    out: list[Point] = []
    for point in points:
        if out and abs(point[0] - out[-1][0]) < 1e-7 and abs(point[1] - out[-1][1]) < 1e-7:
            continue
        out.append(point)
    while (
        closed
        and len(out) > 1
        and abs(out[0][0] - out[-1][0]) < 1e-7
        and abs(out[0][1] - out[-1][1]) < 1e-7
    ):
        out.pop()
    return out


def ring_points(wire: Any) -> list[Point]:
    """Ordered closed ring of ``wire`` in its own plane's XY (straight + sampled).

    Straight edges keep their endpoints; curved edges are sampled at a
    :data:`CURVE_SEGMENT_MM` chord — a cut file is a polyline. The ring is
    implicitly closed, so the final point is not repeated.
    """
    from build123d import GeomType

    points: list[Point] = []
    for edge in wire.order_edges():
        if edge.geom_type == GeomType.LINE:
            samples = [0.0]
        else:
            count = _segment_count(round(float(edge.length), COORD_DECIMALS))
            samples = [index / count for index in range(count)]
        for parameter in samples:
            position = edge.position_at(parameter)
            points.append((float(position.X), float(position.Y)))
    return _dedupe(points, closed=True)


def edge_points(edge: Any) -> list[Point]:
    """Ordered **open** path of one edge in XY, endpoint included.

    A score line is a path, not a ring: the last point is emitted, and nothing
    joins it back to the first.
    """
    from build123d import GeomType

    if edge.geom_type == GeomType.LINE:
        samples = [0.0, 1.0]
    else:
        count = _segment_count(round(float(edge.length), COORD_DECIMALS))
        samples = [index / count for index in range(count + 1)]
    points = [
        (float(edge.position_at(parameter).X), float(edge.position_at(parameter).Y))
        for parameter in samples
    ]
    return _dedupe(points, closed=False)


def solid_marks(
    solid: Any,
    descriptors: Mapping[str, TopologyDescriptor],
    solid_index: int,
    *,
    plane: Any | None = None,
) -> tuple[Mark, ...]:
    """Every engrave/score contour one solid's tagged topology declares.

    ``descriptors`` is the build's tag table recovered from its source map
    (``descriptors_from_source_map``) — a published BRep carries no tags of its
    own, so this is the only thing that can put the script's names back onto
    these bytes. Only tags whose descriptor addresses ``solid_index`` and whose
    name matches :func:`layer_for_tag` produce a mark; a descriptor whose index
    is out of range for this artifact is skipped rather than guessed at.

    ``plane`` — when given — is the flat pattern's own plane: the contour is
    transformed into its local coordinates before the Z component is dropped,
    which is the orthographic projection a cut file wants. Without a plane the
    topology is projected straight onto global XY (the as-built +Z view).

    Marks come back in tag-name order, so two exports of the same build write
    the same file.
    """
    faces: list[Any] | None = None
    edges: list[Any] | None = None
    out: list[Mark] = []
    for name in sorted(descriptors):
        descriptor = descriptors[name]
        layer = layer_for_tag(name)
        if layer is None or descriptor.solid_id != solid_index:
            continue
        if descriptor.kind == "face":
            if faces is None:
                faces = list(solid.faces())
            if not 0 <= descriptor.topology_index < len(faces):
                continue
            wire: Any = faces[descriptor.topology_index].outer_wire()
            points = ring_points(plane.to_local_coords(wire) if plane is not None else wire)
            if len(points) >= 3:
                out.append(Mark(layer=layer, points=tuple(points), closed=True))
        elif descriptor.kind == "edge":
            if edges is None:
                edges = list(solid.edges())
            if not 0 <= descriptor.topology_index < len(edges):
                continue
            edge: Any = edges[descriptor.topology_index]
            points = edge_points(plane.to_local_coords(edge) if plane is not None else edge)
            if len(points) >= 2:
                out.append(Mark(layer=layer, points=tuple(points), closed=False))
    return tuple(out)
