# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""``.heph/serve.json`` — the discovery handshake between the two verbs (§2.1).

``INTERFACE.md`` §2.1: the serving process **owns the session leases** under
``.heph/locks/`` and writes ``<project>/.heph/serve.json`` (``0600``) =
``{pid, http, started_at, token_path, started_by}``. ``heph agent`` gains **no
new flag**: at startup it reads this file, and if a live server owns the project
it runs in **client mode** over the loopback API instead of spawning a second
in-process ``BridgeRuntime``.

**Why this module sits here and not in** ``server/http``. The file is written by
one verb and read by the other, so it belongs *below* both: ``heph agent`` must
be able to discover a server without importing the web client API, which the
2026-07-26 ordering amendment keeps out of the headless surface (and
``server/tests/test_http_boundary.py`` asserts). ``hephaestus.http.principal``
re-exports every name here, so there is one record format and one reader, not
two — mission rule 6 applied to a five-field JSON file.

The third element of the handshake is :data:`WORKSPACE_API_PREFIX`: the client
needs to know where the API lives, and a client-mode CLI that spelled the prefix
itself would be a second copy of a versioned surface.
"""

from __future__ import annotations

import getpass
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

__all__ = [
    "PRIVATE_MODE",
    "SERVE_JSON_NAME",
    "SERVE_TOKEN_NAME",
    "WORKSPACE_API_PREFIX",
    "ServeRecord",
    "clear_serve_record",
    "owning_server",
    "read_serve_record",
    "read_token",
    "write_private",
    "write_serve_record",
]

SERVE_TOKEN_NAME: Final[str] = "serve.token"
SERVE_JSON_NAME: Final[str] = "serve.json"

#: The versioned client-API prefix (``INTERFACE.md`` §2.3). Declared here so the
#: server that serves it and the CLI that calls it read one constant.
WORKSPACE_API_PREFIX: Final[str] = "/api/v1"

#: Owner-read/write only. Both files are same-user secrets on a loopback box.
PRIVATE_MODE: Final[int] = 0o600


@dataclass(frozen=True)
class ServeRecord:
    """``.heph/serve.json`` — which process owns this project's leases (§2.1)."""

    pid: int
    http: str
    started_at: float
    token_path: str
    started_by: str

    def to_json(self) -> dict[str, Any]:
        return {
            "pid": self.pid,
            "http": self.http,
            "started_at": self.started_at,
            "token_path": self.token_path,
            "started_by": self.started_by,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> ServeRecord:
        return cls(
            pid=int(data["pid"]),
            http=str(data["http"]),
            started_at=float(data["started_at"]),
            token_path=str(data["token_path"]),
            started_by=str(data["started_by"]),
        )


def write_serve_record(store_root: Path, *, http: str, token_path: Path) -> ServeRecord:
    """Write ``.heph/serve.json`` (``0600``) for the process that owns the leases."""
    store_root.mkdir(parents=True, exist_ok=True)
    record = ServeRecord(
        pid=os.getpid(),
        http=http,
        started_at=time.time(),
        token_path=str(token_path),
        started_by=_current_user(),
    )
    write_private(store_root / SERVE_JSON_NAME, json.dumps(record.to_json(), sort_keys=True))
    return record


def read_serve_record(store_root: Path) -> ServeRecord | None:
    """The recorded server, or ``None`` when there is no readable record.

    A malformed file is ``None`` rather than an exception: ``heph agent``'s
    question is "does a server own this project", and an unreadable answer to
    that is the same as no answer. Whether the named pid is *alive* is
    :func:`owning_server`'s check — this function reads a file.
    """
    path = store_root / SERVE_JSON_NAME
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    try:
        return ServeRecord.from_json(raw)  # pyright: ignore[reportUnknownArgumentType]
    except (KeyError, TypeError, ValueError):
        return None


def clear_serve_record(store_root: Path) -> None:
    """Remove ``serve.json`` on clean shutdown (missing is not an error)."""
    (store_root / SERVE_JSON_NAME).unlink(missing_ok=True)


def owning_server(root: Path) -> ServeRecord | None:
    """The **live** server that owns ``root``'s leases, or ``None``.

    "Live" is checked, not assumed: a ``serve.json`` left behind by a crashed
    process names a pid that no longer exists, and treating that as an owner
    would make the project permanently unserveable. A record whose pid is gone is
    ``None`` — the file is stale, not authoritative.
    """
    record = read_serve_record(root / ".heph")
    if record is None:
        return None
    if not _pid_alive(record.pid):
        return None
    return record


def read_token(path: Path) -> str:
    """Read a minted token file (the same-user ``0600`` file ``serve.json`` names)."""
    return path.read_text(encoding="utf-8").strip()


def write_private(path: Path, text: str) -> None:
    """Write ``text`` at mode ``0600``, created private rather than chmod'ed after.

    The window between "written" and "chmod'ed" is exactly when another local
    user could open it.
    """
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, PRIVATE_MODE)
    try:
        os.write(fd, text.encode("utf-8"))
    finally:
        os.close(fd)
    os.chmod(path, PRIVATE_MODE)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # The pid exists and belongs to another user. `serve.json` is 0600 and
        # same-user by construction, so this is not our server; treat the record
        # as stale rather than claiming a foreign process owns our leases.
        return False
    return True


def _current_user() -> str:
    try:
        return getpass.getuser()
    except Exception:  # pragma: no cover - no passwd entry and no env fallback
        return str(os.getuid())
