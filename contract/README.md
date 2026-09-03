# `hephaestus-contract`

The dependency-light source of truth for the public tool surface. It contains
typed declarations and generators used to keep the committed JSON Schemas,
TypeScript TypeBox definitions, MCP declarations, and documentation aligned.
It contains no CAD implementation.

## Development

From the repository root:

```console
$ uv sync --dev
$ uv run pytest contract/tests
$ uv run ruff check contract
```

Contract changes must follow [`tool_schema.md`](../tool_schema.md) and clear the
cross-language drift checks described in [`CONTRIBUTING.md`](../CONTRIBUTING.md).
