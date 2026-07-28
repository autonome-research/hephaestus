"""G8C: the whole feature on the failure it exists for, from one scripted run.

Two gate clauses, told as one story because that is how they occur:

* *staleness (editing a constrained part marks the assembly projection stale;
  re-evaluation flips a formerly satisfied fit that the edit broke)*;
* *the reviewer context carrying ``AssemblyStatus`` and a violated constraint
  producing a blocking finding by rule (FakeModel harness)*.

The run is scripted, not real: a fixed turn list issued through the **real tool
dispatcher** stands in for the model, and the reviewer is a FakeModel that
passes confidently on everything it is shown — including the mate. That is the
adversarial case ``VALIDATION.md`` §5 was written for: the blocking finding has
to come from the engine's own measurement, so that no amount of agreement
between the agent and the reviewer can talk a broken fit closed.

The story:

1. the model records requirements, authors ``base`` and ``lid``, builds both and
   declares the register fit **citing the requirement it came from**;
2. ``check_assembly`` measures 0.15 mm of radial clearance: satisfied, and the
   run reviews green;
3. someone tightens the lid's boss to 0.005 mm of clearance and rebuilds — the
   projected status goes STALE rather than silently changing its mind, and
   re-evaluating flips the fit to violated;
4. the termination review then cannot be green however enthusiastically the
   reviewer passes it, and stays not-green until the geometry is fixed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

import pytest
from _g8c import (
    BASE_SRC,
    NOMINAL_CLEARANCE_MM,
    build_all,
    check,
    lid_src,
    outcome,
    rewrite,
    write_part,
)
from hephaestus.agent_bridge.review import (
    ReviewerResponse,
    ReviewRequest,
    TerminalReport,
    TerminationReviewService,
    assembly_status,
    build_review_context,
)
from hephaestus.testing.tools_fixture import Project

#: What the run says it is building. ``R-REGISTER`` is the requirement the mate
#: cites: a constraint is an interpretation of intent, and this one's intent is
#: on the record.
LEDGER: list[dict[str, Any]] = [
    {
        "id": "R-REGISTER",
        "text": "the lid registers into the base with a 0.15 mm radial slip fit",
        "source": "specified",
        "quote": "the lid should locate on the base with a slip fit",
        "value": 0.15,
        "unit": "mm",
        "applies_to": "lid",
    },
    {
        "id": "R-SEAT",
        "text": "the lid seats flush on the base rim",
        "source": "specified",
        "quote": "the lid should sit flush",
        "applies_to": "lid",
    },
]

#: The fit as the model declares it: cited, and with the window the request's
#: number implies rather than the number the geometry happens to produce.
REGISTER_FIT: dict[str, Any] = {
    "id": "c-register-fit",
    "kind": "fit",
    "a": "base:register_slot",
    "b": "lid:register_wall",
    "min_mm": 0.05,
    "max_mm": 0.25,
    "provenance": {"requirement": "R-REGISTER"},
    "note": "slip fit: the boss must clear the bore without rattling",
}

SEAT_COINCIDENT: dict[str, Any] = {
    "id": "c-seat-flush",
    "kind": "coincident",
    "a": "base:rim_top",
    "b": "lid:seat_face",
    "tol_mm": 0.01,
    "provenance": {"requirement": "R-SEAT"},
}

#: The lid, tightened until the boss all but jams in the bore: 0.005 mm of
#: radial clearance against a declared floor of 0.05 mm.
TIGHT_CLEARANCE_MM = 0.005


class FakeReviewer:
    """A reviewer child that passes everything it is shown, confidently.

    It also returns a ``pass`` for the constraint id itself, which must count for
    nothing: no verdict is solicited for a constraint and none is accepted
    (``ASSEMBLY.md`` §3), because the mate was measured against geometry nobody
    in the conversation gets to reinterpret.
    """

    def __init__(self) -> None:
        self.requests: list[ReviewRequest] = []

    def call(self, request: ReviewRequest) -> ReviewerResponse:
        self.requests.append(request)
        findings = [
            {
                "id": str(cast("Mapping[str, Any]", entry)["id"]),
                "verdict": "pass",
                "evidence": "measured it, looks right",
                "channel": "numeric",
            }
            for entry in request.context.requirements
        ]
        findings.append(
            {
                "id": REGISTER_FIT["id"],
                "verdict": "pass",
                "evidence": "the lid drops straight in",
                "channel": "vision",
            }
        )
        return ReviewerResponse(findings=tuple(findings))


def run_the_model(project: Project, *, clearance: float = NOMINAL_CLEARANCE_MM) -> None:
    """The scripted run: requirements, geometry, builds, then the declared mates."""
    project.call("record_requirements", {"entries": LEDGER})
    write_part(project, "base", BASE_SRC)
    write_part(project, "lid", lid_src(clearance))
    build_all(project, "base", "lid")
    project.call("declare_constraint", REGISTER_FIT)
    project.call("declare_constraint", SEAT_COINCIDENT)


def review(project: Project) -> tuple[Any, FakeReviewer]:
    reviewer = FakeReviewer()
    report = TerminationReviewService(project.cad, reviewer).review(
        request="a two-part enclosure: the lid registers into the base",
        run_id="run-1",
    )
    return report, reviewer


def terminal(project: Project, report: Any) -> TerminalReport:
    return TerminalReport.of(
        report,
        cycles=1,
        reason="stop state",
        entries=project.cad.ledger_state().entries,
    )


@pytest.fixture
def run(empty: Project) -> Project:
    """A finished, honest run: both parts built, both mates declared and measured."""
    run_the_model(empty)
    return empty


# ==========================================================================
# 1-2: the run measures its own claim


def test_the_declared_register_fit_is_measured_and_traced_to_its_requirement(
    run: Project,
) -> None:
    status = check(run)

    fit = outcome(status, "c-register-fit")
    assert fit["state"] == "satisfied"
    assert cast("Mapping[str, Any]", fit["residual"])["measured"] == pytest.approx(
        NOMINAL_CLEARANCE_MM, abs=1e-9
    )
    # The mate names the requirement it interprets, so a reviewer reading the
    # status can tell a stated interface from an invented one.
    assert fit["provenance"] == {"requirement": "R-REGISTER"}
    assert outcome(status, "c-seat-flush")["state"] == "satisfied"
    assert list(cast("list[Any]", status["blocking"])) == []


def test_a_run_whose_mates_hold_can_terminate_green(run: Project) -> None:
    check(run)
    report, reviewer = review(run)

    assert report.green is True
    assert report.assembly is not None and report.assembly.blocking() == ()
    # The reviewer was handed the full status, not a summary of it.
    context = reviewer.requests[0].context
    assert context.assembly is not None
    assert context.assembly.satisfied == ("c-register-fit", "c-seat-flush")
    assert terminal(run, report).status == "green"


# ==========================================================================
# 3: the edit, the staleness, the flip


def test_editing_a_constrained_part_marks_the_projection_stale(run: Project) -> None:
    """A rebuild does not silently re-decide the mate; it says the status is old.

    This is the ``hc``/import staleness machinery applied to the assembly
    projection (``ASSEMBLY.md`` §2): the number on file was measured against an
    artifact the project no longer publishes, and a reader is told so instead of
    being handed a recomputed answer it did not ask for.
    """
    assert list(cast("list[Any]", check(run)["stale"])) == []

    rewrite(run, "lid", lid_src(TIGHT_CLEARANCE_MM))
    build_all(run, "lid")

    read = cast("dict[str, Any]", run.call("read_constraints", {}))
    projected = cast("Mapping[str, Any]", read["assembly"])
    assert list(cast("list[Any]", projected["stale"])) == ["lid"]
    # Reading still reports what was actually measured, and it was satisfied:
    # honest, and useless without the staleness beside it — which is the point.
    assert outcome(projected, "c-register-fit")["state"] == "satisfied"


def test_re_evaluation_flips_the_fit_the_edit_broke(run: Project) -> None:
    assert outcome(check(run), "c-register-fit")["state"] == "satisfied"

    rewrite(run, "lid", lid_src(TIGHT_CLEARANCE_MM))
    build_all(run, "lid")
    status = check(run)

    fit = outcome(status, "c-register-fit")
    assert fit["state"] == "violated"
    # The same declaration, a different measurement: 0.005 mm against a 0.05 mm
    # floor. Nothing about the claim changed — the geometry did.
    assert cast("Mapping[str, Any]", fit["residual"])["measured"] == pytest.approx(
        TIGHT_CLEARANCE_MM, abs=1e-9
    )
    assert cast("Mapping[str, Any]", fit["residual"])["slack"] == pytest.approx(-0.045, abs=1e-9)
    # The seat is untouched by the edit and stays satisfied: the flip is local to
    # the mate the edit actually broke.
    assert outcome(status, "c-seat-flush")["state"] == "satisfied"
    assert list(cast("list[Any]", status["blocking"])) == ["c-register-fit"]
    # …and the fresh evaluation is no longer stale.
    assert list(cast("list[Any]", status["stale"])) == []


# ==========================================================================
# 4: the reviewer cannot pass it, and the run cannot terminate green


def test_a_violated_mate_blocks_termination_however_it_is_reviewed(run: Project) -> None:
    check(run)
    rewrite(run, "lid", lid_src(TIGHT_CLEARANCE_MM))
    build_all(run, "lid")

    report, reviewer = review(run)

    # The reviewer passed every requirement, and its opinion of the mate was
    # neither asked for nor accepted.
    assert report.by_id["R-REGISTER"].verdict == "pass"
    assert "c-register-fit" in report.unknown_ids
    blocking = report.by_id["c-register-fit"]
    assert blocking.verdict == "fail"
    assert blocking.harness is True, "the finding is stamped by rule, not solicited"
    assert "violated" in blocking.evidence
    # It says what was declared and what was measured, in the same breath.
    assert "min_mm=0.05" in (blocking.expected or "")
    assert "measured" in (blocking.observed or "")
    assert report.green is False

    open_items = terminal(run, report)
    assert open_items.status == "unresolved_requirements"
    item = next(entry for entry in open_items.unresolved if entry.id == "c-register-fit")
    assert item.source == "constraint"
    # The reviewer really was shown the failure it passed anyway.
    context = reviewer.requests[0].context
    assert context.assembly is not None and context.assembly.violated == ("c-register-fit",)
    assert context.assembly_ref is not None


def test_the_reviewer_measures_now_rather_than_reading_the_last_check(run: Project) -> None:
    """The blocking rule does not depend on anyone having run ``check_assembly``.

    The last projected status says satisfied and nothing re-ran it; the review
    still catches the broken fit, because a stale pass is the one outcome §5 must
    never produce.
    """
    check(run)
    rewrite(run, "lid", lid_src(TIGHT_CLEARANCE_MM))
    build_all(run, "lid")

    fresh = assembly_status(run.cad)
    assert fresh is not None and fresh.blocking() == ("c-register-fit",)
    report, _reviewer = review(run)
    assert report.green is False


def test_an_unmeasurable_mate_blocks_under_its_own_name(run: Project) -> None:
    """``unresolvable`` is not ``violated``, and it is not a pass either."""
    from _g8c import LID_UNTAGGED_SRC

    rewrite(run, "lid", LID_UNTAGGED_SRC)
    build_all(run, "lid")

    report, _reviewer = review(run)

    blocking = report.by_id["c-register-fit"]
    assert blocking.verdict == "fail" and blocking.harness is True
    assert "could NOT be evaluated" in blocking.evidence
    assert "dangling_selector" in blocking.evidence
    # Nothing was measured, so nothing is claimed to have been.
    assert blocking.observed is None
    assert report.green is False


def test_fixing_the_geometry_is_what_closes_the_finding(run: Project) -> None:
    """The full loop: broken, blocked, fixed, green — with no claim ever edited."""
    rewrite(run, "lid", lid_src(TIGHT_CLEARANCE_MM))
    build_all(run, "lid")
    broken, _first = review(run)
    assert broken.green is False
    assert terminal(run, broken).status == "unresolved_requirements"

    rewrite(run, "lid", lid_src(NOMINAL_CLEARANCE_MM))
    build_all(run, "lid")
    fixed, _second = review(run)

    assert fixed.green is True
    assert fixed.assembly is not None and fixed.assembly.blocking() == ()
    assert terminal(run, fixed).status == "green"
    # The constraint set never changed: generation 2 is where the two
    # declarations left it, and the fix was geometry, not paperwork.
    read = cast("dict[str, Any]", run.call("read_constraints", {}))
    assert read["generation"] == 2


def test_the_review_context_says_what_it_is_handing_over(run: Project) -> None:
    """The status travels as evidence, and the prompt says how to read it."""
    check(run)
    context = build_review_context(run.cad, request="a two-part enclosure")

    assert context.assembly is not None
    blob = cast("Mapping[str, Any]", context.to_json())
    assembly = cast("Mapping[str, Any]", blob["assembly"])
    rows = cast("Sequence[Any]", assembly["constraints"])
    assert [cast("Mapping[str, Any]", row)["kind"] for row in rows] == ["fit", "coincident"]
    prompt = context.prompt()
    assert "assembly" in prompt
    # The reviewer is told the rule applies to them: constraints are evidence,
    # not findings to re-litigate.
    assert "blocks termination" in prompt
