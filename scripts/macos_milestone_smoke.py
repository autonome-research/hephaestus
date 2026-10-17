# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Fail-closed, development-only macOS milestone ledger and native prerequisites.

This is deliberately NOT production backend discovery. Missing later stages are
failures, even when every implemented prerequisite passes. No CAD source runs in
the network-enabled wheel downloader (only hash-checked binary downloads).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import signal
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core" / "src"))
sys.path.insert(0, str(ROOT / "opstore" / "src"))

from hephaestus.core.deadline import Deadline, clock_description, transport_budget  # noqa: E402
from hephaestus.core.executor.sandbox.oci import (  # noqa: E402
    RUNTIME_ENV,
    SubprocessTransport,
    TransportOutputLimit,
    TransportTimeout,
)
from hephaestus.core.executor.sandbox.oci_transfer import _Receiver  # noqa: E402

BASE = (
    "python:3.13.7-slim-bookworm@sha256:"
    "adafcc17694d715c905b4c7bebd96907a1fd5cf183395f0ebc4d3428bd22d92d"
)
BASE_COMMIT = "16a0021a535d5859a7a13ec283d23f764f4d377c"
IMPLEMENTED = frozenset(
    {
        "preflight",
        "native_dependencies",
        "executor_image",
        "image_resolution",
        "containment",
        "build",
        "cancellation",
        "cleanup",
        "rgb",
        "selection_masks",
        "kernel_section",
        "linked_glb",
        "browser",
    }
)
REQUIRED = (
    "preflight",
    "native_dependencies",
    "executor_image",
    "image_resolution",
    "containment",
    "build",
    "rgb",
    "selection_masks",
    "kernel_section",
    "linked_glb",
    "browser",
    "cancellation",
    "cleanup",
)


class StageFailure(RuntimeError):
    pass


def accepted(checks: dict[str, Any]) -> bool:
    """An unknown/missing/blocked stage cannot become a successful milestone."""
    return all(checks.get(name, {}).get("status") == "passed" for name in REQUIRED)


def report_path(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_relative_to(ROOT) or path == ROOT:
        raise ValueError("report directory must be inside this checkout")
    if any(char in str(path) for char in (",", "\n", "\r", "\x00")):
        raise ValueError("report directory cannot be represented safely as an OCI mount")
    if path.exists():
        raise ValueError("report directory must be new (evidence is never overwritten)")
    return path


class Smoke:
    def __init__(
        self, directory: Path, wheelhouse: Path | None = None, *, deadline: Deadline | None = None
    ) -> None:
        self.deadline = deadline or Deadline.after(2400)
        self.cleanup_deadline = None
        self.directory = directory
        self.wheelhouse = wheelhouse
        self.logs = directory / "logs"
        self.logs.mkdir(parents=True)
        (directory / "screenshots").mkdir()
        self.transport = SubprocessTransport()
        self.docker: tuple[str, ...] = ()
        self.owned: list[str] = []
        self.sequence = 0
        self.report: dict[str, Any] = {
            "schema_version": 1,
            "experimental": True,
            "started_at": time.time(),
            "deadline_clock": clock_description(),
            "work_deadline_ns": self.deadline.end_ns,
            "work_seconds": 2400,
            "cleanup_seconds": 120,
            "source_root": str(ROOT),
            "checks": {
                name: {
                    "status": "blocked" if name in IMPLEMENTED else "unimplemented",
                    "detail": "not run" if name in IMPLEMENTED else "not implemented; not a pass",
                }
                for name in REQUIRED
            },
            "commands": [],
            "owned_containers": self.owned,
            "owned_image_tags": [],
            "screenshots": [],
        }
        self.save()

    def save(self) -> None:
        self.report["accepted"] = (
            accepted(self.report["checks"])
            and self.report.get("executor_stage_passed") is True
            and self.report.get("renderer_cleanup_passed") is True
            and self.report.get("workspace_cleanup_passed") is True
            and self.report.get("browser_evidence", {}).get("passed") is True
            and "milestone_error" not in self.report
        )
        target = self.directory / "report.json"
        temporary = self.directory / "report.json.tmp"
        temporary.write_text(json.dumps(self.report, indent=2) + "\n")
        temporary.replace(target)

    def check(self, name: str, status: str, detail: str) -> None:
        self.report["checks"][name] = {"status": status, "detail": detail}
        self.save()

    def _save_build_ownership(self) -> None:
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

    def command(
        self,
        argv: tuple[str, ...],
        *,
        timeout: float = 30,
        require: bool = True,
        cleanup: bool = False,
        receiver: _Receiver | None = None,
    ) -> tuple[int, str]:
        name = None
        if "create" in argv and "--name" in argv:
            name = argv[argv.index("--name") + 1]
            records = self.report.setdefault("build_ownership", {})
            if name not in self.owned or name in records or len(records) >= 4:
                raise StageFailure("unowned/duplicate/excessive preparation create")
            records[name] = {"pending": True, "id": None}
            self._save_build_ownership()
        if cleanup and self.cleanup_deadline is None:
            self.cleanup_deadline = Deadline.after(120)
            self.report["cleanup_deadline_ns"] = self.cleanup_deadline.end_ns
        budget = self.cleanup_deadline if cleanup else self.deadline
        assert budget is not None
        timeout = budget.cap(timeout)
        self.sequence += 1
        stem = f"{self.sequence:03d}"
        stdout_limit = (
            receiver.policy.export_bytes
            + receiver.policy.result_bytes
            + receiver.schema.header_max
            + 128
            if receiver is not None
            else 512 * 1024
        )
        record: dict[str, Any] = {
            "argv": list(argv),
            "timeout_seconds": timeout,
            "stdout_limit": stdout_limit,
            "stderr_limit": 512 * 1024,
            "streamed_preparation_export": receiver is not None,
            "log": f"logs/{stem}.log",
        }
        self.report["commands"].append(record)
        self.save()
        try:
            with transport_budget(budget):
                result = self.transport.run(
                    argv,
                    input=b"",
                    timeout=timeout,
                    stdout_limit=stdout_limit,
                    stderr_limit=512 * 1024,
                    env=RUNTIME_ENV,
                    **({"stdout_consumer": receiver.feed} if receiver is not None else {}),
                )
        except (TransportTimeout, TransportOutputLimit) as exc:
            record["error"] = type(exc).__name__
            (self.logs / f"{stem}.log").write_bytes(
                getattr(exc, "stdout", b"") + b"\n" + getattr(exc, "stderr", b"")
            )
            raise StageFailure(f"{argv[0]}: {type(exc).__name__}; see {record['log']}") from exc
        except BaseException as exc:
            record["error"] = type(exc).__name__
            (self.logs / f"{stem}.log").write_bytes(
                getattr(exc, "stdout", b"")[: 512 * 1024]
                + b"\n"
                + getattr(exc, "stderr", b"")[: 512 * 1024]
            )
            raise
        finally:
            self.save()
        record["returncode"] = result.returncode
        (self.logs / f"{stem}.log").write_bytes(
            b"STDOUT\n" + result.stdout + b"\nSTDERR\n" + result.stderr
        )
        self.save()
        if name is not None:
            raw = result.stdout.decode("ascii", errors="strict")
            if result.returncode != 0 or re.fullmatch(r"[0-9a-f]{64}\n", raw) is None:
                raise StageFailure("preparation create settlement unknown")
            self.report["build_ownership"][name] = {"pending": False, "id": raw.strip()}
            self._save_build_ownership()
        if require and result.returncode != 0:
            raise StageFailure(f"command exited {result.returncode}; see {record['log']}")
        return result.returncode, result.stdout.decode("utf-8", errors="strict")

    def preflight(self) -> None:
        if platform.system() != "Darwin" or platform.machine() != "arm64":
            raise StageFailure("this milestone requires native Darwin arm64")
        _, branch = self.command(("/usr/bin/git", "branch", "--show-current"))
        _, head = self.command(("/usr/bin/git", "rev-parse", "HEAD"))
        _, ancestor = self.command(("/usr/bin/git", "merge-base", "HEAD", BASE_COMMIT))
        if branch.strip() != "feat/macos-feasibility" or ancestor.strip() != BASE_COMMIT:
            raise StageFailure("wrong branch or baseline ancestry")
        docker = shutil.which("docker")
        if docker is None:
            raise StageFailure("Docker client not installed")
        _, context = self.command((docker, "context", "show"))
        if context.strip() != "desktop-linux":
            raise StageFailure("active Docker context is not desktop-linux; not changing it")
        _, raw = self.command(
            (docker, "context", "inspect", "desktop-linux", "--format", "{{json .}}")
        )
        endpoint = json.loads(raw)["Endpoints"]["docker"]["Host"]
        if not isinstance(endpoint, str) or not endpoint.startswith("unix:///"):
            raise StageFailure("Docker Desktop endpoint is not a local Unix socket")
        self.docker = (docker, "--host", endpoint)
        _, raw = self.command((*self.docker, "info", "--format", "{{json .}}"))
        info = json.loads(raw)
        if (
            info.get("OSType") != "linux"
            or info.get("Architecture") != "aarch64"
            or "docker desktop" not in str(info.get("OperatingSystem", "")).lower()
        ):
            raise StageFailure("daemon is not native ARM64 Linux Docker Desktop")
        if info.get("ContainersRunning") != 0:
            raise StageFailure("active containers exist; refusing heavy work, not stopping them")
        _, inventory = self.command(
            (*self.docker, "ps", "-a", "--no-trunc", "--format", "{{json .}}")
        )
        self.report["environment"] = {
            "host": platform.platform(),
            "head": head.strip(),
            "branch": branch.strip(),
            "endpoint": endpoint,
            "architecture": info["Architecture"],
            "memory_bytes": info["MemTotal"],
            "initial_containers": [json.loads(line) for line in inventory.splitlines()],
        }
        self.check("preflight", "passed", "native local Docker Desktop; correct worktree branch")

    def native_dependencies(self) -> None:
        """Download only; no untrusted project script or package build is executed."""
        self.command((*self.docker, "pull", "--platform", "linux/arm64", BASE), timeout=180)
        _, raw = self.command((*self.docker, "image", "inspect", BASE))
        image = json.loads(raw)[0]
        if image["Architecture"] != "arm64" or image["Os"] != "linux":
            raise StageFailure("base image is not native Linux arm64")
        self.report["base_image"] = {"reference": BASE, "id": image["Id"]}
        staging = self.directory / "download"
        staging.mkdir(mode=0o700)
        hashes: dict[str, str] = {}
        for name in ("requirements.lock", "build-requirements.lock"):
            source = ROOT / "docker" / "executor" / name
            shutil.copyfile(source, staging / name)
            hashes[name] = hashlib.sha256(source.read_bytes()).hexdigest()
        self.report["dependency_locks"] = hashes
        from macos_preparation import prepare_files

        prepare_files(
            self,
            "download" if self.wheelhouse is None else "download-cache",
            staging / "wheels",
            self.wheelhouse,
        )
        self.check("native_dependencies", "passed", "native cp313 ARM64 hash-checked binary wheels")

    def cleanup(self, *, retain_images: bool = False) -> None:
        if self.cleanup_deadline is None:
            self.cleanup_deadline = Deadline.after(120)
            self.report["cleanup_deadline_ns"] = self.cleanup_deadline.end_ns
        failures: list[str] = []
        for name in self.owned:
            try:
                ownership = self.report.get("build_ownership", {}).get(name, {})
                target = ownership.get("id") or name
                self.command((*self.docker, "rm", "--force", target), require=False, cleanup=True)
                # A successful full inventory positively establishes absence; a failed
                # inspect could instead mean the daemon is unavailable.
                _, names = self.command(
                    (*self.docker, "ps", "-a", "--format", "{{.Names}}"), cleanup=True
                )
                if name in names.splitlines():
                    failures.append(name)
            except Exception as exc:
                failures.append(f"{name}: {exc}")
        if any(r["pending"] for r in self.report.get("build_ownership", {}).values()):
            failures.append("unsettled preparation create; retain build-ownership.json")
        self.report["retained_image_artifacts"] = (
            list(self.report["owned_image_tags"]) if retain_images else []
        )
        for tag in () if retain_images else self.report["owned_image_tags"]:
            try:
                self.command((*self.docker, "image", "rm", tag), require=False, cleanup=True)
                _, tags = self.command(
                    (*self.docker, "image", "ls", "--format", "{{.Repository}}:{{.Tag}}"),
                    cleanup=True,
                )
                if tag in tags.splitlines():
                    failures.append(tag)
            except Exception as exc:
                failures.append(f"{tag}: {exc}")
        self.check(
            "cleanup",
            "failed" if failures else "passed",
            "; ".join(failures)
            if failures
            else (
                "owned containers confirmed absent; explicitly retained image artifacts"
                if retain_images
                else "owned containers and image tags confirmed absent; clients reaped"
            ),
        )

    def run(self) -> int:
        stage = "preflight"
        try:
            self.deadline.remaining()
            self.preflight()
            self.deadline.remaining()
            stage = "workspace_dependencies"
            from macos_workspace_dependencies import preflight as workspace_dependencies

            workspace_dependencies(self)
            self.deadline.remaining()
            stage = "executor"
            from macos_executor_check import run_executor_stages

            run_executor_stages(self)
            self.deadline.remaining()
            stage = "workspace"
            from macos_workspace_check import later_stages

            later_stages(self)
            self.deadline.remaining()
        except (Exception, KeyboardInterrupt) as exc:
            self.report["milestone_error"] = f"{type(exc).__name__}: {exc}"
            self.check(stage, "failed", f"{type(exc).__name__}: {exc}")
            for name in REQUIRED:
                if self.report["checks"][name]["status"] in {"blocked", "unimplemented"}:
                    prefix = "not run" if name in IMPLEMENTED else "unimplemented"
                    self.check(name, "blocked", f"{prefix}; prerequisite {stage} failed")
        finally:
            # A second TERM/INT cannot interrupt bounded ownership cleanup.
            old = {
                sig: signal.signal(sig, signal.SIG_IGN) for sig in (signal.SIGINT, signal.SIGTERM)
            }
            try:
                self.cleanup()
                from macos_executor_check import finish_executor

                finish_executor(self)
                if (
                    self.report.get("workspace_cleanup_passed") is False
                    or self.report.get("renderer_cleanup_passed") is False
                ):
                    self.check("cleanup", "failed", "workspace/renderer ownership incomplete")
            except Exception as exc:
                self.check("cleanup", "failed", f"{type(exc).__name__}: {exc}")
            finally:
                for sig, handler in old.items():
                    signal.signal(sig, handler)
            self.report["finished_at"] = time.time()
            self.save()
        return 0 if self.report["accepted"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", required=True)
    parser.add_argument("--wheelhouse", type=Path, help="reuse local wheels; hashes reverified")
    args = parser.parse_args()
    if args.wheelhouse is not None:
        args.wheelhouse = args.wheelhouse.resolve()
        if not args.wheelhouse.is_relative_to(ROOT) or not args.wheelhouse.is_dir():
            parser.error("wheelhouse must be a directory inside this checkout")
    try:
        directory = report_path(args.report_dir)
    except ValueError as exc:
        parser.error(str(exc))
    os.chdir(ROOT)
    directory.mkdir(parents=True, mode=0o700)

    def interrupted(signum: int, frame: object) -> None:
        del frame
        raise KeyboardInterrupt(f"received signal {signum}")

    signal.signal(signal.SIGTERM, interrupted)
    from macos_renderer_check import RendererSmoke

    smoke = RendererSmoke(directory, args.wheelhouse)
    sources = {
        str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for tree in (
            "core/src",
            "opstore/src",
            "server/src",
            "contract/src",
            "scripts",
            "web/src",
            "web/e2e",
        )
        for p in sorted((ROOT / tree).rglob("*"))
        if p.is_file() and p.suffix in {".py", ".ts", ".tsx", ".mjs"}
    }
    (directory / "host-source-sha256.json").write_text(json.dumps(sources, indent=2) + "\n")
    code = smoke.run()
    print(f"{'PASS' if code == 0 else 'FAIL'}: {directory / 'report.json'}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
