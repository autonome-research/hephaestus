"""Explicit experimental renderer injection; no discovery, host CAD, store or mounts.

Caller resolves/freeze-checks a source build and supplies bounded BREP + closed
metadata. This API deliberately does NOT mint bundles or GLB. Publication must
still use its canonical resolver/_mint_bundle and source/table/GC gates.
"""

from __future__ import annotations

import hashlib
import tempfile
import threading
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from hephaestus.core.errors import SandboxDeniedError
from hephaestus.core.executor.identity import ExecutionIdentity
from hephaestus.core.executor.sandbox.base import Rlimits, SandboxSpec
from hephaestus.core.executor.sandbox.oci_supervisor import SupervisedOciBackend, SupervisorConfig
from hephaestus.core.executor.sandbox.oci_transfer import InputAdmission
from hephaestus.core.render.oci_protocol import (
    MAX_BREP,
    RENDER_VERSION,
    RENDER_WORKER,
    RenderRequest,
    read_request,
    request_bytes,
    validate_response,
)


@dataclass(frozen=True)
class RenderResult:
    """Validated bytes plus host-attested actual render image, separate from CAD identity."""

    data: bytes
    identity: ExecutionIdentity


class RenderService(Protocol):
    """Trusted host injection: validated rendering and a live renderer-image identity.

    This protocol is not worker-data attestation. Implementations must bind the
    returned identity to actual execution/cleanup; publication also checks that
    it agrees with the live identity before and after rendering.
    """

    def render(self, request: RenderRequest, brep: bytes) -> RenderResult: ...

    def execution_identity(self) -> ExecutionIdentity: ...


class OciRenderer:
    def __init__(self, config: SupervisorConfig) -> None:
        if (
            config.runtime_profile != "renderer"
            or config.platform != "linux/arm64"
            or config.storage_policy != "ordinary"
        ):
            raise ValueError("renderer requires explicit ARM64 ordinary renderer profile")
        self._busy = threading.Lock()
        self._config = config
        self._operations = 0
        self._identity: ExecutionIdentity | None = None
        self.supervisor = SupervisedOciBackend(config)
        self._ready = False
        self._poisoned = False

    def probe(self) -> RenderResult:
        if not self._busy.acquire(blocking=False):
            raise SandboxDeniedError("renderer operation already active")
        try:
            if self._poisoned:
                raise SandboxDeniedError("renderer ownership unresolved; session poisoned")
            report = self.supervisor.probe()
            if not report.available:
                raise SandboxDeniedError(str(report.reason))
            result = self._run({"version": RENDER_VERSION, "operation": "probe"}, None)
            self._ready = True
            return result
        finally:
            self._busy.release()

    def execution_identity(self) -> ExecutionIdentity:
        return self.supervisor.execution_identity()

    def render(self, request: Mapping[str, object], brep: bytes) -> RenderResult:
        if not self._ready:
            raise SandboxDeniedError("renderer requires fresh software EGL probe")
        if request.get("operation") == "probe":
            raise ValueError("use renderer probe")
        if not self._busy.acquire(blocking=False):
            raise SandboxDeniedError("renderer operation already active")
        try:
            return self._run(request, brep)
        finally:
            self._busy.release()

    def _run(self, request: object, brep: bytes | None) -> RenderResult:
        if self._poisoned:
            raise SandboxDeniedError("renderer ownership unresolved; session poisoned")
        payload = request_bytes(request)
        frozen = read_request(payload)
        if frozen["operation"] != "probe" and (
            not isinstance(brep, bytes)
            or not 0 < len(brep) <= MAX_BREP
            or hashlib.sha256(brep).hexdigest() != frozen["brep_sha256"]
        ):
            raise ValueError("renderer frozen BREP mismatch/bound")
        # Bounded per-operation journals, rather than exhausting a shared
        # client ledger halfway through cleanup. Previous owners are closed and
        # checked before allocating the next job; no record is discarded.
        if self._operations >= 16:
            raise SandboxDeniedError("renderer session operation limit; open a new owned session")
        if self._operations:
            try:
                self.supervisor.close()
                self.supervisor.require_settled()
            except BaseException:
                self._poisoned = True
                self._ready = False
                raise
            self.supervisor = SupervisedOciBackend(
                replace(
                    self._config,
                    directory=self._config.directory / f"render-{self._operations:02d}",
                )
            )
            if not self.supervisor.probe().available:
                raise SandboxDeniedError("fresh per-render containment probe failed")
            if self.supervisor.execution_identity() != self._identity:
                raise SandboxDeniedError("renderer image identity changed between operations")
        self._operations += 1
        with tempfile.TemporaryDirectory(
            prefix="render-input-", dir=self.supervisor.config.directory
        ) as temporary:
            directory = Path(temporary).resolve(strict=True)
            inputs = ()
            if brep is not None:
                InputAdmission(self.supervisor.storage_policy).write(
                    directory / "inputs", {"source.brep": brep}
                )
                inputs = ("source.brep",)
            spec = SandboxSpec(
                worker_args=("-m", RENDER_WORKER),
                ro_binds=(),
                rw_out_dir=directory,
                rlimits=Rlimits(cpu_seconds=120, address_space_bytes=2 * 1024**3, nproc=256),
                wall_clock_s=120,
                input_files=inputs,
            )
            outcome = self.supervisor.execute(spec, payload)
        if outcome.exit_code != 0 or outcome.timed_out or outcome.stderr:
            raise SandboxDeniedError("renderer failed, timed out or emitted diagnostics")
        validate_response(outcome.stdout, frozen)
        identity = self.supervisor.execution_identity()
        if outcome.execution_identity != identity or (
            self._identity is not None and identity != self._identity
        ):
            raise SandboxDeniedError("renderer image identity changed")
        self._identity = identity
        return RenderResult(outcome.stdout, identity)

    def cancel_active(self) -> bool:
        return self.supervisor.cancel_active()

    def close(self) -> None:
        self._ready = False
        self.supervisor.close()

    def __enter__(self) -> OciRenderer:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
