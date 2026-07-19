# 04 — Mission Plan

The droid mission implementing Hephaestus. A de-risking spike plus eight build
stages (S, 0–7), with Stage 0 split into strictly ordered 0A/0B gates; each
stage lists deliverables, then its **gate**: the complete, machine-
checkable exit criteria. A droid MAY parallelize within a stage but MUST NOT
begin stage N+1 deliverables before stage N's gate is green in CI; Stage 0B
likewise cannot begin before G0A, and Stage 1 requires G0B. Verifier
tiers reference `verification.md`.

Reading `architecture.md`, `script_contract.md`, and `tool_schema.md`
is prerequisite to Stage 0.

---

## Stage S — De-risking spike

The mission's seven riskiest infrastructure assumptions are converted to
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
termination, and fail-closed capability detection, repeated on macOS through a detected
Docker/Podman/OrbStack-compatible backend running the pinned executor image;
(g) an SBOM/import-graph/provider spike that exact-pins Pi and thread-phase,
audits thread-phase's transitive `openai` SDK (tree-shaken out or explicitly
accepted as proven-inert), enumerates Pi `ModelRuntime` provider support, and
runs one non-Anthropic OpenAI-compatible plus one local endpoint against fake
servers. Production MUST use free-runner phase/pattern APIs and MUST NOT depend on thread-phase's separately
versioned/internal AgentAdapter or Pi-adapter surface.

**Gate GS**: the spike workflow is green in CI on two consecutive runs; the
image tag and exact Python, Node, Pi SDK, and thread-phase versions are
recorded in `repo_conventions.md`, with no semver range in the sidecar manifest;
the provider matrix and transitive-dependency disposition are committed; the Pi/thread-phase test uses only
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

## Stage 0 — Headless durability substrate and CAD kernel

Stage 0 is sequentially split so crash consistency is independently testable
and the CAD milestone is not the first place generic storage semantics are
debugged.

### Stage 0A — `opstore` durability package

Deliverables: top-level Python workspace package `opstore/` with a package
README and typed interfaces for operation-key verification/tombstones, generic
WAL prepare/commit/recovery hooks, content-addressed blob publication, cross-
process leases, durable admission/terminal acknowledgment and suspension, and
reachability/GC over SQLite plus the filesystem. It has no CAD, Pi, thread-
phase, git-policy, or `core/` imports; domain-specific payload validation and
publication policy are deliberately absent.

**Gate G0A** (Tier 1): `uv run pytest opstore/tests tests/stage0a -q` exits 0
with ≥90% line coverage and strict type/lint checks. Property/state-machine and
subprocess tests cover operation-key uniqueness/replay/mismatch, HMAC keyring
creation/rotation/restore failure, every PREPARED/blob-install/fsync/COMMITTED
crash point, identical recovery outcomes, lease liveness and deletion races,
reachability and protected-root quota behavior, tombstone horizons, admission/
terminal acknowledgment reconstruction, and `SUSPENDED_WAIT` release/priority
reacquisition without double counting. Import-graph CI rejects any dependency
from `opstore` to build123d/OCP, `hephaestus.core`, Node, Pi, or thread-phase.
The package README examples execute as tests. Nothing in Stage 0B may merge
until G0A is green.

### Stage 0B — Kernel executor and Hephaestus store adapters

Deliverables: `core/executor` (statement-level incremental execution,
checkpoints, secure OS sandbox plus explicit unsafe debug backend, param
validation, `hc` namespace with dependency tracking, source maps),
`core/kernel` services (metrics, interference, clearance, distance, mass,
sealed/genus), `core/checks` engine, and `core/project_store` adapters that add
canonical project lock order, CAD authorization/provenance, coherent dependency
projections, authorized snapshots/journals, and typed source/build/check/export
publication over `opstore`. Deliver build-result records per contract §8, the
CLI verbs `heph build`, `heph check`, `heph lint`, independently authored
`corpus/public_fixtures/` projects for all ordinary PR tests, and the fixed
isolated private-verifier manifest. Private recovered fixtures are never
available to an ordinary/fork PR worker or vendored into the public tree.

**Gate G0B** (Tier 1): public `uv run pytest tests/stage0b -q` exits 0
without private credentials, covering clean-room fixture projects; the isolated
private verifier separately attaches a signed green reference-parity
attestation to the protected stage SHA (both recovered scripts build unmodified
and match their already-published metrics). The public suite's failure fixture
reproduces every field of the
captured error including last-good metrics; param bounds enforcement at both
part and project scope with stale-part propagation from project-param or
`globals.py` changes; determinism; secure-sandbox denial of introspection-based
filesystem, symlink, process, and network escapes, plus refusal of unsafe mode
under serve and for registry code; source-map resolution for all solids and
tags at the scopes promised by architecture §3.1; addressing-grammar resolution
including `#k`/`#*` dedup and candidate-listing errors; and tag-descriptor
fingerprinting (a threshold-crossing `tread_top` displacement warns with
measured deltas/baseline ref, an equivalent no-op does not, interleaved current/
preview/failed/raced builds preserve the baseline, and selector-swap fixtures
exercise documented false-positive/false-negative limits without identity
claims). Build/measure performance budgets apply.

Adapter integration tests cover canonical lock ordering, selective `hc`
dependency projections, coherent manifests, authorization, exact attempted
snapshots, external-drift conflicts, typed crash recovery at every source/build/
check/synthetic-export publication boundary, quota/retention policy, immutable
check-bundle provenance, and stale/failed/preview publication rejection. They
also enforce that CAD policy remains in `core/project_store` while generic WAL,
lease, admission, and GC machinery is imported from—not reimplemented beside—
`opstore`. G2 later verifies Pi/bridge integration rather than repeating G0A's
generic crash matrix. A dedicated `g0b-no-node` image containing Python/core but
no Node runs `heph build corpus/public_fixtures/assembly/primary.py --json`; it
exits 0 and validates against the BuildResult schema.

## Stage 1 — Render service and grounded observation

Deliverables: `core/render` (offscreen rgb/mask/section/explode, named
cameras, bijective mask palette + legend), `heph render`, GLTF export with
solid/face/edge selection IDs plus immutable linked selection bundle, the
`inspect_part` library implementation, and tool-free render-
bundle preparation helpers later consumed by Stage 2 `query_snapshot`. No Pi
session or vision-model query is a Stage 1 deliverable.

**Gate G1** (Tiers 1+2): with Node absent, `uv run pytest tests/stage1
tests/render -q` exits 0:
render goldens for public clean-room fixtures at `iso`/`+X` in all channels
(SSIM ≥ 0.995 across two consecutive CI runs—determinism is part of the gate);
the isolated verifier adds a signed aggregate private-reference render-parity
attestation without exposing images or logs; mask
decode equals legend exactly; selection-mode artifacts use separate palette-exact non-antialiased solid/
face/edge passes, map every selectable ID to kind/solid/topology index and exact
build ref, include untagged faces/edge overlays, and bind equivalent GLTF
raycast IDs to the selection bundle; every per-view bundle and solid/face/edge
pass ref round-trips through selection resolution after a newer build is
published; every labeled solid is visible in ≥ 1 standard
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
The project-orchestrator tool set includes constrained CAS/WAL APIs for
`globals.py` and `checks/*.py` plus explicit part-agent delegation; part and
quick-edit sessions do not receive them. Each custom Pi tool proxies through the versioned Python JSON-RPC bridge to
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
environment key, or global config is active. A fresh-project scripted session
uses only model-visible tools to edit shared globals, create two consuming
parts, discover/create/edit a persistent cross-part check, and delegate work; prompt
delegation returns child terminal evidence, bounded timeout/cancellation leaves
no orphan, queued follow-up transitions are observable through status, and queued/completed/child-failed/pre-admission-
rejected/overflow/timed-out/cancelled/interrupted/idempotent-replay variants are
covered; every admitted state carries one stable child ID, queued/running
follow-ups reserve admission slots while queued, can be cancelled by delegation
ref, reject >32 KiB UTF-8 prompts via the cross-language custom schema keyword
without truncation, reject lone surrogates consistently, distinguish NFC/NFD
payload bytes for idempotency, and enforce default/
configured/max child deadlines plus +60 s terminal-cleanup grace are enforced. Crash injection before enqueue, after stable child
admission, after dispatch, after child terminal, and before parent response
replays to at most one child; ADMITTED recovery takes precedence over generic
interruption, child-terminal projection wins atomically over cancellation/deadline races,
deadline produces only `timed_out`, unrecoverable owner loss only `interrupted`,
and persisted CANCEL_REQUESTED recovers only to `cancelled` with no redispatch; unavailable foreign session routing returns `session_busy`;
scope tests
prove those project tools are absent from part/quick-edit sessions. Object-
scope tests prove part/quick-edit sessions cannot read, create, mutate, build,
or parameterize another part even by supplying its name, and reject nameless
`set_params(scope="project")` / `run_checks(scope="project")`. Context tests prove
image eviction
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
recovery returns one deterministic outcome with no partial success. Terminal
crash tests stop before persistence, after idempotent terminal insertion, and
after acknowledgment, proving one terminal per stable run ID and no duplicate
synthesized interruption. A
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
effective-parameter hashes and remain non-current previews. Explicit
single-part measurement against that preview reports its artifact ref, while
default measurement still resolves current; cross-part selectors require a
project snapshot and reject simultaneous single-artifact selection. Preview
DFM targeting is deferred to G6 with `run_dfm`. Export races freeze
the current successful source artifact (or validate an explicit successful
artifact ref), and returned source/export hashes match the produced bytes.
Explicit targets are create-only and lost-response retries reconcile to the
same source/output without overwrite; automatic/manual GC preserves explicit
and content-addressed successful exports until explicit unpin/delete; pinning
GLTF/selection refs transitively retains linked bundles/passes/source builds. A check-set capture paused between files while edit/create races proves each
CheckReport freezes one complete old or new generation, reports
`check_set_generation` plus bundle ref/hashes, and keeps that bundle reachable
through report retention/GC. A stable direct-filesystem change is reconciled into one `external_import`
generation before discovery/run, while an actively changing tree returns
`check_set_drift`; neither publishes changed content under an old generation. Crash between check-file
rename and generation publication recovers exactly one new generation; a
surviving process acquiring the check-set lock must resolve PREPARED before it
can list/run/edit checks. Check discovery paginates a frozen generation
losslessly past the context cap while concurrent edits create a new generation.
A malformed stable external import returns only
`invalid_check_generation` diagnostics and project checks fail closed rather
than omitting it. A globals-edit/
`set_params` race follows project lock order; changed PARAMS are validated
against persisted overrides and invalidated overrides block the edit until
explicitly cleared/replaced. Malformed globals/check candidates exercise syntax/contract/sandbox/evaluation
diagnostics with unchanged bytes; stale-CAS and current-hash invalid-override
failures validate as distinct conflict versus validation-error schemas. Path
tests reject absolute paths, traversal encodings, symlink escapes, and
unintended overwrites, including a parent-symlink swap raced against atomic
no-replace export creation. Output tests page oversized scripts/references and generic >50 KiB tool
artifacts (including single >50 KiB part/globals/check/skill lines) signal
`oversized_line` in reads and stale-conflict variants, and continue all ordinary/truncated and conflict-time pages only from returned absolute byte
cursors on immutable snapshot refs through `read_artifact`, even when paging
starts after line 1 or another edit lands; reject every non-boundary byte offset
inside multibyte UTF-8 without normalization and guarantee emitted cursor
progress; cap Pi text at 50 KiB/2000 lines, and prove `query_snapshot`
has no tools/extensions/recursion or persistent session, is single-turn/time/
token bounded, does not inject child images into the parent, and charges usage to the parent
budget. Capability tests use the active image model, fall back to configured
vision model for a text-only active model, and return schema-valid discriminated
`image_model_required` / `capability_not_available` outcomes when needed. Thread-phase tests prove direct
Pi-session phase invocation, Python-backed durable event replay, bounded
fanout, cooperative cancellation, orphaned-job interruption and checkpoint
recovery, and a capped two-part cross-check/repair workflow while direct
multimodal prompts bypass the workflow layer. Saturation starts 16 orchestrators
that each make one synchronous delegation and proves parent suspension admits
all children, all parents resume, and no run times out from slot starvation;
fanout never exceeds derived available admission capacity. Bridge tests enforce
every wire/decoded-
data/JSON-depth/member/image/request/prompt/event limit and timeout/overflow
result from architecture §5; reject oversized-dimension/pixel image bombs
before full decode; enforce inspect/section/measure conditional schema rules;
reject a fifth requested view at schema validation; preserve
terminal delivery under stalled consumption: 16 concurrent runs each produce
exactly one durably acknowledged terminal event; completed-but-unacknowledged
runs retain their admission slots, and admission/terminal-ack rows survive restart; a seventeenth—including with 16
queued or completed-but-unacknowledged rows—returns `busy` until durable,
idempotent acknowledgment releases a slot; progress-event floods coalesce only
declared droppable deltas while preserving every audit/tool/question/terminal
event; and cancelling one multiplexed session leaves another healthy. Provider
plumbing runs the fake non-Anthropic OpenAI-compatible and local endpoints
selected in Stage S. Bounded historical-session reads freeze a high-water
cursor, normalize through the sidecar, and reconstruct the same public events
after restart without Python parsing Pi JSONL. Bench: corpus v0 aggregate
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
stdio, opens a public clean-room fixture project, and completes create → edit → build →
inspect (receives images) → measure → export STEP; the exported STEP
re-imports with matching volume. The stock client sends no custom idempotency
metadata; the server derives mutation keys from MCP session + request id, and a
same-id replay returns the recorded result. The same stock-client flow passes
over streamable HTTP with MCP session/request identity and no REST-only header;
optional MCP `_meta` is tested separately. A table-driven parity suite sends
the same mutation/replay, stale-conflict, object-scope denial, and ordinary plus
single-line >50 KiB paging cases through Pi→bridge→core and FastMCP→core, then
asserts equivalent outcomes, hashes, cursor reconstruction, and errors—not only
schema equality. Claude Code configured
with the server completes bracket-101 end-to-end in a
recorded, replayed session committed as a fixture.

## Stage 4 — Web workspace, read-only

Deliverables: `server/http` (project/build/artifact/event APIs over the same
core), `web/` with: project tree, script viewer (Monaco, read-only), Results
panel (geometry list + visibility + properties + check status), three.js
viewport (GLTF, view cube, grid readout, explode slider, section plane), and
live agent-stream panel rendering tool chips, thought sections, images, and
ask_user widgets. Visual language may differ from Smith. Each rendered tool
chip has stable `data-tool-name`/`data-status` attributes and one `data-field`
node for every schema-required output field/reference present in its fixture;
field completeness is asserted mechanically against normalized event JSON.

**Gate G4** (Tier 2): `pnpm test:e2e` exits 0: Playwright opens a public clean-
room fixture project; DOM assertions — tree row count equals build-result geometry count,
properties panel shows all metadata fields from the script, check badges match
`heph check` JSON; pixel assertions — visibility toggle changes the viewport
within the target solid's mask region, explode(1.0) increases scene-graph
pairwise centroid distances, section plane produces golden-matched render.
An agent session started from CLI streams live into the web panel (event
round-trip test). Reopening the project loads a multi-page historical transcript
through the normalized snapshot API, preserves quick-edit parent/child
threading, and matches the previously archived event IDs. Screenshot artifacts
archived.

## Stage 5 — Interactive editing and provenance UX

Deliverables: script editing in Monaco with rebuild-on-save and dirty
markers from git status; version panel over git log with per-part diff view
and tag-as-publish; param sliders generated from `PARAMS` (bounds, live
rebuild); measure mode (click two features → distance readout via measure
tool); selection: raycast → artifact-bound selection id/table → source-map
resolution → quick-edit
popover ("1 face", resolved tag/label) → scoped agent spawn per architecture
§4.4, with the child transcript threading into the part's agent panel.

**Gate G5** (Tier 2 + Tier 1): Playwright: edit a dimension in Monaco → save
→ viewport updates and new metrics land in Results; slider moves
`groove_count` → rebuild reflects it and out-of-bounds input is rejected
inline; clicking the tagged `tread_top` face opens a popover containing the
string "tread_top" and the creating line number. The test renders artifact A,
publishes B, then clicks A's mask and proves crop/provenance still resolve
against A; the inspection response reports A as `source_artifact_ref` even when
current changes, and solid/selection mask domains remain mode-correct with or without `focus`.
Oversized selection legends stay bounded inline and page losslessly via
`mask_legend_ref`; four views return at most four inline composite previews
while all twelve machine-ID passes are artifact refs; each pass contains only
published palette values, and schema
requires selection refs only in mask-selection mode. GLTF raycast selection is accepted only through its immutable linked bundle.
Each returned per-view `bundle_ref` and its solid/face/edge pass refs is submitted
as `selection_artifact_ref` and resolves through A's immutable link after B is
published. Solid, untagged-face, and edge selections resolve through A's
table, while RGB/wrong-mode, mismatched, or expired refs return
`stale_selection`.
Submitting "add a 2 mm
chamfer to this face" to the quick-edit agent (scripted fake model in e2e;
real model in a recorded fixture) results in an `edit_part` diff visible in
the transcript and a changed golden-region render. Git panel shows the edit
as a dirty state; publish creates a tag (asserted via `git tag -l`).
REST mutation tests reject a missing `Idempotency-Key` and replay a recognized
key, independently of MCP-over-HTTP. Concurrency: e2e simulates an agent
`edit_part` racing an editor save with a
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
with correct rule ids, offending tags, and resolved source artifact (pytest);
a transient preview is checked explicitly while default DFM still resolves the
current artifact; findings report source artifact and artifact-bound topology
descriptors rather than bare mask IDs; drawings for the reference
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
secure Linux x86_64 lane; (c) the same fake-model/MCP smoke and executor escape
suite on a macOS lane using a detected Docker/Podman/OrbStack-compatible
backend; and (d) explicit fail-closed agent/server script execution on lanes
without a passing secure backend. The
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
   `verification.md` run in Tier 1 from Stage 0B on. Implementation note
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
8. **Private evidence is never a fork-PR dependency.** Ordinary PR gates use
   only public clean-room fixtures. Restricted parity runs a fixed networkless
   verifier on a protected SHA, exposes no repository credential to tested code,
   emits no raw logs/coverage/cache/artifacts, and returns only a signed
   aggregate leak-scanned attestation; `pull_request_target` is forbidden.
