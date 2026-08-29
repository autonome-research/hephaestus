# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Reading the export write-ahead table — one implementation, three surfaces.

``tp_exports`` is written by exactly one thing (:mod:`._exports`, the §7 export
contract) and by 2026-08-28 it is *read* by three: that writer's own committed
retry, ``server/http``'s §22.7 projection and §22.3 download authorization, and
now ``heph export list`` / ``heph export unpin`` (``INTERFACE.md`` §19.40, the
verbs §22.6 says the workspace's *"unpin it from the command line"* sentence has
to name). Three readers of one table is three places to get the row shape wrong,
so the row shape lives here and each surface renders it into its own document.

WHY a module of its own rather than more functions in :mod:`._exports`: that
module imports the geometry kernel (``load_brep_shape``, the OCCT-backed nesting
and kerf modules) at import time, because it *writes* geometry. Reading the WAL
is a SELECT. ``heph export list`` computes nothing and must stay instant, the
same reason ``cli_joints`` and ``cli_assembly`` are kept out of
:mod:`hephaestus.core.cli` — so nothing in this module imports a kernel, and the
CLI's list verb never loads one.

**Two tolerances this module owns, and both are history rather than taste.**
``outputs`` is the multi-file record added after the table's first shipped shape;
a row written before it carries the single ``rel_path``/``export_blob`` pair
instead, and :func:`recorded_outputs` reads either. And the table itself may not
exist: :func:`has_exports_table` *asks* rather than creating, because a read on
the request path of a ``GET`` (or of a CLI verb run in any project) must not take
a DDL write on ``state.db`` for a project that has never exported. "Nothing has
ever been exported" is an answer — the empty history — not an error.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, cast

from opstore.types import JSONValue

from opstore import OpStore

__all__ = [
    "COMMITTED_STATE",
    "EXPORTS_DIR",
    "EXPORTS_TABLE",
    "FROZEN_STATE",
    "ExportRecord",
    "export_records",
    "has_exports_table",
    "recorded_outputs",
    "row_json",
]

#: The export write-ahead table. Named once; :mod:`._exports` builds its DDL from
#: this constant and both readers select from it.
EXPORTS_TABLE: Final[str] = "tp_exports"

#: The state a row reaches once its files are installed, pinned and linked. The
#: only state whose blobs exist, and therefore the only state any reader may
#: offer bytes from (§22.3).
COMMITTED_STATE: Final[str] = "COMMITTED"

#: The state a row is written in when its source artifact is frozen and before
#: its files are installed. A crashed export stops here: it names no blob.
FROZEN_STATE: Final[str] = "FROZEN"

#: The project-relative directory every export output is confined beneath. A
#: recorded ``rel_path`` is relative to *this*, so anything that reports a path
#: to a person — the WAL's own result ``paths``, §22.4's too-large refusal, and
#: ``heph export list`` — has to prepend it, and there is one place it is spelled.
EXPORTS_DIR: Final[str] = str(Path(".heph") / "exports")


def has_exports_table(store: OpStore) -> bool:
    """Whether this project has ever exported anything.

    Asked rather than created, and read-only on purpose — the ``recorded_kinds``
    precedent (``core/project_store/artifact_kinds.py``). Every caller is a read
    path; running the WAL's own ``ensure_exports_table`` here would make an
    export-history read take a write on ``state.db`` for a project that has never
    exported.
    """
    row = store.db.conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (EXPORTS_TABLE,),
    ).fetchone()
    return row is not None


def row_json(row: Mapping[str, Any], column: str, fallback: JSONValue) -> JSONValue:
    """One JSON-encoded WAL column, tolerant of a row written before it existed."""
    raw = row[column] if column in row.keys() else None  # noqa: SIM118 - sqlite3.Row
    if raw is None:
        return fallback
    try:
        return cast("JSONValue", json.loads(str(raw)))
    except ValueError:  # pragma: no cover - the writer is canonical_json
        return fallback


def recorded_outputs(row: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    """``((rel_path, export_blob), …)`` of one row — multi-file and legacy alike.

    Empty for a row that names neither, which is what a ``FROZEN`` row is: its
    source was frozen and its files were never installed. Returning an empty
    tuple rather than a ``(None, None)`` pair is what lets a caller iterate every
    row of the table without having to know which states carry blobs.
    """
    recorded = row_json(row, "outputs", None)
    if isinstance(recorded, list):
        out: list[tuple[str, str]] = []
        for item in cast("list[JSONValue]", recorded):
            if not isinstance(item, dict):
                continue
            entry = cast("Mapping[str, JSONValue]", item)
            path, blob = entry.get("path"), entry.get("blob")
            if isinstance(path, str) and isinstance(blob, str):
                out.append((path, blob))
        if out:
            return tuple(out)
    path_raw, blob_raw = row["rel_path"], row["export_blob"]
    if path_raw is None or blob_raw is None:
        return ()
    return ((str(path_raw), str(blob_raw)),)


@dataclass(frozen=True, slots=True)
class ExportRecord:
    """One row of ``tp_exports``, decoded once.

    ``recorded_format`` is the ``format`` column as the writer stored it: a
    :data:`~._exports.EXPORT_FORMATS` key for an ``export_part`` row, and
    ``"<operation>:<variant>"`` for a drawing or a document. It is reported under
    the column's own name rather than translated, because §22.7's rule for this
    whole area is that every string is the engine's.
    """

    op_id: str
    part: str
    recorded_format: str
    layout: str
    state: str
    source_artifact_ref: str
    outputs: tuple[tuple[str, str], ...]
    source_input_hashes: Mapping[str, Any]
    extra: Mapping[str, Any]

    @property
    def blobs(self) -> tuple[str, ...]:
        return tuple(blob for _, blob in self.outputs)


def _record(row: Mapping[str, Any]) -> ExportRecord:
    return ExportRecord(
        op_id=str(row["op_id"]),
        part=str(row["part"]),
        recorded_format=str(row["format"]),
        layout=str(row["layout"]),
        state=str(row["state"]),
        source_artifact_ref=str(row["source_artifact_ref"]),
        outputs=recorded_outputs(row),
        source_input_hashes=cast("dict[str, Any]", row_json(row, "source_input_hashes", {})),
        extra=cast("dict[str, Any]", row_json(row, "extra", {})),
    )


def export_records(
    store: OpStore, *, part: str | None = None, state: str | None = COMMITTED_STATE
) -> tuple[ExportRecord, ...]:
    """The recorded exports, oldest first.

    ``state=None`` reads every row; the default reads the committed ones, which
    are the only rows whose blobs exist.

    Ordered by insertion (``rowid``): ``tp_exports`` carries no timestamp, and
    inventing one from the blob store's mtimes would be a derived fact
    (``architecture.md`` §4.4). Insertion order is the true order of a
    single-writer WAL.
    """
    if not has_exports_table(store):
        return ()
    clauses: list[str] = []
    params: list[str] = []
    if part is not None:
        clauses.append("part = ?")
        params.append(part)
    if state is not None:
        clauses.append("state = ?")
        params.append(state)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = cast(
        "Sequence[Mapping[str, Any]]",
        store.db.conn.execute(
            f"SELECT * FROM {EXPORTS_TABLE}{where} ORDER BY rowid", tuple(params)
        ).fetchall(),
    )
    return tuple(_record(row) for row in rows)
