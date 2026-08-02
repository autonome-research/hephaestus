<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# MCP client configuration

`heph serve --mcp` exposes the whole Hephaestus tool surface over the Model
Context Protocol. This is the load-bearing consequence of the engine-first
design: any MCP-capable agent environment gains CAD capability without touching
a browser, and without Hephaestus knowing which environment it is.

The server speaks two transports from one app — **stdio** for a client that
launches the process itself, and **streamable HTTP** at `/mcp` for a client that
connects to one already running. Same tools, same dispatch, same idempotency.

## Prerequisites

`heph` must be on the `PATH` of the process that launches it. If you installed
with `pipx`, it is. If you installed into a virtualenv you activate by hand,
give the client the absolute path to the binary instead of the bare name — an
MCP client launches your server from its own environment, not from your shell,
and "works in my terminal" is the single most common failure here.

Nothing else is required for the tool surface itself. Building parts through
those tools requires the secure executor ([install.md](install.md)); serve mode
never falls back to the unsafe one.

## stdio: a client that launches the server

### Claude Code

```console
$ claude mcp add hephaestus -- heph serve --mcp
```

### Claude Desktop

`claude_desktop_config.json` (macOS:
`~/Library/Application Support/Claude/`, Windows: `%APPDATA%\Claude\`):

```json
{
  "mcpServers": {
    "hephaestus": {
      "command": "heph",
      "args": ["serve", "--mcp"]
    }
  }
}
```

### VS Code, Cursor, and other `mcp.json` clients

```json
{
  "servers": {
    "hephaestus": {
      "type": "stdio",
      "command": "heph",
      "args": ["serve", "--mcp"]
    }
  }
}
```

Note that no configuration above names a project directory. That is
deliberate — see [Binding a project](#binding-a-project).

## HTTP: a client that connects to a running server

Start the server yourself:

```console
$ heph serve --mcp --http 127.0.0.1:8765
```

and point the client at `/mcp`:

```json
{
  "servers": {
    "hephaestus": {
      "type": "http",
      "url": "http://127.0.0.1:8765/mcp"
    }
  }
}
```

The default bind address is `127.0.0.1` on purpose. This server executes
model-authored code against your filesystem; it has no authentication layer of
its own, and it is not a thing to expose on a network interface. If you need it
reachable from elsewhere, put it behind something that authenticates.

## Binding a project

An MCP session with no open project can call **no project tool at all**. The
first call in a session is:

```
open_project(path="/home/you/projects/shelf")
```

An absolute path — the client's working directory is not something Hephaestus
will guess at. `list_parts()` then tells the agent what is there.

This is why the configuration snippets carry no project path: one server
instance can serve any project you point a session at, and the binding is an
explicit, auditable tool call rather than a launch-time argument nobody
remembers setting.

## What the client gets

43 tools, the same set the built-in agent drives, dispatched through the same
code path under an **MCP principal**: a local MCP client is
orchestrator-equivalent, because it *is* the agent. The canonical declarations
are in `tool_schema.md` and the committed JSON schemas under `schemas/`; broadly
they cover

- **project and parts** — `open_project`, `list_parts`, `create_part`,
  `read_part`, `write_part`, `edit_part`, `read_globals`, `edit_globals`,
  `set_params`;
- **build and inspect** — `build_part`, `inspect_part`, `measure`,
  `query_snapshot`, `read_artifact`, `compare_solids`;
- **checks and requirements** — `create_project_check`, `read_project_check`,
  `edit_project_check`, `list_project_checks`, `run_checks`,
  `record_requirements`, `read_requirements`, `update_requirement`;
- **assembly** — `declare_constraint`, `update_constraint`, `read_constraints`,
  `check_assembly`;
- **manufacturing and output** — `run_dfm`, `export_part`, `generate_drawing`,
  `generate_doc`;
- **registries and references** — `list_skills`, `load_skill`,
  `search_parts_store`, `instance_store_part`, `search_materials`,
  `list_references`, `read_reference`;
- **interaction and delegation** — `ask_user`, `answer_question`,
  `delegate_part_agent`, `get_delegation_status`, `cancel_delegation`.

Three behaviours are worth knowing before you wire this up.

**`ask_user` becomes an elicitation.** It maps to the MCP elicitation
capability, so the question reaches the human through the client's own UI. A
client that does not advertise elicitation gets the documented fallback instead:
structured content describing the pending question, plus the exact
`answer_question` call to make. Nothing hangs waiting for a capability the
client never claimed.

**Images come back as MCP image content.** `inspect_part` returns renders
inline, within the `schemas/bridge_limits.json` budgets, alongside the artifact
refs they came from — so the model sees the picture and can still name the build
it depicts.

**Mutating tools are idempotent.** The key derives from MCP session identity
plus the canonical JSON-RPC request id (with an optional
`_meta["hephaestus.dev/idempotency-key"]` override). A retried call after a
dropped connection replays rather than duplicating the edit.

## Troubleshooting

| Symptom | Cause |
|---|---|
| Client reports the server exited immediately | `heph` not on the launching process's `PATH`, or `--mcp` omitted (it is required, and the server says so on stderr and exits 2). |
| Every project tool errors with "no project is bound" | The session never called `open_project`. |
| Builds fail with `sandbox_unavailable` | No probed secure executor on this machine ([install.md](install.md)). Serve mode will not fall back to the unsafe executor, by design. |
| Builds fail with `unsafe_refused` | Something asked for the unsafe local executor under serve. There is no flag for this; it is a policy refusal. |
| Garbled protocol traffic on stdio | Something is writing to stdout. Under `--mcp` on stdio, stdout **is** the transport; every Hephaestus diagnostic goes to stderr. |
