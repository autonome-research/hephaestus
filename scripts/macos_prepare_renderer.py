# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Pinned renderer preparation helpers; trusted offline builds, not workload execution."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "docker/executor"))
from fetch_native_runtime import native_source_allowed  # noqa: E402


def _locked_bytes(path: Path, item: dict) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size != item["size"]:
            raise ValueError("download type/size mismatch: " + path.name)
        data = stream.read(item["size"] + 1)
    if len(data) != item["size"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
        raise ValueError("download hash/size mismatch: " + path.name)
    return data


def fetch_locked(lock: Path, destination: Path, cache: Path | None = None) -> None:
    """Exact URL/size/hash downloads; finite aggregate and per-request budgets.

    curl's max-filesize bounds received bytes even on a malicious oversized body;
    only a hash-verified exclusive file enters the cache/build context.
    """
    destination.mkdir(parents=True, exist_ok=True)
    packages = json.loads(lock.read_text())["packages"]
    if len(packages) > 128 or sum(p["size"] for p in packages) > 128 * 1024**2:
        raise ValueError("download aggregate bound")
    for item in packages:
        name = item["filename"]
        if Path(name).name != name or not 0 < item["size"] <= 64 * 1024**2:
            raise ValueError("download leaf/size")
        url = urlsplit(item["url"])
        allowed = (
            native_source_allowed(item["url"], name, item["sha256"], item["size"])
            if name.endswith(".deb")
            else name.endswith(".whl")
            and url.scheme == "https"
            and url.netloc == "files.pythonhosted.org"
            and not url.query
            and not url.fragment
        )
        if not allowed:
            raise ValueError("download source violates integrity policy")
        target = destination / name
        if not target.exists() and cache is not None and (cache / name).is_file():
            data = _locked_bytes(cache / name, item)  # admission BEFORE staging writes
            with target.open("xb") as stream:
                stream.write(data)
        if not target.exists():
            subprocess.run(
                (
                    "/usr/bin/curl",
                    "--disable",  # Must be first: never load a user's .curlrc (e.g. insecure).
                    "--silent",
                    "--show-error",
                    "--fail",
                    "--location",
                    "--max-redirs",
                    "0",
                    "--proto",
                    "=https",
                    "--proto-redir",
                    "=https",
                    "--connect-timeout",
                    "15",
                    "--max-time",
                    "300",
                    "--max-filesize",
                    str(item["size"]),
                    item["url"],
                    "-o",
                    str(target),
                ),
                check=True,
                timeout=310,
            )
        _locked_bytes(target, item)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("lock", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--cache", type=Path)
    args = parser.parse_args()
    fetch_locked(args.lock, args.destination, args.cache)


def prepare(smoke):
    """Independent image, reusing only the reviewed source-wheel build recipe."""
    import secrets
    import sys

    from macos_preparation import prepare_files

    staging = smoke.directory / "download"
    prepare_files(smoke, "package", staging / "local-wheels", staging / "wheels")
    smoke.report["renderer_source_manifest"] = "prepare-package/inputs-sha256.json"
    context = smoke.directory / "image-context"
    shutil.copytree(
        ROOT / "docker/executor",
        context / "docker/executor",
        ignore=shutil.ignore_patterns("package", "__pycache__"),
    )
    shutil.copytree(ROOT / "docker/renderer", context / "docker/renderer")
    shutil.copytree(staging / "wheels", context / "dist/renderer-wheelhouse")
    for path in (staging / "local-wheels").iterdir():
        with (context / "dist/renderer-wheelhouse" / path.name).open("xb") as target:
            target.write(path.read_bytes())
    for kind in ("python", "native"):
        smoke.command(
            (
                sys.executable,
                str(ROOT / "scripts/macos_prepare_renderer.py"),
                str(ROOT / f"docker/renderer/{kind}-arm64.lock.json"),
                str(context / f"dist/renderer-{kind}"),
                "--cache",
                str(ROOT / f"dist/renderer-{kind}-cache"),
            ),
            timeout=900,
        )
    (smoke.directory / "renderer-image-inputs-sha256.json").write_text(
        json.dumps(
            {
                str(p.relative_to(context)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(context.rglob("*"))
                if p.is_file()
            },
            indent=2,
        )
        + "\n"
    )
    tag = "hephaestus-macos-renderer:" + secrets.token_hex(16)
    smoke.report["owned_image_tags"].append(tag)
    smoke.save()
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
            str(context / "docker/renderer/Dockerfile"),
            "-t",
            tag,
            str(context),
        ),
        timeout=480,
    )
    return tag


if __name__ == "__main__":
    main()
