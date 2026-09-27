# OCI executor image

> **The OCI host foundation is not production activation.**
> The core now contains reusable Docker/Podman argv, preflight, bounded
> transport, lifecycle/cleanup, immutable-image validation, and live-probe
> mechanics. Production backend selection still does not construct it, and
> there is deliberately no default image or environment override. Until a
> published digest, strict runtime discovery, and real macOS evidence land
> atomically, secure production behavior remains unchanged.

The image built here contains the two production workers and the private
capability-probe worker. Its entry point accepts only `manifest` or the
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
  and verified by the live probe (so the worker can write the private host-owned
  staging bind without making it world-writable);
- cgroup memory, CPU, and PID limits;
- a bounded tmpfs mounted at `/tmp`;
- exactly one writable bind, the per-job staging directory at `/work`;
- no project-root bind, no container socket, and no other host paths;
- stdin, stdout, and stderr as the only protocol channels;
- host-enforced wall-clock termination of the entire container;
- an image selected only by immutable digest;
- rejection of every non-empty `SandboxSpec.ro_binds` value; and
- exact conversion of `SandboxSpec.worker_args` through
  `approved_module_for_worker_args()` with no argument passthrough.

Host launch clears the inherited container environment before the launcher
starts, because ambient loader variables take effect before Python can apply
its fixed worker environment. The only loader path is the audited entrypoint's
immutable image-private native-library directory, repeated exactly in the
worker environment. Capability probing must reject root execution,
missing required limits, unlimited limits, limits looser than requested, or
any protocol/envelope mismatch.

The backend uses create followed by attached start, reads worker status from
container inspection rather than the attach client, bounds both output streams,
and treats unconfirmed kill/removal as `sandbox_denied`. Execution is gated on
a passing live report cached only by that backend instance. Its probe is strict:
missing raw rlimit, capability, mount, network, or cgroup evidence is a failure,
not an inferred success.

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
