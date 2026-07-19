# 05 — Repo Conventions

## Layout

Monorepo at `github.com/autonome-research/hephaestus` (single repo keeps the
tool schema, core, and clients atomically versioned through the mission):

```
core/       Python ≥3.11. Deps: build123d, ocp, numpy, trimesh/pyrender (render),
            ezdxf (dxf), pygltflib. Managed with uv; strict pyright.
agent/      TypeScript on Node ≥22.19. Embedded Pi SDK sessions, generated CAD
            tools, Python JSON-RPC bridge client, and thread-phase workflows.
            Managed with pnpm; strict tsc and eslint.
server/     Python. FastMCP + FastAPI + websockets; supervises the packaged
            Node agent sidecar over private JSON-RPC/stdio.
web/        TypeScript, React 18, Vite, three.js, Monaco. pnpm workspace.
registries/ skills/ parts/ materials/ dfm/ — content, versioned in-repo for
            now; splits out post-v0.1 once the registry format stabilizes.
corpus/     tasks/ (public split), solutions/. reference/ is fetched in CI
            from autonome-research/hephaestus-fixtures (private: recovered
            scripts + reconstructed globals.py, pending legal review) and is
            gitignored here; the private gate split of the bench corpus
            lives in autonome-research/hephaestus-corpus-private.
tests/      stage0…stage7 mirrors mission gates; render/ goldens with
            provenance sidecars.
*.md        normative design/mission documents live at repo root in v0.1.
docs/       generated/site-only mkdocs content and assets; links to root docs.
```

## Naming and packaging

- Project name: **hephaestus**; CLI binary: **heph**.
- PyPI: publish as `hephaestus-cad` (the bare name's availability must be
  checked at Stage 7; the import package is `hephaestus` regardless, with the
  distribution name only differing if squatted). npm (web components, if ever
  published separately): `@autonome/hephaestus-web`.
- Python namespaces: `hephaestus.core`, `hephaestus.server`, and the private
  bridge/supervisor under `hephaestus.agent_bridge`. The TypeScript agent is a
  private workspace package compiled into a bounded sidecar artifact and
  bundled in the Python wheel; it is not a second public product package in
  v0.1.
- `heph build/check/render/export` MUST work without Node. The v0.1 secure
  agent/server execution platform is Linux x86_64 with the probed isolation
  backend; other packaging lanes run core-only tests and MUST fail closed for
  agent/server script execution unless an approved secure container backend is
  detected. `heph agent` and agent-enabled serving require Node ≥22.19,
  perform an explicit startup
  compatibility check, and execute the wheel's integrity-checked sidecar —
  never a global `pi` or `thread-phase` binary. The supervisor supplies a
  minimal environment and only explicitly approved provider credentials. A
  standalone bundled sidecar may replace the Node prerequisite later without
  changing the bridge.
- Product dependencies are pinned as a tested set in `pnpm-lock.yaml`. Stage S
  records exact versions for Node, `@earendil-works/pi-coding-agent`,
  and `@autonome-research/thread-phase`. Production phases call the Hephaestus
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
  and the built artifact.

## Versioning and git discipline

- SemVer from `v0.1.0` at Stage 7. Pre-release tags `v0.0.x-stageN` at each
  gate, cut by CI when the gate workflow first passes on main.
- Toolchain pinning: exact build123d/OCP/OCCT versions in the uv lockfile,
  exact Pi/thread-phase versions in the pnpm lockfile, and the CI container
  image tag are recorded here at Stage S. Kernel or renderer upgrades land
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
  (`LEGAL-REVIEW.md`) clears them — and all acceptance tests assert error/
  result *fields and information content*, never the reference product's
  verbatim message text or UX copy. `CONTRIBUTING.md` states this boundary
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

- core/ and server/: ruff + pyright strict, 90% line coverage on core/
  (enforced), property-based tests (hypothesis) for kernel services.
- agent/: eslint + tsc strict; unit tests cover Pi resource/credential
  isolation, bridge framing, event normalization, session lifecycle, context
  policy, sequential mutation/interaction tools, optimistic hashes, crash-
  recoverable mutation WAL/idempotency, dirty-preimage journaling, effective-
  parameter build identity, create-only exports, path confinement,
  cross-process session leases, direct
  Pi-session phase invocation, Python-backed JobStore interruption/recovery,
  all bridge bounds, and thread-phase workflow bounds. No test may pass by
  resolving a global Pi or thread-phase installation.
- web/: eslint, tsc strict, Playwright e2e per mission gates.
- Docs: every public tool/function in `tool_schema.md` matches the canonical
  generated JSON Schema. CI diffs the Python declaration, committed schema,
  generated Pi TypeBox definitions, MCP declarations, and documentation.
