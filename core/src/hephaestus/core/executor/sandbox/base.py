"""Sandbox backend contract: pure protocol + spec types, no backend code.

An :class:`ExecBackend` launches the build worker exactly once per request:
the parent writes one JSON request to the worker's stdin, the worker writes
one JSON result to stdout, and every artifact lands under the single
read-write out dir named by the :class:`SandboxSpec`. Backends (bwrap,
unsafe-local) implement this protocol elsewhere; this module never imports
them and contains no bwrap/argv logic.

Fail-closed rule (DESIGN): secure builds require a passing
:class:`CapabilityReport`; a failing probe means secure execution raises
``sandbox_denied`` — never a silent fallback to an unsandboxed run.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class Rlimits:
    """POSIX resource limits applied to the worker process."""

    cpu_seconds: int
    address_space_bytes: int
    nproc: int

    def __post_init__(self) -> None:
        if self.cpu_seconds <= 0:
            raise ValueError(f"cpu_seconds must be positive, got {self.cpu_seconds}")
        if self.address_space_bytes <= 0:
            raise ValueError(
                f"address_space_bytes must be positive, got {self.address_space_bytes}"
            )
        if self.nproc <= 0:
            raise ValueError(f"nproc must be positive, got {self.nproc}")


@dataclass(frozen=True)
class SandboxSpec:
    """One worker invocation: command, filesystem view, limits, wall clock.

    ``worker_cmd`` is the argv of the worker process (interpreter + worker
    module). ``ro_binds`` are the directories the worker may read (project
    dir, interpreter prefix/venv); ``rw_out_dir`` is the ONE writable
    directory — the fresh per-build out dir where the worker writes BRep and
    artifact files. ``rlimits`` bound cpu/memory/processes inside the
    sandbox; ``wall_clock_s`` is the parent-enforced kill deadline.
    """

    worker_cmd: tuple[str, ...]
    ro_binds: tuple[Path, ...]
    rw_out_dir: Path
    rlimits: Rlimits
    wall_clock_s: float

    def __post_init__(self) -> None:
        if not self.worker_cmd:
            raise ValueError("worker_cmd must not be empty")
        if self.wall_clock_s <= 0:
            raise ValueError(f"wall_clock_s must be positive, got {self.wall_clock_s}")


@dataclass(frozen=True)
class CapabilityReport:
    """Result of a backend capability probe (cached once per store).

    ``available`` is the fail-closed verdict; ``features`` records each
    probed capability by name (e.g. ``"userns"``, ``"net_unshare"``) and
    ``reason`` explains an unavailable verdict.
    """

    backend: str
    available: bool
    reason: str | None = None
    probed_at: float | None = None
    features: Mapping[str, bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.backend:
            raise ValueError("backend name must not be empty")
        if not self.available and not self.reason:
            raise ValueError("an unavailable CapabilityReport must carry a reason")

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CapabilityReport):
            return NotImplemented
        return (
            self.backend == other.backend
            and self.available == other.available
            and self.reason == other.reason
            and self.probed_at == other.probed_at
            and dict(self.features) == dict(other.features)
        )

    def __hash__(self) -> int:
        return hash((self.backend, self.available, self.reason, self.probed_at))


@dataclass(frozen=True)
class ExecOutcome:
    """Raw result of one worker run; the executor parses ``stdout`` as JSON.

    ``timed_out`` is True when the parent killed the worker at the wall
    clock; ``exit_code`` is the worker's (or the sandbox launcher's) exit
    status.
    """

    exit_code: int
    stdout: bytes
    stderr: bytes
    timed_out: bool = False


@runtime_checkable
class ExecBackend(Protocol):
    """A sandbox backend able to probe its capabilities and run one worker.

    Implementations: the secure bwrap backend and the explicit
    ``--unsafe-local-executor`` debug backend. ``probe()`` must be safe to
    call repeatedly (callers cache per store); ``execute()`` runs the worker
    of ``spec`` with ``stdin_payload`` on stdin and returns the collected
    outcome, enforcing ``spec.rlimits`` and ``spec.wall_clock_s``.
    """

    @property
    def name(self) -> str:
        """Stable backend identifier (e.g. ``"bwrap"``, ``"unsafe-local"``)."""
        ...

    def probe(self) -> CapabilityReport:
        """Probe capabilities; never raises for an unavailable sandbox."""
        ...

    def execute(self, spec: SandboxSpec, stdin_payload: bytes) -> ExecOutcome:
        """Run one worker to completion under the sandbox described by ``spec``."""
        ...
