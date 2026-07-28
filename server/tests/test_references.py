"""``INGEST.md`` §2 references, end to end through the real dispatcher.

What is pinned here is the shape of the rule, not just the plumbing:

* registration is **operator-side** — ``heph reference add`` / the bench seeder —
  and the model surface is read-only. There is no ``add_reference`` tool, and the
  dispatcher refuses one by name;
* a document returns text extracted **at registration**, inside the provenance
  delimiters, under the §5 dual cap with a byte cursor that always advances;
* an image returns inline content that passed the §5 image header gate;
* a ledger ``cite`` must name a registered reference, and lint verifies a
  document citation against exactly the text ``read_reference`` returns;
* an image citation is lint-*unverifiable* and reaches the §5 reviewer, whose
  finding is recorded on the ``vision`` channel.
"""

from __future__ import annotations

import io
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from hephaestus.agent_bridge.cad_ops import CadOpError
from hephaestus.agent_bridge.dispatch import DispatchError
from hephaestus.agent_bridge.references_pdf import pdf_extractor
from hephaestus.core.errors import ValidationError
from hephaestus.core.project_store.references import (
    REFERENCE_REF_PREFIX,
    ReferenceCapabilityError,
    ReferenceRegistry,
)
from hephaestus.core.registry import REFERENCE_END, REFERENCE_START
from hephaestus.testing.tools_fixture import PART_WIDGET, Project, make_project

# --------------------------------------------------------------------------
# fixtures: real bytes, because the magic check and the §5 header gate are real


def pdf_bytes(*pages: str) -> bytes:
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    sheet = canvas.Canvas(buf)
    for text in pages:
        sheet.drawString(72, 720, text)
        sheet.showPage()
    sheet.save()
    return buf.getvalue()


def png_bytes(width: int = 8, height: int = 8) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (width, height), (200, 40, 40)).save(buf, format="PNG")
    return buf.getvalue()


SHEET_PAGE_1 = "Bore diameter 6.0 +/- 0.1 mm"
SHEET_PAGE_2 = "Plate thickness 3.0 mm"


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Project]:
    p = make_project(tmp_path / "proj", seed_ledger=False)
    try:
        yield p
    finally:
        p.close()


def registry(project: Project) -> ReferenceRegistry:
    return ReferenceRegistry(project.layout, project.store)


def register_sheet(project: Project, name: str = "sheet.pdf") -> Any:
    return registry(project).add_bytes(
        pdf_bytes(SHEET_PAGE_1, SHEET_PAGE_2), name=name, extractor=pdf_extractor()
    )


# ==========================================================================
# registration is operator-side


def test_add_file_copies_into_references_and_registers(project: Project, tmp_path: Path) -> None:
    source = tmp_path / "elsewhere" / "sheet2.pdf"
    source.parent.mkdir()
    source.write_bytes(pdf_bytes(SHEET_PAGE_1, SHEET_PAGE_2))

    entry = registry(project).add_file(source, extractor=pdf_extractor())

    assert entry.name == "sheet2.pdf"
    assert entry.kind == "document"
    assert entry.mime_type == "application/pdf"
    assert entry.pages == 2
    assert entry.artifact_ref.startswith(REFERENCE_REF_PREFIX)
    # The project carries its own copy, and the CAS carries the bytes a citation
    # was checked against — a later edit of the operator's file cannot rewrite it.
    assert (project.root / "references" / "sheet2.pdf").read_bytes() == source.read_bytes()
    assert registry(project).payload(entry) == source.read_bytes()


def test_registration_is_content_addressed_and_upserts_by_name(project: Project) -> None:
    payload = pdf_bytes(SHEET_PAGE_1, SHEET_PAGE_2)
    first = registry(project).add_bytes(payload, name="sheet.pdf", extractor=pdf_extractor())
    again = registry(project).add_bytes(payload, name="sheet.pdf", extractor=pdf_extractor())
    assert again.sha256 == first.sha256

    replaced = registry(project).add_bytes(
        pdf_bytes("Bore diameter 8.0 mm"), name="sheet.pdf", extractor=pdf_extractor()
    )
    assert replaced.sha256 != first.sha256
    listing = registry(project).list_references()
    assert [entry.name for entry in listing] == ["sheet.pdf"], "an upsert replaces, never appends"
    assert listing[0].pages == 1


def test_a_payload_contradicting_its_extension_is_refused(project: Project) -> None:
    with pytest.raises(ValidationError, match="does not look like image/png"):
        registry(project).add_bytes(b"%PDF-1.4 not a png", name="drawing.png")


def test_an_unsupported_extension_is_refused(project: Project) -> None:
    with pytest.raises(ValidationError, match="unsupported extension"):
        registry(project).add_bytes(b"...", name="model.step")


def test_a_traversing_name_is_refused(project: Project) -> None:
    with pytest.raises(ValidationError, match="one plain filename"):
        registry(project).add_bytes(b"hello", name="../escape.txt")


def test_a_pdf_without_an_extractor_reports_the_missing_capability(project: Project) -> None:
    # Core alone registers text/markdown/images; the pypdf parser is server-side,
    # so its absence is named rather than silently producing an empty document.
    with pytest.raises(ReferenceCapabilityError) as excinfo:
        registry(project).add_bytes(pdf_bytes(SHEET_PAGE_1), name="sheet.pdf")
    assert excinfo.value.reason == "capability_not_available"
    assert registry(project).list_references() == (), "nothing was written"


def test_removal_deregisters_and_deletes_the_copy(project: Project, tmp_path: Path) -> None:
    source = tmp_path / "sheet.pdf"
    source.write_bytes(pdf_bytes(SHEET_PAGE_1))
    registry(project).add_file(source, extractor=pdf_extractor())

    registry(project).remove("sheet.pdf")

    assert registry(project).list_references() == ()
    assert not (project.root / "references" / "sheet.pdf").exists()


# ==========================================================================
# the model cannot add one


def test_there_is_no_tool_that_adds_a_reference() -> None:
    from hephaestus.contract.tools_decl import tool_names

    names = set(tool_names())
    assert {"list_references", "read_reference"} <= names
    assert not {name for name in names if "reference" in name} - {
        "list_references",
        "read_reference",
    }


def test_dispatch_rejects_an_invented_add_reference_tool(project: Project) -> None:
    with pytest.raises(DispatchError) as excinfo:
        project.call("add_reference", {"path": "sheet.pdf"})
    assert excinfo.value.reason == "unknown_tool"


# ==========================================================================
# list_references / read_reference


def test_list_references_reports_kind_pages_and_hash(project: Project) -> None:
    register_sheet(project)
    registry(project).add_bytes(png_bytes(), name="photo.png")

    listing = cast("list[dict[str, Any]]", project.call("list_references", {}))

    assert [entry["name"] for entry in listing] == ["photo.png", "sheet.pdf"]
    photo, sheet = listing
    assert photo["kind"] == "image"
    assert "pages" not in photo
    assert sheet["kind"] == "document"
    assert sheet["pages"] == 2
    assert sheet["sha256"].startswith("sha256:")


def test_read_reference_returns_delimited_page_text(project: Project) -> None:
    register_sheet(project)

    result = project.call("read_reference", {"name": "sheet.pdf"})

    assert result["kind"] == "document"
    assert result["page"] == 1 and result["pages"] == 2
    assert result["truncated"] is False
    assert result["content"].startswith(REFERENCE_START)
    assert result["content"].rstrip().endswith(REFERENCE_END)
    assert SHEET_PAGE_1 in result["content"]
    assert SHEET_PAGE_2 not in result["content"], "a page is a page"

    second = project.call("read_reference", {"name": "sheet.pdf", "page": 2})
    assert SHEET_PAGE_2 in second["content"]


def test_read_reference_pages_by_byte_cursor_under_the_dual_cap(project: Project) -> None:
    from hephaestus.core.registry import TEXT_MAX_BYTES

    body = "\n".join(f"line {index:05d} of the datasheet" for index in range(4000))
    registry(project).add_bytes(body.encode("utf-8"), name="datasheet.txt")

    seen: list[str] = []
    cursor = 0
    for _ in range(20):
        page = project.call("read_reference", {"name": "datasheet.txt", "offset_bytes": cursor})
        assert len(page["content"].encode("utf-8")) <= TEXT_MAX_BYTES
        seen.append(page["content"])
        if not page["truncated"]:
            break
        assert page["next_offset_bytes"] > cursor, "a cursor always advances"
        cursor = page["next_offset_bytes"]
    else:  # pragma: no cover - a stalled cursor would mean the cap is broken
        pytest.fail("paging never terminated")

    assert "line 00000" in seen[0]
    assert "line 03999" in seen[-1]
    assert len(seen) > 1, "the dual cap must have bound at least once"


def test_an_offset_inside_a_code_point_is_refused(project: Project) -> None:
    registry(project).add_bytes("Ø6.0 tolerance".encode(), name="note.txt")

    result = project.call("read_reference", {"name": "note.txt", "offset_bytes": 1})

    assert result["error"] == "invalid_utf8_offset"


def test_read_reference_returns_an_image_inline_with_its_ref(project: Project) -> None:
    import base64

    entry = registry(project).add_bytes(png_bytes(), name="photo.png")

    result = project.call("read_reference", {"name": "photo.png"})

    assert result["kind"] == "image"
    assert result["artifact_ref"] == entry.artifact_ref
    assert len(result["images"]) == 1
    assert result["images"][0]["mime_type"] == "image/png"
    assert base64.b64decode(result["images"][0]["data"]) == registry(project).payload(entry)


def test_an_image_over_the_dimension_budget_is_refused(project: Project) -> None:
    # The §5 header gate runs before anything decodes the payload; a reference is
    # not exempt from it just because an operator supplied it.
    entry = registry(project).add_bytes(png_bytes(), name="photo.png")
    huge = bytearray(registry(project).payload(entry))
    huge[16:20] = (99999).to_bytes(4, "big")  # IHDR width
    registry(project).add_bytes(bytes(huge), name="photo.png")

    with pytest.raises(DispatchError) as excinfo:
        project.call("read_reference", {"name": "photo.png"})
    assert excinfo.value.reason == "image_too_large"


def test_an_unknown_reference_names_the_candidates(project: Project) -> None:
    register_sheet(project)
    with pytest.raises(DispatchError) as excinfo:
        project.call("read_reference", {"name": "nope.pdf"})
    assert excinfo.value.reason == "unknown_reference"
    assert "sheet.pdf" in str(excinfo.value)


def test_reading_is_available_to_a_part_session(project: Project) -> None:
    register_sheet(project)
    result = project.call("read_reference", {"name": "sheet.pdf"}, principal=PART_WIDGET)
    assert result["status"] == "ok"


# ==========================================================================
# ledger citations (INGEST.md §2 / VALIDATION.md §2)


CITE: dict[str, Any] = {"reference": "sheet.pdf", "page": 1, "quote": "Bore diameter 6.0"}
CITED: dict[str, Any] = {
    "id": "R1",
    "text": "bore is 6 mm diameter",
    "source": "specified",
    "cite": CITE,
    "value": 6.0,
    "unit": "mm",
}


def test_a_cite_stands_in_for_the_prompt_quote(project: Project) -> None:
    register_sheet(project)

    result = project.call("record_requirements", {"entries": [CITED]})

    assert result["status"] == "ok"
    entry = cast("list[dict[str, Any]]", result["entries"])[0]
    assert entry["quote"] is None
    assert entry["cite"] == {"reference": "sheet.pdf", "page": 1, "quote": "Bore diameter 6.0"}


def test_specified_without_a_quote_or_a_cite_is_still_refused(project: Project) -> None:
    with pytest.raises(DispatchError) as excinfo:
        project.call(
            "record_requirements",
            {"entries": [{"id": "R1", "text": "bore is 6 mm", "source": "specified"}]},
        )
    assert excinfo.value.reason == "invalid_requirement"


def test_a_cite_of_an_unregistered_reference_is_refused(project: Project) -> None:
    with pytest.raises(DispatchError) as excinfo:
        project.call("record_requirements", {"entries": [CITED]})
    assert excinfo.value.reason == "invalid_requirement"
    assert "not registered" in str(excinfo.value)
    assert project.cad.ledger_state().generation == 0, "nothing was written"


def test_a_cite_past_the_end_of_the_document_is_refused(project: Project) -> None:
    register_sheet(project)
    entry = {**CITED, "cite": {**CITE, "page": 9}}
    with pytest.raises(DispatchError) as excinfo:
        project.call("record_requirements", {"entries": [entry]})
    assert excinfo.value.reason == "invalid_requirement"
    assert "past the end" in str(excinfo.value)


def test_a_page_cite_of_an_image_is_refused(project: Project) -> None:
    registry(project).add_bytes(png_bytes(), name="photo.png")
    entry = {**CITED, "cite": {"reference": "photo.png", "page": 1, "quote": "Ø6.0"}}
    with pytest.raises(DispatchError) as excinfo:
        project.call("record_requirements", {"entries": [entry]})
    assert excinfo.value.reason == "invalid_requirement"


# ==========================================================================
# lint verifies a document citation against the extracted text


def _lint(project: Project, entries: list[dict[str, Any]]) -> list[Any]:
    from hephaestus.core.lint import lint_requirements

    reg = registry(project)
    listing = reg.list_references()
    documents = {e.name: reg.pages(e) for e in listing if e.kind == "document"}
    images = [e.name for e in listing if e.kind == "image"]
    return list(
        lint_requirements(
            entries, "make me a bracket", references=documents, image_references=images
        )
    )


def test_lint_accepts_a_document_citation_that_is_really_there(project: Project) -> None:
    register_sheet(project)
    assert _lint(project, [CITED]) == []


def test_lint_rejects_a_fabricated_document_citation(project: Project) -> None:
    register_sheet(project)
    fabricated = {**CITED, "cite": {**CITE, "quote": "Bore diameter 12.0"}}

    findings = _lint(project, [fabricated])

    assert [f.code for f in findings] == ["unsourced_requirement"]
    assert findings[0].severity == "error"
    assert "is not in 'sheet.pdf'" in findings[0].message


def test_lint_routes_an_image_citation_to_the_reviewer(project: Project) -> None:
    registry(project).add_bytes(png_bytes(), name="drawing.png")
    cited = {**CITED, "cite": {"reference": "drawing.png", "quote": "Ø6.0 ±0.1"}}

    findings = _lint(project, [cited])

    assert [f.code for f in findings] == ["unverifiable_citation"]
    assert findings[0].severity == "warning"
    assert "vision" in findings[0].message


def test_lint_verifies_the_same_text_read_reference_returned(project: Project) -> None:
    register_sheet(project)
    page = project.call("read_reference", {"name": "sheet.pdf", "page": 1})
    quoted = SHEET_PAGE_1[:12]
    assert quoted in page["content"]
    assert _lint(project, [{**CITED, "cite": {**CITE, "quote": quoted}}]) == []


# ==========================================================================
# the §5 reviewer: cited images reach it, and the finding is vision-channel


def test_the_review_context_carries_every_cited_reference(project: Project) -> None:
    from hephaestus.agent_bridge.review import build_review_context

    register_sheet(project)
    registry(project).add_bytes(png_bytes(), name="drawing.png")
    project.call(
        "record_requirements",
        {
            "entries": [
                CITED,
                {
                    "id": "R2",
                    "text": "chamfer called out on the drawing",
                    "source": "specified",
                    "cite": {"reference": "drawing.png", "quote": "1x45"},
                },
            ]
        },
    )

    context = build_review_context(project.cad, request="make me a bracket")

    assert [reference.name for reference in context.references] == ["drawing.png", "sheet.pdf"]
    drawing = context.references[0]
    assert drawing.kind == "image"
    assert drawing.cited_by == ("R2",)
    assert drawing.artifact_ref.startswith(REFERENCE_REF_PREFIX)
    # …and the reviewer is told to open it.
    assert "read_reference" in context.prompt()
    assert "drawing.png" in json.dumps(context.to_json())


def test_an_image_citation_is_recorded_on_the_vision_channel(project: Project) -> None:
    from hephaestus.agent_bridge.review import image_reference_names, normalize_findings

    registry(project).add_bytes(png_bytes(), name="drawing.png")
    project.call(
        "record_requirements",
        {
            "entries": [
                {
                    "id": "R2",
                    "text": "chamfer called out on the drawing",
                    "source": "specified",
                    "cite": {"reference": "drawing.png", "quote": "1x45"},
                    "value": 1.0,
                    "unit": "mm",
                }
            ]
        },
    )
    entries = project.cad.ledger_state().entries

    # The reviewer claims it measured a number; the entry says otherwise, and the
    # entry wins — verifying a callout on a drawing is a looking act.
    report = normalize_findings(
        entries,
        [
            {
                "id": "R2",
                "verdict": "pass",
                "evidence": "read it off the drawing",
                "channel": "numeric",
            }
        ],
        image_references=image_reference_names(project.cad),
    )

    assert report.findings[0].channel == "vision"
    assert report.channel_counts["vision"] == 0, "a pass is not a caught failure"


def test_a_document_citation_leaves_the_channel_to_the_reviewer(project: Project) -> None:
    from hephaestus.agent_bridge.review import image_reference_names, normalize_findings

    register_sheet(project)
    project.call("record_requirements", {"entries": [CITED]})
    entries = project.cad.ledger_state().entries

    report = normalize_findings(
        entries,
        [{"id": "R1", "verdict": "fail", "evidence": "measured 8 mm", "channel": "numeric"}],
        image_references=image_reference_names(project.cad),
    )

    assert report.findings[0].channel == "numeric"
    assert report.channel_counts["numeric"] == 1


# ==========================================================================
# the reviewer profile may read references, and still cannot write


def test_the_reviewer_profile_reads_references_and_nothing_else(project: Project) -> None:
    from hephaestus.contract.tools_decl import REVIEWER_TOOLS, TOOLS_BY_NAME

    assert {"list_references", "read_reference"} <= REVIEWER_TOOLS
    for name in REVIEWER_TOOLS:
        decl = TOOLS_BY_NAME[name]
        assert "reviewer" in decl.profiles
        assert not decl.idempotent, f"{name} is a mutation; the reviewer may not mutate"


def test_the_registry_read_path_never_writes(project: Project) -> None:
    register_sheet(project)
    before = project.store.blobs.read_pointer("references-state")
    project.call("read_reference", {"name": "sheet.pdf"})
    project.call("list_references", {})
    assert project.store.blobs.read_pointer("references-state") == before


# ==========================================================================
# no extracted text at all


def test_a_document_with_no_pages_is_reported_not_guessed(project: Project) -> None:
    entry = registry(project).add_bytes(b"# notes\n", name="notes.md")
    assert entry.pages == 1
    with pytest.raises(CadOpError):
        project.cad.read_reference("notes.md", page=2)
