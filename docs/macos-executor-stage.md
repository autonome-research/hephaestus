<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# Experimental macOS executor stage

**Historical scoped executor evidence; superseded for changed runtime sources.**
This stage's report had full `accepted:false`. A later complete workspace,
[renderer](macos-renderer.md) and authenticated browser run passed, but subsequent
regression/type repairs supersede that live acceptance too. Fresh current-source
images and all-stage acceptance remain pending after CI stabilization; see
[progress](macos-progress.md) and the [roadmap](macos-roadmap.md).
Production discovery and `PRODUCTION_OCI_IMAGE` remain fail-closed. This is a local
explicit-injection acceptance command, not a released workspace launcher.
No selection bundle or `_mint_bundle` bypass exists.

## Reproduce independently

Use native macOS ARM64, the local `desktop-linux` Docker context, no active
containers, and this worktree's `feat/macos-feasibility` branch:

```sh
PYTHONDONTWRITEBYTECODE=1 /opt/homebrew/opt/python@3.13/bin/python3.13 \
  scripts/macos_executor_check.py \
  --report-dir "$PWD/dist/macos-executor-independent-new" \
  --wheelhouse "$PWD/dist/macos-report-02/download/wheels"
```

The report directory must be **new** and inside this checkout. The existing
wheelhouse is copied and revalidated against the original pinned hash locks.
Sources are packaged offline, with identical inputs reusing BuildKit cache. No
host CAD dependency, provider/model/agent call, registry push, entrypoint override,
project/home/socket mount, unsafe backend or production setting is needed.

Exit zero requires fresh containment, build, cancellation and cleanup plus their
mandatory cross-linked evidence. `executor_stage_passed:true` does **not** change
full `accepted:false`. No previous/supplied JSON report can authorize execution.
The existing milestone command runs the same stages:

```sh
./scripts/macos_milestone_smoke.sh \
  --report-dir "$PWD/dist/macos-milestone-independent-new" \
  --wheelhouse "$PWD/dist/macos-report-02/download/wheels"
```

Its exit remains **1** while render/browser stages are missing, even if its scoped
executor stage passes. See [progress](macos-progress.md) for final source-specific
report paths and test commands.

## Actual checks

- A genuinely resolved immutable native ARM64 image; active **profile 5 / protocol
  3 / manifest 4 / transfer 1**. Installed source/package identity is collected by
  the trusted manifest and bound to daemon image/platform, not workload metadata.
- Fresh canonical containment and all integrated [storage controls](macos-staging.md):
  both mounts' separate byte/inode ENOSPC and recovery, read-only inputs, deterministic
  output, malformed/truncated/footer/digest transfer rejection, finite stdout overflow,
  partial artifact cleanup and finite stderr with daemon logging disabled.
- `SupervisedOciBackend` under ordinary storage policy, re-probing every operation.
  Actual `run_build` builds independently authored disjoint 4×5×6 and 2×3×7 cuboids:
  **two sealed solids, 162 mm³**. Source-map binding lines and geometry namespace,
  source hashes, validated BREP/source-map bytes and hashes are checked.
- A second **fixed build worker** re-reads that actual exported BREP through the
  existing preconverted, content-named, read-only input contract and verifies all
  kernel metrics agree. It does not run the host import converter or publish a
  misleading STEP import identity.
- Actual project freeze, `Publisher(backend=...)`, content-addressed installation,
  current publication, revalidation and freshness. Published BREP bytes equal the
  validated snapshot. Source-map transfer bytes and canonical publication bytes
  have separately named hashes; whitespace is not silently conflated. Trusted
  execution identity agrees through assembly, publication and freshness.
- Explicit user cancellation waits on a **passive bounded Docker start-event
  stream**, independently inspects the unique settled execution container as
  `Running:true`, then calls `cancel_active()`. Request and owner receipt ordering,
  actual successful container kill, exit 137, non-OOM terminal state, exact removal
  and client/child reaping are required. Event-stream clients have their own durable
  ownership and bounded logs; neither a timer nor attach disappearance proves Running.
- A separate busy build hits its 20-second wall ceiling, with actual Running,
  `TransportTimeout`, kill and exit 137 evidence. A separate ordinary `ValueError`
  returns a failed build plus a validated one-solid 6 mm³ last-good checkpoint.
  **Ordinary script failure has worker exit 0**, not 1: report schema 3 corrects
  the old synthetic assumption, requires `build_status:failed`, and rejects schemas
  1/2. No worker/image protocol changed.
- After finally/signal cleanup, independent container and PID/process-group
  inventories are checked against exact owned IDs. Durable journals must show
  acknowledged creates, absence and actual reaping; owners must have completed and
  been waited for. Missing journals/observers, pending launch/create, OOM, live groups
  or uncertain cleanup refuse. No broad cleanup or unrelated-container removal.

CAD ceilings: **2 GiB, 256 PIDs, one CPU, 120 CPU seconds**, 120-second ordinary
build wall, 90-second cancellation wall ceiling, 20-second timeout control. Ordinary
storage: 128 MiB/2048 inodes `/work`, 16 MiB/256 inodes `/tmp`. Small controls:
8 MiB/128 and 2 MiB/64. Read-only bounded input snapshots and bounded pre-exit framed
export are unchanged. Trusted packaging/build steps retain their separate documented
finite budgets. Heavy operations are serial; the event observer is not a second worker.

## Evidence and implementation

`scripts/macos_executor_check.py` owns the CLI and structural acceptance gate;
`scripts/macos_executor_live.py` collects actual CAD/publication/cancellation evidence.
`scripts/macos_milestone_smoke.py` calls the same stages. Reports retain raw bounded
command logs, source/build-input hashes, actual image/platform/installed identity,
per-operation requests, wire/output hashes, effective limits, typed terminal states,
Running/stop records, durable journals and independent inventories. The supervisor's
request IPC is private trusted host state, not an imported acceptance report.

First scoped pass: `dist/macos-executor-live-20261008-03/report.json`. Earlier failed
runs `...-01` and `...-02` remain intact: respectively the collector's opstore hash
prefix lookup bug and a correctly rejected roundtrip input name. Both were fixed
without relaxing containment or artifact gates. Final evidence is indexed in
[progress](macos-progress.md). Prior precheck-only/network/staging reports remain
historical; none supplies a present capability.

Host regressions include all mandatory evidence removal/null cases, old schema
rejection, OOM and order/type/cross-link failures, artifact confinement and publication
snapshots, durable unknown-create and cleanup faults, plus collector-specific actual
opstore hash format/canonicalization and missing/live ownership evidence tests.

## Remaining scope

[Supervision](macos-supervision.md) retains its honest abrupt-owner/daemon-death
limitations: unknown create settlement is a durable refusal, never an absence guess.
No machine-death guarantee, production release, cross-runtime/macOS certification,
full suite/pyright pass or independent security review is claimed here. Large CAD,
DFM and host import conversion are not newly certified. Next: separate secure ARM64
Mesa/EGL worker and **all** inspection/publication call sites, real selection masks
and kernel sections, `_mint_bundle`, authenticated native browser, independent
security/render reviews, then final fresh all-stage smoke.
