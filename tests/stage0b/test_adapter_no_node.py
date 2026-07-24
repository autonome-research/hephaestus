"""G0B clause: engine-first — ``heph build`` works with Node absent.

Runs ``heph build <assembly>/parts/primary.py --json`` in a subprocess whose
PATH contains no directory providing ``node``/``npm``/``pnpm``/``npx``.
It must exit 0 and print a BuildResult JSON object that validates against
``core/schemas/build_result.schema.json``.

The public assembly fixture is copied into a tmp project first so the build
artifacts (``.heph/``) never land inside the corpus tree.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import jsonschema
from _adapter_helpers import REPO_ROOT

FIXTURE = REPO_ROOT / "corpus" / "public_fixtures" / "assembly"
SCHEMA_PATH = REPO_ROOT / "core" / "schemas" / "build_result.schema.json"
NODE_NAMES = ("node", "npm", "pnpm", "npx")


def _node_free_path(shim_root: Path) -> str:
    """The current PATH with every Node toolchain entry removed.

    Directories that only provide Node tools are dropped outright. A
    directory that mixes Node with other tools (e.g. ``/usr/bin``) is
    replaced by a symlink farm under ``shim_root`` that omits the Node
    executables — everything else (bwrap, sh, ...) stays reachable.
    """
    kept: list[str] = []
    for index, entry in enumerate(os.environ.get("PATH", "").split(os.pathsep)):
        if not entry:
            continue
        directory = Path(entry)
        if not any((directory / name).exists() for name in NODE_NAMES):
            kept.append(entry)
            continue
        others = (
            [item for item in directory.iterdir() if item.name not in NODE_NAMES]
            if directory.is_dir()
            else []
        )
        if not others:
            continue  # a pure Node directory: drop it
        shim = shim_root / f"path-shim-{index}"
        shim.mkdir(parents=True)
        for item in others:
            (shim / item.name).symlink_to(item)
        kept.append(str(shim))
    return os.pathsep.join(kept)


def _heph_executable() -> str:
    """The installed ``heph`` console script (same venv as this interpreter)."""
    candidate = Path(sys.executable).parent / "heph"
    assert candidate.is_file(), f"heph console script not found at {candidate}"
    return str(candidate)


def test_build_json_with_node_absent_validates_against_schema(
    tmp_path: Path,
) -> None:
    project = tmp_path / "assembly"
    shutil.copytree(FIXTURE, project, ignore=shutil.ignore_patterns(".heph"))
    path = _node_free_path(tmp_path / "shims")
    env = {**os.environ, "PATH": path}
    # The stripped PATH really has no node toolchain.
    for name in NODE_NAMES:
        assert shutil.which(name, path=path) is None, f"{name} still reachable"

    result = subprocess.run(
        [_heph_executable(), "build", str(project / "parts" / "primary.py"), "--json"],
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, (
        f"heph build failed with node absent (exit {result.returncode}):\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )

    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert lines, "no JSON output on stdout"
    payload = json.loads(lines[-1])
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)  # raises on any violation
    assert payload["part"] == "primary"
    assert payload["status"] == "ok"
    assert payload["current"] is True
    assert payload["artifact_ref"], "successful build must carry an artifact ref"
