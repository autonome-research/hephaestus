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
- `heph build/check/render/export` MUST work without Node. The v0.1 native
  secure agent/server platform is Linux x86_64 with probed bubblewrap
  isolation. macOS is supported for agent execution only through a capability-
  tested Docker/Podman/OrbStack-compatible OCI backend running the pinned Linux
  executor profile. Other packaging lanes run core-only tests and MUST fail
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
  `spikes/REPORT.md`; CI-image tag pending first CI run): CPython 3.13.12
  (uv 0.11.3); Node v25.2.1 + pnpm 10.6.5 (engines: pi ≥22.19.0, thread-phase
  ≥22.5.0); build123d 0.11.1; cadquery-ocp-novtk/proxy 7.9.3.1.1 (OCCT 7.9.3);
  fastmcp 3.4.4 + mcp 1.28.1 (protocol 2025-11-25);
  `@earendil-works/pi-coding-agent@0.80.10`;
  `@autonome-research/thread-phase@6.0.0`; bubblewrap 0.11.2.
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
  2. CI renderer: pyrender + surfaceless EGL pinned to Mesa llvmpipe via
     `EGL_DEVICE_ID` (`LIBGL_ALWAYS_SOFTWARE` alone is insufficient); the CI
     image must ship Mesa with the surfaceless EGL platform (osmesa not
     required); matplotlib-Agg 3D is the proven byte-identical fallback.
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
  git repos; `heph init` scaffolds `hephaestus.toml`, `globals.py`, `parts/`,
  `.gitignore` (ignoring `.heph/`), and a starter check.

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
  packages; the reference product is named only in docs, factually.

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
