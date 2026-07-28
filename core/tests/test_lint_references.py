"""``INGEST.md`` §2 citations in ``heph lint``'s ``unsourced_requirement`` rule.

A real spec often lives on the drawing rather than in the prompt, so a
``specified`` entry may carry ``cite={reference, page?, quote}``. What is pinned
here is that citing does not *weaken* the rule:

* a document citation is verified against the reference's extracted text exactly
  as a prompt quote is verified against the request;
* a fabricated one — wrong text, wrong page, unregistered reference — is the same
  ``error``, never a pass;
* an **image** citation has no text to decide against, so it is neither passed
  nor failed here: it is ``unverifiable_citation``, which is how it reaches the
  ``VALIDATION.md`` §5 reviewer's vision channel;
* the CLI resolves the project's own registered references, so what lint checks
  is the same text the model was shown.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from hephaestus.core.cli import main
from hephaestus.core.lint import lint_requirements
from hephaestus.core.project_store.layout import load_project, open_store
from hephaestus.core.project_store.references import ReferenceRegistry
from opstore.types import JSONValue

REQUEST = "make me a bracket, details on the attached sheet"

SHEET_PAGES = (
    "GENERAL NOTES\nAll dimensions in millimetres.",
    "Bore diameter 6.0 +/- 0.1\nPlate thickness 3.0",
)

DOCUMENTS = {"sheet.pdf": SHEET_PAGES}
IMAGES = ("drawing.png",)


def cited(quote: str, *, reference: str = "sheet.pdf", page: int | None = 2) -> dict[str, Any]:
    cite: dict[str, Any] = {"reference": reference, "quote": quote}
    if page is not None:
        cite["page"] = page
    return {"id": "R1", "text": "bore is 6 mm", "source": "specified", "cite": cite}


def run(entry: dict[str, Any]) -> list[Any]:
    return list(lint_requirements([entry], REQUEST, references=DOCUMENTS, image_references=IMAGES))


# -- documents ---------------------------------------------------------------


def test_a_citation_present_in_the_extracted_text_passes() -> None:
    assert run(cited("Bore diameter 6.0 +/- 0.1")) == []


def test_a_citation_matches_across_a_line_break_and_case() -> None:
    assert run(cited("bore   DIAMETER 6.0")) == []


def test_a_citation_absent_from_the_page_is_an_error() -> None:
    (finding,) = run(cited("Bore diameter 12.0"))
    assert finding.code == "unsourced_requirement"
    assert finding.severity == "error"
    assert finding.name == "R1"
    assert "is not in 'sheet.pdf' page 2" in finding.message


def test_a_citation_on_the_wrong_page_is_an_error() -> None:
    # The text exists — on page 2. Naming page 1 is a citation that does not hold.
    (finding,) = run(cited("Bore diameter 6.0", page=1))
    assert finding.code == "unsourced_requirement"


def test_without_a_page_the_whole_document_counts() -> None:
    assert run(cited("Bore diameter 6.0", page=None)) == []


def test_a_page_past_the_end_is_an_error() -> None:
    (finding,) = run(cited("Bore diameter 6.0", page=9))
    assert "does not exist" in finding.message


def test_an_unregistered_reference_is_an_error() -> None:
    (finding,) = run(cited("Bore diameter 6.0", reference="nope.pdf", page=None))
    assert finding.code == "unsourced_requirement"
    assert "does not carry" in finding.message


def test_a_cite_that_quotes_nothing_is_an_error() -> None:
    (finding,) = run(cited("  "))
    assert "quotes nothing" in finding.message


# -- images ------------------------------------------------------------------


def test_an_image_citation_is_unverifiable_not_a_pass() -> None:
    (finding,) = run(cited("1x45 chamfer", reference="drawing.png", page=None))
    assert finding.code == "unverifiable_citation"
    assert finding.severity == "warning"
    assert "vision" in finding.message


# -- the prompt-quote rule is untouched --------------------------------------


def test_an_entry_with_a_plain_quote_is_still_checked_against_the_request() -> None:
    entry = {"id": "R1", "text": "bracket", "source": "specified", "quote": "a bracket"}
    assert lint_requirements([entry], REQUEST, references=DOCUMENTS) == ()
    bad = {**entry, "quote": "a gusset"}
    (finding,) = lint_requirements([bad], REQUEST, references=DOCUMENTS)
    assert finding.code == "unsourced_requirement"
    assert "not in the request" in finding.message


def test_lint_requirements_without_references_still_works() -> None:
    entry = {"id": "R1", "text": "bracket", "source": "specified", "quote": "a bracket"}
    assert lint_requirements([entry], REQUEST) == ()


# -- `heph lint` wiring ------------------------------------------------------


SCRIPT = """body = Box(60.0, 40.0, 6.0)
part.geometry = body

CHECKS = {
    "bore": lambda m: m.bbox("part")[0] >= 6.0,  # R1
}
"""


def _project(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "parts").mkdir(exist_ok=True)
    (root / "hephaestus.toml").write_text('[project]\nname = "cited"\n', encoding="utf-8")
    (root / "globals.py").write_text("PARAMS = {}\n", encoding="utf-8")
    (root / "parts" / "bracket.py").write_text(SCRIPT, encoding="utf-8")
    layout = load_project(root)
    store = open_store(layout)
    try:
        registry = ReferenceRegistry(layout, store)
        # Markdown needs no parser at all: core registers and extracts it alone,
        # which is exactly why lint never depends on pypdf.
        registry.add_bytes("\n".join(SHEET_PAGES).encode("utf-8"), name="sheet.md")
        registry.add_bytes(_png(), name="drawing.png")
    finally:
        store.close()


def _png() -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (10, 10, 10)).save(buf, format="PNG")
    return buf.getvalue()


def _lint_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], entries: list[dict[str, Any]]
) -> tuple[int, list[dict[str, JSONValue]]]:
    root = tmp_path / "proj"
    _project(root)
    ledger = tmp_path / "requirements.json"
    ledger.write_text(json.dumps({"generation": 1, "entries": entries}), encoding="utf-8")
    request = tmp_path / "request.txt"
    request.write_text(REQUEST, encoding="utf-8")
    code = main(
        [
            "lint",
            str(root / "parts" / "bracket.py"),
            "--json",
            "--requirements",
            str(ledger),
            "--request",
            str(request),
        ]
    )
    findings = [
        cast("dict[str, JSONValue]", item)
        for item in cast("list[JSONValue]", json.loads(capsys.readouterr().out))
    ]
    return (code, findings)


def test_heph_lint_verifies_a_citation_against_the_projects_own_references(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    good = cited("Bore diameter 6.0", reference="sheet.md", page=1)
    code, findings = _lint_json(tmp_path, capsys, [good])
    assert code == 0
    assert [f["code"] for f in findings if f["code"] == "unsourced_requirement"] == []


def test_heph_lint_fails_a_fabricated_citation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = cited("Bore diameter 12.0", reference="sheet.md", page=1)
    code, findings = _lint_json(tmp_path, capsys, [bad])
    assert code == 1, "a fabricated citation is an error, so the command fails"
    assert [f["name"] for f in findings if f["code"] == "unsourced_requirement"] == ["R1"]


def test_heph_lint_reports_an_image_citation_as_unverifiable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    entry = cited("1x45 chamfer", reference="drawing.png", page=None)
    code, findings = _lint_json(tmp_path, capsys, [entry])
    assert code == 0, "unverifiable is a warning: it is routed onward, not failed here"
    assert [f["name"] for f in findings if f["code"] == "unverifiable_citation"] == ["R1"]
