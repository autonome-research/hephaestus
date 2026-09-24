"""Fail-closed entry point for workers in the OCI executor image."""

from __future__ import annotations

import os
import re
import resource
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, NoReturn, TextIO

from hephaestus.core.executor.sandbox.oci_protocol import (
    APPROVED_MODULES,
    MAX_ADDRESS_SPACE_BYTES,
    MAX_CPU_SECONDS,
    MAX_NPROC,
    PROTOCOL_VERSION,
    approved_module_for_worker_args,
    diagnostic_bytes,
    manifest_bytes,
)

EXIT_USAGE = 64
EXIT_PROTOCOL = 65
EXIT_WORKER = 66
EXIT_RLIMIT = 78
EXIT_EXEC = 126

FIXED_WORKER_ENV: Mapping[str, str] = MappingProxyType(
    {
        "HOME": "/tmp",
        "TMPDIR": "/tmp",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
    }
)

_DECIMAL_RE = re.compile(r"[1-9][0-9]*", flags=re.ASCII)


class _LaunchError(ValueError):
    def __init__(self, code: str, exit_code: int) -> None:
        super().__init__(code)
        self.code = code
        self.exit_code = exit_code


@dataclass(frozen=True)
class LaunchRequest:
    protocol_version: int
    module: str
    cpu_seconds: int
    address_space_bytes: int
    nproc: int

    def __post_init__(self) -> None:
        values = (
            (self.cpu_seconds, MAX_CPU_SECONDS),
            (self.address_space_bytes, MAX_ADDRESS_SPACE_BYTES),
            (self.nproc, MAX_NPROC),
        )
        if type(self.protocol_version) is not int or self.protocol_version != PROTOCOL_VERSION:
            raise ValueError("unsupported protocol version")
        if self.module not in APPROVED_MODULES:
            raise ValueError("worker is not allowlisted")
        if any(type(value) is not int or not 1 <= value <= maximum for value, maximum in values):
            raise ValueError("limit is outside the protocol bounds")


def _positive_decimal(raw: str, maximum: int) -> int:
    if _DECIMAL_RE.fullmatch(raw) is None:
        raise _LaunchError("invalid_limit", EXIT_USAGE)
    # Avoid converting attacker-sized integers and reject values over the cap.
    maximum_text = str(maximum)
    if len(raw) > len(maximum_text) or (len(raw) == len(maximum_text) and raw > maximum_text):
        raise _LaunchError("invalid_limit", EXIT_USAGE)
    return int(raw)


def parse_argv(argv: Sequence[str]) -> Literal["manifest"] | LaunchRequest:
    """Parse the deliberately small launcher grammar without coercions."""
    if len(argv) == 1 and argv[0] == "manifest":
        return "manifest"
    if len(argv) != 6 or argv[0] != "run":
        raise _LaunchError("invalid_invocation", EXIT_USAGE)

    version = argv[1]
    if _DECIMAL_RE.fullmatch(version) is None:
        raise _LaunchError("invalid_invocation", EXIT_USAGE)
    if version != str(PROTOCOL_VERSION):
        raise _LaunchError("protocol_version_mismatch", EXIT_PROTOCOL)

    try:
        module = approved_module_for_worker_args(("-m", argv[2]))
    except ValueError:
        raise _LaunchError("worker_not_allowed", EXIT_WORKER) from None

    return LaunchRequest(
        protocol_version=PROTOCOL_VERSION,
        module=module,
        cpu_seconds=_positive_decimal(argv[3], MAX_CPU_SECONDS),
        address_space_bytes=_positive_decimal(argv[4], MAX_ADDRESS_SPACE_BYTES),
        nproc=_positive_decimal(argv[5], MAX_NPROC),
    )


def _capped_rlimit(inherited: tuple[int, int], requested: int) -> tuple[int, int]:
    infinity = resource.RLIM_INFINITY
    inherited_soft, inherited_hard = inherited
    soft = requested if inherited_soft == infinity else min(requested, inherited_soft)
    hard = requested if inherited_hard == infinity else min(requested, inherited_hard)
    # A valid inherited pair already has soft <= hard.  Preserve that invariant
    # defensively even when a test double or unusual platform reports otherwise.
    return min(soft, hard), hard


def apply_rlimits(request: LaunchRequest) -> None:
    """Apply every available limit, never relaxing an inherited limit."""
    limits: list[tuple[int, int]] = [
        (resource.RLIMIT_CORE, 0),
        (resource.RLIMIT_CPU, request.cpu_seconds),
        (resource.RLIMIT_AS, request.address_space_bytes),
    ]
    data_limit = getattr(resource, "RLIMIT_DATA", None)
    if data_limit is not None:
        limits.append((data_limit, request.address_space_bytes))
    nproc_limit = getattr(resource, "RLIMIT_NPROC", None)
    if nproc_limit is not None:
        limits.append((nproc_limit, request.nproc))

    for kind, requested in limits:
        inherited = resource.getrlimit(kind)
        resource.setrlimit(kind, _capped_rlimit(inherited, requested))


def exec_worker(request: LaunchRequest) -> NoReturn:
    """Replace the launcher with one allowlisted module in isolated mode."""
    module = approved_module_for_worker_args(("-m", request.module))
    executable = sys.executable
    if not executable or not os.path.isabs(executable):
        raise OSError("interpreter path is not absolute")
    os.execve(
        executable,
        [executable, "-I", "-m", module],
        dict(FIXED_WORKER_ENV),
    )
    raise AssertionError("os.execve returned")  # pragma: no cover


def _write(stream: TextIO, payload: bytes) -> None:
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        buffer.write(payload)
        buffer.flush()
    else:  # Supports StringIO test doubles without changing emitted bytes.
        stream.write(payload.decode("ascii"))
        stream.flush()


def main(argv: Sequence[str] | None = None) -> int:
    args = tuple(sys.argv[1:] if argv is None else argv)
    try:
        parsed = parse_argv(args)
    except _LaunchError as exc:
        _write(sys.stderr, diagnostic_bytes(exc.code))
        return exc.exit_code

    if parsed == "manifest":
        _write(sys.stdout, manifest_bytes())
        return 0

    try:
        apply_rlimits(parsed)
    except Exception:
        _write(sys.stderr, diagnostic_bytes("resource_limit_failed"))
        return EXIT_RLIMIT

    try:
        exec_worker(parsed)
    except Exception:
        _write(sys.stderr, diagnostic_bytes("execve_failed"))
        return EXIT_EXEC


if __name__ == "__main__":  # pragma: no cover - exercised through the module entry point
    raise SystemExit(main())
