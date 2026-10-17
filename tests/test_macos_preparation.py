# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Actual preparation command paths with a synthetic daemon; never live CAD evidence."""

from __future__ import annotations

import hashlib
import importlib
import io
import json
import os
import struct
import sys
from pathlib import Path

import pytest
from hephaestus.core.executor.cancellation import Cancellation, ExecutionCancelled
from hephaestus.core.executor.sandbox import oci_transfer as wire
from hephaestus.core.executor.sandbox.oci import (
    RUNTIME_ENV,
    SubprocessTransport,
    TransportResult,
    TransportTimeout,
)
from hephaestus.core.executor.sandbox.oci_protocol import APPROVED_MODULES
from hephaestus.core.executor.sandbox.oci_storage_policy import DEFAULT_STORAGE

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
prep = importlib.import_module("macos_preparation")
transfer = importlib.import_module("macos_preparation_transfer")
worker = importlib.import_module("macos_preparation_worker")
smoke_module = importlib.import_module("macos_milestone_smoke")

PAYLOAD = b"harmless synthetic wheel bytes; not an installable wheel"
DIGEST = hashlib.sha256(PAYLOAD).hexdigest()
PACKAGES = {"example": {"version": "1.0", "hashes": [DIGEST]}}
LEAF = "example-1.0-py3-none-any.whl"
NONCE = "a" * 64
CID = "b" * 64


def schema(route="download"):
    return transfer.PreparationSchema(route, PACKAGES)


def frame(directory, nonce=NONCE, route="download", packages=PACKAGES):
    directory.mkdir()
    for name, item in packages.items():
        (directory / f"{name}-{item['version']}-py3-none-any.whl").write_bytes(PAYLOAD)
    s = transfer.PreparationSchema(route, packages)
    records = transfer.records(directory, s)
    result = {"files": {k: v.sha256 for k, v in records.items()}}
    stream = io.BytesIO()
    wire._export(stream, result, nonce, "preparation-v1/" + route, directory, transfer.BOUNDS, s)
    return stream.getvalue()


def rewrite_header(data, mutate):
    start = len(wire.MAGIC) + 4
    length = struct.unpack("!I", data[start - 4 : start])[0]
    header = json.loads(data[start : start + length])
    mutate(header)
    encoded = wire.encode(header, 65536)
    body = wire.MAGIC + struct.pack("!I", len(encoded)) + encoded + data[start + length : -40]
    return body + wire.FOOTER + hashlib.sha256(body).digest()


@pytest.mark.parametrize(
    "mutation",
    [
        "valid",
        "empty",
        "truncated",
        "trailing",
        "footer",
        "body",
        "nonce",
        "operation",
        "duplicate",
        "oversized",
        "count",
        "escape",
        "unknown",
        "header",
        "wrong-lock-hash",
        "missing",
    ],
)
def test_preparation_frame_refusals_and_exclusive_publication(tmp_path, mutation):
    data = frame(tmp_path / "source")
    s = schema()
    if mutation == "empty":
        data = b""
    elif mutation == "truncated":
        data = data[:-1]
    elif mutation == "trailing":
        data += b"x"
    elif mutation in {"footer", "body"}:
        at = -1 if mutation == "footer" else -41
        data = data[:at] + bytes([data[at] ^ 1]) + (data[at + 1 :] if at != -1 else b"")
    elif mutation == "nonce":
        data = rewrite_header(data, lambda h: h.update(nonce="c" * 64))
    elif mutation == "operation":
        data = rewrite_header(data, lambda h: h.update(operation="arbitrary.worker"))
    elif mutation == "duplicate":
        data = rewrite_header(data, lambda h: h["artifacts"].append(h["artifacts"][0]))
    elif mutation == "oversized":
        data = rewrite_header(
            data, lambda h: h["artifacts"][0].update(length=transfer.FILE_BYTES + 1)
        )
    elif mutation == "count":
        data = rewrite_header(data, lambda h: h.update(artifacts=h["artifacts"] * 129))
    elif mutation in {"escape", "unknown"}:
        data = rewrite_header(
            data,
            lambda h: h["artifacts"][0].update(
                id="../" + LEAF if mutation == "escape" else "other-1.0-py3-none-any.whl"
            ),
        )
    elif mutation == "header":
        data = wire.MAGIC + struct.pack("!I", 65537)
    elif mutation == "wrong-lock-hash":
        s = transfer.PreparationSchema(
            "download", {"example": {"version": "1.0", "hashes": ["0" * 64]}}
        )
    elif mutation == "missing":
        s = transfer.PreparationSchema("download", {**PACKAGES, "other": PACKAGES["example"]})
    collected, destination = tmp_path / "collected", tmp_path / "published"
    collected.mkdir()
    destination.mkdir()
    with wire._Receiver(
        collected, NONCE, "preparation-v1/download", transfer.BOUNDS, s
    ) as receiver:

        def receive():
            for i in range(0, len(data), 7):
                receiver.feed(data[i : i + 7])
            receiver.finish()
            receiver.install(destination)

        if mutation == "valid":
            receive()
        else:
            with pytest.raises(ValueError):
                receive()
    assert list(collected.iterdir()) == []
    assert list(destination.iterdir()) == ([destination / LEAF] if mutation == "valid" else [])


@pytest.mark.parametrize("mutation", ["symlink", "hardlink", "fifo", "oversized", "extra"])
def test_exporter_refuses_nonregular_unbounded_or_extra_files(tmp_path, mutation):
    leaf = tmp_path / LEAF
    leaf.write_bytes(PAYLOAD)
    if mutation in {"symlink", "hardlink"}:
        other = tmp_path / "other"
        leaf.rename(other)
        leaf.symlink_to(other) if mutation == "symlink" else os.link(other, leaf)
    elif mutation == "fifo":
        leaf.unlink()
        os.mkfifo(leaf)
    elif mutation == "oversized":
        with leaf.open("wb") as stream:
            stream.truncate(transfer.FILE_BYTES + 1)
    else:
        (tmp_path / "unexpected.txt").write_bytes(PAYLOAD)
    with pytest.raises((OSError, ValueError)):
        transfer.records(tmp_path, schema())


@pytest.mark.parametrize(
    "mutation", ["valid", "symlink", "parent-link", "hardlink", "fifo", "bytes", "count", "stale"]
)
def test_snapshot_prewrite_admission(tmp_path, monkeypatch, mutation):
    source = tmp_path / "source"
    source.mkdir()
    leaf = source / "input"
    leaf.write_bytes(PAYLOAD)
    (source / "py.typed").touch()
    destination = tmp_path / "snapshot"
    if mutation == "symlink":
        leaf.unlink()
        leaf.symlink_to(tmp_path / "absent")
    elif mutation == "parent-link":
        link = tmp_path / "alias"
        link.symlink_to(source, target_is_directory=True)
        source = link
    elif mutation == "hardlink":
        os.link(leaf, source / "alias")
    elif mutation == "fifo":
        leaf.unlink()
        os.mkfifo(leaf)
    elif mutation == "bytes":
        monkeypatch.setattr(transfer, "INPUT_BYTES", len(PAYLOAD) - 1)
    elif mutation == "count":
        monkeypatch.setattr(transfer, "INPUT_FILES", 1)
    elif mutation == "stale":
        destination.mkdir()
        (destination / "old").write_bytes(b"unchanged")
    if mutation == "valid":
        manifest = transfer.snapshot({"source": source}, destination)
        assert manifest["source/input"].sha256 == DIGEST
        assert (destination / "source/py.typed").read_bytes() == b""
        assert (destination / "source/input").stat().st_mode & 0o222 == 0
    else:
        with pytest.raises((ValueError, OSError)):
            transfer.snapshot({"source": source}, destination)
        assert not destination.exists() or mutation == "stale"


class Daemon:
    def __init__(self, directory, failure="none"):
        self.directory, self.failure = directory, failure
        self.calls = []
        self.create = None

    def run(self, argv, **kwargs):
        self.calls.append((tuple(argv), kwargs))
        if "pull" in argv:
            return TransportResult(0, b"", b"")
        if "image" in argv and "inspect" in argv:
            return TransportResult(0, b'[{"Architecture":"arm64","Os":"linux","Id":"base"}]', b"")
        if "create" in argv:
            self.create = argv
            if self.failure == "create":
                raise TransportTimeout()
            return TransportResult(0, (CID + "\n").encode(), b"")
        if "start" in argv:
            assert argv[-1] == CID
            assert self.create is not None
            if self.failure == "timeout":
                raise TransportTimeout()
            if self.failure == "interrupt":
                raise KeyboardInterrupt()
            if self.failure == "cancel":
                raise ExecutionCancelled("preparation-test")
            route, nonce = self.create[-2:]
            mount = self.create[self.create.index("--mount") + 1]
            inputs = Path(mount.split("source=", 1)[1].split(",", 1)[0])
            packages = json.loads((inputs / "packages.json").read_text())
            data = frame(self.directory / "daemon-output", nonce, route, packages)
            if self.failure == "truncated":
                data = data[:-1]
            if self.failure == "body-hash":
                # Valid frame digest, wrong body versus declared/lock hash.
                data = data.replace(PAYLOAD, b"x" * len(PAYLOAD))
                data = data[:-40] + wire.FOOTER + hashlib.sha256(data[:-40]).digest()
            kwargs["stdout_consumer"](data)
            return TransportResult(1 if self.failure == "attach" else 0, b"", b"bounded stderr")
        if "inspect" in argv:
            state = {"Running": False, "OOMKilled": self.failure == "oom", "ExitCode": 0}
            return TransportResult(0, json.dumps(state).encode(), b"")
        if "rm" in argv:
            return TransportResult(0, b"", b"")
        if "ps" in argv:
            return TransportResult(0, CID.encode() if self.failure == "cleanup" else b"", b"")
        raise AssertionError(argv)


@pytest.mark.parametrize("route", ["download", "download-cache", "executor", "renderer"])
def test_actual_helpers_all_use_private_export(tmp_path, monkeypatch, route):
    smoke = smoke_module.Smoke(tmp_path)
    smoke.docker = ("docker", "--host", "unix:///synthetic")
    daemon = Daemon(tmp_path)
    smoke.transport = daemon
    monkeypatch.setattr(prep, "locked_packages", lambda _: PACKAGES)
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / LEAF).write_bytes(PAYLOAD)
    if route in {"download", "download-cache"}:
        smoke.wheelhouse = cache if route.endswith("cache") else None
        smoke.native_dependencies()
        assert (tmp_path / "download/wheels" / LEAF).read_bytes() == PAYLOAD
    else:
        (tmp_path / "download").mkdir()
        cache.rename(tmp_path / "download/wheels")
        module = importlib.import_module("macos_prepare_" + route)

        class ReachedImageBuild(Exception):
            pass

        # Stop only AFTER the real helper's preparation/export path completes.
        def stop(*args, **kwargs):
            raise ReachedImageBuild()

        monkeypatch.setattr(module.shutil, "copytree", stop)
        with pytest.raises(ReachedImageBuild):
            module.prepare(smoke)
        local = tmp_path / "download/local-wheels"
        assert len(list(local.glob("*.whl"))) == 2
        assert f"--hash=sha256:{DIGEST}" in (local / "local-requirements.lock").read_text()
    argv = daemon.create
    assert argv is not None
    mounts = [argv[i + 1] for i, v in enumerate(argv) if v == "--mount"]
    assert len(mounts) == 1
    assert mounts[0].endswith(",destination=/inputs,readonly,bind-recursive=disabled")
    assert "/prepare-" in mounts[0] and "source=" + str(ROOT) + "," not in mounts[0]
    tmpfs = [argv[i + 1] for i, v in enumerate(argv) if v == "--tmpfs"]
    assert len(tmpfs) == 3
    assert all("size=" in m and "nr_inodes=" in m and "nosuid,nodev,noexec" in m for m in tmpfs)
    for flag in (
        "--read-only",
        "--pull=never",
        "--cap-drop",
        "--security-opt",
        "--memory",
        "--memory-swap",
        "--pids-limit",
        "--cpus",
    ):
        assert flag in argv
    for flag, value in {
        "--network": "bridge" if route == "download" else "none",
        "--platform": "linux/arm64",
        "--cap-drop": "ALL",
        "--security-opt": "no-new-privileges=true",
        "--ipc": "none",
        "--memory": "1536m",
        "--memory-swap": "1536m",
        "--pids-limit": "128",
        "--cpus": "1",
        "--shm-size": "4k",
    }.items():
        assert argv[argv.index(flag) + 1] == value
    assert [argv[i + 1] for i, v in enumerate(argv) if v == "--ulimit"] == [
        "cpu=240:240" if route in {"download", "download-cache"} else "cpu=120:120",
        "fsize=268435456:268435456",
        "nofile=1024:1024",
    ]
    assert "size=1073741824,nr_inodes=16384,mode=0700" in tmpfs[0]
    assert "size=268435456,nr_inodes=4096" in tmpfs[1]
    assert tmpfs[2] == "/dev/mqueue:ro,nosuid,nodev,noexec,size=4096,nr_inodes=1,mode=0000"
    assert argv[-6:-2] == (
        smoke_module.BASE,
        "/usr/local/bin/python",
        "-I",
        "/inputs/code/macos_preparation_worker.py",
    )
    calls = [a for a, _ in daemon.calls]
    assert ("docker", "--host", "unix:///synthetic", "rm", "--force", CID) in calls
    assert all("cp" not in a and "--entrypoint" not in a for a in calls)
    assert next(iter(smoke.report["build_ownership"].values()))["absent"] is True
    assert smoke.cleanup_deadline is None  # local cleanup did not consume final cleanup budget
    print(
        json.dumps(
            {
                "synthetic_daemon": True,
                "actual_helper": route,
                "commands": [record["argv"] for record in smoke.report["commands"]],
                "worker_commands": worker.recipe(argv[-2]),
            },
            indent=2,
        )
    )


@pytest.mark.parametrize(
    "failure",
    [
        "create",
        "timeout",
        "interrupt",
        "cancel",
        "truncated",
        "body-hash",
        "attach",
        "oom",
        "cleanup",
        "stale",
        "parent-link",
    ],
)
@pytest.mark.parametrize("route", ["download", "download-cache", "package"])
def test_failure_or_interruption_cleans_owned_resource_and_never_publishes(
    tmp_path, monkeypatch, failure, route
):
    smoke = smoke_module.Smoke(tmp_path)
    smoke.docker = ("docker",)
    daemon = Daemon(tmp_path, failure)
    smoke.transport = daemon
    monkeypatch.setattr(prep, "locked_packages", lambda _: PACKAGES)
    destination = tmp_path / "published"
    if failure == "stale":
        destination.mkdir()
        (destination / LEAF).write_bytes(b"stale")
    if failure == "parent-link":
        outside = tmp_path / "outside"
        outside.mkdir()
        (tmp_path / "alias").symlink_to(outside, target_is_directory=True)
        destination = tmp_path / "alias/published"
    wheels = None
    if route != "download":
        wheels = tmp_path / "wheels"
        wheels.mkdir()
        (wheels / LEAF).write_bytes(PAYLOAD)
    with pytest.raises((Exception, KeyboardInterrupt)):
        prep.prepare_files(smoke, route, destination, wheels)
    assert any("rm" in argv for argv, _ in daemon.calls)
    target = next(a[-1] for a, _ in daemon.calls if "rm" in a)
    assert target == (smoke.owned[0] if failure == "create" else CID)
    assert not list((tmp_path / ("prepare-" + route) / "collected").iterdir())
    assert not destination.exists() or failure == "stale"
    if failure == "stale":
        assert (destination / LEAF).read_bytes() == b"stale"
    assert "preparation_exports" not in smoke.report
    assert smoke.cleanup_deadline is None


@pytest.mark.parametrize("route", ["download", "download-cache", "package"])
@pytest.mark.parametrize("expiry", ["none", "work", "cleanup"])
def test_preparation_expiry_preserves_separate_absolute_budgets(
    tmp_path, monkeypatch, expiry, route
):
    from hephaestus.core import deadline as clocks

    now = [0]
    monkeypatch.setattr(clocks, "continuous_ns", lambda: now[0])

    class AdvancingDaemon(Daemon):
        def run(self, argv, **kwargs):
            result = super().run(argv, **kwargs)
            if expiry == "work" and "start" in argv:
                now[0] += 2400_000_000_000  # complete frame cannot override work expiry
            if expiry == "cleanup" and "rm" in argv:
                now[0] += 30_000_000_000  # removal ACK cannot replenish cleanup
            return result

    smoke = smoke_module.Smoke(tmp_path)
    original_work = smoke.deadline
    smoke.docker = ("docker",)
    daemon = AdvancingDaemon(tmp_path)
    smoke.transport = daemon
    monkeypatch.setattr(prep, "locked_packages", lambda _: PACKAGES)
    destination = tmp_path / "published"
    wheels = None
    if route != "download":
        wheels = tmp_path / "wheels"
        wheels.mkdir()
        (wheels / LEAF).write_bytes(PAYLOAD)
    if expiry == "none":
        prep.prepare_files(smoke, route, destination, wheels)
        published = list(destination.glob("*.whl"))
        assert len(published) == (2 if route == "package" else 1)
        assert all(path.read_bytes() == PAYLOAD for path in published)
    else:
        with pytest.raises(TimeoutError, match="deadline expired"):
            prep.prepare_files(smoke, route, destination, wheels)
        assert not destination.exists()
        assert "preparation_exports" not in smoke.report
    calls = [argv for argv, _ in daemon.calls]
    assert ("docker", "rm", "--force", CID) in calls
    assert any("inspect" in argv for argv in calls) is (expiry != "work")
    assert any("ps" in argv for argv in calls) is (expiry != "cleanup")
    ownership = next(iter(smoke.report["build_ownership"].values()))
    assert ownership.get("absent", False) is (expiry != "cleanup")
    assert smoke.deadline is original_work and original_work.end_ns == 2400_000_000_000
    assert original_work.expired() is (expiry == "work")
    assert smoke.cleanup_deadline is None  # final 120-second allowance was not started
    assert not list((tmp_path / ("prepare-" + route) / "collected").iterdir())


def test_actual_attach_client_is_reaped_on_cancel_before_owned_container_cleanup(
    tmp_path, monkeypatch
):
    pidfile = tmp_path / "owned-child.pid"
    with Cancellation() as control:

        class ChildDaemon(Daemon):
            def run(self, argv, **kwargs):
                if "start" not in argv:
                    return super().run(argv, **kwargs)
                consumer = kwargs["stdout_consumer"]

                def consume(data):
                    consumer(data)
                    control.cancel("preparation-test")

                kwargs["stdout_consumer"] = consume
                script = (
                    "import os,sys,time; from pathlib import Path; "
                    f"Path({str(pidfile)!r}).write_text(str(os.getpid())); "
                    f"sys.stdout.buffer.write({wire.MAGIC!r}); sys.stdout.buffer.flush(); "
                    "time.sleep(30)"
                )
                return SubprocessTransport(cancellation=control).run(
                    (sys.executable, "-I", "-S", "-c", script, "start"), **kwargs
                )

        smoke = smoke_module.Smoke(tmp_path)
        smoke.docker = ("docker",)
        daemon = ChildDaemon(tmp_path)
        smoke.transport = daemon
        monkeypatch.setattr(prep, "locked_packages", lambda _: PACKAGES)
        with pytest.raises(ExecutionCancelled):
            prep.prepare_files(smoke, "download", tmp_path / "published")
        pid = int(pidfile.read_text())
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
        assert any(argv == ("docker", "rm", "--force", CID) for argv, _ in daemon.calls)
        assert not (tmp_path / "published").exists()
        assert not list((tmp_path / "prepare-download/collected").iterdir())


def test_fixed_recipes_and_production_boundaries():
    for route in ("download", "download-cache"):
        commands = worker.recipe(route)
        assert len(commands) == 1
        assert commands[0][:7] == (
            "/usr/local/bin/python",
            "-I",
            "-m",
            "pip",
            "--isolated",
            "--disable-pip-version-check",
            "download",
        )
        assert "--require-hashes" in commands[0] and "--only-binary=:all:" in commands[0]
        assert all("source" not in arg and "serve" not in arg for arg in commands[0])
    install, build = worker.recipe("package")[1:]
    assert "--no-index" in install and "--require-hashes" in install
    assert all(flag in build for flag in ("--no-index", "--no-deps", "--no-build-isolation"))
    with pytest.raises(ValueError):
        worker.recipe("arbitrary.module")
    assert not any("preparation" in m for m in APPROVED_MODULES | wire.OPERATIONS)
    assert DEFAULT_STORAGE.export_bytes == 72 * 1024**2
    with pytest.raises(ValueError):
        wire.Receiver(Path("/"), NONCE, "preparation-v1/download", DEFAULT_STORAGE)


def test_real_lock_policy_targets_linux_arm64_without_dependency_changes():
    packages = prep.locked_packages(ROOT / "docker/executor")
    assert "py_lib3mf" in packages and "lib3mf" not in packages and "colorama" not in packages
    assert "hatchling" in packages and "cadquery_ocp_novtk" in packages
    assert len(packages) <= transfer.FILE_COUNT
    transfer.PreparationSchema("download", packages)


@pytest.mark.parametrize(
    "requirement",
    [
        "example>=1.0",
        "example==1.*",
        "example[extra]==1.0",
        "example @ https://example.invalid/a.whl",
        "example==1.0 ; python_version >= '3.13'",
        "example==1.0 --index-url=https://other.invalid",
    ],
)
def test_unknown_lock_grammar_refuses_without_host_marker_fallback(tmp_path, requirement):
    (tmp_path / "requirements.lock").write_text(requirement + " --hash=sha256:" + DIGEST + "\n")
    (tmp_path / "build-requirements.lock").write_text("# empty fixture\n")
    with pytest.raises(ValueError, match="reviewed exact"):
        prep.locked_packages(tmp_path)


@pytest.mark.parametrize("kind", ["lock-bytes", "lock-count", "spec-bytes"])
def test_preparation_metadata_limits_precede_container_creation(tmp_path, monkeypatch, kind):
    if kind == "spec-bytes":
        packages = {
            f"example_{i}": {"version": "1.0", "hashes": [DIGEST] * 128} for i in range(128)
        }
        monkeypatch.setattr(prep, "locked_packages", lambda _: packages)
        smoke = smoke_module.Smoke(tmp_path)
        smoke.docker = ("docker",)
        daemon = Daemon(tmp_path)
        smoke.transport = daemon
        with pytest.raises(ValueError, match=r"bound|limit"):
            prep.prepare_files(smoke, "download", tmp_path / "published")
        assert daemon.calls == [] and smoke.owned == []
        assert not (tmp_path / "prepare-download/inputs/packages.json").exists()
    else:
        text = (
            "#" * (128 * 1024 + 1)
            if kind == "lock-bytes"
            else "".join(f"example_{i}==1.0 --hash=sha256:{DIGEST}\n" for i in range(129))
        )
        (tmp_path / "requirements.lock").write_text(text)
        (tmp_path / "build-requirements.lock").write_text("# empty fixture\n")
        with pytest.raises(ValueError, match=r"bound|count"):
            prep.locked_packages(tmp_path)


def test_large_wheel_streaming_uses_preparation_not_cad_limits(tmp_path):
    import tempfile

    size = 65 * 1024**2
    source, collected, destination = (tmp_path / name for name in ("source", "collected", "dest"))
    for directory in (source, collected, destination):
        directory.mkdir()
    digest = hashlib.sha256()
    chunk = b"x" * 65536
    with (source / LEAF).open("wb") as stream:
        for _ in range(size // len(chunk)):
            stream.write(chunk)
            digest.update(chunk)
    packages = {"example": {"version": "1.0", "hashes": [digest.hexdigest()]}}
    s = transfer.PreparationSchema("download", packages)
    with tempfile.TemporaryFile() as stream:
        wire._export(
            stream,
            {"files": {LEAF: digest.hexdigest()}},
            NONCE,
            "preparation-v1/download",
            source,
            transfer.BOUNDS,
            s,
        )
        stream.seek(0)
        with wire._Receiver(
            collected, NONCE, "preparation-v1/download", transfer.BOUNDS, s
        ) as receiver:
            while data := stream.read(65536):
                receiver.feed(data)
            receiver.finish()
            assert receiver.files[LEAF].length == size
            receiver.install(destination)
    assert (destination / LEAF).stat().st_size == size
    assert not list(collected.iterdir())
    assert DEFAULT_STORAGE.input_bytes == 64 * 1024**2


def test_aggregate_export_is_refused_before_any_body_write(tmp_path):
    packages = {f"wheel{i}": PACKAGES["example"] for i in range(4)}
    s = transfer.PreparationSchema("download", packages)
    header = wire.encode(
        {
            "nonce": NONCE,
            "operation": "preparation-v1/download",
            "result_length": 1,
            "artifacts": [
                {"id": f"{name}-1.0-py3-none-any.whl", "length": transfer.FILE_BYTES}
                for name in packages
            ],
        },
        65536,
    )
    with (
        wire._Receiver(tmp_path, NONCE, "preparation-v1/download", transfer.BOUNDS, s) as receiver,
        pytest.raises(ValueError, match="aggregate"),
    ):
        receiver.feed(wire.MAGIC + struct.pack("!I", len(header)) + header)
    assert not list(tmp_path.iterdir())


def test_ignored_snapshot_entries_are_still_counted(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    for i in range(3):
        (source / f"{i}.pyc").touch()
    monkeypatch.setattr(transfer, "INPUT_ENTRIES", 2)
    with pytest.raises(ValueError, match="entry"):
        transfer.snapshot({"source": source}, tmp_path / "dest")
    assert not (tmp_path / "dest").exists()


def test_exact_downloader_snapshot_imports_without_site_packages_or_cad(tmp_path):
    inputs = tmp_path / "inputs"
    manifest = transfer.snapshot(prep.input_sources("download", None), inputs)
    assert not any(name.startswith(("source/", "wheels/", "cache/")) for name in manifest)
    script = (
        f"import sys; sys.path.insert(0, {str(inputs / 'code')!r}); "
        "import macos_preparation_worker; "
        "assert not any(m.startswith(('OCP', 'build123d', 'hephaestus.core.render', "
        "'hephaestus.core.executor.worker', 'hephaestus.server')) for m in sys.modules); "
        "print(macos_preparation_worker.recipe('download'))"
    )
    result = SubprocessTransport().run(
        (sys.executable, "-I", "-S", "-c", script),
        input=b"",
        timeout=10,
        stdout_limit=4096,
        stderr_limit=4096,
        env=RUNTIME_ENV,
    )
    assert result.returncode == 0, result.stderr
    assert b"--only-binary=:all:" in result.stdout
