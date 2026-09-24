"""Versioned, deterministic protocol primitives for the OCI executor image.

This module intentionally uses only the Python standard library.  The worker
allowlist and manifest are protocol data: changing either incompatibly requires
incrementing :data:`PROTOCOL_VERSION`.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

PROTOCOL_NAME = "hephaestus.oci-executor"
PROTOCOL_VERSION = 2
MANIFEST_VERSION = 2
DIAGNOSTIC_VERSION = 1
OCI_PROFILE_VERSION = 2
OCI_HOSTNAME = "hephaestus-executor"

OCI_TMPFS_BYTES = 256 * 1024**2
PROBE_REQUEST_MAX_BYTES = 1024
PROBE_STDOUT_MAX_BYTES = 64 * 1024
PROBE_STDERR_MAX_BYTES = 16 * 1024
EXEC_STDOUT_MAX_BYTES = 16 * 1024 * 1024
EXEC_STDERR_MAX_BYTES = 1024 * 1024

REQUIRED_OCI_FEATURES: tuple[str, ...] = (
    "numeric_identity",
    "rlimits",
    "capabilities_dropped",
    "no_new_privileges",
    "pid_namespace",
    "uts_namespace",
    "root_read_only",
    "work_writable",
    "tmpfs_profile",
    "network_isolated",
    "cgroup_memory",
    "cgroup_swap",
    "cgroup_pids",
    "cgroup_cpu",
)

BUILD_WORKER = "hephaestus.core.executor.worker"
DFM_WORKER = "hephaestus.core.dfm.worker"
PROBE_WORKER = "hephaestus.core.executor.sandbox._oci_probe_worker"

APPROVED_MODULES: frozenset[str] = frozenset({BUILD_WORKER, DFM_WORKER, PROBE_WORKER})

MAX_CPU_SECONDS = 120
MAX_ADDRESS_SPACE_BYTES = 6 * 1024**3
MAX_NPROC = 4096


def approved_module_for_worker_args(worker_args: Sequence[object]) -> str:
    """Return the module from exactly ``("-m", <approved module>)``.

    No aliases, additional worker arguments, or prefix/suffix matches are
    accepted.  ``ValueError`` deliberately does not include rejected input.
    """
    if (
        len(worker_args) != 2
        or not isinstance(worker_args[0], str)
        or not isinstance(worker_args[1], str)
        or worker_args[0] != "-m"
        or worker_args[1] not in APPROVED_MODULES
    ):
        raise ValueError("worker arguments are not allowlisted")
    return worker_args[1]


def manifest_record() -> dict[str, object]:
    """Return a fresh copy of the immutable protocol manifest."""
    return {
        "diagnostic_version": DIAGNOSTIC_VERSION,
        "limits": {
            "address_space_bytes_max": MAX_ADDRESS_SPACE_BYTES,
            "cpu_seconds_max": MAX_CPU_SECONDS,
            "nproc_max": MAX_NPROC,
            "rlimits": [
                "RLIMIT_AS",
                "RLIMIT_CORE",
                "RLIMIT_CPU",
                "RLIMIT_DATA",
                "RLIMIT_NPROC",
            ],
        },
        "manifest_version": MANIFEST_VERSION,
        "oci_profile_version": OCI_PROFILE_VERSION,
        "protocol": {"name": PROTOCOL_NAME, "version": PROTOCOL_VERSION},
        "workers": sorted(APPROVED_MODULES),
    }


def _canonical_bytes(record: object) -> bytes:
    return (
        json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    ).encode("ascii")


def manifest_bytes() -> bytes:
    """Encode the manifest as canonical JSON followed by one newline."""
    return _canonical_bytes(manifest_record())


def diagnostic_bytes(code: object, **fields: object) -> bytes:
    """Encode one bounded, canonical launcher diagnostic JSON line.

    Callers control which fields they pass and must never pass exception text or
    rejected input.  Protocol/schema identity cannot be overridden.
    """
    if not isinstance(code, str) or not code:
        raise ValueError("diagnostic code must be a non-empty string")
    if "code" in fields or "diagnostic_version" in fields or "protocol_version" in fields:
        raise ValueError("reserved diagnostic field")
    component = fields.pop("component", "oci_launcher")
    if not isinstance(component, str) or not component:
        raise ValueError("diagnostic component must be a non-empty string")
    record: dict[str, object] = {
        "code": code,
        "component": component,
        "diagnostic_version": DIAGNOSTIC_VERSION,
        "protocol_version": PROTOCOL_VERSION,
    }
    record.update(fields)
    return _canonical_bytes(record)
