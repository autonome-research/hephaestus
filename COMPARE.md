<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# 08 — Solid comparison (Stage 8B)

Normative. Fills the Stage 8B slot in `mission_plan.md` ("shape/interface/
topology diff in `hephaestus.geom` serving import round-trips, regression
diffing, and external-benchmark scoring"). Amends `tool_schema.md` (one new
read-only tool) and `script_contract.md` §6 (diff facts available to
`CHECKS`). Design premise: editing work needs a convergence signal ("how far
is my part from the target?") and external evaluation needs a scorer that
runs over two STEP files with no executor and no project — the same facts,
computed once, in the geometry layer.

## 1. `hephaestus.geom.compare`: facts, never verdicts

A new seventh geom service, under the package's standing contract (pure
functions over shapes; no executor/store/agent imports; measurement never
decides). One frozen record and the functions that fill it:

- **`volume_diff(a, b)`** — boolean symmetric difference:
  `common_mm3`, `a_only_mm3`, `b_only_mm3`, `iou` (intersection over union;
  `1.0` iff the solids occupy identical space). Empty/null booleans follow
  the same guards `measure.interference` already uses.
- **`surface_distance(a, b)`** — deterministic surface sampling (parameter-
  grid per face, density proportional to face area between named MIN/MAX
  caps — no RNG anywhere) yielding directed and symmetric **chamfer** means
  and a **max-deviation** (Hausdorff estimate), in mm. Sample counts are
  reported so a score is never quietly built on a coarse grid.
- **`principal_alignment(shape)`** — a canonical pose from the centroid and
  principal axes of inertia with documented deterministic tie-breaking for
  symmetric solids. `volume_diff`/`surface_distance` take `align:
  as_posed|principal`; the record states which was used. Alignment is a
  declared choice, NEVER a silent normalization — an editing task that must
  preserve pose compares `as_posed`; a generation score that shouldn't
  punish a rigid transform compares `principal`.
- **`topology_diff(a, b)`** — census deltas over the §topology descriptors:
  solid/face/edge counts, per-kind face counts (planar/cylindrical/other),
  `genus`, `is_sealed` — the cheap first look before any boolean runs.
- **`solid_diff(a, b, align=...)`** — one call, one `SolidDiff` record
  bundling all of the above plus both bboxes and volumes.

Thresholds do not live here. "iou ≥ 0.99 is a pass" is a claim owned by a
`CHECKS` predicate, a DFM rule, or a bench task policy — cited like any
other requirement under `VALIDATION.md` §1.

## 2. Engine surface

- **Model tool** (canonical pipeline, part + orchestrator profiles):
  `compare_solids(part, target, align?)` where `target` is `"part:<name>"`
  or `"import:<relpath>"` (resolved through the Stage 8A import machinery —
  same confinement, same hashing; the comparison is attributed to the
  import's content hash in the response). Read-only, freely retryable.
  This closes the editing loop: `import_step` → modify → `compare_solids`
  → converge, with the harness measuring convergence rather than the model
  asserting it.
- **`CHECKS` integration** (`script_contract.md` §6): the measurement
  helper exposes `m.diff(part, target, align?)` returning the same facts,
  so acceptance checks can assert `m.diff("bracket", "import:target.step").
  iou >= 0.995` — a functional property with a named tolerance, exactly
  what `VALIDATION.md` §1 demands of editing-task checks.
- **Operator CLI**: `heph diff <part> <target>` prints the `SolidDiff`
  facts; `--json` for scripting. Regression diffing between two published
  builds of the same part rides the same path (`build:<id>` targets may
  follow in a later amendment; not in 8B).

## 3. External scoring (the 8D substrate)

`hephaestus.bench.scoring` gains `score_step_files(candidate, truth,
policy)`: read both via `geom.step_io`, produce a `SolidDiff`, apply a
task-declared threshold policy (`iou_min`, `chamfer_max_mm`, alignment
mode), return a scored verdict with every underlying fact attached. It
imports geom ONLY — proven by test, because CADGenBench scoring must run
where the executor and store do not exist. No bench task fixtures change
in 8B.

## 4. What deliberately does NOT change

No feature recognition, no semantic "what edit happened" inference — the
diff reports where the solids disagree, not why. No mesh-based comparison
path (sampling is on the BRep); no point-cloud imports. No new persistence:
`compare_solids` computes on demand and stores nothing.

## Gate G8B

`uv run pytest tests/stage8b -q` exits 0, covering: identity (self-diff ⇒
zero mismatch volumes, iou 1.0, zero chamfer); a rigid-transformed copy
(as-posed disagrees, principal agrees to tolerance, record names the mode);
a known local edit (a drilled hole ⇒ `a_only/b_only` match the cylinder
volume within named tolerance, chamfer localizes the deviation);
topology-only census on shapes too different to boolean cheaply;
determinism (two separate processes, identical records to 1e-9, identical
sample counts); alignment tie-break determinism on a symmetric part;
`compare_solids` through dispatch against both `part:` and `import:`
targets with import-hash attribution and confinement refusals intact;
a `CHECKS` predicate over `m.diff` passing and failing on either side of
its named threshold; `heph diff` CLI (human + `--json`);
`score_step_files` over two fixture STEP files with a policy, plus the
import-boundary proof that scoring reaches nothing outside `hephaestus.
geom`. Existing suites stay green; the geom/contract/core boundary tests
keep all seams clean.
