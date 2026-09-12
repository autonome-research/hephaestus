# Runtime view

> **Verified against** `49a90c6` on 2026-09-12.
> Sequences traced through the code; state machines read from the modules that
> own them.

arc42 section 6. Six scenarios, chosen because each one shows a rule the static
view cannot.

## 1. A build

```
heph build spacer
  │
  ├─ project store: resolve the part, read the script and globals
  ├─ compute declared parameters and the `hc` projection the part reads
  ├─ probe the sandbox  ──────── fails ──▶ sandbox_denied, nothing runs
  │       (cached only on pass)
  ├─ runner: assemble the job JSON
  │       {part, script, globals_source, part_overrides, project_overrides,
  │        out_dir, origin, mode, imports, import_errors}
  ├─ ExecBackend.execute  ── bwrap ──▶ worker
  │                                      │
  │                                      ├─ split into top-level statements
  │                                      ├─ for each: execute, checkpoint
  │                                      │     (index, line, verbatim text,
  │                                      │      span, bound names)
  │                                      ├─ on failure: error record + last-good BRep
  │                                      └─ on success: compound BRep, geometry
  │                                         index, source map, tag fingerprints
  ├─ runner: collect one JSON result, hash the inputs and the audit trail
  ├─ store: put blobs, pin, link, record artifact kinds
  └─ publication policy: current, preview, or failed
```

**Where each decision lives.** The runner never decides publication. The worker
never touches the store. The backend never decides whether it is trusted. Those
three separations are why a build can be re-run, replayed and audited.

### Current versus preview

A build publishes as `current` only when it used the project's own declared
inputs. Any `--param` or `--global-param` override makes it a **preview**:
stored, addressable and returned, but never current. Preview blobs carry the
`preview` retention class (7 days) rather than `default` (30).

### Staleness

A part is stale when a recorded input no longer hashes to what the build
recorded: the script, the toolchain, the declared parameters, a named import, or
**the projection of `hc` names the part actually read**.

That last one is the subtle one. Hashing all of `globals.py` would make every
part stale whenever anyone touched the shared namespace. Hashing only the names
the part read makes staleness mean what a reader assumes it means.

### Tag descriptor drift

Every tagged topology is fingerprinted at build time and compared against the
prior *successful current* build's fingerprints. Exceeding a threshold produces a
`tag_descriptor_changed` **warning** — a drift heuristic with explicit exact
thresholds, never an identity verdict:

| Topology | Thresholds |
| --- | --- |
| face | centroid displacement > 1.0 mm, normal angle > 5.0°, or relative area delta > 2% |
| edge | midpoint displacement > 1.0 mm, or relative length delta > 2% |
| solid | centroid displacement > 1.0 mm, or relative volume delta > 2% |

Relative delta is `abs(new-old)/max(abs(old), 1e-9)`. With no baseline there is no
warning, and a no-op refactor produces identical descriptors and never warns.

## 2. A check run

Part-scope checks pull the `CHECKS` dict out of an executed part namespace and
evaluate each predicate against a fresh measurement facade.

**A failing or crashing check fails its report entry — it never fails the
build.** A build is a statement about geometry; a check is a statement about
whether that geometry satisfies a requirement. Collapsing them would make a
wrong requirement look like a broken model.

Cross-part checks (`checks/*.py`) execute in a restricted namespace: the
measurement facade, `approx`, and a safe builtin subset. No filesystem, no
import, no introspection surface.

### Check-set generations

Cross-part checks have a lifecycle over opstore primitives:

- a dedicated **exclusive lease** on `check-set-lock`;
- a generation counter, a tree hash, and a lexically-ordered immutable bundle
  behind the `check-set` CAS pointer;
- create and edit are a typed **WAL pair** — the file mutation plus the
  generation publication, compare-and-swapped before `COMMITTED`, under a durable
  intent record.

So recovery after any crash completes **exactly one** generation advance or rolls
wholly back. Changed content is never visible under the prior generation.

A check set that changes mid-capture is `check_set_drift`; a persisted generation
marked invalid fails closed with `invalid_check_generation`.

### Badges

The report layer computes a closed badge set from `passed` and `measured`:

```
("pass", "fail", "error", "not_run")
```

A check whose measurement was cut short badges `error`, never `fail`. **Silence
never reads as a pass.** One function makes the mapping, and both the CLI and the
HTTP route call it, so the e2e can compare browser DOM badges against a
subprocess `heph check --json` and assert byte-parity.

## 3. An agent turn

```
operator prompt
  │
  ├─ HTTP  POST /sessions/{id}/prompt   (no idempotency key — session control)
  ├─ admission: claim a run slot   ── full ──▶ busy
  │       deadline_at persisted NOW; queued time counts
  ├─ supervisor ──▶ sidecar:  session.prompt
  │                              │
  │                              ├─ model turn
  │                              ├─ tool call ──▶ py.tool_dispatch ──┐
  │                              │                                   │
  │   ┌───────────────────────────────────────────────────────────────┘
  │   ├─ py handler POOL (32 workers), never the frame reader
  │   ├─ dispatch: profile gate → object scope → core routing
  │   └─ result or named refusal ──▶ back over the pipe
  │                              │
  │                              ├─ event notifications, streamed
  │                              └─ terminal
  ├─ event pump: per-client bounded queues, progress coalesced
  ├─ terminal ingested in ONE transaction, then terminal.ack
  └─ slot released — only once the ack is durable
```

### Three timeout classes, deliberately different

| Class | Value | Bounds |
| --- | --- | --- |
| `tool_seconds` | 120 | one tool call |
| `turn_seconds` | 600 | one model turn |
| `cad_build_seconds` | 300 | one build |

A turn runs a model round trip plus every tool the model asks for, one of which
may be a build. Bounding a turn by the tool number made the watchdog kill the
**whole sidecar** over latency that was never a fault. That is the failure this
split exists to prevent.

### Handler saturation fails one call, not the pipe

When all 32 workers are busy, a `py.*` request is refused `handler_overloaded`
rather than queued behind the pipe. Failing one tool call is strictly better than
stalling every frame — including the frames that would have delivered the
responses the busy handlers are waiting for.

### The watchdog credits its own delay

Before declaring the child unresponsive, the supervisor adds back the time it
made the child wait (see [the bridge protocol](../04-reference/bridge-protocol.md)).
Without it, a sidecar blocked on a slow `py.tool_dispatch` would be killed for
time the Python side consumed.

## 4. A crash, and what recovery does

### Mid-build

The out dir is fresh per build and nothing has entered the store. The next build
starts clean; the orphaned directory is invisible to reachability.

### Mid-write (the WAL)

Recovery runs under the caller's per-target lock and compares the live hash:
equal to the candidate → complete the commit; equal to the preimage → reapply;
**any third hash → mark `CONFLICTED` without overwriting**.

The recorded response is always the `intended_outcome` fixed at prepare time, so
replay equality holds across crashes, and the outcome is identical regardless of
which of the four crash points fired.

### Mid-run (admission)

Startup occupancy is the **union**, never the sum, of admitted-nonterminal and
terminal-unacknowledged run ids. `startup_reconstruct` repairs admission rows
against persisted terminals *before* reporting available slots.

`recover` applies a fixed precedence:

```
existing terminal > CANCEL_REQUESTED → cancelled
                  > elapsed deadline → timed_out
                  > confirmed owner loss → interrupted
```

At most one terminal is ever synthesized per run.

### Sidecar crash

In-flight calls fail with the structured `PROCESS_DOWN`. The recovery hook runs
**before** anything is respawned, because recoverable runs go to their
coordinators before terminal synthesis. Only then is a replacement spawned,
through the same start path, so the spawn hook replays `runtime.configure`.

Respawn is bounded: 3 attempts, backoff 0.5 s doubling to a 5 s cap, and a child
surviving 30 s resets the counter. A crash *loop* exhausts the budget and leaves
the supervisor **durably dead** with an error naming the attempt count, rather
than thrashing forever.

## 5. A bounded geometric operation

Five operations run a child process under a wall clock through **one** shared
supervision helper. Each must distinguish two facts, because the remedies differ:
more time cures a slow pass and cures nothing about a crashed one.

Every bounded refusal carries what was already measured, plus a list naming which
halves were lost. `lost` and `completed` **partition** the same vocabulary: a
direction that reported is in one and absent from the other, never in both and
never in neither.

The current state of ceiling-versus-death per operation, including the two that
still conflate them, is in [the refusal vocabulary](../04-reference/refusal-vocabulary.md).

## 6. Garbage collection

```
collect(dry_run=False)
  │
  ├─ reachability = pins ∪ protected roots, transitive over links
  ├─ candidates = unreachable blobs older than their retention horizon
  └─ per candidate:
        exclusive deletion lease
          └─ RECHECK reachability          ← the point of the whole sequence
               └─ unlink file
                    └─ delete accounting row
                         └─ release
```

The recheck after taking the lease is what makes this safe: reachability can
change between selection and deletion.

A reader holding a **shared** lease on a ref blocks the unlink, and a reader
arriving after deletion observes `artifact_expired` — **never partial bytes**.
That is enforced by evaluating the `ref_exists` oracle inside the same
`BEGIN IMMEDIATE` transaction that inserts the reader's lease row.

Lease expiry is **liveness-checked**: a lease past its TTL is reclaimed only when
its owner is confirmed dead. A live owner is never reclaimed, however stale its
heartbeat.

A soft quota guards admission rather than deletion: if reachable bytes alone
exceed the quota, new artifact-producing work fails **before** execution.
**Nothing protected is ever deleted.**

## Related

- The state machines in full: [data model](../04-reference/data-model.md).
- The wire these sequences cross: [bridge protocol](../04-reference/bridge-protocol.md).
