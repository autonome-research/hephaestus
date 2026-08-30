<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# 05 — Repo Conventions

## Layout

Monorepo at `github.com/autonome-research/hephaestus` (single repo keeps the
tool schema, core, and clients atomically versioned through the mission):

```
opstore/    Python ≥3.11 workspace package: generic WAL/idempotency, leases,
            admission, CAS blobs, and reachability/GC. No CAD/agent imports;
            separately tested and bundled in the wheel, not published in v0.1.
core/       Python ≥3.11. Deps: build123d, ocp, numpy, trimesh/pyrender (render),
            ezdxf (dxf), pygltflib. Consumes opstore through typed adapters;
            managed with uv and strict pyright.
agent/      TypeScript on Node ≥22.19. Embedded Pi SDK sessions, generated CAD
            tools, Python JSON-RPC bridge client, and thread-phase workflows.
            Managed with pnpm; strict tsc and eslint.
server/     Python. FastMCP + FastAPI + websockets; supervises the packaged
            Node agent sidecar over private JSON-RPC/stdio.
web/        TypeScript, React 18, Vite, three.js, Monaco. pnpm workspace.
            (Stage 4: driven as `pnpm --dir web …` with its own lockfile, like
            `agent/`; see "Stage 4 `web/` accepted versions" below for why there
            is no repository-root `pnpm-workspace.yaml`.)
registries/ skills/ parts/ materials/ dfm/ — content, versioned in-repo for
            now; splits out post-v0.1 once the registry format stabilizes.
corpus/     public_fixtures/ contains clean-room CAD contract/e2e projects;
            tasks/ + solutions/ are the public benchmark split. reference/ is
            fetched only inside the isolated private verifier from
            autonome-research/hephaestus-fixtures (recovered scripts + globals,
            pending legal review) and remains gitignored. Private benchmark
            tasks live in autonome-research/hephaestus-corpus-private.
tests/      stage0a, stage0b, stage1…stage7 mirror mission gates; opstore also
            has package-local tests; render/ goldens carry provenance sidecars.
*.md        normative design/mission documents live at repo root in v0.1.
docs/       generated/site-only mkdocs content and assets; links to root docs.
```

## Naming and packaging

- Project name: **hephaestus**; CLI binary: **heph**.
- PyPI: publish as `hephaestus-cad` (the bare name's availability must be
  checked at Stage 7; the import package is `hephaestus` regardless, with the
  distribution name only differing if squatted). npm (web components, if ever
  published separately): `@autonome/hephaestus-web`.
- Python namespaces: internal workspace package `opstore`; product namespaces
  `hephaestus.core`, `hephaestus.server`, and the private bridge/supervisor under
  `hephaestus.agent_bridge`. `opstore` has no separate PyPI release in v0.1 and
  is bundled as an internal wheel component. The TypeScript agent is a
  private workspace package compiled into a bounded sidecar artifact and
  bundled in the Python wheel; it is not a second public product package in
  v0.1.
- `heph build/check/render` MUST work without Node (export ships as the
  `export_part` tool/MCP surface rather than a CLI verb in v0.1; a `heph
  export` verb, if added, joins this no-Node set — see `docs/cli.md`
  "Verbs that do not exist"). The v0.1 native
  secure agent/server platform is Linux x86_64 with probed bubblewrap
  isolation. macOS is supported for agent execution only through a capability-
  tested Docker/Podman/OrbStack-compatible OCI backend running the pinned Linux
  executor profile — DEFERRED (2026-08-13, operator decision): that OCI
  backend ships post-v0.1 as a named Stage 7 deliverable, and in
  v0.1.0-headless macOS refuses script execution by design (see
  `mission_plan.md` §"Stage 7H", G7H amendment). Other packaging lanes run
  core-only tests and MUST fail
  closed for agent/server script execution unless that approved backend passes
  its escape/resource probes. `heph agent` and agent-enabled serving require Node ≥22.19,
  perform an explicit startup
  compatibility check, and execute the wheel's integrity-checked sidecar —
  never a global `pi` or `thread-phase` binary. The supervisor supplies a
  minimal environment and only explicitly approved provider credentials. A
  standalone bundled sidecar may replace the Node prerequisite later without
  changing the bridge.
- Product dependencies are exact-pinned in `package.json` (no caret/tilde) and
  `pnpm-lock.yaml`; the initial spike candidates are
  `@earendil-works/pi-coding-agent@0.80.10` and
  `@autonome-research/thread-phase@6.0.0`. Stage S records the accepted exact
  versions and Node runtime here. Production phases call the Hephaestus
  Pi session service directly through free-runner phase/pattern APIs; no
  thread-phase AgentAdapter package is a runtime dependency. Upgrades require
  the same bridge, session-resume, event-shape, cancellation, and isolation
  tests as the original spike.
- The selected thread-phase release MUST expose `JobRunner`/patterns through a
  native-free public import and the bundled sidecar MUST have no required
  native Node addon. Older releases that declare/eagerly export
  `better-sqlite3` are not eligible even when a custom store is supplied.
  Persistence uses an application-owned async `JobStore` backed by Python
  SQLite over the bridge. CI audits install-time dependencies, import graphs,
  and the built artifact. In particular, thread-phase 6.0.0's transitive
  `openai` dependency must be absent from the compiled sidecar or explicitly
  allowlisted as inert after proving it is not loaded, receives no credentials,
  and has no runtime request path.

## Versioning and git discipline

- SemVer from `v0.1.0` at Stage 7. Pre-release tags `v0.0.x-stageN` at each
  gate, cut by CI when the gate workflow first passes on main.
- Toolchain pinning: exact build123d/OCP/OCCT versions in the uv lockfile,
  exact Pi/thread-phase versions in the pnpm lockfile, and the CI container
  image tag are recorded here at Stage S.
- **Stage S accepted versions** (local spike evidence 2026-07-24, see
  `spikes/REPORT.md`; the CI image landed 2026-08-28 and is consumed BY DIGEST
  rather than by tag — `docker/ci/Dockerfile`, built and pushed by
  `ci-image.yml`, referenced by digest in `ci.yml`, so there is no tag to
  record and a digest is the stronger pin): CPython 3.13.12
  (uv 0.11.3); Node v25.2.1 + pnpm 10.6.5 (engines: pi ≥22.19.0, thread-phase
  ≥22.5.0); build123d 0.11.1; cadquery-ocp-novtk/proxy 7.9.3.1.1 (OCCT 7.9.3);
  fastmcp 3.4.4 + mcp 1.28.1 (protocol 2025-11-25);
  `@earendil-works/pi-coding-agent@0.80.10`;
  `@autonome-research/thread-phase@6.0.0`; bubblewrap 0.11.2.
- **Stage 4 additions** (the web workspace API; see `INTERFACE.md` §2): Starlette
  1.3.1 and uvicorn 0.51.0 are now *declared* dependencies of
  `hephaestus-server` rather than transitive ones, because `server/http` imports
  them directly and an undeclared transitive import is a dependency that
  disappears the day `fastmcp` changes its own. They are the stack `fastmcp`
  already serves streamable HTTP on, so `server/` gains no second web framework —
  in particular, **not FastAPI**: `INTERFACE.md` §2 names no framework and a
  second one buys nothing. `httpx` 0.28.1 is a dev dependency only, for
  `starlette.testclient`. Python ranges stay ranges (`>=x,<y`) here as everywhere
  else in `pyproject.toml`; the no-caret exact-pin rule above is the
  `package.json` rule and is unchanged. `websockets` 16.1.1 joins them as a
  *declared* dependency for the same reason: `GET /events` (`INTERFACE.md` §2.7)
  needs uvicorn to serve a WebSocket, and `heph agent` client mode needs a
  client for one, so relying on it arriving transitively through `fastmcp` would
  be relying on someone else's dependency graph for a feature of ours.
- **Stage 4 `web/` accepted versions** (the workspace client; see `INTERFACE.md`
  §3 and §19 item 15). Exact pins, no caret or tilde, in `web/package.json` and
  `web/pnpm-lock.yaml`, under the same no-semver-drift rule as `agent/`:
  `react` 18.3.1 and `react-dom` 18.3.1 (React **18**, as the stack line above
  says — React 19 is available and is deliberately not taken, because the stack
  is stated in this file and a stack change is an amendment, not an upgrade);
  `vite` 8.2.2 with `@vitejs/plugin-react` 6.1.0 (plugin 6 peers on Vite 8, so
  the pair moves together); `typescript` 5.9.3; `three` 0.185.1 with
  `@types/three` 0.185.4; `monaco-editor` 0.56.0; `@tanstack/react-query`
  5.102.8; `@playwright/test` 1.62.1; `eslint` 9.39.5 with `@eslint/js` 9.39.5,
  `typescript-eslint` 8.68.0 and `eslint-plugin-react-hooks` 7.1.1; `vitest`
  4.1.11 with `jsdom` 30.0.1; `@types/react` 18.3.31, `@types/react-dom` 18.3.7,
  `@types/node` 22.20.1.
  **The CSS-module tooling is Vite's own** — `*.module.css` is a first-class
  Vite input and needs no package, which is the whole reason §3 chose CSS
  Modules plus a token file over a utility framework. There is deliberately no
  component library, no icon package, and no state library: §3 names each
  rejection and its reason.
  **Bundle delivery** (§3, and the packaged-sidecar precedent): `pnpm --dir web
  build` emits `web/dist/`, and the built assets ship **inside the wheel**,
  served by `heph serve --web` from `importlib.resources`. Vite's dev server is
  a development convenience proxying `/api` — the `/events` WebSocket
  included — to a running `heph serve --web`; it is never a deployment.
  The serving process composes the bundle **around** the API application
  (`http/serve.py::with_bundle`), never inside it: `build_app`'s route surface
  *is* §2.3's closed table and a boundary test asserts that in both directions,
  so a static mount added to the app would have had to weaken the check that the
  API serves nothing else. One origin for the operator, one closed table for the
  API. With no `web/dist/` the server says so on stderr and serves the API alone.
  **Gate G4's browser suite** (`pnpm --dir web test:e2e`) therefore needs
  `pnpm --dir web build` first, plus `pnpm --dir web exec playwright install
  chromium` once per machine; it runs against a real `heph serve --web` on
  `corpus/public_fixtures/workspace/` and is described in `web/e2e/README.md`.
  It is **renderer-pinned** through its G4.7 golden and is deferred in CI beside
  `tests/render` for that one reason (see `.github/workflows/ci.yml`'s scope
  note); it fails by name on an unmatched renderer rather than skipping.
  `@autonome/hephaestus-web` stays reserved and unpublished.
  `web/` is its own pnpm package driven as `pnpm --dir web …`, mirroring
  `agent/`, and **not** a member of a repository-root pnpm workspace: a root
  `pnpm-workspace.yaml` would hoist `agent/`'s lockfile, and
  `pnpm --dir agent install --frozen-lockfile` is load-bearing in CI and in
  `server/hatch_build.py`. Two packages, two lockfiles, one command shape.
- **Stage 7H additions** (packaging; see `PACKAGING.md`): `@sinclair/typebox`
  is a *runtime* dependency of the sidecar, exact-pinned at `0.34.52` — it was
  declared under `devDependencies` with a caret through Stage 7G, so a
  production install produced a sidecar that died on its first import.
  `esbuild@0.28.1` (devDependency) bundles the two sidecar entry points into the
  bounded artifact the wheel ships. The bundle leaves exactly two bare
  specifiers unresolved — `bufferutil` and `utf-8-validate`, ws's optional
  native accelerators, required inside a try/catch — and contains zero `.node`
  files, which is how "no required native Node addon" is now discharged. The
  `openai` clause is satisfied strictly: thread-phase contributes **zero**
  import edges into `openai`; the SDK present in the bundle is reached only
  through `@earendil-works/pi-ai`'s lazily dynamic-imported provider adapters.
  Spike dispositions, binding on later stages:
  1. STEP hashing normalizes the `FILE_NAME` header timestamp
     (`spikes/cad_kernel/box_build.py::normalize_step`); STL is hashed raw.
     **Stage 12A sharpens what that normalizer is for, because the distinction
     is the design** (`MESH_INGEST.md` §1.4): the `FILE_NAME` normalizer is an
     *export-determinism* device — it exists so two **exports** of one shape
     compare equal. **Import** hashing normalizes nothing, deliberately, because
     a build input's identity must be the file's identity. Meshes have the same
     class of volatile header (an STL `solid` line, an OBJ banner, a PLY
     `comment`), so the same problem appears — and the answer is not to
     normalize the input hash but to carry a **second, separately named** hash:
     `mesh_canonical_hash`, over the canonical blob, which is geometry identity
     and never an invalidation key. Two builds whose input hashes differ but
     whose canonical hashes agree can then say "the file changed, the geometry
     did not" instead of guessing. Reversing that would let a normalizer decide
     what counts as a changed build, which is exactly the authority
     `INGEST.md` §1 keeps in the raw bytes.
  2. CI renderer: pyrender + surfaceless EGL pinned to Mesa llvmpipe via
     `EGL_DEVICE_ID` (`LIBGL_ALWAYS_SOFTWARE` alone is insufficient); the CI
     image must ship Mesa with the surfaceless EGL platform (osmesa not
     required); matplotlib-Agg 3D is the proven byte-identical fallback.
     **Pinned CI image (landed 2026-08-28):** `docker/ci/Dockerfile`, built by
     `ci-image.yml`, consumed by digest in ci.yml's `render goldens (pinned
     image)` job —
     `ghcr.io/autonome-research/hephaestus-ci@sha256:94dd58592d531dc6f93a18bb6d0757d553ecea6db29b963c1af38a440d06ce00`,
     renderer `llvmpipe (LLVM 20.1.2, 256 bits)` (Mesa 25.2.8, Ubuntu 24.04
     base by digest). All render goldens and the G4.7 section golden are
     baselined against it; a digest bump is a renderer re-baseline PR.
  3. MCP elicitation works over stdio and streamable HTTP; `ask_user` needs no
     fallback (decline/cancel assertions land in Stage 3).
  4. Production imports thread-phase ONLY via its `/session` and `/patterns`
     subpaths (the root barrel eagerly loads the transitive `openai` SDK; the
     subpaths load 13 modules with zero `openai` and zero native addons;
     `better-sqlite3` is absent — JobStore uses `node:sqlite`-free injection).
  5. Pi tool gating uses a `tools: [...]` allowlist or `noTools: 'builtin'` —
     never `noTools: 'all'`, which also strips custom tools.
- **Tier 3 reference model (mission epoch 1, designated 2026-07-25):**
  `ThinkingCap-Qwen3.6-27B-NVFP4` (qwen3.6:27b) served over an
  OpenAI-compatible vLLM endpoint on the maintainer's workstation
  (self-hosted; endpoint supplied via local provider config, never committed).
  Rationale: the harness must clear its gates with a self-hosted open model.
  Changing the reference model re-baselines thresholds only by explicit PR
  (mission rule 3). Kernel or renderer upgrades land
  only as a dedicated **re-baseline PR type**: it may touch the lockfile/image
  tag, regenerate render goldens via `heph goldens --update` (which refuses on
  a dirty tree), and relax no thresholds; CI attaches before/after golden
  archives to the PR for review. Pi/thread-phase upgrades use a dedicated
  **agent-runtime upgrade** PR type and may not alter public tool/event schemas
  without an explicit contract amendment. Cross-version metric tolerance is
  1e-4 relative (vs 1e-6 within a pinned toolchain); contract tests carry both
  tolerances explicitly.
- Conventional commits; PR-only main; required checks = the current stage's
  gate workflows plus `ci.yml`.
- Design-project convention (user-facing): Hephaestus projects are ordinary
  git repos laid out as `hephaestus.toml`, `globals.py`, `parts/`, and a
  `.gitignore` ignoring `.heph/`. The `heph init` scaffolding verb writes
  exactly that shape (plus `checks/` seeded with the safe cross-part
  template) and refuses a non-empty target; `docs/cli.md` carries the worked
  example.

## Licensing and provenance policy

- Code and docs: Apache-2.0. Registries content: CC-BY-4.0 (skills, docs)
  and Apache-2.0 (part generators, DFM rules).
- Clean-room boundary: this project derives from *observed behavior* of a
  commercial product (screen recording, on-screen scripts, error text
  captured by a user of that product) plus public build123d documentation.
  No decompiled code, no scraped non-public assets, no proprietary model
  weights or prompts are used or accepted in contribution. The two reference
  scripts were produced in the user's own session of that product; because
  the product's terms of service have not yet been reviewed and may speak to
  reverse engineering or output rights, the scripts are held as **private CI
  fixtures**, not published, until the Stage 7 legal review
  (`LEGAL-REVIEW.md`) clears them. Ordinary/fork PR gates use only independently
  authored `corpus/public_fixtures/`. Private-reference parity runs only in an
  isolated verifier against a protected trusted SHA: no `pull_request_target`,
  no PR-code access to repository credentials, no network from the test worker,
  and no logs, coverage, cache, or artifacts containing fixture bytes. The
  verifier emits only a signed aggregate status/leak-scan attestation. All
  acceptance tests assert error/result *fields and information content*, never
  the reference product's verbatim message text or UX copy. `CONTRIBUTING.md` states this boundary
  and CI license-checks dependencies.
- Trademark hygiene: no "Smith"/"Arche" naming in code identifiers or
  packages; the reference product is named only in docs, factually. The same
  rule generalises to **third-party component data**: a store component's id is
  generic or standard-derived (`bearing_608`, `stepper_nema17_frame`), never
  `<vendor>_<sku>`; a vendor name and part number are factual reference and live
  in the record's `datasheet` block only. Publishing scans ids against a
  maintained deny-list (`trademark_in_component_id`), which is deliberately not
  the only control — a deny-list is imperfect and the maintainer review below is
  what actually decides.
- Third-party component data: **reference, do not vendor** (operator decision,
  2026-08-29; `PARTS_STORE.md` §7). A `parts` registry may carry independently
  authored generator source, the nominal dimensions of a published standard, and
  the minimum derived facts its declared interfaces and claims require. It may
  not carry vendor CAD (STEP/IGES/SLDPRT or any converted derivative), vendor
  PDFs, drawing images, artwork or marketing renders, or a bulk transcription of
  a vendor table. A datasheet is referenced by URL and content hash with its
  terms declared, never copied; nothing fetches that URL. Publishing refuses any
  file in a `parts` tree that is not `registry.toml`, `part.json`,
  `generator.py` or `*.md` (`vendored_third_party_payload`). A pack that cannot
  be authored without vendoring something does not ship, and the omission is
  stated loudly rather than resolved by vendoring. Publication of a component
  pack is additionally gated on `LEGAL-REVIEW.md`'s third-party-component-data
  scope field; development is not.

## Registry trust

`hephaestus.toml` pins every registry by content hash (Merkle digest over the
tree); `heph registry update` is the only re-pin path. Executable registry
content (part generators, DFM predicates) has sandbox parity with part
scripts. Contributions to org-hosted registries require review by a
maintainer other than the author; the contribution guide bans referencing
bench corpus tasks by name (CI-grepped) and reproducing their target
geometries (reviewed).

## Quality bars

- opstore/: ruff + pyright strict, 90% line coverage, property/state-machine
  tests, subprocess crash injection, no import dependency on core/CAD/agent,
  and a package README specifying transaction/recovery contracts.
- core/ and server/: ruff + pyright strict, 90% line coverage on core/
  (enforced), property-based tests (hypothesis) for kernel services and adapter-
  contract tests proving `core/project_store` supplies CAD policy above
  `opstore` rather than duplicating its durability machinery.
- agent/: eslint + tsc strict; unit tests cover Pi resource/credential
  isolation, bridge framing, event normalization, session lifecycle, context
  policy, sequential mutation/interaction tools, optimistic hashes, opstore-
  backed mutation replay/recovery integration, dirty-preimage journaling,
  effective-
  parameter build identity, create-only exports, path confinement,
  cross-process session leases, direct
  Pi-session phase invocation, Python-backed JobStore interruption/recovery,
  all bridge bounds, and thread-phase workflow bounds. No test may pass by
  resolving a global Pi or thread-phase installation.
- web/: eslint, tsc strict, Playwright e2e per mission gates.
- Docs: every public tool/function in `tool_schema.md` matches the canonical
  generated JSON Schema. CI diffs the Python declaration, committed schema,
  generated Pi TypeBox definitions, MCP declarations, and documentation.
