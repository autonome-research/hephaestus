<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# 10 — External evaluation (Stage 8D)

Normative. Fills the Stage 8D slot in `mission_plan.md` ("a CADGenBench
adapter (generation via reference images, editing via STEP import),
submission packaging and scoring, plus the clean corpus-v1 re-run that
closes G6's bench clause"). Design premise: a corpus we did not author
cannot fall into the reproduction trap the 2026-07-26 audit closed — the
external benchmark is the honest gate, and Stages 8A/8B exist so this stage
is an ADAPTER, not new capability.

## 1. The target: CADGenBench

Facts the adapter is written against (verified 2026-07-28 from the
benchmark repo; re-verify on divergence, the dataset is authoritative):

- 81 fixtures of real mechanical parts with mating interfaces: 49
  **generation** (reproduce the part as a solid from an engineering
  drawing) and 32 **editing** (apply a described change to a starting STEP
  solid). Task type declared per sample in `description.yaml`.
- Public data: HuggingFace `HuggingAI4Engineering/cadgenbench-data`,
  per-sample folders. Ground truth is PRIVATE to the leaderboard Space —
  local scoring is a sanity floor, never the gate's number.
- Submission: a ZIP of per-sample folders each holding one `output.step`
  (`.stp` accepted), plus root `meta.json`; `sanity_check_submission.py`
  validates locally.
- Server-side scoring: validity (well-formed, watertight — a validity
  failure zeroes the sample), shape similarity (volume IoU + surface F1),
  interface match (keep-in/keep-out volumes), topology match (Betti
  numbers), combined into a CAD Score.

## 2. Adapter: `hephaestus.bench.cadgenbench`

- **`heph bench cadgenbench fetch [--dest]`** — download the public
  dataset via the HF hub into a local cache OUTSIDE the repo (never
  committed; the repo carries only synthetic mini-fixtures in the same
  layout for tests).
- **Conversion, one sample → one bench task** (`convert` step, pure
  function of the sample folder, exercised in tests against the
  mini-fixtures): a generation sample seeds the drawing as a `references/`
  image and states the task prompt (reproduce the drawn part;
  requirements ledger cites the drawing — the vision-citation path 8A
  built); an editing sample seeds the starting solid under `imports/` and
  states the edit instruction (the model starts from
  `import_step(...)` — the convergence loop 8B built). No task text
  beyond what the sample provides: the sample is the spec, verbatim, under
  provenance delimiters.
- **Run orchestration**: `heph bench cadgenbench run` drives the standard
  session harness over converted tasks (same budgets machinery, observe
  mode by default, `--parallel N`, `--samples` filter). The produced part
  is exported to STEP through the normal `export_part` path — the
  submission artifact is a build artifact with full provenance.
- **Packaging**: `heph bench cadgenbench package` assembles the submission
  ZIP (per-sample `output.step` + `meta.json` naming the model, harness
  version, and run refs) and runs the benchmark's own
  `sanity_check_submission.py` against it; packaging FAILS if the sanity
  check does, or if any included sample's local validity floor fails.
- **Local pre-score**: `heph bench cadgenbench score` applies the §3
  local floor to every produced solid: `geom` validity (sealed, positive
  volume, finite bbox) and, where the sample provides any reference
  geometry (editing starts), `bench.scoring.score_step_files` facts. It
  reports per-sample facts and NEVER claims the leaderboard number —
  output says "local floor" in so many words.
- Submission upload itself is an operator act (leaderboard account); the
  machine-checkable gate is everything up to and including the ZIP.

## 3. The G6 closure: clean corpus-v1 re-run

The second half of 8D is not CADGenBench: G6's bench clause (corpus v1
prose, Wilson lower bound) was left open while harness/corpus defects
found by the gpt-5.6-sol runs were fixed (be5f6ea, 937037b, and the Stage
8 work since). The closure run is: current tree, corpus v1, reference
model gpt-5.6-sol via the pi_native provider, budgets as committed
(drawing-shelf's known-tight 18 stands unless the operator amends it —
the run reports it as budget-bound if it is), enforce mode, archived per
verification.md evidence rules. The gate consumes the measured Wilson
bound honestly — if the bar is not met, the stage records the number and
the blocking analysis; it does not move the bar.

## 4. What deliberately does NOT change

No new engine capability — the adapter consumes 8A ingest and 8B
comparison as shipped; any gap it exposes is filed against those specs,
not patched inside the adapter. No committed external data. No claim of
leaderboard scores from local scoring. Corpus v1 tasks are not edited in
this stage (the drawing-shelf budget is an operator decision recorded
outside this spec).

## Gate G8D

`uv run pytest tests/stage8d -q` exits 0, covering, against committed
synthetic mini-fixtures in the CADGenBench layout (one generation + one
editing sample, tiny drawings/solids): conversion produces a valid bench
task per sample (generation seeds the drawing as a reference image and the
prompt verbatim; editing seeds `imports/` and the instruction verbatim;
`description.yaml` task typing respected; a malformed sample refused with
a named reason, never skipped silently); a FakeModel run over both
converted tasks produces STEP artifacts through the standard export path;
packaging assembles the ZIP layout the benchmark demands (`output.step`
per sample folder + `meta.json`), runs the vendored-or-fetched sanity
check, and fails when a sample is missing, a STEP is invalid, or the
sanity check fails; the local pre-score reports geom validity + available
`score_step_files` facts labeled as a local floor; fetch is NOT exercised
against the network in tests (the CLI surface is covered by a cache-layout
test). Existing suites stay green; boundary rules hold (the adapter lives
in bench, imports geom/bench freely, and the engine never imports it).

The G6-closure run is gated by command, not by pytest: a completed
archived corpus-v1 run on the current tree with the measured Wilson bound
recorded in the stage report — whatever the number is.

## 5. Editing-harness fixes (2026-08-02 amendment, post-sweep audit)

The 2026-07-29 sweep's autopsy: 13 of 14 failed editing runs had built a
correct-status candidate; the failures were the harness's. Four fixes, each
rule-enforced:

- **Deliverable-scoped grading.** A converted CADGenBench task declares its
  deliverable part (`candidate`). Adapter grading fails on the DELIVERABLE's
  build/export only; other parts' build failures are recorded as facts,
  never fail reasons — a model probing geometry with scratch parts is doing
  good work, not failing. Amended 2026-08-02 (corpus autopsy): corpus tasks
  get the same honesty through their OWN declarations — grading scopes to
  the parts the task's acceptance names (export/render/DFM/drawing/metadata
  requirements + constraint anchors), an undeclared scratch part's failure
  is a recorded fact, and a DECLARED part never authored fails by name. A
  task naming no parts anywhere keeps the original every-part rule. Corpus
  task files themselves are untouched.
- **Harness faults are not charged.** A tool call whose result is a harness
  fault (named timeout, sidecar restart, bridge error) does not count
  against the tool-call budget — the model must never pay for our failure,
  twice over when it retries. Charged/uncharged is recorded per call in the
  archive. Amended 2026-08-25: an assistant turn that errors on a NAMED
  transient provider class (the 2026-08-02 pair 214/218 died on one
  "WebSocket error" each with correct geometry built) gets exactly ONE
  automatic retry per run — the sidecar re-prompts with a continuation
  prompt and records a `turn_retry` audit event carrying the fault message;
  the fault itself stays uncharged, the retry turn's tool calls are charged
  normally (the model is working), and a second errored turn fails the run
  exactly as before.
- **Editing budget is measured, not guessed.** The editing-task budget is
  set from the observe-mode distribution of completed runs (2026-07-29
  data: passing editing runs and correct-but-over runs cluster 60-90);
  100 calls, recorded here as the calibrated v1 number.
- **Sidecar evidence is archived.** Each run's archive carries the sidecar
  stderr tail and every supervisor restart with its reason — the sweep's
  restarts were diagnosable only by inference from event-stream shape.

**Salvage export** (packaging amendment): `heph bench cadgenbench package`
gains `--from-archive`: a sample whose run built a current, successful
deliverable but never exported it is exported FROM the archived build
artifact — same geometry, same provenance chain, the artifact ref recorded
in the packaging notes. It never resurrects a failed build.

Gate addendum: `tests/stage8d` additionally proves deliverable-scoped
grading (broken scratch part + ok candidate ⇒ pass with the scratch failure
recorded as a fact), the uncharged harness-fault call, the from-archive
export (and its refusal on a failed build), and the archived restart
evidence.
