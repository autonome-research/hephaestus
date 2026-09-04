<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# Install

Clone this repository. Hephaestus is not on PyPI, and there is no GitHub
Release. The import package is `hephaestus`; the CLI binary is `heph`.

## One command

`scripts/bootstrap.sh` takes a fresh clone to a fully built checkout: the
Python workspace, the bundled agent sidecar, and the operator web client. It is
idempotent, it works from any directory and through a symlink, and it invents
no build path — every step is a command this page also documents by hand.

```console
$ git clone https://github.com/autonome-research/hephaestus && cd hephaestus
$ ./scripts/bootstrap.sh
```

| Flag | Effect |
|---|---|
| `--check` | Check the prerequisites, print what is missing, and stop. Changes nothing; exits 1 if anything is missing. |
| `--no-web` | Skip the optional operator web client — four steps instead of six. |
| `-h`, `--help` | Usage and the step list. |

### What it checks first

Every missing prerequisite is reported at once, each with the command that
fixes it, so a machine short two tools costs one round trip rather than two:

- `git`.
- `uv` — `curl -LsSf https://astral.sh/uv/install.sh | sh`.
- a Python 3.11–3.14 that uv can use, probed read-only with
  `uv python find '>=3.11,<3.15'` — `uv python install 3.13` if there is none.
- Node ≥ 22.19 on `PATH` — from nodejs.org, or via mise/nvm/fnm.
- pnpm, or something that can fetch it (below).

bubblewrap is a **warning**, not a failure. The build succeeds without it and
then `heph build` refuses to run part scripts (`sandbox_unavailable`); see
[what each capability needs](#what-each-capability-needs).

### How it finds pnpm

The choice is printed on every run, because which one you got explains most of
what happens next. Four routes, in this order:

1. a `pnpm` on `PATH` that is **corepack's shim** — detected by *reading* the
   file, never by running it, since `pnpm --version` under corepack downloads a
   package manager before it can answer and `--check` must change nothing;
2. a `pnpm` on `PATH` **at or above the pin's major** — it re-executes the
   pinned version itself, per package, from `packageManager` (verified for
   10.18.3 and for 11.25.0 — the install reports `using pnpm v<pin>`);
3. `corepack pnpm`;
4. `npx --yes pnpm@<pin>`, downloaded on demand.

Only a `PATH` pnpm **older** than the pin's major is passed over, with a warning
naming what was used instead. It is passed over because it cannot reach the pin
and cannot build this tree as itself: pnpm 9 does not even parse this
repository's `pnpm-workspace.yaml` ("packages field missing or empty"). The pin
is read, never copied: `agent/package.json`'s `packageManager` field first, then
`PNPM_VERSION` in the CI workflow. `agent/package.json` and `web/package.json`
both carry that field, and a pnpm invoked **directly** honours it, so routes 2
and 4 converge on the pinned version rather than drifting.

The two corepack lanes — the shim at route 1 and `corepack pnpm` at route 3 —
carry one caveat, and it is worth knowing why. Corepack resolves
`packageManager` by walking up from the current directory — `--dir` does not
move that search — and this repository has no root `package.json`, so
`corepack pnpm --dir agent …` run from the clone root finds no field and uses
whatever corepack has activated. pnpm does not rescue it either: its self-switch
is disabled when corepack invoked it, and pnpm 11 fails the command outright
("pnpm does not switch versions when running under corepack") instead. That is
why every pnpm step below is run **from inside** `agent/` or `web/` rather than
with `--dir`: from there all four routes converge on the pin. If you would
rather use `--dir`, run `corepack prepare pnpm@<pin> --activate` once first.

The script exports `CI=true` and `COREPACK_ENABLE_DOWNLOAD_PROMPT=0` before any
pnpm call, so nothing prompts.

### What it does

Six steps, each announced with the literal command line before it runs, failing
fast and naming the step that failed. By hand it is:

```console
$ uv sync --dev                                # the Python workspace
$ (cd agent && pnpm install --frozen-lockfile)
$ (cd agent && pnpm run bundle)                # -> agent/build/sidecar
$ uv run python scripts/stage_sidecar.py       # stage it into hephaestus-server
$ (cd web && pnpm install --frozen-lockfile)   # both skipped by --no-web
$ (cd web && pnpm build)                       # -> web/dist
```

`uv sync --dev` is an editable workspace install and is the whole install for
the engine verbs; steps 2–4 add the agent sidecar, 5–6 the operator UI.

Bootstrap builds; it does not verify. It runs no tests and installs no browser,
so Gate G4 — `pnpm test:e2e` from `web/` — still needs
`pnpm exec playwright install chromium` there first.

## Running `heph` from anywhere

`uv run heph` resolves only from inside the clone; from outside it fails to
spawn `heph` at all. Three things work from any directory, and bootstrap prints
all three when it finishes:

```console
$ /abs/path/to/hephaestus/.venv/bin/heph --version
$ uv run --directory /abs/path/to/hephaestus heph --version
$ ln -s /abs/path/to/hephaestus/scripts/heph ~/bin/heph    # then just: heph
```

`scripts/heph` is a small launcher: it resolves the clone from its own
location, following symlinks, and `exec`s `.venv/bin/heph`. That is what makes
it safe to symlink onto `PATH`, and it names `scripts/bootstrap.sh` if the venv
binary is not there yet rather than failing obscurely. Putting `.venv/bin`
itself on `PATH` also works.

## `heph` runs against a project, not against the clone

A project is a directory holding `hephaestus.toml` plus `globals.py`, `parts/`
and `checks/`. The clone is not one, and `heph serve --web` in the clone is the
most common first mistake. Create one and work inside it:

```console
$ heph init ~/designs/bracket
$ cd ~/designs/bracket && heph serve --web
```

Anywhere else, the refusal says so by name rather than guessing:

```
heph: error (validation_error): no hephaestus.toml found at or above /home/you/hephaestus:
a Hephaestus project is a directory holding hephaestus.toml (plus globals.py, parts/ and
checks/). Create one with `heph init DIR`, then run from inside it (or pass `--project DIR`
to `heph agent` / `heph serve --web`)
```

`heph serve --web --project DIR` and `heph agent --project DIR` start that
search somewhere other than the working directory, so the workspace can be
served without a `cd` — see [cli.md](cli.md#heph-serve---web). The built web
bundle is found relative to the installation, not to the project, so a source
checkout serves its own `web/dist` whatever `--project` names.

## What each capability needs

- **Engine verbs** (`heph init`, `part`, `script`, `params`, `prompt`,
  `build`, `check`, `lint`, `render`, and the rest of the CAD CLI) — any
  Python 3.11–3.14. No Node, no browser, no network. `uv sync --dev`, or
  `scripts/bootstrap.sh --check` first if you would rather be told what is
  missing than find out per-step.
- **Sandboxed script execution** — Linux x86_64 with bubblewrap (≥ 0.11).
  Part scripts run in a probed OS sandbox. Anywhere the probe fails, `heph
  build` exits non-zero (`sandbox_unavailable`); it never silently downgrades.
  `heph build --unsafe-local-executor` is a local debug hatch with no OS
  sandbox. It is refused for registry content and under `heph serve`.
- **macOS** — no script execution in v0.1. `heph lint`, schema/contract reads,
  and `heph --version` work. A capability-tested OCI backend is post-v0.1.
- **Agent sidecar** (`heph agent`, agent-backed serve) — Node ≥ 22.19 on
  `PATH`, after you build the sidecar in this checkout:

  ```console
  $ (cd agent && pnpm install --frozen-lockfile)
  $ (cd agent && pnpm run bundle)
  $ uv run python scripts/stage_sidecar.py
  ```

  It also needs a provider config at `<project>/.heph/providers.json` —
  [cli.md](cli.md#heph-agent) works one through for an API key (`anthropic`)
  and one for an existing Codex/Pi login (`pi_native`).
- **Operator UI** — optional. `pnpm install --frozen-lockfile` then
  `pnpm build`, both run from `web/`, then `heph serve --web` from a project.
  With no bundle built the server says so and serves the API alone.

Wheel and sidecar packaging (integrity, `uv build`, why the sidecar is
bundled): [PACKAGING.md](../PACKAGING.md). MCP is optional:
[mcp.md](mcp.md).

## Verify

```console
$ uv run heph --version
heph 0.1.0

$ uv run heph --help
$ uv run heph init /tmp/gadget
```

Then, in the project — `uv run heph` will not work from here, so use the venv
binary (or whichever of the three forms above you set up):

```console
$ cd /tmp/gadget
$ /abs/path/to/hephaestus/.venv/bin/heph check --json    # engine path; no Node
$ /abs/path/to/hephaestus/.venv/bin/heph build example
```

`heph agent` needs the sidecar built and staged first — `scripts/bootstrap.sh`
does both, or steps 2–4 above by hand.
