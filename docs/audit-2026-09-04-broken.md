<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# Audit 2026-09-04: broken

Twelve defects from the 2026-09-04 surface audit, each re-reproduced against the
working tree, traced to the commit that introduced it, and checked against the
clause that governs it. Every item states what a symptom-only patch would miss,
because in eight of the twelve the obvious patch leaves the mechanism intact.

Two findings are wider than the audit reported. B-1 is not only a tool refusal:
the same empty geometry index is used by `heph check` and by project-scope
`run_checks`, so a cross-part acceptance check reports **`pass: false`** where it
should refuse — a red verification signal for a correct design. B-8 has two
independent causes, and fixing the one the audit named leaves the dialog
unreadable.

One item is a mechanism, not a bug: the Stage-2 gate harness `tests/stage2/_g2.py`
is a subclass of the shipped `BridgeRuntime` that injects exactly the wiring
production never does, so every G2 gate exercises a runtime that does not ship.
B-2 and B-3 are both downstream of that, and neither fix is finished until the
harness stops overriding.

## Summary

| id | title | severity | effort | files |
| --- | --- | --- | --- | --- |
| B-1 | `measure` and every parent-side measurement resolve only the literal `"part"` selector | critical | L | `core/src/hephaestus/core/executor/artifact_geometry.py`, `core/src/hephaestus/core/assembly.py`, `server/src/hephaestus/agent_bridge/cad_ops/_base.py` |
| B-1b | §7 rule 4 has no binding-to-solid mapping, so binding names are unaddressable on any published artifact | medium | M | `core/src/hephaestus/core/executor/worker.py`, `core/src/hephaestus/core/executor/source_map.py`, `core/src/hephaestus/core/executor/published_geometry.py` |
| B-2 | Nine model-visible tools are unwired in all three shipped runtimes | critical | L | `server/src/hephaestus/agent_bridge/dispatch.py`, `server/src/hephaestus/agent_bridge/app.py`, `server/src/hephaestus/http/runtime.py`, `server/src/hephaestus/mcp/app.py` |
| B-3 | `delegate_part_agent` fails its own result schema in both shipped runtimes | high | S | `server/src/hephaestus/agent_bridge/app.py`, `server/src/hephaestus/agent_bridge/workflows.py` |
| B-4 | Every `heph part create` template is unbuildable: the table opens with a forbidden import | critical | M | `core/src/hephaestus/core/part_templates.py`, `docs/cli.md` |
| B-5 | `GET /parts/{part}/build` reports a superseded build as current; the chip says "up to date" | high | L | `server/src/hephaestus/http/projections.py`, `core/src/hephaestus/core/project_store/publication.py`, `web/src/components/BuildStateChip.tsx` |
| B-6 | 404, 405 and every unmapped exception leave the API without an error envelope | high | M | `server/src/hephaestus/http/app.py`, `server/src/hephaestus/http/errors.py` |
| B-7 | View cube: azimuth is applied as a screen roll; 5 of 15 targets are unreachable | high | L | `web/src/components/stage/viewport/ViewCube.tsx`, `web/src/viewport/cameras.ts` |
| B-8 | BOM dialog is 2838px tall at y=-919 with no scroll, and its value column is 0px wide | high | S | `web/src/system/Popover.module.css`, `web/src/system/Panel.module.css` |
| B-9 | Creating a session hides every other session; the new one is then unreachable | high | M | `web/src/components/stream/StreamPanel.tsx`, `web/src/stream/thread.ts` |
| B-10 | Four CLI verbs traceback where the taxonomy says they must refuse | high | M | `core/src/hephaestus/core/cli.py`, `core/src/hephaestus/core/cli_cam.py`, `core/src/hephaestus/core/cli_render.py`, `core/src/hephaestus/core/cli_init.py`, `core/src/hephaestus/core/render/goldens.py` |
| B-11 | A malformed cursor is reported as a dead runtime; resuming a transcript that does not exist mints one | high | M | `server/src/hephaestus/http/errors.py`, `server/src/hephaestus/http/sessions.py`, `agent/src/session/history.ts`, `agent/src/session/manager.ts` |
| B-12 | `stubSummary` is the only producer of the pinned CAD summary, so compaction carries nothing | high | M | `agent/src/main.ts`, `agent/src/session/context.ts` |

Severity is user-visible consequence, not effort. `critical` means a documented
capability does not work at all; `high` means a surface reports something untrue;
`medium` means a documented rule one surface cannot serve, refusing honestly and
with a route around it.

B-1b is **not** one of the twelve. It was opened by wave one's implementation of
B-1, which proved this document's own expectation for contract §7 rule 4
structurally unreachable, and it is recorded here so a later reader treats that
limit as a known deviation rather than as an unfinished fix to be patched back
in.

## Workflow plan

Seven lanes with disjoint file ownership. A file appears under exactly one lane.
Where two lanes must both edit a file, the file is owned by one of them and the
other lane runs after it; those cases are listed in full below the table, because
they are the only real sequencing constraints in the set.

| lane | items | owns |
| --- | --- | --- |
| A — CLI surface | B-4, B-10 | `core/src/hephaestus/core/part_templates.py`, `core/src/hephaestus/core/cli.py`, `core/src/hephaestus/core/cli_cam.py`, `core/src/hephaestus/core/cli_render.py`, `core/src/hephaestus/core/cli_init.py`, `core/src/hephaestus/core/render/goldens.py`, `core/tests/test_cli_authoring.py`, `core/tests/test_cli_cam.py`, `core/tests/test_cli_init.py`, `core/tests/test_render_inspect_cli.py`, `docs/cli.md` |
| B — Engine addressing | B-1 | `core/src/hephaestus/core/executor/artifact_geometry.py`, `core/src/hephaestus/core/assembly.py`, `core/src/hephaestus/core/render/inspect.py`, `core/src/hephaestus/core/checks/report.py`, `core/src/hephaestus/core/placement.py`, `core/src/hephaestus/core/project_store/publication.py`, `core/src/hephaestus/core/project_store/projections.py`, `server/src/hephaestus/agent_bridge/cad_ops/_base.py`, `server/src/hephaestus/agent_bridge/cad_ops/_measure.py`, `server/src/hephaestus/agent_bridge/cad_ops/_checks.py`, `core/tests/test_artifact_geometry.py` |
| C — Agent wiring | B-2, B-3 | `server/src/hephaestus/agent_bridge/dispatch.py`, `server/src/hephaestus/agent_bridge/app.py`, `server/src/hephaestus/agent_bridge/workflows.py`, `server/src/hephaestus/agent_bridge/delegation.py`, `server/src/hephaestus/http/runtime.py`, `server/src/hephaestus/mcp/app.py`, `server/src/hephaestus/testing/tools_fixture.py`, `tests/stage2/_g2.py`, `server/tests/test_workflows.py` |
| D — HTTP envelope and session refusals | B-6, B-11 | `server/src/hephaestus/http/app.py`, `server/src/hephaestus/http/errors.py`, `server/src/hephaestus/http/sessions.py`, `server/src/hephaestus/testing/fake_agent.py`, `agent/src/session/manager.ts`, `agent/src/session/history.ts`, `agent/src/main.ts`, `server/tests/test_http_errors.py`, `server/tests/test_http_sessions.py` |
| E — Sidecar context | B-12 | `agent/src/session/context.ts`, `agent/test/session/context.test.ts`, `tests/stage2/test_g2_context.py` |
| F — Build-state honesty | B-5 | `server/src/hephaestus/http/projections.py`, `server/src/hephaestus/http/context.py`, `server/src/hephaestus/agent_bridge/cad_ops/_build.py`, `core/src/hephaestus/core/types.py`, `core/src/hephaestus/core/cli_authoring.py`, `web/src/api/types.ts`, `web/src/components/BuildStateChip.tsx`, `server/tests/test_http_reads.py` |
| G — Web layout and strip | B-7, B-8, B-9 | `web/src/components/stage/viewport/ViewCube.tsx`, `web/src/components/stage/viewport/ViewCube.module.css`, `web/src/viewport/cameras.ts`, `web/src/system/Popover.module.css`, `web/src/system/Panel.module.css`, `web/src/system/Panel.tsx`, `web/src/system/DataTable.tsx`, `web/src/components/stream/StreamPanel.tsx`, `web/src/stream/thread.ts`, `web/src/api/sessions.ts`, `web/src/copy.ts`, `web/test/viewportChrome.test.tsx`, `web/e2e/viewport.spec.ts`, `web/e2e/chrome.spec.ts`, `web/e2e/stream.spec.ts` |

**Three follow-ups have no lane, and each names a file the table above does not
allocate.** They are not gaps in a lane's work; they are work no lane could do.
B-1b needs `core/src/hephaestus/core/executor/worker.py` and
`core/src/hephaestus/core/executor/source_map.py` (plus the source-map schema
documentation), none of which appear in any `owns` cell — only its third file,
`published_geometry.py`, is lane B's. B-10's shared error boundary is adopted by
the four CLI modules lane A owns and by no others, so eight further `cli_*`
modules keep private copies of the same usage error and guard. And B-1's
tool-level assertions — the `measure`/`run_checks` parity over the four selector
kinds, and the pin that no refusal names a rule-4 binding in **either** its
candidate list or its message — belong in `server/tests/test_dispatch_tools.py`,
which is in no lane's list either. Each needs an explicit ownership grant (widen
a lane, or open one that owns `core/src/hephaestus/core/executor/` and
`server/tests/`) before anyone can act on it.

Four lanes also create a module, and each new module belongs to the lane that
creates it: lane A adds `cli_errors.py` under `core/src/hephaestus/core/`, lane B
adds `published_geometry.py` under `core/src/hephaestus/core/executor/`, lane C
adds `wiring.py` under `server/src/hephaestus/agent_bridge/`, and lane G adds
`cubeTargets.ts` under `web/src/viewport/`. No two lanes create the same file.

### Shared files, and the order they force

- `server/src/hephaestus/agent_bridge/app.py` — owned by lane C (B-2's dispatcher
  construction and B-3's `_handle_delegate` replace the stub at
  `server/src/hephaestus/agent_bridge/app.py:1260`). Lane D's B-11 re-adoption
  change touches `_readopt` in the same file. **C before D.**
- `agent/src/main.ts` and `agent/src/session/history.ts` — owned by lane D
  (B-11's cursor and resume refusals). Lane E's B-12 replaces two `stubSummary`
  call sites in `agent/src/main.ts` and needs the entry readers in
  `agent/src/session/history.ts` exported. **D before E.**
- `server/src/hephaestus/http/app.py` — owned by lane D (B-6's exception
  handlers). Lane F's B-5 changes `get_build` in the same file. **D before F.**
- `core/src/hephaestus/core/project_store/publication.py` — owned by lane B
  (B-1's durable bundle pointer). Lane F extracts `input_mismatches` out of
  `Publisher._revalidate` in the same file. **B before F.**
- `web/src/copy.ts` — owned by lane G (B-7 retires the `iso` glyph string). Lane
  F adds one `buildState.stale` title string. **G before F.**
- `INTERFACE.md` — amended by lanes D (§2.3, §2.4, §2.8), F (§4.1, §5.5, §8) and
  G (§4.7, §5.5, §7.1). §5.5 is amended by both F and G: **G before F**, which
  the `web/src/copy.ts` ordering already forces.
- `docs/cli.md` — owned by lane A and amended by both its items. Land B-4's
  re-recorded quickstart before B-10's exit-code and `--fixtures-dir` edits.

### Order

Lanes A, B, C and G have no inbound dependency and can start together. Then D
(after C), then E (after D) and F (after B, D and G). Within lane A, B-4 first:
it is a two-file change with the largest user-visible payoff and it makes every
`create_part`-then-build test in lane C honest. Within lane C, B-3's schema fix
(dropping the illegal `part_session_id: null`) is two lines and should land
first, so the failure is at least well-formed while B-2's wiring is built.

### Dependencies outside this document

Three of B-2's steps are blocked on defects filed elsewhere in the 2026-09-04
audit. They are named with their mechanism here so the lane is actionable
without them:

- **`py.*` handlers run inline on the supervisor's single reader thread.**
  `Supervisor._read_loop` calls `_on_frame`, which calls the `py.*` handler
  synchronously; `Supervisor.call` then blocks waiting for a response only that
  thread can deliver (`server/src/hephaestus/agent_bridge/supervisor.py`, whose
  own comment states the invariant). Wiring a real `SessionDelegationRunner`
  into `BridgeRuntime` without first moving py-dispatch onto a bounded worker
  pool hangs the sidecar on the first `delivery="prompt"` delegation. B-2's
  delegation third must not land before that; wiring `delegation=` **without**
  `delegation_runner=` is the safe intermediate state and is already supported —
  the dispatcher synthesizes an `INTERRUPTED` terminal rather than inventing a
  completion. **Two capabilities are held short by this blocker, not one.**
  `query_snapshot` is an ordinary tool dispatched from the same
  `py.tool_dispatch` path, so a snapshot caller that issues `Supervisor.call`
  deadlocks identically — wave one reproduced the watchdog killing the child and
  the run dying with `sidecar restarted`. Its safe intermediate state mirrors
  delegation's: bind the caller, and have it report itself unavailable before any
  work starts, so the model reads `capability_not_available` (B-2 step 3). Both
  go live with no edit at either site once py-dispatch moves onto a bounded
  worker pool.
- **`heph agent` runs model-authored build scripts under the unsafe local
  backend.** `CadOpsState` defaults to `UnsafeLocalBackend()` when no backend is
  injected, and `BridgeRuntime` injects none. Until that is fixed,
  `instance_store_part` stays at `capability_not_available` under `heph agent`
  even once the registry is wired, because
  `core/src/hephaestus/core/executor/sandbox/unsafe.py` refuses registry-origin
  jobs by design.
- **`DelegationService` defaults to a permissive gate.**
  `server/src/hephaestus/agent_bridge/delegation.py:148` is `_AllowAllGate`,
  "never rejects (tests inject their own)", and no production code constructs a
  gate. Landing delegation without a real gate means accepting a delegation to a
  part that does not exist and reporting it completed.

B-8's fix has a second half that is also filed separately: `PanelSection`
children are not given the `grid-column: 1 / -1` span that `.body > *` gets. It
is stated in full under B-8 because B-8's acceptance criterion cannot be met
without it; whoever lands it first should note it so it is not applied twice.

## B-1 — `measure` and every parent-side measurement resolve only the literal `"part"` selector

- **severity** critical · **surface** agent-tools · **verdict** confirmed
- **effort** L · **risk** medium · **lane** B · **depends on** — (B-4 eases the
  end-to-end tests; it does not gate the fix)

### Symptom

`measure(kind="bbox", a="top_face", part="w")` refuses with
`invalid_part: selector 'top_face' resolves to nothing` and an **empty**
candidate list, while the same selector resolves inside that part's `CHECKS`
during the build that produced the artifact being measured. Solid labels and
binding names refuse the same way. The audit reported this as a tool defect; it
is wider. `heph check` and project-scope `run_checks` reach the same empty index,
so a project check addressing `"<part>/<label>"` returns `pass: false` with an
`AddressingError` buried inside `measured` — a failing acceptance check for a
correct design, rather than a refusal.

### Reproduction

In a scaffolded project write `parts/w.py` as
`body = Box(40, 20, 6); body.label = "wb"; tag(body.faces().sort_by(Axis.Z)[-1], "top_face"); part.geometry = body`
with `CHECKS` over both selectors, build it, then call the tool and the
project-check path.

Observed — `CHECKS` in-worker: `tag_in_check` passes, measured `[40, 20, 0]`;
`label_in_check` passes, measured `[40, 20, 6]`. `measure` on the same artifact:
`"part"` returns `[40, 20, 6]`; `wb`, `top_face` and the binding `body` each
raise `AddressingError` with `candidates=()`. A project check
`{"cross_label_sel": m.bbox("w/wb")}` returns
`{"pass": false, "measured": {"error": {"type": "AddressingError", ...}}}` while
`m.bbox("w/part")` passes. The published bundle for that same build already
holds `geometry_index: {"bindings": {"body": 1}, "labels": ["wb"], "tags": ["top_face"]}`
and the source map already holds
`{"top_face": {"kind": "face", "solid": 0, "topo_index": 5}}`.

Expected — tool_schema.md's `measure` entry declares the full contract §7
grammar: tags, labels with `#k`/`#*` dedup selectors, binding names, `"part"`,
and `"<part>/<label>"` cross-part, with addressing errors listing candidates
rather than guessing. `measure(kind="bbox", a="top_face")` should return
`[40, 20, 0]`, and an unknown selector should list `wb` and `top_face`.

**Known limit, and it is structural: contract §7 rule 4 is not answerable on this
surface.** This paragraph originally expected the binding `body` among those
candidates too. Wave one proved that unreachable against a published artifact:
publication records label runs and tag placements and **no binding-to-solid
mapping**, so a binding name refuses, and it must appear in neither the
structured candidate list nor the prose that restates the same names a second
time. Advertising it would be advertising a name this surface cannot answer.
That is a narrower hole than it sounds — §5.1 label-fill means a geometry-bearing
binding that was never relabelled is already addressable under rule 3 by that
same name, and a binding whose node was relabelled is addressable by the label it
was given. Closing it at the mechanism is B-1b below; do not "restore" `body` to
the candidate set without landing that first.

### Root cause

`MeasureOps` builds its geometry through
`server/src/hephaestus/agent_bridge/cad_ops/_base.py:424`, which calls
`artifact_source` in
`core/src/hephaestus/core/executor/artifact_geometry.py:66`, whose index is a
hardcoded empty `GeometryIndex(labels=(), bindings={}, tags=frozenset())`. The
contract §7 resolver therefore admits rule 1 only and raises with an empty
candidate tuple; the resolver closure never runs for the other rules.

Reloading a BRep genuinely loses labels and tags — but nothing here depends on
the BRep for them. Publication records the worker's own §7 namespace in the build
bundle (`core/src/hephaestus/core/project_store/publication.py:123`) and the tag
placements in the source map. Two parent-side consumers already reconstruct
exactly that: `AnchorResolver` and `PartGeometry` in
`core/src/hephaestus/core/assembly.py:477` resolve part, tag, label and binding
against a reloaded artifact for constraint anchors, joints and solves; and
`tag_placements_from_source_map` in
`core/src/hephaestus/core/render/inspect.py:419` does it again for
`inspect_part(focus=…)` — which is why `inspect_part(focus="top_face")` succeeds
on the very artifact `measure` cannot address. `measure`, `heph check`
(`core/src/hephaestus/core/checks/report.py:77`) and project-scope `run_checks`
(`server/src/hephaestus/agent_bridge/cad_ops/_checks.py:254`) are the three
callers that use neither.

History. `part_only_source` and its empty index were born with the engine in
b0715f6 "feat(core): Stage 0B CAD engine, Gate G0B green", where its only
consumer was `heph check` measuring `"<part>/part"` cross-part — for which an
empty index is honest. One day later 5329250 "feat(agent): Stage 2B product
layer — full tool surface, thread-phase, registries, bench" added the `measure`
**tool** and reused `artifact_source` verbatim, inheriting the restriction while
declaring the full grammar in the schema. Three days after that d06eb37
"feat: Stage 8C assemblies and constraints — declared cross-part fits that must
hold" built the real published-artifact resolver, because constraint anchors
needed tags — and nobody went back to `measure`. bb546fd
"feat(stage4): server/http + the read-only web workspace — G4 19/20,
browser gate pinned-image-deferred" then wrote a third implementation for
`inspect_part`. `git log --oneline -- core/src/hephaestus/core/executor/artifact_geometry.py`
shows two commits in fourteen months; the file was never revisited after the
capability it lacks was built twice elsewhere.

Spec. **The code is wrong; the spec describes a capability the repository has
already built.** tool_schema.md's `measure` entry declares the grammar;
`core/src/hephaestus/core/addressing.py` states the contract §7 precedence and
that "a selector matching nothing raises addressing_error listing
candidates/near-misses, never a silent guess"; the shipped part-agent prompt in
`agent/src/session/profiles.ts` instructs the model to tag topology "so checks
and measure can address it later". The one document that is wrong is
`core/src/hephaestus/core/executor/artifact_geometry.py`'s own module docstring,
which asserts a limitation that stopped being true at Stage 8C.

What a symptom-only patch would miss. Populating the index only inside
`MeasureOps` leaves `heph check` and project-scope `run_checks` still turning a
valid cross-part label check into a **failing** check rather than a refusal, and
leaves a fourth copy of the published-artifact join in the tree. Populating the
index without wiring a shape resolver is worse than today: `resolves to nothing`
becomes an internal error inside the kernel call.

### Fix

Promote the Stage 8C machinery to the single shared "addressable published
artifact" constructor and have all four consumers use it.

1. `core/src/hephaestus/core/executor/artifact_geometry.py` — add
   `published_artifact_source(shape, *, index, placements, result)` beside
   `part_only_source`. Keep `part_only_source` as the honest fallback when no
   bundle exists; stop making it the default for anything that has one. Rewrite
   the module docstring, which currently states as fact that a reloaded artifact
   "supports exactly the `part` selector".
2. New `published_geometry.py` under `core/src/hephaestus/core/executor/` — move
   `PartGeometry`, the published-index reader, the solid-run map and the
   placement decoder out of `core/src/hephaestus/core/assembly.py:477` verbatim;
   re-export them from `core/src/hephaestus/core/assembly.py` so assemblies,
   joints, motion and the solver keep their imports and their behaviour
   byte-for-byte. Have
   `core/src/hephaestus/core/render/inspect.py:419` delegate to the same
   placement decoder, deleting the second copy.
3. `server/src/hephaestus/agent_bridge/cad_ops/_base.py:424` — widen
   `_artifact_geometry(ref, scratch)` to take `part=None`. When a part is given
   and the current bundle's `artifact_ref` equals `ref`, build the published
   source from the bundle's `geometry_index` and the result's source map;
   otherwise fall back unchanged. Zero migration, and it covers every
   current-build call, which is the default path for `measure`, project-scope
   `run_checks` and `heph check`.
4. `server/src/hephaestus/agent_bridge/cad_ops/_measure.py:136` and the snapshot
   source builder in the same package — thread `part` through.
5. `core/src/hephaestus/core/checks/report.py:69` — build the published source
   instead of `artifact_source`.
6. `core/src/hephaestus/core/project_store/publication.py` — install the bundle
   blob and a `build-bundle:<part>:<artifact blob>` pointer for **every**
   publication kind, GC-linked to the artifact, so an explicit historical or
   preview `artifact_ref` resolves its namespace. **The key carries the part, and
   step 3's `part=` argument therefore stays** — this step was first written with
   an artifact-only key and a promise that step 3's special case would disappear,
   and both are wrong for the same reason: an artifact ref is content-addressed
   over BRep bytes alone, so two parts whose geometry is byte-identical share one
   ref, and a pointer keyed by the artifact alone would hand a measurement the
   other part's namespace. Wave one shipped `build-bundle:<part>:<artifact blob>`
   for exactly that collision; with no part in hand the readers fall back to
   `"part"`-only addressing rather than guessing a namespace, which is what
   `_artifact_geometry`'s docstring in
   `server/src/hephaestus/agent_bridge/cad_ops/_base.py` now states. One residual
   ambiguity is documented in code and is narrower: two builds of the **same**
   part with byte-identical BRep but a renamed label share one ref, so the
   pointer is last-writer-wins. It is mitigated by preferring the part's current
   bundle when the ref IS the current artifact, and by the snapshot manifest
   naming the exact `bundle_ref` it froze.
7. `core/src/hephaestus/core/project_store/projections.py:785` — bump the
   project-snapshot manifest to version 2 with a `bundle_ref` beside each part's
   `artifact_ref`, readers accepting version 1 and falling back.
8. `core/src/hephaestus/core/placement.py` — the preview path builds its bundle
   in memory. **Wave one landed this step as a deliberate no-op, and it should
   stay one: seven of the eight steps are code, and this one is a comment.**
   `placement.py` assembles the preview bundle from the `UnpublishedBuild`
   already in hand, through publication's own `build_bundle` — the identical
   document. Reading it back out of the store instead buys nothing behavioural
   and costs a round-trip plus a retention dependency, on the one path (a 2C
   solve) that measures what it just built. The stale comment that claimed the
   preview path had no durable bundle is corrected in place, beside the
   `PublishedBuild` construction, and states the deviation and its reason. Do not
   close B-1 as "all eight steps landed", and do not "fix" this back into a store
   read.

Spec and doc lines to amend. The module docstring in
`core/src/hephaestus/core/executor/artifact_geometry.py` is the primary doc
defect and must lose both halves of its claim. ASSEMBLY.md's note that
publication records the index should name measurement as a consumer, so the next
stage does not build a fourth copy. tool_schema.md's `measure` entry needs no
change — it already describes the correct behaviour — except to name the one
honest remaining limit: a selector against an artifact whose bundle was never
stored refuses `namespace_unrecorded` rather than listing an empty candidate set.

Compatibility. Purely widening. Selectors that resolve today resolve to the
identical shape, because rule 1 is untouched. Selectors that refuse today may now
succeed, and no in-tree consumer can break: every project check in `corpus/`
uses `<part>/part` only. The manifest bump is read-tolerant in both directions.
The extra bundle blob and pointer per preview build sit inside the existing
preview retention class and are collected with their artifact.

### Tests to add

- `core/tests/test_artifact_geometry.py` — `published_artifact_source` over a
  real published build resolves a tag to the tagged **face** (bbox z-extent 0), a
  label to its solid, and `"part"` to the whole compound; an unknown selector's
  `AddressingError` lists `wb` and `top_face` and **not** the binding `body`, per
  the rule-4 limit in Expected. Plus `addressable_namespace` itself: it drops
  binding-only names and keeps a name that is both a label and a binding.
- `server/tests/test_dispatch_tools.py` — a **parity** assertion, not two
  literals: `measure(a=sel)` equals the part-scope `run_checks` measured value
  for the same selector, over `{part, label, tag}`. That is the invariant that
  actually failed. `binding` joins that set only where §5.1 auto-filled the
  label, which is what makes it resolvable under rule 3.
- `server/tests/test_dispatch_tools.py` — **the message, not only the tuple.** A
  refusal states its near misses twice, in `candidates` and verbatim in the
  prose, so `assert "body" not in exc.message` beside
  `assert "body" not in exc.data["candidates"]`. A filter over the structured
  list alone passes the second assertion and fails the first; that is the
  half-fix this bullet exists to catch. And a cross-part refusal's candidates are
  part-qualified — a bare name there would resolve against whichever part is
  *current*, not the one it came from.
- `server/tests/test_dispatch_tools.py` — cross-part
  `measure(kind="clearance", a="w/top_face", b="v/part")` resolves through the
  project snapshot; and a pre-fix artifact ref refuses `namespace_unrecorded`
  rather than listing an empty candidate set.
- A project check `m.bbox("<part>/<label>")` **passes** — the regression pin for
  the silent-red case, which is the half the audit did not report.
- The Stage 8C, 9A, 9B and 13 suites must stay green unmodified after the
  `PartGeometry` move; that is the refactor's own proof.

### Notes

Landing this widens what project checks can answer, so a project that was red
because of an addressing error will go green — correctly. Say so in the change
description, or it reads as a grading regression. Depends on B-4 only in that
every end-to-end test here currently has to route around the unbuildable
templates.

## B-1b — §7 rule 4 has no binding-to-solid mapping to resolve against

- **severity** medium · **surface** engine · **verdict** confirmed by wave one
- **effort** M · **risk** medium · **lane** none — see the workflow plan ·
  **opened by** B-1's implementation, not by the 2026-09-04 audit

### Symptom

On a published artifact, a contract §7 rule-4 selector — a bare **binding** name
— cannot resolve, and no candidate list may offer one. `measure`, `heph check`
and project-scope `run_checks` all answer the other three rules after B-1; rule 4
they answer by refusing, and the refusal deliberately omits binding names from
both halves of its output (`candidates`, and the near-miss clause of the message,
which states the same names a second time in prose).

The user-visible shape is mild because §5.1 label-fill covers the common case: a
geometry-bearing binding that was never relabelled carries its own name as a
label and resolves under rule 3, and a relabelled one resolves under the label it
was given. What is missing is the case where the two diverge — a binding whose
node was given a *different* label — plus the honesty cost of a documented rule
that one surface silently cannot serve.

### Root cause

Publication records the worker's §7 namespace and the source map's tag
placements, and neither carries topology for a binding.
`core/src/hephaestus/core/executor/source_map.py`'s `BindingEvent` records
`{line, statement_index, iteration, call_site}` — provenance, not geometry — so
`published_geometry.py` has nothing to join a binding name against, and
`addressable_namespace` correctly drops those names rather than advertising what
it cannot answer.

The mapping is not merely absent: it is **computed and thrown away**.
`core/src/hephaestus/core/executor/worker.py`'s `_fill_labels_and_rows` already
walks `_reverse_binding_names` and establishes binding-to-node identity live
(`IsSame` over the wrapped shapes) so that §5.1 can fill labels. It uses the
identity for the label fill and discards it.

### Fix

Record what the worker already knows, and let the parent side join on it.

1. `core/src/hephaestus/core/executor/worker.py` — in `_fill_labels_and_rows`,
   keep the solid indices each binding contributed, in `part.geometry.solids()`
   order, instead of discarding them once the labels are filled.
2. `core/src/hephaestus/core/executor/source_map.py` — persist them: either
   extend the existing `bindings` table with the placements or add a
   `binding_placements` table beside it. Version the source-map schema document
   with it.
3. `core/src/hephaestus/core/executor/published_geometry.py` (lane B's file) —
   `PartGeometry._run_shape` resolves rule 4 off that table, and
   `addressable_namespace` collapses to the identity: with the mapping present it
   no longer has anything to drop, and the filter added for B-1 becomes a no-op
   rather than a special case.

A binding that never reaches `part.geometry` — `tests/stage8c/_g8c.py`'s
`spare_rib` is the in-tree instance — must stay `unaddressable_anchor` either
way. The point of the mapping is to distinguish "bound to geometry that was
published" from "bound to something that never got there", which today are the
same refusal.

Spec and doc lines to amend. tool_schema.md's `measure` entry states the rule-4
limit as a limit; landing this retires that sentence. ASSEMBLY.md carries the
same clause about what the addressable view of a published artifact cannot
supply. Both were written by B-1 to describe the gap honestly and must be
retired **together with** the code, not before it.

### Tests to add

- `core/tests/test_artifact_geometry.py` — a binding whose node was relabelled
  resolves to that node under rule 4, where today it refuses; and
  `addressable_namespace` now keeps binding names it currently drops.
- `server/tests/test_dispatch_tools.py` (unowned — see the workflow plan) — the
  B-1 assertions invert: a refusal's candidates and its message may now name a
  binding. Whoever lands this must update those pins in the same change, or the
  two items contradict each other.
- `tests/stage8c/_g8c.py`'s `spare_rib` stays `unaddressable_anchor`; that is the
  assertion that keeps this from becoming a guess.

### Notes

Until this lands, B-1's behaviour is correct as shipped and must not be "fixed":
a rule-4 binding is absent from candidate lists **by design**, and a patch that
puts `body` back in the list without putting the mapping in the source map
restores exactly the defect B-1 removed — a surface advertising a name it cannot
answer.

## B-2 — Nine model-visible tools are unwired in all three shipped runtimes

- **severity** critical · **surface** server-core · **verdict** confirmed
- **effort** L · **risk** medium-high · **lane** C · **depends on** B-3, and the
  three out-of-scope blockers named in the workflow plan

### Symptom

`list_skills`, `load_skill`, `search_materials`, `search_parts_store` and
`instance_store_part` return
`not_implemented: tool 'X' needs the registry stack, which is not wired in this
runtime`. `get_delegation_status` and `cancel_delegation` return the delegation
equivalent. `query_snapshot` returns `capability_error: capability_not_available`.
`delegate_part_agent` fails its result schema (B-3). The system prompt in
`agent/src/session/profiles.ts` orders the model into two of these — "If ANY
build123d API detail is uncertain, FIRST call `load_skill(...)`" — so a
correctly-behaving model hits a wall on its first uncertainty.

The audit reported two shipped runtimes. It is three: `heph mcp` builds the same
bare dispatcher at `server/src/hephaestus/mcp/app.py:281`.

### Reproduction

Build the production-shaped dispatcher the way `BridgeRuntime` does —
`ToolDispatcher(ProjectStore(...), cad=cad)` — and dispatch all nine as an
orchestrator principal: all nine refuse. Then
`grep -rn 'ToolDispatcher(' --include=*.py .` — every production call site
(`server/src/hephaestus/agent_bridge/app.py:365`,
`server/src/hephaestus/http/runtime.py:174` and its `reload_manifest` sibling,
`server/src/hephaestus/mcp/app.py:281`) passes only `cad=`; every site passing
`registry=`, `delegation=` or `snapshot_caller=` is under `tests/` or
`server/src/hephaestus/testing/`. `grep -rn 'DelegationService(' --include=*.py .`
returns twenty hits, all of them tests or test support.

Expected — architecture.md §4.2 describes the orchestrator as able to "create
parts and delegate through a constrained `delegate_part_agent` tool", present
tense; architecture.md §3.6 says skills are "loaded into context on demand by
`load_skill`" and that `search_parts_store` and `search_materials` query the
registries; agent/STAGE2_DIGEST.md §7 specifies the five registry tool result
shapes. INTERFACE.md §19 — the exhaustive register of what does not exist —
lists none of them.

### Root cause

`ToolDispatcher.__init__` at
`server/src/hephaestus/agent_bridge/dispatch.py:351` takes `registry`,
`delegation`, `delegation_runner`, `snapshot_caller` and `budget_ledger` as
optional keyword injections defaulting to `None`, and each family fails closed
when its injection is absent. No shipped code path supplies any of them. The
injections are exercised only by `tests/stage2/_g2.py:418`, a `BridgeRuntime`
**subclass** that supplies all four, and by
`server/src/hephaestus/testing/workflow_harness.py:125`.

The registry root resolver production would need already ships and is already
used: `RegistrySet.open` at `core/src/hephaestus/core/registry/_set.py:83` reads
the `[registries]` pins from the project manifest, falls back to the bundled
tree, and verifies the Merkle digest — and it is called by `heph registry`, by
`core/src/hephaestus/core/cli.py` and by
`server/src/hephaestus/agent_bridge/cad_ops/_dfm.py:124`. It has simply never
been called from an agent runtime.

History. `git log -S"needs the registry stack" --oneline` and
`-S"needs the delegation service"` each return one commit: 5329250
"feat(agent): Stage 2B product layer — full tool surface, thread-phase,
registries, bench", whose message says the tool audit "wired all 20 remaining
routes into core" and that registries shipped with "sandboxed generators, tamper
refusal, `heph registry` verbs". The core was wired and the CLI verbs were wired;
the agent runtimes were left taking the capabilities as optional injections that
only the gate harness supplies. `git log -S"ToolDispatcher(project_store, cad=cad)" -- server/src/hephaestus/http/runtime.py`
gives bb546fd: the serve runtime was written a month later and copied the same
bare construction.

Spec. **The code is wrong; the specs are correct and need no amendment.** The one
spec line worth correcting is agent/STAGE2_DIGEST.md's Stage-2 scope note, which
still lists `run_dfm`, `generate_drawing`, `generate_doc` and `nested_sheet` as
out of surface; all four shipped in Stage 6.

What a symptom-only patch would miss. Injecting a `RegistryOps` at each of the
four call sites lights up the five registry tools and misses: that the same four
sites are why `heph mcp` is broken too, so the patch gets copied a fifth time by
the next runtime; that `instance_store_part` still refuses without a probed
secure backend, which is a sandbox decision and not a registry one; that the
delegation third cannot be wired into `BridgeRuntime` at all until `py.*`
dispatch moves off the reader thread; that `DelegationService`'s default gate is
permissive, so delegation would go live accepting parts that do not exist; and
that the reason the gate never caught any of this is `tests/stage2/_g2.py`'s
subclass — leave that in place and the next capability is added the same way.

### Fix

Give the capability set one owner, construct it in one place every shipped
runtime calls, and delete the harness override so the gate exercises the shipped
construction.

1. New `wiring.py` in `server/src/hephaestus/agent_bridge/`, exporting
   `build_dispatcher(layout, store, project_store, cad, *, backend, edges)`. It
   resolves the registry with `RegistrySet.open` — the same call
   `server/src/hephaestus/agent_bridge/cad_ops/_dfm.py:124` makes — wraps it in
   `RegistryOps(registries, store, backend=backend)`, and builds a
   `DelegationService` with a real gate and the session edge store. A registry
   integrity error must **not** kill the runtime: catch it, pass `registry=None`,
   and record the reason, so the five tools keep their typed `not_implemented`
   instead of taking the process down.
2. `server/src/hephaestus/agent_bridge/dispatch.py:351` — add
   `bind_runtime(*, snapshot_caller=None, delegation_runner=None)` for the two
   capabilities that need a live sidecar. Keep the constructor signature
   unchanged so every existing test call site still compiles.
3. `server/src/hephaestus/agent_bridge/app.py:365` — replace the bare
   `ToolDispatcher(self._project, cad=self._cad)` with `build_dispatcher(...)`.
   **The second half of this step as first written is a regression, not a fix,
   and wave one reproduced it killing the sidecar.** It said to bind, after
   `Supervisor.start`, a snapshot caller adapting
   `Supervisor.call("query.snapshot", …)`. `query_snapshot` is not a
   `Supervisor.call` adapter's client: it is an **ordinary tool**, so it arrives
   over `py.tool_dispatch`, which `Supervisor._read_loop` runs INLINE on the
   single reader thread. A caller that turns around and issues `Supervisor.call`
   from there waits for a response only the thread it is blocking can deliver.
   Reproduced literally: the caller printed that it was running on
   `Thread-2 (_read_loop)`, `query.snapshot` never got a response, the watchdog
   killed the child as unresponsive, and the run died with `sidecar restarted` —
   strictly worse than the refusal it was meant to replace. This is the same
   reader-thread blocker the workflow plan already names for delegation, and
   `query_snapshot` belongs on that list beside it.

   What wave one shipped instead, and what this step now asks for: **wire the
   caller anyway, and guard it.** Binding it means the capability goes live with
   no edit at this site the moment py-dispatch moves off the reader thread. The
   guard is a module-private `threading.local` flag set for the whole of the
   `py.*` handler, plus a new `SnapshotAvailability` protocol on the dispatcher
   whose `unavailable()` the dispatcher asks **before** it prepares a render
   bundle. The model reads the same
   `{"status": "capability_error", "code": "capability_not_available"}` it read
   before, with an honest message naming the reason; nothing regresses and
   nothing is claimed that is not true. The invariant to carry forward, and to
   state wherever a new `py.*` method is added: **no `py.*` handler may call
   `Supervisor.call`.**
4. `server/src/hephaestus/http/runtime.py:174` and its `reload_manifest`
   sibling — the same call in both, so toggling a manifest flag cannot silently
   drop the registry.
5. `server/src/hephaestus/mcp/app.py:281` — the same call. MCP has no sidecar, so
   it never calls `bind_runtime`: `query_snapshot` keeps its honest
   `capability_not_available` and delegation keeps `not_implemented` there. Pin
   that asymmetry with a test so it stays deliberate.
6. `server/src/hephaestus/agent_bridge/app.py:1260` — route `py.delegate` into
   the dispatcher (this is B-3's routing step; the three lines already exist, in
   `tests/stage2/_g2.py`).
7. `tests/stage2/_g2.py:418` — **delete** the `delegation`, `registry` and
   `snapshot` construction from `G2Runtime.__init__`. Keep only the recording
   decorator and the scripted snapshot caller, passed through `bind_runtime`, so
   the gate proves the shipped path with a scripted vision child rather than a
   scripted dispatcher. This is the change that makes the gate mean something.
8. `server/src/hephaestus/testing/tools_fixture.py` — leave the optional
   injections for unit tests, and add a `make_wired_project` that calls
   `build_dispatcher`, so unit tests can assert the shipped construction without
   booting a sidecar.

Spec and doc lines to amend. None required. Optionally name
the new `wiring.py` in agent/DESIGN.md as the single
owner of the dispatcher's capability set, and record in INTERFACE.md §2.1 that
the serving process owns the registry set as well as the leases.

Compatibility. `RegistrySet.open` raises when a pinned tree no longer hashes to
its pin, so a project pinned against a moved registry would fail to open a
runtime that previously started — which is why the fix degrades to
`registry=None` rather than propagating. `instance_store_part` will run registry
generators under the secure sandbox for the first time in a shipped runtime; on a
host with no bubblewrap, `backend=None` keeps it at `capability_not_available`
rather than degrading to an unsandboxed run, which is the contract
`core/src/hephaestus/core/registry/_ops.py:57` already states. The delegation
half changes nothing observable until the reader-thread blocker is cleared: with
`delegation=` wired and `delegation_runner=` absent,
`server/src/hephaestus/agent_bridge/dispatch.py:1332` synthesizes "exactly ONE
durable terminal instead of inventing a completion", which is already better than
`not_implemented`.

### Tests to add

- New `test_dispatch_wiring.py` in `server/tests/` — `build_dispatcher` over a
  scaffolded project answers all five registry tools with real content
  (`list_skills` non-empty, `load_skill` returns provenance-delimited text) and
  constructs a delegation service, with no injections and no subclass.
- Same file — a project whose registry pin no longer matches yields a dispatcher
  with `registry=None` and a typed `not_implemented`, and does **not** raise out
  of `build_dispatcher`.
- `tests/stage2/test_g2_tool_surface_e2e.py` — extend the surface sweep so every
  one of the 57 declared tools is driven through the un-subclassed harness and
  asserted **not** to return `not_implemented`. This is the gate that would have
  caught B-2 on day one.
- `server/tests/test_mcp_unit_build.py` — the MCP dispatcher answers
  `list_skills` and refuses `delegate_part_agent` by name, pinning the deliberate
  asymmetry.
- A contract-level test that for each of the 57 tools the shipped
  `build_dispatcher` either routes it or refuses with a reason declared in that
  tool's committed schema under `schemas/tools/`.

### Notes

**Honest limit: `query_snapshot` has no shipped HTTP surface, so wiring it
proves less than it looks.** INTERFACE.md §2.3's route table exposes `read_part`,
`inspect_part`, `measure` and the keyed mutations; there is no
`POST /tools/query_snapshot`. Every real caller of this tool today is therefore a
model turn, and every real answer is the guarded refusal in step 3. Wave one's
off-thread proof drove the shared dispatcher directly — the code path an HTTP
tool route would take — which is evidence that the caller is correctly wired, not
that the tool is reachable. Do not read "`query_snapshot` works under serve" as
more than that, and do not count it among the nine tools this item restores until
either py-dispatch moves off the reader thread or a route exists.

## B-3 — `delegate_part_agent` fails its own result schema in both shipped runtimes

- **severity** high · **surface** agent-tools · **verdict** confirmed
- **effort** S · **risk** low · **lane** C

### Symptom

The model calls `delegate_part_agent` and reads
`result from delegate_part_agent failed its result schema` — a proxy internal
error with no reason token, no `status`, and nothing to discriminate on. The
delegation never happened and the model cannot tell why. Secondarily the reason
chosen is a lie: `no_run_slot` names a slot that was never contended.

### Reproduction

Validate the shipped payload against both committed validators.

```
{"status": "rejected", "reason": "no_run_slot", "part_session_id": null}
```

TypeBox (`agent/src/tools/schema.gen.ts`): fails, "Expected union value".
JSON Schema (`schemas/tools/delegate_part_agent.schema.json`): fails, "is not
valid under any of the given schemas". The same object with the key **omitted**
passes both; with a real session id it passes both. End to end over a real
sidecar and a real serve, the tool text is
`result from delegate_part_agent failed its result schema`.

Expected — `part_session_id` is declared optional on the rejected variant:
`contract/src/hephaestus/contract/tools_decl.py:1483` lists `part_session_id`
among the properties with `required` of `["status", "reason"]`. Omitting it is
correct and `null` is not. tool_schema.md's `delegate_part_agent` entry states
that a rejection before admission has no child run or ref.

### Root cause

Two shipped sites emit `part_session_id: None` on the rejected variant:
`server/src/hephaestus/agent_bridge/app.py:1260`, where `_on_py_request` answers
`py.delegate` with a hardcoded rejection, and
`server/src/hephaestus/agent_bridge/workflows.py:483`, where the busy path emits
the identical dict. The model-visible tool routes to `py.delegate` and **not**
`py.tool_dispatch` — `agent/src/tools/proxy.ts:330` special-cases it — so the
shipped `heph agent` and `heph serve --web` never reach the dispatcher's real
`_delegate` at all; they hit the stub unconditionally. The generator renders the
declared optional property as `Type.Optional(Type.String())`, which means "may be
absent"; a present `null` is a type violation. Python's `None` serializes to JSON
`null`, so the two sites emit exactly the one value the schema forbids.

History. `git blame -L 1256,1266 -- server/src/hephaestus/agent_bridge/app.py`
gives 7b9c89b "feat(agent): Stage 2A runtime core — bridge, sidecar, tool
codegen, heph agent". The lines carry their own explanation: "Delegation is owned
by the delegation coordinator; the runtime-core slice rejects rather than
fabricating a child." It is a Stage-2A placeholder. Stage 2B — 5329250, the very
next day — built `DelegationService`, `SessionDelegationRunner` and the whole
thread-phase layer, and never came back to replace it. It survived because
`tests/stage2/_g2.py` overrides `_on_py_request` with the production code that is
missing, so no gate test ever sees the stub; and because
`server/tests/test_workflows.py:213` asserts the invalid payload as a raw Python
dict, **pinning** it, with no cross-validation against the committed schema.

Spec. **The code is wrong on both counts** — an illegal `null` and a reason that
misdescribes what happened — and the spec needs no change.
`tests/stage2/test_g2_capabilities.py:41` already contains the validator that
would have caught this (`jsonschema.validate(result, _result_schema(tool))`
against the committed schema); it is applied to two tools.

What a symptom-only patch would miss. Deleting the key makes the payload valid
and leaves the model reading a permanent, false `rejected: no_run_slot` for a
capability that is merely unwired. It also leaves the real hole: no test anywhere
validates a **shipped** tool reply against its committed schema, so the next
hand-built result payload drifts the same way — and it leaves
`server/tests/test_workflows.py:213` still pinning a wrong shape.

### Fix

Three changes, smallest first, so a partial landing is still an improvement.

1. `server/src/hephaestus/agent_bridge/workflows.py:483` — drop the null key.
   The reason is genuinely `no_run_slot` there; only the key is wrong.
2. `server/tests/test_workflows.py:213` — update the assertion to the corrected
   shape **and** add `jsonschema.validate` against
   `schemas/tools/delegate_part_agent.schema.json`, so the pin is against the
   committed contract rather than a hand-typed dict.
3. `server/src/hephaestus/agent_bridge/app.py:1260` — replace the stub with a
   `_handle_delegate` that resolves the principal from the invocation's session
   id, builds the tool arguments and dispatches under the parent run id. That
   method already exists, in `tests/stage2/_g2.py`; lift it into
   `BridgeRuntime` verbatim and delete the harness override, so the gate stops
   testing code that does not ship.

Spec and doc lines to amend. None. tool_schema.md,
agent/STAGE2_DIGEST.md and `contract/src/hephaestus/contract/tools_decl.py:1483`
already say the right thing.

Compatibility. Omitting an optional key is wire-compatible in both directions:
both validators accept absence, and the sidecar's workflow reader reads the
reason through an optional-string helper. No consumer reads `part_session_id` off
a rejected result. Step 3 makes `py.delegate` start doing real work, which is
B-2's blast radius and inherits B-2's dependency on the reader-thread fix for
`delivery="prompt"`.

### Tests to add

- New `test_agent_bridge_delegate.py` in `server/tests/` — call `_on_py_request` with
  `py.delegate` against a project with no delegation service and assert the reply
  validates against the committed schema. This fails today.
- A contract-level parity test over every hand-built tool-result payload emitted
  outside `ToolDispatcher` — the `py.delegate` reply, the workflow rejections,
  the dispatcher's `capability_error` literals — validated against its committed
  schema. Generalizes `tests/stage2/test_g2_capabilities.py:41` from two tools to
  all of them.
- `agent/test/tools_proxy.test.ts` — feeding `{status, reason, part_session_id: null}`
  through the proxy is rejected, pinning the TypeBox half so a future contract
  edit that widens the type is a deliberate act.
- `tests/stage2/test_delegation_bridge.py` — assert the model-visible tool
  **text** on the happy path. Today it asserts only that the run completed and
  never looks at the tool result, which is why the delegation gate is green while
  the tool is broken.

## B-4 — Every `heph part create` template is unbuildable: the table opens with a forbidden import

- **severity** critical · **surface** cli · **verdict** confirmed
- **effort** M · **risk** medium · **lane** A

### Symptom

All four templates start with `from build123d import *`, which the executor
refuses by design, so every scaffolded part fails to build on line 1. The
documented quickstart — create a part, then build it — cannot work as written.
`from_store` is byte-identical to `blank`.

### Reproduction

```
heph init proj && cd proj
for t in blank solid sheet from_store; do heph part create p_$t --template $t; heph build p_$t; done
```

Observed, for each: `FAILED — SandboxDeniedError at line 1, col 0 /
'__import__' is not available in part scripts; the injected namespace is the
entire API surface (script contract §2) / > 1 | from build123d import *`,
exit 1. `heph part create p_blank` and `p_from_store` produce the same content
hash — identical bytes.

Expected — a created part builds. docs/cli.md's authoring quickstart shows
`heph part create` followed by `heph build` publishing.

### Root cause

`core/src/hephaestus/core/part_templates.py:16` defines all four values as
`"from build123d import *\n\n\nwith BuildPart() as part:\n    …"`. The executor's
restricted builtins map every denied name through `_denier` at
`core/src/hephaestus/core/executor/namespace.py:157`, which raises
`SandboxDeniedError` for `__import__`. The templates therefore encode exactly the
one statement the execution model forbids.

Two further defects ride along. The templates use the builder-context idiom
`with BuildPart() as part:`, which **shadows the injected `part` handle**, while
the contract's output protocol is assignment to `part.geometry` — so even with
the import line removed, `blank` and `solid` would publish no geometry. And
`from_store` is a verbatim copy of `blank`, so a template whose name promises a
store-seeded scaffold delivers an empty one.

History. `git log -S'BLANK_TEMPLATES' --oneline` gives 7b9c89b
"feat(agent): Stage 2A runtime core — bridge, sidecar, tool codegen, heph agent"
for the dispatcher's original table, then 8709f21
"CLI: agent-shaped heph part/script/params/prompt verbs", which moved the table
into `core/src/hephaestus/core/part_templates.py` so, in the module docstring's
words, "the two callers cannot drift". The move preserved the broken bytes
verbatim and, by sharing them, gave the same broken scaffold to the `create_part`
tool as well. The same commit family wrote the example part in
`core/src/hephaestus/core/cli_init.py:50`, which is **correct** — bare
`Box(p.width, 20.0, 6.0)`, a label, `part.geometry = plate`, no import — so a
working reference existed in the tree the whole time.

Spec. **The code is wrong and the spec is unambiguous.** script_contract.md §1
states "There are no imports in part scripts; the injected namespace is the
entire API surface"; §2 describes build123d as **pre-injected**, not as something
a script may import, and states that `open` and `__import__` are absent and that
attempting them is a build error. docs/cli.md is also wrong, because it shows the
broken flow succeeding.

What a symptom-only patch would miss. Deleting the import line leaves
`with BuildPart() as part: pass`, which shadows the injected handle and still
publishes nothing, and leaves `from_store` a duplicate. The real gap is that no
test ever **builds** a template: `core/tests/test_cli_authoring.py:94` asserts
only that the created file is byte-identical to the table it came from, which is
true of any bytes at all.

### Fix

Rewrite the four templates against the actual contract, modelled on the
known-good example part, and pin them with a build test rather than a
byte-equality test.

1. `core/src/hephaestus/core/part_templates.py:16` — replace all four values.
   `blank`: an empty `PARAMS` map, a commented hint and
   `part.geometry = Box(10, 10, 10)`. `solid`: a bounded `Param`, a labelled
   `Box`, assigned to `part.geometry`. `sheet`: a rectangle extruded into a real
   sheet solid with a label. `from_store`: a distinct scaffold that names a store
   part and assigns it. **No value may contain the token `import`.**
2. `core/src/hephaestus/core/part_templates.py` — extend the module docstring
   with the invariant: every value here builds under the part-script contract,
   and name the test that enforces it.
3. `core/src/hephaestus/core/cli_init.py:50` — no change; optionally re-express
   the example part as the `solid` template so there is one scaffold, not two.
4. `docs/cli.md` — re-record the authoring quickstart from a real run of the
   fixed templates. The shown `--json` content hashes change.

Spec and doc lines to amend. docs/cli.md's quickstart transcript and the
`heph part create` example are re-recorded. tool_schema.md's `create_part` entry
is unchanged if `from_store` keeps its name. Add one line to script_contract.md
§2 (or docs/conventions.md) pointing at
`core/src/hephaestus/core/part_templates.py` as the canonical minimal script, so
the next author copies the right thing.

Compatibility. **Breaking for content hashes**: `create_part`'s `initial_script`
and `content_hash` change for every template. `core/tests/test_cli_authoring.py:94`
compares against the table itself, so it keeps passing. Any recorded bench
fixture or golden transcript embedding the current digests must be re-recorded —
grep for them before landing.

### Tests to add

- `core/tests/test_cli_authoring.py` — a parametrized `test_every_template_builds`
  over `TEMPLATE_NAMES`: `heph part create`, then a real `heph build` in a
  temporary project, asserting `status ok` and a non-null artifact ref. **The
  absence of this test is the actual defect.**
- `core/tests/test_executor_namespace.py` — no `PART_TEMPLATES` value contains
  the substring `import`. Cheap, fast, and it fails loudly if the line returns.
- `core/tests/test_cli_authoring.py` — `PART_TEMPLATES["from_store"]` differs
  from `PART_TEMPLATES["blank"]`.
- A docs-example runner that executes the docs/cli.md quickstart end to end. The
  existing docs test asserts that every verb **appears** in the documentation and
  never runs an example, which is why four documented invocations are wrong.

## B-5 — `GET /parts/{part}/build` reports a superseded build as current

- **severity** high · **surface** http · **verdict** confirmed
- **effort** L · **risk** medium · **lane** F · **depends on** B-1 (shared file),
  B-6 (shared file), B-7 (shared file)

### Symptom

After editing a part's script with no rebuild, the build route still answers
`{"status": "ok", "current": true, "artifact_ref": <the old artifact>}`. The
workspace header chip renders that as the literal words **"up to date"**, and the
model's context envelope prints the same stale artifact ref and geometry count
under "build status: ok". `current` is a boolean stamped once at publication and
never recomputed by any reader.

### Reproduction

Against the real application and the real store: build a part; read its script
hash; `PUT` the script back with one appended comment line and that expected
hash; then re-read the build route with no rebuild in between.

Observed: the second read is byte-identical to the first —
`{"status": "ok", "current": true, "artifact_ref": "artifact:build:sha256:5e4a…"}`,
same geometry count, same bounding box — while the script hash has moved. The
document carries neither hash, so no client can detect the drift either.

Expected: either `current: false`, or — better, and what the spec's own chip
vocabulary asks for — `current` retained as publication state plus a separately
computed freshness fact naming the changed input, so the header can print
`stale`. INTERFACE.md §4.1 lists `stale` in the chip's closed vocabulary.

### Root cause

`current` is set exactly once, by the pointer flip:
`core/src/hephaestus/core/project_store/publication.py:589` is
`published = replace(build.result, current=True)`. It is serialized into the
bundle and read back verbatim by the publisher's `current_result`, by
`server/src/hephaestus/agent_bridge/cad_ops/_build.py:300`, and by
`server/src/hephaestus/http/projections.py:97`, which is a bare
`"current": result.current`. No reader on any path recomputes it.

The engine owns the exact comparison that would. `Publisher._revalidate` in
`core/src/hephaestus/core/project_store/publication.py` hashes the live script
bytes, toolchain, imports and consumed-`hc` projection against the recorded input
hashes — but it runs only inside `publish_build`, under locks, never on a read.
Compounding it, `build_projection` does not project the input hashes at all, so
the client cannot derive freshness either, and `web/src/api/types.ts` has no field
for it. The engine's other staleness notion, the projection's `stale` set, tracks
only `hc`-value and import changes, so a script edit marks nothing stale and
`heph build --stale` would not rebuild this part either.

Four readers repeat the claim: `server/src/hephaestus/http/projections.py:97`,
`web/src/components/BuildStateChip.tsx:50` (which maps `current === true` to
`copy.buildState.current`, "up to date", at `web/src/copy.ts:172`),
`server/src/hephaestus/http/context.py:418` for the model, and
`core/src/hephaestus/core/cli_authoring.py:194` for `heph part show`.

History. `current` has been a persisted publication boolean since the engine
existed (b0715f6). The route was written in bb546fd as a one-line pass-through —
freshness was never in scope — and
`git log -L '/async def get_build/,+12:server/src/hephaestus/http/app.py'` shows
only two commits ever touching it, the second being 3e5a9f1
"engine: project statement checkpoints onto GET /build". The web side named the
gap rather than filling it: `web/src/components/BuildStateChip.tsx` carries a
comment saying `stale` "has no producer in this build and is not faked".

Spec. **Both are wrong, in different directions.** architecture.md §3.5 defines
`current` correctly as publication state, so the engine is consistent with its
own spec. INTERFACE.md §2.3 then lists `current` as a plain projection field with
no freshness gloss, while INTERFACE.md §4.1 requires the header chip to render a
closed vocabulary including `stale` — a normative chip state with no server field
behind it. The only place `stale` is defined is INTERFACE.md §5.5, and there it
is an **in-flight rebuild** viewport state, which is why the chip component
concluded there was nothing to render. So: the code is wrong to let `current` be
read as freshness on a surface that says "up to date", and the spec is wrong to
name a chip state with one producer defined and none for the commoner second one.

What a symptom-only patch would miss. Flipping `current` to false in `get_build`
when the script moved would violate architecture.md's definition, break the
existing "current wins over a later failure" test, leave the model still lied to
(the context envelope is built from `current_build` directly), leave `heph part
show` printing `current=True`, and leave the header with no way to say `stale` —
it maps `current: false` to the word **"preview"**, so a freshly-edited part would
read as a preview build, a different and equally false claim.

### Fix

Keep `current` as publication state. Add a read-time freshness fact computed from
the same hashes `_revalidate` compares, serve it as its own field, and give the
orphaned `stale` chip state its producer. The comparison is reconstructible from
a pure read because the published bundle already carries the consumed-`hc` map
beside the recorded input hashes.

1. `core/src/hephaestus/core/project_store/publication.py` — extract the hash
   comparison out of `Publisher._revalidate` into a module-level
   `input_mismatches(...) -> tuple[str, ...]`; `_revalidate` becomes a thin caller
   so publication behaviour is byte-identical.
2. Same file — add `Publisher.freshness(part)` beside `current_result`: read the
   current bundle, call `input_mismatches` with its consumed-`hc` map and the
   result's input hashes, return whether it is fresh and which inputs changed;
   `None` when there is no current bundle. A changed `PARAMS` block is a changed
   script and is already covered by the script leg.
3. `server/src/hephaestus/agent_bridge/cad_ops/_build.py:300` — add
   `build_freshness(name)` delegating to the publisher, documented like its two
   neighbours as lock-free and never a rebuild.
4. `server/src/hephaestus/http/projections.py:60` — `build_projection` takes the
   freshness and emits `"stale": bool` and `"stale_inputs": list[str]`, as a
   named empty list when fresh and in the `not_built` branch, per the module's own
   rule that an empty answer is a named empty list rather than an omitted key.
5. `server/src/hephaestus/http/app.py` — `get_build` computes the freshness in
   the same worker thread as the record and passes it in.
6. `server/src/hephaestus/http/context.py:418` — when stale, say so in the block:
   name the changed inputs, so the model stops being told a superseded artifact
   is the build.
7. `web/src/api/types.ts` — add the two optional fields.
8. `web/src/components/BuildStateChip.tsx:50` — `buildState()` gains
   `if (build.status === "ok" && build.stale) return "stale";` before the
   current/preview line; replace the "no producer" comment with the field it now
   reads; add a fact attribution beside the existing `build.current` one so the
   e2e can compare the chip against the JSON.
9. `core/src/hephaestus/core/cli_authoring.py:194` — `heph part show` prints and
   emits `stale` beside `current`, so INTERFACE.md's "CLI counterpart" claim stays
   true.

While the file is open, close the sibling half of the same route: `get_build`
prefers a current success over a **newer failed** build and discards the loser, so
a part that has ever built successfully can never surface a later failure through
this route, and `BuildDocument.error` is unreachable on a read. Keep the
precedence — it is deliberate, and geometry count is bound to the current build —
and add a `last_failure` member carrying the failed record's error and
checkpoints, recognised as newer when its recorded script hash differs from the
current build's.

Spec and doc lines to amend. INTERFACE.md §2.3's build-projection field list
gains `stale`, `stale_inputs` and `last_failure?`, and its "CLI counterpart"
sentence is corrected — it is already false for a first-fail part.
INTERFACE.md §5.5's 2026-09-01 amendment defines `stale` only as the in-flight
viewport state; add the second producer and say which one the header chip
renders. architecture.md §3.5 gains one sentence: `current` is publication state,
and read routes serve freshness as a separately recomputed fact, so `current` can
never be read as "up to date". `web/src/copy.ts` gains a `buildState.stale`
title naming the changed inputs.

Compatibility. Additive JSON keys only; no existing field changes meaning.
Bundles written before the consumed-`hc` map existed make `freshness()` return
`None`, the keys are omitted, and the chip falls back to today's four-state
mapping. One extra script read and hash per build request — negligible beside the
route set's existing cost, but it belongs inside the existing worker-thread hop
because it is on the part-switch path. The context envelope's goldens are
byte-compared, so `scripts/rebaseline_context_goldens.py` must be run and the
diff reviewed rather than rubber-stamped.

### Tests to add

- `server/tests/test_http_reads.py` — build, `PUT` a script with one appended
  comment, read the build route: `current is True` **and** `stale is True` **and**
  `stale_inputs == ["script"]`. This is the reproduction, turned into a
  regression.
- Same file — the negative half: a `PUT` that rewrites the identical bytes leaves
  `stale is False`.
- Same file — the `hc` leg: a project-parameter or globals edit on a name the
  part consumes yields `stale_inputs == ["hc_dependencies"]`, proving the read
  path uses the same projection `_revalidate` does.
- Same file — with a newer failure recorded, the response still reports
  `status: "ok"` (the precedence holds) **and** carries `last_failure`; with a
  failure recorded before the current success, `last_failure` is absent.
- `core/tests` — the `input_mismatches` extraction is behaviour-preserving: every
  existing raced-publication test passes unmodified.
- `web/test` — the chip prints the stale copy for `{status: "ok", current: true,
  stale: true}`, and the "no bare true/false" fact rule extends to the new field.
- A CLI/HTTP parity test for the three states: not built, first-fail, and
  success-then-fail.

## B-6 — 404, 405 and every unmapped exception leave the API without an error envelope

- **severity** high · **surface** http · **verdict** confirmed
- **effort** M · **risk** low · **lane** D

### Symptom

A route miss answers `404 Not Found` as `text/plain`. A wrong method answers
`405 Method Not Allowed` as `text/plain`. Any exception the refusal mapper does
not map answers `500 Internal Server Error` as `text/plain`. None carries
`status`, `reason` or `message`, so the web client turns all three into a refusal
with no name — `web/src/api/client.ts:93` falls through to
`new WorkspaceError(status, "transport_error", ...)`. That is the exact condition
INTERFACE.md §2.4's 2026-09-03 amendment exists to make impossible.

### Reproduction

With a valid bearer: `GET /api/v1/nosuchroute` returns 404
`text/plain; charset=utf-8`, body `Not Found`. `POST /api/v1/project` (only `GET`
is served) returns 405 `text/plain`, body `Method Not Allowed`. Patching a route
dependency to raise `OSError` and driving it with server exceptions suppressed
returns 500 `text/plain`, body `Internal Server Error` — identical for `OSError`
and `RuntimeError`. Reproduced identically under a real listener.

Expected — INTERFACE.md §2.4: the body is always
`{"status": "error", "reason": <machine reason>, "message": <human>, ...data}`,
and the HTTP status is a coarse envelope over the reason and never replaces it.
No exemption is granted for the router's own refusals or for a server fault.

### Root cause

`build_app` returns `Starlette(routes=routes)` at
`server/src/hephaestus/http/app.py:1650` with no `exception_handlers` argument.
Starlette's default handler for an HTTP exception is a plain-text response, and
its server-error middleware with no handler emits plain-text
`Internal Server Error`. The per-endpoint guard that maps §2.4 correctly is
per-**endpoint**: 404 and 405 are raised by the router before any endpoint runs,
so the guard never sees them. For the 500 path, `refusal_for` deliberately ends
in a bare `raise exc` at `server/src/hephaestus/http/errors.py:515` for anything
unmapped — a mapper that guessed would turn a bug into a plausible refusal — and
the endpoint guard re-raises it into that same defaultless middleware. There is
no `internal_error` reason anywhere in the repository.

History. Introduced whole in bb546fd
"feat(stage4): server/http + the read-only web workspace — G4 19/20, browser gate
pinned-image-deferred", which built the application with no exception handlers
from the first commit. e3ef904
"fix(server): re-adopt a session the sidecar forgot, and refuse by name instead
of an unnamed 500" closed the **supervisor-error** instance of this hole and
explicitly left the general case: it added the re-raise rather than a 500
handler. So the class was diagnosed a day before this audit and one member of it
was fixed.

Spec. **The code violates the governing clause and the spec is also incomplete.**
INTERFACE.md §2.4's error table has no row for a route miss, a wrong method, or a
server fault, and names no `internal_error` reason — so a correct implementation
has no reason string to use.

What a symptom-only patch would miss. Adding only an HTTP-exception handler fixes
404 and 405 and leaves the 500, which is the more dangerous half because that is
where an operator most needs a name. Adding only a 500 handler leaves the
router's refusals. Special-casing either inside the endpoint guard cannot work at
all, because neither condition reaches an endpoint. The root-cause fix is a
decision at the application boundary — every response this process emits carries
the envelope — which is also what makes the static-bundle sibling (a missing
`favicon.ico` answering 500 with a traceback) visible as the same defect rather
than a separate surprise.

### Fix

Register exception handlers on the Starlette application, at the one boundary
that sees every response, leaving `refusal_for`'s re-raise semantics untouched.

1. `server/src/hephaestus/http/errors.py` — add three rows to the reason/status
   table: `unknown_route: 404`, `method_not_allowed: 405`,
   `internal_error: 500`, each with the grounded comment the neighbouring rows
   carry.
2. Same file — add one envelope-response helper, or reuse the existing error-body
   builder. No new module.
3. `server/src/hephaestus/http/app.py` — add an HTTP-exception handler mapping a
   Starlette HTTP exception to a JSON envelope at its own status, with
   `method_not_allowed` for 405 and `unknown_route` for 404. It **must** preserve
   the `Allow` header Starlette attaches to a 405, or the fix regresses a correct
   behaviour while repairing an incorrect one.
4. Same file — add a server-error handler returning
   `{"status": "error", "reason": "internal_error", "message": <fixed sentence>,
   "incident": <short id>}` at 500. The message must be **fixed** text plus a
   correlation id, never `str(exc)`: this path is reached by exceptions nobody has
   classified and therefore nobody has redacted. Log the incident id with the
   traceback so an operator can join the two.
5. `server/src/hephaestus/http/app.py:1650` — pass both handlers to `Starlette`.
   Starlette's server-error middleware runs the handler and then re-raises, so
   uvicorn still logs the traceback and the test client's default re-raise
   behaviour is unchanged.

While the application boundary is open, close the sibling: the static bundle is
composed **around** the API application as a bare ASGI callable, so a missing
file raises an HTTP exception with no middleware between it and the server —
every page load logs a traceback and answers 500 for `/favicon.ico`. Wrap the
static branch in exception middleware (do **not** mount it inside `build_app`;
the composition-around is deliberate, so the closed route-table assertion stays
strong), and record the policy explicitly: a path the bundle does not contain is
a 404, not a single-page fallback, because the client keeps its navigation state
in the URL fragment.

Spec and doc lines to amend. INTERFACE.md §2.4's table gains three rows: no route
matches → 404 `unknown_route`; route matched, method not served → 405
`method_not_allowed` with `Allow`; an exception no branch maps → 500
`internal_error` with a correlation id and a fixed message. Add one paragraph
under the table stating that the envelope covers the **router's** own refusals
and the server-fault path, and that `internal_error` is the one reason in the
table that is not the engine's — it names the absence of an engine condition,
which is why its message is fixed. INTERFACE.md §3 gains one line: a path the
bundle does not contain answers 404.

Compatibility. No test in the server or web suites asserts a plain-text body
(grepped: zero hits for the three strings). The refusal-mapper test that pins the
deliberate re-raise is unaffected. `web/src/api/client.ts` needs no change — it
already prefers a parsed envelope — but its `transport_error` fallback becomes
genuinely unreachable for this server, which is worth a comment there.

### Tests to add

- `server/tests/test_http_errors.py` — a route miss carries the envelope: 404,
  `application/json`, `reason == "unknown_route"`.
- Same file — a wrong method carries the envelope and keeps `Allow`: 405,
  `reason == "method_not_allowed"`, `Allow` names `GET`.
- Same file — an unmapped exception reaches the client as `internal_error` with
  an incident id, and the exception's own text does **not** appear in the body.
- Same file — extend the existing row-by-row table test with the three new rows.
- `server/tests/test_http_boundary.py` — every response the application can emit
  for an unrouted path is `application/json`: a standing guard so a future
  middleware addition cannot silently undo this.
- A static-bundle test: a missing bundle file is a 404 and not a server error,
  while `/` and `/index.html` still return the bundle's HTML.

## B-7 — View cube: azimuth is applied as a screen roll, and edge/corner targets are full-size slabs

- **severity** high · **surface** web · **verdict** confirmed
- **effort** L · **risk** medium · **lane** G

### Symptom

The view cube draws as an unreadable diamond that overflows its 72×72 scene box
into the plate's padding and border, with edge and corner plates painted opaquely
over the faces. Clicking cannot reach most cameras. Measured at 1600×1000 on the
default `iso` view by walking `elementFromPoint` across the plate: fifteen buttons
exist, **ten are reachable**, and `Back`, `Left`, `Bottom`, `Left / Top` and
`Left / Bottom` collect zero pixels. `Front` swallows 2646 px of the 90×98 plate —
the whole lower half. The `iso` corner's own word clips (client width 14,
scroll width 18).

### Reproduction

Open a part, wait for the canvas, then bucket every pixel of the cube's bounding
box by the button under it. Sweeping all fifteen named views: **`Back` is
unreachable at every one of them**; at the five zero-elevation standard views only
six of fifteen targets are reachable and the reachable set is **identical** across
azimuth 0, 90, 180 and 270 (`Front` collects 3374/3384/3376/3373 px) — azimuth
changes nothing about which face is toward the viewer. `Left / Top` and
`Left / Bottom` are unreachable at all fifteen.

Expected — INTERFACE.md §5.5's 2026-09-03 amendment: "faces, edges, and corners
are selectable"; and §5.5's older clause that a view named in the UI is a view
`heph render` can reproduce.

### Root cause

Three independent mechanisms, all in one component.

**Frame mismatch.** `web/src/components/stage/viewport/ViewCube.tsx:146` sets the
parent transform to `rotateX(${-elevation}deg) rotateZ(${-azimuth}deg)`, while
the children are placed in the CSS Y-up frame with `rotateY`/`rotateX`. `rotateZ`
is a rotation in the **screen plane** — a roll — so azimuth never turns the cube
on its vertical axis. Front's normal is invariant under `rotateZ`, so `Front`
faces the viewer at every azimuth and `Back` is culled by
`backface-visibility: hidden` at every azimuth. Mapping the eye direction into the
child frame under the current transform gives a screen normal of `[0,-1,0]` at
`iso` and `[1,0,0]` at `+X` — never `[0,0,1]`. The corrected chain is
`rotateX(${-elevation}deg) rotateY(${-(azimuth + 90)}deg)`, which returns
`[0,0,1]` for all seven standard views.

**Slab geometry.** In `web/src/components/stage/viewport/ViewCube.module.css` the
faces, edges and corners all take `position: absolute; inset: 0` and are then
sized: faces 56×56, edges 14×56 slabs **through the cube's middle**, corners 16×16
at a 20px margin. Those are not cube edges and corners; they are plates through
the body's interior. An edge slab intersects the front and right faces, so hit
testing resolves by paint order inside the one `preserve-3d` stacking context and
`Front / Top` collects 516 px over `Top`'s 739. This is independent of the frame
mismatch: with the corrected parent transform applied, the six **faces** become
correct at every named view and **nine of fifteen targets are still unreachable**
at `iso`.

**Names and addressing.** The `view` strings for edges and corners are
hand-written and several are wrong — the button labelled "Right / Top" carries
`az0_el35`, which names a camera above the `+X` **face**, not a corner.
`web/src/viewport/cameras.ts:122` already owns `nameForDirection`, which
canonicalises the `+++` corner to `iso`; the cube re-implements the naming rule
beside it. And `data-cube-hit` carries the **kind** while `data-view` is minted on
only two of fifteen buttons, so no test can address `Left` except by its localised
accessible name. There are only four of twelve edges and five of eight corners.

History. Introduced whole in the commit whose subject is
"web: well continuity + markdown, typable composer, view cube (#116)" and whose
body says "Smith-style view cube" and "Closes continuity/markdown/composer/cube
operator defects from the 2026-09-02 well drive". `git log -S'preserve-3d' -- web/`
and `-S'data-cube-hit' -- web/` both return only that commit, which also wrote
INTERFACE.md §5.5's amendment and replaced seven labelled axis buttons with the
cube. The same commit rewrote `web/test/viewportChrome.test.tsx`, but the new
assertions only count boxes, check `tabindex` and accessible names, assert two
`data-view` values exist, and read the stylesheet as text. **Not one assertion is
about geometry or reachability**, which is why a cube reaching ten of fifteen
targets shipped green.

Spec. **Both are wrong.** The code violates the selectability clause and the
reproducibility clause. The spec is under-specified: it says "faces, edges, and
corners" without a count, so a build with four of twelve edges and five of eight
corners can claim compliance.

What a symptom-only patch would miss. Patching only the parent transform — the
one-line fix the mechanism most invites — makes the six faces correct and still
leaves nine of fifteen targets unreachable, because the slabs are a separate
defect. Adding the missing edges and corners without fixing the transform makes
the cube denser and no more usable. Patching z-order or `pointer-events` hides the
paint-order symptom while the cube still shows the wrong faces. And none of the
three addresses the hand-written names, so a user clicking "Right / Top" still
gets a camera `heph render` reproduces as something else — an honesty failure,
not a layout one.

### Fix

Replace the `preserve-3d` cube with a **projected 2D hit model**, so the drawn
cube and the hit regions are one computation by construction.

1. New `cubeTargets.ts` in `web/src/viewport/`, pure and unit-testable with no DOM:
   `CUBE_TARGETS` is all 26 directions in `{-1,0,1}` cubed minus the origin,
   normalised, with kind by the count of non-zero components — six faces, twelve
   edges, eight corners. `targetName(dir)` delegates to `nameForDirection` from
   `web/src/viewport/cameras.ts:122`, so the vocabulary has one implementation and
   the `+++` corner comes back as `iso` for free. `projectTargets(azimuth, elevation)`
   builds the camera basis exactly as `web/src/viewport/cameras.ts` already
   defines it and returns, per target, screen `x`, screen `y` and depth, culling
   anything facing away.
2. `web/src/components/stage/viewport/ViewCube.tsx` — delete the hand-written
   target table; render one absolutely-positioned button per **visible** target at
   its projected position, sized by kind, ordered by depth. Draw the cube's
   silhouette and face quads as an inline SVG **under** the buttons from the same
   projection, so the picture is the hit map. Face words render inside face
   buttons; edge and corner buttons carry an accessible name only, which also
   retires the `iso` glyph that clips at 14px.
3. `web/src/components/stage/viewport/ViewCube.module.css` — delete the
   perspective, the `preserve-3d` transform style, the `inset: 0` and
   `backface-visibility` on the shared rule, and the margin-based edge/corner
   placement. The body becomes a relatively-positioned 72×72 box with
   `overflow: hidden`, which also stops the cube painting over the plate's border.
   Keep the existing token pairing for the current-target state verbatim, or the
   chrome test's stylesheet assertions fail for unrelated reasons.
4. Addressing — mint `data-view` on **every** button, keep `data-cube-hit` for the
   kind, and add a key carrying the direction triple. The click handler still
   writes the view into workspace state, unchanged.
5. `web/src/copy.ts` — the `iso` string is no longer drawn as a glyph; keep the key
   for the corner's accessible name and say so in the comment. No new strings are
   needed: the existing face words already compose every edge and corner label.

If a 3D cube is required for aesthetic reasons, the minimum correct version is the
corrected parent transform **plus** edge and corner plates translated to the
cube's actual edges and corners rather than `inset: 0` slabs. That is recorded and
deliberately not recommended: overlapping siblings in a `preserve-3d` subtree
still hit-test by paint order, which is the class of bug being retired.

Spec and doc lines to amend. INTERFACE.md §5.5's 2026-09-03 amendment gains: the
inventory (six faces, twelve edges, eight corners — twenty-six targets, and the
set is closed); the derivation rule (every target's `view` comes from its
direction through the shared camera vocabulary, so the `+++` corner **is** `iso`);
the addressing rule (every target carries `data-view`); and the negative half —
a target that is drawn is hittable, and a target that is not drawn is not; the
cube's hit regions are its projection, never a paint-order accident.

Compatibility. The `view` values written to the URL change for the edge and corner
targets, but the current hand-written ones were never correct cube geometry, and
`web/src/viewport/cameras.ts` still **parses** every one of them, so an old
bookmark keeps resolving to a camera. `data-view="front"` and `data-view="iso"`
survive: the `-Y` face must be given the literal name `front`, which the camera
module already documents as one camera with two names.

### Tests to add

- New `cubeTargets.test.ts` under `web/test/` — 26 targets, six/twelve/eight by
  kind; every `targetName` round-trips through the camera module's angle parser
  to within 1° of its own direction; the `+++` corner is exactly `iso`; the `-Y`
  face is exactly `front`; no two targets share a name.
- Same file — for each standard view and for `iso`, the visible set is exactly one
  face at each axis view and three at `iso`, and the target whose direction equals
  the eye direction has maximum depth.
- `web/test/viewportChrome.test.tsx` — every button carries a `data-view`; the set
  of `data-view` values equals what the projection says is visible at the rendered
  angle; `data-cube-hit` is drawn only from the three kinds.
- `web/e2e/viewport.spec.ts` — **the reachability probe as a gate**: at `iso` and
  at each standard view, walk `elementFromPoint` over the cube and assert every
  button with a non-zero box collects at least one pixel, and that no button
  collects pixels belonging to another target's drawn quad. This is the assertion
  whose absence let the defect ship.
- Same file — clicking the `-X`, `+Y` and `-Z` targets moves the URL's `view` to
  each. All three are unclickable today, so this test fails before the fix. Wave
  one landed this as a **navigation sequence**, not three direct clicks, for the
  reason in the Notes below.

### Notes

**§5.5 behaviour change, and it is deliberate: only viewer-facing cells are drawn
and hittable, so `data-view="front"` is camera-dependent.** The fix's negative
half — a target that is drawn is hittable, and a target that is not drawn is not
— means a face turned away from the viewer is not painted, is not in the
accessibility tree, and is reached by turning the cube. `data-view="front"` is
therefore present exactly when the `-Y` face is toward the camera, and it is
**absent at the default `iso`**. C19's older unconditional reading — "`front` is
always present" — was satisfied by the shipped cube only *because* of the defect:
the parent transform applied azimuth as a screen roll, so `Front` faced the
viewer at every azimuth. Compliance there was the bug, and the alternative
reading (draw the hidden faces so the assertion keeps passing) would reintroduce
precisely the unreachable buttons this item exists to remove.

The testable form that replaces it: at every named view the plate carries a
`data-view` for the camera the workspace is on and marks that cell
`[data-cube-current]`, and the cell whose normal is the eye direction is the one
drawn. Two consequences bind anyone writing tests here. A click test may not
address `-X`, `+Y` or `-Z` directly from `iso` — those cells are behind the cube
and are, correctly, not clickable — so drive them as a sequence of turns instead.
And an inventory test may not assert that all eight standard view names appear as
distinct targets: `cameras.py` gives `-Y` and `front` the same angles, one camera
with two names, so a 26-cell inventory with unique names spells that camera
exactly once, and B-7's own derivation rule spells it `front`. INTERFACE.md §5.5
and its C19 clause are amended to match, and the two assertions that encoded the
old reading (`web/test/viewportChrome.test.tsx`'s C19 case and
`web/e2e/viewport.spec.ts`'s `front` probe) were rewritten rather than kept.

## B-8 — BOM dialog is 2838px tall at y=-919 with no scroll, and its value column is 0px wide

- **severity** high · **surface** web · **verdict** confirmed
- **effort** S · **risk** low · **lane** G

### Symptom

Opening the BOM control produces a modal taller than the screen, centred on its
own midpoint, so its top 919px and bottom 919px are off-screen with no way to
scroll to them. Only the middle third is readable, and neither the title nor the
"Read from" section can be reached. The scrim and `Escape` work, so the dialog is
dismissible — it is simply not readable.

### Reproduction

At 1600×1000, select a part, open the BOM dialog and measure it. Observed:
`{x: 583, y: -919, w: 434, h: 2838}`, `position: fixed`, `max-height: none`,
`overflow: visible`, clipped at both ends. The scrollable body reports
height 2777 / scroll height 2777 / client height 2777 — nothing to scroll,
because the body was allowed to be as tall as its content. The panel's own rows
compute to `35.75px 2776.5px`. Its three columns compute to
`487.625px 0px 8px`, so every value cell is a zero-width box at x=1150 — 133px
outside the dialog's right edge. The sibling Export dialog in the same variant is
fine (434×277) because it renders no data table and never grows.

Expected — INTERFACE.md §4.7's popover clause, quoted verbatim in the component:
overlay surface, popover shadow, bounded width, "anchored and flipped to stay in
the viewport", focus trapped, `Escape` closes.

### Root cause

**Two independent causes, and fixing only the one the audit named leaves the
dialog unreadable.**

*The container has no height contract.*
`web/src/system/Popover.module.css:33` gives the dialog variant
`position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%);
max-width: 60ch` and declares **no `max-height` and no `overflow`**. Its parent
rule makes it a flex column. A fixed-position flex column with no height
constraint sizes to its content, and the centring transform then puts a 2838px box
at 500 − 1419 = −919. The panel's grid rows of `auto minmax(0, 1fr)` cannot help:
`1fr` resolves against the grid container's own content-derived height, so the
body row **is** the content height and its `overflow: auto` never has anything to
clip. The chain that would work — a bounded outer height propagating down through
`min-height: 0` — has no bound at the top.

*The tracks are sized by a sentence.* `web/src/system/Panel.module.css:73` gives
`.body > *` both `grid-column: 1 / -1` and `min-width: 0`, with the comment
"Anything in the body that is not itself a three-column row spans all three".
There is **no equivalent rule for `.section > *`**. A panel section is itself a
subgrid, so a table inside it self-spans and is fine — but a panel note has no
`grid-column`, auto-places into **column 1**, and its `max-width: 68ch` (computed
491.6px) becomes the max-content contribution of the `max-content` label track. In
a container wider than about 500px this is merely ugly — the same panel in the
900px inspector computes `487.625px 348.375px 8px` for labels reading "Pin",
"Process", "Stock form". Below it, the `minmax(0, 1fr)` value track has a zero
minimum and collapses to exactly 0px, which is the dialog's zero-width value
cells. Seven inspector panels are affected.

History. The dialog variant came in whole with the design-system commit b8b6a48
"feat(workspace): all ten plan items — composer, export, local-first sign-in,
design system", which also wrote the panel's three-track body. The BOM control
itself predates it (72f104f "web: pin-bound Export and BOM chrome (#19)", later
reworked). So the wrapper and the panel it wraps were built by two different
passes and no pass ever measured the pair. The e2e written for it,
`web/e2e/chrome.spec.ts:89`, asserts the field set and the values and calls the
panel visible — and a visibility check is "non-empty box and not hidden", which a
box at y=−919 satisfies. **The test passes today against an unreadable dialog.**

Spec. **The code is wrong**: the dialog variant honours the shadow, the width, the
focus trap and `Escape`, and drops the one clause about staying in the viewport.
The spec is also thin in one respect — "anchored and flipped" describes the
anchored popover, and the dialog variant is centred rather than anchored, so §4.7
should give it an explicit height contract.

What a symptom-only patch would miss. Adding `max-height: 80vh` alone leaves the
dialog 434px wide with a 487px label column and a 0px value column, so the content
becomes scrollable and is still unreadable. Fixing only the track defect makes the
dialog 434×488 at this window size, which fits by luck; on a shorter window, or a
part with more sourcing fields, it overflows again with no scroll. Both halves are
required, and only the container half generalises — the same variant is used by
the sign-in dialog, which will grow the same way the first time it carries a long
refusal.

### Fix

Give the dialog variant a height contract mirroring its width contract, and give
panel sections the span their sibling containers already have. Both were verified
in a live browser: together they take the BOM dialog to 434×488 at
`{x: 583, y: 256}`, fully on screen, with tracks `123.406px 220.391px 8px` and
value cells 184px wide.

1. `web/src/system/Popover.module.css:33` — add
   `max-height: min(80vh, calc(100vh - 2 * var(--pad-overlay)))` and
   `overflow: hidden` to the dialog variant. The `overflow` is the load-bearing
   half: it makes the dialog a scroll-container boundary so the flex child cannot
   spill and must resolve against the bounded height. The panel already carries
   `min-height: 0` and `auto minmax(0, 1fr)` rows, so with a bounded parent the
   body row shrinks and its `overflow: auto` engages — the header stays pinned and
   only the body scrolls, which is right for a modal with a title.
2. Same file — add `.panel[data-variant="dialog"] > * { min-height: 0; }` so any
   future non-panel child of a dialog inherits the discipline rather than
   rediscovering this bug.
3. `web/src/system/Panel.module.css:79` — add
   `.section > * { grid-column: 1 / -1; min-width: 0; }` directly after the
   section rule, with a comment naming the 487px label track as the retired
   defect. **This half is also filed separately; whoever lands it first should
   say so.** Verify the computed value rather than relying on cascade order: the
   data table declares the same span at the same specificity in its own module.
4. `web/src/system/DataTable.tsx` — extend the header comment with the container
   contract: a data table or field renders **only** inside a panel body, because
   the body is the sole declarer of the subgrid tracks; and a panel body must
   always have a **bounded-height** ancestor, because its `overflow: auto` is a
   promise only a bounded parent can keep. Every one of the fourteen call sites
   already satisfies the first half, so it is a documentation and lint
   obligation, not a refactor.
5. `web/src/system/Panel.tsx:17` — the "the body owns the column grid" note gains
   its counterpart, and the panel-section doc comment gains the span rule.

Spec and doc lines to amend. INTERFACE.md §4.7's popover clause states the
two-axis bound for the dialog variant and that the panel body inside it is the
scroll region, so the dialog's title stays pinned. §4.7's data-table clause gains
the container contract and its negative half: prose inside a panel spans all three
tracks and contributes to none of their intrinsic sizes — a column sized by a
sentence is not a column.

Compatibility. Pure CSS plus comments; no DOM contract, no data attribute, no API
and no persisted state changes, so every existing selector keeps resolving. The
visible change beyond the dialog is that value columns widen in seven inspector
panels — an improvement, but it moves pixels, so any pixel-comparison archive of
an inspector panel needs re-baselining. The viewport control-region thresholds are
measured on the canvas, not the inspector, and are unaffected.

### Tests to add

- `web/e2e/chrome.spec.ts` — extend the BOM case: the dialog's box satisfies
  `y >= 0` and `y + height <= viewport height`. This is the assertion whose
  absence let the defect through a visibility check.
- Same file — every value cell in the dialog has non-zero width and is contained
  in the dialog's box. Fails today.
- Same file, at a deliberately short viewport — the panel body scrolls
  (`scrollHeight > clientHeight`) while the dialog does not exceed the viewport.
  Guards the case a 1600×1000 fixture would pass by luck.
- Same file — the containment assertion applied to the Export dialog and the
  sign-in dialog too, so the contract is tested on all three call sites rather
  than the one that broke.
- An inspector test — for each inspector tab, the first grid track is under 40%
  of the body width; and every value cell has non-zero width. The sourcing tab
  fails today at 54%, and at 69% in a 1024px window.
- A source-scan test that no data table or field is rendered outside a panel body.

## B-9 — Creating a session hides every other session, and the new one is then unreachable

- **severity** high · **surface** web · **verdict** confirmed
- **effort** M · **risk** low-to-moderate · **lane** G

### Symptom

With two seeded sessions the strip shows two tabs. Creating a session leaves
**exactly one** tab — the brand-new session — while the sessions listing returns
three rows. Both pre-existing sessions vanish from the UI. Removing the session
parameter and reloading re-selects the first listed session, and the new session
is not in the strip at all: it is reachable only by hand-editing the URL
fragment. There is no close route, so every duplicate create leaves a permanently
idle orphan the operator cannot see.

### Reproduction

Open the workspace, read the session tabs, create an orchestrator session from
the strip's menu, then re-read the tabs and the sessions listing; then strip the
session parameter and reload.

Observed: tabs on load are the seeded orchestrator and its quick-edit child;
after the create, one tab, the new session. `GET /sessions` returns three rows.
The new session's thread returns one node with a null parent; the orchestrator's
returns two. After reload with no session parameter: the original two tabs, and
the new session absent.

Expected — INTERFACE.md §7.1: one tab per **attached** session, nested. All three
render, the two seeded ones nested as before and the new orchestrator as a second
root; the strip's membership never shrinks because a session was added.

### Root cause

This is a data-source defect, not a rendering one.
`web/src/components/stream/StreamPanel.tsx:130` computes the tab list as
`stream.tabs.length > 0 ? stream.tabs : rows.map(...)`, where `stream.tabs` is the
thread walk for the **selected** session — the subtree rooted at that session's
topmost recorded ancestor, and nothing else — and `rows` is the flat session
listing. `GET /sessions/{id}/thread` always returns at least a one-node tree, so
the first branch is true the moment the walk resolves and the flat-list branch is
**dead code in every real state**. The strip therefore renders exactly one
connected component of the session forest: the one containing the selection.

The seeded fixture hid this because its two sessions are parent and child of one
thread; the defect becomes visible only once a second **root** exists, and
`POST /sessions` is the only way to make one from the browser. The reload half
compounds it: the panel defaults the selection to the first listed row, and the
bridge returns principals in insertion order
(`server/src/hephaestus/agent_bridge/app.py:1082`), so the newest session is
always last and can never become the default.

History. `git log -S "stream.tabs.length > 0" -- web/src/components/stream/StreamPanel.tsx`
and `git blame -L 126,145` both return a single commit, bb546fd
"feat(stage4): server/http + the read-only web workspace — G4 19/20, browser gate
pinned-image-deferred". The code has never been changed. The comment above it
describes the flat list as a fallback "with no thread yet (the walk is in flight,
or it failed)" — the author's model was that the thread is a superset of the
listing, which is true only for a single-root project.

Spec. **The code is wrong.** INTERFACE.md §7.1 says one tab per attached session
and names `GET /sessions/{id}/thread` as the **edge** source, "never inference".
The spec is also incomplete and should be amended: it names the edge source and
never names the strip's **membership** source, which is what the implementation
got wrong; and it says nothing about idle orphans, even though the route table
carries no session-close route and the panel already acknowledges that "there is
no route that closes one, so none is offered".

What a symptom-only patch would miss. Re-invalidating the sessions query after a
create changes nothing — it already invalidates, and the strip still renders one
thread. Dropping the length check and always using the flat list would silently
delete §7.1's nesting and the thread-depth attribute, regressing a gate binding.
Both leave the reload half untouched, and both leave the strip unable to show a
delegated child of an **unselected** orchestrator — the same bug one level down.

### Fix

The strip's **membership** is the sessions listing (every attached session, which
is what §7.1 asks for); the strip's **shape** is the edge data the server already
serves. Build the tab list as a forest union rather than one thread.

1. `web/src/stream/thread.ts` — add
   `sessionForest(rows, thread): readonly ThreadTab[]`. Index the thread by
   session id. For each listed row, emit the thread entry when one exists (it
   carries kind, origin and creation time) and otherwise synthesise a tab from the
   row's own `parent_session_id` and `thread_state`, with depth computed by
   walking **listed** parents and capped at the existing maximum. A parent id not
   present in the listing is treated as absent — depth 0, never fabricated. Emit
   breadth-first per root, roots in the server's listing order. Nothing guesses a
   parent: the listing already carries `parent_session_id` and `thread_state` from
   the edge join at `server/src/hephaestus/http/sessions.py:568`, so depth is
   **read** from the server rather than inferred. The precedent for the union is
   in the tree and tested: `web/src/api/projectRefresh.ts:41` does exactly this
   merge for the socket subscription.
2. `web/src/components/stream/StreamPanel.tsx:130` — replace the ternary with a
   memo over `sessionForest(rows, stream.tabs)`. Delete the now-false comment and
   replace it with the membership/shape split.
3. `web/src/stream/thread.ts` — leave the thread walk unchanged; it remains the
   edge source §7.1 names.
4. `web/src/components/stream/SessionTabs.tsx` — no change is needed (it already
   renders the depth and thread-state attributes per tab), but verify the roving
   tab order still matches the new emission order.
5. Optional follow-up, server-side, owned by lane D because it edits
   `server/src/hephaestus/http/sessions.py`: the listing loop already fetches each
   row's edge, so it can also project the edge's kind and origin. That lets an
   **unselected** quick-edit child carry its part label without a second thread
   request. `web/src/api/sessions.ts` gains the two fields.

Spec and doc lines to amend. INTERFACE.md §7.1 gains: the strip's membership is
the sessions listing — every session the serving process owns renders exactly one
tab, in every state; the thread route is the source of an edge's kind, origin and
depth for the selected subtree and is never the source of which sessions exist; a
session that is listed but not in the selected thread renders as a root at depth
0, its edges unknown rather than absent, and the tab says so with its thread-state
attribute rather than by disappearing. Add the orphan clause: because the route
table carries no session-close route, a duplicate create is a permanently idle
session, the strip renders it, and hiding it is not an available remedy. Bring
INTERFACE.md §7A.2's matching sentence — mirrored in the panel's own comment —
into agreement.

Compatibility. No wire change in the minimal form: the client already fetches both
documents, so the fix is client-only and needs no server coordination; old servers
work unchanged. The optional follow-up widens a response shape additively. Visible
change for operators: the strip can now contain tabs it did not before, including
idle orphans accumulated by earlier duplicate presses. That is the intended
repair, but it will look like new sessions appearing.

### Tests to add

- `web/test/stream/thread.test.ts` — a `sessionForest` suite: three sessions, two
  in one thread and one independent root, gives three tabs at depths 0/1/0; a
  listed row whose parent is **not** in the listing gets depth 0 and is never
  dropped; a thread entry and a listing row for the same id merge with the thread
  entry's kind and origin winning and the listing's thread state preserved; an
  empty thread (the walk failed) still renders every listed row.
- `web/test/stream/components.test.tsx` — render the panel with a three-row
  listing and a one-node thread for the selected session: three tabs, and the
  selected id among them.
- `web/e2e/stream.spec.ts` — extend the existing create test: after creating a
  session, the tab count is strictly greater than before, and every session id in
  the listing has a tab. This is the regression that would have caught bb546fd.
- `server/tests/test_http_sessions.py` — the listing's row order is stable and
  every row carries `parent_session_id` and `thread_state`, pinning the fields the
  client now depends on for depth.

## B-10 — Four CLI verbs traceback where the taxonomy says they must refuse

- **severity** high · **surface** cli · **verdict** confirmed
- **effort** M · **risk** medium · **lane** A

Four instances of one class. The first is a capability that cannot work outside
the source clone; the other three are operator-supplied output paths with no
precondition and no catch-all.

### Symptom

- `heph goldens --update` in any clean git-backed project dies with a raw
  `FileNotFoundError` naming a fixture path that exists only inside the
  Hephaestus clone.
- `heph cam emit <part> --out /nope/dir/x.dxf` raises `PermissionError` **after**
  the full kerf, nesting and DXF computation has run, so the work is lost as well
  as unreported.
- `heph render <part> --out /nope/dir` raises `PermissionError` after every
  requested view has been rendered — the images exist in memory and are
  discarded.
- `heph init /proc/nope` raises `FileNotFoundError` out of the scaffold. The
  first verb a new user runs is the one with the rawest failure.

### Reproduction

```
heph init gproj && cd gproj && git init -q . && git add -A && git commit -qm init
heph goldens --update
heph cam emit bracket --out /nope/dir/x.dxf
heph render primary --out /nope/dir
heph init /proc/nope
```

Observed, in order: `FileNotFoundError: [Errno 2] No such file or directory:
'<cwd>/corpus/public_fixtures/assembly'` from the golden generator, exit 1
(`--dir` does not help); `PermissionError: [Errno 13] Permission denied: '/nope'`
from the CAM emitter's `out.parent.mkdir`; the same from the render command's
`out_dir.mkdir`; and `FileNotFoundError` from `os.mkdir` inside the scaffold.

Expected — docs/cli.md's exit-code contract, restated in
`core/src/hephaestus/core/cli.py`: 0 success, 1 the operation ran and the answer
was "no", 2 you asked for something impossible (bad usage, a refused capability).
An unwritable output path is bad usage. So is a golden regeneration outside a
checkout.

### Root cause

**One shared cause for the last three, and one distinct cause for the first.**

*No output-path precondition and no catch-all.* `core/src/hephaestus/core/cli.py`
maps the engine taxonomy at its `main()` and has no `except OSError` arm and no
catch-all, so any `OSError` reaches the interpreter. The three verbs each do a
bare `mkdir` on operator-supplied output, and each does it **after** the expensive
work: `core/src/hephaestus/core/cli_cam.py:98` after `emit_part` has computed the
program; `core/src/hephaestus/core/cli_render.py:81` after every view has been
rendered (with an identical unguarded `mkdir` copied into the posed-render command
in the same file); `core/src/hephaestus/core/cli_init.py:95` at the top of six
more unguarded writes, so a failure landing mid-sequence leaves a **partial
scaffold** — which docs/cli.md's "nothing is written" promise forbids.

*Two meanings fused into one variable.* In
`core/src/hephaestus/core/render/goldens.py:255` the resolved root is
`repo_root or _git_root()`, and that one value is then used for **two unrelated
purposes**: the dirty-tree guard (correct for any repository) and the fixture root
at `core/src/hephaestus/core/render/goldens.py:151`, consumed by an unguarded
`shutil.copytree` at line 161. Any git repository passes the first use and fails
the second; the render CLI catches only the dirty-tree error.

History. The goldens conflation is original and never a regression: the module has
two commits, and the generator was written as repository tooling — the workspace
transcript recorder is its other caller and passes an explicit repository root —
and was wired to a public verb in the same commit that created it. The CAM
emitter's `mkdir` is attributable to the single commit that added the verb, which
also added a module-local usage-error class and guard, i.e. the module opted out
of the shared boundary at birth. The render `mkdir` dates to the Stage 1 render
commit and was **copied** into the posed-render command by the Stage 9B motion
commit — evidence on its own that a shared helper is the right shape. The init
scaffold is a single-commit file whose named "target not empty" refusal directly
above the failure shows the author was consciously building a refusal taxonomy and
simply did not extend it to OS-level failures.

Spec. **The code is wrong and the spec is right and already covers three of the
four.** docs/cli.md's exit-code section assigns bad usage to exit 2, and
`core/src/hephaestus/core/cli.py` repeats it. For `heph init`, docs/cli.md's
"nothing is written" invariant is violated by the partial-scaffold path. For
`heph goldens`, **both** are wrong: the code never checks the fixture root, and
the documentation states only the dirty-tree refusal and omits that the verb is
meaningless outside a checkout.

What a symptom-only patch would miss. An `except OSError` at each of the three
`mkdir` calls turns tracebacks into messages and leaves the expensive work still
running first, leaves the copied `mkdir` in the posed-render command, and leaves
the same bug waiting for the next output verb. For `heph init` a guard around the
first `mkdir` still permits a partial scaffold when a later write fails. For
`heph goldens` an `except OSError` would leave the verb advertised to every
installed user as something they could run, and leave the two meanings of `root`
fused, so a future `--fixtures-dir` would still silently re-derive from the
working directory.

### Fix

One new module for the shared boundary, one restructure for the scaffold, one
split for the goldens.

1. New `cli_errors.py` in `core/src/hephaestus/core/`, exporting a shared usage error, a
   json-aware refusal printer, a guard wrapper, and
   `ensure_writable_dir(directory, *, flag)` which creates parents inside a try
   and converts an `OSError` into a usage error naming the flag and the reason.
2. `core/src/hephaestus/core/cli.py` — add a final `except OSError` to the
   taxonomy at `main()`, printing the strerror and the filename and returning 2,
   as a last-resort net beneath the preconditions.
3. `core/src/hephaestus/core/cli_cam.py:98` — move the output-path resolution
   **above** the emit call and call `ensure_writable_dir` there; delete the bare
   `mkdir`. Adopt the shared guard in place of the module-local one.
4. `core/src/hephaestus/core/cli_render.py` — call `ensure_writable_dir`
   immediately after the output directory is parsed, before the pose branch, so
   both the render and posed-render commands are covered by one call; the two
   `mkdir` calls become redundant. Wrap both commands with the shared guard —
   today the render command has no wrapper at all. Note the default is a relative
   directory, so the precondition must **create** it as it does today rather than
   refuse a missing relative path.
5. `core/src/hephaestus/core/cli_init.py:95` — restructure the scaffold to write
   into a sibling temporary directory and rename into place, so a partial scaffold
   is not representable; keep the existing precondition ladder untouched above it
   and convert any `OSError` into the shared usage error. Where the target exists
   and is empty, move the contents in. `heph init` with no argument targets the
   working directory, whose parent may not be writable, so fall back to guarded
   in-place writes when the sibling cannot be made.
6. `core/src/hephaestus/core/render/goldens.py` — split the two meanings of
   `root`. `update_goldens` gains an explicit `fixtures_root`; the fixture
   preparation takes that instead of the repository root; before the loop, a
   fixture root that is not a directory raises a new named
   `GoldenCorpusUnavailableError` stating that golden regeneration runs only
   inside a Hephaestus checkout. **Do not** repoint the git-root helper at the
   fixtures root, or the dirty-tree guard weakens.
7. `core/src/hephaestus/core/cli_render.py:187` — catch the new error, print
   `heph: <message>` and return 2; add a `--fixtures-dir` option so a fork with
   its own corpus can use the verb.

Spec and doc lines to amend. docs/cli.md's `heph goldens` section gains one
sentence: the golden corpus lives in the Hephaestus checkout under
`corpus/public_fixtures`, so this verb runs there, and `--fixtures-dir` points it
at another corpus; the dirty-tree paragraph is unchanged. docs/cli.md's
`heph init` paragraph extends "nothing is written" to say that a target which
cannot be created at all is refused with exit 2 and nothing is written, keeping
exit 1 for the named not-empty refusal, which is a ran-and-answered-no. Optionally
note under `heph cam emit` and `heph render` that `--out` is validated before the
work starts.

Compatibility. The exit code for these inputs changes from 1 to 2, which is the
documented value; no JSON shape changes. The goldens signature change is additive
and its existing in-repository callers keep working. The scaffold restructure
means a partial scaffold is no longer possible; nothing in the tree depends on
init leaving files behind on failure — the init tests assert the opposite.

### Tests to add

- `core/tests/test_render_inspect_cli.py` — golden regeneration in a clean
  scratch repository with no corpus raises the named error and writes nothing,
  mirroring the existing dirty-tree test; the CLI-level case returns 2 with no
  traceback; and `--fixtures-dir` pointed at a copied single-spec corpus
  regenerates into a temporary output directory.
- `core/tests/test_cli_cam.py` — `--out` under an unwritable parent returns 2, the
  message names `--out`, and no DXF is written. Then the **ordering** assertion:
  point `--out` at an unwritable directory for a part with no current build and
  assert the message is the `--out` one, proving the precondition runs first.
- `core/tests/test_render_inspect_cli.py` — the same for `heph render` and for the
  posed-render command, with a patched inspect that must not be called, so the
  test proves no GL session was opened.
- `core/tests/test_cli_init.py` — a target under an unwritable parent returns 2,
  the message names the target, and the parent is unchanged; plus an atomicity
  test that a failure after the first two files leaves the target directory
  absent.

### Notes

**The shared boundary landed as `core/src/hephaestus/core/cli_errors.py`, and it
is half-adopted by design of the lane split, not by oversight.** That module is
the single owner of `CliUsageError`, `usage_from_oserror`, `ensure_writable_dir`,
the json-aware refusal printer and the `guard` wrapper. The four modules lane A
owns adopted it — `core/src/hephaestus/core/cli.py` keeps `_UsageError` only as
an alias of `CliUsageError`, because it has too many call sites to rename in the
same change, and `core/src/hephaestus/core/cli_cam.py`,
`core/src/hephaestus/core/cli_render.py` and
`core/src/hephaestus/core/cli_init.py` raise the shared error directly.

**Follow-up, unassigned:** eight further modules still carry a private
`_UsageError` and a private `_guard` of their own, and none was in lane A's
ownership — `core/src/hephaestus/core/cli_authoring.py`,
`core/src/hephaestus/core/cli_solve.py`,
`core/src/hephaestus/core/cli_registry.py`,
`core/src/hephaestus/core/cli_references.py`,
`core/src/hephaestus/core/cli_import.py`,
`core/src/hephaestus/core/cli_assembly.py`,
`core/src/hephaestus/core/cli_motion.py` and
`server/src/hephaestus/agent_bridge/cli_export.py`. Each should import
`CliUsageError` and `guard` from `hephaestus.core.cli_errors` and delete its
copy. Until that lands, the JSON refusal shape is **deliberately scoped** in
docs/cli.md to the precondition refusals rather than claimed for every verb: do
not widen that sentence ahead of the adoption, and do not read the eight private
copies as duplication left behind carelessly.

One clause of that scoped sentence is nevertheless unreachable and is a small
follow-up of its own: it names "the target check under `heph init`", but
`heph init` declares no `--json` flag, so the object form cannot be produced
there — `heph init --json` is an argparse usage error. Either give `heph init`
the flag or narrow the sentence to the `--out` checks under `heph render` and
`heph cam emit`, which do have it. docs/cli.md is lane A's file.

## B-11 — A malformed cursor is reported as a dead runtime; resuming a transcript that does not exist mints one

- **severity** high · **surface** http · **verdict** confirmed
- **effort** M · **risk** medium · **lane** D

Two session defects with one shared consequence: a client is told something about
the runtime that is not true.

### Symptom

*(a) The cursor.* A history read with a malformed cursor — `%%%`, a base64 token
that is not a cursor, a non-numeric or negative offset — answers **503
`agent_unavailable`** with cause `sidecar_failed`. The sidecar is alive: the very
next history call returns 200. The web client renders "This server has no agent
runtime attached, so there is nobody to send this to", which is false.

*(b) The resume.* `POST /sessions` with a session id and `resume: true` for a
transcript that does not exist answers **200** with `resumed: true` and mints a
session under that name. The listing then shows it. The operator is told they
reopened a transcript they did not, and the panel opens an empty tab labelled as
resumed.

### Reproduction

Against a real sidecar and a real serve. For (a): create a session, then read
history with `cursor=%%%`. Observed 503, reason `agent_unavailable`, cause
`sidecar_failed`, message `history.page failed: {'code': -32603, 'message':
'malformed history cursor'}`; identical for a well-formed-base64 non-cursor and
for a non-numeric or negative `after`; the immediately following unqualified
history read returns 200. For (b): `POST /sessions` with a never-used id and
`resume: true`. Observed 200,
`{"status": "ok", "session_id": "sess-nope", "resumed": true}`; the listing shows
it; its history returns an empty page marked done — indistinguishable from a
genuinely empty resumed transcript. Reproduced identically against the fake
backend, so both backends agree on the wrong answer.

Expected — INTERFACE.md §2.4 tabulates `invalid_cursor` at 400, and states that a
malformed request and an unreachable runtime are never collapsed because "they
have different remedies and a client that could not tell them apart would offer
the wrong one". For the resume, INTERFACE.md §2.4 already defines
`unknown_session` at 404 for an id the runtime holds nothing for.

### Root cause

*(a)* Three layers compose. `agent/src/session/history.ts:511` throws a plain
`Error("malformed history cursor")` from the cursor decoder, called from both the
cursor and the `after` paths. `agent/src/rpc.ts:244` catches any non-`RpcError`
thrown by a handler and emits an internal-error frame — JSON-RPC `-32603`. And
the Python classifier at `server/src/hephaestus/http/errors.py` inspects the error
envelope only for an invalid-params code matched against the unknown-session
pattern; an internal-error envelope matches nothing and falls to the catch-all at
`server/src/hephaestus/http/errors.py:377-382`, which returns
`agent_unavailable`/`sidecar_failed` **unconditionally**. The catch-all's own
docstring states that the error envelope is populated only when the sidecar
answered — so the information needed to avoid this is already in the exception and
is not consulted.

*(b)* No layer checks that the named transcript exists.
`server/src/hephaestus/http/sessions.py` returns `"resumed": resume` — **the
request's own flag echoed back**, never a fact about what happened. The bridge
forwards `resume: true` as an RPC parameter; `agent/src/session/manager.ts:192` is
literally `return this.create({ ...request, resume: true })`, and the manager then
prefers "continue most recent" over "create" — with the session directory absent,
there is nothing to continue and a fresh session is yielded.

History. The cursor decoder's plain throw dates to 7b9c89b
"feat(agent): Stage 2A runtime core — bridge, sidecar, tool codegen, heph agent",
long before any HTTP surface, when a thrown error simply became a `-32603` nobody
rendered. The Python catch-all was written in e3ef904
"fix(server): re-adopt a session the sidecar forgot, and refuse by name instead of
an unnamed 500" — a commit whose whole subject is that an unnamed refusal is
unacceptable, and which converted the old bare 500 into a **named but wrong** 503
for this input. The `after` parameter that made three more inputs reach the same
throw was added in the same commit. For the resume, `git blame` attributes all 43
lines of the block to bb546fd, and the docstring added there records the behaviour
as intentional: "`resume` on an id with no persisted transcript is a fresh session
under that name, which is the sidecar's own behaviour" — an accurate description
of the manager and an incorrect conclusion, treating the sidecar's silence as a
decision.

Spec. For (a) **the code is wrong and the spec is incomplete**: INTERFACE.md §2.8
names `invalid_cursor` only for the cursor-and-`after` **pair** and says nothing
about a token that fails to decode; and it forbids the easiest fix by stating that
neither token is ever decoded outside the sidecar, so the HTTP layer may not
validate the shape itself. For (b) **both are wrong**: INTERFACE.md §2.3's create
row names no body at all, so `resume` is an undocumented parameter whose failure
mode was never specified, while §2.4 already defines the refusal the code should
be giving.

What a symptom-only patch would miss. Special-casing the cursor message in the
Python classifier fixes those inputs and leaves the class: any future sidecar
handler that throws a plain error — the mutually-exclusive-pair throw in the same
file is the next one — still becomes `-32603` and is still reported as a dead
runtime. For the resume, checking existence in the HTTP layer leaves
`heph agent --session NAME --resume` and the bridge's own resume with the same
lie — and the bridge's resume is what §2.8's re-adoption path calls, so a failed
re-adoption would silently create a **new empty session under the old id** and
report the transcript readable.

### Fix

*(a) Cursor.* Two halves, both required.

1. `agent/src/session/history.ts:511` — export a named malformed-cursor error and
   throw it from both decode sites. The history module must not import the RPC
   module (it is the pure normalisation module), so the class, not an `RpcError`,
   is the seam.
2. `agent/src/main.ts` — the history-page handler wraps the paging call and
   re-throws a malformed cursor as an `RpcError` with the invalid-params code.
   Give the mutually-exclusive-pair throw in the same file the same treatment.
3. `server/src/hephaestus/http/errors.py` — map that invalid-params message to a
   400 `invalid_cursor`, reading the engine's own fixed message rather than
   re-deriving it, the discipline the module already documents.
4. **The structural half**, at
   `server/src/hephaestus/http/errors.py:377` — before falling through to the
   `agent_unavailable` catch-all, return a refusal derived from the error envelope
   whenever one is present. A populated envelope is proof the sidecar answered, so
   `agent_unavailable` becomes unreachable on that branch **by construction**
   rather than by enumeration. This alone fixes the mislabel even against an
   un-restaged bundle, which is why it should land first.
5. `server/src/hephaestus/testing/fake_agent.py` — raise the same named refusal so
   the contract is testable without a Node sidecar.
6. Restage the packaged sidecar, or the Python half is untestable end to end.

While the refusal is open, delete the merge that reattaches the attach projection
onto this path: the sidecar-failed refusal carries the provider config path, which
INTERFACE.md §2.4 says this path must **not** carry, because a stale path is worse
than an absent one. The refusal is already correct where it is minted; the merge
is six lines in the endpoint guard and should go. That deletion is also filed on
its own, with its own history, as J-http-envelope-1 in the janky ledger — it is one
six-line change, and whichever lane reaches the wrapper first applies it once.

*(b) Resume.*

1. `agent/src/session/manager.ts:191` — resume checks that the session directory
   exists (and that the profile persists) before delegating, and on a miss throws
   with the exact message the Python unknown-session pattern already parses, so no
   new reason and no new mapping code is needed.
2. `agent/src/main.ts` — the create handler surfaces that as an `RpcError` with
   the invalid-params code, not a plain error, or it becomes `-32603` and lands on
   the (a) mislabel. Land (a) first or together.
3. `server/src/hephaestus/http/sessions.py` — `resumed` reports what happened, not
   what was asked. Replace the docstring's concession with the new rule.
4. `server/src/hephaestus/agent_bridge/app.py` — the re-adoption path uses the
   **directory**-exists check, not a transcript-file check, so a session that was
   created and crashed before writing an entry still re-adopts; the existing
   refuse-by-name path already maps a failed re-adoption to `unknown_session`, so
   the new refusal flows into a tested path.
5. `server/src/hephaestus/testing/fake_agent.py` — model the same refusal; today
   it unconditionally inserts the id.

Spec and doc lines to amend. INTERFACE.md §2.8 extends the `invalid_cursor` clause
from "sending both" to: a token that does not decode, or that carries a
non-integer or negative offset, is `invalid_cursor` at 400 — refused by the
**sidecar**, because the token is opaque above it and the passthrough rule forbids
the HTTP layer from decoding it. Add one sentence to §2.4's `agent_unavailable`
row: a refusal the sidecar **answered** is never `agent_unavailable`, since the
answer is proof of liveness. INTERFACE.md §2.3's create row documents the body
`{profile, part?, session_id?, resume?}` — currently undocumented — and states
that `resume: true` for an id with no persisted transcript is 404
`unknown_session`, not a fresh session under that name; §2.4's `unknown_session`
row gains that firing condition; and §2.8 states that `resumed` is a fact about
the transcript, not an echo of the request.

Compatibility. Five history query shapes move from 503 to 400 and change reason;
the web client already types the vocabulary and renders a named 400 better than
today's 503. The create route's behaviour changes on a route the composer calls,
and the client is ready — it already types `unknown_session` and handles the
branch. No stored state and no migration. The one real hazard is the staged
sidecar: a partial landing where Python expects invalid-params and the staged
bundle still throws a plain error reproduces the old 503 silently — which is why
step (a)(4) is the structural guard and lands first. The workspace fixture's
recorded transcript is reopened by exactly this resume call, and that transcript
exists on disk, so it still resumes; the same is true of the crash-and-resume
paths in the end-to-end suites.

### Tests to add

- Sidecar-backed HTTP lane — history with `cursor=%%%`, with a well-formed-base64
  non-cursor, and with a non-numeric and a negative `after`, each 400
  `invalid_cursor`; then an unqualified history read returns 200, **pinning that
  the sidecar was never considered dead**.
- `server/tests/test_http_errors.py` — a unit on the supervisor-error classifier:
  an exception with **no** error envelope is `agent_unavailable` at 503; one
  **with** an envelope is never `agent_unavailable`. This is the structural
  assertion and it must not name the cursor message.
- Same file — the sidecar-failed refusal does **not** carry the provider config
  path, paired with the existing assertion that the attach refusal does.
- `agent/test/session/history.test.ts` — the decoder throws the named error for a
  non-base64 token, a non-JSON payload, a missing mark, a non-integer offset and a
  negative offset.
- `server/tests/test_http_sessions.py` — resuming a transcript that does not exist
  is 404 `unknown_session` with the session id, and the listing does **not** show
  it; and the positive half, so the fix is not over-tightened: create a session,
  let it persist, resume it by name, 200 with `resumed: true` and its events.
- `server/tests/test_session_readopt.py` — a re-adoption whose session directory
  is missing surfaces `unknown_session` rather than silently minting an empty
  session. This is the regression the fix must not introduce.
- The same four query shapes and the resume case against the fake backend, so both
  contracts are pinned on the lane that runs without a Node toolchain.

## B-12 — `stubSummary` is the only producer of the pinned CAD summary

- **severity** high · **surface** agent-tools · **verdict** confirmed
- **effort** M · **risk** low · **lane** E · **depends on** B-11 (shared files)

### Symptom

At the compaction trigger — and on every explicit compaction request — the model
is handed a pinned summary whose every content field is empty: no decisions, no
open problems, no parameters, check status "unknown", and a design intent that is
the session id and profile. The one artifact designed to survive compaction
survives with no information in it, so whatever the model retains across the
boundary is whatever the vendor summariser happened to keep from the raw
transcript.

### Reproduction

Read the single producer and its two consumers. `agent/src/main.ts:569` is the
entire implementation: a design intent of `session <id> (<profile>)`, empty
decision and problem lists, an empty parameter map, and a check status of
`"unknown"`. It is consumed at the compaction-policy construction and at the
explicit-compaction handler. Grepping for the summary type across the sidecar
returns only the interface at `agent/src/session/context.ts:84` and these three
sites. Rendered through the formatter, the block is the five headings and nothing
else. Real content exists only in `agent/test/session/context.test.ts:15`, which
constructs a summary by hand.

Expected — agent/STAGE2_DIGEST.md §1: the extension requests compaction with a
**CAD-aware pinned summary** containing design intent, decisions, open problems,
current parameters and check status. architecture.md §4.4 says the same, and
`agent/src/session/context.ts` restates it as the module's contract.

### Root cause

The function is named `stubSummary` and is a stub. The summary type, the
formatter, the delimiters and the policy's summary-supplier injection point are
all fully built — the policy takes the summary as a **supplier** precisely so a
real producer could be dropped in, and none ever was.

The sidecar has the raw material: the session's own recorded entries are already
read to mint the turn marker, and `agent/src/session/history.ts` already has typed
readers over exactly those entries — assistant and tool-result shapes,
normalisation, user-prompt extraction, error recovery. Nothing was missing except
the function.

History. `git log -S"stubSummary" --oneline -- agent/src/main.ts` returns exactly
one commit, 7b9c89b "feat(agent): Stage 2A runtime core — bridge, sidecar, tool
codegen, heph agent". It was authored as a stub on day one and never revisited
across Stage 2B, Stage 4 and four web amendments. It survived the gate because of
how the gate test is written: `tests/stage2/test_g2_context.py:42` defines the
required sections as the five **heading strings** and asserts only that each
appears in the summarisation request body. The formatter emits all five headings
unconditionally, so the assertion passes on an empty summary. The test's one
content assertion passes because the body it searches is the whole summarisation
request — which contains the raw pre-compaction transcript the summariser is being
asked to compress. **The gate proves the delimiters and the headings reached the
model; it never proved the summary carried anything.**

Spec. **The code is wrong; the specs are correct.** agent/DESIGN.md assigns the
context module the job. INTERFACE.md §19 does not list it as new work. The
**test** is also wrong — it asserts structure where the spec demands content — and
must be amended alongside.

What a symptom-only patch would miss. Filling in the design intent from the first
prompt — the cheapest visible improvement — leaves four of five fields empty and
leaves the gate unable to tell. The root cause has two halves and both must be
fixed: a real producer, **and** a gate assertion that checks content rather than
headings, or the next stub passes the same way. There is also a scope trap: the
obvious "real" producer is a new bridge request asking Python for project state,
which extends the wire vocabulary for data the sidecar already holds.

### Fix

Build the producer in `agent/src/session/context.ts`, derived from the session's
own recorded entries. Zero wire change, zero Python change, no new bridge method —
every input is already in the transcript the sidecar owns.

1. `agent/src/session/context.ts` — add
   `summarize(entries, managed): PinnedCadSummary`, using the existing entry
   readers in `agent/src/session/history.ts` (exporting the message shapes from
   there if they are module-private).
   - **design intent** — the first operator prompt. The prompt extractor already
     isolates the operator's own sentence from the workspace context envelope,
     which is exactly what the turn marker was added for; truncate to a sentence
     budget, and fall back to today's session-and-profile string only when there
     is no prompt.
   - **parameters** — the newest parameter-setting result's effective map, or the
     newest build result's parameters. Both are tool results already in the
     transcript.
   - **check status** — the newest check run rendered as
     `"<n> passing, <m> failing (<names>)"`, matching the phrasing the existing
     unit test already uses.
   - **open problems** — failing check names from that same result, the reason or
     failing line of the newest failed build, and any unresolved-material entry
     the ledger tools reported. Cap the list and cap each string.
   - **decisions** — every operator answer to a question in the session (the
     question and the selected label, which is a stable server-sent label), plus
     requirement resolutions. These are literally the design decisions the
     operator made, and they are what the gate's post-compaction clause is about.
2. Same file — export the item and byte caps as constants, so the tests read them
   rather than duplicating numbers. The block is prepended to a compaction request
   and therefore competes for the very context the compaction is reclaiming; drop
   oldest-first. Output must be deterministic — the same entries produce the same
   block — so no timestamps and no map-iteration-order dependence.
3. `agent/src/main.ts:569` — delete `stubSummary`; add a `pinnedSummary` that
   calls `summarize` over the session's entries inside a try/catch, falling back
   to today's stub. A bookkeeping failure must not fail a compaction, the same
   posture the turn marker already takes.
4. Same file — both call sites use it.
5. `tests/stage2/test_g2_context.py:42` — **the gate fix**: the assertion moves
   from headings to content. Assert the pre-compaction decision appears **inside**
   the pinned-summary delimiters, not merely somewhere in the request body. This
   is the assertion the gate clause actually asks for.
6. `agent/tsconfig.json` excludes the sidecar's own test directory from
   type-checking, so a summary test would not be type-checked as written. Adding
   a test-scoped configuration is cheap and lands green; do it here or note the
   gap.

Spec and doc lines to amend. agent/STAGE2_DIGEST.md §1 and architecture.md §4.4
already specify the five contents and need no change. Add to agent/DESIGN.md, near
the context module's entry, the derivation: the summary is computed from the
session's own recorded entries and requires no bridge call, so nobody reaches for
a new method later. Record the caps there too.

Compatibility. The summary is an instruction string handed to the vendor's
compaction; there is no schema and no consumer other than the summarising model.
The formatter's output shape and delimiters are unchanged, so the existing
delimiter assertions and any archived event goldens still hold. Behaviour on a
fresh session with no entries is byte-identical to today, so nothing regresses.
The one real risk is size, which the caps address.

### Tests to add

- `agent/test/session/context.test.ts` — `summarize` over a synthetic entry list
  containing an operator prompt, an answered question, a parameter-setting result,
  a failing check run and a failed build produces the five populated fields. The
  hand-written summary already in that file becomes the expected output rather
  than a fixture.
- Same file — determinism (the same entries twice produce byte-identical output)
  and the caps (twenty decisions render as the capped count, newest first, with
  the block under the byte cap).
- Same file — an entry list that throws on read does not throw out of `summarize`,
  and the fallback keeps compaction working.
- `tests/stage2/test_g2_context.py` — the pre-compaction decision is inside the
  pinned-summary span. **This fails today** and is the assertion the gate clause
  requires.
- Same file — after a parameter change and a failing check, the pinned span
  carries the parameter values and the failing check name, proving the summary is
  CAD-aware and not merely prompt-aware.

## Not defects

All twelve reproduced, so nothing in this register resolves to `not_a_defect`,
`by_design` or `not_reproduced` as a whole item. What follows are the **claims
inside** those items that did not survive re-reproduction, recorded so nobody
re-chases them.

- **B-1 — "the `measure` tool cannot address tags" understates it.** The tool
  refusal is real, but the same empty index is reached by `heph check` and by
  project-scope `run_checks`, where the consequence is a **failing check** rather
  than a refusal. A fix scoped to the tool is not a fix. Conversely,
  `inspect_part(focus=…)` on the identical artifact **works** — it uses the second
  of the two existing published-artifact resolvers — so "the artifact cannot carry
  its namespace" is false and must not be used as a reason to widen persistence.
- **B-2 — "two shipped runtimes" is three.** `heph mcp` builds the same bare
  dispatcher at `server/src/hephaestus/mcp/app.py:281`. Any per-call-site patch
  that fixes the two the audit named will be copied a third and then a fourth
  time.
- **B-3 — the reported result payload was quoted without `mime`-level detail that
  matters.** The failure is not that a field is missing; it is that a field
  declared **optional** is present as `null`. Omitting the key passes both
  validators today. A fix that adds the field, or that changes the schema to admit
  `null`, is the wrong direction.
- **B-5 — "`GET /build` hides a newer failed build" is by design, and the design
  is right.** The precedence — a current success wins over a later failure — is
  deliberate, documented in the operation's own docstring, and pinned by a test,
  because the geometry count a gate binds to must be a fact about the current
  build. Inverting it would empty the geometry tree whenever a rebuild failed
  while a good artifact was pinned. What is missing is a **member** for the newer
  failure, not a change of precedence. Likewise, `current` itself is correct as
  publication state: architecture.md §3.5 defines it that way and the engine is
  consistent with its own spec. The defect is that no reader recomputes freshness,
  not that `current` means the wrong thing.
- **B-6 — the plain-text 500 is not a mapper bug.** `refusal_for`'s bare re-raise
  for an unmapped exception is deliberate and pinned by a test: a mapper that
  guessed would turn a bug into a plausible refusal. The fix belongs at the
  application boundary, and that test must stay green.
- **B-7 — "the cube renders as a diamond" is a symptom of two causes, not one.**
  The parent-transform frame mismatch and the interior-slab geometry are
  independent: with the corrected transform applied and nothing else, the six faces
  become correct at every named view and **nine of fifteen targets remain
  unreachable**. Anyone landing only the one-line transform fix should expect the
  reachability probe to stay red.
- **B-8 — the audit's stated cause is not the whole cause, and is partly wrong.**
  "Only the panel body declares the three tracks" and "the dialog is a flex box"
  are both true statements about the code and neither is the mechanism. The
  mechanisms are a dialog variant with no `max-height` and a panel section whose
  children are not given the span its sibling container's children get. Fixing
  either alone leaves the dialog unreadable.
- **B-9 — the strip is not a rendering bug.** The tab component and the nesting
  attributes are correct; the tab **list** is built from the wrong document. A fix
  that flattens the list to repair membership would delete the nesting a gate
  binding depends on.
- **B-10 — `heph goldens` is not the same defect as the other three.** The three
  output-path tracebacks share one cause (no precondition, no catch-all) and one
  fix. The goldens failure is a distinct cause — one variable serving two
  unrelated meanings — and wrapping it in the shared helper would silence it
  without unfusing them, leaving a future `--fixtures-dir` still deriving from the
  working directory.
- **B-11 — the auditor's `config_path` observation is a separate defect from the
  cursor mislabel.** The sidecar-failed refusal carries the provider config path
  because the endpoint guard merges the attach projection back in, six lines added
  by the same commit whose sibling comment says the field is "deliberately
  absent". It is carried in this item's fix because it is in the same wrapper,
  but it is not caused by, and does not depend on, the cursor classification, and
  it is filed separately as J-http-envelope-1.
- **B-12 — the pinned summary is not "not implemented".** Every part of the
  mechanism ships and works: the type, the formatter, the delimiters and the
  policy's supplier injection point. Only the supplier is a stub. A plan that
  budgets for building the compaction machinery is budgeting for work that is
  already done.
