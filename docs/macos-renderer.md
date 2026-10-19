<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# Experimental macOS ARM64 renderer integration

**Historical renderer-stage evidence; superseded for changed runtime sources.**
The stage report below recorded `renderer_stage_passed:true`, full `accepted:false`.
A later all-stage workspace/browser run passed, but subsequent regression/type
repairs invalidate its authority for current sources too. Fresh images and live
acceptance remain required after CI stabilization; see [progress](macos-progress.md)
and the [roadmap](macos-roadmap.md). Production discovery and
`PRODUCTION_OCI_IMAGE` stay closed. The protocol and limits below remain binding;
historical results are not release certification.

## Reproduce

```sh
PYTHONDONTWRITEBYTECODE=1 /opt/homebrew/opt/python@3.13/bin/python3.13 \
  scripts/macos_renderer_check.py \
  --report-dir "$PWD/dist/macos-renderer-independent-new" \
  --wheelhouse "$PWD/dist/macos-report-02/download/wheels"
```

The report directory must be new and inside this worktree. Requires native Darwin
ARM64, branch `feat/macos-feasibility`, the active local `desktop-linux` context
and no running containers. Heavy operations are serial. Every run rebuilds from
current sources with hash-revalidated inputs/cache, resolves daemon-attested
immutable image references and runs fresh probes. No historical BREP/report,
registry push, host kernel, provider/model/agent, global settings or fake network
results are used. `--brep` was removed: the executor sub-run produces the input.

Final evidence: `dist/macos-render-integration-live-20261009-final/report.json`.
Its required renderer checks are `containment`, `rgb`, `selection_masks`,
`kernel_section`, `linked_glb`, `cleanup`. The separate fresh
`executor/report.json` passes all executor checks; generic root build/cancellation
placeholders are not substituted for that child's actual evidence.

- Actual renderer: **llvmpipe (LLVM 15.0.6, 128 bits)**, Mesa 22.3.6,
  native `linux/arm64`.
- Renderer image/config digest:
  `sha256:b249373ebcb093706bd438f3b601bec5f802ca962669eee54a6fb64214f4e35d`.
- Executor image/config digest:
  `sha256:7354de7818945740b3ddf84b91c04d25a68906c29e412e95ebff58fba2fe3498`.
- Fresh disjoint 4×5×6 and 2×3×7 cuboids: **2 solids, 162 mm³**. Actual
  exported/re-read BREP SHA256:
  `c5edeb9e55651a5931b3bdfa3c2a275e5a2a46aa460020d91d852f6053dda9ce`.
  Identical bytes to an earlier fixture do not substitute for the fresh build.
- Host `inspect_part`: nonempty **128×96 RGB** and solid masks; separate
  solid/face/edge passes resolve through a **38-entry** table. Visible solid IDs
  `{1,20}`, faces `{3,5,7,22,24,26}`, all 24 edge IDs. Every nonbackground pixel
  has the exact palette ID and matching table kind. Separate workers repeat
  selection pixels exactly; this is same-ARM-image determinism only.
- Actual `+Z@0` kernel section: **2 planar faces, 26 mm²**. The worker calls
  `geom.measure.section` and renders the canonical cap-shaded channel. The
  measurement, request, actual source and both execution identities persist in
  linked provenance; no screenshot or browser clipping is section evidence.
- Fresh `_mint_bundle` plus worker GLB: **2 meshes, 12 face primitives**. GLB
  SHA256 `2c4a7d9442f3c5894bdd718cc5c704aa5ea706335925a93e8dfb016e5a8c2a7d`.
  Source, bundle, table, every embedded solid/face ID, accessors/indices and GC
  edges are checked before publication. A second call resolves the linked cache.
- Invalid BREP returns worker exit **1**; successes exit **0**. All terminal
  states are typed, stopped and non-OOM. Exact owned containers, clients/groups
  and owners are absent/reaped. The child executor freshly repeats all 13 quota
  controls, observed explicit cancellation, separate timeout and ordinary failure.

Evidence retains actual requests/responses/pixels, `*-inspect.json`, PNGs,
`integration.json`, `linked.glb`, the project store under `executor/project`,
source/image-input/host-source hash manifests, installed identities, bounded raw
logs, effective limits/configuration, terminal/OOM records, journals and independent
inventories. No screenshot or browser/server run is claimed.

## Explicit service injection and complete render call graph

Construct `OciRenderer(SupervisorConfig(..., runtime_profile="renderer"))` with a
validated local `OciRuntime`, immutable image, `platform="linux/arm64"`, private
owned supervision directory, nonroot numeric identity and ordinary storage policy.
Call `probe()` and close it in `finally`/a context manager. The caller separately
owns the executor and project store. Neither worker receives a SQLite store,
lease, project directory or arbitrary input path.

`RenderProject(layout, store, renderer=renderer, backend=executor)` is the host
service seam. The same renderer/backend propagate through
`CadOps(..., renderer=...)` and `WorkspaceRuntime.open(..., renderer=...,
backend=..., serve_mode=True)`, including manifest reload. There is no global
session/report replacement, discovery override or production activation.

| Host caller | Injected route | Native route when not injected |
|---|---|---|
| `inspect_part`, RGB/solid-mask/section | resolves published BREP/metadata, `remote_service.inspect_remote` → fixed worker `channels.render_channel` | existing `_render_channel` |
| `inspect_part`, selection | worker `render_selection_view`/`OffscreenSession`, host publishes real passes/preview/table/bundle | existing `_render_selection` |
| `prepare_render_bundle` / CadOps query snapshot | same injected `inspect_part` | same native inspector |
| `publish_gltf_for_build` | **`_mint_bundle`** → worker selection → host canonical bundle → fixed worker GLB → host validation/publication | original shape/catalog/session/export path |
| CadOps `publish_gltf` | injected `RenderProject` above | native project |
| CadOps `linked_gltf` | stdlib source discovery and the shared linked-GLB resolver; no kernel/EGL import | same resolver |

The native `publish_selection_bundles(shape, session=...)` helper has no production
caller: only native fixture tests use it. Worker/native geometry APIs, CLI/goldens
without injection and native focus/explode keep their native paths. Remote
unsupported options **refuse before host geometry loading**, never fall back.
Core inspection/GLB imports and the CadOps geometry seam are tested without
NumPy/OCP/EGL installed. **Full `WorkspaceRuntime` import is not yet native-free**:
unrelated workspace modules still eagerly import build123d. Its injection/reload
wiring is present and structurally tested, not a claim of full HTTP/browser startup.
Removing those remaining imports belongs to the workspace/browser slice.

## Protocol, publication and freshness

Shared containment **5**, run grammar **3**, inventory manifest **4**, framed
transfer **1** are unchanged. Disjoint renderer manifest extension **1** now
requires renderer API **2**. Old API-1 images/requests/responses refuse. API 2
adds `links` (null except closed GLB bundle/table refs), genuine selection preview
pixels and an optional bounded GLB result. CAD launcher/worker allowlists remain
unchanged; neither image accepts arbitrary modules, scripts or entrypoint argv.

Operations: `probe`, `rgb`, `mask`, `selection`, `section`, `gltf`. BREP ≤16 MiB,
request ≤128 KiB, response ≤8 MiB, GLB ≤4 MiB, 1–128 solids, ≤2048 selectable
occurrences, dimensions **16–512** each, seven canonical views. Injected defaults
are **256×192**, native defaults remain 960×720. Host PNG code only losslessly
encodes validated worker pixels; it does not rasterize or fabricate masks.

Host source resolution requires a published current build with source-map and
recorded artifact kinds, matching live executor identity and exact BREP hash.
The worker verifies actual solid/topology counts. Closed response validation
binds request hash, dimensions, palette, topology namespace, labels/tags and source.
GLB validation rejects external resources/extensions, malformed buffers/accessors,
nonfinite vertices, out-of-range triangles, mismatched mesh/face IDs, wrong
source/bundle/table refs and unexpected scene transforms.

The host retains executor and renderer identities **separately**. OCI selection
bundles use bundle version **2**, adding provenance with both identities, build
input hashes, source-map ref, request/response hashes and actual GL_RENDERER.
Native bundle version 1 is retained. Published renders/GLB also link to provenance
blobs, which link to BREP/source-map. Canonical bundle/pass/table/source GC edges
and recorded kinds are checked at resolution; stale/missing/unlinked selection
still refuses. Live GLB cache reuse checks renderer identity **and** current
executor/source-map/build-input identity. Stored identity JSON is an audit record,
not authority to select an executor or skip probing.

## Containment, ownership and limits

Workers are nonroot, network-none, read-only root, capabilities dropped,
no-new-privileges, private namespaces, **1 CPU, ≤2 GiB, ≤256 PIDs, ≤120 CPU
seconds / 120 wall seconds**. `/work` is 128 MiB/2048 inodes, `/tmp` 16 MiB/256,
both kernel-bounded tmpfs with `nosuid,nodev,noexec`. Only bounded RO
`/inputs/source.brep` is mounted. No host writable output, project/home/socket
mount or device grant; no daemon logs, `docker cp`, archives or post-exit recovery.
Manifest/containment probes retain 256 MiB/32 PIDs/15 CPU/30 wall budgets.

The first integration run exposed exhaustion of the 256-client shared journal
mid-cleanup. It **failed**, retained ownership and was explicitly reconciled;
see progress. The fix reserves whole-operation cleanup capacity **before** side
effects without increasing bounds. Renderer jobs use separate bounded owned
supervision directories, closing prior owners and comparing image identity across
jobs. Concurrent calls refuse. A renderer session permits **16 operations**,
including EGL probe; open a new explicitly owned session afterward. Prior journals
are retained, not deleted or made clean by an absence guess. Unknown creates
remain durable refusals. `cancel_active()` delivers supervisor cancellation;
renderer-specific live cancellation remains untested (executor cancellation is
freshly exercised). Callers must close the renderer and executor they own.

Pinned offline image packaging remains separate: 1 GiB/128 PIDs/120 CPU/180 wall
for trusted source-wheel preparation; 480 wall seconds for the serial native
image build. Public render Python/native downloads are independently URL/size/hash
locked. Existing executor wheels and identical build inputs/cache are revalidated
and reused. No dependency or golden upgrade; no image build timed out in this slice.

## Preparation policy and failure reporting

The downloader admits the committed PyOpenGL 3.1.0 source archive only by its
reviewed exact URL, filename, size, SHA256, name and version tuple. This is not a
general sdist permission. Wheels must retain their URL filename; TLS, disabled
curl configuration, zero redirects, bounded requests/aggregate and pre-write
cache integrity checks still apply. The archive is built only in the existing
offline ARM64 preparation image, never on the host and never as a CAD workload.

The workspace collector records `renderer_live_phase`: `not_started` is set by
this invocation's control flow; `attempted` is persisted before calling the live
collector, including partial launches; `returned` is not a cleanup acknowledgement.
Missing/default state or resource absence establishes none of these facts.
Preparation/download owners must always settle through their existing ledger;
missing, mistyped or incomplete create settlement cannot pass an empty inventory.
`renderer_stage_error` retains the primary preparation/live error, while
`renderer_cleanup` records preparation status, live acknowledgement and independent
cleanup errors, including nested preparation removal failures. Live probe/render
failures likewise retain independent close/reap errors. Live verification requires
existing journal state (including observer journals) and matching owner/final/reap
PIDs; it never initializes replacement evidence for a missing journal.
These checks do **not** waive the milestone's live cleanup ACK requirement:
an early preparation failure still fails acceptance and keeps
`renderer_cleanup_passed:false`, even when preparation cleanup succeeded. It does
not retrofit historical reports or certify fresh renderer/browser acceptance.

## Remaining scope

Remote focus/explode/custom azimuth/elevation, non-current provenance-less refs,
last-good checkpoints and nonnumeric section specifications currently refuse.
Large CAD/mesh scenes and other runtimes are not certified. ARM Mesa 22.3.6/LLVM15
is **not** the pinned x86 Mesa25.2.8/LLVM20 golden baseline; no equivalence,
rebaseline or relaxed threshold is claimed. Full native render/golden suites,
full pyright and full repository pytest were not run.

**937 focused tests passed, zero skips**; commands and failure history are in
[progress](macos-progress.md). Full HTTP imports, authenticated native browser,
independent reviews and final fresh all-stage smoke remain implementation and
acceptance work. `accepted:false` cannot be promoted by this scoped pass.
