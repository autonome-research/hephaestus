# Work on the sidecar

> **Verified against** `3af69da` on 2026-09-12.
> Resolution order and integrity rules read from
> `server/src/hephaestus/agent_bridge/sidecar.py`; the freshness guard from
> `server/src/hephaestus/testing/sidecar.py`; scripts from
> `agent/package.json` and `scripts/stage_sidecar.py`.

The sidecar is the TypeScript process that talks to model providers. It is
`agent/`, built with esbuild, and **staged** into `hephaestus-server` as package
data.

## The one thing to internalise

**Editing `agent/src/` changes nothing until you re-bundle and re-stage.** What
runs is the staged bundle, not your source tree. This is the most common way a
local run diverges from what you just wrote, and the symptom is usually remote —
a method-not-found on the wire rather than a syntax error where you typed.

## The loop

```console
$ cd agent
$ pnpm install --frozen-lockfile      # first time, or after a lockfile change
$ pnpm typecheck                      # tsc -p tsconfig.check.json
$ pnpm test                           # vitest
$ pnpm lint                           # eslint
$ pnpm run bundle                     # node scripts/bundle.mjs → agent/build/sidecar
$ cd .. && uv run python scripts/stage_sidecar.py
$ uv run python -m hephaestus.testing.sidecar    # record what it was built from
```

Run pnpm from **inside** `agent/`, never with `--dir`: corepack resolves
`packageManager` by walking up from the current directory, so `--dir` finds no
field at the repository root and uses whatever corepack has activated.

The last two lines are a pair, and skipping the second is what makes the
freshness guard inert. See [below](#the-freshness-guard).

## What staging does

`scripts/stage_sidecar.py` is the step between `pnpm run bundle` and `uv build`.
It:

1. copies the bundle into `server/src/hephaestus/agent_bridge/_sidecar/`;
2. distils the esbuild metafile into a small `AUDIT.json`;
3. writes the SHA-256 `MANIFEST.json` **the supervisor verifies before every
   spawn**.

`AUDIT.json` exists so the shipped wheel is self-describing. Walking a 14 MB
bundle for import edges at test time would be guesswork; the build knows the
module graph exactly, so it records the findings the release gate asks about and
the test asserts over facts rather than regexes.

## How a sidecar is resolved

Ordered, and **fail-closed at every step**. No branch ever degrades into "spawn
whatever is on `PATH`".

| Step | Source | Rule |
| --- | --- | --- |
| 1 | `$HEPHAESTUS_SIDECAR` (or an explicit argument) | a named override that does not resolve is an **error**, never a fallback |
| 2 | the sidecar packaged in this distribution | located with `importlib.resources` anchored on the *regular* package — never `__file__` arithmetic, never the `hephaestus` namespace package, whose `files()` is not usable on 3.11 |
| 3 | `<repo>/agent/build/sidecar` | only when step 2 found **nothing at all** |

**A packaged sidecar that exists but fails verification refuses.** It is never
"repaired" by silently reaching for the developer's tree — that is exactly how a
tampered release would go unnoticed on the one machine that could detect it.

### Integrity is bidirectional

Every manifest entry must be present with a matching SHA-256, **and** the tree
must contain no file the manifest does not list. A one-directional check would
let an attacker add a module that the bundle's chunk graph then imports.

## The freshness guard

`HEPHAESTUS_SKIP_SIDECAR_BUILD=1` makes sidecar-backed test lanes affordable by
reusing the staged bundle. It also removed the only thing coupling the staged
output to the source it was built from — **the integrity manifest hashes the
staged files, which is a tamper proof, never a freshness proof.**

So staging records a digest of the *inputs*, and the skip path compares it:

| State | Behaviour |
| --- | --- |
| digest matches | reuse the staged bundle |
| digest differs | **refuse** — the staged tree was built from other sources |
| no record at all | treated as *unknown*, warns exactly once, so nobody's tree breaks on upgrade |

CI stages by invoking `scripts/stage_sidecar.py`, which knows nothing about this
record, so the workflow calls `python -m hephaestus.testing.sidecar` immediately
afterwards. Without that step, every job setting `HEPHAESTUS_SKIP_SIDECAR_BUILD=1`
takes the *unknown* branch and the guard is inert exactly where it matters most.
`tests/stage7h/test_sidecar_toolchain.py` asserts the pairing.

## Skips are loud

`HEPHAESTUS_REQUIRE_SIDECAR=1` — set by every CI job that installs Node, and by
the bootstrap lane — turns "no toolchain" from a skip into a **named failure**, so
a regression that would once have quietly skipped twenty assertions fails by name.

The test helper also resolves pnpm the same way `scripts/bootstrap.sh` does,
rather than asking `shutil.which("pnpm")` — which answered "no sidecar" on exactly
the checkout the documentation tells a contributor to create.

## The source layout

```
agent/src/
  main.ts                the entry point
  framing.ts  rpc.ts     the wire — mirrors framing.py / protocol.py
  limits.ts              reads schemas/bridge_limits.json
  events.ts              event emission
  image-identity.ts
  session/               manager, runtime, live, history, context, credentials,
                         model-selection, profiles, retry, extension
  tools/                 proxy, invocation, preflight, clarify, registry,
                         schema.gen.ts (GENERATED)
  workflows/             cad_workflow, runner, jobstore
```

### Two files you must not hand-edit

- **`src/tools/schema.gen.ts`** is generated from
  `contract/src/hephaestus/contract/tools_decl.py`. Change the declaration and
  regenerate; a hand edit fails the drift test. See
  [add or change a tool](add-or-change-a-tool.md).
- **Any limit literal.** Read it from `schemas/bridge_limits.json` through
  `src/limits.ts`. A duplicated literal fails the census test, which checks both
  directions.

### Byte parity with Python

`encodeFrame` must produce **byte-for-byte identical output** to Python's
`encode_frame` for the same value, asserted by a cross-language golden fixture.
That relies on a canonical JSON serialization: recursively sorted object keys,
compact separators, raw (non-ASCII-escaped) UTF-8. If you touch serialization,
that fixture is the test that will tell you.

## Debugging the bridge

**Protocol stdout carries frames and nothing else.** Logs go to stderr. A stray
`console.log` on stdout corrupts the stream, and the symptom is a parse error on
the Python side rather than anything pointing at the line you added.

| Symptom | Likely cause |
| --- | --- |
| `session.model.get: method not found` | stale staged sidecar — re-bundle, re-stage, re-record |
| `frame_too_large` / `-32001` | a result exceeded 64 MiB; the decoder aborts mid-line without buffering it |
| `-32002` unsupported version | an `hv` mismatch — the wire fails closed |
| `handler_overloaded` | all 32 `py.*` workers busy; one call fails rather than the pipe stalling |
| `-32004` `PROCESS_DOWN` | the child exited; the recovery hook ran before any respawn |
| `runtime.configure has not run yet` | a spawn path that did not replay the configure payload |
| supervisor "durably dead" naming an attempt count | a crash loop exhausted 3 respawn attempts |

The supervisor kills the whole sidecar when a pending call passes its effective
deadline by 5 s, **after** crediting the time Python itself made the child wait.
See [the bridge protocol](../04-reference/bridge-protocol.md).

## Running the bridge suites

```console
$ uv run pytest server/tests -q -k bridge
$ uv run pytest tests/stage2 -q
$ HEPHAESTUS_REQUIRE_SIDECAR=1 uv run pytest tests/stage8a -q
```

Wrap long runs in `keepawake`.

## Related

- [The bridge protocol](../04-reference/bridge-protocol.md).
- [Add or change a tool](add-or-change-a-tool.md).
- [Deployment view](../05-architecture/deployment-view.md) — why the sidecar ships where it does.
