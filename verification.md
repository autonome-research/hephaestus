<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# 03 — Verification Harness

Hephaestus is developed as a droid mission with machine-verifiable stage
gates. This document defines the three verification tiers every gate draws
from, the golden corpus, and the CI contract. The principle: **no acceptance
criterion may require human judgment to evaluate.** Every criterion is a
command with an exit code or a metric with a threshold.

## Tier 1 — Geometric assertion tests (pytest)

`opstore/tests/` exercises the standalone durability package; `tests/`
exercises CAD/core adapters and product surfaces. Categories:

- **Opstore tests.** Property/state-machine and subprocess crash tests cover
  generic WAL recovery, idempotency/key rotation, CAS blobs, leases, admission/
  suspension/terminal acknowledgment, reachability, retention, and GC without
  importing CAD/core. Import-graph tests enforce the package boundary; its
  README examples are executable tests.
- **Contract tests.** Required PR checks build independently authored projects
  under `corpus/public_fixtures/` and assert the complete script/result/check/
  render contracts without private credentials. Separately, the two recovered
  reference scripts are mounted only in the isolated private verifier and build
  unmodified; its hidden assertions confirm the published metrics (3 and 25
  labeled geometries, 380×280×250 ±0.5 mm shelf bbox, sealed/genus 0, and the
  stated panel/spline/collar clearance). It returns only a signed aggregate
  pass/fail attestation—never source, dimensions beyond already-public facts,
  logs, coverage, cache, or artifacts.
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
  hand-computable fixtures (two boxes at known offsets, etc.), and — Stage 12A
  (`MESH_INGEST.md` §3, gate G12A clause 10) — **mesh quality** against
  hand-computable fixtures. Hand-computable is the requirement, not a
  convenience: a cube has 8 vertices, 18 edges and 12 triangles so `V - E + F`
  is 2; delete one triangle and it has exactly 3 boundary edges in exactly 1
  loop of `10 + 10 + 10√2` mm. A golden captured from the implementation would
  pass just as happily if the implementation were wrong from the first run,
  which is the whole reason this row says what it says.
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
- **Kernel-derived goldens carry a (container image, OCCT version) pair**
  (`MESH_INGEST.md` §8 Tier 3, Stage 12B). The rule above, extended from the
  renderer to the kernel, and for the same reason: `BRepBuilderAPI_Sewing` is a
  tolerance-driven merge whose output topology this project does **not** claim
  is stable across OCCT builds. A sew golden therefore records **counts and the
  `BRepCheck_Analyzer` verdict, never sewn bytes** — the most a sew can honestly
  offer — and a mismatched pair **invalidates** it: the comparison is refused by
  name rather than run, because a difference under a moved kernel says nothing
  about the code under test. An OCCT bump is a re-baseline PR, exactly as a
  renderer digest bump is (`repo_conventions.md`:186-194); regeneration happens
  only under `HEPHAESTUS_REBASELINE_SEW_GOLDENS`, so a golden can never quietly
  rewrite itself into agreement. The OCCT version is a **measurement** — read
  from the wheel that shipped the kernel, since this binding exports no
  `Standard_Version` — and the image digest reads `unpinned` outside a pinned
  image rather than an empty string that could be mistaken for one.
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

Initial **public** corpus v0 (8 difficulty-ordered tasks). Tool-call
budgets were re-baselined 2026-07-25 (maintainer-authorized corpus amendment)
for the epoch-1 self-hosted reference model: the original frontier-calibrated
budgets produced overruns of 1–2 calls across the board in the first measured
Tier 3 run. New budgets give ~30% headroom over the originals; the pass
criterion and Wilson gate are unchanged. Amended again 2026-08-25 (operator
decision): budgets are now **calibrated from measurement** under the policy in
`VALIDATION.md` §7 ("Budgets are calibrated from measurement") —
`ceil(1.3 × max(hand-counted reference path, observed passing max))`, re-derived
only from archived observe-mode journals, recorded per task in each
`task.json`'s dated `notes`, and never re-scoring an archived artifact (the G6
closure of 2026-08-13 stands as measured under the pre-amendment budgets). The
budgets listed below and each task's `task.json` carry the recalibrated
numbers; tasks already at or above the derived number kept theirs. The
restricted gate
uses separately authored, undisclosed tasks from its private repository; none
of those prompts, ids, targets, checks, or dimensions appear below:

1. **bracket-101** — L-bracket, two through-holes at given centers, filleted
   inner corner. Checks: bbox, hole positions via tagged faces, sealed.
   Budget 25 calls (recalibrated 2026-08-25).
2. **sheet-box** — finger-jointed open box from 6 mm sheet, kerf clearance
   param. Stage-2 checks: zero interference assembled and `as_built` DXF
   profile count = 5. Stage 6 upgrades this task with a valid `nested_sheet`
   layout requirement. Budget 42 (recalibrated 2026-08-25).
3. **cat-step** — the recovered shelf+gusset design re-derived from a prose
   prompt equivalent to the original user intent. Checks: the reference
   scripts' own invariants (clearance fits, envelope, manifold). Budget 52 (calibration 2026-08-25: unchanged).
   This makes the reverse-engineering source into the flagship benchmark task.
4. **store-hardware** — modify bracket-101 to mount with store-sourced M5
   screws, counterbored. Checks: screw instances present, head below surface
   (measured), no interference. Budget 32 (recalibrated 2026-08-25).
5. **repair-fillet** — a deliberately broken script (the oversized-fillet
   fixture); task is repair-only. Checks: builds clean, fillet radius > 0
   applied on the tagged edge set. Budget 12 (calibration 2026-08-25: unchanged). (Tests error-message quality as
   much as the model.)
6. **param-retune** — given the shelf, retune params to hit a new envelope
   without editing geometry code (only `set_params`, project scope). Checks:
   new bbox, all original checks still pass. Budget 13 (recalibrated 2026-08-25).
7. **knob-loft** — a lofted/revolved control knob: knurled-boss-free revolve
   with a lofted grip transition, filleted, exported 3MF. Checks: bbox,
   sealed, genus 0, revolve axis symmetry (max radial deviation of the
   profile under 180° rotation < 0.05 mm), volume window. Budget 33 (recalibrated 2026-08-25).
   *Purpose: forces non-prismatic, non-sheet idioms into the gate.*
8. **enclosure-bosses** — FDM project box with lid, four internal screw
   bosses, and wall-thickness limits. Checks: boss positions via tags,
   min wall ≥ 1.6 mm (DFM-style measured check), lid/box zero interference
   with declared clearance, section render exists for +Z midplane. Budget 43 (recalibrated 2026-08-25).
   *Purpose: forces internal-feature reasoning (section channel) and
   print-process metadata.*

### Corpus splits and validation metrics (amended 2026-07-26)

Every public task ships in two spec variants (`VALIDATION.md` §1): **prose**
(no seeded `checks/`; measures interpretation) and **seeded** (acceptance
checks installed as an independent spec; measures iterate-to-green). The two
pass rates are reported and gated **separately with independently baselined
thresholds**, never collapsed. The corpus-v0 aggregate gate (Wilson lower-90%
≥ 0.60) continues to name the **prose** split so the pre-amendment baseline
stays comparable; the seeded threshold is baselined on its first measurement.
Post-seeding numbers are never compared against pre-amendment results. The
prose-vs-seeded gap — the interpretation tax — is a published leaderboard
column.

Reported alongside pass rates: `interpretation_gap`, `error_recovery_rate`
(failed build → *next build succeeds*, not error uniqueness),
`requirement_coverage`, `clarification_rate`, `review_catch_rate` split by
catching channel (vision vs numeric), and `spec_tampering_rate` (protected
checks are restored before the final build, and the attempt is scored). The
bench answers `ask_user` non-committally ("unspecified — use your judgment")
so auto-answering cannot substitute for the production clarification path;
whether the agent asked is itself scored.

No model-path conclusion (including any downgrade of the vision path) may be
drawn before `knob-loft`, `enclosure-bosses`, and an assembly-mating task have
reported with the channel split.

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
≤ 5 s; **parse + canonicalize + quality for the reference fixture scan**
(Stage 12A, `MESH_INGEST.md` §1.5/§3, gate G12A clause 19). Budgets tighten
(never loosen) by amendment.

**The mesh budget: ≤ 18.4 s, and where that number comes from.** It was
previously owed a re-measurement — set in the repository venv, and this row
refused to quote a second-value until the image had produced one. The image
produced one on 2026-08-30: **6.1365 s** for a 20 480-triangle reference scan,
archived with the (image digest, OCCT version, Python) stamp of the world that
measured it at `tests/stage12a/evidence/pinned_measurements.json`. The ceiling
the gate enforces is **derived** from that figure at import — three times it —
rather than transcribed, so it cannot drift from its record; and it is asserted
to be at or below the 20 s that stood before, because budgets tighten and never
loosen.

**What "in the pinned image" means here, since one machine could not pull it.**
`ci.yml` consumes the image by GHCR digest, and that digest is the pin. A
private package answers `403` without `read:packages`, so a record may instead
be taken in a container built from the repository's own **unchanged**
`docker/ci/Dockerfile`, whose `FROM` is digest-pinned — the route
`docker/ci/README.md` documents and commit `f3a4d42` took for the G1/G4
goldens. The record names which route produced it; a run outside any pinned
image cannot produce a record at all; and the record carries the Dockerfile's
`FROM` digest, re-read from the repository at test time, so a base bump
invalidates it exactly as an OCCT bump invalidates a sew golden.

**And it is re-taken, not just taken.** The
`stage12 measurements (pinned image)` lane in `.github/workflows/ci.yml` runs
`scripts/stage12_pinned_measure.py --check` inside the image on every PR — every
recorded figure measured again, failing if the committed numbers no longer
describe that image — then runs this clause and the other three Stage 12 clauses
that name the image (`MESH_INGEST.md` G12B.25, G12B.33, G12C.45/46) there with
`-s`. That lane is in `release.yml`'s prior-gate list. Changing any of these
numbers is a re-record PR that cites the run that produced them.

## CI contract

GitHub Actions on the autonome-research org:

- `ci.yml`: lint (ruff + pyright strict on opstore/core/server; eslint + tsc
  strict on agent/web), Python and Node unit suites, opstore import-boundary and
  schema/bridge drift checks, Tier 1,
  and Tier 2 render goldens — every PR.
- `e2e.yml`: Playwright suite — PRs touching server/, agent/, or web/.
- `bench.yml`: Tier 3 corpus — manual dispatch + weekly schedule (API cost
  control), publishing the results artifact.
- Public stage checks are ordinary `pull_request` workflows and require no
  private credentials, including for forks. `private-reference.yml` is not
  `pull_request_target`: it runs a fixed verifier on a protected trusted stage
  SHA in a networkless worker, mounts fixtures without exposing repository
  credentials, suppresses worker output/caches/coverage, leak-scans its boundary,
  and publishes only a signed aggregate status. A stage cannot advance until
  both its public gate and any named private attestation are green; ordinary
  external PRs are never required or permitted to fetch private fixtures.
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
credentials and never writes outside project roots. SBOM/import-graph tests
prove the exact Pi/thread-phase pins have no native addon and that thread-
phase's transitive `openai` package is absent from the bundle or proven inert
(no import, credential, or request path). Provider fixtures exercise a non-
Anthropic OpenAI-compatible endpoint and a local endpoint through `ModelRuntime`.
Scheduler tests prove stateful/interactive tools execute sequentially and that
16 synchronously waiting parents enter durable suspension, admit 16 children,
and resume without starvation. Mutation tests cover unique invocation derivation despite repeated provider
tool-call IDs, lost-response idempotency, crash injection at every PREPARED/
rename/fsync/COMMITTED boundary, detected external-save conflicts, exact
attempted-snapshot recovery, project-parameter/`globals.py` build races without
deadlock, coherent project-manifest rejection/acceptance, distinct failed-build
checkpoint refs, transient-preview measurement targeting, artifact-bound solid/untagged-face/edge selection with exact source refs and
round-trip acceptance of every returned per-view bundle/pass ref after current
changes, focus-invariant mask
ID domains and wrong-mode rejection, atomic/provenance-bearing check-set
generations with fail-closed invalid-import diagnostics, typed globals/check
validation, immutable byte-cursor paging, behavioral parity for Pi/bridge and
FastMCP direct dispatch, normalized high-water-marked Pi-history paging, scoped/
object-authorized delegation with every terminal/rejection/interruption
variant, create-only
export retry, and dirty-preimage journals. Manual/automatic GC races against leased
artifact inspection return either a complete hash-valid artifact or structured
`artifact_expired`, never partial bytes. Bridge boundary tests include JSON
and base64 overhead, 1–4-view schema bounds, a restart-reconstructed 16-run durable admission/terminal-ack channel plus
seventeenth-run refusal under stalled consumption, priority reacquisition for
suspended parents, progress-delta coalescing without audit loss, per-session
cancellation isolation, discriminated vision capability outcomes, image
dimension/pixel bombs, and generic
UTF-8-safe artifact paging (including explicit oversized-line signaling, a
single >50 KiB line, and rejection of every interior byte offset of multibyte
code points), plus bounded/readable oversized selection legends. Parameter mutation tests assert mixed-valid/
invalid updates are atomic. Packaging tests audit away required native
Node addons and initialize the Python-backed workflow JobStore across the
supported OS/architecture matrix. Executor escape suites run natively under
Linux bubblewrap and on macOS through the approved OCI backend; absent/failed
backends produce explicit fail-closed results. The private gate split is itself
CI-validated by its reference solutions on every rotation.
