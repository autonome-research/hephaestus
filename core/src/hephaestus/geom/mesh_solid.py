# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
# OCP ships no type stubs and its pybind11 signatures are untyped; the
# relaxation is pinned per-file exactly as ``geom.measure`` and ``geom.nesting``
# pin it, so it stays scoped to the modules that touch the kernel.
# pyright: reportMissingTypeStubs=false
# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false
# pyright: reportUnknownVariableType=false, reportUnknownParameterType=false
"""Triangles -> B-rep, and the refusals that keep it honest (``MESH_INGEST.md`` §4-§5).

This is the module that could most easily lie. Everything in
:mod:`hephaestus.geom.mesh` is arithmetic over a triangle soup and cannot claim
more than it counted; here the kernel is asked to turn a scan into a *solid*,
and OCCT will happily hand back a plausible-looking, catastrophically wrong one.

The load-bearing measurement, reproduced on this repository's pinned OCCT 7.9.3
and archived at ``tests/stage12b/evidence/`` (``MESH_INGEST.md`` §4.2):

* a clean tessellated R20 sphere (2004 triangles) sews in ~0.34 s into ONE
  closed shell; :func:`hephaestus.geom.metrics.is_sealed` on the resulting solid
  is **True** and ``genus`` is 0;
* ``BRepCheck_Analyzer(...).IsValid()`` on that same solid is **False**
  (``BRepCheck_SelfIntersectingWire`` on one wire, ``BRepCheck_UnorientableShape``
  on one face);
* ``BRepOffsetAPI_MakeOffsetShape`` at +2 mm on it returns, after 30.7 s,
  ``IsDone()=True``, non-null, ``TopAbs_SOLID``, 279 faces, ``is_sealed=True``,
  ``genus=0`` — and **volume 0.0030 mm³ where the correct answer is 44602 mm³**.

Every sanity signal the harness has says that offset succeeded. So the design
here is not "check the result": it is **withhold the operand**. ``IsValid()`` is
a mandatory gate (§4.3) and a False verdict is the named refusal
``mesh_solid_invalid``. ``MESH_INGEST.md`` §5.2 is the workflow that does not
need the conversion at all: section the scan, author geometry through the
sections, and offset *that*.

**A finding that runs the other way, and it is good news.** §4.3 predicts
``mesh_to_solid`` "refuses most real scans", and that prediction was made
against the measurement above — which was taken on the tessellator's RAW output,
1027 vertices for 2004 triangles, every triangle carrying its own three corner
copies. Put the same sphere through this stage's own §1.5 canonicalization
first — the weld that exists for *hashing*, merging 5009 duplicate vertex pairs
down to 1003 vertices and dropping 2 degenerate triangles — and the sew produces
a solid whose ``IsValid()`` is **True**. The canonical pipeline built to give a
mesh a stable identity turns out to be the thing that makes it sewable, and
since ``import_mesh`` is the only route to a ``MeshAsset``, every
``mesh_to_solid`` in this harness gets the welded mesh. The gate is unchanged
and the refusals below are unchanged: a cube missing one triangle, a
non-manifold fin and any real hole still fail it. What changed is the
expectation, and the honest thing is to say so rather than to keep quoting a
prediction the code disproves.

Why this is a separate module from :mod:`hephaestus.geom.mesh`: the same seam
that separates ``geom.mesh`` from ``render.tessellate``. Facts computable from
the triangles alone live there; anything that needs OCCT to answer lives here.
Both are pure — no executor, no store, no project, no verdicts — and the
process ceiling on the sew is an engine concern
(:mod:`hephaestus.core.mesh_solid`, the ``COMPARE.md`` §5 rule).
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Literal, NoReturn, cast

from build123d import Solid
from hephaestus.geom.mesh import MeshOperationError, SectionPolyline

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray
    from opstore.types import JSONValue

__all__ = [
    "MESH_DERIVED_REFUSED_OPERATIONS",
    "MESH_REPAIR_AVAILABLE",
    "MESH_SOLID_INTENTS",
    "SEW_TOLERANCE_MM",
    "MeshDerivedSolid",
    "MeshSolidIntent",
    "SewReport",
    "ShapeFixOutcome",
    "analyzer_statuses",
    "gate_sewn_solid",
    "loft_sections",
    "sew_to_solid",
    "shapefix_probe",
]

#: The closed ``intent`` set of §4.3. ``"measurement_target"`` — the solid will
#: be measured, compared, sectioned; ``"boolean_operand"`` — it will be cut from
#: or united with authored geometry, which §5.1 measures as the ONE operation
#: that works on a mesh-derived solid. There is deliberately no
#: ``"offset_operand"``, and there will not be one before §4.5's evidence
#: exists — which, measured below, it does not.
MESH_SOLID_INTENTS: Final[tuple[str, ...]] = ("measurement_target", "boolean_operand")
MeshSolidIntent = Literal["measurement_target", "boolean_operand"]

#: Sewing tolerance. Tight on purpose: the canonical mesh is already welded at
#: ``MESH_WELD_TOL_MM`` (1e-6 mm), so a sew tolerance any looser would merge
#: geometry the canonicalizer deliberately kept apart, and the merge would show
#: up as a topology change nobody recorded.
SEW_TOLERANCE_MM: Final[float] = 1e-6

#: §4.5, MEASURED and not assumed. ``ShapeFix_Shape`` / ``ShapeFix_Solid`` /
#: ``ShapeFix_Shell`` were all run against the §4.1 reference sewn sphere (the
#: unwelded one, the only one that needs repairing) on the pinned OCCT 7.9.3;
#: all three completed **well inside** the §4.1 ceiling (0.3135 s / 0.2466 s /
#: 0.2426 s, from the archived record in
#: ``tests/stage12b/evidence/shapefix_experiment.json`` — the pinned image's own
#: run, which is the only figure this comment is allowed to quote; the numbers
#: here were the pre-image venv's until the third repair pass) and **none of
#: them reached** ``IsValid()`` — every one came back
#: False, and ``ShapeFix_Shape`` and ``ShapeFix_Solid`` additionally flipped the
#: solid's volume sign (-33273.57 mm³ from +33273.57). The disposition rule the
#: spec pre-committed to therefore selects its second branch: ``mesh_to_solid``
#: keeps refusing ``mesh_solid_invalid``, the socket workflow is §5.2 only, and
#: **no ``repair=True`` argument exists anywhere in this stage**. A cheap repair
#: that does not repair is worse than no repair: it would spend a quarter second
#: to turn a named refusal into a differently-broken solid with a sign-flipped
#: volume, which is precisely the plausible-looking wrong answer this stage
#: exists to refuse.
MESH_REPAIR_AVAILABLE: Final[bool] = False


@dataclass(frozen=True)
class SewReport:
    """What the sew produced, in the terms §8 Tier 3 permits to be claimed.

    OCCT's sewing is a tolerance-driven merge whose output topology this
    project does **not** claim is stable across OCCT builds, so nothing here is
    a byte: the record carries counts and a verdict, which is the most a sew can
    honestly offer, and the §8 Tier 3 clause binds exactly those.

    ``is_valid`` and ``analyzer_statuses`` are two halves of one answer, and both
    are kept: the verdict is what the gate acts on, and the status list is what
    lets a caller see *why* rather than being told "no".
    """

    triangle_count: int
    face_count: int
    vertex_count: int
    shell_count: int
    is_valid: bool
    analyzer_statuses: tuple[str, ...]
    sew_seconds: float

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "triangle_count": self.triangle_count,
            "face_count": self.face_count,
            "vertex_count": self.vertex_count,
            "shell_count": self.shell_count,
            "is_valid": self.is_valid,
            "analyzer_statuses": cast("JSONValue", list(self.analyzer_statuses)),
            "sew_seconds": self.sew_seconds,
        }

    def determinism_key(self) -> dict[str, JSONValue]:
        """The §8 Tier 3 projection: counts and verdict, never bytes and never time.

        ``sew_seconds`` is deliberately absent — a wall clock is not a property
        of the geometry, and a golden that pinned one would fail on a busy
        runner for a reason that has nothing to do with the kernel.
        """
        return {
            "triangle_count": self.triangle_count,
            "face_count": self.face_count,
            "vertex_count": self.vertex_count,
            "shell_count": self.shell_count,
            "is_valid": self.is_valid,
            "analyzer_statuses": cast("JSONValue", list(self.analyzer_statuses)),
        }


@dataclass(frozen=True)
class ShapeFixOutcome:
    """One §4.5 repair measurement: did it reach ``IsValid()``, and at what cost."""

    fixer: str
    seconds: float
    reached_valid: bool
    face_count_before: int
    face_count_after: int
    volume_before_mm3: float
    volume_after_mm3: float

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "fixer": self.fixer,
            "seconds": self.seconds,
            "reached_valid": self.reached_valid,
            "face_count_before": self.face_count_before,
            "face_count_after": self.face_count_after,
            "volume_before_mm3": self.volume_before_mm3,
            "volume_after_mm3": self.volume_after_mm3,
        }


def _refuse(operation: str, source: str) -> NoReturn:
    """The §5.1 table, raised by name."""
    raise MeshOperationError(
        f"{operation} on the mesh-derived solid "
        f"{source!r} is refused (MESH_INGEST.md §5.1). Measured on the pinned "
        "kernel: BRepOffsetAPI_MakeOffsetShape at +2 mm over a faceted solid "
        "returns IsDone, non-null, sealed, genus 0 — and a volume five million "
        "times too small. A blend has no smooth edge to work on either: every "
        "edge of a faceted body is a facet crease. Do not offset the scan — "
        "section it, author geometry through the sections (section_polylines -> "
        "loft_sections), and offset that (§5.2).",
        reason="mesh_derived_operation_refused",
    )


#: The operations :class:`MeshDerivedSolid` refuses, named once so a test can
#: enumerate them rather than transcribe them. ``offset_3d`` is the method
#: build123d's own free ``offset()`` dispatches to for a solid, and ``fillet`` /
#: ``chamfer`` are what its free functions call on the target, so refusing the
#: methods refuses BOTH spellings without wrapping or renaming anything
#: build123d exports (``script_contract.md`` §2 forbids that, and this does not
#: do it). ``max_fillet`` joins them because a radius search is a fillet with a
#: loop around it, and answering it would be claiming a blend is possible.
MESH_DERIVED_REFUSED_OPERATIONS: Final[tuple[str, ...]] = (
    "chamfer",
    "fillet",
    "max_fillet",
    "offset_3d",
    "shell",
    "thicken",
)


class MeshDerivedSolid(Solid):
    """A solid sewn from a mesh, refusing what §5.1 measured as wrong on one.

    Subclassing build123d's ``Solid`` — rather than wrapping it — is what keeps
    §5.1's one working operation working: **trim**, a boolean against authored
    geometry, goes through the ordinary kernel path and comes back an ordinary
    ``Solid``. That is right rather than a leak: the result of cutting a scan
    out of authored stock is no longer the object whose facet creases these
    refusals are about.

    What the subclass buys is the ONE chokepoint the harness genuinely owns —
    the object ``mesh_to_solid`` itself returned — and it buys both spellings at
    once, because build123d's free ``offset()`` / ``fillet()`` / ``chamfer()``
    dispatch to methods on their target. It is **not** a kernel interception and
    does not pretend to be: ``Solid(scan.wrapped)`` defeats it in one line, and
    so does a boolean first. That is exactly why the ``heph lint`` rule
    ``mesh_derived_offset`` stands beside it and documents its own
    defeatability (§4.3). A hard refusal where enforcement is real; a named lint
    where it is not.
    """

    #: The import path this solid was sewn from, carried so a refusal can name it.
    mesh_source: str = "<mesh>"
    #: The :class:`SewReport` this solid came with, or ``None`` before it is set.
    mesh_sew_report: SewReport | None = None

    def offset_3d(self, *_args: object, **_kwargs: object) -> NoReturn:
        """Refused (§5.1): measured silently, catastrophically wrong."""
        _refuse("offset", self.mesh_source)

    @classmethod
    def thicken(cls, *_args: object, **_kwargs: object) -> NoReturn:
        """Refused (§5.1): same mechanism, same measurement.

        A ``classmethod``, because build123d's ``Solid.thicken`` is one — it
        thickens a *Face*, and the operand path that actually reaches a
        mesh-derived **solid** for the "shell / thicken (wall)" row is
        :meth:`shell` and :meth:`offset_3d`. The override is kept anyway so the
        spelling a script is most likely to reach for gets the named refusal
        instead of a confusing signature error from one class up.
        """
        _refuse("thicken", "<mesh>")

    def shell(self, *_args: object, **_kwargs: object) -> NoReturn:
        """Refused (§5.1): a wall built by offsetting a facet soup."""
        _refuse("shell", self.mesh_source)

    def fillet(self, *_args: object, **_kwargs: object) -> NoReturn:
        """Refused by geometry, not by policy (§5.1): every edge is a facet crease."""
        _refuse("fillet", self.mesh_source)

    def chamfer(self, *_args: object, **_kwargs: object) -> NoReturn:
        """Refused by geometry, not by policy (§5.1): every edge is a facet crease."""
        _refuse("chamfer", self.mesh_source)

    def max_fillet(self, *_args: object, **_kwargs: object) -> NoReturn:
        """Refused (§5.1): a radius search is a fillet with a loop around it."""
        _refuse("max_fillet", self.mesh_source)


def _sew(vertices: NDArray[np.float64], faces: NDArray[np.int64]) -> tuple[Any, float]:
    """``BRepBuilderAPI_Sewing`` over one triangle per face, and its wall clock."""
    from OCP.BRepBuilderAPI import (
        BRepBuilderAPI_MakeFace,  # pyright: ignore[reportAttributeAccessIssue]
        BRepBuilderAPI_MakePolygon,  # pyright: ignore[reportAttributeAccessIssue]
        BRepBuilderAPI_Sewing,  # pyright: ignore[reportAttributeAccessIssue]
    )
    from OCP.gp import gp_Pnt  # pyright: ignore[reportAttributeAccessIssue]

    started = time.monotonic()
    sewing = BRepBuilderAPI_Sewing(SEW_TOLERANCE_MM)
    for tri in faces:
        polygon = BRepBuilderAPI_MakePolygon()
        for index in tri:
            point = vertices[int(index)]
            polygon.Add(gp_Pnt(float(point[0]), float(point[1]), float(point[2])))
        polygon.Close()
        if not polygon.IsDone():
            continue
        face = BRepBuilderAPI_MakeFace(polygon.Wire())
        if not face.IsDone():
            continue
        sewing.Add(face.Face())
    sewing.Perform()
    return sewing.SewedShape(), time.monotonic() - started


def _shells(shape: Any) -> list[Any]:
    from OCP.TopAbs import TopAbs_ShapeEnum  # pyright: ignore[reportAttributeAccessIssue]
    from OCP.TopExp import TopExp_Explorer  # pyright: ignore[reportAttributeAccessIssue]
    from OCP.TopoDS import TopoDS  # pyright: ignore[reportAttributeAccessIssue]

    found: list[Any] = []
    explorer = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_SHELL)
    while explorer.More():
        found.append(TopoDS.Shell_s(explorer.Current()))
        explorer.Next()
    return found


def analyzer_statuses(shape: Any) -> tuple[str, ...]:
    """Every non-``NoError`` ``BRepCheck`` status on ``shape`` and its sub-shapes.

    ``BRepCheck_Analyzer.IsValid()`` is one bit; a refusal that carried only
    that bit would tell a caller their scan is unusable without telling them
    what is wrong with it. The analyzer's own per-sub-shape result is walked
    here so ``mesh_solid_invalid`` can name the defect — on the reference sewn
    sphere it is ``wire:BRepCheck_SelfIntersectingWire`` and
    ``face:BRepCheck_UnorientableShape``.

    **Three passes, not one, because one was measured to be silent.** A cube
    with one triangle deleted sews into a solid whose ``IsValid()`` is False
    while every sub-shape's ``Result().Status()`` reads ``NoError`` — OCCT keeps
    that verdict in ``BRepCheck_Shell``'s own ``Closed()`` check, and a
    status-only walk reported an empty list beside a refusal, which is a refusal
    that will not say why. So: the status lists, then each shell's dedicated
    closure and orientation checks, then a final ``invalid_unreported`` entry
    for any sub-shape the analyzer rejects and none of the above explained. That
    last one is deliberately an admission rather than a silence.

    Sorted and deduplicated with counts, because the useful fact is *which*
    defects and *how many*, and an unsorted walk order would be a topology
    detail leaking into a message.
    """
    from OCP.BRepCheck import (  # pyright: ignore[reportAttributeAccessIssue]
        BRepCheck_Analyzer,  # pyright: ignore[reportAttributeAccessIssue]
        BRepCheck_Shell,  # pyright: ignore[reportAttributeAccessIssue]
        BRepCheck_Status,  # pyright: ignore[reportAttributeAccessIssue]
    )
    from OCP.TopAbs import TopAbs_ShapeEnum  # pyright: ignore[reportAttributeAccessIssue]
    from OCP.TopExp import TopExp  # pyright: ignore[reportAttributeAccessIssue]
    from OCP.TopoDS import TopoDS  # pyright: ignore[reportAttributeAccessIssue]
    from OCP.TopTools import (
        TopTools_IndexedMapOfShape,  # pyright: ignore[reportAttributeAccessIssue]
    )

    analyzer = BRepCheck_Analyzer(shape)
    levels = (
        (TopAbs_ShapeEnum.TopAbs_VERTEX, "vertex"),
        (TopAbs_ShapeEnum.TopAbs_EDGE, "edge"),
        (TopAbs_ShapeEnum.TopAbs_WIRE, "wire"),
        (TopAbs_ShapeEnum.TopAbs_FACE, "face"),
        (TopAbs_ShapeEnum.TopAbs_SHELL, "shell"),
        (TopAbs_ShapeEnum.TopAbs_SOLID, "solid"),
    )
    counts: dict[str, int] = {}

    def record(name: str) -> None:
        counts[name] = counts.get(name, 0) + 1

    for enum, label in levels:
        mapping = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(shape, enum, mapping)
        for index in range(1, mapping.Extent() + 1):
            sub = mapping.FindKey(index)
            explained = False
            try:
                result = analyzer.Result(sub)
            except Exception:
                result = None
            if result is not None:
                for status in result.Status():
                    if status == BRepCheck_Status.BRepCheck_NoError:
                        continue
                    record(f"{label}:{str(status).rsplit('.', maxsplit=1)[-1]}")
                    explained = True
            if label == "shell":
                # ``MapShapes_s`` hands back a ``TopoDS_Shape``; the shell
                # checker's binding takes a ``TopoDS_Shell`` and nothing else.
                checker = BRepCheck_Shell(TopoDS.Shell_s(sub))
                probes = (
                    (checker.Closed(), "Closed"),
                    (checker.Orientation(), "Orientation"),
                )
                for probe, what in probes:
                    if probe == BRepCheck_Status.BRepCheck_NoError:
                        continue
                    record(f"shell:{what}={str(probe).rsplit('.', maxsplit=1)[-1]}")
                    explained = True
            if not explained and not analyzer.IsValid(sub):
                # An admission, not a silence: the analyzer rejects this
                # sub-shape and nothing above said why. A refusal that reported
                # an empty list here would read as "invalid for no reason".
                record(f"{label}:invalid_unreported")
    return tuple(f"{name}x{count}" for name, count in sorted(counts.items()))


def sew_to_solid(
    vertices: NDArray[np.float64],
    faces: NDArray[np.int64],
    *,
    source: str = "<hmesh>",
) -> tuple[Any, SewReport]:
    """Sew triangles into a solid and MEASURE it — no gate, no refusal on validity.

    Pure and unbounded, exactly as ``geom.compare`` is
    (``COMPARE.md`` §5: process management is an engine concern). The caller
    applies :func:`gate_sewn_solid`; splitting the two is what lets the §4.5
    repair experiment and the §8 Tier 3 determinism clause measure a solid the
    gate would refuse, without either of them having to route around the gate.

    Raises ``mesh_solid_invalid`` only where there is no solid to report on at
    all — a sew that produced no closed shell, or more than one. Those are
    facts about the sew rather than verdicts about the solid, and a caller
    holding "zero shells" needs a different fix from one holding "invalid".
    """
    from OCP.BRepBuilderAPI import (
        BRepBuilderAPI_MakeSolid,  # pyright: ignore[reportAttributeAccessIssue]
    )
    from OCP.BRepCheck import BRepCheck_Analyzer  # pyright: ignore[reportAttributeAccessIssue]

    sewn, seconds = _sew(vertices, faces)
    shells = _shells(sewn)
    if len(shells) != 1:
        raise MeshOperationError(
            f"sewing {source!r} ({faces.shape[0]} triangles) produced "
            f"{len(shells)} closed shells, not one; there is no single solid here to "
            "hand back. A scan whose surface does not sew into one shell is a scan "
            "with holes or disconnected components — §3's quality record says which "
            "(MESH_INGEST.md §4.3).",
            reason="mesh_solid_invalid",
        )
    solid = BRepBuilderAPI_MakeSolid(shells[0]).Solid()
    wrapped = MeshDerivedSolid(solid)
    report = SewReport(
        triangle_count=int(faces.shape[0]),
        face_count=len(wrapped.faces()),
        vertex_count=len(wrapped.vertices()),
        shell_count=len(shells),
        is_valid=bool(BRepCheck_Analyzer(solid).IsValid()),
        analyzer_statuses=analyzer_statuses(solid),
        sew_seconds=float(seconds),
    )
    wrapped.mesh_source = source
    wrapped.mesh_sew_report = report
    return wrapped, report


def gate_sewn_solid(
    solid: Any,
    report: SewReport,
    *,
    source: str,
    quality: object = None,
) -> Any:
    """The MANDATORY ``BRepCheck_Analyzer`` gate of §4.3.

    ``IsValid()`` False is ``mesh_solid_invalid``, and the refusal carries the
    analyzer's own per-sub-shape status list, the triangle count and the §3
    quality record so the caller can see *why* — holes, non-manifold edges — and
    not merely that.

    The refusal is the point, and it fires on far less than §4.3 predicted —
    see the module docstring's canonicalization finding. A cube with one
    triangle deleted still refuses (``shell:Closed=BRepCheck_NotClosed``), a
    non-manifold fin still refuses, and the §4.1 reference sphere refuses
    whenever it reaches here *unwelded*. What a returned solid means is only
    that ``IsValid()`` said so; it is not a promise that an offset of it would
    be right, which is why §5.1 refuses that separately.
    """
    if report.is_valid:
        return solid
    detail = ", ".join(report.analyzer_statuses) or "(no per-sub-shape status reported)"
    quality_note = "" if quality is None else f" quality={quality!r}."
    raise MeshOperationError(
        f"{source!r} sewed into a solid that "
        f"BRepCheck_Analyzer.IsValid() rejects ({report.triangle_count} triangles, "
        f"{report.face_count} faces; {detail}).{quality_note} The solid is withheld "
        "rather than handed back, because §4.2 measured what happens when it is not: "
        "an offset of an invalid mesh-derived solid reports IsDone, non-null, sealed, "
        "genus 0 — and a volume five million times too small. The §3 quality record "
        "says what is wrong with the scan; §5.2 is the workflow that does not need "
        "this conversion at all (MESH_INGEST.md §4.3, §5.2).",
        reason="mesh_solid_invalid",
    )


def shapefix_probe(solid: Any, *, fixer: str = "ShapeFix_Shape") -> ShapeFixOutcome:
    """Run one §4.5 repair fixer and MEASURE the result (never assume it).

    This exists so the §4.5 disposition rule is decided by a number rather than
    by an opinion, and so a future OCCT bump that changes the answer is caught
    by a gate clause instead of by a surprised operator. It is a measurement
    service: it repairs nothing anybody keeps, and no production path calls it.
    """
    from OCP.BRepCheck import BRepCheck_Analyzer  # pyright: ignore[reportAttributeAccessIssue]
    from OCP.ShapeFix import (  # pyright: ignore[reportAttributeAccessIssue]
        ShapeFix_Shape,  # pyright: ignore[reportAttributeAccessIssue]
        ShapeFix_Shell,  # pyright: ignore[reportAttributeAccessIssue]
        ShapeFix_Solid,  # pyright: ignore[reportAttributeAccessIssue]
    )

    fixers: dict[str, Any] = {
        "ShapeFix_Shape": ShapeFix_Shape,
        "ShapeFix_Solid": ShapeFix_Solid,
        "ShapeFix_Shell": ShapeFix_Shell,
    }
    if fixer not in fixers:
        raise ValueError(f"unknown ShapeFix class {fixer!r}; known: {sorted(fixers)}")
    before = cast("Any", Solid(solid.wrapped if hasattr(solid, "wrapped") else solid))
    # ``ShapeFix_Shell`` takes a ``TopoDS_Shell``, not a solid — its binding
    # refuses the solid outright — so it is handed the solid's own shell. Named
    # rather than swallowed: "the shell fixer was run on the shell" is a
    # different experiment from "the shape fixer was run on the solid", and the
    # §4.5 record must say which was measured.
    subject = _shells(before.wrapped)[0] if fixer == "ShapeFix_Shell" else before.wrapped
    started = time.monotonic()
    tool = fixers[fixer](subject)
    tool.Perform()
    fixed = tool.Shape()
    seconds = time.monotonic() - started
    after = cast("Any", Solid(fixed)) if fixed.ShapeType() == before.wrapped.ShapeType() else before
    return ShapeFixOutcome(
        fixer=fixer,
        seconds=float(seconds),
        reached_valid=bool(BRepCheck_Analyzer(fixed).IsValid()),
        face_count_before=len(before.faces()),
        face_count_after=len(after.faces()),
        volume_before_mm3=float(before.volume),
        volume_after_mm3=float(after.volume),
    )


def loft_sections(
    polylines: Sequence[SectionPolyline],
    *,
    ruled: bool = False,
    degree_min: int = 3,
    degree_max: int = 8,
    tolerance_mm: float = 1e-3,
    source: str = "<sections>",
) -> Any:
    """Section contours -> one B-spline per section -> an ANALYTIC solid (§5.2).

    This is the harness-injected half of "do not offset the scan; author
    geometry against the scan, and offset that". It exists as a harness helper
    rather than as script code for a structural reason:
    ``script_contract.md`` §2 closes the namespace with "Nothing else" and
    ``__import__`` is absent, so a part script has **no** route to
    ``GeomAPI_PointsToBSpline`` — specifying a workflow that named it would
    specify an unreachable path (§5.2).

    What comes back is an ordinary build123d ``Solid``, not a
    :class:`MeshDerivedSolid`, and that is the whole point: it was authored
    through the scan's measurements, it is analytic, and ``offset`` / ``thicken``
    / ``fillet`` on it are the operations §5.1 measured as *working*. The scan
    was measurement data; the socket is authored geometry.

    An OPEN contour is refused ``open_section_contour``. Lofting through one
    would ask the kernel to close it, which is the fabrication §5.3 refuses one
    level down — a hole in the scan must not become socket wall by passing
    through a spline fitter.
    """
    from build123d import Wire
    from OCP.BRepBuilderAPI import (  # pyright: ignore[reportAttributeAccessIssue]
        BRepBuilderAPI_MakeEdge,  # pyright: ignore[reportAttributeAccessIssue]
        BRepBuilderAPI_MakeWire,  # pyright: ignore[reportAttributeAccessIssue]
    )
    from OCP.BRepCheck import BRepCheck_Analyzer  # pyright: ignore[reportAttributeAccessIssue]
    from OCP.GeomAbs import GeomAbs_Shape  # pyright: ignore[reportAttributeAccessIssue]
    from OCP.GeomAPI import GeomAPI_PointsToBSpline  # pyright: ignore[reportAttributeAccessIssue]
    from OCP.gp import gp_Pnt  # pyright: ignore[reportAttributeAccessIssue]
    from OCP.TColgp import TColgp_Array1OfPnt  # pyright: ignore[reportAttributeAccessIssue]

    sections = list(polylines)
    if len(sections) < 2:
        raise MeshOperationError(
            f"loft_sections({source!r}) needs at least two contours to "
            f"loft through, got {len(sections)}; one section is a curve, not a solid "
            "(MESH_INGEST.md §5.2)",
            reason="empty_section",
        )
    wires: list[Any] = []
    for index, polyline in enumerate(sections):
        if not polyline.closed:
            raise MeshOperationError(
                f"section {index} of {source!r} does not close "
                f"({len(polyline.points)} points) — the plane crossed a hole in the "
                "scan. Lofting through it would ask the kernel to invent the surface "
                "the scanner never saw, at exactly the place a socket presses. Fill "
                "the hole in the scan, or move the plane (MESH_INGEST.md §5.3).",
                reason="open_section_contour",
            )
        if len(polyline.points) < 3:
            raise MeshOperationError(
                f"section {index} of {source!r} has {len(polyline.points)} "
                "points; a closed contour needs at least three",
                reason="empty_section",
            )
        # A closed contour's record does not repeat its first point (that is
        # what ``closed`` means), and the fitter must see the wrap-around or it
        # produces an open curve through a closed contour.
        points = [*polyline.points, polyline.points[0]]
        array = TColgp_Array1OfPnt(1, len(points))
        for slot, point in enumerate(points, start=1):
            array.SetValue(slot, gp_Pnt(float(point[0]), float(point[1]), float(point[2])))
        fit = GeomAPI_PointsToBSpline(
            array, degree_min, degree_max, GeomAbs_Shape.GeomAbs_C2, tolerance_mm
        )
        edge = BRepBuilderAPI_MakeEdge(fit.Curve()).Edge()
        wires.append(Wire(BRepBuilderAPI_MakeWire(edge).Wire()))
    lofted = cast("Any", Solid).make_loft(wires, ruled=ruled)
    # THE SAME GATE §4.3 mandates for the sew, for the same reason, and it is
    # here because it was MEASURED to be needed. On a densely sampled contour
    # (78 crossing points of a tessellated R15 cylinder, 81 B-spline poles)
    # OCCT's ThruSections returns a ONE-FACE lateral shell with no caps, which
    # build123d still hands back as a ``Solid`` and whose ``.volume`` reads
    # 9423 mm³ where the answer is 14137 — exactly the plausible-looking wrong
    # number this stage exists to refuse, arriving through the workflow that was
    # supposed to be the safe one. Resampling the same contour at a declared
    # 2 mm spacing (48 points, 51 poles) lofts to three faces, a valid solid and
    # 14097 mm³, so the fix is in the caller's hands and the message says so.
    if not BRepCheck_Analyzer(lofted.wrapped).IsValid():
        raise MeshOperationError(
            f"the loft through {len(sections)} sections of "
            f"{source!r} ({', '.join(str(len(p.points)) for p in sections)} points) "
            f"produced {len(lofted.faces())} face(s) that BRepCheck_Analyzer rejects — "
            "an uncapped lateral shell, whose reported volume would be a number about "
            "a surface rather than about a solid. Measured cause: OCCT's ThruSections "
            "does not cap a loft through very dense B-splines. Resample the sections "
            "at a declared spacing (section_polylines(..., spacing=2.0)) and loft "
            "those (MESH_INGEST.md §4.3, §5.2).",
            reason="mesh_solid_invalid",
        )
    return lofted
