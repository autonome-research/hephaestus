# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Install the official, integrity-locked Linux x64 validator into a NEW job-local directory.

No PATH/global install, fallback, image change, or validator adapter. Keep the
upstream LICENSE and NOTICES alongside the unmodified executable.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import platform
import tarfile
import urllib.request
from pathlib import Path

LOCK = Path(__file__).resolve().parents[1] / "docker/ci/gltf-validator.lock.json"


def install(archive: bytes, destination: Path, lock: dict[str, str]) -> Path:
    """Check before extracting; refuse to replace an existing installation."""
    digest = hashlib.sha256(archive).hexdigest()
    if digest != lock["sha256"]:
        raise ValueError(f"Khronos archive SHA-256 mismatch: {digest}")
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:xz") as bundle:
        files: dict[str, bytes] = {}
        for name in ("gltf_validator", "LICENSE", "NOTICES"):
            member = bundle.getmember(name)
            if not member.isfile():
                raise ValueError(f"Khronos archive member is not a regular file: {name}")
            stream = bundle.extractfile(member)
            assert stream is not None
            files[name] = stream.read()
    if hashlib.sha256(files["gltf_validator"]).hexdigest() != lock["binary_sha256"]:
        raise ValueError("Khronos executable SHA-256 mismatch")
    destination.mkdir(parents=True, exist_ok=False)
    for name, content in files.items():
        (destination / name).write_bytes(content)
    binary = destination / "gltf_validator"
    binary.chmod(0o755)
    print(f"Khronos {lock['version']} archive sha256:{digest} -> {binary}", flush=True)
    return binary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    if platform.system() != "Linux" or platform.machine() not in {"x86_64", "AMD64"}:
        raise SystemExit("The locked Khronos release is Linux x64 only; use the pinned CI lane")
    lock: dict[str, str] = json.loads(LOCK.read_text())
    # Network/TLS/HTTP/timeout failures propagate. Never use a cached PATH tool.
    with urllib.request.urlopen(lock["url"], timeout=120) as response:
        archive = response.read()
    install(archive, args.destination.resolve(), lock)


if __name__ == "__main__":
    main()
