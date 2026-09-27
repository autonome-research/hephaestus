# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""Write hash-pinned requirements for the two repository-built executor wheels."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

PACKAGES: tuple[tuple[str, str], ...] = (
    ("hephaestus-executor-runtime", "hephaestus_executor_runtime-*.whl"),
    ("opstore", "opstore-*.whl"),
)


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_local_lock(wheelhouse: Path) -> Path:
    """Create ``local-requirements.lock`` after requiring one wheel per package."""
    lines = ["# Generated from repository-built wheels; do not edit.\n"]
    for distribution, pattern in PACKAGES:
        matches = sorted(wheelhouse.glob(pattern))
        if len(matches) != 1:
            raise ValueError(f"expected exactly one {pattern!r} wheel, found {len(matches)}")
        wheel = matches[0]
        version = wheel.name.split("-", 2)[1]
        lines.append(f"{distribution}=={version} --hash=sha256:{_digest(wheel)}\n")
    target = wheelhouse / "local-requirements.lock"
    target.write_text("".join(lines), encoding="ascii")
    return target


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: write_local_lock.py WHEELHOUSE", file=sys.stderr)
        return 2
    try:
        target = write_local_lock(Path(args[0]))
    except (OSError, ValueError) as exc:
        print(f"write_local_lock: {exc}", file=sys.stderr)
        return 1
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
