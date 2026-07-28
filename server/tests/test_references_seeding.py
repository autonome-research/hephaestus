"""Bench fixtures may seed ``references/`` and ``imports/`` (``INGEST.md`` §2/§1).

The seeding capability, not a committed task: a fixture ships plain files in its
``seed/`` tree and the harness — the operator, here — registers the references,
so a run finds them through ``list_references``/``read_reference`` without any
tool that could have put them there. ``imports/`` needs no registration at all:
an import is resolved from the file at build time, so copying it in is the whole
step, which this pins too.
"""

from __future__ import annotations

import io
from pathlib import Path

from hephaestus.agent_bridge.cad_ops import CadOps
from hephaestus.bench.harness._seed import seed_project, seed_references
from hephaestus.bench.harness._tasks import BenchTask
from hephaestus.core.project_store.layout import load_project, open_store


def png_bytes() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (6, 6), (30, 60, 90)).save(buf, format="PNG")
    return buf.getvalue()


def make_task(directory: Path) -> BenchTask:
    seed = directory / "seed"
    (seed / "references").mkdir(parents=True)
    (seed / "imports").mkdir(parents=True)
    (seed / "references" / "spec.md").write_text(
        "# Vendor sheet\nBore diameter 6.0 +/- 0.1\n", encoding="utf-8"
    )
    (seed / "references" / "drawing.png").write_bytes(png_bytes())
    (seed / "imports" / "base.step").write_bytes(
        b"ISO-10303-21;\nHEADER;\nENDSEC;\nEND-ISO-10303-21;\n"
    )
    (directory / "task.json").write_text("{}", encoding="utf-8")
    return BenchTask(
        id="seeded-refs",
        directory=directory,
        prompt="use the attached sheet",
        budget_tool_calls=10,
    )


def test_a_seeded_fixture_round_trips_through_the_model_surface(tmp_path: Path) -> None:
    task = make_task(tmp_path / "task")
    root = seed_project(task, tmp_path / "proj")

    # imports/ is just files: nothing registers them, and the build resolves the
    # declared path at freeze time (INGEST.md §1).
    assert (root / "imports" / "base.step").is_file()

    layout = load_project(root)
    store = open_store(layout)
    try:
        cad = CadOps(layout, store)
        listing = cad.list_references()
        assert [entry["name"] for entry in listing] == ["drawing.png", "spec.md"]

        document = cad.read_reference("spec.md")
        assert document["kind"] == "document"
        assert "Bore diameter 6.0" in document["content"]

        image = cad.read_reference("drawing.png")
        assert image["kind"] == "image"
        assert image["images"][0]["mime_type"] == "image/png"
    finally:
        store.close()


def test_seeding_a_project_without_references_registers_nothing(tmp_path: Path) -> None:
    directory = tmp_path / "task"
    (directory / "seed").mkdir(parents=True)
    (directory / "task.json").write_text("{}", encoding="utf-8")
    task = BenchTask(id="bare", directory=directory, prompt="build a box", budget_tool_calls=10)

    root = seed_project(task, tmp_path / "proj")

    layout = load_project(root)
    store = open_store(layout)
    try:
        assert CadOps(layout, store).list_references() == []
    finally:
        store.close()


def test_seed_references_is_idempotent(tmp_path: Path) -> None:
    task = make_task(tmp_path / "task")
    root = seed_project(task, tmp_path / "proj")

    assert seed_references(root) == ("drawing.png", "spec.md")

    layout = load_project(root)
    store = open_store(layout)
    try:
        assert [e["name"] for e in CadOps(layout, store).list_references()] == [
            "drawing.png",
            "spec.md",
        ]
    finally:
        store.close()
