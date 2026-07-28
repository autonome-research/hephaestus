"""``ASSEMBLY.md`` §3: the constraint quartet, the reviewer rule, the bench path.

Everything here is asserted through the *real* dispatcher, over real geometry, so
what is tested is the surface a model actually meets:

* the four tools on both declared profiles, including every refusal the contract
  names (``invalid_constraint`` for a malformed or provenance-less entry,
  ``unknown_constraint`` for a patch or a check naming an id the set does not
  carry) — and the ``quick_edit``/``reviewer`` profiles being denied, which is
  what keeps a reviewer from writing the constraints it is judging;
* withdrawal as a new generation that erases nothing;
* the never-green rule extended to assemblies: a violated constraint at
  termination review is a BLOCKING finding stamped from the engine's status,
  never solicited from the reviewer — asserted with a reviewer that passes
  everything it is shown;
* the bench grading path over a two-part fixture, scoring on the declared fit
  through the same engine call the tool uses.

The fixture geometry is deliberately concrete: ``widget`` and ``bracket`` are
co-located boxes (they really do interfere), and ``spacer`` is a box 50 mm away
(it really does clear). So a "satisfied" assertion here is a measurement, not a
mock.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any, cast

import pytest
from hephaestus.agent_bridge.dispatch import DispatchError, Principal
from hephaestus.agent_bridge.review import (
    ReviewerResponse,
    ReviewRequest,
    TerminalReport,
    TerminationReviewService,
    assembly_review_findings,
    assembly_status,
    build_review_context,
)
from hephaestus.contract import tools_decl
from hephaestus.core.project_store.constraints import (
    ANCHOR_PATTERN,
    CONSTRAINT_ID_PATTERN,
    constraint_kinds,
)
from hephaestus.testing.tools_fixture import (
    PART_WIDGET,
    QUICK_WIDGET,
    Project,
    make_project,
)

QUARTET: tuple[str, ...] = (
    "declare_constraint",
    "update_constraint",
    "read_constraints",
    "check_assembly",
)

#: A part 50 mm away from the co-located widget/bracket pair: a real clearance.
SPACER_SRC = """body = Pos(50.0, 0.0, 0.0) * Box(10.0, 10.0, hc.wall)
body.label = "spacer_body"
part.geometry = body
"""

REVIEWER = Principal(session_id="rv", profile="reviewer", part=None)


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Project]:
    # The seeded minimal ledger is a build precondition here, not a subject
    # (VALIDATION.md §2 refuses build_part on an empty one); the review tests
    # below record the entries they actually mean to have judged.
    proj = make_project(tmp_path / "proj")
    (proj.root / "parts" / "spacer.py").write_text(SPACER_SRC, encoding="utf-8")
    try:
        yield proj
    finally:
        proj.close()


def clearance(
    constraint_id: str = "c-gap",
    *,
    a: str = "widget",
    b: str = "spacer",
    value_mm: float = 1.0,
    **fields: Any,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": constraint_id,
        "kind": "clearance_min",
        "a": a,
        "b": b,
        "value_mm": value_mm,
        "provenance": {"assumed": True, "reason": "fixture mate"},
    }
    entry.update(fields)
    return entry


def outcome(result: Mapping[str, Any], constraint_id: str) -> dict[str, Any]:
    status = cast("Mapping[str, Any]", result["assembly"])
    for item in cast("Sequence[Any]", status["constraints"]):
        row = cast("dict[str, Any]", item)
        if row["id"] == constraint_id:
            return row
    raise AssertionError(f"no constraint {constraint_id} in {status}")


# ==========================================================================
# the declaration: vocabulary, availability, profiles


def test_declared_constraint_vocabulary_matches_geom() -> None:
    """The schema restates geom's tables; drift between them is a bug here.

    ``tools_decl`` cannot import ``hephaestus.geom`` (the contract package is pure
    declaration and geom binds the CAD kernel at import), so the equality that
    keeps the tool schema honest is asserted rather than enforced by construction.
    """
    from hephaestus.geom.constraints import CONSTRAINT_KINDS, OPTIONAL_PARAMS, REQUIRED_PARAMS

    assert tuple(CONSTRAINT_KINDS) == tools_decl.CONSTRAINT_KINDS
    declared: set[str] = set()
    for kind in CONSTRAINT_KINDS:
        declared |= set(REQUIRED_PARAMS[kind]) | set(OPTIONAL_PARAMS[kind])
    assert set(tools_decl.CONSTRAINT_PARAMS) == declared
    # …and the store's own grammars, for the same reason.
    assert tools_decl.CONSTRAINT_ID_PATTERN == CONSTRAINT_ID_PATTERN
    assert tools_decl.CONSTRAINT_ANCHOR_PATTERN == ANCHOR_PATTERN
    assert constraint_kinds() == tools_decl.CONSTRAINT_KINDS


def test_the_quartet_is_declared_on_the_canonical_pipeline_only() -> None:
    for name in QUARTET:
        assert tools_decl.get_tool(name).profiles == ("part", "orchestrator"), name


@pytest.mark.parametrize("tool", QUARTET)
def test_a_reviewer_may_not_touch_the_constraints_it_judges(project: Project, tool: str) -> None:
    with pytest.raises(DispatchError) as excinfo:
        project.call(tool, {}, principal=REVIEWER)
    assert excinfo.value.reason == "scope_denied"


@pytest.mark.parametrize("tool", QUARTET)
def test_a_quick_edit_session_declares_no_cross_part_mates(project: Project, tool: str) -> None:
    with pytest.raises(DispatchError) as excinfo:
        project.call(tool, {}, principal=QUICK_WIDGET)
    assert excinfo.value.reason == "scope_denied"


def test_a_part_session_may_declare_a_mate_touching_another_part(project: Project) -> None:
    """A constraint spans parts by nature; scoping it to one would gut it."""
    result = project.call("declare_constraint", clearance(), principal=PART_WIDGET)
    assert result["generation"] == 1
    assert [entry["id"] for entry in result["entries"]] == ["c-gap"]
    assert project.call("read_constraints", {}, principal=PART_WIDGET)["generation"] == 1


# ==========================================================================
# generations: declare -> update -> withdraw, nothing erased


def test_declare_update_withdraw_are_three_generations(project: Project) -> None:
    declared = project.call("declare_constraint", clearance())
    assert declared["generation"] == 1
    assert declared["artifact_ref"].startswith("artifact:constraints:sha256:")
    assert declared["change"] == {
        "kind": "declare",
        "id": "c-gap",
        "patch": declared["entries"][0],
    }

    revised = project.call(
        "update_constraint",
        {"id": "c-gap", "patch": {"value_mm": 2.5}, "reason": "datasheet says 2.5"},
    )
    assert revised["generation"] == 2
    assert revised["entries"][0]["value_mm"] == 2.5
    assert revised["change"]["reason"] == "datasheet says 2.5"

    withdrawn = project.call(
        "update_constraint",
        {"id": "c-gap", "patch": {"withdrawn": True}, "reason": "the lid was deleted"},
    )
    assert withdrawn["generation"] == 3
    # Withdrawn, not erased: the entry and its reason stay in the projection.
    assert withdrawn["entries"][0]["withdrawn"] is True
    assert withdrawn["entries"][0]["withdrawn_reason"] == "the lid was deleted"

    # …and every earlier generation is still readable through the engine.
    history = project.cad.constraint_set().history()
    assert [state.generation for state in history] == [1, 2, 3]
    assert history[0].entries[0].values["value_mm"] == 1.0


def test_a_withdrawn_constraint_is_never_evaluated(project: Project) -> None:
    project.build("widget", "spacer")
    project.call("declare_constraint", clearance(value_mm=1000.0))
    violated = project.call("check_assembly", {})
    assert violated["assembly"]["blocking"] == ["c-gap"]

    project.call(
        "update_constraint",
        {"id": "c-gap", "patch": {"withdrawn": True}, "reason": "not a real mate"},
    )
    after = project.call("check_assembly", {})
    assert after["assembly"]["constraints"] == []
    assert after["assembly"]["blocking"] == []


# ==========================================================================
# refusals — the two machine tokens, and nothing written


def test_provenance_is_compelled(project: Project) -> None:
    entry = clearance()
    del entry["provenance"]
    with pytest.raises(DispatchError) as excinfo:
        project.call("declare_constraint", entry)
    assert excinfo.value.reason == "invalid_constraint"
    assert "provenance" in excinfo.value.message
    assert project.call("read_constraints", {})["generation"] == 0


def test_an_assumption_without_a_reason_is_refused(project: Project) -> None:
    with pytest.raises(DispatchError) as excinfo:
        project.call("declare_constraint", clearance(provenance={"assumed": True}))
    assert excinfo.value.reason == "invalid_constraint"


def test_a_kinds_own_parameters_are_enforced(project: Project) -> None:
    entry = clearance()
    del entry["value_mm"]
    with pytest.raises(DispatchError) as excinfo:
        project.call("declare_constraint", entry)
    assert excinfo.value.reason == "invalid_constraint"
    assert "value_mm" in excinfo.value.message


def test_a_repeated_id_is_refused_rather_than_replaced(project: Project) -> None:
    project.call("declare_constraint", clearance())
    with pytest.raises(DispatchError) as excinfo:
        project.call("declare_constraint", clearance(value_mm=9.0))
    assert excinfo.value.reason == "invalid_constraint"
    assert project.call("read_constraints", {})["entries"][0]["value_mm"] == 1.0


def test_patching_an_unknown_constraint_is_unknown_constraint(project: Project) -> None:
    with pytest.raises(DispatchError) as excinfo:
        project.call(
            "update_constraint", {"id": "c-nope", "patch": {"value_mm": 1.0}, "reason": "r"}
        )
    assert excinfo.value.reason == "unknown_constraint"


def test_checking_an_unknown_id_names_the_constraints_that_exist(project: Project) -> None:
    project.call("declare_constraint", clearance())
    with pytest.raises(DispatchError) as excinfo:
        project.call("check_assembly", {"ids": ["c-nope"]})
    assert excinfo.value.reason == "unknown_constraint"
    assert "c-gap" in excinfo.value.message


def test_a_withdrawal_carrying_field_edits_is_refused(project: Project) -> None:
    """Two acts, two generations: "stop claiming it" is not "the number changed"."""
    project.call("declare_constraint", clearance())
    with pytest.raises(DispatchError) as excinfo:
        project.call(
            "update_constraint",
            {"id": "c-gap", "patch": {"withdrawn": True, "value_mm": 3.0}, "reason": "both"},
        )
    assert excinfo.value.reason == "invalid_constraint"
    assert project.call("read_constraints", {})["generation"] == 1


def test_a_revision_without_a_reason_is_refused(project: Project) -> None:
    project.call("declare_constraint", clearance())
    with pytest.raises(DispatchError) as excinfo:
        project.call(
            "update_constraint", {"id": "c-gap", "patch": {"value_mm": 2.0}, "reason": " "}
        )
    assert excinfo.value.reason == "invalid_constraint"


# ==========================================================================
# evaluation: real geometry, and the three states kept apart


def test_a_satisfied_fit_is_measured_not_asserted(project: Project) -> None:
    project.build("widget", "spacer")
    project.call("declare_constraint", clearance(value_mm=1.0))
    result = project.call("check_assembly", {})
    row = outcome(result, "c-gap")
    assert row["state"] == "satisfied"
    assert row["residual"]["measured"] > 1.0
    assert row["residual"]["unit"] == "mm"
    assert row["a"]["rule"] == "part" and row["a"]["artifact_ref"].startswith("artifact:")
    assert result["assembly"]["blocking"] == []
    assert result["partial"] is False
    assert result["artifact_ref"].startswith("artifact:assembly-status:sha256:")


def test_a_violated_fit_reports_the_measurement_against_the_declaration(
    project: Project,
) -> None:
    project.build("widget", "spacer")
    project.call("declare_constraint", clearance(value_mm=1000.0))
    row = outcome(project.call("check_assembly", {}), "c-gap")
    assert row["state"] == "violated"
    assert row["residual"]["satisfied"] is False
    assert row["residual"]["slack"] < 0.0
    assert row["reason"] is None and row["detail"] is None


def test_an_unbuilt_part_is_unresolvable_and_not_violated(project: Project) -> None:
    project.build("widget")
    project.call("declare_constraint", clearance())
    row = outcome(project.call("check_assembly", {}), "c-gap")
    assert row["state"] == "unresolvable"
    assert row["reason"] == "no_current_build"
    assert row["residual"] is None
    # …and it still blocks: an unchecked constraint is not a passing one.
    assert project.call("read_constraints", {})["assembly"]["blocking"] == ["c-gap"]


def test_a_dangling_selector_is_its_own_reason(project: Project) -> None:
    project.build("widget", "spacer")
    project.call("declare_constraint", clearance(a="widget:no_such_tag"))
    row = outcome(project.call("check_assembly", {}), "c-gap")
    assert row["state"] == "unresolvable"
    assert row["reason"] == "dangling_selector"


def test_reading_never_measures_and_a_partial_check_is_not_projected(
    project: Project,
) -> None:
    project.build("widget", "spacer")
    project.call("declare_constraint", clearance())
    # Never evaluated is null — which is not "the constraints hold".
    assert project.call("read_constraints", {})["assembly"] is None

    partial = project.call("check_assembly", {"ids": ["c-gap"]})
    assert partial["partial"] is True and partial["artifact_ref"] is None
    assert project.call("read_constraints", {})["assembly"] is None, (
        "a partial evaluation must not become the project's assembly status"
    )

    project.call("check_assembly", {})
    read = project.call("read_constraints", {})
    assert read["assembly"]["counts"]["satisfied"] == 1
    assert read["assembly_ref"].startswith("artifact:assembly-status:sha256:")


def test_a_rebuild_marks_the_projected_status_stale(project: Project) -> None:
    project.build("widget", "spacer")
    project.call("declare_constraint", clearance())
    assert project.call("check_assembly", {})["assembly"]["stale"] == []
    # A rebuild that moves the geometry moves the artifact, and the projection
    # says so rather than reporting a measurement of the previous shape.
    (project.root / "parts" / "spacer.py").write_text(
        SPACER_SRC.replace("Pos(50.0, 0.0, 0.0)", "Pos(60.0, 0.0, 0.0)"), encoding="utf-8"
    )
    project.build("spacer")
    assert project.call("read_constraints", {})["assembly"]["stale"] == ["spacer"]


# ==========================================================================
# VALIDATION.md §5: the never-green rule, extended to assemblies


class PassEverything:
    """A reviewer that passes every requirement it is shown, confidently."""

    def __init__(self) -> None:
        self.requests: list[ReviewRequest] = []

    def call(self, request: ReviewRequest) -> ReviewerResponse:
        self.requests.append(request)
        findings = [
            {
                "id": str(entry["id"]),
                "verdict": "pass",
                "evidence": "looks right to me",
                "channel": "numeric",
            }
            for entry in request.context.requirements
        ]
        # …including a pass for the constraint itself, which must count for nothing.
        findings.append(
            {"id": "c-gap", "verdict": "pass", "evidence": "the mate is fine", "channel": "vision"}
        )
        return ReviewerResponse(findings=tuple(findings))


def _record_ledger(project: Project) -> None:
    project.call(
        "record_requirements",
        {
            "entries": [
                {
                    "id": "R1",
                    "text": "the widget is 40 mm wide",
                    "source": "specified",
                    "quote": "the widget is 40 mm wide",
                    "value": 40.0,
                    "unit": "mm",
                }
            ]
        },
    )


def test_the_review_context_carries_the_full_assembly_status(project: Project) -> None:
    project.build("widget", "spacer")
    _record_ledger(project)
    project.call("declare_constraint", clearance())
    context = build_review_context(project.cad, request="build a widget")
    assert context.assembly is not None
    assert context.assembly.satisfied == ("c-gap",)
    assert context.assembly_ref is not None
    blob = json.loads(json.dumps(context.to_json()))
    assert blob["assembly"]["constraints"][0]["kind"] == "clearance_min"
    assert "assembly" in context.prompt()


def test_no_constraints_means_no_assembly_section(project: Project) -> None:
    project.build("widget")
    context = build_review_context(project.cad, request="build a widget")
    assert context.assembly is None and context.assembly_ref is None
    assert assembly_review_findings(context.assembly) == ()


def test_a_violated_constraint_blocks_termination_however_it_is_reviewed(
    project: Project,
) -> None:
    project.build("widget", "spacer")
    _record_ledger(project)
    project.call("declare_constraint", clearance(value_mm=1000.0))

    reviewer = PassEverything()
    service = TerminationReviewService(project.cad, reviewer)
    report = service.review(request="build a widget", run_id="run-1")

    # The reviewer passed everything, including the constraint id it was handed.
    assert report.by_id["R1"].verdict == "pass"
    assert "c-gap" in report.unknown_ids, "a verdict for a constraint id counts for nothing"
    blocking = report.by_id["c-gap"]
    assert blocking.verdict == "fail" and blocking.harness is True
    assert "violated" in blocking.evidence and "1000" in (blocking.expected or "")
    assert report.green is False
    assert report.assembly is not None and report.assembly.blocking() == ("c-gap",)

    terminal = TerminalReport.of(
        report, cycles=1, reason="stop state", entries=project.cad.ledger_state().entries
    )
    assert terminal.status == "unresolved_requirements"
    open_item = next(item for item in terminal.unresolved if item.id == "c-gap")
    assert open_item.source == "constraint"


def test_an_unresolvable_constraint_blocks_for_its_own_reason(project: Project) -> None:
    project.build("widget")  # spacer never built: the mate cannot be measured
    _record_ledger(project)
    project.call("declare_constraint", clearance())

    service = TerminationReviewService(project.cad, PassEverything())
    report = service.review(request="build a widget", run_id="run-1")
    blocking = report.by_id["c-gap"]
    assert blocking.verdict == "fail" and blocking.harness is True
    assert "could NOT be evaluated" in blocking.evidence
    assert "no_current_build" in blocking.evidence
    assert "violated" not in blocking.evidence.split("could NOT")[0]
    assert report.green is False


def test_a_satisfied_constraint_leaves_the_review_green(project: Project) -> None:
    project.build("widget", "spacer")
    _record_ledger(project)
    project.call("declare_constraint", clearance())
    report = TerminationReviewService(project.cad, PassEverything()).review(
        request="build a widget", run_id="run-1"
    )
    assert report.green is True
    assert report.assembly is not None and report.assembly.blocking() == ()


def test_the_reviewer_reads_a_status_measured_now_not_a_stale_projection(
    project: Project,
) -> None:
    """An edit that breaks a fit is caught even though nothing re-ran the check."""
    project.build("widget", "spacer")
    _record_ledger(project)
    project.call("declare_constraint", clearance())
    assert project.call("check_assembly", {})["assembly"]["blocking"] == []

    # Move the spacer onto the widget: the projected status now says "satisfied",
    # but the delivered geometry does not.
    (project.root / "parts" / "spacer.py").write_text(
        SPACER_SRC.replace("Pos(50.0, 0.0, 0.0) * ", ""), encoding="utf-8"
    )
    project.build("spacer")

    status = assembly_status(project.cad)
    assert status is not None and status.blocking() == ("c-gap",)
    report = TerminationReviewService(project.cad, PassEverything()).review(
        request="build a widget", run_id="run-1"
    )
    assert report.green is False


# ==========================================================================
# bench: a task's declared fits, graded through the engine path


def _bench_task(tmp_path: Path, *, value_mm: float) -> Any:
    from hephaestus.bench.harness import BenchTask

    directory = tmp_path / "task"
    (directory / "checks").mkdir(parents=True, exist_ok=True)
    spec: dict[str, Any] = {
        "id": "task",
        "prompt": "put a spacer next to the widget",
        "budget_tool_calls": 50,
        "constraint_requirements": [
            {
                "entry": {
                    "id": "c-gap",
                    "kind": "clearance_min",
                    "a": "widget",
                    "b": "spacer",
                    "value_mm": value_mm,
                }
            }
        ],
    }
    (directory / "task.json").write_text(json.dumps(spec), encoding="utf-8")
    return BenchTask.load(directory)


def test_bench_grades_a_declared_fit_through_the_engine(project: Project, tmp_path: Path) -> None:
    from hephaestus.bench.harness import grade

    project.build("widget", "spacer", "bracket")
    project.close()  # grading opens the project itself

    report = grade(_bench_task(tmp_path, value_mm=1.0), project.root)
    assert [record["outcome"]["state"] for record in report.constraints] == ["satisfied"]
    assert not [reason for reason in report.reasons if reason.startswith("constraint_")]

    # The same geometry against a fit it cannot meet fails, by name and with the
    # measurement in the reason.
    failed = grade(_bench_task(tmp_path, value_mm=1000.0), project.root)
    assert any(reason.startswith("constraint_violated:c-gap:") for reason in failed.reasons)
    assert failed.passed is False


def test_bench_declares_over_whatever_the_run_declared(project: Project, tmp_path: Path) -> None:
    """The acceptance spec is the task's, exactly like its CHECKS."""
    from hephaestus.bench.harness import grade

    project.build("widget", "spacer", "bracket")
    # The run declares the same id with a fit it trivially meets.
    project.call("declare_constraint", clearance(value_mm=0.0))
    project.close()

    report = grade(_bench_task(tmp_path, value_mm=1000.0), project.root)
    assert any(reason.startswith("constraint_violated:c-gap:") for reason in report.reasons)


def test_bench_regrants_a_constraint_the_run_withdrew(project: Project, tmp_path: Path) -> None:
    """A run cannot duck an acceptance mate by withdrawing its id.

    Withdrawal is a legitimate act on the run's OWN claims, but the task owns
    this id: a withdrawn entry is never evaluated, so leaving it withdrawn would
    let a run escape the acceptance constraint by paperwork rather than by
    geometry — and would surface as a harness error rather than as its failure.
    """
    from hephaestus.bench.harness import grade

    project.build("widget", "spacer", "bracket")
    project.call("declare_constraint", clearance(value_mm=0.0))
    project.call(
        "update_constraint",
        {"id": "c-gap", "patch": {"withdrawn": True}, "reason": "not claiming this after all"},
    )
    project.close()

    report = grade(_bench_task(tmp_path, value_mm=1000.0), project.root)

    assert [record["outcome"]["state"] for record in report.constraints] == ["violated"]
    assert any(reason.startswith("constraint_violated:c-gap:") for reason in report.reasons)
    assert not [reason for reason in report.reasons if reason.startswith("harness_error:")]
    assert report.passed is False


def test_bench_reports_an_unmeasurable_fit_as_unresolvable(
    project: Project, tmp_path: Path
) -> None:
    from hephaestus.bench.harness import grade

    # Nothing built at all: grading rebuilds every part, so make the anchor itself
    # unresolvable by naming a tag no part carries.
    project.build("widget", "spacer", "bracket")
    project.close()
    task = _bench_task(tmp_path, value_mm=1.0)
    broken = task.constraints[0]
    entry = dict(broken.entry)
    entry["a"] = "widget:absent_tag"
    task = type(task)(**{**task.__dict__, "constraints": (type(broken)(entry=entry),)})

    report = grade(task, project.root)
    assert any(
        reason.startswith("constraint_unresolvable:c-gap:dangling_selector")
        for reason in report.reasons
    ), report.reasons
