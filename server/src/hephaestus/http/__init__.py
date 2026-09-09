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

The layer note above is about import *direction*; one sentence about import
*time* belongs beside it. **The names re-exported below resolve on first
access, not on import** (ledger J-cli-startup-4, root cause RC-2). The eager
re-export made :mod:`hephaestus.http.cli_web` — a leaf whose own imports are
argparse, sys, pathlib and typing, and which builds nothing until ``heph serve
--web`` runs — the most expensive module in the CLI at 4290 ms cold, because
importing it ran this file, which imported the closed route table (and
starlette routing, and every projection) and the runtime (and through it the
CAD ops, build123d, OCP and scikit-learn). A submodule import is now free; a
name access costs exactly what it always did, once.

The same deferral moves a *broken* dependency from parser-build time to
invocation time, so :mod:`~hephaestus.http.cli_web` refuses there by name,
importing :func:`hephaestus.core.cli.broken_import_message` inside its
``except ImportError`` — the one definition of that sentence, shared with the
CLI's registration stub and with ``serve --mcp``. That edge runs toward
``core`` and only on the failure path; it does not make anything in the
headless surface depend on this package, which is what the paragraph above
forbids.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    # The type checker reads the real symbols from the real modules; only the
    # runtime defers. Tests that import `.app`, `.runtime` or `.sessions`
    # directly are unaffected either way.
    from .app import API_PREFIX, ROUTE_TABLE, build_app
    from .principal import WorkspacePrincipal, mint_token, read_serve_record, write_serve_record
    from .runtime import WorkspaceRuntime

#: Public name -> the submodule that defines it. This is the whole re-export
#: table; ``__all__`` below is its sorted key set, so a name cannot be promised
#: here and be unreachable.
_EXPORTS: Final[dict[str, str]] = {
    "API_PREFIX": "app",
    "ROUTE_TABLE": "app",
    "build_app": "app",
    "WorkspacePrincipal": "principal",
    "mint_token": "principal",
    "read_serve_record": "principal",
    "write_serve_record": "principal",
    "WorkspaceRuntime": "runtime",
}

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


def __getattr__(name: str) -> object:
    """Resolve one re-exported name by importing the module that defines it."""
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f".{module}", __name__), name)
    globals()[name] = value  # bind it, so the next access is a plain lookup
    return value


def __dir__() -> list[str]:
    return sorted(__all__)
