# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Development-only bounded preparation/export shared by all Mac image routes."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import signal
import tomllib
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING

from hephaestus.core.deadline import Deadline
from hephaestus.core.executor.sandbox.oci_storage_policy import MQUEUE_MASK
from hephaestus.core.executor.sandbox.oci_transfer import _Receiver, encode, unique_json
from macos_preparation_transfer import (
    BOUNDS,
    FILE_BYTES,
    TMP_BYTES,
    TMP_INODES,
    WORK_BYTES,
    WORK_INODES,
    PreparationSchema,
    mkdir_private,
    snapshot,
)

if TYPE_CHECKING:
    from macos_milestone_smoke import Smoke

ROOT = Path(__file__).resolve().parents[1]
WIRE = "hephaestus/core/executor/sandbox"


def locked_packages(inputs: Path) -> dict[str, dict]:
    # Deliberately not a general requirements/marker evaluator. These are the
    # complete marker expressions in the existing locks, evaluated for the
    # pinned Linux/aarch64 base. Unknown grammar requires review, never eval or
    # Darwin defaults. Keep the standalone Homebrew-Python harness stdlib-only.
    markers = {
        "": True,
        "sys_platform == 'win32'": False,
        "platform_machine != 'aarch64' or sys_platform != 'linux'": False,
        "sys_platform != 'emscripten' and sys_platform != 'win32'": True,
        "sys_platform != 'cygwin' and sys_platform != 'emscripten'": True,
        "platform_machine == 'aarch64' and sys_platform == 'linux'": True,
    }
    packages = {}
    for leaf in ("requirements.lock", "build-requirements.lock"):
        with (inputs / leaf).open("rb") as stream:
            raw = stream.read(128 * 1024 + 1)
        if len(raw) > 128 * 1024:
            raise ValueError("preparation lock byte bound")
        text = raw.decode("utf-8")
        for line in text.replace("\\\n", " ").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            requirement, *hashes = line.split("--hash=sha256:")
            requirement, _, marker = requirement.partition(";")
            marker = " ".join(marker.split())
            match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.!+]+)", requirement.strip())
            hashes = [h.strip() for h in hashes]
            if (
                match is None
                or marker not in markers
                or not hashes
                or any(re.fullmatch(r"[0-9a-f]{64}", h) is None for h in hashes)
            ):
                raise ValueError("preparation requires reviewed exact hash-locked requirements")
            if not markers[marker]:
                continue
            distribution, version = match.groups()
            name = re.sub(r"[-_.]+", "_", distribution).lower()
            item = {"version": version, "hashes": hashes}
            if name in packages and packages[name] != item:
                raise ValueError("conflicting preparation locks")
            if name not in packages and len(packages) >= 128:
                raise ValueError("preparation package count")
            packages[name] = item
    return packages


def input_sources(route: str, wheels: Path | None) -> dict[str, Path]:
    # No project, home, socket or arbitrary worker/module mounts. Even source
    # packaging receives only the explicitly enumerated supply-chain trees.
    sources = {
        "requirements.lock": ROOT / "docker/executor/requirements.lock",
        "build-requirements.lock": ROOT / "docker/executor/build-requirements.lock",
        "code/macos_preparation_worker.py": ROOT / "scripts/macos_preparation_worker.py",
        "code/macos_preparation_transfer.py": ROOT / "scripts/macos_preparation_transfer.py",
    }
    for module in ("oci_transfer.py", "oci_protocol.py", "oci_storage_policy.py"):
        sources[f"code/{WIRE}/{module}"] = ROOT / f"core/src/{WIRE}/{module}"
    if route == "package":
        if wheels is None:
            raise ValueError("source packaging requires verified wheels")
        sources["wheels"] = wheels
        for relative in (
            "core/src",
            "opstore/src",
            "opstore/pyproject.toml",
            "schemas/bridge_limits.json",
            "docker/executor/package/pyproject.toml",
            "docker/executor/package/hatch_build.py",
        ):
            sources["source/" + relative] = ROOT / relative
    elif route == "download-cache":
        if wheels is None:
            raise ValueError("cache route requires cache")
        sources["cache"] = wheels
    elif route != "download" or wheels is not None:
        raise ValueError("unknown preparation inputs")
    return sources


def create_argv(smoke: Smoke, route: str, name: str, inputs: Path, nonce: str) -> tuple[str, ...]:
    from macos_milestone_smoke import BASE

    if route not in {"download", "download-cache", "package"}:
        raise ValueError("preparation route")
    if any(c in str(inputs) for c in (",", "\n", "\r", "\0")):
        raise ValueError("unsafe snapshot mount path")
    return (
        *smoke.docker,
        "create",
        "--name",
        name,
        "--label",
        "org.hephaestus.macos-feasibility=preparation",
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
        "bridge" if route == "download" else "none",
        "--ipc",
        "none",
        "--memory",
        "1536m",
        "--memory-swap",
        "1536m",
        "--cpus",
        "1",
        "--pids-limit",
        "128",
        "--ulimit",
        "cpu=120:120" if route == "package" else "cpu=240:240",
        "--ulimit",
        f"fsize={FILE_BYTES}:{FILE_BYTES}",
        "--ulimit",
        "nofile=1024:1024",
        "--shm-size",
        "4k",
        "--tmpfs",
        (
            f"/work:rw,nosuid,nodev,noexec,size={WORK_BYTES},nr_inodes={WORK_INODES},"
            f"mode=0700,uid={os.getuid()},gid={os.getgid()}"
        ),
        "--tmpfs",
        f"/tmp:rw,nosuid,nodev,noexec,size={TMP_BYTES},nr_inodes={TMP_INODES}",
        "--tmpfs",
        "/dev/mqueue:" + MQUEUE_MASK,
        "--mount",
        f"type=bind,source={inputs},destination=/inputs,readonly,bind-recursive=disabled",
        "--workdir",
        "/work",
        BASE,
        "/usr/local/bin/python",
        "-I",
        "/inputs/code/macos_preparation_worker.py",
        route,
        nonce,
    )


def remove_owned(smoke: Smoke, name: str) -> None:
    """Separate finite cleanup budget, including when work expires/is cancelled."""
    old = {sig: signal.signal(sig, signal.SIG_IGN) for sig in (signal.SIGINT, signal.SIGTERM)}
    previous = smoke.cleanup_deadline
    smoke.cleanup_deadline = Deadline.after(30)
    try:
        record = smoke.report.get("build_ownership", {}).get(name, {})
        target = record.get("id") or name
        smoke.command((*smoke.docker, "rm", "--force", target), cleanup=True, require=False)
        _, raw = smoke.command(
            (*smoke.docker, "ps", "-a", "--no-trunc", "--format", "{{.ID}} {{.Names}}"),
            cleanup=True,
        )
        if any(target in line.split() or name in line.split() for line in raw.splitlines()):
            raise RuntimeError("preparation container still present")
        if not record or record["pending"]:
            raise RuntimeError("preparation create remains unsettled")
        record["absent"] = True
        smoke._save_build_ownership()
    finally:
        smoke.cleanup_deadline = previous
        for sig, handler in old.items():
            signal.signal(sig, handler)


def prepare_files(smoke: Smoke, route: str, destination: Path, wheels: Path | None = None) -> None:
    """EOF + pinned hashes + successful terminal + exact cleanup precede install."""
    area = smoke.directory / ("prepare-" + route)
    mkdir_private(area)  # no stale run reuse
    inputs = area / "inputs"
    manifest = snapshot(input_sources(route, wheels), inputs)
    packages = locked_packages(inputs)
    if route == "package":
        from macos_preparation_transfer import records

        # Recheck public bytes even when supplied by an earlier successful route.
        records(inputs / "wheels", PreparationSchema("download", packages))
        packages = {}
        for relative in ("docker/executor/package/pyproject.toml", "opstore/pyproject.toml"):
            project = tomllib.loads((inputs / "source" / relative).read_text())["project"]
            packages[project["name"].replace("-", "_")] = {
                "version": project["version"],
                "hashes": [],
            }
    schema = PreparationSchema(route, packages)
    spec = encode(packages, 65536)
    with (inputs / "packages.json").open("xb") as stream:
        stream.write(spec)
    (inputs / "packages.json").chmod(0o444)
    manifest_record = {k: asdict(v) for k, v in manifest.items()}
    manifest_record["packages.json"] = {
        "length": len(spec),
        "sha256": hashlib.sha256(spec).hexdigest(),
    }
    (area / "inputs-sha256.json").write_text(json.dumps(manifest_record, indent=2) + "\n")
    nonce = secrets.token_hex(32)
    name = "heph-macos-prepare-" + secrets.token_hex(16)
    collected = area / "collected"
    mkdir_private(collected)
    smoke.owned.append(name)
    smoke.save()
    with _Receiver(collected, nonce, "preparation-v1/" + route, BOUNDS, schema) as receiver:
        try:
            smoke.command(create_argv(smoke, route, name, inputs, nonce))
            cid = smoke.report["build_ownership"][name]["id"]
            smoke.command(
                (*smoke.docker, "start", "--attach", cid),
                timeout=180 if route == "package" else 300,
                receiver=receiver,
            )
            result = unique_json(receiver.finish())
            if not isinstance(result, dict) or result["files"] != {
                k: v.sha256 for k, v in receiver.files.items()
            }:
                raise ValueError("preparation body hash disagreement")
            _, raw = smoke.command((*smoke.docker, "inspect", "--format", "{{json .State}}", cid))
            state = json.loads(raw)
            if (
                state["Running"] is not False
                or type(state["ExitCode"]) is not int
                or state["ExitCode"] != 0
                or state["OOMKilled"] is not False
            ):
                raise RuntimeError("preparation terminal failure")
            (area / "terminal.json").write_text(json.dumps(state) + "\n")
        finally:
            remove_owned(smoke, name)
        smoke.deadline.remaining()
        mkdir_private(destination)  # exclusive; no stale output acceptance
        receiver.install(destination)
        smoke.deadline.remaining()  # no late publication may become accepted evidence
        exported = {k: asdict(v) for k, v in receiver.files.items()}
    (area / "export-sha256.json").write_text(json.dumps(exported, indent=2) + "\n")
    if route == "package":
        lines = ["# Generated from repository-built wheels; do not edit.\n"]
        for name in ("hephaestus_executor_runtime", "opstore"):
            leaf = next(k for k in exported if k.startswith(name + "-"))
            lines.append(
                f"{name.replace('_', '-')}=={packages[name]['version']} "
                f"--hash=sha256:{exported[leaf]['sha256']}\n"
            )
        with (destination / "local-requirements.lock").open("x") as stream:
            stream.write("".join(lines))
    smoke.deadline.remaining()
    smoke.report.setdefault("preparation_exports", {})[route] = str(
        area.relative_to(smoke.directory)
    )
    smoke.save()
