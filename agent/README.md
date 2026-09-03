# `@hephaestus/agent`

The private TypeScript sidecar used by `heph agent` and agent-enabled serving.
It owns Pi sessions, generated CAD-tool proxies, bridge framing, bounded
thread-phase workflows, and event normalization. It does not implement geometry
or access project files directly; those operations cross the Python bridge.

## Development

From the repository root:

```console
$ pnpm --dir agent install --frozen-lockfile
$ pnpm --dir agent typecheck
$ pnpm --dir agent lint
$ pnpm --dir agent test
$ pnpm --dir agent bundle
```

Use [`../docs/install.md`](../docs/install.md) for runtime prerequisites and
[`../PACKAGING.md`](../PACKAGING.md) for staging the bundled sidecar. The root
architecture, tool schema, and mission plan are authoritative; [`DESIGN.md`](DESIGN.md)
is retained as the historical Stage 2 implementation contract.
