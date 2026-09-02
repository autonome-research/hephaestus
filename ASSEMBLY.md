<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# 09 — Assemblies and constraints (Stage 8C)

Normative. Fills the Stage 8C slot in `mission_plan.md` ("mates/joints as
declared constraints that must hold, replacing post-hoc interference
discovery"). Amends `tool_schema.md` (constraint tools), `VALIDATION.md` §5
(reviewer receives constraint status; unsatisfied constraints block
termination), and `script_contract.md` §6 (nothing — part scripts do not
declare cross-part constraints; see §1). Design premise: parts already share
one world coordinate system and agree on interfaces through shared `hc`
constants; what is missing is a project-scoped, machine-checked statement of
WHICH interfaces must hold, so a violated fit is a named constraint failure
at publication time, not an interference a well-written `CHECKS` happens to
catch.

## 1. Constraints are project state, not script content

A constraint spans parts, so it cannot live in any one part script. The
project carries a **constraint set** — generational state exactly like the
requirement ledger (CAS-swap under the project config lock, immutable
generations, provenance on every entry). Each entry:

```json
{"id": "c-lid-fit", "kind": "clearance_min",
 "a": "enclosure_lid:register_wall", "b": "enclosure_base:register_slot",
 "value_mm": 0.15, "tol_mm": 0.05,
 "provenance": {"requirement": "r-7"}, "note": "slip fit per datasheet"}
```

- **Anchors** are `part[:selector]` where the selector is a §5.3 tag, a
  geometry label, or a binding name — the existing addressing layer, no new
  naming scheme. A bare `part` anchors the whole compound. (Note 2026-08-26:
  the anchor grammar always was colon-separated legal part idents —
  `ANCHOR_PATTERN` in `core/src/hephaestus/core/project_store/constraints.py`;
  the example above originally showed slash-bearing part names, which that
  grammar refuses, and was corrected in the same change.)
- **`poses` (optional; amendment 2026-08-26, `KINEMATICS.md` §3)**: a list of
  named pose ids the entry is evaluated at. Absent, evaluation is at zero
  exactly as in 8C. Present, the constraint is evaluated at each named pose —
  the loop-closure and limit-fit vocabulary; outcome shape in §2.
- **Kinds** (8C set; each later kind is a contract amendment):
  `no_interference(a, b)`, `clearance_min(a, b, value_mm)`,
  `distance(a, b, value_mm, tol_mm)`, `coincident(a, b, tol_mm)` (planar
  faces, opposed normals), `concentric(a, b, tol_mm)` (cylindrical axes),
  `parallel/perpendicular(a, b, tol_deg)`, `fit(a, b, min_mm, max_mm)`
  (cylindrical hole/shaft radial window — the fits vocabulary DFM already
  speaks).
- **Provenance is mandatory**: a constraint cites a ledger requirement id or
  is `assumed` with a reason — the same honesty taxonomy as `VALIDATION.md`
  §2, because a constraint IS an interpretation of intent.
- **NO SOLVER MOVES GEOMETRY.** Scripts position geometry; constraints verify,
  they never move anything. A constraint that requires motion to satisfy is
  simply unsatisfied. A placement solver PROPOSES: Stage 13 (`SOLVER.md`)
  computes candidate placements as a measured, provenance-carrying artifact
  that no tool applies. A constraint's verdict is still produced only by
  measuring delivered geometry; a proposal is never a verdict, never clears a
  violated row, and nothing in Stage 13 writes a script, a parameter, or an
  artifact.

  (Amendment 2026-08-30, `mission_plan.md` §"Stage 13", operator-directed. The
  first two sentences of this bullet are unchanged and stay normative
  verbatim — they are the rule, and Stage 13 does not touch them. What the
  amendment replaced is this bullet's old closing parenthesis, "(A placement
  solver, if ever, is a separate stage.)", which pre-authorised exactly this
  route; the separate stage is Stage 13 and the parenthesis is spent. The
  scope of the reversal is *proposal only*: writeback stays refused, and no
  code path in Stage 13 computes, offers or guesses an inverse from a
  transform to a script expression. Applying a proposal is an authoring act
  through the ordinary `edit_part` / `write_part` / `set_params` path, so
  scripts remain the sole authority on position and the diff stays
  reviewable.)

## 2. Evaluation: residuals in geom, verdicts in the engine

- **`hephaestus.geom.constraints`** (eighth geom service): pure residual
  evaluation — given resolved shapes for `a`/`b` and a kind, return a
  `ConstraintResidual` (measured value, worst-point locations, satisfied
  under the entry's tolerance as a FACT restated from the declared numbers —
  geom still decides nothing about what is declared). Deterministic, reuses
  `measure`/`topology`; angular kinds get named epsilons.
- **Engine evaluation** (`hephaestus.core.assembly`): resolve each anchor
  through the addressing layer against the parts' CURRENT successful build
  artifacts, evaluate residuals, produce an `AssemblyStatus` — per-constraint
  `satisfied | violated(residual) | unresolvable(reason)` — where
  `unresolvable` (missing part, no current build, dangling tag after an
  edit) is its own honest state, never silently skipped and never conflated
  with violated. Status is recomputed on demand and PROJECTED at
  publication: rebuilding any part a constraint touches marks the assembly
  projection stale, same machinery as `hc`/import staleness.
- **Pose-bound outcomes** (amendment 2026-08-26, `KINEMATICS.md` §3): an
  entry carrying `poses` is evaluated at each named pose (anchors resolved
  once, transforms applied, residual per pose). Its outcome extends the 8C
  record explicitly: the row's singular `residual` slot carries the **worst
  pose's residual**, and a new `pose_residuals` table carries one
  `(pose_id, verdict, residual)` entry per bound pose. Violated at ANY bound
  pose is violated; an unresolvable pose makes the row unresolvable. Entries
  without `poses` keep the existing outcome wire shape byte-for-byte.

## 3. Surface

- **Model tools** (part + orchestrator profiles):
  `declare_constraint(entry)`, `update_constraint(id, patch, reason)`
  (revise/withdraw with recorded reason — withdrawal is a new generation,
  never an erasure), `read_constraints()` (entries + latest evaluation),
  `check_assembly(ids?)` (evaluate now, return `AssemblyStatus`). Declaring
  is cheap and reversible, so unlike references it IS model-writable — the
  ledger's compelled-honesty pattern, not the reference registry's
  operator-only pattern.
- **Operator CLI**: `heph assembly` prints the constraint table with latest
  residuals; `--json` for scripting; `heph assembly check` re-evaluates.
- **Ladder integration** (`VALIDATION.md` §5 amendment): the termination
  reviewer receives the full `AssemblyStatus` alongside metrics and renders;
  a `violated` or `unresolvable` constraint at termination review is a
  blocking finding by RULE (the never-green invariant extended to
  assemblies), waivable only by the operator, recorded as such.
- **Bench**: `task.json` acceptance may declare `constraints` that the
  grader evaluates through the same engine path — assembly tasks score on
  declared fits holding, not on volume windows.

## 4. What deliberately does NOT change

No placement solver **in 8C** (amendment 2026-08-30 with Stage 13B:
proposal-only placement solving is Stage 13 per `SOLVER.md`; nothing in
Stage 13 moves what a script authored. `propose_placement` computes candidate
transforms and stores them as a measured, provenance-carrying artifact that no
tool applies — the `AssemblyStatus` row keeps saying `violated` until a rebuilt
script measures otherwise, and writeback is refused: no inverse from a
transform to a script expression is computed, offered or guessed). No
kinematics, no motion studies **in 8C** (amendment
2026-08-26: posed evaluation of declared joints is Stage 9 per
`KINEMATICS.md`; the no-solver rule is unchanged — nothing in Stage 9 moves
what a script authored). No per-script
constraint syntax — `CHECKS` keeps owning single-part assertions; a `CHECKS`
predicate may still call `m.interference` (existing checks stay valid), but
cross-part fits belong in the constraint set. No new persistence machinery
beyond the ledger-pattern generational state. Exploded/assembly drawings
(§ existing `generate_drawing`) are unchanged; they may later annotate
constraint anchors, but not in 8C.

## Gate G8C

`uv run pytest tests/stage8c -q` exits 0, covering: every kind evaluated
against fixture geometry on both sides of its tolerance (satisfied and
violated, residual values asserted to named tolerances); anchor resolution
through tag / label / binding forms and the `unresolvable` taxonomy (missing
part, no current build, dangling tag — each named, none conflated);
provenance compulsion (an entry citing no requirement and not `assumed` is
refused `invalid_constraint`); generational state (declare → update →
withdraw, every generation replayable, nothing erased); staleness (editing a
constrained part marks the assembly projection stale; re-evaluation flips a
formerly satisfied fit that the edit broke); the model tool quartet through
dispatch on both profiles; `heph assembly` human + `--json`; the reviewer
context carrying `AssemblyStatus` and a violated constraint producing a
blocking finding by rule (FakeModel harness); a bench task with declared
constraints graded through the engine path; determinism (two processes,
identical residuals to 1e-9). Existing suites stay green; geom boundary
tests admit `constraints` as a pure service.
