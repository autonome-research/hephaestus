"""G8C: what a model may declare, on whose behalf, and what it may never erase.

Three gate clauses, all at the tool surface:

* *the model tool quartet through dispatch on both profiles* — ``part`` and
  ``orchestrator``. A constraint spans parts by nature, so a part session may
  declare a mate that names another part; scoping it to one would gut the
  feature (``ASSEMBLY.md`` §3);
* *provenance compulsion (an entry citing no requirement and not ``assumed`` is
  refused ``invalid_constraint``)* — with **nothing written**, which is the half
  that matters: a refusal that still advanced a generation would leave the
  project carrying a claim it rejected;
* *generational state (declare → update → withdraw, every generation replayable,
  nothing erased)* — asserted by replaying each generation from the immutable
  artifact ref the tool handed back at the time, not by trusting the live
  pointer.

Reading is here too, because "reading never measures" is what makes the ledger
pattern honest for constraints: ``read_constraints`` reports the LAST evaluation
and ``assembly: null`` for *never evaluated*, which is not a pass.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

import pytest
from _g8c import ORCH, PART_BASE, assumed, check, declare, outcome
from hephaestus.agent_bridge.dispatch import DispatchError, Principal
from hephaestus.contract import tools_decl
from hephaestus.testing.tools_fixture import Project

QUARTET: tuple[str, ...] = (
    "declare_constraint",
    "update_constraint",
    "read_constraints",
    "check_assembly",
)

FIT: dict[str, Any] = {
    "id": "c-register-fit",
    "kind": "fit",
    "a": "base:register_slot",
    "b": "lid:register_wall",
    "min_mm": 0.05,
    "max_mm": 0.25,
}


def entry(overrides: Mapping[str, Any]) -> dict[str, Any]:
    """The §1 worked-example entry with fields replaced (or removed via ``None``)."""
    out = dict(FIT)
    out["provenance"] = {"requirement": "R1"}
    for key, value in overrides.items():
        if value is None:
            out.pop(key, None)
        else:
            out[key] = value
    return out


def entries_of(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [cast("dict[str, Any]", item) for item in cast("Sequence[Any]", result["entries"])]


# ==========================================================================
# the quartet, on both profiles


def test_the_quartet_is_reachable_on_both_declared_profiles(pair: Project) -> None:
    """All four tools, driven by an orchestrator and by a part session.

    The part principal is ``base``; the mate it declares names ``lid``. That is
    the point of the clause: a cross-part constraint cannot be authored by
    anyone who is only allowed to talk about one part.
    """
    for name in QUARTET:
        assert tools_decl.get_tool(name).profiles == ("part", "orchestrator"), name

    declared = declare(
        pair,
        "c-part-session",
        "coincident",
        "base:rim_top",
        "lid:seat_face",
        principal=PART_BASE,
        tol_mm=0.01,
    )
    assert declared["generation"] == 1
    revised = cast(
        "dict[str, Any]",
        pair.call(
            "update_constraint",
            {"id": "c-part-session", "patch": {"tol_mm": 0.05}, "reason": "seat gasket allowance"},
            principal=PART_BASE,
        ),
    )
    assert revised["generation"] == 2
    # …and the orchestrator sees exactly what the part session wrote.
    read = cast("dict[str, Any]", pair.call("read_constraints", {}, principal=ORCH))
    assert entries_of(read)[0]["tol_mm"] == 0.05
    status = check(pair, principal=PART_BASE)
    assert outcome(status, "c-part-session")["state"] == "satisfied"


@pytest.mark.parametrize("tool", QUARTET)
def test_a_reviewer_may_not_write_the_constraints_it_judges(pair: Project, tool: str) -> None:
    """The §5 reviewer reads the assembly status; it does not get to author it."""
    reviewer = Principal(session_id="rv", profile="reviewer", part=None)
    with pytest.raises(DispatchError) as excinfo:
        pair.call(tool, {}, principal=reviewer)
    assert excinfo.value.reason == "scope_denied"


# ==========================================================================
# provenance is compelled (VALIDATION.md §2's taxonomy, applied to a mate)


@pytest.mark.parametrize(
    ("case", "overrides"),
    [
        ("no provenance at all", {"provenance": None}),
        ("an empty provenance object", {"provenance": {}}),
        ("assumed with no reason", {"provenance": {"assumed": True}}),
        ("cited and assumed at once", {"provenance": {"requirement": "R1", "assumed": True}}),
    ],
)
def test_an_entry_that_says_nothing_about_intent_is_refused(
    pair: Project, case: str, overrides: Mapping[str, Any]
) -> None:
    """A constraint IS an interpretation of intent, so it says whose — or is refused."""
    with pytest.raises(DispatchError) as excinfo:
        pair.call("declare_constraint", entry(overrides))
    assert excinfo.value.reason == "invalid_constraint", case
    # Nothing written: the set is still at generation 0 with no entries.
    read = cast("dict[str, Any]", pair.call("read_constraints", {}))
    assert (read["generation"], entries_of(read)) == (0, []), case


@pytest.mark.parametrize(
    ("case", "provenance"),
    [
        ("a cited requirement", {"requirement": "R1"}),
        ("a reasoned assumption", {"assumed": True, "reason": "no requirement covers the seat"}),
    ],
)
def test_both_honest_provenances_are_accepted_and_kept(
    pair: Project, case: str, provenance: Mapping[str, Any]
) -> None:
    declaration = entry({"provenance": provenance})
    result = cast("dict[str, Any]", pair.call("declare_constraint", declaration))
    assert entries_of(result)[0]["provenance"] == dict(provenance), case
    # …and it survives into the evaluation, where a reviewer will read it.
    row = outcome(check(pair), "c-register-fit")
    assert row["provenance"] == dict(provenance)


def test_a_missing_declared_number_is_refused_by_name(pair: Project) -> None:
    """Which numbers a kind takes is the evaluator's own table, not a second schema."""
    with pytest.raises(DispatchError) as excinfo:
        pair.call("declare_constraint", entry({"min_mm": None}))
    assert excinfo.value.reason == "invalid_constraint"
    assert "min_mm" in excinfo.value.message

    with pytest.raises(DispatchError) as excinfo:
        pair.call("declare_constraint", entry({"tol_deg": 0.5}))
    assert excinfo.value.reason == "invalid_constraint"
    assert "tol_deg" in excinfo.value.message


def test_an_omitted_optional_tolerance_is_absent_not_zero(pair: Project) -> None:
    """``null`` on the wire means "not supplied", and the default is the named one."""
    from hephaestus.geom.constraints import INTERFERENCE_TOL_MM3

    pair.call(
        "declare_constraint",
        {
            "id": "c-clear",
            "kind": "no_interference",
            "a": "base",
            "b": "lid",
            "tol_mm3": None,
            "note": None,
            "provenance": assumed(),
        },
    )
    residual = cast("Mapping[str, Any]", outcome(check(pair), "c-clear")["residual"])
    declared = {
        str(cast("Sequence[Any]", pair_)[0]): cast("Sequence[Any]", pair_)[1]
        for pair_ in cast("Sequence[Any]", residual["declared"])
    }
    assert declared == {"tol_mm3": INTERFERENCE_TOL_MM3}


# ==========================================================================
# generations: three acts, three generations, nothing erased


def test_declare_update_withdraw_replay_from_their_own_refs(pair: Project) -> None:
    """Every generation is readable afterwards from the ref handed out at the time."""
    declared = cast("dict[str, Any]", pair.call("declare_constraint", entry({})))
    revised = cast(
        "dict[str, Any]",
        pair.call(
            "update_constraint",
            {
                "id": "c-register-fit",
                "patch": {"max_mm": 0.35},
                "reason": "vendor widened the bore",
            },
        ),
    )
    withdrawn = cast(
        "dict[str, Any]",
        pair.call(
            "update_constraint",
            {
                "id": "c-register-fit",
                "patch": {"withdrawn": True},
                "reason": "the register was replaced by a snap fit",
            },
        ),
    )
    assert [declared["generation"], revised["generation"], withdrawn["generation"]] == [1, 2, 3]

    # Each act recorded WHAT it was and WHY (a silent revision is the thing §3
    # forbids), and each generation has its own immutable artifact ref.
    assert cast("Mapping[str, Any]", declared["change"])["kind"] == "declare"
    assert cast("Mapping[str, Any]", revised["change"])["reason"] == "vendor widened the bore"
    assert cast("Mapping[str, Any]", withdrawn["change"])["kind"] == "withdraw"
    refs = [str(result["artifact_ref"]) for result in (declared, revised, withdrawn)]
    assert len(set(refs)) == 3
    assert all(ref.startswith("artifact:constraints:sha256:") for ref in refs)

    # Replay: the generation each ref names still says what it said then.
    constraints = pair.cad.constraint_set()
    replayed = [constraints.generation(ref) for ref in refs]
    assert [state.generation for state in replayed] == [1, 2, 3]
    assert replayed[0].entries[0].values["max_mm"] == pytest.approx(0.25)
    assert replayed[1].entries[0].values["max_mm"] == pytest.approx(0.35)
    assert replayed[0].entries[0].withdrawn is False
    # Withdrawn, never erased: the entry and the reason stay in the record.
    assert replayed[2].entries[0].withdrawn is True
    assert replayed[2].entries[0].withdrawn_reason == "the register was replaced by a snap fit"
    # …and the parent chain walks back to the first generation unbroken.
    assert [state.generation for state in constraints.history()] == [1, 2, 3]


def test_a_withdrawn_constraint_stops_being_evaluated_without_vanishing(pair: Project) -> None:
    declare(
        pair,
        "c-register-fit",
        "fit",
        "base:register_slot",
        "lid:register_wall",
        min_mm=0.30,
        max_mm=0.40,
    )
    assert list(cast("list[Any]", check(pair)["blocking"])) == ["c-register-fit"]

    pair.call(
        "update_constraint",
        {"id": "c-register-fit", "patch": {"withdrawn": True}, "reason": "not a real interface"},
    )

    status = check(pair)
    assert cast("Sequence[Any]", status["constraints"]) == []
    assert list(cast("list[Any]", status["blocking"])) == []
    # The project stopped CLAIMING it; it did not stop having said it.
    read = cast("dict[str, Any]", pair.call("read_constraints", {}))
    assert entries_of(read)[0]["withdrawn"] is True


def test_reading_never_measures_and_a_partial_check_is_not_projected(pair: Project) -> None:
    declare(pair, "c-seat", "coincident", "base:rim_top", "lid:seat_face", tol_mm=0.01)

    # Never evaluated is null — which is not "the constraints hold".
    assert cast("dict[str, Any]", pair.call("read_constraints", {}))["assembly"] is None

    partial = cast("dict[str, Any]", pair.call("check_assembly", {"ids": ["c-seat"]}))
    assert partial["partial"] is True and partial["artifact_ref"] is None
    assert cast("dict[str, Any]", pair.call("read_constraints", {}))["assembly"] is None, (
        "a partial evaluation must not become the project's assembly status"
    )

    full = cast("dict[str, Any]", pair.call("check_assembly", {}))
    assert full["partial"] is False
    assert str(full["artifact_ref"]).startswith("artifact:assembly-status:sha256:")
    read = cast("dict[str, Any]", pair.call("read_constraints", {}))
    assert cast("Mapping[str, Any]", read["assembly"])["counts"]["satisfied"] == 1
    assert read["assembly_ref"] == full["artifact_ref"]


def test_an_unknown_id_is_its_own_refusal_token(pair: Project) -> None:
    """Patching or checking something that was never declared names the ids that were."""
    declare(pair, "c-seat", "coincident", "base:rim_top", "lid:seat_face", tol_mm=0.01)

    with pytest.raises(DispatchError) as patching:
        pair.call("update_constraint", {"id": "c-ghost", "patch": {"tol_mm": 1.0}, "reason": "x"})
    assert patching.value.reason == "unknown_constraint"

    with pytest.raises(DispatchError) as checking:
        pair.call("check_assembly", {"ids": ["c-ghost"]})
    assert checking.value.reason == "unknown_constraint"
    assert "c-seat" in checking.value.message
