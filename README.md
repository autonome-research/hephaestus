<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# Hephaestus

Hephaestus is open-source parametric CAD. You write
[build123d](https://github.com/gumyr/build123d) parts; `heph` builds, checks,
and renders them. The web UI is optional operator chrome. An Autonome Research
project, licensed Apache-2.0.

## Install

Not on PyPI. There is no GitHub Release.

```console
$ git clone https://github.com/autonome-research/hephaestus && cd hephaestus
$ uv sync --dev
$ uv run heph --version
```

What each capability actually needs (sandbox, macOS, agent sidecar):
[docs/install.md](docs/install.md).

## Operator UI

Optional. Build the client from this clone, then run `heph serve --web` inside
a project.

```console
$ pnpm --dir web install --frozen-lockfile
$ pnpm --dir web build
$ uv run heph serve --web
```

## Headless / agents

Coding agents use `heph` from a clone. You do not need the browser or MCP.

After `uv sync --dev`, put the clone's `.venv/bin` on `PATH` (or call that
`heph` by path):

```console
$ heph init /tmp/gadget && cd /tmp/gadget
$ heph part create spacer --template blank --json
$ heph script write spacer --file spacer.py --expected-hash sha256:… --json
$ heph params spacer --json
$ heph prompt set --file request.txt
$ heph build spacer
$ heph part show spacer --json
$ heph lint parts/spacer.py --request .heph/request.txt
$ heph check --json
$ heph render spacer
```

`heph init` writes a small project that builds with nothing edited. Create and
write are `create_part` / `write_part` (CAS: `--expected-hash` is the
`content_hash` from create/show; an existing name is `already_exists`).
`heph prompt` stores request text at `.heph/request.txt` — not a hosted chat.
Full verb list: [docs/cli.md](docs/cli.md). MCP is optional:
[docs/mcp.md](docs/mcp.md).

Beyond part authoring, the engine ships a pinned component registry
(`heph registry`), STEP/mesh import and scan comparison (`heph import`,
`heph scan`), joints and motion checks (`heph joints`, `heph motion`),
a propose-only pose solver (`heph solve`), 2D laser/waterjet cut-file
emission (`heph cam emit`), and a scored agent bench — all in
[docs/cli.md](docs/cli.md).

## More

- [docs/install.md](docs/install.md) — capability caveats
- [docs/cli.md](docs/cli.md) — every `heph` verb
- [docs/mcp.md](docs/mcp.md) — optional MCP client setup
- [docs/conventions.md](docs/conventions.md) — project layout and part scripts
- [docs/README.md](docs/README.md) — complete documentation and specification-status index
- [CONTRIBUTING.md](CONTRIBUTING.md) — checks, headers, clean-room boundary
