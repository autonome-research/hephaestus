"""Gate G2V §5/§6: the termination reviewer and the bounded continuation ladder.

Every rung here must fire **by rule**. The tests are written to fail if any of
them could be satisfied by asking a model to behave:

* the review context is asserted *structurally* — it carries the verbatim
  request, the ledger and the renders, and it carries no ``CHECKS`` token at
  all, with :class:`ReviewContext` refusing to exist if one leaks;
* ``assumed`` entries are forced to ``fail`` in :func:`normalize_findings`
  regardless of the verdict the reviewer returned;
* every finding carries a channel, supplied or inferred;
* the ladder's bounds (3 cycles, same-failure-twice escalation, the
  ``unresolved_requirements`` terminal) are exercised against a scripted
  reviewer, and the never-green invariant is asserted both as a constructor
  refusal and end to end;
* the ``reviewer`` profile's read-only tool surface is checked through the real
  :class:`ToolDispatcher` **and** through the real Node sidecar with a scripted
  fake model, so "no mutation, no delegation" is a property of the declaration
  and the dispatch layer rather than of the reviewer's prompt.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from hephaestus.agent_bridge.app import BridgeRuntime
from hephaestus.agent_bridge.cad_ops import RequirementEntry, record_clarification_answer
from hephaestus.agent_bridge.dispatch import DispatchError, Principal
from hephaestus.agent_bridge.review import (
    MAX_REVIEW_CYCLES,
    REVIEW_TOOL,
    REVIEW_VIEWS,
    REVIEWER_PROFILE,
    Continuation,
    ContinuationLadder,
    PartEvidence,
    PromptContinuation,
    ReviewContext,
    ReviewerResponse,
    ReviewError,
    ReviewFinding,
    ReviewReport,
    ReviewRequest,
    SessionReviewer,
    TerminalReport,
    TerminationReviewService,
    UnresolvedItem,
    build_review_context,
    internal_feature_reasons,
    is_stop_state,
    normalize_findings,
    run_review_ladder,
    strip_agent_checks,
)
from hephaestus.contract import tools_decl
from hephaestus.testing.fake_openai import FakeOpenAI, RequestInfo, start_fake_openai
from hephaestus.testing.ledger import seed_minimal_ledger
from hephaestus.testing.projects import scaffold_project
from hephaestus.testing.sidecar import build_agent_dist
from hephaestus.testing.stream_assertions import text, tool_call
from hephaestus.testing.tools_fixture import Project, make_project

REVIEWER = Principal(session_id="rev", profile=REVIEWER_PROFILE, part=None)

#: A part with an unmistakable internal feature (a through bore) and a CHECKS
#: block, so one fixture exercises the section-render rule and the exclusion.
BORED_SRC = """body = Box(60.0, 46.0, 40.0)
bore = Cylinder(6.0, 60.0)
solid = body - bore
solid.label = "bracket_bore_body"
part.geometry = solid

CHECKS = {
    "envelope": lambda m: m.bbox("part") <= (60.1, 46.1, 40.1),
}
"""


# --------------------------------------------------------------------------
# fixtures / doubles


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Project]:
    # No seeded ledger: these tests assert on the ledger the *review* sees, so
    # each one records exactly the entries it means to have judged.
    proj = make_project(tmp_path / "proj", seed_ledger=False)
    try:
        yield proj
    finally:
        proj.close()


def entry(
    req_id: str,
    *,
    source: str = "specified",
    **fields: Any,
) -> RequirementEntry:
    """One ledger entry, with the per-source obligations already satisfied."""
    payload: dict[str, Any] = {"id": req_id, "text": f"{req_id} text", "source": source}
    if source == "specified":
        payload["quote"] = f"{req_id} quote"
    if source == "derived":
        payload["from"] = ["R1"]
    if source == "assumed":
        payload.setdefault("rationale", "the request did not say")
        payload.setdefault("material", True)
    payload.update(fields)
    return RequirementEntry.from_json(payload)


class ScriptedReviewer:
    """A :class:`ReviewerCaller` returning canned findings (or raising)."""

    def __init__(self, *rounds: Sequence[Mapping[str, Any]], boom: bool = False) -> None:
        self._rounds = list(rounds)
        self._boom = boom
        self.requests: list[ReviewRequest] = []

    def call(self, request: ReviewRequest) -> ReviewerResponse:
        self.requests.append(request)
        if self._boom:
            raise RuntimeError("reviewer child crashed")
        index = min(len(self.requests) - 1, len(self._rounds) - 1)
        return ReviewerResponse(findings=tuple(self._rounds[index]))


class RecordingAgent:
    """An :class:`AgentContinuation` that records every payload it was handed."""

    def __init__(self, *, status: str = "completed") -> None:
        self.payloads: list[Mapping[str, Any]] = []
        self.status = status

    def deliver(self, payload: Mapping[str, Any]) -> str:
        self.payloads.append(dict(payload))
        return self.status


def finding(
    req_id: str,
    *,
    verdict: str = "fail",
    evidence: str = "Y envelope measured 46 mm against a stated 40 mm",
    channel: str = "numeric",
    **fields: Any,
) -> dict[str, Any]:
    return {
        "id": req_id,
        "verdict": verdict,
        "evidence": evidence,
        "channel": channel,
        **fields,
    }


# --------------------------------------------------------------------------
# §5 — the assembled context


def test_context_carries_request_ledger_and_renders(project: Project) -> None:
    """Request verbatim + ledger + >=2 rgb views per built part (VALIDATION §5)."""
    request = "Make a 60 mm (X) by 40 mm (Y) base plate, 40 mm tall."
    # §2's ordering, which the gate now enforces: the ledger precedes geometry.
    project.cad.record_requirements(
        [
            {
                "id": "R1",
                "text": "base plate 60 mm in X",
                "source": "specified",
                "quote": "60 mm (X)",
                "value": 60.0,
                "unit": "mm",
            }
        ],
        op_id="op-ledger-1",
    )
    project.build("widget")

    context = build_review_context(project.cad, request=request, parts=["widget"])

    assert context.request == request  # verbatim, not a paraphrase
    assert [dict(item)["id"] for item in context.requirements] == ["R1"]
    assert context.ledger_generation == 1
    assert context.ledger_artifact_ref is not None
    widget = next(part for part in context.parts if part.name == "widget")
    views = sorted({render.view for render in widget.renders if render.channel == "rgb"})
    assert views == sorted(REVIEW_VIEWS), views
    assert len(views) >= 2
    assert all(render.artifact_ref.startswith("artifact:") for render in widget.renders)
    # The published metrics ride along; the agent's check results never do.
    assert widget.metrics["bbox_mm"]
    assert "checks" not in widget.metrics


def test_context_excludes_the_agents_own_checks(project: Project) -> None:
    """Structural: no CHECKS token anywhere in the context the reviewer receives."""
    seed_minimal_ledger(project)  # §2: a build with no ledger is refused
    project.build("widget")
    source = (project.root / "parts" / "widget.py").read_text(encoding="utf-8")
    assert "CHECKS" in source and "wide_enough" in source  # the fixture really has one

    context = build_review_context(project.cad, request="build a widget", parts=["widget"])

    blob = json.dumps(context.to_json())
    assert "CHECKS" not in blob
    assert "wide_enough" not in blob
    assert "CHECKS" not in context.prompt()
    # The rest of the script survives: the reviewer still sees how it was made.
    widget = next(part for part in context.parts if part.name == "widget")
    assert "Box(p.width, 20.0, hc.wall)" in widget.script


def test_context_refuses_to_exist_carrying_checks() -> None:
    """The exclusion is enforced where the context is built, not in a prompt."""
    leaking = PartEvidence(
        name="widget",
        script="CHECKS = {'envelope': lambda m: True}\n",
        metrics={},
        geometries=(),
        renders=(),
        internal_features=(),
    )
    with pytest.raises(ReviewError) as excinfo:
        ReviewContext(request="r", requirements=(), parts=(leaking,))
    assert excinfo.value.code == "checks_leaked"


def test_strip_agent_checks_survives_unparseable_scripts() -> None:
    """Any input at all leaves no CHECKS token behind."""
    assert "CHECKS" not in strip_agent_checks("CHECKS = {\n  'a': lambda m: True,\n}\nx = 1\n")
    assert "CHECKS" not in strip_agent_checks("def broken(:\n  CHECKS = 1\n")
    assert "CHECKS" not in strip_agent_checks("# CHECKS explains the envelope\nx = 1\n")
    assert "x = 1" in strip_agent_checks("CHECKS = {}\nx = 1\n")


def test_section_render_for_parts_with_internal_features(project: Project) -> None:
    """A bored part gets a section render; a plain solid does not."""
    seed_minimal_ledger(project)  # §2: a build with no ledger is refused
    (project.root / "parts" / "bored.py").write_text(BORED_SRC, encoding="utf-8")
    project.build("bored", "bracket")

    context = build_review_context(
        project.cad, request="bracket with a bore", parts=["bored", "bracket"]
    )
    bored = next(part for part in context.parts if part.name == "bored")
    bracket = next(part for part in context.parts if part.name == "bracket")

    assert bored.has_internal_features, bored.internal_features
    assert any(render.channel == "section" for render in bored.renders)
    assert not bracket.has_internal_features
    assert not any(render.channel == "section" for render in bracket.renders)


def test_internal_feature_heuristic_reads_the_geometry_index() -> None:
    """Cavity / boss / bore detection is a rule over labels, genus and fill."""
    assert internal_feature_reasons(labels=("body_bore",), metrics=None)
    assert internal_feature_reasons(labels=("boss_mount",), metrics=None)
    assert internal_feature_reasons(
        labels=("body",), metrics={"genus": 1, "solids": 1, "sealed": True}
    )
    assert internal_feature_reasons(
        labels=("body",),
        metrics={
            "genus": 0,
            "solids": 1,
            "sealed": True,
            "volume_mm3": 100.0,
            "bbox_mm": [10.0, 10.0, 10.0],
        },
    )
    assert not internal_feature_reasons(
        labels=("plate",),
        metrics={
            "genus": 0,
            "solids": 1,
            "sealed": True,
            "volume_mm3": 1000.0,
            "bbox_mm": [10.0, 10.0, 10.0],
        },
    )


# --------------------------------------------------------------------------
# §5 — verdict normalization (the rules, not the reviewer's judgement)


def test_assumed_entries_are_fail_unless_confirmed() -> None:
    """An assumed entry the reviewer passed is still a failure."""
    entries = [entry("R1"), entry("W1", source="assumed")]
    report = normalize_findings(
        entries,
        [finding("R1", verdict="pass"), finding("W1", verdict="pass", channel="vision")],
    )

    assert report.by_id["R1"].verdict == "pass"
    assert report.by_id["W1"].verdict == "fail"
    assert report.by_id["W1"].forced_assumption is True
    assert "not confirmed" in report.by_id["W1"].evidence
    assert report.green is False


def test_a_recorded_resolution_confirms_an_assumption() -> None:
    """Confirmation is a ledger resolution — not the reviewer changing its mind."""
    confirmed = entry("W1", source="assumed", resolution="user chose walls outside")
    report = normalize_findings([confirmed], [finding("W1", verdict="pass")])

    assert report.by_id["W1"].verdict == "pass"
    assert report.by_id["W1"].forced_assumption is False
    assert report.green is True


def test_missing_and_malformed_verdicts_never_become_passes() -> None:
    entries = [entry("R1"), entry("R2"), entry("R3")]
    report = normalize_findings(
        entries,
        [finding("R2", verdict="probably fine"), finding("R9", verdict="pass")],
    )

    assert report.by_id["R1"].verdict == "unverifiable"
    assert report.by_id["R2"].verdict == "unverifiable"
    assert report.by_id["R3"].verdict == "unverifiable"
    assert report.unknown_ids == ("R9",)  # a verdict for an id nobody recorded
    assert report.green is False


def test_channel_is_recorded_for_every_finding() -> None:
    """Supplied when valid, inferred otherwise — the §8 split needs it always."""
    entries = [
        entry("R1", value=40.0, unit="mm"),
        entry("R2"),
        entry("R3", value=6.0, unit="mm"),
    ]
    report = normalize_findings(
        entries,
        [
            finding("R1", verdict="fail", channel="numeric"),
            finding("R2", verdict="fail", channel="vision"),
            finding("R3", verdict="fail", channel="telepathy"),
        ],
    )

    assert report.by_id["R1"].channel == "numeric"
    assert report.by_id["R2"].channel == "vision"
    assert report.by_id["R3"].channel == "numeric"  # inferred from a numeric entry
    assert report.channel_counts == {"numeric": 2, "vision": 1}


def test_a_failed_review_verifies_nothing(project: Project) -> None:
    """A crashed reviewer yields unverifiable findings, never a silent pass."""
    project.cad.record_requirements(
        [{"id": "R1", "text": "60 mm", "source": "specified", "quote": "60 mm"}],
        op_id="op-ledger-crash",
    )
    service = TerminationReviewService(project.cad, ScriptedReviewer(boom=True))

    report = service.review(request="build it", run_id="run-1", parts=["widget"])

    assert report.error is not None
    assert report.by_id["R1"].verdict == "unverifiable"
    assert report.green is False


def test_empty_ledger_is_not_green() -> None:
    """Nothing recorded means nothing verified (§5's whole point)."""
    assert normalize_findings([], []).green is False


# --------------------------------------------------------------------------
# §6 — the continuation ladder


def test_findings_reenter_as_an_ordinary_tool_result() -> None:
    entries = [entry("R1")]
    report = normalize_findings(entries, [finding("R1")])
    ladder = ContinuationLadder()

    continuation = ladder.advance(report, entries=entries)

    assert continuation.kind == "continue"
    assert continuation.payload["tool"] == REVIEW_TOOL
    assert continuation.payload["status"] == "changes_required"
    assert continuation.payload["unresolved_requirements"] == ["R1"]
    assert "may not finish" in str(continuation.payload["instruction"])


def test_three_cycle_cap(project: Project) -> None:
    """Three cycles, then an honest terminal — never a fourth review."""
    project.cad.record_requirements(
        [{"id": "R1", "text": "60 mm", "source": "specified", "quote": "60 mm"}],
        op_id="op-ledger-cap",
    )
    # Distinct evidence each cycle, so the repeat rule never fires first.
    reviewer = ScriptedReviewer(
        [finding("R1", evidence="measured 46 in Y")],
        [finding("R1", evidence="now the datum is wrong")],
        [finding("R1", evidence="and the boss is on the far face")],
        [finding("R1", evidence="still wrong somehow")],
    )
    service = TerminationReviewService(project.cad, reviewer)
    agent = RecordingAgent()

    outcome = run_review_ladder(
        service, agent, request="build it", run_id="run-1", cad=project.cad, parts=["widget"]
    )

    assert len(outcome.reports) == MAX_REVIEW_CYCLES == 3
    assert len(reviewer.requests) == 3
    assert outcome.terminal.status == "unresolved_requirements"
    assert "cycles exhausted" in outcome.terminal.reason
    assert [item.id for item in outcome.terminal.unresolved] == ["R1"]


def test_same_failure_twice_escalates_with_concrete_options() -> None:
    """The second identical failure demands an ask_user, not another repair."""
    entries = [entry("R1", value=40.0, unit="mm")]
    same = [finding("R1", evidence="Y envelope measured 46 mm against a stated 40 mm")]
    ladder = ContinuationLadder()

    first = ladder.advance(normalize_findings(entries, same), entries=entries)
    second = ladder.advance(normalize_findings(entries, same, cycle=2), entries=entries)

    assert first.kind == "continue"
    assert second.kind == "escalate"
    assert second.escalated_ids == ("R1",)
    assert second.payload["status"] == "ask_user_required"
    questions = second.payload["questions"]
    assert isinstance(questions, list) and len(questions) == 1
    question = questions[0]
    assert isinstance(question, dict)
    options = question["options"]
    assert isinstance(options, list)
    assert 2 <= len(options) <= 4
    for option in options:
        assert isinstance(option, dict)
        # Every option states its geometric consequence — never "what did you mean?".
        assert option["consequence"]
        assert option["option"]
    assert "ask_user" in str(second.payload["instruction"])


def test_a_repaired_number_that_is_still_wrong_is_the_same_failure() -> None:
    """The signature normalizes digits: 46 -> 44 mm is not a new failure."""
    entries = [entry("R1", value=40.0, unit="mm")]
    ladder = ContinuationLadder()
    ladder.advance(
        normalize_findings(entries, [finding("R1", evidence="Y measured 46 mm, request says 40")]),
        entries=entries,
    )
    second = ladder.advance(
        normalize_findings(
            entries, [finding("R1", evidence="Y measured 44 mm, request says 40")], cycle=2
        ),
        entries=entries,
    )

    assert second.kind == "escalate"


def test_an_ignored_escalation_terminates_rather_than_looping() -> None:
    """The ledger's `asked` flag is the evidence a question was really put."""
    entries = [entry("R1", value=40.0, unit="mm")]
    same = [finding("R1", evidence="Y envelope measured 46 mm against a stated 40 mm")]
    ladder = ContinuationLadder(max_cycles=5)
    ladder.advance(normalize_findings(entries, same), entries=entries)
    escalation = ladder.advance(normalize_findings(entries, same, cycle=2), entries=entries)
    assert escalation.kind == "escalate"

    # Cycle 3 with the requirement still open and still never asked.
    third = ladder.advance(normalize_findings(entries, same, cycle=3), entries=entries)

    assert third.kind == "terminate"
    assert third.terminal is not None
    assert third.terminal.status == "unresolved_requirements"
    assert "escalation_ignored" in third.terminal.reason


def test_an_answered_escalation_may_continue() -> None:
    """Asking (recorded on the ledger) is what unblocks the ladder."""
    entries = [entry("R1", value=40.0, unit="mm")]
    same = [finding("R1", evidence="Y envelope measured 46 mm against a stated 40 mm")]
    ladder = ContinuationLadder(max_cycles=5)
    ladder.advance(normalize_findings(entries, same), entries=entries)
    ladder.advance(normalize_findings(entries, same, cycle=2), entries=entries)

    asked = [entry("R1", value=40.0, unit="mm", asked=True)]
    third = ladder.advance(
        normalize_findings(asked, [finding("R1", evidence="a different failure now")], cycle=3),
        entries=asked,
    )

    assert third.kind == "continue"


def test_unresolved_requirements_terminal_lists_every_open_item() -> None:
    entries = [entry("R1"), entry("W1", source="assumed"), entry("R2")]
    report = normalize_findings(
        entries,
        [finding("R1", verdict="pass"), finding("W1", verdict="pass"), finding("R2")],
    )
    ladder = ContinuationLadder(max_cycles=1)

    continuation = ladder.advance(report, entries=entries)

    assert continuation.kind == "terminate"
    assert continuation.payload["status"] == "unresolved_requirements"
    terminal = continuation.terminal
    assert terminal is not None
    ids = {item.id for item in terminal.unresolved}
    assert ids == {"W1", "R2"}
    listed = terminal.to_json()["unresolved_requirements"]
    assert isinstance(listed, list) and len(listed) == 2
    assert all(isinstance(item, dict) and item["evidence"] for item in listed)


# --------------------------------------------------------------------------
# §6 — the never-green invariant


def test_terminal_report_cannot_be_green_with_open_requirements() -> None:
    """The invariant is a constructor refusal, not a convention."""
    open_item = UnresolvedItem(
        id="R1", verdict="fail", evidence="Y is 46 mm, request says 40", channel="numeric"
    )
    with pytest.raises(ReviewError) as excinfo:
        TerminalReport(status="green", cycles=1, unresolved=(open_item,), reason="lying")
    assert excinfo.value.code == "never_green_with_open_requirements"
    # And the derived constructor never produces that state in the first place.
    derived = TerminalReport.of(
        ReviewReport(
            cycle=1,
            findings=(ReviewFinding(id="R1", verdict="fail", evidence="wrong", channel="numeric"),),
        ),
        cycles=1,
        reason="checked",
    )
    assert derived.status == "unresolved_requirements"
    assert derived.green is False


@pytest.mark.parametrize(
    ("entries", "raw"),
    [
        # an unverified requirement
        ([entry("R1")], [finding("R1", verdict="unverifiable")]),
        # an assumption nobody confirmed, which the reviewer happily passed
        ([entry("W1", source="assumed")], [finding("W1", verdict="pass")]),
        # a failing requirement
        ([entry("R1")], [finding("R1", verdict="fail")]),
        # no ledger at all
        ([], []),
    ],
    ids=["unverified", "assumed_unconfirmed", "failed", "no_ledger"],
)
def test_never_green_while_anything_is_open(
    entries: list[RequirementEntry], raw: list[dict[str, Any]]
) -> None:
    ladder = ContinuationLadder(max_cycles=1)
    continuation = ladder.advance(normalize_findings(entries, raw), entries=entries)

    assert continuation.terminal is not None
    assert continuation.terminal.green is False
    assert continuation.terminal.status == "unresolved_requirements"


def test_green_only_when_every_requirement_is_verified(project: Project) -> None:
    project.cad.record_requirements(
        [
            {"id": "R1", "text": "60 mm", "source": "specified", "quote": "60 mm"},
            {
                "id": "W1",
                "text": "walls outside",
                "source": "assumed",
                "rationale": "not stated",
                "material": True,
            },
        ],
        op_id="op-ledger-green",
    )
    # The confirmation has to come from a real answer: `resolution` is the
    # runtime's to write, so seeding it on the entry above would be refused.
    record_clarification_answer(
        project.cad, "W1", "outside the stated footprint", op_id="op-green-answer"
    )
    reviewer = ScriptedReviewer(
        [finding("R1", verdict="pass"), finding("W1", verdict="pass", channel="vision")]
    )
    service = TerminationReviewService(project.cad, reviewer)
    agent = RecordingAgent()

    outcome = run_review_ladder(
        service, agent, request="build it", run_id="run-g", cad=project.cad, parts=["widget"]
    )

    assert outcome.green is True
    assert outcome.terminal.status == "green"
    assert outcome.terminal.unresolved == ()
    assert len(outcome.reports) == 1


def test_the_agent_receives_every_continuation(project: Project) -> None:
    """Findings are handed to the agent — the ladder never resolves them itself."""
    project.cad.record_requirements(
        [{"id": "R1", "text": "60 mm", "source": "specified", "quote": "60 mm"}],
        op_id="op-ledger-deliver",
    )
    reviewer = ScriptedReviewer(
        [finding("R1", evidence="first problem")],
        [finding("R1", evidence="second, different problem")],
        [finding("R1", evidence="third, different problem again")],
    )
    agent = RecordingAgent()

    outcome = run_review_ladder(
        TerminationReviewService(project.cad, reviewer),
        agent,
        request="build it",
        run_id="run-d",
        cad=project.cad,
        parts=["widget"],
    )

    assert [payload["tool"] for payload in agent.payloads] == [REVIEW_TOOL] * 3
    assert [payload["status"] for payload in agent.payloads] == [
        "changes_required",
        "changes_required",
        "unresolved_requirements",
    ]
    assert outcome.terminal.status == "unresolved_requirements"


def test_a_cancelled_continuation_terminates_unresolved(project: Project) -> None:
    project.cad.record_requirements(
        [{"id": "R1", "text": "60 mm", "source": "specified", "quote": "60 mm"}],
        op_id="op-ledger-cancel",
    )
    agent = RecordingAgent(status="cancelled")

    outcome = run_review_ladder(
        TerminationReviewService(project.cad, ScriptedReviewer([finding("R1")])),
        agent,
        request="build it",
        run_id="run-c",
        cad=project.cad,
        parts=["widget"],
    )

    assert outcome.terminal.status == "unresolved_requirements"
    assert "cancelled" in outcome.terminal.reason


def test_stop_state_needs_a_settled_final_turn() -> None:
    settled = [{"kind": "tool_call"}, {"kind": "tool_result"}, {"kind": "text_delta"}]
    pending = [{"kind": "tool_call"}, {"kind": "tool_call"}, {"kind": "tool_result"}]
    assert is_stop_state(settled, "completed") is True
    assert is_stop_state(pending, "completed") is False
    assert is_stop_state(settled, "cancelled") is False


# --------------------------------------------------------------------------
# §5 — the reviewer profile is read-only, by declaration and by dispatch


def test_reviewer_profile_declares_only_measurement_and_render_tools() -> None:
    declared = {
        name for name in tools_decl.tool_names() if "reviewer" in tools_decl.get_tool(name).profiles
    }
    assert declared == set(tools_decl.REVIEWER_TOOLS)
    # Nothing in the reviewer's surface mutates or delegates.
    assert not any(tools_decl.get_tool(name).idempotent for name in declared)
    assert declared.isdisjoint(
        {"delegate_part_agent", "get_delegation_status", "cancel_delegation"}
    )
    # Nor can it run the agent's own checks.
    assert "run_checks" not in declared


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("write_part", {"name": "widget", "script": "part.geometry = Box(1,1,1)"}),
        ("build_part", {"name": "widget"}),
        ("edit_part", {"name": "widget", "old_str": "a", "new_str": "b"}),
        ("run_checks", {"name": "widget"}),
        ("record_requirements", {"entries": []}),
        ("update_requirement", {"id": "R1", "resolution": "fine"}),
        ("delegate_part_agent", {"part": "widget", "prompt": "go"}),
        ("export_part", {"name": "widget", "format": "step"}),
    ],
)
def test_reviewer_principal_is_refused_every_mutation(
    project: Project, tool: str, arguments: dict[str, Any]
) -> None:
    with pytest.raises(DispatchError) as excinfo:
        project.call(tool, arguments, principal=REVIEWER)
    assert excinfo.value.reason == "scope_denied"


def test_reviewer_principal_may_measure_and_render_across_parts(project: Project) -> None:
    """The reviewer reads the whole project — it judges every part."""
    seed_minimal_ledger(project)  # §2: a build with no ledger is refused
    project.build("widget", "bracket")

    rendered = project.call(
        "inspect_part", {"name": "bracket", "views": ["iso"]}, principal=REVIEWER
    )
    measured = project.call(
        "measure", {"kind": "bbox", "a": "widget/part", "part": "widget"}, principal=REVIEWER
    )

    assert rendered["status"] == "ok"
    assert rendered["render_artifact_refs"]
    assert measured["units"] == "mm"


# --------------------------------------------------------------------------
# through the real sidecar: the reviewer child's actual tool surface


@pytest.fixture(scope="module")
def sidecar_dist() -> Path:
    built = build_agent_dist()
    if built is None:
        pytest.skip("node/pnpm unavailable; the reviewer-child test needs the sidecar")
    return built[0]


@pytest.fixture
def runtime(tmp_path: Path, sidecar_dist: Path) -> Iterator[tuple[BridgeRuntime, FakeOpenAI]]:
    root = scaffold_project(
        tmp_path / "reviewed",
        name="reviewed",
        globals_src="PARAMS = {}\n",
    )
    (root / "parts" / "widget.py").write_text(
        "body = Box(60.0, 46.0, 40.0)\nbody.label = 'plate'\npart.geometry = body\n"
        "CHECKS = {'envelope': lambda m: m.bbox('part') <= (60.1, 46.1, 40.1)}\n",
        encoding="utf-8",
    )
    fake = start_fake_openai([])
    bridge = BridgeRuntime(
        project_root=root, providers=[fake.provider_spec()], dist_main=sidecar_dist
    )
    bridge.start()
    try:
        yield bridge, fake
    finally:
        bridge.close()
        fake.close()


def test_reviewer_child_gets_only_the_read_only_surface(
    runtime: tuple[BridgeRuntime, FakeOpenAI],
) -> None:
    """The live Pi child's own tool list is the generated reviewer subset."""
    bridge, fake = runtime
    offered: dict[str, list[str]] = {}

    def capture(info: RequestInfo) -> dict[str, Any]:
        offered["reviewer"] = sorted(info.tool_names)
        return text('{"findings": []}')

    fake.set_script([capture])
    session = bridge.create_session(REVIEWER_PROFILE, session_id="rev-surface")
    result = bridge.prompt(session, "review this run", timeout=300)

    assert result.status == "completed"
    assert offered["reviewer"] == sorted(tools_decl.REVIEWER_TOOLS)
    forbidden = {"write_part", "edit_part", "build_part", "run_checks", "delegate_part_agent"}
    assert forbidden.isdisjoint(offered["reviewer"])


def test_session_reviewer_drives_a_real_child_and_returns_findings(
    runtime: tuple[BridgeRuntime, FakeOpenAI],
) -> None:
    """End to end: assembled context -> reviewer child -> measured, parsed verdicts."""
    bridge, fake = runtime
    bridge.create_session("orchestrator", session_id="rev-build")
    fake.set_script([tool_call("build_part", {"name": "widget"}, "b0"), text("built")])
    built = bridge.prompt("rev-build", "build the widget", timeout=600)
    assert built.status == "completed"

    def measure_then_answer(_info: RequestInfo) -> dict[str, Any]:
        return tool_call("measure", {"kind": "bbox", "a": "part", "part": "widget"}, "m0")

    def answer(info: RequestInfo) -> dict[str, Any]:
        assert info.has_tool_result
        return text(
            'Here is my judgement:\n{"findings": [{"id": "R1", "verdict": "fail", '
            '"evidence": "bbox Y is 46 mm; the request says 40 mm", "channel": "numeric", '
            '"expected": "40 mm", "observed": "46 mm"}]}'
        )

    fake.set_script([measure_then_answer, answer])
    context = ReviewContext(
        request="a 60 x 40 x 40 mm plate",
        requirements=({"id": "R1", "text": "40 mm in Y", "source": "specified"},),
        parts=(),
    )
    reviewer = SessionReviewer(bridge)

    response = reviewer.call(
        ReviewRequest(run_id="rev-1", context=context, prompt=context.prompt())
    )
    report = normalize_findings([entry("R1", value=40.0, unit="mm")], response.findings, cycle=1)

    assert report.by_id["R1"].verdict == "fail"
    assert report.by_id["R1"].channel == "numeric"
    assert report.by_id["R1"].observed == "46 mm"
    assert report.green is False


class _FakePromptRuntime:
    """Records what a continuation would put into the agent's transcript."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def create_session(self, profile: str, *, session_id: str | None = None) -> str:
        return session_id or profile

    def prompt(self, session_id: str, text: str, *, timeout: float | None = None) -> Any:
        self.prompts.append(text)
        return type("R", (), {"status": "completed", "events": []})()


def test_prompt_continuation_delivers_the_payload_verbatim() -> None:
    """The agent reads the reviewer's structured result, not a summary of it."""
    runtime_double = _FakePromptRuntime()
    entries = [entry("R1")]
    continuation = ContinuationLadder().advance(
        normalize_findings(entries, [finding("R1")]), entries=entries
    )

    status = PromptContinuation(runtime_double, "sess-1").deliver(continuation.payload)

    assert status == "completed"
    delivered = runtime_double.prompts[0]
    assert delivered.startswith(f'<tool_result tool="{REVIEW_TOOL}">')
    body = delivered.split(">", 1)[1].rsplit("</tool_result>", 1)[0]
    assert json.loads(body) == json.loads(json.dumps(dict(continuation.payload)))


def test_continuation_payload_is_json_serializable() -> None:
    """The payload crosses the bridge as a tool result: it must be plain JSON."""
    entries = [entry("R1")]
    continuation: Continuation = ContinuationLadder().advance(
        normalize_findings(entries, [finding("R1")]), entries=entries
    )
    assert json.loads(json.dumps(continuation.payload))["tool"] == REVIEW_TOOL
