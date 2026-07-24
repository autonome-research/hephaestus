"""--unsafe-local-executor: a plain-subprocess ExecBackend for core debugging.

NOT a sandbox. Runs the worker as an ordinary child process with the parent's
environment and filesystem view. Every execution prints an explicit warning
to stderr, the capability report flags every isolation feature ``False``, and
registry content is refused outright (``unsafe_refused``) — registry code
may only run under a probed secure backend. ``heph serve`` refuses this
backend entirely (enforced by the server layer); it exists only for
user-invoked local debugging and for tests. Never a default.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time

from hephaestus.core.errors import UnsafeRefusedError
from hephaestus.core.executor.sandbox.base import (
    CapabilityReport,
    ExecOutcome,
    SandboxSpec,
)

UNSAFE_WARNING = (
    "WARNING: --unsafe-local-executor: running the build worker WITHOUT OS "
    "sandboxing (no filesystem, network, or process isolation). Use only for "
    "local debugging of code you trust."
)


class UnsafeLocalBackend:
    """Plain-subprocess backend: explicit, warned, flagged unsafe, never default."""

    unsafe: bool = True

    @property
    def name(self) -> str:
        return "unsafe-local"

    def probe(self) -> CapabilityReport:
        """Available by construction — but every isolation feature is False."""
        return CapabilityReport(
            backend=self.name,
            available=True,
            probed_at=time.time(),
            features={
                "os_isolation": False,
                "filesystem_isolation": False,
                "network_isolation": False,
                "process_isolation": False,
                "unsafe": True,
            },
        )

    def _refuse_registry(self, stdin_payload: bytes) -> None:
        """Fail closed: refuse registry-origin jobs (and unparseable payloads)."""
        try:
            job: object = json.loads(stdin_payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise UnsafeRefusedError(
                "unsafe-local backend refuses a job payload it cannot parse"
            ) from exc
        if not isinstance(job, dict):
            raise UnsafeRefusedError("unsafe-local backend refuses a non-object job payload")
        if job.get("origin") == "registry":
            raise UnsafeRefusedError(
                "unsafe-local backend refuses registry content; registry code may "
                "only execute under a probed secure sandbox"
            )

    def execute(self, spec: SandboxSpec, stdin_payload: bytes) -> ExecOutcome:
        """Run the worker as a plain subprocess with a wall-clock kill."""
        self._refuse_registry(stdin_payload)
        print(UNSAFE_WARNING, file=sys.stderr)
        try:
            completed = subprocess.run(
                list(spec.worker_cmd),
                input=stdin_payload,
                capture_output=True,
                timeout=spec.wall_clock_s,
                cwd=spec.rw_out_dir,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout if isinstance(exc.stdout, bytes) else b""
            stderr = exc.stderr if isinstance(exc.stderr, bytes) else b""
            return ExecOutcome(exit_code=-1, stdout=stdout, stderr=stderr, timed_out=True)
        return ExecOutcome(
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            timed_out=False,
        )
