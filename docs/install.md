<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# Install

Clone this repository. Hephaestus is not on PyPI, and there is no GitHub
Release. The import package is `hephaestus`; the CLI binary is `heph`.

```console
$ git clone https://github.com/autonome-research/hephaestus && cd hephaestus
$ uv sync --dev
$ uv run heph --version
heph 0.1.0
```

`uv sync --dev` is an editable workspace install. Run `heph` with
`uv run heph` from the clone, or put `.venv/bin` on `PATH`.

## What each capability needs

- **Engine verbs** (`heph init`, `part`, `script`, `params`, `prompt`,
  `build`, `check`, `lint`, `render`, and the rest of the CAD CLI) — any
  Python 3.11–3.14. No Node, no browser, no network.
- **Sandboxed script execution** — Linux x86_64 with bubblewrap (≥ 0.11).
  Part scripts run in a probed OS sandbox. Anywhere the probe fails, `heph
  build` exits non-zero (`sandbox_unavailable`); it never silently downgrades.
  `heph build --unsafe-local-executor` is a local debug hatch with no OS
  sandbox. It is refused for registry content and under `heph serve`.
- **macOS** — no script execution in v0.1. `heph lint`, schema/contract reads,
  and `heph --version` work. A capability-tested OCI backend is post-v0.1.
- **Agent sidecar** (`heph agent`, agent-backed serve) — Node ≥ 22.19 on
  `PATH`, after you build the sidecar in this checkout:

  ```console
  $ pnpm --dir agent install --frozen-lockfile
  $ pnpm --dir agent run bundle
  $ uv run python scripts/stage_sidecar.py
  ```

- **Operator UI** — optional. `pnpm --dir web install --frozen-lockfile`,
  `pnpm --dir web build`, then `uv run heph serve --web` from a project.

Wheel and sidecar packaging (integrity, `uv build`, why the sidecar is
bundled): [PACKAGING.md](../PACKAGING.md). MCP is optional:
[mcp.md](mcp.md).

## Verify

```console
$ uv run heph --version
heph 0.1.0

$ uv run heph --help
$ uv run heph check --json    # inside a project: the engine path, no Node
```

`heph agent` needs the sidecar built first.
