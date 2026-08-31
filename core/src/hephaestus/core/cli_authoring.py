"""Agent-shaped ``heph`` verbs: part / script / params / prompt.

Headless agents (Cursor, Codex, a shell script) drive Hephaestus through these
verbs plus the existing ``heph build`` / ``heph lint``. They are the CLI
counterparts of ``list_parts``, ``create_part``, ``write_part``, ``read_part``,
and the ``PARAMS`` / request-text reads — same store contract, no MCP, no web
UI, no second scripting language.

- ``heph part list [--json]`` — the ``list_parts`` projection.
- ``heph part create NAME [--template T] [--file PATH|-] [--json]`` —
  ``create_part`` (``base_hash=None``; refuses ``already_exists``).
- ``heph part show NAME [--json]`` — the last published ``BuildResult``, or
  the named absence ``not_built``.
- ``heph script show NAME [--json]`` — ``read_part`` (script + hashes).
- ``heph script write NAME [--file PATH|-] --expected-hash HASH [--json]`` —
  ``write_part`` (optimistic CAS; conflict is a discriminated result).
- ``heph params [PART] [--json]`` — declared ``PARAMS`` plus last-build
  effective values. No sandbox.
- ``heph prompt`` / ``heph prompt set`` — the operator request text stored at
  ``.heph/request.txt``. Not a hosted chat and not a context envelope
  (``INTERFACE.md`` §7A.3).

Exit codes match the engine CLI: 0 success, 1 the operation ran and the answer
was no (already exists, CAS conflict), 2 usage.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, cast

from hephaestus.core.params import Param, static_params
from hephaestus.core.part_templates import PART_TEMPLATES, TEMPLATE_NAMES
from hephaestus.core.project_store.layout import (
    find_project_root,
    load_project,
    open_store,
)
from hephaestus.core.project_store.listing import list_parts_projection
from hephaestus.core.project_store.publication import Publisher
from hephaestus.core.project_store.store import ProjectStore, WriteConflictError

from opstore import OpStore

__all__ = ["REQUEST_FILENAME", "add_subparsers"]

_PART_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

#: Project-relative path of the request text ``heph prompt`` reads and writes.
#: Lives under ``.heph/`` so it is gitignored with the rest of the store; it is
#: not a model turn and it is not a context envelope.
REQUEST_FILENAME = ".heph/request.txt"


class _UsageError(Exception):
    """CLI misuse: reported on stderr with exit code 2."""


def _project() -> tuple[Path, ProjectStore, OpStore]:
    root = find_project_root(Path.cwd())
    layout = load_project(root)
    opstore = open_store(layout)
    return root, ProjectStore(layout, opstore), opstore


def _require_part_name(name: str) -> str:
    if not _PART_NAME_RE.match(name):
        raise _UsageError(f"invalid part name {name!r}")
    return name


def _read_source(*, file_arg: str | None, allow_empty: bool, required: bool) -> str:
    """Read a part script (or request text) from ``--file`` or stdin.

    ``file_arg`` is a path, ``-`` for stdin, or ``None``. When ``required`` is
    true and nothing was named, stdin is used if it is not a TTY; a TTY with
    no file is usage. ``allow_empty`` is for ``heph prompt set`` of an empty
    request (a known absence), not for a part script.
    """
    if file_arg is None:
        if required and sys.stdin.isatty():
            raise _UsageError("script source required: pass --file PATH or --file -")
        source = sys.stdin.read()
    elif file_arg == "-":
        source = sys.stdin.read()
    else:
        path = Path(file_arg)
        if not path.is_file():
            raise _UsageError(f"no such file: {path}")
        source = path.read_text(encoding="utf-8")
    if not source and not allow_empty:
        raise _UsageError("script source is empty")
    return source


def _emit(payload: Mapping[str, Any], *, json_out: bool, human: str) -> None:
    if json_out:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(human)


def _conflict_payload(exc: WriteConflictError) -> dict[str, Any]:
    return {
        "applied": False,
        "conflict": {
            "current_hash": exc.live_hash,
            "current_script": exc.live_content,
            "current_snapshot_ref": exc.live_snapshot_ref,
            "base_snapshot_ref": exc.base_ref,
            "attempted_snapshot_ref": exc.attempted_ref,
        },
    }


# --------------------------------------------------------------------------
# heph part


def _cmd_part_list(args: argparse.Namespace) -> int:
    root, store, opstore = _project()
    try:
        payload = list_parts_projection(root, store)
    finally:
        opstore.close()
    if bool(args.json):
        print(json.dumps(payload, sort_keys=True))
        return 0
    parts = cast("list[dict[str, Any]]", payload["parts"])
    if not parts:
        print("no parts")
        return 0
    for entry in parts:
        print(f"{entry['name']}\t{entry['path']}\t{entry['content_hash']}")
    return 0


def _cmd_part_create(args: argparse.Namespace) -> int:
    name = _require_part_name(cast("str", args.name))
    file_arg = cast("str | None", args.file)
    template = cast("str", args.template)
    if file_arg is not None:
        script = _read_source(file_arg=file_arg, allow_empty=False, required=True)
    else:
        script = PART_TEMPLATES.get(template, PART_TEMPLATES["blank"])
    root, store, opstore = _project()
    try:
        try:
            outcome = store.write_part(
                name, script, base_hash=None, op_id=f"heph-part-create-{uuid.uuid4().hex}"
            )
        except WriteConflictError:
            payload = {"status": "already_exists", "part": name}
            if bool(args.json):
                print(json.dumps(payload, sort_keys=True))
            else:
                print(
                    f"heph: error (already_exists): part {name!r} already exists",
                    file=sys.stderr,
                )
            return 1
        snap = outcome.snapshot
        rel = str(snap.path.relative_to(root))
        payload = {
            "status": "ok",
            "path": rel,
            "initial_script": snap.content,
            "content_hash": snap.content_hash,
            "snapshot_ref": snap.snapshot_ref,
            "replayed": outcome.replayed,
        }
        _emit(
            payload,
            json_out=bool(args.json),
            human=f"created {rel} hash={snap.content_hash}",
        )
    finally:
        opstore.close()
    return 0


def _cmd_part_show(args: argparse.Namespace) -> int:
    name = _require_part_name(cast("str", args.part))
    root, store, opstore = _project()
    try:
        store.read_part(name)  # addressing_error + candidates if missing
        publisher = Publisher(load_project(root), opstore)
        result = publisher.current_result(name)
    finally:
        opstore.close()
    if result is None:
        payload: dict[str, Any] = {"status": "not_built", "part": name, "current": False}
        _emit(payload, json_out=bool(args.json), human=f"{name}: not built")
        return 0
    if bool(args.json):
        print(json.dumps(result.to_json()))
        return 0
    status = result.status
    artifact = "" if result.artifact_ref is None else f" artifact={result.artifact_ref}"
    print(f"{name}: {status} (current={result.current}){artifact}")
    if result.metrics is not None:
        print(
            f"  solids={result.metrics.solids} volume={result.metrics.volume_mm3} mm^3 "
            f"sealed={result.metrics.sealed}"
        )
    return 0


# --------------------------------------------------------------------------
# heph script


def _cmd_script_show(args: argparse.Namespace) -> int:
    name = _require_part_name(cast("str", args.name))
    root, store, opstore = _project()
    try:
        snap = store.read_part(name)
    finally:
        opstore.close()
    payload = {
        "status": "ok",
        "name": name,
        "path": str(snap.path.relative_to(root)),
        "script": snap.content,
        "content_hash": snap.content_hash,
        "snapshot_ref": snap.snapshot_ref,
        "line_count": snap.content.count("\n") + (0 if snap.content.endswith("\n") else 1),
    }
    if bool(args.json):
        print(json.dumps(payload, sort_keys=True))
        return 0
    print(f"{payload['path']} hash={snap.content_hash}")
    print(snap.content, end="" if snap.content.endswith("\n") else "\n")
    return 0


def _cmd_script_write(args: argparse.Namespace) -> int:
    name = _require_part_name(cast("str", args.name))
    expected = cast("str | None", args.expected_hash)
    if not expected:
        raise _UsageError("write_part requires --expected-hash (the current content_hash)")
    script = _read_source(file_arg=cast("str | None", args.file), allow_empty=False, required=True)
    _root, store, opstore = _project()
    try:
        store.read_part(name)  # ensure it exists, same as the tool
        try:
            outcome = store.write_part(
                name,
                script,
                base_hash=expected,
                op_id=f"heph-script-write-{uuid.uuid4().hex}",
            )
        except WriteConflictError as exc:
            payload = _conflict_payload(exc)
            if bool(args.json):
                print(json.dumps(payload, sort_keys=True))
            else:
                print(
                    f"{name}: conflict current_hash={exc.live_hash} (expected {expected})",
                    file=sys.stderr,
                )
            return 1
        snap = outcome.snapshot
        payload = {
            "applied": True,
            "content_hash": snap.content_hash,
            "snapshot_ref": snap.snapshot_ref,
            "replayed": outcome.replayed,
            "path": str(snap.path.relative_to(_root)),
        }
        _emit(
            payload,
            json_out=bool(args.json),
            human=f"wrote parts/{name}.py hash={snap.content_hash}",
        )
    finally:
        opstore.close()
    return 0


# --------------------------------------------------------------------------
# heph params


def _param_row(
    name: str,
    *,
    param: Param | None,
    effective: Mapping[str, int | float],
    scope: str,
) -> dict[str, Any]:
    if param is None:
        value: int | float | None = effective.get(name)
        return {"name": name, "value": value, "scope": scope}
    value_num = effective.get(name, param.default)
    return {
        "name": name,
        "value": value_num,
        "default": param.default,
        "min": param.min,
        "max": param.max,
        "step": param.step,
        "doc": param.doc,
        "scope": scope,
    }


def _part_param_rows(store: ProjectStore, publisher: Publisher, name: str) -> list[dict[str, Any]]:
    snap = store.read_part(name)
    declarations, names = static_params(snap.content)
    result = publisher.current_result(name)
    effective: Mapping[str, int | float] = {} if result is None else result.params
    ordered = list(names)
    for extra in effective:
        if extra not in ordered:
            ordered.append(extra)
    return [
        _param_row(key, param=declarations.get(key), effective=effective, scope="part")
        for key in ordered
    ]


def _project_param_rows(root: Path, store: ProjectStore) -> list[dict[str, Any]]:
    layout = load_project(root)
    manifest_values = dict(layout.manifest.params)
    globals_snap = store.read_globals()
    declarations: dict[str, Param] = {}
    names: list[str] = []
    if globals_snap is not None:
        declarations, declared = static_params(globals_snap.content)
        names.extend(declared)
    for extra in manifest_values:
        if extra not in names:
            names.append(extra)
    return [
        _param_row(
            key,
            param=declarations.get(key),
            effective=manifest_values,
            scope="project",
        )
        for key in names
    ]


def _cmd_params(args: argparse.Namespace) -> int:
    raw = cast("str | None", args.part)
    root, store, opstore = _project()
    try:
        publisher = Publisher(load_project(root), opstore)
        if raw is None:
            payload: dict[str, Any] = {
                "status": "ok",
                "project": _project_param_rows(root, store),
                "parts": {
                    name: _part_param_rows(store, publisher, name) for name in store.list_parts()
                },
            }
            human_parts = store.list_parts()
        else:
            name = _require_part_name(raw)
            rows = _part_param_rows(store, publisher, name)
            payload = {"status": "ok", "part": name, "params": rows}
            human_parts = (name,)
    finally:
        opstore.close()
    if bool(args.json):
        print(json.dumps(payload, sort_keys=True))
        return 0
    if raw is None:
        project_rows = cast("list[dict[str, Any]]", payload["project"])
        if project_rows:
            print("project:")
            for row in project_rows:
                print(f"  {row['name']}={row.get('value')}")
        elif not human_parts:
            print("no parts")
            return 0
        for part_name in human_parts:
            rows = cast("list[dict[str, Any]]", payload["parts"][part_name])
            print(f"{part_name}:")
            if not rows:
                print("  (no PARAMS)")
            for row in rows:
                print(f"  {row['name']}={row.get('value')}")
        return 0
    rows = cast("list[dict[str, Any]]", payload["params"])
    if not rows:
        print(f"{raw}: no PARAMS")
        return 0
    for row in rows:
        bounds = ""
        if "min" in row:
            bounds = f" [{row['min']}..{row['max']}]"
        print(f"{row['name']}={row.get('value')}{bounds}")
    return 0


# --------------------------------------------------------------------------
# heph prompt


def _request_path(root: Path) -> Path:
    return root / REQUEST_FILENAME


def _cmd_prompt_show(args: argparse.Namespace) -> int:
    root = find_project_root(Path.cwd())
    path = _request_path(root)
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    payload = {
        "status": "ok" if text else "empty",
        "text": text,
        "path": REQUEST_FILENAME,
    }
    if bool(args.json):
        print(json.dumps(payload, sort_keys=True))
        return 0
    if not text:
        print("no request text stored")
        return 0
    print(text, end="" if text.endswith("\n") else "\n")
    return 0


def _cmd_prompt_set(args: argparse.Namespace) -> int:
    text = _read_source(file_arg=cast("str | None", args.file), allow_empty=True, required=True)
    root = find_project_root(Path.cwd())
    # Opening the store creates ``.heph/``; the request file is not a blob.
    layout = load_project(root)
    opstore = open_store(layout)
    opstore.close()
    path = _request_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    payload = {"status": "ok", "text": text, "path": REQUEST_FILENAME, "bytes": len(text.encode())}
    _emit(
        payload,
        json_out=bool(args.json),
        human=f"stored {payload['bytes']} byte(s) -> {REQUEST_FILENAME}",
    )
    return 0


# --------------------------------------------------------------------------
# registration


def _guard(command: Callable[[argparse.Namespace], int]) -> Callable[[argparse.Namespace], int]:
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
    """Register ``part`` / ``script`` / ``params`` / ``prompt`` on ``heph``."""
    part = sub.add_parser("part", help="list, create, or show a part")
    part_verbs = part.add_subparsers(dest="part_command", required=True)

    listing = part_verbs.add_parser("list", help="list parts in this project")
    listing.add_argument("--json", action="store_true", help="emit the list_parts projection")
    listing.set_defaults(func=_guard(_cmd_part_list))

    create = part_verbs.add_parser(
        "create", help="create parts/<name>.py (create_part: fails if it exists)"
    )
    create.add_argument("name", help="part name (python identifier)")
    create.add_argument(
        "--template",
        default="blank",
        choices=list(TEMPLATE_NAMES),
        help="create_part template when --file is not given (default: blank)",
    )
    create.add_argument(
        "--file",
        default=None,
        help="initial script (path or - for stdin); replaces the template",
    )
    create.add_argument(
        "--description",
        default="",
        help="accepted for create_part parity; the engine does not apply it",
    )
    create.add_argument("--json", action="store_true", help="emit the create_part result")
    create.set_defaults(func=_guard(_cmd_part_create))

    show = part_verbs.add_parser("show", help="show the last published build for a part")
    show.add_argument("part", help="part name")
    show.add_argument("--json", action="store_true", help="emit the BuildResult JSON")
    show.set_defaults(func=_guard(_cmd_part_show))

    script = sub.add_parser("script", help="read or write a part script")
    script_verbs = script.add_subparsers(dest="script_command", required=True)

    script_show = script_verbs.add_parser("show", help="print a part script and its content hash")
    script_show.add_argument("name", help="part name")
    script_show.add_argument("--json", action="store_true", help="emit the read_part result")
    script_show.set_defaults(func=_guard(_cmd_script_show))

    script_write = script_verbs.add_parser(
        "write", help="replace a part script (write_part: expected-hash CAS)"
    )
    script_write.add_argument("name", help="part name")
    script_write.add_argument(
        "--file",
        default=None,
        help="replacement script (path or - for stdin; stdin if omitted and not a TTY)",
    )
    script_write.add_argument(
        "--expected-hash",
        dest="expected_hash",
        default=None,
        help="current content_hash from heph script show / heph part create (required)",
    )
    script_write.add_argument("--json", action="store_true", help="emit the write_part result")
    script_write.set_defaults(func=_guard(_cmd_script_write))

    params = sub.add_parser("params", help="show PARAMS declarations and effective values")
    params.add_argument("part", nargs="?", default=None, help="part name (omit for every part)")
    params.add_argument("--json", action="store_true", help="emit the PARAMS document")
    params.set_defaults(func=_guard(_cmd_params))

    prompt = sub.add_parser(
        "prompt",
        help="show or store the operator request text (not a hosted chat)",
    )
    prompt.add_argument("--json", action="store_true", help="emit {status, text, path}")
    prompt.set_defaults(func=_guard(_cmd_prompt_show))
    prompt_verbs = prompt.add_subparsers(dest="prompt_command", required=False)

    prompt_show = prompt_verbs.add_parser("show", help="print the stored request text")
    prompt_show.add_argument("--json", action="store_true", help="emit {status, text, path}")
    prompt_show.set_defaults(func=_guard(_cmd_prompt_show))

    prompt_set = prompt_verbs.add_parser("set", help="store request text from --file or stdin")
    prompt_set.add_argument(
        "--file",
        default=None,
        help="request text (path or - for stdin; stdin if omitted and not a TTY)",
    )
    prompt_set.add_argument("--json", action="store_true", help="emit the stored record")
    prompt_set.set_defaults(func=_guard(_cmd_prompt_set))
