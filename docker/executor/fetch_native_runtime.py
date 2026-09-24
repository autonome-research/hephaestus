# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""Fetch the hash-locked native OCP loader closure for one Linux architecture."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import urllib.request
from pathlib import Path
from typing import TypedDict, cast
from urllib.parse import urlsplit


class Package(TypedDict):
    filename: str
    sha256: str
    size: int
    url: str


class Lock(TypedDict):
    architecture: str
    packages: list[Package]


def _load_lock(path: Path, architecture: str) -> Lock:
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("native lock must be an object")
    value = cast("dict[str, object]", raw)
    if value.get("architecture") != architecture:
        raise ValueError("native lock architecture mismatch")
    raw_packages = value.get("packages")
    if not isinstance(raw_packages, list) or not raw_packages:
        raise ValueError("native lock has no packages")
    packages: list[Package] = []
    for raw_package in cast("list[object]", raw_packages):
        if not isinstance(raw_package, dict):
            raise ValueError("native package record must be an object")
        package = cast("dict[str, object]", raw_package)
        filename = package.get("filename")
        sha256 = package.get("sha256")
        size = package.get("size")
        url = package.get("url")
        if not (
            isinstance(filename, str)
            and isinstance(sha256, str)
            and type(size) is int
            and isinstance(url, str)
        ):
            raise ValueError("native package record has invalid field types")
        parsed_url = urlsplit(url)
        if (
            Path(filename).name != filename
            or not filename.endswith(".deb")
            or re.fullmatch(r"[0-9a-f]{64}", sha256) is None
            or size <= 0
            or parsed_url.scheme != "https"
            or parsed_url.hostname != "deb.debian.org"
            or parsed_url.username is not None
            or parsed_url.password is not None
            or parsed_url.fragment
        ):
            raise ValueError("native package record violates integrity policy")
        packages.append(Package(filename=filename, sha256=sha256, size=size, url=url))
    if len({item["filename"] for item in packages}) != len(packages):
        raise ValueError("native lock contains duplicate filenames")
    return Lock(architecture=architecture, packages=packages)


def verify(lock_path: Path, destination: Path, architecture: str) -> None:
    """Require exactly the locked artifacts and verify every size and digest."""
    lock = _load_lock(lock_path, architecture)
    expected = {item["filename"] for item in lock["packages"]}
    actual = {path.name for path in destination.glob("*.deb")}
    if actual != expected:
        raise ValueError("native package set does not exactly match its lock")
    for item in lock["packages"]:
        if not _valid(destination / item["filename"], item):
            raise ValueError(f"native package integrity check failed: {item['filename']}")


def fetch(lock_path: Path, destination: Path, architecture: str) -> None:
    """Download each artifact and accept it only after size and SHA-256 checks."""
    lock = _load_lock(lock_path, architecture)
    destination.mkdir(parents=True, exist_ok=True)
    expected = {item["filename"] for item in lock["packages"]}
    for existing in destination.glob("*.deb"):
        if existing.name not in expected:
            existing.unlink()
    for item in lock["packages"]:
        target = destination / item["filename"]
        if target.is_file() and _valid(target, item):
            continue
        fd, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=destination)
        try:
            with (
                os.fdopen(fd, "wb") as output,
                urllib.request.urlopen(item["url"], timeout=60) as response,
            ):
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
            temporary = Path(temporary_name)
            if not _valid(temporary, item):
                raise ValueError(f"native package integrity check failed: {target.name}")
            temporary.replace(target)
        finally:
            Path(temporary_name).unlink(missing_ok=True)
    verify(lock_path, destination, architecture)


def _valid(path: Path, item: Package) -> bool:
    if path.stat().st_size != item["size"]:
        return False
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest() == item["sha256"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("architecture", choices=("amd64", "arm64"))
    parser.add_argument("destination", type=Path)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    directory = Path(__file__).resolve().parent
    try:
        action = verify if args.verify_only else fetch
        action(
            directory / f"native-{args.architecture}.lock.json",
            args.destination,
            args.architecture,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
