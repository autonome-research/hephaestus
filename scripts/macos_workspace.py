# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Explicit local experimental workspace. No production discovery or agent startup.

Run with the project-local .venv interpreter. Images are immutable references,
not trusted reports: both backends perform fresh manifest/containment probes.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import secrets
import shutil
import signal
import socket
import sys
import threading
import time
import webbrowser
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for package in ("core", "opstore", "server", "contract"):
    sys.path.insert(0, str(ROOT / package / "src"))

from hephaestus.core.deadline import Deadline, clock_description  # noqa: E402
from hephaestus.core.executor.sandbox.base import Rlimits  # noqa: E402
from hephaestus.core.executor.sandbox.oci import (  # noqa: E402
    RUNTIME_ENV,
    OciIdentity,
    OciRuntime,
    SubprocessTransport,
)
from hephaestus.core.executor.sandbox.oci_supervisor import (  # noqa: E402
    SupervisedOciBackend,
    SupervisorConfig,
)
from hephaestus.core.render.oci_backend import OciRenderer  # noqa: E402

LIMITS = Rlimits(120, 2 * 1024**3, 256)


@contextmanager
def serial_slot(lock):
    from hephaestus.core.errors import SandboxDeniedError

    if not lock.acquire(blocking=False):
        raise SandboxDeniedError("experimental workspace worker already active")
    try:
        yield
    finally:
        lock.release()


class WorkspaceExecutor(SupervisedOciBackend):
    def __init__(self, config, lock):
        self.serial = lock
        super().__init__(config)

    def probe(self):
        with serial_slot(self.serial):
            if self.config.deadline is not None:
                self.config.deadline.remaining()
            return super().probe()

    def execute(self, spec, stdin_payload):
        with serial_slot(self.serial):
            if self.config.deadline is not None:
                self.config.deadline.remaining()
            return super().execute(spec, stdin_payload)


class WorkspaceRenderer(OciRenderer):
    def __init__(self, config, lock):
        self.serial = lock
        self.deadline = config.deadline
        super().__init__(config)

    def probe(self):
        with serial_slot(self.serial):
            if self.deadline is not None:
                self.deadline.remaining()
            return super().probe()

    def render(self, request, brep):
        with serial_slot(self.serial):
            if self.deadline is not None:
                self.deadline.remaining()
            return super().render(request, brep)


class DeadlineGate:
    """Refuse admission on resume even if the expiry task has not run yet."""

    def __init__(self, app, deadline):
        self.app = app
        self.deadline = deadline

    async def __call__(self, scope, receive, send):
        if scope["type"] in {"http", "websocket"} and self.deadline.expired():
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1001})
            else:
                await send({"type": "http.response.start", "status": 503, "headers": []})
                await send({"type": "http.response.body", "body": b"workspace deadline expired"})
            return
        await self.app(scope, receive, send)


async def expire_session(server, deadline):
    while not deadline.expired():
        await asyncio.sleep(0.1)
    server.should_exit = True


def dispatch_local(workspace, tool, arguments):
    return workspace.dispatcher.dispatch(
        workspace.dispatch_principal(),
        {
            "tool": tool,
            "arguments": arguments,
            "invocation": {
                "entry_id": "local-" + secrets.token_hex(16),
                "ordinal": 0,
                "provider_call_id": "operator",
            },
        },
    )


def record_requirements(workspace, path):
    with path.open("rb") as stream:
        raw = stream.read(65537)
    if len(raw) > 65536:
        raise ValueError("local requirements input exceeds 64 KiB")
    payload = json.loads(raw)
    if (
        not isinstance(payload, dict)
        or set(payload) != {"request", "entries"}
        or not isinstance(payload["request"], str)
        or not payload["request"].strip()
        or not isinstance(payload["entries"], list)
    ):
        raise ValueError("requirements must contain request text and entries")
    # This launcher accepts explicit operator specifications only. It never
    # invents a resolved assumption or fills runtime-only clarification fields.
    for entry in payload["entries"]:
        if (
            not isinstance(entry, dict)
            or entry.get("source") != "specified"
            or not isinstance(entry.get("quote"), str)
            or not entry["quote"]
            or entry["quote"] not in payload["request"]
        ):
            raise ValueError("each local specified requirement must quote the supplied request")
    workspace.cad.set_request_text(payload["request"])
    recorded = dispatch_local(workspace, "record_requirements", {"entries": payload["entries"]})
    return {"input_sha256": hashlib.sha256(raw).hexdigest(), "recorded": recorded}


def document(path, data):
    temporary = path.with_suffix(".next")
    with temporary.open("w") as stream:
        json.dump(data, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def command(argv):
    result = SubprocessTransport().run(
        tuple(argv),
        input=b"",
        timeout=20,
        stdout_limit=256 * 1024,
        stderr_limit=64 * 1024,
        env=RUNTIME_ENV,
    )
    if result.returncode:
        raise RuntimeError("local runtime command refused: " + str(argv[:2]))
    return result.stdout.decode()


def local_runtime():
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise RuntimeError("requires native Darwin arm64")
    docker = shutil.which("docker")
    if docker is None or command([docker, "context", "show"]).strip() != "desktop-linux":
        raise RuntimeError("requires active desktop-linux context")
    context = json.loads(command([docker, "context", "inspect", "desktop-linux"]))[0]
    endpoint = context["Endpoints"]["docker"]["Host"]
    if not endpoint.startswith("unix:///"):
        raise RuntimeError("requires local Unix Docker endpoint")
    info = json.loads(command([docker, "--host", endpoint, "info", "--format", "{{json .}}"]))
    if (
        info["OSType"] != "linux"
        or info["Architecture"] != "aarch64"
        or "docker desktop" not in info["OperatingSystem"].lower()
        or info["ContainersRunning"] != 0
    ):
        raise RuntimeError("requires idle native ARM64 Docker Desktop")
    return OciRuntime(
        "docker", Path(docker), ("--context", "desktop-linux"), endpoint, "Docker Desktop"
    )


def verify_owned(config):
    from hephaestus.core.executor.sandbox.oci_ownership import OwnershipJournal
    from hephaestus.core.executor.sandbox.oci_supervisor import _require_owners_complete

    _require_owners_complete(config)
    paths = sorted(config.directory.rglob("ownership"))
    if not paths:
        raise RuntimeError("missing ownership evidence")
    ids = command(
        [
            str(config.runtime.path),
            "--host",
            config.runtime.endpoint,
            "ps",
            "-a",
            "--no-trunc",
            "--format",
            "{{.ID}}",
        ]
    ).splitlines()
    processes = command(["/bin/ps", "-axo", "pid=,pgid="])
    live = {int(word) for word in processes.split()}
    for path in paths:
        with OwnershipJournal(path, config.binding()) as journal:
            journal.require_clean()
            for record in journal.state["containers"].values():
                if record["pending"] or not record["absent"] or record["id"] in ids:
                    raise RuntimeError("container cleanup uncertain")
            for pid, record in journal.state["clients"].items():
                if not record["reaped"] or int(pid) in live:
                    raise RuntimeError("client cleanup uncertain")
    for path in config.directory.rglob("owner.json"):
        owner = json.loads(path.read_text())
        reaped = json.loads((path.parent / "reaped.json").read_text())
        if owner["pid"] in live or reaped["pid"] != owner["pid"] or reaped["exitcode"] != 0:
            raise RuntimeError("owner cleanup uncertain")
    return {"container_ids": ids, "processes": processes, "journals": len(paths)}


async def serve(args):
    import uvicorn
    from hephaestus.agent_bridge.serve_record import owning_server
    from hephaestus.http.app import build_app
    from hephaestus.http.principal import clear_serve_record, mint_token, write_serve_record
    from hephaestus.http.runtime import WorkspaceRuntime
    from hephaestus.http.serve import with_bundle

    deadline = Deadline.after(args.wall_seconds)
    if args.deadline_ns is not None:
        deadline = Deadline(min(deadline.end_ns, args.deadline_ns))
    deadline.remaining()
    state = args.state_dir.resolve()
    state.mkdir(parents=True, mode=0o700, exist_ok=False)
    report = {
        "experimental": True,
        "accepted": False,
        "pid": os.getpid(),
        "started_at": time.time(),
        "deadline_clock": clock_description(),
        "deadline_ns": deadline.end_ns,
        "cleanup_passed": False,
        "agent_started": False,
    }
    target = state / "workspace.json"
    document(target, report)
    backend = renderer = workspace = sock = None
    configs = []
    record_owned = False
    try:
        root = args.project.resolve(strict=True)
        if owning_server(root) is not None:
            raise RuntimeError("another server owns the project")
        runtime = local_runtime()
        identity = OciIdentity(os.getuid(), os.getgid())
        for role, image in (("executor", args.executor_image), ("renderer", args.renderer_image)):
            configs.append(
                SupervisorConfig(
                    runtime,
                    image,
                    "linux/arm64",
                    state / role,
                    identity,
                    runtime_profile=role,
                    deadline=deadline,
                )
            )
        serial = threading.RLock()
        backend = WorkspaceExecutor(configs[0], serial)
        if not backend.probe().available:
            raise RuntimeError("executor probe refused")
        renderer = WorkspaceRenderer(configs[1], serial)
        rendered = renderer.probe()
        report["executor_identity"] = backend.execution_identity().to_json()
        report["renderer_identity"] = rendered.identity.to_json()
        report["egl"] = json.loads(rendered.data)
        token, token_path = mint_token(root / ".heph")
        workspace = WorkspaceRuntime.open(
            root,
            token=token,
            backend=backend,
            renderer=renderer,
            serve_mode=True,
            render_size=(320, 240),
            build_rlimits=LIMITS,
            build_wall_clock_s=120,
            allow_agent_attach=False,
        )
        # Deliberately detached, without even attempting provider discovery/startup.
        workspace.detach_agent()
        report["capabilities"] = workspace.capabilities(refresh=True)
        if report["capabilities"]["secure_executor"] is not True:
            raise RuntimeError("injected capability projection refused")
        deadline.remaining()
        if args.requirements is not None:
            report["requirements"] = record_requirements(workspace, args.requirements)
        deadline.remaining()
        if args.build:
            report["build"] = dispatch_local(workspace, "build_part", {"name": args.build})
            if report["build"]["status"] != "ok":
                raise RuntimeError("workspace build failed")
        bundle = ROOT / "web/dist"
        if not (bundle / "index.html").is_file():
            raise RuntimeError("build web/ with pinned pnpm before launching")
        report["bundle_sha256"] = {
            str(p.relative_to(bundle)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(bundle.rglob("*"))
            if p.is_file()
        }
        sock = socket.socket()
        sock.bind(("127.0.0.1", args.port))
        url = f"http://127.0.0.1:{sock.getsockname()[1]}"
        sock.listen(128)
        write_serve_record(root / ".heph", http=url, token_path=token_path)
        record_owned = True
        report["http"] = url
        document(target, report)

        class Server(uvicorn.Server):
            async def startup(self, sockets=None):
                await super().startup(sockets=sockets)
                if not self.started:
                    raise RuntimeError("server did not start")
                deadline.remaining()
                ready = {"http": url, "token_path": str(token_path), "pid": os.getpid()}
                if args.ready_fd is not None:
                    os.write(args.ready_fd, json.dumps(ready).encode() + b"\n")
                    os.close(args.ready_fd)
                print(
                    f"EXPERIMENTAL workspace: {url} (token in {token_path}; Ctrl-C to stop)",
                    flush=True,
                )
                if args.open_browser:
                    webbrowser.open(url + "/#t=" + token)

        server = Server(
            uvicorn.Config(
                DeadlineGate(with_bundle(build_app(workspace), bundle), deadline),
                access_log=False,
                log_config=None,
                log_level="critical",
                timeout_graceful_shutdown=15,
            )
        )
        # Poll only to schedule shutdown; admission and worker boundaries also
        # check the continuous deadline, independently of task scheduling order.
        deadline.remaining()
        expiry = asyncio.create_task(expire_session(server, deadline))
        try:
            await server.serve(sockets=[sock])
        finally:
            expiry.cancel()
    except SystemExit as exc:
        if exc.code in (128 + signal.SIGINT, 128 + signal.SIGTERM):
            report["shutdown_signal"] = int(exc.code) - 128
        else:
            report["error"] = f"SystemExit: {exc.code}"
        raise
    except BaseException as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        # Do not let a second interruption abandon exact-owned reconciliation.
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, signal.SIG_IGN)
        errors = []
        for obj in (renderer, backend, workspace, sock):
            if obj is not None:
                try:
                    obj.close()
                except BaseException as exc:
                    errors.append(f"{type(exc).__name__}: {exc}")
        if record_owned:
            clear_serve_record(args.project.resolve() / ".heph")
        for config in configs:
            if config.directory.exists():
                try:
                    report[config.runtime_profile + "_cleanup"] = verify_owned(config)
                except BaseException as exc:
                    errors.append(f"{type(exc).__name__}: {exc}")
        report.update(cleanup_passed=not errors, cleanup_errors=errors, finished_at=time.time())
        document(target, report)
        if errors:
            raise RuntimeError("workspace cleanup unresolved; retain " + str(state))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument(
        "--state-dir", type=Path, required=True, help="new private evidence directory"
    )
    parser.add_argument("--executor-image")
    parser.add_argument("--renderer-image")
    parser.add_argument("--images", type=Path, help="images.json from macos_prepare_workspace.py")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--wall-seconds", type=int, default=1800)
    parser.add_argument(
        "--requirements", type=Path, help="bounded explicit operator request/entries JSON"
    )
    parser.add_argument(
        "--build", help="build/publish through the normal dispatcher before serving"
    )
    parser.add_argument("--open-browser", action="store_true")
    parser.add_argument("--ready-fd", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--deadline-ns", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.images is not None:
        if args.executor_image or args.renderer_image:
            parser.error("use --images OR two explicit immutable image references")
        images = json.loads(args.images.read_text())
        args.executor_image, args.renderer_image = images["executor"], images["renderer"]
    if not args.executor_image or not args.renderer_image:
        parser.error("both immutable images are required")
    if not 0 <= args.port <= 65535 or not 1 <= args.wall_seconds <= 3600:
        parser.error("invalid bounded local session")

    def interrupted(signum, frame):
        del frame
        raise SystemExit(128 + signum)

    # Uvicorn restores and re-delivers its captured signal after shutdown.
    # A default SIGTERM would kill us before the outer finally can reconcile.
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, interrupted)
    asyncio.run(serve(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
