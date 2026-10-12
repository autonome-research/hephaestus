# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Live network-gate regression on Docker Desktop, NOT the full CAD milestone.

Build a native immutable executor image, require its complete ordinary OCI probe
passes, then deliberately run ONLY the fixed trusted probe under bridge networking
and require the same host validator rejects it. Never run CAD in the negative
control, authorize a backend from it, or change the production backend factory.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import signal
import time
from pathlib import Path

# Bootstrap the checkout's core/src path before importing core or other helpers.
from macos_milestone_smoke import ROOT, Smoke, StageFailure, report_path  # isort: skip

from hephaestus.core.errors import SandboxDeniedError
from hephaestus.core.executor.sandbox import oci
from hephaestus.core.executor.sandbox.oci_protocol import PROBE_WORKER, PROTOCOL_VERSION
from hephaestus.core.executor.sandbox.oci_transfer import Receiver
from macos_prepare_executor import prepare
from macos_probe_executor import RecordingTransport, probe, resolve_image


def negative_control(smoke: Smoke, backend: oci.OciBackend) -> None:
    directory = smoke.directory / "negative-control"
    directory.mkdir(mode=0o700)
    spec = oci._probe_spec(directory)
    name = "heph-exec-" + secrets.token_hex(32)
    nonce = secrets.token_hex(32)
    inputs, collected = directory / "inputs", directory / "collected"
    inputs.mkdir(mode=0o700)
    collected.mkdir(mode=0o700)
    argv = list(
        oci.build_create_argv(
            backend.runtime,
            backend.image_ref,
            backend.platform,
            spec,
            name,
            identity=backend.identity,
            input_snapshot=inputs,
            storage_policy=backend.storage_policy_name,
            nonce=nonce,
        )
    )
    position = argv.index("--network") + 1
    if argv[position] != "none":
        raise StageFailure("ordinary profile unexpectedly changed")
    argv[position] = "bridge"  # Deliberate negative control; trusted probe only.
    payload = json.dumps({"nonce": nonce, "protocol_version": PROTOCOL_VERSION}).encode()
    smoke.report["negative_control"] = {
        "status": "running",
        "network_mode": "bridge",
        "authorizes_execution": False,
    }
    smoke.save()
    transport = RecordingTransport(smoke)
    created = transport.run(
        argv,
        input=b"",
        timeout=20,
        stdout_limit=65536,
        stderr_limit=16384,
        env=oci.RUNTIME_ENV,
    )
    if created.returncode or created.stderr:
        raise StageFailure("negative control creation failed")
    container_id = created.stdout.decode("ascii").strip()
    with Receiver(collected, nonce, PROBE_WORKER, backend.storage_policy) as receiver:
        started = transport.run(
            oci.build_start_argv(backend.runtime, container_id),
            input=payload,
            timeout=30,
            stdout_limit=65536,
            stderr_limit=16384,
            env=oci.RUNTIME_ENV,
            stdout_consumer=receiver.feed,
        )
        response_bytes = receiver.finish()
    _, raw = smoke.command((*smoke.docker, "inspect", "--format", "{{json .State}}", container_id))
    state = json.loads(raw)
    if (
        started.returncode
        or started.stderr
        or state["Running"]
        or state["ExitCode"]
        or state.get("OOMKilled")
    ):
        raise StageFailure("negative control probe failed to produce evidence")
    response = json.loads(response_bytes)
    (smoke.directory / "negative-control-probe.json").write_text(
        json.dumps(response, indent=2) + "\n"
    )
    try:
        oci._validate_probe_response(
            response, nonce, spec, directory, backend.identity, backend.storage_policy
        )
    except SandboxDeniedError as exc:
        if str(exc) != "OCI containment checks failed: network_isolated":
            raise StageFailure(f"negative control failed for another reason: {exc}") from exc
        smoke.report["negative_control"] = {
            "status": "passed",
            "network_mode": "bridge",
            "authorizes_execution": False,
            "detail": str(exc),
            "evidence": "negative-control-probe.json",
        }
        smoke.save()
    else:
        raise StageFailure("NETWORK-ENABLED NEGATIVE CONTROL WAS ACCEPTED")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", required=True)
    parser.add_argument("--wheelhouse", required=True, type=Path)
    args = parser.parse_args()
    directory = report_path(args.report_dir)
    wheels = args.wheelhouse.resolve()
    if not wheels.is_relative_to(ROOT) or not wheels.is_dir():
        parser.error("wheelhouse must be an existing directory inside this worktree")
    os.chdir(ROOT)
    smoke = Smoke(directory, wheels)
    smoke.report["scope"] = "network-containment-regression-only"
    smoke.report["network_regression_passed"] = False

    def interrupted(signum: int, frame: object) -> None:
        del frame
        raise KeyboardInterrupt(f"signal {signum}")

    signal.signal(signal.SIGTERM, interrupted)
    try:
        smoke.preflight()
        smoke.native_dependencies()
        image = resolve_image(smoke, prepare(smoke))
        backend = probe(smoke, image)
        negative_control(smoke, backend)
        smoke.report["network_regression_passed"] = True
    except (Exception, KeyboardInterrupt) as exc:
        smoke.report["network_regression_error"] = f"{type(exc).__name__}: {exc}"
    finally:
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, signal.SIG_IGN)
        smoke.cleanup()
        smoke.report["finished_at"] = time.time()
        smoke.report["network_regression_passed"] &= (
            smoke.report["checks"]["cleanup"]["status"] == "passed"
        )
        smoke.save()
    passed = smoke.report["network_regression_passed"]
    print(f"{'PASS' if passed else 'FAIL'} (network regression only): {directory / 'report.json'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
