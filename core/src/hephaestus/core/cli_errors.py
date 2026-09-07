"""The shared CLI refusal boundary: one taxonomy, one exit code, one shape.

``docs/cli.md``'s exit-code contract is three-valued — 0 success, 1 the
operation ran and the answer was "no", 2 you asked for something impossible
(bad usage, no project, an unknown part, a refused capability). Before this
module every verb re-derived that judgement: ten modules defined their own
``_UsageError`` and eleven ``_guard()`` wrappers each caught a different
subset, so one condition ("not a Hephaestus project") reached the operator as
exit 1 with an ``error (validation_error):`` prefix on thirteen verbs and exit
2 with a bare ``heph:`` prefix on four (ledger J-cli-robustness-5), no wrapper
knew about ``--json`` (J-cli-robustness-6), and a module ``main()`` mapped
nothing at all (J-cli-robustness-20). An unwritable ``--out`` was the same
shape of gap one layer down (ledger B-10).

Everything a ``heph`` verb needs to refuse lives here, because all of it was
being copied per verb:

- :class:`CliUsageError` — the one exception every ``heph`` module raises for
  misuse. :func:`dispatch` maps it to exit 2.
- :func:`dispatch` — **the** taxonomy: engine exception in, exit code and one
  refusal line out. :func:`hephaestus.core.cli.main` is a call to it, and so is
  every module ``main()``, so a module entry point behaves like the product
  rather than raising a traceback where ``heph`` refuses.
- :func:`guard` — ``dispatch`` as a subcommand decorator, for the verb groups
  that register through ``add_subparsers``.
- :func:`project_root_or_refuse` — the single "am I in a project?" call. It is
  the one condition J-cli-robustness-5 is about: every verb must answer it the
  same way.
- :func:`require_input_file` — distinguishes "no such file" from "that is a
  directory", which six hand-copied ``not path.is_file()`` sites conflated.
- :func:`ensure_writable_dir` — the output precondition (ledger B-10). Called
  with the parsed output path before any work runs, it creates the directory
  (relative defaults such as ``heph render``'s ``render/`` must still be
  created, not refused) and converts an ``OSError`` into a refusal naming the
  flag and the OS reason.
- :func:`json_listing` — the ``--json`` listing envelope
  (J-cli-robustness-7): an object carrying ``status`` and one plural array key,
  never a bare array, so a generic wrapper can treat every list verb alike.
- :func:`refuse` — the reporter. ``--json`` callers get the refusal as a JSON
  object on stderr rather than a prose line, so one stream carries one
  parseable shape; stdout stays reserved for the result document and is left
  empty on a refusal, exactly as it is today.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Final

from hephaestus.core.errors import (
    AddressingError,
    HephaestusError,
    ValidationError,
)
from hephaestus.core.project_store.layout import find_project_root
from opstore.errors import OpStoreError

__all__ = [
    "CliUsageError",
    "dispatch",
    "ensure_writable_dir",
    "guard",
    "json_listing",
    "parse_content_hash",
    "project_root_or_refuse",
    "refuse",
    "require_input_file",
    "usage_from_oserror",
]


class CliUsageError(Exception):
    """CLI misuse: reported on stderr with exit code 2.

    The shared spelling of the ``_UsageError`` ten ``cli_*`` modules each grew
    their own copy of. :func:`dispatch` catches it, so the engine ``main()``,
    every verb group's ``guard()`` and every module entry point agree.
    """

    #: Machine-readable discriminator for the ``--json`` refusal shape.
    code = "usage"


_CONTENT_HASH_RE: Final[re.Pattern[str]] = re.compile(r"^(?:sha256:)?([0-9a-f]{64})$")


def parse_content_hash(value: str, *, flag: str) -> str:
    """Normalise a content hash to ``sha256:<64 hex>``, or refuse the malformed form.

    ``--expected-hash`` was checked for truthiness only, so any string became a
    "stale hash" conflict whose ``base_snapshot_ref`` was ``artifact:part-snapshot:``
    prefixed onto the user's typo — a malformed ref handed back as if it named
    something (ledger J-cli-robustness-16). ``docs/cli.md`` distinguishes a stale
    hash (a conflict, exit 1) from a missing one (usage, exit 2) and has no third
    case; malformed is usage, not a conflict. The bare 64-hex form is accepted
    because that is what a reader copies out of a filename or a provenance
    footer, and normalised so exactly one spelling reaches the store.

    This is the one grammar for both CLI surfaces. Its permanent home is
    ``hephaestus.core.hashing``, which owns hash *formatting*, so the dispatcher
    and the params paths can share it too; it lives here until that module's
    lane can take it (see the ledger item).
    """
    candidate = value.strip().lower()
    match = _CONTENT_HASH_RE.match(candidate)
    if match is None:
        raise CliUsageError(f"{flag} must be 'sha256:<64 hex>' (got {value!r})")
    return f"sha256:{match.group(1)}"


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


def require_input_file(path: Path, *, what: str) -> Path:
    """Refuse a missing input path *and* a directory, with different words.

    ``not path.is_file()`` is false for two unrelated reasons, and six sites
    copied the "no such file" wording for both, so ``heph lint .`` asserted
    that the current directory does not exist (ledger J-cli-robustness-12).
    ``what`` is the operator's noun for the argument — ``part script``,
    ``requirements file`` — so the message names the argument that was wrong.
    """
    if path.is_file():
        return path
    if path.is_dir():
        raise CliUsageError(f"{what} {path} is a directory: this argument takes one file")
    if path.exists():
        raise CliUsageError(f"{what} {path} is not a regular file")
    raise CliUsageError(f"no such {what}: {path}")


def project_root_or_refuse(start: Path | None = None) -> Path:
    """The project root, or exit 2 — one condition, one code, one message.

    ``find_project_root`` raises ``ValidationError``, which the engine taxonomy
    reports as exit 1 ("the operation ran and the answer was no"). Not being in
    a project is not that: it is ``docs/cli.md``'s exit 2, "you asked for
    something impossible", which is what ``core/src/hephaestus/core/cli.py``'s
    header has always documented. Every verb calls this rather than
    ``find_project_root`` so all fourteen answer alike (J-cli-robustness-5).
    """
    try:
        return find_project_root(Path.cwd() if start is None else start)
    except ValidationError as exc:
        raise CliUsageError(exc.message) from exc


def json_listing(key: str, rows: Sequence[Any], *, status: str = "ok") -> str:
    """Serialize a ``--json`` listing as ``{"status": …, "<key>": [...]}``.

    ``heph part list --json`` emitted an envelope and four sibling listings
    emitted bare arrays, which is simply what ``json.dumps`` of a list produces
    — nobody chose it (ledger J-cli-robustness-7). An array has nowhere to put
    a status or a future cursor, so a generic wrapper cannot treat list verbs
    uniformly. One object, one plural key.
    """
    return json.dumps({"status": status, key: list(rows)}, sort_keys=True)


def refuse(
    message: str,
    *,
    json_out: bool = False,
    code: str = "usage",
    candidates: Sequence[str] = (),
) -> None:
    """Print one refusal on stderr, as JSON when the caller asked for JSON.

    stdout is untouched either way: a refusal never produced a result document
    and must not start now, or ``--json`` consumers would have to distinguish
    the two shapes on the same stream.

    The prose form is the shape ``heph`` has always printed: a bare
    ``heph: <message>`` for a usage or addressing refusal (the operator asked
    for something impossible, and the code adds nothing they can act on) and
    ``heph: error (<code>): <message>`` for an engine refusal, whose code *is*
    the actionable fact.
    """
    payload: dict[str, Any] = {"status": "refused", "code": code, "message": message}
    if candidates:
        payload["candidates"] = list(candidates)
    if json_out:
        print(json.dumps(payload, sort_keys=True), file=sys.stderr)
        return
    detail = message
    if candidates:
        detail += f" (candidates: {', '.join(candidates)})"
    if code in ("usage", AddressingError.code):
        print(f"heph: {detail}", file=sys.stderr)
    else:
        print(f"heph: error ({code}): {detail}", file=sys.stderr)


def _alternatives(exc: AddressingError) -> Sequence[str]:
    """``exc``'s candidates, unless they are not alternatives at all.

    Candidates answer "which name did you mean instead?", so a list containing
    the selector verbatim answers nothing: the name resolved fine and something
    *else* about it failed. That is exactly the case ledger
    J-cli-robustness-10 is about — a part that exists but has no current
    successful build refuses with the whole part list, offering the part as an
    alternative to itself and re-blurring the distinction between "does not
    exist" and "was never built" at the reporting layer. Enforced here rather
    than at each raise site because the invariant is a property of the
    vocabulary (``core/errors.py``: near-misses "when nothing matched"), and
    because two of the sites that break it are engine code a refusal has no
    business editing. An *ambiguous* selector is left alone: there the
    candidates are the several things it really did match, and it may legally
    be one of them.
    """
    if exc.reason == "unresolved" and exc.selector in exc.candidates:
        return ()
    return exc.candidates


def dispatch(command: Callable[[argparse.Namespace], int], args: argparse.Namespace) -> int:
    """Run one subcommand and map the engine taxonomy to an exit code.

    The single place ``docs/cli.md``'s exit-code table is implemented. Exit 2
    is "you asked for something impossible" — misuse, no project, an unknown
    part, an OS path that cannot be used; exit 1 is "the operation ran and the
    answer was no". ``--json`` is read off the parsed namespace rather than
    threaded through every call site, so a verb without the flag reports prose
    and one with it reports the same facts as an object.
    """
    json_out = bool(getattr(args, "json", False))
    try:
        return command(args)
    except CliUsageError as exc:
        refuse(str(exc), json_out=json_out, code=exc.code)
        return 2
    except AddressingError as exc:
        # §7's candidates are the actionable half of an addressing refusal and
        # are dropped by any handler that reports `str(exc)`; they travel in
        # both shapes here.
        refuse(
            exc.message,
            json_out=json_out,
            code=exc.code,
            candidates=_alternatives(exc),
        )
        return 2
    except OpStoreError as exc:
        # The store's own taxonomy is not a `HephaestusError`, so before this
        # branch every opstore refusal left the CLI as a traceback. §19.40 made
        # that reachable on the ordinary path: `Publisher.freeze_inputs` runs
        # `gc.admission_guard()`, so a project whose protected bytes exceed its
        # quota refuses `protected_quota_exceeded` on `heph build` — the refusal
        # §22.6 calls "the most confusing failure this section is capable of
        # producing", which a stack trace would make worse rather than better.
        refuse(exc.message, json_out=json_out, code=exc.code)
        return 1
    except HephaestusError as exc:
        # Covers SandboxDeniedError, ValidationError, ConflictError and the rest
        # of core/DESIGN.md's vocabulary: the operation ran and the answer was no.
        refuse(exc.message, json_out=json_out, code=exc.code)
        return 1
    except OSError as exc:
        # Last-resort net beneath the output preconditions (ledger B-10). Every
        # verb that takes an operator-supplied path validates it up front with
        # `ensure_writable_dir`, which refuses by name; this arm catches the OS
        # failures no precondition can anticipate (a filesystem that fills
        # between the check and the write, a revoked mount) and reports them as
        # what they are — "you asked for something impossible", exit 2 — rather
        # than as an interpreter traceback.
        reason = exc.strerror or exc.__class__.__name__
        detail = f"{reason} ({exc.filename})" if exc.filename else reason
        refuse(detail, json_out=json_out)
        return 2


def guard(
    command: Callable[[argparse.Namespace], int],
) -> Callable[[argparse.Namespace], int]:
    """:func:`dispatch` as a subcommand decorator.

    ``argparse`` stores one callable per verb, so a verb group registers
    ``guard(handler)`` and every entry point — ``heph``, a module ``main()``,
    a test calling the stored ``func`` directly — gets the same taxonomy.
    """

    def run(args: argparse.Namespace) -> int:
        return dispatch(command, args)

    return run
