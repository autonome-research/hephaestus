# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""The onboarding path is code, and code that nothing runs is code that rots.

J-mirrors-and-dx-32. ``scripts/bootstrap.sh`` and ``scripts/heph`` are the very
first commands a new contributor runs — five documents say so — and no workflow
and no test referenced either of them. CI never walked that path because CI does
its own setup (a Python sync plus a pnpm action), so the two setup routes had no
point of contact at all. That is exactly the gap that produced
J-mirrors-and-dx-25, where the documented bootstrap left every sidecar-backed
test skipping in silence.

Two CI lanes carry the expensive half: the docs job runs the script's ``--check``
mode on every change, and a dedicated bare-checkout job runs the whole thing and
then asserts that a sidecar-backed suite passes rather than skips. This module
holds the cheap half — the launcher's clone resolution, which is pure path logic
and needs no toolchain — plus the structural assertions that keep those two
lanes from quietly disappearing.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
LAUNCHER = REPO / "scripts" / "heph"
VENV_HEPH = REPO / ".venv" / "bin" / "heph"
BOOTSTRAP = REPO / "scripts" / "bootstrap.sh"
CI = REPO / ".github" / "workflows" / "ci.yml"


def _ci() -> dict[str, Any]:
    doc = yaml.safe_load(CI.read_text(encoding="utf-8"))
    assert isinstance(doc, dict)
    return doc


def _script(job: dict[str, Any]) -> str:
    return "\n".join(
        str(step["run"])
        for step in job.get("steps", [])
        if isinstance(step, dict) and "run" in step
    )


# --------------------------------------------------------------------------
# the launcher's clone resolution


@pytest.fixture(autouse=True)
def _require_launcher() -> None:
    assert LAUNCHER.is_file(), f"{LAUNCHER} is missing"
    assert os.access(LAUNCHER, os.X_OK), f"{LAUNCHER} is not executable"


def test_the_launcher_resolves_through_a_multi_hop_symlink_chain(tmp_path: Path) -> None:
    """Three hops, in three different directories, ending far from the repo —
    the shape the script's own header comment names (`ln -s .../heph ~/bin/heph`).

    The launcher must resolve the CLONE from its own location rather than from
    any symlink's, and from any working directory — that is the whole
    difference between it and `uv run heph`, which needs the clone as cwd. This
    drives the REAL script (not a reimplementation of its logic).
    """
    if not VENV_HEPH.is_file():
        pytest.skip(f"{VENV_HEPH} is missing; build the checkout first (scripts/bootstrap.sh)")

    hop1 = tmp_path / "a" / "heph"
    hop1.parent.mkdir(parents=True)
    hop1.symlink_to(LAUNCHER)

    hop2 = tmp_path / "b" / "heph"
    hop2.parent.mkdir(parents=True)
    hop2.symlink_to(hop1)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    entry = bin_dir / "heph"
    entry.symlink_to(hop2)

    # Run from a cwd that is nowhere near the clone — the whole point of the
    # launcher over `uv run heph`, per its own header comment.
    outside_cwd = tmp_path / "elsewhere"
    outside_cwd.mkdir()

    direct = subprocess.run(
        [str(VENV_HEPH), "--version"], capture_output=True, text=True, check=False
    )
    via_symlink = subprocess.run(
        [str(entry), "--version"],
        capture_output=True,
        text=True,
        cwd=str(outside_cwd),
        check=False,
    )
    assert via_symlink.returncode == direct.returncode, via_symlink.stderr
    assert via_symlink.stdout == direct.stdout, (
        "the symlinked launcher's output differs from running .venv/bin/heph directly — "
        f"it resolved to a different checkout or binary.\nsymlink stdout: {via_symlink.stdout!r}\n"
        f"direct stdout: {direct.stdout!r}"
    )


def test_the_launcher_names_the_build_command_when_the_venv_binary_is_absent(
    tmp_path: Path,
) -> None:
    """The one failure path the script itself handles: a clone that was never
    built. It must fail with its own named remedy, not a raw "command not
    found" from the final `exec`."""
    fake_repo = tmp_path / "fake-clone"
    (fake_repo / "scripts").mkdir(parents=True)
    (fake_repo / ".venv" / "bin").mkdir(parents=True)  # no `heph` binary inside
    fake_launcher = fake_repo / "scripts" / "heph"
    fake_launcher.write_text(LAUNCHER.read_text(encoding="utf-8"), encoding="utf-8")
    fake_launcher.chmod(0o755)

    proc = subprocess.run(
        [str(fake_launcher), "--version"], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 1, (proc.returncode, proc.stdout, proc.stderr)
    assert "bootstrap.sh" in proc.stderr, proc.stderr
    assert str(fake_repo / ".venv" / "bin" / "heph") in proc.stderr, proc.stderr


# --------------------------------------------------------------------------
# the two lanes


def test_the_documentation_job_runs_the_bootstraps_check_mode() -> None:
    script = _script(_ci()["jobs"]["docs"])
    assert "bootstrap.sh --check" in script, (
        "the docs job no longer runs the bootstrap's check mode, so a broken "
        "prerequisite table can land again (J-mirrors-and-dx-32)"
    )


def test_a_bare_checkout_lane_runs_the_whole_script() -> None:
    job = _ci()["jobs"]["bootstrap"]
    uses = [str(step["uses"]) for step in job.get("steps", []) if "uses" in step]
    assert not any("setup-uv" in entry for entry in uses), (
        "the bootstrap lane pre-installs uv, so it no longer tests the path a "
        "human walks — the point of the lane is a BARE checkout"
    )
    assert not any("pnpm/action-setup" in entry for entry in uses), (
        "the bootstrap lane pre-installs pnpm, which is precisely the thing the "
        "script is responsible for resolving"
    )
    script = _script(job)
    assert "./scripts/bootstrap.sh" in script
    assert "pytest" in script, (
        "the lane runs the script and asserts nothing. The criterion that "
        "matters is that a sidecar-backed suite PASSES afterwards"
    )
    assert job.get("env", {}).get("HEPHAESTUS_REQUIRE_SIDECAR") == "1", (
        "without the require variable the closing suite can skip every "
        "sidecar-backed assertion and the lane still goes green — which is "
        "exactly the J-mirrors-and-dx-25 failure it exists to catch"
    )


def test_every_job_that_installs_node_requires_the_sidecar() -> None:
    """A skip on a machine that installed the toolchain is a regression."""
    missing: list[str] = []
    for job_id, job in _ci()["jobs"].items():
        steps = job.get("steps", [])
        uses = [str(step["uses"]) for step in steps if isinstance(step, dict) and "uses" in step]
        installs_node = any("setup-node" in entry for entry in uses)
        runs_python = "pytest" in _script(job)
        if not (installs_node and runs_python):
            continue
        if job.get("env", {}).get("HEPHAESTUS_REQUIRE_SIDECAR") != "1":
            missing.append(str(job_id))
    assert not missing, (
        f"these jobs install Node and run pytest without HEPHAESTUS_REQUIRE_SIDECAR=1, "
        f"so a bridge suite that stopped running would skip in silence: {missing}"
    )


def test_the_bootstrap_records_the_pnpm_route_the_guards_read() -> None:
    """The reconciliation is a FILE, not two implementations agreeing by luck."""
    from hephaestus.testing import sidecar as helper

    text = BOOTSTRAP.read_text(encoding="utf-8")
    record = helper._BOOTSTRAP_RECORD
    assert record.rsplit("/", 1)[-1] in text, (
        f"scripts/bootstrap.sh no longer writes {record}, which "
        "hephaestus.testing.sidecar.pnpm_command() reads before doing its own "
        "resolution (J-mirrors-and-dx-25)"
    )
