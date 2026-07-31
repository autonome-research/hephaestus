# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""G8B: ``score_step_files`` and the import boundary under it (``COMPARE.md`` §3).

Gate clauses:

* *``score_step_files`` over two fixture STEP files with a policy*;
* *the import-boundary proof that scoring reaches nothing outside
  ``hephaestus.geom``*.

The boundary is the load-bearing half. CADGenBench scoring must run where the
executor, the project store and the agent bridge do not exist, so the proof is a
**fresh interpreter** that imports the scorer, actually scores two files, and
then reports its own ``sys.modules``: a scorer that quietly reached into the
engine would fail here even though its numbers were right.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from _g8b import HOLE_MM3, PLATE_MM3, StepFixtures
from hephaestus.bench import scoring as scoring_module
from hephaestus.bench.scoring import StepScorePolicy, score_step_files

#: Prefixes a scoring interpreter must never load (COMPARE.md §3).
FORBIDDEN_PREFIXES = (
    "hephaestus.core.executor",
    "hephaestus.core.project_store",
    "hephaestus.core.checks",
    "hephaestus.core.render",
    "hephaestus.core.cli",
    "hephaestus.agent_bridge",
    "hephaestus.mcp",
)

#: ``opstore`` is deliberately absent from the list above, on the same terms
#: ``hephaestus.geom`` already states: geometry may name ``opstore.types`` for
#: the ``JSONValue`` alias, and importing it executes the package ``__init__``.
#: The claim being proven here is about the ENGINE — executor, store, checks,
#: bridge — which is what an external scorer will not have.


@pytest.fixture
def files(tmp_path: Path, steps: StepFixtures) -> dict[str, Path]:
    """The fixture STEP bytes on disk, the way a submission would arrive."""
    out: dict[str, Path] = {}
    for name, data in (
        ("plate", steps.plate),
        ("plate_moved", steps.plate_moved),
        ("plate_holed", steps.plate_holed),
        ("plate_taller", steps.plate_taller),
    ):
        path = tmp_path / f"{name}.step"
        path.write_bytes(data)
        out[name] = path
    return out


# ==========================================================================
# the verdict


def test_an_identical_submission_passes_its_policy(files: dict[str, Path]) -> None:
    score = score_step_files(
        files["plate"], files["plate"], {"iou_min": 0.995, "chamfer_max_mm": 0.01}
    )

    assert score.passed is True
    assert [row["name"] for row in score.criteria] == ["iou_min", "chamfer_max_mm"]
    assert all(bool(row["passed"]) for row in score.criteria)
    # Every underlying fact is attached, not just the verdict.
    volume = score.diff["volume"]
    assert volume["iou"] == pytest.approx(1.0, abs=1e-9)
    assert score.diff["a_volume_mm3"] == pytest.approx(PLATE_MM3, rel=1e-6)


def test_a_wrong_submission_fails_and_says_by_how_much(files: dict[str, Path]) -> None:
    score = score_step_files(files["plate_holed"], files["plate"], {"iou_min": 0.995})

    assert score.passed is False
    (row,) = score.criteria
    assert row["name"] == "iou_min" and row["threshold"] == 0.995
    # The missing hole is the whole disagreement, and it is measured.
    assert row["measured"] == pytest.approx(1.0 - HOLE_MM3 / PLATE_MM3, rel=1e-2)
    assert score.diff["volume"]["b_only_mm3"] == pytest.approx(HOLE_MM3, rel=1e-3)


def test_the_policy_decides_whether_pose_counts(files: dict[str, Path]) -> None:
    """The same two files, two questions, two correct answers."""
    as_posed = score_step_files(files["plate_moved"], files["plate"], {"iou_min": 0.9})
    principal = score_step_files(
        files["plate_moved"], files["plate"], {"iou_min": 0.9, "align": "principal"}
    )

    assert as_posed.passed is False
    assert principal.passed is True
    assert as_posed.policy.align == "as_posed"
    assert principal.diff["align"] == "principal"


def test_a_policy_that_names_no_tolerance_yields_no_verdict(files: dict[str, Path]) -> None:
    """An unstated threshold is a missing claim, never a satisfied one."""
    score = score_step_files(files["plate"], files["plate_taller"], None)

    assert score.passed is None
    assert score.criteria == ()
    # …and the facts are there for whoever does own the threshold.
    assert score.diff["volume"]["iou"] < 1.0


def test_an_unreadable_submission_scores_zero_rather_than_raising(
    tmp_path: Path, files: dict[str, Path]
) -> None:
    broken = tmp_path / "broken.step"
    broken.write_bytes(b"ISO-10303-21;\nnot really\n")

    score = score_step_files(broken, files["plate"], {"iou_min": 0.9})

    assert score.passed is False
    assert score.error is not None
    assert score.diff == {}


def test_a_broken_ground_truth_is_a_broken_task_and_raises(
    tmp_path: Path, files: dict[str, Path]
) -> None:
    """A submission may be nonsense; the task's own truth file may not."""
    from hephaestus.geom.step_io import StepReadError

    broken = tmp_path / "truth.step"
    broken.write_bytes(b"ISO-10303-21;\nnot really\n")

    with pytest.raises(StepReadError):
        score_step_files(files["plate"], broken, {"iou_min": 0.9})


def test_the_score_serializes_with_its_policy_and_criteria(files: dict[str, Path]) -> None:
    score = score_step_files(files["plate"], files["plate"], StepScorePolicy(iou_min=0.9))

    reported = score.to_json()
    assert json.loads(json.dumps(reported))["passed"] is True
    assert reported["policy"] == {"iou_min": 0.9, "chamfer_max_mm": None, "align": "as_posed"}
    assert reported["diff"]["surface"]["a_samples"] > 0


def test_an_unknown_alignment_in_a_policy_is_refused(files: dict[str, Path]) -> None:
    with pytest.raises(ValueError):
        score_step_files(files["plate"], files["plate"], {"align": "whatever"})


# ==========================================================================
# the boundary


_BOUNDARY_PROGRAM = """
import json, sys
from hephaestus.bench.scoring import score_step_files

score = score_step_files(sys.argv[1], sys.argv[2], {"iou_min": 0.5})
print(json.dumps({"passed": score.passed, "modules": sorted(sys.modules)}))
"""


def test_scoring_names_no_engine_module_statically() -> None:
    """The scorer's own source imports geom and nothing else from hephaestus."""
    import ast

    source = Path(scoring_module.__file__ or "").read_text(encoding="utf-8")
    named: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            named.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            named.add(node.module)
    hephaestus_modules = sorted(name for name in named if name.startswith("hephaestus."))
    assert hephaestus_modules == ["hephaestus.geom.compare", "hephaestus.geom.step_io"]


def test_scoring_reaches_nothing_outside_geom(files: dict[str, Path]) -> None:
    """A fresh interpreter scores two files without loading the engine."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            textwrap.dedent(_BOUNDARY_PROGRAM),
            str(files["plate_holed"]),
            str(files["plate"]),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, f"scoring failed in a fresh interpreter:\n{result.stderr}"
    reported = json.loads(result.stdout)
    assert reported["passed"] is True  # it really scored, it did not no-op
    forbidden = sorted(
        name
        for name in reported["modules"]
        if any(name == prefix or name.startswith(prefix + ".") for prefix in FORBIDDEN_PREFIXES)
    )
    assert not forbidden, "bench scoring pulled in forbidden modules:\n" + "\n".join(forbidden)
    assert "hephaestus.geom.compare" in reported["modules"]
    assert "hephaestus.geom.step_io" in reported["modules"]


def test_boolean_failure_scores_zero_with_reason(
    monkeypatch: pytest.MonkeyPatch, files: dict[str, Path]
) -> None:
    """A kernel-failed boolean is a failed score with the reason, not a crash.

    Regression: a CADGenBench editing candidate drove the comparison boolean to
    a null TopoDS result and the exception escaped through score_step_files,
    killing the whole 81-sample local-floor report (2026-07-29).
    """
    import hephaestus.geom.compare as compare
    from hephaestus.geom.compare import CompareBooleanError

    def failing_diff(*args: object, **kwargs: object) -> object:
        raise CompareBooleanError("cut")

    monkeypatch.setattr(compare, "solid_diff", failing_diff)
    score = score_step_files(
        files["plate_holed"], files["plate"], {"iou_min": 0.5, "align": "as_posed"}
    )
    assert score.passed is False
    assert score.error is not None and "OCCT boolean failure" in score.error
