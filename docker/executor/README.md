# OCI executor image

> **This image and its launcher are not, by themselves, a complete sandbox.**
> They may be used for untrusted jobs only after the host-side OCI backend,
> live capability probe, and mandatory runtime profile described below land
> together. Until then, secure execution remains on the existing backend.

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

## Required future host profile

The future OCI backend must enforce all of the following in addition to the
launcher rlimits:

- a read-only root filesystem and `--network=none`;
- all capabilities dropped and `no-new-privileges` enabled;
- numeric UID and GID `65532` (also verified by the live probe);
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

No host runtime detection or OCI backend is provided in this phase. The image
must not be enabled until digest verification, this profile, live probing, and
whole-container termination are implemented and tested as one fail-closed
change.
