# Deployment view

> **Verified against** `49a90c6` on 2026-09-12.
> Workspace members from `pyproject.toml`; lanes and jobs from
> `.github/workflows/{ci,release}.yml`; staging from `scripts/stage_sidecar.py`.

arc42 section 7.

## There is one deployment target: a developer's machine

Hephaestus is not a hosted service. It runs as local processes against a local
project directory, and every network surface binds loopback.

| Process | When | Lifetime |
| --- | --- | --- |
| `heph <verb>` | every command | the command |
| the build worker | per build | one build, inside bubblewrap |
| `heph serve --web` | an operator session | until interrupted |
| `heph serve --mcp` | an MCP host session | the host's session |
| the Node sidecar | when an agent session exists | bound to the supervisor by `PR_SET_PDEATHSIG` |
| the vite dev server | web development only | never in a release |

## The workspace

One `uv` workspace, six members. The root is `hephaestus-workspace`, version
`0.0.0`, explicitly **not a published package** (`[tool.uv] package = false`).

```
opstore  core  server  contract  bench  packaging
```

Python `>=3.11,<3.15`.

### Distributions

The import namespace `hephaestus` is split across four distributions, and
`opstore` is a fifth. `hephaestus-cad` is the **aggregate release
distribution**: it carries **no code**, only dependencies.

Why an aggregate rather than one package: re-homing everything into one
distribution would mean either vendoring source — four copies to keep in sync —
or flattening the workspace and losing the per-package test and typecheck
boundaries the whole tree is organised around. A dependency-only aggregate gives
a single `pip install hephaestus-cad` while the components stay exactly where
they are tested.

The console script is `heph`, from `hephaestus.core.cli:main`.

## Where the sidecar lives, and why

The compiled Node sidecar ships inside **`hephaestus-server`**, not inside the
aggregate, because the code that resolves and spawns it is
`hephaestus.agent_bridge`.

Shipping the payload in the same distribution as its only consumer means
`pip install hephaestus-server` is self-consistent, and **there is no way to
assemble an installation whose bridge and sidecar come from different releases.**

### Staging

```console
$ cd agent && pnpm install --frozen-lockfile
$ cd agent && pnpm run bundle
$ uv run python scripts/stage_sidecar.py
```

`stage_sidecar.py` copies the esbuild bundle into
`server/src/hephaestus/agent_bridge/_sidecar/`, distils the esbuild metafile into
a small `AUDIT.json`, and writes the SHA-256 `MANIFEST.json` **the supervisor
verifies before every spawn**.

`AUDIT.json` exists so the shipped wheel is self-describing. Walking a 14 MB
bundle for import edges at test time would be guesswork; the build knows the
module graph exactly, so it records the findings the release gate asks about and
the test asserts over facts rather than regexes.

**A change under `agent/` is not live until it is re-bundled and re-staged.**
That is the single most common way a local run diverges from the source tree, and
the freshness guard behind `HEPHAESTUS_SKIP_SIDECAR_BUILD=1` refuses a stale
stage rather than running one.

## Bootstrap

```console
$ scripts/bootstrap.sh            # Python workspace + sidecar + web
$ scripts/bootstrap.sh --no-web   # skip the web client
$ scripts/bootstrap.sh --check    # prerequisites only; changes nothing
```

It is **idempotent** and safe to re-run. Every step is the same command the
install guide tells you to run by hand; the script only finds the tools, reports
*all* missing prerequisites at once rather than one per run, and runs the steps
in order.

It resolves its own directory through symlinks without `readlink -f`, which is
GNU-only — `heph` is often symlinked onto `PATH`.

`--check` runs in CI, so the bootstrap path cannot rot unnoticed.

## Continuous integration

19 jobs on `push` to `main` and on every pull request, with in-progress runs
cancelled per ref.

| Job | What it gates |
| --- | --- |
| `lint + type` | ruff, pyright |
| `docs + license headers` | `docs_check.py`, license headers, bench leaderboard, `bootstrap.sh --check` |
| `opstore + stage0a` | the durability substrate |
| `contract` | the tool declaration and its generated artifacts |
| `core engine` | the CAD engine |
| `stage0b adapter gate` | the Node adapter boundary |
| `stage gates 1-6` | … |
| `stage gates 8A-8D` | … |
| `stage gates 9A-9C` | … |
| `stage gates 11A-11C` | … |
| `stage gates 12A-12C` | … |
| `stage gates 13A-13C` | solver and determinism |
| `stage12 measurements (pinned image)` | measurement stability under a pinned image |
| `server (shard 1..3/3)` | the server suite, sharded |
| `agent (node)` | the sidecar's own tests |
| `render goldens (pinned image)` | golden images **and the Playwright e2e** — the web e2e suite runs here, not in the `web (node)` job, because it needs the pinned rasterizer |
| `web (node)` | typecheck, eslint, vitest, `vite build` — **no e2e** |
| `bootstrap (bare checkout)` | a fresh clone builds |
| `stage7h packaging invariants` | the wheel's own properties |

The two **pinned image** jobs exist because a render or a measurement compared
against a golden is only meaningful against a fixed rasterizer and a fixed
numeric stack.

## Release

The release workflow runs on `workflow_dispatch` and on a pushed `v*` tag. It
holds **no write permission** on the repository: it does not cut the tag, it
verifies that a pushed tag is coherent with the version the wheels declare. There
is no `pull_request_target`, so it never runs untrusted PR code.

### The lanes

| Lane | What it proves |
| --- | --- |
| `wheelhouse` | builds the wheels, uploads them as one artifact |
| (a) python-only, per OS | `pipx install` → `heph --version` → import/lint/schema smoke, **no script execution and no Node** |
| (b) secure linux x86_64 | core build and check through the secure executor → packaged-sidecar integrity and native-addon audit → Python-backed JobStore init → `heph agent` against a fake model → MCP smoke → the secure-executor escape suite |
| (d) fail-closed | explicit agent/server script execution on lanes **without** a passing secure backend; on macOS the product refuses script execution by design in v0.1 |
| `prior gates` | the prior gates are green on the release SHA |
| `G7H gate` | the aggregate |

### Two structural rules that make the matrix mean something

1. **Every lane installs the built wheel**, downloaded from the `wheelhouse`
   artifact. No lane installs from the source tree — an in-tree install resolves
   the *development* sidecar at `agent/build/sidecar`, and the gate's central
   claim ("the wheel uses its packaged sidecar") becomes untestable.
   `HEPHAESTUS_WHEELHOUSE` points the packaging suites at that same artifact so
   they, too, measure the released bytes.
2. **A lane never passes by absence.** Lane (a) *asserts* Node is gone rather
   than hoping. Lane (d) *asserts the named refusal* rather than a skipped test.
   A lane that would have to skip does not exist at all: the deferred macOS lane
   (c) was **removed, not conditioned**, so no green check can stand in for it.

That second rule is the one worth carrying to other projects. A conditioned lane
reports green for a platform nobody tested.

## Runtime prerequisites

| Requirement | Needed for |
| --- | --- |
| Python 3.11–3.14 | everything |
| `bwrap` (bubblewrap) on `PATH` | secure builds; without it, `sandbox_denied` |
| Node ≥ 22.19 | agent sessions (bundled in the wheel) |
| pnpm 10.34.5 | building the sidecar or the web client from source |
| a GPU/EGL device or software fallback | rendering; `HEPH_EGL_DEVICE` overrides the choice |

Secure builds are **Linux-only**. That is a stated product property in v0.1, not
a gap: the macOS path refuses script execution by name rather than running
unsandboxed.

## Not published

There is no PyPI release and no GitHub release. You build it from a clone.

## Related

- Doing the install: [install and run](../03-how-to/install-and-run.md).
- Cutting a release: [release and package](../03-how-to/release-and-package.md).
- Running the suites: [run the tests](../03-how-to/run-the-tests.md).
