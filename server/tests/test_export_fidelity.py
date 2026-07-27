"""Production-format fidelity: DXF cut-file layers and 3MF per-solid objects.

Two things a shop actually needs, pinned end to end through the real dispatcher
over a real project:

* **DXF layer conventions.** A laser controller maps layer (or colour) to a
  power/speed pair, so a cut file has to say which contour is a through-cut,
  which is a marking and which is a score. This module asserts that the exported
  DXF re-parses with ezdxf onto ``CUT``/``ENGRAVE``/``SCORE``/``BLANK``, that
  each contour is on the layer the part's **own** ``engrave_*``/``score_*`` tags
  put it on, that every layer carries its standard ACI colour, and — the
  failure that scraps material — that a part which tagged nothing emits no empty
  ``ENGRAVE``/``SCORE`` layer at all.
* **3MF fidelity.** 3MF's whole advantage over STL is that a build is a set of
  *named objects*. This module asserts one ``<object>`` per labelled solid with
  the label as its name, every object referenced by ``<build>``, model metadata
  carrying the part's §5.2 fields (material included), ``unit="millimeter"``,
  and a single-solid part still producing a valid one-object package.

Everything is re-read from the bytes that were written — zipfile + ElementTree
for the 3MF, ezdxf for the DXF — never from the writer's own opinion of them.
"""

from __future__ import annotations

import importlib
import io
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from hephaestus.core.cutfile import (
    BLANK_LAYER,
    CUT_LAYER,
    ENGRAVE_LAYER,
    LAYER_COLORS,
    SCORE_LAYER,
    layer_for_tag,
)
from hephaestus.testing.tools_fixture import Project, make_project

#: A sheet part carrying both kinds of non-cut geometry the convention names:
#: a shallow pocket whose floor is tagged ``engrave_*`` (so its contour is a
#: marking, not an opening) and an interior edge tagged ``score_*``.
MARKED_SRC = """PARAMS = {"t": Param(6.0, min=3.0, max=12.0)}

_blank = Box(80.0, 60.0, p.t)
_pocket = Pos(10.0, 5.0, p.t / 2.0) * Box(20.0, 10.0, p.t)
_panel = _blank - _pocket
_panel.label = "panel"
part.geometry = Compound(children=[_panel])

_floor = _panel.faces().filter_by(Axis.Z).sort_by(SortBy.AREA)[0]
tag(_floor, "engrave_pocket")
tag(_floor.edges().sort_by(Axis.Y)[0], "score_fold")

part.description = "Laser-cut panel with an engraved pocket and a score line"
part.material_spec = "6 mm Baltic birch plywood"
part.process = "laser_cut"
part.stock_form = "sheet"
part.blank_size = "One 210 x 125 x 6 mm blank"
"""

#: The same shape with nothing tagged: no marking geometry exists, so no
#: ENGRAVE/SCORE layer may exist either.
PLAIN_SRC = """PARAMS = {"t": Param(6.0, min=3.0, max=12.0)}

_panel = Box(80.0, 60.0, p.t)
_panel.label = "panel"
part.geometry = Compound(children=[_panel])

part.description = "Plain laser-cut panel"
part.process = "laser_cut"
part.stock_form = "sheet"
part.blank_size = "One 210 x 125 x 6 mm blank"
"""

#: Two separately labelled solids — the box-and-lid case a merged 3MF mesh
#: destroys.
ASSEMBLY_SRC = """PARAMS = {"w": Param(40.0, min=10.0, max=100.0)}

_box = Box(p.w, 30.0, 20.0)
_box.label = "enclosure_box"
_lid = Pos(0.0, 0.0, 25.0) * Box(p.w, 30.0, 4.0)
_lid.label = "enclosure_lid"
part.geometry = Compound(children=[_box, _lid])

part.description = "Two-piece printed enclosure"
part.material_spec = "PETG"
part.process = "fdm"
"""

#: One solid, one object: the degenerate case must still be a valid package.
SINGLE_SRC = """PARAMS = {"w": Param(20.0, min=5.0, max=50.0)}

_knob = Box(p.w, p.w, 10.0)
_knob.label = "knob"
part.geometry = _knob

part.description = "Single-solid knob"
"""

_3MF_NS = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"


def _project(tmp_path: Path, name: str, source: str) -> Iterator[Project]:
    project = make_project(tmp_path / f"proj-{name}")
    (project.root / "parts" / f"{name}.py").write_text(source, encoding="utf-8")
    try:
        assert project.call("build_part", {"name": name})["status"] == "ok"
        yield project
    finally:
        project.close()


@pytest.fixture
def marked(tmp_path: Path) -> Iterator[Project]:
    yield from _project(tmp_path, "panel", MARKED_SRC)


@pytest.fixture
def plain(tmp_path: Path) -> Iterator[Project]:
    yield from _project(tmp_path, "panel", PLAIN_SRC)


@pytest.fixture
def assembly(tmp_path: Path) -> Iterator[Project]:
    yield from _project(tmp_path, "enclosure", ASSEMBLY_SRC)


@pytest.fixture
def single(tmp_path: Path) -> Iterator[Project]:
    yield from _project(tmp_path, "knob", SINGLE_SRC)


def _export(project: Project, name: str, **arguments: Any) -> bytes:
    payload: dict[str, Any] = {"name": name, "format": "dxf", "layout": "as_built"}
    payload.update(arguments)
    entry = payload.pop("entry", None)
    result = dict(project.call("export_part", payload, entry=entry))
    assert len(result["paths"]) == 1
    return (project.root / str(result["paths"][0])).read_bytes()


def _read_dxf(data: bytes, path: Path) -> Any:
    """Re-parse exported bytes with ezdxf (untyped: confined to an ``Any``)."""
    path.write_bytes(data)
    ezdxf: Any = importlib.import_module("ezdxf")
    return ezdxf.readfile(str(path))


def _layer_names(document: Any) -> set[str]:
    return {str(layer.dxf.name) for layer in document.layers}


def _entities(document: Any, layer: str) -> list[Any]:
    return list(document.modelspace().query(f'*[layer=="{layer}"]'))


def _rings(document: Any, layer: str) -> list[list[tuple[float, float]]]:
    return [
        [(float(point[0]), float(point[1])) for point in entity.get_points()]
        for entity in document.modelspace().query(f'LWPOLYLINE[layer=="{layer}"]')
    ]


def _extent(ring: list[tuple[float, float]]) -> tuple[float, float]:
    xs = [x for x, _ in ring]
    ys = [y for _, y in ring]
    return (max(xs) - min(xs), max(ys) - min(ys))


def _area(ring: list[tuple[float, float]]) -> float:
    total = 0.0
    for index, (x0, y0) in enumerate(ring):
        x1, y1 = ring[(index + 1) % len(ring)]
        total += x0 * y1 - x1 * y0
    return abs(total) / 2.0


# ==========================================================================
# the layer convention itself


def test_layer_for_tag_is_a_prefix_rule_and_nothing_else() -> None:
    """Assignment is by documented prefix — never a guess about geometry."""
    assert layer_for_tag("engrave_logo") == ENGRAVE_LAYER
    assert layer_for_tag("score_fold_a") == SCORE_LAYER
    # A bare prefix names no feature, and everything unrecognised is a cut.
    assert layer_for_tag("engrave_") is None
    assert layer_for_tag("tread_top") is None
    assert layer_for_tag("ENGRAVE_LOGO") is None


# ==========================================================================
# nested_sheet DXF


def test_nested_sheet_separates_cut_engrave_and_score(marked: Project, tmp_path: Path) -> None:
    """Each contour lands on the layer the part's own tags put it on."""
    document = _read_dxf(_export(marked, "panel", layout="nested_sheet"), tmp_path / "marked.dxf")
    assert {BLANK_LAYER, CUT_LAYER, ENGRAVE_LAYER, SCORE_LAYER} <= _layer_names(document)

    # The perimeter is the only through-cut: the pocket opening was tagged, so
    # it moved to ENGRAVE rather than being cut out of the panel. The cut path
    # may carry a kerf allowance, so it is measured to within a whole millimetre.
    cut = _rings(document, CUT_LAYER)
    assert len(cut) == 1
    assert _extent(cut[0]) == pytest.approx((80.0, 60.0), abs=1.0)

    # The marking is *not* kerf compensated — a marking pass removes no
    # material — so the engraved contour is the nominal pocket, exactly.
    engrave = _rings(document, ENGRAVE_LAYER)
    assert len(engrave) == 1
    assert _area(engrave[0]) == pytest.approx(20.0 * 10.0, rel=1e-3)

    # A score line is a path, not a ring: closing it would cut a slot.
    scores = _entities(document, SCORE_LAYER)
    assert len(scores) == 1
    assert not scores[0].closed


def test_every_emitted_layer_carries_its_standard_colour(marked: Project, tmp_path: Path) -> None:
    """Controllers that key on colour rather than name read the same intent."""
    document = _read_dxf(_export(marked, "panel", layout="nested_sheet"), tmp_path / "colour.dxf")
    for layer in (BLANK_LAYER, CUT_LAYER, ENGRAVE_LAYER, SCORE_LAYER):
        assert int(document.layers.get(layer).color) == LAYER_COLORS[layer]


def test_an_untagged_part_emits_no_empty_marking_layers(plain: Project, tmp_path: Path) -> None:
    """An empty layer invites a power setting that fires on nothing."""
    document = _read_dxf(_export(plain, "panel", layout="nested_sheet"), tmp_path / "plain.dxf")
    names = _layer_names(document)
    assert {BLANK_LAYER, CUT_LAYER} <= names
    assert ENGRAVE_LAYER not in names
    assert SCORE_LAYER not in names
    assert len(_rings(document, CUT_LAYER)) == 1


def test_as_built_dxf_uses_the_same_convention(marked: Project, tmp_path: Path) -> None:
    """The as-built projection is a cut file too, on the same layers."""
    document = _read_dxf(_export(marked, "panel"), tmp_path / "as-built.dxf")
    names = _layer_names(document)
    assert CUT_LAYER in names
    assert _entities(document, CUT_LAYER), "the projected outline must be on CUT"
    assert int(document.layers.get(CUT_LAYER).color) == LAYER_COLORS[CUT_LAYER]
    assert {ENGRAVE_LAYER, SCORE_LAYER} <= names
    assert _entities(document, ENGRAVE_LAYER)
    assert _entities(document, SCORE_LAYER)


def test_as_built_dxf_of_an_untagged_part_has_only_the_cut_layer(
    plain: Project, tmp_path: Path
) -> None:
    names = _layer_names(_read_dxf(_export(plain, "panel"), tmp_path / "plain-built.dxf"))
    assert CUT_LAYER in names
    assert ENGRAVE_LAYER not in names
    assert SCORE_LAYER not in names


def test_nested_sheet_svg_classes_match_the_dxf_layers(marked: Project, tmp_path: Path) -> None:
    """The SVG twin of a cut file separates the same contours the same way."""
    data = _export(marked, "panel", format="svg", layout="nested_sheet")
    root = ET.fromstring(data.decode("utf-8"))
    classes = [element.get("class") for element in root.iter() if element.get("class")]
    assert classes.count(CUT_LAYER) == 1
    assert classes.count(ENGRAVE_LAYER) == 1
    assert classes.count(SCORE_LAYER) == 1
    # An open score line is a polyline, never a polygon.
    scored = [e for e in root.iter() if e.get("class") == SCORE_LAYER]
    assert scored[0].tag.endswith("polyline")


# ==========================================================================
# 3MF


def _model(data: bytes) -> ET.Element:
    """The ``3D/3dmodel.model`` XML of a 3MF package, re-read from the bytes."""
    assert zipfile.is_zipfile(io.BytesIO(data))
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = set(archive.namelist())
        assert {"[Content_Types].xml", "_rels/.rels", "3D/3dmodel.model"} <= names
        return ET.fromstring(archive.read("3D/3dmodel.model").decode("utf-8"))


def _objects(model: ET.Element) -> list[ET.Element]:
    return list(model.iter(f"{_3MF_NS}object"))


def _metadata(model: ET.Element) -> dict[str, str]:
    return {
        str(entry.get("name")): (entry.text or "") for entry in model.iter(f"{_3MF_NS}metadata")
    }


def test_3mf_emits_one_object_per_labelled_solid(assembly: Project) -> None:
    """A box and its lid export as a two-object build, not one merged mesh."""
    model = _model(_export(assembly, "enclosure", format="3mf"))
    assert model.get("unit") == "millimeter"
    objects = _objects(model)
    assert [obj.get("name") for obj in objects] == ["enclosure_box", "enclosure_lid"]
    for obj in objects:
        assert list(obj.iter(f"{_3MF_NS}triangle")), "every object carries its own mesh"


def test_3mf_build_references_every_object(assembly: Project) -> None:
    """An object no build item names is a part the consumer never places."""
    model = _model(_export(assembly, "enclosure", format="3mf"))
    declared = [obj.get("id") for obj in _objects(model)]
    placed = [item.get("objectid") for item in model.iter(f"{_3MF_NS}item")]
    assert declared == placed
    assert len(placed) == 2


def test_3mf_carries_the_parts_metadata(assembly: Project) -> None:
    """Title/Designer/Description/Application plus the declared material."""
    metadata = _metadata(_model(_export(assembly, "enclosure", format="3mf")))
    assert metadata["Title"] == "enclosure"
    assert metadata["Designer"]
    assert metadata["Description"] == "Two-piece printed enclosure"
    assert metadata["Application"] == "Hephaestus"
    assert metadata["heph:Material"] == "PETG"
    assert metadata["heph:Process"] == "fdm"


def test_3mf_of_a_single_solid_part_is_still_one_valid_object(single: Project) -> None:
    model = _model(_export(single, "knob", format="3mf"))
    objects = _objects(model)
    assert len(objects) == 1
    assert objects[0].get("name") == "knob"
    assert [item.get("objectid") for item in model.iter(f"{_3MF_NS}item")] == [objects[0].get("id")]
    assert list(objects[0].iter(f"{_3MF_NS}vertex"))


def test_3mf_is_deterministic(assembly: Project) -> None:
    """Two exports of the same build produce identical bytes."""
    first = _export(assembly, "enclosure", format="3mf", target="a.3mf", entry="3mf-a")
    second = _export(assembly, "enclosure", format="3mf", target="b.3mf", entry="3mf-b")
    assert first == second
