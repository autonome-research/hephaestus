"""G2V clauses: termination review (§5) and the continuation ladder (§6).

The gate clauses read: *"termination review (reviewer receives request/ledger/
renders and NOT the agent's CHECKS — asserted structurally; assumed ⇒
fail-unless-confirmed; channel recorded); continuation ladder (findings
re-enter, 3-cycle cap, same-failure-twice escalation, ``unresolved_requirements``
terminal, and the never-green-with-open-requirements invariant)"*. Each sentence
is one test below, run over a real project store with a real build, a real
render pipeline and the real ladder; the reviewer child is scripted so the gate
measures the *rules*, not a model's mood.

The reviewer's live tool surface (a Pi child on the read-only ``reviewer``
profile, driven by the scripted fake model through the real Node sidecar) and
the exhaustive unit coverage — verdict normalization, the cavity/boss/bore
heuristic, the CHECKS stripper, the escalation-ignored path — live in
``server/tests/test_termination_review.py``; this module is the gate evidence.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from hephaestus.agent_bridge.cad_ops import RequirementEntry, record_clarification_answer
from hephaestus.agent_bridge.review import (
    MAX_REVIEW_CYCLES,
    REVIEW_TOOL,
    ContinuationLadder,
    ReviewerResponse,
    ReviewRequest,
    TerminationReviewService,
    build_review_context,
    normalize_findings,
    run_review_ladder,
)
from hephaestus.testing.tools_fixture import Project, make_project

#: The recorded seed-2 misread, as the ledger records it: a stated 40 mm in Y
#: and an unconfirmed assumption about which side of it the wall stands on.
REQUEST = "Bracket: 60 mm (X) by 40 mm (Y) base plate, 40 mm tall, 6 mm walls."
LEDGER: list[dict[str, Any]] = [
    {
        "id": "R1",
        "text": "base plate 40 mm in Y",
        "source": "specified",
        "quote": "40 mm (Y)",
        "value": 40.0,
        "unit": "mm",
    },
    {
        "id": "R9",
        "text": "walls stand outside the stated footprint",
        "source": "assumed",
        "rationale": "the request does not say which side of the stated Y the wall is on",
        "material": True,
    },
]


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Project]:
    # No seeded ledger: `seeded()` records exactly the §5 fixture below, and the
    # assertions name those ids.
    p = make_project(tmp_path / "proj", seed_ledger=False)
    try:
        yield p
    finally:
        p.close()


def seeded(project: Project) -> Project:
    """A built project whose ledger holds the §5 fixture.

    The ordering is the one ``VALIDATION.md`` compels, not a convenience: §2
    forbids geometry that precedes requirements (an empty ledger refuses
    ``build_part`` outright), and §3 then refuses it again while ``R9`` — a
    material assumption — has never been put to anyone. So the fixture records
    the ledger, takes §7's non-committal answer on ``R9``, and only then builds.
    ``R9`` is still ``assumed`` and unconfirmed afterwards, which is exactly the
    state §5 is asked to judge below.
    """
    project.cad.record_requirements(LEDGER, op_id="g2v-ledger")
    record_clarification_answer(
        project.cad,
        "R9",
        "unspecified — use your engineering judgment and record it as an assumption.",
        op_id="g2v-asked",
    )
    project.build("widget")
    return project


def entries(project: Project) -> Sequence[RequirementEntry]:
    return project.cad.ledger_state().entries


class Reviewer:
    """A scripted reviewer child: one canned round of findings per cycle."""

    def __init__(self, *rounds: Sequence[Mapping[str, Any]]) -> None:
        self._rounds = list(rounds)
        self.contexts: list[ReviewRequest] = []

    def call(self, request: ReviewRequest) -> ReviewerResponse:
        self.contexts.append(request)
        index = min(len(self.contexts) - 1, len(self._rounds) - 1)
        return ReviewerResponse(findings=tuple(self._rounds[index]))


class Agent:
    """The agent side of the continuation: records what it was made to resolve."""

    def __init__(self) -> None:
        self.payloads: list[Mapping[str, Any]] = []

    def deliver(self, payload: Mapping[str, Any]) -> str:
        self.payloads.append(dict(payload))
        return "completed"


def fail(req_id: str, evidence: str, *, channel: str = "numeric") -> dict[str, Any]:
    return {"id": req_id, "verdict": "fail", "evidence": evidence, "channel": channel}


# --------------------------------------------------------------------------
# §5


def test_the_reviewer_receives_request_ledger_and_renders_but_not_the_checks(
    project: Project,
) -> None:
    """The gate clause, asserted structurally on the assembled context."""
    seeded(project)

    context = build_review_context(project.cad, request=REQUEST, parts=["widget"])
    blob = json.dumps(context.to_json())

    assert context.request == REQUEST  # verbatim
    assert [dict(e)["id"] for e in context.requirements] == ["R1", "R9"]
    widget = next(part for part in context.parts if part.name == "widget")
    assert len({render.view for render in widget.renders if render.channel == "rgb"}) >= 2
    assert widget.metrics["bbox_mm"]
    # The agent's own acceptance tests are in the script on disk and in no part
    # of what the reviewer is handed.
    assert "CHECKS" in (project.root / "parts" / "widget.py").read_text(encoding="utf-8")
    assert "CHECKS" not in blob
    assert "CHECKS" not in context.prompt()


def test_assumed_entries_are_failures_until_confirmed(project: Project) -> None:
    """A confident reviewer pass cannot clear an unconfirmed assumption."""
    seeded(project)
    reviewer = Reviewer(
        [
            {"id": "R1", "verdict": "pass", "evidence": "bbox Y is 40", "channel": "numeric"},
            {"id": "R9", "verdict": "pass", "evidence": "walls look right", "channel": "vision"},
        ]
    )
    service = TerminationReviewService(project.cad, reviewer)

    report = service.review(request=REQUEST, run_id="g2v-1", parts=["widget"])

    assert report.by_id["R1"].verdict == "pass"
    assert report.by_id["R9"].verdict == "fail"
    assert report.by_id["R9"].forced_assumption is True
    assert report.green is False

    # A resolution recorded by the *runtime* from a real answer — not a better
    # argument, and not the run's own hand on the ledger — is what confirms it.
    record_clarification_answer(
        project.cad, "R9", "outside the stated footprint", op_id="g2v-resolve"
    )
    confirmed = service.review(request=REQUEST, run_id="g2v-2", parts=["widget"])
    assert confirmed.by_id["R9"].verdict == "pass"
    assert confirmed.green is True


def test_every_finding_records_its_channel(project: Project) -> None:
    """The §8 vision/numeric split needs a channel on every verdict, always."""
    seeded(project)
    reviewer = Reviewer(
        [
            fail("R1", "bbox Y is 46 mm against a stated 40 mm"),
            {"id": "R9", "verdict": "fail", "evidence": "wall on the wrong face"},
        ]
    )

    report = TerminationReviewService(project.cad, reviewer).review(
        request=REQUEST, run_id="g2v-3", parts=["widget"]
    )

    assert {f.id: f.channel for f in report.findings} == {"R1": "numeric", "R9": "vision"}
    assert report.channel_counts == {"numeric": 1, "vision": 1}


# --------------------------------------------------------------------------
# §6


def test_findings_reenter_as_a_tool_result_the_agent_must_resolve(project: Project) -> None:
    seeded(project)
    agent = Agent()
    reviewer = Reviewer(
        [fail("R1", "bbox Y is 46 mm against a stated 40 mm")],
        [fail("R1", "the datum moved but Y is still wrong")],
        [fail("R1", "and now the boss sits on the far face")],
    )

    run_review_ladder(
        TerminationReviewService(project.cad, reviewer),
        agent,
        request=REQUEST,
        run_id="g2v-4",
        cad=project.cad,
        parts=["widget"],
    )

    assert [p["tool"] for p in agent.payloads] == [REVIEW_TOOL] * 3
    assert agent.payloads[0]["status"] == "changes_required"
    assert "R1" in list(agent.payloads[0]["unresolved_requirements"])


def test_three_cycle_cap_then_an_unresolved_requirements_terminal(project: Project) -> None:
    seeded(project)
    reviewer = Reviewer(
        [fail("R1", "Y is 46 mm against a stated 40 mm")],
        [fail("R1", "the datum moved but Y is still wrong")],
        [fail("R1", "and now the boss sits on the far face")],
        [fail("R1", "a fourth review that must never happen")],
    )
    agent = Agent()

    outcome = run_review_ladder(
        TerminationReviewService(project.cad, reviewer),
        agent,
        request=REQUEST,
        run_id="g2v-5",
        cad=project.cad,
        parts=["widget"],
    )

    assert len(reviewer.contexts) == MAX_REVIEW_CYCLES == 3
    assert outcome.terminal.status == "unresolved_requirements"
    open_ids = {item.id for item in outcome.terminal.unresolved}
    assert open_ids == {"R1", "R9"}  # the failing requirement and the assumption
    assert all(item.evidence for item in outcome.terminal.unresolved)


def test_the_same_failure_twice_escalates_to_a_concrete_question(project: Project) -> None:
    seeded(project)
    same = [fail("R1", "Y envelope measured 46 mm against a stated 40 mm")]
    ledger = entries(project)
    ladder = ContinuationLadder()

    first = ladder.advance(normalize_findings(ledger, same), entries=ledger)
    second = ladder.advance(normalize_findings(ledger, same, cycle=2), entries=ledger)

    assert first.kind == "continue"
    assert second.kind == "escalate"
    assert second.payload["status"] == "ask_user_required"
    questions = second.payload["questions"]
    assert isinstance(questions, list) and questions
    for raw in questions:
        assert isinstance(raw, dict)
        options = raw["options"]
        assert isinstance(options, list)
        assert 2 <= len(options) <= 4
        # Concrete options only: each states its geometric consequence.
        for option in options:
            assert isinstance(option, dict)
            assert option["option"] and option["consequence"]


def test_a_run_may_never_terminate_green_with_an_open_requirement(project: Project) -> None:
    """The invariant, end to end: everything measured, one assumption unconfirmed."""
    seeded(project)
    reviewer = Reviewer(
        [
            {"id": "R1", "verdict": "pass", "evidence": "bbox Y is 40 mm", "channel": "numeric"},
            {"id": "R9", "verdict": "pass", "evidence": "looks fine to me", "channel": "vision"},
        ]
    )
    agent = Agent()

    outcome = run_review_ladder(
        TerminationReviewService(project.cad, reviewer),
        agent,
        request=REQUEST,
        run_id="g2v-6",
        cad=project.cad,
        parts=["widget"],
    )

    assert outcome.green is False
    assert outcome.terminal.status == "unresolved_requirements"
    assert [item.id for item in outcome.terminal.unresolved] == ["R9"]
    assert agent.payloads[-1]["status"] == "unresolved_requirements"
