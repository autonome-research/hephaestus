<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# Experimental macOS quota-bounded staging

**Fresh profile-5/manifest-4 staging passes within the real executor CLI.**
The [executor stage](macos-executor-stage.md) reruns all of this CLI's controls
against the same fresh immutable ARM64 image used for CAD and cancellation.
See [progress](macos-progress.md) for exact source-specific reports. Full
acceptance remains false. This independent storage-only command remains available.
The older `dist/macos-storage-gate-20261008T020845Z/report.json` certifies only
its recorded profile-5/manifest-3 source/image, not current sources.

The previous
profile-4 staging pass is historical. Profile 5 fixes the two storage-review
findings and adds partial-artifact/finite-overflow controls; fresh evidence is
below and in [progress](macos-progress.md). The independent follow-up is linked
above. This is storage/transport
work, not CAD, provenance, cancellation or release evidence.
Production discovery and `PRODUCTION_OCI_IMAGE` remain disabled. The executor
stage now integrates durable supervision and live identity validation; production
activation, renderer/browser and independent reviews remain separate gates. See [progress](macos-progress.md) and the
[executor handoff](macos-executor-stage.md).

The separate [bounded preparation/export contract](macos-preparation.md) now
removes the writable host binds previously used by downloader/source packaging.
Its unit controls do not certify a fresh live Mac run; the historical smoke is
not compliant acceptance and final exact-source CI/ARM64 acceptance remain due.

## Reproduce

Run serially from `feat/macos-feasibility`, with Docker Desktop's active context
`desktop-linux`, Linux ARM64 and no running containers:

```sh
PYTHONDONTWRITEBYTECODE=1 /opt/homebrew/opt/python@3.13/bin/python3.13 \
  scripts/macos_staging_check.py \
  --report-dir "$PWD/dist/macos-staging-new" \
  --wheelhouse "$PWD/dist/macos-report-02/download/wheels"
```

The report path must be new and inside this worktree. Existing wheels are
revalidated against the unchanged hash locks. Trusted offline image packaging and
CAD-library sanity checks are preparation, not user CAD execution. No project,
home, socket or host output directory is mounted into an execution container.
No registry service, push, remote publication, provider or agent is used.

Exit zero means **only** `scope: quota-bounded-staging`,
`staging_stage_passed: true`. `accepted` and `executor_stage_passed` stay false.
Required scoped checks: `containment`, `positive_output`, `byte_exhaustion`,
`inode_exhaustion`, `artifact_transfer`, `cleanup`. Earlier/later milestone checks
are never promoted by a storage pass. Failure reports and raw bounded logs remain.

## Active contract: profile 5 / protocol 3 / manifest 3

Canonical implementation is in `core/src/hephaestus/core/executor/sandbox/`:
`oci.py`, `oci_launcher.py`, `oci_storage_policy.py`, `oci_storage.py`,
`oci_transfer.py`, `oci_worker_io.py` and `_oci_storage_worker.py`.
Build and DFM workers use the same launcher-generated transport invocation,
snapshot, tmpfs profile, attach stream, receiver and cleanup path as controls.
The launcher applies rlimits, checks actual storage, then **execs** the approved
worker: no keepalive shell/supervisor replaces worker PID 1. There is no arbitrary
module, command, path or entrypoint override. Native worker protocols remain native.

| Bound | Ordinary policy (not CAD-capacity certified) | Live control policy |
|---|---:|---:|
| `/work` tmpfs bytes / inodes | 128 MiB / 2,048 | 8 MiB / 128 |
| `/tmp` tmpfs bytes / inodes | 16 MiB / 256 | 2 MiB / 64 |
| Read-only input snapshot bytes / files | 64 MiB / 128 | 64 KiB / 8 |
| Result JSON bytes | 16 MiB | 64 KiB |
| Exported artifact bytes | 72 MiB | 256 KiB |

Both writable tmpfs mounts are `nosuid,nodev,noexec`, private numeric-user-owned
mode 0700, with explicit `size` **and** `nr_inodes`. Kernel bounds include scratch,
unaccepted files, directories and deleted-but-open allocations. Logical input and
export lengths have independent host bounds: sparse logical lengths are not byte
allocation evidence. Tmpfs metadata/anonymous memory also consume the cgroup
budget; tmpfs size is not a total-RAM guarantee.

Docker still exposes writable POSIX `/dev/mqueue` under `--ipc=none`. It is now
masked by a fixed **read-only** 4 KiB / one-inode tmpfs, mode 0000, with
`nosuid,nodev,noexec`. It is not a third writable scratch area. Actual mount flags,
filesystem type and write denial are checked. `/dev/shm` must be absent or
unwritable; runtime-managed regular files and `/dev` must deny writes. Unknown
writable storage mounts refuse. Per-mount RO flags are not unioned with writable
superblock flags. Linux errno values are validated as Linux values on Darwin.

Profile 5 adds a required closed `masked_devices` observation for all five proc
mask paths: no-follow stat, exact integer file type and device major/minor.
Only Linux null **character devices (1:3)** qualify for the writable tmpfs-mask
exception; regular files, directories, symlinks and other devices refuse.
Explicit `{"errno":2}` is admitted only if mountinfo independently has no mount at
that path (some kernels omit `/proc/latency_stats`); missing observations still
refuse. This mandatory evidence change rejects profile-4 manifests and probes.
Protocol/manifest grammars remain 3/3 and framed transfer remains version 1.

Every container explicitly uses logging driver `none` and disables healthchecks.
Before start, inspection must match immutable image config ID, audited entrypoint,
exact command/environment/user, resources/security, tmpfs options, sole RO input
bind and empty persistent log path. Live observations verify capacities, inodes
and writable surfaces. Missing/malformed evidence refuses. The exact manifest
includes policies, transfer version and the mqueue mask; old images/versions have
no compatibility fallback. Each backend instance has a fixed public storage
policy; a small-policy pass does not activate an ordinary-policy instance.

## Inputs and pre-exit artifacts

`SandboxSpec.input_files` declares fixed leaves under `rw_out_dir/inputs`.
Build admission bounds raw aggregate bytes/count before conversion; converted
BRep/mesh/point blobs **and facts sidecars** are admitted before host staging
writes. DFM admits its BRep before writing `inputs/source.brep`. OCI declarations
must match build imports/sidecars or the exact DFM input. Native paths are unchanged.
Existing import conversion remains host-side code; this work does **not** certify
its CAD/memory isolation or authorize untrusted host CAD. CAD acceptance stays closed.

Only declared singly-linked regular files are copied into a fresh private
snapshot, with no-follow directory/leaf opens, exclusive bounded writes and
length/hash rechecks. The snapshot alone is bound RO at `/inputs`. Host copies are
bounded per job; this is not a global history/cache/retention quota.

Workers export while tmpfs exists, using transfer version 1: bounded closed header,
nonce/operation, bounded result JSON, ordered fixed artifact IDs/bodies, completion
digest and EOF. No archive extraction, compression, caller filesystem paths or
post-exit `docker cp`. The receiver streams into private exclusive host files,
not a whole artifact-sized stdout buffer. It rejects malformed/truncated/trailing
frames and artifact/result disagreement. Build source-map JSON must also agree
with collected bytes, including JSON scalar types, before installation.

Only complete transfer, successful typed non-OOM terminal state, successful attach
and confirmed container removal permit exclusive output installation. Receiver
source links are closed before returning. Timeout, output overflow, OOM, invalid
transfer or uncertain cleanup cannot return accepted artifacts. Existing build
assembly/publication artifact and provenance gates remain downstream and unchanged.
Hashes/nonces are corruption/identity checks, **not trusted CAD provenance**.

An unconditional lifecycle guard reconciles the submitted owned name/ID on every
exit before confirmed removal, including `BaseExceptionGroup`, receiver write/
parse plus unlink failures, cancellation and client-reap errors. Unknown create
settlement remains a refusal. Uncertain known-container cleanup retains the exact
ID, clears cached capability and refuses future probe/execute reuse. The original
failure remains in the exception chain. These in-memory guards are not the still
missing durable external owner or live user-cancellation acceptance.

## Fresh storage-review follow-up evidence

`dist/macos-staging-review-live-20261005-02/report.json` passed all six scoped
checks, 15 containment features and 13 serial stdlib controls. Flags:
`staging_stage_passed:true`, `executor_stage_passed:false`, `accepted:false`.
Image config/digest:
`sha256:92ed96672af9605e2c9250a0e0362f8be03fdf37cb66e5c1bd4f8eb5efbf1758`,
`linux/arm64`. Source manifest, image-input hashes, host harness hashes and bounded
raw logs are retained in that directory, as in the historical report below.

- The four mounted proc masks have actual no-follow `file_type:8192` (character),
  major 1 / minor 3 observations. `/proc/latency_stats` is explicitly ENOENT and
  absent from mountinfo. No writable regular-file exemption remains.
- The same deterministic input/output and independent byte/inode controls passed
  at 8 MiB/128 and 2 MiB/64, within 256 MiB, 32 PIDs, 1 CPU, 15 CPU seconds and
  30 wall seconds per control. No ordinary-policy capacity claim.
- `partial-body` created a real host collection file and wrote **9,216 bytes**;
  `artifact-truncated-footer` wrote **18,432 bytes**. Both rejected and removed
  partials without installing artifacts. Saved raw wire, receiver body-byte
  counts and empty-directory checks support this, not zero-artifact controls.
- The fixed finite **384 KiB** stdout emitter exceeded the **335,872-byte** attach
  limit, after transferring 18,432 artifact bytes. `logs/115-oci.json` records
  `TransportOutputLimit` on stdout, with bounded raw prefix/hash/count. Host outcome
  is 125 with no artifacts; actual worker terminal was exit 0 / non-OOM, already
  stopped before cleanup. This is **not a live worker-cancellation test**.
- All 13 controls retain typed non-OOM terminal state, exact IDs, confirmed absence,
  unchanged host sentinels and disabled daemon logging. No unsettled creates or
  unreconciled known containers. No partial transfer directories remain.
- `dist/macos-staging-review-development-20261005-01/focused-final.log` records
  **622 passing focused tests**, zero skips. P1 regression uses a real attach
  subprocess and actual receiver IO with injected write/parse **plus unlink**
  failures, while synthetic daemon state stays running until kill. It asserts
  reaping, kill/removal/absence and no accepted artifacts; uncertain cleanup
  retains ownership and poisons probe/execute reuse. It is not live fault injection.

The first new report `...-01` remains a failure: launcher observation refused before
containment. The collector initially required even an unmounted nonexistent path
to stat successfully; the explicit ENOENT/no-mount rule corrected that. Both image
builds completed without timeout; no build-timeout retry was used. No historical
image/result was relabelled as the current pass.

## Historical profile-4 live evidence (before review fixes)

Prior report: `dist/macos-staging-live-20261005-04/report.json`.

- Image config/digest:
  `sha256:8ce42b37345ccc54e5151f356930cfcc7420cf96f56e853f173fe37682644360`.
  Native `linux/arm64`; daemon-attested local RepoDigest is recorded in the report.
- Exact reviewed image sources: `executor-source-sha256.json`.
  Exact wheel/native/Dockerfile inputs: `executor-image-inputs-sha256.json`.
  Host harness hashes: report `host_source_sha256`.
- All **15** fresh containment features passed. Ten fixed storage controls ran
  serially at 256 MiB memory/swap-total, 32 PIDs, one CPU, 15 CPU seconds,
  30 worker wall seconds. Every control recorded PID 1, exit 0,
  `Running:false`, `OOMKilled:false`, its exact container ID, and confirmed absence.
- Byte controls wrote **8,388,608** and **2,097,152** real non-sparse bytes before
  Linux `ENOSPC=28`, with zero available bytes and remaining inodes.
- Independent empty-file controls allocated **127** and **63** files before
  ENOSPC, leaving zero available inodes and **all** byte capacity free. The root
  directory consumes the first inode. Deletion and subsequent write recovery passed.
- Positive input: 1,036 bytes,
  SHA256 `7fde220561620e7471e83a79b2c1fee39b228b06a65244286451e90d99d17a1c`.
  Mutation returned EROFS. Synthetic output: 18,432 bytes,
  SHA256 `519d1a7b1aa1422ebb2c12e9a4853c93fdfa2eaf8b0585dac5f0a6f732a89164`.
  Synthetic source map: 19 bytes,
  SHA256 `cb8daed7b30399a1c3c8b83b3b7bee4b774a30fc389afc1d375e4c23a3cc4ae8`.
  These are explicitly **not geometry or provenance**.
- Truncation, bad digest, trailing data and oversized header were rejected through
  real attach/receiver IO, with no installed output. A finite 6,912-byte stderr
  control verified attached logging while daemon logging stayed disabled.
- Raw bounded command/inspect logs and base64 wire prefixes (max 64 KiB, with
  full-stream byte counts/hashes) are under `logs/`. Controls fit within that raw
  prefix bound; ordinary large transfers are not duplicated into unbounded logs.
- Owned containers and temporary image tags removed and absence confirmed. No
  unresolved create requests. Preparation cache, source snapshots and reports remain.

Prior reports `...-01` and `...-02` failed storage containment and remain intact;
`...-02/logs/032-oci.json` records the actual writable mqueue observation. `...-03`
was the first passing integrated run. `...-04` repeats acceptance after native-main,
policy immutability and source-map comparison hardening. No build timed out and no
build-timeout retry was used. Each image has its own source identity, not a combined
or retroactively updated snapshot.

## Tests and remaining coverage

`tests/test_macos_staging.py` adds synthetic canonical-path tests alongside the
151 adversarial transfer tests and existing OCI/executor regressions. The focused
historical pre-review suite passed **558 tests**, zero skips; logs are under
`dist/macos-staging-development-20261005-01/`. Native worker routing tests replace
CAD operations with explicitly synthetic test functions; no host CAD is executed.

Not run/certified: untrusted CAD/import conversion, live DFM, ordinary-policy CAD
capacity, full repository suite/pyright, Podman/OrbStack/x86 runtimes, renderer,
authenticated browser, independent security/render review, or final all-stage smoke.
Ambiguous creates still poison the backend; recorded names and failure logs are
not an external settlement barrier. Real observed user cancellation and durable
reconciliation remain implementation work for the next slice. Production activation
and release/cross-platform certification are separate authorization and evidence.
