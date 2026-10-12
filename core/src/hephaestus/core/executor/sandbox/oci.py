"""Conservative OCI host mechanics (not selected by production policy).

This module contains only an explicitly constructed backend.  It performs no
runtime discovery and has no default image: callers must supply an immutable
image digest and a validated local runtime.  Production platform selection is
intentionally outside this module and remains disabled.
"""

from __future__ import annotations

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
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import BinaryIO, Literal, Protocol, cast

from hephaestus.core.errors import SandboxDeniedError, ValidationError
from hephaestus.core.executor.cancellation import Cancellation, ExecutionCancelled
from hephaestus.core.executor.identity import ExecutionIdentity
from hephaestus.core.executor.sandbox.base import CapabilityReport, ExecOutcome, SandboxSpec
from hephaestus.core.executor.sandbox.oci_network import network_isolated
from hephaestus.core.executor.sandbox.oci_protocol import (
    EXEC_STDERR_MAX_BYTES,
    EXEC_STDOUT_MAX_BYTES,
    MAX_ADDRESS_SPACE_BYTES,
    MAX_CPU_SECONDS,
    MAX_NPROC,
    OCI_HOSTNAME,
    OCI_PROFILE_VERSION,
    PROBE_STDERR_MAX_BYTES,
    PROBE_STDOUT_MAX_BYTES,
    PROBE_WORKER,
    PROTOCOL_VERSION,
    REQUIRED_OCI_FEATURES,
    approved_module_for_worker_args,
    manifest_bytes,
)

from .oci_ownership import OwnershipJournal
from .oci_storage import storage_valid
from .oci_storage_policy import MQUEUE_MASK, REQUEST_MAX_BYTES, STORAGE_POLICIES, StoragePolicy
from .oci_transfer import FileRecord, Receiver, encode, snapshot_inputs, unique_json

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
        stdout_consumer: Callable[[bytes], None] | None = None,
    ) -> TransportResult: ...


class SubprocessTransport:
    """Bounded, shell-free subprocess transport used by the real backend."""

    def __init__(
        self,
        *,
        cancellation: Cancellation | None = None,
        ownership: OwnershipJournal | None = None,
    ) -> None:
        self.cancellation = cancellation
        self.ownership = ownership

    def run(
        self,
        argv: Sequence[str],
        *,
        input: bytes,
        timeout: float,
        stdout_limit: int,
        stderr_limit: int,
        env: Mapping[str, str],
        stdout_consumer: Callable[[bytes], None] | None = None,
    ) -> TransportResult:
        if timeout <= 0:
            raise TransportTimeout()
        if self.cancellation is not None and "start" in argv:
            self.cancellation.check()
        selector = selectors.DefaultSelector()
        try:
            if self.ownership is not None:
                self.ownership.launching_client()
            proc = subprocess.Popen(
                tuple(argv),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                close_fds=True,
                start_new_session=True,
                env=dict(env),
            )
        except BaseException:
            selector.close()
            raise
        stdout = bytearray()
        stderr = bytearray()
        stdout_count = 0
        try:
            if self.ownership is not None:
                self.ownership.client(proc.pid, reaped=False)
            # Never interrupt create on user cancellation: receive its bounded
            # response first. Cleanup/control calls must also remain deliverable.
            control = self.cancellation if "start" in argv else None
            if control is not None:
                control.check()
                selector.register(control.reader, selectors.EVENT_READ, "cancel")
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
            while any(key.data != "cancel" for key in selector.get_map().values()):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TransportTimeout(bytes(stdout), bytes(stderr))
                events = selector.select(remaining)
                if not events:
                    raise TransportTimeout(bytes(stdout), bytes(stderr))
                for key, _ in events:
                    if key.data == "cancel":
                        assert control is not None
                        control.check()
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
                    if channel == "stdout" and stdout_consumer is not None:
                        stdout_count += len(chunk)
                        if stdout_count > stdout_limit:
                            raise TransportOutputLimit("stdout")
                        stdout_consumer(chunk)
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
            # Keep the group leader waitable (unreaped) until descendants have
            # been signalled: after wait()/poll(), its PID could be reused.
            while os.waitid(os.P_PID, proc.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is None:
                if control is not None:
                    control.check()
                if time.monotonic() >= deadline:
                    raise TransportTimeout(bytes(stdout), bytes(stderr))
                time.sleep(0.01)
            # Darwin returns EPERM for a group containing only its zombie
            # leader. Reap then independently require group absence; an actual
            # unkillable descendant still refuses in _reap_group.
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=5.0)
            self._reap_group(proc)
            return TransportResult(int(proc.returncode), bytes(stdout), bytes(stderr))
        except BaseException as exc:
            if isinstance(exc, ExecutionCancelled):
                exc.stdout, exc.stderr = bytes(stdout), bytes(stderr)
            if proc.returncode is None:
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(proc.pid, signal.SIGKILL)
                # Do not poll/reap before signalling this owned process group.
                with contextlib.suppress(OSError):
                    proc.kill()
            try:
                proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired as exc:
                raise TransportReapError("OCI runtime client could not be reaped") from exc
            self._reap_group(proc)
            raise
        finally:
            selector.close()
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                if stream is not None:
                    with contextlib.suppress(OSError):
                        stream.close()

    def _reap_group(self, proc: subprocess.Popen[bytes]) -> None:
        # Signalling happened before wait/reap while PID ownership was certain.
        # This check may refuse on surviving zombies, but never kills a reused PID.
        deadline = time.monotonic() + 2.0
        while True:
            try:
                os.killpg(proc.pid, 0)
            except ProcessLookupError:
                break
            except PermissionError:
                pass  # Darwin zombie-only group; NOT proof of absence.
            if time.monotonic() >= deadline:
                raise TransportReapError("OCI client process group remains")
            time.sleep(0.01)
        if self.ownership is not None:
            self.ownership.client(proc.pid, reaped=True)


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


def _profile_modules(profile: str) -> frozenset[str]:
    if profile == "executor":
        from .oci_protocol import APPROVED_MODULES

        return APPROVED_MODULES
    if profile == "renderer":
        from hephaestus.core.render.oci_protocol import RENDER_MODULES

        return RENDER_MODULES
    raise ValueError("unsupported OCI runtime profile")


def _profile_entrypoint(profile: str) -> tuple[str, ...]:
    _profile_modules(profile)
    if profile == "renderer":
        return (*AUDITED_ENTRYPOINT[:-1], "hephaestus.core.render.oci_launcher")
    return AUDITED_ENTRYPOINT


def build_create_argv(
    runtime: OciRuntime,
    image_ref: str,
    platform: OciPlatform,
    spec: SandboxSpec,
    container_name: str,
    *,
    identity: OciIdentity,
    command_tail: Sequence[str] | None = None,
    input_snapshot: Path | None = None,
    storage_policy: str = "ordinary",
    nonce: str = "0" * 64,
    runtime_profile: str = "executor",
) -> tuple[str, ...]:
    """Build the canonical create argv.  This function starts no process."""
    image = str(parse_immutable_image_ref(image_ref))
    _validated_name(container_name)
    module, directory = _preflight(spec, image_ref, platform, runtime_profile)
    if storage_policy not in STORAGE_POLICIES or re.fullmatch(r"[0-9a-f]{64}", nonce) is None:
        raise ValueError("invalid storage invocation")
    policy = STORAGE_POLICIES[storage_policy]
    source = input_snapshot or directory.path / "inputs"
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
            storage_policy,
            nonce,
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
        "--log-driver=none",
        "--no-healthcheck",
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
        "/tmp:" + _tmpfs_options(policy.tmp_bytes, policy.tmp_inodes, identity),
        "--tmpfs",
        "/work:" + _tmpfs_options(policy.work_bytes, policy.work_inodes, identity),
        "--tmpfs",
        "/dev/mqueue:" + MQUEUE_MASK,
        "--mount",
        f"type=bind,source={source_text},destination=/inputs,readonly,bind-propagation=rprivate",
        "--workdir",
        "/work",
        image,
        *tail,
    )


def _tmpfs_options(size: int, inodes: int, identity: OciIdentity) -> str:
    return (
        f"rw,nosuid,nodev,noexec,size={size},nr_inodes={inodes},"
        f"mode=0700,uid={identity.uid},gid={identity.gid}"
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


def _preflight(
    spec: SandboxSpec, image_ref: str, platform: str, runtime_profile: str = "executor"
) -> tuple[str, _DirectoryIdentity]:
    parse_immutable_image_ref(image_ref)
    if platform not in {"linux/amd64", "linux/arm64"}:
        raise ValueError("unsupported OCI platform")
    if runtime_profile == "renderer" and platform != "linux/arm64":
        raise ValueError("experimental renderer requires native linux/arm64")
    if spec.ro_binds:
        raise ValueError("OCI backend refuses all ro_binds")
    if runtime_profile == "executor":
        module = approved_module_for_worker_args(spec.worker_args)
    else:
        modules = _profile_modules(runtime_profile)
        if (
            len(spec.worker_args) != 2
            or spec.worker_args[0] != "-m"
            or spec.worker_args[1] not in modules
        ):
            raise ValueError("worker arguments are not allowlisted for profile")
        module = spec.worker_args[1]
    limits = (
        (spec.rlimits.cpu_seconds, MAX_CPU_SECONDS),
        (spec.rlimits.address_space_bytes, MAX_ADDRESS_SPACE_BYTES),
        (spec.rlimits.nproc, MAX_NPROC),
    )
    if any(type(value) is not int or not 1 <= value <= maximum for value, maximum in limits):
        raise ValueError("OCI resource limit is outside protocol bounds")
    wall = spec.wall_clock_s
    if runtime_profile == "renderer" and (
        spec.rlimits.address_space_bytes > 2 * 1024**3 or spec.rlimits.nproc > 256 or wall > 180
    ):
        raise ValueError("experimental renderer resource envelope exceeded")
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
        storage_policy: str = "ordinary",
        ownership: OwnershipJournal | None = None,
        cancellation: Cancellation | None = None,
        scratch_dir: Path | None = None,
        runtime_profile: str = "executor",
    ) -> None:
        _profile_modules(runtime_profile)
        if runtime_profile == "renderer" and platform != "linux/arm64":
            raise ValueError("experimental renderer requires native linux/arm64")
        self._runtime_profile = runtime_profile
        if storage_policy not in STORAGE_POLICIES:
            raise ValueError("unsupported storage policy")
        self.ownership = ownership
        self.cancellation = cancellation
        self.scratch_dir = scratch_dir
        if ownership is not None:
            ownership.require_clean()
        self._storage_policy_name = storage_policy
        self._image_id: str | None = None
        self._execution_identity: ExecutionIdentity | None = None
        self.last_effective_config: dict[str, object] | None = None
        self.last_input_records: dict[str, FileRecord] = {}
        self.last_transfer_records: dict[str, FileRecord] = {}
        self.last_transfer_observation: dict[str, object] = {}
        self.last_container_id: str | None = None
        self.last_probe_response: object = None
        self.runtime = runtime
        self.image_ref = str(parse_immutable_image_ref(image_ref))
        self.platform: OciPlatform = platform_for_machine() if platform is None else platform
        self.identity = identity or OciIdentity(os.geteuid(), os.getegid())
        if self.platform not in {"linux/amd64", "linux/arm64"}:
            raise ValueError("unsupported OCI platform")
        self._transport: OciTransport = transport or SubprocessTransport(
            cancellation=cancellation, ownership=ownership
        )
        self._passing_report: CapabilityReport | None = None
        # Diagnostic ownership only, NOT a durable external supervisor. Unsettled
        # creates poison this instance even after best-effort name cleanup.
        self._unsettled_creates: set[str] = set()
        self._unreconciled_containers: set[str] = set()
        self._last_terminal_state: Mapping[str, object] | None = None

    @property
    def storage_policy_name(self) -> str:
        return self._storage_policy_name

    @property
    def storage_policy(self) -> StoragePolicy:
        return STORAGE_POLICIES[self._storage_policy_name]

    @property
    def unsettled_creates(self) -> frozenset[str]:
        return frozenset(self._unsettled_creates)

    @property
    def unreconciled_containers(self) -> frozenset[str]:
        return frozenset(self._unreconciled_containers)

    @property
    def last_terminal_state(self) -> Mapping[str, object] | None:
        """Validated state retained before removal; not durable live evidence."""
        return self._last_terminal_state

    @property
    def name(self) -> str:
        return f"oci-{self.runtime.kind}"

    def execution_identity(self) -> ExecutionIdentity:
        """Identity from this instance's trusted manifest run, not workload stdout.

        No daemon call on freshness reads. Poisoned ownership or configuration
        changes invalidate the cached capability rather than silently reusing it.
        """
        identity = self._execution_identity
        report = self._passing_report
        if (
            report is None
            or not report.available
            or report.backend != self.name
            or any(report.features.get(name) is not True for name in REQUIRED_OCI_FEATURES)
            or identity is None
            or self._unsettled_creates
            or self._unreconciled_containers
            or identity.to_json()["image_ref"] != self.image_ref
            or identity.to_json()["image_id"] != self._image_id
            or identity.to_json()["platform"] != self.platform
        ):
            raise SandboxDeniedError("trusted OCI execution identity unavailable or changed")
        return identity

    def probe(self) -> CapabilityReport:
        """Validate runtime/image and run fresh manifest and containment containers.

        Only a passing report is retained, and only in this backend instance.
        """
        if self._unsettled_creates:
            return CapabilityReport(
                backend=self.name,
                available=False,
                reason="OCI create settlement requires external supervision",
                features={},
            )
        if self._unreconciled_containers:
            return CapabilityReport(
                backend=self.name,
                available=False,
                reason="OCI owned-container reconciliation required",
                features={},
            )
        if self._passing_report is not None:
            try:
                self.execution_identity()
            except SandboxDeniedError as exc:
                return CapabilityReport(backend=self.name, available=False, reason=str(exc))
            return self._passing_report
        try:
            self._validate_runtime()
            self._validate_image()
            features = self._live_probe()
            if any(features.get(name) is not True for name in REQUIRED_OCI_FEATURES):
                raise SandboxDeniedError("live OCI containment evidence is incomplete")
            if self._execution_identity is None or self._image_id is None:
                raise SandboxDeniedError("live OCI execution identity is incomplete")
        except (
            OSError,
            TypeError,
            UnicodeError,
            ValueError,
            SandboxDeniedError,
            ValidationError,
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
        _preflight(spec, self.image_ref, self.platform, self._runtime_profile)
        report = self._passing_report
        if (
            report is None
            or self._unreconciled_containers
            or self._unsettled_creates
            or not report.available
            or report.backend != self.name
            or any(report.features.get(name) is not True for name in REQUIRED_OCI_FEATURES)
        ):
            raise SandboxDeniedError(
                "sandbox_unavailable: OCI execution requires a passing probe "
                "on this backend instance"
            )
        identity = self.execution_identity()
        outcome = self._run_container(spec, stdin_payload)
        if self.execution_identity() != identity:
            raise SandboxDeniedError("OCI execution identity changed during execution")
        return replace(outcome, execution_identity=identity)

    def _call(
        self,
        argv: Sequence[str],
        *,
        input: bytes = b"",
        timeout: float = 10.0,
        stdout_limit: int = PROBE_STDOUT_MAX_BYTES,
        stderr_limit: int = PROBE_STDERR_MAX_BYTES,
        stdout_consumer: Callable[[bytes], None] | None = None,
    ) -> TransportResult:
        return self._transport.run(
            argv,
            input=input,
            timeout=timeout,
            stdout_limit=stdout_limit,
            stderr_limit=stderr_limit,
            env=RUNTIME_ENV,
            **({"stdout_consumer": stdout_consumer} if stdout_consumer is not None else {}),
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
        if config.get("Entrypoint") != list(_profile_entrypoint(self._runtime_profile)):
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
        if config.get("Healthcheck") not in (None, {"Test": ["NONE"]}):
            raise SandboxDeniedError("executor image declares a healthcheck")
        image_id = value.get("Id")
        if (
            not isinstance(image_id, str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", image_id, re.ASCII) is None
        ):
            raise SandboxDeniedError("executor image identity is missing")
        self._image_id = image_id

    def _validate_effective(
        self,
        container_id: str,
        spec: SandboxSpec,
        inputs: Path,
        argv: Sequence[str],
        *,
        timeout: float,
    ) -> None:
        result = self._call(
            (*self.runtime.prefix, "inspect", "--format", "{{json .}}", container_id),
            timeout=timeout,
        )
        value = (
            _json_unique(result.stdout) if result.returncode == 0 and not result.stderr else None
        )
        if (
            not isinstance(value, dict)
            or self._image_id is None
            or value.get("Image") != self._image_id
        ):
            raise SandboxDeniedError("effective container image mismatch")
        host, config, mounts = value.get("HostConfig"), value.get("Config"), value.get("Mounts")
        if (
            not isinstance(host, dict)
            or not isinstance(config, dict)
            or not isinstance(mounts, list)
        ):
            raise SandboxDeniedError("effective container config missing")
        expected = {
            "ReadonlyRootfs": True,
            "Privileged": False,
            "NetworkMode": "none",
            "IpcMode": "none",
            "PidMode": "",
            "UTSMode": "",
            "Memory": spec.rlimits.address_space_bytes,
            "MemorySwap": spec.rlimits.address_space_bytes,
            "PidsLimit": spec.rlimits.nproc,
            "NanoCpus": 1000000000,
            "CapDrop": ["ALL"],
            "LogConfig": {"Type": "none", "Config": {}},
        }
        if any(type(host.get(k)) is not type(v) or host[k] != v for k, v in expected.items()):
            raise SandboxDeniedError("effective resource/security/log configuration mismatch")
        security = (
            "no-new-privileges=true" if self.runtime.kind == "docker" else "no-new-privileges"
        )
        if host.get("SecurityOpt") != [security] or any(
            host.get(k) not in (None, [], {})
            for k in ("CapAdd", "Binds", "Devices", "DeviceRequests", "PortBindings")
        ):
            raise SandboxDeniedError("effective container grants extra access")
        policy = self.storage_policy
        tmpfs = {
            "/work": _tmpfs_options(policy.work_bytes, policy.work_inodes, self.identity),
            "/tmp": _tmpfs_options(policy.tmp_bytes, policy.tmp_inodes, self.identity),
            "/dev/mqueue": MQUEUE_MASK,
        }
        if host.get("Tmpfs") != tmpfs or value.get("LogPath") != "":
            raise SandboxDeniedError("effective tmpfs/logging mismatch")
        if (
            config.get("Entrypoint") != list(_profile_entrypoint(self._runtime_profile))
            or config.get("Cmd") != list(argv[argv.index(self.image_ref) + 1 :])
            or config.get("Env") != list(AUDITED_IMAGE_ENV)
            or config.get("WorkingDir") != "/work"
            or config.get("User") != f"{self.identity.uid}:{self.identity.gid}"
            or config.get("Hostname") != OCI_HOSTNAME
            or config.get("Healthcheck") != {"Test": ["NONE"]}
            or config.get("Tty") is not False
            or config.get("OpenStdin") is not True
        ):
            raise SandboxDeniedError("effective worker configuration mismatch")
        if len(mounts) != 1 or not isinstance(mounts[0], dict):
            raise SandboxDeniedError("unexpected effective mounts")
        mount = mounts[0]
        if (
            any(
                mount.get(k) != v
                for k, v in {
                    "Type": "bind",
                    "Source": str(inputs),
                    "Destination": "/inputs",
                    "RW": False,
                    "Propagation": "rprivate",
                }.items()
            )
            or type(mount.get("RW")) is not bool
        ):
            raise SandboxDeniedError("effective input mount mismatch")
        self.last_effective_config = value

    def _live_probe(self) -> dict[str, bool]:
        with tempfile.TemporaryDirectory(
            prefix="heph-oci-probe-", dir=self.scratch_dir
        ) as temporary:
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
            if manifest.timed_out or manifest.exit_code != 0 or manifest.stderr:
                raise SandboxDeniedError("executor manifest verification failed")
            self._accept_manifest(manifest.stdout)

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
            self.last_probe_response = value
            return _validate_probe_response(
                value,
                nonce,
                probe_spec,
                probe_dir,
                self.identity,
                self.storage_policy,
            )

    def _accept_manifest(self, payload: bytes) -> None:
        value = _json_unique(payload)
        if not isinstance(value, dict):
            raise SandboxDeniedError("executor manifest verification failed")
        inventory = value.get("execution_identity")
        # Exact canonical bytes reject extra fields, old versions and coercions.
        expected_manifest = manifest_bytes
        if self._runtime_profile == "renderer":
            from hephaestus.core.render.oci_protocol import manifest_bytes as render_manifest

            expected_manifest = render_manifest
        if payload != expected_manifest(inventory) or self._image_id is None:
            raise SandboxDeniedError("executor manifest verification failed")
        self._execution_identity = ExecutionIdentity.for_oci(
            image_ref=self.image_ref,
            image_id=self._image_id,
            platform=self.platform,
            runtime=inventory,
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
        module, directory = _preflight(spec, self.image_ref, self.platform, self._runtime_profile)
        if len(stdin_payload) > REQUEST_MAX_BYTES:
            raise ValueError("request byte limit")
        if command_tail is None:
            job = unique_json(stdin_payload)
            if not isinstance(job, dict):
                raise ValueError("job must be an object")
            from .oci_protocol import BUILD_WORKER, DFM_WORKER

            if module in {BUILD_WORKER, DFM_WORKER} and job.get("out_dir") != ".":
                raise ValueError("OCI output path must be fixed")
            if module == BUILD_WORKER:
                imports = job.get("imports", {})
                if not isinstance(imports, dict) or any(
                    not isinstance(v, str) or v not in spec.input_files for v in imports.values()
                ):
                    raise ValueError("undeclared build input")
                expected_inputs: set[str] = set()
                for leaf in imports.values():
                    if (
                        not isinstance(leaf, str)
                        or re.fullmatch(r"[0-9a-f]{32}\.(?:brep|hmesh|hpts)", leaf) is None
                    ):
                        raise ValueError("invalid build input name")
                    expected_inputs.add(leaf)
                    if leaf.endswith((".hmesh", ".hpts")):
                        expected_inputs.add(leaf + ".facts")
                if expected_inputs != set(spec.input_files):
                    raise ValueError("build input declaration disagrees with job")
            if module == "hephaestus.core.render.oci_worker":
                from hephaestus.core.render.oci_protocol import read_request

                request = read_request(stdin_payload)
                expected = () if request["operation"] == "probe" else ("source.brep",)
                if spec.input_files != expected:
                    raise ValueError("renderer input declaration mismatch")
            if module == DFM_WORKER and (
                job.get("brep") != "source.brep" or spec.input_files != ("source.brep",)
            ):
                raise ValueError("undeclared DFM input")
        nonce = secrets.token_hex(32)
        # Same filesystem for exclusive link installation. Host output is NEVER mounted.
        with tempfile.TemporaryDirectory(
            prefix=".heph-transfer-", dir=directory.path.parent
        ) as temporary:
            root = Path(temporary).resolve(strict=True)
            inputs, collected = root / "inputs", root / "collected"
            inputs.mkdir(mode=0o700)
            collected.mkdir(mode=0o700)
            self.last_input_records = dict(
                snapshot_inputs(directory.path, spec.input_files, inputs, self.storage_policy)
            )
            with contextlib.ExitStack() as stack:
                receiver = (
                    None
                    if command_tail
                    else stack.enter_context(
                        Receiver(collected, nonce, module, self.storage_policy)
                    )
                )
                try:
                    return self._run_staged(
                        spec,
                        stdin_payload,
                        directory,
                        inputs,
                        nonce,
                        receiver,
                        command_tail,
                        stdout_limit,
                        stderr_limit,
                    )
                finally:
                    if receiver is not None:
                        self.last_transfer_observation = {
                            "wire_bytes": receiver.total,
                            "body_bytes": receiver.body_bytes,
                            "created_files": list(receiver.created),
                            "state": receiver.state,
                            "installed": receiver.installed,
                        }

    def _run_staged(
        self,
        spec: SandboxSpec,
        stdin_payload: bytes,
        directory: _DirectoryIdentity,
        inputs: Path,
        nonce: str,
        receiver: Receiver | None,
        command_tail: Sequence[str] | None,
        stdout_limit: int,
        stderr_limit: int,
    ) -> ExecOutcome:
        name = f"heph-exec-{secrets.token_hex(32)}"
        create_argv = build_create_argv(
            self.runtime,
            self.image_ref,
            self.platform,
            spec,
            name,
            identity=self.identity,
            command_tail=command_tail,
            input_snapshot=inputs,
            storage_policy=self.storage_policy_name,
            nonce=nonce,
            runtime_profile=self._runtime_profile,
        )
        if self._unsettled_creates:
            raise SandboxDeniedError("OCI create settlement requires external supervision")
        if self.cancellation is not None:
            self.cancellation.check()
        if self.ownership is not None:
            self.ownership.require_clean()
            self.ownership.submitted(name)
        self._last_terminal_state = None
        self.last_container_id = None
        self.last_transfer_records = {}
        self.last_transfer_observation = {}
        deadline = time.monotonic() + float(spec.wall_clock_s)
        container_id: str | None = None
        reconciled = False
        self._unsettled_creates.add(name)  # before the daemon can receive create
        try:
            create = self._call(create_argv, timeout=_remaining(deadline))
            if create.returncode != 0 or create.stderr:
                raise SandboxDeniedError("OCI container creation failed")
            lines = create.stdout.decode("ascii", errors="strict").splitlines()
            if len(lines) != 1:
                raise SandboxDeniedError("runtime returned an ambiguous container id")
            container_id = _validated_container_id(lines[0])
            if self.ownership is not None:
                self.ownership.settled(name, container_id)
            self._unsettled_creates.discard(name)
            self.last_container_id = container_id
            if self.cancellation is not None:
                self.cancellation.check()
            self._validate_effective(
                container_id, spec, inputs, create_argv, timeout=_remaining(deadline)
            )
            if not _same_directory(directory):
                raise SandboxDeniedError("rw_out_dir changed during container creation")
            transfer_error: ValueError | None = None

            def consume(chunk: bytes) -> None:
                nonlocal transfer_error
                if transfer_error is None:
                    try:
                        assert receiver is not None
                        receiver.feed(chunk)
                    except ValueError as exc:
                        transfer_error = exc

            try:
                attached = self._call(
                    build_start_argv(self.runtime, container_id),
                    input=stdin_payload,
                    timeout=_remaining(deadline),
                    stdout_limit=(
                        (8 * 1024**2 + 8192)
                        if receiver and receiver.operation == "hephaestus.core.render.oci_worker"
                        else (
                            self.storage_policy.result_bytes
                            + self.storage_policy.export_bytes
                            + 8192
                            if receiver
                            else stdout_limit
                        )
                    ),
                    stderr_limit=stderr_limit,
                    stdout_consumer=consume if receiver else None,
                )
            except TransportOutputLimit:
                return ExecOutcome(
                    exit_code=125,
                    stdout=b"",
                    stderr=b"OCI worker output limit exceeded\n",
                    timed_out=False,
                )
            except TransportTimeout:
                return ExecOutcome(exit_code=137, stdout=b"", stderr=b"", timed_out=True)
            try:
                state = self._inspect_present(container_id, timeout=_remaining(deadline))
                if state["Running"] is not False:
                    raise SandboxDeniedError("attach ended while OCI container was still running")
                exit_code = cast(int, state["ExitCode"])
                if state["OOMKilled"] is not False:
                    raise SandboxDeniedError("OCI worker was OOM-killed")
                self._remove_and_confirm(container_id)
                reconciled = True
            except TransportTimeout:
                return ExecOutcome(exit_code=137, stdout=b"", stderr=b"", timed_out=True)
            result = attached.stdout
            if receiver:
                if transfer_error is not None:
                    raise SandboxDeniedError("OCI artifact transfer rejected") from transfer_error
                if exit_code != 0:
                    return ExecOutcome(exit_code, b"", attached.stderr, False)
                if attached.returncode != 0:
                    raise SandboxDeniedError("OCI attach client failed")
                try:
                    result = receiver.finish()
                except ValueError as exc:
                    raise SandboxDeniedError("OCI artifact transfer rejected") from exc
                if receiver.operation == "hephaestus.core.executor.worker":
                    from hephaestus.core.executor.artifacts import read_artifact

                    response = unique_json(result)
                    if "source_map" in receiver.files:
                        # The host-selected collected leaf is still private, not installed.
                        raw = read_artifact(inputs.parent / "collected", "source_map.json")
                        source_map = unique_json(raw)
                        if (
                            not isinstance(response, dict)
                            or not isinstance(response.get("source_map"), dict)
                            or encode(source_map) != encode(response["source_map"])
                        ):
                            raise SandboxDeniedError("OCI source map disagrees with response")
                if receiver.operation == "hephaestus.core.render.oci_worker":
                    from hephaestus.core.render.oci_protocol import read_request, validate_response

                    validate_response(result, read_request(stdin_payload))
                self.last_transfer_records = dict(receiver.files)
                if self.cancellation is not None:
                    self.cancellation.check()
                receiver.install(directory.path)
                receiver.close()  # drop source links BEFORE caller can publish
            return ExecOutcome(exit_code, result, attached.stderr, False)
        except (TransportTimeout, subprocess.TimeoutExpired):
            return ExecOutcome(exit_code=137, stdout=b"", stderr=b"", timed_out=True)
        except TransportOutputLimit:
            raise SandboxDeniedError("OCI runtime control output exceeded its bound") from None
        except UnicodeDecodeError:
            raise SandboxDeniedError("runtime returned a non-ASCII container id") from None
        except (OSError, ValueError) as exc:
            raise SandboxDeniedError("OCI runtime lifecycle failed closed") from exc
        finally:
            # Includes BaseExceptionGroup, receiver abort/unlink failures, client
            # reap failures and cancellation. Attach-client death is NOT worker
            # death. Never let an exceptional path bypass owned reconciliation.
            if not reconciled:
                try:
                    self._cleanup(container_id or name)
                except BaseException:
                    self._passing_report = None
                    if container_id is not None:
                        self._unreconciled_containers.add(container_id)
                    # Preserve the original failure as exception context; no
                    # timeout/failure outcome may hide uncertain cleanup.
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
        if not isinstance(value, dict) or not {"Running", "ExitCode", "OOMKilled"}.issubset(value):
            raise SandboxDeniedError("container state response is malformed")
        if type(value["Running"]) is not bool or type(value["OOMKilled"]) is not bool:
            raise SandboxDeniedError("container running/OOM state is malformed")
        if type(value["ExitCode"]) is not int or not 0 <= value["ExitCode"] <= 255:
            raise SandboxDeniedError("container exit status is invalid")
        if value["Running"] is False:
            self._last_terminal_state = MappingProxyType(
                {key: value[key] for key in ("Running", "ExitCode", "OOMKilled")}
            )
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
        self._record_absence(identity)

    def _cleanup(self, identity: str) -> None:
        """Never confuse name absence with settlement of an interrupted create.

        Polling is only best-effort reclamation, not a daemon request barrier.
        Without an external owner/reconciler this path MUST remain a failure,
        including when every inspection reports absence.
        """
        if _NAME_RE.fullmatch(identity):
            self._unsettled_creates.add(identity)
            self._passing_report = None
            try:
                for attempt in range(5):
                    if self._cleanup_known(identity):
                        break
                    if attempt < 4:
                        time.sleep(0.05)
            finally:
                raise SandboxDeniedError(
                    f"OCI create settlement unconfirmed; external supervisor required: {identity}"
                )
        self._cleanup_known(identity)

    def _cleanup_known(self, identity: str) -> bool:
        """Best-effort bounded reclamation; False means absent at first inspect."""
        failure: Exception | None = None
        try:
            state = self._inspect(identity)
        except Exception as exc:
            failure = exc
            state = {}
        if state is None:
            self._record_absence(identity)
            return False

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
                    self._record_absence(identity)
                    return True
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
            self._record_absence(identity)
            return True
        raise SandboxDeniedError(
            "OCI cleanup was ambiguous; container absence was not confirmed"
        ) from failure

    def _record_absence(self, identity: str) -> None:
        if self.ownership is not None:
            self.ownership.absent(
                identity, dict(self._last_terminal_state) if self._last_terminal_state else None
            )

    def reconcile_owned(self, ownership: OwnershipJournal) -> None:
        """Explicit recovery; never signal restored host PIDs (they can be reused).

        Known acknowledged creates can be removed/confirmed and reused normally.
        Unknown daemon requests and unreaped clients remain durable refusals even
        after a successful best-effort resource removal. No polling settles them.
        """
        self.ownership = ownership
        for name, record in ownership.state["containers"].items():
            if record["pending"] or not record["absent"]:
                self._last_terminal_state = None
                self._cleanup_known(record["id"] or name)
        ownership.require_clean()


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
        rlimits=Rlimits(15, 256 * 1024**2, 32),
        wall_clock_s=30.0,
    )


def _validate_probe_response(
    value: object,
    nonce: str,
    spec: SandboxSpec,
    probe_dir: Path,
    identity: OciIdentity,
    storage_policy: StoragePolicy = STORAGE_POLICIES["ordinary"],
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
        "storage",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise SandboxDeniedError("OCI probe response schema mismatch")
    if (
        value["nonce"] != nonce
        or value["kind"] != "hephaestus_executor_probe"
        or type(value["protocol_version"]) is not int
        or value["protocol_version"] != PROTOCOL_VERSION
        or type(value["oci_profile_version"]) is not int
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
        limits_ok = (
            isinstance(core, list)
            and len(core) == 2
            and all(type(item) is int and item == 0 for item in core)
        )
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
        proof_ok = value["work_proof"] == nonce
        features["work_writable"] = (
            value["cwd"] == "/work" and _mount_has(work, "/work", "rw") and proof_ok
        )
        features["tmpfs_profile"] = (
            _mount_has(tmp, "/tmp", "rw", fs_type="tmpfs")
            and all(_mount_option(tmp, option) for option in ("nosuid", "nodev", "noexec"))
            and type(value["tmp_capacity_bytes"]) is int
            and value["tmp_capacity_bytes"] == storage_policy.tmp_bytes
            and type(value["tmp_write_errno"]) is int
            and value["tmp_write_errno"] == 0
        )

    features["storage_quotas"] = storage_valid(value["storage"], storage_policy)
    features["network_isolated"] = network_isolated(value["network"])

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
