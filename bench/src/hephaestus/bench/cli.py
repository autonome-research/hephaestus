"""Minimal standalone dispatcher for the bench verbs.

``heph`` proper registers the bench verb by calling
:func:`hephaestus.bench.cli_bench.add_subparsers` (mirroring how
``hephaestus.core.cli`` registers the render and agent verbs), so the engine CLI
keeps working without the bench stack installed. This module is the equivalent
entry point when the engine CLI is not involved — it prefixes the ``bench`` verb
and hands the argv to the same handlers::

    uv run python -m hephaestus.bench.cli run --dry-run
    uv run python -m hephaestus.bench.cli score bench/results/<model>/<date>

Exit codes match :mod:`hephaestus.bench.cli_bench` (0 success, 1 error / gate not
met, 2 usage).
"""

from __future__ import annotations

from . import cli_bench

__all__ = ["main"]

#: The verb ``cli_bench`` registers; this dispatcher supplies it implicitly.
VERB = "bench"


def main(argv: list[str] | None = None) -> int:
    """Dispatch ``run``/``score`` through the shared :mod:`cli_bench` handlers."""
    return cli_bench.main([VERB, *(argv if argv is not None else [])])


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
