"""Private durable ownership for one explicitly bounded OCI supervision session.

An absent name is never evidence that a create request has settled. Only the
successful create response transitions pending -> known. Recovery reclaims exact
recorded resources but retains unknown requests and unproved local-client state.
The directory is operator-owned, not a workload input or a report-import API.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import stat
import threading
from pathlib import Path
from typing import TypedDict, cast

from hephaestus.core.errors import SandboxDeniedError

MAX_RECORD_BYTES = 256 * 1024
MAX_CONTAINERS = 64


class ContainerRecord(TypedDict):
    id: str | None
    pending: bool
    absent: bool
    terminal: dict[str, object] | None


class ClientRecord(TypedDict):
    reaped: bool


class OwnershipState(TypedDict):
    version: int
    binding: dict[str, object]
    containers: dict[str, ContainerRecord]
    clients: dict[str, ClientRecord]
    launch_pending: bool


class OwnershipJournal:
    def __init__(self, directory: Path, binding: dict[str, object]) -> None:
        # Keep pure OCI identity/schema imports usable on other packaging hosts.
        # Durable ownership itself requires POSIX locking; no unsafe fallback.
        try:
            import fcntl
        except ImportError as exc:
            raise SandboxDeniedError("durable OCI ownership requires POSIX locking") from exc
        directory.mkdir(mode=0o700, parents=False, exist_ok=True)
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise SandboxDeniedError("ownership directory must be private and owned")
        self.state: OwnershipState
        self.directory = directory.resolve(strict=True)
        self._mutex = threading.RLock()
        self._fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            self._lock = os.open(
                "lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600, dir_fd=self._fd
            )
        except BaseException:
            os.close(self._fd)
            raise
        try:
            lock_info = os.fstat(self._lock)
            if not stat.S_ISREG(lock_info.st_mode) or lock_info.st_nlink != 1:
                raise SandboxDeniedError("invalid ownership lock")
            fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                fd = os.open("state.json", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=self._fd)
            except FileNotFoundError:
                self.state = {
                    "version": 1,
                    "binding": binding,
                    "containers": {},
                    "clients": {},
                    "launch_pending": False,
                }
                self._save()
            else:
                with os.fdopen(fd, "rb") as stream:
                    info = os.fstat(stream.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                        raise SandboxDeniedError("invalid ownership record")
                    data = stream.read(MAX_RECORD_BYTES + 1)
                if len(data) > MAX_RECORD_BYTES:
                    raise SandboxDeniedError("ownership record limit")
                from .oci_transfer import unique_json

                try:
                    self.state = self._validate(unique_json(data), binding)
                except (TypeError, ValueError, KeyError) as exc:
                    raise SandboxDeniedError("invalid ownership record schema") from exc
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _validate(value: object, binding: dict[str, object]) -> OwnershipState:
        if (
            not isinstance(value, dict)
            or set(value) != {"version", "binding", "containers", "clients", "launch_pending"}
            or type(value["launch_pending"]) is not bool
            or type(value["version"]) is not int
            or value["version"] != 1
            or value["binding"] != binding
            or not isinstance(value["containers"], dict)
            or len(value["containers"]) > MAX_CONTAINERS
            or not isinstance(value["clients"], dict)
            or len(value["clients"]) > 256
        ):
            raise SandboxDeniedError("invalid ownership binding/schema")
        for name, record in value["containers"].items():
            if (
                not isinstance(name, str)
                or re.fullmatch(r"heph-exec-[0-9a-f]{64}", name) is None
                or not isinstance(record, dict)
                or set(record) != {"id", "pending", "absent", "terminal"}
                or type(record["pending"]) is not bool
                or type(record["absent"]) is not bool
                or (
                    record["id"] is not None
                    and (
                        not isinstance(record["id"], str)
                        or re.fullmatch(r"[0-9a-f]{64}", record["id"]) is None
                    )
                )
                or (record["id"] is None and not record["pending"])
            ):
                raise SandboxDeniedError("invalid owned container")
        for pid, record in value["clients"].items():
            if (
                not isinstance(pid, str)
                or not pid.isdecimal()
                or not isinstance(record, dict)
                or set(record) != {"reaped"}
            ):
                raise SandboxDeniedError("invalid owned client")
            if type(record["reaped"]) is not bool:
                raise SandboxDeniedError("invalid client reap evidence")
        for record in value["containers"].values():
            terminal = record["terminal"]
            if terminal is not None and (
                not isinstance(terminal, dict)
                or set(terminal) != {"Running", "ExitCode", "OOMKilled"}
                or terminal["Running"] is not False
                or type(terminal["OOMKilled"]) is not bool
                or type(terminal["ExitCode"]) is not int
                or not 0 <= terminal["ExitCode"] <= 255
            ):
                raise SandboxDeniedError("invalid durable terminal state")
        # The complete journal schema is admitted above, never before validation.
        return cast(OwnershipState, value)

    def _save(self) -> None:
        raw = json.dumps(self.state, sort_keys=True, separators=(",", ":")).encode()
        if len(raw) > MAX_RECORD_BYTES:
            raise SandboxDeniedError("ownership journal bound exceeded")
        # A stale temp name has no authority. Unlink rather than truncate a
        # potentially aliased inode; exclusive recreation cannot follow links.
        with contextlib.suppress(FileNotFoundError):
            os.unlink("state.next", dir_fd=self._fd)
        fd = os.open(
            "state.next",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=self._fd,
        )
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace("state.next", "state.json", src_dir_fd=self._fd, dst_dir_fd=self._fd)
        os.fsync(self._fd)

    @property
    def pending(self) -> bool:
        return (
            self.state["launch_pending"]
            or any(r["pending"] or not r["absent"] for r in self.state["containers"].values())
            or any(not r["reaped"] for r in self.state["clients"].values())
        )

    def require_clean(self) -> None:
        if self.pending:
            raise SandboxDeniedError("durable OCI ownership requires reconciliation")

    def admit_operation(self) -> None:
        """Reserve a whole bounded probe/job/cleanup before any external side effect.

        At most three containers and fewer than 32 clients are used by a normal
        owner. Reserve 4/64, including exceptional cleanup, without enlarging or
        discarding the durable ledger. Recovery has its own separate journal.
        """
        with self._mutex:
            self.require_clean()
            if (
                len(self.state["containers"]) > MAX_CONTAINERS - 4
                or len(self.state["clients"]) > 256 - 64
            ):
                raise SandboxDeniedError("supervision session capacity; new owned session required")

    def submitted(self, name: str) -> None:
        with self._mutex:
            if len(self.state["containers"]) >= MAX_CONTAINERS:
                raise SandboxDeniedError("supervision session container limit reached")
            if name in self.state["containers"]:
                raise SandboxDeniedError("owned create name reused")
            self.state["containers"][name] = {
                "id": None,
                "pending": True,
                "absent": False,
                "terminal": None,
            }
            self._save()  # MUST complete before Popen/create submission

    def settled(self, name: str, container_id: str) -> None:
        with self._mutex:
            self.state["containers"][name].update(id=container_id, pending=False)
            self._save()

    def absent(self, identity: str, terminal: dict[str, object] | None) -> None:
        with self._mutex:
            for name, record in self.state["containers"].items():
                if identity in (name, record["id"]):
                    record["absent"] = True
                    if terminal is not None:
                        record["terminal"] = terminal
                    self._save()
                    return
            raise SandboxDeniedError("unowned cleanup")

    def launching_client(self) -> None:
        """Persist spawn intent before Popen: death before PID recording refuses."""
        with self._mutex:
            if self.state["launch_pending"] or len(self.state["clients"]) >= 256:
                raise SandboxDeniedError("unsettled client launch or session client limit")
            self.state["launch_pending"] = True
            self._save()

    def client(self, pid: int, *, reaped: bool) -> None:
        with self._mutex:
            if str(pid) not in self.state["clients"] and len(self.state["clients"]) >= 256:
                raise SandboxDeniedError("supervision session client limit reached")
            self.state["clients"][str(pid)] = {"reaped": reaped}
            self.state["launch_pending"] = False
            self._save()

    def close(self) -> None:
        os.close(self._lock)
        os.close(self._fd)

    def __enter__(self) -> OwnershipJournal:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
