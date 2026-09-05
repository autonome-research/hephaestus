# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""``heph cam emit`` — 2D CAM cut-file from a built part (laser / waterjet).

This is not Stage 14 milling CAM and it is not ``export_part``. A program is
not an export: the write-ahead table, the GC-root pin, and the workspace
panel stay where they are. This verb reads the current published artifact,
runs the in-tree flat-pattern + kerf path, and writes a DXF plus a toolpath
record the operator can inspect headless.

Kerf is never invented. An explicit ``--kerf-mm`` wins; otherwise the DFM
pack's ``kerf_mm`` for the part's declared process is used; otherwise the
file is the nominal path and the record says ``kerf_uncompensated``.

Exit codes match the engine CLI: 0 success, 1 the emit ran and the answer
was no (not a 2D cut process, no flat pattern, a kerf that cannot offset),
2 usage (no project, unknown part, an ``--out`` that cannot be written).
``--out`` is validated before the emit runs, so an unwritable path is reported
in the first millisecond instead of after the whole program has been computed
and thrown away.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from hephaestus.core.cli_errors import CliUsageError, ensure_writable_dir, guard
from hephaestus.core.errors import ValidationError
from hephaestus.core.project_store.layout import find_project_root

__all__ = ["add_subparsers"]


def _kerf_line(kerf: Mapping[str, Any]) -> str:
    applied = kerf.get("applied_mm")
    source = kerf.get("source", "none")
    if isinstance(applied, int | float) and not isinstance(applied, bool) and applied > 0.0:
        return f"{applied:g} mm ({source})"
    note = kerf.get("note") or "uncompensated"
    reason = kerf.get("reason")
    if isinstance(reason, str) and reason:
        return f"none ({note}: {reason})"
    return f"none ({note})"


def _layers_line(layers: Mapping[str, Any]) -> str:
    parts = [f"{count} {name}" for name, count in layers.items() if isinstance(count, int)]
    return ", ".join(parts) if parts else "none"


def format_program(payload: Mapping[str, Any], *, path: str) -> str:
    """The human report: process, kerf source, contours, and where the DXF went."""
    process = payload.get("process", "?")
    part = payload.get("part", "?")
    kerf = payload.get("kerf")
    kerf_map: Mapping[str, Any] = cast("Mapping[str, Any]", kerf) if isinstance(kerf, dict) else {}
    layers = payload.get("layers")
    layer_map: Mapping[str, Any] = (
        cast("Mapping[str, Any]", layers) if isinstance(layers, dict) else {}
    )
    profiles = payload.get("profiles")
    n_profiles = len(cast("list[object]", profiles)) if isinstance(profiles, list) else 0
    digest = payload.get("dxf_sha256", "")
    lines = [
        f"{part}: {process}",
        f"  kerf: {_kerf_line(kerf_map)}",
        f"  profiles: {n_profiles}",
        f"  contours: {_layers_line(layer_map)}",
        f"  wrote {path}",
    ]
    if isinstance(digest, str) and digest:
        lines.append(f"  dxf: {digest}")
    return "\n".join(lines)


def _project_root() -> Path:
    try:
        return find_project_root(Path.cwd())
    except ValidationError as exc:
        raise CliUsageError(exc.message) from exc


def _cmd_emit(args: argparse.Namespace) -> int:
    from hephaestus.core.cam import emit_part

    name = cast("str", args.part)
    root = _project_root()
    # The output precondition runs BEFORE the emit (ledger B-10): kerf, nesting
    # and DXF generation are the expensive part, and an unwritable `--out`
    # discovered afterwards throws all of it away to report an OS error the
    # operator could have been told about in the first millisecond.
    out = Path(cast("str", args.out)) if args.out else Path(f"{name}.dxf")
    ensure_writable_dir(out.parent, flag="--out")
    program = emit_part(
        name, project_root=root, explicit_kerf_mm=cast("float | None", args.kerf_mm)
    )
    out.write_bytes(program.dxf)
    payload = program.to_json()
    payload["path"] = str(out)
    if bool(args.json):
        print(json.dumps(payload, sort_keys=True))
    else:
        print(format_program(payload, path=str(out)))
    return 0


def add_subparsers(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
) -> None:
    """Register the ``cam emit`` verb on an existing subparser set."""
    cam = sub.add_parser("cam", help="2D CAM: laser-cut / waterjet toolpath and DXF")
    verbs = cam.add_subparsers(dest="cam_command", required=True)
    emit = verbs.add_parser(
        "emit",
        help="emit a kerf-compensated laser/waterjet cut-file from a built part",
    )
    emit.add_argument("part", help="part whose current build is the source")
    emit.add_argument(
        "--out",
        default=None,
        help="DXF path (default: <part>.dxf in the current directory)",
    )
    emit.add_argument(
        "--kerf-mm",
        type=float,
        default=None,
        dest="kerf_mm",
        help="explicit kerf width in millimetres (overrides the process pack)",
    )
    emit.add_argument("--json", action="store_true", help="emit the cut-file record as JSON")
    emit.set_defaults(func=guard(_cmd_emit))
