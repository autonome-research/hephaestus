<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# macOS acceptance roadmap

**Production remains closed. Do not merge until required checks on the reviewed
source are genuinely green.** This is an evidence-gated plan, not a release
commitment or schedule. No broad installer or feature implementation is authorized
by this document. [Progress](macos-progress.md) separates current results from
historical failures and passes; prior live acceptance is **superseded for changed
runtime sources** until fresh images and a new all-stage run succeed.

## Current implementation versus certification — 2026-10-15

The unpublished four-gap repair has local source review and serial regression
coverage, not certification: Plan's bounded evidence/lifecycle exceptions and
Darwin re-adoption are tested; official hash-pinned Khronos provisioning is wired
fail-closed but its two original route tests still require explicit CI **passes,
not skips**. Mac/shared-OCI continuous deadlines have real clock acquisition and
injected progression controls, not a physical suspend trial. Legacy bwrap,
agent watchdog and persisted UTC paths are outside that migration.

Before another all-stage smoke, repair/review the existing writable download and
package binds. The retained 13/13 raw harness result is **not guardrail-compliant
acceptance**. Root partial-host typing still fails; full native/typing/render
coverage belongs to current-source CI. Clean-machine certification below has not
been performed. No publication or activation is authorized by this review.

See [current results](macos-progress.md) and the separately authorized
[physical-suspend procedure](suspend-inclusive-deadlines.md). These distinguish
implemented, locally tested and unverified claims; they do not add new numerical
gates to the existing phases below or promise historical global-state proof.

## Phase 1 — CI correctness

Exit only when the exact reviewed tree has successful locked dependency
provisioning, root strict Pyright **zero errors/warnings**, Ruff/format/docs/license
checks, full native core and all three server shards green. All required CI jobs
must finish, including unchanged pinned-render goldens, section golden, Khronos,
synthetic browser and G4 e2e stages; no hidden failing selection, new exclusion,
waived assertion, threshold relaxation or golden rebaseline.

Verify the shared F1 lifecycle repair without turning an independent cleanup owner
into a kill-on-terminal native pass. Preserve duplex EOF/cancellation, bounded
receives, durable ambiguous-create refusal, exact PID/group reaping and
acknowledgement-before-reuse. Require passing reruns of the reproduced baseline
browser failures and any newly reached downstream failures. Local synthetic passes and partial-host typing are supplemental,
not substitutes for full-dependency native CI.

## Phase 2 — clean-machine reproducible installation

Exit after **two independent fresh Apple Silicon environments**, with empty
project caches/stores and no inherited venv, reproduce the documented workspace
setup and all 13 acceptance stages from the same reviewed source/locks. Record
macOS, hardware/RAM, Docker Desktop/VM quotas, native browser, tool versions,
verified download hashes, image digests and source/bundle manifests. Missing pinned
bytes must fetch with hash verification or fail explicitly; a reused wheelhouse
alone proves neither clean installation nor reproducibility.

Use only the non-CAD host dependency subset and frozen web dependencies; no host
CAD, amd64 emulation or global Docker changes. Require the authored two-solid
162 mm³ build, all 12 linked faces, exact masks and kernel section PNG/provenance,
authenticated HTTP/Chrome behavior, and independently verified owned cleanup.
Retain every failed attempt; open design findings remain open. See the
[workspace procedure](macos-workspace.md), not a new installer.

## Phase 3 — reliability and real Apple Silicon CI

Before running disruptive experiments, approve an isolated machine/resource plan
and explicit bounds. Exit requires:

- At least **10 repetitions per scenario**: cancel during create and observed
  running executor/renderer work, timeout, ordinary failure, parent EOF/SIGTERM,
  abrupt owner death, daemon disconnect/restart and host crash/restart. Classify
  actual restart tests separately from injected faults.
- Successful cancellation proves ordered request/receipt, worker stop, typed
  non-OOM terminal state, removal/absence and client/group/owner reaping. Lost
  create/reap acknowledgement instead passes only as **durable refusal** with
  exact-resource reconciliation; no journal deletion or replacement session to
  evade unresolved ownership.
- An **8-hour attended endurance run with at least 100 serial operations**, across
  deliberately closed bounded sessions: exercise renderer rollover and the
  16-operation refusal, then reopen only after affirmative settlement. No
  unbounded service or relaxed worker/session quota. Zero leaked owned resources,
  stale artifact reuse or silent failures; record latency, RSS, swap and disk
  growth against predeclared per-fixture budgets.
- Repeat the reliability workload on a real **8 GB Apple Silicon Mac** under
  controlled memory pressure with the documented roughly 4 GB VM. Record OOM and
  refusal behavior and verify host responsiveness, bounded cleanup and unchanged
  project/store integrity; do not infer this from a small VM on a larger host.
- Real Apple Silicon CI (not an emulated Linux lane) runs containment, fresh
  build/render/browser and recovery gates on the proposed macOS/Docker matrix.
  Require **three consecutive complete green candidate runs**, retaining failures
  and exact source/image/resource evidence, alongside Linux native CI.

## Phase 4 — narrowly supported release

Only after Phases 1–3 and separate security/provenance/release approval: publish a
reviewed support matrix limited to **Apple Silicon + Docker Desktop** versions
actually tested, immutable image artifacts, reproducible packaging, operator
recovery instructions and rollback evidence. Any production activation is a
separate reviewed change with fail-closed discovery and probes; this roadmap does
not enable `PRODUCTION_OCI_IMAGE` or grant release approval.

Candidate supported scope: bounded local authenticated workspace, requirement-gated
builds, RGB/exact selection masks, supported axis sections and provenance-linked
GLB readback in the tested native Chrome workflow. Experimental availability today
is not a support promise. Unsupported until separately accepted: agents/providers,
selection-popover UI, pairwise interference, DFM/import conversion,
export/drawings/posed scenes, arbitrary view/focus/explode, large CAD, other
browsers, Intel Macs, Podman/OrbStack and unattended recovery. No host CAD fallback.

## Phase 5 — capability and platform expansion

Each additional capability/runtime/platform needs its own contract, threat/resource
review, reproducible installation and native CI/reliability evidence before entering
the support matrix. Keep unavailable features explicit; do not extrapolate Docker
Desktop evidence to other runtimes or Linux native evidence to macOS.

## Separate source-provenance disclosure

Clean-machine installation is **not** source clean-room provenance. As disclosed in
the PR, Nurb source (FSL-1.1-MIT) was inspected separately during feasibility
research; no Nurb source/assets were copied into this Apache-2.0 project.
Implementation and diagnostic fixtures use existing Hephaestus contracts and
public build123d APIs. No vendor CAD, PDFs, images or benchmark answers ship.
The [contribution boundary](../CONTRIBUTING.md#the-clean-room-boundary) still applies.
