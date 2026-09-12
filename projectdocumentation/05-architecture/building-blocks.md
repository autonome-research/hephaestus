# Building block view

> **Verified against** `49a90c6` on 2026-09-12.
> Module inventories from `ls` on each package; responsibilities read from each
> module's own docstring.

arc42 section 5. Three levels, following the C4 model: containers, then the
components inside each, then the modules that matter.

## Level 1: containers

```
┌───────────────────────────── one machine ──────────────────────────────┐
│                                                                        │
│  ┌──────────┐   subprocess   ┌──────────────┐   framed JSON-RPC        │
│  │   heph   │───────────────▶│  build       │   over stdio             │
│  │   CLI    │   (bubblewrap) │  worker      │       ┌──────────────┐   │
│  └────┬─────┘                └──────────────┘   ┌──▶│  sidecar     │   │
│       │                                         │   │  (Node/TS)   │───┼──▶ provider
│       │  in-process                             │   └──────────────┘   │
│       ▼                                         │                      │
│  ┌─────────────────────────────────────────┐    │                      │
│  │  engine (core) + dispatcher             │────┘                      │
│  │  + opstore  ← .heph/state.db, blobs/    │                           │
│  └─────────────────────────────────────────┘                           │
│       ▲                     ▲                                          │
│       │ HTTP (loopback)     │ MCP (stdio or HTTP)                       │
│  ┌────┴─────┐          ┌────┴─────┐                                     │
│  │ web      │          │ MCP host │                                     │
│  │ (React)  │          └──────────┘                                     │
│  └──────────┘                                                           │
└────────────────────────────────────────────────────────────────────────┘
```

## Level 1 inventory

Six Python packages in one `uv` workspace, two Node packages.

| Package | Deps | Responsibility |
| --- | --- | --- |
| `opstore` | **none** | durability substrate |
| `contract` | **none** | the tool declaration and its generators |
| `core` | build123d, OCCT, … | the CAD engine and the `heph` CLI |
| `server` | `core`, `contract`, Starlette, fastmcp | HTTP, MCP, agent bridge |
| `bench` | `server` | the scored agent benchmark |
| `packaging` | — | wheel packaging support |
| `agent` | TypeScript, Node ≥ 22.19 | the sidecar that talks to providers |
| `web` | React, three.js, Monaco | the operator workspace |

The two zero-dependency packages are the load-bearing part of the split: they are
what let durability and the tool contract be tested and reasoned about without
the CAD kernel present.

## Level 2: inside `core`

| Area | Modules | What it owns |
| --- | --- | --- |
| project store | `project_store/` — `layout`, `store`, `publication`, `artifact_kinds`, `retention`, `locks`, `listing`, `projections`, `references`, `constraints`, `kinematics`, `proposals` | what a project is on disk, and publication policy |
| executor | `executor/` — `runner`, `worker`, `splitter`, `namespace`, `fingerprint`, `imports`, `source_map`, `tags`, `bounded_pass`, `sandbox/` | running a part script safely and recording what happened |
| geometry | `hephaestus/geom/` — `measure`, `compare`, `topology`, `mesh`, `solve`, `constraints`, `kinematics`, `metrics`, `nesting`, `kerf`, `step_io` | the measurement and solving primitives |
| checks | `checks/` — `engine`, `report` | part-scope and cross-part checks, and their generations |
| render | `render/` — including `bundle`, `gltf`, `cameras` | PNGs, selection bundles, the GLB document |
| DFM | `dfm/` — `types`, `context`, `runner`, `worker` | manufacturability rule packs |
| registry | `registry/` | hash-pinned untrusted content |
| placement | `placement.py`, `assembly.py`, `motion.py` | solving, assemblies, motion |
| CAM | `cam.py`, `cutfile.py`, `nesting.py`, `kerf.py` | 2D cut output |
| CLI | `cli.py` plus 14 `cli_*.py` modules | the 25 verbs |

### The executor, in detail

The interesting boundary is parent versus child.

**Parent (`runner.py`).** Builds the worker job, launches it through an
`ExecBackend` — **never directly** — collects the one JSON result, computes the
input and audit hashes, and assembles a `BuildResult`.

It returns an `UnpublishedBuild` with `current=False` and no project snapshot
ref. Publication policy — the current pointer, snapshots, stale markers — belongs
to the project store. The runner does not decide what becomes current.

**Child (`worker.py`).** One JSON job on stdin, one JSON result on stdout.
Executes the script **statement by statement**, checkpointing after every
statement: index, line, verbatim statement text, span, bound names. Shape refs
are held eagerly; metrics are computed lazily.

On failure it emits a complete error record — line and column, type, message, a
±2-line frame with a `"> "` marker, `built_through`, and `last_good` metrics —
and writes the last-good BRep. On success it writes the final compound BRep plus
the geometry index, the source map and tag fingerprints.

**Artifacts are written only under the job's out dir.** The parent moves them
into content-addressed storage and mints the refs. The child never touches the
store.

Statement-level execution is what makes "it built through line 40 and then
failed" a fact rather than a guess. `splitter.py` parses the module once and
yields one statement per top-level statement with its exact span.

### The sandbox

Three modules behind one protocol.

`base.py` is a **pure protocol with no backend code** — it never imports bwrap or
the unsafe backend and contains no argv logic. Its rule: secure builds require a
passing capability report; a failing probe raises `sandbox_denied`, never a
silent fallback.

`bwrap.py` is the secure backend:

- every `ro_bind` is bound read-only **at its own host path** (identity bind), so
  the worker command's host paths work unchanged inside;
- **one** writable bind: the fresh per-build out dir, which is also the chdir;
- tmpfs `/tmp` and `/run`; private `/proc` and `/dev`; base OS from a read-only
  `/usr` bind plus the host's own top-level merged-usr entries;
  `--remount-ro /` seals everything else;
- `--unshare-net/pid/user/ipc/uts` and `--die-with-parent`;
- `--clearenv` with a minimal fixed environment — `PATH`, `HOME=/tmp`, `TMPDIR`,
  `LANG`, `PYTHONDONTWRITEBYTECODE`. No `PYTHONHASHSEED` override: determinism
  relies on the default hash randomization being irrelevant to geometry, which is
  a claim the determinism suites check rather than an assumption;
- rlimits applied in a pre-exec hook and inherited across bwrap's exec;
- a parent-side wall-clock kill of the whole process group.

`probe.py` proves the sandbox works **by running it**. A trivial job executes
inside bwrap and performs live escape probes: a network connect must fail, a
write outside the out dir must fail, `/etc/shadow` must be unreadable, and the
out dir must be writable and visible to the host. **A version string is never
trusted as evidence.**

Caching is asymmetric on purpose: only *passing* reports are cached per store
root, and failures are re-probed every time, so installing bwrap later is picked
up. The cache is invalidated when the bwrap path or version changes.

`unsafe.py` is **not a sandbox**. It runs the worker as an ordinary child with
the parent's environment and filesystem view. Every execution prints an explicit
warning to stderr, the capability report flags every isolation feature `False`,
registry content is refused outright, and `heph serve` refuses the backend
entirely. It exists for local debugging and tests. Never a default.

## Level 2: inside `server`

| Component | Modules | Responsibility |
| --- | --- | --- |
| HTTP | `http/` — 20 modules, `app.py` the route table | the workspace API |
| MCP | `mcp/` | the Model Context Protocol surface |
| agent bridge | `agent_bridge/` — 25 modules plus `cad_ops/` | the sidecar, the dispatcher, sessions, delegation, events |

### The agent bridge

| Module | Responsibility |
| --- | --- |
| `supervisor.py` | spawn, framed JSON-RPC, watchdog, orphan-free restart |
| `framing.py` / `protocol.py` | the wire: LF-delimited frames, frozen method sets, error codes |
| `dispatch.py` | profile gate → object scope → core routing |
| `cad_ops/` | everything geometric, parametric, check-, artifact- or export-related |
| `sessions.py`, `session_edges.py` | sessions and their parentage |
| `delegation.py` | delegated child part agents |
| `events.py` | the event pump: bounded queues, coalescing, durable terminals |
| `admission.py` | run slots over opstore admission |
| `jobstore.py` | the sidecar's durable key/value and checkpoints |
| `limits.py` | the one reader of `bridge_limits.json` on the Python side |
| `wiring.py`, `app.py` | assembly |

The dispatcher is the single chokepoint. Nothing in `http/` computes a result;
nothing in `mcp/` does either.

## Level 2: inside `web`

| Area | Modules |
| --- | --- |
| API | `api/` — `client`, `token`, `idempotency`, `queries`, `events`, `sessions`, `providers`, `exports`, `dfm`, `params`, `refresh` |
| state | `state/` — `workspace` (the pin authority), `shell`, `heldPart`, `visibility`, `appearance`, `pinSplit` |
| stream | `stream/` — 23 modules: socket, live, transcript, conversation, composer, follow-scroll, tool results |
| viewport | `viewport/` — `engine`, `scene`, `cameras`, `glb`, `section`, `explode`, `display` |
| design system | `system/` — 10 primitives plus tokens and type roles |
| components | `components/` — shell, header, rail, stage, inspector, stream, export |

See [the web client reference](../04-reference/web-client.md) for the rules each
of these enforces.

## Import bans that are asserted, not agreed

These are the boundaries a test enforces at import level, which is the only kind
that survives a refactor:

- `server/http` may not import `core.render` at all.
- `heph agent` may not import the web client API, even to read a file the two
  verbs share — the `serve.json` record and its reader live in one module both
  import instead.
- `executor/sandbox/base.py` may not import a backend.
- Building the CLI parser may not import the CAD kernel, the MCP stack, the HTTP
  stack or the geometry package — asserted as a module-name property in a fresh
  subprocess, not as a wall-clock threshold.

## Related

- What runs when: [runtime view](runtime-view.md).
- The rules that cut across all of this: [crosscutting concepts](crosscutting-concepts.md).
