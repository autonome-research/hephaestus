"""Closed, bounded Linux storage observations for OCI profile 5.

Mount flags are per-mount flags, NOT unioned with superblock flags (a read-only
bind may have a writable superblock). Linux errno values are wire constants.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

from .oci_storage_policy import StoragePolicy
from .oci_transfer import Json

MASKED_DEVICE_PATHS = (
    "/proc/interrupts",
    "/proc/kcore",
    "/proc/keys",
    "/proc/latency_stats",
    "/proc/timer_list",
)

RUNTIME_PATHS = (
    "/dev",
    "/dev/shm",
    "/dev/mqueue",
    "/etc/hosts",
    "/etc/hostname",
    "/etc/resolv.conf",
    "/inputs",
)
CAPACITY_KEYS = {"bytes", "available_bytes", "inodes", "available_inodes", "block_size"}


def bounded_text(path: str) -> str:
    with open(path, "rb") as stream:
        data = stream.read(65537)
    if len(data) > 65536:
        raise ValueError("proc observation exceeds bound")
    return data.decode("ascii")


def capacity(path: str) -> dict[str, int]:
    info = os.statvfs(path)
    return {
        "bytes": info.f_blocks * info.f_frsize,
        "available_bytes": info.f_bavail * info.f_frsize,
        "inodes": info.f_files,
        "available_inodes": info.f_favail,
        "block_size": info.f_frsize,
    }


def mount_records(text: str) -> dict[str, Json]:
    from ._oci_probe_worker import unescape_mount

    records: dict[str, Json] = {}
    for line in text.splitlines():
        before, sep, after = line.partition(" - ")
        head, tail = before.split(), after.split()
        if not sep or len(head) < 6 or len(tail) != 3 or len(records) >= 256:
            raise ValueError("invalid mount inventory")
        path = unescape_mount(head[4])
        if path in records or not path.startswith("/"):
            raise ValueError("ambiguous mount inventory")
        options: list[Json] = [option for option in sorted(head[5].split(","))]
        records[path] = {"fs_type": tail[0], "options": options}
    return records


def write_errno(path: str) -> int:
    target = Path(path)
    try:
        info = target.stat()
        directory = stat.S_ISDIR(info.st_mode)
        flags = os.O_WRONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        if directory:
            target /= ".heph-storage-check"
            flags |= os.O_CREAT | os.O_EXCL
        fd = os.open(target, flags, 0o600)
    except OSError as exc:
        return int(exc.errno or -1)
    else:
        os.close(fd)
        if directory:
            target.unlink()
        return 0


def masked_device(path: str) -> dict[str, int]:
    # Fixed five trusted proc paths only, no open/read of a device, no symlink
    # following and no directory enumeration. Some kernels omit latency_stats:
    # explicit ENOENT is admissible only when mountinfo also has no such mount.
    try:
        info = os.stat(path, follow_symlinks=False)
    except FileNotFoundError:
        return {"errno": 2}
    return {
        "file_type": stat.S_IFMT(info.st_mode),
        "major": os.major(info.st_rdev),
        "minor": os.minor(info.st_rdev),
    }


def observe_storage() -> dict[str, Json]:
    return {
        "mounts": mount_records(bounded_text("/proc/self/mountinfo")),
        "capacities": {p: {**capacity(p)} for p in ("/work", "/tmp")},
        "runtime_write_errno": {p: write_errno(p) for p in RUNTIME_PATHS},
        "masked_devices": {p: {**masked_device(p)} for p in MASKED_DEVICE_PATHS},
    }


def capacity_valid(value: object, byte_limit: int, inode_limit: int) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == CAPACITY_KEYS
        and all(type(v) is int and v >= 0 for v in value.values())
        and value["bytes"] == byte_limit
        and value["inodes"] == inode_limit
        and 0 < value["block_size"] <= byte_limit
        and 0 <= value["available_bytes"] <= byte_limit
        and 0 <= value["available_inodes"] <= inode_limit
    )


def storage_valid(value: object, policy: StoragePolicy) -> bool:
    try:
        return _storage_valid(value, policy)
    except (KeyError, TypeError, ValueError):
        return False


def _storage_valid(value: object, policy: StoragePolicy) -> bool:
    if not isinstance(value, dict) or set(value) != {
        "mounts",
        "capacities",
        "runtime_write_errno",
        "masked_devices",
    }:
        return False
    devices = value["masked_devices"]
    if not isinstance(devices, dict) or set(devices) != set(MASKED_DEVICE_PATHS):
        return False
    mounts = value["mounts"]
    if not isinstance(mounts, dict):
        return False
    for path, device in devices.items():
        if (
            isinstance(device, dict)
            and set(device) == {"errno"}
            and type(device["errno"]) is int
            and device["errno"] == 2
            and path not in mounts
        ):
            continue
        if (
            not isinstance(device, dict)
            or set(device) != {"file_type", "major", "minor"}
            or any(type(v) is not int for v in device.values())
            or device != {"file_type": stat.S_IFCHR, "major": 1, "minor": 3}
        ):
            return False
    mounts, capacities, runtime = value["mounts"], value["capacities"], value["runtime_write_errno"]
    if not all(isinstance(v, dict) for v in (mounts, capacities, runtime)):
        return False
    if set(runtime) != set(RUNTIME_PATHS) or set(capacities) != {"/work", "/tmp"}:
        return False
    for path, code in runtime.items():
        allowed = {2, 13, 30} if path == "/dev/shm" else {13, 30}
        if type(code) is not int or code not in allowed:
            return False
    if runtime["/inputs"] != 30:
        return False
    for path, byte_limit, inode_limit in (
        ("/work", policy.work_bytes, policy.work_inodes),
        ("/tmp", policy.tmp_bytes, policy.tmp_inodes),
    ):
        mount = mounts.get(path)
        if not isinstance(mount, dict) or mount.get("fs_type") != "tmpfs":
            return False
        options = mount.get("options")
        if not isinstance(options, list) or not {"rw", "nosuid", "nodev", "noexec"} <= set(options):
            return False
        if not capacity_valid(capacities[path], byte_limit, inode_limit):
            return False
    if not {"/", "/inputs", "/dev", "/dev/mqueue", "/proc"} <= set(mounts):
        return False
    for path, mount in mounts.items():
        if not isinstance(path, str) or not path.startswith("/"):
            return False
        if not isinstance(mount, dict) or set(mount) != {"fs_type", "options"}:
            return False
        options = mount["options"]
        if (
            not isinstance(mount["fs_type"], str)
            or not isinstance(options, list)
            or not all(isinstance(v, str) for v in options)
            or len(set(options)) != len(options)
            or len({"ro", "rw"} & set(options)) != 1
        ):
            return False
        if path in {"/", "/inputs", "/dev/mqueue"} and "ro" not in options:
            return False
        if path == "/dev/mqueue" and (
            mount["fs_type"] != "tmpfs" or not {"nosuid", "nodev", "noexec"} <= set(options)
        ):
            return False
        if "ro" in options:
            continue
        expected = {
            "/work": "tmpfs",
            "/tmp": "tmpfs",
            "/dev": "tmpfs",
            "/dev/pts": "devpts",
            "/proc": "proc",
        }
        if path in expected:
            if mount["fs_type"] != expected[path]:
                return False
            continue
        if path in {"/etc/hosts", "/etc/hostname", "/etc/resolv.conf"}:
            continue  # independently proved unwritable by this numeric identity
        # Independently observed no-follow Linux /dev/null character devices,
        # not an exemption based merely on tmpfs mount type or path spelling.
        if path in MASKED_DEVICE_PATHS and mount["fs_type"] == "tmpfs":
            continue
        return False
    return True


class StorageRefusal(ValueError):
    def __init__(self, observations: dict[str, object]) -> None:
        super().__init__("unsupported writable storage surfaces")
        self.observations = observations


def require_storage(policy: StoragePolicy) -> None:
    observations = observe_storage()
    if not storage_valid(observations, policy):
        raise StorageRefusal(dict(observations))
