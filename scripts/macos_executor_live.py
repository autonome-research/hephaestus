# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Local real-build acceptance collector. No host kernel, report import or provider."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

from hephaestus.core.errors import ValidationError
from hephaestus.core.executor.cancellation import ExecutionCancelled
from hephaestus.core.executor.identity import IDENTITY_METADATA_KEY
from hephaestus.core.executor.runner import BuildRequest, assemble_build, run_build, worker_args
from hephaestus.core.executor.sandbox.base import Rlimits, SandboxSpec
from hephaestus.core.executor.sandbox.oci import (
    RUNTIME_ENV,
    OciIdentity,
    OciRuntime,
    SubprocessTransport,
)
from hephaestus.core.executor.sandbox.oci_ownership import OwnershipJournal
from hephaestus.core.executor.sandbox.oci_supervisor import (
    EvidenceTransport,
    SupervisedOciBackend,
    SupervisorConfig,
)
from hephaestus.core.executor.sandbox.oci_transfer import InputAdmission
from hephaestus.core.project_store.layout import load_project, open_store
from hephaestus.core.project_store.publication import Publisher
from hephaestus.core.project_store.store import blob_hash_of_ref
from macos_milestone_smoke import StageFailure

# Independently authored analytic fixture: disjoint cuboids, 120 + 42 mm^3.
TWO_SOLIDS = """left = Box(4, 5, 6)
right = Pos(12, 0, 0) * Box(2, 3, 7)
part.geometry = Compound(children=[left, right])
check("two_solids", lambda m: len(part.geometry.solids()) == 2)
check("volume", lambda m: abs(part.geometry.volume - 162.0) < 1e-8)
"""
# Ordinary Python work inside the fixed CAD worker. Finite CPU/wall ceilings are
# enforced by the real backend; no import, sleep, subprocess or entrypoint escape.
BUSY = "part.geometry = Box(1, 1, 1)\nwhile True:\n    value = 1 + 1\n"
FAILURE = 'part.geometry = Box(1, 2, 3)\nraise ValueError("independent ordinary failure control")\n'
LIMITS = Rlimits(120, 2 * 1024**3, 256)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def document(path: Path, value: object) -> str:
    data = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(data)
    return digest(data)


def load(path: Path) -> dict:
    data = path.read_bytes()
    if len(data) > 8 * 1024**2:
        raise StageFailure(f"evidence bound: {path}")
    return json.loads(data)


def require(value: object, reason: str) -> None:
    if not value:
        raise StageFailure(reason)


class _Started(Exception):
    pass


def observed_build(backend, request, out, smoke, *, cancel):
    """Wait on actual daemon start events, not elapsed sleeps or progress polling.

    The event stream is independently owned/reaped and never authorizes execution.
    Only observe_running's exact settled execution ID and typed inspection do so.
    --since closes the watcher startup race; old probes cannot match this job.
    """
    event_dir = smoke.directory / ("cancel-events" if cancel else "timeout-events")
    event_dir.mkdir(mode=0o700)
    since = str(int(time.time()))
    previous = backend.last_directory
    stopped = threading.Event()
    observation = {}

    def watch():
        buffer = bytearray()
        with OwnershipJournal(event_dir / "ownership", backend.config.binding()) as journal:
            transport = EvidenceTransport(SubprocessTransport(ownership=journal), event_dir)

            def consume(chunk):
                buffer.extend(chunk)
                require(len(buffer) <= 65536, "daemon event line limit")
                while b"\n" in buffer:
                    line, _, tail = buffer.partition(b"\n")
                    buffer[:] = tail
                    event = json.loads(line)
                    directory = backend.last_directory
                    if (
                        directory is None
                        or directory == previous
                        or not (directory / "executing.json").exists()
                    ):
                        continue
                    state = load(backend.config.directory / "ownership/state.json")
                    ids = [
                        r["id"]
                        for r in state["containers"].values()
                        if not r["pending"] and not r["absent"]
                    ]
                    if event.get("Actor", {}).get("ID") not in ids:
                        continue
                    observation.update(backend.observe_running())
                    document(event_dir / "start-event.json", event)
                    if cancel:
                        require(backend.cancel_active(), "explicit cancellation was not delivered")
                    raise _Started

            try:
                transport.run(
                    (
                        *smoke.docker,
                        "events",
                        "--since",
                        since,
                        "--filter",
                        "type=container",
                        "--filter",
                        "event=start",
                        "--format",
                        "{{json .}}",
                    ),
                    input=b"",
                    timeout=100,
                    stdout_limit=65536,
                    stderr_limit=65536,
                    env=RUNTIME_ENV,
                    stdout_consumer=consume,
                )
            except _Started:
                pass
            finally:
                stopped.set()
            journal.require_clean()
        require(observation, "no positively observed running worker")

    with ThreadPoolExecutor(max_workers=2) as pool:
        watcher = pool.submit(watch)
        job = pool.submit(run_build, request, backend=backend, out_dir=out, rlimits=LIMITS)
        try:
            watcher.result(timeout=110)
            try:
                job.result(timeout=230)
            except ExecutionCancelled:
                require(cancel, "timeout was misreported as user cancellation")
            except ValidationError as exc:
                require(not cancel and "exceeded the wall clock" in str(exc), str(exc))
            else:
                raise StageFailure("long-running control completed unexpectedly")
        finally:
            if not job.done():
                backend.cancel_active("caller_cancel")
    require(stopped.is_set(), "event watcher not reaped")
    return observation


def operation_record(smoke, backend, kind, link):
    directory = backend.last_directory
    require(directory is not None, "missing operation directory")
    result = load(directory / "result.json")
    request = load(directory / "request.json")
    commands = [load(p) for p in sorted(directory.glob("command-*.json"))]
    cid = result.get("container_id")
    attach = [c for c in commands if "start" in c["argv"] and c["argv"][-1] == cid]
    require(len(attach) == 1, "missing unique actual attach evidence")
    wire = attach[0].get("wire", attach[0]["stdout"])
    state = load(backend.config.directory / "ownership/state.json")
    records = [r for r in state["containers"].values() if r["id"] == cid]
    require(
        len(records) == 1 and not records[0]["pending"] and records[0]["absent"],
        "unsettled execution",
    )
    require(
        result.get("identity") == smoke.report["executor_evidence"]["identity"],
        "operation identity mismatch",
    )
    record = {
        **link,
        "container_id": cid,
        "create_settled": True,
        "input_sha256": request["input_sha256"],
        "stdout_sha256": wire["sha256"],
        "stderr_sha256": attach[0]["stderr"]["sha256"],
        "terminal_state": result["terminal"],
        "operation": str(directory.relative_to(smoke.directory)),
        "result_sha256": digest((directory / "result.json").read_bytes()),
        "limits": request["limits"],
        "wall_clock_s": request["wall_clock_s"],
    }
    if kind in ("explicit_cancel", "timeout"):
        running = load(directory / "running.json")
        kills = [
            c
            for c in commands
            if "kill" in c["argv"] and c["argv"][-1] == cid and c.get("returncode") == 0
        ]
        require(len(kills) == 1, "no actual successful container kill")
        if kind == "explicit_cancel":
            stop = load(directory / "stop-received.json")
            request_stop = load(directory / "stop-request.json")
            require(
                stop["reason"] == request_stop["reason"] == "user_cancel",
                "not an explicit user stop",
            )
            require(
                running["monotonic_ns"] <= request_stop["monotonic_ns"] <= stop["monotonic_ns"],
                "cancel order",
            )
            require(result["outcome"] == "user_cancel", "missing owner cancellation outcome")
        else:
            require(
                result["outcome"] == "timeout" and attach[0].get("error") == "TransportTimeout",
                "not a wall timeout",
            )
        record["in_flight"] = {
            "container_id": running["container_id"],
            "Running": running["state"]["Running"],
            "sequence": 1,
        }
        record["stop"] = {"kind": kind, "delivered": True, "sequence": 2}
    return record


def publication_artifacts(store, built):
    artifacts = {}
    for ref, data in built.artifact_bytes.items():
        name = built.artifact_files[ref].name
        stored = store.blobs.get(blob_hash_of_ref(ref))
        require(
            stored == data and digest(data) == ref.rsplit(":", 1)[-1],
            "published artifact bytes/hash mismatch",
        )
        raw = built.artifact_files[ref].read_bytes()
        artifacts[name] = {
            "sha256": digest(data),
            "published_sha256": digest(stored),
            "bytes": len(data),
            "validated": True,
            "transfer_sha256": digest(raw),
            "transfer_bytes": len(raw),
        }
    require(set(artifacts) == {"final.brep", "source_map.json"}, "missing publication artifacts")
    return artifacts


def validate_brep(smoke, backend, built):
    """Re-read actual exported BREP in a second fixed build worker, never on Mac.

    This uses the existing preconverted BREP input contract directly; it does not
    mislabel BREP as raw STEP or invoke the host STEP converter. No publication
    of this diagnostic build is attempted.
    """
    out = smoke.directory / "brep-roundtrip"
    out.mkdir(mode=0o700)
    data = built.artifact_bytes[built.result.artifact_ref]
    admission = InputAdmission(backend.storage_policy)
    leaf = digest(data)[:32] + ".brep"
    admission.write(out / "inputs", {leaf: data})
    script = 'part.geometry = import_step("roundtrip.step")\n'
    request = BuildRequest("roundtrip", script, wall_clock_s=120)
    job = {
        "part": request.part,
        "script": script,
        "out_dir": ".",
        "mode": "build",
        "origin": "local",
        "globals_source": None,
        "part_overrides": {},
        "project_overrides": {},
        "imports": {"roundtrip.step": leaf},
        "import_errors": {},
    }
    outcome = backend.execute(
        SandboxSpec(worker_args(), (), out, LIMITS, 120, tuple(admission.names)),
        json.dumps(job).encode(),
    )
    require(outcome.exit_code == 0 and not outcome.timed_out, "BREP roundtrip worker failed")
    verified = assemble_build(
        request,
        json.loads(outcome.stdout),
        out_dir=out,
        execution_identity=backend.execution_identity(),
    )
    require(
        verified.result.status == "ok" and verified.result.metrics == built.result.metrics,
        "exported BREP kernel re-read differs from original metrics",
    )
    return {
        "input_sha256": digest(data),
        "operation": str(backend.last_directory.relative_to(smoke.directory)),
        "result_sha256": document(
            smoke.directory / "brep-roundtrip-result.json", verified.result.to_json()
        ),
    }


def run_cad(smoke, image):
    config = SupervisorConfig(
        OciRuntime(
            "docker",
            Path(smoke.docker[0]),
            selector=("--context", "desktop-linux"),
            endpoint=smoke.docker[2],
            server_identity="Docker Desktop",
        ),
        image,
        "linux/arm64",
        smoke.directory / "supervisor",
        OciIdentity(os.getuid(), os.getgid()),
        deadline=smoke.deadline,
    )
    with SupervisedOciBackend(config) as backend:
        capability = backend.probe()
        require(capability.available, str(capability.reason))
        identity = backend.execution_identity()
        link = {"run_id": digest(os.urandom(32)), "execution_fingerprint": identity.toolchain_hash}
        probe_dir = backend.last_directory
        probe = load(probe_dir / "result.json")
        evidence = {
            "schema_version": 3,
            **link,
            "identity": identity.to_json(),
            "containment": {
                **link,
                "features": dict(capability.features),
                "raw_probe_sha256": document(smoke.directory / "cad-probe.json", probe["probe"]),
                "terminal_state": probe["terminal"],
            },
            "runs": {},
        }
        smoke.report["executor_evidence"] = evidence
        smoke.save()
        project = smoke.directory / "project"
        (project / "parts").mkdir(parents=True)
        (project / "hephaestus.toml").write_text('name = "macos-executor-control"\nunits = "mm"\n')
        (project / "parts/two_solids.py").write_text(TWO_SOLIDS)
        layout = load_project(project)
        with open_store(layout) as store:
            publisher = Publisher(layout, store, backend=backend)
            frozen = publisher.freeze_inputs("two_solids")
            built = run_build(
                BuildRequest("two_solids", frozen.script, wall_clock_s=120),
                backend=backend,
                out_dir=smoke.directory / "build",
                rlimits=LIMITS,
            )
            record = operation_record(smoke, backend, "build", link)
            document(smoke.directory / "build-result.json", built.result.to_json())
            require(built.result.status == "ok", f"CAD failed: {built.result.error}")
            metrics = built.result.metrics
            require(
                metrics is not None
                and metrics.solids == 2
                and abs(metrics.volume_mm3 - 162.0) < 1e-8
                and metrics.sealed,
                "kernel metrics disagree with analytic cuboids",
            )
            require(
                built.result.checks and all(c.passed for c in built.result.checks.values()),
                "kernel checks failed",
            )
            require(
                built.source_map and built.geometry_index_json, "missing source map/geometry index"
            )
            require(
                built.result.input_hashes.script == "sha256:" + digest(TWO_SOLIDS.encode())
                and set(built.source_map["bindings"]) == {"left", "right"}
                and built.source_map["bindings"]["left"][0]["line"] == 1
                and built.source_map["bindings"]["right"][0]["line"] == 2
                and set(built.geometry_index_json["labels"]) == {"left", "right"},
                "source-map/source/geometry namespace mismatch",
            )
            published = publisher.publish_build(built, op_id="independent-two-solid-build")
            require(published.kind == "current", f"publication refused: {published}")
            current = publisher.current_result("two_solids")
            freshness = publisher.freshness("two_solids")
            require(
                current is not None and freshness is not None and freshness.fresh,
                "published build is not fresh",
            )
            require(
                current.metadata[IDENTITY_METADATA_KEY] == identity.canonical,
                "published execution identity mismatch",
            )
            document(smoke.directory / "published-result.json", current.to_json())
            document(smoke.directory / "freshness.json", asdict(freshness))
            artifacts = publication_artifacts(store, built)
            validation = {
                "brep_roundtrip": validate_brep(smoke, backend, built),
                "metrics": metrics.to_json(),
                "checks": {k: v.to_json() for k, v in built.result.checks.items()},
                "source_map": built.source_map,
                "geometry_index": built.geometry_index_json,
            }
            record.update(
                artifacts=artifacts,
                source_map_agrees=True,
                kernel_geometry_validated=True,
                kernel_validation_sha256=document(
                    smoke.directory / "kernel-validation.json", validation
                ),
                assembly_fingerprint=built.result.input_hashes.toolchain,
                publication_fingerprint=current.input_hashes.toolchain,
                freshness_fingerprint=identity.toolchain_hash,
            )
            evidence["runs"]["build"] = record
            smoke.check(
                "build",
                "passed",
                "real two-solid kernel build; validated bytes, current publication "
                "and fresh image identity",
            )
        for kind, cancel in (("explicit_cancel", True), ("timeout", False)):
            (project / f"parts/{kind}.py").write_text(BUSY)
            observed_build(
                backend,
                BuildRequest(kind, BUSY, wall_clock_s=90 if cancel else 20),
                smoke.directory / kind,
                smoke,
                cancel=cancel,
            )
            evidence["runs"][kind] = operation_record(smoke, backend, kind, link)
            require(
                not list((smoke.directory / kind).iterdir()), "stopped build retained artifacts"
            )
            smoke.save()
            # Cancellation invalidates the cached capability, as designed.
            require(backend.probe().available, "fresh probe after stop failed")
        (project / "parts/failure.py").write_text(FAILURE)
        failed = run_build(
            BuildRequest("failure", FAILURE, wall_clock_s=120),
            backend=backend,
            out_dir=smoke.directory / "failure",
            rlimits=LIMITS,
        )
        require(
            failed.result.status == "failed"
            and failed.result.error is not None
            and failed.result.error.type == "ValueError",
            "ordinary failure not observed",
        )
        require(
            failed.result.error.last_good is not None
            and failed.result.error.last_good.solids == 1
            and abs(failed.result.error.last_good.volume_mm3 - 6.0) < 1e-8
            and failed.artifact_bytes,
            "ordinary failure missing validated last-good kernel checkpoint",
        )
        document(smoke.directory / "failure-result.json", failed.result.to_json())
        evidence["runs"]["failure"] = operation_record(smoke, backend, "failure", link)
        evidence["runs"]["failure"]["build_status"] = failed.result.status
        smoke.check(
            "cancellation",
            "passed",
            "observed running user stop, separate wall timeout and ordinary build failure",
        )
        smoke.report["supervisor_binding"] = config.binding()
        smoke.save()
    return evidence


def verify_cleanup(smoke):
    """Independent inventory plus actual wait/group evidence; uncertainty refuses."""
    evidence = smoke.report.get("executor_evidence")
    if not evidence:
        raise StageFailure("missing execution evidence")
    _, raw = smoke.command(
        (*smoke.docker, "ps", "-a", "--no-trunc", "--format", "{{.ID}}"), cleanup=True
    )
    inventory = raw.splitlines()
    _, processes = smoke.command(("/bin/ps", "-axo", "pid=,pgid="), cleanup=True)
    live = {int(word) for line in processes.splitlines() for word in line.split()}
    supervisor = smoke.directory / "supervisor"
    journals = [supervisor / "ownership/state.json"]
    state = load(journals[0])
    recorded_ids = {r["id"] for r in state["containers"].values()}
    for kind, run in evidence["runs"].items():
        require(run["container_id"] in recorded_ids, "run missing durable ownership")
        operation = smoke.directory / run["operation"]
        require(operation.parent == supervisor and operation.is_dir(), "missing owned operation")
        if kind in ("explicit_cancel", "timeout"):
            require(
                (operation / "observer-ownership/state.json").is_file(),
                "missing observer ownership",
            )
            name = "cancel" if kind == "explicit_cancel" else "timeout"
            require(
                (smoke.directory / f"{name}-events/ownership/state.json").is_file(),
                "missing event client ownership",
            )
    journals += list(
        (smoke.directory / "supervisor").glob("operation-*/observer-ownership/state.json")
    )
    journals += list(smoke.directory.glob("*-events/ownership/state.json"))
    require(journals, "missing ownership journals")
    for path in journals:
        state = load(path)
        require(not state["launch_pending"], "unsettled client launch")
        for cid, client in state["clients"].items():
            require(client["reaped"] is True and int(cid) not in live, "client/child group remains")
        for container in state["containers"].values():
            require(
                not container["pending"]
                and container["absent"]
                and container["id"] not in inventory,
                "container remains or create unsettled",
            )
    operations = list(supervisor.glob("operation-*"))
    require(operations, "missing owner operations")
    for directory in operations:
        owner, reaped = load(directory / "owner.json"), load(directory / "reaped.json")
        require(
            owner["pid"] == reaped["pid"] and reaped["exitcode"] == 0 and owner["pid"] not in live,
            "owner not reaped/absent",
        )
        require(
            load(directory / "owner-final.json")["commands_finished"] is True, "unfinished owner"
        )
    ids = [
        evidence["runs"][k]["container_id"]
        for k in ("build", "explicit_cancel", "timeout", "failure")
        if k in evidence["runs"]
    ]
    require(not set(ids).intersection(inventory), "owned container still present")
    evidence["cleanup"] = {
        "run_id": evidence["run_id"],
        "owned_container_ids": ids,
        "independently_absent_ids": ids,
        "unsettled_creates": [],
        "remaining_image_tags": [],
        "clients_reaped": True,
        "children_reaped": True,
        "inventory_sha256": document(
            smoke.directory / "final-inventory.json",
            {"containers": inventory, "processes": processes},
        ),
    }
