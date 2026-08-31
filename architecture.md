<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# 00 — Architecture

Status: draft for droid mission. Normative language: MUST / SHOULD / MAY.

## 1. Evidence base

This architecture reverse-engineers the observable behavior of Smith
(smith.arche.co) from a 250 s screen recording, two full part scripts, a
captured build-failure message, and a face-selection interaction. Nothing here
derives from Smith's code, network traffic, or non-public material; where the
evidence ran out we made our own decisions and marked them. Key observations
and the decision each one drives:

| Observation | Decision |
|---|---|
| Script diffs use `Pos(...) * shape`, `align=(Align.CENTER, ...)`, `extrude`, `make_face`, `Polyline`, `fillet`, `Compound(children=[...])`, `.color`, `.label` | The kernel DSL is build123d, used natively. Hephaestus adopts build123d unmodified as the geometry API. |
| Scripts contain no imports; `PARAMS = {"x": Param(5, min=2, max=10)}`, `p.x`, `hc.tab_w`, `part.geometry`, `tag(face, "tread_top")`, `part.feature("tread_top").surface_finish` | Scripts execute in a preamble-injected namespace with a small extension API: bounded params, project-shared constants, a part output object, topology tagging. Specified in `script_contract.md`. |
| Failure message: `[error] Line 46:14 — Failed creating a fillet…`, `Built successfully through line 44`, last-good stats `1 bodies / 1 solids, size [250.0, 200.0, 18.0] mm, volume 868892.28 mm³, sealed=True, genus=0`, hint `inspect_part(name, last_good=true)` | The executor is statement-level incremental with per-statement checkpointing. Errors carry source frames, the last successful statement, last-good metrics including manifold invariants, and the last-good state stays renderable. |
| Tool chips: `Create`, `Edit` (diff), `Build` ("438 faces" / "success"), `Measure Overlap`, `Inspect — rgb\|mask, 2 views` with labeled thumbnails (`iso`, `+X`), `Query Build Snapshot`, `Load Skill`, `Search Store`, `Search Materials`, `Ask question (N)`, `Import` | The agent tool surface. Hephaestus mirrors it in snake_case (the error hint shows the real API is snake_case: `inspect_part`) and extends it. Specified in `tool_schema.md`. |
| Tabs `Files / Script / Results / Scrapyard`; Results = `GEOMETRIES 25` with per-solid visibility; per-part `PROPERTIES` panel; per-part agent tabs each with `v1*`; top bar `Publish · v1* · Rebuild`; URL `/session/{uuid}` | Project = set of parts; one script, one agent context, one dirty-flagged version per part. Hephaestus replaces the session/version model with git (§5). Scrapyard (community sharing) is explicitly deferred. |
| Face click → "Quick edit — 1 face" popover → "Ask a new agent…" | Selection spawns a scoped agent with the selection as context. No parametric direct manipulation anywhere in the product. Hephaestus adopts this and strengthens it with source maps (§4.4). |
| Composer: model selector ("Sol"), DFM toggle, doc attach, screenshot; agent volunteers static FEA; export surface: STEP | Model selection is a UI concern (Hephaestus is model-agnostic at the core). DFM is a mode that loads rule packs. FEA is a pluggable analysis. Export must exceed STEP-only (§4.6). |

## 2. System overview

Six components, strictly layered. Calls within the Python engine are
in-process; the TypeScript agent runtime is an isolated local sidecar reached
through a versioned JSON-RPC-over-stdio bridge. Nothing in a lower layer knows
about a higher one.

```
┌────────────────────────────────────────────────────────┐
│  Clients:  CLI (heph)  ·  MCP clients  ·  Web UI       │
└──────────────▲─────────────────▲───────────────────────┘
               │ stdio/HTTP MCP  │ HTTP + WS
┌──────────────┴─────────────────┴───────────────────────┐
│  server/   Python MCP/HTTP API · events · agent bridge │
└──────────────▲─────────────────┬───────────────────────┘
               │ Python API      │ JSON-RPC/stdio
┌──────────────┴──────────────┐  ▼
│ core/ executor · kernel     │  ┌───────────────────────┐
│ render · checks · CAD store │◄─┤ agent/  TypeScript    │
└──────────────┬──────────────┘  │ Pi sessions + tools    │
               ▼                 │ thread-phase workflows │
┌─────────────────────────────┐  └───────────────────────┘
│ opstore/ WAL · leases · CAS │
│ admission · retention / GC  │
└─────────────────────────────┘
```

The agent sidecar never imports or reimplements geometry logic. Its custom
tools issue typed requests over the bridge; the Python process dispatches
those requests to `core/` and returns text, structured data, and image blocks.
`core/` MUST be importable and fully functional with no server, no agent, no
Node runtime, and no network: `heph build`, `heph render`, `heph check`, and
`heph export` are thin wrappers over it. This is the engine-first invariant
and the mission's Stage 0B; the CAD-independent durability substrate lands
first in Stage 0A.

## 3. core/

### 3.1 Executor

Runs a part script in a sandboxed subprocess with the injected namespace from
`script_contract.md`. Requirements:

- **Statement-level execution.** The script is split into top-level statements
  via `ast`. Statements execute sequentially; after each one the executor
  records a checkpoint: statement index, source span, names bound, the
  verbatim statement text, and — for names bound to build123d shapes — a
  metrics snapshot (solid count, bbox, volume, face count, `sealed` =
  is-manifold, `genus`). Those checkpoints persist on the §8 `BuildResult`
  and are projected by `GET /parts/{part}/build` as `checkpoints[]`. Metrics
  and per-statement BRep writes stay lazy (mission rule 4): a checkpoint
  carries an `artifact_ref` only when publication minted a last-good blob
  for that stop.
- **Failure semantics.** On exception, the build result MUST include: the
  failing line and column, exception type, a source frame (±2 lines), the last
  successfully executed statement, the last-good metrics snapshot, and a
  machine-readable `last_good_artifact_ref`; canonical replay uses
  `inspect_part(part, artifact_ref=last_good_artifact_ref)`. This reproduces (and is acceptance-tested against) the observed
  Smith error shape.
- **Determinism.** Same script + params + hephaestus version ⇒ identical
  geometry (bit-stable STEP is not required; metric-stable within 1e-6 mm is).
- **Sandboxing.** The namespace whitelist is defense in depth, not a security
  boundary: Python/native-object introspection can bypass language-only
  restrictions. Normal agent/server and executable-registry builds therefore
  require a probed OS isolation backend that exposes no project/host files,
  gives the worker an empty writable tmpfs, mounts only the pinned runtime
  read-only, creates a network namespace with no interfaces, drops privileges,
  and enforces CPU, memory, process, and wall-clock limits. The v0.1 native
  backend is Linux bubblewrap isolation. macOS agent execution requires a
  detected Docker, Podman, or OrbStack-compatible OCI backend running the
  pinned Linux executor image with read-only root, no network, dropped
  capabilities, bounded resources, and only protocol pipes exposed; Stage S
  must prove this profile rather than trusting backend presence. Both paths are
  mutation-tested for filesystem/network escapes. On a platform without a
  passing backend, agent/server execution fails closed; an explicit
  `--unsafe-local-executor` exists only for user-invoked core debugging, prints
  a warning, may not execute registry content, and is refused by `heph serve`.
  This is local single-user isolation, not hardened multi-tenant containment;
  OCCT native crashes remain a worker-level DoS risk. DECISION(ours).
- **Source maps.** Provenance is recorded at three scopes, each with an
  honest guarantee: (1) *bindings* — for every name bound to a shape, the
  creating statement and every rebinding statement, including bindings made
  inside loops and function bodies (recorded per iteration with the call
  site); (2) *boolean results* — a shape produced by `+ - &` attributes to
  the boolean statement itself, with references to the operand shapes'
  provenance (result *faces* are NOT attributed to operand statements: OCCT
  history tracking is out of scope, and the docs make no per-face promise for
  untagged topology); (3) *tags* — tagged faces/edges map name → (solid,
  topology index, tagging statement) plus a drift fingerprint (contract
  §5.3). Selection resolution (§4.4) therefore lands on: the tag if the
  picked topology is tagged, else the owning solid's binding/boolean
  statement. Serialized alongside the build artifact. DECISION(ours) — this
  is the provenance layer; Smith shows only its effects (per-feature
  metadata), not its mechanism.

### 3.2 Kernel services

Pure functions over built geometry, shared by tools and checks:

- `metrics(shape)` → bbox, volume, area, solid/face/edge counts, sealed, genus
- `interference(a, b)` → overlap volume (boolean intersection)
- `clearance(a, b)` → minimum separation distance
- `distance(feature_a, feature_b)` → measured distance between tagged or
  selected topology
- `mass(shape, material)` → via materials registry density
- `section(shape, plane)` → section faces for section rendering

### 3.3 Render service

Offscreen, headless, deterministic. Given a build artifact and a view spec,
produce:

- **rgb** — shaded render honoring `.color`, from named cameras (`iso`, `+X`,
  `-X`, `+Y`, `-Y`, `+Z`, `-Z`, `front`, custom azimuth/elevation).
- **mask** — flat-shaded ID render. `solid` mode has one solid-ID pass.
  `selection` mode is an artifact bundle with **three separate non-antialiased
  integer/palette passes** (`solid`, `face`, `edge`); no pixel encodes multiple
  domains, and edge rasterization cannot overwrite face/solid pixels because it
  is a separate layer. The bundle publishes one global `selection_id → {kind,
  solid_id, topology_index, tag?}` table, per-pass palettes, and exact source
  build ref. Each requested view returns a typed per-view `bundle_ref` plus
  `{solid, face, edge}` pass refs; every pass links immutably back to its bundle.
  ID passes are artifact-only; one non-decodable composite preview per view may
  be inline, preserving the four-image bridge cap. GLTF primitives/
  edge overlays carry the same IDs and link the bundle, so model, web raycast,
  and tests share one namespace.
- **section** — rgb with a section plane applied.
- **explode(t)** — per-solid translation along assembly axes, t ∈ [0, 1].
  Amended 2026-08-27, landing with Stage 4: the transform is a **homothety
  about the assembly centroid**, not a translation along a shared axis — each
  solid moves `(solid_centroid − assembly_centroid) · t · EXPLODE_SCALE`, so a
  solid further from the centre moves further. `core/render/channels.py`'s
  `_explode_offset` is its one definition, and `core/render/gltf.py` emits that
  displacement at `t = 1` as each mesh's `extras.explode_offset` so the web
  client applies `offset · t` and computes nothing (`INTERFACE.md` §5.1/§5.2).

Implementation: export tessellation from OCP, render via a headless rasterizer
(VTK offscreen or trimesh/pyrender). Renders MUST be deterministic across CI
runs on the same platform tier (SSIM ≥ 0.995 against goldens). DECISION(ours):
we render server-side for the agent loop and ship GLTF to web clients, which
render live locally.

Amended 2026-08-27, landing with Stage 4: "ship GLTF to web clients" now has a
producer. `GET /artifacts/{ref}/gltf` **resolves, or publishes on demand, the
selection bundle for that exact build ref** — re-tessellating from the stored
BREP — and publishes the GLB under the existing `gltf` artifact kind, which is
what makes the route's `ETag: <ref>` / `immutable` caching honest. It **never
returns an unlinked GLB**: an unlinked one carries numerically valid IDs that no
bundle backs, so the viewport would be pickable but unresolvable. The engine half
is `core/render/gltf_publish.py`; the web layer reaches it through the same
`CadOps` seam every other engine call rides (`INTERFACE.md` §5.1, §12.3).

### 3.4 Checks engine

Executes `CHECKS` blocks (see `script_contract.md` §6) against a build:
each check is a named predicate over kernel-service results with a tolerance.
Output is a machine-readable report (pass/fail per check, measured values).
Checks are re-run on every build of the part and on every build of any part
whose shared constants it consumes. Cooperating project-check create/edit increments a check-set generation under
a dedicated check-set lock. A project-check run holds that lock while
atomically enumerating and snapshotting the complete,
lexically ordered authorized `checks/*.py` set into one immutable bundle, then
releases it before execution. CheckReport includes generation,
`check_bundle_ref`, and per-file hashes alongside geometry
`project_snapshot_ref`. A concurrent edit/create belongs wholly to the old or
new generation, never a mixed in-flight report. Check mutations use a typed
WAL containing old/new generation and file hashes: after candidate rename,
generation publication is compare-and-swapped before COMMITTED; recovery after
any crash completes exactly one generation advance or restores/conflicts the
file. Changed content is never visible under the prior cooperative generation.
Every check-set lock acquisition—read, capture, create, or edit—first resolves
all relevant `PREPARED` check WAL rows while holding the lock, before exposing
generation or files. Thus a surviving process cannot observe renamed content
under the old generation. On every lock acquisition, the stored tree hash is
also compared with the live check tree. A stable direct-filesystem change with
no matching WAL is reconciled under the lock into exactly one new
`external_import` generation before list/run proceeds. If sandbox parse/
contract validation fails, the generation is persisted as invalid with an
opaque diagnostics artifact; discovery returns only the discriminated invalid-
generation result and project check execution fails closed—malformed checks are
never omitted. An edit still changing during capture returns `check_set_drift`. Thus changed content is never reported under an old
generation, while atomicity guarantees remain limited to cooperating writers. DECISION(ours) — no observed
equivalent; this is Hephaestus's persistent verification layer.

### 3.5 Project store and `opstore` boundary

The generic durability substrate is a separate top-level Python workspace
package, `opstore/`. It owns operation-key verification/tombstones, generic WAL
transactions and recovery hooks, content-addressed blob publication, leases,
admission/terminal acknowledgment (including suspension), and reachability/GC
primitives over SQLite plus the filesystem. It has its own README, public typed
interfaces, crash/property tests, and **must not import build123d, OCP, Pi,
thread-phase, or `core/`**.

`core/project_store` is the Hephaestus adapter and policy layer. It defines CAD-
specific payloads and state transitions, project authorization and lock order,
git/source semantics, dependency projections, artifact provenance edges, and
typed build/check/export/delegation publication using `opstore` primitives.
Thus extracting durability does not let generic storage decide what constitutes
a current build, coherent project, valid check, or authorized artifact. The
package remains in this monorepo and ships inside the Hephaestus wheel for v0.1;
a separate repository/public release is deferred until its API stabilizes.

A Hephaestus project is a directory in a git repository:

```
project/
├── hephaestus.toml         project manifest: name, units, registry pins
├── globals.py              project-shared constants (the `hc` namespace)
├── parts/
│   ├── cat_step_shelf.py
│   └── cat_step_gusset.py
├── assemblies/             assembly definitions (Stage 6)
├── checks/                 cross-part checks
└── .heph/                  build artifacts, renders, source maps (gitignored)
```

Version semantics are git semantics. "Publish" = tag. The dirty marker
(Smith's `v1*`) = `git status`. The web UI reads history from git log.
DECISION(ours), replacing Smith's opaque session/version model.

**Concurrency.** Single-writer per part: builds and script writes serialize
on a per-part advisory lock in `.heph/locks/`; project-scoped parameter writes
use a project-config lock, then acquire affected part locks in lexical order
when updating stale markers. The global order is project-config → check-set → lexical part locks; no code
may wait for an earlier lock while holding a later one. Builds
briefly acquire project + target-part locks in that order to capture a snapshot,
release both during geometry computation, then reacquire them in the same order
for publication. The agent's mutations and a human's editor save go through
the same store API and lock order. The no-lost-write guarantee applies to
cooperating Hephaestus clients (web editor, CLI store API, and agents). Direct
third-party filesystem writes bypass advisory locking and are outside that
atomicity guarantee; a watcher snapshots observed external versions best-
effort and reports drift, but cannot provide filesystem compare-and-swap.
Writes carry the base content hash they were computed against; a stale hash is
a conflict returned with current content/hash and content-addressed refs for
the base and exact attempted candidate. Reads register immutable hash-addressed
snapshots so the store can construct that candidate after the live file
changes. The commit path rechecks the live hash immediately before rename and
conflicts/journals any observed intervening version.

Every mutation carries a trusted operation id. The Pi proxy derives it from
session UUID + persisted assistant-message entry ID + tool-call ordinal +
provider tool-call ID, so repeated provider IDs cannot collide. The server
normalizes all sources into an HMAC-bound key with a trusted embedded timestamp,
allowing horizon checks after tombstone GC. The HMAC keyring is generated
atomically under `.heph/keys/` with mode 0600, has explicit key IDs, and is
never committed. Rotation creates a new active key while retaining verification
keys for at least 37 days after their last issuance; operation rows/tombstones
record the key ID. Backup/restore treats the keyring and `.heph/state.db` as one
unit. A missing/corrupt keyring with existing state fails closed and requires
explicit restore/recovery — it is never silently regenerated. A non-Pi client
uses the bounded idempotency contract described in `tool_schema.md`; the model
never invents the key. The `core/project_store` adapter uses `opstore`'s crash-recoverable operation
state machine in `.heph/state.db`: (1) write and
fsync content-addressed preimage/candidate blobs and a same-directory candidate
temp file; (2) transactionally record `PREPARED` with operation id, canonical
payload hash, before/after hashes, paths, and intended outcome; (3) atomically
rename the candidate, then fsync the file and parent directory; (4)
transactionally record `COMMITTED` plus the response. On retry/startup, a
`PREPARED` row is resolved under the same lock: live hash = candidate completes
the commit, live hash = preimage safely reapplies it, and any third hash marks
the operation `CONFLICTED` without overwriting. Identical committed retries
return the recorded outcome; id reuse with another payload fails. Recovery is
from git for committed state, the journal for overwritten dirty state, and the
attempted snapshot for a rejected contender.

Builds, exports, and project manifests use typed variants of the same WAL.
Build publication fsyncs a content-addressed bundle, records `PREPARED` with
bundle/current-pointer hashes, atomically installs the bundle, then compare-
and-swaps the current pointer under project/part locks before `COMMITTED`.
Exports first freeze/authorize an immutable successful source artifact and
record its input hashes, then fsync a temp output, record source/target/pin and
export-hash intent, atomically create the final file, persist its GC-root pin,
and commit the provenance-bearing outcome. Project manifests
are content-addressed bundles whose live pointer is compare-and-swapped while
all addressed projection validations/locks hold. Recovery inspects bundle and
pointer/pin state and completes or marks conflict; no partial bundle, unpinned
delivered export, or half-published manifest is reported successful.

Delegation uses a non-filesystem WAL state machine keyed by the trusted parent
invocation: `PREPARED → ADMITTED → DISPATCHED → TERMINAL`, with one stable child
run ID persisted at ADMITTED. Dispatch and queueing are idempotent on that ID.
At ADMITTED the coordinator persists absolute `deadline_at = admitted_at + D`;
queued time counts. For synchronous `delivery="prompt"`, the waiting parent is
transactionally moved to durable `SUSPENDED_WAIT` while the child admission is
reserved; that parent does not consume an active run slot. Child and resumed-
parent admissions have FIFO priority over new external prompts, and the parent
must reacquire a slot before processing the child result. This prevents 16
waiting orchestrators from starving all 16 children. Follow-up parents are not
waiting and retain their ordinary slot; thread-phase fanout derives its bound
from currently available child admissions rather than an independent constant. Child terminal ingestion and delegation-row terminal
projection occur in one Python `state.db` transaction. Cancellation, deadline,
and recovery each start that same coordinator transaction by checking the
child terminal table; an existing child terminal wins. Otherwise they CAS the
nonterminal delegation row: cancellation to `CANCEL_REQUESTED`, elapsed
`deadline_at` to terminal `timed_out`, or recovery ownership to the same child.
Only the transaction winning that CAS may abort/dispatch/insert its terminal.
Recovery precedence is therefore: (1) project existing child/delegation
terminal; (2) finish CANCEL_REQUESTED as `cancelled`; (3) deadline as
`timed_out`; (4) resume PREPARED (allocating its first child ID) or recover
ADMITTED/DISPATCHED with the persisted ID; (5) unrecoverable owner/process loss
as `interrupted`. Any terminal forbids dispatch and has precedence
over generic interruption synthesis. Crashes at enqueue, dispatch ack,
cancellation, terminal insertion, or parent response therefore produce at most
one child and exactly one semantically distinct terminal.

A build invocation freezes immutable script, part params, request-effective
params, pinned toolchain, and the part's consumed-`hc` projection (the exact
`hc` names read plus canonical values) under its trusted idempotency key. Full
`globals.py` source and project-param hashes are retained as audit metadata but
do not invalidate an artifact whose consumed projection is unchanged. Before
publishing a **successful, non-preview** artifact as current or clearing stale
state, it reacquires the locks and revalidates script/part-param/toolchain and
consumed-`hc` hashes. Failed builds
and transient-parameter previews always have `current=false` and preserve the
prior successful current artifact. A raced build may retain a content-addressed
superseded artifact for audit, but cannot become current; retrying the same
invocation returns the result from its original frozen snapshot. Every attempt
returns an opaque immutable build `artifact_ref`, and failures return the exact
`last_good_artifact_ref` described by their metrics.

Project/global changes increment an audit revision and recompute dependency
projections. Only parts whose consumed names/values changed become stale. A
coherent project-snapshot manifest atomically maps every addressed part to a
successful artifact whose consumed-`hc` projection matches the current live
projection; unchanged parts may contribute an artifact from an older audit
revision. Shared dependency names necessarily carry equal canonical values.
Project-scoped measure/check rejects with `incoherent_project_snapshot` and
stale/mismatched projection details unless a valid current manifest exists or
the caller supplies an immutable `project_snapshot_ref`. Reads of one part run lock-free against
its last completed current artifact, so a long build never blocks inspection. Two *clients* attached to one part share
one agent context; the event stream serializes what each sees.
DECISION(ours) — no concurrency behavior was observable in the reference
product.

**Artifact lifecycle.** `.heph/` is quota-managed. The current successful
artifact and one most-recent-failure last-good pointer per part are protected;
older failed-build/checkpoint refs follow the normal 30-day evidence retention
unless user/job-pinned. Active session branches, uncommitted recovery journal entries, operation WAL
rows needed for idempotency, live job checkpoints, every successful
manufacturing export, every check bundle referenced by a retained CheckReport,
and user-pinned evidence are protected. Pins are transitive across artifact
links: pinning a GLTF or selection layer retains its selection bundle/table and
source build; pinning the bundle retains every pass and source build. Exports remain
GC roots until explicit `heph export unpin/delete`; this applies to explicit
and content-addressed targets. Accepted-overwrite preimage journals are kept
for at least 30 days and can be pinned longer. By default, unpinned superseded
renders/builds and full completed-operation outcomes age out after 30 days,
stale previews after 7 days, and content blobs are deleted only by reachability
GC. Outcome GC retains a compact
key/payload/terminal-state/commit-hash tombstone through the 30-day idempotency
window. Keys encode/are assigned a trusted creation time and are rejected as
`key_expired` outside that window without execution; tombstones may age out
after the window plus a 7-day safety margin, so protected metadata cannot grow
without bound. `heph gc --dry-run` explains
every candidate; automatic GC runs only between jobs, uses a configurable
10 GiB soft quota, never deletes protected refs, and emits an audit report. If
protected roots alone exceed the quota, GC reports `protected_quota_exceeded`
and new artifact-producing operations fail before execution until the user
raises the quota or explicitly unpins/deletes data; nothing protected is
silently removed. Session deletion is explicit; Pi compaction does not delete
JSONL history.

Artifact reads acquire `opstore` project-wide, cross-process shared leases
recorded in `state.db`; manual and automatic GC use the same coordinator and require an
exclusive per-ref deletion lease, then recheck reachability before unlinking.
Lease expiry is heartbeat/liveness checked. A reader either opens and validates
the complete immutable artifact under lease or receives `artifact_expired`; GC
never produces a partial read, including on platforms where unlinking an open
file is unsafe.

### 3.6 Registries client

Four registry types, one format: a versioned directory with a `registry.toml`
manifest, fetchable from a git URL or a local path, **pinned in
`hephaestus.toml` by content hash** (a Merkle digest over the registry tree;
`heph registry update` re-pins explicitly, nothing updates implicitly).
Registry content is untrusted input in two distinct ways and is handled
accordingly: *executable* content (parts-store generators, DFM rule
predicates) runs only under the same sandboxed executor and injected-
namespace whitelist as part scripts — a store part is a part script, with no
additional capabilities; *contextual* content (skills, materials notes) is
injected into agent context wrapped in provenance-marked delimiters, and the
system prompt instructs the model that registry text is reference material,
not instructions — with the residual prompt-injection risk named in the
threat model (§7) rather than hand-waved.

- **skills/** — markdown packs teaching the agent domain technique (build123d
  idioms, joinery, sheet-goods design, 3D-print design rules). Loaded into
  context on demand by `load_skill`.
- **parts/** — parametric generators (standard hardware: screws, inserts,
  bearings) exposing the same script contract; `search_parts_store` queries
  them, instancing returns a placed `Compound`.
- **materials/** — JSON/TOML records: density, sheet thicknesses, cost hints,
  finish notes; `search_materials` queries them.
- **dfm/** — per-process rule packs (laser_cut, cnc_router, fdm, waterjet): predicates
  over geometry + material (min feature size, kerf, min internal radius, wall
  thickness) that the checks engine can run when the part declares that
  process. Powers the DFM mode.

## 4. agent/

### 4.1 Pi-based agent runtime

The TypeScript agent sidecar embeds `@earendil-works/pi-coding-agent` through
its SDK. A Pi `AgentSession` owns the model/tool loop, provider and credential
resolution, streaming events, steering and follow-up queues, cancellation,
retry, token accounting, compaction, and persistent session history. The
lower-level `pi-agent-core` remains an implementation detail; Hephaestus uses
the full SDK so it does not rebuild those lifecycle services.

Pi's coding tools are disabled. A shipped, trusted Hephaestus extension and
custom `ResourceLoader` provide a CAD-specific system prompt and only the
tools defined in `tool_schema.md`. Tool implementations are TypeScript
proxies over the Python JSON-RPC bridge; build123d scripts still execute only
inside the Python sandbox. Pi events are normalized into a stable
Hephaestus event vocabulary before CLI, MCP, or web clients see them, so Pi
session formats and provider-specific events do not become public API.

**Context policy** (configurable, defaults stated): CAD system prompt +
provenance-delimited loaded references + project summary (parts list, `hc`
params and constants, check status) + rolling Pi transcript. Images are the
budget hazard: a Hephaestus context/compaction extension keeps image blocks
only for the most recent K=3 `inspect_part` results. (`query_snapshot` returns
text/artifact refs only.) Older image blocks
are replaced in model context by a text stub (`[render: cat_step iso/mask,
superseded — re-run inspect_part to view]`) while the immutable artifact
remains on disk. At T=70% of the model's context window the extension requests
Pi compaction with a CAD-aware pinned summary: design intent, decisions, open
problems, current params, and check status. The build artifact, not either
Pi's transcript or a thread-phase log, is the source of truth for geometry.
Per-session token and cost budgets trigger `ask_user` escalation at 90%.

Authentication is app-owned through Pi `ModelRuntime` with explicit
Hephaestus auth/model paths. The Python supervisor starts the sidecar with a
minimal environment and forwards only provider credential variables explicitly
approved in Hephaestus configuration; ambient provider keys, project/global Pi
resources, and generic coding tools MUST NOT silently affect a run. Exact Pi
and Node versions are exact-pinned (no caret/tilde ranges) and compatibility-
tested in Stage S. The spike inventories Pi `ModelRuntime` providers and proves
one non-Anthropic OpenAI-compatible endpoint plus one local endpoint through
fake servers; unsupported provider classes narrow the README claim before
Stage 0.

### 4.2 Agent scoping

One persistent Pi session exists per part (matching observed per-part tabs),
plus a separate project-orchestrator session that can create parts and
delegate through a constrained `delegate_part_agent` tool. Part sessions cannot
delegate or edit project-global/check files; the orchestrator alone receives
those scoped tools. Scoped quick-edit agents (§4.4) are child sessions seeded
with a
bounded provenance and image context. The server grants one process a leased,
heartbeat-backed lock for each persistent session under `.heph/locks/`; a
second process MUST route through the owning server or fail with a structured
`session_busy` result rather than opening the same Pi JSONL for writing. Stale
leases are recovered only after owner liveness checks. Pi session JSONL is
conversation truth; git and `.heph/` build artifacts remain design truth.

### 4.3 Structured questions

`ask_user` emits an options block (observed: "Ask question (4)"); in CLI it
renders as a numbered prompt, over MCP as structured content, in web as a
widget. The loop suspends until an answer event arrives.

### 4.4 Selection → scoped agent

A client sends `{part, build_artifact_ref, selection_artifact_ref,
selection_id}`. `selection_artifact_ref` may name a returned per-view bundle,
one of its solid/face/edge pass layers, or a GLTF whose immutable metadata links
that bundle. The server follows immutable pass/GLTF links and validates the
bundle association, exact source build, ID kind/table entry, and layer before
provenance/crop lookup. RGB, unlinked GLTF, and unrelated mask refs are rejected. It never falls back to current geometry; an
expired/mismatched ref returns `stale_selection`. The harness spawns a child Pi
session whose context contains the artifact-bound part source, resolved
provenance, and crop centered on the selected topology. This reproduces Smith's "Quick edit — 1 face → Ask a new
agent" with strictly more context than Smith demonstrates.

### 4.5 Thread-phase orchestration

`@autonome-research/thread-phase` is the deterministic orchestration substrate
above individual Pi sessions, not the interactive agent loop. It owns bounded,
auditable project workflows such as request decomposition → part delegation →
cross-part checks → capped repair → final verification, as well as benchmark
fanout across tasks and seeds. A `JobRunner` persists orchestration events and
supports replay and cooperative cancellation. Hephaestus supplies an
application-owned `JobStore` backed by Python SQLite over the bridge, avoiding
a required native Node SQLite addon in the packaged sidecar. Session ownership
remains with Hephaestus: phases call its Pi session service directly and use
thread-phase's free-runner patterns (for example `boundedFanout`) rather than
depending on the separately versioned/internal `AgentAdapter` or Pi-adapter
surface. The pinned thread-phase distribution MUST expose phases, patterns,
and `JobRunner` without a required native Node addon; Stage S rejects older
package layouts that eagerly require `better-sqlite3` even when a custom store
is supplied. Its transitive `openai` package is not an approved Hephaestus
provider path: Stage S records an SBOM/import graph and either excludes it from
the compiled sidecar or explicitly allowlists it as inert, proving it is never
loaded, receives no credentials, and cannot initiate runtime requests.

Jobs carry owner leases, heartbeats, and resumable phase checkpoints. On
startup, the supervisor classifies orphaned `RUNNING` jobs as interrupted,
records a terminal failure with `failureClass="interrupted"` in thread-phase's
existing status model, and projects that class as `interrupted` to Hephaestus
clients. Resume creates/continues execution from a verified checkpoint or
re-runs an idempotent phase; it never leaves an unowned job appearing live or
marks it successful from partial output. Checkpoints live in the Python-backed
JobStore and include the workflow definition/version and input/output hashes.

Direct single-part chat, multimodal `query_snapshot`, quick edits, and ordinary
build/measure/render tool calls bypass thread-phase and use Pi/core directly.
This is deliberate: thread-phase is for deterministic multi-phase control and
does not own multimodal context. State ownership is non-overlapping: Pi JSONL
stores conversation history, thread-phase `JobStore` stores workflow history,
git stores authored design state, and `.heph/` stores generated CAD artifacts.

## 5. server/

- **MCP server** (FastMCP, stdio for local, streamable HTTP for remote):
  exposes the full tool schema plus project/session management. An MCP client
  with no Hephaestus UI can run the entire loop; this is Stage 3's gate.
  HTTP transports bind to localhost and require a generated bearer token by
  default; binding beyond localhost requires an explicit flag whose help text
  points at the threat model. Historical conversation reads are owned by the
  sidecar: a private bounded bridge method reads Pi JSONL via Pi's session API,
  normalizes it to public Hephaestus events, and freezes a first-page high-water
  mark into opaque cursors. HTTP serves that normalized snapshot; Python/web
  never parse Pi JSONL directly.
- **HTTP + WebSocket API** for the web client (`server/http`): project and part
  reads, build/render artifact serving (GLTF, PNGs), the git projection, the
  agent event stream, selection and answer events. Same bind/token defaults.
  Amended 2026-08-27, landing with Stage 4: this surface is a **named, closed
  route table** rather than a prose promise — `INTERFACE.md` §2.3 enumerates
  every route, §2.4 closes the error mapping, and §2.5 pins REST idempotency;
  a route not in that table is not served, and `server/tests/test_http_boundary.py`
  asserts the served surface *is* the table in both directions. Two consequences
  the prose above left open are now decided there: mutations carry an
  `Idempotency-Key` on an **enumerated** seven routes (never a rule derived from
  tool declarations), and `/artifacts/{ref}/bytes` is closed **by enumeration**
  so an `export`-kind ref is refused rather than served. It remains a **web
  client API, not part of the headless surface** (2026-07-26 ordering
  amendment): nothing in the headless surface may depend on it, which is also
  asserted mechanically.

  Amended 2026-08-27, the **live stream and history half** (`INTERFACE.md` §2.7,
  §2.8). `GET /events` upgrades to a WebSocket and emits the normalized public
  vocabulary only, in the Python-side shape verbatim plus exactly one envelope
  field, `session_id`. A browser tab registers as a **non-durable observer**: it
  gets the same 1024-slot bound and the same `progress` coalescing as any pump
  client, but it **never participates in backpressure-cancel**. On overflow the
  socket closes `4409 resync_required` and the client is dropped; **the run is
  not cancelled**, because a stalled UI must not kill an agent's work. History is
  pre-attach backfill only and never closes a live gap: live events are
  identified by `(run_id, seq)` and historical ones by `(session_id, ordinal)`,
  two disjoint namespaces that are never merged. Parent/child session threading
  is recorded **outside** the event vocabulary, in `state.db`'s new
  `tp_session_edges` table, written by `SessionService.spawn_quick_edit` and by
  the delegation WAL's `PREPARED` transition; a session with no row reopens
  `unlinked` rather than being guessed at.
- **Agent bridge**: the Python server starts and supervises the packaged Node
  sidecar and speaks strict LF-delimited, versioned JSON-RPC over stdio. The
  bridge supports prompts, images, tool requests/results, streaming events,
  user-question suspension, cancellation, session resume, and bounded output.
  Protocol limits are contractual defaults: each LF-terminated wire frame is
  at most 64 MiB of UTF-8 including JSON, base64, and delimiter; parsed JSON
  has maximum nesting depth 64, 10,000 members per object, and 10,000 items per
  array before tool-specific tighter schemas; non-image string data totals at
  most 16 MiB; decoded binary totals at most 32 MiB, with 8 MiB per image and
  four images per result. Images are PNG/JPEG only, at most 4096×4096 each and
  32 megapixels total per result; dimensions/pixel budget are checked with a
  bounded header parser before full decode, and the decoder enforces its own
  allocation cap. The incremental framer aborts as soon as the wire cap is
  exceeded. There are at most 64 pending RPC requests, **16 admitted run
  slots**, 32 queued prompts per session, and 1024 ordinary buffered events. An
  active run—including an admitted queued delegation—reserves one slot at
  ADMITTED, before sidecar execution/queueing, and retains it through terminal
  acknowledgment unless it durably enters `SUSPENDED_WAIT`. Queued, running,
  and completed-but-unacknowledged active runs together can never exceed 16.
  The dedicated backpressured terminal channel has the same 16 slots and accepts exactly one terminal record per run. The Python event/
  JobStore durably records a terminal before its slot is acknowledged/reused; a
  seventeenth run returns `busy`. Request/queue overflow returns `busy`.
  Explicitly droppable progress deltas are first coalesced to the latest event
  per `(run_id, event_kind, tool_call_id)`; audit events, tool calls/results,
  questions/answers, and terminals are never coalesced or dropped. Only if the
  bounded queue still cannot progress after coalescing does backpressure cancel
  the affected run and route its final error through the terminal channel.
  Protocol stdout never carries logs.

  Python transactionally allocates a stable run ID and durable admission row
  before prompting/queueing the sidecar; every event carries it. Admission rows
  persist state, terminal ID, and `terminal_acked_at`. Reserving a slot counts
  active rows without a durable terminal acknowledgment and succeeds only when
  fewer than 16 exist; durable `SUSPENDED_WAIT` parents are excluded until they
  reacquire a prioritized active slot. A project terminal table has unique
  `(run_id, "terminal")` key/payload hash, covering direct Pi runs and workflows. Terminal insertion
  and operation-specific terminal projection share a transaction; bridge
  acknowledgment names the terminal ID and durably/idempotently sets
  `terminal_acked_at` before slot release. Startup reconstructs occupancy as
  the **union of run IDs** in admitted-nonterminal and terminal-unacknowledged
  rows (never their sum), resolves persisted terminals/acknowledgments, then
  admits new runs. Restart recovery checks the terminal
  table plus operation-specific recovery state.
  Generic direct runs with no recoverable coordinator get one `interrupted`
  terminal when owner loss is confirmed; delegation follows §3.5 precedence.
  A crash after terminal insertion or acknowledgment creates none.

  Tool requests default to 120 s with an explicit 300 s CAD-build class.
  Synchronous delegation supplies child deadline `D` (default 600 s, maximum
  1200 s); its bridge deadline is always `D + 60 s`, reserving cleanup/terminal
  persistence grace. The outer timeout never races the child deadline and
  remains cancellable. Prompt hard/idle timeouts are capped by
  configuration. Each run has its own
  abort controller: cancelling one session terminates only its owned tool child
  processes and leaves other multiplexed sessions healthy. The supervisor
  kills the whole sidecar only after an unresponsive-process watchdog fires,
  then marks affected generic runs interrupted and hands recoverable delegation/
  workflow runs to their coordinators before any terminal synthesis. A crashed sidecar cannot corrupt
  a completed build artifact and is restartable from verified Pi session and
  workflow state. The bridge is private implementation, never a remotely
  exposed transport.

## 6. web/

React + TypeScript. Vite. three.js viewport consuming GLTF with per-solid
metadata plus artifact-bound face/edge selection IDs and linked selection bundle (id ↔ mask palette ↔ tree row). Monaco for scripts. Panels: file
tree / script / results (geometry list with visibility, properties, check
status) / agent stream. Viewport affordances: view cube, grid with scale
readout, explode slider, measure mode, section plane, selection with quick-edit
popover. The web app is a pure client of server/; it holds no geometry logic.

## 7. Threat model

Hephaestus executes model-generated code and loads community content by
design; the threat model states what is and is not defended.

**Assets**: the user's machine and files; the user's design IP; API keys;
the integrity of published bench results.

**Trust boundaries and mitigations**:

1. *Model-generated scripts* (the core loop). Untrusted by definition. The
   probed OS filesystem/network/process sandbox (§3.1) is the boundary; the
   namespace whitelist is auditable defense in depth, not the boundary.
   Additions to either surface require reviewed tests. Residual risk accepted:
   kernel/OS sandbox escapes and OCP/OCCT native crashes are possible; workers
   are least-privileged, restartable, and per-build, but this is not a
   multi-tenant security claim.
2. *Agent runtime and registry content*. The shipped Pi extension and
   thread-phase workflows are trusted application code and run with the Node
   process's permissions, so only pinned, reviewed packages are loaded. Pi's
   generic coding tools and ambient global/project extensions are disabled.
   Community registry content is never loaded as a Pi extension or privileged
   Pi skill: executable content gets sandbox parity with part scripts (§3.6),
   while contextual content is returned by `load_skill` inside explicit
   provenance delimiters. A prompt-injected model can invoke only the narrow
   Hephaestus tool bridge. Model-facing names and paths are canonicalized under
   fixed project roots, reject absolute/traversal/symlink escapes, and write
   atomically through git-recoverable project APIs. Hash pinning makes registry
   supply-chain changes explicit and reviewable.
3. *Remote transports*. Localhost + bearer token by default (§5); TLS and
   real authn are deliberately out of scope for the mission — the documented
   deployment posture for shared use is "behind your own reverse proxy," not
   "expose heph serve."
4. *Bench integrity*. Private gate split, provenance-hashed goldens, and
   solutions-validated tasks (see `verification.md`).

Explicitly out of scope: multi-tenant isolation, DRM on designs, and
defending a user who pastes hostile scripts and explicitly selects
`--unsafe-local-executor` for core debugging (the flag prints a warning,
refuses registry code, and is unavailable under `heph serve`).

## 8. Explicit non-goals (current mission)

- Scrapyard-style community design sharing (deferred by decision; registries
  cover the ecosystem need first).
- Parametric direct manipulation (drag-editing dimensions in the viewport).
  Selection → scoped agent is the interaction model.
- Multi-tenant hosted service hardening.
- Training or fine-tuning models. The corpus may eventually support it, but
  the mission targets harness quality with off-the-shelf models.
