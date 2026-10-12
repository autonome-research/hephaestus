# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Synthetic host regressions. Live acceptance comes only from the local CLI."""

from __future__ import annotations

import copy
import importlib
import io
import json
import os
import stat
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from hephaestus.core.errors import SandboxDeniedError
from hephaestus.core.executor.sandbox import oci, oci_launcher
from hephaestus.core.executor.sandbox.oci_storage import (
    MASKED_DEVICE_PATHS,
    masked_device,
    mount_records,
    storage_valid,
)
from hephaestus.core.executor.sandbox.oci_storage_policy import (
    CONTROL_STORAGE,
    DEFAULT_STORAGE,
    STORAGE_WORKER,
)
from hephaestus.core.executor.sandbox.oci_transfer import InputAdmission, export

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "core/tests"))
fixtures = importlib.import_module("test_sandbox_oci")
check = importlib.import_module("macos_staging_check")


def test_storage_observation_uses_bind_flags_not_superblock_flags():
    records = mount_records("1 0 0:1 / /inputs ro,nosuid - ext4 /dev/vda rw\n")
    assert records["/inputs"]["options"] == ["nosuid", "ro"]
    with pytest.raises(ValueError):
        mount_records("bad")
    with pytest.raises(ValueError):
        mount_records("1 0 0:1 / /inputs ro - ext4 dev rw\n" * 2)


def test_all_storage_evidence_is_required_and_typed():
    good = fixtures.synthetic_storage(CONTROL_STORAGE)
    assert storage_valid(good, CONTROL_STORAGE)
    assert not storage_valid(good, DEFAULT_STORAGE)
    for key in good:
        value = copy.deepcopy(good)
        del value[key]
        assert not storage_valid(value, CONTROL_STORAGE)
    for path in good["runtime_write_errno"]:
        for bad in (0, False, None, [], "30", 2):
            if path == "/dev/shm" and bad == 2:
                continue
            value = copy.deepcopy(good)
            value["runtime_write_errno"][path] = bad
            assert not storage_valid(value, CONTROL_STORAGE)
    for path in ("/work", "/tmp"):
        for key in good["capacities"][path]:
            for bad in (None, False, [], "128", -1, 2**40):
                value = copy.deepcopy(good)
                value["capacities"][path][key] = bad
                assert not storage_valid(value, CONTROL_STORAGE)
        for key in ("fs_type", "options"):
            for bad in (None, [], {}, [None], "tmpfs"):
                value = copy.deepcopy(good)
                value["mounts"][path][key] = bad
                if key == "fs_type" and bad == "tmpfs":
                    continue
                assert not storage_valid(value, CONTROL_STORAGE)
    value = copy.deepcopy(good)
    value["mounts"]["/unexpected"] = {"fs_type": "tmpfs", "options": ["rw"]}
    assert not storage_valid(value, CONTROL_STORAGE)
    value = copy.deepcopy(good)
    value["mounts"]["/inputs"]["options"] = ["rw"]
    assert not storage_valid(value, CONTROL_STORAGE)
    # Actual Docker ipc=none still had a writable POSIX mqueue. Never allowlist it.
    value = copy.deepcopy(good)
    value["mounts"]["/dev/mqueue"] = {
        "fs_type": "mqueue",
        "options": ["rw", "nodev", "noexec", "nosuid"],
    }
    assert not storage_valid(value, CONTROL_STORAGE)
    del value["mounts"]["/dev/mqueue"]
    assert not storage_valid(value, CONTROL_STORAGE)


@pytest.mark.parametrize(
    "policy,nonce", [("unknown", "0" * 64), ("control", "x" * 64), ("control", "0" * 63)]
)
def test_launcher_rejects_unknown_policy_nonce(policy, nonce):
    with pytest.raises(ValueError):
        oci_launcher.parse_argv(
            ("run", "3", STORAGE_WORKER, "15", "268435456", "32", policy, nonce)
        )


def test_launcher_storage_failure_prevents_exec(monkeypatch, capsys):
    monkeypatch.setattr(oci_launcher, "apply_rlimits", lambda _: None)

    def refuse(_):
        raise ValueError("unsupported storage")

    monkeypatch.setattr(oci_launcher, "require_storage", refuse)
    monkeypatch.setattr(oci_launcher, "exec_worker", lambda _: pytest.fail("must not exec"))
    assert (
        oci_launcher.main(
            ("run", "3", STORAGE_WORKER, "15", "268435456", "32", "control", "0" * 64)
        )
        == 78
    )
    assert "storage_observation_failed" in capsys.readouterr().err


def test_input_admission_precedes_all_writes_and_includes_sidecars(tmp_path):
    policy = replace(CONTROL_STORAGE, input_bytes=9, input_files=2)
    admission = InputAdmission(policy)
    name = "a" * 32 + ".hmesh"
    area = tmp_path.resolve() / "inputs"
    with pytest.raises(ValueError, match="aggregate"):
        admission.write(area, {name: b"12345", name + ".facts": b"12345"})
    assert not area.exists()
    admission.write(area, {name: b"1234", name + ".facts": b"12345"})
    admission.write(area, {name: b"1234"})
    with pytest.raises(ValueError, match="collision"):
        admission.write(area, {name: b"other"})
    with pytest.raises(ValueError, match="aggregate"):
        admission.write(area, {"source.brep": b"x"})
    assert (area / name).read_bytes() == b"1234"
    assert len(list(area.iterdir())) == 2


def test_converted_input_admitted_before_host_write(tmp_path, monkeypatch):
    from hephaestus.core.executor import imports

    admission = InputAdmission(replace(CONTROL_STORAGE, input_bytes=8))
    monkeypatch.setattr(imports, "_convert_step", lambda *a, **kw: b"x" * 9)
    with pytest.raises(ValueError):
        imports.stage_import(
            b"raw", path="test.step", content_hash="a" * 64, out_dir=tmp_path, admission=admission
        )
    assert not (tmp_path / "inputs").exists()


def test_raw_input_aggregate_refuses_before_converter(tmp_path, monkeypatch):
    from hephaestus.core.executor import runner
    from hephaestus.core.executor.imports import ImportPayload

    admission = InputAdmission(replace(CONTROL_STORAGE, input_bytes=8))
    request = runner.BuildRequest(
        part="test", script="", imports={"a": ImportPayload(b"12345"), "b": ImportPayload(b"12345")}
    )
    monkeypatch.setattr(runner, "stage_import", lambda *a, **kw: pytest.fail("must not convert"))
    with pytest.raises(SandboxDeniedError, match="raw input aggregate"):
        runner.stage_request_imports(request, tmp_path, admission=admission)
    assert not list(tmp_path.iterdir())


class WireTransport:
    def __init__(
        self,
        output,
        *,
        malformed=False,
        oom=False,
        exit_code=0,
        removal=True,
        config_mutator=None,
        bad_source_map=False,
    ):
        self.output = output
        self.malformed, self.oom, self.exit_code = malformed, oom, exit_code
        self.removal, self.config_mutator = removal, config_mutator
        self.bad_source_map = bad_source_map
        self.argv = None
        self.removed = False
        self.commands = []

    def run(self, argv, *, stdout_consumer=None, **kwargs):
        self.commands.append(tuple(argv))

        def result(value):
            return oci.TransportResult(0, (json.dumps(value) + "\n").encode(), b"")

        if "create" in argv:
            self.argv = argv
            return oci.TransportResult(0, (fixtures.CONTAINER_ID + "\n").encode(), b"")
        if "{{json .}}" in argv:
            config = fixtures.synthetic_effective(self.argv)
            if self.config_mutator:
                self.config_mutator(config)
            return result(config)
        if "start" in argv:
            assert stdout_consumer is not None
            stream = io.BytesIO()
            source = self.output.parent / "synthetic-worker"
            source.mkdir()
            (source / "final.brep").write_bytes(b"synthetic-body")
            (source / "source_map.json").write_bytes(b'{"x":1}' if self.bad_source_map else b"{}")
            export(
                stream,
                {
                    "status": "ok",
                    "artifacts": {"build": "final.brep", "source_map": "source_map.json"},
                    "source_map": {"x": True} if self.bad_source_map else {},
                    "params_declaration": {},
                },
                self.argv[-1],
                self.argv[self.argv.index("run") + 2],
                source,
                CONTROL_STORAGE,
            )
            wire = stream.getvalue()
            if self.malformed:
                wire = wire[:-1]
            for i in range(0, len(wire), 7):
                stdout_consumer(wire[i : i + 7])
            assert not (self.output / "final.brep").exists()
            return oci.TransportResult(0, b"", b"")
        if "rm" in argv:
            assert not (self.output / "final.brep").exists()
            self.removed = self.removal
            return oci.TransportResult(0 if self.removal else 1, b"", b"")
        if "inspect" in argv:
            if self.removed:
                return oci.TransportResult(1, b"", b"no such container")
            assert not (self.output / "final.brep").exists()
            return result({"Running": False, "ExitCode": self.exit_code, "OOMKilled": self.oom})
        raise AssertionError(argv)


def wire_backend(tmp_path, **kwargs):
    out = tmp_path.resolve() / "out"
    out.mkdir()
    transport = WireTransport(out, **kwargs)
    backend = oci.OciBackend(
        fixtures.runtime(),
        fixtures.IMAGE,
        "linux/arm64",
        identity=fixtures.IDENTITY,
        transport=transport,
        storage_policy="control",
    )
    fixtures.passing(backend)
    spec = fixtures.spec(out, worker_args=("-m", STORAGE_WORKER))
    return backend, spec, transport


def test_oci_transfer_runner_publication_and_freshness_share_control_identity(tmp_path):
    from _execution_identity import runtime_inventory
    from hephaestus.core.executor.identity import IDENTITY_METADATA_KEY
    from hephaestus.core.executor.runner import BuildRequest, run_build
    from hephaestus.core.executor.sandbox.base import Rlimits
    from hephaestus.core.executor.sandbox.oci_protocol import manifest_bytes
    from hephaestus.core.project_store.layout import open_store
    from hephaestus.core.project_store.publication import Publisher
    from test_project_store_helpers import DEFAULT_SCRIPT, make_project

    def no_host_toolchain():
        pytest.fail("OCI path must not inspect host CAD metadata")

    backend, spec, transport = wire_backend(tmp_path)
    backend._accept_manifest(manifest_bytes(runtime_inventory()))
    built = run_build(
        BuildRequest("widget", DEFAULT_SCRIPT, wall_clock_s=30),
        backend=backend,
        out_dir=spec.rw_out_dir,
        rlimits=Rlimits(15, 256 * 1024**2, 32),
        native_toolchain_hash=no_host_toolchain,
    )
    assert transport.removed
    expected = backend.execution_identity()
    assert built.execution_identity == expected
    assert built.result.input_hashes.toolchain == expected.toolchain_hash
    layout = make_project(tmp_path / "project")
    with open_store(layout) as store:
        publisher = Publisher(
            layout, store, backend=backend, native_toolchain_hash=no_host_toolchain
        )
        published = publisher.publish_build(built, op_id="wire")
        assert published.kind == "current"
        assert publisher.freshness("widget").fresh
        assert (
            publisher.current_result("widget").metadata[IDENTITY_METADATA_KEY] == expected.canonical
        )
        # A reader without this injected executor cannot treat the OCI record as native.
        native_reader = Publisher(layout, store, native_toolchain_hash=no_host_toolchain)
        assert native_reader.freshness("widget").changed_inputs == ("toolchain",)


def test_canonical_path_streams_installs_only_after_terminal_and_cleanup(tmp_path):
    backend, spec, transport = wire_backend(tmp_path)
    outcome = backend.execute(spec, b'{"protocol_version":3,"operation":"positive"}')
    assert outcome.exit_code == 0 and not outcome.timed_out
    assert (spec.rw_out_dir / "final.brep").read_bytes() == b"synthetic-body"
    assert (spec.rw_out_dir / "final.brep").stat().st_nlink == 1
    assert transport.removed
    assert "--log-driver=none" in transport.argv
    assert str(spec.rw_out_dir) not in transport.argv[transport.argv.index("--mount") + 1]
    assert len(list(tmp_path.glob(".heph-transfer-*"))) == 0


@pytest.mark.parametrize("change", [{"malformed": True}, {"oom": True}, {"removal": False}])
def test_canonical_path_never_installs_on_invalid_transfer_oom_or_cleanup(tmp_path, change):
    backend, spec, _ = wire_backend(tmp_path, **change)
    with pytest.raises(SandboxDeniedError):
        backend.execute(spec, b'{"protocol_version":3,"operation":"positive"}')
    assert not list(spec.rw_out_dir.iterdir())
    assert not list(tmp_path.glob(".heph-transfer-*"))


@pytest.mark.parametrize(
    "section,key,bad",
    [
        (None, "Image", "sha256:" + "f" * 64),
        (None, "LogPath", "/log"),
        ("HostConfig", "LogConfig", {"Type": "json-file", "Config": {}}),
        ("HostConfig", "Tmpfs", {"/work": "rw"}),
        ("HostConfig", "Privileged", True),
        ("HostConfig", "CapAdd", ["SYS_ADMIN"]),
        ("HostConfig", "NetworkMode", "host"),
        ("HostConfig", "PidMode", "host"),
        ("HostConfig", "IpcMode", "host"),
        ("HostConfig", "ReadonlyRootfs", False),
        ("HostConfig", "Memory", 0),
        ("HostConfig", "PidsLimit", 0),
        ("HostConfig", "NanoCpus", 0),
        ("Config", "User", "0:0"),
        ("Config", "Tty", True),
        ("Config", "Healthcheck", {"Test": ["CMD", "sh"]}),
        ("Config", "Cmd", ["sh"]),
        ("Config", "Env", ["LD_PRELOAD=bad"]),
        ("Config", "Entrypoint", ["sh"]),
        (None, "Mounts", []),
    ],
)
def test_effective_config_mismatch_refuses_before_start(tmp_path, section, key, bad):
    def mutate(value):
        (value if section is None else value[section])[key] = bad

    backend, spec, transport = wire_backend(tmp_path, config_mutator=mutate)
    with pytest.raises(SandboxDeniedError):
        backend.execute(spec, b'{"protocol_version":3,"operation":"positive"}')
    assert not any("start" in argv for argv in transport.commands)
    assert transport.removed and not list(spec.rw_out_dir.iterdir())


@pytest.mark.parametrize("operation", ["work-bytes", "tmp-bytes", "work-inodes", "tmp-inodes"])
def test_exhaustion_requires_actual_typed_errno_capacity_and_recovery(operation):
    path = "/work" if operation.startswith("work") else "/tmp"
    before = fixtures.synthetic_storage(CONTROL_STORAGE)["capacities"][path]
    after = dict(before)
    inodes = operation.endswith("inodes")
    after["available_inodes" if inodes else "available_bytes"] = 0
    value = {
        "path": path,
        "kind": "inodes" if inodes else "bytes",
        "before": before,
        "exhausted": after,
        "restored": dict(before),
        "allocated": before["available_inodes" if inodes else "available_bytes"],
        "errno": 28,
        "recovery": True,
    }
    assert check.exhaustion_valid(value, operation)
    for key in value:
        bad = dict(value)
        del bad[key]
        assert not check.exhaustion_valid(bad, operation)
    for bad_errno in (None, True, 28.0, 27, 12, 13, 24):
        assert not check.exhaustion_valid({**value, "errno": bad_errno}, operation)
    assert not check.exhaustion_valid({**value, "allocated": 0}, operation)
    assert not check.exhaustion_valid({**value, "recovery": False}, operation)


@pytest.mark.parametrize(
    "module,names,job",
    [
        (fixtures.BUILD_WORKER, ("source.brep",), {"out_dir": ".", "imports": {}}),
        (fixtures.BUILD_WORKER, (), {"out_dir": ".", "imports": {"key": "a" * 32 + ".brep"}}),
        (
            fixtures.BUILD_WORKER,
            ("a" * 32 + ".hmesh",),
            {"out_dir": ".", "imports": {"key": "a" * 32 + ".hmesh"}},
        ),
        ("hephaestus.core.dfm.worker", (), {"out_dir": ".", "brep": "source.brep"}),
        (
            "hephaestus.core.dfm.worker",
            ("source.brep",),
            {"out_dir": ".", "brep": "../source.brep"},
        ),
    ],
)
def test_job_input_declaration_mismatch_refuses_before_create(tmp_path, module, names, job):
    backend, spec, transport = wire_backend(tmp_path)
    spec = replace(spec, worker_args=("-m", module), input_files=names)
    with pytest.raises(ValueError):
        backend.execute(spec, json.dumps(job).encode())
    assert transport.commands == []


def test_dfm_admission_and_declaration_before_backend_dispatch(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from hephaestus.core.dfm import runner
    from hephaestus.core.executor.sandbox.base import CapabilityReport, ExecOutcome

    calls = []

    class Backend:
        storage_policy = replace(CONTROL_STORAGE, input_bytes=8)

        def probe(self):
            return CapabilityReport("synthetic", True)

        def execute(self, spec, payload):
            assert spec.input_files == ("source.brep",)
            assert (spec.rw_out_dir / "inputs/source.brep").read_bytes() == b"synthetic"
            assert not (spec.rw_out_dir / "source.brep").exists()
            calls.append(spec)
            return ExecOutcome(0, b"{}", b"")

    pack = SimpleNamespace(process="test", rules=[])
    request = runner.DfmRequest("part", "test", b"synthetic", "synthetic-ref")
    monkeypatch.setattr(runner, "parse_evaluation", lambda *a, **kw: "synthetic-evaluation")
    with pytest.raises(ValueError):
        runner.evaluate_pack(
            replace(request, brep=b"oversized"), pack, backend=Backend(), scratch_root=tmp_path
        )
    assert calls == [] and not list(tmp_path.iterdir())
    backend = Backend()
    backend.storage_policy = replace(CONTROL_STORAGE, input_bytes=9)
    assert (
        runner.evaluate_pack(request, pack, backend=backend, scratch_root=tmp_path)
        == "synthetic-evaluation"
    )
    assert len(calls) == 1 and not list(tmp_path.iterdir())


def test_build_source_map_disagreement_refuses_before_install(tmp_path):
    backend, spec, transport = wire_backend(tmp_path, bad_source_map=True)
    spec = replace(spec, worker_args=("-m", fixtures.BUILD_WORKER))
    with pytest.raises(SandboxDeniedError, match="source map disagrees"):
        backend.execute(spec, b'{"out_dir":".","imports":{}}')
    assert transport.removed and not list(spec.rw_out_dir.iterdir())


@pytest.mark.parametrize(
    "field,stale",
    [
        ("manifest_version", 2),
        ("oci_profile_version", 3),
        ("oci_profile_version", 4),
        ("protocol", {"name": "hephaestus.oci-executor", "version": 2}),
    ],
)
def test_stale_image_manifest_refused_before_containment(tmp_path, monkeypatch, field, stale):
    from hephaestus.core.executor.sandbox.base import ExecOutcome
    from hephaestus.core.executor.sandbox.oci_protocol import manifest_record

    backend, _, _ = wire_backend(tmp_path)
    record = manifest_record()
    record[field] = stale
    calls = []

    def stale_manifest(*args, **kwargs):
        calls.append(kwargs)
        return ExecOutcome(
            0, (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode(), b""
        )

    monkeypatch.setattr(backend, "_run_container", stale_manifest)
    with pytest.raises(SandboxDeniedError, match="manifest"):
        backend._live_probe()
    assert len(calls) == 1 and calls[0]["command_tail"] == ("manifest",)


@pytest.mark.parametrize("path", MASKED_DEVICE_PATHS)
@pytest.mark.parametrize(
    "field,bad",
    [
        ("file_type", stat.S_IFREG),
        ("file_type", stat.S_IFDIR),
        ("file_type", stat.S_IFLNK),
        ("file_type", stat.S_IFBLK),
        ("file_type", float(stat.S_IFCHR)),
        ("major", True),
        ("minor", 5),
        ("major", 0),
        ("minor", "3"),
    ],
)
def test_writable_proc_masks_require_actual_typed_null_device(path, field, bad):
    value = fixtures.synthetic_storage(CONTROL_STORAGE)
    value["masked_devices"][path][field] = bad
    assert not storage_valid(value, CONTROL_STORAGE)


@pytest.mark.parametrize("path", MASKED_DEVICE_PATHS)
def test_missing_or_extra_device_evidence_refuses(path):
    for change in (None, {}, {"file_type": stat.S_IFCHR, "major": 1, "minor": 3, "extra": 0}):
        value = fixtures.synthetic_storage(CONTROL_STORAGE)
        value["masked_devices"][path] = change
        assert not storage_valid(value, CONTROL_STORAGE)
    value = fixtures.synthetic_storage(CONTROL_STORAGE)
    del value["masked_devices"][path]
    assert not storage_valid(value, CONTROL_STORAGE)


def test_mask_observer_does_not_follow_symlinks_or_open_devices(tmp_path):
    regular = tmp_path / "regular"
    regular.write_bytes(b"not a device")
    link = tmp_path / "link"
    link.symlink_to(regular)
    assert masked_device(str(regular))["file_type"] == stat.S_IFREG
    assert masked_device(str(tmp_path))["file_type"] == stat.S_IFDIR
    assert masked_device(str(link))["file_type"] == stat.S_IFLNK
    assert masked_device(str(tmp_path / "absent")) == {"errno": 2}


@pytest.mark.parametrize("path", MASKED_DEVICE_PATHS)
def test_explicit_absent_device_requires_absent_mount_and_exact_errno(path):
    value = fixtures.synthetic_storage(CONTROL_STORAGE)
    value["masked_devices"][path] = {"errno": 2}
    assert not storage_valid(value, CONTROL_STORAGE)  # mounted but stat failed
    del value["mounts"][path]
    assert storage_valid(value, CONTROL_STORAGE)  # no device exemption is used
    for bad in (None, {"errno": 2.0}, {"errno": True}, {"errno": 13}, {"errno": 2, "extra": 0}):
        value["masked_devices"][path] = bad
        assert not storage_valid(value, CONTROL_STORAGE)


@pytest.mark.parametrize("failure", ["write", "parse"])
@pytest.mark.parametrize("removal", [True, False])
def test_grouped_transfer_failure_reaps_client_and_reconciles_running_container(
    tmp_path, monkeypatch, failure, removal
):
    """Synthetic daemon state, REAL attach child/receiver/transport/lifecycle.

    No Docker or CAD: tests the ownership boundary when a live attach client
    encounters a receiver failure AND unlink failure, not receiver cleanup alone.
    """
    from hephaestus.core.executor.sandbox import oci_transfer

    backend, spec, _ = wire_backend(tmp_path)
    clients = []
    real_popen = oci.subprocess.Popen

    def popen(*args, **kwargs):
        child = real_popen(*args, **kwargs)
        clients.append(child)
        return child

    monkeypatch.setattr(oci.subprocess, "Popen", popen)
    real_write, real_unlink = oci_transfer._write, os.unlink
    failures = []

    def write(stream, data):
        if failure == "write" and not isinstance(stream, io.BytesIO):
            real_write(stream, data[:1])  # actual partial disk write precedes failure
            failures.append("write")
            raise OSError("injected receiver write failure")
        real_write(stream, data)

    def unlink(path, *args, **kwargs):
        if path == "last_good.brep" and "unlink" not in failures:
            failures.append("unlink")
            raise PermissionError("injected unlink failure")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(oci_transfer, "_write", write)
    monkeypatch.setattr(os, "unlink", unlink)

    class RunningTransport(WireTransport):
        running = True

        def run(self, argv, *, stdout_consumer=None, **kwargs):
            if "start" in argv:
                self.commands.append(tuple(argv))
                source = tmp_path / "worker-source"
                source.mkdir()
                (source / "last_good.brep").write_bytes(b"synthetic-partial-body")
                stream = io.BytesIO()
                export(
                    stream,
                    {"status": "failed", "artifacts": {"last_good": "last_good.brep"}},
                    self.argv[-1],
                    STORAGE_WORKER,
                    source,
                    CONTROL_STORAGE,
                )
                wire = stream.getvalue()
                wire = wire[:-1] + bytes([wire[-1] ^ 1])
                # A positive stream edge, not a sleep-based assertion. The
                # child cannot exit normally: it blocks until killed or timeout.
                return oci.SubprocessTransport().run(
                    [sys.executable, "-c", f"import os,signal;os.write(1,{wire!r});signal.pause()"],
                    input=b"",
                    timeout=5,
                    stdout_limit=65536,
                    stderr_limit=1024,
                    env={},
                    stdout_consumer=stdout_consumer,
                )
            if "kill" in argv:
                self.commands.append(tuple(argv))
                assert self.running
                assert len(clients) == 1 and clients[0].poll() is not None
                self.running = False
                return oci.TransportResult(0, b"", b"")
            if "inspect" in argv and "{{json .}}" not in argv:
                self.commands.append(tuple(argv))
                if self.removed:
                    return oci.TransportResult(1, b"", b"no such container")
                return oci.TransportResult(
                    0,
                    json.dumps(
                        {
                            "Running": self.running,
                            "ExitCode": 0 if self.running else 137,
                            "OOMKilled": False,
                        }
                    ).encode()
                    + b"\n",
                    b"",
                )
            return super().run(argv, stdout_consumer=stdout_consumer, **kwargs)

    transport = RunningTransport(spec.rw_out_dir, removal=removal)
    backend._transport = transport
    error = ExceptionGroup if removal else SandboxDeniedError
    with pytest.raises(error) as caught:
        backend.execute(spec, b'{"protocol_version":3,"operation":"positive"}')
    assert "unlink" in failures
    assert len(clients) == 1 and clients[0].returncode == -9
    assert all(s.closed for s in (clients[0].stdin, clients[0].stdout, clients[0].stderr))
    assert any("kill" in argv for argv in transport.commands), (
        [argv[1:4] for argv in transport.commands],
        transport.running,
        backend.last_terminal_state,
    )
    assert any("rm" in argv for argv in transport.commands)
    assert not list(spec.rw_out_dir.iterdir())
    assert not list(tmp_path.glob(".heph-transfer-*"))
    assert backend.last_transfer_records == {}
    assert backend.last_transfer_observation["installed"] is False
    if removal:
        assert transport.removed
        assert backend.unreconciled_containers == frozenset()
        assert isinstance(caught.value.__context__, (OSError, ValueError))
    else:
        assert backend.unreconciled_containers == {fixtures.CONTAINER_ID}
        commands = len(transport.commands)
        assert not backend.probe().available
        with pytest.raises(SandboxDeniedError):
            backend.execute(spec, b'{"protocol_version":3,"operation":"positive"}')
        assert len(transport.commands) == commands
        assert isinstance(caught.value.__context__, ExceptionGroup)


def test_storage_policy_is_fixed_per_backend(tmp_path):
    backend, _, _ = wire_backend(tmp_path)
    with pytest.raises(AttributeError):
        backend.storage_policy = DEFAULT_STORAGE
    with pytest.raises(AttributeError):
        backend.storage_policy_name = "ordinary"
    assert backend.storage_policy == CONTROL_STORAGE


@pytest.mark.parametrize(
    "module,entry",
    [
        ("hephaestus.core.executor.worker", "execute_job"),
        ("hephaestus.core.dfm.worker", "evaluate_job"),
    ],
)
def test_approved_worker_oci_mode_uses_fixed_inputs_and_same_export_seam(
    module, entry, monkeypatch
):
    from hephaestus.core.executor.sandbox import oci_worker_io

    worker = importlib.import_module(module)
    calls = []
    sent = []

    def operation(job, *, input_dir):
        calls.append((job, input_dir))
        return {"status": "failed", "artifacts": {}}

    monkeypatch.setattr(worker, entry, operation)
    monkeypatch.setattr(
        oci_worker_io.WorkerIO, "send", lambda self, value, selected: sent.append((value, selected))
    )
    monkeypatch.setattr(
        sys, "stdin", io.TextIOWrapper(io.BytesIO(b'{"out_dir":".","brep":"source.brep"}'))
    )
    assert worker.main(oci_args=("--oci-transfer", "control", "a" * 64)) == 0
    assert calls[0][1] == Path("/inputs")
    assert sent == [({"status": "failed", "artifacts": {}}, module)]


@pytest.mark.parametrize(
    "module,entry",
    [
        ("hephaestus.core.executor.worker", "execute_job"),
        ("hephaestus.core.dfm.worker", "evaluate_job"),
    ],
)
def test_native_main_keeps_native_protocol_despite_caller_argv(module, entry, monkeypatch, capsys):
    worker = importlib.import_module(module)

    def operation(job, *, input_dir):
        assert input_dir is None
        return {"status": "failed", "artifacts": {}}

    monkeypatch.setattr(worker, entry, operation)
    monkeypatch.setattr(sys, "argv", ["pytest", "not-worker-args"])
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))
    assert worker.main() == 0
    assert json.loads(capsys.readouterr().out) == {"status": "failed", "artifacts": {}}


@pytest.mark.parametrize(
    "operation", ["partial-body", "artifact-truncated-footer", "stdout-overflow"]
)
def test_fixed_live_transfer_controls_export_actual_bodies_then_reject(
    tmp_path, monkeypatch, operation
):
    from types import SimpleNamespace

    from hephaestus.core.executor.sandbox import _oci_storage_worker as worker
    from hephaestus.core.executor.sandbox.oci_transfer import Receiver

    nonce = "a" * 64
    source, collected = tmp_path / "work", tmp_path / "collected"
    source.mkdir()
    collected.mkdir()
    # /work itself is also used by the exporter, not just its artifact leaf.
    monkeypatch.setattr(
        worker, "Path", lambda path: source if path == "/work" else source / Path(path).name
    )
    monkeypatch.setattr(
        worker, "observe_storage", lambda: fixtures.synthetic_storage(CONTROL_STORAGE)
    )
    monkeypatch.setattr(
        worker,
        "worker_io",
        lambda: SimpleNamespace(
            policy=CONTROL_STORAGE,
            nonce=nonce,
            read=lambda: {"protocol_version": 3, "operation": operation},
        ),
    )
    stdout = io.BytesIO()
    monkeypatch.setattr(worker.sys, "stdout", SimpleNamespace(buffer=stdout))
    assert worker.main() == 0
    wire = stdout.getvalue()
    assert len(wire) == 384 * 1024 if operation == "stdout-overflow" else len(wire) < 65536
    with Receiver(collected.resolve(), nonce, STORAGE_WORKER, CONTROL_STORAGE) as receiver:
        with pytest.raises(ValueError):
            for start in range(0, len(wire), 4096):
                receiver.feed(wire[start : start + 4096])
            receiver.finish()
        assert receiver.created == ["last_good.brep"]
        assert receiver.body_bytes == (
            len(worker.OUTPUT) // 2 if operation == "partial-body" else len(worker.OUTPUT)
        )
        assert not receiver.installed
    assert not list(collected.iterdir())


def test_streaming_transport_does_not_accumulate_stdout():
    chunks = []
    result = oci.SubprocessTransport().run(
        [sys.executable, "-c", "import sys;sys.stdout.buffer.write(b'x'*131072)"],
        input=b"",
        timeout=5,
        stdout_limit=131072,
        stderr_limit=1024,
        env={},
        stdout_consumer=chunks.append,
    )
    assert result.stdout == b"" and result.returncode == 0
    assert b"".join(chunks) == b"x" * 131072
    with pytest.raises(oci.TransportOutputLimit):
        oci.SubprocessTransport().run(
            [sys.executable, "-c", "import sys;sys.stdout.buffer.write(b'x'*1025)"],
            input=b"",
            timeout=5,
            stdout_limit=1024,
            stderr_limit=1024,
            env={},
            stdout_consumer=lambda _: None,
        )
