# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Collector regressions with explicitly synthetic artifacts/process observations."""

import importlib
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from hephaestus.core.executor.identity import ExecutionIdentity
from hephaestus.core.executor.sandbox.oci_storage_policy import DEFAULT_STORAGE
from hephaestus.core.project_store.layout import load_project, open_store
from opstore.gc import PREVIEW_RETENTION_CLASS

from opstore import canonical_json

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
live = importlib.import_module("macos_executor_live")


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def test_publication_collector_preserves_opstore_hash_prefix_and_canonical_bytes(tmp_path):
    (tmp_path / "hephaestus.toml").write_text('name = "synthetic"\n')
    layout = load_project(tmp_path)
    snapshots, files = {}, {}
    with open_store(layout) as store:
        for name, kind, data in (
            ("final.brep", "build", b"synthetic-not-kernel"),
            ("source_map.json", "source-map", b"{}"),
        ):
            blob = store.blobs.put(data, PREVIEW_RETENTION_CLASS)
            ref = f"artifact:{kind}:{blob}"
            path = tmp_path / name
            path.write_bytes(data if kind == "build" else b"{\n}\n")
            snapshots[ref], files[ref] = data, path
        built = SimpleNamespace(artifact_bytes=snapshots, artifact_files=files)
        result = live.publication_artifacts(store, built)
        assert result["source_map.json"]["sha256"] != result["source_map.json"]["transfer_sha256"]
        assert result["final.brep"]["published_sha256"] == live.digest(b"synthetic-not-kernel")
        snapshots[next(iter(snapshots))] = b"changed snapshot"
        with pytest.raises(live.StageFailure, match="bytes/hash"):
            live.publication_artifacts(store, built)


def test_roundtrip_uses_closed_content_named_ro_input_no_host_converter(tmp_path):
    # Same schema specimen as other evidence tests; not an attested executor.
    from test_macos_executor import synthetic_evidence_report

    identity = ExecutionIdentity(
        canonical_json(synthetic_evidence_report()["executor_evidence"]["identity"])
    )
    data = b"synthetic-not-kernel"
    ref = "artifact:build:sha256:" + live.digest(data)
    built = SimpleNamespace(
        artifact_bytes={ref: data}, result=SimpleNamespace(artifact_ref=ref, metrics=None)
    )

    class Synthetic:
        storage_policy = DEFAULT_STORAGE
        last_directory = tmp_path / "synthetic-operation"

        def execution_identity(self):
            return identity

        def execute(self, spec, payload):
            job = json.loads(payload)
            leaf = job["imports"]["roundtrip.step"]
            assert re.fullmatch(r"[0-9a-f]{32}\.brep", leaf)
            assert spec.input_files == (leaf,)
            assert (spec.rw_out_dir / "inputs" / leaf).read_bytes() == data
            assert spec.ro_binds == ()
            assert spec.worker_args == ("-m", "hephaestus.core.executor.worker")
            (spec.rw_out_dir / "final.brep").write_bytes(data)
            (spec.rw_out_dir / "source_map.json").write_text("{}")
            return SimpleNamespace(
                exit_code=0,
                timed_out=False,
                stdout=json.dumps(
                    {
                        "status": "ok",
                        "artifacts": {"build": "final.brep", "source_map": "source_map.json"},
                        "source_map": {},
                    }
                ).encode(),
            )

    record = live.validate_brep(SimpleNamespace(directory=tmp_path), Synthetic(), built)
    assert record["input_sha256"] == live.digest(data)


def synthetic_cleanup(tmp_path):
    cid = "a" * 64
    operation = tmp_path / "supervisor/operation-00"
    put(operation / "owner.json", {"pid": 123})
    put(operation / "reaped.json", {"pid": 123, "exitcode": 0})
    put(operation / "owner-final.json", {"commands_finished": True})
    journal = tmp_path / "supervisor/ownership/state.json"
    put(
        journal,
        {
            "launch_pending": False,
            "clients": {"456": {"reaped": True}},
            "containers": {"synthetic": {"id": cid, "pending": False, "absent": True}},
        },
    )
    report = {
        "executor_evidence": {
            "run_id": "b" * 64,
            "runs": {"build": {"container_id": cid, "operation": "supervisor/operation-00"}},
        }
    }
    smoke = SimpleNamespace(
        directory=tmp_path,
        docker=("synthetic-docker",),
        report=report,
        command=lambda argv: (0, ""),
    )
    return smoke, operation, journal


@pytest.mark.parametrize(
    "fault",
    [
        "journal",
        "owner",
        "reaped",
        "final",
        "pending",
        "client",
        "live_client",
        "live_group",
        "live_container",
        "unowned",
        "observer",
    ],
)
def test_cleanup_requires_actual_records_and_independent_absence(tmp_path, fault):
    smoke, operation, journal = synthetic_cleanup(tmp_path)
    if fault in {"journal", "owner", "reaped", "final"}:
        path = (
            journal
            if fault == "journal"
            else operation
            / {"owner": "owner.json", "reaped": "reaped.json", "final": "owner-final.json"}[fault]
        )
        path.unlink()
    elif fault in {"pending", "client", "unowned"}:
        state = json.loads(journal.read_text())
        if fault == "pending":
            state["launch_pending"] = True
        elif fault == "client":
            state["clients"]["456"]["reaped"] = False
        else:
            state["containers"] = {}
        put(journal, state)
    elif fault == "observer":
        runs = smoke.report["executor_evidence"]["runs"]
        runs["explicit_cancel"] = runs.pop("build")
    else:

        def command(argv):
            if argv[0] == "/bin/ps":
                return (
                    0,
                    "456 456\n"
                    if fault == "live_client"
                    else "789 456\n"
                    if fault == "live_group"
                    else "",
                )
            return 0, "a" * 64 + "\n" if fault == "live_container" else ""

        smoke.command = command
    with pytest.raises((live.StageFailure, FileNotFoundError)):
        live.verify_cleanup(smoke)
    assert "cleanup" not in smoke.report["executor_evidence"]


def test_synthetic_cleanup_collector_checks_all_owned_records(tmp_path):
    smoke, _, _ = synthetic_cleanup(tmp_path)
    live.verify_cleanup(smoke)
    assert smoke.report["executor_evidence"]["cleanup"]["clients_reaped"] is True
