"""Private worker which reports raw OCI containment observations.

The worker deliberately makes no overall security decision.  It emits one
closed, versioned JSON record; the host backend compares every observation
with the profile it requested.
"""

from __future__ import annotations

import json
import os
import re
import resource
import socket
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO, TextIO

from hephaestus.core.executor.sandbox.oci_protocol import (
    OCI_PROFILE_VERSION,
    PROBE_REQUEST_MAX_BYTES,
    PROTOCOL_VERSION,
    diagnostic_bytes,
)

MAX_REQUEST_BYTES = PROBE_REQUEST_MAX_BYTES
_NONCE_RE = re.compile(r"[0-9a-f]{64}", flags=re.ASCII)
_STATUS_KEYS = ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb", "NoNewPrivs")


class ProbeRequestError(ValueError):
    pass


class ProbeProtocolError(ProbeRequestError):
    pass


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ProbeRequestError("invalid probe request")
        result[key] = value
    return result


@dataclass(frozen=True)
class ProbeRequest:
    nonce: str
    protocol_version: int


def parse_request(payload: bytes) -> ProbeRequest:
    """Validate one size-bounded, closed-schema probe request."""
    if len(payload) > MAX_REQUEST_BYTES:
        raise ProbeRequestError("invalid probe request")
    try:
        value: object = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ProbeRequestError("invalid probe request") from None
    if not isinstance(value, dict) or set(value) != {"nonce", "protocol_version"}:
        raise ProbeRequestError("invalid probe request")
    nonce = value.get("nonce")
    version = value.get("protocol_version")
    if not isinstance(nonce, str) or _NONCE_RE.fullmatch(nonce) is None:
        raise ProbeRequestError("invalid probe request")
    if type(version) is not int:
        raise ProbeRequestError("invalid probe request")
    if version != PROTOCOL_VERSION:
        raise ProbeProtocolError("unsupported protocol version")
    return ProbeRequest(nonce=nonce, protocol_version=version)


def _limit_value(
    name: str,
    *,
    required: bool,
    getrlimit: Callable[[int], tuple[int, int]],
) -> list[int] | None:
    kind = getattr(resource, name, None)
    if kind is None:
        if required:
            raise RuntimeError("required resource limit is unavailable")
        return None
    soft, hard = getrlimit(kind)
    return [int(soft), int(hard)]


def parse_status(text: str) -> dict[str, object]:
    """Parse only the capability/NNP fields required from ``/proc/self/status``."""
    values: dict[str, str] = {}
    for line in text.splitlines():
        key, separator, value = line.partition(":")
        if separator and key in _STATUS_KEYS:
            if key in values:
                raise RuntimeError("duplicate process status field")
            values[key] = value.strip()
    if set(values) != set(_STATUS_KEYS):
        raise RuntimeError("incomplete process status")
    caps: dict[str, str] = {}
    for key in _STATUS_KEYS[:-1]:
        raw = values[key]
        if re.fullmatch(r"[0-9a-fA-F]{16}", raw) is None:
            raise RuntimeError("malformed capability set")
        caps[key] = raw.lower()
    if values["NoNewPrivs"] not in {"0", "1"}:
        raise RuntimeError("malformed NoNewPrivs")
    return {"capabilities": caps, "no_new_privs": int(values["NoNewPrivs"])}


def _unescape_mount(value: str) -> str:
    return re.sub(
        r"\\(040|011|012|134)",
        lambda match: {"040": " ", "011": "\t", "012": "\n", "134": "\\"}[match.group(1)],
        value,
    )


def parse_mountinfo(
    text: str, paths: tuple[str, ...] = ("/", "/work", "/tmp")
) -> dict[str, object]:
    """Return the most-specific mount covering each requested path."""
    mounts: list[tuple[str, str, set[str]]] = []
    for line in text.splitlines():
        before, separator, after = line.partition(" - ")
        fields = before.split()
        tail = after.split()
        if not separator or len(fields) < 6 or len(tail) < 3:
            raise RuntimeError("malformed mountinfo")
        mountpoint = _unescape_mount(fields[4])
        options = set(fields[5].split(",")) | set(tail[2].split(","))
        mounts.append((mountpoint, tail[0], options))

    result: dict[str, object] = {}
    for requested in paths:
        candidates = [
            item
            for item in mounts
            if requested == item[0]
            or (item[0] != "/" and requested.startswith(item[0].rstrip("/") + "/"))
            or item[0] == "/"
        ]
        if not candidates:
            raise RuntimeError("mount is absent")
        mountpoint, fs_type, options = max(candidates, key=lambda item: len(item[0]))
        result[requested] = {
            "fs_type": fs_type,
            "mountpoint": mountpoint,
            "options": sorted(options),
        }
    return result


def _read_limit(path: Path) -> int | str:
    value = path.read_text(encoding="ascii").strip()
    if value == "max":
        return value
    if re.fullmatch(r"[0-9]+", value) is None:
        raise RuntimeError("malformed cgroup limit")
    return int(value)


def _resolve_cgroup_path(mountpoint: str, root: str, membership: str) -> Path:
    try:
        relative = PurePosixPath(membership).relative_to(PurePosixPath(root))
    except ValueError:
        raise RuntimeError("cgroup membership is outside its mounted hierarchy") from None
    return Path(mountpoint, *relative.parts)


def parse_cgroup_observation(
    cgroup_text: str,
    mountinfo_text: str,
    *,
    read_limit: Callable[[Path], int | str] = _read_limit,
) -> dict[str, object]:
    """Parse the current process's cgroup v2 or conventional v1 controller paths."""
    rows: list[tuple[str, set[str], str]] = []
    for line in cgroup_text.splitlines():
        fields = line.split(":", 2)
        if len(fields) != 3 or not fields[2].startswith("/"):
            raise RuntimeError("malformed cgroup membership")
        rows.append((fields[0], set(filter(None, fields[1].split(","))), fields[2]))

    cgroup_mounts: list[tuple[str, str, str, set[str]]] = []
    for line in mountinfo_text.splitlines():
        before, separator, after = line.partition(" - ")
        fields, tail = before.split(), after.split()
        if not separator or len(fields) < 5 or len(tail) < 3:
            raise RuntimeError("malformed mountinfo")
        if tail[0] in {"cgroup", "cgroup2"}:
            cgroup_mounts.append(
                (
                    _unescape_mount(fields[4]),
                    _unescape_mount(fields[3]),
                    tail[0],
                    set(tail[2].split(",")),
                )
            )

    unified = next(
        (path for hierarchy, controllers, path in rows if hierarchy == "0" and not controllers),
        None,
    )
    v2_mount = next(
        ((path, root) for path, root, fs_type, _ in cgroup_mounts if fs_type == "cgroup2"),
        None,
    )
    if unified is not None and v2_mount is not None:
        base = _resolve_cgroup_path(*v2_mount, unified)
        return {
            "version": 2,
            "memory_max": read_limit(base / "memory.max"),
            "memory_swap_max": read_limit(base / "memory.swap.max"),
            "memory_swap_mode": "additional",
            "pids_max": read_limit(base / "pids.max"),
            "cpu_quota": _cpu_max(read_limit, base / "cpu.max"),
        }

    def controller_path(controller: str) -> Path:
        member = next((path for _, ctrls, path in rows if controller in ctrls), None)
        mount = next(
            (
                (path, root)
                for path, root, fs_type, options in cgroup_mounts
                if fs_type == "cgroup" and controller in options
            ),
            None,
        )
        if member is None or mount is None:
            raise RuntimeError("required cgroup controller is absent")
        return _resolve_cgroup_path(*mount, member)

    memory = controller_path("memory")
    pids = controller_path("pids")
    cpu = controller_path("cpu")
    quota = read_limit(cpu / "cpu.cfs_quota_us")
    period = read_limit(cpu / "cpu.cfs_period_us")
    return {
        "version": 1,
        "memory_max": read_limit(memory / "memory.limit_in_bytes"),
        "memory_swap_max": read_limit(memory / "memory.memsw.limit_in_bytes"),
        "memory_swap_mode": "total",
        "pids_max": read_limit(pids / "pids.max"),
        "cpu_quota": {"quota": quota, "period": period},
    }


def _cpu_max(read_limit: Callable[[Path], int | str], path: Path) -> dict[str, int | str]:
    # cpu.max contains two fields and therefore cannot use the ordinary scalar reader.
    if read_limit is _read_limit:
        fields = path.read_text(encoding="ascii").strip().split()
    else:
        value = read_limit(path)
        fields = str(value).split()
    if (
        len(fields) != 2
        or (fields[0] != "max" and not fields[0].isdigit())
        or not fields[1].isdigit()
    ):
        raise RuntimeError("malformed cpu.max")
    return {"quota": fields[0] if fields[0] == "max" else int(fields[0]), "period": int(fields[1])}


def _attempt_write(path: Path, payload: bytes) -> int:
    try:
        path.write_bytes(payload)
    except OSError as exc:
        return int(exc.errno or -1)
    else:
        path.unlink(missing_ok=True)
        return 0


def _network_observation() -> dict[str, object]:
    interfaces = sorted(path.name for path in Path("/sys/class/net").iterdir())
    # Loopback routes are compatible with --network=none. Report only routes
    # attached to another interface so the host can require this list empty.
    ipv4_rows = [
        line.split()
        for line in Path("/proc/net/route").read_text().splitlines()[1:]
        if line.strip()
    ]
    ipv6_rows = [
        line.split()
        for line in Path("/proc/net/ipv6_route").read_text().splitlines()
        if line.strip()
    ]
    if any(len(row) < 1 for row in ipv4_rows) or any(len(row) < 10 for row in ipv6_rows):
        raise RuntimeError("malformed network route table")
    routes = [" ".join(row) for row in ipv4_rows if row[0] != "lo"]
    routes += [" ".join(row) for row in ipv6_rows if row[-1] != "lo"]
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.25)
    try:
        sock.connect(("198.51.100.1", 9))
    except OSError as exc:
        connect_errno = int(exc.errno or -1)
    else:
        connect_errno = 0
    finally:
        sock.close()
    return {"interfaces": interfaces, "routes": routes, "connect_errno": connect_errno}


def probe_record(
    request: ProbeRequest,
    *,
    getrlimit: Callable[[int], tuple[int, int]] | None = None,
    geteuid: Callable[[], int] | None = None,
    getegid: Callable[[], int] | None = None,
    raw_observations: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Collect identity/rlimits and either supplied or live raw observations."""
    read_limit = resource.getrlimit if getrlimit is None else getrlimit
    observations: dict[str, object]
    if raw_observations is None:
        status = parse_status(Path("/proc/self/status").read_text(encoding="ascii"))
        mount_text = Path("/proc/self/mountinfo").read_text(encoding="utf-8")
        proof_name = f".heph-oci-probe-{request.nonce}"
        proof = Path("/work") / proof_name
        proof.write_text(request.nonce, encoding="ascii")
        tmp_stat = os.statvfs("/tmp")
        observations = {
            **status,
            "cwd": os.getcwd(),
            "hostname": socket.gethostname(),
            "pid": os.getpid(),
            "mounts": parse_mountinfo(mount_text),
            "root_write_errno": _attempt_write(Path("/.heph-oci-root-write"), b"x"),
            "work_proof": proof_name,
            "tmp_write_errno": _attempt_write(Path("/tmp/.heph-oci-tmp-write"), b"x"),
            "tmp_capacity_bytes": tmp_stat.f_frsize * tmp_stat.f_blocks,
            "network": _network_observation(),
            "cgroup": parse_cgroup_observation(
                Path("/proc/self/cgroup").read_text(encoding="ascii"), mount_text
            ),
        }
    else:
        observations = dict(raw_observations)

    return {
        "cgroup": observations.get("cgroup"),
        "cwd": observations.get("cwd"),
        "effective_gid": (os.getegid if getegid is None else getegid)(),
        "effective_uid": (os.geteuid if geteuid is None else geteuid)(),
        "hostname": observations.get("hostname"),
        "kind": "hephaestus_executor_probe",
        "mounts": observations.get("mounts"),
        "network": observations.get("network"),
        "nonce": request.nonce,
        "no_new_privs": observations.get("no_new_privs"),
        "oci_profile_version": OCI_PROFILE_VERSION,
        "pid": observations.get("pid"),
        "protocol_version": PROTOCOL_VERSION,
        "capabilities": observations.get("capabilities"),
        "rlimits": {
            "RLIMIT_AS": _limit_value("RLIMIT_AS", required=True, getrlimit=read_limit),
            "RLIMIT_CORE": _limit_value("RLIMIT_CORE", required=True, getrlimit=read_limit),
            "RLIMIT_CPU": _limit_value("RLIMIT_CPU", required=True, getrlimit=read_limit),
            "RLIMIT_DATA": _limit_value("RLIMIT_DATA", required=True, getrlimit=read_limit),
            "RLIMIT_NPROC": _limit_value("RLIMIT_NPROC", required=True, getrlimit=read_limit),
        },
        "root_write_errno": observations.get("root_write_errno"),
        "tmp_capacity_bytes": observations.get("tmp_capacity_bytes"),
        "tmp_write_errno": observations.get("tmp_write_errno"),
        "work_proof": observations.get("work_proof"),
    }


def probe_bytes(
    request: ProbeRequest,
    *,
    getrlimit: Callable[[int], tuple[int, int]] | None = None,
    geteuid: Callable[[], int] | None = None,
    getegid: Callable[[], int] | None = None,
    raw_observations: Mapping[str, object] | None = None,
) -> bytes:
    record = probe_record(
        request,
        getrlimit=getrlimit,
        geteuid=geteuid,
        getegid=getegid,
        raw_observations=raw_observations,
    )
    return (
        json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    ).encode("ascii")


def _write(stream: TextIO, payload: bytes) -> None:
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        buffer.write(payload)
        buffer.flush()
    else:
        stream.write(payload.decode("ascii"))
        stream.flush()


def _read_bounded(stream: BinaryIO) -> bytes:
    return stream.read(MAX_REQUEST_BYTES + 1)


def main() -> int:
    try:
        request = parse_request(_read_bounded(sys.stdin.buffer))
    except ProbeProtocolError:
        _write(
            sys.stderr,
            diagnostic_bytes("protocol_version_mismatch", component="oci_probe_worker"),
        )
        return 65
    except ProbeRequestError:
        _write(sys.stderr, diagnostic_bytes("invalid_probe_request", component="oci_probe_worker"))
        return 64
    try:
        response = probe_bytes(request)
    except Exception:
        _write(
            sys.stderr,
            diagnostic_bytes("probe_inspection_failed", component="oci_probe_worker"),
        )
        return 78
    _write(sys.stdout, response)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
