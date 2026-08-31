<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# 16 — Computer-aided manufacturing: 3-axis milling and drilling (Stage 14)

The number is the next free one in the repo's sequence: `architecture.md` is 00,
`script_contract.md` 01, `tool_schema.md` 02, `verification.md` 03,
`mission_plan.md` 04, `repo_conventions.md` 05, `VALIDATION.md` 06, `INGEST.md`
07, `COMPARE.md` 08, `ASSEMBLY.md` 09, `EXTERNAL_EVAL.md` 10, `KINEMATICS.md`
11, `INTERFACE.md` 12. This is 13.

**DRAFT — pending a `mission_plan.md` amendment.** Revised after an adversarial
pass against the codebase: four blocking findings folded in — the offset
ladder's termination (§4.1, §4.3), the lint/header contradiction (§1.1, §1.5,
§0.1), two refusals filed at a lifecycle point that could not compute them
(§3.1, §4.3, §5.3), and a collision check that claimed machinery §11 never named
(§5.5). Each fix tightened a clause or named new work; none waived one.
Nothing in this document is binding. Promotion follows the
`ASSEMBLY.md` / `COMPARE.md` / `KINEMATICS.md` pattern exactly: an adversarial
pass against the codebase, then a dated `mission_plan.md` amendment carrying a
Stage 14 heading with the G14A–G14D gate summaries and citing this spec. Until
that amendment lands, CAM is not in mission scope at all — mission rule 5
(`mission_plan.md` "Mission-wide rules" 5) names the deferred set (FEA, STEP
import, community sharing, kerf-aware auto-nesting) and CAM is not in it, so
CAM enters *only* by amending the plan with a new gated stage. This document is
the proposal for that stage, not the stage.

## Amendment manifest

Every existing normative document this spec would change, and exactly what
changes in each. Each amendment lands with the sub-stage whose machinery ships
it — amending a document before its machinery exists is doc drift
(`KINEMATICS.md` header, closing paragraph).

| document | change | lands with |
|---|---|---|
| `mission_plan.md` | New dated **Stage 14** heading naming 14A–14D and carrying gates G14A–G14D, citing this spec. Mission rule 5's deferred list is **not** touched: CAM was never on it, and a new gated stage is the whole mechanism rule 5 prescribes. | 14A |
| `tool_schema.md` | New heading **"Manufacturing setups"** with the declare/update/read quartets of §3 and `check_program` (§9). `export_part`'s format enum is **not** extended — a program is not an export (§1.4); emission is the separate operator verb `heph cam emit`. The Deferred section gains a reserved `emit_program` slot naming this spec, on the `run_fea` precedent (`tool_schema.md:1487-1491`). | 14B (quartets), 14C (`check_program`), 14D (Deferred slot) |
| `script_contract.md` §5.3 | The closed §5.3 tag-prefix vocabulary that `cutfile.layer_for_tag` already reads (`core/src/hephaestus/core/cutfile.py:117-144`) gains the CAM prefixes `mill_`, `drill_`, `pocket_`, `profile_`, `face_`, `keepout_` (§3.7). §5.2 is **not** amended: the nine assignable `part.*` fields stay nine (`script_contract.md:115-144`), and no CAM state enters a part script. | 14B |
| `script_contract.md` §6 | The project-scope `CHECKS` measurement facade gains `m.program(setup_id)` — the read surface of §5.9's result record — on the `m.sweep` precedent (`KINEMATICS.md` §4). The part-scope facade does not carry it. | 14C |
| `VALIDATION.md` §5 | The termination reviewer receives `ProgramStatus` (§5.9); a CAM check in any non-success state, and any `unresolvable` setup, is a **blocking finding by rule**, stamped from the engine's status and never solicited from the reviewer — the never-green invariant extended a third time, the same mechanism as the constraint rule (`VALIDATION.md:308-315`) and the motion rule (`:317-330`). | 14C |
| `COMPARE.md` §1 | `solid_diff` gains no new function. The **amendment is a stated restriction**: for material-removal verification the `iou` field of `VolumeDiff` is not a legal threshold (§5.3), and §1's "thresholds do not live here" sentence gains the CAM-side owner. `COMPARE.md` §4's "no mesh-based comparison path" is unchanged and this spec adds none. | 14C |
| `architecture.md` §3.6 (registries) | A **fifth registry kind**, `tools`, added to `BUNDLED_KINDS` / `RegistryKind` (`core/src/hephaestus/core/registry/_layout.py:38-41`), and a **sixth**, `posts`, for controller dialects (§7). Both are content-hash-pinned by the existing Merkle digest (`registry/_digest.py:53-71`) and the existing `[registries]` pin table (`registry/_pins.py:41-52`); neither adds a fetch, verify or pin mechanism. | 14A (`tools`), 14D (`posts`) |
| `registries/dfm/registry.toml` | Two new packs, `cnc_mill` and `cnc_router` (§6), closing the documented hole that `cnc_router` is the default `part.process` written by `heph init` (`core/src/hephaestus/core/cli_init.py:64`). **`cnc_router` shipped as issue #28** (existing DFM machinery, no CAM, no mill pack). `cnc_mill` remains 14A. | 14A |
| `registries/materials/*.json` | `al-6061.json` and `plywood-baltic-birch.json` gain a **declared** machining block (§6.2). The prose in `al-6061.json`'s `notes` — "3 mm end mill => 1.5 mm minimum internal radius", "pockets deeper than about 4x the tool diameter chatter", "thin webs below roughly 1 mm distort" — stays as prose *and* becomes numbers a predicate reads. Contextual notes are never machine-checkable (`architecture.md:406-410`); that is exactly the defect this closes. | 14A |
| `verification.md` "Performance budgets (Tier 1)" (`verification.md:210-218`) | One new budget, and an honest one: **`check_program` on the reference setup ≤ 120 s wall clock**, which is 4× the reference-shelf full-build budget and is the first budget in the mission that is not sub-30 s. §5.8 states why, and states plainly that if the reference setup cannot meet it the *gate is tightened by shrinking the reference setup*, never by raising the budget — budgets tighten, never loosen, by amendment (`verification.md:218`). The budget is paired with clause (G14C-12), which counts the collision check's OCCT booleans as a function of sample count, so the number bounds a curve rather than one fixture. | 14C |
| `EXTERNAL_EVAL.md` | Unchanged. CAM produces no CADGenBench submission and no external score. | — |
| `INTERFACE.md` | Unchanged in this spec. A workspace CAM panel is a later amendment; nothing here adds a web surface, and §1.4's operator gate is a CLI verb precisely so that it does not acquire one by default. | — |

Design premise: every artifact Hephaestus has ever produced is **inert**. A
wrong DXF wastes a sheet; a wrong drawing misleads a reader; a wrong STEP is
someone else's input. A machine program is the first artifact this project
could produce that, handed to a machine, moves a tonne of metal at speed under
its own power — and the blast radius is a broken tool, a scrapped part, a
wrecked spindle, a thrown workpiece, an injured operator. That asymmetry, not
the geometry, is what makes this the highest-risk specification in the set, and
it is why safety and honesty discipline is §1 rather than an appendix.

---

## 0. What this is, what it is not, and what it does not certify

**What it is.** Hephaestus CAM is the generation of a **3-axis milling and
drilling program from features the part script itself tagged**, against a
**declared** setup (stock, work-holding, work coordinate system, tools, feeds),
plus a **sampled geometric verification** of that program against the
as-designed solid using the existing `hephaestus.geom.compare` machinery
(`COMPARE.md` §1). Operations come from declarations, never from feature
recognition. Every number that commands the machine is transported from
declared data, never derived.

**What it is not.**

- **Not feature recognition.** `INGEST.md` §1 already states it: "Feature
  recognition is explicitly out of scope: no inference of parameters or design
  intent from B-rep" (`INGEST.md:26`). CAM does not relax this by one inch.
  `cutfile.py` records the reason in the shape that matters here: "Nothing is
  inferred from geometry size, depth or position — a heuristic that silently
  promotes a pocket to an engrave pass is exactly the failure mode that scraps a
  sheet, so an untagged contour is always cut" (`cutfile.py:41-44`). The CAM
  analogue of "always cut" is **"never machined"**: an untagged feature produces
  no operation, and the coverage check (§5.1) reports it by name.
- **Not a CAM kernel.** No surfacing (scallop, parallel, waterline), no 4- or
  5-axis, no adaptive/trochoidal clearing, no rest-machining strategy search, no
  automatic setup planning, no automatic tool selection. §2 lists exclusions by
  name.
- **Not dynamics.** `KINEMATICS.md` §0 already refuses forces, torques,
  friction, and time (`KINEMATICS.md:49-54`). Nothing here computes a cutting
  force, a deflection, a chatter stability lobe, a tool life, or a spindle load.
  Feeds and speeds are **transported data** (§3.6), never a computed result.
- **Not a machine connection.** No serial, no network, no drip-feed, no
  machine-state read, no DNC. Mission rule 6 (framework boundaries are
  contractual) applies directly: the operator's controller and sender own that
  responsibility and no stage may introduce a second implementation of it. It
  also keeps the sandbox story intact — CAM adds **no external binary**, so
  nothing new shells out under `bwrap` (`core/src/hephaestus/core/executor/sandbox/bwrap.py:1-27`).

### 0.1 What this does not certify — for the operator, in words

Read this paragraph before you run anything this project produced.

> **This project cannot certify that a machine will execute this program
> safely.** It can generate a toolpath from features you declared and check the
> *geometry* that program describes, at a finite set of sampled points along
> each move, against the solid the design says you wanted, inside a scene you
> yourself declared. It has never seen your machine. It does not know your
> spindle, your holder stack-up, your vise, your clamps, your table, your travel
> limits, your controller's firmware, your backlash, your tool wear, or your
> workpiece's actual position on the table. It computes no cutting force and no
> deflection. It did not choose your feeds or your speeds — you or your tool
> library did, and this harness only carried them. Anything you did not declare
> was not checked, and the report says so by name rather than by silence.
> **Air-cut this program above the stock, single-block the first pass, keep the
> rapid override down and a hand on the feed hold.** The strongest sentence this
> project will ever print about a program is *"matches the design at the samples
> taken, with no collision at samples in the declared scene"* — and that is a
> statement about arithmetic, not about your shop.

That paragraph is not documentation. It is **content**: it is the frozen
constant `SAFETY_PARAGRAPH`, §1.5 makes it the **first region** of every emitted
program header and part of the program's content hash, clause (G14D-9) asserts
the header byte-for-byte against a golden, and clause (G14D-16) asserts
`SAFETY_PARAGRAPH` is byte-equal to the text above.

It is also the one region the §1.1 banned-token lint does not read, and §1.1
states the rule that makes that an exemption by construction rather than a hole:
the lint bans those tokens **as claims**, and this paragraph's only occurrence of
one is the word `safely` under negation in its first sentence. A lint that fired
on the disclaimer would force a choice between deleting the safety paragraph and
weakening the lint — and mission rule 1 forbids both, because a gate clause is a
command and ambiguity in one is resolved by tightening it.

---

## 1. Safety and honesty discipline

This section governs every other section. Where §2–§9 and this section
disagree, this section wins.

### 1.1 The claim vocabulary is closed, and every universal claim is sampled

One closed set, stated once, for every CAM result (§5.9 assigns them to
checks):

```
covered | uncovered
round_trip_identical | round_trip_diverged
matches_at_samples | gouge_at_samples | rest_at_samples
no_collision_at_samples_in_declared_scene | collision_at_samples
unverifiable | unresolvable
```

- **The banned-token lint, written so it is a command with an exactly-defined
  subject.** The tokens `verified`, `safe`, `collision-free`, `validated` and
  `ready to run` are banned **as claims** from every CAM result serialization,
  every CLI string, every tool response and every program header this project
  emits. Three mechanical details, because without them the clause is
  unsatisfiable rather than strict:
  - **Whole-token, case-insensitive, over a frozen token list** — never
    substring containment. `safely` is not the token `safe`. A substring sweep
    would fire on `safely`, on `unverifiable` and on `collision_at_samples`:
    three strings this spec *mandates*, so a substring lint bans the spec.
  - **The subject is text this project asserts.** The header is emitted as an
    ordered list of **typed regions** (§1.5), of which exactly two kinds are
    exempt by construction: `safety_paragraph` (the frozen `SAFETY_PARAGRAPH`
    of §0.1) and `quoted_simplifications` (tool and post `simplifications`
    strings, §3.5 and §7). Both are transported verbatim out of a frozen
    constant or a pinned, digest-checked registry record, and both are rendered
    under an attribution line naming the record and its digest — so no exempt
    byte is ever this project's own claim about a program. The lint runs over
    `lintable_remainder`, the concatenation of every non-exempt region, and
    clause (G14D-16) asserts the decomposition is **total** (every header byte
    lies in exactly one region) so the exemption cannot widen silently.
  - Consequently the honest sentence — the one this bullet used to get wrong by
    claiming the tokens appear in no header at all — is: **the banned tokens
    appear nowhere as this project's claim.** The word `safely` appears exactly
    once, negated, inside `SAFETY_PARAGRAPH`; a vendor's `simplifications`
    string may carry whatever the vendor wrote, attributed to the vendor and to
    a digest. Clause (G14C-18) lints the result and CLI surfaces, clause
    (G14D-16) lints `lintable_remainder` and freezes the two exempt regions;
    together they are the whole rule.
- Every claim that quantifies over a continuum — the whole path, the whole
  swept volume — is emitted with the `_at_samples` suffix, for exactly the
  reason `KINEMATICS.md` §4 gives for `holds_at_samples`: "one bad sample
  existentially falsifies them, but all-good samples only evidence, and the
  verdict name says so" (`KINEMATICS.md:204-211`). A gouge is a *local* event
  and the sample spacing that finds it is the whole question, so the spacing is
  declared, bounded, and reported in the result (§5.3).
- **`covered` is the one verdict with no suffix**, and this is deliberate:
  coverage (§5.1) quantifies over a *finite, enumerated* set of declarations,
  not over a continuum, so it is exhaustively decidable and the name must not
  pretend otherwise by borrowing a sampling caveat it does not need.
- **`collision_at_samples` is not the negation of
  `no_collision_at_samples_in_declared_scene`.** The positive form carries
  `in_declared_scene` because a clean result is a claim about what the operator
  declared and nothing else; the negative form does not, because a found
  collision is a found collision. Asymmetric on purpose.
- `unresolvable` is its own state and is never conflated with a failing check,
  the rule `ASSEMBLY.md` §2 set and `VALIDATION.md` §5 restates: "`unresolvable`
  says the mate was never checked — and an unchecked constraint is not a passing
  one" (`VALIDATION.md:313-314`).

### 1.2 A number that commands a machine is never invented

`resolve_kerf` already states the doctrine and the reason, for a cut width:
"A default kerf is never invented — a wrong compensation is worse than none,
because none is visible with a caliper and a wrong one looks correct"
(`core/src/hephaestus/geom/kerf.py:40-42`). Its source order is fixed —
explicit argument, else the DFM pack's `kerf_mm` for the declared process, else
nothing applied plus a `KERF_UNCOMPENSATED` note (`kerf.py:136-178`).

CAM inherits this verbatim and raises the stakes: here "worse" is a broken tool
and a thrown part.

- **Feeds, spindle speeds, depths of cut, stepovers, plunge rates and coolant
  states are declared data the harness transports.** Source order, fixed and
  gated: the operation's explicit value, else the tool-registry record's
  declared value for the operation kind and the declared material, else the
  named refusal `no_declared_feed` / `no_declared_speed` / `no_declared_doc`.
  **There is no third branch.** No table lookup, no chip-load formula, no
  scaling from a similar material, no "reasonable default".
- This is not a capability gap to be closed later by adding a model. There is
  no physical model anywhere in this repo to derive these from — the materials
  registry carries `density` and nothing mechanical
  (`registries/materials/al-6061.json`), and `KINEMATICS.md` §0 already refuses
  to pretend otherwise. A stage that adds a feed calculator is a *different*
  stage with a different gate and it must justify its oracle.
- Unlike kerf, **absence is a refusal, not a note**. An uncompensated cut file
  is a legitimate output that a caliper can catch; a program with an invented
  feed is a legitimate-looking output that a spindle catches.

### 1.3 The severity vocabulary is new, because the existing one means something else

A DFM pack rule's `severity` is `error | warning | info`
(`core/src/hephaestus/core/registry/_dfm.py:51`), and an `error` there means
*"this will not manufacture well."* A CAM finding that borrowed that word for
*"this will crash"* would collide two meanings inside one closed vocabulary and
quietly degrade both — the DFM reader learns to treat `error` as survivable, and
the CAM reader learns to treat it as advisory.

CAM findings therefore carry their own disjoint closed set:

```
crash_risk | part_risk | advisory
```

`crash_risk` is reserved for findings about the *declared scene* — tool, holder
or spindle intersecting stock, fixture or table geometry — and is the only value
that blocks emission by rule (§1.4). `part_risk` covers gouge and rest findings.
`advisory` covers everything else. Clause (G14C-19) asserts the two vocabularies
are disjoint sets, so a future edit cannot merge them by accident.

Registry provenance is inherited unchanged: `DfmEvaluation` carries
`pack_name`/`pack_version`/`registry`/`registry_digest`
(`core/src/hephaestus/core/dfm/types.py:274-286`) and every `DfmFinding`
repeats `source_artifact_ref` (`dfm/types.py:139-160`) because "a DFM report is
a claim about specific bytes, never about 'the part'." A CAM result is a claim
about specific bytes **and specific declarations**, never about "the job."

### 1.4 Emission is operator-gated; declaration is model-writable

The repo already draws this line twice and gives its reason both times.
Constraints and joints are model-writable because "declaring is cheap,
reversible, and measured against geometry the model didn't choose"
(`ASSEMBLY.md` §3, reaffirmed at `KINEMATICS.md` §6). Reference documents are
operator-only because they are context the model must not inject
(`INGEST.md` §2).

A runnable machine program is the opposite of cheap and reversible. So:

- **The model MAY**: declare setups, stock, fixtures, WCS, operations and
  tolerance budgets; read the tool and post registries; call `check_program`;
  read every result. All of it is cheap, reversible, generational, and measured
  against geometry the model did not choose — the same argument, unchanged.
- **The model MAY NOT** cause a runnable program to reach the filesystem.
  There is no model tool that writes a program. Emission is the operator CLI
  verb `heph cam emit <setup>` (§9), and it additionally requires
  **runtime-recorded operator consent** on the `ask_user` pattern: consent is
  stored in fields the model-facing writes refuse, exactly as `asked` and
  `resolution` are refused from `record_requirements` / `update_requirement`
  ("which is what makes a recorded answer evidence" — `VALIDATION.md:174-178`,
  `tool_schema.md` `ask_user`). Absent consent: `consent_not_recorded`, nothing
  written.
- **Emission is refused by rule** when the setup's latest `check_program` is
  stale or absent (`program_never_simulated`), when any finding is `crash_risk`
  (`crash_risk_open`), when the source artifact is not the non-stale current
  successful artifact (`stale_source_artifact`, the `export_part` rule at
  `tool_schema.md:1268-1272`), or when any consumed registry is unpinned or
  fails its digest (`registry_unpinned`). Only the operator may waive, and a
  waiver is recorded as a waiver — the `VALIDATION.md` §5 waiver shape.
- **A program is not an export.** `export_part` gains no `gcode` format. An
  export is inert interchange; a program is an instruction. Sharing the verb
  would put a machine instruction one enum value away from every existing
  export call site, including the model-facing one.

### 1.5 The program carries its own warnings, in band

A posted file opens with a comment header a human reads standing at the machine.
It is an **ordered list of typed regions**, and it carries, in this order:

1. `safety_paragraph` — `SAFETY_PARAGRAPH`, the §0.1 paragraph verbatim, and it
   is **first** because it is the part a human standing at a machine reads
   first;
2. the source artifact ref; the setup, stock, fixture and WCS records; the tool
   list with ids, the tool registry name and its Merkle digest; the post id and
   its digest;
3. **every §5.9 verdict verbatim in its sampled spelling**, with
   `samples_evaluated`, the sample step, `collision_samples_evaluated` and the
   collision subsample rate (§5.5);
4. the **not-checked manifest** — machine geometry, travel limits, the tool
   changer, and the stock's **in-process remaining material** (§5.5), each named
   rather than omitted, because §1.6.8 says the absence of a finding is never
   evidence of absence of the fault;
5. every named refusal that was raised and not resolved; every `part_risk` and
   `advisory` finding, including `holder_below_stock_top_at_samples` (§5.5);
6. `quoted_simplifications` — each tool's and the post's `simplifications`
   verbatim, under an attribution line naming the record and its digest.

Regions 1 and 6 are the §1.1 lint exemption, and they are exempt **by
construction**: their bytes are transported from a frozen constant and from
pinned registry records, never composed by the emitter. Everything else is
`lintable_remainder`. Clause (G14D-16) asserts the decomposition is total and
that each exempt region is byte-equal to its source.

**The header is part of the program's content hash.** A file whose provenance
was stripped is not this project's file, and clause (G14D-10) proves it by
mutating one header byte and asserting the hash moves.

First-run discipline (air-cut above stock, single-block the first pass, rapid
override down, hand on the feed hold) is header content and is repeated in the
`generate_doc`-style operator sheet, because the only genuine mitigation for the
unverifiable residue is a human with a hand on the feed hold.

### 1.6 What this project will never claim

Stated once, plainly, so a reviewer can check it as a list:

1. That a machine will execute a program safely, or at all.
2. That a program is collision-free — only that no collision was found at the
   samples taken in the scene the operator declared.
3. That the tool, shank or holder clears the **material still standing in the
   stock** at any moment of the program. Stage 14 models no in-process stock
   state and §5.5 checks none; every collision result carries the stamp
   `in_process_stock_not_modelled` and the header repeats it.
4. That a feed, speed or depth of cut is correct, appropriate, or survivable.
5. That a tool will not break, deflect, chatter, or wear.
6. That the stock is where the WCS says it is.
7. That the post-processor's dialect matches the operator's controller firmware
   revision (§7 makes this a declared `simplifications` field, not a hope).
8. That the absence of a finding is evidence of absence of the fault: anything
   not declared was not checked.

---

## 2. Scope: exactly what is specified, and what is excluded by name

**Specified (Stage 14).** One part, one or more **declared setups**, each with a
single spindle axis parallel to a declared stock face normal:

- **Drilling** on bores the script tagged `drill_*`, recognized through
  `DfmContext.holes()` — full-sweep internal cylinders
  (`core/src/hephaestus/core/dfm/context.py:407-409`) — whose axis is parallel
  to the setup's spindle axis within a named epsilon. Peck and simple cycles.
- **2.5D pocketing** of prismatic, planar-floored pockets the script tagged
  `pocket_*`, cleared by concentric contour offsets at a declared stepover and
  stepdown. The offset ladder's **termination** — the point at which the next
  inward offset collapses — is a reported fact and never a refusal (§4.1); this
  matters enough to say in the scope section, because the opposite reading makes
  every correct pocketing run refuse.
- **Profiling** of the outer boundary tagged `profile_*`, with declared holding
  tabs.
- **Facing** of a planar face tagged `face_*`.
- **Keep-out volumes** tagged `keepout_*`: geometry the tool must not enter,
  checked as a first-class collision target.

**Excluded by name, and each exclusion is a future amendment with its own
gate, not a TODO:**

- 3-axis **surfacing** from arbitrary geometry (scallop, parallel, waterline,
  pencil, rest-machining). This needs a real surface CAM engine and cannot be
  honestly gated as one stage. It is the top of the ladder and it is out.
- **4- and 5-axis**, indexed or continuous. Multi-setup here means multiple
  *declared* setups the operator re-fixtures between, each independently
  verified; the harness never claims a relationship between setups it did not
  measure.
- **Turning, wire EDM, waterjet, plasma, swiss.** Waterjet/plasma are closer to
  the existing 2D cut-file path (`cutfile.py`, `geom/nesting.py`) than to this
  one and should extend that instead.
- **Adaptive / trochoidal clearing**, high-speed cornering, arc fitting of
  linearized paths. Deterministic contour-offset clearing is the honest,
  reproducible placeholder here, on exactly the precedent `shelf_nest` set:
  "simple deterministic shelf/row packing, in profile order, no rotation …
  this is the honest, reproducible placeholder and is documented as such"
  (`core/src/hephaestus/geom/nesting.py:16-22`).
- **Automatic tool selection, automatic setup planning, automatic operation
  ordering.** Order is declared; the harness verifies that the declared order is
  self-consistent (§5.1) and refuses when it is not.
- **Feeds/speeds derivation, cutting force, deflection, chatter, tool life,
  thermal growth, spindle load.** §1.2 and §1.6.
- **Machine simulation** (kinematic machine model, travel limits, ATC
  collisions, rotary limits). There is no machine model in this repo and this
  stage adds none.
- **Threading, tapping, boring cycles, chamfer mills, engraving.** Later kinds,
  each a contract amendment, exactly as `ASSEMBLY.md` §1 and `KINEMATICS.md` §1
  add mate and joint kinds.

---

## 3. Declared state: a setup is project state, not script content

A setup spans the part, the stock, the fixture and the tools, so by the argument
`ASSEMBLY.md` §1 and `KINEMATICS.md` §1 both make verbatim — "a constraint spans
parts, so it cannot live in any one part script"; "a joint relates two parts" —
it cannot live in any part script. And it could not anyway: the nine assignable
`part.*` fields are the whole surface, and "Assigning anything else … is a §8
build error at the statement, naming the valid fields"
(`script_contract.md:126-131`).

CAM state therefore rides **the ledger pattern**, unchanged and unextended:
CAS-swap under the project config lock, immutable generations, provenance
mandatory on every entry, withdrawal is a new generation and never an erasure,
`read_*` returns withdrawn entries with their reasons (`ASSEMBLY.md` §1,
`KINEMATICS.md` §1/§6).

### 3.1 The setup entry

```json
{"id": "s-op1", "spindle_axis": "+Z", "order": 1,
 "stock": "st-plate", "fixture": "fx-vise", "wcs": "w-g54",
 "tolerance": {"gouge_budget_mm3": 0.5, "rejects_mm3": 2.0,
               "rest_budget_mm3": 40.0, "max_deviation_mm": 0.10},
 "provenance": {"requirement": "r-11"}, "note": "first op, top face up"}
```

- `spindle_axis` is one of the six axis-aligned directions; it is **declared,
  never inferred**, and every operation in the setup is refused
  `axis_not_parallel_to_spindle` if its feature axis diverges beyond
  `CAM_AXIS_EPS_DEG` (reusing the `CONCENTRIC_AXIS_EPS_DEG` convention
  `KINEMATICS.md` §1 already reuses for joint frames).
- `order` is a strict total order over the project's setups. It is declared, not
  planned.
- **`tolerance` is a material budget in the `VALIDATION.md` §1 rule-2 sense**:
  each budget carries, in the entry, the smallest deviation it must reject
  (`rejects_mm3`) and the margin it keeps. "An inline `abs=20.0` justifies
  nothing and is rejected" (`VALIDATION.md:72-74`) — the same rule, applied to a
  gouge budget. **Two checks, at two lifecycle points, because they need
  different inputs.** At *declaration* only the entry's own shape is decidable:
  an absent block is `no_declared_tolerance`, and a budget carrying no
  `rejects_mm3` is `budget_missing_rejects`. Whether a budget is below the
  simulation's resolution floor is **not** decidable here, and filing it here
  would have been an ordering bug: the floor is a published function of the
  sample step and the **tool radius** (§5.3), a setup entry carries no tool (the
  tool is a per-operation field, §3.7), a setup may carry many operations with
  different tools, and no operation references a setup at the moment the setup
  is declared. So `budget_below_resolution` is a **resolution-time** refusal
  (§4.3), raised once the setup's operations and their tools are bound, naming
  the budget, the floor, and the operation whose tool produced the binding
  floor.
- Provenance is mandatory on the 8C taxonomy: cite a ledger requirement or be
  `assumed` with a reason. A setup **is** an interpretation of intent.

### 3.2 Stock — new declared state, with 2D precedent and no 3D machinery

The existing `Blank` is 2D only — `width_mm`, `height_mm`, `margin_mm`,
`spacing_mm` (`core/src/hephaestus/geom/nesting.py:125-160`) — and is read from
the free-text `part.blank_size` under a script-hash check that refuses
`blank_unknown` when the source drifted (`tool_schema.md`, `nested_sheet`
block). A 3D stock record is genuinely new; the *refusal* shape is not.

```json
{"id": "st-plate", "kind": "rectangular",
 "extents_mm": [120.0, 80.0, 25.0],
 "origin_anchor": "bracket:datum_corner", "origin_offset_mm": [0.0, 0.0, 0.0],
 "material": "al-6061",
 "provenance": {"requirement": "r-12"}}
```

- `kind` is `rectangular` in Stage 14. Cylindrical bar and a
  previously-machined-solid stock (a second setup's input) are named future
  kinds, each a contract amendment.
- `origin_anchor` uses the existing `part[:selector]` anchor grammar —
  `ANCHOR_PATTERN` at
  `core/src/hephaestus/core/project_store/constraints.py:103`, colon-separated
  legal part idents, no new naming scheme. A slash-bearing anchor is refused
  `invalid_stock`, the same two-grammars reason 8C records.
- `material` resolves through the existing materials registry; an unresolved id
  is `stock_material_unknown`. The resolved record is what §6's packs and §3.6's
  feed lookup key on.
- The part must fit inside the stock at the declared origin, or
  `stock_too_small`, naming the axis and the overhang in mm.

### 3.3 Work-holding — the single largest gap, named as such

**There is no precedent anywhere in this repo for work-holding.** Nothing models
a vise, a clamp, a fixture plate, a table, or a soft jaw. This is the reason the
strongest available collision sentence is `no_collision_at_samples_in_declared_scene`
and not anything stronger, and it must be said out loud rather than papered over.

What Stage 14 can honestly do: a fixture is **declared geometry** — a list of
parts (authored by scripts, or instanced from the parts store) placed by the
existing anchor grammar plus a rigid transform, exactly the way a joint's child
rides its parent (`KINEMATICS.md` §2, applied through
`geom.kinematics`'s rigid placement, which does not mutate its input).

```json
{"id": "fx-vise", "members": [
   {"part": "vise_body", "anchor": "bracket:datum_corner",
    "offset_mm": [-60.0, -40.0, -25.0]},
   {"part": "vise_jaw_fixed", "anchor": "bracket:datum_corner",
    "offset_mm": [-60.0, -40.0, -25.0]}],
 "provenance": {"assumed": "shop standard 100 mm vise, measured 2026-08-20"}}
```

Consequences, stated rather than hidden:

- A collision check against a fixture nobody declared is `undeclared_scene` — an
  `unresolvable` state, **never a clean result**. An empty fixture is not a
  fixture; it is a missing declaration, and the report says so.
- Machine geometry (spindle nose, column, table, travel limits) is not
  declarable in Stage 14 and is therefore **not checked**. The header says so.
- The holder is not the fixture: it is declared on the tool record (§3.5)
  because it travels with the tool, and it is the single most frequently
  crashed object in real machining.

### 3.4 Work coordinate system

The cheapest of the five, because the machinery exists.

```json
{"id": "w-g54", "code": "G54",
 "datum": "bracket:datum_corner", "z_zero": "stock_top",
 "provenance": {"requirement": "r-13"}}
```

`datum` is an anchor under the same grammar; it resolves through the 8C
anchoring path against the part's CURRENT successful build artifact. An
unresolvable datum is `wcs_anchor_unresolvable` (the 8C `UNRESOLVABLE_REASONS`
taxonomy, extended, not replaced). `z_zero` is `stock_top | part_top | datum`,
declared, never guessed — a Z zero the harness picked is the single fastest way
to bury a cutter in a vise.

### 3.5 The tool library is a new registry kind, `tools`

Shape precedent is exact: `registries/parts/screw_socket_head_m5/part.json`
carries `id`, `name`, `summary`, `keywords`, typed `params` with
min/max/unit/doc, `envelope`, `mating_features`, and a **`simplifications`**
list ("no thread helix (envelope only) … no under-head fillet"). A tool record
is the same object with different fields:

```json
{"id": "em_6mm_3fl_carbide", "kind": "end_mill",
 "diameter_mm": 6.0, "corner_radius_mm": 0.0, "flutes": 3,
 "flute_length_mm": 20.0, "shank_diameter_mm": 6.0, "overall_length_mm": 57.0,
 "stickout_mm": 25.0,
 "holder": {"kind": "er32_collet", "envelope": "cylinder",
            "diameter_mm": 40.0, "length_mm": 60.0, "taper_deg": 0.0},
 "max_doc_mm": 3.0, "max_woc_mm": 3.0,
 "feeds": [{"material": "al-6061", "op": "pocket",
            "rpm": 9000, "feed_mm_min": 1200.0, "plunge_mm_min": 300.0,
            "doc_mm": 3.0, "woc_mm": 2.4,
            "source": "tool vendor datasheet rev C, 2026-03"}],
 "simplifications": ["holder is a straight cylinder envelope, not the real body",
                     "no helix, no flute geometry — the cutter is a cylinder",
                     "feeds are the vendor's numbers, not a measured result"],
 "license": "Apache-2.0"}
```

- **`holder` is mandatory and load-bearing.** Without it there is no collision
  claim to make at all — the recon's central finding. A record with no holder
  makes every collision check on it `undeclared_scene`.
- **`feeds` entries carry a `source` string** and are the only place a feed or
  speed can come from other than an explicit operation value (§1.2). A record
  with no matching `(material, op)` entry and no explicit operation value is
  `no_declared_feed`.
- **`simplifications` is safety content, not documentation** — the parts-store
  idiom used for exactly this purpose ("Do not use it to reason about thread
  engagement or preload"). A tool's simplifications are copied into the program
  header verbatim.
- The registry rides the existing machinery with no new mechanism: Merkle digest
  over path+content so "a rename is as detectable as an edit"
  (`core/src/hephaestus/core/registry/_digest.py:53-71`), pinned in
  `hephaestus.toml`'s `[registries]` table (`registry/_pins.py:41-52`),
  `heph registry list|pin|update|verify` unchanged.
- **The `tools` registry carries no executable content.** Unlike `parts`
  (generator scripts) and `dfm` (predicates), a tool record is pure data. There
  is no reason for a cutter to be a program, and every reason for it not to be.

### 3.6 Feeds and speeds: transported, gated, never derived

Restating §1.2 as the mechanical rule the gate binds to. For each operation, in
this fixed order:

1. the operation entry's explicit `feed_mm_min` / `rpm` / `doc_mm` / `woc_mm`;
2. else the resolved tool record's `feeds` entry matching the setup stock's
   resolved material id **and** the operation kind;
3. else the named refusal, one per missing number: `no_declared_feed`,
   `no_declared_speed`, `no_declared_doc`, `no_declared_woc`.

Every resolved number is reported in the result **with its source** — the
`KerfDecision` shape (`kerf.py:91-134`: `applied_mm`, `source`, `note`,
`reason`) generalized to a `FeedDecision` per operation, so a reader never has
to infer where a number came from. A declared `doc_mm` exceeding the tool's
`max_doc_mm` is `doc_exceeds_tool_limit` — a refusal, not a clamp, on the
`joint_limit_exceeded` precedent ("an evaluation never silently clamps",
`KINEMATICS.md:123-125`).

### 3.7 Operations reference tags, and only tags

```json
{"id": "op-3", "setup": "s-op1", "kind": "pocket",
 "feature": "bracket:pocket_cable_relief", "tool": "em_6mm_3fl_carbide",
 "depth_mm": 8.0, "stepdown_mm": 3.0, "stepover_mm": 2.4,
 "climb": true, "tabs": null,
 "provenance": {"requirement": "r-14"}, "note": "roughing pass only"}
```

- `kind` ∈ `drill | pocket | profile | face` (Stage 14 set; each later kind is a
  contract amendment, the `ASSEMBLY.md` §1 / `KINEMATICS.md` §1 rule).
- `feature` is an anchor whose selector is a §5.3 tag whose **prefix matches the
  operation kind**: `drill_*` for `drill`, `pocket_*` for `pocket`, `profile_*`
  for `profile`, `face_*` for `face`, plus `mill_*` as a generic and
  `keepout_*` reserved for §5.5. A mismatched prefix is `tag_prefix_mismatch`; an
  unknown prefix is `tag_prefix_unknown`. **This is `cutfile.layer_for_tag`
  (`cutfile.py:133-144`) generalized from four layers to five operation
  kinds — the same lookup, never a search, never a heuristic.**
- Two operations claiming the same feature in the same setup is
  `duplicate_feature_claim` at declaration. (Roughing plus finishing on one
  feature is a Stage 14 exclusion; it needs rest-material accounting, §2.)
- `climb` is declared. There is no inference of climb versus conventional from
  geometry.

---

## 4. Toolpath geometry: a tenth pure geom service, and where it refuses

### 4.1 What `hephaestus.geom.toolpath` owns

A tenth service under the standing `hephaestus.geom` contract — "pure geometry
services over build123d/OCP shapes … no executor, no project store, no
`opstore` runtime … measurement never decides"
(`core/src/hephaestus/geom/__init__.py:1-21`), enforced by the AST allowlist and
subprocess import-closure test at `core/tests/test_geom_import_boundary.py:45-78`.

Two pure functions and their records:

- `moves_for(profile_wires, tool, params) -> MoveList` — offset chains,
  lead-in/out, ramp or plunge entry, stepdown levels, tab bridges. The 2D offset
  **primitive** is the one kerf already calls:
  `wire.offset_2d(distance, kind=Kind.INTERSECTION)` on the flat pattern's own
  boundaries (`core/src/hephaestus/geom/kerf.py:228`). Reusing it is why the
  corner behaviour needs no second decision — `Kind.INTERSECTION` "extends the
  offset segments to their intersection rather than rounding the corner: a
  compensated square stays a square" (`kerf.py:205-209`), which is exactly what
  a finishing ring wants too.

  **The primitive is all that is shared, and the earlier claim that
  contour-offset toolpath geometry is what kerf already computes was wrong.**
  Kerf offsets each ring **exactly once**, by a half-kerf, and treats a collapsed
  offset as a **terminal refusal** (`kerf.py:235-236`). A pocket-clearing ladder
  offsets the same boundary **repeatedly** inward, and collapse is its
  **termination condition** — the normal end of a correct run. Two pieces of
  machinery follow from that difference, neither of which kerf has, and §11
  item 6 names both as new work rather than assuming them:

  - **Iterated offsetting with an explicit termination rule.** The ladder emits
    loop `k` at distance `tool_radius + k × stepover_mm`, `k = 0, 1, 2, …`, and
    **terminates when the next offset either fails to bound a face or bounds one
    of area below `TOOLPATH_MIN_LOOP_AREA_MM2`** — the same predicate kerf
    applies at `kerf.py:231-236`, read as a **stop** rather than as a refusal.
    Termination is a **fact**, reported as `loops_emitted` on the operation,
    **never a refusal**: a pocket that clears completely is a pocket whose ladder
    terminated, so a refusal here would make every correct pocketing run refuse.
    The case where the tool does not fit at all is decided *before* the ladder
    runs and is the separate named refusal `feature_below_tool_radius` (§4.3), so
    a zero-loop ladder is never how that fact is discovered.
  - **Self-intersection pruning.** Offsetting a non-convex boundary inward makes
    the offset self-intersect and split; the ladder must discard degenerate
    branches and carry the disjoint loops forward as separate rings, each
    terminating on its own. Kerf never meets this — it offsets a die-cut
    boundary once, outward or inward, and stops — and there is no code anywhere
    in this repo that does it.
- `swept_solid(moves, tool, step_mm) -> AnyShape` — the union of the tool solid
  placed at sampled points along the moves. This is the **dual of
  `publish_sweep_envelope`** (`core/src/hephaestus/core/render/posed.py:512-536`):
  fuse instead of cut, at exactly the samples the check evaluates, so "the label
  never claims samples the geometry did not visit" (`posed.py:41-45`).

Everything else — stock resolution, project state, emission, verdicts — is
engine (`hephaestus.core.cam`). Clause (G14B-1) admits `toolpath` to the
boundary tests as a pure service, exactly as G8C admitted `constraints` and G9A
admitted `kinematics`.

### 4.2 The move vocabulary is closed

```
rapid | linear | arc_cw | arc_ccw | dwell | tool_change | spindle | coolant
```

Every move carries its endpoint in WCS millimetres, its feed source
(§3.6), and the operation id that produced it. Arcs exist in the internal move
list only where the source geometry was a true circular arc; **no arc fitting of
a linearized path**, because a fitted arc is a claim about a path the harness
approximated and a post that emits it commands motion nobody computed.

### 4.3 Refusals: the closed set

Every failure mode is a named refusal carrying the ids and numbers a human needs
to act. Nothing here degrades to a plausible path — the `kerf_offset_failed`
rule, "never downgraded to an uncompensated path in either layout"
(`tool_schema.md`, kerf block), applied to motion.

**A refusal is filed at the lifecycle point where its inputs exist**, and that
rule is load-bearing rather than tidy: a refusal filed earlier than its inputs
either cannot fire or fires on a guessed value, and both are exactly the defects
this spec exists to name. Each list below is closed.

**Declaration time** — decidable from the entry's own declared fields and the
entries it names, with **no geometry, no registry resolution and no tool in the
loop**: `invalid_setup`, `invalid_stock`, `invalid_fixture`, `invalid_wcs`,
`invalid_operation`, `invalid_tool_ref`, `duplicate_feature_claim`,
`tag_prefix_mismatch`, `tag_prefix_unknown`, `no_declared_tolerance`,
`budget_missing_rejects`, `op_sample_bound_exceeded`.

`op_sample_bound_exceeded` is the only sampling arithmetic that belongs here,
and it is genuinely closed-form: from the operation entry's own `depth_mm`,
`stepdown_mm` and `stepover_mm` plus the named stock's declared `extents_mm`,

```
levels      = ceil(depth_mm / stepdown_mm)
loops_bound = ceil(min(extent_x, extent_y) / (2 × stepover_mm))
passes      = levels × loops_bound
```

and `passes > CAM_OP_PASS_BOUND_MAX` is refused, the refusal naming the product
and both factors. It bounds **passes, not samples**, and it is deliberately
loose — the stock cross-section is an over-bound on any pocket footprint. It is
a cheap arithmetic sieve that kills an absurd declaration early. **It is not the
sample cap**, and §5.3 says why the sample cap cannot live here.

**Resolution time** — `unknown_tool`, `unknown_post`, `registry_unpinned`,
`stock_material_unknown`, `stock_too_small`, `wcs_anchor_unresolvable`,
`feature_anchor_unresolvable`, `axis_not_parallel_to_spindle`,
`no_declared_feed`, `no_declared_speed`, `no_declared_doc`, `no_declared_woc`,
`doc_exceeds_tool_limit`, `budget_below_resolution`.

`budget_below_resolution` sits here, not at declaration, because its comparand
`CAM_MIN_RESOLVABLE_MM3` is a published function of the sample step and the
**tool radius** (§5.3), and a tool is bound to a setup only once an operation
naming both exists (§3.1).

**Generation time** — `no_matching_tool` (no tool of a diameter that fits the
feature), `tool_too_short` (`flute_length_mm` or `stickout_mm` below the declared
depth), `feature_below_tool_radius` (an internal radius tighter than the tool
can produce, decided *before* the offset ladder runs — §4.1),
`pocket_boundary_not_closed`, `pocket_floor_not_planar`, `unreachable_feature`
(the feature is not accessible from the setup's spindle axis),
`sample_cap_exceeded` (the setup-wide computed sample total over every move of
every generated operation exceeds `CAM_SIM_SAMPLES_MAX`, naming the total and
the operation whose moves pushed it over — §5.3),
`collision_sample_cap_exceeded` (likewise against `CAM_COLLISION_SAMPLES_MAX`,
§5.5), `toolpath_offset_failed`.

**`toolpath_offset_failed` is the kernel-error case and nothing else**: the
`except Exception` branch at `kerf.py:227-230`, "the kernel could not build an
offset boundary", carrying the operation, the ring and the distance. A
**collapsed** offset is deliberately *not* this refusal — it is the offset
ladder's termination condition and a reported fact (`loops_emitted`, §4.1).
Conflating the two, as an earlier draft of this section did, makes every
correctly-cleared pocket end in a named refusal, and would put clause (G14B-2)
and clause (G14B-16) in direct contradiction.

**Verification time** — `removal_boolean_failed` (a null or failed boolean;
`CompareBooleanError` at `core/src/hephaestus/geom/compare.py:433`, coined for
this OCCT failure mode, reused rather than reinvented), `cam_sim_timeout`
(carrying the moves already simulated and which halves were lost — the
`compare_timeout` shape, `COMPARE.md` §5), `undeclared_scene`.

**Emission time** — `consent_not_recorded`, `program_never_simulated`,
`crash_risk_open`, `stale_source_artifact`, `post_lacks_capability`,
`registry_unpinned`.

### 4.4 Determinism

The move list is **bit-reproducible** and the gate binds to that: same source
artifact bytes, same declarations, same pinned registries, same pinned OCCT ⇒
byte-identical move list and byte-identical program text. Mechanically this
rides the existing discipline — fixed iteration order, `COORD_DECIMALS = 6`
rounding on every emitted coordinate (`core/src/hephaestus/core/cutfile.py:130`),
no RNG anywhere (the `geom.compare` rule, `COMPARE.md` §1: "deterministic
parameter-grid sampling — no RNG anywhere").

**The removal simulation is not bit-reproducible across kernel versions**, and
this spec says so rather than pretending. OCCT boolean results on near-tangent
geometry are sensitive to build and platform; two different OCCT builds can
return volumes differing in the last digits, and a threshold sitting exactly on
that difference would flip. What IS reproducible, and what the gate binds to:

1. the move list and program bytes, exactly (above);
2. the **sample grid** — the set of parameter values at which the tool is
   placed — exactly, because it is computed from declared numbers by fixed
   arithmetic, the `sweep_axis_values` discipline (`core/src/hephaestus/core/motion.py:2201`);
3. the simulation *result* only **within the pinned CI image**, on the
   render-golden precedent: "Goldens are valid only for a (container image,
   hephaestus renderer version) pair recorded in each golden's provenance
   sidecar" (`verification.md:66-73`). A CAM simulation golden carries the same
   sidecar, keyed on (container image, OCCT version), and clause (G14C-16)
   asserts the sidecar is present and matched;
4. verdicts, to a **declared margin**: the gate fixtures are constructed so the
   measured quantity sits at least `CAM_VERDICT_MARGIN = 10×` away from its
   threshold, so a last-digit kernel difference cannot flip a gate clause. A
   fixture that cannot be built with that margin is not a gate fixture.

---

## 5. Verification: the gate's whole substance

The honest framing first, because everything below depends on it: **none of
these checks verify a toolpath. They verify a model of a toolpath, and the gap
between the model and the machine is exactly where damage happens.** The gate is
therefore built so that its weight rests on the checks that are deterministic,
cheap and exhaustive (§5.1, §5.2), with the sampled simulation as
*corroborating* evidence (§5.3–§5.6) rather than the load-bearing clause. Mission
rule 1 says ambiguity in a gate is a defect resolved by tightening the gate,
never waiving it — and a clause too expensive to run is a defect in the clause.

### 5.1 Declaration coverage — cheap, exhaustive, and the gate's backbone

Every §5.3-tagged feature in the part whose prefix is in the CAM set is either
covered by exactly one operation in exactly one setup, or it is reported by
name. Verdict `covered` / `uncovered`; the `uncovered` result lists every
feature with its tag, its descriptor, and why (no operation, or an operation
that was refused, naming the refusal).

This is a check over **declarations**, not geometry: it is O(features), it is
exhaustive rather than sampled, it is deterministic, and it needs no boolean.
For drilling it is very nearly the whole verification story: every tagged bore is
either covered by an operation whose tool diameter matches and whose declared
depth reaches, or it is a named refusal. **This is `cutfile.py`'s rule-not-
heuristic pattern applied to operations**, and it is the reason 14A/14B can be
gated before the simulation exists.

Coverage also checks **order consistency**: an operation whose feature is
enclosed by material a later-ordered operation removes is `feature_occluded_by_order`,
naming both operations.

### 5.2 Post round-trip — the highest-value clause per unit of cost

The emitted program text is parsed back by **the same parser the simulator
uses**, and the parsed move list must equal the pre-post internal move list
exactly. Verdict `round_trip_identical` / `round_trip_diverged`, with the first
divergent move named on both sides.

Post-processor bugs are a large fraction of real crashes — a wrong plane select,
an I/J-versus-R arc, a modal feed that never got cancelled, a work offset that
did not change — and this clause catches all of them deterministically at
near-zero cost, with no kernel, no boolean and no sampling. It is why §7
recommends declarative-only posts: a single emitter is a testable emitter, and a
round-trip against a per-post code path proves much less.

### 5.3 Material-removal simulation, and the IoU trap

Simulated result = `stock − ⋃(swept tool volumes)`, compared to the as-designed
solid with `solid_diff(sim, target, align="as_posed")`
(`core/src/hephaestus/geom/compare.py:681`). Alignment is `as_posed` and is
declared, never silently normalized — the `COMPARE.md` §1 rule.

**Sampling is declared, bounded and reported.** The per-move step is
`CAM_SIM_STEP_FRACTION = 0.10` of the active tool's radius, clamped to
`[CAM_SIM_STEP_MIN_MM = 0.05, CAM_SIM_STEP_MAX_MM = 2.0]`, overridable per setup
and **always reported** alongside `samples_evaluated`.

**The cap is on the computed total across every move of the setup, and it is
checked at generation time.** A setup whose computed sample total exceeds
`CAM_SIM_SAMPLES_MAX = 200000` is refused `sample_cap_exceeded`, the refusal
naming the computed total and the operation whose moves pushed it over.

The *shape* is `SWEEP_SAMPLES_MAX`'s — a cap on a **computed total**, refused
where the cost is incurred, the refusal naming the number
(`core/src/hephaestus/core/project_store/kinematics.py:239`, refusal at
`:1035-1038`; "the cap is on the computed grid total … a per-axis count under
the cap proves nothing"). But it is **not that discipline verbatim, and the
difference is the whole reason this refusal moved off declaration time**:
`SWEEP_SAMPLES_MAX` is checkable at declaration precisely because its total is
`raw_samples ** len(sweep)` — closed-form arithmetic over the check entry's own
declared fields, with no geometry in the loop (`kinematics.py:1034-1035`). A CAM
setup's sample total is not: it is a function of generated toolpath length,
which needs resolved feature geometry, a resolved tool radius and an OCCT offset
ladder, none of which exist when the setup entry is written. What *is*
closed-form at declaration is the per-operation pass bound of §4.3
(`op_sample_bound_exceeded`), and that is the only sampling arithmetic filed
there.

**`iou` is not a legal CAM threshold, and this is the single most important
statistic decision in the spec.** IoU on a removal simulation is dominated by
bulk material: a 0.2 mm gouge into a 100 mm part barely moves it. Asserting on
one scalar `iou` is exactly the volume-proxy anti-pattern `VALIDATION.md` §1
rule 3 already bans ("a check named for a fit is measured as a fit — not through
a volume proxy"). The right statistics are the **directed halves**, which
`VolumeDiff` already separates (`COMPARE.md` §1, `compare.py:484`):

| statistic | meaning here | verdict |
|---|---|---|
| `a_only_mm3` (sim minus target) | material the program **leaves** that the design does not want — **rest stock** | `rest_at_samples` above `rest_budget_mm3` |
| `b_only_mm3` (target minus sim) | material the program **removes** that the design wants — **gouge** | `gouge_at_samples` above `gouge_budget_mm3` |
| `surface_distance` max-deviation | where the worst disagreement is, localized | reported with both, compared to `max_deviation_mm` |

Success is `matches_at_samples`, never `matches`.

**The resolution floor, as a published formula.** Below some volume, a boolean
difference cannot be told from the sampling's own discretization artefact at the
declared step. Because a gouge is a **local** event (§1.1), the right subject for
the floor is the artefact a *single* pair of consecutive samples leaves behind: a
swept solid is a union of discrete tool placements, and between two placements
spaced `step_mm` apart along a straight move the union under-fills a scallop
whose maximum depth is the sagitta `h`, over a chord of length `step_mm` and an
axial height bounded by the engaged depth `doc_mm`. So the floor is a **frozen
formula**, not an unstated computation:

```
CAM_MIN_RESOLVABLE_MM3(step_mm, r, doc_mm)
  = max(CAM_KERNEL_NOISE_MM3,
        CAM_RESOLUTION_K × step_mm × h × doc_mm)
  where h = r - sqrt(max(0.0, r*r - (step_mm/2)*(step_mm/2)))
        r = the active tool's radius in mm
        CAM_RESOLUTION_K     = 10.0
        CAM_KERNEL_NOISE_MM3 = 1e-6
```

Neither constant is tuned. `CAM_KERNEL_NOISE_MM3` is three orders above
`OVERLAP_EPS_MM3 = 1e-9` (`core/src/hephaestus/geom/measure.py:59`), the repo's
existing "this is not a real overlap" epsilon, and the factor
`CAM_RESOLUTION_K = 10.0` is the same 10× separation §4.4 demands of every gate
fixture: a budget is resolvable only if it is an order of magnitude above the
artefact it must be distinguished from. Clause (G14B-19) asserts the formula
against hand-computed values on both sides of the `max`.

The floor is **reported in every result**, and a declared `gouge_budget_mm3`
below it is refused `budget_below_resolution` at **resolution time** (§3.1,
§4.3), naming the budget, the floor, and the operation whose tool radius produced
it. When a setup's operations use several tools, the binding floor is the
**largest** floor over the setup's operations — a budget must be resolvable
everywhere it is applied, not somewhere. A budget the simulation cannot resolve
is a budget that reads as satisfied for the wrong reason.

### 5.4 Gouge: two things that must never be conflated

- **Geometric gouge** — the cutting portion of the tool entering the design
  solid. This is `b_only_mm3` above, it is checkable, and it is checked.
- **Dynamic gouge** — deflection, chatter, entry at a feed the tool cannot take,
  a climb pass in a corner that pulls in. This is a physics claim; there is no
  machinery anywhere in this repo for it (`KINEMATICS.md` §0 excludes dynamics,
  forces, torques, friction and time), and it is an **explicit non-claim**
  (§1.6.5). A program that passes §5.3 can still break a tool.

### 5.5 Collision, against a declared scene and nothing else

**Checked bodies**: the tool's **non-cutting** portion (shank above the flute
length) and its **holder** envelope (§3.5).

**Checked scene, exhaustively**: the declared fixture members (§3.3) and every
declared `keepout_*` volume. That is the whole list. Measured with the existing
`geom.measure.interference` / `clearance`
(`core/src/hephaestus/geom/measure.py:62,92`).

**The stock is not a collision target, and the narrowing is deliberate.** An
earlier draft of this section checked against "the stock's remaining material at
each sample". That is the honest target and this stage cannot have it: it
requires an **in-process stock state machine** — a cut boolean per sample carried
forward through the whole program — which no machinery in this repo provides and
which §11 does not add. §11 opens by asserting its list is exhaustive, so
claiming remaining-material collision here was claiming machinery that neither
exists nor is planned.

The available substitute, the **undisturbed** stock envelope, is not a narrowing
but a falsehood in the other direction: a shank descending into any pocket
intersects the undisturbed envelope, so every *correct* pocketing program would
raise a `crash_risk` that blocks emission by rule (§1.4) — and operators would
learn to routinely waive the one finding class that must never be routine. So
Stage 14 checks neither, and says so in three places: every collision result
carries the stamp **`in_process_stock_not_modelled`**, the §1.5 header repeats it
in the not-checked manifest, and §1.6.3 states it as a standing non-claim.
Modelling it is a future amendment with its own gate, its own sample cap and its
own measured boolean budget — never a budget raise on this one.

**One cheap static fact is computed instead, and it is not a collision claim.**
`holder_below_stock_top_at_samples` is an `advisory` finding (§1.3 —
deliberately *not* `crash_risk`) raised when the holder envelope's lowest point
at any collision sample lies below the declared stock top plane, naming the
sample and the depth in mm. It is decidable from declared numbers with no
boolean at all, it is the signal an operator actually wants ("your holder is
going into the material"), and filing it as advisory rather than as a collision
is what keeps §1.1's vocabulary honest: it is not evidence of contact.

**The collision grid is its own grid, with its own cap.** Collision cost is
exactly `collision_samples_evaluated × |checked bodies| × |scene bodies|` OCCT
intersections, and it must be bounded in **that** dimension rather than
inheriting `CAM_SIM_SAMPLES_MAX` — 200000 samples against two checked bodies and
a three-member vise is 1.2 million intersections against a 120 s `check_program`
budget (§5.8), in a repo whose nearest existing budget is "`measure
interference` across all shelf pairs ≤ 5 s" (`verification.md:210-218`). So the
collision grid is a uniform subsample of the simulation grid at rate
`CAM_COLLISION_SUBSAMPLE = 8`, overridable **downward only** per setup (an
operator may declare `1` and pay for the full grid; nothing may declare a
coarser one), capped at `CAM_COLLISION_SAMPLES_MAX = 5000`. A setup over the cap
is refused `collision_sample_cap_exceeded` at generation time, naming the total.
Both `collision_samples_evaluated` and the subsample rate are reported in the
result **and in the header**, because a subsampled grid finds strictly less than
a full one and an `_at_samples` verdict must name *which* samples. Clause
(G14C-12) asserts the boolean count equals the product above **exactly**,
measured at two different sample counts, so the §5.8 budget binds to a counted
curve rather than to one fixture.

Verdict `no_collision_at_samples_in_declared_scene` / `collision_at_samples`,
the latter naming the move, the sample, the two bodies and the overlap volume,
and raising a `crash_risk` finding (§1.3) that blocks emission by rule.

A check whose scene lacks a fixture or a holder is `undeclared_scene` — an
`unresolvable` state. **It is never reported as a clean pass**, and the
distinction is the one `VALIDATION.md` §5 already draws: "`unresolvable` says the
mate was never checked — and an unchecked constraint is not a passing one."

Not checked, and named as not checked in the header: the stock's **in-process
remaining material** (above), the spindle nose, the column, the table, the
enclosure, axis travel limits, the tool changer, and anything else the operator
did not declare.

### 5.6 Remaining stock

`a_only_mm3` above `rest_budget_mm3`, localized by the chamfer max-deviation, is
`rest_at_samples`: the program does not finish the part. Cheap, deterministic
given the simulation, and the clause most likely to catch a genuine planning
error (a pocket declared 6 mm deep on an 8 mm feature).

### 5.7 Named tolerances, in one table

| constant | value | what it bounds |
|---|---|---|
| `CAM_AXIS_EPS_DEG` | 0.5 | feature axis vs declared spindle axis |
| `CAM_SIM_STEP_FRACTION` | 0.10 | per-move sample step, as a fraction of tool radius |
| `CAM_SIM_STEP_MIN_MM` / `_MAX_MM` | 0.05 / 2.0 | clamp on the above |
| `CAM_SIM_SAMPLES_MAX` | 200000 | computed total samples per setup, checked at **generation** (§5.3); refusal names the total |
| `CAM_OP_PASS_BOUND_MAX` | 20000 | `levels × loops_bound` from an operation entry's own declared numbers, checked at **declaration** (§4.3) |
| `CAM_COLLISION_SUBSAMPLE` | 8 | collision grid as every *n*th simulation sample; overridable **downward only** (§5.5) |
| `CAM_COLLISION_SAMPLES_MAX` | 5000 | computed collision samples per setup; refusal names the total (§5.5) |
| `TOOLPATH_MIN_LOOP_AREA_MM2` | 1e-6 | offset-ladder **termination**, never a refusal (§4.1); the `kerf.py:74` floor read as a stop |
| `CAM_SIM_TIMEOUT_S` | 300.0 | wall clock, env `HEPHAESTUS_CAM_SIM_TIMEOUT_S` |
| `CAM_MIN_RESOLVABLE_MM3` | published formula, reported (§5.3) | floor under any declared volume budget, checked at **resolution** |
| `CAM_RESOLUTION_K` | 10.0 | the margin factor inside that formula |
| `CAM_KERNEL_NOISE_MM3` | 1e-6 | absolute term inside that formula; 10³ above `OVERLAP_EPS_MM3` (`measure.py:59`) |
| `CAM_VERDICT_MARGIN` | 10× | gate-fixture distance from every threshold (§4.4) |
| `gouge_budget_mm3` / `rest_budget_mm3` / `max_deviation_mm` | **declared per setup**, with `rejects_mm3` | the material budgets of `VALIDATION.md` §1 rule 2 |

The budgets are declared rather than constant for the reason `COMPARE.md` §1
gives: "Thresholds do not live here. 'iou ≥ 0.99 is a pass' is a claim owned by a
`CHECKS` predicate, a DFM rule, or a bench task policy."

### 5.8 Bounded execution, and the performance problem stated plainly

The simulation runs under the `COMPARE.md` §5 pattern, both legs: a killable
subprocess under a wall-clock ceiling (`CAM_SIM_TIMEOUT_S`, env-overridable —
the local-floor pattern, mirroring `COMPARE_TIMEOUT_S = 300.0` at
`core/src/hephaestus/core/project_compare.py:82-85` and `MOTION_TIMEOUT_S` at
`core/src/hephaestus/core/motion.py:1434`), with the cheap facts — coverage,
round-trip, move count, per-op feed sources — computed and streamed **first**, so
a ceiling kill still returns everything that did not need the kernel. A timeout
is the named refusal `cam_sim_timeout` carrying the moves already simulated and
naming which halves were lost. Inside a `CHECKS` predicate, a CAM timeout makes
that check `unverifiable` — "not a pass and not a crash" (`COMPARE.md` §5).

**The open risk, stated rather than hidden.** `COMPARE.md` §5 records the
measurement: "one editing sample held a core for ~19 h; five of six live-run
infrastructure deaths in the 2026-07-29 sweep ended on an unanswered
`compare_solids`" (`COMPARE.md:108-111`). A removal simulation is thousands of
booleans, not one. Meanwhile mission rule 4 says performance is gated, and
`verification.md`'s Tier 1 ceilings are 30 s / 10 s / 5 s
(`verification.md:210-218`) with no plausible removal-simulation analogue.

So the spec says it: **the verification a full CAM gate would want may not fit
inside the performance discipline this mission already enforces.** Three
consequences, all binding:

1. The gate's weight rests on §5.1 and §5.2, which are cheap and exhaustive.
2. The simulation budget is a *new, larger, named* Tier 1 budget (≤ 120 s on the
   reference setup) and, if the reference setup cannot meet it, **the reference
   setup shrinks** — the budget does not grow. Budgets tighten, never loosen
   (`verification.md:218`).
   **A budget measured on one fixture bounds one fixture**, though, and a
   shipped check must be bounded in the dimension the budget bounds — otherwise
   any user setup that reaches a declared cap escapes it. So the two boolean
   loops carry their own caps and their own counted curves: the removal
   simulation at `CAM_SIM_SAMPLES_MAX` (§5.3), and the collision check at
   `CAM_COLLISION_SAMPLES_MAX` over a subsampled grid, with clause (G14C-12)
   asserting its boolean count equals
   `collision_samples_evaluated × |checked bodies| × |scene bodies|` exactly at
   two sample counts. That is what makes the 120 s number a bound rather than an
   observation. The in-process stock booleans that would have dominated both are
   not deferred-and-hoped-for: §5.5 removes them from the check and names the
   omission.
3. It is an argument for the declared scope: drilling (cylinders subtracted from
   a box) is cheap; 2.5D pocketing is affordable; surfacing is not, which is one
   more reason §2 excludes it.

### 5.9 `ProgramStatus`: the result record

`check_program(setup_ids?)` returns a per-setup record carrying: the source
artifact ref; the stock, fixture, WCS and tool records with the registry name and
digest for each; per-operation `FeedDecision`s with sources; per-operation
`loops_emitted` (the offset ladder's termination fact, §4.1); the coverage
verdict; the round-trip verdict; the simulation verdicts with
`samples_evaluated`, the sample step, `CAM_MIN_RESOLVABLE_MM3` with the
`(step_mm, r, doc_mm)` it was computed from, and every directed volume and
deviation as a number; the collision verdict with `collision_samples_evaluated`,
the subsample rate, its scene manifest (what was declared, and therefore what was
checked) and the `in_process_stock_not_modelled` stamp (§5.5); every named
refusal raised; and every finding with its §1.3 severity.

`unresolvable` at the setup level follows §2's `MotionStatus` rule
(`KINEMATICS.md` §2): an unresolvable setup makes every check on it
unresolvable — named, never skipped, never conflated with a failing check.

---

## 6. Machining DFM packs: the cheapest honest first act

Two packs, `cnc_mill` and `cnc_router`, in the existing `dfm` registry, using
the existing machinery with no extension: flat `[params]` of named scalars with
unit and description, `[[rules]]` binding a stable `<process>.<name>` rule id,
title, severity and a `reads` whitelist to one predicate file, with both load-time
invariants enforced — unique well-formed rule ids, and every name in `reads`
present in `[params]`, so "a predicate can therefore never read an undeclared
number" (`core/src/hephaestus/core/registry/_dfm.py:14-20`). Issue #28 shipped
`cnc_router` on that machinery; `cnc_mill` is the remainder of this sub-stage.

### 6.1 Why this is first, and why it is not CAM

Every rule in both shipped packs is a **static, local, geometric predicate over
one immutable artifact**. A toolpath is categorically different: a time-ordered
program with state — what has already been removed, where the tool is, which
setup is active. `DfmContext` has no accessibility notion, no tool, no setup
direction, no stock, no sequence and no time. **DFM cannot be extended into CAM;
it can only be extended with more static predicates.** That is not a defect; it
is the correct read of what the existing machinery carries, and it is why §6 is
its own sub-stage that ships value without a single line of toolpath code.

### 6.2 The rules, and the prose they replace

`registries/materials/al-6061.json` already carries real machining knowledge as
free text: "internal corners need a radius of at least half the pocket depth's
worth of tool clearance (3 mm end mill => 1.5 mm minimum internal radius),
pockets deeper than about 4x the tool diameter chatter, and thin webs below
roughly 1 mm distort." Material notes are contextual registry content injected
into agent context inside provenance delimiters — reference material, never
machine-checkable (`architecture.md:406-410`). Meanwhile `cnc_router` is the
default `part.process` `heph init` writes (`cli_init.py:64`) and appears across
the corpus. Issue #28 shipped that pack on the existing DFM machinery
(`core/tests/test_dfm_packs.py` asserts `index.has("cnc_router")`); `cnc_mill`
is still unshipped.

So: the harness already tells models it is machining aluminium on a router, and
the only machining knowledge it carries is prose no gate can check. The packs
convert it to declared numbers a predicate reads:

- `min_internal_radius_vs_tool` — `internal_rounds()` (`dfm/context.py:411`)
  against the smallest declared tool radius. `severity = "error"`.
- `pocket_depth_vs_tool_diameter` — `opposing_faces()` depth against
  `max_depth_diameter_ratio` (the "4x" from the notes, now a number).
- `min_web_thickness` — `opposing_faces()` (`dfm/context.py:415`) against
  `min_web_mm` (the "roughly 1 mm").
- `bore_aspect_ratio` — `holes()` depth-to-diameter against a declared cap.
- `single_axis_accessibility` — the one genuinely new geometric idea, and the
  only rule here that is not a scalar comparison: every `planar_faces()` outward
  normal and every `cylinders()` axis is tested for a common half-space, and a
  feature reachable from no single axis is reported. It is a **static predicate
  over one artifact** — no stock, no fixture, no sequence — which is exactly why
  it fits the existing machinery, and it is the rule that will most often tell a
  model its part is not 3-axis machinable before any setup exists.

Gate shape is G6's, already proven: "DFM fixtures with known violations yield
findings with correct rule ids, offending tags, and resolved source artifact"
(`mission_plan.md` Gate G6).

---

## 7. Post-processors belong in a content-hash-pinned registry, and should be declarative

**Yes to the registry, and it is the strongest structural argument in the spec.**
A controller dialect is exactly the shape the registry format was built for: a
versioned directory with a manifest, fetched from a git URL or local path, pinned
in `hephaestus.toml` by a Merkle digest over the tree, re-pinned only explicitly
(`architecture.md` §3.6; `registry/_digest.py:53-71`; `registry/_pins.py:41-52`).
A post is materially the same kind of object as a DFM pack: a table of named
parameters plus a small amount of emission behaviour. The laser pack states the
governing principle for exactly this case: "Override them by publishing a fork of
this pack with your own `[params]`; the rules read only the parameters they
declare, **so a re-tuned pack is a data change, not a code change**"
(`registries/dfm/laser_cut/pack.toml`).

**Pinning here is not hygiene; it is the safety mechanism.** A DFM pack's digest
tells you which advisory limits ran. A post's digest tells you **which dialect
produced the bytes that will drive the machine** — the only way to reproduce,
audit or attribute an emitted program. `DfmEvaluation` already carries `registry`
+ `registry_digest` (`dfm/types.py:274-286`); a CAM result carries the post's
identically, **and so does the in-file header** (§1.5), so
`export_hashes` + post digest + source artifact ref make a program replayable
under the existing idempotency contract.

**Declarative-only, and here is the executability argument.** Executable registry
content (parts generators, DFM predicates) runs **only** under the sandboxed
executor with the injected namespace, and the tool answers
`capability_not_available` rather than evaluating unsandboxed
(`architecture.md` §3.6; `tool_schema.md` `run_dfm`). A post written as code
would be executable registry content and would have to ride exactly that path —
same `bwrap` profile, `--unshare-net/pid/user/ipc/uts`, `--clearenv`, one
writable bind (`executor/sandbox/bwrap.py:1-27`), fail-closed with
`SandboxDeniedError` when bwrap is absent. That is a real constraint: the
injected namespace is a **CAD** namespace with no filesystem access, not a
string-templating one.

More decisively: **an untrusted executable post is a supply-chain path that
terminates at a spinning machine.** That is a materially different threat from a
DFM predicate, whose worst outcome is a wrong advisory finding. So a post is a
TOML dialect table that the engine's **single** emitter reads:

```toml
[post]
id = "grbl_1_1"
name = "GRBL 1.1"
version = "0.1.0"

[dialect]
units = "mm"
arc_mode = "ijk"          # ijk | r
plane_select = "G17"
work_offsets = ["G54", "G55", "G56"]
canned_cycles = []         # GRBL has none: a drill op is emitted as explicit moves
tool_change = "manual_pause"
coolant = {on = "M8", off = "M9"}
decimals = 3
block_numbers = false

simplifications = [
  "dialect written against the GRBL 1.1 documentation, not against a controller",
  "no canned cycles: peck drilling is emitted as explicit retract moves",
  "no tool-length compensation (G43): stickout is assumed set at the tool"
]
```

- A single emitter is a **testable** emitter, which is what makes §5.2's
  round-trip meaningful. A fork needing behaviour beyond the table is an explicit
  contract amendment adding a declared field, not a code escape hatch.
- A post whose `canned_cycles` cannot express a declared operation refuses
  `post_lacks_capability`, naming the operation and the missing capability —
  never a silent substitution of a semantically different sequence.
- **A registry pins bytes, not truth.** It cannot certify that a dialect matches
  a controller's firmware revision. `simplifications` is therefore mandatory on
  a post record, on the parts-store idiom, and is copied verbatim into the
  program header. It is load-bearing safety content, not documentation.

---

## 8. Provenance and reproducibility

- A CAM result names the source artifact ref, the stock/fixture/WCS record
  generations, every tool id with the `tools` registry name and Merkle digest,
  the post id and digest, and the sample step and totals. **A result that cannot
  name the artifact it came from is not evidence** — the project's standing rule.
- An emitted program carries `source_artifact_ref`, `source_input_hashes` and
  `export_hashes` under the existing `export_part` provenance contract
  (`tool_schema.md:1256-1275`): create-only confined targets beneath
  `.heph/exports/`, never overwritten, GC-pinned, idempotency-key replay of a
  lost response, `capability_error` when the capability is absent.
- §4.4 governs what is and is not bit-reproducible. Restated for emphasis: the
  **program bytes are**; the **simulation result is not**, across kernel builds,
  and the gate binds to a pinned-image golden with a provenance sidecar plus a
  10× verdict margin, exactly as render goldens bind to a (container image,
  renderer version) pair (`verification.md:66-73`).

---

## 9. Surface

- **Model tools** (part + orchestrator profiles, the 8C quartet decision applied
  unchanged — declaring is cheap, reversible and measured against geometry the
  model did not choose): `declare_setup` / `update_setup` / `read_setups`,
  `declare_stock` / `update_stock` / `read_stock`,
  `declare_fixture` / `update_fixture` / `read_fixtures`,
  `declare_wcs` / `update_wcs` / `read_wcs`,
  `declare_operation` / `update_operation` / `read_operations`, and
  `check_program(setup_ids?)`. Every quartet follows the 8C lifecycle contract:
  update is revise/withdraw with a recorded reason, generational, nothing erased,
  and `read_*` returns withdrawn entries with their reasons.
  **Tool-count discipline is a design constraint**: the surface is pinned at
  exactly 53 tools in two places (`contract/tests/test_toolgen.py:98,109` and
  `tests/stage2/test_g2_contract_drift.py:354`), and each tool costs five
  generated drift-tested artifacts plus a per-profile dispatch decision. Five
  quartets plus one check verb is 16 tools, which is a real cost and must be
  argued for in the amendment rather than assumed. A cheaper shape — one
  namespaced `declare_cam(kind, entry)` quartet — is a legitimate alternative
  this spec does not foreclose; what it does foreclose is putting any of it on
  `export_part`.
- **No model tool emits a program.** §1.4. `tool_schema.md`'s Deferred section
  gains a reserved `emit_program` slot naming this spec, on the `run_fea`
  precedent (`tool_schema.md:1487-1491`) — reserved, and deliberately not
  implemented as a model tool.
- **Operator CLI**: `heph cam` (setup/stock/fixture/wcs/operation tables,
  `--json`), `heph cam check [setups]`, `heph cam emit <setup> --post <id>`
  (consent-gated, §1.4), `heph cam sheet <setup>` (the operator sheet).
- **`CHECKS` surface** (`script_contract.md` §6): the project-scope facade — and
  only it — gains `m.program(setup_id)` returning the §5.9 record, so an
  acceptance check can assert `m.program("s-op1").coverage == "covered"`. A
  part-scope predicate calling it raises a named refusal (`kind="contract"`) **at
  evaluation**, recorded as that check's failure — the same discriminated-facade
  mechanism as `m.diff`'s import-target refusal and `m.at_pose`'s scope refusal
  (`KINEMATICS.md` §4), not a load-time pass over predicate bodies.
- **Ladder integration** (`VALIDATION.md` §5): the reviewer receives
  `ProgramStatus`; any non-success verdict, any `crash_risk` finding, and any
  `unresolvable` setup is a **blocking finding by rule**, stamped from the
  engine's status, never solicited from the reviewer, waivable only by the
  operator and recorded as a waiver.
- **Bench**: `task.json` acceptance may declare `cam_requirements` — setups,
  operations and expected verdicts from the §1.1 closed set — graded through the
  engine path, never from what the run reports about itself. A `machining-*`
  family is **its own split**, baselined on its own first measurement with the
  reference model at ≥3 seeds, neither compared against nor averaged into the
  v1/v2/v3 baselines (`VALIDATION.md` §1, as G9C restates it). Every task ships
  prose and seeded variants, dual independent solutions, and a hand-counted
  budget under `VALIDATION.md` §7.

---

## 10. What deliberately does NOT change

`part.process` stays a free-text string and §5.2 stays nine fields — no CAM
state enters a part script (`script_contract.md:126-131`). §5.3 tagging gains
prefixes but no new mechanism; tags remain recomputed selectors with the
existing drift-fingerprint heuristic, not stable identities. `export_part` gains
no format and no CAM parameter. `generate_drawing` is unchanged. `geom.kerf`,
`geom.nesting` and `core.cutfile` are unchanged — the 2D cut-file path is a
different process and CAM does not absorb it. `geom.compare` gains no function;
only a stated restriction on which of its fields may carry a CAM threshold
(§5.3). No placement solver, no pose solver, no dynamics, no FEA — mission rule 5
still names FEA as deferred and this stage does not smuggle it in through a
cutting-force model. No mesh path, no point clouds (`COMPARE.md` §4 stands). No
new external binary and no new sandbox backend: CAM shells out to nothing, so
`bwrap` fail-closed posture is untouched (`executor/sandbox/bwrap.py:1-27`). No
machine connection of any kind (§0). No web surface (`INTERFACE.md` unchanged).
The ledger pattern is reused, not extended; the one new *kind* of persistence is
the program-status projection of §11, on the assembly/motion projection
precedent.

---

## 11. NAMED NEW WORK

Everything below does not exist today and must be built. Anything not named here
is a claim that it already exists — so this list is exhaustive by construction,
following `KINEMATICS.md`'s discipline of naming new machinery rather than
assuming it.

**Registries and data (14A)**

1. A fifth registry kind `tools` — `BUNDLED_KINDS` and `RegistryKind`
   (`registry/_layout.py:38-41`), its record schema, loader and validation.
   *(New. The digest, pin and verify machinery is reused unchanged.)*
2. A bundled `tools` registry with at least the cutters the gate fixtures need,
   each with a mandatory `holder` block and `simplifications`. *(New content.)*
3. `cnc_mill` and `cnc_router` DFM packs: `pack.toml` plus one predicate file per
   rule. *(New content on existing machinery.)*
4. A **declared machining block** on the materials records (`al-6061`,
   `plywood-baltic-birch`): min internal radius, max depth/diameter ratio, min
   web thickness. *(New fields in an existing schema; the materials record shape
   is extended.)*
5. `DfmContext.single_axis_accessibility` support — the accessibility predicate
   of §6.2 needs a half-space test over face normals and cylinder axes. The
   inputs exist (`planar_faces`, `cylinders` — `dfm/context.py:373,388`); the
   predicate does not. *(New, in the pack; no context extension if it can be
   written from the existing accessors — clause (G14A-6) decides this by test.)*

**Pure geometry (14B)**

6. `hephaestus.geom.toolpath` — a **tenth** pure service. Contour-offset chains,
   lead-in/out, ramp entry, stepdown levels, tab bridges, the closed move
   vocabulary and `MoveList` record. *(New module. The only thing reused from
   kerf is the offset **primitive** `wire.offset_2d(…, Kind.INTERSECTION)`,
   `kerf.py:228` — a single call. §4.1 names the two things kerf does not do and
   this module must: an **iterated offset ladder with a termination rule**
   (`TOOLPATH_MIN_LOOP_AREA_MM2`, reporting `loops_emitted` as a fact and never
   as a refusal — kerf offsets each ring once and treats collapse as terminal,
   `kerf.py:235-236`), and **self-intersection pruning** of an inward offset of
   a non-convex boundary into disjoint loops, which has no precedent anywhere in
   this repo.)*
7. `toolpath.swept_solid` — the tool solid unioned at sampled points. *(New. The
   sampling-and-fuse pattern is `publish_sweep_envelope`'s, `posed.py:512-536`,
   but that function is engine-side and store-bound; this one is pure.)*
8. A tool **solid model** — cutter plus non-cutting shank plus holder envelope,
   built from a tool record. *(New. Nothing in the repo turns a tool record into
   geometry, because there are no tool records.)*
9. The geom import-boundary allowlist entry admitting `toolpath`
   (`core/tests/test_geom_import_boundary.py:45-78`). *(New test data.)*

**Declared state (14B)**

10. Five generational ledger-pattern stores: setups, stock, fixtures, WCS,
    operations. *(New stores on an existing pattern.)*
11. Stock resolution against the part's current artifact, including the
    `stock_too_small` measurement. *(New.)*
12. Fixture scene assembly — placing declared member parts by anchor plus offset
    into one scene. *(New. Nearest precedent is `render_posed_scene`'s N-compound
    scene construction, `posed.py:1-50`, which is render-side.)*
13. WCS resolution through the 8C anchoring path, with `z_zero` modes. *(New.)*
14. `FeedDecision` — the per-operation source-ordered resolution record and its
    refusals. *(New, on the `KerfDecision` shape at `kerf.py:91-134`.)*
15. The CAM tag-prefix table and its lookup. *(New, on `layer_for_tag`'s shape,
    `cutfile.py:117-144`.)*
16. `CAM_MIN_RESOLVABLE_MM3` — the **published formula** of §5.3 over
    `(step_mm, r, doc_mm)`, its two frozen constants, the largest-floor rule
    across a setup's operations, and the `budget_below_resolution` refusal **at
    resolution time**. *(New; there is no analogue anywhere. It lands in 14B, not
    14C, because the formula is pure arithmetic over resolved declarations and
    the refusal must fire before any simulation exists.)*
17. The **declaration-time pass bound** `op_sample_bound_exceeded` (§4.3) — the
    closed-form `levels × loops_bound` sieve over an operation entry's own
    declared numbers and the named stock's extents. *(New. It is the CAM analogue
    of `SWEEP_SAMPLES_MAX`'s closed-form check, and it is deliberately **not**
    the sample cap: §5.3 files that at generation time because it needs generated
    toolpath length.)*
18. The full refusal taxonomy of §4.3 as typed errors, **each bound to the
    lifecycle point where its inputs exist**, with a test that no refusal is
    raisable from a stage that cannot compute its operands. *(New.)*

**Verification (14C)**

19. `hephaestus.core.cam` — the engine: resolution, generation orchestration,
    `ProgramStatus`. *(New module.)*
20. The coverage checker, including the order-consistency clause. *(New.)*
21. The removal simulator — stock minus the union of swept volumes, bounded, with
    cheap facts streamed first, and the generation-time `sample_cap_exceeded`
    over the computed total. *(New. It reuses `geom.compare` but is not it.)*
22. The declared-scene collision checker over sampled tool/holder placements
    against **fixture members and keepout volumes only** (§5.5).
    *(New. `geom.measure.interference`/`clearance` are reused,
    `measure.py:62,92`. In-process stock is **not** a target and is **not**
    deferred machinery this list assumes: item 24 names the stamp that says so.)*
23. The **collision sample grid**: a downward-overridable uniform subsample of
    the simulation grid, `CAM_COLLISION_SAMPLES_MAX`, the generation-time
    `collision_sample_cap_exceeded`, and the reported
    `collision_samples_evaluated` + rate. *(New. Its cost must be bounded in its
    own dimension rather than inheriting the simulation's cap — §5.8.)*
24. The `in_process_stock_not_modelled` stamp on every collision result and in
    the header's not-checked manifest, and the
    `holder_below_stock_top_at_samples` **advisory** static fact (§5.5). *(New.
    The stamp is what makes the omission a named non-claim rather than silence;
    the advisory is the cheap declared-numbers signal that replaces the
    remaining-material check this stage does not have.)*
25. Bounded execution for the simulation — killable subprocess, ceiling,
    `cam_sim_timeout` with partial facts. *(New instance of the `COMPARE.md` §5
    pattern; the pattern is not reusable code today, it is a shape implemented
    twice already, `project_compare.py:82-85` and `motion.py:1434`.)*
26. A **program-status projection field** of `ProjectionState`, restaled when a
    setup's part rebuilds, GC-linked so a stale status never reads as "never
    evaluated". *(New; the one piece of non-ledger persistence this stage adds,
    on the assembly and motion projection precedent, `KINEMATICS.md` §2.)*
27. `m.program(setup_id)` on the project-scope `CHECKS` facade, with the
    part-scope evaluation-time refusal. *(New.)*
28. Reviewer-context integration and the never-green rule for CAM. *(New wiring
    in an existing mechanism.)*
29. A CAM simulation golden format with a (container image, OCCT version)
    provenance sidecar. *(New; the render-golden sidecar is a different artifact
    kind.)*

**Emission (14D)**

30. A sixth registry kind `posts`, its record schema and loader. *(New.)*
31. The **single declarative emitter** — dialect table plus internal move list to
    program text. *(New.)*
32. The **program parser** used by §5.2's round-trip, which must be the
    simulator's parser. *(New. Note this is a second consumer of the same parser
    and the gate asserts they are the same object, not two implementations.)*
33. The in-band header as an **ordered list of typed regions** (§1.5), the frozen
    `SAFETY_PARAGRAPH` constant, the `quoted_simplifications` regions with their
    attribution lines, the derived `lintable_remainder`, and the whole header's
    inclusion in the content hash. *(New. The region typing is not decoration: it
    is what makes the §1.1 lint exemption a construction rather than a hole, and
    clause (G14D-16) asserts the decomposition is total.)*
34. The frozen **banned-claim token list** and the whole-token, case-insensitive
    lint that reads it — over CAM result serializations, CLI strings and
    `lintable_remainder`. *(New. A substring grep is not this: it would fire on
    `safely`, `unverifiable` and `collision_at_samples`, three strings this spec
    mandates.)*
35. Operator consent: runtime-only consent fields refused from every model-facing
    write, and the `heph cam emit` gate. *(New; the *pattern* is `ask_user`'s
    runtime-only `asked`/`resolution`, `VALIDATION.md:174-178`.)*
36. `heph cam` / `heph cam check` / `heph cam emit` / `heph cam sheet`. *(New CLI
    verbs.)*
37. The operator sheet generator (first-run discipline, tool list, verdicts).
    *(New; `generate_doc` is a different document kind.)*
38. A `machining-*` corpus family with its own Tier 3 split, coverage constant
    and threshold — because new-family tasks are invisible to every existing gate
    until a coverage constant and its own threshold land
    (`aggregate_threshold` keys on coverage, `bench/.../scoring.py`). *(New.)*
39. A new Tier 1 performance budget in `verification.md` and its CI job, **and
    the counted-boolean clause (G14C-12)** that makes it a bound on a curve
    rather than an observation on one fixture. *(New.)*

**Named as future amendments, not as deferred work of this stage** — each needs
its own gated stage under mission rule 5, and none of it is assumed anywhere
above: an **in-process stock state machine** and per-sample cut booleans (the
honest collision target §5.5 declines to fake); surfacing; 4- and 5-axis; arc
fitting; rest-machining; a feeds-and-speeds model.

**Explicitly NOT new work, because it exists**: the Merkle digest, registry pin
table and `heph registry verify`; the ledger/generational-state pattern; the 8C
anchor grammar and resolution path; `geom.compare`'s `volume_diff`,
`surface_distance` and `solid_diff`; `geom.measure`'s interference/clearance;
`wire.offset_2d`; the `bwrap` sandbox; the export provenance and idempotency
contract; the `ask_user` runtime-only-field mechanism; the reviewer's
blocking-finding mechanism; the tool-contract drift generator.

---

## Gates

Stage 14 lands in four gated sub-stages, **strictly ordered**, and the ordering
is itself the safety decision: **the harness must be able to check a program
before it is able to produce one.** Existing suites stay green at every
sub-stage.

### Gate G14A — machining DFM packs and the tool registry (no CAM)

`uv run pytest tests/stage14a -q` exits 0, covering:

1. The `tools` registry kind loads, validates, and is refused when malformed;
   an unknown kind is refused naming the valid kinds
   (`registry/_layout.py:70-72` shape).
2. A tampered `tools` tree fails its Merkle digest and refuses to load; a
   **renamed** file fails it too (path is bound into the leaf,
   `_digest.py:53-71`).
3. A tool record with no `holder` block is refused at load, by name.
4. A tool record with a `feeds` entry lacking `source` is refused at load.
5. Both new DFM packs load: every `rule_id` is `<process>.<name>` and unique, and
   every `reads` name exists in `[params]` — asserted through the existing
   loader, and a deliberately broken fork of each pack is refused
   (`_dfm.py:14-20`).
6. Each of the five §6.2 rules fires on a fixture with a known violation and does
   not fire on a compliant fixture, with correct `rule_id`, offending tag,
   artifact-bound topology descriptor and resolved `source_artifact_ref` (the G6
   clause shape); the accessibility rule additionally proves it is computable
   from the existing `DfmContext` accessors, or the context extension it needed
   is asserted present.
7. The materials machining block resolves and each pack parameter that reads it
   gets the declared number, not the prose.
8. `index.has("cnc_router")` at `core/tests/test_dfm_packs.py` was inverted by
   issue #28; this stage still owes the same inversion for `cnc_mill`, and the
   `heph init` default process (`cli_init.py:64`) already resolves to a real
   pack end to end.
9. A registry predicate attempting file IO is denied by the sandbox (the G6
   registry-integrity clause, re-run for the new packs).
10. Determinism: two processes, identical `DfmEvaluation` records including
    `registry_digest`.

### Gate G14B — declared state and toolpath geometry (nothing is emitted)

`uv run pytest tests/stage14b -q` exits 0, covering:

1. Geom boundary tests admit `toolpath` as a pure service: the AST allowlist and
   the subprocess import-closure check both pass with it present
   (`core/tests/test_geom_import_boundary.py:45-78`).
2. Offset-ladder geometry against hand-computed fixtures, **terminating
   normally**: a rectangular pocket at a known stepover yields the hand-computed
   number of loops with expected areas to 1e-9; a circular pocket likewise; a
   profile with declared tabs yields the declared tab count at the declared
   width. In every one of these cases the operation reports `loops_emitted`
   equal to the hand-computed count and **raises no refusal at all** — asserted
   as an empty refusal list, not merely as an absent `toolpath_offset_failed`.
   This clause and clause 16 are the two halves of §4.1's termination rule and
   they are satisfiable together only because collapse is a fact and not a
   refusal.
3. The ladder's termination rule and self-intersection pruning, each on its own
   fixture: a pocket whose ladder terminates because the next offset bounds a
   face below `TOOLPATH_MIN_LOOP_AREA_MM2` reports the termination as a fact
   naming the loop index; a **non-convex** (L-shaped) pocket whose inward offset
   splits yields the hand-computed number of **disjoint** rings, each terminating
   independently, with the degenerate branches discarded; a feature narrower than
   the tool is `feature_below_tool_radius` **before** the ladder runs, so a
   zero-loop ladder is never how that fact is reported.
4. The move vocabulary is closed: a move kind outside the set is refused; **no
   arc is emitted for a linearized path** (a spline pocket boundary yields
   `linear` moves only).
5. The tool solid: cutter, shank and holder envelopes have hand-computable
   volumes and the correct axial extents from a tool record.
6. Every quartet: declare → update → withdraw, every generation replayable,
   nothing erased, `read_*` returns withdrawn entries with reasons; provenance
   compulsion refuses an entry citing no requirement and not `assumed`
   (`invalid_setup` / `invalid_stock` / `invalid_fixture` / `invalid_wcs` /
   `invalid_operation`).
7. Anchor grammar: a slash-bearing stock or WCS anchor is refused
   `invalid_stock` / `invalid_wcs` (`ANCHOR_PATTERN`,
   `project_store/constraints.py:103`).
8. `stock_too_small` fires on both sides of each axis, naming the axis and the
   overhang in mm; a part exactly fitting does not fire.
9. `axis_not_parallel_to_spindle` fires on both sides of `CAM_AXIS_EPS_DEG`.
10. WCS resolution through tag / label / binding anchor forms, plus
   `wcs_anchor_unresolvable` for each of the 8C unresolvable reasons (missing
   part, no current build, dangling tag) — each named, none conflated.
11. The tag-prefix rule: each of the five CAM prefixes maps to its operation
    kind; a mismatched prefix is `tag_prefix_mismatch`; an unknown prefix is
    `tag_prefix_unknown`; a bare prefix with nothing after it names no feature
    (the `layer_for_tag` boundary rule, `cutfile.py:139-143`).
12. `duplicate_feature_claim` on two operations naming one feature.
13. Feed resolution: explicit wins; tool-record `feeds` matching
    `(material, op)` is used and reported with `source: "tool"`; a missing number
    yields `no_declared_feed` / `no_declared_speed` / `no_declared_doc` /
    `no_declared_woc` — **and there is no case in which a number is produced from
    neither**, asserted by exhausting the branch.
14. `doc_exceeds_tool_limit` refuses rather than clamps.
15. Generation refusals, each on its own fixture and each named:
    `no_matching_tool`, `tool_too_short`, `feature_below_tool_radius`,
    `pocket_boundary_not_closed`, `pocket_floor_not_planar`,
    `unreachable_feature`.
16. `toolpath_offset_failed` fires **only on a kernel error** — a fault-injected
    `offset_2d` raising, the `except Exception` branch shape at
    `kerf.py:227-230` — and the refusal carries the operation, the ring and the
    distance. Asserted in both directions: (a) the fault-injected fixture raises
    it; (b) the clause-2 pockets, which run their ladders to normal collapse,
    raise it **zero times**. A definition under which a collapsed offset is this
    refusal would make (a) and (b) mutually unsatisfiable, so this clause is what
    holds §4.1's separation in place.
17. `sample_cap_exceeded` at **generation** time, from a generated move list, on
    a setup whose per-move step is legal but whose computed total exceeds
    `CAM_SIM_SAMPLES_MAX`, the refusal naming the computed total **and the
    operation whose moves pushed it over**; asserted additionally to be
    unraisable at declaration, since the declaration path has no move list.
18. `op_sample_bound_exceeded` at **declaration**, on an operation entry whose
    `levels × loops_bound` product exceeds `CAM_OP_PASS_BOUND_MAX`, the refusal
    naming the product and both factors — computed from the entry's own numbers
    and the named stock's `extents_mm`, with no registry, no artifact and no
    geometry touched, asserted by running it against a project whose parts have
    never been built.
19. `CAM_MIN_RESOLVABLE_MM3` equals the §5.3 formula, asserted against
    hand-computed values on **both** sides of the `max` (a fine step where the
    scallop term binds; a coarse step and small radius where
    `CAM_KERNEL_NOISE_MM3` binds), and the largest-floor rule across a setup
    whose two operations carry different tool radii.
20. `budget_below_resolution` at **resolution** time when a declared
    `gouge_budget_mm3` is under the bound floor, naming budget, floor and the
    operation whose tool produced it; asserted **unraisable at declaration**,
    since a setup entry names no tool. At declaration only the shape rules fire:
    `no_declared_tolerance` when the block is absent, `budget_missing_rejects`
    when a budget carries no `rejects_mm3` (the `VALIDATION.md` §1 rule-2 shape).
21. Determinism: two processes, byte-identical `MoveList` serialization.
22. The tool surface through dispatch on **both** profiles, and the contract
    drift artifacts regenerate clean with the pinned tool count updated and this
    stage cited (`contract/tests/test_toolgen.py:98,109`,
    `tests/stage2/test_g2_contract_drift.py:354`).
23. `heph cam` human and `--json`.
24. **Nothing is emitted**: a filesystem assertion that no sub-stage-14B code
    path writes any file under `.heph/exports/`, and that no tool in the surface
    produces program text.

### Gate G14C — verification

`uv run pytest tests/stage14c -q` exits 0, covering:

1. Coverage: `covered` on a fully-declared fixture; `uncovered` naming each
   uncovered tag and its reason on a fixture with one untagged bore, one tagged
   bore with no operation, and one operation that was refused.
2. `feature_occluded_by_order` on a fixture whose declared order buries a
   feature, naming both operations.
3. Round-trip: `round_trip_identical` on the reference setup, and
   `round_trip_diverged` naming the first divergent move under a fault-injected
   emitter that drops one block, and again under one that swaps `I/J` for `R`.
4. The round-trip parser and the simulator's parser are **the same object**,
   asserted by identity, not by two passing tests.
5. Removal simulation: `matches_at_samples` on a fixture whose declared program
   produces the target; every directed volume, deviation, `samples_evaluated`,
   sample step and `CAM_MIN_RESOLVABLE_MM3` present as numbers in the record, the
   reported floor asserted **equal to the §5.3 formula** evaluated at the run's
   own `(step_mm, r, doc_mm)`.
6. `gouge_at_samples` on a fixture with a deliberate 1.0 mm overdepth, the
   verdict driven by `b_only_mm3` and the deviation localized by
   `surface_distance` max-deviation — **and the same fixture's `iou` asserted to
   remain above 0.99**, which is the clause that proves why `iou` is not a legal
   threshold.
7. `rest_at_samples` on a fixture with a pocket declared 2 mm shallow, driven by
   `a_only_mm3`.
8. Every gate fixture's measured quantity sits at least `CAM_VERDICT_MARGIN`
   (10×) from its threshold, asserted numerically, so a kernel-build difference
   cannot flip a clause.
9. Collision, against the §5.5 scene and nothing else:
   `no_collision_at_samples_in_declared_scene` on a clean fixture;
   `collision_at_samples` naming move, sample, both bodies and overlap volume on
   a fixture whose holder fouls a declared clamp, raising a `crash_risk` finding;
   and a **deep pocket whose shank is well inside the stock's undisturbed
   envelope raises no collision finding at all**, which is the clause that pins
   the narrowing — an implementation that quietly reintroduced the stock as a
   collision target would fail here rather than ship a `crash_risk` on every
   correct pocketing program.
10. `undeclared_scene` when the fixture set is empty and when the tool record has
    no holder — asserted to be an `unresolvable` state and **asserted not equal
    to** the clean verdict.
11. The in-process omission is *stated*, not silent: every collision result — the
    clean one included — carries `in_process_stock_not_modelled`, the §1.5
    not-checked manifest names it, and `heph cam check --json` surfaces it. On
    the same fixtures, `holder_below_stock_top_at_samples` fires with the sample
    and the depth in mm when the holder passes below the declared stock top, does
    not fire when it clears, and is asserted to carry severity `advisory` —
    **never** `crash_risk`, since it is not evidence of contact (§1.3, §5.5).
12. The collision budget binds to a **counted curve**, not to one fixture: the
    OCCT intersection count is asserted to equal
    `collision_samples_evaluated × |checked bodies| × |scene bodies|` **exactly**,
    measured at two different simulation sample counts on the same scene so the
    linear relation is checked rather than assumed; the collision grid is the
    declared subsample of the simulation grid at `CAM_COLLISION_SUBSAMPLE`; a
    per-setup override to a **coarser** rate is refused while an override to `1`
    is accepted; and `collision_sample_cap_exceeded` fires at generation time
    above `CAM_COLLISION_SAMPLES_MAX`, naming the total.
13. `cam_sim_timeout` under a fault-injected slow boolean: the named refusal
    carries the moves already simulated, names which halves were lost, the cheap
    facts (coverage, round-trip, feed sources) are present, and the subprocess is
    dead afterwards (the `COMPARE.md` §5 gate addendum shape).
14. `removal_boolean_failed` on a fixture that produces a null boolean — never a
    partial solid reported as a result.
15. `m.program` in a project-scope check resolving against the run's frozen
    snapshot; the part-scope evaluation-time refusal (`kind="contract"`) recorded
    as that check's failure; a CAM timeout inside a predicate landing as
    `unverifiable` in the check report.
16. Determinism and reproducibility: two processes give identical move lists,
    identical sample grids, and identical simulation records **within the pinned
    CI image**; the simulation golden's provenance sidecar names the image and
    OCCT version and is asserted to match the running one.
17. The program-status projection restales when a setup's part rebuilds, and the
    GC edge keeps a stale status readable.
18. **Vocabulary lint, over the 14C surfaces.** The frozen banned-claim token
    list (`verified`, `safe`, `collision-free`, `validated`, `ready to run`) is
    matched **whole-token and case-insensitively** — not by substring — over
    every CAM result serialization and every CLI string, and no token appears.
    Two negative controls are asserted in the same clause, because they are what
    distinguishes this lint from the substring sweep it replaces: the strings
    `unverifiable`, `collision_at_samples` and
    `no_collision_at_samples_in_declared_scene` are all present in the surfaces
    under lint and all pass. The clause also asserts every universal verdict
    carries its `_at_samples` suffix. The header is **not** this clause's
    subject; it ships in 14D and clause (G14D-16) lints it.
19. The CAM severity set and the DFM severity set are **disjoint**, asserted as
    sets (`_dfm.py:51`).
20. Reviewer context carries `ProgramStatus`; each non-success verdict, each
    `crash_risk` finding and each `unresolvable` setup produces a blocking
    finding by rule under the FakeModel harness, and a reviewer-supplied verdict
    for a CAM id is filed as unknown and counts for nothing
    (`VALIDATION.md:236-239` shape).
21. `heph cam check` human and `--json`.
22. Tier 1 performance: `check_program` on the reference setup completes within
    the new declared budget in the pinned image — read together with clause 12,
    which is what makes that number a bound on a curve rather than a measurement
    of one fixture (§5.8).

### Gate G14D — emission, under operator consent

`uv run pytest tests/stage14d -q` exits 0, covering:

1. The `posts` registry kind loads and validates; a tampered or renamed post tree
   fails its digest; a post record without `simplifications` is refused.
2. The declarative emitter produces byte-identical program text across two
   processes for the same move list, post and pins.
3. `post_lacks_capability` when a declared drill operation needs a canned cycle
   the dialect does not carry — naming the operation and the capability, never
   substituting a different sequence.
4. Two posts over one move list produce different bytes and **the same
   round-tripped move list**, which is the clause that proves the dialect table
   changes dialect and not motion.
5. `consent_not_recorded`: `heph cam emit` with no runtime-recorded consent
   writes nothing and refuses by name; every model-facing write path refuses the
   consent fields (asserted per tool), so a recorded consent is evidence
   (`VALIDATION.md:174-178` shape).
6. `program_never_simulated` when the setup has no `check_program` result, and
   when the result is stale after a rebuild.
7. `crash_risk_open` blocks emission; an operator waiver permits it and the
   waiver is recorded as a waiver and appears in the header.
8. `stale_source_artifact` when the frozen artifact is not the non-stale current
   successful one; `registry_unpinned` when the `tools` or `posts` registry is
   unpinned or fails verification.
9. The header is asserted **byte-for-byte** against a golden, in §1.5's region
   order: `SAFETY_PARAGRAPH` **first**, then the source artifact ref, records,
   tool ids with registry digest, post id with digest, every verdict in its
   sampled spelling with `samples_evaluated`, step, `collision_samples_evaluated`
   and the collision subsample rate, the not-checked manifest **including
   `in_process_stock_not_modelled`** (§5.5), every unresolved refusal, every
   `part_risk` and `advisory` finding, and every tool and post `simplifications`
   entry under its attribution line.
10. Mutating one header byte changes the program's content hash.
11. Emission writes only create-only confined targets beneath `.heph/exports/`,
    never overwrites, pins as a GC root, and replays an idempotency key to the
    same recorded path (the `export_part` contract, `tool_schema.md:1256-1275`),
    with traversal and symlink escapes refused.
12. `export_part` still rejects any CAM format value, asserted against the
    canonical JSON Schema — the surface did not acquire a program format.
13. No new external binary: the emitted-program path spawns no subprocess outside
    the existing executor, asserted structurally.
14. `heph cam emit` and `heph cam sheet` human and `--json`; the operator sheet
    carries the first-run discipline text.
15. Tier 3, following the `VALIDATION.md` §1 split rule as G9C restates it: the
    `machining-*` corpus family is **its own split**, baselined on its own first
    measurement with the reference model at ≥3 seeds, neither compared against
    nor averaged into the v1/v2/v3 baselines; the existing 0.70 prose bar keys on
    its own coverage and is not diluted; each task ships prose and seeded
    variants, dual independent solutions, and a hand-counted budget. Its Tier 1
    half — reference solutions passing their own acceptance through the engine
    path — is covered here; the Tier 3 measurement clause is **named, not
    skipped**, on the `tests/stage9c` precedent.
16. **The header lint, and the exemption that makes it satisfiable alongside
    clause 9.** Four assertions, in one clause because they are one rule:
    (a) the region decomposition is **total and disjoint** — concatenating the
    emitted regions in order reproduces the header byte-for-byte, and every byte
    lies in exactly one region, so the exemption cannot be widened by an emitter
    that writes outside a region;
    (b) `SAFETY_PARAGRAPH` is a frozen constant, asserted byte-equal to the §0.1
    paragraph in this document, and each `quoted_simplifications` region is
    asserted byte-equal to the `simplifications` strings of the pinned tool or
    post record it is attributed to, with the attribution line naming that
    record's id and digest;
    (c) the whole-token, case-insensitive banned-claim lint over
    `lintable_remainder` — the concatenation of every **non-exempt** region —
    finds none of `verified`, `safe`, `collision-free`, `validated`,
    `ready to run`;
    (d) the two negative controls that prove the lint is whole-token and not a
    substring sweep: the same lint run over the **whole** header, exempt regions
    included, would fire on the word `safely` in `SAFETY_PARAGRAPH`, and this is
    asserted explicitly — so the exemption is a recorded, tested fact rather than
    an accident, and a future edit that deletes the safety paragraph to satisfy
    the lint fails clause 9 while a future edit that widens the exemption fails
    (a).
