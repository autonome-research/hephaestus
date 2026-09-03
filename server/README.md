# `hephaestus-server`

The Python transport and runtime-integration package. It provides the MCP and
loopback HTTP/WebSocket surfaces, supervises the packaged TypeScript sidecar,
and translates requests into core operations. Geometry and engineering facts
remain owned by `hephaestus-core`.

The server uses FastMCP, Starlette, uvicorn, and websockets; it does not add a
separate FastAPI application.

## Development

From the repository root:

```console
$ uv sync --dev
$ uv run pytest server/tests
$ uv run pyright server
$ uv run ruff check server
```

See [`architecture.md`](../architecture.md) for boundaries,
[`docs/mcp.md`](../docs/mcp.md) for MCP setup, and
[`INTERFACE.md`](../INTERFACE.md) for the workspace API contract and status.
