"""``export_part(layout="nested_sheet")``: flat profiles nested on one blank.

Stage 6 turns the reserved ``nested_sheet`` layout into a real cut file. What
this module pins, end to end through the real dispatcher over a real project:

* a three-solid sheet part nests onto its **declared** blank and the DXF
  re-parses (ezdxf) into three closed polylines whose areas are the source
  faces' areas;
* no two placed profiles overlap — checked pairwise on the parsed geometry, not
  on the layout the writer believed in;
* a profile too large for the blank is a **structured refusal** naming the
  profile and the blank, never a silent overlap and never a clipped part;
* two exports of the same build are byte-identical (deterministic shelf
  packing, deterministic writer);
* the SVG variant parses as XML and carries the same profile count.
"""

from __future__ import annotations

import importlib
import math
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from hephaestus.agent_bridge.cad_ops import CadOpError
from hephaestus.agent_bridge.dispatch import DispatchError
from hephaestus.core.nesting import (
    BLANK_LAYER,
    PROFILE_LAYER,
    Blank,
    NestingRefusal,
    Profile,
    blank_from_metadata,
    blank_size_literal,
    shelf_nest,
)
from hephaestus.testing.tools_fixture import Project, make_project

#: Three prismatic 6 mm laminations — the shape a laser actually cuts. Their
#: flat patterns are 90x55, 70x40 and 50x30 mm.
SHEET_SRC = """PARAMS = {"t": Param(6.0, min=3.0, max=12.0)}

_a = Pos(0.0, 0.0, 0.0) * Box(90.0, 55.0, p.t)
_a.label = "front"
_b = Pos(200.0, 0.0, 0.0) * Box(70.0, 40.0, p.t)
_b.label = "side"
_c = Pos(0.0, 200.0, 0.0) * Box(50.0, 30.0, p.t)
_c.label = "gusset"
part.geometry = Compound(children=[_a, _b, _c])

part.description = "Three-lamination laser-cut sheet fixture"
part.process = "laser_cut"
part.stock_form = "sheet"
part.blank_size = "Three 210 x 125 x 6 mm nested profiles"
"""

#: Areas of the three flat patterns, in mm^2.
EXPECTED_AREAS: tuple[float, ...] = (90.0 * 55.0, 70.0 * 40.0, 50.0 * 30.0)


@pytest.fixture
def sheet(tmp_path: Path) -> Iterator[Project]:
    """A project whose ``sheet`` part is built and declares its blank."""
    project = make_project(tmp_path / "proj")
    (project.root / "parts" / "sheet.py").write_text(SHEET_SRC, encoding="utf-8")
    try:
        assert project.call("build_part", {"name": "sheet"})["status"] == "ok"
        yield project
    finally:
        project.close()


def _export(project: Project, **arguments: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": "sheet", "format": "dxf", "layout": "nested_sheet"}
    payload.update(arguments)
    entry = payload.pop("entry", None)
    return dict(project.call("export_part", payload, entry=entry))


def _exported_bytes(project: Project, result: dict[str, Any]) -> bytes:
    assert len(result["paths"]) == 1
    return (project.root / str(result["paths"][0])).read_bytes()


def _read_dxf(data: bytes, path: Path) -> Any:
    """Re-parse exported bytes with ezdxf (untyped: confined to an ``Any``)."""
    path.write_bytes(data)
    ezdxf: Any = importlib.import_module("ezdxf")
    return ezdxf.readfile(str(path))


def _rings(document: Any, layer: str) -> list[list[tuple[float, float]]]:
    """The closed polylines of one layer, as point rings."""
    rings: list[list[tuple[float, float]]] = []
    for entity in document.modelspace().query(f'LWPOLYLINE[layer=="{layer}"]'):
        assert entity.closed, "a nested profile must be a CLOSED polyline"
        rings.append([(float(point[0]), float(point[1])) for point in entity.get_points()])
    return rings


def _polygons(data: bytes, path: Path) -> list[list[tuple[float, float]]]:
    """The ``PROFILES``-layer closed polylines of a DXF, as point rings."""
    return _rings(_read_dxf(data, path), PROFILE_LAYER)


def _area(ring: list[tuple[float, float]]) -> float:
    total = 0.0
    for index, (x0, y0) in enumerate(ring):
        x1, y1 = ring[(index + 1) % len(ring)]
        total += x0 * y1 - x1 * y0
    return abs(total) / 2.0


def _bbox(ring: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    xs = [x for x, _ in ring]
    ys = [y for _, y in ring]
    return (min(xs), min(ys), max(xs), max(ys))


# ==========================================================================
# the nested DXF


def test_declared_blank_nests_three_profiles(sheet: Project, tmp_path: Path) -> None:
    """G6: the declared 210x125 blank carries the part's three flat profiles."""
    result = _export(sheet)
    assert result["source_artifact_ref"].startswith("artifact:build:")
    assert str(result["paths"][0]).endswith(".dxf")
    rings = _polygons(_exported_bytes(sheet, result), tmp_path / "read.dxf")
    assert len(rings) == 3
    assert sorted(round(_area(ring), 3) for ring in rings) == sorted(EXPECTED_AREAS)
    # Every profile lies inside the declared blank, margins included.
    for ring in rings:
        min_x, min_y, max_x, max_y = _bbox(ring)
        assert min_x >= 5.0 - 1e-6 and min_y >= 5.0 - 1e-6
        assert max_x <= 205.0 + 1e-6 and max_y <= 120.0 + 1e-6


def test_the_blank_outline_is_its_own_layer(sheet: Project, tmp_path: Path) -> None:
    """The reference rectangle is on ``BLANK`` so a cutter can drop it."""
    document = _read_dxf(_exported_bytes(sheet, _export(sheet)), tmp_path / "layers.dxf")
    blanks = _rings(document, BLANK_LAYER)
    assert len(blanks) == 1
    assert _area(blanks[0]) == pytest.approx(210.0 * 125.0)


def test_placed_profiles_never_overlap(sheet: Project, tmp_path: Path) -> None:
    """Pairwise bounding boxes of the *parsed* geometry are disjoint."""
    rings = _polygons(_exported_bytes(sheet, _export(sheet)), tmp_path / "overlap.dxf")
    boxes = [_bbox(ring) for ring in rings]
    for first in range(len(boxes)):
        for second in range(first + 1, len(boxes)):
            a = boxes[first]
            b = boxes[second]
            disjoint = (
                a[2] <= b[0] + 1e-9
                or b[2] <= a[0] + 1e-9
                or (a[3] <= b[1] + 1e-9 or b[3] <= a[1] + 1e-9)
            )
            assert disjoint, f"profiles {first} and {second} overlap: {a} vs {b}"


def test_export_is_byte_identical_across_two_runs(sheet: Project) -> None:
    """Determinism: same build, same blank, same bytes (ezdxf metadata pinned)."""
    first = _export(sheet, target="nest-a.dxf", entry="nest-a")
    second = _export(sheet, target="nest-b.dxf", entry="nest-b")
    assert _exported_bytes(sheet, first) == _exported_bytes(sheet, second)
    # Identical bytes hash identically: the content address is the proof.
    assert {*first["export_hashes"].values()} == {*second["export_hashes"].values()}


def test_an_explicit_blank_overrides_the_declared_one(sheet: Project, tmp_path: Path) -> None:
    """An explicit blank is the caller's declaration and wins over metadata."""
    result = _export(sheet, blank={"width_mm": 300.0, "height_mm": 300.0, "margin_mm": 10.0})
    document = _read_dxf(_exported_bytes(sheet, result), tmp_path / "explicit.dxf")
    assert _area(_rings(document, BLANK_LAYER)[0]) == pytest.approx(300.0 * 300.0)
    for profile_ring in _rings(document, PROFILE_LAYER):
        assert _bbox(profile_ring)[0] >= 10.0 - 1e-6


# ==========================================================================
# refusals


def test_an_oversized_profile_is_a_structured_refusal(sheet: Project) -> None:
    """No clipping, no overlap: the profile and the blank are both named."""
    with pytest.raises(DispatchError) as ei:
        _export(sheet, blank={"width_mm": 80.0, "height_mm": 60.0})
    assert ei.value.reason == "profile_too_large"
    data = ei.value.data
    assert data["profile"]["name"] == "sheet_1"
    assert data["profile"]["width_mm"] == pytest.approx(90.0)
    assert data["blank"]["width_mm"] == pytest.approx(80.0)
    assert "does not fit" in str(ei.value)
    # Nothing was written.
    exports = sheet.root / ".heph" / "exports"
    assert not exports.exists() or not list(exports.glob("*.dxf"))


def test_a_full_blank_is_a_structured_refusal(sheet: Project) -> None:
    """Rows that run out of height refuse, naming what could not be placed."""
    with pytest.raises(DispatchError) as ei:
        _export(sheet, blank={"width_mm": 100.0, "height_mm": 70.0, "margin_mm": 1.0})
    assert ei.value.reason == "blank_full"
    assert ei.value.data["profile"]["name"] == "sheet_2"
    assert ei.value.data["placed"]


def test_a_part_without_a_declared_blank_refuses(sheet: Project) -> None:
    """``widget`` declares no ``part.blank_size``; guessing stock is not allowed."""
    sheet.call("build_part", {"name": "widget"})
    with pytest.raises(DispatchError) as ei:
        sheet.call("export_part", {"name": "widget", "format": "dxf", "layout": "nested_sheet"})
    assert ei.value.reason == "blank_unknown"
    assert "blank" in str(ei.value)


def test_an_edited_script_no_longer_supplies_the_blank(sheet: Project) -> None:
    """Metadata is only trusted while the script still hashes to the artifact."""
    (sheet.root / "parts" / "sheet.py").write_text(
        SHEET_SRC.replace('part.blank_size = "Three 210 x 125 x 6 mm nested profiles"', ""),
        encoding="utf-8",
    )
    with pytest.raises(DispatchError) as ei:
        _export(sheet, entry="edited")
    assert ei.value.reason == "blank_unknown"


def test_nested_sheet_requires_a_flat_format(sheet: Project) -> None:
    """A nested layout is a cut file: STEP/GLTF/3MF/STL are refused."""
    with pytest.raises(CadOpError) as ei:
        sheet.cad.export_part(
            "sheet",
            "step",
            artifact_ref=None,
            target=None,
            layout="nested_sheet",
            blank=None,
            op_id="op-bad-format",
        )
    assert ei.value.reason == "invalid_params"


# ==========================================================================
# the SVG variant


def test_svg_variant_carries_the_same_profiles(sheet: Project) -> None:
    result = _export(sheet, format="svg")
    assert str(result["paths"][0]).endswith(".svg")
    data = _exported_bytes(sheet, result)
    root = ET.fromstring(data.decode("utf-8"))
    polygons = root.findall("{http://www.w3.org/2000/svg}polygon")
    assert len(polygons) == 3
    assert [polygon.get("id") for polygon in polygons] == ["sheet_1", "sheet_2", "sheet_3"]
    assert root.get("viewBox") == "0 0 210 125"
    # Deterministic here too.
    again = _export(sheet, format="svg", target="again.svg", entry="svg-2")
    assert _exported_bytes(sheet, again) == data


# ==========================================================================
# the pure nesting layer


def test_blank_size_metadata_parsing() -> None:
    assert blank_size_literal(SHEET_SRC) == "Three 210 x 125 x 6 mm nested profiles"
    parsed = blank_from_metadata("Three 210 x 125 x 6 mm nested profiles")
    assert parsed is not None
    assert (parsed.width_mm, parsed.height_mm) == (210.0, 125.0)
    assert blank_from_metadata("one sheet of plywood") is None
    assert blank_size_literal("part.description = 'no blank here'") is None


def test_shelf_packing_is_row_major_and_deterministic() -> None:
    square = Profile(name="p", points=((0.0, 0.0), (40.0, 0.0), (40.0, 40.0), (0.0, 40.0)))
    layout = shelf_nest((square, square, square), Blank(100.0, 100.0))
    positions = [(placement.x_mm, placement.y_mm) for placement in layout.placements]
    assert positions == [(5.0, 5.0), (50.0, 5.0), (5.0, 50.0)]
    assert shelf_nest((square, square, square), Blank(100.0, 100.0)).to_json() == layout.to_json()


def test_shelf_packing_refuses_rather_than_overlapping() -> None:
    wide = Profile(name="wide", points=((0.0, 0.0), (99.0, 0.0), (99.0, 10.0), (0.0, 10.0)))
    with pytest.raises(NestingRefusal) as ei:
        shelf_nest((wide,), Blank(100.0, 100.0))
    assert ei.value.reason == "profile_too_large"
    assert cast("dict[str, Any]", ei.value.data["profile"])["name"] == "wide"


HOLED_SRC = """_plate = Box(80.0, 60.0, 6.0)
_bore = Cylinder(10.0, 20.0)
plate = _plate - _bore
plate.label = "plate"
part.geometry = plate

part.description = "A plate with a bore, whose hole must reach the cut file"
part.process = "laser_cut"
part.blank_size = "One 210 x 125 x 6 mm profile"
"""


def test_a_hole_reaches_the_cut_file(tmp_path: Path) -> None:
    """Inner boundaries are cut contours: dropping them would cut a solid part."""
    project = make_project(tmp_path / "holed")
    try:
        (project.root / "parts" / "plate.py").write_text(HOLED_SRC, encoding="utf-8")
        assert project.call("build_part", {"name": "plate"})["status"] == "ok"
        result = project.call(
            "export_part", {"name": "plate", "format": "dxf", "layout": "nested_sheet"}
        )
        data = (project.root / str(result["paths"][0])).read_bytes()
        rings = _rings(_read_dxf(data, tmp_path / "holed.dxf"), PROFILE_LAYER)
        assert len(rings) == 2
        areas = sorted(_area(ring) for ring in rings)
        assert areas[1] == pytest.approx(80.0 * 60.0)
        assert areas[0] == pytest.approx(math.pi * 10.0**2, rel=0.005)
    finally:
        project.close()
