<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

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

## Stage 2V — Validation ladder

Amendment (2026-07-26, maintainer-directed) under mission rule 5. Stage 2
closed the verification loop (did the agent build what it intended?) but
measured evidence shows it is self-referential: agents author `CHECKS` that
encode their own misreading, pass them, and stop. This stage adds
**validation** — was the intention correct? — as an escalating ladder in which
**every rung fires by rule, not by model choice**. `VALIDATION.md` is the
normative specification; the summary here is its gate.

Deliverables: (a) corpus `spec: prose|seeded` variants with separately
baselined split scoring; (b) the requirement ledger (`specified`/`derived`/
`assumed` entries, ledger-cited CHECKS thresholds, `heph lint` unsourced-
constant rules); (c) a rule-enforced clarification gate that refuses
`build_part` on material unresolved assumptions and demands concrete-option
questions; (d) automatic unrequested post-build critique (pairwise
interference, manifold, prompt-number diff); (e) a blocking independent
termination reviewer child (request verbatim + ledger + multi-view/section
renders + scripts + metrics, and explicitly NOT the agent's own CHECKS)
returning per-requirement pass/fail/unverifiable with the catching channel;
(f) the bounded continuation ladder (≤3 cycles, same-failure-twice escalates
to `ask_user`, `unresolved_requirements` terminal, never-green-with-open-
requirements invariant); (g) a non-committal bench answerer with asking
scored; (h) the §8 metric suite.

**Gate G2V**: as specified in `VALIDATION.md` §Gate G2V — `uv run pytest
tests/stage2v -q` exits 0 with every listed clause covered, the recorded
`bracket-101` seed-2 misread fixture MUST trigger the prompt-number diff, and
all prior gates stay green. The prose-split Tier 3 threshold is unchanged and
remains the historical baseline; the seeded split is baselined on first
measurement and is never compared against pre-amendment numbers.

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

## Stage ordering amendment (2026-07-26, maintainer-directed)

Under mission rule 5, the stage ORDER changes; no gate, threshold, or
deliverable is removed or weakened. Rationale: the engine-first invariant
(`architecture.md` §2, `README.md`) already makes the CLI + MCP server the
product and the web UI one client among several. Every line of the ~43 kLOC
built so far is headless, so the functional component can ship — and be
deployed as an agent inside any MCP environment — before any UI exists.

**New order:** Stage 2V → G2 closure → **Stage 6** → **Stage 7H (headless
release)** → Stage 4 → Stage 5 → Stage 7 (full release).

Consequences, all recorded rather than assumed:

- Stage 6 is engine work and moves ahead of the UI stages unchanged, EXCEPT
  its one web-dependent clause — "e2e covers the DFM toggle surfacing findings
  in the web panel" — which defers to G4/G5 and is struck from G6. G6's
  pytest/ezdxf/pdf/bench clauses are unaffected.
- Stages 4 and 5 keep their deliverables and gates verbatim; only their
  position moves. `server/http` lands with Stage 4 as before — it is a web
  client API, not part of the headless surface.
- Stage 7 splits: 7H ships the headless artifact; 7 ships the complete
  product. Neither relaxes G7's clean-machine matrix.

## Stage 7H — Headless release (v0.1.0-headless)

The deployable functional component: Python wheel, `heph` CLI, MCP server,
and the packaged agent sidecar — no web UI, no browser dependency.

Deliverables: the PyPI wheel with its private compiled sidecar per
`repo_conventions.md` (integrity-checked, never a global `pi`/`thread-phase`),
a headless docs set (install, `heph` verbs, MCP client configuration, project
conventions, registry pinning), the model-leaderboard page generated from
bench artifacts, CONTRIBUTING + registry contribution guide, and Apache-2.0
headers.

**Gate G7H** (as amended 2026-08-13, below): clean-machine matrix lanes as
specified in G7 —
(a) Python-only `pipx install` → `heph --version` → import/lint/schema smoke
with no script execution and no Node; (b) core build/check through the secure
executor → packaged-sidecar integrity/native-addon audit → Python-backed
JobStore initialization → `heph agent` fake-model → MCP smoke on the supported
secure Linux x86_64 lane; (d) explicit fail-closed
agent/server script execution on lanes without a passing secure backend — on
macOS the product refuses script execution by design in v0.1. The
test MUST prove the wheel uses its packaged sidecar. The Linux release lane
also runs the secure-executor escape suite. Gates GS, G0A, G0B, G1, G2, G2V,
G3 and G6 are green on the release SHA; headless docs build without warnings;
`bench.yml` publishes the leaderboard artifact; tag `v0.1.0-headless` is cut.
`LEGAL-REVIEW.md` is NOT a G7H blocker: it gates publication of the private
reference fixtures and the full release, not the headless tool.

**G7H amendment (2026-08-13, operator decision).** v0.1.0-headless supports
secure script execution on **Linux x86_64 via probed bubblewrap ONLY**. Lane
(c) — the same fake-model/MCP smoke and executor escape suite on a macOS lane
through a capability-tested OCI backend — is **DEFERRED to the post-v0.1
roadmap** and is recorded as a named deliverable of Stage 7 (full release),
not dropped. Lanes (a), (b) and (d) keep their wording verbatim; lane (d)'s
fail-closed clause now explicitly covers macOS ("on macOS the product refuses
script execution by design in v0.1"). This is a tightening, not a waiver:
lane (a) still runs on macOS, `heph agent`/serve on macOS refuse rather than
run unsandboxed, and `tests/stage7h/test_lane_fail_closed.py`
(`test_bwrap_is_still_the_only_secure_backend`) fails the day an OCI backend
lands without this amendment being revisited. The deferral text is pinned in
`tests/stage7h/CI_ONLY.md` §3 and by
`tests/stage7h/test_release_lanes.py`, so silently resurrecting lane (c) and
silently forgetting macOS both fail tests.

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

**G4 status (2026-08-28): CLOSED.** Every clause is green in CI on
`2529d13` (run 33197851560), the first run in which the gate's own command
executed on a machine other than the maintainer's. `pnpm --dir web test:e2e`
passes 14/14 inside the pinned CI container image
(`docker/ci/Dockerfile`, consumed by digest in ci.yml's `render goldens
(pinned image)` job), against a real `heph serve --web` on the public
clean-room fixture `corpus/public_fixtures/workspace/`, with the scripted
model outside the served process. Landing that image also ended the Stage S
deferral of `tests/render`: G1's golden corpus (25 tests) and the G4.7
section golden now run in CI beside it, re-baselined inside the image
(`llvmpipe (LLVM 20.1.2, 256 bits)`, Mesa 25.2.8) by the sanctioned
`heph goldens --update` path. An independent verifier read every covering
assertion rather than trusting names and reported 19/20 clauses green with
one uncovered — mission rule 1's CI mapping for the browser gate — which
this run closes. `INTERFACE.md` is the design spec the deliverables were
built from; its §16 carries the deliverable-to-clause map.

**Not claimed by G4, recorded 2026-08-28.** A product review of the running
workspace found four gaps that are surface the gate never named: no prompt
composer, no export path, no provider sign-in, and no design system. The
first and last are Stage 4 surface and are owed under this gate's
deliverable text; the other two require a new gated stage. See
`docs/workspace-plan.md` and `INTERFACE.md` §0.2, §7A, §22, §23. A green G4
is not a claim that the workspace is finished.

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
denied by the sandbox). The DFM-toggle web-panel e2e clause defers to G4/G5
under the 2026-07-26 ordering amendment.

**G6 status (2026-08-13): CLOSED.** Every clause is green, including the
Tier 3 corpus-v1 bench measurement: the archived clean sweep
`bench/results/gpt-5.6-sol/2026-08-13.json` records prose 30/36
(pass rate 0.833), **Wilson lower-90% 0.7396 ≥ 0.70, `meets_gate: true`**,
seeded 35/36 (0.9116), interpretation gap 0.139, harness_error_rate 0/72.
The bar was never moved: the 2026-07-29 attempt measured 0.5894 and was
recorded as NOT MET; the gap between the two runs is the audited chain of
harness/contract defects fixed in between (bounded compare, deliverable-
and declared-scope grading, uncharged harness faults, the loud part.*
metadata contract, and the build record carrying the worker's runtime
metadata — commits 1016b2e..8be179c), every one regression-tested. All
seven residual failures in the closing sweep are budget overruns, zero
correctness or harness failures.

**Corpus-v2 (2026-08-25, operator decision — post-closure, not a gate
amendment).** The public corpus grows from 12 to 16 tasks with four additions.
The ingest pair is the two shapes `INGEST.md` §2 names as the substrate for
external benchmarks: `flange-edit` (editing — a seeded vendor STEP under
`imports/`, acceptance measured with `m.diff` against the import per
`COMPARE.md` §2, which required wiring the Stage 8A import resolver into
project-scope `run_checks`; previously the promised predicate was unresolvable
at grade time) and `plate-from-drawing` (generation — a seeded drawing image
under `references/`, the vision-citation ledger path of `VALIDATION.md` §2).
The assembly pair, `hinge-mate` and `shaft-coupler`, is the first corpus
coverage of `ASSEMBLY.md` §3 constraint grading (declared fits holding, scored
through the engine path). Every addition ships prose and seeded variants, a
reference solution and an independent second solution, and hand-count-derived
budgets per the 2026-08-25 measured-budget policy (no observe-mode journal
data exists for new tasks; each task.json's `notes` carries the derivation).
Nothing about G6 moves: its evidence stands as measured over corpus v1,
`aggregate_threshold` still keys on the v1 coverage (a superset sweep reads
the same 0.70), and no archived artifact is re-scored. The corpus-count pins
in `tests/stage6` and `server/tests/test_bench_corpus.py` are repointed to
sixteen with this decision cited.

## Stage 7 — Release

Deliverables: the PyPI wheel with its private compiled agent sidecar per
`repo_conventions.md` (no public npm publication is required for v0.1), a
versioned docs site, demo recording script, CONTRIBUTING + registry
contribution guide, issue templates, Apache-2.0 headers, and a model-leaderboard
page generated from bench artifacts. Named deliverable carried in from the
G7H amendment (2026-08-13): **macOS secure script execution via a
capability-tested Docker/Podman/OrbStack-compatible OCI backend** running the
pinned Linux executor profile — G7 lane (c) below — deferred out of
v0.1.0-headless and owed by this stage.

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

## Stage 8 — Frontier capability (amendment 2026-07-27, maintainer-directed)

Priority decision recorded: the optimal CAD harness outranks the soonest
release, so Stage 7H (headless packaging) moves AFTER Stage 8 and ships a
stronger tool. Stage 8 lands in four gated sub-stages, each with its own
normative spec; the module reshape (hephaestus.geom / hephaestus.contract /
hephaestus.bench, commit 3669a7a) is its foundation.

- **8A — Ingest** (`INGEST.md`): `import_step` as an expression term with
  harness-resolved reads and content-addressed inputs; operator-supplied
  reference documents/images with ledger-citable provenance. Gate G8A per
  `INGEST.md`.
- **8B — Solid comparison**: shape/interface/topology diff in
  `hephaestus.geom` serving import round-trips, regression diffing, and
  external-benchmark scoring. Spec to be committed with the stage.
- **8C — Assemblies and constraints**: mates/joints as declared constraints
  that must hold, replacing post-hoc interference discovery. Spec to be
  committed with the stage.
- **8D — External evaluation**: a CADGenBench adapter (generation via
  reference images, editing via STEP import), submission packaging and
  scoring, plus the clean corpus-v1 re-run that closes G6's bench clause.
  The external benchmark is the gate — a corpus we did not author cannot
  fall into the reproduction trap the 2026-07-26 audit closed.

## Stage 9 — Kinematics and motion (amendment 2026-08-26, maintainer-directed)

Priority decision restated: Stage 9 is frontier-capability work under the same
engine-first decision recorded for Stage 8 — the optimal CAD harness outranks
the soonest release. Normative spec: `KINEMATICS.md` (posed evaluation of
declared joints — no placement solver, no dynamics; authored positions stay
authored). Stage 9 lands in three gated sub-stages, strictly ordered:

- **9A — Joints and posed evaluation** (`KINEMATICS.md` §1–§3): joint and pose
  sets as generational project state, pure forward kinematics in
  `hephaestus.geom.kinematics`, engine `MotionStatus`, and 8C constraints
  evaluated at named poses. Gate G9A: `uv run pytest tests/stage9a -q` exits 0
  per `KINEMATICS.md` "Gates"; existing suites stay green.
- **9B — Motion checks** (`KINEMATICS.md` §4, §6): sampled sweeps with the
  closed five-verdict vocabulary, `m.at_pose`/`m.sweep` in project-scope
  checks, posed-scene renders, and the reviewer's motion-blocking rule. Gate
  G9B: `uv run pytest tests/stage9b -q` exits 0 per `KINEMATICS.md` "Gates".
- **9C — Couplings and the mechanism bench** (`KINEMATICS.md` §5, §6): linear
  joint couplings and the corpus v3 mechanism tasks with their own Tier 3
  splits. Gate G9C: `uv run pytest tests/stage9c -q` exits 0 per
  `KINEMATICS.md` "Gates".

## Stage 10 — Workspace egress and provider attachment (amendment 2026-08-28, maintainer-directed)

Recorded on the product owner's review of the running Stage 4 workspace. Two
capabilities the workspace lacks are product decisions rather than UI
additions, and mission rule 5 requires each to enter by a new gated stage
rather than by widening G4 or G5. G4 and G5 are unedited. Normative spec:
`INTERFACE.md` §22 and §23. Stage 10 lands in two gated sub-stages, strictly
ordered.

- **10A — Egress** (`INTERFACE.md` §22): `export_part`, `generate_drawing` and
  `generate_doc` as keyed REST mutations replaying from the existing
  `tp_exports` WAL; a `tp_exports` projection; a blob-addressed download route
  authorized by a `COMMITTED` row; and an `ExportPanel` bound to the workspace
  pin. Prerequisite, landing in Stage 4: the artifact kind is bound to the
  blob, so `/artifacts/{ref}/bytes`'s enumeration constrains reachability and
  not only labelling.

  **Gate G10A** (Tier 2): `pnpm test:e2e` exits 0 — Playwright pins artifact A,
  exports STEP from the pin, and asserts the downloaded bytes' sha-256 equals
  the `export_hashes` entry the route returned; publishes build B for the same
  part; re-exports from the still-pinned A and asserts the same digest, and
  that a `null`-ref export is not reachable from the client. A DXF export of
  the same pin asserts `kerf.source == "dfm"` and `applied_mm == 0.2` from the
  process pack. `GET /artifacts/{ref}/bytes` refuses the export's ref **and**
  refuses a `build`-relabelled ref naming the same blob. An export with no
  `Idempotency-Key` is `400 idempotency_key_required` with no file created; the
  same key twice yields one file and `"replayed": true`; the same key with a
  changed format yields `key_payload_mismatch`. `heph build` on the fixture,
  then a `gc.collect()`, leaves the exported blob and its source build blob
  both reachable. `heph export list` and `heph export unpin BLOB` exist and are
  exercised.

- **10B — Provider attachment** (`INTERFACE.md` §23): an agent runtime
  attachable to a running serve; provider specs writable from the workspace
  **without** the credential allowlist or `auth_source`; API-key and
  subscription-OAuth sign-in relayed to Pi, which remains the sole credential
  store; per-provider fail-closed verification; and a `ProvidersPanel` whose
  source and health axes are never collapsed.

  **Gate G10B** (Tier 2 + Tier 1): `pnpm test:e2e` exits 0 — serve a project
  with **no** `providers.json`; the panel renders `agent_unavailable` by name;
  provider specs are written and a runtime is attached without restarting the
  process; a provider is configured against a scripted `FakeModel`; a session
  then runs and streams into the panel; sign-out returns the panel to `none`
  and the session routes to `agent_unavailable`. Tier 1: the web path **cannot**
  add a name to `credential_allowlist` (refused by name), and a variable outside
  the allowlist never reaches the sidecar's environment; a sentinel credential
  literal appears nowhere in the opstore, the archived event goldens, the
  sidecar `stderr_tail`, or the bench evidence bundle, including under a
  scripted OAuth fixture whose token endpoint returns the sentinel in its
  response body; and the process holds exactly one listening socket after a
  full OAuth flow.

**The open question this amendment carried, and the ruling that closed it on the
same day.** The amendment as drafted carried one question forward — whether the
workspace may **discover** a Pi `auth.json` outside the project root and offer it
as a credential source — on the ground that mission rule 7's approval mechanism
is a supervisor-prepared allowlisted environment and that a spec section may not
decide a mission-wide rule by argument. The operator ruled on it in the same
2026-08-28 review, in these words:

> "The server should be able to work locally, the same way that Claude for
> science works."

**Ruling: approved, with binding constraints, and it enters as its own gated
sub-stage.** The server MAY enumerate the operator's existing home-directory
credential sources and **offer** them. Discovery is an **offer, never a silent
adoption**; a secret is **never** echoed to the client, logged, or placed in a
URL, an event, or an artifact; the serve stays **loopback-only**; anything the
server writes is mode **0600**; and **mission rule 7 is unchanged and still
forbids ambient provider keys reaching a run unapproved** — the credential
allowlist remains supervisor-prepared and is not web-writable. The ruling grants
a ceiling, not a floor: `INTERFACE.md` §15.41's "no masked key tail" refusal is
stricter than the ceiling and is **not** relaxed by this approval.

- **10C — Credential discovery** (`INTERFACE.md` §23.5): an explicit
  enumeration route that describes each discovered source **without** its
  secret — kind, provider id, model ids, source path — and an adoption route
  that takes effect only on a request **naming** the discovered source. Strictly
  after 10B, because a discovered source is worthless without the attach path
  10B builds.

  **Gate G10C** (Tier 2 + Tier 1): `pnpm test:e2e` exits 0 — serve a project
  with no `providers.json` beside a scripted home-directory Pi `auth.json` and a
  scripted local OpenAI-compatible endpoint; the panel lists both by kind,
  provider id, model ids and source path, and the response body carries **no**
  secret material and **no** masked key tail; a session before adoption routes to
  `agent_unavailable`, byte-identically to the run with nothing discovered; one
  explicit adoption request naming a discovered source configures it; and
  `providers.json` afterwards **names every credential source in use**, at mode
  `0600`. Tier 1: no credential path outside `<project>/.heph` is read unless
  `providers.json` already names it or the operator's adoption request named it;
  no discovery runs on panel mount or on a timer; every `/providers/**` route
  refuses `not_loopback` off a loopback bind; discovery adopts **no** ambient
  environment variable and the web path still cannot add a name to
  `credential_allowlist`; and the §23 sentinel-leak grep is extended to the
  discovered file's secret, which appears nowhere in the opstore, the archived
  event goldens, the sidecar `stderr_tail`, or the bench evidence bundle.

## Stage 11 — The component store (amendment 2026-08-29, operator-directed)

Frontier-capability work under the engine-first decision recorded for Stage 8 —
the optimal CAD harness outranks the soonest release. Recorded on the operator's
2026-08-29 approval of the recommended build order in
`docs/frontier-staging-proposal.md`, which puts the component store first of the
five frontier capabilities and opens it as its own gated stage under rule 5.
Normative spec: `PARTS_STORE.md` (the existing `parts` registry kind gains a
validated component record, tagged mounting interfaces the consuming script can
anchor 8C constraints and Stage 9 joints to, and a datasheet provenance
discipline — no new registry kind, no new tool, no geom service, no solver, no
inertia, no vendor payload). Stage 11 lands in three gated sub-stages, strictly
ordered.

- **11A — the component record** (`PARTS_STORE.md` §1, §4–§6, §8): a validated,
  closed-vocabulary component record replacing the opaque `params` blob;
  well-formedness refusals for class, interface, mass, performance-curve and
  datasheet data; the `license` field made required at parse;
  `duplicate_registry_kind` replacing the silent second-registry drop; the
  publish-time `vendored_third_party_payload` and `trademark_in_component_id`
  scanners; `heph registry components`; and the `geom_type` worker-protocol field
  §2.3 needs.

  **Gate G11A** (Tier 1): `uv run pytest tests/stage11a -q` exits 0 per
  `PARTS_STORE.md` "Gates" — 24 clauses. Legacy fragment-**body** invariance and
  digest honesty are separate clauses: a legacy part's fragment is byte-identical
  to its golden *after the `# registry: … @ <digest>` line is elided*, and the
  elided digest must equal the recomputed Merkle root. Whole-fragment byte
  identity is not asserted and cannot be — the header carries the tree's root,
  which this stage's own `part.json` edits move, and the earlier "byte-for-byte
  including their fragments" claim was false and is withdrawn. Also: every named
  record refusal, each naming what it refused; `param_schema_drift` refused at
  index **and** at publish; contract drift with the 53-tool count **unchanged**
  and the record-only result fields dispatched by both profiles; seam invariance
  (the geom import-boundary tests enumerate exactly the nine existing pure
  services — this stage adds none); worker-protocol drift with `geom_type` on
  every `tag_fingerprints` entry and out-of-set values refused at parse; tamper
  refusal and `publication_drift` naming exactly the modified file; the runtime
  sandbox refusal re-asserted against a component generator's **body** region;
  `heph registry components [--json]` byte-identical across two processes; and
  determinism of every refusal reason and detail.

- **11B — mounting interfaces as tagged geometry** (`PARTS_STORE.md` §2): a
  fourth generator marker region under an exact AST contract, selectors rooted at
  the published shape and evaluated **after** placement, instance-scoped
  `__`-infix tag names whose re-tagging is a refusal rather than last-wins, and
  declared-class verification at the caller's `pos`.

  **Gate G11B** (Tier 1): `uv run pytest tests/stage11b -q` exits 0 per
  `PARTS_STORE.md` "Gates" — 21 clauses, including `interface_region_violation`
  enumerated against the AST contract rather than against the word "nested",
  with the canonical region parsing clean as its negative control; the
  `interface_body_local_reference` refusal, without which the post-placement
  rewrite leaves a body local in the unplaced frame and the selector resolves to
  a real face that is the wrong one; record ⇄ region interface-name set equality
  in both directions; placement resolution at a non-trivial translation **and**
  rotation, with a deliberately body-local-rooted fragment failing to resolve so
  the clause has teeth; `interface_not_placed` firing in the **consumer's** build
  where a hand-authored tag still only warns; file IO in the interface region
  refused at index time and therefore before any such tree can be published or
  pinned; the five-row class decision table verified positively and negatively;
  `interface_placement_drift` with its documented necessary-not-sufficient limit
  named; `duplicate_tag` on a doubly-pasted fragment; the 8C join end to end at a
  non-zero `pos` through `satisfied` → `violated` → `unresolvable`; the Stage 9
  joint join; the `interfaces` half of contract drift; and byte-identical
  fragments across two processes below the elided digest header. `tests/stage8c`
  and `tests/stage9a` stay green — both consume the resolver this sub-stage
  feeds.

- **11C — provenance, federation, and the corpus** (`PARTS_STORE.md` §7–§8): the
  datasheet pointer block, the operator-declared ledger join (`cite.component` /
  `cite.claim`), the `uncited_component_datum` lint rule, merged multi-registry
  federation, and the `LEGAL-REVIEW.md` schema checker.

  **Gate G11C** (Tier 1 + Tier 3): `uv run pytest tests/stage11c -q` exits 0 per
  `PARTS_STORE.md` "Gates" — 15 clauses, including `datasheet_digest_mismatch`
  firing positively on an operator-declared join **and staying silent absent
  one** (the negative clause the earlier digest-inferred formulation could not
  have had, because a join keyed on digest equality that fails on digest
  inequality is logically empty); the component-claim citation round-tripping,
  with `incomplete_component_cite` and an unknown id writing nothing; a core-only
  install refusing a PDF reference with the named `capability_not_available`
  rather than degrading; merged federation resolving a unique id bare and a
  colliding id as `ambiguous_component_id` — a refusal, never a precedence rule;
  both federated registries' digests visible in their own search results; and the
  `LEGAL-REVIEW.md` schema checker asserted against fixtures for all five scope
  fields. Tier 3: the component corpus family is **its own split**, baselined on
  its own first measurement with the reference model at ≥3 seeds, neither
  compared against nor averaged into the v1/v2/v3 baselines, and named — not
  skipped. **Amended 2026-08-29** after a verifier scored the clause uncovered:
  the split is machinery, not a promise. `hephaestus.bench.scoring` carries a
  closed family vocabulary (`CORPUS_FAMILIES`), carves family runs out of *both*
  spec splits so the 0.70 bar cannot be diluted by the plumbing, gives the family
  its own thresholdless `component-prose` / `component-seeded` splits, and
  refuses a first baseline below three seeds per task by the name
  `insufficient_component_seeds`. The live reference-model numbers remain a
  detached run — this repository fabricates none — but the properties the clause
  protects are now enforced in code and asserted in `tests/stage11c`.

  **Status of that Tier 3 row, stated so no matrix can round it up (2026-08-29,
  second verifier pass).** Clause 12 has two halves and they have two kinds of
  evidence. Its **machinery** is Tier 1 and closed: pytest assertions, run by
  the `stage gates 11A-11C` CI job. Its **number** is Tier 3 and outstanding: no
  `component_baseline.json` exists, taking it is a detached `heph bench run` at
  ≥3 seeds with the epoch's reference model (rule 3) followed by
  `heph bench score`, and it is archived bench evidence rather than a CI clause
  — the same standing G9C's mechanism-split baseline has. The honest report of
  this row is *machinery closed, measurement outstanding*, never green; and
  `heph bench score` itself prints `component family: NOT MEASURED` on every
  archive that ran no family task, so the absence is stated by the tool that
  reads the evidence and not only by this paragraph.

**Gates are commands here too (added 2026-08-29).** All three Stage 11 suites
run in `.github/workflows/ci.yml`'s `stage gates 11A-11C` job, and that check
name is required by `release.yml`'s prior-gate list. They were the only stage
suites in the repository with no workflow lane when a verifier looked, which
made them three Tier-1 gates that passed on a developer's machine — rule 1 says
that is not a gate yet, and the lane closes it.

**Licensing: reference, do not vendor (operator decision, 2026-08-29).** The
store's value is mostly not geometry, so the licensing posture is a product
decision and the operator made it, in these words:

> "D3 licensing: REFERENCE, DO NOT VENDOR. Third-party datasheets and vendor CAD
> are referenced by URL and content hash with their terms declared; they are not
> copied into this repository. If a pack cannot be built without vendoring
> something, that pack does not ship in this stage — say so loudly rather than
> vendoring."

This is `docs/frontier-staging-proposal.md` D3 option (b): clean-room geometry
plus pointer-only datasheets. Option (c) — third-party federated packs under
their own licenses — remains available later and only behind **both** the 11C
federation gate and the fifth `LEGAL-REVIEW.md` scope field below. Option (d),
vendor CAD payloads vendored into a registry tree, is refused permanently by this
amendment, so that a later drafter must reverse a dated operator decision rather
than a paragraph. The mechanical half is gate clauses, not good intentions:
`vendored_third_party_payload` refuses any file in a `parts` tree that is not
`registry.toml`, `part.json`, `generator.py` or `*.md`, and
`trademark_in_component_id` refuses a vendor trademark as an id — with the honest
limit stated, that a deny-list check is imperfect and the human review requiring
a reviewer other than the author remains the real control.

**The fifth `LEGAL-REVIEW.md` scope field.** The four scope fields G7 names do
not cover third-party component data. Stage 11 adds a fifth required field —
*third-party component data provenance and terms: which standards were used, that
no vendor payload is vendored, and that every `datasheet` pointer's terms permit
reference-by-citation* — and, because publication of a component pack is blocked
until it is signed off while development is not, it carries the same
blocks-publication-not-development force G7 already gives the review. Two things
are said plainly rather than assumed. First, **this amendment does not edit G7's
gate text**; whoever next amends G7 folds the fifth field into that checklist
sentence, and until then the requirement lives here and in `PARTS_STORE.md` §7.
Second, G7's "CI checks the file's schema" describes a checker that does not
exist today — `scripts/docs_check.py` carries `LEGAL-REVIEW.md` only as a
forward reference and nothing validates its fields — so Stage 11 **builds** that
checker, for all five fields, and gates it at G11C rather than citing it as
though it were already there.

**Two tightenings under rule 1, landing with this stage.** The registry `license`
field becomes required at parse (today `parse_manifest` reads it optionally, so
an absent license silently becomes `""` and publishing copies it unchecked, while
`registries/PUBLISHING.md` already claims publishing checks it), and `part.json`
params become cross-checked against the generator's declared `PARAMS`. Neither is
a waiver; both make an existing claim true.

**Findings discipline (D5), satisfied before this block landed.** The adversarial
pass against `PARTS_STORE.md` returned eight confirmed findings — five blocking,
three major — and all eight were closed by **tightening**, never by deleting a
clause for being hard to satisfy; one clause was re-sited rather than dropped when
its original siting proved unreachable. The closures were then audited clause by
clause against the code they cite rather than taken on the fix author's word, and
six residuals found inside the closures were closed with them. `PARTS_STORE.md`
is promoted from DRAFT to normative by this amendment.

**Numbering, settled here.** D4 option (a) was resolved on 2026-08-28 —
document number equals recommended execution order — and this block applies it:
`PARTS_STORE.md` is document 13 and **Stage 11**. Mesh and scan ingest
(`MESH_INGEST.md`) is Stage 12, pose solving and placement proposal Stage 13,
computer-aided manufacturing Stage 14, structural analysis Stage 15. The
ready-to-paste blocks in `docs/frontier-staging-proposal.md` §3 predate that
resolution and still label mesh ingest "Stage 11"; that document is the approved
plan, not a normative contract, and **this amendment is what settles the
collision**: Stage 11 is the component store, and no other stage takes the
number. No other stage's gate text is edited by this block.

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
