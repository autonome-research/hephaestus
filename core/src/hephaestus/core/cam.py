"""2D CAM: laser-cut and waterjet toolpath emission from existing geometry.

This is not Stage 14 milling CAM (``CAM.md``). Waterjet and laser share the
existing 2D cut-file path — flat pattern, kerf, DXF — and that path is what
this module exposes as an engine verb. A program here is a cut-file: ordered
contours plus the DXF bytes a controller already consumes.

Kerf is never invented. :func:`~hephaestus.geom.kerf.resolve_kerf` supplies
the source order: an explicit millimetre width, else the DFM pack's
``kerf_mm`` for the declared process, else an uncompensated path that says so.
A default kerf is worse than none, because none is visible with a caliper and
a wrong one looks correct.

Cut order is the shop convention, not a guess: mark (engrave, then score)
while the sheet is still held, then pierce every hole, then free the part on
its outer ring. Nothing is inferred from size or depth — an untagged contour
is always a through-cut, the same rule :mod:`hephaestus.core.cutfile` already
states.

The geometry kernel is the one already in-tree:
:func:`~hephaestus.geom.kerf.kerf_compensated_shape`,
:func:`~hephaestus.geom.nesting.flat_profiles`,
:func:`~hephaestus.geom.nesting.shelf_nest`,
:func:`~hephaestus.geom.nesting.layout_to_dxf`. This module does not add a
second offset, a second packer, or a second DXF writer.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from hephaestus.core.errors import AddressingError, HephaestusError, ValidationError
from hephaestus.core.hashing import sha256_bytes
from hephaestus.geom.kerf import KerfDecision, KerfRefusal, kerf_compensated_shape, resolve_kerf
from hephaestus.geom.nesting import (
    CUT_LAYER,
    DEFAULT_MARGIN_MM,
    DEFAULT_SPACING_MM,
    ENGRAVE_LAYER,
    SCORE_LAYER,
    Blank,
    NestedLayout,
    NestingRefusal,
    Profile,
    blank_from_metadata,
    flat_profiles,
    layout_to_dxf,
    shelf_nest,
)
from opstore.types import JSONValue

__all__ = [
    "CUT2D_PROCESSES",
    "CamRefusal",
    "Cut2dProgram",
    "CutContour",
    "derived_blank",
    "emit_cut2d",
    "emit_part",
    "pack_kerf_of",
]

#: Processes this pack will emit a 2D cut-file for. A router bit is not a beam;
#: ``cnc_router`` has a DFM pack and no place here.
CUT2D_PROCESSES: Final[tuple[str, ...]] = ("laser_cut", "waterjet")


class CamRefusal(HephaestusError):
    """2D CAM could not produce a cut-file; ``reason`` is the stable token."""

    code = "cam_refused"

    def __init__(
        self, reason: str, message: str, *, data: Mapping[str, JSONValue] | None = None
    ) -> None:
        super().__init__(f"{reason}: {message}")
        self.reason = reason
        self.data: dict[str, JSONValue] = dict(data or {})


@dataclass(frozen=True)
class CutContour:
    """One ordered pass of the beam: which layer, which ring, and its polyline."""

    layer: str
    ring: str
    profile: str
    points: tuple[tuple[float, float], ...]
    closed: bool = True

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "layer": self.layer,
            "ring": self.ring,
            "profile": self.profile,
            "closed": self.closed,
            "points": [[x, y] for x, y in self.points],
        }


@dataclass(frozen=True)
class Cut2dProgram:
    """One 2D CAM artifact: the toolpath, the DXF, and the kerf that shaped them."""

    process: str
    part: str
    kerf: KerfDecision
    blank: Blank
    profiles: tuple[Profile, ...]
    toolpath: tuple[CutContour, ...]
    dxf: bytes
    source_artifact_ref: str | None = None

    def to_json(self) -> dict[str, JSONValue]:
        layers: dict[str, JSONValue] = {}
        for contour in self.toolpath:
            current = layers.get(contour.layer, 0)
            assert isinstance(current, int)
            layers[contour.layer] = current + 1
        return {
            "kind": "cut2d",
            "process": self.process,
            "part": self.part,
            "source_artifact_ref": self.source_artifact_ref,
            "kerf": self.kerf.to_json(),
            "blank": self.blank.to_json(),
            "profiles": [profile.to_json() for profile in self.profiles],
            "toolpath": [contour.to_json() for contour in self.toolpath],
            "layers": layers,
            "dxf_sha256": sha256_bytes(self.dxf),
            "dxf_bytes": len(self.dxf),
        }


def pack_kerf_of(process: str, dfm: Any) -> tuple[float | None, str | None]:
    """``(kerf_mm, why-not)`` from the DFM pack of one process.

    ``dfm`` is a :class:`~hephaestus.core.registry.DfmIndex` or ``None``. The
    token names the missing link the same way export already does, so a
    waterjet part without a pack is ``no_dfm_pack`` and a router pack without
    ``kerf_mm`` is ``pack_declares_no_kerf`` — never an invented width.
    """
    if dfm is None:
        return None, "no_dfm_registry"
    try:
        has = bool(dfm.has(process))
    except Exception:  # pragma: no cover - DfmIndex.has does not raise
        return None, "no_dfm_pack"
    if not has:
        return None, "no_dfm_pack"
    pack = dfm.get(process)
    param = pack.params.get("kerf_mm")
    if param is None:
        return None, "pack_declares_no_kerf"
    return float(param.value), None


def derived_blank(profiles: tuple[Profile, ...]) -> Blank:
    """A stock rectangle that fits ``profiles`` in one shelf row, plus margin.

    Used when the part did not declare ``part.blank_size``. This is not a shop
    blank invented as manufacturing advice — it is the smallest rectangle the
    already-extracted profiles occupy, so the DXF has a ``BLANK`` layer and
    the packer has somewhere to put them.
    """
    if not profiles:
        raise CamRefusal("no_profiles", "there are no profiles to emit a blank for", data={})
    width = sum(profile.width_mm for profile in profiles)
    if len(profiles) > 1:
        width += DEFAULT_SPACING_MM * (len(profiles) - 1)
    height = max(profile.height_mm for profile in profiles)
    return Blank(
        width_mm=width + 2.0 * DEFAULT_MARGIN_MM,
        height_mm=height + 2.0 * DEFAULT_MARGIN_MM,
        margin_mm=DEFAULT_MARGIN_MM,
        spacing_mm=DEFAULT_SPACING_MM,
    )


def _toolpath_from_layout(layout: NestedLayout) -> tuple[CutContour, ...]:
    """Shop order: engrave, score, holes, then the outer ring that frees the part."""
    contours: list[CutContour] = []
    for placement in layout.placements:
        name = placement.profile.name
        engrave = [mark for mark in placement.marks() if mark.layer == ENGRAVE_LAYER]
        score = [mark for mark in placement.marks() if mark.layer == SCORE_LAYER]
        for index, mark in enumerate(engrave, start=1):
            contours.append(
                CutContour(
                    layer=ENGRAVE_LAYER,
                    ring=f"engrave_{index}",
                    profile=name,
                    points=mark.points,
                    closed=mark.closed,
                )
            )
        for index, mark in enumerate(score, start=1):
            contours.append(
                CutContour(
                    layer=SCORE_LAYER,
                    ring=f"score_{index}",
                    profile=name,
                    points=mark.points,
                    closed=mark.closed,
                )
            )
        for index, ring in enumerate(placement.hole_points(), start=1):
            contours.append(
                CutContour(
                    layer=CUT_LAYER,
                    ring=f"hole_{index}",
                    profile=name,
                    points=ring,
                    closed=True,
                )
            )
        contours.append(
            CutContour(
                layer=CUT_LAYER,
                ring="outer",
                profile=name,
                points=placement.points(),
                closed=True,
            )
        )
    return tuple(contours)


def emit_cut2d(
    shape: Any,
    *,
    process: str,
    part: str = "part",
    explicit_kerf_mm: float | None = None,
    pack_kerf_mm: float | None = None,
    unavailable: str | None = None,
    blank: Blank | None = None,
    source_artifact_ref: str | None = None,
) -> Cut2dProgram:
    """Emit a laser/waterjet cut-file from a shape the caller already holds.

    ``process`` must be one of :data:`CUT2D_PROCESSES`. Kerf follows
    :func:`resolve_kerf`. A failed offset or a solid with no flat pattern is
    a named refusal — this is a cut path, so there is no ``as_built`` fallback.
    """
    if process not in CUT2D_PROCESSES:
        raise CamRefusal(
            "not_a_cut2d_process",
            f"process {process!r} is not a 2D cut process; "
            f"candidates: {', '.join(CUT2D_PROCESSES)}",
            data={"process": process, "candidates": list(CUT2D_PROCESSES)},
        )
    try:
        decision = resolve_kerf(
            explicit_mm=explicit_kerf_mm,
            process=process,
            pack_kerf_mm=pack_kerf_mm,
            unavailable=unavailable,
        )
    except ValidationError:
        raise
    cut_shape: Any = shape
    if decision.compensates:
        applied = decision.applied_mm
        assert applied is not None  # compensates implies a positive width
        try:
            cut_shape = kerf_compensated_shape(shape, applied, prefix=part)
        except KerfRefusal as exc:
            raise CamRefusal(exc.reason, exc.message, data=exc.data) from exc
    try:
        profiles = flat_profiles(cut_shape, prefix=part)
    except NestingRefusal as exc:
        raise CamRefusal(exc.reason, exc.message, data=exc.data) from exc
    resolved = blank if blank is not None else derived_blank(profiles)
    try:
        layout = shelf_nest(profiles, resolved)
    except NestingRefusal as exc:
        raise CamRefusal(exc.reason, exc.message, data=exc.data) from exc
    return Cut2dProgram(
        process=process,
        part=part,
        kerf=decision,
        blank=resolved,
        profiles=profiles,
        toolpath=_toolpath_from_layout(layout),
        dxf=layout_to_dxf(layout),
        source_artifact_ref=source_artifact_ref,
    )


def emit_part(
    name: str,
    *,
    project_root: Path,
    explicit_kerf_mm: float | None = None,
) -> Cut2dProgram:
    """Emit a 2D cut-file from a part's current published build.

    Process comes from the build's §5.2 metadata. Kerf comes from the DFM pack
    of that process when the pack declares ``kerf_mm``. The blank is
    ``part.blank_size`` when it parses, otherwise a tight rectangle around the
    extracted profiles.
    """
    from hephaestus.core.executor.artifact_geometry import load_brep_shape
    from hephaestus.core.project_store.layout import load_project, open_store
    from hephaestus.core.project_store.publication import Publisher
    from hephaestus.core.project_store.store import blob_hash_of_ref
    from hephaestus.core.registry import RegistrySet

    layout = load_project(project_root)
    if name not in layout.part_names():
        raise AddressingError(
            f"unknown part {name!r}",
            selector=name,
            candidates=layout.part_names(),
        )
    store = open_store(layout)
    try:
        result = Publisher(layout, store).current_result(name)
        if result is None or result.artifact_ref is None:
            raise CamRefusal(
                "not_built",
                f"part {name!r} has no current successful build to emit from; "
                f"run 'heph build {name}'",
                data={"part": name},
            )
        process = (result.metadata.get("process") or "").strip()
        if not process:
            raise CamRefusal(
                "no_process",
                f"part {name!r} declares no part.process; 2D CAM is process-specific "
                f"and is never guessed (candidates: {', '.join(CUT2D_PROCESSES)})",
                data={"part": name, "candidates": list(CUT2D_PROCESSES)},
            )
        registries = RegistrySet.open(project_root)
        pack_kerf, unavailable = pack_kerf_of(process, registries.dfm)
        blank_size = (result.metadata.get("blank_size") or "").strip()
        blank = blank_from_metadata(blank_size) if blank_size else None
        blob = blob_hash_of_ref(result.artifact_ref)
        if not store.blobs.has(blob):
            raise CamRefusal(
                "missing_artifact",
                f"artifact {result.artifact_ref} is not durably stored",
                data={"part": name, "artifact_ref": result.artifact_ref},
            )
        shape = load_brep_shape(store.blobs.get(blob))
        return emit_cut2d(
            shape,
            process=process,
            part=name,
            explicit_kerf_mm=explicit_kerf_mm,
            pack_kerf_mm=pack_kerf,
            unavailable=unavailable,
            blank=blank,
            source_artifact_ref=result.artifact_ref,
        )
    finally:
        store.close()
