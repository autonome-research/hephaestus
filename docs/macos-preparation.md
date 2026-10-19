<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# Bounded macOS supply-chain preparation

This repairs the writable `/work` host binds in the milestone downloader and
both source-wheel helpers. Those binds were in **trusted preparation**, not
actual CAD execution; this repair does not demonstrate a new CAD escape. The
historical pre-repair smoke remains noncompliant acceptance. The repair was
published through `a92edc76546b797ada1a30b41373f6b3331dc6bf`, with exact-source
CI and compliant cached ARM64 acceptance recorded in [progress](macos-progress.md).
Subsequent isolated-install repairs need new-source validation; those old results
are not current acceptance. No production backend/agent activation or physical
suspend/clean-machine certification follows.

## Complete paths

- `Smoke.native_dependencies()` in
  [macos_milestone_smoke.py](../scripts/macos_milestone_smoke.py) still pulls and
  verifies the pinned native ARM64 Python base. It calls `prepare_files` with
  `download`, or `download-cache` when reusing an existing wheelhouse.
- [macos_prepare_executor.py](../scripts/macos_prepare_executor.py) and
  [macos_prepare_renderer.py](../scripts/macos_prepare_renderer.py) both call
  the same `prepare_files(..., "package", ...)`. Separate smoke directories
  keep executor/renderer inputs, outputs and ownership independent.
- [macos_preparation.py](../scripts/macos_preparation.py) snapshots explicit
  inputs, records their lengths/SHA-256, creates a random exact-owned container,
  starts/attaches **by its settled full ID**, consumes the framed stdout stream,
  observes terminal state, removes that ID and positively inventories absence,
  then publishes to a new host directory. No post-exit `docker cp` exists.
- The only container command is `/usr/local/bin/python -I
  /inputs/code/macos_preparation_worker.py ROUTE NONCE` in the unchanged
  digest-pinned base, not the audited CAD image. The
  [fixed worker](../scripts/macos_preparation_worker.py) has three closed routes,
  no shell/module/entrypoint option and no environment-based override.

`download` runs only base Python's isolated pip `download`, explicit public
PyPI index, `--only-binary=:all: --require-hashes --no-cache-dir`, 20-second
request timeout and one retry, against both unchanged executor locks. The
cache route substitutes `--no-index --find-links=/inputs/cache` and disables
networking. Neither receives repository source trees, CAD projects or provider
code. Its small code snapshot contains only this recipe, its schema and the
three stdlib OCI transfer/protocol/policy modules.

`package` is network-none. It copies the admitted source snapshot into `/work`,
creates `/work/venv`, installs the unchanged hash-locked **binary** build tools
from read-only `/inputs/wheels` with `--no-index`, then builds exactly the
executor-runtime and opstore wheels with `--no-index --no-deps
--no-build-isolation`. `SOURCE_DATE_EPOCH=0` remains fixed. The only source
inputs are `core/src`, `opstore/src`, opstore's manifest, bridge limits and the
executor package's manifest/build hook. Package wheel tags must be
`py3-none-any`; versions come from those snapshotted manifests. No CAD script
is executed. After verified export, the host generates the two hash-pinned
local requirements in a new directory; it never accepts a worker-supplied lock.

Both existing Dockerfile builds still use `--network none --pull=false`, ARM64,
CPU/data/nproc ulimits and their previous aggregate wall budgets. They install
hash-pinned public/local wheels offline. Renderer Python/native URL-size-hash
fetches and executor's pinned native fetcher are host supply-chain steps,
not container output mounts. Both ARM64 native locks now locate the unchanged
`libexpat1_2.5.0-1+deb12u3_arm64.deb` at
`https://snapshot.debian.org/file/90544df9f8be225046764399c0a1786b98669611`.
Snapshot's binary-version and file-info APIs identify Debian security provenance;
a fresh HTTPS download matched 87,944 bytes and SHA256
`3caad0fb4382e206b005737de35b3193450589a10053f8415ded216649a233bc`, including
embedded package/version/ARM64 metadata. The SHA-1-shaped archive locator is not
the integrity authority: the original SHA256 and byte length remain mandatory.
Only that exact Snapshot URL/pin tuple is admitted; ordinary native sources remain
HTTPS `deb.debian.org` pool paths, Python wheels HTTPS `files.pythonhosted.org`.
Both fetch paths refuse redirects rather than following arbitrary hosts/protocols.
The curl fetcher disables user configuration before all other options, so `.curlrc`
cannot weaken TLS verification or add transfers.
No package upgrade or old-cache substitute is involved. Image tags remain random, local and
recorded before build; no push/registry/provider service is introduced.

## Mount and resource policy

The **only bind** is the freshly admitted private snapshot at `/inputs`, with
`readonly,bind-recursive=disabled`. No project, home, socket, checkout root or
host output directory is mounted. Root is read-only; capabilities are dropped,
no-new-privileges is set, logging disabled, numeric UID/GID retained, IPC none.
Network is bridge only for public binary downloads; every other route is none.

These are explicit **preparation-only** limits, not changed CAD/render quotas:

| Resource | Limit |
| --- | --- |
| `/work` tmpfs | 1 GiB, 16,384 inodes, mode 0700, caller UID/GID |
| `/tmp` tmpfs | 256 MiB, 4,096 inodes |
| Both scratch mounts | `rw,nosuid,nodev,noexec` |
| `/dev/mqueue` | existing 4 KiB/one-inode read-only mode-0000 mask |
| Shared memory size | 4 KiB; IPC none |
| Memory / memory+swap | 1,536 MiB / 1,536 MiB (no additional swap) |
| CPU / processes / open files | one CPU; 128 pids; 1,024 fds |
| CPU rlimit | download 240 s; package 120 s |
| File-size rlimit | 256 MiB |
| Attach wall allowance | download 300 s; package 180 s, capped by original absolute work deadline |
| Each cleanup | separate 30 s continuous budget, not restarted per command |
| Final harness cleanup | original separate 120 s budget retained |
| Input snapshot | 896 MiB, 2,048 files, 4,096 visited entries including ignored entries, depth 20 |
| Repository source within snapshot | 64 MiB |
| Lock parsing / generated package spec | 128 KiB per lock / 64 KiB spec; spec reserved within snapshot limits |
| Export | 128 wheels; 256 MiB per public wheel; 768 MiB aggregate |
| Source-wheel export | exactly two allowlisted wheels, at most 64 MiB each |
| Frame header / result / stderr | 64 KiB / 64 KiB / 512 KiB |

The larger memory ceiling (previously downloader 768 MiB, package 1 GiB)
explicitly accounts for private tmpfs instead of host-backed writable `/work`.
The downloader pids ceiling is now 128 rather than 64. Work storage formerly
had **no container filesystem quota**; it now has both byte and inode limits.
`/tmp` retains its byte ceiling and gains an inode ceiling where absent. CPU
and attach budgets are unchanged. CAD `StoragePolicy`, render limits, audited
module allowlists, launcher grammar and production discovery are unchanged.
Oversized dependencies fail; no automatic quota escalation exists.

## Transfer, publication and ownership

The [preparation schema](../scripts/macos_preparation_transfer.py) reuses
`oci_transfer`'s incremental framing, EOF/footer digest checks, stable-file
collection, no-follow descriptor opens and exclusive install/rollback. The
internal framing adapter is not a worker registry: the public CAD receiver and
exporter remain fixed to their old schema/limits and reject preparation ops.

Before snapshot writes, the full bounded inventory is admitted. Every path
component is opened without following symlinks; special files and multiply
linked files refuse. Copies are exclusive, read-only and independently
rehashed. Empty source marker files are allowed; wheel bodies remain nonempty.
An incomplete snapshot is never mounted and a stale snapshot directory refuses.

Before export, the worker admits the whole output inventory, rejecting extras,
links, special files and excess bytes/count. The host independently checks
wheel distribution/version against the locks, one wheel per required target
package, canonical leaf names, sizes, nonduplicate JSON/descriptors, nonce and
operation, result/body correspondence, individual SHA-256 and the full-stream
completion digest. The existing lock-marker vocabulary is evaluated explicitly for the pinned
Linux ARM64/CPython 3.13 base, not using Darwin's platform; unknown marker or
requirement grammar fails closed. Host preparation remains stdlib-only. Public wheel hashes must be in the original locks.
Source wheel integrity is bound to this fresh trusted build and input manifest,
not claimed to be an externally preknown reproducible hash.

The complete frame is flushed **before container exit**. The host incrementally
collects at most the finite export budget, never buffering whole wheels in RAM.
EOF alone is insufficient: attach must succeed, inspected state must be stopped,
exit zero and not OOM, and exact-owned removal must be confirmed. Only then does
exclusive installation rehash the collected bytes and link them into a fresh
host directory. Ancestor symlinks, existing destinations and changed collected
bytes refuse. Private host directories must remain under sole harness control;
this is not protection against a concurrent malicious host process. Failures
never produce accepted preparation evidence; partial rejected directories are
not reusable as successful output.

Create intent and settlement are now durable in base `Smoke`, not only its
renderer subclass. Unknown create acknowledgements remain pending even if a
later inventory is empty. Failure, cancellation, deadline expiry, malformed
transfer and interruption unwind through exact-owned cleanup; second INT/TERM
signals are masked during its bounded budget. Existing transport client-group
kill/reap and late-ACK refusal remain. No broad container/image cleanup occurs.

Evidence per route lives in `prepare-ROUTE/`: input manifest, terminal state and
export manifest; full actual argv and finite stream limits are in `report.json`,
bounded diagnostics in `logs/`, and durable IDs in `build-ownership.json`.
Rejected preparation and historical reports are never promoted into acceptance.

## Controls and remaining evidence

[Preparation tests](../tests/test_macos_preparation.py) invoke all actual helper
paths with a synthetic daemon, inspect their complete argv/mounts and fixed
child recipes, and exercise success/refusal through the real transfer engine.
Controls include truncation, bad digests/hashes, nonce/op skew, malformed or
oversized headers, count/aggregate limits, duplicate/unknown/path-escape files,
symlink/hardlink/FIFO inputs and outputs, stale publication, owned cleanup on
create failure, timeout, cancellation, interruption, terminal/cleanup failures,
and a real owned attach-like subprocess cancellation/reap. A 65 MiB positive
stream proves large wheels use the separate finite preparation policy. An
isolated no-site-packages child imports the exact downloader code snapshot
without CAD/provider modules.

These tests are unit/contract controls, **not live Docker preparation, kernel
quota exhaustion, native wheel-build acceptance or full Mac acceptance**.
For a fresh-download setup without a prior wheelhouse, follow
[workspace setup](macos-workspace.md); omission of `--wheelhouse` downloads the
locked native wheels. A new checkout isolates project caches but does not isolate
the Docker daemon/base/BuildKit cache or provision a new OS. Exact-source CI and
another empty same-host fixture remain required for these install repairs;
physical suspend and clean-machine certification remain separate.
