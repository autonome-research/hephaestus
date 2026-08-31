<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# 12 — The web workspace (Stages 4 and 5)

**DRAFT — pending adversarial review, EXCEPT §22 and §23.** The Stage 4/5 body
of this document is not yet normative. Promotion follows the `ASSEMBLY.md` /
`COMPARE.md` / `KINEMATICS.md` pattern: a dated `mission_plan.md` amendment
carrying the Stage 4 and Stage 5 headings and citing this spec, after an
adversarial pass against the codebase. Until then `mission_plan.md` Stage 4
and Stage 5 are the only binding text.

**§22 and §23 are NORMATIVE as of 2026-08-28.** They were promoted by exactly
that mechanism, ahead of the rest of this document and independently of it:
`mission_plan.md` §"Stage 10 — Workspace egress and provider attachment
(amendment 2026-08-28, maintainer-directed)" is a dated amendment that names
Stage 10A, 10B and 10C, cites this spec's §22 and §23 as their normative
specification, and carries gates G10A, G10B and G10C. The two sections are
therefore the binding design beneath those three gates, on the same footing
`KINEMATICS.md` holds beneath G9A–G9C. The rest of this document's status is
unchanged (§0.2).

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

### 0.2 The 2026-08-28 product review, and what it changed

The product owner reviewed a running workspace serving the public clean-room
fixture and reported four things. They are recorded verbatim because a
paraphrase would let the spec answer an easier question:

1. *"there is an agent panel but no way for me to start chatting with an agent
   about the displayed material"*
2. *"there is no export button or export types to take out of heph and put into
   a different cad software"*
3. *"whatever design that was in the UI you put up looked pretty bad"*
4. *"there should be a way to sign in with your sub or api to chat against the
   objects or blank canvas"*

All four are consequences of decisions **this document made on purpose**:
§9's deferral of prompting as cited by `StreamPanel.tsx`, §15.17's export
refusal, §3's "CSS Modules + a design-token file" row, and §2.2's "it never
prompts for credentials". The question the review had to answer was therefore
not *did we build the spec* — we did — but **was the spec wrong about the
product**. Ruling, per complaint:

| Complaint | Ruling | Where the answer lives |
|---|---|---|
| 1 — no way to chat | **The spec was wrong, and it was wrong by miscitation.** §9 says nothing about prompting; `Composer` was already on §4.2's Stage-4/5 inventory. The deferral had no clause behind it. | **§7A** (new), Stage 4/5 |
| 2 — no export | **The mechanism decision was right; the product decision was a deferral that was escalated and never answered.** It is answered now, and the mechanism argument turned out to be weaker than §2.6 claimed (§2.6, §22.3). | **§22** (new), **Stage 10A**, approved 2026-08-28 |
| 3 — design | **The row was wrong about what it had bought.** CSS Modules is a delivery mechanism, not a design system; five of the layers a design system supplies were never authored. The *dependency* rejections all survive review. | **§3.1–§3.14**, **§4.7** (rewritten/new), Stage 4 |
| 4 — sign-in | **§2.2's sentence answered a different question than it was read as answering.** It is narrowed, not withdrawn. | **§23** (new), **Stage 10B/10C**, approved 2026-08-28 |

**Numbering allocation, done once and up front.** All four amendments touch the
same closed lists, and this document's own rule (§7A's opening) is that section
numbers are the only cross-reference mechanism, so an unallocated landing would
silently invalidate citations. The allocation is: `§7A` inserted under §7 with a
letter rather than a renumber; `§22` egress; `§23` provider sign-in; §15
refusals **24–41** in one sequence; §19 items **17–41** in one sequence; §4.7
new; §3 replaced in place. No section between §8 and §21 is renumbered.

**Stage status of each amendment, and what is DRAFT beyond this document's own
draft status.** Updated 2026-08-28 by the approval recorded two paragraphs
below: nothing in this document is DRAFT-for-want-of-a-stage any more.

| Amendment | Stage | Gate status |
|---|---|---|
| §7A composer on orchestrator/part sessions, blank-canvas create, read-refresh | Stage 4 | Under G4's existing deliverables; no gate edit. §7A.9 argues it. |
| §7A.7 answering `ask_user` from the browser | Stage 4 | G4's deliverable text says `ask_user widgets`; the route and registry already exist. |
| §7A composer in a quick-edit tab | Stage 5 | **Already gated** by G5.16, verbatim. |
| §3.1–§3.14, §4.7 design system | Stage 4 | Tightenings under G4's shell/panel deliverables; §3.14 adds checks, not clauses. |
| §2.6 kind-binding correction (§19.24) | Stage 4 | A correction to a route this document already specifies; it is a **prerequisite** of §22. |
| **§22 egress** | **Stage 10A — APPROVED 2026-08-28** | The `mission_plan.md` amendment of §22.10 landed as Stage 10A with **Gate G10A**. §22 is normative beneath it. |
| **§23 provider sign-in** | **Stage 10B — APPROVED 2026-08-28**; discovery is **Stage 10C** | The same amendment landed as Stage 10B with **Gate G10B**. The **open rule-7 question** (§23.5) was ruled on the same day and enters as **Stage 10C** with **Gate G10C**. |

Sections **§22** and **§23** are **normative** beneath Gates G10A, G10B and
G10C. G4 and G5 keep their text verbatim; neither mentions export or
credentials, and the Stage 10 amendment edits neither.

### 0.2a The 2026-08-28 approval, recorded

Two operator decisions of the same date, both binding, closed everything §0.2
had left open.

**1 — The Stage 10 amendment is APPROVED.** `mission_plan.md` now carries
§"Stage 10 — Workspace egress and provider attachment (amendment 2026-08-28,
maintainer-directed)", citing this document's §22 and §23 as its normative
spec. §22.10's clause shape landed as **G10A** and §23.14 item 16's clause
shape landed as **G10B**, both verbatim from `docs/workspace-plan.md` §9. The
amendment boundary that section 3 of the plan drew — *"items 7–10 are not
buildable until `mission_plan.md` carries the amendment"* — is **crossed**.
Every "DRAFT (new stage)" marking in this document is struck, and §21's risk 15
("specified against a stage that does not exist yet") is closed by the stage
existing.

**2 — Local-first credentials are APPROVED**, resolving the item §23.5 marked
**OPEN — MAINTAINER SIGN-OFF REQUIRED**. In the operator's words:

> "The server should be able to work locally, the same way that Claude for
> science works."

The server MAY discover the operator's existing home-directory credential
sources — a Pi `auth.json`, an existing `providers.json`, a local
OpenAI-compatible endpoint — and **offer** them. The binding constraints that
survive the approval are written into §23.5 in full and are gated by **G10C**:
discovery is an offer and never a silent adoption; a secret is never echoed to
the client, never logged, and never in a URL, an event or an artifact; the
serve stays loopback-only; anything written is `0600`; and **mission rule 7 is
unchanged** — it still forbids ambient provider keys reaching a run unapproved,
and `credential_allowlist` stays supervisor-prepared and not web-writable.

**The approval is a ceiling, not a floor.** It permits describing a discovered
source with "a masked hint at most". §15.41's **no masked key tail** refusal is
stricter than that ceiling, so it stands unrelaxed: a discovered source is
described by kind, provider id, model ids and source path, and by nothing
derived from its secret. An approval that permits *at most* X does not oblige
X, and this document does not weaken a shipped refusal on the strength of a
permission it did not need.

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
| `GET /parts` | `[{name, path, content_hash, snapshot_ref}]` — `list_parts` projection. **Same serializer** as `heph part list --json` (`hephaestus.core.project_store.listing`). |
| `GET /parts/{part}/script?offset_line&limit_lines` | `read_part` result verbatim, `_PAGING_FIELDS` intact. CLI counterpart: `heph script show --json`. |
| `GET /parts/{part}/build` | `BuildResult` projection: `{status, current, artifact_ref, project_snapshot_ref, effective_params, geometry_count, geometries[], metrics, checks, source_map_ref, warnings, checkpoints[], error?, critique?}`. CLI counterpart: `heph part show --json` emits the engine `BuildResult` (same document `heph build --json` writes) or `{status:"not_built"}`. |
| `GET /parts/{part}/properties` | the enumerated `part.*` metadata projection (§6.2) |
| `GET /parts/{part}/checks` | the shared `heph check --json` serializer (§6.3) |
| `GET /parts/{part}/params` | `PARAMS` declarations `{name, value, default, min, max, step, scope}` + `state_hash`. CLI counterpart: `heph params [PART] --json` (script literals + last-build effective values; no sandbox, no `state_hash` — it does not write `set_params`). |
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
| `POST /context/preview` | resolve a composer context envelope → `{block, truncated, sources[]}`; **starts no run, calls no tool** (§7A.3). Project-scoped for the same reason `measure` is: its operands span parts and artifacts and a session id is not among them. **NEW WORK (§19.19).** |

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
| `POST /parts/{part}/export` **Stage 10A (§22)** | `export_part` | **existing `tp_exports` WAL** |
| `POST /parts/{part}/drawing` **Stage 10A (§22)** | `generate_drawing` | **existing `tp_exports` WAL** |
| `POST /parts/{part}/doc` **Stage 10A (§22)** | `generate_doc` | **existing `tp_exports` WAL** |
| `PUT /providers/specs` **Stage 10B (§23)** | the `providers.json` **spec-only** write (§23.6) | **NEW WORK**: the same non-tool ledger extension the two rows above it need |

The three export rows are the only rows in this table that need **no** ledger
extension: they replay a complete `ExportCommit` — paths,
`source_artifact_ref`, `source_input_hashes`, `export_hashes`, and the
per-operation `extra` — from a `COMMITTED` row. `PUT /providers/specs` does need
it, under the same key space.

**TIGHTENING (binds the `PUT /providers/specs` row).** The route is named
`/specs` and not `/providers` because it is **not** the whole file. It writes
provider specs only. `credential_allowlist` and `auth_source` are **read-only
projections** and a body carrying either is refused
`allowlist_not_web_writable` by name. WHY, at length in §23.6: those two fields
compose into an arbitrary-environment-variable-to-arbitrary-host exfiltration
primitive driven by a bearer token §23's own threat model concedes any
page-script compromise holds, and mission rule 7's approval mechanism is *an
allowlisted credential environment prepared by the supervisor*, which is a
terminal act, not a browser click.

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
| `POST /sessions/{id}/prompt` | `prompt`, body `{text, context?}` (§7A.3) | A prompt is not idempotent in any useful sense — the same words twice are two turns, and pretending otherwise would let a replay swallow a deliberate re-ask. At-least-once, stated. The optional `context` member changes nothing about the key policy: it carries references, never facts (§7A.3). |
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

**Egress and credential reads — Stage 10A (§22) and Stage 10B (§23)**

| Route | Returns | § |
|---|---|---|
| `GET /parts/{part}/exports` | committed `tp_exports` projection: rows with paths, blobs, sizes, source ref, `extra` | §22.7 |
| `GET /exports/{export_blob}/bytes` | the file, as an `attachment`, addressed by the blob a **`COMMITTED`** row names | §22.3 |
| `GET /providers` | specs, availability, auth state, egress acknowledgements, `auth_source`, file mode — **no credential material** | §23.8 |
| `GET /providers/catalog` | Pi's built-in catalog, live over the bridge | §23.1 |
| `GET /providers/{id}/auth/status` | `{state, type?, expires_at?, health, last_observed_at, flow?}` — metadata only | §23.8 |
| `POST /providers/discover` **Stage 10C** | the discovery **offer**: `[{kind, provider_id, model_ids[], source_path}]` — never a secret, never a masked tail, and it runs **only** on this explicit request | §23.5 |

`POST /providers/discover` is a `POST` and sits in the read table on purpose: it
returns a projection and mutates nothing, but it reads the operator's
home directory, so it must never be reachable by a `GET` a page can issue
incidentally. It requires no idempotency key, on the same argument as the
credential mutations below.

**Credential mutations — key not required, and sending one is ignored — Stage
10B, plus `POST /providers/adopt` at Stage 10C.** `POST /providers/attach`,
`POST /providers/{id}/auth/key`,
`.../auth/begin`, `.../auth/complete`, `.../auth/cancel`, `.../auth/signout`,
`POST /providers/auth/unlink`, `POST /providers/adopt`. Each carries its own no-key argument in §23.6;
none is a source, config, or output mutation, and a byte-for-byte replay of a
credential rotation would be a silent security failure.

Absent, deliberately: no `POST /artifacts` (the workspace mints nothing), no
`DELETE` anywhere — sign-out is a `POST` because signed-out is a *state*, not an
absence (§23.9) — **no route that takes a raw filesystem path in a request
body**, no OAuth callback route, and no route that returns credential
material. The `auth_source` path is specifically **not** admitted into any
request body (§23.5): it is the path the server symlinks the project's
credential file at, and Pi subsequently writes through it.

**AMENDED 2026-08-28 (Stage 10C), and narrowed rather than widened.** This rule
previously read "in **either** direction". Discovery has to name what it found
or the offer is unreadable, so the outbound half is now an enumerated exception
and the inbound half is stated more strictly than before:
`POST /providers/discover` returns a `source_path` **as display text**, beside a
server-minted opaque `discovery_id`. `POST /providers/adopt` takes the
`discovery_id` **only**; a body carrying a path — under any key — is refused
`path_not_web_writable` by name, exactly as `PUT /providers/specs` refuses
`auth_source`. The direction that matters is inbound: a client-supplied path is
what turns a credential route into a traversal primitive, and no route accepts
one. Outbound, on a loopback-only serve, the server is telling the operator
where their own file is.

**What changed about "no export route".** Until the 2026-08-28 review this row
read *no export/drawing/document routes (§15)*, and justified itself with
`/artifacts/{ref}/bytes` being closed by enumeration. §22 answers the product
half of that deferral, and §2.6 corrects the mechanism half: the enumeration
constrains which **named surface** serves export bytes and — until §19.24 lands
— does **not** constrain reachability, because the route resolves by hash and
the kind segment is a caller-supplied label. Both halves are stated where they
are enforced rather than asserted here.

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
shipped code (`cad_ops/_artifacts.py`:22-34). Deriving one policy from another
set's membership meant a refusal stated in prose was contradicted by a route
nobody had re-read. That defect is real and the enumeration fixes it.
`selection-crop` (§12.5) is on the list because Stage 5 mints it; there is no
`selection-pass` kind — the three pass layers are `selection-solid`,
`selection-face`, `selection-edge`.

**CORRECTION (2026-08-28 review). The enumeration is not the boundary this
section claimed it was, and the claim is withdrawn rather than repeated.**

An earlier revision of this paragraph said the enumeration made §15.17 "a
statement about what the server will serve". It does not, and the reason is
mechanical: `artifact_kind(ref)` (`http/artifacts.py`:127-136) reads the kind
out of the **caller-supplied string**, and `_blob()` resolves by
`blob_hash_of_ref(ref)` against the project's blob store. Nothing checks the
ref's kind segment against the stored blob. Export outputs go into that same
blob store (`_commit_export` does `blobs.put` → `gc.pin` → `gc.link`).
Therefore `GET /artifacts/artifact:build:sha256:<an export blob>/bytes` serves
export bytes **today**, and the only thing standing in the way is that no client
knows the hash. The pytest that submits an `artifact:export:…` ref and asserts
a refusal passes and proves less than it appears to: it tests a *label*, and
relabelling is free.

This matters now because §22 is the change that hands every client the hashes,
in `export_hashes` on three POST responses and in `GET /parts/{part}/exports`.

**NEW WORK (§19.24) — bind the kind to the blob.** The artifact kind is recorded
alongside the blob at publication, and `_blob()` verifies the ref's kind segment
against the stored one, refusing `artifact_kind_mismatch`. Only then is the
enumeration a boundary rather than a naming convention, and only then can
§15.17's replacement sentence be true. **This is a prerequisite of §22: neither
`GET /parts/{part}/exports` nor `export_hashes` in a response body ships to a
browser before it lands.** Stated as an ordering constraint and not as a
preference, because the failure it prevents is one the product would ship
believing it had prevented.

**TIGHTENING (binds this route, and it does not wait for §19.24).** Every
response from this route carries `Content-Disposition: attachment` and
`X-Content-Type-Options: nosniff`. WHY: an SVG is a document with script
capability, the workspace origin holds the bearer token, and an inline-rendered
artifact SVG would be script execution on the token's origin initiated by
geometry. §22.3 puts the same two headers on the export-bytes route; putting
them only there would have left the mitigation on the route an SVG **cannot**
currently be fetched through while omitting it from the one it can. Two headers,
both routes, no exceptions.

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

## 3. `web/` — stack and visual system

### 3.1 Stack — unchanged and still correct

Binding by convention (named in `repo_conventions.md` and `architecture.md` §6,
not in gate text) and treated as fixed: **TypeScript (strict) + React 18 +
Vite**, pnpm workspace; **Monaco** for script and diff; **three.js** for the
viewport; **GLTF/GLB** as the geometry wire format; **Playwright** for
`pnpm test:e2e`, which is the literal gate command. CI runs eslint and
`tsc --noEmit`.

| Decision | Choice | WHY / rejected |
|---|---|---|
| Server state | TanStack Query | Server state is almost entirely content-addressed and cacheable **by ref** (§2.6); refetch/invalidate is the whole problem. §7A.11 finally makes invalidation a specified boundary rather than an implied one. |
| Workspace state | one module over `useSyncExternalStore`, no state library | The pin must have exactly **one** authority (§4.5) and must be URL-serializable, which is a flat record, not a reducer ceremony. *Rejected:* Zustand and Redux Toolkit — a dependency whose only output is a store this small; and bare per-component `useState`, which cannot hold a single pin authority. |
| Router | None; hand-rolled URL state sync | One route (§4.5). A router would exist only to parse a query string. |
| Bundle delivery | built assets ship inside the wheel, served by `--web` from `importlib.resources` | The packaged-sidecar precedent. Vite's dev server is a development convenience proxying `/api` to a running `heph serve --web`. `@autonome/hephaestus-web` stays reserved and unpublished. |

### 3.2 The dependency decisions, revisited — and the row that was wrong

The original §3 table rejected Tailwind, every component library, and (as read
below) every icon *package*, and the product owner then reported that the
result "looked pretty bad". Every rejection was re-argued against the shipped
pixels. **Every dependency rejection is upheld. One row was wrong about what it
had bought. One rejection was upheld and was never implemented.**

| Decision | Original | Ruling | WHY |
|---|---|---|---|
| Styling | CSS Modules + a design-token file | **Upheld as a mechanism; wrong as an answer.** | Tailwind would not have picked a type ramp, assigned roles to it, given `pass`/`fail`/`error` distinct colour, right-aligned a numeric column, or lit a three.js scene. Every defect §3.3 enumerates would have shipped byte-identically on top of it, plus a `node_modules` entry. The `data-*` testability argument also survives: the e2e addresses the DOM through 28 distinct `data-*` attributes and the app mints 93; class-soup selectors would compete with that contract for the same job. |
| Component library | None | **Upheld.** | §4.2's inventory is 28 entries, of which 24 are project-specific instruments. A library ships an accordion, a date picker, and a modal; this workspace needs a provenance popover, a section control, and a tool chip. *Rejected again:* Radix, Ark, Base UI. |
| Icon package | "any icon package **beyond an inline SVG sprite**" | **AMBIGUOUS — tightened.** | The sentence parses two ways: an inline sprite is the permitted alternative, or even a sprite is refused. **TIGHTENING (binds §3, no gate clause):** the permissive reading is in force — a repo-owned inline SVG sprite is permitted and is now **required** (§3.12). Evidence that this needed saying: `web/src` and `web/public` contain **zero** `.svg` files and zero `<svg>` elements. The sprite was not rejected; nobody built the thing the sentence already allowed. |
| Accessibility | "a stated floor, not a gap" | **Upheld as policy; the floor was not met.** | The row asserted a floor with no number, and the shipped app falls under it in four named places. §3.13 replaces it with measurable clauses. |

**The row that was wrong, and the arithmetic that convicts it.** *CSS Modules +
a design-token file* is a **delivery mechanism**, not a design system. Measured
on the shipped tree:

- `tokens.css` defines a five-step type ramp; across `web/src/**/*.css` there are
  91 `font-size: var(--size-*)` declarations — `xs` **65**, `sm` 21, `md` 3,
  `lg` 1, `xl` 1. The single `lg` is a `›` chevron; the single `xl` is the
  no-token failure screen. **The workspace has no heading anywhere.**
- Five ground tokens exist; four are used, `--ground-raised` **zero** times.
  Rail against Stage measures **1.068:1**. The shell is one flat field divided
  by hairlines.
- `--space-1..5` are used 45 / 88 / 37 / 6 / 6. The scale is fine; the **role
  assignment** is missing, which is why panel, overlay, and drawer padding do
  not agree.
- Five bordered-pill classes exist in `panels.module.css`. `.toggle` is a
  `<button>`; `.state` is inert text; their `border` declarations are
  **byte-identical**.

**DECISION: add no dependency; add a system layer** (`web/src/system/`, roughly
350 lines of TSX + CSS Modules) that owns both the markup contract and the
styling contract for every primitive. The two most damaging defects found are
failures of **ownership**, which is exactly what a dependency cannot supply:

1. `ChecksPanel.tsx`:59 writes `data-badge` onto the `<li>` while
   `panels.module.css` selects `.badge[data-badge=…]` on the element one level
   down; `Fact.tsx` has no `data-badge` prop, so nothing matches and `pass`,
   `fail` and `error` all compute to the same colour, the same border, and
   `::before { content: none }`. `DfmPanel.tsx`:132 does it correctly two files
   over, which is the proof it was a slip and not a position. A
   `<Badge status=…/>` that owns both halves makes this **unrepresentable**;
   Tailwind makes it identically representable.
2. `Shell.module.css` collapses the stream column to 44px by media query while
   `Shell.tsx`'s `useState(true)` decides whether the panel renders its
   contents. Two sources of truth for one fact, disagreeing between 1024 and
   1279px. A `useBreakpoint()` hook feeding the store makes it unrepresentable.

*Rejected:* "just fix the CSS files in place" — it leaves the contract implicit,
which is what produced both bugs.

### 3.3 Design principles — a dense professional instrument with a collaborator in it

Five, ordered; a later one never overrides an earlier one.

1. **The measurement outranks the chrome.** The brightest, largest,
   highest-contrast thing on screen is the part, then the numbers about the
   part, then the words about the numbers, then the furniture. The shipped app
   inverts this: the rendered mesh samples `rgb(25,25,34)` on a `rgb(13,15,18)`
   ground — **1.10:1**, the dimmest object in frame — while the `iso` view-cube
   button carries a solid accent fill that is the loudest. §3.11 and §4.7 fix
   both ends.
2. **Hierarchy is carried by size and weight before it is carried by colour.**
   65 of 91 type declarations at 11px is a workspace telling the reader that
   nothing is more important than anything else.
3. **A control and a readout must be distinguishable without hovering.** Two
   primitives differing in *kind*, not degree: a readout has a tinted fill and
   no border; a control has a raised surface and a border.
4. **Furniture does not move.** Measured canvas heights by inspector tab today:
   results 412 · properties 366 · checks 494 · dfm 645 · provenance 617 — a 76%
   swing that re-fits the 3D camera on every tab click. A drawer is furniture.
5. **The agent is a peer surface, and its emptiness must look designed.** The
   stream column is a full-height peer (§4.1) precisely to cash out
   "collaborator, not console". A peer column whose entire content is two italic
   12px sentences at 3.10:1 contradicts the layout claim. Every state — refusal,
   absence, "no runtime attached" — is a first-class composed state with a
   shape, an icon, a heading, and where an action exists, a button.

### 3.4 The system layer

```
web/src/system/
  tokens.css          palette + semantic layer (§3.6, §3.9)
  type.module.css     the seven type roles (§3.8)
  icons.tsx           the closed sprite (§3.12)
  Badge · Button · Chip · DataTable · Field · Panel · TabBar
  TreeRow · Input · Popover · EmptyState        (.tsx + .module.css each)
  useBreakpoint.ts    the single authority for §4.1's breakpoints
  format.ts           the numeric render boundary (§4.7 DataTable)
```

**Rule (mechanically enforced, §3.14): a component under `web/src/components/`
may not declare a `font-size`, `color`, `border`, `border-radius`, or
`background` on a text-bearing element.** It composes a type role and renders a
system primitive. Panel-local CSS Modules survive only for *layout*.

**DECISION: primitives own their `data-*` contract.** `<Badge status="pass"/>`
emits `data-badge="pass"` on the element it styles. *Rejected:* leaving `data-*`
to call sites, which is the shipped arrangement and the direct cause of the
check-badge bug.

**TIGHTENING (binds §1, and it is the constraint that shapes `DataTable`).**
No primitive takes a `source` **string** and mints a `<Fact>` from it. §1's
boundary is enforced by `heph/no-derived-fact`, whose first rule is that
`<Fact source>` must be a *static, dotted, literal* path — "a computed `source`
would let a component mint an attribution at runtime, which is attribution
theatre" (`no-derived-fact.js`:12-25). A `rows={[{source: "…", value}]}` API is
exactly that computed source, one indirection away, and it would not survive the
lint the same repo already runs. **Row APIs therefore carry a `ReactNode`,
constructed by the caller**, so every attribution stays a reviewable literal at
the call site. This costs three characters per row and keeps §1 untouched; the
alternative — amending `no-derived-fact` to admit a dynamic source — is a real
option, but it is a change to the boundary §1 exists to hold and it is not made
here.

### 3.5 Themes — one, and the seam is named

**DECISION: dark only.** *Rejected:* shipping light and dark now. The dominant
surface is a WebGL viewport whose ground must be darker than the part (§3.11);
a light theme is not a token flip there but a second viewport treatment plus a
second set of status hues that survive on white — real work with no gate behind
it, and half-doing it produces light chrome around a dark hole. What is *not*
deferred is making it addable: the token file is two layers, so a light theme is
a second palette block under `:root[data-theme="light"]` with **no component
changes**, because no component may reference a palette token. Light theme is an
§18 amendment candidate, not a §19 item.

### 3.6 Token architecture — two layers, and the second is the only public one

Layer 1 is a **private palette**: raw hue lives there and nowhere else, and a
component referencing a `--p-*` token or a literal hex fails `no-palette-token`
(§3.14). Layer 2 is the **semantic layer** and is the entire public API.

**WHY two layers.** The shipped `tokens.css` has one, so `--ground-1` means both
"the rail" and "the fill behind a DFM finding card", and there is no name for
"the surface a button sits on" — which is why five pill classes each invented
their own border. A semantic name is a decision recorded once; a palette name is
a colour anyone may spend anywhere.

### 3.7 Space — the scale was right, the roles were missing

The five existing steps keep their existing values (`--space-1..5` = 4 · 8 · 12 ·
16 · 24px), so no shipped rule changes meaning; `--space-0: 2px` and
`--space-6: 32px` are added. What is new and load-bearing is the **role set**
components actually reference: `--pad-panel`, `--pad-panel-header`, `--pad-row`,
`--pad-control`, `--pad-overlay`, `--gap-inline`, `--gap-stack`, `--gap-group`,
`--gap-section`. A component may reference `--space-*` only for a one-off
geometric offset it names in a comment. This is the difference between "12px
because that's the rhythm" and "12px because I typed it".

### 3.8 Type — seven roles, and 11px is confined to one of them

Faces are unchanged. The five `--size-*` tokens become palette-layer and
private; the public API is seven role classes consumed with `composes:`:

| Role | Size / weight | Face | Used for |
|---|---|---|---|
| `.display` | 18 / 600 | ui | fatal + no-token screens only |
| `.title` | 15 / 600 | ui | panel headers, dialog titles, part name, empty-state heading |
| `.body` | 13 / 400 | ui | prose, transcript text, empty-state and refusal copy |
| `.label` | 12 / 500 | ui | tab labels, button text, control labels, tree rows |
| `.data` | 12 / 500 | mono, `tabular-nums` | every number the user reads |
| `.code` | 12 / 400 | mono | refs, hashes, selectors, script, tool names |
| `.eyebrow` | 11 / 600, `0.08em`, uppercase | ui | section eyebrows above a group |

**TIGHTENING (binds §3, no gate clause): 11px may appear only inside
`.eyebrow`**, checked mechanically. This one rule converts the shipped 65-of-91
distribution into a ramp with a shape: eyebrows 11, controls and data 12, prose
13, panel titles 15.

### 3.9 Colour — semantic roles, with the ratio each one guarantees

The semantic layer names six surfaces (`canvas · app · panel · raised · control ·
overlay`), four inks (`strong · base · muted · faint`), three lines (`border ·
border-strong · border-control`), four accents, and five statuses each carrying
an **ink** and a **16% fill**. Every role ships with its measured WCAG ratio
against every surface it is permitted on, and the permission table is the
normative artefact — not the hex values.

**Two refusals encoded in that table.**

- `--ink-muted` is **forbidden on `--surface-overlay`** (3.87:1). Use the base
  ink.
- `--ink-faint` is **not a text token at all.** Permitted only on `app`, `panel`
  and `canvas`, and only for non-essential marks: a separator glyph, a
  decorative rule. **No prose, no unit column, no disabled-control label.** This
  retires the shipped defect directly: `--ink-3` on `--ground-1` measures
  **3.10:1** and is the empty-state colour in four files plus `.note` at 11px
  italic. Empty-state prose moves to the base ink at `.body` and loses the
  italics. *(2026-08-28 review correction: an earlier draft of this section
  declared `--ink-faint` non-text and then assigned it as text twice, in the
  `DataTable` unit column and on disabled controls. Both assignments are struck;
  the unit column and disabled-control text are `--ink-muted`.)*

**Line tokens are in the table too, and one of them had to move.** *(2026-08-28
review correction.)* An earlier draft's guarantee table contained no line token
at all, while §3.13's floor promised non-text UI ≥ 3:1 and §3.10 made
`--border-control` "the mechanical form of principle 3" — the sole signal
distinguishing a control from a readout. At the proposed value it measured
1.85–2.54:1 against the surfaces it sits on: **the half of the floor that failed
was the half the table omitted.** `--border-control` is therefore specified as
*whatever value clears 3:1 against both its own fill and every surface it is
permitted on* (≈`#6f7c92` against `--surface-control` reaches it), and the
guarantee table carries a line-token block measured against each. A floor whose
own load-bearing token fails it is prose again, which is the exact criticism
§3.13 opens with.

**Surface separation.** Adjacent rungs measure 1.066 to 1.237. That is
deliberately modest and is **not** the mechanism: in a dark instrument palette,
plane separation is carried by the **border**, not the fill — a fill pair strong
enough to read as two planes on its own is a mid-grey UI, which loses principle
1. **Rule: every boundary between two named surfaces carries a 1px `--border`,
or a 1px `--border-strong` where a card must read as detached.** The shipped
1.068 rail/stage figure was a defect not because 1.068 is wrong but because the
seam was a hairline and the ladder had two rungs in play.

**Colour is never alone.** Every status carries **ink + fill + glyph + word**.
The shipped `--glyph-*` values survive verbatim and move into the sprite
(§3.12), because a `content:` pseudo-element is not reachable by a screen reader
and the shipped token file's own header already claims "every badge carries a
glyph and a label".

### 3.10 Elevation, radius, border, focus, motion

**Elevation** is the six-rung surface ladder plus exactly two shadows
(`--elev-popover`, `--elev-dialog`). There is no third. Assignment is closed:
`canvas` → viewport only · `app` → page and stage · `panel` → header, rail,
stream, inspector drawer · `raised` → tab bars, row hover, cards, status fills ·
`control` → buttons and inputs at rest · `overlay` + popover shadow →
`SelectionPopover`, `MeasureHUD`, tooltip, view-cube plate, and (§22, §23)
`ExportPanel`'s disclosure and `SignInDialog`'s anchored menus · `overlay` +
dialog shadow → `ConflictDialog`, `TagDialog`, `SignInDialog`. A surface not on
this list is not a surface.

**Radius.** 3px controls/badges/chips, 6px cards/popovers/overlay plates, 10px
dialogs, `999px` **badges only**. The shipped split between `.badge` (pill) and
`.toggle`/`.chip`/`.state` (3px) is kept and made meaning-bearing: **pill
reports, 3px acts.**

**Borders.** `--border` for seams, `--border-strong` for a detached card or
readout, `--border-control` for every interactive control **and only** for
interactive controls. This is the mechanical form of principle 3, and it is the
rule the shipped `.toggle`/`.state` pair violates byte-for-byte.

**Focus.** `:focus-visible { outline: 2px solid var(--focus-ring);
outline-offset: 2px }`, up from the shipped 1px so a ring on a control sitting
on a raised surface is not swallowed by its own border. The viewport canvas gets
the same ring at `outline-offset: -2px` so it draws inside the canvas.

**Motion.** Three durations (90 / 160 / 240ms), one easing. **Refusal: nothing
animates that carries a measurement.** A metric, a badge, a check row and the
viewport camera change instantly — an instrument that eases a number into place
has made the reader wait to trust it. The existing `prefers-reduced-motion`
block is kept verbatim.

### 3.11 The viewport is not chrome — the one problem no CSS solves

`viewport/engine.ts`:74 reads `const BACKGROUND = new Color("#0d0f12")` and its
own comment claims "the geometry is the bright thing". That value **is** the
app's darkest chrome surface. Sampled from the shipped screenshots the mesh is
`rgb(25,25,34)` on `rgb(13,15,18)` — 1.10:1. `engine.ts` adds `gltf.scene`
verbatim and authors no material, so the part's appearance is whatever
`baseColorFactor` the server's GLB happens to carry; the client holds no display
opinion. There is no `outputColorSpace`, no tone mapping, no edge pass, no grid
and no axis triad — despite `GridReadout`, which is a text box reading
`View iso / Scale 172 mm` about a grid that does not exist.

**NEW WORK (§19.28), normative:**

1. A viewport ground distinct from every chrome surface, on both
   `setClearColor` and `scene.background`.
2. **The client authors the material.** Every loaded mesh is overridden with a
   `MeshStandardMaterial` at a specified part colour. **Floor: ≥ 4.5:1 part vs
   ground, exporter-independent**, measured in the browser (§3.14).
3. `outputColorSpace = SRGBColorSpace`, `toneMapping = ACESFilmicToneMapping`.
   Without these the linear output is exactly the flat desaturated grey the
   screenshots show.
4. **Silhouette + feature edges** via `EdgesGeometry(geom, 25)`, `depthWrite:
   false`. The single highest-value CAD viewport affordance, ~15 lines.
5. **Ground grid**, spacing driven by the same scale `GridReadout` already
   reports, so the readout finally describes something visible.
6. **Axis triad**, bottom-left, in the Z-up frame `engine.ts` already
   establishes.
7. Lights ride with the camera, unchanged — `engine.ts`'s reasoning ("the
   picture is an instrument reading, not a beauty render") is correct.

**Named consequence for G4.5, stated rather than discovered.** G4.5's evidence
is a **self-referential** before/after delta inside a decoded solid-pass mask
against an outside control region (§5.4), so authoring the material does not
invalidate the method. It does move the numbers: §21.10 already records that the
0.10 / 0.01 thresholds are chosen rather than measured, and they must be
**re-derived against the new material before this work lands**, not loosened
after it. G4.7 is untouched: the section render is server pixels and the client
preview is non-evidentiary (§5.3).

### 3.12 Iconography — a closed, repo-owned sprite

`web/src/system/icons.tsx` exports one component over a **closed vocabulary of
18 ids** spanning status, structure, object and action. Adding an id is a spec
edit, exactly as adding a panel is. Rules, all mechanical: single path,
`viewBox="0 0 16 16"`, `stroke="currentColor"`, no `<style>`, no gradient, no
embedded colour — so an icon inside a danger-ink badge is red with no
icon-specific rule. `aria-hidden` unless the icon is a control's only label, in
which case the control carries `aria-label` from `copy.ts`.

**Refusal:** no icon font, no `@iconify`, no Lucide, no Heroicons. The bundle
ships inside a Python wheel and its weight is the operator's download — the
original §3 reason, still correct.

**Refusal:** icons never replace words in a status. `<Badge>` renders **icon +
word**, always. The 18 ids exist to make a scan *faster*, never to make it
*possible*.

### 3.13 Accessibility floor — replacing the original §3 row

The previous row asserted a floor with no number. This one is numeric and
testable.

1. **Contrast.** All text ≥ **4.5:1** against its own surface. Non-text UI that
   carries meaning — focus ring, control border, status fill edge, selected-tab
   underline — ≥ **3:1** against its adjacent surface, **including
   `--border-control`**, whose permitted pairings are enumerated in §3.9's table
   and checked by §3.14's fourth check.
2. **No colour-only encoding, verified rather than asserted**, on the split
   substrate §3.14 specifies: every badge state differs in icon **and** text,
   not only in colour.
3. **Focus visibility** on every keyboard-reachable control including the
   viewport canvas.
4. **Keyboard reachability.** Every control except the orbit interaction is
   reachable by Tab. Tab bars implement roving tabindex with
   `role="tablist"`/`tab`/`aria-selected`; the rail tree implements arrow-key
   navigation with `role="tree"`/`treeitem`/`aria-expanded`; popovers trap focus,
   restore it to the opener, and close on `Escape`. The rail overlay below
   1024px gains a scrim and a close control — today it has neither and **cannot
   be dismissed at all**.
5. **Live regions.** `aria-live="polite"` on run-terminal transitions and the
   pager; `assertive` on `RefusalBanner`.
6. **Target size.** Every control ≥ 24×24px hit area, achieved by padding rather
   than font-size. The shipped 11px pill controls are ~18px tall.
7. **Reduced motion.** The existing block, unchanged.

### 3.14 Mechanical enforcement — four checks, on the `no-derived-fact` precedent

§1 made the client boundary a lint rule rather than a promise. The same move
applies here; without it this section is a mood board with hex codes. All four
are grep-shaped `node` scripts run by `pnpm lint`, adding no dependency.

| Check | Rule | Failure mode it retires |
|---|---|---|
| `no-palette-token` | No file outside `system/tokens.css` may reference `var(--p-*)` or a literal hex outside a `.svg`. | Hue spent ad hoc; the reason `.chip` and `.state` diverged. |
| `no-raw-type` | No file outside `system/type.module.css` may declare `font-size`, `font-weight`, `letter-spacing`, `text-transform`, or `font-family`. | The 65-of-91 collapse to 11px. |
| `system-owns-status` | No `data-badge`, `data-severity`, or `data-chip-status` may appear in a file that does not also declare the matching CSS in the same directory. | `ChecksPanel.tsx`:59 — an attribute one element away from its selector, silently. |
| `token-contrast` | Parses `tokens.css`, computes every declared role × permitted-surface pairing, and asserts each meets its §3.9 floor — **text ≥ 4.5, meaningful non-text ≥ 3.0.** | §3.13.1 being prose. This is the check that catches a `--border-control` at 1.85:1, which is how that defect reached a spec draft. |

**Plus test coverage split by substrate — and the split is the point.**
*(2026-08-28 review correction: an earlier draft put the whole no-colour-only
assertion in Playwright over the fixture, where it cannot run. `not_run` has no
producer in the public clean-room fixture, deliberately and with a written
refusal, so a browser assertion over it has nothing to render.)*

- **Component test** (`vitest` + jsdom) renders **all six** `Badge` statuses
  directly and asserts a distinct icon id **and** distinct text for each. This
  covers `not_run` without faking an engine state, and it is what actually
  catches the `ChecksPanel` class of bug. It also forces the vocabulary to be
  honest: two statuses may not share an icon id, so `info` and `dirty` take
  different ids rather than both taking `dot`.
- **`web/e2e/design-system.spec.ts`** asserts only over what the fixture
  reaches, matching the existing enumeration in `dom.spec.ts`, and says so:
  sampled computed contrast for every ink and status ink against its rendered
  background ≥ 4.5; the viewport canvas's centre pixel ≥ 4.5:1 against its
  corner pixel when geometry is loaded (the part-vs-ground floor of §3.11.2);
  grid columns at 1440 / 1280 / **1279** / 1024 / 1023 matching §4.1's table
  with `document.body.scrollWidth === clientWidth` at all five; and the
  inspector canvas height identical across all five inspector tabs.

**Clean-room hygiene, inherited verbatim and unchanged:** no "Smith" or "Arche"
in identifiers, packages, filenames, or copy; the visual language may differ and
here deliberately does; and **no test asserts the reference product's message
text or UX copy** — assertions are on fields and information content. All
workspace copy is invented and lives in one module (`web/src/copy.ts`) so a
reviewer can audit it in one file.

**Migration acceptance criterion.** The existing e2e suite is expected to need
**no selector changes**: all 28 `data-*` selectors it uses are preserved by the
primitives that now own them. That is the testability claim of §3.2, and it is
how this migration is judged. It covers the shipped panels; the four surfaces
this amendment adds — `Composer` (§7A), `ExportPanel` (§22), `ProvidersPanel`
and `SignInDialog` (§23) — are built **on** the system layer from their first
commit and are named in §4.7 so that complaint 3 is not answered for every
surface except the three the operator asked us to add.

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

**AMENDED 2026-08-28 — three corrections, each a defect the shipped build can
be measured exhibiting.**

**(a) The breakpoint has one authority, not two.** Measured today:

| width | `grid-template-columns` | stream box | stream `scrollWidth` | body overflows |
|---|---|---|---|---|
| 1440 | `280px 740px 420px` | 420 | 419 | no |
| 1280 | `280px 580px 420px` | 420 | 419 | no |
| **1279** | `280px 955px 44px` | **44** | **81** | **yes** |
| **1024** | `280px 700px 44px` | **44** | **81** | **yes** |
| 1023 | `979px 44px` | 44 | 81 | yes |

`Shell.module.css` collapses the column; `Shell.tsx` decides whether the panel
renders. Between 1024 and 1279 they disagree and `StreamPanel` shreds into a
one-word-per-line ribbon. 1280×800 is the default MacBook Air logical
resolution and any half-screen split on a 2560px monitor lands inside the broken
band; this is not an edge case.

**TIGHTENING (binds G4's shell deliverable):** `web/src/system/useBreakpoint.ts`
is the **sole** authority. It writes `streamOpen` / `railOverlay` into workspace
state; `Shell.module.css` keeps **no** media query that changes
`grid-template-columns`; the grid is driven by `data-stream` and `data-rail`,
which React sets. A user's explicit collapse survives a resize inside a band and
is re-evaluated on a band crossing. **The Stream strip is a control, not a
narrower panel** (§7A.1): focusing or activating it expands the column, because
a composer cannot live in 44px.

**(b) `data-rail` is wired, not deleted.** `grep -rn 'data-rail' web/src`
returns exactly one hit — the CSS rule that consumes it. Nothing sets it, so
below 1024px the rail is a 280px absolutely-positioned overlay covering a third
of the stage with no scrim, no close control, and **no dismissal**.
`useBreakpoint` sets it; the header gains a rail toggle; the overlay gains a
scrim, an `Escape` handler, and trapped focus (§3.13.4).

**(c) The inspector drawer stops resizing the viewport.** §4.1 says the drawer
is "resizable"; the code makes it *variable* — `grid-template-rows: minmax(0,1fr)
auto` with a 132px floor — which is not the same thing and is what produces the
76% canvas-height swing of §3.3.4. The stage row becomes an explicit
`--drawer-height` (`clamp(200px, 32vh, 420px)` by default) with a 6px drag
handle writing it into workspace state; `.content { overflow: auto }` already
exists and takes the excess. Height is then identical across tabs **by
construction**, which §3.14's e2e asserts.

**Header layout.** The header grid is a symmetric three-up centring the artifact
pin, so with a short project name roughly 450px of the left cell and 350px of
the right are dead in a 44px bar. It becomes `auto 1fr auto`, left-aligned on
one baseline, reading **identity → pin → build state → token**, with one
dominant element in the pin chip (the ref, in `.code`) and `ARTIFACT PIN`
demoted to a title attribute. **Copy defect, fixed at the same time:**
`copy.ts`:58 (`pin.current`) and :62 (`buildState.current`) are two different
closed vocabularies that both spell "current", rendered in two chip styles
~600px apart on two different axes — pin freshness versus build state. The
build-state vocabulary changes `current` → **`up to date`**; the pin vocabulary
keeps `current`. Two axes, two words.

### 4.2 Panel inventory (closed for Stage 4/5)

`ProjectTree`, `GitDirty`, `VersionList`, `Viewport`, `ViewCube`, `GridReadout`,
`ExplodeSlider`, `SectionControl`, `SelectionPopover`, `MeasureHUD`,
`ScriptEditor`, `Timeline`, `DiffView`, `ResultsPanel`, `PropertiesPanel`,
`ProvenancePanel`, `ChecksPanel`, `DfmPanel`, `ParamSliders`, `StreamPanel`,
`ToolChip`, `ThoughtSection`, `EventImage`, `AskUserWidget`, `Composer`,
`ConflictDialog`, `TagDialog`, `ArtifactPin`, `Fact`.

A panel not on this list is not Stage 4/5 work (§18).

**`Composer` is on this list and always was**, on a list whose heading closes it
for Stage 4 **and** Stage 5 jointly. Nothing in this section ever assigned it to
Stage 5; §7A.9 states what actually gates it and strikes the citation that
claimed otherwise.

**System primitives are not panels.** `Badge`, `Button`, `Chip`, `DataTable`,
`Panel`/`PanelHeader`, `TabBar`, `TreeRow`, `Field`, `Input`, `Popover`,
`EmptyState`, `Icon` live in `web/src/system/` (§3.4) and are *how* a panel is
built, not entries in this inventory. Adding one is not §18 work; adding a
**panel** still is.

**Three panels join the inventory under Stage 10, and are marked as such.**
`ExportPanel` (§22.7) is **Stage 10A**; `ProvidersPanel` + `SignInDialog`
(§23.8) are **Stage 10B**, with the panel's discovery affordance **Stage 10C**
(§23.5). They are **not** Stage 4/5 work and do not become so by appearing here. They are
listed because a closed list that silently acquires members is not closed, and
because §3.14's migration criterion has to be able to name them.

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
  stage_tab: "viewport" | "script" | "timeline" | "results" | "diff"
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

**`Fact.tsx` is unchanged by the §3 design-system amendment**, and that is a
constraint on the primitives rather than a note about them (§3.4's tightening).
`DataTable` and `Field` take a constructed `ReactNode`, never a `source` string,
so every attribution stays a static literal the lint and a reviewer can both
read out of the source tree.

### 4.7 Component specifications (system layer)

Each primitive states its markup contract, its `data-*` contract, and the
shipped defect it retires. This is where §3.4's ownership rule becomes concrete.

**`Panel` / `PanelHeader` / `PanelBody`.** Grid `auto minmax(0,1fr)`,
`min-height: 0`; header at `--pad-panel-header` with a `--border` bottom, title
in `.title` — **the app's first heading level anywhere** — optional `.eyebrow`,
right-aligned actions; body at `--pad-panel`, `overflow: auto`, stacked at
`--gap-group`. *Retires:* no heading level in the product, and every panel
declaring its own padding and disagreeing.

**`TabBar`.** `role="tablist"`, roving tabindex, arrows, Home/End. Selected
state is `box-shadow: inset 0 -2px 0 var(--accent)` — **not** a border, so the
bar does not reflow on selection. Emits `data-{attr}`, preserving
`[data-stage-tab]` and `[data-inspector-tab]` verbatim for the e2e. *Retires:*
three tab bars hand-rolled with three paddings and no keyboard pattern.

**`TreeRow`.** `role="treeitem"`, `aria-expanded`, `aria-selected`, 26px,
indent by depth, disclosure chevrons from the sprite, selected marked with an
inset accent rule. The §13.1 dirty marker is a `Badge` variant carrying an
`aria-label`, **never a bare coloured dot**. *Retires:* colour-only dirty
markers; a tree with no keyboard navigation.

**`DataTable` — one primitive for all four inspector panels.** Three columns:
label (`.label`, `--ink-muted`), value (`.data`, **right-aligned,
`tabular-nums`**), unit (`.label`, `--ink-muted`, left-aligned so units form
their own column). All `DataTable`s inside one panel share one grid via
`subgrid`, so columns align down the whole drawer. **Rows carry a `ReactNode`
value** — the caller writes `<Fact source="build.metrics.area_mm2" …/>` itself
(§3.4, §4.6). `format.ts` is the render boundary and the only place a number
becomes a string; §1 is untouched, because formatting is presentation, not
derivation, and `<Fact>`'s `data-value` still carries the unformatted server
value. *Retires, all four at once:* `74289.99999999999` shipped to an engineer
as a measurement; left-aligned numerals with no tabular figures; units welded
into SCREAMING_SNAKE API keys (`AREA_MM2`, `BBOX_MM`) and shown raw; and a
200px table floating in a 1490px panel with the Properties value column
visibly jogging between two groups that each compute their own `max-content`.

**`Field`.** One key/value fact on the same three-column geometry, for panels
carrying a fact rather than a table. Replaces the `<dl>` grids in
`PropertiesPanel` and `ProvenancePanel`.

**`Badge` — the readout primitive, and the P0 bug fix.** Emits
`data-badge="…"` **on the element it styles**, and renders icon **+** text,
always both, on a tinted status fill with **no** border (`not_run` takes a
dashed `--border-strong` so an absence reads as an absence). Closed vocabulary:
`pass · fail · error · not_run · info · dirty`, each with its **own** icon id
(§3.14 — two statuses sharing an id would make the distinctness assertion false
by construction). *Retires the shipped P0:* `ChecksPanel.tsx`:59-60 puts
`data-badge` on the `<li>` while the CSS selects `.badge[data-badge=…]`, so
`pass`, `fail` and `error` compute identically — label-only encoding at 11px in
a surface whose entire job is "did my part pass", in a file whose own token
header claims the opposite. Note also that the **fill is required, not
optional**: a 1px hairline in an accent hue at 11px is not a status signal at
arm's length, which is what the shipped rule would have produced even had the
selector matched.

**`Chip`.** The other readout: raised fill, **no border**, 3px radius, inert by
contract — it renders a `<span>` and takes no `onClick`.

**`Button` — four variants and nothing else:** `primary` (accent fill, one per
surface at most), `secondary` (the default), `quiet` (toolbar and row actions),
`toggle` (`aria-pressed`, accent-quiet fill when on). All ≥ 24px min height.
**Disabled requires a `reason` prop**, rendered as `title` +
`aria-describedby`: a disabled control in this app must always be able to say
why — which is the same rule §7A.8 applies to the composer and §22.7 to a
refused export. *Retires the shipped P1:* `.toggle` (a `<button>`) and `.state`
(inert text) ship byte-identical borders, so the affordance is absent **by
construction**. Five bordered pills collapse to two kinds: readouts have a
tinted fill and no border; controls have a control surface and a control
border. Same fix, same commit: `DfmPanel.tsx`:225 renders *"Automatic
evaluation after each build: off"* as a chip in the panel's action corner,
looking exactly like a settings toggle, and the panel's prose then has to
apologise underneath — *"This is a project setting in the manifest, not a
per-message flag, and it is read-only here."* **When a layout has to be
corrected by a caption, the layout is wrong.** It moves into the `Field` list
where every other read-only fact lives, and the caption is deleted.

**`Input` — text, textarea, slider.** Invalid state carries a message row in
words, never colour alone. The slider's numeric readout is `.data`,
right-aligned, and **editable** — a slider whose value cannot be typed is not a
parameter control (§10). Bounds come from `PARAMS` and render as `Field`s, never
invented.

**`Popover`.** Overlay surface, popover shadow, `max-width: 44ch`, anchored and
flipped to stay in the viewport, focus trapped, `Escape` closes, focus restored
to the opener. Carries `data-provenance-state` for §4.4's three shapes, and
§4.4's explanatory sentences render in `.body` at `--ink-muted` — **not** the
current 3.10:1 — because a sentence that exists to make a weak answer read as
designed cannot itself be below the legibility floor.

**`EmptyState`.** Centred column, `max-width: 44ch`, sprite icon, `.title`
heading, `.body` prose in the base ink and **not italic**, optional `Button`.
*Retires the shipped P2:* italic-grey-and-smaller is the universal signal for
*footnote*, and applying it to a panel's primary content tells the reader the
panel is broken — exactly the failure `Stage.tsx`'s own comment says it is
avoiding ("a state that exists for a reason reads as designed; the same state
with its content missing reads as a bug"). The prose achieves it; the styling
defeats it. **Second rule: a shared cause is detected once.** `WORKING TREE` and
`VERSIONS` currently render the *identical* sentence in adjacent rail sections
above ~1000px of void; one `EmptyState` spans both and the sentence is printed
once.

**`RefusalBanner` — kept, promoted.** The closest-to-right component already
shipped. It gains `role="alert"` + `aria-live="assertive"`, a `.title` heading,
the reason code as a `Chip` in `.code`, a `secondary` retry `Button`, and the
shared danger fill so it is the same recipe as every other danger surface.

**`ToolChip` — §7.2's contract untouched, restyled.** The generic
`data-tool-name` / `data-field` contract is the whole of §7.2 and the e2e
depends on it; it does not change. Visual: a raised card, tool name in `.code`,
status via `Badge`, fields via `DataTable` — which is what finally right-aligns
the numbers an agent reports. **Refusal, promoted from a bug to a rule: a
reading surface never receives `JSON.stringify` output.** Today a check row
renders a typed `AddressingError` as raw JSON wrapped mid-token across three
lines at the same weight and colour as a passing check's `[250,156,5.5]`, with
the actual information — *you referenced a part that doesn't exist* — buried at
character 120 inside JSON punctuation. The server already returns a typed error:
`message` renders as the row value, `code` as a `Chip`, and the raw object goes
behind a `<details>`.

**`ViewCube` — reordered and detuned.** Eight mono buttons in a 4×2 grid
currently read `iso +X -X +Y / -Y +Z -Z front`, so `+Y` and `-Y` land on
different rows and `front` sits beside `+Z` as a different category of thing;
the only selected signal is a solid accent fill that is the loudest element in
the application, in direct violation of principle 1. The **vocabulary stays
closed** at `cameras.py`'s eight names (§5.5 survives); the **layout** becomes a
3×3 orientation cross with `front` on a separate named-views row, and selected
state becomes an accent-quiet fill.

**`ScriptEditor` status bar — two label fixes.** The bar reads
`READ ONLY | 13 lines | cbe552b4cf cbe552b4cf`: two different refs both rendered
`.slice(-10)`, colliding on the fixture, so the same hash appears twice with no
labels and reads as a rendering bug. Both gain visible labels
(`content …` / `snapshot …`) as `Field`s in `.code`, keeping their distinct
`data-source` values. The editor frame shrink-to-fits rather than framing
~800px of void below 13 lines. The Script tab is otherwise the best surface in
the product — a real gutter, tabular line numbers, syntax colour, a status bar.
**It is the existence proof that the absence of a design system was a choice not
yet made, not a capability gap.**

**`Composer` (§7A.10), `ExportPanel` (§22.7), `ProvidersPanel` and
`SignInDialog` (§23.8)** are built on these primitives from their first commit
and declare no colour, type, or border of their own.

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

## 7A. The composer — starting and holding a conversation

*(Numbered `7A` as an **insert under §7**, not a renumber. §16, §17, §19 and §20
cite section numbers as their only cross-reference mechanism; renumbering §8–§21
to open a slot would silently invalidate every one of those citations while
changing no text. The letter is the cost of keeping the clause maps checkable.)*

§7 specifies the stream as a surface that **renders**. This section specifies
the surface that **speaks**, and it is the half the shipped build declines to
write: `StreamPanel.tsx`:26 states "§9 puts prompting in Stage 5", and **§9 does
not**. §9 is titled "Stage 5 — editing" and its four subsections are
save-is-a-store-mutation, rebuild-on-save, conflict/merge, and no-write-is-lost;
the word "prompt" occurs in it once, as "merge prompt". Nowhere in this document
is `Composer` assigned to Stage 5. §4.1's shell diagram places it in the STREAM
column and §4.2 lists it in an inventory closed for Stage 4/5 **jointly**. That
miscitation is **struck** here, and §7A.9 states what actually gates the
composer.

Every route this section uses is already in §2.3's table. It adds **one** route,
**one** optional request member, and **one** sidecar parameter; each is marked
**NEW WORK** and appears in §19.

### 7A.1 Where the composer lives, and the two places it does not

**DECISION.** The composer is the last child of the STREAM column, below the
transcript, **one per session tab** — the position §4.1's diagram already gives
it. Its identity is the tab's `session_id`; it has no session picker of its own.

*Rejected: one global composer with a session selector.* A session is the
addressed object (`?s=`, §4.5), and the profile of the addressed session decides
the tool scope the words execute under (§7A.2). A composer that could retarget
without the tab changing would let a part-scoped question land in an
orchestrator, or an orchestrator's project-wide instruction land in a
`quick_edit` session bound to one part, with the only visible difference being a
dropdown the operator was not looking at. **Scope must move when the reader's
eye moves.**

*Rejected: a text field in the `SelectionPopover` ("ask about this face").* That
affordance already exists and is not a composer: §4.3's spine ends
`"Ask about this" → quick-edit spawn → child session tab`, and §12.5 seeds that
child with artifact-bound source, resolved provenance, and a crop. A second
input at the popover would create two prompt paths with different scopes and
different seeding, distinguishable only by which pixel was clicked. **The
popover spawns; the spawned tab's composer prompts.**

**TIGHTENING (binds §4.1's breakpoint prose).** A composer cannot live in a 44px
strip, so the strip is a **control** rather than a narrower panel: focusing or
activating it expands the column. §4.1(a) makes the breakpoint and the panel's
open state one fact with one owner, which this section depends on.

### 7A.2 The blank canvas: creating a session, and the profile a web-started one gets

The operator ask has two halves — "about the displayed material" and "about a
blank canvas" — and they are the same route with a different `part`.

**DECISION.** `POST /sessions` is reachable from exactly two affordances, both
explicit:

| Affordance | Body | Profile | Bound part |
|---|---|---|---|
| STREAM empty state / "New session" | `{profile: "orchestrator"}` | `orchestrator` | none |
| A part row's context action, or "Ask about `<part>`" | `{profile: "part", part: "<part>"}` | `part` | that part |

**The blank canvas is the orchestrator profile with no part**, and that is not a
workaround: `dispatch.py`:412-413 exempts an orchestrator principal from
object-scope entirely, and :429 makes nameless project-scope operations
orchestrator-only. A session that must be able to *create the first part* cannot
be scoped to a part that does not exist. It also matches §2.2, which already
assigns the *workspace principal* `profile="orchestrator"` on the stated ground
that "a local operator with the project open is orchestrator-equivalent".

**What the profile implies, stated because a scope refusal read as a bug is the
failure mode.** `agent_bridge/sessions.py`'s `_SPECS` is the authority and is
**not** restated by the client: an `orchestrator` delegates and addresses every
part plus nameless project scope; a `part` session does not delegate and
anything outside its binding is `scope_denied`; a `quick_edit` session is
part-scoped and seeded from a resolved selection.

**TIGHTENING (binds §2.3's `POST /sessions` row) — `quick_edit` is not creatable
here.** `SESSION_PROFILES` is closed at three and the route accepts all three
today. It must accept **two**. A `quick_edit` session's entire meaning is the
seeding `spawn_quick_edit` performs — part, source, provenance, crop ref and
`parent_session_id`, resolved against **A**, with `stale_selection` raised
*before any lease is taken* (§12.5). A bare
`POST /sessions {profile:"quick_edit", part:"tread"}` produces a session with
that profile's restrictions and **none of its context**: a scope the operator
can feel but cannot see, and a `parent_session_id` that is nothing, so §2.8's
edge is never written and the tab reopens `unlinked`. The route refuses it by
name — `400 invalid_params`, naming `POST /parts/{part}/quick_edit` as the route
that creates one. **NEW WORK (§19.26)**, three lines and a pytest.

**TIGHTENING (same row).** `profile: "part"` with `part: null` is refused
`400 invalid_params`. Unvalidated today, it produces a part-profile session
bound to nothing, whose every object-scoped tool call fails `scope_denied`
against a `None` binding.

**The profile is never chosen silently.** The create affordance shows the
profile it will use and what that profile can do, in one line, **from a server
projection** — not from a client-side copy of the table above. A user who does
not know their session cannot delegate reads `scope_denied` as a broken product.

**At-least-once is the stated consequence and the UI carries it** (§2.3): a
duplicate create is an extra *idle* session. The composer therefore creates a
session **only on an explicit operator action** — never on focus, never on first
keystroke, never as recovery from a failed prompt. **Named refusal:** there is
no route that closes a session and none is invented. An orphan is idle and
harmless; `GET /sessions` lists it, and the panel says it can be left rather
than offering a close button no route backs.

**Where a part comes from, said out loud** *(2026-08-28 review addition)*. After
this section lands, the only way to bring a part into existence from the browser
is to **type English at an orchestrator agent, which calls `create_part`**.
There is no part-creation route, no button, and none is added: §15.9 forbids the
workspace inventing model tools and a part is authored source, not a form. What
this section owes the operator is therefore not a button but an **entry point**:
the parts-empty state is an `EmptyState` (§4.7) whose action creates an
orchestrator session and focuses the composer, with copy naming `create_part` as
the mechanism. **A blank canvas the operator has to guess is filled by talking
is the same defect as a composer that is not there.** Project creation is
further out of reach and is refused by name (§15.30): `heph serve` opens an
**existing** project root, so a new project is `heph init` at a terminal.

### 7A.3 The context envelope — the client sends references, never facts

This is the sharpest constraint in the section, and §1 decides it before the UI
question is asked: the client may compute screen-space quantities, and may not
compute, synthesize, reconcile, or infer any value that appears in a result, a
badge, a readout, a provenance answer, or a selection.

A prompt is none of those five. But a prompt becomes something worse (§7A.4), so
the rule is applied in its strictest form.

**TIGHTENING (binds §1, extending its closed list to the prompt path).**
`POST /sessions/{id}/prompt` gains one optional member, `context`, whose every
field is **either a closed-vocabulary token the client already owns as §4.5
workspace state, or an opaque server-minted identifier the client is echoing
back unmodified**. There is no free-form field, no number the client computed,
and no string the client authored: `part`, `artifact_ref`, `pin_mode`,
`stage_tab`, `inspector_tab`, `view`, `explode_t`, `section_plane`,
`hidden_labels[]`, `selection{selection_id, bundle_ref}`, `focus`.

Three need their WHY stated, because each is where a careless implementation
would smuggle in a fact:

- **`explode_t` is a parameter, not a displacement.** §1 already establishes
  that the GLTF ships each solid's `explode_offset` and "the client applies
  `offset · t` and nothing else". The envelope carries `t`. It never carries a
  distance, and the composed block never says how far anything moved.
- **`hidden_labels` reports the toggles, not what is visible.** The namespace is
  the geometry-entry label from `GET /parts/{part}/build`, which
  `state/visibility.ts` already uses because that is the only namespace the
  client has. The composed block therefore says *"the operator has hidden the
  geometry labelled `cleat_left`"* and **never** *"the operator can see 2
  solids"*. Camera framing and occlusion are not knowable server-side, not
  knowable client-side without computing over geometry, and are claimed by
  neither. **Named honesty limit:** a context block claiming to describe what is
  on screen would be the client asserting a fact about pixels the server cannot
  check.
- **`selection` is submitted, not described.** The envelope carries the ids; the
  server resolves them through §12.3 against the pinned ref; a selection that
  does not resolve is `stale_selection` — **never** a fallback to current
  geometry (§15.3), and never a prompt that quietly drops the selection it
  claimed to carry.

**A lying client is caught, not believed.** Because resolution is server-side,
an `artifact_ref` outside the project opstore fails §2.2's project-scoped check;
an unknown `part` is `unknown_part`; a `selection_id` from another build is
`stale_selection`; a malformed `section_plane` is `invalid_params`. The envelope
is a set of claims the server verifies against its own state, which is the only
structural difference between *carrying context* and *letting the browser write
the brief*.

**An empty or absent envelope is not an error.** `context: null` is the blank
canvas and the server composes nothing. The default envelope is exactly the
workspace state visible at submit time; every member is **opt-out**, rendered as
a removable chip row above the textarea, so the operator sees the references
before sending and can drop any of them. The chips render §4.5 state, which is
navigation, not fact — the same exemption §1 grants the grid readout — so no
chip goes through `<Fact>` and none carries a `data-source`.

**The CLI does not compose this envelope.** `heph prompt` / `heph prompt set`
store operator request text at `.heph/request.txt` and start no run, call no
tool, and do not pass the file to `set_request_text`. Headless agents author
parts with `heph part create` / `heph script write` and build with `heph build`;
they do not get a second prompt path that would have to invent context the
terminal does not have. There is no hosted chat on `heph`.

**NEW WORK (§19.19) — `server/http/context.py::compose_context`.** It reads
**only** through the existing projections — the serializers behind
`GET /parts/{part}/build`, `/properties`, `/checks`, `/dfm`, and
`/artifacts/{ref}/meta` — and re-serializes nothing (mission rule 6). Its output
is deterministic in `(references, project state)`, bounded by the existing
`text_result` caps with truncation **marked, never silent** (§2.9's precedent),
and goldened at `tests/stage4/goldens/context/<case>.txt` so a change to what
the agent is told is a diff in a review rather than a change nobody can see.

**NEW WORK (§19.20) — `POST /context/preview`**, project-scoped, read, no key.
Resolves an envelope and returns `{block, truncated, sources[]}` **without**
prompting: it starts no run and calls no tool. This is what the composer's "what
will the agent be told?" disclosure renders. The preview is **advisory**; the
prompt route composes again, from the same function, at send time, and the
response echoes the block actually sent. Saying the preview is authoritative
would be a claim the two calls cannot make good on.

### 7A.4 Where the composed block goes — and the one field it must never touch

The sidecar's `session.prompt` takes `{session_id, run_id, prompt}` and nothing
else. There are two ways to get a context block to the model, and the choice is
a correctness argument, not a tidiness one.

*Rejected: prepend the block to `prompt`.* It costs nothing and it breaks
`VALIDATION.md`. `BridgeRuntime.prompt` binds the whole prompt string to the ops
layer at `agent_bridge/app.py`:550 — `self._cad.set_request_text(text)` — and
`cad_ops/_base.py`:279-288 states why: "`VALIDATION.md` §4 diffs the numbers in
the request against the built geometry, and §5 hands the reviewer the request
verbatim". `_critique.py`'s `prompt_number_diff` then runs
`request_numbers(request)` over that text and matches each extracted number
against the build's own bbox extents, tagged dimensions and CHECKS thresholds. A
context block carrying `bbox 250 × 140 × 5.5 mm` would put the build's own
extents into "the request", and every one of them would come back
`matched: true` **against itself**. The rung that exists to catch a design that
does not meet its brief would be measuring the workspace's own context block. A
critique with no request already **omits** `prompt_number_diff` rather than
inventing one; prepending is exactly inventing one.

**DECISION, and the invariant it protects:**

> **The request text is exactly what the operator typed.** The context block
> reaches the model as a separate leading content block on the turn and is
> **never** passed to `set_request_text`.

**NEW WORK (§19.22)**, one field in three places: `session.prompt` accepts an
optional `context` string; `main.ts` prepends it as its own user-role content
block; `BridgeRuntime.prompt` gains `context: str | None`, forwards it, and does
not bind it.

**NAMED HONESTY LIMIT — the invariant does not survive concurrency, and the
composer is what makes concurrency reachable.** *(2026-08-28 review, and this is
the finding that changed the section.)* `CadOps` holds exactly **one**
`_request_text` for the whole project (`_base.py`:270) — it is per *runtime*,
not per session or per run. Every session shares it. A guard of one live run
*per session* therefore does not protect it: two tabs on two different sessions
— the blank-canvas orchestrator and a part session, the exact pair §7A.2 sells —
can prompt concurrently, the supervisor is concurrent, and admission allows 16
runs. The second `set_request_text` clobbers the first, and session A's build is
then critiqued against session B's prompt: a **fabricated request diff**, which
is precisely the failure this subsection exists to prevent. Two single-run
regression pytests cannot see it. This is pre-existing machinery; the composer is
what makes it reachable, and claiming the byte-for-byte invariant without naming
the hole would be the kind of assertion §2.6 was just corrected for.

Two things follow, and both are required:

1. **NEW WORK (§19.23) — bind the request text to the run, not to the ops
   object.** It is passed through `BridgeRuntime.prompt` into a per-run scope
   that `_build.py` reads from the active run. This is the honest fix and it
   makes the invariant true rather than conditional.
2. **Until §19.23 lands, the guard of §7A.5 is project-wide** — one live prompt
   per *runtime*, not per session — and §15.28 records the limit. The
   composer does not ship the per-session guard while claiming the invariant.

Two regression pytests, both regressions rather than decoration: with a context
envelope present, `CadOps.request_text` equals the operator's `text`
byte-for-byte; and a prompt whose `text` contains no numbers, sent with an
envelope full of them, yields `prompt_number_diff.numbers == []`. A third, added
by the review, runs **two concurrent prompts on two sessions** and asserts each
run's critique sees its own request.

**Reopen honesty, and it costs nothing new.** §8 already records that user
prompts are omitted from normalization by design and that the transcript says so
once, in place. The context block is part of the user turn, so it is
unrecoverable on reopen for **exactly** the reason prompts are, and is covered by
the same named absence. No new absence state is minted and §15.10's ban on
event-vocabulary extension is untouched: the block is never an event.

### 7A.5 Sending a turn: at-least-once, no key, and how a tab learns its own run id

`POST /sessions/{id}/prompt` carries **no** `Idempotency-Key` and a supplied one
is ignored (§2.3). The composer cashes that out rather than routing around it.

**TIGHTENING (binds §2.3's prompt row).** The composer **never retries a prompt
automatically.** A failed or lost POST leaves the operator's text in the box,
marks the turn `data-send-state="unknown"`, and states that the turn may have
started and that the stream is the authority. An auto-retry over an at-least-once
route is a duplicate-turn generator with a spinner on it.

**The run id comes from the stream, not from the response.**
`WorkspaceSessions.run_prompt` blocks for the whole turn, so the response arrives
*after* the run is over and cannot be the source of a mid-run cancel target. The
composer learns its run id from the first `/events` frame whose envelope
`session_id` matches the tab — precisely the field §2.7 added the envelope for.

*Rejected: the client mints the run id.* The route accepts one, but
`BridgeRuntime.new_run_id` owns that namespace, and a second minter in it is the
duplication mission rule 6 forbids, with a collision producing
`run '<id>' already active` as its symptom.

**Named limit:** between submit and the first event carrying the run id, **cancel
is unavailable**. The composer renders `data-cancel-state="unavailable"` with
its reason ("no run id yet") rather than a dead button, and the same state when
the socket is not `live` (§7.4), because a tab with no stream has no way to learn
the id. The window is one model round-trip.

**TIGHTENING + NEW WORK (§19.27) — one live run per runtime.** `manager.ts`
guards run-id uniqueness only; nothing refuses a second prompt on a session that
already has a live run, and nothing at all serializes across sessions. Two
interleaved turns on one Pi JSONL is the condition §2.1's lease design exists to
prevent, and §7A.4's per-runtime `_request_text` makes the cross-session case a
correctness bug and not merely an ordering one. `POST /sessions/{id}/prompt`
therefore refuses while **any** run is live under the runtime, with a **new,
distinct reason `run_in_flight`** carrying the holding session and run ids.

*Rejected: reusing `session_busy`.* `SessionBusyError` already means *a foreign
lease holder owns this session* (§2.1), which is a different fact with a
different remedy; collapsing them would make "your terminal holds this session"
and "another tab is mid-turn" indistinguishable in the one place the operator
must tell them apart. The composer disables while any run is live, whoever
started it, and names which session holds it. **When §19.23 lands, the guard
narrows to per-session and `run_in_flight` keeps its meaning** — the scope
changes, the vocabulary does not.

### 7A.6 Cancellation, and what a `4409` does to a run this tab started

**DECISION (binds §2.7's observer decision). Issuing a prompt does not upgrade
the socket.** The originating tab remains a **non-durable observer**: on overflow
the server closes it `4409 / resync_required` and **does not cancel the run it
started**. WHY: §2.7's decision is about backpressure, not authorship. A tab that
started a run has the same frame-budget problem as one that did not, and
upgrading it would reintroduce the coupling the decision exists to remove — a
slow tab killing the run it is watching. Ownership of a prompt is not a claim
about a socket's ability to keep up.

**The consequence, and the existing field that closes it.** `terminal` is
live-only and never appears in a history page (§7.3), so a tab that resyncs
across the end of its own run could lose the event that says the run ended. It
does not need it.

**TIGHTENING (binds §2.3's prompt row, §7.4).** The composer's turn-completion
state comes from the **prompt response**, not from the `terminal` event.
`run_prompt` already returns `{run_status, terminal, events[]}` for exactly this
reason — "the socket is the live surface; this list is what a client with no
socket renders instead, so a run is never invisible". The stream is the live
rendering; the response is the authority for *this turn is over*. Observers that
did not issue the prompt still depend on `terminal` and still get §7.4's
labelled `resyncing` break. Only the originating tab gets the stronger
guarantee, and it gets it from a field that already exists.

**Cancel with a question pending.** `cancel_run` calls
`questions.abandon_run(run_id)`, so every suspended question on that run is
released and the tool call fails `AskAbandoned` rather than receiving a
fabricated selection. The cancelling client learns from `abandoned_questions` in
the cancel response. **Named wart:** there is no `question_abandoned` event, and
minting one would extend the vocabulary (§15.10). An *observer* tab's widget
therefore stays interactive until it either sees the run's `terminal` or attempts
an answer and receives `404 unknown_question`; on that 404 it disables with
`data-ask-state="abandoned"` and the stated reason. This is a real gap, bounded
by the `terminal` band in the common case, and it is written down rather than
closed with a new event kind.

### 7A.7 Answering `ask_user` from the browser

§7.3 already says, normatively, "Answering posts `POST /sessions/{id}/answer`;
first answer wins." §2.7 already says "Both the CLI's numbered prompt and the web
widget may answer; neither is privileged." The route is built, the registry is
built (idempotent on the question id, first answer wins, `accepted:false` for the
loser), and `AskUserWidget.tsx`:101 hardcodes `disabled`. **This is not new work.
It is a deviation, and this section closes it** (§19.21).

**DECISION — the widget's affordance is derived from the question's own params,
never chosen by the client.** `ask_user` declares `options`, `allow_free_text`
(default `true`) and `multi` (default `false`), and the `question` payload
carries them: options with `multi:false` → one button per option plus a free-text
field **only if** `allow_free_text`; `multi:true` → multi-select, one submit; no
options → a single text field, the only thing a bare `ask_user` can accept;
`allow_free_text:false` → buttons only, **no** text field. Offering free text on
a question that declared `allow_free_text:false` would hand the model an answer
its own schema does not admit.

**TIGHTENING (binds §7.3) — the answer value's namespace, currently undefined
across surfaces.** `_CLARIFICATION_OPTION` is `{label, consequence}`, and
`agent_bridge/cli.py`:274-276 flattens options with `str(o)`; for an object
option that is a **Python dict repr**, and `_resolve_selection` returns that repr
as the selection the model receives. Two surfaces answering one question can
therefore hand the model two different values.

> The answer value is the option's **`label`** for an object option and the
> string itself for a bare-string option; a `multi` answer is an array of those.
> The web widget submits the label **the server sent**, never a label it
> reconstructed from rendered text.

The CLI's `str(o)` stringification is **NEW WORK (§19.29)**: a Python repr
crossing into a model-visible selection is a defect independent of this section,
named because the web widget must not be built to match it.

**Live only, and the reopened widget stays disabled — correctly.** §7.3's
reopened widget is rebuilt from the `ask_user` call and its result and marked
`data-widget-source="tool_result"`. There is no pending question; the run is
over; its disabled state is right and keeps its stated reason. What changes is
only the live branch. **`data-answered-by` becomes honest:** `ask.ts`:23-30
reserves `"self"` and records that this build can only ever report `"other"`.
With the post wired, `answered_by` comes from the route's `accepted` flag — the
winner renders `"self"`, every other client `"other"`, and the recorded selection
is the winner's, returned unchanged so both clients agree on what the run was
told. No web-side lock is invented over the suspended question; that would be a
second session-ownership mechanism (§2.7). `404 unknown_question` is a
first-class rendered state — "answered, abandoned, or never asked" — on the
widget, in place, not in a toast.

### 7A.8 No agent runtime: `agent_unavailable` stays, and gains a cause

Today `sessions_or_refuse` raises `503 agent_unavailable` on every session route
and `events_socket` closes `1008 agent_unavailable`. **That refusal is right and
does not change.** A serve with no runtime still serves every read, mutation,
artifact and git route. Three things do change.

**1. The composer renders, disabled, with the refusal named.**
`StreamPanel.tsx`:26's reasoning — "a disabled text box with no explanation would
be worse than its honest absence" — is correct and its conclusion is wrong,
because it considers two options where there are three. §4.4's discipline is
applied to every other missing capability in this document: *a state that exists
for a reason reads as designed; the same state with its content missing reads as
a bug.* A disabled composer **with** its reason is that state. Silence is what
produced a product review finding that the workspace has no way to talk to an
agent.

**2. The refusal becomes actionable, and its content comes from the server.**
`serve.py`:128-178 knows exactly why `_attach_agent` returned `None` — a missing
`providers.json` at a path it prints, or one of
`ConfigError | AuthLinkError | SidecarError | SupervisorError | RuntimeError` —
and writes it to **stderr**, which no browser will read; the cause is then
discarded. **NEW WORK (§19.25):** the serve records the attach outcome as a
structured, non-secret value on the runtime, and `agent_unavailable` carries it
in §2.4's `data`: a closed `cause ∈ (no_provider_config | provider_config_invalid
| node_missing | node_too_old | sidecar_failed | auth_link_refused)`, the
`config_path` that was checked, and a `detail` reduced at the boundary. **No
secret ever enters it** — not a credential, not a token, not a provider's
response body.

**3. What the disabled composer offers, and the seam with §23** *(2026-08-28
review — this replaces a flat refusal that would have contradicted §23)*. In the
shipped product the disabled composer **names the file the server looked for and
does not offer to write it**, because until §23 lands there is nothing behind
such an offer but a text editor. §2.2's "it never prompts for credentials"
remains true of what it was about — the **workspace bearer token**: no login, no
cookie, no user model. §15.34 records this as a **dated, conditional** refusal
rather than an absolute one, and §23 — whose stage was **approved 2026-08-28 as
Stage 10B** (§0.2a) — strikes it and re-specs this state to render §23's entry
point **when §23 ships**. Note the two events are distinct and the refusal is
keyed to the second: §15.34 says *until §23 lands*, and a stage being gated is
not a panel existing. Until the ProvidersPanel is built, the disabled composer
still names the file and still does not offer to write it. Writing it as absolute would
have had the document forbid and specify the same surface, which is exactly the
collision §0.2's allocation pass exists to prevent.

**Ordering, stated because it is a product fact and not a spec detail.** For an
operator who already has a `providers.json` — which is every operator who has
ever run `heph agent` — the Stage 4 composer answers complaint 1 completely. For
an operator who does not, it renders disabled with a named cause and a path that
runs through a terminal until §23 ships. That is an improvement on silence and it
is **not** a full answer, and §22/§23's plan orders them accordingly rather than
leaving the sequencing to whoever picks up the work.

`GET /sessions/{id}/thread` continues **not** to gate on the runtime: threading
is durable in `state.db` and readable long after the process that wrote it.

### 7A.9 Which stage this is

Two load-bearing findings from the stage-boundary reading: "read-only" appears
twice in `mission_plan.md` — once in the Stage 4 heading and once attached to
`script viewer (Monaco, read-only)` — and grepping the G4/G5 span for
`must not|never|forbid|prohibit` returns **no prohibition on the workspace**. G4
is a floor, not a ceiling.

| Surface | Stage | What gates it |
|---|---|---|
| Answering `ask_user` from the browser | **Stage 4** | G4's deliverable text says `ask_user widgets`. A widget that cannot be answered is a rendering of a question. §7.3 already specifies the post; the implementation is stricter than the spec and the spec is stricter than the gate, with no clause behind the tightest layer. |
| The composer in a quick-edit tab | **Stage 5, already gated** | G5, verbatim: *"Submitting 'add a 2 mm chamfer to this face' to the quick-edit agent … results in an `edit_part` diff visible in the transcript."* That is a browser submission through a composer. G5.16 already carries it. |
| The composer on an orchestrator / part session, and the blank-canvas create | **Stage 4** | No clause asks and no clause forbids. §4.1 places it, §4.2 lists it in an inventory closed for Stage 4/5 jointly, and §2.3 already carries `POST /sessions` and `POST /sessions/{id}/prompt` as closed routes with a stated no-key policy **G5.19 obliges a test of, in the negative direction**. It ships as the entry point G4's own `ask_user` and live-stream deliverables presuppose. |

**No new stage.** Export needed one and got one (§22, Stage 10A) and provider
sign-in needed one and got one (§23, Stage 10B/10C);
chat does not, because every route it uses is already inside two closed lists
this document owns. A session creation is not a project mutation: §2.3 states
that `session.create`, `prompt`, `cancel`, `answer` and `spawn_quick_edit` have
no `ToolDecl`, no `Invocation`, and no recorded-outcome row to replay. Its
*consequence* — the agent calling `write_part` — is a mutation performed by the
agent under the dispatcher's unchanged authz, identical whether the words arrived
from a TTY or a socket, and **G4 already requires the panel to watch exactly
that write**.

**TIGHTENING (binds G4.8) — non-negotiable, and the one obligation the composer
creates.** G4.8's e2e fixture **must keep starting its session from the CLI**.
"An agent session started from CLI streams live into the web panel" is a claim
about lease topology (§2.1: a session started in a terminal is *the same session
object* the browser attaches to, because there is only ever one runtime). If the
suite were rewritten to drive that clause through the composer, the cross-process
round trip the clause exists to test would go untested and the clause would
degenerate into a self-observation. The composer's coverage is a **separate**
e2e case that starts its session in the browser; the two never share a fixture.

**Session creation over HTTP rides the one dispatcher — with the boundary named
exactly.** The *session* is created through `BridgeRuntime.create_session` → the
sidecar's `session.create`, which records the `Principal(session_id, profile,
part)`. The *tools that session then calls* ride `ToolDispatcher.dispatch`
unchanged under that principal. There is no second session mechanism and no
second dispatcher. Saying that "session creation rides the dispatcher" would be
false and is not said: session control does not pass through dispatch at all,
which is precisely why §2.3 had to enumerate its key policy instead of deriving
it from `MUTATION_TOOLS`.

### 7A.10 DOM contract

On §7.2's precedent, stated as a component contract because the e2e addresses it:

```html
<form data-composer
      data-session-id="sess-…"
      data-profile="orchestrator"
      data-composer-state="idle | sending | running | disabled"
      data-disabled-reason="agent_unavailable | run_in_flight | no_session | null"
      data-cancel-state="available | unavailable"
      data-send-state="ok | unknown">
  <ul data-context-chips>
    <li data-context-key="part"          data-context-value="tread"></li>
    <li data-context-key="artifact_ref"  data-context-value="artifact:build:sha256:…"></li>
    <li data-context-key="inspector_tab" data-context-value="checks"></li>
    <li data-context-key="hidden_labels" data-context-count="1"></li>
  </ul>
  <textarea data-composer-input></textarea>
</form>
```

`data-composer-state` and `data-disabled-reason` are **closed**. No chip carries
a `data-source`, because no chip is a fact (§4.6); a chip that ever renders a
measured value is a `heph/no-derived-fact` failure, and the rule already in §1
catches it without extension.

### 7A.11 The read-refresh boundary — the turn's effect on the rest of the workspace

*(2026-08-28 review addition. Without this the section answers complaint 1 as
far as "words go in and events come back" and no further.)*

The composer makes the browser the **originator** of agent mutations for the
first time. Nothing today refreshes the read caches when the agent writes:
`queries.ts` defines `keys.{project,parts,build,script,properties,checks,dfm,
gitStatus,gitLog,gitTags}` and a 5s project staleness, and no mutation path
invalidates any of them. The blank-canvas flow would therefore end with a
transcript full of successful tool calls and a rail that still says the project
has no parts.

**DECISION, normative as the write path is.** On a `terminal` frame for a run on
this project — and on the prompt response, which §7A.6 already makes the
authority for turn completion — the client invalidates
`keys.project`, `keys.parts`, `keys.build(part)`, `keys.script(part)`,
`keys.params(part)`, `keys.properties(part)`, `keys.checks(part)`,
`keys.dfm(part)` and `keys.gitStatus()`.

**TIGHTENING (binds §1).** The invalidation is a **refetch of the server
projection**, never a client-side merge of tool results. A composer that patched
the parts list from a `create_part` result would be the client deriving the
project's shape from an event payload — the exact failure §1 and
`no-derived-fact` exist to prevent, arriving through a door §1 did not have to
consider before the browser could start runs. The pin does **not** move: §4.5's
sticky-pin tightening binding G5.6 is untouched, so a refetch updates *current*
and never re-points the workspace at a build the operator did not choose.

**The e2e asserts the end state the operator cares about, not the transcript.**
§7A.12 case 1 ends by asserting the new part appears in `[role=tree]`, is
selectable, and its build renders — because "the agent said it worked" is not
what complaint 1 asked for.

### 7A.12 E2E cases

All against the public clean-room fixture with a scripted fake model, in a
fixture **separate** from G4.8's:

1. **blank canvas** — no part selected; create an `orchestrator` session; prompt;
   assert the turn's events reach the transcript, `run_status` is terminal,
   **and** the created part appears in the tree, is selectable, and renders
   (§7A.11);
2. **context envelope** — pin A, select `tread`, open the Checks tab, submit, and
   assert the composed block against `tests/stage4/goldens/context/`;
3. **request-text purity** — a prompt with no numbers plus a number-rich envelope
   yields `prompt_number_diff.numbers == []` (pytest, not Playwright: it asserts
   on the ops layer, not the DOM);
4. **concurrent purity** — two prompts on two sessions; each critique sees its
   own request (pytest; §7A.4);
5. `ask_user` answered from the browser: `data-answered-by="self"` on the
   answering widget, `"other"` on a second attached client, `accepted:false` for
   the loser;
6. `agent_unavailable`: serve with no `providers.json`; the composer renders
   disabled with `data-disabled-reason="agent_unavailable"` and the named
   `cause`;
7. `profile:"quick_edit"` on `POST /sessions` is refused `invalid_params`.

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
17. **REWRITTEN 2026-08-28. The workspace serves export bytes only through
    `GET /exports/{blob}/bytes`, addressed by a blob a `COMMITTED` `tp_exports`
    row names (§22.3), and only under **Stage 10A**, the gated stage §22
    required and was granted on 2026-08-28.**
    `/artifacts/{ref}/bytes` remains closed **by enumeration** and `export`
    remains in `REFUSED_BYTES_KINDS`: the generic blob-fetch primitive is not
    the export path, and a pytest still asserts it refuses an `export`-kind ref.
    Egress is a **named operation** with a result document, a provenance record,
    and an audit row — not a side effect of blob storage.

    **Two things this refusal no longer claims, and did claim.** First, the
    product half — "offers no export affordance" — was a deferral, correctly
    escalated to §18.6 and never answered; the product owner answered it on
    2026-08-28 and §22 is the answer. Second, and more seriously: the
    enumeration constrains which **named surface** serves export bytes and, until
    §19.24 binds the artifact kind to the blob, does **not** constrain
    reachability, because `artifact_kind()` reads a caller-supplied label and
    `_blob()` resolves by hash (§2.6's CORRECTION). The sentence "any
    bearer-holding browser could fetch the bytes" was true of the rejected
    draft **and remains true of the shipped route** for anyone who knows a blob
    hash. §22 is the change that publishes the hashes, so §19.24 is its
    prerequisite and not its companion.
18. **No bench or leaderboard surface.** `docs/README.md`'s no-static-site
    decision makes the default answer no, and no gate asks.
19. **No operator-waiver UI** (§13.2).
20. **No "Smith"/"Arche" in identifiers or packages**, and no test asserting the
    reference product's copy.
21. **No `/session/{uuid}` route** (§4.5).
22. **No mobile layout.**
23. **`server/http` is not headless surface.** Nothing in G7H may come to depend
    on it.

**Added 2026-08-28 (§0.2). Numbers 24–41 are allocated in one sequence across
all four amendments, so no two of them claim a number.** **Updated 2026-08-28
(§0.2a): the entries formerly marked DRAFT belong to §22 and §23, whose stages
were approved the same day (Stage 10A, 10B, 10C). Every refusal below is in
force under the gate its section names.**

*From §7A — the composer (Stage 4/5):*

24. **No global composer and no session picker inside one.** Scope moves when
    the tab moves (§7A.1).
25. **No client-authored context.** The envelope carries references and
    closed-vocabulary tokens; the block is composed server-side from the
    existing projections and is never written by the browser (§7A.3).
26. **No context in the request text.** `VALIDATION.md` §4's request is exactly
    what the operator typed (§7A.4).
27. **No claim about what is visible.** The envelope reports visibility
    *toggles*; camera framing and occlusion are claimed by nobody (§7A.3).
28. **No automatic prompt retry**, no idempotency key on a prompt, and — until
    §19.23 binds request text to a run — **no concurrent turns anywhere under
    one runtime**, because `_request_text` is one field per runtime and a
    per-session guard would not protect it (§7A.4, §7A.5). The refusal is
    `run_in_flight`, never `session_busy`.
29. **No client-minted run id** (§7A.5).
30. **No part-creation and no project-creation affordance.** A part is created
    by the orchestrator agent's `create_part`, reached through the composer from
    the parts-empty state (§7A.2); a project is created by `heph init` at a
    terminal, because `heph serve` opens an **existing** project root. Stated
    because an unnamed absence here is precisely what produced the product
    review.
31. **No `quick_edit` session created without a resolved selection** (§7A.2).
32. **No durable upgrade for the tab that issued a prompt**; the originating tab
    is still a non-durable observer (§7A.6).
33. **No `question_abandoned` event**, and no other event-vocabulary extension
    (§7A.6, §15.10).
34. **No credential prompt *until §23 lands*, and `agent_unavailable` names the
    file without offering to write it.** **This refusal is dated and
    conditional, not absolute** — §23 strikes it and re-specs §7A.8's disabled
    state to render its entry point. Written this way deliberately: an absolute
    refusal here would have had this document forbid and specify the same
    surface in two sections that could not see each other (§7A.8.3).
35. **No session-close route, so no close button** (§7A.2), and **no free-text
    answer to a question that declared `allow_free_text: false`** (§7A.7).

*From §22 — egress (**Stage 10A**, gate G10A):*

36. **No metadata injected into STEP, STL, GLB or SVG; no provenance sidecar
    file; no filesystem path on the wire in either direction; no kerf override
    or `target` from the browser; no unpin, no delete, no `DELETE` route; no
    inline rendering of any exported byte, SVG first among them; no streaming,
    progress bar, or service worker; and no export from an unpinned "current"**
    (§22.9 states each with its WHY).
37. **No import. Egress is one-way** (§22.8).

*From §3 / §4.7 — the design system (Stage 4):*

38. **No CSS framework, no component library, no icon package, and no second
    theme.** The sprite is repo-owned and closed at 18 ids; light theme is an
    §18 candidate (§3.2, §3.5, §3.12).
39. **No primitive that mints a `<Fact>` from a `source` string**, and no
    amendment to `heph/no-derived-fact` to permit one (§3.4).
40. **Nothing animates that carries a measurement** (§3.10).

*From §23 — provider sign-in (**Stage 10B**, gate G10B; discovery **Stage 10C**,
gate G10C):*

41. **No OAuth client registration of our own, no loopback callback listener, no
    background credential probe, no masked key tail, no mid-run
    re-authentication, and no route that returns credential material of any
    kind** (§23.11 states each with its WHY). **And no web-writable
    `credential_allowlist` or `auth_source`** (§23.6) — the one refusal in this
    list whose absence would have made the sign-in surface an exfiltration
    primitive.

    **UNCHANGED by the 2026-08-28 credential ruling, and the two clauses it
    could have been read to touch are named.** The ruling permits describing a
    discovered source "with a masked hint at most", which is a **ceiling**;
    **no masked key tail** is stricter and stands (§0.2a). And **no background
    credential probe** stands: discovery runs on an explicit
    `POST /providers/discover` and never on panel mount, on a timer, or as a
    side effect of another route (§23.5).

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

**AMENDED 2026-08-28 — four clauses whose deliverable changed.** No gate text is
edited; each row below adds to what the clause's deliverable is, and two of them
add an obligation the clause always had and the spec had not written down.

| Clause | What changed | Where |
|---|---|---|
| **G4.8** | **Its fixture is now load-bearing in a new way.** The composer makes it possible to start a session in the browser, so the clause's cross-process claim could be silently destroyed by "simplifying" the suite to use it. The fixture **must keep starting its session from the CLI**; the composer's coverage is a separate case with a separate fixture, and the two never share one. | §7A.9 |
| **G4.D** | Unchanged in contract, restyled in `ToolChip`: `data-tool-name` / `data-status` / `data-field` are preserved byte-for-byte by the primitive that now owns them, and that preservation is the migration's acceptance criterion. A reading surface stops receiving `JSON.stringify` output. | §3.14, §4.7 |
| **G4.4** | The closed badge vocabulary gains an **enforcement substrate split**: a component test covers all six states including `not_run`, which the public fixture deliberately cannot produce; the Playwright case asserts only over what the fixture reaches. The shipped `ChecksPanel` badge defect means this clause's DOM assertion currently passes against three visually identical badges. | §3.14, §4.7 |
| **G4.5** | Method unchanged — a self-referential before/after delta inside a decoded mask against an outside control region. §3.11's material authorship moves the numbers, so §21.10's chosen thresholds must be **re-derived before that work lands**, not loosened after it. | §3.11, §5.4 |
| **G4 `ask_user` widgets** | A widget that cannot be answered is a rendering of a question. The post is already specified (§7.3) and already built; the hardcoded `disabled` is a deviation, and it closes. | §7A.7, §19.21 |

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

**AMENDED 2026-08-28.**

| Clause | What changed | Where |
|---|---|---|
| **G5.16** | The clause's own words — *submitting "add a 2 mm chamfer to this face" to the quick-edit agent* — are a **browser submission through a composer**, and the shipped build has no composer to submit through. G5.16 was therefore already gating the surface `StreamPanel.tsx`:26 deferred, and the deferral cited a section that does not say it. §7A is the deliverable; nothing in G5's text changes. | §7A, §7A.9 |
| **G5.19** | Its negative direction now covers one more session-control row's body: `POST /sessions/{id}/prompt` accepts an optional `context` member and still requires no key, and the enumerated test asserts that a supplied key is **ignored** rather than honoured. | §2.3, §7A.3 |
| **G5.6** | Reinforced, not changed. §7A.11's read-refresh boundary explicitly does **not** move the pin: a refetch triggered by an agent turn updates *current* and never re-points the workspace. An invalidation that advanced the pin would fail this clause from inside the feature that answers complaint 1. | §7A.11, §4.5 |

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
6. ~~**Export / drawing / document surfaces.**~~ **STRUCK 2026-08-28.** This
   entry was a correctly-escalated deferral of a genuine product decision, and
   the product owner made the decision. It is now **§22**, with its own gated
   stage under mission rule 5 (§22.10) — **approved 2026-08-28 as Stage 10A,
   Gate G10A**. The sentence "the workspace would be the
   first non-agent, non-CLI export path in the product" survives as the reason
   it needed a stage rather than a button, and §22 keeps it in view.
7. **Orchestrator delegation-tree view.** §7.1 renders three levels as nested
   tabs. A dedicated delegation graph — with admission occupancy, the 16-slot
   ceiling, and queued state made visible — is unaddressed by any gate.
8. **DFM ergonomics beyond §6.4.** Whether a *per-run* DFM request should exist
   at all is a tool-surface question, not a UI question, and belongs to whichever
   stage revisits `run_dfm`.
9. **Light theme.** §3.6's two-layer token architecture makes it a second
   `:root[data-theme="light"]` palette block with **no component changes** —
   except the viewport, which needs a second display treatment (light ground,
   dark part, different edge and grid colour). That is real work with no gate
   behind it (§3.5).
10. **A drawing and document viewer.** §22 ships drawings and documents as
    downloads and says plainly that a PDF the workspace cannot show is a weaker
    deliverable than a STEP, because a STEP's destination is another application
    by definition while a drawing's destination is a pair of eyes. The viewer
    belongs with whichever stage gives the workspace a document surface at all —
    §18.1's ledger panel has the identical problem and should not solve it twice.
11. **Posed renders and swept envelopes in the browser.** Unchanged from §18.3,
    restated here only because §22.8 was asked whether `heph render --pose`
    counts as egress. It does not: a posed render is a PNG, not a file another
    CAD tool consumes, and a pose dropdown with no pose table above it is a
    control with no subject.

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

**Added 2026-08-28 (§0.2). Items 17–41 are allocated in one sequence across all
four amendments.** Each names its stage. **Updated 2026-08-28: the
`mission_plan.md` amendment of §22.10 / §23.14 is approved (Stage 10A, 10B,
10C), so no item below is blocked on a stage that does not exist.**

*§7A — the composer. Stage 4, except where noted.*

17. **`Composer` mounted in `StreamPanel`**, one per session tab, with the closed
    `data-composer-state` / `data-disabled-reason` contract (§7A.1, §7A.10), and
    the strip-expands-on-focus behaviour that makes the <1280px breakpoint and
    the panel's open state one fact with one owner (§4.1a).
18. **Four client API functions** in `web/src/api/sessions.ts`, which is
    read-only by construction today ("Read types only"): `createSession`,
    `sendPrompt`, `cancelRun`, `answerQuestion`. `apiJson` already accepts a
    `RequestInit` with `method`/`body` — proven in production by
    `viewport/useSectionPlate.ts` — so no new client plumbing is required.
19. **`server/http/context.py::compose_context`** — deterministic, bounded by the
    `text_result` caps with **marked** truncation, reading only through the
    existing projections, with a golden family
    `tests/stage4/goldens/context/<case>.txt` (§7A.3).
20. **`POST /context/preview`** added to §2.3's inspection table: project-scoped,
    read, no key, starts no run. This is an edit to a table declared closed for
    Stages 4/5 and is named as such rather than slipped in (§7A.3).
21. **Enabling the `ask_user` post** — delete the hardcoded `disabled` at
    `AskUserWidget.tsx`:101, derive the affordance from the question's own
    `options` / `allow_free_text` / `multi`, submit the **server-sent `label`**,
    and let `data-answered-by` take the `"self"` value `ask.ts`:29-30 reserves
    for it (§7A.7).
22. **`context` on the prompt path, in three places** — an optional `context`
    param on the sidecar's `session.prompt` prepended as its own leading content
    block (`agent/src/main.ts`), a `context: str | None` on `BridgeRuntime.prompt`
    that is forwarded and **not** passed to `set_request_text` (`app.py`:550),
    and the `context` member on `POST /sessions/{id}/prompt`. Two regression
    pytests: request-text purity, and `prompt_number_diff.numbers == []` under a
    number-rich envelope (§7A.4).
23. **Bind the request text to the run rather than to the ops object.**
    `CadOps._request_text` is one field per **runtime** (`_base.py`:270), shared
    by every session, so the §7A.4 invariant does not survive two concurrent
    turns and a per-session guard cannot save it. It is threaded through
    `BridgeRuntime.prompt` into a per-run scope that `_build.py` reads from the
    active run, with a pytest that runs two prompts on two sessions and asserts
    each critique sees its own request. **Until this lands, item 27's guard is
    project-wide and §15.28 records the limit.** *(2026-08-28 review — this item
    exists because the composer makes a pre-existing hole reachable.)*
24. **Bind the artifact kind to the blob** so `/artifacts/{ref}/bytes`'s
    enumeration is a boundary rather than a naming convention: record the kind
    at publication and have `_blob()` verify the ref's kind segment against the
    stored one, refusing `artifact_kind_mismatch`. Today `artifact_kind()` reads
    a caller-supplied label and `_blob()` resolves by hash, so an export blob is
    served by relabelling its ref. **This is a prerequisite of §22 and is
    worth doing on its own account** (§2.6's CORRECTION, §15.17). *Stage 4 —
    it is a correction to a route this document already owns.*
25. **Structured `agent_unavailable` cause** — `_attach_agent` (`serve.py`:128-178)
    records its outcome instead of printing it to stderr and discarding it; the
    refusal carries a closed `cause`, the `config_path`, and a reduced `detail`
    that can contain no secret (§7A.8).
26. **`POST /sessions` validation** — refuse `profile:"quick_edit"` by name
    (pointing at `POST /parts/{part}/quick_edit`), and refuse `profile:"part"`
    with `part: null` (§7A.2).
27. **One live run per runtime**, refused with the **new** reason
    `run_in_flight` naming the holding session and run — not `session_busy`,
    which already means a foreign lease holder (§7A.5). Narrows to per-session
    when item 23 lands.
28. **The read-refresh boundary** (§7A.11): a `terminal` frame or prompt response
    for a run on this project invalidates the enumerated `queries.ts` keys, by
    **refetch of the server projection**, never a client-side merge, and never
    moving the pin.
29. **CLI answer-value defect** — `agent_bridge/cli.py`:274-276 flattens options
    with `str(o)`, so an object option's Python **dict repr** becomes the
    selection the model receives. The answer namespace is the option's `label`
    on both surfaces (§7A.7). Independent of §7A; named because the web widget
    must not be built to match the defect.
30. **Composer e2e cases 1–7** (§7A.12), in a fixture **separate** from G4.8's,
    whose session must keep being started from the CLI.

*§3 / §4.7 — the design system. Stage 4.*

31. **`web/src/system/`** — the twelve primitives, the two-layer token file, the
    seven type roles, the 18-id icon sprite, `useBreakpoint`, and `format.ts`
    (§3.4, §4.7). Row APIs carry a `ReactNode`, never a `source` string (§3.4).
32. **The four static checks** `no-palette-token`, `no-raw-type`,
    `system-owns-status`, `token-contrast`, plus the `Badge` component test and
    `web/e2e/design-system.spec.ts` on the substrate split of §3.14.
33. **Viewport display authorship** — ground colour, material override, colour
    space, tone mapping, edge pass, grid, axis triad (§3.11), **with G4.5's
    delta thresholds re-derived against the new material before it lands**.
34. **`useBreakpoint` as the sole breakpoint authority**, `data-rail` wired with
    a scrim, close control and `Escape`, and a fixed `--drawer-height` with a
    drag handle (§4.1a–c). Three shipped defects, one owner.

*§22 — egress. **Stage 10A**, Gate G10A (approved 2026-08-28).*

35. **`POST /parts/{part}/export` · `/drawing` · `/doc`** — three key-required
    rows riding `ToolDispatcher.dispatch` with no bypass, replaying from the
    existing `tp_exports` WAL and needing **no** ledger extension (§22.2).
36. **`GET /exports/{export_blob}/bytes`** — the third artifact-byte surface with
    its own authorization (named by the `outputs` of a `COMMITTED` row), sharing
    `_blob()`, adding `Content-Disposition: attachment` with a **blob-derived**
    filename, `nosniff`, the enumerated format→mime map with its drift test, and
    the `export_too_large` ceiling (§22.3, §22.4).
37. **`GET /parts/{part}/exports`** — a projection over `tp_exports`, which today
    is written and read only by `op_id` (§22.7). **Ships only after item 24.**
38. **`ExportPanel`** (§22.7) — sixth Inspector tab, subject-before-controls, the
    two-step Export → Download flow, the refusal ladder, the export history with
    a running byte total, and the bearer-header `fetch` → `Blob` → object-URL →
    revoke download path with the key owned across retries.
39. **`_source_input_hashes` for non-current refs** (`cad_ops/_exports.py`) —
    resolve `input_hashes` from the frozen bundle for any `build`-kind ref, not
    only when the ref happens to be the part's current result. Today an export of
    an older pin carries only `{"source_artifact": …}`, which is the case that
    needs provenance most (§22.5).
40. **`heph export list` / `heph export unpin BLOB`** — CLI verbs over the
    existing `ExportOps.unpin_export`, which has **no production caller anywhere**
    (its only call site is a server test). `tool_schema.md` already promises this
    verb; nothing implements it, and §22.6 makes the omission materially worse.
    Not web work: §2.3 admits no `DELETE`. **Plus, as a separately-decided item:
    wiring `GcCollector.admission_guard()` into the artifact-producing paths**,
    which today has no production caller either — so exports pin unboundedly and
    *nothing currently refuses* on the strength of it (§22.6).
41. **`blank_undeclared` as a first-class refusal** on the nested-sheet path,
    distinct from `invalid_params`, carrying the explicit-blank remedy — because
    `blank_size_literal` is a static AST read for a string `Constant` and the
    flagship fixture's `tread.py` sets `part.blank_size` as an f-string **on
    purpose**, so `export_part(layout="nested_sheet")` refuses on the product's
    own showcase part (§22.1, §22.7).

*§23 — provider sign-in. **Stage 10B**, Gate G10B, with credential discovery at
**Stage 10C**, Gate G10C (both approved 2026-08-28). Its own new-work list is
§23.14 and is numbered inside that section, because its first item is a
capability the product does not have and the review found the section
unbuildable without it.*

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

**Added 2026-08-28.**

| Ambiguity | Resolution | § |
|---|---|---|
| which stage the composer belongs to — the code cited §9, and §9 says nothing about prompting | ask_user answering and the orchestrator/part composer are Stage 4 under G4's own deliverables; the quick-edit composer is **already gated** by G5.16 verbatim; the citation is struck | 7A.9 |
| whether "read-only" in the Stage 4 heading forbids a browser-originated turn | it does not: it appears twice, once in the heading and once attached to the Monaco viewer, and the G4/G5 span contains no prohibition on the workspace. G4 is a floor, not a ceiling — and G4 already requires the panel to watch an agent's `write_part` | 7A.9 |
| what a prompt may carry beyond the operator's words | a closed envelope of references and §4.5 tokens; composed server-side; never in `set_request_text` | 7A.3, 7A.4 |
| what refuses a second concurrent turn, and under what name | `run_in_flight`, scoped **per runtime** until request text is bound per run, then per session; never `session_busy`, which means a foreign lease holder | 7A.5, 19.23 |
| what an agent turn does to the read caches — unspecified, and nothing did it | enumerated invalidation on `terminal` / prompt response, by refetch of the server projection, never a client-side merge, never moving the pin | 7A.11 |
| §3's icon row parses two ways | a repo-owned inline SVG sprite is permitted **and required**; icon *packages* are the rejection | 3.2, 3.12 |
| §4.1's breakpoints are stated in prose and implemented twice | `useBreakpoint` is the sole authority; no media query changes `grid-template-columns` | 4.1a |
| §4.1 says the drawer is "resizable"; the code makes it *variable* | a fixed `--drawer-height` plus a drag handle; identical viewport height across all inspector tabs, asserted | 4.1c |
| §3's accessibility floor asserts a floor with no number | §3.13's seven numbered clauses, all measurable, plus the `token-contrast` check that catches the floor's own load-bearing token failing it | 3.13, 3.14 |
| whether the bytes-route enumeration is a reachability boundary | **no** — it constrains the named surface only, until the artifact kind is bound to the blob; the earlier claim is withdrawn rather than repeated | 2.6, 15.17 |
| whether "no export affordance" was a mechanism decision or a product decision | two decisions welded into one sentence; the mechanism half survives (narrowed), the product half was a deferral and has been answered | 15.17, 22 |
| whether §2.2's "never prompts for credentials" reaches model providers | no — it is about the **workspace bearer token** and stays true of it; provider credentials are a different object with a different lifetime and store | 23.0 |

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

**Added 2026-08-28.**

12. **§7A.5's project-wide run guard is a real usability cost paid for a real
    correctness property.** One live turn per *runtime* means an operator cannot
    ask the orchestrator something while a part session is thinking — in a
    workspace whose §7.1 renders three levels of concurrent sessions as nested
    tabs. It is the honest interim behaviour while `_request_text` is
    per-runtime, and §19.23 is the item that buys it back. If a reviewer holds
    that the cost is unacceptable even briefly, then §19.23 is a **prerequisite**
    of the composer rather than a follow-on, and the composer's Stage 4 landing
    moves behind it.
13. **§7A.11's invalidation is the client's first behavioural response to an
    agent event, and it is a new class of coupling.** Everything the client did
    before was render an event; this reacts to one by re-reading the project.
    The refetch-not-merge rule keeps §1 intact, but a chatty turn now produces a
    burst of refetches, and no budget is stated for it. If it proves noisy, the
    fix is a coalescing window at the invalidation boundary — **never** a
    client-side merge, which would put the boundary itself in question.
14. **§3.11's material authorship makes the client hold a display opinion for
    the first time.** Today the part looks like whatever `baseColorFactor` the
    GLB carries; after §3.11 it looks like what the client decided. That is
    correct for an instrument — but it means an exporter change can no longer be
    seen in the viewport, and the ≥4.5:1 floor is enforced by a browser
    measurement rather than by the geometry pipeline. If a later stage wants the
    viewport to show material provenance, this decision is what it has to
    revisit.
15. ~~**§22 and §23 are specified against a stage that does not exist yet.**~~
    **CLOSED 2026-08-28.** The stage exists: `mission_plan.md` §"Stage 10"
    carries G10A, G10B and G10C, so each section now has the gate clause — and
    therefore the CI job — whose absence was the whole of this risk. The
    out-of-scope-on-its-face rule for `/exports/**` and `/providers/**` PRs is
    retired with it; those PRs are now ordinary stage work, reviewed against
    their gate. **What the closure does not buy:** the strict ordering
    10A → 10B → 10C is a real dependency (§23.0's attach path is the
    precondition for a discovered credential being usable), and building 10C
    first would produce an offer with nothing behind it.
16. **§23.5's discovery offer was a proposed reading of mission rule 7. The
    maintainer ruled, and it is now an established one — under constraints that
    are themselves the residual risk.** The 2026-08-28 approval (§0.2a) grants
    discovery and keeps rule 7 intact, which means the two can now be confused:
    a reader who remembers "the operator approved local credentials" may take it
    for approval of *ambient* credentials, which it explicitly is not. The
    mitigating mechanism is mechanical rather than editorial and is the test
    §23.5 already named: **after any sign-in, `providers.json` must contain a
    record of every credential source in use — if a source works and no file
    names it, rule 7 has been broken.** G10C asserts it. The second residual is
    scope creep in the offer itself: discovery is permitted to describe
    `{kind, provider_id, model_ids, source_path}` and a reviewer should treat any
    additional field — a tail, a fingerprint, a validity probe result — as a new
    decision needing its own ruling, not as a detail of this one.

---

## 22. Egress — taking geometry out

> **NORMATIVE — Stage 10A, Gate G10A. Approved 2026-08-28.** The
> `mission_plan.md` amendment of §22.10 was granted under mission rule 5, on the
> precedent of Stages 8 and 9; `mission_plan.md` §"Stage 10 — Workspace egress
> and provider attachment (amendment 2026-08-28, maintainer-directed)" cites this
> section as its normative spec. Every clause below is in force as the design
> beneath **G10A**, which is the only text that binds. G4 and G5 keep their text
> verbatim; neither mentions export, and the amendment edits neither.
>
> **What the promotion does and does not license.** It licenses building §22:
> `/exports/**` exists as Stage 10A work. It does **not** retroactively license
> anything already shipped — §15.17's rewritten refusal is part of §22 and binds
> the implementation — and it does not move §22 ahead of its prerequisite: the
> §19.24 kind-binding correction lands in **Stage 4**, and G10A's
> relabelled-ref clause is unsatisfiable until it does.

**What this replaces.** §15.17 was two decisions welded into one sentence: a
*mechanism* decision (close `/artifacts/{ref}/bytes` by enumeration) and a
*product* decision (no export affordance, because a Download STEP button is the
product's first non-agent, non-CLI export path). The mechanism decision was
correct in aim, is narrower in effect than it claimed (§2.6's CORRECTION), and
is untouched here. The product decision was a deferral, correctly escalated to
§18.6 and never answered; the product owner answered it on 2026-08-28. §18.6 is
struck and §15.17 is rewritten.

### 22.1 What the engine writes, and what of it is offered

Measured against the public clean-room fixture, not read off a schema.
`EXPORT_FORMATS` (`cad_ops/_exports.py`) is six entries and there is no seventh:

| Format | Writer | Layouts | Kerf | Fixture output |
|---|---|---|---|---|
| `step` | `build123d.exporters3d.export_step` | `as_built` | never | 145 426 B |
| `stl` | `export_stl(ascii_format=False)` | `as_built` | never | 44 884 B |
| `gltf` → `.glb` | `export_gltf(binary=True)` | `as_built` | never | 48 244 B |
| `3mf` | `_three_mf_bytes` — one `<object>` per labelled solid + §5.2 metadata | `as_built` | never | 9 461 B |
| `dxf` | hidden-line `Drawing` → `_as_built_dxf`, `CUT` layer from §5.3 tags | `as_built`, `nested_sheet` | yes | 18 672 / 16 889 B |
| `svg` | same projection → SVG | `as_built`, `nested_sheet` | yes | 1 858 / 1 252 B |

`generate_drawing` writes PDF **and** SVG for three kinds on three sheet sizes,
with extracted dimensions and a title block. `generate_doc` writes Markdown
**and** JSON for `bom`, `assembly_instructions`, `spec`; the fixture BOM carries
registry densities, a per-item mass, and a provenance block naming the source
artifact ref and the script sha-256.

**DECISION: all six formats, both layouts, all three document kinds, all three
drawing kinds are offered.** There is no curated subset, because a subset needs
a rule and every available rule is arbitrary — "solids only" hides the DXF a
laser cutter wants; "the ones we tested" is all of them; "STEP, because that is
what the operator asked for" ships a format picker with one entry, which is not
a picker. The engine's enum **is** the closed vocabulary and the client renders
it from `TOOLS_BY_NAME["export_part"].params`, never from a list of its own —
§1's no-derived-fact rule reaches enums, not only values.

**Offered:** `format` (six); `layout`, revealed only for `dxf`/`svg` because the
tool's own conditional refuses it elsewhere and a control that exists only to
produce `invalid_params` is a trap; `blank` dimensions, revealed only for
`nested_sheet`.

**Refused — `kerf_mm` is not a browser control.** The resolution order is fixed
in `core/geom/kerf.py`: explicit → the DFM pack's `kerf_mm` → none, plus a
`kerf_uncompensated` note, and *a default kerf is never invented*. On the fixture
the pack resolves 0.2 mm from `laser_cut` without anyone asking. A number box in
a download dialog is the worst place in the product to override a manufacturing
constant: it is per-click, it is recorded nowhere a second operator will read it,
and it silently disagrees with the process pack the DFM panel is displaying two
tabs away. The panel **displays** the resolved `kerf.applied_mm`, `kerf.source`
and `kerf.process`, and renders `kerf_uncompensated` as a named warning on the
produced file. *Rejected:* an "advanced" disclosure containing the field — the
disclosure is the tell that the control does not belong on this surface.

**Refused — `target` is never accepted from the browser.** §2.3 admits no raw
filesystem path and this section does not reopen it. The server always takes the
no-target branch of `_output_paths`, whose stem is content-addressed over the
whole output set. Consequences, stated: the operator cannot choose the on-disk
filename, and `target_exists` is **unreachable** from the browser by
construction — which is the point, because a create-only collision is a failure
the operator could neither see nor clear from a browser.

**Refused — `artifact_ref` is not optional and is never `null`** (§22.5).

### 22.2 Export is a mutation, and how it keys

It is a mutation on all three of the product's own definitions: `export_part`
carries `ToolDecl.idempotent = True` and is therefore in `MUTATION_TOOLS`;
`tool_schema.md` says "Source/config/output mutations carry an idempotency key in
trusted invocation" and "Export invocation metadata carries the idempotency key";
and it **writes** — a file under `.heph/exports/` through a confined create-only
walk, a blob, a GC-root pin, a reachability link, and a row in the `tp_exports`
write-ahead table. It is an **output** mutation, not a source mutation, so §22.5's
read-only-over-design-state axis does not reach it.

It joins §2.3's first table, and it is the only member of that table needing **no
ledger extension**: unlike `POST /git/tag` and `POST /project/config/dfm`, which
have no tool and nothing to replay from, these three replay a complete
`ExportCommit` — paths, `source_artifact_ref`, `source_input_hashes`,
`export_hashes`, and the per-operation `extra` — from a `COMMITTED` row. The
`extra` column exists precisely so a committed retry replays the *whole* result
and not just its filenames.

**Two key layers, and they agree.** §2.5's REST key is derived from `(project
keyring HMAC, route identity, Idempotency-Key header)` with the body carried
separately as `payload_hash`. `_begin_export` independently hashes a canonical
payload and raises **`key_payload_mismatch`** when a known `op_id` arrives with a
different one — the same reason string `opstore/errors.py` raises and §2.4
already tabulates. **No new key vocabulary is introduced**, and the layers are
not collapsed: the REST ladder decides whether the request is admitted, the
export WAL decides whether it re-runs.

**WHY key an export at all**, since the operator's mental model is "a download":
because `_commit_export` installs create-only. A keyless retry after a dropped
145 KB response would not produce a second file — it would collide with its own
first attempt and refuse. With a key, a dropped download is a replay that returns
the identical result document and the identical bytes, marked `"replayed": true`.
The key is what makes retry the obvious thing to do rather than the thing that
breaks.

**TIGHTENING (binds the client).** The key is minted once per *submission*, not
once per click: the client reuses it across transport retries of one export and
mints a fresh UUIDv7 the moment any field changes. A stale key with a changed
format is `key_payload_mismatch`; a fresh key with unchanged fields silently
produces a second identical file. Both are wrong and both are the client's to
prevent, so the panel owns the key and the retry button does not re-mint.

### 22.3 How the bytes reach the browser — and what the enumeration actually buys

**`export` stays in `REFUSED_BYTES_KINDS`, and the reason is stated more
carefully than it was.** §2.6's CORRECTION establishes the mechanical fact: the
bytes route resolves by hash, its kind segment is a caller-supplied label, and
export outputs live in the same blob store. **Until §19.24 binds kind to blob,
the enumeration constrains which *named surface* serves export bytes and does not
constrain reachability.**

What the enumeration does buy — and it is worth keeping — is a **surface**
boundary. `GET /artifacts/{ref}/bytes` is authorized by project-scoped
reachability alone (§2.2): it is the workspace's one *"hand me a blob"*
primitive. Serving export bytes through it would make egress a **side effect of
blob storage** rather than a named operation: every export any agent ever
produced during any run, fetchable by ref, with no result document, no
`source_input_hashes`, no kerf readout, and no audit row. That is not a security
boundary — loopback, `0600` token, the same local user who can `ls .heph/exports/`
— it is a design boundary about what egress *is*.

So what replaces the refusal is not a widened set but a **third route with its
own authorization argument**, which is exactly the shape §2.6's own title
establishes. The extraction is shared: it calls the same `_blob()` reachability
check, so mission rule 6 is satisfied by construction.

**ORDERING CONSTRAINT, non-negotiable.** `export_hashes` in a response body and
`GET /parts/{part}/exports` are what turn "nobody knows the hash" into "every
client knows the hash". **Neither ships before §19.24.** Stated as a constraint
because the alternative is shipping a boundary the product believes it has.

**One grounding fact the record should carry.** The kind the enumeration refuses
is a kind the production path does not currently mint: `EXPORT_REF_PREFIX` has
exactly one producer (`Publisher.publish_export`), and that has **no production
caller** — grep finds it only in `tests/stage0b/`. The shipped `export_part` path
takes `_commit_export`, which does `blobs.put` → `gc.pin` → `gc.link` and returns
`export_hashes: {rel_path → sha256:…}`. The pytest that submits an `export` ref
to the bytes route is testing a ref shape only tests construct. The refusal
should stay, and it was aimed slightly past its target. Saying so is cheaper than
a reader discovering it.

**The routes.**

```
POST /parts/{part}/export     Idempotency-Key required   → result document, NO bytes
POST /parts/{part}/drawing    Idempotency-Key required   → result document, NO bytes
POST /parts/{part}/doc        Idempotency-Key required   → result document, NO bytes
GET  /parts/{part}/exports                               → committed tp_exports projection
GET  /exports/{export_blob}/bytes                        → the file, as an attachment
```

**DECISION: the mutation returns no bytes.** The three POSTs return the tool
result verbatim. WHY: collapsing production and download into one response would
mean a retried *download* re-enters a keyed *mutation*, would put a
multi-megabyte binary where §2.4's refusal payload has to fit, and would make
"the export failed" and "the transfer failed" the same event. Two steps, two
failures, two error messages.

**DECISION: the download is addressed by blob hash, not by an artifact ref.**
`export_blob` is a value the caller read out of `export_hashes` — the
`sha256:<hex>` the store itself assigned. Not `artifact:export:…`, because
production does not mint one; not a path, because §2.3 admits no filesystem
paths.

**TIGHTENING — the authorization, stated as its own rule.**
`GET /exports/{blob}/bytes` serves a blob **only** when it is named by the
`outputs` column of a `tp_exports` row in the **`COMMITTED`** state in the open
project. Not "stored". Not "pinned". A `FROZEN` row's blob, a blob stored for any
other reason, and a blob from another project are all **404 `unknown_export`**.
This is strictly narrower than the bytes route's reachability check, which is why
it can exist without widening anything: it is not a blob-fetch primitive, it is a
re-read of a recorded result.

**Response headers.**

| Header | Value | Why |
|---|---|---|
| `Content-Type` | from format, one enumerated map with a drift test (§19.36) | a format added without a content type is a test failure, not an `application/octet-stream` |
| `Content-Disposition` | `attachment; filename="<part>-<blob[:12]>.<ext>"` | **derived from the blob hash and the format, never echoed from `rel_path`** — see below |
| `X-Content-Type-Options` | `nosniff` | an SVG is a document with script capability and the workspace origin holds the bearer |
| `ETag` | the blob hash | honest: the address *is* the digest |
| `Cache-Control` | `private, max-age=31536000, immutable` | `private`, unlike `/artifacts/bytes`'s `public`, because this response carries a bearer and a shared cache is the one place it should never land |

**TIGHTENING (2026-08-28 review) — the filename is derived, not echoed.** An
earlier draft said the filename "is the server's — already
`_validate_relative_target`-confined and content-addressed. Never a
client-supplied string." That is true of exports **the panel** creates, because
the panel cannot send a `target`. It is **not** true of the rows this route
actually serves: it serves any blob a `COMMITTED` row names, including every
export an agent produced with an explicit `target`, and `_validate_relative_target`
confines traversal while permitting `"` and `;` — the two characters that
structure a `Content-Disposition` parameter list. The filename is therefore
derived from the blob hash and the format extension, which is what the
content-addressed argument already described; the recorded `rel_path` renders as
**body text in the panel**, where a quote is harmless.

**TIGHTENING (security).** Every export byte response is `attachment` + `nosniff`
and **an SVG is never served inline**. §2.6 puts the same two headers on
`/artifacts/{ref}/bytes`, because that is the route an artifact SVG can actually
be fetched through and a mitigation present only on the route the attack cannot
use is decoration. *Rejected:* serving SVG inline so the panel can preview a cut
file — a preview is worth less than the token.

### 22.4 The download itself: bytes without a token in a URL

§2.2's DECISION is that the bearer rides in the **fragment**, never a query
string, so it never enters an access log or a `Referer`. A file download must not
undo that. The problem is mechanical: `<a href download>`, `window.open`, and a
form POST all navigate, and a navigation carries no `Authorization` header.

| Option | Verdict |
|---|---|
| Token in the query string | **Rejected.** Exactly what §2.2 forbids, and worse than the general case: a download URL lands in the browser's *downloads list*, which outlives the serve and the `sessionStorage` the token was moved into. |
| A cookie | **Rejected.** §2.2: no login, no cookie, no refresh, no user model. It would also add CSRF surface to a route table that has none. |
| A one-shot signed capability URL | **Rejected.** A second credential with its own minting, lifetime and revocation story is an authentication subsystem, which §15.6 excludes — and it re-creates the leak it fixes, because the capability URL lands in the downloads list too. |
| A service worker injecting the header | **Rejected.** A second runtime with its own cache and update lifecycle, added to buy a progress bar. |

**DECISION: `fetch` with the bearer header → `Blob` → object URL → synthetic
click → `URL.revokeObjectURL` in a `finally` on every path including the throw.**
The token never enters any URL; the object URL is same-origin and opaque. The
`filename` comes from the export **result document** the client already holds,
not from parsing `Content-Disposition` — the client would otherwise be
re-deriving a fact it was handed, which §1's lint exists to prevent.

**The cost, named rather than discovered.** The whole file buffers in the tab's
memory before it reaches disk, and there is no progress. On the fixture that is
1.2 KB to 145 KB and invisible; on a large assembly STEP it is tens of megabytes
and a visible stall. **TIGHTENING:** the panel renders the byte count from
`export_hashes` and the exports projection **before** offering the download, so a
large file is a stated cost and not a hang, and the button enters
`data-export-state="transferring"` for the duration. A file the workspace cannot
buffer is a refusal (`export_too_large`) carrying the size and the CLI path to
the file on disk — not a crashed tab. The threshold is a server constant,
enumerated, never a client guess.

### 22.5 Provenance: which ref, which snapshot, what is content-addressed

**DECISION: `artifact_ref` is required on all three POST routes and is always the
workspace pin.** The client sends `WorkspaceState.artifact_ref` (§4.5) verbatim.
Never `null`, never "current", never resolved server-side at click time.

WHY this is the most important decision in the section: `_freeze_export_source`
has two branches, and with `artifact_ref = None` it resolves
`publisher.current_result(name)` **at export time**. The workspace pin is sticky
and is never auto-advanced (§4.5's tightening binding G5.6) — so a `null` ref
means the operator looks at build A, clicks Export, and receives a STEP of build
B because B published in between. That is precisely the silent fallback-to-current
that `architecture.md` §4.4 forbids outright, and it is the failure A/B discipline
exists to catch. **The exported file must be the geometry on screen or the
workspace is lying with a download.**

A consequence that reads as a bonus and is really the same decision: with an
explicit ref, `stale_source` is unreachable. Staleness is a statement about the
*script*, not about the artifact, and a pinned build is a real, complete,
reproducible build no matter how far the script has moved on. So the workspace
**does not refuse to export a stale part** — it exports the pin and says what the
pin is (§22.7).

**What travels with the file, in three layers.**

*Layer 1 — the result document, which is the audit row.* `source_artifact_ref`,
`source_input_hashes`, `export_hashes`, `paths`, and `kerf` when present. This is
what the panel renders and what `GET /parts/{part}/exports` replays.

*Layer 2 — inside the file, only where the format already has a place for it.*
3MF carries the §5.2 manufacturing metadata `_three_mf_bytes` already writes. DXF
carries the `CUT` layer and the §5.3 tag-derived separation of through-cuts from
`engrave_*`/`score_*` geometry. **STEP, STL, GLB and SVG carry nothing, and
nothing is injected.** WHY: G3's clause is that the exported STEP re-imports with
matching volume, and the moment the product writes a byte into a STEP that
`build123d.exporters3d` did not write, the product owns a STEP writer. Mission
rule 6. Provenance lives beside the file.

*Layer 3 — beside the file: nothing.* **DECISION: no `.provenance.json`
sidecar.** It would be a second provenance store that can drift from
`tp_exports`, `_output_paths` would have to carry a suffix that is not a format,
and `_commit_export`'s multi-output rollback would have to know which of its
files is not a deliverable. The `tp_exports` row **is** the record.

**Content-addressed and pinned: yes, twice.** The blob hash is sha256 over the
exact bytes and is the download address. The on-disk stem, absent a `target`, is
content-addressed over the whole output set — which is why a drawing's PDF and
SVG share a stem and differ only by suffix, and why the same export run twice
with the same key produces one file rather than two.

**A named weakness, and it is real.** `_source_input_hashes` returns the build's
full `input_hashes` — script hash, params, frozen imports — **only when the
frozen ref happens to be the part's current result**. For any other pinned ref it
degrades to `{"source_artifact": "sha256:…"}`. So the export of an older pin
carries strictly *less* provenance than the export of the current build, which is
backwards: an old pin is the case where you most need to know what produced it.
The bundle at `source_ref` contains those hashes and nothing reads them back.
**NEW WORK (§19.39).**

### 22.6 GC and pinning: what an export costs, permanently

Facts, from `_commit_export` and `opstore/gc.py`: every output blob is `gc.pin`ned
— an unconditional GC root — and `gc.link`ed to its source build's blob.
`reachable()` is pins closed transitively over links. Three consequences follow.

1. **An export permanently protects the build it came from.** This is the
   intended shape and it is what makes re-exporting an old pin reproducible and
   its provenance panel resolvable. It is also why §12.4's "A's source map is no
   longer stored" state becomes rarer for any part that has ever been exported.
2. **Export is the first affordance in the workspace that lets a browser user
   create an unbounded, un-collectable retention obligation.** Every other write
   in the route table is bounded — a script version, a param set, a tag. An
   export pins bytes and a build forever. That is not a reason to refuse it; it
   is a reason to **show** it, which is why §22.7's panel carries an export
   history with a running byte total rather than a fire-and-forget button.
3. **There is no unpin surface anywhere in the product.** `tool_schema.md`
   promises exports are "pinned as a GC root until explicit
   `heph export unpin/delete`". `ExportOps.unpin_export` exists and its docstring
   names that verb. Grep finds **one** caller, a server test. **There is no
   `heph export` verb at all.** The promise's second half is unimplemented across
   the entire product, and this section makes the pressure on it materially
   worse.

**DECISION: the workspace offers no unpin and no delete, and says so by name.**
§2.3's "no `DELETE` anywhere" is a route-table decision this section does not
reopen, and a destructive, irreversible, quota-affecting operation is the last
thing to add to a surface whose first write this is. The panel states, as
designed copy rather than as an omission: *"Exports are kept until they are
unpinned from the command line. This workspace does not delete them."* §19.40
makes that sentence name something that exists.

**CORRECTION (2026-08-28 review) — what actually happens when exports accumulate,
stated truthfully.** An earlier draft argued that `GcCollector.admission_guard()`
fails new artifact-producing work when protected bytes exceed the quota, and
therefore that heavy exporting eventually makes **builds** refuse — surfacing
that as `quota_exceeded` on the export routes. Two things were wrong with it.
`admission_guard()` has **zero production callers** in the repo (its own
definition, opstore tests, and one stage0b adapter test), so builds do **not**
refuse today; the real consequence of unbounded export pinning is **unbounded
disk growth with no guard at all**, which is a different and worse shape than the
one the draft defended. And the engine's reason for that condition is
`protected_quota_exceeded`, not `quota_exceeded` — inventing a second name for a
state the engine already names is exactly the drift §2.4's mapping table exists
to prevent, under a rule (§22.7) that says every string is the engine's.

Restated: **exports pin unboundedly and nothing currently refuses on the strength
of it, so the retention obligation is presently invisible rather than eventually
loud.** §22.6's argument therefore rests on what actually exists — the visible
export history with its running byte total, and the `heph export unpin` CLI verb
of §19.40. Wiring `admission_guard()` into the artifact-producing paths is a real
gap this section makes worse, and it is named as its own new-work item rather
than assumed; when it lands, the export routes surface the engine's own
`protected_quota_exceeded` **verbatim** through §2.4 with the `GcUsage` numbers,
and never as a generic 500 — because *"your builds stopped working because you
downloaded too much"* is the most confusing failure this section is capable of
producing and the only defence is to name it at the moment it is caused.

### 22.7 The affordance: where it lives, what it offers, how it refuses

**DECISION: the Inspector gains a sixth tab, `export`. The header gains
nothing.** WHY the Inspector: §4.3's provenance spine puts the *pin* in the
header and everything the pin *implies* in the Inspector — Results, Properties,
Provenance, Checks and DFM are all statements about the pinned artifact, and an
export is another one. It inherits the pin without a second control, and it sits
beside the DFM panel whose process pack decides the kerf it will report. WHY not
the header: the header is 44px of the most contested space in the app and already
renders the word "current" twice in two different closed vocabularies (§4.1) —
adding a third element there is how that defect happened.

**TIGHTENING.** `ExportPanel` is the only Inspector tab containing a control that
writes, so it renders its **subject before its controls**: the pinned ref, its
`pin_mode`, and the part, on the first line, above any format button. There is no
bare "Export ▾" that resolves its subject at click time. The tab is
`data-inspector-tab="export"`; the panel carries `data-export-state`; format
buttons `data-export-format`; refusals `data-export-refusal`.

Two steps, not one: **Export** runs the keyed mutation, **Download** fetches the
bytes. They are two routes with two failure modes, and a single button would
report a create-only refusal and a transfer failure with the same spinner. Below
the fold, the history from `GET /parts/{part}/exports` with byte totals, so
§22.6's retention is a number the operator can see rather than a fact they
discover.

**How it refuses. Closed vocabulary; every string is the engine's.**

| Condition | Reason | Rendered as |
|---|---|---|
| Pinned ref is a failed build's checkpoint | `invalid_source` | disabled; *"the pinned artifact is a failed build's checkpoint, not a build — export freezes successful geometry only"* |
| `pin_mode = "current"`, no successful build | `AddressingError` | disabled; renders `candidates` |
| Pinned build's blob no longer stored | `invalid_source` | disabled; *"this build's artifact is no longer stored"* — distinct from the above, **never folded into it** |
| `nested_sheet`, no blank declared and none given | `blank_undeclared` | reveals explicit width/height; states that a part whose `blank_size` is computed at runtime cannot be read statically (the fixture's `tread` does this **on purpose**) |
| A profile will not fit the blank | `NestingRefusal` reasons | names the profile and the blank; never a silent overlap, never a clipped part |
| Kerf resolved to none | `kerf_uncompensated` | **a warning on the produced file, not a refusal** — the file is correct, it is just nominal |
| Sandbox absent | `capability_not_available` | §15.7's existing rendering, unchanged |
| Same key, changed options | `key_payload_mismatch` | *"this export was already run with different options"* + the recorded options |
| File too large to buffer | `export_too_large` | the size, and the CLI path to the file on disk |
| Blob not from a committed row | `unknown_export` | 404 |
| *(only once §19.40's guard is wired)* protected bytes over quota | `protected_quota_exceeded` | the engine's reason verbatim, with `GcUsage` |

**Stale and failed builds, explicitly, because the question was asked.** A
*stale* part is not a refusal — the pin is exported and the subject line says the
build is behind the script. A *failed* build has no `build`-kind ref to pin, so
the controls are disabled with the checkpoint or addressing reason above and the
panel names the build error rather than rendering an enabled button that will
4xx. This is the distinction §4.4 already draws for provenance: a legitimately
weak answer that says why it is weak reads as instrument honesty; the same answer
with a disabled control and no sentence reads as a bug.

### 22.8 Neighbouring egress: what ships together

**Ships in this stage.** *Nested-sheet DXF/SVG* — not a separate capability but a
`layout` argument of the same tool through the same WAL, pin and confinement;
refusing it would mean a format picker that offers DXF and then hides the only
layout a laser cutter wants. *Documents* — literally the same `wal_export` code
path with the same key policy, pin, link and download route; a BOM with
registry-density masses and a provenance footer is what a person hands to a shop
and is the highest value per byte in the audit. *Drawings* — same path, shipped
as **downloads only**.

Naming the drawing tradeoff rather than hiding it: a downloaded PDF the workspace
cannot show is a weaker deliverable than a downloaded STEP, because a STEP's
destination is another application by definition while a drawing's destination is
a pair of eyes. The honest response is not to withhold the file — that is
precisely the arbitrariness this section corrects — but to say the *viewer* is
deferred, to §18.10.

**Deferred, with reasons.** Posed renders (§18.11 — not egress in this sense).
Rotation- and yield-aware auto-nesting (mission rule 5's closed deferred list;
`shelf_nest` is deterministic shelf packing in profile order with no rotation and
says so in its own docstring — this section ships the nesting that exists and
does not imply the nesting that does not). Export unpin/delete from the browser
(§22.6). Kerf override and `target` (§22.1). **Import** — one sentence because
the operator's phrasing invites it: `import_geometry` and `run_fea` are excluded
from `TOOLS` (§15.14) and STEP import is on mission rule 5's closed deferred
list. **Geometry leaves Hephaestus in this stage; it does not come back.**

### 22.9 Exclusions this section adds

Carried into §15 as refusals 36–37. Each with its WHY:

1. **No metadata injected into STEP, STL, GLB or SVG.** G3's re-import clause;
   the moment the product writes a byte a format's own writer did not, the
   product owns that writer (mission rule 6).
2. **No provenance sidecar file.** The `tp_exports` row is the record; a second
   store can drift from it (§22.5).
3. **No filesystem path on the wire, in either direction.** `target` is
   server-chosen; the download filename is blob-derived (§22.1, §22.3).
4. **No kerf override from the browser.** A per-click manufacturing constant
   recorded nowhere is worse than no control (§22.1).
5. **No unpin, no delete, no `DELETE` route.** §2.3's decision is not reopened by
   the section that makes retention pressing (§22.6).
6. **No inline rendering of any exported byte, SVG first among them.** A preview
   is worth less than the token (§22.3).
7. **No streaming, no progress bar, no service worker.** A buffered download with
   a stated size, and a named refusal above the ceiling (§22.4).
8. **No export from an unpinned "current".** `artifact_ref` is required, because
   a `null` ref silently exports a different build than the one on screen
   (§22.5).
9. **No import. Egress is one-way** (§22.8).

### 22.10 The `mission_plan.md` amendment this section needed — GRANTED 2026-08-28

**Status: landed.** `mission_plan.md` §"Stage 10 — Workspace egress and provider
attachment (amendment 2026-08-28, maintainer-directed)" carries **Stage 10A** and
**Gate G10A**, citing this section as its normative spec. The clause shape below
was reproduced in `docs/workspace-plan.md` §9 in the form the maintainer would
approve, so it could be read in one pass, and **G10A carries it verbatim** — plus
the two CLI clauses §22.6 requires, `heph export list` and `heph export unpin
BLOB`, which the plan's gate text already named. `mission_plan.md` is the only
text that binds; the shape is repeated here so this section can be read without
leaving it, and if the two ever disagree, the gate wins and the disagreement is a
defect in this section.

> Playwright pins artifact **A**, exports STEP from the pin, and asserts the
> downloaded bytes' sha-256 equals the `export_hashes` entry the route returned;
> publishes build **B** for the same part; re-exports from the still-pinned **A**
> and asserts the same digest, and that a `null`-ref export is not reachable from
> the client. A DXF export of the same pin asserts `kerf.source == "dfm"` and
> `applied_mm == 0.2` from the process pack. `GET /artifacts/{ref}/bytes` refuses
> the export's ref **and** refuses a `build`-relabelled ref naming the same blob.
> An export with no `Idempotency-Key` is `400 idempotency_key_required` with no
> file created; the same key twice yields one file and `"replayed": true`; the
> same key with a changed format yields `key_payload_mismatch`. `heph build` on
> the fixture, then a `gc.collect()`, leaves the exported blob and its source
> build blob both reachable.

The A/B half is what makes the export honest rather than merely present, and it
is the same discipline G5.5 imposes on selection. **The relabelled-ref clause is
the 2026-08-28 review's addition and is the one that proves §19.24 landed**; a
gate that asserted only the `artifact:export:…` refusal would pass against a
route that serves the same bytes under a different label.

---

## 23. Provider sign-in — attaching a model to the workspace

> **NORMATIVE — Stage 10B, Gate G10B. Approved 2026-08-28.** The
> `mission_plan.md` amendment of §23.14 was granted under mission rule 5. Every
> clause below is in force as the design beneath **G10B**, which is the only
> text that binds.
>
> **And the one question this section did not have the authority to answer is
> answered** (§23.5). The operator ruled on home-directory credential discovery
> on the same day — *"The server should be able to work locally, the same way
> that Claude for science works"* — approving it **with binding constraints**.
> It enters as its own gated sub-stage, **Stage 10C, Gate G10C**, strictly after
> 10B, because a discovered credential is unusable without 10B's attach path.
> §23.5 carries the ruling and its constraints in full; the marker
> **OPEN — MAINTAINER SIGN-OFF REQUIRED** is struck wherever it appeared.

**What it amends, enumerated.**

- **§2.2** — *"it never prompts for credentials, because there are none to
  prompt for. No login, no cookie, no refresh, no user model."* That sentence
  answered *how does the browser authenticate to the server* and was then allowed
  to stand as if it had answered *how does the operator attach a model*. It is
  **narrowed to the workspace bearer token**, which remains exactly as specified.
  Provider credentials are a different object with a different lifetime and a
  different store, and §23 is that store's contract.
- **§4.2** — gains `ProvidersPanel` and `SignInDialog`, marked **Stage 10B**
  (the panel's discovery affordance is Stage 10C).
- **§2.3** — gains the `/providers/**` block, split across both key-policy tables.
- **§15** — refusal 41; and it **strikes refusal 34**, which §7A.8 wrote as dated
  and conditional precisely so this strike is a one-line edit rather than a
  contradiction.
- **§17 exclusion 10 (no event-vocabulary extension)** — **not** amended. §23.6
  carries the entire sign-in conversation on plain request/response routes so
  that exclusion survives untouched. An earlier draft carried the auth
  interaction over `/events`; it is withdrawn.
- **§17 exclusion 6 (no TLS, real authn, multi-tenant isolation)** — **not**
  amended. A provider sign-in is not authentication of the operator to the
  server. Conflating the two is the mistake §2.2 already made and §23 does not
  repeat.

### 23.0 The state this section exists to fix — and the capability it needs first

Today a project with no `.heph/providers.json` serves every read route and
refuses every session route with `agent_unavailable`. That refusal is correct,
named, and addressed **to someone at a terminal**. The operator is in a browser,
looking at a panel that has told them accurately that the thing they want does
not exist, and has given them no path to making it exist.

**BLOCKING FINDING, folded in and made the first item of work.** *(2026-08-28
review.)* A draft of this section could not be used in the state it exists to
fix. `_attach_agent` returns `None` when `providers.json` is absent, so there is
**no `BridgeRuntime`, no `Supervisor`, and no sidecar process at all**. Every
credential route is a relay to the sidecar; §23's own precondition table refused
them `503 agent_unavailable` — "no sidecar; nothing to configure" — in exactly the
zero-config case. And even if the file were written, the apply mechanism was
`Supervisor.restart()`, which needs a Supervisor that does not exist:
`attach_sessions` is called from one place, once, during `serve`. The section's
own gate clause was unsatisfiable as written, and the operator was still being
sent back to a terminal, which is the whole of complaint 4.

**The missing capability is named, and it is item 1 of §23.14: attach an agent
runtime to a *running* serve.** `_attach_agent`'s body is refactored so serve-time
and post-hoc attach are one code path, exposed as
`WorkspaceRuntime.attach_agent()` and reachable as `POST /providers/attach`.

**The route block is therefore split by dependency, and the precondition table
with it:**

| Route class | Needs a sidecar? | Refuses `agent_unavailable`? |
|---|---|---|
| `GET /providers`, `PUT /providers/specs` | **No** — they read and write a file | **No.** Refusing these in the zero-config case is what made the section unusable. |
| `POST /providers/attach` | No — it *creates* one | No; it reports per-provider verification results |
| `GET /providers/catalog`, every `auth/*` route | **Yes** — Pi is the credential store | Yes, and correctly |

The success path of sign-in is not "the panel says connected". It is:
`agent_unavailable` disappears → `GET /sessions` returns → the empty state becomes
an action → **no session → create one → prompt it** (§7A.2's blank canvas). A
sign-in surface that ends at a green checkmark has not answered the complaint.

### 23.1 Supported credential kinds (closed)

Four provider kinds exist in the runtime and collapse to **three credential
mechanisms**: `anthropic` (API key), `openai_compatible` (API key + `baseUrl`),
`local` (endpoint only, credential optional), and `pi_native` (Pi's built-in
catalog; the credential is whatever the app-owned `auth.json` holds, reached by
subscription OAuth). §23 supports all three mechanisms and adds no fourth.

**DECISION: no Hephaestus-defined provider catalog.** *Rejected:* a curated "sign
in with X" list maintained in this repo — a second catalog beside Pi's, drifting
the moment Pi ships a provider, which mission rule 6 forbids. The list the panel
shows is `runtime.getProviders()`, read live over the bridge.

**DECISION: `pi_native` remains structureless.** Its spec carries an id and model
ids — no `credential`, no `baseUrl`, no `api`. §23 adds no field to it. That
structurelessness is load-bearing: there is no field through which a key could be
smuggled into a subscription provider, so "subscription" and "keyed" cannot be
confused at the type level.

### 23.2 Where a secret lives, and what writes it

**A provider secret may exist in exactly three places, and the list is closed:**
`<project>/.heph/agent/auth.json` (`0600`, parent `0700`, written by **Pi's
`AuthStorage` only**, through the sidecar); the serving process's heap en route
to `runtime.configure`; and the sidecar's heap inside the registered provider.

**Two places a secret may never appear, both enforced rather than declared:**

1. **`providers.json`.** It holds specs, *variable names*, a path, and endpoint
   acknowledgements. It has never held a secret and §23 does not make it one. The
   workspace writes it with `write_private` at `0600` — created private, never
   `chmod`'ed after, because the window between written and chmod'ed is exactly
   when another local user could open it. A file the **operator** hand-authored
   is not `chmod`'ed by the workspace; changing the mode of a file we did not
   write is a surprise, and the panel reports the mode instead.
2. **The opstore.** No credential material enters an artifact, a build record, a
   golden, a transcript, a drawing, a document, or a bench evidence bundle, and
   §23.14's leak test is what makes that a claim about what a search finds rather
   than about what a reviewer believes.

**DECISION: Hephaestus is not a secret store; Pi is.** Everything persisted goes
through `ModelRuntime.setRuntimeApiKey` / `login` → `Models.login` →
`credentials.modify` → `FileAuthStorageBackend`, which writes `0600` under a
`proper-lockfile` cross-process lock. *Rejected:* a Python-side credential file
with its own format and locking — a second authority over the same fact, drifting
from what the sidecar actually holds, which mission rule 6 forbids. The cost is
stated: **every credential write requires a live sidecar**, which is why §23.0's
attach capability is item 1 and not a footnote.

**DECISION: API-key persistence has no default.** Every key submission carries a
required, closed `scope`: `serve` (serving-process heap only; restarting forgets
it) or `project` (written to `auth.json`, survives restarts). Omitting it is
refused `credential_scope_required`, **not defaulted**. A defaulted
secret-persistence decision is the single most consequential default a local tool
can have, and this document declines to make it. *Rejected:* defaulting to
`serve` for safety — it reads as safe and produces an operator who retypes a key
every morning until they stop using the product.

**The env-variable path is unchanged and is not deprecated.**
`credential_allowlist` + `build_minimal_env` remains the mechanism for an
operator who manages secrets outside the product. §23 adds a path; it removes
none.

### 23.3 Flow — API key paste

`GET /providers` → the operator opens `SignInDialog`, picks a kind, and (for
`openai_compatible` and `local`) types a `baseUrl` → the key goes into a
`type="password"` field with `autocomplete="off"` and no `name` a password
manager would save under a misleading identity → `POST /providers/{id}/auth/key`
with `{key, scope}`, **the key in the body**, never a path segment, query
parameter, or fragment → the server relays it to `runtime.setApiKey` or holds it
in the configure map → attach-or-restart (§23.7) → the response carries the
§23.8 projection and **not the key**.

**The fragment is not a safe place for a provider secret either**, and this is
the one place §2.2's reasoning does not transfer. The bearer rides in the
fragment because a fragment never reaches an access log or a `Referer`. A
provider key is same-origin-visible to the page, does not expire with the serve,
and is worth more than the token. Body or nowhere.

**Endpoint rules, because a `baseUrl` typed in a browser is an outbound network
destination**, and every subsequent turn POSTs project geometry, script source
and transcripts to it:

- Kind `local` **must** resolve to a loopback IP literal or the literal host
  `localhost`. A hostname is refused `endpoint_not_loopback` — a name can
  re-resolve between the check and the request, and a check a name defeats is
  decoration.
- A non-loopback endpoint is **not kind `local`**. It is `openai_compatible`, and
  it requires `egress_acknowledged: {host, at}` recorded in `providers.json` and
  re-affirmed by **typing the host**, not by clicking a checkbox. `heph serve`
  prints every acknowledged egress host at start-up and `ProvidersPanel` lists
  them permanently. Silently accepting an arbitrary URL is an exfiltration path
  with a UI on it; the answer is not refusal but **durable visibility** — a file
  a reviewer can read, not a dialog someone dismissed.

**TIGHTENING (2026-08-28 review) — these checks live on the spec write, not on
the key paste.** `baseUrl` arrives in `PUT /providers/specs`, so
`endpoint_not_loopback` and `egress_not_acknowledged` are enforced there. An
earlier draft enforced them on the key flow, where the endpoint is not an
operand.

### 23.4 Flow — subscription OAuth (`pi_native`)

Two mechanically distinct flows exist in the pinned dependency; §23 supports both
and adds neither.

**Device code — the default where the provider offers it.**
`POST /providers/{id}/auth/begin {type:"device_code"}` relays `runtime.login.begin`
to the sidecar; **Pi** contacts the provider. The route returns **only**
`{user_code, verification_uri, interval_seconds, expires_at}` — four values, none
secret. The panel renders the code large and the URI as a link the operator opens
in a normal tab. The client polls `GET /providers/{id}/auth/status`; the
**sidecar** polls the provider, honouring `authorization_pending` and `slow_down`.
Poll state lives in the sidecar; **the browser never touches the provider.** On
completion Pi exchanges the code and persists the credential, and the status
route flips to `{"state":"project","type":"oauth","expires_at":…}` — **no token
in the body, ever.**

**DECISION: device code is the default because it opens no listening socket.** It
works over SSH, in a container, and cannot collide with a real provider CLI
login. Every other property follows from that one.

**Authorize URL + manual paste — the universal fallback**, for providers whose
flow is callback-only and for any device-code flow the operator cannot complete.
`begin {type:"authorize_url"}` returns `{authorize_url, expires_at}`; Pi mints
the PKCE verifier and the `state` and **both stay in the sidecar**. The operator
approves, is redirected to a loopback callback where **nothing is listening**,
the browser shows a connection error, and the URL bar holds the answer. The
operator pastes it into `POST /providers/{id}/auth/complete`; Pi's
`parseAuthorizationInput` accepts a full redirect URL, a `code#state` pair, or a
bare code, and **verifies `state`** — a mismatch is
`authorization_state_mismatch`, refused, credential unchanged.

**DECISION: no loopback callback listener, ever.** *Rejected* on three
independent grounds, any one sufficient: the redirect URIs are **fixed by the
provider's registered client**, so the port cannot be chosen to avoid a collision
and a real CLI login already running makes the flow fail with a bind error the
operator cannot act on; a second listening socket contradicts §0's
one-loopback-listener posture and the second one would be **unauthenticated**,
inside a route table whose whole discipline is that it is closed and gated; and
the manual-paste fallback is already implemented in the pinned dependency and
adds **zero** new network surface. The cost is stated rather than hidden: **the
callback-only subscription flow is a copy-paste and will look unpolished next to
a one-click login.** That is the price of not opening a socket, and §23 pays it
deliberately.

**The server is not an OAuth client and applies to become one for nobody.**
Hephaestus registers no OAuth client with any provider. The client id, the PKCE
verifier and the token exchange are Pi's, running in the sidecar, using the
correct endpoints and refresh semantics. The Python side sees four non-secret
values on the way out and `{state, type, expires_at}` on the way back, and never
sees an authorization code, an access token, or a refresh token at all. This is
the mission-rule-6 answer to *may the server act as an OAuth client on the
operator's behalf*: it may act as a **relay for a flow it does not implement**.
Two implications the UI states rather than buries: the operator's provider will
list **Pi** in its authorized-applications page, said before the operator clicks
— an operator who later revokes "that Pi thing they don't remember installing"
and finds Hephaestus dead was misled by our silence; and **Hephaestus never
refreshes a token** — there is no refresh clock, no refresh route, and no refresh
error vocabulary of our own.

### 23.5 The `auth_source` symlink — and the one question this section could not answer, now ruled

`link_auth_source` symlinks `<project>/.heph/agent/auth.json` at an existing Pi
`auth.json` so `pi_native` providers can use a login the operator already has. It
is opt-in and refuses to clobber a non-placeholder file.

**That protection guards link *creation*, not later writes *through* the link.** A
sign-in performed while linked would write into the operator's own
`~/.pi/agent/auth.json` and overwrite whatever login lives there. The existing
symlink-not-copy reasoning is explicitly about *rotation*, and cross-process
refresh safety is already handled by `AuthStorage`'s lock. **Refresh through the
link is safe. Login through the link is not.** Nothing in the codebase
distinguishes them.

**Rule, absolute:** before any credential write, the server stats
`<project>/.heph/agent/auth.json`; if `is_symlink()`, every write route refuses
`auth_source_linked` with the target path named, and offers
`POST /providers/auth/unlink`, which replaces the symlink with an own file and
**does not read, copy, or modify the target**. Sign-out while linked is refused
by the same rule: unlinking is how you stop borrowing, and `logout()` through a
symlink would sign the operator out of their own terminal.

**TIGHTENING (2026-08-28 review) — `auth_source` is not admitted into any HTTP
body, and the guard was on the wrong end of the link.** A draft listed
`auth_source` among the fields `PUT /providers` writes, in a section whose own
route table says "no route that accepts a filesystem path". `auth_source` **is** a
filesystem path, and it is the path the server symlinks the credential file at
and Pi subsequently rewrites. Worse, the `is_symlink()` guard protects the link's
own path and runs at the wrong moment: the damage is done by the write that
**creates** the link — the route the draft was adding — not by the credential
write the guard blocks. `link_auth_source`'s existing "never clobber a real
credential" check has the same blind spot. Therefore: **`auth_source` stays an
operator-authored line in `providers.json`**, `GET /providers` reports it, and
`PUT /providers/specs` refuses a body carrying it.

**RESOLVED — APPROVED 2026-08-28. Stage 10C, Gate G10C.** This paragraph
previously read **OPEN — MAINTAINER SIGN-OFF REQUIRED** and recorded the
argument without answering it, because mission rule 7 is mission-wide and
deciding a mission-rule question by argument inside a spec section is the move
mission rule 1 exists to prevent. The operator answered it, in these words:

> "The server should be able to work locally, the same way that Claude for
> science works."

**The counter-argument is recorded, not deleted**, because it is what shapes the
constraints: rule 7's approval mechanism is *an allowlisted credential
environment prepared by the supervisor* — a terminal act — and a global Pi auth
file is exactly the class of thing G2's session tests prove inert. The ruling
does not overturn that. It draws a line the counter-argument did not have: a
credential the operator **explicitly adopts, by one act, naming the source, with
the adoption recorded on disk** is not an ambient credential, and rule 7 is about
ambient credentials. Rule 7 is unchanged and still binds.

**What is approved.** The server MAY enumerate the operator's existing
credential sources — a Pi `auth.json` outside the project root, an existing
`providers.json`, a local OpenAI-compatible endpoint — and **offer** them.

**The binding constraints, each a refusal the implementation must demonstrate it
cannot violate.** These are the operator's own conditions and none is
negotiable at implementation time:

1. **An offer, never a silent adoption.** Discovery returns a list. Nothing is
   configured, linked, read into a runtime, or written to `providers.json` by
   it. Adoption is **one explicit request naming the discovered source**
   (`POST /providers/adopt`, carrying the server-minted `discovery_id` from the
   offer). No other route adopts as a side effect.
2. **A secret is never echoed to the client, never logged, never in a URL, an
   event, or an artifact.** The offer describes a source by
   `{kind, provider_id, model_ids, source_path}` and by nothing else. The
   operator's ruling permits "a masked hint at most"; that is a **ceiling**, and
   §15.41's **no masked key tail** is stricter and stands unrelaxed (§0.2a).
3. **Loopback only.** `POST /providers/discover` and `POST /providers/adopt`
   carry §23.6's route-level `not_loopback` precondition like every other
   `/providers/**` route. A discovery route reachable off-loopback is a
   home-directory enumeration primitive.
4. **`0600` on anything written.** The `providers.json` adoption record goes
   through `write_private` (§23.14 item 7); an operator-authored file's mode is
   **reported, never changed**.
5. **Mission rule 7 intact.** `credential_allowlist` stays supervisor-prepared
   and is **not web-writable** (§23.6). Discovery adopts **no** ambient
   environment variable.

**What is still forbidden, unchanged by the approval** — each a refusal the
implementation must be able to demonstrate it cannot perform: reading
`~/.pi/agent/auth.json` because it happens to exist **and no one adopted it**;
forwarding `ANTHROPIC_API_KEY` because it happens to be exported; shelling out to
a global `pi login`; widening `BASE_ENV_VARS`; and letting the browser choose
which environment variables are forwarded.

**One draft clause is superseded by the ruling, and it is named rather than
quietly dropped.** The draft's third gate clause was that the offer performs
**no read of the discovered file before acceptance**. The operator's decision
directs the opposite and says why: *"enumerate what exists, describe it WITHOUT
its secret (kind, provider id, model ids, source path…)"* — an offer that has
read nothing cannot say what provider or which models, and is not an offer. So
the clause is **narrowed, not struck**: the offer may read a discovered file's
**non-secret** fields, and the secret material is never read into a response,
a log, an event, or an artifact. What the draft was protecting — that nothing
happens to a credential you did not choose — is carried by constraint 1
instead, which is where it belongs.

**The distinguishing test is mechanical and G10C asserts it: after any sign-in,
`providers.json` must contain a record of every credential source in use. If a
source works and no file names it, rule 7 has been broken.** Its negative half
matters as much: a discovered-but-**unadopted** login behaves **identically** to
no login at all — the session routes to `agent_unavailable`, byte for byte.

### 23.6 Routes, and the one field that must never cross the wire

Every route is `/api/v1/…`, bearer-authenticated exactly as every other route. No
exemptions, no unauthenticated callback. **Precondition, checked at the route and
not inherited:** every `/providers/**` route refuses `not_loopback` unless the
serve's bound host is a loopback literal. §15.6 already says the serve is
loopback-only; §23 re-checks it at the route anyway, on the §2.6 pattern — a
refusal a future configuration change could quietly contradict is worse than no
refusal, because a reader stops looking.

**Reads (no key):** `GET /providers`, `GET /providers/catalog`,
`GET /providers/{id}/auth/status` — **metadata only** (§23.8).

**Config mutation — key required:** `PUT /providers/specs` (§2.3's first table),
under the same non-tool ledger extension `POST /project/config/dfm` and
`POST /git/tag` already need, with the same key space.

**BLOCKING FINDING, folded in — `credential_allowlist` is not web-writable, and
this is the refusal without which the whole section is an exfiltration
primitive.** *(2026-08-28 review.)* A draft made `providers.json` browser-writable
in one route whose body carried `credential_allowlist` **and** the provider specs
(`baseUrl`, `credential`). Those two fields **compose**: allowlist a variable,
point a spec's `baseUrl` at a collector, and every subsequent turn ships it —
an arbitrary-environment-variable-to-arbitrary-host primitive, driven by a bearer
token §23.13's own threat model concedes any page-script compromise holds. §23.5
lists exactly this by name as something the implementation must demonstrate it
cannot perform — *"forwarding `ANTHROPIC_API_KEY` because it happens to be
exported"*, *"letting the browser choose which environment variables are
forwarded"* — and the draft then built the route that performs it. The negative
test it proposed (export a non-allowlisted variable, sign in, assert the
sidecar's env lacks it) passes trivially and proves nothing, **because the attack
is to put the variable inside the allowlist.**

Therefore: the route is `PUT /providers/specs` and it accepts **specs only**.

**Discovery — Stage 10C, added by the 2026-08-28 credential ruling (§23.5).**
Two routes, neither taking a key, both under the same route-level `not_loopback`
precondition as everything else in this block:

- `POST /providers/discover` — the **offer**. Returns
  `[{discovery_id, kind, provider_id, model_ids[], source_path}]` and nothing
  else. `discovery_id` is **server-minted and opaque**; `source_path` is display
  text. It reads only non-secret fields of what it finds, mutates nothing, and
  runs **only** when called — never on panel mount, never on a timer, never as a
  side effect of another route (§15.41's "no background credential probe" is
  unrelaxed). It is a `POST` despite being a read (§2.3) so that reading the
  operator's home directory can never be something a page issues incidentally.
- `POST /providers/adopt` — the **explicit act**. Body is
  `{discovery_id}` **only**. A body carrying a filesystem path under any key is
  refused `path_not_web_writable`, and an unknown or expired handle is refused
  `discovery_source_unknown`; both by name, on the `allowlist_not_web_writable`
  pattern. On success the adoption is recorded in `providers.json` through
  `write_private` at `0600` — which is what makes §23.5's distinguishing test
  (*if a source works and no file names it, rule 7 has been broken*) mechanical
  rather than aspirational.

**Why the handle and not the path.** The offer already told the operator the
path, so a path in the adopt body would add no information the operator lacks —
it would only add a **client-chosen** path to a credential route, which is the
one shape §23.5 forbids by name. The handle is the same discipline
`PUT /providers/specs` uses on `auth_source`: the server keeps authority over
which file it touches.
`credential_allowlist` and `auth_source` are read-only projections; a body
carrying either is refused `allowlist_not_web_writable` **by name**. A spec whose
`credential` names a variable not already in the on-disk allowlist is refused
`credential_not_allowlisted` — the existing runtime code, unchanged. And the
negative test becomes **"the web path cannot add a name to the allowlist"**,
which is the property mission rule 7 actually needs (§23.14 item 11).

**Credential mutations — key not required, and sending one is ignored:**
`POST /providers/attach` (§23.0); `.../auth/key` (a repeat with the *same* key
sets the same credential; a repeat with a *different* key is a deliberate
rotation, and a byte-for-byte replay that swallowed it would be a silent security
failure — the same shape as `prompt`); `.../auth/begin` (at most one flow per
provider; a second refuses `login_already_in_progress` — flow identity, not key
identity, is the guard); `.../auth/complete` (governed by `state` verification,
which is stronger and already exists; a second mechanism over it is the
duplication rule 6 forbids); `.../auth/cancel`, `.../auth/signout`,
`/providers/auth/unlink` (all idempotent by construction).

**Error mapping (extends §2.4).** A pending flow and a backoff request are
**200** with a discriminated status, not errors. 400 for
`credential_scope_required`, `authorization_input_malformed`,
`endpoint_not_loopback`, `egress_not_acknowledged`, `allowlist_not_web_writable`;
403 `not_loopback`; 404 `provider_unknown` / `model_unknown`; 409
`auth_source_linked`, `login_already_in_progress`, `runs_in_flight`,
`authorization_expired`, `authorization_state_mismatch`; 422
`unsupported_auth_type` with the flows the provider *does* offer; 502
`provider_unreachable` naming the host and **never** the body; 503
`agent_unavailable` **only on the routes of §23.0's third row**.

**A provider's token-endpoint response body never crosses the API — and the
mechanism is named, because a draft named one that cannot see the channel.**
*(2026-08-28 review.)* The draft promised that Pi's raw-body interpolation "is
caught at the bridge boundary and reduced to a code plus an HTTP status before it
reaches a client, a log, or a `stderr_tail`". The bridge boundary is the framed
JSON-RPC channel; **the sidecar's stderr is a second, independent pipe** that the
supervisor drains verbatim into a retained tail the bench harness archives.
Nothing done to a JSON-RPC error frame can reduce what Pi wrote to
`console.error`. The reduction therefore happens **where the bytes are**, in both
places: Pi's OAuth calls are wrapped in the sidecar so a token-endpoint failure is
re-raised as `{code, http_status}` **before any logging**, and `_drain_stderr`
gains a redaction pass at the append point, which is the one place every sidecar
line passes through.

### 23.7 Applying a credential — attach or restart, and the deadlock it must not create

`runtime.configure` runs once per sidecar process. **DECISION: a credential
change attaches a runtime if there is none, and otherwise restarts the sidecar**
via `Supervisor.restart(reason="credentials")`, with the spawn hook replaying the
new configure. *Rejected:* making `configure` idempotently re-runnable — a second
configure path that must stay behaviourally identical to the first forever, when
the restart path already exists and is already exercised. §23.0's attach
capability is what makes the first half of that sentence possible; an earlier
draft said only "restart" and was therefore inoperable in the zero-config case.

**The cost is real and is surfaced, not swallowed: a restart kills every
in-flight run in every session.** `auth/key` and `signout` refuse
`409 runs_in_flight` with the run ids listed unless the body carries
`confirm: true`, and the dialog names the count. **A credential change is not a
hot swap and the UI never implies it is.**

**The deadlock, and the tightening that resolves it.** `createModelRuntime`
throws on the first provider that fails verification, so a
declared-but-unauthenticated provider takes down the **entire** runtime: no
sidecar, therefore no bridge, therefore no way to perform the login that would
fix it. The operator can only reach a working state by hand-editing a file, which
is the state complaint 4 is about.

**TIGHTENING / NEW WORK: provider verification becomes fail-closed *per
provider*, not per runtime.** Each failure is recorded as
`{provider_id, code, message}` and the runtime comes up with the providers that
verified; `configure`'s result gains `providers: [{id, available,
unavailable_reason?}]`; a `session.create` naming an unavailable provider refuses
with that provider's own code.

**The property being preserved is named, because this looks like a weakening and
is not.** The existing behaviour's value is that a `pi_native` provider *"simply
fails configuration — it can never fall back to an ambient login"*. That is a
statement about **substitution**, and substitution remains impossible: an
unavailable provider is never silently replaced, never falls back, and cannot
serve a turn. What changes is only that its failure no longer takes its
neighbours and the login path down with it. **Failing closed per provider is
strictly stronger than failing closed per runtime**, because the per-runtime
version's practical effect is that operators delete providers from a config file
to get unstuck.

### 23.8 Showing signed-in state without showing the secret

`ProvidersPanel` renders one row per declared provider, on **two axes never
collapsed into one.**

**Axis 1 — source (closed):** `none` · `env` (an allowlisted variable present at
start) · `serve` (memory, this serve only) · `project` (persisted in the
app-owned `auth.json`) · `linked` (the Pi `auth.json` this project symlinks —
**not ours to write**). It answers *what would I have to change to change this?*

**Axis 2 — health (closed):** `unused` · `accepted` · `rejected` · `expired` ·
`unreachable` · `rate_limited`. It answers *does it work?*

**DECISION: health is *last observed*, never *current*, and there is no
background probe.** The panel renders "accepted 14:32", never "connected".
*Rejected:* a validity ping on panel load or a periodic keepalive — an unsolicited
outbound request from a local tool the operator did not ask to make one, burning
provider rate limit to answer a question the next real turn answers for free, and
a green dot meaning "valid 90 seconds ago" is a claim the design cannot keep.
`<Fact>` carries `last_observed_at` as its source, so the staleness is on screen
rather than in a footnote.

**DECISION: no masked key tail. Not four characters, not two.** *Rejected:*
`sk-…AB12` so an operator with several keys can tell which is which — a tail of a
key with known structure is meaningful material to anything that reads a
screenshot or a screen-share, and the question it answers is already answered by
the provider id and the source state, which are not secret at all. **A read side
that returns no credential material at all** is a property worth more than the
convenience, and §23.13 shows exactly what it buys. Pi's own contract points the
same way: its read side returns `CredentialInfo`, never `Credential`.

### 23.9 Sign-out and rotation

Sign-out removes the credential from `auth.json` under Pi's lock, drops a
`serve`-scoped key from the configure map, and restarts the sidecar. Three
properties: **it does not delete the provider spec** — the row stays, in state
`none`, because a provider that vanishes when you sign out reads as a deletion
the operator did not perform and leaves them unable to sign back in without
re-typing an endpoint; **sign-out while `linked` is refused** (unlink first); and
**it cannot fail halfway**, because Pi's `modify` is a serialized
read-modify-write under a lock and a throwing operation propagates **without
writing**.

**Rotation has no verb.** Rotating an API key is signing in over an existing one,
and the response names the state it replaced (`{"replaced":"project"}`), so a
rotation that landed in a different scope than intended is visible in the
response rather than discovered three weeks later. **OAuth rotation is not
ours:** a second refresh implementation racing Pi's over one file is the failure
mode `link_auth_source`'s copy-versus-symlink reasoning already identified, and
it does not become safe because we wrote it.

### 23.10 A credential revoked under a running session

The next model request returns 401 and Pi surfaces `ModelsError` code `auth`.
**The run fails. It is not retried, not paused, and not resumed.** It terminates
through the ordinary error path with the reason in the transcript — **no new
event kind**. The provider's health axis flips to `rejected` and the panel shows
it; that is the only notification the design has, and it is enough, because the
operator is looking at a failed turn. **Tool calls already dispatched are not
rolled back:** if the agent wrote a part before the credential died, the part is
written and the build is real, and the transcript is the record — stated because
the alternative, a partial turn presented as if it had not happened, is a
provenance lie, and this document's centre of gravity is provenance.

**DECISION: no mid-run re-authentication.** *Rejected:* suspending the run like
an `ask_user` and resuming after a fresh login — it needs a new event kind; a
suspended run holds one of the 16 admission slots for as long as the operator
takes to find their password; and a turn whose first half ran against one
credential and whose second half runs against another is a provenance object this
workspace cannot honestly describe.

**"Bad key" and "revoked key" are the same refusal and the workspace does not
pretend otherwise.** Both are a 401, so there is one reason —
`credential_rejected` — carrying the provider's own status code. Inventing
`credential_revoked` would be a distinction the wire does not support, and a
vocabulary that names a state it cannot observe is worse than a coarse one that
can.

### 23.11 Refusal vocabulary (closed)

Existing engine/runtime codes reused: `agent_unavailable`, `provider_unknown`,
`model_unknown`, `credential_not_allowlisted`, `provider_not_authenticated` (now
**per provider**), `authorization_pending` and `slow_down` (both **200**),
`authorization_state_mismatch`, `authorization_input_malformed`.

Introduced here and used nowhere else: `not_loopback`, `auth_source_linked`,
`runs_in_flight`, `login_already_in_progress`, `unsupported_auth_type`,
`credential_scope_required`, `endpoint_not_loopback`, `egress_not_acknowledged`,
`allowlist_not_web_writable`, `authorization_expired`, `credential_rejected`,
`credential_expired`, `provider_unreachable`, `provider_rate_limited` (distinct
from §2.4's `busy`, which is Hephaestus's own admission ceiling).

Added by the 2026-08-28 credential ruling (Stage 10C, §23.5, §23.6), and the
vocabulary stays closed: `path_not_web_writable` — an adopt body carried a
filesystem path — and `discovery_source_unknown` — the `discovery_id` names no
current offer. Neither degrades to `invalid_params`.

Every one is a **named** refusal in the sense this codebase already uses: a
closed set, tested by enumeration, never degraded to a generic 400 and never
collapsed into a neighbour.

### 23.12 Exclusions this section adds

Recorded in §15 as refusal 41, stated there in full. §15.34 is **struck** by this
section.

### 23.13 Threat model

The server binds loopback and gates every route on a per-serve bearer token in a
`0600` file. §23 raises that token's value from *read and edit this project* to
*attach or replace the model provider*, and that elevation is the whole of what
this section adds to the attack surface. Five classes.

**A process running as the operator's own uid** gains everything, and the design
does nothing about it and does not pretend to: `serve.token`, `auth.json` and
`providers.json` are all `0600` and all readable by that uid, and the serving
process's heap holds `serve`-scoped keys. Same-uid isolation is not a property
`0600` provides. §23's storage rules defend against *other local users*, not
against the operator's own compromised process.

**Another local user** is blocked from the files but **not** from the socket: a
loopback listener has no uid check, so the bearer is the only gate and the attack
reduces to guessing 32 bytes of entropy. §23 adds one concrete hardening here —
`providers.json` is now written `0600`, where a hand-authored one may be
world-readable, denying them the endpoint list and credential-variable names that
make a targeted attack cheaper.

**Anything reaching loopback without the token** gets `401` on every route
including `/providers/**`, which takes no exemption and exposes no callback. It
learns a port is open. This is the class the no-listener decision is really
about: an OAuth callback listener would have been an unauthenticated inbound
route beside a closed, bearer-gated table.

**Script inside the workspace page** — an XSS, a compromised dependency — holds
the bearer, so it can call every route the operator can. **What it cannot do is
steal the credential that is already there:** no route returns an access token, a
refresh token, or an API key — not masked, not truncated, not four characters.
That is the concrete purchase of §23.8's no-masked-tail decision and §23.2's "the
store is Pi's": a total compromise of the page is an escalation to *use* and to
*replace*, never to *exfiltrate*. The residual — that a replaced endpoint is an
exfiltration path for future turns — is answered by §23.6's allowlist refusal
(which removes the environment-variable half outright) and by durable visibility
for the rest: `egress_acknowledged` is a record in a file, printed at start-up and
listed permanently in the panel. **A silent redirection is not available; a loud
one is.**

**An attacker who can write the filesystem** wins outright and the design says
so. They can point `auth_source` at a file they control or edit a `baseUrl`, and
the next serve will use it. Nothing in a local tool defends against an attacker
with write access to its configuration; the only answer is that both facts are
printed at start-up and rendered in the panel, which is worth something to a
person who looks and nothing to a person who does not.

**Network exposure is a capability, not a leak, and is named as one.** Kind
`local` is constrained to loopback literals and has no egress at all. Kind
`openai_compatible` against a remote host has full egress by construction — every
prompt sends geometry, script source and transcript — and is reachable only
through a typed acknowledgement recorded on disk. The credential itself never
crosses the network except to the provider, by Pi's own code, and never crosses
the local API boundary in either direction after the moment it is set.

### 23.14 Named new work (this section's own list)

Numbered inside §23 because its first item is a **capability the product does not
have**, and burying that in §19's sequence would misrepresent the section's size.

1. **`WorkspaceRuntime.attach_agent()`** — construct and start a `BridgeRuntime`
   *after* serve start, and detach/replace one, with `_attach_agent`'s body
   refactored so serve-time and post-hoc attach are **one code path**. Exposed as
   `POST /providers/attach`. **Without this the section cannot be used in the
   only state it exists to fix** (§23.0).
2. **`/api/v1/providers/**`** — the routes of §23.6, their §2.4 error mapping, the
   route-level `not_loopback` precondition, and the dependency split that keeps
   `GET /providers` and `PUT /providers/specs` serviceable with **no** sidecar.
3. **The bridge credential methods** over `ModelRuntime`'s existing
   `login`/`logout`/`setRuntimeApiKey`/`removeRuntimeApiKey`/`listCredentials`/
   `getProviderAuthStatus`. **Pi remains the single authority**; nothing
   re-implements storage, PKCE, token exchange, or refresh (rule 6).
4. **A browser auth-interaction adapter in the sidecar** — turning Pi's
   notify/prompt callbacks into request/response state a status route can read,
   **without** touching the `/events` vocabulary, plus the sidecar-side
   device-code poll loop.
5. **Per-provider fail-closed verification** (§23.7), with the **no-substitution
   property asserted by test, not by reading**.
6. **Attach-or-restart wiring**, the `runs_in_flight` refusal, and `confirm`.
7. **The `providers.json` spec-only writer** through `write_private` at `0600`,
   with `egress_acknowledged`, and the rule that an operator-authored file's mode
   is **reported, never changed**.
8. **`PUT /providers/specs` in the non-tool ledger extension** §19.7 already
   requires for `POST /project/config/dfm` and `POST /git/tag`.
9. **The symlink guard** — `is_symlink()` before every credential write,
   `auth_source_linked` with the target named, and `POST /providers/auth/unlink`.
   **This closes a real gap: `link_auth_source` protects link creation and
   nothing protects writes through the link** (§23.5).
10. **Token-endpoint body containment in both channels** — the sidecar wrapper
    that re-raises OAuth failures as `{code, http_status}` before any logging,
    **and** a redaction pass in `_drain_stderr` at the append point (§23.6).
11. **The mission-rule-7 negative test, aimed at the real property:** *the web
    path cannot add a name to `credential_allowlist`.* A body carrying it is
    refused `allowlist_not_web_writable`; a spec naming a variable outside the
    on-disk allowlist is refused `credential_not_allowlisted`. **Plus** the
    existing G2-style assertion, driven through HTTP, that a variable outside the
    allowlist never reaches the sidecar's environment.
12. **The credential-leak test, extended to the channel the claim is about.** The
    fixture signs in with a sentinel key literal and a pytest greps the opstore,
    the archived event goldens, `sidecar_evidence()`'s `stderr_tail`, and the
    bench evidence bundle. **And** a scripted OAuth fixture whose token endpoint
    returns a body containing a sentinel, so the OAuth channel — where the Python
    side never sees the value and no key-shaped sentinel could be planted — is
    exercised too (§23.6).
13. **A `no-listener` assertion.** After a full OAuth flow, the process holds
    exactly **one** listening socket. Enforced rather than declared, on the §2.6
    by-enumeration pattern.
14. **`ProvidersPanel` and `SignInDialog`**, built on §3.4's system layer, with
    two-axis status rendering, the password-field discipline, the "your provider
    will show this as Pi" disclosure, the egress-host acknowledgement, and the
    empty-state → create-session → prompt path (§23.0).
15. **Closed copy vocabulary in `copy.ts`** for both status axes, every refusal
    reason, and the scope choice — no reason string constructed at a call site.
16. ~~**The gate clause shape** for the amending stage~~ — **LANDED 2026-08-28
    as Gate G10B**, verbatim from `docs/workspace-plan.md` §9: serve a project
    with **no** `providers.json`; assert the panel renders `agent_unavailable`
    **by name**; write specs; **attach**; configure a provider against a scripted
    `FakeModel`; assert a session then runs and streams; assert sign-out returns
    the panel to `none` and the session routes to `agent_unavailable`; plus items
    11, 12 and 13. **The zero-config path is asserted end to end, because that is
    the clause that proves the complaint is answered.** `mission_plan.md` is now
    the binding text; this entry is a pointer, not a second gate.

**Added 2026-08-28 by the credential ruling — Stage 10C, Gate G10C (§23.5).**
Numbered on, because §19's rule that a closed list may not silently acquire
members applies to this list too.

17. **`POST /providers/discover` and `POST /providers/adopt`** (§23.6) — the
    offer and the one explicit act, with the opaque server-minted
    `discovery_id`, the `{kind, provider_id, model_ids, source_path}` projection
    that reads **only** non-secret fields, the `providers.json` adoption record
    through `write_private` at `0600`, and the two new named refusals
    `path_not_web_writable` and `discovery_source_unknown`. Enumerates a Pi
    `auth.json` outside the project root, an existing `providers.json`, and a
    local OpenAI-compatible endpoint.
18. **The Stage 10C negative tests, which are the whole of what the ruling's
    constraints buy.** Four, each aimed at a property rather than a message:
    a discovered-but-**unadopted** source leaves a session routing to
    `agent_unavailable` **byte-identically** to a run with nothing discovered;
    no credential path outside `<project>/.heph` is read unless
    `providers.json` names it or the adoption request named it; discovery fires
    on **no** code path but its own route — not on mount, not on a timer, not as
    a side effect; and item 12's sentinel grep is **extended to the discovered
    file's secret**, which appears nowhere in the opstore, the archived event
    goldens, `stderr_tail`, or the bench bundle. Item 11's rule-7 assertion is
    unchanged and still binds: the web path cannot add a name to
    `credential_allowlist`, and discovery adopts no ambient environment
    variable.
19. **The `ProvidersPanel` discovery affordance** (§23.8, §23.5) — the offer
    list rendered with its four fields and **no** masked tail (§15.41), and an
    adopt control that is unmistakably an act: nothing in the panel adopts on
    render, on hover, or on selection.
