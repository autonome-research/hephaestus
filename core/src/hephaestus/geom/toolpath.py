# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
# pyright: reportMissingTypeStubs=false
# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false
# pyright: reportUnknownVariableType=false, reportUnknownParameterType=false

"""Toolpath geometry: contour-offset ladders, moves and tool solids (CAM.md §4).

A pure geometry service — the eleventh under the standing ``hephaestus.geom``
contract, admitted by Gate G14B clause 1: functions over shapes the caller
already holds, no executor, no project store, no verdicts. Everything that
*decides* — stock resolution, feed transport, refusal filing, emission — is
engine (:mod:`hephaestus.core.machining`) and deliberately not here.

The 2D offset **primitive** is the one kerf already calls
(``wire.offset_2d(distance, kind=Kind.INTERSECTION)``, ``kerf.py:228``), and
the primitive is all that is shared. Kerf offsets each ring exactly once and
treats a collapsed offset as a terminal refusal (``kerf.py:235-236``); a
pocket-clearing ladder offsets the same boundary repeatedly inward, and
collapse is its **termination condition** — the normal end of a correct run.
Two pieces of machinery follow (CAM.md §4.1, §11 item 6), and both live here:

* **Iterated offsetting with an explicit termination rule.** Loop ``k`` is
  emitted at inward distance ``tool_radius + k * stepover_mm``; the ladder
  terminates when the next offset either fails to bound a face or bounds one
  of area below :data:`TOOLPATH_MIN_LOOP_AREA_MM2`. Termination is a **fact**,
  reported as :attr:`LadderResult.termination` next to ``loops_emitted`` —
  never a refusal, because a pocket that clears completely is a pocket whose
  ladder terminated. The case where the tool does not fit at all is decided
  *before* the ladder runs (:func:`tool_fits`) and is the engine's separate
  named refusal ``feature_below_tool_radius``.
* **Self-intersection pruning.** Offsetting a non-convex boundary inward makes
  the offset self-intersect and split; each ladder rung collects every wire
  the kernel produced, discards degenerate branches (a wire that bounds no
  face, or one below the area floor), and carries the disjoint loops forward
  as separate rings, each terminating on its own.

The one refusal this module owns is :class:`ToolpathRefusal` with reason
``toolpath_offset_failed`` — the **kernel-error case and nothing else**, the
``except Exception`` branch shape of ``kerf.py:227-230``, carrying the ring
index and the distance. A collapsed offset is deliberately not this refusal
(CAM.md §4.3); conflating the two would make every correctly-cleared pocket
end in a named refusal.

The move vocabulary is **closed** (:data:`MOVE_KINDS`, CAM.md §4.2). Arcs may
exist only where the source geometry was a true circular arc; this module
performs **no arc fitting of linearized paths** — every discretised boundary
becomes ``linear`` moves, because a fitted arc is a claim about a path the
harness approximated.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Final, Literal

from hephaestus.core.cutfile import COORD_DECIMALS, ring_points
from opstore.types import JSONValue

__all__ = [
    "MOVE_KINDS",
    "TOOLPATH_MIN_LOOP_AREA_MM2",
    "LadderResult",
    "LadderTermination",
    "Move",
    "MoveKind",
    "MoveList",
    "OffsetLoop",
    "ToolSolid",
    "ToolpathRefusal",
    "moves_for_rings",
    "offset_ladder",
    "profile_moves",
    "sample_count",
    "swept_solid",
    "tool_fits",
    "tool_solid",
]

#: Offset-ladder **termination** floor (mm^2): the next inward offset bounding
#: a face below this has collapsed, and the ladder stops. This is the
#: ``kerf.py:74`` predicate read as a **stop rather than a refusal**
#: (CAM.md §4.1, §5.7) — the difference that makes clause G14B-2 (empty
#: refusal lists on normal collapse) and clause G14B-16 satisfiable together.
TOOLPATH_MIN_LOOP_AREA_MM2: Final[float] = 1e-6

MoveKind = Literal[
    "rapid", "linear", "arc_cw", "arc_ccw", "dwell", "tool_change", "spindle", "coolant"
]

#: The closed move vocabulary (CAM.md §4.2). A kind outside this set is
#: refused at construction; the set grows only by contract amendment.
MOVE_KINDS: Final[tuple[MoveKind, ...]] = (
    "rapid",
    "linear",
    "arc_cw",
    "arc_ccw",
    "dwell",
    "tool_change",
    "spindle",
    "coolant",
)


class ToolpathRefusal(Exception):
    """The kernel could not build an offset boundary; ``data`` names ring and distance.

    Reason is always ``toolpath_offset_failed`` and it fires **only** on a
    kernel error — never on a collapsed offset, which is the ladder's
    termination fact (CAM.md §4.1/§4.3).
    """

    def __init__(self, message: str, *, data: dict[str, JSONValue]) -> None:
        super().__init__(message)
        self.reason: Final[str] = "toolpath_offset_failed"
        self.message = message
        self.data = data


@dataclass(frozen=True)
class Move:
    """One move: endpoint in WCS millimetres, feed source, producing operation.

    ``feed_mm_min`` is ``None`` exactly for moves that do not cut (rapids,
    state changes); a cutting move's feed is transported by the engine's
    ``FeedDecision`` and never invented here.

    ``i``/``j`` are the arc-centre offsets from the move's START point and are
    meaningful only on ``arc_cw``/``arc_ccw`` moves — the §4.2 rule stands:
    arcs exist only where the source geometry was a true circular arc, and no
    generator in this repo fits one to a linearized path. They default to
    ``None`` so every existing linear-only ``MoveList`` serializes to the same
    bytes it did before the fields existed (Gate G14B clause 21's surface is
    unchanged).
    """

    kind: MoveKind
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    feed_mm_min: float | None = None
    feed_source: str | None = None
    op_id: str | None = None
    i: float | None = None
    j: float | None = None

    def __post_init__(self) -> None:
        if self.kind not in MOVE_KINDS:
            raise ValueError(
                f"move kind {self.kind!r} is outside the closed vocabulary "
                f"({', '.join(MOVE_KINDS)}) — CAM.md §4.2"
            )
        if (self.i is not None or self.j is not None) and self.kind not in ("arc_cw", "arc_ccw"):
            raise ValueError(
                f"move kind {self.kind!r} carries no arc centre — i/j are arc fields "
                "(CAM.md §4.2)"
            )

    def to_json(self) -> dict[str, JSONValue]:
        out: dict[str, JSONValue] = {
            "kind": self.kind,
            "x": round(self.x, COORD_DECIMALS),
            "y": round(self.y, COORD_DECIMALS),
            "z": round(self.z, COORD_DECIMALS),
        }
        if self.feed_mm_min is not None:
            out["feed_mm_min"] = round(self.feed_mm_min, COORD_DECIMALS)
        if self.feed_source is not None:
            out["feed_source"] = self.feed_source
        if self.op_id is not None:
            out["op_id"] = self.op_id
        if self.i is not None:
            out["i"] = round(self.i, COORD_DECIMALS)
        if self.j is not None:
            out["j"] = round(self.j, COORD_DECIMALS)
        return out


@dataclass(frozen=True)
class MoveList:
    """An ordered, closed-vocabulary move list; serialization is canonical.

    ``serialize()`` is the byte-reproducibility surface Gate G14B clause 21
    binds to: fixed iteration order, :data:`COORD_DECIMALS` rounding on every
    coordinate, no RNG anywhere (CAM.md §4.4).
    """

    moves: tuple[Move, ...] = ()

    def __len__(self) -> int:
        return len(self.moves)

    def to_json(self) -> list[JSONValue]:
        return [move.to_json() for move in self.moves]

    def serialize(self) -> bytes:
        import json

        return json.dumps(self.to_json(), sort_keys=True, separators=(",", ":")).encode("utf-8")


@dataclass(frozen=True)
class OffsetLoop:
    """One emitted ring: ladder index, inward distance, bounded area, polyline."""

    loop_index: int
    distance_mm: float
    area_mm2: float
    points: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class LadderTermination:
    """The ladder's termination **fact** (never a refusal): where and why it stopped.

    ``reason`` is ``offset_collapsed`` when the next offset bounded no face at
    all, ``below_min_loop_area`` when it bounded one under
    :data:`TOOLPATH_MIN_LOOP_AREA_MM2`.
    """

    loop_index: int
    distance_mm: float
    reason: Literal["offset_collapsed", "below_min_loop_area"]

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "loop_index": self.loop_index,
            "distance_mm": round(self.distance_mm, COORD_DECIMALS),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class LadderResult:
    """Every ring the ladder emitted, plus its termination fact.

    ``loops_emitted`` counts rings across every rung — a rung that split
    (self-intersection pruning) contributes one per disjoint ring.
    """

    loops: tuple[OffsetLoop, ...]
    termination: LadderTermination

    @property
    def loops_emitted(self) -> int:
        return len(self.loops)


# --------------------------------------------------------------------------
# the offset primitive, split-aware


def _kernel_offset(wire: Any, distance: float) -> list[Any]:
    """The raw kernel offset: one inward offset, every wire it produced.

    The primitive is kerf's (``BRepOffsetAPI_MakeOffset`` with the
    ``Kind.INTERSECTION`` join, ``kerf.py:228``'s ``offset_2d`` reached one
    level down, because a split offset comes back as **several** wires and
    ``Wire.offset_2d`` refuses that shape). Module-level on purpose: this is
    the seam clause G14B-16's fault injection replaces, exactly as the kerf
    gate injects into ``offset_2d``.
    """
    from build123d import Wire
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform  # pyright: ignore[reportAttributeAccessIssue]
    from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeOffset  # pyright: ignore[reportAttributeAccessIssue]
    from OCP.GeomAbs import GeomAbs_JoinType  # pyright: ignore[reportAttributeAccessIssue]
    from OCP.TopAbs import TopAbs_ShapeEnum  # pyright: ignore[reportAttributeAccessIssue]
    from OCP.TopExp import TopExp_Explorer  # pyright: ignore[reportAttributeAccessIssue]
    from OCP.TopLoc import TopLoc_Location  # pyright: ignore[reportAttributeAccessIssue]
    from OCP.TopoDS import TopoDS  # pyright: ignore[reportAttributeAccessIssue]

    # Normalize the input to a LOCATION-FREE wire first (bake the TopLoc
    # transform into the geometry, then clear it). ``BRepOffsetAPI_MakeOffset``
    # composes a located wire's placement into its output geometry a second
    # time, so a boundary that reached here through a placed face — every
    # reloaded published artifact — would come back offset around a doubled
    # centre. Found by Gate G14C's removal simulation, whose booleans are the
    # first consumer of these rings' ABSOLUTE coordinates (the 14B clauses
    # assert areas and counts, which are placement-invariant).
    raw = wire.wrapped
    if not raw.Location().IsIdentity():
        raw = BRepBuilderAPI_Transform(raw, raw.Location().Transformation(), True).Shape()
        raw = raw.Located(TopLoc_Location())
    maker = BRepOffsetAPI_MakeOffset()
    maker.Init(GeomAbs_JoinType.GeomAbs_Intersection, False)
    maker.AddWire(TopoDS.Wire_s(raw))
    maker.Perform(-abs(distance))
    shape = maker.Shape()
    out: list[Any] = []
    if shape is not None and not shape.IsNull():
        explorer = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_WIRE)
        while explorer.More():
            out.append(Wire(TopoDS.Wire_s(explorer.Current())))
            explorer.Next()
    return out


def _inward_wires(wire: Any, distance: float, *, loop_index: int) -> list[Any]:
    """:func:`_kernel_offset`, with a kernel error filed as the one refusal.

    A kernel exception here — and only here — is ``toolpath_offset_failed``,
    the ``except Exception`` branch shape of ``kerf.py:227-230``. A collapsed
    offset never reaches this branch: the kernel returns an empty or
    degenerate wire set for that, and the ladder reads it as termination.
    """
    try:
        return _kernel_offset(wire, distance)
    except Exception as exc:  # OCC raises a bare RuntimeError on a failed offset
        raise ToolpathRefusal(
            f"the kernel could not build an offset boundary at loop {loop_index} "
            f"(inward {abs(distance):.4f} mm)",
            data={"ring": loop_index, "offset_mm": -abs(distance)},
        ) from exc


def _bounded_area(candidate: Any) -> float | None:
    """The area a candidate offset wire bounds, or ``None`` for a degenerate branch.

    ``None`` and near-zero are **termination/pruning inputs**, never errors:
    an inward offset past a region's local width returns a self-intersecting
    or empty boundary, and that is the normal end of that ring's life.
    """
    from build123d import Face

    try:
        return float(Face(candidate).area)
    except Exception:
        return None


def tool_fits(boundary: Any, tool_radius_mm: float) -> bool:
    """Whether a tool of ``tool_radius_mm`` fits inside ``boundary`` at all.

    Decided **before** the ladder runs (CAM.md §4.1): the engine files
    ``feature_below_tool_radius`` on ``False``, so a zero-loop ladder is never
    how that fact is discovered. The probe is the ladder's own first rung —
    an inward offset by the tool radius that bounds a real face.
    """
    wires = _inward_wires(boundary, tool_radius_mm, loop_index=0)
    for candidate in wires:
        area = _bounded_area(candidate)
        if area is not None and area >= TOOLPATH_MIN_LOOP_AREA_MM2:
            return True
    return False


def offset_ladder(boundary: Any, *, tool_radius_mm: float, stepover_mm: float) -> LadderResult:
    """The concentric clearing ladder over one closed boundary (CAM.md §4.1).

    Emits loop ``k`` at inward distance ``tool_radius_mm + k * stepover_mm``
    until the next offset collapses — which is reported as the termination
    fact, never raised. The caller must have decided ``tool_fits`` first;
    calling with a tool that does not fit yields an empty ladder terminating
    at loop 0, which the engine treats as a contract misuse, not as how
    ``feature_below_tool_radius`` is discovered.
    """
    if tool_radius_mm <= 0.0 or not math.isfinite(tool_radius_mm):
        raise ValueError(f"tool_radius_mm must be a positive length (got {tool_radius_mm})")
    if stepover_mm <= 0.0 or not math.isfinite(stepover_mm):
        raise ValueError(f"stepover_mm must be a positive length (got {stepover_mm})")
    loops: list[OffsetLoop] = []
    index = 0
    while True:
        distance = tool_radius_mm + index * stepover_mm
        rung: list[OffsetLoop] = []
        collapsed_area: float | None = None
        for candidate in _inward_wires(boundary, distance, loop_index=index):
            area = _bounded_area(candidate)
            if area is None:
                continue  # degenerate branch: pruned, carried by no ring
            if area < TOOLPATH_MIN_LOOP_AREA_MM2:
                collapsed_area = area
                continue
            rung.append(
                OffsetLoop(
                    loop_index=index,
                    distance_mm=distance,
                    area_mm2=area,
                    points=tuple(ring_points(candidate)),
                )
            )
        if not rung:
            reason: Literal["offset_collapsed", "below_min_loop_area"] = (
                "below_min_loop_area" if collapsed_area is not None else "offset_collapsed"
            )
            return LadderResult(
                loops=tuple(loops),
                termination=LadderTermination(
                    loop_index=index, distance_mm=distance, reason=reason
                ),
            )
        loops.extend(sorted(rung, key=lambda loop: loop.points))
        index += 1


# --------------------------------------------------------------------------
# rings and boundaries to moves (linear-only for discretised paths)


def moves_for_rings(
    loops: tuple[OffsetLoop, ...],
    *,
    z_mm: float,
    safe_z_mm: float,
    feed_mm_min: float,
    plunge_mm_min: float,
    feed_source: str,
    op_id: str,
) -> tuple[Move, ...]:
    """One clearing level's moves over already-computed rings.

    Rapid to each ring's start above the work, plunge at the plunge feed,
    then ``linear`` moves around the ring — never an arc, because the ring is
    a discretised polyline (CAM.md §4.2's no-arc-fitting rule).
    """
    out: list[Move] = []
    for loop in loops:
        if not loop.points:
            continue
        first = loop.points[0]
        out.append(Move(kind="rapid", x=first[0], y=first[1], z=safe_z_mm, op_id=op_id))
        out.append(
            Move(
                kind="linear",
                x=first[0],
                y=first[1],
                z=z_mm,
                feed_mm_min=plunge_mm_min,
                feed_source=feed_source,
                op_id=op_id,
            )
        )
        for point in (*loop.points[1:], first):
            out.append(
                Move(
                    kind="linear",
                    x=point[0],
                    y=point[1],
                    z=z_mm,
                    feed_mm_min=feed_mm_min,
                    feed_source=feed_source,
                    op_id=op_id,
                )
            )
        out.append(Move(kind="rapid", x=first[0], y=first[1], z=safe_z_mm, op_id=op_id))
    return tuple(out)


def profile_moves(
    boundary_points: tuple[tuple[float, float], ...],
    *,
    z_mm: float,
    safe_z_mm: float,
    tab_count: int,
    tab_width_mm: float,
    tab_top_z_mm: float,
    feed_mm_min: float,
    plunge_mm_min: float,
    feed_source: str,
    op_id: str,
) -> tuple[Move, ...]:
    """A profile pass with declared holding tabs as raised bridges.

    ``tab_count`` evenly spaced gaps of ``tab_width_mm`` (by arc length along
    the closed polyline) are bridged at ``tab_top_z_mm`` instead of cut at
    ``z_mm`` — declared, never inferred. With ``tab_count == 0`` the ring is
    cut through, exactly like one clearing ring.
    """
    if tab_count < 0:
        raise ValueError(f"tab_count must be non-negative (got {tab_count})")
    points = list(boundary_points)
    if len(points) < 3:
        raise ValueError("a profile boundary needs at least three points")
    closed = [*points, points[0]]
    lengths = [
        math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(points, closed[1:], strict=True)
    ]
    perimeter = sum(lengths)
    if tab_count and tab_count * tab_width_mm >= perimeter:
        raise ValueError(
            f"{tab_count} tabs of {tab_width_mm} mm exceed the {perimeter:.3f} mm perimeter"
        )

    def at_length(s: float) -> tuple[float, float]:
        s = s % perimeter
        acc = 0.0
        for (a, b), seg in zip(zip(points, closed[1:], strict=True), lengths, strict=True):
            if seg and acc + seg >= s:
                t = (s - acc) / seg
                return (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
            acc += seg
        return closed[-1]

    def cut(x: float, y: float, z: float, feed: float) -> Move:
        return Move(
            kind="linear", x=x, y=y, z=z, feed_mm_min=feed, feed_source=feed_source, op_id=op_id
        )

    out: list[Move] = []
    start = at_length(0.0)
    out.append(Move(kind="rapid", x=start[0], y=start[1], z=safe_z_mm, op_id=op_id))
    out.append(cut(start[0], start[1], z_mm, plunge_mm_min))
    if tab_count == 0:
        vertex_s = 0.0
        for seg, point in zip(lengths, closed[1:], strict=True):
            vertex_s += seg
            out.append(cut(point[0], point[1], z_mm, feed_mm_min))
    else:
        spacing = perimeter / tab_count
        events: list[tuple[float, str]] = []
        for tab in range(tab_count):
            centre = (tab + 0.5) * spacing
            events.append((centre - tab_width_mm / 2.0, "up"))
            events.append((centre + tab_width_mm / 2.0, "down"))
        # walk the perimeter, emitting vertices and tab bridges in arc-length order
        breakpoints = sorted(events)
        vertex_s = 0.0
        vertices: list[tuple[float, tuple[float, float]]] = []
        for seg, point in zip(lengths, closed[1:], strict=True):
            vertex_s += seg
            vertices.append((vertex_s, point))
        merged: list[tuple[float, str, tuple[float, float]]] = [
            *((s, "vertex", p) for s, p in vertices),
            *((s, kind, at_length(s)) for s, kind in breakpoints),
        ]
        merged.sort(key=lambda item: (item[0], item[1] != "up"))
        z_current = z_mm
        for _s, kind, point in merged:
            if kind == "up":
                out.append(cut(point[0], point[1], z_current, feed_mm_min))
                out.append(cut(point[0], point[1], tab_top_z_mm, feed_mm_min))
                z_current = tab_top_z_mm
            elif kind == "down":
                out.append(cut(point[0], point[1], z_current, feed_mm_min))
                out.append(cut(point[0], point[1], z_mm, plunge_mm_min))
                z_current = z_mm
            else:
                out.append(cut(point[0], point[1], z_current, feed_mm_min))
    out.append(Move(kind="rapid", x=start[0], y=start[1], z=safe_z_mm, op_id=op_id))
    return tuple(out)


def sample_count(moves: MoveList | tuple[Move, ...], step_mm: float) -> int:
    """The deterministic per-setup sample total the §5.3 cap is checked against.

    Fixed arithmetic over declared numbers (the ``sweep_axis_values``
    discipline): each positioning move contributes ``ceil(length / step) + 1``
    samples, with a floor of 2; non-positioning moves contribute none.
    """
    if step_mm <= 0.0 or not math.isfinite(step_mm):
        raise ValueError(f"step_mm must be a positive length (got {step_mm})")
    items = moves.moves if isinstance(moves, MoveList) else moves
    total = 0
    previous: Move | None = None
    for move in items:
        if move.kind in ("rapid", "linear", "arc_cw", "arc_ccw"):
            if previous is not None:
                length = math.hypot(
                    move.x - previous.x, move.y - previous.y, move.z - previous.z
                )
                total += max(2, math.ceil(length / step_mm) + 1)
            previous = move
    return total


# --------------------------------------------------------------------------
# the tool solid


@dataclass(frozen=True)
class ToolSolid:
    """Cutter, shank and holder envelopes built from one tool record.

    Every volume is hand-computable (three cylinders), and the axial extents
    are the record's own numbers: cutter ``[0, flute_length_mm]`` from the
    tip, shank ``[flute_length_mm, stickout_mm]``, holder
    ``[stickout_mm, stickout_mm + holder length]``. The cutter is the only
    body that may cut; shank and holder are the §5.5 collision bodies.
    """

    cutter: Any
    shank: Any | None
    holder: Any
    cutter_extent_mm: tuple[float, float] = field(default=(0.0, 0.0))
    shank_extent_mm: tuple[float, float] | None = None
    holder_extent_mm: tuple[float, float] = field(default=(0.0, 0.0))

    @property
    def cutter_volume_mm3(self) -> float:
        return float(self.cutter.volume)

    @property
    def shank_volume_mm3(self) -> float:
        return 0.0 if self.shank is None else float(self.shank.volume)

    @property
    def holder_volume_mm3(self) -> float:
        return float(self.holder.volume)


def tool_solid(
    *,
    diameter_mm: float,
    flute_length_mm: float,
    shank_diameter_mm: float,
    stickout_mm: float,
    holder_diameter_mm: float,
    holder_length_mm: float,
) -> ToolSolid:
    """The tool's three envelope cylinders, tip at the origin, axis +Z.

    Pure construction from declared numbers — nothing is measured or
    inferred, so ``pi * r^2 * h`` per body is the whole arithmetic a test
    needs (Gate G14B clause 5).
    """
    from build123d import Align, Cylinder, Pos

    for name, value in (
        ("diameter_mm", diameter_mm),
        ("flute_length_mm", flute_length_mm),
        ("shank_diameter_mm", shank_diameter_mm),
        ("holder_diameter_mm", holder_diameter_mm),
        ("holder_length_mm", holder_length_mm),
    ):
        if value <= 0.0 or not math.isfinite(value):
            raise ValueError(f"{name} must be a positive length (got {value})")
    if stickout_mm < flute_length_mm:
        raise ValueError(
            f"stickout_mm ({stickout_mm}) cannot be shorter than flute_length_mm "
            f"({flute_length_mm})"
        )
    bottom = (Align.CENTER, Align.CENTER, Align.MIN)
    cutter = Cylinder(diameter_mm / 2.0, flute_length_mm, align=bottom)
    shank_length = stickout_mm - flute_length_mm
    shank = (
        Pos(0, 0, flute_length_mm) * Cylinder(shank_diameter_mm / 2.0, shank_length, align=bottom)
        if shank_length > 0.0
        else None
    )
    holder = Pos(0, 0, stickout_mm) * Cylinder(
        holder_diameter_mm / 2.0, holder_length_mm, align=bottom
    )
    return ToolSolid(
        cutter=cutter,
        shank=shank,
        holder=holder,
        cutter_extent_mm=(0.0, flute_length_mm),
        shank_extent_mm=(flute_length_mm, stickout_mm) if shank is not None else None,
        holder_extent_mm=(stickout_mm, stickout_mm + holder_length_mm),
    )


def swept_solid(moves: MoveList | tuple[Move, ...], tool: ToolSolid, step_mm: float) -> Any:
    """The union of the cutter placed at sampled points along the moves.

    The dual of ``publish_sweep_envelope`` (fuse instead of cut), at exactly
    the samples :func:`sample_count` counts — so the label never claims
    samples the geometry did not visit. Pure and deliberately simple; the
    bounded, subprocess-confined use of it is the 14C engine's job.
    """
    from build123d import Pos

    if step_mm <= 0.0 or not math.isfinite(step_mm):
        raise ValueError(f"step_mm must be a positive length (got {step_mm})")
    items = moves.moves if isinstance(moves, MoveList) else moves
    placements: list[tuple[float, float, float]] = []
    previous: Move | None = None
    for move in items:
        if move.kind not in ("rapid", "linear", "arc_cw", "arc_ccw"):
            continue
        if previous is not None and move.kind != "rapid":
            length = math.hypot(move.x - previous.x, move.y - previous.y, move.z - previous.z)
            count = max(2, math.ceil(length / step_mm) + 1)
            for sample in range(count):
                t = sample / (count - 1)
                placements.append(
                    (
                        previous.x + t * (move.x - previous.x),
                        previous.y + t * (move.y - previous.y),
                        previous.z + t * (move.z - previous.z),
                    )
                )
        previous = move
    if not placements:
        raise ValueError("no cutting moves to sweep")
    solid: Any = None
    for x, y, z in placements:
        placed = Pos(x, y, z) * tool.cutter
        solid = placed if solid is None else solid + placed
    return solid
