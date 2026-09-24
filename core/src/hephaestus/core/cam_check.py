# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
# pyright: reportMissingTypeStubs=false
# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false
# pyright: reportUnknownVariableType=false, reportUnknownParameterType=false

"""``check_program``: coverage, round-trip, removal simulation, collision (CAM.md §5).

Stage 14C's whole substance, under the honest framing §5 opens with: **none of
these checks verify a toolpath — they verify a model of a toolpath**, so the
gate's weight rests on the cheap, exhaustive, deterministic halves (§5.1
coverage, §5.2 round-trip) with the sampled simulation as corroborating
evidence. Nothing here writes a program anywhere: the round-trip's emitter and
parser are :mod:`hephaestus.core.cam_text`'s in-memory machinery (the dated
14C landing decision), and Gate G14B clause 24's filesystem assertion extends
over every path in this module.

The layout mirrors the lifecycle discipline of :mod:`hephaestus.core.machining`:

* resolution and generation are machining's (this module calls them, it does
  not re-own their refusals);
* **generation-time** caps filed here because their inputs exist here:
  ``collision_sample_cap_exceeded`` over the computed collision-grid total
  (§5.5 — its own cap in its own dimension, never inherited from
  ``CAM_SIM_SAMPLES_MAX``);
* **evaluation-time** verdicts, every universal one in its ``_at_samples``
  spelling (§1.1), with `covered` the one deliberate exception (a finite
  enumerated set needs no sampling caveat);
* the §1.3 severity vocabulary ``crash_risk | part_risk | advisory`` —
  deliberately disjoint from the DFM ``error | warning | info`` set, asserted
  as sets by Gate G14C clause 19.

Collision is measured against the §5.5 **declared scene and nothing else**:
fixture members and ``keepout_*`` volumes. The stock's in-process remaining
material is NOT modelled and not checked, every collision result — the clean
one included — carries the stamp ``in_process_stock_not_modelled``, and the
cheap declared-numbers substitute is the ``holder_below_stock_top_at_samples``
**advisory** (never ``crash_risk``: it is not evidence of contact).

The removal simulation runs under the ``COMPARE.md`` §5 pattern, both legs: a
killable spawned subprocess under :func:`cam_sim_timeout_s`, with the cheap
facts computed FIRST in the parent so a ceiling kill still returns everything
that did not need the kernel. ``fault`` is the gate's injection seam (a slow
boolean; a null boolean), the ``on_between_scans`` test-seam precedent.
"""

from __future__ import annotations

import math
import multiprocessing
import os
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, cast

from hephaestus.core.assembly import AnchorResolver, PartGeometry, UnresolvableAnchorError
from hephaestus.core.cam_text import CamPost, RoundTripReport, parse_program, round_trip
from hephaestus.core.errors import ValidationError
from hephaestus.core.machining import (
    MachiningError,
    ResolvedSetup,
    SetupProgram,
    generate_setup,
    resolve_setup,
)
from hephaestus.core.project_store.cam import (
    CamState,
    FixtureEntry,
    OperationEntry,
    operation_kind_for_tag,
)
from hephaestus.core.project_store.layout import ProjectLayout
from hephaestus.core.project_store.publication import Publisher
from hephaestus.geom.toolpath import Move, MoveList, ToolSolid, tool_solid
from opstore.types import JSONValue

from opstore import OpStore, canonical_json

__all__ = [
    "CAM_COLLISION_SAMPLES_MAX",
    "CAM_COLLISION_SUBSAMPLE",
    "CAM_SEVERITIES",
    "CAM_SIM_TIMEOUT_ENV",
    "CAM_SIM_TIMEOUT_S",
    "CAM_VERDICT_MARGIN",
    "IN_PROCESS_STOCK_STAMP",
    "NOT_CHECKED",
    "PARSER",
    "PROGRAM_VERDICTS",
    "REFERENCE_POST",
    "CamCheckError",
    "CamSimTimeout",
    "CollisionReport",
    "CoverageReport",
    "ProgramStatus",
    "SimulationReport",
    "SnapshotProgramContext",
    "cam_sim_timeout_s",
    "check_program",
    "check_setup",
    "grid_placements",
    "simulation_provenance",
]

#: The §1.3 CAM finding severities — a NEW closed set, disjoint from the DFM
#: pack severities (``registry/_dfm.py:51`` — ``error | warning | info``),
#: because an ``error`` there means "will not manufacture well" and a word
#: borrowed for "this will crash" would quietly degrade both readings.
#: ``crash_risk`` is the only value that blocks emission by rule (§1.4).
CAM_SEVERITIES: Final[tuple[str, ...]] = ("crash_risk", "part_risk", "advisory")

#: The §1.1 closed claim vocabulary, as §5.9 assigns it to checks.
PROGRAM_VERDICTS: Final[tuple[str, ...]] = (
    "covered",
    "uncovered",
    "round_trip_identical",
    "round_trip_diverged",
    "matches_at_samples",
    "gouge_at_samples",
    "rest_at_samples",
    "no_collision_at_samples_in_declared_scene",
    "collision_at_samples",
    "unverifiable",
    "unresolvable",
)

#: Gate fixtures sit at least this factor from every threshold (§4.4/§5.7),
#: so a kernel-build difference cannot flip a clause.
CAM_VERDICT_MARGIN: Final[float] = 10.0

#: Wall-clock ceiling for one setup's removal simulation (§5.7/§5.8), the
#: ``COMPARE_TIMEOUT_S``/``MOTION_TIMEOUT_S`` local-floor pattern.
CAM_SIM_TIMEOUT_S: Final[float] = 300.0
CAM_SIM_TIMEOUT_ENV: Final[str] = "HEPHAESTUS_CAM_SIM_TIMEOUT_S"

#: The collision grid is every n-th simulation sample (§5.5). Overridable
#: **downward only** per setup: an operator may pay for the full grid (1);
#: nothing may declare a coarser one.
CAM_COLLISION_SUBSAMPLE: Final[int] = 8

#: Cap on the computed collision-sample total per setup, checked at
#: generation time (§5.5); the refusal names the total.
CAM_COLLISION_SAMPLES_MAX: Final[int] = 5000

#: The §5.5 stamp every collision result carries, the clean one included:
#: Stage 14 models no in-process stock state, and the omission is a named
#: non-claim rather than silence (§1.6.3).
IN_PROCESS_STOCK_STAMP: Final[str] = "in_process_stock_not_modelled"

#: The §5.5 not-checked manifest: named as not checked, never omitted,
#: because the absence of a finding is not evidence of absence of the fault
#: (§1.6.8).
NOT_CHECKED: Final[tuple[str, ...]] = (
    IN_PROCESS_STOCK_STAMP,
    "spindle_nose",
    "machine_column",
    "machine_table",
    "enclosure",
    "axis_travel_limits",
    "tool_changer",
)

#: THE parser (CAM.md §5.2, §11 item 32): the simulator consumes exactly what
#: the round-trip parsed, and Gate G14C clause 4 asserts this binding is the
#: same OBJECT as :func:`hephaestus.core.cam_text.parse_program` — one
#: implementation, no drift.
PARSER = parse_program

#: The 14C reference post record. A fixture-shaped :class:`CamPost` — the
#: ``posts`` REGISTRY kind, digests and ``simplifications`` stay 14D.
REFERENCE_POST: Final[CamPost] = CamPost(id="ref_linear_ij")


def cam_sim_timeout_s() -> float:
    """The effective ceiling: :data:`CAM_SIM_TIMEOUT_ENV` else the default."""
    raw = os.environ.get(CAM_SIM_TIMEOUT_ENV)
    if raw is None:
        return CAM_SIM_TIMEOUT_S
    try:
        return float(raw)
    except ValueError:
        return CAM_SIM_TIMEOUT_S


class CamCheckError(ValidationError):
    """A 14C check-time refusal; ``reason`` is the stable machine token."""

    def __init__(
        self, message: str, *, reason: str, data: Mapping[str, JSONValue] | None = None
    ) -> None:
        super().__init__(message, kind="contract")
        self.reason = reason
        self.data: dict[str, JSONValue] = dict(data or {})

    def to_json(self) -> dict[str, JSONValue]:
        return {"reason": self.reason, "message": self.message, "data": dict(self.data)}


class CamSimTimeout(ValidationError):
    """The removal simulation hit the ceiling or its subprocess died (§5.8).

    Not empty-handed: carries the per-op progress the child streamed (the
    moves already simulated), names which halves were lost, and rides with
    the cheap facts the parent computed first. Inside a ``CHECKS`` predicate
    this lands as ``unverifiable`` — not a pass and not a crash
    (``COMPARE.md`` §5).
    """

    def __init__(
        self,
        message: str,
        *,
        setup_id: str,
        timeout_s: float,
        moves_simulated: int,
        ops_simulated: tuple[Mapping[str, JSONValue], ...],
        lost: tuple[str, ...],
        cheap: Mapping[str, JSONValue] | None = None,
    ) -> None:
        super().__init__(message, kind="contract")
        self.reason: str = "cam_sim_timeout"
        self.setup_id = setup_id
        self.timeout_s = timeout_s
        self.moves_simulated = moves_simulated
        self.ops_simulated = ops_simulated
        self.lost = lost
        self.cheap: dict[str, JSONValue] | None = None if cheap is None else dict(cheap)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "reason": self.reason,
            "setup": self.setup_id,
            "message": self.message,
            "timeout_s": self.timeout_s,
            "moves_simulated": self.moves_simulated,
            "ops_simulated": [dict(op) for op in self.ops_simulated],
            "lost": list(self.lost),
            "cheap": self.cheap,
        }


def simulation_provenance() -> dict[str, JSONValue]:
    """The (container image, OCCT version) pair the §8 golden sidecar names.

    The simulation result is deliberately NOT claimed bit-reproducible across
    kernel builds (§4.4); a golden binds to this pair exactly as render
    goldens bind to (container image, renderer version).
    """
    import OCP

    return {
        "container_image": os.environ.get("HEPHAESTUS_CI_IMAGE", "unpinned"),
        "occt_version": str(getattr(OCP, "__version__", "unknown")),
    }


# --------------------------------------------------------------------------
# the sample grid (shared by simulation and collision)


def grid_placements(
    moves: MoveList | Sequence[Move], step_mm: float
) -> tuple[tuple[int, tuple[float, float, float]], ...]:
    """The simulation grid: ``(move index, point)`` per sampled tool placement.

    Exactly :func:`hephaestus.geom.toolpath.swept_solid`'s enumeration —
    cutting segments only, ``max(2, ceil(length/step) + 1)`` samples per
    segment — factored out so the collision grid can be a **declared
    subsample of the simulation grid** (§5.5) rather than a second sampling
    with its own drift.
    """
    if step_mm <= 0.0 or not math.isfinite(step_mm):
        raise ValueError(f"step_mm must be a positive length (got {step_mm})")
    items = moves.moves if isinstance(moves, MoveList) else tuple(moves)
    out: list[tuple[int, tuple[float, float, float]]] = []
    previous: Move | None = None
    for index, move in enumerate(items):
        if move.kind not in ("rapid", "linear", "arc_cw", "arc_ccw"):
            continue
        if previous is not None and move.kind != "rapid":
            length = math.hypot(move.x - previous.x, move.y - previous.y, move.z - previous.z)
            count = max(2, math.ceil(length / step_mm) + 1)
            for sample in range(count):
                t = sample / (count - 1)
                out.append(
                    (
                        index,
                        (
                            previous.x + t * (move.x - previous.x),
                            previous.y + t * (move.y - previous.y),
                            previous.z + t * (move.z - previous.z),
                        ),
                    )
                )
        previous = move
    return tuple(out)


# --------------------------------------------------------------------------
# §5.1 coverage — cheap, exhaustive, and the gate's backbone


@dataclass(frozen=True)
class CoverageReport:
    """The §5.1 verdict over declarations: exhaustive, deterministic, no boolean.

    ``covered`` is the one §1.1 verdict with no ``_at_samples`` suffix, on
    purpose: it quantifies over a finite enumerated set. ``uncovered`` names
    every feature with its tag, its descriptor and its reason; ``occlusions``
    carries the §5.1 order-consistency findings
    (``feature_occluded_by_order``), each naming both operations.
    """

    verdict: str
    covered: tuple[Mapping[str, JSONValue], ...] = ()
    uncovered: tuple[Mapping[str, JSONValue], ...] = ()
    occlusions: tuple[Mapping[str, JSONValue], ...] = ()

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "verdict": self.verdict,
            "covered": [dict(item) for item in self.covered],
            "uncovered": [dict(item) for item in self.uncovered],
            "occlusions": [dict(item) for item in self.occlusions],
        }


def _shape_descriptor(shape: Any) -> str:
    """A short declared-fact descriptor of one tagged feature's geometry."""
    try:
        from build123d import Face, GeomType

        if isinstance(shape, Face):
            if shape.geom_type == GeomType.CYLINDER:
                from OCP.BRepAdaptor import BRepAdaptor_Surface  # pyright: ignore[reportAttributeAccessIssue]
                from OCP.TopoDS import TopoDS  # pyright: ignore[reportAttributeAccessIssue]

                adaptor = BRepAdaptor_Surface(TopoDS.Face_s(shape.wrapped))
                return f"cylindrical face diameter {2.0 * float(adaptor.Cylinder().Radius()):g} mm"
            if shape.geom_type == GeomType.PLANE:
                return f"planar face {float(shape.area):g} mm^2"
    except Exception:  # pragma: no cover - descriptor is reporting, not law
        pass
    return type(shape).__name__


def _cylinder_key(shape: Any) -> tuple[float, float, float, float] | None:
    """A comparable identity for one cylindrical face (centre + radius)."""
    from build123d import Face, GeomType

    if not isinstance(shape, Face) or shape.geom_type != GeomType.CYLINDER:
        return None
    centre = shape.center()
    from OCP.BRepAdaptor import BRepAdaptor_Surface  # pyright: ignore[reportAttributeAccessIssue]
    from OCP.TopoDS import TopoDS  # pyright: ignore[reportAttributeAccessIssue]

    adaptor = BRepAdaptor_Surface(TopoDS.Face_s(shape.wrapped))
    return (
        round(float(centre.X), 3),
        round(float(centre.Y), 3),
        round(float(centre.Z), 3),
        round(float(adaptor.Cylinder().Radius()), 3),
    )


def _feature_bbox(shape: Any) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    box = shape.bounding_box()
    return (
        (float(box.min.X), float(box.min.Y), float(box.min.Z)),
        (float(box.max.X), float(box.max.Y), float(box.max.Z)),
    )


def coverage_check(
    resolved: ResolvedSetup,
    operations: Sequence[OperationEntry],
    refused: Mapping[str, Mapping[str, JSONValue]],
    resolver: AnchorResolver,
) -> CoverageReport:
    """§5.1: every CAM-tagged feature covered by exactly one operation, or named.

    A check over **declarations** plus the parts' tag indexes — O(features),
    exhaustive, deterministic, no boolean. Reasons, closed: ``no_operation``
    (a CAM tag no operation claims), ``operation_refused`` (the claiming
    operation was refused, the refusal named), ``untagged_bore`` (a
    cylindrical face carrying no tag at all — the census that keeps "nothing
    references it" from reading as "nothing is there"). Order consistency
    (§5.1 last paragraph): an earlier-ordered operation whose feature is
    enclosed by material a later-ordered operation removes is
    ``feature_occluded_by_order``, naming both operations.
    """
    parts = {resolved.stock.origin_anchor.partition(":")[0]}
    for operation in operations:
        parts.add(operation.feature_parts[0])
    claims: dict[str, list[OperationEntry]] = {}
    for operation in operations:
        claims.setdefault(operation.feature, []).append(operation)

    covered: list[Mapping[str, JSONValue]] = []
    uncovered: list[Mapping[str, JSONValue]] = []
    for part in sorted(parts):
        try:
            geometry, _ = resolver.locate(part, "part")
        except UnresolvableAnchorError:
            continue  # resolution already filed its own named refusal
        claimed_cylinders: set[tuple[float, float, float, float]] = set()
        for tag in sorted(geometry.index.tags):
            try:
                shape = geometry.shape_for(resolver.locate(part, tag)[1])
            except UnresolvableAnchorError:
                continue
            key = _cylinder_key(shape)
            if key is not None:
                claimed_cylinders.add(key)
            prefix, kind = operation_kind_for_tag(tag)
            if prefix is None or kind == "keepout":
                continue  # not a CAM feature (keepouts are scene, §5.5)
            anchor = f"{part}:{tag}"
            claiming = claims.get(anchor, [])
            if not claiming:
                uncovered.append(
                    {
                        "tag": anchor,
                        "descriptor": _shape_descriptor(shape),
                        "reason": "no_operation",
                    }
                )
                continue
            refusals = [refused[op.id] for op in claiming if op.id in refused]
            if refusals:
                uncovered.append(
                    {
                        "tag": anchor,
                        "descriptor": _shape_descriptor(shape),
                        "reason": "operation_refused",
                        "operation": claiming[0].id,
                        "refusal": dict(refusals[0]),
                    }
                )
                continue
            covered.append(
                {
                    "tag": anchor,
                    "descriptor": _shape_descriptor(shape),
                    "operation": claiming[0].id,
                }
            )
        # The untagged census: a bore no tag names cannot be covered and must
        # not vanish (§1.6.8 — anything not declared was not checked).
        for solid in geometry.shape.solids():
            for face_shape in solid.faces():
                key = _cylinder_key(face_shape)
                if key is None or key in claimed_cylinders:
                    continue
                claimed_cylinders.add(key)  # report each bore once
                uncovered.append(
                    {
                        "tag": None,
                        "part": part,
                        "descriptor": _shape_descriptor(face_shape),
                        "reason": "untagged_bore",
                    }
                )

    occlusions = _occlusion_findings(resolved)
    verdict = "covered" if not uncovered else "uncovered"
    return CoverageReport(
        verdict=verdict,
        covered=tuple(covered),
        uncovered=tuple(uncovered),
        occlusions=occlusions,
    )


def _occlusion_findings(resolved: ResolvedSetup) -> tuple[Mapping[str, JSONValue], ...]:
    """§5.1 order consistency over the setup's resolved operations.

    For an earlier-declared operation A and a later-declared B: A is occluded
    when A's feature sits inside B's footprint and at (or below) B's declared
    floor — reaching A's feature first means cutting through material B is
    declared to remove later. Decided from resolved feature bounding boxes
    and declared order only; no boolean.
    """
    eps = 1e-6
    findings: list[Mapping[str, JSONValue]] = []
    ops = resolved.operations
    for a_index, earlier in enumerate(ops):
        a_min, a_max = _feature_bbox(earlier.feature_shape)
        for later in ops[a_index + 1 :]:
            if later.entry.kind not in ("pocket", "face"):
                continue
            b_min, b_max = _feature_bbox(later.feature_shape)
            inside_xy = (
                a_min[0] >= b_min[0] - eps
                and a_max[0] <= b_max[0] + eps
                and a_min[1] >= b_min[1] - eps
                and a_max[1] <= b_max[1] + eps
            )
            if inside_xy and a_max[2] <= b_max[2] + eps:
                findings.append(
                    {
                        "reason": "feature_occluded_by_order",
                        "operation": earlier.entry.id,
                        "occluded_by": later.entry.id,
                        "feature": earlier.entry.feature,
                        "occluding_feature": later.entry.feature,
                    }
                )
    return tuple(findings)


# --------------------------------------------------------------------------
# §5.5 collision — against the declared scene and nothing else


@dataclass(frozen=True)
class SceneBody:
    """One declared scene body: a fixture member or a keep-out volume."""

    name: str
    shape: Any


@dataclass(frozen=True)
class CollisionReport:
    """The §5.5 result: verdict, counted booleans, stamp, findings.

    ``state`` is ``"checked"`` or ``"unresolvable"`` (``undeclared_scene`` —
    never a clean pass: "an unchecked constraint is not a passing one"). The
    stamp rides EVERY report, unresolvable ones included.
    """

    state: str
    verdict: str | None
    samples_evaluated: int
    subsample: int
    booleans_evaluated: int
    checked_bodies: tuple[str, ...]
    scene: tuple[str, ...]
    not_checked: tuple[str, ...] = NOT_CHECKED
    events: tuple[Mapping[str, JSONValue], ...] = ()
    findings: tuple[Mapping[str, JSONValue], ...] = ()
    reason: str | None = None
    detail: str | None = None

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "state": self.state,
            "verdict": self.verdict,
            "samples_evaluated": self.samples_evaluated,
            "subsample": self.subsample,
            "booleans_evaluated": self.booleans_evaluated,
            "checked_bodies": list(self.checked_bodies),
            "scene": list(self.scene),
            IN_PROCESS_STOCK_STAMP: True,
            "not_checked": list(self.not_checked),
            "events": [dict(event) for event in self.events],
            "findings": [dict(finding) for finding in self.findings],
            "reason": self.reason,
            "detail": self.detail,
        }


_AXIS_ROTATIONS: Final[Mapping[str, tuple[float, float, float]]] = {
    "+Z": (0.0, 0.0, 0.0),
    "-Z": (180.0, 0.0, 0.0),
    "+X": (0.0, 90.0, 0.0),
    "-X": (0.0, -90.0, 0.0),
    "+Y": (-90.0, 0.0, 0.0),
    "-Y": (90.0, 0.0, 0.0),
}


def resolve_scene(
    resolved: ResolvedSetup,
    fixture: FixtureEntry,
    resolver: AnchorResolver,
) -> tuple[SceneBody, ...]:
    """The §5.5 declared scene, exhaustively: fixture members + keepouts.

    That is the whole list. The undisturbed stock envelope is deliberately
    NOT a scene body (§5.5 records why at length), and the in-process
    remaining material is machinery this stage does not have — the stamp says
    so on every result.
    """
    from build123d import Pos

    bodies: list[SceneBody] = []
    for member in fixture.members:
        part, _, selector = member.anchor.partition(":")
        try:
            geometry, resolution = resolver.locate(part, selector or "part")
            shape = geometry.shape_for(resolution)
        except UnresolvableAnchorError as exc:
            raise CamCheckError(
                f"fixture {fixture.id}: member anchor {member.anchor!r} is unresolvable "
                f"({exc.reason}): {exc.detail}",
                reason="undeclared_scene",
                data={"fixture": fixture.id, "anchor": member.anchor},
            ) from exc
        placed = Pos(*member.offset_mm) * shape
        bodies.append(SceneBody(name=f"fixture:{fixture.id}:{member.part}", shape=placed))
    seen_parts = {resolved.stock.origin_anchor.partition(":")[0]}
    for operation in resolved.operations:
        seen_parts.add(operation.entry.feature_parts[0])
    for part in sorted(seen_parts):
        try:
            geometry, _ = resolver.locate(part, "part")
        except UnresolvableAnchorError:
            continue
        for tag in sorted(geometry.index.tags):
            prefix, kind = operation_kind_for_tag(tag)
            if kind != "keepout":
                continue
            try:
                shape = geometry.shape_for(resolver.locate(part, tag)[1])
            except UnresolvableAnchorError:
                continue
            bodies.append(SceneBody(name=f"keepout:{part}:{tag}", shape=shape))
    return tuple(bodies)


def _placed_body(body: Any, rotation: tuple[float, float, float], point: tuple[float, float, float]) -> Any:
    from build123d import Pos, Rotation

    oriented = body if rotation == (0.0, 0.0, 0.0) else Rotation(*rotation) * body
    return Pos(*point) * oriented


def collision_check(
    resolved: ResolvedSetup,
    program: SetupProgram,
    scene: tuple[SceneBody, ...],
    *,
    subsample: int,
) -> CollisionReport:
    """§5.5: tool shank + holder against the declared scene, at counted samples.

    The boolean count is exactly ``collision_samples_evaluated x |checked
    bodies| x |scene bodies|`` — no early exit, no pruning — so Gate G14C
    clause 12 can bind the §5.8 budget to a counted curve rather than one
    fixture. ``undeclared_scene`` (an empty scene, or a tool record without a
    holder) is an ``unresolvable`` state, never a clean pass.
    """
    from hephaestus.geom.measure import interference

    ops_by_id = {op.entry.id: op for op in resolved.operations}
    checked_names: list[str] = []
    if not scene:
        return CollisionReport(
            state="unresolvable",
            verdict=None,
            samples_evaluated=0,
            subsample=subsample,
            booleans_evaluated=0,
            checked_bodies=(),
            scene=(),
            reason="undeclared_scene",
            detail=(
                "the declared scene is empty (no fixture member, no keepout volume); an "
                "unchecked scene is not a clear one (CAM.md §5.5, VALIDATION.md §5)"
            ),
        )

    # Collect this setup's collision grid: the declared subsample of the
    # simulation grid, in program order, each sample bound to its operation's
    # own tool bodies.
    grid: list[tuple[str, int, tuple[float, float, float]]] = []
    solids: dict[str, ToolSolid] = {}
    for op_program in program.operations:
        if not op_program.moves:
            continue
        operation = ops_by_id.get(op_program.op_id)
        if operation is None:  # pragma: no cover - programs come from resolution
            continue
        tool = operation.tool
        holder = getattr(tool, "holder", None)
        if holder is None:
            return CollisionReport(
                state="unresolvable",
                verdict=None,
                samples_evaluated=0,
                subsample=subsample,
                booleans_evaluated=0,
                checked_bodies=(),
                scene=tuple(body.name for body in scene),
                reason="undeclared_scene",
                detail=(
                    f"tool {tool.id!r} declares no holder envelope, so there is no "
                    "collision claim to make at all (CAM.md §3.5/§5.5)"
                ),
            )
        if operation.entry.id not in solids:
            solids[operation.entry.id] = tool_solid(
                diameter_mm=tool.diameter_mm,
                flute_length_mm=tool.flute_length_mm,
                shank_diameter_mm=tool.shank_diameter_mm,
                stickout_mm=tool.stickout_mm,
                holder_diameter_mm=holder.diameter_mm,
                holder_length_mm=holder.length_mm,
            )
        for move_index, point in grid_placements(op_program.moves, operation.step_mm):
            grid.append((operation.entry.id, move_index, point))
    collision_grid = grid[::subsample]

    rotation = _AXIS_ROTATIONS[resolved.setup.spindle_axis]
    stock_top = resolved.stock_max_mm[2]
    booleans = 0
    events: list[Mapping[str, JSONValue]] = []
    findings: list[Mapping[str, JSONValue]] = []
    holder_worst: tuple[int, float] | None = None
    for sample_index, (op_id, move_index, point) in enumerate(collision_grid):
        solid = solids[op_id]
        bodies: list[tuple[str, Any]] = []
        if solid.shank is not None:
            bodies.append(("shank", solid.shank))
        bodies.append(("holder", solid.holder))
        checked_names = [name for name, _ in bodies]
        for body_name, body in bodies:
            placed = _placed_body(body, rotation, point)
            for scene_body in scene:
                overlap = float(interference(placed, scene_body.shape))
                booleans += 1
                if overlap > 0.0:
                    events.append(
                        {
                            "move": move_index,
                            "sample": sample_index,
                            "operation": op_id,
                            "body": body_name,
                            "scene_body": scene_body.name,
                            "overlap_mm3": overlap,
                        }
                    )
        # The cheap declared-numbers advisory (§5.5): the holder envelope's
        # lowest point below the declared stock top. No boolean; +Z only,
        # because "below the stock top plane" has a meaning only along it.
        if resolved.setup.spindle_axis == "+Z":
            holder_low = point[2] + solid.holder_extent_mm[0]
            depth = stock_top - holder_low
            if depth > 0.0 and (holder_worst is None or depth > holder_worst[1]):
                holder_worst = (sample_index, depth)

    for event in events:
        findings.append(
            {
                "id": f"collision:{event['operation']}:{event['sample']}",
                "severity": "crash_risk",
                "reason": "collision_at_samples",
                **dict(event),
            }
        )
    if holder_worst is not None:
        findings.append(
            {
                "id": f"holder_below_stock_top:{resolved.setup.id}",
                "severity": "advisory",
                "reason": "holder_below_stock_top_at_samples",
                "sample": holder_worst[0],
                "depth_mm": holder_worst[1],
            }
        )
    verdict = (
        "collision_at_samples" if events else "no_collision_at_samples_in_declared_scene"
    )
    return CollisionReport(
        state="checked",
        verdict=verdict,
        samples_evaluated=len(collision_grid),
        subsample=subsample,
        booleans_evaluated=booleans,
        checked_bodies=tuple(dict.fromkeys(checked_names)),
        scene=tuple(body.name for body in scene),
        events=tuple(events),
        findings=tuple(findings),
    )


# --------------------------------------------------------------------------
# §5.3 removal simulation — bounded, sampled, directed halves


@dataclass(frozen=True)
class SimulationReport:
    """The §5.3 record: directed halves, deviation, samples, step, floor.

    ``iou`` is REPORTED and is not a legal threshold (§5.3, ``COMPARE.md``
    §1): the verdicts key on the directed halves — ``b_only_mm3`` (gouge)
    and ``a_only_mm3`` (rest) — against the setup's declared budgets.
    """

    verdict: str
    a_only_mm3: float
    b_only_mm3: float
    common_mm3: float
    iou: float
    max_deviation_mm: float
    samples_evaluated: int
    per_op: tuple[Mapping[str, JSONValue], ...]
    floor_mm3: float
    floor_inputs: Mapping[str, JSONValue]
    budgets: Mapping[str, float]
    findings: tuple[Mapping[str, JSONValue], ...] = ()

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "verdict": self.verdict,
            "a_only_mm3": self.a_only_mm3,
            "b_only_mm3": self.b_only_mm3,
            "common_mm3": self.common_mm3,
            "iou": self.iou,
            "max_deviation_mm": self.max_deviation_mm,
            "samples_evaluated": self.samples_evaluated,
            "per_op": [dict(item) for item in self.per_op],
            "min_resolvable_mm3": self.floor_mm3,
            "min_resolvable_inputs": dict(self.floor_inputs),
            "budgets": {name: self.budgets[name] for name in sorted(self.budgets)},
            "findings": [dict(finding) for finding in self.findings],
        }


def _removal_boolean(stock: Any, swept: Any, fault: Mapping[str, JSONValue]) -> Any:
    """The one removal boolean, seamed for the gate's fault injection.

    ``fault`` comes from the check invocation (a gate-only parameter, the
    ``on_between_scans`` precedent): ``slow_boolean_s`` sleeps here — where
    the §5.8 ceiling must catch it — and ``null_boolean`` returns ``None``,
    which the child files as ``removal_boolean_failed`` rather than reporting
    a partial solid (Gate G14C clause 14).
    """
    delay = fault.get("slow_boolean_s")
    if isinstance(delay, int | float) and delay > 0:
        time.sleep(float(delay))
    if fault.get("null_boolean"):
        return None
    return stock - swept


def _balanced_fuse(shapes: list[Any]) -> Any:
    """Pairwise-tree fuse: the same union as a linear fold, in O(log n) depth."""
    layer = shapes
    while len(layer) > 1:
        merged: list[Any] = []
        for index in range(0, len(layer) - 1, 2):
            merged.append(layer[index] + layer[index + 1])
        if len(layer) % 2:
            merged.append(layer[-1])
        layer = merged
    return layer[0]


def _sim_child(conn: Any, spec: Mapping[str, Any]) -> None:  # pragma: no cover
    """One setup's removal simulation, where a kill cannot take the session down.

    Runs in a spawned subprocess (the ``COMPARE.md`` §5 pattern, the
    ``_diff_child``/``_sweep_child`` shape). Message protocol, in order: one
    ``("op", {...})`` per operation AS ITS SWEEP COMPLETES — a ceiling kill
    after the n-th send still leaves the caller holding n operations'
    progress (the moves already simulated) — then exactly one of
    ``("full", record)`` or ``("refusal", (reason, detail))``.
    """
    from build123d import Align, Box, Cylinder, Pos
    from hephaestus.core.executor.artifact_geometry import load_brep_shape
    from hephaestus.geom.compare import solid_diff

    fault_early: Mapping[str, JSONValue] = spec.get("fault") or {}
    pid_file = fault_early.get("pid_file")
    if isinstance(pid_file, str) and pid_file:
        # Gate seam (clause G14C-13): the parent's kill must leave a DEAD
        # subprocess, and the gate proves it by pid rather than by trust.
        Path(pid_file).write_text(str(os.getpid()), encoding="utf-8")
    target = load_brep_shape(Path(str(spec["target_brep"])).read_bytes())
    stock_min: Sequence[float] = spec["stock_min"]
    stock_max: Sequence[float] = spec["stock_max"]
    extents = [stock_max[axis] - stock_min[axis] for axis in range(3)]
    stock = Pos(*stock_min) * Box(*extents, align=(Align.MIN, Align.MIN, Align.MIN))
    fault: Mapping[str, JSONValue] = spec.get("fault") or {}

    swept_parts: list[Any] = []
    samples_total = 0
    for op_spec in cast("Sequence[Mapping[str, Any]]", spec["ops"]):
        cutter = Cylinder(
            float(op_spec["cutter_diameter_mm"]) / 2.0,
            float(op_spec["cutter_flute_length_mm"]),
            align=(Align.CENTER, Align.CENTER, Align.MIN),
        )
        moves = tuple(
            Move(
                kind=item["kind"],
                x=float(item.get("x", 0.0)),
                y=float(item.get("y", 0.0)),
                z=float(item.get("z", 0.0)),
            )
            for item in cast("Sequence[Mapping[str, Any]]", op_spec["moves"])
        )
        placements = grid_placements(moves, float(op_spec["step_mm"]))
        placed = [Pos(*point) * cutter for _, point in placements]
        if placed:
            swept_parts.append(_balanced_fuse(placed))
        samples_total += len(placements)
        conn.send(
            (
                "op",
                {
                    "op": str(op_spec["op"]),
                    "samples": len(placements),
                    "moves": len(moves),
                },
            )
        )
    if not swept_parts:
        conn.send(("refusal", ("removal_boolean_failed", "no cutting moves to simulate")))
        conn.close()
        return
    swept = _balanced_fuse(swept_parts)
    removed = _removal_boolean(stock, swept, fault)
    volume = 0.0
    if removed is not None:
        try:
            volume = float(removed.volume)
        except Exception:
            volume = 0.0
    if removed is None or volume <= 0.0:
        conn.send(
            (
                "refusal",
                (
                    "removal_boolean_failed",
                    "the stock-minus-swept boolean produced no solid; a partial solid is "
                    "never reported as a result (CAM.md §5.3, Gate G14C clause 14)",
                ),
            )
        )
        conn.close()
        return
    diff = solid_diff(removed, target, align="as_posed")
    conn.send(
        (
            "full",
            {
                "a_only_mm3": diff.volume.a_only_mm3,
                "b_only_mm3": diff.volume.b_only_mm3,
                "common_mm3": diff.volume.common_mm3,
                "iou": diff.volume.iou,
                "max_deviation_mm": diff.surface.max_deviation_mm,
                "samples_evaluated": samples_total,
            },
        )
    )
    conn.close()


def _bounded_sim(
    spec: dict[str, Any],
    *,
    setup_id: str,
    timeout_s: float,
    cheap: Mapping[str, JSONValue] | None,
) -> tuple[dict[str, JSONValue] | None, tuple[str, str] | None, tuple[Mapping[str, JSONValue], ...]]:
    """Run the removal simulation under the wall-clock ceiling (§5.8).

    Returns ``(record, refusal, per_op progress)``. A ceiling kill or child
    death raises :class:`CamSimTimeout` carrying the per-op progress that
    streamed in, the names of the lost halves, and the cheap facts the
    parent already holds.
    """
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=_sim_child, args=(child, spec))
    proc.start()
    child.close()

    ops: list[Mapping[str, JSONValue]] = []
    outcome: tuple[str, Any] | None = None
    died = False
    cut_short = f"did not finish within {timeout_s:g}s and was killed"
    deadline = time.monotonic() + timeout_s

    def _receive() -> bool:
        nonlocal outcome
        kind, payload = parent.recv()
        if kind == "op":
            ops.append(cast("Mapping[str, JSONValue]", payload))
            return False
        outcome = (str(kind), payload)
        return True

    try:
        while outcome is None and time.monotonic() < deadline:
            try:
                if parent.poll(0.05):
                    _receive()
                elif not proc.is_alive():
                    while parent.poll(0.2) and not _receive():
                        pass
                    died = outcome is None
                    break
            except EOFError:
                proc.join(5.0)
                died = True
                break
    finally:
        if proc.is_alive():
            proc.kill()
        proc.join()
        parent.close()
    if died:
        cut_short = f"subprocess died (exit code {proc.exitcode})"

    if outcome is not None:
        kind, payload = outcome
        if kind == "full":
            return cast("dict[str, JSONValue]", payload), None, tuple(ops)
        reason, detail = cast("tuple[str, str]", payload)
        return None, (reason, detail), tuple(ops)
    moves_simulated = sum(int(cast("int", op.get("moves", 0))) for op in ops)
    raise CamSimTimeout(
        f"setup {setup_id}: removal simulation {cut_short} (CAM.md §5.8, ceiling "
        f"{timeout_s:g}s via {CAM_SIM_TIMEOUT_ENV}); lost: removal_boolean, "
        "surface_sampling",
        setup_id=setup_id,
        timeout_s=timeout_s,
        moves_simulated=moves_simulated,
        ops_simulated=tuple(ops),
        lost=("removal_boolean", "surface_sampling"),
        cheap=cheap,
    )


# --------------------------------------------------------------------------
# the per-setup record (§5.9)


@dataclass(frozen=True)
class ProgramStatus:
    """The §5.9 per-setup result record ``check_program`` returns.

    ``state`` follows the ``MotionStatus`` rule (``KINEMATICS.md`` §2): an
    unresolvable setup makes every check on it unresolvable — named, never
    skipped, never conflated with a failing check. No field anywhere in this
    record carries program text.
    """

    setup_id: str
    state: str
    source_artifact_ref: str | None = None
    records: Mapping[str, JSONValue] = field(default_factory=dict[str, "JSONValue"])
    operations: tuple[Mapping[str, JSONValue], ...] = ()
    coverage: CoverageReport | None = None
    round_trip: RoundTripReport | None = None
    simulation: SimulationReport | None = None
    collision: CollisionReport | None = None
    refusals: tuple[Mapping[str, JSONValue], ...] = ()
    findings: tuple[Mapping[str, JSONValue], ...] = ()
    reason: str | None = None
    detail: str | None = None

    def blocking(self) -> tuple[str, ...]:
        """Ids that block by rule: crash_risk findings + the unresolvable state."""
        out = [
            str(finding.get("id"))
            for finding in self.findings
            if finding.get("severity") == "crash_risk"
        ]
        if self.state == "unresolvable":
            out.append(self.setup_id)
        return tuple(out)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "setup": self.setup_id,
            "state": self.state,
            "source_artifact_ref": self.source_artifact_ref,
            "records": dict(self.records),
            "operations": [dict(op) for op in self.operations],
            "coverage": None if self.coverage is None else self.coverage.to_json(),
            "round_trip": None if self.round_trip is None else self.round_trip.to_json(),
            "simulation": None if self.simulation is None else self.simulation.to_json(),
            "collision": None if self.collision is None else self.collision.to_json(),
            "refusals": [dict(refusal) for refusal in self.refusals],
            "findings": [dict(finding) for finding in self.findings],
            "reason": self.reason,
            "detail": self.detail,
        }


def _feed_facts(resolved: ResolvedSetup, program: SetupProgram) -> list[dict[str, JSONValue]]:
    """Per-operation cheap facts: feeds with sources, ladder facts, samples."""
    facts: list[dict[str, JSONValue]] = []
    by_id = {op.entry.id: op for op in resolved.operations}
    for op_program in program.operations:
        entry = by_id.get(op_program.op_id)
        fact: dict[str, JSONValue] = {
            "op": op_program.op_id,
            "tool": op_program.tool_id,
            "moves": len(op_program.moves),
            "loops_emitted": op_program.loops_emitted,
            "refusals": [dict(refusal) for refusal in op_program.refusals],
        }
        if op_program.feeds is not None:
            fact["feeds"] = op_program.feeds.to_json()
        if entry is not None:
            fact["step_mm"] = entry.step_mm
            fact["floor_mm3"] = entry.floor_mm3
        facts.append(fact)
    return facts


def _simulation_report(
    resolved: ResolvedSetup,
    record: Mapping[str, JSONValue],
    per_op: tuple[Mapping[str, JSONValue], ...],
) -> SimulationReport:
    """Assemble the §5.3 record and decide the verdict from the directed halves."""
    budgets = {name: float(resolved.setup.tolerance[name]) for name in resolved.setup.tolerance}
    a_only = float(cast("float", record["a_only_mm3"]))
    b_only = float(cast("float", record["b_only_mm3"]))
    binding = None
    for operation in resolved.operations:
        if operation.entry.id == resolved.binding_floor_operation:
            binding = operation
    if binding is None and resolved.operations:
        binding = resolved.operations[0]
    floor_inputs: dict[str, JSONValue] = {}
    if binding is not None:
        floor_inputs = {
            "operation": binding.entry.id,
            "step_mm": binding.step_mm,
            "r_mm": binding.tool.diameter_mm / 2.0,
            "doc_mm": binding.feeds.doc_mm,
        }
    findings: list[Mapping[str, JSONValue]] = []
    verdict = "matches_at_samples"
    if b_only > budgets.get("gouge_budget_mm3", math.inf):
        verdict = "gouge_at_samples"
        findings.append(
            {
                "id": f"gouge:{resolved.setup.id}",
                "severity": "part_risk",
                "reason": "gouge_at_samples",
                "b_only_mm3": b_only,
                "budget_mm3": budgets["gouge_budget_mm3"],
            }
        )
    elif a_only > budgets.get("rest_budget_mm3", math.inf):
        verdict = "rest_at_samples"
        findings.append(
            {
                "id": f"rest:{resolved.setup.id}",
                "severity": "part_risk",
                "reason": "rest_at_samples",
                "a_only_mm3": a_only,
                "budget_mm3": budgets["rest_budget_mm3"],
            }
        )
    return SimulationReport(
        verdict=verdict,
        a_only_mm3=a_only,
        b_only_mm3=b_only,
        common_mm3=float(cast("float", record["common_mm3"])),
        iou=float(cast("float", record["iou"])),
        max_deviation_mm=float(cast("float", record["max_deviation_mm"])),
        samples_evaluated=int(cast("int", record["samples_evaluated"])),
        per_op=per_op,
        floor_mm3=resolved.floor_mm3,
        floor_inputs=floor_inputs,
        budgets=budgets,
        findings=tuple(findings),
    )


def check_setup(
    layout: ProjectLayout,
    store: OpStore,
    setup_id: str,
    *,
    tools: Any,
    materials: Any | None = None,
    post: CamPost = REFERENCE_POST,
    collision_subsample: int | None = None,
    timeout_s: float | None = None,
    scratch: Path | None = None,
    resolver: AnchorResolver | None = None,
    fault: Mapping[str, JSONValue] | None = None,
    simulate: bool = True,
    raise_timeout: bool = False,
) -> ProgramStatus:
    """One setup's §5.9 record: resolve, generate, then check every half.

    Order is the §5.8 discipline: the cheap, exhaustive halves (coverage,
    round-trip, feed sources, ladder facts) are computed FIRST, so a
    simulation ceiling kill still returns everything that did not need the
    kernel — the :class:`CamSimTimeout` refusal is filed in the record with
    the cheap facts present, never raised past this function.

    ``collision_subsample`` may only refine the grid downward (§5.5); a
    coarser override is refused ``invalid_collision_subsample`` and an
    override to ``1`` is accepted. ``fault`` is the gate's injection seam.
    """
    from hephaestus.core.executor.artifact_geometry import write_brep_shape

    scratch_dir = scratch or Path(tempfile.mkdtemp(prefix="heph-cam-check-"))
    if resolver is None:
        resolver = AnchorResolver(layout, store, Publisher(layout, store), scratch_dir)
    subsample = CAM_COLLISION_SUBSAMPLE if collision_subsample is None else collision_subsample
    if collision_subsample is not None:
        if not isinstance(collision_subsample, int) or collision_subsample < 1:
            raise CamCheckError(
                f"setup {setup_id}: collision subsample must be a positive integer "
                f"(got {collision_subsample!r})",
                reason="invalid_collision_subsample",
                data={"setup": setup_id},
            )
        if collision_subsample > CAM_COLLISION_SUBSAMPLE:
            raise CamCheckError(
                f"setup {setup_id}: collision subsample {collision_subsample} is coarser "
                f"than CAM_COLLISION_SUBSAMPLE = {CAM_COLLISION_SUBSAMPLE}; the override is "
                "downward only — an operator may pay for a finer grid, nothing may declare "
                "a coarser one (CAM.md §5.5)",
                reason="invalid_collision_subsample",
                data={
                    "setup": setup_id,
                    "subsample": collision_subsample,
                    "max": CAM_COLLISION_SUBSAMPLE,
                },
            )

    cam = CamState(layout, store)
    try:
        resolved = resolve_setup(
            layout,
            store,
            setup_id,
            tools=tools,
            materials=materials,
            scratch=scratch_dir,
            resolver=resolver,
        )
    except MachiningError as exc:
        return ProgramStatus(
            setup_id=setup_id,
            state="unresolvable",
            refusals=(exc.to_json(),),
            reason=exc.reason,
            detail=exc.message,
        )

    program = generate_setup(resolved)
    refusals: list[Mapping[str, JSONValue]] = [dict(r) for r in program.refusals]
    refused_ops: dict[str, Mapping[str, JSONValue]] = {}
    for op_program in program.operations:
        for refusal in op_program.refusals:
            refused_ops[op_program.op_id] = dict(refusal)
            refusals.append(dict(refusal))

    # Generation-time collision cap: the collision grid's own total in its own
    # dimension (§5.5) — checked here, before any boolean runs.
    grid_total = 0
    for op_program in program.operations:
        if not op_program.moves:
            continue
        operation = next(op for op in resolved.operations if op.entry.id == op_program.op_id)
        grid_total += len(grid_placements(op_program.moves, operation.step_mm))
    collision_total = len(range(0, grid_total, subsample))
    collision_capped = collision_total > CAM_COLLISION_SAMPLES_MAX
    if collision_capped:
        refusals.append(
            CamCheckError(
                f"setup {setup_id}: the computed collision-sample total {collision_total} "
                f"exceeds CAM_COLLISION_SAMPLES_MAX = {CAM_COLLISION_SAMPLES_MAX} at "
                f"subsample {subsample} (CAM.md §5.5) — refused at generation time, "
                "before any boolean runs",
                reason="collision_sample_cap_exceeded",
                data={
                    "setup": setup_id,
                    "collision_samples": collision_total,
                    "cap": CAM_COLLISION_SAMPLES_MAX,
                    "subsample": subsample,
                },
            ).to_json()
        )

    # -- the cheap, exhaustive halves FIRST (§5.8) --------------------------
    active_ops = tuple(
        cast("OperationEntry", entry.entry) for entry in resolved.operations
    )
    coverage = coverage_check(resolved, active_ops, refused_ops, resolver)
    trip = round_trip(program.move_list, post) if program.move_list.moves else None
    op_facts = _feed_facts(resolved, program)
    findings: list[Mapping[str, JSONValue]] = []
    for occlusion in coverage.occlusions:
        findings.append(
            {
                "id": f"occlusion:{occlusion['operation']}",
                "severity": "part_risk",
                **dict(occlusion),
            }
        )

    tools_records: list[JSONValue] = []
    for operation in resolved.operations:
        tools_records.append(
            {
                "id": operation.tool.id,
                "registry": getattr(operation.tool, "registry", ""),
                "registry_digest": getattr(operation.tool, "digest", ""),
            }
        )
    records: dict[str, JSONValue] = {
        "stock": resolved.stock.to_json(),
        "wcs": resolved.wcs.to_json(),
        "fixture": cam.fixtures.get(resolved.setup.fixture).to_json(),
        "tools": tools_records,
        "post": post.to_json(),
        "generations": {
            ledger.KIND_LABEL: ledger.state().generation for ledger in cam.ledgers()
        },
    }
    cheap: dict[str, JSONValue] = {
        "coverage": coverage.verdict,
        "round_trip": None if trip is None else trip.verdict,
        "moves": len(program.move_list),
        "feed_sources": [
            {"op": fact["op"], "sources": cast("Mapping[str, JSONValue]", fact["feeds"]).get("sources")}
            for fact in op_facts
            if "feeds" in fact
        ],
    }

    # -- collision (declared scene only, §5.5) ------------------------------
    collision: CollisionReport | None = None
    if not collision_capped:
        fixture = cast("FixtureEntry", cam.fixtures.get(resolved.setup.fixture))
        try:
            scene = resolve_scene(resolved, fixture, resolver)
        except CamCheckError as exc:
            refusals.append(exc.to_json())
            scene = ()
        collision = collision_check(resolved, program, scene, subsample=subsample)
        findings.extend(collision.findings)
        if collision.state == "unresolvable":
            refusals.append(
                {
                    "reason": collision.reason,
                    "message": collision.detail,
                    "data": {"setup": setup_id},
                }
            )

    # -- the removal simulation, bounded (§5.3/§5.8) ------------------------
    simulation: SimulationReport | None = None
    if simulate and program.move_list.moves and not any(
        r.get("reason") == "sample_cap_exceeded" for r in refusals
    ):
        target_part = resolved.stock.origin_anchor.partition(":")[0]
        try:
            geometry, _ = resolver.locate(target_part, "part")
            target_path = scratch_dir / f"cam-target-{setup_id}.brep"
            write_brep_shape(geometry.shape, target_path)
            ceiling = timeout_s if timeout_s is not None else cam_sim_timeout_s()
            spec: dict[str, Any] = {
                "target_brep": str(target_path),
                "stock_min": list(resolved.stock_min_mm),
                "stock_max": list(resolved.stock_max_mm),
                "fault": dict(fault or {}),
                "ops": [
                    {
                        "op": op_program.op_id,
                        "step_mm": next(
                            op.step_mm
                            for op in resolved.operations
                            if op.entry.id == op_program.op_id
                        ),
                        "cutter_diameter_mm": next(
                            op.tool.diameter_mm
                            for op in resolved.operations
                            if op.entry.id == op_program.op_id
                        ),
                        "cutter_flute_length_mm": next(
                            op.tool.flute_length_mm
                            for op in resolved.operations
                            if op.entry.id == op_program.op_id
                        ),
                        # Untruncated coordinates on purpose: ``Move.to_json``
                        # rounds to COORD_DECIMALS, and a swept surface
                        # displaced ~1e-6 from the design face it should
                        # coincide with turns an exact-coincidence boolean
                        # into a sliver case the kernel can refuse.
                        "moves": [
                            {"kind": move.kind, "x": move.x, "y": move.y, "z": move.z}
                            for move in op_program.moves
                        ],
                    }
                    for op_program in program.operations
                    if op_program.moves
                ],
            }
            record, sim_refusal, per_op = _bounded_sim(
                spec, setup_id=setup_id, timeout_s=ceiling, cheap=cheap
            )
            if sim_refusal is not None:
                reason, detail = sim_refusal
                refusals.append({"reason": reason, "message": detail, "data": {"setup": setup_id}})
            elif record is not None:
                simulation = _simulation_report(resolved, record, per_op)
                findings.extend(simulation.findings)
        except CamSimTimeout as exc:
            # Inside a CHECKS predicate the timeout must reach the checks
            # engine, which records the check as unverifiable (§5.8); on the
            # tool/CLI path it is FILED, cheap facts riding it, so one killed
            # simulation never empties the rest of the record.
            if raise_timeout:
                raise
            refusals.append(exc.to_json())
        except UnresolvableAnchorError as exc:  # pragma: no cover - resolution passed above
            refusals.append({"reason": exc.reason, "message": exc.detail, "data": {}})

    source_ref = resolved.operations[0].artifact_ref if resolved.operations else None
    return ProgramStatus(
        setup_id=setup_id,
        state="checked",
        source_artifact_ref=source_ref,
        records=records,
        operations=tuple(op_facts),
        coverage=coverage,
        round_trip=trip,
        simulation=simulation,
        collision=collision,
        refusals=tuple(refusals),
        findings=tuple(findings),
    )


def check_program(
    layout: ProjectLayout,
    store: OpStore,
    setup_ids: Sequence[str] | None = None,
    *,
    tools: Any,
    materials: Any | None = None,
    post: CamPost = REFERENCE_POST,
    collision_subsample: int | None = None,
    timeout_s: float | None = None,
    scratch: Path | None = None,
    record: bool = True,
    fault: Mapping[str, JSONValue] | None = None,
) -> tuple[tuple[ProgramStatus, ...], bool]:
    """``check_program(setup_ids?)``: every active setup's §5.9 record.

    A full run (``setup_ids is None``) is recorded onto the program-status
    projection so a later read — and the reviewer — sees it; a named subset
    is evaluated but deliberately not projected (``partial``, the
    ``check_assembly``/``check_motion`` rule). Returns ``(statuses,
    partial)``.
    """
    from hephaestus.core.errors import AddressingError

    cam = CamState(layout, store)
    active = [
        entry.id for entry in cam.setups.state().active
    ]
    partial = setup_ids is not None
    targets: Sequence[str]
    if setup_ids is None:
        targets = active
    else:
        unknown = sorted(set(setup_ids) - set(active))
        if unknown:
            raise AddressingError(
                f"no setup {unknown[0]!r} is declared",
                selector=unknown[0],
                candidates=tuple(active),
            )
        targets = list(setup_ids)

    scratch_dir = scratch or Path(tempfile.mkdtemp(prefix="heph-cam-check-"))
    resolver = AnchorResolver(layout, store, Publisher(layout, store), scratch_dir)
    statuses = tuple(
        check_setup(
            layout,
            store,
            setup_id,
            tools=tools,
            materials=materials,
            post=post,
            collision_subsample=collision_subsample,
            timeout_s=timeout_s,
            scratch=scratch_dir,
            resolver=resolver,
            fault=fault,
        )
        for setup_id in targets
    )
    if record and not partial:
        _project(store, cam, statuses, resolver)
    return statuses, partial


def _project(
    store: OpStore,
    cam: CamState,
    statuses: tuple[ProgramStatus, ...],
    resolver: AnchorResolver,
) -> None:
    """Record one full run onto the program-status projection (§11 item 26)."""
    from hephaestus.core.project_store.locks import LockManager
    from hephaestus.core.project_store.projections import ProgramProjection, Projections

    document = canonical_json([status.to_json() for status in statuses]).encode("utf-8")
    blob = store.blobs.put(document)
    store.gc.pin(blob)
    projections = Projections(store, locks=LockManager(store))
    projections.record_program(
        ProgramProjection(
            statuses_blob=blob,
            setup_generation=cam.setups.state().generation,
            operation_generation=cam.operations.state().generation,
            audit_revision=projections.state().audit_revision,
            parts=resolver.artifact_refs(),
        )
    )


def projected_statuses(store: OpStore) -> tuple[Mapping[str, JSONValue], ...] | None:
    """The last projected full run's records, or ``None`` for never evaluated."""
    import json

    from hephaestus.core.project_store.locks import LockManager
    from hephaestus.core.project_store.projections import Projections

    state = Projections(store, locks=LockManager(store)).state()
    if state.program is None:
        return None
    raw = json.loads(store.blobs.get(state.program.statuses_blob).decode("utf-8"))
    return tuple(cast("Sequence[Mapping[str, JSONValue]]", raw))


# --------------------------------------------------------------------------
# the CHECKS read surface over one frozen snapshot (§9, script_contract §6)


class _PinnedResolver(AnchorResolver):
    """The 8C anchoring path pinned to one frozen project snapshot.

    The ``_SnapshotAnchorResolver`` rule (``motion.py``), restated for CAM:
    inside a project-scope check run every read comes from the SAME frozen
    snapshot the run's sources came from, never CURRENT mid-run. A part
    outside the manifest is ``missing_part``; a part republished past the
    pinned ref is ``missing_artifact``.
    """

    def __init__(
        self,
        layout: ProjectLayout,
        store: OpStore,
        publisher: Publisher,
        scratch: Path,
        *,
        pinned: Mapping[str, str],
        snapshot_ref: str,
    ) -> None:
        super().__init__(layout, store, publisher, scratch)
        self._pinned = dict(pinned)
        self._snapshot_ref = snapshot_ref

    def _load_part(self, part: str) -> PartGeometry:
        pinned_ref = self._pinned.get(part)
        if pinned_ref is None:
            names = ", ".join(sorted(self._pinned)) or "none"
            raise UnresolvableAnchorError(
                "missing_part",
                f"no part {part!r} in this run's frozen project snapshot "
                f"{self._snapshot_ref} (snapshot parts: {names})",
            )
        geometry = super()._load_part(part)
        if geometry.artifact_ref != pinned_ref:
            raise UnresolvableAnchorError(
                "missing_artifact",
                f"part {part!r} was republished after this run's snapshot froze: current "
                f"artifact {geometry.artifact_ref} is not the pinned {pinned_ref} "
                "(a check run never measures CURRENT mid-run)",
            )
        return geometry


class SnapshotProgramContext:
    """``m.program(setup_id)`` bound to one frozen snapshot (CAM.md §9).

    The project-scope facade's program resolver: evaluates
    :func:`check_setup` against the run's pinned artifact refs, memoized per
    setup id (one run has one program state, so re-asking restates the same
    facts). A :class:`CamSimTimeout` inside a predicate propagates to the
    checks engine, which records that check as **unverifiable** — not a pass
    and not a crash.
    """

    def __init__(
        self,
        layout: ProjectLayout,
        store: OpStore,
        *,
        snapshot_ref: str,
        scratch: Path,
        tools: Any,
        materials: Any | None = None,
        timeout_s: float | None = None,
    ) -> None:
        import json

        from hephaestus.core.project_store.store import blob_hash_of_ref

        self.snapshot_ref = snapshot_ref
        self._layout = layout
        self._store = store
        self._scratch = scratch
        self._tools = tools
        self._materials = materials
        self._timeout_s = timeout_s
        manifest = json.loads(store.blobs.get(blob_hash_of_ref(snapshot_ref)).decode("utf-8"))
        parts = cast("Mapping[str, Mapping[str, JSONValue]]", manifest.get("parts", {}))
        pinned = {name: str(entry.get("artifact_ref", "")) for name, entry in parts.items()}
        self._resolver = _PinnedResolver(
            layout,
            store,
            Publisher(layout, store),
            scratch,
            pinned=pinned,
            snapshot_ref=snapshot_ref,
        )
        self._results: dict[str, Mapping[str, JSONValue]] = {}

    def program(self, setup_id: str) -> Mapping[str, JSONValue]:
        result = self._results.get(setup_id)
        if result is None:
            result = check_setup(
                self._layout,
                self._store,
                setup_id,
                tools=self._tools,
                materials=self._materials,
                scratch=self._scratch,
                resolver=self._resolver,
                timeout_s=self._timeout_s,
                raise_timeout=True,
            ).to_json()
            self._results[setup_id] = result
        return result
