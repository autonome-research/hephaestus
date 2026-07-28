# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""G8A: a seeded bench task exercising each of ``imports/`` and ``references/``.

Gate clause: *a seeded bench task exercising each of ``imports/`` and
``references/`` end to end with the FakeModel*.

Both runs go through the real bench loop — ``harness.run_task``, a real
:class:`~hephaestus.agent_bridge.app.BridgeRuntime` orchestrator session against
the *packaged* Node sidecar, a scripted OpenAI-compatible fake model, then real
grading and archiving. The fixtures are authored here rather than committed to
``corpus/`` so that this gate cannot be satisfied (or broken) by an edit to a
task somebody else owns, and so the STEP seed is produced by the product's own
writer at run time.

The two tasks are the two shapes ``INGEST.md`` §2 names as the substrate for
external benchmarks:

``ingest-plate`` (editing)
    the fixture seeds ``imports/vendor_plate.step``; the model imports it, bores
    it, builds and exports. Editing an existing part is the CADGenBench editing
    split, and here the "existing part" is a real vendor file.
``sheet-from-drawing`` (generation from documents)
    the fixture seeds ``references/`` with a drawing image and a datasheet; the
    model looks at both, records requirements that CITE the datasheet rather
    than the prompt, and builds to them. Generation-from-drawing is the other
    split.

What each asserts beyond "the bench went green" is the ingest-specific
evidence: the graded build names the imported file in its input hashes, and the
run's own ledger carries a document citation the model could only have got by
reading the registered reference.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from _g8a import StepFixtures, png_bytes
from hephaestus.agent_bridge.app import BridgeRuntime
from hephaestus.bench import harness
from hephaestus.bench.harness import ARCHIVE_EVENTS_FILENAME, BenchTask, ProviderConfig
from hephaestus.core.project_store.layout import load_project, open_store
from hephaestus.testing.fake_openai import FakeOpenAI, RequestInfo, start_fake_openai

#: A scripted turn never needs the 1800 s default.
PROMPT_TIMEOUT = 300.0

# --------------------------------------------------------------------------
# the two fixtures

INGEST_PROMPT = (
    "The supplier finally sent the plate they machine for us: it is in the "
    "project as vendor_plate.step. Start from that file rather than remodelling "
    "it — import it and put a 6 mm diameter hole straight through the middle of "
    "it, right through the 5 mm thickness. Call the part `bracket` and build it."
)

DATASHEET = (
    "# Blank data sheet, revision C\n"
    "\n"
    "Plate blank 40 x 20 x 5 mm, aluminium.\n"
    "Bore diameter 6.0 +/- 0.1 mm, through, on the centre of the blank.\n"
)

DRAWING_PROMPT = (
    "The shop sent us a drawing and the blank data sheet for it; both are "
    "registered as references on this project. Read them, then model the part "
    "they describe. Call it `plate` and build it. Record what the data sheet "
    "specifies as requirements citing the sheet itself, not my message."
)

#: 40 x 20 x 5 less a Ø6 hole through the 5 mm thickness.
BLANK_MM3 = 40.0 * 20.0 * 5.0
BORE_MM3 = 3.0 * 3.0 * 3.14159265358979 * 5.0

CHECKS_SRC = """# Acceptance for the ingest fixtures: the blank's envelope and the
# material left after the Ø6 bore. The window (5 mm^3) is two orders below the
# bore itself (141 mm^3), so a missing or wrongly sized hole fails.
_ENVELOPE = (40.0, 20.0, 5.0)
_VOLUME = {volume!r}

CHECKS = {{
    "{part}_envelope": lambda m: m.bbox("{part}/part") == approx(_ENVELOPE, abs=0.05),
    "{part}_material_budget": lambda m: m.volume("{part}/part") == approx(_VOLUME, abs=5.0),
}}
"""

INGEST_PART_SRC = """# The vendor's blank, bored: the file is a term in the expression.
base = import_step("vendor_plate.step")
bore = Cylinder(3.0, 20.0)
part.geometry = base - bore
part.description = "vendor blank with the Ø6 through bore"
"""

DRAWING_PART_SRC = """# Modelled to the data sheet: 40 x 20 x 5 blank, Ø6 through bore.
blank = Box(40.0, 20.0, 5.0)
bore = Cylinder(3.0, 20.0)
part.geometry = blank - bore
part.description = "plate to blank data sheet revision C"
"""


def write_task(
    directory: Path,
    *,
    task_id: str,
    prompt: str,
    part: str,
    check_name: str,
    exports: list[dict[str, Any]] | None = None,
) -> BenchTask:
    """Author one bench task directory (``task.json`` + ``seed/`` + ``checks/``)."""
    seed = directory / "seed"
    seed.mkdir(parents=True, exist_ok=True)
    (seed / "hephaestus.toml").write_text(
        f'[project]\nname = "{task_id.replace("-", "_")}"\n', encoding="utf-8"
    )
    (seed / "globals.py").write_text(
        "# Project-shared namespace (script contract §4).\nPARAMS = {}\n", encoding="utf-8"
    )
    (directory / "checks").mkdir(exist_ok=True)
    (directory / "checks" / f"{check_name}.py").write_text(
        CHECKS_SRC.format(part=part, volume=BLANK_MM3 - BORE_MM3), encoding="utf-8"
    )
    spec: dict[str, Any] = {
        "id": task_id,
        "prompt": prompt,
        "budget_tool_calls": 20,
        "required_checks": [check_name],
        "export_requirements": exports or [],
    }
    (directory / "task.json").write_text(json.dumps(spec), encoding="utf-8")
    return BenchTask.load(directory)


@pytest.fixture
def ingest_task(tmp_path: Path, steps: StepFixtures) -> BenchTask:
    directory = tmp_path / "tasks" / "ingest-plate"
    task = write_task(
        directory,
        task_id="ingest-plate",
        prompt=INGEST_PROMPT,
        part="bracket",
        check_name="ingest_plate",
        exports=[{"part": "bracket", "format": "step"}],
    )
    imports = task.seed_dir / "imports"
    imports.mkdir(parents=True, exist_ok=True)
    (imports / "vendor_plate.step").write_bytes(steps.plate)
    return task


@pytest.fixture
def drawing_task(tmp_path: Path) -> BenchTask:
    directory = tmp_path / "tasks" / "sheet-from-drawing"
    task = write_task(
        directory,
        task_id="sheet-from-drawing",
        prompt=DRAWING_PROMPT,
        part="plate",
        check_name="drawing_plate",
    )
    references = task.seed_dir / "references"
    references.mkdir(parents=True, exist_ok=True)
    (references / "datasheet.md").write_text(DATASHEET, encoding="utf-8")
    (references / "drawing.png").write_bytes(png_bytes(64, 48))
    return task


# --------------------------------------------------------------------------
# the loop


@pytest.fixture
def fake_model() -> Iterator[FakeOpenAI]:
    fake = start_fake_openai([])
    try:
        yield fake
    finally:
        fake.close()


@pytest.fixture
def provider(fake_model: FakeOpenAI) -> ProviderConfig:
    return ProviderConfig(providers=(fake_model.provider_spec(),), model_id=fake_model.model_id)


@pytest.fixture
def runtime_factory(sidecar_dist: Path) -> harness.RuntimeFactory:
    def factory(project_root: Path, config: ProviderConfig) -> BridgeRuntime:
        return BridgeRuntime(
            project_root=project_root, providers=config.providers, dist_main=sidecar_dist
        )

    return factory


def tool_call(name: str, arguments: dict[str, Any], call_id: str) -> dict[str, Any]:
    return {"kind": "tool_calls", "calls": [{"name": name, "arguments": arguments, "id": call_id}]}


def last_tool_json(info: RequestInfo) -> Any:
    """The JSON payload of the most recent tool result in the transcript.

    Tolerant about shape on purpose: a result is a JSON object (``build_part``),
    a JSON array (``list_references``), or — once a tool returns an image — a
    multi-part content list whose text part carries the JSON while the image
    rides alongside. All three have to be readable by a scripted model, because
    a real one reads all three.
    """
    body = cast("dict[str, Any]", json.loads(info.body_text))
    for message in reversed(cast("list[Any]", body.get("messages", []))):
        if not isinstance(message, dict):
            continue
        entry = cast("dict[str, Any]", message)
        if entry.get("role") != "tool":
            continue
        content = entry.get("content")
        chunks: list[str] = []
        if isinstance(content, str):
            chunks.append(content)
        elif isinstance(content, list):
            for part in cast("list[Any]", content):
                if isinstance(part, str):
                    chunks.append(part)
                elif isinstance(part, dict):
                    text = cast("dict[str, Any]", part).get("text")
                    if isinstance(text, str):
                        chunks.append(text)
        for chunk in chunks:
            try:
                parsed, _end = json.JSONDecoder().raw_decode(chunk.lstrip())
            except json.JSONDecodeError:
                continue
            return parsed
        return None
    return None


def last_tool_result(info: RequestInfo) -> dict[str, Any]:
    """The last tool result, which must have been a JSON object."""
    parsed = last_tool_json(info)
    assert isinstance(parsed, dict), parsed
    return cast("dict[str, Any]", parsed)


def archived_events(run_dir: Path) -> list[dict[str, Any]]:
    return [
        cast("dict[str, Any]", json.loads(line))
        for line in (run_dir / ARCHIVE_EVENTS_FILENAME).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def tool_names(events: list[dict[str, Any]]) -> list[str]:
    """Tool names in call order, off the archived normalized event stream."""
    names: list[str] = []
    for event in events:
        if event.get("kind") != "tool_call":
            continue
        payload = event.get("payload")
        if isinstance(payload, dict):
            names.append(str(cast("dict[str, Any]", payload).get("name", "")))
    return names


# ==========================================================================
# imports/: the editing-style task


def ingest_script(fake: FakeOpenAI) -> None:
    """Ledger, then create -> write (importing the seeded file) -> build."""

    def create(info: RequestInfo) -> dict[str, Any]:
        recorded = last_tool_result(info)
        assert recorded.get("status") == "ok", recorded
        return tool_call("create_part", {"name": "bracket", "template": "blank"}, "c1")

    def write(info: RequestInfo) -> dict[str, Any]:
        created = last_tool_result(info)
        return tool_call(
            "write_part",
            {
                "name": "bracket",
                "expected_hash": created["content_hash"],
                "script": INGEST_PART_SRC,
            },
            "c2",
        )

    def build(info: RequestInfo) -> dict[str, Any]:
        written = last_tool_result(info)
        assert written.get("applied") is True, written
        return tool_call("build_part", {"name": "bracket"}, "c3")

    def finish(info: RequestInfo) -> dict[str, Any]:
        built = last_tool_result(info)
        assert built.get("status") == "ok", built
        return {"kind": "text", "chunks": ["imported the vendor blank and bored it Ø6"]}

    fake.set_script(
        [
            tool_call(
                "record_requirements",
                {
                    "entries": [
                        {
                            "id": "R1",
                            "text": "the geometry starts from the supplied vendor_plate.step",
                            "source": "specified",
                            "quote": "Start from that file rather than remodelling it",
                        },
                        {
                            "id": "R2",
                            "text": "a 6 mm diameter hole passes through the plate",
                            "source": "specified",
                            "quote": "6 mm diameter hole straight through the middle",
                            "value": 6.0,
                            "unit": "mm",
                        },
                    ]
                },
                "c0",
            ),
            create,
            write,
            build,
            finish,
        ]
    )


def test_a_seeded_imports_task_runs_end_to_end(
    tmp_path: Path,
    ingest_task: BenchTask,
    fake_model: FakeOpenAI,
    provider: ProviderConfig,
    runtime_factory: harness.RuntimeFactory,
) -> None:
    ingest_script(fake_model)
    archive = tmp_path / "results" / provider.model_slug / "2026-07-27"

    run = harness.run_task(
        ingest_task,
        1,
        provider=provider,
        archive_dir=archive,
        runtime_factory=runtime_factory,
        prompt_timeout=PROMPT_TIMEOUT,
        date="2026-07-27",
    )

    assert run.error is None, run.error
    assert run.passed, run.reasons
    grade = cast("dict[str, Any]", run.grade)
    for name, value in cast("dict[str, Any]", grade["checks"]).items():
        assert cast("dict[str, Any]", value)["pass"] is True, name
    # The required STEP export was produced from the graded geometry.
    export = cast("dict[str, Any]", cast("list[Any]", grade["exports"])[0])
    assert "invalid" not in export
    # The ledger call is compelled by VALIDATION.md §2 and not charged.
    assert run.tool_calls == 3
    assert run.compelled_tool_calls == 1

    # …and the graded build really was an ingest: the project the run worked in
    # names the seeded file in the build's input hashes.
    project = Path(cast("str", run.project_dir))
    assert (project / "imports" / "vendor_plate.step").is_file()
    layout = load_project(project)
    store = open_store(layout)
    try:
        from hephaestus.agent_bridge.cad_ops import CadOps

        current = CadOps(layout, store).current_build("bracket")
        assert current is not None
        assert list(current.input_hashes.imports) == ["vendor_plate.step"]
        assert current.metrics is not None
        assert current.metrics.volume_mm3 == pytest.approx(BLANK_MM3 - BORE_MM3, abs=1.0)
    finally:
        store.close()


# ==========================================================================
# references/: the generation-style task


def drawing_script(fake: FakeOpenAI) -> None:
    """Look at the drawing, read the sheet, cite it, then model to it."""

    def read_sheet(info: RequestInfo) -> dict[str, Any]:
        listing = last_tool_json(info)
        assert isinstance(listing, list), listing
        names = {
            str(cast("dict[str, Any]", entry)["name"])
            for entry in cast("list[Any]", listing)
            if isinstance(entry, dict)
        }
        assert {"datasheet.md", "drawing.png"} <= names, listing
        return tool_call("read_reference", {"name": "datasheet.md"}, "c1")

    def read_drawing(info: RequestInfo) -> dict[str, Any]:
        sheet = last_tool_result(info)
        assert "Bore diameter 6.0" in str(sheet.get("content")), sheet
        return tool_call("read_reference", {"name": "drawing.png"}, "c2")

    def record(info: RequestInfo) -> dict[str, Any]:
        drawing = last_tool_result(info)
        assert drawing.get("kind") == "image", drawing
        return tool_call(
            "record_requirements",
            {
                "entries": [
                    {
                        "id": "R1",
                        "text": "the blank is 40 x 20 x 5 mm",
                        "source": "specified",
                        "cite": {
                            "reference": "datasheet.md",
                            "page": 1,
                            "quote": "Plate blank 40 x 20 x 5 mm",
                        },
                    },
                    {
                        "id": "R2",
                        "text": "a Ø6 bore passes through the centre of the blank",
                        "source": "specified",
                        "cite": {
                            "reference": "datasheet.md",
                            "page": 1,
                            "quote": "Bore diameter 6.0 +/- 0.1 mm",
                        },
                        "value": 6.0,
                        "unit": "mm",
                    },
                ]
            },
            "c3",
        )

    def create(info: RequestInfo) -> dict[str, Any]:
        recorded = last_tool_result(info)
        assert recorded.get("status") == "ok", recorded
        return tool_call("create_part", {"name": "plate", "template": "blank"}, "c4")

    def write(info: RequestInfo) -> dict[str, Any]:
        created = last_tool_result(info)
        return tool_call(
            "write_part",
            {"name": "plate", "expected_hash": created["content_hash"], "script": DRAWING_PART_SRC},
            "c5",
        )

    def build(info: RequestInfo) -> dict[str, Any]:
        written = last_tool_result(info)
        assert written.get("applied") is True, written
        return tool_call("build_part", {"name": "plate"}, "c6")

    def finish(info: RequestInfo) -> dict[str, Any]:
        built = last_tool_result(info)
        assert built.get("status") == "ok", built
        return {"kind": "text", "chunks": ["modelled the blank to data sheet revision C"]}

    fake.set_script(
        [
            tool_call("list_references", {}, "c0"),
            read_sheet,
            read_drawing,
            record,
            create,
            write,
            build,
            finish,
        ]
    )


def test_a_seeded_references_task_runs_end_to_end(
    tmp_path: Path,
    drawing_task: BenchTask,
    fake_model: FakeOpenAI,
    provider: ProviderConfig,
    runtime_factory: harness.RuntimeFactory,
) -> None:
    drawing_script(fake_model)
    archive = tmp_path / "results" / provider.model_slug / "2026-07-27"

    run = harness.run_task(
        drawing_task,
        1,
        provider=provider,
        archive_dir=archive,
        runtime_factory=runtime_factory,
        prompt_timeout=PROMPT_TIMEOUT,
        date="2026-07-27",
    )

    assert run.error is None, run.error
    assert run.passed, run.reasons
    grade = cast("dict[str, Any]", run.grade)
    for name, value in cast("dict[str, Any]", grade["checks"]).items():
        assert cast("dict[str, Any]", value)["pass"] is True, name

    events = archived_events(archive / "sheet-from-drawing-s1")
    called = tool_names(events)
    assert called[:3] == ["list_references", "read_reference", "read_reference"]

    # The run's ledger is document-grounded: the entries cite the registered
    # sheet, and carry no prompt quote at all.
    project = Path(cast("str", run.project_dir))
    layout = load_project(project)
    store = open_store(layout)
    try:
        from hephaestus.agent_bridge.cad_ops import CadOps
        from hephaestus.core.lint import lint_requirements
        from hephaestus.core.project_store.references import ReferenceRegistry

        cad = CadOps(layout, store)
        entries = cad.ledger_state().entries
        assert [entry.id for entry in entries] == ["R1", "R2"]
        for entry in entries:
            assert entry.quote is None
            assert entry.cite is not None
            assert entry.cite.reference == "datasheet.md"

        # …and every citation really is in the text the model was shown, which is
        # what `heph lint` checks: the sheet, not the request, is the source.
        registry = ReferenceRegistry(layout, store)
        documents = {
            e.name: registry.pages(e) for e in registry.list_references() if e.kind == "document"
        }
        findings = lint_requirements(
            [entry.to_json() for entry in entries],
            run.prompt,
            references=documents,
            image_references=[e.name for e in registry.list_references() if e.kind == "image"],
        )
        assert [f.code for f in findings] == []
    finally:
        store.close()
