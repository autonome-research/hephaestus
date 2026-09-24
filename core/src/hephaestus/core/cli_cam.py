# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""``heph cam`` — the CAM CLI: declared-state tables, and the 2D cut-file emit.

Two verbs with two histories, deliberately kept apart:

* ``heph cam`` (bare, Stage 14B — CAM.md §9, Gate G14B clause 23) prints the
  five declared-state ledgers (setups, stock, fixtures, WCS, operations) as
  human tables or ``--json``. It reads the ledgers and nothing else: no
  resolution, no generation, no kernel, and **no emission of any kind** — the
  D2 mandate is a filesystem assertion over this path (clause 24).
* ``heph cam emit`` is the **prior claim** on the verb (CAM.md §1.4): the 2D
  laser/waterjet cut-file from a built part. It is not Stage 14 milling CAM
  and it is not ``export_part``; its behaviour is byte-for-byte the shipped
  contract, and milling emission (the ``<setup>`` form, consent-gated) is
  deferred to 14D in full.

For ``emit``: kerf is never invented. An explicit ``--kerf-mm`` wins;
otherwise the DFM pack's ``kerf_mm`` for the part's declared process is used;
otherwise the file is the nominal path and the record says
``kerf_uncompensated``.

Exit codes match the engine CLI: 0 success, 1 the verb ran and the answer
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

from hephaestus.core.cli_errors import (
    ensure_writable_dir,
    guard,
    project_root_or_refuse,
)

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


def _cmd_emit(args: argparse.Namespace) -> int:
    from hephaestus.core.cam import emit_part

    name = cast("str", args.part)
    root = project_root_or_refuse()
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


_LEDGER_COLUMNS: Mapping[str, tuple[str, ...]] = {
    "setups": ("spindle_axis", "order", "stock", "fixture", "wcs"),
    "stock": ("kind", "extents_mm", "material", "origin_anchor"),
    "fixtures": ("members",),
    "wcs": ("code", "datum", "z_zero"),
    "operations": ("setup", "kind", "feature", "tool", "depth_mm"),
}


def _entry_line(name: str, entry: Mapping[str, Any]) -> str:
    parts: list[str] = [str(entry.get("id", "?"))]
    for column in _LEDGER_COLUMNS[name]:
        value = entry.get(column)
        if name == "fixtures" and column == "members":
            members = cast("list[object]", value) if isinstance(value, list) else []
            value = f"{len(members)} member(s)"
        parts.append(f"{column}={value}")
    if entry.get("withdrawn"):
        parts.append(f"withdrawn ({entry.get('withdrawn_reason')})")
    return "  " + " ".join(parts)


def format_cam_state(state: Mapping[str, Any]) -> str:
    """The human tables: every ledger, withdrawn entries included with reasons."""
    lines: list[str] = []
    for name in ("setups", "stock", "fixtures", "wcs", "operations"):
        ledger = state.get(name)
        ledger_map: Mapping[str, Any] = (
            cast("Mapping[str, Any]", ledger) if isinstance(ledger, dict) else {}
        )
        raw_entries = ledger_map.get("entries")
        entries = cast("list[Any]", raw_entries) if isinstance(raw_entries, list) else []
        generation = ledger_map.get("generation", 0)
        lines.append(f"{name}: {len(entries)} entr{'y' if len(entries) == 1 else 'ies'} "
                     f"(generation {generation})")
        for entry in entries:
            if isinstance(entry, dict):
                lines.append(_entry_line(name, cast("Mapping[str, Any]", entry)))
    return "\n".join(lines)


def _cmd_show(args: argparse.Namespace) -> int:
    """``heph cam`` — the declared-state tables. Reads ledgers; writes nothing."""
    from hephaestus.core.project_store.cam import CamState
    from hephaestus.core.project_store.layout import load_project, open_store

    root = project_root_or_refuse()
    layout = load_project(root)
    store = open_store(layout)
    try:
        state = CamState(layout, store).to_json()
    finally:
        store.close()
    if bool(args.json):
        print(json.dumps(state, sort_keys=True))
    else:
        print(format_cam_state(cast("Mapping[str, Any]", state)))
    return 0


def _verdict_line(name: str, block: Mapping[str, Any] | None) -> str:
    if not isinstance(block, dict):
        return f"  {name}: not evaluated"
    verdict = block.get("verdict")
    extras: list[str] = []
    samples = block.get("samples_evaluated")
    if isinstance(samples, int) and not isinstance(samples, bool):
        extras.append(f"{samples} samples")
    if block.get("in_process_stock_not_modelled"):
        extras.append("in_process_stock_not_modelled")
    suffix = f" ({', '.join(extras)})" if extras else ""
    return f"  {name}: {verdict}{suffix}"


def format_program_status(status: Mapping[str, Any]) -> str:
    """One setup's §5.9 record as the human report (CAM.md §9, ``heph cam check``).

    Verdicts in their sampled spellings verbatim, every named refusal, every
    finding with its severity, and the §5.5 stamp — the surface Gate G14C
    clause 18's whole-token banned-claim lint runs over, so nothing here may
    editorialize a verdict into a claim.
    """
    setup = status.get("setup", "?")
    state = status.get("state", "?")
    lines = [f"{setup}: {state}"]
    if state == "unresolvable":
        lines.append(f"  reason: {status.get('reason')} — {status.get('detail')}")
    for name in ("coverage", "round_trip", "simulation", "collision"):
        block = status.get(name)
        lines.append(_verdict_line(name, block if isinstance(block, dict) else None))
    refusals = status.get("refusals")
    for refusal in refusals if isinstance(refusals, list) else []:
        if isinstance(refusal, dict):
            lines.append(f"  refusal: {refusal.get('reason')}")
    findings = status.get("findings")
    for finding in findings if isinstance(findings, list) else []:
        if isinstance(finding, dict):
            lines.append(f"  finding [{finding.get('severity')}]: {finding.get('reason')}")
    return "\n".join(lines)


def _cmd_check(args: argparse.Namespace) -> int:
    """``heph cam check [setups]`` — simulate and verify; writes nothing."""
    from hephaestus.core.cam_check import check_program
    from hephaestus.core.project_store.layout import load_project, open_store
    from hephaestus.core.registry import RegistrySet

    root = project_root_or_refuse()
    layout = load_project(root)
    store = open_store(layout)
    registries = RegistrySet.open(root)
    try:
        statuses, partial = check_program(
            layout,
            store,
            cast("list[str] | None", args.setups) or None,
            tools=registries.tools,
            materials=registries.materials,
        )
    finally:
        store.close()
    payload = {
        "status": "ok",
        "partial": partial,
        "programs": [status.to_json() for status in statuses],
    }
    if bool(args.json):
        print(json.dumps(payload, sort_keys=True))
    else:
        for status in statuses:
            print(format_program_status(status.to_json()))
    blocked = any(status.blocking() for status in statuses)
    return 1 if blocked else 0


def add_subparsers(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
) -> None:
    """Register the ``cam emit`` verb on an existing subparser set."""
    cam = sub.add_parser(
        "cam", help="CAM: declared-state tables (bare), and the 2D laser/waterjet cut-file"
    )
    # Bare ``heph cam`` prints the declared-state tables (Stage 14B); the
    # subcommands stay exactly as shipped, so the 2D emit contract is untouched.
    cam.add_argument(
        "--json", action="store_true", help="emit the declared-state ledgers as JSON"
    )
    cam.set_defaults(func=guard(_cmd_show))
    verbs = cam.add_subparsers(dest="cam_command", required=False)
    check = verbs.add_parser(
        "check",
        help="simulate and verify declared setups (CAM.md §5); writes nothing",
    )
    check.add_argument(
        "setups",
        nargs="*",
        help="setup ids to check (default: every active setup, recorded)",
    )
    check.add_argument("--json", action="store_true", help="emit the §5.9 records as JSON")
    check.set_defaults(func=guard(_cmd_check))
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
