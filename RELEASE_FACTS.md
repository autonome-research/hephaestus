<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# RELEASE_FACTS — Stage 7H recon (read-only survey, 2026-08-01)

Facts established by reading the tree at `341da20`. Nothing here is a decision;
every "must change" line is a gap between what exists and what G7H demands.

---

## 1. Normative requirements (verbatim scope)

`mission_plan.md` §"Stage 7H — Headless release (v0.1.0-headless)":

- Deliverables: PyPI wheel with its **private compiled sidecar** per
  `repo_conventions.md` (integrity-checked, never a global `pi`/`thread-phase`);
  headless docs set (install, `heph` verbs, MCP client configuration, project
  conventions, registry pinning); model-leaderboard page generated from bench
  artifacts; `CONTRIBUTING.md` + registry contribution guide; Apache-2.0 headers.
- **G7H** = G7's clean-machine matrix lanes (a)-(d) verbatim, plus: gates GS,
  G0A, G0B, G1, G2, G2V, G3, G6 green on the release SHA; headless docs build
  without warnings; `bench.yml` publishes the leaderboard artifact; tag
  `v0.1.0-headless` cut.
- `LEGAL-REVIEW.md` is explicitly **NOT** a G7H blocker (it gates the private
  reference fixtures and the full v0.1 release only).
- G6's bench clause status (mission_plan §"G6 status") is a **prerequisite gate**
  for G7H — it is currently OPEN pending an archived Tier 3 run. Stage 8D
  ("clean corpus-v1 re-run that closes G6's bench clause") is the intended
  closer; `git log` shows `ca944b3 bench: … G6 bench clause measured, gate not
  met`. This is the single largest external risk to declaring G7H green.

`repo_conventions.md` packaging rules that bind Stage 7H:

- Project name **hephaestus**, CLI binary **heph**, PyPI distribution
  `hephaestus-cad` (bare `hephaestus` availability "must be checked at Stage 7";
  import package is `hephaestus` regardless). No npm publication required for v0.1.
- `opstore` is **bundled as an internal wheel component**, not separately
  published in v0.1.
- The TypeScript agent is "a private workspace package compiled into a bounded
  sidecar artifact and **bundled in the Python wheel**"; not a second public
  package.
- `heph build/check/render/export` **MUST work without Node**.
- `heph agent` / agent-enabled serving require Node ≥22.19, do an explicit
  startup compatibility check, and execute the wheel's **integrity-checked**
  sidecar — never a global `pi`/`thread-phase`. Supervisor supplies a minimal
  env + only explicitly approved provider credentials.
- Exact pins, no caret/tilde, in `package.json` + `pnpm-lock.yaml`; "no semver
  range in the sidecar manifest" (Gate GS wording).
- The packaged sidecar MUST have **no required native Node addon**;
  thread-phase 6.0.0's transitive `openai` must be absent from the compiled
  sidecar or explicitly allowlisted as proven inert.
- SemVer from `v0.1.0` at Stage 7; pre-release tags `v0.0.x-stageN` cut by CI
  when the gate workflow first passes on main. **`git tag` is currently empty —
  no tag has ever been cut.**
- Registry pinning: `hephaestus.toml` pins every registry by Merkle content
  hash; `heph registry update` is the only re-pin path. Executable registry
  content has sandbox parity with part scripts.
- `heph init` is a documented convention ("scaffolds `hephaestus.toml`,
  `globals.py`, `parts/`, `.gitignore`, a starter check") — **it does not exist
  in the CLI today** (see §5).

`verification.md` §CI contract:
- `ci.yml` = lint + unit + Tier 1 + Tier 2 goldens, every PR. **Exists.**
- `e2e.yml` (Playwright) — not needed headless. **Absent.**
- `bench.yml` = Tier 3 corpus, manual dispatch + weekly schedule, "publishing
  the results artifact". **Absent — must be authored for G7H.**
- "A docs-layout/link check verifies every repository path and section
  reference in the normative root documents." **Absent.**
- §"Verification of the verifiers": "Packaging tests audit away required native
  Node addons and initialize the Python-backed workflow JobStore across the
  supported OS/architecture matrix."

---

## 2. The sidecar artifact set as it exists today

### 2.1 What is built

`agent/` is a private pnpm package `@hephaestus/agent@0.1.0` (`"private": true`,
`"type": "module"`, `engines.node >=22.19`, `exports: {".": "./dist/main.js"}`).

Build is **plain `tsc`**, not a bundler:
`"build": "tsc -p tsconfig.json"` → `rootDir: src`, `outDir: dist`,
`module/moduleResolution: NodeNext`, `declaration: true`, `sourceMap: true`.

Result (`agent/dist`, **708 KB**, gitignored via the global `dist/` rule):

```
dist/main.js            dist/events.js   dist/framing.js  dist/limits.js  dist/rpc.js
dist/session/{context,extension,history,live,manager,profiles,runtime}.js
dist/tools/{clarify,invocation,preflight,proxy,registry,schema.gen}.js
dist/workflows/{cad_workflow,jobstore,runner}.js
+ a .d.ts and .js.map beside every .js
```

Two entry points are spawned, not one:
- `agent/dist/main.js` — the session sidecar (`app.default_dist_main()`).
- `agent/dist/workflows/runner.js` — the workflow runner
  (`workflows.default_workflow_runner_main()`).

### 2.2 Runtime dependency closure (measured from compiled output)

Every bare specifier in `agent/dist/**/*.js`:

```
@earendil-works/pi-coding-agent        (root barrel)
@autonome-research/thread-phase/session
@autonome-research/thread-phase/patterns
@sinclair/typebox
@sinclair/typebox/value
node:crypto  node:fs  node:http  node:path  node:process  node:url
```

Facts and one defect:

- The compiled sidecar is **not self-contained**. `dist/` alone cannot run; Node
  resolves those four bare specifiers by walking up to `agent/node_modules`.
- **`@sinclair/typebox` is declared in `devDependencies`, not `dependencies`**
  (`agent/package.json`), yet `dist/tools/schema.gen.js` and
  `dist/tools/proxy.js` import it at runtime. A `pnpm install --prod` install
  produces a sidecar that dies on first import. This is a real packaging bug that
  Stage 7H must fix (promote to `dependencies` with an exact pin — it is
  currently `^0.34.0`, which also violates the no-caret rule for a runtime dep).
  `spikes/REPORT.md` records typebox 1.1.38 arriving transitively; the direct
  dep is a different major.
- Production imports thread-phase only through `/session` and `/patterns`
  (Stage S disposition 4 — the root barrel eagerly loads the `openai` SDK).
  **Verified still true in `dist/`**: no root `@autonome-research/thread-phase`
  import appears.
- `@earendil-works/pi-coding-agent` **is** imported at its root. That package
  pulls `@earendil-works/pi-tui`, which ships `.node` prebuilds — but only for
  `darwin-{arm64,x64}` and `win32-{arm64,x64}` (`darwin-modifiers.node`,
  `win32-console-mode.node`); **no linux prebuild exists**, which is consistent
  with "no *required* native addon" but is exactly the claim the G7H audit must
  re-prove per platform.
- Current dev install `agent/node_modules` is **258 MB** across 278 pnpm store
  entries — that includes eslint/typescript/vitest/rollup. The production-only
  closure has never been measured in this repo and must be (a `pnpm install
  --prod --frozen-lockfile` into a scratch dir, then `du`). `.node` files found
  under the dev tree that are **dev-only** and must not appear in a prod closure:
  `@rollup/rollup-linux-x64-{gnu,musl}`, `@mariozechner/clipboard-linux-x64-gnu`.

### 2.3 The spawn contract (unchanged shape a packaged sidecar must preserve)

`server/src/hephaestus/agent_bridge/app.py::BridgeRuntime.__init__`:

```python
argv = [_node_executable(), str(dist_main or default_dist_main())]
config = SupervisorConfig(
    argv=argv,
    credential_allowlist=frozenset(credential_allowlist),
    extra_env={"HEPHAESTUS_AGENT_DIR": str(agent_dir)},
    cwd=str(self._layout.root),
)
```

- `_node_executable()` = `$HEPHAESTUS_NODE` or `shutil.which("node")`; raises
  `RuntimeError("node executable not found (set HEPHAESTUS_NODE or install
  Node)")`. **There is no Node ≥22.19 version check today** — `repo_conventions`
  requires "an explicit startup compatibility check". Gap.
- Environment: `supervisor.build_minimal_env()` passes only
  `BASE_ENV_VARS = ("PATH", "HOME", "LANG", "TMPDIR")` + the caller's credential
  allowlist + `extra_env` (currently only `HEPHAESTUS_AGENT_DIR`). Nothing else.
- `agent_dir` defaults to `<project>/.heph/agent`; `link_auth_source()` is the
  only path by which a credential the app did not mint reaches the sidecar, and
  it is a **symlink, never a copy** (OAuth rotation), refusing to clobber a
  non-placeholder `auth.json` (`_EMPTY_AUTH = ("", "{}")`).
- Transport: framed JSON-RPC over the child's stdio; `_pdeathsig_preexec()` sets
  `PR_SET_PDEATHSIG=SIGKILL` on Linux; watchdog + bounded respawn
  (`respawn_max_attempts=3`, backoff 0.5→2.0 s, cooldown 30 s); `spawn_hook`
  replays `runtime.configure` onto every child.

**Nothing about this contract needs to change for packaging.** Only path
resolution does.

### 2.4 How the sidecar path is resolved today, and what must change

Three independent hard-coded resolvers, all `repo_root()`-relative:

| Location | Expression |
|---|---|
| `agent_bridge/app.py:77-84` | `repo_root() = Path(__file__).resolve().parents[4]`; `default_dist_main() = repo_root()/"agent"/"dist"/"main.js"` |
| `agent_bridge/workflows.py:126-128` | `default_workflow_runner_main() = Path(__file__).resolve().parents[4]/"agent"/"dist"/"workflows"/"runner.js"` (does **not** reuse `repo_root()`) |
| `testing/sidecar.py:39-53` | `agent_dir() = repo_root()/"agent"`; `sidecar_main()`, `workflow_runner_main()`; `build_agent_dist()` shells out to `pnpm --dir agent build` |

`parents[4]` from `server/src/hephaestus/agent_bridge/app.py` is
`server/src/hephaestus/agent_bridge` → `hephaestus` → `src` → `server` →
**repo root**. In an installed wheel, `parents[4]` of
`site-packages/hephaestus/agent_bridge/app.py` is *not* a repo root — it lands
somewhere above `site-packages`. **An installed wheel today cannot find its
sidecar at all.** This is the central Stage 7H change.

What must change:
1. A single resolver (one function, used by `app.py`, `workflows.py`, and the
   testing helper) with an ordered policy: (i) explicit override
   (`HEPHAESTUS_SIDECAR` / constructor arg) → (ii) **packaged** sidecar shipped
   inside the wheel (e.g. `hephaestus/_sidecar/`, located via
   `importlib.resources` — never `__file__`-relative arithmetic) → (iii) the
   in-repo `agent/dist` development fallback, used only when the packaged one is
   absent. G7H requires a test proving the wheel takes branch (ii).
2. `workflows.py`'s duplicate literal must be folded into that resolver, or the
   two entry points will diverge.
3. Integrity check: `repo_conventions` says "integrity-checked sidecar". Nothing
   in the tree computes or verifies a sidecar digest today. A manifest
   (per-file SHA-256 over the shipped sidecar tree, generated at build, verified
   before spawn, failing closed) has to be introduced.
4. Node version gate at `_node_executable()`.

### 2.5 Packaging options for the sidecar (both viable, neither present)

- **(A) `dist/` + production `node_modules`, both inside the wheel.** No new
  toolchain; keeps the pnpm lockfile as the pinning authority; but ships a large
  vendored tree (unmeasured; dev tree is 258 MB) and puts `node_modules` bytes
  under `hatch` data files.
- **(B) Bundle to a single file** (esbuild/rollup, `--platform=node
  --format=esm`, externalizing nothing). `repo_conventions` explicitly
  anticipates this: "A standalone bundled sidecar may replace the Node
  prerequisite later without changing the bridge." Two entry points must be
  bundled (`main.js`, `workflows/runner.js`). **No bundler is a declared
  devDependency today** (rollup exists only transitively under vitest).

Either way the wheel needs `hatch` data inclusion — `core/pyproject.toml` and
`server/pyproject.toml` today declare only `packages = ["src/hephaestus"]`.

---

## 3. Existing packaging tooling inventory

- Build backend: **hatchling** in all five publishable packages. No
  `MANIFEST.in`, no `setup.cfg`, no `setup.py`, no `[tool.hatch.build.*]` beyond
  `targets.wheel.packages`, no `force-include`, no `artifacts`, no
  `shared-data`. No `hatch_build.py` custom build hook.
- Root `pyproject.toml` is `hephaestus-workspace` v0.0.0 with
  `[tool.uv] package = false` — deliberately unpublishable.
- **No aggregate `hephaestus-cad` distribution exists.** Stage 7H must author it
  (a new metadata-only package depending on the five, or a repackaging of the
  set — the mission text says "the PyPI wheel", singular).
- No `LICENSE` file, no `CONTRIBUTING.md`, no `LEGAL-REVIEW.md` at repo root.
  No Apache-2.0 headers were found in source files.
- No `docs/` directory; **no mkdocs/sphinx/any doc tooling anywhere** in the
  tree or the dev dependency group. `repo_conventions.md` §Layout reserves
  `docs/` for "generated/site-only mkdocs content". "Docs build without
  warnings" therefore has no build to run yet.
- Version strings today: `hephaestus-core`, `hephaestus-server`,
  `hephaestus-contract`, `hephaestus-bench`, `opstore` are all
  `version = "0.1.0"`; `agent/package.json` is `0.1.0`; root workspace `0.0.0`.
  **No Python package exposes `__version__`**, and there is no single source of
  truth for the version the CLI would report. `git tag` is empty.

---

## 4. What a headless wheel must contain / depend on

Python import packages, and where they live:

| Distribution | Import package(s) | Deps |
|---|---|---|
| `opstore` 0.1.0 | `opstore` | none |
| `hephaestus-core` 0.1.0 | `hephaestus.core`, **`hephaestus.geom`** (both under `core/src/hephaestus`) | build123d, ezdxf, numpy, opstore, pillow, pygltflib, pyrender, reportlab, trimesh |
| `hephaestus-contract` 0.1.0 | `hephaestus.contract` | none |
| `hephaestus-server` 0.1.0 | `hephaestus.agent_bridge`, `hephaestus.mcp`, `hephaestus.testing` | fastmcp<4, mcp≥1.28, hephaestus-contract, hephaestus-core, opstore, pypdf |
| `hephaestus-bench` 0.1.0 | `hephaestus.bench` | hephaestus-server, huggingface-hub, pyyaml |

Notes that bear on the wheel:

- `hephaestus` is a **namespace split across four distributions** (core/geom,
  contract, agent_bridge+mcp+testing, bench). All four use
  `packages = ["src/hephaestus"]` with no `__init__.py` collision checked here —
  worth confirming they are implicit namespace packages before shipping.
- `hephaestus.testing` (fake OpenAI server, sidecar builder, workflow harness)
  currently ships **inside `hephaestus-server`**. `testing/sidecar.py` shells out
  to `pnpm build`, i.e. the released wheel contains a module that tries to build
  the sidecar from a repo that is not there. Decide: exclude it, or make it
  degrade cleanly.
- `hephaestus-bench` pulls `huggingface-hub` — an evaluation dependency, not a
  product one. Whether the headless wheel depends on bench (and therefore on HF)
  should be an explicit decision; the `heph bench` / `heph cadgenbench` verbs are
  registered only when `hephaestus.bench` imports (`core/cli.py` guards with
  `try: … except ImportError: pass`).
- Sidecar payload (§2.5) plus its integrity manifest.
- Lane (a) requires the Python-only install to work **with no Node** — the
  existing `try/except ImportError` verb registration already makes the engine
  CLI Node-free at import time; `_node_executable()` only raises when `heph
  agent` actually runs.

---

## 5. Full `heph` verb inventory (as registered by `core/cli.py::build_parser`)

`prog="heph"`, `description="Hephaestus CAD engine CLI (engine-first: no
server)"`, `add_subparsers(dest="command", required=True)`.

Always present (from `hephaestus-core`):

| Verb | Sub-verbs | Module |
|---|---|---|
| `build` | — (`part`, `--param`, `--global-param`, `--stale`, `--json`, `--unsafe-local-executor`) | `core/cli.py` |
| `check` | — (`--project`, `--json`) | `core/cli.py` |
| `lint` | — (`path`, `--json`, `--requirements`, `--request`) | `core/cli.py` |
| `render` | — | `core/cli_render.py` |
| `goldens` | — (`--update`; refuses on a dirty tree) | `core/cli_render.py` |
| `registry` | `list`, `pin`, `update`, `verify` | `core/cli_registry.py` |
| `reference` | `add`, `list`, `remove` | `core/cli_references.py` |
| `diff` | — | `core/cli_diff.py` |
| `assembly` | (bare, `--json`) + `check` | `core/cli_assembly.py` |

Registered only when the optional package imports:

| Verb | Sub-verbs | Module | Guard |
|---|---|---|---|
| `agent` | — (`--project`, `--providers`, …) | `agent_bridge/cli.py` | `from hephaestus.agent_bridge import cli` |
| `bench` | `run`, `score` | `bench/cli_bench.py` | `from hephaestus.bench import cli_bench` |
| `cadgenbench` | `fetch`, `convert`, `run`, `package`, `score` | `bench/cadgenbench/_cli.py` | via `cli_bench` |
| `serve` | — (`--mcp` required, `--http HOST:PORT`) | `mcp/cli_serve.py` | `from hephaestus.mcp import cli_serve` |

Gaps against the mission text:

- **`heph --version` does not exist.** `build_parser()` adds no `--version`
  action and no package exposes `__version__`. G7H lane (a) names
  `heph --version` explicitly — this must be added, wired to a single version
  source, before the lane can be written.
- **`heph init` does not exist**, though `repo_conventions.md` §Versioning
  documents it as the user-facing scaffolding convention and the headless docs
  set is supposed to document project conventions.
- `heph export` is named in `repo_conventions.md` ("`heph build/check/render/
  export` MUST work without Node") but **is not a registered verb**; exports
  exist as a tool/`cad_ops/_exports.py` surface. Either the convention text is
  stale or a verb is missing — resolve before writing docs that promise it.

---

## 6. Existing CI, and the precise G7H lane (a)-(d) commands

### 6.1 What `.github/workflows/ci.yml` already establishes

Single workflow, `on: [push to main, pull_request]`, no `pull_request_target`,
`permissions: contents: read`, concurrency-cancel. Env:
`UV_PYTHON=3.13`, `NODE_VERSION=22.19.0`, `PNPM_VERSION=10`.

Jobs: `lint-type`, `opstore` (stage0a, `--cov-fail-under=90`), `core`,
`stage0b`, `stages` (1/2/2v/3/6), `server` (3-way file-sharded), `agent-node`.

Reusable step recipe every sidecar/sandbox job uses:

```yaml
- uses: actions/checkout@v4
- uses: astral-sh/setup-uv@v5
- uses: pnpm/action-setup@v4
  with: {version: "${{ env.PNPM_VERSION }}"}
- uses: actions/setup-node@v4
  with: {node-version: "${{ env.NODE_VERSION }}"}
- name: sandbox + renderer prerequisites
  run: |
    sudo apt-get update -q
    sudo apt-get install -y -q bubblewrap libegl1 libgl1 libgl1-mesa-dri libglx-mesa0
    sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0
- run: uv sync --dev
- run: pnpm --dir agent install --frozen-lockfile
- run: pnpm --dir agent build
```

Documented exclusion: `tests/render` (G1 byte-pinned goldens) is not run on
stock `ubuntu-latest` — Mesa drift. It moves in when the pinned CI image lands.

> **Correction, 2026-08-30 (third Stage 12 repair pass).** The two sentences
> that stood here — that the pinned image was still outstanding and that
> `repo_conventions.md` recorded the CI image tag as "pending first CI run" —
> were true when this survey was taken at `341da20` and have not been true since
> **2026-08-28**: `docker/ci/Dockerfile` landed, `ci-image.yml` builds and pushes
> it to GHCR, `ci.yml` consumes it **by digest** in the `render goldens (pinned
> image)` job, and `tests/render` runs there. The rest of this document is left
> as the dated survey it is; this line is corrected in place rather than left
> standing, because a stale claim about a measurement is the one kind of doc
> drift this project's own rules refuse.

Missing workflows G7H needs: `bench.yml` (leaderboard artifact — named in the
gate), the release/matrix workflow itself, and the docs-layout/link check.

### 6.2 G7H lanes, as they would run on CI

Lane structure, derived verbatim from the G7 text. `PKG` = the built
`hephaestus_cad-0.1.0-py3-none-any.whl`; a `build-wheel` job produces it once
(`uv build`) and uploads it, and every lane downloads it — no lane may install
from the source tree, or "the wheel uses its packaged sidecar" is untestable.

**Lane (a) — Python-only, every packaging lane** (`ubuntu-latest`,
`macos-latest`, and at least one lane with no secure backend). Node MUST be
absent: do not add `actions/setup-node`, and assert it.

```bash
# no setup-node step in this job
command -v node && { echo "node present; lane (a) is invalid"; exit 1; }
python -m pip install --user pipx && python -m pipx ensurepath
pipx install ./dist/hephaestus_cad-0.1.0-py3-none-any.whl
heph --version                       # <-- verb does not exist yet (§5)
heph --help                          # every Node-free verb registers
python -c "import hephaestus.core, hephaestus.geom, hephaestus.contract, opstore"
heph lint corpus/public_fixtures/<project>/parts/<part>.py
heph registry verify --project corpus/public_fixtures/<project>
uv run pytest tests/stage7h/test_lane_a_no_node.py -q   # asserts: no script
                                                        # execution, no spawn
```

Assertions the lane must make, not just the commands: no part-script execution
occurs, no `node` is spawned (a PATH shim that fails loudly is the honest way),
and the contract/schema smoke diffs the committed JSON Schema against the
installed `hephaestus.contract` declarations.

**Lane (b) — secure Linux x86_64** (`ubuntu-latest` + the bubblewrap/Mesa
prerequisites block from §6.1, `actions/setup-node@v4` pinned to 22.19.0):

```bash
pipx install ./dist/hephaestus_cad-0.1.0-py3-none-any.whl
# 1. core build/check through the secure executor (no --unsafe-local-executor)
heph build --json                     # inside a public clean-room fixture project
heph check --project --json
# 2. packaged-sidecar integrity + native-addon audit
uv run pytest tests/stage7h/test_packaged_sidecar.py -q
#    - resolves the sidecar from the INSTALLED wheel, asserts the path is under
#      site-packages and NOT the repo's agent/dist
#    - verifies the shipped integrity manifest (per-file sha256), then mutates a
#      byte and asserts spawn fails closed
#    - walks the shipped sidecar tree: zero required *.node; `openai` absent or
#      allowlisted-inert (no import, no credential, no request path)
#    - a hostile global `pi`/`thread-phase` on PATH is planted and proven unused
# 3. Python-backed JobStore initialization
uv run pytest tests/stage7h/test_jobstore_init.py -q
# 4. heph agent against the fake model
uv run pytest tests/stage7h/test_lane_b_fake_model.py -q   # start_fake_openai +
                                                           # heph agent
# 5. Stage-3 MCP smoke
uv run pytest tests/stage3 -q
# 6. release-lane-only: secure-executor escape suite
uv run pytest core/tests -k "sandbox or bwrap or escape" -q
```

**Lane (c) — macOS through a detected OCI backend** (`macos-latest`,
`actions/setup-node@v4`, Colima/Docker installed and *capability-probed*):

```bash
pipx install ./dist/hephaestus_cad-0.1.0-py3-none-any.whl
uv run pytest tests/stage7h/test_oci_backend_probe.py -q   # detect + escape/
                                                            # resource probes;
                                                            # skip is NOT a pass
uv run pytest tests/stage7h/test_lane_b_fake_model.py -q    # same fake-model smoke
uv run pytest tests/stage3 -q                               # same MCP smoke
uv run pytest core/tests -k "sandbox or escape" -q          # escape suite via OCI
```

**Lane (d) — fail-closed** (a lane with **no** passing secure backend: no
bubblewrap installed, no OCI backend; `ubuntu-latest` with the prerequisites
step deliberately omitted):

```bash
pipx install ./dist/hephaestus_cad-0.1.0-py3-none-any.whl
command -v bwrap && { echo "backend present; lane (d) is invalid"; exit 1; }
uv run pytest tests/stage7h/test_fail_closed.py -q
#  - `heph build` (agent/server script execution path) exits non-zero with a
#    structured capability-detection error, NOT a silent fallback to unsafe
#  - `heph serve --mcp` refuses to serve script execution
#  - `heph agent` refuses
#  - the ONLY way to execute is the explicit --unsafe-local-executor debug flag,
#    which must remain refused under serve and for registry code
```

Gate aggregation job (`needs: [a, b, c, d]`) additionally asserts: GS/G0A/G0B/
G1/G2/G2V/G3/G6 green on the release SHA, `bench.yml`'s leaderboard artifact
present, docs build clean, then cuts `v0.1.0-headless`.

---

## 7. Ranked gap list for Stage 7H

1. Sidecar path resolution is `repo_root()`-relative in three places → an
   installed wheel cannot find its sidecar. Single resolver + packaged-first
   policy. (§2.4)
2. No sidecar integrity manifest exists at all. (§2.4)
3. `@sinclair/typebox` is a runtime import declared as a devDependency, with a
   caret range. Prod install is broken today. (§2.2)
4. No `heph --version`; no `__version__`; no single version source; no git tags.
   Lane (a) cannot be written without it. (§3, §5)
5. No aggregate `hephaestus-cad` distribution, no hatch data-file config to
   carry the sidecar. (§3)
6. No `bench.yml`; leaderboard artifact publication is named in the gate. (§6.1)
7. No doc tooling, no `docs/`, so "docs build without warnings" is unrunnable;
   also no docs-layout/link check. (§3)
8. No `LICENSE`, no `CONTRIBUTING.md`, no registry contribution guide, no
   Apache-2.0 headers. (§3)
9. No Node ≥22.19 startup compatibility check. (§2.3)
10. G6's Tier 3 bench clause is OPEN — a prerequisite gate, not a 7H
    deliverable, but it blocks the tag. (§1)
11. `heph init` and `heph export` are promised by `repo_conventions.md` and do
    not exist; either ship them or amend the convention. (§5)
12. `hephaestus.testing` ships in the server wheel and shells out to `pnpm
    build` against a repo that will not exist. (§4)
