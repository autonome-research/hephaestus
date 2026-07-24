"""Spike B server: FastMCP server with an echo tool and an elicitation-using ask tool.

Run over stdio (default) or streamable HTTP:
    uv run python echo_server.py            # stdio
    uv run python echo_server.py --http     # streamable HTTP on 127.0.0.1:8765
"""

import sys
from dataclasses import dataclass

from fastmcp import Context, FastMCP

mcp = FastMCP("elicitation-spike")


@mcp.tool
def echo(text: str) -> str:
    """Echo the input text back."""
    return f"echo:{text}"


@dataclass
class Answer:
    """Structured answer schema requested from the client mid-call."""

    name: str
    quantity: int


@mcp.tool
async def ask(topic: str, ctx: Context) -> str:
    """Ask the client (via MCP elicitation) for a structured Answer about `topic`,
    then round-trip the answer back inside the tool result."""
    result = await ctx.elicit(
        f"Please provide a name and quantity for: {topic}",
        response_type=Answer,
    )
    if result.action == "accept":
        return f"answered:{topic}:name={result.data.name}:quantity={result.data.quantity}"
    return f"not-answered:{result.action}"


if __name__ == "__main__":
    if "--http" in sys.argv:
        mcp.run(transport="http", host="127.0.0.1", port=8765)
    else:
        mcp.run()  # stdio
