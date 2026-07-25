"""``heph serve --mcp [--http HOST:PORT]`` — one app, two MCP transports.

``--mcp`` is required (Stage 4 adds the read-only HTTP workspace behind the same
verb). Without ``--http`` the server speaks MCP over **stdio**, the transport a
locally-launched MCP client uses; with it, the identical
:class:`~hephaestus.mcp.app.HephaestusMCP` app is served over **streamable
HTTP** at ``/mcp`` — same tools, same dispatch, same idempotency derived from
MCP session + request id (no REST-only header is ever involved).

Serve mode is the executor policy boundary: the app is constructed with
``serve_mode=True``, so builds run on a probed secure backend and the unsafe
local executor is refused with ``unsafe_refused`` — there is deliberately no
``--unsafe-local-executor`` flag on this verb.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

__all__ = ["add_subparsers", "parse_http_address", "serve"]

DEFAULT_HTTP_HOST = "127.0.0.1"
DEFAULT_HTTP_PORT = 8765


def parse_http_address(value: str) -> tuple[str, int]:
    """Parse ``HOST:PORT`` (or a bare ``PORT``) for ``--http``."""
    text = value.strip()
    if not text:
        raise ValueError("--http expects HOST:PORT")
    if ":" not in text:
        return DEFAULT_HTTP_HOST, int(text)
    host, _, port = text.rpartition(":")
    return (host or DEFAULT_HTTP_HOST), int(port)


def serve(*, http: str | None = None) -> int:
    """Run the MCP server on stdio, or on streamable HTTP when ``http`` is set."""
    from .app import build_app

    app, runtime = build_app(serve_mode=True)
    try:
        if http is None:
            app.run(transport="stdio", show_banner=False)
        else:
            host, port = parse_http_address(http)
            app.run(transport="http", host=host, port=port, show_banner=False)
    finally:
        runtime.close()
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    if not bool(getattr(args, "mcp", False)):
        # stdout is the MCP transport: diagnostics never go there.
        print("heph: serve: --mcp is required (no other surface is served yet)", file=sys.stderr)
        return 2
    return serve(http=getattr(args, "http", None))


def add_subparsers(sub: Any) -> None:
    """Register the ``serve`` verb on the ``heph`` CLI subparser action."""
    serve_parser = sub.add_parser("serve", help="serve the project over MCP")
    serve_parser.add_argument(
        "--mcp", action="store_true", help="serve the MCP tool surface (required)"
    )
    serve_parser.add_argument(
        "--http",
        default=None,
        metavar="HOST:PORT",
        help=(
            "serve streamable HTTP instead of stdio "
            f"(default {DEFAULT_HTTP_HOST}:{DEFAULT_HTTP_PORT})"
        ),
    )
    serve_parser.set_defaults(func=_cmd_serve)
