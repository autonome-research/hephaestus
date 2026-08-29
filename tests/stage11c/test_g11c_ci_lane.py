"""Stage 11's gates are commands, not habits (``PARTS_STORE.md`` §Gates).

Mission rule 1: "Gates are commands. Every criterion above maps to a CI job."
When a verifier checked on 2026-08-29, ``tests/stage11a``, ``tests/stage11b``
and ``tests/stage11c`` appeared in no workflow — every other stage suite in the
repository (0a, 0b, 1, 2, 2v, 3, 4, 6, 7h, 8a-8d, 9a-9c) had a lane and Stage 11
was the sole exception. Three Tier-1 gates that pass only on a developer's
machine are not gates yet, so the lane landed with that finding's repair.

This module is what keeps it landed. The failure mode it exists against is not
"someone deletes the job" — that is loud — but the quiet one: a fourth sub-stage
suite is added later and nobody extends the job's argument list, so a gate is
green in the document and unrun in CI. So the assertion is over the **suite
directories that exist**, not over a copy of today's command line.

It lives in ``tests/stage11c`` because that is the last sub-stage's suite and
the one a full-matrix run reaches last; it asserts on behalf of all three.
``tests/stage7h`` separately pins that every ci.yml check name is required by
``release.yml``, which is why a job asserted here is also a job a release cannot
skip.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import yaml

REPO: Path = Path(__file__).resolve().parents[2]
CI: Path = REPO / ".github" / "workflows" / "ci.yml"
RELEASE: Path = REPO / ".github" / "workflows" / "release.yml"

#: The job that carries Stage 11, by the name it publishes as a check.
STAGE11_JOB_NAME: str = "stage gates 11A-11C"


def _workflow(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), f"{path} is not a YAML mapping"
    return cast("dict[str, Any]", loaded)


def _stage11_suites() -> list[str]:
    """Every Stage 11 suite directory that exists, as pytest would be given it."""
    found = sorted(
        f"tests/{path.name}"
        for path in (REPO / "tests").iterdir()
        if path.is_dir() and path.name.startswith("stage11")
    )
    assert found, "no tests/stage11* suite exists; this test would prove nothing"
    return found


def test_every_stage11_suite_runs_in_a_ci_job() -> None:
    """The three suites are arguments of a real ``uv run pytest`` step."""
    jobs = cast("dict[str, Any]", _workflow(CI)["jobs"])
    commands = [
        str(step.get("run", ""))
        for job in jobs.values()
        for step in cast("list[dict[str, Any]]", cast("dict[str, Any]", job).get("steps", []))
    ]
    for suite in _stage11_suites():
        assert any(suite in command and "pytest" in command for command in commands), (
            f"{suite} runs in no ci.yml job; mission rule 1 makes a gate a command"
        )


def test_the_stage11_job_provisions_what_the_suites_need() -> None:
    """The prerequisites are named, and the ones deliberately absent stay absent.

    G11A's runtime-sandbox refusal needs bubblewrap; G11C clause 11 grades two
    corpus tasks through the engine path and needs the software renderer. Node
    is deliberately **not** provisioned — the contract-drift clauses read the
    committed ``schema.gen.ts`` and compare it in-process — and that absence is
    asserted rather than left to drift back in, because an unexplained
    prerequisite is how a lane becomes cargo cult.
    """
    jobs = cast("dict[str, Any]", _workflow(CI)["jobs"])
    job = next(
        cast("dict[str, Any]", value)
        for value in jobs.values()
        if str(cast("dict[str, Any]", value).get("name", "")) == STAGE11_JOB_NAME
    )
    steps = cast("list[dict[str, Any]]", job["steps"])
    script = "\n".join(str(step.get("run", "")) for step in steps)
    uses = [str(step.get("uses", "")) for step in steps]
    assert "bubblewrap" in script
    assert "apparmor_restrict_unprivileged_userns" in script
    assert "libgl1-mesa-dri" in script
    assert not any("setup-node" in item or "pnpm" in item for item in uses), (
        "this lane needs no Node; add it only with the clause that needs it"
    )


def test_the_stage11_check_is_required_before_a_release() -> None:
    """A gate a release can be cut over is not a gate (rule 1, G7H's lane)."""
    assert STAGE11_JOB_NAME in RELEASE.read_text(encoding="utf-8")
