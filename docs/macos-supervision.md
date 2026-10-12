<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# Experimental macOS OCI ownership and cancellation

**Historical scoped executor acceptance; not current-source certification.**
The old scoped report had full `accepted:false`; a later complete workspace run
passed, but changed runtime sources supersede that live acceptance. F1's shared
lifecycle design remains unresolved. See the [roadmap](macos-roadmap.md) for
fresh CI/recovery gates. Ownership rules below remain binding.

The
[executor CLI](macos-executor-stage.md) now uses this supported injection for fresh
image/storage/CAD/publication and observed user cancellation, separate timeout and
ordinary failure, with exact owned cleanup. See [progress](macos-progress.md) for
source-specific evidence. Production discovery and `PRODUCTION_OCI_IMAGE` are
unchanged. No worker command, diagnostic backdoor, image entrypoint override or
profile exception was added. Versions remain **profile 5 / protocol 3 / manifest 4 /
transfer 1**. The original host implementation contract below remains binding.

## Supported explicit injection

`core/src/hephaestus/core/executor/sandbox/oci_supervisor.py` exposes
`SupervisorConfig`, `SupervisedOciBackend` and `reconcile`. A config supplies the
same explicit `OciRuntime`, immutable image reference, platform and numeric
non-root identity as the canonical backend, plus a **private operator-owned
session directory** and a fixed storage policy. There is no discovery/environment
activation, service, or arbitrary workload command. Keep the directory outside
workload snapshots and retain it through recovery.

Use `with SupervisedOciBackend(config) as backend`, require `backend.probe()` to
pass, and inject that instance into `run_build`, `Publisher(backend=...)` and,
later, `WorkspaceRuntime.open(backend=..., serve_mode=True)`. Each `execute`
starts a fresh fixed host controller process, re-probes the canonical backend,
requires the previous image-bound identity to match, and only then executes the
approved worker. No monkeypatch, host CAD fallback, or unsafe backend is involved.
The serving runtime now projects **its injected backend's** probe; unsafe
injection still refuses and unsafe capability projection is false. This is not a
current-source workspace/render/browser acceptance claim.

The wrapper supports at most one operation at a time, 16 operations per retained
session, 64 recorded containers and 256 recorded client PIDs. These are ceilings,
not a promise of 16 executable jobs: each owner now reserves room for four
containers and 64 clients **before any runtime side effect**, including exceptional
cleanup, so admission refuses earlier when the retained session lacks capacity.
The renderer uses bounded per-operation session directories and closes/rechecks
previous owners; no ledger bounds increased or historical records were discarded.
Explicit recovery has a separate bounded journal. This fixes the first live render
integration's mid-cleanup client-ledger exhaustion (retained failed report and exact
owned reconciliation in progress). Jobs are limited to
one CPU, <=2 GiB address space/cgroup memory, <=256 PIDs, <=120 CPU seconds and
<=180 worker wall seconds. Existing storage byte/inode limits, RO inputs, streamed
bounded artifacts, no daemon logging and typed OOM refusal remain canonical.
Probe containers retain their smaller existing envelope. There is no persistent
multiprocessing resource-tracker or helper: owners use fixed subprocesses and a
private inherited control connection. No global daemon is launched.

## Durable state and settlement

`oci_ownership.py` uses a private no-follow directory, exclusive process lock,
bounded closed version-1 JSON, atomic replacement and file/directory fsync.
Every exact random create **name is durable before client submission**. Only a
successfully parsed, acknowledged create ID settles its request. The ID is
persisted before attach or cancellation cleanup. A nonzero client result, corrupt
response, disconnection, output limit or deadline can be ambiguous even if the
name is absent. Bounded inspections reclaim resources but **never settle requests**.

Successfully acknowledged, removed and confirmed-absent containers do not poison
ordinary reuse. Names/IDs and terminal states are retained instead of erased.
Local client spawn intent is durable **before Popen**, including observer and
recovery clients; the exact PID follows and is marked reaped only after wait and
process-group absence. Death before PID persistence remains a pending launch. Signalling precedes leader reaping to avoid signalling a
reused PID. Darwin's zombie-only group EPERM is not absence: reap and bounded
absence checks must still succeed. Surviving groups fail closed.

`reconcile(config)` locks the state and targets **only exact recorded names/IDs**.
It can reclaim a delayed resource or complete removal of an acknowledged create.
It never kills restored host PIDs, which may have been reused. Unknown create
settlement, unproved local-client reaping, or an owner killed before its final
record remain durable pending/refusal states. There is no report-import, finite
absent-poll, deletion-of-journal or force-success API. Do not delete pending state
or open a new session merely to evade it.

## Cancellation and death

`cancel_active()` sends an explicit user-stop message; callers must still await
the synchronous result/cleanup. `observe_running()` performs an independent,
bounded daemon state inspection of the unique settled **execution** container,
not a probe or attach PID, and saves raw typed evidence. For acceptance, first
observe Running, then request cancellation, then require the recorded received
stop, actual successful kill command, non-OOM terminal state, absence and reaping.
A cancellation during create is valid cancellation behavior but **not** proof of
cancelling an observed running worker.

During create, cancellation is remembered without killing the create client:
the bounded request may still return a definitive ID, which is then cleaned up
without starting it. During attach, cancellation wakes the real transport,
terminates/reaps its client group, and the canonical unconditional guard kills,
inspects and removes the actual container. Attach disappearance alone never
certifies worker death. `ExecutionCancelled`, `ExecOutcome.timed_out`, ordinary
failure and cleanup uncertainty are separate outcomes.

`executor/cancellation.py::run_cancellable` propagates an async dispatch stop into
the synchronous owner's control path and waits for its bounded teardown before
releasing operation locks or staging. Repeated task cancellation cannot abandon
that wait. HTTP and MCP dispatch use this boundary. Async cancellation may itself
originate from an outer deadline or disconnect, so it records `caller_cancel`,
**not** certified `user_cancel`. Explicit `cancel_active()` is the user-stop seam.
Neither bridge/provider/agent calls nor a new public cancellation route are needed
for the next local acceptance demonstration.

Parent connection EOF triggers `parent_closed` cleanup in the independent owner;
it is not relabelled user cancellation. SIGTERM/SIGINT request owner cancellation.
The owner's 420-second outer hang detector covers probes, controls and a <=180s
worker; exceptional cleanup can add the canonical finite control/reaping bounds.
The parent refuses on an owner deadline/disconnection and retains recovery state.
No lifetime guarantee is claimed if the OS/daemon cannot schedule or answer.

**Abrupt owner SIGKILL/machine death is not magically recoverable.** It can land
between process spawn and PID persistence, or after the daemon received create
but before the response was journaled. An unfinished per-operation owner record
prevents silent restored reuse even when the container journal alone looks clean.
Recovery attempts exact owned container reclamation but cannot prove unknown
request settlement or reap another process's former children. Retain the record
and report that uncertainty. On parent death with a surviving owner, the owner can
finish cleanup and its final record allows recovery; the dead parent has no
`waitpid` evidence, so this is not the successful live cancellation acceptance
case. No always-running recovery daemon is implied.

## Actual per-operation evidence collector

The owner writes fresh `operation-NN/` records from **actual calls**, not a schema
that accepts supplied hashes:

- bounded original request/control input and actual source hashes;
- immutable image/platform/installed-source identity and fresh containment bytes;
- raw bounded command stdout/stderr prefixes, lengths/hashes, errors and limits;
- streamed wire prefix/length/hash, transfer/input/output records, effective config;
- typed terminal/OOM state before removal, durable names/IDs and client reaping;
- independently observed `running.json`, stop request/receipt timestamps/reasons;
- owner completion and parent `reaped.json` (the latter requires actual wait).

Each operation has at most 128 recorded commands and 8 MiB of command evidence;
wire previews are 16 KiB, control previews 64 KiB and requests <=16 MiB. The
original fixed request IPC file is separately bounded at 24 MiB (normally <=16 MiB
plus configuration). No daemon logs or unbounded output files are created. Native
CAD result parsing/assembly and publication still run through `run_build` and
`Publisher`; transport hashes are not kernel or publication proof. The per-operation evidence always retains `accepted:false`. The executor CLI now
collects and validates scoped live acceptance around it. Historical complete
workspace acceptance is recorded separately in progress; it does not certify
these changed runtime sources.

## Host tests and next gate

`core/tests/test_oci_supervision.py` uses a **synthetic daemon CLI**, with real
controller/client subprocesses. It covers delayed acknowledged creates,
cancellation during create and attach, actual Running observations, timeout,
daemon removal errors, parent process death/EOF, abrupt owner death, real client
children, reaping uncertainty, restored pending state, fsync failure before
submission, async cleanup and injected capability projection. The projection test
executes the actual dependency-free method in isolation; it is not a full
`WorkspaceRuntime.open` integration test. See [progress](macos-progress.md) for
exact commands and counts, including retained failed runs.

Fresh image/storage and real CAD/publication/cancel/timeout/failure checks are now
integrated in the executor CLI. Next: review supervision/security independently.
Renderer, GLB minting, browser and final all-stage acceptance remain separate
required gates.
