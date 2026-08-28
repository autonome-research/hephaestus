# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""``server/http`` — the web workspace API (``INTERFACE.md`` §2).

**This is a web client API, not part of the headless surface.** The 2026-07-26
ordering amendment says so, and it has a consequence this package enforces by
its import direction: nothing in the headless surface may come to depend on it.
``hephaestus.mcp`` and ``hephaestus.agent_bridge`` import *nothing* from here.
What the two transports share lives **below** both, where either may reach it
without either depending on the other:
:mod:`hephaestus.agent_bridge.project_projections` (the ``open_project`` /
``list_parts`` bodies), :mod:`hephaestus.core.artifacts` (the UTF-8 pager), and
:mod:`hephaestus.core.checks.report` (the ``heph check --json`` document).

The layers, in the order a request meets them:

* :mod:`~hephaestus.http.principal` — the bearer, the ``0600`` token file, and
  the ``serve.json`` record that says which process owns the project's leases.
* :mod:`~hephaestus.http.runtime` — one open project: store, ``CadOps``,
  ``ToolDispatcher``, REST ledger.
* :mod:`~hephaestus.http.app` — the closed route table (§2.3).
* :mod:`~hephaestus.http.idempotency` — the §2.5 key ladder and replay shape.
* :mod:`~hephaestus.http.errors` — the §2.4 mapping, closed.
* :mod:`~hephaestus.http.projections`, :mod:`~hephaestus.http.artifacts`,
  :mod:`~hephaestus.http.git_projection` — what each route actually returns.

Numbers, IDs, verdicts, and provenance are the server's; pixels, camera, and
hover state are the client's. This package is the first half of that sentence.
"""

from __future__ import annotations

from .app import API_PREFIX, ROUTE_TABLE, build_app
from .principal import WorkspacePrincipal, mint_token, read_serve_record, write_serve_record
from .runtime import WorkspaceRuntime

__all__ = [
    "API_PREFIX",
    "ROUTE_TABLE",
    "WorkspacePrincipal",
    "WorkspaceRuntime",
    "build_app",
    "mint_token",
    "read_serve_record",
    "write_serve_record",
]
