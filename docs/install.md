<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# Install

The public product is the **headless** `hephaestus-cad` aggregate: CLI `heph`,
MCP server, packaged agent sidecar. The import package is `hephaestus`
regardless (`repo_conventions.md`).

**Not on PyPI.** Tag `v0.1.0-headless` exists on this repository; the name
`hephaestus-cad` is not published to the Python Package Index, so
`pip install hephaestus-cad` / `pipx install hephaestus-cad` /
`uv tool install hephaestus-cad` against the index 404. Install from this
GitHub repository at that tag.

The repo root is a uv workspace (`hephaestus-workspace`, `package = false`),
not an installable project. `hephaestus-cad` lives in `packaging/` and depends
on four in-repo distributions that are also unpublished. Pull them from the
same tag — otherwise the installer looks on PyPI and 404s.

```console
$ uv pip install \
    "opstore @ git+https://github.com/autonome-research/hephaestus.git@v0.1.0-headless#subdirectory=opstore" \
    "hephaestus-contract @ git+https://github.com/autonome-research/hephaestus.git@v0.1.0-headless#subdirectory=contract" \
    "hephaestus-core @ git+https://github.com/autonome-research/hephaestus.git@v0.1.0-headless#subdirectory=core" \
    "hephaestus-server @ git+https://github.com/autonome-research/hephaestus.git@v0.1.0-headless#subdirectory=server" \
    "hephaestus-cad @ git+https://github.com/autonome-research/hephaestus.git@v0.1.0-headless#subdirectory=packaging"
$ heph --version
heph 0.1.0
```

```console
$ pip install \
    "opstore @ git+https://github.com/autonome-research/hephaestus.git@v0.1.0-headless#subdirectory=opstore" \
    "hephaestus-contract @ git+https://github.com/autonome-research/hephaestus.git@v0.1.0-headless#subdirectory=contract" \
    "hephaestus-core @ git+https://github.com/autonome-research/hephaestus.git@v0.1.0-headless#subdirectory=core" \
    "hephaestus-server @ git+https://github.com/autonome-research/hephaestus.git@v0.1.0-headless#subdirectory=server" \
    "hephaestus-cad @ git+https://github.com/autonome-research/hephaestus.git@v0.1.0-headless#subdirectory=packaging"
$ heph --version
heph 0.1.0
```

`heph` is a tool, not a library you import into your own project. Prefer a
venv (or `uv pip install` into one uv manages) so one binary lands on `PATH`.
Nothing in Hephaestus inspects how it was installed. A clone of the tag plus
`uv sync` is the contributor path — [CONTRIBUTING.md](../CONTRIBUTING.md).

Python 3.11 through 3.14 are supported.

## What gets installed

`hephaestus-cad` is an aggregate: it carries no code of its own and depends on
the four distributions that do. This matters when you read a traceback or pin a
version.

| Distribution | Carries |
|---|---|
| `hephaestus-core` | The CAD engine, the executor, the renderer, and the `heph` entry point |
| `hephaestus-contract` | The canonical tool-surface declaration and committed JSON schemas |
| `hephaestus-server` | The agent bridge, the MCP server, and **the compiled agent sidecar** |
| `opstore` | The durable op/WAL store the project store is built on (internal component, not a separate product) |

The evaluation harness is deliberately **not** installed by default — it pulls
dataset tooling no one modeling a bracket should have to download. Extra
`bench` is the unpublished `hephaestus-bench` member (`bench/` on the same tag):

```console
$ pip install \
    "hephaestus-bench @ git+https://github.com/autonome-research/hephaestus.git@v0.1.0-headless#subdirectory=bench" \
    "hephaestus-cad[bench] @ git+https://github.com/autonome-research/hephaestus.git@v0.1.0-headless#subdirectory=packaging"
```

(Plus the four members above if they are not already installed.) `heph bench`
simply does not appear in `heph --help` without it. See [cli.md](cli.md).

## What each capability requires

Hephaestus has three capability tiers and they have genuinely different
prerequisites. Installing the distribution gets you the first one everywhere.

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
- **macOS**: in v0.1.0-headless, script execution refuses by design
  (deferred 2026-08-13, operator decision). The planned macOS path — a
  capability-tested Docker/Podman/OrbStack-compatible OCI backend running the
  pinned Linux executor profile — ships post-v0.1. Everything that does not
  execute part scripts (`heph lint`, schema/contract reads, `heph --version`)
  works on macOS today.
- **Anywhere else**, script execution **fails closed**. `heph build` exits
  non-zero with a structured capability error; it never silently downgrades.

There is a debug escape hatch, `heph build --unsafe-local-executor`, which runs
the worker with no OS sandboxing. It is refused outright for registry content
and for anything under `heph serve` — `unsafe_refused`, flag or no flag — because
those are exactly the paths where the code came from somewhere else.

### 3. The agent and the MCP tool surface — Node ≥ 22.19

`heph agent` and agent-backed serving spawn the compiled agent sidecar, which
needs a Node ≥ 22.19 runtime on `PATH`. The sidecar itself is **packaged inside
the wheel**; it is never a globally installed `pi` or `thread-phase` binary, and
there is no fallback that would make it one.

Before spawning, the bridge verifies the packaged sidecar against a per-file
SHA-256 manifest shipped beside it. The check is bidirectional: a missing file,
a changed byte, **and an unexpected extra file** are all integrity failures. The
extra-file direction is not paranoia — the sidecar is a bundled chunk graph, so
a planted module is reachable the moment an existing chunk names it.

A sidecar that fails verification **refuses**. It is never repaired by falling
back to some other sidecar.

| Failure | Code | Meaning |
|---|---|---|
| No sidecar found at all | `sidecar_missing` | Broken install, or `HEPHAESTUS_SIDECAR` points at nothing |
| Manifest mismatch | `sidecar_integrity` | The shipped bytes are not the bytes that were built |
| Node too old or absent | `node_incompatible` | Install Node ≥ 22.19 |

`heph agent` prints `<code>: <message>` and exits 2, so a CI lane can key on the
code rather than on prose.

## Verifying the install

```console
$ heph --version
heph 0.1.0

$ heph --help                     # the verb list; `bench` appears only with the extra
$ heph check --json               # inside a project: the engine path, no Node
$ heph agent --project .          # the agent path: Node + packaged sidecar + a provider config
```

If you want to confirm the install is using *its own* sidecar rather than
something on your machine, ask for the resolution directly:

```console
$ python -c "from hephaestus.agent_bridge.sidecar import resolve_sidecar; \
  r = resolve_sidecar(); print(r.source, r.root)"
packaged /home/you/.venv/lib/python3.13/site-packages/hephaestus/agent_bridge/_sidecar
```

`source` is `packaged` for any installed distribution. It is `development` only
in a checkout of this repository that has no packaged sidecar, and `override`
only when you set `HEPHAESTUS_SIDECAR` yourself.

## Environment variables

| Variable | Effect |
|---|---|
| `HEPHAESTUS_SIDECAR` | Use this sidecar directory instead of the packaged one. Highest precedence, still integrity-verified. |
| `HEPHAESTUS_NODE` | Spawn exactly this Node binary, verbatim, with no version gate. The test-harness escape hatch; the ≥ 22.19 gate applies to Node discovered on `PATH`. |
| `HEPHAESTUS_AGENT_PROVIDERS` | Path to the provider config `heph agent` should load (see [cli.md](cli.md)). |

Nothing else about your environment reaches the sidecar. The supervisor builds a
minimal environment and forwards **only** the credential variables named in your
provider config's allowlist — an ambient `ANTHROPIC_API_KEY` that you did not
list is not passed on.

## Building from source

You do not need this to use Hephaestus, only to develop it or to audit the
sidecar bundle yourself. The full recipe, the measured artifact sizes, and the
reasoning behind bundling rather than vendoring are in `PACKAGING.md`:

```console
$ pnpm --dir agent install --frozen-lockfile
$ pnpm --dir agent run bundle
$ uv run python scripts/stage_sidecar.py
$ uv build --all-packages --out-dir dist
```
