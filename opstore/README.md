# opstore

A generic durability substrate over SQLite plus the filesystem. It owns
operation-key verification and tombstones, a generic file-mutation WAL with
crash recovery, content-addressed blob publication with named CAS pointers,
cross-process shared/exclusive leases with liveness-checked expiry, durable
run admission with terminal acknowledgment and suspension, and reachability
GC with deletion leases and quota accounting.

opstore is **stdlib-only** and carries **no domain policy**: it never decides
what a "current build" or "authorized artifact" is. Payload validation and
publication policy live in the caller (for Hephaestus: `core/project_store`),
attached through the hooks opstore exposes (`validate` callables, protected
roots, purge hooks, lock providers).

## Store layout

One `OpStore` owns a root directory:

```
<root>/
├── state.db      SQLite (WAL journal mode, busy_timeout=5000, foreign_keys=ON)
├── keys/         HMAC keyring, one JSON file per key, mode 0600
└── blobs/        content-addressed blobs: blobs/sha256/<2>/<hex>
```

`OpStore.create(root)` initializes a fresh store. `OpStore.open(root)` opens an
existing one and is **fail-closed**: if `state.db` exists but the keyring is
missing or corrupt, it raises `keyring_missing`/`keyring_corrupt` and never
silently regenerates keys — the keyring and `state.db` are a single
backup/restore unit. Every module is also usable directly with a `Database`
handle; the facade only wires shared injectables (`Clock`, `Liveness`,
`CrashHook`, `LockProvider`) through the modules.

## Transaction and recovery contract

- **Hashes** are `"sha256:<hex>"` everywhere. Canonical payload hash = sha256
  over canonical JSON (sorted keys, compact separators, UTF-8, no unicode
  normalization).
- **SQLite discipline**: every multi-step transition runs inside a single
  `BEGIN IMMEDIATE` transaction. Cross-process correctness relies on SQLite
  transactions, not in-process locks.
- **fsync discipline**: blob/candidate writes fsync the file and then the
  parent directory; installs are atomic `os.rename` followed by file and
  directory fsync.
- **Idempotency**: every mutation presents a caller-supplied raw operation id.
  `opkeys.begin` normalizes it into an HMAC-bound key with a trusted embedded
  timestamp and returns exactly one of: `Fresh` (execute now), `Replay`
  (return the recorded response, never re-execute), `PendingRecovery` (run
  `wal.recover` first), or a structured error (`key_payload_mismatch`,
  `key_timestamp_skew`, `key_expired`). Committed outcomes older than the
  30-day idempotency window collapse into tombstones retained a further
  7 days; past that horizon the key is `key_expired` without execution.
- **WAL state machine** per mutation: (1) durable preimage + candidate blobs
  and a same-directory candidate temp file, (2) transactional `PREPARED` row
  (optional caller `validate` runs inside that transaction), (3) atomic
  rename + fsyncs, (4) transactional `COMMITTED` row with the recorded
  response. Recovery under the caller's per-target lock compares the live
  file hash: candidate → complete, preimage → reapply, anything else →
  `CONFLICTED` without overwriting. The outcome is identical regardless of
  crash point, and committed retries replay the recorded response.
- **Leases**: a lease past its heartbeat TTL is reclaimable only once its
  owner is confirmed dead (`Liveness`), or via explicit `break_stale` which
  durably records the takeover. GC deletes a blob only under an exclusive
  deletion lease plus a reachability recheck, so readers holding a shared
  lease never observe partial bytes; a ref gone before acquisition is the
  structured `artifact_expired` error.
- **Admission**: slot occupancy is the union of admitted-nonterminal and
  terminal-unacknowledged runs, excluding durable `SUSPENDED_WAIT`. Terminals
  are unique per run, inserted atomically with the caller's projection, and
  release their slot only after a durable acknowledgment. Recovery precedence:
  existing terminal > `CANCEL_REQUESTED` (`cancelled`) > elapsed deadline
  (`timed_out`) > confirmed owner loss (`interrupted`); at most one terminal
  is ever synthesized.
- **Crash injection**: every step above calls `CrashHook.maybe_crash` with a
  documented point name; the test hook exits with code 42 when
  `OPSTORE_CRASH_POINT` names the point, and the suite asserts recovery
  reaches the identical end state from every point.

## Examples

The fences below execute as tests (`tests/stage0a/test_readme_examples.py`).
`ROOT` is a `pathlib.Path` to a fresh empty directory, substituted by the test
runner; replace it with your own store root.

### Create a store, publish a blob behind a CAS pointer

```python
from opstore import OpStore

store = OpStore.create(ROOT)
digest = store.blobs.put(b"bundle bytes")
store.blobs.cas_swap("current", None, digest)  # create: expected absent
assert store.blobs.read_pointer("current") == digest
assert store.blobs.get(digest) == b"bundle bytes"
store.close()
```

### Idempotent WAL mutation with replay

```python
from opstore import Fresh, OpStore, Replay, sha256_canonical_json

store = OpStore.create(ROOT)
payload = {"path": "parts/shelf.py", "content": "WIDTH = 420\n"}
payload_hash = sha256_canonical_json(payload)

fresh = store.opkeys.begin("tool-call-1", payload_hash)
assert isinstance(fresh, Fresh)
outcome = store.wal.execute(
    fresh,
    ROOT / "files" / "shelf.py",
    b"WIDTH = 420\n",
    intended_outcome='{"ok": true}',
)
assert outcome.response == '{"ok": true}'

retry = store.opkeys.begin("tool-call-1", payload_hash)  # same key, same payload
assert isinstance(retry, Replay)  # replayed, not re-executed
assert retry.response == '{"ok": true}'
store.close()
```

### Admission, terminal, acknowledgment

```python
from opstore import OpStore, TerminalState

store = OpStore.create(ROOT)
store.admission.admit("run-1", deadline_at=None)
store.admission.dispatch("run-1")
assert store.admission.active_count() == 1

record = store.admission.insert_terminal(
    "run-1", "terminal-1", TerminalState.COMPLETED, {"artifacts": 2}
)
assert store.admission.active_count() == 1  # terminal not yet acknowledged
store.admission.acknowledge_terminal("run-1", record.terminal_id)
assert store.admission.active_count() == 0  # slot released after durable ack
store.close()
```

### Pins, reachability links, and a GC dry run

```python
from opstore import GcAction, OpStore

store = OpStore.create(ROOT)
manifest = store.blobs.put(b"manifest")
mesh = store.blobs.put(b"mesh")
store.gc.pin(manifest)
store.gc.link(manifest, mesh)  # pinning the manifest also keeps the mesh
assert mesh in store.gc.reachable()

report = store.gc.collect(dry_run=True)
assert report.dry_run
assert all(c.action is not GcAction.COLLECTED for c in report.candidates)
store.close()
```

### Reopen with fail-closed keyring check and startup recovery

```python
from opstore import OpStore, current_owner

store = OpStore.create(ROOT)
lease = store.leases.acquire_shared("some-ref", current_owner(), ttl_s=30.0)
store.leases.release(lease.lease_id)
store.close()

reopened = OpStore.open(ROOT)  # raises keyring_missing/corrupt if invalid
recovery = reopened.recover()  # WAL recover_all + admission reconstruction
assert recovery.wal == ()
assert recovery.admission.available_slots == reopened.config.run_slots
reopened.close()
```

## Quality bar

ruff clean, pyright strict clean, ≥90% line coverage, hypothesis
property/state-machine tests, subprocess crash-injection tests at every named
crash point, and README examples that execute as tests.
