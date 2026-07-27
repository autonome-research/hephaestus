"""G2V clause: a §4 dimension finding is BINDING at termination.

The gate clause reads: *"an unresolved §4 dimension finding is binding at
termination, exactly as an unconfirmed material assumption is: a build whose bbox
contradicts a request number cannot terminate green; it clears only when a later
successful build no longer raises it or when the user dismisses it through
``ask_user``; the model can clear it neither through the ledger nor through its
own ``CHECKS``"*.

The evidence is the measured failure itself. On ``bracket-101`` seed 2 the §4
critique fired, correctly and unrequested — "bbox.y measures 46 mm" against a
request that says 40 mm — and the model shipped anyway, because §4 was advice.
This module drives the **verbatim recorded s2 script** through the real
dispatcher and the real §5/§6 ladder and asserts that it can no longer do that.

Exhaustive coverage of the store, the clearing rules and the escalation options
lives in ``server/tests/test_dimension_findings.py``; this module is the gate
evidence for the four sentences above.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any, cast

import pytest
from hephaestus.agent_bridge.review import (
    MAX_REVIEW_CYCLES,
    ReviewerResponse,
    ReviewRequest,
    TerminationReviewService,
    open_dimension_findings,
    run_review_ladder,
)
from hephaestus.bench.harness import BENCH_ANSWER, load_tasks
from hephaestus.testing.tools_fixture import Project, make_project

#: The recorded seed-2 run, read from where ``server/tests`` keeps it: evidence,
#: not example code, so both gates read the same bytes.
FIXTURES = Path(__file__).resolve().parents[2] / "server" / "tests" / "fixtures"

#: The same bracket read the other way — wall inboard of the stated -Y edge, so
#: the footprint is the stated 60 x 40 and the height the stated 40.
IN_SPEC_SRC = """PARAMS = {
    "wall_thick": Param(6.0, min=2.0, max=10.0),
}

base = Box(hc.bracket_len, hc.bracket_width, hc.plate_t,
           align=(Align.CENTER, Align.CENTER, Align.MIN))
wall = Pos(0, -hc.bracket_width / 2, 0) * Box(
    hc.bracket_len, p.wall_thick, hc.bracket_height,
    align=(Align.CENTER, Align.MIN, Align.MIN))
part.geometry = base + wall
part.description = "L-bracket, wall inside the stated footprint"
"""

#: One ``specified`` ledger entry: §3 and §5 have nothing to hold open here, so
#: the only thing that can keep the terminal red is the §4 finding under test.
LEDGER: list[dict[str, Any]] = [
    {
        "id": "R1",
        "text": "base plate is 40 mm in Y",
        "source": "specified",
        "quote": "40 mm (Y)",
        "value": 40.0,
        "unit": "mm",
    }
]

#: The reviewer passes everything, every cycle — the point being that its opinion
#: is not what decides.
PASSES: list[dict[str, Any]] = [
    {"id": "R1", "verdict": "pass", "evidence": "measured it", "channel": "numeric"}
]


class Reviewer:
    def __init__(self, findings: Sequence[Mapping[str, Any]] = ()) -> None:
        self._findings = tuple(findings)
        self.contexts: list[ReviewRequest] = []

    def call(self, request: ReviewRequest) -> ReviewerResponse:
        self.contexts.append(request)
        return ReviewerResponse(findings=self._findings)


class Agent:
    def __init__(self) -> None:
        self.payloads: list[Mapping[str, Any]] = []

    def deliver(self, payload: Mapping[str, Any]) -> str:
        self.payloads.append(dict(payload))
        return "completed"


@pytest.fixture(scope="module")
def request_text() -> str:
    return load_tasks(["bracket-101"], specs=("prose",))[0].prompt


@pytest.fixture
def s2(tmp_path: Path, request_text: str) -> Iterator[Project]:
    project = make_project(tmp_path / "s2", seed_ledger=False)
    (project.root / "globals.py").write_text(
        (FIXTURES / "bracket_101_s2_globals.py").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (project.root / "parts" / "bracket.py").write_text(
        (FIXTURES / "bracket_101_s2_bracket.py").read_text(encoding="utf-8"), encoding="utf-8"
    )
    project.cad.set_request_text(request_text)
    project.cad.record_requirements(LEDGER, op_id="g2v-dim-ledger")
    try:
        yield project
    finally:
        project.close()


def build(project: Project) -> dict[str, Any]:
    result = cast("dict[str, Any]", project.call("build_part", {"name": "bracket"}))
    assert result["status"] == "ok", result.get("error") or result.get("message")
    return result


def open_ids(project: Project) -> set[str]:
    return {finding.id for finding in open_dimension_findings(project.cad)}


def terminate(project: Project, run_id: str) -> tuple[Any, Agent, Reviewer]:
    """Run the real §5/§6 ladder to its terminal over the current geometry."""
    reviewer = Reviewer(PASSES)
    agent = Agent()
    outcome = run_review_ladder(
        TerminationReviewService(project.cad, reviewer),
        agent,
        request=cast("str", project.cad.request_text),
        run_id=run_id,
        cad=project.cad,
        parts=["bracket"],
    )
    return outcome, agent, reviewer


def test_the_recorded_misread_cannot_terminate_green(s2: Project) -> None:
    """THE clause. §4 fired on this geometry before and the run shipped anyway."""
    result = build(s2)

    # Unrequested, in the build's own result: the contradiction, and that it binds.
    kinds = {
        str(cast("dict[str, Any]", w)["kind"])
        for w in cast("list[Any]", result["critique"]["warnings"])
    }
    assert {"dimension_mismatch", "unmatched_request_number", "open_dimension_finding"} <= kinds
    assert open_ids(s2)

    outcome, agent, reviewer = terminate(s2, "g2v-dim-blocked")

    # The reviewer passed every ledger entry; the run is still not done.
    assert all(f.verdict == "pass" for f in outcome.reports[-1].findings if not f.harness)
    assert outcome.green is False
    assert outcome.terminal.status == "unresolved_requirements"
    assert {item.id for item in outcome.terminal.unresolved} == open_ids(s2)
    # …routed through the very same §6 machinery: findings re-enter as work, the
    # cap holds, and the terminal lists every open dimension.
    assert len(reviewer.contexts) == MAX_REVIEW_CYCLES == 3
    assert agent.payloads[0]["status"] == "changes_required"
    assert agent.payloads[-1]["status"] == "unresolved_requirements"
    assert any(p["status"] == "ask_user_required" for p in agent.payloads), "same failure twice"


def test_it_clears_when_a_rebuild_matches_the_request(s2: Project) -> None:
    build(s2)
    assert open_ids(s2)

    (s2.root / "parts" / "bracket.py").write_text(IN_SPEC_SRC, encoding="utf-8")
    build(s2)

    assert open_ids(s2) == set()
    outcome, _agent, _reviewer = terminate(s2, "g2v-dim-rebuilt")
    assert outcome.green is True


def test_an_explicit_runtime_recorded_dismissal_clears_it(s2: Project) -> None:
    """The operator's route: a committal ``ask_user`` answer, recorded by the runtime."""
    build(s2)
    ids = sorted(open_ids(s2))

    from hephaestus.agent_bridge.cad_ops import question_refusal, record_answers

    # The two halves ``BridgeRuntime._handle_ask_user`` composes, in its order: the
    # §3 question-shape gate applies to a dimension finding exactly as to a ledger
    # id, and then the runtime — never the model — writes the answer back.
    params: dict[str, Any] = {
        "question": "The bracket measures 46 mm in Y against the stated 40 mm. Keep it?",
        "options": [
            {"label": "keep 46 mm", "consequence": "the wall stays outside the footprint"},
            {"label": "rebuild to 40 mm", "consequence": "the wall moves inboard"},
        ],
        "requirement_ids": ids,
    }
    assert question_refusal(params) is None
    assert question_refusal({**params, "options": ["keep it"]}) is not None

    recorded = record_answers(s2.cad, "run-1", params, "Keep 46 mm — that is what I want.")

    assert [entry["dismissed"] for entry in recorded] == [True] * len(ids)
    assert open_ids(s2) == set()
    outcome, _agent, _reviewer = terminate(s2, "g2v-dim-dismissed")
    assert outcome.green is True


def test_neither_the_bench_answer_nor_the_ledger_nor_checks_can_clear_it(s2: Project) -> None:
    """Everything the *model* can reach, tried, and none of it closes the finding."""
    from hephaestus.agent_bridge.cad_ops import record_answers

    build(s2)
    ids = sorted(open_ids(s2))

    # §7's non-committal answer: the question is on record, nothing is resolved.
    record_answers(s2.cad, "run-1", {"requirement_ids": ids}, BENCH_ANSWER)
    assert open_ids(s2) == set(ids)

    # A ledger entry that impersonates the finding, and a self-written resolution.
    s2.cad.record_requirements(
        [
            {
                "id": ids[0],
                "text": "46 mm in Y is fine",
                "source": "assumed",
                "rationale": "I checked it myself",
                "material": False,
            }
        ],
        op_id="g2v-dim-impersonate",
    )
    refusal = cast(
        "dict[str, Any]",
        s2.call("update_requirement", {"id": ids[0], "text": "settled"}),
    )
    assert refusal["status"] == "ok"  # an ordinary patch is allowed …
    assert open_ids(s2) == set(ids)  # … and clears nothing

    # An acceptance test that asserts the request's number.
    source = (s2.root / "parts" / "bracket.py").read_text(encoding="utf-8")
    (s2.root / "parts" / "bracket.py").write_text(
        source + '\nCHECKS["y_is_40"] = lambda m: 40.0 <= 40.0\n', encoding="utf-8"
    )
    build(s2)
    assert open_ids(s2) == set(ids)

    outcome, _agent, _reviewer = terminate(s2, "g2v-dim-unclearable")
    assert outcome.green is False
    assert {item.id for item in outcome.terminal.unresolved} == set(ids)
