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
  **Amended 2026-08-29 (`MESH_INGEST.md` §6.5, Stage 12C):** a third declared
  mode, **`declared`**, carries an operator- or script-supplied rigid transform,
  validated as rigid (orthonormal to 1e-9, determinant +1) or refused by name,
  and echoed on the record it produced. It exists for scan targets, where
  `principal` is refused (`scan_principal_unavailable`: `principal_alignment`
  raises for a shape with no volume, and a limb scan is always *partial*, so the
  sampled region's principal axes are not the object's). `as_posed` and
  `principal` semantics are unchanged, `compare_solids` still takes exactly
  those two, and there is still **no fitted registration** anywhere — no ICP
  exists in the pinned stack and Stage 12 adds none. Alignment is declared or it
  is refused.
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
diff reports where the solids disagree, not why. No new persistence:
`compare_solids` computes on demand and stores nothing.

**Amended 2026-08-29 (`MESH_INGEST.md` §6, Stage 12C).** The sentence "No
mesh-based comparison path (sampling is on the BRep); no point-cloud imports"
is replaced by the scoped rule below. What it protected is kept: `compare_solids`
and the `SolidDiff` record are **byte-for-byte unchanged**, their sampling is
still on the BRep, and a `scan:` target on `compare_solids` or `m.diff` is
refused `scan_target_unsupported` naming the replacement rather than widening
`SolidDiff`.

A **scan-target** comparison path exists, and it is a *different record type*:
`compare_to_scan` / `m.scan_diff` return a `ScanDistance`, which reports the two
directed distances separately with the method that produced each, and which has
**no `iou`** (an intersection-over-union needs a solid on both sides, and a scan
yields one only through a sew whose validity gate refuses most real scans) and
**no `chamfer_mm`** (one direction may be an upper bound, and averaging an exact
number with a bound produces a number with no defined meaning). `align="principal"`
is refused against a scan target by name. Point-cloud imports exist as a
measurement target only (`MESH_INGEST.md` §2.3): a point cloud is not a shape,
and passing one where a shape is expected is refused `point_cloud_not_a_shape`
rather than silently sampled to zeros.

Carried forward across the replacement, because it is a rule about a different
mesh entirely: **an FEA mesh is a solver input, never a comparison operand**
(`PHYSICS.md` §9, whose "explicit non-amendment" re-anchors here). A solver
discretization is not a measurement target and nothing in Stage 12 admits one.

*Provenance, stated exactly, because an earlier draft of this paragraph said
"carried forward verbatim from the replaced sentence" and that was not true.*
The replaced sentence read "No mesh-based comparison path (sampling is on the
BRep); no point-cloud imports" — it never contained the FEA rule. The FEA rule
is `PHYSICS.md` §9's **reading** of that sentence: §9 declares it an explicit
non-amendment at Stage 15 on the grounds that a solver discretization was
already excluded by it. What `mission_plan.md`'s Stage 12 row requires is that
the exclusion **survive this rewrite**, and it does — stated here in its own
words, above, rather than inherited from a sentence that no longer exists. The
requirement is met in substance; the earlier claim about where the words came
from was not, and is corrected rather than left to be discovered.

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

## 5. Bounded execution (2026-08-02 amendment, CADGenBench audit)

Comparison on pathological B-reps is unbounded in the kernel: a boolean or
chamfer pass over a heavy imported solid can grind for hours (measured: one
editing sample held a core for ~19 h; five of six live-run infrastructure
deaths in the 2026-07-29 sweep ended on an unanswered `compare_solids`).
An interactive tool that can outlive its session is a harness defect, so:

- **The engine surface is bounded.** `compare_solids`, `m.diff`, and `heph
  diff` compute the `SolidDiff` in a killable subprocess under a wall-clock
  ceiling (named constant, env-overridable — the local-floor pattern). The
  cheap facts (topology census, bboxes, volumes) are computed and streamed
  FIRST; a ceiling kill returns a named `compare_timeout` refusal that
  CARRIES the partial facts and says which halves (volume boolean, surface
  sampling) were lost. The model gets signal it can act on — never a dead
  session, never a silently coarse number.
- **`geom.compare` itself stays pure and unbounded** — process management
  is an engine concern; external scorers already bound it their own way
  (`bench` local floor) and `score_step_files` callers own their budgets.
- A `CHECKS` predicate over `m.diff` whose diff times out is `unverifiable`
  for that build (named, recorded), not a pass and not a crash.

Gate addendum: `tests/stage8b` additionally proves the ceiling (a diff that
cannot finish returns `compare_timeout` with census+bbox facts within
bounds; the subprocess is dead afterwards), and the unverifiable-check path.
