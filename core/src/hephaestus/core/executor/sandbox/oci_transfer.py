"""Stdlib-only framing and input snapshots for experimental OCI profile 4.

Wire: magic/version, big-endian u32 header length, closed JSON header, result
JSON, ordered artifact bodies, footer and SHA256 of everything before footer,
then EOF. No archives, paths, metadata, compression or provenance claims.

Caller supplies private host-owned directories (no concurrent host writers),
feeds bounded transport chunks, and calls finish ONLY at observed EOF. Successful
finish is transport validation, not permission to publish: terminal/OOM/cleanup
and result-schema/provenance gates remain the integrator's responsibility.
Close aborts/removes collected files unless explicitly installed. No stream
passed by the caller is closed here. Blocking streams only; partial writes work.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
import re
import stat
import struct
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import BinaryIO, Protocol, Self, TypeAlias, cast

from .oci_protocol import BUILD_WORKER, DFM_WORKER, PROBE_WORKER
from .oci_storage_policy import (
    ARTIFACT_TRANSFER_VERSION,
    REQUEST_MAX_BYTES,
    STORAGE_WORKER,
    StoragePolicy,
)

Json: TypeAlias = "bool | int | float | str | list[Json] | dict[str, Json] | None"
MAGIC = b"HEPHXFER" + bytes([ARTIFACT_TRANSFER_VERSION])
FOOTER = b"HEPHDONE"
HEADER_MAX = 4096
CHUNK_SIZE = 65536
JSON_NODES_MAX = 65536
NAMES = {"build": "final.brep", "source_map": "source_map.json", "last_good": "last_good.brep"}
LIMITS = {"build": 64 * 1024**2, "last_good": 64 * 1024**2, "source_map": 8 * 1024**2}
# Render-only operation uses bounded result JSON and zero artifact bodies. This
# extends transfer v1 without changing its grammar; the separate renderer
# manifest/launcher is the authority. The CAD worker allowlist is unchanged.
OPERATIONS = frozenset(
    {BUILD_WORKER, DFM_WORKER, PROBE_WORKER, STORAGE_WORKER, "hephaestus.core.render.oci_worker"}
)
INPUT_RE = re.compile(
    r"(?:[0-9a-f]{32}\.(?:brep|hmesh(?:\.facts)?|hpts(?:\.facts)?)|source\.brep)", re.ASCII
)


def unique_json(data: bytes) -> Json:
    """Bound nesting/container entries before the recursive decoder allocates."""

    def unique(pairs: list[tuple[str, Json]]) -> dict[str, Json]:
        result: dict[str, Json] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def invalid(_: str) -> Json:
        raise ValueError("invalid JSON constant")

    def finite(text: str) -> float:
        value = float(text)
        if not math.isfinite(value):
            raise ValueError("non-finite JSON number")
        return value

    if not 0 < len(data) <= REQUEST_MAX_BYTES:
        raise ValueError("JSON byte limit")
    depth = nodes = 0
    quoted = escaped = False
    for c in data:
        if quoted:
            if escaped:
                escaped = False
            elif c == 92:
                escaped = True
            elif c == 34:
                quoted = False
        elif c == 34:
            quoted = True
        elif c in (91, 123):
            depth += 1
            nodes += 1
            if depth > 32:
                raise ValueError("JSON nesting exceeds bound")
        elif c in (93, 125):
            depth -= 1
        elif c in (44, 58):
            nodes += 1
        if nodes > JSON_NODES_MAX:
            raise ValueError("JSON entry limit")
    # Explicit UTF-8 prevents json.loads accepting UTF-16/32 or BOM encodings.
    return cast(
        Json,
        json.loads(
            data.decode("utf-8"),
            object_pairs_hook=unique,
            parse_constant=invalid,
            parse_float=finite,
        ),
    )


def encode(value: object, maximum: int = REQUEST_MAX_BYTES) -> bytes:
    # Reject huge/cyclic caller objects before JSON serialization. Bounds apply
    # to both sides, even though the writer ordinarily runs in a trusted worker.
    budget = maximum
    nodes = 0

    def check(item: object, depth: int) -> None:
        nonlocal budget, nodes
        nodes += 1
        budget -= 1
        if depth > 32 or nodes > JSON_NODES_MAX or budget < 0:
            raise ValueError("JSON object exceeds bound")
        if isinstance(item, str):
            budget -= len(item)
        elif isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str):
                    raise ValueError("JSON keys must be strings")
                check(key, depth + 1)
                check(child, depth + 1)
        elif isinstance(item, list):
            for child in item:
                check(child, depth + 1)
        elif item is not None and type(item) not in (bool, int, float):
            raise ValueError("invalid JSON type")
        if budget < 0:
            raise ValueError("JSON object exceeds bound")

    check(value, 0)
    data = bytearray()
    for text in json.JSONEncoder(sort_keys=True, separators=(",", ":"), allow_nan=False).iterencode(
        value
    ):
        chunk = text.encode("utf-8")
        if len(data) + len(chunk) + 1 > maximum:
            raise ValueError("JSON byte limit")
        data.extend(chunk)
    data.extend(b"\n")
    # Writer and reader share the same structural/encoding limits.
    unique_json(bytes(data))
    return bytes(data)


def _identity(nonce: object, operation: object) -> tuple[str, str]:
    if not isinstance(nonce, str) or re.fullmatch(r"[0-9a-f]{64}", nonce) is None:
        raise ValueError("invalid nonce")
    if not isinstance(operation, str) or operation not in OPERATIONS:
        raise ValueError("unknown transfer operation")
    return nonce, operation


def input_name(name: object) -> str:
    if not isinstance(name, str) or INPUT_RE.fullmatch(name) is None:
        raise ValueError("invalid staged input leaf")
    return name


def open_directory(path: Path) -> int:
    """Refuse symlinks in EVERY path component, not merely the final one."""
    if ".." in path.parts:
        raise ValueError("parent path component")
    fd = os.open("/" if path.is_absolute() else ".", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in path.parts:
            if component in ("/", "."):
                continue
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def open_regular(
    directory_fd: int, name: object, maximum: int, *, allow_empty: bool = False
) -> tuple[BinaryIO, os.stat_result]:
    if (
        not isinstance(name, str)
        or not name
        or name in {".", ".."}
        or any(c in name for c in "/\\\0")
    ):
        raise ValueError("invalid leaf")
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or not (0 if allow_empty else 1) <= info.st_size <= maximum
        ):
            raise ValueError("not a bounded singly linked regular file")
        return os.fdopen(fd, "rb", buffering=0), info
    except BaseException:
        os.close(fd)
        raise


def _signature(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_nlink,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _collect(source: BinaryIO, info: os.stat_result) -> Iterator[bytes]:
    left = info.st_size
    while left:
        chunk = source.read(min(left, CHUNK_SIZE))
        if not chunk or len(chunk) > left:
            raise ValueError("file truncated or invalid read")
        left -= len(chunk)
        yield chunk
    if source.read(1) or _signature(os.fstat(source.fileno())) != _signature(info):
        raise ValueError("file changed during collection")


class WriteStream(Protocol):
    """Transport streams may block or return malformed counts; validate each write."""

    def write(self, data: memoryview, /) -> object: ...
    def flush(self) -> None: ...


class ReadStream(Protocol):
    def read(self, size: int, /) -> object: ...


def write_all(stream: WriteStream, data: bytes | memoryview) -> None:
    view = memoryview(data)
    while view:
        count = stream.write(view)
        if type(count) is not int or not 0 < count <= len(view):
            raise OSError("invalid/blocked stream write")
        view = view[count:]


def _exclusive(directory_fd: int, name: str, mode: int = 0o600) -> BinaryIO:
    fd = os.open(
        name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode, dir_fd=directory_fd
    )
    try:
        return os.fdopen(fd, "wb", buffering=0)
    except BaseException:
        os.close(fd)
        os.unlink(name, dir_fd=directory_fd)
        raise


def _unlink_all(directory_fd: int, names: list[str]) -> None:
    # Attempt every owned leaf even if one removal fails; never report success
    # on cleanup uncertainty. No broad directory removal or swallowed errors.
    failures: list[OSError] = []
    for name in names:
        try:
            os.unlink(name, dir_fd=directory_fd)
        except OSError as exc:
            failures.append(exc)
    if failures:
        raise ExceptionGroup("transfer cleanup incomplete", failures)


@dataclass(frozen=True)
class FileRecord:
    length: int
    sha256: str


def snapshot_inputs(
    out_dir: Path, names: tuple[object, ...], destination: Path, policy: StoragePolicy
) -> dict[str, FileRecord]:
    """Admit ALL sources before writing; rollback only exclusively owned leaves.

    Source inventory and aggregate are bounded, including the empty declaration.
    Destination is caller-owned and must not be mounted until this returns.
    This bounds the snapshot, NOT earlier staging by import/DFM callers.
    """
    if type(names) is not tuple or len(names) > policy.input_files:
        raise ValueError("input count/type")
    names = tuple(input_name(name) for name in names)
    if len(set(names)) != len(names):
        raise ValueError("duplicate input declaration")
    with contextlib.ExitStack() as stack:
        root = open_directory(out_dir)
        stack.callback(os.close, root)
        destfd = open_directory(destination)
        stack.callback(os.close, destfd)
        # Mounting a nonempty destination could expose undeclared host files.
        # Inspect only one entry, never allocate an unbounded directory listing.
        with os.scandir(destfd) as entries:
            if next(entries, None) is not None:
                raise FileExistsError("input snapshot destination is not empty")
        try:
            area = os.open("inputs", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
        except FileNotFoundError:
            if names:
                raise
            return {}
        stack.callback(os.close, area)
        seen: set[str] = set()
        with os.scandir(area) as entries:
            for entry in entries:
                if entry.name not in names or entry.name in seen:
                    raise ValueError("undeclared staged input")
                seen.add(entry.name)
        if seen != set(names):
            raise ValueError("missing staged input")
        sources: list[tuple[str, BinaryIO, os.stat_result]] = []
        total = 0
        for name in names:
            source, info = open_regular(area, name, policy.input_bytes)
            stack.enter_context(source)
            total += info.st_size
            if total > policy.input_bytes:
                raise ValueError("aggregate input limit")
            sources.append((name, source, info))
        created: list[str] = []
        records: dict[str, FileRecord] = {}
        try:
            for name, source, info in sources:
                target = _exclusive(destfd, name, 0o444)
                created.append(name)
                digest = hashlib.sha256()
                with target:
                    for chunk in _collect(source, info):
                        write_all(target, chunk)
                        digest.update(chunk)
                copied, copied_info = open_regular(destfd, name, policy.input_bytes)
                check = hashlib.sha256()
                with copied:
                    for chunk in _collect(copied, copied_info):
                        check.update(chunk)
                if copied_info.st_size != info.st_size or check.digest() != digest.digest():
                    raise ValueError("input copy mismatch")
                records[name] = FileRecord(info.st_size, check.hexdigest())
            return records
        except BaseException:
            _unlink_all(destfd, created)
            raise


class InputAdmission:
    """Per-job pre-write aggregate admission, including converted sidecars.

    Caller owns a fresh staging directory. No recursive copy, overwrite or
    post-write quota guess; snapshot_inputs independently rechecks on dispatch.
    """

    def __init__(self, policy: StoragePolicy) -> None:
        self.policy = policy
        self.names: dict[str, FileRecord] = {}

    def write(self, directory: Path, files: Mapping[str, object]) -> None:
        records: dict[str, FileRecord] = {}
        admitted: dict[str, bytes] = {}
        for name, data in files.items():
            input_name(name)
            if not isinstance(data, bytes) or not 0 < len(data) <= self.policy.input_bytes:
                raise ValueError("input byte limit")
            admitted[name] = data
            records[name] = FileRecord(len(data), hashlib.sha256(data).hexdigest())
            if name in self.names and self.names[name] != records[name]:
                raise ValueError("staged input identity collision")
        merged = self.names | records
        if (
            len(merged) > self.policy.input_files
            or sum(r.length for r in merged.values()) > self.policy.input_bytes
        ):
            raise ValueError("aggregate staged input limit")
        directory.mkdir(mode=0o700, exist_ok=True)
        fd = open_directory(directory)
        created: list[str] = []
        try:
            for name, data in admitted.items():
                if name in self.names:
                    continue
                target = _exclusive(fd, name, 0o444)
                created.append(name)
                with target:
                    write_all(target, data)
            self.names = merged
        except BaseException:
            _unlink_all(fd, created)
            raise
        finally:
            os.close(fd)


def artifact_ids(result: object, operation: str) -> list[str]:
    if not isinstance(result, dict):
        raise ValueError("result must be an object")
    if operation not in OPERATIONS:
        raise ValueError("unknown operation")
    if operation not in {BUILD_WORKER, STORAGE_WORKER}:
        if result.get("artifacts", {}) != {}:
            raise ValueError("unexpected artifacts")
        return []
    artifacts = result.get("artifacts")
    status = result.get("status")
    if not isinstance(artifacts, dict) or status not in ("ok", "failed"):
        raise ValueError("artifact mapping/status missing or invalid")
    allowed = {"build", "source_map"} if status == "ok" else set(artifacts)
    if status == "failed" and allowed not in (set(), {"last_good"}):
        raise ValueError("invalid failure artifacts")
    if set(artifacts) != allowed or any(artifacts[k] != NAMES.get(k) for k in artifacts):
        raise ValueError("artifact/result disagreement")
    return sorted(artifacts)


class _TransferSchema:
    """Internal framing adapter, NOT an execution/worker admission registry.

    The public CAD entrypoints always use this closed schema. Development
    preparation reuses only the byte/file machinery with its own closed schema.
    """

    header_max = HEADER_MAX
    file_count = 2

    def identity(self, nonce: object, operation: object) -> tuple[str, str]:
        return _identity(nonce, operation)

    def ids(self, result: object, operation: str) -> list[str]:
        return artifact_ids(result, operation)

    def name(self, ident: str) -> str:
        return NAMES[ident]

    def limit(self, ident: str) -> int:
        if ident not in LIMITS:
            raise ValueError("unknown artifact id")
        return LIMITS[ident]


class _TransferBounds(Protocol):
    @property
    def result_bytes(self) -> int: ...
    @property
    def export_bytes(self) -> int: ...


_CAD_SCHEMA = _TransferSchema()


def export(
    stream: WriteStream,
    result: object,
    nonce: object,
    operation: object,
    directory: Path,
    policy: StoragePolicy,
) -> None:
    """Admit before sending; a collection/write error deliberately has no footer."""
    _export(stream, result, nonce, operation, directory, policy, _CAD_SCHEMA)


def _export(
    stream: WriteStream,
    result: object,
    nonce: object,
    operation: object,
    directory: Path,
    policy: _TransferBounds,
    schema: _TransferSchema,
) -> None:
    nonce, operation = schema.identity(nonce, operation)
    data = encode(result, policy.result_bytes)
    ids = schema.ids(result, operation)
    if len(ids) > schema.file_count or len(ids) != len(set(ids)):
        raise ValueError("artifact count/duplicates")
    with contextlib.ExitStack() as stack:
        directory_fd = open_directory(directory)
        stack.callback(os.close, directory_fd)
        files: list[tuple[str, BinaryIO, os.stat_result]] = []
        for ident in ids:
            source, info = open_regular(
                directory_fd, schema.name(ident), min(schema.limit(ident), policy.export_bytes)
            )
            stack.enter_context(source)
            files.append((ident, source, info))
        if sum(info.st_size for _, _, info in files) > policy.export_bytes:
            raise ValueError("aggregate export limit")
        header = encode(
            {
                "nonce": nonce,
                "operation": operation,
                "result_length": len(data),
                "artifacts": [{"id": ident, "length": info.st_size} for ident, _, info in files],
            },
            schema.header_max,
        )
        digest = hashlib.sha256()

        def send(chunk: bytes) -> None:
            write_all(stream, chunk)
            digest.update(chunk)

        send(MAGIC + struct.pack("!I", len(header)))
        send(header)
        send(data)
        for _, source, info in files:
            for chunk in _collect(source, info):
                send(chunk)
        write_all(stream, FOOTER + digest.digest())
        stream.flush()


@dataclass(frozen=True)
class _Descriptor:
    ident: str
    length: int


class _Receiver:
    """Single-use incremental receiver; errors poison it and remove partials.

    feed never copies a complete transport chunk: even a single giant feed has
    only CHUNK_SIZE transient body memory. Result JSON is separately bounded.
    finish declares EOF; close is idempotent and must always be called.
    """

    def __init__(
        self,
        directory: Path,
        nonce: object,
        operation: object,
        policy: _TransferBounds,
        schema: _TransferSchema,
    ) -> None:
        nonce, operation = schema.identity(nonce, operation)
        self.schema = schema
        self.nonce, self.operation, self.policy = nonce, operation, policy
        self.dirfd = open_directory(directory)
        self.buffer = bytearray()
        self.digest = hashlib.sha256()
        self.state = "prefix"
        self.need = len(MAGIC) + 4
        self.result = bytearray()
        self.descriptors: list[_Descriptor] = []
        self.files: dict[str, FileRecord] = {}
        self.created: list[str] = []
        self.target: BinaryIO | None = None
        self.file_hash = hashlib.sha256()
        self.index = 0
        self.total = 0
        self.body_bytes = 0
        self.finished = False
        self.installed = False
        self.closed = False

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def _abort(self) -> None:
        self.state = "failed"
        self.close()

    def feed(self, chunk: object) -> None:
        if self.closed:
            raise ValueError("receiver closed")
        try:
            if self.finished or not isinstance(chunk, bytes):
                raise ValueError("feed after EOF or invalid chunk type")
            self.total += len(chunk)
            if (
                self.total
                > self.policy.result_bytes
                + self.policy.export_bytes
                + self.schema.header_max
                + len(MAGIC)
                + 4
                + len(FOOTER)
                + 32
            ):
                raise ValueError("wire limit")
            view = memoryview(chunk)
            while view:
                if self.state == "done":
                    raise ValueError("trailing transfer bytes")
                count = min(self.need, len(view), CHUNK_SIZE)
                part = view[:count]
                view = view[count:]
                if self.state != "footer":
                    self.digest.update(part)
                if self.state == "result":
                    self.result.extend(part)
                elif self.state == "body":
                    if self.target is None:
                        raise ValueError("missing artifact target")
                    write_all(self.target, part)
                    self.body_bytes += len(part)
                    self.file_hash.update(part)
                else:
                    self.buffer.extend(part)
                self.need -= count
                if self.need == 0:
                    self._advance()
        except BaseException:
            self._abort()
            raise

    def _advance(self) -> None:
        part = bytes(self.buffer)
        self.buffer.clear()
        if self.state == "prefix":
            if part[: len(MAGIC)] != MAGIC:
                raise ValueError("transfer version/magic mismatch")
            self.need = struct.unpack("!I", part[-4:])[0]
            if not 0 < self.need <= self.schema.header_max:
                raise ValueError("header length exceeds bound")
            self.state = "header"
        elif self.state == "header":
            self._header(part)
        elif self.state == "footer":
            if part != FOOTER + self.digest.digest():
                raise ValueError("completion digest mismatch")
            self.state = "done"
        else:
            if self.state == "result":
                ids = self.schema.ids(unique_json(bytes(self.result)), self.operation)
                if ids != [d.ident for d in self.descriptors]:
                    raise ValueError("artifact set/order disagreement")
            else:
                if self.target is None:
                    raise ValueError("missing artifact target")
                self.target.close()
                self.target = None
                desc = self.descriptors[self.index - 1]
                self.files[desc.ident] = FileRecord(desc.length, self.file_hash.hexdigest())
            self._next_body()

    def _header(self, part: bytes) -> None:
        header = unique_json(part)
        if not isinstance(header, dict) or set(header) != {
            "nonce",
            "operation",
            "result_length",
            "artifacts",
        }:
            raise ValueError("invalid header schema")
        if header["nonce"] != self.nonce or header["operation"] != self.operation:
            raise ValueError("transfer identity mismatch")
        length = header["result_length"]
        if type(length) is not int or not 0 < length <= self.policy.result_bytes:
            raise ValueError("result length exceeds bound")
        descriptors = header["artifacts"]
        if not isinstance(descriptors, list) or len(descriptors) > self.schema.file_count:
            raise ValueError("artifact count")
        seen: set[str] = set()
        total = 0
        for desc in descriptors:
            if not isinstance(desc, dict) or set(desc) != {"id", "length"}:
                raise ValueError("artifact descriptor")
            ident, size = desc["id"], desc["length"]
            if not isinstance(ident, str) or ident in seen:
                raise ValueError("unknown/duplicate artifact id")
            maximum = self.schema.limit(ident)
            if type(size) is not int or not 0 < size <= maximum:
                raise ValueError("artifact length exceeds bound")
            seen.add(ident)
            total += size
            self.descriptors.append(_Descriptor(ident, size))
        if total > self.policy.export_bytes:
            raise ValueError("aggregate export limit")
        self.state, self.need = "result", length

    def _next_body(self) -> None:
        if self.index == len(self.descriptors):
            self.state, self.need = "footer", len(FOOTER) + 32
            return
        desc = self.descriptors[self.index]
        self.index += 1
        name = self.schema.name(desc.ident)
        self.target = _exclusive(self.dirfd, name)
        self.created.append(name)
        self.file_hash = hashlib.sha256()
        self.state, self.need = "body", desc.length

    def finish(self) -> bytes:
        if self.closed:
            raise ValueError("receiver closed")
        try:
            if self.state != "done":
                raise ValueError("truncated transfer")
            self.finished = True
            return bytes(self.result)
        except BaseException:
            self._abort()
            raise

    def install(self, destination: Path) -> None:
        """Exclusive same-filesystem installation AFTER caller's external gates.

        Private host directories must remain under sole caller control. No
        cross-filesystem copy fallback and no replacement of existing leaves.
        """
        if self.closed or not self.finished or self.installed:
            raise ValueError("installation requires finished, uninstalled transfer")
        installed: list[str] = []
        fd: int | None = None
        try:
            fd = open_directory(destination)
            # Revalidate collected bytes before making any destination visible.
            for ident, record in self.files.items():
                source, info = open_regular(
                    self.dirfd, self.schema.name(ident), self.schema.limit(ident)
                )
                digest = hashlib.sha256()
                with source:
                    for chunk in _collect(source, info):
                        digest.update(chunk)
                if info.st_size != record.length or digest.hexdigest() != record.sha256:
                    raise ValueError("collected artifact changed")
            for ident in self.files:
                name = self.schema.name(ident)
                os.link(name, name, src_dir_fd=self.dirfd, dst_dir_fd=fd, follow_symlinks=False)
                installed.append(name)
            # Keep source links until close; no fallible source-unlink step can
            # produce a partially installed set. Caller closes before publishing.
            self.installed = True
        except BaseException:
            try:
                if fd is not None:
                    _unlink_all(fd, installed)
            finally:
                self._abort()
            raise
        finally:
            if fd is not None:
                os.close(fd)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            try:
                if self.target is not None:
                    self.target.close()
            finally:
                _unlink_all(self.dirfd, self.created)
        finally:
            os.close(self.dirfd)
            self.buffer.clear()
            self.result.clear()


class Receiver(_Receiver):
    """CAD receiver: callers cannot supply a wider schema or worker allowlist."""

    def __init__(
        self, directory: Path, nonce: object, operation: object, policy: StoragePolicy
    ) -> None:
        super().__init__(directory, nonce, operation, policy, _CAD_SCHEMA)


def read_job(stream: ReadStream) -> Json:
    """Bounded read to EOF, including streams which return short reads."""
    data = bytearray()
    while True:
        chunk = stream.read(min(CHUNK_SIZE, REQUEST_MAX_BYTES + 1 - len(data)))
        if not isinstance(chunk, bytes):
            raise ValueError("invalid/blocked request stream")
        if not chunk:
            return unique_json(bytes(data))
        data.extend(chunk)
        if len(data) > REQUEST_MAX_BYTES:
            raise ValueError("request exceeds bound")
