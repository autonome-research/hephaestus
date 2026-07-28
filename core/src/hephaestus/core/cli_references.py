"""``heph reference`` CLI verbs: add, list, remove (``INGEST.md`` §2).

Reference registration is **operator-side, on purpose**. The model's surface is
``list_references``/``read_reference`` and nothing else: there is no tool that
adds a reference, so the only ways one enters a project are this verb group and
a bench task fixture. Keeping the verbs here (rather than in
:mod:`hephaestus.core.cli`) matches ``cli_registry``/``cli_render``: the store
and the reference registry load only when a reference verb runs.

- ``heph reference add <file> [--name NAME] [--json]`` copies the file into
  ``references/`` and registers it: payload bytes into the opstore CAS, a new
  immutable registry generation under the project-config lock, and — for a
  document — its extracted per-page text stored alongside so every later read
  and every ``heph lint`` citation check works off the same text.
- ``heph reference list [--json]`` reports name, kind, mime type, page count
  and content hash.
- ``heph reference remove <name> [--json]`` deregisters and deletes the copy.

PDF extraction needs the pypdf-backed extractor that ships with
``hephaestus-server``; it is imported lazily and its absence is reported as
``capability_not_available`` rather than registering an unverifiable document.
Text, markdown and images need nothing beyond the engine.

Exit codes match the engine CLI: 0 success, 1 error, 2 usage.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import cast

from hephaestus.core.project_store.layout import find_project_root, load_project, open_store
from hephaestus.core.project_store.references import ReferenceRegistry, TextExtractor

from opstore import OpStore

__all__ = ["add_subparsers", "resolve_extractor"]


class _UsageError(Exception):
    """CLI misuse: reported on stderr with exit code 2."""


def resolve_extractor() -> TextExtractor | None:
    """The server's pypdf extractor when installed, else ``None``.

    Core deliberately does not depend on ``pypdf``; a core-only installation
    registers text/markdown/image references normally and reports the missing
    capability by name when asked to register a PDF.
    """
    try:
        from hephaestus.agent_bridge.references_pdf import pdf_extractor
    except ImportError:
        return None
    return pdf_extractor()


def _registry(start: Path) -> tuple[ReferenceRegistry, OpStore]:
    root = find_project_root(start)
    layout = load_project(root)
    store = open_store(layout)
    return (ReferenceRegistry(layout, store), store)


def _cmd_add(args: argparse.Namespace) -> int:
    source = Path(cast("str", args.path))
    if not source.is_file():
        raise _UsageError(f"no such file: {source}")
    registry, store = _registry(Path.cwd())
    try:
        entry = registry.add_file(
            source,
            name=cast("str | None", args.name),
            extractor=resolve_extractor(),
        )
    finally:
        store.close()
    if bool(args.json):
        print(json.dumps(entry.listing(), sort_keys=True))
    else:
        pages = "" if entry.pages is None else f", {entry.pages} page(s)"
        print(f"registered {entry.name} ({entry.kind}, {entry.mime_type}{pages}) {entry.sha256}")
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    registry, store = _registry(Path.cwd())
    try:
        entries = registry.list_references()
    finally:
        store.close()
    if bool(args.json):
        print(json.dumps([entry.listing() for entry in entries], sort_keys=True))
        return 0
    if not entries:
        print("no references registered")
        return 0
    for entry in entries:
        pages = "" if entry.pages is None else f" pages={entry.pages}"
        print(f"{entry.name}\t{entry.kind}\t{entry.mime_type}{pages}\t{entry.sha256}")
    return 0


def _cmd_remove(args: argparse.Namespace) -> int:
    registry, store = _registry(Path.cwd())
    try:
        entry = registry.remove(cast("str", args.name))
    finally:
        store.close()
    if bool(args.json):
        print(json.dumps(entry.listing(), sort_keys=True))
    else:
        print(f"removed {entry.name}")
    return 0


def _guard(command: Callable[[argparse.Namespace], int]) -> Callable[[argparse.Namespace], int]:
    """Report reference-verb misuse as exit 2 regardless of the entry point."""

    def run(args: argparse.Namespace) -> int:
        try:
            return command(args)
        except _UsageError as exc:
            print(f"heph: {exc}", file=sys.stderr)
            return 2

    return run


def add_subparsers(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
) -> None:
    """Register the ``reference`` verb group on an existing subparser set."""
    reference = sub.add_parser(
        "reference", help="register operator-supplied reference documents and images"
    )
    verbs = reference.add_subparsers(dest="reference_command", required=True)

    add = verbs.add_parser("add", help="copy a file into references/ and register it")
    add.add_argument("path", help="file to register (pdf, txt, md, png, jpg)")
    add.add_argument("--name", default=None, help="register under this name (default: filename)")
    add.add_argument("--json", action="store_true", help="emit the registry entry as JSON")
    add.set_defaults(func=_guard(_cmd_add))

    listing = verbs.add_parser("list", help="list registered references")
    listing.add_argument("--json", action="store_true", help="emit JSON records")
    listing.set_defaults(func=_guard(_cmd_list))

    remove = verbs.add_parser("remove", help="deregister a reference and delete its copy")
    remove.add_argument("name", help="registered reference name")
    remove.add_argument("--json", action="store_true", help="emit the removed entry as JSON")
    remove.set_defaults(func=_guard(_cmd_remove))
