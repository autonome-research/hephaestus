<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# Experimental OCI execution identity

Implemented and now exercised through [real scoped executor acceptance](macos-executor-stage.md):
fresh manifest-4 image/storage, CAD, BREP re-read, actual publication/revalidation
and freshness. **Full milestone acceptance remains false.** Profile **5**, run
protocol **3**, transfer **1** are unchanged. Old manifests (including manifest 3
with otherwise valid storage evidence) refuse. Rebuild/rerun when image sources
change. [Progress and evidence](macos-progress.md) identify the tested sources.

## Authority and measurement

The caller supplies a trusted immutable image to an explicitly constructed
`OciBackend`. An arbitrary image does not become trusted by printing this schema.
The existing daemon inspection verifies RepoDigest, config ID, Linux platform,
fixed entrypoint, environment and other image restrictions. Each created container
must attest that same config ID before starting. No production discovery or
`PRODUCTION_OCI_IMAGE` change is made.

The fixed launcher's separate, bounded **manifest invocation** runs no user script
and accepts no inventory input. It measures:

- installed executor and opstore source/data files, by pathname and actual bytes
  (not git status or a worker's claimed hash); generated pycache is excluded;
- Python version and the installed distribution name/version/METADATA inventory,
  including build123d, OCP and the executor/opstore packages;
- a closed identity schema version, with bounded package/source inventories.

The host binds that inventory to the daemon-attested image reference, config ID
and platform. This immutable `ExecutionIdentity` belongs to the backend, not to
workload result JSON. The identity is usable only after the full probe passes;
changed image/platform or poisoned ownership/cleanup state refuses use. No host
CAD packages are needed to construct, assemble, publish or compare OCI identity.
The image digest additionally binds native libraries, interpreter binaries and
all other image content not individually enumerated in the inventory.

This is an execution-environment identity, **not proof of geometric correctness**,
source-map truth, kernel acceptance or cancellation. Those gates remain separate.
The existing artifact schema, byte/hash checks, terminal/OOM checks, transfer
bounds and cleanup refusal still apply.

## Hash and store contract

`input_hashes.toolchain` is the existing invalidation key; no public BuildResult
schema is widened. On OCI it hashes the canonical versioned identity projection:
image **digest** (not repository location), config ID, platform and runtime
inventory. Identical immutable image aliases therefore compare equal; an image,
platform, installed source, package metadata or version change changes the hash.
The full daemon-attested reference is retained as audit data.

The runner captures backend identity before execution, requires the same identity
on the host `ExecOutcome`, and rechecks it after execution. It never accepts a
script-supplied fingerprint. `assemble_build(..., execution_identity=...)` is a
trusted host API, not a worker field. Native callers retain the original
`toolchain_hash()` semantics and content hashes.

The reserved metadata key `hephaestus.execution_identity` contains the canonical
identity JSON string. Assembly discards any script value at that key and writes
only the host-owned record. `UnpublishedBuild` also retains the typed identity.
Publication validates both against `input_hashes.toolchain` before installing
artifacts. The metadata is persisted in ordinary result records and build bundles,
including failed/preview/raced evidence; it survives worker teardown/store reopen.
Malformed or hash-inconsistent identity refuses; missing identity cannot pass OCI
freshness/current publication. Stored metadata never selects a live backend.

`Publisher(..., backend=backend)` is the supported injection seam: use the **same
backend** as `run_build`. Publication revalidation and lock-free freshness call
one comparison against that backend's current identity. Wrong/unavailable backend,
native-to-OCI or OCI-to-native changes report a toolchain mismatch; neither stored
hashes nor host packages are substituted. Native records without this metadata
remain compatible with native publishers. `current` remains publication state,
never a freshness verdict. Missing/corrupt identity cannot promote an old record.

`CadOps`' publisher factory, engine CLI build publication and golden-fixture build
publication pass their execution backend. Publisher instances used only for
historical reads need no backend. This does not yet make the whole workspace
import/execution/render path host-CAD-free; renderer and import-conversion wiring
remain later work. Native-only solver/toolchain computations are not relabelled
as OCI execution.

BREP `artifact_ref` continues to identify **geometry bytes**, not execution inputs.
An identical BREP may therefore be shared across executors while its immutable
build bundles differ. The existing part+artifact bundle pointer/current-bundle
precedence is unchanged. Identity is inline in existing records: no new GC roots,
pins, widened retention, artifact kinds, WAL or pointer semantics. Previews remain
7-day evidence (without downgrading already-retained identical blobs); failures and
races never replace current state or clear stale markers. Replays retain their
original immutable identity.

## Host coverage and remaining gates

`core/tests/test_execution_identity.py` uses explicit synthetic backends and
native-hash dependency injection, with no global monkeypatches or installed CAD
packages. It covers source/package changes, schema/version rejection, wrong or
missing outcome/record identity, stale/unavailable identity, cross-backend
publication/freshness, immutable bundle changes, native compatibility, script
forgery, preview/failure/replay/GC and the CadOps publisher factory. Installed-source
fixtures are temporary directories, not packages installed into the host runtime.
`tests/test_macos_staging.py` also exercises real OCI transfer/runner/publication
code against a synthetic daemon; it is not live execution proof.

The staging collector now records the canonical identity and its toolchain hash
from a passing real backend. Executor evidence schema 2 uses that same identity
hash rather than a second report-only fingerprint; schema 1 refuses. The collector
still cannot claim CAD acceptance. The executor precheck remains closed on durable
external create/cancellation supervision; no user CAD should run before that phase.
A fresh immutable image build, manifest measurement and storage controls are
required, followed by supervised CAD, render, browser and independent reviews.
