# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""``heph serve --web`` — the workspace half of the serve verb's parser.

``INTERFACE.md`` §2.1's **DECISION (binds G4.8)**: ``--web [HOST:PORT]`` is
*orthogonal* to ``--mcp``. ``--mcp`` remains required for the MCP transport and
is not required for ``--web``; what survives unchanged is the invariant that
matters — both force ``serve_mode=True``, so the secure backend is probed and
``--unsafe-local-executor`` remains absent from this verb.

This module exists as a separate half of one verb for a dependency reason, not a
stylistic one. ``server/http`` is a web client API and **not part of the headless
surface** (the 2026-07-26 ordering amendment), so
:mod:`hephaestus.mcp.cli_serve` may not import it. The ``heph`` parser builder
therefore assembles the ``serve`` verb from both halves: ``cli_serve`` creates
the parser and owns ``--mcp``, this module extends it with ``--web``, and
``server/tests/test_http_boundary.py`` asserts the direction mechanically so the
arrangement cannot quietly invert.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from typing import cast

__all__ = ["extend_serve"]


def extend_serve(parser: argparse.ArgumentParser) -> None:
    """Add ``--web`` / ``--web-address`` to the ``serve`` verb, and route them."""
    parser.add_argument(
        "--web", action="store_true", help="serve the web workspace API (INTERFACE.md §2)"
    )
    # ``--web`` deliberately takes no optional inline value: argparse's
    # ``nargs="?"`` form silently swallows a following token, which on a verb
    # that may grow a positional is a bug waiting for its first user. The
    # address is its own flag.
    parser.add_argument(
        "--web-address",
        default=None,
        metavar="HOST:PORT",
        dest="web_address",
        help="bind address for --web (loopback only; default 127.0.0.1:8760)",
    )
    inner = cast("Callable[[argparse.Namespace], int]", parser.get_default("func"))
    parser.set_defaults(func=_router(inner))


def _router(
    inner: Callable[[argparse.Namespace], int],
) -> Callable[[argparse.Namespace], int]:
    """Route ``--web`` here; hand everything else to the MCP half unchanged."""

    def command(args: argparse.Namespace) -> int:
        if not bool(getattr(args, "web", False)):
            return inner(args)
        if bool(getattr(args, "mcp", False)):
            # §2.1 DECISION: the two flags are orthogonal and both force
            # serve_mode=True. Serving both from one process is the intended end
            # state; what is not built is the single event loop that would run
            # FastMCP's transport and the workspace app together — so the
            # combination is refused **by name** rather than silently serving one
            # of them and leaving the operator to discover which.
            print(
                "heph: serve: --mcp and --web in one process is not implemented; "
                "run two processes, or pick one",
                file=sys.stderr,
            )
            return 2
        from .serve import serve_web

        return serve_web(web=getattr(args, "web_address", None))

    return command
