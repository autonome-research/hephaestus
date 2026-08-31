<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# Install

Hephaestus is **not on PyPI**. There is **no GitHub Release**.
`pip install hephaestus-cad`, `pipx install hephaestus-cad`, and
`uv tool install hephaestus-cad` against the index all 404.

Tag `v0.1.0-headless` exists as a historical headless cut. It has no `web/`,
and it is **not an install path**. Do not document or use a
`git+…#subdirectory=…` install until wheels that include the packaged
`_sidecar/` exist: the sidecar is gitignored build output, and
`server/hatch_build.py` refuses a non-editable `hephaestus-server` wheel
without it.

Install from a clone of this repository. The import package is `hephaestus`
regardless (`repo_conventions.md`); the CLI binary is `heph`.

```console
$ git clone https://github.com/autonome-research/hephaestus && cd hephaestus
$ uv sync --dev
$ uv run heph --version
heph 0.1.0
```

`uv sync --dev` is an editable workspace install. That is why it works on a
bare checkout: `server/hatch_build.py` skips the packaged-sidecar check for
editable builds, and the engine verbs do not need the sidecar. `heph` is a
tool, not a library you import into your own project; run it with `uv run heph`
from the clone, or use `.venv/bin/heph` after the sync.

Python 3.11 through 3.14 are supported.

## What you get

Public v0.1 is the **engine-first CLI**. `heph` is the agent core. MCP
(`heph serve --mcp`) is optional. `web/` exists on `main` as optional operator
chrome — `heph serve --web` is the operator workspace.

`uv sync --dev` installs the workspace members that actually carry code, plus
the evaluation harness (`hephaestus-bench`) because `--dev` is the contributor
path:

| Distribution | Carries |
|---|---|
| `hephaestus-core` | The CAD engine, the executor, the renderer, and the `heph` entry point |
| `hephaestus-contract` | The canonical tool-surface declaration and committed JSON schemas |
| `hephaestus-server` | The agent bridge, the MCP server, and (in a *wheel*, not this checkout) the compiled agent sidecar |
| `opstore` | The durable op/WAL store the project store is built on (internal component, not a separate product) |
| `hephaestus-bench` | The Tier 3 evaluation harness (`heph bench`, `heph bench cadgenbench`) — present under `--dev` |

`hephaestus-cad` is the intended future aggregate wheel. It is not published.
A non-editable `hephaestus-server` wheel still requires a staged sidecar
(see [Building a wheel](#building-a-wheel)).

`heph bench` appears in `heph --help` after `uv sync --dev`. See
[cli.md](cli.md).

## What each capability requires

Hephaestus has three capability tiers and they have genuinely different
prerequisites. `uv sync --dev` gets you the first one everywhere.

### 1. The engine — everywhere, no Node

`heph build`, `check`, `lint`, `render`, `diff`, `assembly`, `registry`,
`reference` and `goldens` are pure Python. They need no Node, no browser, and no
network. This is the guarantee in `repo_conventions.md`: the engine verbs work
without Node, full stop.

### 2. Executing part scripts securely — Linux x86_64 with bubblewrap

Part scripts are model-authored code. They run in an OS sandbox, and the
sandbox is **proved by running it**, not by reading a version string: a probe
executes a trivial job inside bubblewrap and checks live that network connects
fail, that writes outside the output directory fail, that `/etc/shadow` is
unreadable, and that the output directory really is writable and visible to the
host. Any probe that does not block raises `sandbox_unavailable`.

- **Linux x86_64 with bubblewrap ≥ 0.11** is the supported secure lane. Install
  `bubblewrap` from your distribution.
- **macOS**: in v0.1, script execution refuses by design (deferred 2026-08-13,
  operator decision). The planned macOS path — a capability-tested
  Docker/Podman/OrbStack-compatible OCI backend running the pinned Linux
  executor profile — ships **post-v0.1**. Everything that does not execute
  part scripts (`heph lint`, schema/contract reads, `heph --version`) works
  on macOS today.
- **Anywhere else**, script execution **fails closed**. `heph build` exits
  non-zero with a structured capability error; it never silently downgrades.

There is a debug escape hatch, `heph build --unsafe-local-executor`, which runs
the worker with no OS sandboxing. It is refused outright for registry content
and for anything under `heph serve` — `unsafe_refused`, flag or no flag — because
those are exactly the paths where the code came from somewhere else.

### 3. The agent — Node ≥ 22.19, after you build the sidecar

`heph agent` and agent-backed serving spawn the compiled agent sidecar, which
needs a Node ≥ 22.19 runtime on `PATH`. In a clone the sidecar is **not** in
the tree: it is gitignored build output. Build it before the first agent
session (the same recipe [PACKAGING.md](../PACKAGING.md) uses):

```console
$ pnpm --dir agent install --frozen-lockfile
$ pnpm --dir agent run bundle
$ uv run python scripts/stage_sidecar.py
```

The sidecar is never a globally installed `pi` or `thread-phase` binary, and
there is no fallback that would make it one.

Before spawning, the bridge verifies the sidecar against a per-file SHA-256
manifest shipped beside it. The check is bidirectional: a missing file, a
changed byte, **and an unexpected extra file** are all integrity failures.

A sidecar that fails verification **refuses**. It is never repaired by falling
back to some other sidecar.

| Failure | Code | Meaning |
|---|---|---|
| No sidecar found at all | `sidecar_missing` | Sidecar not built in this checkout, or `HEPHAESTUS_SIDECAR` points at nothing |
| Manifest mismatch | `sidecar_integrity` | The bytes are not the bytes that were built |
| Node too old or absent | `node_incompatible` | Install Node ≥ 22.19 |

`heph agent` prints `<code>: <message>` and exits 2, so a CI lane can key on the
code rather than on prose.

MCP (`heph serve --mcp`) is optional. It needs the same sidecar only for
agent-backed tools; the engine tool surface does not. See [mcp.md](mcp.md).

### Optional: operator workspace

`web/` exists on `main`. `heph serve --web` is the operator workspace — optional
chrome, not the agent core. It serves the built client from `web/dist` (or the
API alone if you have not built it). See [cli.md](cli.md) and
[CONTRIBUTING.md](../CONTRIBUTING.md).

```console
$ pnpm --dir web install --frozen-lockfile
$ pnpm --dir web build
$ uv run heph serve --web
```

## Verifying the install

```console
$ uv run heph --version
heph 0.1.0

$ uv run heph --help          # the verb list; `bench` appears after `uv sync --dev`
$ uv run heph check --json    # inside a project: the engine path, no Node
```

`heph agent` needs the sidecar built first (tier 3 above). If you want to
confirm which sidecar a session would use:

```console
$ uv run python -c "from hephaestus.agent_bridge.sidecar import resolve_sidecar; \
  r = resolve_sidecar(); print(r.source, r.root)"
```

After `uv sync --dev` on a bare checkout, `source` is `development` once you
have bundled `agent/build/sidecar`, or the call refuses with `sidecar_missing`
until you do. `source` is `packaged` only for an installed wheel that includes
`_sidecar/`. `override` is only when you set `HEPHAESTUS_SIDECAR` yourself.

## Environment variables

| Variable | Effect |
|---|---|
| `HEPHAESTUS_SIDECAR` | Use this sidecar directory instead of the packaged or development one. Highest precedence, still integrity-verified. |
| `HEPHAESTUS_NODE` | Spawn exactly this Node binary, verbatim, with no version gate. The test-harness escape hatch; the ≥ 22.19 gate applies to Node discovered on `PATH`. |
| `HEPHAESTUS_AGENT_PROVIDERS` | Path to the provider config `heph agent` should load (see [cli.md](cli.md)). |

Nothing else about your environment reaches the sidecar. The supervisor builds a
minimal environment and forwards **only** the credential variables named in your
provider config's allowlist — an ambient `ANTHROPIC_API_KEY` that you did not
list is not passed on.

## Building a wheel

You do not need this to *use* Hephaestus from a clone. It is how a release
wheel is built, and it is the reason a `git+…#subdirectory=…` install cannot
work today: without a staged sidecar, `server/hatch_build.py` refuses the
non-editable build. The full recipe, the measured artifact sizes, and the
reasoning behind bundling rather than vendoring are in `PACKAGING.md`:

```console
$ pnpm --dir agent install --frozen-lockfile
$ pnpm --dir agent run bundle
$ uv run python scripts/stage_sidecar.py
$ uv build --all-packages --out-dir dist
```
