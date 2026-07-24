"""Tests for opstore.keyring: creation, rotation, fail-closed open, purge horizon."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
from conftest import FakeClock
from opstore.errors import KeyringCorruptError, KeyringMissingError, NotFoundError
from opstore.keyring import KEYS_DIRNAME, Keyring

DAY = 86_400.0


def key_files(root: Path) -> list[Path]:
    return sorted((root / KEYS_DIRNAME).glob("*.json"))


def test_create_makes_one_active_key_mode_0600(store_root: Path, fake_clock: FakeClock) -> None:
    ring = Keyring.create(store_root, clock=fake_clock)
    files = key_files(store_root)
    assert len(files) == 1
    mode = stat.S_IMODE(files[0].stat().st_mode)
    assert mode == 0o600
    record = json.loads(files[0].read_text())
    assert record["key_id"] == ring.active_key_id
    assert record["retired_at"] is None
    assert record["created_at"] == fake_clock.now()
    assert not list((store_root / KEYS_DIRNAME).glob(".*tmp"))


def test_create_fails_if_keys_exist(store_root: Path, fake_clock: FakeClock) -> None:
    Keyring.create(store_root, clock=fake_clock)
    with pytest.raises(KeyringCorruptError):
        Keyring.create(store_root, clock=fake_clock)


def test_open_roundtrip(store_root: Path, fake_clock: FakeClock) -> None:
    created = Keyring.create(store_root, clock=fake_clock)
    mac = created.mac(created.active_key_id, b"payload")
    reopened = Keyring.open(store_root, clock=fake_clock)
    assert reopened.active_key_id == created.active_key_id
    assert reopened.verify(b"payload", mac) == created.active_key_id


def test_open_fails_closed_when_state_exists_without_keys(
    store_root: Path, fake_clock: FakeClock
) -> None:
    (store_root / "state.db").write_bytes(b"")
    with pytest.raises(KeyringMissingError) as excinfo:
        Keyring.open(store_root, clock=fake_clock)
    assert excinfo.value.code == "keyring_missing"
    assert "restore" in str(excinfo.value)
    # And it must not have silently regenerated anything.
    assert not key_files(store_root)


def test_open_missing_without_state(store_root: Path, fake_clock: FakeClock) -> None:
    with pytest.raises(KeyringMissingError):
        Keyring.open(store_root, clock=fake_clock)


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        "[]",
        '{"key_id": "x"}',
        '{"key_id": "x", "secret_hex": "zz", "created_at": 0, "retired_at": null}',
        '{"key_id": "x", "secret_hex": "", "created_at": 0, "retired_at": null}',
        '{"key_id": "other", "secret_hex": "ab", "created_at": 0, "retired_at": null}',
    ],
)
def test_open_corrupt_key_file_fails_closed(
    store_root: Path, fake_clock: FakeClock, content: str
) -> None:
    Keyring.create(store_root, clock=fake_clock)
    (store_root / KEYS_DIRNAME / "x.json").write_text(content)
    with pytest.raises(KeyringCorruptError) as excinfo:
        Keyring.open(store_root, clock=fake_clock)
    assert excinfo.value.code == "keyring_corrupt"


def test_open_zero_or_two_active_keys_is_corrupt(store_root: Path, fake_clock: FakeClock) -> None:
    ring = Keyring.create(store_root, clock=fake_clock)
    # Second active key -> corrupt.
    twin = json.loads(key_files(store_root)[0].read_text())
    twin["key_id"] = "kdeadbeefdeadbeef"
    (store_root / KEYS_DIRNAME / "kdeadbeefdeadbeef.json").write_text(json.dumps(twin))
    with pytest.raises(KeyringCorruptError):
        Keyring.open(store_root, clock=fake_clock)
    (store_root / KEYS_DIRNAME / "kdeadbeefdeadbeef.json").unlink()
    # Zero active keys -> corrupt.
    active_path = store_root / KEYS_DIRNAME / f"{ring.active_key_id}.json"
    record = json.loads(active_path.read_text())
    record["retired_at"] = fake_clock.now()
    active_path.write_text(json.dumps(record))
    with pytest.raises(KeyringCorruptError):
        Keyring.open(store_root, clock=fake_clock)


def test_mac_verify_roundtrip_and_negative(store_root: Path, fake_clock: FakeClock) -> None:
    ring = Keyring.create(store_root, clock=fake_clock)
    mac = ring.mac(ring.active_key_id, b"data")
    assert ring.verify(b"data", mac) == ring.active_key_id
    assert ring.verify(b"other", mac) is None
    assert ring.verify(b"data", "00" * 32) is None
    with pytest.raises(NotFoundError):
        ring.mac("knope", b"data")


def test_rotate_retains_old_key_for_verification(store_root: Path, fake_clock: FakeClock) -> None:
    ring = Keyring.create(store_root, clock=fake_clock)
    old_id = ring.active_key_id
    mac = ring.mac(old_id, b"data")
    fake_clock.advance(10.0)
    new_id = ring.rotate()
    assert new_id != old_id
    assert ring.active_key_id == new_id
    assert ring.verify(b"data", mac) == old_id
    assert ring.mac(old_id, b"data") == mac
    # Durable on disk: reopen sees both, same active.
    reopened = Keyring.open(store_root, clock=fake_clock)
    assert reopened.active_key_id == new_id
    assert reopened.verify(b"data", mac) == old_id
    retired = json.loads((store_root / KEYS_DIRNAME / f"{old_id}.json").read_text())
    assert retired["retired_at"] == fake_clock.now()
    assert stat.S_IMODE((store_root / KEYS_DIRNAME / f"{new_id}.json").stat().st_mode) == 0o600


def test_purge_horizon_37_days(store_root: Path, fake_clock: FakeClock) -> None:
    ring = Keyring.create(store_root, clock=fake_clock)
    old_id = ring.active_key_id
    mac = ring.mac(old_id, b"data")
    ring.rotate()

    fake_clock.advance(36 * DAY)
    assert ring.purge() == ()
    assert ring.verify(b"data", mac) == old_id

    fake_clock.advance(1 * DAY)  # exactly 37 d after retirement -> horizon reached
    assert ring.verify(b"data", mac) is None  # expired for verification
    assert ring.purge() == (old_id,)
    assert not (store_root / KEYS_DIRNAME / f"{old_id}.json").exists()
    assert ring.purge() == ()
    # Active key never purged.
    assert (store_root / KEYS_DIRNAME / f"{ring.active_key_id}.json").exists()


def test_purge_never_touches_active_even_far_future(
    store_root: Path, fake_clock: FakeClock
) -> None:
    ring = Keyring.create(store_root, clock=fake_clock)
    fake_clock.advance(400 * DAY)
    assert ring.purge() == ()
    mac = ring.mac(ring.active_key_id, b"x")
    assert ring.verify(b"x", mac) == ring.active_key_id


def test_multiple_rotations_verify_across_generations(
    store_root: Path, fake_clock: FakeClock
) -> None:
    ring = Keyring.create(store_root, clock=fake_clock)
    macs: list[tuple[str, str]] = []
    for _ in range(4):
        macs.append((ring.active_key_id, ring.mac(ring.active_key_id, b"m")))
        fake_clock.advance(DAY)
        ring.rotate()
    for key_id, mac in macs:
        assert ring.verify(b"m", mac) == key_id
    assert len(ring.key_ids()) == 5
