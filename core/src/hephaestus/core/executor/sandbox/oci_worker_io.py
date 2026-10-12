"""Fixed launcher-generated worker transport mode; native workers keep native IO."""

from __future__ import annotations

import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .oci_storage_policy import STORAGE_POLICIES, StoragePolicy
from .oci_transfer import Json, export, read_job


@dataclass(frozen=True)
class WorkerIO:
    nonce: str
    policy: StoragePolicy

    def read(self) -> dict[str, Json]:
        job = read_job(sys.stdin.buffer)
        if not isinstance(job, dict):
            raise ValueError("job must be an object")
        return job

    def send(self, result: Json, module: str) -> None:
        export(sys.stdout.buffer, result, self.nonce, module, Path("/work"), self.policy)


def worker_io(args: Sequence[str] | None = None) -> WorkerIO | None:
    args = sys.argv[1:] if args is None else args
    if not args:
        return None
    if (
        len(args) != 3
        or args[0] != "--oci-transfer"
        or args[1] not in STORAGE_POLICIES
        or re.fullmatch(r"[0-9a-f]{64}", args[2]) is None
    ):
        raise ValueError("invalid internal transport invocation")
    return WorkerIO(args[2], STORAGE_POLICIES[args[1]])
