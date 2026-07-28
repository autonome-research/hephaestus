"""Fixtures for the Gate G8A (ingest) evidence suite.

Two heavy fixtures, both session-scoped: the STEP fixture bytes (authored once
because OCCT stamps a timestamp into the header, and identical bytes are the
whole point) and the packaged Node sidecar the two bench clauses drive.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from _g8a import StepFixtures, make_step_fixtures
from hephaestus.testing.tools_fixture import Project, make_project


@pytest.fixture(scope="session")
def steps(tmp_path_factory: pytest.TempPathFactory) -> StepFixtures:
    return make_step_fixtures(tmp_path_factory.mktemp("step-fixtures"))


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Project]:
    """A real project + dispatcher, ledger seeded so builds are not gated."""
    p = make_project(tmp_path / "proj")
    try:
        yield p
    finally:
        p.close()


@pytest.fixture
def bare_project(tmp_path: Path) -> Iterator[Project]:
    """The same, with no ledger: for the clauses whose subject *is* the ledger."""
    p = make_project(tmp_path / "proj", seed_ledger=False)
    try:
        yield p
    finally:
        p.close()


@pytest.fixture(scope="session")
def sidecar_dist() -> Path:
    """Build the packaged sidecar once; skip cleanly when Node is absent."""
    from hephaestus.agent_bridge.app import repo_root

    if not (os.environ.get("HEPHAESTUS_NODE") or shutil.which("node")):
        pytest.skip("node is not available; the bench clauses need the packaged sidecar")
    pnpm = shutil.which("pnpm")
    if pnpm is None:
        pytest.skip("pnpm is not available; cannot build the sidecar")
    agent_dir = repo_root() / "agent"
    build = subprocess.run(
        [pnpm, "--dir", str(agent_dir), "build"], capture_output=True, text=True, check=False
    )
    dist_main = agent_dir / "dist" / "main.js"
    if build.returncode != 0 or not dist_main.exists():
        pytest.fail(f"sidecar build failed:\n{build.stdout}\n{build.stderr}")
    return dist_main
