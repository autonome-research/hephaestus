# Crosscutting concepts

> **Verified against** `16f9613` on 2026-09-12.
> Each concept below is asserted somewhere in the test suite; the assertion
> mechanism is named with the concept.

arc42 section 8. These are the rules that appear in every subsystem. Learning
them once explains a great deal of code that would otherwise look arbitrary.

## 1. Evidence or a named refusal — never a plausible answer

The founding rule. An operation that cannot produce evidence returns a **named
reason**; a caller dispatches on the name.

Its three corollaries, each of which has been violated at some point and fixed:

- **A verdict is not a refusal.** The solver has 12 verdict spellings and 34
  refusal names, and the sets are disjoint — a killed solve decided nothing.
- **A ceiling is not a death.** More time cures a slow pass and cures nothing
  about a crashed one, so the two must be separately named.
- **Silence is not a pass.** A check that never ran badges `not_run`, and a
  measurement that could not be taken badges `error`, never `fail`.

See [the refusal vocabulary](../04-reference/refusal-vocabulary.md).

## 2. Closed vocabularies, asserted as data

Wherever a surface is a set, the set is **data in the code**, and a drift test
asserts the live surface *is* that data — in both directions.

| Surface | The data | The assertion |
| --- | --- | --- |
| HTTP routes | `ROUTE_TABLE`, 56 rows | the served app equals the table, across both transports |
| routes named but not served | `UNSERVED_SPEC_ROUTES`, 3 | the gap is a fact in the code |
| bridge methods | 4 frozen sets | each side may originate only what it declares |
| event kinds | `EVENT_KINDS`, 10 | the socket emits the public vocabulary only |
| socket control frames | `CONTROL_FRAME_KEYS`, 2 | anything else closes `1008` |
| agent tools | `TOOLS_BY_NAME`, 57 | generated artifacts drift-tested against it |
| bridge limits | 27 leaves in one JSON file | a census test, **both directions** |
| check badges | 4 | one mapping function, two callers |

The both-directions part is what catches drift. A test that only asserts "every
declared thing is tested" passes forever after a key is deleted. The census test
also asserts that **every boundary test names a limit that still exists**.

## 3. One implementation per behaviour

Where two surfaces must agree, they call one function.

- `heph check --json` and `GET /parts/{part}/checks` serialize through **the same
  serializer**, so the e2e compares browser DOM badges against a subprocess
  `heph check --json` and asserts byte-parity on the canonical JSON.
- The `serve.json` record and its reader live in one module that both
  `heph serve --web` and `heph agent` import — `heph agent` may not import the
  web client API to read a file the two verbs share.
- `bounded_pass.py` is the one subprocess-supervision helper the five bounded
  operations share.
- The workspace API prefix is one constant read by the server that serves it and
  the client-mode CLI that calls it.

The rule exists because a second implementation of a behaviour is a second
implementation of its bugs, and the copy in the friendlier place is the one people
read.

## 4. No number is declared twice

Every numeric bound on the bridge is a leaf in `schemas/bridge_limits.json`, read
by `agent_bridge/limits.py` on the Python side and `agent/src/limits.ts` on the
TypeScript side. The file's own preamble forbids duplicating a limit literal in
code on either side.

The file is staged into the wheel, so an installed package resolves it without
the repository:

```
$HEPHAESTUS_BRIDGE_LIMITS  →  packaged copy  →  walk up to schemas/
```

The `contract` package carries its **own** staged copy rather than importing
`hephaestus.core` for one, because it declares no dependencies. Before that
staging existed, a wheel failed on `import hephaestus.contract`: the repo walk-up
climbed out of `site-packages` and found nothing.

The numbers that are *not* in that file are named as such — `MAX_REPAIR_ROUNDS`,
`MAX_PARTS`, the engine ceilings and their environment overrides. See
[limits and configuration](../04-reference/limits-and-configuration.md).

## 5. Untrusted content, and the two classes of it

Registry content is untrusted, and the two classes are handled differently
because the threat differs.

**Contextual content** — skills markdown, materials notes — never becomes an
ambient extension or a privileged skill. It reaches the model only as a tool
result wrapped in provenance delimiters, under a **dual** text cap (bytes *and*
lines), with absolute snapshot-bound byte cursors on any truncation, so a page is
never silently misleading.

**Executable content** — parts-store generators, DFM predicates — is a part
script with **no additional capabilities**. It runs under the same backend and
the same injected namespace as a part script, with `origin: "registry"` so the
unsafe local backend refuses it.

Registries are pinned in `hephaestus.toml` by a **Merkle digest over the tree**.
`heph registry update` is the only re-pin path; nothing re-pins implicitly, and a
tree whose bytes no longer hash to the pin refuses to load with
`registry_integrity`.

## 6. Content addressing and provenance

Everything published is a blob named by its hash. A ref is
`artifact:<kind>:sha256:<hex>`, and the kind is verified against
`tp_artifact_kinds` rather than believed from the caller's string.

Immutability is what makes provenance work: publishing a newer build **mints new
bundles and never mutates an existing one**, so an old selection bundle keeps
resolving to its original source build, and a pinned artifact keeps resolving
after a newer build lands.

Findings are artifact-bound. A DFM finding carries the `source_artifact_ref` it
was measured against and descriptors that address topology **inside those exact
bytes**, never a mutable mask id.

## 7. Idempotency, three layers, one vocabulary

| Layer | Key | Replay |
| --- | --- | --- |
| opstore opkeys | HMAC-bound `v1.<ts>.<key_id>.<mac>` | the recorded outcome |
| REST | `Idempotency-Key`, UUIDv7, scoped by route identity | the stored body, **byte-for-byte** |
| the tool surface | the trusted invocation id | the recorded outcome |

They do not share a shape, and that is deliberate: a REST replay is the same
operator client re-sending its own committed call, while a bridge retry is a
*model* being told a live hash it does not hold. So two tool families resolve a
retry to a **discriminated result** — `conflict` with the live hash,
`already_exists` — rather than a replay.

They do share a vocabulary. `key_payload_mismatch` means the same thing at every
layer, and the export path deliberately raises the same string from both of its
two key layers.

## 8. Fail closed, and prove rather than trust

- The keyring is opened fail-closed and **never regenerated**, even (especially)
  when `state.db` exists.
- The sandbox is proven **by running escape probes**; a version string is never
  trusted as evidence. Only passing probes are cached; failures are re-probed so
  installing bwrap later is picked up.
- An unknown frame version fails closed.
- A persisted check generation marked invalid fails closed.
- `secure_backend` **never** falls back to the unsafe backend.

## 9. Liveness is checked, not assumed

Owner identity is `(pid, pid_start_ns)`. A lease past its TTL is reclaimed only
once its owner is **confirmed dead**; a live owner is never reclaimed, however
stale its heartbeat.

Where `/proc` is unavailable the start time is `0` and liveness degrades to
pid-existence — stated in the type's own docstring rather than assumed away.

## 10. Refusal messages are wire messages

Every engine message is now a message a client may see. Two consequences the code
enforces:

- **A refusal names what the caller sent**, and the condition and its window —
  never a composed internal identifier. Correlation belongs in the log, and the
  identifier the caller holds is attached by the layer that knows it.
- **An unexpected exception returns a fixed message and an incident id.** The
  traceback goes to the server log; nothing of the exception text reaches the
  client.

## 11. The client derives nothing

The browser renders facts it was given. A `<Fact>` carries `data-source` naming
the **HTTP response field**, and a lint rejects computed sources, derived values
and forged attributions.

Nothing transforms a response on the way in either: a `select` that reshaped a
document would be the client deriving a fact one layer below the panel that
renders it.

## 12. Tests assert mechanisms, not wall clocks

A recurring choice, worth stating because it looks like under-testing:

- CLI startup cost is asserted as a **module-name property in a fresh
  subprocess**, not as a wall-clock threshold — a clock assertion would be flaky
  on a loaded machine and would not say what broke.
- `pytest-timeout` is a coarse safety net only. The diagnosable bound is the
  per-test deadline the waiting tests carry themselves, and they **name the lock
  they were waiting on**. Its method is thread-based so it never kills the process
  out from under the subprocess-heavy stage suites.
- Structural audits match what they mean. A check for unguarded shared-connection
  reads that matched `.conn.execute(` missed every call that passed `self._db.conn`
  *into* a helper; matching the **mention** of the shared connection found them.

## 13. Sequencing rules in recovery

Order is part of the contract wherever recovery is involved:

- The recovery hook runs **before** terminal synthesis, always.
- A terminal is durable **before** it is acknowledged.
- The GC rechecks reachability **after** taking the deletion lease.
- `startup_reconstruct` repairs admission rows **before** reporting free slots.
- `claimToken()` runs **before** anything else reads the URL fragment.

Each of these was a bug before it was a rule.

## Related

- Why each was chosen: [decisions](decisions.md).
- What is still open: [known open issues](../06-operations/known-open-issues.md).
