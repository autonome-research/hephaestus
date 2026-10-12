<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# macOS progress — experimental executor and renderer

## Independent regression review — uncommitted follow-up to 4429022

**Do not merge: required CI is not green. Production remains closed.**
All live passes below are historical and **superseded for changed runtime sources**
until fresh images and a new all-stage run succeed. Independent rehashing of all
457 host / 173 executor / 173 renderer manifest entries found **26 / 21 / 21
changed entries**, respectively, and no missing old entries; new source files
also need fresh manifest coverage. The [roadmap](macos-roadmap.md)
defines the next CI, clean-machine, reliability and narrowly scoped release gates,
without schedule promises. No installer or capability expansion is included here.

Review compared the actual accumulated diff against initial `4429022`, not an
agent's success summary. Retained triage established 2,007 branch-introduced type
errors (baseline zero), 31 new test failures plus five baseline failures, and eight
downstream baseline browser failures. The missing local CAD environment does not
explain those original fully provisioned CI regressions.

Reviewed repairs preserve early native focus+section refusal, native default
render dimensions, baseline golden-generator bytes, exact GLB/source/table/GC
linkage and adversarial runtime validation. Typed records are constructed after
closed raw admission, not used as permission to trust worker JSON. Fresh-process
CAD import guards strengthen the five remote boundary cases; malformed-stream,
identity, cleanup and failure assertions remain exercised, not skipped.

This review additionally reproduced and fixed renderer-service identity mismatch,
live identity drift and cross-renderer bundle export: publication now compares
live identity before/after rendering with the returned identity, and GLB export
requires the minted bundle's executor/renderer/source provenance to agree. Three
new regressions failed before the fix and pass afterward. This checks consistency
of **trusted host injection**; a protocol annotation is not worker attestation.
Native rendering limits and ownership semantics are unchanged.

F1 remains **design-held and locally failing**: native bounded passes kill on
terminal, whereas OCI owners need duplex EOF, final durable records and parent
reaping before reuse. No import exemption, hidden re-export or weakened lifecycle
was added. Full native/core/server and strict typing authority still require CI.

Current local results (complete logs under ignored
`dist/macos-independent-regression-review/`):

- Exact historical 963-test selection: **985 passed**, one Starlette/httpx warning
  (19 prior added cases plus three review regressions). No skips/deselections.
- Supplemental bounded-pass/focused-refusal/image-identity/HTTP error/idempotency/
  catalog selection: **184 passed, 5 failed**, one warning. Failures retained:
  `test_multiprocessing_is_imported_by_the_helper_and_nowhere_else_in_the_engine`
  in `core/tests/test_bounded_pass.py`; `test_a_param_cas_conflict_is_two_hundred_with_the_discriminated_result`
  and `test_the_path_part_always_wins_over_a_part_named_in_the_body` in
  `server/tests/test_http_errors.py`; build-route variants of
  `test_a_recognized_key_replays_the_stored_body_byte_for_byte` and
  `test_the_same_key_with_a_different_payload_is_key_payload_mismatch` in
  `server/tests/test_http_idempotency.py`. The latter four require missing local
  build123d; they are **not passes**. Existing native test fixtures attempted their
  ordinary build paths and refused; no CAD dependency/fallback was installed.
- Offline provider catalog selection: **3 passed, 77 explicitly deselected**.
- Web typecheck/lint pass; **1512 tests / 82 files pass**, one worker. Existing
  jsdom canvas/navigation diagnostics remain in logs. No web source edits or
  browser e2e run; the eight baseline browser failures remain pending reproduction.
- Root partial-host Pyright: **810 errors / 7 warnings**, not a pass. Changed
  files retain three missing-CAD-related diagnostics. Root Ruff, formatting,
  docs (including the untracked roadmap explicitly), license and diff checks pass.
- Local packaging **26.3 vs locked 26.2** and Pygments **2.21.0 vs locked 2.20.0**
  make these Python results supplemental, not locked-environment acceptance.

Exact focused command (900-second outer hang detector, unchanged markers):

```sh
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH="$PWD/core/src:$PWD/opstore/src:$PWD/server/src:$PWD/contract/src" \
.venv/bin/python -m pytest \
  core/tests/test_render_remote.py core/tests/test_render_oci.py \
  tests/test_macos_workspace.py tests/test_macos_renderer.py \
  core/tests/test_oci_supervision.py core/tests/test_execution_identity.py \
  tests/test_macos_staging.py tests/test_macos_executor.py \
  tests/test_macos_executor_live.py tests/test_macos_feasibility.py \
  core/tests/test_sandbox_oci.py core/tests/test_sandbox_oci_network.py \
  core/tests/test_sandbox_oci_launcher.py core/tests/test_sandbox_oci_image.py \
  core/tests/test_sandbox_oci_transfer.py -q --timeout=120
```

Supplemental selections use the same environment and timeout, with all files
named above, including `core/tests/test_focused_section_refusal.py`,
`server/tests/test_image_identity.py` and `server/tests/test_http_catalog_admission.py`.
Provider selection: `server/tests/test_http_providers.py -k 'catalog_registration or concurrent_catalog'`.
Web: `(cd web && pnpm typecheck && pnpm lint && pnpm test --maxWorkers=1)`.
Full native CI, stage1 schema gate, pinned render/section/Khronos and both browser
lanes remain required; no skipped downstream stage is a green check.

No installs, commits, pushes, live OCI/CAD acceptance, providers/models or manual
workspace workloads in this review. Synthetic tests owned temporary stores and
finite child processes. Sibling remains clean at `16a0021`; Docker idle. Publication
inventory excludes generated reports, journals, tokens, browser profiles and
private/project CAD. Separate source-provenance disclosure remains unchanged:
Nurb source was inspected in separate research; no source/assets were copied.
Clean-machine reproducibility is not a source clean-room claim.

## Independent acceptance and PR handoff (2026-10-12, historical)

**Historical independent local experimental macOS acceptance passed for its recorded
sources; superseded by subsequent runtime repairs. Production discovery remains
disabled; this is not full-product or release certification.**
The new all-stage run is
`dist/macos-final-reviewed-20261012T152211Z/report.json`, `accepted:true`, SHA256
`df0fa8086de37a4add4bf4773a4e9ecaf9d686f869b364ad7a7b64d42b93370a`.
All 13 required checks passed: preflight, native dependencies, executor image,
image resolution, containment, build, RGB, exact selection masks, kernel section,
linked GLB, native Chrome workspace, delivered cancellation and owned cleanup.
The independent gate also recorded 694 focused tests passing, root ruff/format,
documentation references, license headers and diff checks. Earlier acceptance
was refused on two line-length errors; the two formatting-only fixes preceded
this new run. Failed reports were not edited or promoted.

Before PR packaging, all **457 host, 173 executor and 173 renderer** source-manifest
entries were independently rehashed against files at that checkpoint: no missing
or changed entries then. Subsequent runtime repairs invalidate that comparison for
the present source. This source comparison was not a new live acceptance run. Raw local reports
and diagnostic artifacts remain ignored under `dist/`, so their paths in these
documents are evidence references, not promised downloadable repository files.
Reproduction is documented in [the local workspace guide](macos-workspace.md).

Historical pre-publication checks are retained locally in
`dist/macos-pr-handoff-20261012/`: **963 focused Python tests passed** (one existing
Starlette/httpx deprecation warning); **1512 web tests passed across 82 files**
with one worker; TypeScript typecheck, eslint, root ruff and formatting,
documentation references, license headers and diff checks passed. These are
scoped checks, not a rerun of full pytest or root pyright. A publication inventory
and heuristic credential/private-path scan exclude generated data; its only
private-path matches were synthetic Docker endpoint fixtures, not personal paths.

A subsequent operator-authored rack concept exercised two 51-solid / 306-face
builds, real selection-linked GLBs, kernel measurements/sections and native browser
screenshots. Its geometry, source archive, device references and local evidence
remain outside this compatibility PR. It is a visualization, **not fabrication
validation**. The operator also opened the real workspace in Firefox; that manual
use is not a Firefox automated acceptance claim. The interactive server was
subsequently stopped by exact PID, its cleanup report passed, its serve record
was removed, and no containers were running at shutdown verification.

The operator explicitly authorized a commit series and remote PR after the local
milestone. Earlier no-commit/no-publication instructions below describe the
historical phases, not authorization for this uncommitted review to publish. The
initial series separates secure execution
and provenance, isolated rendering, workspace integration, acceptance tooling and
documentation. No generated CAD, provider credentials, tokens, browser profiles,
image artifacts, runtime journals or third-party CAD sources are included.
Nurb source was inspected in separate feasibility research; no code/assets were
copied. See [the provenance disclosure](macos-feasibility.md).

**Still not green/certified:** root pyright in the partial host environment and the
native HTTP-boundary fixture; full pytest, pinned x86 Linux goldens, release
packaging, other runtimes, large CAD and production discovery. The older diagnostic
fixture's open dimension findings and absent selection-popover workflow remain
explicit limitations. No threshold, failed test, probe or production gate was
waived to package this PR. A draft PR must not be read as approval to release.

## Independent-gate handoff (report label 20261009, historical)

**Ready for the new independent all-stage shell gate; no remaining concrete blocker
found in the five reviewed repairs.** This continuation changes documentation only:
corrected stale pre-workspace status in `docs/macos-feasibility.md` and
`docker/executor/README.md`, and explicitly retained browser dimension findings in
`docs/macos-workspace.md`. No source/test/lock/golden changes or image rebuilds.

Fresh read-only inspection is retained in
`dist/macos-independent-gate-handoff-20261009-01/inspection.json` and
`inspection.log`, with the inspection script beside them. Recomputed 457 host,
173 executor-source, 173 renderer-source and 220 image-input manifest entries:
**zero mismatches**. Four recorded report/manifest hashes match the prior checkpoint.
Docker responds at the explicit local socket: `desktop-linux`, Linux aarch64,
4,109,803,520 bytes RAM, zero running containers. All ten unrelated stopped
container IDs/names/states are unchanged; recorded smoke tags are absent. The
recorded 40 owner and 732 client PIDs/groups plus browser/server are absent, with
completion/reap records retained. Sibling remains untouched, clean `main` at
`16a0021a535d5859a7a13ec283d23f764f4d377c`. No cleanup was necessary or performed.

The interrupted report remains failed and its old session permanently refused;
`interrupted-reconciliation.json` is unchanged. The later complete `...review-03`
pass below remains recorded evidence, **not a new acceptance run in this slice**.
This handoff inspection therefore has `accepted:false`. The predecessor's no-text
final-review outputs were not code findings or successful reviews. Root pyright,
native HTTP-fixture failure, absent selection-popover UI and open dimension
findings remain explicit limitations; build success is not requirement completion.
No providers/models/agents, workers, servers or browsers were started here.

Next shell: run `bash scripts/macos_milestone_smoke.sh` with a **new** report path
and the hash-revalidated wheelhouse as documented in [local workspace](macos-workspace.md).
Allow up to 2400 seconds outside the command; do not increase individual worker,
network or build timeouts. Only a complete new all-stage run may pass that gate;
no production/release or full-suite certification follows from this handoff.

## Review repairs and fresh local acceptance (report label 20261009)

**Local experimental milestone accepted; production/release support remains disabled.**
Fresh complete run: `dist/macos-workspace-acceptance-20261009-review-03/report.json`,
`accepted:true`. SHA256:
`2ccccb4a5ca537979832d747af58ef8b9beefba4d4b0e2d521be6aa75764b3e3`.
This is a new source-specific run, not promotion of an earlier report.

Review repairs:

- Renderer rollover now closes **and affirmatively checks durable settlement**
  before opening another supervisor. Pending creates/removals/client launches,
  unreaped clients and incomplete owner/reap records refuse before a new owner
  or daemon command; the renderer stays poisoned. Successful rollover is tested.
- Browser Node spawn and every post-spawn initialization step are inside cleanup.
  Ownership-write/report-save/reader-start failures and interruption reap real
  test children; failed persistence retains pending ownership. Ownership writes
  now fsync the containing directory. A separate real native Chrome SIGTERM
  control also passed and independently verified Node/Chrome absence.
- Shared GLB linkage no longer applies OCI's 4 MiB/2048-ID admission ceilings to
  native publication. OCI validation explicitly retains those ceilings. Native
  publication/readback boundary regressions exceed each limit (synthetic geometry,
  not a claim of new native kernel coverage).
- Exact requested GLB refs resolve independently; cache lookup searches **all**
  candidates for matching executor/renderer/source-input provenance. Two valid
  publications remain readable, with no repeated rendering for current identity.
- Both render and browser acceptance require the complete authored cuboid face
  set: IDs `2–7,21–26`, 12 primitives, two meshes. Removing one otherwise-linked
  primitive fails. Real Mesa masks, kernel sections and `_mint_bundle` remain.
- Host versions are checked against `uv.lock`; web install is frozen, with all
  direct exact pins checked and the static bundle freshly built. Public downloads
  use a project-local pnpm store with finite network/command limits, no lock edits.

Final evidence and commands are under `dist/macos-review-repair-20261009-01/`:

- `focused-final.log`: **963 passed, zero skips**, including review regressions,
  OCI supervision/identity/storage/transfer, macOS collectors and workspace runtime.
- `web-final.log`: **1512 passed / 82 files**, one worker; tsc and eslint pass.
- `http-02.log`: **54 passed, 1 failed** across HTTP boundary/serve/refusal tests.
  The retained native-fixture failure first cannot import the project because its
  subprocess changes cwd while PYTHONPATH is relative. The diagnostic rerun with
  absolute paths (`http-native-absolute-path.log`) reaches the existing native
  path and refuses **build123d distribution not installed**. It is not caused by
  OCI injection; no host CAD fallback/dependency installation or fixture waiver
  was added. The independent real serve-mode HTTP OCI build succeeds below.
  `http-01.log` retains an initial missing-contract collection failure; the rerun
  explicitly adds `contract/src`. No full native suite pass is claimed.
- `pyright-final.log`: root pyright **fails: 12,450 errors / 13 warnings** in this
  partial environment, including missing dependency/type information and actual
  typing debt. Not waived or described as merely missing packages. Tool 1.1.411
  and its dependencies were installed only under this evidence directory from
  root-lock hashes. Full Python type safety/release readiness is **not** established.
- `checkpoint.json` / `verification-final.log`: independently checked every host,
  packaged-source and image-input hash (**zero mismatches**), artifact/ref/table/GC
  links, complete GLB geometry, actual HTTP build, section PNG/provenance, ordered
  explicit cancellation versus separate timeout/failure, 40 reaped owners and 732
  client records. No active owned resources or temporary smoke tags; all ten
  unrelated stopped container IDs/names/states unchanged. Sibling remains clean
  `main` at `16a0021a535d5859a7a13ec283d23f764f4d377c`.
- Executor image: `sha256:173c7179774fbc719843ea04913329c073e7e2f61188533a07a86ed2d9f12776`.
  Renderer image: `sha256:430cb61739ea34d3d94f824fed92fd4d584236933210b66d9f50c3f7732b4077`.
  Fresh offline source builds; no image-build timeout or timeout retry.
- Native Chrome **154.0.8037.98**, actual llvmpipe **LLVM 15.0.6 / 128 bits**;
  real HTTP build: two solids, 162 mm³; scene raycast and authenticated context
  resolution, unknown-ID refusal; actual two-face **26 mm²** kernel section.
  Browser report SHA256 `25978221c6707e985b8959f06343a65f6735f758f3335151f3611e30682a5807`.
  GLB SHA256 `1b6e8290045c395ab286c098de93db8576b598d3f6ea1d183ef338ac34199d00`.
  Host manifest SHA256 `a128c4e2db6b8084ec4185db73712fe74bab910d5050d545eea0bd43ddbfa4ba`.

Failures remain intact: `...review-01` refused before image builds because the
isolated offline pnpm store lacked tarballs. Frozen public pinned installation
fixed that; `...review-02` passed but precedes final typing/fail-closed refinements.
`...review-final` was **interrupted by the outer 1200-second shell watchdog** during
renderer probing, after both image builds and executor gates completed. It remains
`accepted:false`, without a finished cleanup claim. Exact-resource reconciliation
removed only its stopped preparation containers/four tags and verified workers and
clients absent. Its last renderer owner has `parent_closed` and no parent reap
acknowledgement: **that old session is permanently refused**, not repaired by an
absence guess. `interrupted-reconciliation.json` retains this unresolved evidence.
One new run (`...review-03`) with a 2400-second outer wait completed all stages;
worker/build/network limits were unchanged. Earlier `clarification_required/no_ledger`
and native HTTP-fixture failures are also preserved. Prior report hashes are in
`historical-summary.json`; none was promoted or overwritten.

```sh
bash scripts/macos_milestone_smoke.sh \
  --report-dir "$PWD/dist/macos-workspace-acceptance-20261009-review-03" \
  --wheelhouse "$PWD/dist/macos-report-02/download/wheels"
PYTHONPATH=core/src:opstore/src:server/src .venv/bin/python -m pytest \
  core/tests/test_render_remote.py core/tests/test_render_oci.py \
  tests/test_macos_workspace.py tests/test_macos_renderer.py \
  core/tests/test_oci_supervision.py core/tests/test_execution_identity.py \
  tests/test_macos_staging.py tests/test_macos_executor.py \
  tests/test_macos_executor_live.py tests/test_macos_feasibility.py \
  core/tests/test_sandbox_oci.py core/tests/test_sandbox_oci_network.py \
  core/tests/test_sandbox_oci_launcher.py core/tests/test_sandbox_oci_image.py \
  core/tests/test_sandbox_oci_transfer.py -q --timeout=120
(cd web && pnpm typecheck && pnpm lint && pnpm test --maxWorkers=1)
```

Use a **new** report path to reproduce. Tested launch/use/stop instructions:
[local workspace](macos-workspace.md). Real startup uses the ordinary requirements
ledger dispatcher, real HTTP build uses serve-mode admission, workers serialize,
agent attachment stays disabled, and SIGTERM shuts down the owned server cleanly.
No providers/models/agents, global changes, unrelated cleanup, commits or publication.
Full pytest, pinned Linux goldens, large CAD, other runtimes and release packaging
remain unrun; full pyright and the native fixture are not green. The supplied
independent reviews' findings are addressed, but no new independent human review
or production/release certification is claimed.

## Workspace integration/review checkpoint (2026-10-09, historical)

`dist/macos-workspace-live-20261009-03/report.json` passed the original full
required stage list with native Chrome 154.0.8037.98 and owned cleanup. Subsequent
hardening requires a **new final run**, not reuse of that pass: added real HTTP
build acceptance, explicit host/web pin checks and fresh bundle build, serial
CAD/render admission, permanently disabled agent attachment, bounded durable
browser/client ownership and graceful signal delivery (the generic command
transport SIGKILLs its group and was unsuitable for detached Chrome).

`dist/macos-workspace-live-20261009-final/report.json` is **failed, retained**:
the added HTTP build correctly returned `clarification_required/no_ledger`.
No gate was weakened. Launcher `--requirements` now records a bounded explicit
operator specification through the normal dispatcher, verifies quoted request
text, and `--build` also uses that dispatcher. The diagnostic fixture supplies
its authored requirements as real input. Current scoped HTTP-build/browser run
`dist/macos-workspace-browser-dev-20261009-04/report.json` passed but remains
`accepted:false` because it is not a new all-stage run.

Native launcher preparation/use implemented and actually exercised:
`dist/macos-workspace-images-20261009-03/images.json` retains two immutable local
image artifacts for use (not active containers); `dist/macos-launcher-use-20261009-03/workspace.json`
records a real gated build and clean bounded start/stop on
`dist/macos-local-demo-20261009-02`. Earlier launcher failure exposed an eager
kernel import even in the **unavailable** interference report; fixed that path.
OCI interference now explicitly says unavailable without host CAD fallback.
Preparation attempts 01/02 failed before image builds on uv's NumPy fork and the
private pnpm PATH; exact branch selection and pinned executable PATH fixed both.

Focused gates: **946 passed**, zero skips (`focused-02.log`), and **1512 web tests
passed** (82 files), typecheck/lint passed (`web-*-02.log`). New requirement tests
and final-source rerun still follow. Existing HTTP boundary run had **22 passed,
1 failed**: its native unsafe-fixture build cannot import the project under the
isolated worker and no full host CAD environment is installed. No host CAD ran,
no dependency was added to make that native-only test green; the failure is
retained in `http-boundary-01.log`. HTTP's no-renderer-import contract was restored
by making the renderer injection annotation follow the CadOps typing boundary.
The earlier focused failure from eager drawing NumPy import was fixed by deferring
actual drawing imports, not by weakening import-boundary assertions.

Instructions: [local workspace](macos-workspace.md). Next: final focused checks,
fresh all-stage smoke, independent source/ownership verification and final docs.
Independent human reviews/full release coverage remain explicitly outstanding.

## First full workspace smoke refusal (2026-10-09)

`dist/macos-workspace-live-20261009-01/report.json` remains **failed**.
All fresh executor/render stages passed, and native Chrome loaded two actual
meshes and resolved raycast face ID 22 through the authenticated context route;
unknown ID 999999 refused with 409. Section navigation exposed a real client bug:
a same-part URL reset the current pin while the unchanged cached build response
never re-ran the observer. Fixed observer dependencies without moving held pins.

Cleanup also correctly failed: uvicorn re-delivered SIGTERM to the default handler
before the launcher's outer finally, leaving its serve record and no final cleanup
record. The launcher now installs an unwinding signal handler before uvicorn.
Exact settled journals plus independent inventories verified all workers/clients/
owners absent; only that dead server's stale serve record was removed. Reconciliation:
`dist/macos-workspace-dev-20261009-01/server-reconciliation.json`; the failed report
was not promoted. A scoped browser debugging attempt `...browser-dev-20261009-02`
refused because cleanup had removed the temporary image refs. No old report
substituted for an actual image/probe. Next: fresh full smoke with both fixes.

## Workspace implementation checkpoint (2026-10-09)

**In progress; full `accepted:false`.** New explicit `scripts/macos_workspace.py`
opens `WorkspaceRuntime` with freshly probed immutable executor/render workers,
serve mode, 2 GiB/256 PID/120 CPU/120 wall build limits and 320×240 renders.
No production factory patch, provider discovery or agent startup. It serves the
existing authenticated API/static bundle on loopback, keeps the token in the
private project file, and retains exact supervision and cleanup evidence.
`macos_workspace_check.py` wires native Chrome/Playwright and renderer stages into
the milestone. The browser collector exercises actual GLB/scene raycasting,
server context selection resolution and the existing section controls/plate.
It does not claim the unimplemented click-to-selection popover works.

Fixed startup imports in CadOps document/motion modules. Registry indexing also
previously imported host build123d merely to obtain its export names; a declaration
extracted from the hash-verified pinned public wheel now serves the parser, with
exact runtime parity required during worker namespace construction. Image rebuild
required; no dependency or golden versions changed. Runtime reload retains explicit
build/render settings. Added `tests/test_macos_workspace.py` and web raycast tests.

Evidence: `dist/macos-workspace-dev-20261009-01/`. Workspace tests: **5 passed**;
initial failures (eager registry kernel import) preserved. Web build and raycast
unit passed. Host dependencies installed in `.venv` from exact root `uv.lock`
versions/hashes. Pinned web frozen install/build passed. Project-local Playwright
Chromium download hit its 180s command bound at 30%; not counted as installed or
passing. Acceptance instead uses existing native `/Applications/Google Chrome.app`,
with actual binary/version recorded. No unrelated Playwright MCP process touched.
Next: fresh serial full smoke, preserve/fix real failures, wider regressions and
precise local instructions. Independent reviews/full release lanes remain due.

## Render integration final checkpoint (2026-10-08; report label 20261009)

**`renderer_stage_passed:true`, `executor_stage_passed:true`, `accepted:false`.**
Final fresh serial run:
`dist/macos-render-integration-live-20261009-final/report.json`; real executor
controls are in its `executor/report.json`. Current-source hashes, installed image
identities, raw bounded logs, render requests/pixels, effective containment,
terminal/OOM records, owned journals and independent cleanup inventories remain.

- Renderer image/config digest:
  `sha256:b249373ebcb093706bd438f3b601bec5f802ca962669eee54a6fb64214f4e35d`.
  Actual native ARM64 **llvmpipe (LLVM 15.0.6, 128 bits)**.
- Executor image/config digest:
  `sha256:7354de7818945740b3ddf84b91c04d25a68906c29e412e95ebff58fba2fe3498`.
  Fresh 2-solid/162 mm³ CAD, BREP re-read, publication/freshness, all 13 quota
  controls, positively observed explicit cancellation, timeout/failure and cleanup.
- Host `inspect_part`: nonempty 128×96 RGB, exact solid/face/edge mask IDs resolving
  through real tables/GC links, **2-face / 26 mm² kernel section** with separately
  retained executor/render identity and build-input provenance.
- Fresh GLB via **`_mint_bundle`**, not a bypass: **2 meshes / 12 face primitives**,
  SHA256 `2c4a7d9442f3c5894bdd718cc5c704aa5ea706335925a93e8dfb016e5a8c2a7d`.
  Validated refs/table/mesh/face IDs before publication, linked cache resolution,
  stale-source refusal, artifact kinds and GC graph. Files: `linked.glb`,
  `integration.json`, `*-inspect.json`, PNGs and `executor/project` store.
- Invalid-BREP control exited 1; successful workers exited 0; all non-OOM.
  Exact workers, clients/groups and owners absent/reaped. No agents/providers,
  browsers/servers, unrelated cleanup, global settings or external publication ran.
- **937 tests passed, zero skips**, `focused-06.log` below. Final ruff/format pass.
  `focused-05.log` is an incomplete run stopped by the 180-second shell bound,
  not a pass: no named test failure was emitted and no pytest/synthetic owner or
  client remained afterward. The final verbose rerun used a stricter per-test
  120-second hang detector and completed in 50.92 seconds. No test was waived.
- Final `checkpoint.json`/`verification-final.log` independently verify **zero
  host-source hash mismatches**, no running containers, all exact owned tags
  absent, unchanged ten unrelated stopped IDs/names/states, and sibling clean
  `main` at `16a0021a535d5859a7a13ec283d23f764f4d377c`. The first checkpoint
  verifier correctly found one owned tag retained by failed run `...-01`'s
  unresolved container. After its prior exact-container reconciliation, that
  single tag was removed without force (`reconciled-tag-cleanup.log`); the first
  verifier failure and original failed report remain. No broad cleanup occurred.
- Repository lint/format, docs (78 documents), license (67 governed files) and
  `git diff --check` pass; bounded logs are in the development evidence directory.
  No commits, resets, cleans, stashes, pushes or sibling edits.

New host files: `render/{defaults,glb_gate,remote_service}.py`,
`core/tests/test_render_remote.py`, `scripts/macos_renderer_live.py`. Updated all
inspection and GLB host entry points, CadOps geometry readback, runtime injection
and reload, bundle kinds/links, renderer protocol/worker/backend, CLI and tests.
Renderer API **2** rejects API 1; native bundles remain v1, OCI bundles v2 carry
provenance. Shared containment/run/inventory/transfer stay **5/3/4/1**. The native
selection helper has no production caller. Full call graph, limits and reproduction:
[macos-renderer.md](macos-renderer.md).

Final commands (all logs under `dist/macos-render-integration-dev-20261009-01/`):

```sh
PYTHONDONTWRITEBYTECODE=1 /opt/homebrew/opt/python@3.13/bin/python3.13 \
  scripts/macos_renderer_check.py \
  --report-dir "$PWD/dist/macos-render-integration-live-20261009-final" \
  --wheelhouse "$PWD/dist/macos-report-02/download/wheels"
PYTHONPATH=core/src:opstore/src:server/src .venv/bin/python -m pytest \
  core/tests/test_render_remote.py core/tests/test_render_oci.py \
  tests/test_macos_renderer.py core/tests/test_oci_supervision.py \
  core/tests/test_execution_identity.py tests/test_macos_staging.py \
  tests/test_macos_executor.py tests/test_macos_executor_live.py \
  tests/test_macos_feasibility.py core/tests/test_sandbox_oci.py \
  core/tests/test_sandbox_oci_network.py core/tests/test_sandbox_oci_launcher.py \
  core/tests/test_sandbox_oci_image.py core/tests/test_sandbox_oci_transfer.py \
  -v --timeout=120
```

**Next:** native-free full workspace imports/local launcher and real authenticated
native browser. Full `WorkspaceRuntime` import still eagerly needs build123d in
unrelated workspace modules; its new injection/reload seam is structurally tested,
not server acceptance. Remote focus/explode, arbitrary views, non-current/last-good
provenance-less builds refuse; session bound is 16 render operations. Independent
security/render reviews, renderer-specific live cancellation, full native/golden
coverage, full pytest/pyright and final all-stage smoke remain unrun. Production
is closed; no full usable workspace or release certification is claimed.

## Render integration first scoped pass (2026-10-08; report label 20261009)

`dist/macos-render-integration-live-20261009-02/report.json` records fresh
**`renderer_stage_passed:true`, `executor_stage_passed:true`, `accepted:false`**.
Executor sub-run repeats all quota, actual CAD/publication/freshness, observed
explicit cancellation, timeout and ordinary-failure controls. Host inspection
produced nonempty 128×96 RGB, exact 38-entry solid/face/edge tables/masks and
measured kernel section **2 faces / 26 mm²**. Fresh `_mint_bundle` and worker
GLB publication passed: **2 meshes, 12 face primitives**, validated refs/IDs and
GC links. Image digest `sha256:74b97c7a131d1c5ce15b196e31b553cfe684b239ea4fcc7047a938c01096106e`;
llvmpipe LLVM 15.0.6/128 bits. Invalid BREP returned exit 1/non-OOM; all owned
workers/clients/groups/owners were removed/reaped, with journals retained.

Current focused suite: **935 passed**, zero skips, in
`dist/macos-render-integration-dev-20261009-01/focused-04.log`. Added shared
journal capacity admission, per-render owned sessions, exact numeric GLB binding,
source-input/executor/renderer cache identity checks and native-free linked-GLB
reader. These follow-ups require the final fresh source-specific rerun; this
first scoped pass is not evidence for later edits. Full HTTP runtime import still
requires host CAD through unrelated workspace modules; no server/browser startup
or complete workspace launcher is claimed. Next: final focused tests, final live
rerun and documentation. Production stays closed.

## Render integration first live refusal (2026-10-08; report label 20261009)

`dist/macos-render-integration-live-20261009-01/report.json` is **failed** and
remains `accepted:false`. Fresh executor stages passed. Real RGB, exact masks,
repeatability and integrated inspection/kernel section ran, but the thirteenth
renderer operation exhausted the existing 256-client session journal during a
manifest control, before GLB export. Cleanup correctly refused, retaining the
acknowledged owned ID. Explicit supported `reconcile(config)` reclaimed only that
owned resource; `dist/macos-render-integration-dev-20261009-01/reconciliation.log`
records completion. The original failure is not promoted to success.

Concrete fix in progress: admit a whole operation's cleanup capacity before any
side effect; retain the same journal bounds. Renderer requests now use separate
bounded per-operation supervision directories, close/recheck previous owners and
compare actual image identities across jobs. No record deletion or capacity
increase. Regressions and a fresh serial rerun follow. No build timed out.

## Render integration implementation checkpoint (2026-10-08; report label 20261009)

**In progress; `accepted:false`, no fresh integration pass yet.** Preserved the
actual dirty worktree and verified the sibling clean at its required baseline.
Added explicit `RenderProject`/`CadOps`/`WorkspaceRuntime.open(renderer=...)`
injection. Remote inspection branches before any host kernel/EGL call; native
paths remain explicit. `_mint_bundle` now renders genuine worker selection passes
through the same store publisher. A closed renderer API v2 adds actual preview
pixels and bounded linked GLB export; v1 refuses. Host validates GLB structure,
mesh/face IDs, source/bundle/table references before installing bytes. Bundle
resolution additionally checks recorded artifact kinds and GC links.

New files: `render/{defaults,glb_gate,remote_service}.py`,
`scripts/macos_renderer_live.py`. The renderer CLI now drives a fresh executor
sub-run instead of borrowing historical BREP. Host import checks pass without
CAD/NumPy/EGL. Initial boundary tests: **151 passed**, zero skips, in
`dist/macos-render-integration-dev-20261009-01/tests-initial.log`; this is not live
acceptance. Remaining: adversarial integration tests, fresh image/live controls,
fix concrete bugs, full focused regressions and accurate final docs. Browser,
independent reviews and full milestone remain pending; production stays closed.

## Final renderer-worker checkpoint (2026-10-08)

**Separate renderer implemented and live-tested; full `accepted:false`.**
`dist/macos-renderer-live-20261008-final/report.json` records
`renderer_worker_passed:true`, `renderer_cleanup_passed:true`. Exact source,
image input, installed identity, requests/pixels, bounded raw logs, terminal
state, limits and durable ownership/inventories are retained there.

- Native ARM64 image/config digest:
  `sha256:2783e3601e699ed77e50ffd41f06208fa5be88b6aabc674fdf9ec93469a40bea`.
  Actual renderer: **llvmpipe (LLVM 15.0.6, 128 bits)**; Mesa 22.3.6.
- Canonical 128×96 RGB, solid mask and all three selection passes; exact palette
  and 38-entry table validation. Two separate selection workers produced identical
  response/pixel hashes. Canonical kernel section: two faces, **26 mm²**, plus
  cap-shaded raster. Input is an explicitly hash-identified historical BREP, not
  a claim of fresh CAD in this renderer report.
- Invalid BREP failed with worker exit 1, no accepted output. Success exits 0;
  all terminal states non-OOM. Exact containers, clients/groups and owners absent
  and reaped; no pending settlement. Trusted preparation also durably tracks
  create intent and refuses ambiguous settlement despite an absence observation.
- Earlier executor gates remain green in a **fresh live rerun**:
  `dist/macos-executor-after-renderer-20261008/report.json`,
  `executor_stage_passed:true`, `accepted:false`. Image digest
  `sha256:f969c075c9975069c4db61ac3759099db752f05165c3a03ec896f8a39c669934`.
  Repeated quota controls, real CAD/publication, positively observed explicit
  cancellation, separate timeout/failure and exact cleanup passed.
- **889 focused tests passed, zero skips**. Logs and checkpoint hashes:
  `dist/macos-renderer-implementation-20261008-01/`. New tests cover closed schemas,
  exact palette/table/source binding, skew, image mismatch, malformed transfer,
  render failure/OOM/timeout and cleanup refusal, native-free host imports,
  pinned dependencies and pre-write cache admission. No weakened existing tests.

Implementation: new `core/src/hephaestus/core/render/oci_{protocol,launcher,worker,backend}.py`,
independent `docker/renderer/` locks/Dockerfile, `scripts/macos_{prepare_renderer,renderer_check}.py`,
`core/tests/test_render_oci.py`, `tests/test_macos_renderer.py`. Narrow shared changes
in OCI profile selection, transfer operation recognition and supervisor config
retain the unchanged CAD allowlist and executor journal compatibility. Renderer
package camera exports are lazy; `ChannelView.gl_renderer` records the real context.
See [renderer API, limits, evidence and next-slice contract](macos-renderer.md).

Reproduce serially with a new report directory:

```sh
PYTHONDONTWRITEBYTECODE=1 /opt/homebrew/opt/python@3.13/bin/python3.13 \
  scripts/macos_renderer_check.py \
  --report-dir "$PWD/dist/macos-renderer-independent-new" \
  --wheelhouse "$PWD/dist/macos-report-02/download/wheels"
```

Focused command (same worktree, no native CAD environment required):

```sh
PYTHONPATH=core/src:opstore/src:server/src .venv/bin/python -m pytest \
  core/tests/test_render_oci.py tests/test_macos_renderer.py \
  core/tests/test_oci_supervision.py core/tests/test_execution_identity.py \
  tests/test_macos_staging.py tests/test_macos_executor.py \
  tests/test_macos_executor_live.py tests/test_macos_feasibility.py \
  core/tests/test_sandbox_oci.py core/tests/test_sandbox_oci_network.py \
  core/tests/test_sandbox_oci_launcher.py core/tests/test_sandbox_oci_image.py \
  core/tests/test_sandbox_oci_transfer.py -q
```

**Next slice:** integrate every inspection and GLB publication call site with the
explicit renderer, preserving `_mint_bundle`, actual selection bundle/table/source
links, GC and executor-versus-renderer provenance/freshness. Then authenticated
native browser, independent security/render reviews and fresh all-stage smoke.
No web/browser integration, full render/publication acceptance, x86 rebaseline,
full suite/pyright or cross-runtime release certification is claimed. Production
remains closed. No providers/models/agents, global settings, commits, pushes,
unsafe CAD fallback or unrelated cleanup were used; sibling remains untouched.

## Renderer first live checkpoint (2026-10-08, superseded)

`dist/macos-renderer-live-20261008-05/report.json` has
`renderer_worker_passed:true`, full `accepted:false`. Actual native ARM64
`llvmpipe (LLVM 15.0.6, 128 bits)` produced 128×96 RGB, solid mask and all
three selection passes from the explicitly hash-identified historical two-solid
BREP input. Fresh kernel section: two faces, 26 mm². Separate selection workers
produced identical pixel hashes. Invalid BREP failed with exit 1; all successful
workers exited 0, all typed terminal states were non-OOM, and owned containers,
clients/groups and owners were independently absent/reaped after cleanup.
Image digest: `sha256:6bc547f49e7bfc610c40aaaad2ee6aedc155b1debb072858de2738351ca6529e`.
This report is source-specific; a stricter explicit renderer launcher limit check
and executor-compatible journal binding landed afterward and require a final rerun.

Honest failed attempts retained: `...-01` failed `pip check` for missing pinned
`packaging`; `...-02` live EGL import failed because PyOpenGL uses the image
linker cache; `...-03`/`...-04` exposed pyglet's eager XRender loader import.
Fixed with root-pinned packaging 26.2, image-local linker cache, and hash-locked
XRender/Xi/Xrandr/Xinerama client libraries. No display server, host setting,
dependency upgrade, monkeypatch or golden change. All builds were finite; none
timed out or used a timeout retry. No unrelated resources were removed.

Current new boundary suite: 126 passed, zero skips. Earlier shared executor
regression: 318 passed. Next: final all-focused executor/renderer regressions,
fresh final image/worker test, documentation and exact sibling/cleanup check.

## Renderer implementation checkpoint (2026-10-08, historical draft)

Inspected the actual dirty worktree, contracts, canonical offscreen/channels/
selection/kernel section and GLB `_mint_bundle` paths before editing. Sibling
remains clean at the required baseline; Docker Desktop is native Linux aarch64,
4,109,803,520 bytes RAM, with no running containers at inspection.

Implemented draft separate renderer profile/launcher/API, bounded closed BREP
requests and raw-pixel responses, canonical RGB/mask/selection/kernel section
worker, and explicit supervised `OciRenderer`. CAD allowlist and production
selection remain unchanged. Shared containment profile 5, run grammar 3,
manifest 4 and transfer 1 are retained; the disjoint renderer manifest extension
is version 1. No web/publication integration or acceptance is claimed.

Independent renderer Python additions are pinned to existing root `uv.lock`,
including PyOpenGL 3.1.0 source (trusted offline build only). ARM64 Debian
Mesa 22.3.6 / LLVM 15 closure has an independent URL/size/SHA256 lock. Public
pinned downloads completed via `scripts/macos_prepare_renderer.py`; cache and
bounded logs are under `dist/renderer-{python,native}-cache` and
`dist/macos-renderer-implementation-20261008-01/`. Initial package-index download
hit finite deadlines; a bounded range continuation completed it. No image build
or live render yet. Next: host boundary tests, offline image build, actual
llvmpipe probe/small BREP renders/failure and cleanup checks. Full `accepted:false`.

## Final real executor checkpoint (2026-10-08)

**`executor_stage_passed:true`; full `accepted:false`. 743 focused tests passed,
zero skips** (`dist/macos-executor-implementation-20261008-01/focused-final.log`).
Fresh final serial evidence:

- `dist/macos-executor-live-20261008-final/report.json`: executor CLI exit **0**,
  75.73 seconds; containment/build/cancellation/cleanup all passed with raw records.
  Image digest `sha256:d407de0986bebf19ad38df002ada86ded0aac153c302ac8bea4b996b02935930`,
  native Linux ARM64. Trusted toolchain fingerprint
  `sha256:ebb3896a89d12715a701a2aa90abc60562f808d3732de1b8a6a7a04f2b7fa21e`.
- `dist/macos-executor-milestone-20261008-final/report.json`: shared milestone
  implementation also **executor_stage_passed:true**, 76.88 seconds. Exit **1**
  correctly retains missing RGB/masks/section/linked-GLB/browser as unimplemented.
  Its separately attested image digest is
  `sha256:9959f317176d2a574aff3d8ace383a1138b490a99d9fbe5cb5f61d6c8a4bee13`;
  no source/report/image identity is borrowed from the other run.
- Both repeat all **13 storage controls**, 15 containment features and supervised
  ordinary-policy probes. Two solids, 162 mm³, 12 faces, 24 edges, sealed, bbox
  15×5×7 mm; actual exported BREP re-read in another fixed worker agrees. Actual
  source-map binding lines/namespace, transfer and canonical publication bytes,
  current result and freshness are checked. Real kernel/CAS evidence is in
  `kernel-validation.json`, `brep-roundtrip-result.json`, `published-result.json`,
  `freshness.json` and the retained project store in each report directory.
- Explicit cancellation records actual Docker start event, independent settled
  worker Running inspection, ordered user request/owner receipt, successful KILL,
  terminal exit137/non-OOM, exact absence and owner/client/child reaping. Separate
  timeout hits 20 seconds with exit137/non-OOM; ordinary ValueError has worker
  exit0, failed build and validated one-solid 6 mm³ checkpoint. No stopped run
  retains installed artifacts. `supervisor/`, `cancel-events/`, `timeout-events/`
  retain bounded raw logs/journals; `final-inventory.json` independently checks IDs
  and PID/groups. Unrelated stopped containers remain untouched; no workers remain.

Files changed in this slice: `scripts/macos_executor_check.py`, new
`scripts/macos_executor_live.py`, shared `scripts/macos_milestone_smoke.py`,
`tests/test_macos_executor.py`, new `tests/test_macos_executor_live.py`, related
macOS docs and executor README. Earlier core/supervisor/security implementations
are preserved. No production activation, source/image protocol widening, host CAD,
provider/agent/model, entrypoint override, global setting or dependency upgrade.
No timed-out image build/retry; identical image inputs reused cached build layers.

Exact independent executor rerun (new report path required):

```sh
PYTHONDONTWRITEBYTECODE=1 /opt/homebrew/opt/python@3.13/bin/python3.13 \
  scripts/macos_executor_check.py \
  --report-dir "$PWD/dist/macos-executor-independent-new" \
  --wheelhouse "$PWD/dist/macos-report-02/download/wheels"
```

Milestone rerun uses the same interpreter/arguments with
`scripts/macos_milestone_smoke.py` and a different new report directory; expected
exit **1** until remaining real stages exist. Full focused host command:

```sh
PYTHONPATH=core/src:opstore/src:server/src .venv/bin/python -m pytest \
  core/tests/test_oci_supervision.py core/tests/test_execution_identity.py \
  tests/test_macos_staging.py tests/test_macos_executor.py \
  tests/test_macos_executor_live.py tests/test_macos_feasibility.py \
  core/tests/test_sandbox_oci.py core/tests/test_sandbox_oci_network.py \
  core/tests/test_sandbox_oci_launcher.py core/tests/test_sandbox_oci_image.py \
  core/tests/test_sandbox_oci_transfer.py -q
```

Repository ruff/format pass; docs/license/diff checks and hashed checkpoint index
are recorded under `dist/macos-executor-implementation-20261008-01/`.
Full suite/pyright and the previously failing Darwin native-probe lane were not
rerun; its old failure/skips remain historical, not passing coverage. No Linux
native/backend-release or other OCI runtime certification is claimed. Sibling is
still clean `main` at `16a0021a535d5859a7a13ec283d23f764f4d377c`.

**Next:** secure separate ARM64 Mesa/EGL worker, all inspection and GLB publication
call sites, exact selection masks/kernel sections and `_mint_bundle`, actual
native authenticated browser, independent security/render reviews, then fresh
all-stage smoke. Render-dependent publication remains blocked; no fake mask,
selection bundle or screenshot substitutes for these gates.

## First real scoped executor pass (2026-10-08)

`dist/macos-executor-live-20261008-03/report.json`: **executor_stage_passed:true,
accepted:false**, 76.87 seconds. All fresh storage controls, real two-solid
162 mm³ CAD, second-worker BREP re-read, source-map/artifact CAS byte verification,
image-bound assembly/publication/freshness, observed explicit cancellation,
separate 20-second timeout, ordinary ValueError/checkpoint and exact owned cleanup
passed. Worker exits: build 0, user cancellation 137, timeout 137, ordinary failure
0 with `status:failed`; all typed terminal `Running:false, OOMKilled:false`.
Production remains closed; render/GLB/browser remain unimplemented.

Earlier attempts are retained: `...-01` hit a collector bug stripping opstore's
`sha256:` prefix after successful publication; `...-02` correctly refused the
roundtrip diagnostic's non-content-addressed input leaf. Fixed the collector and
used the existing 32-hex BREP name grammar, without changing backend gates.
All image input hashes across these runs are identical; the third build's log
records all build layers CACHED. No timed-out image build or retry occurred.
Additional host collector regressions cover canonical-vs-transfer bytes, closed
input names, missing journals/owners/observers, pending creates, unreaped clients,
live PIDs/groups/containers and missing owned IDs. `collector-tests.log` records
**228 passed** (collector + existing executor/harness suites). Next: final combined
focused tests, final fresh CLI and milestone invocation, docs/tooling checks.

## Executor integration checkpoint (2026-10-08)

**`accepted:false`; live run pending.** Preserved prior work and inspected branch
`feat/macos-feasibility`; sibling remains clean at the required baseline.
`scripts/macos_executor_live.py` now drives independently authored two-cuboid CAD
through `run_build`, real store publication/freshness and the supported supervisor.
The CLI and milestone share fresh image/storage/build/cancel/timeout/failure stages;
there is no report-import or production activation. Explicit cancellation waits
on passive daemon start events then independently inspects the settled worker;
no progress timer or attach-disappearance assertion substitutes for Running.

Report schema 3 corrects the historical synthetic schema's failure exit assumption:
the actual worker returns exit 0 with `status:failed` for ordinary script errors.
Old schemas 1/2, missing result status and malformed evidence still refuse.
Source-map transfer bytes and canonical publication bytes are recorded separately.
`dist/macos-executor-implementation-20261008-01/focused-01.log`: **729 passed**
using the prior full focused supervision/identity/storage/harness command below.
Next: serial fresh immutable ARM64 image/storage/CAD controls and fix actual defects.


## Final supervision host checkpoint (2026-10-08)

**`accepted:false`; 725 focused tests passed, zero skips.** Explicit
`SupervisedOciBackend` now runs each operation under a bounded, independently
spawned owner with fresh canonical OCI probes, immutable identity comparison,
durable pre-create names and client-spawn intent, acknowledged IDs, delivered
stops, actual client/group reaping and bounded exact-resource recovery. No global
service/helper, daemon settings, production activation, workload entrypoint or
storage/schema exception was added. See [the supervision contract](macos-supervision.md)
for supported injection, evidence and honest death/settlement limits.

- New: `executor/cancellation.py`, `sandbox/oci_ownership.py`,
  `sandbox/oci_supervisor.py`, `core/tests/test_oci_supervision.py` and its synthetic
  CLI fixture. `oci.py` retains canonical containment/transfer/OOM gates, adding
  ownership hooks, cancellation wakeup, explicit scratch placement and safer
  process-group termination before leader reaping.
- HTTP/MCP dispatch now delivers caller cancellation and awaits synchronous
  teardown. Explicit `cancel_active()` remains separately identified as user stop;
  timeout, parent EOF, owner signals, ordinary failure and cleanup uncertainty are
  not promoted to user cancellation. `WorkspaceRuntime` capability projection now
  probes its actual injection, retaining unsafe refusal.
- Unknown create settlement stays pending even after absence/reclamation; restored
  client spawn/reaping uncertainty and abrupt owner death also refuse reuse.
  Ordinary acknowledged, removed/reaped executions **do** permit clean reuse.
  Parent-death tests observe actual independent owner cleanup; they do not invent
  reaping evidence on behalf of the dead parent. Disk-full stop-record failure
  still delivers cleanup but remains an evidence failure.
- Per-operation collector writes actual source/input hashes, bounded command/raw
  wire evidence, image identity, fresh containment/effective config, transfers,
  terminal/OOM state, independent Running observation, stop receipt and reaping.
  It is not an imported JSON acceptance schema. Real CAD assembly/publication
  acceptance integration and live demonstration are still next-phase work.

Evidence: `dist/macos-supervision-20261008-01/`.
`focused-final-02.log`: **725 passed in 48.25s** (33 new supervision regressions
plus the earlier 692 identity/storage/harness tests). `process-evidence-final/`
retains bounded copies of actual final test controller/client records, explicitly
**synthetic-daemon / real host subprocess** evidence, not OCI or CAD. The source,
log and copied-record hashes and point-in-time owned-PID absence checks are in
`checkpoint.json`; durable fault records are retained, never cleared by those
absence observations. `python313-import.log` records the specified native Python
3.13 interpreter importing the stdlib supervision interfaces without starting a
worker. No dependency/golden upgrades were made.

Earlier failures remain: `supervision-01.log` (Darwin zombie-only group signal
EPERM); `focused-05.log` (zombie group EPERM during absence checking, fixed without
treating it as absence); `focused-final.log` (**724 passed, 1 failed**), where
putting the *whole* suite's pytest temp directory inside the checkout invalidated
an existing test's outside-checkout fixture assumption. The final rerun used its
normal external pytest temp root; no test assertion was changed or skipped.
`pytest-final/` retains that earlier run, not substituted for the final evidence.

Final ruff/format, docs, license and diff checks are logged under the report
folder. Full suite, pyright, full WorkspaceRuntime import/server tests (local
contract/CAD dependency closure absent), actual Linux clients, live Docker image,
storage/CAD/cancel/timeout/failure, render/browser and independent reviews were
**not** run. No Docker resources, image builds, servers, browsers, agents or
providers were launched. Sibling remains clean `main` at the required baseline;
prior uncommitted work remains, with no reset/clean/stash/commit/push.

Reproduce:

```sh
PYTHONPATH=core/src:opstore/src:server/src .venv/bin/python -m pytest \
  core/tests/test_oci_supervision.py core/tests/test_execution_identity.py \
  tests/test_macos_staging.py tests/test_macos_executor.py \
  tests/test_macos_feasibility.py core/tests/test_sandbox_oci.py \
  core/tests/test_sandbox_oci_network.py core/tests/test_sandbox_oci_launcher.py \
  core/tests/test_sandbox_oci_image.py core/tests/test_sandbox_oci_transfer.py -q
```

**Next:** fresh manifest-4 ARM64 image and trusted storage validation, then actual
CAD/assembly/publication/freshness, observed explicit user cancellation, timeout
and ordinary failure through the supported supervisor. Retain all earlier gates;
production discovery and full milestone acceptance remain closed. Renderer,
selection/section, `_mint_bundle`, authenticated browser, independent reviews and
final all-stage smoke remain required.

## Supervision implementation checkpoint — host regressions (2026-10-08)

**Implemented, not live accepted; `accepted:false`.** The explicit supported
backend and recovery contract are in [macos-supervision.md](macos-supervision.md).
Parent death, abrupt owner death, delayed create acknowledgement, cancel during
create/attach, actual client descendants, reaping/cleanup failure and restored
pending ownership now have host regressions. Unknown settlement remains pending;
ordinary acknowledged/cleaned executions and restored clean sessions can run.
Explicit user stop, caller/task cancellation, parent EOF, timeout and failure are
not conflated. HTTP/MCP await synchronous teardown; capability projection uses
WorkspaceRuntime's actual injection and still rejects unsafe execution.

`supervision-04.log`: **22 passed**. `focused-05.log`: **716 passed, 1 failed**;
the new real child-group test exposed Darwin EPERM during the *absence check*
while an orphan zombie was being reaped. This now waits within the existing
2-second group-reaping hang detector and still requires actual ESRCH, never counts
EPERM as absence. `child-group-06.log`: **1 passed**. Final combined rerun follows.
The previous 692-test suite passed in that combined run; failure was the new test.

Per-operation collector records actual bounded raw control bytes, streamed wire,
source/image/identity/limits, effective configuration, terminal/OOM state, owned
IDs and reaping, plus independent running observation and delivered stop receipt.
The next phase must integrate and run genuine CAD assembly/publication acceptance;
this collector cannot promote missing CAD/render/browser stages. No image rebuild,
Docker calls, CAD, providers, agents, browser or server ran in this host slice.
`runtime-import.log` retains the local missing `hephaestus.contract` dependency;
the runtime projection test executes only its real dependency-free method, not a
claimed full-server import/integration. Full suite/type-check not run.

## In-progress supervision checkpoint (2026-10-08)

**`accepted:false`; no live OCI/CAD/cancellation acceptance.** Prior uncommitted
work preserved; sibling inspected clean at the required baseline. Implementing
explicit `SupervisedOciBackend` injection, per-operation spawned owners, durable
pre-create names and acknowledged IDs, bounded transport control, recovery and
request-scoped async cancellation. No global daemon/service or production change.

Fresh host evidence: `dist/macos-supervision-20261008-01/`.
`baseline-after-hooks.log`: **692 passed** (existing identity/storage/harness gates).
`supervision-02.log`: **17 passed** (new tests; synthetic daemon, real local
supervisor/client subprocesses). Initial `supervision-01.log` exposed Darwin
EPERM signalling zombie-only groups: transport now keeps leaders unreaped while
signalling, then reaps and requires group absence. No permission failure is counted
as proven cleanup without that independent check.

Files: new `executor/cancellation.py`, `sandbox/oci_ownership.py`,
`sandbox/oci_supervisor.py`, `core/tests/test_oci_supervision.py` and its synthetic
CLI fixture; lifecycle hooks in `sandbox/oci.py`; HTTP/MCP dispatch cancellation
wiring and `WorkspaceRuntime` projection of its actual injected backend.
The collector writes actual bounded command bytes/prefixes, stream hashes,
identity/probe/effective config, input/output records, terminal state and reaping
records. It does not import a passing JSON ledger. Remaining work in this slice:
process-death/reaping faults, durable stop evidence, runtime wiring tests, focused
regressions and documentation. Fresh manifest-4 image/storage validation and real
CAD/cancel/timeout/failure demonstrations remain next-phase requirements.

Commands: `PYTHONPATH=core/src:opstore/src:server/src .venv/bin/python -m pytest
core/tests/test_oci_supervision.py -xq`; the previous checkpoint's 692-test command
was also run unchanged. No Docker commands/resources in this checkpoint.


## Final host checkpoint — trusted image-bound execution identity (2026-10-08)

**Implemented; `accepted:false`. No user CAD or live image acceptance.** See the
[identity contract](macos-execution-identity.md). Active **profile 5 / protocol 3 /
manifest 4 / transfer 1**. Production discovery/`PRODUCTION_OCI_IMAGE` are unchanged.
The executor precheck now names only the unresolved durable supervision blocker;
removing the implemented host-toolchain blocker does not open a CAD success path.

Changes:

- `core/src/hephaestus/core/executor/identity.py` and its
  `sandbox/oci_identity.py`: canonical deeply
  immutable identity, closed inventory schema, actual installed executor/opstore
  source hashes and package/version/METADATA inventory. Fixed launcher manifest
  collects this before any script, under existing bounded container control.
- `sandbox/oci.py`, `oci_protocol.py`, `oci_launcher.py`, `base.py`: mandatory
  manifest-4 inventory, daemon digest/config/platform binding, per-container image
  checks and host-owned outcome identity. Poisoned/changed backend identity fails
  closed, including cached capability reads. Profile/run/transfer remain unchanged.
- `runner.py`: capture and recheck control identity, reject wrong/missing outcome
  identity, discard script-supplied reserved metadata, persist the trusted record.
  Imports with no payload no longer eagerly import mesh numerics. Native hashing
  remains compatible; no host CAD packages were installed.
- `project_store/publication.py`: supported `backend=` injection, identity/hash
  consistency before artifact installation, shared live identity comparison for
  revalidation and freshness. BREP refs remain byte-addressed; immutable bundles
  change with executor inputs. Image repository aliases do not change the content
  fingerprint. Missing/wrong/unavailable identity cannot become fresh/current.
  Preview/failure/race/replay/GC/pointer contracts remain intact.
- `CadOps._publisher()`, CLI build and golden-fixture publication wire their actual
  backend. The base CadOps publisher factory no longer eagerly imports rendering;
  the full workspace/render/import-conversion integration is NOT claimed complete.
- `macos_probe_executor.py` records identity from the real backend. Executor report
  schema **2** uses the same fingerprint; old report schema **1** refuses. No report
  import/override or fake evidence path was added.

Host evidence: `dist/macos-execution-identity-20261008-01/`. `focused-final.log`:
**692 passed**, zero skips, including 49 identity regressions and the integrated
synthetic-daemon transfer → runner → publication → freshness check.
`checkpoint.json` and `source-sha256.json` retain actual source/log hashes and
explicitly no updated image/storage acceptance. `ruff-final-02.log`,
`format-final-02.log`, `docs-complete.log`, `license-complete.log` and
`diff-complete.log` are the final tooling results. Earlier failures are preserved:
preview fixture reused a default-retained record, failed fixture lacked its error
record, and the first CadOps test attempted the full dependency-heavy assembly.
`focused-04-refusal.log` records the old cache-test fixture lacking the now-required
identity; it now supplies the synthetic control identity. A new negative test
proves containment features alone cannot pass without identity. Fixtures exercise
valid distinct records and the actual publisher factory; no dependencies/goldens,
platform checks or behavioral assertions were weakened to pass. Prior
`focused-03.log` (691 passed) is not substituted for this final run.

Additional native-backend exploration in `backend-contracts.log`: **26 passed,
1 failed, 6 skipped**. `test_incomplete_passing_bwrap_cache_is_rejected` expects a
Linux reprobe callback but Darwin returns `bwrap is supported only on Linux`
before reaching it. Command: `PYTHONPATH=core/src:opstore/src:server/src
.venv/bin/python -m pytest core/tests/test_sandbox_base.py
core/tests/test_sandbox_probe.py -q`. The probe/bwrap code and test are unchanged. This run is
**not passing Linux coverage**; no platform check or test was waived. Full suite,
full pyright, actual Linux backends, live image identity, CAD/render/browser and
cancellation acceptance were not run. No Docker commands or resources were launched.
Separate `native-pure-contracts.log`: **35 passed**, zero skips, from the unchanged
sandbox-base tests and hashing classes `TestHashText`, `TestEffectiveParamsHash`,
`TestConsumedHcHash`, `TestParamsDeclarationHash` (explicit pytest node selection,
not the CAD-installed `TestToolchainHash` class).

Reproduce the focused host slice (no CAD dependencies):

```sh
PYTHONPATH=core/src:opstore/src:server/src .venv/bin/python -m pytest \
  core/tests/test_execution_identity.py tests/test_macos_staging.py \
  tests/test_macos_executor.py tests/test_macos_feasibility.py \
  core/tests/test_sandbox_oci.py core/tests/test_sandbox_oci_network.py \
  core/tests/test_sandbox_oci_launcher.py core/tests/test_sandbox_oci_image.py \
  core/tests/test_sandbox_oci_transfer.py -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

**Next:** rebuild the executor wheel/image from this source and rerun the trusted
small storage gate; manifest-3 images now correctly refuse. The prior independent
storage report `dist/macos-storage-gate-20261008T020845Z/report.json`, image
`sha256:db15fdc3217374bda0e354c77b27feb0c27c3b634013d9875408876faddcb166`, passes
only its recorded source/image. No current-source staging pass is inferred.
Then implement durable owned create/cancellation supervision and its positive
in-flight/delivered-stop evidence before any user CAD acceptance. Independent
identity/security review and later render/browser/final smoke remain due.

## Earlier implementation checkpoint — identity wiring (2026-10-08)

**`accepted:false`; no live CAD, cancellation, render or browser acceptance.**
New source is **profile 5 / protocol 3 / manifest 4 / transfer 1**. The independent
storage gate at `dist/macos-storage-gate-20261008T020845Z/report.json` remains
historical evidence for its recorded source/image, not certification of these
changes. Rebuild the executor wheel/image and rerun storage controls before
claiming staging for this updated source. No Docker operations in this slice.

Implemented `executor/identity.py`, `sandbox/oci_identity.py`, manifest inventory,
host attestation binding, outcome-to-runner consistency, publisher backend
injection, and shared publication/freshness identity comparison. Fixed manifest
runs measure installed executor/opstore source bytes plus Python and distribution
versions/METADATA hashes, independently of script execution. The host binds them
to daemon-attested immutable RepoDigest/config ID/platform and verifies the config
ID on each created container. The reserved result metadata carries the canonical
identity durably; worker-supplied identity text is discarded. Native hashes and
byte-addressed BREP refs remain unchanged; build bundles change with identity.
`CadOps._publisher()` and CLI/golden build publication use their actual backend.

Evidence under `dist/macos-execution-identity-20261008-01/`:
`focused-initial.log`: **622 passed** (current focused OCI/storage/harness suite).
`identity-initial.log`: **44 passed, 1 failed** in the new synthetic host tests;
the preview retention fixture reused an identical default-retained record. The
fixture now uses a distinct transient parameter snapshot, preserving the store's
existing retention-promotion semantics. `ruff-initial.log` records formatting
issues before formatting. No kernel evidence is inferred from these tests.

Next: finish host regressions (source changes, wrong/missing identity, cross-
backend publication/freshness, failed/preview/replay/GC), rerun focused checks,
and record final source hashes. Supervision remains a prerequisite for user CAD;
production discovery and `PRODUCTION_OCI_IMAGE` remain untouched and fail-closed.

## Historical checkpoint — storage review fixes live-tested

**`staging_stage_passed:true`; `executor_stage_passed:false`; `accepted:false`.**
Fresh report: `dist/macos-staging-review-live-20261005-02/report.json`.
Native ARM64 image config/digest:
`sha256:92ed96672af9605e2c9250a0e0362f8be03fdf37cb66e5c1bd4f8eb5efbf1758`.
Active **profile 5 / protocol 3 / manifest 3 / transfer 1**. All six staging checks,
15 containment features and **13** serial fixed storage controls passed. No CAD,
provenance, render, browser, user cancellation or provider/agent acceptance work.

Actual observations: `/proc/interrupts`, `/proc/kcore`, `/proc/keys` and
`/proc/timer_list` are character devices (`file_type:8192`, major/minor **1:3**).
`/proc/latency_stats` reports explicit **ENOENT=2** and has no mount. Missing/type-
mismatched evidence still refuses. Work/tmp byte exhaustion independently wrote
8,388,608 / 2,097,152 bytes; inode controls created 127 / 63 files, with ENOSPC and
recovery. All controls have typed terminal exit 0, `OOMKilled:false`, and exact
owned-container absence; stdout overflow returns host **125**, not worker success.

Partial-body control actually collected **9,216 bytes** into `last_good.brep`;
artifact-truncated-footer collected **18,432 bytes**. Both refused and removed all
partial collection without installation. Fixed finite 384 KiB stdout emitter hit
the 335,872-byte attach bound (`logs/115-oci.json`, `TransportOutputLimit`, stdout),
after collecting 18,432 artifact bytes; no output accepted. Raw wire prefixes,
container state/config logs, body counts, empty collection checks and unchanged
outside sentinels are saved, not inferred from a report label. Daemon logs stayed
`none`; attached stderr positive control remains below its limit.

Host evidence: `dist/macos-staging-review-development-20261005-01/`:
`focused-final.log` **622 passed**, no skips. Integrated P1 tests use a real attach
subprocess plus synthetic daemon state (not a live injected host-filesystem fault)
and assert client reaping, kill/removal/absence, original failure chaining, no
accepted artifacts and poisoned reuse on uncertain reconciliation. P2 tests reject
regular files/directories/symlinks/wrong devices and absent-stat/present-mount
contradictions. Fixed live-control emitter tests check actual partial body bytes.
The failed first live report and initial test/lint failures remain untouched.
No image build timed out; no timeout retry was used. The second build was for the
concrete explicit-absence fix, reusing unchanged hash-verified inputs/cache.

`checkpoint.json` / `verification.log` independently reparse saved raw wire for
the three new controls and verify actual body bytes/footer truncation, matching
source/image-input/harness hashes (zero mismatches), zero running/owned containers,
removed owned image tags and the same ten unrelated stopped IDs/names/states.
Sibling remains clean main at `16a0021a535d5859a7a13ec283d23f764f4d377c`.
`verify_checkpoint.py` records the bounded read-only inspection commands.
`ruff-check-final.log`, `ruff-format-final.log`, `docs-check-final.log`,
`license-check-final.log` and `diff-check-final.log` passed; the final documentation
addendum is rechecked in `docs-check-complete.log` / `diff-check-complete.log`.
No full suite or pyright was run.

Commands (all reports new; only the scoped staging gate exits zero):

```sh
PYTHONDONTWRITEBYTECODE=1 /opt/homebrew/opt/python@3.13/bin/python3.13 \
  scripts/macos_staging_check.py \
  --report-dir "$PWD/dist/macos-staging-review-live-20261005-02" \
  --wheelhouse "$PWD/dist/macos-report-02/download/wheels"
PYTHONPATH=core/src:opstore/src:server/src .venv/bin/python -m pytest \
  tests/test_macos_staging.py tests/test_macos_executor.py \
  tests/test_macos_feasibility.py core/tests/test_sandbox_oci.py \
  core/tests/test_sandbox_oci_network.py core/tests/test_sandbox_oci_launcher.py \
  core/tests/test_sandbox_oci_image.py core/tests/test_sandbox_oci_transfer.py -q
```

Next: independent storage re-review of these fixes/evidence; preserve these gates
in later work. No genuine external runtime limitation remains in the tested small
storage scope. Ordinary-policy CAD capacity, other runtimes, full suite/pyright,
trusted executor provenance, durable external create/cancellation ownership and
all render/browser stages remain unproven. Production discovery remains closed.
No commits, pushes, global settings, unrelated cleanup or sibling edits.

## Earlier review-fix checkpoint — first fresh live refusal

`dist/macos-staging-review-live-20261005-01/report.json` exited **1** after
native dependency hash checks, offline image build and immutable resolution
succeeded. The launcher refused with `storage_observation_failed` before the
containment worker (raw `logs/032-oci.json`); no controls ran and scoped staging
remains false for this run. Image:
`sha256:4a6b96d1ad17673255042acd7ca64e973e92a12331271be51cd678fd82329a68`.
Cleanup passed; no build timeout/retry. The previous mount inventory has no
`/proc/latency_stats`. Collector refinement now records explicit no-follow ENOENT
for absent paths, accepted **only if mountinfo independently has no mount there**;
a mounted path with missing/type-mismatched observation still refuses. This is not
a tmpfs exemption. Added corresponding negative tests and actual received-body
byte accounting. Next: focused checks and one fresh source rebuild/control run.

### Implemented review fixes

Scope: storage/transfer only; full **`accepted:false`**. Prior reports are
historical, not evidence for the modified source. Fixed `oci.py` with an
unconditional post-submission lifecycle guard (including grouped receiver/unlink
errors), retained unreconciled known IDs and permanently refused instance reuse
on uncertain cleanup. Tests combine the real streaming attach subprocess and
receiver with synthetic running-container state; kill/removal/absence, client
reaping, no accepted output, exception preservation and poisoned reuse are asserted.
This is not durable ownership or delivered live user cancellation acceptance.

`oci_storage.py` now collects bounded no-follow file type and device major/minor
for all five proc masks, requiring Linux null character devices (1:3). Missing,
regular-file, directory, symlink and wrong-device evidence refuses. This mandatory
observation change advances **profile 4 → 5**, keeping protocol 3 / manifest 3 /
transfer 1 (their grammars are unchanged). Old profile-4 manifests/probes refuse;
version tests changed only with that implementation and explicit rejection tests.

Added fixed partial-body, artifact-truncated-footer and finite 384 KiB stdout
overflow controls to the trusted storage worker and `scripts/macos_staging_check.py`.
The live gate now requires actual collection creation, no partial/installed output,
typed non-OOM terminal state, exact owned absence and unchanged host sentinels.
No CAD, provenance, renderer, browser or provider work in this slice.

Fresh host evidence: `dist/macos-staging-review-development-20261005-01/`.
`focused-02.log`: **614 passed**, no skips, using the focused command below.
`focused-01.log`: 610 passed / 4 failed in new test fixtures (state JSON omitted
its required newline); fixtures corrected, assertions retained. `group-debug.log`
retains investigation. Next: lint/format, fresh bounded Docker preflight, native
hash-verified rebuild and the full relevant staging controls; do not reuse a
historical staging pass. Independent storage review is not yet discharged by live
evidence. All later milestone gates remain closed.

## Historical final checkpoint — before independent storage review

**`staging_stage_passed:true`; `executor_stage_passed:false`; `accepted:false`.**
Final fresh report: `dist/macos-staging-live-20261005-04/report.json`.
Image config/digest:
`sha256:8ce42b37345ccc54e5151f356930cfcc7420cf96f56e853f173fe37682644360`,
Linux ARM64. This repeated all six required scoped checks and all 15 containment
features after the follow-up code changes described below. Ten serial controls
passed, including independent real byte/inode ENOSPC on **both** tmpfs mounts,
input EROFS, deterministic bytes/hashes, malformed-transfer refusals, logging and
owned cleanup. No user CAD, live DFM, renderer, browser, provider or agent ran.

Implementation, supported limits, exact hashes and limitations:
[macos-staging.md](macos-staging.md). Source/image input manifests and bounded raw
logs are retained in each report; failed `...-01`/`...-02` reports are untouched.
Successful `...-03` is a prior source snapshot, not substituted for `...-04`.
No image build timed out or used a timeout retry. Trusted preparation caches were
reused/revalidated. Four report trees retain approximately 1.85 GiB total of
reviewed build inputs/evidence; no unrelated resources were deleted or pruned.

Final host evidence: `dist/macos-staging-development-20261005-01/`:

- `focused-final.log`: **558 passed in 1.13s**, zero skips. Includes the 151
  adversarial transfer tests and 53 new staging tests. Initial 34 failing old
  grammar/lifecycle fixtures are preserved in `focused-initial.log`; tests were
  updated for coherent protocol/schema changes, with explicit old-version refusal.
- `ruff-check.log`, `ruff-format.log`, `docs-check-final.log`, `license-check-final.log`,
  `diff-check-final.log`: all passed. Full pytest and pyright were not run.
- `checkpoint.json`: hashes reports/logs; **zero** current-source vs built-image
  source-manifest or host-harness mismatches. All ten original unrelated stopped
  container IDs/states unchanged; no owned IDs or running containers remain.
  Sibling checkout is still clean main at
  `16a0021a535d5859a7a13ec283d23f764f4d377c`.
- `cad-precheck.log` and
  `dist/macos-staging-cad-precheck-20261005-01/report.json`: real native preflight,
  expected exit **1**, with only trusted image-bound provenance and durable
  external create/cancellation ownership blocking CAD. Storage blocker removed
  after integrated live acceptance, not by a report-schema assertion.

Commands used:

```sh
PYTHONDONTWRITEBYTECODE=1 /opt/homebrew/opt/python@3.13/bin/python3.13 \
  scripts/macos_staging_check.py \
  --report-dir "$PWD/dist/macos-staging-live-20261005-04" \
  --wheelhouse "$PWD/dist/macos-report-02/download/wheels"
PYTHONPATH=core/src:opstore/src:server/src .venv/bin/python -m pytest \
  tests/test_macos_staging.py tests/test_macos_executor.py \
  tests/test_macos_feasibility.py core/tests/test_sandbox_oci.py \
  core/tests/test_sandbox_oci_network.py core/tests/test_sandbox_oci_launcher.py \
  core/tests/test_sandbox_oci_image.py core/tests/test_sandbox_oci_transfer.py -q
```

Use a **new report path** to repeat the live command. Next slice: trusted executor
image/toolchain identity through assembly/publication/freshness, then durable
owned create settlement and delivered user cancellation before real CAD acceptance.
Keep staging gates green while shared APIs change. Production discovery stays
closed. Ordinary-policy CAD capacity, import conversion isolation, other runtimes,
render/publication call sites, authenticated browser, independent reviews and final
all-stage smoke remain unproven; no usable experimental workspace is claimed.

## Earlier live checkpoint — first pass, superseded by final source run above

`dist/macos-staging-live-20261005-03/report.json` passed all six staging checks
through the real backend/launcher/PID1 workers, with 15 fresh containment features.
Image config/digest: `sha256:a2367c4333dcafbd71cea66a0870c65dc7bea4fce1b16528996448de65d47159`,
Linux ARM64. Ten serial storage controls exited 0 with typed `OOMKilled:false`
and independent owned-container absence checks. `/work`: 8,388,608 bytes /128
inodes (127 free); `/tmp`: 2,097,152 bytes /64 inodes (63 free). Real non-sparse
writes exhausted all available bytes with ENOSPC; separate empty-file controls
exhausted all free inodes while retaining all byte capacity. Recovery passed.
Positive input/output bytes and hashes, input EROFS, four malformed transfer
refusals and finite attached stderr with daemon logging disabled all passed.

Failed reports `...-01` and `...-02` remain intact. The first had insufficiently
specific launcher diagnostics; the second showed Docker still mounts writable
POSIX `/dev/mqueue` with `--ipc=none`. No allowlist exception was made. The profile
now masks it with a fixed 4 KiB /1-inode **read-only** tmpfs, mode 0000, and checks
both effective config and actual mount/write denial. No image build timed out;
no timeout retry was used. About 462 MiB/report of trusted build inputs remain.

Follow-up host regressions preserve native worker `main()` behavior, verify
build/DFM transport routing and bounded DFM admission without CAD, reject stale
manifests and source-map type mismatches before installation, and freeze the
public per-instance storage policy. **558 focused tests passed**, zero skips, in
`dist/macos-staging-development-20261005-01/focused-04.log`. Final fresh integrated
run for this follow-up source snapshot is next; the `...-03` image identifies
its own source, not later edits. Storage blocker removed from executor precheck;
trusted image-bound provenance and durable external create/cancellation ownership
remain explicit refusals. No CAD/render/browser acceptance claimed.

## Earlier current-run checkpoint — implementation, not yet accepted

Branch/runtime inspected: `feat/macos-feasibility`, Docker `desktop-linux`, Linux
ARM64, 4,109,803,520-byte VM, zero running containers. Sibling clean at the original
baseline. Prior work preserved. No CAD/provider/model calls.

Implemented draft integration in canonical `oci.py`, launcher, build/DFM workers,
input admission, strict storage observations, fixed stdlib storage worker and
`scripts/macos_staging_check.py`. Profile/protocol/manifest now 4/3/3 in source;
new images and live evidence are still pending. Host outputs are not mounted;
framed receiver installs only after terminal/non-OOM/removal checks. Daemon logs
are disabled. Ordinary and small control policies are distinct instance gates.

Initial focused regressions: **471 passed, 34 failed**, retained at
`dist/macos-staging-development-20261005-01/focused-initial.log`. These include
old grammar/version fixtures and lifecycle doubles needing real streaming/config
responses; no assertion has been waived. Next: update coherent fixtures, add
integration/adversarial tests, run fresh trusted live controls and resolve actual
runtime incompatibilities without weakening containment. Full acceptance false;
staging not yet passed. The transfer checkpoint below is historical.

# Previous bounded transfer checkpoint

## Scope and current gate

Host-only recovery of the unfinished bounded input/artifact transfer library.
**Full acceptance remains false; CAD precheck remains blocked.** No containers,
CAD, providers, agents, image builds or browser were run in this slice. The sibling
`../hephaestus` was observed clean on main at
`16a0021a535d5859a7a13ec283d23f764f4d377c`; it is not modified.

Fresh evidence: `dist/macos-transfer-checkpoint-20261005-01/`. Original transfer,
storage and protocol drafts were copied there before edits (not overwritten).
No reset/clean/stash/commit/push or cleanup of unrelated resources.

## Checkpoint 1 — active baseline recovered

- Restored **active protocol 2 / manifest 2 / profile 3**, 256 MiB `/tmp`, three
  actual workers and the existing 14 containment features. Removed premature
  claims about transfer, logging and storage from the active manifest. Profile-3
  network validation, strict schema, OOM/state evidence, ambiguous-create refusal
  and artifact/publication hardening remain intact.
- Isolated future limits/worker names in `sandbox/oci_storage_policy.py`.
  `SandboxSpec.input_files` is explicitly reserved, not an active storage feature.
  `oci_storage.py` is an **inactive observation draft**, not validated containment.
- Existing focused command (below, without transfer tests): **352 passed**,
  `existing-tests.log`. This is fresh, not the older historical 352-pass run.
- Rewrote `sandbox/oci_transfer.py`: bounded framed writer/receiver, strict JSON,
  fixed artifacts, descriptor-relative file admission, exclusive snapshot writes,
  rollback, short IO, explicit EOF/close/install semantics. Integration is absent.
- Initial new transfer tests: **140 passed, 1 failed**. Failure was the synthetic
  UNIX socket fixture exceeding Darwin's socket path length, before admission was
  tested. Fixture corrected to bind at a short owned temporary path and rename;
  assertions were not relaxed. Final rerun pending at this checkpoint.

## Commands and next action

```sh
PYTHONPATH=core/src:opstore/src:server/src .venv/bin/python -m pytest \
  tests/test_macos_executor.py tests/test_macos_feasibility.py \
  core/tests/test_sandbox_oci.py core/tests/test_sandbox_oci_network.py \
  core/tests/test_sandbox_oci_launcher.py core/tests/test_sandbox_oci_image.py \
  core/tests/test_sandbox_oci_transfer.py -q
```

## Checkpoint 2 — host transfer tests green

The full focused command above passed **503 tests (352 existing + 151 new)**,
zero skips, in `focused-tests-02.log`, repeated after final code edits in
`focused-tests-final.log` (**503 passed in 1.44s**). Repository ruff check/format,
docs, license headers and `git diff --check` all passed; see `ruff-check-final.log`,
`ruff-format-final.log`, `docs-check.log`, `license-check.log`, `diff-check.log`.
`checkpoint.json` records the host platform, exact source/log SHA256 values,
commands and scoped outcome, with `accepted:false`, `storage_stage_passed:false`
and `executor_stage_passed:false`. No worker terminal state/image is invented. The initial socket-fixture failure is retained in
`transfer-tests-initial.log`; no test assertion or security gate was waived.

New tests use explicitly synthetic bytes, not kernel geometry. They exercise all
two-chunk split positions and all truncation positions, single-byte feeds, strict
JSON and version/nonce/op/length/count/digest rejection, exact artifact sets,
no-follow ancestors/leaves, links/FIFOs/sockets/devices, aggregate admission,
exclusive paths, collection mutation, short IO, write/interruption/cleanup errors,
and install rollback. Four-MiB bodies passed through receiver, writer and input
snapshot with measured Python allocation peaks below 512 KiB per operation (input
fixture and wire constructed before tracing; JSON/result memory is separately
bounded). This is not a process-RSS or workload-memory measurement.

Concrete draft repairs: removed the unwired `worker_context()` invocation parser
and unsupported storage worker from active launcher allowlisting; typed transfer
records/JSON/streams; bounded directory enumeration; no chmod of a caller's path
before no-follow validation; nonempty snapshot destinations refuse; no whole-feed
buffering; writer handles partial writes; cleanup attempts every owned leaf and
raises on uncertainty. Installation requires declared EOF and verifies collected
hashes again. Caller must still hold private directories exclusively, check worker
terminal/OOM/cleanup state, close the receiver before publication, and run existing
full result/source-map/provenance gates. This library does not attest CAD results.

`oci_storage.py` was inspected, not certified: its unbounded procfs read, loose
nested dict typing, incomplete mount/path schema and permissive missing-path errno
handling need replacement/review at quota integration. It imports only the isolated
future policy now and has no active callers. No storage feature is advertised or
made to pass by this draft. The profile-4/protocol-3/manifest-3 draft is preserved
in the fresh report directory for the later coherent integration.

No live storage or CAD acceptance is inferred from these tests. Full repository
pytest, pyright, CAD/publication integration and live runtime checks were not run.

Final lightweight checks:

```sh
.venv/bin/ruff check .
.venv/bin/ruff format --check .
/opt/homebrew/opt/python@3.13/bin/python3.13 scripts/docs_check.py
/opt/homebrew/opt/python@3.13/bin/python3.13 scripts/license_headers.py --check
git diff --check
```

Final sibling inspection again showed clean main at the baseline SHA. No Docker
commands were needed for this host-only slice; no runtime inventory/live cleanup
claim is made. Owned container/image/browser/server resources created: **none**.

## Integration plan (later slices, not enabled here)

1. Review/replace the inactive storage observations with bounded Linux-specific
   closed-schema evidence. Implement `/work` and `/tmp` byte **and inode** quotas,
   RO bounded `/inputs`, all writable-surface inspection, no daemon logs, effective
   configuration/image checks. Add upstream import/DFM admission **before** staging.
2. Integrate this experimental transfer through bounded attached stdout and fixed
   PID1 worker pre-exit export. No post-exit `docker cp`; no output host mount.
   Version profile/protocol/manifest coherently only when launcher, real workers,
   transport and probes implement the contract. Native build/DFM stay unchanged.
3. Require EOF, result-schema/artifact agreement, non-OOM typed terminal state,
   expected exit and confirmed cleanup before installing/accepting artifacts.
   Stream hashes/nonce are corruption/identity checks, **not provenance**.
4. Small trusted storage diagnostics establish real byte/inode exhaustion and
   transfer/logging controls before CAD. Then trusted image provenance through
   assembly/publication/freshness, durable create ownership and real delivered
   cancellation, executor acceptance, render/publication, authenticated browser,
   independent reviews and final fresh all-stage smoke. Production discovery and
   `PRODUCTION_OCI_IMAGE` remain fail-closed throughout this local checkpoint.
