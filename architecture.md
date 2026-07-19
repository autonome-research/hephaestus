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
| Scripts contain no imports; `PARAMS = {"x": Param(5, min=2, max=10)}`, `p.x`, `hc.tab_w`, `part.geometry`, `tag(face, "tread_top")`, `part.feature("tread_top").surface_finish` | Scripts execute in a preamble-injected namespace with a small extension API: bounded params, project-shared constants, a part output object, topology tagging. Specified in `01-script-contract.md`. |
| Failure message: `[error] Line 46:14 — Failed creating a fillet…`, `Built successfully through line 44`, last-good stats `1 bodies / 1 solids, size [250.0, 200.0, 18.0] mm, volume 868892.28 mm³, sealed=True, genus=0`, hint `inspect_part(name, last_good=true)` | The executor is statement-level incremental with per-statement checkpointing. Errors carry source frames, the last successful statement, last-good metrics including manifold invariants, and the last-good state stays renderable. |
| Tool chips: `Create`, `Edit` (diff), `Build` ("438 faces" / "success"), `Measure Overlap`, `Inspect — rgb\|mask, 2 views` with labeled thumbnails (`iso`, `+X`), `Query Build Snapshot`, `Load Skill`, `Search Store`, `Search Materials`, `Ask question (N)`, `Import` | The agent tool surface. Hephaestus mirrors it in snake_case (the error hint shows the real API is snake_case: `inspect_part`) and extends it. Specified in `02-tool-schema.md`. |
| Tabs `Files / Script / Results / Scrapyard`; Results = `GEOMETRIES 25` with per-solid visibility; per-part `PROPERTIES` panel; per-part agent tabs each with `v1*`; top bar `Publish · v1* · Rebuild`; URL `/session/{uuid}` | Project = set of parts; one script, one agent context, one dirty-flagged version per part. Hephaestus replaces the session/version model with git (§5). Scrapyard (community sharing) is explicitly deferred. |
| Face click → "Quick edit — 1 face" popover → "Ask a new agent…" | Selection spawns a scoped agent with the selection as context. No parametric direct manipulation anywhere in the product. Hephaestus adopts this and strengthens it with source maps (§4.4). |
| Composer: model selector ("Sol"), DFM toggle, doc attach, screenshot; agent volunteers static FEA; export surface: STEP | Model selection is a UI concern (Hephaestus is model-agnostic at the core). DFM is a mode that loads rule packs. FEA is a pluggable analysis. Export must exceed STEP-only (§4.6). |

## 2. System overview

Five components, strictly layered. Every arrow is an in-process call or a
typed message; nothing in a lower layer knows about a higher one.

```
┌────────────────────────────────────────────────────────┐
│  Clients:  CLI (heph)  ·  MCP clients  ·  Web UI       │
└──────────────▲─────────────────▲───────────────────────┘
               │ stdio/HTTP MCP  │ HTTP + WS
┌──────────────┴─────────────────┴───────────────────────┐
│  server/   MCP server + HTTP API + event stream        │
└──────────────▲─────────────────────────────────────────┘
               │ Python API
┌──────────────┴─────────────────────────────────────────┐
│  agent/    harness: loop, tool dispatch, model adapters │
└──────────────▲─────────────────────────────────────────┘
               │ Python API
┌──────────────┴─────────────────────────────────────────┐
│  core/     executor · kernel services · render · checks │
│            registries client · project store (git)      │
└────────────────────────────────────────────────────────┘
```

`core/` MUST be importable and fully functional with no server, no agent, and
no network: `heph build`, `heph render`, `heph check`, `heph export` are thin
wrappers over it. This is the engine-first invariant and the mission's Stage 0.

## 3. core/

### 3.1 Executor

Runs a part script in a sandboxed subprocess with the injected namespace from
`01-script-contract.md`. Requirements:

- **Statement-level execution.** The script is split into top-level statements
  via `ast`. Statements execute sequentially; after each one the executor
  records a checkpoint: statement index, source span, names bound, and — for
  names bound to build123d shapes — a metrics snapshot (solid count, bbox,
  volume, face count, `sealed` = is-manifold, `genus`).
- **Failure semantics.** On exception, the build result MUST include: the
  failing line and column, exception type, a source frame (±2 lines), the last
  successfully executed statement, the last-good metrics snapshot, and a
  machine-readable pointer that `inspect_part(part, last_good=True)` will
  render. This reproduces (and is acceptance-tested against) the observed
  Smith error shape.
- **Determinism.** Same script + params + hephaestus version ⇒ identical
  geometry (bit-stable STEP is not required; metric-stable within 1e-6 mm is).
- **Sandboxing.** Subprocess with resource limits (CPU time, memory, wall
  clock) and no network. The namespace whitelist is the only import surface.
  This is a local-first tool, not a hardened multi-tenant service; limits are
  for hygiene (runaway booleans), not adversarial isolation. DECISION(ours).
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
- **mask** — flat-shaded ID render where each solid (or each tagged face, in
  face mode) has a unique color from a published bijective palette; the
  color↔id table ships with the image so the model and tests can decode it.
- **section** — rgb with a section plane applied.
- **explode(t)** — per-solid translation along assembly axes, t ∈ [0, 1].

Implementation: export tessellation from OCP, render via a headless rasterizer
(VTK offscreen or trimesh/pyrender). Renders MUST be deterministic across CI
runs on the same platform tier (SSIM ≥ 0.995 against goldens). DECISION(ours):
we render server-side for the agent loop and ship GLTF to web clients, which
render live locally.

### 3.4 Checks engine

Executes `CHECKS` blocks (see `01-script-contract.md` §6) against a build:
each check is a named predicate over kernel-service results with a tolerance.
Output is a machine-readable report (pass/fail per check, measured values).
Checks are re-run on every build of the part and on every build of any part
whose shared constants it consumes. DECISION(ours) — no observed equivalent;
this is Hephaestus's persistent verification layer.

### 3.5 Project store

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
on a per-part advisory lock in `.heph/locks/`; the agent's `edit_part` and a
human's editor save go through the same store API and the same lock. Writes
carry the base content hash they were computed against; a stale hash is a
conflict returned to the caller (the web editor surfaces it as a merge
prompt; the agent receives it as a failed edit with the current content and
retries against reality). Reads (render, measure, export) run lock-free
against the last completed build artifact, so a long build never blocks
inspection of the previous state. Two *clients* attached to one part share
one agent context; the event stream is the serialization point for what each
sees. DECISION(ours) — no concurrency behavior was observable in the
reference product.

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
- **dfm/** — per-process rule packs (laser_cut, cnc_router, fdm): predicates
  over geometry + material (min feature size, kerf, min internal radius, wall
  thickness) that the checks engine can run when the part declares that
  process. Powers the DFM mode.

## 4. agent/

### 4.1 Harness

An async loop: user message → model → tool calls → tool results → model → …
with streaming events published for clients. Model adapters normalize
Anthropic-API, OpenAI-compatible, and local (llama.cpp/ollama) backends behind
one interface; the tool schema is defined once in `02-tool-schema.md` and
rendered per-adapter.

**Context policy** (configurable, defaults stated): system prompt + loaded
skills + project summary (parts list, `hc` params and constants, check
status) + rolling transcript. Images are the budget hazard: only the most
recent K=3 `inspect_part`/`query_snapshot` results keep their images; older
image blocks are replaced in-context by a text stub (`[render: cat_step iso/
mask, superseded — re-run inspect_part to view]`) so the model always knows
re-inspection is one call away. At T=70% of the model's context window the
harness compacts: tool-call bodies collapse to one-line results, and
transcript segments older than the last successful build are summarized into
a pinned "session so far" block (design intent, decisions, open problems,
current check status) — the build artifact, not the transcript, is the source
of truth for geometry state, which is what makes aggressive compaction safe.
Per-session token and cost budgets are enforced by the harness with an
`ask_user` escalation at 90%. DECISION(ours) — none of this is observable
in the reference product, and it is where agent harnesses actually live or
die.

### 4.2 Agent scoping

One agent context per part (matching observed per-part tabs), plus a project
orchestrator context that can create parts and delegate. Scoped quick-edit
agents (§4.4) are children of a part context.

### 4.3 Structured questions

`ask_user` emits an options block (observed: "Ask question (4)"); in CLI it
renders as a numbered prompt, over MCP as structured content, in web as a
widget. The loop suspends until an answer event arrives.

### 4.4 Selection → scoped agent

A client sends a selection reference: `{part, kind: solid|face|edge, mask_id}`.
The harness resolves it through the source map to `{label?, tag?, statement,
source span}` and spawns a child agent whose context contains the part script,
the resolved provenance, and a crop of the current render centered on the
selection. This reproduces Smith's "Quick edit — 1 face → Ask a new agent"
with strictly more context than Smith demonstrates.

## 5. server/

- **MCP server** (FastMCP, stdio for local, streamable HTTP for remote):
  exposes the full tool schema plus project/session management. An MCP client
  with no Hephaestus UI can run the entire loop; this is Stage 3's gate.
  HTTP transports bind to localhost and require a generated bearer token by
  default; binding beyond localhost requires an explicit flag whose help text
  points at the threat model.
- **HTTP + WebSocket API** for the web client: project CRUD mapped to git,
  build/render artifact serving (GLTF, PNGs), agent event stream, selection
  and answer events. Same bind/token defaults.

## 6. web/

React + TypeScript. Vite. three.js viewport consuming GLTF with per-solid
metadata (id ↔ mask palette ↔ tree row). Monaco for scripts. Panels: file
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
   sandbox (subprocess, namespace whitelist, no filesystem/network, resource
   limits) is the boundary; the whitelist is the attack surface and is kept
   auditable — additions to the injected namespace require a PR touching one
   reviewed module. Residual risk accepted: OCP/OCCT native crashes can DoS
   a build worker; workers are restartable and per-build.
2. *Registry content*. Executable registry content gets sandbox parity with
   part scripts (§3.6); contextual content is a prompt-injection vector that
   delimiting reduces but does not eliminate — the enforced backstop is that
   *no tool escapes the sandbox*, so a hijacked agent can at worst corrupt
   the project (git-recoverable), not the machine. Hash pinning makes
   registry supply-chain changes explicit and reviewable.
3. *Remote transports*. Localhost + bearer token by default (§5); TLS and
   real authn are deliberately out of scope for the mission — the documented
   deployment posture for shared use is "behind your own reverse proxy," not
   "expose heph serve."
4. *Bench integrity*. Private gate split, provenance-hashed goldens, and
   solutions-validated tasks (see `03-verification.md`).

Explicitly out of scope: multi-tenant isolation, DRM on designs, and
defending a user who pastes hostile scripts and also disables the sandbox
(`--no-sandbox` exists for kernel debugging, prints a warning, and refuses
under `heph serve`).

## 8. Explicit non-goals (current mission)

- Scrapyard-style community design sharing (deferred by decision; registries
  cover the ecosystem need first).
- Parametric direct manipulation (drag-editing dimensions in the viewport).
  Selection → scoped agent is the interaction model.
- Multi-tenant hosted service hardening.
- Training or fine-tuning models. The corpus may eventually support it, but
  the mission targets harness quality with off-the-shelf models.
