# OCI executor image

> **The OCI host foundation is not production activation.**
> The core now contains reusable Docker/Podman argv, preflight, bounded
> transport, lifecycle/cleanup, immutable-image validation, and live-probe
> mechanics. Production backend selection still does not construct it, and
> there is deliberately no default image or environment override. Until a
> published digest, strict runtime discovery, and real macOS evidence land
> atomically, secure production behavior remains unchanged.

The image built here contains build/DFM, the private containment probe and the
fixed stdlib-only storage-control worker. Its entry point accepts only `manifest` or the
versioned `run` grammar documented by `oci_launcher`; it has no default worker
command. Select a published image by immutable OCI digest, never by a floating
tag.

## Image packaging

`package/` defines the private, image-only `hephaestus-executor-runtime`
distribution. Its build hook stages the reviewed core import package but gives
it worker-specific metadata, avoiding the rendering dependencies declared by
the end-user `hephaestus-core` distribution. It is not a second source tree and
must never be published as an end-user wheel.

`requirements.lock` is generated from that package's uv lock and pins every
runtime artifact by SHA-256. `build-requirements.lock` separately pins and
hashes the complete Hatchling build environment used offline for both local
wheels. Produce a wheelhouse natively on each Linux
target architecture (amd64 and arm64); do not cross-populate native wheels:

```console
(cd docker/executor/package && uv lock --check && \
  uv export --frozen --no-dev --no-emit-local --format requirements-txt \
    --output-file ../requirements.lock)
uvx --python 3.13.7 --from pip==25.2 pip download \
  --dest dist/executor-wheelhouse --only-binary=:all: --require-hashes \
  -r docker/executor/requirements.lock \
  -r docker/executor/build-requirements.lock
SOURCE_DATE_EPOCH=0 uv build --offline --no-index \
  --find-links dist/executor-wheelhouse --require-hashes \
  --build-constraints docker/executor/build-requirements.lock \
  --wheel docker/executor/package --out-dir dist/executor-wheelhouse
SOURCE_DATE_EPOCH=0 uv build --offline --no-index \
  --find-links dist/executor-wheelhouse --require-hashes \
  --build-constraints docker/executor/build-requirements.lock \
  --wheel opstore --out-dir dist/executor-wheelhouse
uv run python docker/executor/write_local_lock.py dist/executor-wheelhouse
uv run python docker/executor/fetch_native_runtime.py \
  "$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')" dist/executor-native
DOCKER_BUILDKIT=1 docker build --pull=false \
  -f docker/executor/Dockerfile -t hephaestus-executor:local .
```

Run those commands on the target architecture: the fixed Python 3.13 download
interpreter must select the same ABI as the image. The Dockerfile installs both
third-party and repository-built wheels from that wheelhouse with networking
disabled, `--no-index`, `--only-binary=:all:`, and `--require-hashes`. The
architecture-specific Debian artifacts are also URL-, size-, version-, and
SHA-256-locked before the offline build extracts them under the private virtual
environment prefix. The build runs `pip check`, imports build123d, constructs a
solid, and validates the launcher manifest before copying only that prefix into
its final stage. The Python base is selected by a multi-arch index digest; the
Dockerfile uses no remotely fetched frontend directive.

The no-VTK OCP wheel is still dynamically linked to the vendor-neutral libGL
and libGLX dispatch loaders and to X11, even for non-rendering geometry calls.
The native lock therefore includes that minimal loader closure and DejaVu fonts
for deterministic text geometry. It deliberately does **not** include a Mesa
GLX provider, DRI drivers, EGL, VTK, or a display server; rendering remains a
separate capability and cannot be activated in this networkless image.

Only the executor distribution, `opstore`, build123d, the no-VTK OCP
package/proxy, and their audited Python/native runtime closure belong in that
wheelhouse. Explicitly excluded are:

- `hephaestus-server`, `hephaestus-contract`, `hephaestus-cad`, and
  `hephaestus-bench`;
- Node, npm, pnpm, and web assets;
- Mesa providers/DRI drivers, EGL, VTK, display servers, and rendering-only
  dependencies beyond OCP's mandatory vendor-neutral loader closure;
- bubblewrap; and
- Docker, Podman, nerdctl, and containerd clients.

The final stage receives only the installed virtual environment; source,
compilers, wheelhouse, and package caches stay out. The base image is immutable
supply-chain input selected by digest rather than a floating tag.

## Implemented host profile foundation

An explicitly constructed (test/integration-only) `OciBackend` now enforces the
following in addition to launcher rlimits:

- a read-only root filesystem and `--network=none`;
- all capabilities dropped and `no-new-privileges` enabled;
- private PID and UTS namespaces, verified by PID 1 and the fixed container
  hostname rather than assumed from runtime defaults;
- the invoking Darwin user's numeric, non-root UID and GID, passed explicitly
  and verified by the live probe; writable tmpfs ownership is assigned explicitly;
- cgroup memory, CPU, and PID limits;
- separate `/work` and `/tmp` tmpfs mounts with kernel aggregate byte and inode
  limits, mode 0700 and `nosuid,nodev,noexec`;
- exactly one bind: a bounded per-job snapshot at `/inputs`, **read-only**;
- no host output mount; bounded framed stdout artifact export before worker exit;
- explicit logging driver `none`, empty log path and disabled healthchecks;
- a fixed read-only 4 KiB / one-inode tmpfs masking Docker's otherwise writable
  `/dev/mqueue`, plus actual denial checks for other runtime storage surfaces;
- no project-root bind, no container socket, and no other host paths;
- stdin, stdout, and stderr as the only protocol channels;
- host-enforced wall-clock termination of the entire container;
- an image selected only by immutable digest;
- rejection of every non-empty `SandboxSpec.ro_binds` value; and
- exact conversion of `SandboxSpec.worker_args` through
  `approved_module_for_worker_args()` with no argument passthrough.

Active versions are **profile 5 / protocol 3 / manifest 4**, transfer version 1.
Manifest 4 adds mandatory trusted pre-workload installed-source/package/version
inventory, bound by the host to the daemon-attested immutable image and platform.
Assembly, publication and freshness use this identity, never host CAD metadata.
See `docs/macos-execution-identity.md`. Images must be rebuilt; prior manifest-3
storage reports do not certify the updated source/image.
Profile 5 requires no-follow file type and Linux null character-device identity
(major 1 / minor 3) for runtime proc masks. Explicit ENOENT is allowed only when
mountinfo also has no mount at that path; missing evidence or writable regular-file,
directory, symlink or wrong-device substitutions refuse. Profile-4 images/probes
are rejected; protocol and transfer grammars are unchanged. Manifest-3 images
also refuse because their execution inventory is missing.
The manifest declares exact ordinary/control storage policies and the RO mqueue
mask. Older images and launcher grammars refuse. A `run` invocation contains only
version, approved module, CPU/AS/NPROC limits, fixed policy name and transfer nonce.
The launcher verifies storage and execs the worker with a fixed transport-mode
argument; worker PID 1 semantics are unchanged. Native build/DFM protocols remain
native. Input declarations include mesh/point facts sidecars; admission precedes
host staging writes. CAD import conversion isolation is not newly certified.

Host launch clears the inherited container environment before the launcher
starts, because ambient loader variables take effect before Python can apply
its fixed worker environment. The only loader path is the audited entrypoint's
immutable image-private native-library directory, repeated exactly in the
worker environment. Capability probing must reject root execution,
missing required limits, unlimited limits, limits looser than requested, or
any protocol/envelope mismatch.

The backend uses create, effective image/security/mount/log configuration
inspection, then attached start. Stdout is streamed into confined bounded host
collection, not accumulated as an artifact-sized buffer. Only complete framing,
EOF, result/artifact agreement, matching build source-map JSON, typed successful
non-OOM terminal state and confirmed removal permit exclusive artifact installation.
Existing assembly/publication gates still apply; transfer hashes are not CAD
provenance. Every post-submission exit has an unconditional owned-container cleanup guard,
including grouped receiver/host-unlink failures. Unconfirmed cleanup retains the
known ID and poisons reuse; ambiguous creates remain separately fail-closed.
The standalone backend remains a synchronous foundation. Explicit local
`SupervisedOciBackend` injection now adds a fresh per-operation owner, durable
pre-create names/acknowledged IDs, delivered cancellation, bounded client/group
reaping and exact-resource recovery. Unknown requests or abrupt owner/client
death retain pending state; absence polling never settles them. See
`docs/macos-supervision.md` for supported interfaces and cleanup limits. Host
regressions are not live cancellation acceptance.
Execution is gated on a passing report cached only by that backend instance and
its fixed storage policy. Missing raw limits, capacities/inodes, writable-surface,
network or cgroup evidence fails, never implies success.

Local native ARM64 storage evidence and reproduction are documented in
`docs/macos-staging.md`. The tested small policy is 8 MiB/128 inodes at `/work`
and 2 MiB/64 inodes at `/tmp`. Ordinary defaults are 128 MiB/2048 and 16 MiB/256;
those are ceilings, not demonstrated CAD capacity. Real stdlib storage controls
passed under profile 4; the stricter profile-5 review follow-up and its fresh
source-specific results are tracked in `docs/macos-staging.md`. Fresh manifest-4 image/storage and real supervised CAD/provenance/cancellation,
timeout/failure acceptance passed historically in the experimental executor CLI. See
`docs/macos-executor-stage.md` and `docs/macos-progress.md` for source-specific
reports and reruns. The historical independent local experimental run is recorded at
`dist/macos-final-reviewed-20261012T152211Z/report.json` (`accepted:true`),
including all 13 required stages: rendering, authenticated native Chrome, actual
HTTP build and cleanup among them. Its source manifests matched files at the
initial PR packaging checkpoint only. **That live acceptance is superseded for
changed runtime sources** after regression/type repairs; fresh images and a new
all-stage run are required. Current CI blockers and evidence-gated next milestones
are in `docs/macos-progress.md` and `docs/macos-roadmap.md`. Generated
reports remain local, not shipped in Git. Repeat runs must use fresh reports and
sessions rather than reuse a recorded pass. Production discovery is unchanged. The interrupted `...review-final` stays failed and its
unresolved parent-reap record permanently refuses reuse; see progress for exact
reconciliation. Root pyright and the native HTTP-boundary fixture remain failed,
not waived or evidence of full-suite success.

## Separate experimental renderer

`docker/renderer/Dockerfile` now provides a separate native ARM64 Mesa/EGL image
with an independently locked native/render dependency closure. It reuses this
source-wheel recipe and the containment/transfer/supervisor mechanisms, **not**
the CAD worker allowlist or image entrypoint. The executor remains renderer-free
and rejects render workloads; the renderer rejects build/DFM/arbitrary modules.
Shared profile 5/protocol 3/manifest 4/transfer 1 are unchanged; disjoint renderer
manifest extension 1 / API 2 are exact-validated (API 1 now refuses). See `docs/macos-renderer.md`
for historical live results, limits and explicit injection. The earlier core
inspection, exact selection, measured kernel sections and linked GLB run passed through
`_mint_bundle`. Scoped renderer-stage success alone is not workspace/browser
acceptance; the later complete report above exercises both. Tested explicit local
launch/use/stop instructions are in `docs/macos-workspace.md`. Browser picking
proves raycast/context resolution, not the absent selection-popover workflow;
open dimension findings are retained, so build success is not design-requirement
completion. Production stays closed.

## Still blocked: production activation

The package boundary, hashed dependency closure, and buildable executor
Dockerfile now exist. Production remains disabled because there is no published
multi-architecture executor digest, runtime discovery, or real macOS release
lane. In particular, no environment variable, project setting, CLI option, or
floating tag can activate OCI execution. Local image builds and daemon-free
unit tests are not evidence that Docker Desktop, OrbStack, or Podman machine
implements the requested containment. Activation must land atomically with a
published digest, strict runtime discovery, and release-lane tests that verify
both manifest and containment probes on supported macOS runtimes.
