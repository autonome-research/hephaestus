"""The constraint set as generational project state (``ASSEMBLY.md`` §1).

The ledger pattern, and therefore the ledger's obligations: every act is a new
immutable generation naming its parent, provenance is compulsory, a withdrawal
records a reason and erases nothing, and every generation stays replayable
afterwards. These are the clauses that make a constraint set *evidence* rather
than a mutable settings blob, so they are asserted directly rather than through
the evaluator.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from _assembly_project import assumed, fit_entry, make_assembly_project
from hephaestus.core.errors import AddressingError
from hephaestus.core.project_store.constraints import (
    CONSTRAINTS_POINTER,
    ConstraintError,
    ConstraintSet,
    parse_anchor,
)
from hephaestus.core.project_store.layout import ProjectLayout, open_store
from hephaestus.core.project_store.retention import protected_pointer_names

from opstore import OpStore


@pytest.fixture
def layout(tmp_path: Path) -> ProjectLayout:
    return make_assembly_project(tmp_path / "proj")


@pytest.fixture
def store(layout: ProjectLayout) -> Iterator[OpStore]:
    opened = open_store(layout)
    yield opened
    opened.close()


@pytest.fixture
def constraints(layout: ProjectLayout, store: OpStore) -> ConstraintSet:
    return ConstraintSet(layout, store)


class TestGenerations:
    def test_declare_update_withdraw_are_three_generations(
        self, constraints: ConstraintSet
    ) -> None:
        declared = constraints.declare(fit_entry())
        assert declared.generation == 1
        assert declared.artifact_ref is not None

        updated = constraints.update("c-pin-fit", {"max_mm": 0.25}, "vendor widened the tolerance")
        assert updated.generation == 2
        assert updated.parent == declared.blob
        assert updated.by_id["c-pin-fit"].values["max_mm"] == 0.25

        withdrawn = constraints.withdraw("c-pin-fit", "the register moved to a boss")
        assert withdrawn.generation == 3
        entry = withdrawn.by_id["c-pin-fit"]
        assert entry.withdrawn is True
        assert entry.withdrawn_reason == "the register moved to a boss"
        # Withdrawal is not erasure: the entry is still stored, just not claimed.
        assert withdrawn.entries and withdrawn.active == ()

    def test_every_generation_stays_replayable(self, constraints: ConstraintSet) -> None:
        first = constraints.declare(fit_entry())
        constraints.update("c-pin-fit", {"min_mm": 0.02}, "loosened after the fit test")
        constraints.withdraw("c-pin-fit", "superseded by c-pin-fit-2")

        assert first.artifact_ref is not None
        replayed = constraints.generation(first.artifact_ref)
        assert replayed.by_id["c-pin-fit"].values["min_mm"] == 0.05
        assert replayed.by_id["c-pin-fit"].withdrawn is False

        history = constraints.history()
        assert [state.generation for state in history] == [1, 2, 3]
        assert [None if s.change is None else s.change.kind for s in history] == [
            "declare",
            "update",
            "withdraw",
        ]
        assert history[1].change is not None
        assert history[1].change.reason == "loosened after the fit test"

    def test_the_live_generation_is_a_protected_gc_root(self, layout: ProjectLayout) -> None:
        assert CONSTRAINTS_POINTER in protected_pointer_names(layout)

    def test_older_generations_survive_gc(self, constraints: ConstraintSet, store: OpStore) -> None:
        first = constraints.declare(fit_entry())
        constraints.update("c-pin-fit", {"max_mm": 0.3}, "widened")
        store.gc.collect()
        assert first.artifact_ref is not None
        assert constraints.generation(first.artifact_ref).by_id["c-pin-fit"].values["max_mm"] == 0.2

    def test_pointer_moves_only_on_success(
        self, constraints: ConstraintSet, store: OpStore
    ) -> None:
        constraints.declare(fit_entry())
        before = store.blobs.read_pointer(CONSTRAINTS_POINTER)
        with pytest.raises(ConstraintError):
            constraints.declare(fit_entry())  # duplicate id
        assert store.blobs.read_pointer(CONSTRAINTS_POINTER) == before
        assert constraints.state().generation == 1

    def test_committed_op_id_replays_rather_than_advancing(
        self, constraints: ConstraintSet
    ) -> None:
        first = constraints.declare(fit_entry(), op_id="tool-call-1")
        again = constraints.declare(fit_entry(), op_id="tool-call-1")
        assert again.generation == first.generation
        assert again.blob == first.blob
        assert constraints.state().generation == 1


class TestProvenanceCompulsion:
    def test_an_entry_with_no_provenance_is_refused(self, constraints: ConstraintSet) -> None:
        entry = fit_entry()
        entry.pop("provenance")
        with pytest.raises(ConstraintError) as err:
            constraints.declare(entry)
        assert err.value.reason == "invalid_constraint"
        assert constraints.state().generation == 0

    def test_an_empty_provenance_object_is_refused(self, constraints: ConstraintSet) -> None:
        with pytest.raises(ConstraintError) as err:
            constraints.declare(fit_entry(provenance={}))
        assert "assumed" in err.value.message

    def test_an_assumption_without_a_reason_is_refused(self, constraints: ConstraintSet) -> None:
        with pytest.raises(ConstraintError) as err:
            constraints.declare(fit_entry(provenance={"assumed": True}))
        assert err.value.reason == "invalid_constraint"

    def test_a_cited_requirement_or_a_reasoned_assumption_both_pass(
        self, constraints: ConstraintSet
    ) -> None:
        constraints.declare(fit_entry())
        constraints.declare(fit_entry(id="c-two", provenance=assumed()))
        state = constraints.state()
        assert state.by_id["c-pin-fit"].provenance.requirement == "r-1"
        assert state.by_id["c-two"].provenance.assumed is True
        assert state.by_id["c-two"].provenance.reason

    def test_both_at_once_is_refused(self, constraints: ConstraintSet) -> None:
        with pytest.raises(ConstraintError):
            constraints.declare(
                fit_entry(provenance={"requirement": "r-1", "assumed": True, "reason": "x"})
            )


class TestEntrySchema:
    def test_unknown_kind_is_refused_naming_the_vocabulary(
        self, constraints: ConstraintSet
    ) -> None:
        with pytest.raises(ConstraintError) as err:
            constraints.declare(fit_entry(kind="welded"))
        assert "clearance_min" in err.value.message

    def test_a_missing_declared_parameter_is_refused_by_name(
        self, constraints: ConstraintSet
    ) -> None:
        entry = fit_entry()
        entry.pop("max_mm")
        with pytest.raises(ConstraintError) as err:
            constraints.declare(entry)
        assert "max_mm" in err.value.message

    def test_a_parameter_the_kind_does_not_take_is_refused_by_name(
        self, constraints: ConstraintSet
    ) -> None:
        with pytest.raises(ConstraintError) as err:
            constraints.declare(fit_entry(tol_deg=0.5))
        assert "tol_deg" in err.value.message

    def test_optional_parameters_are_accepted(self, constraints: ConstraintSet) -> None:
        constraints.declare(
            {
                "id": "c-gap",
                "kind": "clearance_min",
                "a": "base",
                "b": "pin",
                "value_mm": 0.2,
                "tol_mm": 0.01,
                "provenance": assumed(),
            }
        )
        assert constraints.state().by_id["c-gap"].values == {"value_mm": 0.2, "tol_mm": 0.01}

    def test_anchor_grammar(self) -> None:
        assert parse_anchor("base").selector == "part"
        assert parse_anchor("base:bore_face").part == "base"
        assert parse_anchor("base:bore_face").selector == "bore_face"
        with pytest.raises(ConstraintError):
            parse_anchor("base/bore_face")
        with pytest.raises(ConstraintError):
            parse_anchor("")

    def test_a_patch_that_would_not_have_validated_is_refused(
        self, constraints: ConstraintSet
    ) -> None:
        constraints.declare(fit_entry())
        with pytest.raises(ConstraintError):
            constraints.update("c-pin-fit", {"a": "base/bore_face"}, "typo")
        assert constraints.state().generation == 1

    def test_changing_kind_drops_the_old_kinds_numbers(self, constraints: ConstraintSet) -> None:
        constraints.declare(fit_entry())
        state = constraints.update(
            "c-pin-fit",
            {"kind": "clearance_min", "value_mm": 0.15},
            "a fit window was the wrong question; the seat only needs a gap",
        )
        entry = state.by_id["c-pin-fit"]
        assert entry.kind == "clearance_min"
        assert entry.values == {"value_mm": 0.15}


class TestReasonsAndUnknownIds:
    def test_update_requires_a_reason(self, constraints: ConstraintSet) -> None:
        constraints.declare(fit_entry())
        with pytest.raises(ConstraintError):
            constraints.update("c-pin-fit", {"max_mm": 0.4}, "   ")

    def test_withdraw_requires_a_reason(self, constraints: ConstraintSet) -> None:
        constraints.declare(fit_entry())
        with pytest.raises(ConstraintError):
            constraints.withdraw("c-pin-fit", "")

    def test_patching_an_unknown_id_is_its_own_refusal(self, constraints: ConstraintSet) -> None:
        with pytest.raises(ConstraintError) as err:
            constraints.update("c-nope", {"max_mm": 0.4}, "reason")
        assert err.value.reason == "unknown_constraint"

    def test_reading_an_unknown_id_lists_the_declared_ones(
        self, constraints: ConstraintSet
    ) -> None:
        constraints.declare(fit_entry())
        with pytest.raises(AddressingError) as err:
            constraints.get("c-nope")
        assert err.value.candidates == ("c-pin-fit",)

    def test_a_withdrawn_constraint_cannot_be_withdrawn_twice(
        self, constraints: ConstraintSet
    ) -> None:
        constraints.declare(fit_entry())
        constraints.withdraw("c-pin-fit", "obsolete")
        with pytest.raises(ConstraintError):
            constraints.withdraw("c-pin-fit", "obsolete again")


class TestProjection:
    def test_entry_round_trips_through_its_stored_json(self, constraints: ConstraintSet) -> None:
        constraints.declare(fit_entry())
        stored = constraints.state().by_id["c-pin-fit"].to_json()
        assert stored["a"] == "base:bore_face"
        assert stored["min_mm"] == 0.05
        assert stored["provenance"] == {"requirement": "r-1"}
        assert stored["note"] == "slip fit per datasheet"

    def test_parts_names_every_anchored_part_once(self, constraints: ConstraintSet) -> None:
        constraints.declare(fit_entry())
        constraints.declare(
            {
                "id": "c-self",
                "kind": "no_interference",
                "a": "base",
                "b": "base:bore_face",
                "provenance": assumed(),
            }
        )
        assert constraints.state().parts == ("base", "pin")
