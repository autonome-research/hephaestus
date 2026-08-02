# Hephaestus

Agent-native parametric CAD. Design parts as Python scripts, build them through a
sandboxed geometry kernel, and drive the whole surface from an LLM agent or an
MCP client.

```console
$ pip install hephaestus-cad
$ heph --version
$ heph build
```

`hephaestus-cad` is the headless distribution: the `heph` CLI, the MCP server,
and the packaged agent sidecar. No web UI, no browser dependency.

## What you get

| Command | Needs Node? | What it does |
|---|---|---|
| `heph build` / `check` / `lint` / `render` | no | Build parts, run checks, lint scripts, render views |
| `heph registry` / `reference` / `diff` / `assembly` | no | Pin registries, manage references, diff projects, check assemblies |
| `heph serve --mcp` | for agent tools | Serve the tool surface to an MCP client |
| `heph agent` | yes | Run an agent session against the packaged sidecar |

Node ≥22.19 is a runtime prerequisite for `heph agent` and agent-enabled
serving only. Every other verb runs on Python alone.

The agent sidecar is compiled into this distribution and integrity-checked with
a per-file SHA-256 manifest before every spawn. Hephaestus never executes a
globally installed agent binary; a missing or tampered sidecar is a named
refusal, not a fallback.

## Extras

- `pip install hephaestus-cad[bench]` adds the Tier 3 evaluation harness
  (`heph bench`, `heph cadgenbench`) and its `huggingface-hub` dependency.

## Documentation

Install, verbs, MCP client configuration, project conventions, and registry
pinning: see the [docs](https://github.com/autonome-research/hephaestus/tree/main/docs).

Licensed under Apache-2.0.
