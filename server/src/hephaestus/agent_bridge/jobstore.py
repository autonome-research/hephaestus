"""``py.jobstore_*`` durable store backing the thread-phase ``JobStore`` adapter.

The packaged sidecar has **no native SQLite addon** (repo_conventions Stage S
item 4); its application-owned async ``JobStore`` (``agent/src/workflows/
jobstore.ts``) persists every job/event/checkpoint by calling the five frozen
bridge methods — ``py.jobstore_{get,put,list,delete,checkpoint}`` — which this
module answers over dedicated ``tp_``-prefixed tables in the opstore
``state.db`` (DESIGN.md ``jobstore.py``; digest §5).

Design:

* A generic durable key/value namespace (``tp_jobstore``) carries the TS side's
  serialized job records and durable event log — ``put``/``get``/``list``/
  ``delete`` map straight onto it, upsert-idempotent and ordered by insertion
  ``seq`` so replay is deterministic.
* ``checkpoint`` writes a resumable phase checkpoint (``tp_jobstore_checkpoints``)
  carrying the **workflow version and input/output hashes** (digest §5, arch
  §4.5) so a resumed run continues only from a *verified* checkpoint. Checkpoints
  are upsert-idempotent on ``(job_id, checkpoint_key)`` and survive restart.

Every mutation runs inside opstore's ``BEGIN IMMEDIATE`` transaction, so
concurrent bridge writers serialize correctly across the single ``state.db``
connection. The ``tp_`` tables are created idempotently on the shared connection
(opstore's fixed schema owns no workflow tables and must not be edited).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Final, cast

from opstore.db import Database
from opstore.errors import NotFoundError
from opstore.types import Clock, JSONValue, SystemClock

__all__ = [
    "CheckpointRecord",
    "JobStore",
    "KvRecord",
]

_KV_TABLE = "tp_jobstore"
_CHECKPOINT_TABLE = "tp_jobstore_checkpoints"

_CREATE_KV: Final[str] = f"""
CREATE TABLE IF NOT EXISTS {_KV_TABLE}(
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  namespace TEXT NOT NULL,
  key TEXT NOT NULL,
  value TEXT NOT NULL,
  updated_at REAL NOT NULL,
  UNIQUE(namespace, key))
"""

_CREATE_CHECKPOINTS: Final[str] = f"""
CREATE TABLE IF NOT EXISTS {_CHECKPOINT_TABLE}(
  job_id TEXT NOT NULL,
  checkpoint_key TEXT NOT NULL,
  workflow_version TEXT NOT NULL,
  input_hash TEXT NOT NULL,
  output_hash TEXT NOT NULL,
  value TEXT NOT NULL,
  updated_at REAL NOT NULL,
  PRIMARY KEY(job_id, checkpoint_key))
"""


@dataclass(frozen=True, slots=True)
class KvRecord:
    """One durable key/value row."""

    namespace: str
    key: str
    value: JSONValue
    updated_at: float


@dataclass(frozen=True, slots=True)
class CheckpointRecord:
    """One resumable phase checkpoint with its provenance hashes."""

    job_id: str
    checkpoint_key: str
    workflow_version: str
    input_hash: str
    output_hash: str
    value: JSONValue
    updated_at: float


def _loads(text: str) -> JSONValue:
    return cast(JSONValue, json.loads(text))


class JobStore:
    """Durable backing store for the sidecar's async thread-phase ``JobStore``.

    Construct once per opstore ``state.db``; the ``tp_`` tables are ensured on the
    shared connection at construction. All methods are synchronous over the
    single connection; the async ``dispatch`` wrapper adapts them to the five
    ``py.jobstore_*`` bridge requests.
    """

    def __init__(self, db: Database, *, clock: Clock | None = None) -> None:
        self._db = db
        self._clock = clock or SystemClock()
        db.conn.execute(_CREATE_KV)
        db.conn.execute(_CREATE_CHECKPOINTS)

    # -- generic key/value (jobs + durable event log) --------------------------

    def put(self, namespace: str, key: str, value: JSONValue) -> None:
        """Upsert a durable value; idempotent on ``(namespace, key)``."""
        text = json.dumps(value, sort_keys=True, ensure_ascii=False)
        now = self._clock.now()
        with self._db.transaction() as conn:
            conn.execute(
                f"INSERT INTO {_KV_TABLE}(namespace, key, value, updated_at) "
                "VALUES(?, ?, ?, ?) ON CONFLICT(namespace, key) "
                "DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                (namespace, key, text, now),
            )

    def get(self, namespace: str, key: str) -> JSONValue | None:
        """The stored value, or ``None`` if absent."""
        row = self._db.conn.execute(
            f"SELECT value FROM {_KV_TABLE} WHERE namespace = ? AND key = ?",
            (namespace, key),
        ).fetchone()
        return None if row is None else _loads(str(row["value"]))

    def list(
        self, namespace: str, *, prefix: str | None = None, limit: int | None = None
    ) -> list[KvRecord]:
        """Records in ``namespace`` (optionally key-prefixed), insertion-ordered."""
        sql = f"SELECT namespace, key, value, updated_at FROM {_KV_TABLE} WHERE namespace = ?"
        params: list[object] = [namespace]
        if prefix is not None:
            sql += " AND key LIKE ? ESCAPE '\\'"
            params.append(_like_prefix(prefix))
        sql += " ORDER BY seq"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        rows = self._db.conn.execute(sql, tuple(params)).fetchall()
        return [
            KvRecord(
                namespace=str(r["namespace"]),
                key=str(r["key"]),
                value=_loads(str(r["value"])),
                updated_at=float(r["updated_at"]),
            )
            for r in rows
        ]

    def delete(self, namespace: str, key: str) -> bool:
        """Remove a value; returns ``True`` iff a row existed."""
        with self._db.transaction() as conn:
            cur = conn.execute(
                f"DELETE FROM {_KV_TABLE} WHERE namespace = ? AND key = ?",
                (namespace, key),
            )
        return cur.rowcount > 0

    # -- resumable checkpoints -------------------------------------------------

    def checkpoint(
        self,
        job_id: str,
        checkpoint_key: str,
        *,
        workflow_version: str,
        input_hash: str,
        output_hash: str,
        value: JSONValue,
    ) -> CheckpointRecord:
        """Persist a resumable phase checkpoint; idempotent on ``(job, key)``.

        The workflow version and input/output hashes are stored so resume can
        continue only from a *verified* checkpoint (arch §4.5, mission rule 6).
        """
        text = json.dumps(value, sort_keys=True, ensure_ascii=False)
        now = self._clock.now()
        with self._db.transaction() as conn:
            conn.execute(
                f"INSERT INTO {_CHECKPOINT_TABLE}(job_id, checkpoint_key, workflow_version, "
                "input_hash, output_hash, value, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(job_id, checkpoint_key) DO UPDATE SET "
                "workflow_version = excluded.workflow_version, input_hash = excluded.input_hash, "
                "output_hash = excluded.output_hash, value = excluded.value, "
                "updated_at = excluded.updated_at",
                (job_id, checkpoint_key, workflow_version, input_hash, output_hash, text, now),
            )
        return CheckpointRecord(
            job_id=job_id,
            checkpoint_key=checkpoint_key,
            workflow_version=workflow_version,
            input_hash=input_hash,
            output_hash=output_hash,
            value=value,
            updated_at=now,
        )

    def get_checkpoint(self, job_id: str, checkpoint_key: str) -> CheckpointRecord | None:
        """The stored checkpoint for ``(job_id, checkpoint_key)``, if any."""
        row = self._db.conn.execute(
            f"SELECT * FROM {_CHECKPOINT_TABLE} WHERE job_id = ? AND checkpoint_key = ?",
            (job_id, checkpoint_key),
        ).fetchone()
        if row is None:
            return None
        return CheckpointRecord(
            job_id=str(row["job_id"]),
            checkpoint_key=str(row["checkpoint_key"]),
            workflow_version=str(row["workflow_version"]),
            input_hash=str(row["input_hash"]),
            output_hash=str(row["output_hash"]),
            value=_loads(str(row["value"])),
            updated_at=float(row["updated_at"]),
        )

    def list_checkpoints(self, job_id: str) -> list[CheckpointRecord]:
        """All checkpoints for a job, ordered by ``checkpoint_key``."""
        rows = self._db.conn.execute(
            f"SELECT * FROM {_CHECKPOINT_TABLE} WHERE job_id = ? ORDER BY checkpoint_key",
            (job_id,),
        ).fetchall()
        return [
            CheckpointRecord(
                job_id=str(r["job_id"]),
                checkpoint_key=str(r["checkpoint_key"]),
                workflow_version=str(r["workflow_version"]),
                input_hash=str(r["input_hash"]),
                output_hash=str(r["output_hash"]),
                value=_loads(str(r["value"])),
                updated_at=float(r["updated_at"]),
            )
            for r in rows
        ]

    # -- async bridge adapter --------------------------------------------------

    async def dispatch(self, method: str, params: dict[str, Any]) -> Any:
        """Answer one ``py.jobstore_*`` bridge request.

        Recognized methods: ``py.jobstore_get``/``_put``/``_list``/``_delete``/
        ``_checkpoint``. Unknown methods raise :class:`~opstore.errors.NotFoundError`.
        """
        if method == "py.jobstore_put":
            self.put(str(params["namespace"]), str(params["key"]), params.get("value"))
            return {"ok": True}
        if method == "py.jobstore_get":
            return {"value": self.get(str(params["namespace"]), str(params["key"]))}
        if method == "py.jobstore_list":
            prefix = params.get("prefix")
            limit = params.get("limit")
            records = self.list(
                str(params["namespace"]),
                prefix=None if prefix is None else str(prefix),
                limit=None if limit is None else int(cast(int, limit)),
            )
            return {"items": [{"key": r.key, "value": r.value} for r in records]}
        if method == "py.jobstore_delete":
            return {"deleted": self.delete(str(params["namespace"]), str(params["key"]))}
        if method == "py.jobstore_checkpoint":
            record = self.checkpoint(
                str(params["job_id"]),
                str(params["checkpoint_key"]),
                workflow_version=str(params["workflow_version"]),
                input_hash=str(params["input_hash"]),
                output_hash=str(params["output_hash"]),
                value=params.get("value"),
            )
            return {"ok": True, "updated_at": record.updated_at}
        raise NotFoundError(f"unknown jobstore method {method!r}")


def _like_prefix(prefix: str) -> str:
    escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return escaped + "%"
