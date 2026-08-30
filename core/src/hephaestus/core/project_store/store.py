"""Part-script CRUD over the project store (architecture §3.5).

Reads register immutable content-addressed snapshots (opstore blobs) and
return ``content_hash``/``snapshot_ref``, so the store can later reconstruct
the exact base a write was computed against. Writes are compare-and-swap on
the base content hash and go through the opstore file WAL (preimage +
candidate blobs, ``PREPARED``/``COMMITTED`` rows, atomic rename) under the
part's advisory lock, with a preimage journal entry under ``.heph/journal/``.
A stale base hash — cooperative or third-party filesystem drift — is a
``conflict`` carrying the live content/hash plus content-addressed refs for
the base and the exact attempted candidate.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from hephaestus.core.errors import AddressingError, ConflictError, ValidationError
from hephaestus.core.project_store.layout import ProjectLayout
from hephaestus.core.project_store.locks import LockManager, part_lock
from opstore.types import JSONValue, OwnerId

from opstore import (
    ConflictedError,
    Fresh,
    OpStore,
    PendingRecovery,
    Replay,
    canonical_json,
    sha256_bytes,
    sha256_canonical_json,
)

if TYPE_CHECKING:
    from hephaestus.core.executor.imports import ImportKind

__all__ = [
    "IMPORT_ARTIFACT_KIND",
    "IMPORT_REF_PREFIX",
    "SNAPSHOT_ARTIFACT_KIND",
    "SNAPSHOT_REF_PREFIX",
    "DriftEvidence",
    "ImportSnapshot",
    "ProjectStore",
    "SourceSnapshot",
    "WriteConflictError",
    "WriteOutcome",
    "artifact_kind_of_ref",
    "artifact_ref",
    "blob_hash_of_ref",
]

#: The artifact kinds the two registered-snapshot prefixes name. Split out
#: because §19.24 makes the kind a value the store *records*, not only a string
#: a prefix happens to contain.
SNAPSHOT_ARTIFACT_KIND = "part-snapshot"
IMPORT_ARTIFACT_KIND = "import"
#: Ref prefix for registered source snapshots (part scripts and globals.py).
SNAPSHOT_REF_PREFIX = f"artifact:{SNAPSHOT_ARTIFACT_KIND}:"
#: Ref prefix for registered ``imports/`` payload snapshots (INGEST.md §1).
IMPORT_REF_PREFIX = f"artifact:{IMPORT_ARTIFACT_KIND}:"
#: Reserved name for the globals.py snapshot.
GLOBALS_NAME = "globals"


def artifact_ref(kind: str, blob_hash: str) -> str:
    """``artifact:<kind>:sha256:<hex>`` for an already-computed blob hash."""
    return f"artifact:{kind}:{blob_hash}"


def _split_ref(ref: str) -> tuple[str, str]:
    """``(kind, "sha256:<hex>")`` for a well-formed ref, or ``ValidationError``.

    One parse of the ``artifact:<kind>:<alg>:<hash>`` grammar, because both
    halves are read — the hash to resolve bytes, the kind to check them against
    the store's publication record (``INTERFACE.md`` §2.6's CORRECTION, §19.24).
    A second copy of these four conditions is how the two halves would come to
    disagree about which refs are well formed (mission rule 6).
    """
    parts = ref.split(":")
    if len(parts) != 4 or parts[0] != "artifact" or parts[2] != "sha256" or not parts[3]:
        raise ValidationError(f"malformed artifact ref: {ref!r}", kind="contract")
    return parts[1], f"sha256:{parts[3]}"


def blob_hash_of_ref(ref: str) -> str:
    """The ``sha256:<hex>`` blob hash embedded in an ``artifact:`` ref."""
    return _split_ref(ref)[1]


def artifact_kind_of_ref(ref: str) -> str:
    """The ``<kind>`` segment of an ``artifact:`` ref.

    A **claim** by whoever wrote the ref, never evidence about the bytes: only
    :func:`hephaestus.core.project_store.artifact_kinds.recorded_kinds` speaks
    for the store. Kept here anyway so the claim is extracted by the same grammar
    that resolves the hash.
    """
    return _split_ref(ref)[0]


@dataclass(frozen=True)
class SourceSnapshot:
    """An immutable, registered read of one source file."""

    name: str
    path: Path
    content: str
    content_hash: str  # "sha256:<hex>" of the file bytes
    snapshot_ref: str  # SNAPSHOT_REF_PREFIX + content_hash


@dataclass(frozen=True)
class ImportSnapshot:
    """An immutable, registered read of one ``imports/`` file (INGEST.md §1).

    Binary, unlike :class:`SourceSnapshot`: a STEP payload is not text and is
    never decoded. The bytes are registered as an opstore blob at read time, so
    the build that froze them can replay the ORIGINAL content on a
    lost-response retry even after the file on disk has been replaced.
    """

    path: str  # as declared in the script, relative to imports/
    data: bytes
    content_hash: str  # "sha256:<hex>" of the file bytes
    snapshot_ref: str  # IMPORT_REF_PREFIX + content_hash


@dataclass(frozen=True)
class DriftEvidence:
    """External filesystem drift: live content no longer matches the record."""

    part: str
    recorded_hash: str
    live_hash: str | None  # None: the file is gone
    live_snapshot_ref: str | None  # registered snapshot of the observed version


@dataclass(frozen=True)
class WriteOutcome:
    """A committed (or replayed) part write."""

    snapshot: SourceSnapshot
    replayed: bool = False


class WriteConflictError(ConflictError):
    """Stale-base part write; carries live content plus base/attempted refs."""

    def __init__(
        self,
        message: str,
        *,
        part: str,
        live_hash: str | None,
        live_content: str | None,
        live_snapshot_ref: str | None,
        base_ref: str | None,
        attempted_ref: str,
    ) -> None:
        super().__init__(message)
        self.part = part
        self.live_hash = live_hash
        self.live_content = live_content
        self.live_snapshot_ref = live_snapshot_ref
        self.base_ref = base_ref
        self.attempted_ref = attempted_ref


class ProjectStore:
    """Snapshot-registering reads and WAL-backed CAS writes for one project."""

    def __init__(
        self,
        layout: ProjectLayout,
        store: OpStore,
        *,
        locks: LockManager | None = None,
        owner: OwnerId | None = None,
    ) -> None:
        self.layout = layout
        self._store = store
        self.locks = locks or LockManager(store, owner=owner)

    # -- reads --------------------------------------------------------------

    def _record_snapshot_kind(self, blob_hash: str) -> None:
        """Bind ``part-snapshot`` to these bytes in the store (§2.6, §19.24).

        The import is deferred because :mod:`.artifact_kinds` parses the ref
        grammar this module owns; importing it at module scope would be a cycle,
        and duplicating the grammar to break the cycle is the reimplementation
        mission rule 6 forbids. Same shape as the ``executor.imports`` import in
        :meth:`read_import` below.
        """
        from hephaestus.core.project_store.artifact_kinds import record_artifact_kind

        record_artifact_kind(self._store, SNAPSHOT_ARTIFACT_KIND, blob_hash)

    def _register(self, name: str, path: Path, data: bytes) -> SourceSnapshot:
        content_hash = self._store.blobs.put(data)
        self._record_snapshot_kind(content_hash)
        return SourceSnapshot(
            name=name,
            path=path,
            content=data.decode("utf-8"),
            content_hash=content_hash,
            snapshot_ref=SNAPSHOT_REF_PREFIX + content_hash,
        )

    def list_parts(self) -> tuple[str, ...]:
        """Lexically sorted part names present in ``parts/``."""
        return self.layout.part_names()

    def read_part(self, part: str) -> SourceSnapshot:
        """Read one part script, registering its content-addressed snapshot.

        A missing part raises ``addressing_error`` listing the parts that do
        exist as candidates.
        """
        path = self.layout.part_path(part)
        if not path.is_file():
            raise AddressingError(
                f"part {part!r} does not exist under {self.layout.parts_dir}",
                selector=part,
                candidates=self.list_parts(),
            )
        return self._register(part, path, path.read_bytes())

    def read_globals(self) -> SourceSnapshot | None:
        """Read ``globals.py`` (None when the project has no globals)."""
        path = self.layout.globals_path
        if not path.is_file():
            return None
        return self._register(GLOBALS_NAME, path, path.read_bytes())

    def read_import(self, path: str, *, kind: ImportKind = "step") -> ImportSnapshot:
        """Read one ``imports/`` file under path confinement, registering its bytes.

        Resolution is the executor's ``read_import`` walk (no-follow/beneath,
        rechecked at read time): traversal, absolute paths and symlink escapes
        raise the named ``ImportResolutionError`` from
        :mod:`hephaestus.core.executor.imports` rather than reading anything.

        ``kind`` is the declaration's kind and it resolves the ``MESH_INGEST.md``
        §1.6 byte ceiling. This is the freeze path, so a declaration exists and
        the ceiling comes from it: a file declared ``import_mesh`` is bounded as
        a mesh whatever it is named. Without the ceiling here the file would be
        in memory and in the blob store — the very next line — before any
        refusal could fire.
        """
        from hephaestus.core.executor.imports import max_bytes_for_kind
        from hephaestus.core.executor.imports import read_import as confined_read
        from hephaestus.core.project_store.artifact_kinds import record_artifact_kind

        data = confined_read(self.layout.imports_dir, path, max_bytes=max_bytes_for_kind(kind))
        content_hash = self._store.blobs.put(data)
        record_artifact_kind(self._store, IMPORT_ARTIFACT_KIND, content_hash)
        return ImportSnapshot(
            path=path,
            data=data,
            content_hash=content_hash,
            snapshot_ref=IMPORT_REF_PREFIX + content_hash,
        )

    def import_hash(self, path: str) -> str | None:
        """Live hash of one ``imports/`` file (``None`` when it cannot be read).

        Used by publication revalidation and staleness: a file that is gone,
        replaced by a symlink, or otherwise unreadable is "not the frozen
        bytes", which is all either caller needs to know.

        This path has **no declaration** to read a kind from —
        :meth:`ProjectStore.sync_import_state` drives it over every regular file
        beneath ``imports/``, declared or not — so the ``MESH_INGEST.md`` §1.6
        ceiling is resolved from the file extension instead. An undeclared 40 GB
        scan dropped into ``imports/`` would otherwise be read whole into the
        parent by the next staleness sync, which is the door a
        declaration-driven ceiling cannot close. An over-ceiling file lands as
        the ``None`` above: "not the frozen bytes" is already what a file this
        function cannot read means, so no caller learns a new behaviour.
        """
        from hephaestus.core.executor.imports import ImportResolutionError, max_bytes_for_path
        from hephaestus.core.executor.imports import read_import as confined_read

        try:
            data = confined_read(self.layout.imports_dir, path, max_bytes=max_bytes_for_path(path))
        except ImportResolutionError:
            return None
        return sha256_bytes(data)

    def list_imports(self) -> tuple[str, ...]:
        """Every regular file beneath ``imports/``, as posix-relative paths, sorted."""
        root = self.layout.imports_dir
        if not root.is_dir():
            return ()
        out: list[str] = []
        for path in sorted(root.rglob("*")):
            if path.is_symlink() or not path.is_file():
                continue
            out.append(path.relative_to(root).as_posix())
        return tuple(out)

    # -- drift --------------------------------------------------------------

    def external_drift(self, part: str, recorded_hash: str) -> DriftEvidence | None:
        """Compare the live file hash against a recorded snapshot hash.

        Returns ``None`` when unchanged; otherwise evidence with the observed
        version registered as an immutable snapshot (best-effort watcher
        semantics — no filesystem compare-and-swap is possible).
        """
        path = self.layout.part_path(part)
        if not path.is_file():
            return DriftEvidence(
                part=part, recorded_hash=recorded_hash, live_hash=None, live_snapshot_ref=None
            )
        data = path.read_bytes()
        live_hash = sha256_bytes(data)
        if live_hash == recorded_hash:
            return None
        snapshot = self._register(part, path, data)
        return DriftEvidence(
            part=part,
            recorded_hash=recorded_hash,
            live_hash=live_hash,
            live_snapshot_ref=snapshot.snapshot_ref,
        )

    # -- writes -------------------------------------------------------------

    def write_part(
        self,
        part: str,
        content: str,
        *,
        base_hash: str | None,
        op_id: str,
    ) -> WriteOutcome:
        """CAS write of one part script through the opstore WAL.

        ``base_hash`` is the content hash the edit was computed against
        (``None`` = the file must not exist yet). A mismatching live hash
        raises :class:`WriteConflictError` with the current content/hash and
        refs for the base and the exact attempted candidate — nothing is
        written. The mutation itself is idempotent on ``op_id`` (a retry of a
        committed write replays without re-executing) and journals the
        preimage under ``.heph/journal/``.
        """
        path = self.layout.part_path(part)
        raw = content.encode("utf-8")
        after_hash = sha256_bytes(raw)
        self.locks.acquire(part_lock(part))
        try:
            payload: JSONValue = {
                "kind": "part_write",
                "part": part,
                "base": base_hash,
                "after": after_hash,
            }
            payload_hash = sha256_canonical_json(payload)
            outcome = self._store.opkeys.begin(op_id, payload_hash)
            if isinstance(outcome, PendingRecovery):
                self._store.wal.recover(outcome.op_key)
                outcome = self._store.opkeys.begin(op_id, payload_hash)
            if isinstance(outcome, Replay):
                # Committed retry: the recorded outcome stands, never re-executed.
                return WriteOutcome(
                    snapshot=SourceSnapshot(
                        name=part,
                        path=path,
                        content=content,
                        content_hash=after_hash,
                        snapshot_ref=SNAPSHOT_REF_PREFIX + after_hash,
                    ),
                    replayed=True,
                )
            if not isinstance(outcome, Fresh):
                raise ConflictError(
                    f"part write {op_id!r} cannot proceed: unresolved prior state {outcome!r}"
                )
            live: bytes | None = path.read_bytes() if path.is_file() else None
            live_hash = None if live is None else sha256_bytes(live)
            if live_hash != base_hash:
                self._store.wal.recover(outcome.op_key)  # aborts the fresh skeleton
                attempted = self._store.blobs.put(raw)
                # `attempted_ref` below is a `part-snapshot` ref the §9.3 merge
                # prompt pages through `GET /artifacts/{ref}/text`; it is minted
                # here rather than by `_register`, so it is bound here too.
                self._record_snapshot_kind(attempted)
                live_snapshot_ref = None
                if live is not None:
                    live_snapshot_ref = self._register(part, path, live).snapshot_ref
                raise WriteConflictError(
                    f"part {part!r} changed since base {base_hash!r} "
                    f"(live is {live_hash!r}); write refused",
                    part=part,
                    live_hash=live_hash,
                    live_content=None if live is None else live.decode("utf-8"),
                    live_snapshot_ref=live_snapshot_ref,
                    base_ref=None if base_hash is None else SNAPSHOT_REF_PREFIX + base_hash,
                    attempted_ref=SNAPSHOT_REF_PREFIX + attempted,
                )
            self._journal_preimage(
                op_id=op_id,
                part=part,
                target=path,
                before_hash=live_hash,
                preimage=live,
                after_hash=after_hash,
            )
            try:
                self._store.wal.execute(
                    outcome,
                    path,
                    raw,
                    intended_outcome=canonical_json({"part": part, "content_hash": after_hash}),
                )
            except ConflictedError as exc:
                raise WriteConflictError(
                    f"part {part!r} changed underneath the commit: {exc}",
                    part=part,
                    live_hash=sha256_bytes(path.read_bytes()) if path.is_file() else None,
                    live_content=path.read_text(encoding="utf-8") if path.is_file() else None,
                    live_snapshot_ref=None,
                    base_ref=None if base_hash is None else SNAPSHOT_REF_PREFIX + base_hash,
                    attempted_ref=SNAPSHOT_REF_PREFIX + after_hash,
                ) from exc
            return WriteOutcome(snapshot=self._register(part, path, raw), replayed=False)
        finally:
            self.locks.release(part_lock(part))

    def _journal_preimage(
        self,
        *,
        op_id: str,
        part: str,
        target: Path,
        before_hash: str | None,
        preimage: bytes | None,
        after_hash: str,
    ) -> None:
        """Durable preimage journal entry under ``.heph/journal/`` (30d class)."""
        preimage_blob = None if preimage is None else self._store.blobs.put(preimage)
        entry: JSONValue = {
            "kind": "part_write",
            "op_id": op_id,
            "part": part,
            "target": str(target),
            "before_hash": before_hash,
            "preimage_blob": preimage_blob,
            "after_hash": after_hash,
        }
        self.layout.journal_dir.mkdir(parents=True, exist_ok=True)
        entry_name = sha256_canonical_json(entry).removeprefix("sha256:")[:32]
        journal_path = self.layout.journal_dir / f"{entry_name}.json"
        journal_path.write_text(canonical_json(entry), encoding="utf-8")
