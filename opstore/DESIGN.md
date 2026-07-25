# opstore — Design Contract (Stage 0A)

> **STATUS — historical implementation contract.** This file was the
> implementation-time contract for Stage 0A (`opstore/`) and is kept for the
> reasoning it records. It is **not** normative today: the root documents
> (`architecture.md`, `mission_plan.md`, `script_contract.md`, `tool_schema.md`,
> `verification.md`, `repo_conventions.md`) are. Where this file and a root
> document disagree, the root document wins. Known drift: the Tier 3 corpus
> budgets these stage docs were written against were re-baselined in
> `verification.md` on 2026-07-25.

Normative for every implementation agent. Derived from `architecture.md` §3.5/§5,
`mission_plan.md` Stage 0A/G0A, `verification.md`, `repo_conventions.md`. Where this
file is silent, those documents govern. Do not contradict them.

## Scope and boundary

`opstore` is a **generic** durability substrate over SQLite + the filesystem:
operation-key verification/tombstones, WAL prepare/commit/recovery hooks,
content-addressed blob publication, cross-process leases, durable
admission/terminal acknowledgment and suspension, reachability/GC.

- **Stdlib only.** No third-party runtime dependencies. No imports of build123d,
  OCP, `hephaestus.*`, Node, Pi, thread-phase — CI rejects them (G0A import-graph).
- **No domain policy.** opstore never decides what a "current build" or
  "authorized artifact" is; payload validation and publication policy live in
  `core/project_store` (Stage 0B). opstore exposes hooks/primitives.
- Quality bar: ruff clean, **pyright strict** clean, **≥90% line coverage**,
  property/state-machine tests (hypothesis), subprocess crash-injection tests,
  README examples that execute as tests.

## Package layout

```
opstore/src/opstore/
  __init__.py      public API re-exports (Integration agent ONLY touches this)
  errors.py        typed exceptions + structured status/error codes
  types.py         dataclasses, Protocols (Clock, Liveness, CrashHook), enums
  hashing.py       sha256 content addressing helpers ("sha256:<hex>")
  db.py            connection mgmt, migrations (FULL schema below), transactions
  keyring.py       HMAC keyring under <root>/keys/
  blobs.py         CAS blob store under <root>/blobs/ + named pointers w/ CAS
  opkeys.py        operation keys, idempotency verification, tombstones
  wal.py           generic file-mutation WAL prepare/commit/recovery
  leases.py        shared/exclusive cross-process leases w/ heartbeat liveness
  admission.py     admission rows, run slots, SUSPENDED_WAIT, terminal table+ack
  gc.py            pins, reachability links, quota, GC with deletion leases
opstore/tests/     module tests (test_<module>.py), crash tests, property tests
tests/stage0a/     import-graph boundary test, README-example runner, cross-module
                   integration tests
```

## Core conventions

- **Store root**: `OpStore(root: Path, config: StoreConfig)` owning
  `<root>/state.db`, `<root>/keys/`, `<root>/blobs/`. `OpStore` is a small
  facade in `__init__.py` wiring the modules; each module also usable directly
  with a `Database` handle.
- **Injectables** (in `types.py`), required for horizon/crash/liveness tests:
  - `Clock` protocol: `now() -> float` (unix seconds). Default `SystemClock`.
  - `Liveness` protocol: `is_alive(owner: OwnerId) -> bool`. `OwnerId` =
    `(pid, pid_start_ns)`; default checks `os.kill(pid, 0)` + `/proc/<pid>/stat`
    start time when available.
  - `CrashHook`: `maybe_crash(point: str) -> None`. Default no-op; test impl
    reads env `OPSTORE_CRASH_POINT` and calls `os._exit(42)` at the named point.
    Every WAL/publication/admission step calls it with a documented point name.
- **SQLite discipline**: WAL journal mode, `busy_timeout=5000`,
  `foreign_keys=ON`; every multi-step transition uses `BEGIN IMMEDIATE`.
  Cross-process correctness relies on SQLite transactions, not in-process locks.
- **Hashes**: `"sha256:" + hexdigest` everywhere. Canonical payload hash =
  sha256 over canonical JSON (sorted keys, `separators=(",", ":")`,
  `ensure_ascii=False`, UTF-8). No Unicode normalization.
- **fsync discipline**: blob/candidate writes fsync file then parent directory;
  renames are `os.rename` (atomic, same filesystem) followed by dir fsync.

## Module contracts

### keyring.py
- Keys under `<root>/keys/`: JSON files `{key_id, secret_hex, created_at,
  retired_at|null}`, file mode **0600**, created atomically (temp+rename),
  never committed to git (caller's concern).
- `Keyring.create(root)` — fails if keys exist; `Keyring.open(root)` — **fails
  closed** (`KeyringError`) if state.db exists but keyring is missing/corrupt;
  never silently regenerates.
- `rotate()` creates new active key, retains retired keys for verification
  **≥ 37 days** after retirement (`purge(clock)` enforces).
- `mac(key_id, data) / verify(data, mac_hex) -> key_id | None` using HMAC-SHA256;
  verification tries active then unexpired retired keys.

### opkeys.py — operation keys / idempotency / tombstones
- `OpKey`: caller-supplied raw id + canonical payload hash → normalized internal
  key: `v1.<ts>.<key_id>.<hmac(raw_id|ts)>` with trusted embedded timestamp.
- `begin(raw_id, payload_hash, ts=None)` outcomes (structured, in errors.py):
  - new key → registers row, returns `Fresh` handle;
  - same key + same payload, COMMITTED → `Replay(response)`;
  - same key + same payload, PREPARED → resolve via wal recovery first;
  - same key + **different payload** → `KeyPayloadMismatch` error;
  - key older than **30 days** (window, configurable `StoreConfig.idempotency_window_s`)
    → `KeyExpired` **without execution**;
  - key found only as tombstone + same payload → `Replay` from tombstone
    (terminal state + commit hash only); different payload → mismatch error.
- Outcome GC: completed operation rows older than the window collapse to
  **tombstones** `{key, payload_hash, terminal_state, commit_hash}` retained
  through **window + 7 days**, then deleted; post-horizon presentation of the
  key → `KeyExpired`.
- First-seen keys with embedded ts outside ±5 min of server clock are rejected
  (`KeyTimestampSkew`); recognized keys replay through the full window without
  the freshness check.

### wal.py — generic file-mutation WAL
State machine per operation (rows in `operations`):
1. write+fsync preimage blob, candidate blob, and same-directory candidate temp
   file  [crash points: `after_blob_fsync`]
2. `PREPARED` row recorded transactionally with op key, payload hash,
   before/after hashes, target path, intended outcome  [`after_prepared`]
3. atomic rename candidate→target, fsync file + parent dir  [`after_install`,
   `after_dir_fsync`]
4. `COMMITTED` + response recorded  [`after_committed`]

Recovery (`recover(op_key)` / startup `recover_all()`), under the caller-provided
per-target lock (hook `LockProvider`): live hash == candidate → complete commit;
== preimage → reapply; any third hash → mark `CONFLICTED` **without overwriting**.
Committed retry replays recorded response. Identical outcome regardless of crash
point (property test). Generic hooks let core attach domain validation:
`prepare(..., validate: Callable | None)` runs inside the PREPARED transaction.

Pointer-CAS publication variant for blob bundles (used by build/manifest
publication later): `publish(pointer_name, expected_pointer_hash, bundle_hash)`
under the same PREPARED/COMMITTED discipline; recovery completes or conflicts.

### blobs.py
- `put(bytes) -> "sha256:..."` (dedup, fsync, `<root>/blobs/sha256/<2>/<hex>`),
  `open_stream/get`, `has`, `size`. Blobs deleted **only** by gc.py.
- Named pointers table with `cas_swap(name, expected_hash|None, new_hash)`.

### leases.py
- `acquire_shared(ref, owner, ttl_s)` / `acquire_exclusive(ref, owner, ttl_s)`
  (exclusive requires no live shared/exclusive holders), `heartbeat(lease_id)`,
  `release(lease_id)`.
- Expiry is **liveness-checked**: a lease past its heartbeat TTL is reclaimable
  only after `Liveness.is_alive(owner)` is false, or forced by explicit
  `break_stale(...)` that records the takeover. Deletion races: an exclusive
  deletion lease + reachability recheck happen in gc.py before unlink; readers
  holding a shared lease never observe partial bytes (`artifact_expired`
  structured error when the ref is gone before acquisition).

### admission.py
- Durable admission rows: `run_id` (caller-supplied stable id), states
  `ADMITTED → DISPATCHED → (terminal)`, plus `SUSPENDED_WAIT` flag, and
  `CANCEL_REQUESTED`; absolute `deadline_at` persisted at admission (queued time
  counts).
- **Slot rule**: active = rows without durable terminal **acknowledgment**,
  excluding rows durably in `SUSPENDED_WAIT`. Admission succeeds only when
  active < `config.run_slots` (default **16**); otherwise structured `Busy`.
- `suspend(run_id)` (transactionally reserve a child admission while parent
  suspends — one transaction), `resume_request(run_id)`: suspended parents
  reacquire with **FIFO priority over new admissions** (priority queue table).
- **Terminal table**: unique `(run_id, kind='terminal')`, terminal_id, payload
  hash+json. `insert_terminal` idempotent on run_id; a second distinct terminal
  for the same run is rejected. Terminal insertion + caller's projection run in
  **one transaction** (exposed as a context-managed transaction hook).
- `acknowledge_terminal(run_id, terminal_id)` durable + idempotent, releases the
  slot only after the ack row is durable.
- **Startup reconstruction**: occupancy = **union** of admitted-nonterminal and
  terminal-unacknowledged run ids (never the sum); helper resolves persisted
  terminals/acks, then reports available slots. Recovery precedence helper:
  existing terminal wins; then CANCEL_REQUESTED → `cancelled`; elapsed deadline
  → `timed_out`; confirmed owner loss → `interrupted` (exactly one synthesized
  terminal; crash after insertion/ack creates no extra terminal).

### gc.py
- Tables: `pins(ref)`, `links(from_ref, to_ref)`, `protected` provided by caller
  callback. Reachability = pins ∪ caller-protected roots, **transitive over
  links**.
- `collect(dry_run=...)`: candidates = unreachable blobs/refs older than
  retention (`config.retention_s` default 30 d; caller can tag previews with
  shorter retention 7 d). For each candidate: exclusive deletion lease →
  reachability **recheck** → unlink → release. Dry-run returns an explanation
  report per candidate.
- Soft quota (`config.quota_bytes`, default 10 GiB): if protected+pinned alone
  exceed quota → structured `ProtectedQuotaExceeded`; `admission_guard()` lets
  callers fail new artifact-producing work before execution.
- Tombstone/outcome horizons executed here too (calls into opkeys.purge).

## SQLite schema (single source of truth — db.py owns ALL of it)

```sql
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE operations(
  op_key TEXT PRIMARY KEY, raw_id TEXT NOT NULL, key_id TEXT NOT NULL,
  ts REAL NOT NULL, payload_hash TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('PREPARED','COMMITTED','CONFLICTED')),
  target_path TEXT, before_hash TEXT, after_hash TEXT,
  preimage_blob TEXT, candidate_blob TEXT,
  intended_outcome TEXT, response TEXT,
  created_at REAL NOT NULL, committed_at REAL);
CREATE TABLE tombstones(
  op_key TEXT PRIMARY KEY, payload_hash TEXT NOT NULL,
  terminal_state TEXT NOT NULL, commit_hash TEXT,
  created_at REAL NOT NULL, expires_at REAL NOT NULL);
CREATE TABLE pointers(name TEXT PRIMARY KEY, blob_hash TEXT NOT NULL,
  updated_at REAL NOT NULL);
CREATE TABLE blobs(hash TEXT PRIMARY KEY, size INTEGER NOT NULL,
  created_at REAL NOT NULL, retention_class TEXT NOT NULL DEFAULT 'default');
CREATE TABLE leases(
  lease_id TEXT PRIMARY KEY, ref TEXT NOT NULL,
  mode TEXT NOT NULL CHECK(mode IN ('shared','exclusive')),
  owner_pid INTEGER NOT NULL, owner_start_ns INTEGER NOT NULL,
  ttl_s REAL NOT NULL, heartbeat_at REAL NOT NULL, created_at REAL NOT NULL);
CREATE TABLE admissions(
  run_id TEXT PRIMARY KEY,
  state TEXT NOT NULL CHECK(state IN
    ('ADMITTED','DISPATCHED','CANCEL_REQUESTED','TERMINAL')),
  suspended INTEGER NOT NULL DEFAULT 0,
  deadline_at REAL, admitted_at REAL NOT NULL,
  terminal_id TEXT, terminal_acked_at REAL,
  owner_pid INTEGER, owner_start_ns INTEGER);
CREATE TABLE resume_queue(
  seq INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL UNIQUE,
  requested_at REAL NOT NULL);
CREATE TABLE terminals(
  run_id TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'terminal',
  terminal_id TEXT NOT NULL, payload_hash TEXT NOT NULL, payload TEXT NOT NULL,
  created_at REAL NOT NULL, PRIMARY KEY(run_id, kind));
CREATE TABLE pins(ref TEXT PRIMARY KEY, created_at REAL NOT NULL);
CREATE TABLE links(from_ref TEXT NOT NULL, to_ref TEXT NOT NULL,
  PRIMARY KEY(from_ref, to_ref));
```

Migrations: `meta['schema_version']`; db.py applies versioned migration list.
If a module needs a schema change it MUST be made in db.py (coordinate via the
orchestrator), not ad-hoc `CREATE TABLE` elsewhere.

## Error/status vocabulary (errors.py)

Exceptions carry a stable `code`: `key_expired`, `key_payload_mismatch`,
`key_timestamp_skew`, `keyring_missing`, `keyring_corrupt`, `busy`,
`artifact_expired`, `protected_quota_exceeded`, `conflicted`, `lease_held`,
`lease_expired`, `terminal_conflict`, `not_found`. States: `PREPARED`,
`COMMITTED`, `CONFLICTED`, `ADMITTED`, `DISPATCHED`, `CANCEL_REQUESTED`,
`SUSPENDED_WAIT`, terminals `completed|failed|cancelled|timed_out|interrupted`.

## Test obligations (G0A)

- Per-module unit tests + hypothesis property/state-machine tests (opkeys
  uniqueness/replay/mismatch; WAL crash matrix identical-recovery; lease
  liveness/deletion races; admission slot accounting incl. SUSPENDED_WAIT
  release/priority reacquisition without double counting; GC reachability +
  protected-root quota; tombstone horizons).
- Subprocess crash injection at **every** named crash point (env
  `OPSTORE_CRASH_POINT`), asserting recovery outcome equality.
- Keyring creation/rotation/restore-failure (fail-closed) tests.
- `tests/stage0a/test_import_boundary.py`: walks opstore's import graph and
  asserts no forbidden imports (build123d, OCP, hephaestus, subprocess to
  node/pi/thread-phase).
- `tests/stage0a/test_readme_examples.py`: extracts ```python blocks from
  `opstore/README.md` and executes them (tmpdir substitution allowed via a
  documented `ROOT` placeholder convention).
