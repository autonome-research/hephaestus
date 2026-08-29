<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# 15 — Placement proposal and pose solving (Stage 13)

Number 13 is the next free slot in the repo's document sequence: `00`
`architecture.md`, `01` `script_contract.md`, `02` `tool_schema.md`, `03`
`verification.md`, `04` `mission_plan.md`, `05` `repo_conventions.md`, `06`
`VALIDATION.md`, `07` `INGEST.md`, `08` `COMPARE.md`, `09` `ASSEMBLY.md`, `10`
`EXTERNAL_EVAL.md`, `11` `KINEMATICS.md`, `12` `INTERFACE.md`.

**DRAFT — pending adversarial review and a `mission_plan.md` amendment.**
Nothing in this document is binding. Promotion follows the
`ASSEMBLY.md` / `COMPARE.md` / `KINEMATICS.md` pattern exactly
(`KINEMATICS.md:8-11`; `mission_plan.md:678-701` is the worked example): a
dated `mission_plan.md` Stage 13 heading naming 13A/13B/13C, carrying the
G13A–G13C gate summaries, and citing this spec — written **after** an
adversarial pass against the codebase. Until that amendment lands, the
no-solver rule quoted in §1 is the only binding text on this subject and this
document is a proposal about proposals.

This document is unusual among its siblings: every other normative spec in
this repo *adds* a capability the plan already anticipated. This one
**reverses a rule five documents and four modules state in the imperative**.
Mission rule 5 (`mission_plan.md:815-817`) is the only door — deferred items
enter by amending the plan with a new gated stage — and `ASSEMBLY.md:57`
pre-authorised exactly this route in the same breath as the refusal: "(A
placement solver, if ever, is a separate stage.)" §1 is therefore not
preamble. It is the load-bearing section, and a reviewer who rejects §1
should reject the rest unread.

## Amendment manifest

Each amendment lands with the sub-stage whose machinery ships it; amending a
document before its machinery exists is doc drift (`KINEMATICS.md:25-29`).

- **`ASSEMBLY.md` §1, the `NO SOLVER` bullet (`ASSEMBLY.md:55-57`)** — lands
  with **13A**, and the ordering is not a preference. 13A's second target
  form (§2A) drives joint motion to satisfy *declared 8C constraint ids*,
  which is exactly the act `ASSEMBLY.md:56-57` forbids as written: "A
  constraint that requires motion to satisfy is simply unsatisfied." An 13A
  that shipped before this amendment would be a sub-stage of machinery its
  own binding rule prohibits, so the amendment is 13A's machinery, not 13B's.
  The first two sentences are unchanged and stay normative
  verbatim: *"Scripts position geometry; constraints verify, they never move
  anything. A constraint that requires motion to satisfy is simply
  unsatisfied."* The parenthesis `(A placement solver, if ever, is a separate
  stage.)` is replaced by: *"A placement solver PROPOSES: Stage 13
  (`SOLVER.md`) computes candidate placements as a measured, provenance-
  carrying artifact that no tool applies. A constraint's verdict is still
  produced only by measuring delivered geometry; a proposal is never a
  verdict, never clears a violated row, and nothing in Stage 13 writes a
  script, a parameter, or an artifact."* The heading of the bullet changes
  from `NO SOLVER` to `NO SOLVER MOVES GEOMETRY`.
- **`ASSEMBLY.md` §4 (`ASSEMBLY.md:108`)** — lands with **13B**. "No
  placement solver." is scoped to 8C the way its neighbouring sentence was
  already scoped to 8C by the Stage 9 amendment: "No placement solver **in
  8C** (amendment: proposal-only placement solving is Stage 13 per
  `SOLVER.md`; nothing in Stage 13 moves what a script authored)."
- **`KINEMATICS.md` §0, first bullet (`KINEMATICS.md:45-48`)** — lands with
  **13A**. The sentence *"nothing in Stage 9 moves what a script authored or
  republishes transformed artifacts. A pose exists only inside an
  evaluation."* is unchanged and remains true of Stage 9 and of Stage 13. The
  bullet gains: *"Stage 13 (`SOLVER.md`) adds the inverse direction —
  **solving for joint parameter values** (§2A below) and **proposing** part
  placements (§2B) — under the same rule: a solved pose is a parameter
  assignment, which is exactly what a declared pose already is
  (`KINEMATICS.md` §3), and a proposed placement is an artifact nobody
  applies."* The bullet title changes from "A solver that positions authored
  geometry" to "A solver that MOVES authored geometry".
- **`KINEMATICS.md` §7 (`KINEMATICS.md:325`)** — lands with **13B**. "No
  placement/assembly solver — authored positions stay authored." becomes "No
  placement/assembly solver **in Stage 9** — authored positions stay
  authored, in Stage 9 and in Stage 13 alike (`SOLVER.md` §1)."
- **`tool_schema.md`** — **§`check_assembly`'s "There is no solver."
  (`tool_schema.md:815`)** is rewritten to the amended `ASSEMBLY.md` §1
  wording, **at 13A**, in the same change that adds the `solve_pose` heading.
  Splitting them was the original plan and was wrong: a normative tool
  document that carries a `solve_pose` signature block and the un-scoped
  sentence "There is no solver." would contradict itself for the whole
  duration of a *passing* G13A, and doc drift that a gate does not catch is
  the failure `KINEMATICS.md:25-29` names. G13A greps for exactly this pair
  (Gates, G13A). Three new tool headings are added — `solve_pose` (13A),
  `propose_placement` (13B, with its `space` enum extended in 13C),
  `read_proposals` (13B) — with their profile rows (§11).
- **`VALIDATION.md` §5** — lands with **13B**. The reviewer context gains
  placement proposals, **explicitly as non-evidence**: the never-green rule at
  `VALIDATION.md:308-317` is unchanged, and one sentence is added — "A
  placement proposal (`SOLVER.md` §8) is delivered to the reviewer as a fact
  about a computation, never as a constraint verdict; it clears nothing, and
  no verdict is solicited or accepted for a proposal id." **`VALIDATION.md`
  §1** gains the Stage 13 corpus split (13C), on the G9C wording verbatim.
- **`script_contract.md`** — **nothing changes.** Named here because silence
  in an amendment manifest is a claim: part scripts declare no solve, `PARAMS`
  and `hc` are untouched, the `CHECKS` facade gains no solver surface (§12),
  and no build path changes. The 13C parameter solve rides `build_part`'s
  existing transient-override preview contract (`script_contract.md:344-351`,
  `tool_schema.md:238-243`) without amending it.
- **`COMPARE.md`, `INGEST.md`, `EXTERNAL_EVAL.md`, `architecture.md`,
  `verification.md`, `repo_conventions.md`, `INTERFACE.md`** — unchanged.
  `COMPARE.md` §5's bounded-execution pattern is *reused* (§10), not amended.

Design premise: Stage 8C made a mate a declared, machine-checked fact, and
its honesty rests on a single mechanism — nothing between declaration and
measurement can move the geometry, so `violated` means the delivered design
misses the mate (`VALIDATION.md:313-315`). What 8C cannot do is tell an
author *how far off, and in what direction*. A `violated` row today carries a
signed scalar (`ConstraintResidual.slack`,
`core/src/hephaestus/geom/constraints.py:295-333`) and a worst-point pair;
turning that into an edit is unaided human or model arithmetic over a coupled
system, and coupled systems are where hand arithmetic fails. Stage 13 computes
the answer and **hands it back as a measurement**, leaving the authoring act —
and therefore the authorship, the diff, the provenance and the git history —
exactly where they are.

## 0. What this capability is, and what it is not

Stage 13 is a **numerical proposal service**: given declared constraints, the
current published artifacts, and a declared set of free variables, it computes
values that would reduce declared residuals, re-measures its own answer
through the *existing* evaluator in a separate process, and stores the result
as a content-addressed artifact. It is:

- **13A — pose solving.** Free variables are declared joint parameters
  (`KINEMATICS.md` §1). The output is an assignment `{joint_id: value}`,
  which is precisely the shape a named pose already has
  (`KINEMATICS.md:158-167`) and precisely what `declare_pose` already writes.
  **This half moves nothing authored** — but its legality under the *unamended*
  rule splits, and the earlier draft of this bullet overclaimed it. An
  **anchor-to-point target** (the inverse of `reach`) touches no constraint
  set and needs no rule change: it is arithmetic over declared joint
  parameters, and a solved assignment is a pose. A **constraint-id target**
  (§2A) drives motion in order to satisfy a declared 8C constraint, which
  `ASSEMBLY.md:56-57` forbids in those words; it is legal only under the §1
  amendment, which therefore lands with 13A (Amendment manifest). 13A is
  staged before 13B because it shares every piece of machinery with it and
  scheduling it elsewhere would duplicate that machinery — not because it
  needs no amendment.
- **13B — placement proposal.** Free variables are a rigid transform per
  declared-free part. The output is a **proposal artifact**, not a placement.
- **13C — parameter proposal.** Free variables are declared `Param`s
  (`script_contract.md:44-64`), evaluated by transient-override preview
  builds, which are `current=false` by contract and publish nothing
  (`script_contract.md:344-351`).

It is **not**:

- **A solver that moves geometry.** No tool, CLI verb, or code path in Stage
  11 writes a part script, writes a parameter, republishes a transformed
  artifact, or makes any build current. The four module-level contracts that
  say so today (`geom/constraints.py:17-18`, `geom/kinematics.py:17-21`,
  `core/assembly.py:27-34`, `core/motion.py:106-110`) are **not weakened**;
  the new modules restate them.
- **A writeback engine.** There is no inverse from a `RigidTransform` to a
  script expression. A +0.42 mm X delta on
  `corpus/public_fixtures/assembly/parts/bracket.py:19-20` can be authored as
  a change to `hc.joint_clear`, `hc.shelf_w`, `p.wing`, or a new literal —
  four different design intents, three of which change other parts
  (`script_contract.md:88-97`). Stage 13 **refuses to guess which**, and the
  refusal is structural rather than a promise or a runtime check: the
  proposal document schema (§8) is `additionalProperties: false`, so a
  `suggested_edit` field cannot be emitted, and every tool input schema in
  this repo already is (53 of 53 `schemas/tools/*.schema.json`, e.g.
  `set_params.schema.json:6`), so one cannot be requested either. There is
  no refusal *name* here because there is no reachable request to refuse —
  see §8.
- **A constraint-driven parametric modeller.** Constraints do not acquire
  authority over geometry; they acquire a *gradient*. The authority stays in
  the script.
- **A global optimiser.** Every method here is local, started from declared
  starts, and its verdicts say so by name (§6). No branch-and-bound, no
  simulated annealing, no random restarts (an RNG would also break §9).
- **Dynamics, loads, FEA, or contact resolution.** Unchanged from
  `KINEMATICS.md:49-54`; FEA is named deferred by `mission_plan.md:815-817`.
- **A verdict.** §7 and §8 are the sections that make this true, and they are
  the sections a hostile review should read first.

## 1. The reversal, confronted

### 1.1 The rule, verbatim

`ASSEMBLY.md:55-57`, §1's last bullet:

> **NO SOLVER.** Scripts position geometry; constraints verify, they never
> move anything. A constraint that requires motion to satisfy is simply
> unsatisfied. (A placement solver, if ever, is a separate stage.)

`ASSEMBLY.md:108`, §4: "No placement solver."

`KINEMATICS.md:45-48`, §0's first bullet:

> - **A solver that positions authored geometry.** The 8C rule stands
>   verbatim: scripts position geometry; nothing in Stage 9 moves what a
>   script authored or republishes transformed artifacts. A pose exists only
>   inside an evaluation.

`KINEMATICS.md:325`, §7: "No placement/assembly solver — authored positions
stay authored."

`tool_schema.md:815-817`: "**There is no solver.** Scripts position geometry;
constraints verify, they never move anything, and a constraint that would
need motion to satisfy is simply unsatisfied."

And in code, as module contract, four times:
`core/src/hephaestus/geom/constraints.py:17-18`
("**NO SOLVER** … Nothing here moves geometry. A constraint that would need
motion to hold simply measures as unsatisfied.");
`core/src/hephaestus/geom/kinematics.py:17-21`;
`core/src/hephaestus/core/assembly.py:27-34`;
`core/src/hephaestus/core/motion.py:106-110`.

### 1.2 What the rule protects

The rule is a short sentence guarding seven properties. Each is named here
with the machinery that implements it, because a design that preserves "the
spirit" of an unenumerated rule preserves nothing.

- **P1 — reproducibility is defined off the script.** A build's identity is
  `input_hashes = {script, hc_dependencies, part_params, effective_params,
  toolchain, imports}` (`script_contract.md:305-313`, rules at `:336-351`). A
  position originating anywhere else is not named by that hash set, so the
  artifact stops being a function of its recorded inputs.
- **P2 — git owns authored design state (mission rule 6,
  `mission_plan.md:818-822`).** Per-part placement stored in `.heph/` or a
  ledger would be a second source of geometric truth, which rule 6 forbids
  independently of `ASSEMBLY.md`.
- **P3 — one home per number.** `hc` is how mating parts agree without
  duplicating numbers; a part may not shadow an `hc` name (lint error) "so
  every tunable has exactly one home", and the executor marks exactly the
  consuming parts dirty when an `hc` name changes
  (`script_contract.md:88-97`). A solved literal transform is a second home
  for a number `hc` already owns, and it desynchronises every part reading it.
- **P4 — the diff carries intent.** Real placements are symbolic:
  `corpus/public_fixtures/assembly/parts/bracket.py:19-20` reads
  `body = Pos(hc.shelf_w / 2.0 + hc.joint_clear + p.wing / 2.0, 0, 0) * body`
  under the comment "Seat the bracket one joint_clear off the frame's +X
  face." A reviewer reads that. Nobody reads a 3×4 matrix.
- **P5 — the verdict vocabulary means something.** "`violated` says the
  delivered geometry does not meet a declared mate, `unresolvable` says the
  mate was never checked — and an unchecked constraint is not a passing one"
  (`VALIDATION.md:313-315`), stamped from the engine's status, with "no
  verdict … solicited for a constraint id and none … accepted"
  (`VALIDATION.md:308-312`).
- **P6 — the closed loop stays broken.** "A self-authored spec test cannot
  catch a misreading of the spec, because it encodes the misreading"
  (`VALIDATION.md:24-26`); "Acceptance checks are functional, never
  reproductive" (`VALIDATION.md:58-60`). A harness that satisfies its own
  declared constraints by moving geometry is that loop with one extra step.
- **P7 — every geometry decision cites a requirement.** Constraint provenance
  is compulsory — a requirement id or `assumed` with a reason — "because a
  constraint IS an interpretation of intent" (`ASSEMBLY.md:52-54`;
  enforced at
  `core/src/hephaestus/core/project_store/constraints.py:26-31`).

### 1.3 The design that preserves them

One structural decision does most of the work, and it is the decision the
operator's framing already points at:

> **DECISION (the reversal's whole content): the solver PROPOSES.** Its
> output is a content-addressed, provenance-carrying measurement artifact.
> No tool, no CLI verb, and no agent path in Stage 13 applies it. Applying is
> an authoring act performed by an agent or operator through the *existing*
> `edit_part` / `write_part` / `set_params` surface, with the existing
> optimistic-hash, journal-backed, no-force-overwrite contract
> (`tool_schema.md:190-228`), and it shows up in git as a normal diff.
>
> **The alternative that lost: mutating published artifacts** — republishing
> transformed geometry so a constraint measures satisfied. It fails P1
> (provenance stops being a function of `input_hashes`), P2 (git no longer
> holds design state), P5 and P6 (the constraint becomes self-satisfied), and
> it exports geometry no script produces. Stage 9 already refused a strictly
> weaker version of it — "or republishes transformed artifacts"
> (`KINEMATICS.md:46`), "exports are never posed" (`KINEMATICS.md:337`).
> A third alternative, **the solver driving `edit_part` itself**, is refused
> in Stage 13 for a narrower reason: it resolves the writeback ambiguity of
> §0 by model interpretation, which `VALIDATION.md` gates rather than trusts,
> and it collides with the tag-drift soft failure
> (`script_contract.md:161-188`) where a resolved selector "may select a
> *different* face, and nothing in the resolution itself detects the drift".
> It is a candidate for a later amendment that would need the
> dimension-findings discipline verbatim; it is not in Stage 13.

Property by property, under that decision:

| Property | How it survives |
|---|---|
| P1 | No artifact is produced by anything but a script build. A proposal is not an input to a build and is not in `input_hashes`. The 13C preview builds are `current=false` by existing contract (`script_contract.md:344-351`). |
| P2 | A proposal is a *measurement*, in the same category as an `AssemblyStatus` or a `SolidDiff` — not design state. Design state after Stage 13 is exactly what it is today: scripts, `globals.py`, and persisted params, in git. |
| P3 | Nothing is written, so no second home is created. The 13C parameter space is the strongest case: its free variables are `Param`s, which already have exactly one home and already ride `effective_params` in the input hash. |
| P4 | The author writes the diff. A proposal deliberately ships **no** suggested source text (§8). |
| P5 | §7: the proposal's residuals are re-measured by `core.assembly` through `evaluate_residual` in a separate process, and the `AssemblyStatus` row is untouched — it keeps saying `violated` until a rebuilt script measures otherwise. |
| P6 | The loop is broken at the same seam `VALIDATION.md` already uses for binding-dimension findings: a finding "clears in exactly two ways — a later successful build of the same part whose binding diff no longer raises it … or an explicit dismissal by the user", and "there is no model-facing write" (`VALIDATION.md:254-266`). Stage 13 adopts that clearing rule verbatim for proposals. |
| P7 | A solve request carries compulsory provenance on the 8C/ledger taxonomy (§8): a requirement id, or `assumed` with a reason. A proposal without it is refused `invalid_solve_request`, nothing written. |

## 2. Three solve spaces, one discipline

Every space obeys the same five-step pipeline; only the variables differ.
**Resolve → assemble residuals → iterate → re-measure independently → record
as a proposal.**

### 2A. Pose space (13A) — free joint parameters

Variables: a declared subset of the joint set's parameters, each inside its
declared limits (`JointFrame.limits` / `travel_limits`,
`core/src/hephaestus/geom/kinematics.py:268-298`). Targets: an anchor-to-point
target (the inverse of `reach`, `KINEMATICS.md:195-200`), and/or a set of
constraint ids evaluated at the solved assignment.

Nothing here moves authored geometry: a solved assignment is a *pose*, poses
are already declared, model-writable project state (`KINEMATICS.md:158-167`,
`declare_pose` at `KINEMATICS.md:271-274`), and `forward_kinematics` already
places parts transiently without mutation
(`core/src/hephaestus/geom/kinematics.py:711-763`). Stage 13A adds the
inverse direction and nothing else. **13A does not auto-declare a pose**: the
solved assignment is returned, and `declare_pose` remains an explicit act.

**The two target forms are not equally legal today, and the difference is
scheduling, not rhetoric.** The anchor-to-point form needs no amendment: it
never reads the constraint set. The constraint-id form does — it moves joint
parameters *in order to make a declared 8C constraint measure satisfied*,
and `ASSEMBLY.md:56-57` says in the imperative that such a constraint "is
simply unsatisfied". That is the `ASSEMBLY.md` §1 amendment's whole job, and
it is why the manifest schedules that amendment at **13A**. An implementer
who wants 13A to ship without touching `ASSEMBLY.md` has exactly one legal
option: ship anchor-to-point targets only and defer constraint-id targets to
13B. This spec does not take that option — it amends at 13A — but records it
so the choice is a decision rather than an oversight.

### 2B. Transform space (13B) — a rigid transform per free part

Variables: `SE(3)` per part named in the request's `free` set; every other
part is ground. At least one part must be ground
(`no_ground_part`) — a system with no ground has a six-dimensional trivial
null space and every reported solution would be an arbitrary member of it.

**A part that rides a joint may not be free** (`free_part_is_jointed`): its
position is owned by forward kinematics from its parent, and letting a
transform and a joint both claim it would create the second-home failure P3
describes, inside one evaluation. Jointed parts are solved in pose space.

**A pose-bound constraint (`ASSEMBLY.md:41-44`) may not be an objective term
in transform space** (`pose_bound_constraint_in_transform_space`): its
residual is already a function of a pose assignment, and composing a free
transform with an FK transform makes the returned number attributable to
neither. Solve it in pose space, or unbind it.

### 2C. Parameter space (13C) — declared `Param`s

Variables: named `Param`s of parts or of `globals.py`
(`script_contract.md:44-64`, `:70-85`), each strictly inside its declared
`min`/`max`. This is the space that costs nothing from §1.2: the variables
are bounded, named, one-home-each, already inputs to `input_hashes`, and
already settable without touching source through transient overrides — a
build with transient params "create[s] a preview artifact and therefore
always return[s] `current=false`" (`tool_schema.md:238-240`). The solver can
therefore *evaluate* candidates while writing nothing at all.

Its cost, stated as a limitation rather than routed around: **it can only
reach placements the author parameterised.** A mate nobody made a knob for is
unreachable, and that unreachability is reported by name
(`no_free_variable_affects(constraint_id)` — a constraint whose residual is
insensitive to every free parameter, detected as an all-zero Jacobian column
block beyond `SENSITIVITY_EPS`), never worked around by inventing a
transform.

## 3. The residual system

### 3.1 The verdict is `satisfied`; the objective is a residual VECTOR

Two different numbers do two different jobs here, and an earlier draft of
this section conflated them. Conflating them is how a solver comes to emit
`converged_at_tolerance` for a placement the engine measures `violated`.

**What the verdict is decided on: `ConstraintResidual.satisfied`
(`geom/constraints.py:326`), never `slack`.** The record's own docstring is
the reason, and it is the sharpest sentence in the module: "Kinds with an
additional class predicate (`coincident`'s opposed normals, `concentric`'s
axis alignment) can be unsatisfied with positive slack, which is why
`satisfied` is stored rather than derived by the reader"
(`geom/constraints.py:304-311`). Read the code: `coincident`'s `slack` is
`tol_mm - gap` (`:664`) while its `satisfied` is `gap <= tol_mm and opposed`
(`:665`); `concentric`'s are `tol_mm - offset` (`:697`) and
`offset <= tol_mm and angle <= axis_eps_deg` (`:698`). A bracket lying flush
in the right plane and facing the *wrong way* measures `gap == 0.0`,
`slack == tol_mm`, `satisfied == False` — and `AssemblyStatus` keeps saying
`violated`. A solver graded on `slack` would report that placement as
converged, which is precisely the overclaim P5 (§1.2) exists to prevent and
precisely what §11's bench acceptance already refuses by grading on
constraint ids that "must measure `satisfied` through the ordinary engine
path". §6.1 and §7 are therefore written on `satisfied`.

**What the iteration is driven on: a residual vector per constraint**, whose
components are quantities `ConstraintResidual` already carries — in
`measured`, or by name in `values`. Each component has its own declared
bound and its own weight (§3.4):

| Kind | Primary component | Its bound | Class-predicate component | Its bound |
|---|---|---|---|---|
| `coincident` | plane gap, mm (`:657`, `measured`) | `tol_mm` | `normal_deviation_deg`, distance from a true 180° (`:658`, `values`) | `normal_eps_deg`, default `COINCIDENT_NORMAL_EPS_DEG = 1e-3` (`:209`) |
| `concentric` | radial offset, mm (`:691`) | `tol_mm` | `axis_angle_deg`, folded angle between the axis *lines* (`:692`, `:701`) | `axis_eps_deg`, default `CONCENTRIC_AXIS_EPS_DEG = 1e-3` (`:215`) |
| `parallel` | folded angle, deg (`:719`) | `tol_deg` | none — `satisfied` is the primary bound alone (`:725`) | — |
| `perpendicular` | deviation from square, deg (`:742`) | `tol_deg` | none (`:748`) | — |
| `fit` (2C only) | `hole_radius − shaft_radius`, mm (`:790-800`) | `min_mm`/`max_mm` window | none — `axis_angle_deg` / `axis_offset_mm` ride along as facts and do **not** gate `satisfied` | — |

Both class-predicate bounds are *tight*: 1e-3 deg, documented as "kernel
round-off, not a design allowance" (`geom/constraints.py:206-215`). Both are
read out of the entry's `declared` tuple (`:666`, `:699`), never assumed — a
constraint that overrode `normal_eps_deg` is solved against the number it
declared, exactly as `ConstraintResidual.declared` echoes bounds
(`:318-320`).

**The alternative that lost: keep the class predicates out of the objective
and catch them at §7.** A solver blind to the normals has no gradient that
would ever flip the bracket, so every same-facing fixture would burn its
whole iteration budget, converge on the primary component, and be refused at
verification. A refusal produced *unconditionally* for a whole fixture class
is a design error wearing a safety net's clothes.

Nothing new is invented to define "how far off": the numbers the solver
drives are the numbers the reviewer already reads.

### 3.2 Not every kind is an objective term, and the refusals say why

This is the finding most likely to be skipped by an implementer and is
therefore normative. The eight 8C kinds do not form one class:

| Kind | Objective term in 2B? | In 2C? | Class predicate (§3.1) | Why |
|---|---|---|---|---|
| `coincident` | yes | yes | opposed normals | Plane gap `dot(c_b − c_a, n_a)` (`geom/constraints.py:638-671`) — closed-form in the transform through `PlanarFaceRecord` (`geom/topology.py:86-93`). |
| `concentric` | yes | yes | axis alignment | Radial offset of one axis from the other (`geom/constraints.py:672-708`) via `CylinderRecord` (`geom/topology.py:96-108`). |
| `parallel` | yes | yes | none | Folded angle between directions (`geom/constraints.py:709-731`). |
| `perpendicular` | yes | yes | none | `abs(90 − angle)` (`geom/constraints.py:732-754`). |
| `fit` | **no** — `not_an_objective_kind(pose_invariant)` | **yes** | none | `measured = hole_radius − shaft_radius` (`geom/constraints.py:790-800`) is invariant under a rigid transform, so it carries no gradient in 2B. It is not invariant under a `Param` change, so it is a legitimate term in 2C. |
| `distance` | **no** — `not_an_objective_kind(kernel_extremum)` | **yes**, disclosed | none | `measure.distance` is `a.distance_to(b)` (`geom/measure.py:87-89`): piecewise smooth with a witness pair (`_closest_points`, `geom/constraints.py:505-513`) that switches discontinuously as surfaces slide, and the kink sits exactly where mates live. Excluded from 2B structurally (§4.1: `geom.solve` holds frames, not shapes); admitted in 2C, where every derivative is a finite difference anyway, and every result naming one lists it in `nonsmooth_terms`. |
| `clearance_min` | **no** — `not_an_objective_kind(plateau)` | **no** | none | `measure.clearance` returns exactly `0.0` whenever the solids overlap (`geom/measure.py:92-101`): a flat plateau over the whole infeasible region. A solver started in penetration has no descent information at all, and a solver that "optimises" it silently does not work. |
| `no_interference` | **no** — `not_an_objective_kind(plateau)` | **no** | none | Overlap volume is identically `0` over the whole feasible set (`geom/measure.py:62-71`). |

The two plateau kinds are **feasibility filters, never objective terms**.
They are evaluated at the returned solution as verification predicates (§7)
and their outcome is reported; they never steer the iteration. Declaring one
as an objective term is refused at request time, by name, with the reason.

### 3.3 The solver's residual is a REFORMULATION, and the identity is gated

The table above admits four kinds because their `measured` is closed-form in
the transform. That is true and it is not sufficient. **As implemented, all
four of those `measured` expressions are non-smooth or singular at exactly
their own solutions** — the same pathology §3.2 uses to *exclude* `distance`,
whose "kink sits exactly where mates live". Naming the defect in the excluded
kind and not in the admitted ones would be the review this document is
supposed to survive, failed:

- `coincident`: `gap = abs(_dot(...))` (`:657`). An absolute value whose kink
  is at `gap == 0` — the mate.
- `concentric`: `_radial_offset` is a Euclidean norm to a line
  (`:378-386`). Non-differentiable at offset `0` — the mate.
- `parallel`: `_folded_angle_deg` (`:372-375`) over
  `_angle_deg = degrees(acos(clamp(dot)))` (`:367-369`). The derivative of
  `acos` is `-1/sqrt(1 - u²)` and is **unbounded** as `u → ±1` — the
  Jacobian blows up precisely at a parallel mate.
- `perpendicular`: `abs(90 - folded_angle)` (`:742`), where the fold
  `min(θ, 180-θ)` kinks at θ = 90° and the outer `abs` kinks at the same
  point — the perpendicular solution.

So `geom.solve` does **not** iterate on `measured`. It iterates on a signed
or vector reformulation per component, chosen so the residual is zero exactly
where `measured` is zero, smooth in a neighbourhood of that zero, and of
bounded derivative there. `measured` remains the reported number; the
reformulation is an implementation of the same measurement, and the gate
proves it is the same rather than asserting it.

| Component | Solver residual | Dim | Identity that recovers the engine's number |
|---|---|---|---|
| `coincident` gap | signed plane gap `dot(c_b − c_a, n_a)` — **no `abs`** | 1 | `abs(r) == measured` |
| `coincident` normals | `n_a + n_b` (zero exactly when opposed) | 3 | `2·degrees(asin(clamp(‖r‖/2)))  ==  normal_deviation_deg` |
| `concentric` offset | the radial-offset **vector** `p_b − foot`, expressed in the two axes of `a`'s perpendicular frame | 2 | `‖r‖ == measured` |
| `concentric` axes | `cross(axis_a, axis_b)` | 3 | `degrees(asin(clamp(‖r‖))) == axis_angle_deg` |
| `parallel` | `cross(d_a, d_b)` (zero for parallel *and* anti-parallel, which is what folding means) | 3 | `degrees(asin(clamp(‖r‖))) == measured` |
| `perpendicular` | `dot(d_a, d_b)` — signed, smooth everywhere, zero exactly at square | 1 | `degrees(asin(clamp(abs(r)))) == measured` |

Each identity holds for unit-normalised directions (`_unit`, `:360-365`,
already applied by `_plane_of` / `_cylinder_of` / `_direction_of`); `clamp`
is `max(-1, min(1, ·))`, the same guard `_angle_deg` applies at `:368`. Each
is a **gate clause**, asserted to 1e-9 on every fixture (Gates, G13B): if the
reformulation and the measurement ever disagree, the solver is optimising
something other than the constraint, and no amount of convergence would make
its answer evidence.

Two consequences, both normative:

- **The reformulated components are dimensionless where the engine's are
  degrees.** They are scaled into their measurement domain by the identity's
  leading factor (`180/π`, or `2·180/π` for the coincident normal pair)
  before §3.4's weights apply, so a weight declared in `deg` means what it
  says. The tolerance test is **never** applied to a reformulated component:
  tolerance is decided on the re-measured engine numbers by §7, which is the
  whole point of §7.
- **Analytic Jacobians (NW4) are Jacobians of the reformulation**, and are
  gated where the old formulation would have failed: finite-difference
  agreement is asserted at a point *within one declared tolerance of the
  solution*, not at a comfortable distance from it.

### 3.4 Weighting across units is a declared choice, never a default

A residual vector mixing mm and deg has no canonical norm. The precedent is
`COMPARE.md:34-36`: "Alignment is a declared choice, NEVER a silent
normalization." So:

- `weighting: "unit_scaled_v1" | "declared"` is **required** on every solve
  request; absent, `invalid_solve_request(undeclared_weighting)`.
- `unit_scaled_v1`: length residuals weight 1.0 per mm; angular residuals are
  multiplied by `characteristic_radius_mm * π / 180`, where
  `characteristic_radius_mm` is the maximum over free parts of the distance
  from the part's bounding-box centre to its bounding-box corner — so one
  degree of tilt costs what that tilt moves at the part's extremity. The
  computed radius is recorded in the result.
- `declared`: explicit `{"mm": w, "deg": w}` from the caller.
- **Class-predicate components carry their own weight**, not a share of the
  primary's. A `coincident` term contributes two weighted rows (one `mm`, one
  `deg`), a `concentric` term likewise; `parallel`, `perpendicular` and `fit`
  contribute one. Both class-predicate bounds are 1e-3 deg (§3.1), three
  orders tighter than a typical `tol_mm`, so folding them into one weight
  would let the tight bound dominate every step or vanish entirely depending
  on the declared numbers — which is exactly the silent normalization
  `COMPARE.md:34-36` forbids.
- Either way the applied weights are echoed in the proposal record, next to
  the residuals and per component, exactly as `ConstraintResidual.declared`
  echoes bounds (`geom/constraints.py:318-320`).

### 3.5 Regularisation is a declared choice too

`regularization: "min_norm_from_start"` is the only member in Stage 13 and is
still **required and echoed**, because §6 shows the Jacobian is rank-deficient
by construction and the choice of which null-space member to return is a
design decision, not a numerical detail. `min_norm_from_start` means: among
solutions within tolerance, return the one nearest the start iterate in the
weighted norm — "nearest to what the author already wrote", which is the only
choice that respects P4.

## 4. Solution method

### 4.1 Where it lives

- **`hephaestus.geom.solve`** — a **tenth pure geom service**, under the
  standing contract: pure functions over frames and numbers the caller
  already holds, no executor, store, project, or verdicts
  (`geom/constraints.py:6-18` states the contract; the boundary is
  mechanically enforced by the AST allowlist and import-closure test at
  `core/tests/test_geom_import_boundary.py:43-78`). It takes **extracted
  frames** — `PlanarFaceRecord` / `CylinderRecord` (`geom/topology.py:86-108`)
  — and declared bounds, and returns transforms, residuals, rank and
  null-space facts. It never sees a shape, which is why kernel-extremum kinds
  are structurally excluded from 2B (§3.2) rather than excluded by taste.
- **`hephaestus.core.placement`** — the engine half, mirroring the
  `constraints.py` ↔ `assembly.py` and `kinematics.py` ↔ `motion.py` split
  (`core/assembly.py:1-19`): anchor resolution through the shared
  `AnchorResolver` / `PartGeometry` pair (`core/assembly.py:476-573`, already
  reused by motion per `core/assembly.py:42-47`), the outcome vocabulary, the
  independent verification pass, and the proposal record.
- **`hephaestus.core.project_store.proposals`** — generational proposal
  state on the ledger pattern (`project_store/constraints.py:1-37`).

### 4.2 The iteration

Weighted Levenberg–Marquardt with a trust region, over the weighted residual
vector `r(x)` of §3:

1. **Frames once.** Anchors resolve once against current artifacts; the
   analytic kinds' records are transported under the candidate transform in
   closed form. No kernel call occurs inside a 2B iteration.
2. **Analytic Jacobian** of the §3.3 reformulation per objective component
   (NW3, NW4), assembled column-blocked by
   free variable.
3. **Rank and null space** by fixed-order Householder QR with column pivoting
   against a declared relative tolerance `RANK_TOL_REL`. If the smallest
   retained and largest discarded singular-value surrogates straddle the
   tolerance by less than `RANK_MARGIN_REL`, the solve is refused
   `rank_undecidable` — a guessed rank silently decides whether the answer is
   unique, which is the one thing §6 exists to prevent.
4. **Damped step**, clipped to the variable box (joint limits in 2A, `Param`
   bounds in 2C; 2B is unbounded unless the request declares a box).
   **Bounds are never clamped silently** — the refusal-never-clamp rule of
   `geom/kinematics.py:217-245` and `KINEMATICS.md:125` — a step that would
   leave the box is shortened to the boundary and the affected variables are
   reported in `bounds_active` / `limits_active` on the result, because a
   solution sitting on a bound is a boundary solution and not a stationary
   point.
5. **SO(3) validity.** Every accepted 2B iterate's rotation block is checked
   for orthonormality to `SO3_EPS` and re-projected; an iterate that cannot
   be re-projected within `SO3_REPROJECT_EPS` is the named refusal
   `non_rigid_iterate`, carrying the deviation. Nothing in the codebase
   checks this today (NW2), and a drifted iterate would produce a "transform"
   that is not a placement.
6. **Termination** on `‖weighted r‖∞ <= tol` **and** every objective
   constraint's reformulated class-predicate component inside its own
   declared bound (§3.1/§3.3) — the candidate-convergence test, which §7 then
   re-decides on the engine's `satisfied` — on `‖J^T W r‖ <=
   STATIONARITY_EPS` with residual above tolerance (over-constrained, §6), on
   the iteration ceiling, or on the wall clock (§10). The solver's
   termination test is a *candidate* test only: it never emits a verdict, and
   `‖weighted r‖∞ <= tol` alone was the earlier draft's mistake.

**No new dependency.** The linear algebra is fixed-order plain-float
arithmetic implemented in `geom.solve`. `numpy` is already a core dependency
(`core/pyproject.toml:7-17`) but its BLAS backend is threaded and
dispatch-dependent, which §9 shows would forfeit the one determinism tier
worth having; `scipy` is not a dependency and adding one is mission rule 7
territory (`mission_plan.md:823-827`). **The alternative that lost:
`scipy.optimize.least_squares`** — fewer lines, no reproducible digits, and a
new pinned dependency.

## 5. Initial guess, and its sensitivity

`zero: "as_built"` (`KINEMATICS.md:102-106`) makes the authored configuration
a genuinely good start: authored positions are near-solutions by discipline,
which is what makes a local method defensible and a global one unnecessary.
So `starts` defaults to the single start `as_built`.

But the interesting failures are exactly where that is false — a mate 20 mm
out because the author misread the spec puts the true solution outside the
local basin. Therefore:

- **Starts are declared and reported.** `starts` is a list; each entry is
  `as_built` or an explicit assignment. Every result names which start
  produced it (`from_start: "<id>"`), and non-convergence names **every**
  start tried.
- **No random restarts.** An RNG would break §9 and would let a rerun quietly
  change the answer. A caller who wants coverage declares more starts.
- **Sensitivity is reported, not assumed away.** When two or more declared
  starts converge to solutions differing by more than
  `SOLUTION_DISTINCT_EPS` (weighted norm), the verdict is
  `multiple_solutions_from_starts` (§6) and **all** of them are returned. The
  solver does not pick.
- **A local method's silence is never infeasibility.** The verdict name for
  failure is `no_placement_found_from_starts` — the
  `not_reached_at_samples` construction (`KINEMATICS.md:207-211`,
  `core/motion.py:1359-1378`) — and the spec forbids the spellings
  "infeasible", "impossible", and "no solution exists" anywhere in the
  result.

## 6. Convergence, non-convergence, multiplicity, and constraint count

### 6.1 The closed verdict set, stated once

Six spellings, and no others. For 2B and 2C:

1. **`converged_at_tolerance`** — never "solved". Three conjuncts, all
   required, all machine-checked:
   1. **every objective constraint re-measures `satisfied is True`** through
      the ordinary engine path (§7) — the class predicates of §3.1 included,
      which residual-within-tolerance does **not** imply for `coincident` or
      `concentric`;
   2. every weighted residual is within the declared tolerance as re-measured
      by §7;
   3. the Jacobian at the solution has full column rank at `RANK_TOL_REL`.

   Conjunct (i) is not redundant with (ii) and the spec is explicit about it
   because the earlier draft got this wrong: a zero-gap, same-facing
   `coincident` pair passes (ii) with room to spare and fails (i), and
   emitting a success verdict for it would contradict the `AssemblyStatus`
   row that still reads `violated` — P5 (§1.2), and the bench acceptance of
   §11 which grades on `satisfied` through the engine path. A solve meeting
   (ii) and (iii) but not (i) is **not** a success: it terminates
   `no_placement_found_from_starts` (verdict 4) carrying the unsatisfied
   constraint ids and their class-predicate values, because from that start
   the iteration genuinely did not reach a satisfying configuration.

   It is evidence about *this iterate from this start*, and it claims nothing
   about uniqueness beyond the local basin.
2. **`underdetermined_at_tolerance`** — conjuncts (i) and (ii) of verdict 1
   hold (every objective constraint re-measures `satisfied`, residuals within
   tolerance) but (iii) does not: the null space is non-trivial, the solution
   set is a positive-dimensional manifold, and one member is being shown.
   **This, not verdict 1, is where a single-kind 2B system lands** — a lone
   `coincident`, `concentric`, `parallel` or `perpendicular` pair is
   rank-deficient by construction, so no gate clause may demand a unique
   transform from one. Carries `dof_remaining` and a
   named basis of the free directions (translation along an axis, rotation
   about an axis, with the axis in world mm). **This is a distinct verdict,
   not a footnote on success**, because reporting one point of a continuum as
   *the* answer is a claim the mathematics does not support. Multiplicity is
   the norm here, not the exception: `concentric` leaves axial rotation *and*
   axial translation free, `coincident` leaves the whole in-plane `SE(2)`
   free, `parallel`/`perpendicular` fix two of three rotational DOF, `fit` is
   pose-invariant. A realistic 2B system is under-determined by construction.
3. **`multiple_solutions_from_starts`** — two or more declared starts
   converged to solutions separated by more than `SOLUTION_DISTINCT_EPS`.
   All are returned, ranked by weighted distance from `as_built`, none
   chosen. This is how *discrete* multiplicity surfaces — a bracket flipped
   180° about a bore satisfies `concentric` + `coincident` identically, and
   rank tells you nothing about it.
4. **`no_placement_found_from_starts`** — no declared start produced a
   configuration meeting verdict 1's conjuncts (i) and (ii), and no start
   reached stationarity. Two routes land here and the record says which: no
   start reached tolerance, or a start reached tolerance on the primary
   components while an objective constraint still re-measures
   `satisfied is False` — the class-predicate case of §3.1, whose unsatisfied
   ids and class-predicate values are carried explicitly, because "the gap is
   zero and it is still not a mate" is exactly the fact an author needs and
   the fact a residual number hides. Carries every start, the best iterate
   per start, and its independently re-measured per-constraint residuals.
   **Never "infeasible"** (§5).
5. **`overconstrained_at_residual_floor`** — a start reached a stationary
   point (`‖J^T W r‖ <= STATIONARITY_EPS`) whose weighted residual exceeds
   tolerance, with full column rank: the declared constraints disagree with
   each other over the declared free variables. Carries the per-constraint
   residuals at the floor and the floor value. It names **no culprit
   constraint**: identifying a minimal inconsistent subset is a different
   computation nobody has run, and naming one on a whim would be a verdict
   about the author's intent. It also does not claim global infeasibility —
   only that this start's basin has none.
6. **`unresolvable(reason)`** — reuse of
   `core/assembly.py:120-171`'s `UNRESOLVABLE_REASONS` verbatim, same
   failure/same fix/same name, exactly as `core/motion.py:225-249` already
   does, plus the Stage 13 additions named in §6.3.

For 2A the same six apply with pose spellings, plus one asymmetry taken
straight from `KINEMATICS.md:201-214`: an anchor-to-point target is an
**existence** claim, so a verified achieving assignment is proof, and its
success spelling is `pose_found`, with failure `no_pose_found_from_starts`.

### 6.2 Over- and under-constrained, each named

- **Under-constrained** → verdict 2 (`underdetermined_at_tolerance`), always
  with `dof_remaining` and the direction basis. Never reported as
  `converged_at_tolerance`.
- **Over-constrained but consistent** (more equations than DOF, residuals
  still within tolerance) → verdict 1. Full rank; nothing to report beyond
  the residuals.
- **Over-constrained and inconsistent** → verdict 5
  (`overconstrained_at_residual_floor`).
- **Rank not decidable** → refusal `rank_undecidable` (§4.2, step 3), which
  is not a verdict.

### 6.3 Refusals are not verdicts

`MotionTimeout` is "deliberately NOT a `SWEEP_VERDICTS` member: a killed
sweep decided nothing, and giving the kill a verdict spelling would let a
timeout be read as an outcome" (`core/motion.py:1489-1498`). Stage 13 copies
that rule exactly. The refusal set, closed, none of them a verdict:

**Request-time** (`invalid_solve_request(reason)`, nothing written):
`no_free_variables`, `no_ground_part`, `free_part_is_jointed`,
`free_part_in_no_constraint`, `undeclared_weighting`,
`undeclared_regularization`, `not_an_objective_kind(plateau|kernel_extremum|
pose_invariant)`, `pose_bound_constraint_in_transform_space`,
`unknown_constraint`, `withdrawn_constraint`, `unknown_param`,
`unbounded_param`, `unknown_joint`, `missing_provenance`,
`tolerance_below_determinism_floor` (a declared tolerance tighter than 1e-9,
the number G8C's determinism clause asserts two processes agree to —
`ASSEMBLY.md:134-135`).

**Resolution-time** (`unresolvable(reason)`): the nine
`UNRESOLVABLE_REASONS` of `core/assembly.py:161-171`, plus
`stale_proposal_inputs` (§8) and `no_free_variable_affects` (§2C).

**Run-time** (named refusals carrying the best iterate and its independently
re-measured residuals): `solver_timeout`, `iteration_ceiling`,
`build_budget_exhausted` (2C), `unbuildable_parameter_iterate` (2C — a
candidate whose preview build failed, carrying the build error),
`non_rigid_iterate`, `rank_undecidable`, and — the one that matters most —
`solver_residual_disagreement` (§7).

**Two notes on closure, because a closed vocabulary that omits a member it
elsewhere asserts is not closed.**

- `tolerance_below_determinism_floor` was spelled
  `tolerance_below_measurement_floor` in the earlier draft, and the rename is
  deliberate. 1e-9 is a *determinism* floor: it is what two processes in the
  pinned image are gated to agree to (`ASSEMBLY.md:134-135`), and nothing in
  this repo has ever measured the kernel's accuracy against ground truth.
  Calling it a measurement floor would claim a number nobody computed, and
  attach that claim to the one epsilon a reader is most likely to trust. A
  genuine measurement floor — an accuracy bound on `evaluate_residual`
  against analytically known geometry — does not exist here and Stage 13 does
  not add one (§12); if one is ever wanted it enters by mission rule 5, as
  its own gated stage with its own measurements, never by renaming this
  constant back.
- **`no_writeback_grammar` is not in any of the three lists, and that is the
  correction, not the omission.** The earlier draft asserted it as a refusal
  name in §0, §8 and a gate clause while never listing it here. It is also
  unreachable as written: `propose_placement`'s declared inputs (§11) have no
  field through which a `suggested_edit` could be requested, and every tool
  input schema in this repo is `additionalProperties: false` (53 of 53 —
  `set_params.schema.json:6`, `read_part.schema.json:6`,
  `compare_solids.schema.json:6`), so an extra field is rejected by JSON
  Schema validation before dispatch and produces a schema error, never a
  named Stage 13 refusal. The guarantee is kept and made *stronger* by moving
  it from a runtime name to a schema fact: §8 asserts structurally that no
  proposal record carries source text or a `suggested_edit` field, and the
  gate asserts the proposal document schema is `additionalProperties: false`
  and the tool input schemas are too. A refusal nobody can trigger is not a
  safeguard; a schema that cannot express the field is.

## 7. Independent verification: why the answer is believed

**A solved placement is never trusted because the solver said so.** This
section is the mechanical reason §1's amendment is safe, and every clause of
it is a gate clause.

1. **A separate process.** Verification runs in a fresh subprocess whose only
   input is the serialised proposal document — transforms (or parameter
   values), the bound artifact refs, the constraint generation — and the
   project store. It does not import `geom.solve`, proven by an
   import-closure assertion in the same style as
   `core/tests/test_geom_import_boundary.py:64-78`. A solver bug therefore
   cannot reach the number that is reported.
2. **The existing evaluator, unmodified.** Verification calls
   `hephaestus.core.assembly`'s evaluator over shapes placed by
   `geom.kinematics.transformed_shape` (`geom/kinematics.py:763-782` — a
   placed copy, never a mutation), which dispatches to
   `geom.constraints.evaluate_residual` (`geom/constraints.py:822`). It is
   the same code path that produces a real `AssemblyStatus`, and in 2C it is
   literally a preview build followed by the ordinary evaluation.
3. **All eight kinds, not the four that steered.** The plateau and
   pose-invariant kinds excluded from the objective (§3.2) are *evaluated*
   here. A proposal that satisfies four mates and drives two parts into each
   other is reported with `no_interference` violated at the solution — which
   is the honest answer and the reason those kinds are not silently dropped.
4. **`satisfied` is what the verdict is read from — not the residual
   number.** For each objective constraint the pass reads the whole
   re-measured `ConstraintResidual`: `measured`, `slack`, every entry of
   `values`, and `satisfied` (`geom/constraints.py:320-329`). Verdict 1
   requires `satisfied is True` on every one of them (§6.1). This is the
   clause that closes the gap §7.5 alone cannot: a same-facing `coincident`
   pair has a genuinely zero gap, so the solver's number and the kernel's
   number **agree perfectly** and the disagreement check below passes — the
   only thing that catches it is reading the predicate the kernel already
   evaluated. Every class-predicate value (`normal_deviation_deg`,
   `axis_angle_deg`) is recorded in the proposal beside its declared bound,
   so a reader can see which conjunct failed rather than inferring it.
5. **The solver's own numbers are discarded.** The proposal record carries the
   re-measured residuals. The solver's internal residuals are retained only
   for the disagreement check and are never the reported figure.
6. **Disagreement is fatal, not a warning.** If any re-measured residual
   differs from the solver's internal value by more than `VERIFY_EPS`, the
   whole result is refused `solver_residual_disagreement`, naming the
   constraint id and both numbers. No verdict is emitted. A solver whose
   model of the geometry has drifted from the kernel's is not producing
   evidence, and reporting its answer with a caveat would be exactly the
   overclaim this project's vocabulary exists to prevent. The comparison is
   per *component*, over the identities of §3.3: the reformulated residual is
   mapped back into the measurement domain and compared against `measured`
   and against each class-predicate value, so a reformulation bug is caught
   here and not absorbed.
7. **The `AssemblyStatus` row is untouched.** Verification produces facts
   about a *hypothetical* configuration. It does not write, project, or
   invalidate assembly status. The row keeps saying `violated`.

## 8. The proposal record: provenance, staleness, and what it may never do

A proposal is an immutable content-addressed document,
`artifact:placement-proposal:sha256:…`, in generational state on the ledger
pattern (`project_store/constraints.py:1-37`). It binds, compulsorily:

- every source part's `artifact_ref` at solve time;
- the constraint-set generation, and the joint/pose/coupling generations for
  2A;
- the full request: space, free set, ground set, starts, weighting (with the
  computed `characteristic_radius_mm`), regularisation, tolerance, iteration
  ceiling, budgets;
- the toolchain hash and the `geom.solve` version;
- **provenance on the 8C taxonomy** — a requirement id, or `assumed` with a
  reason (`ASSEMBLY.md:52-54`). A solve is an interpretation of intent for
  the same reason a constraint is;
- the verdict, the independently re-measured per-constraint residuals (§7) —
  `measured`, `slack`, `satisfied`, and every `values` entry, each beside the
  bound it was tested against, so a reader never has to re-derive
  satisfaction from a number — `dof_remaining` and the null-space basis where
  applicable, `bounds_active` / `limits_active`, `nonsmooth_terms`,
  iterations used, and `from_start`;
- the `solver_core` and `verification` blocks with their per-block
  `determinism_tier` (§9).

**The document schema is `additionalProperties: false`.** This is not a
stylistic choice: it is the mechanism by which "carries no source text" below
is a structural fact rather than a promise, and it is asserted as a gate
clause. Note that this deviates from the repo's *tool result* convention,
where all 53 result schemas are `additionalProperties: true` — the proposal
is a content-addressed artifact document, not a tool result, and an artifact
whose shape is open cannot be a closed vocabulary.

**Staleness.** A proposal whose bound artifact refs no longer match the parts'
current refs is reported `stale: true` at read, naming which refs changed —
the `AssemblyProjection` staleness rule (`core/assembly.py:988-1000`) applied
by comparison at read time rather than by a stored projection.
**DECISION**: no new `ProjectionState` field. Proposals are immutable and
their inputs are already bound, so freshness is a pure function of the
current refs; adding a projection field would be a second, cache-shaped copy
of a fact that can be recomputed exactly. *The alternative that lost:* a
`SolveProjection` on the Stage 9 motion-projection precedent
(`KINEMATICS.md:140-147`) — better when status is expensive to recompute,
which this is not.

**What a proposal may never do**, each a gate clause:

- **It is never a verdict.** No tool accepts a proposal id where a constraint
  verdict is expected; the reviewer receives proposals labeled as
  computations, and `VALIDATION.md:308-312`'s rule — verdicts stamped from
  the engine, none solicited, none accepted — is unchanged.
- **It never clears anything.** The dimension-findings clearing rule verbatim
  (`VALIDATION.md:254-266`): a violated constraint clears in exactly two ways
  — a later successful build of the same part that measures otherwise, or an
  explicit operator dismissal — and there is **no model-facing write** that
  clears one.
- **It carries no source text.** The record names the part and the transform,
  decomposed into translation (mm) plus axis-angle (axis, degrees) for human
  legibility, and says nothing about which statement to edit. §0 gives the
  reason. The absence is **structural, not a refusal**: the proposal document
  schema is `additionalProperties: false` above, so no `suggested_edit` field
  can be emitted, and every tool input schema is `additionalProperties: false`
  (53 of 53), so none can be requested — an extra field is a JSON Schema
  rejection before dispatch. The earlier draft named a refusal
  (`no_writeback_grammar`) for a request the tool grammar cannot express;
  §6.3 records why that name was removed rather than kept as decoration.
- **It is never an input to a build.** Not in `input_hashes`, not readable
  from a part script, not readable from `CHECKS` (§12).

## 9. Determinism, honestly tiered

The gates already demand cross-process identity to 1e-9
(`ASSEMBLY.md:134-135`), and this repo has already been bitten by
environment-dependent float output — goldens had to be re-baselined *inside
the pinned CI image* (commits `148075f`, `f3a4d42`; the pinned-image policy
is `verification.md:68-73`). Iterative solving makes that harder, so the
claim is split.

**The tier is a property of a BLOCK, not of a solve.** The earlier draft
tiered whole solves and immediately contradicted itself: it defined D1 for
transform-space solves only, put every 2A solve in D2, and then gated a pose
solve at D1 — a byte-identity claim about digits that come out of kernel
anchor resolution, which is the one thing this section exists to refuse. The
correct seam is not 2A-versus-2B; it is **kernel-touched versus not**, and
that seam runs *through* every solve, so the record carries two blocks and
each states its own tier.

- **`solver_core`** — the extracted frames the iteration consumed, the
  request, the returned iterate (joint assignment in 2A, transform rows in
  2B, parameter values in 2C), rank, `dof_remaining`, the null-space basis,
  `from_start`, iterations used.
- **`verification`** — everything §7 measured: the re-measured
  `ConstraintResidual` per constraint, `satisfied`, the class-predicate
  values, the plateau kinds' outcomes.

**Tier D1 — bit-reproducible, gated on the digits, and available only to
`solver_core`.** A solve whose iteration is kernel-free — 2A, and 2B when
every objective term is analytic (§3.2) — extracts frames once and then does
nothing but fixed-order plain-float arithmetic in `geom.solve` (§4.2).
**Given identical extracted frames**, an identical request, and the pinned
image, `solver_core` is byte-identical across processes, and the gate asserts
byte equality of its canonical JSON minus timestamps. The frames are inside
the block, not upstream of it, precisely because the claim is conditional on
them: frame extraction is a kernel call and is *not* claimed bit-stable, so a
reader comparing two `solver_core` blocks can see whether the condition held
instead of taking it on faith. Two runs whose recorded frames differ are
D2-comparable only, and the gate asserts frame equality as an explicit
precondition rather than assuming it. This is why no BLAS and no RNG are
permitted anywhere in the iteration.

**Tier D2 — not bit-reproducible, and the spec says so.** Three cases, and
the first is unconditional: **every `verification` block is D2**, in every
space including 2A, because it is kernel measurement; a 2C `solver_core` is
D2 as well (each iterate is a preview build, and OCP boolean output is not
claimed bit-stable across environments); and any `solver_core` whose recorded
frames differ from the comparison run's is D2 by the condition above. For
these the spec claims **no** stability of the returned digits. What is
reproducible, and what the gate binds to:

1. the **verdict spelling** — identical across processes;
2. the **independently re-measured residuals** (§7) — identical to within the
   declared tolerance, on the same side of it, and with identical `satisfied`
   flags (a run that flips `satisfied` has flipped the answer, tolerance or
   no tolerance);
3. the **set of active bounds/limits** and `dof_remaining`;
4. the proposal's **bound input refs** — identical, so two runs are provably
   about the same geometry.

Iteration counts, step sizes, and the returned digits themselves are
explicitly **not** gated in D2. `determinism_tier` is recorded **per block** —
`solver_core.determinism_tier ∈ {D1, D2}`, `verification.determinism_tier`
always `"D2"` — so a reader never has to infer which claim applies to which
number, and the gates assert in both directions: no `verification` block ever
claims D1, and no 2C `solver_core` does either. A `solver_trace_ref`
(iterates, damping, residual norms) is stored for replay and is evidence
about a run, never about the design.

## 10. Bounded execution

`COMPARE.md:105-129` is the pattern, and its measurement is the warning: a
single boolean ground for ~19 h on a pathological B-rep, and five of six
live-run infrastructure deaths ended on an unanswered `compare_solids`. The
Stage 13 sharpening is that **the ceiling must be per iteration, not only per
solve**, because a solve is an unbounded number of kernel evaluations.

- 2B iterations touch no kernel, so a 2B solve is bounded by
  `SOLVE_ITER_MAX` plus `SOLVE_TIMEOUT_S` (named constants,
  env-overridable on the local-floor pattern, as
  `MOTION_TIMEOUT_S` / `motion_timeout_s()` at `core/motion.py:1434-1447`).
- Every §7 verification pass — which *does* touch the kernel — runs in the
  killable subprocess under `VERIFY_TIMEOUT_S`, per pass.
- 2C additionally carries `SOLVE_BUILD_BUDGET`, a cap on **total preview
  builds** across the whole solve (each finite-difference gradient costs
  `1 + n`), and each build runs under the executor's existing bounds. Budget
  exhaustion is `build_budget_exhausted`, carrying the best iterate and its
  verified residuals.
- Every ceiling returns a **named refusal carrying partial evidence** —
  never a hang, never a silent pass, never a verdict (`core/motion.py:
  1489-1498`).
- Inside a `CHECKS` predicate: nothing. There is no solver surface in
  `CHECKS` (§12), so this class of timeout cannot reach a check report.

## 11. Surface

**Model tools: +3 (53 → 56).** Tool count is a design constraint at this
size: each tool costs five generated, drift-tested artifacts, a per-profile
decision, dispatch tests on both profiles, and a `tool_schema.md` heading
under one drift gate (`contract/tests/test_toolgen.py:98-110`,
`tests/stage2/test_g2_contract_drift.py:354`). The 8A/8B lever applies — put
the capability in the script or an existing enum, not on the surface — so
2C is an **enum value on an existing tool**, not a fourth tool.

- `solve_pose(targets, free_joints?, starts?, tol, weighting, regularization,
  provenance, ceiling?)` → pose verdict + solved assignment + verified
  residuals. **Part and orchestrator profiles**, on the 8C quartet rationale
  (`ASSEMBLY.md:87-94`): cheap, reversible, and measured against geometry the
  model did not choose.
- `propose_placement(space: "transform"|"parameters", constraints, free,
  ground?, starts?, weighting, regularization, tol, provenance, budgets?)`
  → proposal ref + verdict + verified residuals. **Orchestrator profile
  only**: it reasons across parts and spends a project-scoped build budget,
  the same rationale that makes project-scoped `set_params` and `run_checks`
  orchestrator-only (`tool_schema.md:126-132`). `space: "parameters"` is the
  13C enum extension — the `layout="nested_sheet"` precedent
  (`tool_schema.md:1258-1284`), a schema amendment rather than a new tool.
- `read_proposals(ids?)` → entries + verdicts + staleness, **withdrawn
  generations included with their reasons** (the 8C read-tool shape:
  generational state is honest only if every generation stays readable,
  `KINEMATICS.md:275-280`). Both profiles.

**Operator CLI**: `heph solve pose|placement|params` and `heph proposals`
(table + `--json`), on the `heph assembly` / `heph motion` shape.

**Ladder integration** (`VALIDATION.md` §5): the termination reviewer
receives open proposals as labeled non-evidence, alongside the unchanged
`AssemblyStatus`. A violated constraint with a `converged_at_tolerance`
proposal against it is **still a blocking finding** — the proposal is a
suggestion nobody has acted on. No new blocking rule is added: Stage 13
introduces no new failure the reviewer must judge.

**Bench** (13C): a new `solve-*` task family. Acceptance is graded on the
**rebuilt part**, never on the proposal: a `proposal_requirements` entry names
constraint ids that must measure `satisfied` through the ordinary engine path
after the agent has applied a proposal by authoring it. That is the
closed-loop break made mechanical — a run cannot pass by producing a good
proposal, only by delivering geometry. Per `VALIDATION.md` §1 as restated by
G9C (`KINEMATICS.md:386-399`): **solve-prose and solve-seeded are each their
own split, each baselined on its own first measurement with the reference
model at ≥3 seeds, neither compared against nor averaged into the v1/v2/v3
baselines**; `aggregate_threshold` keys on coverage
(`bench/src/hephaestus/bench/scoring.py:117-128`), so the new family is
invisible to existing bars until its own coverage constant and threshold
land, and re-baselining any combined bar is its own future amendment. Each
task ships prose + seeded variants, dual independent solutions, and
hand-counted budgets (`VALIDATION.md:58-98`).

## 12. What deliberately does NOT change

No script syntax: parts declare no solve, `PARAMS`/`hc` are untouched, no new
`part.*` field. **No `CHECKS` surface** — the measurement facade gains
nothing, in either scope; a predicate that could read a proposal would let an
acceptance check pass on a computation instead of on geometry, which is
`VALIDATION.md:58-60` inverted. No new persistence beyond the ledger-pattern
proposal set (no `ProjectionState` field, §8). No change to `AssemblyStatus`,
`MotionStatus`, or any wire shape either produces — 8C and Stage 9 evidence
stays byte-for-byte valid. No change to `check_assembly` or `check_motion`
semantics. No change to `edit_part` / `write_part` / `set_params`: no force
overwrite appears, and no tool applies a proposal. No change to export —
`as_built` is still what a script built, never a proposed placement. No
dynamics, loads, FEA, or motor sizing (`mission_plan.md:815-817`). No new
runtime dependency (§4.2). **No measurement floor**: Stage 13 does not
measure `evaluate_residual`'s accuracy against analytically known geometry
and does not claim one exists; the only 1e-9 in this document is the
determinism floor G8C already asserts (§6.3), and every gate clause that
names 1e-9 names a pure-function claim, never a solved quantity. No new
sandbox profile: nothing here shells out to
an external binary, so the executor seam (`core/src/hephaestus/core/executor/`)
is untouched — a future external solver binary would re-engage mission rules
6 and 7 and is out of scope. No global optimisation, no random restarts, no
mesh path, no feature recognition. Ball, planar and gear joints remain absent
(`KINEMATICS.md:99-101`), so 2A's variable set is the Stage 9 kind set.

## 13. NAMED NEW WORK

Nothing in this list exists today. Anything not listed here is a claim that it
already exists.

**Mathematics and `geom.solve` (the tenth pure service)**

1. **Transform → parameters** — a log map / rigid decomposition
   (translation + axis-angle) for reporting and for `min_norm_from_start`.
   `geom/kinematics.py` is forward-only (`:491-556`); there is no inverse.
2. **`SO(3)` validity and re-projection** — orthonormality check to
   `SO3_EPS`, re-projection, and the `non_rigid_iterate` refusal. Nothing in
   the repo checks a `RigidTransform`'s rotation block today
   (`geom/kinematics.py:423-448` is a raw 3×4 dataclass).
3. **The residual reformulation of §3.3 and its identities** — the signed
   plane gap, the radial-offset vector in the axis's perpendicular frame, the
   normal-sum vector, and the two cross/dot angular forms, each with the
   closed-form map back into the engine's measurement domain. None of these
   exist: `geom/constraints.py` computes the `abs`/`acos`/norm forms and
   nothing else.
4. **Analytic Jacobians of the reformulation** (not of `measured`) for
   `coincident`, `concentric`, `parallel`, `perpendicular` with respect to
   `SE(3)` — including the class-predicate rows, which are new objective
   components, not existing ones — and the closed-form transport of
   `PlanarFaceRecord` / `CylinderRecord` under a candidate transform
   (`geom/topology.py:86-108` records exist; transporting them does not).
5. **Weighted residual assembly** across mm/mm³/deg, per *component* rather
   than per constraint (§3.4), with the `unit_scaled_v1` characteristic-radius
   computation and the `declared` mode.
6. **Fixed-order Householder QR with column pivoting**, rank determination
   against `RANK_TOL_REL`, and the `rank_undecidable` straddle refusal.
7. **Null-space basis extraction and naming** — turning basis vectors into
   human-readable free directions ("translation along [0,0,1] through
   (12.0, 0.0, 4.5)").
8. **Damped least squares with a trust region**, `min_norm_from_start`
   regularisation, and the box-clipping step with `bounds_active` /
   `limits_active` reporting (no clamping — `geom/kinematics.py:217-245`).
9. **Stationarity detection** (`‖J^T W r‖`) to distinguish verdict 5 from
   verdict 4.
10. **Solution-distinctness comparison** in the weighted norm
    (`SOLUTION_DISTINCT_EPS`) for `multiple_solutions_from_starts`.
11. **Finite-difference driver for 2C**, including the per-constraint
    sensitivity test that produces `no_free_variable_affects`.

**Engine (`hephaestus.core.placement`)**

12. **The solve-request grammar and its request-time refusal set** (§6.3),
    including `free_part_is_jointed`,
    `pose_bound_constraint_in_transform_space`,
    `not_an_objective_kind(reason)`, and
    `tolerance_below_determinism_floor`.
13. **Ground/free-set semantics** — parts partitioned into free and ground,
    `no_ground_part`.
14. **The frame-extraction-once pipeline** over the shared `AnchorResolver` /
    `PartGeometry` (`core/assembly.py:476-573`), producing the analytic
    records `geom.solve` consumes.
15. **The independent verification pass** (§7): separate process, its
    import-closure assertion, the all-eight-kinds evaluation, the
    **satisfaction read** (`ConstraintResidual.satisfied` plus every
    class-predicate `values` entry beside its declared bound, §7.4), the
    per-component disagreement comparison over the §3.3 identities, and the
    `solver_residual_disagreement` refusal.
16. **The verdict and refusal vocabularies** (§6), and the pose-space variant
    with `pose_found` / `no_pose_found_from_starts`.
17. **Bounded execution**: `SOLVE_ITER_MAX`, `SOLVE_TIMEOUT_S`,
    `VERIFY_TIMEOUT_S`, `SOLVE_BUILD_BUDGET`, each env-overridable on the
    local-floor pattern, with partial-evidence refusals.
18. **The 2C preview-build driver** — issuing transient-override builds,
    reading residuals through the ordinary evaluation, and
    `unbuildable_parameter_iterate`.
19. **Per-block determinism tiering** (§9): the `solver_core` /
    `verification` split of the proposal document, the recorded extracted
    frames that make the D1 claim conditional and checkable, per-block
    `determinism_tier`, and the `solver_trace_ref` trace record.

**Store, surface, evidence**

20. **`project_store.proposals`** — generational proposal state, the
    `artifact:placement-proposal:sha256:…` document, its
    `additionalProperties: false` JSON Schema (§8 — a deviation from the tool
    result convention, deliberate and gated), canonical JSON serialisation,
    and GC edges keeping a stale proposal readable.
21. **Read-time staleness** by comparing bound refs to current refs (§8).
22. **Three tools** (`solve_pose`, `propose_placement`, `read_proposals`),
    their five generated artifacts each, profile rows, dispatch tests, and
    the repointed 53 → 56 pins (`contract/tests/test_toolgen.py:98-110`,
    `tests/stage2/test_g2_contract_drift.py:354`).
23. **CLI**: `heph solve pose|placement|params`, `heph proposals`, human and
    `--json`.
24. **Reviewer context extension**: proposals delivered as labeled
    non-evidence, with the proof that they clear nothing.
25. **Geom boundary admission**: `solve` added to the AST allowlist and
    import-closure suites (`core/tests/test_geom_import_boundary.py:43-78`).
26. **Hand-computable fixtures** for every analytic Jacobian and for each
    verdict — including a deliberately under-determined system with a known
    null-space dimension, a flipped-bracket discrete-multiplicity fixture, a
    provably inconsistent over-constrained fixture, a **full-column-rank**
    fixture per analytic kind (a lone mate of any of the four kinds is
    rank-deficient by construction, §6.1 verdict 2, so a unique hand-computed
    transform does not exist for one), and a **zero-gap same-facing
    `coincident`** fixture for the class-predicate clause. With them, the two
    gate-only constants `TRANSFORM_MATCH_EPS` (§ Gates) and the recorded
    per-fixture conditioning number they are derived from.
27. **The `tool_schema.md` / `ASSEMBLY.md` sub-stage drift gate** — asserting
    at the sub-stage that adds a heading, not one later, that no un-scoped
    "There is no solver." survives alongside a `solve_pose` heading and that
    every declared tool name has a normative heading (the
    `tests/stage2/test_g2_contract_drift.py:270-305` shape, re-run at 13A).
28. **Bench**: the `solve-*` family, its `proposal_requirements` acceptance
    vocabulary and grader half, its coverage constant and its own splits, and
    dual independent solutions per task.
29. **The `mission_plan.md` Stage 13 amendment itself**, and the six document
    amendments of the manifest.

## Gates

Stage 13 lands in three gated sub-stages, strictly ordered. Every clause below
is a pytest assertion; a clause that cannot be written as one is a defect in
this document to be fixed by tightening it, never by waiving it (mission rule
1, `mission_plan.md:801-804`).

**Two epsilons exist only for these gates, and they exist because an earlier
draft demanded 1e-9 of quantities no part of this spec drives to 1e-9.** A
gate clause may assert 1e-9 of a **pure function evaluated at fixed given
inputs** — `forward_kinematics` at declared joint values, a §3.3 identity —
because that is arithmetic with no iteration in it, and it is the claim
`ASSEMBLY.md:134-135` and `KINEMATICS.md:345-347` already make. A gate clause may
**never** assert 1e-9 of a *solved* quantity: the solver terminates on the
declared tolerance (§4.2 step 6), a tolerance tighter than 1e-9 is refused
`tolerance_below_determinism_floor` (§6.3), and demanding accuracy a
termination rule cannot deliver is a clause nobody can write — the defect
mission rule 1 says to fix by tightening, which is what these two constants
do.

- **`TRANSFORM_MATCH_EPS`** — how far a returned transform may sit from a
  hand-computed one. Per fixture: `tol * TRANSFORM_MATCH_FACTOR * kappa`,
  where `kappa` is that fixture's condition number of the weighted Jacobian
  at the solution, recorded in the fixture beside its hand-computed answer,
  and `TRANSFORM_MATCH_FACTOR` is a declared constant. Residual accuracy and
  *solution* accuracy are different quantities related by the conditioning,
  and the gate says which one it is asserting.
- **`JACOBIAN_FD_EPS`** — relative agreement between an analytic Jacobian
  column and a central finite difference of the same reformulated residual.

### Gate G13A — pose solving

`uv run pytest tests/stage13a -q` exits 0, covering:

1. **Forward kinematics, as a pure function.** `forward_kinematics` at
   *fixed given* joint values reproduces the hand-computed transform of a
   two-revolute chain to **1e-9**, with no solver anywhere in the call — the
   G9A clause shape (`KINEMATICS.md:345-347`) restated so this suite owns it.
   This is the only 1e-9 in G13A and it is a claim about arithmetic.
2. **Inverse kinematics, as a solve.** On that same chain: the verdict is
   `pose_found`, and the target error **re-measured by §7 through
   `core.motion`'s resolution path** is `<= tol` — the declared tolerance,
   which is the number the solver actually drove. The clause asserts `<=
   tol`, never 1e-9, and asserts that the record reports the re-measured
   error rather than the solver's internal one.
3. `pose_found` asserted verbatim as the success spelling; the strings
   "solved", "infeasible" and "holds" appear nowhere in any result payload.
4. `no_pose_found_from_starts` on an out-of-reach target, carrying every
   declared start and the closest miss distance — and **not** spelled
   `violated`.
5. A redundant chain (3 joints, 2-DOF target) returns
   `pose_underdetermined_at_tolerance` with `dof_remaining == 1` and a named
   direction basis.
6. Two declared starts converging to elbow-up and elbow-down return
   `multiple_poses_from_starts` with both assignments, ranked by distance
   from `as_built`, and neither marked chosen.
7. A target reachable only past a declared limit returns
   `no_pose_found_from_starts` with the limiting joint in `limits_active`;
   the returned assignment is inside limits and no value is clamped
   (`geom/kinematics.py:217-245`).
8. Every request-time refusal in §6.3 reachable from pose space fires by
   name with nothing written: `no_free_variables`, `unknown_joint`,
   `missing_provenance`, `undeclared_weighting`, `undeclared_regularization`,
   `tolerance_below_determinism_floor` — the last on a request declaring
   `tol` below 1e-9, with the superseded spelling
   `tolerance_below_measurement_floor` asserted absent from the source tree
   and from every payload.
9. `rank_undecidable` on a fixture constructed to straddle `RANK_TOL_REL`.
10. Independent verification: the solved assignment's target error is
    re-measured through `core.motion`'s resolution path in a separate
    process; an injected solver-side residual error produces
    `solver_residual_disagreement` and **no verdict**.
11. Import-closure assertion: the verification process's closure excludes
    `hephaestus.geom.solve`.
12. `solver_timeout` and `iteration_ceiling` are named refusals carrying the
    best iterate and its verified residuals, and are absent from the verdict
    set (asserted against the literal verdict tuple).
13. **Determinism, per block (§9), and the negative in both directions.** Two
    processes solve the same request. The recorded extracted frames are
    asserted **equal** first, as the explicit precondition of the D1 claim;
    then `solver_core` is byte-identical as canonical JSON minus timestamps,
    and `solver_core.determinism_tier == "D1"`. The `verification` block is
    **not** byte-compared: it is held to the four D2 bindings of §9 —
    identical verdict spelling, re-measured residuals within tolerance and on
    the same side of it with identical `satisfied` flags, identical
    `limits_active` and `dof_remaining`, identical bound input refs — and
    carries `determinism_tier == "D2"`. The test asserts that **no**
    `verification` block in any record claims `"D1"`, so the negative
    assertion lands with the first record that carries a tier rather than two
    sub-stages later.
14. **Amendment drift, asserted at the sub-stage that ships the heading.**
    With 13A's amendments landed: `tool_schema.md` contains a `solve_pose`
    heading **and** no un-scoped sentence "There is no solver." (the
    `check_assembly` occurrence at `tool_schema.md:815` now reads the amended
    `ASSEMBLY.md` §1 wording); every name in `TOOL_NAMES` has a matching
    normative heading with a parseable signature block (the
    `tests/stage2/test_g2_contract_drift.py:270-305` shape, re-run here);
    `ASSEMBLY.md` §1's last bullet is titled `NO SOLVER MOVES GEOMETRY` and
    carries the amended text verbatim; `KINEMATICS.md` §0's first bullet
    carries the Stage 13 sentence. A passing G13A therefore cannot leave a
    normative document contradicting the machinery the same sub-stage
    shipped.
15. `solve_pose` through dispatch on both profiles; the solved assignment is
    returned and **no pose is declared** as a side effect (pose-set
    generation unchanged).
16. `heph solve pose` human and `--json`.
17. Existing suites stay green; `tests/stage9a`–`stage9c` unchanged; the geom
    boundary suites admit `solve` as a pure service.

### Gate G13B — placement proposal, transform space

`uv run pytest tests/stage13b -q` exits 0, covering:

18. **Each analytic objective kind on a FULL-COLUMN-RANK fixture.** For
    `coincident`, `concentric`, `parallel`, `perpendicular`: a fixture built
    from the kind under test plus enough further analytic constraints to
    remove the null space entirely, so a unique answer exists to hand-compute
    at all. The clause asserts, in order: the rank at the solution is full
    (asserted explicitly, not inferred from the verdict); the verdict is
    `converged_at_tolerance`; **`satisfied is True` for every objective
    constraint** as re-measured by §7, class predicates included; the
    verified residual is `<= tol`; and the returned transform matches the
    hand-computed one to `TRANSFORM_MATCH_EPS`, with the fixture's recorded
    `kappa`. A lone mate of any of these four kinds is rank-deficient by
    construction (§6.1 verdict 2) and is asserted in clause 23 instead — no
    clause anywhere demands a unique transform from a positive-dimensional
    solution set.
19. **The reformulation is the same measurement, and its Jacobian is right
    where it matters (§3.3).** For every fixture and every objective
    component: the reformulated residual mapped back through its stated
    identity reproduces the engine's `measured` or class-predicate value to
    **1e-9** — a pure-function claim over fixed inputs, the only kind of 1e-9
    this gate permits. And: each analytic Jacobian column agrees with a
    central finite difference of the same reformulated residual to
    `JACOBIAN_FD_EPS`, evaluated at a point **within one declared tolerance
    of the solution** — the neighbourhood where the `abs` / `acos` / norm
    forms of `geom/constraints.py` are non-smooth or unbounded, and therefore
    the neighbourhood where a clause evaluated at a comfortable distance
    would have proved nothing.
20. **A class predicate is not a footnote: the negative fixture.** A
    `coincident` pair whose gap is exactly zero with **same-facing** normals
    does **not** return `converged_at_tolerance`. The record shows
    `satisfied == False`, `normal_deviation_deg` near 180, and the declared
    `normal_eps_deg` beside it; the verdict is `no_placement_found_from_starts`
    when no free DOF can flip the part. The mirror positive is asserted in the
    same test: given a free rotational DOF, the solver flips the part and
    returns `converged_at_tolerance` with `satisfied is True` — proving the
    class predicate steers the iteration (§3.1) rather than only failing it at
    verification. The `concentric` analogue is asserted alongside: zero radial
    offset with axes tilted beyond `axis_eps_deg` is not a success.
21. `not_an_objective_kind` fires with reason `plateau` for `clearance_min`
    and `no_interference`, `pose_invariant` for `fit`, and `kernel_extremum`
    for `distance` — each asserted with its reason string, nothing written.
22. Those excluded kinds are nevertheless **evaluated at the solution**: a
    fixture whose four analytic mates are satisfiable only by driving two
    solids into each other returns `converged_at_tolerance` — with all four
    objective constraints re-measuring `satisfied is True` — and
    `no_interference` violated in the verification block.
23. **`underdetermined_at_tolerance` is where the rank-deficient single-kind
    systems land.** A single `concentric` pair: `dof_remaining == 2`, and the
    basis names axial translation and axial rotation about the measured axis.
    A single `coincident` pair: `dof_remaining == 3`, the in-plane `SE(2)`
    basis named. Each asserts `satisfied is True` at the returned member and
    the verified residual `<= tol`, and neither asserts a unique transform.
24. `multiple_solutions_from_starts` on the 180°-flip bracket fixture; all
    solutions returned, none chosen.
25. `overconstrained_at_residual_floor` on a provably inconsistent pair, with
    stationarity asserted, per-constraint residuals at the floor attached,
    and **no culprit constraint named** (asserted as an absent field).
26. `no_placement_found_from_starts` from a deliberately distant start, with
    every start listed; the words "infeasible"/"no solution" absent from the
    payload.
27. `no_ground_part`, `free_part_is_jointed`,
    `pose_bound_constraint_in_transform_space`, `free_part_in_no_constraint`,
    `unknown_constraint`, `withdrawn_constraint` each fire by name with
    nothing written.
28. `non_rigid_iterate` under a fault-injected rotation-block perturbation
    beyond `SO3_REPROJECT_EPS`.
29. Weighting: the same system under `unit_scaled_v1` and under two different
    `declared` weight pairs returns different solutions, each echoing its
    applied weights **per component** — a `coincident` term echoes two, one
    `mm` and one `deg` (§3.4) — and (for `unit_scaled_v1`) the computed
    `characteristic_radius_mm`; a request omitting `weighting` is refused.
30. Regularisation is echoed; a request omitting it is refused
    `undeclared_regularization`.
31. Independent verification (§7): separate process, import-closure
    assertion, all-eight-kind evaluation, the satisfaction read (§7.4 — every
    `values` entry recorded beside its declared bound), and a fault-injected
    internal residual producing `solver_residual_disagreement` with both
    numbers and no verdict.
32. **The proposal is not a verdict**: after a `converged_at_tolerance`
    proposal against a violated constraint, `check_assembly` still reports
    that constraint `violated`, the assembly projection is unchanged, and no
    tool accepts the proposal id where a constraint id is expected.
33. **The proposal clears nothing**: the FakeModel reviewer harness produces
    the blocking finding for the violated constraint with the converged
    proposal present, and no model-facing write clears it
    (`VALIDATION.md:254-266`).
34. Proposal provenance: the record binds every source `artifact_ref`, the
    constraint generation, the toolchain hash and the request; a proposal
    with neither a requirement id nor `assumed` is refused
    `missing_provenance`.
35. Staleness: rebuilding a bound part makes `read_proposals` report
    `stale: true` naming the changed ref; the proposal stays readable.
36. **No writeback, asserted structurally rather than by a refusal name.**
    Three assertions, no runtime trigger among them: (i) the proposal record
    contains no source text and no `suggested_edit` field, asserted against
    the canonical proposal document schema; (ii) that schema is
    `additionalProperties: false`, so the field cannot appear whatever an
    implementer adds; (iii) all 56 tool input schemas are
    `additionalProperties: false` (`schemas/tools/*.schema.json`), so the
    field cannot be requested either — an extra key is a schema rejection
    before dispatch. A fourth clause keeps the vocabulary closed: the string
    `no_writeback_grammar` appears in no refusal tuple and in no payload,
    asserted against the literal request-time / resolution-time / run-time
    tuples of §6.3, so the closed set has no member the document asserts but
    does not list.
37. Determinism for an all-analytic 2B solve, per block (§9): recorded frames
    asserted equal, `solver_core` byte-identical as canonical JSON minus
    timestamps with `determinism_tier == "D1"`, the `verification` block held
    to the four D2 bindings and carrying `determinism_tier == "D2"`, and no
    `verification` block claiming D1.
38. Bounded execution: `SOLVE_ITER_MAX` and `SOLVE_TIMEOUT_S` produce named
    refusals carrying the best iterate and its verified residuals; the
    verification subprocess is dead after `VERIFY_TIMEOUT_S`; neither
    spelling is in the verdict tuple.
39. `propose_placement` is refused on the part profile and dispatches on the
    orchestrator profile; `read_proposals` dispatches on both and returns
    withdrawn generations with their reasons.
40. Tool-count pins repointed to 56 with this stage cited, and the five
    generated artifacts drift-clean (`contract/tests/test_toolgen.py`,
    `tests/stage2/test_g2_contract_drift.py`); the clause-14 heading gate
    re-runs over the 13B headings.
41. `heph solve placement` and `heph proposals`, human and `--json`.
42. Reviewer context carries proposals labeled as non-evidence; no verdict is
    solicited or accepted for a proposal id.
43. Existing suites stay green; 8C and Stage 9 wire shapes byte-for-byte
    unchanged, asserted against recorded evidence.

### Gate G13C — parameter space, and the bench

`uv run pytest tests/stage13c -q` exits 0, covering:

44. A parameter solve over a two-`Param` fixture reaches a hand-computed
    optimum — the parameter values asserted to `TRANSFORM_MATCH_EPS`'s
    parameter-space analogue derived from the same declared tolerance and
    recorded conditioning, never to 1e-9; `fit` and `distance` are admitted
    as objective terms here and `fit`'s admission is asserted against 13B's
    refusal of the same kind (the difference being pose- versus
    parameter-invariance).
45. `nonsmooth_terms` lists every `distance` term in the result, and the
    record states the local-model caveat.
46. Every candidate build is a preview: `current == false` on every build the
    solve issued, the parts' current artifact refs are unchanged afterwards,
    and no parameter override is persisted (project param state hash
    unchanged).
47. `no_free_variable_affects` on a constraint insensitive to every free
    parameter, naming the constraint id.
48. `unknown_param`, `unbounded_param` refused by name; a solve never
    proposes a value outside a declared `min`/`max`, and a solution on a
    bound reports it in `bounds_active`.
49. `unbuildable_parameter_iterate` carrying the build error when a candidate
    fails to build; `build_budget_exhausted` carrying the best iterate and
    its verified residuals.
50. Determinism D2 in **both** blocks across two processes: a 2C
    `solver_core` carries `determinism_tier == "D2"` (its iterates are
    preview builds), the `verification` block carries `"D2"`, and all four
    bindings of §9 are asserted — identical verdict spelling, verified
    residuals within tolerance and on the same side of it with identical
    `satisfied` flags, identical `bounds_active` and `dof_remaining`,
    identical bound input refs. The test explicitly does **not** assert digit
    equality anywhere, and asserts that no 2C block of either kind claims
    tier D1.
51. `space: "parameters"` accepted as an enum value on `propose_placement`
    with its schema constraint enforced in the canonical JSON Schema; no
    fourth tool is added (tool count still 56).
52. `heph solve params` human and `--json`.
53. The `solve-*` corpus family graded through the engine path: the reference
    solutions pass their own acceptance (Tier 1), and a run that produces a
    correct proposal **without rebuilding** fails the task — asserted
    directly, because it is the clause that keeps the loop broken.
54. Each new task ships prose + seeded variants and a second independent
    solution that also passes (`VALIDATION.md:94-98`); corpus-count pins
    repointed with this stage cited.
55. The Tier 3 bench clause, per `VALIDATION.md` §1 as restated by G9C:
    **solve-prose and solve-seeded are each their own split, each baselined
    on its own first measurement with the reference model at ≥3 seeds,
    neither compared against nor averaged into the v1/v2/v3 baselines** —
    the existing 0.70 prose bar keys on its own coverage
    (`bench/src/hephaestus/bench/scoring.py:117-128`) and is not diluted;
    re-baselining any combined bar is its own explicit future amendment.
56. Existing suites stay green.
