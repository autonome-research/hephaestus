"""Trusted, pre-workload image inventory. Stdlib only; never accepts job input.

The immutable image is a trust input, not made trustworthy by this inventory.
The fixed launcher measures installed source bytes and distribution metadata in
its separate manifest container, before any CAD script can run. The host binds
that observation to the daemon-attested digest, config ID and platform.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import re
from collections.abc import Iterable
from pathlib import Path

IDENTITY_VERSION = 1
SOURCE_DISTRIBUTIONS = {
    "hephaestus-executor-runtime": "hephaestus/",
    "opstore": "opstore/",
}
MAX_SOURCE_BYTES = 32 * 1024 * 1024
MAX_SOURCE_FILES = 8192


def _hash(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def validate_runtime_identity(value: object) -> dict[str, object]:
    """Closed, bounded inventory schema; no coercion or missing-version fallback."""
    if not isinstance(value, dict) or set(value) != {
        "version",
        "python",
        "packages",
        "source_trees",
    }:
        raise ValueError("invalid executor runtime identity")
    if type(value["version"]) is not int or value["version"] != IDENTITY_VERSION:
        raise ValueError("unsupported executor identity version")
    if (
        not isinstance(value["python"], str)
        or re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", value["python"]) is None
    ):
        raise ValueError("invalid executor Python version")
    packages = value["packages"]
    if not isinstance(packages, dict) or not 4 <= len(packages) <= 256:
        raise ValueError("missing executor packages")
    if not {"build123d", *SOURCE_DISTRIBUTIONS} <= packages.keys() or not {
        "cadquery-ocp",
        "cadquery-ocp-novtk",
        "cadquery-ocp-proxy",
        "ocp",
    }.intersection(packages):
        raise ValueError("missing executor toolchain packages")
    for name, record in packages.items():
        if not isinstance(name, str) or re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) is None:
            raise ValueError("invalid distribution name")
        if not isinstance(record, dict) or set(record) != {"version", "metadata_sha256"}:
            raise ValueError("invalid distribution identity")
        version = record["version"]
        if (
            not isinstance(version, str)
            or re.fullmatch(r"[A-Za-z0-9.!+_-]{1,128}", version) is None
        ):
            raise ValueError("invalid distribution version")
        _require_hash(record["metadata_sha256"])
    sources = value["source_trees"]
    if not isinstance(sources, dict) or set(sources) != set(SOURCE_DISTRIBUTIONS):
        raise ValueError("missing executor source identity")
    for digest in sources.values():
        _require_hash(digest)
    return value


def _require_hash(value: object) -> None:
    if not isinstance(value, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
        raise ValueError("invalid executor identity hash")


def installed_source_hash(dist: importlib.metadata.Distribution, prefix: str) -> str:
    """Hash installed source/data, not RECORD claims or checkout/git status.

    Wheel pycache is excluded (generated interpreter cache); every shipped file
    below the package namespace otherwise participates, including schema data.
    """
    records: dict[str, str] = {}
    total = 0
    root = Path(str(dist.locate_file(""))).resolve(strict=True)
    for file in dist.files or ():
        name = str(file)
        if not name.startswith(prefix) or "__pycache__" in file.parts or file.suffix == ".pyc":
            continue
        path = Path(str(dist.locate_file(file)))
        if (
            ".." in file.parts
            or path.is_symlink()
            or not path.is_file()
            or not path.resolve().is_relative_to(root)
        ):
            raise ValueError("invalid installed source file")
        if name in records or len(records) >= MAX_SOURCE_FILES:
            raise ValueError("invalid installed source inventory")
        with path.open("rb") as stream:
            data = stream.read(MAX_SOURCE_BYTES - total + 1)
        total += len(data)
        if total > MAX_SOURCE_BYTES:
            raise ValueError("installed source inventory exceeds bound")
        records[name] = _hash(data)
    if not records:
        raise ValueError("missing installed executor sources")
    return _hash(_canonical(records))


def collect_runtime_identity(
    *,
    distributions: Iterable[importlib.metadata.Distribution] | None = None,
    python_version: str | None = None,
) -> dict[str, object]:
    """Measure inside the image; explicit inventory inputs support host tests.

    The launcher never accepts these dependencies from argv or workload input.
    """
    packages: dict[str, object] = {}
    sources: dict[str, str] = {}
    for dist in importlib.metadata.distributions() if distributions is None else distributions:
        name = re.sub(r"[-_.]+", "-", dist.metadata["Name"]).lower()
        if name in packages or len(packages) >= 256:
            raise ValueError("duplicate/excessive installed distributions")
        metadata = dist.read_text("METADATA")
        if metadata is None or len(metadata.encode()) > 1024 * 1024:
            raise ValueError("missing/oversized installed package metadata")
        packages[name] = {"version": dist.version, "metadata_sha256": _hash(metadata.encode())}
        if name in SOURCE_DISTRIBUTIONS:
            sources[name] = installed_source_hash(dist, SOURCE_DISTRIBUTIONS[name])
    return validate_runtime_identity(
        {
            "version": IDENTITY_VERSION,
            "python": platform.python_version() if python_version is None else python_version,
            "packages": packages,
            "source_trees": sources,
        }
    )
