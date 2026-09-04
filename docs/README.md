<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# Hephaestus documentation

Install from a clone — [install.md](install.md); `scripts/bootstrap.sh` is the
one command that does all of it. The CLI is the product:
`heph part` / `script` / `params` / `prompt` / `build` need no browser and
no MCP. The operator UI (`heph serve --web`) is optional. MCP is optional.

| Page | What it covers |
|---|---|
| [install.md](install.md) | Clone and `scripts/bootstrap.sh`, what each capability needs, running `heph` from outside the clone |
| [cli.md](cli.md) | Every `heph` verb — including `part` / `script` / `params` / `prompt` — with one worked example each |
| [mcp.md](mcp.md) | Optional: a stock MCP client against `heph serve --mcp` |
| [conventions.md](conventions.md) | Project layout, part scripts, `PARAMS` / `hc` / `CHECKS` |
| [registry-pinning.md](registry-pinning.md) | Pinning skills/parts/materials/DFM registries |
| [leaderboard.md](leaderboard.md) | Generated model leaderboard |

Contributing: [CONTRIBUTING.md](../CONTRIBUTING.md), and
[registry-contributions.md](registry-contributions.md) for a DFM pack,
material, part generator, or skill.

## Design and status documents (repository root)

These stay in the tree because they define or record repository contracts; they
are not the user-facing front door. `mission_plan.md` is authoritative for stage
scope. A document marked draft does not enter mission scope by itself.

| Document | Status | Subject |
|---|---|---|
| `README.md` | User-facing | What the project is and how to use it |
| `mission_plan.md` | Authoritative | Mission stages, gates, and current scope |
| `architecture.md` | Foundational draft | Component boundaries and threat model |
| `script_contract.md` | Normative | Part-script contract |
| `tool_schema.md` | Normative | Agent/MCP tool surface |
| `repo_conventions.md` | Normative | Layout, naming, packaging, and licensing |
| `verification.md` | Normative | CI contract and corpus integrity |
| `VALIDATION.md` | Normative | Validation ladder and reported metrics |
| `PACKAGING.md` | Normative | Wheel and sidecar build |
| `INGEST.md`, `COMPARE.md`, `ASSEMBLY.md`, `EXTERNAL_EVAL.md` | Normative | Stage 8 capability specifications |
| `KINEMATICS.md` | Normative | Stage 9 joints, poses, and motion checks |
| `INTERFACE.md` | Mixed; see its header | Workspace specification; only promoted sections are normative |
| `PARTS_STORE.md` | Normative | Stage 11 component store and registries |
| `MESH_INGEST.md` | Normative | Stage 12 mesh and scan ingest |
| `SOLVER.md` | Normative | Stage 13 pose solving and placement proposals |
| `CAM.md`, `PHYSICS.md` | Draft | Proposed future manufacturing and structural-analysis stages |
| `RELEASE_FACTS.md` | Historical survey | Read-only Stage 7H repository findings |

## Historical plans and decision records

These preserve review and amendment history. They are non-normative; use
`mission_plan.md` and the promoted specifications above for current behavior.

| Document | Subject |
|---|---|
| [workspace-plan.md](workspace-plan.md) | Approved workspace review plan whose amendments have landed elsewhere |
| [frontier-staging-proposal.md](frontier-staging-proposal.md) | Frontier-stage drafting record containing intentionally superseded stage text |

## Checking these docs

```console
$ uv run python scripts/docs_check.py
```

The checker covers the user guides and the active normative root set named in
`scripts/docs_check.py`; draft and historical surveys are intentionally outside
that gate. It resolves relative links, backticked repository paths (including
line-range citations), and `§N` section references. That is Gate G7H's docs
clause — one tool, no site generator.
