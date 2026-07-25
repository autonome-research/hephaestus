"""Locating and building the packaged Node sidecar a bridge harness drives.

Every end-to-end bridge test must run the artifact a release would ship —
``agent/dist/main.js`` and ``agent/dist/workflows/runner.js`` built by ``pnpm
build`` — never a globally installed ``pi``/``thread-phase``. This module owns
that build: :func:`build_agent_dist` runs it at most once per process and
returns ``None`` when Node or pnpm is absent, leaving the *skip vs fail* policy
to each suite, but raises when the toolchain is present and the build is broken
so a gate can never pass by silently skipping a broken sidecar.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from hephaestus.agent_bridge.app import repo_root

__all__ = [
    "agent_dir",
    "build_agent_dist",
    "node_available",
    "node_executable",
    "sidecar_main",
    "workflow_runner_main",
]


def node_executable() -> str | None:
    """The Node binary to spawn the sidecar with, or ``None`` when absent."""
    return os.environ.get("HEPHAESTUS_NODE") or shutil.which("node")


def node_available() -> bool:
    """Whether a Node binary can be found at all."""
    return bool(node_executable())


def agent_dir() -> Path:
    """The ``agent/`` workspace holding the sidecar sources and its ``dist``."""
    return repo_root() / "agent"


def sidecar_main() -> Path:
    """The built sidecar entry the supervisor spawns."""
    return agent_dir() / "dist" / "main.js"


def workflow_runner_main() -> Path:
    """The built workflow runner entry the workflow supervisor spawns."""
    return agent_dir() / "dist" / "workflows" / "runner.js"


_DIST_CACHE: list[tuple[Path, Path] | None] = []


def build_agent_dist() -> tuple[Path, Path] | None:
    """Build ``agent/dist`` once and return ``(main.js, workflows/runner.js)``.

    Returns ``None`` when Node or pnpm is unavailable (the caller decides
    whether that is a skip), and fails loudly when the build itself is broken.
    The result is cached for the process so a whole suite pays for at most one
    ``pnpm build``.
    """
    if _DIST_CACHE:
        return _DIST_CACHE[0]
    result = _build_agent_dist()
    _DIST_CACHE.append(result)
    return result


def _build_agent_dist() -> tuple[Path, Path] | None:
    if node_executable() is None:
        return None
    pnpm = shutil.which("pnpm")
    if pnpm is None:
        return None
    build = subprocess.run(
        [pnpm, "--dir", str(agent_dir()), "build"],
        capture_output=True,
        text=True,
        check=False,
    )
    main = sidecar_main()
    runner = workflow_runner_main()
    if build.returncode != 0 or not main.exists() or not runner.exists():
        raise AssertionError(f"sidecar build failed:\n{build.stdout}\n{build.stderr}")
    return main, runner
