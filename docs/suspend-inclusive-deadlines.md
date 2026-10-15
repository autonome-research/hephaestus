<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# Experimental Mac deadlines: expiration at resume

This describes the experimental Mac launcher and shared OCI lifecycle code, not
production activation or physical suspend certification. Implementation/control
coverage is not evidence of historical machine-global invariance.

## Clock and scope

`core/src/hephaestus/core/deadline.py` acquires:

- Darwin 10.12+: `mach_continuous_time()` from `/usr/lib/libSystem.B.dylib`, an
  unsigned 64-bit tick count. `mach_timebase_info()` must return success and
  nonzero numerator/denominator. Integer `ticks * numer // denom` yields ns.
- Linux 2.6.39+: Python's `clock_gettime_ns(CLOCK_BOOTTIME)`. Availability includes
  an actual successful kernel read, not merely existence of the Python constant.

Both facilities include system suspend and are monotonic, not adjustable UTC.
Missing symbols, unsupported platforms, invalid timebases and failed reads refuse
bounded work; there is no UTC, `monotonic`, or `perf_counter` fallback. Ordinary
Python monotonic/performance clocks do not provide this portable guarantee. On
this Mac Python reports `mach_absolute_time()`, **not** the continuous clock.
Linux `CLOCK_MONOTONIC` also excludes suspend. UTC is still appropriate for human
report timestamps, never for these limits.

References: [Apple mach_continuous_time](https://developer.apple.com/documentation/kernel/1646199-mach_continuous_time),
[Linux clock_gettime](https://man7.org/linux/man-pages/man2/clock_gettime.2.html).
The latter documents that BOOTTIME is MONOTONIC plus suspended time (and that
REALTIME is adjustable). Neither clock promises execution while the CPU is asleep.
Linux time namespaces/VMs have their own clock domain: no host deadline is sent
into the OCI worker. Absolute values travel only between trusted processes on
the same host boot. They must not be restored as executable deadlines after reboot;
durable ownership records are for reconciliation, not replay authorization.

## Separate limits, not one outer wait

The historical audit recorded about 2638 calendar seconds around an external
Python `wait(timeout=2400)`. That external workflow wait was neither a worker
budget nor an application-wide continuous deadline. This implementation does
not change the coding harness/tool's outer wait and cannot retroactively certify
that run.

| Boundary | Authority and enforcement |
| --- | --- |
| Milestone work | 2400 seconds continuous from `Smoke` creation; inherited by nested smoke collectors, direct OCI probes and owners, not refreshed per stage. Checked before commands/stages and before acceptance. |
| Native workspace session | Existing `--wall-seconds` (default 1800, max 3600); now starts before setup, not after server startup. Smoke's 600-second child cap is unchanged and additionally capped by the parent's absolute deadline. HTTP/websocket admission and executor/renderer entry check independently of the shutdown task. |
| OCI owner | Existing 420-second work ceiling, capped by the enclosing session/smoke deadline; absolute deadline crosses trusted parent/owner IPC. Before admission, controls, execution and successful completion. Existing alarm retained only as an auxiliary awake hang detector, **not** suspend authority. |
| OCI job | Existing `SandboxSpec.wall_clock_s`, unchanged profiles (supervised max 180 seconds). Continuous across create, validation, start, result handling and installation. No start after expired create/validation. |
| Runtime client | Existing per-command allowance, bounded by the absolute caller budget through synchronous evidence wrappers. Check before Popen, after selector wake, before I/O delivery and before returning success. |
| Parent waiting for owner | Existing 435-second hang detector, additionally capped by enclosing remaining work + existing 15-second margin. Continuous polling; a late buffered owner ACK cannot authorize success. |

Selector/event/process waits only schedule checks. Polls are at most 100 ms
(50 ms for the independent-owner channel); they are not real-time scheduling
promises. At the first scheduled boundary on resume, an elapsed deadline refuses
new work and begins/continues exact-owned cleanup. Ready I/O or a buffered success
cannot override expiry. There is necessarily a scheduling gap between checking
and a syscall; this is boundary enforcement, not an atomic kernel admission gate
or a claim that arbitrary instructions cannot run after the deadline. A request
admitted before expiry can still finish bounded bookkeeping; this is not rollback.

Ordinary bounded CAD measurement passes retain their documented post-deadline
measurement drain, now using continuous time. Independent cleanup-owner ACKs
use the strict variant: late ACKs are **not** successful lifecycle completion.

## Cleanup is separate, and can refuse

Expiry never means that resources magically disappeared during sleep. Work
budgets are not extended for cleanup, and cleanup permission is not permission
to start another model/build/render operation.

- One **30-second continuous reconciliation budget** per OCI container lifecycle,
  shared across nested/retried cleanup helpers. Individual daemon commands retain
  their smaller existing limits. A second suspend consumes this cleanup budget;
  on resume no new daemon command is launched after it expires.
- Local runtime-client SIGKILL/reap retains its separate **5 seconds**, followed
  by **2 seconds** for positive group absence. These local epilogues can follow a
  daemon-command deadline; they are not additional worker runtime.
- An independent owner's parent closes IPC on timeout and allows the existing
  separate **10-second reap**. It does not kill the cleanup owner on a late ACK.
  Owner close retains its existing **435-second** separate wait, now continuous.
- Browser/server shutdown retains **60 seconds** for graceful termination,
  **10 seconds** for forced reap, and **5 seconds** for its log-reader join.
  These are distinct per-process epilogues, not extensions of the work ceiling.
  A wait that reaps a child but returns after expiry still refuses completion;
  it must not trigger a subsequent numeric-group signal after PID reuse becomes
  possible. Browser/readiness sub-budgets retain the parent's absolute endpoint,
  rather than restarting a relative allowance after clock progression.
- Final smoke-owned container/tag cleanup and inventories have an additional
  **120-second continuous aggregate cap**, with existing smaller command limits.
  Only explicitly marked cleanup commands use it; ordinary commands still
  consult the expired work deadline. Nested collectors have their own cleanup
  scope. These are additive phase bounds, **not** a promise that the entire
  launcher exits within 2400 seconds including cleanup or host sleep.

No cleanup is promised while asleep, during an uninterruptible kernel operation,
or while the daemon is unavailable. Failed/expired cleanup retains durable
pending/unreconciled ownership and refuses reuse; absence is not inferred from
client death or a failed inspect. Successful removal without successful absence
confirmation is still unresolved. No broad kill, prune, restored-PID signal or
unknown-resource deletion is introduced.

Delivered cancellation retains its reason; worker deadline expiry remains
`timed_out`; output-limit and OOM observations remain distinct refusals. Owner
lifetime expiry is recorded as timeout rather than successful completion.
Uncertain cleanup can override a timeout result with a refusal, retaining the
original exception context and ownership evidence.

## What this does not certify

Production/experimental agent attachment remains disabled. The agent bridge's
adaptive RPC watchdog credits handler wait time; it is not a finite session
lifetime. Its ordinary monotonic timing and the opstore's persisted UTC
lease/delegation contracts are **not migrated here**. Neither are native bwrap's
`communicate(timeout=...)` limits. This patch therefore does not claim a universal
suspend-inclusive guarantee for every engine/agent path on Linux. Linux support
here is the genuine BOOTTIME facility and the shared OCI/owner supervision paths;
real Linux CI is still required.

The existing smoke download/package writable-bind issue is not repaired here.
Do **not** run that smoke as guardrail-compliant acceptance until separately
repaired/reviewed. No old smoke report becomes compliant because clocks changed.

## Validation and future physical trial

Deterministic tests advance the injected continuous clock while UTC moves in
both directions; real owned/reaped Python subprocesses exercise ready-I/O races.
Unadvanced controls succeed, advanced controls time out. Synthetic daemon tests
prove no post-expiry start and separately exhausted cleanup retaining ownership.
These are **NOT physical Mac suspend certification**. No SIGSTOP experiment is
represented as sleep; no physical suspend trial was run for this change.

A separately authorized operator can validate physical suspend narrowly:

1. Use a disposable **owned Python child only**, not Docker/CAD, browser, provider
   work, or the milestone harness. Save source hashes, OS/Python versions and
   actual raw `mach_continuous_time` plus timebase before and after the trial.
   Keep a second awake control run with identical source and a fresh evidence
   directory. Never overwrite a previous trial.
2. Run `SubprocessTransport` with an `OwnershipJournal`, a **20-second** timeout,
   bounded output and a child that prints a readiness marker then waits. Keep
   a bounded child self-exit as a backstop. Record the live owned PID/group and
   continuous deadline before indicating readiness to the operator.
3. Only with new explicit permission, the operator may use the normal macOS UI
   to suspend soon after readiness and resume after the deadline. Do not use
   `pmset`, reboot, change power settings, prevent sleep, or restart Docker.
   If no genuine sleep occurred or the deadline was not crossed, label the trial
   inconclusive, not passed. Do not increase the 20-second budget to obtain green.
4. On resume require `TransportTimeout`, no successful post-expiry result, actual
   owned-child reap and positive group absence within their separate cleanup
   bounds. Independently recompute elapsed ns from raw ticks/timebase; compare
   the recorded deadline, not UTC. Use read-only OS sleep/wake records to establish
   physical sleep; a clock jump or SIGSTOP alone is insufficient.
5. A second trial may cover sleep **during cleanup**: expect refusal/unresolved
   ownership if its separate bound elapses, not impossible cleanup-in-sleep.
   Do not do this with daemon resources without a separately reviewed recovery
   procedure. Retain every failure and abort on ownership uncertainty.

That child-only physical trial would validate the host-clock/transport claim,
not VM suspend behavior, complete workspace scheduling, CAD acceptance, or
historical machine invariance. Those claims need separately scoped evidence.
