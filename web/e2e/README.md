<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# `web/e2e` — the Gate G4 Playwright suite

`pnpm --dir web test:e2e` is the literal Gate G4 command (`mission_plan.md`
Stage 4). It runs Playwright against a **real** `heph serve --web` on the public
clean-room fixture `corpus/public_fixtures/workspace/`.

```
pnpm --dir web install --frozen-lockfile
pnpm --dir web exec playwright install chromium   # once per machine
pnpm --dir web build                              # `serve --web` serves web/dist
pnpm --dir web test:e2e
```

`pnpm --dir web build` is a real prerequisite, not a convenience: since
`http/serve.py::with_bundle`, the serving process serves the built bundle at
`/` and the API under `/api/`, so the browser loads the app from the same origin
that answers its requests — the topology a wheel-installed operator gets. With
no `dist/`, `heph serve --web` says so on stderr and serves the API alone.

## What stands the world up

| File | What it does |
|---|---|
| `global-setup.ts` | spawns the harness and waits for its handshake; every failure is fatal and named |
| `harness/serve_fixture.py` | materializes the fixture, builds `tread` + `riser`, starts the scripted provider, starts **`heph serve --web`**, reopens the committed transcript's two sessions, then stays alive |
| `harness/world.ts` | reads the handshake; `api()`, `apiBytes()`, `route()`, `open()`, `uuid7()` |
| `global-teardown.ts` | SIGTERMs the harness, which unwinds the server (and its `serve.json`) |

The scripted model runs **in the harness process**, and `.heph/providers.json`
points the served process's sidecar at it. The workspace process is the shipped
one; a fake model inside it would make the gate a test of a modified server.

## Clause map

| Clause | Where | Note |
|---|---|---|
| G4.0 | `playwright.config.ts` | one browser, no retries, one worker, no `--pass-with-no-tests` |
| G4.1 | `corpus/public_fixtures/workspace/` | see its `README.md` for the §14 requirement ledger |
| G4.2 | `dom.spec.ts` | tree rows == `geometry_count` **over HTTP**; the three-number invariant is `tests/stage4` |
| G4.3 | `dom.spec.ts` | DOM ↔ projection **set equality**; projection ↔ `part.*` is `tests/stage4` |
| G4.4 | `dom.spec.ts` | badges vs a subprocess `heph check --json`, expectations derived from the subprocess's own document |
| G4.5 | `viewport.spec.ts` | before/after delta inside a decoded solid-pass mask, via `helpers/maskDelta.ts` |
| G4.6 | `viewport.spec.ts` | pairwise centroid distances out of `window.__hephaestus_viewport__` |
| G4.7 | `viewport.spec.ts` | the plate's **server** bytes against the committed golden |
| G4.8 | `stream.spec.ts` | `heph agent` from the command line, streaming into an already-attached panel |
| G4.9 | `stream.spec.ts` | `data-history-pages` > 1 over the committed >250-event transcript |
| G4.10 | `stream.spec.ts` | nested tab with `data-thread-kind="quick_edit"`, child transcript reopened |
| G4.11 | `stream.spec.ts` | every archived `(session_id, ordinal)` id in the DOM exactly once |
| G4.12 | `harness/archive.ts` | named screenshots attached; **never** compared to anything |
| G4.D | `stream.spec.ts` | containment + groundedness over `JSON.parse(payload.text)`, `R` read from `schemas/tools/*` |
| G4.X | `dom.spec.ts` | the DFM action's findings, with topology descriptors |

## Three things that are easy to get wrong here

**The token.** `open()` loads `#t=<token>` first and then navigates to the §4.5
route. `#t=` and `explode_t`'s `t=` are the same letter in the same fragment;
`api/token.ts` discriminates on the leading slash, and `dom.spec.ts` asserts the
token does not survive in the URL.

**Idempotency keys are UUIDv7.** §2.5's ladder refuses anything else by name, so
`crypto.randomUUID()` (v4) tests the refusal rather than the mutation. Use
`uuid7()` from `harness/world.ts`.

**`heph` verbs run under the handshake's `python`.** The materialized fixture is
outside this repository's uv workspace, so `uv run` from inside it finds no
`hephaestus`. `world().python` is the interpreter the harness itself is running.

## What is renderer-pinned, and therefore deferred in CI

G4.7 compares against a committed golden, and a golden is valid only for its
`(container image, renderer version)` pair (`verification.md` Tier 2). §14 says
the browser gate runs "inside the same pinned CI container image as
`tests/render`" — and `ci.yml`'s scope note records that this image does not
exist yet, which is why `tests/render` is excluded from every-PR CI today. This
suite and `tests/stage4/test_g4_section_golden.py` move when it lands. Both
**fail by name** on an unmatched renderer rather than skipping, so the deferral
can never quietly become a pass.

## `helpers/` — harness code, never app code

Nothing under `web/src` imports it and `pnpm build` never sees it. §5.4 puts
G4.5's whole mechanism in the harness ("All three steps run in the **test
harness**, never in the workspace… the app ships no pixel reader").

| Module | What it is |
|---|---|
| `helpers/png.ts` | an 8-bit truecolour PNG decoder over `node:zlib`; refuses 16-bit/indexed/greyscale/interlaced **by name** |
| `helpers/maskDelta.ts` | `maskForPalette`, the `inside`/`band`/`control` partition at dilation radius 2, and `assertVisibilityDelta` (inside ≥ 0.10, control ≤ 0.01) |

Both are unit-tested from `../test/pngDecode.test.ts` and
`../test/maskDelta.test.ts`, against files a separate encoder wrote.

**Sizing the canvas to the pass.** `inspect_part` exposes no width/height, so
the pass is always 960×720 and the *canvas* is what moves: `viewport.spec.ts`
lifts the viewport to a fixed 960×720 box at the origin with
`pointer-events: none`, so the frame is whole and the Results toggle underneath
stays genuinely clickable. Take the frames with explode collapsed — at `t = 0`
the viewport frames the plain scene bbox, which is the extent the `mask` channel
frames, so the two cameras agree by construction.

## Selectors this suite reads

`[data-tree-row]`, `[data-geometry-index]`, `[data-geometry-label]`,
`[data-source]`+`[data-value]`, `[data-panel]`, `[data-inspector-panel]`,
`[data-field]`, `[data-check]`+`[data-badge]`, `[data-dfm-finding]`,
`[data-dfm-descriptor]`, `[data-visibility-toggle]`, `[data-testid="viewport"]`
with `data-glb-state` / `data-artifact-ref` / `data-section-state`,
`[data-viewport-canvas]`, `[data-explode-t]`, `[data-section-control]` with
`data-section-plane`, `[data-section-plate]`+`data-plate-ref`,
`[data-testid="stream-panel"|"transcript"]`, `[data-history-state]`,
`[data-history-pages]`, `[data-stream-state]`, `[data-session-tab]` with
`data-thread-depth` / `data-thread-kind`, `[data-event-id]`+`data-surface`,
`[data-tool-name]`+`data-status`+`data-tool-call-id`, `[data-field-state]`,
`[data-image-state]`+`data-mime-type`, `[data-terminal-state]`,
`[data-testid="no-token"]`.

G4.6 reads the scene graph rather than the DOM, through
`window.__hephaestus_viewport__.solids()` (`../src/viewport/testHook.ts`). The
pairwise **subtraction** is the harness's, not the app's.
