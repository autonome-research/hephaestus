"""G8D: the local pre-score (``EXTERNAL_EVAL.md`` §2, "Local pre-score").

Gate clause: *the local pre-score reports geom validity + available
``score_step_files`` facts labeled as a local floor*.

The load-bearing assertion is the label. CADGenBench's ground truth is private,
so nothing computed here can be a CAD Score, and a number printed next to a
leaderboard's name without that said out loud is an invitation to misread it.
So the suite asserts the words, and asserts that the only reference geometry the
public dataset ships — an editing sample's own starting solid — is reported
*as* the starting solid, never as agreement with a truth we do not have.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _g8d import DATASET, STEPS, outputs_with
from hephaestus.bench.cadgenbench import LOCAL_FLOOR_LABEL, score_outputs

SAMPLES = ("101", "102", "201")


def test_the_floor_reports_validity_per_sample_and_says_what_it_is(tmp_path: Path) -> None:
    outputs = outputs_with(
        tmp_path / "outputs",
        {"101": STEPS / "plate.step", "102": STEPS / "open_face.step", "201": None},
    )

    floor = score_outputs(outputs, SAMPLES)

    assert {e.sample_id: e.status for e in floor.entries} == {
        "101": "valid",
        "102": "invalid",
        "201": "missing",
    }
    assert (floor.n_valid, floor.n_invalid, floor.n_missing) == (1, 1, 1)
    document = floor.to_json()
    assert document["label"] == LOCAL_FLOOR_LABEL
    assert "local floor" in document["label"]
    assert "NOT the CADGenBench cad_score" in document["label"]
    # …and the facts are really facts, not a verdict.
    plate = next(e for e in floor.entries if e.sample_id == "101")
    assert plate.validity is not None
    assert plate.validity.volume_mm3 == pytest.approx(800.0, rel=1e-6)


def test_editing_samples_are_measured_against_their_own_starting_solid(tmp_path: Path) -> None:
    outputs = outputs_with(
        tmp_path / "outputs",
        {"101": STEPS / "plate.step", "102": None, "201": STEPS / "edited.step"},
    )

    floor = score_outputs(outputs, SAMPLES, dataset_root=DATASET, policy={"iou_min": 0.5})

    edited = next(e for e in floor.entries if e.sample_id == "201")
    assert edited.reference == "editing_start"
    assert edited.step_score is not None
    assert edited.note is not None and "not ground truth" in edited.note
    # 20x6x4 inside 20x10x4: the edit really happened, and the fact says so.
    diff = edited.step_score["diff"]
    assert diff["volume"]["iou"] == pytest.approx(0.6, abs=0.05)

    # A generation sample ships no reference geometry at all: no score is
    # invented for it, and the absence is visible.
    generation = next(e for e in floor.entries if e.sample_id == "101")
    assert generation.reference is None
    assert generation.step_score is None


def test_the_operator_facing_output_says_local_floor_out_loud(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """§2: the *output* says "local floor" in so many words — not just the JSON."""
    from hephaestus.bench.cadgenbench import CACHE_ENV_VAR
    from hephaestus.core.cli import main as heph_main

    monkeypatch.setenv(CACHE_ENV_VAR, str(tmp_path / "empty-cache"))
    outputs = outputs_with(tmp_path / "outputs", {"101": STEPS / "plate.step", "201": None})

    code = heph_main(
        ["bench", "cadgenbench", "score", "--outputs", str(outputs), "--samples", "101,201"]
    )

    assert code == 0
    printed = capsys.readouterr().out
    assert "local floor" in printed
    assert "NOT the CADGenBench cad_score" in printed
    assert "cad_score" not in printed.replace("NOT the CADGenBench cad_score", "")
    assert "101" in printed and "valid" in printed

    # No dataset root is resolvable here, and that is not fatal: only the
    # editing-start facts go missing, per sample.
    assert heph_main(["bench", "cadgenbench", "score", "--outputs", str(outputs)]) == 1
    assert "cadgenbench" in capsys.readouterr().err


def test_the_floor_scores_a_broken_candidate_instead_of_crashing(tmp_path: Path) -> None:
    outputs = outputs_with(tmp_path / "outputs", {"201": STEPS / "broken.step"})

    floor = score_outputs(outputs, ("201",), dataset_root=DATASET)

    entry = floor.entries[0]
    assert entry.status == "invalid"
    assert entry.validity is not None and entry.validity.failures == ("unreadable_step",)
    assert entry.step_score is not None
    assert entry.step_score["passed"] is False
    assert entry.step_score["error"]
