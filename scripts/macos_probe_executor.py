# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Resolve daemon-attested local image digests and run unmodified OCI probes."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING

from hephaestus.core.executor.sandbox.oci import (
    OciBackend,
    OciRuntime,
    SubprocessTransport,
    TransportOutputLimit,
    TransportResult,
)

if TYPE_CHECKING:
    from macos_milestone_smoke import Smoke


class RecordingTransport:
    """Observe real transport; never change a request, response or security gate."""

    def __init__(self, smoke: Smoke) -> None:
        self.smoke = smoke
        self.real = SubprocessTransport()

    def run(
        self,
        argv: Sequence[str],
        *,
        input: bytes,
        timeout: float,
        stdout_limit: int,
        stderr_limit: int,
        env: Mapping[str, str],
        stdout_consumer: Callable[[bytes], None] | None = None,
    ) -> TransportResult:
        smoke = self.smoke
        if "create" in argv and "--name" in argv:
            smoke.owned.append(argv[argv.index("--name") + 1])
        smoke.sequence += 1
        stem = f"{smoke.sequence:03d}-oci"
        record: dict[str, object] = {
            "argv": list(argv),
            "log": f"logs/{stem}.json",
            "timeout_seconds": timeout,
            "stdout_limit": stdout_limit,
            "stderr_limit": stderr_limit,
            "input_bytes": len(input),
            "input_sha256": hashlib.sha256(input).hexdigest(),
        }
        smoke.report["commands"].append(record)
        smoke.save()
        started = time.monotonic()
        stdout = stderr = b""
        wire_hash = hashlib.sha256()
        wire_bytes = 0
        preview = bytearray()

        def consume(chunk: bytes) -> None:
            nonlocal wire_bytes
            wire_bytes += len(chunk)
            wire_hash.update(chunk)
            preview.extend(chunk[: max(0, 65536 - len(preview))])
            assert stdout_consumer is not None
            stdout_consumer(chunk)

        try:
            result = self.real.run(
                argv,
                input=input,
                timeout=timeout,
                stdout_limit=stdout_limit,
                stderr_limit=stderr_limit,
                env=env,
                stdout_consumer=consume if stdout_consumer else None,
            )
            stdout, stderr = result.stdout, result.stderr
            record["returncode"] = result.returncode
            if "create" in argv and "--name" in argv and result.returncode == 0:
                smoke.report.setdefault("container_ids", {})[argv[argv.index("--name") + 1]] = (
                    stdout.decode("ascii").strip()
                )
            return result
        except BaseException as exc:
            record["error"] = type(exc).__name__
            if isinstance(exc, TransportOutputLimit):
                record["overflow_stream"] = exc.stream
            stdout = getattr(exc, "stdout", b"")[:stdout_limit]
            stderr = getattr(exc, "stderr", b"")[:stderr_limit]
            raise
        finally:
            record["elapsed_seconds"] = time.monotonic() - started
            if stdout_consumer:
                record.update(
                    wire_bytes=wire_bytes,
                    wire_sha256=wire_hash.hexdigest(),
                    wire_prefix_base64=base64.b64encode(preview).decode("ascii"),
                )
            (smoke.logs / f"{stem}.json").write_text(
                json.dumps(
                    {
                        **record,
                        "stdout": stdout.decode("utf-8", errors="replace"),
                        "stderr": stderr.decode("utf-8", errors="replace"),
                    },
                    indent=2,
                )
                + "\n"
            )
            smoke.save()


def resolve_image(smoke: Smoke, tag: str, *, role: str = "executor") -> str:
    from macos_milestone_smoke import StageFailure

    # Docker Desktop's containerd image store attests locally built manifests
    # without a registry push. Do NOT compute or fabricate a RepoDigest. Runtimes
    # without this capability fail here; production defaults remain untouched.
    if role not in {"executor", "renderer"}:
        raise ValueError("unsupported image role")
    repository = "localhost/heph-macos-" + secrets.token_hex(16) + "/" + role
    local_tag = repository + ":owned"
    smoke.report["owned_image_tags"].append(local_tag)
    smoke.save()
    smoke.command((*smoke.docker, "tag", tag, local_tag))
    _, raw = smoke.command((*smoke.docker, "image", "inspect", local_tag))
    image = json.loads(raw)[0]
    digests = [ref for ref in image["RepoDigests"] if ref.startswith(repository + "@sha256:")]
    if len(digests) != 1:
        raise StageFailure("daemon did not attest exactly one local immutable RepoDigest")
    # Prove that the reference resolves, not merely that metadata lists it.
    _, resolved_raw = smoke.command((*smoke.docker, "image", "inspect", digests[0]))
    resolved = json.loads(resolved_raw)[0]
    if (
        resolved["Id"] != image["Id"]
        or resolved["Architecture"] != "arm64"
        or resolved["Os"] != "linux"
        or digests[0] not in resolved["RepoDigests"]
    ):
        raise StageFailure("digest resolution changed image identity or platform")
    smoke.report[role + "_image"] = {
        "reference": digests[0],
        "config_id": resolved["Id"],
        "platform": "linux/arm64",
        "repo_digests": resolved["RepoDigests"],
    }
    smoke.report[role + "_image_ref"] = digests[0]
    smoke.save()
    smoke.check("image_resolution", "passed", "daemon-attested locally resolvable RepoDigest")
    return digests[0]


def probe(smoke: Smoke, image_ref: str, *, storage_policy: str = "ordinary") -> OciBackend:
    from macos_milestone_smoke import StageFailure

    scratch = smoke.directory / "probe-scratch"
    scratch.mkdir(mode=0o700)
    # Keep all probe staging within this checkout. No backend behavior or
    # report is replaced; tempfile's scratch location is the only override.
    import tempfile

    previous = tempfile.tempdir
    tempfile.tempdir = str(scratch)
    try:
        backend = OciBackend(
            OciRuntime(
                "docker",
                Path(smoke.docker[0]),
                selector=("--context", "desktop-linux"),
                endpoint=smoke.docker[2],
                server_identity="Docker Desktop",
            ),
            image_ref,
            "linux/arm64",
            transport=RecordingTransport(smoke),
            storage_policy=storage_policy,
            deadline=smoke.deadline,
        )
        report = backend.probe()
    finally:
        tempfile.tempdir = previous
    smoke.report["containment_report"] = asdict(report)
    smoke.report["containment_response"] = backend.last_probe_response
    smoke.report["containment_terminal_state"] = dict(backend.last_terminal_state or {})
    smoke.report["containment_unsettled_creates"] = sorted(backend.unsettled_creates)
    smoke.report["containment_unreconciled_containers"] = sorted(backend.unreconciled_containers)
    smoke.report["containment_recorded_at"] = time.time()
    smoke.save()
    if not report.available:
        if report.reason and "network_isolated" in report.reason:
            from macos_network_diagnostic import diagnose

            try:
                diagnose(smoke)
            except Exception as exc:
                smoke.report.setdefault("network_diagnostic", {}).update(
                    status="failed", error=f"{type(exc).__name__}: {exc}"
                )
                smoke.save()
        raise StageFailure(str(report.reason))
    execution_identity = backend.execution_identity()
    smoke.report["execution_identity"] = execution_identity.to_json()
    smoke.report["execution_toolchain_hash"] = execution_identity.toolchain_hash
    smoke.save()
    smoke.check("containment", "passed", "unmodified manifest and all live OCI containment checks")
    return backend
