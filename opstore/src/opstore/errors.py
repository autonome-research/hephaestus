"""Typed exceptions with stable structured error codes for opstore.

Every exception carries a stable ``code`` string from the vocabulary fixed in
DESIGN.md: ``key_expired``, ``key_payload_mismatch``, ``key_timestamp_skew``,
``keyring_missing``, ``keyring_corrupt``, ``busy``, ``artifact_expired``,
``protected_quota_exceeded``, ``conflicted``, ``lease_held``, ``lease_expired``,
``terminal_conflict``, ``not_found``. Callers dispatch on ``code`` (or the
exception type); message text is informational only.
"""

from __future__ import annotations


class OpStoreError(Exception):
    """Base class for all opstore errors; carries a stable ``code``."""

    code: str = "opstore_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class KeyExpiredError(OpStoreError):
    """Operation key is older than the idempotency window (never executed/replayed)."""

    code = "key_expired"


class KeyPayloadMismatchError(OpStoreError):
    """Operation key reused with a different canonical payload hash."""

    code = "key_payload_mismatch"


class KeyTimestampSkewError(OpStoreError):
    """First-seen key whose embedded timestamp is outside the freshness window."""

    code = "key_timestamp_skew"


class KeyringError(OpStoreError):
    """Base for keyring failures (missing or corrupt keyring state)."""

    code = "keyring_error"


class KeyringMissingError(KeyringError):
    """Keyring absent while store state exists; requires explicit restore."""

    code = "keyring_missing"


class KeyringCorruptError(KeyringError):
    """Keyring present but unreadable/invalid; requires explicit recovery."""

    code = "keyring_corrupt"


class BusyError(OpStoreError):
    """No admission slot available."""

    code = "busy"


class ArtifactExpiredError(OpStoreError):
    """Referenced artifact was garbage-collected before acquisition."""

    code = "artifact_expired"


class ProtectedQuotaExceededError(OpStoreError):
    """Protected + pinned artifacts alone exceed the configured quota."""

    code = "protected_quota_exceeded"


class ConflictedError(OpStoreError):
    """Compare-and-swap or recovery observed a third-party/hash conflict."""

    code = "conflicted"


class LeaseHeldError(OpStoreError):
    """A conflicting live lease is held on the ref."""

    code = "lease_held"


class LeaseExpiredError(OpStoreError):
    """The lease no longer exists or its heartbeat TTL elapsed and it was reclaimed."""

    code = "lease_expired"


class TerminalConflictError(OpStoreError):
    """A second distinct terminal was presented for an already-terminal run."""

    code = "terminal_conflict"


class NotFoundError(OpStoreError):
    """Referenced entity (blob, pointer, row) does not exist."""

    code = "not_found"
