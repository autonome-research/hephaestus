"""Tests for opstore.wal: prepare/commit, recovery matrix, pointer publish, crash injection."""

from __future__ import annotations

import shutil
import time
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path

import pytest
from _optest import CrashRunner
from hypothesis import given, settings
from hypothesis import strategies as st
from opstore.blobs import BlobStore
from opstore.db import Database
from opstore.errors import ConflictedError, NotFoundError
from opstore.hashing import sha256_bytes
from opstore.keyring import Keyring
from opstore.opkeys import Fresh, OpKeys, PendingRecovery, Replay
from opstore.wal import (
    CRASH_PUBLISH_AFTER_COMMITTED,
    CRASH_PUBLISH_AFTER_PREPARED,
    CRASH_PUBLISH_AFTER_SWAP,
    FILE_CRASH_POINTS,
    PUBLISH_CRASH_POINTS,
    PreparedOp,
    PublishOp,
    Wal,
    WalOutcome,
)

RAW_ID = "op-crash-1"
INITIAL = b"initial contents\n"
CANDIDATE = b"candidate contents v2\n"
RESPONSE = '{"ok": true, "rev": 2}'
PAYLOAD = sha256_bytes(b"wal payload")
BUNDLE = b"bundle bytes for publish\n"


class _Crash(Exception):
    """In-process stand-in for a hard crash at a named point."""


class RaisingCrashHook:
    """Crash hook that raises ``_Crash`` at one named point."""

    def __init__(self, point: str) -> None:
        self.point = point

    def maybe_crash(self, point: str) -> None:
        if point == self.point:
            raise _Crash(point)


class RecordingLockProvider:
    """Lock provider that records every target it was asked to lock."""

    def __init__(self) -> None:
        self.locked: list[str] = []

    def lock(self, target: str) -> AbstractContextManager[None]:
        self.locked.append(target)
        return nullcontext()


@pytest.fixture
def keyring(store_root: Path) -> Keyring:
    return Keyring.create(store_root)


@pytest.fixture
def blobs(store_root: Path, db: Database) -> BlobStore:
    return BlobStore(store_root, db)


@pytest.fixture
def opkeys(db: Database, keyring: Keyring) -> OpKeys:
    return OpKeys(db, keyring)


@pytest.fixture
def wal(db: Database, blobs: BlobStore) -> Wal:
    return Wal(db, blobs)


@pytest.fixture
def target(store_root: Path) -> Path:
    path = store_root / "data" / "target.txt"
    path.parent.mkdir()
    path.write_bytes(INITIAL)
    return path


def _fresh(opkeys: OpKeys, raw_id: str = RAW_ID) -> Fresh:
    outcome = opkeys.begin(raw_id, PAYLOAD)
    assert isinstance(outcome, Fresh)
    return outcome


def _row(db: Database, op_key: str) -> dict[str, object]:
    row = db.conn.execute("SELECT * FROM operations WHERE op_key = ?", (op_key,)).fetchone()
    assert row is not None
    return dict(zip(row.keys(), tuple(row), strict=True))


def test_prepare_commit_happy_path(
    opkeys: OpKeys, wal: Wal, blobs: BlobStore, db: Database, target: Path
) -> None:
    fresh = _fresh(opkeys)
    prepared = wal.prepare(fresh, target, CANDIDATE, intended_outcome=RESPONSE)
    assert prepared.before_hash == sha256_bytes(INITIAL)
    assert prepared.after_hash == sha256_bytes(CANDIDATE)
    assert prepared.preimage_blob is not None
    assert blobs.get(prepared.preimage_blob) == INITIAL
    assert blobs.get(prepared.candidate_blob) == CANDIDATE
    assert prepared.candidate_temp.exists()
    assert target.read_bytes() == INITIAL  # nothing installed yet
    row = _row(db, fresh.op_key)
    assert row["state"] == "PREPARED"
    assert row["target_path"] == str(target)
    assert row["intended_outcome"] == RESPONSE

    outcome = wal.commit(prepared)
    assert outcome.action == "committed"
    assert outcome.response == RESPONSE
    assert target.read_bytes() == CANDIDATE
    assert not prepared.candidate_temp.exists()
    row = _row(db, fresh.op_key)
    assert row["state"] == "COMMITTED"
    assert row["response"] == RESPONSE

    replay = opkeys.begin(RAW_ID, PAYLOAD)
    assert isinstance(replay, Replay)
    assert replay.response == RESPONSE
    assert replay.commit_hash == sha256_bytes(CANDIDATE)


def test_execute_creates_new_file_without_preimage(
    opkeys: OpKeys, wal: Wal, db: Database, store_root: Path
) -> None:
    target = store_root / "data" / "fresh.txt"
    fresh = _fresh(opkeys)
    outcome = wal.execute(fresh, target, CANDIDATE, intended_outcome=RESPONSE)
    assert outcome.action == "committed"
    assert target.read_bytes() == CANDIDATE
    row = _row(db, fresh.op_key)
    assert row["before_hash"] is None
    assert row["preimage_blob"] is None
    assert row["state"] == "COMMITTED"


def test_prepare_requires_registration(wal: Wal, keyring: Keyring, target: Path) -> None:
    bogus = Fresh(op_key="v1.1.0.k.mac", raw_id="x", key_id="k", ts=1.0, payload_hash=PAYLOAD)
    with pytest.raises(NotFoundError):
        wal.prepare(bogus, target, CANDIDATE, intended_outcome=RESPONSE)


def test_validate_runs_inside_prepared_txn_and_rolls_back(
    opkeys: OpKeys, wal: Wal, db: Database, target: Path
) -> None:
    fresh = _fresh(opkeys)
    seen: list[PreparedOp] = []

    def failing_validate(prepared: PreparedOp) -> None:
        seen.append(prepared)
        raise ValueError("domain validation failed")

    with pytest.raises(ValueError):
        wal.prepare(fresh, target, CANDIDATE, intended_outcome=RESPONSE, validate=failing_validate)
    assert len(seen) == 1
    assert target.read_bytes() == INITIAL
    row = _row(db, fresh.op_key)
    assert row["state"] == "PREPARED"
    assert row["target_path"] is None  # rolled back to skeleton
    # Recovery aborts the skeleton and frees the key for a fresh retry.
    outcome = wal.recover(fresh.op_key)
    assert outcome.action == "aborted"
    retry = opkeys.begin(RAW_ID, PAYLOAD)
    assert isinstance(retry, Fresh)


def test_validate_success_is_recorded(opkeys: OpKeys, wal: Wal, db: Database, target: Path) -> None:
    fresh = _fresh(opkeys)
    calls: list[str] = []
    wal.commit(
        wal.prepare(
            fresh,
            target,
            CANDIDATE,
            intended_outcome=RESPONSE,
            validate=lambda p: calls.append(p.op_key),
        )
    )
    assert calls == [fresh.op_key]
    assert _row(db, fresh.op_key)["state"] == "COMMITTED"


def test_commit_conflicts_on_intervening_write_without_overwrite(
    opkeys: OpKeys, wal: Wal, db: Database, target: Path
) -> None:
    fresh = _fresh(opkeys)
    prepared = wal.prepare(fresh, target, CANDIDATE, intended_outcome=RESPONSE)
    target.write_bytes(b"third-party interloper\n")
    with pytest.raises(ConflictedError) as excinfo:
        wal.commit(prepared)
    assert excinfo.value.code == "conflicted"
    assert target.read_bytes() == b"third-party interloper\n"
    assert _row(db, fresh.op_key)["state"] == "CONFLICTED"
    replay = opkeys.begin(RAW_ID, PAYLOAD)
    assert isinstance(replay, Replay)
    assert replay.terminal_state == "CONFLICTED"


def test_recover_reapplies_from_preimage(
    opkeys: OpKeys, wal: Wal, db: Database, target: Path
) -> None:
    fresh = _fresh(opkeys)
    wal.prepare(fresh, target, CANDIDATE, intended_outcome=RESPONSE)
    pending = opkeys.begin(RAW_ID, PAYLOAD)
    assert isinstance(pending, PendingRecovery)
    outcome = wal.recover(pending.op_key)
    assert outcome.action == "reapplied"
    assert outcome.response == RESPONSE
    assert target.read_bytes() == CANDIDATE
    assert _row(db, fresh.op_key)["state"] == "COMMITTED"


def test_recover_completes_installed_candidate(
    opkeys: OpKeys, wal: Wal, db: Database, target: Path
) -> None:
    fresh = _fresh(opkeys)
    prepared = wal.prepare(fresh, target, CANDIDATE, intended_outcome=RESPONSE)
    prepared.candidate_temp.rename(target)  # simulate crash right after the install rename
    outcome = wal.recover(fresh.op_key)
    assert outcome.action == "completed"
    assert outcome.response == RESPONSE
    assert target.read_bytes() == CANDIDATE
    assert _row(db, fresh.op_key)["state"] == "COMMITTED"


def test_recover_third_hash_marks_conflicted_without_overwrite(
    opkeys: OpKeys, wal: Wal, blobs: BlobStore, db: Database, target: Path
) -> None:
    fresh = _fresh(opkeys)
    prepared = wal.prepare(fresh, target, CANDIDATE, intended_outcome=RESPONSE)
    target.write_bytes(b"someone else's data\n")
    outcome = wal.recover(fresh.op_key)
    assert outcome.action == "conflicted"
    assert target.read_bytes() == b"someone else's data\n"
    assert _row(db, fresh.op_key)["state"] == "CONFLICTED"
    # Preimage and exact attempted candidate stay addressable for conflict resolution.
    assert blobs.get(prepared.candidate_blob) == CANDIDATE
    assert prepared.preimage_blob is not None
    assert blobs.get(prepared.preimage_blob) == INITIAL


def test_committed_retry_replays_recorded_response(opkeys: OpKeys, wal: Wal, target: Path) -> None:
    fresh = _fresh(opkeys)
    wal.commit(wal.prepare(fresh, target, CANDIDATE, intended_outcome=RESPONSE))
    outcome = wal.recover(fresh.op_key)
    assert outcome.action == "replayed"
    assert outcome.response == RESPONSE
    assert outcome.after_hash == sha256_bytes(CANDIDATE)


def test_recover_unknown_op_raises(wal: Wal) -> None:
    with pytest.raises(NotFoundError):
        wal.recover("v1.1.0.k.mac")


def test_recover_all_resolves_every_prepared_op(
    opkeys: OpKeys, wal: Wal, store_root: Path, target: Path
) -> None:
    fresh_a = _fresh(opkeys, "op-a")
    wal.prepare(fresh_a, target, CANDIDATE, intended_outcome="resp-a")
    other = store_root / "data" / "other.txt"
    fresh_b = _fresh(opkeys, "op-b")
    wal.prepare(fresh_b, other, b"other candidate", intended_outcome="resp-b")
    outcomes = wal.recover_all()
    assert {o.op_key: o.action for o in outcomes} == {
        fresh_a.op_key: "reapplied",
        fresh_b.op_key: "reapplied",
    }
    assert target.read_bytes() == CANDIDATE
    assert other.read_bytes() == b"other candidate"
    assert wal.recover_all() == ()


def test_recovery_runs_under_caller_lock(
    opkeys: OpKeys, db: Database, blobs: BlobStore, target: Path
) -> None:
    locks = RecordingLockProvider()
    wal = Wal(db, blobs, lock_provider=locks)
    fresh = _fresh(opkeys)
    wal.prepare(fresh, target, CANDIDATE, intended_outcome=RESPONSE)
    wal.recover(fresh.op_key)
    assert locks.locked == [str(target)]


def test_publish_happy_path_and_replay(
    opkeys: OpKeys, wal: Wal, blobs: BlobStore, db: Database
) -> None:
    bundle_hash = blobs.put(BUNDLE)
    fresh = _fresh(opkeys)
    outcome = wal.publish(fresh, "current", None, bundle_hash, intended_outcome=RESPONSE)
    assert outcome.action == "committed"
    assert blobs.read_pointer("current") == bundle_hash
    row = _row(db, fresh.op_key)
    assert row["state"] == "COMMITTED"
    assert row["target_path"] == "pointer:current"
    replay = opkeys.begin(RAW_ID, PAYLOAD)
    assert isinstance(replay, Replay)
    assert replay.response == RESPONSE
    assert replay.commit_hash == bundle_hash


def test_publish_requires_stored_bundle(opkeys: OpKeys, wal: Wal) -> None:
    fresh = _fresh(opkeys)
    with pytest.raises(NotFoundError):
        wal.publish(fresh, "current", None, sha256_bytes(b"never stored"), intended_outcome="r")


def test_publish_stale_expectation_conflicts(
    opkeys: OpKeys, wal: Wal, blobs: BlobStore, db: Database
) -> None:
    bundle_hash = blobs.put(BUNDLE)
    other_hash = blobs.put(b"other bundle")
    blobs.cas_swap("current", None, other_hash)
    fresh = _fresh(opkeys)
    with pytest.raises(ConflictedError):
        wal.publish(fresh, "current", None, bundle_hash, intended_outcome=RESPONSE)
    assert blobs.read_pointer("current") == other_hash  # unchanged
    assert _row(db, fresh.op_key)["state"] == "CONFLICTED"


def test_publish_validate_failure_rolls_back(
    opkeys: OpKeys, wal: Wal, blobs: BlobStore, db: Database
) -> None:
    bundle_hash = blobs.put(BUNDLE)
    fresh = _fresh(opkeys)

    def failing_validate(op: PublishOp) -> None:
        raise ValueError("bundle rejected")

    with pytest.raises(ValueError):
        wal.publish(
            fresh,
            "current",
            None,
            bundle_hash,
            intended_outcome=RESPONSE,
            validate=failing_validate,
        )
    assert blobs.read_pointer("current") is None
    assert _row(db, fresh.op_key)["target_path"] is None  # skeleton restored


@pytest.mark.parametrize(
    ("point", "expected_action"),
    [
        (CRASH_PUBLISH_AFTER_PREPARED, "reapplied"),
        (CRASH_PUBLISH_AFTER_SWAP, "completed"),
        (CRASH_PUBLISH_AFTER_COMMITTED, "replayed"),
    ],
)
def test_publish_recovery_per_crash_point(
    opkeys: OpKeys,
    db: Database,
    blobs: BlobStore,
    point: str,
    expected_action: str,
) -> None:
    bundle_hash = blobs.put(BUNDLE)
    fresh = _fresh(opkeys)
    crashy = Wal(db, blobs, crash_hook=RaisingCrashHook(point))
    with pytest.raises(_Crash):
        crashy.publish(fresh, "current", None, bundle_hash, intended_outcome=RESPONSE)
    locks = RecordingLockProvider()
    wal = Wal(db, blobs, lock_provider=locks)
    outcome = wal.recover(fresh.op_key)
    assert outcome.action == expected_action
    assert outcome.response == RESPONSE
    assert blobs.read_pointer("current") == bundle_hash
    assert _row(db, fresh.op_key)["state"] == "COMMITTED"
    if expected_action != "replayed":
        assert locks.locked == ["pointer:current"]


def test_publish_recovery_third_pointer_value_conflicts(
    opkeys: OpKeys, db: Database, blobs: BlobStore
) -> None:
    bundle_hash = blobs.put(BUNDLE)
    third_hash = blobs.put(b"third bundle")
    fresh = _fresh(opkeys)
    crashy = Wal(db, blobs, crash_hook=RaisingCrashHook(CRASH_PUBLISH_AFTER_PREPARED))
    with pytest.raises(_Crash):
        crashy.publish(fresh, "current", None, bundle_hash, intended_outcome=RESPONSE)
    blobs.cas_swap("current", None, third_hash)  # someone else published meanwhile
    wal = Wal(db, blobs)
    outcome = wal.recover(fresh.op_key)
    assert outcome.action == "conflicted"
    assert blobs.read_pointer("current") == third_hash  # never overwritten


@settings(max_examples=25, deadline=None)
@given(
    point=st.sampled_from(FILE_CRASH_POINTS),
    candidate=st.binary(min_size=0, max_size=128),
    initial=st.one_of(st.none(), st.binary(max_size=128)),
)
def test_property_recovery_outcome_identity_across_crash_points(
    tmp_path_factory: pytest.TempPathFactory,
    point: str,
    candidate: bytes,
    initial: bytes | None,
) -> None:
    """Whatever the crash point, recovery(+retry) ends in the identical final state."""
    root = tmp_path_factory.mktemp("walprop")
    keyring = Keyring.create(root)
    with Database.connect(root / "state.db") as db:
        blobs = BlobStore(root, db)
        opkeys = OpKeys(db, keyring)
        target = root / "data" / "t.txt"
        target.parent.mkdir()
        if initial is not None:
            target.write_bytes(initial)
        fresh = opkeys.begin("raw-prop", PAYLOAD)
        assert isinstance(fresh, Fresh)
        crashy = Wal(db, blobs, crash_hook=RaisingCrashHook(point))
        with pytest.raises(_Crash):
            crashy.commit(crashy.prepare(fresh, target, candidate, intended_outcome="resp"))
        wal = Wal(db, blobs)
        wal.recover_all()
        outcome: object = opkeys.begin("raw-prop", PAYLOAD)
        if isinstance(outcome, Fresh):  # skeleton was aborted; retry executes fresh
            wal.commit(wal.prepare(outcome, target, candidate, intended_outcome="resp"))
            outcome = opkeys.begin("raw-prop", PAYLOAD)
        assert isinstance(outcome, Replay)
        assert outcome.terminal_state == "COMMITTED"
        assert outcome.response == "resp"
        assert outcome.commit_hash == sha256_bytes(candidate)
        assert target.read_bytes() == candidate
        leftovers = [p for p in target.parent.iterdir() if p.name.startswith(".")]
        assert leftovers == []


# --- subprocess crash injection -------------------------------------------------------------

WAL_OP_SCRIPT = """
from pathlib import Path
from opstore.blobs import BlobStore
from opstore.db import Database
from opstore.keyring import Keyring
from opstore.opkeys import Fresh, OpKeys
from opstore.types import EnvCrashHook
from opstore.wal import Wal

root = Path({root!r})
with Database.connect(root / "state.db") as db:
    keyring = Keyring.open(root)
    blobs = BlobStore(root, db)
    opkeys = OpKeys(db, keyring)
    wal = Wal(db, blobs, crash_hook=EnvCrashHook())
    outcome = opkeys.begin({raw_id!r}, {payload_hash!r}, ts={ts!r})
    assert isinstance(outcome, Fresh), outcome
    prepared = wal.prepare(outcome, root / "data" / "target.txt", {candidate!r},
                           intended_outcome={response!r})
    wal.commit(prepared)
"""

PUBLISH_SCRIPT = """
from pathlib import Path
from opstore.blobs import BlobStore
from opstore.db import Database
from opstore.keyring import Keyring
from opstore.opkeys import Fresh, OpKeys
from opstore.types import EnvCrashHook
from opstore.wal import Wal

root = Path({root!r})
with Database.connect(root / "state.db") as db:
    keyring = Keyring.open(root)
    blobs = BlobStore(root, db)
    opkeys = OpKeys(db, keyring)
    wal = Wal(db, blobs, crash_hook=EnvCrashHook())
    bundle_hash = blobs.put({bundle!r})
    outcome = opkeys.begin({raw_id!r}, {payload_hash!r}, ts={ts!r})
    assert isinstance(outcome, Fresh), outcome
    wal.publish(outcome, "current", None, bundle_hash, intended_outcome={response!r})
"""


def _init_root(base: Path, name: str, keys_from: Path | None) -> Path:
    root = base / name
    root.mkdir()
    if keys_from is None:
        Keyring.create(root)
    else:
        shutil.copytree(keys_from / "keys", root / "keys")
    data = root / "data"
    data.mkdir()
    (data / "target.txt").write_bytes(INITIAL)
    return root


def _snapshot(root: Path, raw_id: str) -> dict[str, object]:
    """Comparable durable state: target bytes, pointer, and the operation row."""
    target = root / "data" / "target.txt"
    snap: dict[str, object] = {
        "target": target.read_bytes() if target.exists() else None,
        "temps": sorted(p.name for p in target.parent.iterdir() if p.name.startswith(".")),
    }
    with Database.connect(root / "state.db") as db:
        row = db.conn.execute(
            "SELECT op_key, key_id, ts, payload_hash, state, target_path, before_hash, "
            "after_hash, preimage_blob, candidate_blob, intended_outcome, response "
            "FROM operations WHERE raw_id = ?",
            (raw_id,),
        ).fetchone()
        assert row is not None
        row_dict = dict(zip(row.keys(), tuple(row), strict=True))
        # Roots differ between the baseline and crashed runs; compare relative paths.
        target_path = row_dict["target_path"]
        if isinstance(target_path, str) and target_path.startswith(str(root)):
            row_dict["target_path"] = str(Path(target_path).relative_to(root))
        snap["row"] = row_dict
        pointer = db.conn.execute(
            "SELECT blob_hash FROM pointers WHERE name = 'current'"
        ).fetchone()
        snap["pointer"] = None if pointer is None else str(pointer["blob_hash"])
    return snap


def _drive_file_recovery(root: Path, ts: float) -> None:
    with Database.connect(root / "state.db") as db:
        keyring = Keyring.open(root)
        blobs = BlobStore(root, db)
        opkeys = OpKeys(db, keyring)
        wal = Wal(db, blobs)
        wal.recover_all()
        outcome = opkeys.begin(RAW_ID, PAYLOAD, ts=ts)
        if isinstance(outcome, Fresh):
            wal.commit(
                wal.prepare(
                    outcome, root / "data" / "target.txt", CANDIDATE, intended_outcome=RESPONSE
                )
            )
        else:
            assert isinstance(outcome, Replay)


def _drive_publish_recovery(root: Path, ts: float) -> None:
    with Database.connect(root / "state.db") as db:
        keyring = Keyring.open(root)
        blobs = BlobStore(root, db)
        opkeys = OpKeys(db, keyring)
        wal = Wal(db, blobs)
        wal.recover_all()
        outcome = opkeys.begin(RAW_ID, PAYLOAD, ts=ts)
        if isinstance(outcome, Fresh):
            wal.publish(outcome, "current", None, blobs.put(BUNDLE), intended_outcome=RESPONSE)
        else:
            assert isinstance(outcome, Replay)


@pytest.mark.parametrize("point", FILE_CRASH_POINTS)
def test_crash_injection_file_wal_recovers_to_identical_state(
    tmp_path: Path, run_crash_subprocess: CrashRunner, point: str
) -> None:
    ts = time.time()
    baseline = _init_root(tmp_path, "baseline", None)
    crashed = _init_root(tmp_path, "crashed", keys_from=baseline)

    proc = run_crash_subprocess(
        WAL_OP_SCRIPT.format(
            root=str(baseline),
            raw_id=RAW_ID,
            payload_hash=PAYLOAD,
            ts=ts,
            candidate=CANDIDATE,
            response=RESPONSE,
        ),
        crash_point=None,
    )
    assert proc.returncode == 0, proc.stderr

    proc = run_crash_subprocess(
        WAL_OP_SCRIPT.format(
            root=str(crashed),
            raw_id=RAW_ID,
            payload_hash=PAYLOAD,
            ts=ts,
            candidate=CANDIDATE,
            response=RESPONSE,
        ),
        crash_point=point,
    )
    assert proc.returncode == 42, f"{point}: {proc.stderr}"

    _drive_file_recovery(crashed, ts)
    assert _snapshot(crashed, RAW_ID) == _snapshot(baseline, RAW_ID)


@pytest.mark.parametrize("point", PUBLISH_CRASH_POINTS)
def test_crash_injection_publish_recovers_to_identical_state(
    tmp_path: Path, run_crash_subprocess: CrashRunner, point: str
) -> None:
    ts = time.time()
    baseline = _init_root(tmp_path, "baseline", None)
    crashed = _init_root(tmp_path, "crashed", keys_from=baseline)

    proc = run_crash_subprocess(
        PUBLISH_SCRIPT.format(
            root=str(baseline),
            raw_id=RAW_ID,
            payload_hash=PAYLOAD,
            ts=ts,
            bundle=BUNDLE,
            response=RESPONSE,
        ),
        crash_point=None,
    )
    assert proc.returncode == 0, proc.stderr

    proc = run_crash_subprocess(
        PUBLISH_SCRIPT.format(
            root=str(crashed),
            raw_id=RAW_ID,
            payload_hash=PAYLOAD,
            ts=ts,
            bundle=BUNDLE,
            response=RESPONSE,
        ),
        crash_point=point,
    )
    assert proc.returncode == 42, f"{point}: {proc.stderr}"

    _drive_publish_recovery(crashed, ts)
    snap_crashed = _snapshot(crashed, RAW_ID)
    snap_baseline = _snapshot(baseline, RAW_ID)
    assert snap_crashed == snap_baseline
    assert snap_crashed["pointer"] == sha256_bytes(BUNDLE)


def test_crash_subprocess_completes_without_crash_point(
    tmp_path: Path, run_crash_subprocess: CrashRunner
) -> None:
    ts = time.time()
    root = _init_root(tmp_path, "plain", None)
    proc = run_crash_subprocess(
        WAL_OP_SCRIPT.format(
            root=str(root),
            raw_id=RAW_ID,
            payload_hash=PAYLOAD,
            ts=ts,
            candidate=CANDIDATE,
            response=RESPONSE,
        ),
        crash_point=None,
    )
    assert proc.returncode == 0, proc.stderr
    assert (root / "data" / "target.txt").read_bytes() == CANDIDATE


def test_wal_outcome_is_frozen_dataclass() -> None:
    outcome = WalOutcome(op_key="k", action="committed", state=None, response=None, after_hash=None)
    with pytest.raises(AttributeError):
        outcome.response = "x"  # type: ignore[misc]
