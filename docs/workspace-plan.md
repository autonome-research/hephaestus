<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# Workspace plan — answering the 2026-08-28 product review

**Status: APPROVED 2026-08-28. Still a plan, not a gate.** `mission_plan.md`
remains the only binding text. The amendment this document proposed in §9 was
approved by the operator on 2026-08-28 and **has landed** in `mission_plan.md`
as §"Stage 10 — Workspace egress and provider attachment (amendment 2026-08-28,
maintainer-directed)", carrying **G10A** and **G10B** verbatim from §9 below,
plus **G10C** for the credential ruling of the same day (§9a). `INTERFACE.md` is
the normative spec for everything below; every item names the section that
governs it. Nothing here weakens or rewords G4 or G5, and the amendment edits
neither.

**The amendment boundary of §3 is CROSSED.** Items 7–10 are buildable. Read §3
for what the boundary was and why it existed; it is kept rather than deleted
because a boundary that vanishes on being crossed teaches nobody why it was
drawn. Ordering within Stage 10 is now a dependency question, not a permission
question: 10A → 10B → 10C, strictly.

## 0. What was reported, and what the review concluded

The product owner reviewed a running workspace on the public clean-room fixture
and reported four things, verbatim:

1. *"there is an agent panel but no way for me to start chatting with an agent
   about the displayed material"*
2. *"there is no export button or export types to take out of heph and put into a
   different cad software"*
3. *"whatever design that was in the UI you put up looked pretty bad"*
4. *"there should be a way to sign in with your sub or api to chat against the
   objects or blank canvas"*

All four were consequences of deliberate spec decisions. The review's job was
therefore not *did we build the spec* — we did — but *was the spec wrong*. The
rulings are in `INTERFACE.md` §0.2 and are summarised here only as the input to
the ordering below:

| Complaint | Ruling | Section | Stage |
|---|---|---|---|
| 1 chat | **Spec was wrong, and by miscitation** — the code cited §9, and §9 says nothing about prompting. `Composer` was already on the Stage-4/5 panel inventory. | §7A | **Stage 4** (quick-edit half already gated by G5.16) |
| 2 export | Mechanism decision right; **product decision was an unanswered deferral**, now answered. Mechanism argument turned out weaker than claimed. | §22 | **Stage 10A**, G10A |
| 3 design | **Row was wrong about what it bought.** CSS Modules is a delivery mechanism, not a design system. Every *dependency* rejection survives. | §3, §4.7 | **Stage 4** |
| 4 sign-in | §2.2's sentence answered a different question than it was read as answering. Narrowed, not withdrawn. | §23 | **Stage 10B**, G10B; discovery **Stage 10C**, G10C |

## 1. The ordering, in one table

Ordered by operator value **subject to dependency**. "Size" is honest calendar
effort for one engineer who knows this codebase: **h** = hours, **d** = days,
**w** = a week or more.

| # | Item | § | Stage | Size | Why here |
|---|---|---|---|---|---|
| 1 | Answer `ask_user` from the browser | §7A.7 | 4 | **h** | Deletes one hardcoded `disabled`. The route, registry and widget all exist. Highest value per hour in the whole plan. |
| 2 | Bind artifact kind to blob | §2.6, §19.24 | 4 | **h–d** | Security correction to a shipped route, and a **hard prerequisite** of §22. Independent of everything else. |
| 3 | Design system layer + the four checks | §3.4–§3.14 | 4 | **w** | Complaint 3, and every surface built after it inherits the fix. Must precede 4 and 6 or they are built twice. |
| 4 | Composer, blank canvas, read-refresh | §7A | 4 | **d–w** | Complaint 1. The largest single answer to the review. |
| 5 | Request text bound per run | §19.23 | 4 | **d** | Makes §7A.4's invariant true rather than conditional, and buys back the concurrency the composer must otherwise refuse. |
| 6 | Viewport display authorship | §3.11 | 4 | **d** | Complaint 3's other half — the part is currently the dimmest object on screen. Gated on G4.5 threshold re-derivation. |
| — | **Amendment approval boundary — CROSSED 2026-08-28 (§3)** | §9 below | — | — | Was: nothing past this line is buildable until the maintainer approves the new stage. The stage is approved; what remains below the line is dependency order, not permission. |
| 7 | Attach a runtime to a running serve | §23.0, §23.14.1 | **10B** | **d** | The capability without which sign-in cannot be used in the state it exists to fix. Also useful on its own. |
| 8 | Provider sign-in surface | §23 | **10B** | **w+** | Complaint 4. Largest item in the plan. |
| 8a | Credential discovery: offer and adopt | §23.5, §23.14.17–19 | **10C** | **d** | The 2026-08-28 credential ruling (§9a). Additive after item 8; strictly after it. |
| 9 | Export: routes, panel, download | §22 | **10A** | **w** | Complaint 2. Blocked on item 2. |
| 10 | `heph export list` / `unpin`, `admission_guard` wiring | §19.40 | **10A** | **d** | Makes §22's "unpin it from the command line" name something that exists. |

## 2. Stage 4 items, in detail

### Item 1 — Answering `ask_user` from the browser · §7A.7 · hours

**Machinery it needs:** none that does not exist. `POST /sessions/{id}/answer`
is built; `PendingQuestions.answer` is idempotent on the question id with
first-answer-wins and an `accepted` flag; §7.3 already specifies the post;
`ask.ts` already reserves the `"self"` value it can never currently emit. The
work is deleting the hardcoded `disabled` at `AskUserWidget.tsx`:101, deriving
the widget's affordance from the question's own `options` / `allow_free_text` /
`multi`, and submitting the **server-sent `label`**.

**Stage:** 4. G4's deliverable text says `ask_user widgets`, and a widget that
cannot be answered is a rendering of a question.

**Acceptance evidence:** e2e — `data-answered-by="self"` on the answering widget,
`"other"` on a second attached client, `accepted:false` for the loser; a
`404 unknown_question` renders `data-ask-state="abandoned"` in place.

**Carries one independent defect fix (§19.29):** `agent_bridge/cli.py`:274-276
flattens options with `str(o)`, so an object option's **Python dict repr**
becomes the selection the model receives. Two surfaces answering one question
currently hand the model two different values. Fix the CLI; do not build the web
widget to match it.

### Item 2 — Bind artifact kind to blob · §2.6, §19.24 · hours to a day

**What is wrong.** `artifact_kind(ref)` reads the kind out of the
**caller-supplied string** and `_blob()` resolves by `blob_hash_of_ref(ref)`.
Nothing checks the ref's kind segment against the stored blob, and export
outputs live in the same blob store. So
`GET /artifacts/artifact:build:sha256:<export blob>/bytes` serves export bytes
**today**; the only thing in the way is that no client knows the hash. The
pytest that submits an `artifact:export:…` ref and asserts a refusal is testing a
*label*, and relabelling is free.

**Machinery:** record the artifact kind alongside the blob at publication; have
`_blob()` verify the ref's kind segment against the stored one; refuse
`artifact_kind_mismatch`. Plus `Content-Disposition: attachment` and
`X-Content-Type-Options: nosniff` on `/artifacts/{ref}/bytes` — that is the route
an artifact SVG can actually be fetched through, and the mitigation was specified
only on the route the attack cannot use.

**Stage:** 4. It is a correction to a route this spec already owns.

**Acceptance evidence:** the existing pytest still passes, **plus** a new one
that relabels an export blob as `artifact:build:…` and asserts the refusal. §22's
gate clause repeats it, because a gate asserting only the `artifact:export:…`
refusal would pass against a route that serves the same bytes under a different
name.

**Do this before item 9.** §22 is the change that publishes the hashes.

### Item 3 — The design system layer · §3.4–§3.14, §4.7 · about a week

**Machinery:** a new `system/` directory under `web/src/` — twelve primitives, a two-layer token file,
seven type roles, an 18-id icon sprite, `useBreakpoint`, `format.ts`. **No
dependency is added.** Every dependency rejection in the original §3 survives
review; what failed was ownership, and ownership is what a dependency cannot
supply.

**Three shipped defects it makes unrepresentable, each independently worth the
work:**

- `ChecksPanel.tsx`:59 puts `data-badge` on the `<li>` while the CSS selects it
  on the `.badge` one level down, so `pass`, `fail` and `error` compute to
  identical colour, border and `::before: none` — **label-only status encoding at
  11px in the panel whose entire job is "did my part pass"**, in a file whose own
  token header claims the opposite. `DfmPanel.tsx`:132 does it correctly two
  files over.
- `Shell.module.css` collapses the stream column to 44px by media query while
  `Shell.tsx`'s `useState(true)` decides whether the panel renders. Between 1024
  and 1279px they disagree and the panel shreds into a one-word-per-line ribbon.
  1280×800 is the default MacBook Air resolution.
- `data-rail` is set by nothing, so below 1024px the rail is a 280px overlay over
  a third of the stage with no scrim, no close control, and **no dismissal at
  all**.

**Stage:** 4. Tightenings under G4's shell and panel deliverables. It adds
checks, not clauses.

**Acceptance evidence:** four static checks (`no-palette-token`, `no-raw-type`,
`system-owns-status`, `token-contrast`); a `Badge` **component test** covering
all six statuses including `not_run`; a new `design-system` spec under `web/e2e/` over what
the fixture actually reaches. **The migration's acceptance criterion is that the
existing e2e needs no selector changes** — all 28 `data-*` selectors are
preserved by the primitives that now own them.

**Sequencing note.** Do this **before** items 4, 8 and 9, or `Composer`,
`ProvidersPanel`, `SignInDialog` and `ExportPanel` get built on the old
arrangement and complaint 3 is answered for every surface except the three the
operator asked for.

### Item 4 — The composer · §7A · days to a week

**Machinery.** Four client API functions in `web/src/api/sessions.ts` (read-only
by construction today); `compose_context` server-side; `POST /context/preview`;
one optional `context` field threaded through three layers
(`session.prompt` → `BridgeRuntime.prompt` → the HTTP body); two `POST /sessions`
validations; the `run_in_flight` guard; the structured `agent_unavailable` cause;
and the read-refresh boundary.

**The three decisions that carry the section:**

1. **The client sends references, never facts** (§7A.3). A closed envelope of
   §4.5 tokens and server-minted ids; the block is composed server-side from the
   existing projections; the server verifies every claim against its own state.
2. **The context block never reaches `set_request_text`** (§7A.4). Prepending it
   to the prompt would put the build's own extents into "the request", and
   `VALIDATION.md` §4's `prompt_number_diff` would match every one of them
   **against itself** — turning the rung that catches a design not meeting its
   brief into a measurement of the workspace's own context block.
3. **The read-refresh boundary is normative** (§7A.11). Without it the
   blank-canvas flow ends with a transcript full of successful tool calls and a
   rail that still says the project has no parts. Invalidation is a **refetch of
   the server projection**, never a client-side merge, and it never moves the
   pin.

**Stage:** 4 for the orchestrator/part composer and the blank-canvas create; the
quick-edit composer is **already gated by G5.16 verbatim** — *"Submitting 'add a
2 mm chamfer to this face' to the quick-edit agent … results in an `edit_part`
diff visible in the transcript"* is a browser submission through a composer.

**Non-negotiable constraint:** **G4.8's e2e fixture must keep starting its
session from the CLI.** That clause is a claim about lease topology; rewriting it
to use the composer would degenerate it into a self-observation. The composer's
coverage is a separate case with a separate fixture.

**Acceptance evidence:** §7A.12's seven cases, of which case 1 ends by asserting
the **new part appears in the tree, is selectable, and renders** — not that the
transcript looked successful.

**Honest limit while item 5 is outstanding:** one live turn per *runtime*, so an
operator cannot ask the orchestrator something while a part session is thinking.
See item 5.

### Item 5 — Bind request text to the run · §19.23 · days

**Why it exists.** `CadOps` holds exactly **one** `_request_text` for the whole
project (`_base.py`:270) — per *runtime*, not per session or per run. A guard of
one live run *per session* does not protect it: two tabs on two different
sessions (the blank-canvas orchestrator and a part session — the exact pair the
composer sells) can prompt concurrently, and the second `set_request_text`
clobbers the first. Session A's build is then critiqued against session B's
prompt: **a fabricated request diff**, which is precisely what §7A.4 exists to
prevent. Pre-existing machinery; the composer is what makes it reachable.

**Machinery:** thread the request text through `BridgeRuntime.prompt` into a
per-run scope that `_build.py` reads from the active run.

**Acceptance evidence:** a pytest running two prompts on two sessions,
asserting each critique sees its own request. Then the §7A.5 guard narrows from
per-runtime to per-session, and `run_in_flight` keeps its meaning.

**If the interim restriction is judged unacceptable, this item is a prerequisite
of item 4 rather than a follow-on**, and item 4 moves behind it.

### Item 6 — Viewport display authorship · §3.11 · days

The client currently holds **no display opinion**: the part looks like whatever
`baseColorFactor` the server's GLB carries, on a clear colour that **is** the
app's darkest chrome surface — 1.10:1, the dimmest object in frame, in a CAD
workspace whose first design principle is that the measurement outranks the
chrome. Ground colour, material override with a ≥4.5:1 floor, colour space, tone
mapping, an edge pass, a grid, an axis triad. The edge pass is ~15 lines and is
the single highest-value CAD viewport affordance in the list.

**Gated on:** re-deriving G4.5's 0.10 / 0.01 delta thresholds against the new
material **before** it lands. §21.10 already records that they were chosen rather
than measured. G4.7 is untouched — the section render is server pixels.

## 3. The amendment boundary — CROSSED 2026-08-28

**As drafted:** *"Items 7–10 are not buildable until `mission_plan.md` carries
the amendment in §9 below. Both §22 and §23 are marked DRAFT throughout
`INTERFACE.md` for that reason. Neither has a gate clause, so neither has a CI
job, so neither can be completed — a PR touching `/exports/**` or
`/providers/**` before the amendment lands is out of scope on its face."*

**As of 2026-08-28 the amendment landed.** `mission_plan.md` §"Stage 10" carries
G10A, G10B and G10C; the DRAFT markings in `INTERFACE.md` §22 and §23 are struck
and both sections are normative beneath those gates; each now has a gate clause,
so each has a CI job, so each can be completed. The out-of-scope-on-its-face rule
for `/exports/**` and `/providers/**` PRs is **retired** — those are ordinary
stage work now, reviewed against their gate like anything else.

**Kept, because it survived the crossing:** items 7–10 are still ordered by
dependency. Item 9 (export) is blocked on item 2; item 8 (sign-in) is blocked on
item 7 (attach); discovery is blocked on item 8. A permission that arrived does
not dissolve a prerequisite.

## 4. Item 7 — Attach an agent runtime to a running serve · §23.0 · days

This is the finding that changed the sign-in proposal most. A project with no
`providers.json` has **no `BridgeRuntime`, no `Supervisor`, and no sidecar
process at all** — `_attach_agent` returns `None` and `attach_sessions` is called
from one place, once, during `serve`. Every credential route is a relay to the
sidecar. The sign-in surface was therefore unreachable **in exactly the
zero-config case it exists to fix**, and its own gate clause ("serve with no
`providers.json` … configure a provider through the UI") was unsatisfiable.

**Machinery:** refactor `_attach_agent`'s body so serve-time and post-hoc attach
are one code path; expose `WorkspaceRuntime.attach_agent()`; add
`POST /providers/attach`. Split the route block by dependency: `GET /providers`
and `PUT /providers/specs` must be serviceable **with no sidecar** (they read and
write a file); only the credential routes may precondition on a runtime.

**Useful on its own** even if item 8 never ships: it turns "restart your server"
into an in-product action.

## 5. Item 8 — Provider sign-in · §23 · a week or more

**Largest item in the plan, and the one with an open governance question.**

**Machinery:** eleven routes; the bridge credential methods over Pi's existing
`login`/`logout`/`setRuntimeApiKey`/`listCredentials`; a browser auth-interaction
adapter in the sidecar (device-code poll included) that touches **no** event
vocabulary; per-provider fail-closed verification; attach-or-restart wiring; the
spec-only `providers.json` writer; the symlink guard; and two panels.

**Three decisions that make it safe rather than merely present:**

1. **Hephaestus is not a secret store; Pi is.** Nothing re-implements storage,
   PKCE, token exchange or refresh. The Python side sees four non-secret values
   on the way out and `{state, type, expires_at}` on the way back, and never sees
   an authorization code, access token or refresh token at all.
2. **`credential_allowlist` is not web-writable.** This is the refusal without
   which the section is an exfiltration primitive: a route carrying both the
   allowlist and a spec's `baseUrl` composes into
   *arbitrary-environment-variable → arbitrary-host*, driven by a bearer token
   the threat model concedes any page-script compromise holds. The route is
   `PUT /providers/specs`, it takes specs only, and a body carrying the allowlist
   or `auth_source` is refused **by name**.
3. **No loopback callback listener, ever.** The redirect ports are fixed by the
   provider's registered client, so a real CLI login already running makes the
   flow fail with a bind error the operator cannot act on; and a second listening
   socket would be **unauthenticated**, beside a route table whose whole
   discipline is that it is closed and gated. The cost is stated: the
   callback-only subscription flow is a copy-paste and will look unpolished next
   to a one-click login.

**RULED 2026-08-28 — was OPEN, needing the maintainer rather than a spec
argument (§23.5).** Whether the panel may **discover** `~/.pi/agent/auth.json`
and offer it as a credential source is a **mission rule 7** question. Rule 7 is
mission-wide and its approval mechanism is a supervisor-prepared allowlist — a
terminal act, not a browser click — and a global Pi auth file is exactly the
class of thing G2's session tests currently prove inert. The argument is kept
because it is what shaped the constraints. **The operator approved discovery**
(§9a), and it enters as **item 8a / Stage 10C with its own gate clauses**, which
is the form the open question itself required: no credential path outside
`<project>/.heph` is read unless `providers.json` names it or an adoption request
named it; the offer is an **offer and never a silent adoption**, reading
**non-secret fields only** and never echoing, logging or emitting a secret; and a
discovered-but-**unadopted** login behaves identically to none. Rule 7 is
unchanged: `credential_allowlist` stays supervisor-prepared and not web-writable,
and no ambient environment variable is adopted.

**Acceptance evidence:** the zero-config path end to end (no `providers.json` →
panel names `agent_unavailable` → write specs → attach → configure against a
scripted `FakeModel` → a session runs and streams → sign out returns the panel to
`none`); **the rule-7 negative test aimed at the real property** — *the web path
cannot add a name to the allowlist*; the credential-leak test extended to a
scripted OAuth fixture whose token endpoint returns a sentinel in its body,
because that is the channel the never-echo claim is actually about and no
key-shaped sentinel can be planted there; and a `no-listener` assertion that the
process holds exactly one listening socket after a full OAuth flow.

## 6. Item 9 — Export · §22 · about a week

**Blocked on item 2.** `export_hashes` in a response body and
`GET /parts/{part}/exports` are what turn "nobody knows the hash" into "every
client knows the hash".

**What ships:** all six formats, both layouts, all three document kinds, all
three drawing kinds. No curated subset, because a subset needs a rule and every
available rule is arbitrary. Three keyed POST routes replaying from the existing
`tp_exports` WAL — the only rows in §2.3's first table needing **no** ledger
extension — plus a projection, a narrowly-authorized bytes route, and an
Inspector tab.

**The decision that makes it honest:** `artifact_ref` is required and is always
the workspace pin. With a `null` ref, `_freeze_export_source` resolves
`current_result` **at export time**, so the operator looks at build A, clicks
Export, and receives a STEP of build B. **The exported file must be the geometry
on screen or the workspace is lying with a download.**

**Two corrections the review forced:**

- **The retention argument was underwritten.** A draft argued that heavy
  exporting eventually makes *builds* refuse via `admission_guard()`. That
  function has **zero production callers** — the real consequence is unbounded
  disk growth **with no guard at all**, which is worse than the shape the draft
  defended. And the engine's reason is `protected_quota_exceeded`, not
  `quota_exceeded`, under a rule that says every string is the engine's. §22.6
  now says what is true and leans on the visible export history plus the CLI verb
  of item 10.
- **The download filename is derived, not echoed.** The route serves any blob a
  `COMMITTED` row names, including every export an agent produced with an
  explicit `target`, and `_validate_relative_target` permits `"` and `;` — the
  two characters that structure a `Content-Disposition` parameter list. Filename
  comes from the blob hash and the format extension; the recorded path renders as
  body text.

**Acceptance evidence:** §22.10's clause, including the A/B half (pin A, export,
publish B, re-export from A, same digest) and the relabelled-ref refusal that
proves item 2 landed.

## 7. Item 10 — The CLI verbs the product already promised · §19.40 · days

`tool_schema.md` promises exports are "pinned as a GC root until explicit
`heph export unpin/delete`". `ExportOps.unpin_export` exists and its docstring
names that verb. **There is no `heph export` verb at all**, and grep finds one
caller: a server test. §22 makes the omission materially worse, so it ships with
the fix. Same item: wiring `GcCollector.admission_guard()` into the
artifact-producing paths, which likewise has no production caller.

## 8. What is deliberately not in this plan

Named because unnamed absences are what produced the review in the first place.
Each is in `INTERFACE.md` §15 or §18 with its reason:

- **No part-creation or project-creation affordance.** A part is created by the
  orchestrator agent's `create_part`, reached through the composer from the
  parts-empty state; a project is created by `heph init` at a terminal, because
  `heph serve` opens an **existing** project root (§15.30).
- **No drawing or document viewer** — §22 ships them as downloads and says
  plainly that a PDF the workspace cannot show is a weaker deliverable than a
  STEP (§18.10).
- **No import.** Geometry leaves Hephaestus in this stage; it does not come back
  (§15.37).
- **No light theme** — addable with no component changes once the token file is
  two-layer, and with no gate behind it (§18.9).
- **No kerf override, no `target`, no unpin, and no `DELETE` from the browser**
  (§22.9).
- **No masked key tail, no background credential probe, no mid-run
  re-authentication** (§15.41).

## 9. The `mission_plan.md` amendment — APPROVED 2026-08-28, LANDED

Approving this one block is what unblocked items 7–10. It adds a stage and edits
no existing gate. **It was approved by the operator on 2026-08-28 and is now in
`mission_plan.md` §"Stage 10 — Workspace egress and provider attachment
(amendment 2026-08-28, maintainer-directed)". G10A and G10B are carried there
verbatim from the block below.** The block is retained unaltered as the record of
what was put and approved; `mission_plan.md` is the text that binds, and if the
two ever disagree the gate wins and the disagreement is a defect here.

**One departure from the block, recorded rather than folded in silently:** the
block's closing paragraph carries an open question forward. It is no longer open
— see §9a. `mission_plan.md`'s Stage 10 records the ruling in its place.

> ## Stage 10 — Workspace egress and provider attachment (amendment 2026-08-28, maintainer-directed)
>
> Recorded on the product owner's review of the running Stage 4 workspace. Two
> capabilities the workspace lacks are product decisions rather than UI
> additions, and mission rule 5 requires each to enter by a new gated stage
> rather than by widening G4 or G5. G4 and G5 are unedited. Normative spec:
> `INTERFACE.md` §22 and §23. Stage 10 lands in two gated sub-stages, strictly
> ordered.
>
> - **10A — Egress** (`INTERFACE.md` §22): `export_part`, `generate_drawing` and
>   `generate_doc` as keyed REST mutations replaying from the existing
>   `tp_exports` WAL; a `tp_exports` projection; a blob-addressed download route
>   authorized by a `COMMITTED` row; and an `ExportPanel` bound to the workspace
>   pin. Prerequisite, landing in Stage 4: the artifact kind is bound to the
>   blob, so `/artifacts/{ref}/bytes`'s enumeration constrains reachability and
>   not only labelling.
>
>   **Gate G10A** (Tier 2): `pnpm test:e2e` exits 0 — Playwright pins artifact A,
>   exports STEP from the pin, and asserts the downloaded bytes' sha-256 equals
>   the `export_hashes` entry the route returned; publishes build B for the same
>   part; re-exports from the still-pinned A and asserts the same digest, and
>   that a `null`-ref export is not reachable from the client. A DXF export of
>   the same pin asserts `kerf.source == "dfm"` and `applied_mm == 0.2` from the
>   process pack. `GET /artifacts/{ref}/bytes` refuses the export's ref **and**
>   refuses a `build`-relabelled ref naming the same blob. An export with no
>   `Idempotency-Key` is `400 idempotency_key_required` with no file created; the
>   same key twice yields one file and `"replayed": true`; the same key with a
>   changed format yields `key_payload_mismatch`. `heph build` on the fixture,
>   then a `gc.collect()`, leaves the exported blob and its source build blob
>   both reachable. `heph export list` and `heph export unpin BLOB` exist and are
>   exercised.
>
> - **10B — Provider attachment** (`INTERFACE.md` §23): an agent runtime
>   attachable to a running serve; provider specs writable from the workspace
>   **without** the credential allowlist or `auth_source`; API-key and
>   subscription-OAuth sign-in relayed to Pi, which remains the sole credential
>   store; per-provider fail-closed verification; and a `ProvidersPanel` whose
>   source and health axes are never collapsed.
>
>   **Gate G10B** (Tier 2 + Tier 1): `pnpm test:e2e` exits 0 — serve a project
>   with **no** `providers.json`; the panel renders `agent_unavailable` by name;
>   provider specs are written and a runtime is attached without restarting the
>   process; a provider is configured against a scripted `FakeModel`; a session
>   then runs and streams into the panel; sign-out returns the panel to `none`
>   and the session routes to `agent_unavailable`. Tier 1: the web path **cannot**
>   add a name to `credential_allowlist` (refused by name), and a variable outside
>   the allowlist never reaches the sidecar's environment; a sentinel credential
>   literal appears nowhere in the opstore, the archived event goldens, the
>   sidecar `stderr_tail`, or the bench evidence bundle, including under a
>   scripted OAuth fixture whose token endpoint returns the sentinel in its
>   response body; and the process holds exactly one listening socket after a
>   full OAuth flow.
>
> **Open question carried by this amendment, requiring a separate maintainer
> ruling before it is implemented:** whether the workspace may **discover** a Pi
> `auth.json` outside the project root and offer it as a credential source.
> Mission rule 7's approval mechanism is a supervisor-prepared allowlisted
> environment; `INTERFACE.md` §23.5 records the argument on both sides and ships
> without discovery pending that ruling.

## 9a. The carried open question, ruled 2026-08-28

§9's block closes by carrying one question: *whether the workspace may*
**discover** *a Pi `auth.json` outside the project root and offer it as a
credential source.* The operator ruled on it the same day, in these words:

> "The server should be able to work locally, the same way that Claude for
> science works."

**Approved, with binding constraints, entering as its own gated sub-stage
`10C` with `G10C`** — which is the form §23.5 itself demanded of an approval
("if the maintainer wants the offer, it enters with its own gate clauses"). The
server MAY enumerate the operator's existing credential sources — a Pi
`auth.json`, an existing `providers.json`, a local OpenAI-compatible endpoint —
and **offer** them, describing each *without* its secret. The constraints that
survive the approval, each now written into `INTERFACE.md` §23.5 and gated by
G10C: discovery is an **offer, never a silent adoption**, and adoption is one
explicit request naming the discovered source; a secret is **never** echoed to
the client, logged, or placed in a URL, an event, or an artifact; the serve stays
**loopback-only**; anything written is **`0600`**; and **mission rule 7 is
unchanged**, still forbidding ambient provider keys reaching a run unapproved,
with `credential_allowlist` supervisor-prepared and not web-writable.

**Two consequences worth stating, because they are where an implementer would
drift.** First, the ruling permits describing a source "with a masked hint at
most" — a **ceiling**, not an instruction. `INTERFACE.md` §15.41's *no masked
key tail* is stricter and stands: the offer carries kind, provider id, model ids
and source path, and nothing derived from a secret. Second, §23.5's draft clause
*"no read of the discovered file before acceptance"* is **narrowed** by the
ruling rather than kept — an offer that has read nothing cannot name a provider
or its models — to: the offer reads **non-secret fields only**, and what the
clause was protecting is carried by "never a silent adoption" instead.

**Item 8's size and shape are unchanged by this.** Discovery is additive work
after item 8, not a rewrite of it: two routes, one panel affordance, and four
negative tests (`INTERFACE.md` §23.14 items 17–19).

## 10. If only one thing is built

**Item 1, then item 3, then item 4.** Item 1 is hours and closes a deviation
where the spec, the route and the widget already agree. Item 3 is the week that
makes every later surface inherit a design instead of re-inventing one. Item 4 is
the answer to the complaint that was most clearly a spec error rather than a
spec deferral: the code deferred prompting to a section that never asked for it,
and `Composer` was on the Stage-4 inventory the entire time.
