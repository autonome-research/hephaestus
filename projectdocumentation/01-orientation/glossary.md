# Glossary

> **Verified against** `49a90c6` on 2026-09-12.
> Each term is defined from the code that uses it, and links to where it is
> specified in full.

arc42 section 12. Terms are defined once here; other documents link rather than
redefine.

## Core vocabulary

**Part** — one Python script under `parts/`, executed statement by statement
against an injected namespace, producing solid geometry. A part name matches
`^[a-z][a-z0-9_]{0,63}$`.

**Project** — a directory containing `hephaestus.toml`, `globals.py`, `parts/`,
`checks/` and the gitignored `.heph/` store.

**`hc`** — the shared namespace declared in `globals.py`, readable from any part.
Staleness hashes **the projection of `hc` names a part actually read**, not the
whole file.

**Injected namespace** — everything in scope inside a part script without an
import: build123d, `math`, `Param`, `p`, `hc`, `part`, `tag`, `approx`. The
injected namespace *is* the API surface.

**`PARAMS`** — a part's declared tunables, read back as `p.<name>`. Each is a
`Param(default, min=…, max=…)`.

**Build** — one execution of a part script producing geometry, published as a
content-addressed artifact.

**Current** — a build that used the project's own declared inputs, and therefore
is what the project says the part *is*.

**Preview** — a build made with a `--param` or `--global-param` override. Stored,
addressable and returned, but never current. Carries the `preview` retention
class (7 days) rather than `default` (30).

**Stale** — a recorded build input no longer hashes to what the build recorded.
`heph part show` reports `stale` and `stale_inputs`. **`heph build --stale` is
narrower**: it rebuilds *consumers* of changed shared inputs (`globals.py`, a
project parameter, a replaced import), not a part whose own script you edited.

**Checkpoint** — the record the worker writes after each top-level statement:
index, line, verbatim text, span, bound names.

## Addressing

**Selector** — how a piece of geometry is addressed inside a part: a label, a
tag, a binding name, or `"<part>/<selector>"` across parts. Tags support `#k` and
`#*`.

**Artifact ref** — `artifact:<kind>:sha256:<hex>`. The kind is verified against
the recorded publication kinds, not believed from the caller's string.

**Addressing error** — a selector that resolved to nothing or ambiguously.
Carries `candidates` and a `reason` of `unresolved` or `ambiguous`. Distinct from
`invalid_part` (not a legal name) and `unknown_part` (a legal name the project
does not have).

## Evidence

**Refusal** — a named reason returned instead of a plausible answer. Callers
dispatch on the name. See [the vocabulary](../04-reference/refusal-vocabulary.md).

**Verdict** — an outcome a solve or a check reached. **Disjoint from refusals**:
a killed solve decided nothing, so `solver_timeout` cannot be spelled as an
outcome.

**Check** — a predicate over measurements, declared in a part's `CHECKS` or in
`checks/*.py`. A failing check **never fails the build**.

**`measured`** — the evidence a check recorded, not a restatement of its verdict.
A measurement that could not be taken writes an error object *inside* `measured`.

**Badge** — the closed four-value report status: `pass`, `fail`, `error`,
`not_run`. Computed by one function with two callers. A check whose measurement
was cut short badges `error`, never `fail`; silence is `not_run`.

**Measurement facade (`m`)** — the object a check receives. `m.bbox`, `m.volume`,
`m.mass`, `m.sealed`, `m.genus`, `m.distance`, `m.clearance`, `m.interference`,
`m.diff`, `m.scan_diff`, `m.at_pose`, `m.sweep`. It is an object, not a callable.

**`approx`** — a comparator, not a two-argument function:
`m.bbox(s)[2] == approx(value, abs=1e-6)`.

**Check-set generation** — the version of the cross-part check set, advanced under
an exclusive lease and a WAL pair so recovery completes exactly one advance or
rolls wholly back.

## Durability

**opstore** — the generic durability substrate: WAL, operation keys,
content-addressed blobs, leases, admission, GC. No third-party dependencies, no
knowledge of CAD.

**Operation key** — `v1.<ts>.<key_id>.<mac>`, HMAC-bound, carrying a trusted
embedded timestamp.

**Crash point** — a named hook (`after_prepared`, `gc.collect.after_recheck`, …)
that tests fire at to prove recovery is identical regardless of where a crash
lands. Twenty-one of them.

**Lease** — a shared or exclusive claim on a ref, with a heartbeat TTL. Expiry is
**liveness-checked**: a stale lease is reclaimed only once its owner is confirmed
dead.

**Owner id** — `(pid, pid_start_ns)`. Not pid alone, so a recycled pid is not
mistaken for a live owner.

**Admission** — the durable run-slot ledger. States `ADMITTED → DISPATCHED →
TERMINAL`, plus `CANCEL_REQUESTED` and a durable suspended flag.

**Terminal** — the single durable end record of a run. Exactly one per run, made
durable **before** it is acknowledged.

**Pin / link** — the GC reachability graph. Pins are roots; links are edges, and
reachability is transitive over them.

**Retention class** — `default` (30 days) or `preview` (7 days). Decides a blob's
collection horizon.

## The agent surface

**Tool** — one of 57 declared operations. Declared as data; schemas and types are
generated.

**Profile** — a session's authorization level: `orchestrator` (57 tools),
`part` (46), `quick_edit` (20), `reviewer` (5). The reviewer's inability to mutate
is a property of the declaration table, not of any prompt.

**Object scope** — a `part` or `quick_edit` session is bound to one normalized
part id; addressing a different part is `scope_denied`.

**Dispatcher** — the single chokepoint every tool call crosses. CLI, HTTP and MCP
all reach it; there is no bypass.

**Sidecar** — the compiled Node process that talks to model providers. Ships
inside `hephaestus-server`, verified against a SHA-256 manifest before every
spawn.

**Bridge** — the framed JSON-RPC channel between the engine and the sidecar.

**Frame** — one UTF-8 JSON object terminated by a single `\n`. Protocol stdout
carries nothing else; logs go to stderr.

**`hv`** — the frame version. An unknown value fails closed.

**`py.*`** — the nine request methods the sidecar originates toward Python.

**Child-wait credit** — the time the supervisor made the child wait, added back to
a pending call's deadline before the watchdog judges the child unresponsive.

**Event pump** — the component that fans sidecar events into bounded per-client
queues and makes terminals durable.

**Droppable** — of an event kind: may be coalesced under backpressure. Only
`progress` is droppable.

**Observer** — a non-durable event client (the browser). Dropped on overflow
(close `4409 resync_required`) rather than cancelling the run.

**Delegation** — an orchestrator handing one part to a child session.

## Execution

**Executor** — the subsystem that runs part scripts. Split into a parent
(`runner`) and a sandboxed child (`worker`).

**Backend** — an `ExecBackend`: `bwrap` (secure) or `unsafe` (local debugging
only, never a default).

**Probe** — the live escape test that establishes the sandbox works, by *running*
it. A version string is never trusted as evidence.

**`sandbox_denied`** — the code returned when there is no proven sandbox. Note
that `sandbox_unavailable:` is a **message prefix**, not a code.

**Origin** — where a script came from. `origin: "registry"` marks untrusted
registry content, which the unsafe backend refuses.

**Tag fingerprint** — a descriptor hash of a tagged topology, compared against the
prior successful current build to produce `tag_descriptor_changed` **warnings**. A
drift heuristic with exact thresholds, never an identity verdict.

## Registries and content

**Registry** — a versioned directory pinned in `hephaestus.toml` by a **Merkle
digest over the tree**. `heph registry update` is the only re-pin path.

**Contextual content** — skills markdown, materials notes. Reaches the model only
as a tool result inside provenance delimiters, under a dual cap (bytes *and*
lines).

**Executable content** — parts-store generators, DFM predicates. A part script
with no additional capabilities.

**DFM** — design for manufacturability. Rule packs run sandboxed against build
artifacts; findings are artifact-bound.

## Solving

**Solve** — `solve_pose` (declared joint parameters) or `propose_placement` (a
rigid transform per declared-free part).

**The solver proposes.** Nothing in it writes a script, writes a parameter,
republishes a transformed artifact, or makes a build current. `solve_pose` writes
nothing at all; `propose_placement` writes exactly one immutable proposal document
that **nothing applies**.

**Proposal** — that document. Read with `heph proposals` / `read_proposals`.

## The web client

**`<Fact>`** — the primitive every displayed number renders through, carrying
`data-source` naming the HTTP response field and `data-value` carrying the value
unformatted.

**Pin authority** — the rule that `artifact_ref` and `pin_mode` change only
through `hold`, `followCurrent` or `observeCurrent`, and that publishing never
advances a held pin.

**Plate** — the server-rendered section PNG, the evidentiary surface,
golden-compared. Distinct from the **live clipping preview**, which never is.

**Band** — a viewport capacity band: `wide` (≥ 1280 px), `medium` (1024–1279),
`narrow` (< 1024). Capacity never resets explicit conversation intent.

## Process

**Gate** — a numbered set of testable clauses. `G2`, `G6`, `G7H` and the staged
gates run as their own CI jobs.

**Gate clause** — one testable sentence. The stage suites are organised by gate
rather than by module because a clause usually crosses three modules.

**Pinned image** — the container image a golden or a measurement was baselined
on. A `pinned_image` test **fails by name off the image rather than skipping**.

**Wilson lower bound** — the benchmark's gate statistic: the one-sided lower 90%
bound of the aggregate pass rate, never the raw fraction, so tiny-n luck cannot
pass a stage.

## Documents in this repository

| Document | What it governs |
| --- | --- |
| `architecture.md` | the system's normative architecture |
| `INTERFACE.md` | the HTTP, web and event surfaces |
| `tool_schema.md` | the agent tool surface |
| `SOLVER.md` | solving and proposals |
| `VALIDATION.md` | the reviewer, requirements, benchmark splits |
| `script_contract.md` | what a part script may do |
| `verification.md` | the verification tiers |
| `PACKAGING.md` | the wheel build |
| `CONTRIBUTING.md` | the working process |

These are **authority**; this documentation set points at them and does not copy
them.
