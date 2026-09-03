<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# 13 — The component store (Stage 11)

**Number.** `INTERFACE.md` is 12 and is the highest assigned; `architecture.md`
00 … `INTERFACE.md` 12 is the sequence (verified by reading the first heading of
every root `.md`). **13 is the next free number** and this document takes it.

**Stage designation.** This spec is **Stage 11**, with sub-gates **G11A**,
**G11B**, **G11C** and suites `tests/stage11a`, `tests/stage11b`,
`tests/stage11c`. `KINEMATICS.md:50` already reserves "Stage 10" informally as
the *FEA / motor-sizing candidate*, so a bare "Stage 10" would collide; the
earlier provisional "Stage 10S / G10S-A…C" naming is retired and no `10S` name
survives in this document. **The one collision this document named is now
settled, and not by this document:** `docs/frontier-staging-proposal.md` §3.2
still labels mesh and scan ingest "Stage 11" in a paste-ready block that predates
the 2026-08-28 D4 resolution. Renumbering another capability's stage was never
this spec's to do, so it was left for the amendment — and the `mission_plan.md`
Stage 11 block (amendment 2026-08-29) settles it: Stage 11 is the component
store, mesh and scan ingest is Stage 12, and no other stage takes the number.
Nothing else in this spec depends on the digit.

**Status: NORMATIVE** as of 2026-08-29, on the `mission_plan.md` Stage 11
amendment of that date, which cites this document as the stage's normative spec
and carries the G11A/G11B/G11C gate summaries. Before that date it was a draft,
and the paragraphs below that describe the review it went through are kept as
written because they are the record of *why* it is safe to be normative, not
decoration. Revised after a hostile adversarial review
against the codebase, of the kind `KINEMATICS.md:10-12` records; eight confirmed
findings are folded in, and each was closed by **tightening** — no gate clause
was deleted for being hard to satisfy, and one (the runtime sandbox refusal) was
re-sited rather than dropped when its original siting proved unreachable. What
the review changed, in one line each:

- §2 was inoperative for any instance not at the origin — fragment tags named
  *pre-placement* topology while `resolve_placements` matches by
  location-sensitive `IsSame`. §2.1 now roots selectors at the published shape
  and emits the region *after* the placement statement; §2.3 verifies at the
  caller's `pos`; G11B clauses 9 and 16 instance at a non-zero translation
  **and** rotation.
- "Byte-for-byte as today, including their fragments" was false: the fragment
  header embeds the tree's Merkle root, which this stage's own edits move. §1
  and G11A clauses 1–3 split fragment-*body* invariance from digest honesty.
- §2.3's verdict was not computable from anything crossing the sandbox
  boundary. A `geom_type` field on the worker's per-tag record is now named work
  and a §8 protocol change.
- "A nested call" as an interface-region violation refused the mechanism's own
  canonical example. Replaced by an exact AST contract, with a negative-control
  gate clause.
- `datasheet_digest_mismatch` was vacuous — its join key was digest equality and
  its failure condition digest inequality. The join is now operator-declared
  through the ledger.
- Two clauses bound to machinery a later sub-stage delivers; both moved.

**Second pass: the closures were audited clause by clause, not taken on
report.** Mission rule 5's discipline — a blocking finding closes *before* the
amendment lands — is worth nothing if "folded in" is self-certified, so every
one of the eight was re-read against the current text and against the code it
cites. All eight are closed. Six **residuals** were found in the closures
themselves and are closed here; each is a narrower form of the finding it
descends from, and each was closed by tightening:

- §2.1's AST contract admitted `bound_names` in a selector argument. The
  post-placement rewrite retargets the *root*; a body local has no placed
  counterpart to retarget to, so a selector mixing the two measured the placed
  shape in the unplaced frame — finding 1, at one remove. Body locals are now
  refused (`interface_body_local_reference`), and the rewrite covers **every**
  occurrence of the root token, not only the chain root.
- "Chain root" was used undefined in a rule that claims to be parser-decidable.
  It is now defined as an explicit descent.
- "The injected-namespace whitelist" cited a module docstring; the real set is
  assembled at runtime from `build123d.__all__`. A parse-time rule cannot cite a
  runtime dict, so `SELECTOR_NAMES` is named work and is pinned to the namespace.
- `interface_class_mismatch` had no decision table, leaving three cells to
  guess — `solid` worst, which has no adaptor. The table is written out, with
  `("solid", "OTHER")` an admitting row and torus/cone/spline faces, wires and
  vertices refusals.
- §7.4's join was exact but not *total*: a `cite` could name a claim of a
  component with no `datasheet` block, leaving the iff without a right-hand side.
  §6.1 now requires the block whenever `claims` is non-empty, and requires
  `claims[].id` unique.
- §7.5 said the fifth `LEGAL-REVIEW.md` scope field would be "checked by the same
  CI schema check that checks the other four". There is no such check
  (`scripts/docs_check.py:101`). The checker is now named work and gated.

One ordering question the first pass left implicit is also decided in writing:
every Named new work item is assigned to a sub-stage in the Gates preamble, and
item 11 (record ⇄ region interface-name equality) is **G11B**, because assigning
it to G11A would have made every G11A clause that indexes a component record
depend on G11B's parser — finding 5's bug, in a place finding 5 did not look.

**That amendment has landed.** Mission rule 5 is explicit that new capability
enters "only by amending this plan with a new gated stage"; the `mission_plan.md`
Stage 11 block, dated 2026-08-29 and operator-directed, is that amendment, and it
cites this file as the stage's normative spec. The sentence this paragraph
replaced said that until such an amendment landed "nothing here is a commitment
and no clause below is evidence". That condition is discharged: every clause of
the three gates below is now a command in the rule 1 sense, and ambiguity in one
is a defect to be closed by tightening, never by waiving.

## Amendment manifest

Every existing normative document this spec changes, and exactly what changes.
A document not listed here is unchanged, and two that a reader would expect to
be listed are called out as deliberately untouched.

| Document | Change |
|---|---|
| `mission_plan.md` | **LANDED 2026-08-29.** A new gated stage (Stage 11) with the three sub-gates below, per rule 5, citing this document as its normative spec and carrying the G11A/G11B/G11C gate summaries. Two tightenings under rule 1 (`:801-804`) land with it: the registry `license` field becomes required, and `part.json` params become cross-checked against the generator. Neither is a waiver; both close a gap the current text already implies. The block also quotes the operator's D3 licensing decision (§7) and settles the Stage-11 numbering collision. |
| `mission_plan.md:643-646` | The `LEGAL-REVIEW.md` schema clause **needs** a fifth required scope field — *third-party component data provenance and terms* (§7.5) — and **the 2026-08-29 amendment did not make that edit**: it is G7's gate text, and an amendment opening Stage 11 does not rewrite another stage's gate. The requirement therefore lives in the Stage 11 block and in §7.5, and this row stays open as the outstanding one-line edit for whoever next amends G7. The row also records that the "CI checks the file's schema" sentence at `:646` describes a checker that does not exist (`scripts/docs_check.py:101` carries the file as a forward reference and nothing validates its fields); this stage **builds** that checker for all five fields and gates it at G11C clause 15, rather than citing it as if it were already there. |
| `tool_schema.md:1101-1114` | The result shapes of `search_parts_store` and `instance_store_part` gain fields (§3, §5, §6). **No new tool.** Both tools keep their names, arguments and refusal shapes; `instance_store_part` gains one optional argument (`instance`). |
| `script_contract.md` §5.3 | The tag namespace gains one reserved form: a tag name containing the infix `__` is a *store-instance interface tag*, emitted by a pasted fragment, and re-tagging one is a refusal rather than the ordinary last-wins overwrite (`core/src/hephaestus/core/executor/tags.py:58-59`, `:84`). Hand-authored tags without `__` keep last-wins semantics byte-for-byte. A `__`-infix tag that does not resolve into the final compound is additionally a build **error**, where a plain tag stays a `tag_unresolved` warning (`core/src/hephaestus/core/executor/worker.py:562-573`). |
| `script_contract.md` §2 (injected namespace) | **A note only, and it is a note precisely so no reader mistakes it for a change.** The namespace gains no name and loses none. One *derived* constant is exported from `namespace.py` — `SELECTOR_NAMES`, the injected key set minus the two dunder keys and minus the harness handles (`p`, `part`, `tag`, `hc`, `check`, `CHECKS`, `import_step`, `approx`) — because §2.1's parse-time interface-region rule has to cite a static set and `build_namespace` assembles the real one at execution time from `build123d.__all__` (`namespace.py:496-538`). Pinned by that equation, so there is one definition of the namespace and not two (rule 6). Excluding the handles restates the existing contract rather than adding policy: `hc` / `check` / `CHECKS` are already `_FORBIDDEN_NAMES` (`_generator.py:42`) and `p` is the bind region's alone. |
| `script_contract.md` §8 (worker result protocol) | Each entry of `tag_fingerprints` gains one field, `geom_type`, from a closed set (`PLANE`, `CYLINDER`, `CIRCLE`, `LINE`, `OTHER`), computed **in the worker** where the shape lives. This is a protocol change, not a sandbox-contract change, and it is the only way §2.3's verdict can be computed at all — see §2.3. Artifacts it moves: `TagDescriptor` (`core/src/hephaestus/core/executor/fingerprint.py:64-75`), `descriptors_to_json` / the `runner.py:375` parse, the published `tag_fingerprints` in `project_store/publication.py:472`, and the pinning test `core/tests/test_worker_protocol.py`. |
| `ASSEMBLY.md` §1 | A note only: an anchor selector may name a store-instance interface tag. **The anchor grammar does not change** — `ANCHOR_PATTERN` is `^[A-Za-z_][A-Za-z0-9_]*(:[^\s:]+)?$` (`core/src/hephaestus/core/project_store/constraints.py:103`) and already admits these names. No new naming scheme, per that section's own rule. |
| `KINEMATICS.md` §1 | The same note for joint anchors, which ride the same resolver by construction (`core/src/hephaestus/core/assembly.py:43-46`: the `AnchorResolver`/`PartGeometry` pair exists precisely so there is "one implementation of §7 against a published artifact, not two that could disagree"). |
| `VALIDATION.md` §2 (`:117-121`) | One new `heph lint` rule, `uncited_component_datum`, in the family of `unsourced_constant`. Component data reaches a `CHECKS` threshold only through a ledger entry, exactly as every other number does. |
| `VALIDATION.md` §2 (`:122-136`) | The citation-of-a-reference form gains two optional fields, `component` and `claim`. A `cite` may declare *which component claim* it transcribes: `{reference, page?, quote, component?, claim?}` (`RequirementCite` in `server/src/hephaestus/agent_bridge/cad_ops/_requirements.py`). This is the join §7.4 needs and it is **operator-declared, never inferred** — the first draft of this spec inferred the join from digest equality and was thereby vacuous (§7.4 records why). Existing citations without the two fields are unchanged and are checked exactly as today. |
| `INGEST.md` §2 | A note only: `references/` is the home for vendor datasheets, and this spec adds **no** mechanism there. The operator-only property (`core/src/hephaestus/core/project_store/references.py:1-7`, "There is deliberately no tool that adds one") is the reason it is the right home, and is preserved exactly. |
| `registries/PUBLISHING.md:23-28` | The `license` line's claim ("state one — publishing checks it is present") becomes true: today `parse_manifest` reads it with `opt_str` (`core/src/hephaestus/core/registry/_layout.py:78`, field at `:51`), so an absent license silently becomes `""` and `publish_registry` copies it unchecked (`_publish.py:181`). Plus a new component-authoring section. |
| `docs/registry-contributions.md` | Checklist gains the third-party-payload and per-component-license items of §7. |
| `repo_conventions.md:226-249` | The licensing and provenance policy gains a third-party **component data** clause (§7). The existing clean-room boundary and trademark-hygiene rules are extended in scope, not relaxed. |
| `CONTRIBUTING.md:58-65` | The "not accepted, under any framing" list gains vendor CAD payloads (STEP/IGES/SLDPRT), vendor PDFs, and bulk datasheet table transcriptions. |

**Deliberately NOT amended.** `architecture.md` §3.6 and
`core/src/hephaestus/core/registry/_layout.py:38-41` — `BUNDLED_KINDS` stays
`("skills", "parts", "materials", "dfm")` and `RegistryKind` gains no member.
See §0. And `COMPARE.md`, `EXTERNAL_EVAL.md`, `verification.md` performance
budgets, and the `hephaestus.geom` seam: **this stage adds no geom service**,
which is itself a design claim and is tested (§Gates, G11A clause 16).

## Design premise

Stage 8C made static fits declared and machine-checked; Stage 9 made
configurations declared and machine-checked. Both key on **tags** — the 8C
selector vocabulary is "a §5.3 tag, a geometry label, or a binding name"
(`ASSEMBLY.md:34-36`), and a joint anchor must resolve to geometry whose class
defines a frame (`KINEMATICS.md:80-85`). The parts store is the one producer in
the system *structurally forbidden* from emitting a tag:
`_FORBIDDEN_NAMES` includes `tag`, and `_check_body_region` refuses any
generator body that so much as references the name
(`core/src/hephaestus/core/registry/_generator.py:42`, `:199-206`). So the
moment the harness gained a vocabulary for mechanisms, the store became the
part of it that cannot speak that vocabulary: a bearing arrives as anonymous
geometry with a `.label`, and the model must re-select its bore by hand
(`_generator.py:334-336`).

The second half of the premise is that a component is mostly *not geometry*. A
motor is a mass, a bolt circle, a shaft axis, a torque curve and a datasheet;
the solid is the least interesting of those. Today a store part carries exactly
`id, name, summary, keywords, params, preview, script_path, registry, digest`
(`_parts.py:31-44`), `params` is copied verbatim as an opaque
`Mapping[str, JSONValue]` with nothing validating its shape (`_parts.py:85-90`),
and the `envelope` / `mating_features` / `origin` / `simplifications` /
`license` keys that every shipped `part.json` carries are read by no code and
reach no tool result (`_parts.py:91-101`; `search_result` at `:48-56`;
`tool_schema.md:1103`). The `clearance_hole_mm: 3.4` in
`registries/parts/screw_socket_head_m3/part.json` reaches a design only because
a skill tells the model to read it out of prose and retype it. That is the
failure this spec exists to fix, and it is the failure this spec must not
recommit at larger scale: **data that nothing can consume is decoration, and
adding a torque curve nothing can consume would be a worse version of the same
mistake.**

## 0. What the component store IS, and what it IS NOT

**It IS** the existing `parts` registry kind, given (a) a validated component
record in place of an opaque metadata blob, (b) the ability to emit **tagged
mounting interfaces** into the consuming script so 8C constraints and Stage 9
joints can anchor to them through the existing addressing layer, and (c) a
provenance discipline that makes a datasheet number citable rather than
recalled. It rides the machinery that already exists end to end: the Merkle
digest over the tree (`_digest.py`), verify-on-load with a hard refusal
(`_layout.py:108-130`), publish/consume records that name the drifted file
(`_publish.py:190-224`), and generators that execute only under a probed secure
sandbox or not at all (`_ops.py:196-203`).

**It is NOT:**

- **A second store.** Mission rule 6 (`mission_plan.md:818-822`) forbids a
  second implementation of what an existing subsystem owns. There is no
  `components` registry kind: adding one means editing `BUNDLED_KINDS` and the
  `RegistryKind` Literal in core (`_layout.py:38-41`), which is a code change to
  the registry subsystem in order to duplicate the registry subsystem. A
  component is a `parts` entry with a richer, validated record.
- **A CAD-model importer.** No vendor STEP is vendored, instanced, or
  redistributed. A component's geometry is authored, parametric, clean-room
  envelope geometry, on exactly the footing the shipped M3 screw already
  documents for itself: a "DIN 912 envelope", `simplifications: ["no thread
  helix (envelope only)", …]`, and a generator comment reading "Do not use it to
  reason about thread engagement or preload"
  (`registries/parts/screw_socket_head_m3/part.json`, `generator.py:1-14`). A
  project that needs the vendor's real solid registers it as an operator-side
  import (`INGEST.md` §1) — that path exists and this stage does not touch it.
- **A physics or sizing capability.** No dynamics, no loads, no FEA, no motor
  sizing. `KINEMATICS.md:49-51` forecloses these by name and mission rule 5
  names FEA explicitly as deferred. A torque-speed curve is admitted as
  **declared, provenance-bearing, well-formedness-checked reference data**, and
  §6 states plainly that nothing in the harness can evaluate a torque margin
  today and names the work that would be required.
- **An inertia provider.** A declared mass is admitted (§5). A declared inertia
  tensor is **refused**, because `Metrics` carries no mass, centre of mass or
  inertia (`core/src/hephaestus/core/types.py:137-163`), nothing consumes a
  tensor, and `KINEMATICS.md:51-54` puts configuration-level inertia
  deliberately out of scope with the rest of dynamics. Shipping an unconsumed
  tensor would be Finding A1 with more decimal places.
- **A parameter-system change.** `Param` is `int | float` only —
  `ParamType = Literal["int", "float"]`, bounds finite and ordered
  (`core/src/hephaestus/core/params.py:21`, `:44-76`). "NEMA 17 or NEMA 23"
  therefore cannot be one parameter, and this spec does **not** add an
  enumerated parameter kind (§4 states why, and what it costs instead).
- **A solver.** Unchanged from `ASSEMBLY.md:55-57`: scripts position geometry;
  a component instance is placed by the `pos` argument the model supplies and by
  nothing else.

## 1. The component record

A component is a store part whose `part.json` carries a `component` block. A
part without one is a **legacy store part** and behaves exactly as today — a
hard compatibility requirement, gated (G11A clauses 1–3).

**What "must not move" means, exactly.** It means the rendered fragment *body*:
binds, renamed locals, kept body lines, the placement statement and the
`.label` line. It does **not** mean the fragment's bytes, and a gate asserting
byte identity of the whole fragment would be unsatisfiable by construction.
`render_fragment`'s second header line is
`# registry: {part.registry} @ {part.digest}   id: {part.id}`
(`_generator.py:330`), and `part.digest` is `registry.digest`
(`_parts.py:100`) — the Merkle root over the *whole* tree, which binds path and
content into every leaf (`_digest.py:53-60`) and hashes every file it finds,
`registry.toml` and every `part.json` included (`:28-35`). So item 19 (retiring
`envelope` / `mating_features` / `origin` / `simplifications` from the six
shipped `part.json` files) and item 13 (registry `license` required) each move
the root, and therefore move the header line of *every* fragment the tree
produces — including the fragments of parts this stage never edits.

That is not a defect to be papered over; it is what a Merkle root is for. The
gate is split accordingly: **fragment-body invariance** is asserted with the
`# registry: … @ <digest>` line replaced by a fixed sentinel, and **digest
honesty** is a separate clause asserting that the elided line's digest equals
`merkle_digest(tree)` recomputed in the test, so the provenance header still
cannot drift silently (G11A clauses 1–2). Item 19's deliverable *is* a digest
change, and clause 3 states it as such: the new root is re-published and
re-pinned, and `publication_drift` names exactly the edited files
(`_publish.py:190-224`).

Body invariance binds to **frozen legacy fixture parts**, not to the six
shipped ones. Item 19 gives shipped parts validated `component` blocks, so the
shipped six cannot simultaneously serve as the gate's "carries no component
fields" evidence; a gate that reused them for both roles would be asserting
something it had just made false. The fixtures live under
`tests/stage11a/fixtures/legacy_parts/`, carry no `component` block, and are
edited by nothing in this stage.

```json
{
  "id": "stepper_nema17_frame",
  "name": "NEMA 17 stepper motor (frame envelope)",
  "summary": "…", "keywords": ["nema17", "stepper", "motor"],
  "params": { "body_length": {"type": "float", "default": 39.0,
                              "min": 20.0, "max": 60.0, "unit": "mm"} },
  "component": {
    "class": "motor",
    "series": {"family": "nema", "size": "17", "standard": "NEMA ICS 16-2001"},
    "license": "Apache-2.0",
    "data_license": "facts-only",
    "interfaces": [
      {"name": "mount_face",  "class": "planar_face",     "role": "mount"},
      {"name": "pilot_bore",  "class": "cylindrical_face", "role": "pilot"},
      {"name": "shaft",       "class": "cylindrical_face", "role": "shaft"},
      {"name": "shaft_axis",  "class": "circular_edge",    "role": "axis"},
      {"name": "bolt_1",      "class": "cylindrical_face", "role": "mount_hole"}
    ],
    "mass": {"value_g": 280.0, "source": "datasheet",
             "com_mm": [0.0, 0.0, -19.5]},
    "datasheet": {
      "publisher": "…", "document_title": "…", "revision": "Rev C",
      "url": "https://…/….pdf",
      "sha256": "sha256:9f2c…", "retrieved": "2026-08-20"
    },
    "claims": [
      {"id": "torque_speed", "kind": "torque_speed_curve",
       "unit_x": "rpm", "unit_y": "N*m",
       "samples": [[0, 0.44], [200, 0.42], [600, 0.28], [1200, 0.11]],
       "cite": {"page": 3, "quote": "Holding torque 0.44 N·m"}}
    ]
  }
}
```

**`class` is a closed set** — `motor`, `bearing`, `gear`, `encoder`,
`fastener`, `insert`, `coupling_hw`, `pulley`, `leadscrew`. A value outside it
is `unknown_component_kind` at index time. Closed because the class drives the
required-interface rule below, and an open string would make that rule
unenforceable. Each later class is a contract amendment, the
`ASSEMBLY.md:45` / `KINEMATICS.md:95` convention.

**Required interfaces per class**, enforced at index time
(`missing_required_interface`). A `bearing` without a `bore` and an `outer`
interface is not a bearing record; a `motor` without a `shaft` and a
`mount_face` is not a motor record. This is what stops the record degenerating
into optional prose the way `mating_features` did.

**`series` replaces an enumerated parameter.** A NEMA 17 and a NEMA 23 are two
part ids sharing a `series.family`; search groups them (§3). §4 records why.

**Two tightenings ride along, both under rule 1** (`mission_plan.md:801-804`,
ambiguity is resolved by tightening a gate, never waiving it):

1. **`part.json.params` is cross-checked against the generator's `PARAMS`.**
   Today `PartsIndex` never reads `generator.py` (`_parts.py:62-101` imports no
   generator machinery), while the *authoritative* parameter list at execution
   is the generator's — `_coerce_overrides(params, generator.param_names)`
   (`_ops.py:175`, `:236-245`). A record may therefore advertise parameters the
   generator lacks, and `heph registry publish` passes, because
   `validate_content` for `parts` only counts ids (`_publish.py:62-63`). Under
   this spec the index calls `parse_generator` and a mismatch is
   `param_schema_drift`, named per parameter.
2. **The registry `license` becomes required.** `req_str` in place of `opt_str`
   at `_layout.py:78`, making `PUBLISHING.md:28`'s "publishing checks it is
   present" true. Absent is `unlicensed_registry`.

**The decorative keys are resolved, not preserved.** `envelope`,
`mating_features`, `origin` and `simplifications` are either promoted into the
validated block (`origin` becomes the record's frame statement;
`simplifications` becomes a required non-empty list on any component whose
geometry is an envelope) or removed. `mating_features` is **deleted**: a
clearance hole the consumer must retype is precisely what an emitted interface
tag replaces. Leaving an unread key beside a read one would teach the next
author that either is fine.

## 2. Mounting interfaces are tagged geometry

This is the load-bearing section, and the mechanism is smaller than it looks
because **the fragment is pasted source**.

`render_fragment` emits the generator's body verbatim into the consumer's
script, binds replaced by literal effective values, every module-scope name
rewritten under a per-instance prefix so two pastes cannot collide
(`_generator.py:296-340`, prefix at `:247-256`, rename at `:310-318`).
Therefore a `tag()` call inside a fragment is executed **during the consumer's
build, in the consumer's namespace**. It lands in that build's `TagRegistry`
(`core/src/hephaestus/core/executor/tags.py:54-86`), is placed into the source
map by `resolve_placements`, and resolves through the same `AnchorResolver`
every 8C constraint and every Stage 9 joint uses — the module docstring is
explicit that a published BRep "carries topology and nothing else — no labels,
no tags, no bindings — so the namespace comes from what publication recorded
beside it: the build's §7 `geometry_index` … the source map's tag placements"
(`core/src/hephaestus/core/assembly.py:36-46`).

**So no new addressing machinery is required, and none is proposed.** What is
required is permission to emit the tag, and a discipline that makes the emitted
names safe.

### 2.1 A fourth marker region

The generator contract has exactly three marker regions, each required exactly
once and in order (`_generator.py:38-40`, `:99-113`). This spec adds a fourth,
after `body`:

```python
# --- hephaestus-store: interface ---
tag(_root.faces().filter_by(GeomType.PLANE).sort_by(SortBy.AREA)[-1], "mount_face")
tag(_root.faces().filter_by(GeomType.CYLINDER).sort_by(SortBy.RADIUS)[0], "shaft")
```

Both statements are rooted at `_root` — the name the body publishes as
`part.geometry` — and both order by a **measure**, not by a world axis. That is
the authoring rule §2.3 explains and `interface_placement_drift` partly
enforces: a measure is invariant under the placement the consumer applies, and
`sort_by(Axis.Z)[-1]` is not.

#### The selector must be rooted at the published shape, and is evaluated *after* placement

This is the rule the first draft of this spec got wrong, and it is worth stating
why, because the failure it caused was the silent-wrong-answer class §2.2 exists
to eliminate.

`render_fragment`'s tail does not tag the body's locals; it creates a **moved
copy**:

```
{prefix} = Pos(...) * Rot(...) * {prefix}{root}
{prefix}.label = "{part.id}"
```

(`_generator.py:335-338`, placement expression built at `:258-292`). It is
`{prefix}` — the moved copy — that the model composes into `part.geometry`, as
the header instructs (`:331-332`). A tag emitted against the *unplaced* body
local therefore names topology that is not in the final compound at all:
`resolve_placements` matches with `TopoDS_Shape.IsSame` (`tags.py:96-101`),
which is location-sensitive, so every interface tag of an instance with a
non-identity `pos` would resolve to `solid_index=None` (`tags.py:150-156`),
`PartGeometry._tag_shape` would raise `unaddressable_anchor`
(`assembly.py:500-506`), and the constraint row would be unresolvable — for a
motor seated on a pad, which is the whole point of the mechanism.

Two rules close it:

1. **The chain root of every selector is the generator's root name** — the bare
   name the body publishes as `part.geometry = <name>`, which `parse_generator`
   already extracts as `GeneratorSource.root_name` (`_generator.py:230-238`,
   field at `:62`). A selector rooted at any other name is
   `interface_root_violation`. This is not a real restriction: an interface that
   is not reachable from the published shape is `interface_not_placed` anyway,
   so a non-root selector could only ever name something unaddressable.
2. **The region is emitted after the placement statement, with the root
   rewritten to the instance name.** `render_fragment` appends the interface
   region *below* the two tail lines, and rewrites **every** occurrence of the
   renamed root token `{prefix}{root}` to `{prefix}` — not only the one at the
   chain root. "Occurrence" means a whole token: the same
   `(?<![A-Za-z0-9_])…(?![A-Za-z0-9_])` boundary the existing rename pass
   already uses (`_generator.py:310-318`), so `{prefix}{root}` is never rewritten
   inside `{prefix}{root}_face`. Because `{prefix}` is exactly
   `placement * {prefix}{root}`, the selector then runs on the placed copy and
   `IsSame` matches by construction. Rewriting only the chain root would leave a
   second mention of the root pointing at the unplaced body local, which is this
   finding at one remove; the "No body locals" rule above and this "every
   occurrence" rule are the two halves that close it, and neither is sufficient
   alone. When `pos` is empty, `_placement` returns `""` (`:262-263`) and
   `{prefix}` is an alias of the root — the same shape object — so the origin
   case is unaffected.

**The consequence this spec does not hide.** Selectors are evaluated
*post-placement*, in the consumer's frame. A pos-dependent selector such as
`sort_by(Axis.Z)[-1]` can therefore pick a different face under a `Rot` than it
picked at the origin. Forbidding pos-dependent selectors is not decidable by a
parser, so this spec does not pretend to forbid them. Instead §2.3 verifies at
the caller's `pos`, and adds `interface_placement_drift`, which is a real
machine-checkable control and is stated there with its exact limit.

#### The statement grammar, exactly

Mission rule 1 (`mission_plan.md:801-804`) makes an ambiguity a defect closed by
tightening, so the region's grammar is stated as an AST contract rather than as
the word "nested", which an earlier draft used and which would have refused the
region's own canonical example — every realistic selector *is* a chain of nested
calls. A parser decides all of the following; none of them requires judgement.

A statement in the interface region is admissible iff it is an `ast.Expr` whose
value is an `ast.Call` with:

- `func` an `ast.Name` with `id == "tag"` (not an attribute, not a call result);
- exactly two positional arguments, no `*args`, no keywords;
- **argument 2** an `ast.Constant` of type `str`, matching
  `^[a-z][a-z0-9_]{0,47}$` and containing no `__` (the infix is reserved for the
  emitted form, §2.2). A name that is not a literal is
  `interface_region_violation` — the index must know statically which interfaces
  a part offers, without executing anything, because `_parts.py` "indexes and
  searches them; it never executes anything" (`:5-6`), and that property is not
  being given up;
- **argument 1** any expression subject to: its *chain root* (defined below) is
  an `ast.Name` equal to `root_name`, else `interface_root_violation`; it
  contains no `ast.NamedExpr`, `ast.Lambda`, `ast.Await`, `ast.Starred`,
  `ast.JoinedStr`, or any comprehension node; and every `ast.Name` it *loads* is
  either `root_name` or a name in the interface-selector whitelist (below). A
  loaded name that is a generator body or bind local other than `root_name` is
  **`interface_body_local_reference`** — see "No body locals", below.

**Chain root, defined so a parser can compute it.** Starting from argument 1's
expression node, repeatedly descend: from an `ast.Attribute` take `.value`, from
an `ast.Subscript` take `.value`, from an `ast.Call` take `.func`. Stop at the
first node that is none of the three. That node is the chain root. It is
`interface_root_violation` unless it is an `ast.Name` whose `id == root_name`.
So `_root.faces().sort_by(SortBy.AREA)[-1]` roots at `_root` and passes, while
`Compound(children=[_root]).faces()[0]` roots at the `ast.Name` `Compound` and is
refused — the case G11B clause 4 names as "a whitelisted callable rather than a
name binding".

**No body locals, and why the earlier draft's `bound_names` term was a hole.**
An earlier draft admitted "a name in `bound_names`" as a loadable name in
argument 1. That reintroduced the very defect this subsection exists to close.
The post-placement rewrite below retargets the *root* to the placed instance;
a body local such as `_shaft_face` or `_body_length` still names **pre-placement**
geometry, or a coordinate in the pre-placement frame, and the rewrite cannot
retarget it — there is no placed counterpart to retarget it to. A selector
mixing the placed root with an unplaced local measures one shape against the
other's frame and produces a plausible, silently wrong face. It is refused
outright. The authoring cost is real and is the same cost §2.1 already imposes:
express the discriminator as a **measure** on the placed shape, not as a
remembered local. The canonical example loads only `_root`, `GeomType`, `SortBy`
and `Axis`, so this refuses nothing the mechanism needs (G11B clause 3 is the
negative control).

**The whitelist must be a declared constant, not a live namespace.** "The
injected-namespace whitelist" is not a static set today: `build_namespace`
assembles it at execution time from `build123d.__all__` plus `math`, `Param`,
`p`, `part`, `tag`, `approx` and `safe_builtins()`
(`core/src/hephaestus/core/executor/namespace.py:502-536`,
`_build123d_exports` at `:496-500`). A parse-time rule cannot cite a runtime
dict. So `namespace.py` gains one exported frozenset, `SELECTOR_NAMES`, and
`_check_interface_region` reads *that*. It is the injected key set minus two
declared exclusions, and both exclusions are the existing contract, not a new
policy:

```
SELECTOR_NAMES == injected_names(build_namespace(...)) - _DUNDERS - _HANDLES
_DUNDERS = {"__builtins__", "__name__"}
_HANDLES = {"p", "part", "tag", "hc", "check", "CHECKS", "import_step", "approx"}
```

`_DUNDERS` are not script vocabulary. `_HANDLES` are the harness handles, and
the region has no business reading any of them: `p` is the bind region's alone —
the bind region is exactly one `_<name> = p.<name>` line per parameter and "the
body never touches `p`" (`_generator.py`'s own contract, `:99-113`) — and a
parameter read in a selector is a *coordinate in the unplaced frame*, the same
hazard as a body local. `part` would root the chain somewhere other than
`root_name` and is caught anyway; `tag` is the statement's own callee; `hc`,
`check`, `CHECKS` are already in `_FORBIDDEN_NAMES` (`:42`) and stay forbidden
everywhere; `import_step` would put an ingest inside a selector. What remains is
exactly the pure-geometry vocabulary — `build123d.__all__` and `math` — which is
what a selector is for. The pinning test asserts the equation above, so a
build123d upgrade cannot silently widen or narrow the region and a handle cannot
creep back in (named new work item 2; rule 6 — one definition of the namespace,
not two). Note what this does and does not cost `_parts.py`'s "indexes and
searches them; it never executes anything" (`:5-6`): the index gains an *import*
of a declared constant, and still executes no script. Importing a library is not
executing untrusted source, and the property being preserved is the latter.

Decidable violations, each its own gate case (G11B clauses 2 and 4): a
statement that is not a `tag` call; a non-literal name argument; an `ast.Assign`
or `ast.AugAssign` or walrus; a `tag` call appearing as a sub-expression rather
than as the statement; a loaded name that is neither `root_name` nor in
`SELECTOR_NAMES`; a loaded name that is a body or bind local other than
`root_name`; a chain root that is not `root_name`.

Note what the last two do to `tag(open("/etc/passwd").read(), "x")`: `open` is
not `root_name`, so it is `interface_root_violation`, and `open` is not in the
whitelist (it is in `DENIED_BUILTINS`, `namespace.py:47-62`), so it is also
`interface_region_violation`. Both fire at parse time — hence at index time,
hence at publish, since `validate_content` builds the index
(`_publish.py:50-63`). That is the governing control for file IO in this region,
and G11B clause 11 asserts it in exactly those terms; the *runtime* sandbox
denial is re-asserted against a component tree's **body** region, where it is
reachable, by G11A clause 22.

#### The remaining rules

- The interface region is the **only** region permitted to reference `tag`.
  `_FORBIDDEN_NAMES` (`_generator.py:42`) continues to apply unchanged to the
  body: `hc`, `check`, `CHECKS` stay forbidden everywhere, and `tag` stays
  forbidden in `params` / `bind` / `body`. Store generators remain pure
  geometry; they simply now *name* parts of it.
- The set of literal names must equal the set of `component.interfaces[].name`,
  exactly. A surplus is `undeclared_interface`; a shortfall is
  `unimplemented_interface`. This is the `_dfm.py:261-271` invariant
  generalised — "a predicate can therefore never read an undeclared number"
  becomes "a generator can never emit an undeclared interface". It is **G11B
  work** (item 11, G11B clause 6), not G11A: half the comparison is the region
  the G11B parser reads, so binding it to G11A would make every G11A clause that
  indexes a component record depend on G11B — see the Gates preamble.
- The region may not assign; `bound_names` is computed over bind + body only
  (`_generator.py:124`) and stays that way.
- `part.geometry = <name>` remains the last statement of the **body**.
  `render_fragment` keeps stripping exactly that line and no other (`:327`).

### 2.2 Instance-scoped tag names, and the silent-overwrite hazard

`TagRegistry.tag` documents its own collision behaviour: "Re-tagging an
existing name overwrites (last tagging statement wins, deterministic)"
(`tags.py:58-59`), implemented as a plain `self._tags[name] = …`
(`tags.py:84`). For hand-authored scripts that is a reasonable, deterministic
rule. For pasted fragments it is a **silent correctness failure**: two motors
in one script both emitting `tag(..., "shaft")` would leave one `shaft` tag,
and an 8C constraint anchored on it would be measured against whichever
fragment was pasted lower in the file — a satisfied constraint about the wrong
solid. Nothing today would report it.

The fix has two halves:

1. **Names are instance-scoped at render time.** The emitted literal becomes
   `<instance>__<name>`, where `<instance>` is the `instance` argument if the
   caller supplied one, else the existing deterministic
   `instance_prefix(part_id, params, pos)` (`_generator.py:247-256`) with its
   leading underscore stripped. So the M3 screw's mount face is
   `screw_socket_head_m3_bcb446__mount_face`. This is the same rename pass the
   fragment already applies to locals (`:312-318`), extended to the one string
   position that carries meaning. `instance` must match the part-ident grammar;
   otherwise `invalid_instance_name`.
2. **Re-tagging an interface tag is a refusal, not an overwrite.** `tags.py:84`
   gains a scoped rule: a name containing the infix `__` may not be re-tagged;
   the second call raises `duplicate_tag` naming both statements. Scoped to
   `__` so that every existing hand-authored tag keeps last-wins semantics
   byte-for-byte — a `script_contract.md` §5.3 amendment that cannot break a
   script that does not use the reserved form. This is the mechanism that turns
   the hazard above into a build failure the operator sees.

Two instances with identical `(id, params, pos)` hash to the same prefix
(`:249-255`) and are therefore the same instance by construction; pasting one
twice is the collision case, and it now fails loudly. The escape hatch is the
`instance` argument, which is why it exists.

### 2.3 Declared class verified against built topology

An interface declares a `class` from a closed set:
`planar_face | cylindrical_face | circular_edge | linear_edge | solid`. The set
is chosen to be exactly what the consumers need and no more: 8C `coincident`
wants opposed planar faces and `concentric`/`fit` want cylindrical axes
(`ASSEMBLY.md:47-51`); a Stage 9 `revolute` needs "a cylindrical face or
circular edge", a `prismatic` needs "a planar face or linear edge"
(`KINEMATICS.md:80-83`).

**The declaration is verified, not trusted** — and the verification is a larger
piece of new work than it looks, because nothing that crosses the sandbox
boundary today can tell a plane from a cylinder.

#### What is missing, precisely

`instance_store_part` already builds the geometry before emitting a fragment —
"Only after the geometry actually builds with the requested parameters is a
fragment emitted" (`_ops.py:170-172`, build at `:176`, fragment at `:180`). But:

- The classifier an earlier draft cited returns only `face` / `edge` / `solid` /
  `wire` / `vertex` (`tags.py:105-119`). Four of the five declared interface
  classes — `planar_face` vs `cylindrical_face`, `circular_edge` vs
  `linear_edge` — are **invisible to it**. It cannot make the distinction the
  gate needs.
- Nothing else carries a surface or curve type across the boundary either.
  `TagPlacement.kind` is the same three-way label (`tags.py:32-38`);
  `TagDescriptor` carries `kind`, `point`, `scalar`, `normal` and no geometry
  type (`core/src/hephaestus/core/executor/fingerprint.py:64-75`).
- What *does* survive is more than the scratch directory: `_build_generator`
  deletes its scratch tree in a `finally` (`_ops.py:214`, `:221-222`), so the
  BRep and the source-map *file* are gone before the caller sees anything, but
  `UnpublishedBuild` carries `source_map` and `tag_fingerprints` in memory
  (`runner.py:126-131`, populated at `:421-427`). Placements are therefore
  reachable; **types are not**. And `instance_store_part` reads only
  `result.params` and `result.metrics` today (`_ops.py:176-187`).

#### The named work this requires

The verdict must be computed **in the worker, where the shape lives**. So:
`TagDescriptor` gains `geom_type` from the closed set
`PLANE | CYLINDER | CIRCLE | LINE | OTHER`, read off the OCP adaptor in-worker
beside the existing descriptor computation (`worker.py:580-584`); it rides the
existing `tag_fingerprints` channel through `descriptors_to_json` and the
`runner.py:375` parse; `_ops.py` reads `build.tag_fingerprints` instead of
discarding it. This is a **§8 worker result protocol change**, it is listed in
the Amendment manifest, and `core/tests/test_worker_protocol.py` is an artifact
this stage edits. §10's "no change to the sandbox contract" means the sandbox
boundary and the injected-namespace whitelist; it does **not** mean the worker
result protocol, and §10 now says so.

#### The decision table, written out

The verdict is a total function of the observed pair, not a description of one.
Five declared classes, five `geom_type` values and five `kind` values would
otherwise leave the reader to guess three of the cells — in particular `solid`,
which has no surface or curve adaptor at all. Stated:

| declared class | admissible `(kind, geom_type)` |
|---|---|
| `planar_face` | `("face", "PLANE")` |
| `cylindrical_face` | `("face", "CYLINDER")` |
| `circular_edge` | `("edge", "CIRCLE")` |
| `linear_edge` | `("edge", "LINE")` |
| `solid` | `("solid", "OTHER")` |

Every other pair is `interface_class_mismatch`. Three consequences are meant and
none is an oversight. `geom_type` is `OTHER` for a solid **by definition**, not
by failure: a solid has no single adaptor, the worker writes `OTHER`, and the
table admits exactly that pair — so `("solid", "OTHER")` is a positive
verification of `solid`, not a fallthrough. A face whose surface is a torus, a
cone or a B-spline classifies `("face", "OTHER")` and matches **no** declared
class; that is a refusal, because this stage's consumers (8C `coincident` /
`concentric` / `fit`, Stage 9 `revolute` / `prismatic`) accept none of them, and
admitting a class the consumers cannot use is how `mating_features` happened.
Admitting a further surface class is a contract amendment, the `ASSEMBLY.md:45`
convention. And `kind` values `wire` and `vertex` (`tags.py:105-118`) appear in
no row: an interface tag may not name one, which is `interface_class_mismatch`
naming the observed `kind`.

#### The three verdicts

- `interface_class_mismatch` — the declared class and the observed
  `(kind, geom_type)` pair are not the table's row for that class. Names the
  interface, the declared class and the observed pair.
- `interface_not_placed` — a tagged topology absent from the final compound, the
  condition `TagPlacement` already represents with `solid_index=None`
  (`tags.py:31-38`). It fires in **two** places, and the second is the one an
  earlier draft omitted:
  1. in the store's own verification build, below;
  2. in the **consumer's** build. Today the worker only appends a
     `tag_unresolved` warning for an unplaced tag (`worker.py:562-573`), which
     is right for a hand-authored tag the author is still iterating on and wrong
     for a store interface tag, where it means the pasted fragment's anchors are
     dead. For a `__`-infix name the warning becomes a build **error**
     (`script_contract.md` §5.3, amended). Without this, a consumer whose own
     composition moves the instance after the paste gets a green build and an
     `unaddressable_anchor` at constraint time.
- `interface_placement_drift` — see below.

#### Verification runs at the caller's `pos`

Because §2.1 evaluates selectors post-placement, verifying only the generator's
own pos-free build would verify the wrong thing. So when `_placement` returns a
non-empty expression, `instance_store_part` runs a **second sandboxed build**:
the rendered fragment itself, plus a synthesized `part.geometry = {prefix}`,
executed under the same `origin="registry"` backend. That build's tag placements
are the caller's, and G11B clauses 9, 13 and 14 bind to it. When `pos` is empty the
placement expression is `""` (`_generator.py:262`), `{prefix}` aliases the root,
and the first build's placements are already the right ones — so the origin case
pays nothing. Rule 4 makes this cost gated, not merely disclosed: G11B clause
12 asserts the second build happens iff the placement expression is non-empty,
and pins the two-build wall clock to a named budget.

`interface_placement_drift` is what makes the pos-dependent-selector hazard
machine-checkable rather than an authoring convention. Area, length and volume
are invariant under rigid motion, so for every interface tag the descriptor's
`geom_type` and `scalar` must agree between the unplaced build and the placed
build, to 1e-9 relative; a `sort_by(Axis.Z)[-1]` that picks a different face
under a `Rot` almost always picks one of a different measure, and is caught.
**Its limit, stated rather than glossed:** two faces of equal measure are
indistinguishable this way, so the check is a *necessary, not sufficient*
condition for selector pos-invariance. It is named as such, and it is why
`interface_placement_drift` reports drift and never certifies invariance.

**This is what stops the interface block becoming the next `mating_features`**:
every declared interface is checked against real geometry on every
instantiation, at the default parameters and at the caller's, and at the
caller's placement.

### 2.4 What the consumer does with it

Nothing new. The model pastes the fragment, composes the instance into
`part.geometry` as the fragment header already instructs (`_generator.py:328-333`),
and then declares an ordinary 8C constraint:

```json
{"id": "c-motor-seats", "kind": "coincident",
 "a": "gantry_plate:motor_pad",
 "b": "gantry_plate:stepper_nema17_frame_a91f03__mount_face",
 "tol_mm": 0.05, "provenance": {"requirement": "r-4"}}
```

Both anchors name the same part because the component is *inside* that part's
script — which is the correct model of a bolted-on motor and requires no change
to `ANCHOR_PATTERN` (`constraints.py:103`). A component instanced as its own
part (its own `parts/*.py` whose whole body is one fragment) anchors
cross-part, also unchanged. The gate requires the first form end to end
(G11B clause 16).

## 3. Discovery

`search_parts_store` returns `{id, name, params, preview, registry,
registry_digest}` today (`_parts.py:48-56`; wire shape confirmed at
`tool_schema.md:1103`). It gains, for component records only:

- `component_class`, `series`
- `interfaces`: `[{name, class, role}]` — **names as declared, unprefixed**,
  because the instance prefix is not known until instantiation
- `mass_g` when declared
- `has_datasheet`: bool

`instance_store_part` gains in its result: `interfaces` with the **emitted**
(prefixed) names, so the model does not have to reconstruct them from the
fragment text; `mass` (the declared block, verbatim); `datasheet` (the pointer
block, verbatim); and `claims_ref` (§6). It gains one optional argument,
`instance`.

**Tool count is unchanged at 53.** This is deliberate and follows the 8A/8B
precedent — `import_step` is a script term, not a tool (`INGEST.md:14-19`), and
the capability went into the result and the `CHECKS` facade rather than onto
the surface. The cost is not zero: each of these two schema changes still
regenerates five drift-tested artifacts (the Python decl, the JSON schema, the
TypeBox `schema.gen.ts`, the MCP tools file, and the `tool_schema.md` heading),
and both profiles' dispatch tests must stay green. That cost is named in §New
work and gated (G11A clause 15 for the record-only fields, G11B clause 17
for `interfaces`).

## 4. Series, and the enumerated-parameter road not taken

A frame size, a bore diameter, a width class and a module are **discrete**
axes. `Param` admits only continuous finite numerics: `ParamType` is
`Literal["int", "float"]` and the type is inferred from the default
(`params.py:21`, `:78-81`), overrides are bounds-checked numerically
(`params.py` merge path; `_ops.py:246-252` additionally rejects non-finite and
bool). A `Param(choices=[...])` would ripple through the whole §3 parameter
system: the worker's merge, the CLI override parser, the project param state
that `AuditHashes` covers (`types.py:130-135`), the web workspace's parameter
controls, and every bench task's override shape.

**Decision: no enum parameter kind. Series are separate part ids.** A NEMA 17
and a NEMA 23 are `stepper_nema17_frame` and `stepper_nema23_frame`, sharing
`component.series.family = "nema"`, and search groups by family. The cost is
record duplication across a family, which is content, not machinery; the
alternative's cost is a core parameter-system change that this stage does not
need and cannot gate cheaply. A reviewer who wants enums should attack this
here rather than discover it in the schema.

Continuous parameters stay continuous and stay the generator's: bounds live in
`Param(default, min=, max=)` and are enforced on the build path, which
`_ops.py:237` records as "bounds are the worker's job". Nothing in this spec
moves bounds enforcement into the record — that would be the second
implementation rule 6 forbids.

## 5. Mass, centre of mass, and what is refused

`geom.measure.mass(shape, density)` exists and `m.mass("part")` reaches it
through the `CHECKS` facade, but density comes from the materials registry,
where it is required and numeric because "downstream mass estimates depend on
it" (`_materials.py:4-5`, `:75-79`). A motor is not a material: it is a
heterogeneous assembly whose mass is a datasheet fact, and `volume × density`
over its envelope is not merely imprecise, it is a different quantity.

- A component may declare `mass: {value_g, source, com_mm?}` with
  `MASS_SOURCES = ("datasheet", "standard", "computed")` — a closed set.
- `source: "datasheet"` **requires** the `datasheet` pointer block (§7);
  `source: "standard"` requires a `series.standard` string; both absent is
  `unsourced_component_datum` at index time. This is the
  `docs/registry-contributions.md` materials rule applied to components: a
  record whose numbers are recalled is a rumour with units on it.
- `source: "computed"` is admitted only for a **homogeneous** component (a
  fastener, an insert) and requires a materials-registry id; the value is then
  reproducible from the built envelope and is checked against it at
  instantiation to a declared tolerance. A declared `datasheet` mass and a
  computed mass are never reconciled or averaged: declaring both is
  `mass_source_conflict`.
- `com_mm` is a point in the component frame. It is **data, not a measurement**:
  nothing computes it, nothing checks it, and it is returned to the model as
  declared.
- **An inertia tensor is refused** — `inertia_out_of_scope` at index time on any
  record carrying one. `Metrics` has no mass, COM or inertia slot
  (`types.py:137-163`), `instance_store_part` returns exactly those metrics
  (`_ops.py:185`), and `KINEMATICS.md:51-54` places configuration-level inertia
  deliberately out of scope with the rest of dynamics. A named refusal is the
  honest response to a field with no consumer; silently storing it is how
  `mating_features` happened.

**How a declared mass becomes checkable.** It does not become checkable by
being returned. It becomes checkable when the model records it as a ledger
entry citing the datasheet reference (`VALIDATION.md:122-136`), after which any
`CHECKS` threshold using it satisfies `unsourced_constant`
(`VALIDATION.md:117-121`) by citing that entry id. The store supplies the
number and its provenance; the ledger is where a number becomes a commitment.
That is the existing machinery doing the work, and §7 is the other half of it.

## 6. Performance data, and the predicate that does not exist

This section is the one most likely to be over-read, so it states its limit
first: **no part of Hephaestus can evaluate a torque-speed curve today, and
this stage does not add one.**

### 6.1 What is admitted

A component may carry `claims`: declared, provenance-bearing datasheet data,
each entry `{id, kind, unit_x, unit_y, samples, cite}` with `kind` from a
closed set (`torque_speed_curve`, `load_rating`, `speed_limit`,
`resolution`, `backlash`, `efficiency_curve`). Each entry **must** carry a
`cite` naming a page and quote in the record's `datasheet` block; absent, it is
`unsourced_component_datum` and the registry does not index — and therefore
does not publish, since `validate_content` builds the index (`_publish.py:50-63`).

Two closure rules, so that §7.4's join is a total function rather than a rule
with undefined cells:

- **A non-empty `claims` list requires the record's `datasheet` block.** A cite
  naming a page and quote in a block that is not there cites nothing;
  `unsourced_component_datum` names the claim id. This is what makes
  `K.datasheet.sha256` in §7.4 always defined for any component a ledger entry
  can legally name — without it, a `cite` could name a claim of a component with
  no datasheet and `datasheet_digest_mismatch` would have no right-hand side.
- **`claims[].id` is unique within a record**, matching the same
  `^[a-z][a-z0-9_]{0,47}$` grammar as an interface name; a repeat is
  `duplicate_claim_id`. A ledger `cite.claim` resolves to exactly one claim or
  the ledger op refuses (§7.4); an ambiguous id would make the refusal itself
  ambiguous.

### 6.2 What is checked at load: well-formedness only

The `_dfm.py:161-182` / `_materials.py:75-79` numeric compulsion generalised. A
`torque_speed_curve` is validated at index time for: at least two samples;
every sample a finite pair of numbers; strictly increasing in `x`; `y`
non-negative; `y` non-increasing across the sampled range; declared units from
a closed unit set. Any violation is `malformed_performance_curve`, naming the
sample index. This turns a transcription error into a load-time contract error
instead of a plausible-looking number, which is the entire honest benefit
available at this stage.

### 6.3 What is NOT checked, and why

A torque check needs a *required* torque. There are only two sources for one:
an operator-declared load requirement, or a dynamics computation.
`KINEMATICS.md:49-51` forecloses the second by name — "No dynamics or physics.
No masses-in-motion, forces, torques, friction, or time. Motor sizing, load
cases, and FEA are a later stage (Stage 10 candidate)" — and mission rule 5
(`mission_plan.md:815-817`) makes the first enter only by plan amendment. **A
performance datum is therefore reference material in this stage, not an input
to any verdict.**

To keep that honest rather than merely stated, three enforcement points:

- `claims` reach the model wrapped as reference material under the standard
  provenance delimiters, the way registry text already does
  (`_reference.py` `wrap_reference`, used at `_ops.py:125-133`) — footer
  restating that it is reference material, not instructions.
- The result field is named `claims`, not `performance` or `specs`. A
  vocabulary that says "the vendor asserts" is not the vocabulary that says
  "the harness verified".
- The new lint rule `uncited_component_datum` fires on a `CHECKS` numeric
  literal that matches a component claim value with no ledger citation —
  catching the "retype the number from the tool result" path that
  `mating_features` currently *depends* on.

### 6.4 Named new work: the predicate that would consume a curve

If a later stage wants a torque margin, this is its shape, and none of it
exists:

1. **A demand side.** A ledger requirement `{id, kind: "required_torque",
   value, unit, source: "specified"|"assumed", cite|rationale}` — new ledger
   entry kinds, new validation, a plan amendment.
2. **A consuming predicate in the engine, not in geom.** The geom seam holds
   pure services with no verdicts; `ASSEMBLY.md:59-66` splits residuals into
   geom and verdicts into the engine, and a torque margin is a verdict. A DFM
   predicate is the wrong host too: DFM rules measure *geometry* against
   process parameters (`PUBLISHING.md:126-128`, "Write rules that measure"), and
   a torque margin measures neither.
3. **A sampled-evaluation vocabulary.** A margin evaluated at declared
   operating points is `holds_at_samples`, never `holds`
   (`KINEMATICS.md:201-211`); a value read between datasheet points must report
   that it interpolated, and by what rule. Anything reporting a continuous
   guarantee from eight datasheet samples is exactly the dishonesty the ladder
   exists to prevent.
4. **Coupling-aware reflection**, if wanted: `KINEMATICS.md:246-263` already
   owns declared ratios, so reflected torque through a declared ratio is
   reachable — *if and only if* the demand is declared, never derived.

None of the four is proposed here. They are named so that this spec's silence
about them is not mistaken for their existence.

## 7. Provenance, licensing, and the datasheet

The part most likely to be got wrong, so it is stated as three lists and a
join.

**The operator's decision, 2026-08-29, which this section implements.** The
licensing posture was never a spec author's to settle — it is a product decision
about what this repository redistributes. It was put to the operator as D3 of
`docs/frontier-staging-proposal.md` and decided in these words:

> "D3 licensing: REFERENCE, DO NOT VENDOR. Third-party datasheets and vendor CAD
> are referenced by URL and content hash with their terms declared; they are not
> copied into this repository. If a pack cannot be built without vendoring
> something, that pack does not ship in this stage — say so loudly rather than
> vendoring."

That is D3 option (b), and the three lists below are it, made mechanical: 7.1 is
what "not copied into this repository" still permits, 7.2 is the refusal with
`vendored_third_party_payload` and `trademark_in_component_id` as its enforcement,
and 7.3 is "referenced by URL and content hash with their terms declared". Two
consequences are recorded here rather than left to be inferred. **Third-party
federated packs under their own licenses — D3 option (c) — are not authorised by
this decision**; they remain available only behind both §8's federation gate and
the fifth `LEGAL-REVIEW.md` scope field of §7.5. **Vendoring vendor CAD payloads —
option (d) — is refused permanently by the 2026-08-29 amendment**, so reversing it
requires reversing a dated operator decision in `mission_plan.md`, not editing a
paragraph here. And the last sentence of the decision is a shipping rule with
teeth: a component pack that cannot be authored without vendoring something **does
not ship in this stage**, and the omission is stated loudly in the stage's
completion report rather than quietly resolved by vendoring the payload.

### 7.1 What MAY be vendored into the repository

- **Generator source** — independently authored parametric geometry,
  Apache-2.0, matching `repo_conventions.md:226-228` ("part generators, DFM
  rules" are Apache-2.0).
- **Dimensions from a published standard**: a DIN 912 head diameter, a NEMA 17
  frame square and bolt circle, an ISO 15 bearing bore/OD/width. These are the
  nominal dimensions of a public interface standard, and the shipped store is
  already exactly this (`screw_socket_head_m3/part.json`, "DIN 912 envelope").
  The record cites the standard in `series.standard`.
- **The minimum set of derived numeric facts the geometry and its interfaces
  require**, and no more. A bearing's bore, OD and width: yes. The vendor's full
  40-row dimension table transcribed: **no** — see 7.2.

### 7.2 What may NOT be vendored, under any framing

- Vendor CAD payloads: STEP, IGES, SLDPRT, or any converted derivative.
- Vendor PDFs, drawing images, artwork, logos, marketing renders.
- **Bulk transcriptions of vendor tables.** Individual facts are not
  copyrightable in most jurisdictions; a substantial compilation may be, and
  the harness has no way to distinguish them, so the rule is drawn at
  necessity: a number a declared interface or a declared claim requires is
  admissible, a table copied wholesale is not.
- Anything under terms the contributor has not read. `CONTRIBUTING.md:58-65`
  already refuses "scraped non-public assets" under any framing; this extends
  the same refusal to vendor component data.
- **A vendor trademark as a component id.** `repo_conventions.md:248-249`
  forbids reference-product naming in identifiers; this generalises it. Ids are
  generic or standard-derived (`bearing_608`, `stepper_nema17_frame`), never
  `<vendor>_<sku>`. A vendor name and part number are factual reference and
  live in the `datasheet` block only. Violation is `trademark_in_component_id`,
  checked at publish against a maintained deny-list — a check that will be
  imperfect, which is why it is a publish-time warning-to-error tightening and
  not the only control; the human review of
  `docs/registry-contributions.md:27-31` (registry content requires a reviewer
  other than the author, because it is executed or fed to a model) remains the
  real control.

A publish-time scanner enforces the payload half mechanically: any file in a
`parts` tree that is not `registry.toml`, `part.json`, `generator.py`, or
`*.md` is `vendored_third_party_payload`. Blunt on purpose — a store tree has
no legitimate reason to contain a binary, and the Merkle digest hashes every
file it finds (`_digest.py`, dotfiles and `__pycache__` excluded), so a
smuggled payload would otherwise be pinned and redistributed with the pack.

### 7.3 What is referenced by URL and hash instead

The `datasheet` block is a **pointer, redistributing nothing**:
`{publisher, document_title, revision, url, sha256, retrieved}`. All six are
required when the block is present; `sha256` is the digest of the exact
document the numbers were transcribed from, in the `sha256:…` form the rest of
the system uses (`_publish.py:132-133` enforces that prefix on publication
digests).

The URL is provenance, **not a fetch target**. Nothing in Hephaestus retrieves
it: the sandbox denies network by construction (`tests/stage0b/` proves network
denial for registry-origin execution), and a registry that fetched at load
would break the offline, content-addressed determinism the whole trust model
rests on. A reader obtains the document themselves.

### 7.4 The join: `heph reference add`, then the ledger

The citable path already exists end to end and this spec adds no mechanism to
it:

1. The operator registers their own copy: `heph reference add <datasheet>.pdf`.
   Registration is operator-side and content-addressed; "There is deliberately
   no tool that adds one" (`references.py:1-7`; `INGEST.md:56-63`). PDFs
   require the server package's extractor and a core-only install refuses with
   a named `capability_not_available` rather than degrading
   (`references.py:15-27`, `ReferenceCapabilityError` at `:101-111`).
2. The model records a requirement citing it:
   `{"source": "specified", "cite": {"reference": "….pdf", "page": 3,
   "quote": "Holding torque 0.44 N·m"}}`. `VALIDATION.md:122-136` is emphatic
   that this "is not a weaker claim and is not checked more weakly": the ledger
   op refuses a citation of a reference the project does not carry, or a page
   past its end, with `invalid_requirement` and nothing written, and
   `unsourced_requirement` verifies a document citation against the stored
   extracted text exactly as it verifies a prompt quote.
3. Any `CHECKS` threshold then cites that ledger id, satisfying
   `unsourced_constant` (`VALIDATION.md:117-121`).

**The one new join, and its honest limit.** A ledger citation names a reference
*the project carries*; a component lives in a *registry*, shared across
projects, and knows nothing about any project's `references/`. The two
provenance systems do not meet today.

An earlier draft of this section proposed to infer the join: select the
candidate reference *by* `sha256` equality with the component's
`datasheet.sha256`, then report `datasheet_digest_mismatch` *if the digests
differ*. That rule is **logically empty** — a set defined by equality contains
no unequal member, so it can never fire, and a pytest cannot be written to it.
Read the other way, it fires on every project carrying any unrelated drawing.
Under rule 1 the repair is to make the join precise, not to drop the check.

**The join is operator-declared, through the ledger, and is checkable exactly.**
A component claim reaches a project the same way every other outside number
does: a ledger entry citing `{reference, page, quote}` (`VALIDATION.md:122-136`;
`RequirementCite` in
`server/src/hephaestus/agent_bridge/cad_ops/_requirements.py`). That citation
gains two optional fields naming what it transcribes:

```json
{"source": "specified",
 "cite": {"reference": "nema17-datasheet.pdf", "page": 3,
          "quote": "Holding torque 0.44 N·m",
          "component": "stepper_nema17_frame", "claim": "torque_speed"}}
```

Both fields are present or both absent (`incomplete_component_cite` otherwise),
`component` must name a part the project's registries carry and `claim` an id in
that component's `claims`, or the ledger op refuses with `invalid_requirement`
and writes nothing — the existing refusal, on the existing path
(`VALIDATION.md:126-129`).

The rule is then decidable, in both directions:

- For each ledger entry whose `cite` names component claim `C` in component `K`
  and reference `R`, `datasheet_digest_mismatch` fires **iff**
  `ReferenceEntry(R).sha256 != K.datasheet.sha256`
  (`references.py:158-166`) — same document, different bytes, which is the
  revision-drift case that silently poisons transcribed numbers.
- The rule is **silent** when no ledger entry names a component claim. An
  unrelated registered reference whose digest differs from some component's
  produces no finding, ever; nothing is inferred from the mere co-presence of a
  reference and a component. G11C clause 7 is that negative clause, and it is
  the one an inferred join could not have had.

With no such ledger entry the component's `datasheet` pointer remains an **audit
trail naming exactly which document to obtain** — not a verified citation, and
the vocabulary does not claim it is.

### 7.5 `LEGAL-REVIEW.md` does not exist

Verified: `ls LEGAL-REVIEW.md` at the repository root returns "No such file or
directory". It is a planned Stage 7 deliverable. Its declared schema is four
scope fields — "reviewer, date, scope: ToS analysis of the reference product,
reference-fixture publication decision, trademark scan of identifiers"
(`mission_plan.md:643-645`) — and `mission_plan.md:448-449` records that it "is
NOT a G7H blocker: it gates publication of the private reference fixtures and
the full release, not the headless tool."

**None of those four fields covers third-party component data.** This spec
therefore does not cite `LEGAL-REVIEW.md` as authority for anything, and no
clause below depends on it. It instead **tightens** that gate, per rule 1, by
adding a fifth required scope field — *third-party component data provenance
and terms: which standards were used, that no vendor payload is vendored, and
that every `datasheet` pointer's terms permit reference-by-citation*.
Publication of a component pack is blocked until that field is signed off;
development is not, matching the existing rule that the review "blocks only
publication, not development".

**Where that fifth field is actually written, as of the 2026-08-29 amendment.**
Not in G7's checklist sentence: an amendment opening one stage does not rewrite
another stage's gate text, so the requirement is stated in the `mission_plan.md`
Stage 11 block and here, and `mission_plan.md:643-646` still lists four fields.
This is named rather than glossed because a reader who greps G7 for the fifth
field will not find it. Two obligations follow. Whoever next amends G7 folds the
field into that sentence — the amendment that adds it is a one-line edit, and
the checker below already validates five fields, so the gate and the checker
would otherwise disagree in G7's favour. And until then, nothing may cite G7 as
the authority that third-party component data was reviewed; the authority is the
Stage 11 block.

**The CI schema check does not exist either, and this spec does not pretend it
does.** `mission_plan.md:646` says "CI checks the file's schema", but the file
is a declared forward reference — `scripts/docs_check.py:101` lists
`LEGAL-REVIEW.md` in `FORWARD_REFERENCES` as "Stage 7 legal review, not a G7H
blocker" — and there is no checker for its four fields anywhere in the tree
(`grep -rn LEGAL-REVIEW --include=*.py --include=*.yml` returns that one line and
nothing else). An earlier draft of this section wrote "checked by the same CI
schema check that checks the other four", which asserts a mechanism that is not
there — precisely the failure the `KINEMATICS.md` convention names, that unnamed
or misnamed machinery is a claim of existence. So the checker is **named new
work** (item 33), it ships with this stage rather than waiting on Stage 7, it
validates all five fields against a fixture, and it is gated (G11C clause 15).
Stage 7 then inherits a checker instead of owing one.

## 8. Federation: one registry per kind is a silent drop

`RegistrySet.__init__` does `by_kind.setdefault(registry.kind, registry)` and
builds every index from `by_kind.get(<kind>)`
(`core/src/hephaestus/core/registry/_set.py:33-40`). **A second `parts`
registry is silently discarded** — no warning, no error, and which one survives
depends on `hephaestus.toml` table order plus the bundled fallback
(`_set.py:57-60`). Any story in which a vendor component pack sits alongside
the bundled `hephaestus-parts` is broken today, and would fail as a missing
part rather than as a configuration error.

- **G11A ships the refusal.** `setdefault` becomes an explicit check: two
  registries of one kind is `duplicate_registry_kind`, naming both, refusing to
  open the set. Fail-closed, and it converts a silent wrong answer into a
  configuration error the operator can fix. This is a behaviour change for any
  project that currently pins two of a kind and is unknowingly using one — which
  is precisely the population that should be told. **G11A clause 18 was amended
  on 2026-08-29** to name the *unfederated* kinds outright rather than `parts`,
  once the next bullet was scheduled into G11C; the amendment is written out at
  that clause, and it scopes the refusal rather than waiving it.
- **G11C ships merged federation**: several `parts` registries indexed
  together, ids addressed `<registry>/<id>` when ambiguous and bare when
  unique, with a named `ambiguous_component_id` refusal rather than a
  precedence rule. Deferred to its own sub-gate because the addressing decision
  deserves its own evidence, and because the refusal above makes the interim
  state honest.

## 9. Determinism

Stated per artifact, because these do not all have the same status.

**Bit-reproducible, and gates may assert byte equality:**

- The registry Merkle root and its leaf list. `_digest.py` binds path and
  content into every leaf, so a rename is as detectable as an edit, and the
  publication record carries every `(path, digest)` pair (`_publish.py:99-125`).
- The rendered `script_fragment` — **at a fixed tree state**, which is the only
  comparison a gate makes of it. `render_fragment` is pure string manipulation
  (`_generator.py:296-340`) over a prefix derived from
  `json.dumps(..., sort_keys=True)` then sha256 (`:249-255`), and numeric
  literals go through `_literal` (`:241-244`), which is `repr` of an int or a
  float — round-trip exact, not formatted. So two *processes* reading the same
  tree produce the same bytes, header included (G11B clause 20). Two *tree
  states* do not, and no clause asserts they do: the `# registry: … @ <digest>`
  line carries the Merkle root, so any registry byte moving moves it. Every
  cross-tree-state clause elides that line and asserts digest honesty separately
  (G11A clauses 1–3). Read this bullet as "reproducible", never as "invariant
  under this stage's own edits" — conflating the two is exactly the false claim
  §10 withdraws.
- The emitted interface tag names, their count, and their order.
- Every named refusal above: same input, same reason, same detail.
- A declared mass, COM, and every `claims` sample. Declared data is copied, not
  computed.

**NOT bit-reproducible across environments:** anything the geometry kernel
computes — `Metrics.volume_mm3`, `area_mm2`, face and edge counts, the
`geom_type` classification `interface_class_mismatch` reads, and the descriptor
`scalar` that `interface_placement_drift` compares, all of which depend on the
OCP/OpenCascade build. The project already answers this with a pinned CI image,
and this stage inherits that answer rather than inventing one.

Note the asymmetry `interface_placement_drift` exploits: the descriptor `scalar`
is *not* reproducible across kernel builds, but it *is* invariant under rigid
motion **within one build**, which is the only comparison the rule makes. It
compares the unplaced and placed builds of the same instance in the same
process, to the same 1e-9 the residual gates use, and never compares across
processes. A rule that compared a recorded scalar to a fresh one would be
measuring the kernel.

The registry Merkle root **does** move whenever any registry byte moves, and
this stage moves several (§1). That is determinism working, not failing: the
gate asserts fragment-body invariance under an elided digest line plus digest
honesty as a separate clause, never whole-fragment byte identity.

**How the gates bind.** Clauses that must be exact bind to the reproducible
list: identical fragment bytes from two processes, identical tag names,
identical digests, identical refusal reasons. Clauses that touch kernel output
bind to a **named tolerance**, 1e-9, which is the tolerance G8C and G9A already
use for residuals and transforms (`ASSEMBLY.md:135`; `KINEMATICS.md:362`).
Interface class verification binds to the topology *class* — an enumerated
label, stable where a coordinate is not — and never to a face index, because a
face index is a kernel-ordering artifact and a gate that pinned one would be
measuring the kernel, not this stage.

## 10. What deliberately does NOT change

No new registry kind (`BUNDLED_KINDS` and `RegistryKind` are untouched,
`_layout.py:38-41`). No second store, no parallel index, no non-registry
component catalogue. No new geom service — this stage adds nothing to the nine
pure services and the geom import-boundary test should remain able to enumerate
exactly those nine. No solver: `ASSEMBLY.md:55-57` stands, and a component is
placed by `pos` and by nothing else. No dynamics, loads, FEA, motor sizing, or
inertia. No change to `Param`, to the override merge path, or to bounds
enforcement (`_ops.py:237`, bounds are the worker's job).

**No change to the sandbox *contract*** — the sandbox boundary itself, the
injected-namespace whitelist
(`core/src/hephaestus/core/executor/namespace.py:1-13`), `DENIED_BUILTINS`
(`:47-62`), or the rule that generators run only under a probed secure backend
(`_ops.py:196-203`). A component generator is exactly as untrusted as a store
generator is today, and the G6 clause that a published, pinned generator
attempting `open("/etc/passwd")` is still denied and the refusal quotes no file
contents remains the governing evidence (re-asserted against a component tree by
G11A clause 22). **This is not a claim that the §8 worker result protocol is
unchanged — it changes**, by one field, `geom_type` on each `tag_fingerprints`
entry, because §2.3's verdict cannot be computed anywhere else. The two are
different contracts and this spec no longer lets one sentence cover both.

Nor is it a claim that `namespace.py` is byte-untouched. It gains one **derived
export**, `SELECTOR_NAMES` — the injected key set minus `__builtins__` and
`__name__` — for §2.1's parse-time rule, which cannot cite a dict that
`build_namespace` only assembles at execution time (`:496-538`). No name enters
the namespace, none leaves, `DENIED_BUILTINS` is unchanged, and the constant is
pinned equal to `injected_names(build_namespace(...))` so it can only ever
*describe* the whitelist, never define a second one. Stating this rather than
letting "no change to the sandbox contract" cover it is the same discipline the
paragraph above applies to the §8 protocol: one sentence, one contract.

No tool is added; two result schemas grow. No fetch of any URL, ever. No change
to `references/`: registration stays operator-only.

**Legacy store parts without a `component` block behave as today** — with the
precision §1 states and the earlier draft did not: the fragment *body* is
byte-identical, the `# registry: … @ <digest>` header line moves because this
stage moves the tree's Merkle root, and both halves are separately gated
(G11A clauses 1–3). The claim "byte-for-byte as today, including their
fragments" was false and is withdrawn.

`run_dfm`, `generate_drawing`, `generate_doc`, `export_part` and the
nesting/cut-file path are untouched.

## Named new work

Nothing in this section exists today. Anything a reader believes this stage
needs that is absent here is a defect in this list, per the `KINEMATICS.md`
convention that unnamed machinery is a claim of existence.

**Parser and rendering (`_generator.py`, `tags.py`)**

1. The fourth `interface` marker region: constant, position enforcement, and
   the region-order check extended from three markers to four (`:99-113`).
2. `_check_interface_region` — the §2.1 AST contract in full: `ast.Expr` of an
   `ast.Call` on `ast.Name("tag")`, two positional arguments, no keywords;
   argument 2 an `ast.Constant` `str` matching the interface-name grammar and
   free of `__`; argument 1 free of walrus/lambda/await/starred/f-string/
   comprehension nodes, with every loaded `ast.Name` in
   `{root_name} ∪ SELECTOR_NAMES` — **not** `bound_names`, whose admission was
   the §2.1 hole that let a selector mix the placed root with an unplaced local.
   `tag` permitted here and nowhere else, with `_FORBIDDEN_NAMES` (`:42`)
   unchanged for the body. Refusals: `interface_region_violation`,
   `interface_body_local_reference`.

   Riding with it, because the rule is undecidable without it:
   **`SELECTOR_NAMES` in `namespace.py`** — one exported frozenset,
   `injected_names(build_namespace(...)) - _DUNDERS - _HANDLES` with both
   exclusion sets declared beside it (§2.1), so the parse-time rule cites a
   declared constant instead of the runtime dict `build_namespace` assembles
   (`namespace.py:496-538`). Pinned by that equation, so a build123d upgrade
   cannot silently widen or narrow what the region may name, a harness handle
   cannot creep back in, and there is one definition of the namespace rather
   than two (rule 6).
3. Static extraction of the declared interface-name set from the region, for
   the index, without execution.
4. **The chain-root rule and the post-placement rewrite.** `parse_generator`
   refuses a selector whose chain root is not `root_name`
   (`interface_root_violation`, `_generator.py:230-238` supplies the name).
   `render_fragment` then emits the interface region *below* the tail
   (`:334-337`), rewriting **every whole-token occurrence** of the renamed root
   `{prefix}{root}` to `{prefix}` — the placed instance — and rewriting each tag
   literal to `<instance>__<name>`. Three properties, none of them optional:
   the region below the tail, *every* root occurrence rewritten (not just the
   chain root), and the literal rewritten. Rewriting only the literal is the bug
   that made an earlier draft of §2 inoperative for any instance not at the
   origin; rewriting only the chain root is the same bug at one remove, and is
   why item 2 refuses body locals in argument 1 as well. Stripping stays exactly
   the `part.geometry` line and no other (`:327`).
5. The `instance` argument: grammar validation, `invalid_instance_name`, and
   the fallback to `instance_prefix` (`:247-256`).
6. `TagRegistry.tag` scoped duplicate refusal for `__`-infix names
   (`tags.py:84`), leaving last-wins semantics intact for every other name.
7. **Unplaced `__`-infix tags become build errors, not warnings**, in the
   consumer's own build: `worker.py:562-573` today appends a `tag_unresolved`
   warning for any unplaced tag; a store-instance interface tag that does not
   resolve raises `interface_not_placed` instead. Plain tags keep the warning.

**Worker result protocol (`worker.py`, `fingerprint.py`, `runner.py`)**

8. `geom_type` on `TagDescriptor` — `PLANE | CYLINDER | CIRCLE | LINE | OTHER`,
   read off the shape's adaptor **in the worker** (`worker.py:580-584`), because
   nothing else crosses the boundary carrying a surface or curve type
   (`fingerprint.py:64-75` has none; `TagPlacement.kind` and `_classify` are the
   same three-way label, `tags.py:32-38`, `:105-118`). It rides the existing
   `tag_fingerprints` channel through `descriptors_to_json`, the `runner.py:375`
   parse and the published copy at `publication.py:472`. **This is a §8 protocol
   change**, listed in the Amendment manifest, and it re-pins
   `core/tests/test_worker_protocol.py`. Without it §2.3's verdict is not
   computable at all.

**Record schema and index (`_parts.py`, `_layout.py`, `_publish.py`)**

9. `ComponentRecord` and `ComponentInterface` dataclasses, plus their parsers
   and the closed `class` / interface-class / role / mass-source / claim-kind
   vocabularies.
10. Required-interface-per-class table and `missing_required_interface`.
11. Interface-name set equality between record and generator region
    (`undeclared_interface` / `unimplemented_interface`).
12. `part.json` params ⇄ generator `PARAMS` cross-check — `PartsIndex` must
    call `parse_generator`, which it does not do today (`_parts.py:62-101`) —
    and `param_schema_drift`.
13. Registry `license` required: `opt_str` → `req_str` at `_layout.py:78`, and
    `unlicensed_registry`.
14. Per-component `license` / `data_license` fields; today licence is one string
    for a whole tree (`_publish.py:99-104`).
15. Mass block, `mass_source_conflict`, `unsourced_component_datum`, and the
    `inertia_out_of_scope` refusal.
16. `claims` block and the `torque_speed_curve` well-formedness validator
    (`malformed_performance_curve`), plus the two §6.1 closure rules that make
    §7.4's join total: a non-empty `claims` list requires the record's
    `datasheet` block (`unsourced_component_datum`), and `claims[].id` is unique
    within a record (`duplicate_claim_id`).
17. `datasheet` pointer block with all six required fields and `sha256:`
    prefix validation.
18. Publish-time payload scanner (`vendored_third_party_payload`) and the
    component-id trademark scan (`trademark_in_component_id`).
19. Retirement of `envelope` / `mating_features` / `origin` / `simplifications`
    from the six shipped `part.json` files: promoted into the validated block or
    deleted. **Its stated deliverable is a Merkle-root change** — every one of
    these edits moves the tree digest and therefore the `# registry: … @ …`
    header line of every fragment the tree produces, including parts this item
    does not touch (§1). So it ships with its own evidence: fragment bodies
    regression-pinned *before* the edit under an elided digest line, the new
    root re-published and re-pinned, and `publication_drift` naming exactly the
    edited `part.json` files (G11A clause 3). An earlier draft's hedge that
    the fragments would be "regression-pinned first" was the pin this item
    breaks; pinning the body and asserting the digest move separately is the
    repair.
20. A **frozen legacy fixture tree** at `tests/stage11a/fixtures/legacy_parts/`
    — store parts with no `component` block, edited by nothing in this stage, so
    that clause 1's "carries no component fields" evidence does not rest on the
    six shipped parts that item 19 gives component blocks to.

**Instantiation (`_ops.py`)**

21. Post-build interface verification: read `build.tag_fingerprints` and the
    in-memory `source_map` off `UnpublishedBuild` (`runner.py:126-131`) rather
    than discarding them (`_ops.py:176-187` reads only `result.params` and
    `result.metrics` today), match each emitted tag, and compare `(kind,
    geom_type)` to the declared class — `interface_class_mismatch`,
    `interface_not_placed`, `interface_placement_drift`.
22. **The placement-verification build.** When `_placement` returns a non-empty
    expression (`_generator.py:259-292`), a second sandboxed build of the
    rendered fragment plus a synthesized `part.geometry = {prefix}`, under the
    same `origin="registry"` backend, so verification happens at the caller's
    `pos` and not only in the generator's pos-free frame. Skipped when the
    placement expression is empty, where `{prefix}` aliases the root. Gated for
    both correctness and cost (G11B clauses 9 and 12), per rule 4.
23. Result-shape extension: `interfaces` (emitted names), `mass`, `datasheet`,
    `claims` wrapped as reference material through `wrap_reference`.

**Registry set (`_set.py`)**

24. `duplicate_registry_kind` replacing `setdefault` (`:33-35`).
25. (G11C) Merged multi-registry indexing per kind, `<registry>/<id>`
    addressing, and `ambiguous_component_id`.

**Lint and ledger**

26. `uncited_component_datum` lint rule.
27. **The ledger citation extension**: `RequirementCite` gains optional
    `component` and `claim` (`server/src/hephaestus/agent_bridge/cad_ops/`
    `_requirements.py`), both-or-neither (`incomplete_component_cite`), with an
    unknown component id or claim id refused as `invalid_requirement` and
    nothing written, on the existing refusal path (`VALIDATION.md:126-129`).
    This is what makes the §7.4 join operator-declared rather than inferred.
28. `datasheet_digest_mismatch` lint rule: for each ledger entry whose `cite`
    names a component claim and a reference, fire iff
    `ReferenceEntry.sha256 != component.datasheet.sha256`
    (`references.py:158-166`); silent when no entry names a component claim. The
    one genuinely new cross-system join, and the only one proposed.

**Contract surface**

29. Two tool result-schema amendments and one new optional argument, through
    the five generated drift-tested artifacts, with per-profile dispatch tests
    on both profiles. The record-only fields (`component_class`, `series`,
    `mass_g`, `has_datasheet`) land in G11A; `interfaces` lands in G11B with
    the renderer that populates it, because a schema field no code can fill is
    not evidence of anything.
30. `heph registry components [--json]` operator listing.

**Content and docs**

31. The seeded component packs themselves: motors, bearings, gears, encoders,
    structural fasteners — authored geometry, records, interfaces, and
    provenance. This is the bulk of the calendar time and none of it is
    machinery.
32. `registries/PUBLISHING.md` component-authoring section, including the pos-invariant
    selector authoring rule §2.1 names and `interface_placement_drift` can only
    partly enforce; `docs/registry-contributions.md` checklist items;
    `repo_conventions.md` and `CONTRIBUTING.md` clauses of §7.
33. The `LEGAL-REVIEW.md` fifth scope field **and the CI schema check itself**,
    which does not exist today (`scripts/docs_check.py:101` carries the file as a
    `FORWARD_REFERENCES` entry and nothing checks its fields). The check
    validates all five scope fields against a fixture and is gated by G11C
    clause 15; `mission_plan.md:643-646` is amended to name it. This stage does
    not *hold* the human review — that stays Stage 7's one deliberately human
    step — it ships the machine half so the review has something to fail against.
34. A corpus family for component-bearing mechanisms, with its own split
    baselined on its own first measurement — never averaged into the v1/v2
    baselines, the `VALIDATION.md` §1 rule as G9C restates it
    (`KINEMATICS.md:392-398`). **Amended 2026-08-29** (see G11C clause 12): the
    family is a first-class object in `hephaestus.bench.scoring`, not a
    convention a future operator applies by hand — `CORPUS_FAMILIES` (closed),
    `split_name` carving family runs out of both spec splits so the 0.70 bar
    cannot be diluted, `component-prose` / `component-seeded` splits carrying no
    threshold, and `record_component_baseline` writing the first measurement
    once and refusing one below three seeds per task by the name
    `insufficient_component_seeds`.

**Explicitly deferred, and NOT in this stage** (each would be its own
amendment): the torque-margin predicate and its ledger demand side (§6.4); an
enumerated `Param` kind (§4); inertia tensors and any dynamics; merged
federation beyond G11C's scope; any vendor-CAD ingest path.

## Gates

Three sub-stages, strictly ordered. Every clause is a pytest assertion; a
clause that could only be satisfied by inspection is a defect in this section.

**And every one of them is a command in CI** (mission rule 1: "Gates are
commands. Every criterion above maps to a CI job."). The three suites run in
`.github/workflows/ci.yml`'s `stage gates 11A-11C` job on every PR and push to
`main`, and that check name is in `release.yml`'s required prior-gate list, so a
release cannot be cut over a red Stage 11. Added 2026-08-29, after a verifier
observed that these were the only stage suites in the repository with no
workflow lane: three Tier-1 gates that pass on a developer's machine are not
gates yet. The lane provisions bubblewrap (G11A's runtime-sandbox refusal) and
the Mesa software stack (G11C clause 11's engine-path grading) and deliberately
no Node — the contract-drift clauses compare the committed `schema.gen.ts`
against the generator's output in-process, and a prerequisite a lane does not
need is noise rather than safety. G11C clause 12's Tier 3 measurement is the one
thing not in that job, and it is archived bench evidence by construction; see
the clause.

**Ordering is a correctness property of this section, not a convenience.** A
clause in sub-stage A that binds to machinery sub-stage B delivers cannot pass
when A runs, and an earlier draft had two such clauses (a sandbox refusal
routed through the interface region, and a contract-drift clause dispatching a
result field only B's renderer can populate). Both have been moved to B, and
each sub-stage's clauses are now satisfiable with only that sub-stage's Named
new work and its predecessors'.

**Every Named new work item is assigned to a sub-stage, in writing.** Leaving
the assignment implicit is how the ordering bug above survived a draft: a
reader could place an item in A because it sits in an `_parts.py` paragraph
while its other half sits in B's parser. So:

| Sub-stage | Named new work items |
|---|---|
| **G11A** | 8, 9, 10, 12, 13, 14, 15, 16, 17, 18, 19, 20, 24, 30; item 23's `mass` / `datasheet` half; item 29's record-only half; item 31 for the seeded records |
| **G11B** | 1, 2 (including `SELECTOR_NAMES`), 3, 4, 5, 6, 7, **11**, 21, 22; item 23's `interfaces` half; item 29's `interfaces` half; item 31 for those records' interface regions |
| **G11C** | 25, 26, 27, 28, 32, 33, 34; item 23's `claims` half; item 31 for the completed packs |

**Item 11 is the one that had to be decided rather than inherited.** Record ⇄
region interface-name set equality (`undeclared_interface` /
`unimplemented_interface`) is listed under "Record schema and index", which reads
like A, but *half of it is B's parser*: there is no region to compare against
until items 1–4 land. Assigning it to A would make every A clause that indexes a
component record — 4–14, 19, 20, 21, 22, 23 — depend on B, which is the ordering
bug in its purest form. So **item 11 is G11B work, gated by G11B clause 6.** The
consequence is named, not hidden: for the duration of A, a component record may
declare interfaces its generator does not yet emit, and A's own clauses do not
catch that. This is honest because A publishes no component pack as a
deliverable — item 31's packs complete in C — and because §1's per-class
*required-interface* rule (item 10, record-only, G11A clause 5) still fires in A,
so a record cannot omit the interfaces its class demands. What A cannot check is
whether a generator implements them; B is where that becomes checkable, and B is
where it is checked.

### Gate G11A — the component record

`uv run pytest tests/stage11a -q` exits 0, covering:

1. **Legacy fragment-body invariance.** Each frozen legacy fixture part (item
   20) indexes, searches, and instantiates with a `script_fragment` that is
   byte-identical to a recorded golden **after the `# registry: … @ <digest>`
   line is replaced by a fixed sentinel** — binds, renamed locals, kept body
   lines, the placement statement and the `.label` line pinned exactly. Whole-
   fragment byte identity is *not* asserted and cannot be: the header carries
   the tree's Merkle root, which this stage moves by construction (§1, §9).
   `search_parts_store` results for a legacy fixture part carry no component
   fields.
2. **Digest honesty.** For each fragment in clause 1, the elided header line's
   digest equals `merkle_digest(tree)` recomputed in the test
   (`_digest.py:53-60`), and equals the value the publication record carries. The
   header therefore still cannot drift silently.
3. **The shipped six, and the digest change item 19 delivers.** Each shipped
   part's fragment body is pinned under the clause-1 elision against a
   **recorded golden**, on both sides of item 19. After the edit: the tree's
   Merkle root differs from the pre-edit root; the new root is re-published and
   re-pinned; `publication_drift` against the pre-edit publication record names
   **exactly** the edited `part.json` files and no others
   (`_publish.py:190-224`); and every shipped part's fragment body is unchanged
   under the clause-1 elision, including the parts item 19 did not edit.

   **Amended 2026-08-29, under rule 1** — a tightening, and it closes a hole
   this clause had rather than opening one. The "pre-edit" tree is a *recorded
   fixture*, and the clause now says in writing what has to be recorded in it:
   **both** `part.json` and `generator.py` for all six parts. An earlier form
   recorded only `part.json` and read `generator.py` from the current shipped
   tree, which made the reconstruction a hybrid the moment item 31 appended an
   `interface` region to those same six generators — and made the fragment-body
   assertion compare one generator against itself, so it could not fail. Three
   consequences are now required rather than assumed:

   - the recorded "before" bytes are asserted to *differ* from the shipped
     bytes, for both files, so a "before" fixture cannot silently become a copy
     of "after";
   - the `publication_drift` sentence above is asserted over the **whole** drift
     set of a tree where item 19 is the only difference (generators held at their
     recorded bytes on both sides), not over a filtered view of the whole
     stage's drift — and the whole stage's drift is *additionally* asserted in
     full, with every file attributed to the item that moved it: item 19's six
     `part.json`, item 31's six `generator.py` interface regions, `registry.toml`,
     and the packs G11C's half of item 31 adds. Nothing is filtered out of either;
   - "unchanged under the clause-1 elision" is asserted as the pre-stage
     fragment being a strict **prefix** of the shipped one, with the remainder
     parsed and required to be exactly item 31's region — every statement a `tag`
     call whose name literal is instance-scoped (§2.2). Equality would be the
     false statement: the bodies genuinely grew a region this stage, and the
     claim clause 3 owns is that *item 19* moved no body line.
4. `component.class` outside the closed set is `unknown_component_kind` at
   index time, the message listing the valid set.
5. A `motor` record lacking `shaft` or `mount_face`, and a `bearing` lacking
   `bore` or `outer`, are each `missing_required_interface` naming the missing
   interface.
6. A duplicate interface `name` within one record is `duplicate_interface_name`;
   a duplicate `claims[].id` within one record is `duplicate_claim_id`. Both
   name the repeated identifier, and both matter because a ledger
   `cite.component`/`cite.claim` pair and an emitted `<instance>__<name>` tag
   each have to resolve to exactly one thing (§6.1, §7.4).
7. An interface `class` outside the closed set is `unknown_interface_class`.
8. `param_schema_drift`: a record advertising a parameter the generator's
   `PARAMS` lacks, and a record omitting one it has, are each refused at index
   time, naming the parameter — **and** `heph registry publish` refuses the same
   tree, since `validate_content` builds the index (`_publish.py:50-63`).
9. `unlicensed_registry`: a `registry.toml` with no `license` refuses to parse;
   an existing licensed tree still parses unchanged.
10. `unsourced_component_datum` on (a) `mass.source="datasheet"` with no
    `datasheet` block, (b) `mass.source="standard"` with no `series.standard`,
    (c) a `claims` entry with no `cite`, (d) a non-empty `claims` list on a
    record with no `datasheet` block — the case that makes §7.4's
    `K.datasheet.sha256` always defined for a component a ledger entry may name
    (§6.1).
11. `mass_source_conflict` when a datasheet mass and a computed-mass material id
    are both declared.
12. `inertia_out_of_scope` on a record carrying an inertia tensor, the refusal
    naming the field.
13. `malformed_performance_curve` for each of: one sample; a non-finite value;
    non-increasing `x`; negative `y`; increasing `y` across the range; an
    undeclared unit — each naming the offending sample index.
14. `datasheet` block validation: each of the six fields missing in turn is
    refused; a `sha256` without the `sha256:` prefix is refused.
15. **Contract drift, record-only half.** The 53-tool count is unchanged; the
    five generated artifacts regenerate identically from the declaration; both
    profiles dispatch `search_parts_store` and `instance_store_part` carrying
    the **record-only** new fields — `component_class`, `series`, `mass_g`,
    `has_datasheet`, `mass`, `datasheet`. The `interfaces` field is *not*
    asserted here: it is populated only by the renderer G11B delivers, and a
    schema field no code can fill is not evidence of anything. G11B clause 17
    is its half.
16. **Seam invariance.** The geom import-boundary tests pass unchanged and
    enumerate exactly the nine existing pure services — this stage adds none.
17. **Worker protocol drift.** `core/tests/test_worker_protocol.py` passes with
    `geom_type` present on every `tag_fingerprints` entry and drawn from the
    closed set; a published build's `tag_fingerprints` round-trips the field
    (`publication.py:472`); a descriptor with an out-of-set `geom_type` is
    refused at parse (`runner.py:375`).
18. `duplicate_registry_kind`: a project pinning two registries of an
    **unfederated** kind — any kind outside `RegistrySet.FEDERATED_KINDS`, which
    today is `skills`, `materials` and `dfm` — refuses to open the set, naming
    **both registry names and both roots**; a project pinning one still opens;
    and `FEDERATED_KINDS` is itself asserted, so federating a further kind cannot
    silently retire this clause's subject.

    **Amended 2026-08-29, under rule 1.** This clause read "a project pinning two
    `parts` registries", which was written before §8's own second bullet was
    scheduled into a sub-gate: **G11C clause 9 federates `parts`**, so two
    `parts` trees now index together and a colliding id is a per-id
    `ambiguous_component_id` refusal. The refusal is therefore *scoped*, not
    waived — it keeps its job for every kind where §8's silent drop is still
    reachable, and the `parts` half of the behaviour is G11C clause 9's to
    evidence. Leaving the old text standing would have left a clause no test
    could satisfy while its covering test quietly re-sited itself, which is the
    gate-to-test mismatch rule 1 exists to close.

    The amendment **tightens** in the same breath: "naming both" is now "both
    names and both roots". Two vendor packs of one kind routinely carry the same
    manifest `name` — a fork, or a copy of the bundled tree — and a refusal that
    prints one name twice tells the operator nothing about which pin to remove.
    The roots are the part that is always distinct.
19. `vendored_third_party_payload`: publishing a `parts` tree containing a
    `.pdf`, a `.step`, and a `.png` is refused, each file named.
20. `trademark_in_component_id`: a component id on the deny-list is refused at
    publish.
21. **Tamper refusal.** A one-byte edit to a component's `generator.py`, and
    separately to its `part.json`, each changes the Merkle root and makes the
    pinned tree refuse to load with `RegistryIntegrityError` carrying
    `expected`/`actual`; `publication_drift` names exactly the modified file and
    reports an added file as `added` — the G6 shape
    (`tests/stage6/test_g6_registry_integrity.py:121-149`) re-asserted against
    component content, since G6's evidence was recorded against a DFM tree.
22. **Runtime sandbox refusal, re-asserted against a component tree.** A
    component generator whose **body** region attempts `open("/etc/passwd")`,
    published and pinned, is denied through the real `instance_store_part` tool
    with `sandbox_denied`, and the refusal quotes no file contents. The body
    region is where this is reachable: the *interface* region's file IO is
    refused by the parser before a tree containing it can be indexed, hence
    before it can be published, so its control is G11B clause 11 and not a
    runtime denial. Deleting this clause because the interface-region form is
    unreachable would have dropped the only component-tree re-assertion of G6's
    governing evidence; it is re-sited, not weakened.
23. **Determinism.** Two processes produce identical Merkle roots, identical
    leaf lists, and identical refusal reasons and details for clauses 4–14.
24. **`heph registry components [--json]`** (item 30) lists every component
    record in the pinned registries with its class, series, declared interface
    names and `has_datasheet`, listing legacy parts not at all; `--json` output
    is byte-identical across two processes and its key order is stable. A
    deliverable with no clause is an ungated deliverable, which this section
    treats as a defect in itself.

### Gate G11B — mounting interfaces as tagged geometry

`uv run pytest tests/stage11b -q` exits 0, covering:

1. A generator with an `interface` region parses; the four markers out of order,
   duplicated, or with `interface` before `body` are each refused.
2. **`interface_region_violation`, enumerated against the §2.1 AST contract**
   and not against the word "nested" — a region built of nested selector calls
   is the mechanism, so a rule refusing nested calls would refuse the spec's own
   example and leave the region able to tag only a bare solid. Each of the
   following is refused, and each is decidable by a parser: a statement that is
   not a `tag` call; a `tag` call with a non-`ast.Constant` name argument; a
   name argument that is a `str` constant but violates the interface-name
   grammar or contains `__`; a `tag` call with keywords, `*args`, or other than
   two positional arguments; an `ast.Assign`, `ast.AugAssign` or walrus; a `tag`
   call appearing as a sub-expression rather than as the statement; a lambda,
   comprehension, `await`, starred expression or f-string inside argument 1; a
   loaded free name that is neither `root_name` nor in `SELECTOR_NAMES` —
   including, specifically, a selector reading `p.<param>`, which is the bind
   region's alone. The whitelist itself is asserted, not assumed:
   `SELECTOR_NAMES == injected_names(build_namespace(...)) - _DUNDERS - _HANDLES`
   holds exactly (`namespace.py:502-538`), every member of `_HANDLES` is refused
   in the region by name, and `GeomType`, `SortBy`, `Axis` and `math` are
   admitted — so the parse-time rule and the execution-time namespace cannot
   drift apart in either direction.
3. **The canonical region parses.** Both statements of §2.1's example —
   attribute chains, method calls, `filter_by`/`sort_by` arguments and a
   subscript — parse clean. This is the negative control on clause 2: a
   tightening that refuses the mechanism is a defect, not a stricter gate.
4. **Rooting, and the body-local refusal.** `interface_root_violation`: a
   selector whose chain root is a body local other than `root_name`, and one
   whose chain root is a whitelisted callable rather than a name binding
   (`Compound(children=[_root]).faces()[0]`), are each refused, naming the
   offending root and `root_name`. `interface_body_local_reference`: a selector
   correctly rooted at `root_name` that nevertheless *loads* a bind or body
   local anywhere in argument 1 — `_root.faces().sort_by(SortBy.DISTANCE,
   _hub.center())[0]` and `_root.faces().filter_by(Plane(origin=(0, 0,
   _body_length)))[0]` are the two shapes of it, one geometric and one scalar —
   is refused, naming the local. This is the clause with the sharpest teeth in
   the sub-gate: without it the post-placement rewrite retargets the root and
   leaves the local in the unplaced frame, and the selector resolves to a real
   face that is the wrong one.
5. `tag` in the `params`, `bind` or `body` region is still refused, message
   unchanged from `_generator.py:199-206`.
6. **Record ⇄ region set equality** (Named new work item 11, which lands here and
   not in G11A because there is no region to compare against until clause 1's
   parser exists): `undeclared_interface` (region tags a name the record omits)
   and `unimplemented_interface` (record declares a name the region never tags),
   each naming the offending interface. Both directions, on the same record, in
   the same suite.
7. **Emitted names.** The fragment's tag literals are exactly
   `<instance>__<name>` for every declared interface, with the caller's
   `instance` when supplied and the `instance_prefix`-derived value when not;
   `invalid_instance_name` for an instance not matching the ident grammar.
8. **Emitted position and rooting.** In the rendered fragment the interface
   region appears **below** both tail lines (`_generator.py:334-337`), every
   selector's chain root is the instance name `{prefix}`, not the renamed body
   local `{prefix}{root}`, and the token `{prefix}{root}` does not appear
   **anywhere** in the emitted region — asserted by tokenising the region, not by
   substring search, so `{prefix}{root}_face` is not mistaken for it. Asserted on
   the fragment text, so the rewrite that makes clause 9 possible is pinned
   independently of any build.
9. **Placement resolution at a non-trivial `pos`** — the clause the placement
   bug would have failed. A component is instanced at a **non-zero translation
   *and* a non-zero rotation**; the placement-verification build runs; every
   interface tag resolves with `solid_index is not None` and
   `topo_index is not None`, and every one resolves through `PartGeometry` to a
   shape rather than `unaddressable_anchor` (`assembly.py:500-506`). The same
   assertion at translation-only and at rotation-only. A deliberately
   body-local-rooted fragment (constructed by bypassing clause 4) resolves to
   `solid_index is None` for every tag, proving the clause has teeth.
10. **`interface_not_placed` fires in the consumer's build, not only in the
    generator's.** A consumer script that pastes a fragment and then composes a
    *transformed* copy of the instance into `part.geometry` fails the build with
    `interface_not_placed` naming the tags, where today the worker would emit
    only a `tag_unresolved` warning (`worker.py:562-573`); a hand-authored
    non-`__` tag in the same position still produces the warning and a
    successful build, unchanged.
11. **File IO in the interface region is refused before publication.** A
    generator whose interface region calls a `DENIED_BUILTINS` name
    (`namespace.py:47-62`) is `interface_region_violation` **and**
    `interface_root_violation` at index time, and `heph registry publish`
    refuses that tree, since `validate_content` builds the index
    (`_publish.py:50-63`). Such a tree can therefore never be published or
    pinned, which is why the runtime-denial form of this clause lives at
    G11A clause 22 against the body region instead.
12. **The second build happens exactly when it must, and costs what is
    budgeted.** The placement-verification build runs iff `_placement` returns a
    non-empty expression: asserted by counting backend invocations for
    `pos=None`, `pos={}`, an all-zero `pos`, and a non-zero `pos`. Wall clock
    for the two-build path stays within a named budget on the pinned CI image,
    per rule 4 (`mission_plan.md` performance rule).
13. **Class verification, against the §2.3 table.** A record declaring
    `planar_face` for topology that builds as a cylindrical face is
    `interface_class_mismatch` naming declared and observed, decided on the
    worker-computed `geom_type` and not on the three-way `kind`. Each of the
    five table rows is verified **positively** at least once, `("solid",
    "OTHER")` included, so the `solid` row is proved to be an admitting row and
    not a fallthrough. Each of these is verified **negatively**: a face whose
    surface is a torus or a cone, classifying `("face", "OTHER")`, matches no
    row and is refused; a tag naming a wire and one naming a vertex are each
    refused, naming the observed `kind`. Fires at the default parameters, at a
    caller-supplied parameter set, and at a non-zero `pos`.
14. **`interface_placement_drift`.** A generator whose interface selector is
    pos-dependent (`sort_by(Axis.Z)[-1]` over faces of unequal area) instanced
    under a rotation that reorders them is refused, naming the interface and
    both scalars; the same generator at the origin, and a pos-invariant selector
    under the same rotation, are silent. The clause additionally asserts the
    documented limit: two faces of **equal** measure are not distinguished, so
    the rule is recorded as necessary-not-sufficient and the test names that
    case explicitly rather than leaving it as an unstated gap.
15. **The overwrite hazard.** Pasting the same component fragment twice into one
    script fails the build with `duplicate_tag` naming both tagging statements;
    two instances differing only by `instance` build cleanly and produce two
    disjoint tag sets. A hand-authored script re-tagging a non-`__` name still
    overwrites last-wins, byte-for-byte as today (`tags.py:58-59`).
16. **The 8C join, end to end** — the clause this sub-stage exists for, and the
    one the placement bug made unreachable. A user part instances a component
    **at a non-zero `pos`** (a motor seated on a pad is not at the part origin),
    composes it into `part.geometry`, and builds; an 8C `coincident` constraint
    anchored on `<part>:<instance>__mount_face` against a user-authored tag on
    the same part evaluates `satisfied`; editing the user part so the pad moves
    flips it to `violated` with the residual asserted to 1e-9; deleting the
    component instance from the script makes it `unresolvable` with reason
    `dangling_selector`, not `violated` (`assembly.py:141-143`, and the taxonomy
    at `:161-170`).
17. **Contract drift, `interfaces` half.** The `instance_store_part` result
    carries `interfaces` with the emitted prefixed names; the five generated
    artifacts regenerate identically with the field present; both profiles
    dispatch it. Together with G11A clause 15 this is the whole of Named new
    work item 29.
18. **The Stage 9 join.** A `revolute` joint anchored on a component's
    `__shaft_axis` resolves; the same joint anchored on a `planar_face`
    interface is refused for shape class, not silently framed
    (`KINEMATICS.md:80-85`).
19. **Cross-part form.** A component instanced as its own part file anchors
    cross-part through the same resolver, with no anchor-grammar change
    (`constraints.py:103`).
20. **Determinism.** Two processes produce fragments that are byte-identical
    below the elided digest header — including tag literals, their count and
    their order — and identical emitted-name lists in the tool result.
21. Existing suites stay green, `tests/stage8c` and `tests/stage9a` in
    particular, since both consume the resolver this sub-stage feeds.

### Gate G11C — provenance, federation, and the corpus

`uv run pytest tests/stage11c -q` exits 0, covering:

1. `instance_store_part` returns `mass` and `datasheet` verbatim as declared,
   and `claims` wrapped in provenance delimiters whose footer restates that it
   is reference material and not instructions.
2. A computed-mass homogeneous component's declared value agrees with the built
   envelope's `volume × density` to the declared tolerance; a seeded
   disagreement is refused rather than reconciled.
3. **The ledger path, end to end.** An operator registers a datasheet with
   `heph reference add`; the model records a `specified` requirement citing
   `{reference, page, quote}`; `heph lint` passes it; a `CHECKS` threshold
   citing that ledger id passes `unsourced_constant`. A citation of a page past
   the document's end is `invalid_requirement` with nothing written
   (`VALIDATION.md:126-129`).
4. **The component-claim citation.** A `cite` carrying `component` and `claim`
   round-trips through `record_requirements` / `read_requirements`; one carrying
   only one of the two is `incomplete_component_cite`; one naming a component id
   the project's registries do not carry, and one naming a claim id the
   component does not declare, are each `invalid_requirement` with nothing
   written; an existing citation carrying neither field is accepted and checked
   exactly as before.
5. `uncited_component_datum` fires on a `CHECKS` numeric literal equal to a
   component claim value with no ledger citation, and does not fire once the
   citation is added.
6. **`datasheet_digest_mismatch` fires on the declared join, positively.** A
   ledger entry whose `cite` names component claim `C` of component `K` and
   reference `R`, where `ReferenceEntry(R).sha256 != K.datasheet.sha256`
   (`references.py:158-166`), produces exactly one finding naming `K`, `C`, `R`
   and both digests. Re-registering `R` with bytes whose digest matches makes it
   silent.
7. **`datasheet_digest_mismatch` is silent absent a declared join** — the
   negative clause the earlier, digest-inferred formulation could not have had.
   A project carrying a component and an unrelated registered reference whose
   sha256 differs from that component's `datasheet.sha256`, with **no** ledger
   entry naming a component claim, produces **no** finding. A project carrying
   no references at all produces no finding. In both cases the component's
   `datasheet` audit-trail fields are still present in the
   `instance_store_part` result, unchanged.
8. A core-only install refuses a PDF reference registration with the named
   `capability_not_available` rather than degrading
   (`references.py:101-111`), and the component's pointer block is unaffected.
9. **Merged federation.** Two `parts` registries index together; a unique id
   resolves bare; a colliding id resolves under `<registry>/<id>` and is
   `ambiguous_component_id` when addressed bare — a refusal, never a precedence
   rule.
10. Both federated registries' digests appear in their own search results, so a
    component always names the tree it came from (`_parts.py:99-100`).
11. **Corpus, Tier 1.** At least two component-bearing mechanism tasks — a
    bearing-supported shaft with a declared `fit`, and a motor-mounted plate
    with a declared `coincident` and a bolt-circle `concentric`, both instanced
    at a non-zero `pos` — are graded through the engine path, and each task's
    reference solutions pass its own acceptance.
12. **Corpus, Tier 3, named not skipped.** The component family is its own
    split, baselined on its own first measurement with the reference model at
    ≥3 seeds, **neither compared against nor averaged into the v1/v2
    baselines**; the existing 0.70 prose bar keys on its own coverage and is not
    diluted. Re-baselining any combined bar is its own future amendment. The
    clause follows the G9C precedent verbatim (`KINEMATICS.md:392-398`).

    **Amendment, 2026-08-29 — the machinery, not only the rule (rule 1:
    tighten, never waive).** An independent verifier scored this clause
    *uncovered*: the only assertions behind it pinned the clause's own prose and
    one mechanical corollary, so the clause's subject had no evidence. The cause
    was not the missing bench run. It was that **no component split existed to
    measure.** `score_records` split runs by `VALIDATION.md` §1 spec alone, so a
    detached sweep over the whole corpus would have folded `bearing-shaft` and
    `motor-plate` into the very number compared against 0.70 — the dilution this
    clause forbids, arriving through the plumbing rather than through anyone's
    decision, and no test would have caught it. A clause whose subject the code
    cannot express is a spec defect, so the clause is tightened into three
    testable halves, all three gated here and none of them deferred:

    a. **The split is a first-class object.** `CORPUS_FAMILIES` is a closed
       family vocabulary whose single entry is `component`
       (`COMPONENT_FAMILY_TASKS`), and `split_name` is the one function that
       decides which split a run belongs to. Following the G9C precedent
       verbatim, a family is its own split **per spec** — `component-prose` and
       `component-seeded`, never averaged with each other either — which is a
       tightening of this clause's earlier singular "its own split": one split
       mixing prose and seeded runs would violate §1 while satisfying the
       sentence. A family split carries no threshold, ever.
    b. **Non-dilution is structural, not hoped for.** Family runs are carved out
       of *both* spec splits, so the gated prose number shares no run with the
       family and the 0.70 bar keeps covering exactly the corpus it was
       baselined over. A family split appears in the artifact only when it has
       runs, and **no key the family needs is written onto a split that does not
       need it**, so re-scoring an archive measured before this stage
       reproduces its stored artifact byte for byte. `tests/stage6`'s corpus-v1
       shape pin is repointed to the carved gated split, **citing this
       amendment**; it is strengthened in the same edit, not relaxed, by
       asserting where the carved-out runs went.

       *Second tightening, 2026-08-29, under rule 1.* As first written this
       paragraph claimed byte-identity and asserted it nowhere, and the claim
       was **false**: `SplitScore.to_json` emitted `min_seeds_per_task` on every
       split, so a pre-stage archive re-scored today differed from its stored
       artifact in exactly one key per split. A verifier demonstrated it on
       `bench/results/gpt-5.6-sol/2026-08-03` and
       `bench/results/gpt-5.6-sol/2026-08-13`. Two ways were
       open — weaken the sentence to "no split row is added and no gate-bearing
       number moves", or make the artifact genuinely stable — and rule 1 takes
       the second: the artifact is archived evidence (mission rule 2), so an
       amendment that rewrites a stored artifact on the next re-score has
       damaged the record even though no number moved. `min_seeds_per_task` is
       therefore serialised on family splits only, which is where its single
       reader — the ≥3-seed floor of (c) — looks; `heph bench score`'s table
       still prints it for every split, because a printed table is not
       evidence. Both halves are now asserted rather than claimed: byte
       identity against those two checked-in artifacts, and, over *every*
       archive in `bench/results`, that none grows a family row.

       **The byte half is EVIDENCE-BOUND, corrected 2026-08-30.** Several §8
       metrics — `build_failures`, `build_recoveries`,
       `clarification_refusals` — are derived from the PER-RUN directories
       beside `runs.jsonl`, and those are deliberately not committed: one file
       is tracked under `bench/results/gpt-5.6-sol/2026-08-03` against 74 on a
       machine that ran the sweep. Re-scoring without them returns zeros for
       exactly those fields, so the byte comparison holds only where the
       complete archive exists and CANNOT hold on a bare checkout. It passed
       locally and failed in CI for that reason alone (run 33274622760). The
       covering test therefore skips with that named reason when the per-run
       directories are absent, and a companion test pins that the skip can
       fire for no other cause — a conditional skip is a hole in a gate unless
       its condition is itself asserted. The clause's other half, and every
       other clause of 12, run everywhere. Three archives
       there had already drifted from their stored artifacts before this stage
       (one `--date`-named directory, two written by a scorer older than the §8
       metric block); this stage neither caused nor repairs that, and the
       byte-identity clause names its two clean witnesses rather than
       pretending to a fleet-wide claim.
    c. **The ≥3-seed floor is a named refusal.** `record_component_baseline`
       writes the family's first measurement and never re-baselines, exactly as
       `record_seeded_baseline` does — and because "first measurement" and
       "never re-baselined" together make a thin first run permanent, it refuses
       one below three distinct seeds per task by the name
       `insufficient_component_seeds`, writing nothing. `heph bench score`
       calls it and prints the refusal rather than swallowing it, so a family
       whose baseline was refused never looks like a family that was not run.

    **What remains deferred, stated plainly:** the live reference-model numbers.
    No pytest can produce them, and this repository fakes nothing — `bench/results`
    and `bench/archive` are untouched by this stage. The detached run now has a
    baseline file to write (`component_baseline.json`) and a shape it cannot get
    wrong, and the properties this clause exists to protect — its own split, its
    own first measurement, at ≥3 seeds, never averaged in — are enforced by code
    and asserted by `tests/stage11c`, not left to the operator's care.

    **The measurement, 2026-08-29: what its status is and who says so.** This
    clause has two halves with two different kinds of evidence, and conflating
    them is how "G11C: all clauses green" would mislead an operator. Said
    plainly:

    * **The machinery is Tier 1 and closed.** (a), (b) and (c) above are pytest
      assertions in `tests/stage11c`, run in CI by the `stage gates 11A-11C`
      job (`.github/workflows/ci.yml`) and required by `release.yml`'s
      prior-gate check, per mission rule 1.
    * **The number is Tier 3 and outstanding.** No `component_baseline.json`
      exists in this repository. Taking it is a detached run — `heph bench run`
      over `bearing-shaft` and `motor-plate` at ≥3 seeds with the epoch's
      reference model (mission rule 3), then `heph bench score` on the archive,
      which writes the baseline or refuses it by name — and it is **archived
      bench evidence, not a CI clause**, exactly as G9C's mechanism-split
      baseline is (`KINEMATICS.md:392-398`, and the `stage gates 9A-9C` job's
      own comment). A gate matrix reports this row as *machinery closed,
      measurement outstanding*, never as green.
    * **Nothing may report it as taken while it is not.** The absence is not
      left to a reader's care either: `heph bench score` prints
      `component family: NOT MEASURED` — naming both tasks and the file that
      would hold the answer — on every archive that measured no family task,
      and stops printing it once a baseline exists. Both directions are
      asserted in `tests/stage11c`, so the warning is a report on the world
      rather than a banner.
13. Corpus-count pins repointed with this stage cited.
14. **Determinism.** Two processes produce identical lint findings for clauses
    5, 6 and 7 and identical federated resolution for clause 9.
15. **The `LEGAL-REVIEW.md` schema check exists and has teeth.** A fixture
    carrying every required field passes; a fixture missing the field this stage
    adds — *third-party component data provenance and terms* — is refused,
    naming it; a fixture missing any one of the pre-existing fields is refused,
    naming it. **The count, corrected 2026-08-29 under rule 1.** This clause
    first read "all five scope fields (reviewer, date, and the four scope items
    plus …)", which enumerates six and was flagged as such by a verifier. The
    checker requires **six**: two identity fields (reviewer, date) and four
    scope statements, the fourth being the one Stage 11 adds. The "four scope
    fields"/"five" phrasing elsewhere is G7's own, inherited by §7.5 and the
    `mission_plan.md` block, and it is G7's sentence to correct; this clause
    stops repeating an arithmetic it cannot make true, and
    `scripts/legal_review_check.py` resolves the conflict the only way that
    drops nothing — every field either document names is required. The check is
    asserted against fixtures,
    not against the repository root, because `LEGAL-REVIEW.md` is a Stage 7
    deliverable that deliberately does not exist here (§7.5) — so this clause
    pins the checker, and Stage 7's own gate pins the signed file.
