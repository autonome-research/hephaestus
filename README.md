<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# Hephaestus

**An open agentic CAD harness.** Hephaestus pairs a language model with a real
parametric solid-modeling kernel (build123d / OpenCascade), a grounded
visual-feedback loop, and a persistent geometric verification layer, so that an
agent can design, inspect, iterate on, and export manufacturable parts from a
terminal. The web UI is optional operator chrome. MCP is optional.

Hephaestus is an Autonome Research Labs project, licensed Apache-2.0.

## Why

Commercial AI-CAD products (the reference point for this project is Smith by
Arche) have demonstrated that the agent-plus-kernel loop works: a model that
can write parametric scripts, *see* multi-view renders of what it built,
measure interference numerically, and repair its own failures produces genuinely
manufacturable output. But those products are closed at every layer that
matters: the model is proprietary, the harness is browser-bound, the parts and
skills catalogs are walled, and design history is an opaque version badge.

Hephaestus inverts each of those decisions:

| Axis | Closed products | Hephaestus |
|---|---|---|
| Model | Locked to a house model | API and local-model endpoints compatibility-tested through the pinned Pi runtime; the benchmark corpus measures which are good at CAD |
| Surface | Browser-only webapp | Engine-first: the CLI is the agent core; the web UI is optional operator chrome (`heph serve --web`); MCP is optional |
| Versioning | Opaque `v1*` badge | Plain files in git; branches, PRs, blame, CI |
| Verification | Transient, in-loop only | Persistent geometric spec tests re-run on every build |
| Skills / parts / materials | Closed catalogs | Open, versioned, community-contributed registries |
| Provenance | Implicit | Source maps: every solid and face traceable to the statement that made it |

The load-bearing consequence of "engine-first": the agent core is the CLI and
the headless engine. A CI pipeline, a local shell, or any agent that can run
`heph` gains CAD capability without a browser and without MCP. The web UI is
optional operator chrome — one way to look at a project — not the product.
`heph serve --mcp` is there if you want it; nothing requires it.

## What already works about the approach

The design of this harness is grounded in a close reading of a working
commercial system. The following were directly observed and are adopted here
(see `architecture.md` for the full evidence-to-decision mapping):

- Parametric scripts in build123d, one script per part, with a
  bounded-parameter block (`PARAMS`) that drives generated UI controls.
- A project-shared constants namespace so parts can reference each other's
  interface dimensions (mortise positions, sheet thicknesses) without copying
  numbers.
- Statement-level incremental execution with last-good checkpointing: a failed
  build reports the exact failing line, the last statement that succeeded, and
  the metrics of the last valid geometry — and the agent can render that
  last-good state before attempting a fix.
- Grounded vision: every build can be inspected as multi-view RGB renders plus
  face/part-ID mask renders, giving the model pixel-space observations it can
  cross-reference with kernel-space measurements.
- Manufacturing metadata as first-class part properties (process, stock,
  tolerances, finish, assembly method), including per-feature metadata attached
  to semantically tagged topology.
- Face selection spawning a scoped "quick edit" agent with the selection as
  context, rather than attempting parametric direct manipulation.

## What Hephaestus adds

Three capabilities with no observed equivalent in the reference product:

1. **Persistent spec tests.** `CHECKS` blocks in part scripts declare
   geometric invariants (clearances, bounding boxes, manifoldness, mass
   budgets). They re-run on every rebuild forever, not just in the turn where
   the agent happened to measure. Geometry gets TDD.
2. **Source maps.** The executor records which statement produced every solid
   and, via topology tags, every labeled face. Selection in any client resolves
   to code, and the scoped agent receives exact line context.
3. **Open registries.** Skills (markdown packs), parts (parametric
   generators), materials, and DFM rule packs (per process: laser, CNC router,
   FDM) are versioned artifacts that anyone can publish and pin.

## Repository map

```
hephaestus/
├── README.md                  ← you are here
├── architecture.md            system architecture and evidence base
├── script_contract.md         the part-script authoring contract
├── tool_schema.md             agent tool definitions
├── verification.md            verification harness: tiers, corpus, CI
├── mission_plan.md            phased droid mission with verifiable gates
├── repo_conventions.md        packaging, layout, licensing, naming
├── opstore/                   Python: reusable WAL/idempotency/lease/GC substrate
├── core/                      Python: CAD executor, kernel, render, checks + opstore adapters
├── agent/                     TypeScript: Pi SDK runtime + thread-phase workflows
├── server/                    Python: MCP/HTTP API + Node agent bridge
├── web/                       TypeScript: React + three.js operator chrome (`heph serve --web`)
├── registries/                skills/, parts/, materials/, dfm/
└── corpus/                    golden prompts + expected assertions
```

## Status

Under active construction, engine-first. Stages S through 3 are complete with
green gates (durability substrate, CAD engine, render service, agent runtime,
MCP server); the validation ladder (Stage 2V) and manufacturing depth (Stage 6)
continue.

Public v0.1 is the **engine-first CLI**: `heph` is the agent core. `web/` exists
on `main` as optional operator chrome — `heph serve --web` is the operator
workspace. MCP (`heph serve --mcp`) is optional and not required to use the
engine.

There is **no PyPI package** and **no GitHub Release**. Tag `v0.1.0-headless`
is a historical headless cut; it has no `web/` and is not an install path.
Install from a clone of this repository ([Install](#install)).

Originally documented as: pre-implementation. `mission_plan.md` is the operative document: a
staged droid mission in which every stage gates on machine-checkable evidence
(pytest/pnpm exit codes, deterministic render comparisons,
Playwright/computer-use screenshot assertions, and benchmark success rates).
The agent layer embeds Pi for individual sessions and uses thread-phase only
for deterministic multi-session workflows; the Python CAD engine remains
independent. The Python CAD CLI works without Node on every supported Python
platform. In v0.1, script execution is supported on Linux x86_64 with probed
bubblewrap isolation. On macOS, script execution refuses by design; a
capability-tested Docker/Podman/OrbStack-compatible OCI backend is post-v0.1.
Everything that does not execute part scripts (`heph lint`, schema/contract
reads, `heph --version`) works on macOS today. Script execution fails closed
anywhere else.
No stage advances on human vibes.

## Install

Hephaestus is **not on PyPI**. There is no GitHub Release. `pip install
hephaestus-cad` 404s. Do not install from a `git+…#subdirectory=…` URL — the
agent sidecar is gitignored build output, and `server/hatch_build.py` refuses a
non-editable `hephaestus-server` wheel without it.

Install from a clone:

```console
$ git clone https://github.com/autonome-research/hephaestus && cd hephaestus
$ uv sync --dev
$ uv run heph --version
```

Python 3.11 through 3.14. Capability tiers (engine vs sandbox vs agent/Node)
and the optional operator workspace: [docs/install.md](docs/install.md).
Contributor checks: [CONTRIBUTING.md](CONTRIBUTING.md).
