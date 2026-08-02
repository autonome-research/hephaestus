<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# Hephaestus documentation (headless)

This is the documentation set for **v0.1.0-headless**: the Python wheel, the
`heph` CLI, the MCP server, and the packaged agent sidecar. There is no web UI
in this release and nothing here needs a browser.

These pages are the *user-facing* half of the documentation. The normative
design and mission documents live at the repository root and win any
disagreement; each page below names the ones it distills.

| Page | What it covers |
|---|---|
| [install.md](install.md) | Installing the wheel, what each capability actually requires, and how to verify the install |
| [cli.md](cli.md) | Every `heph` verb, with one honest worked example each |
| [mcp.md](mcp.md) | Configuring a stock MCP client against `heph serve --mcp` |
| [conventions.md](conventions.md) | What a Hephaestus project is: layout, part scripts, `PARAMS`/`hc`/`CHECKS`, and what the executor will and will not allow |
| [registry-pinning.md](registry-pinning.md) | Pinning skills/parts/materials/DFM registries by Merkle digest, and what a pin buys you |
| [leaderboard.md](leaderboard.md) | Generated model leaderboard — which models can do CAD here, and the interpretation tax |

Contributing: [CONTRIBUTING.md](../CONTRIBUTING.md), and
[registry-contributions.md](registry-contributions.md) for adding a DFM pack,
material, part generator, or skill.

## Normative documents (repository root)

| Document | Authority over |
|---|---|
| `README.md` | What the project is and why |
| `architecture.md` | Component boundaries and the threat model |
| `script_contract.md` | The part-script contract: injected namespace, `PARAMS`, `hc`, output object, `CHECKS`, build result |
| `tool_schema.md` | The canonical agent/MCP tool surface |
| `repo_conventions.md` | Layout, naming, packaging, versioning, licensing, registry trust |
| `verification.md` | The CI contract, corpus integrity, and how gates are decided |
| `VALIDATION.md` | The validation ladder and the reported metric set |
| `PACKAGING.md` | How the wheel and its sidecar are built |
| `COMPARE.md`, `ASSEMBLY.md`, `INGEST.md`, `EXTERNAL_EVAL.md` | Stage 8 capability specs |

## Building these docs

The docs are plain Markdown — no site generator, no theme, no network. They are
built by being *checked*:

```console
$ uv run python scripts/docs_check.py
```

The checker resolves every relative link, every backticked repository path, and
every `§N` section reference in this set and in the root normative documents,
and exits non-zero on the first unresolved one. That is the "docs build without
warnings" clause of Gate G7H, and it is also the docs-layout/link check
`verification.md` requires — one tool, because they are the same job.

A static-site build was deliberately not introduced. Every consumer of this set
(GitHub, an editor, `less`, a model reading the repository) already renders
Markdown, and a generator would add a dependency whose only output is the input
with CSS on it.
