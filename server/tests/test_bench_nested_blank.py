"""Grading a ``nested_sheet`` export: the blank comes from the requirement.

The bench defect these pin (``gpt-5.6-sol``, 2026-07-26, ``nest-gusset`` seeds
1-3): the run's own ``export_part(layout="nested_sheet")`` succeeded and wrote a
nested DXF, and grading then re-exported *without* passing a blank. Resolution
therefore fell through to the part's own ``part.blank_size``, which that run had
not authored, and every seed was failed with

    export_failed:gusset:dxf -> CadOpError: part 'gusset' declares no
    part.blank_size for the exported artifact

— our grading path failing a correct run, on a precondition nothing had named.
The requirement being graded *carries* the blank (``ExportRequirement.blank_mm``,
the 210 x 125 the task names), so the grader passes it and nests onto the stock
the task requires.

Whether the run declared that stock is a real requirement of this task — the
prompt asks for it in as many words — and it is now gated as the metadata
property it is (``MetadataRequirement.blank_mm``), failing under its own name.
``VALIDATION.md`` §1: a check asserts a functional property and fails for the
reason it is named after.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import pytest
from hephaestus.bench.harness import (
    BenchTask,
    ExportRequirement,
    GradeReport,
    MetadataRequirement,
    corpus_solutions_dir,
    grade,
    load_tasks,
    seed_project,
)

#: The declaration line the reference gusset authors, and the failure shape the
#: archived runs carried when grading read it instead of the requirement.
BLANK_DECLARATION = 'part.blank_size = "210 x 125 mm blank, one set per blank"\n'
ARCHIVED_FAILURE = "declares no part.blank_size"

#: The stock ``nest-gusset`` names, and what a whole sheet would be instead.
REQUIRED_BLANK = (210.0, 125.0)
WHOLE_SHEET = "2500 x 1250 mm sheet"


@pytest.fixture(scope="module")
def task() -> BenchTask:
    (loaded,) = load_tasks(["nest-gusset"])
    return loaded


def _reference_source() -> str:
    source = (corpus_solutions_dir() / "nest-gusset" / "parts" / "gusset.py").read_text(
        encoding="utf-8"
    )
    assert BLANK_DECLARATION in source, "the reference solution declares its blank"
    return source


def _project(task: BenchTask, root: Path, source: str) -> Path:
    seed_project(task, root)
    (root / "parts").mkdir(exist_ok=True)
    (root / "parts" / "gusset.py").write_text(source, encoding="utf-8")
    return root


def _export_record(report: GradeReport) -> Mapping[str, Any]:
    assert len(report.exports) == 1, report.exports
    return report.exports[0]


def _blank_extents(record: Mapping[str, Any]) -> tuple[float, float]:
    extents = cast("list[float]", record["blank_extents"])
    return (round(extents[2] - extents[0], 3), round(extents[3] - extents[1], 3))


def test_a_nested_export_grades_on_the_requirements_blank_not_the_parts(
    task: BenchTask, tmp_path: Path
) -> None:
    """The defect, reproduced on its own geometry and then absent.

    The reference gusset stripped of exactly one line — its ``part.blank_size``
    — is the state all three archived seeds were in. The nested export must
    still be produced and still validate, nested on the 210 x 125 the
    requirement names, and the *only* thing that fails is the declaration the
    prompt separately asks for, under a name that says so.
    """
    root = _project(
        task, tmp_path / "undeclared", _reference_source().replace(BLANK_DECLARATION, "")
    )
    report = grade(task, root)

    record = _export_record(report)
    assert ARCHIVED_FAILURE not in str(record.get("error", "")), record
    assert "error" not in record, record
    assert "invalid" not in record, record
    assert int(cast("int", record["bytes"])) > 0
    assert record["profile_count"] == 3
    # The blank actually nested onto is the required one, read back off the
    # exported bytes rather than taken from the call.
    assert _blank_extents(record) == REQUIRED_BLANK
    assert not [r for r in report.reasons if r.startswith("export_")], report.reasons
    # …and the geometry checks are untouched, so one thing fails, by its name.
    assert report.check_status == "ok"
    assert "metadata_missing:gusset:blank_size" in report.reasons
    assert [r for r in report.reasons if not r.startswith("metadata_")] == []
    assert not report.passed


def test_a_part_that_declares_its_own_blank_still_grades_green(
    task: BenchTask, tmp_path: Path
) -> None:
    """The reference path is unchanged: declared blank, same nested result."""
    root = _project(task, tmp_path / "declared", _reference_source())
    report = grade(task, root)

    assert report.passed, report.reasons
    record = _export_record(report)
    assert record["profile_count"] == 3
    assert _blank_extents(record) == REQUIRED_BLANK
    # The declaration was read, parsed and matched against the requirement.
    (metadata,) = report.metadata
    assert metadata["missing_fields"] == []
    assert metadata["blank_mm"] == list(REQUIRED_BLANK)


def test_declaring_a_whole_sheet_fails_the_metadata_check_by_name(
    task: BenchTask, tmp_path: Path
) -> None:
    """A run cannot pass by calling the stock a full sheet.

    That defence used to live in the export (the grader let ``part.blank_size``
    pick the stock, then measured the drawn rectangle). Now the export nests on
    the required blank, so the declaration is judged where it is made — and the
    failure names the stock declared and the stock required, not a nesting
    error.
    """
    root = _project(
        task,
        tmp_path / "whole-sheet",
        _reference_source().replace("210 x 125 mm blank, one set per blank", WHOLE_SHEET),
    )
    report = grade(task, root)

    assert not report.passed
    assert "metadata_blank_size:gusset:2500.0x1250.0!=210.0x125.0" in report.reasons
    # The geometry is untouched and the export is unaffected by the wrong claim.
    assert [r for r in report.reasons if not r.startswith("metadata_")] == []
    assert _blank_extents(_export_record(report)) == REQUIRED_BLANK


def test_the_declared_blank_is_gated_structurally_not_by_wording(
    task: BenchTask, tmp_path: Path
) -> None:
    """``part.blank_size`` is free text by contract: the ``W x H`` is the claim."""
    root = _project(
        task,
        tmp_path / "reworded",
        _reference_source().replace(
            "210 x 125 mm blank, one set per blank",
            "one gusset set per 210x125 laser blank (grain along X)",
        ),
    )
    report = grade(task, root)

    assert report.passed, report.reasons
    assert report.metadata[0]["blank_mm"] == list(REQUIRED_BLANK)


def test_the_corpus_task_gates_the_blank_it_nests_on(task: BenchTask) -> None:
    """Both halves of the 210 x 125, gated on the two claims it makes."""
    (export,) = task.exports
    assert export.layout == "nested_sheet"
    assert export.blank_mm == REQUIRED_BLANK
    (metadata,) = task.metadata
    assert metadata.blank_mm == REQUIRED_BLANK
    assert "blank_size" in metadata.required_fields


def test_a_required_blank_only_parses_on_the_layout_that_nests() -> None:
    """A blank that gates nothing may not be written as though it gated something.

    ``export_part`` uses ``blank`` only when nesting, and the ``BLANK`` layer the
    fit test reads back is only drawn by the nested layout — so a blank on an
    ``as_built`` export is a requirement that cannot fail for its stated reason.
    """
    nested = {
        "part": "gusset",
        "format": "dxf",
        "layout": "nested_sheet",
        "profile_layer": "PROFILES",
        "blank_mm": [210.0, 125.0],
    }
    assert ExportRequirement.from_json(nested).blank_mm == REQUIRED_BLANK
    with pytest.raises(ValueError, match="nested_sheet"):
        ExportRequirement.from_json({**nested, "layout": "as_built"})


def test_a_blank_requirement_must_also_require_the_field() -> None:
    """Absent and wrong are two failures, so the spec must carry both names."""
    with pytest.raises(ValueError, match="blank_size"):
        MetadataRequirement.from_json(
            {"part": "gusset", "required_fields": ["description"], "blank_mm": [210.0, 125.0]}
        )
    parsed = MetadataRequirement.from_json(
        {"part": "gusset", "required_fields": ["blank_size"], "blank_mm": [210.0, 125.0]}
    )
    assert parsed.blank_mm == REQUIRED_BLANK
    assert parsed.to_json()["blank_mm"] == [210.0, 125.0]
