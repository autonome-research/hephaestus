<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# Frontier staging proposal — the operator's decision document

> **2026-08-29 — the component store crossed the amendment boundary.** The
> operator approved the recommended build order of §2.2 and opened the component
> store first. `PARTS_STORE.md` is now **normative** and `mission_plan.md` carries
> a dated **Stage 11 — The component store** block citing it, with gate summaries
> for G11A/G11B/G11C. D3 was decided as option (b), *reference, do not vendor*,
> and D5's discipline was honoured: all eight of that spec's confirmed findings
> were closed by tightening and independently audited before the block landed.
> Three consequences for readers of this document. **(a)** §3.1's block is
> superseded by the landed text — it is retained as the drafting record, and its
> `10S` names, its "23 / 21 / 14" clause counts and its 2026-08-28 date are all
> stale; the landed stage is **Stage 11 / G11A–G11C** with **24 / 21 / 15**
> clauses. **(b)** §3.2's block still labels mesh and scan ingest "Stage 11"
> because it predates the D4 resolution recorded at §4's D4; that collision is
> settled by the landed amendment, which reserves Stage 11 for the component
> store — **mesh and scan ingest is Stage 12**, and its block must be renumbered
> (heading, gate names, suite paths) by whoever opens it. **(c)** §3.6's second
> edit — the fifth `LEGAL-REVIEW.md` scope field — landed in the Stage 11 block's
> own text rather than as an edit to G7's gate text, because an amendment for one
> stage does not rewrite another stage's gate; the requirement and the checker it
> needs are gated at G11C. The four remaining stages are untouched and every
> decision in §4 other than D3 still stands as recommendation, not ruling.

> **2026-08-29 — mesh and scan ingest crossed the amendment boundary too, second
> in the recommended order.** `MESH_INGEST.md` is now **normative** and
> `mission_plan.md` carries a dated **Stage 12 — Mesh and scan ingest** block
> citing it, with gate summaries for G12A/G12B/G12C (51 clauses: 20 / 13 / 18).
> Three consequences for readers. **(a)** §3.2's ready-to-paste block is
> superseded by the landed text and is retained only as the drafting record; its
> `Stage 11` heading, its `G11A`–`G11C` gate names, its `tests/stage11*` suite
> paths and its 2026-08-28 date are all stale, and the "tenth geom service"
> ordinal D4 flagged is correct as written because `geom.mesh` is indeed the
> tenth. **(b)** The landed block goes materially beyond §3.2 in ways a reader
> must take from `mission_plan.md` rather than from here: the tool-surface pin
> moves **53 → 54** at 12C and Stage 12 is the first of the five to move it; the
> byte-ceiling refusal is renamed `mesh_import_too_large` **unilaterally**, so no
> other document is obliged to rename anything; the `COMPARE.md` §4 replacement
> is required to carry `PHYSICS.md`'s FEA-mesh exclusion forward verbatim,
> because this stage rewrites that sentence first; and the clinical-claim
> refusal, the lattice deferral with its rule 6 precondition, and the four
> constants left unvalued under rule 4 are all recorded in the plan. **(c)** D5's
> discipline was honoured — six confirmed findings closed by tightening and then
> independently audited clause by clause, with the residuals found inside two
> closures closed with them — but the review was **smaller than the
> `KINEMATICS.md` precedent this document recommends**, and both the amendment
> and the spec header say so rather than implying otherwise. The three remaining
> stages (solver, CAM, physics) are untouched and every decision in §4 other than
> D3 still stands as recommendation, not ruling.

**Date: 2026-08-28. Status: PROPOSAL for three of the five specs; superseded for
`PARTS_STORE.md` and `MESH_INGEST.md`, promoted on 2026-08-29 — see the notes
above. Nothing here is normative and nothing here amends anything.** Five normative
specifications have been drafted and revised
against the codebase — `PHYSICS.md`, `SOLVER.md`, `MESH_INGEST.md`,
`PARTS_STORE.md`, `CAM.md`. Each is written in the normative voice so review has
something falsifiable to attack; each says in its own header that it is a DRAFT
pending a `mission_plan.md` amendment. Mission rule 5 (`mission_plan.md:815-817`)
is the only door: deferred and new capability "enter only by amending this plan
with a new gated stage." This document is the text such an amendment would be
built from, the sequencing argument behind it, and the decisions that are the
operator's and not a spec author's.

**What this document does NOT do.** It does not edit `mission_plan.md`; §3 below
is paste-ready text for the operator to apply. It does not promote any of the
five specs. It does not close any of the 30 confirmed adversarial findings §5.1
lists, and it recommends that no spec be cited by a dated amendment until its own
blocking findings are closed by *tightening* — mission rule 1
(`mission_plan.md:801-804`): ambiguity in a gate is a defect in the plan,
resolved by tightening the gate, never by waiving it. A gate clause that cannot
pass is a stronger version of the same defect.

**Where the tree stands.** Stages 8A–9C have landed (`tests/stage8a` …
`tests/stage9c`); `hephaestus.geom` holds nine pure services; the tool surface is
exactly 53, pinned twice (`contract/tests/test_toolgen.py` lines 98 and 109;
`tests/stage2/test_g2_contract_drift.py` line 354); Stage 10 (workspace egress,
provider attachment, credential discovery) is in flight under its own dated
amendment (`mission_plan.md:700`). Everything below is what comes after that.

---

## 1. The five capabilities, as specced

Sizes use one scale, defined here so it is not a vibe. **One unit = Stage 9**
(three sub-gates, one new geom service, 13 new tools, one new projection field,
one new corpus family). The unit is a *shape*, not a schedule; the multipliers
below are read off clause counts, named-new-work counts, and the number of
distinct seams each stage opens, and they are estimates, not measurements.

### 1.1 `PARTS_STORE.md` — the component store (drafted as Stage 10S)

The existing `parts` registry kind gains (a) a **validated component record** in
place of today's opaque metadata blob — where `params` is copied verbatim as an
untyped mapping and the `envelope` / `mating_features` / `origin` /
`simplifications` / `license` keys every shipped `part.json` carries are read by
no code and reach no tool result — (b) the ability to emit **tagged mounting
interfaces** into the consuming script from a fourth marker region in the
generator, so 8C constraints and Stage 9 joints can anchor to a bearing's bore or
a motor's shaft through the existing addressing layer rather than by hand-
reselecting anonymous geometry, and (c) a provenance discipline (`datasheet`
pointer by URL + sha256, joined to the requirement ledger by an operator-declared
citation) that makes a datasheet number citable instead of recalled. It adds
**no** geom service, **no** new registry kind, and **no** new tool — both existing
store tools keep their names and refusal shapes; `instance_store_part` gains one
optional `instance` argument and richer result fields. It also ships two
fail-closed fixes to machinery that is silently wrong today: a second registry of
one kind is currently dropped by `setdefault`
(`core/src/hephaestus/core/registry/_set.py` lines 33-40) and becomes
`duplicate_registry_kind`; an absent registry `license` currently becomes `""`
and becomes a parse refusal.
**Size: M — the smallest of the five, and larger than the recon's "S" estimate.**
That estimate rested on "more content is the whole job"; the drafted spec
falsifies it. Interface emission is new machinery on three seams — an AST
contract for the generator's interface region, a worker-protocol change
(`geom_type` on each `tag_fingerprints` entry, because the declared-class verdict
is not computable from anything else that crosses the sandbox boundary), and a
`script_contract.md` §5.3 tag-namespace change where `__`-infix instance tags
lose last-wins overwrite semantics.
**Unlocks:** the mechanism vocabulary Stage 9 shipped, applied to hardware the
model did not have to author. The corpus already shows the gap —
`corpus/tasks/gripper-jaws`, `hinge-travel`, `leadscrew-actuator` hand-author
bearings and lead screws that a store should supply.

### 1.2 `MESH_INGEST.md` — mesh and scan ingest (drafted as Stage 12)

Two new import terms (`import_mesh`, `import_point_cloud`) admit an STL/PLY/OBJ
mesh or a point cloud as a **content-addressed, immutable measurement target**
on exactly the `INGEST.md` §1 terms — harness-resolved outside the sandbox,
hashed, staged read-only, threaded through revalidation and staleness. A tenth
pure geom service, `geom.mesh`, parses, canonicalizes and *measures* triangle
arrays (watertightness, self-intersection, component count, quality) without ever
repairing them silently; §4.3 adds `mesh_to_solid` behind a mandatory validity
gate; §5 adds `section_polylines` and `loft_sections`, which is the socket path —
author a parametric socket, section the scan, fit, then offset the fit. §6 adds a
scan-target comparison whose record is a *different type* from `SolidDiff`,
reports no `iou`, and refuses `align="principal"`. Exactly **one** new tool
(`compare_to_scan`); five new injected script names, in two waves. Units are
declared, never inferred, and the declared unit is part of the staged blob's
identity. Tagging mesh topology is refused: triangle indices are an artifact of
file order and canonicalization deliberately destroys that order.
**Size: M.** It reuses G8A's gate skeleton nearly verbatim (confinement,
traversal, symlink refusals, sandbox-denial proof, content-addressed inputs,
determinism, stale-input invalidation) and adds no external binary.
**Unlocks: what a project can START from.** Today the harness can begin from
prose, a drawing image, or a vendor STEP. This is the only one of the five that
adds a fourth door, and it lands *inside* the existing contract rather than
against it — `INGEST.md` §1's shape ("take this file, apply these operations, the
script remains the source of truth") holds for a scan without modification.

### 1.3 `SOLVER.md` — placement proposal and pose solving (drafted as Stage 11)

A **numerical proposal service** over three spaces: 11A solves for declared joint
parameter values (the output is an assignment `{joint_id: value}` — precisely the
shape `declare_pose` already writes), 11B proposes a rigid transform per declared-
free part, 11C proposes declared `Param` values through transient-override
preview builds that are `current=false` by existing contract. Every space
re-measures its own answer through the *existing* `core.assembly` evaluator in a
separate process, and stores a content-addressed, provenance-carrying artifact
that **no tool applies**. There is no writeback: the refusal is structural rather
than a promise, because the proposal document schema is
`additionalProperties: false`, so a `suggested_edit` field cannot be emitted, and
every tool input schema in the repo already is, so one cannot be requested.
Verdicts are honest by construction — `pose_found`, `no_pose_found_from_starts`,
`multiple_solutions_from_starts`, `underdetermined_at_tolerance`,
`overconstrained_at_residual_floor` — and determinism is tiered rather than
claimed uniformly. **+3 tools** (`solve_pose`, `propose_placement`,
`read_proposals`), pins repointed 53 → 56.
**Size: M for 11A alone; L for all three spaces.**
**Unlocks:** it upgrades `reach` from `not_reached_at_samples` to a solved
answer, and turns a `violated` 8C row from "you missed" into "you missed by this
much, in this direction, and here is a set of free-variable values that would not
have". **This is the one capability that reverses a standing rule** —
`ASSEMBLY.md:55-57` — and §4/D1 below is where the operator decides that, not the
spec.

### 1.4 `CAM.md` — 3-axis milling and drilling (drafted as Stage 11)

Generation of a 3-axis milling and drilling program **from features the part
script itself tagged**, against a declared setup (stock, work-holding, WCS,
tools, feeds), plus a sampled geometric verification of that program against the
as-designed solid. Nothing is inferred from geometry: an untagged feature
produces no operation and the coverage check reports it by name. Feeds and speeds
are *transported* from a new content-hash-pinned `tools` registry kind, never
derived. A tenth pure geom service, `geom.toolpath`, owns the offset ladder and a
closed move vocabulary. Verification is the gate's whole substance: declaration
coverage, a post round-trip through the *same parser object* the simulator uses,
sampled material-removal simulation with `iou` explicitly barred as a legal
threshold, gouge and rest-stock verdicts, and collision against a **declared**
scene and nothing else — every collision result stamped
`in_process_stock_not_modelled`. Emission is operator-gated: no model tool writes
a program, `heph cam emit` requires runtime-recorded consent on the `ask_user`
pattern, and emission is refused by rule when the simulation is stale or absent,
when any finding is `crash_risk`, or when a consumed registry is unpinned.
**+16 tools as drafted** (five quartets plus `check_program`); the spec names a
cheaper namespaced alternative (+4) and does not foreclose it. Two new registry
kinds (`tools`, `posts`). One new performance budget, 120 s — the first in the
mission that is not sub-30 s.
**Size: L.**
**Unlocks:** the first artifact this project could produce that, handed to a
machine, moves a tonne of metal under its own power. That asymmetry, not the
geometry, is the whole risk profile, and it is why the safety paragraph is
frozen *content* — part of every emitted program's header and of its content
hash — rather than documentation.

### 1.5 `PHYSICS.md` — structural analysis (drafted as Stage 11)

A bounded, sandboxed, content-addressed **linear-elastostatic solve of one part
under one declared load case**, whose scalar outputs feed a `CHECKS` predicate and
the termination reviewer. Load cases are declared generational project state on
the ledger pattern with compulsory provenance, bindable to Stage 9 poses. The
materials registry gains an optional `mechanical` block, and **most shipped
materials refuse**: `al-6061` resolves to a solvable isotropic block; plywood,
PLA and PETG each resolve to a declared unsupported model and produce
`material_model_unsupported` from phase 1, before any mesh exists. Meshing and
solving are two external binaries (gmsh, CalculiX) run under the existing
bubblewrap sandbox with four additions, pinned by image digest, with mesh, deck,
raw output and result each published as content-addressed artifacts. The verdict
vocabulary encodes what was actually established: `holds_at_mesh` for a single
mesh, `holds_at_converged_mesh` only for a met three-or-more-level refinement
ladder, `not_converged` as neither pass nor `violated`, plus
`linear_range_exceeded` and `small_strain_assumption_violated`, and
`buckling_not_evaluated: true` on **every** record including passing ones. Four
analytic reference cases (uniaxial bar and rigid-body patch test, cantilever,
Lamé cylinder, Kirchhoff plate) are the only oracle for a solver we did not
write. **+4 tools** (the load-case quartet plus `check_loads`); `run_fea` leaves
the deferred section and is deliberately **not** revived as spelled, because an
inline `load_spec` argument is state nothing records. **No geom service** — the
first capability stage since 8B that adds none, because a subprocess cannot live
behind the `geom` boundary under any refactoring.
**Size: XL.**
**Unlocks: what the harness can CLAIM.** "Max von Mises stress under load case L,
over the declared evaluation region, stays below the allowable divided by the
declared safety factor" becomes a predicate that re-derives itself every time the
geometry moves. It also carries the loudest non-certification obligation in the
set, precisely because its results *block*.

### 1.6 The cost signature, side by side

| | Parts store | Mesh ingest | Solver | CAM | Physics |
|---|---|---|---|---|---|
| Drafted stage | 10S | 12 | 11 | 11 | 11 |
| Sub-gates | 3 | 3 | 3 | 4 | 3 |
| **Gate clauses** | **58** | **51** | **56** | **72** | **79** |
| Named new-work items | 34 | 37 | 29 | 39 | 39 |
| New tools | 0 | 1 | 3 | 16 (or 4) | 4 |
| New geom service | — | `mesh` | — | `toolpath` | — (stated as a non-change) |
| New registry kinds | 0 | 0 | 0 | 2 (`tools`, `posts`) | 0 |
| New external binaries | 0 | 0 | 0 | 0 | **2** |
| New corpus split | folds + own | `scan-*` | `solve-*` | `machining-*` | `stress-*` |
| Reverses a standing rule | no | `COMPARE.md` §4 | **`ASSEMBLY.md` §1** | no | rule 5's FEA entry |
| Size | M | M | M / L | L | XL |
| Confirmed findings open | 8 (5 blocking) | 6 (3 blocking) | 6 (3 blocking) | 4 (4 blocking) | 6 (3 blocking) |

**Totals: 316 gate clauses, 178 named new-work items, +24 tools** (53 → 77 as
drafted; 53 → 65 if CAM takes its namespaced quartet), five new Tier 3 corpus
splits, two new geom services, two new registry kinds, two new external binaries.

---

## 2. Sequencing recommendation

### 2.1 The dependency graph

**Hard edges — these are blockers, not preferences.**

1. **Physics → materials mechanical properties.** A stress number cannot be
   computed from `density` alone; the shipped records carry nothing else. The
   registry amendment is cheap (hash-pinning and `heph registry verify` already
   exist) but strictly first.
2. **Physics → a non-Python-binary execution path under bwrap.** The sandbox
   contract launches "interpreter + worker module", one JSON in, one JSON out.
   gmsh and CalculiX are native binaries. This is the largest hidden cost in the
   set and `PHYSICS.md` §5.3 is the only place in the five drafts that names it.
   The escape suite must be extended to a job that execs a native binary.
3. **Physics → *meshing*, which is NOT mesh ingest.** These are conflated
   routinely and must not be. FEA needs BRep → volumetric tet mesh; the harness
   has BRep → surface tessellation, for rendering, behind a prefix `geom` may not
   import. Mesh/scan *ingest* shares a file format with meshing and nothing else.
   **Physics does not depend on scan ingest, and scan ingest does not depend on
   physics.**
4. **Mesh ingest → a mesh value type in geom.** Every geom signature today takes
   an OCP/build123d `AnyShape`. A mesh is the first non-BRep operand, and
   `is_sealed`/`genus` on a shell are not the same facts as watertight /
   self-intersecting / component-count on a triangle soup. One new pure service
   plus a `COMPARE.md` §4 amendment.
5. **CAM → machining data and a *tool* registry — not the parts store.** A cutter
   library is structurally the registry pattern but a different kind. CAM needs
   the parts store's *sibling*, not the parts store.
6. **CAM's 3-axis half → a material-removal verifier.** A gate asserting "the
   G-code parses" is exactly the ambiguity rule 1 forbids. `CAM.md` §5.3 supplies
   the verifier, which is why the toolpath half is schedulable at all — but it is
   a blocker on *evidence*, and evidence machinery is what makes CAM an L.

**Soft edges — composition, not blockage.** Physics ∘ kinematics: load cases at
named poses drop into the existing `poses: [...]` precedent, a strict
enhancement. Parts store ∘ 8C/9: a bearing *is* a joint and a screw *is* a fit,
so the store's value multiplied the day Stage 9 landed. Solver ∘ everything: 11A
consumes the joint set as-is.

**One anti-edge worth stating**, because it is the sequencing mistake most
available: a socket workflow needs scan ingest to *start* and physics to *claim
load transfer*, but the honest intermediate exists in between — a scan-derived
socket graded on declared clearance and relief constraints at named poses claims
fit and does not claim load. Shipping the fit half without the load half is
honest. Shipping either while calling it "validated for load" is the failure this
project exists to prevent.

### 2.2 The recommended order

**1 — Parts store.** First because it is the only one with no hard inbound edge,
no new subsystem, no new tool, and no new evidence machinery; because its value
just multiplied and the corpus visibly shows the gap; and because its two
fail-closed fixes (silent second-registry drop, silent empty license) are latent
wrong answers in shipped code that should not wait behind an XL stage.

**2 — Mesh and scan ingest.** Second because it is the only one that changes what
a project can start from, because it reuses an existing gate skeleton rather than
inventing one, and because every other capability's value is capped by what the
harness can take as input. It has no dependency on any of the other four.

**3 — Solver, pose half first.** Third because 11A shares every piece of
machinery with 11B and scheduling it elsewhere duplicates that machinery, and
because the pose half is where the robotics value is. It is placed after mesh
ingest, not before, because its *permission* question (D1) is the heaviest in the
set and should not be the thing that blocks two stages with no permission
question at all.

**4 — CAM.** Fourth because its four sub-stages absorb a full stage's worth of
new evidence machinery (removal simulation, collision, post round-trip,
vocabulary lint) and two new registry kinds, and because emission — the first
non-inert artifact this project has ever produced — should land against a mature
verifier and a settled safety posture, not against a fresh one.

**5 — Physics.** Last, and by the widest margin. It is the only stage that needs
a second sandbox execution profile, an analytic oracle for software we did not
write, a pinned-solver determinism policy with a declared tolerance, and an
amendment that strikes FEA from rule 5's deferred list by name. Every one of
those is a project-first, and stacking four project-firsts into the earliest
stage is how a gate gets waived.

**Do not run two of these concurrently.** The five drafts collide on: three
claims to Stage 11 and to document number 13; two claims to "the tenth geom
service"; the same `verification.md` golden-provenance block; `COMPARE.md` §4;
the `registries/PUBLISHING.md` kind table; and the tool-count pins, which are two
literal integers that every stage repoints. `MESH_INGEST.md` alone writes its
cross-document clauses *relatively* so it stays correct whichever order the two
land in; the others do not. Serialize, and settle the numbering first (D4).

### 2.3 The robotics and prosthetics answer, stated directly

- **Prosthetics: mesh and scan ingest, unambiguously.** A socket begins with a
  limb scan and nothing in the harness can read one; `COMPARE.md:82-83` closes
  the door explicitly today. This is a capability whose absence is total, not
  partial, and it is the rare frontier capability that lands inside an existing
  contract rather than against it.
- **Robotics: the parts store first, then the pose half of the solver.** Stage 9
  already supplied the mechanism *vocabulary* — joints, poses, sweeps, couplings,
  and the honest `holds_at_samples` verdict set. What is missing is the mechanism
  *hardware* (which the store supplies, with tagged interfaces that 8C and 9
  anchor to directly) and the ability to ask "what joint values put the gripper
  here" (which is 11A, and which upgrades `reach` from a sampled miss to a solved
  answer without weakening a single verdict name).
- **One pick across both: mesh and scan ingest.** It changes what the harness can
  take as **input**. Physics changes what it can **claim**, which is second in
  value and is not credible without the input; and every capability's
  claim-strength is capped by the honesty rules the validation ladder already
  enforces, which is exactly as it should be.

---

## 3. `mission_plan.md` amendment text — ready to paste

Paste the blocks below after the Stage 10 block (`mission_plan.md:700`ff) and
before `## Mission-wide rules`. **Paste only the block for the stage actually
being opened**, at the time it is opened — a stage heading whose spec is still a
draft with open blocking findings is doc drift of exactly the kind
`KINEMATICS.md` records. Two edits to existing text are called out separately at
§3.6 and land only with the stages that need them.

Stage numbers below assume decision **D4 option (a)** — number equals recommended
order. If the operator chooses (b), keep each spec's self-assigned number and
add the ordering sentence of §3.7 instead.

### 3.1 Stage 10S — the component store

> **LANDED 2026-08-29 as Stage 11, and not in this form.** `mission_plan.md`
> carries the authoritative block; this one is the drafting record. It differs in
> four ways a reader must not copy from: the stage and gate names (10S /
> G10S-A…C → **Stage 11 / G11A–G11C**), the suite paths (tests/stage10sa… →
> tests/stage11a…, which do not exist yet — the stage has landed as a plan
> commitment, not as code), the clause counts (23 / 21 / 14 → **24 / 21 / 15**, the
> three extra clauses being `heph registry components`, the `LEGAL-REVIEW.md`
> schema checker, and the negative `datasheet_digest_mismatch` clause), and the
> date. Read `mission_plan.md` for the text that binds.

```markdown
## Stage 10S — The component store (amendment 2026-08-28, maintainer-directed)

Frontier-capability work under the engine-first decision recorded for Stage 8.
Normative spec: `PARTS_STORE.md` (the existing `parts` registry kind gains a
validated component record, tagged mounting interfaces the consuming script can
anchor 8C constraints and Stage 9 joints to, and a datasheet provenance
discipline — no new registry kind, no new tool, no geom service, no solver, no
inertia, no vendor payload). Stage 10S lands in three gated sub-stages, strictly
ordered.

- **10S-A — the component record** (`PARTS_STORE.md` §1, §4–§6, §8): a validated,
  closed-vocabulary component record replacing the opaque `params` blob;
  well-formedness refusals for class, interface, mass, performance-curve and
  datasheet data; the `license` field made required at parse; `duplicate_registry_kind`
  replacing the silent second-registry drop; and the `geom_type` worker-protocol
  field §2.3 needs. Gate G10S-A: `uv run pytest tests/stage10sa -q` exits 0 per
  `PARTS_STORE.md` "Gates" — 23 clauses covering legacy fragment-body invariance
  and digest honesty separately, every named record refusal, contract drift with
  the 53-tool count **unchanged**, seam invariance (no geom service is added),
  worker-protocol drift, tamper and runtime-sandbox refusal, and determinism.
- **10S-B — mounting interfaces as tagged geometry** (`PARTS_STORE.md` §2): a
  fourth generator marker region under an exact AST contract, selectors rooted at
  the published shape and evaluated after placement, instance-scoped `__`-infix
  tag names whose re-tagging is a refusal rather than last-wins, and declared-class
  verification at the caller's `pos`. Gate G10S-B: `uv run pytest tests/stage10sb -q`
  exits 0 per `PARTS_STORE.md` "Gates" — 21 clauses, including placement resolution
  at a non-trivial translation **and** rotation, `interface_not_placed` firing in
  the consumer's build, file IO in the interface region refused before publication,
  the 8C join end to end, the Stage 9 joint join, and byte-identical fragments
  across two processes.
- **10S-C — provenance, federation, and the corpus** (`PARTS_STORE.md` §7–§8):
  the datasheet pointer block, the operator-declared ledger join
  (`cite.component` / `cite.claim`), the `uncited_component_datum` lint rule, and
  merged multi-registry federation with `ambiguous_component_id` rather than a
  precedence rule. Gate G10S-C: `uv run pytest tests/stage10sc -q` exits 0 per
  `PARTS_STORE.md` "Gates" — 14 clauses, including `datasheet_digest_mismatch`
  firing positively on a declared join and staying silent absent one, both
  federated registries' digests visible in their own search results, and the
  component corpus family as its own Tier 3 split, named not skipped.
```

### 3.2 Stage 11 — mesh and scan ingest

> **LANDED 2026-08-29 as Stage 12, and not in this form.** `mission_plan.md`
> carries the authoritative block; this one is the drafting record and must not be
> copied from. It differs in five ways. The stage and gate names (Stage 11 /
> G11A–G11C → **Stage 12 / G12A–G12C**) and the suite paths (`tests/stage11*` →
> `tests/stage12*`) were renumbered by the amendment that opened the stage,
> as this note previously instructed. The date is stale (2026-08-28 →
> **2026-08-29**). The clause counts are unchanged in total — 20 / 13 / 18, 51 —
> but individual clauses were **tightened** by the adversarial pass and its audit
> after this block was drafted, so the summaries below understate several of them:
> notably the ceiling clause now binds the *undeclared*-file path as well as the
> declared one, the eleventh admission refusal is asserted **unreachable** rather
> than skipped, and the round-trip is two clauses (identity as a corruption check,
> fidelity as the clause that actually binds the deflection) rather than one. And
> the landed block carries obligations this one has no text for at all — the
> 53 → 54 tool pin, the unilateral `mesh_import_too_large` rename, the FEA-mesh
> exclusion the `COMPARE.md` §4 replacement must preserve, the clinical-claim
> refusal, the lattice deferral, and the constants left unvalued under rule 4.
> Read `mission_plan.md` for the text that binds.

```markdown
## Stage 11 — Mesh and scan ingest (amendment 2026-08-28, maintainer-directed)

Normative spec: `MESH_INGEST.md` (a mesh or point cloud admitted as an immutable,
content-addressed measurement target on the `INGEST.md` §1 terms — no feature
recognition, no surface reconstruction, no mesh-native modeller, no tagging of
mesh topology, and no clinical claim). Mission rule 5's deferred list is
untouched: mesh ingest was never on it, which is precisely why it needs a new
gated stage rather than a waiver. Stage 11 lands in three gated sub-stages,
strictly ordered.

- **11A — admission, canonicalization, facts** (`MESH_INGEST.md` §1–§3):
  `import_mesh` / `import_point_cloud` as script terms; the closed format set;
  declared units, with the declared unit part of the staged blob's identity; two
  named hashes (raw file bytes and canonical geometry) whose meanings are
  distinct; ceilings refused before the parser runs; and `hephaestus.geom.mesh` as
  a tenth pure service measuring quality without silently repairing it. Gate G11A:
  `uv run pytest tests/stage11a -q` exits 0 per `MESH_INGEST.md` "Gates" (20
  clauses); the geom boundary tests admit `mesh` as a pure service.
- **11B — mesh → B-rep, sections, the socket path** (`MESH_INGEST.md` §4–§5):
  `mesh_to_solid` behind a mandatory validity gate, `section_polylines`,
  `loft_sections`, and the fit-then-offset socket design. Gate G11B:
  `uv run pytest tests/stage11b -q` exits 0 per `MESH_INGEST.md` "Gates" (13
  clauses), including the sew-derived goldens carrying an OCCT-version sidecar and
  refusing a mismatched (image, OCCT) pair.
- **11C — scan scoring, surface, corpus** (`MESH_INGEST.md` §6–§7): the
  `ScanDistance` record and the fields it deliberately lacks, the `declared`
  alignment mode, `compare_to_scan` as the single new tool, `m.scan_diff` on the
  part-scope facade, reviewer delivery of mesh-quality facts, and the `scan-*`
  corpus family. Gate G11C: `uv run pytest tests/stage11c -q` exits 0 per
  `MESH_INGEST.md` "Gates" (18 clauses); the `scan-*` family is its own split with
  its own coverage constant and threshold, baselined on its own first measurement
  with the reference model at ≥3 seeds, neither compared against nor averaged into
  the v1/v2/v3 baselines.
```

### 3.3 Stage 12 — pose and placement solving

```markdown
## Stage 12 — Pose solving and placement proposal (amendment 2026-08-28, maintainer-directed)

Normative spec: `SOLVER.md`. This stage carries the one rule reversal in the
frontier set and the ruling that bounds it, recorded here rather than in the spec:
**the solver PROPOSES.** Its output is a content-addressed, provenance-carrying
measurement artifact; no tool, CLI verb, or agent path applies it; applying is an
authoring act performed through the existing `edit_part` / `write_part` /
`set_params` surface and shows up in git as a normal diff. `ASSEMBLY.md` §1's
first two sentences stay normative verbatim — "Scripts position geometry;
constraints verify, they never move anything. A constraint that requires motion
to satisfy is simply unsatisfied." — and the parenthesis "(A placement solver, if
ever, is a separate stage.)" is replaced by the proposal wording of `SOLVER.md`'s
amendment manifest. **Writeback — a solver that authors a script edit — is
refused by this amendment and enters, if ever, only by a further amendment that
must reverse this sentence explicitly.** Stage 12 lands in three gated sub-stages,
strictly ordered.

- **12A — pose solving** (`SOLVER.md` §2A): inverse kinematics over declared joint
  parameters, with `pose_found` / `no_pose_found_from_starts` /
  `multiple_solutions_from_starts` as verdicts, independent re-measurement in a
  separate process, and `solve_pose` on both profiles. Gate G12A:
  `uv run pytest tests/stage12a -q` exits 0 per `SOLVER.md` "Gates" (17 clauses),
  including the amendment-drift clause that asserts `tool_schema.md` no longer
  says "There is no solver." in the same change that adds the `solve_pose`
  heading.
- **12B — placement proposal** (`SOLVER.md` §2B, §7–§8): a rigid transform per
  declared-free part as a proposal artifact; the reformulation-identity gate; the
  named over/under-determined verdicts; provenance, staleness, and the structural
  no-writeback assertion. Gate G12B: `uv run pytest tests/stage12b -q` exits 0 per
  `SOLVER.md` "Gates" (26 clauses), including that a `converged_at_tolerance`
  proposal leaves the `AssemblyStatus` row saying `violated` and clears nothing in
  the reviewer.
- **12C — parameter space and the bench** (`SOLVER.md` §2C): free variables that
  are declared `Param`s, evaluated by transient-override preview builds that are
  `current=false` by contract and publish nothing; and the `solve-*` corpus family
  as its own Tier 3 split. Gate G12C: `uv run pytest tests/stage12c -q` exits 0
  per `SOLVER.md` "Gates" (13 clauses).
```

### 3.4 Stage 13 — computer-aided manufacturing

```markdown
## Stage 13 — Computer-aided manufacturing: 3-axis milling and drilling (amendment 2026-08-28, maintainer-directed)

Normative spec: `CAM.md`. CAM was never on rule 5's deferred list, so it enters by
this new gated stage, which is the whole mechanism rule 5 prescribes. **Safety
posture, recorded as part of the amendment and binding on every sub-stage:** the
model may declare setups, stock, fixtures, WCS, operations and budgets and may
call `check_program`; **no model tool causes a runnable program to reach the
filesystem**; emission is the operator CLI verb `heph cam emit` under
runtime-recorded consent; `export_part` gains no CAM format value; and the frozen
`SAFETY_PARAGRAPH` of `CAM.md` §0.1 is the first region of every emitted program
header and part of its content hash. Stage 13 lands in four gated sub-stages,
strictly ordered; **nothing is emitted before 13D.**

- **13A — machining DFM packs and the tool registry, no CAM** (`CAM.md` §6, §3.5):
  `cnc_mill` and `cnc_router` DFM packs closing the documented hole that
  `cnc_router` is `heph init`'s default `part.process` with no pack behind it; a
  fifth registry kind `tools`; and declared machining blocks on the materials
  records. Gate G13A: `uv run pytest tests/stage13a -q` exits 0 per `CAM.md`
  "Gates" (10 clauses).
- **13B — declared state and toolpath geometry, nothing emitted** (`CAM.md` §3–§4):
  the setup/stock/fixture/WCS/operation quartets, the CAM tag prefixes, and
  `hephaestus.geom.toolpath` as a pure service with a closed move vocabulary and a
  closed refusal set. Gate G13B: `uv run pytest tests/stage13b -q` exits 0 per
  `CAM.md` "Gates" (24 clauses), the last of which is a filesystem assertion that
  no 13B code path writes a program.
- **13C — verification** (`CAM.md` §5): declaration coverage, post round-trip
  through the same parser object the simulator uses, sampled material-removal
  simulation with `iou` barred as a threshold, gouge and rest verdicts, collision
  against the declared scene and nothing else, and the vocabulary lint. Gate G13C:
  `uv run pytest tests/stage13c -q` exits 0 per `CAM.md` "Gates" (22 clauses),
  including the 120 s `check_program` budget bound to a **counted curve** of OCCT
  booleans rather than to one fixture. `verification.md` gains that budget;
  budgets tighten, never loosen — if the reference setup cannot meet it, the
  reference setup shrinks.
- **13D — emission, under operator consent** (`CAM.md` §7, §1.4–§1.5): the `posts`
  registry kind, the declarative emitter, consent gating, and the four
  refuse-by-rule conditions. Gate G13D: `uv run pytest tests/stage13d -q` exits 0
  per `CAM.md` "Gates" (16 clauses), including the header asserted byte-for-byte
  against a golden and `SAFETY_PARAGRAPH` asserted byte-equal to §0.1.
```

### 3.5 Stage 14 — structural analysis

```markdown
## Stage 14 — Structural analysis (amendment 2026-08-28, maintainer-directed)

Normative spec: `PHYSICS.md` (a bounded, sandboxed, content-addressed
linear-elastostatic solve of one part under one declared load case, feeding a
`CHECKS` predicate and the termination reviewer — not a certification, not a
viewer, not a geom service, and not dynamics, plasticity, contact, thermal,
buckling or fatigue). **This amendment removes FEA from mission rule 5's deferred
list**; STEP import, community sharing and kerf-aware auto-nesting stay deferred,
untouched. `KINEMATICS.md` §0's stale "Stage 10 candidate" forward reference is
corrected to this stage in the same change. Stage 14 lands in three gated
sub-stages, strictly ordered, and the ordering is itself asserted rather than
asserted about: no G14A clause may depend on a mesher, a solver, a deck writer, a
`CHECKS` resolver, or a tool.

- **14A — properties, units, and load-case state** (`PHYSICS.md` §1–§4): the
  materials `mechanical` block with most shipped materials declaring an
  unsupported model; one consistent unit system stated once; load cases as
  generational project state with compelled provenance, pose binding, and the
  phase-1 refusals that are decidable without a solve. Gate G14A:
  `uv run pytest tests/stage14a -q` exits 0 per `PHYSICS.md` "Gates" (23 clauses),
  the last of which runs the whole suite with `gmsh` and `ccx` absent from the
  sandbox `PATH` and `hephaestus.core.fea` not importable.
- **14B — mesh, solve, and the analytic suite** (`PHYSICS.md` §5–§6, §10): two
  pinned external binaries under the existing sandbox with the four additions of
  §5.3; mesh, deck, raw output and result each content-addressed; the four
  analytic reference cases; and the convergence ladder that alone licenses
  `holds_at_converged_mesh`. Gate G14B: `uv run pytest tests/stage14b -q` exits 0
  per `PHYSICS.md` "Gates" (38 clauses), image-pinned clauses carrying the
  `CI_ONLY` marker rather than skipping silently. `verification.md`'s golden
  provenance rule gains the mesher and solver pins; a digest change that moves
  either is a solver re-baseline under the same rule.
- **14C — the predicate, the ladder, and the bench** (`PHYSICS.md` §7–§8): the
  `m.load_case` project-scope read surface, the load-case quartet plus
  `check_loads`, reviewer delivery including the non-certification sentence
  verbatim, blocking-by-rule for `violated` / `not_converged` /
  `linear_range_exceeded` / `unresolvable`, and the `stress-*` corpus family. Gate
  G14C: `uv run pytest tests/stage14c -q` exits 0 per `PHYSICS.md` "Gates" (18
  clauses); `REVIEWER_TOOLS` is asserted **unchanged** — load results reach the
  reviewer as context, never as a tool.
```

### 3.6 Two edits to existing text, each landing with its own stage

1. **Rule 5, with Stage 14 only.** `mission_plan.md:815-817` reads "Deferred items
   (FEA, STEP import, community sharing, kerf-aware auto-nesting) enter only by
   amending this plan with a new gated stage." Strike `FEA, ` when the Stage 14
   block lands, and not before. The three others stay.
2. **The `LEGAL-REVIEW.md` schema, with Stage 10S.** `mission_plan.md:643-645`
   declares four scope fields; none covers third-party component data. Add a fifth
   required field — *third-party component data provenance and terms: which
   standards were used, that no vendor payload is vendored, and that every
   `datasheet` pointer's terms permit reference-by-citation* — checked by the same
   CI schema check as the other four. Publication of a component pack is blocked
   until it is signed off; development is not, matching
   `mission_plan.md:448-449`.

### 3.7 If the operator keeps the self-assigned numbers instead (D4 option b)

Replace the stage numbers above with each spec's own (10S, 12, 11, 11, 11 — which
requires renaming three of them anyway) and add this sentence to the first block
pasted, on the `mission_plan.md:399` "Stage ordering amendment" precedent:

> Execution order is 10S → mesh ingest → solver → CAM → structural analysis,
> which is not the numeric order; stage numbers record identity, not schedule,
> exactly as the 2026-07-26 ordering amendment moved Stage 7H after Stage 8.

---

## 4. Decisions the operator must make

Each is a question, its options, and a recommendation. None of them is a spec
author's to settle.

### D1 — Does the solver's reversal of the `ASSEMBLY.md` no-solver rule stand?

`ASSEMBLY.md:55-57` says, in the imperative: "**NO SOLVER.** Scripts position
geometry; constraints verify, they never move anything. A constraint that
requires motion to satisfy is simply unsatisfied. (A placement solver, if ever, is
a separate stage.)" Four modules restate it in code. `SOLVER.md` §1.2 enumerates
the seven properties that sentence protects — reproducibility defined off the
script, git as the owner of design state, one home per number, a diff that
carries intent, a verdict vocabulary that means something, a closed evaluation
loop that stays broken, and compulsory requirement provenance.

**Options.**
- **(a) Reject.** No solver of any kind. Cost: `reach` stays a sampled miss
  forever; a `violated` row keeps carrying a residual nobody can act on without
  hand arithmetic over a coupled system.
- **(b) Approve only the anchor-to-point pose solve.** The inverse of `reach`,
  over declared joint parameters, touching no constraint set. **This needs no rule
  change at all** — it is arithmetic over declared parameters and a solved
  assignment is a pose, which `declare_pose` already writes. Cost: the
  constraint-id target of §2A, and all of 11B/11C, do not exist.
- **(c) Approve the proposal-only reversal in full** — `SOLVER.md` §1.3's DECISION:
  the solver proposes, output is a measurement artifact, nothing applies it,
  applying is an authoring act through the existing edit surface. The seven
  properties survive property-by-property in that section's table.
- **(d) Approve (c) plus writeback** — the solver drives `edit_part` itself.

**Recommendation: (c), with (d) refused in the amendment's own text, and with the
sub-stage split tightened.** (c) is the option that keeps every property (b)
keeps and adds the capability. (d) resolves the writeback ambiguity by model
interpretation — a +0.42 mm X delta can be authored as a change to
`hc.joint_clear`, a part param, or a literal, and three of those change other
parts — which is exactly what `VALIDATION.md` gates rather than trusts; it also
collides with the tag-drift soft failure, where a resolved selector may select a
different face and nothing in the resolution detects it. Two tightenings to apply
with the approval: **(i)** split the first sub-stage so the anchor-to-point target
(legal today) is separable from the constraint-id target (legal only under the
amendment), so a reviewer can see which clauses depend on the reversal; **(ii)**
put the writeback refusal in the *plan*, not only the spec, so a later drafter
must reverse a dated maintainer amendment rather than a paragraph.

### D2 — What is the CAM safety posture: how close to a running machine?

`CAM.md` is the only spec whose output, misused, injures a person. It answers this
question itself, well, but the answer is a product decision.

**Options.**
- **(a) Cut-file half only.** Stop at 2D/2.5D: kerf, nesting, cutfile layers, DXF
  round-trip — nearly free against machinery that already exists. Never emit
  G-code. Cost: no 3-axis capability at all.
- **(b) Generate and verify, never emit.** Land 13A–13C; the harness declares
  setups, generates toolpaths, and reports `matches_at_samples` /
  `gouge_at_samples` / `rest_at_samples` / collision findings — and produces no
  runnable file. Drop 13D and the `posts` registry from this stage.
- **(c) Emit under operator consent, as drafted.** 13A–13D, with the consent gate,
  the four refuse-by-rule conditions, the in-band safety header, and
  `export_part` untouched.
- **(d) A model-facing emit tool.** Refused by the spec; listed only for
  completeness.

**Recommendation: (b) as the first landing, with (c) held as its own later
decision, and (d) refused permanently in the amendment text.** The argument is
`CAM.md` §1.4's own: declaration is cheap and reversible, emission is neither.
(b) captures the whole verification capability — which is where the engineering
value and all the gate substance are — while the first artifact that commands a
machine waits for the removal simulator and the collision check to have *archived
evidence in the pinned image*, not just passing clauses. Two conditions on later
approving (c): the `SAFETY_PARAGRAPH` byte-for-byte clause and the
`in_process_stock_not_modelled` stamp must both be in force before emission
exists, and the operator sheet must be reviewed by someone who runs a machine.
Note that (b) is not free of the honesty problem: a report saying
`matches_at_samples` will be read by some users as "verified", which is why the
vocabulary lint and the closed claim set are 13C clauses and not documentation.

### D3 — What is the parts-store licensing discipline, and who signs it?

The store's value is mostly *not geometry* — a motor is a mass, a bolt circle, a
shaft axis, a torque curve, and a datasheet. Every one of those except the
geometry is somebody else's published data.

**Options.**
- **(a) Clean-room only.** Independently authored parametric envelope geometry
  plus dimensions from published standards; no `datasheet` block at all. Cost: a
  number in a design still cannot cite its source, which is the failure the spec
  exists to fix.
- **(b) Clean-room geometry + pointer-only datasheets, as drafted.** Vendorable:
  generator source, dimensions from a published standard, and the minimum set of
  derived numeric facts the geometry and its declared interfaces require.
  Not vendorable under any framing: vendor CAD payloads, vendor PDFs, artwork,
  bulk table transcriptions, anything under unread terms, or a vendor trademark as
  a component id. The `datasheet` block is `{publisher, document_title, revision,
  url, sha256, retrieved}` — a pointer that redistributes nothing and that nothing
  in the harness ever fetches, joined to the ledger by an **operator-declared**
  citation.
- **(c) (b) plus third-party federated packs** under their own licenses, resolved
  through the merged federation of 10S-C.
- **(d) Vendor CAD payloads vendored into a registry tree.**

**Recommendation: (b) now; (c) later, only behind both the federation sub-gate and
the fifth `LEGAL-REVIEW.md` scope field; (d) never.** Three tightenings ship with
(b) and are already gate clauses: a publish-time scanner refusing any file in a
`parts` tree that is not `registry.toml` / `part.json` / `generator.py` / `*.md`
(`vendored_third_party_payload` — blunt on purpose, since a store tree has no
legitimate reason to contain a binary and the Merkle digest would otherwise pin
and redistribute it); `trademark_in_component_id` against a maintained deny-list;
and the registry `license` field becoming a parse-time requirement. **The operator
must decide who signs the fifth scope field**, because `LEGAL-REVIEW.md` does not
exist yet and its existing four fields do not cover component data — and note the
honest limit the spec itself states: the deny-list check will be imperfect, so the
real control remains the human review requiring a reviewer other than the author
for all registry content.

### D4 — Stage and document numbering

> **Numbering resolved, 2026-08-28.** D4 option (a) was applied to all five
> drafts in one pass, at the moment it was free: `13 PARTS_STORE` (Stage 11),
> `14 MESH_INGEST` (Stage 12), `15 SOLVER` (Stage 13), `16 CAM` (Stage 14),
> `17 PHYSICS` (Stage 15) — document number equals recommended execution order.
> Gate names and the per-stage test suite path suite paths were renumbered with the headers,
> and MESH_INGEST's collision note was rewritten to record the allocation rather
> than the collision. D4 below is retained as the reasoning behind that choice.


Three drafts claim Stage 11 and document number 13 simultaneously; two claim "the
tenth geom service". Two specs cannot both be Stage 11: a gate is a command, and
two documents issuing `uv run pytest tests/stage11a -q` over different suites
makes both unsatisfiable.

**Options.** **(a)** Number equals recommended order — renumber four drafts now,
while they are still drafts and no gate has ever run, and §3's blocks apply as
written. **(b)** Keep each self-assigned number and record execution order in a
separate sentence, on the `mission_plan.md:399` ordering-amendment precedent.
**(c)** Decide lazily, at each promotion.

**Recommendation: (a).** It costs one mechanical pass per draft (header, gate
names, the per-stage test suite path paths, cross-references) at the only moment that pass is
free, and it makes the plan readable in the way its readers already expect. (c) is
the one to avoid: it guarantees that the second and third specs to promote will
each rewrite clauses that cite the first. Whichever is chosen, fix the "tenth geom
service" ordinal in whichever of `MESH_INGEST.md` / `CAM.md` lands second — it
becomes the eleventh.

### D5 — Do the 30 confirmed findings block the amendments?

The adversarial pass returned 30 confirmed findings across the five specs — **18
blocking, 12 major** — and several are of the form "these two gate clauses cannot
both pass" (see §5.1).

**Options.** **(a)** Amend now, fix findings during implementation. **(b)** Close
each spec's *blocking* findings before its own amendment lands; majors during
implementation. **(c)** Close all 30 for a spec before its amendment lands.

**Recommendation: (c) for the spec being promoted, one spec at a time — and never
promote all five at once.** Rule 1 makes a gate a command; a stage heading that
cites a spec containing a mutually unsatisfiable clause pair has promoted an
unrunnable command, and the repair is then an amendment to an amendment. The
findings are cheap to close relative to the stages they gate — most are a
clause-siting or an ordering fix, which is precisely what "resolve by tightening"
means. The single most instructive one to fix first is `PHYSICS.md`'s
`FEA_RLIMITS` `nproc` finding: the declared value would reproduce a sandbox
start-up failure this tree has already recorded and fixed, which is exactly the
class of defect a spec review exists to catch before a stage opens.

### D6 — What reference model baselines five new Tier 3 splits?

Rule 3 (`mission_plan.md:807-808`) names one reference model per mission epoch,
and changing it re-baselines thresholds explicitly in a PR. These five stages add
five new corpus families — `scan-*`, `solve-*`, `machining-*`, `stress-*`, and a
component family — each of which is its own split under `VALIDATION.md` §1 as G9C
restated it, each baselined on its own first measurement at ≥3 seeds, none
averaged into v1/v2/v3.

**Options.** **(a)** Keep the current reference model and baseline each new split
on its own first measurement, however low. **(b)** Name a stronger reference model
for the epoch and re-baseline every existing threshold in one PR. **(c)** Follow
the `tests/stage7h/CI_ONLY.md` precedent G9C used and land the Tier 3 clause
**named, not skipped**, deferring the measurement.

**Recommendation: (a) plus (c) — and one prohibition.** The prohibition is the
important half: **do not let a Tier 3 pass rate stand in for Tier 1 correctness**,
which is the specific trap in the physics stage. A stress threshold on a simulated
number is the "volume window" anti-pattern one level up. Solver correctness lives
in the analytic benchmarks; scan-fidelity correctness lives in the round-trip
tolerance; CAM correctness lives in the removal simulation. Whether the reference
model can *drive* those capabilities is a separate, honestly-baselined question,
and (b) is worth raising on its own merits but should not be entangled with
opening a stage.

---

## 5. What this costs, and what could go wrong

### 5.1 The bill, stated plainly

**316 gate clauses. 178 named new-work items. Up to +24 tools against a surface
pinned at 53 in two literal places. Five new Tier 3 corpus splits. Two new geom
services. Two new registry kinds. Two new external binaries inside the sandbox.
One new pinned Python dependency. Thirteen normative documents amended.** In the
Stage-9 unit of §1: roughly **eight Stage-9-equivalents**, distributed about
1 : 1.2 : 1.3 : 2 : 2.5 across parts store, mesh ingest, solver, CAM, physics.
That is an estimate read off clause counts and seam counts, not a measurement, and
it should be treated as the *lower* bound for the two stages that open a
project-first — a native binary under bwrap, and an artifact that commands a
machine — because neither has a precedent in this tree to estimate from.

Every tool costs five generated drift-tested artifacts, a per-profile decision,
the `reviewer` subset decision, dispatch tests on both profiles, and a
`tool_schema.md` heading, all under one drift gate. At 53, tool-count discipline
is a design constraint rather than a preference, and the 8A/8B lever — put the
capability in the script or the `CHECKS` facade, not on the tool surface — is what
kept mesh ingest at +1 and the parts store at 0. **CAM's +16 is the outlier and
should be argued for or reduced to the namespaced +4 before its amendment lands.**

And 30 confirmed findings remain open across the five drafts (18 blocking, 12
major): 8 in `PARTS_STORE.md`, 6 each in `PHYSICS.md`, `SOLVER.md` and
`MESH_INGEST.md`, 4 in `CAM.md`. Several are mutually-unsatisfiable clause pairs —
CAM's vocabulary lint versus its mandatory header, the parts store's byte-identical
fragment golden versus a fragment header that embeds a Merkle root this stage
moves, physics's result-determinism clause versus its own per-run scratch path.
Each is closable by tightening; none is closed today.

### 5.2 The eight things most likely to go wrong

1. **The physics oracle problem.** The four analytic cases are simple geometry
   with closed-form answers; real corpus parts are neither. A green G14B can
   coexist with a well-meshed wrong answer on a part shaped unlike a bar, a
   cantilever, a cylinder or a plate. The convergence ladder and the
   `holds_at_converged_mesh` / `holds_at_mesh` split are the mitigation; the
   residual risk is real and should be stated in the stage report, not just the
   spec.
2. **The first non-inert artifact.** Even with consent gating, refuse-by-rule
   conditions, an in-band safety header and 13D placed last, CAM emission is the
   first output of this project that can hurt someone. The named risk is not a bad
   toolpath — it is a good toolpath run in a shop whose vise, stack-up and travel
   limits the harness never saw, by a person who read `matches_at_samples` as
   "verified".
3. **Blocking-by-rule fatigue.** Constraints block, motion blocks, loads would
   block, programs would block — four classes of finding that are blocking by rule
   and waivable only by the operator. The never-green invariant is the project's
   best idea; it degrades into a rubber stamp the moment waiving becomes routine.
   Watch the waiver rate as a first-class metric before adding the fourth class.
4. **Tool-surface inflation.** 53 → 77 dilutes every per-profile decision and
   multiplies five generated artifacts by 24. The counter-lever exists and is
   proven; it has to actually be pulled, most obviously on CAM.
5. **Determinism becoming conditional in three unrelated places.** The solver
   tiers determinism (D1/D2) by solve space; FE results are per-host and exclude
   one named field; sew-derived goldens become (image, OCCT-version) pairs. Each is
   individually honest and each is the right call. Together, "identical inputs ⇒
   identical bytes" stops being one sentence and becomes three qualified sentences
   in three documents, and nobody reads three.
6. **Cross-spec collision during implementation.** Five drafts touch
   `verification.md`'s golden block, `COMPARE.md` §4, the registry kind table, and
   two tool-count integers. Only `MESH_INGEST.md` writes its cross-document clauses
   relatively. Serializing the stages is the mitigation; settling D4 first is the
   precondition.
7. **Over-read of honest verdicts.** `holds_at_samples`, `matches_at_samples`,
   `holds_at_converged_mesh`, "fit at samples, no load claim" — the vocabulary is
   deliberately weak and will be quoted strongly by someone downstream. Both the
   scan and physics specs refuse clinical and certification claims in contract
   form; that discipline has to survive into the README, the workspace UI, and any
   external write-up, which are outside every one of these gates.
8. **Scope leaking back through the door rule 5 opens.** Striking FEA from the
   deferred list is the correct use of rule 5. The failure mode is the next
   capability arriving as "and while we're here" rather than as its own dated,
   gated stage — which is exactly what these five drafts, and this document, exist
   to prevent.

### 5.3 What would make this cheaper, honestly

Three levers, in order of value. **Land the parts store and mesh ingest first and
stop to look**: together they are ~2.2 units, carry no reversal and no new binary,
and between them answer both the robotics and the prosthetics question — if the
value shows up there, the case for the expensive three is evidence rather than
argument. **Take CAM's namespaced quartet** (+4 instead of +16) and land 13A–13C
only, which removes a registry kind, a consent mechanism and the entire emission
surface from the first landing. **Split the solver at the amendment line**, taking
the anchor-to-point pose solve (which needs no rule change) as its own sub-stage,
so the reversal is a decision made against working machinery rather than against a
document.
