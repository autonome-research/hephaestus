"""The VALIDATION.md §2 requirement ledger, through the real dispatcher.

The ledger is the substrate the rest of the validation ladder stands on, so what
is tested here is what those rungs are allowed to assume: immutable generations
(an old generation stays readable after later writes), an idempotent replay that
returns *its own* generation rather than the current one, structural refusal of
an entry that does not meet its source's obligations (with nothing written), and
the ``unresolved_material`` set the §3 clarification gate blocks on.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from hephaestus.agent_bridge.cad_ops import ledger_state, record_clarification_answer
from hephaestus.agent_bridge.dispatch import DispatchError
from hephaestus.testing.tools_fixture import (
    ORCH,
    PART_WIDGET,
    QUICK_WIDGET,
    Project,
    make_project,
)
from opstore.errors import KeyPayloadMismatchError

#: §7's bench answerer, verbatim: an answer that declines to decide.
BENCH_NON_COMMITTAL: str = (
    "unspecified — use your engineering judgment and record it as an assumption."
)

R1: dict[str, Any] = {
    "id": "R1",
    "text": "base plate 60 mm in X",
    "source": "specified",
    "quote": "60 mm (X) by 40 mm (Y) base plate",
    "value": 60.0,
    "unit": "mm",
    "applies_to": "bracket",
}
R2: dict[str, Any] = {
    "id": "R2",
    "text": "overall height 40 mm",
    "source": "specified",
    "quote": "overall height is 40 mm",
    "value": 40.0,
    "unit": "mm",
    "applies_to": "bracket",
}
#: The seed-2 case: nothing in the request says which side the wall stands on.
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
    # seed_ledger=False: this module's subject IS the ledger/gate, so it must see
    # the project's real initial state — no ledger at all (VALIDATION.md §2).
    p = make_project(tmp_path / "proj", seed_ledger=False)
    try:
        yield p
    finally:
        p.close()


def _ids(result: Any) -> list[str]:
    return [str(entry["id"]) for entry in cast("list[Any]", result["entries"])]


def _entry(result: Any, entry_id: str) -> dict[str, Any]:
    for entry in cast("list[Any]", result["entries"]):
        if entry["id"] == entry_id:
            return cast("dict[str, Any]", entry)
    raise AssertionError(f"no entry {entry_id} in {result}")


# ==========================================================================
# recording, reading, generations


def test_record_then_read_reports_one_generation(project: Project) -> None:
    result = project.call("record_requirements", {"entries": [R1, R2]})
    assert result["status"] == "ok"
    assert result["generation"] == 1
    assert result["artifact_ref"].startswith("artifact:requirements:sha256:")
    assert _ids(result) == ["R1", "R2"]
    assert result["unresolved_material"] == []
    assert _entry(result, "R1")["quote"] == R1["quote"]

    read = project.call("read_requirements", {})
    assert read == result

    # An empty project reports the empty generation rather than failing.
    assert project.cad.ledger_state().generation == 1


def test_the_empty_ledger_is_generation_zero(project: Project) -> None:
    read = project.call("read_requirements", {})
    assert read == {
        "status": "ok",
        "generation": 0,
        "artifact_ref": None,
        "entries": [],
        "unresolved_material": [],
    }


def test_recording_upserts_by_id_and_preserves_order(project: Project) -> None:
    project.call("record_requirements", {"entries": [R1, R2]})
    third = {**R1, "id": "R3", "text": "plate 6 mm thick", "quote": "6 mm thick", "value": 6.0}
    revised = {**R1, "text": "base plate 62 mm in X", "value": 62.0}
    result = project.call("record_requirements", {"entries": [revised, third]})

    assert result["generation"] == 2
    assert _ids(result) == ["R1", "R2", "R3"], "an upsert replaces in place, it does not reorder"
    assert _entry(result, "R1")["value"] == 62.0


def test_generations_are_immutable_and_stay_readable(project: Project) -> None:
    first = project.call("record_requirements", {"entries": [R1]})
    second = project.call("record_requirements", {"entries": [R2]})
    assert second["artifact_ref"] != first["artifact_ref"]

    old = project.cad.ledger_generation(str(first["artifact_ref"]))
    assert old.generation == 1
    assert [entry.id for entry in old.entries] == ["R1"]
    # The current generation names its parent, so the chain is walkable.
    assert project.cad.ledger_state().parent == old.blob

    # …and the frozen document is a model-readable artifact.
    page = project.call("read_artifact", {"ref": first["artifact_ref"], "max_bytes": 8192})
    document = cast("dict[str, Any]", json.loads(str(page["content"])))
    assert document["generation"] == 1
    assert [entry["id"] for entry in cast("list[Any]", document["entries"])] == ["R1"]


def test_update_requirement_patches_only_the_supplied_fields(project: Project) -> None:
    project.call("record_requirements", {"entries": [R1, R2]})
    result = project.call("update_requirement", {"id": "R2", "value": 46.0, "unit": "mm"})

    assert result["generation"] == 2
    entry = _entry(result, "R2")
    assert entry["value"] == 46.0
    assert entry["text"] == R2["text"], "an unsupplied field is untouched"
    assert entry["quote"] == R2["quote"]
    assert _ids(result) == ["R1", "R2"]


def test_update_of_an_unknown_id_is_refused(project: Project) -> None:
    project.call("record_requirements", {"entries": [R1]})
    with pytest.raises(DispatchError) as excinfo:
        project.call("update_requirement", {"id": "R7", "value": 1.0})
    assert excinfo.value.reason == "unknown_requirement"
    assert project.cad.ledger_state().generation == 1


# ==========================================================================
# the CAS / idempotency contract


def test_a_replayed_invocation_returns_its_own_generation(project: Project) -> None:
    first = project.call("record_requirements", {"entries": [R1]}, entry="e-rec")
    project.call("record_requirements", {"entries": [R2]})  # the ledger moves on

    replay = project.call("record_requirements", {"entries": [R1]}, entry="e-rec")
    assert replay["generation"] == 1, "a replay reports the generation it created"
    assert replay["artifact_ref"] == first["artifact_ref"]
    assert _ids(replay) == ["R1"]
    # Nothing was re-done: the live ledger is still the second generation.
    assert project.cad.ledger_state().generation == 2


def test_same_invocation_different_payload_is_a_hard_mismatch(project: Project) -> None:
    project.call("record_requirements", {"entries": [R1]}, entry="e-rec")
    with pytest.raises(KeyPayloadMismatchError):
        project.call("record_requirements", {"entries": [R2]}, entry="e-rec")
    assert project.cad.ledger_state().generation == 1


def test_a_replayed_update_does_not_advance_the_generation(project: Project) -> None:
    project.call("record_requirements", {"entries": [R1]})
    first = project.call("update_requirement", {"id": "R1", "value": 61.0}, entry="e-upd")
    replay = project.call("update_requirement", {"id": "R1", "value": 61.0}, entry="e-upd")
    assert replay == first
    assert project.cad.ledger_state().generation == 2


# ==========================================================================
# structural validation (nothing lands on refusal)


@pytest.mark.parametrize(
    ("entry", "reason"),
    [
        ({"id": "R1", "text": "t", "source": "specified"}, "invalid_requirement"),
        ({"id": "R1", "text": "t", "source": "derived"}, "invalid_requirement"),
        ({"id": "R1", "text": "t", "source": "derived", "from": ["R9"]}, "invalid_requirement"),
        ({"id": "R1", "text": "t", "source": "assumed"}, "invalid_requirement"),
        (
            {"id": "R1", "text": "t", "source": "assumed", "rationale": "because"},
            "invalid_requirement",
        ),
        ({"id": "R1", "text": "", "source": "specified", "quote": "q"}, "invalid_requirement"),
        ({"id": "1R", "text": "t", "source": "specified", "quote": "q"}, "invalid_requirement"),
        ({"id": "R1", "text": "t", "source": "guessed"}, "invalid_requirement"),
    ],
)
def test_an_entry_failing_its_source_obligations_writes_nothing(
    project: Project, entry: dict[str, Any], reason: str
) -> None:
    with pytest.raises(DispatchError) as excinfo:
        project.call("record_requirements", {"entries": [entry]})
    assert excinfo.value.reason == reason
    assert project.cad.ledger_state().generation == 0
    assert project.cad.ledger_state().entries == ()


def test_a_batch_is_all_or_nothing(project: Project) -> None:
    bad = {"id": "R5", "text": "t", "source": "assumed", "rationale": "r"}  # no material flag
    with pytest.raises(DispatchError):
        project.call("record_requirements", {"entries": [R1, bad]})
    assert project.cad.ledger_state().generation == 0

    # A corrected batch under a new invocation lands whole.
    result = project.call("record_requirements", {"entries": [R1, {**bad, "material": False}]})
    assert _ids(result) == ["R1", "R5"]


def test_a_duplicate_id_in_one_batch_is_refused(project: Project) -> None:
    with pytest.raises(DispatchError) as excinfo:
        project.call("record_requirements", {"entries": [R1, {**R1, "text": "again"}]})
    assert excinfo.value.reason == "invalid_requirement"


def test_derived_entries_must_resolve_against_the_whole_ledger(project: Project) -> None:
    project.call("record_requirements", {"entries": [R1]})
    derived = {"id": "R4", "text": "wall length matches plate", "source": "derived", "from": ["R1"]}
    result = project.call("record_requirements", {"entries": [derived]})
    assert _entry(result, "R4")["from"] == ["R1"]

    with pytest.raises(DispatchError):
        project.call(
            "record_requirements",
            {"entries": [{**derived, "id": "R6", "from": ["R404"]}]},
        )


def test_an_empty_batch_is_refused(project: Project) -> None:
    with pytest.raises(DispatchError):
        project.call("record_requirements", {"entries": []})


# ==========================================================================
# the unresolved-material set (what §3 blocks on)


def test_material_assumptions_are_reported_until_resolved(project: Project) -> None:
    result = project.call("record_requirements", {"entries": [R1, WALL_DIR]})
    assert result["unresolved_material"] == ["R9"]
    assert ledger_state(project.cad).unresolved_material == ("R9",)

    # Asking is not resolving: a non-committal answer keeps the entry open (§7).
    # Both fields are the runtime's to write — the model cannot patch either, so
    # the writes below go through the clarification recorder (see
    # test_clarification_gate.py for the refusal itself).
    record_clarification_answer(project.cad, "R9", BENCH_NON_COMMITTAL, op_id="op-asked")
    asked = project.call("read_requirements", {})
    assert asked["unresolved_material"] == ["R9"]
    assert _entry(asked, "R9")["asked"] is True

    record_clarification_answer(project.cad, "R9", "outside: 46 mm overall", op_id="op-resolved")
    resolved = project.call("read_requirements", {})
    assert resolved["unresolved_material"] == []
    assert _entry(resolved, "R9")["resolution"] == "outside: 46 mm overall"


def test_an_immaterial_assumption_never_blocks(project: Project) -> None:
    immaterial = {**WALL_DIR, "id": "R8", "material": False}
    result = project.call("record_requirements", {"entries": [immaterial]})
    assert result["unresolved_material"] == []


def test_ledger_state_reader_exposes_entries_and_the_open_set(project: Project) -> None:
    project.call("record_requirements", {"entries": [R1, WALL_DIR]})
    state = ledger_state(project.cad)
    assert state.generation == 1
    assert [entry.id for entry in state.entries] == ["R1", "R9"]
    assert state.by_id["R9"].unresolved_material is True
    assert state.by_id["R1"].unresolved_material is False
    assert state.artifact_ref is not None


# ==========================================================================
# authorization


def test_a_part_session_may_use_the_ledger_and_quick_edit_may_not(project: Project) -> None:
    project.call("record_requirements", {"entries": [R1]}, principal=PART_WIDGET)
    assert _ids(project.call("read_requirements", {}, principal=PART_WIDGET)) == ["R1"]

    for tool, arguments in (
        ("record_requirements", {"entries": [R2]}),
        ("read_requirements", {}),
        ("update_requirement", {"id": "R1", "value": 1.0}),
    ):
        with pytest.raises(DispatchError) as excinfo:
            project.call(tool, arguments, principal=QUICK_WIDGET)
        assert excinfo.value.reason == "scope_denied"

    assert project.call("read_requirements", {}, principal=ORCH)["generation"] == 1
