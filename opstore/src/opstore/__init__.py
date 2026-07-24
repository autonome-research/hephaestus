"""opstore: generic durability substrate (WAL, idempotency, CAS, leases, admission, GC).

Public API. ``OpStore`` is a small facade over one store root that wires the
module layer — ``Database``, ``Keyring``, ``BlobStore``, ``OpKeys``, ``Wal``,
``LeaseManager``, ``AdmissionControl``, ``Gc`` — with shared injectables
(``Clock``, ``Liveness``, ``CrashHook``, ``LockProvider``). Each module remains
directly usable with a ``Database`` handle.

Facade contract (DESIGN.md "Core conventions" + keyring fail-closed):

- ``OpStore.create(root)`` initializes ``<root>/keys/`` (fresh keyring) and
  ``<root>/state.db``; it fails with ``conflicted`` if store state already
  exists and never mints a keyring over existing state.
- ``OpStore.open(root)`` requires existing state and opens the keyring
  **fail-closed**: a missing or corrupt keyring raises
  ``KeyringMissingError``/``KeyringCorruptError`` and is never regenerated.
- ``recover()`` runs startup recovery: WAL ``recover_all()`` then admission
  ``startup_reconstruct()``.
- ``gc`` is wired with ``opkeys.purge`` as a purge hook, so every non-dry
  ``collect()`` also enforces the outcome/tombstone horizons.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from opstore.admission import (
    AdmissionControl,
    AdmissionRow,
    RecoveryReason,
    RecoveryResult,
    StartupReport,
    TerminalRecord,
)
from opstore.blobs import BlobStore
from opstore.db import Database
from opstore.errors import (
    ArtifactExpiredError,
    BusyError,
    ConflictedError,
    KeyExpiredError,
    KeyPayloadMismatchError,
    KeyringCorruptError,
    KeyringError,
    KeyringMissingError,
    KeyTimestampSkewError,
    LeaseExpiredError,
    LeaseHeldError,
    NotFoundError,
    OpStoreError,
    ProtectedQuotaExceededError,
    TerminalConflictError,
)
from opstore.gc import Gc, GcAction, GcCandidate, GcReport, GcUsage, ProtectedRoots
from opstore.hashing import (
    canonical_json,
    is_hash,
    sha256_bytes,
    sha256_canonical_json,
    sha256_file,
)
from opstore.keyring import Keyring
from opstore.leases import Lease, LeaseManager
from opstore.opkeys import BeginOutcome, Fresh, OpKeys, PendingRecovery, PurgeReport, Replay
from opstore.types import (
    AdmissionState,
    Clock,
    CrashHook,
    JSONValue,
    LeaseMode,
    Liveness,
    OperationState,
    OwnerId,
    StoreConfig,
    TerminalState,
    current_owner,
)
from opstore.wal import LockProvider, PreparedOp, PublishOp, Wal, WalOutcome

__all__ = [
    "AdmissionControl",
    "AdmissionRow",
    "AdmissionState",
    "ArtifactExpiredError",
    "BeginOutcome",
    "BlobStore",
    "BusyError",
    "Clock",
    "ConflictedError",
    "CrashHook",
    "Database",
    "Fresh",
    "Gc",
    "GcAction",
    "GcCandidate",
    "GcReport",
    "GcUsage",
    "JSONValue",
    "KeyExpiredError",
    "KeyPayloadMismatchError",
    "KeyTimestampSkewError",
    "Keyring",
    "KeyringCorruptError",
    "KeyringError",
    "KeyringMissingError",
    "Lease",
    "LeaseExpiredError",
    "LeaseHeldError",
    "LeaseManager",
    "LeaseMode",
    "Liveness",
    "LockProvider",
    "NotFoundError",
    "OpKeys",
    "OpStore",
    "OpStoreError",
    "OpStoreRecovery",
    "OperationState",
    "OwnerId",
    "PendingRecovery",
    "PreparedOp",
    "ProtectedQuotaExceededError",
    "ProtectedRoots",
    "PublishOp",
    "PurgeReport",
    "RecoveryReason",
    "RecoveryResult",
    "Replay",
    "StartupReport",
    "StoreConfig",
    "TerminalConflictError",
    "TerminalRecord",
    "TerminalState",
    "Wal",
    "WalOutcome",
    "canonical_json",
    "current_owner",
    "is_hash",
    "sha256_bytes",
    "sha256_canonical_json",
    "sha256_file",
]

STATE_DB_NAME = "state.db"


@dataclass(frozen=True, slots=True)
class OpStoreRecovery:
    """Startup-recovery report: resolved WAL operations plus admission occupancy."""

    wal: tuple[WalOutcome, ...]
    admission: StartupReport


class OpStore:
    """One store root: ``<root>/state.db``, ``<root>/keys/``, ``<root>/blobs/``."""

    def __init__(
        self,
        root: Path,
        config: StoreConfig,
        db: Database,
        keyring: Keyring,
        *,
        clock: Clock | None = None,
        liveness: Liveness | None = None,
        crash_hook: CrashHook | None = None,
        lock_provider: LockProvider | None = None,
        protected_roots: ProtectedRoots | None = None,
    ) -> None:
        self.root = root
        self.config = config
        self.db = db
        self.keyring = keyring
        self.blobs = BlobStore(root, db, clock=clock, crash_hook=crash_hook)
        self.opkeys = OpKeys(db, keyring, clock=clock, config=config)
        self.wal = Wal(
            db, self.blobs, clock=clock, crash_hook=crash_hook, lock_provider=lock_provider
        )
        self.leases = LeaseManager(db, clock=clock, liveness=liveness, crash_hook=crash_hook)
        self.admission = AdmissionControl(
            db, config=config, clock=clock, liveness=liveness, crash_hook=crash_hook
        )
        self.gc = Gc(
            root,
            db,
            config,
            clock=clock,
            liveness=liveness,
            crash_hook=crash_hook,
            protected_roots=protected_roots,
            purge_hooks=(self.opkeys.purge,),
        )

    @classmethod
    def create(
        cls,
        root: Path,
        config: StoreConfig | None = None,
        *,
        clock: Clock | None = None,
        liveness: Liveness | None = None,
        crash_hook: CrashHook | None = None,
        lock_provider: LockProvider | None = None,
        protected_roots: ProtectedRoots | None = None,
    ) -> OpStore:
        """Initialize a fresh store at ``root`` (keyring first, then state.db).

        Fails with ``ConflictedError`` if ``<root>/state.db`` already exists and
        with ``KeyringCorruptError`` if a keyring already exists: existing state
        never gets a silently regenerated keyring (open() is fail-closed too).
        """
        config = config or StoreConfig()
        root.mkdir(parents=True, exist_ok=True)
        if (root / STATE_DB_NAME).exists():
            raise ConflictedError(f"store already exists at {root}; use OpStore.open()")
        keyring = Keyring.create(root, clock=clock, config=config)
        db = Database.connect(root / STATE_DB_NAME)
        return cls(
            root,
            config,
            db,
            keyring,
            clock=clock,
            liveness=liveness,
            crash_hook=crash_hook,
            lock_provider=lock_provider,
            protected_roots=protected_roots,
        )

    @classmethod
    def open(
        cls,
        root: Path,
        config: StoreConfig | None = None,
        *,
        clock: Clock | None = None,
        liveness: Liveness | None = None,
        crash_hook: CrashHook | None = None,
        lock_provider: LockProvider | None = None,
        protected_roots: ProtectedRoots | None = None,
    ) -> OpStore:
        """Open an existing store; the keyring check is fail-closed and runs first.

        ``NotFoundError`` if ``<root>/state.db`` is absent;
        ``KeyringMissingError``/``KeyringCorruptError`` if state exists but the
        keyring is missing or invalid (explicit restore required — the keyring
        and state.db are one backup unit and are never regenerated).
        """
        config = config or StoreConfig()
        if not (root / STATE_DB_NAME).exists():
            raise NotFoundError(f"no store at {root} ({STATE_DB_NAME} missing)")
        keyring = Keyring.open(root, clock=clock, config=config)
        db = Database.connect(root / STATE_DB_NAME)
        return cls(
            root,
            config,
            db,
            keyring,
            clock=clock,
            liveness=liveness,
            crash_hook=crash_hook,
            lock_provider=lock_provider,
            protected_roots=protected_roots,
        )

    def recover(self) -> OpStoreRecovery:
        """Startup recovery: resolve every PREPARED WAL op, then rebuild occupancy."""
        wal_outcomes = self.wal.recover_all()
        report = self.admission.startup_reconstruct()
        return OpStoreRecovery(wal=wal_outcomes, admission=report)

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self.db.close()

    def __enter__(self) -> OpStore:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
