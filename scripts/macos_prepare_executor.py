# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Development-only native image preparation; called by the milestone harness."""

from __future__ import annotations

import hashlib
import json
import secrets
import shutil
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from macos_milestone_smoke import Smoke


def prepare(smoke: Smoke) -> str:
    from macos_milestone_smoke import ROOT
    from macos_preparation import prepare_files

    staging = smoke.directory / "download"
    prepare_files(smoke, "package", staging / "local-wheels", staging / "wheels")
    smoke.report["executor_source_manifest"] = "prepare-package/inputs-sha256.json"
    context = smoke.directory / "image-context"
    shutil.copytree(
        ROOT / "docker/executor",
        context / "docker/executor",
        ignore=shutil.ignore_patterns("package", "__pycache__"),
    )
    shutil.copytree(staging / "wheels", context / "dist/executor-wheelhouse")
    for path in (staging / "local-wheels").iterdir():
        with (context / "dist/executor-wheelhouse" / path.name).open("xb") as target:
            target.write(path.read_bytes())
    native_cache = ROOT / "dist/macos-executor-native"
    if native_cache.is_dir():
        shutil.copytree(native_cache, context / "dist/executor-native")
    smoke.command(
        (
            sys.executable,
            str(ROOT / "docker/executor/fetch_native_runtime.py"),
            "arm64",
            str(context / "dist/executor-native"),
        ),
        timeout=180,
    )
    if not native_cache.exists():
        shutil.copytree(context / "dist/executor-native", native_cache)
    inputs = {
        str(path.relative_to(context)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(context.rglob("*"))
        if path.is_file()
    }
    (smoke.directory / "executor-image-inputs-sha256.json").write_text(
        json.dumps(inputs, indent=2) + "\n"
    )
    smoke.report["executor_image_inputs_manifest"] = "executor-image-inputs-sha256.json"
    tag = "hephaestus-macos-experimental:" + secrets.token_hex(16)
    smoke.report["experimental_image_tag"] = tag
    smoke.report["owned_image_tags"].append(tag)
    smoke.save()
    # RUN commands are trusted offline installers, not CAD workers. Bound each
    # process's data segment/CPU and aggregate build wall time; serial build.
    smoke.command(
        (
            *smoke.docker,
            "build",
            "--platform",
            "linux/arm64",
            "--network",
            "none",
            "--ulimit",
            "data=2147483648:2147483648",
            "--ulimit",
            "cpu=120:120",
            "--ulimit",
            "nproc=256:256",
            "--progress",
            "plain",
            "--pull=false",
            "-f",
            str(context / "docker/executor/Dockerfile"),
            "-t",
            tag,
            str(context),
        ),
        timeout=360,
    )
    smoke.check("executor_image", "passed", "native existing executor Dockerfile built offline")
    return tag


if __name__ == "__main__":
    raise SystemExit("Use macos_milestone_smoke.sh; this helper owns no standalone lifecycle")
