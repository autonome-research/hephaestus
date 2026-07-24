# Spike B — FastMCP elicitation (Stage S, deliverable b)

**Question:** Does MCP elicitation (`ctx.elicit`) work end-to-end — a server
requesting a structured answer from a scripted client mid-tool-call — over
both stdio and streamable HTTP?

**Answer: YES on both transports.** No fallback (structured content +
follow-up call) is needed; `tool_schema.md` §ask_user can map to MCP
elicitation as planned.

## Versions (exact, from `out/versions.log`)

| Component | Version |
|---|---|
| Python | 3.13.12 (uv-managed CPython) |
| fastmcp | 3.4.4 (pinned `==` in pyproject.toml) |
| mcp (official SDK) | 1.28.1 (pinned `==`) |
| pydantic | 2.13.4 |
| uvicorn | 0.51.0 |
| httpx | 0.28.1 |
| MCP protocol negotiated | 2025-11-25 |

## What was exercised

- `echo_server.py`: FastMCP server exposing `echo(text)` and
  `ask(topic, ctx)`. `ask` calls `await ctx.elicit(message,
  response_type=Answer)` where `Answer` is a dataclass `{name: str,
  quantity: int}`, and embeds the accepted answer in its tool result.
- `scripted_client.py`: official `mcp` SDK client (`ClientSession` with an
  `elicitation_callback`), no FastMCP client code. Connects via
  `mcp.client.stdio.stdio_client` and
  `mcp.client.streamable_http.streamablehttp_client`
  (`http://127.0.0.1:8765/mcp`). Calls `echo`, asserts the result; calls
  `ask`, answers the mid-call `elicitation/create` request programmatically
  with `ElicitResult(action="accept", content={"name": "widget",
  "quantity": 7})`, and asserts:
  - the elicitation message arrived verbatim;
  - `requestedSchema.properties` is exactly `{name, quantity}` (structured
    schema round-trips);
  - the tool result is exactly `answered:bracket:name=widget:quantity=7`
    (the programmatic answer round-trips into the tool result).

## Results

| Transport | Elicitation round-trip | `ask` call latency | Exit code |
|---|---|---|---|
| stdio | PASS | ~0.005 s | 0 |
| streamable HTTP | PASS | ~0.008 s | 0 |

Two consecutive full runs of `./run_all.sh` exited 0
(`out/stdio.log`, `out/http.log`, `out/run2_summary.log`).

## Reproduce

```sh
cd spikes/mcp_elicitation
uv sync
./run_all.sh          # logs land in out/ (gitignored)
```

## Notes / caveats

- The client rejects/declines path was not exercised (only `action="accept"`);
  Stage 3 should handle `decline`/`cancel` — the server already branches on
  `result.action`.
- FastMCP 3.x elicitation `response_type` supports dataclasses, option lists,
  and scalar types; only the dataclass (structured object) case was proven
  here, which is the shape `ask_user` needs.
- This spike is a standalone uv project, deliberately *not* a member of the
  root uv workspace.
