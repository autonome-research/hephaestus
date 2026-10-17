# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Closed preparation file schema over the existing OCI framing/file primitives.

Not an audited CAD worker and never registered with an OCI launcher. This module
is stdlib-only so the downloader needs no installed application or CAD modules.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from hephaestus.core.executor.sandbox.oci_transfer import (
    FileRecord,
    _collect,
    _exclusive,
    _TransferSchema,
    open_directory,
    open_regular,
    write_all,
)

MIB = 1024**2
# Independent preparation ceilings: do not widen StoragePolicy/CAD/render limits.
FILE_BYTES = 256 * MIB
EXPORT_BYTES = 768 * MIB
FILE_COUNT = 128
INPUT_BYTES = 896 * MIB
INPUT_FILES = 2048
INPUT_ENTRIES = 4096
SOURCE_BYTES = 64 * MIB
WORK_BYTES = 1024 * MIB
WORK_INODES = 16384
TMP_BYTES = 256 * MIB
TMP_INODES = 4096
HEX = re.compile(r"[0-9a-f]{64}")
WHEEL = re.compile(
    r"([a-zA-Z0-9_]+)-([a-zA-Z0-9_.!+]+)-[a-zA-Z0-9_.]+-[a-zA-Z0-9_.]+-[a-zA-Z0-9_.]+\.whl"
)
ROUTES = frozenset({"download", "download-cache", "package"})


@dataclass(frozen=True)
class PreparationBounds:
    result_bytes: int = 65536
    export_bytes: int = EXPORT_BYTES


BOUNDS = PreparationBounds()


class PreparationSchema(_TransferSchema):
    header_max = 65536
    file_count = FILE_COUNT

    def __init__(self, route: str, packages: dict[str, dict]) -> None:
        if route not in ROUTES or not 0 < len(packages) <= FILE_COUNT:
            raise ValueError("preparation route/package count")
        if route == "package" and set(packages) != {"hephaestus_executor_runtime", "opstore"}:
            raise ValueError("source package allowlist")
        for name, item in packages.items():
            if (
                not re.fullmatch(r"[a-z0-9_]{1,100}", name)
                or not isinstance(item, dict)
                or set(item) != {"version", "hashes"}
                or not isinstance(item["version"], str)
                or not re.fullmatch(r"[a-zA-Z0-9_.!+]{1,50}", item["version"])
                or not isinstance(item["hashes"], list)
                or len(item["hashes"]) > 128
                or any(not isinstance(h, str) or not HEX.fullmatch(h) for h in item["hashes"])
                or (route != "package" and not item["hashes"])
            ):
                raise ValueError("preparation package schema")
        self.route = route
        self.packages = packages

    def identity(self, nonce: object, operation: object) -> tuple[str, str]:
        if not isinstance(nonce, str) or not HEX.fullmatch(nonce):
            raise ValueError("preparation nonce")
        if operation != "preparation-v1/" + self.route:
            raise ValueError("preparation operation")
        return nonce, str(operation)

    def name(self, ident: str) -> str:
        match = WHEEL.fullmatch(ident)
        if not match or len(ident) > 200:
            raise ValueError("not an allowlisted wheel leaf")
        distribution, version = match.groups()
        item = self.packages.get(distribution)
        if item is None or version != item["version"]:
            raise ValueError("unlocked wheel distribution/version")
        if self.route == "package" and ident != f"{distribution}-{version}-py3-none-any.whl":
            raise ValueError("unexpected source wheel tags")
        return ident

    def limit(self, ident: str) -> int:
        self.name(ident)
        return FILE_BYTES if self.route != "package" else SOURCE_BYTES

    def ids(self, result: object, operation: str) -> list[str]:
        if not isinstance(result, dict) or set(result) != {"files"}:
            raise ValueError("preparation result schema")
        files = result["files"]
        if not isinstance(files, dict) or not 0 < len(files) <= self.file_count:
            raise ValueError("preparation file count")
        seen = set()
        for name, digest in files.items():
            if not isinstance(name, str):
                raise ValueError("preparation leaf type")
            self.name(name)
            distribution = name.split("-", 1)[0].lower()
            if distribution in seen:
                raise ValueError("duplicate distribution")
            seen.add(distribution)
            if not isinstance(digest, str) or not HEX.fullmatch(digest):
                raise ValueError("preparation digest")
            hashes = self.packages[distribution]["hashes"]
            if self.route != "package" and digest not in hashes:
                raise ValueError("wheel hash not in pinned lock")
        if seen != set(self.packages):
            raise ValueError("incomplete preparation output")
        return sorted(files)


def records(directory: Path, schema: PreparationSchema) -> dict[str, FileRecord]:
    fd = open_directory(directory)
    result = {}
    total = 0
    try:
        with os.scandir(fd) as entries:
            for entry in entries:
                if len(result) >= schema.file_count:
                    raise ValueError("preparation file count")
                source, info = open_regular(fd, schema.name(entry.name), schema.limit(entry.name))
                total += info.st_size
                with source:
                    if total > EXPORT_BYTES:
                        raise ValueError("preparation aggregate bytes")
                    digest = hashlib.sha256()
                    for chunk in _collect(source, info):
                        digest.update(chunk)
                result[entry.name] = FileRecord(info.st_size, digest.hexdigest())
    finally:
        os.close(fd)
    schema.ids(
        {"files": {k: v.sha256 for k, v in result.items()}}, "preparation-v1/" + schema.route
    )
    return result


def mkdir_private(path: Path) -> None:
    """Exclusive directory creation without following even an ancestor symlink."""
    fd = open_directory(path.parent)
    try:
        os.mkdir(path.name, mode=0o700, dir_fd=fd)
    finally:
        os.close(fd)


def snapshot(sources: dict[str, Path], destination: Path) -> dict[str, FileRecord]:
    """Bounded no-follow tree copy into a fresh private directory.

    Admit the complete inventory before copying. Reopen through no-follow
    parents, compare stat identity and use the existing stable-file collector.
    Inputs are trusted supply-chain files, never a project/home/socket mount.
    """
    admitted = []
    total = entries = 0
    # Reserve one entry/file and 64 KiB for the host-generated closed package spec.
    entry_limit, file_limit, byte_limit = INPUT_ENTRIES - 1, INPUT_FILES - 1, INPUT_BYTES - 65536

    def visit(path: Path, relative: Path) -> None:
        nonlocal total, entries
        entries += 1
        if entries > entry_limit or len(relative.parts) > 20:
            raise ValueError("preparation input entry/depth bound")
        parent = open_directory(path.parent)
        try:
            info = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                fd = open_directory(path)
                try:
                    with os.scandir(fd) as children:
                        for child in children:
                            if child.name == "__pycache__" or child.name.endswith((".pyc", ".pyo")):
                                entries += 1
                                if entries > entry_limit:
                                    raise ValueError("preparation input entry bound")
                                continue
                            visit(path / child.name, relative / child.name)
                finally:
                    os.close(fd)
            else:
                source, info = open_regular(parent, path.name, FILE_BYTES, allow_empty=True)
                source.close()
                total += info.st_size
                if total > byte_limit or len(admitted) >= file_limit:
                    raise ValueError("preparation input byte/file bound")
                admitted.append((path, relative, info))
        finally:
            os.close(parent)

    for name, source in sources.items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ValueError("snapshot path")
        visit(source, relative)
    if len({r for _, r, _ in admitted}) != len(admitted):
        raise ValueError("duplicate snapshot path")
    if sum(i.st_size for _, r, i in admitted if r.parts[0] == "source") > SOURCE_BYTES:
        raise ValueError("source snapshot byte bound")
    mkdir_private(destination)  # never reuse stale/partial inputs
    dest = open_directory(destination)
    os.close(dest)
    result = {}
    for path, relative, admitted_info in admitted:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        parent = open_directory(path.parent)
        dest = open_directory(target.parent)
        try:
            source, info = open_regular(parent, path.name, FILE_BYTES, allow_empty=True)
            with source:
                if info != admitted_info:
                    raise ValueError("snapshot source changed after admission")
                with _exclusive(dest, target.name, 0o444) as output:
                    digest = hashlib.sha256()
                    for chunk in _collect(source, info):
                        write_all(output, chunk)
                        digest.update(chunk)
            # Independently re-read the snapshot before it becomes mountable.
            copied, copied_info = open_regular(dest, target.name, FILE_BYTES, allow_empty=True)
            check = hashlib.sha256()
            with copied:
                for chunk in _collect(copied, copied_info):
                    check.update(chunk)
            if copied_info.st_size != info.st_size or check.digest() != digest.digest():
                raise ValueError("snapshot integrity")
            result[str(relative)] = FileRecord(info.st_size, check.hexdigest())
        finally:
            os.close(parent)
            os.close(dest)
    return result
