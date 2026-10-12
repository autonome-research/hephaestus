"""Fixed stdlib-only storage controls; never executes caller code or paths.

The launcher, quotas, PID1 exec, input snapshot and framed exporter are exactly
those used by build/DFM. Synthetic .brep bytes are NOT kernel geometry.
"""

from __future__ import annotations

import hashlib
import io
import os
import struct
import sys
from pathlib import Path

from .oci_protocol import PROTOCOL_VERSION
from .oci_storage import capacity, observe_storage
from .oci_storage_policy import CONTROL_STORAGE, STORAGE_OPERATIONS, STORAGE_WORKER
from .oci_transfer import MAGIC, Json, export, unique_json
from .oci_worker_io import worker_io

INPUT = b"hephaestus storage input v1\n" * 37
OUTPUT = b"SYNTHETIC NOT CAD\n" * 1024
SOURCE_MAP = b'{"synthetic":true}\n'


def exhaust(path: str, *, inodes: bool) -> dict[str, Json]:
    before = capacity(path)
    target = Path(path)
    allocated = 0
    code = 0
    names: list[Path] = []
    try:
        if inodes:
            for index in range(before["inodes"] + 2):
                leaf = target / f".heph-inode-{index}"
                try:
                    with leaf.open("xb"):
                        pass
                except OSError as exc:
                    code = int(exc.errno or -1)
                    break
                names.append(leaf)
                allocated += 1
        else:
            leaf = target / ".heph-byte-test"
            with leaf.open("xb", buffering=0) as stream:
                names.append(leaf)
                chunk = bytes(range(256)) * 256
                # Real writes, not truncate/seek/fallocate: no sparse-file proof.
                for _ in range(before["bytes"] // len(chunk) + 2):
                    try:
                        count = stream.write(chunk)
                    except OSError as exc:
                        code = int(exc.errno or -1)
                        break
                    if type(count) is not int or not 0 < count <= len(chunk):
                        raise ValueError("invalid write count")
                    allocated += count
        exhausted = capacity(path)
    finally:
        for leaf in names:
            leaf.unlink()
    restored = capacity(path)
    recovery = target / ".heph-recovery"
    with recovery.open("xb") as stream:
        stream.write(b"recovered")
    recovery.unlink()
    return {
        "path": path,
        "kind": "inodes" if inodes else "bytes",
        "before": {**before},
        "exhausted": {**exhausted},
        "restored": {**restored},
        "allocated": allocated,
        "errno": code,
        "recovery": True,
    }


def main() -> int:
    transport = worker_io()
    if transport is None or transport.policy != CONTROL_STORAGE:
        raise ValueError("storage controls require fixed control policy")
    job = transport.read()
    if (
        set(job) != {"protocol_version", "operation"}
        or type(job["protocol_version"]) is not int
        or job["protocol_version"] != PROTOCOL_VERSION
        or job["operation"] not in STORAGE_OPERATIONS
    ):
        raise ValueError("invalid storage control request")
    operation = job["operation"]
    result: dict[str, Json] = {
        "status": "failed",
        "artifacts": {},
        "operation": operation,
        "storage": observe_storage(),
        "pid": os.getpid(),
    }
    if operation == "positive":
        source = Path("/inputs/source.brep")
        data = source.read_bytes()  # snapshot is admitted at 64 KiB aggregate
        if data != INPUT:
            raise ValueError("deterministic input mismatch")
        try:
            with source.open("wb"):
                pass
        except OSError as exc:
            result["input_write_errno"] = exc.errno
        else:
            raise ValueError("input unexpectedly writable")
        result["input_sha256"] = hashlib.sha256(data).hexdigest()
        result["input_bytes"] = len(data)
        Path("/work/final.brep").write_bytes(OUTPUT)
        Path("/work/source_map.json").write_bytes(SOURCE_MAP)
        result.update(
            status="ok", artifacts={"build": "final.brep", "source_map": "source_map.json"}
        )
    elif operation in {"work-bytes", "tmp-bytes", "work-inodes", "tmp-inodes"}:
        result["exhaustion"] = exhaust(
            "/work" if operation.startswith("work") else "/tmp", inodes=operation.endswith("inodes")
        )
    elif operation == "finite-stderr":
        sys.stderr.buffer.write(b"bounded storage diagnostic\n" * 256)
        sys.stderr.buffer.flush()
    if operation in {"partial-body", "artifact-truncated-footer", "stdout-overflow"}:
        Path("/work/last_good.brep").write_bytes(OUTPUT)
        result["artifacts"] = {"last_good": "last_good.brep"}
    if operation in {
        "truncated",
        "bad-digest",
        "trailing",
        "oversized-header",
        "partial-body",
        "artifact-truncated-footer",
        "stdout-overflow",
    }:
        stream = io.BytesIO()
        export(stream, result, transport.nonce, STORAGE_WORKER, Path("/work"), transport.policy)
        wire = stream.getvalue()
        if operation in {"truncated", "artifact-truncated-footer"}:
            wire = wire[:-1]
        elif operation == "partial-body":
            prefix = len(MAGIC) + 4
            header_end = prefix + struct.unpack("!I", wire[len(MAGIC) : prefix])[0]
            header = unique_json(wire[prefix:header_end])
            assert isinstance(header, dict)
            result_length = header["result_length"]
            assert type(result_length) is int
            wire = wire[: header_end + result_length + len(OUTPUT) // 2]
        elif operation == "stdout-overflow":
            # Finite 384 KiB, above the 328 KiB control attach ceiling. Real
            # artifact precedes overflow, so rejection must remove collected IO.
            wire += b"x" * (384 * 1024 - len(wire))
        elif operation == "bad-digest":
            wire = wire[:-1] + bytes([wire[-1] ^ 1])
        elif operation == "trailing":
            wire += b"x"
        else:
            wire = MAGIC + struct.pack("!I", 4097)
        sys.stdout.buffer.write(wire)
        sys.stdout.buffer.flush()
    else:
        transport.send(result, STORAGE_WORKER)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
