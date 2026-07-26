"""Stage 6 drawings and documents: what the PDF/SVG/markdown actually carry.

The fixture is a three-solid laser-cut shelf with a bore, full §5.2 metadata and
a material that resolves in the materials registry — enough for every claim
``generate_drawing`` and ``generate_doc`` make to be checkable:

* the dimensioned sheet's PDF **text layer** carries the principal dimension
  strings and the title-block values (extracted with pypdf — a rasterized
  dimension would fail here, which is the point);
* the SVG variant is well-formed XML carrying the same annotations;
* the exploded sheet's rendered view differs from the assembled one;
* the BOM lists every labeled solid group with its registry material, and the
  assembly document's steps are ordered by phase and are reproducible;
* both files of both tools are pinned exports whose recorded hashes are the
  hashes of the bytes on disk.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import pytest
from hephaestus.agent_bridge.cad_ops import CadOpError, CadOps
from hephaestus.agent_bridge.dispatch import DispatchError, Principal, ToolDispatcher
from hephaestus.core.project_store.layout import ProjectLayout, load_project, open_store
from hephaestus.core.project_store.store import ProjectStore
from pypdf import PdfReader

from opstore import OpStore

SHELF_SRC = """PARAMS = {
    "width": Param(600.0, min=200.0, max=1200.0),
}

t = 18.0
deck = Box(p.width, 250.0, t)
bore = Cylinder(radius=4.0, height=t * 4)
deck = deck - bore
deck.label = "deck"
left = Pos(-p.width / 2 + t / 2, 0, -100.0) * Box(t, 250.0, 200.0)
left.label = "side"
right = Pos(p.width / 2 - t / 2, 0, -100.0) * Box(t, 250.0, 200.0)
right.label = "side"
part.geometry = Compound(children=[deck, left, right])

part.description = "Cat step shelf, deck plus two sides"
part.material_spec = "18 mm Baltic birch plywood"
part.process = "laser_cut"
part.general_tolerance = "+/-0.25 mm cut profile"
part.finish = "sanded, hardwax oiled"
part.assembly_method = "glued finger joints"
part.joint = "finger"
part.blank_size = "1200 x 600 mm sheet"

CHECKS = {
    "deck_is_wide_enough": lambda m: m.bbox("part")[0] >= 400.0,
}
"""

BRACKET_SRC = """body = Box(40.0, 20.0, 6.0)
body.label = "bracket_body"
part.geometry = body
part.description = "Reference bracket"
part.process = "laser_cut"
"""

ORCH = Principal(session_id="orch", profile="orchestrator", part=None)


class Project:
    """A built shelf project plus the ops object and dispatcher under test."""

    def __init__(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        (root / "parts").mkdir(exist_ok=True)
        (root / "checks").mkdir(exist_ok=True)
        (root / "hephaestus.toml").write_text('[project]\nname = "catstep"\n', encoding="utf-8")
        (root / "globals.py").write_text("PARAMS = {}\n", encoding="utf-8")
        (root / "parts" / "shelf.py").write_text(SHELF_SRC, encoding="utf-8")
        (root / "parts" / "bracket.py").write_text(BRACKET_SRC, encoding="utf-8")
        self.root = root
        self.layout: ProjectLayout = load_project(root)
        self.store: OpStore = open_store(self.layout)
        self.cad = CadOps(self.layout, self.store)
        self.dispatcher = ToolDispatcher(ProjectStore(self.layout, self.store), cad=self.cad)
        assert self.cad.build_part("shelf", op_id="build-shelf")["status"] == "ok"

    def call(self, tool: str, arguments: dict[str, Any], *, entry: str) -> Any:
        return self.dispatcher.dispatch(
            ORCH,
            {
                "session_id": "orch",
                "run_id": "run-1",
                "tool": tool,
                "arguments": arguments,
                "invocation": {
                    "session_id": "orch",
                    "entry_id": entry,
                    "ordinal": 1,
                    "provider_call_id": "call_0",
                },
            },
        )

    def read(self, rel_path: str) -> bytes:
        return (self.root / rel_path).read_bytes()

    def close(self) -> None:
        self.store.close()


@pytest.fixture(scope="module")
def project(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Project]:
    p = Project(tmp_path_factory.mktemp("drawings") / "proj")
    try:
        yield p
    finally:
        p.close()


@pytest.fixture(scope="module")
def dimensioned(project: Project) -> dict[str, Any]:
    return dict(
        project.call(
            "generate_drawing", {"name": "shelf", "kind": "dimensioned"}, entry="drw-dimensioned"
        )
    )


@pytest.fixture(scope="module")
def bom(project: Project) -> dict[str, Any]:
    return dict(project.call("generate_doc", {"name": "shelf", "kind": "bom"}, entry="doc-bom"))


def pdf_text(data: bytes) -> str:
    import io

    return "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(data)).pages)


def svg_texts(data: bytes) -> list[str]:
    root = ElementTree.fromstring(data.decode("utf-8"))
    ns = "{http://www.w3.org/2000/svg}"
    return [node.text or "" for node in root.iter(f"{ns}text")]


def svg_images(data: bytes) -> list[bytes]:
    hrefs = re.findall(r'xlink:href="data:image/png;base64,([^"]+)"', data.decode("utf-8"))
    return [base64.b64decode(href) for href in hrefs]


# ==========================================================================
# generate_drawing


def test_dimensioned_pdf_text_layer_carries_every_principal_dimension(
    project: Project, dimensioned: dict[str, Any]
) -> None:
    text = pdf_text(project.read(dimensioned["pdf"]))
    dimensions = dimensioned["dimensions"]
    # The five principal dimensions of this shelf: three overall extents, the
    # sheet thickness measured off opposing faces, and the bore diameter.
    principal = {d["id"]: d["text"] for d in dimensions}
    assert principal["overall_x"] == "600.0"
    assert principal["overall_y"] == "250.0"
    assert principal["overall_z"] == "209.0"
    assert principal["thickness"] == "18.0"
    assert principal["bore_1"] == "Ø8.0"
    for dimension in dimensions:
        assert dimension["text"] in text, f"{dimension['id']} missing from the PDF text layer"
        assert dimension["label"] in text


def test_dimensioned_pdf_carries_the_title_block_from_part_metadata(
    project: Project, dimensioned: dict[str, Any]
) -> None:
    text = pdf_text(project.read(dimensioned["pdf"]))
    block = dimensioned["title_block"]
    assert block["project"] == "catstep"
    assert block["material_spec"] == "18 mm Baltic birch plywood"
    assert block["process"] == "laser_cut"
    assert block["general_tolerance"] == "+/-0.25 mm cut profile"
    assert block["finish"] == "sanded, hardwax oiled"
    assert block["source_artifact_ref"] == dimensioned["source_artifact_ref"]
    assert block["script_hash"].startswith("sha256:")
    for caption in ("PROJECT", "PART", "DESCRIPTION", "MATERIAL", "PROCESS", "TOLERANCE", "FINISH"):
        assert caption in text
    for value in block.values():
        assert value in text


def test_svg_variant_is_xml_with_the_same_annotations(
    project: Project, dimensioned: dict[str, Any]
) -> None:
    data = project.read(dimensioned["svg"])
    texts = svg_texts(data)
    for dimension in dimensioned["dimensions"]:
        assert dimension["text"] in texts
        assert dimension["label"] in texts
    for value in dimensioned["title_block"].values():
        assert value in texts
    # The views are embedded, not referenced: an SVG that needs a sidecar PNG is
    # not a deliverable.
    assert svg_images(data), "no view is embedded in the SVG"


def test_exploded_view_differs_from_the_assembled_one(project: Project) -> None:
    assembled = project.call(
        "generate_drawing", {"name": "shelf", "kind": "assembly"}, entry="drw-assembly"
    )
    exploded = project.call(
        "generate_drawing", {"name": "shelf", "kind": "exploded"}, entry="drw-exploded"
    )
    assert assembled["views"] == exploded["views"] == ["iso", "+Z"]
    first = svg_images(project.read(assembled["svg"]))
    second = svg_images(project.read(exploded["svg"]))
    assert first and len(first) == len(second)
    assert first[0] != second[0], "the exploded isometric renders identically to the assembled one"
    # Same geometry, so the dimensions are unchanged: only the view exploded.
    assert [d["text"] for d in assembled["dimensions"]] == [
        d["text"] for d in exploded["dimensions"]
    ]


def test_drawing_outputs_are_pinned_exports_with_provenance_hashes(
    project: Project, dimensioned: dict[str, Any]
) -> None:
    assert dimensioned["paths"] == [dimensioned["pdf"], dimensioned["svg"]]
    assert dimensioned["source_artifact_ref"].startswith("artifact:build:")
    assert dimensioned["source_input_hashes"]["script"].startswith("sha256:")
    pins = project.store.gc.pins()
    for path in dimensioned["paths"]:
        rel = Path(path).relative_to(Path(".heph") / "exports").as_posix()
        recorded = dimensioned["export_hashes"][rel]
        data = project.read(path)
        assert recorded == "sha256:" + hashlib.sha256(data).hexdigest()
        assert recorded in pins


def test_drawing_retry_on_the_same_invocation_replays_the_whole_result(
    project: Project, dimensioned: dict[str, Any]
) -> None:
    again = project.call(
        "generate_drawing", {"name": "shelf", "kind": "dimensioned"}, entry="drw-dimensioned"
    )
    assert again["replayed"] is True
    assert again["paths"] == dimensioned["paths"]
    assert again["dimensions"] == dimensioned["dimensions"]
    assert again["title_block"] == dimensioned["title_block"]


def test_regenerating_the_same_sheet_is_byte_identical(project: Project) -> None:
    """Content-addressed names collide, which is the determinism proof.

    A fresh invocation renders the same artifact again; the output stem is the
    digest of the produced bytes, so a create-only collision can only happen if
    the PDF and SVG came out byte-for-byte identical. Non-deterministic
    composition would quietly write a second file instead.
    """
    with pytest.raises(DispatchError) as excinfo:
        project.call(
            "generate_drawing", {"name": "shelf", "kind": "dimensioned"}, entry="drw-again"
        )
    assert excinfo.value.reason == "target_exists"


def test_drawing_target_names_both_files_and_is_create_only(project: Project) -> None:
    out = project.call(
        "generate_drawing",
        {"name": "shelf", "kind": "assembly", "sheet": "A3", "target": "sheets/shelf-a3"},
        entry="drw-target",
    )
    assert out["pdf"] == str(Path(".heph") / "exports" / "sheets" / "shelf-a3.pdf")
    assert out["svg"] == str(Path(".heph") / "exports" / "sheets" / "shelf-a3.svg")
    assert out["sheet"] == "A3"
    with pytest.raises(DispatchError) as excinfo:
        project.call(
            "generate_drawing",
            {"name": "shelf", "kind": "assembly", "sheet": "A3", "target": "sheets/shelf-a3"},
            entry="drw-target-2",
        )
    assert excinfo.value.reason == "target_exists"


def test_a_refused_multi_file_export_leaves_no_half_deliverable(project: Project) -> None:
    """A colliding second file rolls the first one back, so a retry is possible."""
    exports = project.layout.exports_dir / "partial"
    exports.mkdir(parents=True, exist_ok=True)
    (exports / "shelf.svg").write_bytes(b"someone else's file")
    with pytest.raises(DispatchError) as excinfo:
        project.call(
            "generate_drawing",
            {"name": "shelf", "kind": "assembly", "target": "partial/shelf"},
            entry="drw-partial",
        )
    assert excinfo.value.reason == "target_exists"
    assert not (exports / "shelf.pdf").exists()


def test_drawing_refuses_an_unknown_kind_before_freezing_anything(project: Project) -> None:
    with pytest.raises(CadOpError) as excinfo:
        project.cad.generate_drawing("shelf", "isometric", op_id="drw-bad")
    assert excinfo.value.reason == "invalid_params"


def test_drawing_refuses_a_part_with_no_current_build(project: Project) -> None:
    with pytest.raises(DispatchError) as excinfo:
        project.call(
            "generate_drawing", {"name": "bracket", "kind": "dimensioned"}, entry="drw-unbuilt"
        )
    assert excinfo.value.reason == "invalid_part"


# ==========================================================================
# generate_doc


def test_bom_lists_every_labeled_solid_with_its_registry_material(
    project: Project, bom: dict[str, Any]
) -> None:
    body = json.loads(project.read(bom["json"]).decode("utf-8"))
    rows = body["rows"]
    assert [row["label"] for row in rows] == ["deck", "side"]
    assert [row["quantity"] for row in rows] == [1, 2]
    assert sum(row["quantity"] for row in rows) == 3  # every solid of the compound
    for row in rows:
        assert row["material_spec"] == "18 mm Baltic birch plywood"
        assert row["material_id"] == "plywood-baltic-birch"
        assert row["density_kg_m3"] > 0
        assert row["registry_digest"].startswith("sha256:")
        assert row["stock"] == "1200 x 600 mm sheet"
        assert row["mass_g"] > 0
    assert body["total_mass_g"] == pytest.approx(sum(row["mass_g"] for row in rows), rel=1e-6)
    markdown = project.read(bom["doc"]).decode("utf-8")
    assert "| deck | 1 |" in markdown
    assert "| side | 2 |" in markdown
    assert "Baltic birch plywood" in markdown
    assert bom["items"] == 2


def test_bom_says_so_when_a_material_spec_resolves_to_nothing(project: Project) -> None:
    path = project.root / "parts" / "shelf.py"
    original = path.read_text(encoding="utf-8")
    path.write_text(
        original.replace('"18 mm Baltic birch plywood"', '"unobtainium honeycomb"'),
        encoding="utf-8",
    )
    try:
        project.cad.build_part("shelf", op_id="build-unobtainium")
        out = project.cad.generate_doc("shelf", "bom", op_id="doc-unobtainium")
        body = json.loads(project.read(out["json"]).decode("utf-8"))
        assert all(row["material_id"] is None for row in body["rows"])
        assert all(row["mass_g"] is None for row in body["rows"])
        assert "no registry match" in out["markdown"]
    finally:
        path.write_text(original, encoding="utf-8")
        project.cad.build_part("shelf", op_id="build-restore")


def test_assembly_doc_orders_steps_deterministically(project: Project) -> None:
    first = project.call(
        "generate_doc", {"name": "shelf", "kind": "assembly_instructions"}, entry="doc-asm-1"
    )
    second = project.call(
        "generate_doc",
        {"name": "shelf", "kind": "assembly_instructions", "target": "docs/shelf-asm"},
        entry="doc-asm-2",
    )
    body = json.loads(project.read(first["json"]).decode("utf-8"))
    steps = body["steps"]
    assert [step["phase"] for step in steps] == [
        "fabricate",
        "fabricate",
        "prepare",
        "prepare",
        "assemble",
        "finish",
    ]
    assert steps[0]["text"].startswith("Laser-cut 1 x deck at 600.0 x 250.0 x 18.0 mm")
    assert steps[1]["refers_to"] == ["side"]
    assert "glued finger joints" in steps[4]["text"]
    # Same evidence, same document: a second generation is byte-identical.
    assert json.loads(project.read(second["json"]).decode("utf-8"))["steps"] == steps
    assert second["markdown"] == first["markdown"]


def test_spec_doc_reports_params_metrics_and_checks_of_the_frozen_build(
    project: Project,
) -> None:
    out = project.call("generate_doc", {"name": "shelf", "kind": "spec"}, entry="doc-spec")
    body = json.loads(project.read(out["json"]).decode("utf-8"))
    assert body["params"] == {"width": 600.0}
    assert body["metrics"]["solids"] == 3
    assert body["checks"]["deck_is_wide_enough"]["pass"] is True
    assert body["metadata"]["joint"] == "finger"
    assert "## Checks" in out["markdown"]


def test_doc_outputs_are_pinned_exports_with_provenance_hashes(
    project: Project, bom: dict[str, Any]
) -> None:
    assert bom["paths"] == [bom["doc"], bom["json"]]
    assert bom["doc"].endswith(".md") and bom["json"].endswith(".json")
    assert bom["source_input_hashes"]["script"].startswith("sha256:")
    pins = project.store.gc.pins()
    for path in bom["paths"]:
        rel = Path(path).relative_to(Path(".heph") / "exports").as_posix()
        recorded = bom["export_hashes"][rel]
        assert recorded == "sha256:" + hashlib.sha256(project.read(path)).hexdigest()
        assert recorded in pins


def test_doc_refuses_an_unknown_kind(project: Project) -> None:
    with pytest.raises(CadOpError) as excinfo:
        project.cad.generate_doc("shelf", "datasheet", op_id="doc-bad")
    assert excinfo.value.reason == "invalid_params"
