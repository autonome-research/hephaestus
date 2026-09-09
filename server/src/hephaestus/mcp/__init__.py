"""Stage 3 MCP server: the canonical tool surface over stdio / streamable HTTP.

The public entry points are :func:`build_app` (a configured
:class:`~fastmcp.FastMCP` instance) and :class:`HephaestusMCP` (the runtime that
owns project binding, dispatch, idempotency, and elicitation).

**Names below resolve on first access, not on import** (ledger
J-cli-startup-3, root cause RC-2). :mod:`hephaestus.core.cli` registers
``heph serve --mcp`` by importing :mod:`hephaestus.mcp.cli_serve`, and that
leaf is written to be free — it imports FastMCP inside the serve handler. An
eager ``from .app import ...`` here defeated it: the parent package runs first,
so fastmcp (and IPython through it) plus the whole CAD-ops closure arrived
before the leaf's first line, costing 407 ms warm and 2878 ms cold on every
``heph`` invocation, including ``heph --version``. The ordering rules this
package cites govern import *direction*; this ``__getattr__`` governs import
*time*. The public name list is unchanged, and every attribute-access consumer
(``from hephaestus.mcp import build_app``) keeps working and pays exactly once.

Deferring the cost moves a *broken* dependency from parser-build time to
invocation time, so :func:`hephaestus.mcp.cli_serve.serve` has to refuse there
the way the parser used to: by name. It does that by importing
:func:`hephaestus.core.cli.broken_import_message` inside its ``except
ImportError`` — the one definition of that sentence, shared with the CLI's
registration stub and with the web half, so all three say the same thing. That
edge is deliberate and it is not the direction the ordering rules govern: it
runs toward ``core``, never toward :mod:`hephaestus.http`, and it exists only
on the failure path — a serve that starts never imports
:mod:`hephaestus.core.cli` at all.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    # The type checker reads the real symbols from the real modules; only the
    # runtime defers. `heph serve --mcp` is unaffected either way.
    from .app import EXTRA_TOOL_NAMES, HephaestusMCP, build_app
    from .idempotency import (
        IDEMPOTENCY_META_KEY,
        IdempotencyError,
        IdempotencyLedger,
        derive_raw_id,
        payload_hash,
    )

#: Public name -> the submodule that defines it. This is the whole re-export
#: table; ``__all__`` below is its sorted key set, so a name cannot be promised
#: here and be unreachable.
_EXPORTS: Final[dict[str, str]] = {
    "EXTRA_TOOL_NAMES": "app",
    "HephaestusMCP": "app",
    "build_app": "app",
    "IDEMPOTENCY_META_KEY": "idempotency",
    "IdempotencyError": "idempotency",
    "IdempotencyLedger": "idempotency",
    "derive_raw_id": "idempotency",
    "payload_hash": "idempotency",
}

__all__ = [
    "EXTRA_TOOL_NAMES",
    "IDEMPOTENCY_META_KEY",
    "HephaestusMCP",
    "IdempotencyError",
    "IdempotencyLedger",
    "build_app",
    "derive_raw_id",
    "payload_hash",
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
