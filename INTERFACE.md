<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# 12 — The web workspace (Stages 4 and 5)

**DRAFT — pending adversarial review.** Not normative. Promotion follows the
`ASSEMBLY.md` / `COMPARE.md` / `KINEMATICS.md` pattern: a dated `mission_plan.md`
amendment carrying the Stage 4 and Stage 5 headings and citing this spec, after
an adversarial pass against the codebase. Until then `mission_plan.md` Stage 4
and Stage 5 are the only binding text.

This spec **adds design detail beneath G4 and G5**. It does not restate,
reword, weaken, or extend either gate. Where a gate clause is ambiguous,
mission rule 1 requires **tightening**; every tightening below is marked
**TIGHTENING** and names the clause it binds. Where the gates are silent, the
choice is marked **DECISION** and names the alternative that lost. Where
nothing in the repo satisfies a clause, it is marked **NEW WORK** (§19 is the
closed list).

Clause labels (`G4.2`, `G5.13`, `G4.X`, …) are a **citation index over the gate
prose**, introduced here for mapping only. They are not gate edits, they carry
no authority, and the gate text in `mission_plan.md` is the only text that
binds.

This spec amends, enumerated per doc and per section on the `KINEMATICS.md`
manifest pattern:

- `architecture.md` §5 — the HTTP/WS surface becomes a named, closed route
  table rather than a prose promise (lands with §2.3).
- `architecture.md` §6 — the client boundary gains a mechanical test (lands
  with §1 and §4.6).
- `repo_conventions.md` **Stage S accepted-versions block** — gains the exact
  pinned versions of the `web/` dependency set §3 introduces (React, Vite,
  three.js, Monaco, TanStack Query, Playwright, and the CSS-module tooling)
  under the no-caret exact-pin rule, and §3's wheel-embedded bundle-delivery
  clause. It does **not** amend `repo_conventions.md`'s stack or lint bar:
  `web/  TypeScript, React 18, Vite, three.js, Monaco. pnpm workspace.` and
  `web/: eslint, tsc strict, Playwright e2e per mission gates.` are already
  there, and §3 restates rather than adds them. Recording the pins is named
  work (§19).
- `tool_schema.md` preamble §idempotency — REST becomes a third named
  transport with a pinned reconciliation shape and an explicit per-route key
  policy (§2.3, §2.5), which G5.19 forces.
- `agent/src/session/history.ts` — the historical normalizer gains `isError`
  on `tool_result` (§7.2, §19), without which a reopened transcript would
  render a failed tool as succeeded.

It amends **nothing** in `script_contract.md`, `VALIDATION.md`, `ASSEMBLY.md`,
`COMPARE.md`, `INGEST.md`, `EXTERNAL_EVAL.md`, or `KINEMATICS.md`: the
workspace reads those surfaces and authors none of them.

---

## 0. What the workspace is, and what it is not

The workspace is **an observation and provenance instrument that happens to
have an editor**. Its centre of gravity is a geometry viewport bound to one
*immutable build artifact*, and a provenance chain that answers "where did this
face come from" without ever guessing. The agent stream sits beside it as a
peer surface, not a log pane.

That framing is not decoration. It falls out of two facts the repo already
carries:

1. `heph agent` writes tool images to `<project>/.heph/agent_images/` and prints
   a path (`agent_bridge/cli.py`). Grounded vision is the mechanism of the core
   loop (`architecture.md` §3.3) and a terminal cannot show it. The deficit the
   workspace closes is *seeing what the agent saw* — a viewport-and-artifact
   problem before it is an editing problem.
2. G5's densest clauses are not editing clauses. They are A/B provenance
   clauses: render A, publish B, click A's mask, and every ref must still
   resolve against A. A workspace whose central object is "the current part"
   fails those by construction. **The central object is an artifact ref.**

The workspace is **not**:

- **A parametric CAD editor.** `architecture.md` §8: no direct manipulation.
  Nothing is dragged in the viewport. The three human editing verbs are exactly
  Monaco text, `PARAMS` sliders, and *selection → scoped agent*.
- **A geometry engine.** `architecture.md` §6, last line: *"The web app is a
  pure client of `server/`; it holds no geometry logic."* §1 makes that a
  mechanical test rather than a slogan.
- **A session manager.** Sessions, leases, and admission belong to `server/`
  (`architecture.md` §4.2). The browser is one more client under the same lease
  contract, and it loses that contract's arguments.
- **A deployment.** `architecture.md` §7: loopback plus a bearer token. No TLS,
  no real authn, no multi-tenancy, no hosted posture.
- **A sharing surface.** §8: no Scrapyard-style community sharing.
- **Part of the headless surface.** The 2026-07-26 ordering amendment:
  `server/http` "is a web client API, not part of the headless surface."
  Nothing in G7H may come to depend on it.

### 0.1 Drafting stance — engine truth, and one implementation

Every panel is a projection of a wire shape that already exists. Every route
returns a shape a tool or a CLI verb already returns. Where the browser needs
something the engine does not say, the honest answers in order are: (1) it is
already said somewhere and the route joins two existing documents; (2) it is a
genuinely missing *durable* fact and is added **in the engine**, never in the
client; (3) it is not shown. This spec never computes a fact client-side
because the server declined to offer it.

Mission rule 6, stated as the rule this spec follows literally:

> `server/http` rides the **same** `ToolDispatcher` / `CadOps` / `RenderStore`
> the MCP server rides. Where a contract (UTF-8 paging, check serialization,
> event normalization) lives in exactly one place today, HTTP calls that place.
> Where it lives in one place with a session-scoped principal check welded to
> it, the contract is **extracted** into a shared function and each caller
> applies its own principal check. **Extraction is permitted; duplication is
> not.**

Numbers, IDs, verdicts, and provenance are the server's. **Pixels, camera, and
hover state are the client's.** That sentence is the whole architecture.

---

## 1. The boundary, stated as a test

`architecture.md` §3.3 already permits local rendering ("we render server-side
for the agent loop and ship GLTF to web clients, which render live locally")
while §6 forbids client geometry logic. The line between them:

> The client may compute **screen-space** quantities from server-supplied
> geometry — camera transforms, raycast hits, per-node visibility, per-node
> translation along a **server-declared** axis. It may not compute, synthesize,
> reconcile, or infer **any value that appears in a result, a badge, a readout,
> a provenance answer, or a selection**.

**TIGHTENING (binds G4.2, G4.3, G4.4, G4.6, G5.1, G5.4).** Every number the UI
presents as fact renders through the `<Fact>` primitive (§4.6) and carries a
`data-source` attribute naming the HTTP response field it was read from. A
displayed fact with no such attribution is a lint failure — `web/` eslint rule
`heph/no-derived-fact`. Screen-space quantities are exempt *and are never
rendered as facts*: the grid readout renders a camera state, never a
measurement.

Three consequences, named because they are the ones that get got wrong:

- **Measure computes nothing.** Two clicks produce two *server-validated*
  selections and one `measure` call. The readout is `{value, units}` verbatim.
- **Explode is a client transform over a server-declared displacement.** The
  GLTF ships each solid's **`explode_offset`** — the full displacement vector
  at `t = 1`, `(solid_centroid − assembly_centroid) · EXPLODE_SCALE`, which is
  what `render/channels.py::_explode_offset` computes (`channels.py`:553-557;
  `EXPLODE_SCALE = 1.0` at :111 is a single global constant, not a per-solid
  number). The client applies `offset · t` and nothing else. It does not
  compute centroids, does not normalize, and does not reconstruct a magnitude.
  G4.6 reads pairwise centroid distances back out of the scene graph, which is
  a screen-space fact about a server-declared vector — exactly what
  `verification.md` Tier 2 asks for. §5.1 makes the emission NEW WORK and §5.2
  states why the vector, and not an axis/scale pair, is the shipped shape.
- **Section is a server render** (§5.3). This is the sharpest render decision in
  the document and it goes the conservative way.

**Closed list of what the client MUST NOT compute:** distances, volumes,
masses, clearances, interference; section geometry; selection IDs, palettes,
legends, or any decode of a shaded viewport frame; check verdicts, DFM
findings, requirement or assembly or motion state; dirty/history/publication
state; any re-count of anything a build result already counts.

---

## 2. `server/http`

### 2.1 Topology — one process owns the leases

**DECISION (binds G4.8).** `heph serve` gains `--web [HOST:PORT]`, orthogonal to
`--mcp`: `--mcp` remains required for the MCP transport and is not required for
`--web`. What survives unchanged is the invariant that matters — both force
`serve_mode=True`, so the secure backend is probed and `--unsafe-local-executor`
remains absent from this verb. **The web never has an unsandboxed path.**

The serving process **owns the session leases** under `.heph/locks/` and writes
`<project>/.heph/serve.json` (`0600`) = `{pid, http, started_at, token_path,
started_by}`. `heph agent` gains **no new flag**: at startup it reads
`serve.json`, and if a live server owns the project it runs in **client mode**,
driving `session.create` / `prompt` / `cancel` over the loopback API (reading
the same-user `0600` token file) instead of spawning its own `BridgeRuntime`.
If no server is running it behaves exactly as today. If a server is running but
unreachable, it refuses with structured `session_busy` rather than opening a
second in-process bridge.

*Rejected alternative:* a cross-process event bus (fanout socket, tailed file)
so both processes can hold a runtime. Rejected because `architecture.md` §4.2
already says a second process **must** route through the owning server or fail
`session_busy`; a bus would be a second implementation of session ownership
(mission rule 6) and would put two writers on one Pi JSONL.

*Rejected alternative:* a `--server URL` flag on `heph agent`. Rejected as an
added surface with no gate behind it; `serve.json` is discovery enough, and a
flag invites pointing the CLI at a server that does not own the project's
locks.

The visible consequence — and it is the whole of G4.8 — is that a session
started in a terminal is *the same session object* the browser attaches to,
because there is only ever one runtime. No event forwarding exists to get
wrong.

### 2.2 Principal and authorization

The workspace principal is **not** a Pi session and must not borrow one.

```
WorkspacePrincipal { project_root, profile="orchestrator", token_id }
```

`profile="orchestrator"` mirrors `mcp/app.py::_MCP_PROFILE`: a local operator
with the project open is orchestrator-equivalent. Dispatch's own object-scope
and reviewer rules apply unchanged; the HTTP layer adds no authz of its own
beyond the token. Every tool route goes through `ToolDispatcher.dispatch` with
this principal — there is no bypass. Sessions spawned *from* the workspace
(quick edit) keep their own profile and their own `Principal`.

**Token.** Minted per serve into `<project>/.heph/serve.token` (`0600`).
`heph serve --web` prints, and on a TTY opens, `http://127.0.0.1:PORT/#t=<token>`.
**DECISION:** the token rides in the **fragment**, never a query string, so it
never enters an access log or a `Referer`. The app moves it to `sessionStorage`,
rewrites the URL, and sends `Authorization: Bearer …` on every request including
the WS upgrade. Without a token the app renders one non-interactive panel
explaining how to obtain one; it never prompts for credentials, because there
are none to prompt for. No login, no cookie, no refresh, no user model.

**Artifact capability model.** `tool_schema.md` scopes an artifact ref to the
current project *and authorized session* — that is the model-facing rule and it
is unchanged. The HTTP principal is not a Pi session, so for `server/http` an
artifact ref is a **project-scoped capability**: it must resolve in the open
project's opstore, and nothing else authorizes it. Stated as its own rule
rather than smuggled in, because this is the one place the web principal is
weaker-scoped than a model principal, and G5.8 forces the question.

### 2.3 Route table (closed for Stages 4/5)

Every route is `/api/v1/…`, bearer-authenticated, JSON except where noted. A
route not listed here is not Stage 4/5 work. The prefix is versioned because
this is a client API, not the headless surface, and a version segment is the
cheapest way to keep it from calcifying into one.

**Project and parts (read, no idempotency key)**

| Route | Returns |
|---|---|
| `GET /project` | `{root, name, units, parts[], serve_mode, capabilities}` — the `open_project` projection, same serializer as `mcp/app.py` |
| `GET /parts` | `[{name, path, content_hash, snapshot_ref}]` — `list_parts` projection |
| `GET /parts/{part}/script?offset_line&limit_lines` | `read_part` result verbatim, `_PAGING_FIELDS` intact |
| `GET /parts/{part}/build` | `BuildResult` projection: `{status, current, artifact_ref, project_snapshot_ref, effective_params, geometry_count, geometries[], metrics, checks, source_map_ref, warnings, error?, critique?}` |
| `GET /parts/{part}/properties` | the enumerated `part.*` metadata projection (§6.2) |
| `GET /parts/{part}/checks` | the shared `heph check --json` serializer (§6.3) |
| `GET /parts/{part}/params` | `PARAMS` declarations `{name, value, default, min, max, step, scope}` + `state_hash` |
| `GET /parts/{part}/dfm` | last `run_dfm` projection + `{auto_run, resolved_from}` |
| `GET /checks` | project-wide `heph check --json` parity body |

**Artifacts**

| Route | Returns |
|---|---|
| `GET /artifacts/{ref}/meta` | `{kind, mime_type, total_bytes, sha256, links{}}` |
| `GET /artifacts/{ref}/text?offset_bytes=` | the shared UTF-8 pager (§2.6) |
| `GET /artifacts/{ref}/bytes` | exact stored bytes, no transformation (§2.6) |
| `GET /artifacts/{ref}/gltf` | GLB bytes for a build artifact, `ETag: <ref>` |

**Inspection, selection, measurement**

| Route | Is |
|---|---|
| `POST /parts/{part}/inspect` | `inspect_part`, result verbatim including its `capability_error` variant |
| `POST /parts/{part}/selection/resolve` | server-validated selection → `ResolvedSelection` (§12.3) |
| `POST /parts/{part}/render/section` | server section render (§5.3) |
| `POST /measure` | `measure`, **project-scoped** |

`measure` is project-scoped, not part-scoped: `clearance` and `interference`
take features from two different parts, and a `/parts/{part}/measure` route
would have to lie about one of its operands. `inspect_part` and `measure` are
POST because their argument documents exceed what a query string should carry,
and they take **no** key: the key policy below is per route, not per HTTP verb.

**Mutating routes and their key policy (closed)**

**TIGHTENING (binds G5.19, "which routes are REST mutations").** An earlier
draft derived the key requirement from `MUTATION_TOOLS` (i.e.
`ToolDecl.idempotent`, computed in `dispatch.py`:112-114 purely from declared
tools). That rule is **withdrawn**, because it decides nothing for half of this
table: `session.create`, `prompt`, `cancel`, `answer`, `spawn_quick_edit`, a
project-config write, and a git tag have no `ToolDecl`, no `Invocation`, and no
recorded-outcome row to replay. A rule that silently exempts the routes a
reader most expects it to cover is worse than no rule. The policy is therefore
**enumerated**, in two tables, and the second one is not a weaker version of the
first — it is a different contract.

*Store, config, and output mutations — `Idempotency-Key` **required**, replayed
byte-for-byte (§2.5).* These are exactly the mutations `tool_schema.md`'s
"Source/config/output mutations carry an idempotency key" clause covers, and
for the first five `MUTATION_TOOLS` genuinely decides and the existing ledger
genuinely replays.

| Route | The tool it *is* | Record replayed from |
|---|---|---|
| `PUT /parts/{part}/script` | `write_part` (`expected_hash` required) | existing tool ledger |
| `PATCH /parts/{part}/script` | `edit_part` | existing tool ledger |
| `POST /parts/{part}/params` | `set_params` | existing tool ledger |
| `POST /parts/{part}/build` | `build_part` | existing tool ledger |
| `POST /parts/{part}/dfm` | `run_dfm` | existing tool ledger |
| `POST /project/config/dfm` | `[dfm] auto_run` project-config write (§6.4) | **NEW WORK**: non-tool ledger extension |
| `POST /git/tag` | publish-as-tag (§13.2) | **NEW WORK**: non-tool ledger extension |

**NEW WORK (§19).** The last two rows are config and output mutations with no
tool behind them, so the recorded-outcome ledger is extended to cover non-tool
REST operations. Its key space is `(project keyring HMAC, route,
Idempotency-Key)` exactly as for the tool rows (§2.5) — the operation identity
is the route, and the stored value is the response body. Without this extension
those two rows would be a header requirement with nothing behind it, which is
precisely the defect this table exists to remove.

*Session-control routes — `Idempotency-Key` **not required**, and sending one
is ignored rather than honoured.* Session control is not a source, config, or
output mutation; `tool_schema.md`'s key clause does not reach it, and §2.5's
byte-for-byte replay is incoherent for a route whose whole meaning is a
side effect on a live run.

| Route | Is | Why no key, and what stands in for one |
|---|---|---|
| `POST /sessions` | `session.create` (profile from a closed set) | Creates a session; a duplicate is an extra *idle* session, not a lost or doubled write. At-least-once is the stated consequence: a retried create may leave an orphan session, which `GET /sessions` lists and the operator closes. |
| `POST /sessions/{id}/prompt` | `prompt` | A prompt is not idempotent in any useful sense — the same words twice are two turns, and pretending otherwise would let a replay swallow a deliberate re-ask. At-least-once, stated. |
| `POST /sessions/{id}/answer` | `session.answer` for a pending `ask_user` | Governed by **question-id idempotency**, not by the header ladder: idempotent on the question id, first answer wins (§2.7). That is a stronger and already-existing guarantee; a second mechanism over it would be the duplication mission rule 6 forbids. |
| `POST /runs/{run_id}/cancel` | `cancel` — cancellation targets a **run**, so the route does | Idempotent **by construction**: `app.py::cancel` is a quiet no-op after close and a repeated `request_cancel` on an already-cancelled run changes nothing. A key would record a replay of a no-op. |
| `POST /parts/{part}/quick_edit` | `spawn_quick_edit` (§12.5) | Spawns a child session. Same shape as `POST /sessions`: at-least-once, a duplicate is an extra child tab, and the durable edge (§2.8) makes the duplicate visible rather than silent. |

**G5.19's subject, named exactly.** The missing-key test enumerates the seven
routes of the first table and asserts `400 idempotency_key_required` with **no
execution** on each; the replay test enumerates the same seven. It asserts on
the five session-control routes that a missing key is **accepted**, so the
policy is tested in both directions and cannot rot into "whatever the
implementation happens to check".

**Streams, history, git (read)**

| Route | Returns |
|---|---|
| `GET /events` (WebSocket) | live normalized events (§2.7) |
| `GET /sessions` | attachable sessions for the project |
| `GET /sessions/{id}/history?cursor=` | `history_page` passthrough (§2.8) |
| `GET /sessions/{id}/thread` | parent/child session edges (§2.8) |
| `GET /git/status` | `{dirty[], clean, head, branch}` (§13.1) |
| `GET /git/log?part=` | `[{sha, short, subject, author_date, tags[]}]` |
| `GET /git/diff?part=&from=&to=` | bounded unified diff text |
| `GET /git/tags` | `git tag -l` projection |

Absent, deliberately: no `POST /artifacts` (the workspace mints nothing), no
`DELETE` anywhere, no export/drawing/document routes (§15), no route that takes
a raw filesystem path. "No export route" is enforced rather than merely
declared: `/artifacts/{ref}/bytes` is closed **by enumeration** and refuses an
`export`-kind ref (§2.6), because a generic binary route scoped to
`BINARY_ARTIFACT_KINDS` would have served export bytes to any bearer holder.

### 2.4 Error mapping (closed)

Structured taxonomies survive the wire. The body is always
`{"status":"error", "reason": <machine reason>, "message": <human>, …data}`;
HTTP status is a coarse envelope over the reason and never replaces it.

| Engine condition | HTTP | Body |
|---|---|---|
| `invalid_params` / `invalid_part` / `invalid_cursor`, idempotency key faults | 400 | reason verbatim |
| addressing miss on `focus` | 400 | `addressing_error` |
| missing or invalid bearer | 401 | `unauthorized` |
| `DispatchError(scope_denied)` | 403 | `scope_denied` |
| `unknown_tool`, unknown part or artifact | 404 | reason verbatim |
| `StaleSelectionError` | 409 | `stale_selection` + `reason ∈ {rgb_ref, wrong_mode, mismatched, expired, malformed}` |
| `session_busy`, `part_busy`, `key_expired`, `key_timestamp_skew`, `key_payload_mismatch` | 409 | full refusal payload verbatim |
| snapshot ref past retention | 410 | `snapshot_expired` |
| admission full (17th run) | 429 | `busy` |
| `TIMEOUT` / `PROCESS_DOWN` | 504 / 503 | reason verbatim |
| **edit / param CAS conflict** | **200** | not an error — the discriminated result carrying `conflict{…}` |
| **`capability_not_available` / `image_model_required`** | **200** | the discriminated `capability_error` *result* |

**DECISION.** CAS conflicts and capability errors return **200**. They are
*successful, discriminated results* in `tool_schema.md`, and a web layer that
turned them into 4xx would make the editor's merge prompt (G5.20)
indistinguishable from a transport failure, and would make a missing sandbox
indistinguishable from a broken server. *Rejected alternative:* mapping
conflict to 409 for HTTP tidiness — it reads better in a log and destroys the
only distinction the gate actually tests.

**The reason strings above are the engine's, not this document's.** They are
tabulated because §2.4 promises the "full refusal payload verbatim", and a
verbatim promise over an invented vocabulary is a lie. Each is grounded:
`key_expired` (`opstore/src/opstore/errors.py`:27) is reserved for a key
presented **after** the 30-day horizon and is never used for a first-sight
freshness failure; `key_timestamp_skew` (`errors.py`:39,
`mcp/idempotency.py`:180-185) is the first-sight UUIDv7 skew refusal;
`key_payload_mismatch` (`errors.py`:31) is the opstore's same-key-different-
payload refusal, which is the one REST raises. MCP's own reason for that
condition is the differently-named `idempotency_key_reuse`
(`mcp/idempotency.py`:194); the two transports keep their own strings and
neither is rewritten to match the other.

**TIGHTENING (binds G5.15).** The five-value `StaleReason` vocabulary is closed
and must not be collapsed. `malformed` — which no gate clause names — is
surfaced with its own reason, never folded into `mismatched`, never degraded to
a generic 400. A test enumerates all five and asserts five distinct reasons
reach the DOM.

**TIGHTENING (binds G5.7).** `addressing_error` and `stale_selection` are
distinct statuses with distinct reasons. Flattening a focus miss into
`stale_selection` would make the mask-domain clause untestable.

### 2.5 REST idempotency

G5.19 requires REST mutation idempotency tested **independently of
MCP-over-HTTP**. Both paths share one HMAC-bound normalized-key store
(timestamp-prefixed, project keyring per `architecture.md` §3.5, 30-day
horizon, 7-day tombstone margin). They differ only in key derivation: REST
follows the **header rule**, on the route set §2.3 enumerates and no other; MCP
keeps its own derivation (session identity + canonical request id, honouring
`_meta["hephaestus.dev/idempotency-key"]`) and explicitly does not follow the
header rule. Two derivations, one store, two independent test lanes.

| Situation | Response |
|---|---|
| `Idempotency-Key` absent on a **key-required** route (§2.3, first table) | **400** `idempotency_key_required`, **no execution** |
| `Idempotency-Key` absent on a **session-control** route (§2.3, second table) | proceed; the header is not required there and a supplied one is ignored |
| present but not a UUIDv7 | **400** `idempotency_key_malformed`, no execution |
| first sight, UUIDv7 timestamp outside ±`FRESHNESS_SKEW_S = 300` | **409** `key_timestamp_skew`, **no execution** |
| recognized key inside the 30-day horizon | replay; **freshness is not re-checked** |
| same key, different payload | **409** `key_payload_mismatch` |
| key presented after the 30-day horizon | **409** `key_expired`, no execution |

The freshness asymmetry is a documented trap, written in prose so a test author
trips over it here instead of in CI: **replay tests must not re-assert
freshness.** The two expiry-shaped reasons are likewise not interchangeable:
first-sight skew is `key_timestamp_skew` and post-horizon presentation is
`key_expired`, which is the split the engine already makes (§2.4).

**TIGHTENING (binds G5.19, key derivation).** The key is **payload-
independent**, exactly as MCP's is:

> raw id = `(WorkspacePrincipal token/route identity, Idempotency-Key header
> value)`, carried as `Invocation.entry_id` so that `Invocation.op_id` stays
> **derived** rather than assigned. The canonical JSON body goes only into the
> separate `payload_hash(...)` digest (`mcp/idempotency.py`:137-153) and
> **never into the key**.

WHY, and this is a correctness point rather than a tidiness one: an earlier
draft derived the key from `(project keyring HMAC, route, canonical JSON body)`
and called it "the `op_id` handed to `Invocation`". Both halves were wrong.
`Invocation.op_id` is a `@property` over `session_id|entry_id|ordinal|
provider_call_id` (`dispatch.py`:246-273) and cannot be handed anything — a
REST caller supplies `entry_id` and the property does the rest. And folding the
body into the key makes `key_payload_mismatch` **structurally unreachable**: two
different payloads under one header value would compute two different keys and
both would execute as first sights, so the row above it could never fire and
the lost-response guarantee it protects would be silently absent. Separating
key from payload digest is what makes the mismatch detectable, and it is what
makes the REST lane "identical in kind" to MCP's rather than merely similar in
prose.

Payload hashing is **byte-faithful**: no Unicode normalization
(NFC ≠ NFD), and unpaired surrogates are refused as `invalid_unicode_scalar`
*before* sizing and hashing. The HTTP layer parses request bodies as bytes and
validates scalars itself; it never lets a JSON runtime substitute U+FFFD, which
would silently break the Stage 3 parity suite.

**TIGHTENING (binds G5.19, the unspecified REST reconciliation shape).**
`tool_schema.md` pins two transport-specific shapes — MCP same-id retry replays
`{applied: true, …}`; a Pi-bridge retry of a committed edit reports
`{applied: false, conflict:{current_hash}}`. REST is a **third transport with
no pinned shape**, so:

> A recognized REST key on a committed mutation **replays the stored response
> body byte-for-byte**, with envelope field `"replayed": true` (normative) and
> response header `Idempotency-Replayed: true` (advisory). It does **not**
> degrade to the conflict shape.

WHY: the bridge's conflict shape exists because the retrying principal is a
*model* that must be told a live hash it does not hold. A REST replay is the
same operator client re-sending its own committed call; handing it a conflict
for its own success would be a lie, and would make a lost-response recovery
indistinguishable from a genuine race. The two families that return a
discriminated result rather than a bare success (`edit_part`/`write_part` →
`conflict`; project-check → `already_exists` / `conflict(kind="stale_hash")`)
are unaffected: their discriminated result *is* the stored response and replays
as such. This shape is added to the Stage 3 transport-parity suite as a third
lane.

### 2.6 Two artifact surfaces, two authorizations

`read_artifact` is a *model-facing tool* whose `ref` is a capability scoped to
an authorized Pi session, and it refuses binary artifacts outright ("binary
artifacts return metadata and must be consumed by their dedicated
render/export path"). The browser is neither a Pi session nor satisfied by
metadata. Hence two routes and one extraction.

**Text pager — `GET /artifacts/{ref}/text?offset_bytes=`.** The UTF-8 boundary
contract of `cad_ops/_artifacts.py` is **extracted** into a shared function
(`core.artifacts.page_text(blob, offset_bytes, max_bytes)`) called by both the
tool and this route. Mission rule 6 forbids reimplementation and G5.8's word
"losslessly" makes any divergence a gate failure. The contract, restated only
so a reviewer can check the route against it: page clamped to
`[1, READ_ARTIFACT_PAGE_MAX = 49152]`; a code point is never split; the end
walks back to a boundary and extends by one code point when that would
otherwise return nothing, so a cursor always progresses; a single oversized
line is supported; `next_offset_bytes` is boundary-aligned; an offset that is
neither `0`, nor `total_bytes`, nor an exact code-point boundary returns
`invalid_utf8_offset` **without normalizing it**. This is the route the
oversized `mask_legend_ref` pages through, and the route the conflict dialog
continues from (§9.3).

**Binary bytes — `GET /artifacts/{ref}/bytes`.** Serves the exact stored bytes.
`Content-Type` from artifact kind; `ETag: <ref>` and `Cache-Control: public,
max-age=31536000, immutable`, which are honest because refs are
content-addressed.

**TIGHTENING (binds §15.17's refusal, which was otherwise decorative).** The
route is closed **by enumeration, not by set membership**. It serves exactly:

```
build, build-checkpoint, render, gltf,
selection-solid, selection-face, selection-edge, selection-preview,
selection-crop
```

Every other kind is a **404 `unknown_artifact_kind_for_route`**, and `export`
is named explicitly as the kind that is refused. A pytest submits an `export`
ref to the route and asserts the refusal.

WHY this is not pedantry: an earlier draft scoped the route to
`BINARY_ARTIFACT_KINDS`, and `export` is a member of that frozenset in the
shipped code (`cad_ops/_artifacts.py`:22-34). Any bearer-holding browser could
therefore have fetched export bytes from the workspace, which would have made
§15.17's "no export path" a statement about which buttons exist rather than a
statement about what the server will serve. A refusal that a route quietly
contradicts is worse than no refusal, because a reader stops looking.
`selection-crop` (§12.5) is on the list because Stage 5 mints it; there is no
`selection-pass` kind — the three pass layers are `selection-solid`,
`selection-face`, `selection-edge`.

**TIGHTENING (binds G5.10).** This route performs **no image transformation** —
no re-encode, no resample, no colour-profile insertion, no compression change.
The palette bijection (`id_to_rgb`, 24-bit big-endian `n+1`,
`BACKGROUND_RGB = (0,0,0)` never a valid occurrence colour) survives only if
the bytes are the `encode_png` bytes. Any pixel assertion decodes the
**downloaded bytes**, never a canvas readback, and the workspace never displays
a pass PNG through a scaled `<img>` (§12.2: passes are fetched and decoded as
masks by the test; they are not a visual layer).

Authorization for both is `WorkspacePrincipal` + reachability from the open
project's opstore (§2.2) — a different model from the session-scoped tool
capability, said out loud because G5.8 forces exactly that divergence.

### 2.7 The live event stream

`GET /events` upgrades to a WebSocket. The client sends
`{"subscribe": {"sessions": [...], "runs": [...]}}`; the server registers a
queue via the existing `EventPump` client API and emits the **normalized public
vocabulary only** — `text_delta, thought, tool_call, tool_result, image,
question, answer, audit, progress, terminal`. Bridge frames are never surfaced.
Wire shape is the Python-side shape verbatim — `{run_id, seq, kind,
tool_call_id?, payload?}` — plus exactly one envelope field, `session_id`, so a
multi-session panel can route without inspecting payloads. **No web-specific
event kind is minted and no field is added to `HephaestusEvent`.**

**DECISION (binds G4.8, second trap).** A browser client registers as a
**non-durable observer**. It gets the same 1024-slot `PerClientQueue` bound and
the same coalescing of `progress` (the only `DROPPABLE_KINDS` member), but it
**never participates in `_backpressure_cancel`**. On overflow the server closes
that socket with close code `4409` / reason `resync_required` and drops the
client; it does **not** cancel the run.

WHY, and this is the whole justification: `EventPump`'s durable-overflow policy
cancels the affected *run*. A stalled browser tab would otherwise kill an
agent's work — an unacceptable coupling between a UI's frame budget and a
design's progress. The alternative, making the web client droppable, is
illegal: only `progress` is droppable, and `audit` / `tool_call` /
`tool_result` / `question` / `answer` / `terminal` are never dropped.
Disconnect-and-resync is the only policy that is both run-preserving and
lossless for durable kinds.

**Reconnection, and the two identity namespaces.** The client reconnects with
`{"resume": {"session_id": …, "after": {"run_id": …, "seq": …}}}` and replays
whatever the live buffer still holds.

**TIGHTENING (binds G4.9, G4.11) — history does not close a live gap.** An
earlier draft had the client re-read missing events through the history
snapshot API and "dedupe on `(run_id, seq)`". That cannot work, and the reason
is a durable fact the sidecar does not record:

- Live events carry the **real run id** and a **run-monotonic** seq minted by
  `active.nextSeq()` (`agent/src/session/live.ts`:68-80, `main.ts`:109-124).
- Historical events do not. `main.ts`:344 calls `pageHistory(entries,
  sessionId, …)`, passing the **session id** into the parameter `history.ts`
  names `runId`, and `normalizeEntries` restarts `seq` at 0 for the whole
  session (`history.ts`:72-78). A historical event's identity is therefore
  `(session_id, session-global ordinal)`.

The same logical event has two disjoint identities on the two surfaces. A
dedupe on `(run_id, seq)` would never match, so a "refilled" gap would render
every event twice.

The spec takes the honest branch rather than pricing an engine change:

> **History is used for pre-attach backfill only, never to close a live gap.**
> On attach or reopen, the client pages history and renders it as the
> historical prefix. Once the live socket is attached, a `4409` resync
> reconnects, replays what the live buffer still holds, and renders anything
> the buffer dropped as a **labelled break** (§7.4's `resyncing` state). The
> break is never healed from history.

*Rejected alternative:* carrying the originating run id and a per-run seq
through Pi session entries so `normalizeEntries` could reconstruct them
(`agent/src/session/history.ts`, `main.ts`:344). It is the better long-run
shape and it is a real engine change — it re-baselines G4.11's archive, since
it changes what the archive is an archive *of*. No G4/G5 clause asks for a
gap-healing resync, so buying that re-baseline here would be scope this stage
did not earn. It is named in §21 as a risk, not smuggled in as an assumption.

**Honest cost of a resync, stated as the surface actually supports it.** An
earlier draft claimed "durable kinds are not lost". That is false, and it is
the kind of overclaim §4.4 and §15 police elsewhere. `normalizeEntries` emits
exactly six kinds — `audit`, `text_delta`, `thought`, `tool_call`,
`tool_result`, `image` (metadata only) — so of the ten normalized kinds:

| Kind | Reconstructible from history? |
|---|---|
| `text_delta`, `thought`, `tool_call`, `tool_result`, `audit` | yes |
| `image` | **metadata only** — `history.ts`:99-101 emits `{mimeType}`; the base64 `data` that `live.ts`:119-132 carries is not in the archived payload (§7.3) |
| `question`, `answer` | **no** — synthetic, minted only into the live run stream around `py.ask_user` (`main.ts`:105-125) |
| `terminal` | **no** — minted only by the Python pump (`events.py`:264-275) |
| `progress` | **no** — coalesced, the only `DROPPABLE_KINDS` member, never durable |

`question`, `answer`, and `terminal` are on the never-dropped list
(`events.py`:8-11, 63) *within a live run* — that is a statement about the live
pump's backpressure policy, not a claim that history can replay them. A resync
gap spanning one of them is rendered as the labelled break above and is **not**
silently healed. The owning client of a run (the CLI, or the tab that issued
the prompt) keeps the existing durable semantics; only observers take the
lossy-but-labelled channel.

**`ask_user` with two clients attached.** The question broadcasts to every
attached client. `POST /sessions/{id}/answer` is idempotent on the question id
and **the first answer wins**: the run resumes, every client receives the
`answer` event, and each widget disables itself with
`data-answered-by="self"|"other"`. Both the CLI's numbered prompt and the web
widget may answer; neither is privileged. Inventing a web-side lock over a
suspended question would be a second session-ownership mechanism.

### 2.8 History, threading, and event identity

`GET /sessions/{id}/history?cursor=` is a **passthrough** of
`BridgeRuntime.history_page`. The opaque base64url cursor is forwarded and
returned unmodified.

**TIGHTENING (binds G4.9).** The route exposes **no page-size parameter**.
`HISTORY_PAGE_SIZE = 250` lives in `agent/src/session/history.ts`, and page 1
freezes a high-water mark; a client-selectable page size would break both
restart-stability and the frozen-mark guarantee. "Multi-page" therefore means
the fixture transcript exceeds 250 normalized events, which §14 makes a fixture
requirement.

**TIGHTENING (binds G4.11) — what "event ID" names, and in which namespace.**
There is no field named "event ID", and there is no *single* identity: the two
surfaces mint two, and this spec names both rather than asserting a shared one
that does not exist.

| Surface | Identity | Serialized as | Minted by |
|---|---|---|---|
| Live stream | `(run_id, seq)` — run-scoped, run-monotonic | `"<run_id>#<seq>"` | `active.nextSeq()`, `live.ts`:68-80 |
| History page | `(session_id, ordinal)` — session-scoped, restarts at 0 per session | `"<session_id>@<ordinal>"` | `normalizeEntries`, `history.ts`:72-78 |

**The two are not comparable and are never merged.** DOM attributes carry
whichever one the event actually has, distinguished by their separator, so a
test reading `data-event-id` can tell a live chip from a historical one without
a second attribute. No third identity is invented, and neither existing one is
rewritten to look like the other.

**G4.11's archive is the historical one.** The gate reopens a project and
matches the previously archived event IDs, so the archive is over
`(session_id, ordinal)` pairs — the identities the reopened transcript actually
emits. Archiving `(run_id, seq)` would have archived identities the reopened
panel never produces, and the assertion would have been vacuous or impossible
depending on how the comparison was written.

`history.ts` already guarantees identical entries yield identical events and
seq numbers; Stage 4 commits the first *archive* of that guarantee —
a golden family `tests/stage4/goldens/events/<fixture>.jsonl` of normalized
event JSON with a provenance sidecar naming the sidecar version. Churn policy
matches render goldens: a re-baseline is its own PR carrying the normalization
change that caused it. The e2e asserts the reopened transcript's IDs equal the
archive **across a sidecar restart**, because restart-stability is the property
the archive exists to defend.

**NEW WORK (binds G4.10) — parent/child threading.** `HephaestusEvent` carries
no parent linkage, `history.page` is per-session, and a quick-edit child is a
separate `session_id` with its own Pi JSONL; `QuickEditContext.parent_session_id`
exists in memory and is persisted nowhere. Threading is therefore recorded
**outside** the event stream, durably in `state.db`, at the two sites that
already create the relationship — on the `tp_delegations` precedent:

```
tp_session_edges(child_session_id PK, parent_session_id, kind, origin, created_at)
kind ∈ ("quick_edit", "delegation")
origin: quick_edit → {part, source_artifact_ref, selection_id, provenance,
                      crop_artifact_ref}
        delegation → {delegation_ref, parent_run_id, child_run_id}
```

Written by `SessionService.spawn_quick_edit` and by the delegation WAL's
`PREPARED` transition. `GET /sessions/{id}/thread` returns the transitive tree
rooted at `id`. **The event vocabulary is untouched and Pi JSONL is never the
source of truth for the edge** (mission rule 6, `architecture.md` §4.1).
Reopening reconstructs threading from the edge table and pages each session's
history independently.

Honest limit: **an edge created before this table exists cannot be recovered.**
Pre-existing transcripts reopen flat, and the UI says so
(`data-thread-state="unlinked"`) rather than guessing a parent.

### 2.9 Git projection

**NEW WORK.** No git machinery exists in `core/` or `server/` today;
`architecture.md` §3.5 pins the semantics and nothing implements them. Stage 5
adds one narrow read-mostly module, `server/http/git_projection.py`, shelling
to `git` in the project root with a **fixed argv, never a shell string**:

- `status --porcelain=v2` → `{dirty: [{path, part?, index, worktree}], clean,
  head, branch}`. Dirtiness is a fact about `parts/*.py` in the working tree.
- `log --follow -- parts/<part>.py` → the version list.
- `diff` between two revisions for one part, bounded to the `text_result` caps
  (51200 bytes / 2000 lines) with an explicit truncation marker; never silently
  cut.
- `tag -l`, and annotated tag creation (§13.2).

Refusals: no commit, push, checkout, reset, branch, stash, or merge from the
workspace. It can *see* history and *mark* a publication; it cannot rewrite the
human's repository. A dirty tree is reported, never cleaned.

---

## 3. `web/` — stack

Binding by convention (named in `repo_conventions.md` and `architecture.md` §6,
not in gate text) and treated as fixed: **TypeScript (strict) + React 18 +
Vite**, pnpm workspace; **Monaco** for script and diff; **three.js** for the
viewport; **GLTF/GLB** as the geometry wire format; **Playwright** for
`pnpm test:e2e`, which is the literal gate command. CI runs eslint and
`tsc --noEmit`.

Decisions the gates leave open:

| Decision | Choice | WHY / rejected |
|---|---|---|
| Server state | TanStack Query | Server state is almost entirely content-addressed and cacheable **by ref** (§2.6); refetch/invalidate is the whole problem. |
| Workspace state | one module over `useSyncExternalStore`, no state library | The pin must have exactly **one** authority (§4.5) and must be URL-serializable, which is a flat record, not a reducer ceremony. *Rejected:* Zustand and Redux Toolkit — a dependency whose only output is a store this small; and bare per-component `useState`, which cannot hold a single pin authority. |
| Styling | CSS Modules + a design-token file | `docs/README.md` precedent: a dependency whose only output is the input with CSS on it earns nothing. A utility framework also complicates the `data-*` testability contract. *Rejected:* Tailwind. |
| Component library | None | Every component here is a panel, a chip, or a canvas. *Rejected:* any library, and any icon package beyond an inline SVG sprite — the bundle ships in a wheel and its weight is the operator's download. |
| Router | None; hand-rolled URL state sync | One route (§4.5). A router would exist only to parse a query string. |
| Bundle delivery | built assets ship inside the wheel, served by `--web` from `importlib.resources` | The packaged-sidecar precedent. Vite's dev server is a development convenience proxying `/api` to a running `heph serve --web`. `@autonome/hephaestus-web` stays reserved and unpublished. |
| Accessibility | a stated floor, not a gap | Keyboard reachability for every control that is not the viewport canvas; visible focus rings; `aria-live="polite"` on run-terminal transitions; **no colour-only status encoding** — every badge carries a glyph and a label. A testability contract this specific (§7.2) with no accessibility story would be an embarrassing asymmetry. |

**Clean-room hygiene, inherited verbatim:** no "Smith" or "Arche" in
identifiers, packages, filenames, or copy; the visual language may differ and
here deliberately does; and **no test asserts the reference product's message
text or UX copy** — assertions are on fields and information content. All
workspace copy is invented and lives in one module (`web/src/copy.ts`) so a
reviewer can audit it in one file.

---

## 4. Information architecture

### 4.1 The shell

```
┌──────────────────────────────────────────────────────────────────────────┐
│ HEADER  project · branch · HEAD  |  ARTIFACT PIN  |  build state | token  │
├────────────┬────────────────────────────────────┬────────────────────────┤
│   RAIL     │              STAGE                 │        STREAM          │
│   280px    │              1fr                   │        420px           │
│  parts     │  ┌ tabs: Viewport | Script | Diff ┐ │  session tabs (nested) │
│  tree      │  │  three.js canvas               │ │  ─────────────────     │
│  git dirty │  │  view cube ▸ top-right         │ │  event log             │
│  versions  │  │  grid readout ▸ bottom-left    │ │  tool chips            │
│            │  │  selection popover ▸ anchored  │ │  thought sections      │
│            │  │  measure HUD ▸ bottom-centre   │ │  images                │
│            │  └────────────────────────────────┘ │  ask_user widget       │
│            ├────────────────────────────────────┤ │  ─────────────────    │
│            │  INSPECTOR (drawer, resizable)     │ │  composer             │
│            │  Results | Properties | Provenance │ │                       │
│            │  Checks  | DFM                     │ │                       │
└────────────┴────────────────────────────────────┴────────────────────────┘
```

- **HEADER** carries the two facts that make provenance legible at a glance:
  the **artifact pin** (§12.1) and the **build-state chip** (`current` /
  `preview` / `stale` / `failed`). When the pin is not the current build the
  header is visibly marked and every panel below inherits that marking. This is
  the most important element in the document, because G5.5/G5.6 are exactly the
  case where a user must not be able to forget which build they are looking at.
- **RAIL** is the project: part tree, inline git dirty markers (§13.1), and the
  selected part's version list.
- **STAGE** is geometry, with Script and Diff as *tabs over the same region*, so
  the viewport is the default and text is the deviation — the inverse of an
  IDE, on purpose. This is a CAD workspace.
- **INSPECTOR** is a bottom drawer of the Stage rather than a third column: its
  content is *about the thing in the Stage*, and losing that spatial relation
  costs more than the vertical pixels.
- **STREAM** is a full-height peer column, collapsible but not hidden by
  default. Giving the agent a column rather than a bottom drawer is the
  "collaborator, not console" claim cashed out in layout.

Breakpoints: below 1280px the Stream collapses to a docked strip with an unread
count; below 1024px the Rail collapses to an overlay. There is no phone layout
and none is attempted.

### 4.2 Panel inventory (closed for Stage 4/5)

`ProjectTree`, `GitDirty`, `VersionList`, `Viewport`, `ViewCube`, `GridReadout`,
`ExplodeSlider`, `SectionControl`, `SelectionPopover`, `MeasureHUD`,
`ScriptEditor`, `DiffView`, `ResultsPanel`, `PropertiesPanel`,
`ProvenancePanel`, `ChecksPanel`, `DfmPanel`, `ParamSliders`, `StreamPanel`,
`ToolChip`, `ThoughtSection`, `EventImage`, `AskUserWidget`, `Composer`,
`ConflictDialog`, `TagDialog`, `ArtifactPin`, `Fact`.

A panel not on this list is not Stage 4/5 work (§18).

### 4.3 The provenance spine

One continuous path; every affordance below is a station on it:

```
artifact pin (HEADER)
  → viewport GLTF bound to that ref
    → raycast hit (client, a HINT)
      → POST /selection/resolve (server validates)
        → SelectionPopover (kind, label, tag?, line?)
          → ProvenancePanel (source_artifact_ref, table ref, bundle ref, crop)
            → "Ask about this" → quick-edit spawn
              → child session tab in STREAM, threaded under the parent
```

No station may be short-circuited by client knowledge. The popover renders only
what the server returned.

### 4.4 Rendering a legitimately weak provenance answer

`architecture.md` §3.1 caps what provenance may claim: resolution lands on the
**tag** if the picked topology is tagged, else on the owning solid's
binding/boolean statement; boolean **result** faces are not attributed to
operand statements, because OCCT history tracking is out of scope. G5 asserts
only the strong case. How the weak case *looks* is unspecified and is therefore
a spec obligation.

The popover has exactly three shapes, each a first-class designed state — not a
strong state with fields missing:

| State | Renders | `data-provenance-state` |
|---|---|---|
| **Tagged** | `tread_top` · face of `stair_tread` · `parts/stair.py:41` | `tagged` |
| **Owned** | face of solid `stair_tread`, created by `parts/stair.py:33` (`cut`) — *this face was produced by a boolean; Hephaestus does not attribute it to an operand statement* | `owned` |
| **Unattributed** | face #217 of solid `stair_tread` — *no statement attribution available* | `unattributed` |

The italic sentences are the design point. A weak answer that *says why it is
weak* reads as instrument honesty; the same answer with a blank field reads as
a bug. This mirrors `KINEMATICS.md`'s `holds_at_samples` discipline: never claim
more than the machinery knows.

**One state is reached for a different reason and must say so.** A face that
*is* tagged, whose pinned build's source map is no longer stored, renders
`owned` with the explicit reason *"A's source map is no longer stored"* — never
the generic `unattributed` copy. "The machinery cannot attribute this face" and
"the attribution existed and was not retained" are different facts, and a
popover that renders them identically is claiming the first while the second is
true. §12.4 makes retaining that source map named new work precisely so this
state is rare rather than routine.

### 4.5 Workspace state (closed) and URL

```
WorkspaceState {
  part: string | null
  artifact_ref: string | null      // the pin — sticky, never auto-advanced
  pin_mode: "current" | "pinned"
  view: "iso" | "+X" | … | "az<d>_el<d>"
  channel_overlay: "none" | "section"
  explode_t: number                // 0..1
  section_plane: string | null     // "[+-]AXIS@OFFSET"
  selection: {selection_id, kind, bundle_ref} | null
  measure: {a?, b?} | null
  stage_tab: "viewport" | "script" | "diff"
  inspector_tab: "results" | "properties" | "provenance" | "checks" | "dfm"
  focus: string | null
  session: string | null
}
```

Serialized as `/#/p/{part}?ref=…&view=iso&t=0.0&sec=…&sel=…&tab=viewport&s=…`.

**DECISION:** no `/session/{uuid}` route. That URL shape is observed evidence
from the reference product and is a false friend here — `architecture.md` §1
replaces the session/version model with git, so a session is not an addressable
workspace object. Sessions are tabs inside the Stream, addressed by `?s=`.

**TIGHTENING (binds G5.6).** `artifact_ref` is first-class, sticky workspace
state carried by every inspection, selection, crop, and measurement. Publishing
a new build **never** advances a pin whose `pin_mode` is `"pinned"`. The header
offers "Follow current" as an explicit one-click action that states what it will
discard. A workspace that auto-refreshed to latest would silently fall back to
current geometry, which `architecture.md` §4.4 forbids outright.

### 4.6 The `<Fact>` primitive

```tsx
<Fact source="build.geometry_count" value={n} />
// → <span data-source="build.geometry_count" data-value="12">12</span>
```

This is what makes §1's `no-derived-fact` lint mechanical, and it gives the e2e
one uniform selector for DOM-vs-JSON comparison instead of per-panel text
scraping.

---

## 5. Viewport and the render division of labour

### 5.1 Geometry delivery

The viewport loads `GET /artifacts/{ref}/gltf` for the **pinned** build. The GLB
is the existing `core/render/gltf.py` output: one **mesh per solid** (mesh count
equals solid count — a G1 assertion), one **primitive per face** inside its
solid's mesh, `extras` carrying selection IDs and descriptors, and
`asset.extras` carrying `selection_bundle_ref`, `source_artifact_ref`,
`selection_table_ref`. Model, browser raycast, and tests therefore share one
namespace with no new format.

**NEW WORK (§19) — the route has no producer today, and an unlinked GLB is not
an acceptable fallback.** `export_gltf` has **no production caller** anywhere in
`core/` or `server/` (tests only), no `gltf` artifact is ever published, and its
signature makes `bundle_ref`, `source_artifact_ref`, `selection_table_ref`, and
a `SelectionCatalog` **mandatory** (`gltf.py`:84-92). Those refs exist only
after an `inspect_part(channel="mask", mask_mode="selection")` has minted a
bundle for that exact build. So for a freshly built — or pinned but never
inspected — artifact, the only GLB the server could produce is an *unlinked*
one, which §12.3 requires be **rejected**. The viewport's first station would be
pickable but unresolvable: the worst possible failure, because it looks like it
works.

The route therefore does the minting rather than hoping it already happened:

> `GET /artifacts/{ref}/gltf` **resolves, or publishes on demand, the selection
> bundle for that exact build ref** — re-tessellating from the stored BREP
> (`executor/worker.py`:599-600, `FINAL_BREP`) — and publishes the GLB under
> the existing `gltf` artifact kind. It **never returns an unlinked GLB**; if
> the bundle cannot be minted the route refuses rather than degrading.

Publishing under a real artifact kind is also what makes §2.6's `ETag: <ref>` /
`immutable` caching claim honest: the ref is content-addressed because there is
a stored artifact behind it, not because the route says so.

**No glTF extension is introduced.** Everything needed already rides in
`extras`, and an extension would drag a new artifact into the
`tool_schema.md` ↔ JSON-Schema ↔ TypeBox ↔ MCP drift suite for no capability.

**NEW WORK (§19) — the one `extras` addition is `explode_offset`.** An earlier
draft said the GLB ships a per-solid unit `explode_axis` and a scalar
`explode_scale`, and that "the server already computes both". Neither claim
survives contact with the code: `explode_silhouette` returns an `int` pixel
count (`channels.py`:706-722), the displacement lives in the module-private
`_explode_offset` and is **not normalized** (`channels.py`:553-557), and
`EXPLODE_SCALE` is a single **global** constant `= 1.0` (`channels.py`:111).
There is no unit vector and no per-solid scale anywhere in the repo, and
`core/render/gltf.py` emits no explode data at all. So this is new emission
work, and it is defined normatively here:

> `core/render/gltf.py` emits, per mesh, `extras.explode_offset` = the float3
> `(solid.centroid() − scene.centroid()) * EXPLODE_SCALE` — i.e.
> `_explode_offset(scene, solid, t=1.0)`, exported from `channels.py` for this
> purpose rather than reimplemented.

**Invariant, asserted by a server-side pytest:** for every solid and every `t`,
the client's `explode_offset · t` is byte-equivalent to
`_explode_offset(scene, solid, t)`. Without that test the viewport and
`heph render --channel explode` can drift silently, and the drift would first
appear as a golden mismatch in an unrelated stage.

### 5.2 Explode

The slider drives `explode_t ∈ [0,1]`; the client translates each solid's node
by `explode_offset · t`. Camera framing is not re-fit during the drag (the
server frames once at `t=1`; the client mirrors that by framing once and
holding). G4.6 reads pairwise centroid distances back out of the scene graph
and demands a strict increase over **all** pairs, so a single-solid fixture
makes the clause vacuous: the fixture carries **≥3 solids** (§14).

**Why a displacement vector and not a unit axis plus a scalar — this is a gate
correctness point, not a style preference.** The server's transform is a
**homothety** about the assembly centroid: each solid moves a distance
proportional to `|c_i − C|`. A unit axis with the only `explode_scale` that
exists (the global `1.0`) moves **every solid the same distance** along
different directions, which is a different transform. It does not guarantee a
strict increase in centroid distance over *all* pairs — two solids at very
different radii can close on each other — so it can fail G4.6 outright, and it
puts the viewport visibly out of agreement with `heph render --channel explode`
and with the section/explode golden family. Shipping the offset keeps the
magnitude a **server** number, which §1's closed list requires (the client may
not compute distances), and makes G4.6 hold by the same construction the G1
explode gate already relies on.

*Rejected alternative:* shipping `axis_i = normalize(c_i − C)` with a per-solid
`explode_scale_i = |c_i − C| · EXPLODE_SCALE`. Mathematically equivalent, and
rejected anyway: it is two numbers where one will do, it invites a reader to
reach for the global `EXPLODE_SCALE` as the scalar, and the normalization is a
geometry operation performed for no reason on a value the server already holds
in the form the client needs.

### 5.3 Section — the rasterizer decision

**DECISION (binds G4.7, and consequently G5.16).** Section renders that any gate
compares against a golden are **server-rendered PNGs**, produced by the existing
`render_channel(..., channel="section")` path with
`section_plane="[+-]AXIS@OFFSET"` and served as artifact bytes. The viewport
displays them as a **section plate** — a fitted image layer in the Stage — with
the plate's `source_artifact_ref` shown in the header.

The client additionally offers a **live clipping preview** using three.js
clipping planes while the plane control is dragged. That preview carries
`data-section-state="preview"`, is **never** golden-compared, and is replaced by
the server plate (`data-section-state="rendered"`) when the drag settles or the
user clicks *Render section*.

WHY: existing goldens are software-llvmpipe/OSMesa renders under a pinned
`(container image, renderer version)` pair at SSIM ≥ 0.995. A headless-Chromium
WebGL render is a **different rasterizer** and will not match them. The
alternative is a new browser-golden family with its own provenance sidecars, its
own re-baseline machinery, and its own platform-tier pinning — a large new
determinism surface bought for one clause. Reusing the server family costs one
image fetch and buys exact continuity with `heph render` and `heph goldens`.

**Consequence, stated so it is not discovered later:** for gated views, `web/`
is a viewer of server pixels. The interactive WebGL render is the *working*
surface; the *evidentiary* surface is server-rendered. That asymmetry is
deliberate and is the honest reading of "no geometry logic in the client".

**Corollary (binds G5.16), scoped precisely.** "A changed golden-region render"
is likewise a server render: after the quick edit's `edit_part` lands and the
part rebuilds, the e2e requests a render of the affected region and compares
against the region golden.

> **No browser screenshot is ever compared against a golden.** The refusal is
> about *golden* comparisons, and only about those: no browser-rendered golden
> family is created, no browser pixels are pinned to a `(container image,
> renderer version)` pair, and no re-baseline machinery is added for a
> rasterizer this repo does not control.

That is the whole of the decision, and it is deliberately **not** the broader
claim "no browser pixel is ever read". The broader claim would leave G4.5 —
"visibility toggle changes the viewport within the target solid's mask region"
— with no legal evidence path at all, since that clause is intrinsically about
*the viewport* and, unlike G4.7, has no server-side substitute to be rehomed
onto. §5.4 states the mechanism it does get. Screenshots remain archived CI
artifacts (G4.12) and Tier 2's rule holds unchanged: the pass/fail signal is
always the scripted assertion, never a human looking at an image.

### 5.4 Visibility

Per-solid visibility toggles live in the Results panel and hide the corresponding
GLTF mesh node — a scene-graph property, not geometry.

**TIGHTENING (binds G4.5) — the named mechanism, stated so the clause is not
left unasserted.** G4.5 is the one pixel clause with no server-side substitute,
so its evidence is a **self-referential delta over viewport pixels**, not a
golden:

1. Fetch the **solid-ID pass PNG** for the pinned build from
   `/artifacts/{ref}/bytes` (§2.6, byte-exact, no transformation) and decode it
   test-side to a mask `M` for the target solid's palette value. The mask is
   never decoded from the viewport, which is lit and antialiased, and the
   workspace itself never displays a pass.
2. Screenshot the viewport **before** and **after** the toggle, in the pinned
   CI image (§14), at the pass's own resolution and camera.
3. Assert on two regions: inside `M`, the fraction of changed pixels is
   **≥ 0.10**; inside a **control region** outside `M` (its complement, minus a
   two-pixel dilation band around `M`'s boundary to absorb antialiasing), the
   fraction of changed pixels is **≤ 0.01**. The dilation band is excluded from
   both, not silently attributed to one.

All three steps run in the **test harness**, never in the workspace. §1's closed
list bars the *client* from decoding a shaded viewport frame or a palette, and
that bar is untouched: the app ships no pixel reader, and the mask's palette
decode happens in Playwright against downloaded pass bytes.

**This is a delta assertion between two frames from the same rasterizer, not a
pinned-rasterizer golden.** Nothing is compared against a stored image, no
reference pixels are committed, and no `(container image, renderer version)`
pair is pinned for browser output — so it creates **no browser-golden
determinism family**, and §5.3's refusal stands untouched. The thresholds are
loose on purpose: the clause asks whether the toggle changed the right region,
which is a question about *where* the change is, and a tight threshold would be
a claim about the renderer's output that this spec has just refused to make.

WHY this is written out rather than left to the implementer: §5.3's refusal and
this clause were in flat contradiction in an earlier draft — §5.4 asserted over
viewport screenshots while §5.3 and §14 banned browser-screenshot assertions
outright. An implementer following the refusal literally would have left G4.5
unasserted and the clause effectively unmapped, which is exactly the degenerate
pass mission rule 1 exists to close.

### 5.5 View cube, grid readout, stale-but-valid

The view cube drives `view` through the `STANDARD_VIEWS` vocabulary of
`core/render/cameras.py` plus its `az<deg>_el<deg>` grammar, so a view named in
the UI is a view `heph render` can reproduce; free orbit snapshots the nearest
`az/el` into workspace state, keeping every reachable camera nameable. The grid
readout shows camera state and scale — a screen-space fact, never rendered
through `<Fact>`.

During a rebuild the viewport keeps the **last completed** artifact and the
header shows `stale` with the ref it is showing. `architecture.md` §3 already
guarantees a long build never blocks inspection; the UI's job is to express
"stale but valid" rather than to blank the canvas. It never blanks.

---

## 6. Results, properties, checks, DFM

### 6.1 The geometry count

**TIGHTENING (binds G4.2) — what "geometry count" names.** Three plausible
numbers exist: labeled entries in `BuildResult.geometries`, GLTF mesh nodes, and
`kind="solid"` entries in the selection table. The gate says *build-result*
geometry count, so:

> `geometry_count := len(BuildResult.geometries)`, served as an **explicit
> field** by `GET /parts/{part}/build`.

`ResultsPanel` renders exactly one row per `geometries` entry, each carrying
`data-geometry-index`. The e2e reads `geometry_count` **over HTTP** and compares
it to the DOM row count; it does not recount client-side and does not consult
the GLTF. A separate **server-side pytest invariant** asserts the three numbers
agree for the fixture — agreement is an invariant, not this clause, and when it
breaks a Python test fails rather than an e2e.

### 6.2 Properties

**TIGHTENING (binds G4.3) — what "all metadata fields" names.** "All" is a
completeness assertion with no list attached, and the only closed vocabulary
available is the `part.*` loud-metadata contract (`script_contract.md` §5.3,
`part.feature(...)`, and the `part.*` metadata surface). Two assertions, both
required, because either alone has a hole:

1. **DOM ↔ projection.** The e2e asserts **set equality** between
   `PropertiesPanel`'s `data-field` nodes and the keys of
   `GET /parts/{part}/properties`. Containment would be satisfied by rendering
   one field — exactly the degenerate pass mission rule 1 requires be closed.
2. **Projection ↔ contract.** A server-side pytest asserts the projection's key
   set equals the enumerated `part.*` metadata the fixture's script declares.
   Without this, a thin projection would make assertion (1) trivially true.

Draft-level note kept deliberately: if that enumeration proves looser than
assumed, G4.3 needs a different anchor and this section is wrong (§21).

Each row renders through `<Fact source="properties.<key>">`.

### 6.3 Check badges

**TIGHTENING (binds G4.4).** The web client never runs checks.
`GET /parts/{part}/checks` serializes the `CheckReport` through **the same
function** `heph check --json` uses (extracted to `core.checks.report_json` if
it is not already standalone). The e2e compares browser DOM badges against a
subprocess `heph check --json` — one serializer, two callers, no second
implementation, byte-parity asserted on the canonical JSON.

Badge vocabulary is closed and mirrors the report: `pass`, `fail`, `error`,
`not_run`. **`not_run` renders as its own visible state with the words "not
run"** — the rule that silence never reads as a pass is a UI obligation, not
only a tool one.

### 6.4 DFM — the orphaned clause, given a home

The 2026-07-26 ordering amendment struck "e2e covers the DFM toggle surfacing
findings in the web panel" from G6 and deferred it *to* G4/G5, whose verbatim
text does not mention it and may not be edited. It is binding under mission
rule 1, so it lands here as coverage inside `pnpm test:e2e`:

- **`DfmPanel`** renders a `run_dfm` result: `severity_counts` header, findings
  list, `errored_rules`, a `truncated` marker, `process`, pack
  `{name, version, registry, registry_digest}`, `material`, and `resolved_from ∈
  {current, artifact_ref, project_snapshot}` as a visible chip.
- Each finding renders `rule_id`, `severity`, `title`, `message`, `measured`,
  `suggested_bound` + `bound_unit`, `tags`, and **artifact-bound topology
  descriptors** `{kind, solid_id, topology_index, tag}`. G6 pins that findings
  report descriptors "rather than bare mask IDs", so the panel renders the
  descriptor and never the raw integer alone.
- A descriptor is **clickable** and drives the same server resolve path as a
  raycast (§12.3) against the finding's `source_artifact_ref`. A finding on a
  **transient preview** therefore highlights on the preview, and the panel marks
  it `data-dfm-source="preview"` versus `"current"` — G6 explicitly requires
  transient-preview and current-artifact resolution be distinguishable, and the
  panel makes that visible.
- **The "DFM toggle" is two controls, not one.** `[dfm] auto_run` in
  `hephaestus.toml` is a *project setting*, not a per-message flag, so the
  workspace exposes (a) a **Run DFM** action → `POST /parts/{part}/dfm`, and (b)
  a project-settings toggle → `POST /project/config/dfm`. Collapsing them into
  one composer switch would imply a tool argument that does not exist. The e2e
  covers (a) surfacing findings and (b) the setting round-tripping.
- `capability_not_available` (no sandbox) renders as an explicit explanatory
  refusal card, never an empty list. Silence never reads as a pass.

---

## 7. The agent stream

### 7.1 Session tabs and threading

One tab per attached session, nested: an orchestrator, its delegated part
sessions, and a part session's quick-edit children form a three-level tree
rendered as an indented tab list with `data-thread-depth`. The edge source is
`GET /sessions/{id}/thread` (§2.8) — never inference.

Attachment is explicit: opening a part shows its session if one exists; the
"attach" affordance lists live sessions. **A browser tab is a client, never a
lease holder.** While the CLI holds a persistent session's lease, the browser
reads and can prompt *through the owning server* (§2.1), which is the only
reason both surfaces can drive one session at all.

### 7.2 The tool chip contract

A testability contract imposed on the DOM, specified as a component contract
because it constrains component design directly.

```html
<article class="chip"
         data-tool-name="build_part"
         data-status="ok"
         data-event-id="run-a1b2c3d4e5f6#41"
         <!-- live; a historical chip carries "sess-…@41" (§2.8) -->
         data-tool-call-id="…">
  <header>…</header>
  <dl>
    <div data-field="artifact_ref">…</div>
    <div data-field="status">…</div>
    <div data-field="project_snapshot_ref">…</div>
  </dl>
</article>
```

- `data-tool-name` — the canonical tool name from `tool_call.name`.
- `data-status` — closed set **`running | ok | error`**, derived only from
  normalized events: a `tool_call` with no matching `tool_result` is `running`;
  a `tool_result` with `isError` true is `error`, false is `ok`. There is no
  fourth value — a cancelled run's orphan chips stay `running` until the
  `terminal` event marks the *run*, because cancellation is a property of the
  run, not of a chip.
- `data-field` — **one node per schema-required output field or reference that
  is present in the fixture's event payload**, under the predicate below.

**NEW WORK (binds G4.D, and it is an engine change, not a client one).** Only
the **live** normalizer emits `isError`: `live.ts`:114-118 emits
`{toolName, text, isError}`, while `history.ts`:93-102 emits `{toolName, text}`
with no `isError` at all. In a **reopened** transcript — the exact flow G4 gates
— every chip's `isError` is `undefined`, which under the rule above reads as
`false` → `ok`. The panel would state, as fact, that a tool call which failed
succeeded. That is a silently-dropped state and it contradicts this section's
own closing rule. Therefore:

> `normalizeEntries` **must emit `isError` for `tool_result`** — from Pi's
> `toolResult` message, or derived from the serialized result envelope's
> `status` — and that change lands in the engine **before** the G4.11 event
> archive is baselined, so the archive records the corrected shape and is not
> re-baselined a stage later.

**Fallback if the signal proves unrecoverable from Pi entries:** the closed set
gains a fourth, **visible** value `unknown`, rendered with explanatory copy
("this transcript does not record whether the call failed"), used only for
historical chips. That is strictly worse than fixing the normalizer and is
recorded as the fallback rather than the plan — but defaulting a failed call to
`ok` is not an option in either branch.

**TIGHTENING (binds G4.D) — the completeness predicate, over the parsed result
document.** Two defects had to be fixed together here, so the predicate is
restated once, in full, and the earlier gloss is deleted rather than reconciled.

*First, the substrate.* An earlier draft intersected the schema's required
output fields with "the keys actually present in the normalized `tool_result`
payload". That payload has exactly two keys — `toolName` and `text`
(`history.ts`:98, `live.ts`:114-118) — and neither is a schema output field.
The structured result is serialized **inside `text`** as a JSON string
(`agent/src/tools/proxy.ts`:370, `content: [{type: "text", text:
JSON.stringify(payload)}]`). Read literally, the intersection was empty for
every tool, so a chip with **zero** `data-field` nodes satisfied the assertion
— the degenerate pass mission rule 1 requires be closed, dressed as a
mechanical check. It is also why the section's own example chip
(`data-field="artifact_ref"`, `"project_snapshot_ref"`) contradicted its own
predicate: those are keys of the *parsed result*, not of the envelope.

*Second, the form.* The same draft asserted **set equality** and then glossed it
as "a chip rendering extra fields passes". Those are different predicates and a
test author cannot implement both. The gate's phrasing — "one `data-field` node
for every schema-required output field/reference present in its fixture" — is a
**containment** obligation, so containment is what is specified.

> Let `D = JSON.parse(payload.text)`, `K = keys(D)`, `R` = the tool's
> **required** output fields from `schemas/tools/<name>.schema.json` (generated
> from `contract/tools_decl.py`, drift-tested in CI), and `F` = the chip's
> `data-field` values. Two assertions, both required:
>
> 1. **Completeness (containment):** `F ⊇ (R ∪ references(D)) ∩ K`, where
>    `references(D)` is the set of keys in `D` ending in `_ref`. A chip
>    rendering additional fields passes; a chip dropping a present required
>    field or a present ref fails.
> 2. **Groundedness (closure):** every member of `F` is in `K`. A `data-field`
>    node naming a key the payload does not carry fails.
>
> **Contract pinned so the parse is total:** every dispatched tool result
> serializes as a **single canonical-JSON text block** — which it does today
> (`proxy.ts`:370). §16's G4.D row states this predicate and not the equality
> form.

Assertion (1) alone is satisfied by a chip that renders every schema field
whether present or not — placeholder fabrication, which §4.4's honesty
discipline forbids. Assertion (2) is what kills it. Equality would have closed
both holes at once, but it also rejects `project_snapshot_ref` on a tool where
that ref is present-but-not-required — so equality is stricter than the gate,
and mission rule 1 permits tightening an ambiguity, not raising a bar the gate
did not set.

**Named failure mode, visible rather than silent.** If `payload.text` is not
JSON, or the result arrives as multiple content blocks, the chip renders
**plainly degraded**: zero `data-field` nodes, `data-field-state="unparsed"`,
and a stated reason in the chip body. The empty field set is then a *visible
refusal* carrying its cause, not a pass. Without this, the one case where the
predicate is vacuous is also the one case indistinguishable from success.

Bespoke chips exist only where a result has an irreducible visual form:
`build_part` (status + error record + critique), `edit_part`/`write_part`
(diff), `inspect_part` (images + refs), `measure` (value + units), `run_checks`,
`run_dfm`, `check_assembly`, `check_motion`, `set_params`, `read_artifact`,
`delegate_part_agent`, `ask_user`. Everything else is the generic
schema-driven chip. Both satisfy the same attribute contract, so a degraded
fixture never breaks the contract — it renders plainly. **A chip degrades by
omission and names the absent fields; it never fabricates a placeholder value.**

### 7.3 Kinds

- `text_delta` → streamed assistant text.
- `thought` → collapsed `ThoughtSection`, expandable, `data-event-id` present.
- `image` → **live**: decoded from the event's base64 with its `mimeType` and
  shown inline; an oversized or undecodable payload renders a labelled
  placeholder and never throws (the CLI's precedent). This is §0's deficit
  being closed: the images live in the transcript, not only in
  `.heph/agent_images/`. **Historical**: the archived payload is `{mimeType}`
  only (`history.ts`:99-101) — the base64 `data` that `live.ts`:119-132 carries
  is not retained — so a reopened transcript renders a **labelled metadata
  placeholder** stating the mime type and that the bytes are not retained in
  history. Rendering nothing there would read as "the agent produced no image",
  which is false; carrying the bytes into Pi entries would be engine new work
  no G4/G5 clause asks for, and is not taken (§21).
- `question` → `AskUserWidget`. `architecture.md` §4.3 already says the same
  question is a numbered prompt in the CLI, structured content over MCP, and a
  widget in the web. Options render label **and** geometric consequence
  (`_CLARIFICATION_OPTION` requires both). Answering posts
  `POST /sessions/{id}/answer`; first answer wins (§2.7). **Live only**:
  `question` and `answer` are synthetic events minted around `py.ask_user`
  (`main.ts`:105-125) and `normalizeEntries` can never emit them, so a
  **reopened** `AskUserWidget` is rendered from the `ask_user` tool call and
  its tool result — which history does carry — and is marked
  `data-widget-source="tool_result"` and non-interactive. It is not
  reconstructed from `question`/`answer`, because those are not there.
- `answer` → the recorded answer (live only; see above).
- `audit` → a compact line carrying `payload.event`.
- `progress` → a coalesced transient indicator that never accumulates history;
  it is the only droppable kind and treating it as durable in the DOM would
  misrepresent the stream.
- `terminal` → a run-terminal band carrying `{state, terminal_id}`. A
  `backpressure_cancel` reason renders with its own explanatory copy, because a
  user must be able to distinguish "the model stopped" from "the plumbing gave
  up". **Live only**: `terminal` is minted by the Python pump
  (`events.py`:264-275) and never appears in a history page, so a reopened
  transcript shows no terminal band and says so once, in place, rather than
  implying the run is still open.

### 7.4 Stream states

Closed vocabulary on the Stream header: `live`, `reconnecting`, `resyncing`,
`historical`, `detached`. `resyncing` is §2.7's close-and-refill state and is
**visible** — a silent gap in a transcript the user believes is complete is
worse than a labelled one.

---

## 8. Transcript loading

On reopen: `GET /sessions/{id}/thread` for structure, then paged
`GET /sessions/{id}/history` per session with the cursor forwarded verbatim
until `done`. The panel renders progressively and shows a page counter —
"multi-page" is a user-visible fact, not only a test fact.

Rules the client obeys and the e2e checks:

- **Live and historical events are never merged**, because they are not in one
  namespace: live events are keyed `(run_id, seq)` and historical ones
  `(session_id, ordinal)` (§2.8). History renders as the transcript's
  **prefix**, the live stream as its suffix, and the boundary between them is a
  visible seam, not a silent join. Within the live stream, terminal events sort
  last by their `seq = 2**62` minting — a statement about the live stream only,
  since no `terminal` ever appears in a history page (§7.3).
- **Four kinds are unrecoverable from a reopened transcript**, and each renders
  as a named absence rather than as nothing (§2.7's table):
  - **user prompts** — normalization omits them by design; the transcript shows
    the agent's side and **says so once, in place**;
  - **`question` / `answer`** — synthetic and live-only; a reopened
    `AskUserWidget` is rebuilt from the `ask_user` tool call/result (§7.3);
  - **`terminal`** — pump-minted and live-only; no terminal band is shown;
  - **`progress`** — coalesced and never durable, which is the correct
    rendering anyway (§7.3).
  Plus **`image` bytes**: history retains `{mimeType}` only, so a reopened
  image is a labelled metadata placeholder (§7.3). These are honest limits of
  the public event vocabulary and the history surface, not bugs to paper over —
  but they are limits, and an earlier draft's claim that "durable kinds are not
  lost" across a resync overstated all five.
- Threading comes from the edge table; a session with no edge renders at root
  with `data-thread-state="unlinked"` (§2.8).

---

## 9. Stage 5 — editing

### 9.1 Save is a store mutation, never a file write

**TIGHTENING (binds G5.1, G5.20, G5.22).** `architecture.md` §3.5 restricts the
no-lost-write guarantee to cooperating Hephaestus clients using the store API
and explicitly excludes direct filesystem writes. A plain PUT of file bytes
would place the web editor **outside the guarantee the gate demands**.
Therefore:

`PUT /parts/{part}/script` **is** `write_part`: `expected_hash` required, atomic
write, preimage journalled to `.heph/journal/`, snapshot registered, CAS
checked, `snapshot_ref` returned. `PATCH` **is** `edit_part` for targeted edits.
**There is no route that accepts a path and bytes.**

Monaco holds `content_hash` from its last read and sends it as `expected_hash`.
Save is explicit (⌘/Ctrl-S or button); **no autosave, no debounce race** — an
autosaving editor racing an agent would generate conflict storms that teach the
user nothing.

### 9.2 Rebuild on save

Save → `POST /parts/{part}/build` with **no transient params** → the pin
advances only if `pin_mode == "current"`. During the build the viewport holds
the last completed artifact and the header shows `stale` (§5.5). New metrics come
from the rebuilt `BuildResult.metrics`, never from the browser
(`architecture.md` §6). A new build request supersedes an in-flight one through
the dispatch layer; no session cancel is involved.

A `_CLARIFICATION_REQUIRED` dispatch-gate result renders as a first-class panel
state ("this build needs a requirement ledger entry first"), not an error,
because it is not one — no idempotency key is claimed and no geometry ran.

### 9.3 Conflict and the merge prompt

When `write_part` returns a `conflict` block (a **200**, §2.4), `ConflictDialog`
opens carrying, verbatim from the payload: `current_hash`, `current_script`
(the bounded conflict-time snapshot), `current_truncated`,
`current_oversized_line`, `current_oversized_line_offset_bytes`,
`current_next_offset_bytes`, `current_snapshot_ref`, `base_snapshot_ref`,
`attempted_snapshot_ref`.

Three actions and only three: **keep mine** (re-save against `current_hash`),
**take theirs** (discard the local buffer; the dialog shows that the attempted
bytes remain retrievable at `attempted_snapshot_ref`), **open a diff** (Monaco
three-way over `base_snapshot_ref` / `current_snapshot_ref` /
`attempted_snapshot_ref`).

**Named refusal, inherited (binds G5.21).** When `current_truncated` is set the
dialog continues paging from `current_snapshot_ref` at
`current_next_offset_bytes` via `GET /artifacts/{ref}/text` (§2.6). It **never**
calls `read_part`: `tool_schema.md` is explicit — *"`read_part` intentionally
requests newer live state and is never conflict continuation."* The bounded
chunk is the **raw** content, never `numbered_script`, and the 51200-byte /
2000-line cap is measured on both the final UTF-8 text **and** its JSON-escaped
representation. The agent's failed `edit_part` chip in the transcript renders
the same bounded chunk, hash, and paging cursor.

### 9.4 No write is lost

**TIGHTENING (binds G5.20) — who wins.** The gate is symmetric and names no
winner, so the contract is stated symmetrically: **first commit wins; the loser
receives the full conflict payload.** Both directions are tested, because each
puts the loser's bytes in a different place:

| Race outcome | Committed bytes | Overwritten dirty preimage | Rejected contender bytes |
|---|---|---|---|
| Agent commits first | working tree → git | `.heph/journal/` | the editor's bytes at `attempted_snapshot_ref` |
| Editor commits first | working tree → git | `.heph/journal/` | the agent's bytes at `attempted_snapshot_ref` |

**The sharpest requirement in this section:** `attempted_snapshot_ref` requires
registering an immutable snapshot for bytes the server is **about to refuse**.
The REST save path therefore **snapshots first, then validates, then rejects** —
never validates-then-discards. A validate-first implementation passes every
happy-path test and loses a write exactly once, under load, unreproducibly.

Retention: snapshots are held ≥30 days **and** while referenced by a live
operation, conflict, journal, or pin. An expired ref returns `snapshot_expired`
(410) and **must not** fall back to mutable path state; the dialog says the
bytes are gone rather than showing different bytes. Recovery from
`.heph/journal/` is an operator action, not an automated one, and the dialog
links the journal path rather than performing it.

Lock order is contractual and unchanged: project-config → check-set → lexical
part locks; never wait on an earlier lock while holding a later one.

---

## 10. Param sliders

Generated from the script's `PARAMS` with `Param(default, min, max, step)`
bounds.

**TIGHTENING (binds G5.2).** A slider commits through **`set_params`** (a
persisted override carrying `expected_state_hash`), followed by a **default
`build_part` with no transient overrides**. It does **not** send transient
`params` to `build_part`. Transient overrides always return `current=false` and
mint a *preview* artifact; a slider wired that way would move the picture and
never move the design — a silent, extremely plausible failure. `groove_count` is
`Param(5, min=2, max=10)`, an integer param, so its control is a stepped slider
with an integer numeric input beside it.

A stale `expected_state_hash` returns a **result** with a conflict block (not an
error, §2.4); the panel re-reads and re-offers. Scope defaults to **part**;
project-scope `set_params` is orchestrator-only, and while the web principal is
orchestrator-equivalent (§2.2), project scope is a distinct explicit control
rather than a default — a UI-honesty rule, not an authz one.

**TIGHTENING (binds G5.3) — "rejected inline" means the *server* rejected it.**
The client does **not** clamp. It sends the value; `set_params` is
all-or-nothing and returns `rejected[]` naming **every** offender and the
violated bound; the panel renders those entries verbatim beside their controls
and applies nothing. Client-side clamping would diverge from the all-or-nothing
contract and would make the clause untestable — a UI that cannot express an
invalid value cannot demonstrate the engine's refusal.

Live rebuild is debounced 300 ms **on release**, not during drag.

---

## 11. Measure mode

Click two features → two server-validated selections (§12.3) → one `measure`
call → `{value, units, detail, resolved_artifact_refs[]}` in the HUD and in
Results. Kinds offered are the tool's own vocabulary — `distance`, `clearance`,
`interference`, `bbox`, `volume`, `mass` — with no synthesis. The HUD shows
`resolved_artifact_refs`, so a measurement taken against a pinned artifact is
visibly a measurement *of that artifact*.

Measure is disabled, with a stated reason, when the pin is a failed build's
last-good checkpoint: the measurement's provenance would then differ from the
visible header state, and a readout that quietly means something else is worse
than an unavailable one.

---

## 12. Selection, provenance, quick edit

### 12.1 The pin

Every inspection, selection, crop, and measurement carries the pinned
`artifact_ref`. `POST /parts/{part}/inspect` always sends it explicitly.
`artifact_ref` and `last_good` are mutually exclusive in the canonical schema
and the client honours that. A "refresh" that dropped the ref would silently
fall back to current geometry, which `architecture.md` §4.4 forbids.

### 12.2 What the client does and does not do with passes

The client raycasts the **GLTF**. It never decodes a pass PNG for interaction:
passes are artifact-only and non-antialiased, and exist so that machines (tests,
the model) can decode exact palette values. The inline composite preview is
**explicitly not palette-decodable** and is used only as a thumbnail.

**TIGHTENING (binds G5.9).** A four-view inspection returns at most **four**
inline composite previews — which is the bridge's four-images-per-result cap
(`architecture.md` §5; 8 MiB/image, 32 MP total), not a layout preference —
while all **twelve** machine-ID passes (4 views × solid/face/edge) are artifact
refs. **No pixel assertion anywhere in G4 or G5 may be made against an inline
preview**, G4.5's mask region included; the mask assertion fetches pass bytes
from `/artifacts/{ref}/bytes` (§2.6).

**TIGHTENING (binds G5.11).** The HTTP inspection DTO reproduces the schema's
*conditional, two-sided* obligation: a successful `channel="mask",
mask_mode="selection"` result **requires** `selection_table_ref`,
`mask_legend_ref`, and one `selection_bundles` entry per view; **every other
mode returns none of them — absent keys, not `null`.** A permissive DTO that
always emits `selection_table_ref: null` violates the clause as written, and the
canonical-schema drift check must cover the **negative** direction.

**Focus** changes camera framing only: the `mask_mode="solid"` domain (exactly
one solid-ID pass) and the `mask_mode="selection"` domain (three passes over one
global namespace) never exchange an ID, with or without `focus`
(`inspect.py::_focus_solids`, `_render_channel_focused`: "focus changes only the
camera; the ID namespace / legend are unchanged"). A focus miss stays
`addressing_error` (§2.4).

### 12.3 Resolution is a server operation

The route takes **two request shapes**, one per resolver, because the engine has
two and they authorize differently:

```
POST /parts/{part}/selection/resolve
# (A) GLTF pick — a raycast hit
{ build_artifact_ref, gltf_artifact_ref, mesh_index, primitive_index? }
# (B) mask submission — a pass or bundle ref plus an ID
{ build_artifact_ref, selection_artifact_ref, selection_id }
→ { kind, solid_index, topology_index, tag?, label?, line?,
    source_artifact_ref, bundle_ref, selection_table_ref,
    provenance, crop_artifact_ref }
```

**TIGHTENING (binds G5.12) — the unlinked-GLTF rejection is a server fact.**
Shape (A) dispatches to `gltf.py::resolve_gltf_pick` **against the server-held
GLB bytes**; shape (B) dispatches to `bundle.py::resolve_selection`. The
distinction matters because the two functions do not accept the same inputs: it
is `resolve_selection` that accepts a bundle ref *or any pass ref* and follows
the immutable link, while `resolve_gltf_pick(data, mesh_index, …)` reads the
hit's embedded ID out of the GLB and resolves it through the bundle ref in
`asset.extras` (`gltf.py`:335-360).

An earlier draft offered only shape (B) and expected it to carry G5.12. It
cannot: with no GLB in the request, the server has nothing to check the
submitted bundle ref *against*, so the only party that could notice an
unlinked GLB is the **client**, reading `asset.extras` — which §1's closed list
forbids (selection IDs and their links are server values) and which is the
precise thing G5.12 exists to prevent. Under shape (A) the refusal is produced
server-side by `gltf.py`:354-360 raising
`StaleSelectionError(malformed, "GLB asset carries no linked selection bundle
ref")`, and it reaches the browser as `stale_selection(malformed)` (§2.4).

The browser's raycast therefore supplies `(mesh_index, primitive_index)` as a
**hint about which triangle was hit** — never a `selection_id`, and never an
authorization. The **server** validates bundle association, exact source build,
ID kind and table entry, and layer.

- **Binds G5.12:** an **unlinked** GLTF — carrying numerically valid IDs but no
  immutable bundle link in its metadata — is **rejected**
  (`stale_selection`, reason `malformed`). The GLB alone never authorizes a
  selection. This is why the resolve call exists at all instead of the client
  asserting its hit. §5.1's route never serves an unlinked GLB in the first
  place, so this refusal is a second line of defence, and both are tested.
- **Binds G5.14:** solid, **untagged-face**, and edge selections all resolve
  through A's table on `(kind, solid_index, topology_index)` alone. A resolver
  keyed on tag names would pass G5.4 and fail G5.14 — named here because it is
  the natural, wrong implementation.
- **Binds G5.13, cardinality:** for a four-view inspection this is **4 bundle
  refs + 12 pass refs = 16 distinct submissions** through **shape (B)**, each
  after B is published, each resolving through A's immutable link. The gate says
  "each"; the test enumerates all sixteen and does not sample. Shape (B) is kept
  as its own request form precisely so this clause has a submission path that is
  not a raycast: G5.13's subject is a *ref* the model or the test posts, not a
  triangle a browser hit.
- **Binds G5.15:** RGB refs, wrong-mode refs, mismatched refs, and expired refs
  return `stale_selection` with the reason preserved; `malformed` is never
  collapsed (§2.4).

### 12.4 The line number

**NEW WORK (binds G5.4).** `SelectionEntry` carries no line number. The join is:
the selection table gives the `tag`; **A's source map**
(`BuildResult.source_map_ref` → `TagPlacement.line`, via
`inspect.py::_tag_placements`) gives the line.

**TIGHTENING:** the join is performed **against A's source map, never against
the current script.** A line number that tracked live edits would silently
contradict G5.5 and G5.6 — the popover would claim a line in a file the pictured
geometry was not built from. Untagged topology has no tag and therefore no line;
that is legal (G5.4 demands the line only for the tagged face, while G5.14
demands untagged faces merely *resolve*) and renders as §4.4's `owned` /
`unattributed` states.

**NEW WORK (§19) — A's source map is unreachable today, so the join cannot be
performed at all.** The only route from a part to a `BuildResult` is the
**current** pointer: `inspect.py::_resolve_source` returns `source_map=None`
for any `artifact_ref` that is not the current build (`inspect.py`:286-306). In
G5's own A/B scenario — render A, publish B, click A's mask — A is by
construction not current, so `_tag_placements` receives `None`, returns `{}`,
and **no line exists for any tag**. The popover would then render §4.4's
`unattributed` state — "no statement attribution available" — for a face that is
in fact tagged with a known creating line. That is both a gate failure (G5.4
read under G5.5) and an honesty violation of exactly the kind §4.4 exists to
prevent: the UI would state the machinery knows nothing when the truth is that
the server dropped a fact it once had.

The missing durable fact is added **in the engine** (§0.1 path 2), not worked
around in the client. Either is acceptable and one is chosen at implementation:

1. persist a `build artifact_ref → {build-result ref, source_map_ref}` index in
   the project store, so any build ref can reach its own source map; or
2. **GC-link A's source-map blob into A's selection bundle** at
   `publish_selection_bundle` (`bundle.py`:251-259, which already links the
   table, passes, preview, and source into the bundle blob), so
   `resolve_selection` returns the source map alongside the table and pinning A
   retains it. This is the cheaper option and it reuses a link direction the
   code already establishes.

**Aged-out honesty.** When A's source map is genuinely no longer stored, the
popover renders the `owned` state with an **explicit reason** — "A's source map
is no longer stored" — and never the generic `unattributed` copy. The
difference between "the machinery cannot attribute this face" and "the
attribution existed and was not retained" is exactly the distinction §4.4 makes
its whole argument out of, and collapsing them would be the same lie in a
smaller font.

### 12.5 Crop, provenance, and the quick-edit spawn

**NEW WORK.** `agent_bridge/sessions.py` declares
`ResolvedSelection{part, source, provenance, crop_artifact_ref}` and
`SelectionResolver` as a Protocol whose "real impl lives in core" — and nothing
implements either. Stage 5 lands the concrete resolver in `core`:

1. resolve through `resolve_selection` against **A**, never current;
2. render a **crop centred on the selected topology of build A**, minted as a
   new artifact kind `selection-crop` **against A** and **GC-linked in both
   directions** on the selection-bundle precedent, so pinning A retains the
   crop;
3. emit a `provenance` string carrying §4.4's honesty ceiling. The structured
   form is `SelectionProvenance{state ∈ (tagged|owned|unattributed), tag|null,
   label|null, line|null, statement|null}`; `ResolvedSelection.provenance` (a
   `str`, as declared) carries its canonical one-line rendering.

The crop is a **new render artifact derived from an old build**. That is legal —
bundles are immutable and publishing B mints new ones without mutating A's — and
it is precisely what the A/B gate exercises.

`POST /parts/{part}/quick_edit` then calls `SessionService.spawn_quick_edit`,
producing a `QuickEditContext` seeded with artifact-bound part source, the
resolved provenance, and the crop. **Resolution runs before any lease is taken**,
so a busy session refuses cleanly with `session_busy` and a stale selection
refuses with `stale_selection` — neither ever falls back to current geometry.
The child appears as a threaded tab in the Stream (§7.1) via the durable edge of
§2.8, and its `edit_part` diff renders in its transcript (G5.16).

Scope, inherited: a `quick_edit` session is bound to one normalized part ID;
anything resolving outside it is `scope_denied`, and it gets no
`delegate_part_agent`. The composer in a quick-edit tab shows the bound part and
the crop, so the user can see the scope they are speaking into.

---

## 13. Git panel and the two meanings of "publish"

### 13.1 Dirty markers

`GET /git/status` drives inline markers on the part tree and a dot on the Script
tab. Dirtiness is a `git status` fact about `parts/*.py` in the working tree.
`.heph/journal/` is gitignored and contributes nothing, so **dirtiness is
entirely disjoint from artifact and publication state** — a part can be clean and
unbuilt, or dirty and current. The header shows the artifact axis; the rail shows
the git axis; the UI never blurs them.

### 13.2 Publish is overloaded — and the workspace names both

**TIGHTENING (binds G5.5 and G5.18 jointly).** Two different operations are
called "publish" inside G5 itself, and the UI must never let them read as one:

| Sense | Operation | Where it appears | Precondition |
|---|---|---|---|
| **Artifact publication** | a successful default `build_part` becomes `current` | header build-state chip; the UI words are **"Make current" / "current build"** | `status="ok"`, no transient override, revalidated hashes |
| **Release tag** | `git tag` | Versions panel, **"Tag release…"** | none in the engine |

The workspace's copy uses "current build" and "tag" and **never the bare word
"publish" in UI text**. `POST /git/tag` creates an annotated tag on HEAD;
`TagDialog` shows the tag name, HEAD sha, and the current dirty set, and **warns
without blocking** when the tree is dirty, because a tag on a dirty tree records
a commit that is not what the user sees.

**Named non-decision, and it is a real one:** whether a human may tag over a
blocking termination-review finding (`VALIDATION.md` §5) is **not decided in
Stage 4/5**, because no operator-waiver surface exists anywhere in the product
today. The workspace neither offers a waiver nor enforces the reviewer. Building
a waiver UI here would invent a governance mechanism ahead of its stage (§18).

---

## 14. Fixture and test architecture

**NEW WORK (binds G4.1).** None of
`corpus/public_fixtures/{assembly,failure_fillet,fingerprint}` is a project with
the shape these gates need, and the graded corpus is **Tier 3 bench evidence**,
not UI fixture material — reusing `cat-step` would couple G4's e2e to scoring
inputs, and mission rule 8 forbids private evidence in ordinary PR gates. Stage 4
adds a dedicated public clean-room fixture project,
`corpus/public_fixtures/workspace/`, carrying by requirement:

- **≥3 solids**, so G4.6's all-pairs centroid clause is not vacuous;
- a tagged **`tread_top`** face with a known creating line (G5.4);
- **`groove_count = Param(5, min=2, max=10)`** (G5.2, G5.3);
- the full enumerated **`part.*` metadata** set (G4.3, both directions of §6.2);
- checks producing at least one of each badge state **including `not_run`**
  (G4.4);
- a **selection legend exceeding `INLINE_LEGEND_CAP_BYTES` (50 KiB)** so
  `mask_legend_truncated` + `mask_legend_ref` paging is actually exercised
  (G5.8);
- a committed **>250-event** normalized transcript with at least one quick-edit
  child (G4.9, G4.10, G4.11);
- a **DFM-violating** feature (§6.4).

**TIGHTENING (binds G4.0).** `pnpm test:e2e` runs Playwright against a real
`heph serve --web` on the fixture, **inside the same pinned CI container image**
as `tests/render`. `verification.md` Tier 2 binds every golden to a
`(container image, renderer version)` pair, and §5.3 makes the gated section
render a *server* render — so running the browser suite in a different image
would invalidate G4.7's golden by construction. **One CI image serves both the
Python render goldens and the browser e2e.** This is a real constraint on CI
topology, stated here so it is designed rather than discovered.

Golden families touched by Stages 4/5, **all server-side**, each with a
provenance sidecar and a re-baseline-PR policy on the `heph goldens --update`
precedent (which refuses a dirty tree): the existing render goldens; the
**region golden** for G5.16; and the **new normalized-event archive** for G4.11.
**No browser-rendered golden family is created**: no browser pixels are
committed as reference images, pinned to a `(container image, renderer
version)` pair, or given re-baseline machinery. Screenshots are archived CI
artifacts (G4.12) and are **never compared against a golden**.

The one place browser pixels are read at all is G4.5's before/after delta
inside a decoded solid-pass mask region (§5.4) — two frames from the same
rasterizer in the same run, compared to each other, with nothing stored. It is
an assertion, and it is deliberately not a golden; the distinction is what lets
§5.3's refusal and G4.5's clause both stand.

**Tier split.** G5 is Tier 2 **+ Tier 1**, and the Tier 1 half is pytest against
`core/render/*` and `server/http`: palette-value exhaustiveness per pass
(G5.10), the five `StaleReason` values (G5.15), schema conditionality in both
directions (G5.11), legend paging (G5.8), REST idempotency and the parity lane
(G5.19), and the snapshot-then-reject write path (G5.22). Only their *submission
path* — the refs the browser posts — is browser-side.

**Two mandatory evidence paths for G5.16:** the scripted fake model gates the
PR, and the recorded real-model fixture is committed as separate evidence.
Neither substitutes for the other.

---

## 15. What deliberately does not change, and what is not included

Refusals in the doc-culture sense: each is something a reader might reasonably
expect and will not find.

1. **No parametric direct manipulation** (`architecture.md` §8). Selection →
   scoped agent is the interaction model.
2. **No geometry logic in the client** (§6), enforced by §1's `<Fact>` / lint
   mechanism rather than by good intentions.
3. **No fallback to current geometry** on selection resolution, ever (§4.4).
   Stale is stale and says so.
4. **No per-face attribution for untagged boolean-result topology** (§3.1) —
   §4.4's third popover state is the honest answer, not a bug.
5. **No community sharing, gallery, or Scrapyard** (§8).
6. **No TLS, real authn, or multi-tenant isolation** (§7). Loopback + bearer
   token, and one docs sentence about reverse proxies.
7. **No `--unsafe-local-executor` on `heph serve`.** The web therefore never has
   an unsandboxed path; `capability_not_available` is rendered, not hidden.
8. **No second dispatch, serializer, pager, or idempotency store.** Extraction
   where needed; duplication never (mission rule 6).
9. **No new model tool and no new `inspect_part` parameter.** Nothing the
   workspace needs is added to the model's surface.
10. **No event-vocabulary extension.** Threading is a durable edge (§2.8).
11. **No page-size knob on history**, and no rewriting of an opaque cursor
    (§2.8).
12. **No posed-scene render panel** — and the reason is *not* that posed render
    is unavailable. Posed-scene render is **shipped Stage 9 harness
    machinery**, reachable from `heph render --pose <id>` and supplied to the
    termination reviewer (`KINEMATICS.md` §6). What that section defers is only
    the **model-facing** surface: posed render is not a model tool and not an
    `inspect_part` parameter in Stage 9, pending a per-profile dispatch rule.
    The workspace is an **operator** client, so that deferral does not reach
    it. The actual and sufficient reason for the exclusion is that **no G4 or
    G5 clause asks for a motion or posed surface** (§18.3 keeps it as an
    amendment candidate). Stating it the other way would have told a future
    stage that an operator-side posed preview needs a per-profile dispatch rule
    first, which is false.
13. **No `add_reference`.** Reference registration is operator-side
    (`heph reference add`) by design; the workspace does not invent a tool for
    it.
14. **No `run_fea`, no `import_geometry`** — excluded from `TOOLS`.
15. **`ask_user` never reaches `py.tool_dispatch`.** The widget answers
    `py.ask_user`, and no route pretends otherwise.
16. **No git write beyond tag creation** — no commit, push, checkout, reset,
    branch, stash, or merge.
17. **The workspace serves no `export`-kind artifact bytes and offers no
    export, drawing, or document affordance.** Both halves are load-bearing:
    §2.6 closes `/artifacts/{ref}/bytes` **by enumeration**, so an `export` ref
    is refused by the route and a pytest asserts it. Scoping that route to
    `BINARY_ARTIFACT_KINDS` — of which `export` is a member — would have made
    this a statement about buttons while any bearer-holding browser could fetch
    the bytes. A "Download STEP" button would be the product's first
    non-agent, non-CLI export path: a product decision, not a UI addition
    (§18).
18. **No bench or leaderboard surface.** `docs/README.md`'s no-static-site
    decision makes the default answer no, and no gate asks.
19. **No operator-waiver UI** (§13.2).
20. **No "Smith"/"Arche" in identifiers or packages**, and no test asserting the
    reference product's copy.
21. **No `/session/{uuid}` route** (§4.5).
22. **No mobile layout.**
23. **`server/http` is not headless surface.** Nothing in G7H may come to depend
    on it.

---

## 16. Deliverables → G4 clause map

Labels index the gate text in `mission_plan.md`, which is authoritative and is
neither reproduced nor edited here.

| Clause | Subject | Deliverable | Where |
|---|---|---|---|
| **G4.0** | `pnpm test:e2e` exits 0, Tier 2 | pnpm workspace + Playwright suite, run in the **same pinned CI image** as `tests/render` | §3, §14 |
| **G4.1** | public clean-room fixture project | `corpus/public_fixtures/workspace/` with the nine listed requirements | §14 |
| **G4.2** | tree rows == build-result geometry count | explicit `geometry_count` on `GET /parts/{part}/build`; one row per `geometries` entry; server-side three-number invariant test | §2.3, §6.1 |
| **G4.3** | properties panel shows all metadata fields | `GET /parts/{part}/properties`; DOM↔projection **and** projection↔`part.*` set equality | §2.3, §6.2 |
| **G4.4** | check badges match `heph check` JSON | shared `report_json` serializer behind `GET /parts/{part}/checks`; byte-parity against a subprocess; closed badge vocabulary incl. `not_run` | §2.3, §6.3 |
| **G4.5** | visibility toggle changes viewport in the solid's mask region | per-solid visibility; solid-pass bytes from `/artifacts/{ref}/bytes` decoded as a test-side mask; before/after viewport delta asserted **inside** the mask against an unchanged control region — a self-referential delta, **not** a golden | §2.6, §5.3, §5.4 |
| **G4.6** | explode(1.0) increases pairwise centroid distances | per-solid `explode_offset` (the server's own `_explode_offset` at `t=1`) in GLTF extras; client applies `offset · t`; server-side byte-equivalence pytest; ≥3-solid fixture | §1, §5.1, §5.2, §14 |
| **G4.7** | section plane → golden-matched render | server-rendered section plate; client clipping preview explicitly non-evidentiary; existing golden discipline unchanged | §5.3 |
| **G4.8** | CLI-started session streams live into the web panel | `heph serve --web` owns leases; `heph agent` client mode via `serve.json`; WS `/events`; non-durable observer never triggers backpressure-cancel | §2.1, §2.7 |
| **G4.9** | multi-page historical transcript via the normalized snapshot API | `history_page` passthrough, opaque cursor unmodified, **no page-size knob**; >250-event fixture; history is the transcript **prefix**, never a live-gap refill | §2.7, §2.8, §8, §14 |
| **G4.10** | preserves quick-edit parent/child threading | `tp_session_edges` in `state.db` written at spawn and at delegation `PREPARED`; `GET /sessions/{id}/thread`; nested tabs; `unlinked` honesty state | §2.8, §7.1 |
| **G4.11** | matches previously archived event IDs | two namespaces named, not merged: live `(run_id, seq)`, historical `(session_id, ordinal)`; the archive is over the **historical** pair, which is what a reopened transcript emits; `tests/stage4/goldens/events/`; restart-stability assertion | §2.8, §14 |
| **G4.12** | screenshot artifacts archived | Playwright artifact retention; screenshots never an assertion | §14 |
| **G4.D** | stable `data-tool-name`/`data-status`; one `data-field` per schema-required present field, checked against normalized event JSON | `ToolChip` contract; **containment + groundedness** over the *parsed* result document `JSON.parse(payload.text)`, not the event envelope: `F ⊇ (required ∪ present refs) ∩ keys(D)` **and** `F ⊆ keys(D)`; non-JSON `text` renders a visibly degraded chip; `isError` added to historical normalization so a failed call never reads `ok` | §7.2, §19 |
| **G4.X** | *(deferred from G6)* DFM toggle surfacing findings in the web panel | `DfmPanel`; topology descriptors not bare mask IDs; preview-vs-current marking; toggle split into an action and a project-config write | §6.4 |

---

## 17. Deliverables → G5 clause map

| Clause | Subject | Deliverable | Where |
|---|---|---|---|
| **G5.1** | Monaco edit → save → viewport + new metrics in Results | `PUT /parts/{part}/script` **is** `write_part`; rebuild-on-save; metrics from the rebuilt `BuildResult` | §9.1, §9.2 |
| **G5.2** | slider moves `groove_count`, rebuild reflects it | `set_params` + default `build_part`; never transient params | §10 |
| **G5.3** | out-of-bounds rejected inline | server `rejected[]` rendered verbatim beside the control; **no client clamping** | §10 |
| **G5.4** | popover contains `"tread_top"` and the creating line | `SelectionPopover`; `tag → TagPlacement.line` joined against **A's** source map, which requires **NEW WORK** to reach at all (`_resolve_source` drops it for any non-current ref); aged-out case renders `owned` + a stated reason, never generic `unattributed` | §4.4, §12.4, §19 |
| **G5.5** | render A, publish B, click A's mask, crop/provenance resolve against A | concrete `SelectionResolver` in `core`; `selection-crop` minted against A, GC-linked both ways; sticky pin | §12.1, §12.5 |
| **G5.6** | inspection reports A as `source_artifact_ref` even when current changes | `artifact_ref` first-class sticky workspace state; explicit "Follow current"; no auto-advance | §4.5, §12.1 |
| **G5.7** | mask domains mode-correct with or without `focus` | focus changes camera only; two ID domains never exchange an ID; `addressing_error` kept distinct | §2.4, §12.2 |
| **G5.8** | oversized legends bounded inline, page losslessly via `mask_legend_ref` | extracted `page_text` shared with `read_artifact`; `GET /artifacts/{ref}/text` under `WorkspacePrincipal`; oversized-legend fixture | §2.6, §2.2, §14 |
| **G5.9** | ≤4 inline previews, 12 machine-ID passes as artifact refs | inspection DTO cap; binary bytes endpoint; no pixel assertion against a preview | §2.6, §12.2 |
| **G5.10** | each pass contains only published palette values | byte-exact PNG serving, no transformation of any kind; test decodes downloaded bytes | §2.6, §14 |
| **G5.11** | schema requires selection refs only in mask-selection mode | two-sided conditional DTO; absent keys, not `null`; drift check covers the negative direction | §12.2 |
| **G5.12** | GLTF raycast accepted only through its immutable linked bundle | `POST /selection/resolve` **GLTF-pick shape** `{build_artifact_ref, gltf_artifact_ref, mesh_index, primitive_index?}` → `resolve_gltf_pick` over server-held GLB bytes; unlinked GLB → `stale_selection(malformed)` raised **server-side**, never by the client reading `asset.extras`; the gltf route never serves an unlinked GLB | §5.1, §12.3 |
| **G5.13** | each per-view `bundle_ref` and its pass refs resolves through A after B | enumerated **16** submissions (4 bundles + 12 passes), not sampled | §12.3 |
| **G5.14** | solid, untagged-face, edge selections resolve through A's table | resolution on `(kind, solid_index, topology_index)`, never on tag | §12.3 |
| **G5.15** | rgb/wrong-mode, mismatched, expired → `stale_selection` | 409 with the five-value `StaleReason` preserved; `malformed` never collapsed | §2.4 |
| **G5.16** | quick-edit chamfer → `edit_part` diff in transcript + changed golden-region render | `spawn_quick_edit` path; child tab; **server-rendered** region golden; fake model in e2e **and** committed recorded real-model fixture | §5.3, §12.5, §14 |
| **G5.17** | git panel shows the edit as dirty | `GET /git/status` projection; `GitDirty` markers; disjoint from artifact state | §2.9, §13.1 |
| **G5.18** | publish creates a tag (`git tag -l`) | `POST /git/tag`; "Make current" vs "Tag release" naming discipline | §13.2 |
| **G5.19** | REST rejects missing `Idempotency-Key`, replays a recognized key, independent of MCP | **enumerated** per-route key policy — seven store/config/output routes require a key, five session-control routes do not, and both directions are tested; payload-**independent** key carried as `Invocation.entry_id` with the body only in `payload_hash`, so `key_payload_mismatch` is reachable; full response ladder with the engine's own reason strings; freshness on first sight only; pinned REST replay shape in the Stage 3 parity suite | §2.3, §2.5 |
| **G5.20** | stale-base-hash race surfaces as a merge prompt | conflict as a **200** discriminated result; `ConflictDialog`; first-commit-wins, both directions tested | §2.4, §9.3, §9.4 |
| **G5.21** | transcript shows a failed edit with bounded chunk/hash + paging cursor | conflict payload rendered verbatim; continuation from `current_snapshot_ref` via the text pager; `read_part` refused as continuation; raw chunk, not `numbered_script` | §9.3, §7.2 |
| **G5.22** | no write lost: git / `.heph/journal/` / conflict payload | store-API save path; **snapshot-then-reject**; three-store table; retention and `snapshot_expired` honesty | §9.1, §9.4 |

---

## 18. Amendment candidates (post-G4/G5)

**None of these is a gate clause.** G4 and G5 were written before Stages 8 and 9
existed. Each enters only by amending `mission_plan.md` with a new gated stage
(mission rule 5). They are listed because the doc culture requires exclusions be
named, not omitted.

1. **Requirement ledger and reviewer findings (`VALIDATION.md`).** The
   highest-value candidate: generational, artifact-addressed,
   `source ∈ {specified, derived, assumed}`, citations with lint states
   including `unverifiable_citation`, and a blocking independent termination
   reviewer. This is now the substrate of "is this design done", and Stage 4/5
   predates it. A read-only ledger panel is the natural first increment.
2. **Assembly panel (Stage 8C, `ASSEMBLY.md`).** `AssemblyStatus` read-only:
   per-constraint residual or named `unresolvable` reason; generational state
   where withdrawal is a new generation rather than an erasure. The honesty
   hazard is that `assembly: null` means *never evaluated* and is **not a pass**
   — a badge design must carry that distinction before this panel ships.
3. **Motion panel (Stage 9, `KINEMATICS.md`).** `MotionStatus`, joints and poses
   with withdrawn entries and reasons, the closed five-verdict sweep vocabulary
   rendered verbatim (`holds_at_samples`, **never** "holds"), the coupling
   table, `results: null` said out loud, `partial: true` on a named-subset
   evaluation. Swept-envelope and **posed-scene** previews belong here too, and
   the blocker is **not** `KINEMATICS.md` §6's deferral: posed-scene render
   already exists as Stage 9 engine machinery, exposed through
   `heph render --pose <id>` and the reviewer context, and §6 defers only the
   *model-facing* surface (a model tool or an `inspect_part` parameter) pending
   its per-profile dispatch rule. An operator-side posed preview panel has no
   dependency on that rule. It is excluded from Stage 4/5 for the ordinary
   reason every entry in this section is excluded: **no G4/G5 clause asks for
   it**, so it needs a new gated stage under mission rule 5 like everything
   else here.
4. **Operator waiver UI.** `ASSEMBLY.md` §3 and `KINEMATICS.md` §6 make certain
   findings "waivable only by the operator, recorded as such", and no such
   surface exists anywhere in the product. It should be designed as governance,
   with the ledger — not bolted to a tag dialog (§13.2).
5. **`compare_solids` diff visualization** (`COMPARE.md`) and **reference
   registry browsing** — references being the one object where the human, not
   the model, is the writer. There is deliberately no `add_reference` tool and
   the workspace must not invent one.
6. **Export / drawing / document surfaces.** The workspace would be the first
   non-agent, non-CLI export path in the product: a genuine product decision,
   not a UI addition.
7. **Orchestrator delegation-tree view.** §7.1 renders three levels as nested
   tabs. A dedicated delegation graph — with admission occupancy, the 16-slot
   ceiling, and queued state made visible — is unaddressed by any gate.
8. **DFM ergonomics beyond §6.4.** Whether a *per-run* DFM request should exist
   at all is a tool-surface question, not a UI question, and belongs to whichever
   stage revisits `run_dfm`.

---

## 19. Named new work

Everything else in this spec is a projection of something that exists. These do
not exist today and must be built:

1. `server/http` in its entirety (§2), and `heph serve --web` + `serve.json`.
2. `web/` in its entirety, the pnpm workspace, and the `test:e2e` script (§3).
3. `heph agent` client mode against a running server (§2.1).
4. The non-durable observer client class and its `4409` resync protocol (§2.7).
5. Extraction of `page_text` and `report_json` into shared functions with
   per-caller principal checks (§2.6, §6.3).
6. `tp_session_edges` in `state.db` and `GET /sessions/{id}/thread` (§2.8).
7. The REST idempotency path, its pinned replay shape, and its parity lane
   (§2.5), **plus** the ledger extension that records non-tool REST mutations
   (`POST /project/config/dfm`, `POST /git/tag`) under the same key space
   (§2.3) — without it those two rows are a header requirement with nothing
   behind them.
8. The concrete `SelectionResolver` in `core`, the `selection-crop` artifact
   kind, and its two-way GC links (§12.5).
9. The `tag → TagPlacement.line` source-map join resolved against A (§12.4),
   **including the durable fact that makes it possible**: either a `build
   artifact_ref → {build-result ref, source_map_ref}` index in the project
   store, or a GC link from A's selection bundle to A's source-map blob at
   `publish_selection_bundle`. Today `_resolve_source` returns `source_map=None`
   for every non-current ref, which is every ref G5.5 cares about.
10. The git projection: `status`, `log`, `diff`, `tag` (§2.9).
11. `explode_offset` in GLTF mesh `extras`, `_explode_offset` exported from
    `channels.py` for the purpose, and the server-side byte-equivalence pytest
    against `heph render --channel explode` (§5.1, §5.2).
12. **GLB export and publication for a build artifact ref**, including minting
    (or resolving) the selection bundle for that exact ref by re-tessellating
    from the stored BREP, publishing under the `gltf` artifact kind, and the
    rule that the route never returns an unlinked GLB (§5.1). `export_gltf` has
    no production caller today and cannot be called without a bundle.
13. `isError` on `tool_result` in `normalizeEntries` (`agent/src/session/
    history.ts`), landed **before** the G4.11 event archive is baselined
    (§7.2). Without it a reopened transcript renders every failed tool call as
    `ok`.
14. Closing `GET /artifacts/{ref}/bytes` **by enumeration** rather than by
    `BINARY_ARTIFACT_KINDS` membership, with a pytest asserting an `export` ref
    is refused (§2.6, §15.17).
15. Recording the exact pinned versions of the `web/` dependency set in
    `repo_conventions.md`'s **Stage S accepted-versions block** under the
    no-caret rule — React, Vite, three.js, Monaco, TanStack Query, Playwright,
    and the CSS-module tooling — together with §3's wheel-embedded
    bundle-delivery clause (§0).
16. The public clean-room fixture project, the normalized-event archive golden,
    and the quick-edit region golden (§14).

---

## 20. Ambiguities tightened — mission rule 1 ledger

Each row is a gate ambiguity resolved by **tightening**. None rewords a gate;
each adds a decision the gate's text does not make.

| Ambiguity | Resolution | § |
|---|---|---|
| "geometry count" — three candidate numbers | `len(BuildResult.geometries)`, served as an explicit field; separate invariant test ties all three | 6.1 |
| "all metadata fields" — no closed list | two-sided set equality: DOM ↔ projection **and** projection ↔ enumerated `part.*` | 6.2 |
| which rasterizer a "golden-matched render" is matched in | server pixels; no browser golden family; client clipping preview is non-evidentiary | 5.3 |
| what "event ID" names | two namespaces, both named: live `(run_id, seq)`, historical `(session_id, ordinal)`; the archive is over the historical pair and is asserted across a sidecar restart | 2.8 |
| whether history can close a live gap | no — two disjoint identity namespaces; history is the transcript prefix, a live gap is a labelled break | 2.7, 8 |
| which kinds survive a reopen | six of ten, `image` metadata-only; `question`/`answer`/`terminal`/`progress` are live-only and render as named absences | 2.7, 7.3, 8 |
| which routes are REST mutations for the key rule | enumerated per route: seven require a key, five session-control routes do not; `answer` is governed by question-id idempotency | 2.3 |
| what the REST idempotency key is derived from | the header value and route identity, **never the body**; the body is the separate `payload_hash` | 2.5 |
| how G4.5's pixel clause is evidenced without a browser golden | before/after viewport delta inside a decoded solid-pass mask, against an outside control region; self-referential, nothing stored | 5.3, 5.4 |
| the `data-field` completeness predicate | containment **and** groundedness over `JSON.parse(payload.text)`; equality dropped as stricter than the gate; unparsed `text` renders a visibly degraded chip | 7.2 |
| which resolver shape carries G5.12 | the GLTF-pick shape against server-held GLB bytes; the mask-submission shape is kept separate for G5.13 | 12.3 |
| quick-edit threading, absent from the event vocabulary | durable `tp_session_edges` in `state.db`; vocabulary untouched; pre-existing transcripts reopen `unlinked` | 2.8 |
| REST reconciliation shape (a third transport, unpinned) | byte-for-byte replay + `"replayed": true`; added to the Stage 3 parity suite as a third lane | 2.5 |
| the form of "reject a missing key" | `400 idempotency_key_required`, no execution; full ladder tabulated | 2.5 |
| which side of the stale-hash race wins | first commit wins; both directions tested; **snapshot-then-reject** | 9.4 |
| whether a browser client can backpressure-cancel a run | no — non-durable observer, socket closed `4409`, resync from history, gap rendered | 2.7 |
| cross-process live streaming topology | the serving process owns leases; `heph agent` attaches as a client via `serve.json` or refuses `session_busy` | 2.1 |
| slider semantics (`set_params` vs transient `build_part` params) | `set_params` + default build; transient overrides never become current | 10 |
| the two senses of "publish" | "Make current" (artifact) vs "Tag release" (git); the bare word never appears in UI copy | 13.2 |
| artifact authorization for a non-session principal | project-scoped capability, stated as its own rule; two routes, two contracts | 2.2, 2.6 |
| HTTP status for a CAS conflict / capability error | **200** with the discriminated result — a 4xx would make the merge prompt indistinguishable from a transport failure | 2.4 |
| where `measure` lives, given cross-part kinds | project-scoped `POST /measure`, not `/parts/{part}/measure` | 2.3 |
| the orphaned G6 DFM-toggle clause | placed as e2e coverage under `pnpm test:e2e`; toggle split into an action and a project-config write; descriptors, not mask IDs | 6.4 |

---

## 21. Residual risks this draft wants attacked

Named so review has targets, not so they are pre-forgiven.

1. **§5.3's server-render decision** makes the gated viewport a picture viewer.
   If a reviewer holds that G4.7's "golden-matched render" must be the *live*
   viewport, the cost is an entire browser-golden determinism family and this
   section is wrong.
2. **§2.7's disconnect-and-resync** trades a visible UI hiccup for run safety.
   If the durable backlog provably cannot overflow for a web client, the simpler
   shared-fate design wins.
3. **§2.8's edge table** puts threading outside the event stream. If a later
   stage needs threading *inside* the vocabulary, this is a migration, not an
   extension.
4. **§2.5's chosen REST replay shape** is a genuine third transport shape. It
   must be argued against MCP's `{applied: true}` on parity grounds, not
   accepted because it is written down here.
5. **§6.2's set equality on `part.*`** is only as closed as that contract
   actually is. If the enumeration is looser than assumed, G4.3 needs a
   different anchor.
6. **§12.5's crop renderer** is the largest piece of new `core` work in Stage 5
   and the only one with no existing caller to imitate — including its GC-link
   direction, which nothing today exercises for a derived-from-old-build
   artifact.
7. **§2.1's client-mode `heph agent`** changes the behaviour of an existing,
   shipped verb based on the presence of a file. If a reviewer holds that a
   shipped CLI verb may not silently change topology, this needs an explicit
   opt-in and the rejected `--server` flag returns.
8. **§2.7's refusal to heal a live gap from history** buys honesty at the cost
   of a visible seam every reconnect. The alternative — carrying the
   originating run id and a per-run seq through Pi session entries so
   `normalizeEntries` can reconstruct live-comparable identities — is the
   better long-run shape and re-baselines G4.11's archive. If a reviewer holds
   that a labelled break is unacceptable UX for a workspace, that engine change
   is the price and it must be scoped before Stage 4, not after.
9. **§7.3's historical-image placeholder** is honest but thin. If reopened
   transcripts are the primary way the images of §0's deficit are seen, then
   not retaining the bytes defeats the workspace's stated centre of gravity,
   and carrying them into Pi entries becomes new work this spec declined.
10. **§5.4's delta thresholds** (≥0.10 inside the mask, ≤0.01 outside) are
    chosen, not measured. If the fixture's target solid is small in frame or
    heavily occluded, the inside-mask fraction may not clear 0.10 and the
    numbers need re-deriving from the fixture rather than the clause being
    loosened.
11. **§12.4's chosen durable fact** — bundle-linked source map versus a store
    index — is left open here. If a later stage needs a build ref's source map
    outside a selection context, the GC-link option will not reach it and the
    index is the one that had to be built.
