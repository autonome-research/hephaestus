# Quality requirements and risks

> **Verified against** `3af69da` on 2026-09-12.
> Test inventory from `find … -name 'test_*.py' | wc -l` = 370 Python test files
> (opstore 11, core 85, server 88, contract 2, staged gates 183), plus 77 web
> unit files and 44 e2e files. Scoring rules read from
> `bench/src/hephaestus/bench/scoring.py`.

arc42 sections 10 and 11.

## Quality tree

```
evidential integrity ── never present an unmeasured value as a measurement
  ├─ refusals are named and dispatched on
  ├─ verdicts and refusals are disjoint
  ├─ a ceiling is distinguishable from a death
  └─ silence never reads as a pass

durability ────────── a crash never loses or corrupts recorded work
  ├─ recovery is identical regardless of crash point
  ├─ exactly one terminal per run
  ├─ fail-closed keyring
  └─ no partial read of a collected artifact

reproducibility ───── the same inputs give the same geometry
  ├─ content addressing everywhere
  ├─ hashed build inputs, including the `hc` projection actually read
  ├─ a fixed sandbox environment
  └─ goldens compared under a pinned image

agent effectiveness ─ a model can actually finish a task
  └─ a scored benchmark with a statistical gate
```

Performance is a **constraint**, not a goal. Where the two conflict the
evidential property wins and the cost is stated — the synchronous render frame
and `preserveDrawingBuffer` are both in that category.

## How each quality goal is measured

### Evidential integrity

| Property | Mechanism |
| --- | --- |
| refusals are named | 87 HTTP reasons mapped to statuses; 39 CAD-op reasons; 13 registry reasons |
| verdicts ≠ refusals | the sets are intersected in a test; the intersection is empty |
| ceiling ≠ death | per-operation reason pairs; **two operations still conflate them** (see [known open issues](../06-operations/known-open-issues.md)) |
| silence ≠ pass | a closed 4-badge set from one mapping function, two callers, byte-parity asserted by the e2e |
| the client derives nothing | an eslint rule, error-level, plus DOM-versus-JSON comparison in the e2e |

### Durability

Tested by **injecting crashes**, not by hoping. Every documented crash point is a
named hook the suite fires at, and the assertion is that the end state is
identical regardless of which fired:

```
after_blob_fsync   after_prepared   after_install   after_dir_fsync   after_committed
publish.after_prepared   publish.after_swap   publish.after_committed
blobs.put.after_file_fsync   blobs.put.after_rename
blobs.put.after_dir_fsync    blobs.put.after_db_insert
leases.acquire.after_commit
gc.collect.after_lease   gc.collect.after_recheck
gc.collect.after_unlink  gc.collect.after_row_delete
admission.after_admit    admission.after_suspend
admission.after_terminal_insert   admission.after_ack
```

Twenty-one named points, injected through `CrashHook`; `EnvCrashHook` reads
`OPSTORE_CRASH_POINT`, and the production default is a no-op.

A fake `Clock` moves time without sleeping, and a fake `Liveness` decides whether
an owner is dead — without which lease reclamation could only be tested by
killing real processes.

### Reproducibility

Two CI jobs run under a **pinned image**: `render goldens` and
`stage12 measurements`. A render or a measurement compared against a golden is
only meaningful against a fixed rasterizer and a fixed numeric stack.

The sandbox contributes a fixed environment: `--clearenv` with `PATH`,
`HOME=/tmp`, `TMPDIR`, `LANG`, `PYTHONDONTWRITEBYTECODE`. There is deliberately
**no `PYTHONHASHSEED` override** — determinism relies on the default hash
randomization being irrelevant to geometry, which the determinism suites check
rather than assume.

### Agent effectiveness

The benchmark is a scored gate, and the statistic is chosen so **tiny-n luck
cannot pass a stage**. It is not the raw pass fraction; it is the one-sided lower
90% Wilson bound of the aggregate pass rate:

```
lower = [p + z²/(2n) − z·√(p(1−p)/n + z²/(4n²))] / (1 + z²/n)      z ≈ 1.281552
```

| Gate | Threshold | Corpus |
| --- | --- | --- |
| G2 | 0.60 | corpus v0, 8 tasks × ≥ 3 seeds (n ≥ 24), plus `repair-fillet` at 3/3 |
| G6 | 0.70 | corpus v1, the same 8 plus 4 Stage 6 additions, 12 tasks × ≥ 3 seeds (n ≥ 36) |

Three rules keep the number honest:

- **Thresholds are tunable upward only.**
- **Which threshold applies is read off the corpus the archive actually covers**,
  not configured. A v0 archive keeps being scored against the bound it was
  measured under, and a v1 run cannot be scored against the easier one.
- **The two corpus splits are scored separately and never averaged.** The
  headline numbers are the prose split alone, because that is the split the
  baseline was measured on. The seeded split carries **no threshold** and is
  baselined on first measurement.

The leaderboard generator is held to three properties, and the first is the one
that matters: **it reads, it never scores.** Every number on the page is copied
from an artifact `heph bench score` already wrote. A leaderboard that re-derived
statistics would be a second scorer, and a second scorer eventually differs from
the first. It is also deterministic — same artifacts in, byte-identical page out
— which is what makes `--check` mean something in CI.

## The test system

| Suite | Files | What it covers |
| --- | --- | --- |
| `opstore/tests` | 11 | durability, with crash injection |
| `core/tests` | 85 | the engine |
| `server/tests` | 88 | HTTP, MCP, bridge, dispatch (sharded 3 ways in CI) |
| `contract/tests` | 2 | the declaration and its generated artifacts |
| `tests/stage*` | 183 | the staged gate clauses, 25 stage directories |
| `web/test` | 77 | vitest |
| `web/e2e` | 44 | Playwright, three configurations |
| `agent/test` | — | the sidecar's own suite |

A **gate clause is a testable sentence**, which is why the stage suites are
organised by gate rather than by module: the question they answer is "is this
clause true", and a clause usually crosses three modules.

### Two deliberate testing choices

**Wall clocks are not assertions.** CLI startup cost is asserted as a module-name
property in a fresh subprocess, not as a time threshold: a clock assertion would
be flaky on a loaded machine and would not say what broke.

**`pytest-timeout` is a coarse safety net only.** The diagnosable bound is the
per-test deadline the waiting tests carry themselves, and those tests **name the
lock they were waiting on**. The plugin exists so a wait nobody bounded dies with
a test name attached instead of as a job timeout, and its method is thread-based
so it never kills the process out from under the subprocess-heavy stage suites.

## Risks

Recorded honestly. Each is a real exposure, not a theoretical one.

### R1 — Apparent flakiness hiding real defects

**Severity: high. Realised, repeatedly.**

A red CI run that passes on retry reads as flake. In this repository, a
concentrated pass through nine such reds found **nine real defects**: a turn
bounded by the tool budget so the watchdog killed the whole sidecar; an admission
slot leak from a coordinator raising and a branch outliving its workflow; fifteen
unguarded shared-connection reads across six modules; a scroll handler treating
every scroll event as operator input.

**Mitigation.** Every red is chased to a root cause before it is retried. That is
policy, and it is the single highest-yield practice here.

### R2 — A structural check that does not match what it means

**Severity: high. Realised.**

A check for unguarded shared-connection reads matched `.conn.execute(` and passed
while `opstore`'s own admission module passed `self._db.conn` **into** helpers —
invisible to the pattern. Matching the *mention* of the shared connection found
them.

**Mitigation.** A structural audit must match the concept, not one spelling of
it, and the audit should be tested against a known violation.

### R3 — A stale staged sidecar

**Severity: medium. Realised.**

After an `agent/` edit or a `git pull`, the staged bundle is older than the
source and the symptom is remote: `session.model.get: method not found` in an
e2e run.

**Mitigation.** The freshness guard behind `HEPHAESTUS_SKIP_SIDECAR_BUILD=1`
refuses a stale stage rather than running one, which converts a confusing wire
error into a named refusal. Re-bundle, re-stage, re-record.

### R4 — Environment differences read as failures

**Severity: medium. Realised.**

The stage-13C determinism suite needs the machine on AC power: on battery the CPU
drops to about 1 GHz and a parameter solve takes ~244 s against a 60 s ceiling.
Nothing is wrong with the code.

**Mitigation.** The 60 s solve ceiling is a **production** bound, and a suite that
needs longer declares its own budget rather than inheriting it — the ceiling is
not what that suite is testing. When a check fails, the runbook's three readings
apply: the claim is wrong, the code is wrong, or the environment is wrong.

### R5 — Documentation that is believed and false

**Severity: medium. Realised, three times while this set was written.**

A helper's own docstring said it read the kernel's process file when it forked a
process listing; a commit message repeated the claim; a subsystem summary said an
API exported 57 names when it exports 61.

**Mitigation.** The house rule and the stamps. `docs_check.py` catches dangling
links, paths and section references, and **cannot catch a false sentence** — which
is why the verification procedure exists. See
[the verification runbook](../06-operations/verification-runbook.md).

### R6 — Two bounded operations still conflate a ceiling with a death

**Severity: medium. Open.**

`scan` and `mesh_sew` compute a differentiated message but raise the same reason,
so a machine reading `reason` cannot tell a crash from a ceiling there. Tracked in
[known open issues](../06-operations/known-open-issues.md).

### R7 — Secure execution is Linux-only

**Severity: medium. Accepted, by design in v0.1.**

Without bubblewrap there is no secure backend and script execution refuses by
name. macOS therefore cannot build a part.

**Mitigation.** Release lane (d) asserts the named refusal rather than skipping,
so the property is tested rather than assumed.

### R8 — Declared surfaces with no producer

**Severity: low. Known and recorded.**

Delegation declares seven rejection reasons and produces five. `queue_full` names
a prompt queue that no longer exists; `session_busy` has no producer on this
runtime.

**Mitigation.** Both are recorded as such in the code rather than quietly left to
look live — an unreachable reason that looks reachable is a worse defect than a
missing one.

### R9 — Unverified artifact kinds

**Severity: low. Bounded and stated.**

Blobs published before `tp_artifact_kinds` existed have no rows and are reported
as the empty set, which readers must treat as *unverified*.

**Mitigation.** The two wrong answers — "no kind matches" and "any kind matches"
— are both refused by the module; the caller decides.

### R10 — Not published

**Severity: low. Intentional.**

There is no PyPI release and no GitHub release, so every user builds from a
clone. `scripts/bootstrap.sh --check` runs in CI so that path cannot rot
unnoticed.

## Related

- The current open register: [known open issues](../06-operations/known-open-issues.md).
- How a claim gets checked: [verification runbook](../06-operations/verification-runbook.md).
