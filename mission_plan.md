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

## Stage 12 — Mesh and scan ingest (amendment 2026-08-29, operator-directed)

Frontier-capability work under the engine-first decision recorded for Stage 8 —
the optimal CAD harness outranks the soonest release. Recorded on the operator's
2026-08-29 approval of the recommended build order in
`docs/frontier-staging-proposal.md`, which puts mesh and scan ingest **second** of
the five frontier capabilities, immediately after the component store, and opens
it as its own gated stage under rule 5. It is second on that document's own
argument: it is the one capability that changes what the harness can *read*. A
prosthetic socket begins with a limb scan, `import_step` is the only door into the
harness today, and `COMPARE.md` §4 closes the mesh door in so many words. Rule 5's
deferred list is untouched — mesh ingest was never on it, which is precisely why
it needs a new gated stage rather than a waiver. Normative spec: `MESH_INGEST.md`
(a mesh or point cloud admitted as an immutable, content-addressed measurement
target on the `INGEST.md` §1 terms — no feature recognition, no surface
reconstruction, no mesh-native modeller, no tagging of mesh topology, no clinical
claim). Stage 12 lands in three gated sub-stages, strictly ordered.

**The honesty problem this stage exists to solve, stated before the gates.** A
mesh has no exact topology. Almost every fact the harness knows how to state
about a solid becomes a *different, weaker* fact when the solid came from
triangles, and the entire difficulty of this stage is refusing to let the two
vocabularies share a field name. Three consequences bind rather than describe:
mesh repair is **measured and named**, never silently performed; a mesh record
carries no `volume`, `sealed`, `genus`, `chamfer_mm` or `iou` attribute, and
G12A.12 fails the gate if a rename reintroduces one; and every refusal is a named
code drawn from a closed set. A plausible-looking wrong surface is worse than a
named refusal — the same reason this project reports `holds_at_samples` rather
than `holds`.

- **12A — admission, canonicalization, facts** (`MESH_INGEST.md` §1–§3):
  `import_mesh` / `import_point_cloud` as script terms; the closed five-extension
  format set with magic sniffing; declared units, with the declared unit part of
  the staged blob's identity; two separately named hashes (raw file bytes, and the
  canonical geometry) whose meanings never merge; the `.hmesh.facts` sidecar
  carrying the pre-canonical counts a post-weld blob cannot recover; ceilings
  refused before the parser runs; and `hephaestus.geom.mesh` as a tenth pure geom
  service that measures quality without repairing it.

  **Gate G12A** (Tier 1): `uv run pytest tests/stage12a -q` exits 0 per
  `MESH_INGEST.md` "Gates" — 20 clauses. The happy path over each admitted format,
  binary and ASCII, against independently computed counts and bboxes. Every §1.7
  refusal **reachable in 12A** fires with its exact code at the right layer as a
  build error at the offending statement — ten of the eleven; the eleventh,
  `mesh_units_conflict`, is asserted **unreachable** rather than skipped, by
  enumerating the admitted extensions, asserting none of them carries an in-file
  unit and asserting that the two unit-carrying formats refuse at admission, so
  that admitting one later without making the code fire breaks the clause. A
  clause claiming "every" while testing ten would itself have been the defect.
  Also: the confinement walk intact for the new terms, exactly as G8A proves it
  for STEP; the `units` keyword grammar, with a computed value still
  `DynamicImportPathError` and `import_step` unregressed; `input_hashes` carrying
  the **raw** bytes while a re-exported file with only a changed ASCII header
  yields a different input hash and the **same** canonical hash; staleness and
  revalidation re-run on the new kind; canonicalization determinism across two
  processes, invariant under triangle and vertex permutation; unit scaling
  asserted in one build as the exact ratios 1 : 10 : 1000 : 25.4 **together with**
  the mechanism that permits it — four pairwise-distinct staged filenames, and
  reuse preserved for a repeated (bytes, unit) pair — a clause that fails against
  the unmodified `staged_filename`, which is the point of writing it;
  pre-canonical counts surviving the sandbox boundary through the sidecar, with
  the separation pinned in both directions (mutating the sidecar leaves the
  canonical hash unchanged; mutating the blob changes it) and worker-side
  recomputation asserted impossible by fixture; `MeshQuality` against
  hand-computable fixtures; a self-intersection ceiling that reports `None` with a
  named method and is asserted **not** to read as zero; the field-name discipline
  above; `point_cloud_not_a_shape`; `tag()` on mesh topology refused; mixed
  mesh + STEP + authored builds; the geom import-boundary tests admitting `mesh`
  as a pure service that reaches the renderer nowhere; `heph scan`; the
  parse + canonicalize + quality budget measured in the pinned image and enforced
  as a ceiling; and the byte ceiling firing **inside the confinement walk before
  anything is spent** — no new opstore blob, no `ImportSnapshot`, and the bytes
  never read, asserted against a sparse fixture larger than the process's memory
  that a read-first implementation cannot survive, with STEP's path proven
  unaffected. That clause carries a second half without which it would be
  half-true: the same fixture is left in the imports tree with **no script
  declaring it** and a full `sync_import_state` is run, because that path resolves
  no declaration and a ceiling read only from a declaration could never bound it.

- **12B — mesh → B-rep, sections, the socket path** (`MESH_INGEST.md` §4–§5):
  `mesh_to_solid` behind a mandatory `BRepCheck_Analyzer` validity gate,
  `section_polylines`, the injected `loft_sections` helper, and the fit-then-offset
  socket design that offsets the *authored* solid rather than the mesh-derived one.

  **Gate G12B** (Tier 1 + Tier 3): `uv run pytest tests/stage12b -q` exits 0 per
  `MESH_INGEST.md` "Gates" — 13 clauses. `mesh_to_solid` on a clean tessellated
  fixture **records the measured validity verdict rather than presuming it**, and
  refuses `mesh_solid_invalid` carrying the analyzer status list where it is
  False. The §4.2 finding is pinned as a regression: the 279-face, `sealed=True`,
  0.003 mm³ offset result is asserted to be exactly what the validity gate
  withholds, and no `intent` value reaches it. `geom.metrics.is_sealed` True
  beside `IsValid()` False is asserted **as a fact**, so the two predicates can
  never be silently conflated. Also: `mesh_sew_timeout` under fault injection,
  with partial facts attached and the subprocess dead afterwards; the `ShapeFix`
  experiment run on the pinned image with its outcome archived and the gate
  asserting whichever branch of the §4.5 disposition rule that outcome selects —
  including that `repair=True` does not exist when it fails; `section_polylines`
  against hand-computable fixtures, where a holed fixture yields an **open**
  contour flagged by name and never closed; section determinism across two
  processes; the §5.2 socket path written as a real part script and run through
  the executor, which also proves the new terms are reachable because an
  unreachable name fails it as a `NameError` at its own line; the injected surface
  asserted as **exact set equality** against the documented list, with
  `GeomAPI_PointsToBSpline`, `BRepBuilderAPI_Sewing`, `OCP` and `trimesh` all
  unreachable and `open` / `__import__` still absent, so `script_contract.md` §2's
  closure is proven at the moment three terms are added underneath it rather than
  assumed; `mesh_derived_operation_refused` for offset, shell/thicken and fillet;
  `heph lint`'s `mesh_derived_offset` rule asserted **with** a defeating case it
  does not flag, so its reach is pinned and can never be read as a guarantee; and
  sew-derived goldens carrying an (image digest, OCCT version) sidecar that
  refuses a mismatched pair. Tier 3: sewn face and vertex counts and the validity
  verdict identical across two processes in the pinned image — counts and verdict,
  never sewn bytes.

- **12C — scan scoring, surface, corpus** (`MESH_INGEST.md` §6–§7): the
  `ScanDistance` record and the fields it deliberately lacks, the `declared`
  alignment mode, `compare_to_scan` as the single new tool, `m.scan_diff` on the
  part-scope facade, reviewer delivery of mesh-quality facts, and the `scan-*`
  corpus family.

  **Gate G12C** (Tier 1 + Tier 2 + Tier 3): `uv run pytest tests/stage12c -q`
  exits 0 per `MESH_INGEST.md` "Gates" — 18 clauses. Direction A exact to 1e-9
  against closed-form distances; direction B's `kdtree_bound_exact_triangle`
  matched against a brute-force all-triangle reference to 1e-9, which is what
  proves the `d_v + L_max` candidate set a sound superset rather than a heuristic;
  `scan_neighborhood_overflow` abandoning refinement **by name**, populating a
  named upper bound asserted **≥** the true distance and leaving the exact field
  `None`. Record discipline runs over **all three** part→scan fields — mean and
  max both populated or both `None`, the bound the complement of both, and no
  record carrying an exact field beside a bound. Also: `scan_iou_unavailable`;
  `declared` alignment echoed and validated rigid (orthonormal to 1e-9, det +1) or
  refused, with `principal` refused by name on both a mesh and a point cloud;
  `compare_solids` and `m.diff` refusing a `scan:` target while a byte-for-byte
  regression holds every existing G8B `SolidDiff` record unchanged;
  `compare_to_scan` through dispatch on **both** profiles with the scan's
  canonical hash and the part's artifact ref attributed; the tool-surface pin
  asserted both relatively and absolutely (below); `m.scan_diff` passing and
  failing either side of its threshold, with the cross-part facade refusing a
  `scan:` target and the scan appearing in the build's frozen inputs;
  `scan_timeout` landing inside a predicate as `unverifiable` — not a pass, not a
  crash. The round-trip is **two** clauses because one cannot do both jobs:
  round-trip **identity** (tessellate → export → import → compare) is labelled in
  the test as a corruption check with a ×1.001 negative control, and round-trip
  **fidelity** is the clause that actually binds the declared deflection, holding
  `part_to_scan_max_mm` inside a **two-sided** window with the exact method
  asserted **first** so a bound cannot satisfy it, and a negative control on each
  side. Tier 2: identical `ScanDistance` records to 1e-9 across two processes,
  with identical sample counts and identical method strings — a differing method
  string fails the clause. Plus reviewer context carrying `MeshQuality`,
  `geometry_source` and `ScanDistance`, with a mesh-derived source surfaced and
  asserted **not** to produce a blocking finding; `heph scan check`; and the
  `scan-*` corpus tasks' two independent reference solutions passing their own
  acceptance through the engine path. Tier 3: **scan-prose and scan-seeded are
  each their own split**, each baselined on its own first measurement with the
  reference model at ≥3 seeds, neither compared against nor averaged into the
  v1/v2/v3 baselines, and the existing 0.70 prose bar keys on its own coverage
  constant so it cannot be diluted by the plumbing. Re-baselining any combined bar
  is its own explicit future amendment.

**The tool-surface pin moves here: 53 → 54.** Stage 12 is the first of the five
frontier stages to move it. `PARTS_STORE.md` adds no tool, so the pin stood at 53
where this stage opened, and `compare_to_scan` is the single addition. G12C.42
asserts **both** halves: that the pin in both places increments by exactly one
from a pre-stage value recorded as a named constant in the stage-12 test module at
gate-authoring time — never re-derived from git history at test time, which would
make the gate depend on the checkout's depth and shape — and that the recorded
value **is 53**, so the post-stage pin is **54**. A future reorder that changes
the pre-stage value updates the constant *and* cites the amendment that moved it.

**One refusal-code rename, taken unilaterally by this stage.** `PHYSICS.md`
(Stage 15, this document's successor) also drafts a `mesh_too_large`. Rather than
leave a live collision in a closed vocabulary, this stage names its byte-ceiling
refusal `mesh_import_too_large`, on two order-independent grounds: it is an
`ImportResolutionReason` about a *file*, and the two refusals are about different
objects at different times. **No clause here obliges any other document to rename
anything**, and no "the later document renames" rule is invoked — under the
settled order that rule would point the wrong way and would have a future agent
revert this rename and re-open the collision.

**The document amendments this stage carries, each landing with its own
machinery.** `INGEST.md` §1 and §3, `repo_conventions.md`'s spike disposition, and
`script_contract.md` §2's first wave (`import_mesh`, `import_point_cloud`) land at
12A, together with two `verification.md` additions whose evidence is G12A's own —
the Tier 1 kernel-service list gains mesh quality against hand-computable
fixtures, and the Tier 1 performance-budget list gains the parse + canonicalize +
quality budget. `script_contract.md` §2's second wave (`mesh_to_solid`,
`section_polylines`, `loft_sections`) and `verification.md`'s golden-provenance
(container image, OCCT version) pair land at 12B. `COMPARE.md` §1 and §4,
`script_contract.md` §6, `tool_schema.md`, `VALIDATION.md` §1 and §5, and the
`scipy` pin in `core/pyproject.toml` land at 12C. Two of those rows are
constrained rather than free. The `COMPARE.md` §4 replacement **carries the
FEA-mesh exclusion forward verbatim** — an FEA mesh is a solver input, never a
comparison operand — because `PHYSICS.md` declares that sentence an explicit
non-amendment at Stage 15 and this stage rewrites it first; preserving it is a
requirement of the row, not a courtesy. The `verification.md` row **adds a pair to
whatever list stands** rather than rewriting the block, so `PHYSICS.md`'s later
mesher/solver pin joins it without conflict. **This block edits no other stage's
gate text.**

**The one open question this stage does not pre-decide.** Whether OCCT's
`ShapeFix_*` can repair a faceted solid to validity, and at what cost, was not
measured. `MESH_INGEST.md` §4.5 pre-commits to the **disposition rule** rather
than to a result — success within the §4.1 ceiling gives `mesh_to_solid` a
recorded `repair=True`; failure keeps `mesh_solid_invalid` and leaves the socket
workflow as §5.2 only — and G12B.25 measures it on the pinned image, archives the
evidence under rule 2, and asserts whichever branch the outcome selects. Naming an
unmeasured mechanism as new work rather than assuming it is the `KINEMATICS.md`
discipline. **Measured 2026-08-30, in the image:** all three fixers
(`ShapeFix_Shape`, `ShapeFix_Solid`, `ShapeFix_Shell`) complete in under 0.32 s
and **none reaches `IsValid()`**; two of them hand back a solid whose volume has
flipped sign. The rule's second branch holds, `repair=True` does not exist, and
the archived evidence carries the (image digest, OCCT version) stamp saying which
world produced that answer.

**Constants set from the pinned image's own measurement, under rule 4 — TAKEN,
2026-08-30.** `MESH_ROUNDTRIP_EPS_MM`, `MESH_TESSELLATION_VOLUME_BIAS` and the
G12A performance budget were previously set in the repository venv and the debt
was recorded here as outstanding. It is now discharged, and by a measurement
rather than by a promise: `scripts/stage12_pinned_measure.py --write` takes all
four figures **inside the pinned image**, refuses to write anywhere else
(`hephaestus.testing.pinned_image.pinned_stamp`), and archives them stamped with
the world they came from at `evidence/pinned_measurements.json` in each of `tests/stage12a`, `tests/stage12b` and `tests/stage12c`.
Each constant is then **derived at import from its recorded figure** rather than
transcribed beside it, so a constant cannot exist without the record and cannot
drift from it in silence. The recorded numbers: parse + canonicalize + quality
**6.1365 s** for 20 480 triangles (ceiling 18.4 s, three times the measurement);
round-trip identity **9.3686e-7 mm** (ceiling 1e-3 mm, three orders of magnitude
rounded up to the next power of ten); tessellated-volume bias **0.70650 %** at
the pinned 0.1 mm deflection (ceiling 0.883 %); the `ShapeFix` disposition and
the two-process sew counts recorded outright. Every derived ceiling is asserted
**at or below** the value that stood before the image measured anything: budgets
tighten, never loosen, and a re-measurement on a slower image may not buy an
implementation room it never earned.

**Where that measurement was taken, stated exactly rather than implied.** The
GHCR digest `ci.yml` pins is not resolvable from the machine that took it — a
private package answers `403` without `read:packages` — so the record was taken
in a container built from the repository's own **unchanged**
`docker/ci/Dockerfile`, whose `FROM` is itself digest-pinned. That is the route
`docker/ci/README.md` documents and the route commit `f3a4d42` took to re-record
the G1/G4 goldens "inside the pinned CI image", and the record says which of the
two routes produced it rather than claiming a digest it does not have. What ties
it to the pin mechanically is the **base image**: `load_pinned` re-reads the
`FROM` digest from `docker/ci/Dockerfile` at test time and refuses a record taken
against a different one, so a base bump invalidates every record that did not
move with it. And the `stage12 measurements (pinned image)` lane re-takes all
four in the GHCR image on every PR (`--check`), failing if the recorded numbers
no longer describe it. A recorded number nobody re-takes is a number nobody is
accountable for.

`MESH_MAX_BYTES` / `MESH_MAX_TRIANGLES` / `MESH_MAX_POINTS` remain deliberately
unvalued here: they are admission ceilings whose *shape* is what G12A.2 and
G12A.20 bind, not wall clocks, and rule 4's re-measurement obligation does not
reach them.

**One Tier 3 clause carries a different debt, and it is not this one.**
**G12C.51** (the `scan-prose` / `scan-seeded` splits) needs a **live
reference-model sweep**, which is a detached run this repository does not take
and must never fake — rule 2's archive is evidence precisely because nothing
writes into it that did not happen. Its machinery is closed and asserted (own
splits in both specs, own first-measurement baseline at ≥ 3 seeds, the 0.70
prose bar keying on its own coverage constant with the family carved out and not
dropped, and `INSUFFICIENT_SCAN_SEEDS` refusing a thin first measurement with
nothing written), and `heph bench score` prints `scan family: NOT MEASURED …
outstanding` on any archive with no scan runs — a tool that says what it does not
know, which is the same disposition Stage 11 took for its own Tier 3 clause.

**Three repair passes, and what the third one found (2026-08-30).** Each pass was
an independent verifier reading all 51 clauses against the code that claimed to
satisfy them; the findings are recorded in `MESH_INGEST.md` ("The repair pass…",
"The second repair pass…", "The third repair pass…") rather than only in a
session log, because a finding closed and reported nowhere is a finding the next
agent rediscovers. The third pass passed 50 of 51 and found the defect this stage
exists to make impossible: **`compare_to_scan` on a part with no faces returned a
distance of `0.0` under the name of the exact method, from zero samples, with no
refusal spent** — a plausible-looking wrong number, reachable through the
product's own tool, and *invisible* to the clause (G12C.37) written to police
those very fields, because the bad record's shape is a legal one. Fixed at the
producer, which now refuses `scan_unmeasurable` before spending either
direction. Beside it: the `[code]` derivation rule was closed for the admission
third of §10 and open for the other two thirds (two §10 codes existed only as
message prose, with no `reason=` behind them); two clauses asserted a weaker case
than the one their own spec text names; one asserted a recomputation instead of
the build's own output; and `ci.yml` still carried two comments claiming a
pinned-image measurement was owed after it had been taken. Every one is closed by
tightening — two refusal codes were **added** to the §10 vocabulary
(`scan_target_ambiguous_units`, `declared_transform_not_rigid`), none removed,
none relaxed — and the count stands at 51.

**Clinical claims, refused in contract form (`MESH_INGEST.md` §11).** A prosthetic
socket is a load-bearing medical device. This stage evidences **geometric distance
between an authored solid and a scan, at named samples, to a named tolerance** —
and nothing else. **Fit** is refused: rectification is clinical judgement the
harness cannot verify, and no `CHECKS` predicate over a `ScanDistance` may be
presented as evidence of it. **Load** is refused: structural adequacy is FEA,
deferred by name by rule 5 and entering only by its own gated stage. **Softness**
is refused: the scan is a rigid capture of a deformable limb and nothing here
models tissue. Shipping the geometric half honestly is real capability; shipping
either half while calling it "validated for fit" is the failure this project
exists to prevent. This block creates no clinical-claim exception anywhere else in
the plan.

**Structural lattices are deferred by name, with a precondition.** Gyroid/TPMS and
strut lattices are out of scope and are their own gated stage under rule 5, whose
**explicit precondition** is the rule 6 second-kernel question — answered before
such a stage is scheduled, not during it. A TPMS lattice is an implicit surface
realized by marching cubes, so it *produces* a mesh and inherits every honesty
problem above; at 10⁵–10⁶ faces the boolean *is* the operation, which needs a
mesh-native engine, which is a second implementation of what the Python core owns.
Print infill is not this and already has a home: it is manufacturing metadata on
the existing 3MF export path, and slicers own it.

**Gates are commands here too.** All three Stage 12 suites join
`.github/workflows/ci.yml` as their own lane on the pattern the Stage 11 lane
established, and that check name joins `release.yml`'s prior-gate list. Rule 1 is
the reason: three Tier 1 gates that only ever pass on a developer's machine are
not gates yet. **So does the measurement lane**, and that correction is worth
recording: an earlier draft added `stage12 measurements (pinned image)` to
`ci.yml` and argued *in a comment* for leaving it out of the prior-gate list.
`tests/stage7h::test_the_prior_gate_check_names_every_ci_job` asserts set
equality between the two, so that argument turned a green gate red — and under
rule 1 a documented deviation from an assertion is still a failing assertion,
resolved by tightening rather than by prose. The lane is in the list. It takes a
measurement rather than waiting on one, and a release that shipped constants
nothing re-measured in the image is exactly what the list exists to stop.

**Findings discipline (D5), satisfied before this block landed.** The adversarial
pass against `MESH_INGEST.md` returned six confirmed findings — three blocking,
three major — and the closures were then audited clause by clause against the code
they cite rather than taken on the fix author's word. Four closed outright; the
audit found residuals inside two of them and one document-wide sequencing
inversion, and every one was closed by **tightening**. No gate clause was deleted
or weakened: the count stands at 51 (G12A 20, G12B 13, G12C 18). The four
substantive tightenings, recorded because each one is a trap a later implementer
would otherwise fall into: the staged-filename formula was corrected to the
expression the code actually evaluates, since the drafted one would have silently
renamed every already-staged STEP artifact; the byte ceiling was extended to the
**undeclared-file** path that `sync_import_state` drives over every file under the
imports tree, which a declaration-resolved ceiling could never bound; the
`mesh_units_conflict` code was kept in the closed vocabulary with its
unreachability asserted **as a fact** rather than skipped or deleted; and six
clauses that still reasoned from a retracted ordering in which `PHYSICS.md` was
the predecessor were rewritten against the settled order — one of them would have
instructed a future agent to revert the rename above and re-open a live refusal
collision, and another would have had an implementer waiting on a tool-count
repoint from a stage that lands three stages later. `MESH_INGEST.md` is promoted
from DRAFT to normative by this amendment.

**What that review was, stated so no later reader rounds it up.**
`MESH_INGEST.md`'s own header named two conditions for normativity: an adversarial
review on the `KINEMATICS.md` precedent, and this dated amendment. The review that
actually ran was a six-finding adversarial pass plus an independent
clause-by-clause closure audit against the repository — not the 40-agent, 31-finding
pass `KINEMATICS.md` records. That is the evidence behind this promotion, and it is
written here rather than in the spec so the promotion cannot be read as claiming
more than it has. A further adversarial pass remains available and would land as
tightenings under rule 1, never as waivers.

**Numbering, unchanged from the Stage 11 block that settled it.** D4 option (a)
holds: `MESH_INGEST.md` is document 14 and **Stage 12**, with the gate names
G12A/G12B/G12C and the suites this block names. `docs/frontier-staging-proposal.md`
§3.2's ready-to-paste block still labels mesh and scan ingest "Stage 11" because it
predates that resolution; it is superseded by the text above and retained only as
the drafting record.

## Stage 13 — Pose solving and placement proposal (amendment 2026-08-30, operator-directed)

Frontier-capability work under the engine-first decision recorded for Stage 8 —
the optimal CAD harness outranks the soonest release. Recorded on the operator's
2026-08-29 approval of the recommended build order in
`docs/frontier-staging-proposal.md`, which puts pose solving and placement
proposal **third** of the five frontier capabilities, after the component store
and mesh ingest, and opens it as its own gated stage under rule 5. Normative
spec: `SOLVER.md`. Stage 13 lands in three gated sub-stages, strictly ordered.

**This stage is not like the others, and the difference is the whole reason it
needs its own paragraphs before any gate.** Every other frontier stage *adds* a
capability the plan already anticipated. This one **reverses a rule five
documents and four modules state in the imperative** — `ASSEMBLY.md` §1's "NO
SOLVER" bullet, restated in `ASSEMBLY.md` §4, in `KINEMATICS.md` §0 and §7, in
`tool_schema.md`'s `check_assembly` section, and as a module contract in
`geom/constraints.py`, `geom/kinematics.py`, `core/assembly.py` and
`core/motion.py`. Rule 5 is the only door, and the `ASSEMBLY.md` §1 bullet
pre-authorised exactly this route in the same breath as the refusal — "(A
placement solver, if ever, is a separate stage.)" — so this is the separate
stage, and the parenthesis is now spent. **All four module contracts stand
unamended**: the reversal is a document-level scoping, and the new Stage 13
modules restate the rule rather than relax it.

**D1, decided (operator, 2026-08-29).** `docs/frontier-staging-proposal.md` §4's
D1 put four options to the operator: reject any solver; approve only the
anchor-to-point pose solve, which needs no rule change; approve the
proposal-only reversal in full; or approve that plus writeback. The operator
approved **the proposal-only reversal, option (c), with (d) refused**, and
bounded it in these terms:

> The solver proposes. Its output is a measurement artifact carrying transforms
> and provenance; nothing applies it; applying a proposal stays an authoring act
> through the ordinary edit path, so scripts remain the sole authority on
> position and the diff stays reviewable. Writeback is refused. A solver that
> mutates published artifacts would make geometry authorless; that is the thing
> the original rule protected and it survives intact.

Both tightenings D1 recommended with the approval are applied. The first: 13A's
two target forms are held apart and asserted by their own gate clauses — the
anchor-to-point form is legal under the *unamended* rule and the constraint-id
form is legal only under this amendment — so a reviewer can see exactly which
clauses the reversal buys. `SOLVER.md` §2A records the one legal alternative,
shipping anchor-to-point only and deferring constraint-id targets to 13B, and
states that it is not taken, so the ordering is a decision rather than an
oversight. The second: the writeback refusal is in the **plan**, below, and not
only in the spec.

### The reversal, in this plan's own words

**THE SOLVER PROPOSES.** Its output is a measurement artifact carrying
transforms and provenance. **Nothing applies a proposal.** No tool, no CLI verb
and no agent path in Stage 13 writes a part script, writes a parameter,
republishes a transformed artifact, or makes any build current; applying a
proposal stays an **authoring act** through the ordinary
`edit_part` / `write_part` / `set_params` surface, under the existing
optimistic-hash, journal-backed, no-force-overwrite contract, and it shows up in
git as a normal diff. **WRITEBACK IS REFUSED.** No code path in Stage 13
computes, offers or guesses an inverse from a rigid transform to a script
expression; a +0.42 mm X delta on a real bracket can be authored as a change to
`hc.joint_clear`, to `hc.shelf_w`, to the part's own `p.wing`, or as a new
literal — four different design intents, three of which change other parts —
and Stage 13 refuses to guess which. The refusal is
structural rather than a promise: the proposal document schema is
`additionalProperties: false`, so a `suggested_edit` field cannot be emitted,
and every tool input schema in this repository is `additionalProperties: false`,
so one cannot be requested either.

That is written here, in the plan, and not only in `SOLVER.md`, because the
operator directed on 2026-08-29 that the writeback refusal live in the plan's own
text: a rule that exists only in the spec it constrains is a rule with one
reader, and a later drafter must now reverse a dated operator amendment rather
than a paragraph. Writeback — a solver that authors a script edit — enters, if
ever, only by a further amendment that reverses this sentence explicitly, and it
would need `VALIDATION.md`'s dimension-findings discipline verbatim.

**What the original rule protected, and that it survives.** The `NO SOLVER`
sentence was short, and short rules are the ones a reversal quietly guts, so
what it guarded is enumerated here rather than gestured at. **Scripts stay the
sole authority on position**: no artifact is produced by anything but a script
build, so a build's identity remains a function of its recorded `input_hashes`
and a position originating anywhere else would not be named by that hash set.
**Git keeps owning design state** (rule 6): a proposal is a *measurement*, in
the same category as an `AssemblyStatus` or a `SolidDiff`, and design state
after Stage 13 is exactly what it is today — scripts, `globals.py`, and
persisted params, in git. No per-part placement is stored in `.heph/` or a
ledger, which would be a second source of geometric truth. **The diff keeps
carrying intent**: real placements are symbolic, a reviewer reads
`Pos(hc.shelf_w / 2.0 + hc.joint_clear + p.wing / 2.0, 0, 0)` under a comment
saying why, and nobody reads a 3×4 matrix — so a proposal deliberately ships
**no** suggested source text. **One home per number** survives because nothing
is written, so no solved literal can shadow an `hc` name the executor uses to
mark consumers dirty. **The verdict vocabulary keeps meaning something**: a
proposal's residuals are re-measured by the *existing* `core.assembly` evaluator
in a separate process, the `AssemblyStatus` row is untouched, and it keeps
saying `violated` until a rebuilt script measures otherwise. **The closed
evaluation loop stays broken**, on the seam `VALIDATION.md` already uses for
binding-dimension findings — a violated constraint clears in exactly two ways,
a later successful build that measures otherwise or an explicit operator
dismissal, and there is no model-facing write that clears one. **Requirement
provenance stays compulsory**: a solve request cites a requirement id or is
`assumed` with a reason, refused `missing_provenance` otherwise, because a solve
is an interpretation of intent for the same reason a constraint is.

The alternative that lost is named so the choice is legible: **mutating
published artifacts** — republishing transformed geometry so a constraint
measures satisfied — fails every property above, makes the constraint
self-satisfied, and exports geometry no script produced. Stage 9 already refused
a strictly weaker version of it. A solved placement is therefore **verified
independently** by the existing constraint evaluator and never trusted because
the solver said it converged; where the solver's own number and the kernel's
disagree, the whole result is refused by name and no verdict is emitted.

**Honesty vocabulary, binding on all three sub-stages.** Convergence,
non-convergence, over-constraint, under-constraint and **multiplicity** are each
their own named state, and a constraint system with many solutions never
silently picks one: a positive-dimensional solution set is
`underdetermined_at_tolerance` carrying `dof_remaining` and a named basis of the
free directions, and two declared starts reaching genuinely different answers is
`multiple_solutions_from_starts` with **all** of them returned and none chosen.
A local method's silence is never infeasibility — the failure spelling is
`no_placement_found_from_starts`, and "infeasible", "impossible" and "no
solution exists" appear nowhere in a result. Refusals are not verdicts, on the
`MotionTimeout` precedent: a killed solve decided nothing. And determinism is
tiered **per block rather than per solve**, because the seam is kernel-touched
versus not: a kernel-free `solver_core` is bit-reproducible in the pinned image
and gated on the digits, while every `verification` block is D2 and the gate
binds only what is genuinely reproducible — the verdict spelling, the
re-measured residuals within tolerance and on the same side of it with identical
`satisfied` flags, the active bounds and `dof_remaining`, and the bound input
refs. Iteration counts, step sizes and returned digits are explicitly not gated
in D2, and the spec says so rather than claiming uniform reproducibility.

### The sub-stages and their gates

- **13A — pose solving** (`SOLVER.md` §2A): inverse kinematics over declared
  joint parameters, in both target forms — an anchor-to-point target (the
  inverse of `reach`, which needs no rule change) and a constraint-id target
  (which moves joints in order to satisfy a declared 8C constraint, and is legal
  only under this amendment). `solve_pose` on both profiles, writing nothing:
  no proposal artifact, no pose declaration, no generation. The solve record
  carries its `solver_core` / `verification` blocks inline, so no G13A clause
  reaches forward into 13B's store.

  **Gate G13A** (Tier 1): `uv run pytest tests/stage13a -q` exits 0 per
  `SOLVER.md` "Gates" — **17 clauses** (1–17). Forward kinematics as a *pure
  function* to 1e-9 at fixed given joint values — the only 1e-9 in the gate, and
  a claim about arithmetic, never about a solved quantity. Then both target
  forms: `pose_found` with the target error **re-measured** through
  `core.motion`'s resolution path and asserted `<= tol`, never 1e-9; and
  `pose_converged_at_tolerance` on a constraint-id target with conjunct (i)
  asserted **independently** — the constraint re-measures `satisfied is True`
  through the ordinary `core.assembly` path, class predicates included, every
  `values` entry recorded beside its declared bound. That constraint-id clause
  is **not optional and not deferrable**: it is the sole reason the
  `ASSEMBLY.md` §1 amendment lands at 13A, and a G13A that amended the
  no-solver rule for a capability no clause exercises would buy the amendment on
  credit. Also: the pose verdict tuple asserted verbatim and complete — seven
  spellings, `pose_found` only for anchor-to-point and
  `pose_converged_at_tolerance` only for constraint-id — with "solved",
  "infeasible" and "holds" absent from every payload;
  `no_pose_found_from_starts` on an out-of-reach target carrying every declared
  start, and **not** spelled `violated`; `pose_underdetermined_at_tolerance`
  with `dof_remaining == 1` and a named direction basis;
  `multiple_poses_from_starts` on elbow-up/elbow-down with neither chosen;
  a limit-blocked target reporting `limits_active` with no value clamped;
  every reachable request-time refusal by name with nothing written, including
  `tolerance_below_determinism_floor` and its superseded spelling asserted
  absent from the source tree; `rank_undecidable` on a straddle fixture;
  independent verification in a separate process with an injected solver-side
  error producing `solver_residual_disagreement` and **no verdict**; the
  import-closure assertion excluding `hephaestus.geom.solve` from the verifier;
  `solver_timeout` and `iteration_ceiling` as named refusals absent from the
  verdict tuple; per-block determinism with the recorded frames asserted
  **equal first** as the precondition of the D1 claim and no `verification`
  block claiming D1; the amendment-drift clause below; dispatch on both profiles
  with no pose declared as a side effect; `heph solve pose`; and existing suites
  stay green with the Stage 13 delta under `tests/stage9*` **asserted rather
  than assumed**: `tests/stage9a` and `tests/stage9b` untouched, and the only
  edit anywhere under `tests/stage9c` the corpus-count pin G13C clause 54
  repoints, 23 → 25, held equal to the public corpus on disk. (This summary
  read "`tests/stage9a`–`stage9c` unchanged" until 2026-09-01. The tree denied
  it — 13C's two new public tasks had to move stage9c's pin — and no clause
  asserted it, so it is tightened to the delta under mission rule 1 and G13A
  now asserts the delta *and* this line. Nothing was deleted or relaxed; see
  the closure record below and `SOLVER.md` clause 17.)

- **13B — placement proposal, transform space** (`SOLVER.md` §2B, §7–§8): a
  rigid transform per declared-free part, returned as a content-addressed,
  provenance-carrying **proposal artifact** that no tool applies, with
  `propose_placement` (orchestrator profile only) and `read_proposals` (both).

  **Gate G13B** (Tier 1): `uv run pytest tests/stage13b -q` exits 0 per
  `SOLVER.md` "Gates" — **26 clauses** (18–43). Each analytic objective kind on
  a **full-column-rank** fixture, with the rank asserted explicitly rather than
  inferred from the verdict, because a lone mate of any of those kinds is
  rank-deficient by construction and no clause anywhere may demand a unique
  transform from a positive-dimensional solution set — those land in
  `underdetermined_at_tolerance` with their `dof_remaining` and named bases
  instead. The reformulation-identity clause: the solver does not iterate on the
  engine's `measured` expressions, because all four are non-smooth or singular
  at exactly their own solutions, so each reformulated residual is mapped back
  through its stated identity and asserted to reproduce the engine's number to
  1e-9 — a pure-function claim — and each analytic Jacobian column is checked
  against a central finite difference **within one declared tolerance of the
  solution**, the neighbourhood where a clause evaluated at a comfortable
  distance would prove nothing. The class-predicate clause carries both signs: a
  zero-gap **same-facing** `coincident` pair is **not** a success, and with a
  free rotational DOF the solver flips the part and returns
  `converged_at_tolerance` — proving the predicate steers the iteration rather
  than only failing it at verification. Also: `not_an_objective_kind` with each
  reason string; the excluded kinds nevertheless **evaluated at the solution**,
  so a proposal that satisfies four mates and drives two solids into each other
  reports `no_interference` violated; `multiple_solutions_from_starts` on the
  180°-flip bracket; `overconstrained_at_residual_floor` with stationarity
  asserted and **no culprit constraint named**; the request-time refusals; the
  `non_rigid_iterate` `SO(3)` clause; weighting and regularisation echoed per
  component and refused when undeclared; independent verification with a
  fault-injected disagreement; **the proposal is not a verdict** —
  `check_assembly` still reports the constraint `violated` and no tool accepts a
  proposal id where a constraint id is expected; **the proposal clears
  nothing** — the reviewer harness still produces the blocking finding; provenance
  and read-time staleness; **no writeback asserted structurally** rather than by
  a refusal name, against the proposal schema's own `additionalProperties:
  false` and the tool input schemas', with a fourth assertion keeping the
  vocabulary closed in **both** directions; per-block determinism; bounded
  execution; profile dispatch; the tool-count repoint; and 8C and Stage 9 wire
  shapes byte-for-byte unchanged against recorded evidence.

  **13B landed 2026-08-30, and four decisions inside it are recorded here
  rather than left in the code.** (1) Clause 19's 1e-9 identity claim holds
  verbatim for every *length* component, at the solution and away from it, and
  for every *angular* component at a well-conditioned configuration — but **not**
  for an angular component at the solution, and the reason is the very pathology
  §3.3 exists to name: the engine measures an angle as `degrees(acos(dot))`,
  whose derivative is unbounded as `dot → ±1`, so one ulp of `dot` becomes
  `ulp / sin θ` of angle. At this gate's tightest fixture that is 1.2e-8 deg,
  measured. The gate therefore declares a bound of 1e-6 deg for that case and
  asserts it stays three orders below the tightest class-predicate bound any
  design declares, so the comparison can never go vacuous. Demanding 1e-9 there
  would be demanding of `acos` an accuracy it does not have — the same defect
  the `tolerance_below_measurement_floor` rename corrects elsewhere, and it is
  reported rather than absorbed. (2) `propose_placement` accepts the **declared
  box** §4.2 step 4 already contemplates ("2B is unbounded unless the request
  declares a box"), because clause 20's negative needs a transform-space system
  in which "no free DOF can flip the part" is expressible at all; bounds are
  never clamped in silence and a variable that reaches one comes back in
  `bounds_active`. (3) `free_part_is_jointed` refuses a part named by an active
  joint in **either** role, not only as a child: moving a joint's parent freely
  while its subtree stays where forward kinematics put it would propose a
  placement no kinematic chain can realise. That is stricter than §2B's
  sentence, and it is named rather than silent. (4) A proposal is recorded for
  every verdict that computed a placement and **not** for `unresolvable`, which
  computed none — storing a proposal that proposes nothing would make the
  proposal set answer a question it never asked. The CI lane is renamed
  `stage gates 13A-13B` with the suite it now runs, on the rule the 13A note
  records: a lane naming a suite that does not exist is a red build. (13C
  renamed it again, to `stage gates 13A-13C`.)

  **A defect 13A left behind, found here and fixed here rather than reported
  and left red.** Two EARLIER stages pin the tool surface by absolute count —
  `tests/stage11b`'s "no tool is added by this stage" (`== 54`) and G12C.42's
  "the pin increments by exactly one from the recorded pre-stage value"
  (`53 + 1`, plus two literal-needle assertions on the two repointed pins).
  Both express a claim about **their own** stage's delta, and both wrote it as
  an absolute literal, which says instead that no later stage may ever add a
  tool. So 13A's `solve_pose` turned five of those assertions red the moment it
  landed, and 13A's report claimed "existing suites stay green" without having
  run either suite — the exact failure mode this plan's verification note warns
  about, one passing file proving nothing about the ones nobody ran. 13B ran
  them, found them red, and repaired both gates by stating the delta they
  always meant: each now pins its own stage's value plus a NAMED list of the
  tools declared after it, so an unaccounted addition is still a red build and
  a later stage that adds one has to say so in that stage's own gate. Neither
  claim is weakened; both are now falsifiable by the thing they were about.

- **13C — parameter space and the bench** (`SOLVER.md` §2C, §11): free variables
  that are declared `Param`s, evaluated by transient-override preview builds
  that are `current=false` by existing contract and publish nothing —
  `space: "parameters"` as an enum value on `propose_placement`, not a fourth
  tool.

  **Gate G13C** (Tier 1 + Tier 3): `uv run pytest tests/stage13c -q` exits 0 per
  `SOLVER.md` "Gates" — **13 clauses** (44–56). A two-`Param` solve reaching a
  hand-computed optimum to `PARAM_MATCH_EPS`, derived from the declared
  tolerance and the fixture's recorded conditioning and **never** to 1e-9;
  `fit` admitted here and asserted against 13B's refusal of the same kind;
  `nonsmooth_terms` listing every `distance` term with the local-model caveat
  stated; **every candidate build a preview** — `current == false` on every
  build the solve issued, current artifact refs unchanged afterwards and no
  parameter override persisted; `no_free_variable_affects` naming the insensitive
  constraint rather than inventing a transform for a knob the author never made;
  the parameter refusals and the no-clamping rule; `unbuildable_parameter_iterate`
  and `build_budget_exhausted` carrying the best iterate and its verified
  residuals; **D2 in both blocks**, with the test explicitly asserting no digit
  equality anywhere and no 2C block claiming D1; the `space: "parameters"` enum
  extension asserted to have been **absent** from the 13B enum, so that clause is
  not vacuous, with the tool count unchanged at 57; `heph solve params`; and the
  `solve-*` corpus family graded **through the engine path on the rebuilt part**
  — a run that produces a correct proposal **without rebuilding fails the task**,
  which is the closed-loop break made mechanical. Tier 3: **solve-prose and
  solve-seeded are each their own split**, each baselined on its own first
  measurement with the reference model at ≥ 3 seeds, neither compared against nor
  averaged into the v1/v2/v3 baselines, carved out by `split_name` **before** the
  aggregate is formed so the existing 0.70 prose bar keys on its own coverage and
  cannot be diluted through the plumbing, with a first measurement thinner than
  three seeds refused `insufficient_solve_seeds` and no baseline file written.
  Re-baselining any combined bar is its own explicit future amendment.

  **13C landed 2026-08-30, with six deviations recorded rather than absorbed.**
  (1) A finite-difference gradient costs **`2n`** evaluations, not the `1 + n`
  §10 wrote: the driver is the *central* difference `geom.solve` already owns
  and G13B clause 19 holds the analytic Jacobians against, so a second
  forward-difference implementation for the budget's sake would be a second
  place for the step and the divisor to drift apart, and less accurate exactly
  at the solution §3.3's argument is about. The real cost is below both numbers
  because a part parameter cannot change another part's geometry, so a probe
  rebuilds one part and an evaluation at inputs already built is cached; and
  the §7 verification pass's builds are **not** charged to the iteration's
  budget, because §10 already gives that pass its own wall-clock bound and
  charging one ceiling against another would refuse a solve for the cost of
  checking it. (2) `no_free_variable_affects` has a **second conjunct** the
  §2C sentence does not state, and the one-conjunct reading is wrong: a
  constraint that is already *satisfied* and moves for nothing is not
  unreachable, it is reached — and a `fit` inside its declared window
  contributes an identically flat residual by construction, so the naive test
  would refuse a whole solve over a constraint that holds. The refusal fires
  only when a source is flat in every free variable **and** at least one of its
  components is outside its own declared bound. (3) `unbounded_param` names the
  case that really exists — a `globals.py` **derived constant**, a readable
  `hc` name with no declared box — because every `Param` proper is bounded by
  construction, so the sentence's literal reading would have been a refusal
  nothing could reach, the `no_writeback_grammar` defect over again. (4) `fit`
  and `distance` needed §3.3 reformulations of their own, and §3.3 had none:
  `distance`'s engine number kinks at exactly the declared separation, and
  `fit`'s bound is a **window** rather than a tolerance, so its residual is a
  deadband whose flat interior is what forced (2). Both identities are gated
  like the other six. (5) §11's `budgets?` is spelled **`build_budget`**: there
  is exactly one budget in this space, and an unnamed plural is a field no gate
  clause can assert against. `box` and `ground` are refused in parameter space
  and `build_budget` in transform space, by name rather than ignored, because a
  declared limit nothing spends is a limit a reader would believe was enforced.
  (6) A `Param` declares **no unit** (`script_contract.md` §3 is
  `default`/`min`/`max`/`doc`/`step`), so §Gates' "in the declared units of
  each `Param`" names a field that does not exist; `PARAM_MATCH_EPS` is
  asserted in each `Param`'s own numeric scale and the variable's recorded unit
  is the literal `"param"`, which says exactly that rather than claiming mm.

  **Three things 13C had to repair rather than report.** A preview publication
  stores the §8 `BuildResult` and stops — only a current-pointer flip wrote the
  bundle document that carries a build's §7 geometry index — so a 2C candidate
  had no namespace and every tag anchor came back `unaddressable_anchor` for a
  tag the build had certainly placed; `build_bundle` is now one function both
  paths call. And two earlier stages' family clauses pinned
  `bench.scoring.CORPUS_FAMILIES` as an **exact mapping**, which says "no later
  stage may ever register a family" — never Stage 11's or Stage 12C's claim,
  and red the moment the solve family landed. Each now pins its own stage's
  registration plus a **named** list of the families declared after it, so an
  unaccounted family is still a red build. This is the 13B repair pattern
  applied a second time, and the second occurrence is the argument for the
  pattern: a count written as an absolute is a claim about every future stage.

  **Two more the closing run found, both in the ceiling refusals §6.3 says
  must carry evidence.** (1) `build_budget_exhausted` was coming back with no
  best iterate at all. The base point's residual was being evaluated *after*
  the finite-difference Jacobian, and `best_x` — the only thing such a refusal
  can carry — is recorded by an evaluation, never by a probe that raised, so a
  budget spent inside the first Jacobian left the refusal with a bare name.
  The base evaluation now runs first; every build it needs is already in the
  solve's own cache, so it costs nothing and the refusal carries what the
  solve had reached. (2) `unbuildable_parameter_iterate` was firing only for a
  candidate whose *script* raised. A candidate can instead build geometry the
  kernel then refuses to **fingerprint** — `normal_at` on a zero-radius
  cylinder's side face raises `StdFail_NotDone` out of OCP — which kills the
  build worker, and `run_build` reports that as a raw `ValidationError` rather
  than a failed `BuildResult`. Both are "a candidate whose preview build
  failed" and both are now that named refusal, carrying the worker's own error
  labelled `source: build_worker` so it is never mistaken for a script error.
  `SandboxDeniedError` is deliberately not swallowed: an unavailable backend is
  not a fact about the geometry.

  **And the citation audit paid for itself a third time, on drift no Stage 13
  edit caused.** `docs/cli.md`'s scoped "no solver" sentence moved 255 → 390
  under this stage's own `heph solve` sections, and the four mission-rule
  citations moved +8 lines each under an unrelated insertion into this file
  made while the 13C suite was running. All five were re-resolved. The one
  that broke was the citation to mission rule 1 — the rule that says a gate is
  a command — which is the case the per-sub-stage audit exists for.

  The CI lane is renamed `stage gates 13A-13C` with the suite it now runs, and
  its timeout moves 45 → 75 minutes for a measured reason: 13C is the first
  solve suite that spends kernel time per iterate, because every 2C candidate
  is a preview build. A lane that times out is a red build that says nothing
  about the gate.

  **Status of clause 55's Tier 3 row, stated so no matrix can round it up
  (2026-08-30).** The clause has two halves and they have two kinds of
  evidence, exactly as G11C clause 12 and G12C clause 51 do. Its **machinery**
  is Tier 1 and closed: the family and its splits, `record_solve_baseline`, the
  ≥3-seed floor, the `insufficient_solve_seeds` refusal that writes nothing,
  and the carve-out `split_name` performs before the aggregate is formed — all
  pytest assertions, run by the `stage gates 13A-13C` CI job. Its **number** is
  Tier 3 and **outstanding**: no `solve_baseline.json` exists, taking it is a
  detached `heph bench run` at ≥3 seeds with the epoch's reference model
  (rule 3) followed by `heph bench score`, and it is archived bench evidence
  rather than a CI clause. No bench was run for this stage and no baseline
  artifact was written or fabricated. The honest report of this row is
  *machinery closed, measurement outstanding*, never green — and `heph bench
  score` itself prints `solve family: NOT MEASURED … outstanding` on every
  archive that ran no solve task, and `solve family: N runs measured, NOT
  BASELINED` on one that ran too few, so the absence is stated by the tool that
  reads the evidence and in the distinction that tells an operator which of the
  two sweeps to take.

**The document amendments this stage carries, each landing with its own
machinery.** `ASSEMBLY.md` §1's `NO SOLVER` bullet, `KINEMATICS.md` §0's first
bullet, and `tool_schema.md`'s `check_assembly` "There is no solver." sentence
land **with this amendment**, ahead of 13A's code, and that ordering is
deliberate rather than sloppy: 13A's constraint-id target does exactly what
`ASSEMBLY.md:56-57` forbids as written, so shipping 13A first would be a
sub-stage of machinery its own binding rule prohibits, and a normative tool
document carrying a `solve_pose` signature block beside an un-scoped "There is
no solver." would contradict itself for the whole duration of a *passing* G13A.
None of the three sentences is deleted; each is **scoped**, keeps its
no-writeback force, and gains a dated pointer to Stage 13. G13A clause 14
asserts all three as landed text, plus a `solve_pose` heading with no un-scoped
denial beside it, the tool-count repoint, this block's writeback refusal present
**in `mission_plan.md`'s own words** rather than as a citation, and the
citation audit below. `ASSEMBLY.md` §4's "No placement solver." and
`KINEMATICS.md` §7's "No placement/assembly solver" are scoped at **13B**, where
transform-space placement actually ships. **A fourth sentence, found while this
block was being written and recorded rather than quietly fixed**:
`docs/cli.md`'s `heph joints` section says "there is no per-script joint syntax
and no solver", which is true today and becomes false when 13A ships
`heph solve pose`. It is scoped at **13A**, not here, because unlike the other
three it names a CLI surface rather than a rule, and scoping it before the verb
exists would describe machinery that does not — and G13A clause 14 asserts the
pair there the same way it does for `tool_schema.md`. `VALIDATION.md` §5 (proposals
delivered to the reviewer explicitly as non-evidence) and the three
`tool_schema.md` tool headings land with the sub-stages that ship them;
`VALIDATION.md` §1 gains the corpus split at 13C. **`script_contract.md` changes
nothing**, and it is named here because silence in an amendment manifest is a
claim: part scripts declare no solve, `PARAMS` and `hc` are untouched, the
`CHECKS` facade gains **no** solver surface in either scope — a predicate that
could read a proposal would let an acceptance check pass on a computation
instead of on geometry — and the 13C parameter solve rides `build_part`'s
existing transient-override preview contract without amending it.

**The tool-surface pin moves per sub-stage: 54 → 55 at 13A, 55 → 57 at 13B.**
Three tools land (`solve_pose`, `propose_placement`, `read_proposals`) and 13C
adds none — its space is an enum value on an existing tool, the 8A/8B lever
applied. The base is **54**, not the 53 `SOLVER.md` carried when it was drafted:
Stage 12C's `compare_to_scan` moved it, and G12C.42 recorded that move with its
pre-stage constant. Because both pins are literal `assert len(...) == N` on an
existing suite, **each sub-stage repoints them as it lands** or "existing suites
stay green" fails on the sub-stage that adds the tool. **This block edits no
other stage's gate text**, G12C's constants included.

**A citation audit is a precondition on every sub-stage.** `SOLVER.md` was
drafted at `ab0cf66`, before Stage 11 (`d9d845f`) and Stage 12 (`668064f`)
landed, and those stages amended five of the documents it cites by line — roughly
thirty of its citations had drifted by up to 550 lines, two of them
load-bearing rather than cosmetic, because a gate clause that greps a line
number is a clause nobody can write once the number moves. All of them were
re-resolved against `HEAD` on 2026-08-30 before this block landed, and every
sub-stage re-runs the audit mechanically as part of its own gate, in two halves:
every `file:line` citation in `SOLVER.md` resolves **by range** inside the file
it names, and every citation in that document's **anchor register** resolves to
text containing its registered anchor. Documents drift under other stages; a
spec that cites them by line has to be re-measured, not trusted.

**The anchor half was tightened on 2026-09-01, under rule 1.** Both this
paragraph and `SOLVER.md` used to state it as a universal — *every* citation
resolving to text containing its anchor — which no gate can assert, because a
line number carries no per-citation expectation a parser can derive; the
machinery underneath it checked ranges universally and anchors over a list
curated inside two test files. An independent verifier found the gap, and rule 1
resolves ambiguity by **tightening, never waiving**: the anchor half is now
scoped to an enumerated register that lives in the normative document
(`SOLVER.md`'s Amendment manifest), all three sub-stages parse that register
rather than keeping private lists, and each asserts that the list it checks *is*
the register. No clause was deleted and none was relaxed — the claim now made
is the claim now asserted, which is more than the old sentence ever bought.

**A second independent pass on 2026-09-01 returned two further findings, and
both closed by tightening as well.** (1) **The epsilons were letting the solver
grade itself.** G13B clause 18 and G13C clause 44 each derive their accuracy
bound as `tol * FACTOR * kappa`, and `SOLVER.md`'s Gates preamble says the
*fixture* records `kappa`; both implementations read it from the record instead
— the solver's own reported conditioning, pinned by nothing — so a solver
reporting an inflated number would have widened the tolerance it was being
graded against with the gate still green. It sat ~700x from vacuous in the
shipped tree and would have been undetectable if it moved, which is the
self-grading shape §7's independent verification exists to refuse, arriving
through the gate's own arithmetic instead of through the measurement. The
conditioning is now recorded per fixture *as arithmetic* — `12/π` and `6√2/π` at
13B, exactly `2` at 13C, each derived from the part dimensions and the
`unit_scaled_v1` weights — the epsilons are derived from the recording, and the
solver's report is separately held to it within a declared band. Both suites
also assert the rule over their own source, so the next call site cannot regress
quietly. (2) **A gate sentence the tree contradicted.** G13A clause 17 claimed
"`tests/stage9a`–`stage9c` unchanged"; 13C's two new corpus tasks had to move
stage9c's count pin, and no clause asserted the sentence at all, so a passing
G13A coexisted with a normative sentence its own tree denied — the drift shape
this stage's per-sub-stage audit exists to catch, arriving in the gate text
rather than in a citation. It is tightened to the delta (9a and 9b untouched;
stage9c's corpus pin repointed by 13C clause 54, 23 → 25) and G13A now asserts
that delta, holding the pin equal to the public corpus on disk rather than to a
literal. *That closure needed a second pass, and the second pass is the
instructive one:* it was applied to `SOLVER.md` and to this record, while the
**plan's own G13A gate summary** — hundreds of lines above, and the block a verifier is
sent to read — still carried the superseded absolute verbatim, so the plan
contradicted itself for the length of a green matrix. It survived because
clause 14 asserted only the writeback refusal in this file and nothing asserted
the plan's gate summaries. Both are now closed: the summary states the delta,
and clause 14 asserts the summary *and* that the old absolute appears in this
file only in quotation marks, as the dated record of what was replaced.
**Neither closure deleted or relaxed a clause**, and the count stands
at **56**.

**Findings discipline (D5), satisfied before this block landed.** The adversarial
pass against `SOLVER.md` returned six confirmed findings — three blocking, three
major — and an independent audit then read each closure against the code it
cites rather than taking the fix author's word. All six were closed by
**tightening**; no gate clause was deleted or weakened, and the count stands at
**56** (G13A 17, G13B 26, G13C 13). The closures worth recording here, because
each is a trap a later implementer would otherwise fall into: a solver graded on
`ConstraintResidual.slack` would have reported a bracket lying flush in the
right plane and **facing the wrong way** as converged, since `coincident`'s
`slack` is `tol_mm - gap` while its `satisfied` is `gap <= tol_mm and opposed` —
so the verdict is read from `satisfied`, and the class predicates were given real
gradients so the solver can flip the part rather than only failing it at
verification; gate clauses demanding 1e-9 of *solved* quantities were replaced
with per-fixture epsilons derived from the declared tolerance and the recorded
conditioning, since residual accuracy and solution accuracy are different
quantities related by the conditioning; the determinism tier was re-cut from
whole solves to **blocks**, because the earlier draft gated a pose solve at D1
on digits that come out of kernel anchor resolution; the four admitted kinds
were shown to be non-smooth or singular at exactly their own solutions — the
same defect used to *exclude* `distance` — and each gained a smooth
reformulation with a gated closed-form identity back to the engine's number; a
refusal name asserted in three places but listed in no closed set was **removed**
rather than listed, because it was unreachable through any input schema and a
schema that cannot express the field is a stronger guarantee than a refusal
nobody can trigger; and the amendment ordering was moved forward to 13A for the
reason stated above. The audit found seven further defects inside those closures
and closed them with them, including two counting assertions that reality
contradicted — the tool surface is 54, not 53, and **zero** of the 54 result
schemas are closed rather than "all 53 are `additionalProperties: true`" — both
of which would have failed on landing rather than degraded quietly.
`SOLVER.md` is promoted from DRAFT to normative by this amendment.

**Gates are commands here too, and the lane lands with the first sub-stage that
has a suite to run.** No Stage 13 suite exists yet — this block is the
amendment, not the machinery — so `.github/workflows/ci.yml` is unchanged by it
and `release.yml`'s prior-gate list is unchanged with it. **13A adds both, in
one change**: a lane on the pattern the Stage 11 and Stage 12 lanes
established, plus that check name in `release.yml`'s prior-gate list, because
`tests/stage7h::test_the_prior_gate_check_names_every_ci_job` asserts set
equality between the two and a lane added without the list entry turns a green
gate red. Rule 1 is the reason the lane is not optional: three Tier 1 gates
that only ever pass on a developer's machine are not gates yet.

**The lane that landed is named `stage gate 13A`, not the `stage gates 13A-13C`
this paragraph first prescribed, and the correction is deliberate** (amended
with 13A, 2026-08-30). A lane runs the suites it names, and only
`tests/stage13a` exists — the same paragraph's own rule is that "a lane naming
a suite that does not exist is a red build, not a placeholder", so a label
claiming 13B and 13C would have been that failure in the job title instead of
the command. Stage 12 set the precedent exactly: its lane was `stage gates
12A-12B` until 12C shipped its suite, and the rename rode the change that added
it. 13B and 13C rename this one the same way, and the `release.yml` entry moves
with it in the same change, because the set-equality assertion above is what
makes forgetting either half loud.

**Numbering, unchanged from the Stage 11 block that settled it.** D4 option (a)
holds: `SOLVER.md` is document **15** and **Stage 13**, with the gate names
G13A/G13B/G13C and the suites this block names.
`docs/frontier-staging-proposal.md` §3.3's ready-to-paste block labels this
capability "Stage 12" and its gates "G12A"–"G12C" because it predates that
resolution and predates the six findings; it is superseded by the text above and
retained only as the drafting record. Computer-aided manufacturing (`CAM.md`)
remains Stage 14 and structural analysis (`PHYSICS.md`) Stage 15.

Signpost, so the stage list is not read as the whole shipped surface: a 2D
laser/waterjet cut-file path (`heph cam emit`, DXF-only, no machine program)
and the `cnc_router`/`waterjet` DFM packs shipped as issue-driven engine work
outside any stage heading (issues #28/#30, commits `f318dbd`/`9a68bb2`). They
are ordinary tested engine code, not gate evidence. `CAM.md` §2 blesses the 2D
substance and its §1.4 records the prior claim on the `heph cam emit` verb
name, which the Stage 14 landing must reconcile.

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
