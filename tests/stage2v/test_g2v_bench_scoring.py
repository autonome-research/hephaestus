"""G2V clauses: the bench answers non-committally, and the splits never merge.

Three sentences of the gate live here:

* *"bench answerer non-committal + ``asked`` scored"* — the answer the bench
  gives is the one §3 classifies as non-committal, it is written to the ledger by
  the runtime, and the entry it names stays ``assumed`` and keeps blocking;
* *"seeded/prose split scored separately with no cross-baseline comparison"* —
  the gate statistic is the prose split's alone, adding seeded runs cannot move
  it, and the seeded split carries no threshold to compare against;
* *"protected seeded checks restored **before** the final build and tampering
  scored"* — the ordering is asserted structurally, and the attempt shows up in
  the §8 metric table.

The exhaustive unit coverage lives in
``server/tests/test_bench_validation_metrics.py`` and
``server/tests/test_bench_scoring.py``; this module is the gate evidence.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from hephaestus.agent_bridge.cad_ops import (
    clarification_gate,
    ledger_state,
    question_refusal,
    record_answers,
)
from hephaestus.bench import metrics
from hephaestus.bench.harness import (
    BENCH_ANSWER,
    SEEDED_SUFFIX,
    bench_answerer,
    load_tasks,
    restore_protected,
    seed_project,
    seeded_variant,
)
from hephaestus.bench.scoring import (
    G2_AGGREGATE_THRESHOLD,
    SEEDED_BASELINE_FILENAME,
    record_seeded_baseline,
    score_records,
    wilson_lower_bound,
)
from hephaestus.testing.tools_fixture import Project, make_project

#: The recorded seed-2 misread, as a ledger entry: an unstated wall direction.
WALL_DIR: dict[str, Any] = {
    "id": "R9",
    "text": "wall stands outside the stated footprint",
    "source": "assumed",
    "rationale": "the request does not say which side of the stated Y the wall is on",
    "material": True,
    "applies_to": "bracket",
}


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Project]:
    p = make_project(tmp_path / "proj")
    try:
        yield p
    finally:
        p.close()


def run(task_id: str, seed: int, *, passed: bool) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "seed": seed,
        "model": "gate-model",
        "date": "2026-07-27",
        "passed": passed,
        "status": "completed",
        "tool_calls": 4,
        "budget_tool_calls": 20,
        "reasons": [],
    }


# --------------------------------------------------------------------------
# §7 — the bench answerer is non-committal, and asking is what gets scored


def build(project: Project) -> dict[str, Any]:
    return cast("dict[str, Any]", project.call("build_part", {"name": "bracket"}))


def test_the_bench_answer_records_the_question_without_answering_it(project: Project) -> None:
    """The whole of §7 in one path: ask, record ``asked``, resolve nothing.

    The two hooks called here are exactly the two ``agent_bridge.app``'s
    ``py.ask_user`` handler is made of, so this is the production path with the
    transport removed — not a re-implementation of it.
    """
    project.call("record_requirements", {"entries": [WALL_DIR]})
    assert build(project)["status"] == "clarification_required"

    params: dict[str, Any] = {
        "run_id": "run-1",
        "question": "Which side of the stated 40 mm does the wall stand on?",
        "options": [
            {"label": "inside", "consequence": "40 mm overall, 34 mm internal"},
            {"label": "outside", "consequence": "46 mm overall, 40 mm internal"},
        ],
        "requirement_ids": ["R9"],
    }
    assert question_refusal(params) is None  # a well-shaped clarification
    selection = bench_answerer(params)
    assert selection == BENCH_ANSWER
    recorded = record_answers(project.cad, "run-1", params, selection)
    assert [entry["id"] for entry in recorded] == ["R9"]
    assert recorded[0]["committal"] is False

    entry = ledger_state(project.cad).by_id["R9"]
    assert entry.asked is True  # §8 clarification_rate counts exactly this
    assert entry.resolution is None
    assert entry.source == "assumed"
    # Asking clears the §3 gate — that is all the gate ever compels — but the
    # assumption itself is untouched: a question asked is not a question answered,
    # so it stays an open item for §5 and for §8's requirement accounting.
    assert entry.unresolved_material is True
    assert clarification_gate(ledger_state(project.cad)).ids == ()
    assert build(project)["status"] == "ok"


def test_an_asked_assumption_is_scored_as_a_clarification() -> None:
    entries = [
        {**WALL_DIR, "asked": True, "material_class": "feature_direction"},
        {**WALL_DIR, "id": "R10", "asked": False, "material_class": "feature_direction"},
    ]
    record = {**run("bracket-101", 1, passed=False), "requirements": entries}
    table = metrics.aggregate_metrics([metrics.run_metrics(record, events=[])])
    assert table.clarification_rate == pytest.approx(0.5)


# --------------------------------------------------------------------------
# §1 — the two splits are scored separately, and never compared


def test_the_gate_statistic_is_the_prose_split_alone() -> None:
    prose = [run("bracket-101", i, passed=i < 18) for i in range(24)]
    perfect = [run("repair-fillet", i, passed=True) for i in range(3)]
    baseline = score_records([*prose, *perfect])
    assert baseline.meets_gate is True
    # 18 of 24 bracket seeds plus 3 of 3 repair-fillet seeds — the prose split.
    assert baseline.wilson_lower_90 == pytest.approx(wilson_lower_bound(21, 27), abs=1e-9)

    # Seeding the corpus adds a whole second split; the historical gate number
    # must not move by a single digit, or the baseline stops being comparable.
    seeded_runs = [run("bracket-101" + SEEDED_SUFFIX, i, passed=False) for i in range(24)]
    with_seeded = score_records([*prose, *perfect, *seeded_runs])
    assert with_seeded.wilson_lower_90 == baseline.wilson_lower_90
    assert with_seeded.meets_gate is baseline.meets_gate
    assert (with_seeded.n, with_seeded.passes) == (baseline.n, baseline.passes)
    assert with_seeded.n_total == baseline.n_total + 24


def test_the_seeded_split_has_no_threshold_to_compare_against(tmp_path: Path) -> None:
    score = score_records([run("bracket-101" + SEEDED_SUFFIX, i, passed=i < 2) for i in range(3)])
    assert score.seeded.n == 3
    assert score.seeded.threshold is None
    assert score.seeded.meets_threshold is None
    assert score.prose.threshold == G2_AGGREGATE_THRESHOLD
    # Baselined on first measurement, and never re-baselined afterwards.
    path = tmp_path / SEEDED_BASELINE_FILENAME
    first = record_seeded_baseline(score, path)
    assert first is not None and first["threshold"] is None
    better = score_records([run("bracket-101" + SEEDED_SUFFIX, i, passed=True) for i in range(3)])
    assert record_seeded_baseline(better, path) == first
    assert json.loads(path.read_text(encoding="utf-8"))["passes"] == 2


def test_the_two_pass_rates_are_reported_side_by_side_and_never_averaged() -> None:
    score = score_records(
        [
            *[run("bracket-101", i, passed=False) for i in range(3)],
            *[run("bracket-101" + SEEDED_SUFFIX, i, passed=True) for i in range(3)],
        ]
    )
    payload = score.to_json()
    assert payload["pass_rate_prose"] == 0.0
    assert payload["pass_rate_seeded"] == 1.0
    # The interpretation tax, as its own column.
    assert payload["interpretation_gap"] == 1.0
    # No number in the artifact is the mean of the two splits (which would be 0.5).
    assert payload["aggregate"] == 0.0
    assert payload["gated_split"] == metrics.SPEC_PROSE


# --------------------------------------------------------------------------
# §1/§8 — the seeded spec is restored before grading builds, and tampering scores


def test_a_run_cannot_edit_its_way_to_green_and_the_attempt_is_scored(tmp_path: Path) -> None:
    task = seeded_variant(load_tasks(["bracket-101"], specs=("prose",))[0])
    project_root = tmp_path / "proj"
    seed_project(task, project_root)
    spec_file = project_root / task.seeded_check_paths[0]
    original = spec_file.read_text(encoding="utf-8")
    assert original, "a seeded run must be given the acceptance checks as its spec"

    spec_file.write_text("CHECKS = {'envelope': lambda m: True}\n", encoding="utf-8")
    tampered = restore_protected(task, project_root)
    assert tampered == [task.seeded_check_paths[0]]
    assert spec_file.read_text(encoding="utf-8") == original

    record = {
        **run(task.id, 1, passed=False),
        "spec": task.spec,
        "protected_paths": list(task.protected_paths),
        "grade": {"restored_protected": tampered},
    }
    measured = metrics.run_metrics(record, events=[])
    assert measured.tampered is True
    assert metrics.aggregate_metrics([measured]).spec_tampering_rate == pytest.approx(1.0)


def test_grading_restores_the_spec_before_it_builds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ordering the seeded split rests on, asserted rather than read.

    If ``_build_all`` ever ran first, a run that rewrote its own acceptance
    checks would be graded against the rewrite — which is exactly the failure the
    seeded split exists to make impossible.
    """
    import contextlib
    from collections.abc import Generator

    from hephaestus.bench.harness import _grade  # pyright: ignore[reportPrivateUsage]

    order: list[str] = []

    class _NullCad:
        layout = None

    @contextlib.contextmanager
    def fake_open_cad(root: Path) -> Generator[Any]:
        order.append("open_cad")
        yield _NullCad()

    def fake_restore(task: Any, root: Path) -> list[str]:
        order.append("restore")
        return []

    def fake_build_all(cad: Any, layout: Any) -> tuple[dict[str, Any], list[str]]:
        order.append("build")
        return {}, ["stop"]

    monkeypatch.setattr(_grade, "restore_protected", fake_restore)
    monkeypatch.setattr(_grade, "_build_all", fake_build_all)
    monkeypatch.setattr(_grade, "open_cad", fake_open_cad)

    task = seeded_variant(load_tasks(["bracket-101"], specs=("prose",))[0])
    _grade.grade(task, tmp_path)
    assert order.index("restore") < order.index("build")
