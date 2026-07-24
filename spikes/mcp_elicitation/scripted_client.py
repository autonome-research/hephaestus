"""Spike B scripted client: official `mcp` SDK client that connects over stdio
and streamable HTTP, calls `echo`, then calls `ask` and answers the server's
mid-call elicitation programmatically, asserting the round-tripped answer.

Usage:
    uv run python scripted_client.py stdio
    uv run python scripted_client.py http http://127.0.0.1:8765/mcp
"""

import asyncio
import pathlib
import sys
import time
from typing import Any

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

HERE = pathlib.Path(__file__).resolve().parent
ANSWER = {"name": "widget", "quantity": 7}

# Captured details of the elicitation request, for assertions and the log.
seen: dict[str, Any] = {}


async def elicitation_callback(
    context: Any, params: types.ElicitRequestParams
) -> types.ElicitResult:
    """Answer the server's elicitation programmatically."""
    seen["message"] = params.message
    schema = getattr(params, "requestedSchema", None)
    if schema is not None and not isinstance(schema, dict):
        schema = schema.model_dump()
    seen["schema"] = schema
    seen["schema_props"] = sorted(schema["properties"].keys()) if schema else None
    print(f"[client] elicitation received: message={params.message!r}", flush=True)
    print(f"[client] requestedSchema properties: {seen['schema_props']}", flush=True)
    return types.ElicitResult(action="accept", content=ANSWER)


async def exercise(session: ClientSession, transport: str) -> None:
    t0 = time.monotonic()
    init = await session.initialize()
    print(
        f"[client:{transport}] initialized against server "
        f"{init.serverInfo.name!r} (protocol {init.protocolVersion}) "
        f"in {time.monotonic() - t0:.3f}s",
        flush=True,
    )

    # 1. echo
    r = await session.call_tool("echo", {"text": "hello-spike"})
    assert not r.isError, r
    echo_text = r.content[0].text  # type: ignore[union-attr]
    assert echo_text == "echo:hello-spike", f"unexpected echo result: {echo_text!r}"
    print(f"[client:{transport}] echo OK: {echo_text!r}", flush=True)

    # 2. ask -> server elicits mid-call -> callback answers -> tool result
    seen.clear()
    t1 = time.monotonic()
    r2 = await session.call_tool("ask", {"topic": "bracket"})
    dt = time.monotonic() - t1
    assert not r2.isError, r2
    ask_text = r2.content[0].text  # type: ignore[union-attr]
    print(f"[client:{transport}] ask result ({dt:.3f}s): {ask_text!r}", flush=True)

    # The elicitation must actually have happened, with the structured schema.
    assert seen.get("message") == "Please provide a name and quantity for: bracket", seen
    assert seen.get("schema_props") == ["name", "quantity"], seen
    # The programmatic answer must round-trip into the tool result.
    assert ask_text == "answered:bracket:name=widget:quantity=7", ask_text
    print(f"[client:{transport}] PASS: elicitation round-trip verified", flush=True)


async def run_stdio() -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(HERE / "echo_server.py")],
        cwd=str(HERE),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(
            read, write, elicitation_callback=elicitation_callback
        ) as session:
            await exercise(session, "stdio")


async def run_http(url: str) -> None:
    async with streamablehttp_client(url) as (read, write, _get_session_id):
        async with ClientSession(
            read, write, elicitation_callback=elicitation_callback
        ) as session:
            await exercise(session, "http")


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "stdio"
    if mode == "stdio":
        asyncio.run(run_stdio())
    elif mode == "http":
        url = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8765/mcp"
        asyncio.run(run_http(url))
    else:
        print(f"unknown mode: {mode}", file=sys.stderr)
        return 2
    print(f"[client:{mode}] ALL ASSERTIONS PASSED", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
