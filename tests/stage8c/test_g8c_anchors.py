"""G8C: what an anchor names, and what it means when it names nothing.

Gate clause: *anchor resolution through tag / label / binding forms and the
``unresolvable`` taxonomy (missing part, no current build, dangling tag — each
named, none conflated)*.

Both halves are asserted against **published** artifacts, because that is where
the difficulty is: a reloaded BRep carries topology and nothing else, so every
selector here has to be resolved through the namespace publication recorded
beside it (``ASSEMBLY.md`` §2). A tag that resolves resolves to a real face of a
real reloaded solid, and a tag that does not resolve says which of the eight
things went wrong.

``unresolvable`` is the clause with teeth. Every reason below is a different
fix — build the part, rename the tag, anchor something with a cylinder — and
none of them is ``violated``: reporting "not checked" as "the geometry is wrong"
would send a run off to change geometry that was never measured, and reporting
it as ``satisfied`` would be worse.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

import pytest
from _g8c import (
    LID_UNTAGGED_SRC,
    NOMINAL_CLEARANCE_MM,
    build_all,
    check,
    declare,
    outcome,
    rewrite,
    states,
)
from hephaestus.agent_bridge.dispatch import DispatchError
from hephaestus.core.assembly import UNRESOLVABLE_REASONS
from hephaestus.testing.tools_fixture import Project


def anchors(row: Mapping[str, Any]) -> tuple[str, str]:
    """``(a rule, b rule)`` — which §7 rule matched on each side."""
    return (
        str(cast("Mapping[str, Any]", row["a"])["rule"]),
        str(cast("Mapping[str, Any]", row["b"])["rule"]),
    )


# ==========================================================================
# the forms that resolve


def test_every_anchor_form_resolves_against_the_published_artifact(built: Project) -> None:
    """Whole part, tag, explicit label, and a label filled in from a binding.

    The four are declared against ONE pair of parts so the rules can be compared
    directly, and each row reports the rule that matched — the anchor is not
    merely accepted, it is accounted for.
    """
    declare(built, "c-part", "no_interference", "base", "bracket")
    declare(
        built,
        "c-tag",
        "fit",
        "base:register_slot",
        "lid:register_wall",
        min_mm=0.05,
        max_mm=0.25,
    )
    declare(built, "c-label", "no_interference", "base:base_body", "bracket")
    # `lid_body` is never labelled in the script: §5.1 label-fill gives a
    # geometry-bearing binding its binding name, so the binding form of an
    # anchor is resolved — honestly, as a LABEL, which is what it became.
    declare(built, "c-binding", "no_interference", "base:base_body", "lid:lid_body")

    status = check(built)

    assert anchors(outcome(status, "c-part")) == ("part", "part")
    assert anchors(outcome(status, "c-tag")) == ("tag", "tag")
    assert anchors(outcome(status, "c-label")) == ("label", "part")
    assert anchors(outcome(status, "c-binding")) == ("label", "label")
    assert set(states(status).values()) == {"satisfied"}
    # Each side records the artifact the geometry was read from, so a residual
    # can be traced to the exact bytes it was measured on.
    for constraint_id in ("c-part", "c-tag", "c-label", "c-binding"):
        row = outcome(status, constraint_id)
        for side in ("a", "b"):
            ref = cast("Mapping[str, Any]", row[side])["artifact_ref"]
            assert str(ref).startswith("artifact:build:sha256:"), (constraint_id, side)


def test_a_tag_anchor_names_one_face_where_the_part_form_names_none(built: Project) -> None:
    """Same two parts, same kind, two anchor forms — and only one is answerable.

    The tagged faces are flush to 1e-9 mm. The whole parts are not two planes at
    all: a plate has six, they are not coplanar, and §7 forbids guessing which
    one was meant, so the constraint comes back refused rather than measured
    against the largest face that happened to be enumerated first.
    """
    declare(built, "c-faces", "coincident", "base:rim_top", "lid:seat_face", tol_mm=0.01)
    declare(built, "c-solids", "coincident", "base", "lid", tol_mm=0.01)

    status = check(built)

    faces = outcome(status, "c-faces")
    assert faces["state"] == "satisfied"
    assert cast("Mapping[str, Any]", faces["residual"])["measured"] == pytest.approx(0.0, abs=1e-9)
    solids = outcome(status, "c-solids")
    assert solids["state"] == "unresolvable"
    assert solids["reason"] == "shape_refused"
    assert "ambiguous_plane" in str(solids["detail"])


def test_a_whole_part_anchor_measures_the_published_solid(built: Project) -> None:
    """Where a part DOES stand for one shape of the kind's class, it is measured.

    The base is a bore and the lid is a boss, each the only cylinder its part
    carries, so the whole-part fit is answerable — and answers with exactly the
    number the tagged faces give. Anchoring a part is a coarser statement, not a
    different measurement.
    """
    declare(
        built,
        "c-faces",
        "fit",
        "base:register_slot",
        "lid:register_wall",
        min_mm=0.05,
        max_mm=0.25,
    )
    declare(built, "c-solids", "fit", "base", "lid", min_mm=0.05, max_mm=0.25)

    status = check(built)

    faces = outcome(status, "c-faces")
    solids = outcome(status, "c-solids")
    assert (faces["state"], solids["state"]) == ("satisfied", "satisfied")
    assert anchors(solids) == ("part", "part")
    for row in (faces, solids):
        assert cast("Mapping[str, Any]", row["residual"])["measured"] == pytest.approx(
            NOMINAL_CLEARANCE_MM, abs=1e-9
        )


# ==========================================================================
# the taxonomy: six named reasons out of one status


def test_each_way_of_being_uncheckable_is_named_separately(built: Project) -> None:
    """One evaluation, six reasons, zero of them ``violated``."""
    declare(built, "c-missing-part", "no_interference", "base", "ghost")
    declare(built, "c-unbuilt", "no_interference", "base", "never_built")
    declare(built, "c-dangling", "no_interference", "base", "lid:no_such_tag")
    declare(built, "c-ambiguous", "no_interference", "base", "lid:seat_face#9")
    declare(built, "c-binding-only", "no_interference", "base", "lid:spare_rib")
    declare(built, "c-wrong-class", "concentric", "base:rim_top", "lid:seat_face", tol_mm=0.1)

    status = check(built)

    reasons = {
        constraint_id: outcome(status, constraint_id)["reason"] for constraint_id in states(status)
    }
    assert reasons == {
        # the anchor names a part this project does not have
        "c-missing-part": "missing_part",
        # the part exists and has never been built: build it
        "c-unbuilt": "no_current_build",
        # the tag the constraint was written against is not in the namespace
        "c-dangling": "dangling_selector",
        # the selector is in the grammar but names nothing that exists
        "c-ambiguous": "dangling_selector",
        # the binding contributed no geometry to the published artifact
        "c-binding-only": "unaddressable_anchor",
        # geometry WAS resolved; it is the wrong class for the kind
        "c-wrong-class": "shape_refused",
    }
    assert set(states(status).values()) == {"unresolvable"}
    # Not one of them carries a residual: nothing was measured, so there is no
    # number to report, and inventing one would be the dishonest part.
    for constraint_id in reasons:
        row = outcome(status, constraint_id)
        assert row["residual"] is None, constraint_id
        assert row["detail"], constraint_id
    # …and every reason emitted is one the engine's closed vocabulary names.
    assert set(reasons.values()) <= set(UNRESOLVABLE_REASONS)


def test_an_unchecked_constraint_blocks_exactly_like_a_violated_one(built: Project) -> None:
    """The two states are reported apart and counted together (``VALIDATION.md`` §5)."""
    declare(built, "c-unbuilt", "no_interference", "base", "never_built")
    declare(built, "c-violated", "clearance_min", "base", "bracket", value_mm=100.0)

    status = check(built)

    assert states(status) == {"c-unbuilt": "unresolvable", "c-violated": "violated"}
    assert cast("Mapping[str, Any]", status["counts"]) == {
        "satisfied": 0,
        "violated": 1,
        "unresolvable": 1,
    }
    assert list(cast("list[Any]", status["blocking"])) == ["c-unbuilt", "c-violated"]


def test_building_the_missing_part_turns_the_reason_into_a_measurement(
    assembly: Project,
) -> None:
    """``no_current_build`` names its own fix, and the fix works."""
    build_all(assembly, "base")
    declare(assembly, "c-seat", "coincident", "base:rim_top", "lid:seat_face", tol_mm=0.01)
    first = outcome(check(assembly), "c-seat")
    assert (first["state"], first["reason"]) == ("unresolvable", "no_current_build")

    build_all(assembly, "lid")

    second = outcome(check(assembly), "c-seat")
    assert second["state"] == "satisfied"
    assert cast("Mapping[str, Any]", second["residual"])["measured"] == pytest.approx(0.0, abs=1e-9)


def test_an_edit_that_drops_a_tag_dangles_rather_than_passing(built: Project) -> None:
    """The dangling-tag case as it really arises: someone edited the script.

    The constraint was satisfied against the previous build. After an edit that
    removes the tag it anchors, the honest answer is "that selector is gone",
    not the last number anyone measured.
    """
    declare(
        built,
        "c-fit",
        "fit",
        "base:register_slot",
        "lid:register_wall",
        min_mm=0.05,
        max_mm=0.25,
    )
    assert outcome(check(built), "c-fit")["state"] == "satisfied"

    rewrite(built, "lid", LID_UNTAGGED_SRC)
    build_all(built, "lid")

    row = outcome(check(built), "c-fit")
    assert row["state"] == "unresolvable"
    assert row["reason"] == "dangling_selector"
    assert "register_wall" in str(row["detail"])
    assert row["residual"] is None


def test_a_malformed_anchor_never_reaches_evaluation(built: Project) -> None:
    """The grammar is checked at declaration, so a typo is refused, not deferred.

    ``part/selector`` is the §7 *cross-part* spelling; an anchor already knows
    which part it means, so accepting it here would leave two grammars for one
    string. Nothing is written.
    """
    with pytest.raises(DispatchError) as excinfo:
        declare(built, "c-slash", "no_interference", "base/rim_top", "lid")
    assert excinfo.value.reason == "invalid_constraint"
    assert cast("dict[str, Any]", built.call("read_constraints", {}))["generation"] == 0
