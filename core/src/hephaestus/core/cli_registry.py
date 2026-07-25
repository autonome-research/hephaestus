"""``heph registry`` CLI verbs: list, pin, update, verify (hash-pinned registries).

Kept out of :mod:`hephaestus.core.cli` so the registry stack loads only when a
registry verb runs; ``cli.build_parser`` registers these through
:func:`add_subparsers` and every other verb is untouched.

- ``heph registry list [--json]`` resolves the project's ``[registries]`` pins
  (falling back to the registries bundled with this installation) and reports
  each registry's kind, version, path, live Merkle digest, and pin state.
- ``heph registry pin <name> [--path DIR] [--json]`` records a registry's
  current digest in ``hephaestus.toml``. It refuses to *change* an existing
  pin — that is what ``update`` is for — so accepting new bytes is always a
  deliberate act.
- ``heph registry update [name ...] [--json]`` is the only re-pin path:
  recompute each named (or every pinned) registry's digest and write it.
- ``heph registry verify [name ...] [--json]`` re-hashes each pinned tree and
  fails when a tree drifted from its pin **or** is not pinned at all.

Exit codes match the engine CLI: 0 success, 1 error (drift, unpinned tree),
2 usage (unknown registry, missing path).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import cast

from hephaestus.core.errors import ValidationError
from hephaestus.core.project_store.layout import find_project_root
from hephaestus.core.registry import (
    MANIFEST_FILENAME,
    RegistryIntegrityError,
    RegistryPin,
    bundled_pins,
    load_registry,
    merkle_digest,
    read_pins,
    write_pins,
)
from opstore.types import JSONValue

__all__ = ["add_subparsers", "main"]


class _UsageError(Exception):
    """CLI misuse: reported on stderr with exit code 2."""


def _project_root() -> Path:
    try:
        return find_project_root(Path.cwd())
    except ValidationError as exc:
        raise _UsageError(exc.message) from exc


def _resolved_pins(project_root: Path) -> dict[str, RegistryPin]:
    """Project pins, with the bundled registries filling any gap."""
    pins = dict(read_pins(project_root))
    for name, pin in bundled_pins().items():
        pins.setdefault(name, pin)
    return pins


def _select(pins: dict[str, RegistryPin], names: list[str]) -> list[str]:
    if not names:
        return sorted(pins)
    unknown = sorted(name for name in names if name not in pins)
    if unknown:
        known = ", ".join(sorted(pins)) or "(none)"
        raise _UsageError(f"unknown registry {', '.join(unknown)}; known registries: {known}")
    return sorted(set(names))


def _describe(name: str, pin: RegistryPin, project_root: Path) -> dict[str, JSONValue]:
    root = pin.resolve(project_root)
    record: dict[str, JSONValue] = {
        "name": name,
        "path": str(root),
        "pinned_digest": pin.digest,
        "pinned": pin.digest is not None,
    }
    if not (root / MANIFEST_FILENAME).is_file():
        record["status"] = "missing"
        return record
    digest = merkle_digest(root)
    record["digest"] = digest
    if pin.digest is None:
        record["status"] = "unpinned"
    elif pin.digest == digest:
        record["status"] = "ok"
    else:
        record["status"] = "drifted"
    try:
        registry = load_registry(root)
    except ValidationError as exc:
        record["status"] = "invalid"
        record["detail"] = exc.message
        return record
    record["kind"] = registry.kind
    record["version"] = registry.manifest.version
    record["registry_name"] = registry.manifest.name
    record["license"] = registry.manifest.license
    return record


# --------------------------------------------------------------------------
# commands


def _cmd_list(args: argparse.Namespace) -> int:
    project_root = _project_root()
    pins = _resolved_pins(project_root)
    records = [_describe(name, pins[name], project_root) for name in sorted(pins)]
    if bool(args.json):
        print(json.dumps(records))
        return 0
    if not records:
        print("no registries resolved (no [registries] pins and no bundled registries)")
        return 0
    for record in records:
        print(f"{record['name']}: {record['status']} ({record.get('kind', '?')})")
        print(f"  path:   {record['path']}")
        print(f"  digest: {record.get('digest', '(unreadable)')}")
        if record["pinned_digest"] is not None and record["status"] == "drifted":
            print(f"  pinned: {record['pinned_digest']}")
    return 0


def _cmd_pin(args: argparse.Namespace) -> int:
    project_root = _project_root()
    name = cast("str", args.name)
    pins = dict(read_pins(project_root))
    path = cast("str | None", args.path)
    if path is None:
        candidate = pins.get(name) or bundled_pins().get(name)
        if candidate is None:
            raise _UsageError(f"registry {name!r} has no recorded path; pass --path DIR")
        path = candidate.path
    root = RegistryPin(name=name, path=path).resolve(project_root)
    if not (root / MANIFEST_FILENAME).is_file():
        raise _UsageError(f"{root} is not a registry ({MANIFEST_FILENAME} missing)")
    digest = merkle_digest(root)
    existing = pins.get(name)
    if existing is not None and existing.digest is not None and existing.digest != digest:
        print(
            f"heph: error (registry_integrity): {name!r} is pinned at {existing.digest} "
            f"but {root} hashes to {digest}; run 'heph registry update {name}' to accept it",
            file=sys.stderr,
        )
        return 1
    pins[name] = RegistryPin(name=name, path=path, digest=digest)
    write_pins(project_root, pins)
    _report_pin(name, root, digest, json_out=bool(args.json), verb="pinned")
    return 0


def _cmd_update(args: argparse.Namespace) -> int:
    project_root = _project_root()
    pins = dict(read_pins(project_root))
    for name, pin in bundled_pins().items():
        pins.setdefault(name, pin)
    selected = _select(pins, cast("list[str]", args.name))
    updated: list[dict[str, JSONValue]] = []
    for name in selected:
        pin = pins[name]
        root = pin.resolve(project_root)
        if not (root / MANIFEST_FILENAME).is_file():
            raise _UsageError(f"{root} is not a registry ({MANIFEST_FILENAME} missing)")
        digest = merkle_digest(root)
        updated.append(
            {
                "name": name,
                "path": str(root),
                "previous_digest": pin.digest,
                "digest": digest,
                "changed": pin.digest != digest,
            }
        )
        pins[name] = RegistryPin(name=name, path=pin.path, digest=digest)
    write_pins(project_root, pins)
    if bool(args.json):
        print(json.dumps(updated))
        return 0
    for record in updated:
        mark = "re-pinned" if record["changed"] else "unchanged"
        print(f"{record['name']}: {mark} {record['digest']}")
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    project_root = _project_root()
    pins = _resolved_pins(project_root)
    selected = _select(pins, cast("list[str]", args.name))
    records: list[dict[str, JSONValue]] = []
    failed = False
    for name in selected:
        pin = pins[name]
        root = pin.resolve(project_root)
        record: dict[str, JSONValue] = {"name": name, "path": str(root)}
        if pin.digest is None:
            record["status"] = "unpinned"
            record["detail"] = "no digest in hephaestus.toml; run 'heph registry pin'"
            failed = True
        else:
            try:
                registry = load_registry(root, expected_digest=pin.digest)
            except RegistryIntegrityError as exc:
                record["status"] = "drifted"
                record["expected_digest"] = exc.expected
                record["digest"] = exc.actual
                record["detail"] = exc.message
                failed = True
            except ValidationError as exc:
                record["status"] = "invalid"
                record["detail"] = exc.message
                failed = True
            else:
                record["status"] = "ok"
                record["digest"] = registry.digest
                record["kind"] = registry.kind
        records.append(record)
    if bool(args.json):
        print(json.dumps(records))
    else:
        for record in records:
            print(f"{record['name']}: {record['status']}")
            detail = record.get("detail")
            if isinstance(detail, str):
                print(f"  {detail}")
        if not records:
            print("no registries to verify")
    return 1 if failed else 0


def _report_pin(name: str, root: Path, digest: str, *, json_out: bool, verb: str) -> None:
    if json_out:
        print(json.dumps({"name": name, "path": str(root), "digest": digest}))
    else:
        print(f"{name}: {verb} {digest}")
        print(f"  path: {root}")


def _guard(command: Callable[[argparse.Namespace], int]) -> Callable[[argparse.Namespace], int]:
    """Report registry-verb misuse as exit 2 regardless of which entry point ran it."""

    def run(args: argparse.Namespace) -> int:
        try:
            return command(args)
        except _UsageError as exc:
            print(f"heph: {exc}", file=sys.stderr)
            return 2

    return run


# --------------------------------------------------------------------------
# entrypoint


def add_subparsers(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
) -> None:
    """Register the ``registry`` verb group on an existing subparser set."""
    registry = sub.add_parser("registry", help="inspect and pin content registries")
    verbs = registry.add_subparsers(dest="registry_command", required=True)

    listing = verbs.add_parser("list", help="list resolved registries and their digests")
    listing.add_argument("--json", action="store_true", help="emit JSON records")
    listing.set_defaults(func=_guard(_cmd_list))

    pin = verbs.add_parser("pin", help="record a registry's current digest (never changes a pin)")
    pin.add_argument("name", help="registry name (the [registries.<name>] key)")
    pin.add_argument("--path", default=None, metavar="DIR", help="registry directory to pin")
    pin.add_argument("--json", action="store_true", help="emit JSON records")
    pin.set_defaults(func=_guard(_cmd_pin))

    update = verbs.add_parser("update", help="re-pin registries to their current digests")
    update.add_argument("name", nargs="*", default=[], help="registries to re-pin (default: all)")
    update.add_argument("--json", action="store_true", help="emit JSON records")
    update.set_defaults(func=_guard(_cmd_update))

    verify = verbs.add_parser("verify", help="verify every pinned registry tree")
    verify.add_argument("name", nargs="*", default=[], help="registries to verify (default: all)")
    verify.add_argument("--json", action="store_true", help="emit JSON records")
    verify.set_defaults(func=_guard(_cmd_verify))


def main(argv: list[str] | None = None) -> int:
    """Standalone entry point (``python -m hephaestus.core.cli_registry``) for tests."""
    parser = argparse.ArgumentParser(prog="heph", description="Hephaestus registry verbs")
    sub = parser.add_subparsers(dest="command", required=True)
    add_subparsers(sub)
    args = parser.parse_args(argv)
    command = cast("Callable[[argparse.Namespace], int]", args.func)
    return command(args)


if __name__ == "__main__":
    sys.exit(main())
