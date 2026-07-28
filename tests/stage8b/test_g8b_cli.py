# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""G8B: the ``heph diff`` operator CLI, human and ``--json`` (``COMPARE.md`` §2).

Gate clause: *``heph diff`` CLI (human + ``--json``)*.

The operator and the model must see the *same* comparison: the JSON form here is
asserted to be exactly the ``compare_solids`` result document, because a number
an operator quotes and a number a model read have to be the same number or the
evidence trail forks.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from _g8b import StepFixtures, build_ok, install_import, write_script
from hephaestus.core.cli import main
from hephaestus.testing.tools_fixture import Project

PLATE_SRC = "part.geometry = Box(40.0, 20.0, 5.0)\n"
HOLED_SRC = "part.geometry = Box(40.0, 20.0, 5.0) - Cylinder(3.0, 20.0)\n"
MOVED_SRC = (
    "body = Box(40.0, 20.0, 5.0).moved(Location((13.0, -7.0, 4.0)))\n"
    "part.geometry = body.moved(Rotation(0.0, 0.0, 35.0))\n"
)


def run(root: Path, monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    monkeypatch.chdir(root)
    return main(list(argv))


@pytest.fixture
def built(project: Project, steps: StepFixtures) -> Project:
    """A project with two built parts and the plate seeded under ``imports/``."""
    install_import(project.root, "plate.step", steps.plate)
    write_script(project, "plate", PLATE_SRC)
    write_script(project, "holed", HOLED_SRC)
    write_script(project, "moved", MOVED_SRC)
    build_ok(project, "plate")
    build_ok(project, "holed")
    build_ok(project, "moved")
    # The store is reopened by the CLI in the same process; release the lock.
    project.store.close()
    return project


def test_human_output_reports_every_family_of_fact(
    built: Project, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(built.root, monkeypatch, "diff", "holed", "part:plate") == 0

    out = capsys.readouterr().out
    assert "align: as_posed" in out
    for heading in ("volume (mm^3)", "surface (mm)", "topology (delta = b - a)"):
        assert heading in out
    assert "iou" in out and "chamfer" in out
    # Sample counts are printed, so a coarse grid is visible without --json.
    assert "samples" in out
    # Both operands are named with the evidence they were read from.
    assert "a: part:holed (artifact:build:sha256:" in out
    assert "b: part:plate (artifact:build:sha256:" in out


def test_json_output_is_the_tool_result_document(
    built: Project, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(built.root, monkeypatch, "diff", "holed", "import:plate.step", "--json") == 0

    reported = cast("dict[str, Any]", json.loads(capsys.readouterr().out))
    assert reported["status"] == "ok"
    assert reported["align"] == "as_posed"
    assert cast("dict[str, Any]", reported["a"]) == {
        "kind": "part",
        "name": "holed",
        "artifact_ref": cast("dict[str, Any]", reported["a"])["artifact_ref"],
    }
    b = cast("dict[str, Any]", reported["b"])
    assert b["kind"] == "import" and b["path"] == "plate.step"
    assert b["sha256"].startswith("sha256:")
    diff = cast("dict[str, Any]", reported["diff"])
    assert set(diff) == {
        "align",
        "volume",
        "surface",
        "topology",
        "a_bbox_mm",
        "b_bbox_mm",
        "a_volume_mm3",
        "b_volume_mm3",
    }
    assert cast("dict[str, Any]", diff["volume"])["iou"] < 1.0  # the hole is missing from b


def test_principal_alignment_is_selectable_and_says_what_it_did(
    built: Project, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(built.root, monkeypatch, "diff", "moved", "part:plate", "--align", "principal") == 0

    out = capsys.readouterr().out
    assert "align: principal" in out
    # The bboxes printed next to a principal comparison are the shapes as the
    # caller posed them; the report says so rather than letting them be misread.
    assert "bboxes are as-posed" in out


def test_an_unresolvable_target_exits_one_with_a_named_error(
    built: Project, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(built.root, monkeypatch, "diff", "holed", "import:absent.step") == 1

    err = capsys.readouterr().err
    assert "heph: error" in err
    assert "absent.step" in err


def test_a_traversing_target_is_refused_by_the_cli_too(
    built: Project, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (built.root / "secret.txt").write_text("SECRET-CONTENT-42\n", encoding="utf-8")

    assert run(built.root, monkeypatch, "diff", "holed", "import:../secret.txt") == 1

    err = capsys.readouterr().err
    assert "SECRET-CONTENT-42" not in err
