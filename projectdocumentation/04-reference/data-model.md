# Data model and durability

> **Verified against** `3af69da` on 2026-09-12.
> Schema read from `opstore/src/opstore/db.py` (`_SCHEMA_V1`, 10 tables,
> `SCHEMA_VERSION` = 1); extension tables located by grepping `CREATE TABLE`
> across `core/src` and `server/src`; `len(opstore.__all__)` = 61.

Everything Hephaestus records goes through one substrate. `opstore` is a
**generic** durability layer — it knows nothing about CAD — and the engine layers
its own tables on top of the same database.

`opstore` declares **no third-party dependencies**. That is what lets durability
be tested and reasoned about without the CAD kernel present.

## On disk

```
<project>/
  hephaestus.toml       name, units, [params] project-parameter overrides
  globals.py            the shared `hc` namespace
  parts/                one Python script per part
  checks/               cross-part checks
  imports/              admitted external geometry
  references/           operator reference documents and images
  .heph/                gitignored store root  (an opstore)
    state.db            SQLite, WAL journal mode
    blobs/sha256/<first2>/<hex>
    keys/               one JSON file per HMAC key, mode 0600
    journal/            accepted-overwrite preimages
    serve.json          discovery record, mode 0600
    serve.token         per-serve bearer, mode 0600
```

The store root is created on first open and opened **fail-closed** afterwards.

## The database

SQLite with `journal_mode=WAL`, `busy_timeout=5000`, `foreign_keys=ON`. Every
multi-step transition runs inside `BEGIN IMMEDIATE`.

`db.py` owns the **complete** schema — no other opstore module may issue
`CREATE TABLE`. Migrations are a versioned list applied under `BEGIN IMMEDIATE`
with the current version in `meta['schema_version']`.

Cross-process correctness relies on SQLite transactions, not in-process locks.
In-process, threads share one connection and its transactions serialize on a
re-entrant lock.

### The ten core tables

| Table | What it holds |
| --- | --- |
| `operations` | the WAL row per operation key: state `PREPARED`/`COMMITTED`/`CONFLICTED`, payload hash, before/after hashes, target path, preimage and candidate blobs, intended outcome, response |
| `tombstones` | retired operation keys with their terminal state and expiry |
| `pointers` | named compare-and-swap pointers → blob hash |
| `blobs` | hash, size, created-at, retention class |
| `leases` | shared/exclusive leases with owner pid, owner start time, TTL, heartbeat |
| `admissions` | one row per run: state, suspended flag, absolute deadline, terminal id and ack, owner identity |
| `resume_queue` | FIFO of runs waiting to resume |
| `terminals` | exactly one terminal per `(run_id, kind)` with payload and payload hash |
| `pins` | GC roots |
| `links` | reachability edges, transitive |

### Engine extension tables

Layered on the same `state.db`, each `tp_`-prefixed and created `IF NOT EXISTS`
by its owning module:

| Table | Owner | What it records |
| --- | --- | --- |
| `tp_artifact_kinds` | `core/project_store/artifact_kinds.py` | the kind a blob was published under |
| `tp_exports` | `agent_bridge/cad_ops/export_history.py` | the export WAL; written by exactly one module |
| `tp_delegations` | `agent_bridge/delegation.py` | delegated child runs |
| `tp_session_edges` | `agent_bridge/session_edges.py` | session parentage |
| `tp_jobstore`, `tp_jobstore_checkpoints` | `agent_bridge/jobstore.py` | the sidecar's key/value and checkpoint store |
| `http_dfm_last` | `http/runtime.py` | the last DFM result per part |
| `rest_idempotency` | `http/idempotency.py` | the REST recorded-outcome ledger |
| `mcp_idempotency` | `mcp/idempotency.py` | the MCP equivalent |

## Blobs are content-addressed

`put(data)` returns `"sha256:<hex>"` and dedups by content hash. A write goes to
a same-directory temp file which is **fsynced**, atomically renamed into place,
and followed by a **parent-directory fsync** before the accounting row is
committed.

The temp name is unique per writer (pid **plus a random token**, not pid alone):
two in-process puts of the same hash — two concurrent builds of the same part —
must not collide on `O_CREAT|O_EXCL`.

Blob files are deleted only by GC.

## Artifact refs

```
artifact:<kind>:sha256:<hex>
```

The store originally verified only the *hash* half: the kind segment was read
straight out of the caller-supplied string and believed. Because export outputs
live in the same blob store as builds and renders, a ref whose **label** said
`build` and whose **hash** named an export served the export's bytes — so every
refusal written in terms of the kind segment refused a naming convention rather
than a reachability boundary, and relabelling was free.

`tp_artifact_kinds` closes that: one row per `(blob, kind)` recorded **at
publication**, by the publisher, who is the party that knows. A reader resolves
the recorded kinds for a blob and refuses a ref whose label is not among them.

**Why `(blob, kind)` is a set and not a column.** The store dedups by content
hash, so two publications of *identical bytes* under two kinds are one blob. A
single-valued column would have to pick a winner, and the loser — a legitimately
published artifact — would become unservable through its own ref. A set says what
is true. It is also append-only, which is what makes recording idempotent under
the WAL replay every publication path already performs.

**The honest limit, surfaced rather than guessed.** A blob published before the
table existed, or by a path not yet instrumented, has **no** rows. That is
reported as the empty set and a reader must treat it as *unverified* — not as "no
kind matches", which would make every pre-existing artifact unreadable, and not
as "any kind matches", which would be the module lying. The caller decides what
an unverified blob may do.

## The write-ahead log

Every file mutation follows one state machine, with named crash points that tests
inject at:

1. write + fsync the preimage blob, the candidate blob, and a same-directory
   candidate temp file — `after_blob_fsync`
2. record a `PREPARED` row transactionally with the op key, payload hash,
   before/after hashes, target path and **intended outcome**; an optional
   `validate` callable runs inside that transaction — `after_prepared`
3. atomic rename candidate → target, fsync the file and the parent directory —
   `after_install`, `after_dir_fsync`
4. `COMMITTED` plus the recorded response — `after_committed`

### Recovery

`recover(op_key)` (and startup `recover_all()`) runs under the caller-provided
per-target lock and compares the **live hash**:

| Live hash equals | Action |
| --- | --- |
| the candidate | complete the commit |
| the preimage | reapply |
| anything else | mark `CONFLICTED` **without overwriting** |

The recovery outcome is **identical regardless of crash point**, and the recorded
response is always the `intended_outcome` fixed at prepare time, so replay
equality holds across crashes.

A pointer-CAS publication variant runs the same discipline with its own crash
points, and recovery completes the swap, reapplies it, or marks `CONFLICTED` when
the pointer holds a third hash.

## Operation keys

```
v1.<ts>.<key_id>.<mac>
```

`mac` is HMAC-SHA256 over `<raw_id>|<ts>` under the named keyring key; `<ts>` is
the trusted embedded timestamp (`repr` of unix seconds, round-trip exact).

`begin(raw_id, payload_hash, ts=None)` resolves to one of:

| Situation | Outcome |
| --- | --- |
| unknown key inside the freshness window | registers a skeleton `PREPARED` row, returns `Fresh` |
| recognized `COMMITTED`/`CONFLICTED` row, or a live tombstone with the same payload | `Replay` |
| recognized `PREPARED` row | `PendingRecovery` — resolve via `wal.recover(op_key)` first |
| key reuse with a different canonical payload hash | `KeyPayloadMismatchError` |
| first-seen key with a timestamp outside ±`freshness_skew_s` (5 min) | `KeyTimestampSkewError` |
| older than the idempotency window (first seen), or at/past the tombstone horizon (recognized) | `KeyExpiredError`, without execution |

Recognized keys replay through the full window **without** the freshness check.

**Refusal messages name the condition and its window, never the composed
identifier.** `raw_id` reaches this module fully composed — namespace prefix,
principal fingerprint, route template, the caller's own key, ordinal, lane — and
`op_key` additionally carries the keyring key id and the HMAC. Both used to be
formatted into these messages, which was harmless while the messages were for a
log and stopped being so when every engine message became a **wire** message. A
refusal names what the caller sent; correlation belongs in the log, and the
identifier the *caller* holds — its `Idempotency-Key` header — is attached by the
HTTP layer, the only layer that knows it.

## The keyring

One JSON file per key under `<root>/keys/`:
`{key_id, secret_hex, created_at, retired_at|null}`, mode `0600`, created
atomically (same-directory temp + rename + directory fsync).

`Keyring.create(root)` fails if any keys already exist. `Keyring.open(root)`
**fails closed** — `KeyringMissingError` / `KeyringCorruptError` — whenever the
keyring is absent or invalid, and never silently regenerates keys, even
(especially) when `state.db` exists.

`rotate()` creates a new active key; retired keys stay verifiable for at least
`key_retirement_retention_s` (37 days) after retirement, and `purge()` deletes
only keys past that horizon. Verification tries the active key, then unexpired
retired keys.

## Leases

Shared leases coexist. An exclusive lease requires no live shared or exclusive
holder, and any live lease blocks a new exclusive; a conflicting live lease
raises `LeaseHeldError`.

**Expiry is liveness-checked.** A lease past its heartbeat TTL is reclaimed
during a conflicting acquisition **only when `Liveness.is_alive(owner)` is
false**. A live owner is never reclaimed, however stale its heartbeat.
`break_stale` forces takeover of TTL-elapsed leases regardless of liveness and
durably records the takeover under a `meta` key — the fixed schema has no
dedicated audit table.

Acquisition accepts a `ref_exists` oracle evaluated **inside the same
`BEGIN IMMEDIATE` transaction** that inserts the lease row. A ref gone before
acquisition raises `ArtifactExpiredError`, so a reader either holds a lease on a
present ref or gets the structured error — **never a partial read**, because GC
deletes only under an exclusive deletion lease, which the reader's shared lease
blocks.

Owner identity is `OwnerId = (pid, pid_start_ns)`, not pid alone: the default
liveness check combines `os.kill(pid, 0)` with the `/proc/<pid>/stat` start time
so a recycled pid is not mistaken for the owner. Where `/proc` is unavailable,
`pid_start_ns` is `0` and liveness degrades to pid-existence only — stated rather
than assumed away.

## Admission

One row per caller-supplied stable `run_id`. States
`ADMITTED → DISPATCHED → TERMINAL`, plus `CANCEL_REQUESTED` and the durable
`SUSPENDED_WAIT` flag. The absolute `deadline_at` is persisted **at admission**,
so queued time counts against it.

**The slot rule.** Active = rows without a durable terminal **acknowledgment**,
excluding rows durably suspended. A new admission succeeds only while
`active + pending resume reservations < run_slots` (16); otherwise a structured
`busy`. Queued resume requests therefore have **FIFO priority over new
admissions**.

`suspend` releases the parent's slot and reserves the child admission in **one**
transaction, so net occupancy is unchanged. `resume_request` / `resume` reacquire
through the FIFO `resume_queue`.

Terminals are unique per `(run_id, 'terminal')`. `insert_terminal` is idempotent
for the same terminal (id plus payload hash) and rejects a distinct second
terminal with `terminal_conflict`. `terminal_transaction` exposes the insertion
transaction so callers project their own state atomically with it.

`acknowledge_terminal` is durable and idempotent, and the slot is released only
once the ack is durable — a terminal-unacknowledged run keeps occupying.

**Startup occupancy is the union, never the sum**, of admitted-nonterminal and
terminal-unacknowledged run ids; `startup_reconstruct` repairs admission rows
against persisted terminals before reporting available slots.

`recover` applies a fixed precedence:

```
existing terminal  >  CANCEL_REQUESTED → cancelled
                   >  elapsed deadline → timed_out
                   >  confirmed owner loss → interrupted
```

At most one terminal is ever synthesized per run; a crash after insertion or ack
creates no extra terminal.

## Garbage collection

Reachability is `pins` ∪ caller-protected roots (an injected callback),
**transitive over `links`** — pinning A with A→B→C retains B and C.

`collect(dry_run=…)` takes as candidates the unreachable blobs older than their
retention-class horizon (`default` 30 days, `preview` 7 days). For each real
candidate:

```
exclusive deletion lease → fresh reachability RECHECK → unlink file
  → delete accounting row → release
```

The recheck after taking the lease is the point: reachability can change between
selection and deletion. A dry run explains every candidate and deletes nothing;
the report explains each candidate either way.

**Soft quota.** If protected plus pinned (reachable) bytes *alone* exceed
`quota_bytes` (10 GiB), `admission_guard()` raises
`ProtectedQuotaExceededError`, so new artifact-producing work fails **before**
execution. Nothing protected is ever deleted.

Outcome and tombstone horizons run here too: `purge_hooks` — `opkeys.purge` among
them — are invoked by every non-dry `collect`.

Crash points `after_lease`, `after_recheck`, `after_unlink`, `after_row_delete`
all recover by re-`collect()`: the end state (no file, no row, no lease) is
identical regardless of crash point.

## The facade

`OpStore` wires the modules with shared injectables — `Clock`, `Liveness`,
`CrashHook`, `LockProvider` — and each module remains directly usable with a
`Database` handle.

- `OpStore.create(root)` initializes `keys/` and `state.db`; it fails
  `conflicted` if store state already exists, and **never mints a keyring over
  existing state**.
- `OpStore.open(root)` requires existing state and opens the keyring fail-closed.
- `recover()` runs WAL `recover_all()` then admission `startup_reconstruct()`.
- `gc` is wired with `opkeys.purge` as a purge hook, so every non-dry `collect()`
  also enforces the outcome and tombstone horizons.

The injectables are why this is testable: `CrashHook` fires at each named crash
point, `Clock` moves time, and `Liveness` decides whether an owner is dead —
without which lease reclamation could only be tested by killing real processes.

## Related

- The numbers: [limits and configuration](limits-and-configuration.md).
- What refuses and how: [refusal vocabulary](refusal-vocabulary.md).
- Where admission sits at runtime: [runtime view](../05-architecture/runtime-view.md).
