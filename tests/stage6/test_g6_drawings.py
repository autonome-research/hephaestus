# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""G6: the drawing clause — a dimensioned sheet a shop can read off.

Gate clause: *"drawings for the reference shelf render to PDF whose extracted
dimension strings include the five principal dimensions (pytest + pdf text
extraction)"*.

The fixture is a shelf-class part with three solids (a deck on two side panels)
and one 8 mm cable bore, so its five principal dimensions are known by
construction: 600 x 250 x 218 mm overall, 18.0 mm material thickness and a
Ø8.0 bore. The evidence is deliberately read back with **pypdf** — an
independent PDF reader, not the engine's own extractor — so a sheet whose
dimensions were baked into the rendered raster instead of a text layer fails
here, which is the whole content of the clause.

The exhaustive drawing/document coverage (SVG parity, exploded views, BOM rows,
export pinning) lives in ``server/tests/test_drawings_docs.py``; this module is
the gate evidence.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from typing import Any, cast

import pytest
from _g6 import G6Project, make_g6_project
from hephaestus.agent_bridge.cad_ops import dimension_text
from pypdf import PdfReader

#: The five principal dimensions of the shelf fixture, as printed strings.
PRINCIPAL: dict[str, str] = {
    "overall_x": dimension_text(600.0, "linear"),
    "overall_y": dimension_text(250.0, "linear"),
    "overall_z": dimension_text(218.0, "linear"),
    "thickness": dimension_text(18.0, "thickness"),
    "bore_1": dimension_text(8.0, "diameter"),
}


@pytest.fixture(scope="module")
def project(tmp_path_factory: pytest.TempPathFactory) -> Iterator[G6Project]:
    scaffolded = make_g6_project(
        tmp_path_factory.mktemp("g6-drawing") / "proj", ("shelf",), secure=False
    )
    try:
        yield scaffolded
    finally:
        scaffolded.close()


@pytest.fixture(scope="module")
def built(project: G6Project) -> str:
    return project.build("shelf")


@pytest.fixture(scope="module")
def dimensioned(project: G6Project, built: str) -> dict[str, Any]:
    return dict(project.call("generate_drawing", {"name": "shelf", "kind": "dimensioned"}))


def _pdf_text(data: bytes) -> str:
    """What an independent reader extracts from the sheet's text layer."""
    return "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(data)).pages)


def test_the_shelf_fixture_really_is_multi_solid(project: G6Project, built: str) -> None:
    """A one-solid part would make the dimension set trivially small."""
    result = project.cad.current_build("shelf")
    assert result is not None
    geometries = cast("Any", result).geometries
    assert {str(row.label) for row in geometries} == {"deck", "side", "side#2"}
    assert sum(int(row.solids) for row in geometries) == 3
    assert built.startswith("artifact:")


def test_the_dimensioned_sheet_extracts_to_the_five_principal_dimensions(
    project: G6Project, dimensioned: dict[str, Any], built: str
) -> None:
    assert dimensioned["kind"] == "dimensioned"
    assert dimensioned["source_artifact_ref"] == built

    measured = {
        str(d["id"]): str(d["text"])
        for d in cast("list[dict[str, Any]]", dimensioned["dimensions"])
    }
    for identifier, printed in PRINCIPAL.items():
        assert measured.get(identifier) == printed, f"{identifier}: measured {measured}"

    text = _pdf_text(project.read(str(dimensioned["pdf"])))
    for identifier, printed in PRINCIPAL.items():
        assert printed in text, f"{identifier} ({printed}) is not in the PDF text layer"


def test_every_dimension_on_the_sheet_is_text_not_raster(
    project: G6Project, dimensioned: dict[str, Any]
) -> None:
    """Not only the five: nothing the tool claims to have drawn is rasterized."""
    text = _pdf_text(project.read(str(dimensioned["pdf"])))
    for dimension in cast("list[dict[str, Any]]", dimensioned["dimensions"]):
        assert str(dimension["text"]) in text, f"{dimension['id']} missing from the text layer"
        assert str(dimension["label"]) in text


def test_the_sheet_states_the_material_and_the_bytes_it_describes(
    project: G6Project, dimensioned: dict[str, Any], built: str
) -> None:
    """A drawing is a manufacturing document: it says what, and from which build."""
    block = cast("dict[str, Any]", dimensioned["title_block"])
    assert block["material_spec"] == "18 mm Baltic birch plywood"
    assert block["process"] == "laser_cut"
    assert block["source_artifact_ref"] == built
    assert str(block["script_hash"]).startswith("sha256:")

    text = _pdf_text(project.read(str(dimensioned["pdf"])))
    for value in ("18 mm Baltic birch plywood", "laser_cut", "MATERIAL", "PROCESS"):
        assert value in text


def test_a_drawing_of_a_different_build_carries_that_builds_dimensions(
    project: G6Project, built: str
) -> None:
    """The sheet is bound to an artifact, not to "the part" as of drawing time."""
    preview = project.build("shelf", {"width": 800.0})
    assert preview != built
    sheet = dict(
        project.call(
            "generate_drawing",
            {"name": "shelf", "kind": "dimensioned", "artifact_ref": preview},
        )
    )
    assert sheet["source_artifact_ref"] == preview
    measured = {
        str(d["id"]): str(d["text"]) for d in cast("list[dict[str, Any]]", sheet["dimensions"])
    }
    assert measured["overall_x"] == dimension_text(800.0, "linear")
    text = _pdf_text(project.read(str(sheet["pdf"])))
    assert dimension_text(800.0, "linear") in text
    assert PRINCIPAL["overall_x"] not in text, "the preview sheet reprints the current build"
