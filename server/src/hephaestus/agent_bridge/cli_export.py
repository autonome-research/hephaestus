# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""``heph export list`` / ``heph export unpin BLOB`` — the retention verbs.

``INTERFACE.md`` §19.40, under Stage 10A / Gate G10A. §22.6 rules that the
workspace *"offers no unpin and no delete, and says so by name"*, and it puts a
sentence in the Export panel — *"Exports are kept until they are unpinned from
the command line. This workspace does not delete them."* — that until now named
nothing. `tool_schema.md` had promised the same verb for longer: exports are
"pinned as a GC root until explicit ``heph export unpin/delete``", and
``ExportOps.unpin_export`` existed with **no production caller anywhere**, only a
server test. These two verbs are the second half of both promises.

**Two verbs, deliberately asymmetric, on the ``heph assembly`` precedent.**

- ``heph export list [PART] [--json]`` reads the committed export rows and their
  outputs, with each file's size, its GC-root pin, and whether the blob is still
  reachable at all. It computes nothing and loads no geometry kernel, so it is
  instant and safe to run anywhere.
- ``heph export unpin BLOB [--json]`` drops one exported blob's GC root through
  ``ExportOps.unpin_export`` and reports what that changed.

**What unpin does and does not do, stated because the difference is the whole
point.** It removes a *pin*. It deletes nothing, and this verb never collects:
GC is ``opstore``'s own pass under its retention horizons, and a verb that
unpinned and swept in one step would make an irreversible deletion the
side effect of a reversible bookkeeping change. After an unpin the blob is
merely *collectable* — it survives until it is both unreachable and older than
its retention class. §22.6's third consequence is what makes this worth a verb:
an export pins its outputs **and** transitively protects the build they came
from, forever, so the only way a project that has exported a lot ever shrinks is
here.

**Why unpinning matters more than it used to, as of the same item.** §19.40's
other half wired ``GcCollector.admission_guard()`` into the artifact-producing
paths (``Publisher.freeze_inputs`` and ``ExportOps._guard_admission``), so a
project whose *protected* bytes exceed its quota now refuses new builds and new
exports with the store's own ``protected_quota_exceeded``. That refusal's remedy
is "raise the quota or unpin data", and this verb is the second half of it —
which is why ``list`` prints the quota accounting under the table and ``unpin``
prints it again afterwards.

Exit codes match the engine CLI: 0 success, 2 usage — a blob that is not an
export blob, or one no committed export names. There is no failure exit of this
verb's own: an unpin is either performed or already performed, and "nothing is
pinned" is a fact about the project rather than a CLI failure, the same reading
``heph assembly`` gives "never evaluated". Run outside a project, both verbs give
``hephaestus.core.cli``'s existing ``error (validation_error)`` and exit **1**,
which is what every read verb in the CLI does today — ``cli.py``'s module
docstring says that case is a 2, and the docstring is wrong for all of them; this
verb does not diverge from its siblings to be right on its own.

Kept in the server package because the export write-ahead table lives there
(``agent_bridge/cad_ops/export_history``), on the same footing as ``heph agent``
and ``heph bench``: :func:`hephaestus.core.cli.build_parser` registers it inside
a ``try/except ImportError`` so the Node-free engine CLI is unchanged when the
server package is not installed. The verb itself needs **no** Node and no
network, and ``list`` deliberately imports no geometry kernel.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from hephaestus.core.project_store.layout import find_project_root, load_project, open_store

from opstore import OpStore

from .cad_ops.export_history import EXPORTS_DIR, ExportRecord, export_records

__all__ = ["add_subparsers"]

_HEADER = ("part", "format", "layout", "bytes", "pin", "blob", "path")


class _UsageError(Exception):
    """CLI misuse: reported on stderr with exit code 2."""


def _files(
    store: OpStore, records: Sequence[ExportRecord]
) -> list[tuple[ExportRecord, str, str, int, bool, bool]]:
    """``(record, rel_path, blob, bytes, pinned, reachable)`` for every output.

    ``pinned`` and ``reachable`` are two different facts and both are reported.
    A blob is *pinned* when it is a GC root in its own right — what every export
    does to its outputs. It is *reachable* when the closure of pins and the
    project's protected roots over the ``links`` table contains it, which is what
    GC actually consults. Unpinning an export whose bytes are also the bytes of
    something else the project protects leaves it reachable, and an operator who
    was told only "unpinned" would believe they had reclaimed space they had not.
    """
    pins = store.gc.pins()
    reachable = store.gc.reachable()
    rows: list[tuple[ExportRecord, str, str, int, bool, bool]] = []
    for record in records:
        for rel_path, blob in record.outputs:
            size = store.blobs.size(blob) if store.blobs.has(blob) else 0
            rows.append((record, rel_path, blob, size, blob in pins, blob in reachable))
    return rows


def _cmd_list(args: argparse.Namespace) -> int:
    """Print the committed export rows and their outputs (no evaluation)."""
    part = args.part if isinstance(args.part, str) else None
    root = find_project_root(Path.cwd())
    layout = load_project(root)
    store = open_store(layout)
    try:
        records = export_records(store, part=part)
        rows = _files(store, records)
        usage = store.gc.usage()
    finally:
        store.close()

    if bool(args.json):
        document: dict[str, Any] = {
            "status": "ok",
            "part": part,
            "exports": [
                {
                    "op_id": record.op_id,
                    "part": record.part,
                    "format": record.recorded_format,
                    "layout": record.layout,
                    "state": record.state,
                    "source_artifact_ref": record.source_artifact_ref,
                    "source_input_hashes": dict(record.source_input_hashes),
                    "extra": dict(record.extra),
                    "outputs": [
                        {
                            "path": rel_path,
                            "blob": blob,
                            "bytes": size,
                            "pinned": pinned,
                            "reachable": reachable,
                        }
                        for owner, rel_path, blob, size, pinned, reachable in rows
                        if owner.op_id == record.op_id
                    ],
                    "total_bytes": sum(
                        size for owner, _, _, size, _, _ in rows if owner.op_id == record.op_id
                    ),
                }
                for record in records
            ],
            "total_bytes": sum(size for _, _, _, size, _, _ in rows),
            "pinned_bytes": sum(size for _, _, _, size, pinned, _ in rows if pinned),
            "usage": usage.to_json(),
        }
        print(json.dumps(document, sort_keys=True))
        return 0

    if not rows:
        print("no exports recorded")
        return 0
    table: list[tuple[str, ...]] = [_HEADER]
    for record, rel_path, blob, size, pinned, reachable in rows:
        if pinned:
            pin = "pinned"
        elif reachable:
            # Unpinned but still protected by something else — the state an
            # operator most needs told, because it is the one where unpinning
            # reclaimed nothing.
            pin = "reachable"
        else:
            pin = "collectable"
        table.append(
            (
                record.part,
                record.recorded_format,
                record.layout,
                str(size),
                pin,
                blob,
                f"{EXPORTS_DIR}/{rel_path}",
            )
        )
    _print_table(table)
    print(
        f"\n{len(records)} export(s), {len(rows)} file(s), "
        f"{sum(size for _, _, _, size, _, _ in rows)} bytes"
    )
    print(_usage_line(usage.to_json()))
    if any(pinned for _, _, _, _, pinned, _ in rows):
        print("drop an export's GC root with 'heph export unpin BLOB' (deletes nothing)")
    return 0


def _cmd_unpin(args: argparse.Namespace) -> int:
    """Drop one exported blob's GC root, and report what that changed."""
    # The kernel-binding module is imported here rather than at module import:
    # `list` must not pay for it, and this is the `cli_joints`/`cli_assembly`
    # rule applied one verb further.
    from hephaestus.agent_bridge.cad_ops import CadOps

    blob = _normalized_blob(str(args.blob))
    root = find_project_root(Path.cwd())
    layout = load_project(root)
    store = open_store(layout)
    try:
        named = [
            (record, rel_path)
            for record in export_records(store)
            for rel_path, candidate in record.outputs
            if candidate == blob
        ]
        if not named:
            raise _UsageError(
                f"{blob} is not an output of any committed export in this project "
                f"(list them with 'heph export list')"
            )
        was_pinned = blob in store.gc.pins()
        # §19.40 names `ExportOps.unpin_export` as the operation these verbs are
        # over, so the verb calls it rather than reaching past it to `gc.unpin`.
        CadOps(layout, store).unpin_export(blob)
        still_reachable = blob in store.gc.reachable()
        usage = store.gc.usage()
        size = store.blobs.size(blob) if store.blobs.has(blob) else 0
    finally:
        store.close()

    if bool(args.json):
        print(
            json.dumps(
                {
                    "status": "ok",
                    "blob": blob,
                    "bytes": size,
                    "was_pinned": was_pinned,
                    "pinned": False,
                    "reachable": still_reachable,
                    "exports": [
                        {"op_id": record.op_id, "part": record.part, "path": rel_path}
                        for record, rel_path in named
                    ],
                    "usage": usage.to_json(),
                },
                sort_keys=True,
            )
        )
        return 0

    where = ", ".join(f"{record.part} {rel_path}" for record, rel_path in named)
    if was_pinned:
        print(f"unpinned {blob} ({size} bytes) — {where}")
    else:
        print(f"{blob} was already unpinned ({size} bytes) — {where}")
    if still_reachable:
        print(
            "still reachable: the project protects these bytes by another root "
            "or link, so nothing becomes collectable"
        )
    else:
        print(
            "now collectable: the blob and anything it alone protected are "
            "eligible for the next GC pass once past their retention horizon"
        )
    print(_usage_line(usage.to_json()))
    return 0


def _usage_line(usage: dict[str, int]) -> str:
    """The quota accounting, in the store's own three numbers.

    Printed by both verbs because §19.40's other half made these numbers
    actionable: over quota, ``Publisher.freeze_inputs`` and
    ``ExportOps._guard_admission`` refuse new work with
    ``protected_quota_exceeded``, whose stated remedy is this verb.
    """
    return (
        f"store: {usage['protected_bytes']} protected of {usage['quota_bytes']} quota "
        f"({usage['total_bytes']} stored)"
    )


def _normalized_blob(raw: str) -> str:
    """The blob as the store spells it: ``sha256:<hex>``.

    A bare digest is accepted because that is what a reader copies out of a
    filename or a provenance footer; nothing else is guessed at. No prefix
    matching: an unpin resolved by prefix is an irreversible-feeling operation
    whose subject depends on what else happens to be in the store.
    """
    candidate = raw.strip()
    if not candidate:
        raise _UsageError("unpin needs an export blob (see 'heph export list')")
    if candidate.startswith("sha256:"):
        return candidate
    if len(candidate) == 64 and all(c in "0123456789abcdef" for c in candidate.lower()):
        return f"sha256:{candidate.lower()}"
    raise _UsageError(f"{raw!r} is not an export blob: expected 'sha256:<hex>' or the bare digest")


def _print_table(rows: list[tuple[str, ...]]) -> None:
    widths = [max(len(row[column]) for row in rows) for column in range(len(rows[0]))]
    for row in rows:
        print("  ".join(cell.ljust(widths[column]) for column, cell in enumerate(row)).rstrip())


def _guard(command: Callable[[argparse.Namespace], int]) -> Callable[[argparse.Namespace], int]:
    """Report export-verb misuse as exit 2 regardless of the entry point."""

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
    """Register the ``export`` verb group on an existing subparser set."""
    export = sub.add_parser("export", help="list exported files and release their GC roots")
    verbs = export.add_subparsers(dest="export_command", required=True)

    listing = verbs.add_parser("list", help="show every committed export and its pinned outputs")
    listing.add_argument("part", nargs="?", default=None, help="only this part's exports")
    listing.add_argument("--json", action="store_true", help="emit the machine form")
    listing.set_defaults(func=_guard(_cmd_list))

    unpin = verbs.add_parser("unpin", help="drop one exported blob's GC root (deletes nothing)")
    unpin.add_argument("blob", help="the export blob, 'sha256:<hex>' as 'heph export list' prints")
    unpin.add_argument("--json", action="store_true", help="emit the machine form")
    unpin.set_defaults(func=_guard(_cmd_unpin))
