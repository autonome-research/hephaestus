# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""G7H's clean-machine matrix, asserted as a *structure* rather than a hope.

Lanes (a)-(d) live in ``.github/workflows/release.yml`` and only ever run on
GitHub's runners: a macOS lane and a "no bubblewrap installed" lane cannot be
reproduced on this machine. What CAN be checked here — and is worth far more
than a YAML linter — is that each lane still *makes the claim its clause names*:

* lane (a) has no Node on it, and does not quietly acquire one via
  ``actions/setup-node``;
* lane (b) installs bubblewrap, runs the escape suite, and plants a hostile
  global ``pi``/``thread-phase`` so "uses its packaged sidecar" is asserted
  against a machine that offers an alternative;
* lane (c) FAILS when no OCI backend answers — the failure mode this suite
  guards hardest, because a lane that skips is indistinguishable from a lane
  that passed;
* lane (d) does not install a secure backend and asserts the named refusal;
* every lane installs the built wheel from the shared ``wheelhouse`` artifact,
  never from the source tree — an in-tree install resolves the *development*
  sidecar and makes the gate's central claim untestable.

These are the invariants that decay silently. A future edit that adds
``continue-on-error: true`` to lane (c), or drops the escape suite from lane
(b), keeps the workflow perfectly valid and quietly guts the gate; each one
fails a test below.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO / ".github" / "workflows"
RELEASE = WORKFLOWS / "release.yml"
BENCH = WORKFLOWS / "bench.yml"
CI = WORKFLOWS / "ci.yml"

#: PyYAML resolves the bare key ``on`` to the boolean ``True`` (YAML 1.1).
ON = True


def _load(path: Path) -> dict[str, Any]:
    doc = yaml.safe_load(path.read_text())
    assert isinstance(doc, dict), f"{path} is not a mapping"
    return doc


@pytest.fixture(scope="module")
def release() -> dict[str, Any]:
    return _load(RELEASE)


@pytest.fixture(scope="module")
def bench() -> dict[str, Any]:
    return _load(BENCH)


def _job(doc: dict[str, Any], name: str) -> dict[str, Any]:
    jobs = doc["jobs"]
    assert name in jobs, f"job {name} is gone; the gate clause it carried is unproven"
    job: dict[str, Any] = jobs[name]
    return job


def _steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for s in job.get("steps", []) if isinstance(s, dict)]


def _script(job: dict[str, Any]) -> str:
    """Every ``run:`` body in the job, concatenated."""
    return "\n".join(str(step.get("run", "")) for step in _steps(job))


def _uses(job: dict[str, Any]) -> list[str]:
    return [str(step["uses"]) for step in _steps(job) if "uses" in step]


LANES = ("lane-a", "lane-b", "lane-c", "lane-d")


# --------------------------------------------------------------------------
# workflow-wide rules


def test_no_workflow_uses_pull_request_target() -> None:
    """Mission rule 8. Never runs untrusted PR code with repository secrets.

    Comment lines are excluded: several of these files say *why* they do not use
    it, and a text search that cannot tell a prohibition from a use is a test
    that punishes documentation.
    """
    for path in sorted(WORKFLOWS.glob("*.yml")):
        code = "\n".join(
            line for line in path.read_text().splitlines() if not line.lstrip().startswith("#")
        )
        assert "pull_request_target" not in code, path
        triggers = _load(path)[ON]
        assert "pull_request_target" not in triggers, path


def test_every_run_block_is_valid_shell() -> None:
    """``bash -n`` over every step body in every workflow.

    The lanes are mostly shell, and half of them run on machines this repository
    cannot reproduce — a macOS runner, a runner with no bubblewrap. A quoting or
    heredoc mistake there costs a full release-matrix round trip to discover, so
    it gets caught here instead. ``${{ … }}`` expressions are replaced with a
    literal first: they are substituted by Actions before the shell ever sees
    them, and leaving them in would just be checking GitHub's grammar.
    """
    for path in sorted(WORKFLOWS.glob("*.yml")):
        doc = _load(path)
        for job_id, job in doc["jobs"].items():
            for step in _steps(job):
                body = step.get("run")
                if not body:
                    continue
                script = re.sub(r"\$\{\{[^}]*\}\}", "GHA_EXPRESSION", str(body))
                checked = subprocess.run(
                    ["bash", "-n"], input=script, text=True, capture_output=True, check=False
                )
                assert checked.returncode == 0, (
                    f"{path.name}:{job_id} step {step.get('name')!r} is not valid "
                    f"shell:\n{checked.stderr}"
                )


def test_every_action_is_pinned_to_the_same_major_as_ci() -> None:
    """One action version across the workflows.

    Two majors of ``upload-artifact`` in one repository is the kind of drift
    that produces a lane which silently uploads nothing.
    """
    versions: dict[str, set[str]] = {}
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for job in _load(path)["jobs"].values():
            for spec in _uses(job):
                action, _, ref = spec.partition("@")
                assert ref, f"{path.name}: {spec} is unpinned"
                versions.setdefault(action, set()).add(ref)
    mixed = {a: sorted(v) for a, v in versions.items() if len(v) > 1}
    assert not mixed, f"actions pinned to different versions: {mixed}"


def test_the_release_workflow_holds_no_write_permission(
    release: dict[str, Any],
) -> None:
    """It verifies a tag; it never cuts or pushes one."""
    assert release["permissions"] == {"contents": "read", "checks": "read"}
    assert "actions/create-release" not in RELEASE.read_text()
    assert "git tag" not in RELEASE.read_text()
    assert "git push" not in RELEASE.read_text()


def test_the_release_workflow_triggers_on_dispatch_and_version_tags(
    release: dict[str, Any],
) -> None:
    triggers = release[ON]
    assert "workflow_dispatch" in triggers
    assert triggers["push"]["tags"] == ["v*"]
    assert "pull_request" not in triggers, "the release matrix is not a per-PR gate; ci.yml is"


def test_the_toolchain_versions_agree_with_ci(release: dict[str, Any]) -> None:
    """A lane on a different Node/Python than ci.yml would be testing a
    different product than the one the prior gates certified."""
    ci = _load(CI)
    for key in ("UV_PYTHON", "NODE_VERSION", "PNPM_VERSION"):
        assert release["env"][key] == ci["env"][key], key


# --------------------------------------------------------------------------
# the wheel every lane measures


def test_the_wheelhouse_is_built_once_by_the_documented_sequence(
    release: dict[str, Any],
) -> None:
    script = _script(_job(release, "wheelhouse"))
    for command in (
        "pnpm --dir agent install --frozen-lockfile",
        "pnpm --dir agent run bundle",
        "scripts/stage_sidecar.py",
        "uv build --all-packages",
    ):
        assert command in script, f"the build no longer runs `{command}` (PACKAGING.md)"
    assert any(u.startswith("actions/upload-artifact") for u in _uses(_job(release, "wheelhouse")))


@pytest.mark.parametrize("lane", LANES)
def test_every_lane_installs_the_built_wheel_and_never_the_source_tree(
    release: dict[str, Any], lane: str
) -> None:
    job = _job(release, lane)
    assert job["needs"] == "wheelhouse" or "wheelhouse" in job["needs"]
    assert any(u.startswith("actions/download-artifact") for u in _uses(job)), (
        f"{lane} does not download the wheelhouse artifact"
    )
    script = _script(job)
    assert "pipx install" in script, f"{lane} does not pipx-install the wheel"
    assert "dist/hephaestus_cad-" in script, f"{lane} installs something else"
    assert "pip install -e" not in script, f"{lane} installs the source tree"


@pytest.mark.parametrize("lane", LANES)
def test_no_lane_reaches_for_the_unsafe_executor(release: dict[str, Any], lane: str) -> None:
    assert "--unsafe-local-executor" not in _script(_job(release, lane))


@pytest.mark.parametrize("lane", LANES)
def test_no_lane_can_pass_by_being_skipped(release: dict[str, Any], lane: str) -> None:
    """No ``continue-on-error``, and no step-level ``if`` that could turn a
    missing prerequisite into a green check."""
    job = _job(release, lane)
    assert not job.get("continue-on-error"), lane
    for step in _steps(job):
        assert not step.get("continue-on-error"), f"{lane}: {step.get('name')}"
        condition = str(step.get("if", ""))
        assert condition in ("", "always()"), (
            f"{lane} step {step.get('name')!r} is conditional on {condition!r}"
        )


# --------------------------------------------------------------------------
# lane (a) — python only, no Node, no script execution


def test_lane_a_runs_on_every_packaging_lane(release: dict[str, Any]) -> None:
    """G7 says lane (a) covers *every* packaging lane, so it is a matrix."""
    matrix = _job(release, "lane-a")["strategy"]["matrix"]
    assert set(matrix["os"]) >= {"ubuntu-latest", "macos-latest"}


def test_lane_a_never_installs_node(release: dict[str, Any]) -> None:
    job = _job(release, "lane-a")
    assert not any("setup-node" in u for u in _uses(job)), (
        "lane (a) installed Node; its entire claim is that none is present"
    )


def test_lane_a_removes_node_from_path_and_asserts_it_is_gone(
    release: dict[str, Any],
) -> None:
    """Hosted images ship Node preinstalled, so absence has to be made true."""
    script = _script(_job(release, "lane-a"))
    assert "contains node" in script or "dropping" in script
    assert 'command -v "$binary"' in script
    assert "lane (a) is invalid" in script


def test_lane_a_does_the_four_things_its_clause_names(release: dict[str, Any]) -> None:
    script = _script(_job(release, "lane-a"))
    assert "heph --version" in script  # -> heph --version
    assert "import hephaestus.core" in script  # -> import smoke
    assert "heph lint" in script  # -> lint smoke
    assert "generate_json_schemas" in script  # -> schema smoke


def test_lane_a_proves_no_script_was_executed(release: dict[str, Any]) -> None:
    script = _script(_job(release, "lane-a"))
    assert "heph build" not in script, "lane (a) executed a part script"
    assert ".heph" in script, "lane (a) never checks that no store was created"


@pytest.mark.parametrize("lane", ["lane-a", "lane-b"])
def test_a_hostile_global_pi_is_planted_and_proven_unused(
    release: dict[str, Any], lane: str
) -> None:
    """repo_conventions.md: never a global ``pi`` or ``thread-phase``.

    An assertion made on a machine where neither exists proves nothing, so both
    lanes plant them on PATH with a witness file.
    """
    script = _script(_job(release, lane))
    assert "thread-phase" in script and "hostile" in script
    assert "hostile-invoked" in script


# --------------------------------------------------------------------------
# lane (b) — the supported secure Linux lane


def test_lane_b_installs_the_secure_backend_prerequisites(
    release: dict[str, Any],
) -> None:
    script = _script(_job(release, "lane-b"))
    assert "bubblewrap" in script
    assert "kernel.apparmor_restrict_unprivileged_userns=0" in script


def test_lane_b_pins_node_to_the_supported_floor(release: dict[str, Any]) -> None:
    job = _job(release, "lane-b")
    node = [s for s in _steps(job) if "setup-node" in str(s.get("uses", ""))]
    assert node, "lane (b) needs Node: it spawns the sidecar"
    assert node[0]["with"]["node-version"] == "${{ env.NODE_VERSION }}"


def test_lane_b_covers_every_clause_of_its_gate_sentence(
    release: dict[str, Any],
) -> None:
    """build/check -> sidecar integrity + addon audit -> JobStore -> agent
    fake-model -> MCP smoke, plus the release-lane escape suite."""
    script = _script(_job(release, "lane-b"))
    assert "heph build" in script and "heph check" in script
    assert "tests/stage7h" in script  # integrity, addon audit, jobstore, agent
    assert "tests/stage3" in script  # MCP smoke
    for suite in (
        "core/tests/test_sandbox_base.py",
        "core/tests/test_sandbox_bwrap.py",
        "core/tests/test_sandbox_probe.py",
        "core/tests/test_registry_sandbox.py",
    ):
        assert suite in script, f"the escape suite lost {suite}"


def test_lane_b_points_the_wheel_suites_at_the_built_artifact(
    release: dict[str, Any],
) -> None:
    """Otherwise the suite rebuilds the tree and measures a second artifact."""
    job = _job(release, "lane-b")
    envs = [step.get("env", {}) for step in _steps(job)]
    assert any("HEPHAESTUS_WHEELHOUSE" in env for env in envs)


# --------------------------------------------------------------------------
# lane (c) — macOS through a detected OCI backend


def test_lane_c_runs_on_macos(release: dict[str, Any]) -> None:
    assert _job(release, "lane-c")["runs-on"] == "macos-latest"


def test_lane_c_fails_when_no_backend_answers(release: dict[str, Any]) -> None:
    """The lane exists to prove the backend path. A skip would be a false green.

    Detection is by *response* (``docker info`` / ``podman info``), not by the
    binary being on PATH: an installed-but-dead Docker must not count.
    """
    script = _script(_job(release, "lane-c"))
    assert "docker info" in script or '"$candidate" info' in script
    assert "exit 1" in script
    assert "never a skip" in script, "the lane no longer records why a missing backend is a failure"
    assert "pytest.skip" not in script


def test_lane_c_probes_the_executor_profile_before_trusting_the_backend(
    release: dict[str, Any],
) -> None:
    """architecture.md: "Stage S must prove this profile rather than trusting
    backend presence."
    """
    script = _script(_job(release, "lane-c"))
    for flag in ("--read-only", "--network none", "--cap-drop ALL"):
        assert flag in script, f"the capability probe dropped {flag}"


def test_lane_c_runs_the_same_smokes_as_the_linux_lane(
    release: dict[str, Any],
) -> None:
    script = _script(_job(release, "lane-c"))
    assert "tests/stage7h" in script  # fake-model
    assert "tests/stage3" in script  # MCP
    assert "test_sandbox_probe.py" in script  # escape suite


def test_lane_c_is_documented_as_red_until_the_oci_backend_lands() -> None:
    """The honest state, recorded where a reader will hit it.

    ``secure_backend()`` constructs a ``BwrapBackend`` and nothing else, so on
    macOS it refuses — correct fail-closed behaviour, and exactly why the lane
    must fail rather than skip. The comment is load-bearing: it is the only
    place that says G7H's lane (c) clause is not yet satisfiable.
    """
    text = RELEASE.read_text()
    assert "KNOWN RED" in text
    assert "OCI backend" in text


# --------------------------------------------------------------------------
# lane (d) — fail-closed


def test_lane_d_installs_no_secure_backend(release: dict[str, Any]) -> None:
    script = _script(_job(release, "lane-d"))
    assert "install -y -q bubblewrap" not in script
    assert "command -v bwrap" in script, (
        "lane (d) does not verify its own premise; a runner image that started "
        "shipping bubblewrap would silently turn this into lane (b)"
    )


def test_lane_d_asserts_the_refusal_rather_than_a_skip(
    release: dict[str, Any],
) -> None:
    script = _script(_job(release, "lane-d"))
    assert "sandbox_unavailable" in script
    assert "tests/stage7h/test_lane_fail_closed.py" in script
    assert "heph build" in script


def test_lane_d_keeps_the_non_executing_surface_alive(
    release: dict[str, Any],
) -> None:
    """Fail-closed is about script execution, not about the tool going dark."""
    script = _script(_job(release, "lane-d"))
    assert "heph --version" in script
    assert "heph lint" in script


# --------------------------------------------------------------------------
# prior gates + the aggregation


def _ci_check_names() -> set[str]:
    """Every check name ci.yml publishes, with its one matrix expanded."""
    ci = _load(CI)
    names: set[str] = set()
    for job_id, job in ci["jobs"].items():
        template = str(job.get("name", job_id))
        shards = job.get("strategy", {}).get("matrix", {}).get("shard")
        if shards:
            for shard in shards:
                names.add(template.replace("${{ matrix.shard }}", str(shard)).strip())
        else:
            names.add(template.strip())
    return names


def test_the_prior_gate_check_names_every_ci_job(release: dict[str, Any]) -> None:
    """G7H: "Gates GS, G0A, G0B, G1, G2, G2V, G3 and G6 are green on the
    release SHA."

    Those gates are ci.yml jobs, so the requirement is set equality: a new ci
    job that nobody added here would be a gate the release never checked, and a
    renamed job would be checked as "missing" and fail loudly (never silently).
    """
    script = _script(_job(release, "prior-gates"))
    # The `required=( … )` array: one quoted check name per line, optionally
    # followed by a comment naming the gate it carries.
    required = {
        match.group(1)
        for match in (re.match(r'^\s*"([^"]+)"\s*(#.*)?$', line) for line in script.splitlines())
        if match is not None
    }
    assert required == _ci_check_names(), (
        f"release.yml requires {sorted(required)};\nci.yml publishes {sorted(_ci_check_names())}"
    )


def test_the_gate_job_waits_for_every_lane(release: dict[str, Any]) -> None:
    gate = _job(release, "release-gate")
    assert set(gate["needs"]) == {
        "wheelhouse",
        "lane-a",
        "lane-b",
        "lane-c",
        "lane-d",
        "prior-gates",
    }


def test_the_gate_job_checks_docs_and_the_leaderboard(
    release: dict[str, Any],
) -> None:
    script = _script(_job(release, "release-gate"))
    assert "scripts/docs_check.py" in script  # docs build without warnings
    assert "license_headers.py --check" in script  # Apache-2.0 headers
    assert "heph bench leaderboard --check" in script  # the page is current


def test_the_gate_verifies_the_tag_without_creating_it(
    release: dict[str, Any],
) -> None:
    """Tagging is the maintainer's act; CI proves the tag would be coherent."""
    steps = _steps(_job(release, "release-gate"))
    tag_step = [s for s in steps if "tag" in str(s.get("name", ""))]
    assert tag_step, "nothing checks the tag against the built version"
    assert tag_step[0]["if"] == "startsWith(github.ref, 'refs/tags/')"
    assert "does not match built version" in str(tag_step[0]["run"])


# --------------------------------------------------------------------------
# bench.yml


def test_bench_runs_on_dispatch_and_a_weekly_schedule(bench: dict[str, Any]) -> None:
    """verification.md: "manual dispatch + weekly schedule (API cost control)"."""
    triggers = bench[ON]
    assert "workflow_dispatch" in triggers
    crons = [entry["cron"] for entry in triggers["schedule"]]
    assert crons and all(len(c.split()) == 5 for c in crons)
    assert all(c.split()[4] != "*" for c in crons), "that is a daily schedule"


def test_bench_publishes_the_leaderboard_artifact(bench: dict[str, Any]) -> None:
    """The clause G7H names verbatim."""
    job = _job(bench, "leaderboard")
    uploads = [
        s for s in _steps(job) if str(s.get("uses", "")).startswith("actions/upload-artifact")
    ]
    assert uploads, "bench.yml publishes no leaderboard artifact"
    assert uploads[0]["with"]["name"] == "leaderboard"
    assert uploads[0]["with"]["if-no-files-found"] == "error"


def test_the_leaderboard_job_needs_no_credentials(bench: dict[str, Any]) -> None:
    """It reads committed artifacts. A scheduled run must not need a key, or the
    weekly signal quietly dies the first time a secret rotates."""
    job = _job(bench, "leaderboard")
    assert "secrets." not in json.dumps(job)


def test_the_leaderboard_job_checks_the_committed_page(bench: dict[str, Any]) -> None:
    script = _script(_job(bench, "leaderboard"))
    assert "heph bench leaderboard --check" in script


def test_bench_never_writes_the_archive_from_ci(bench: dict[str, Any]) -> None:
    """VALIDATION.md §8: leaderboard rows are transcribed from *archived*
    artifacts. CI publishes evidence; a human commits history."""
    text = BENCH.read_text()
    assert "git commit" not in text and "git push" not in text
    assert "--results-dir" in text
    corpus = _script(_job(bench, "corpus"))
    assert "$RUNNER_TEMP/results" in corpus, "the corpus job writes into bench/results/"


def test_the_paid_corpus_job_only_runs_when_a_dispatcher_opts_in(
    bench: dict[str, Any],
) -> None:
    condition = str(_job(bench, "corpus")["if"])
    assert "workflow_dispatch" in condition
    assert "inputs.run_corpus" in condition
    assert "inputs.model" in condition


def test_the_corpus_job_builds_the_sidecar_it_spawns(bench: dict[str, Any]) -> None:
    script = _script(_job(bench, "corpus"))
    assert "pnpm --dir agent run bundle" in script
    assert "scripts/stage_sidecar.py" in script
    assert "bubblewrap" in script, "bench builds must run under the secure executor"
