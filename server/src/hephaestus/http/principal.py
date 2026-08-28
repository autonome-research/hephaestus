# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""The workspace principal, its bearer token, and the ``serve.json`` handshake.

``INTERFACE.md`` §2.2. The workspace principal is **not** a Pi session and must
not borrow one::

    WorkspacePrincipal { project_root, profile="orchestrator", token_id }

``profile="orchestrator"`` mirrors ``mcp/app.py``'s ``_MCP_PROFILE``: a local
operator with the project open is orchestrator-equivalent. Dispatch's own
object-scope and reviewer rules apply unchanged; this layer adds **no authz of
its own beyond the token**.

The token is minted per serve into ``<project>/.heph/serve.token`` (``0600``)
and rides in the URL **fragment**, never a query string, so it never enters an
access log or a ``Referer`` (§2.2). The server only ever sees it as
``Authorization: Bearer …``; there is no login, cookie, refresh, or user model,
and nothing here prompts for credentials because there are none to prompt for.

``<project>/.heph/serve.json`` (``0600``) is the discovery file §2.1 pins:
``{pid, http, started_at, token_path, started_by}``. ``heph agent`` reads it to
decide whether a live server already owns the project's leases — one process
owns them, and a second either routes through it or refuses ``session_busy``.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from hephaestus.agent_bridge.serve_record import (
    SERVE_JSON_NAME,
    SERVE_TOKEN_NAME,
    ServeRecord,
    clear_serve_record,
    read_serve_record,
    read_token,
    write_private,
    write_serve_record,
)

__all__ = [
    "SERVE_JSON_NAME",
    "SERVE_TOKEN_NAME",
    "WORKSPACE_PROFILE",
    "ServeRecord",
    "WorkspacePrincipal",
    "clear_serve_record",
    "mint_token",
    "read_serve_record",
    "read_token",
    "token_id",
    "verify_token",
    "write_serve_record",
]

#: A local operator with the project open is orchestrator-equivalent (§2.2).
WORKSPACE_PROFILE: Final[str] = "orchestrator"

# The ``serve.json`` record, its reader/writer, and the ``0600`` write helper
# live in :mod:`hephaestus.agent_bridge.serve_record` and are re-exported here.
# They are the handshake between ``heph serve --web`` and ``heph agent``, and
# ``heph agent`` may not import the web client API to read a file the two verbs
# share (the 2026-07-26 ordering amendment). One record format, one reader.


@dataclass(frozen=True)
class WorkspacePrincipal:
    """The §2.2 web principal: one open project, one bearer, no session."""

    project_root: Path
    token_id: str
    profile: str = WORKSPACE_PROFILE

    @property
    def session_id(self) -> str:
        """The dispatch-visible identity: namespaced so it can never collide.

        A Pi session id and an MCP session id are ``<uuid>`` and ``mcp:<id>``;
        this one is ``web:<token id>``. It is *not* a session — nothing suspends
        on it and no lease is taken in its name — but ``Principal.session_id`` is
        the field dispatch namespaces its idempotency keys by, so it must be
        unmistakable in a ledger row.
        """
        return f"web:{self.token_id}"


def token_id(token: str) -> str:
    """A short, non-reversible label for a token (for logs and ledger keys)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


def mint_token(store_root: Path) -> tuple[str, Path]:
    """Mint a fresh per-serve bearer token into ``.heph/serve.token`` (``0600``).

    Written with ``O_CREAT|O_TRUNC`` at mode ``0600`` rather than written then
    chmod'ed: the window between the two is exactly when another local user
    could open it.
    """
    store_root.mkdir(parents=True, exist_ok=True)
    path = store_root / SERVE_TOKEN_NAME
    token = secrets.token_urlsafe(32)
    write_private(path, token)
    return token, path


def verify_token(presented: str, expected: str) -> bool:
    """Constant-time bearer comparison."""
    return hmac.compare_digest(presented, expected)
