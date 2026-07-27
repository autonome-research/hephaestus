"""Sheet nesting: flat profiles laid out on one declared blank (Stage 6).

``export_part(layout="nested_sheet")`` turns a built sheet part into the file a
laser or router actually consumes: every solid's flat profile, positioned on a
declared blank, written as DXF or SVG.

Three deliberately small pieces, each pure and testable on its own:

* :func:`flat_profiles` — one :class:`Profile` per solid of a built shape. A
  sheet part is prismatic, so its flat pattern is its **largest planar face**;
  the face's outer wire (and its inner wires, which are cut contours too) is
  taken in the face's own plane, canonicalised to counter-clockwise winding
  with the outer ring's bounding box at the origin, and discretised (straight
  edges keep their endpoints, curved edges are sampled at a
  :data:`CURVE_SEGMENT_MM` chord — a cut file is a polyline).
* :func:`shelf_nest` — **simple deterministic shelf/row packing**, in profile
  order, no rotation. Rotation- and yield-aware auto-nesting is deferred by
  mission rule 5; this is the honest, reproducible placeholder and is documented
  as such in ``tool_schema.md``. A profile that cannot be placed raises
  :class:`NestingRefusal` naming the profile and the blank — never a silent
  overlap and never a clipped part.

* :func:`layout_to_dxf` / :func:`layout_to_svg` — the bytes. Both are pure
  functions of the layout: coordinates are rounded to :data:`COORD_DECIMALS`
  and written in placement order, so two exports of the same build produce
  identical geometry bytes (DXF additionally carries ezdxf's own generated
  header, which is not content). Geometry is separated onto the cut-file layers
  :mod:`hephaestus.core.cutfile` defines — ``CUT``/``ENGRAVE``/``SCORE`` plus
  the reference ``BLANK`` — with the standard ACI colour per layer, because a
  laser controller maps layer (or colour) to a power/speed pair.

**Kerf compensation happens upstream of everything here**
(:mod:`hephaestus.core.kerf`): the exporter grows each solid's flat pattern onto
the waste side by half the kerf *before* profiles are extracted, so the profiles
this module packs are already the path the machine follows and the blank's
declared spacing is measured between compensated outlines.

Nothing here touches the store, the sandbox or the network: the caller resolves
the artifact and the blank and hands over bytes and numbers.
"""

from __future__ import annotations

import ast
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, cast

from hephaestus.core.cutfile import (
    BLANK_LAYER,
    COORD_DECIMALS,
    CURVE_SEGMENT_MM,
    CUT_LAYER,
    CUTFILE_LAYERS,
    ENGRAVE_LAYER,
    LAYER_COLORS,
    LAYER_SVG_COLORS,
    MAX_CURVE_SEGMENTS,
    MIN_CURVE_SEGMENTS,
    SCORE_LAYER,
    Mark,
    Point,
    ring_points,
    solid_marks,
)
from hephaestus.core.dfm.types import TopologyDescriptor
from hephaestus.core.errors import ValidationError
from hephaestus.core.kernel.topology import planar_faces
from opstore.types import JSONValue

__all__ = [
    "BLANK_LAYER",
    "COORD_DECIMALS",
    "CURVE_SEGMENT_MM",
    "CUT_LAYER",
    "DEFAULT_MARGIN_MM",
    "DEFAULT_SPACING_MM",
    "ENGRAVE_LAYER",
    "LAYER_COLORS",
    "MAX_CURVE_SEGMENTS",
    "MIN_CURVE_SEGMENTS",
    "PROFILE_LAYER",
    "SCORE_LAYER",
    "Blank",
    "Mark",
    "NestedLayout",
    "NestingRefusal",
    "Placement",
    "Profile",
    "blank_from_metadata",
    "blank_size_literal",
    "flat_profiles",
    "layout_layers",
    "layout_to_dxf",
    "layout_to_svg",
    "shelf_nest",
]

#: Default clear border between the blank edge and any profile.
DEFAULT_MARGIN_MM: Final[float] = 5.0
#: Default clear gap between two placed profiles.
DEFAULT_SPACING_MM: Final[float] = 5.0

#: Historical name for the through-cut layer. Profiles have always been the cut
#: geometry; since the cut-file layer convention landed the layer is called
#: ``CUT`` (what a controller expects) and this alias names the same layer.
PROFILE_LAYER: Final[str] = CUT_LAYER

_EPS: Final[float] = 1e-9


class NestingRefusal(Exception):
    """A profile could not be placed; ``data`` names the profile and the blank."""

    def __init__(self, reason: str, message: str, *, data: dict[str, JSONValue]) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.data = data


@dataclass(frozen=True)
class Blank:
    """The stock rectangle profiles are nested on, in millimetres."""

    width_mm: float
    height_mm: float
    margin_mm: float = DEFAULT_MARGIN_MM
    spacing_mm: float = DEFAULT_SPACING_MM

    def __post_init__(self) -> None:
        if not (self.width_mm > 0.0 and self.height_mm > 0.0):
            raise ValidationError(
                f"blank must have positive width and height (got {self.width_mm} x "
                f"{self.height_mm})",
                kind="contract",
            )
        if self.margin_mm < 0.0 or self.spacing_mm < 0.0:
            raise ValidationError(
                f"blank margin/spacing must not be negative (got margin {self.margin_mm}, "
                f"spacing {self.spacing_mm})",
                kind="contract",
            )

    @property
    def usable_width_mm(self) -> float:
        return self.width_mm - 2.0 * self.margin_mm

    @property
    def usable_height_mm(self) -> float:
        return self.height_mm - 2.0 * self.margin_mm

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "width_mm": self.width_mm,
            "height_mm": self.height_mm,
            "margin_mm": self.margin_mm,
            "spacing_mm": self.spacing_mm,
        }


@dataclass(frozen=True)
class Profile:
    """One solid's flat pattern: a closed ring with its bbox at the origin.

    ``holes`` are the face's inner boundaries in the same coordinates — they are
    cut contours too, and a file that dropped them would cut a solid part where
    the design has openings. Packing only ever considers ``points`` (the outer
    ring), which is what occupies space on the blank.

    ``marks`` are the profile's non-cut contours — the engrave and score
    geometry the part's own ``engrave_*``/``score_*`` tags declare
    (:mod:`hephaestus.core.cutfile`). They travel with the profile so a
    placement moves them with it, and they never affect packing: a marking pass
    removes no material and occupies no space the outer ring does not already.
    """

    name: str
    points: tuple[Point, ...]
    holes: tuple[tuple[Point, ...], ...] = ()
    marks: tuple[Mark, ...] = ()

    def __post_init__(self) -> None:
        if len(self.points) < 3:
            raise ValidationError(
                f"profile {self.name!r} has fewer than three points", kind="contract"
            )

    @property
    def width_mm(self) -> float:
        return max(x for x, _ in self.points) - min(x for x, _ in self.points)

    @property
    def height_mm(self) -> float:
        return max(y for _, y in self.points) - min(y for _, y in self.points)

    @property
    def area_mm2(self) -> float:
        """Absolute shoelace area of the closed ring."""
        total = 0.0
        count = len(self.points)
        for index in range(count):
            x0, y0 = self.points[index]
            x1, y1 = self.points[(index + 1) % count]
            total += x0 * y1 - x1 * y0
        return abs(total) / 2.0

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "name": self.name,
            "width_mm": self.width_mm,
            "height_mm": self.height_mm,
            "area_mm2": self.area_mm2,
            "holes": len(self.holes),
            "marks": {
                layer: sum(1 for mark in self.marks if mark.layer == layer)
                for layer in (ENGRAVE_LAYER, SCORE_LAYER)
                if any(mark.layer == layer for mark in self.marks)
            },
        }


@dataclass(frozen=True)
class Placement:
    """A profile translated onto the blank by ``(x_mm, y_mm)``."""

    profile: Profile
    x_mm: float
    y_mm: float

    def _translate(self, ring: tuple[Point, ...]) -> tuple[Point, ...]:
        return tuple(
            (
                round(x + self.x_mm, COORD_DECIMALS),
                round(y + self.y_mm, COORD_DECIMALS),
            )
            for x, y in ring
        )

    def points(self) -> tuple[Point, ...]:
        """The placed outer ring."""
        return self._translate(self.profile.points)

    def hole_points(self) -> tuple[tuple[Point, ...], ...]:
        """The placed inner rings (cut contours inside the profile)."""
        return tuple(self._translate(ring) for ring in self.profile.holes)

    def marks(self) -> tuple[Mark, ...]:
        """The placed engrave/score contours, in the profile's own order."""
        return tuple(
            Mark(layer=mark.layer, points=self._translate(mark.points), closed=mark.closed)
            for mark in self.profile.marks
        )

    def bbox(self) -> tuple[float, float, float, float]:
        """``(min_x, min_y, max_x, max_y)`` of the placed profile."""
        return (
            self.x_mm,
            self.y_mm,
            self.x_mm + self.profile.width_mm,
            self.y_mm + self.profile.height_mm,
        )

    def to_json(self) -> dict[str, JSONValue]:
        return {"profile": self.profile.name, "x_mm": self.x_mm, "y_mm": self.y_mm}


@dataclass(frozen=True)
class NestedLayout:
    """Every profile placed on one blank, in placement order."""

    blank: Blank
    placements: tuple[Placement, ...]

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "blank": self.blank.to_json(),
            "profiles": [placement.profile.to_json() for placement in self.placements],
            "placements": [placement.to_json() for placement in self.placements],
        }


# --------------------------------------------------------------------------
# blank declaration


_SIZE_RE: Final[re.Pattern[str]] = re.compile(
    r"(\d+(?:\.\d+)?)\s*[xX\u00d7]\s*(\d+(?:\.\d+)?)",
)


def blank_size_literal(source: str) -> str | None:
    """The ``part.blank_size = "..."`` string literal of a part script, if any.

    Read statically (``ast``): the export never re-executes a script, and the
    caller only trusts the answer when the script's hash still matches the
    artifact it is exporting.
    """
    try:
        module = ast.parse(source)
    except SyntaxError:
        return None
    for node in ast.walk(module):
        if not isinstance(node, ast.Assign):
            continue
        value = node.value
        if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
            continue
        for target in node.targets:
            if (
                isinstance(target, ast.Attribute)
                and target.attr == "blank_size"
                and isinstance(target.value, ast.Name)
                and target.value.id == "part"
            ):
                return value.value
    return None


def blank_from_metadata(
    blank_size: str,
    *,
    margin_mm: float = DEFAULT_MARGIN_MM,
    spacing_mm: float = DEFAULT_SPACING_MM,
) -> Blank | None:
    """A :class:`Blank` from a free-text ``part.blank_size``, or None.

    ``part.blank_size`` is free text by contract (§5.2) — "Three 210 x 125 x
    6 mm nested profiles". The first ``W x H`` pair in it is the blank; a string
    with no such pair yields None so the caller can refuse explicitly instead of
    guessing a stock size.
    """
    match = _SIZE_RE.search(blank_size)
    if match is None:
        return None
    width = float(match.group(1))
    height = float(match.group(2))
    if width <= 0.0 or height <= 0.0:
        return None
    return Blank(width_mm=width, height_mm=height, margin_mm=margin_mm, spacing_mm=spacing_mm)


# --------------------------------------------------------------------------
# profile extraction


def _signed_area(points: list[Point]) -> float:
    total = 0.0
    count = len(points)
    for index in range(count):
        x0, y0 = points[index]
        x1, y1 = points[(index + 1) % count]
        total += x0 * y1 - x1 * y0
    return total / 2.0


def _largest_planar_face(solid: Any) -> Any | None:
    records = planar_faces(solid)
    if not records:
        return None
    best = min(records, key=lambda record: (-record.area, record.index))
    return list(solid.faces())[best.index]


def _solid_sort_key(solid: Any) -> tuple[float, float, float, float]:
    box = solid.bounding_box()
    return (
        round(float(box.min.X), COORD_DECIMALS),
        round(float(box.min.Y), COORD_DECIMALS),
        round(float(box.min.Z), COORD_DECIMALS),
        -round(float(solid.volume), COORD_DECIMALS),
    )


def flat_profiles(
    shape: Any,
    *,
    prefix: str = "profile",
    tags: Mapping[str, TopologyDescriptor] | None = None,
    tag_shape: Any | None = None,
) -> tuple[Profile, ...]:
    """One flat :class:`Profile` per solid of ``shape``, deterministically ordered.

    Solids are ordered by bounding-box minimum then descending volume (a
    reloaded BRep has no labels to order by), and each profile is named
    ``"<prefix>_<n>"`` in that order. A solid with no planar face — nothing
    flat to cut — is refused rather than approximated. The face's inner
    boundaries travel with the profile as :attr:`Profile.holes`: they are cut
    contours, not decoration.

    ``tags`` is the build's tag table (``descriptors_from_source_map``), keyed
    by §5.3 tag name and addressed against the artifact's *own* ``solids()``
    order. Tags named by the :mod:`hephaestus.core.cutfile` convention
    (``engrave_*``, ``score_*``) become the profile's :attr:`Profile.marks`,
    projected into the flat pattern's plane. A mark that lands **inside** an
    inner boundary reclassifies it — a tagged engrave pocket is a marking, not
    a through-cut *and* a marking — and a mark spanning the whole outer ring is
    dropped, because the perimeter is always cut. Without ``tags`` every contour
    is a through-cut, which is the safe reading of a part that declared nothing.

    ``tag_shape`` is where those descriptors are resolved, when it is not
    ``shape`` itself. Kerf compensation rebuilds each flat pattern, so the
    source map's topology indices address the **nominal** artifact and nothing
    else; passing the nominal shape here keeps a part's engrave and score
    geometry alive through a compensated export instead of silently losing it.
    The contours are still expressed in the *packed* profile's plane and shifted
    by the *packed* outline's origin, so mark and cut path stay in one rigid
    frame — the compensated path is offset from the nominal outline, and the
    marking is not, which is exactly right: a marking removes no material.
    """
    from build123d import Plane

    descriptors = dict(tags or {})
    # Descriptors address the artifact's own solids() order; the flat pattern
    # re-sorts for determinism, so carry each solid's original index with it.
    numbered: list[tuple[int, Any]] = list(enumerate(cast("list[Any]", shape.solids())))
    indexed = sorted(numbered, key=lambda item: _solid_sort_key(item[1]))
    tag_solids: list[Any] = [] if tag_shape is None else cast("list[Any]", tag_shape.solids())
    if tag_shape is not None and len(tag_solids) != len(numbered):
        # The nominal shape must partition the same way, or a descriptor's
        # solid id names different geometry. Refuse the tags, not the export.
        descriptors = {}
        tag_solids = []
    if not tag_solids:
        tag_shape = None
    if not indexed:
        raise NestingRefusal(
            "no_profiles",
            "the exported artifact contains no solids to nest",
            data={"profiles": []},
        )
    profiles: list[Profile] = []
    for index, (origin, solid) in enumerate(indexed, start=1):
        name = f"{prefix}_{index}"
        face = _largest_planar_face(solid)
        if face is None:
            raise NestingRefusal(
                "not_a_sheet_profile",
                f"{name} has no planar face: it has no flat pattern to nest",
                data={"profile": name},
            )
        plane: Any = Plane(face)
        local: Any = plane.to_local_coords(face.outer_wire())
        points = ring_points(local)
        if len(points) < 3:
            raise NestingRefusal(
                "not_a_sheet_profile",
                f"{name} has a degenerate outer boundary",
                data={"profile": name},
            )
        if _signed_area(points) < 0.0:
            points.reverse()
        min_x = min(x for x, _ in points)
        min_y = min(y for _, y in points)

        def _normalized(
            ring: list[Point], dx: float = min_x, dy: float = min_y
        ) -> tuple[Point, ...]:
            return tuple(
                (round(x - dx, COORD_DECIMALS), round(y - dy, COORD_DECIMALS)) for x, y in ring
            )

        holes: list[tuple[Point, ...]] = []
        for inner in face.inner_wires():
            ring = ring_points(plane.to_local_coords(inner))
            if len(ring) < 3:
                continue
            if _signed_area(ring) < 0.0:
                ring.reverse()
            holes.append(_normalized(ring))
        outer = _normalized(points)
        tagged = solid if tag_shape is None else tag_solids[origin]
        marks = tuple(
            Mark(layer=mark.layer, points=_normalized(list(mark.points)), closed=mark.closed)
            for mark in solid_marks(tagged, descriptors, origin, plane=plane)
        )
        marks, holes = _reconcile_marks(marks, holes, outer)
        profiles.append(
            Profile(
                name=name,
                points=outer,
                holes=tuple(sorted(holes)),
                marks=marks,
            )
        )
    return tuple(profiles)


def _reconcile_marks(
    marks: tuple[Mark, ...],
    holes: list[tuple[Point, ...]],
    outer: tuple[Point, ...],
) -> tuple[tuple[Mark, ...], list[tuple[Point, ...]]]:
    """Resolve a mark that lands on geometry the cut layer already carries.

    A tagged engrave pocket's floor projects onto the same opening the flat
    pattern would otherwise cut through, and a tag on the flat face itself
    projects onto the perimeter. Emitting both would either cut a marking
    (scrap) or double-fire the perimeter, so:

    * a closed mark whose centroid falls **inside** an inner boundary takes
      that boundary off the cut layer — the part's own tag says it is a
      marking, not an opening;
    * a closed mark that spans the outer ring is dropped — the perimeter is the
      through-cut by definition and nothing may move it.

    Containment is tested on the centroid rather than on point equality because
    kerf compensation moves the cut path off the nominal contour by half a kerf:
    the two rings describe the same feature and are no longer the same points.
    """
    kept_marks: list[Mark] = []
    kept_holes = list(holes)
    outer_box = _ring_bbox(outer)
    for mark in marks:
        if not mark.closed:
            kept_marks.append(mark)
            continue
        if _covers(_ring_bbox(mark.points), outer_box):
            continue
        centre = _ring_centre(mark.points)
        kept_holes = [ring for ring in kept_holes if not _inside(centre, _ring_bbox(ring))]
        kept_marks.append(mark)
    return tuple(kept_marks), kept_holes


def _ring_bbox(ring: tuple[Point, ...]) -> tuple[float, float, float, float]:
    xs = [x for x, _ in ring]
    ys = [y for _, y in ring]
    return (min(xs), min(ys), max(xs), max(ys))


def _ring_centre(ring: tuple[Point, ...]) -> Point:
    box = _ring_bbox(ring)
    return ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)


def _inside(point: Point, box: tuple[float, float, float, float]) -> bool:
    return box[0] <= point[0] <= box[2] and box[1] <= point[1] <= box[3]


_Box = tuple[float, float, float, float]


def _covers(box: _Box, other: _Box) -> bool:
    """``box`` reaches the whole of ``other`` (within a kerf-scale tolerance)."""
    tolerance = 1.0
    return (
        abs(box[0] - other[0]) <= tolerance
        and abs(box[1] - other[1]) <= tolerance
        and abs(box[2] - other[2]) <= tolerance
        and abs(box[3] - other[3]) <= tolerance
    )


# --------------------------------------------------------------------------
# packing


def shelf_nest(profiles: tuple[Profile, ...], blank: Blank) -> NestedLayout:
    """Left-to-right shelf packing of ``profiles`` onto one ``blank``.

    Deterministic and deliberately simple (mission rule 5 defers kerf-aware
    auto-nesting): profiles keep their given order and orientation, fill a row
    until the next one would cross the right margin, then start a new row above
    the tallest profile of the row just closed. Nothing is rotated, nothing is
    reordered, nothing overlaps.

    Raises :class:`NestingRefusal` — ``profile_too_large`` when a profile cannot
    fit the blank at all, ``blank_full`` when the rows ran out of height.
    """
    if not profiles:
        raise NestingRefusal(
            "no_profiles", "there are no profiles to nest", data={"blank": blank.to_json()}
        )
    placements: list[Placement] = []
    cursor_x = blank.margin_mm
    row_y = blank.margin_mm
    row_height = 0.0
    for profile in profiles:
        width = profile.width_mm
        height = profile.height_mm
        if width > blank.usable_width_mm + _EPS or height > blank.usable_height_mm + _EPS:
            raise NestingRefusal(
                "profile_too_large",
                f"profile {profile.name!r} is {width:.3f} x {height:.3f} mm and does not fit "
                f"the {blank.width_mm:.3f} x {blank.height_mm:.3f} mm blank with a "
                f"{blank.margin_mm:.3f} mm margin",
                data={"profile": profile.to_json(), "blank": blank.to_json()},
            )
        if placements and cursor_x + width > blank.width_mm - blank.margin_mm + _EPS:
            row_y += row_height + blank.spacing_mm
            cursor_x = blank.margin_mm
            row_height = 0.0
        if row_y + height > blank.height_mm - blank.margin_mm + _EPS:
            raise NestingRefusal(
                "blank_full",
                f"profile {profile.name!r} ({width:.3f} x {height:.3f} mm) has no room left on "
                f"the {blank.width_mm:.3f} x {blank.height_mm:.3f} mm blank "
                f"({len(placements)} profile(s) already placed)",
                data={
                    "profile": profile.to_json(),
                    "blank": blank.to_json(),
                    "placed": [placement.to_json() for placement in placements],
                },
            )
        placements.append(
            Placement(
                profile=profile,
                x_mm=round(cursor_x, COORD_DECIMALS),
                y_mm=round(row_y, COORD_DECIMALS),
            )
        )
        cursor_x += width + blank.spacing_mm
        row_height = max(row_height, height)
    return NestedLayout(blank=blank, placements=tuple(placements))


# --------------------------------------------------------------------------
# writers


def layout_layers(layout: NestedLayout) -> tuple[str, ...]:
    """The cut-file layers this layout actually carries geometry on.

    ``BLANK`` and ``CUT`` are always present (a nested sheet always draws the
    stock rectangle and at least one profile); ``ENGRAVE`` and ``SCORE`` appear
    only when a part tagged topology onto them. An empty layer in a controller's
    job list is an invitation to assign it a power setting, so none is written.
    """
    used = {mark.layer for placement in layout.placements for mark in placement.profile.marks}
    return tuple(
        layer for layer in CUTFILE_LAYERS if layer in (BLANK_LAYER, CUT_LAYER) or layer in used
    )


def layout_to_dxf(layout: NestedLayout) -> bytes:
    """The layout as a DXF on the cut-file layers a laser controller reads.

    Through-cuts (every profile's outer ring and its holes) go on ``CUT``, the
    stock rectangle on ``BLANK``, and the part's tagged marking geometry on
    ``ENGRAVE``/``SCORE`` — each layer carrying its standard ACI colour
    (:data:`hephaestus.core.cutfile.LAYER_COLORS`), because a controller keys
    power and speed off layer or colour. Layers with no geometry are not
    written at all. Closed contours are ``LWPOLYLINE``\\ s with the close flag;
    a score line tagged on an edge is an *open* polyline, so nothing joins its
    ends into a slot the design does not have.

    The bytes are a pure function of the layout. ezdxf otherwise stamps a fresh
    creation timestamp and two random GUIDs into every document it writes, so
    this pins its ``write_fixed_meta_data_for_testing`` switch for the duration
    of the write and restores it afterwards — an export that cannot be
    reproduced byte for byte is not evidence.
    """
    import importlib
    import io

    # ezdxf's public names are re-exports its stubs do not mark as such, so the
    # interop surface is confined to these deliberately ``Any``-typed locals
    # (the same discipline the build123d exporters get in the export module).
    ezdxf: Any = importlib.import_module("ezdxf")
    stream = io.StringIO()
    # The switch must be on for *both* halves: ezdxf stamps a creation
    # timestamp when the document is created and a written-at timestamp plus
    # two random GUIDs when it is serialized.
    restore = bool(ezdxf.options.write_fixed_meta_data_for_testing)
    ezdxf.options.write_fixed_meta_data_for_testing = True
    try:
        document: Any = ezdxf.new(dxfversion="R2010", setup=False)
        document.header["$INSUNITS"] = 4  # millimetres
        for layer in layout_layers(layout):
            document.layers.add(layer, color=LAYER_COLORS[layer])
        modelspace: Any = document.modelspace()
        blank = layout.blank
        modelspace.add_lwpolyline(
            [
                (0.0, 0.0),
                (blank.width_mm, 0.0),
                (blank.width_mm, blank.height_mm),
                (0.0, blank.height_mm),
            ],
            close=True,
            dxfattribs={"layer": BLANK_LAYER},
        )
        for placement in layout.placements:
            for ring in (placement.points(), *placement.hole_points()):
                modelspace.add_lwpolyline(
                    list(ring),
                    close=True,
                    dxfattribs={"layer": CUT_LAYER},
                )
            for mark in placement.marks():
                modelspace.add_lwpolyline(
                    list(mark.points),
                    close=mark.closed,
                    dxfattribs={"layer": mark.layer},
                )
        document.write(stream)
    finally:
        ezdxf.options.write_fixed_meta_data_for_testing = restore
    return stream.getvalue().encode("utf-8")


def _svg_number(value: float) -> str:
    rounded = round(value, COORD_DECIMALS)
    if math.isclose(rounded, round(rounded), abs_tol=10.0**-COORD_DECIMALS):
        return str(round(rounded))
    return f"{rounded:.6f}".rstrip("0")


def layout_to_svg(layout: NestedLayout) -> bytes:
    """The layout as an SVG: one element per contour, classed by cut-file layer.

    Each profile's outer ring is id'd by profile name and each of its holes
    ``<name>_hole_<n>``; both are ``<polygon>`` on ``class="CUT"``. Tagged
    marking geometry follows as ``<name>_engrave_<n>`` / ``<name>_score_<n>``
    on ``class="ENGRAVE"``/``"SCORE"``, closed marks as ``<polygon>`` and open
    ones as ``<polyline>`` so a score line stays a line. Stroke colour matches
    the DXF's ACI colour per layer. SVG's Y axis points down, so every point is
    mirrored about the blank's mid-height; the file therefore reads the same way
    as the DXF when opened.
    """
    blank = layout.blank
    width = _svg_number(blank.width_mm)
    height = _svg_number(blank.height_mm)
    lines: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}mm" height="{height}mm" '
        f'viewBox="0 0 {width} {height}">',
        f'<rect class="{BLANK_LAYER}" x="0" y="0" width="{width}" height="{height}" '
        f'fill="none" stroke="{LAYER_SVG_COLORS[BLANK_LAYER]}" stroke-width="0.25"/>',
    ]

    def _points(ring: tuple[Point, ...]) -> str:
        return " ".join(f"{_svg_number(x)},{_svg_number(blank.height_mm - y)}" for x, y in ring)

    for placement in layout.placements:
        name = placement.profile.name
        for ring_id, ring in [
            (name, placement.points()),
            *(
                (f"{name}_hole_{index}", ring)
                for index, ring in enumerate(placement.hole_points(), start=1)
            ),
        ]:
            lines.append(
                f'<polygon class="{CUT_LAYER}" id="{ring_id}" points="{_points(ring)}" '
                f'fill="none" stroke="{LAYER_SVG_COLORS[CUT_LAYER]}" stroke-width="0.25"/>'
            )
        counters: dict[str, int] = {}
        for mark in placement.marks():
            counters[mark.layer] = counters.get(mark.layer, 0) + 1
            mark_id = f"{name}_{mark.layer.lower()}_{counters[mark.layer]}"
            element = "polygon" if mark.closed else "polyline"
            lines.append(
                f'<{element} class="{mark.layer}" id="{mark_id}" points="{_points(mark.points)}" '
                f'fill="none" stroke="{LAYER_SVG_COLORS[mark.layer]}" stroke-width="0.25"/>'
            )
    lines.append("</svg>")
    return ("\n".join(lines) + "\n").encode("utf-8")
