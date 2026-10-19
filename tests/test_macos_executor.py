# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Host-only regressions, never substitutes for live executor-stage evidence."""

from __future__ import annotations

import copy
import importlib
import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from hephaestus.core.errors import ConflictError, ValidationError
from hephaestus.core.executor import artifacts, runner
from hephaestus.core.hashing import sha256_bytes
from hephaestus.core.project_store import publication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
check = importlib.import_module("macos_executor_check")


def test_executor_missing_or_malformed_evidence_never_passes() -> None:
    report = {
        "security_precheck": {"status": "passed", "blockers": []},
        "checks": {name: {"status": "passed"} for name in check.EXECUTOR_REQUIRED},
    }
    assert not check.executor_passed(report)  # Labels alone are never evidence.
    for name in check.EXECUTOR_REQUIRED:
        for bad in ({}, None, {"status": True}, {"status": "blocked"}, {"status": "failed"}):
            assert not check.executor_passed({**report, "checks": {**report["checks"], name: bad}})
        assert not check.executor_passed(
            {**report, "checks": {k: v for k, v in report["checks"].items() if k != name}}
        )
    for bad in (None, [], {}, {"status": "passed"}, {"status": "passed", "blockers": ["quota"]}):
        assert not check.executor_passed({**report, "security_precheck": bad})
    assert not check.executor_passed({})


def synthetic_evidence_report() -> dict:
    """Unit-only schema specimen. No real image, CAD or cancellation is claimed."""
    digest = "a" * 64
    from hephaestus.core.executor.identity import ExecutionIdentity

    identity_record = ExecutionIdentity.for_oci(
        image_ref="registry.example/executor@sha256:" + digest,
        image_id="sha256:" + digest,
        platform="linux/arm64",
        runtime={
            "version": 1,
            "python": "3.13.7",
            "source_trees": {
                name: "sha256:" + digest for name in ("hephaestus-executor-runtime", "opstore")
            },
            "packages": {
                name: {"version": "0.1.0", "metadata_sha256": "sha256:" + digest}
                for name in (
                    "hephaestus-executor-runtime",
                    "opstore",
                    "build123d",
                    "cadquery-ocp-novtk",
                )
            },
        },
    )
    identity = identity_record.to_json()
    fingerprint = identity_record.toolchain_hash
    link = {"run_id": digest, "execution_fingerprint": fingerprint}
    runs = {}
    for index, (kind, exit_code) in enumerate(
        (("build", 0), ("explicit_cancel", 137), ("timeout", 137), ("failure", 0)), 1
    ):
        container = str(index) * 64
        runs[kind] = {
            **link,
            "container_id": container,
            "create_settled": True,
            "input_sha256": digest,
            "stdout_sha256": digest,
            "stderr_sha256": digest,
            "terminal_state": {"Running": False, "ExitCode": exit_code, "OOMKilled": False},
        }
        if kind in ("explicit_cancel", "timeout"):
            runs[kind].update(
                {
                    "in_flight": {"container_id": container, "Running": True, "sequence": 1},
                    "stop": {"kind": kind, "delivered": True, "sequence": 2},
                }
            )
    runs["failure"]["build_status"] = "failed"
    runs["build"].update(
        {
            "artifacts": {
                name: {"sha256": digest, "published_sha256": digest, "bytes": 10, "validated": True}
                for name in ("final.brep", "source_map.json")
            },
            "source_map_agrees": True,
            "kernel_geometry_validated": True,
            "kernel_validation_sha256": digest,
            "assembly_fingerprint": fingerprint,
            "publication_fingerprint": fingerprint,
            "freshness_fingerprint": fingerprint,
        }
    )
    from hephaestus.core.executor.sandbox.oci_protocol import REQUIRED_OCI_FEATURES

    return {
        "security_precheck": {"status": "passed", "blockers": []},
        "checks": {name: {"status": "passed"} for name in check.EXECUTOR_REQUIRED},
        "executor_evidence": {
            "schema_version": 3,
            **link,
            "identity": identity,
            "containment": {
                **link,
                "features": {name: True for name in REQUIRED_OCI_FEATURES},
                "raw_probe_sha256": digest,
                "terminal_state": {"Running": False, "ExitCode": 0, "OOMKilled": False},
            },
            "staging_quota": {
                **link,
                "byte_limit": 256 * 1024 * 1024,
                "inode_limit": 4096,
                "positive_control_sha256": digest,
                "byte_exhaustion_sha256": digest,
                "many_file_exhaustion_sha256": digest,
            },
            "runs": runs,
            "cleanup": {
                "run_id": digest,
                "owned_container_ids": [str(i) * 64 for i in range(1, 5)],
                "independently_absent_ids": [str(i) * 64 for i in range(1, 5)],
                "unsettled_creates": [],
                "remaining_image_tags": [],
                "clients_reaped": True,
                "children_reaped": True,
                "inventory_sha256": digest,
            },
        },
    }


@pytest.mark.parametrize("version", [1, 2, 3.0, True])
def test_old_report_identity_schema_is_not_execution_evidence(version):
    report = synthetic_evidence_report()
    report["executor_evidence"]["schema_version"] = version
    assert not check.executor_passed(report)


def mandatory_paths(value: dict, prefix: tuple = ()) -> list[tuple]:
    paths = []
    for key, child in value.items():
        path = (*prefix, key)
        paths.append(path)
        if isinstance(child, dict):
            paths.extend(mandatory_paths(child, path))
    return paths


@pytest.mark.parametrize("path", mandatory_paths(synthetic_evidence_report()))
def test_each_mandatory_evidence_record_is_required(path: tuple) -> None:
    report = synthetic_evidence_report()
    assert check.executor_passed(report)  # Structural test only; never used by the CLI.
    for operation in ("remove", "null"):
        broken = copy.deepcopy(report)
        target = broken
        for key in path[:-1]:
            target = target[key]
        if operation == "remove":
            del target[path[-1]]
        else:
            target[path[-1]] = None
        assert not check.executor_passed(broken), path


@pytest.mark.parametrize(
    "mutation",
    [
        "stale",
        "same_job",
        "late_observation",
        "oom",
        "false_exit",
        "artifact",
        "cleanup",
        "quota",
        "mutable_image",
    ],
)
def test_evidence_cross_links_and_types_refuse(mutation: str) -> None:
    report = synthetic_evidence_report()
    evidence = report["executor_evidence"]
    runs = evidence["runs"]
    if mutation == "stale":
        runs["build"]["publication_fingerprint"] = "b" * 64
    elif mutation == "same_job":
        runs["timeout"]["container_id"] = runs["explicit_cancel"]["container_id"]
    elif mutation == "late_observation":
        runs["explicit_cancel"]["in_flight"]["sequence"] = 3
    elif mutation == "oom":
        runs["build"]["terminal_state"]["OOMKilled"] = True
    elif mutation == "false_exit":
        runs["build"]["terminal_state"]["ExitCode"] = False
    elif mutation == "artifact":
        runs["build"]["artifacts"]["final.brep"]["published_sha256"] = "b" * 64
    elif mutation == "cleanup":
        evidence["cleanup"]["unsettled_creates"] = ["pending-create"]
    elif mutation == "quota":
        evidence["staging_quota"]["inode_limit"] = True
    else:
        evidence["identity"]["image_ref"] = "executor:latest"
    assert not check.executor_passed(report)


def test_failed_preparation_runs_no_worker_and_exits_one(tmp_path: Path) -> None:
    class LocalCheck(check.ExecutorCheck):
        def preflight(self):
            self.check("preflight", "passed", "test double, not live")

        def native_dependencies(self):
            raise RuntimeError("independent preparation refusal")

        def command(self, *args, **kwargs):
            pytest.fail("failed preparation must not execute workers")

    smoke = LocalCheck(tmp_path)
    assert smoke.run() == 1
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["accepted"] is False
    assert report["executor_stage_passed"] is False
    assert report["security_precheck"]["status"] == "pending"
    assert report["security_precheck"]["blockers"] == []
    assert "independent preparation refusal" in report["executor_error"]
    for stage in ("containment", "build", "cancellation"):
        assert report["checks"][stage]["status"] == "blocked"
    assert "executor_evidence" not in report
    assert report["owned_containers"] == []
    assert report["wheelhouse"]["revalidated"] is False


def test_cleanup_exception_is_failed_evidence(tmp_path: Path) -> None:
    class BrokenCleanup(check.ExecutorCheck):
        def preflight(self):
            raise KeyboardInterrupt("test interruption")

        def cleanup(self):
            raise RuntimeError("cannot confirm absence")

    smoke = BrokenCleanup(tmp_path)
    assert smoke.run() == 1
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["checks"]["cleanup"]["status"] == "failed"
    assert not report["executor_stage_passed"]
    assert not report["accepted"]


@pytest.mark.parametrize(
    "name", ["/etc/passwd", "../final.brep", "sub/final.brep", "", "unknown.brep"]
)
def test_artifact_names_are_closed(tmp_path: Path, name: str) -> None:
    with pytest.raises(ValidationError, match="allowlisted"):
        artifacts.read_artifact(tmp_path, name)


@pytest.mark.parametrize(
    "kind", ["missing", "symlink", "fifo", "directory", "hardlink", "empty", "oversize"]
)
@pytest.mark.timeout(5)  # Hang detector specifically for FIFO/nonregular opens.
def test_unsafe_artifact_refused_without_blocking(tmp_path: Path, kind: str, monkeypatch) -> None:
    monkeypatch.setattr(artifacts, "MAX_ARTIFACT_BYTES", 16)
    path = tmp_path / "final.brep"
    outside = tmp_path / "outside"
    outside.write_bytes(b"secret")
    if kind == "symlink":
        path.symlink_to(outside)
    elif kind == "fifo":
        os.mkfifo(path)
    elif kind == "directory":
        path.mkdir()
    elif kind == "hardlink":
        os.link(outside, path)
    elif kind == "empty":
        path.touch()
    elif kind == "oversize":
        path.write_bytes(b"x" * 17)
    with pytest.raises(ValidationError):
        artifacts.read_artifact(tmp_path, path.name)


def test_symlink_staging_directory_refused(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    (real / "final.brep").write_bytes(b"data")
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(ValidationError):
        artifacts.read_artifact(link, "final.brep")


def make_build(tmp_path: Path, monkeypatch):
    # Unit-only metadata stub; no host CAD packages are installed or executed.
    monkeypatch.setattr(runner, "toolchain_hash", lambda: "a" * 64)
    (tmp_path / "final.brep").write_bytes(b"unit-test-not-kernel-evidence")
    (tmp_path / "source_map.json").write_text("{}")
    return runner.assemble_build(
        runner.BuildRequest("test", "unit-only"),
        {
            "status": "ok",
            "artifacts": {"build": "final.brep", "source_map": "source_map.json"},
            "source_map": {},
        },
        out_dir=tmp_path,
    )


@pytest.mark.parametrize(
    "record",
    [
        {"status": "ok"},
        {"status": "ok", "artifacts": {"build": "final.brep"}},
        {"status": "failed", "artifacts": {"build": "final.brep"}},
        {"status": "failed", "artifacts": {"last_good": "/etc/passwd"}},
        {"status": "failed", "artifacts": {"last_good": "../last_good.brep"}},
        {"status": "failed", "artifacts": {"last_good": False}},
        {"status": "failed", "artifacts": {"surprise": "final.brep"}},
    ],
)
def test_assembly_refuses_missing_or_malformed_artifacts_before_toolchain(
    tmp_path: Path, record
) -> None:
    with pytest.raises(ValidationError, match="artifact"):
        runner.assemble_build(runner.BuildRequest("test", ""), record, out_dir=tmp_path)


@pytest.mark.parametrize("source", ["not-json", "[]", '{"wrong": true}', '{"x": false}'])
def test_source_map_file_must_match_response(tmp_path: Path, source: str) -> None:
    (tmp_path / "final.brep").write_bytes(b"data")
    (tmp_path / "source_map.json").write_text(source)
    with pytest.raises(ValidationError, match="source map"):
        runner.assemble_build(
            runner.BuildRequest("test", ""),
            {
                "status": "ok",
                "artifacts": {"build": "final.brep", "source_map": "source_map.json"},
                "source_map": {"x": 0},
            },
            out_dir=tmp_path,
        )


def test_publication_uses_validated_bytes_not_reopened_paths(tmp_path: Path, monkeypatch) -> None:
    build = make_build(tmp_path, monkeypatch)
    expected = dict(build.artifact_bytes)
    for path in build.artifact_files.values():
        path.unlink()
        path.symlink_to("/does/not/exist")
    installed = []

    def put(data, retention):
        installed.append(data)
        return sha256_bytes(data)

    store = SimpleNamespace(_store=SimpleNamespace(blobs=SimpleNamespace(put=put)))
    monkeypatch.setattr(publication, "record_artifact_refs", lambda *args: None)
    refs, _ = publication.Publisher._install_evidence(store, build, "test")
    assert set(refs) == set(expected)
    assert installed == [expected[ref] for ref in sorted(expected)]
    with pytest.raises(ConflictError, match="incomplete"):
        publication.Publisher._install_evidence(store, replace(build, artifact_bytes={}), "test")


def test_legacy_publication_cannot_escape_staging(tmp_path: Path, monkeypatch) -> None:
    build = make_build(tmp_path, monkeypatch)
    ref = build.result.artifact_ref
    build = replace(build, artifact_bytes=None, artifact_files={ref: tmp_path.parent / "secret"})
    with pytest.raises(ConflictError, match="outside"):
        publication.Publisher._install_evidence(SimpleNamespace(), build, "test")
