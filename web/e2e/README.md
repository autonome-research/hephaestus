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
| `harness/no_agent_serve.py` | a **second** `heph serve --web` with no `providers.json`, for §7A.12 case 6. Started and stopped by `composer.spec.ts` itself, because `agent_unavailable` is a property of a differently configured serve rather than of a different page |
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
| G4.9 | `stream.spec.ts` | `data-history-pages` > 1 on the panel root over the committed >250-event transcript, with §8(b)'s negative half beside it: at the latest page the count is an attribute and no counter row is drawn |
| G4.10 | `stream.spec.ts` | nested tab with `data-thread-kind="quick_edit"`, child transcript reopened |
| G4.11 | `stream.spec.ts` | every archived `(session_id, ordinal)` id in the DOM exactly once |
| G4.12 | `harness/archive.ts` | named screenshots attached; **never** compared to anything |
| G4.D | `stream.spec.ts` | containment + groundedness over `JSON.parse(payload.text)`, `R` read from `schemas/tools/*` |
| G4.X | `dom.spec.ts` | the DFM action's findings, with topology descriptors |
| §7A | `composer.spec.ts` | the composer (INTERFACE.md §7A, §19.17/§19.20/§19.26/§19.28/§19.30). §7A.12's cases 1, 2, 6 and 7: a part created by the composer's own turn appears in the tree with **no manual reload**, the context chip row is droppable and the disclosure matches `POST /context/preview` byte for byte, a serve with no runtime renders the composer disabled with its named cause and the path, and `POST /sessions` refuses `quick_edit` and a partless `part`. Cases 3 and 4 are pytest by §7A.12's own instruction ("it asserts on the ops layer, not the DOM"): `server/tests/test_context_envelope.py` and `server/tests/test_request_binding.py`. Case 5 is `ask.spec.ts`. **Every session here is created in the browser** — §7A.9 forbids this and G4.8 sharing a fixture, because a G4.8 driven through the composer would test a self-observation instead of a cross-process round trip |
| §7A.7 | `ask.spec.ts` | a browser answers a suspended `ask_user`: `self` / `other` on two attached tabs, and `abandoned` in place after a cancel. Under G4's `ask_user widgets` deliverable (INTERFACE.md §0.2's Stage-4 row), not a new clause |
| **G10A** | `export.spec.ts` | egress (INTERFACE.md §22, Stage 10A): the panel's download equals the recorded blob byte for byte, the token is in no URL the browser issues, the pin survives a newer build, the DFM pack's kerf is reported, `/artifacts/{ref}/bytes` refuses the export ref **and** a `build`-relabelled ref naming the same blob, the key ladder's three clauses, and a `gc.collect()` that leaves the export and its source build reachable. **A different gate from G4/G5** — G4 and G5 do not mention export and the Stage 10 amendment edits neither |

**G10A's "same digest" clause is discharged on the replay path, and the reason is
measured.** `step` and `dxf` are not byte-deterministic — OCCT stamps wall-clock
time into the STEP `FILE_NAME` header and the DXF writer does the same — so two
fresh executions over one frozen artifact differ whenever they cross a second
boundary; and for the four formats that *are* deterministic (`stl`, `glb`,
`3mf`, `svg`) a fresh-key re-export produces the identical content-addressed
stem and is refused `target_exists` by the create-only install. The digest half
therefore rides the idempotency-key replay, which is what §22.2 says the key is
for, and the pin half is asserted on geometry. `export.spec.ts`'s header carries
the full argument.

**The scripted model dispatches on the request, not on turn order.**
`serve_fixture.py::scripted_turns` hands `FakeOpenAI` a list of identical
resolvers, each of which reads the request: a conversation with a tool result in
it gets the closing text turn, a prompt carrying the handshake's
`ask.sentinel` gets the `ask_user` suspension, anything else gets G4.8's
`run_checks`. A positional script made every spec's turns depend on which specs
had already run, which is a coupling that only ever bites when someone adds a
spec.

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
`tests/render`" — and that image landed 2026-08-28 (`docker/ci/Dockerfile`,
built and pushed by `ci-image.yml`, consumed by digest). So this suite is no
longer deferred: `ci.yml`'s `render goldens (pinned image)` job runs
`pnpm --dir web test:e2e` there, alongside `tests/render` and
`tests/stage4/test_g4_section_golden.py`. The stock-runner jobs still exclude
all three by name. Both G4.7 halves **fail by name** on an unmatched renderer
rather than skipping, so the pin can never quietly become a pass.
`docker/ci/README.md` has the recipe for running them locally in that image
without the container writing build state into your worktree.

Note the two halves do not agree about *when* they may run. The pytest half
refuses up front on the renderer **string**; the Playwright half builds the
fixture live and compares **bytes**, so it passes on any host whose pixels
happen to match. Measured 2026-08-28 on an Arch host at llvmpipe 22.1.8: the
served plate is byte-identical to the golden baselined on llvmpipe 20.1.2, so
the pytest guard is stricter than the assertion it guards. Conservative and
deliberate — but do not read a green e2e G4.7 on a dev host as evidence that
the pytest half would pass there.

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
`[data-viewport-canvas]`, `[data-appearance]` / `[data-appearance-control]`,
`[data-explode-t]`, `[data-section-control]` with
`data-section-plane`, `[data-section-plate]`+`data-plate-ref`,
`[data-testid="stream-panel"]` — which carries `data-stream`,
`data-history-state` and `data-history-pages` **unconditionally**, since
§7.4(a)/§8(a) make the drawn badge and the drawn page counter exception-only and
a gate cannot read a row that is not mounted (§7.4(b), §8(c)) —
`[data-testid="transcript"]`, `[data-history-bar]` and `[data-stream-state]`
(the two DRAWN exceptions, absent in the steady state),
`[data-session-create]` / `[data-session-ask]` / `[data-session-create-menu]`,
`[data-stream-collapse]`, `[data-session-tab]` with
`data-thread-depth` / `data-thread-kind`, `[data-event-id]`+`data-surface`,
`[data-tool-name]`+`data-status`+`data-tool-call-id` (with §7.2 (a)'s
`data-chip-repeat` / `data-event-ids` / `data-tool-call-ids` on a coalesced
row), `[data-chip-detail]`+`[data-chip-detail-count]`, `[data-field-state]`,
`[data-image-state]`+`data-mime-type`, `[data-terminal-state]`,
`[data-testid="no-token"]`.

G4.6 reads the scene graph rather than the DOM, through
`window.__hephaestus_viewport__.solids()` (`../src/viewport/testHook.ts`). The
pairwise **subtraction** is the harness's, not the app's.
