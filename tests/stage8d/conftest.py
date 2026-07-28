"""Fixtures for the Gate G8D (external evaluation) evidence suite.

One heavy fixture — the packaged Node sidecar the FakeModel run clause drives —
built once per session and skipped cleanly when Node is not available, exactly
as the G8A/G8B suites do it. Everything else in this suite is pure and offline.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def sidecar_dist() -> Path:
    """Build the packaged sidecar once; skip cleanly when Node is absent."""
    from hephaestus.agent_bridge.app import repo_root

    if not (os.environ.get("HEPHAESTUS_NODE") or shutil.which("node")):
        pytest.skip("node is not available; the run clause needs the packaged sidecar")
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
