# Architecture decisions

> **Verified against** `49a90c6` on 2026-09-12.
> Every decision below is recorded from the code that implements it and the
> reasoning the code itself carries. None is a proposal.

arc42 section 9, as [ADRs](https://adr.github.io/). Each record states the
decision, the alternative that was rejected, and what it cost — because a
decision record without a cost is advocacy.

**Status vocabulary:** `Accepted` (in force), `Superseded` (replaced, kept for
the reasoning), `Open` (a real question with no answer yet — these live in
[known open issues](../06-operations/known-open-issues.md), not here).

---

## ADR-001 — `opstore` is generic and dependency-free

**Status:** Accepted.

**Decision.** Durability — WAL, idempotency keys, content-addressed blobs,
leases, run admission, GC — lives in a package that knows nothing about CAD and
declares no third-party dependencies. `contract` is separated on the same
principle.

**Rejected.** Durability as a module inside `core`, beside the geometry it
serves.

**Why.** Durability is the part that must be right under crash, which means
testing it exhaustively with injected crash points, a fake clock and a fake
liveness oracle. Inside `core` every one of those tests would drag in OCCT.

**Cost.** Two package boundaries to maintain, and a generic vocabulary
(`ref`, `owner`, `run_id`) that reads as less specific than a CAD-aware one
would. `contract` has to carry its own staged copy of the limits file rather than
importing one.

---

## ADR-002 — Declare the tool surface once, generate the rest

**Status:** Accepted.

**Decision.** 57 tools are declared as data in one Python module. JSON Schemas,
the TypeScript TypeBox module, the MCP declarations and the normative prose
headings are generated or drift-tested against it in CI.

**Rejected.** Hand-maintained schemas per language.

**Why.** Three copies of 57 signatures across two languages fail silently — a
model calls a tool with a parameter the server dropped, and nothing errors until
geometry is wrong.

**Cost.** Regenerating is a build step. Hand-editing a generated schema fails the
suite, which surprises newcomers exactly once.

---

## ADR-003 — Verdicts and refusals are disjoint vocabularies

**Status:** Accepted.

**Decision.** A named refusal may never be spellable as an outcome. Verified by
intersecting the sets; the solver's 12 verdicts and 34 refusals have an empty
intersection, asserted in the suite.

**Rejected.** A single status enum with `timeout` alongside `no_solution`.

**Why.** A killed solve **decided nothing**. One enum invites a caller to treat
`solver_timeout` as "no placement exists", which is the exact wrong conclusion:
one means try again with more budget, the other means the problem is
over-constrained.

**Cost.** A large vocabulary — 87 HTTP reasons, 34 solver refusals, 39 CAD-op
reasons — and the discipline to keep adding to it rather than reaching for a
generic failure.

---

## ADR-004 — Prove the sandbox by running it

**Status:** Accepted.

**Decision.** Capability is established by executing a trivial job inside
bubblewrap and performing live escape probes: network connect must fail, writes
outside the out dir must fail, `/etc/shadow` must be unreadable, the out dir must
be writable and visible. A version string is never trusted.

**Rejected.** Checking `bwrap --version` and a feature matrix.

**Why.** A version says what the binary claims, not what the kernel, the
container, the seccomp profile or the user namespace configuration will actually
permit. Every one of those can make a nominally capable bwrap fail to isolate.

**Cost.** A probe run per store root on first use. Mitigated asymmetrically: only
*passing* reports are cached, so a later `apt install bubblewrap` is picked up
without a cache bust.

---

## ADR-005 — No silent fallback to unsandboxed execution

**Status:** Accepted.

**Decision.** `secure_backend` returns a probed backend or raises
`sandbox_denied`. The unsafe backend exists only for user-invoked local
debugging, prints a warning on every execution, reports every isolation feature
`False`, and is refused outright for registry content and for `serve`.

**Rejected.** Falling back with a warning when bwrap is unavailable.

**Why.** A warning in a log is not consent. The difference between "sandboxed"
and "ran arbitrary downloaded Python as you" must be a refusal the operator
resolves, not a line they scroll past.

**Cost.** Secure builds are Linux-only in v0.1, and macOS refuses script
execution by name. Stated as a product property, with a release lane that asserts
the refusal rather than skipping.

---

## ADR-006 — Statement-level execution with checkpoints

**Status:** Accepted.

**Decision.** The worker splits a part script into top-level statements and
executes them one at a time, checkpointing index, line, verbatim text, span and
bound names after each. Failure emits a complete error record with a ±2-line
frame, `built_through`, and last-good metrics, plus the last-good BRep.

**Rejected.** `exec()` on the module and a traceback.

**Why.** "It built through line 40 and then failed, and here is the geometry as
of line 39" is a fact a model can act on. A traceback is not.

**Cost.** Execution is not a plain `exec`, so anything relying on module-level
semantics across statements needs care. Shape refs are held eagerly and metrics
computed lazily to keep the checkpointing affordable.

---

## ADR-007 — Starlette, not FastAPI

**Status:** Accepted.

**Decision.** The workspace API is Starlette.

**Rejected.** FastAPI.

**Why.** Starlette is already in the dependency graph as the transport `fastmcp`
serves streamable HTTP on, so `heph serve --mcp --web` runs **one** HTTP stack in
one process. FastAPI would be a second web framework with no gate behind it.

**Cost.** Request validation is written rather than derived from signatures —
which the closed route table and the canonical tool schemas were going to do
anyway.

---

## ADR-008 — The route table is data, and so is the gap

**Status:** Accepted.

**Decision.** `ROUTE_TABLE` is 56 `(method, template)` pairs; a boundary test
asserts the served surface equals it across both transports. Three routes the
specification names and the app does not serve are declared as
`UNSERVED_SPEC_ROUTES`.

**Rejected.** Deriving the served set from decorators, and leaving the
unimplemented rows to a spec reader to notice.

**Why.** A route added without a row should fail a test rather than ship quietly.
And a specification could name a route that does not exist indefinitely with a
green suite — it had, for three routes, one of which nobody had ever counted.

**Cost.** Adding a route is a two-file change.

---

## ADR-009 — No state library in the web client

**Status:** Accepted.

**Decision.** One module over `useSyncExternalStore` holds a flat,
URL-serializable workspace record. TanStack Query holds server state.

**Rejected.** Zustand or Redux; per-component `useState`.

**Why.** The pin must have **exactly one authority**, and the record must
round-trip through a URL, which is a flat record rather than a reducer ceremony.
A library's only output here would be a store this small; `useState` cannot hold a
single pin authority at all.

**Cost.** The store is hand-written, and its invariant — `artifact_ref` and
`pin_mode` are not writable through `update()`, only through three named doors —
is enforced by the patch type plus a runtime throw rather than by a framework.

---

## ADR-010 — Publishing never advances a held pin

**Status:** Accepted.

**Decision.** `observeCurrent(ref)` is a **no-op while held**. It is the only
path a server response may take to the pin.

**Rejected.** Refreshing the workspace to the newest build when one lands.

**Why.** A workspace that auto-refreshed to latest would silently swap the
geometry an operator was reading a measurement against. The measurement on screen
would then describe something else.

**Cost.** An operator can sit on stale geometry indefinitely, so the header has
an explicit "follow current" action and the pin state is visible.

---

## ADR-011 — Production and download are two steps

**Status:** Accepted.

**Decision.** `POST /parts/{part}/export` returns a result document and **no
bytes**; `GET /exports/{export_blob}/bytes` serves them, addressed by blob hash
and authorized by a `COMMITTED` export row.

**Rejected.** Returning the file from the mutation.

**Why.** Three reasons, each sufficient: a retried *download* would re-enter a
keyed *mutation*; a multi-megabyte binary would sit where the refusal payload has
to fit; and "the export failed" and "the transfer failed" would become the same
event.

**Cost.** Two round trips, and a client that must hold the returned hashes.

---

## ADR-012 — The bearer rides a WebSocket subprotocol

**Status:** Accepted.

**Decision.** The token is a second subprotocol value (`hephaestus.bearer`); the
server echoes the first value back on accept.

**Rejected.** The query string.

**Why.** A browser **cannot** set a header on a WebSocket upgrade — there is no
API for it. A subprotocol travels in a request header; a query string travels
into every proxy log on the path, which is exactly what the fragment rule exists
to prevent.

**Cost.** An unusual handshake that needs explaining, which is why it is
explained in the module that does it.

---

## ADR-013 — A stalled browser tab never cancels a run

**Status:** Accepted.

**Decision.** The event pump's durable-overflow policy cancels the affected run.
A non-durable **observer** that overflows is dropped instead: the socket closes
`4409 resync_required` and the run continues untouched.

**Rejected.** Shared fate — treating the browser like any other client.

**Why.** An agent's work must not die because someone left a tab behind a
breakpoint. Making the web client droppable instead is illegal because only
`progress` is droppable.

**Cost.** The client must render a **labelled break** for what the buffer lost,
and it can never heal one from history: the live and historical identity
namespaces are disjoint, so a dedupe would never match and every refilled event
would render twice. Of the ten event kinds, history can reconstruct five, `image`
as metadata only, and four not at all. Stated rather than implied.

---

## ADR-014 — `py.*` handlers run on a pool, and saturation fails one call

**Status:** Accepted.

**Decision.** The frame reader decodes and routes; 32 workers execute. A request
arriving when all workers are busy is refused `handler_overloaded` rather than
queued.

**Rejected.** Running handlers inline on the reader; or queueing behind the pipe.

**Why.** A handler may issue **outbound** requests — a delegation prompts its
child over the same pipe — so inline execution blocks the only thread that can
deliver the response it is waiting for. And queueing behind the pipe stalls every
frame, including the ones that would unblock the busy handlers.

**Cost.** A named overload reason callers must handle, and a worker count (32,
twice the run slots) that has to be kept in a ratio with admission.

---

## ADR-015 — Three timeout classes, not one

**Status:** Accepted. **Supersedes** a single tool-call bound.

**Decision.** `tool_seconds` (120), `turn_seconds` (600) and
`cad_build_seconds` (300) are separate classes. `cad_build_seconds` is not
selectable on the supervisor: builds travel sidecar-to-Python, so the deadline
that decides one is the sidecar's own RPC peer default.

**Why it changed.** Bounding a turn by the tool number made the watchdog kill the
**whole sidecar** over latency that was never a fault. A turn runs a model round
trip plus every tool the model asks for.

**Cost.** Three numbers to reason about, and a field that would be "correctly
named on the wrong object" if added where it first seems to belong.

---

## ADR-016 — The watchdog credits its own delay

**Status:** Accepted.

**Decision.** A pending call's effective deadline moves out by the time the
supervisor itself made the child wait. The credit closes on the transition to
zero in-flight handlers, not per handler.

**Rejected.** A flat deadline; or summing per handler.

**Why.** Without the credit, a sidecar blocked on a slow `py.tool_dispatch` is
judged unresponsive for time the Python side consumed. Per-handler summing would
let a genuine wedge be paid for with concurrency, because the child waits **once**
for a batch it issued in parallel.

**Cost.** The deadline is no longer a simple constant, so a test that asserts one
has to model the credit.

---

## ADR-017 — `(blob, kind)` is a set, recorded by the publisher

**Status:** Accepted.

**Decision.** `tp_artifact_kinds` holds one row per (blob, kind), written at
publication. A reader refuses a ref whose label is not among the recorded kinds.

**Rejected.** A `kind` column on the blob; and continuing to believe the caller's
string.

**Why.** The store dedups by content hash, so identical bytes published under two
kinds are one blob; a single-valued column would have to pick a winner and make
the loser unservable through its own ref. Believing the caller's label meant a ref
saying `build` whose hash named an export served the export's bytes — so every
refusal written in terms of the kind segment refused a naming convention rather
than a boundary.

**Cost.** Blobs published before the table existed have no rows, reported as the
**empty set** and treated as *unverified* — not "no kind matches" (which would
make every pre-existing artifact unreadable) and not "any kind matches" (which
would be the module lying). The caller decides what an unverified blob may do.

---

## ADR-018 — A lane never passes by absence

**Status:** Accepted.

**Decision.** Release lanes assert the thing that should be missing. Lane (a)
asserts Node is gone; lane (d) asserts the named refusal. The deferred macOS lane
was **removed, not conditioned**.

**Rejected.** Conditioning a lane on platform availability and letting it skip.

**Why.** A conditioned lane reports green for a platform nobody tested, and no
green check should be able to stand in for one that did not run.

**Cost.** Removing a lane is visible and deliberate, which is the point, but it
means the matrix has to be edited rather than toggled.

---

## ADR-019 — Every lane installs the built wheel

**Status:** Accepted.

**Decision.** No release lane installs from the source tree; each downloads the
`wheelhouse` artifact. `HEPHAESTUS_WHEELHOUSE` points the packaging suites at the
same artifact.

**Why.** An in-tree install resolves the *development* sidecar at
`agent/build/sidecar`, which makes the gate's central claim — that the wheel uses
its packaged sidecar — untestable.

**Cost.** A wheelhouse job every lane waits on.

---

## ADR-020 — The sidecar ships inside `hephaestus-server`

**Status:** Accepted.

**Decision.** The compiled Node bundle is package data of `hephaestus-server`,
not of the aggregate distribution, with a SHA-256 manifest the supervisor
verifies before every spawn.

**Rejected.** Shipping it in `hephaestus-cad`.

**Why.** The only code that resolves and spawns it is `hephaestus.agent_bridge`.
Co-locating them means `pip install hephaestus-server` is self-consistent and
there is **no way to assemble an installation whose bridge and sidecar come from
different releases**.

**Cost.** A staging step between `pnpm run bundle` and `uv build`, and a local
tree whose sidecar goes stale after an `agent/` edit or a `git pull`. The
freshness guard behind `HEPHAESTUS_SKIP_SIDECAR_BUILD=1` refuses a stale stage
rather than running one — which is what turns a confusing
`session.model.get: method not found` into a named error.

---

## ADR-021 — The client computes no facts, enforced by lint

**Status:** Accepted.

**Decision.** Every number presented as fact renders through `<Fact>` carrying
`data-source` naming the HTTP response field. `heph/no-derived-fact` rejects
computed sources, derived values, and `data-source` on any other element.

**Rejected.** A convention; or a lint that tried to decide whether a number is a
fact.

**Why.** An attribution any element could write is not an attribution. And "is
this number presented as fact" is a judgement about meaning — a lint that guessed
would be either trivially evadable or would flag the grid readout, which is
exempt by name.

**Cost.** The mechanical half is three checks; completeness rests on the e2e's
DOM-versus-JSON comparison. Some components split in two to keep the `source`
prop a literal.

---

## ADR-022 — Refusal text has no raw-message fallback

**Status:** Accepted. **Supersedes** "the server named it, so the server's words
stand".

**Decision.** A reason absent from the client's map renders the generic sentence,
never `error.message`.

**Why it changed.** The old reasoning is true of a sentence and false of a
*composed* string. The server builds one message as `f"{cause}: {detail}"`, so the
panel rendered `no_provider_config: no provider config at <path>` — a machine
reason code, a colon and an engine detail — inside a `role="alert"`.

**Cost.** A new reason needs a client-side sentence, or it renders generically.
That is the intended pressure.

---

## ADR-023 — The GLB's `selection_id` is not parsed

**Status:** Accepted.

**Decision.** The client reads exactly three per-mesh values from the GLB and
deliberately does not read `extras.selection_id`. A raycast supplies
`(mesh_index, primitive_index)` as a **hint about which triangle was hit**.

**Rejected.** Reading the ID the document already carries.

**Why.** A client that had the ID in hand would eventually submit it, and
selection IDs are server values — a hint is not an authorization. So it is not
parsed, not stored, and not reachable from anything the module returns.

**Cost.** A server round trip to resolve a selection.

---

## ADR-024 — Section has two surfaces, and only one is evidence

**Status:** Accepted.

**Decision.** The **plate** is a server-rendered PNG, golden-compared. The
**live clipping preview** is three.js clipping planes, never golden-compared. The
two carry different `data-section-state` values.

**Why.** A headless-Chromium WebGL render is a **different rasterizer** and will
not match server goldens. Comparing it would produce a permanently red test that
says nothing about the model.

**Cost.** Two implementations of "show me a section", and the discipline to keep
them visibly distinct in the DOM.

---

## ADR-025 — Orthographic in the browser, framed like the server

**Status:** Accepted.

**Decision.** The viewport uses an orthographic camera whose framing mirrors the
server's construction, renders on demand with a **synchronous** frame after a
programmatic change, and sets `preserveDrawingBuffer`.

**Why.** A perspective viewport would put the browser and `heph render` in
visible disagreement about the same named view for no gain in a CAD instrument. A
synchronous frame means a harness that screenshots right after a click sees the
frame that click produced, rather than racing the compositor. Chromium may clear
a WebGL back buffer after compositing, so a screenshot without
`preserveDrawingBuffer` can come back blank.

**Cost.** `preserveDrawingBuffer` costs a copy per frame. User drags still
coalesce through rAF, because sixty synchronous frames a second is what a loop is
for.

## Related

- The concepts these decisions express: [crosscutting concepts](crosscutting-concepts.md).
- Questions still open: [known open issues](../06-operations/known-open-issues.md).
