"""Bench scoring: the Wilson gate statistic, the artifact, and the CLI verbs.

The Stage 2 gate is the one-sided lower 90% Wilson bound of the *aggregate* pass
rate, never the raw fraction (verification.md Tier 3, digest §8). The hand-worked
boundary cases below are the point of the whole module: at n = 24 (8 tasks x 3
seeds) 18 passes clear the 0.60 threshold and 17 do not, even though both raw
fractions (0.750 and 0.708) sit comfortably above it.

Nothing here starts a model, a sidecar or a CAD build: scoring an archived run
directory is pure arithmetic over JSON.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, cast

import pytest
from hephaestus.bench import cli_bench
from hephaestus.bench.harness import SEEDED_SUFFIX, dry_run, load_tasks, task_ids
from hephaestus.bench.scoring import (
    G2_AGGREGATE_THRESHOLD,
    PERFECT_TASKS,
    RUNS_FILENAME,
    SEEDED_BASELINE_FILENAME,
    Z_LOWER_90,
    load_run_records,
    record_seeded_baseline,
    score_directory,
    score_records,
    wilson_lower_bound,
    write_score,
)


def record(
    task_id: str,
    seed: int,
    *,
    passed: bool,
    tool_calls: int = 5,
    budget: int = 15,
    model: str = "ref-model",
    date: str = "2026-07-24",
) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "seed": seed,
        "model": model,
        "date": date,
        "passed": passed,
        "status": "completed",
        "tool_calls": tool_calls,
        "budget_tool_calls": budget,
        "reasons": [] if passed else ["check_failed:x"],
    }


# --------------------------------------------------------------------------
# the gate statistic


def test_z_constant_is_the_digest_value() -> None:
    assert pytest.approx(1.281552) == Z_LOWER_90
    assert G2_AGGREGATE_THRESHOLD == 0.60


@pytest.mark.parametrize(
    ("passes", "n", "expected"),
    [
        (18, 24, 0.623237),
        (17, 24, 0.579186),
        (24, 24, 0.935951),
        (20, 24, 0.715280),
        (0, 24, 0.0),
        (3, 3, 0.646221),
        (1, 1, 0.378447),
    ],
)
def test_wilson_lower_bound_hand_computed(passes: int, n: int, expected: float) -> None:
    assert wilson_lower_bound(passes, n) == pytest.approx(expected, abs=1e-6)


def test_wilson_boundary_decides_the_gate_where_the_raw_fraction_does_not() -> None:
    # Both raw fractions are above 0.60; only one survives the lower bound.
    assert min(18 / 24, 17 / 24) > G2_AGGREGATE_THRESHOLD
    assert wilson_lower_bound(18, 24) > G2_AGGREGATE_THRESHOLD
    assert wilson_lower_bound(17, 24) < G2_AGGREGATE_THRESHOLD


def test_wilson_matches_the_closed_form_and_is_monotonic() -> None:
    def closed_form(passes: int, n: int) -> float:
        p = passes / n
        z2 = Z_LOWER_90 * Z_LOWER_90
        centre = p + z2 / (2 * n)
        spread = Z_LOWER_90 * math.sqrt(p * (1.0 - p) / n + z2 / (4 * n * n))
        return (centre - spread) / (1.0 + z2 / n)

    previous = -1.0
    for passes in range(0, 25):
        value = wilson_lower_bound(passes, 24)
        assert value == pytest.approx(closed_form(passes, 24), abs=1e-12)
        assert value > previous
        previous = value
    # More evidence at the same rate never lowers the bound.
    assert wilson_lower_bound(48, 64) > wilson_lower_bound(18, 24)


def test_wilson_edge_cases() -> None:
    assert wilson_lower_bound(0, 0) == 0.0  # no evidence never passes a gate
    assert 0.0 <= wilson_lower_bound(0, 5) <= 1.0
    with pytest.raises(ValueError):
        wilson_lower_bound(5, 4)


# --------------------------------------------------------------------------
# aggregation + the artifact


def test_score_records_builds_the_per_task_table() -> None:
    records = [
        record("bracket-101", 1, passed=True, tool_calls=6),
        record("bracket-101", 2, passed=True, tool_calls=8),
        record("bracket-101", 3, passed=False, tool_calls=15),
        record("repair-fillet", 1, passed=True, tool_calls=3, budget=8),
        record("repair-fillet", 2, passed=True, tool_calls=4, budget=8),
        record("repair-fillet", 3, passed=True, tool_calls=3, budget=8),
    ]
    score = score_records(records)
    assert score.n == 6
    assert score.passes == 5
    assert score.aggregate == pytest.approx(5 / 6)
    assert score.wilson_lower_90 == pytest.approx(wilson_lower_bound(5, 6))
    bracket = score.per_task["bracket-101"]
    assert (bracket.n, bracket.passes) == (3, 2)
    assert bracket.pass_rate == pytest.approx(2 / 3)
    assert bracket.mean_tool_calls == pytest.approx((6 + 8 + 15) / 3)
    assert bracket.budget_tool_calls == 15
    assert score.model == "ref-model"
    assert score.date == "2026-07-24"


def test_gate_requires_both_the_bound_and_the_perfect_task() -> None:
    passing = [record(f"t{i // 3}", i, passed=i < 18) for i in range(24)]
    score = score_records(passing)
    assert score.wilson_lower_90 == pytest.approx(wilson_lower_bound(18, 24), abs=1e-9)
    # repair-fillet is absent entirely -> the perfect-task requirement fails.
    assert score.perfect_task_failures == PERFECT_TASKS
    assert not score.meets_gate

    with_perfect = [
        *[record("bracket-101", i, passed=i < 18) for i in range(24)],
        *[record("repair-fillet", i, passed=True, budget=8) for i in range(3)],
    ]
    good = score_records(with_perfect)
    assert good.perfect_task_failures == ()
    assert good.meets_gate

    one_short = [
        *[record("bracket-101", i, passed=i < 18) for i in range(24)],
        *[record("repair-fillet", i, passed=i > 0, budget=8) for i in range(3)],
    ]
    missed = score_records(one_short)
    assert missed.perfect_task_failures == ("repair-fillet",)
    assert not missed.meets_gate


def test_score_directory_reads_runs_index_then_falls_back(tmp_path: Path) -> None:
    archive = tmp_path / "ref-model" / "2026-07-24"
    archive.mkdir(parents=True)
    rows = [record("bracket-101", 1, passed=True), record("bracket-101", 2, passed=False)]
    (archive / RUNS_FILENAME).write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8"
    )
    assert len(load_run_records(archive)) == 2
    indexed = score_directory(archive)
    assert (indexed.n, indexed.passes) == (2, 1)

    # Without the index, the per-run result.json files still score.
    (archive / RUNS_FILENAME).unlink()
    for row in rows:
        run_dir = archive / f"{row['task_id']}-s{row['seed']}"
        run_dir.mkdir()
        (run_dir / "result.json").write_text(json.dumps(row), encoding="utf-8")
    recovered = score_directory(archive)
    assert (recovered.n, recovered.passes) == (2, 1)


def test_write_score_emits_the_leaderboard_artifact(tmp_path: Path) -> None:
    score = score_records([record("bracket-101", 1, passed=True)])
    target = write_score(score, tmp_path / "model" / "2026-07-24.json")
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["z"] == Z_LOWER_90
    assert payload["threshold"] == G2_AGGREGATE_THRESHOLD
    assert payload["n"] == 1 and payload["passes"] == 1
    assert payload["per_task"]["bracket-101"]["mean_tool_calls"] == 5.0
    assert set(payload) >= {"aggregate", "wilson_lower_90", "meets_gate", "per_task", "model"}


# --------------------------------------------------------------------------
# CLI verbs


def test_dry_run_plans_every_task_and_seed_without_a_model() -> None:
    tasks = load_tasks(["bracket-101", "repair-fillet"])
    plan = dry_run(tasks, seeds=3)
    assert len(plan) == 6
    assert {entry["task_id"] for entry in plan} == {"bracket-101", "repair-fillet"}
    assert {entry["seed"] for entry in plan} == {1, 2, 3}
    for entry in plan:
        assert entry["prompt"]
        assert entry["budget_tool_calls"] > 0
        assert entry["required_checks"]


def test_cli_bench_run_dry_run_lists_tasks(capsys: pytest.CaptureFixture[str]) -> None:
    code = cli_bench.main(["bench", "run", "--dry-run", "--seeds", "3", "--json"])
    assert code == 0
    plan = json.loads(capsys.readouterr().out)
    assert len(plan) == 3 * len(task_ids())
    assert {entry["task_id"] for entry in plan} == set(task_ids())


def test_cli_bench_run_requires_a_provider_when_not_dry(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = cli_bench.main(["bench", "run", "--tasks", "bracket-101", "--seeds", "1"])
    assert code == 2
    assert "--provider is required" in capsys.readouterr().err


def test_cli_bench_run_rejects_an_unknown_task(capsys: pytest.CaptureFixture[str]) -> None:
    code = cli_bench.main(["bench", "run", "--tasks", "no-such-task", "--dry-run"])
    assert code == 2
    assert "no corpus task" in capsys.readouterr().err


def test_cli_bench_score_writes_the_artifact_and_gates(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    archive = tmp_path / "ref-model" / "2026-07-24"
    archive.mkdir(parents=True)
    rows = [
        *[record("bracket-101", i, passed=i < 18) for i in range(24)],
        *[record("repair-fillet", i, passed=True, budget=8) for i in range(3)],
    ]
    (archive / RUNS_FILENAME).write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8"
    )
    code = cli_bench.main(["bench", "score", str(archive), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["meets_gate"] is True
    written = json.loads((archive.parent / "2026-07-24.json").read_text(encoding="utf-8"))
    assert written == payload

    # One failed repair-fillet seed fails the gate even with the same bound.
    (archive / RUNS_FILENAME).write_text(
        "".join(
            json.dumps(row, sort_keys=True) + "\n"
            for row in [
                *[record("bracket-101", i, passed=i < 18) for i in range(24)],
                *[record("repair-fillet", i, passed=i > 0, budget=8) for i in range(3)],
            ]
        ),
        encoding="utf-8",
    )
    assert cli_bench.main(["bench", "score", str(archive)]) == 1
    assert "required-perfect tasks failed" in capsys.readouterr().out


def test_cli_bench_score_rejects_a_missing_directory(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli_bench.main(["bench", "score", "/nonexistent/bench/archive"]) == 2
    assert "is not a directory" in capsys.readouterr().err


# --------------------------------------------------------------------------
# VALIDATION.md §1: the two splits are scored separately and never averaged


def seeded(task_id: str) -> str:
    return task_id + SEEDED_SUFFIX


def test_the_two_splits_are_tallied_separately() -> None:
    score = score_records(
        [
            record("bracket-101", 1, passed=True),
            record("bracket-101", 2, passed=False),
            record(seeded("bracket-101"), 1, passed=True),
            record(seeded("bracket-101"), 2, passed=True),
        ]
    )
    assert (score.prose.n, score.prose.passes) == (2, 1)
    assert (score.seeded.n, score.seeded.passes) == (2, 2)
    assert score.pass_rate_prose == pytest.approx(0.5)
    assert score.pass_rate_seeded == pytest.approx(1.0)
    assert score.interpretation_gap == pytest.approx(0.5)
    # The headline numbers are the prose split; the archive total is separate.
    assert (score.n, score.passes) == (2, 1)
    assert (score.n_total, score.passes_total) == (4, 3)


def test_a_seeded_run_never_moves_the_prose_gate() -> None:
    """The historical baseline stays comparable: seeding cannot change it."""
    prose_only = [record("bracket-101", i, passed=i < 18) for i in range(24)]
    before = score_records(prose_only)
    after = score_records(
        [*prose_only, *[record(seeded("bracket-101"), i, passed=True) for i in range(24)]]
    )
    assert after.wilson_lower_90 == before.wilson_lower_90
    assert (after.n, after.passes, after.aggregate) == (before.n, before.passes, before.aggregate)
    assert after.meets_gate == before.meets_gate


def test_the_seeded_split_carries_no_threshold_and_cannot_be_compared() -> None:
    score = score_records([record(seeded("bracket-101"), i, passed=True) for i in range(3)])
    assert score.seeded.threshold is None
    assert score.seeded.meets_threshold is None  # never False: nothing to meet
    assert score.prose.threshold == G2_AGGREGATE_THRESHOLD
    # A perfect seeded split with no prose evidence is not a passed gate.
    assert score.n == 0
    assert score.meets_gate is False
    assert score.interpretation_gap is None


def test_the_split_pass_rates_are_never_averaged_into_one_number() -> None:
    score = score_records(
        [
            *[record("bracket-101", i, passed=False) for i in range(4)],
            *[record(seeded("bracket-101"), i, passed=True) for i in range(4)],
        ]
    )
    payload = score.to_json()
    assert payload["pass_rate_prose"] == 0.0
    assert payload["pass_rate_seeded"] == 1.0
    assert payload["gated_split"] == "prose"
    # The one aggregate that exists is the prose split's, not the mean of the two.
    assert payload["aggregate"] == 0.0
    assert payload["interpretation_gap"] == 1.0


def test_the_seeded_baseline_is_recorded_once_and_never_re_baselined(tmp_path: Path) -> None:
    first = score_records([record(seeded("bracket-101"), i, passed=i < 2) for i in range(3)])
    path = tmp_path / SEEDED_BASELINE_FILENAME
    baseline = record_seeded_baseline(first, path)
    assert baseline is not None
    assert (baseline["n"], baseline["passes"]) == (3, 2)
    assert baseline["threshold"] is None

    # A later, better measurement does not move the baseline.
    later = score_records([record(seeded("bracket-101"), i, passed=True) for i in range(3)])
    assert record_seeded_baseline(later, path) == baseline
    assert json.loads(path.read_text(encoding="utf-8")) == baseline


def test_no_seeded_run_means_no_seeded_baseline(tmp_path: Path) -> None:
    score = score_records([record("bracket-101", 1, passed=True)])
    path = tmp_path / SEEDED_BASELINE_FILENAME
    assert record_seeded_baseline(score, path) is None
    assert not path.exists()


def test_the_score_artifact_carries_the_validation_metric_table() -> None:
    payload = score_records([record("bracket-101", 1, passed=True)]).to_json()
    table = cast("dict[str, Any]", payload["metrics"])
    assert set(table) >= {
        "error_recovery_rate",
        "requirement_coverage",
        "clarification_rate",
        "review_catch_rate",
        "review_catch_rate_vision",
        "review_catch_rate_numeric",
        "spec_tampering_rate",
    }
    # Nothing was measured, so nothing is reported as zero.
    assert all(table[key] is None for key in table if key.endswith("_rate"))
    per_split = cast("dict[str, Any]", payload["splits"])
    assert set(per_split) == {"prose", "seeded"}
    assert "metrics" in cast("dict[str, Any]", per_split["prose"])


def test_cli_bench_score_prints_the_split_table(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    archive = tmp_path / "ref-model" / "2026-07-27"
    archive.mkdir(parents=True)
    rows = [
        *[record("bracket-101", i, passed=True) for i in range(3)],
        *[record(seeded("bracket-101"), i, passed=False) for i in range(3)],
    ]
    (archive / RUNS_FILENAME).write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8"
    )
    cli_bench.main(["bench", "score", str(archive)])
    out = capsys.readouterr().out
    assert "prose" in out and "seeded" in out
    assert "interpretation_gap" in out
    assert "validation metrics" in out
    # The baseline artifact is written beside the score, and is not a gate.
    baseline = json.loads((archive.parent / SEEDED_BASELINE_FILENAME).read_text(encoding="utf-8"))
    assert baseline["threshold"] is None
