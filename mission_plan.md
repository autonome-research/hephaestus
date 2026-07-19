# 04 — Mission Plan

The droid mission implementing Hephaestus. A de-risking spike plus eight build stages (S, 0–7), strictly ordered;
each stage lists deliverables, then its **gate**: the complete, machine-
checkable exit criteria. A droid MAY parallelize within a stage but MUST NOT
begin stage N+1 deliverables before stage N's gate is green in CI. Verifier
tiers reference `verification.md`.

Reading `architecture.md`, `script_contract.md`, and `tool_schema.md`
is prerequisite to Stage 0.

---

## Stage S — De-risking spike

The mission's six riskiest infrastructure assumptions are converted to
evidence before anything is built on them. Deliverables: (a) a pinned CI
container image with build123d + OCP installed, in which a scripted box is
built and rendered on the software rasterizer **twice in separate jobs** with
byte-comparable determinism (SSIM = 1.0 or pixel-identical); (b) a FastMCP
echo server exercising elicitation from a scripted client over stdio and
streamable HTTP — or, if elicitation support is inadequate, a written
fallback decision (structured content + follow-up call) committed to
`tool_schema.md` §ask_user before Stage 2; (c) a 10-minute OCCT sanity
script exercising fillet failure, boolean of 30 solids, and STEP round-trip
in the image, timed against the performance budgets; (d) a pinned Node + Pi +
thread-phase compatibility spike proving a Pi SDK session with all coding
tools disabled can call a fake Hephaestus custom tool, stream text/tool/image
events, compact, cancel, and resume from its app-owned session directory; and
(e) a supervised Python ↔ Node JSON-RPC-over-stdio fixture proving tool-call
round trips, bounded framing, process-crash reporting, cancellation, and
`ask_user` suspension, plus a thread-phase phase that calls a pre-built Pi
session through the Hephaestus session service and emits durable JobRunner
events; and (f) the packaged secure Linux executor running inside the actual
CI/release image, with filesystem/network/process escape probes, resource-limit
termination, and fail-closed capability detection. Production MUST use free-
runner phase/pattern APIs and MUST NOT depend on thread-phase's separately
versioned/internal AgentAdapter or Pi-adapter surface.

**Gate GS**: the spike workflow is green in CI on two consecutive runs; the
image tag and exact Python, Node, Pi SDK, and thread-phase versions are
recorded in `repo_conventions.md`; the Pi/thread-phase test uses only
project-pinned dependencies rather than a global CLI; the selected
thread-phase release has a native-free public orchestration import and the
packaged sidecar has no required native Node addon (older eager
`better-sqlite3` package layouts are rejected, and JobStore persistence is
exercised through a Python-SQLite bridge implementation). Hostile ambient
provider keys and Pi resources are ignored unless explicitly approved. Tests
hit every bridge size/queue/timeout boundary, race two processes for one Pi
session and observe one owner plus `session_busy`, crash owners and recover
stale leases, and crash a `RUNNING` workflow then observe an interrupted record
and verified resume/rerun. Subprocess leak checks find no orphan sidecars after
success, failure, timeout, or cancellation; any fallback decisions are merged
as doc amendments. Nothing else may merge first.

## Stage 0 — Kernel executor and script contract (headless)

Deliverables: `core/executor` (statement-level incremental execution,
checkpoints, secure OS sandbox plus explicit unsafe debug backend, param
validation, `hc` namespace with dependency tracking, source maps),
`core/kernel` services (metrics, interference, clearance, distance, mass,
sealed/genus), `core/checks` engine, and `core/project_store` with canonical
locks/order, operation WAL and crash recovery, idempotency DB, authorized
snapshots/journals, coherent dependency-projection manifests, opaque artifact
refs, quota/GC, and typed build/export publication. Deliver build-result records
per contract §8 and the CLI verbs `heph build`, `heph check`,
`heph lint`. Vendor the two recovered Smith scripts into `corpus/reference/`
with a `globals.py` reconstructed from their `hc.*` reads.

**Gate G0** (Tier 1): `uv run pytest tests/stage0 -q` exits 0, covering:
contract tests on both reference scripts (25 and 3 labeled geometries; shelf
bbox 380×280×250 ±0.5; all sealed, genus 0; panel/spline/collar pairwise
interference < 1e-6 mm³); failure-shape fixture reproduces every field of the
captured error including last-good metrics; param bounds enforcement at
both part and project scope with stale-part propagation from project-param or
`globals.py` changes; determinism; secure-sandbox denial of introspection-based
filesystem, symlink, process, and network escapes, plus refusal of unsafe mode
under serve and for registry code; source-map resolution for all solids and
tags at the scopes promised by architecture §3.1; addressing-grammar
resolution incl. `#k`/`#*` dedup and candidate-listing errors; tag-descriptor
fingerprinting (a threshold-crossing `tread_top` displacement triggers a
`tag_descriptor_changed` warning with measured deltas and baseline artifact ref,
while an equivalent no-op refactor does not; interleaved current/preview/
failed/raced builds preserve the same baseline; intentional edits and symmetric
selector swaps verify documented false-positive/false-negative limits without
identity claims); performance
budgets for build and measure. Core project-store tests directly exercise
canonical lock ordering, selective `hc` dependency projections, coherent
manifests, authorized snapshots/artifact refs, operation-key uniqueness and
replay, crash injection at every source/build/synthetic-export WAL publication
boundary, external-drift conflict behavior, idempotency keyring rotation,
quota/GC retention (including exports and journals), and stale/failed/preview
publication rejection. These are G0 requirements; G2 later verifies only their
Pi/bridge integration.
`heph build corpus/reference/parts/cat_step_shelf.py --json` exits 0 and its
JSON validates against the BuildResult schema.

## Stage 1 — Render service and grounded observation

Deliverables: `core/render` (offscreen rgb/mask/section/explode, named
cameras, bijective mask palette + legend), `heph render`, GLTF export with
per-solid ids, the `inspect_part` library implementation, and tool-free render-
bundle preparation helpers later consumed by Stage 2 `query_snapshot`. No Pi
session or vision-model query is a Stage 1 deliverable.

**Gate G1** (Tiers 1+2): with Node absent, `uv run pytest tests/stage1
tests/render -q` exits 0:
render goldens for both reference parts at `iso`/`+X` in all channels (SSIM ≥
0.995 across two consecutive CI runs — determinism is part of the gate); mask
decode equals legend exactly; every labeled solid visible in ≥ 1 standard
view; explode(1.0) renders differ from explode(0.0) with strictly increased
silhouette area; GLTF validates (`gltf-validator`) with solid count matching
the build result.

## Stage 2 — Pi agent runtime and CLI-complete product

Deliverables: a TypeScript `agent/` sidecar embedding the pinned
`@earendil-works/pi-coding-agent` SDK; app-owned `ModelRuntime`, credentials,
settings, resources, and persistent sessions; Pi coding tools and ambient
extensions disabled; a CAD-specific system prompt and trusted Hephaestus
extension; streaming event normalization; and the full tool schema of
`tool_schema.md` except run_dfm/generate_drawing/generate_doc/deferred and the
Stage-6-only `nested_sheet` layout mode (`as_built` export is implemented).
Each custom Pi tool proxies through the versioned Python JSON-RPC bridge to
`core/`, including inline image results. Stage 2 implements the production
`query_snapshot` ephemeral, tool-free Pi vision child over Stage 1 render-
bundle helpers. `heph agent` supervises the sidecar
and renders streaming output and `ask_user` without exposing the private
bridge.

Additional deliverables: one persistent Pi session per part, a separate
project-orchestrator session, scoped quick-edit child sessions, and the
context policy of architecture §4.1 (image eviction, CAD-aware compaction,
pinned summaries, budgets). Add pinned thread-phase orchestration for bounded
project decomposition → part delegation → cross-part verification → capped
repair, and use its JobRunner for durable workflow events, replay, and
cancellation. Its application-owned JobStore persists through Python SQLite
over the bridge so the wheel sidecar needs no native Node SQLite addon.
Thread-phase phases invoke the Hephaestus Pi session service directly and use
free-runner patterns, with no AgentAdapter package dependency. Direct
multimodal and single-part paths bypass thread-phase.
Also deliver the six authored registry references (build123d idioms; profiles
& extrusion; booleans & clearances; sheet-goods & joinery; fillets & failure
repair; parts-store usage), a minimal parts store (metric screws, heat-set
inserts), materials (plywoods, PLA/PETG, 6061), and the benchmark harness.
Registry references remain provenance-delimited tool results and MUST NOT be
loaded as privileged Pi extensions or ambient skills.

**Gate G2** (Tiers 1+3): `uv run pytest tests/stage2 -q`, `pnpm --dir agent
test`, and `pnpm --dir agent typecheck` all exit 0. Tests use a scripted fake
model to drive every generated Pi custom tool through the real Node/Python
bridge, including images, `ask_user`, cancellation, process restart, session resume,
and a repair flow off the failure fixture. An event fixture repeats provider
ID `call_0` across distinct persisted assistant entries and proves trusted
invocation IDs remain unique. Contract tests prove the
Python declaration, committed JSON Schema, Pi TypeBox schema, MCP schema, and
`tool_schema.md` do not drift. Session tests prove per-part isolation,
project delegation, quick-edit parentage, one leased cross-process writer per
Pi JSONL with safe stale-owner recovery, app-owned credentials/resources, and
that no built-in coding tool, ambient extension, unapproved provider
environment key, or global config is active. Context tests prove image eviction
and Pi compaction preserve the pinned CAD summary and that a post-compaction
fake model can answer a pre-compaction decision. Tool scheduling tests prove
interactive/mutating tools are sequential; mixed `ask_user`/mutation batches
are preflighted in both source orders, all siblings are blocked, and no
mutation occurs before an answer. Mutation tests drop responses after create/edit/write/parameter/export commits,
retry with the same trusted invocation id, and receive the cached outcome
without duplicate writes; id reuse with another payload fails. First-seen stale
UUIDv7 keys fail, while a recognized key replays after five minutes and through
the 30-day horizon; post-horizon keys fail after outcome/tombstone GC. Crash injection
after blob/journal fsync, `PREPARED`, bundle/export install, current-manifest
or export-pin publication, directory fsync, and `COMMITTED` proves typed startup
recovery returns one deterministic outcome with no partial success. A
non-cooperating external save completed before the final live-hash validation
is detected and preserved as conflict/journal evidence; a separate test injects
a write after validation to demonstrate/document why atomicity is guaranteed
only for cooperating Hephaestus clients.
Optimistic-concurrency tests race edit/write/part-parameter changes, reject
stale hashes without changing bytes, and reconstruct exact attempted candidates
from snapshot refs. Project-parameter and direct-`globals.py` edit races against builds of two
consumers prove changed dependency projections cannot publish stale artifacts
or clear stale state and complete without lock inversion. Changing an `hc`
value consumed only by part A, rebuilding A, and retaining part B's older but
projection-valid artifact produces a coherent project manifest. Project measure/check
rejects a mixed generation until an atomic coherent manifest exists, then
returns/accepts its immutable `project_snapshot_ref`. Two concurrent failed
builds each return distinct artifact/last-good refs that render their own exact
checkpoints. Builds with different transient params have different
effective-parameter hashes and remain non-current previews. Export races freeze
the current successful source artifact (or validate an explicit successful
artifact ref), and returned source/export hashes match the produced bytes.
Explicit targets are create-only and lost-response retries reconcile to the
same source/output without overwrite; automatic/manual GC preserves explicit
and content-addressed successful exports until explicit unpin/delete.
Path tests reject absolute paths, traversal encodings, symlink escapes, and
unintended overwrites, including a parent-symlink swap raced against atomic
no-replace export creation. Output tests page oversized scripts/references and generic >50 KiB tool
artifacts (including a single >50 KiB line) through `read_artifact`, guarantee
cursor progress, cap Pi text at 50 KiB/2000 lines, and prove `query_snapshot`
has no tools/extensions/recursion or persistent session, is single-turn/time/
token bounded, does not inject child images into the parent, and charges usage
to the parent budget. Thread-phase tests prove direct
Pi-session phase invocation, Python-backed durable event replay, bounded
fanout, cooperative cancellation, orphaned-job interruption and checkpoint
recovery, and a capped two-part cross-check/repair workflow while direct
multimodal prompts bypass the workflow layer. Bridge tests enforce every wire/decoded-
data/JSON-depth/member/image/request/prompt/event limit and timeout/overflow
result from architecture §5; reject oversized-dimension/pixel image bombs
before full decode; enforce inspect/section/measure conditional schema rules;
reject a fifth requested view at schema validation; preserve
terminal-event reserve on overflow, and prove cancelling one multiplexed
session leaves another healthy. Bench: corpus v0 aggregate
lower-90% Wilson bound ≥ 0.60 (8 public tasks × ≥3 seeds) with the designated
reference model; `repair-fillet` specifically MUST pass 3/3 seeds. A restricted
≥3-task private gate at ≥3 seeds enforces the same aggregate lower bound without
revealing task-level identity/specification. Pi session
transcripts, normalized Hephaestus events, thread-phase job records, and result
JSON for the public split are archived as ordinary CI artifacts. Private-split
prompts, scripts, images, tool payloads, transcripts, and workflow records go
only to an access-controlled artifact store with retention limits; public CI
receives redacted aggregate counts/rates and leak-scan evidence.

## Stage 3 — MCP server

Deliverables: `server/mcp` via FastMCP — stdio and streamable-HTTP transports
— exposing the tool schema plus `open_project`/`list_parts`; ask_user mapped
to MCP elicitation (fallback: structured content + follow-up call);
`heph serve --mcp`.

**Gate G3** (Tier 1 integration): `uv run pytest tests/stage3 -q` exits 0: a
scripted MCP client (no Hephaestus code on the client side) connects over
stdio, opens the reference project, and completes create → edit → build →
inspect (receives images) → measure → export STEP; the exported STEP
re-imports with matching volume. The stock client sends no custom idempotency
metadata; the server derives mutation keys from MCP session + request id, and a
same-id replay returns the recorded result. Same flow passes over HTTP
transport, where mutating calls carry `Idempotency-Key`. Claude Code configured
with the server completes bracket-101 end-to-end in a
recorded, replayed session committed as a fixture.

## Stage 4 — Web workspace, read-only

Deliverables: `server/http` (project/build/artifact/event APIs over the same
core), `web/` with: project tree, script viewer (Monaco, read-only), Results
panel (geometry list + visibility + properties + check status), three.js
viewport (GLTF, view cube, grid readout, explode slider, section plane), and
live agent-stream panel rendering tool chips, thought sections, images, and
ask_user widgets — visual language may differ from Smith; information
structure MUST match `tool_schema.md` outputs.

**Gate G4** (Tier 2): `pnpm test:e2e` exits 0: Playwright opens the reference
project; DOM assertions — tree row count equals build-result geometry count,
properties panel shows all metadata fields from the script, check badges match
`heph check` JSON; pixel assertions — visibility toggle changes the viewport
within the target solid's mask region, explode(1.0) increases scene-graph
pairwise centroid distances, section plane produces golden-matched render.
An agent session started from CLI streams live into the web panel (event
round-trip test). Screenshot artifacts archived.

## Stage 5 — Interactive editing and provenance UX

Deliverables: script editing in Monaco with rebuild-on-save and dirty
markers from git status; version panel over git log with per-part diff view
and tag-as-publish; param sliders generated from `PARAMS` (bounds, live
rebuild); measure mode (click two features → distance readout via measure
tool); selection: raycast → mask id → source-map resolution → quick-edit
popover ("1 face", resolved tag/label) → scoped agent spawn per architecture
§4.4, with the child transcript threading into the part's agent panel.

**Gate G5** (Tier 2 + Tier 1): Playwright: edit a dimension in Monaco → save
→ viewport updates and new metrics land in Results; slider moves
`groove_count` → rebuild reflects it and out-of-bounds input is rejected
inline; clicking the tagged `tread_top` face opens a popover containing the
string "tread_top" and the creating line number; submitting "add a 2 mm
chamfer to this face" to the quick-edit agent (scripted fake model in e2e;
real model in a recorded fixture) results in an `edit_part` diff visible in
the transcript and a changed golden-region render. Git panel shows the edit
as a dirty state; publish creates a tag (asserted via `git tag -l`).
Concurrency: e2e simulates an agent `edit_part` racing an editor save with a
stale base hash — the conflict surfaces in the editor as a merge prompt and
in the transcript as a failed edit carrying the bounded current raw-content
chunk/hash plus a paging cursor when needed, and no write
is lost: committed state is recoverable from git, overwritten dirty preimages
from `.heph/journal/`, and rejected contender bytes from the conflict payload.

## Stage 6 — Manufacturing depth and ecosystem

Deliverables: `run_dfm` with rule packs for laser_cut (min feature vs kerf,
min internal radius, sheet-thickness match vs materials registry) and fdm
(min wall, overhang angle, min hole); DFM mode auto-run wiring;
`generate_drawing` (dimensioned + exploded, PDF/SVG with title block from
metadata) and `generate_doc` (BOM, assembly instructions); `nested_sheet` DXF
layout; registry publishing guide + `heph registry publish` with content-hash
pinning end-to-end (publish computes the digest; consume verifies it);
corpus expanded to 12 tasks (public/private split maintained) including a
DFM-repair task and a drawing task.

**Gate G6** (all tiers): DFM fixtures with known violations yield findings
with correct rule ids and offending tags (pytest); drawings for the reference
shelf render to PDF whose extracted dimension strings include the five
principal dimensions (pytest + pdf text extraction); nested DXF for the
gusset contains 3 profiles fitting the declared 210×125 blanks (ezdxf
assertions); bench on corpus v1 lower-90% Wilson bound ≥ 0.70 (12 tasks × ≥3 seeds)
with the reference model; a registry-integrity test (tampered registry tree
fails the hash check and refuses to load; a store part attempting file IO is
denied by the sandbox); e2e covers the DFM toggle surfacing findings in the
web panel.

## Stage 7 — Release

Deliverables: the PyPI wheel with its private compiled agent sidecar per
`repo_conventions.md` (no public npm publication is required for v0.1), a
versioned docs site, demo recording script, CONTRIBUTING + registry
contribution guide, issue templates, Apache-2.0 headers, and a model-leaderboard
page generated from bench artifacts.

**Gate G7**: clean-machine matrix tests cover (a) Python-only `pipx install` →
`heph --version` → import/lint/schema smoke with no script execution and no Node
on every packaging lane; (b) core build/check through the secure executor →
full packaged-sidecar integrity/native-addon audit → Python-backed JobStore
initialization → `heph agent` fake-model → Stage-3 MCP smoke on the supported
secure Linux x86_64 lane; and (c) explicit fail-closed agent/server script
execution on lanes without a passing secure backend. The
test MUST prove the wheel uses its packaged sidecar and not a global Pi or
thread-phase installation. The Linux release lane also runs the secure-executor
escape suite. `LEGAL-REVIEW.md` is present at
repo root with its checklist fields completed and signed off (reviewer, date,
scope: ToS analysis of the reference product, reference-fixture publication
decision, trademark scan of identifiers) — CI checks the file's schema; the
review itself is the one deliberately human step in the mission and blocks
only publication, not development; docs build without warnings; `bench.yml`
publishes the leaderboard artifact; all prior gates are green on the release
SHA; tag `v0.1.0` is cut.

---

## Mission-wide rules

1. **Gates are commands.** Every criterion above maps to a CI job; the
   mission tracker links stage → workflow. Ambiguity in a gate is a defect in
   this document and MUST be resolved by tightening the gate, never by
   waiving it.
2. **Evidence is archived.** Bench transcripts, Playwright screenshots, and
   render goldens are CI artifacts; stage completion reports link them.
3. **Reference-model budget.** Tier 3 gates name one reference model per
   mission epoch; changing it re-baselines thresholds explicitly in a PR.
4. **Performance is gated, not aspirational.** The budgets in
   `verification.md` run in Tier 1 from Stage 0 on. Implementation note
   for the executor: per-statement *full* metric snapshots are permitted to
   be lazy (checkpoint the shape reference eagerly; compute metrics on
   failure or on demand) — the budgets are the arbiter, and the failure-shape
   tests only require last-good metrics to be *available*, not precomputed.
5. **Scope discipline.** Deferred items (FEA, STEP import, community
   sharing, kerf-aware auto-nesting) enter only by amending this plan with a
   new gated stage.
6. **Framework boundaries are contractual.** Pi owns individual conversation
   and tool-loop lifecycle; thread-phase owns deterministic multi-session
   workflows; Python core owns geometry; git owns authored design state. No
   stage may introduce a second implementation of those responsibilities or
   make Pi/thread-phase persistence the source of geometric truth.
7. **Pinned, isolated agent dependencies.** Product and CI execution use the
   repository lockfile, app-owned Pi resources, and an allowlisted credential
   environment prepared by the supervisor. Global Pi extensions, coding tools,
   thread-phase pipelines, unapproved credentials, or CLIs MUST NOT affect a
   Hephaestus run.
