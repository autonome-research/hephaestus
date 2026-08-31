<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# Hephaestus documentation

Install from a clone — [install.md](install.md). The CLI is the product:
`heph part` / `script` / `params` / `prompt` / `build` need no browser and
no MCP. The operator UI (`heph serve --web`) is optional. MCP is optional.

| Page | What it covers |
|---|---|
| [install.md](install.md) | Clone, `uv sync --dev`, what each capability needs |
| [cli.md](cli.md) | Every `heph` verb — including `part` / `script` / `params` / `prompt` — with one worked example each |
| [mcp.md](mcp.md) | Optional: a stock MCP client against `heph serve --mcp` |
| [conventions.md](conventions.md) | Project layout, part scripts, `PARAMS` / `hc` / `CHECKS` |
| [registry-pinning.md](registry-pinning.md) | Pinning skills/parts/materials/DFM registries |
| [leaderboard.md](leaderboard.md) | Generated model leaderboard |

Contributing: [CONTRIBUTING.md](../CONTRIBUTING.md), and
[registry-contributions.md](registry-contributions.md) for a DFM pack,
material, part generator, or skill.

## Design documents (repository root)

These stay in the tree. They are not the front door.

| Document | Subject |
|---|---|
| `README.md` | What the project is and how to use it |
| `architecture.md` | Component boundaries and the threat model |
| `script_contract.md` | Part-script contract |
| `tool_schema.md` | Agent/MCP tool surface |
| `repo_conventions.md` | Layout, naming, packaging, licensing |
| `verification.md` | CI contract and corpus integrity |
| `VALIDATION.md` | Validation ladder and reported metrics |
| `PACKAGING.md` | Wheel and sidecar build |
| `COMPARE.md`, `ASSEMBLY.md`, `INGEST.md`, `EXTERNAL_EVAL.md` | Stage 8 capability specs |

## Checking these docs

```console
$ uv run python scripts/docs_check.py
```

The checker resolves relative links, backticked repository paths, and `§N`
section references. That is Gate G7H's docs clause — one tool, no site
generator.
