"""``heph reference add|list|remove`` — the operator's half of ``INGEST.md`` §2.

The verb group exists so that registration has an operator-side home at all: the
model surface is read-only by construction, so if an operator could not register
one, references could not exist. What is pinned here is that the CLI does the
whole registration (copy + content addressing + extraction) and reports what it
did, and that a capability it does not have is named rather than faked.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any, cast

import pytest
from hephaestus.core.cli import main
from hephaestus.core.project_store.layout import load_project, open_store
from hephaestus.core.project_store.references import ReferenceRegistry


def project(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "parts").mkdir(exist_ok=True)
    (root / "hephaestus.toml").write_text('[project]\nname = "refs"\n', encoding="utf-8")
    (root / "globals.py").write_text("PARAMS = {}\n", encoding="utf-8")
    return root


def png_bytes() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (5, 5), (1, 2, 3)).save(buf, format="PNG")
    return buf.getvalue()


def entries(root: Path) -> list[dict[str, Any]]:
    layout = load_project(root)
    store = open_store(layout)
    try:
        return [dict(e.listing()) for e in ReferenceRegistry(layout, store).list_references()]
    finally:
        store.close()


def run(root: Path, monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    monkeypatch.chdir(root)
    return main(list(argv))


def test_add_registers_and_reports_the_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = project(tmp_path / "proj")
    source = tmp_path / "sheet.md"
    source.write_text("# Sheet\nBore diameter 6.0\n", encoding="utf-8")

    assert run(root, monkeypatch, "reference", "add", str(source), "--json") == 0

    reported = cast("dict[str, Any]", json.loads(capsys.readouterr().out))
    assert reported["name"] == "sheet.md"
    assert reported["kind"] == "document"
    assert reported["pages"] == 1
    assert reported["sha256"].startswith("sha256:")
    assert (root / "references" / "sheet.md").read_text(encoding="utf-8") == source.read_text()
    assert [e["name"] for e in entries(root)] == ["sheet.md"]


def test_add_honours_an_explicit_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = project(tmp_path / "proj")
    source = tmp_path / "scan.png"
    source.write_bytes(png_bytes())

    assert run(root, monkeypatch, "reference", "add", str(source), "--name", "sheet1.png") == 0

    capsys.readouterr()
    assert [e["name"] for e in entries(root)] == ["sheet1.png"]
    assert (root / "references" / "sheet1.png").is_file()


def test_add_refuses_a_missing_file_as_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = project(tmp_path / "proj")
    assert run(root, monkeypatch, "reference", "add", str(tmp_path / "nope.md")) == 2


def test_add_refuses_an_unsupported_format(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = project(tmp_path / "proj")
    source = tmp_path / "model.step"
    source.write_text("ISO-10303-21;\n", encoding="utf-8")
    # A STEP file is an INGEST.md §1 import, not a §2 reference.
    assert run(root, monkeypatch, "reference", "add", str(source)) == 1


def test_list_reports_registered_references(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = project(tmp_path / "proj")
    (tmp_path / "a.md").write_text("alpha\n", encoding="utf-8")
    (tmp_path / "b.png").write_bytes(png_bytes())
    run(root, monkeypatch, "reference", "add", str(tmp_path / "a.md"))
    run(root, monkeypatch, "reference", "add", str(tmp_path / "b.png"))
    capsys.readouterr()

    assert run(root, monkeypatch, "reference", "list", "--json") == 0

    listed = cast("list[dict[str, Any]]", json.loads(capsys.readouterr().out))
    assert [e["name"] for e in listed] == ["a.md", "b.png"]
    assert [e["kind"] for e in listed] == ["document", "image"]


def test_list_on_an_empty_project_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = project(tmp_path / "proj")
    assert run(root, monkeypatch, "reference", "list") == 0
    assert "no references registered" in capsys.readouterr().out


def test_remove_deregisters_and_deletes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = project(tmp_path / "proj")
    (tmp_path / "a.md").write_text("alpha\n", encoding="utf-8")
    run(root, monkeypatch, "reference", "add", str(tmp_path / "a.md"))
    capsys.readouterr()

    assert run(root, monkeypatch, "reference", "remove", "a.md") == 0

    assert entries(root) == []
    assert not (root / "references" / "a.md").exists()


def test_removing_an_unknown_reference_names_the_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = project(tmp_path / "proj")
    (tmp_path / "a.md").write_text("alpha\n", encoding="utf-8")
    run(root, monkeypatch, "reference", "add", str(tmp_path / "a.md"))
    capsys.readouterr()

    assert run(root, monkeypatch, "reference", "remove", "b.md") == 2
    assert "a.md" in capsys.readouterr().err


def test_a_pdf_registers_through_the_server_side_extractor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from reportlab.pdfgen import canvas

    root = project(tmp_path / "proj")
    source = tmp_path / "sheet.pdf"
    buf = io.BytesIO()
    sheet = canvas.Canvas(buf)
    sheet.drawString(72, 720, "Bore diameter 6.0")
    sheet.showPage()
    sheet.save()
    source.write_bytes(buf.getvalue())

    assert run(root, monkeypatch, "reference", "add", str(source), "--json") == 0

    reported = cast("dict[str, Any]", json.loads(capsys.readouterr().out))
    assert reported["pages"] == 1

    layout = load_project(root)
    store = open_store(layout)
    try:
        registry = ReferenceRegistry(layout, store)
        assert "Bore diameter 6.0" in registry.pages(registry.get("sheet.pdf"))[0]
    finally:
        store.close()


def test_without_the_pdf_extractor_the_capability_is_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from hephaestus.core import cli_references

    root = project(tmp_path / "proj")
    source = tmp_path / "sheet.pdf"
    source.write_bytes(b"%PDF-1.4\n% not really\n")
    # A core-only installation: the pypdf-backed extractor is not importable.
    monkeypatch.setattr(cli_references, "resolve_extractor", lambda: None)

    assert run(root, monkeypatch, "reference", "add", str(source)) == 1

    assert "hephaestus-server" in capsys.readouterr().err
    assert entries(root) == [], "nothing was registered"
