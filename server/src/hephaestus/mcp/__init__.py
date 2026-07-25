"""Stage 3 MCP server: the canonical tool surface over stdio / streamable HTTP.

The public entry points are :func:`build_app` (a configured
:class:`~fastmcp.FastMCP` instance) and :class:`HephaestusMCP` (the runtime that
owns project binding, dispatch, idempotency, and elicitation).
"""

from __future__ import annotations

from .app import EXTRA_TOOL_NAMES, HephaestusMCP, build_app
from .idempotency import (
    IDEMPOTENCY_META_KEY,
    IdempotencyError,
    IdempotencyLedger,
    derive_raw_id,
    payload_hash,
)

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
