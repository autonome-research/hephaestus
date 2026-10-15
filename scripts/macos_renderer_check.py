# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Fresh serial executor -> inspection -> linked GLB acceptance, never full acceptance.

All CAD/raster/kernel/publication/terminal/ownership observations are fresh.
No agent, provider, host CAD, browser or historical report authorizes execution.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import signal
from pathlib import Path

# This stdlib harness establishes the worktree import path before core imports.
from macos_milestone_smoke import Smoke, StageFailure, report_path

# isort: split
from hephaestus.core.errors import SandboxDeniedError
from hephaestus.core.executor.sandbox.oci import OciIdentity, OciRuntime
from hephaestus.core.executor.sandbox.oci_ownership import OwnershipJournal
from hephaestus.core.executor.sandbox.oci_supervisor import SupervisedOciBackend, SupervisorConfig
from hephaestus.core.render.oci_backend import OciRenderer
from hephaestus.core.render.oci_protocol import MAX_BREP, RENDER_VERSION
from macos_prepare_renderer import prepare
from macos_probe_executor import resolve_image


class RendererSmoke(Smoke):
    """Trusted build containers also retain ambiguous create intent durably.

    Workload lifecycle uses the full reviewed supervisor/journal. The inherited
    preparation helper has a smaller name ledger; an absence inventory alone
    must not turn an unacknowledged packaging/download create into success.
    """

    def _save_build_ownership(self):
        target = self.directory / "build-ownership.json"
        temporary = self.directory / "build-ownership.next"
        with temporary.open("w") as stream:
            json.dump(self.report["build_ownership"], stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(target)
        fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def command(self, argv, **kwargs):
        name = None
        if "create" in argv and "--name" in argv:
            name = argv[argv.index("--name") + 1]
            records = self.report.setdefault("build_ownership", {})
            if name in records or len(records) >= 4:
                raise StageFailure("duplicate/excessive preparation ownership")
            records[name] = {"pending": True, "id": None}
            self._save_build_ownership()
        result = super().command(argv, **kwargs)
        if name is not None:
            code, raw = result
            if code != 0 or re.fullmatch(r"[0-9a-f]{64}\n", raw) is None:
                raise StageFailure("preparation create settlement unknown")
            self.report["build_ownership"][name] = {"pending": False, "id": raw.strip()}
            self._save_build_ownership()
        return result

    def cleanup(self, *, retain_images=False):
        super().cleanup(retain_images=retain_images)
        if any(r["pending"] for r in self.report.get("build_ownership", {}).values()):
            self.check(
                "cleanup", "failed", "unsettled preparation create; retain build-ownership.json"
            )


def save(path: Path, data: object) -> None:
    with path.open("x") as stream:
        json.dump(data, stream, indent=2)
        stream.write("\n")


def require(condition, message):
    if not condition:
        raise StageFailure(message)


def verify_cleanup(smoke, config):
    states = []
    paths = sorted(config.directory.rglob("ownership")) + sorted(config.directory.rglob("recovery"))
    require(paths, "missing renderer ownership journals")
    for path in paths:
        with OwnershipJournal(path, config.binding()) as journal:
            journal.require_clean()
            states.append(journal.state)
    state = {"clients": {}, "containers": {}}
    for saved in states:
        require(not saved["launch_pending"], "pending renderer client launch")
        state["clients"].update(saved["clients"])
        state["containers"].update(saved["containers"])
    _, raw = smoke.command(
        (*smoke.docker, "ps", "-a", "--no-trunc", "--format", "{{.ID}}"), cleanup=True
    )
    _, processes = smoke.command(("/bin/ps", "-axo", "pid=,pgid="), cleanup=True)
    live = {int(word) for line in processes.splitlines() for word in line.split()}
    for client, record in state["clients"].items():
        require(record["reaped"] is True and int(client) not in live, "unreaped/live client group")
    for record in state["containers"].values():
        require(
            record["pending"] is False
            and record["absent"] is True
            and record["id"] not in raw.splitlines(),
            "pending/live container",
        )
    for operation in sorted(config.directory.rglob("operation-*")):
        owner = json.loads((operation / "owner.json").read_text())
        reaped = json.loads((operation / "reaped.json").read_text())
        final = json.loads((operation / "owner-final.json").read_text())
        require(
            owner["pid"] == reaped["pid"]
            and reaped["exitcode"] == 0
            and owner["pid"] not in live
            and final["commands_finished"] is True,
            "unreaped/live owner",
        )
    save(
        smoke.directory / "renderer-final-inventory.json",
        {"containers": raw.splitlines(), "processes": processes, "ownership": state},
    )


def live(smoke, image_ref, executor):
    brep_path = executor.directory / "build/final.brep"
    with brep_path.open("rb") as stream:
        brep = stream.read(MAX_BREP + 1)
    require(0 < len(brep) <= MAX_BREP, "fresh fixture size")
    fixture_hash = hashlib.sha256(brep).hexdigest()
    smoke.report["render_input"] = {
        "path": str(brep_path),
        "sha256": fixture_hash,
        "bytes": len(brep),
        "origin": "fresh supervised executor build and canonical publication in executor/",
    }
    runtime = OciRuntime(
        "docker",
        Path(smoke.docker[0]),
        ("--context", "desktop-linux"),
        smoke.docker[2],
        "Docker Desktop",
    )
    config = SupervisorConfig(
        runtime,
        image_ref,
        "linux/arm64",
        smoke.directory / "supervisor",
        OciIdentity(os.getuid(), os.getgid()),
        runtime_profile="renderer",
        deadline=smoke.deadline,
    )
    results = {}
    smoke.report["renderer_binding"] = config.binding()
    smoke.report["renderer_cleanup_passed"] = False
    smoke.save()
    renderer = OciRenderer(config)
    try:
        probe = renderer.probe()
        save(smoke.directory / "renderer-identity.json", probe.identity.to_json())
        save(smoke.directory / "egl-probe.json", json.loads(probe.data))
        smoke.check(
            "containment",
            "passed",
            "fresh renderer manifest/containment and real llvmpipe context; "
            "every operation independently re-probes",
        )
        for operation in ("rgb", "mask", "selection", "section", "selection"):
            request = {
                "version": RENDER_VERSION,
                "links": None,
                "operation": operation,
                "source_ref": "artifact:build:sha256:" + fixture_hash,
                "brep_sha256": fixture_hash,
                "solids": [{"label": None, "color": None}, {"label": None, "color": None}],
                "placements": [],
                "view": "+Z" if operation == "section" else "iso",
                "width": 128,
                "height": 96,
                "section": {"axis": "Z", "sign": 1, "offset": 0}
                if operation == "section"
                else None,
            }
            result = renderer.render(request, brep)
            require(result.identity == probe.identity, "render identity changed")
            response = json.loads(result.data)
            name = operation if operation not in results else operation + "-repeat"
            save(smoke.directory / (name + "-request.json"), request)
            (smoke.directory / (name + "-response.json")).write_bytes(result.data)
            require(
                response["topology"] == [{"faces": 6, "edges": 12}] * 2, "unexpected real topology"
            )
            for kind, image in response["images"].items():
                pixels = base64.b64decode(image["pixels"], validate=True)
                if operation in ("mask", "selection") and kind != "preview":
                    require(
                        any(
                            pixels[i : i + 3] != b"\0\0\0"
                            for i in range(0, len(pixels), image["channels"])
                        ),
                        "empty real ID pass",
                    )
                else:
                    require(
                        any(pixels[i : i + 3] != b"\xff\xff\xff" for i in range(0, len(pixels), 4)),
                        "empty real shaded pass",
                    )
                (smoke.directory / (name + "-" + kind + ".pixels")).write_bytes(pixels)
            if operation == "section":
                require(
                    response["section"]["faces"] == 2
                    and abs(response["section"]["area_mm2"] - 26) < 1e-8,
                    "actual kernel section must be two faces / 26 mm2",
                )
            directory = renderer.supervisor.last_directory
            evidence = json.loads((directory / "result.json").read_text())
            require(
                evidence["terminal"]["Running"] is False
                and evidence["terminal"]["OOMKilled"] is False
                and evidence["terminal"]["ExitCode"] == 0,
                "render terminal state",
            )
            results[name] = {
                "response_sha256": hashlib.sha256(result.data).hexdigest(),
                "images": {k: v["sha256"] for k, v in response["images"].items()},
                "operation": str(directory.relative_to(smoke.directory)),
                "gl_renderer": response["gl_renderer"],
                "terminal": evidence["terminal"],
                "container_id": evidence["container_id"],
            }
            smoke.report["renderer_runs"] = results
            smoke.save()
        require(
            results["selection"]["images"] == results["selection-repeat"]["images"],
            "cross-process ARM selection nondeterminism",
        )
        from macos_renderer_live import integrated

        config_executor = SupervisorConfig(
            runtime,
            executor.report["executor_image_ref"],
            "linux/arm64",
            executor.directory / "supervisor",
            OciIdentity(os.getuid(), os.getgid()),
            deadline=smoke.deadline,
        )
        with SupervisedOciBackend(config_executor) as backend:
            require(
                backend.probe().available,
                "fresh executor identity unavailable for render publication",
            )
            integrated(smoke, executor.directory / "project", backend, renderer)
        bad = b"not a BREP\n"
        digest = hashlib.sha256(bad).hexdigest()
        bad_request = {
            **request,
            "brep_sha256": digest,
            "source_ref": "artifact:build:sha256:" + digest,
        }
        try:
            renderer.render(bad_request, bad)
        except SandboxDeniedError:
            directory = renderer.supervisor.last_directory
            evidence = json.loads((directory / "result.json").read_text())
            require(
                evidence["terminal"]["Running"] is False
                and evidence["terminal"]["OOMKilled"] is False
                and evidence["terminal"]["ExitCode"] == 1,
                "render failure terminal evidence missing",
            )
            smoke.report["renderer_failure"] = {
                "operation": str(directory.relative_to(smoke.directory)),
                "terminal": evidence["terminal"],
                "container_id": evidence["container_id"],
            }
        else:
            raise StageFailure("invalid BREP unexpectedly rendered")
    finally:
        renderer.close()
        verify_cleanup(smoke, config)
        smoke.report["renderer_cleanup_passed"] = True
        smoke.save()


def renderer_passed(report: dict) -> bool:
    """Scoped gate only; these fields are filled by the fresh collector above."""
    return (
        report.get("renderer_worker_passed") is True
        and report.get("executor_stage_passed") is True
        and report.get("renderer_cleanup_passed") is True
        and all(
            report.get("checks", {}).get(k, {}).get("status") == "passed"
            for k in (
                "containment",
                "rgb",
                "selection_masks",
                "kernel_section",
                "linked_glb",
                "cleanup",
            )
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-dir", required=True)
    parser.add_argument("--wheelhouse", type=Path, required=True)
    args = parser.parse_args()
    smoke = RendererSmoke(report_path(args.report_dir), args.wheelhouse.resolve())
    source_root = Path(__file__).resolve().parents[1]
    host_sources = {
        str(path.relative_to(source_root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for tree in ("core/src", "opstore/src", "server/src", "scripts")
        for path in sorted((source_root / tree).rglob("*.py"))
    }
    save(smoke.directory / "host-source-sha256.json", host_sources)
    smoke.report.update(
        renderer_worker_passed=False,
        renderer_stage_passed=False,
        accepted=False,
        renderer_api_version=RENDER_VERSION,
        host_sources_sha256=hashlib.sha256(
            (smoke.directory / "host-source-sha256.json").read_bytes()
        ).hexdigest(),
    )
    executor = RendererSmoke(
        smoke.directory / "executor", args.wheelhouse.resolve(), deadline=smoke.deadline
    )

    def interrupted(signum, frame):
        raise KeyboardInterrupt("renderer check interrupted")

    signal.signal(signal.SIGTERM, interrupted)
    failed = False
    try:
        smoke.preflight()
        from macos_executor_check import run_executor_stages

        executor.docker = smoke.docker
        run_executor_stages(executor)
        smoke.native_dependencies()
        tag = prepare(smoke)
        image_ref = resolve_image(smoke, tag, role="renderer")
        live(smoke, image_ref, executor)
    except BaseException as exc:
        failed = True
        smoke.report["renderer_error"] = f"{type(exc).__name__}: {exc}"
    finally:
        old = {sig: signal.signal(sig, signal.SIG_IGN) for sig in (signal.SIGINT, signal.SIGTERM)}
        try:
            try:
                executor.cleanup()
                from macos_executor_check import finish_executor

                finish_executor(executor)
                smoke.report["executor_stage_passed"] = executor.report["executor_stage_passed"]
            finally:
                smoke.cleanup()
            if "renderer_binding" in smoke.report and not smoke.report.get(
                "renderer_cleanup_passed"
            ):
                smoke.check("cleanup", "failed", "renderer ownership unresolved; retain journals")
        except Exception as exc:
            failed = True
            smoke.check("cleanup", "failed", f"{type(exc).__name__}: {exc}")
        finally:
            for sig, handler in old.items():
                signal.signal(sig, handler)
        smoke.report["renderer_worker_passed"] = (
            not failed
            and smoke.report["checks"]["cleanup"]["status"] == "passed"
            and smoke.report.get("renderer_cleanup_passed") is True
        )
        smoke.report["renderer_stage_passed"] = renderer_passed(smoke.report)
        smoke.save()
    print(
        ("PASS" if smoke.report["renderer_stage_passed"] else "FAIL")
        + " (renderer stage; full acceptance false): "
        + str(smoke.directory / "report.json")
    )
    return 0 if smoke.report["renderer_stage_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
