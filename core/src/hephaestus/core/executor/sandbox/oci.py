"""Conservative OCI host mechanics (not selected by production policy).

This module contains only an explicitly constructed backend.  It performs no
runtime discovery and has no default image: callers must supply an immutable
image digest and a validated local runtime.  Production platform selection is
intentionally outside this module and remains disabled.
"""

from __future__ import annotations

import asyncio
import contextlib
import errno
import json
import math
import os
import platform as platform_module
import re
import secrets
import selectors
import signal
import stat
import subprocess
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import BinaryIO, Literal, Protocol, cast

from hephaestus.core.errors import SandboxDeniedError
from hephaestus.core.executor.sandbox.base import CapabilityReport, ExecOutcome, SandboxSpec
from hephaestus.core.executor.sandbox.oci_protocol import (
    EXEC_STDERR_MAX_BYTES,
    EXEC_STDOUT_MAX_BYTES,
    MAX_ADDRESS_SPACE_BYTES,
    MAX_CPU_SECONDS,
    MAX_NPROC,
    OCI_HOSTNAME,
    OCI_PROFILE_VERSION,
    OCI_TMPFS_BYTES,
    PROBE_STDERR_MAX_BYTES,
    PROBE_STDOUT_MAX_BYTES,
    PROBE_WORKER,
    PROTOCOL_VERSION,
    REQUIRED_OCI_FEATURES,
    approved_module_for_worker_args,
    manifest_bytes,
)

RuntimeKind = Literal["docker", "podman"]
OciPlatform = Literal["linux/amd64", "linux/arm64"]
_CONTAINER_RE = re.compile(r"[0-9a-f]{64}", re.ASCII)
_NAME_RE = re.compile(r"heph-exec-[0-9a-f]{64}", re.ASCII)
_REPOSITORY_RE = re.compile(
    r"(?P<registry>(?:localhost|[a-z0-9]+(?:[.-][a-z0-9]+)*)(?::[0-9]+)?)/"
    r"(?P<path>[a-z0-9]+(?:[._-][a-z0-9]+)*(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*)",
    re.ASCII,
)
AUDITED_ENTRYPOINT: tuple[str, ...] = (
    "/usr/bin/env",
    "-i",
    "LD_LIBRARY_PATH=/opt/hephaestus/native/$LIB:/opt/hephaestus/native/usr/$LIB",
    "/opt/hephaestus/bin/python",
    "-I",
    "-m",
    "hephaestus.core.executor.sandbox.oci_launcher",
)
# The pinned Python base declares this exact environment. The audited entrypoint
# runs ``env -i`` before Python, so none reaches the launcher or worker. Any base
# drift or loader/Python injection variable still fails image inspection.
AUDITED_IMAGE_ENV: tuple[str, ...] = (
    "PATH=/usr/local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "GPG_KEY=7169605F62C751356D054A26A821E680E5FA6305",
    "PYTHON_VERSION=3.13.7",
    "PYTHON_SHA256=5462f9099dfd30e238def83c71d91897d8caa5ff6ebc7a50f14d4802cdaaa79a",
)
RUNTIME_ENV: Mapping[str, str] = MappingProxyType(
    {
        "PATH": "/usr/bin:/bin",
        "LANG": "C",
        "LC_ALL": "C",
    }
)


@dataclass(frozen=True)
class ImmutableImageRef:
    repository: str
    digest: str

    def __str__(self) -> str:
        return f"{self.repository}@sha256:{self.digest}"


def parse_immutable_image_ref(value: object) -> ImmutableImageRef:
    """Parse one registry-qualified, lowercase sha256 image reference."""
    if not isinstance(value, str) or value.count("@sha256:") != 1:
        raise ValueError("OCI image must be one immutable sha256 reference")
    repository, digest = value.split("@sha256:", 1)
    match = _REPOSITORY_RE.fullmatch(repository)
    if match is None:
        raise ValueError("OCI image repository is malformed or not registry-qualified")
    registry = match.group("registry")
    if registry != "localhost" and "." not in registry and ":" not in registry:
        raise ValueError("OCI image repository must name an explicit registry")
    if re.fullmatch(r"[0-9a-f]{64}", digest, re.ASCII) is None:
        raise ValueError("OCI image digest must be 64 lowercase hexadecimal characters")
    return ImmutableImageRef(repository, digest)


def platform_for_machine(machine: str | None = None) -> OciPlatform:
    """Map a host machine spelling to the only supported image platforms."""
    normalized = (platform_module.machine() if machine is None else machine).lower()
    if normalized in {"x86_64", "amd64"}:
        return "linux/amd64"
    if normalized in {"arm64", "aarch64"}:
        return "linux/arm64"
    raise ValueError("unsupported OCI host architecture")


@dataclass(frozen=True)
class OciRuntime:
    """An absolute runtime client plus explicit validated local endpoint identity.

    ``endpoint`` and ``server_identity`` are evidence inputs checked by
    :meth:`OciBackend.probe`; leaving either unset makes probing fail closed.
    ``selector`` names the context/connection whose endpoint is validated.
    Container operations pin that immutable endpoint directly with ``--host``
    or ``--url`` rather than re-resolving the mutable selector after probing.
    """

    kind: RuntimeKind
    path: Path
    selector: tuple[str, ...] = ()
    endpoint: str | None = None
    server_identity: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in {"docker", "podman"}:
            raise ValueError("unsupported OCI runtime")
        path = Path(self.path)
        if not path.is_absolute():
            raise ValueError("OCI runtime executable must be absolute")
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "selector", tuple(self.selector))
        if self.selector:
            expected = "--context" if self.kind == "docker" else "--connection"
            if len(self.selector) != 2 or self.selector[0] != expected or not self.selector[1]:
                raise ValueError("runtime selector must explicitly name one context/connection")
            if any(_unsafe_argument(part) for part in self.selector):
                raise ValueError("unsafe runtime selector")

    @property
    def prefix(self) -> tuple[str, ...]:
        if self.endpoint is not None:
            endpoint_option = "--host" if self.kind == "docker" else "--url"
            return (str(self.path), endpoint_option, self.endpoint)
        return (str(self.path), *self.selector)


@dataclass(frozen=True)
class OciIdentity:
    """Numeric non-root identity used inside the container.

    The host user's IDs are used on Darwin so the worker can write a bind
    mounted staging directory without making it world-writable.  Callers may
    inject explicit IDs for deterministic tests.
    """

    uid: int
    gid: int

    def __post_init__(self) -> None:
        if any(
            type(value) is not int or not 1 <= value <= 2**31 - 1 for value in (self.uid, self.gid)
        ):
            raise ValueError("OCI container identity must be numeric and non-root")


@dataclass(frozen=True)
class TransportResult:
    returncode: int
    stdout: bytes
    stderr: bytes


class TransportTimeout(TimeoutError):
    def __init__(self, stdout: bytes = b"", stderr: bytes = b"") -> None:
        super().__init__("OCI runtime operation timed out")
        self.stdout = stdout
        self.stderr = stderr


class TransportOutputLimit(RuntimeError):
    def __init__(self, stream: Literal["stdout", "stderr"]) -> None:
        super().__init__(f"OCI runtime {stream} limit exceeded")
        self.stream = stream


class TransportReapError(OSError):
    """The local runtime client did not die after a bounded SIGKILL wait."""


class OciTransport(Protocol):
    def run(
        self,
        argv: Sequence[str],
        *,
        input: bytes,
        timeout: float,
        stdout_limit: int,
        stderr_limit: int,
        env: Mapping[str, str],
    ) -> TransportResult: ...


class SubprocessTransport:
    """Bounded, shell-free subprocess transport used by the real backend."""

    def run(
        self,
        argv: Sequence[str],
        *,
        input: bytes,
        timeout: float,
        stdout_limit: int,
        stderr_limit: int,
        env: Mapping[str, str],
    ) -> TransportResult:
        if timeout <= 0:
            raise TransportTimeout()
        proc = subprocess.Popen(
            tuple(argv),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            close_fds=True,
            start_new_session=True,
            env=dict(env),
        )
        selector = selectors.DefaultSelector()
        stdout = bytearray()
        stderr = bytearray()
        try:
            assert proc.stdin is not None and proc.stdout is not None and proc.stderr is not None
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                os.set_blocking(stream.fileno(), False)
            selector.register(proc.stdout, selectors.EVENT_READ, "stdout")
            selector.register(proc.stderr, selectors.EVENT_READ, "stderr")
            if input:
                selector.register(proc.stdin, selectors.EVENT_WRITE, "stdin")
            else:
                proc.stdin.close()
            sent = 0
            deadline = time.monotonic() + timeout
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TransportTimeout(bytes(stdout), bytes(stderr))
                events = selector.select(remaining)
                if not events:
                    raise TransportTimeout(bytes(stdout), bytes(stderr))
                for key, _ in events:
                    stream = cast(BinaryIO, key.fileobj)
                    channel = cast(str, key.data)
                    if channel == "stdin":
                        try:
                            written = os.write(stream.fileno(), input[sent : sent + 65536])
                        except BrokenPipeError:
                            written = 0
                            selector.unregister(stream)
                            stream.close()
                        sent += written
                        if sent >= len(input) and not stream.closed:
                            selector.unregister(stream)
                            stream.close()
                        continue
                    try:
                        chunk = os.read(stream.fileno(), 65536)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        selector.unregister(stream)
                        stream.close()
                        continue
                    target, limit = (
                        (stdout, stdout_limit) if channel == "stdout" else (stderr, stderr_limit)
                    )
                    room = limit - len(target)
                    target.extend(chunk[: max(0, room)])
                    if len(chunk) > room:
                        raise TransportOutputLimit(cast(Literal["stdout", "stderr"], channel))
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TransportTimeout(bytes(stdout), bytes(stderr))
            try:
                proc.wait(timeout=remaining)
            except subprocess.TimeoutExpired as exc:
                raise TransportTimeout(bytes(stdout), bytes(stderr)) from exc
            return TransportResult(int(proc.returncode), bytes(stdout), bytes(stderr))
        except BaseException:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGKILL)
            if proc.poll() is None:
                with contextlib.suppress(OSError):
                    proc.kill()
            try:
                proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired as exc:
                raise TransportReapError("OCI runtime client could not be reaped") from exc
            raise
        finally:
            selector.close()
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                if stream is not None:
                    with contextlib.suppress(OSError):
                        stream.close()


def _unsafe_argument(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


def _validated_name(value: str) -> str:
    if _NAME_RE.fullmatch(value) is None:
        raise ValueError("invalid OCI container name")
    return value


def _validated_container_id(value: str) -> str:
    if _CONTAINER_RE.fullmatch(value) is None:
        raise SandboxDeniedError("sandbox_unavailable: runtime returned an invalid container id")
    return value


def _runtime_prefix(runtime: OciRuntime) -> list[str]:
    return list(runtime.prefix)


def build_create_argv(
    runtime: OciRuntime,
    image_ref: str,
    platform: OciPlatform,
    spec: SandboxSpec,
    container_name: str,
    *,
    identity: OciIdentity,
    command_tail: Sequence[str] | None = None,
) -> tuple[str, ...]:
    """Build the canonical create argv.  This function starts no process."""
    image = str(parse_immutable_image_ref(image_ref))
    _validated_name(container_name)
    module, directory = _preflight(spec, image_ref, platform)
    source = directory.path
    source_text = str(source)
    if _unsafe_mount_path(source_text):
        raise ValueError("rw_out_dir cannot be represented safely as an OCI mount")
    security_opt = "no-new-privileges=true" if runtime.kind == "docker" else "no-new-privileges"
    if command_tail is not None and tuple(command_tail) != ("manifest",):
        raise ValueError("OCI command tail is not an exact protocol invocation")
    tail = (
        ("manifest",)
        if command_tail is not None
        else (
            "run",
            str(PROTOCOL_VERSION),
            module,
            str(spec.rlimits.cpu_seconds),
            str(spec.rlimits.address_space_bytes),
            str(spec.rlimits.nproc),
        )
    )
    return (
        *_runtime_prefix(runtime),
        "create",
        "--interactive",
        "--name",
        container_name,
        "--pull=never",
        "--platform",
        platform,
        "--user",
        f"{identity.uid}:{identity.gid}",
        "--read-only",
        "--network",
        "none",
        "--ipc",
        "none",
        "--hostname",
        OCI_HOSTNAME,
        "--cap-drop",
        "ALL",
        "--security-opt",
        security_opt,
        "--memory",
        str(spec.rlimits.address_space_bytes),
        "--memory-swap",
        str(spec.rlimits.address_space_bytes),
        "--pids-limit",
        str(spec.rlimits.nproc),
        "--cpus",
        "1.0",
        "--tmpfs",
        f"/tmp:rw,nosuid,nodev,noexec,size={OCI_TMPFS_BYTES},mode=1777",
        "--mount",
        f"type=bind,source={source_text},destination=/work,bind-propagation=rprivate",
        "--workdir",
        "/work",
        image,
        *tail,
    )


def build_start_argv(runtime: OciRuntime, container_id: str) -> tuple[str, ...]:
    return (
        *runtime.prefix,
        "start",
        "--attach",
        "--interactive",
        _validated_container_id(container_id),
    )


def build_inspect_argv(runtime: OciRuntime, identity: str) -> tuple[str, ...]:
    _validate_identity(identity)
    return (*runtime.prefix, "inspect", "--format", "{{json .State}}", identity)


def build_kill_argv(runtime: OciRuntime, identity: str) -> tuple[str, ...]:
    _validate_identity(identity)
    return (*runtime.prefix, "kill", "--signal", "KILL", identity)


def build_remove_argv(runtime: OciRuntime, identity: str) -> tuple[str, ...]:
    _validate_identity(identity)
    return (*runtime.prefix, "rm", "--force", identity)


def _validate_identity(identity: str) -> None:
    if _CONTAINER_RE.fullmatch(identity) is None and _NAME_RE.fullmatch(identity) is None:
        raise ValueError("invalid OCI container identity")


def _unsafe_mount_path(value: str) -> bool:
    return "," in value or "\x00" in value or _unsafe_argument(value)


@dataclass(frozen=True)
class _DirectoryIdentity:
    path: Path
    device: int
    inode: int


def _preflight(spec: SandboxSpec, image_ref: str, platform: str) -> tuple[str, _DirectoryIdentity]:
    parse_immutable_image_ref(image_ref)
    if platform not in {"linux/amd64", "linux/arm64"}:
        raise ValueError("unsupported OCI platform")
    if spec.ro_binds:
        raise ValueError("OCI backend refuses all ro_binds")
    module = approved_module_for_worker_args(spec.worker_args)
    limits = (
        (spec.rlimits.cpu_seconds, MAX_CPU_SECONDS),
        (spec.rlimits.address_space_bytes, MAX_ADDRESS_SPACE_BYTES),
        (spec.rlimits.nproc, MAX_NPROC),
    )
    if any(type(value) is not int or not 1 <= value <= maximum for value, maximum in limits):
        raise ValueError("OCI resource limit is outside protocol bounds")
    wall = spec.wall_clock_s
    if isinstance(wall, bool) or not math.isfinite(wall) or wall <= 0:
        raise ValueError("OCI wall clock must be finite and positive")
    stated = Path(spec.rw_out_dir)
    try:
        stated_stat = stated.lstat()
    except OSError:
        raise ValueError("rw_out_dir must exist") from None
    if stat.S_ISLNK(stated_stat.st_mode) or not stat.S_ISDIR(stated_stat.st_mode):
        raise ValueError("rw_out_dir must be a non-symlink directory")
    resolved = stated.resolve(strict=True)
    if _unsafe_mount_path(str(resolved)):
        raise ValueError("rw_out_dir cannot be represented safely as an OCI mount")
    current = resolved.stat()
    return module, _DirectoryIdentity(resolved, current.st_dev, current.st_ino)


def _same_directory(identity: _DirectoryIdentity) -> bool:
    try:
        current = identity.path.stat()
    except OSError:
        return False
    return stat.S_ISDIR(current.st_mode) and (current.st_dev, current.st_ino) == (
        identity.device,
        identity.inode,
    )


def _json_unique(payload: bytes) -> object:
    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    try:
        text = payload.decode("utf-8")
        if not text.endswith("\n") or "\n" in text[:-1] or "\r" in text:
            raise ValueError("expected exactly one JSON record")
        value: object = json.loads(text, object_pairs_hook=unique)
        return value
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid JSON record") from exc


class OciBackend:
    """Explicit OCI backend; execution is impossible until this instance probes."""

    def __init__(
        self,
        runtime: OciRuntime,
        image_ref: str,
        platform: OciPlatform | None = None,
        *,
        identity: OciIdentity | None = None,
        transport: OciTransport | None = None,
    ) -> None:
        self.runtime = runtime
        self.image_ref = str(parse_immutable_image_ref(image_ref))
        self.platform: OciPlatform = platform_for_machine() if platform is None else platform
        self.identity = identity or OciIdentity(os.geteuid(), os.getegid())
        if self.platform not in {"linux/amd64", "linux/arm64"}:
            raise ValueError("unsupported OCI platform")
        self._transport: OciTransport = transport or SubprocessTransport()
        self._passing_report: CapabilityReport | None = None

    @property
    def name(self) -> str:
        return f"oci-{self.runtime.kind}"

    def probe(self) -> CapabilityReport:
        """Validate runtime/image and run fresh manifest and containment containers.

        Only a passing report is retained, and only in this backend instance.
        """
        if self._passing_report is not None:
            return self._passing_report
        try:
            self._validate_runtime()
            self._validate_image()
            features = self._live_probe()
            if any(features.get(name) is not True for name in REQUIRED_OCI_FEATURES):
                raise SandboxDeniedError("live OCI containment evidence is incomplete")
        except (
            OSError,
            TypeError,
            UnicodeError,
            ValueError,
            SandboxDeniedError,
            TransportTimeout,
            TransportOutputLimit,
        ) as exc:
            return CapabilityReport(
                backend=self.name,
                available=False,
                reason=f"OCI sandbox unavailable: {exc}",
                probed_at=time.time(),
                features={},
            )
        report = CapabilityReport(
            backend=self.name,
            available=True,
            probed_at=time.time(),
            features=features,
        )
        self._passing_report = report
        return report

    def execute(self, spec: SandboxSpec, stdin_payload: bytes) -> ExecOutcome:
        # Preflight deliberately runs before checking the capability gate, so a
        # malformed request never reaches (or depends on) transport state.
        _preflight(spec, self.image_ref, self.platform)
        report = self._passing_report
        if (
            report is None
            or not report.available
            or report.backend != self.name
            or any(report.features.get(name) is not True for name in REQUIRED_OCI_FEATURES)
        ):
            raise SandboxDeniedError(
                "sandbox_unavailable: OCI execution requires a passing probe "
                "on this backend instance"
            )
        return self._run_container(spec, stdin_payload)

    def _call(
        self,
        argv: Sequence[str],
        *,
        input: bytes = b"",
        timeout: float = 10.0,
        stdout_limit: int = PROBE_STDOUT_MAX_BYTES,
        stderr_limit: int = PROBE_STDERR_MAX_BYTES,
    ) -> TransportResult:
        return self._transport.run(
            argv,
            input=input,
            timeout=timeout,
            stdout_limit=stdout_limit,
            stderr_limit=stderr_limit,
            env=RUNTIME_ENV,
        )

    def _validate_runtime(self) -> None:
        endpoint = self.runtime.endpoint
        identity = self.runtime.server_identity
        if endpoint is None or identity is None or not self.runtime.selector:
            raise SandboxDeniedError("runtime lacks an explicit validated local endpoint")
        if not (
            endpoint.startswith("unix:///")
            or endpoint.startswith("unix://")
            or endpoint.startswith("/")
        ):
            raise SandboxDeniedError("remote OCI endpoint is forbidden")
        lowered = identity.lower()
        allowed = (
            ("docker desktop", "orbstack") if self.runtime.kind == "docker" else ("podman machine",)
        )
        identity_token = next((token for token in allowed if token in lowered), None)
        if identity_token is None:
            raise SandboxDeniedError("runtime server identity is not an approved local VM")
        self._validate_runtime_endpoint(endpoint)
        argv = (*self.runtime.prefix, "info", "--format", "{{json .}}")
        result = self._call(argv)
        if result.returncode != 0 or result.stderr:
            raise SandboxDeniedError("runtime info validation failed")
        value = _json_unique(result.stdout)
        if not isinstance(value, dict):
            raise SandboxDeniedError("runtime info response is malformed")
        os_name = value.get("OSType", value.get("os"))
        architecture = value.get("Architecture", value.get("arch"))
        host = value.get("host")
        if isinstance(host, dict):
            os_name = host.get("os", os_name)
            architecture = host.get("arch", architecture)
        expected_arch = self.platform.removeprefix("linux/")
        aliases = {"amd64": {"amd64", "x86_64"}, "arm64": {"arm64", "aarch64"}}
        if (
            os_name != "linux"
            or not isinstance(architecture, str)
            or architecture not in aliases[expected_arch]
        ):
            raise SandboxDeniedError("runtime server platform does not match the requested image")
        encoded_info = json.dumps(value, sort_keys=True).lower()
        if identity_token not in encoded_info:
            raise SandboxDeniedError(
                "runtime server did not confirm its expected local VM identity"
            )

    def _validate_runtime_endpoint(self, endpoint: str) -> None:
        selector_name = self.runtime.selector[1]
        if self.runtime.kind == "docker":
            argv = (
                str(self.runtime.path),
                "context",
                "inspect",
                selector_name,
                "--format",
                "{{json .}}",
            )
            result = self._call(argv)
            value = _json_unique(result.stdout) if result.returncode == 0 else None
            endpoints = value.get("Endpoints") if isinstance(value, dict) else None
            docker = endpoints.get("docker") if isinstance(endpoints, dict) else None
            observed = docker.get("Host") if isinstance(docker, dict) else None
            if result.stderr or observed != endpoint:
                raise SandboxDeniedError("Docker context endpoint validation failed")
            return

        argv = (
            str(self.runtime.path),
            "system",
            "connection",
            "list",
            "--format",
            "json",
        )
        result = self._call(argv)
        value = _json_unique(result.stdout) if result.returncode == 0 else None
        if result.stderr or not isinstance(value, list):
            raise SandboxDeniedError("Podman connection validation failed")
        matches = [
            item
            for item in value
            if isinstance(item, dict)
            and item.get("Name") == selector_name
            and item.get("URI") == endpoint
        ]
        if len(matches) != 1:
            raise SandboxDeniedError("Podman connection is not tied to the selected local machine")

    def _validate_image(self) -> None:
        argv = (*self.runtime.prefix, "image", "inspect", self.image_ref, "--format", "{{json .}}")
        result = self._call(argv)
        if result.returncode != 0 or result.stderr:
            raise SandboxDeniedError("immutable executor image is not available locally")
        value = _json_unique(result.stdout)
        if not isinstance(value, dict):
            raise SandboxDeniedError("image inspection response is malformed")
        config = value.get("Config")
        repo_digests = value.get("RepoDigests")
        if not isinstance(config, dict) or not isinstance(repo_digests, list):
            raise SandboxDeniedError("image metadata is incomplete")
        if self.image_ref not in repo_digests:
            raise SandboxDeniedError("local image metadata does not attest the requested digest")
        expected_arch = self.platform.removeprefix("linux/")
        architecture = value.get("Architecture")
        aliases = {"amd64": {"amd64", "x86_64"}, "arm64": {"arm64", "aarch64"}}
        if (
            value.get("Os") != "linux"
            or not isinstance(architecture, str)
            or architecture not in aliases[expected_arch]
        ):
            raise SandboxDeniedError("executor image platform mismatch")
        if config.get("Entrypoint") != list(AUDITED_ENTRYPOINT):
            raise SandboxDeniedError("executor image entrypoint mismatch")
        if config.get("Cmd") not in (None, []):
            raise SandboxDeniedError("executor image command must be empty")
        if value.get("Volumes") not in (None, {}) or config.get("Volumes") not in (None, {}):
            raise SandboxDeniedError("executor image declares volumes")
        image_env = config.get("Env")
        if image_env is None:
            image_env = []
        if image_env != list(AUDITED_IMAGE_ENV):
            raise SandboxDeniedError("executor image environment mismatch")
        image_id = value.get("Id")
        if (
            not isinstance(image_id, str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", image_id, re.ASCII) is None
        ):
            raise SandboxDeniedError("executor image identity is missing")

    def _live_probe(self) -> dict[str, bool]:
        with tempfile.TemporaryDirectory(prefix="heph-oci-probe-") as temporary:
            root = Path(temporary)
            manifest_dir = root / "manifest"
            manifest_dir.mkdir()
            manifest_spec = _probe_spec(manifest_dir)
            manifest = self._run_container(
                manifest_spec,
                b"",
                command_tail=("manifest",),
                stdout_limit=PROBE_STDOUT_MAX_BYTES,
                stderr_limit=PROBE_STDERR_MAX_BYTES,
            )
            if (
                manifest.timed_out
                or manifest.exit_code != 0
                or manifest.stderr
                or manifest.stdout != manifest_bytes()
            ):
                raise SandboxDeniedError("executor manifest verification failed")

            probe_dir = root / "containment"
            probe_dir.mkdir()
            nonce = secrets.token_hex(32)
            payload = json.dumps(
                {"nonce": nonce, "protocol_version": PROTOCOL_VERSION},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("ascii")
            probe_spec = _probe_spec(probe_dir)
            outcome = self._run_container(
                probe_spec,
                payload,
                stdout_limit=PROBE_STDOUT_MAX_BYTES,
                stderr_limit=PROBE_STDERR_MAX_BYTES,
            )
            if outcome.timed_out or outcome.exit_code != 0 or outcome.stderr:
                raise SandboxDeniedError("OCI containment probe process failed")
            value = _json_unique(outcome.stdout)
            return _validate_probe_response(
                value,
                nonce,
                probe_spec,
                probe_dir,
                self.identity,
            )

    def _run_container(
        self,
        spec: SandboxSpec,
        stdin_payload: bytes,
        *,
        command_tail: Sequence[str] | None = None,
        stdout_limit: int = EXEC_STDOUT_MAX_BYTES,
        stderr_limit: int = EXEC_STDERR_MAX_BYTES,
    ) -> ExecOutcome:
        _, directory = _preflight(spec, self.image_ref, self.platform)
        name = f"heph-exec-{secrets.token_hex(32)}"
        create_argv = build_create_argv(
            self.runtime,
            self.image_ref,
            self.platform,
            spec,
            name,
            identity=self.identity,
            command_tail=command_tail,
        )
        deadline = time.monotonic() + float(spec.wall_clock_s)
        container_id: str | None = None
        try:
            create = self._call(create_argv, timeout=_remaining(deadline))
            if create.returncode != 0 or create.stderr:
                raise SandboxDeniedError("OCI container creation failed")
            lines = create.stdout.decode("ascii", errors="strict").splitlines()
            if len(lines) != 1:
                raise SandboxDeniedError("runtime returned an ambiguous container id")
            container_id = _validated_container_id(lines[0])
            if not _same_directory(directory):
                raise SandboxDeniedError("rw_out_dir changed during container creation")
            try:
                attached = self._call(
                    build_start_argv(self.runtime, container_id),
                    input=stdin_payload,
                    timeout=_remaining(deadline),
                    stdout_limit=stdout_limit,
                    stderr_limit=stderr_limit,
                )
            except TransportOutputLimit:
                self._cleanup(container_id)
                return ExecOutcome(
                    exit_code=125,
                    stdout=b"",
                    stderr=b"OCI worker output limit exceeded\n",
                    timed_out=False,
                )
            except TransportTimeout:
                self._cleanup(container_id)
                return ExecOutcome(exit_code=137, stdout=b"", stderr=b"", timed_out=True)
            try:
                state = self._inspect_present(container_id, timeout=_remaining(deadline))
                if state["Running"] is not False:
                    raise SandboxDeniedError("attach ended while OCI container was still running")
                exit_code = state["ExitCode"]
                if type(exit_code) is not int or not 0 <= exit_code <= 255:
                    raise SandboxDeniedError("container exit status is invalid")
                self._remove_and_confirm(container_id)
            except TransportTimeout:
                self._cleanup(container_id)
                return ExecOutcome(exit_code=137, stdout=b"", stderr=b"", timed_out=True)
            return ExecOutcome(exit_code, attached.stdout, attached.stderr, False)
        except (TransportTimeout, subprocess.TimeoutExpired):
            self._cleanup(container_id or name)
            return ExecOutcome(exit_code=137, stdout=b"", stderr=b"", timed_out=True)
        except TransportOutputLimit:
            self._cleanup(container_id or name)
            raise SandboxDeniedError("OCI runtime control output exceeded its bound") from None
        except UnicodeDecodeError:
            self._cleanup(container_id or name)
            raise SandboxDeniedError("runtime returned a non-ASCII container id") from None
        except (OSError, ValueError) as exc:
            self._cleanup(container_id or name)
            raise SandboxDeniedError("OCI runtime lifecycle failed closed") from exc
        except SandboxDeniedError:
            self._cleanup(container_id or name)
            raise
        except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
            # Cancellation must not orphan a container.  Cleanup ambiguity is
            # intentionally allowed to replace the cancellation fail-closed.
            self._cleanup(container_id or name)
            raise

    def _inspect(self, identity: str, *, timeout: float = 5.0) -> dict[str, object] | None:
        result = self._call(build_inspect_argv(self.runtime, identity), timeout=timeout)
        if result.returncode != 0:
            text = result.stderr.decode("utf-8", errors="replace").lower()
            absent = (
                "no such object",
                "no such container",
                "no container with name or id",
            )
            if any(marker in text for marker in absent):
                return None
            raise SandboxDeniedError("container existence could not be determined")
        if result.stderr:
            raise SandboxDeniedError("container inspection produced unexpected diagnostics")
        value = _json_unique(result.stdout)
        if not isinstance(value, dict) or not {"Running", "ExitCode"}.issubset(value):
            raise SandboxDeniedError("container state response is malformed")
        if type(value["Running"]) is not bool:
            raise SandboxDeniedError("container running state is malformed")
        return value

    def _inspect_present(self, identity: str, *, timeout: float = 5.0) -> dict[str, object]:
        state = self._inspect(identity, timeout=timeout)
        if state is None:
            raise SandboxDeniedError("container disappeared before status inspection")
        return state

    def _remove_and_confirm(self, identity: str) -> None:
        removed = self._call(build_remove_argv(self.runtime, identity), timeout=5.0)
        if removed.returncode != 0:
            raise SandboxDeniedError("OCI container removal failed")
        if self._inspect(identity) is not None:
            raise SandboxDeniedError("OCI container removal could not be confirmed")

    def _cleanup(self, identity: str) -> None:
        """Boundedly kill and force-remove, then require confirmed absence."""
        failure: Exception | None = None
        try:
            state = self._inspect(identity)
        except Exception as exc:
            failure = exc
            state = {}
        if state is None:
            return

        if state.get("Running") is True:
            try:
                killed = self._call(build_kill_argv(self.runtime, identity), timeout=5.0)
                if killed.returncode != 0:
                    failure = SandboxDeniedError("OCI container kill command failed")
            except Exception as exc:
                failure = exc
            # Runtime termination may be asynchronous. Poll boundedly, but do
            # not let a slow/failed kill prevent the force-removal attempt.
            for _ in range(5):
                try:
                    observed = self._inspect(identity, timeout=1.0)
                except Exception as exc:
                    failure = exc
                    break
                if observed is None:
                    return
                state = observed
                if state.get("Running") is False:
                    break
                time.sleep(0.05)

        try:
            removed = self._call(build_remove_argv(self.runtime, identity), timeout=5.0)
            if removed.returncode != 0:
                failure = SandboxDeniedError("OCI force-removal command failed")
        except Exception as exc:
            failure = exc
        try:
            remaining = self._inspect(identity, timeout=5.0)
        except Exception as exc:
            remaining = state
            failure = exc
        if remaining is None:
            return
        raise SandboxDeniedError(
            "OCI cleanup was ambiguous; container absence was not confirmed"
        ) from failure


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TransportTimeout()
    return remaining


def _probe_spec(path: Path) -> SandboxSpec:
    from hephaestus.core.executor.sandbox.base import Rlimits

    return SandboxSpec(
        worker_args=("-m", PROBE_WORKER),
        ro_binds=(),
        rw_out_dir=path,
        rlimits=Rlimits(MAX_CPU_SECONDS, MAX_ADDRESS_SPACE_BYTES, MAX_NPROC),
        wall_clock_s=float(MAX_CPU_SECONDS + 30),
    )


def _validate_probe_response(
    value: object,
    nonce: str,
    spec: SandboxSpec,
    probe_dir: Path,
    identity: OciIdentity,
) -> dict[str, bool]:
    required = {
        "cgroup",
        "cwd",
        "effective_gid",
        "effective_uid",
        "hostname",
        "kind",
        "mounts",
        "network",
        "nonce",
        "no_new_privs",
        "oci_profile_version",
        "pid",
        "protocol_version",
        "capabilities",
        "rlimits",
        "root_write_errno",
        "tmp_capacity_bytes",
        "tmp_write_errno",
        "work_proof",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise SandboxDeniedError("OCI probe response schema mismatch")
    if (
        value["nonce"] != nonce
        or value["kind"] != "hephaestus_executor_probe"
        or value["protocol_version"] != PROTOCOL_VERSION
        or value["oci_profile_version"] != OCI_PROFILE_VERSION
    ):
        raise SandboxDeniedError("OCI probe identity mismatch")
    features = {name: False for name in REQUIRED_OCI_FEATURES}
    effective_uid = value["effective_uid"]
    effective_gid = value["effective_gid"]
    features["numeric_identity"] = (
        type(effective_uid) is int
        and type(effective_gid) is int
        and effective_uid == identity.uid
        and effective_gid == identity.gid
    )

    caps = value["capabilities"]
    features["capabilities_dropped"] = (
        isinstance(caps, dict)
        and set(caps) == {"CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb"}
        and all(item == "0000000000000000" for item in caps.values())
    )
    features["no_new_privileges"] = (
        type(value["no_new_privs"]) is int and value["no_new_privs"] == 1
    )
    features["pid_namespace"] = type(value["pid"]) is int and value["pid"] == 1
    features["uts_namespace"] = value["hostname"] == OCI_HOSTNAME

    limits = value["rlimits"]
    expected = {
        "RLIMIT_AS": spec.rlimits.address_space_bytes,
        "RLIMIT_DATA": spec.rlimits.address_space_bytes,
        "RLIMIT_CPU": spec.rlimits.cpu_seconds,
        "RLIMIT_NPROC": spec.rlimits.nproc,
    }
    limits_ok = isinstance(limits, dict) and set(limits) == {*expected, "RLIMIT_CORE"}
    if limits_ok:
        core = limits["RLIMIT_CORE"]
        limits_ok = core == [0, 0]
        for key, maximum in expected.items():
            pair = limits[key]
            limits_ok = limits_ok and (
                isinstance(pair, list)
                and len(pair) == 2
                and all(type(item) is int and 0 < item <= maximum for item in pair)
                and pair[0] <= pair[1]
            )
    features["rlimits"] = limits_ok

    mounts = value["mounts"]
    if isinstance(mounts, dict) and set(mounts) == {"/", "/work", "/tmp"}:
        root, work, tmp = mounts["/"], mounts["/work"], mounts["/tmp"]
        root_write_errno = value["root_write_errno"]
        features["root_read_only"] = (
            _mount_has(root, "/", "ro")
            and type(root_write_errno) is int
            and root_write_errno in {errno.EROFS, errno.EACCES}
        )
        proof_name = value["work_proof"]
        proof_ok = False
        if isinstance(proof_name, str) and proof_name == f".heph-oci-probe-{nonce}":
            proof = probe_dir / proof_name
            try:
                info = proof.lstat()
                proof_ok = (
                    stat.S_ISREG(info.st_mode)
                    and not proof.is_symlink()
                    and proof.read_text("ascii") == nonce
                )
            except (OSError, UnicodeError):
                proof_ok = False
        features["work_writable"] = (
            value["cwd"] == "/work" and _mount_has(work, "/work", "rw") and proof_ok
        )
        features["tmpfs_profile"] = (
            _mount_has(tmp, "/tmp", "rw", fs_type="tmpfs")
            and all(_mount_option(tmp, option) for option in ("nosuid", "nodev", "noexec"))
            and type(value["tmp_capacity_bytes"]) is int
            and 0 < value["tmp_capacity_bytes"] <= OCI_TMPFS_BYTES
            and type(value["tmp_write_errno"]) is int
            and value["tmp_write_errno"] == 0
        )

    network = value["network"]
    connect_errno = network.get("connect_errno") if isinstance(network, dict) else None
    features["network_isolated"] = (
        isinstance(network, dict)
        and set(network) == {"interfaces", "routes", "connect_errno"}
        and network["interfaces"] == ["lo"]
        and network["routes"] == []
        and type(connect_errno) is int
        and connect_errno
        in {errno.ENETUNREACH, errno.EHOSTUNREACH, errno.EAFNOSUPPORT, errno.ENETDOWN}
    )

    cgroup = value["cgroup"]
    if (
        isinstance(cgroup, dict)
        and set(cgroup)
        == {"version", "memory_max", "memory_swap_max", "memory_swap_mode", "pids_max", "cpu_quota"}
        and type(cgroup["version"]) is int
        and cgroup["version"] in {1, 2}
    ):
        memory = cgroup["memory_max"]
        pids = cgroup["pids_max"]
        features["cgroup_memory"] = (
            type(memory) is int and 0 < memory <= spec.rlimits.address_space_bytes
        )
        features["cgroup_pids"] = type(pids) is int and 0 < pids <= spec.rlimits.nproc
        swap = cgroup["memory_swap_max"]
        if cgroup["memory_swap_mode"] == "additional":
            features["cgroup_swap"] = type(swap) is int and swap == 0
        elif cgroup["memory_swap_mode"] == "total":
            features["cgroup_swap"] = (
                type(swap) is int and type(memory) is int and 0 < swap <= memory
            )
        cpu = cgroup["cpu_quota"]
        if isinstance(cpu, dict) and set(cpu) == {"quota", "period"}:
            quota, period = cpu["quota"], cpu["period"]
            features["cgroup_cpu"] = (
                type(quota) is int
                and type(period) is int
                and quota > 0
                and period > 0
                and quota <= period
            )
    if any(value is not True for value in features.values()):
        missing = sorted(name for name, passed in features.items() if passed is not True)
        raise SandboxDeniedError("OCI containment checks failed: " + ", ".join(missing))
    return features


def _mount_has(value: object, mountpoint: str, option: str, *, fs_type: str | None = None) -> bool:
    return (
        isinstance(value, dict)
        and value.get("mountpoint") == mountpoint
        and (fs_type is None or value.get("fs_type") == fs_type)
        and _mount_option(value, option)
    )


def _mount_option(value: object, option: str) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("options"), list)
        and option in value["options"]
    )


__all__ = [
    "AUDITED_ENTRYPOINT",
    "AUDITED_IMAGE_ENV",
    "ImmutableImageRef",
    "OciBackend",
    "OciIdentity",
    "OciRuntime",
    "OciTransport",
    "SubprocessTransport",
    "TransportOutputLimit",
    "TransportReapError",
    "TransportResult",
    "TransportTimeout",
    "build_create_argv",
    "build_inspect_argv",
    "build_kill_argv",
    "build_remove_argv",
    "build_start_argv",
    "parse_immutable_image_ref",
    "platform_for_machine",
]
