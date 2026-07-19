# 03 — Verification Harness

Hephaestus is developed as a droid mission with machine-verifiable stage
gates. This document defines the three verification tiers every gate draws
from, the golden corpus, and the CI contract. The principle: **no acceptance
criterion may require human judgment to evaluate.** Every criterion is a
command with an exit code or a metric with a threshold.

## Tier 1 — Geometric assertion tests (pytest)

`tests/` contains pytest suites that exercise core/ directly. Categories:

- **Contract tests.** The two recovered Smith scripts (private fixtures —
  see the provenance policy in `repo_conventions.md`; fetched into
  `corpus/reference/` from the private fixtures repo in CI, absent from the
  public tree pending legal review) build unmodified; their published metrics match: `cat_step_gusset` produces
  3 labeled solids; `cat_step_shelf` produces 25 labeled geometries, bbox
  380×280×250 ±0.5 mm, all solids sealed, genus 0, and pairwise interference
  among panels/splines/collar = 0 within 1e-6 mm³ (the assembled clearance-fit
  claim in its own comments).
- **Executor tests.** Statement splitting, checkpointing, param bounds
  enforcement, `hc` dependency tracking, language-whitelist checks plus
  OS-sandbox denial of introspection-driven host filesystem/symlink/process/
  network escapes, unsafe-backend refusal in serve/registry paths, and
  determinism (two builds ⇒ identical metrics).
- **Failure-shape tests.** A fixture script with an oversized fillet at a
  known line must yield an error record whose *fields* are asserted
  individually: correct line/col, exception type, a source frame spanning the
  failing statement, `built_through` at the prior statement, last-good
  metrics equal to independently computed values, and a machine-readable
  last-good inspect pointer. Assertions are structural, never string-equality
  against the reference product's message text — our wording is our own; the
  captured Smith error defines which *information* must be present, not the
  prose. Mutation tests (below) corrupt each field to prove each assertion
  bites.
- **Kernel-service tests.** interference/clearance/distance/mass against
  hand-computable fixtures (two boxes at known offsets, etc.).
- **Export round-trips.** Each export freezes and reports an immutable
  successful source artifact plus source/output hashes. STEP re-imports via OCP
  with equal solid count and volume within 1e-3; DXF profiles re-parse via
  ezdxf with expected closed-polyline counts and areas; GLTF validates and
  solid count matches. Rebuild races and lost-response retries preserve the
  same source/output provenance; `nested_sheet` schema rejects non-DXF/SVG.
- **Source-map tests.** Every solid in `part.geometry` resolves to a
  statement; every tag resolves to (solid, face, statement); after an edit
  that moves lines, re-resolution follows the moved statement. Tag descriptor
  tests cover each exact centroid/normal/area/length/volume threshold, no-op
  refactors, intentional edits, large edits, symmetric selector swaps, and
  interleaved current/preview/failed/raced completion, asserting warnings use
  the captured successful-current baseline ref and report heuristic deltas
  without identity claims.

Gate form: `uv run pytest tests/<stage-dir> -q` exits 0.

## Tier 2 — Deterministic render and UI verification

- **Render determinism policy.** Renders in CI run on a pure software
  rasterizer (no GPU: OSMesa/llvmpipe-class backend) inside the pinned CI
  container image; renderer, mesa, and font versions are part of the image
  tag. Goldens are valid only for a (container image, hephaestus renderer
  version) pair recorded in each golden's provenance sidecar.
- **Render goldens.** For fixture parts, rgb/mask/section/explode renders are
  compared to committed goldens with SSIM ≥ 0.995 within the pinned image.
  Mask
  renders additionally verify programmatically: decode every pixel, assert the
  color set equals the legend, and each labeled solid's mask area > 0 from at
  least one standard view.
- **Playwright / computer-use flows.** From Stage 4 on, headless browser
  scripts drive the web UI end to end and assert on both DOM and pixels:
  project opens; tree lists N geometries matching the build result; toggling
  a visibility eye changes the viewport (image diff > threshold in the
  solid's mask region); explode slider at t=1 strictly increases pairwise
  centroid distances (read back from the client's scene graph); clicking a
  masked face opens the quick-edit popover naming the resolved tag; submitting
  a quick edit lands an `edit_part` diff in the transcript panel. Screenshots
  are archived as CI artifacts, so stage review includes visual evidence —
  but the pass/fail signal is always the scripted assertion, not the
  screenshot.

Gate form: `uv run pytest tests/render -q` and `pnpm test:e2e` exit 0.

## Tier 3 — Golden-prompt benchmark (agent-in-the-loop)

`corpus/` defines end-to-end tasks: a natural-language prompt, a required
CHECKS set the final geometry must satisfy, a tool-call budget, and export
requirements. The bench harness runs the full agent loop against a configured
model and scores each task pass/fail (all checks pass AND exports validate
AND within budget), reporting success rate over S seeds.

Corpus integrity: tasks are split into a **public split** (leaderboard,
docs, community reproduction) and a **private gate split** (a separate
restricted repo, fetched only by the gate workflow) so that stage gates are
not passable by training-data leakage or by overfitting skills to published
tasks. Private tasks rotate: when a private task is promoted to the public
leaderboard, a new private task replaces it. Skills packs MUST NOT reference
any corpus task by name or replicate a task's target geometry (reviewed at
PR; a grep-level CI check enforces the naming half). Public-split transcripts,
images, tool payloads, Pi sessions, and workflow records may be ordinary CI
artifacts. Private-split raw artifacts are written only to a restricted store
with explicit retention/access policy; public jobs expose redacted aggregate
counts/rates plus a leak-scan attestation, never private prompts, task ids,
expected geometry, reference scripts, images, or model/tool transcripts.
Scoring uses S ≥ 3 seeds per task and gates on the one-sided lower 90% Wilson
confidence bound of the aggregate pass rate — not the raw fraction — so tiny-n
luck cannot pass a stage.

Initial **public** corpus v0 (8 difficulty-ordered tasks). The restricted gate
uses separately authored, undisclosed tasks from its private repository; none
of those prompts, ids, targets, checks, or dimensions appear below:

1. **bracket-101** — L-bracket, two through-holes at given centers, filleted
   inner corner. Checks: bbox, hole positions via tagged faces, sealed.
   Budget 15 calls.
2. **sheet-box** — finger-jointed open box from 6 mm sheet, kerf clearance
   param. Stage-2 checks: zero interference assembled and `as_built` DXF
   profile count = 5. Stage 6 upgrades this task with a valid `nested_sheet`
   layout requirement. Budget 25.
3. **cat-step** — the recovered shelf+gusset design re-derived from a prose
   prompt equivalent to the original user intent. Checks: the reference
   scripts' own invariants (clearance fits, envelope, manifold). Budget 40.
   This makes the reverse-engineering source into the flagship benchmark task.
4. **store-hardware** — modify bracket-101 to mount with store-sourced M5
   screws, counterbored. Checks: screw instances present, head below surface
   (measured), no interference. Budget 20.
5. **repair-fillet** — a deliberately broken script (the oversized-fillet
   fixture); task is repair-only. Checks: builds clean, fillet radius > 0
   applied on the tagged edge set. Budget 8. (Tests error-message quality as
   much as the model.)
6. **param-retune** — given the shelf, retune params to hit a new envelope
   without editing geometry code (only `set_params`, project scope). Checks:
   new bbox, all original checks still pass. Budget 6.
7. **knob-loft** — a lofted/revolved control knob: knurled-boss-free revolve
   with a lofted grip transition, filleted, exported 3MF. Checks: bbox,
   sealed, genus 0, revolve axis symmetry (max radial deviation of the
   profile under 180° rotation < 0.05 mm), volume window. Budget 20.
   *Purpose: forces non-prismatic, non-sheet idioms into the gate.*
8. **enclosure-bosses** — FDM project box with lid, four internal screw
   bosses, and wall-thickness limits. Checks: boss positions via tags,
   min wall ≥ 1.6 mm (DFM-style measured check), lid/box zero interference
   with declared clearance, section render exists for +Z midplane. Budget 30.
   *Purpose: forces internal-feature reasoning (section channel) and
   print-process metadata.*

Scoring artifact: `bench/results/<model>/<date>.json` with per-task pass
rate, mean tool calls, and token cost. The bench doubles as the model
leaderboard deliverable.

Gate form (Stage 2): with a designated reference frontier model, public corpus
v0 aggregate lower-90% Wilson bound ≥ 0.60 over 8 tasks × ≥3 seeds, with
`repair-fillet` at 3/3 seeds. A separate restricted gate runs ≥3 undisclosed
private tasks × ≥3 seeds and enforces the same aggregate lower bound without
publishing per-task identity or results. The benchmark runs through the packaged Pi SDK
runtime and thread-phase JobRunner using project-pinned dependencies; Pi
session transcripts, normalized Hephaestus events, workflow records, and
public results are archived; private raw evidence follows the restricted
artifact policy above. Thresholds are mission-tunable *upward* only.

## Performance budgets (Tier 1)

Wall-clock ceilings measured in the pinned CI image, enforced as tests:
reference shelf full build ≤ 30 s; incremental rebuild after a single-
statement edit ≤ 1.5× the changed statement's original cost plus fixed
overhead ≤ 2 s (this is the test that keeps per-statement checkpointing
honest — see the lazy-metrics note in the mission plan); 4-view rgb+mask
render of the shelf ≤ 10 s; `measure interference` across all shelf pairs
≤ 5 s. Budgets tighten (never loosen) by amendment.

## CI contract

GitHub Actions on the autonome-research org:

- `ci.yml`: lint (ruff + pyright strict on core/server; eslint + tsc strict on
  agent/web), Python and Node unit suites, schema/bridge drift checks, Tier 1,
  and Tier 2 render goldens — every PR.
- `e2e.yml`: Playwright suite — PRs touching server/, agent/, or web/.
- `bench.yml`: Tier 3 corpus — manual dispatch + weekly schedule (API cost
  control), publishing the results artifact.
- Stage gates are encoded as required checks per the mission plan; a stage's
  PR cannot merge until its gate workflow is green.
- A docs-layout/link check verifies every repository path and section reference
  in the normative root documents.

## Verification of the verifiers

Meta-tests that keep gates honest: golden images carry provenance (script
hash + renderer version) and regenerate only via `heph goldens --update`
which refuses on a dirty tree; benchmark tasks are validated by a
`solutions/` reference implementation that must pass its own checks in CI
(a task no reference solution passes is a broken task, not a hard task);
and mutation tests confirm the contract suite actually fails when the
executor's error fields are deliberately corrupted. Bridge mutation tests
corrupt framing, schema versions, tool results, image payloads, event order,
and cancellation acknowledgements and MUST fail closed. Isolation tests place
hostile fake global Pi extensions, thread-phase executables, provider
environment variables, traversal paths, and symlink escapes on the machine and
prove the packaged runtime loads only explicitly approved resources and
credentials and never writes outside project roots. Scheduler tests prove
stateful/interactive tools execute sequentially. Mutation tests cover unique invocation derivation despite repeated provider
tool-call IDs, lost-response idempotency, crash injection at every PREPARED/
rename/fsync/COMMITTED boundary, detected external-save conflicts, exact
attempted-snapshot recovery, project-parameter/`globals.py` build races without
deadlock, coherent project-manifest rejection/acceptance, distinct failed-build
checkpoint refs, transient-parameter artifact identity, create-only export
retry, and dirty-preimage journals. Manual/automatic GC races against leased
artifact inspection return either a complete hash-valid artifact or structured
`artifact_expired`, never partial bytes. Bridge boundary tests include JSON
and base64 overhead, 1–4-view schema bounds, terminal-event reserve,
per-session cancellation isolation, image dimension/pixel bombs, and generic
UTF-8-safe artifact paging
(including a single >50 KiB line). Parameter mutation tests assert mixed-valid/
invalid updates are atomic. Packaging tests audit away required native
Node addons and initialize the Python-backed workflow JobStore across the
supported OS/architecture matrix. The private gate split is itself
CI-validated by its reference solutions on every rotation.
