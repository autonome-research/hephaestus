# core — Design Contract (Stage 0B)

Normative for every implementation agent. The *semantic* contracts live in the
root docs — `script_contract.md` (entire part-script contract, §1–§9),
`architecture.md` (§2 engine-first, §3.1 executor, §3.2 kernel, §3.4 checks,
§3.5 project_store/lock order), `mission_plan.md` Stage 0B / Gate G0B,
`verification.md` (test categories + performance budgets),
`repo_conventions.md` (layout/quality bars). Read the sections for your area
IN FULL before coding. This file fixes only what those docs leave open:
package layout, internal API boundaries, and build decisions from Stage S.

## Non-negotiables

- **Engine-first**: `core/` imports no server, agent, Node, or network code.
  `heph build/check/lint` work with Node absent (gate: PATH without node).
- **opstore is imported, not reimplemented.** All WAL/lease/admission/GC
  machinery comes from `opstore`; `core/project_store` adds CAD policy only
  (lock order, authorization, projections, publication payload types).
- Quality bar: ruff clean, pyright strict (see relaxation note below), ≥90%
  line coverage on core/ (enforced at gate), hypothesis property tests for
  kernel services.
- Part scripts follow `script_contract.md` EXACTLY: injected namespace (§2),
  PARAMS (§3), `hc`/globals.py (§4), part output + tags + fingerprints (§5),
  CHECKS + approx (§6), addressing grammar (§7), BuildResult record (§8 —
  every field, including the full `error` object with `built_through`,
  `last_good`, `last_good_artifact_ref`, `hint`).

## Package layout

```
core/pyproject.toml          name hephaestus-core; import pkg hephaestus.core
core/src/hephaestus/         native namespace package (NO __init__.py at
core/src/hephaestus/core/      hephaestus/ level; core/ has __init__.py)
  errors.py                  typed errors: addressing_error (with candidates),
                             param_out_of_bounds, sandbox_denied,
                             unsafe_refused, validation_error kinds
                             syntax|contract|sandbox|evaluation, conflict,
                             incoherent_project_snapshot, check_set_drift,
                             invalid_check_generation
  types.py                   BuildResult/CheckReport/Warning/ErrorRecord
                             dataclasses mirroring script_contract §8 exactly;
                             to_json()/from_json(); JSON Schema committed at
                             core/schemas/build_result.schema.json
  params.py                  Param(default, min, max, doc="", step=None),
                             int/float inference, bounds validation naming the
                             parameter, PARAMS extraction, override merging
  addressing.py              §7 grammar: "part" | tag | label (#k/#* dedup in
                             tree order) | binding name (list bindings, append
                             order); cross-part "<part>/<label>"; ambiguity/
                             miss -> addressing_error listing candidates
  hashing.py                 sha256 helpers; canonical effective-param JSON;
                             consumed-hc projection hashing; toolchain hash
                             (python + build123d + OCP versions); reuse
                             opstore.hashing where possible
  kernel/
    metrics.py               metrics(shape): bbox, volume, area, solid/face/
                             edge counts, sealed (is-manifold), genus
    measure.py               interference(a,b) overlap volume; clearance(a,b)
                             min separation; distance(feat_a, feat_b);
                             mass(shape, density); section(shape, plane)
  executor/
    splitter.py              ast top-level statement split, source spans
    namespace.py             §2 injected namespace builder (build123d *, math,
                             Param/PARAMS/p, hc, part, tag, check/CHECKS/
                             approx); no open/__import__; attempt -> build
                             error; part API object (geometry, metadata
                             fields, feature())
    runner.py                statement-by-statement exec in worker subprocess;
                             checkpoint after each stmt (index, span, bound
                             names, lazy metrics — shape refs eager, full
                             metrics computed on failure/demand per mission
                             rule 4); error record per §8 incl. ±2-line frame
    worker.py                the sandboxed child: JSON on stdin -> executes ->
                             JSON result on stdout; writes BRep/artifacts only
                             under its rw out dir
    source_map.py            §3.1 three scopes: bindings (per-iteration with
                             call site), boolean results (statement-level,
                             never per-face), tags (solid, topo index,
                             statement) + serialized alongside build artifact
    tags.py                  tag() recompute-per-build; fingerprint.py:
                             §5.3 descriptors + EXACT thresholds (face 1.0mm/
                             5.0deg/2%; edge 1.0mm/2%; solid 1.0mm/2%;
                             rel delta abs(new-old)/max(abs(old),1e-9));
                             baseline = successful current artifact only;
                             warning kind tag_descriptor_changed, never an
                             identity claim
    globals_exec.py          globals.py execution (namespace minus part),
                             project PARAMS, derived constants, hc read-
                             tracking -> consumed-projection per part
    sandbox/
      base.py                ExecBackend protocol + capability probe result
      bwrap.py               secure backend: adapt spikes/sandbox argv (ro
                             project bind, tmpfs, --unshare-net/pid/user/ipc/
                             uts, --clearenv, rlimits, wall-clock kill); venv
                             + pinned runtime ro-bind; ONE rw bind: the fresh
                             per-build out dir; fail-closed probe
      unsafe.py              --unsafe-local-executor: plain subprocess, prints
                             warning, refused for registry content and under
                             serve (flag plumbed for future); never default
  checks/
    engine.py                CHECKS collection/run per build; failing check
                             fails the report, not the build; cross-part
                             checks/*.py; check-set generations + lock +
                             immutable bundle per architecture §3.4 (external_
                             import reconciliation, check_set_drift, invalid
                             generation fail-closed)
    facade.py                measurement facade m.* bound to built geometry
                             (m.interference/bbox/sealed/genus/mass/clearance/
                             distance/volume) resolving via addressing.py;
                             approx(value, abs=tol) comparator
  project_store/
    layout.py                project root: hephaestus.toml, globals.py,
                             parts/, checks/, .heph/ (store root = .heph/)
    locks.py                 canonical total order: project-config ->
                             check-set -> lexical part locks; advisory file
                             locks in .heph/locks/ + opstore leases
    store.py                 open/create project; part CRUD reads with
                             content_hash/snapshot registration; CAS writes
                             via opstore WAL (preimage journal under
                             .heph/journal/)
    projections.py           consumed-hc dependency projections; audit
                             revisions; stale-part marking (exactly the
                             consumers whose names/values changed); coherent
                             project-snapshot manifests;
                             incoherent_project_snapshot rejection
    publication.py           typed build/check/synthetic-export publication
                             over opstore (bundle install + current-pointer
                             CAS under project+part locks; snapshot freeze;
                             revalidate hashes before publish; failed/preview/
                             raced never current, never clear stale)
  cli.py                     heph entrypoint: build [--param k=v] [--stale]
                             [--json], check, lint; exit codes 0/1; --json
                             emits the exact BuildResult JSON
  lint.py                    §9: geometry unreachable from part.geometry,
                             unlabeled multi-solid compounds, params never
                             read, tags never referenced, missing description/
                             process, PARAMS shadowing an hc name (error)
core/schemas/build_result.schema.json
core/tests/                  unit tests per module (test_<module>.py)
tests/stage0b/               gate tests (see Gate section)
corpus/public_fixtures/      independently authored clean-room projects
```

## Build decisions (binding, from Stage S evidence)

- Worker protocol: parent sends {script, params, globals_source, project_params,
  mode} JSON via stdin; worker streams nothing, returns one result JSON on
  stdout (checkpoints, metrics, error, source map, tag fingerprints, artifact
  file names). Artifacts (BRep of final compound; BRep of last-good compound on
  failure) written under the per-build out dir; parent moves them into opstore
  CAS blobs and builds refs `artifact:build:sha256:...` /
  `artifact:build-checkpoint:sha256:...`.
- Sandbox: bwrap argv per spikes/sandbox/RESULTS.md; the worker venv
  (sys.prefix) and the interpreter are ro-bound; project dir ro-bound; out dir
  rw; network/pid/user/ipc/uts unshared; clearenv + minimal PATH; rlimits
  (cpu, as, nproc) + parent wall-clock kill. Capability probe runs once per
  store and is cached; no probe pass -> secure builds fail closed with
  sandbox_unavailable (unsafe backend only via explicit flag).
- Determinism: metrics stable to 1e-6 mm across rebuilds (contract test);
  toolchain hash includes python/build123d/OCP exact versions.
- Serialization: shapes persist as BRep (OCP BRepTools). STEP/render are later
  stages.
- `current` publication: revalidate script/part-param/toolchain/consumed-hc
  hashes under reacquired locks before CAS-ing the current pointer (architecture
  §3.5); transient-param builds are previews (current=false, 7d retention
  class); failed builds publish checkpoint evidence only.
- pyright: strict for all pure modules. For modules that touch untyped
  build123d/OCP surfaces (kernel/, executor/namespace.py, worker.py), per-file
  overrides may disable reportUnknownMemberType/reportUnknownVariableType/
  reportUnknownArgumentType ONLY — everything else stays strict. Declare the
  override list in root pyproject [tool.pyright] executionEnvironments.

## Fixtures (corpus/public_fixtures/ — independently authored, clean-room)

- `assembly/`: globals.py (project PARAMS e.g. sheet_t, clearance + derived
  constants), parts/primary.py (multi-solid labeled compound, tags incl.
  duplicate labels for #k dedup, PARAMS, CHECKS incl. approx), parts/bracket.py
  (consumes hc names; interference/clearance cross-part check under checks/),
  a starter hephaestus.toml. Used by most gate tests; `heph build
  corpus/public_fixtures/assembly/parts/primary.py --json` must validate
  against the BuildResult schema with Node absent.
- `failure_fillet/`: parts/broken.py with an oversized fillet at a KNOWN line;
  drives every §8 error-record field assertion (line/col/type/frame/
  built_through/last_good metrics vs independently computed values/
  last_good_artifact_ref/hint).
- `fingerprint/`: fixture pair driving tag-descriptor tests: threshold-crossing
  tread_top-style displacement warns with measured deltas + baseline ref; an
  equivalent no-op refactor does not; selector-swap (symmetric neighbor)
  documents the false-negative limit without identity claims.

## Gate G0B (tests/stage0b/) — every clause of mission_plan G0B becomes a test

failure fixture full-field reproduction incl. mutation tests (corrupt each
field -> assertion bites); param bounds at part+project scope with stale
propagation from project-param/globals.py edits; two-build determinism;
sandbox escape denial (reuse spike probe patterns: introspection-based fs,
symlink, process, network) + unsafe-mode refusal for registry paths; source-map
resolution for all solids/tags at §3.1 scopes; addressing grammar incl. #k/#*
and candidate-listing errors; fingerprint thresholds/baseline/interleaved
current-preview-failed-raced ordering; performance budgets (public-fixture
scaled: full build ≤30s, incremental rebuild ≤ changed-statement×1.5+2s,
measure interference across assembly pairs ≤5s); adapter integration (lock
order incl. no-inversion race test, selective projections, coherent manifests,
authorization, exact attempted snapshots, external-drift conflict, typed crash
recovery at every publication boundary via OPSTORE_CRASH_POINT, quota/
retention, immutable check-bundle provenance, stale/failed/preview publication
rejection, opstore-imported-not-reimplemented import-graph test); no-node test
(PATH stripped of node -> heph build --json exits 0 and validates against
core/schemas/build_result.schema.json).
