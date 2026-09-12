# What Hephaestus is

> **Verified against** `3af69da` on 2026-09-12.
> Sources checked: `README.md`, `uv run heph --help`, `uv run heph serve --help`,
> `pyproject.toml`, each package's `pyproject.toml` / `package.json`.

## In one paragraph

Hephaestus is open-source **parametric CAD**. A part is a Python script written
against [build123d](https://github.com/gumyr/build123d); the `heph` command
builds it into solid geometry, checks it, renders it, and records every result
in a durable store. On top of that engine sit three optional surfaces: an HTTP
server with a browser workspace, a Model Context Protocol server, and an agent
bridge that lets a language model drive the same operations through a declared
tool catalogue. It is an Autonome Research project, licensed Apache-2.0.

## The problem it addresses

CAD that an agent can drive has to answer a harder question than CAD a person
drives: **what is actually true about this model, and how do you know?**

A person looking at a screen can see that a bracket is wrong. A model cannot.
So the system is built so that every answer it gives is either a measurement it
made or a refusal it names — and the two are never confused. That single
commitment explains most of the design:

- Operations that cannot produce evidence **refuse by name** rather than
  returning a plausible number.
- A measurement that could not be taken is reported as *unverifiable*, not as a
  failure and not as a pass.
- A solve proposes; it does not silently move geometry.
- A result's provenance — which build, which script, which inputs — is
  addressable, so a claim can be re-checked later.

The practical consequence is a large refusal vocabulary and an unusual number
of structural tests. Both are deliberate. See
[the refusal vocabulary](../04-reference/refusal-vocabulary.md).

## What you can do with it

From the command line, with no server and no browser
(`uv run heph --help`):

| Area | Verbs |
| --- | --- |
| Project and parts | `init`, `part`, `script`, `params`, `prompt` |
| Build and verify | `build`, `check`, `lint`, `diff` |
| Visual output | `render`, `goldens` |
| Assemblies and motion | `assembly`, `joints`, `motion`, `solve`, `proposals` |
| External geometry | `import`, `scan`, `reference`, `registry` |
| Manufacturing output | `cam` |
| Distribution | `export` |
| Agents and evaluation | `agent`, `bench`, `serve` |

`heph serve` has three modes (`uv run heph serve --help`): `--web` for the
browser workspace API, `--mcp` for the Model Context Protocol surface, and
`--http` to serve MCP over streamable HTTP instead of stdio.

## The shape of the system

Six Python packages in one `uv` workspace, plus two Node packages:

| Package | Language | What it is |
| --- | --- | --- |
| `opstore` | Python, stdlib only | the durability substrate: content-addressed blobs, idempotency keys, a write-ahead log, leases, run admission, garbage collection |
| `core` | Python | the CAD engine: project store, part scripts, the sandboxed executor, geometry, assemblies, the solver, checks, render, CAM — and the `heph` CLI |
| `server` | Python | the HTTP workspace API, the MCP server, and the agent bridge |
| `contract` | Python, stdlib only | the single declaration of the agent tool catalogue, from which JSON Schemas and TypeScript types are generated |
| `bench` | Python | the scored agent benchmark |
| `packaging` | Python | wheel packaging support |
| `agent` | TypeScript | the sidecar process that talks to model providers and runs agent sessions |
| `web` | TypeScript, React | the operator workspace in the browser |

The one console entry point is `heph`
(`core/pyproject.toml`: `heph = "hephaestus.core.cli:main"`). The server, bench
and agent surfaces are reached through its subcommands rather than through
separate binaries.

Why the split matters: `opstore` and `contract` declare no third-party
dependencies at all, which is what lets durability and the tool contract be
tested and reasoned about without the CAD kernel present.

## What it is not

- **Not a hosted service.** `heph prompt` stores request text in your project;
  it is not a chat backend.
- **Not a GUI-first CAD tool.** The browser workspace is operator chrome over
  the engine; everything it does, the CLI does.
- **Not published.** It is not on PyPI and there is no GitHub release; you build
  it from a clone.

## Where to go next

- Do it once, end to end: [Your first part](../02-tutorial/your-first-part.md).
- Set up a machine: [Install and run](../03-how-to/install-and-run.md).
- Understand the structure: [Architecture](../05-architecture/README.md).
- Look something up: [Reference](../04-reference/).
