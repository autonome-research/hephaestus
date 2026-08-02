<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# PACKAGING — how the headless wheel is built (Stage 7H)

Normative sources: `mission_plan.md` §"Stage 7H", `repo_conventions.md`
§"Naming and packaging", `verification.md` §"Verification of the verifiers".
This file records the *mechanics*; where it disagrees with those, they win.

## The build, end to end

```console
pnpm --dir agent install --frozen-lockfile   # exact pins from pnpm-lock.yaml
pnpm --dir agent run bundle                  # -> agent/build/sidecar/  (~14 MB, 43 files)
uv run python scripts/stage_sidecar.py       # -> server/src/.../agent_bridge/_sidecar/
uv build --all-packages --out-dir dist       # -> dist/*.whl, dist/*.tar.gz
```

Artifacts (`dist/`, gitignored):

| Wheel | Size | Contents |
|---|---|---|
| `hephaestus_cad-0.1.0-py3-none-any.whl` | ~2 KB | metadata only; the aggregate users install |
| `hephaestus_server-0.1.0-py3-none-any.whl` | ~2.8 MB | bridge, MCP, **the packaged sidecar** |
| `hephaestus_core-0.1.0-py3-none-any.whl` | ~333 KB | engine + `heph` entry point |
| `hephaestus_contract-0.1.0-py3-none-any.whl` | ~24 KB | tool-surface contract + schemas |
| `opstore-0.1.0-py3-none-any.whl` | ~38 KB | internal WAL/op store |
| `hephaestus_bench-0.1.0-py3-none-any.whl` | ~94 KB | evaluation only, behind the `bench` extra |

Install: `pip install hephaestus-cad` (add `[bench]` for the Tier 3 harness).

## Why the sidecar is bundled, not vendored

`pnpm build` (plain `tsc`) emits `agent/dist/`, which is **not self-contained** —
Node resolves four bare specifiers by walking up into `agent/node_modules`.
Shipping that means shipping the production closure. Measured:

| Approach | Size | Files | `.node` addons |
|---|---|---|---|
| `dist/` + production `node_modules` | 202 MB | 24,480 | 3 (rollup ×2, clipboard) — none loaded |
| esbuild bundle (**chosen**) | 13.8 MB | 43 | **0** |

The vendored tree would have put three Linux native addons in the wheel that the
sidecar never loads, turning "no required native Node addon" into a claim that
had to be re-argued per platform. The bundle makes it trivially true.

`repo_conventions.md` anticipates this: *"A standalone bundled sidecar may
replace the Node prerequisite later without changing the bridge."* The spawn
contract is unchanged — only path resolution moved.

Unresolved bare specifiers in the bundle: `bufferutil` and `utf-8-validate`,
ws's optional native accelerators, both `require`d inside a try/catch and absent
by design. Any *other* escape is a build defect.

## Integrity

`scripts/stage_sidecar.py` writes `MANIFEST.json` (per-file SHA-256) and
`AUDIT.json` (the module-graph facts the G7H audit asserts over) into the staged
tree. `hephaestus.agent_bridge.sidecar` verifies the manifest **before every
spawn**, bidirectionally: a missing file, a changed byte, and an *added* file
are all refusals. `server/hatch_build.py` re-verifies at build time, so a stale
or absent sidecar fails `uv build` rather than shipping.

Resolution policy (ordered, fail-closed at every step — never a global
`pi`/`thread-phase`):

1. `$HEPHAESTUS_SIDECAR` override — a named override that fails is an error.
2. **packaged** — inside the installed distribution, via `importlib.resources`.
3. **development** — `agent/build/sidecar`, only if step 2 found *nothing*.

## The `openai` clause

`repo_conventions.md` requires thread-phase 6.0.0's transitive `openai` to be
absent or proven inert. The build's module graph shows **thread-phase
contributes zero import edges into `openai`**, so the clause holds strictly. The
SDK that *is* in the bundle arrives via `@earendil-works/pi-ai`'s provider
adapters — pi's own OpenAI-compatible transport, which the fake-model lane
exercises deliberately, and which loads through lazy dynamic imports.
`tests/stage7h/test_packaged_sidecar.py` asserts both facts off `AUDIT.json`.

## Data files that had to become package data

Three Python modules read `schemas/bridge_limits.json` at **import** time by
walking up from `__file__`. That walk climbs out of `site-packages`, so an
installed wheel failed on `import hephaestus.core`. `core/hatch_build.py` and
`contract/hatch_build.py` stage the repo's one copy into each distribution
(`hephaestus/{core,contract}/_data/`); `agent_bridge.limits` now delegates to
`hephaestus.core.limits`. The sidecar carries its own copy at
`_sidecar/schemas/bridge_limits.json`, covered by the integrity manifest — so
the bridge's bounds cannot be widened by editing a file in `site-packages`.

`schemas/bridge_limits.json` remains the single source of truth; no second copy
is committed under any `src/`.

## Versions

Every distribution and `agent/package.json` declare `0.1.0`; the runtime source
of truth for `heph --version` is installed distribution metadata
(`hephaestus.core.version`), never a literal.
`tests/stage7h/test_version_coherence.py` keeps the declarations coordinated.
