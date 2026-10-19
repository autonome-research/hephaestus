<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# Local experimental Mac workspace

This is **explicit development injection**, not production macOS support.
Production backend discovery and `PRODUCTION_OCI_IMAGE` remain closed. Tested
locally on Darwin ARM64 with Docker Desktop `desktop-linux`, Linux aarch64,
a roughly 4 GB VM, and native Google Chrome. No agent, provider, model, remote
publication, privileged worker or host CAD installation is needed.

## Current evidence

**Scoped install repairs need new-source acceptance.** Published baseline
`a92edc76546b797ada1a30b41373f6b3331dc6bf` has 21 successful exact-source CI jobs
(run `39017093038`) and compliant cached 13-stage acceptance at
`dist/pr128-network-retry-20261017T165219Z/acceptance/report.json` (SHA256
`01ea937efe0cff18b04e9dcbb014986c693b7f4329020f74af2b3ebf0fbd278e`).
Preparation already uses [read-only inputs and bounded transfer](macos-preparation.md);
the older writable-bind failures below are historical, not the current recipe.

The same-host empty-project-cache rehearsal at
`dist/clean-app-rehearsal-20261017T203250Z/REPORT.md` remains **blocked**, not a
cold-install pass: host/web and fresh wheels succeeded, then expat's Debian pool
URL returned 404 before image/CAD/browser work. Both ARM64 locks now point to
an official immutable Snapshot content address serving the identical pinned bytes.
Explicit installer cache/temp and browser scratch controls below address the
other isolation findings. These source changes invalidate reuse of earlier
CI/live passes as current acceptance. A new independent empty fixture and
exact-source CI are still needed; no merge/release certification follows.

This is one existing Mac with inherited tools/Chrome and shared Docker Desktop,
base images and BuildKit cache: **not a fresh machine or cold Docker**. Physical
suspend remains untested; see [suspend-inclusive deadlines](suspend-inclusive-deadlines.md).
Dated failures and remaining limits are preserved in [progress](macos-progress.md).

Historical independent all-stage **local experimental acceptance** is recorded in
`dist/macos-final-reviewed-20261012T152211Z/report.json` (SHA256
`df0fa8086de37a4add4bf4773a4e9ecaf9d686f869b364ad7a7b64d42b93370a`).
All 13 required stages passed. It exercises this launcher with real requirement
intake, HTTP build, Chrome raycast/context resolution, full 12-face GLB, kernel
section and graceful SIGTERM shutdown. Its 457 host, 173 executor and 173 renderer
source-manifest entries were rehashed before the initial PR packaging with no
differences **at that checkpoint**, not after the subsequent runtime repairs.
The report directory retains source/image/input/bundle hashes and exact-resource
checks locally; generated `dist/` evidence is not included in the repository.
The smoke removes its tags: **prepare new images from current source** for manual
use; older retained preparation images are not proof for current source.

The interrupted `...review-final` report remains false; its old renderer session
lacks a parent-reap acknowledgement and must not be reused, despite confirmed
physical cleanup. The successful run uses wholly fresh sessions. See
[progress](macos-progress.md) for retained failures and complete commands.

## Setup

Run from this worktree on `feat/macos-feasibility`. Keep Docker idle: the tools
refuse active containers rather than stopping anybody else's containers. Do not
change the Docker context globally. Python 3.13 or 3.14 is supported for the
native server; the acceptance harness uses the specified Homebrew Python 3.13.

```sh
# Only on a checkout without a venv; never replace an existing environment.
umask 077
mkdir -p "$PWD/dist"
mkdir "$PWD/dist/mac-setup-new"
mkdir "$PWD/dist/mac-setup-new/home" "$PWD/dist/mac-setup-new/tmp"
# Use this shell for the setup commands; do not copy user credentials into HOME.
export HOME="$PWD/dist/mac-setup-new/home" TMPDIR="$PWD/dist/mac-setup-new/tmp"
test -e .venv/bin/python || uv --no-cache --no-config --no-python-downloads venv \
  --python /opt/homebrew/opt/python@3.13/bin/python3.13 .venv
/opt/homebrew/opt/python@3.13/bin/python3.13 scripts/macos_workspace_dependencies.py \
  --report-dir "$PWD/dist/mac-host-deps-new" --no-cache
(cd web && pnpm install --frozen-lockfile --store-dir "$PWD/../dist/mac-pnpm-new" \
  --network-concurrency=2 --fetch-retries=0 --fetch-timeout=30000 && pnpm build)
```

The acceptance preflight performs a frozen web install into
`dist/macos-pnpm-store`, verifies all direct exact pins, and rebuilds `web/dist`.
Public pinned downloads are permitted; an empty offline store is not a pass.
No global pnpm/Docker configuration is changed. For an empty-cache rehearsal use
a new checkout with no ignored project files; do not delete old caches/evidence.
These commands reuse installed Python/uv/Node/pnpm/Chrome prerequisites.

The host installer defaults to `--no-cache`; mutually exclusive `--cache-dir`
can select a **new** owned directory below this checkout's `dist/`. `--temp-dir`
can similarly select a new temporary directory there. Otherwise HOME/TMPDIR are
private `installer/home` and `installer/tmp` below the new report directory.
Symlink components, existing leaves and escaping paths refuse. Cache/config,
public index and disabled keyring controls are passed explicitly to uv; outer
`UV_CACHE_DIR` is deliberately not inherited. No user config/provider environment
is forwarded. Hash-required binary installation and the non-CAD subset remain.

The host installer takes the non-CAD server subset from **this `uv.lock`**,
including wheel hashes. It never resolves newer dependencies. `web/` retains its
own exact package and pnpm pins. Acceptance uses pinned `@playwright/test` against
native Chrome at `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`;
it records the binary hash and actual version. It does not download an unpinned
browser or treat a failed browser installation as a pass. Golden pins are unchanged.

## Prepare images and a disposable example

All paths marked `new` must not exist. Without `--wheelhouse`, preparation fetches
fresh hash-locked ARM64 wheels from public PyPI; no prior `dist/` wheelhouse is
required. Optional `--wheelhouse` revalidates every cached wheel. Preparation is
serial, offline for source packaging/image installation, and may reuse Docker
build cache and checkout-local verified native caches. It does **not** run
untrusted CAD or confer an execution capability.

```sh
/opt/homebrew/opt/python@3.13/bin/python3.13 scripts/macos_prepare_workspace.py \
  --report-dir "$PWD/dist/mac-images-new"
/opt/homebrew/opt/python@3.13/bin/python3.13 scripts/macos_workspace_demo.py \
  --directory "$PWD/dist/mac-demo-new"
```

Preparation explicitly **retains two local image artifacts**, recorded as exact
tags in `mac-images-new/report.json` and `mac-images-new/renderer/report.json`.
`images.json` contains daemon-resolved immutable references, not an acceptance
certificate. Every launch freshly checks manifests, containment, executor identity
and real Mesa/EGL. Nothing is pushed and no registry service is exposed.

The example is independently authored: two sealed cuboids, 162 mm³ total volume.
Its `requirements.json` is an explicit **diagnostic specification**, not a claim
about a real customer's requirements. For your project supply your own request and
entries; the launcher requires each `specified` quote to occur in that request,
and the ordinary dispatcher validates the ledger. It never fabricates resolved
assumptions. Missing requirements still refuse a build.

## Start, use, stop

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/macos_workspace.py \
  --project "$PWD/dist/mac-demo-new" \
  --images "$PWD/dist/mac-images-new/images.json" \
  --state-dir "$PWD/dist/mac-session-new" \
  --requirements "$PWD/dist/mac-demo-new/requirements.json" \
  --build two_solids --open-browser
```

`--build` uses the **normal dispatcher and requirement gate**, not an unsafe
executor. `--images` can instead be replaced with both `--executor-image` and
`--renderer-image` immutable references. No environment override activates OCI.

- HTTP binds **127.0.0.1 only**, to a newly allocated port (`--port` can select a
  fixed local port). The existing authenticated routes and actual `web/dist`
  bundle are served. No alternate mock app or production-factory patch exists.
- The console prints only the base URL and token-file path. `--open-browser`
  opens the token-fragment URL in the system browser; tested acceptance uses
  Chrome explicitly. Firefox was additionally used manually, not certified by
  the automated Chrome gate. The app consumes and removes the fragment. Do not paste
  the token into logs or screenshots. The token remains in `.heph/serve.token`
  at mode 0600; `.heph/serve.json` is normal local discovery.
- Select the part, inspect its actual GLB, use the geometry visibility controls,
  or enable a section and click **Render section**. The rendered plate is the
  exact stored worker PNG, not the browser clipping preview. The launcher uses
  320×240 worker images, within the renderer's unchanged bound.
- Build mutations through the existing authenticated API use UUIDv7 idempotency
  keys. The example's startup build and the smoke's HTTP build both exercise
  real serve-mode injection. The requirements file is only needed to seed/update
  the ledger; omit it when reopening a project with its existing ledger.
- Agent attachment is **disabled**, including attempts through the attach route.
  The unavailable agent panel is expected. Do not configure a provider for this
  acceptance. No model responses or scripted-provider substitution are used.
- Stop with **Ctrl-C** (or SIGTERM to this exact launcher PID). A finite default
  1800-second session ceiling also stops it; `--wall-seconds` accepts at most
  3600. This is not a permanent service. Close your manually opened browser tab;
  the launcher does not own or kill your existing browser. Automated acceptance
  owns and reaps its separate Chrome instance and profile.

`workspace.json` records identities, capabilities, actual build/requirements,
bundle hashes and final cleanup. Per-job supervisors record create intent before
submission, acknowledged IDs, terminal/OOM evidence and reaping. **Cleanup failure
is failure**: retain the state directory for exact-resource reconciliation as
specified in [supervision](macos-supervision.md); do not prune Docker or remove an
unknown resource. A second interruption cannot abort the bounded cleanup phase.

Worker admission is serial across CAD and rendering. CAD and rendering use at
most 2 GiB, 256 PIDs, one CPU, 120 CPU seconds and 120 worker wall seconds.
Read-only root, no network/capabilities, bounded read-only inputs, aggregate
byte+inode tmpfs quotas, fixed worker protocols, bounded transfer and disabled
daemon logs remain unchanged. Each owned renderer session admits at most 16
operations; exhaustion refuses rather than deleting journals or relaxing bounds.

When finished permanently, remove **only the two exact retained tags** listed in
the preparation reports with `docker --host <recorded-local-endpoint> image rm
<exact-tag>`. No `prune`, broad prefix cleanup, global setting change or deletion
of unrelated stopped containers is part of this workflow. Keeping the image
artifacts for the next launch is intentional, not an active service.

## Fresh acceptance

```sh
bash scripts/macos_milestone_smoke.sh \
  --report-dir "$PWD/dist/mac-all-stage-new"
```

The command verifies host pins, rebuilds the actual bundle, prepares fresh image
references and runs quota controls, real CAD/publication, observed delivered worker
cancellation, timeout/failure, RGB, exact masks, kernel sections, linked GLB and
native authenticated Chrome **serially**. Browser evidence includes an HTTP build,
401 without auth, scene/mesh count, a real scene raycast resolved through the
existing context route, rejection of an unknown selection, actual section controls,
PNG byte/hash equality and independently checked kernel/worker provenance. Named
screenshots supplement those assertions; they establish no geometry fact.

The browser collector derives private HOME, TMPDIR/profile parent and artifact
paths under `<report-dir>/browser/runtime/`, passes them through the actual Node
and Playwright launch, and records the actual `--user-data-dir` path after checking
confinement. It never adopts a user's Chrome profile/cookies. Settled scratch is
removed on success and initialization failure; unresolved browser ownership
retains its profile for exact-resource reconciliation. After a client launch, a
missing browser ownership record is unresolved, not proof of absence. Evidence
stays outside scratch.
A private OS temporary directory was not itself a security flaw; these controls
make same-host fixture confinement explicit and verifiable.

Browser/Node/server ownership is recorded before launch, and graceful signal
handling closes the actual Chrome process, not merely its client. Final checks
independently inventory exact worker/client/owner/browser/server IDs and groups.
Temporary smoke tags are removed; retained preparation artifacts are separate.
Allow an outer shell wait of up to 2400 seconds for serial image preparation and
all stages; individual build/network/worker timeouts remain much smaller. A killed
parent cannot retroactively acknowledge reaping: keep such a report failed and
its old ownership session refused, even after exact physical cleanup.
Missing evidence, failed operations, OOM, timeout or uncertain cleanup prevent
acceptance. Reports are new, failures are retained, and old reports never authorize
execution. [Progress](macos-progress.md) names the actual final report and commands.

## Scope and remaining coverage

The historical run tested a local build/render workspace, **not the full product
on macOS**. That pass does not certify the current changed sources.

- The browser pick gate uses the existing read-only scene hook plus authenticated
  context resolution. It proves a real resolvable face hit. The product's
  click-to-selection popover/dedicated selection route is still unimplemented;
  the gate does not pretend a pointer click activates that absent UI.
- The diagnostic HTTP build retains **open dimension findings** in
  `browser/browser.json` (including the 12 mm X request versus 15 mm bounding
  extent). Nothing dismisses or waives them: build/transport acceptance is not
  design-requirement completion.
- Pairwise interference in post-build critique is explicitly **unavailable**, not
  a clean result. DFM, import conversion, export/drawing/posed-scene services and
  arbitrary render views/focus/explode are not newly certified. There is no host
  CAD fallback to make them green. Current provenance-bearing builds are required.
- The supplied independent security/render findings have regression-tested fixes.
  A new independent human review, full pytest, pinned x86 Linux goldens, other
  browsers/macOS versions/runtimes, large CAD, renderer-specific
  live cancellation, daemon/machine-death recovery and release packaging remain
  outside this local acceptance. Abrupt unknown-create settlement remains a
  durable refusal, not an absence guess. No production/release support claim is made.
- Root pyright still **fails** in the partial host environment. The initial
  fully provisioned PR CI's 2,007 branch-introduced errors were repaired: baseline
  `8ea36417` has zero errors/warnings in exact-tree CI. New source changes need
  new full-dependency CI; the partial host cannot certify that gate. Native HTTP build tests still fail
  locally without build123d; no fallback or dependency change conceals them.
  The earlier OCI HTTP build and 963 focused host / 1512 web passes are historical.
  Current selections and failures are in [progress](macos-progress.md); none
  constitute full-suite, native-kernel or current live-image certification.
