<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# 11 — Kinematics and motion (Stage 9)

Normative (promoted 2026-08-26 with the `mission_plan.md` Stage 9 amendment —
a dated Stage 9 heading carrying the G9A/G9B/G9C gate summaries and citing
this spec, the Stage 2V / Stage 8 amendment pattern). Revised 2026-08-26
after a 40-agent adversarial review against the codebase (31 confirmed
findings folded in).

This spec amends: `tool_schema.md` (joint and motion tools);
`VALIDATION.md` §5 (reviewer receives motion status; a violated or
unresolvable motion check blocks termination by rule); `ASSEMBLY.md` §1 (a
constraint entry may bind to named poses; the §1 example's slash-bearing part
names are corrected to legal idents in the same change); `ASSEMBLY.md` §2
(the pose-bound outcome shape of §3 below — unbound entries keep the existing
wire shape byte-for-byte); `ASSEMBLY.md` §4 (its "no kinematics, no motion
studies" sentence is scoped to 8C: posed evaluation of declared joints is
Stage 9 per this spec; the no-solver rule is unchanged); the `check_assembly`
result form in `tool_schema.md`; and `script_contract.md` §6 (the
project-scope measurement facade gains the two read surfaces of §4 below —
part scripts still declare no joints; see §1). Each amendment lands with the
sub-stage whose machinery ships it: the `VALIDATION.md` §5 and
`script_contract.md` §6 amendments land with Stage 9B, where the reviewer
motion surface and the `CHECKS` read surfaces ship — amending them at 9A
would be doc drift.

Design premise: Stage 8C made *static* fits declared, machine-checked state.
A mechanism's defining requirements — travel, non-collision through travel,
reach — are properties of a *family* of configurations, and today no part of
the harness can even state them. Stage 9 makes the configuration family
itself declared, generational, machine-checked project state.

## 0. What kinematics is here, and what it is not

Kinematics in Hephaestus is **posed evaluation**: a pure function from
declared joint parameter values to rigid transforms, applied transiently to
published build artifacts so existing measurements (clearance, interference,
distance, the whole 8C residual set) can be taken *at a configuration* or
*over a sampled range of configurations*. It is not:

- **A solver that positions authored geometry.** The 8C rule stands verbatim:
  scripts position geometry; nothing in Stage 9 moves what a script authored
  or republishes transformed artifacts. A pose exists only inside an
  evaluation.
- **Dynamics or physics.** No masses-in-motion, forces, torques, friction, or
  time. Motor sizing, load cases, and FEA are a later stage (Stage 10
  candidate). Per-part mass under a rigid transform is pose-invariant, so
  `geom.measure.mass` already covers what a pose can ask of it;
  configuration-level inertia about world axes has no primitive today and is
  deliberately out of scope with the rest of dynamics.
- **Continuous-motion certification.** Sweeps are *sampled* and reported as
  facts about the samples taken (§4). Claiming a continuous guarantee from a
  finite sample would be exactly the dishonesty the validation ladder exists
  to prevent.

## 1. Joints are project state, not script content

A joint relates two parts, so — like an 8C constraint — it cannot live in any
one part script. The project carries a **joint set**: generational state on
the ledger pattern (CAS-swap under the project config lock, immutable
generations, provenance on every entry, withdrawal is a new generation).
Each entry:

```json
{"id": "j-elbow", "kind": "revolute",
 "parent": "arm_upper:elbow_bore", "child": "arm_fore:elbow_pin",
 "limits": {"min": -5.0, "max": 150.0},
 "zero": "as_built",
 "provenance": {"requirement": "r-3"}, "note": "elbow travel per spec table 2"}
```

- **Anchors** are `part[:selector]` under exactly the 8C anchor grammar
  (`ANCHOR_PATTERN` / `CONSTRAINT_ANCHOR_PATTERN` — colon separator, legal
  part idents, no new naming scheme). A slash in an anchor is refused
  `invalid_joint` at declaration, for the same two-grammars reason
  `project_store/constraints.py` records for 8C anchors. The selector must
  resolve to geometry whose class defines a frame: a cylindrical face or
  circular edge for `revolute`/`cylindrical` (axis), a planar face or linear
  edge for `prismatic` (direction), any resolvable anchor for `fixed`. The
  wrong shape class is a named refusal (`ConstraintShapeError` taxonomy
  extended), never a guessed frame.
- **The PARENT anchor's frame is the joint frame.** The child anchor exists
  for attachment and provenance — it names what rides the joint and where it
  claims to connect. Because `zero: "as_built"` guarantees no coaxiality, the
  child anchor's own frame is measured against the parent's at resolution:
  divergence beyond a named epsilon (axis angle beyond
  `JOINT_FRAME_EPS_DEG`, reusing the `CONCENTRIC_AXIS_EPS_DEG` convention;
  radial offset beyond `JOINT_FRAME_EPS_MM`) is the unresolvable reason
  `misaligned_joint_anchors` — never a silently chosen frame, never an
  average of two frames.
- **Kinds** (Stage 9 set; each later kind is a contract amendment):
  `fixed` (rigid attachment, 0 DOF), `revolute` (1 rotational DOF about the
  parent axis, limits in degrees), `prismatic` (1 translational DOF along the
  parent direction, limits in mm), `cylindrical` (rotation + translation on
  one axis, two limit pairs). Ball, planar, and gear joints are deliberately
  absent from 9; couplings (§5) cover ratio relationships without a gear
  joint kind.
- **`zero` defines the reference configuration**: `"as_built"` (the authored
  positions ARE parameter zero — the default, and the only value in 9A) means
  every part is authored in its zero pose, which is the discipline the corpus
  and DFM already assume. A numeric zero offset is a 9C amendment candidate,
  not in the initial contract.
- **The joint graph must be a forest.** Parent/child edges over parts; a
  cycle at declaration time is refused `cyclic_joint_graph` with the cycle
  named. Closed-loop mechanisms (four-bars) are expressed as an open chain
  plus an 8C `coincident`/`concentric` constraint bound to poses (§3) —
  loop closure is then *measured* at sampled configurations, honestly, rather
  than solved. Parts in no joint entry are simply static, as today.
- **Provenance is mandatory**, same taxonomy as 8C: cite a ledger requirement
  or be `assumed` with a reason. Travel limits are interpretations of intent.

## 2. Evaluation: transforms in geom, resolution in the engine

- **`hephaestus.geom.kinematics`** (ninth geom service): pure forward
  kinematics — given a forest of joint frames (axis point, direction, kind,
  limits) and a parameter assignment `{joint_id: value}`, return the rigid
  transform per part, composed root-to-leaf. Deterministic; out-of-limits
  parameters are refused by name (`joint_limit_exceeded`, carrying the id,
  value, and limit) — an evaluation never silently clamps. Applying a
  transform to a shape for measurement uses OCP's rigid placement (no
  tessellation, no mutation of the input shape). Like its eight siblings:
  no executor, no store, no project, no verdicts.
- **Engine evaluation** (`hephaestus.core.motion`): resolve each joint's
  anchors and frames through the 8C anchoring path against CURRENT successful
  build artifacts, build the forest, evaluate poses, produce a
  `MotionStatus` with **two sections**: per-joint outcomes —
  `resolved | unresolvable(reason)`, reusing the 8C `UNRESOLVABLE_REASONS`
  plus the genuinely joint-level extensions (`cyclic_joint_graph`,
  `misaligned_joint_anchors`, wrong shape class) — and per-pose outcomes —
  `resolved | unresolvable(reason)`, where `orphaned_pose` (§3) lives,
  naming the withdrawn joint id in its detail. An unresolvable joint makes
  every pose that binds it unresolvable — named, never skipped, never
  conflated with a violated check. (Withdrawn joints follow the 8C rule:
  never evaluated, and withdrawal is not a failure — which is exactly why a
  pose naming one is a per-POSE state, not a per-joint one.)
- **Staleness** follows the `AssemblyProjection` precedent, stated as such:
  a new named motion field of `ProjectionState` (with its `to_json`/
  `from_json` extension), restaled at publication whenever a forest part's
  current artifact ref changes, and GC-linked from the state blob so a stale
  status never reads as "never evaluated". This is the one piece of
  non-ledger persistence Stage 9 adds, and §7 names it. Status is recomputed
  on demand, projected at publication — the same *rule* as `hc`/import/
  assembly staleness, implemented as its own projection like assembly's.
- **Snapshot coherence inside check runs**: `check_motion` and `heph motion`
  resolve against CURRENT artifacts. Inside a project-scope check run (§4),
  motion resolution is against the SAME frozen snapshot the run's sources
  came from — a posed-context factory and a sweep-result resolver are
  threaded caller → `run_bundle` → the project measurement facade, alongside
  the existing `imports` callback, so a check never measures a different
  geometry state than the rest of its own run.

## 3. Named poses, and constraints evaluated at them

A **named pose** is a project-state entry binding parameter values:

```json
{"id": "p-closed", "joints": {"j-elbow": 0.0, "j-wrist": -90.0},
 "provenance": {"requirement": "r-3"}}
```

Joints omitted from a pose take their zero value. A pose naming a withdrawn
joint is `orphaned_pose` at evaluation — a per-pose unresolvable state (§2),
not erased and not a joint failure.

**`ASSEMBLY.md` §1/§2 amendment**: a constraint entry gains an optional
`"poses": ["p-closed", ...]` field. Absent, evaluation is at zero exactly as
in 8C and the outcome wire shape is byte-for-byte the existing one — every
existing constraint keeps its meaning and its evidence. Present, the
constraint is evaluated at each named pose (anchors resolved once, transforms
applied, residual per pose) and its outcome shape extends the 8C record
explicitly: the row's singular `residual` slot carries the **worst pose's
residual**, and a new `pose_residuals` table carries one `(pose_id, verdict,
residual)` entry per bound pose. Violated at ANY bound pose is violated; an
unresolvable pose makes the row unresolvable. This is the loop-closure and
limit-fit vocabulary: "the latch clears at p-open and engages within 0.1 mm
at p-closed" is two constraint entries, both machine-checked.

## 4. Sweeps: sampled motion checks, reported as facts

A **motion check** evaluates a measurement over a sampled range of one or
more joint parameters:

```json
{"id": "mc-elbow-clear", "kind": "sweep_clearance",
 "a": "arm_fore", "b": "arm_upper:wire_channel",
 "sweep": {"j-elbow": {"from": -5.0, "to": 150.0}},
 "min_mm": 2.0, "samples": 64,
 "provenance": {"requirement": "r-5"}}
```

- **Kinds** (Stage 9 set): `sweep_clearance(a, b, min_mm)` (minimum
  separation across samples), `sweep_no_interference(a, b)` (no sample
  intersects), `reach(anchor, target_point_mm, tol_mm)` (some sample brings
  the anchor within tolerance, reported with the achieving parameter
  values). Swept-volume envelope artifacts are 9B facts (§6), not check
  kinds.
- **The result vocabulary is one closed set, stated once**:
  `holds_at_samples | satisfied | not_reached_at_samples | violated |
  unresolvable`. Universal kinds (`sweep_clearance`,
  `sweep_no_interference`) emit `holds_at_samples` on success — **never
  "holds"**: one bad sample existentially falsifies them, but all-good
  samples only evidence, and the verdict name says so — and `violated` on a
  falsifying sample. The existence kind (`reach`) inverts: one achieving
  sample IS proof, so success is `satisfied`; failure is
  `not_reached_at_samples` (carrying the closest sample's parameters and
  miss distance), never `violated` — samples not reaching is evidence, not
  proof of unreachability, and the name must not claim more.
  `unresolvable` follows §2. For the termination reviewer (§6) every
  non-success state (`violated`, `not_reached_at_samples`, `unresolvable`)
  is blocking alike.
- **Sampling is declared and reported.** `samples` is the per-axis request
  (default `SWEEP_SAMPLES_DEFAULT = 64`, inclusive of both endpoints);
  multi-joint sweeps evaluate the grid product. **The cap is on the computed
  total**: a declaration whose grid product (`samples`^n_joints) exceeds
  `SWEEP_SAMPLES_MAX = 4096` is refused at declaration, the refusal naming
  the computed total. Every result records `samples_evaluated` (the grid
  total), the worst sample's parameter values, and its measured value.
- **Bounded execution** (`COMPARE.md` §5 pattern, both legs): a sweep runs
  under `MOTION_TIMEOUT_S = 300` (env `HEPHAESTUS_MOTION_TIMEOUT_S`),
  streams per-sample facts as they land, and a timeout is a named refusal
  carrying the samples already evaluated — partial evidence, never a hang
  and never a silent pass. Inside a `CHECKS` predicate, a motion timeout
  makes that check **unverifiable** in the report (the `run_checks`
  discrimination extended to the motion-timeout class, partial per-sample
  facts attached), not a bare error.
- **`CHECKS` surface**: the project-scope measurement facade (and only it)
  gains `m.at_pose(pose_id)` — a posed measurement context whose
  `interference`/`clearance`/`distance` calls measure the posed
  configuration — and `m.sweep(check_id)` — the motion-check result record.
  Both resolve through the engine path against the run's frozen snapshot
  (§2). Enforcement sits where the existing scope rules actually live: the
  part-scope facade does not carry these resolvers, and a part-scope
  predicate calling them raises a named refusal (`kind="contract"`, citing
  the scope rule) **at evaluation**, recorded as that check's failure — the
  same discriminated-facade mechanism as the `m.diff` import-target refusal,
  not a load-time pass over predicate bodies (which the engine has never
  had and Stage 9 does not add). A check run that resolved motion state
  records the frozen motion generation(s) in its `CheckReport` alongside
  `project_snapshot_ref`, so motion evidence is replayable like every other
  kind.

## 5. Couplings (9C)

A **coupling** declares a linear relationship between two joint parameters —
`child = ratio * parent + offset_deg|_mm` — the transmission vocabulary
(gear pairs, lead screws, belt reductions) without gear-tooth geometry:

```json
{"id": "cp-wrist-drive", "parent": "j-motor", "child": "j-wrist",
 "ratio": 0.2, "offset": 0.0, "provenance": {"requirement": "r-8"}}
```

Coupled parameters are dependent: a pose or sweep assigns only free
parameters, and assigning a coupled child directly is refused by name.
Couplings compose through the same forest evaluation; a coupling cycle is
`cyclic_coupling` at declaration. Whether the physical transmission can
carry the motion (tooth engagement, thread pitch) is out of scope — that is
geometry the parts must get right, checkable today with 8C
`concentric` + `clearance` at poses.

## 6. Surface

- **Model tools** (part + orchestrator profiles, the 8C quartet decision and
  its recorded rationale applied unchanged: declaring is cheap, reversible,
  and measured against geometry the model didn't choose, so compelled
  honesty beats gatekeeping — `ASSEMBLY.md` §3):
  `declare_joint` / `update_joint` / `read_joints`,
  `declare_pose` / `update_pose` / `read_poses`,
  `declare_motion_check` / `update_motion_check` / `read_motion_checks`,
  `check_motion(ids?)` (evaluate now → `MotionStatus` + per-check results),
  and 9C `declare_coupling` / `update_coupling` / `read_coupling`s
  (`read_couplings` returns all entries, withdrawn ones included with their
  reasons, per the 8C read-tool shape — generational state is honest only if
  every generation stays readable). All quartets follow the 8C lifecycle
  contract (update = revise/withdraw with recorded reason, generational,
  nothing erased). No `poses`-field restriction by profile is needed: the
  8C constraint quartet is already part-writable, and Stage 9 keeps the two
  surfaces consistent rather than opening a scoping leak between them.
- **Posed-scene rendering is new harness machinery, named as such** — no
  existing surface can produce it: every current render path (the
  `inspect_part` tool, `heph render`) loads exactly one part's artifact, and
  a pose is a relative configuration of several. Stage 9 adds an
  engine-internal **posed-scene render**: inputs are the joint forest's
  parts' current artifact refs, the joint-set + pose-set generations, and a
  parameter assignment (a pose id, or explicit values — a sweep's worst
  sample is not a named pose); the parts are placed by FK transforms into
  one scene fed to the existing camera/channel machinery; the output is a
  preview artifact whose provenance binds ALL source artifact refs plus the
  generations and the assignment. It is exposed through `heph render --pose
  <id>` and through the reviewer context — it is NOT a model tool and NOT a
  parameter on `inspect_part` in Stage 9 (a model-facing posed render is a
  later amendment once its per-profile dispatch rule is designed).
- **Envelope facts (9B)**: `check_motion` on a sweep may additionally publish
  a swept-envelope artifact — the union of the moving compound at each
  sample — as a content-addressed preview artifact labeled with its sample
  count. It is a visualization and packaging fact ("does the mechanism stay
  inside its enclosure" is a `sweep_clearance` against that enclosure, not a
  claim about the envelope solid).
- **Operator CLI**: `heph joints` (table + `--json`), `heph motion`
  (statuses, latest sweep results, and the coupling table + `--json`),
  `heph motion check [ids]`, `heph render --pose <id>`.
- **Ladder integration** (`VALIDATION.md` §5 amendment): the termination
  reviewer receives `MotionStatus`, every motion-check result (including
  each worst sample's parameter values and measured value as numeric
  facts), and posed-scene renders at each declared pose and at each sweep's
  worst sample (via the parameter-assignment form above). A motion check in
  any non-success state (`violated`, `not_reached_at_samples`,
  `unresolvable`) at termination review is a blocking finding by RULE — the
  never-green invariant extended to motion — waivable only by the operator,
  recorded as such.
- **Bench**: `task.json` acceptance may declare `poses`, `constraints` with
  pose bindings, and `motion_checks`, graded through the same engine path.
  Corpus v3 adds mechanism tasks (minimum: a gripper with jaw travel and
  posed closure fit; a hinge with travel limits and swept clearance; a
  lead-screw actuator using a coupling), each with prose + seeded variants,
  dual solutions, and hand-count budgets per the 2026-08-25 measured-budget
  policy.

## 7. What deliberately does NOT change

No placement/assembly solver — authored positions stay authored. No dynamics,
loads, FEA, or motor sizing. Declared state rides the ledger pattern (joint
set, pose set, motion-check set, coupling set — four uses of it, or one
namespaced store, an implementation choice this spec does not constrain);
the ONE piece of non-ledger persistence Stage 9 adds is the motion
projection field of `ProjectionState` (§2), on the assembly-projection
precedent. No per-script joint syntax; the `CHECKS` facade gains only the
two project-scope read surfaces in §4, and no load-time inspection of
predicate bodies is added anywhere. 8C evaluation of entries without `poses`
is bit-for-bit unchanged. `generate_drawing` is unchanged (posed drawing
views are a Stage 10+ candidate). Export (`as_built`) is unchanged — exports
are never posed in Stage 9. `inspect_part` and the model-tool render surface
are unchanged (§6).

## Gates

Stage 9 lands in three gated sub-stages, strictly ordered.

**Gate G9A — joints and posed evaluation.** `uv run pytest tests/stage9a -q`
exits 0, covering: FK correctness per kind against hand-computed transforms
(revolute about an off-origin axis, prismatic, cylindrical, fixed, chains of
three, forest with a static part) to 1e-9, with the parent-frame rule
asserted (a deliberately offset child anchor within epsilon does not move
the frame); limit refusal by name, no clamping; anchor frame extraction
through tag/label/binding forms, the extended shape-class refusals, the
anchor-grammar refusal of a slash-bearing anchor (`invalid_joint`), and
`misaligned_joint_anchors` on both sides of both epsilons;
`cyclic_joint_graph`; generational declare/update/withdraw with provenance
compulsion (`invalid_joint`); named poses incl. `orphaned_pose` as a
per-pose outcome naming the withdrawn joint; pose-bound 8C constraints
evaluated per-pose with the extended outcome shape (worst-pose residual in
the singular slot, `pose_residuals` table) on a fixture satisfied at zero
and violated at a limit pose, AND the unbound-entry byte-for-byte wire
regression against recorded 8C evidence; staleness (rebuilding a jointed
part restales the motion projection field; the GC edge keeps a stale status
readable); the tool surface through dispatch on both profiles; `heph
joints`; determinism (two processes, identical transforms). Existing suites
stay green; geom boundary tests admit `kinematics` as a pure service.

**Gate G9B — motion checks.** `uv run pytest tests/stage9b -q` exits 0,
covering: each sweep kind on both sides of its threshold with all five
verdict spellings (`holds_at_samples`, `satisfied`,
`not_reached_at_samples`, `violated`, `unresolvable`) asserted verbatim and
`reach` failure carrying closest-sample parameters and miss distance;
worst-sample parameter values and measured value in every result; the
grid-total sample-cap refusal, using a multi-joint entry whose per-axis
count is under the cap but whose product is over it, the refusal naming the
computed total; timeout as named refusal carrying partial per-sample facts
(fault-injected slow measure) AND the in-predicate timeout landing as
`unverifiable` in the check report; `m.at_pose`/`m.sweep` in project-scope
checks resolving against the run's frozen snapshot, the part-scope
evaluation-time named refusal (`kind="contract"`) recorded as that check's
failure, and the frozen motion generation(s) recorded in the `CheckReport`;
the posed-scene render (multi-part placement, provenance binding every
source artifact ref + generations + assignment, preview-only) at a pose id
and at an explicit worst-sample assignment; envelope artifact publication as
preview with sample-count label; reviewer context carrying `MotionStatus`,
worst-sample numeric facts, and posed-scene renders, with each non-success
verdict producing a blocking finding by rule (FakeModel harness); `heph
motion` human + `--json`.

**Gate G9C — couplings and the mechanism bench.** `uv run pytest
tests/stage9c -q` exits 0, covering: coupling composition through FK,
dependent-parameter assignment refusal, `cyclic_coupling`;
`read_couplings` returning withdrawn entries with reasons and the coupling
table in `heph motion --json`; the three corpus v3 mechanism tasks graded
through the engine path with their reference solutions passing their own
acceptance (Tier 1); corpus-count pins repointed with this stage cited. The
Tier 3 bench clause, following the Stage 2V split rule (`VALIDATION.md` §1)
verbatim: **mechanism-prose and mechanism-seeded are each their own split,
each baselined on its own first measurement with the reference model at ≥3
seeds, neither compared against nor averaged into the v1/v2 baselines** —
the existing 0.70 prose bar keys on its own coverage and is not diluted;
re-baselining any combined bar is its own explicit future amendment.
