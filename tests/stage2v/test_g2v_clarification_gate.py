"""G2V clause: the clarification gate (``VALIDATION.md`` §3).

The gate clause reads: *"the clarification gate (material assumption blocks
``build_part`` with the discriminated result; resolution unblocks; non-committal
answer keeps ``assumed`` + ``asked``)"*. Those three sentences are the three
tests below, driven end to end through the real dispatcher over a real project
store — plus the fourth property that makes the rung a rule rather than a
request: the model can neither exempt its own guess from the gate (``material:
false``) nor clear it by writing the clarification record itself.

The exhaustive unit coverage (material-class table, question shaping, answer
normalization, idempotent answer recording) lives in
``server/tests/test_clarification_gate.py``; this module is the gate evidence.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from hephaestus.agent_bridge.cad_ops import question_refusal, record_clarification_answer
from hephaestus.agent_bridge.dispatch import DispatchError
from hephaestus.testing.tools_fixture import Project, make_project

#: The recorded seed-2 misread: the request never says which side of the stated
#: 40 mm the wall stands on, and the answer is 6 mm of geometry.
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


def _build(project: Project) -> dict[str, Any]:
    return cast("dict[str, Any]", project.call("build_part", {"name": "bracket"}))


def test_a_material_assumption_blocks_the_build(project: Project) -> None:
    project.call("record_requirements", {"entries": [WALL_DIR]})
    result = _build(project)
    assert result["status"] == "clarification_required"
    assert [e["id"] for e in cast("list[Any]", result["entries"])] == ["R9"]
    assert result["message"]


def test_the_gate_is_not_the_model_s_to_disarm(project: Project) -> None:
    """An assumption tagged ``material: false`` in a §3 class still blocks."""
    project.call("record_requirements", {"entries": [{**WALL_DIR, "material": False}]})
    assert _build(project)["status"] == "clarification_required"


def test_a_resolution_unblocks_the_build(project: Project) -> None:
    project.call("record_requirements", {"entries": [WALL_DIR]})
    assert _build(project)["status"] == "clarification_required"
    record_clarification_answer(
        project.cad,
        "R9",
        {"label": "outside", "consequence": "46 mm overall, 40 mm internal"},
        op_id="g2v-answer",
    )
    assert _build(project)["status"] == "ok"


def test_a_non_committal_answer_keeps_the_entry_assumed_and_asked(project: Project) -> None:
    """§7's bench answer records the question without resolving the assumption.

    The gate then lets the run reach geometry — §3's closing clause hands a
    declined answer to §5 ("it then must survive §5 review"), and §6's model of a
    good ending is "built, but wall direction unconfirmed". What may not happen is
    finishing *green*, which is pinned by
    ``test_g2v_termination_review.test_assumed_entries_are_failures_until_confirmed``.
    """
    project.call("record_requirements", {"entries": [WALL_DIR]})
    record_clarification_answer(
        project.cad,
        "R9",
        "unspecified — use your engineering judgment and record it as an assumption.",
        op_id="g2v-noncommittal",
    )
    entry = project.cad.ledger_state().by_id["R9"]
    assert (entry.source, entry.asked, entry.resolution) == ("assumed", True, None)
    assert entry.unresolved_material is True, "still open for §5/§6 and §8's metrics"
    assert _build(project)["status"] == "ok"


@pytest.mark.parametrize("field", ["asked", "resolution"])
def test_the_run_cannot_write_its_own_clarification_record(project: Project, field: str) -> None:
    """§3: only the runtime writes ``asked``/``resolution``, from a real answer.

    Both the gate and §5's fail-unless-confirmed key on this record. If the model
    could write it, one ``update_requirement`` would disarm the gate and buy a §5
    pass on the same guess — the ``material: false`` escape, reopened one field
    over. So both fields are refused on every model-facing ledger write.
    """
    project.call("record_requirements", {"entries": [WALL_DIR]})
    value: Any = True if field == "asked" else "outside — I decided"

    with pytest.raises(DispatchError) as raised:
        project.call("update_requirement", {"id": "R9", field: value})
    assert raised.value.reason == "invalid_requirement"

    entry = project.cad.ledger_state().by_id["R9"]
    assert (entry.asked, entry.resolution) == (False, None), "nothing was written"
    assert _build(project)["status"] == "clarification_required", "the gate is still shut"


def test_a_clarification_without_consequences_is_never_asked() -> None:
    refusal = question_refusal(
        {"requirement_ids": ["R9"], "question": "which side?", "options": ["inside", "outside"]}
    )
    assert refusal is not None
    assert refusal["code"] == "clarification_question_shape"
