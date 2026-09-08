# `@hephaestus/agent`

The private TypeScript sidecar used by `heph agent` and agent-enabled serving.
It owns Pi sessions, generated CAD-tool proxies, bridge framing, bounded
thread-phase workflows, and event normalization. It does not implement geometry
or access project files directly; those operations cross the Python bridge.

## Development

```console
$ cd agent
$ pnpm install --frozen-lockfile
$ pnpm typecheck
$ pnpm lint
$ pnpm test
$ pnpm bundle
```

Run pnpm from **inside** the package directory, never with `--dir`: the flag moves
the install but not the version resolution, because corepack picks the
`packageManager` field by walking up from the current directory and there is
deliberately no root manifest (`CONTRIBUTING.md`, "pnpm: the pin, and where its
settings live"; [`../docs/install.md`](../docs/install.md)).

Use [`../docs/install.md`](../docs/install.md) for runtime prerequisites and
[`../PACKAGING.md`](../PACKAGING.md) for staging the bundled sidecar. The root
architecture, tool schema, and mission plan are authoritative; [`DESIGN.md`](DESIGN.md)
is retained as the historical Stage 2 implementation contract.
