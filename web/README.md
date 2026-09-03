<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# `web/` — the Hephaestus workspace client

An observation and provenance instrument that happens to have an editor
(`INTERFACE.md` §0). It is a **pure client** of `server/http`: it holds no
geometry logic and computes no fact (§1). Numbers, IDs, verdicts and provenance
are the server's; pixels, camera and hover state are the client's.

## Commands

```console
$ pnpm --dir web install --frozen-lockfile
$ pnpm --dir web build       # tsc --noEmit && vite build → web/dist
$ pnpm --dir web typecheck
$ pnpm --dir web lint
$ pnpm --dir web test        # vitest: workspace state, URL, token handshake
$ pnpm --dir web test:e2e    # Playwright — see e2e/README.md; build first
```

To drive it against a live project:

```console
$ cd <project> && heph serve --web            # prints http://127.0.0.1:8760/#t=<token>
$ HEPH_WEB_API=http://127.0.0.1:8760 pnpm --dir web dev
```

Vite's dev server is a development convenience proxying `/api` (including the
`/api/v1/events` WebSocket) to a running `heph serve --web` (§3). In production
the built assets ship inside the wheel and `--web` serves them from
`importlib.resources`.

## Layout

| Path | What lives there |
|---|---|
| `src/copy.ts` | **Every** human-facing string, in one file, so clean-room hygiene is auditable in one place (§3) |
| `src/tokens.css` | The design-token file; `*.module.css` beside each component (§3) |
| `src/state/workspace.ts` | §4.5's closed record, the **single pin authority**, and URL serialization |
| `src/state/react.ts` | `useSyncExternalStore` binding + the URL sync |
| `src/api/` | The `/api/v1` fetch path, the §2.4 refusal envelope, the wire types, TanStack Query wiring |
| `src/components/Fact.tsx` | §4.6's `<Fact>` primitive — the only element that may mint `data-source` |
| `src/components/rail/` | §13's read-only half: part tree, git dirty markers, versions |
| `src/components/stage/` | Stage tabs, Monaco script view, viewport, and Inspector shell |
| `src/components/inspector/` | Properties, checks, DFM, results, sourcing, provenance, and export panels |
| `src/stream/` | §7/§8 transcript model plus composer context, gating, socket resync, history paging, and threading |
| `src/components/stream/` | Session tabs, Composer, tool chips, thoughts, images, interactive `ask_user`, and transcript rendering |
| `src/components/ProvidersPanel.tsx`, `src/components/SignInDialog.tsx` | Runtime attachment, provider selection, and credential flows |
| `src/components/chrome/ExportChrome.tsx`, `src/api/exports.ts` | Export selection, admission, and download flows |
| `eslint-rules/no-derived-fact.js` | §1's boundary, made mechanical |
| `test/fixtures/record-normalized-events.mjs` | Records `normalized-events.json` by running the sidecar's own normalizers; see below |

## The rules this code exists to keep

**The pin has exactly one authority.** `artifact_ref` and `pin_mode` are not
writable through `update()`; there are three doors (`hold`, `followCurrent`,
`observeCurrent`) and `observeCurrent` — the only path a server response may
take to the pin — is a no-op while held. Publishing a new build never advances a
held pin (§4.5, G5.6).

**Nothing displayed is computed here.** Every fact renders through `<Fact>` with
a `data-source` naming the response field. `heph/no-derived-fact` rejects a
derived `value` (arithmetic, `.length`, `Math.*`, coercions, folding array
methods), a non-static `source`, and a `data-source` on any element that is not
`<Fact>`. The geometry count in the tree is the server's explicit
`build.geometry_count` field, never a recount of `geometries` (§6.1, G4.2).

**The two axes never blur.** The header shows the artifact axis (pin, build
state); the rail shows the git axis (dirty markers, versions). Dirtiness is a
`git status` fact about `parts/*.py` and is disjoint from artifact and
publication state (§13.1).

**"Publish" is never a word in the UI.** A build becoming `current` is "current
build"; a `git tag` is a "tag release" (§13.2).

**Script paging never re-reads the mutable source.** Page 0 is
`GET /parts/{part}/script`; every later page is
`GET /artifacts/{snapshot_ref}/text?offset_bytes=` at a cursor the *server*
supplied — `tool_schema.md`'s continuation rule, in its web spelling.

**History and the live stream are never merged.** They are not in one namespace:
a live event is `(run_id, seq)`, a historical one `(session_id, ordinal)`, and
`data-event-id`'s separator (`#` vs `@`) says which. History is the transcript's
prefix, the socket its suffix, the boundary a **visible seam**, and a
`4409 resync_required` leaves a **labelled break** that is never healed from
history — §2.7 is explicit that a dedupe across the two would never match
(§2.7, §2.8, §8).

**A tool chip never reads an unknown outcome as success.** `data-status` is
`running | ok | error`, plus §7.2's own named fallback `unknown` for a historical
result whose failure flag `normalizeEntries` could recover from neither Pi's
`isError` nor the serialized envelope's `status`. `data-field` nodes are exactly
the keys of `JSON.parse(payload.text)`, which satisfies §7.2's containment
obligation for every tool and its groundedness obligation by construction; a
result that is not a JSON object renders `data-field-state="unparsed"` with zero
fields and a stated reason (G4.D).

### Re-recording the stream fixture

The stream component tests run against **recorded** engine output, not
hand-written events, because what they assert is what the engine emits:

```console
$ pnpm --dir agent build
$ node web/test/fixtures/record-normalized-events.mjs
```

The output (`web/test/fixtures/normalized-events.json`) is committed with a
provenance block. Re-recording is its own change, carrying the normalization
change that caused it — the churn policy the render goldens use. It is **not**
G4.11's event archive (`tests/stage4/goldens/events/`, server-side, over a real
project); §14 forbids a browser-rendered golden family and this is not one.

## Implemented operator surfaces

The client now includes the Inspector panels, Composer and browser-created
sessions, interactive `ask_user` answers, provider/runtime attachment and
credential flows, export controls, and the Playwright acceptance suite. The
suite map and its prerequisites live in [e2e/README.md](e2e/README.md).

The architectural boundary is unchanged: the browser may initiate operations,
but it does not compute geometry, verdicts, provenance, or derived engineering
facts. Those remain server-owned and arrive through the documented API.
