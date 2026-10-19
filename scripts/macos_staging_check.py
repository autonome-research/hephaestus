# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Real canonical OCI quota/transfer controls, NOT CAD or milestone acceptance."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import time
from dataclasses import asdict
from pathlib import Path

from macos_milestone_smoke import ROOT, Smoke, StageFailure, report_path  # isort: skip

from hephaestus.core.errors import SandboxDeniedError
from hephaestus.core.executor.sandbox._oci_storage_worker import INPUT, OUTPUT, SOURCE_MAP
from hephaestus.core.executor.sandbox.base import Rlimits, SandboxSpec
from hephaestus.core.executor.sandbox.oci import OciBackend
from hephaestus.core.executor.sandbox.oci_protocol import PROTOCOL_VERSION
from hephaestus.core.executor.sandbox.oci_storage import capacity_valid, storage_valid
from hephaestus.core.executor.sandbox.oci_storage_policy import CONTROL_STORAGE, STORAGE_WORKER
from hephaestus.core.executor.sandbox.oci_transfer import InputAdmission
from macos_prepare_executor import prepare
from macos_probe_executor import probe, resolve_image

CHECKS = (
    "containment",
    "positive_output",
    "byte_exhaustion",
    "inode_exhaustion",
    "artifact_transfer",
    "cleanup",
)
MALFORMED = (
    "truncated",
    "bad-digest",
    "trailing",
    "oversized-header",
    "partial-body",
    "artifact-truncated-footer",
)
REJECTED = (*MALFORMED, "stdout-overflow")


def exhaustion_valid(value: object, operation: str) -> bool:
    if not isinstance(value, dict) or set(value) != {
        "path",
        "kind",
        "before",
        "exhausted",
        "restored",
        "allocated",
        "errno",
        "recovery",
    }:
        return False
    path = "/work" if operation.startswith("work") else "/tmp"
    inodes = operation.endswith("inodes")
    size, count = (
        (CONTROL_STORAGE.work_bytes, CONTROL_STORAGE.work_inodes)
        if path == "/work"
        else (CONTROL_STORAGE.tmp_bytes, CONTROL_STORAGE.tmp_inodes)
    )
    if (
        value["path"] != path
        or value["kind"] != ("inodes" if inodes else "bytes")
        or type(value["errno"]) is not int
        or value["errno"] != 28
        or value["recovery"] is not True
    ):
        return False
    before, after, restored = (value[k] for k in ("before", "exhausted", "restored"))
    if not all(capacity_valid(v, size, count) for v in (before, after, restored)):
        return False
    allocated = value["allocated"]
    if type(allocated) is not int or allocated <= 0 or restored != before:
        return False
    if inodes:
        return (
            allocated == before["available_inodes"]
            and after["available_inodes"] == 0
            and after["available_bytes"] >= size // 2
        )
    return (
        allocated == before["available_bytes"]
        and after["available_bytes"] == 0
        and after["available_inodes"] > 0
    )


def control(smoke: Smoke, backend: OciBackend, operation: str) -> dict:
    directory = smoke.directory / "controls" / operation
    directory.mkdir(parents=True, mode=0o700)
    sentinel = smoke.directory / f"{operation}.sentinel"
    sentinel_bytes = b"host sentinel outside collection\n"
    with sentinel.open("xb") as stream:
        stream.write(sentinel_bytes)
    inputs = ()
    if operation == "positive":
        admission = InputAdmission(CONTROL_STORAGE)
        admission.write(directory / "inputs", {"source.brep": INPUT})
        inputs = tuple(admission.names)
    spec = SandboxSpec(
        ("-m", STORAGE_WORKER), (), directory, Rlimits(15, 256 * 1024**2, 32), 30, inputs
    )
    record = {
        "operation": operation,
        "limits": asdict(spec.rlimits),
        "wall_seconds": spec.wall_clock_s,
        "passed": False,
    }
    smoke.report.setdefault("controls", {})[operation] = record
    smoke.save()
    try:
        outcome = backend.execute(
            spec,
            json.dumps({"protocol_version": PROTOCOL_VERSION, "operation": operation}).encode(),
        )
    except SandboxDeniedError as exc:
        record["refusal"] = str(exc)
        if operation not in MALFORMED or str(exc) != "OCI artifact transfer rejected":
            raise
    else:
        if operation in MALFORMED:
            raise StageFailure("malformed transfer was accepted")
        record["stdout"] = outcome.stdout.decode("utf-8")
        record["stderr"] = outcome.stderr.decode("utf-8")
        record["exit_code"] = outcome.exit_code
        record["timed_out"] = outcome.timed_out
        if operation == "stdout-overflow":
            if (
                outcome.timed_out
                or outcome.exit_code != 125
                or outcome.stdout
                or outcome.stderr != b"OCI worker output limit exceeded\n"
            ):
                raise StageFailure("finite overflow did not hit the attach output bound")
        elif outcome.timed_out or outcome.exit_code != 0:
            raise StageFailure("control did not complete")
        response = json.loads(outcome.stdout) if operation != "stdout-overflow" else None
        if operation != "stdout-overflow" and (
            not isinstance(response, dict)
            or type(response.get("pid")) is not int
            or response["pid"] != 1
            or response.get("operation") != operation
            or not storage_valid(response.get("storage"), CONTROL_STORAGE)
        ):
            raise StageFailure("control storage/PID evidence rejected")
        if operation == "positive":
            if (
                response.get("input_write_errno") != 30
                or response.get("input_sha256") != hashlib.sha256(INPUT).hexdigest()
                or response.get("input_bytes") != len(INPUT)
            ):
                raise StageFailure("input RO/identity proof failed")
            outputs = {}
            for name, expected in (("final.brep", OUTPUT), ("source_map.json", SOURCE_MAP)):
                data = (directory / name).read_bytes()
                if data != expected:
                    raise StageFailure("deterministic output mismatch")
                outputs[name] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            record["outputs"] = outputs
        elif operation.endswith(("bytes", "inodes")):
            if not exhaustion_valid(response.get("exhaustion"), operation):
                raise StageFailure("real ENOSPC/capacity/recovery evidence failed")
        elif (
            operation == "finite-stderr" and outcome.stderr != b"bounded storage diagnostic\n" * 256
        ):
            raise StageFailure("bounded attached logging mismatch")
    finally:
        record["container_id"] = backend.last_container_id
        record["terminal_state"] = dict(backend.last_terminal_state or {})
        record["effective_config"] = backend.last_effective_config
        record["input_records"] = {k: asdict(v) for k, v in backend.last_input_records.items()}
        record["transfer_records"] = {
            k: asdict(v) for k, v in backend.last_transfer_records.items()
        }
        record["transfer_observation"] = backend.last_transfer_observation
        record["unsettled_creates"] = sorted(backend.unsettled_creates)
        record["unreconciled_containers"] = sorted(backend.unreconciled_containers)
        smoke.save()
    if operation == "stdout-overflow":
        attached = [
            command
            for command in smoke.report["commands"]
            if "start" in command["argv"] and command["argv"][-1] == record["container_id"]
        ]
        if (
            len(attached) != 1
            or attached[0].get("error") != "TransportOutputLimit"
            or attached[0].get("overflow_stream") != "stdout"
        ):
            raise StageFailure("missing actual stdout overflow transport evidence")
        record["overflow_transport_log"] = attached[0]["log"]
    state = record["terminal_state"]
    allowed_exits = {0, 137} if operation == "stdout-overflow" else {0}
    if (
        set(state) != {"Running", "ExitCode", "OOMKilled"}
        or state["Running"] is not False
        or state["OOMKilled"] is not False
        or type(state["ExitCode"]) is not int
        or state["ExitCode"] not in allowed_exits
        or backend.unsettled_creates
        or backend.unreconciled_containers
    ):
        raise StageFailure("control lacks typed non-OOM terminal/settlement evidence")
    if operation in REJECTED:
        if any(directory.iterdir()) or list(directory.parent.glob(".heph-transfer-*")):
            raise StageFailure("rejected transfer retained partial or installed output")
        observation = record["transfer_observation"]
        if observation.get("installed") is not False or record["transfer_records"]:
            raise StageFailure("rejected transfer accepted artifacts")
        if operation in {"partial-body", "artifact-truncated-footer", "stdout-overflow"}:
            expected_body = len(OUTPUT) // 2 if operation == "partial-body" else len(OUTPUT)
            if (
                observation.get("created_files") != ["last_good.brep"]
                or type(observation.get("body_bytes")) is not int
                or observation["body_bytes"] != expected_body
            ):
                raise StageFailure("control did not receive actual expected artifact bytes")
        record["partial_collection_absent"] = True
    if sentinel.read_bytes() != sentinel_bytes:
        raise StageFailure("host sentinel changed")
    record["sentinel_sha256"] = hashlib.sha256(sentinel_bytes).hexdigest()
    record["sentinel_unchanged"] = True
    # Independent successful inventory, not an absence guess from inspect failure.
    _, inventory = smoke.command((*smoke.docker, "ps", "-a", "--no-trunc", "--format", "{{.ID}}"))
    if not backend.last_container_id or backend.last_container_id in inventory.splitlines():
        raise StageFailure("owned worker absence not confirmed")
    record["absence_confirmed"] = True
    record["passed"] = True
    smoke.save()
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", required=True)
    parser.add_argument("--wheelhouse", required=True, type=Path)
    args = parser.parse_args()
    wheels = args.wheelhouse.resolve()
    if not wheels.is_relative_to(ROOT) or not wheels.is_dir():
        parser.error("wheelhouse must exist inside this checkout")
    directory = report_path(args.report_dir)
    os.chdir(ROOT)
    smoke = Smoke(directory, wheels)
    smoke.report.update(
        scope="quota-bounded-staging",
        staging_stage_passed=False,
        executor_stage_passed=False,
        storage_policy=asdict(CONTROL_STORAGE),
    )
    smoke.report["host_source_sha256"] = {
        str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((ROOT / "scripts").glob("macos_*.py"))
    }
    for name in CHECKS:
        smoke.check(name, "blocked", "not run")
    backend = None
    stage = "preflight"

    def interrupted(signum, frame):
        del frame
        raise KeyboardInterrupt(f"signal {signum}")

    signal.signal(signal.SIGTERM, interrupted)
    try:
        smoke.preflight()
        stage = "native_dependencies"
        smoke.native_dependencies()
        stage = "executor_image"
        image = resolve_image(smoke, prepare(smoke))
        stage = "containment"
        backend = probe(smoke, image, storage_policy="control")
        stage = "positive_output"
        control(smoke, backend, "positive")
        smoke.check(stage, "passed", "deterministic input/output bytes and hashes; input EROFS")
        for stage, suffix in (("byte_exhaustion", "bytes"), ("inode_exhaustion", "inodes")):
            for mount in ("work", "tmp"):
                control(smoke, backend, f"{mount}-{suffix}")
            smoke.check(
                stage,
                "passed",
                "independent ENOSPC, exact observed capacities and recovery on both tmpfs mounts",
            )
        stage = "artifact_transfer"
        for operation in (*REJECTED, "finite-stderr"):
            control(smoke, backend, operation)
        smoke.check(
            stage,
            "passed",
            "partial-body/footer cleanup and finite output overflow; daemon logging disabled",
        )
    except (Exception, KeyboardInterrupt) as exc:
        smoke.check(stage, "failed", f"{type(exc).__name__}: {exc}")
    finally:
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, signal.SIG_IGN)
        smoke.cleanup()
        unsettled = [
            record["argv"]
            for record in smoke.report["commands"]
            if "create" in record["argv"] and record.get("returncode") != 0
        ]
        smoke.report["unsettled_create_requests"] = unsettled
        if (
            unsettled
            or smoke.report.get("containment_unsettled_creates")
            or smoke.report.get("containment_unreconciled_containers")
            or (
                backend is not None
                and (backend.unsettled_creates or backend.unreconciled_containers)
            )
        ):
            smoke.check(
                "cleanup", "failed", "unsettled daemon create requires external reconciliation"
            )
        smoke.report["finished_at"] = time.time()
        smoke.report["staging_stage_passed"] = all(
            smoke.report["checks"][name]["status"] == "passed" for name in CHECKS
        )
        smoke.save()
    passed = smoke.report["staging_stage_passed"]
    print(
        f"{'PASS' if passed else 'FAIL'} (quota-bounded-staging only): {directory / 'report.json'}"
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
