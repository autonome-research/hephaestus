"""Host-only synthetic transfer tests. No CAD, quota or provenance evidence."""

from __future__ import annotations

import hashlib
import io
import json
import os
import socket
import struct
import tempfile
import tracemalloc
from dataclasses import replace
from pathlib import Path

import pytest
from hephaestus.core.executor.sandbox import oci_transfer as transfer
from hephaestus.core.executor.sandbox.oci_protocol import (
    APPROVED_MODULES,
    BUILD_WORKER,
    DFM_WORKER,
    MANIFEST_VERSION,
    OCI_PROFILE_VERSION,
    OCI_TMPFS_BYTES,
    PROBE_WORKER,
    PROTOCOL_VERSION,
    REQUIRED_OCI_FEATURES,
    approved_module_for_worker_args,
    manifest_record,
)
from hephaestus.core.executor.sandbox.oci_storage_policy import (
    CONTROL_STORAGE,
    DEFAULT_STORAGE,
    STORAGE_WORKER,
    StoragePolicy,
)

NONCE = "ab" * 32
RESULT = {"status": "ok", "artifacts": {"build": "final.brep", "source_map": "source_map.json"}}
BODIES = {"build": b"synthetic-not-brep", "source_map": b'{"test":true}'}
INPUT = "0" * 32 + ".brep"


def wire(result=None, *, header=None, result_bytes=None, bodies=None, operation=BUILD_WORKER):
    if result is None:
        result = RESULT
    data = transfer.encode(result) if result_bytes is None else result_bytes
    if bodies is None:
        bodies = BODIES
    if header is None:
        header = {
            "nonce": NONCE,
            "operation": operation,
            "result_length": len(data),
            "artifacts": [{"id": key, "length": len(body)} for key, body in bodies.items()],
        }
    encoded = header if isinstance(header, bytes) else transfer.encode(header)
    prefix = transfer.MAGIC + struct.pack("!I", len(encoded))
    payload = prefix + encoded + data + b"".join(bodies.values())
    return payload + transfer.FOOTER + hashlib.sha256(payload).digest()


def header_for_wire():
    return {
        "nonce": NONCE,
        "operation": BUILD_WORKER,
        "result_length": len(transfer.encode(RESULT)),
        "artifacts": [{"id": key, "length": len(body)} for key, body in BODIES.items()],
    }


def source_dir(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    for ident, body in BODIES.items():
        (source / transfer.NAMES[ident]).write_bytes(body)
    return source


def reject(tmp_path, data, *, policy=CONTROL_STORAGE):
    target = tmp_path / "receive"
    target.mkdir()
    with transfer.Receiver(target, NONCE, BUILD_WORKER, policy) as receiver:
        with pytest.raises((ValueError, OSError)):
            receiver.feed(data)
            receiver.finish()
        assert list(target.iterdir()) == []
        with pytest.raises(ValueError):
            receiver.feed(b"")
    receiver.close()  # idempotent


@pytest.mark.parametrize("chunk_size", [1, 2, 3, 7, 13, 64, 65536])
def test_roundtrip_and_exclusive_install(tmp_path, chunk_size):
    source = source_dir(tmp_path)
    stream = io.BytesIO()
    transfer.export(stream, RESULT, NONCE, BUILD_WORKER, source, CONTROL_STORAGE)
    assert not stream.closed
    assert stream.getvalue() == wire()
    target, destination = tmp_path / "receive", tmp_path / "installed"
    target.mkdir()
    destination.mkdir()
    with transfer.Receiver(target, NONCE, BUILD_WORKER, CONTROL_STORAGE) as receiver:
        fd = receiver.dirfd
        with pytest.raises(ValueError):
            receiver.install(destination)
        data = stream.getvalue()
        for start in range(0, len(data), chunk_size):
            receiver.feed(data[start : start + chunk_size])
        assert json.loads(receiver.finish()) == RESULT
        assert receiver.finish() == transfer.encode(RESULT)
        for ident, body in BODIES.items():
            assert receiver.files[ident] == transfer.FileRecord(
                len(body), hashlib.sha256(body).hexdigest()
            )
        receiver.install(destination)
        with pytest.raises(ValueError):
            receiver.install(destination)
    with pytest.raises(OSError):
        os.fstat(fd)
    assert list(target.iterdir()) == []
    for ident, body in BODIES.items():
        path = destination / transfer.NAMES[ident]
        assert path.read_bytes() == body
        assert path.stat().st_nlink == 1
        assert path.stat().st_mode & 0o777 == 0o600


def test_every_split_and_truncation(tmp_path):
    data = wire()
    # Every possible two-chunk boundary, including header/result/body/footer.
    for index in range(len(data) + 1):
        with transfer.Receiver(tmp_path, NONCE, BUILD_WORKER, CONTROL_STORAGE) as receiver:
            receiver.feed(data[:index])
            receiver.feed(data[index:])
            receiver.finish()
        assert list(tmp_path.iterdir()) == []
    for index in range(len(data)):
        with transfer.Receiver(tmp_path, NONCE, BUILD_WORKER, CONTROL_STORAGE) as receiver:
            receiver.feed(data[:index])
            with pytest.raises(ValueError, match="truncated"):
                receiver.finish()
        assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "result,bodies,operation",
    [
        ({"status": "failed", "artifacts": {}}, {}, BUILD_WORKER),
        (
            {"status": "failed", "artifacts": {"last_good": "last_good.brep"}},
            {"last_good": b"checkpoint"},
            BUILD_WORKER,
        ),
        ({"diagnostic": True}, {}, PROBE_WORKER),
        ({"status": "ok"}, {}, DFM_WORKER),
        (RESULT, BODIES, STORAGE_WORKER),
    ],
)
def test_other_allowed_results(tmp_path, result, bodies, operation):
    source, target = tmp_path / "source", tmp_path / "target"
    source.mkdir()
    target.mkdir()
    for ident, body in bodies.items():
        (source / transfer.NAMES[ident]).write_bytes(body)
    stream = io.BytesIO()
    transfer.export(stream, result, NONCE, operation, source, CONTROL_STORAGE)
    with transfer.Receiver(target, NONCE, operation, CONTROL_STORAGE) as receiver:
        receiver.feed(stream.getvalue())
        assert json.loads(receiver.finish()) == result
    assert list(target.iterdir()) == []  # uninstalled successful transfer is discarded


@pytest.mark.parametrize(
    "field,value",
    [
        ("nonce", "a" * 64),
        ("nonce", 1),
        ("nonce", None),
        ("operation", "unknown"),
        ("operation", []),
        ("operation", DFM_WORKER),
        ("result_length", True),
        ("result_length", 1.0),
        ("result_length", "1"),
        ("result_length", 0),
        ("result_length", -1),
        ("result_length", 65537),
        ("result_length", None),
        ("artifacts", {}),
        ("artifacts", None),
    ],
)
def test_header_types_identity_and_bounds(tmp_path, field, value):
    header = header_for_wire()
    header[field] = value
    reject(tmp_path, wire(header=header))


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "extra",
        "duplicate-key",
        "duplicate-artifact",
        "count",
        "order",
        "descriptor-extra",
        "descriptor-missing",
        "descriptor-type",
        "artifact-missing",
    ],
)
def test_closed_header_and_record_schema(tmp_path, change):
    header = header_for_wire()
    if change == "missing":
        del header["nonce"]
    elif change == "extra":
        header["version"] = 1
    elif change == "duplicate-key":
        header = transfer.encode(header).replace(b'"nonce":', b'"nonce":"ignored","nonce":')
    elif change == "duplicate-artifact":
        header["artifacts"][1] = header["artifacts"][0]
    elif change == "count":
        header["artifacts"] *= 2
    elif change == "order":
        header["artifacts"].reverse()
    elif change == "descriptor-extra":
        header["artifacts"][0]["path"] = "final.brep"
    elif change == "descriptor-missing":
        del header["artifacts"][0]["length"]
    elif change == "descriptor-type":
        header["artifacts"][0] = []
    elif change == "artifact-missing":
        header["artifacts"].pop()
    reject(tmp_path, wire(header=header))


@pytest.mark.parametrize(
    "ident",
    ["../escape", "/tmp/escape", "build/x", "build\\x", "build\0", "bu\u0456ld", "", None, [], 1],
)
def test_closed_artifact_ids(tmp_path, ident):
    header = header_for_wire()
    header["artifacts"][0]["id"] = ident
    reject(tmp_path, wire(header=header))


@pytest.mark.parametrize("length", [False, 1.5, "12", None, -1, 0, 64 * 1024**2 + 1])
def test_artifact_lengths(tmp_path, length):
    header = header_for_wire()
    header["artifacts"][0]["length"] = length
    reject(tmp_path, wire(header=header))


@pytest.mark.parametrize(
    "mutation",
    [
        "version",
        "magic",
        "empty-header",
        "huge-header",
        "body",
        "footer",
        "trailing",
        "extra-body",
        "short-body",
        "long-result",
        "short-result",
    ],
)
def test_framing_corruption(tmp_path, mutation):
    data = wire()
    if mutation == "version":
        data = data[:8] + b"\x02" + data[9:]
    elif mutation == "magic":
        data = b"X" + data[1:]
    elif mutation in {"empty-header", "huge-header"}:
        data = transfer.MAGIC + struct.pack("!I", 0 if mutation == "empty-header" else 2**32 - 1)
    elif mutation == "body":
        data = data.replace(BODIES["build"], b"x" * len(BODIES["build"]))
    elif mutation == "footer":
        data = data[:-1] + bytes([data[-1] ^ 1])
    elif mutation == "trailing":
        data += b"X"
    elif mutation == "extra-body":
        data = data[:-40] + b"X" + data[-40:]
    elif mutation == "short-body":
        data = data.replace(BODIES["build"], BODIES["build"][:-1])
    else:
        header = header_for_wire()
        header["result_length"] += 1 if mutation == "long-result" else -1
        data = wire(header=header)
    reject(tmp_path, data)


@pytest.mark.parametrize(
    "data",
    [
        b'{"status":"ok","status":"failed","artifacts":{}}',
        b'{"status":"failed","artifacts":{"last_good":"last_good.brep","last_good":"last_good.brep"}}',
        b'{"status":"failed","artifacts":{},"x":NaN}',
        b'{"status":"failed","artifacts":{},"x":1e9999}',
        b'{"status":"failed","artifacts":{},"x":' + b"[" * 33 + b"0" + b"]" * 33 + b"}",
        b'{"status":"failed","artifacts":{},"x":"\xff"}',
        b"[]",
        b"null",
        b"{}",
        b'{"status":true,"artifacts":{}}',
        b'{"status":"error","artifacts":{}}',
        b'{"status":"ok","artifacts":{"build":"../escape","source_map":"source_map.json"}}',
        b'{"status":"failed","artifacts":{"build":"final.brep"}}',
        b'{"status":"ok","artifacts":{}}',
        b'{"status":"failed","artifacts":{}} {}',
    ],
)
def test_result_schema_json_and_artifact_agreement(tmp_path, data):
    reject(tmp_path, wire(result_bytes=data))


def test_nonbuild_cannot_export_artifacts(tmp_path):
    with pytest.raises(ValueError, match="unexpected artifacts"):
        transfer.export(io.BytesIO(), RESULT, NONCE, DFM_WORKER, tmp_path, CONTROL_STORAGE)


@pytest.mark.parametrize(
    "nonce,operation",
    [
        ("a", BUILD_WORKER),
        ("A" * 64, BUILD_WORKER),
        (True, BUILD_WORKER),
        (NONCE, "unknown"),
        (NONCE, []),
    ],
)
def test_constructor_and_writer_reject_identity(tmp_path, nonce, operation):
    with pytest.raises(ValueError):
        transfer.Receiver(tmp_path, nonce, operation, CONTROL_STORAGE)
    with pytest.raises(ValueError):
        transfer.export(io.BytesIO(), RESULT, nonce, operation, tmp_path, CONTROL_STORAGE)


def special(path, kind, outside):
    if kind == "symlink":
        path.symlink_to(outside)
    elif kind == "hardlink":
        os.link(outside, path)
    elif kind == "fifo":
        os.mkfifo(path)
    elif kind == "directory":
        path.mkdir()
    elif kind == "empty":
        path.touch()
    elif kind == "oversized":
        with path.open("wb") as stream:
            stream.truncate(CONTROL_STORAGE.input_bytes + CONTROL_STORAGE.export_bytes + 1)
    elif kind == "socket":
        # Darwin's sockaddr_un path limit is shorter than pytest's temp path.
        with tempfile.TemporaryDirectory(prefix="heph-xfer-", dir="/tmp") as short:
            leaf = Path(short) / "s"
            with socket.socket(socket.AF_UNIX) as sock:
                sock.bind(str(leaf))
            leaf.rename(path)
    elif kind != "missing":
        raise AssertionError(kind)


@pytest.mark.parametrize(
    "kind", ["symlink", "hardlink", "fifo", "directory", "empty", "oversized", "socket", "missing"]
)
def test_input_and_writer_special_files_refuse_before_output(tmp_path, kind):
    outside = tmp_path / "sentinel"
    outside.write_bytes(b"untouched")
    source, target = tmp_path / "source", tmp_path / "target"
    (source / "inputs").mkdir(parents=True)
    target.mkdir()
    special(source / "inputs" / INPUT, kind, outside)
    with pytest.raises((ValueError, OSError)):
        transfer.snapshot_inputs(source, (INPUT,), target, CONTROL_STORAGE)
    assert list(target.iterdir()) == []
    special(source / "final.brep", kind, outside)
    (source / "source_map.json").write_bytes(b"{}")
    stream = io.BytesIO()
    with pytest.raises((ValueError, OSError)):
        transfer.export(stream, RESULT, NONCE, BUILD_WORKER, source, CONTROL_STORAGE)
    assert stream.getvalue() == b""
    assert outside.read_bytes() == b"untouched"


@pytest.mark.parametrize(
    "name",
    [
        "../escape",
        "/source.brep",
        "x/y",
        "x\\y",
        "x\0",
        "\uff21" * 32 + ".brep",
        "",
        "final.brep",
        1,
    ],
)
def test_input_names_refuse(tmp_path, name):
    with pytest.raises(ValueError):
        transfer.snapshot_inputs(tmp_path, (name,), tmp_path, CONTROL_STORAGE)


def test_snapshot_admission_inventory_aggregate_and_count(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    area = source / "inputs"
    area.mkdir(parents=True)
    target.mkdir()
    (area / INPUT).write_bytes(b"1234")
    (area / "source.brep").write_bytes(b"5678")
    for names, policy in [
        ((), CONTROL_STORAGE),
        ((INPUT,), CONTROL_STORAGE),
        ((INPUT, INPUT), CONTROL_STORAGE),
        ((INPUT, "source.brep"), replace(CONTROL_STORAGE, input_files=1)),
        ((INPUT, "source.brep"), replace(CONTROL_STORAGE, input_bytes=7)),
    ]:
        with pytest.raises(ValueError):
            transfer.snapshot_inputs(source, names, target, policy)
        assert list(target.iterdir()) == []
    records = transfer.snapshot_inputs(
        source, (INPUT, "source.brep"), target, replace(CONTROL_STORAGE, input_bytes=8)
    )
    assert records[INPUT] == transfer.FileRecord(4, hashlib.sha256(b"1234").hexdigest())
    assert (target / INPUT).stat().st_mode & 0o777 == 0o444
    assert (target / "source.brep").read_bytes() == b"5678"


def test_empty_input_area_and_sidecars(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    source.mkdir()
    target.mkdir()
    assert transfer.snapshot_inputs(source, (), target, CONTROL_STORAGE) == {}
    (source / "inputs").mkdir()
    assert transfer.snapshot_inputs(source, (), target, CONTROL_STORAGE) == {}
    names = tuple(
        "a" * 32 + suffix for suffix in (".hmesh", ".hmesh.facts", ".hpts", ".hpts.facts")
    )
    for name in names:
        (source / "inputs" / name).write_bytes(b"input")
    assert set(transfer.snapshot_inputs(source, names, target, CONTROL_STORAGE)) == set(names)


@pytest.mark.parametrize("location", ["root", "ancestor", "area", "destination"])
def test_no_follow_directories(tmp_path, location):
    source, target = tmp_path / "source", tmp_path / "target"
    (source / "inputs").mkdir(parents=True)
    target.mkdir()
    (source / "inputs" / INPUT).write_bytes(b"input")
    link = tmp_path / "link"
    if location == "root":
        link.symlink_to(source, target_is_directory=True)
        source = link
    elif location == "ancestor":
        link.symlink_to(tmp_path, target_is_directory=True)
        source = link / "source"
    elif location == "area":
        (source / "inputs").rename(source / "actual")
        (source / "inputs").symlink_to(source / "actual", target_is_directory=True)
    else:
        link.symlink_to(target, target_is_directory=True)
        target = link
    with pytest.raises(OSError):
        transfer.snapshot_inputs(source, (INPUT,), target, CONTROL_STORAGE)
    assert list(target.iterdir()) == []
    if location in {"root", "ancestor", "destination"}:
        with pytest.raises(OSError):
            transfer.Receiver(
                source if location != "destination" else target,
                NONCE,
                BUILD_WORKER,
                CONTROL_STORAGE,
            )


def test_parent_path_and_regular_helper_escape(tmp_path):
    with pytest.raises(ValueError):
        transfer.open_directory(tmp_path / "..")
    fd = transfer.open_directory(tmp_path)
    try:
        for name in ("../escape", "/escape", "a/b", "a\\b", ".", "..", "a\0"):
            with pytest.raises(ValueError):
                transfer.open_regular(fd, name, 100)
    finally:
        os.close(fd)


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo", "directory", "empty"])
def test_exclusive_receiver_preserves_existing_targets(tmp_path, kind):
    target = tmp_path / "target"
    target.mkdir()
    sentinel = tmp_path / "sentinel"
    sentinel.write_bytes(b"sentinel")
    special(target / "source_map.json", kind, sentinel)
    with (
        transfer.Receiver(target, NONCE, BUILD_WORKER, CONTROL_STORAGE) as receiver,
        pytest.raises(FileExistsError),
    ):
        receiver.feed(wire())
    assert not (target / "final.brep").exists()
    assert os.path.lexists(target / "source_map.json")
    assert sentinel.read_bytes() == b"sentinel"


def test_install_collision_rolls_back_and_preserves_sentinel(tmp_path):
    target, dest = tmp_path / "target", tmp_path / "dest"
    target.mkdir()
    dest.mkdir()
    (dest / "source_map.json").write_bytes(b"sentinel")
    with transfer.Receiver(target, NONCE, BUILD_WORKER, CONTROL_STORAGE) as receiver:
        receiver.feed(wire())
        receiver.finish()
        with pytest.raises(FileExistsError):
            receiver.install(dest)
    assert list(target.iterdir()) == []
    assert sorted(p.name for p in dest.iterdir()) == ["source_map.json"]
    assert (dest / "source_map.json").read_bytes() == b"sentinel"


def test_install_refuses_tampered_collection(tmp_path):
    target, dest = tmp_path / "target", tmp_path / "dest"
    target.mkdir()
    dest.mkdir()
    with transfer.Receiver(target, NONCE, BUILD_WORKER, CONTROL_STORAGE) as receiver:
        receiver.feed(wire())
        receiver.finish()
        (target / "final.brep").write_bytes(b"changed")
        with pytest.raises(ValueError, match="changed"):
            receiver.install(dest)
    assert list(target.iterdir()) == list(dest.iterdir()) == []


def test_input_collision_and_midcopy_failure_rollback(tmp_path, monkeypatch):
    source, target = tmp_path / "source", tmp_path / "target"
    (source / "inputs").mkdir(parents=True)
    target.mkdir()
    for name in (INPUT, "source.brep"):
        (source / "inputs" / name).write_bytes(b"input")
    (target / "source.brep").write_bytes(b"sentinel")
    with pytest.raises(FileExistsError):
        transfer.snapshot_inputs(source, (INPUT, "source.brep"), target, CONTROL_STORAGE)
    assert not (target / INPUT).exists()
    assert (target / "source.brep").read_bytes() == b"sentinel"
    (target / "source.brep").unlink()
    original = transfer._write
    calls = 0

    def fail(stream, data):
        nonlocal calls
        calls += 1
        original(stream, data[:1])
        if calls == 2:
            raise OSError("injected disk failure")
        original(stream, data[1:])

    monkeypatch.setattr(transfer, "_write", fail)
    with pytest.raises(OSError, match="injected"):
        transfer.snapshot_inputs(source, (INPUT, "source.brep"), target, CONTROL_STORAGE)
    assert list(target.iterdir()) == []


def test_receiver_write_failure_cleans_prior_and_partial_files(tmp_path, monkeypatch):
    original = transfer._write
    calls = 0

    def fail(stream, data):
        nonlocal calls
        calls += 1
        original(stream, data[:1])
        if calls == 2:
            raise OSError("injected disk failure")
        original(stream, data[1:])

    monkeypatch.setattr(transfer, "_write", fail)
    with (
        transfer.Receiver(tmp_path, NONCE, BUILD_WORKER, CONTROL_STORAGE) as receiver,
        pytest.raises(OSError, match="injected"),
    ):
        receiver.feed(wire())
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("mutation", ["truncate", "grow", "same-size"])
def test_writer_collection_changes_never_emit_footer(tmp_path, mutation):
    source = source_dir(tmp_path)

    class ChangingStream(io.BytesIO):
        def write(self, data):
            if bytes(data) == BODIES["build"]:
                path = source / "final.brep"
                path.write_bytes(
                    {
                        "truncate": b"",
                        "grow": BODIES["build"] + b"X",
                        "same-size": b"x" * len(BODIES["build"]),
                    }[mutation]
                )
            return super().write(data)

    stream = ChangingStream()
    with pytest.raises(ValueError, match="changed"):
        transfer.export(stream, RESULT, NONCE, BUILD_WORKER, source, CONTROL_STORAGE)
    assert transfer.FOOTER not in stream.getvalue()
    target = tmp_path / "target"
    target.mkdir()
    with transfer.Receiver(target, NONCE, BUILD_WORKER, CONTROL_STORAGE) as receiver:
        receiver.feed(stream.getvalue())
        with pytest.raises(ValueError):
            receiver.finish()
    assert list(target.iterdir()) == []


def test_snapshot_detects_source_mutation_and_cleans(tmp_path, monkeypatch):
    area = tmp_path / "inputs"
    target = tmp_path / "target"
    area.mkdir()
    target.mkdir()
    (area / INPUT).write_bytes(b"input")
    original = transfer._write

    def mutate(stream, data):
        original(stream, data)
        (area / INPUT).write_bytes(b"changed")

    monkeypatch.setattr(transfer, "_write", mutate)
    with pytest.raises(ValueError, match="changed"):
        transfer.snapshot_inputs(tmp_path, (INPUT,), target, CONTROL_STORAGE)
    assert list(target.iterdir()) == []


@pytest.mark.parametrize("count", [0, None, -1, True, 1000000])
def test_invalid_stream_writes_fail(count, tmp_path):
    source = source_dir(tmp_path)

    class BadWriter(io.BytesIO):
        def write(self, data):
            return count

    stream = BadWriter()
    with pytest.raises(OSError):
        transfer.export(stream, RESULT, NONCE, BUILD_WORKER, source, CONTROL_STORAGE)
    assert not stream.closed


def test_short_writes_and_short_request_reads(tmp_path):
    class ShortStream(io.BytesIO):
        def write(self, data):
            return super().write(data[:1])

        def read(self, size=-1):
            return super().read(min(size, 1))

    stream = ShortStream()
    transfer.export(stream, RESULT, NONCE, BUILD_WORKER, source_dir(tmp_path), CONTROL_STORAGE)
    assert stream.getvalue() == wire()
    request = ShortStream(b'{"request":true}')
    assert transfer.read_job(request) == {"request": True}
    assert not request.closed


def test_request_bound_and_invalid_json(monkeypatch):
    monkeypatch.setattr(transfer, "REQUEST_MAX_BYTES", 16)
    for data in (b" " * 17, b'{"x":1,"x":2}', b""):
        with pytest.raises(ValueError):
            transfer.read_job(io.BytesIO(data))


def test_aggregate_export_and_wire_limits(tmp_path):
    source = source_dir(tmp_path)
    total = sum(map(len, BODIES.values()))
    policy = replace(CONTROL_STORAGE, export_bytes=total - 1)
    with pytest.raises(ValueError, match="aggregate"):
        transfer.export(io.BytesIO(), RESULT, NONCE, BUILD_WORKER, source, policy)
    reject(tmp_path, wire(), policy=policy)
    target = tmp_path / "small"
    target.mkdir()
    with (
        transfer.Receiver(target, NONCE, BUILD_WORKER, CONTROL_STORAGE) as receiver,
        pytest.raises(ValueError, match="wire limit"),
    ):
        receiver.feed(b"x" * (CONTROL_STORAGE.result_bytes + CONTROL_STORAGE.export_bytes + 5000))
    assert list(target.iterdir()) == []


def test_memory_bound_for_giant_feed_and_streaming_writer(tmp_path):
    # Body size is well above the asserted peak. Prepare fixture BEFORE tracing.
    body = b"x" * (4 * 1024**2)
    bodies = {"build": body, "source_map": b"{}"}
    data = wire(bodies=bodies)
    source = source_dir(tmp_path)
    (source / "final.brep").write_bytes(body)
    target = tmp_path / "target"
    target.mkdir()
    tracemalloc.start()
    try:
        with transfer.Receiver(target, NONCE, BUILD_WORKER, DEFAULT_STORAGE) as receiver:
            receiver.feed(data)
            receiver.finish()
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 512 * 1024, peak

    class Sink:
        largest = 0
        total = 0

        def write(self, chunk):
            self.largest = max(self.largest, len(chunk))
            self.total += len(chunk)
            return len(chunk)

        def flush(self):
            pass

    sink = Sink()
    tracemalloc.start()
    try:
        transfer.export(sink, RESULT, NONCE, BUILD_WORKER, source, DEFAULT_STORAGE)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 512 * 1024, peak
    assert sink.largest <= transfer.CHUNK_SIZE
    assert sink.total > len(body)


def test_post_eof_feed_and_explicit_close_remove_outputs(tmp_path):
    receiver = transfer.Receiver(tmp_path, NONCE, BUILD_WORKER, CONTROL_STORAGE)
    receiver.feed(wire())
    receiver.finish()
    with pytest.raises(ValueError, match="EOF"):
        receiver.feed(b"trailing")
    assert list(tmp_path.iterdir()) == []
    receiver.close()
    with pytest.raises(ValueError, match="closed"):
        receiver.finish()


@pytest.mark.parametrize("value", [0, -1, True, 1.0, 129])
def test_policy_rejects_invalid_or_widened_bounds(value):
    with pytest.raises(ValueError):
        StoragePolicy(input_files=value)


def test_json_writer_bounds_and_constants():
    cycle = []
    cycle.append(cycle)
    for value in (cycle, {"x": float("nan")}, {"x": "x" * 100}, {1: "x"}, {"x": (1, 2)}):
        with pytest.raises(ValueError):
            transfer.encode(value, 64)
    with pytest.raises(ValueError, match="entry limit"):
        transfer.unique_json(b"[" + b"0," * transfer.JSON_NODES_MAX + b"0]")


def test_snapshot_memory_bound_and_empty_destination_requirement(tmp_path):
    area, target = tmp_path / "inputs", tmp_path / "target"
    area.mkdir()
    target.mkdir()
    (area / INPUT).write_bytes(b"x" * (4 * 1024**2))
    tracemalloc.start()
    try:
        transfer.snapshot_inputs(tmp_path, (INPUT,), target, DEFAULT_STORAGE)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 512 * 1024, peak
    # Even zero declarations may not expose arbitrary preexisting host files.
    with pytest.raises(FileExistsError):
        transfer.snapshot_inputs(tmp_path, (), target, CONTROL_STORAGE)


def test_cleanup_attempts_every_leaf_and_reports_uncertainty(tmp_path, monkeypatch):
    receiver = transfer.Receiver(tmp_path, NONCE, BUILD_WORKER, CONTROL_STORAGE)
    receiver.feed(wire())
    original = os.unlink
    attempted = []

    def fail_one(name, *, dir_fd=None):
        attempted.append(name)
        if name == "final.brep":
            raise PermissionError("injected unlink refusal")
        original(name, dir_fd=dir_fd)

    with monkeypatch.context() as patch:
        patch.setattr(transfer.os, "unlink", fail_one)
        with pytest.raises(ExceptionGroup, match="cleanup incomplete"):
            receiver.close()
    assert attempted == ["final.brep", "source_map.json"]
    assert not (tmp_path / "source_map.json").exists()
    assert (tmp_path / "final.brep").exists()
    with pytest.raises(OSError):
        os.fstat(receiver.dirfd)
    # Explicit caller reconciliation of this exact owned residual, not a pass.
    (tmp_path / "final.brep").unlink()


def test_cancellation_during_feed_also_cleans(tmp_path, monkeypatch):
    def interrupted(stream, data):
        stream.write(data[:1])
        raise KeyboardInterrupt

    monkeypatch.setattr(transfer, "_write", interrupted)
    receiver = transfer.Receiver(tmp_path, NONCE, BUILD_WORKER, CONTROL_STORAGE)
    with pytest.raises(KeyboardInterrupt):
        receiver.feed(wire())
    assert list(tmp_path.iterdir()) == []
    assert receiver.closed


def test_open_regular_rejects_character_device():
    fd = transfer.open_directory(Path("/dev"))
    try:
        with pytest.raises(ValueError, match="regular file"):
            transfer.open_regular(fd, "null", 1024)
    finally:
        os.close(fd)


@pytest.mark.parametrize("version", [0, 2, 255])
def test_incompatible_transfer_versions_reject(tmp_path, version):
    data = wire()
    reject(tmp_path, data[:8] + bytes([version]) + data[9:])


def test_source_map_specific_limit_and_result_writer_limit(tmp_path):
    header = header_for_wire()
    header["artifacts"][1]["length"] = transfer.LIMITS["source_map"] + 1
    reject(tmp_path, wire(header=header), policy=DEFAULT_STORAGE)
    source = source_dir(tmp_path)
    stream = io.BytesIO()
    with pytest.raises(ValueError):
        transfer.export(
            stream, RESULT, NONCE, BUILD_WORKER, source, replace(CONTROL_STORAGE, result_bytes=16)
        )
    assert stream.getvalue() == b""


def test_invalid_request_stream_does_not_imply_eof():
    class Blocked(io.BytesIO):
        def read(self, size=-1):
            return None

    with pytest.raises(ValueError, match="blocked"):
        transfer.read_job(Blocked())


def test_truncated_file_after_admission_and_fd_cleanup(tmp_path, monkeypatch):
    source = source_dir(tmp_path)
    original = transfer.open_regular
    opened = []

    def truncate_after_admission(fd, name, maximum):
        stream, info = original(fd, name, maximum)
        opened.append(stream)
        if name == "source_map.json":
            (source / "final.brep").write_bytes(b"")
        return stream, info

    monkeypatch.setattr(transfer, "open_regular", truncate_after_admission)
    stream = io.BytesIO()
    with pytest.raises(ValueError, match="truncated"):
        transfer.export(stream, RESULT, NONCE, BUILD_WORKER, source, CONTROL_STORAGE)
    assert all(item.closed for item in opened)
    assert transfer.FOOTER not in stream.getvalue()


def test_active_profile_versions_the_integrated_storage_contract():
    assert (PROTOCOL_VERSION, MANIFEST_VERSION, OCI_PROFILE_VERSION) == (3, 4, 5)
    assert OCI_TMPFS_BYTES == 16 * 1024**2
    assert {BUILD_WORKER, DFM_WORKER, PROBE_WORKER, STORAGE_WORKER} == APPROVED_MODULES
    assert "storage_quotas" in REQUIRED_OCI_FEATURES
    assert manifest_record()["artifact_transfer_version"] == 1
    assert manifest_record()["log_driver"] == "none"
    assert set(manifest_record()["storage"]) == {"ordinary", "control"}
    assert approved_module_for_worker_args(("-m", STORAGE_WORKER)) == STORAGE_WORKER
