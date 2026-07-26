"""The VALIDATION.md §3 clarification gate, through the real dispatcher.

The gate is the rung that makes an unconfirmed *material* assumption stop the
build instead of quietly becoming geometry. What is tested here is that every
part of it fires **by rule**:

* a material assumption refuses ``build_part`` with the discriminated
  ``clarification_required`` result — and the s2 wall-direction entry, the
  recorded seed-2 misread, is one of them;
* materiality is the harness's call, not the model's: an assumption tagged
  ``material: false`` whose subject is a §3 material class still blocks;
* only the *runtime* can clear the gate: ``asked``/``resolution`` are refused on
  every model-facing ledger write, so a run cannot answer its own question — the
  gate compels an ``ask_user``, and nothing else opens it;
* a recorded committal answer resolves the entry and unblocks the build;
* a declined / non-committal answer records ``asked`` and **leaves the entry
  assumed**: the build proceeds (§3's last clause, §6's "built, but wall
  direction unconfirmed") but §5 sees an unconfirmed assumption and forces a
  fail, so the run can never finish green on it;
* a genuinely immaterial assumption does not block anything;
* a clarification question without 2-4 consequence-bearing options is refused
  before any human is asked.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from hephaestus.agent_bridge.cad_ops import (
    CLARIFICATION_MAX_OPTIONS,
    CadOpError,
    answer_text,
    clarification_gate,
    invalid_question_result,
    is_committal,
    material_class,
    option_label,
    question_problems,
    question_refusal,
    record_answers,
    record_clarification_answer,
)
from hephaestus.agent_bridge.dispatch import DispatchError
from hephaestus.agent_bridge.review import normalize_findings
from hephaestus.testing.tools_fixture import ORCH, Project, make_project

#: §7's bench answerer, verbatim: the answer that declines to decide.
BENCH_NON_COMMITTAL: str = (
    "unspecified — use your engineering judgment and record it as an assumption."
)

#: The seed-2 case verbatim: nothing in the request says which side of the
#: stated footprint the wall stands on, and the answer moves 6 mm of geometry.
WALL_DIR: dict[str, Any] = {
    "id": "R9",
    "text": "wall stands outside the stated footprint",
    "source": "assumed",
    "rationale": "the request does not say which side of the stated Y the wall is on",
    "material": True,
    "applies_to": "bracket",
}
#: A specified entry: never gate material, whatever it is about.
R1: dict[str, Any] = {
    "id": "R1",
    "text": "base plate 60 mm in X",
    "source": "specified",
    "quote": "60 mm (X) by 40 mm (Y) base plate",
    "value": 60.0,
    "unit": "mm",
    "applies_to": "bracket",
}
#: An assumption that moves nothing: no §3 class, and declared immaterial.
NAMING: dict[str, Any] = {
    "id": "R20",
    "text": "call the solid bracket_body for readability",
    "source": "assumed",
    "rationale": "the request never names the solid",
    "material": False,
    "applies_to": "naming",
}

WALL_OPTIONS: list[dict[str, str]] = [
    {"label": "inside the stated footprint", "consequence": "40 mm overall, 34 mm internal"},
    {"label": "outside the stated footprint", "consequence": "46 mm overall, 40 mm internal"},
]


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Project]:
    p = make_project(tmp_path / "proj")
    try:
        yield p
    finally:
        p.close()


def _build(project: Project) -> dict[str, Any]:
    return cast("dict[str, Any]", project.call("build_part", {"name": "bracket"}))


# ==========================================================================
# the gate refuses the build


def test_a_material_assumption_blocks_the_build_with_the_discriminated_result(
    project: Project,
) -> None:
    """The s2 wall-direction entry is exactly what fires (VALIDATION.md §3)."""
    assert _build(project)["status"] == "ok", "the fixture builds while the ledger is empty"

    project.call("record_requirements", {"entries": [R1, WALL_DIR]})
    result = _build(project)

    assert result["status"] == "clarification_required"
    assert result["unresolved_material"] == ["R9"]
    assert [entry["id"] for entry in cast("list[Any]", result["entries"])] == ["R9"], (
        "only the offending entries ride on the refusal"
    )
    entry = cast("dict[str, Any]", cast("list[Any]", result["entries"])[0])
    assert entry["source"] == "assumed"
    assert entry["resolution"] is None
    assert "ask_user" in str(result["message"])
    assert "consequence" in str(result["message"])
    assert "artifact_ref" not in result, "a refused build produces no geometry"


def test_the_refusal_is_a_result_not_an_error_and_repeats(project: Project) -> None:
    """A refusal claims no idempotency key: it did no work, so it can be retried."""
    project.call("record_requirements", {"entries": [WALL_DIR]})
    first = project.call("build_part", {"name": "bracket"}, entry="e-build")
    second = project.call("build_part", {"name": "bracket"}, entry="e-build")
    assert first == second == first  # stable, and no KeyPayloadMismatch on the retry

    # …and once the runtime records a real answer, that same invocation id builds.
    record_clarification_answer(
        project.cad, "R9", cast("Any", WALL_OPTIONS[1]), op_id="clarify-retry"
    )
    built = project.call("build_part", {"name": "bracket"}, entry="e-build")
    assert built["status"] == "ok"


def test_the_model_cannot_disarm_the_gate_by_tagging_material_false(project: Project) -> None:
    """§3 materiality is classified by the harness from applies_to/text."""
    project.call(
        "record_requirements",
        {"entries": [{**WALL_DIR, "id": "R11", "material": False}]},
    )
    result = _build(project)
    assert result["status"] == "clarification_required"
    assert result["unresolved_material"] == ["R11"]
    # The ledger's own `unresolved_material` (the model's flag) is empty here —
    # the gate is strictly wider than the self-declaration.
    assert project.cad.ledger_state().unresolved_material == ()


def test_an_immaterial_assumption_does_not_block(project: Project) -> None:
    project.call("record_requirements", {"entries": [R1, NAMING]})
    assert _build(project)["status"] == "ok"
    assert not clarification_gate(project.cad.ledger_state()).blocked


def test_a_specified_entry_never_gates(project: Project) -> None:
    """Only assumptions gate: a traceable requirement is not a guess."""
    project.call(
        "record_requirements",
        {"entries": [{**R1, "id": "R2", "text": "wall outside the 40 mm footprint"}]},
    )
    assert _build(project)["status"] == "ok"


@pytest.mark.parametrize(
    ("applies_to", "text", "expected"),
    [
        ("bracket", "overall envelope in Y", "envelope_dimension"),
        ("plate", "origin at the lower-left corner", "datum_origin"),
        ("bracket", "wall stands outside the stated footprint", "feature_direction"),
        ("bore", "clearance fit for the M4 fastener", "fit_clearance"),
        ("bracket", "3 mm stock thickness", "material_thickness"),
        ("naming", "call the solid bracket_body for readability", None),
        ("documentation", "note the revision in a comment", None),
    ],
)
def test_material_classes_are_matched_from_the_entry_subject(
    applies_to: str, text: str, expected: str | None
) -> None:
    from hephaestus.agent_bridge.cad_ops import RequirementEntry

    entry = RequirementEntry(id="R1", text=text, source="assumed", applies_to=applies_to)
    assert material_class(entry) == expected


# ==========================================================================
# resolution


def test_a_recorded_resolution_unblocks_the_build(project: Project) -> None:
    project.call("record_requirements", {"entries": [R1, WALL_DIR]})
    assert _build(project)["status"] == "clarification_required"

    record_clarification_answer(
        project.cad,
        "R9",
        "outside — 46 mm overall, 40 mm internal",
        op_id="clarify-committal",
    )
    assert project.call("read_requirements", {})["unresolved_material"] == []
    assert _build(project)["status"] == "ok"


# ==========================================================================
# provenance: the run cannot answer its own question
#
# The §3 gate and §5's fail-unless-confirmed both key on the clarification
# record. If the model could write it, one `update_requirement` would disarm the
# gate AND buy a §5 pass on the same guess — "a gate the model can disarm by
# tagging its own guess is not a gate" applies to the resolution exactly as it
# applies to `material: false`.


@pytest.mark.parametrize("field", ["asked", "resolution"])
def test_the_model_cannot_write_the_clarification_record(project: Project, field: str) -> None:
    """§3: ``asked``/``resolution`` are refused on a model-facing patch."""
    project.call("record_requirements", {"entries": [WALL_DIR]})
    value: Any = True if field == "asked" else "outside — I decided"

    with pytest.raises(CadOpError) as raised:
        project.cad.update_requirement("R9", {field: value}, op_id="self-resolve")

    assert raised.value.reason == "invalid_requirement"
    assert "ask_user" in str(raised.value)
    entry = project.cad.ledger_state().by_id["R9"]
    assert (entry.asked, entry.resolution) == (False, None), "nothing was written"
    assert clarification_gate(project.cad.ledger_state()).blocked, "the gate is still shut"
    assert _build(project)["status"] == "clarification_required"


@pytest.mark.parametrize("field", ["asked", "resolution"])
def test_the_model_cannot_declare_the_clarification_record_on_a_new_entry(
    project: Project, field: str
) -> None:
    """The same refusal on ``record_requirements`` — the other write path."""
    value: Any = True if field == "asked" else "outside — I decided"

    with pytest.raises(DispatchError) as raised:
        project.call("record_requirements", {"entries": [{**WALL_DIR, field: value}]})

    assert raised.value.reason == "invalid_requirement"
    assert project.cad.ledger_state().entries == (), "the whole batch is refused"


def test_re_recording_an_entry_neither_forges_nor_erases_the_answer(project: Project) -> None:
    """An upsert carries the runtime's clarification record across untouched."""
    project.call("record_requirements", {"entries": [WALL_DIR]})
    record_clarification_answer(
        project.cad, "R9", cast("Any", WALL_OPTIONS[1]), op_id="clarify-keep"
    )

    project.call(
        "record_requirements",
        {"entries": [{**WALL_DIR, "text": "wall stands outside (restated)"}]},
    )

    entry = project.cad.ledger_state().by_id["R9"]
    assert entry.text == "wall stands outside (restated)", "the model's own fields do update"
    assert entry.asked is True and entry.resolution is not None, "the answer survives"


def test_a_committal_answer_resolves_the_entry(project: Project) -> None:
    project.call("record_requirements", {"entries": [WALL_DIR]})
    outcome = record_clarification_answer(
        project.cad, "R9", cast("Any", WALL_OPTIONS[1]), op_id="clarify-1"
    )
    assert outcome.committal is True
    entry = project.cad.ledger_state().by_id["R9"]
    assert entry.asked is True
    assert entry.resolution is not None
    assert "46 mm overall" in entry.resolution, "the consequence is recorded, not just the label"
    assert entry.source == "assumed", "the provenance of the value is not rewritten"
    assert not clarification_gate(project.cad.ledger_state()).blocked


@pytest.mark.parametrize(
    "answer",
    [
        "unspecified — use your engineering judgment and record it as an assumption.",
        "I don't know",
        "no preference",
        "either way is fine",
        "",
    ],
)
def test_a_non_committal_answer_keeps_the_entry_assumed_and_marks_it_asked(
    project: Project, answer: str
) -> None:
    """§3/§7: asking is recorded; guessing is not laundered into a resolution.

    The build then proceeds — the gate's job is to compel the question, and §3's
    closing clause hands a declined answer to §5 ("it then must survive §5
    review"), which is where §6's honest ending, "built, but wall direction
    unconfirmed", comes from. What must hold is that the entry is still *assumed
    and unconfirmed* afterwards, so §5 forces a fail on it; that is asserted by
    ``test_a_declined_answer_can_never_finish_green`` below.
    """
    project.call("record_requirements", {"entries": [WALL_DIR]})
    outcome = record_clarification_answer(project.cad, "R9", answer, op_id="clarify-nc")

    assert outcome.committal is False
    entry = project.cad.ledger_state().by_id["R9"]
    assert entry.asked is True, "the question is on the record"
    assert entry.resolution is None, "a non-answer is not a resolution"
    assert entry.confirmed is False
    assert entry.source == "assumed"
    assert entry.unresolved_material is True, "still an open item for §5/§6"
    assert not clarification_gate(project.cad.ledger_state()).blocked
    assert _build(project)["status"] == "ok"


def test_a_declined_answer_can_never_finish_green(project: Project) -> None:
    """The burden a declined answer shifts onto §5 is actually carried there."""
    project.call("record_requirements", {"entries": [WALL_DIR]})
    record_clarification_answer(project.cad, "R9", BENCH_NON_COMMITTAL, op_id="clarify-declined")
    assert _build(project)["status"] == "ok", "the run reaches geometry"

    entries = project.cad.ledger_state().entries
    # …and the reviewer's most generous possible verdict is overruled by rule.
    report = normalize_findings(
        entries, [{"id": "R9", "verdict": "pass", "evidence": "looks right to me"}]
    )
    finding = report.findings[0]
    assert (finding.verdict, finding.forced_assumption) == ("fail", True)
    assert report.open_ids == ("R9",)


def test_recording_an_answer_is_idempotent_on_the_derived_op_id(project: Project) -> None:
    project.call("record_requirements", {"entries": [WALL_DIR]})
    params: dict[str, Any] = {"requirement_ids": ["R9"], "question": "q", "options": WALL_OPTIONS}
    first = record_answers(project.cad, "run-1", params, cast("Any", WALL_OPTIONS[0]))
    generation = project.cad.ledger_state().generation
    again = record_answers(project.cad, "run-1", params, cast("Any", WALL_OPTIONS[0]))

    assert again == first
    assert project.cad.ledger_state().generation == generation, "a replay writes no generation"


def test_an_answer_to_an_unknown_id_is_reported_not_raised(project: Project) -> None:
    project.call("record_requirements", {"entries": [WALL_DIR]})
    recorded = record_answers(
        project.cad, "run-1", {"requirement_ids": ["R404"]}, "inside the footprint"
    )
    assert recorded == [
        {"id": "R404", "committal": True, "recorded": False, "resolution": "inside the footprint"}
    ]


# ==========================================================================
# question shape (enforced before anyone is asked)


def test_a_clarification_must_carry_consequence_bearing_options() -> None:
    params: dict[str, Any] = {
        "requirement_ids": ["R9"],
        "question": "which side does the wall stand on?",
        "options": ["inside", "outside"],
    }
    refusal = question_refusal(params)
    assert refusal is not None
    assert refusal["status"] == "invalid_question"
    assert refusal["code"] == "clarification_question_shape"
    problems = cast("list[str]", refusal["problems"])
    assert len(problems) == 2
    assert all("geometric consequence" in problem for problem in problems)


@pytest.mark.parametrize(
    "options",
    [
        [WALL_OPTIONS[0]],  # too few
        [{**WALL_OPTIONS[0], "label": f"option {i}"} for i in range(CLARIFICATION_MAX_OPTIONS + 1)],
        [{"label": "inside", "consequence": ""}, WALL_OPTIONS[1]],
        [{"label": "", "consequence": "40 mm overall"}, WALL_OPTIONS[1]],
        "not an array",
    ],
)
def test_badly_shaped_clarifications_are_refused(options: Any) -> None:
    params = {"requirement_ids": ["R9"], "question": "which side?", "options": options}
    assert question_refusal(params) is not None


def test_a_well_shaped_clarification_is_asked() -> None:
    params = {"requirement_ids": ["R9"], "question": "which side?", "options": WALL_OPTIONS}
    assert question_refusal(params) is None


def test_an_ordinary_question_is_not_held_to_the_clarification_shape() -> None:
    """The pattern binds clarifications; a plain question keeps string options."""
    assert question_refusal({"question": "proceed?", "options": ["yes"]}) is None
    assert question_problems("proceed?", ["yes"]) != ()


def test_the_refusal_names_every_problem_at_once() -> None:
    result = invalid_question_result(("a", "b"))
    assert result["problems"] == ["a", "b"]
    assert "was not asked" in str(result["message"])


# ==========================================================================
# answer normalization


@pytest.mark.parametrize(
    ("selection", "expected"),
    [
        ("outside", True),
        ({"label": "outside", "consequence": "46 mm overall"}, True),
        (["outside", "flush"], True),
        ("unspecified — use your engineering judgment", False),
        ("   ", False),
        (None, False),
    ],
)
def test_committal_classification(selection: Any, expected: bool) -> None:
    assert is_committal(selection) is expected


def test_answer_text_flattens_every_selection_shape() -> None:
    assert answer_text(cast("Any", WALL_OPTIONS[1])) == (
        "outside the stated footprint — 46 mm overall, 40 mm internal"
    )
    assert answer_text(cast("Any", ["a", "b"])) == "a; b"
    assert option_label(cast("Any", WALL_OPTIONS[1])) == "outside the stated footprint"
    assert option_label(cast("Any", "plain")) == "plain"


# ==========================================================================
# the gate is a dispatch-layer rule, not a per-profile courtesy


def test_the_gate_applies_to_every_session_that_can_build(project: Project) -> None:
    from hephaestus.testing.tools_fixture import PART_WIDGET, QUICK_WIDGET

    project.call("record_requirements", {"entries": [WALL_DIR]})
    for principal in (ORCH, PART_WIDGET, QUICK_WIDGET):
        name = "bracket" if principal is ORCH else "widget"
        result = project.call("build_part", {"name": name}, principal=principal)
        assert result["status"] == "clarification_required", principal.profile
