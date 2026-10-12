# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Development-only native image preparation; called by the milestone harness."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from macos_milestone_smoke import Smoke

PREPARE = """set -eu
python -m venv /work/venv
/work/venv/bin/python -m pip --isolated --disable-pip-version-check install \
  --no-index --find-links=/work/wheels --require-hashes -r /work/build-requirements.lock
export SOURCE_DATE_EPOCH=0
/work/venv/bin/python -m pip --isolated --disable-pip-version-check wheel \
  --no-index --no-deps --no-build-isolation --wheel-dir=/work/wheels \
  /work/source/docker/executor/package /work/source/opstore
python /work/source/docker/executor/write_local_lock.py /work/wheels
"""


def prepare(smoke: Smoke) -> str:
    from macos_milestone_smoke import BASE, ROOT, StageFailure

    staging = smoke.directory / "download"
    source = staging / "source"
    for relative in ("core/src", "opstore/src", "docker/executor/package"):
        shutil.copytree(
            ROOT / relative,
            source / relative,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".venv", "dist", "src")
            if relative == "docker/executor/package"
            else shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
    for relative in (
        "opstore/pyproject.toml",
        "schemas/bridge_limits.json",
        "docker/executor/write_local_lock.py",
    ):
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    source_hashes = {
        str(path.relative_to(source)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(source.rglob("*"))
        if path.is_file()
    }
    (smoke.directory / "executor-source-sha256.json").write_text(
        json.dumps(source_hashes, indent=2) + "\n"
    )
    smoke.report["executor_source_manifest"] = "executor-source-sha256.json"
    smoke.save()
    name = "heph-macos-package-" + secrets.token_hex(16)
    smoke.owned.append(name)
    smoke.save()
    smoke.command(
        (
            *smoke.docker,
            "create",
            "--name",
            name,
            "--platform",
            "linux/arm64",
            "--pull=never",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--read-only",
            "--log-driver=none",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges=true",
            "--network",
            "none",
            "--ipc",
            "none",
            "--memory",
            "1g",
            "--memory-swap",
            "1g",
            "--cpus",
            "1",
            "--pids-limit",
            "128",
            "--ulimit",
            "cpu=120:120",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,noexec,size=268435456",
            "--mount",
            f"type=bind,source={staging},destination=/work",
            "--workdir",
            "/work",
            BASE,
            "/bin/sh",
            "-c",
            PREPARE,
        )
    )
    smoke.command((*smoke.docker, "start", "--attach", name), timeout=180, require=False)
    _, raw = smoke.command((*smoke.docker, "inspect", "--format", "{{json .State}}", name))
    state = json.loads(raw)
    if state["Running"] or state["ExitCode"] != 0 or state.get("OOMKilled"):
        raise StageFailure("offline local wheel build failed")
    context = smoke.directory / "image-context"
    shutil.copytree(
        ROOT / "docker/executor",
        context / "docker/executor",
        ignore=shutil.ignore_patterns("package", "__pycache__"),
    )
    shutil.copytree(staging / "wheels", context / "dist/executor-wheelhouse")
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
