# 04 — Mission Plan

The droid mission implementing Hephaestus. A de-risking spike plus eight build stages (S, 0–7), strictly ordered;
each stage lists deliverables, then its **gate**: the complete, machine-
checkable exit criteria. A droid MAY parallelize within a stage but MUST NOT
begin stage N+1 deliverables before stage N's gate is green in CI. Verifier
tiers reference `03-verification.md`.

Reading `00-architecture.md`, `01-script-contract.md`, and `02-tool-schema.md`
is prerequisite to Stage 0.

---

## Stage S — De-risking spike

The mission's two riskiest infrastructure assumptions are converted to
evidence before anything is built on them. Deliverables: (a) a pinned CI
container image with build123d + OCP installed, in which a scripted box is
built and rendered on the software rasterizer **twice in separate jobs** with
byte-comparable determinism (SSIM = 1.0 or pixel-identical); (b) a FastMCP
echo server exercising elicitation from a scripted client over stdio and
streamable HTTP — or, if elicitation support is inadequate, a written
fallback decision (structured content + follow-up call) committed to
`02-tool-schema.md` §ask_user before Stage 2; (c) a 10-minute OCCT sanity
script exercising fillet failure, boolean of 30 solids, and STEP round-trip
in the image, timed against the performance budgets.

**Gate GS**: the spike workflow is green in CI on two consecutive runs; the
image tag is recorded in `05-repo-conventions.md`; any fallback decisions are
merged as doc amendments. Nothing else may merge first.

## Stage 0 — Kernel executor and script contract (headless)

Deliverables: `core/executor` (statement-level incremental execution,
checkpoints, sandbox, param validation, `hc` namespace with dependency
tracking, source maps), `core/kernel` services (metrics, interference,
clearance, distance, mass, sealed/genus), `core/checks` engine, build-result
records per contract §7, and the CLI verbs `heph build`, `heph check`,
`heph lint`. Vendor the two recovered Smith scripts into `corpus/reference/`
with a `globals.py` reconstructed from their `hc.*` reads.

**Gate G0** (Tier 1): `uv run pytest tests/stage0 -q` exits 0, covering:
contract tests on both reference scripts (25 and 3 labeled geometries; shelf
bbox 380×280×250 ±0.5; all sealed, genus 0; panel/spline/collar pairwise
interference < 1e-6 mm³); failure-shape fixture reproduces every field of the
captured error including last-good metrics; param bounds enforcement at
both part and project scope with stale-part propagation from a project-param
change; determinism; sandbox denial; source-map resolution for all solids
and tags at the scopes promised by architecture §3.1; addressing-grammar
resolution incl. `#k`/`#*` dedup and candidate-listing errors; tag-drift
fingerprinting (an edit that displaces the `tread_top` selection triggers a
`tag_drift` warning; an equivalent no-op refactor does not); performance
budgets for build and measure.
`heph build corpus/reference/parts/cat_step_shelf.py --json` exits 0 and its
JSON validates against the BuildResult schema.

## Stage 1 — Render service and grounded observation

Deliverables: `core/render` (offscreen rgb/mask/section/explode, named
cameras, bijective mask palette + legend), `heph render`, GLTF export with
per-solid ids, and the `inspect_part` / `query_snapshot` implementations as
library functions.

**Gate G1** (Tiers 1+2): `uv run pytest tests/stage1 tests/render -q` exits 0:
render goldens for both reference parts at `iso`/`+X` in all channels (SSIM ≥
0.995 across two consecutive CI runs — determinism is part of the gate); mask
decode equals legend exactly; every labeled solid visible in ≥ 1 standard
view; explode(1.0) renders differ from explode(0.0) with strictly increased
silhouette area; GLTF validates (`gltf-validator`) with solid count matching
the build result.

## Stage 2 — Agent harness (CLI-complete product)

Deliverables: `agent/` loop with streaming events; model adapters (Anthropic
API, OpenAI-compatible, ollama); the full tool schema of `02-tool-schema.md`
except run_dfm/generate_drawing/generate_doc/deferred; skills registry loader
with an initial 6-pack of authored skills (build123d idioms; profiles &
extrusion; booleans & clearances; sheet-goods & joinery; fillets & failure
repair; parts-store usage); a minimal parts store (metric screws, heat-set
inserts) and materials registry (plywoods, PLA/PETG, 6061); `heph agent`
interactive CLI with ask_user rendering; bench harness.

Additional deliverables: the project orchestrator context (creates parts,
delegates to part agents, owns cross-part checks) and the context policy of
architecture §4.1 (image eviction, compaction, budgets) as implemented,
configurable behavior.

**Gate G2** (Tiers 1+3): `uv run pytest tests/stage2 -q` exits 0 (tool
dispatch unit tests with a scripted fake model driving every tool through a
recorded session, including a repair flow off the failure fixture; adapter
conformance against recorded API fixtures; an orchestrator test where the
fake model creates two mating parts through delegation and a cross-part
check passes; a context test proving image eviction and compaction preserve
the pinned session summary and that a post-compaction fake model can still
answer a question about a pre-compaction decision from the summary). Bench:
corpus v0 aggregate lower-90% Wilson bound ≥ 0.60 (8 tasks × ≥3 seeds) with
the designated reference model; `repair-fillet` specifically MUST pass 3/3
seeds (error-shape quality is the point of the stage). Transcripts + result
JSON archived as CI artifacts.

## Stage 3 — MCP server

Deliverables: `server/mcp` via FastMCP — stdio and streamable-HTTP transports
— exposing the tool schema plus `open_project`/`list_parts`; ask_user mapped
to MCP elicitation (fallback: structured content + follow-up call);
`heph serve --mcp`.

**Gate G3** (Tier 1 integration): `uv run pytest tests/stage3 -q` exits 0: a
scripted MCP client (no Hephaestus code on the client side) connects over
stdio, opens the reference project, and completes create → edit → build →
inspect (receives images) → measure → export STEP; the exported STEP
re-imports with matching volume. Same flow passes over HTTP transport.
Claude Code configured with the server completes bracket-101 end-to-end in a
recorded, replayed session committed as a fixture.

## Stage 4 — Web workspace, read-only

Deliverables: `server/http` (project/build/artifact/event APIs over the same
core), `web/` with: project tree, script viewer (Monaco, read-only), Results
panel (geometry list + visibility + properties + check status), three.js
viewport (GLTF, view cube, grid readout, explode slider, section plane), and
live agent-stream panel rendering tool chips, thought sections, images, and
ask_user widgets — visual language may differ from Smith; information
structure MUST match `02-tool-schema.md` outputs.

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
in the transcript as a failed edit carrying current content, and no write is
lost (both contents recoverable from git).

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

Deliverables: packaging (PyPI + npm per `05-repo-conventions.md`), versioned
docs site, demo recording script, CONTRIBUTING + registry contribution guide,
issue templates, Apache-2.0 headers, model-leaderboard page generated from
bench artifacts.

**Gate G7**: clean-machine install test in CI (`pipx install` → `heph
--version` → Stage-3 MCP smoke test passes); `LEGAL-REVIEW.md` present at
repo root with its checklist fields completed and signed off (reviewer,
date, scope: ToS analysis of the reference product, reference-fixture
publication decision, trademark scan of identifiers) — CI checks the file's
schema; the review itself is the one deliberately human step in the mission
and blocks only publication, not development; docs build without warnings;
`bench.yml` publishes the leaderboard artifact; all prior gates green on the
release SHA; tag `v0.1.0` cut.

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
   `03-verification.md` run in Tier 1 from Stage 0 on. Implementation note
   for the executor: per-statement *full* metric snapshots are permitted to
   be lazy (checkpoint the shape reference eagerly; compute metrics on
   failure or on demand) — the budgets are the arbiter, and the failure-shape
   tests only require last-good metrics to be *available*, not precomputed.
5. **Scope discipline.** Deferred items (FEA, STEP import, community
   sharing, kerf-aware auto-nesting) enter only by amending this plan with a
   new gated stage.
