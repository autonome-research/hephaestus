# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""Locating and building the packaged Node sidecar a bridge harness drives.

Every end-to-end bridge test must run the artifact a release would ship — never
a globally installed ``pi``/``thread-phase``. Through Stage 7G that artifact was
``agent/dist/`` from a plain ``tsc`` build, which is *not* what ships: ``dist/``
resolves four bare specifiers by walking up into ``agent/node_modules``, so it
could only ever run inside the repo. The wheel ships the bundled, integrity-
manifested sidecar instead, and this module now builds and stages exactly that,
so an in-repo suite and a wheel install exercise the same bytes.

:func:`build_agent_dist` runs the build at most once per process and returns
``None`` when Node or pnpm is absent, leaving the *skip vs fail* policy to each
suite, but raises when the toolchain is present and the build is broken so a
gate can never pass by silently skipping a broken sidecar.

In an installed wheel there is no ``agent/`` tree and no pnpm. The build
functions report that honestly (``None``); :func:`sidecar_main` and
:func:`workflow_runner_main` keep working, because they ask the resolver, which
finds the packaged sidecar.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from hephaestus.agent_bridge.app import repo_root
from hephaestus.agent_bridge.sidecar import (
    NodeVersionError,
    SidecarError,
    resolve_sidecar,
)
from hephaestus.agent_bridge.sidecar import (
    node_executable as _checked_node_executable,
)

__all__ = [
    "agent_dir",
    "build_agent_dist",
    "node_available",
    "node_executable",
    "sidecar_main",
    "sidecar_root",
    "workflow_runner_main",
]


def node_executable() -> str | None:
    """The Node binary to spawn the sidecar with, or ``None`` when unusable.

    Folds in the ≥22.19 compatibility check: a Node too old to run the sidecar
    is reported the same as no Node at all, so a suite skips rather than failing
    with an unexplained child crash.
    """
    try:
        return _checked_node_executable()
    except NodeVersionError:
        return None


def node_available() -> bool:
    """Whether a compatible Node binary can be found at all."""
    return bool(node_executable())


def agent_dir() -> Path:
    """The ``agent/`` workspace holding the sidecar sources (source tree only)."""
    return repo_root() / "agent"


def sidecar_root() -> Path:
    """The root of the verified sidecar tree this installation would spawn."""
    return resolve_sidecar().root


def sidecar_main() -> Path:
    """The built sidecar entry the supervisor spawns."""
    return resolve_sidecar().main


def workflow_runner_main() -> Path:
    """The built workflow runner entry the workflow supervisor spawns."""
    return resolve_sidecar().runner


_DIST_CACHE: list[tuple[Path, Path] | None] = []


def build_agent_dist() -> tuple[Path, Path] | None:
    """Build+stage the sidecar once and return ``(main.js, workflows/runner.js)``.

    Returns ``None`` when the toolchain or the source tree is unavailable (the
    caller decides whether that is a skip), and fails loudly when the build
    itself is broken. The result is cached for the process so a whole suite pays
    for at most one bundle.
    """
    if _DIST_CACHE:
        return _DIST_CACHE[0]
    result = _build_agent_dist()
    _DIST_CACHE.append(result)
    return result


def _run(argv: list[str], *, what: str) -> None:
    proc = subprocess.run(argv, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise AssertionError(f"{what} failed:\n{proc.stdout}\n{proc.stderr}")


def _build_agent_dist() -> tuple[Path, Path] | None:
    if node_executable() is None:
        return None
    pnpm = shutil.which("pnpm")
    if pnpm is None:
        return None
    agent = agent_dir()
    stage_script = repo_root() / "scripts" / "stage_sidecar.py"
    if not agent.is_dir() or not stage_script.is_file():
        # An installed wheel: nothing to build. Whatever is packaged is what runs.
        return None
    if os.environ.get("HEPHAESTUS_SKIP_SIDECAR_BUILD") != "1":
        _run([pnpm, "--dir", str(agent), "run", "bundle"], what="sidecar bundle")
        _run([sys.executable, str(stage_script)], what="sidecar staging")
    try:
        resolution = resolve_sidecar()
    except SidecarError as exc:  # pragma: no cover - a broken build must be loud
        raise AssertionError(f"sidecar unusable after build: {exc}") from exc
    return resolution.main, resolution.runner
