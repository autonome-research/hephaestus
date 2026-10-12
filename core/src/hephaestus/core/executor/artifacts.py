"""Bounded, no-follow reads of the build worker's closed artifact vocabulary.

These are read/publication limits, NOT a writable staging storage quota. The
worker must have terminated before collection; snapshots, not paths, are used
for subsequent publication.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

from hephaestus.core.errors import ValidationError

ARTIFACT_NAMES = {
    "build": "final.brep",
    "last_good": "last_good.brep",
    "source_map": "source_map.json",
}
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
MAX_SOURCE_MAP_BYTES = 8 * 1024 * 1024


def read_artifact(directory: Path, filename: str) -> bytes:
    """Open a single allowlisted regular file relative to an owned directory FD.

    O_NONBLOCK prevents a FIFO open from hanging before fstat can reject it.
    O_NOFOLLOW applies to both the directory and the leaf; names have no path
    components. Never resolve a worker-provided path or reopen after validation.
    """
    if filename not in ARTIFACT_NAMES.values():
        raise ValidationError("worker artifact filename is not allowlisted", kind="evaluation")
    maximum = MAX_SOURCE_MAP_BYTES if filename == "source_map.json" else MAX_ARTIFACT_BYTES
    try:
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise ValidationError(
                        "worker artifact must be a singly-linked regular file", kind="evaluation"
                    )
                if not 0 < info.st_size <= maximum:
                    raise ValidationError(
                        "worker artifact size is outside bounds", kind="evaluation"
                    )
                data = stream.read(maximum + 1)
                if len(data) != info.st_size or len(data) > maximum:
                    raise ValidationError("worker artifact changed during read", kind="evaluation")
                return data
        finally:
            os.close(directory_fd)
    except OSError as exc:
        raise ValidationError(
            f"worker artifact could not be opened safely: {filename}", kind="evaluation"
        ) from exc
