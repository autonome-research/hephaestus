# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""`CI_ONLY.md` names real jobs and real steps.

The clauses of G7H that no local test can prove are enumerated in
`tests/stage7h/CI_ONLY.md`, each pointing at the workflow job that does prove
it. That document is load-bearing — it is the reason "this clause has no test
here" reads as *covered elsewhere* rather than *forgotten* — and a pointer
document decays in exactly one way: the job gets renamed, the reference does
not, and the clause quietly becomes uncovered while the prose still claims
otherwise.

So every job and step `CI_ONLY.md` cites is resolved against the workflow files.
This is a cheap check that keeps an expensive claim honest.

It deliberately does NOT check the reverse direction (every CI-only clause is
listed). No mechanical source of truth exists for "the set of clauses", since
that is a reading of `mission_plan.md` prose; the gate against omission there is
review, and the marker vocabulary the document defines.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Final

import pytest
import yaml

REPO: Final[Path] = Path(__file__).resolve().parents[2]
CI_ONLY: Final[Path] = Path(__file__).resolve().parent / "CI_ONLY.md"
WORKFLOWS: Final[Path] = REPO / ".github" / "workflows"

#: ``…`release.yml` → `lane-a` → *step name*, *another step*…``
_ROW_RE: Final[re.Pattern[str]] = re.compile(r"`(\w+\.yml)`\s*→\s*`([\w-]+)`([^|\n]*)")
_STEP_RE: Final[re.Pattern[str]] = re.compile(r"\*([^*]+)\*")


def _doc() -> str:
    return CI_ONLY.read_text(encoding="utf-8")


def _workflow(name: str) -> dict[str, Any]:
    loaded = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _citations() -> list[tuple[str, str, list[str]]]:
    """``(workflow, job, [step names])`` for every pointer in the document."""
    found: list[tuple[str, str, list[str]]] = []
    for workflow, job, tail in _ROW_RE.findall(_doc()):
        steps = [s.strip() for s in _STEP_RE.findall(tail)]
        found.append((workflow, job, steps))
    return found


def test_the_document_actually_cites_something() -> None:
    """Guard against a regex that silently matches nothing.

    Without this, renaming the citation format would turn every assertion below
    into a vacuous pass over an empty list — a green check proving nothing.
    """
    citations = _citations()
    assert len(citations) >= 10, f"only {len(citations)} citations parsed; the format changed"
    assert any(steps for _, _, steps in citations), "no step-level citations parsed"


@pytest.mark.parametrize("workflow", ["release.yml", "bench.yml"])
def test_every_cited_workflow_exists(workflow: str) -> None:
    assert (WORKFLOWS / workflow).is_file()


def test_every_cited_job_exists() -> None:
    """A renamed job must break this test, not silently orphan a clause."""
    missing: list[str] = []
    for workflow, job, _ in _citations():
        jobs = _workflow(workflow)["jobs"]
        if job not in jobs:
            missing.append(f"{workflow} has no job `{job}` (CI_ONLY.md cites it)")
    assert not missing, "\n".join(missing)


def test_every_cited_step_exists_in_its_job() -> None:
    """The step names quoted in italics are real `name:` values."""
    problems: list[str] = []
    for workflow, job, steps in _citations():
        definition = _workflow(workflow)["jobs"].get(job)
        if definition is None:
            continue  # reported by the job test above
        names = {
            str(step.get("name", "")).strip()
            for step in definition.get("steps", [])
            if isinstance(step, dict)
        }
        for step in steps:
            if step not in names:
                problems.append(f"{workflow}:{job} has no step named '{step}'")
    assert not problems, "\n".join(problems)


def test_every_lane_of_the_matrix_is_accounted_for() -> None:
    """Every lane G7 named appears — the live ones, the DEFERRED lane-c
    (2026-08-13 amendment; accounted for is the whole point of a deferral, as
    opposed to a drop) — plus the two aggregation jobs."""
    text = _doc()
    for job in ("lane-a", "lane-b", "lane-c", "lane-d", "prior-gates", "release-gate"):
        assert f"`{job}`" in text, f"CI_ONLY.md never mentions {job}"


def test_the_deferred_lane_names_the_tests_that_pin_it() -> None:
    """Lane (c) is DEFERRED; the document must point at the tests holding the
    deferral honest in both directions.

    Repointed from ``test_the_known_red_lane_names_the_tests_that_pin_it``
    under the G7H amendment (2026-08-13, ``mission_plan.md`` §"Stage 7H"): the
    lane-c job was removed from ``release.yml``, so the entry to keep visible
    is no longer a KNOWN RED gap but the dated deferral itself. If either
    named test is renamed away, the DEFERRED entry loses its tripwire and the
    clause can rot into a silent drop (or a silent resurrection).
    """
    text = _doc()
    assert "DEFERRED (2026-08-13" in text, (
        "CI_ONLY.md §3 no longer carries the dated lane (c) deferral"
    )
    for pin in (
        "test_lane_c_is_deferred_not_silently_dropped",
        "test_bwrap_is_still_the_only_secure_backend",
    ):
        assert pin in text, f"CI_ONLY.md does not name the pinning test {pin}"
        hits = list(Path(__file__).parent.glob("test_*.py"))
        assert any(pin in p.read_text(encoding="utf-8") for p in hits), (
            f"CI_ONLY.md names {pin}, but no test in tests/stage7h defines it"
        )


def test_the_deferral_agrees_with_the_mission_plan_and_the_workflow() -> None:
    """The three normative locations tell one story.

    ``mission_plan.md`` records the dated operator decision, ``CI_ONLY.md``
    carries the DEFERRED entry, and ``release.yml`` contains no lane-c job.
    Any one of them changing alone — the plan un-deferring, the document
    forgetting, or the workflow resurrecting the lane — is the inconsistency
    this test exists to catch.
    """
    plan = (REPO / "mission_plan.md").read_text(encoding="utf-8")
    assert "G7H amendment (2026-08-13" in plan, (
        "mission_plan.md no longer records the dated lane (c) deferral decision"
    )
    assert "DEFERRED to the post-v0.1" in plan
    assert "DEFERRED (2026-08-13" in _doc()
    release = _workflow("release.yml")
    assert "lane-c" not in release["jobs"], (
        "release.yml grew a lane-c job while CI_ONLY.md still records the "
        "clause as deferred; revisit the 2026-08-13 amendment first"
    )


def test_the_g6_bench_clause_is_marked_red_for_exactly_as_long_as_it_is_open() -> None:
    """G7H requires G6 green on the release SHA; G6's numeric clause is OPEN.

    `prior-gates` can only prove that the `stage gates 1-6` *job* concluded
    success, and that job runs pytest — it never runs a Tier 3 corpus sweep. So
    "G6 green" as CI measures it is strictly weaker than "G6 green" as
    `mission_plan.md` defines it, and the gap is invisible unless the document
    says so.

    This test is the tripwire in both directions. While `mission_plan.md`
    §"G6 status" records the bench clause OPEN, `CI_ONLY.md` must carry the
    KNOWN RED paragraph naming it. The day that clause closes, the assertion
    inverts and fails until the stale paragraph is deleted — the same
    maintenance contract the document states for every other entry.
    """
    plan = (REPO / "mission_plan.md").read_text(encoding="utf-8")
    section = plan.split("**G6 status", 1)
    assert len(section) == 2, "mission_plan.md no longer has a `**G6 status` section"
    status = section[1].split("\n## ", 1)[0]
    open_in_plan = "OPEN" in status

    text = _doc()
    marked_red = "KNOWN RED (G6's bench clause)" in text

    if open_in_plan:
        assert marked_red, (
            "mission_plan.md still records G6's Tier 3 bench clause OPEN, but "
            "CI_ONLY.md §5 no longer marks it KNOWN RED — the weakest link in "
            "the prior-gates clause would be undocumented"
        )
    else:
        assert not marked_red, (
            "mission_plan.md no longer records G6's bench clause OPEN; delete "
            "the KNOWN RED paragraph from CI_ONLY.md §5 (see its Maintenance "
            "section) rather than leaving a resolved gap advertised as a gap"
        )


def test_the_archived_measurement_cited_as_red_really_fails_the_gate() -> None:
    """The KNOWN RED entry cites a file and a number; both must still hold.

    A prose claim that a run missed the bar is worth nothing if the run it names
    was superseded. This reads the artifact rather than trusting the sentence.
    """
    if "KNOWN RED (G6's bench clause)" not in _doc():
        pytest.skip("G6's bench clause is no longer marked red; nothing to corroborate")

    summary = REPO / "bench" / "results" / "gpt-5.6-sol" / "2026-07-29.json"
    assert summary.is_file(), f"CI_ONLY.md cites {summary}, which does not exist"
    data = json.loads(summary.read_text(encoding="utf-8"))
    assert data["meets_gate"] is False, (
        f"{summary} now reports meets_gate=True; CI_ONLY.md §5 cites it as the "
        "evidence G6's bench clause is unmet and must be revisited"
    )
    assert data["pass_rate_prose"] < 0.70, (
        f"{summary} now reports pass_rate_prose={data['pass_rate_prose']}, which "
        "no longer corroborates the KNOWN RED entry in CI_ONLY.md §5"
    )


def test_no_ci_only_clause_is_also_claimed_as_a_local_skip() -> None:
    """No test in this directory skips with a reason that names a CI-only lane.

    The document's whole premise is that a CI-only clause has *no* local test.
    A `pytest.skip("covered by lane (c)")` would report green while proving
    nothing, which is the failure mode `CI_ONLY.md` exists to prevent.
    """
    offenders: list[str] = []
    for path in sorted(Path(__file__).parent.glob("test_*.py")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if not stripped.startswith(("pytest.skip", "@pytest.mark.skip")):
                continue
            if re.search(r"lane \((a|c|d)\)|prior-gates|release-gate", stripped):
                offenders.append(f"{path.name}:{lineno}: {stripped}")
    assert not offenders, "CI-only clauses must not be skipped locally:\n" + "\n".join(offenders)
