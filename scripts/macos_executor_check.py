# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Experimental real supervised macOS executor acceptance, not render/browser acceptance."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import time
from pathlib import Path

from macos_milestone_smoke import ROOT, Smoke, StageFailure, report_path

EXECUTOR_REQUIRED = ("containment", "build", "cancellation", "cleanup")


def _sha256(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _terminal(value: object, exit_code: int) -> bool:
    return (
        isinstance(value, dict)
        and value.get("Running") is False
        and value.get("OOMKilled") is False
        and type(value.get("ExitCode")) is int
        and value["ExitCode"] == exit_code
    )


def execution_evidence_complete(report: dict) -> bool:
    """Structural/cross-link gate, NOT an attestation of arbitrary supplied JSON.

    The live collector populates this schema from actual operations. No report
    import/override is offered. Schema 3 records ordinary failure as a failed
    build result with successful worker exit, not a fictitious exit code 1.
    """
    evidence = report.get("executor_evidence")
    if not isinstance(evidence, dict) or type(evidence.get("schema_version")) is not int:
        return False
    if evidence["schema_version"] != 3 or not _sha256(evidence.get("run_id")):
        return False
    identity = evidence.get("identity")
    if not isinstance(identity, dict):
        return False
    from hephaestus.core.errors import ValidationError
    from hephaestus.core.executor.identity import ExecutionIdentity

    from opstore import canonical_json

    try:
        trusted_shape = ExecutionIdentity(canonical_json(identity))
    except (ValidationError, ValueError, TypeError):
        return False
    # Same canonical identity as runner/publication, not a second report-only hash.
    fingerprint = trusted_shape.toolchain_hash
    if evidence.get("execution_fingerprint") != fingerprint:
        return False
    containment = evidence.get("containment")
    from hephaestus.core.executor.sandbox.oci_protocol import REQUIRED_OCI_FEATURES

    if (
        not isinstance(containment, dict)
        or containment.get("run_id") != evidence["run_id"]
        or containment.get("execution_fingerprint") != fingerprint
        or not isinstance(containment.get("features"), dict)
        or any(containment["features"].get(key) is not True for key in REQUIRED_OCI_FEATURES)
        or not _sha256(containment.get("raw_probe_sha256"))
        or not _terminal(containment.get("terminal_state"), 0)
    ):
        return False
    quota = evidence.get("staging_quota")
    if (
        not isinstance(quota, dict)
        or type(quota.get("byte_limit")) is not int
        or not 0 < quota["byte_limit"] <= 256 * 1024 * 1024
        or type(quota.get("inode_limit")) is not int
        or not 0 < quota["inode_limit"] <= 4096
        or quota.get("execution_fingerprint") != fingerprint
        or quota.get("run_id") != evidence["run_id"]
        or not all(
            _sha256(quota.get(key))
            for key in (
                "positive_control_sha256",
                "byte_exhaustion_sha256",
                "many_file_exhaustion_sha256",
            )
        )
    ):
        return False
    runs = evidence.get("runs")
    if not isinstance(runs, dict) or set(runs) != {
        "build",
        "explicit_cancel",
        "timeout",
        "failure",
    }:
        return False
    containers = []
    for kind, expected_exit in (
        ("build", 0),
        ("explicit_cancel", 137),
        ("timeout", 137),
        ("failure", 0),
    ):
        run = runs[kind]
        if not isinstance(run, dict):
            return False
        if (
            run.get("run_id") != evidence["run_id"]
            or run.get("execution_fingerprint") != fingerprint
            or run.get("create_settled") is not True
            or not all(
                _sha256(run.get(key))
                for key in ("container_id", "input_sha256", "stdout_sha256", "stderr_sha256")
            )
            or not _terminal(run.get("terminal_state"), expected_exit)
        ):
            return False
        if kind == "failure" and run.get("build_status") != "failed":
            return False
        containers.append(run["container_id"])
        if kind in ("explicit_cancel", "timeout"):
            observed = run.get("in_flight")
            stop = run.get("stop")
            if (
                not isinstance(observed, dict)
                or observed.get("container_id") != run["container_id"]
                or observed.get("Running") is not True
                or type(observed.get("sequence")) is not int
                or observed["sequence"] < 0
                or not isinstance(stop, dict)
                or stop.get("kind") != kind
                or stop.get("delivered") is not True
                or type(stop.get("sequence")) is not int
                or stop["sequence"] <= observed["sequence"]
            ):
                return False
    if len(set(containers)) != len(containers):
        return False
    build = runs["build"]
    artifacts = build.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != {"final.brep", "source_map.json"}:
        return False
    for name, limit in (("final.brep", 64 * 1024 * 1024), ("source_map.json", 8 * 1024 * 1024)):
        artifact = artifacts[name]
        if (
            not isinstance(artifact, dict)
            or not _sha256(artifact.get("sha256"))
            or artifact.get("published_sha256") != artifact["sha256"]
            or artifact.get("validated") is not True
            or type(artifact.get("bytes")) is not int
            or not 0 < artifact["bytes"] <= limit
        ):
            return False
    if (
        build.get("source_map_agrees") is not True
        or build.get("kernel_geometry_validated") is not True
        or build.get("assembly_fingerprint") != fingerprint
        or build.get("publication_fingerprint") != fingerprint
        or build.get("freshness_fingerprint") != fingerprint
        or not _sha256(build.get("kernel_validation_sha256"))
    ):
        return False
    cleanup = evidence.get("cleanup")
    return (
        isinstance(cleanup, dict)
        and cleanup.get("run_id") == evidence["run_id"]
        and cleanup.get("owned_container_ids") == containers
        and cleanup.get("independently_absent_ids") == containers
        and cleanup.get("unsettled_creates") == []
        and cleanup.get("remaining_image_tags") == []
        and cleanup.get("clients_reaped") is True
        and cleanup.get("children_reaped") is True
        and _sha256(cleanup.get("inventory_sha256"))
    )


def executor_passed(report: dict) -> bool:
    """Missing/malformed evidence or any security blocker prevents success."""
    checks = report.get("checks")
    precheck = report.get("security_precheck")
    return (
        isinstance(precheck, dict)
        and precheck.get("status") == "passed"
        and precheck.get("blockers") == []
        and isinstance(checks, dict)
        and all(
            isinstance(checks.get(name), dict) and checks[name].get("status") == "passed"
            for name in EXECUTOR_REQUIRED
        )
        and execution_evidence_complete(report)
    )


def require_security_ready(smoke: Smoke) -> None:
    """Snapshot implemented contracts; fresh runtime gates below still must pass."""
    sources = {
        "core/src/hephaestus/core/project_store/publication.py",
        "core/src/hephaestus/core/executor/sandbox/oci_launcher.py",
        "core/src/hephaestus/core/executor/artifacts.py",
        "core/src/hephaestus/core/executor/runner.py",
        "core/src/hephaestus/core/executor/identity.py",
        "core/src/hephaestus/core/executor/sandbox/oci_identity.py",
        "core/src/hephaestus/core/executor/sandbox/oci_supervisor.py",
        "core/src/hephaestus/core/executor/sandbox/oci_ownership.py",
        "core/src/hephaestus/core/executor/cancellation.py",
        "server/src/hephaestus/http/runtime.py",
        "scripts/macos_executor_check.py",
        "scripts/macos_executor_live.py",
        "core/tests/test_sandbox_oci.py",
        "tests/test_macos_executor.py",
    }
    smoke.report["security_precheck"] = {
        "status": "pending",
        "blockers": [],
        "source_sha256": {
            path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in sorted(sources)
        },
        "artifact_read_hardening": "confined bounded reads and immutable publication snapshots",
        "terminal_state_hardening": "typed Running/ExitCode/OOMKilled required; OOM rejected",
        "execution_identity": "manifest-4 image identity; freshly collected in this report",
        "create_cleanup_hardening": (
            "explicit per-operation durable owner implemented; unknown create settlement "
            "and abrupt owner/client death retain pending state"
        ),
        "acceptance_evidence": "fresh real storage, supervised CAD and publication required",
    }
    smoke.report["executor_stage_passed"] = False
    smoke.save()


def run_executor_stages(smoke: Smoke) -> None:
    from macos_executor_live import document, run_cad
    from macos_prepare_executor import prepare
    from macos_probe_executor import probe, resolve_image
    from macos_staging_check import REJECTED, control

    require_security_ready(smoke)
    smoke.native_dependencies()
    smoke.report["wheelhouse"] = {"path": str(smoke.wheelhouse), "revalidated": True}
    image = resolve_image(smoke, prepare(smoke))
    backend = probe(smoke, image, storage_policy="control")
    for operation in (
        "positive",
        "work-bytes",
        "tmp-bytes",
        "work-inodes",
        "tmp-inodes",
        *REJECTED,
        "finite-stderr",
    ):
        control(smoke, backend, operation)
    smoke.report["staging_controls_passed"] = True
    smoke.save()
    evidence = run_cad(smoke, image)
    controls = smoke.report["controls"]
    evidence["staging_quota"] = {
        "run_id": evidence["run_id"],
        "execution_fingerprint": evidence["execution_fingerprint"],
        "byte_limit": backend.storage_policy.work_bytes + backend.storage_policy.tmp_bytes,
        "inode_limit": backend.storage_policy.work_inodes + backend.storage_policy.tmp_inodes,
        "positive_control_sha256": document(
            smoke.directory / "quota-positive.json", controls["positive"]
        ),
        "byte_exhaustion_sha256": document(
            smoke.directory / "quota-bytes.json",
            {k: controls[k] for k in ("work-bytes", "tmp-bytes")},
        ),
        "many_file_exhaustion_sha256": document(
            smoke.directory / "quota-inodes.json",
            {k: controls[k] for k in ("work-inodes", "tmp-inodes")},
        ),
    }
    if backend.execution_identity().toolchain_hash != evidence["execution_fingerprint"]:
        raise StageFailure("storage/CAD execution identity mismatch")
    smoke.report["security_precheck"]["status"] = "passed"
    smoke.save()


def finish_executor(smoke: Smoke) -> None:
    from macos_executor_live import verify_cleanup

    # A failed/unknown trusted preparation create must not become absence success.
    uncertain = [
        c["argv"]
        for c in smoke.report["commands"]
        if "create" in c["argv"] and c.get("returncode") != 0
    ]
    smoke.report["unsettled_create_requests"] = uncertain
    if uncertain:
        raise StageFailure("unsettled preparation/control create; retain exact owned names")
    if smoke.report.get("executor_evidence"):
        if smoke.report["checks"]["cleanup"]["status"] != "passed":
            raise StageFailure("owned resource cleanup failed")
        verify_cleanup(smoke)
    smoke.report["executor_stage_passed"] = executor_passed(smoke.report)
    smoke.save()


class ExecutorCheck(Smoke):
    def cleanup(self) -> None:
        super().cleanup()
        if self.docker:
            _, raw = self.command(
                (*self.docker, "ps", "-a", "--no-trunc", "--format", "{{json .}}")
            )
            self.report["final_containers"] = [json.loads(line) for line in raw.splitlines()]
        finish_executor(self)
        self.save()

    def run(self) -> int:
        self.report["scope"] = "experimental-supervised-executor"
        self.report["executor_stage_passed"] = False
        self.report["wheelhouse"] = {
            "path": str(self.wheelhouse),
            "revalidated": False,
            "reason": "not consumed yet",
        }
        self.save()
        stage = "preflight"
        try:
            self.preflight()
            stage = "executor"
            run_executor_stages(self)
        except (Exception, KeyboardInterrupt) as exc:
            self.report["executor_error"] = f"{type(exc).__name__}: {exc}"
            if stage == "preflight":
                self.check(stage, "failed", str(exc))
            else:
                self.check(stage, "failed", f"{type(exc).__name__}: {exc}")
        finally:
            old = {
                sig: signal.signal(sig, signal.SIG_IGN) for sig in (signal.SIGINT, signal.SIGTERM)
            }
            try:
                self.cleanup()
            except Exception as exc:
                self.check("cleanup", "failed", f"{type(exc).__name__}: {exc}")
            finally:
                for sig, handler in old.items():
                    signal.signal(sig, handler)
            self.report["finished_at"] = time.time()
            self.report["executor_stage_passed"] = executor_passed(self.report)
            self.save()
        return 0 if self.report["executor_stage_passed"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", required=True)
    parser.add_argument("--wheelhouse", required=True, type=Path)
    args = parser.parse_args()
    try:
        directory = report_path(args.report_dir)
    except ValueError as exc:
        parser.error(str(exc))
    wheels = args.wheelhouse.resolve()
    if not wheels.is_relative_to(ROOT) or not wheels.is_dir():
        parser.error("wheelhouse must be an existing directory inside this worktree")
    os.chdir(ROOT)

    def interrupted(signum: int, frame: object) -> None:
        del frame
        raise KeyboardInterrupt(f"received signal {signum}")

    signal.signal(signal.SIGTERM, interrupted)
    check = ExecutorCheck(directory, wheels)
    code = check.run()
    print(f"{'PASS' if code == 0 else 'FAIL'} (executor stage): {directory / 'report.json'}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
