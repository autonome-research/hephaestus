# `hephaestus-core`

The Python CAD engine behind the `heph` CLI. It owns project loading, sandboxed
part-script execution, geometry services, checks, rendering, registries, and
artifact publication. It must remain usable without the server, browser, Node,
or a network connection.

## Development

From the repository root:

```console
$ uv sync --dev
$ uv run pytest core/tests
$ uv run pyright core
$ uv run ruff check core
```

The public behavior is defined by [`script_contract.md`](../script_contract.md),
[`tool_schema.md`](../tool_schema.md), and the capability specifications indexed
in [`docs/README.md`](../docs/README.md). Internal boundaries and historical
implementation detail are recorded in [`DESIGN.md`](DESIGN.md).
