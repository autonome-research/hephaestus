# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""G14C clauses 18-20: the vocabulary lint, disjoint severities, never-green.

Clause 18 is the whole-token, case-insensitive banned-claim lint over the 14C
surfaces — result serializations and CLI strings — with the three negative
controls that distinguish it from the substring sweep it replaces: the spec
MANDATES ``unverifiable``, ``collision_at_samples`` and
``no_collision_at_samples_in_declared_scene``, so a substring lint would ban
the spec. Clause 19 asserts the CAM and DFM severity vocabularies are
disjoint AS SETS. Clause 20 is the never-green rule under the FakeModel
posture: the blocking findings come from the engine's status, and a
reviewer-supplied verdict for a CAM id is filed as unknown and counts for
nothing.
"""

from __future__ import annotations

import json
from typing import Any, cast

from _g14c import check_kwargs, declare_drill_setup, foul_members
from hephaestus.agent_bridge.review import (
    ReviewContext,
    normalize_findings,
    program_review_findings,
)
from hephaestus.core.cam_check import (
    CAM_SEVERITIES,
    PROGRAM_VERDICTS,
    CamSimTimeout,
    check_setup,
)
from hephaestus.core.checks.engine import run_checks
from hephaestus.core.checks.facade import project_measurement
from hephaestus.core.cli_cam import format_program_status
from hephaestus.core.lint import CAM_BANNED_CLAIM_TOKENS, cam_banned_claims
from hephaestus.core.project_store.cam import CamState
from hephaestus.core.registry._dfm import SEVERITIES as DFM_SEVERITIES


def _surfaces(bench_copy: tuple[Any, Any]) -> list[str]:
    """Every 14C surface under lint: result serializations and CLI strings,
    from real runs covering clean, gouge, fouling and undeclared scenes —
    plus an ``unverifiable`` check outcome, so all three negative controls
    are genuinely present in the corpus."""
    layout, store = bench_copy
    cam = CamState(layout, store)
    declare_drill_setup(cam)
    out: list[str] = []
    clean = check_setup(layout, store, "s-op1", **check_kwargs())
    cam.operations.update("op-drill", {"depth_mm": 5.0}, "the gouge fixture")
    gouge = check_setup(layout, store, "s-op1", **check_kwargs())
    cam.fixtures.update("fx-post", {"members": foul_members()}, "the fouling fixture")
    fouled = check_setup(layout, store, "s-op1", **check_kwargs(), simulate=False)
    cam.fixtures.update("fx-post", {"members": []}, "the undeclared fixture")
    undeclared = check_setup(layout, store, "s-op1", **check_kwargs(), simulate=False)
    for status in (clean, gouge, fouled, undeclared):
        document = status.to_json()
        out.append(json.dumps(document, sort_keys=True))
        out.append(format_program_status(document))

    def timing_out(_setup: str) -> Any:
        raise CamSimTimeout(
            "setup s-op1: removal simulation did not finish within 10s and was killed",
            setup_id="s-op1",
            timeout_s=10.0,
            moves_simulated=3,
            ops_simulated=({"op": "op-drill", "samples": 37, "moves": 3},),
            lost=("removal_boolean", "surface_sampling"),
            cheap={"coverage": "covered"},
        )

    results = run_checks(
        {"programmed": lambda m: m.program("s-op1")},
        lambda: project_measurement({}, program=timing_out),
    )
    out.append(json.dumps(results["programmed"].to_json(), sort_keys=True))
    return out


# -- clause 18: the whole-token lint over every 14C surface -----------------


def test_no_banned_claim_token_appears_on_any_surface_and_the_controls_pass(
    bench_copy: tuple[Any, Any],
) -> None:
    surfaces = _surfaces(bench_copy)
    corpus = "\n".join(surfaces)
    # The three negative controls ARE in the corpus — the spec mandates the
    # strings a substring sweep would have fired on.
    assert "unverifiable" in corpus
    assert "collision_at_samples" in corpus
    assert "no_collision_at_samples_in_declared_scene" in corpus
    # …and every surface passes the whole-token, case-insensitive lint.
    for surface in surfaces:
        assert cam_banned_claims(surface) == (), surface[:200]


def test_the_lint_is_whole_token_and_case_insensitive_not_substring() -> None:
    assert CAM_BANNED_CLAIM_TOKENS == (
        "verified",
        "safe",
        "collision-free",
        "validated",
        "ready to run",
    )
    # Whole-token: the mandated strings never fire.
    assert cam_banned_claims("safely") == ()
    assert cam_banned_claims("unverifiable") == ()
    assert cam_banned_claims("collision_at_samples") == ()
    assert cam_banned_claims("no_collision_at_samples_in_declared_scene") == ()
    # …while the actual claims fire, whatever the case.
    assert cam_banned_claims("this program is Verified") == ("verified",)
    assert cam_banned_claims("SAFE to run") == ("safe",)
    assert cam_banned_claims("it is collision-free now") == ("collision-free",)
    assert cam_banned_claims("Ready  to\trun") == ("ready to run",)


def test_every_universal_verdict_carries_its_at_samples_suffix() -> None:
    """§1.1: a claim quantifying over a continuum says so in its name.
    ``covered``/``uncovered`` (a finite enumerated set), the round-trip pair
    (an exact byte comparison) and the two states are the deliberate
    exceptions."""
    exempt = {
        "covered",
        "uncovered",
        "round_trip_identical",
        "round_trip_diverged",
        "unverifiable",
        "unresolvable",
    }
    sampled = set(PROGRAM_VERDICTS) - exempt
    assert sampled, "the closed set carries sampled verdicts"
    for verdict in sampled:
        assert "_at_samples" in verdict, verdict
    # The §1.1 asymmetry, on purpose: the positive collision claim is scoped
    # to the declared scene; a found collision is a found collision.
    assert "no_collision_at_samples_in_declared_scene" in PROGRAM_VERDICTS
    assert "collision_at_samples" in PROGRAM_VERDICTS


# -- clause 19: CAM and DFM severities are disjoint, as sets ----------------


def test_cam_and_dfm_severity_vocabularies_are_disjoint_sets() -> None:
    """§1.3: a DFM ``error`` means "will not manufacture well"; borrowing it
    for "this will crash" would quietly degrade both readings. Asserted as
    SETS so a future edit cannot merge them by accident."""
    assert set(CAM_SEVERITIES) == {"crash_risk", "part_risk", "advisory"}
    assert set(DFM_SEVERITIES) == {"error", "warning", "info"}
    assert set(CAM_SEVERITIES) & set(DFM_SEVERITIES) == set()


# -- clause 20: never-green from engine status; reviewer verdicts count nil --


def test_each_non_success_program_state_blocks_by_rule_from_the_engine(
    bench_copy: tuple[Any, Any],
) -> None:
    layout, store = bench_copy
    cam = CamState(layout, store)
    declare_drill_setup(cam, depth_mm=5.0)  # gouge
    gouge = check_setup(layout, store, "s-op1", **check_kwargs()).to_json()
    cam.operations.update("op-drill", {"depth_mm": 4.0}, "back to nominal")
    cam.fixtures.update("fx-post", {"members": foul_members()}, "the fouling fixture")
    fouled = check_setup(layout, store, "s-op1", **check_kwargs(), simulate=False).to_json()
    cam.operations.update(
        "op-drill", {"tool": "em_3mm_2fl_carbide"}, "an unknown-feed fixture"
    )
    unresolvable = check_setup(
        layout, store, "s-op1", **check_kwargs(), simulate=False
    ).to_json()
    assert unresolvable["state"] == "unresolvable"
    programs = (gouge, fouled, unresolvable)

    findings = program_review_findings(programs)
    by_id = {finding.id: finding for finding in findings}
    # A non-success verdict blocks; a crash_risk finding blocks; an
    # unresolvable setup blocks — each stamped from the engine's status.
    assert by_id["s-op1:simulation"].verdict == "fail"
    assert by_id["s-op1:simulation"].harness is True
    assert "gouge_at_samples" in by_id["s-op1:simulation"].evidence
    crash_ids = [fid for fid in by_id if fid.startswith("collision:")]
    assert crash_ids and all(by_id[fid].harness for fid in crash_ids)
    assert by_id["s-op1"].verdict == "fail"
    assert "could NOT be checked" in by_id["s-op1"].evidence


def test_a_reviewer_supplied_cam_verdict_is_filed_unknown_and_counts_for_nothing(
    bench_copy: tuple[Any, Any],
) -> None:
    """The FakeModel posture (VALIDATION.md:236-239 shape): the reviewer
    passes everything it is shown, CAM ids included — and the blocking
    finding stands because it was never the reviewer's to give."""
    layout, store = bench_copy
    declare_drill_setup(CamState(layout, store), depth_mm=5.0)
    gouge = check_setup(layout, store, "s-op1", **check_kwargs()).to_json()

    report = normalize_findings(
        (),
        [
            {
                "id": "s-op1:simulation",
                "verdict": "pass",
                "evidence": "the program looks fine to me",
                "channel": "numeric",
            }
        ],
        programs=(gouge,),
    )
    # The confident pass for the CAM id was neither asked for nor accepted.
    assert "s-op1:simulation" in report.unknown_ids
    blocking = report.by_id["s-op1:simulation"]
    assert blocking.verdict == "fail" and blocking.harness is True
    assert report.green is False
    # The report carries the program state it was judged against.
    assert report.programs == (gouge,)


def test_the_reviewer_context_carries_program_status_and_says_the_rule(
    bench_copy: tuple[Any, Any],
) -> None:
    layout, store = bench_copy
    declare_drill_setup(CamState(layout, store))
    status = check_setup(layout, store, "s-op1", **check_kwargs()).to_json()
    context = ReviewContext(
        request="a drilled block",
        requirements=(),
        parts=(),
        programs=(cast("Any", status),),
    )
    blob = context.to_json()
    assert blob["programs"][0]["setup"] == "s-op1"
    prompt = context.prompt()
    assert "'programs'" in prompt
    assert "no verdict is solicited or accepted for a CAM id" in prompt
    # The context's own lint: no banned claim in what the reviewer is handed.
    assert cam_banned_claims(json.dumps(blob["programs"], sort_keys=True)) == ()
