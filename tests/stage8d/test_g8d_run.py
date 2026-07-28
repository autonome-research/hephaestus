# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""G8D: a FakeModel run over both converted samples (``EXTERNAL_EVAL.md`` §2).

Gate clause: *a FakeModel run over both converted tasks produces STEP artifacts
through the standard export path*.

"Standard" is the whole claim, so nothing is shortened: each converted task goes
through :func:`hephaestus.bench.harness.run_task` — a real orchestrator session
against the packaged Node sidecar and a scripted OpenAI-compatible fake model,
then the real grader, which performs the task's declared STEP export from the
**graded geometry**. The submission bytes are therefore a build artifact with
provenance, not something the model handed us.

The two samples exercise the two ingest paths Stage 8A shipped, as converted:
generation reads a registered drawing reference, editing starts from
``import_step`` on the seeded solid. The run ends where the benchmark's does —
the collected outputs are packaged into the submission ZIP.
"""

from __future__ import annotations

import json
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from _g8d import DATASET
from hephaestus.agent_bridge.app import BridgeRuntime
from hephaestus.bench import harness
from hephaestus.bench.cadgenbench import (
    PART_NAME,
    SubmissionMeta,
    collect_outputs,
    convert_samples,
    package_submission,
    score_outputs,
    step_validity,
)
from hephaestus.bench.harness import BenchTask, ProviderConfig
from hephaestus.testing.fake_openai import FakeOpenAI, RequestInfo, start_fake_openai

#: A scripted turn never needs the 1800 s default.
PROMPT_TIMEOUT = 300.0

GENERATION_SRC = "# The plate the drawing shows.\npart.geometry = Box(20.0, 10.0, 4.0)\n"
EDITING_SRC = (
    "# The supplied solid, with its long walls brought inward.\n"
    'base = import_step("input.step")\n'
    "part.geometry = base & Box(20.0, 6.0, 4.0)\n"
)


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


@pytest.fixture
def converted(tmp_path: Path) -> dict[str, BenchTask]:
    report = convert_samples(DATASET, tmp_path / "tasks", ids=["101", "201"])
    assert report.ok, [error.to_json() for error in report.refusals]
    return {task.id: task for task in report.tasks}


def tool_call(name: str, arguments: dict[str, Any], call_id: str) -> dict[str, Any]:
    return {"kind": "tool_calls", "calls": [{"name": name, "arguments": arguments, "id": call_id}]}


def last_tool_json(info: RequestInfo) -> Any:
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
                if isinstance(part, dict):
                    text = cast("dict[str, Any]", part).get("text")
                    if isinstance(text, str):
                        chunks.append(text)
                elif isinstance(part, str):
                    chunks.append(part)
        for chunk in chunks:
            try:
                parsed, _end = json.JSONDecoder().raw_decode(chunk.lstrip())
            except json.JSONDecodeError:
                continue
            return parsed
        return None
    return None


def last_tool_result(info: RequestInfo) -> dict[str, Any]:
    parsed = last_tool_json(info)
    assert isinstance(parsed, dict), parsed
    return cast("dict[str, Any]", parsed)


def build_script(fake: FakeOpenAI, *, source: str, opening: list[Any]) -> None:
    """The shared tail: create the part, write it, build it, report."""

    def create(info: RequestInfo) -> dict[str, Any]:
        assert last_tool_result(info).get("status") == "ok"
        return tool_call("create_part", {"name": PART_NAME, "template": "blank"}, "c8")

    def write(info: RequestInfo) -> dict[str, Any]:
        created = last_tool_result(info)
        return tool_call(
            "write_part",
            {"name": PART_NAME, "expected_hash": created["content_hash"], "script": source},
            "c9",
        )

    def build(info: RequestInfo) -> dict[str, Any]:
        assert last_tool_result(info).get("applied") is True
        return tool_call("build_part", {"name": PART_NAME}, "c10")

    def finish(info: RequestInfo) -> dict[str, Any]:
        assert last_tool_result(info).get("status") == "ok"
        return {"kind": "text", "chunks": ["built the part the sample asks for"]}

    fake.set_script([*opening, create, write, build, finish])


def generation_script(fake: FakeOpenAI) -> None:
    def read_drawing(info: RequestInfo) -> dict[str, Any]:
        listing = last_tool_json(info)
        assert isinstance(listing, list), listing
        names = {str(cast("dict[str, Any]", e)["name"]) for e in cast("list[Any]", listing)}
        assert names == {"input.png"}, listing
        return tool_call("read_reference", {"name": "input.png"}, "c1")

    def record(info: RequestInfo) -> dict[str, Any]:
        drawing = last_tool_result(info)
        assert drawing.get("kind") == "image", drawing
        return tool_call(
            "record_requirements",
            {
                "entries": [
                    {
                        "id": "R1",
                        "text": "the plate is 20 x 10 x 4 mm",
                        "source": "specified",
                        "cite": {"reference": "input.png", "quote": "20 x 10 x 4"},
                    }
                ]
            },
            "c2",
        )

    build_script(
        fake,
        source=GENERATION_SRC,
        opening=[tool_call("list_references", {}, "c0"), read_drawing, record],
    )


def editing_script(fake: FakeOpenAI) -> None:
    build_script(
        fake,
        source=EDITING_SRC,
        opening=[
            tool_call(
                "record_requirements",
                {
                    "entries": [
                        {
                            "id": "R1",
                            "text": "the two long walls move inward by 2 mm",
                            "source": "specified",
                            "quote": "Bring the two long walls of the plate inward by 2mm.",
                            "value": 2.0,
                            "unit": "mm",
                        }
                    ]
                },
                "c0",
            )
        ],
    )


def run_one(
    task: BenchTask,
    *,
    fake: FakeOpenAI,
    provider: ProviderConfig,
    runtime_factory: harness.RuntimeFactory,
    archive: Path,
) -> harness.RunRecord:
    record = harness.run_task(
        task,
        1,
        provider=provider,
        archive_dir=archive,
        runtime_factory=runtime_factory,
        prompt_timeout=PROMPT_TIMEOUT,
        date="2026-07-28",
    )
    assert record.error is None, record.error
    assert record.passed, record.reasons
    return record


def test_both_converted_samples_run_and_produce_step_through_the_export_path(
    tmp_path: Path,
    converted: dict[str, BenchTask],
    fake_model: FakeOpenAI,
    provider: ProviderConfig,
    runtime_factory: harness.RuntimeFactory,
) -> None:
    archive = tmp_path / "results" / provider.model_slug / "2026-07-28"

    generation_script(fake_model)
    generation = run_one(
        converted["cadgenbench-101"],
        fake=fake_model,
        provider=provider,
        runtime_factory=runtime_factory,
        archive=archive,
    )
    editing_script(fake_model)
    editing = run_one(
        converted["cadgenbench-201"],
        fake=fake_model,
        provider=provider,
        runtime_factory=runtime_factory,
        archive=archive,
    )

    # The editing run really was an ingest: the graded build names the seeded
    # file among its input hashes (INGEST.md §1).
    from hephaestus.agent_bridge.cad_ops import CadOps
    from hephaestus.core.project_store.layout import load_project, open_store

    project = Path(cast("str", editing.project_dir))
    layout = load_project(project)
    store = open_store(layout)
    try:
        current = CadOps(layout, store).current_build(PART_NAME)
        assert current is not None
        assert list(current.input_hashes.imports) == ["input.step"]
    finally:
        store.close()

    # …and both runs' STEPs come out of the grader's own export requirement.
    outputs = tmp_path / "outputs"
    outcome = collect_outputs([generation, editing], outputs)
    assert outcome.sample_ids == ("101", "201")
    for sample_id, volume in (("101", 800.0), ("201", 480.0)):
        candidate = outputs / sample_id / "output.step"
        assert candidate.is_file(), outcome.to_json()
        facts = step_validity(candidate)
        assert facts.ok, facts.to_json()
        assert facts.volume_mm3 == pytest.approx(volume, rel=1e-6)

    # The submission the benchmark would receive, assembled from those bytes.
    report = package_submission(
        outputs,
        ("101", "201"),
        SubmissionMeta(
            submitter_name="Hephaestus",
            submission_name="stage 8d smoke",
            agree_to_publish=True,
        ),
        tmp_path / "submission.zip",
    )
    with zipfile.ZipFile(report.zip_path) as archive_file:
        assert sorted(archive_file.namelist()) == [
            "101/",
            "101/output.step",
            "201/",
            "201/output.step",
            "meta.json",
        ]

    floor = score_outputs(outputs, ("101", "201"), dataset_root=DATASET)
    assert (floor.n_valid, floor.n_invalid, floor.n_missing) == (2, 0, 0)
    assert "local floor" in floor.label
