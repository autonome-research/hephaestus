# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Fixed trusted preparation recipes; not a CAD launcher or module trampoline."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

# The host snapshots ONLY these stdlib transfer modules and this fixed recipe.
# -I ignores host/PYTHONPATH/user-site configuration. No arbitrary module option.
sys.path.insert(0, "/inputs/code")

from hephaestus.core.executor.sandbox.oci_transfer import _export, unique_json
from macos_preparation_transfer import BOUNDS, PreparationSchema, records


def recipe(route: str) -> list[tuple[str, ...]]:
    python = "/usr/local/bin/python"
    pip = (python, "-I", "-m", "pip", "--isolated", "--disable-pip-version-check")
    if route in {"download", "download-cache"}:
        source = (
            ("--index-url", "https://pypi.org/simple")
            if route == "download"
            else ("--no-index", "--find-links=/inputs/cache")
        )
        return [
            (
                *pip,
                "download",
                *source,
                "--no-cache-dir",
                "--only-binary=:all:",
                "--require-hashes",
                "--timeout",
                "20",
                "--retries",
                "1",
                "--dest",
                "/work/wheels",
                "-r",
                "/inputs/requirements.lock",
                "-r",
                "/inputs/build-requirements.lock",
            )
        ]
    if route != "package":
        raise ValueError("unknown preparation recipe")
    venv = "/work/venv/bin/python"
    return [
        (python, "-I", "-m", "venv", "/work/venv"),
        (
            venv,
            "-I",
            "-m",
            "pip",
            "--isolated",
            "--disable-pip-version-check",
            "install",
            "--no-index",
            "--find-links=/inputs/wheels",
            "--require-hashes",
            "--only-binary=:all:",
            "-r",
            "/inputs/build-requirements.lock",
        ),
        (
            venv,
            "-I",
            "-m",
            "pip",
            "--isolated",
            "--disable-pip-version-check",
            "wheel",
            "--no-index",
            "--no-deps",
            "--no-build-isolation",
            "--no-cache-dir",
            "--wheel-dir=/work/wheels",
            "/work/source/docker/executor/package",
            "/work/source/opstore",
        ),
    ]


def main() -> None:
    if len(sys.argv) != 3:
        raise ValueError("preparation route and nonce required")
    route, nonce = sys.argv[1:]
    with Path("/inputs/packages.json").open("rb") as stream:
        raw = stream.read(65537)
    if len(raw) > 65536:
        raise ValueError("preparation spec byte bound")
    packages = unique_json(raw)
    if not isinstance(packages, dict):
        raise ValueError("packages schema")
    schema = PreparationSchema(route, packages)
    operation = "preparation-v1/" + route
    schema.identity(nonce, operation)
    commands = recipe(route)  # closed before any source copy/process launch
    Path("/work/wheels").mkdir()
    if route == "package":
        # Read-only admitted snapshot copied into kernel-bounded scratch for
        # hatch's source staging. Neither pip nor a build hook can write host files.
        shutil.copytree("/inputs/source", "/work/source")
    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": "/tmp",
        "TMPDIR": "/tmp",
        "SOURCE_DATE_EPOCH": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    for command in commands:
        subprocess.run(
            command, check=True, stdout=sys.stderr, stderr=sys.stderr, env=env, timeout=280
        )
    files = records(Path("/work/wheels"), schema)
    _export(
        sys.stdout.buffer,
        {"files": {k: v.sha256 for k, v in files.items()}},
        nonce,
        operation,
        Path("/work/wheels"),
        BOUNDS,
        schema,
    )
    # The footer has been flushed while tmpfs still exists. No docker cp/recovery.


if __name__ == "__main__":
    main()
