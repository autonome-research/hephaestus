# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
# pyright: reportMissingTypeStubs=false
# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false
# pyright: reportUnknownVariableType=false, reportUnknownParameterType=false

"""Machining resolution and toolpath generation (CAM.md §3.6, §4, §5.3; Stage 14B).

The engine peer of the 2D cut-file path: :mod:`hephaestus.core.cam` owns
laser/waterjet DXF emission and is **byte-frozen by CAM.md §10** — this module
does not touch it, absorb it, or share a verb with it. What lives here is the
milling half the D2 mandate allows Stage 14B to ship: resolving declared CAM
state against real artifacts and generating an in-memory
:class:`~hephaestus.geom.toolpath.MoveList` from it. **Nothing here writes a
program to disk, and nothing here may** — Gate G14B clause 24 is a filesystem
assertion over every code path in this module.

The discipline is CAM.md §4.3's: **a refusal is filed at the lifecycle point
where its inputs exist**, each list closed:

* *resolution* (:func:`resolve_setup`) — ``unknown_tool``,
  ``stock_material_unknown``, ``stock_too_small`` (both sides, per axis, with
  the overhang in mm), ``wcs_anchor_unresolvable`` /
  ``feature_anchor_unresolvable`` (the 8C ``UNRESOLVABLE_REASONS`` carried in
  the refusal's data, never conflated), ``axis_not_parallel_to_spindle``
  (both sides of :data:`CAM_AXIS_EPS_DEG`), the four ``no_declared_*`` feed
  refusals with **no third branch** (§3.6), ``doc_exceeds_tool_limit`` (a
  refusal, never a clamp — the ``joint_limit_exceeded`` precedent), and
  ``budget_below_resolution`` against :func:`cam_min_resolvable_mm3` with the
  **largest** floor across the setup's operations;
* *generation* (:func:`generate_setup`) — ``no_matching_tool``,
  ``tool_too_short``, ``feature_below_tool_radius`` (decided **before** the
  ladder, via :func:`~hephaestus.geom.toolpath.tool_fits`),
  ``pocket_boundary_not_closed``, ``pocket_floor_not_planar``,
  ``unreachable_feature``, ``sample_cap_exceeded`` (the computed total over
  every move, against :data:`CAM_SIM_SAMPLES_MAX`), and
  ``toolpath_offset_failed`` — re-raised from the geom ladder's kernel-error
  branch **only**; a collapsed offset is the ladder's termination fact and
  arrives here as ``loops_emitted``, never as a refusal.

Feeds and speeds are **transported data** (§1.2/§3.6): the operation's
explicit value, else the tool record's ``feeds`` entry for
``(material, op kind)``, else the named refusal. There is no table lookup, no
chip-load formula, no scaling, no "reasonable default" — and unlike kerf,
absence is a refusal, not a note, because a program with an invented feed is
a legitimate-looking output that a spindle catches.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, cast

from hephaestus.core.assembly import AnchorResolver, UnresolvableAnchorError
from hephaestus.core.errors import ValidationError
from hephaestus.core.limits import CAM_SIM_SAMPLES_MAX, cam_min_resolvable_mm3
from hephaestus.core.project_store.cam import (
    CamState,
    OperationEntry,
    SetupEntry,
    StockEntry,
    WcsEntry,
)
from hephaestus.core.project_store.layout import ProjectLayout
from hephaestus.core.project_store.publication import Publisher
from hephaestus.core.registry._tools import ToolRecord, ToolsIndex
from hephaestus.geom.toolpath import (
    LadderTermination,
    Move,
    MoveList,
    ToolpathRefusal,
    moves_for_rings,
    offset_ladder,
    profile_moves,
    sample_count,
    tool_fits,
)
from opstore.types import JSONValue

from opstore import OpStore

__all__ = [
    "CAM_AXIS_EPS_DEG",
    "CAM_SIM_STEP_FRACTION",
    "CAM_SIM_STEP_MAX_MM",
    "CAM_SIM_STEP_MIN_MM",
    "SAFE_Z_CLEARANCE_MM",
    "FeedDecision",
    "MachiningError",
    "OperationProgram",
    "ResolvedOperation",
    "ResolvedSetup",
    "SetupProgram",
    "generate_setup",
    "resolve_feeds",
    "resolve_setup",
    "sim_step_mm",
    "spindle_axis_vector",
]

#: Feature axis vs declared spindle axis (CAM.md §3.1/§5.7), reusing the
#: ``CONCENTRIC_AXIS_EPS_DEG`` convention KINEMATICS.md §1 already reuses.
CAM_AXIS_EPS_DEG: Final[float] = 0.5

#: Per-move sample step as a fraction of the active tool's radius, clamped
#: (CAM.md §5.3). Declared, bounded, and always reported.
CAM_SIM_STEP_FRACTION: Final[float] = 0.10
CAM_SIM_STEP_MIN_MM: Final[float] = 0.05
CAM_SIM_STEP_MAX_MM: Final[float] = 2.0

#: Rapid clearance above the work for generated entry moves (engine policy,
#: reported in every program record; not a machine claim).
SAFE_Z_CLEARANCE_MM: Final[float] = 5.0

_AXIS_VECTORS: Final[Mapping[str, tuple[float, float, float]]] = {
    "+X": (1.0, 0.0, 0.0),
    "-X": (-1.0, 0.0, 0.0),
    "+Y": (0.0, 1.0, 0.0),
    "-Y": (0.0, -1.0, 0.0),
    "+Z": (0.0, 0.0, 1.0),
    "-Z": (0.0, 0.0, -1.0),
}


class MachiningError(ValidationError):
    """A resolution- or generation-time refusal; ``reason`` is the machine token."""

    def __init__(
        self, message: str, *, reason: str, data: Mapping[str, JSONValue] | None = None
    ) -> None:
        super().__init__(message, kind="contract")
        self.reason = reason
        self.data: dict[str, JSONValue] = dict(data or {})

    def to_json(self) -> dict[str, JSONValue]:
        return {"reason": self.reason, "message": self.message, "data": dict(self.data)}


def spindle_axis_vector(axis: str) -> tuple[float, float, float]:
    """The declared spindle direction as a unit vector (declared, never inferred)."""
    try:
        return _AXIS_VECTORS[axis]
    except KeyError:  # pragma: no cover - the ledger refuses these at declaration
        raise MachiningError(
            f"unknown spindle axis {axis!r}", reason="invalid_setup"
        ) from None


def sim_step_mm(tool_radius_mm: float) -> float:
    """The declared per-move sample step for one tool (CAM.md §5.3)."""
    return min(
        CAM_SIM_STEP_MAX_MM, max(CAM_SIM_STEP_MIN_MM, CAM_SIM_STEP_FRACTION * tool_radius_mm)
    )


# --------------------------------------------------------------------------
# feed resolution: transported, gated, never derived


@dataclass(frozen=True)
class FeedDecision:
    """Which numbers command the machine, and where each one came from.

    The :class:`~hephaestus.geom.kerf.KerfDecision` shape generalized to one
    record per operation (CAM.md §3.6): every resolved number is reported
    with its source (``explicit`` or ``tool``), so a reader never has to
    infer where a number came from. There is no ``none`` source — absence is
    one of the four named refusals, never a value.
    """

    feed_mm_min: float
    rpm: float
    plunge_mm_min: float
    doc_mm: float
    woc_mm: float | None
    sources: Mapping[str, str]
    tool_feed_source: str | None = None

    def to_json(self) -> dict[str, JSONValue]:
        out: dict[str, JSONValue] = {
            "feed_mm_min": self.feed_mm_min,
            "rpm": self.rpm,
            "plunge_mm_min": self.plunge_mm_min,
            "doc_mm": self.doc_mm,
            "sources": dict(sorted(self.sources.items())),
        }
        if self.woc_mm is not None:
            out["woc_mm"] = self.woc_mm
        if self.tool_feed_source is not None:
            out["tool_feed_source"] = self.tool_feed_source
        return out


#: number -> the named refusal its absence raises (CAM.md §3.6). Closed.
_FEED_REFUSALS: Final[Mapping[str, str]] = {
    "feed_mm_min": "no_declared_feed",
    "rpm": "no_declared_speed",
    "doc_mm": "no_declared_doc",
    "woc_mm": "no_declared_woc",
    "plunge_mm_min": "no_declared_feed",
}


def resolve_feeds(operation: OperationEntry, tool: ToolRecord, material: str) -> FeedDecision:
    """The §3.6 fixed source order, number by number, with no third branch.

    1. the operation entry's explicit value; 2. else the tool record's
    ``feeds`` entry matching the resolved material id **and** the operation
    kind, reported with ``source: "tool"``; 3. else the named refusal. No
    case produces a number from neither — Gate G14B clause 13 asserts this by
    exhausting the branches.
    """
    entry = tool.feed_for(material, operation.kind)

    def number(name: str, *, required: bool) -> tuple[float | None, str | None]:
        explicit = operation.feeds.get(name)
        if explicit is not None:
            return float(explicit), "explicit"
        if entry is not None:
            value = float(getattr(entry, name, 0.0) or 0.0)
            if value > 0.0:
                return value, "tool"
        if not required:
            return None, None
        raise MachiningError(
            f"operation {operation.id}: no declared {name} — not on the entry, and tool "
            f"{tool.id!r} declares no ({material!r}, {operation.kind!r}) feeds value for it. "
            f"There is no third branch: nothing is looked up, derived or defaulted "
            f"(CAM.md §1.2/§3.6)",
            reason=_FEED_REFUSALS[name],
            data={"operation": operation.id, "tool": tool.id, "material": material, "number": name},
        )

    sources: dict[str, str] = {}
    feed, source = number("feed_mm_min", required=True)
    assert feed is not None and source is not None
    sources["feed_mm_min"] = source
    rpm, source = number("rpm", required=True)
    assert rpm is not None and source is not None
    sources["rpm"] = source
    doc, source = number("doc_mm", required=True)
    assert doc is not None and source is not None
    sources["doc_mm"] = source
    needs_woc = operation.kind in ("pocket", "face")
    woc, source = number("woc_mm", required=needs_woc)
    if woc is not None and source is not None:
        sources["woc_mm"] = source
    plunge, source = number("plunge_mm_min", required=True)
    assert plunge is not None and source is not None
    sources["plunge_mm_min"] = source
    if tool.max_doc_mm > 0.0 and doc > tool.max_doc_mm:
        raise MachiningError(
            f"operation {operation.id}: declared doc_mm {doc:g} exceeds tool {tool.id!r} "
            f"max_doc_mm {tool.max_doc_mm:g} — a refusal, not a clamp: an evaluation never "
            f"silently clamps (KINEMATICS.md:123-125, applied by CAM.md §3.6)",
            reason="doc_exceeds_tool_limit",
            data={
                "operation": operation.id,
                "tool": tool.id,
                "doc_mm": doc,
                "max_doc_mm": tool.max_doc_mm,
            },
        )
    return FeedDecision(
        feed_mm_min=feed,
        rpm=rpm,
        plunge_mm_min=plunge,
        doc_mm=doc,
        woc_mm=woc,
        sources=sources,
        tool_feed_source=entry.source if entry is not None else None,
    )


# --------------------------------------------------------------------------
# resolution


@dataclass(frozen=True)
class ResolvedOperation:
    """One operation bound to its tool, feature geometry and transported feeds."""

    entry: OperationEntry
    tool: ToolRecord
    feeds: FeedDecision
    feature_shape: Any
    feature_rule: str
    artifact_ref: str
    step_mm: float
    floor_mm3: float


@dataclass(frozen=True)
class ResolvedSetup:
    """One setup with every named record bound and every §4.3 resolution check run."""

    setup: SetupEntry
    stock: StockEntry
    wcs: WcsEntry
    wcs_rule: str
    wcs_artifact_ref: str
    material: str
    operations: tuple[ResolvedOperation, ...]
    floor_mm3: float
    binding_floor_operation: str | None
    stock_min_mm: tuple[float, float, float]
    stock_max_mm: tuple[float, float, float]


def _anchor_refusal(
    exc: UnresolvableAnchorError, *, reason: str, subject: str, anchor: str
) -> MachiningError:
    """An 8C anchoring failure as the owning CAM refusal, its reason preserved.

    The taxonomy is **extended, not replaced** (CAM.md §3.4): the CAM token
    names which declaration could not resolve, and the 8C reason
    (``missing_part`` / ``no_current_build`` / ``dangling_selector`` / …)
    rides in the data unconflated.
    """
    return MachiningError(
        f"{subject}: anchor {anchor!r} is unresolvable ({exc.reason}): {exc.detail}",
        reason=reason,
        data={"anchor": anchor, "unresolvable_reason": exc.reason, "detail": exc.detail},
    )


def _shape_bbox(shape: Any) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    box = shape.bounding_box()
    return (
        (float(box.min.X), float(box.min.Y), float(box.min.Z)),
        (float(box.max.X), float(box.max.Y), float(box.max.Z)),
    )


def _check_stock_fits(
    stock: StockEntry, resolver: AnchorResolver
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """The part fits inside the stock at the declared origin, or ``stock_too_small``.

    The stock's minimum corner is the resolved ``origin_anchor`` geometry's
    bounding-box minimum plus ``origin_offset_mm``; the refusal names the
    axis, the side, and the overhang in millimetres (CAM.md §3.2).
    """
    part, _, selector = stock.origin_anchor.partition(":")
    selector = selector or "part"
    try:
        geometry, resolution = resolver.locate(part, selector)
        anchor_shape = geometry.shape_for(resolution)
    except UnresolvableAnchorError as exc:
        raise _anchor_refusal(
            exc, reason="invalid_stock", subject=f"stock {stock.id}", anchor=stock.origin_anchor
        ) from exc
    anchor_min, _ = _shape_bbox(anchor_shape)
    part_min, part_max = _shape_bbox(geometry.shape)
    stock_min = tuple(anchor_min[i] + stock.origin_offset_mm[i] for i in range(3))
    stock_max = tuple(stock_min[i] + stock.extents_mm[i] for i in range(3))
    eps = 1e-9
    for axis_index, axis in enumerate(("X", "Y", "Z")):
        low = stock_min[axis_index] - part_min[axis_index]
        if low > eps:
            raise MachiningError(
                f"stock {stock.id}: the part overhangs the stock by {low:.6f} mm on the "
                f"{axis} minimum side",
                reason="stock_too_small",
                data={"stock": stock.id, "axis": axis, "side": "min", "overhang_mm": low},
            )
        high = part_max[axis_index] - stock_max[axis_index]
        if high > eps:
            raise MachiningError(
                f"stock {stock.id}: the part overhangs the stock by {high:.6f} mm on the "
                f"{axis} maximum side",
                reason="stock_too_small",
                data={"stock": stock.id, "axis": axis, "side": "max", "overhang_mm": high},
            )
    return (
        cast("tuple[float, float, float]", stock_min),
        cast("tuple[float, float, float]", stock_max),
    )


def _is_planar_face(shape: Any) -> bool:
    from build123d import Face, GeomType

    return isinstance(shape, Face) and shape.geom_type == GeomType.PLANE


def _cylinder_facts(
    shape: Any,
) -> tuple[tuple[float, float, float], tuple[float, float, float], float] | None:
    """``(axis point, axis direction, radius)`` of a cylindrical face, else None."""
    from build123d import Face, GeomType

    if not isinstance(shape, Face) or shape.geom_type != GeomType.CYLINDER:
        return None
    from OCP.BRepAdaptor import BRepAdaptor_Surface  # pyright: ignore[reportAttributeAccessIssue]
    from OCP.TopoDS import TopoDS  # pyright: ignore[reportAttributeAccessIssue]

    adaptor = BRepAdaptor_Surface(TopoDS.Face_s(shape.wrapped))
    cylinder = adaptor.Cylinder()
    axis = cylinder.Axis()
    location, direction = axis.Location(), axis.Direction()
    return (
        (float(location.X()), float(location.Y()), float(location.Z())),
        (float(direction.X()), float(direction.Y()), float(direction.Z())),
        float(cylinder.Radius()),
    )


def _feature_axis(shape: Any) -> tuple[tuple[float, float, float], bool] | None:
    """``(axis, directed)`` for a feature: a planar face's outward normal
    (directed — it says which way the feature faces), or a cylinder's axis
    (undirected — a bore has no facing). ``None`` for any other class: the
    axis rule has no subject there, and generation names its own refusal.
    """
    if _is_planar_face(shape):
        try:
            normal = shape.normal_at()
            return ((float(normal.X), float(normal.Y), float(normal.Z)), True)
        except Exception:
            return None
    facts = _cylinder_facts(shape)
    if facts is not None:
        return (facts[1], False)
    return None


def _axis_angle_deg(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    """The undirected angle between two axes, in degrees."""
    dot = abs(a[0] * b[0] + a[1] * b[1] + a[2] * b[2])
    la = math.sqrt(a[0] ** 2 + a[1] ** 2 + a[2] ** 2)
    lb = math.sqrt(b[0] ** 2 + b[1] ** 2 + b[2] ** 2)
    if la == 0.0 or lb == 0.0:
        return 90.0
    return math.degrees(math.acos(max(-1.0, min(1.0, dot / (la * lb)))))


def resolve_setup(
    layout: ProjectLayout,
    store: OpStore,
    setup_id: str,
    *,
    tools: ToolsIndex,
    materials: Any | None = None,
    scratch: Path | None = None,
    resolver: AnchorResolver | None = None,
) -> ResolvedSetup:
    """Bind one declared setup's records, anchors, tools and budgets (CAM.md §4.3).

    Every refusal raised here is resolution-time by construction: it needs a
    registry record, a published artifact, or a bound tool. Declaration-time
    refusals have already been enforced by the ledgers, and generation-time
    ones cannot fire because no toolpath exists yet.
    """
    import tempfile

    cam = CamState(layout, store)
    setup = cast("SetupEntry", cam.setups.get(setup_id))
    stock = cast("StockEntry", cam.stock.get(setup.stock))
    wcs = cast("WcsEntry", cam.wcs.get(setup.wcs))
    cam.fixtures.get(setup.fixture)  # existence; the scene itself is 14C machinery
    if materials is not None and materials.get(stock.material) is None:
        raise MachiningError(
            f"stock {stock.id}: material {stock.material!r} is not in the materials "
            f"registry",
            reason="stock_material_unknown",
            data={"stock": stock.id, "material": stock.material},
        )
    operations = tuple(
        cast("OperationEntry", entry)
        for entry in cam.operations.state().active
        if cast("OperationEntry", entry).setup == setup_id
    )
    scratch_dir = scratch or Path(tempfile.mkdtemp(prefix="heph-cam-"))
    if resolver is None:
        # ``resolver`` is 14C's injection point for the pinned-snapshot
        # resolver (CAM.md §9's frozen-snapshot rule for ``m.program``);
        # every 14B caller keeps the CURRENT-artifact path unchanged.
        resolver = AnchorResolver(layout, store, Publisher(layout, store), scratch_dir)

    # WCS resolution through the 8C anchoring path (tag / label / binding).
    wcs_part, _, wcs_selector = wcs.datum.partition(":")
    wcs_selector = wcs_selector or "part"
    try:
        wcs_geometry, wcs_resolution = resolver.locate(wcs_part, wcs_selector)
        wcs_geometry.shape_for(wcs_resolution)
    except UnresolvableAnchorError as exc:
        raise _anchor_refusal(
            exc, reason="wcs_anchor_unresolvable", subject=f"wcs {wcs.id}", anchor=wcs.datum
        ) from exc

    stock_min, stock_max = _check_stock_fits(stock, resolver)
    spindle = spindle_axis_vector(setup.spindle_axis)

    resolved: list[ResolvedOperation] = []
    floor_mm3 = 0.0
    binding_operation: str | None = None
    for operation in operations:
        if not tools.has(operation.tool):
            raise MachiningError(
                f"operation {operation.id}: tool {operation.tool!r} is not in the tools "
                f"registry (known: {', '.join(tools.ids()) or 'none'})",
                reason="unknown_tool",
                data={"operation": operation.id, "tool": operation.tool},
            )
        tool = tools.get(operation.tool)
        part, selector = operation.feature_parts
        try:
            geometry, resolution = resolver.locate(part, selector)
            feature_shape = geometry.shape_for(resolution)
        except UnresolvableAnchorError as exc:
            raise _anchor_refusal(
                exc,
                reason="feature_anchor_unresolvable",
                subject=f"operation {operation.id}",
                anchor=operation.feature,
            ) from exc
        axis_info = _feature_axis(feature_shape)
        if axis_info is not None:
            axis, _directed = axis_info
            angle = _axis_angle_deg(axis, spindle)
            if angle > CAM_AXIS_EPS_DEG:
                raise MachiningError(
                    f"operation {operation.id}: feature axis diverges {angle:.4f} deg from "
                    f"the declared spindle axis {setup.spindle_axis} "
                    f"(CAM_AXIS_EPS_DEG = {CAM_AXIS_EPS_DEG})",
                    reason="axis_not_parallel_to_spindle",
                    data={
                        "operation": operation.id,
                        "angle_deg": angle,
                        "eps_deg": CAM_AXIS_EPS_DEG,
                        "spindle_axis": setup.spindle_axis,
                    },
                )
        feeds = resolve_feeds(operation, tool, stock.material)
        radius = tool.diameter_mm / 2.0
        step = sim_step_mm(radius)
        floor = cam_min_resolvable_mm3(step, radius, feeds.doc_mm)
        if floor > floor_mm3:
            floor_mm3 = floor
            binding_operation = operation.id
        resolved.append(
            ResolvedOperation(
                entry=operation,
                tool=tool,
                feeds=feeds,
                feature_shape=feature_shape,
                feature_rule=resolution.kind,
                artifact_ref=geometry.artifact_ref,
                step_mm=step,
                floor_mm3=floor,
            )
        )

    # budget_below_resolution: the largest floor over the setup's operations
    # binds (a budget must be resolvable everywhere it is applied), and the
    # refusal names the budget, the floor and the binding operation. It is
    # unraisable at declaration by construction: a setup entry names no tool.
    if resolved:
        budget = float(setup.tolerance.get("gouge_budget_mm3", 0.0))
        if budget < floor_mm3:
            raise MachiningError(
                f"setup {setup.id}: gouge_budget_mm3 {budget:g} is below the resolution "
                f"floor {floor_mm3:g} mm^3 (CAM_MIN_RESOLVABLE_MM3 at the binding "
                f"operation {binding_operation!r}) — a budget the simulation cannot "
                f"resolve reads as satisfied for the wrong reason (CAM.md §5.3)",
                reason="budget_below_resolution",
                data={
                    "setup": setup.id,
                    "budget_mm3": budget,
                    "floor_mm3": floor_mm3,
                    "operation": binding_operation or "",
                },
            )
    return ResolvedSetup(
        setup=setup,
        stock=stock,
        wcs=wcs,
        wcs_rule=wcs_resolution.kind,
        wcs_artifact_ref=wcs_geometry.artifact_ref,
        material=stock.material,
        operations=tuple(resolved),
        floor_mm3=floor_mm3,
        binding_floor_operation=binding_operation,
        stock_min_mm=stock_min,
        stock_max_mm=stock_max,
    )


# --------------------------------------------------------------------------
# generation


@dataclass(frozen=True)
class OperationProgram:
    """One operation's generated moves, its ladder facts, and its refusals.

    A refused operation carries its named refusal and **no moves** — nothing
    degrades to a plausible path (the ``kerf_offset_failed`` rule applied to
    motion, CAM.md §4.3). ``loops_emitted`` and ``termination`` are the §4.1
    facts; an empty ``refusals`` list on a normally-collapsed ladder is Gate
    G14B clause 2's whole subject.
    """

    op_id: str
    tool_id: str
    feeds: FeedDecision | None
    moves: tuple[Move, ...] = ()
    loops_emitted: int = 0
    termination: LadderTermination | None = None
    tabs_emitted: int = 0
    samples: int = 0
    refusals: tuple[Mapping[str, JSONValue], ...] = ()

    def to_json(self) -> dict[str, JSONValue]:
        out: dict[str, JSONValue] = {
            "op": self.op_id,
            "tool": self.tool_id,
            "loops_emitted": self.loops_emitted,
            "samples": self.samples,
            "refusals": [dict(refusal) for refusal in self.refusals],
            "moves": len(self.moves),
        }
        if self.feeds is not None:
            out["feeds"] = self.feeds.to_json()
        if self.termination is not None:
            out["termination"] = self.termination.to_json()
        if self.tabs_emitted:
            out["tabs_emitted"] = self.tabs_emitted
        return out


@dataclass(frozen=True)
class SetupProgram:
    """One setup's generated move list and the facts a checker needs."""

    setup_id: str
    operations: tuple[OperationProgram, ...]
    move_list: MoveList
    samples_total: int
    refusals: tuple[Mapping[str, JSONValue], ...] = ()

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "setup": self.setup_id,
            "operations": [op.to_json() for op in self.operations],
            "samples_total": self.samples_total,
            "refusals": [dict(refusal) for refusal in self.refusals],
            "moves": self.move_list.to_json(),
        }


def _boundary_wire(op: OperationEntry, shape: Any) -> Any:
    """The pocket/profile/face boundary wire, or the two named §4.3 refusals."""
    from build123d import Edge, Face, Wire

    if isinstance(shape, Edge | Wire):
        raise MachiningError(
            f"operation {op.id}: feature {op.feature!r} is an open path, not a closed "
            f"boundary",
            reason="pocket_boundary_not_closed",
            data={"operation": op.id, "feature": op.feature},
        )
    if not isinstance(shape, Face):
        raise MachiningError(
            f"operation {op.id}: feature {op.feature!r} is not a face",
            reason="pocket_floor_not_planar",
            data={"operation": op.id, "feature": op.feature},
        )
    if not _is_planar_face(shape):
        raise MachiningError(
            f"operation {op.id}: feature {op.feature!r} is not a planar floor — 2.5D "
            f"pocketing clears prismatic, planar-floored pockets only (CAM.md §2)",
            reason="pocket_floor_not_planar",
            data={"operation": op.id, "feature": op.feature},
        )
    wire = shape.outer_wire()
    if not bool(wire.is_closed):
        raise MachiningError(
            f"operation {op.id}: feature {op.feature!r} boundary is not closed",
            reason="pocket_boundary_not_closed",
            data={"operation": op.id, "feature": op.feature},
        )
    return wire


def _generate_operation(
    resolved: ResolvedOperation, setup: SetupEntry, spindle: tuple[float, float, float]
) -> OperationProgram:
    """One operation's moves, with every generation refusal filed by name."""
    op = resolved.entry
    tool = resolved.tool
    feeds = resolved.feeds
    radius = tool.diameter_mm / 2.0
    if tool.flute_length_mm < op.depth_mm or tool.stickout_mm < op.depth_mm:
        raise MachiningError(
            f"operation {op.id}: tool {tool.id!r} is too short for the declared "
            f"{op.depth_mm:g} mm depth (flute {tool.flute_length_mm:g} mm, stickout "
            f"{tool.stickout_mm:g} mm)",
            reason="tool_too_short",
            data={
                "operation": op.id,
                "tool": tool.id,
                "depth_mm": op.depth_mm,
                "flute_length_mm": tool.flute_length_mm,
                "stickout_mm": tool.stickout_mm,
            },
        )
    axis_info = _feature_axis(resolved.feature_shape)
    if axis_info is not None and axis_info[1]:
        axis = axis_info[0]
        facing = axis[0] * spindle[0] + axis[1] * spindle[1] + axis[2] * spindle[2]
        if facing < 0.0:
            raise MachiningError(
                f"operation {op.id}: feature {op.feature!r} faces away from the declared "
                f"spindle axis {setup.spindle_axis} and is not accessible from it",
                reason="unreachable_feature",
                data={
                    "operation": op.id,
                    "feature": op.feature,
                    "spindle_axis": setup.spindle_axis,
                },
            )
    if op.kind == "drill":
        return _generate_drill(resolved)
    boundary = _boundary_wire(op, resolved.feature_shape)
    _, _, z_face = _face_top(resolved.feature_shape)
    # A POCKET operation's tag names the pocket FLOOR the design already
    # carries (§3.7's prefix table tags the feature, not the blank), so the
    # material to clear stands ABOVE the tagged face: the levels descend from
    # ``floor + depth`` and finish exactly at the floor. A FACE operation's
    # tag names the surface being faced, so its levels descend below the tag
    # — found by Gate G14C's removal simulation, whose booleans are the first
    # consumer of the generated Z placements (the 14B clauses assert ladder
    # counts, which are Z-invariant).
    z_top = z_face + op.depth_mm if op.kind == "pocket" else z_face
    safe_z = z_top + SAFE_Z_CLEARANCE_MM
    if op.kind == "profile":
        return _generate_profile(resolved, boundary, z_face, safe_z)
    # pocket / face: the concentric clearing ladder (CAM.md §4.1)
    try:
        fits = tool_fits(boundary, radius)
    except ToolpathRefusal as exc:
        # The pre-ladder probe rides the same kernel primitive, so a kernel
        # error there is the same named refusal, never a fit verdict.
        raise MachiningError(
            f"operation {op.id}: {exc.message}",
            reason=exc.reason,
            data={"operation": op.id, **exc.data},
        ) from exc
    if not fits:
        raise MachiningError(
            f"operation {op.id}: feature {op.feature!r} carries an internal region "
            f"narrower than tool {tool.id!r} radius {radius:g} mm — decided before the "
            f"offset ladder runs, so a zero-loop ladder is never how this is discovered "
            f"(CAM.md §4.1)",
            reason="feature_below_tool_radius",
            data={"operation": op.id, "tool": tool.id, "tool_radius_mm": radius},
        )
    stepover = op.stepover_mm if op.stepover_mm is not None else feeds.woc_mm or radius
    try:
        ladder = offset_ladder(boundary, tool_radius_mm=radius, stepover_mm=stepover)
    except ToolpathRefusal as exc:
        raise MachiningError(
            f"operation {op.id}: {exc.message}",
            reason=exc.reason,
            data={"operation": op.id, **exc.data},
        ) from exc
    stepdown = op.stepdown_mm if op.stepdown_mm is not None else op.depth_mm
    levels = max(1, math.ceil(op.depth_mm / stepdown))
    moves: list[Move] = []
    for level in range(levels):
        z = z_top - min(op.depth_mm, (level + 1) * stepdown)
        moves.extend(
            moves_for_rings(
                ladder.loops,
                z_mm=z,
                safe_z_mm=safe_z,
                feed_mm_min=feeds.feed_mm_min,
                plunge_mm_min=feeds.plunge_mm_min,
                feed_source=feeds.sources["feed_mm_min"],
                op_id=op.id,
            )
        )
    samples = sample_count(tuple(moves), resolved.step_mm)
    return OperationProgram(
        op_id=op.id,
        tool_id=tool.id,
        feeds=feeds,
        moves=tuple(moves),
        loops_emitted=ladder.loops_emitted,
        termination=ladder.termination,
        samples=samples,
    )


def _face_top(face: Any) -> tuple[float, float, float]:
    box = face.bounding_box()
    return (float(box.min.X), float(box.min.Y), float(box.max.Z))


def _tab_number(tabs: Mapping[str, JSONValue], key: str) -> float:
    value = tabs.get(key, 0.0)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0.0
    return float(value)


def _generate_profile(
    resolved: ResolvedOperation, boundary: Any, z_top: float, safe_z: float
) -> OperationProgram:
    from hephaestus.core.cutfile import ring_points

    op = resolved.entry
    feeds = resolved.feeds
    points = tuple(ring_points(boundary))
    tabs = op.tabs or {}
    tab_count = int(_tab_number(tabs, "count"))
    depth = op.depth_mm
    tab_top = z_top - depth + _tab_number(tabs, "height_mm")
    moves = profile_moves(
        points,
        z_mm=z_top - depth,
        safe_z_mm=safe_z,
        tab_count=tab_count,
        tab_width_mm=_tab_number(tabs, "width_mm"),
        tab_top_z_mm=tab_top,
        feed_mm_min=feeds.feed_mm_min,
        plunge_mm_min=feeds.plunge_mm_min,
        feed_source=feeds.sources["feed_mm_min"],
        op_id=op.id,
    )
    return OperationProgram(
        op_id=op.id,
        tool_id=resolved.tool.id,
        feeds=feeds,
        moves=moves,
        loops_emitted=1,
        tabs_emitted=tab_count,
        samples=sample_count(moves, resolved.step_mm),
    )


def _generate_drill(resolved: ResolvedOperation) -> OperationProgram:
    """Peck drilling on a tagged bore: matched diameter, explicit retracts."""
    op = resolved.entry
    tool = resolved.tool
    feeds = resolved.feeds
    facts = _cylinder_facts(resolved.feature_shape)
    if facts is None:
        raise MachiningError(
            f"operation {op.id}: feature {op.feature!r} is not a cylindrical bore",
            reason="no_matching_tool",
            data={"operation": op.id, "feature": op.feature},
        )
    origin, _direction, bore_radius = facts
    if abs(2.0 * float(bore_radius) - tool.diameter_mm) > 1e-3:
        raise MachiningError(
            f"operation {op.id}: bore diameter {2.0 * float(bore_radius):.3f} mm has no "
            f"matching tool — tool {tool.id!r} is {tool.diameter_mm:g} mm, and drilled "
            f"diameter is the tool's diameter, never an approximation",
            reason="no_matching_tool",
            data={
                "operation": op.id,
                "tool": tool.id,
                "bore_diameter_mm": 2.0 * float(bore_radius),
                "tool_diameter_mm": tool.diameter_mm,
            },
        )
    if tool.flute_length_mm < op.depth_mm or tool.stickout_mm < op.depth_mm:
        raise MachiningError(
            f"operation {op.id}: tool {tool.id!r} is too short for the declared "
            f"{op.depth_mm:g} mm depth",
            reason="tool_too_short",
            data={"operation": op.id, "tool": tool.id, "depth_mm": op.depth_mm},
        )
    x, y = float(origin[0]), float(origin[1])
    z_top = float(resolved.feature_shape.bounding_box().max.Z)
    safe_z = z_top + SAFE_Z_CLEARANCE_MM
    peck = resolved.entry.stepdown_mm or op.depth_mm
    moves: list[Move] = [Move(kind="rapid", x=x, y=y, z=safe_z, op_id=op.id)]
    drilled = 0.0
    while drilled < op.depth_mm:
        drilled = min(op.depth_mm, drilled + peck)
        moves.append(
            Move(
                kind="linear",
                x=x,
                y=y,
                z=z_top - drilled,
                feed_mm_min=feeds.plunge_mm_min,
                feed_source=feeds.sources["plunge_mm_min"],
                op_id=op.id,
            )
        )
        moves.append(Move(kind="rapid", x=x, y=y, z=safe_z, op_id=op.id))
    return OperationProgram(
        op_id=op.id,
        tool_id=tool.id,
        feeds=feeds,
        moves=tuple(moves),
        samples=sample_count(tuple(moves), resolved.step_mm),
    )


def generate_setup(resolved: ResolvedSetup) -> SetupProgram:
    """Every operation's moves, in declared order, under the generation caps.

    A refused operation is recorded **as its named refusal with no moves**;
    the rest of the setup still generates, so a report can name every refusal
    rather than only the first. ``sample_cap_exceeded`` is checked over the
    computed total across every generated move, naming the total and the
    operation whose moves pushed it over (CAM.md §5.3).
    """
    spindle = spindle_axis_vector(resolved.setup.spindle_axis)
    programs: list[OperationProgram] = []
    setup_refusals: list[dict[str, JSONValue]] = []
    all_moves: list[Move] = []
    total = 0
    over_cap_op: str | None = None
    for operation in resolved.operations:
        try:
            program = _generate_operation(operation, resolved.setup, spindle)
        except MachiningError as exc:
            programs.append(
                OperationProgram(
                    op_id=operation.entry.id,
                    tool_id=operation.tool.id,
                    feeds=operation.feeds,
                    refusals=(exc.to_json(),),
                )
            )
            continue
        previous_total = total
        total += program.samples
        over = total > CAM_SIM_SAMPLES_MAX
        if over and over_cap_op is None and previous_total <= CAM_SIM_SAMPLES_MAX:
            over_cap_op = operation.entry.id
        programs.append(program)
        all_moves.extend(program.moves)
    if total > CAM_SIM_SAMPLES_MAX:
        setup_refusals.append(
            MachiningError(
                f"setup {resolved.setup.id}: the computed sample total {total} across every "
                f"move exceeds CAM_SIM_SAMPLES_MAX = {CAM_SIM_SAMPLES_MAX}; operation "
                f"{over_cap_op!r} pushed it over (CAM.md §5.3)",
                reason="sample_cap_exceeded",
                data={
                    "setup": resolved.setup.id,
                    "samples_total": total,
                    "cap": CAM_SIM_SAMPLES_MAX,
                    "operation": over_cap_op or "",
                },
            ).to_json()
        )
    return SetupProgram(
        setup_id=resolved.setup.id,
        operations=tuple(programs),
        move_list=MoveList(moves=tuple(all_moves)),
        samples_total=total,
        refusals=tuple(setup_refusals),
    )
