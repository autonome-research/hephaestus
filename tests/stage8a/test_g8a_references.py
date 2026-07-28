# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""G8A: reference documents and images, operator to reviewer.

Gate clauses: *reference registration/read (text paging + caps, image budgets,
provenance delimiters)*; *ledger document citations verified by lint, image
citations routed to the reviewer with channel recorded*.

One chain, asserted where each link is visible to somebody:

1. the **operator** registers a datasheet and a drawing with ``heph reference
   add`` — the only way one enters a project, since the model surface has no
   write path and the dispatcher does not know a tool that would be one;
2. the **model** lists them and reads them: document text inside the provenance
   delimiters, paged by byte cursor under the §5 dual cap; an image inline,
   through the same header gate every rendered image passes, with its artifact
   ref alongside;
3. the **ledger** cites them, and ``heph lint`` verifies a document citation
   against the extracted text the model was shown — a fabricated one fails the
   command;
4. an **image** citation lint cannot verify reaches the §5 termination reviewer
   with the image attached, and the finding is recorded on the vision channel,
   so §8's channel split counts document-grounded work.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import Any, cast

import pytest
from _g8a import pdf_bytes, png_bytes
from hephaestus.agent_bridge.dispatch import DispatchError
from hephaestus.core.cli import main as heph
from hephaestus.core.registry import (
    REFERENCE_END,
    REFERENCE_START,
    TEXT_MAX_BYTES,
    TEXT_MAX_LINES,
)
from hephaestus.testing.tools_fixture import Project

SHEET_PAGE_1 = "Bore diameter 6.0 +/- 0.1 mm"
SHEET_PAGE_2 = "Plate thickness 3.0 mm"

CITED_DOCUMENT: dict[str, Any] = {
    "id": "R1",
    "text": "the bore is 6 mm diameter",
    "source": "specified",
    "cite": {"reference": "sheet.pdf", "page": 1, "quote": "Bore diameter 6.0"},
    "value": 6.0,
    "unit": "mm",
}
CITED_IMAGE: dict[str, Any] = {
    "id": "R2",
    "text": "the front edge carries a 1 x 45 chamfer, called out on the drawing",
    "source": "specified",
    "cite": {"reference": "drawing.png", "quote": "1x45"},
    "value": 1.0,
    "unit": "mm",
}


def register(project: Project, tmp_path: Path, name: str, data: bytes) -> dict[str, Any]:
    """Register one reference the operator's way: ``heph reference add``.

    Run from inside the project, because that is how an operator runs it: the
    verb finds the project from the working directory and there is no flag that
    would let anything else name one.
    """
    source = tmp_path / "operator" / name
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(data)
    out = io.StringIO()
    with contextlib.chdir(project.root), contextlib.redirect_stdout(out):
        code = heph(["reference", "add", str(source), "--json"])
    assert code == 0, out.getvalue()
    return cast("dict[str, Any]", json.loads(out.getvalue()))


@pytest.fixture
def documented(bare_project: Project, tmp_path: Path) -> Project:
    register(bare_project, tmp_path, "sheet.pdf", pdf_bytes(SHEET_PAGE_1, SHEET_PAGE_2))
    register(bare_project, tmp_path, "drawing.png", png_bytes())
    return bare_project


# ==========================================================================
# registration is the operator's, reading is the model's


def test_the_operator_registers_and_the_model_reads(documented: Project) -> None:
    listing = cast("list[dict[str, Any]]", documented.call("list_references", {}))

    assert [(e["name"], e["kind"]) for e in listing] == [
        ("drawing.png", "image"),
        ("sheet.pdf", "document"),
    ]
    assert all(e["sha256"].startswith("sha256:") for e in listing)
    assert next(e for e in listing if e["kind"] == "document")["pages"] == 2


def test_there_is_no_way_for_the_model_to_add_one(documented: Project) -> None:
    with pytest.raises(DispatchError) as excinfo:
        documented.call("add_reference", {"path": "/etc/passwd"})
    assert excinfo.value.reason in ("unknown_tool", "invalid_tool")
    # …and the project's registry is exactly what the operator put there.
    assert len(cast("list[Any]", documented.call("list_references", {}))) == 2


def test_document_text_arrives_inside_the_provenance_delimiters(documented: Project) -> None:
    page = cast(
        "dict[str, Any]", documented.call("read_reference", {"name": "sheet.pdf", "page": 2})
    )

    assert page["kind"] == "document"
    assert page["page"] == 2
    assert page["pages"] == 2
    content = cast("str", page["content"])
    assert content.startswith(REFERENCE_START)
    assert REFERENCE_END in content
    # The provenance header names the project's own reference set and the digest
    # the citation will be checked against — this is reference MATERIAL.
    assert 'registry="project:references"' in content
    assert page["sha256"] in content
    assert SHEET_PAGE_2.split(" ")[0] in content


def test_a_long_document_pages_by_byte_cursor_under_the_caps(
    bare_project: Project, tmp_path: Path
) -> None:
    """The §5 dual cap binds, and the cursor always advances to the end."""
    body = "".join(f"line {n}: bore diameter 6.0 mm on the vendor sheet\n" for n in range(4000))
    register(bare_project, tmp_path, "long.md", body.encode("utf-8"))

    seen: list[str] = []
    offset = 0
    for _ in range(20):
        page = cast(
            "dict[str, Any]",
            bare_project.call("read_reference", {"name": "long.md", "offset_bytes": offset}),
        )
        content = cast("str", page["content"])
        # Both §5 caps bind on the slice this read delivered: at most 50 KiB of
        # document bytes, and at most 2000 lines of them (the wrapper adds its
        # own header and footer line on top).
        end = cast("int", page.get("next_offset_bytes", page["total_bytes"]))
        assert end - offset <= TEXT_MAX_BYTES
        assert content.count("\n") <= TEXT_MAX_LINES + 2
        seen.append(content)
        if not page["truncated"]:
            break
        assert end > offset, "a cursor that does not advance is a hang"
        offset = end
    else:  # pragma: no cover - a document this size pages in far fewer reads
        pytest.fail("the document never finished paging")

    assert len(seen) > 1, "a 200 KiB document must not arrive in one read"
    assert "line 0:" in seen[0]
    assert "line 3999:" in seen[-1]


def test_an_image_arrives_inline_with_its_artifact_ref(documented: Project) -> None:
    image = cast("dict[str, Any]", documented.call("read_reference", {"name": "drawing.png"}))

    assert image["kind"] == "image"
    assert image["mime_type"] == "image/png"
    assert image["artifact_ref"].startswith("artifact:reference:")
    inline = cast("list[dict[str, Any]]", image["images"])
    assert len(inline) == 1
    assert inline[0]["mime_type"] == "image/png"
    assert inline[0]["data"], "the image is delivered inline, not by reference alone"


def test_an_operator_supplied_image_is_not_exempt_from_the_image_budgets(
    bare_project: Project, tmp_path: Path
) -> None:
    """§5 budgets bind on the way to the model, whoever put the file there."""
    oversize = bytearray(png_bytes())
    oversize[16:20] = (99999).to_bytes(4, "big")  # IHDR width
    register(bare_project, tmp_path, "huge.png", bytes(oversize))

    with pytest.raises(DispatchError) as excinfo:
        bare_project.call("read_reference", {"name": "huge.png"})
    assert excinfo.value.reason == "image_too_large"


def test_an_unknown_reference_names_what_the_project_carries(documented: Project) -> None:
    with pytest.raises(DispatchError) as excinfo:
        documented.call("read_reference", {"name": "invented.pdf"})
    assert excinfo.value.reason == "unknown_reference"
    assert "sheet.pdf" in str(excinfo.value)


# ==========================================================================
# the ledger cites a reference, and lint checks the document half


def lint_target(project: Project) -> Path:
    """A plain part script to lint: the subject here is the ledger, not the script."""
    path = project.root / "parts" / "lintee.py"
    if not path.is_file():
        path.write_text("part.geometry = Box(60.0, 40.0, 6.0)\n", encoding="utf-8")
    return path


def lint(project: Project, tmp_path: Path, request: str) -> tuple[int, list[dict[str, Any]]]:
    """``heph lint`` over the project's OWN ledger, as an operator would run it."""
    ledger = cast("dict[str, Any]", project.call("read_requirements", {}))
    ledger_path = tmp_path / "requirements.json"
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    request_path = tmp_path / "request.txt"
    request_path.write_text(request, encoding="utf-8")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = heph(
            [
                "lint",
                str(lint_target(project)),
                "--json",
                "--requirements",
                str(ledger_path),
                "--request",
                str(request_path),
            ]
        )
    findings = cast("list[dict[str, Any]]", json.loads(out.getvalue()))
    return code, findings


def test_a_document_citation_stands_in_for_a_prompt_quote(documented: Project) -> None:
    result = cast(
        "dict[str, Any]", documented.call("record_requirements", {"entries": [CITED_DOCUMENT]})
    )

    assert result["status"] == "ok"
    entry = cast("list[dict[str, Any]]", result["entries"])[0]
    assert entry["quote"] is None
    assert entry["cite"]["reference"] == "sheet.pdf"


def test_lint_verifies_a_citation_against_the_registered_document(
    documented: Project, tmp_path: Path
) -> None:
    documented.call("record_requirements", {"entries": [CITED_DOCUMENT]})

    code, findings = lint(documented, tmp_path, "make the bracket to the attached sheet")

    assert code == 0, findings
    assert [f for f in findings if f["code"] == "unsourced_requirement"] == []


def test_lint_fails_a_citation_the_document_does_not_contain(
    documented: Project, tmp_path: Path
) -> None:
    fabricated = {
        **CITED_DOCUMENT,
        "cite": {"reference": "sheet.pdf", "page": 1, "quote": "Bore diameter 12.0"},
    }
    documented.call("record_requirements", {"entries": [fabricated]})

    code, findings = lint(documented, tmp_path, "make the bracket to the attached sheet")

    assert code == 1, "a fabricated citation is an error, so the command fails"
    assert [f["name"] for f in findings if f["code"] == "unsourced_requirement"] == ["R1"]


def test_a_citation_of_an_unregistered_reference_never_enters_the_ledger(
    documented: Project,
) -> None:
    invented = {**CITED_DOCUMENT, "cite": {"reference": "nowhere.pdf", "quote": "Ø6.0"}}
    with pytest.raises(DispatchError) as excinfo:
        documented.call("record_requirements", {"entries": [invented]})
    assert excinfo.value.reason == "invalid_requirement"
    assert documented.cad.ledger_state().generation == 0, "nothing was written"


# ==========================================================================
# the image half is the reviewer's, on the vision channel


def test_an_image_citation_is_unverifiable_and_reaches_the_reviewer(
    documented: Project, tmp_path: Path
) -> None:
    from hephaestus.agent_bridge.review import build_review_context

    documented.call("record_requirements", {"entries": [CITED_DOCUMENT, CITED_IMAGE]})

    code, findings = lint(documented, tmp_path, "make the bracket to the attached sheet")
    assert code == 0, "unverifiable is a warning: it is routed onward, not failed here"
    unverifiable = [f for f in findings if f["code"] == "unverifiable_citation"]
    assert [f["name"] for f in unverifiable] == ["R2"]
    assert "vision" in cast("str", unverifiable[0]["message"])

    context = build_review_context(documented.cad, request="make the bracket to the sheet")

    drawing = next(r for r in context.references if r.name == "drawing.png")
    assert drawing.kind == "image"
    assert drawing.cited_by == ("R2",)
    assert drawing.artifact_ref.startswith("artifact:reference:")
    assert "read_reference" in context.prompt()


def test_the_finding_on_an_image_citation_is_recorded_as_vision(documented: Project) -> None:
    """§8's channel split measures document-grounded work: the entry decides."""
    from hephaestus.agent_bridge.review import image_reference_names, normalize_findings

    documented.call("record_requirements", {"entries": [CITED_DOCUMENT, CITED_IMAGE]})
    entries = documented.cad.ledger_state().entries

    report = normalize_findings(
        entries,
        [
            # The reviewer claims it measured the callout; verifying a drawing is
            # a looking act, and the entry's citation wins.
            {"id": "R2", "verdict": "fail", "evidence": "no chamfer", "channel": "numeric"},
            {"id": "R1", "verdict": "fail", "evidence": "measured 8 mm", "channel": "numeric"},
        ],
        image_references=image_reference_names(documented.cad),
    )

    by_id = {finding.id: finding for finding in report.findings}
    assert by_id["R2"].channel == "vision"
    assert by_id["R1"].channel == "numeric"
    assert report.channel_counts["vision"] == 1
    assert report.channel_counts["numeric"] == 1


def test_the_reviewer_may_read_references_and_may_not_write(documented: Project) -> None:
    from hephaestus.contract.tools_decl import REVIEWER_TOOLS, TOOLS_BY_NAME

    assert {"list_references", "read_reference"} <= REVIEWER_TOOLS
    for name in REVIEWER_TOOLS:
        assert not TOOLS_BY_NAME[name].idempotent, f"{name} is a mutation"
