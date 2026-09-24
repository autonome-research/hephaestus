"""Daemon-free tests for conservative OCI host mechanics."""

from __future__ import annotations

import copy
import errno
import json
import math
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

import pytest
from hephaestus.core.errors import SandboxDeniedError
from hephaestus.core.executor.sandbox import oci as oci_module
from hephaestus.core.executor.sandbox.base import CapabilityReport, Rlimits, SandboxSpec
from hephaestus.core.executor.sandbox.oci import (
    AUDITED_ENTRYPOINT,
    AUDITED_IMAGE_ENV,
    OciBackend,
    OciIdentity,
    OciRuntime,
    SubprocessTransport,
    TransportOutputLimit,
    TransportResult,
    TransportTimeout,
    build_create_argv,
    build_inspect_argv,
    build_kill_argv,
    build_remove_argv,
    build_start_argv,
    parse_immutable_image_ref,
    platform_for_machine,
)
from hephaestus.core.executor.sandbox.oci_protocol import (
    BUILD_WORKER,
    OCI_HOSTNAME,
    OCI_PROFILE_VERSION,
    OCI_TMPFS_BYTES,
    PROTOCOL_VERSION,
    REQUIRED_OCI_FEATURES,
)

DIGEST = "a" * 64
IMAGE = f"registry.example/hephaestus/executor@sha256:{DIGEST}"
CONTAINER_ID = "b" * 64
NAME = "heph-exec-" + "c" * 64
IDENTITY = OciIdentity(uid=501, gid=20)


class FakeTransport:
    def __init__(self, results: Sequence[TransportResult | Exception] = ()) -> None:
        self.results = list(results)
        self.calls: list[tuple[tuple[str, ...], bytes, Mapping[str, str], float]] = []

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
        del stdout_limit, stderr_limit
        self.calls.append((tuple(argv), input, dict(env), timeout))
        if not self.results:
            raise AssertionError("unexpected transport invocation")
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def runtime(kind: Literal["docker", "podman"] = "docker") -> OciRuntime:
    if kind == "docker":
        return OciRuntime("docker", Path("/usr/bin/docker"))
    return OciRuntime("podman", Path("/opt/homebrew/bin/podman"))


def spec(out: Path, **changes: object) -> SandboxSpec:
    values: dict[str, object] = {
        "worker_args": ("-m", BUILD_WORKER),
        "ro_binds": (),
        "rw_out_dir": out,
        "rlimits": Rlimits(17, 123456789, 31),
        "wall_clock_s": 20.0,
    }
    values.update(changes)
    return SandboxSpec(**values)  # type: ignore[arg-type]


def passing(backend: OciBackend) -> None:
    backend._passing_report = CapabilityReport(
        backend=backend.name,
        available=True,
        features={name: True for name in REQUIRED_OCI_FEATURES},
    )


def test_exact_docker_create_argv(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    actual = build_create_argv(runtime(), IMAGE, "linux/amd64", spec(out), NAME, identity=IDENTITY)
    assert actual == (
        "/usr/bin/docker",
        "create",
        "--interactive",
        "--name",
        NAME,
        "--pull=never",
        "--platform",
        "linux/amd64",
        "--user",
        "501:20",
        "--read-only",
        "--network",
        "none",
        "--ipc",
        "none",
        "--hostname",
        "hephaestus-executor",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges=true",
        "--memory",
        "123456789",
        "--memory-swap",
        "123456789",
        "--pids-limit",
        "31",
        "--cpus",
        "1.0",
        "--tmpfs",
        f"/tmp:rw,nosuid,nodev,noexec,size={OCI_TMPFS_BYTES},mode=1777",
        "--mount",
        f"type=bind,source={out},destination=/work,bind-propagation=rprivate",
        "--workdir",
        "/work",
        IMAGE,
        "run",
        "2",
        BUILD_WORKER,
        "17",
        "123456789",
        "31",
    )
    assert actual.count("--mount") == 1
    assert not any(item in actual for item in ("--tty", "-t", "--env", "--env-file"))


def test_podman_nnp_and_lifecycle_argv(tmp_path: Path) -> None:
    podman = runtime("podman")
    out = tmp_path / "out"
    out.mkdir()
    create = build_create_argv(podman, IMAGE, "linux/arm64", spec(out), NAME, identity=IDENTITY)
    assert create[0] == "/opt/homebrew/bin/podman"
    assert create[create.index("--security-opt") + 1] == "no-new-privileges"
    assert build_start_argv(podman, CONTAINER_ID) == (
        "/opt/homebrew/bin/podman",
        "start",
        "--attach",
        "--interactive",
        CONTAINER_ID,
    )
    assert build_inspect_argv(podman, CONTAINER_ID)[-3:] == (
        "--format",
        "{{json .State}}",
        CONTAINER_ID,
    )
    assert build_kill_argv(podman, CONTAINER_ID)[-3:] == (
        "--signal",
        "KILL",
        CONTAINER_ID,
    )
    assert build_remove_argv(podman, CONTAINER_ID)[-2:] == ("--force", CONTAINER_ID)


@pytest.mark.parametrize(
    "bad",
    [
        "executor:latest",
        "registry.example/executor:tag@sha256:" + DIGEST,
        "executor@sha256:" + DIGEST,
        "namespace/executor@sha256:" + DIGEST,
        "registry.example/executor@sha256:" + "A" * 64,
        "registry.example/executor@sha256:" + "a" * 63,
        "registry.example/executor@sha512:" + DIGEST,
    ],
)
def test_image_parser_rejects_mutable_or_malformed_references(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_immutable_image_ref(bad)


def test_image_parser_accepts_only_explicit_registries() -> None:
    for image in (
        IMAGE,
        f"localhost/executor@sha256:{DIGEST}",
        f"registry:5000/team/executor@sha256:{DIGEST}",
    ):
        assert str(parse_immutable_image_ref(image)) == image


def test_runtime_configuration_is_immutable_and_pins_the_endpoint() -> None:
    selector = ["--context", "desktop-linux"]
    selected = OciRuntime(
        "docker",
        Path("/usr/bin/docker"),
        selector=selector,  # type: ignore[arg-type]
        endpoint="unix:///Users/test/.docker/run/docker.sock",
        server_identity="Docker Desktop",
    )
    selector[1] = "attacker-controlled"
    assert selected.selector == ("--context", "desktop-linux")
    assert selected.prefix == (
        "/usr/bin/docker",
        "--host",
        "unix:///Users/test/.docker/run/docker.sock",
    )


def test_architecture_mapping_is_closed() -> None:
    assert platform_for_machine("x86_64") == "linux/amd64"
    assert platform_for_machine("aarch64") == "linux/arm64"
    with pytest.raises(ValueError):
        platform_for_machine("riscv64")


@pytest.mark.parametrize(
    "changes",
    [
        {"ro_binds": (Path("/project"),)},
        {"worker_args": ("-m", "not.allowed")},
        {"worker_args": ("-m", BUILD_WORKER, "extra")},
        {"rlimits": Rlimits(True, 100, 10)},
        {"rlimits": Rlimits(121, 100, 10)},
        {"wall_clock_s": math.nan},
        {"wall_clock_s": math.inf},
    ],
)
def test_preflight_refuses_before_transport(tmp_path: Path, changes: dict[str, object]) -> None:
    out = tmp_path / "out"
    out.mkdir()
    transport = FakeTransport()
    backend = OciBackend(runtime(), IMAGE, "linux/amd64", transport=transport)
    with pytest.raises(ValueError):
        backend.execute(spec(out, **changes), b"payload")
    assert transport.calls == []


def test_output_directory_preflight(tmp_path: Path) -> None:
    backend = OciBackend(runtime(), IMAGE, "linux/amd64", transport=FakeTransport())
    missing = tmp_path / "missing"
    with pytest.raises(ValueError):
        backend.execute(spec(missing), b"")
    file = tmp_path / "file"
    file.write_text("x")
    with pytest.raises(ValueError):
        backend.execute(spec(file), b"")
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(ValueError):
        backend.execute(spec(link), b"")
    comma = tmp_path / "bad,dir"
    comma.mkdir()
    with pytest.raises(ValueError):
        backend.execute(spec(comma), b"")


def test_direct_execution_without_instance_probe_fails_closed(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    transport = FakeTransport()
    backend = OciBackend(runtime(), IMAGE, "linux/amd64", transport=transport)
    with pytest.raises(SandboxDeniedError):
        backend.execute(spec(out), b"payload")
    assert transport.calls == []


def test_normal_lifecycle_uses_inspected_status_and_sanitized_env(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    transport = FakeTransport(
        [
            TransportResult(0, (CONTAINER_ID + "\n").encode(), b""),
            TransportResult(99, b"worker-output", b"worker-error"),
            TransportResult(0, b'{"Running":false,"ExitCode":7}\n', b""),
            TransportResult(0, b"", b""),
            TransportResult(1, b"", b"Error: no such container\n"),
        ]
    )
    backend = OciBackend(runtime(), IMAGE, "linux/amd64", transport=transport)
    passing(backend)
    outcome = backend.execute(spec(out), b"exact-input")
    assert outcome.exit_code == 7
    assert outcome.stdout == b"worker-output"
    assert outcome.stderr == b"worker-error"
    assert transport.calls[1][1] == b"exact-input"
    assert transport.calls[1][2] == {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"}
    assert transport.calls[1][0][-4:-1] == ("start", "--attach", "--interactive")


def test_timeout_kills_confirms_and_removes(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    transport = FakeTransport(
        [
            TransportResult(0, (CONTAINER_ID + "\n").encode(), b""),
            TransportTimeout(),
            TransportResult(0, b'{"Running":true,"ExitCode":0}\n', b""),
            TransportResult(0, b"", b""),
            TransportResult(0, b'{"Running":false,"ExitCode":137}\n', b""),
            TransportResult(0, b"", b""),
            TransportResult(1, b"", b"no such container"),
        ]
    )
    backend = OciBackend(runtime(), IMAGE, "linux/amd64", transport=transport)
    passing(backend)
    outcome = backend.execute(spec(out), b"")
    assert outcome.timed_out
    assert any("kill" in call[0] for call in transport.calls)
    assert any("rm" in call[0] for call in transport.calls)


def test_cleanup_force_removes_after_failed_asynchronous_kill(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    running = TransportResult(0, b'{"Running":true,"ExitCode":0}\n', b"")
    transport = FakeTransport(
        [
            TransportResult(0, (CONTAINER_ID + "\n").encode(), b""),
            TransportTimeout(),
            running,
            TransportResult(1, b"", b"kill failed"),
            running,
            running,
            TransportResult(0, b'{"Running":false,"ExitCode":137}\n', b""),
            TransportResult(0, b"", b""),
            TransportResult(1, b"", b"no such container"),
        ]
    )
    backend = OciBackend(runtime(), IMAGE, "linux/amd64", identity=IDENTITY, transport=transport)
    passing(backend)
    outcome = backend.execute(spec(out), b"")
    assert outcome.timed_out
    assert any("rm" in call[0] for call in transport.calls)
    assert transport.results == []


def test_post_attach_inspection_respects_the_worker_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "out"
    out.mkdir()
    transport = FakeTransport(
        [
            TransportResult(0, (CONTAINER_ID + "\n").encode(), b""),
            TransportResult(0, b"worker", b""),
            TransportResult(0, b'{"Running":false,"ExitCode":0}\n', b""),
            TransportResult(0, b"", b""),
            TransportResult(1, b"", b"no such container"),
        ]
    )
    ticks = iter((0.0, 0.0, 0.0, 21.0))
    monkeypatch.setattr(oci_module.time, "monotonic", lambda: next(ticks))
    backend = OciBackend(runtime(), IMAGE, "linux/amd64", identity=IDENTITY, transport=transport)
    passing(backend)
    outcome = backend.execute(spec(out), b"")
    assert outcome.timed_out
    # No ordinary post-attach inspect used a fresh five-second allowance. The
    # first inspect is cleanup after the deadline has already expired.
    assert transport.calls[2][3] == 5.0


def test_output_limit_is_bounded_failure_after_cleanup(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    transport = FakeTransport(
        [
            TransportResult(0, (CONTAINER_ID + "\n").encode(), b""),
            TransportOutputLimit("stdout"),
            TransportResult(0, b'{"Running":true,"ExitCode":0}\n', b""),
            TransportResult(0, b"", b""),
            TransportResult(0, b'{"Running":false,"ExitCode":137}\n', b""),
            TransportResult(0, b"", b""),
            TransportResult(1, b"", b"no such object"),
        ]
    )
    backend = OciBackend(runtime(), IMAGE, "linux/amd64", transport=transport)
    passing(backend)
    outcome = backend.execute(spec(out), b"")
    assert outcome.exit_code == 125
    assert not outcome.timed_out
    assert outcome.stdout == b""
    assert outcome.stderr == b"OCI worker output limit exceeded\n"


def test_subprocess_transport_drains_both_streams_and_handles_early_stdin_close() -> None:
    transport = SubprocessTransport()
    result = transport.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.stdout.buffer.write(b'o'*4096); sys.stderr.buffer.write(b'e'*4096)",
        ],
        input=b"unused" * 100_000,
        timeout=5.0,
        stdout_limit=4096,
        stderr_limit=4096,
        env={},
    )
    assert result.returncode == 0
    assert result.stdout == b"o" * 4096
    assert result.stderr == b"e" * 4096


def test_subprocess_transport_enforces_output_and_time_bounds() -> None:
    transport = SubprocessTransport()
    with pytest.raises(TransportOutputLimit):
        transport.run(
            [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'x'*65)"],
            input=b"",
            timeout=5.0,
            stdout_limit=64,
            stderr_limit=64,
            env={},
        )
    with pytest.raises(TransportTimeout):
        transport.run(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            input=b"",
            timeout=0.05,
            stdout_limit=64,
            stderr_limit=64,
            env={},
        )


def test_only_passing_probe_is_cached_on_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = OciBackend(runtime(), IMAGE, "linux/amd64", transport=FakeTransport())
    calls = 0

    def validate() -> None:
        nonlocal calls
        calls += 1

    monkeypatch.setattr(backend, "_validate_runtime", validate)
    monkeypatch.setattr(backend, "_validate_image", validate)
    monkeypatch.setattr(
        backend,
        "_live_probe",
        lambda: {name: True for name in REQUIRED_OCI_FEATURES},
    )
    first = backend.probe()
    second = backend.probe()
    assert first.available and second is first
    assert calls == 2


def test_numeric_identity_must_be_non_root() -> None:
    with pytest.raises(ValueError):
        OciIdentity(uid=0, gid=20)
    with pytest.raises(ValueError):
        OciIdentity(uid=501, gid=0)


def test_invalid_create_id_is_cleaned_up_by_name(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    transport = FakeTransport(
        [
            TransportResult(0, b"not-a-container-id\n", b""),
            TransportResult(0, b'{"Running":true,"ExitCode":0}\n', b""),
            TransportResult(0, b"", b""),
            TransportResult(0, b'{"Running":false,"ExitCode":137}\n', b""),
            TransportResult(0, b"", b""),
            TransportResult(1, b"", b"no such container"),
        ]
    )
    backend = OciBackend(runtime(), IMAGE, "linux/amd64", identity=IDENTITY, transport=transport)
    passing(backend)
    with pytest.raises(SandboxDeniedError):
        backend.execute(spec(out), b"")
    cleanup_identity = transport.calls[1][0][-1]
    assert cleanup_identity.startswith("heph-exec-")
    assert "kill" in transport.calls[2][0]
    assert transport.calls[-1][0][-1] == cleanup_identity


def test_malformed_post_start_inspection_still_cleans_up(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    transport = FakeTransport(
        [
            TransportResult(0, (CONTAINER_ID + "\n").encode(), b""),
            TransportResult(0, b"worker", b""),
            TransportResult(0, b"{}\n", b""),
            TransportResult(0, b'{"Running":true,"ExitCode":0}\n', b""),
            TransportResult(0, b"", b""),
            TransportResult(0, b'{"Running":false,"ExitCode":137}\n', b""),
            TransportResult(0, b"", b""),
            TransportResult(1, b"", b"no such object"),
        ]
    )
    backend = OciBackend(runtime(), IMAGE, "linux/amd64", identity=IDENTITY, transport=transport)
    passing(backend)
    with pytest.raises(SandboxDeniedError):
        backend.execute(spec(out), b"")
    assert any("kill" in call[0] for call in transport.calls)
    assert any("rm" in call[0] for call in transport.calls)


def _valid_probe_response(nonce: str) -> dict[str, object]:
    return {
        "capabilities": {
            "CapInh": "0000000000000000",
            "CapPrm": "0000000000000000",
            "CapEff": "0000000000000000",
            "CapBnd": "0000000000000000",
            "CapAmb": "0000000000000000",
        },
        "cgroup": {
            "version": 2,
            "memory_max": 123456789,
            "memory_swap_max": 0,
            "memory_swap_mode": "additional",
            "pids_max": 31,
            "cpu_quota": {"quota": 100000, "period": 100000},
        },
        "cwd": "/work",
        "effective_gid": IDENTITY.gid,
        "effective_uid": IDENTITY.uid,
        "hostname": OCI_HOSTNAME,
        "kind": "hephaestus_executor_probe",
        "mounts": {
            "/": {"mountpoint": "/", "fs_type": "overlay", "options": ["ro"]},
            "/work": {"mountpoint": "/work", "fs_type": "virtiofs", "options": ["rw"]},
            "/tmp": {
                "mountpoint": "/tmp",
                "fs_type": "tmpfs",
                "options": ["rw", "nosuid", "nodev", "noexec"],
            },
        },
        "network": {
            "interfaces": ["lo"],
            "routes": [],
            "connect_errno": errno.ENETUNREACH,
        },
        "nonce": nonce,
        "no_new_privs": 1,
        "oci_profile_version": OCI_PROFILE_VERSION,
        "pid": 1,
        "protocol_version": PROTOCOL_VERSION,
        "rlimits": {
            "RLIMIT_AS": [123456789, 123456789],
            "RLIMIT_CORE": [0, 0],
            "RLIMIT_CPU": [17, 17],
            "RLIMIT_DATA": [123456789, 123456789],
            "RLIMIT_NPROC": [31, 31],
        },
        "root_write_errno": errno.EACCES,
        "tmp_capacity_bytes": OCI_TMPFS_BYTES,
        "tmp_write_errno": 0,
        "work_proof": f".heph-oci-probe-{nonce}",
    }


def test_probe_response_requires_every_raw_containment_observation(tmp_path: Path) -> None:
    nonce = "d" * 64
    out = tmp_path / "out"
    out.mkdir()
    (out / f".heph-oci-probe-{nonce}").write_text(nonce, encoding="ascii")
    request_spec = spec(out)
    response = _valid_probe_response(nonce)
    features = oci_module._validate_probe_response(response, nonce, request_spec, out, IDENTITY)
    assert set(features) == set(REQUIRED_OCI_FEATURES)
    assert all(features.values())

    for mutate in (
        lambda value: value.__setitem__("effective_uid", 0),
        lambda value: value.__setitem__("effective_uid", True),
        lambda value: value.__setitem__("no_new_privs", True),
        lambda value: value.__setitem__("pid", 2),
        lambda value: value.__setitem__("hostname", "shared-host"),
        lambda value: value.__setitem__("tmp_write_errno", False),
        lambda value: value["capabilities"].__setitem__("CapEff", "0000000000000001"),
        lambda value: value["network"].__setitem__("interfaces", ["eth0", "lo"]),
        lambda value: value["network"].__setitem__("connect_errno", []),
        lambda value: value["cgroup"].__setitem__("version", []),
        lambda value: value["cgroup"].__setitem__("memory_max", 123456790),
        lambda value: value["mounts"]["/tmp"].__setitem__("fs_type", "overlay"),
    ):
        invalid = copy.deepcopy(response)
        mutate(invalid)
        with pytest.raises(SandboxDeniedError):
            oci_module._validate_probe_response(invalid, nonce, request_spec, out, IDENTITY)

    (out / f".heph-oci-probe-{nonce}").write_bytes(b"\xff")
    with pytest.raises(SandboxDeniedError):
        oci_module._validate_probe_response(response, nonce, request_spec, out, IDENTITY)


def test_runtime_and_image_metadata_are_strict() -> None:
    selected = OciRuntime(
        "docker",
        Path("/usr/bin/docker"),
        selector=("--context", "desktop-linux"),
        endpoint="unix:///Users/test/.docker/run/docker.sock",
        server_identity="Docker Desktop",
    )
    context = {
        "Endpoints": {"docker": {"Host": selected.endpoint}},
    }
    info = {
        "OSType": "linux",
        "Architecture": "amd64",
        "OperatingSystem": "Docker Desktop",
    }
    image = {
        "Architecture": "amd64",
        "Config": {
            "Cmd": [],
            "Entrypoint": list(AUDITED_ENTRYPOINT),
            "Env": list(AUDITED_IMAGE_ENV),
            "Volumes": None,
        },
        "Id": "sha256:" + "e" * 64,
        "Os": "linux",
        "RepoDigests": [IMAGE],
    }
    transport = FakeTransport(
        [
            TransportResult(0, (json.dumps(context) + "\n").encode(), b""),
            TransportResult(0, (json.dumps(info) + "\n").encode(), b""),
            TransportResult(0, (json.dumps(image) + "\n").encode(), b""),
        ]
    )
    backend = OciBackend(selected, IMAGE, "linux/amd64", identity=IDENTITY, transport=transport)
    backend._validate_runtime()
    backend._validate_image()

    image["RepoDigests"] = []
    bad = OciBackend(
        selected,
        IMAGE,
        "linux/amd64",
        identity=IDENTITY,
        transport=FakeTransport([TransportResult(0, (json.dumps(image) + "\n").encode(), b"")]),
    )
    with pytest.raises(SandboxDeniedError):
        bad._validate_image()


def test_probe_converts_malformed_external_types_to_unavailable_report() -> None:
    selected = OciRuntime(
        "docker",
        Path("/usr/bin/docker"),
        selector=("--context", "desktop-linux"),
        endpoint="unix:///Users/test/.docker/run/docker.sock",
        server_identity="Docker Desktop",
    )
    context = {"Endpoints": {"docker": {"Host": selected.endpoint}}}
    malformed_info = {
        "OSType": "linux",
        "Architecture": [],
        "OperatingSystem": "Docker Desktop",
    }
    backend = OciBackend(
        selected,
        IMAGE,
        "linux/amd64",
        identity=IDENTITY,
        transport=FakeTransport(
            [
                TransportResult(0, (json.dumps(context) + "\n").encode(), b""),
                TransportResult(0, (json.dumps(malformed_info) + "\n").encode(), b""),
            ]
        ),
    )
    report = backend.probe()
    assert not report.available
    assert report.reason is not None and "unavailable" in report.reason
