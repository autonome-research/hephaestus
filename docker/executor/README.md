# OCI executor image

> **The OCI host foundation is not production activation.**
> The core now contains reusable Docker/Podman argv, preflight, bounded
> transport, lifecycle/cleanup, immutable-image validation, and live-probe
> mechanics. Production backend selection still does not construct it, and
> there is deliberately no default image or environment override. Until the
> packaging, image, digest, and real macOS evidence below land atomically,
> secure production behavior remains unchanged.

The eventual image will contain the two production workers and the private
capability-probe worker. Its entry point will accept only `manifest` or the
versioned `run` grammar documented by `oci_launcher`; it will have no default
worker command. Select a published image by immutable OCI digest, never by a
floating tag.

## Image-packaging prerequisite

No executor Dockerfile or dependency lock is checked in yet. That omission is
fail-closed and deliberate: the published `hephaestus-core` distribution has a
broader dependency boundary than the executor. Installing it with `--no-deps`
would make `pip check` fail, while resolving its declared dependencies would
pull rendering packages into an image that is meant to contain only the worker
runtime. A placeholder image would make this foundation look buildable when it
is not.

Before an image can be added, introduce an executor-specific distribution or
an equivalently explicit packaging boundary whose metadata names the complete
audited worker dependency closure. Then:

- build its wheel and `opstore` with a fixed `SOURCE_DATE_EPOCH`;
- create separate Linux wheelhouses for amd64 and arm64;
- reject source distributions;
- pin every wheel byte by SHA-256, including locally built wheels;
- install offline with `--no-index`, `--only-binary=:all:`, and
  `--require-hashes`;
- run `pip check`; and
- copy only the resulting virtual environment into a digest-pinned, non-root
  final image.

Only the executor distribution, `opstore`, build123d, the no-VTK OCP
package/proxy, and their audited Python/native runtime closure belong in that
wheelhouse. Explicitly excluded are:

- `hephaestus-server`, `hephaestus-contract`, `hephaestus-cad`, and
  `hephaestus-bench`;
- Node, npm, pnpm, and web assets;
- Mesa, EGL, GLX, VTK, and rendering-only dependencies;
- bubblewrap; and
- Docker, Podman, nerdctl, and containerd clients.

The eventual final stage must receive only the installed virtual environment;
source, compilers, wheelhouse, and package caches stay out. Its Dockerfile
frontend and every base image are immutable supply-chain inputs and must be
selected by digest rather than a floating tag.

## Implemented host profile foundation

An explicitly constructed (test/integration-only) `OciBackend` now enforces the
following in addition to launcher rlimits:

- a read-only root filesystem and `--network=none`;
- all capabilities dropped and `no-new-privileges` enabled;
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

Host launch must also clear the inherited container environment before the
launcher starts, because loader variables take effect before Python can apply
its fixed worker environment. Capability probing must reject root execution,
missing required limits, unlimited limits, limits looser than requested, or
any protocol/envelope mismatch.

The backend uses create followed by attached start, reads worker status from
container inspection rather than the attach client, bounds both output streams,
and treats unconfirmed kill/removal as `sandbox_denied`. Execution is gated on
a passing live report cached only by that backend instance. Its probe is strict:
missing raw rlimit, capability, mount, network, or cgroup evidence is a failure,
not an inferred success.

## Still blocked: production activation

There is no executor Dockerfile, published immutable digest, production image
setting, runtime discovery, or platform-selection/fallback change in this
phase. In particular, no environment variable, project setting, CLI option, or
floating tag can activate OCI execution. Daemon-free tests establish command
construction and fail-closed state-machine behavior only; they are not evidence
that Docker Desktop, OrbStack, or Podman machine implements the requested
containment. The image must remain disabled until its package boundary and
locked closure exist, a multi-architecture digest is published, strict image
inspection passes, and release-lane tests verify both manifest and containment
probes on real supported macOS runtimes.
