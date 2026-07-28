"""G8D: sample -> bench task conversion (``EXTERNAL_EVAL.md`` §2).

Gate clauses: *conversion produces a valid bench task per sample (generation
seeds the drawing as a reference image and the prompt verbatim; editing seeds
``imports/`` and the instruction verbatim; ``description.yaml`` task typing
respected; a malformed sample refused with a named reason, never skipped
silently)*.

What is actually asserted is the honesty property, not the file shuffling: the
benchmark's own sentence must reach the model **unmodified and quoted**, and
every word the harness adds must sit outside the provenance delimiters. A
conversion that paraphrased the statement — or slipped a dimension into the
framing — would make this harness a co-author of the benchmark's answers, which
is the single failure an external gate exists to rule out.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from _g8d import DATASET, EDIT_INSTRUCTION, GENERATION_DESCRIPTION
from hephaestus.bench.cadgenbench import (
    PART_NAME,
    SAMPLE_PROVENANCE_FILENAME,
    ConversionReport,
    SampleError,
    convert_sample,
    convert_samples,
    discover_samples,
    load_sample,
    sample_id_for_task,
    sample_prompt,
)
from hephaestus.core.registry import REFERENCE_END, REFERENCE_START


def quoted_block(prompt: str) -> str:
    """The text between the provenance delimiters, exactly."""
    start = prompt.index(REFERENCE_START)
    body = prompt.index(">>>", start) + len(">>>")
    end = prompt.index(REFERENCE_END, body)
    return prompt[body:end].strip("\n")


# ==========================================================================
# reading the sample


def test_task_typing_is_respected_including_the_absent_generation_default() -> None:
    """``task_type`` is absent on every real generation sample; it defaults."""
    assert "task_type" not in (DATASET / "101" / "description.yaml").read_text(encoding="utf-8")

    generation = load_sample(DATASET / "101")
    editing = load_sample(DATASET / "201")

    assert generation.task_type == "generation"
    assert editing.task_type == "editing"
    assert generation.images == ("input.png",)
    assert editing.step_inputs == ("input.step",)
    # The folded YAML block's trailing newline is stripped once, at the source.
    assert generation.description == GENERATION_DESCRIPTION
    assert editing.description == EDIT_INSTRUCTION


def test_multi_image_samples_are_driven_off_input_files() -> None:
    """A second drawing is found because ``input_files`` names it, not by luck."""
    sample = load_sample(DATASET / "102")
    assert sample.images == ("input.png", "input2.png")


def test_sample_ids_are_enumerated_not_generated() -> None:
    ids = discover_samples(DATASET)
    assert ids == ("101", "102", "201", "301", "302")


# ==========================================================================
# the converted task


def test_a_generation_sample_seeds_the_drawing_and_quotes_the_prompt(tmp_path: Path) -> None:
    sample = load_sample(DATASET / "101")

    task = convert_sample(sample, tmp_path / "tasks")

    assert task.id == "cadgenbench-101"
    # INGEST.md §2: the drawing is seeded as a reference, registered at seed time.
    assert (task.seed_dir / "references" / "input.png").is_file()
    assert not (task.seed_dir / "imports").exists()
    # …and the sample's sentence arrives verbatim, inside the delimiters.
    assert quoted_block(task.prompt) == GENERATION_DESCRIPTION
    assert task.prompt.count(GENERATION_DESCRIPTION) == 1
    assert PART_NAME in task.prompt
    assert [e.part for e in task.exports] == [PART_NAME]
    assert [e.fmt for e in task.exports] == ["step"]


def test_an_editing_sample_seeds_imports_and_quotes_the_instruction(tmp_path: Path) -> None:
    sample = load_sample(DATASET / "201")

    task = convert_sample(sample, tmp_path / "tasks")

    # INGEST.md §1: the starting solid is a file the build resolves.
    assert (task.seed_dir / "imports" / "input.step").is_file()
    assert not (task.seed_dir / "references").exists()
    assert quoted_block(task.prompt) == EDIT_INSTRUCTION
    assert 'import_step("input.step")' in task.prompt


def test_the_harness_adds_nothing_inside_the_quotation() -> None:
    """Everything we say is outside the delimiters; the sample's text is untouched."""
    for sample_id, statement in (("101", GENERATION_DESCRIPTION), ("201", EDIT_INSTRUCTION)):
        prompt = sample_prompt(load_sample(DATASET / sample_id))
        assert quoted_block(prompt) == statement
        # The framing names the benchmark and never restates the geometry.
        head = prompt[: prompt.index(REFERENCE_START)]
        assert "CADGenBench" in head
        assert statement not in head


def test_a_multi_image_sample_seeds_every_drawing_it_declares(tmp_path: Path) -> None:
    """Three real generation samples ship ``input2.png``; both must reach the run."""
    sample = load_sample(DATASET / "102")

    task = convert_sample(sample, tmp_path / "tasks")

    references = task.seed_dir / "references"
    assert sorted(p.name for p in references.iterdir()) == ["input.png", "input2.png"]
    # …and the framing names both, so the model is not told there is one drawing.
    for name in ("input.png", "input2.png"):
        assert name in task.prompt


def test_the_converted_task_carries_its_sample_provenance(tmp_path: Path) -> None:
    """Packaging maps a run back to a submission folder by record, not by string luck."""
    task = convert_sample(load_sample(DATASET / "201"), tmp_path / "tasks")

    sidecar = json.loads((task.directory / SAMPLE_PROVENANCE_FILENAME).read_text(encoding="utf-8"))
    assert sidecar["sample_id"] == "201"
    assert sidecar["task_type"] == "editing"
    assert sidecar["description"] == EDIT_INSTRUCTION
    assert Path(sidecar["source_dir"]) == DATASET / "201"
    assert sample_id_for_task(task.id) == "201"


def test_a_foreign_task_id_is_not_read_as_a_sample() -> None:
    """A corpus run must never be mistaken for a submission folder."""
    with pytest.raises(ValueError, match="not a converted CADGenBench task id"):
        sample_id_for_task("drawing-shelf")


def test_the_converted_task_round_trips_through_the_strict_corpus_loader(tmp_path: Path) -> None:
    """The task the runner uses is the task that was written, strictly parsed."""
    task = convert_sample(load_sample(DATASET / "201"), tmp_path / "tasks")

    spec = json.loads((task.directory / "task.json").read_text(encoding="utf-8"))
    assert spec["id"] == task.id
    assert spec["budget_tool_calls"] == task.budget_tool_calls
    assert "Mecado" in spec["notes"]  # ODC-BY attribution travels with the task


# ==========================================================================
# refusals


@pytest.mark.parametrize(
    ("sample_id", "reason"),
    [("301", "missing_input_file"), ("302", "unknown_task_type")],
)
def test_a_malformed_sample_is_refused_by_name(sample_id: str, reason: str) -> None:
    with pytest.raises(SampleError) as excinfo:
        load_sample(DATASET / sample_id)

    assert excinfo.value.reason == reason
    assert excinfo.value.sample_id == sample_id


def test_a_malformed_sample_is_reported_never_silently_skipped(tmp_path: Path) -> None:
    report = convert_samples(DATASET, tmp_path / "tasks")

    assert isinstance(report, ConversionReport)
    assert [task.id for task in report.tasks] == [
        "cadgenbench-101",
        "cadgenbench-102",
        "cadgenbench-201",
    ]
    assert {error.sample_id: error.reason for error in report.refusals} == {
        "301": "missing_input_file",
        "302": "unknown_task_type",
    }
    # A pass that refused anything is not an ok pass: the CLI exits non-zero.
    assert report.ok is False
    document = report.to_json()
    assert [row["sample_id"] for row in document["refusals"]] == ["301", "302"]


def test_an_input_file_outside_the_sample_folder_is_refused(tmp_path: Path) -> None:
    """Traversal in ``input_files`` is a refusal, not a copy from anywhere."""
    sample_dir = tmp_path / "999"
    sample_dir.mkdir()
    (sample_dir / "description.yaml").write_text(
        "description: >\n  Reproduce it.\n\ninput_files:\n  - ../../etc/passwd\n\n"
        "input_type: text+image\n",
        encoding="utf-8",
    )

    with pytest.raises(SampleError) as excinfo:
        load_sample(sample_dir)

    assert excinfo.value.reason == "unsafe_input_file"
