# Hephaestus

Agent-native parametric CAD. Design parts as Python scripts, build them through a
sandboxed geometry kernel, and drive the whole surface from the `heph` CLI.

This file is the long description of the intended `hephaestus-cad` aggregate
wheel. That wheel is **not published**: there is no PyPI package and no GitHub
Release. Until wheels that include the packaged `_sidecar/` exist, do not
`pip install hephaestus-cad` and do not install from a
`git+…#subdirectory=…` URL (`server/hatch_build.py` refuses a non-editable
`hephaestus-server` wheel without the sidecar, and the sidecar is gitignored).

Install from a clone:

```console
$ git clone https://github.com/autonome-research/hephaestus && cd hephaestus
$ uv sync --dev
$ uv run heph --version
$ uv run heph build
```

`uv sync --dev` is the headless engine install: the `heph` CLI and the
workspace members it needs. MCP (`heph serve --mcp`) is optional. The web UI
(`heph serve --web`) is optional operator chrome.

## What you get

| Command | Needs Node? | What it does |
|---|---|---|
| `heph build` / `check` / `lint` / `render` | no | Build parts, run checks, lint scripts, render views |
| `heph registry` / `reference` / `diff` / `assembly` | no | Pin registries, manage references, diff projects, check assemblies |
| `heph serve --mcp` | for agent tools | Optional: serve the tool surface to an MCP client |
| `heph serve --web` | no (client is `web/dist`) | Optional operator workspace |
| `heph agent` | yes | Run an agent session against a built sidecar |

Node ≥22.19 is a runtime prerequisite for `heph agent` and agent-enabled
serving only. Every other verb runs on Python alone.

In a *published* wheel the agent sidecar would be compiled into the
distribution and integrity-checked with a per-file SHA-256 manifest before
every spawn. That wheel does not exist yet. In a clone, build the sidecar
yourself (`PACKAGING.md`) before `heph agent`. Hephaestus never executes a
globally installed agent binary; a missing or tampered sidecar is a named
refusal, not a fallback.

## Extras

`uv sync --dev` includes `hephaestus-bench` (the Tier 3 evaluation harness:
`heph bench`, `heph cadgenbench`). On a future published wheel that extra
would be `hephaestus-cad[bench]`; do not `pip install` that name from the
index today.

## Documentation

Install, verbs, optional MCP client configuration, project conventions, and
registry pinning: see the [docs](https://github.com/autonome-research/hephaestus/tree/main/docs).

Licensed under Apache-2.0.
