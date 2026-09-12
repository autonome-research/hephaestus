# Install and run

> **Verified against** `49a90c6` on 2026-09-12.
> Bootstrap behaviour read from `scripts/bootstrap.sh`; prerequisite versions
> from `pyproject.toml`, `agent/package.json`, `web/package.json`; `heph
> --version` and `heph init` run.

`docs/install.md` in this repository is the authoritative install page — it
covers every pnpm resolution route, every corepack caveat, and what each
capability needs. This page is the short path and the verification steps.

## Prerequisites

| Tool | Version | Needed for |
| --- | --- | --- |
| `git` | any | cloning |
| `uv` | any recent | the Python workspace |
| Python | 3.11–3.14 | everything |
| Node | ≥ 22.19 | the agent sidecar |
| pnpm | 10.34.5 (pinned) | building the sidecar and the web client |
| `bwrap` | any | secure builds — **a warning, not a failure, at install time** |

Without bubblewrap the install succeeds and `heph build` then refuses to run part
scripts with `sandbox_denied`. That is the design; see
[ADR-005](../05-architecture/decisions.md#adr-005-no-silent-fallback-to-unsandboxed-execution).

## One command

```console
$ git clone https://github.com/autonome-research/hephaestus && cd hephaestus
$ ./scripts/bootstrap.sh
```

It is idempotent, works from any directory and through a symlink, and invents no
build path — every step is a command `docs/install.md` also documents by hand.

| Flag | Effect |
| --- | --- |
| `--check` | report prerequisites and stop; changes nothing, exits 1 if any is missing |
| `--no-web` | skip the operator web client — four steps instead of six |
| `-h`, `--help` | usage and the step list |

**Every missing prerequisite is reported at once**, each with the command that
fixes it, so a machine short two tools costs one round trip rather than two.

`--check` runs in CI, which is what keeps this path from rotting.

## Verify the install

Four checks, in increasing depth. Run them in order; each one tells you something
the previous one could not.

### 1. The CLI answers

```console
$ uv run heph --version
heph 0.1.0
```

This also proves the fast path: registering the 25 verbs pulls no heavy module.

### 2. A project scaffolds

```console
$ uv run heph init /tmp/verify && cd /tmp/verify
initialized Hephaestus project 'verify' at /tmp/verify
  hephaestus.toml
  globals.py
  parts/example.py
  checks/project.py
  .gitignore
```

### 3. A part builds — this is the real test

```console
$ uv run heph build example
example: ok (current) artifact=artifact:build:sha256:d266f257c390143eca85ca60eae63829a02cc0d3a3360daa3668e118132b69a5
```

That hash is **reproducible**: a correct install of the pinned toolchain produces
exactly it for the scaffolded part. A different hash means a different geometry
kernel or a different build environment, and is worth investigating before you
trust anything else.

If you get this instead, bubblewrap is missing or not usable:

```console
$ uv run heph build example --json
{"code": "sandbox_denied", "message": "sandbox_unavailable: secure sandbox probe failed: bwrap not on PATH", "status": "refused"}
```

The probe **runs** bubblewrap and performs live escape probes; it never trusts a
version string. A failing probe is re-run every time, so installing bubblewrap
later is picked up without clearing anything.

### 4. Checks and renders work

```console
$ uv run heph check --json
{"scope": "project", "project": "verify", "check_set_generation": 0, …}

$ uv run heph render example
example: rendered 2 image(s) -> render
  iso [rgb] render/example_iso_rgb.png
  +X  [rgb] render/example_pX_rgb.png
  source_artifact_ref: artifact:build:sha256:d266f257…
```

If rendering fails on a machine with an unusual GPU setup, `HEPH_EGL_DEVICE`
overrides the device chosen.

## Run the browser workspace

```console
$ uv run heph serve --web --project ~/designs/bracket
```

One line on stdout carries the entry URL with the workspace token in the
**fragment**. Open it; the app moves the token to `sessionStorage` and rewrites
the URL immediately.

The token is minted per serve into `<project>/.heph/serve.token` (mode `0600`),
and `<project>/.heph/serve.json` is the discovery record other verbs read.

Without a token the app renders one non-interactive panel explaining how to get
one. It never prompts for credentials, because there are none to prompt for.

## Run the MCP server

```console
$ uv run heph serve --mcp                       # stdio
$ uv run heph serve --mcp --http 127.0.0.1:8765 # streamable HTTP
```

`--mcp` and `--web` in one process are refused by name, as is `--project` without
`--web`.

Neither serve mode has an unsafe-executor opt-in. Serve is the mode an operator
exposes to a client.

## Run an agent session

You need a provider attached first. The `heph agent` verb is registered only when
the server package imports; if it is installed but its dependency chain is
broken, the verb **stays in `heph --help`** and refuses by name, telling you the
import that failed rather than telling you to install something that is already
there.

Agent sessions need the staged Node sidecar. If you change anything under
`agent/`, see [work on the sidecar](work-on-the-sidecar.md) — the staged bundle
is what runs, not your source tree.

## Common problems

| Symptom | Cause | Fix |
| --- | --- | --- |
| `sandbox_denied` on every build | no usable bubblewrap | install `bubblewrap`; nothing to clear afterwards |
| `session.model.get: method not found` | stale staged sidecar | re-bundle and re-stage; see [work on the sidecar](work-on-the-sidecar.md) |
| a verb missing from `heph --help` | its package is not installed | install it — `argparse` reports `invalid choice` |
| a verb present but refusing by name | installed, but a transitive import is broken | the refusal names the import |
| pnpm builds the wrong version | corepack resolves `packageManager` by walking up from the current directory | run pnpm from **inside** `agent/` or `web/`, never with `--dir`; `docs/install.md` has the full matrix |
| a stage-13C determinism test times out | the machine is on battery and the CPU is throttled | plug in, or give the suite its own solve budget — see [known open issues](../06-operations/known-open-issues.md) |

## Related

- [Your first part](../02-tutorial/your-first-part.md) — the guided version of the checks above.
- [Run the tests](run-the-tests.md).
- [Limits and configuration](../04-reference/limits-and-configuration.md) — every environment variable.
