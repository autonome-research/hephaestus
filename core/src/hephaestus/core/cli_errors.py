"""The shared CLI refusal boundary: usage errors, output preconditions, guards.

``docs/cli.md``'s exit-code contract is three-valued — 0 success, 1 the
operation ran and the answer was "no", 2 you asked for something impossible
(bad usage, a refused capability). An unwritable ``--out`` is the third kind,
and before this module every output verb re-derived that judgement (or, more
often, did not): each did a bare ``mkdir`` on operator-supplied output *after*
the expensive work, so the failure arrived as an interpreter traceback with the
computed program, images or scaffold already thrown away (ledger B-10).

Three things live here, because all three were being copied per verb:

- :class:`CliUsageError` — one exception every ``heph`` module can raise and
  :func:`hephaestus.core.cli.main` already maps to exit 2. Modules that predate
  it still define a private ``_UsageError``; new refusals should use this one.
- :func:`ensure_writable_dir` — the *precondition*. Called with the parsed
  output path before any work runs, it creates the directory (relative defaults
  such as ``heph render``'s ``render/`` must still be created, not refused) and
  converts an ``OSError`` into a refusal naming the flag and the OS reason.
- :func:`guard` / :func:`refuse` — the reporter. ``--json`` callers get the
  refusal as a JSON object on stderr rather than a prose line, so one stream
  carries one parseable shape; stdout stays reserved for the result document
  and is left empty on a refusal, exactly as it is today.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path

__all__ = [
    "CliUsageError",
    "ensure_writable_dir",
    "guard",
    "refuse",
    "usage_from_oserror",
]


class CliUsageError(Exception):
    """CLI misuse: reported on stderr with exit code 2.

    The shared spelling of the ``_UsageError`` every ``cli_*`` module grew its
    own copy of. :func:`hephaestus.core.cli.main` catches it, and :func:`guard`
    catches it for the standalone entry points (``heph render``'s module
    ``main``) that do not run through the engine taxonomy.
    """

    #: Machine-readable discriminator for the ``--json`` refusal shape.
    code = "usage"


def usage_from_oserror(exc: OSError, *, subject: str) -> CliUsageError:
    """Convert an ``OSError`` into a refusal that names *what* failed and *why*.

    ``subject`` is the operator-visible thing that could not be used — a flag
    and its value, or a target directory. The OS reason and offending filename
    come from the exception, because "Permission denied" without the path it
    was denied on is the traceback's only useful line minus the path.
    """
    reason = exc.strerror or exc.__class__.__name__
    filename = exc.filename
    detail = f"{reason} ({filename})" if filename else reason
    return CliUsageError(f"{subject}: {detail}")


def ensure_writable_dir(directory: Path, *, flag: str) -> Path:
    """Create ``directory`` now, or refuse by name — the output precondition.

    Run this on the *parsed* output path before the work starts. Creating is
    the correct behaviour rather than refusing a missing path: ``heph render``
    defaults ``--out`` to the relative ``render/``, which has never had to
    exist beforehand. What is refused is a path that cannot be made or written:
    an unwritable parent, a file where a directory was named, a read-only
    existing directory.
    """
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise usage_from_oserror(exc, subject=f"{flag} {directory}") from exc
    if not os.access(directory, os.W_OK):
        raise CliUsageError(f"{flag} {directory}: Permission denied ({directory})")
    return directory


def refuse(message: str, *, json_out: bool = False, code: str = "usage") -> None:
    """Print one refusal on stderr, as JSON when the caller asked for JSON.

    stdout is untouched either way: a refusal never produced a result document
    and must not start now, or ``--json`` consumers would have to distinguish
    the two shapes on the same stream.
    """
    if json_out:
        print(
            json.dumps({"status": "refused", "code": code, "message": message}, sort_keys=True),
            file=sys.stderr,
        )
    else:
        print(f"heph: {message}", file=sys.stderr)


def guard(
    command: Callable[[argparse.Namespace], int],
) -> Callable[[argparse.Namespace], int]:
    """Wrap a subcommand so :class:`CliUsageError` is exit 2, not a traceback.

    ``--json`` is read off the parsed namespace rather than threaded through
    every call site, so a verb without the flag simply reports prose.
    """

    def run(args: argparse.Namespace) -> int:
        try:
            return command(args)
        except CliUsageError as exc:
            refuse(str(exc), json_out=bool(getattr(args, "json", False)), code=exc.code)
            return 2

    return run
