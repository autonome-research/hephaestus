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

``--project DIR`` (default: the working directory) is registered here for the
same reason ``--web`` is: it is the web half's flag, and it is spelled and
resolved exactly as ``heph agent --project`` so the two verbs cannot disagree
about which project they are serving and discovering. A ``DIR`` that is not
inside a project is refused by ``find_project_root`` with the ordinary
``validation_error`` — the identical answer the working-directory path gives,
because it *is* that path with a different starting point. A ``DIR`` that is
not a *directory* is refused one step earlier, here: ``find_project_root``
walks upward from a non-strict ``resolve()``, so a mistyped name or a path
pointing at ``hephaestus.toml`` itself would otherwise resolve to the nearest
ancestor project and serve *that* — a different project than the operator
named, with no diagnostic. That guard is a *narrowing*, not a divergence:
every ``DIR`` that is a real directory still resolves through
``find_project_root`` exactly as ``heph agent --project`` resolves it, so the
two verbs still cannot land on different roots for the same input, and
``heph agent --project`` refuses a non-directory the same way, by name and with
the same exit status (:mod:`hephaestus.agent_bridge.cli`), so the two verbs
answer alike for every ``DIR`` — real or mistyped.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path
from typing import cast

__all__ = ["extend_serve"]


def extend_serve(parser: argparse.ArgumentParser) -> None:
    """Add ``--web`` / ``--web-address`` / ``--project`` to ``serve``, and route them."""
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
    # Mirrors `heph agent --project` exactly — same spelling, same metavar, same
    # default, and the same resolution (`find_project_root` from that directory).
    # That symmetry is the point rather than a convenience: the two verbs must
    # agree on *which* project they are talking about, because `heph agent`
    # discovers this serve by reading `<root>/.heph/serve.json` (INTERFACE.md
    # §2.1, "no new flag"). Resolving the same DIR through the same function
    # means both land on the same root and therefore on the same record.
    parser.add_argument(
        "--project",
        default=None,
        metavar="DIR",
        help="project directory for --web (default: cwd)",
    )
    inner = cast("Callable[[argparse.Namespace], int]", parser.get_default("func"))
    parser.set_defaults(func=_router(inner))


def _router(
    inner: Callable[[argparse.Namespace], int],
) -> Callable[[argparse.Namespace], int]:
    """Route ``--web`` here; hand everything else to the MCP half unchanged."""

    def command(args: argparse.Namespace) -> int:
        project = cast("str | None", getattr(args, "project", None))
        if not bool(getattr(args, "web", False)):
            if project is not None:
                # Accepting and ignoring it would be the worst answer: the
                # operator would believe they had aimed the MCP transport at a
                # project it never looked at. The MCP half resolves the project
                # from the working directory, and saying so is one line.
                print(
                    "heph: serve: --project applies to --web; the MCP transport resolves "
                    "the project from the working directory",
                    file=sys.stderr,
                )
                return 2
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

        # `expanduser` here rather than in `serve_web`: it is a shell-shaped
        # courtesy owed to a string that came off a command line, and the
        # library entry point takes a `Path` that a caller has already meant.
        root = Path(project).expanduser() if project is not None else None
        if root is not None and not root.is_dir():
            # `find_project_root` resolves non-strictly and then walks *up*, so a
            # typo'd or file-shaped DIR does not fail — it quietly lands on the
            # nearest ancestor project and serves that one instead. Serving a
            # different project than the operator named is the expensive kind of
            # silence: the token, the serve record and the leases all go to the
            # wrong root. The walk-up is the right behaviour for a directory that
            # merely sits *inside* a project; it is the wrong behaviour for a
            # path that is not a directory at all, so that is the only case
            # refused here, by name, before `serve_web` sees it.
            print(
                f"heph: serve: --project {project}: not a directory",
                file=sys.stderr,
            )
            return 2
        return serve_web(web=getattr(args, "web_address", None), root=root)

    return command
