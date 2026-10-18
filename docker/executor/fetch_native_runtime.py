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

# Official Snapshot binfiles/info metadata maps this content address to the
# unchanged Debian security artifact. SHA-1 is only its archive locator; SHA-256
# and byte length below remain the integrity authority.
EXPAT_SNAPSHOT = "https://snapshot.debian.org/file/90544df9f8be225046764399c0a1786b98669611"
EXPAT_PIN = (
    "libexpat1_2.5.0-1+deb12u3_arm64.deb",
    "3caad0fb4382e206b005737de35b3193450589a10053f8415ded216649a233bc",
    87944,
)


def native_source_allowed(url: str, filename: str, sha256: str, size: int) -> bool:
    if url == EXPAT_SNAPSHOT:
        return (filename, sha256, size) == EXPAT_PIN
    parsed = urlsplit(url)
    return (
        parsed.scheme == "https"
        and parsed.netloc == "deb.debian.org"
        and not parsed.query
        and not parsed.fragment
        and parsed.path.startswith(("/debian/pool/", "/debian-security/pool/"))
    )


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("native package redirects are not allowed")


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
        if (
            Path(filename).name != filename
            or not filename.endswith(".deb")
            or re.fullmatch(r"[0-9a-f]{64}", sha256) is None
            or size <= 0
            or not native_source_allowed(url, filename, sha256, size)
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
                urllib.request.build_opener(NoRedirect()).open(item["url"], timeout=60) as response,
            ):
                received = 0
                while chunk := response.read(min(1024 * 1024, item["size"] - received + 1)):
                    received += len(chunk)
                    if received > item["size"]:
                        raise ValueError("native package exceeds locked size")
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
