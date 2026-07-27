"""Binding dimension findings: §4's critique with teeth (``VALIDATION.md`` §4/§6).

The measured failure this stage exists for is not that §4 stayed silent — it
fired, correctly and unrequested, on ``bracket-101`` seed 2 — but that nothing
made the run *do* anything about it. These tests pin the rung that fixes that,
and every one of them is driven from the **verbatim recorded s2 script** through
the real build: no scripted warning, no hand-built finding.

The clauses, one per test:

* a build whose bbox contradicts a request number cannot terminate green;
* it clears when a rebuild matches — and only then;
* a runtime-recorded dismissal clears it, and a non-committal answer does not;
* the model cannot clear it by writing to the ledger, nor by asserting the
  number in its own ``CHECKS``, nor by having the reviewer pass it;
* the 3-cycle cap, the same-failure-twice escalation and the
  ``unresolved_requirements`` terminal all hold for a dimension finding exactly
  as they do for a review finding.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any, cast

import pytest
from hephaestus.agent_bridge.cad_ops import (
    CadOpError,
    DimensionFinding,
    record_answers,
)
from hephaestus.agent_bridge.review import (
    MAX_REVIEW_CYCLES,
    ContinuationLadder,
    ReviewerResponse,
    ReviewRequest,
    TerminationReviewService,
    normalize_findings,
    open_dimension_findings,
    run_review_ladder,
)
from hephaestus.bench.harness import BENCH_ANSWER, load_tasks
from hephaestus.testing.tools_fixture import Project, make_project

FIXTURES = Path(__file__).parent / "fixtures"

#: The recorded s2 script places the wall OUTSIDE the stated footprint, so the
#: bracket measures 46 mm in Y. This is the same bracket read the other way: the
#: wall stands *inboard* of the -Y edge, so the footprint is the stated 60 x 40
#: and the overall height the stated 40. Deliberately a plain rebuild — no tags,
#: no CHECKS — because the only thing that may clear a finding is geometry.
_CORRECTED_SRC = """PARAMS = {
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

#: A ``CHECKS`` threshold that asserts the request's number. It must not clear
#: anything: a self-authored acceptance test is the artifact that encodes the
#: misreading, so it can never be the evidence that the misreading is gone.
_ASSERTING_CHECKS = """CHECKS = {
    "envelope": lambda m: m.bbox("part") <= (60.1, 46.1, 40.1),
    "sealed": lambda m: m.sealed("part"),
    "y_is_40": lambda m: 40.0 <= 40.0,
}"""

#: The ledger the s2 project records: one plain ``specified`` entry, so nothing
#: here is ever kept open by §3/§5's assumption rules and the only thing that can
#: hold the terminal red is the dimension finding under test.
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

PASS_R1: list[dict[str, Any]] = [
    {"id": "R1", "verdict": "pass", "evidence": "measured", "channel": "numeric"}
]


class Reviewer:
    """A scripted reviewer child: the same canned verdicts every cycle."""

    def __init__(self, findings: Sequence[Mapping[str, Any]] = ()) -> None:
        self._findings = tuple(findings)
        self.contexts: list[ReviewRequest] = []

    def call(self, request: ReviewRequest) -> ReviewerResponse:
        self.contexts.append(request)
        return ReviewerResponse(findings=self._findings)


class Agent:
    """The agent side of the §6 continuation: it records and resolves nothing."""

    def __init__(self) -> None:
        self.payloads: list[Mapping[str, Any]] = []

    def deliver(self, payload: Mapping[str, Any]) -> str:
        self.payloads.append(dict(payload))
        return "completed"


@pytest.fixture(scope="module")
def request_text() -> str:
    """The ``bracket-101`` request, from the corpus, never paraphrased."""
    return load_tasks(["bracket-101"], specs=("prose",))[0].prompt


@pytest.fixture
def s2(tmp_path: Path, request_text: str) -> Iterator[Project]:
    """The recorded seed-2 run in a real project, with its request bound."""
    project = make_project(tmp_path / "s2", seed_ledger=False)
    (project.root / "globals.py").write_text(
        (FIXTURES / "bracket_101_s2_globals.py").read_text(encoding="utf-8"), encoding="utf-8"
    )
    _write_bracket(project, (FIXTURES / "bracket_101_s2_bracket.py").read_text(encoding="utf-8"))
    project.cad.set_request_text(request_text)
    project.cad.record_requirements(LEDGER, op_id="dimfind-ledger")
    try:
        yield project
    finally:
        project.close()


def _write_bracket(project: Project, source: str) -> None:
    (project.root / "parts" / "bracket.py").write_text(source, encoding="utf-8")


def _bracket_source(project: Project) -> str:
    return (project.root / "parts" / "bracket.py").read_text(encoding="utf-8")


def build(project: Project) -> dict[str, Any]:
    result = cast("dict[str, Any]", project.call("build_part", {"name": "bracket"}))
    assert result["status"] == "ok", result.get("error") or result.get("message")
    return result


def findings(project: Project) -> tuple[DimensionFinding, ...]:
    return open_dimension_findings(project.cad)


def ladder_outcome(project: Project, run_id: str, reviewer: Reviewer | None = None) -> Any:
    agent = Agent()
    outcome = run_review_ladder(
        TerminationReviewService(project.cad, reviewer or Reviewer(PASS_R1)),
        agent,
        request=cast("str", project.cad.request_text),
        run_id=run_id,
        cad=project.cad,
        parts=["bracket"],
    )
    return outcome, agent


# --------------------------------------------------------------------------
# raising


def test_the_recorded_misread_raises_binding_findings(s2: Project) -> None:
    """§4 already said 46 != 40. Now the run carries it as an open obligation."""
    result = build(s2)

    open_findings = findings(s2)
    assert {finding.kind for finding in open_findings} == {
        "dimension_mismatch",
        "unmatched_request_number",
    }
    assert {finding.axis for finding in open_findings} == {"y"}
    assert {finding.request_value_mm for finding in open_findings} == {40.0}
    assert all(finding.part == "bracket" for finding in open_findings)

    # The build result says so itself, in the same tool result, with the id an
    # ask_user question would have to name.
    block = cast("dict[str, Any]", result["critique"]["dimension_findings"])
    assert {cast("dict[str, Any]", f)["id"] for f in cast("list[Any]", block["open"])} == {
        finding.id for finding in open_findings
    }
    binding = [
        cast("dict[str, Any]", w)
        for w in cast("list[Any]", result["critique"]["warnings"])
        if cast("dict[str, Any]", w)["kind"] == "open_dimension_finding"
    ]
    assert len(binding) == len(open_findings)
    assert all("BINDING" in str(warning["message"]) for warning in binding)


def test_an_axis_less_number_is_advisory_and_never_binding(s2: Project) -> None:
    """Binding requires evidence of a contradiction, not of the harness's blindness.

    "no dimension corresponds to 12 mm" means the 12 mm was not *found* — it may
    be there, untagged. Only a number the request pinned to an axis is measured
    either way round by the bbox, so only that one binds.
    """
    result = build(s2)

    advisory = {
        (
            str(cast("dict[str, Any]", w)["kind"]),
            cast("dict[str, Any]", w).get("axis"),
        )
        for w in cast("list[Any]", result["critique"]["prompt_number_diff"]["warnings"])
    }
    assert ("unmatched_request_number", None) in advisory, "the advisory rung is unchanged"
    assert all(finding.axis is not None for finding in findings(s2))


def test_the_misread_cannot_terminate_green(s2: Project) -> None:
    """THE clause: the s2 run must be blocked, whatever anyone says about it."""
    build(s2)

    outcome, _agent = ladder_outcome(s2, "dimfind-green")

    assert outcome.green is False
    assert outcome.terminal.status == "unresolved_requirements"
    unresolved = {item.id for item in outcome.terminal.unresolved}
    assert unresolved == {finding.id for finding in findings(s2)}
    assert all(item.source == "critique" for item in outcome.terminal.unresolved)
    # Every open item says which number was not honoured, in the request's words.
    assert all("40 mm" in item.evidence for item in outcome.terminal.unresolved)
    assert any("46" in item.evidence for item in outcome.terminal.unresolved)


def test_a_clean_build_is_green(s2: Project) -> None:
    """The control: the same project, built to the request, terminates green."""
    _write_bracket(s2, _CORRECTED_SRC)
    build(s2)
    assert findings(s2) == ()

    outcome, _agent = ladder_outcome(s2, "dimfind-clean")
    assert outcome.green is True


# --------------------------------------------------------------------------
# clearing


def test_a_rebuild_that_matches_clears_it(s2: Project) -> None:
    """Clearing rule 1: a later successful build whose diff no longer raises it."""
    build(s2)
    raised = {finding.id for finding in findings(s2)}
    assert raised

    _write_bracket(s2, _CORRECTED_SRC)
    build(s2)

    assert findings(s2) == ()
    state = s2.cad.dimension_findings()
    assert {f.id for f in state.findings} == raised, "the record survives; the obligation does not"
    assert {f.closed_by for f in state.findings} == {"rebuild"}

    outcome, _agent = ladder_outcome(s2, "dimfind-rebuilt")
    assert outcome.green is True


def test_a_failed_rebuild_does_not_clear_it(s2: Project) -> None:
    """A build that errors publishes nothing, so it is evidence of nothing."""
    build(s2)
    raised = {finding.id for finding in findings(s2)}

    _write_bracket(s2, "part.geometry = Box(60.0, 40.0, 0.0)\n")
    broken = cast("dict[str, Any]", s2.call("build_part", {"name": "bracket"}))
    assert broken["status"] == "error"

    assert {finding.id for finding in findings(s2)} == raised


def test_a_preview_build_clears_nothing(s2: Project) -> None:
    """A transient-override build is never published, so it never counts."""
    build(s2)
    raised = {finding.id for finding in findings(s2)}

    _write_bracket(s2, _CORRECTED_SRC)
    preview = cast(
        "dict[str, Any]",
        s2.call("build_part", {"name": "bracket", "params": {"wall_thick": 5.0}}),
    )
    assert preview["status"] == "ok"
    assert "dimension_findings" not in cast("dict[str, Any]", preview["critique"])

    assert {finding.id for finding in findings(s2)} == raised


def test_a_runtime_recorded_dismissal_clears_it(s2: Project) -> None:
    """Clearing rule 2: the user says the built dimension is what they meant."""
    build(s2)
    open_ids = sorted(finding.id for finding in findings(s2))

    recorded = record_answers(
        s2.cad,
        "run-1",
        {"requirement_ids": open_ids},
        "Yes — 46 mm in Y is what I want; the wall stands outside the footprint.",
    )

    assert [entry["kind"] for entry in recorded] == ["dimension_finding"] * len(open_ids)
    assert all(entry["dismissed"] is True for entry in recorded)
    assert findings(s2) == ()
    state = s2.cad.dimension_findings()
    assert {f.closed_by for f in state.findings} == {"user"}
    assert all(f.asked and f.dismissal for f in state.findings)

    outcome, _agent = ladder_outcome(s2, "dimfind-dismissed")
    assert outcome.green is True


def test_a_non_committal_answer_dismisses_nothing(s2: Project) -> None:
    """§7: the bench answerer must not be able to answer past its own measurement."""
    build(s2)
    open_ids = sorted(finding.id for finding in findings(s2))

    recorded = record_answers(s2.cad, "run-1", {"requirement_ids": open_ids}, BENCH_ANSWER)

    assert all(entry["committal"] is False for entry in recorded)
    assert all(entry["dismissed"] is False for entry in recorded)
    # The question is on record; the finding is not closed by having been asked.
    assert sorted(finding.id for finding in findings(s2)) == open_ids
    assert all(s2.cad.dimension_findings().by_id[i].asked for i in open_ids)

    outcome, _agent = ladder_outcome(s2, "dimfind-noncommittal")
    assert outcome.green is False


def test_a_dismissed_finding_is_not_reopened_by_a_later_build(s2: Project) -> None:
    """A human judged that dimension; rebuilding the same geometry does not undo it."""
    build(s2)
    open_ids = sorted(finding.id for finding in findings(s2))
    record_answers(s2.cad, "run-1", {"requirement_ids": open_ids}, "Keep 46 mm; that is intended.")

    build(s2)

    assert findings(s2) == ()


def test_a_store_that_could_not_record_says_so(s2: Project, monkeypatch: Any) -> None:
    """Silence must never read as agreement — the §4 ``unavailable`` rule."""

    def boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("the findings pointer is wedged")

    monkeypatch.setattr(type(s2.cad), "record_dimension_findings", boom)
    result = build(s2)

    block = cast("dict[str, Any]", result["critique"]["dimension_findings"])
    kinds = {str(cast("dict[str, Any]", w)["kind"]) for w in cast("list[Any]", block["warnings"])}
    assert kinds == {"dimension_findings_unavailable"}
    assert block["open"] == [] and block["cleared"] == []
    assert "dimension_findings_unavailable" in {
        str(cast("dict[str, Any]", w)["kind"])
        for w in cast("list[Any]", result["critique"]["warnings"])
    }


# --------------------------------------------------------------------------
# what cannot clear it


def test_the_model_cannot_clear_it_through_the_ledger(s2: Project) -> None:
    """The findings store has no model-facing write, and the ledger is not it."""
    build(s2)
    open_ids = sorted(finding.id for finding in findings(s2))

    # A ledger entry that impersonates the finding id …
    s2.cad.record_requirements(
        [
            {
                "id": open_ids[0],
                "text": "the Y envelope is fine as built",
                "source": "assumed",
                "rationale": "I measured it myself",
                "material": False,
            }
        ],
        op_id="dimfind-impersonate",
    )
    # … and an attempt to write the clarification record onto it.
    with pytest.raises(CadOpError) as refused:
        s2.cad.update_requirement(
            open_ids[0], {"resolution": "accepted", "asked": True}, op_id="dimfind-selfresolve"
        )
    assert refused.value.reason == "invalid_requirement"

    assert sorted(finding.id for finding in findings(s2)) == open_ids
    outcome, _agent = ladder_outcome(s2, "dimfind-ledger")
    assert outcome.green is False


def test_the_model_cannot_dismiss_a_finding_itself(s2: Project) -> None:
    """The dismissal write refuses any provenance but the runtime's."""
    build(s2)
    finding_id = findings(s2)[0].id

    with pytest.raises(CadOpError) as refused:
        s2.cad.dismiss_dimension_finding(
            finding_id, answer="fine by me", dismissed=True, op_id="dimfind-self"
        )

    assert refused.value.reason == "invalid_dimension_finding"
    assert finding_id in {finding.id for finding in findings(s2)}


def test_asserting_the_number_in_checks_does_not_clear_it(s2: Project) -> None:
    """A self-authored acceptance test is never the evidence a misread is gone."""
    build(s2)
    open_ids = sorted(finding.id for finding in findings(s2))

    source = _bracket_source(s2)
    start = source.index("CHECKS = {")
    end = source.index("}", start) + 1
    _write_bracket(s2, source[:start] + _ASSERTING_CHECKS + source[end:])
    result = build(s2)

    # The threshold really did enter the advisory dimension pool …
    pool = cast("dict[str, Any]", result["critique"]["prompt_number_diff"]["dimensions"])
    assert any(name.startswith("checks_threshold:") for name in pool)
    # … and the binding record refused to look at it.
    assert sorted(finding.id for finding in findings(s2)) == open_ids


def test_the_reviewer_cannot_pass_a_dimension_finding(s2: Project) -> None:
    """No verdict is solicited for one, and none is accepted."""
    build(s2)
    open_ids = sorted(finding.id for finding in findings(s2))
    reviewer = Reviewer(
        [
            *PASS_R1,
            *(
                {"id": fid, "verdict": "pass", "evidence": "looks right", "channel": "vision"}
                for fid in open_ids
            ),
        ]
    )

    report = TerminationReviewService(s2.cad, reviewer).review(
        request=cast("str", s2.cad.request_text), run_id="dimfind-reviewer", parts=["bracket"]
    )

    assert set(report.open_ids) == set(open_ids)
    assert set(report.unknown_ids) == set(open_ids), "the reviewer's verdicts were filed, not used"
    assert all(report.by_id[fid].verdict == "fail" for fid in open_ids)
    assert all(report.by_id[fid].harness is True for fid in open_ids)
    assert report.green is False


# --------------------------------------------------------------------------
# §6: the same machinery as a review finding


def test_the_three_cycle_cap_and_unresolved_terminal_hold(s2: Project) -> None:
    build(s2)
    reviewer = Reviewer(PASS_R1)

    outcome, agent = ladder_outcome(s2, "dimfind-cap", reviewer)

    assert len(reviewer.contexts) == MAX_REVIEW_CYCLES == 3
    assert outcome.terminal.status == "unresolved_requirements"
    assert {item.id for item in outcome.terminal.unresolved} == {f.id for f in findings(s2)}
    assert agent.payloads[0]["status"] == "changes_required"
    assert agent.payloads[-1]["status"] == "unresolved_requirements"
    # The findings really re-entered as work, naming themselves.
    assert set(cast("list[Any]", agent.payloads[0]["unresolved_requirements"])) == {
        f.id for f in findings(s2)
    }


def test_the_same_dimension_failing_twice_escalates_with_the_dismissal_option(
    s2: Project,
) -> None:
    build(s2)
    entries = s2.cad.ledger_state().entries
    open_findings = findings(s2)
    ladder = ContinuationLadder()

    first = ladder.advance(
        normalize_findings(entries, PASS_R1, dimensions=open_findings),
        entries=entries,
        dimensions=open_findings,
    )
    second = ladder.advance(
        normalize_findings(entries, PASS_R1, cycle=2, dimensions=open_findings),
        entries=entries,
        dimensions=open_findings,
    )

    assert first.kind == "continue"
    assert second.kind == "escalate"
    assert set(second.escalated_ids) == {finding.id for finding in open_findings}
    questions = cast("list[Any]", second.payload["questions"])
    assert questions
    for raw in questions:
        options = cast("list[Any]", cast("dict[str, Any]", raw)["options"])
        assert 2 <= len(options) <= 4
        for option in options:
            entry = cast("dict[str, Any]", option)
            assert entry["option"] and entry["consequence"]
        # The escalation must name the route that actually exists: a dismissal.
        assert any("dismiss" in str(cast("dict[str, Any]", o)["option"]) for o in options)


def test_an_ignored_escalation_terminates_the_run(s2: Project) -> None:
    """A silent repair does not satisfy a mandatory question — for §4 findings too."""
    build(s2)
    entries = s2.cad.ledger_state().entries
    open_findings = findings(s2)
    ladder = ContinuationLadder(max_cycles=6)

    for cycle in (1, 2):
        ladder.advance(
            normalize_findings(entries, PASS_R1, cycle=cycle, dimensions=open_findings),
            entries=entries,
            dimensions=open_findings,
        )
    third = ladder.advance(
        normalize_findings(entries, PASS_R1, cycle=3, dimensions=open_findings),
        entries=entries,
        dimensions=open_findings,
    )

    assert third.kind == "terminate"
    assert "escalation_ignored" in cast("str", third.payload["reason"])

    # …and putting the question is what satisfies it: the runtime records `asked`.
    record_answers(
        s2.cad,
        "run-1",
        {"requirement_ids": [finding.id for finding in open_findings]},
        BENCH_ANSWER,
    )
    asked = findings(s2)
    assert all(finding.asked for finding in asked)
    resumed = ContinuationLadder(max_cycles=6)
    resumed.advance(
        normalize_findings(entries, PASS_R1, dimensions=asked), entries=entries, dimensions=asked
    )
    resumed.advance(
        normalize_findings(entries, PASS_R1, cycle=2, dimensions=asked),
        entries=entries,
        dimensions=asked,
    )
    continued = resumed.advance(
        normalize_findings(entries, PASS_R1, cycle=3, dimensions=asked),
        entries=entries,
        dimensions=asked,
    )
    # The question was put, so the run is allowed to keep going — it escalates
    # again rather than being terminated for having ignored the escalation.
    assert continued.kind == "escalate"
    assert continued.terminal is None
