# Hephaestus

**An open agentic CAD harness.** Hephaestus pairs a language model with a real
parametric solid-modeling kernel (build123d / OpenCascade), a grounded
visual-feedback loop, and a persistent geometric verification layer, so that an
agent can design, inspect, iterate on, and export manufacturable parts — from a
terminal, from any MCP client, or from a web workspace.

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
| Model | Locked to a house model | Any API or local model; the benchmark corpus measures which are good at CAD |
| Surface | Browser-only webapp | Engine-first: CLI and MCP server are the product; the web UI is a client |
| Versioning | Opaque `v1*` badge | Plain files in git; branches, PRs, blame, CI |
| Verification | Transient, in-loop only | Persistent geometric spec tests re-run on every build |
| Skills / parts / materials | Closed catalogs | Open, versioned, community-contributed registries |
| Provenance | Implicit | Source maps: every solid and face traceable to the statement that made it |

The load-bearing consequence of "engine-first": because the core loop is
exposed over MCP, *any* agent environment — Claude Code, a droid fleet, a CI
pipeline — gains CAD capability without touching a browser. The web UI is one
client among several, not the product.

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
├── core/                      Python: executor, kernel services, render, checks
├── agent/                     TypeScript: Pi SDK runtime + thread-phase workflows
├── server/                    Python: MCP/HTTP API + Node agent bridge
├── web/                       TypeScript: React + three.js client
├── registries/                skills/, parts/, materials/, dfm/
└── corpus/                    golden prompts + expected assertions
```

## Status

Pre-implementation. `mission_plan.md` is the operative document: a
staged droid mission in which every stage gates on machine-checkable evidence
(pytest/pnpm exit codes, deterministic render comparisons,
Playwright/computer-use screenshot assertions, and benchmark success rates).
The agent layer embeds Pi for individual sessions and uses thread-phase only
for deterministic multi-session workflows; the Python CAD engine remains
independent. No stage advances on human vibes.
