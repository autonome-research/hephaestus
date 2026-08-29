<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# 17 — Structural analysis (Stage 15)

**Number.** 13 is the next free slot: `INTERFACE.md` is 12 and is the current
high-water mark (`architecture.md` 00, `script_contract.md` 01,
`tool_schema.md` 02, `verification.md` 03, `mission_plan.md` 04,
`repo_conventions.md` 05, `VALIDATION.md` 06, `INGEST.md` 07, `COMPARE.md`
08, `ASSEMBLY.md` 09, `EXTERNAL_EVAL.md` 10, `KINEMATICS.md` 11).

**Stage number.** 11, not 10. `KINEMATICS.md:50-51` forward-references FEA as
a "Stage 10 candidate"; two days later `mission_plan.md:700` claimed Stage 10
for "Workspace egress and provider attachment (amendment 2026-08-28,
maintainer-directed)". That forward reference is now stale prose and this
spec corrects it explicitly (see the amendment manifest) rather than
inheriting it.

**Status: DRAFT.** Not normative. This document is pending (a) a hostile
adversarial review against the codebase, on the `KINEMATICS.md` precedent —
that spec was revised after a 40-agent review folded in 31 confirmed findings
(`KINEMATICS.md:10-12`) — and (b) a `mission_plan.md` amendment opening Stage
11. Mission rule 5 (`mission_plan.md:815-817`) names FEA by name among the
deferred items that "enter only by amending this plan with a new gated
stage", so the amendment is the *authorized* mechanism, not an exception to
it. **This document does not itself amend `mission_plan.md`**; the staging
proposal is a separate file. Until both land, nothing here is binding and no
clause below may be cited as settled contract.

## Amendment manifest

Every normative document this spec changes, and exactly what changes. Each
amendment lands with the sub-stage whose machinery ships it — the
`KINEMATICS.md:25-29` rule that amending a doc before its machinery exists is
doc drift.

| Document | Change | Lands with |
| --- | --- | --- |
| `mission_plan.md` rule 5 (`:815-817`) | The deferred list loses **FEA**; Stage 15 is opened with the G15A/G15B/G15C summaries below, on the Stage 8 / Stage 9 / Stage 10 dated-amendment pattern. STEP import, community sharing and kerf-aware auto-nesting stay deferred, untouched. | 15A |
| `KINEMATICS.md` §0 (`:49-54`) | "Stage 10 candidate" → Stage 15, this spec. The rest of that bullet stands: Stage 9 has no dynamics, and per-part mass under a rigid transform is still pose-invariant. | 15A |
| `KINEMATICS.md` §7 (`:325-326`) | "No dynamics, loads, FEA, or motor sizing" is scoped to Stage 9, exactly as `ASSEMBLY.md` §4's "no kinematics" sentence was scoped to 8C (`KINEMATICS.md:20-22`). Dynamics and motor sizing remain out of scope everywhere (§9 below). | 15A |
| `registries/PUBLISHING.md` §1 kind table (`:38`) | The `materials` row's "one JSON record (numeric `density` required)" gains the **optional** `mechanical` block of §2. No new registry kind; the four kinds of `:25` are unchanged. | 15A |
| `architecture.md` §3.6 | The `materials` registry kind's content grows by the `mechanical` block. The kind set is unchanged. | 15A |
| `script_contract.md` §6 | The project-scope measurement facade gains one read surface, `m.load_case(id)` (§7). Part scripts declare no load cases, exactly as they declare no joints (`KINEMATICS.md:23-25`). | 15C |
| `tool_schema.md` "Deferred (schema reserved, not in mission scope)" (`:1487-1489`) | `run_fea(name, load_spec)` leaves the deferred section and is superseded by the §8 surface — the reserved name is *not* revived as spelled, because a `load_spec` inline argument contradicts the declared-state design of §3. The deferred section keeps `import_geometry(path)`. `contract/src/hephaestus/contract/tools_decl.py:84` `STAGE2_EXCLUDED_TOOLS` loses `run_fea` in the same change, and the `test_toolgen.py:98,109` / `tests/stage2/test_g2_contract_drift.py:354` tool-count pins are repointed with this stage cited. | 15C |
| `VALIDATION.md` §5 | The termination reviewer receives load-case status and every load-check result; `violated`, `not_converged`, `linear_range_exceeded` and `unresolvable` are blocking findings **by rule**, stamped from the engine, on the `ASSEMBLY.md` §3 / `KINEMATICS.md` §6 mechanism already written twice at `VALIDATION.md:311-334`. The reviewer additionally receives the §6 non-certification sentence verbatim. | 15C |
| `VALIDATION.md` §1 | Corpus v4 `stress-*` is its own split, baselined on its own first measurement, on the `VALIDATION.md` §1 split rule as G9C restated it (`KINEMATICS.md:394-398`). | 15C |
| `verification.md` Tier 1 "Kernel-service tests" (`:48-49`) | Gains the §10 analytic-benchmark suite alongside the existing hand-computable interference/clearance/distance/mass fixtures. | 15B |
| `verification.md` "Render determinism policy" (`:69-73`) | The pinned CI image now also pins the **mesher and solver**; a digest change that moves either is a solver re-baseline under the same golden-regeneration rule. | 15B |
| `verification.md` "Performance budgets (Tier 1)" (`:210-219`) | Gains the §5 solve budget. Budgets tighten, never loosen. | 15B |

**Explicit non-amendments**, stated because their absence would otherwise
read as an oversight: `COMPARE.md` §4's "no mesh-based comparison path" is
**not** lifted — an FEA mesh is a solver input, never a comparison operand
(§9). `ASSEMBLY.md` is unchanged — Stage 15 has no multi-part stress, because
that needs contact (§9). `INGEST.md` is unchanged. `INTERFACE.md` is
unchanged: `run_fea` is excluded from the workspace `TOOLS` set at
`INTERFACE.md:3296` and `:4347`, and whether the workspace carries the §8
surface is a Stage 10 product question this spec does not answer.

**Design premise.** `CHECKS` made a geometric assertion permanent: a
dimension that must hold is a predicate that re-runs on every build forever,
and a violation is named at publication rather than discovered by a human
reading a number. Every structural question a designer actually has —
"does this bracket survive 200 N at the tip?" — is today either unasked or
asked once, by hand, in a tool outside the harness, against a geometry that
then changes. Stage 15 makes *"max von Mises stress under load case L, over
the declared evaluation region, stays below the material's allowable divided
by the declared safety factor"* a machine-checked predicate on the same
ledger, with the same provenance, the same named refusals, and the same
blocking rule as a clearance constraint. The value is not the number; it is
that the number is re-derived, from named inputs, every time the geometry
moves.

## 0. What structural analysis is here, and what it is not

Structural analysis in Hephaestus is **a bounded, sandboxed, content-addressed
linear-elastostatic solve of one part under one declared load case, whose
scalar outputs feed a `CHECKS` predicate and the termination reviewer**. It
is a predicate machine, not a viewer.

It **is**:

- **Small-displacement, small-strain, isotropic linear elasticity, static.**
  One material model (`isotropic_linear_elastic`), one analysis type
  (`static`), one element family (second-order tetrahedra). Everything else
  is a named refusal, not a silent approximation.
- **Per part.** A load case names exactly one part. Assembly-level stress
  needs contact, which is out of scope (§9), so a load case naming two parts
  is refused `assembly_load_case_unsupported` at declaration.
- **Sampled in the mesh sense, exactly as motion is sampled in the
  configuration sense.** A finite-element result is an approximation on one
  discretization. `KINEMATICS.md:55-58` refuses to call a finite sample a
  continuous guarantee; this spec refuses, for the same reason, to call a
  single-mesh result a converged one. The verdict vocabulary of §6 says which
  it was, in the verdict's own name.

It is **not**:

- **A certification.** Nothing here says a part is safe. A success verdict
  says: *the declared idealization, meshed to the declared parameters, under
  the declared load case, with the declared material's declared allowable,
  met the declared margin over the declared evaluation region.* Every one of
  those adjectives is a recorded fact and every one of them can be wrong.
  `registries/dfm/registry.toml:11-12` already states the analogous limit for
  DFM ("advisory engineering limits, not a certification"); Stage 15 differs
  in that its results **block** (§8) — a load check that has never been
  evaluated is not a passing one — and that difference makes the
  non-certification sentence *more* load-bearing, not less, because a
  blocking green is exactly what a reader over-reads.
- **A tenth `hephaestus.geom` service.** This is the sharpest structural
  difference from Stage 9 and it is stated up front. `geom`'s contract
  (`core/src/hephaestus/geom/__init__.py:10-20`, enforced by
  `core/tests/test_geom_import_boundary.py:45-78`) is pure functions over
  shapes with no executor. Forward kinematics is a pure function, so
  `geom.kinematics` was legal. A mesh generation and a solve are *external
  binary subprocesses*, so they are executor work by construction and cannot
  live in `geom` under any refactoring. **Stage 15 adds no geom service** —
  the first capability stage since 8B that does not — and §9 says so again as
  a deliberate non-change.
- **A design tool the model drives interactively.** There is no "run a solve
  and look at it" loop. The model declares a load case; the engine evaluates
  it; the result is a fact with a verdict. `tool_schema.md:1489`'s reserved
  `run_fea(name, load_spec)` — an inline spec argument — is deliberately
  **not** the surface this spec ships (§8): an inline load spec is state that
  nothing records, and a result whose inputs are not on the ledger cannot be
  re-derived, which fails the mission's provenance rule outright.
- **Dynamics, plasticity, contact, thermal, buckling, or fatigue.** §9
  enumerates the exclusions and gives each one a named refusal rather than a
  silent success.

## 1. Units: one consistent system, stated once, because three are currently in the tree

Stage 15 cannot put a Young's modulus next to a density that three modules
disagree about. The disagreement is live and this section fixes it as a
precondition, not as a side effect.

**What is in the tree today:**

- `core/src/hephaestus/core/registry/_materials.py:75-79` refuses a materials
  record whose `density` is not a number, with the message
  `"'density' must be a number (kg/m^3)"`. All four records comply:
  `registries/materials/al-6061.json:4` is `2700.0`,
  `plywood-baltic-birch.json` `680.0`, `pla.json` `1240.0`, `petg.json`
  `1270.0`.
- `core/src/hephaestus/geom/measure.py:104-106` is `shape_volume(shape) *
  density`, documented at `:30-32` as "unit-agnostic; with mm³ volumes and
  density in **g/mm³** the result is grams".
- `core/src/hephaestus/core/checks/facade.py:85` sets
  `DEFAULT_DENSITY = 1.0`, consumed at `:518`, and the `m.mass` docstring at
  `:516` documents the fallback as "**1.0 g/cm³**" — a third unit, and not
  what the multiply computes.
- **No production caller binds a density at all.** The one production
  `part_measurement` call, `core/src/hephaestus/core/executor/worker.py:674`,
  passes `imports=` and nothing else. So `m.mass("part")` in every real
  `CHECKS` run today returns the part's volume in mm³ under the name "mass in
  grams".
- The only correct consumption of registry density in the tree is the BOM
  path, `server/src/hephaestus/agent_bridge/cad_ops/_doc.py:109-114`:
  `self.material.density * self.volume_mm3 * 1e-6`, commented
  "(kg/m^3 x mm^3 → g)".

**What Stage 15A fixes, normatively:**

- **The registry keeps kg/m³.** It is the published, human-checkable number
  (`al-6061.json`'s own `sources` field says "published 6061 density 2.70
  g/cm^3"). Changing it would break every record and every consumer for no
  gain. The registry is the *human* boundary.
- **The solver deck is written in the mm–N–MPa–t/mm³ consistent system**, the
  standard system for a mm-geometry structural deck: lengths mm, forces N,
  stresses and moduli MPa, mass density tonne/mm³. Conversion happens at
  exactly one named boundary, `DENSITY_KGM3_TO_TMM3 = 1e-12`, applied in the
  deck writer and nowhere else. The deck records the system it was written in
  as a literal string field so a reader never has to infer it.
- **`geom.measure.mass` is unchanged** — it is a pure unit-agnostic multiply
  and its docstring is already honest. What changes is that somebody finally
  passes it a real number: a second named boundary,
  `DENSITY_KGM3_TO_GMM3 = 1e-6`, converts a resolved materials record for the
  measurement facade, and the executor's `part_measurement` call binds it
  from the part's `material_spec`.
- **`DEFAULT_DENSITY = 1.0` becomes a named refusal.** `m.mass(selector)`
  with no explicit density and no resolved material raises
  `mass_density_unbound` (`kind="contract"`), naming the part and saying that
  a mass is not a volume. A silent 1.0 is precisely the guessed value the
  project's refusal discipline exists to prevent. Verified safe to tighten:
  `grep -rn "\.mass(" corpus/ --include=*.py` returns nothing, so no corpus
  acceptance check depends on the current behaviour; the audit is a named
  new-work item (§11) and a G15A clause, not an assumption.

Everything downstream — `pressure_mpa`, `youngs_modulus_mpa`,
`allowable_stress_mpa`, `force_n`, `max_displacement_mm` — is named with its
unit in the field name, on the `value_mm`/`min_mm`/`tol_mm` convention
`ASSEMBLY.md` §1 and `KINEMATICS.md` §4 already use.

## 2. Mechanical properties live in the materials registry, and most materials refuse

`registries/PUBLISHING.md:38` fixes the `materials` kind as "one JSON record
(numeric `density` required)", and `PUBLISHING.md:1-8` pins the whole tree by
a Merkle digest that `heph registry verify` re-checks
(`core/src/hephaestus/core/cli_registry.py:21`). That is already the
provenance machinery a modulus needs. **Stage 15 extends the existing
`materials` kind; it does not invent a second store and does not add a fifth
registry kind.**

A record gains an **optional** `mechanical` block:

```json
{
  "id": "al-6061",
  "density": 2700.0,
  "mechanical": {
    "model": "isotropic_linear_elastic",
    "youngs_modulus_mpa": 68900.0,
    "poissons_ratio": 0.33,
    "allowable_stress_mpa": 276.0,
    "allowable_basis": "yield",
    "failure_criterion": "von_mises",
    "temperature_c": 20.0,
    "source": "ASM 6061-T6 room-temperature typical: E 68.9 GPa, nu 0.33, 0.2% offset yield 276 MPa"
  }
}
```

- **Optional is deliberate.** `_materials.py:75-79` makes `density` the only
  required numeric field and all four shipped records predate this stage.
  Requiring `mechanical` would refuse every existing registry at load, which
  is a contract break for a capability most projects never use.
- **`model` is a closed set and only one value solves.**
  `isotropic_linear_elastic` is the Stage 15 value. `orthotropic` and
  `anisotropic_process_dependent` are *declarable* — a record may state that
  its material is orthotropic and carry no elastic constants — and both are
  refused at solve time by name, `material_model_unsupported`. A declared
  "we know this is orthotropic and this stage cannot analyse it" is
  categorically better evidence than a missing key, because it distinguishes
  *not yet characterised* from *characterised as out of scope*.
- **`allowable_basis` is a closed set** — `yield | ultimate |
  proportional_limit | design_allowable` — because "the allowable is 276" is
  meaningless without saying which 276. It is carried into the result record
  and into the reviewer context verbatim.
- **`failure_criterion` is a closed set** — `von_mises` (ductile metals) or
  `max_principal` (brittle). The criterion is a *material* property, not a
  check parameter, for the same reason `DfmFinding` takes severity from the
  rule declaration and never from the predicate
  (`core/src/hephaestus/core/dfm/types.py:143-146`, "so registry content
  cannot understate its own severity"): a check that could pick its own
  failure criterion could pick the flattering one.
- **`temperature_c` is required inside the block.** Properties are
  temperature-dependent and the tree already says so in prose:
  `registries/materials/pla.json` notes PLA is "Poor above roughly 50 C". A
  block without it is `material_temperature_unstated`. Stage 15 performs no
  temperature analysis (§9) — the field exists so that a number stated at
  20 °C is never silently reused as if it were universal.
- **`source` is required inside the block**, free text naming where the number
  came from. This is the `provenance` compulsion of `ASSEMBLY.md` §1 and
  `KINEMATICS.md:113-114` applied to registry content: an elastic modulus is
  an interpretation of a datasheet, and an uncited one is an assumption.
- **Coherence is checked at registry load, not at solve time**:
  `youngs_modulus_mpa > 0`, `-1.0 < poissons_ratio < 0.5`,
  `allowable_stress_mpa > 0`. Outside those, `material_property_incoherent`
  naming the field and the bound. ν ≥ 0.5 is incompressible and makes the
  standard displacement formulation singular; catching it at publish time is
  cheaper and more honest than catching it as a solver failure.

**What Stage 15 ships as registry content, and what it refuses:**

| Record | `mechanical.model` | Solvable in Stage 15 |
| --- | --- | --- |
| `al-6061` | `isotropic_linear_elastic` | **Yes** — wrought aluminium is near-isotropic and the one material whose isotropic constants are not a lie |
| `plywood-baltic-birch` | `orthotropic` (declared, no constants) | No — `material_model_unsupported` |
| `pla` | `anisotropic_process_dependent` (declared, no constants) | No — `material_model_unsupported` |
| `petg` | `anisotropic_process_dependent` (declared, no constants) | No — `material_model_unsupported` |

This is a deliberately narrow first landing and it has a consequence worth
naming before the gate does: **the corpus's sheet-goods and printed tasks
cannot be stress-checked in Stage 15.** A plywood panel is orthotropic — a
single E is wrong by a factor of roughly 20 between grain directions — and a
printed part is weaker at layer boundaries, which `registries/materials/
petg.json`'s own note gestures at in prose. Analysing either with an
isotropic modulus produces a plausible number that is not about the object.
The refusal is the feature.

`search_materials` (`schemas/tools/search_materials.schema.json:20-46`, and
`Material.to_json` at `_materials.py:43-54`) gains `mechanical` in its
result. `DfmRequest.material` (`core/src/hephaestus/core/dfm/runner.py:79`)
already carries the whole resolved record to predicates as `ctx.material`, so
DFM packs see the new block for free with no DFM change; none is required in
Stage 15.

## 3. Load cases are declared, generational project state

A load case is a statement about intent — what this part must survive — so it
belongs on the ledger with requirements, constraints, joints and poses, not in
a tool argument. It rides the pattern implemented four times over
(`project_store/constraints.py`, `project_store/kinematics.py`,
`references.py`, `checks/engine.py`): CAS-swap of an immutable
content-addressed generation under the project-config lock, provenance on
every entry, withdrawal is a new generation and erases nothing
(`core/src/hephaestus/core/project_store/kinematics.py:9-18`).
`KINEMATICS.md:326-329` leaves "four uses of it, or one namespaced store" an
unconstrained implementation choice; this spec adds a fifth use and does not
constrain it either.

```json
{"id": "lc-tip-load", "part": "bracket",
 "restraints": [{"anchor": "bracket:mount_face", "kind": "fixed"}],
 "loads": [{"anchor": "bracket:tip_pad", "kind": "force_n",
            "vector_n": [0.0, 0.0, -200.0]}],
 "safety_factor": 2.0,
 "evaluate_on": ["bracket:web", "bracket:tip_pad"],
 "mesh": {"target_size_mm": 2.0, "curvature_angle_deg": 20.0},
 "refinement": {"levels": 3, "ratio": 2.0},
 "pose": "p-closed",
 "provenance": {"requirement": "r-7"},
 "note": "worst-case hand load per spec table 4"}
```

- **Anchors are the 8C anchor grammar, exactly** — `part[:selector]` under
  `ANCHOR_PATTERN` (`core/src/hephaestus/core/project_store/constraints.py:
  102`), resolved through the shared `AnchorResolver` that Stage 9 reused
  verbatim rather than copying (`KINEMATICS.md:76-78`). No new addressing
  scheme. A slash-bearing anchor is `invalid_load_case`, for the
  two-grammars reason `constraints.py:95-98` records.
- **The `part` field and every anchor's part must agree.** Two parts is
  `assembly_load_case_unsupported` (§9) — a named refusal for a named
  exclusion, never a solve of one part with the other silently ignored.
- **Restraint kinds (closed set, Stage 15)**: `fixed` (all six DOF at the
  anchored face's nodes) and `normal_sliding` (the face may slide in its own
  plane; a roller). Each later kind is a contract amendment. The anchor must
  resolve to a planar or cylindrical *face*: a restraint on an edge or vertex
  produces an unbounded stress at the constraint by construction, so it is
  refused `restraint_anchor_wrong_class` rather than meshed and reported.
- **Load kinds (closed set, Stage 15)**: `force_n` (a total force vector in N,
  distributed over the anchored face's area — the deck writer divides by the
  measured face area and records that area as a fact), `pressure_mpa` (a
  scalar normal pressure on the anchored face, positive into the surface), and
  `gravity` (a body force from the part's resolved density and a declared
  acceleration vector in mm/s²). Loads bind to faces only, for the same
  singularity reason: `load_anchor_wrong_class`.
- **A load case with no load is refused, `no_load_declared`.** A zero-load
  solve reports zero stress and passes every margin trivially. This is the
  `VALIDATION.md:78-80` volume-window anti-pattern in its purest form — a
  check that cannot fail — and it must not be reachable by omission.
- **A load case whose restraints leave a rigid-body mode is refused,
  `underconstrained_load_case`, by a parent-side geometric test**: the
  restrained DOF of the declared restraint set, evaluated over the resolved
  restrained faces' node positions, must remove all six rigid-body modes
  (three translations, three rotations). This is checked **before** the deck
  is written, and it is deliberately independent of the solver's own
  singularity report — see §5 for why one detector is not enough.
- **`safety_factor` is declared on the entry, mandatory, > 1.0.** It is a
  requirement, not a predicate constant, so the engine — not a `CHECKS`
  predicate — computes the verdict against
  `allowable_stress_mpa / safety_factor`. This follows the DFM severity rule
  (`dfm/types.py:143-146`) rather than the `COMPARE.md:45-47` threshold rule,
  and the difference is deliberate: an IoU threshold is a task policy, but an
  allowable stress is registry-owned material data and a safety factor is a
  ledger-cited requirement, so neither is a predicate's to choose.
- **`evaluate_on` is a declared, mandatory, non-empty list of anchors** and it
  is the single most consequential field on the entry. See §4.
- **`mesh` and `refinement`** are recorded inputs, §5. **`refinement` is
  mandatory on the entry**, with `levels ∈ [1, 4]` and `levels != 2`, because
  the verdict vocabulary of §6 is a function of the ladder's length and a
  missing ladder would make the verdict a function of a default nobody
  declared. `levels == 1` is the honest single-mesh declaration and earns
  `holds_at_mesh`; `levels ∈ [3, 4]` is a convergence claim; `levels == 2` is
  refused `invalid_load_case` because a two-point sequence is monotone by
  construction and so cannot evidence convergence (§6). A missing `refinement`
  block is the same refusal.
- **`pose` is optional** and binds a `KINEMATICS.md` §3 named pose. Its only
  physical effect is on **world-fixed loads**: a rigid rotation of a part with
  its anchor-fixed loads rotated along with it produces an identical stress
  field, so for `force_n` and `pressure_mpa` a pose is provenance and nothing
  more. For `gravity`, which is world-fixed, the pose genuinely changes the
  answer. The spec states this rather than letting a reader assume a pose
  matters generally, and the result record carries
  `pose_affects_result: true|false` computed from the declared load kinds. A
  `pose` naming a withdrawn pose or a pose whose joints are unresolvable is
  `orphaned_load_case` at evaluation — a per-case unresolvable state on the
  `KINEMATICS.md:165-167` `orphaned_pose` precedent, not an erasure and not a
  failure of the pose set.
- **Provenance is mandatory**, same taxonomy as 8C and 9A: cite a ledger
  requirement or be `assumed` with a reason. A load magnitude is an
  interpretation of intent, and an uncited 200 N is the most consequential
  assumption in the whole document.

**Staleness** follows the `AssemblyProjection` / `MotionProjection` precedent
exactly: a new named `loads` field on `ProjectionState`
(`core/src/hephaestus/core/project_store/projections.py:319-347`, which
already carries `assembly: AssemblyProjection | None` and
`motion: MotionProjection | None` with the same "None before the first
evaluation — an unevaluated set is not a passing one" comment), with its
`to_json`/`from_json` extension, restaled when the part's current artifact
ref changes, when the load-case set generation advances, when the pinned
registry digest changes (a modulus is an input), or when the bound pose's
motion generation advances. GC-linked so a stale status stays readable rather
than reading as never-evaluated.

## 4. The evaluation region, and the singularity problem

This is the section a structural engineer will read first, and it is where
this spec most differs from a naive "report the peak von Mises" design.

**Peak stress in a linear-elastic solid is not always a finite number.** At a
re-entrant corner with zero fillet radius, and at the boundary of a `fixed`
restraint, the exact elasticity solution is singular: the stress goes to
infinity as the radius goes to zero. A finite-element mesh does not report
infinity; it reports a finite number that **increases without bound as the
mesh is refined**. A convergence study over such a point therefore does not
converge, and a single-mesh peak taken there is not an approximation of
anything — it is an artifact of the element size. Reporting it as "max von
Mises" would be the single most seductive lie this capability could tell.

Stage 15 handles it in three declared, machine-checkable moves:

1. **The peak is taken over a declared region, never globally.**
   `evaluate_on` is mandatory and non-empty. The reported
   `max_von_mises_mpa` is the maximum over nodes belonging to the resolved
   anchors' faces and the solid volume they bound. There is no global-peak
   field on the record, because there is no global peak worth reporting.
2. **Restraint boundaries are excluded by name and by measurement.** Nodes
   within `SINGULARITY_EXCLUSION_MM = 1.0` of any restrained node are removed
   from the peak search, and the count of excluded nodes and the **effective**
   exclusion radius are recorded facts on the result *and members of the result
   record's hashed inputs* — a number that moves the verdict may not sit
   outside the provenance chain. A default of 1.0 mm is not physics; it is a
   declared convention, and the record says so by carrying the number.

   **The env override is a one-directional floor, and this is a deliberate
   departure from the timeout precedent.** `COMPARE_TIMEOUT_ENV` and
   `MOTION_TIMEOUT_ENV` (`core/src/hephaestus/core/project_compare.py:84-85`,
   `core/src/hephaestus/core/motion.py:1436-1437`) accept any value in either
   direction, which is harmless for a *ceiling on how long we will wait*: a
   wall clock does not move an answer. An exclusion radius does. A larger
   radius removes more nodes from the peak search, lowers `max_von_mises_mpa`,
   and can turn a `violated` into a `holds_at_converged_mesh` — so the same
   load case, geometry, registry digest and image digest could yield opposite
   verdicts on two machines. Therefore
   `HEPHAESTUS_FEA_SINGULARITY_EXCLUSION_MM` **honours a value at or below
   `SINGULARITY_EXCLUSION_MM` and refuses a value above it by name,
   `exclusion_radius_loosened`**, naming the requested value and the default.
   This is the `verification.md:218` "budgets tighten, never loosen" rule
   applied to an accuracy convention, and it matches the sentence this bullet
   already carried; the sentence was previously contradicted by the mechanism
   it cited, and the mechanism is what changed. Every **[image]** gate clause
   runs with the variable unset, and G15B asserts both halves.
3. **A zero-radius re-entrant edge inside the evaluation region is a
   refusal, not a number.** `stress_singularity_in_region`, detected from the
   BRep before any mesh is built: a concave edge inside the declared region
   whose adjoining faces meet at an interior angle below
   `REENTRANT_ANGLE_DEG = 170.0` and which carries no fillet. The refusal
   names the topology descriptor (the `DfmFinding.topology` shape at
   `core/src/hephaestus/core/dfm/types.py:41-56`: `{kind, solid_id,
   topology_index, tag?}`) and states the two fixes: fillet the edge, or move
   the evaluation region off it. It is a refusal rather than a warning
   because the alternative is a mesh-dependent number that a convergence
   study will happily report as *diverging*, and `not_converged` would then
   blame the mesh for a geometry decision.

Additionally: if the peak node after exclusion still lies on the boundary of
the excluded set, the result carries `peak_in_excluded_region` as its
`reason` and the verdict is `unresolvable`. The number exists but it is
about the restraint, not the part.

## 5. Meshing and solving: pinned binaries, content-addressed in and out

### 5.1 The toolchain is two external binaries, and neither exists today

`grep -rn "FEA\|finite element" ` over source returns only deferral prose. No
mesher, no solver, no element library is in this tree. OCCT ships a **surface**
mesher only — `BRepMesh_IncrementalMesh`, wrapped at
`core/src/hephaestus/core/render/tessellate.py:34` for rendering — and
`import OCP; [m for m in dir(OCP) if "Mesh" in m]` yields
`BRepMesh, IMeshData, IMeshTools, MeshVS, RWMesh, XBRepMesh`, all surface
meshing, mesh visualisation, or mesh IO. There is no tetrahedral mesher in
the kernel and no volume mesher in `uv.lock`.

Stage 15 pins two:

- **Gmsh** as the volume mesher. It reads BRep/STEP through its own OCC
  kernel and emits an Abaqus-format `.inp` with physical groups, which is
  what carries the face→boundary-condition mapping. `[external knowledge;
  not verified in-repo — no mesher exists here]`
- **CalculiX (`ccx`)** as the solver. GPL, one static binary, ASCII `.inp` in
  and ASCII `.dat`/`.frd` out. ASCII output is what makes a byte-level
  determinism clause feasible at all. `tool_schema.md:1489`'s reserved slot
  already names CalculiX, so this is the toolchain the plan anticipated.
  `[external knowledge]`

Both are pinned in `docker/ci/Dockerfile` as `apt-get install` lines with
exact versions, in the same block as `bubblewrap` and the Mesa packages
(`docker/ci/Dockerfile:15-23`), and the image is consumed **by digest**
(`docker/ci/Dockerfile:1-8`). A runner-side install would violate the
renderer-pin discipline the image exists to enforce and mission rule 7's
pinned-dependency rule (`mission_plan.md:824-828`). The **image digest is now
part of every FEA result's provenance**, exactly as it is part of a render
golden's.

**Why an external solver rather than an in-tree one.** `scipy` 1.18.0 is
already a runtime transitive dependency (`uv.lock:132-133`, pulled by
build123d/pyrender/ocp-gordon/svgpathtools), so `scipy.sparse.linalg` is
available with no new pin and a small in-tree linear FEM would make rule 7
trivial and rule 6 a non-issue. It is rejected because it inverts the trust
problem: we would then own the element library, the shape functions, the
integration rule and the assembly, and §10's analytic suite would be
verifying our own arithmetic against our own reading of the same textbook.
An independently-written solver that we verify against closed-form solutions
we did not write is a genuinely independent oracle. The cost — two pinned
binaries and a determinism policy — is the price of that independence, and it
is stated here rather than discovered at review.

**Rule 6 boundary statement** (`mission_plan.md:818-822`, "Python core owns
geometry"): a mesher consumes geometry and produces a discretization; it does
not author, modify, or become a source of geometric truth. No mesh is ever a
build artifact, a boolean operand, an export, or a comparison target — the
mesh exists only as an input to one solve and is addressed only by hash. The
authored script remains the sole source of geometry. A solver is not a
geometry implementation at all.

### 5.2 The mesh is a recorded input, and its determinism must be established

A result without its mesh is not evidence. The `MeshSpec` is part of the load
case (§3) and part of the hash:

```json
{"element": "c3d10", "target_size_mm": 2.0, "min_size_mm": 0.5,
 "curvature_angle_deg": 20.0, "order": 2}
```

- `element` is a closed set with one Stage 15 value, `c3d10` — second-order
  (10-node) tetrahedra. First-order tets are excluded deliberately: they are
  overly stiff in bending and would fail §10's cantilever case for reasons
  that have nothing to do with the integration being correct. `order: 2` is
  redundant with `element` and is recorded anyway, because a reader of the
  archived record should not have to know the Abaqus element vocabulary.
- Every field, plus the mesher version string and the CI image digest, is
  hashed into the mesh artifact's inputs. The mesh is published as
  `artifact:mesh:sha256:<hex>` under the existing content-addressing scheme
  (`core/src/hephaestus/core/project_store/store.py:64-66`,
  `artifact_ref(kind, blob_hash)`), and recorded in `tp_artifact_kinds`
  (`project_store/artifact_kinds.py`) like every other published kind, so a
  ref whose label says `mesh` cannot serve a build's bytes.
- **Mesh quality is a reported fact with a declared metric and a declared
  floor.** The record carries node count, element count, and the worst
  element's quality under **one named metric**:
  `MESH_QUALITY_METRIC = "scaled_jacobian"`, the ratio of the minimum to the
  maximum Jacobian determinant over an element's nodes, normalized so that a
  perfectly-shaped element is 1.0 and an inverted or degenerate one is ≤ 0.
  `MESH_QUALITY_FLOOR = 0.2`, and the comparison is `worst < floor ⇒ refuse`.
  A mesh whose worst element falls below the floor is refused
  `mesh_quality_below_floor`, naming the element, the metric, the value, and
  the floor — a solve on degenerate elements produces numbers, and numbers
  from degenerate elements are the second-most seductive lie available here.
  **Naming the metric is not pedantry**: aspect ratio, minimum dihedral angle,
  radius ratio and scaled Jacobian disagree about which tetrahedra are bad,
  they do not even share a direction of goodness, and a floor without a metric
  leaves the implementer to choose which meshes get refused. That choice is a
  verdict-determining choice, so the spec makes it rather than delegating it,
  and G15B.13 asserts the named metric's value rather than "its metric".
- **Problem size is capped, and the cap is derived from the ceiling rather
  than declared beside it.** The two numbers are not independent: a cap that
  admits meshes the declared `FEA_RLIMITS` (§5.3) cannot solve simply moves
  the failure from a cheap named refusal to the expensive unnamed one the cap
  exists to prevent, which would make the "cheap, deterministic, actionable"
  claim below false at exactly the sizes it matters. So:

  > `FEA_NODES_MAX` is **defined** as the largest `c3d10` node count at which
  > the §10 case-2 reference solve completes inside the pinned image under
  > `FEA_RLIMITS` with a 20 % headroom margin on both `cpu_seconds` and
  > `address_space_bytes`, measured once in 15B, recorded as the constant's
  > docstring with the measuring image digest, and re-measured whenever the
  > image digest moves.

  `250_000` is carried here as a **stated upper bound, not a justification**:
  the effective constant is `min(250_000, measured)`. Its provenance is that
  it is a round number below which no corpus part is expected to fall, and
  under mission rule 1 (`mission_plan.md:800-803`) a constant with no stated
  basis is exactly the ambiguity that must be resolved by tightening — hence
  the measurement is named new work (§11) and gated (G15B), not left to the
  implementer. A mesh exceeding the cap is `mesh_too_large`, naming the
  computed node count and the cap. This is the `SWEEP_SAMPLES_MAX` discipline
  (`KINEMATICS.md:217-221`: cap the computed total, name the total in the
  refusal) applied to the analogous unbounded axis. Refusing at mesh time is
  strictly better than timing out at solve time — cheap, deterministic, and
  actionable — **and that claim is only true because the cap is derived from
  the ceiling**, which is why G15B asserts that a mesh at exactly
  `FEA_NODES_MAX` solves to completion under `FEA_RLIMITS` inside the image.
- **Exhausting the address-space limit is its own named refusal.** A solve
  killed by `RLIMIT_AS` is `solve_out_of_memory`, carrying the recorded
  `address_space_bytes` and the mesh's node count — never `solve_failed` and
  never `fea_timeout`. The three call for different fixes (coarsen the mesh;
  fix the deck; raise the wall clock) and collapsing them would hide the one
  failure the cap derivation above is meant to make impossible.

**Determinism is NOT inherited from the tessellator.**
`render/tessellate.py:16-19` asserts byte-identical tessellation across
processes and backs it with render goldens; that contract covers OCCT's
surface mesher and nothing else. Volume meshers commonly use randomized point
insertion or hash-ordered work queues `[external knowledge]`. Stage 15
therefore **establishes** mesh determinism by measurement rather than
assuming it: G15B.7 is a two-process byte comparison of the mesh file inside
the pinned image, and the mitigations are declared in advance — the mesher
runs single-threaded with an explicitly pinned algorithm and random seed, and
the pinned settings are recorded on the artifact. If byte-determinism cannot
be achieved with those settings pinned, **that is a stage-blocking finding**,
not something to be papered over with a tolerance: the mesh is an input, and
an input that varies is not content-addressable, which collapses the whole
provenance chain. Mission rule 1 (`mission_plan.md:800-803`: "Ambiguity in a
gate is a defect in this document and MUST be resolved by tightening the
gate, never by waiving it") applies directly.

### 5.3 The solve runs under the existing sandbox, with four additions

The sandbox already permits an arbitrary argv:
`SandboxSpec.worker_cmd` is `tuple[str, ...]`
(`core/src/hephaestus/core/executor/sandbox/base.py:54`) and tests already
run a non-Python binary (`core/tests/test_executor_failure.py:191`,
`tests/stage0b/test_sandbox_denial.py:119`, both `worker_cmd=("true",)`).
Three facts make an external solver a genuinely low-friction fit, and one
makes it a problem.

Favourable, all verified:

- **`/usr` is already read-only bound on every run**
  (`core/src/hephaestus/core/executor/sandbox/bwrap.py:102`, plus the host's
  top-level merged-usr entries at `:95-110` so any dynamically linked ELF's
  `PT_INTERP` resolves), and `PATH` inside the sandbox is `/usr/bin:/bin`
  (`bwrap.py:60-66`). A distro-packaged `/usr/bin/ccx` and `/usr/bin/gmsh` are
  therefore **already reachable with no new bind**.
- **Network isolation is unconditional and structural.** `--unshare-net` at
  `bwrap.py:269`, alongside `--unshare-user/ipc/uts/pid`, `--clearenv`,
  `--die-with-parent`, and `--remount-ro /` at `:262-300`. "The solver is
  networkless" is not a property to be verified of the solver; it is enforced
  by the harness, and a solver that tried to phone home would simply fail.
- **One writable directory** — the fresh per-build out dir, which is also the
  chdir (`bwrap.py:290-296`), with `/tmp` a tmpfs and `HOME=/tmp`
  (`bwrap.py:60-66`, `:278-284`). CalculiX writes its scratch beside its
  input, which is exactly this shape. `[external knowledge]`
- **Fail-closed**: no bwrap ⇒ `SandboxDeniedError("sandbox_unavailable: ...
  secure execution fails closed")` (`bwrap.py:348-352`).

And one more thing is favourable only by accident and must be fixed: the out
dir is bound **at its host path** — `--bind <out_dir> <out_dir>`, `--chdir
<out_dir>` (`bwrap.py:290-296`) — so the interior working directory is
run-unique. For a Python worker whose output is a JSON record that never
mentions its cwd, that is invisible. For a solver that stamps its input path
into its own output header, it is a determinism bug (addition 2 below).

The four additions Stage 15 makes:

1. **`SandboxSpec` gains `extra_env: tuple[tuple[str, str], ...] = ()`**,
   applied after `SANDBOX_ENV` in `build_bwrap_argv`. The FEA spec sets
   `OMP_NUM_THREADS=1`. This matters more than it looks:
   `SANDBOX_ENV` (`bwrap.py:60-66`) sets only PATH/HOME/TMPDIR/LANG/
   PYTHONDONTWRITEBYTECODE, so a threaded solver under `--clearenv` picks its
   thread count from the visible CPU count, and multithreaded assembly and
   factorization reorder floating-point summation. **This is the
   highest-probability determinism failure in the whole design**, the fix is
   one environment entry, and it is specified and gated
   (G15B.8) rather than assumed. `extra_env` rather than a global
   `SANDBOX_ENV` change because pinning `OMP_NUM_THREADS` globally would
   change OpenBLAS behaviour under every existing worker for reasons
   unrelated to this stage.
2. **The FEA scratch dir is bound at a fixed interior path.** The FEA spec
   binds its per-run scratch dir as `--bind <scratch> /work` with
   `--chdir /work`, so no run-unique byte sequence can reach any tool's
   output, and the worker passes only `/work`-relative paths to `gmsh` and
   `ccx`. Without this, the mesher's and solver's own output headers echo a
   path that differs on every run `[external knowledge]`, and the byte-level
   determinism clauses of §5.4 are unsatisfiable by construction — not
   because the solver is nondeterministic, but because we handed it a
   nondeterministic input. This is additive and FEA-only: `build_bwrap_argv`
   gains an optional interior mount point for the writable bind and every
   existing worker keeps the host-path shape at `bwrap.py:290-296`, because
   changing it globally would move every existing golden for reasons
   unrelated to this stage. G15B asserts that the scratch dir's host path
   appears as a byte sequence in **no** published FEA artifact — mesh, deck,
   raw output, or result.
3. **FEA declares its own ceilings — and only its own ceilings.**
   `executor/runner.py:57-62` sets `DEFAULT_RLIMITS = Rlimits(cpu_seconds=120,
   address_space_bytes=6 GiB, nproc=4096)` and
   `DEFAULT_WALL_CLOCK_S = 300.0`; a sparse factorization of even a modest tet
   mesh routinely exceeds 120 s CPU `[external knowledge]`. Stage 15 declares
   `FEA_RLIMITS = Rlimits(cpu_seconds=600, address_space_bytes=8 * 1024**3,
   nproc=4096)` and `FEA_WALL_CLOCK_S = 900.0`, env-overridable via
   `HEPHAESTUS_FEA_TIMEOUT_S`. **The limits a result was produced under are
   recorded on the result**, because a solve that succeeds under 8 GiB on one
   machine and is killed on another produces different evidence, not just
   different timing.

   **`nproc` is 4096 and is not Stage 15's to lower.** `RLIMIT_NPROC` is not
   a per-sandbox process budget: it is a per-real-UID (per-userns ucount)
   limit charged against *every task the invoking user already has*, so
   lowering it to a number that sounds like "enough threads for a solver"
   fails `bwrap`'s userns clone with `EAGAIN` before the solver is reached.
   This tree has already paid for that lesson and wrote it down twice —
   `executor/runner.py:54-56` ("nproc must exceed the invoking user's live
   kernel task ucount or bwrap's userns clone fails EAGAIN … 4096 is the
   standard fork-bomb cap that clears real desktop task counts") and
   `sandbox/probe.py:63-66`, which pins the *probe's* rlimits at 4096 for the
   same reason. A Stage 15 that shipped `nproc=64` would make every sandboxed
   FEA run fail to start on any ordinary developer desktop, and would do it
   by walking back into a recorded fix. The two ceilings a solve actually
   needs are CPU time and address space; those are what this stage raises.
   Any future tightening of `nproc` must state a **measured** floor against a
   realistic live task count and gate it, never a guess — G15B carries the
   clause that keeps it honest.

   **The DFM precedent, cited correctly.** `dfm/runner.py:53-54`
   (`DEFAULT_DFM_WALL_CLOCK_S = 120.0`) is a **wall-clock-only** precedent:
   the DFM path declares its own *timeout* and then explicitly does not touch
   rlimits, taking `rlimits: Rlimits = DEFAULT_RLIMITS` as its signature
   default at `dfm/runner.py:125`. That default is a recorded decision, not
   an omission. So the precedent supports `FEA_WALL_CLOCK_S`; for the rlimits
   themselves it counsels the opposite of a bespoke tuple, and Stage 15
   departs from `DEFAULT_RLIMITS` in exactly two fields, each with a stated
   reason, and inherits the third.
4. **FEA refuses the unsafe backend unconditionally**, `fea_requires_sandbox`.
   `sandbox/unsafe.py:57-71` refuses jobs carrying `origin: "registry"`, and
   `dfm/runner.py:106` stamps exactly that on every rule-pack job so registry
   predicates can never run unsandboxed. An FEA deck is harness-generated,
   not registry content, so the existing origin rule would not catch it —
   yet executing a third-party native binary is a *stronger* reason to
   require confinement than executing a Python predicate. Stage 15 therefore
   adds a job-level refusal that does not route through `origin` at all.

**Execution shape.** `worker_cmd` stays `(sys.executable, "-m",
"hephaestus.core.fea.worker")` — the one-JSON-in/one-JSON-out protocol
(`sandbox/base.py:1-14`) is preserved and the worker `subprocess`-execs
`/usr/bin/gmsh` and `/usr/bin/ccx` *inside* the sandbox. The alternative —
making the solver the `worker_cmd` directly — would need a second result
framing, a second escape-suite, and would put deck writing and result parsing
outside the confinement. The parent-side runner is
`dfm/runner.py:119-186`'s shape with a different worker: stage inputs into a
fresh scratch out dir, one sandboxed run, `shutil.rmtree` in `finally`
(`:185-186`), `timed_out` ⇒ named refusal (`:174-178`), nonzero exit ⇒ named
refusal carrying the last 2000 bytes of stderr (`:180-184`), stdout parsed
into a typed record.

**Solver absence is a capability refusal, not a crash.** `solver_unavailable`
when `ccx` or `gmsh` is not on the sandbox `PATH`, on the
`capability_not_available` pattern `dfm/runner.py:11-17` records. Local
developers without the pinned image get a named refusal, and the CI gate runs
inside the image where both exist.

### 5.4 Determinism: what is claimed, and what is not

Stated plainly, because overclaiming here would be worse than claiming
nothing. `bwrap.py:16-17` already sets the precedent of recording such a
decision honestly ("no `PYTHONHASHSEED` override: determinism relies on the
default hash randomization being irrelevant to geometry").

**Bit-reproducible, and gated as such:**

- **The mesh file**, for identical (BRep bytes, `MeshSpec`, mesher version,
  image digest), across two processes — G15B.7.
- **The solver deck** (`.inp`), for identical (mesh, load case generation,
  material record, registry digest, unit system), across two processes —
  G15B.9. The deck is generated by us, in ASCII, with sorted node/element
  emission; there is no excuse for it to vary.
- **The parsed result record with `raw_ref` excluded**, across two processes
  **inside the pinned CI image on the same host** — G15B.10. The exclusion is
  named rather than assumed: `raw_ref` is the sha256 of bytes we do not
  author, and the paragraph on hash hygiene below explains why a clause
  asserting exact equality *including* it would be asserting a property this
  spec elsewhere says may not hold. Every other field of the record —
  including every number a verdict is computed from — is inside the equality.
- **The volatile region of the raw solver output is identified, not
  assumed away** — G15B.10a. The worker records, on the result, the byte
  ranges of the raw output it treats as volatile (the header lines carrying
  paths, dates, and version banners), plus `raw_canonical_sha256`: a digest
  over a **declared, recorded normalization** — the byte ranges blanked, the
  normalization's own version string included in what is hashed. Two
  processes must agree on `raw_canonical_sha256` exactly. This is the clause
  that turns "the raw bytes may vary" from an excuse into a measurement: if
  the volatile set is empty after addition 2 of §5.3, the gate proves it; if
  it is not, the gate names exactly which bytes and the record carries the
  ranges for a reader to check. What is **not** done is editing the published
  bytes.

**NOT claimed, and not gated:**

- **Bit-identity of solver output across machines or toolchains.** Sparse
  direct solvers use fill-reducing permutations that may tie-break on pointer
  or hash order, and `libgfortran`/BLAS may dispatch on CPU features
  (AVX-512 vs AVX2), changing FMA contraction `[external knowledge]`. The
  pinned image fixes the software but not the CPU. **The honest claim is:
  bit-reproducible within a pinned toolchain on one host; reproducible to a
  stated tolerance otherwise.** No gate asserts the cross-machine half,
  because CI cannot run cross-machine, and asserting an untested property is
  the failure mode this document exists to avoid. The cross-machine tolerance
  `SOLVE_AGREEMENT_REL = 1e-6` is declared for operators comparing results by
  hand and is explicitly **not** a gate clause.
- **Convergence-iteration counts under an iterative solver.** Stage 15 uses a
  direct sparse factorization (CalculiX's default SPOOLES path) precisely
  because an iterative solver's iterate count moves with any floating-point
  difference `[external knowledge]`. If an iterative path is ever adopted,
  the converged tolerance and iteration count both become reported facts and
  this section becomes an amendment.

**Hash hygiene, and the contradiction it would otherwise create.** Solver
output headers commonly echo input paths and timestamps
`[external knowledge]`. The **raw solver output is published as-is** as
`artifact:fea-raw:sha256:<hex>` — it is the primary evidence and must not be
edited. Three moves keep that compatible with a byte-level determinism gate
instead of contradicting it:

1. **Remove the run-unique input.** §5.3 addition 2 binds the scratch dir at
   the fixed interior path `/work`, so the largest source of header variance
   — the path — is gone by construction rather than tolerated. G15B asserts
   the host path appears in no published artifact.
2. **Name what is left.** Timestamps and version banners survive move 1.
   They are not edited out of the published bytes; they are *identified* by
   recorded byte range and excluded from `raw_canonical_sha256`, which is the
   digest the determinism clause tests.
3. **Keep `raw_ref` out of the exact-equality clause.** `raw_ref` is the
   sha256 of the unedited bytes, so it inherits whatever variance move 2
   names. It stays on the record as provenance and is compared through
   `raw_canonical_sha256` rather than through equality of the record.

**The verdict is computed from the parsed record**, never from the raw bytes,
and it is the parsed record whose determinism is gated.

**Which refs live where.** The **result record** names four artifact refs —
`mesh_ref`, `deck_ref`, `raw_ref`, and the source build artifact — plus the
registry digest and the image digest. `result_ref` is **not** a field of the
hashed record, because a content-addressed record cannot contain its own
hash; it is the ref assigned when that record is published, and it lives on
the `LoadProjection` entry that points at the record (and, from there, on
`LoadCaseFacts`, §7). So the chain from verdict back to authored geometry
runs through five hashes and every link is one: the projection entry names
`result_ref`, the record names the other four. A result that cannot name the
artifacts it came from is not evidence.

## 6. Convergence honesty, and the verdict vocabulary

**A single-mesh result is not a converged result.** A displacement-based
finite-element solution converges to the exact solution from below in
stiffness — a coarse mesh is too stiff, under-predicts displacement, and
generally under-predicts peak stress `[external knowledge]`. So a coarse mesh
that *passes* a margin is the least trustworthy possible evidence, and a
vocabulary that spells that pass the same as a converged one would invert the
reader's confidence exactly where it matters.

The verdict set is closed and stated once:

| Verdict | Meaning |
| --- | --- |
| `holds_at_mesh` | The margin held on a single declared mesh. **Never "holds".** Weakest success state: mesh-dependent, and the direction of the discretization error is the flattering one. Emitted only when `refinement.levels == 1`. |
| `holds_at_converged_mesh` | The margin held **and** a ladder of at least `REFINEMENT_LEVELS_MIN = 3` levels met the §6 convergence criterion. Unreachable from a shorter ladder, by construction and by gate. Still not "holds": the idealization, the load case, and the allowable can all be wrong, and none of them is what convergence tests. |
| `violated` | At the finest evaluated mesh, the peak over the evaluation region exceeded `allowable_stress_mpa / safety_factor`. |
| `not_converged` | The refinement ladder did not meet the criterion. **The margin question was not answered** — not a pass, not a `violated`. Carries every level's node count and peak. |
| `unresolvable` | Never evaluated: a named reason from the §8 taxonomy (missing properties, unsupported model, unmeshable geometry, unresolvable anchor, orphaned pose, solver unavailable, peak in excluded region). |

The naming rule is `KINEMATICS.md:201-211`'s, applied to a different sampling
axis: a universal claim over a discretization gets a verdict whose name
carries the qualifier, because all-good samples evidence but do not prove.
`holds_at_mesh` is to a mesh what `holds_at_samples` is to a sweep.

**The convergence criterion** (`refinement: {levels, ratio}`): each level
divides `target_size_mm` by `ratio`; the ladder runs coarse-to-fine; the
tracked scalar is the peak over the evaluation region. The criterion is met
when the sequence is **monotone** and the relative change between the two
finest levels is at most `CONVERGENCE_BAND_REL = 0.05`.

**Three points minimum, and the reason is that two points cannot fail.**
`REFINEMENT_LEVELS_MIN = 3` for any `holds_at_converged_mesh`. Monotonicity
is a statement about a *trend*, and it is undefined for fewer than three
points: every two-element sequence is monotone, so on a two-level ladder the
monotonicity half of the criterion is vacuous, and the band half compares the
finest mesh against the declared coarse one — the mesh this section opens by
calling the least trustworthy evidence available. A two-level ladder can
therefore satisfy the letter of the criterion while evidencing nothing, and
reporting that under a verdict whose name asserts convergence is precisely
the overclaim the `holds_at_samples` rule this spec inherits exists to
prevent. So `levels == 2` and a missing `refinement` block are both
`invalid_load_case` at declaration (§3), refused rather than silently
promoted or silently demoted — a demotion to `holds_at_mesh` would let a
reader believe a ladder was run and discarded, which is a different lie.
`levels` is bounded by `REFINEMENT_LEVELS_MAX = 4` above, so the admissible
set is exactly `{1, 3, 4}`.

The *total* node count across the ladder is capped by `FEA_NODES_MAX` per
level, refused by name before any solve. The band tightens by amendment and
never loosens (`verification.md:218`'s rule for performance budgets, applied
to an accuracy budget for the same reason). Every level's
`(target_size_mm, nodes, elements, peak_mpa, relative_delta)` is a recorded
fact, and for a ladder of three or more levels the **observed convergence
order** computed from the last three peaks is recorded alongside them — this
section claimed a reader could compute one, and a claimed-computable number
that nothing computes is a claim nobody checks. A `not_converged` result is
then diagnostic rather than merely negative.

**Linear-range validity is a separate flag, and it is load-bearing.** Linear
elasticity has no yield: above the proportional limit the material would have
yielded and redistributed, so the linear solution reports a stress the object
would never have experienced. When the peak exceeds the material's
`allowable_stress_mpa` on a `yield` or `proportional_limit` basis, the result
carries `linear_range_exceeded: true` and the record's own text says the
reported magnitude is **outside the validity of the model that produced it**.
The verdict is `violated` — which is correct and conservative — but no
consumer may read the number as a physical stress, and the reviewer context
carries the flag beside the number so a model cannot quote "480 MPa" as if
the solve knew that.

## 7. The `CHECKS` surface

The project-scope measurement facade — and only it — gains one read surface:

```python
def load_bearing(m):
    return m.load_case("lc-tip-load").verdict == "holds_at_converged_mesh"
```

- **Mechanism, verbatim from the existing one.** `checks/facade.py:75-84`
  defines `ImportResolver` and `SweepResolver` as callables injected by the
  caller that owns the project, "because who may read `imports/` and under
  what confinement is a project question, not a measurement one"
  (`facade.py:16-19`). Stage 15 adds `LoadCaseResolver = Callable[[str],
  Mapping[str, JSONValue]]` with the same contract and the same comment
  shape. `project_measurement` (`facade.py:699-724`) accepts it;
  `part_measurement` (`facade.py:680-696`) deliberately does not — and that
  omission **is** the scope enforcement, in the facade's own words at
  `:713-714`. A part-scope predicate calling `m.load_case` gets a named
  refusal at **evaluation** (`kind="contract"`, citing the scope rule), on
  the `_motion_scope_refusal` shape at `facade.py:537-551`, recorded as that
  check's failure. **No load-time inspection of predicate bodies is added**,
  because the engine has never had one and Stage 15 does not introduce one.
- **`LoadCaseFacts` is flattened on the `DiffFacts`/`SweepFacts` rule**
  (`facade.py:338-398`): named scalar fields a predicate reads directly, a
  `verdict` from the closed §6 set carried as **a fact restated, never
  re-decided** (the `SweepFacts` docstring's own words at `facade.py:344-347`),
  and `raw` holding the whole record — "what the check report records as the
  measured value, so the evidence behind a failing check is every number, not
  the one that was read".

  Fields: `id, part, verdict, max_von_mises_mpa, allowable_mpa,
  allowable_basis, failure_criterion, safety_factor, margin,
  linear_range_exceeded, max_displacement_mm, peak_location_mm, peak_element,
  nodes, elements, mesh_quality_metric, mesh_quality_worst, levels (the
  per-level ladder), convergence_order, converged, excluded_nodes,
  exclusion_radius_mm, pose, pose_affects_result, mesh_ref, deck_ref,
  result_ref, raw_ref, raw_canonical_sha256, material_id, registry_digest,
  image_digest, rlimits, unit, reason, detail, raw`.

  `result_ref` reaches the facts from the projection entry, not from the
  record (§5.4): the record cannot carry its own hash. `raw` is the record,
  so `raw["result_ref"]` does not exist and a predicate reading it gets a
  `KeyError`, not a `None` that reads as "no result".
- **Timeout ⇒ `unverifiable`, not error.** `checks/engine.py:238-278`'s
  `run_checks` already discriminates two exception classes from ordinary
  failure — "a measurement whose bounded subprocess hit the wall-clock
  ceiling makes the check **unverifiable** — the predicate was never
  answered... Not a pass, and not a crash" — with the catch literally
  `except (CompareTimeout, MotionTimeout)` at `:266`. **`FeaTimeout` is the
  third member of that tuple**, and this is the single most important
  existing hook in the design: a solve that ran out of wall clock must not
  read as a failing check.
- **Provenance on the report.** `run_bundle` (`engine.py:435-482`) records
  `motion_generations` only when motion state actually governed the run,
  through wrapper closures that flip a flag **on invocation** — "never on
  mere availability of the resolvers" (`engine.py:443-446`). Stage 15 adds
  `load_generations` by the identical wrapper trick, landing on `CheckReport`
  beside `project_snapshot_ref` and `motion_generations`.
- **Snapshot coherence.** The injected resolver resolves against the run's
  **frozen** snapshot, the same rule `KINEMATICS.md:148-154` states for
  motion: a check never measures a different geometry state than the rest of
  its own run.

## 8. Surface, refusals, and the ladder

### 8.1 Tools

The quartet pattern, on the 8C decision and its recorded rationale applied
unchanged (`ASSEMBLY.md` §3, restated at `KINEMATICS.md:266-270`: declaring
is cheap, reversible, and measured against geometry the model did not choose,
so compelled honesty beats gatekeeping) — part + orchestrator profiles:

- `declare_load_case` / `update_load_case` / `read_load_cases` — the 8C
  lifecycle contract (update = revise/withdraw with recorded reason,
  generational, nothing erased; `read_load_cases` returns withdrawn entries
  with their reasons, because generational state is honest only if every
  generation stays readable).
- `check_loads(ids?)` — evaluate now → `LoadStatus` + per-case results.

**Four tools, not more.** The tool surface is exactly 53 today, pinned twice
(`contract/tests/test_toolgen.py:98,109`;
`tests/stage2/test_g2_contract_drift.py:354`), and each addition costs five
drift-tested generated artifacts (`contract/src/hephaestus/contract/
toolgen.py:1-30`), a per-profile decision, dispatch tests on both profiles,
and a `tool_schema.md` heading. The 8A/8B lever applies: put the capability
in the `CHECKS` facade rather than on the tool surface. There is no
`run_fea`-shaped tool that takes an inline load spec, and no separate
`mesh_part` tool: a mesh is not a thing a model asks for, it is a recorded
input to a declared case.

### 8.2 Operator CLI

`heph loads` (the load-case table + `--json`), `heph loads check [ids]`,
`heph loads show <id>` (the ladder, the excluded-node count, and every
artifact ref). No posed or deformed-shape render in Stage 15 — a deformed
render would be the "viewer" §0 refuses, and a scaled-deformation image is
the most over-read artifact in the entire discipline.

### 8.3 Named refusals

Every failure mode. Refusals are named at the layer that owns them; nothing
in this table is a warning, a default, or a guess.

**Evaluation happens in two phases, and the layer column says which.**
Evaluating a load case is not one indivisible act. **Phase 1 is parent-side
and pre-solve**: resolve the part's material and check its model, resolve
every anchor and check its shape class, resolve the bound pose, compute
`pose_affects_result` from the declared load kinds, and run the rigid-body-mode
test. None of it touches a mesher, a solver, or a deck; all of it is
determinable from the ledger, the registry, and the current build artifact.
**Phase 2 is the pipeline**: the pre-mesh singularity scan, mesh, deck, solve,
parse, ladder, verdict. The split is not a description of an implementation —
it is a **contract about which sub-stage owns which refusal**, and it is what
makes the G15A clauses for the phase-1 refusals runnable with no `gmsh` and no
`ccx` on `PATH` (G15A.23 asserts exactly that). A phase-1 determination that
silently waited for phase-2 machinery would make G15A untestable until G15B
landed, and mission rule 1 (`mission_plan.md:800-803`) makes a gate clause
that cannot run a defect in this document.

| Name | Layer | Raised when |
| --- | --- | --- |
| `material_property_incoherent` | registry load | `E ≤ 0`, `ν ∉ (-1, 0.5)`, or `allowable ≤ 0`; names field and bound |
| `material_temperature_unstated` | registry load | a `mechanical` block without `temperature_c` |
| `material_source_unstated` | registry load | a `mechanical` block without `source` |
| `material_properties_missing` | evaluation ph.1 | the part's material resolves to a record with no `mechanical` block |
| `material_model_unsupported` | evaluation ph.1 | `model` is `orthotropic` or `anisotropic_process_dependent` |
| `material_unresolved` | evaluation ph.1 | the part's `material_spec` resolves to nothing (the `dfm/runner.py:79` "or None when it resolved to nothing" case, made explicit) |
| `mass_density_unbound` | measurement | `m.mass` with no explicit density and no resolved material (§1) |
| `invalid_load_case` | declaration | schema, unknown kind, missing/invalid provenance, bad anchor grammar, `safety_factor ≤ 1.0`, empty `evaluate_on`, a missing `refinement` block, `refinement.levels == 2`, `levels` outside `[1, 4]` (§3, §6) |
| `unknown_load_case` | read/evaluate | id not in the current generation |
| `assembly_load_case_unsupported` | declaration | anchors span two parts (§9) |
| `no_load_declared` | declaration | zero load entries, or all loads zero-magnitude |
| `underconstrained_load_case` | pre-solve, parent side | restrained DOF leave a rigid-body mode |
| `restraint_anchor_wrong_class` | evaluation ph.1 | a restraint anchored to an edge or vertex |
| `load_anchor_wrong_class` | evaluation ph.1 | a load anchored to an edge or vertex |
| `unresolvable_load_anchor` | evaluation ph.1 | the 8C `UNRESOLVABLE_REASONS` taxonomy, reused |
| `orphaned_load_case` | evaluation ph.1 | the bound pose is withdrawn or its joints are unresolvable |
| `exclusion_radius_loosened` | evaluation ph.1 | `HEPHAESTUS_FEA_SINGULARITY_EXCLUSION_MM` above `SINGULARITY_EXCLUSION_MM`; names the requested value and the default (§4) |
| `stress_singularity_in_region` | pre-mesh (ph.2) | an unfilleted re-entrant edge inside `evaluate_on` (§4) |
| `peak_in_excluded_region` | post-solve | the peak node lies on the excluded set's boundary (§4) |
| `mesh_too_large` | post-mesh | node count exceeds `FEA_NODES_MAX`; names the count and the cap |
| `mesh_quality_below_floor` | post-mesh | worst element below `MESH_QUALITY_FLOOR` under `MESH_QUALITY_METRIC`; names the element, the metric, the value and the floor |
| `mesh_failed` | mesher | nonzero exit, or zero elements produced |
| `solver_unavailable` | pre-run | `ccx` or `gmsh` absent from the sandbox `PATH` |
| `fea_requires_sandbox` | pre-run | the unsafe-local backend (§5.3) |
| `sandbox_denied` | pre-run | reused verbatim from `bwrap.py:348-352` |
| `singular_stiffness` | solver | the solver's own zero-pivot / rigid-mode report — the second, independent detector for the `underconstrained_load_case` condition |
| `solve_out_of_memory` | solver | the solve is killed against `FEA_RLIMITS.address_space_bytes`, or the solver reports an allocation failure; carries the limit and the node count. Distinct from `solve_failed` and from `fea_timeout` because it calls for a different fix, and because collapsing it would hide the failure §5.2's cap derivation exists to make impossible |
| `solve_failed` | solver | nonzero exit with the last 2000 bytes of stderr (`dfm/runner.py:180-184` shape), *other than* an address-space kill |
| `fea_timeout` | runner | `FEA_WALL_CLOCK_S` exceeded; `FeaTimeout`, joining the `run_checks` unverifiable tuple |
| `load_case_scope_refusal` | `CHECKS` facade | `m.load_case` on a part-scope facade (§7) |

**Two independent detectors for one condition** is deliberate. A singular
stiffness matrix is the most common load-case authoring error, and some
solvers return plausible garbage rather than an error for a
nearly-singular system `[external knowledge]`. Detecting it only from the
solver's report would be trusting the solver about the one thing we most need
to not trust it about; detecting it only geometrically would miss numerically
singular but geometrically plausible restraint sets. Both fire, and a G15B
clause asserts each independently.

### 8.4 Ladder integration (`VALIDATION.md` §5)

The termination reviewer receives:

- the full **load status** — every declared load case `resolved` or with its
  named `unresolvable` reason;
- **every load-check result**, with `max_von_mises_mpa`, `allowable_mpa`,
  `allowable_basis`, `safety_factor`, `margin`, the per-level ladder, the
  excluded-node count, and `linear_range_exceeded`, as numeric facts;
- the material id and registry digest that supplied the allowable, and the
  CI image digest that pinned the solver;
- and, **verbatim**, the §0 non-certification sentence, so the reviewer
  cannot infer certification from a green.

`violated`, `not_converged`, `linear_range_exceeded`, and `unresolvable` are
each a **blocking finding by rule** — the never-green invariant extended to
loads, the same mechanism `VALIDATION.md:311-334` already implements twice
for constraints and motion. Stamped **from the status the engine produced,
not from the reviewer's report about itself**; no verdict is solicited for a
load-case id and none is accepted. The states stay apart because they call
for different fixes: `violated` says the geometry does not carry the declared
load; `not_converged` says the discretization never answered the question;
`unresolvable` says the case was never evaluated — and an unevaluated load
case is not a passing one. A case whose solve hit the wall clock blocks on
the same unchecked-claim terms with its partial facts on the record. Only the
operator may waive, and a waiver is recorded as a waiver.

**This is blocking, where DFM is advisory** (`registries/dfm/registry.toml:
11-12`), and the contrast is intentional: a DFM finding is a question a shop
would ask, while a declared load case is a requirement the project committed
to. The cost of blocking is that a green is over-read, which is why §0's
non-certification sentence rides the reviewer context rather than living only
in this document.

### 8.5 Bench

`task.json` acceptance may declare `load_case_requirements`, each naming a
case id and an expected verdict from the closed §6 set, installed and
evaluated **through the engine path** and never from what the run reports
about itself (`bench/src/hephaestus/bench/harness/_grade.py:688`, "graded
*through the same engine path*", and `:798`; the `gripper-jaws`
`joint_requirements` / `motion_check_requirements` shape).

**The trap, named.** A stress threshold on a simulated number is the
`VALIDATION.md:78-80` volume-window anti-pattern one level up: a task that
scores "peak stress under 200 MPa" is grading the solver, the mesh, and the
model's geometry as one undifferentiated number. The honest form: **acceptance
asserts a declared margin under a declared load evaluated through the engine
path, exactly as a constraint requirement does, while correctness-of-the-solver
lives entirely in §10's Tier 1 analytic benchmarks.** A Tier 3 pass rate may
never stand in for solver validation.

Corpus v4 adds a `stress-*` family (minimum: an aluminium bracket that must
carry a declared tip load with a declared safety factor and a declared
evaluation region; a second task whose reference geometry *fails* its margin
and must be thickened, so the family grades a fix and not only a pass), each
with prose + seeded variants, dual independent solutions
(`VALIDATION.md:94-98`), and hand-counted budgets. Per `VALIDATION.md` §1 as
G9C restated it verbatim (`KINEMATICS.md:394-398`): **stress-prose and
stress-seeded are each their own split, each baselined on its own first
measurement with the reference model at ≥3 seeds, neither compared against
nor averaged into the v1/v2/v3 baselines**; the existing 0.70 prose bar keys
on its own coverage (`bench/src/hephaestus/bench/scoring.py:117-128`) and is not diluted, and
re-baselining any combined bar is its own explicit future amendment.

## 9. What deliberately does NOT change, and what is deliberately out of scope

### 9.1 Non-changes

- **No geom service.** `hephaestus.geom` stays at nine pure services and the
  boundary tests (`core/tests/test_geom_import_boundary.py:45-78`) are
  unchanged. A solve is a subprocess (§0).
- **No mesh in the geometry layer, ever.** `COMPARE.md:82-83`'s "no
  mesh-based comparison path; no point-cloud imports" stands unamended. A
  mesh is a solver input addressed by hash and is never a build artifact, a
  boolean operand, an export, or a comparison target.
- **No placement or assembly solver.** `ASSEMBLY.md:55-57` and
  `KINEMATICS.md:45-48` stand verbatim: scripts position geometry, nothing
  here moves what a script authored, and no result republishes transformed
  geometry.
- **`geom.measure.mass` is unchanged** (§1) — what changes is that a caller
  finally binds a real density.
- **Export, `generate_drawing`, `inspect_part`, and the render surface are
  unchanged.** No deformed-shape render, no stress contour image, in any
  surface, in Stage 15 (§8.2).
- **No new registry kind and no new persistence pattern.** The four kinds of
  `registries/PUBLISHING.md:25` are unchanged; the load-case set is a fifth
  use of the existing ledger pattern; the one piece of non-ledger persistence
  is the `loads` field of `ProjectionState`, on the assembly/motion
  projection precedent (§3).
- **`INTERFACE.md` is unchanged** — `run_fea`'s exclusion from the workspace
  `TOOLS` set (`INTERFACE.md:3296`, `:4347`) is a Stage 10 product question.
- **`SANDBOX_ENV` is unchanged**; `extra_env` is additive and defaults empty
  (§5.3).

### 9.2 Out of scope, each with its named refusal

Every exclusion is a refusal, not a silent success — the point of naming them
is that a load case reaching for one gets told, rather than getting an
isotropic-linear-static answer to a different question.

| Excluded | Why | Refusal |
| --- | --- | --- |
| **Dynamics, modal, vibration, impact** | Needs mass matrices, damping, and time. `KINEMATICS.md:49-54` already excludes it and this stage does not reopen it. | `analysis_type_unsupported` |
| **Nonlinear material (plasticity, hyperelastic, creep)** | Needs a constitutive model beyond `E, ν`; the honest signal is §6's `linear_range_exceeded`, which says the linear answer left its own validity. | `material_model_unsupported` |
| **Contact** | The reason load cases are per-part (§0). Contact is nonlinear, mesh-sensitive, and the single largest source of plausible-looking wrong answers in the discipline. | `assembly_load_case_unsupported` |
| **Large deformation / geometric nonlinearity** | Small-strain kinematics assumed. A result whose max displacement exceeds `LARGE_DISPLACEMENT_FRACTION = 0.02` of the part's bounding-box diagonal carries `small_strain_assumption_violated` on the record and is `unresolvable` — because the linear answer is then about a shape the part never had. | `small_strain_assumption_violated` |
| **Buckling / stability** | **Named explicitly because it is the exclusion most likely to be over-read.** A thin web can pass every stress margin in this document and still collapse elastically under a compressive load; nothing here looks for that. A load case whose loads are net-compressive on a slender member is **not** refused — we cannot detect it reliably — so instead the reviewer context carries the exclusion in the non-certification sentence, and the record carries `buckling_not_evaluated: true` unconditionally. Stating it on every record is the only honest option available. | recorded flag, not a refusal |
| **Thermal, thermo-mechanical, thermal expansion** | No temperature field; `temperature_c` (§2) exists only to stamp the properties' validity. | `analysis_type_unsupported` |
| **Fatigue, durability, cycles to failure** | Needs S–N data, load spectra, and surface-finish factors, none of which exist. A static margin says nothing about 10⁶ cycles. | `analysis_type_unsupported` |
| **Fracture, crack propagation** | Needs fracture toughness and a crack. | `analysis_type_unsupported` |
| **Orthotropic and composite materials** | §2: plywood and printed parts, which is most of the corpus. | `material_model_unsupported` |
| **Welds, bolted-joint stiffness, press fits** | Joint modelling is its own discipline; 8C `clearance`/`concentric` constraints already carry what the harness can honestly say about a fit. | `assembly_load_case_unsupported` |
| **Motor sizing and torque** | `KINEMATICS.md:50` deferred it alongside FEA; this stage takes only the FEA half and says so. | not in the load-kind set |
| **Optimization / auto-thickening** | The harness measures; the script authors. A solver that changed geometry would be the non-git source of geometric truth mission rule 6 forbids. | no surface exists |

## 10. Analytic reference cases: the only way to verify a solver we did not write

The gate does not trust the solver. It verifies the *integration* — geometry
→ mesh → deck → solve → parse → verdict — against problems whose exact answer
is known in closed form, and it declares, for each, the band the
idealization itself costs. `verification.md:48-49` already establishes the
precedent ("Kernel-service tests: interference/clearance/distance/mass against
hand-computable fixtures"); this is that discipline at one more level of
difficulty.

**The closed-form solutions live in the test suite
(`tests/stage15b/analytic.py`), never in the product.** An oracle that ships
in the engine is an oracle the engine could be made to agree with.

**Every band below is justified by the theory gap, not chosen to make the
solver pass.** A band with no stated reason is exactly the ambiguity mission
rule 1 says must be resolved by tightening.

### Case 1 — Uniaxial bar and rigid-body patch test

`σ = P/A`; `δ = P L / (A E)`; and a mesh under an imposed rigid-body
translation and rotation must produce **exactly zero strain**.

- Tests element formulation, assembly, boundary conditions, unit handling —
  and catches the class of bug the three richer cases can mask.
- **Band: 1e-9 relative.** There is no idealization gap: the exact solution is
  in the element space, so a correct implementation reproduces it to round-off.
  This is the tolerance `KINEMATICS.md:346` uses for hand-computed transforms
  and `ASSEMBLY.md:135` for residual determinism.

### Case 2 — Cantilever beam, end load

`δ_tip = P L³ / (3 E I)`; `σ_bending = M c / I`; rectangular `I = b h³/12`,
`c = h/2`.

- Tests bending, a fixed restraint, a distributed end load.
- **Declared idealization: `L/h = 20`.** Euler–Bernoulli neglects shear
  deflection, which is approximately `6 P L / (5 G A)` — under 1–2 % of the
  bending term at this slenderness `[external knowledge]`. The slenderness is
  part of the fixture, not an afterthought.
- **Bands: 2 % on tip deflection, 3 % on bending stress**, both justified by
  that shear term, plus **strictly decreasing error across the refinement
  ladder** — which is the more diagnostic clause, and is machine-checkable
  without any tolerance argument at all.
- **Stress is sampled at mid-span, never at the built-in end**, where the
  idealization is singular (§4). A gate that sampled at the fixture would
  chase a mesh-dependent number forever, and would fail for the right reason
  in a way that looks like the wrong one.

### Case 3 — Thick-walled cylinder, internal pressure (Lamé)

`σ_θ(r) = p a² (b² + r²) / (r² (b² − a²))`,
`σ_r(r) = p a² (b² − r²) / (r² (b² − a²))` (open ends), with a closed-form
bore displacement in `E` and `ν`.

- **Exact, with no idealization gap** — this is the tightest case and
  therefore the best discriminator. It is also the only one of the four where
  **`ν` genuinely matters**, so it is what proves Poisson's ratio reached the
  deck at all; the cantilever would pass with `ν` mis-transcribed.
- Tests curved-surface meshing and `pressure_mpa` (a `*DLOAD`) rather than a
  point or face force.
- **Band: 1 %** on hoop stress at the bore and at the outer radius with
  second-order elements.

### Case 4 — Clamped circular plate, uniform pressure (Kirchhoff)

`w_max = q a⁴ / (64 D)`, `D = E t³ / (12 (1 − ν²))`.

- Tests plate bending and thin-feature meshing — the sheet-goods geometry the
  corpus actually contains.
- **Declared idealization: `a/t ≥ 10`**; Kirchhoff neglects transverse shear.
  **Band: 3 %** on centre deflection.
- **It is also the case that carries the honest material refusal**: the same
  plate declared in `plywood-baltic-birch` must refuse
  `material_model_unsupported` rather than produce a number, because the
  isotropic formula is wrong for plywood by a factor a percentage band would
  never reveal. Verifying a *refusal* with the same fixture that verifies a
  *result* is the cheapest possible proof that the refusal is real.

## 11. NAMED NEW WORK

Everything below does not exist today and must be built. This list is
exhaustive by intent, on the `KINEMATICS.md` discipline: **anything not named
here is a claim that it already exists**, and a reviewer should treat an
omission as a defect in this document rather than as machinery to be assumed.

**Registry and materials (15A)**

1. `Material.mechanical` — a new frozen record and its parse/validate path in
   `core/src/hephaestus/core/registry/_materials.py` (today the dataclass at
   `:29-41` is `id, name, density, forms, thicknesses, notes, keywords,
   registry, digest` and nothing else), including `to_json` at `:43-54`.
2. The four coherence/completeness refusals at registry load
   (`material_property_incoherent`, `material_temperature_unstated`,
   `material_source_unstated`, and the closed-set checks on `model`,
   `allowable_basis`, `failure_criterion`).
3. `mechanical` blocks authored into all four shipped records — solvable
   constants for `al-6061`, declared-unsupported models for the other three
   (§2) — with sourced provenance strings, plus a registry version bump and
   digest re-pin.
4. `schemas/tools/search_materials.schema.json` extension (today `:20-46`
   declares exactly `{density, forms, id, name, notes, thicknesses}`) and its
   drift-tested regeneration.
5. `registries/PUBLISHING.md` §1 table row edit and `architecture.md` §3.6
   edit.

**Units (15A)**

6. `DENSITY_KGM3_TO_GMM3` and `DENSITY_KGM3_TO_TMM3` as named constants at one
   boundary each.
7. Binding a resolved material's density into `part_measurement` at
   `core/src/hephaestus/core/executor/worker.py:674` — today it passes
   `imports=` only, so no production `m.mass` has ever had a real density.
8. Replacing `DEFAULT_DENSITY = 1.0` (`checks/facade.py:85`, consumed at
   `:518`) with the `mass_density_unbound` refusal, and correcting the `:516`
   docstring's "1.0 g/cm³".
9. An audit of every fixture and corpus `m.mass` call for the tightened
   behaviour (verified today as empty in `corpus/`, but not in `core/tests`
   or `server/tests`).

**Load-case state (15A)**

10. `core/src/hephaestus/core/project_store/loads.py` — the load-case ledger:
    entry schema, generational CAS-swap under the project-config lock,
    withdrawal-as-generation, `read` returning withdrawn entries.
11. The declaration-time refusals: `invalid_load_case`, `unknown_load_case`,
    `assembly_load_case_unsupported`, `no_load_declared`.
12. The parent-side rigid-body-mode test producing
    `underconstrained_load_case` — new geometry-side work with no existing
    analogue.
13. The restraint/load anchor **shape-class** checks
    (`restraint_anchor_wrong_class`, `load_anchor_wrong_class`) — the
    `ConstraintShapeError` taxonomy extended, on the
    `KINEMATICS.md:83-85` precedent.
13a. **The two-phase evaluator split** (§8.3): a parent-side phase-1 entry
    point that resolves the material and its model, resolves every anchor and
    checks its shape class, resolves the bound pose, computes
    `pose_affects_result`, runs the rigid-body-mode test, and resolves the
    effective exclusion radius — returning either a `LoadStatus` of named
    refusals or a green light for phase 2. It **must be callable, and is
    tested, with no mesher and no solver on `PATH`**; the phase-2 pipeline
    (item 22) consumes its output rather than re-deriving it. This is the
    machinery that makes the ordering claim in the Gates section true rather
    than aspirational.
14. `LoadProjection` and the `loads` field on `ProjectionState`
    (`project_store/projections.py:319-347`), with `to_json`/`from_json`, the
    restale triggers of §3 (including the **registry-digest** trigger, which
    neither assembly nor motion has), and the GC edge.

**Geometry preparation (15B)**

15. Re-entrant-edge detection inside a declared region producing
    `stress_singularity_in_region` — `geom.topology` today provides
    `planar_faces` (`:140`) and `opposing_planar_pairs` (`:201`) and nothing
    about edge concavity or fillet presence. *(If this is implemented as a
    pure function it may live in `geom.topology`; §0's no-new-service rule
    forbids a `geom.fea`, not a topology descriptor.)*
16. Resolving `evaluate_on` anchors to a node set after meshing — the
    mesh-entity ↔ CAD-topology mapping, and the exclusion-radius node filter
    of §4.
17. Face-area measurement for `force_n` distribution, recorded as a fact.

**Toolchain and sandbox (15B)**

18. Pinned `gmsh` and `ccx` lines in `docker/ci/Dockerfile`, a new image
    build/push, and every gate job repointed to the new digest.
19. `SandboxSpec.extra_env` and its application in `build_bwrap_argv`
    (`bwrap.py:262-300`), plus the escape-suite coverage that a non-Python
    binary under bwrap is confined exactly as a Python worker is — the
    existing suites prove confinement for `sys.executable` workers and
    `("true",)`, not for a solver that opens files.
19a. **A fixed interior mount point for the writable bind** (§5.3 addition 2):
    `build_bwrap_argv` gains an optional interior path for the `--bind` /
    `--chdir` pair that is today the host path twice
    (`bwrap.py:290-296`), and the FEA spec passes `/work`. Additive and
    FEA-only — every existing worker keeps the host-path shape, asserted.
20. `FEA_RLIMITS` (`cpu_seconds` and `address_space_bytes` raised,
    **`nproc` inherited at 4096** — see §5.3 addition 3 for why this field is
    not Stage 15's to lower), `FEA_WALL_CLOCK_S`, `HEPHAESTUS_FEA_TIMEOUT_S`,
    `FEA_NODES_MAX` (item 22b), `MESH_QUALITY_METRIC`, `MESH_QUALITY_FLOOR`,
    `CONVERGENCE_BAND_REL`, `REFINEMENT_LEVELS_MIN`,
    `REFINEMENT_LEVELS_MAX`, `SINGULARITY_EXCLUSION_MM`,
    `REENTRANT_ANGLE_DEG`, `LARGE_DISPLACEMENT_FRACTION`,
    `SOLVE_AGREEMENT_REL` — named constants, none of which exists.
20a. **The exclusion-radius floor resolver** and its refusal: a
    `singularity_exclusion_mm()` that honours
    `HEPHAESTUS_FEA_SINGULARITY_EXCLUSION_MM` at or below the default and
    raises `exclusion_radius_loosened` above it — deliberately **not** the
    `compare_timeout_s` / `motion_timeout_s` shape
    (`project_compare.py:96-100`, `motion.py:1440-1447`), which accepts any
    value in either direction because a wall clock cannot move an answer.
    Plus folding the effective radius into the result record's hashed inputs.
21. `fea_requires_sandbox` as a job-level refusal that does not route through
    `origin` (`sandbox/unsafe.py:57-71` refuses only `origin: "registry"`).

**Solve pipeline (15B)**

22. `core/src/hephaestus/core/fea/` — a new package: `runner.py` (the
    `dfm/runner.py:119-186` shape), `worker.py` (the sandboxed child that
    execs the mesher and solver), `deck.py` (the `.inp` writer, deterministic
    and sorted), `parse.py` (`.dat`/`.frd` → typed record), `types.py`
    (`LoadCaseResult`, `LoadStatus`, `MeshFacts`, `ConvergenceLadder`).
22a. The mesh-determinism establishment work of §5.2 — pinned mesher
    algorithm and seed, single-threaded invocation, and the two-process byte
    comparison that either establishes the property or blocks the stage.
22b. **The `FEA_NODES_MAX` derivation measurement** (§5.2): a one-time,
    archived measurement inside the pinned image of the largest `c3d10` node
    count at which the §10 case-2 reference solve completes under
    `FEA_RLIMITS` with 20 % headroom on both `cpu_seconds` and
    `address_space_bytes`; the constant is set to
    `min(250_000, measured)`, its docstring carries the measurement and the
    measuring image digest, and a moved image digest re-opens it. Without
    this the cap and the ceiling are two independent guesses and the "cheap,
    deterministic, actionable" claim is unfounded at the sizes that matter.
22c. **Volatile-range identification and `raw_canonical_sha256`** (§5.4): the
    parser records the byte ranges of the raw solver output it treats as
    volatile and a digest over a declared, versioned normalization of those
    ranges. The published bytes are never edited; the normalization is a
    recorded input, so a reader can recompute the digest.
23. `artifact:mesh`, `artifact:fea-deck`, `artifact:fea-raw`,
    `artifact:fea-result` as published kinds, recorded in `tp_artifact_kinds`
    (`project_store/artifact_kinds.py`).
24. `FeaTimeout` as an exception type and its addition to the `run_checks`
    tuple at `checks/engine.py:266` (today literally
    `except (CompareTimeout, MotionTimeout)`).
25. The convergence ladder driver: N solves, monotonicity and band test,
    per-level facts, the recorded observed convergence order from the last
    three peaks, the `REFINEMENT_LEVELS_MIN` guard that makes
    `holds_at_converged_mesh` unreachable from a shorter ladder, and
    `not_converged`.
26. `linear_range_exceeded`, `small_strain_assumption_violated`, and
    `buckling_not_evaluated` computation and recording.
27. `singular_stiffness` extraction from the solver's own diagnostic output —
    parser work against a format we do not control.
27a. **`solve_out_of_memory` discrimination**: distinguishing an
    `RLIMIT_AS`-driven death (the kill signal, or the solver's own allocation
    failure on stderr) from an ordinary nonzero exit and from a wall-clock
    kill, so the three failures stay three refusals.

**`CHECKS` and surface (15C)**

28. `LoadCaseResolver` and the `at_load` injection on `project_measurement`
    (`facade.py:699-724`), the deliberate omission on `part_measurement`
    (`:680-696`), and the `load_case_scope_refusal` on the
    `_motion_scope_refusal` shape (`:537-551`).
29. `LoadCaseFacts` — a new flattened record on the `SweepFacts` pattern
    (`facade.py:338-398`) with a `from_json`.
30. `load_generations` on `CheckReport` and the invocation-flipped wrapper in
    `run_bundle` (`engine.py:443-459`).
31. Four tools through the full generated pipeline: `tools_decl.py` entries,
    five drift-tested artifacts, `PROFILES` decisions, reviewer-subset
    decision (`tools_decl.py:78-81` — load results reach the reviewer as
    *context*, not as a tool, so `REVIEWER_TOOLS` is unchanged), dispatch
    tests on both profiles, `tool_schema.md` headings, and repointing the two
    53-tool pins.
32. `run_fea` removal from `STAGE2_EXCLUDED_TOOLS`
    (`tools_decl.py:84`) and from the `tool_schema.md:1487-1489` deferred
    section.
33. `heph loads` / `heph loads check` / `heph loads show`, human + `--json`.
34. The `VALIDATION.md` §5 reviewer context extension, the four blocking
    rules stamped from engine status, and the verbatim non-certification
    sentence in the reviewer's prompt assembly.
35. Corpus v4 `stress-*` tasks: prose + seeded variants, dual independent
    solutions, hand-counted budgets, `load_case_requirements` in the
    `task.json` parser and the grader half installed through the engine path
    (`_grade.py:685-715`), a new coverage constant and its own threshold in
    `bench/src/hephaestus/bench/scoring.py` (`:105`, `:117-128`), and repointed corpus-count
    pins (`server/tests/test_bench_corpus.py:273`).

**Verification (15B/15C)**

36. `tests/stage15a`, `tests/stage15b`, `tests/stage15c` — three new suite
    directories on the `tests/stage9{a,b,c}` convention.
37. `tests/stage15b/analytic.py` — the four closed-form solutions and their
    fixture geometries, written independently of the product.
38. A `verification.md` performance budget for a reference solve in the
    pinned image.
39. A CI-only marker file for any clause that can only run inside the pinned
    image, on the `tests/stage7h/CI_ONLY.md` precedent that G9C followed
    (`KINEMATICS.md` G9C; `tests/stage9c/test_corpus_mechanisms.py:35-48`) —
    named, never skipped.

**Count: 46 named new-work items** (items 1–39 with 13a, 19a, 20a, 22a, 22b,
22c, 27a).

## Gates

Stage 15 lands in three gated sub-stages, strictly ordered. Every clause is a
pytest assertion; gate form is `uv run pytest tests/<dir> -q` exits 0
(`verification.md:65`). Clauses marked **[image]** run only inside the pinned
CI image and carry the `CI_ONLY` marker rather than being skipped silently.

**Strictly ordered means each gate passes with only its own sub-stage's
machinery present**, and that is itself asserted rather than asserted about:
no G15A clause may depend on a mesher, a solver, a deck writer, a `CHECKS`
resolver, or a tool, and G15A.23 proves it by running the whole G15A suite
with `gmsh` and `ccx` absent from the sandbox `PATH`. This is what the §8.3
two-phase evaluation split is *for*. Where a clause could plausibly have sat
in two sub-stages, this document places it once and says why, because a clause
whose sub-stage is ambiguous is a defect under mission rule 1
(`mission_plan.md:800-803`) and the resolution is to tighten, never to relax
the ordering. Two consequences worth stating: the phase-1 refusals
(`material_model_unsupported`, the anchor-class and anchor-resolution
refusals, `orphaned_load_case`, `pose_affects_result`) are **15A** work and
are gated in G15A because §8.3 makes them solver-independent; and the tool
quartet and the `heph loads` CLI are **15C** work (§11 items 31 and 33) and
are gated **only** in G15C.8 and G15C.14 — an earlier draft duplicated them as
a G15A clause, which asserted 15C machinery inside the 15A gate and is
removed, its full coverage retained downstream.

### Gate G15A — properties, units, and load-case state

`uv run pytest tests/stage15a -q` exits 0.

1. A materials record with a well-formed `mechanical` block loads and
   round-trips through `Material.to_json` and the `search_materials` schema.
2. A record with no `mechanical` block still loads (backward compatibility),
   and all four pre-Stage-11 record files load unchanged at their prior
   digests before the content amendment.
3. `material_property_incoherent` fires on each of `E ≤ 0`, `ν = 0.5`,
   `ν = -1.0`, `allowable = 0`, each naming its field and bound.
4. `material_temperature_unstated` and `material_source_unstated` each fire.
5. Each of `model`, `allowable_basis`, `failure_criterion` refuses a value
   outside its closed set, naming the set.
6. `al-6061` resolves to a solvable block; `plywood-baltic-birch`, `pla` and
   `petg` each resolve to a declared unsupported model, and each produces
   `material_model_unsupported` **from phase 1** (§8.3) when a load case names
   it — asserted with no mesher and no solver present, because the material
   model is decided from the registry record and never from a solve.
7. `heph registry verify` passes on the amended registry and fails on a
   one-byte tamper of a `mechanical` block.
8. `DENSITY_KGM3_TO_GMM3` applied to `al-6061` and a 1000 mm³ fixture yields
   2.7 g through `m.mass` — the mass is a mass, to 1e-9.
9. `mass_density_unbound` fires on `m.mass` with no explicit density and no
   resolved material; the message names the part and does not return a
   number.
10. A `m.mass` call with an explicit density is unchanged, bit-for-bit,
    against recorded pre-stage behaviour.
11. Declare/update/withdraw a load case: generational, immutable, provenance
    compelled (`invalid_load_case` without it), withdrawn entries returned by
    `read_load_cases` with their reasons.
12. `invalid_load_case` fires on each of: a slash-bearing anchor, an unknown
    restraint kind, an unknown load kind, `safety_factor = 1.0`, empty
    `evaluate_on`, **a missing `refinement` block**, **`refinement.levels =
    2`**, and **`refinement.levels = 5`** — the last three because the verdict
    vocabulary is a function of the ladder's length (§6), and each refusal
    names the admissible set `{1, 3, 4}`.
13. `assembly_load_case_unsupported` on a case whose anchors span two parts.
14. `no_load_declared` on a case with zero load entries, and on a case whose
    only load is a zero-magnitude `force_n`.
15. `underconstrained_load_case` on each of: no restraint; a single small
    `fixed` face leaving a rotational mode; three collinear restrained
    points — each refusal naming the unremoved mode.
16. `restraint_anchor_wrong_class` and `load_anchor_wrong_class` on an edge
    anchor and a vertex anchor — **phase 1**: the shape class of a resolved
    anchor is a BRep fact (§11 item 13), decided before any mesh exists.
17. `unresolvable_load_anchor` through the reused 8C `UNRESOLVABLE_REASONS`
    taxonomy for a tag that no longer resolves — **phase 1**: anchor
    resolution is the 8C resolver against the current build's source map, not
    a solver output.
18. `orphaned_load_case` when the bound pose is withdrawn, naming the pose id
    — a per-case state, not a pose-set failure; **phase 1**, decided from the
    motion generation alone.
19. `pose_affects_result` is `true` for a `gravity` case with a bound pose and
    `false` for a `force_n` case with a bound pose, on the same fixture —
    **phase 1**, computed from the declared load kinds (§3) and therefore
    available before, and independently of, any result.
20. Staleness: rebuilding the part restales the `loads` projection field;
    advancing the load-case generation restales it; **changing the pinned
    registry digest restales it**; the GC edge keeps a stale status readable.
21. `ProjectionState.to_json` / `from_json` round-trip with the `loads` field
    present and absent.
22. Two processes produce byte-identical load-case generation documents from
    the same declarations.
23. **The sub-stage ordering, asserted rather than asserted about**: the whole
    of `tests/stage15a` passes with `gmsh` and `ccx` absent from the sandbox
    `PATH` and with `hephaestus.core.fea` not importable, and every phase-1
    determination of §8.3 — material resolution and model check, anchor
    resolution, anchor shape class, orphaned pose, `pose_affects_result`,
    the rigid-body-mode test, the effective exclusion radius — returns its
    named result under that condition. A G15A clause that needed G15B
    machinery would fail here by construction, which is the point.

*(23 clauses.)* The tool quartet and `heph loads` are **not** among them: they
are 15C machinery (§11 items 31, 33) and are gated at G15C.8 and G15C.14.

### Gate G15B — mesh, solve, and the analytic suite

`uv run pytest tests/stage15b -q` exits 0.

1. **[image]** `gmsh` and `ccx` are present at the pinned versions inside the
   sandbox, reached through `/usr/bin` with **no bind added** to
   `worker_ro_binds()`.
2. `solver_unavailable` is a named refusal, not a crash, when `ccx` is absent
   from the sandbox `PATH` (fault-injected).
3. `fea_requires_sandbox`: an FEA job under the unsafe-local backend is
   refused before any binary runs, and the refusal does not depend on
   `origin`.
4. `sandbox_denied` when bwrap is absent (the `bwrap.py:348-352` path,
   asserted for the FEA runner specifically).
5. The FEA worker cannot read the project directory or write outside
   `rw_out_dir`, proven by denial — the escape suite extended to a job that
   execs a native binary.
6. **[image]** A meshed fixture produces a mesh with recorded node count,
   element count, worst-element quality, mesher version, and image digest,
   published as `artifact:mesh:sha256:…` and recorded in
   `tp_artifact_kinds`.
7. **[image]** **Mesh determinism**: two processes, identical BRep and
   `MeshSpec`, byte-identical mesh files.
8. **[image]** The solver's environment inside the sandbox contains
   `OMP_NUM_THREADS=1` (echoed by the worker into the record and asserted),
   and `SANDBOX_ENV` is unchanged for non-FEA workers.
9. **[image]** **Deck determinism**: two processes, identical mesh + case +
   material, byte-identical `.inp`; and the deck names its unit system as a
   literal field.
10. **[image]** **Result determinism**: two processes on one host, parsed
    result records equal **field-for-field with exactly one field excluded,
    `raw_ref`**, and the exclusion list asserted to be exactly that one field
    (so a later addition cannot quietly widen it). Every number a verdict is
    computed from is inside the equality. The raw solver output is published
    as-is and its ref recorded, and no verdict is computed from the raw bytes.
10a. **[image]** **Raw-output volatility is measured, not assumed**: the two
    runs of clause 10 agree on `raw_canonical_sha256` exactly; the recorded
    volatile byte ranges are exactly the ranges over which the two raw
    outputs differ (empty set permitted and asserted as empty when it is);
    and the published `artifact:fea-raw` bytes are byte-identical to what the
    solver wrote, proving the normalization edited nothing.
11. The **result record** names four artifact refs — mesh, deck, raw, and the
    source build artifact — plus the registry digest, the image digest, the
    effective exclusion radius, and the rlimits it ran under; a record
    missing any is refused at construction (the `dfm/runner.py:84-88` "must
    name the artifact it measured" rule). `result_ref` is **absent** from the
    record and present on the projection entry that points at it (§5.4), and
    a record carrying a `result_ref` key is refused — a record cannot contain
    its own hash, and a field that silently could not be filled is worse than
    one that is refused.
12. `mesh_too_large` fires before any solve on a mesh spec exceeding
    `FEA_NODES_MAX`, the refusal naming the computed node count and the cap.
13. `mesh_quality_below_floor` fires on a fixture producing a degenerate
    element, and the refusal names the element, the literal metric name
    `scaled_jacobian`, the element's computed scaled-Jacobian value, and the
    floor `0.2`; a second fixture whose worst element is above the floor
    solves and records the same named metric as a fact. The metric name is
    asserted as a literal, not read from the implementation.
14. `mesh_failed` on unmeshable input (a fixture with a zero-thickness sliver).
15. `stress_singularity_in_region` on a fixture with an unfilleted re-entrant
    corner inside `evaluate_on`, naming the topology descriptor; the same
    geometry with the corner filleted solves.
16. The exclusion filter: excluded-node count and `SINGULARITY_EXCLUSION_MM`
    are recorded facts; `peak_in_excluded_region` fires when the surviving
    peak sits on the excluded boundary, and the verdict is `unresolvable`.
17. `singular_stiffness` from the solver's own report on a deliberately
    under-restrained deck **that the parent-side test was bypassed for** —
    proving the two detectors of §8.3 are independent.
18. **[image]** **Analytic case 1** — uniaxial bar: stress and displacement to
    1e-9 relative; rigid-body translation and rigid-body rotation each
    produce zero strain to 1e-9.
19. **[image]** **Analytic case 2** — cantilever at `L/h = 20`: tip deflection
    within 2 %, mid-span bending stress within 3 %, of the Euler–Bernoulli
    closed form; and the error **strictly decreases** across three refinement
    levels.
20. **[image]** **Analytic case 3** — thick-walled cylinder under internal
    pressure: hoop stress at bore and at outer radius each within 1 % of
    Lamé; and the same case solved with `ν` perturbed by 0.05 falls outside
    the band, proving Poisson's ratio reached the deck.
21. **[image]** **Analytic case 4** — clamped circular plate at `a/t = 12`:
    centre deflection within 3 % of Kirchhoff.
22. **[image]** The same plate declared in `plywood-baltic-birch` refuses
    `material_model_unsupported` and produces no number.
23. **[image]** Convergence: a three-level ladder on case 2 is monotone with
    a final relative delta under `CONVERGENCE_BAND_REL`, every level's
    `(target_size_mm, nodes, elements, peak_mpa, relative_delta)` is
    recorded, and the observed convergence order computed from the last three
    peaks is recorded and positive.
24. `not_converged` on a fixture whose ladder does not meet the criterion,
    carrying every level's facts; the verdict is neither a pass nor
    `violated`.
25. `holds_at_mesh` is emitted for `levels == 1` and
    `holds_at_converged_mesh` only for a met ladder — both spellings asserted
    verbatim, and `holds` appears nowhere in the verdict vocabulary.
26. `linear_range_exceeded` is `true` and the verdict is `violated` on a
    fixture loaded past the declared yield; the record's text names the
    validity limit.
27. `small_strain_assumption_violated` on a fixture whose max displacement
    exceeds `LARGE_DISPLACEMENT_FRACTION` of the bbox diagonal; verdict
    `unresolvable`.
28. `buckling_not_evaluated` is present and `true` on **every** result record,
    including passing ones.
29. `fea_timeout` as a named refusal under a fault-injected slow solve, the
    subprocess dead afterwards, and the recorded rlimits and wall clock on
    the refusal.
30. `solve_failed` carries the last 2000 bytes of solver stderr.
31. **[image]** The `verification.md` solve budget: the reference case solves
    within its declared ceiling.
32. **`FEA_RLIMITS` lets a job start on a real host.** An FEA job launches
    successfully under the declared `FEA_RLIMITS` on a host carrying a
    realistic live task count for the invoking UID — the test raises the
    UID's task count above `FEA_RLIMITS.nproc / 8` (or reads the live count
    and skips *loudly*, never silently, if the host cannot reach it) and
    asserts the sandbox's userns clone succeeds and the solver runs. A
    companion negative asserts that a deliberately low `nproc` fails with the
    recorded `EAGAIN` shape rather than with a solver error, so the failure
    mode `executor/runner.py:54-56` documents stays visible. This clause
    exists so that a future tightening of `nproc` cannot silently
    reintroduce a failure this tree already recorded and fixed.
33. **No run-unique path reaches any artifact.** The scratch dir's host path,
    as a byte sequence, appears in none of the published `artifact:mesh`,
    `artifact:fea-deck`, `artifact:fea-raw` or `artifact:fea-result` bytes;
    the interior working directory observed by the worker is exactly
    `/work`; and a non-FEA worker still runs with the host-path bind
    (`bwrap.py:290-296` unchanged for everything else).
34. **[image]** **The cap is the ceiling.** A mesh at exactly `FEA_NODES_MAX`
    nodes solves to completion under `FEA_RLIMITS` inside the pinned image —
    no `fea_timeout`, no `solve_out_of_memory` — and the recorded peak CPU
    seconds and peak address space each sit at or below 80 % of the declared
    limits. `FEA_NODES_MAX` equals `min(250_000, measured)` for the archived
    measurement of §11 item 22b, and its recorded measuring image digest
    equals the image the clause ran in. This is the clause that makes §5.2's
    "cheap, deterministic, and actionable" claim machine-checkable rather
    than rhetorical.
35. **`solve_out_of_memory` is its own refusal.** A fault-injected solve
    driven past `FEA_RLIMITS.address_space_bytes` produces
    `solve_out_of_memory`, carrying the limit and the node count — asserted
    **not** to be `solve_failed` and **not** to be `fea_timeout`, with all
    three reachable on the same fixture family under different injections.
36. **A short ladder cannot claim convergence.** No load case with
    `refinement.levels == 1` produces `holds_at_converged_mesh` under any
    peak sequence; `levels == 2` and a missing `refinement` never reach the
    solver at all (refused `invalid_load_case`, G15A.12); and a synthetic
    two-point peak sequence fed directly to the ladder driver raises rather
    than reporting a met criterion — the negative of clause 23, asserted
    because monotonicity is vacuous on two points and a positive clause
    cannot detect that.
37. **The exclusion radius is a floor, and it is inside the chain.** A run
    with `HEPHAESTUS_FEA_SINGULARITY_EXCLUSION_MM` set **below**
    `SINGULARITY_EXCLUSION_MM` is honoured and the effective radius is
    recorded on the result and inside its hashed inputs (asserted by the
    result hash differing from the same case at the default); a run with it
    set **above** the default is refused `exclusion_radius_loosened`, naming
    the requested value and the default, before any mesh is built; and every
    **[image]** clause in this gate runs with the variable unset, asserted by
    reading the recorded effective radius back as `SINGULARITY_EXCLUSION_MM`.

*(38 clauses.)*

### Gate G15C — the predicate, the ladder, and the bench

`uv run pytest tests/stage15c -q` exits 0.

1. A project-scope `CHECKS` predicate over `m.load_case` passes and fails on
   either side of the declared safety factor, on one fixture.
2. `m.load_case` in a **part-scope** check raises the named
   `load_case_scope_refusal` (`kind="contract"`, citing the scope rule) **at
   evaluation**, recorded as that check's failure — and no load-time pass
   over predicate bodies exists (asserted by a predicate whose refusing call
   is inside a never-taken branch, which must therefore pass).
3. `LoadCaseFacts` exposes every §7 field, and `raw` carries the whole
   record, from a `from_json` round-trip.
4. The predicate reads `verdict` as a restated fact: a fixture whose engine
   verdict is `violated` cannot be made to pass by the predicate reading a
   different field, because `allowable_mpa` and `safety_factor` come from
   the registry and the ledger, not from the check.
5. A `CHECKS` predicate whose solve times out lands as **`unverifiable`** in
   the check report — `FeaTimeout` through the `run_checks:266` tuple — with
   partial facts attached; not a pass, not an error.
6. `load_generations` appears on `CheckReport` **only when a load resolver
   was actually invoked**, including on a run whose only invocation ended in
   a named refusal; absent when the resolvers were merely available.
7. `m.load_case` resolves against the run's frozen snapshot: a fixture that
   republishes the part mid-run measures the frozen geometry.
8. The four tools through dispatch on both profiles; `read_load_cases`
   returns withdrawn entries with reasons.
9. Contract drift: five generated artifacts regenerate identically, the
   tool-count pins are repointed, and `run_fea` is gone from
   `STAGE2_EXCLUDED_TOOLS` and from the deferred section of
   `tool_schema.md`.
10. `REVIEWER_TOOLS` is **unchanged** — load results reach the reviewer as
    context, never as a tool.
11. Reviewer context (FakeModel harness) carries load status, every numeric
    fact of §8.4, the material id, both digests, and the §0
    non-certification sentence **verbatim**.
12. Each of `violated`, `not_converged`, `linear_range_exceeded` and
    `unresolvable` produces a blocking finding **by rule**, stamped from the
    engine status; no verdict is solicited for a load-case id and a solicited
    one is not accepted.
13. An operator waiver of a blocking load finding is recorded as a waiver.
14. `heph loads`, `heph loads check`, `heph loads show` — human and `--json`,
    the ladder and excluded-node count visible in both.
15. The corpus v4 `stress-*` tasks parse, and each reference solution passes
    its own acceptance through the engine path (Tier 1), including the task
    whose starting geometry **fails** its margin.
16. A `load_case_requirements` entry is graded from the engine's status and
    not from the run's own report (the `_grade.py:688` / `:798` engine-path rule asserted for the
    new vocabulary).
17. Corpus-count pins repointed with this stage cited; the new coverage
    constant and its own threshold in place.
18. The Tier 3 bench clause, **named not skipped** (the `tests/stage7h/
    CI_ONLY.md` precedent G9C followed): stress-prose and stress-seeded are
    each their own split, each baselined on its own first measurement with
    the reference model at ≥3 seeds, neither compared against nor averaged
    into the v1/v2/v3 baselines; the 0.70 prose bar keys on its own coverage
    and is not diluted; re-baselining any combined bar is its own explicit
    future amendment.

*(18 clauses.)*

Existing suites stay green at every sub-stage; the geom/contract/core
boundary tests keep all seams clean and continue to admit **no** new geom
service.

**Total: 79 gate clauses** (G15A 23, G15B 38, G15C 18).
