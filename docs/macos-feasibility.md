<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# First macOS feasibility milestone (experimental, not a release)

**Status: CI stabilization pending; production closed. Historical live acceptance
is superseded for changed runtime sources until a fresh all-stage run succeeds.**
See the [roadmap](macos-roadmap.md) and current [review results](macos-progress.md).
Do not merge on the historical evidence below.
`dist/macos-final-reviewed-20261012T152211Z/report.json` records a complete
`accepted:true` run: native ARM64 containment/quota controls, real two-solid CAD
and image-bound publication, delivered cancellation distinct from timeout/failure,
Mesa/EGL RGB and exact masks, kernel sections, canonical `_mint_bundle`/12-face
GLB, authenticated native Chrome, real HTTP build and owned cleanup. Active
versions remain profile **5**, protocol **3**, manifest **4**, transfer **1**.
See [progress](macos-progress.md) for exact hashes, failures and review repairs;
[local workspace](macos-workspace.md) documents the tested explicit launcher.
Production discovery remains disabled; this is not full-product/release support.

The final independent report's SHA256 is
`df0fa8086de37a4add4bf4773a4e9ecaf9d686f869b364ad7a7b64d42b93370a`.
All 13 required stages passed. Before PR packaging, all 457 host, 173 executor
and 173 renderer source-manifest entries matched files at that historical
checkpoint, before the regression/type repairs. They no longer match. Reports,
images, ownership journals and browser profiles remain local under ignored
`dist/`; these paths are evidence references, not files shipped in the PR.

The interrupted `...review-final` report remains `accepted:false`; its missing
parent-reap acknowledgement permanently refuses that old session. Both later
successful runs used fresh sessions, not promoted historical evidence. To repeat
the independent gate, use a new report directory and the documented 2400-second
outer wait without changing worker/build limits.

Root pyright and the native HTTP-boundary fixture still fail, unwaived. Focused
host/web passes are not full-suite certification. Browser picking proves actual
raycast/context resolution, not the absent selection-popover workflow; retained
open dimension findings mean a successful build is not design-requirement
completion. Earlier storage/executor reports and the observed-results section
below are historical, not authority for later source changes.

## Authority and baseline

Development used a separate `hephaestus-macos-feasibility` worktree on branch
`feat/macos-feasibility`, based on `16a0021a535d5859a7a13ec283d23f764f4d377c`.
The original `main` checkout remains untouched. The operator subsequently
explicitly authorized commits and a remote compatibility PR; the earlier
local-only publication restriction in those earlier entries is historical.
The current review explicitly permits **no further commits or pushes**.
Production OCI remains disabled.
Read `CONTRIBUTING.md`, `repo_conventions.md`, and `docker/executor/README.md`
before extending this work.

Provenance disclosure: Nurb source (FSL-1.1-MIT) was inspected separately during
feasibility research. No Nurb code or assets were transplanted into this Apache-2.0
project. The implementation and diagnostic fixtures use existing Hephaestus
contracts and public build123d APIs; no vendor CAD or benchmark answers ship.

Initial observed environment: Darwin arm64 (operator reports Apple M2, 8 GB RAM),
Docker context `desktop-linux`, Linux aarch64, 4,109,803,520 bytes VM memory,
8 advertised CPUs, zero running containers. Ten unrelated **stopped** containers
exist; none belongs to this milestone. Do not remove or restart them.

## Architecture decisions

1. Native ARM64 Linux OCI workers; native Mac browser using the existing Three.js
   viewport. No amd64 emulation and no browser screenshot renderer substitute.
2. Use explicitly constructed `OciRuntime` / `OciBackend` instances in development
   tooling only. Validate local Unix endpoint and Docker Desktop identity; select
   image by registry-qualified sha256 digest and run the existing exact manifest
   and containment probes. Never set `PRODUCTION_OCI_IMAGE`, mutate a passing
   report, or monkeypatch `secure_backend`. Normal macOS CLI remains fail-closed.
3. Build the existing renderer-free executor package/image first. Its CPython
   3.13.7 base, hashed wheels and architecture-specific native closure are
   supply-chain inputs. A tag or image config ID is not a RepoDigest. If needed,
   use an owned registry published ONLY on 127.0.0.1, with local storage and no
   external pushes/credentials; stop/remove it after resolving the local digest.
   **Measured on this daemon:** its containerd image store already records a
   RepoDigest after a registry-qualified local tag. The harness now inspects that
   daemon-reported ref and resolves it again by digest, without any registry,
   push or fabricated metadata. Other image stores may fail this stage.
4. Keep Mesa/EGL as canonical rendering. Prefer a separate, immutable render
   worker image with no socket, project or home bind. The current OCI protocol
   allows ONLY build, DFM, containment and fixed stdlib storage-control modules:
   it is NOT an arbitrary Python runner.
   A render worker needs a separately reviewed/versioned protocol/profile and
   strict probes, not an extra command smuggled through build stdin.
5. Rendering boundary must cover the full call graph:
   `inspect_part -> _render_channel -> channels.render_channel` (RGB/section),
   `inspect_part -> _render_selection -> OffscreenSession` (selection), and
   `publish_gltf_for_build -> _mint_bundle -> OffscreenSession` (GLB provenance).
   Kernel sectioning lives below `channels`, not in Three.js clipping. Forwarding
   only inspection leaves fresh GLB publication trying to load Linux EGL on Mac.
6. Host owns the project/store/leases. Workers receive bounded frozen inputs in
   private per-job staging, never a project-root mount. Render outputs must be
   validated and published through existing artifact kinds, selection tables,
   bundle/source links and GC edges. Do not share a live SQLite store with workers.
   Validate GLB source/bundle/table and mesh count before publication; stale or
   unlinked selections must refuse. Do not synthesize mask bytes.
7. `WorkspaceRuntime.open(backend=...)` is the explicit injection seam; retain
   `serve_mode=True`. Its `_secure_executor_available` now probes that actual
   injected backend, not a second production factory, while retaining unsafe
   refusal. The explicit launcher now exercises real workspace startup and HTTP
   build with this injection. Agent attachment remains disabled; no model or
   provider is needed for the milestone.
8. Cancellation needs a positive in-flight edge and container identity. Cancelling
   an `asyncio.to_thread` await does not interrupt synchronous `OciBackend.execute`.
   Use an owned supervisory process with a delivered cancellation signal, bounded
   reaping, and verified container absence. Do not count wall timeout as user
   cancellation or disappearance of the Docker attach client as worker death.

## Shared safety/resource constraints

- No unsafe backend, privileged mode, host network, Docker socket inside workers,
  home/project-root bind, security-check bypass, fabricated passes, fake masks,
  skipped-test-as-pass, dependency upgrade or golden rebaseline.
- Public downloads/project-local tools only. No global upgrades, daemon settings,
  prune/reset/clean, deletion of unrelated resources, remote publication or API calls.
- Serial builds/tests; at most one heavy worker. Target worker envelope: one CPU,
  <=2 GiB resident memory, <=256 PIDs, <=120 CPU seconds / <=180 wall seconds,
  bounded stdout/stderr and staging output. Reduce via supported request seams;
  do not relax security maxima or native limits to make a test pass.
- The current capability probe and trusted storage controls request 256 MiB,
  32 PIDs, one CPU, 15 CPU seconds and 30 wall seconds. Protocol maxima remain
  ceilings, not reservation or local CAD admission. Later CAD must request and
  prove the tight envelope independently.
- All execution workers: nonroot numeric identity, readonly root, network none,
  all capabilities dropped, no-new-privileges, private namespaces, cgroup/rlimits,
  `/work` and `/tmp` byte+inode-bounded noexec tmpfs, RO bounded `/inputs`, no host
  output bind and no daemon logs. Render integration must retain these guarantees.
- Track exact owned IDs/names before launch; finally/signal cleanup must kill,
  remove and confirm absence, including failed create/start paths. Never cleanup
  by broad name prefix or by diffing/removing all newly visible containers.
- Loopback services only; random bearer token, no token in screenshots/logs.
  Stop services and browser, reap local children, then confirm owned containers
  absent. A cleanup ambiguity is failure.

## Stage tasks and risks

### E — executor feasibility (first gate)

- [x] Materialize an ARM64 wheelhouse with the existing hash locks and native lock.
- [x] Build existing executor Dockerfile without widening its package closure.
- [x] Resolve locally immutable image; record image/platform/source identities.
- [x] Run real manifest and containment probes on this Mac (profile-v3 network
      investigation only; not tighter-envelope CAD acceptance).
- [x] Run independent two-solid CAD fixture with tight limits; assert volume,
      solid count, BREP/source-map hashes and publication provenance.
- [x] Cancel a positively observed in-flight job; prove descendants/container and
      host client are gone. Also test error/timeout cleanup.

Risks: unavailable pinned ARM64 wheels; loader closure; Docker Desktop mount and
cgroup evidence; RepoDigest resolution; UID mapping; 4 GB VM; async cancellation.
If containment cannot pass, stop here and record the exact observed blocker.

### R — render-worker feasibility (after E)

- [x] Package pinned Mesa surfaceless EGL and current Python render dependencies
      in a separate ARM64 image; keep executor renderer-free.
- [x] Implement strict bounded render request/response and genuine profile probes.
      Worker and publication/integration evidence is in
      [macOS renderer](macos-renderer.md) and [progress](macos-progress.md).
- [x] Stage BREP + metadata only; compute RGB and solid/face/edge masks through
      current rendering APIs. Assert dimensions, nonempty pixels, palette IDs,
      selection-table resolution and exact source refs.
- [x] Compute a section through the kernel; verify expected nonempty cut geometry,
      render it and link it to the source build.
- [x] Cover `_mint_bundle` as well as inspection; validate/publish linked GLB.
- [x] Record actual GL_RENDERER/image hashes. Do not compare to pinned x86 CI
      goldens or claim that ARM64 pixels rebaseline those goldens.

Risks: Mesa dependency closure, renderer thread/context lifetime, larger memory
footprint, existing image allowlist, bounded output transfer, host publication
validation and multiple EGL entry points. Keep one render worker at a time.

### I — usable experimental workspace and acceptance

- [x] Explicit development-only workspace launcher with genuinely probed backend,
      loopback HTTP, existing auth/routes/static bundle, no agent/provider startup.
- [x] Complete workspace startup/capability projection with injected backends and
      ordinary dispatcher requirement intake; actual serve-mode HTTP build.
- [x] Native Chrome loads the actual workspace and provenance-linked GLB;
      viewport, mesh count, raycast/context resolution and section checked;
      screenshots plus HTTP/artifact evidence retained, with no network mocks.
- [x] All-stage smoke runs build/render/browser/cancellation checks serially,
      exits nonzero for ANY missing/failed required check and requires cleanup.
- [ ] New independent all-stage acceptance for this handoff (fresh report/session).
      The recorded `...review-03` pass is not a substitute for that new run.

Risks: renderer call sites bypassing injection, web package/toolchain availability,
browser auth/asset routes, cancellation ownership, cold downloads and memory.
A screenshot alone is not CAD, selection, containment or cleanup evidence.

## Acceptance/evidence interface

```sh
./scripts/macos_milestone_smoke.sh --report-dir "$PWD/dist/macos-report"
```

The report directory must be new and inside this checkout. `report.json` is the
machine-readable ledger: required stages have explicit `passed`, `failed`,
`blocked` or `unimplemented` status, never a silent skip. `logs/` holds bounded
command output; `screenshots/` is populated only by actual browser checks.
Absence of screenshots is not success. Image preparation and stage outcomes must
be recorded even when an earlier prerequisite fails. Exit zero is reserved for
all required checks plus cleanup passing. This is not the production CLI or the
full release suite.

Intended image preparation follows `docker/executor/README.md` **inside native
ARM64 Linux**, using a disposable download/build container and copies of reviewed
sources rather than mounting the checkout into it. Reuse hash-verified project-
local downloads; never silently re-resolve pins. The smoke harness is the final
acceptance entry point, not a replacement for the repository's existing tests.
The implemented and exercised launcher, stop procedure, scope limits and fresh
acceptance command are documented in [local workspace](macos-workspace.md).

## Observed execution results (historical)

The remainder records earlier blocked stages and their commands verbatim in
substance. Their unimplemented/precheck-only status does not describe the current
launcher; use the current evidence and workspace instructions above.

### Historical independent-review follow-up (superseded by scoped executor acceptance)

Fresh executor-only evidence is in
`dist/macos-executor-review-fix/precheck-final/report.json` (command output:
`dist/macos-executor-review-fix/precheck-final-cli.log`). The CLI accepted both
`--report-dir` and `--wheelhouse`, passed lightweight native preflight and exited
**1** at three explicit security blockers; both acceptance fields remain false.
No image preparation, CAD, cancellation, timeout or renderer/browser ran.

OOM/terminal evidence is now strictly typed and retained before removal; an
OOM-marked zero exit refuses. Ambiguous creates retain in-memory ownership and
poison the backend even after an absence observation. Delayed-create tests cover
best-effort reclamation, **not** durable external supervision or race-safe cleanup.
Executor acceptance now checks mandatory supporting records and cross-links;
synthetic schema tests are not real image, artifact or cancellation evidence.
The quota/provenance implementations and live collector remain absent.

`dist/macos-executor-review-fix/host-tests-final.log` records **352 passed**.
Fresh ruff check/format, docs, license and diff logs are in
`dist/macos-executor-review-fix/`; the full paths and focused reproduction command
are in [the executor-stage handoff](macos-executor-stage.md).
`dist/macos-executor-review-fix/cleanup-summary.json` records zero owned resources
and unchanged recorded IDs/states for the ten unrelated stopped containers.
No continuous observation or live worker termination is inferred from inventory.

Prior reports remain untouched: the historical milestone and final executor
reports have different `artifacts.py` hashes and are not one source snapshot.
No full suite, pyright, CAD integration or heavy rerun was attempted in this
follow-up. Production discovery is still disabled; all renderer/browser work
remains deferred and full milestone acceptance remains false.

### Historical profile-v2 disposition: BLOCKED on the real containment probe

`dist/macos-report-09/report.json` records a real ARM64 executor image build,
daemon-attested immutable resolution, exact manifest, and live containment run.
The unchanged backend returns:

```text
OCI sandbox unavailable: OCI containment checks failed: network_isolated
```

`logs/030-oci.json` contains the actual probe response. Networking reported
`connect_errno=101` (ENETUNREACH) and `routes=[]`, but `/sys/class/net` contained:

```text
bonding_masters erspan0 gre0 gretap0 ip6_vti0 ip6gre0 ip6tnl0 ip_vti0 lo sit0 tunl0
```

The strict existing contract requires `interfaces == ["lo"]`. No entries were
filtered, no passing report was injected, and no project CAD job ran. The
probe process exited zero: **process success is not containment success**.
The response also records UID 501/GID 20, PID 1, no-new-privileges, zero
capabilities, root write errno 30, writable staging proof, 256 MiB bounded tmpfs,
and cgroup v2 limits. These observations do not override the failed network gate.
The backend's overall capability report is unavailable with an empty feature
map, not a partial approval.

Whether these tunnel/sysfs entries represent inert defaults, sysfs visibility
outside the network namespace, or usable interfaces requires a separate security
investigation. Do not treat ENETUNREACH alone as sufficient or hide these entries.
Next executor task is to reconcile actual namespace/interface evidence with the
existing strict profile, without global Docker changes or weakening the probe.
Until then renderer/integration implementation is deliberately deferred.

### Attempts and tooling evidence

- Report 01: 64 MiB downloader tmpfs exhausted; failed honestly and cleaned up.
- Report 02: bounded 256 MiB downloader tmpfs succeeded; full hash-locked native
  wheels available (including CPython 3.13 ARM64 no-VTK OCP).
- Report 03: Docker rejected the unsupported `as` ulimit spelling before build.
  Trusted image-build RUN processes now use supported `data`, CPU and NPROC
  limits; build wall time/output are host bounded. This is not a change to the
  executor launcher's mandatory RLIMIT_AS contract.
- Report 04: Debian download TLS handshake timeout. Previously fetched native
  artifacts are now cached locally and hash/size reverified on every reuse.
- Reports 05–08: existing executor image built successfully (offline installs,
  `pip check`, build123d solid construction, linkage and manifest checks).
  Registry experiments failed: localhost resolved to inaccessible IPv6, then
  literal 127.0.0.1 was refused from the daemon even while the Mac's `/v2/`
  request succeeded. All registries were removed. This was **not** a failed
  containment probe and was superseded by inspecting actual local RepoDigests.
- Report 09: local digest resolution and exact manifest passed; real containment
  refused `network_isolated` as described above. Owned containers and tags were
  removed and their absence confirmed. No untrusted CAD build, render, section,
  GLB publication, browser screenshot or in-flight job cancellation is claimed.
- Final exact-interface run:
  `./scripts/macos_milestone_smoke.sh --report-dir "$PWD/dist/macos-report-final"`
  exited **1**. It repeated native dependency/image preparation, immutable
  resolution and the real `network_isolated` refusal. Cleanup passed; screenshot
  list is empty. Report/logs are in `dist/macos-report-final/`.
- Focused tests: **85 passed**, zero skipped, in `dist/macos-unit-tests.log`.
  Repository-wide ruff check/format check, license-header check, docs check and
  `git diff --check` passed. These are scoped tooling checks, not milestone passes.
- `dist/macos-prior-attempt-cleanup.json` confirms the ten image tags owned by
  earlier iterations are absent. Public dependency images, BuildKit cache,
  project-local wheels/tools and reports remain for reproduction; no prune was
  performed. The original ten unrelated stopped containers remain untouched.

The preparation/network scripts implement native prerequisite/image preparation,
immutable resolution, real manifest/containment probes, bounded logs and owned-resource
cleanup. The milestone and new executor entry points now **stop at the security
precheck before preparing images**. Build/render/browser/cancellation checks remain
unimplemented. Both commands exit 1; no prior containment report can override the
remaining provenance/supervision blockers. This is a blocked feasibility implementation, not a usable
workspace or completed acceptance milestone. See [executor-stage evidence and
handoff](macos-executor-stage.md).

### Historical reproduction and focused tests

The entry point needs native Python >=3.11 and the existing Docker CLI. It uses
stdlib host control code plus the repository's bounded transport; no host CAD,
agent/model calls or production activation. Run serially with no active containers:

```sh
./scripts/macos_milestone_smoke.sh --report-dir "$PWD/dist/macos-report-new"
# Optional reuse: pip still verifies every wheel against the original hash locks.
./scripts/macos_milestone_smoke.sh \
  --report-dir "$PWD/dist/macos-report-cached-new" \
  --wheelhouse "$PWD/dist/macos-report-02/download/wheels"
```

Reports must be new; commands and limits are recorded in `report.json`, complete
bounded output in `logs/`. The current commands stop before downloads/builds due to
the executor security precheck; the following describes the earlier preparation
runs and the independent network-check CLI. Source copies/package preparation mount only private
staging, not the checkout. The downloader alone uses bridge networking for public
binary dependencies; source wheel preparation and image RUNs are offline, and
all actual probe/worker containers use the unchanged `--network=none` profile.
No registry service is used by the current command.

For the focused host-only tests, the local `.venv` was provisioned with
pytest 9.1.1, pytest-timeout 2.4.0, hypothesis 6.161.2 and ruff 0.16.0 (not a full
`uv sync`, no kernel dependencies). Invocation:

```sh
PYTHONPATH="$PWD/core/src:$PWD/opstore/src:$PWD/server/src" \
  .venv/bin/python -m pytest tests/test_macos_feasibility.py \
  core/tests/test_sandbox_oci.py core/tests/test_sandbox_oci_image.py \
  core/tests/test_sandbox_oci_launcher.py -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

These daemon-free tests cover existing OCI gates and harness reporting/cleanup;
they are not browser, live cancellation or release evidence. Full suite, pyright,
ARM render goldens and workspace browser tests have not run. The old, incomplete
sysfs-only observation must still be refused. Profile v3 requires new interface
state, address and dual-stack evidence; see the linked investigation for the
focused live controls and additional regression tests.
