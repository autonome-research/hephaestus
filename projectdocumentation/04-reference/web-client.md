# Web workspace client

> **Verified against** `3af69da` on 2026-09-12.
> Dependencies read from `web/package.json`; module inventory from
> `find web/src -name '*.ts*' | wc -l` = 128 source files, 77 unit test files,
> 44 e2e files; lint rules read from `web/eslint-rules/`.

The browser workspace is what `heph serve --web` fronts. Its own package
description states what it is: *"an observation and provenance instrument that
happens to have an editor."* Everything below follows from that ordering.

## Stack

| Dependency | Version | Role |
| --- | --- | --- |
| `react` / `react-dom` | 18.3.1 | UI |
| `@tanstack/react-query` | 5.102.8 | server state |
| `three` | 0.185.1 | the 3D viewport |
| `monaco-editor` | 0.56.0 | the script editor |
| `vite` | 8.2.2 | dev server and build |
| `vitest` | 4.1.11 | unit tests |
| `@playwright/test` | 1.62.1 | end-to-end |
| `typescript` | 5.9.3 | `tsc --noEmit` gates the build |

Node ≥ 22.19, pnpm 10.34.5. There is **no state library**: the workspace record
is one module over `useSyncExternalStore`. Zustand and Redux were rejected as a
dependency whose only output is a store this small; per-component `useState` was
rejected because it cannot hold a single pin authority.

## Layout

```
HEADER
RAIL  |  STAGE  |  STREAM
```

The stream is a **full-height peer column**, collapsible but not hidden by
default. Giving the agent a column rather than a bottom drawer is the
"collaborator, not console" claim cashed out in layout.

Width supplies **capacity, never conversation intent** — a capacity band never
resets an explicit intent, and neither threshold automatically hides the
conversation. Three bands, from `state/shell.ts`:

| Band | Width |
| --- | --- |
| `wide` | ≥ 1280 px (`BREAKPOINT_STREAM`, `BREAKPOINT_RAIL`) |
| `medium` | 1024–1279 px |
| `narrow` | < 1024 px (`BREAKPOINT_NARROW`) |

Column sizing: stream 360–640 px, stage minimum 360 px, rail 280 px, drawer
200–420 px. An explicit Hide leaves a horizontal return control whose activation
reveals without writing a task, and conversation evidence outlives the panel's
mount.

Client presentation is **not** the addressable URL record: this store owns
explicit panel intent and preferred dimensions, `useBreakpoint` supplies only
capacity, and CSS consumes `data-stream` / `data-rail` rather than a competing
grid media query.

| Region | Contents |
| --- | --- |
| Header | project, build state chip, pin controls, model picker |
| Rail | project tree, version list, git dirty panel |
| Stage | viewport, script editor, parameter sliders, timeline, inspector |
| Stream | transcript, composer, tool chips, ask-user widget, session tabs |

## The token

`heph serve --web` prints `http://127.0.0.1:PORT/#t=<token>`. The token rides in
the **fragment**, never a query string, so it never enters an access log or a
`Referer`.

The app moves it to `sessionStorage` (keyed to this origin), rewrites the URL,
and sends `Authorization: Bearer …` on every request. Without a token the app
renders **one non-interactive panel** explaining how to obtain one; it never
prompts for credentials, because there are none to prompt for.

The rewrite happens **once, before anything else reads the hash**, because the
workspace route lives in that same fragment and `#t=…` is not a route —
`main.tsx` calls `claimToken()` first for exactly that reason.

A 401 forgets the token and notifies the app gate, so the tab remounts the
no-token panel instead of leaving a shell that 401s every subsequent request.
Token absence is a two-valued type — `"none"` (never had one) versus
`"unauthorized"` (a live 401) — because they are different situations for the
reader.

## One fetch path

`api/client.ts` is the only module that talks to the server. It **preserves the
reason** rather than flattening refusals into a message string:

```ts
class WorkspaceError extends Error {
  readonly status: number;
  readonly reason: string;                              // the machine word — keep it
  readonly data: Readonly<Record<string, unknown>>;
}
```

A named refusal the client renders as generic failure is the same defect the
provenance rules name: a weak answer that does not say why it is weak reads as a
bug.

### Refusals are not retried

```ts
retry: (failureCount, error) => {
  if (error instanceof MissingTokenError) return false;
  if (error instanceof WorkspaceError) return false;
  return failureCount < 2;
}
```

A refusal is the server's **considered answer**, not a transient failure. The
taxonomy is closed, and retrying a `stale_selection` or an `unknown_artifact`
produces the same refusal at the cost of load.

### Refusal text has no raw-message fallback

`components/refusalText.ts` maps a reason to one sentence, and the old
`error.message` fallback is **deliberately gone**. That fallback reasoned "the
server named it, so the server's words stand" — true of a sentence and false of a
*composed* string. The server builds `agent_unavailable`'s message as
`f"{cause}: {detail}"`, so the panel rendered `no_provider_config: no provider
config at <path>` — a machine reason code, a colon and an engine detail — inside
a `role="alert"`.

It is a module no surface owns, because three surfaces render the same refusals:
the sign-in dialog, the providers panel, and the composer's attach action. One
route (`POST /providers/attach`) is rendered by two of them a few inches apart on
the same screen.

### Idempotency keys are minted client-side

The first two rungs of the key ladder are the client's to satisfy, and both are
"no execution", so a client that mints a wrong-shaped key never runs anything and
never learns why from a spinner.

The key is a **UUIDv7**, and the version is not decorative: the server reads the
timestamp embedded in the key to apply the first-sight freshness rung. A UUIDv4
has no timestamp to read, which is why it is refused as malformed rather than
accepted as an opaque string.

**The key is minted once per *submission*, not once per click.** A transport
retry of one export reuses its key — that is the point, because the server
installs export files create-only and a keyless or re-keyed retry collides with
its own first attempt. A fresh key is minted the moment any field changes.

## Query policy

TanStack Query was chosen because server state is almost entirely
content-addressed and cacheable **by ref**; refetch and invalidate are the whole
problem.

Staleness is a property of the **route**, not a tuning knob. Every route with a
hook is *project state* — `/project`, `/parts`, `/parts/{part}/{build,script}`,
`/git/*` — which changes when the human or the agent changes it, so each carries
a short staleness and refetches on focus.

The **by-ref** tier has no hook on purpose. Its one consumer is the script pager,
which must *accumulate* pages of one snapshot in cursor order; a per-page query
cache holds each page but not the sequence, so `useScriptPages.ts` owns that
accumulation and calls `apiJson` directly.

**Nothing transforms a response.** A `select` that reshaped a document would be
the client deriving a fact one layer below the panel that renders it, and it
would put the `<Fact source="…">` paths out of step with the wire.

## The pin authority

`artifact_ref` is first-class, sticky workspace state, and **publishing a new
build never advances a pin whose `pin_mode` is `"pinned"`**.

`artifact_ref` and `pin_mode` are therefore *not* writable through `update()` —
the patch type excludes them and the method throws if a non-TypeScript caller
passes one anyway. There are exactly three doors:

| Door | Effect |
| --- | --- |
| `hold(ref)` | an explicit user act: `pin_mode := "pinned"` |
| `followCurrent(ref)` | the explicit header action: `pin_mode := "current"` |
| `observeCurrent(ref)` | the server said what `current` is — a **no-op while held** |

`observeCurrent` is the only path a server response may take to the pin, and it
is the one that must not fire while held. A workspace that auto-refreshed to
latest would silently fall back to current geometry, which the architecture
forbids outright.

The workspace record is a flat, URL-serializable record rather than a reducer
ceremony, because it has to round-trip through a URL.

## Provenance: `<Fact>`

```tsx
<Fact source="build.geometry_count" value={n} />
→ <span data-source="build.geometry_count" data-value="12">12</span>
```

Three properties are load-bearing:

- `data-source` names the **HTTP response field** the number came from — not the
  panel, not the concept, the field, so an assertion can index the JSON with it.
- `data-value` carries the value **unformatted**, so a human-readable rendering
  (thousands separators, a unit suffix) never becomes the thing an assertion has
  to parse back.
- `<Fact>` is the **only** element allowed to mint `data-source`.

This gives the e2e one uniform selector for DOM-versus-JSON comparison instead of
per-panel text scraping.

### `heph/no-derived-fact`

A custom eslint rule, error-level, that decides exactly three things:

1. **`<Fact source>` must be a static, dotted response path.** A computed
   `source` would let a component mint an attribution at runtime — attribution
   theatre, since the point is that a reviewer and the e2e can both read it out
   of the source tree.
2. **`<Fact value>` may not be a derived expression.** Arithmetic, `.length`,
   `Math.*`, `Number(…)`, `parseInt`/`parseFloat` and the reducing array methods
   are rejected outright. "Any re-count of anything a build result already
   counts" is `.length` on a server array, spelled out.
3. **Only `<Fact>` may carry a literal `data-source`.** Otherwise any element
   could forge the attribution the lint exists to check.

What it deliberately does **not** decide is whether an arbitrary rendered number
is a *fact*. That is a judgement about meaning, and a lint that guessed would
either be trivially evadable or would flag the grid readout, which is exempt by
name — screen-space quantities are exempt *and are never rendered as facts*. The
mechanical half is the three checks; the completeness half is the e2e's
DOM-versus-JSON comparison.

Repeated elements carry their index in a `data-*` attribute beside the fact
(`build.geometries[].label`), because the path has to be a static string for the
rule to check it.

### Measured values

A `measured` value renders as **the message as the row value, the code as a chip,
and the raw object behind a disclosure** — never `JSON.stringify` output in a
reading surface.

The machine-readable half is unchanged: `<Fact>`'s `data-value` still carries
`JSON.stringify(measured)` verbatim, which is what the e2e's DOM-versus-JSON
comparison and the audit harness read. The defect was never that the value was
serialized; it was that the same serialization was **also** the human text.

It is two components rather than one, and the split is the lint's: a single
`<MeasuredValue source={…}>` would have to pass its `source` prop into `<Fact>`,
and a computed attribution cannot be reviewed or asserted on.

## Design-system lints

Four more custom rules in `web/eslint-rules/design-system.js`:

| Rule | What it holds |
| --- | --- |
| `heph/no-palette-token` | components use semantic tokens, not raw palette values |
| `heph/no-raw-type` | typography goes through the type roles |
| `heph/system-owns-status` | status presentation belongs to the system layer |
| `heph/token-contrast` | token pairs must meet contrast |

The design system itself is `web/src/system/`: `Badge`, `Button`, `Chip`,
`DataTable`, `EmptyState`, `Input`, `Panel`, `Popover`, `TabBar`, `TreeRow`, plus
`tokens.css` and the type roles.

## The event socket

`GET /events` is a WebSocket. Everything the transport decides is one of the
`live.ts` actions; the socket module holds no transcript state of its own.

**The bearer rides a subprotocol.** A browser **cannot** set a header on a
WebSocket upgrade — there is no API for it. The server therefore accepts the
token as a second subprotocol value (`hephaestus.bearer`) and echoes the first
value back on accept. That preserves the property the fragment rule argues for,
because a subprotocol travels in a request header, not in the URL. The query
string, the other thing browsers can do, would put the token in every proxy log
on the path.

**Two control frames and no others.** `{subscribe, resume}`; any other key closes
the socket `1008`. The vocabulary is closed on the client too — a frame is built
by the two builder functions or not at all.

**Reconnection is not repair.** A `4409 resync_required` close means the server
dropped this observer to protect the run: the browser never participates in
backpressure cancellation, because a stalled tab must not kill an agent's work.
Reconnecting replays only what the live buffer still holds; the rest is a
**labelled break**. The module never fetches history to fill one, because the two
identity namespaces do not compare.

### Follow-scroll

Reading position is per session — `{following, top, anchor, offset}` — held in a
project-lifetime map, because presentation is not workspace URL state. Following
resumes when the reader is within `FOLLOW_BOTTOM_PX` (32 px) of the bottom.

A scroll event is only treated as operator input when it actually came from the
operator; treating every scroll event as input made the stream stop following
during its own programmatic scrolls.

## The viewport

`viewport/engine.ts` is a plain class, not a hook or a component: the renderer
owns a GPU context and a scene graph whose lifetime is the canvas's, not a render
pass's. React *drives* it — one effect per workspace field — and `Viewport.tsx`
holds no three.js state of its own.

Four decisions worth reading:

- **Orthographic, framed like the server.** The server fits an orthographic
  camera per view; a perspective viewport would put the browser and `heph render`
  in visible disagreement about the same named view, for no gain in a CAD
  instrument. `scene.ts::framingFor` mirrors the server's construction.
- **On-demand rendering, with a *synchronous* frame after a programmatic
  change.** There is no animation loop. A change the app made — a toggle, a
  slider tick, a view — draws immediately rather than on the next rAF, so a
  harness that screenshots right after a click sees the frame that click
  produced. A user drag coalesces through rAF, because sixty synchronous frames a
  second is what a loop is for.
- **`preserveDrawingBuffer`.** Chromium may clear a WebGL back buffer after
  compositing, and a screenshot taken afterwards can come back blank. It costs a
  copy per frame and buys a deterministic screenshot.
- **The client authors the display**, while the GLB's own materials are kept
  anyway.

### Reading the GLB

`GET /artifacts/{ref}/gltf` returns one **mesh per solid** (mesh count equals
solid count, a hard assertion), one **primitive per face** inside its solid's
mesh, and `extras` carrying selection IDs and descriptors.

`glb.ts` reads the JSON chunk and returns **exactly three** per-mesh values:
`solid_index`, `label`, and `explode_offset` (the float3 displacement at t = 1).

**`extras.selection_id` is deliberately not read.** The browser's raycast
supplies `(mesh_index, primitive_index)` as a **hint about which triangle was
hit** — never a `selection_id`, and never an authorization. A client that had the
ID in hand would eventually submit it, and selection IDs are server values. So
the ID is not parsed, not stored, and not reachable from anything the module
returns.

### Section has two surfaces that must not be confused

| Surface | What it is |
| --- | --- |
| the **plate** | a *server*-rendered PNG, displayed as a fitted image layer, `data-section-state="rendered"` — the evidentiary surface, golden-compared |
| the **live clipping preview** | three.js clipping planes while the control is dragged, `data-section-state="preview"` — **never** golden-compared |

The plate is server pixels because a headless-Chromium WebGL render is a
**different rasterizer** and will not match the goldens.

## Running it

```console
$ cd web && pnpm install
$ pnpm dev                       # vite; proxies /api to $HEPH_WEB_API
                                 # (default http://127.0.0.1:8760), ws: true so
                                 # GET /api/v1/events rides the same proxy
$ pnpm typecheck                 # tsc --noEmit
$ pnpm test                      # vitest
$ pnpm test:e2e                  # playwright
$ pnpm lint                      # eslint, including the five custom rules
```

There are three Playwright configurations: the default, an images config, and a
synthetic config.

`pnpm build` runs `tsc --noEmit` before `vite build`, so a type error fails the
build rather than shipping.
