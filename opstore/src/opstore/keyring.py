"""HMAC keyring under ``<root>/keys/``.

Contract (DESIGN.md "keyring.py"):

- One JSON file per key: ``{key_id, secret_hex, created_at, retired_at|null}``,
  file mode 0600, created atomically (same-directory temp + rename + dir fsync).
- ``Keyring.create(root)`` fails if any keys already exist. ``Keyring.open(root)``
  **fails closed** — ``KeyringMissingError``/``KeyringCorruptError`` — whenever
  the keyring is absent or invalid; it never silently regenerates keys, even
  (especially) when ``<root>/state.db`` exists.
- ``rotate()`` creates a new active key; retired keys remain verifiable for at
  least ``key_retirement_retention_s`` (default 37 days) after retirement, and
  ``purge()`` deletes only keys past that horizon.
- ``mac(key_id, data)`` / ``verify(data, mac_hex) -> key_id | None`` use
  HMAC-SHA256; verification tries the active key then unexpired retired keys.
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from opstore.errors import KeyringCorruptError, KeyringMissingError, NotFoundError
from opstore.types import Clock, StoreConfig, SystemClock

KEYS_DIRNAME = "keys"
_SECRET_BYTES = 32


@dataclass(frozen=True, slots=True)
class KeyRecord:
    """In-memory image of one key file."""

    key_id: str
    secret: bytes
    created_at: float
    retired_at: float | None


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_key_file(keys_dir: Path, record: KeyRecord) -> None:
    """Atomically (temp + rename) write ``record`` with mode 0600 and fsync."""
    payload = json.dumps(
        {
            "key_id": record.key_id,
            "secret_hex": record.secret.hex(),
            "created_at": record.created_at,
            "retired_at": record.retired_at,
        },
        sort_keys=True,
    ).encode("utf-8")
    tmp = keys_dir / f".{record.key_id}.{os.getpid()}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.rename(tmp, keys_dir / f"{record.key_id}.json")
    _fsync_dir(keys_dir)


def _load_key_file(path: Path) -> KeyRecord:
    try:
        parsed: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise KeyringCorruptError(f"unreadable key file {path.name}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise KeyringCorruptError(f"key file {path.name} is not a JSON object")
    raw = cast(dict[str, object], parsed)
    key_id = raw.get("key_id")
    secret_hex = raw.get("secret_hex")
    created_at = raw.get("created_at")
    retired_at = raw.get("retired_at")
    if (
        not isinstance(key_id, str)
        or not isinstance(secret_hex, str)
        or not isinstance(created_at, int | float)
        or not (retired_at is None or isinstance(retired_at, int | float))
    ):
        raise KeyringCorruptError(f"key file {path.name} has invalid fields")
    if key_id != path.stem:
        raise KeyringCorruptError(f"key file {path.name} embeds mismatched key_id {key_id!r}")
    try:
        secret = bytes.fromhex(secret_hex)
    except ValueError as exc:
        raise KeyringCorruptError(f"key file {path.name} has non-hex secret") from exc
    if not secret:
        raise KeyringCorruptError(f"key file {path.name} has empty secret")
    return KeyRecord(
        key_id=key_id,
        secret=secret,
        created_at=float(created_at),
        retired_at=None if retired_at is None else float(retired_at),
    )


class Keyring:
    """Active + retired HMAC-SHA256 keys with fail-closed open semantics."""

    def __init__(
        self,
        root: Path,
        keys: dict[str, KeyRecord],
        active_key_id: str,
        clock: Clock,
        retention_s: float,
    ) -> None:
        self._root = root
        self._keys = keys
        self._active_key_id = active_key_id
        self._clock = clock
        self._retention_s = retention_s

    @staticmethod
    def _keys_dir(root: Path) -> Path:
        return root / KEYS_DIRNAME

    @classmethod
    def create(
        cls,
        root: Path,
        clock: Clock | None = None,
        config: StoreConfig | None = None,
    ) -> Keyring:
        """Create a fresh keyring with one active key; fails if any key exists."""
        clock = clock or SystemClock()
        config = config or StoreConfig()
        keys_dir = cls._keys_dir(root)
        keys_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        if any(keys_dir.glob("*.json")):
            raise KeyringCorruptError(f"keyring already exists under {keys_dir}")
        record = _new_key(clock)
        _write_key_file(keys_dir, record)
        return cls(
            root,
            {record.key_id: record},
            record.key_id,
            clock,
            config.key_retirement_retention_s,
        )

    @classmethod
    def open(
        cls,
        root: Path,
        clock: Clock | None = None,
        config: StoreConfig | None = None,
    ) -> Keyring:
        """Open an existing keyring; fails closed if missing or corrupt."""
        clock = clock or SystemClock()
        config = config or StoreConfig()
        keys_dir = cls._keys_dir(root)
        key_paths = sorted(keys_dir.glob("*.json")) if keys_dir.is_dir() else []
        if not key_paths:
            state_hint = (
                " while store state exists; restore the keyring backup"
                if (root / "state.db").exists()
                else ""
            )
            raise KeyringMissingError(f"no keyring under {keys_dir}{state_hint}")
        keys: dict[str, KeyRecord] = {}
        for path in key_paths:
            record = _load_key_file(path)
            keys[record.key_id] = record
        active = [record for record in keys.values() if record.retired_at is None]
        if len(active) != 1:
            raise KeyringCorruptError(
                f"keyring under {keys_dir} has {len(active)} active keys (expected 1)"
            )
        return cls(root, keys, active[0].key_id, clock, config.key_retirement_retention_s)

    @property
    def active_key_id(self) -> str:
        return self._active_key_id

    def key_ids(self) -> tuple[str, ...]:
        """All known key ids (active first, then retired, stable order)."""
        retired = sorted(key_id for key_id in self._keys if key_id != self._active_key_id)
        return (self._active_key_id, *retired)

    def rotate(self) -> str:
        """Retire the active key and create a new active key; returns its key_id."""
        keys_dir = self._keys_dir(self._root)
        now = self._clock.now()
        old = self._keys[self._active_key_id]
        retired = KeyRecord(
            key_id=old.key_id,
            secret=old.secret,
            created_at=old.created_at,
            retired_at=now,
        )
        _write_key_file(keys_dir, retired)
        self._keys[retired.key_id] = retired
        record = _new_key(self._clock)
        _write_key_file(keys_dir, record)
        self._keys[record.key_id] = record
        self._active_key_id = record.key_id
        return record.key_id

    def purge(self) -> tuple[str, ...]:
        """Delete retired keys past the retention horizon; returns purged key_ids."""
        keys_dir = self._keys_dir(self._root)
        now = self._clock.now()
        purged: list[str] = []
        for record in list(self._keys.values()):
            if record.retired_at is None:
                continue
            if record.retired_at + self._retention_s <= now:
                (keys_dir / f"{record.key_id}.json").unlink(missing_ok=True)
                del self._keys[record.key_id]
                purged.append(record.key_id)
        if purged:
            _fsync_dir(keys_dir)
        return tuple(purged)

    def mac(self, key_id: str, data: bytes) -> str:
        """HMAC-SHA256 hex digest of ``data`` under the named key."""
        record = self._keys.get(key_id)
        if record is None:
            raise NotFoundError(f"unknown key_id {key_id!r}")
        return hmac.new(record.secret, data, "sha256").hexdigest()

    def verify(self, data: bytes, mac_hex: str) -> str | None:
        """key_id whose HMAC over ``data`` matches, or None.

        Tries the active key first, then retired keys still inside the
        retention horizon.
        """
        now = self._clock.now()
        for key_id in self.key_ids():
            record = self._keys[key_id]
            if (
                record.retired_at is not None
                and record.retired_at + self._retention_s <= now
            ):
                continue
            expected = hmac.new(record.secret, data, "sha256").hexdigest()
            if hmac.compare_digest(expected, mac_hex):
                return key_id
        return None


def _new_key(clock: Clock) -> KeyRecord:
    return KeyRecord(
        key_id="k" + secrets.token_hex(8),
        secret=secrets.token_bytes(_SECRET_BYTES),
        created_at=clock.now(),
        retired_at=None,
    )
