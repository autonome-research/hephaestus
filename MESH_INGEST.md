<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# 14 — Mesh and scan ingest (Stage 12)

**Numbering.** The root normative sequence runs `00 architecture` … `12
INTERFACE`. Five capability drafts were authored in parallel on 2026-08-28 and
four of them self-assigned document `13`; three self-assigned Stage `11`. Two
specs cannot both be Stage 11: mission rule 1 makes a gate a *command*
(`mission_plan.md`), and two documents issuing `uv run pytest tests/stage11a -q`
over different suites makes both unsatisfiable. The maintainer resolved this by
`docs/frontier-staging-proposal.md` decision D4 option (a) — number equals the
recommended execution order, allocated once across all five while every one was
still a draft and no gate had ever run: `13 PARTS_STORE` (Stage 11), `14
MESH_INGEST` (Stage 12), `15 SOLVER` (Stage 13), `16 CAM` (Stage 14), `17
PHYSICS` (Stage 15). This document therefore holds document number `14`, stage
`12`, the gate names `G12A`/`G12B`/`G12C` and the suites `tests/stage12{a,b,c}`.
No draft may renumber unilaterally once any of the five is normative; a
reordering is an amendment that moves every affected header together. Every
cross-document clause below is written **relative** to whatever the predecessor
stage leaves standing (§Amendment manifest, G12C.42), never against an absolute
count or an absolute line of text, so this spec stays correct whichever order
the five land in.

**Status: DRAFT.** Not normative. It becomes normative only after (a) an
adversarial review against the codebase on the `KINEMATICS.md` precedent
(`KINEMATICS.md:10-12` — 40 agents, 31 confirmed findings folded in) and (b) a
dated `mission_plan.md` Stage 12 amendment carrying the G12A/G12B/G12C gate
summaries and citing this document, on the Stage 2V / Stage 8 / Stage 9 / Stage
10 amendment pattern. Mission rule 5 (`mission_plan.md:815-817`) requires that
amendment: this is new capability, not a widening of G8A.

**Every wall-clock and volume figure quoted below was measured in the repository
venv** (`.venv`, Python 3.13.12, build123d 0.11.1, OCCT 7.9.3 per
`spikes/REPORT.md:10`, trimesh 4.12.2, numpy 2.5.1), **not in the pinned CI
image** (`repo_conventions.md:186-194`). Mission rule 4
(`mission_plan.md:809-814`) makes performance a gate, so no gate clause below
cites a second-value until it has been re-measured in the image. Orders of
magnitude are load-bearing; exact seconds are not yet evidence.

## Amendment manifest

Every existing normative document this spec changes, and exactly what changes.
Each amendment lands with the sub-stage whose machinery ships it — amending a
document before its machinery exists is doc drift (`KINEMATICS.md:25-29`).

**Every row is relative, not absolute.** `PHYSICS.md` is sequenced ahead of this
document (header), and it edits some of the same files. A row that quoted a line
number or a count would be wrong the moment the predecessor stage landed, so each
row below names the **sentence or the pin as it stands when this stage opens**
and states what the predecessor may already have done to it. Line citations are
where the text lives *today* and are a locator, never the amendment's subject.

| Document | Change | Lands |
|---|---|---|
| `mission_plan.md` | New gated **Stage 12** heading, dated, carrying the G12A/G12B/G12C summaries and citing this file. Rule 5's deferred list is untouched — mesh ingest was never on it, which is precisely why it needs a new stage rather than a waiver. | 12A |
| `INGEST.md` §1 | The `Formats` bullet (`INGEST.md:52-53`) is extended: STEP remains the only format producing a **B-rep** import; §1 below adds two further import terms producing **mesh assets**, which are a different kind, not a further STEP-like format. The "Identical bytes ⇒ identical geometry" sentence (`INGEST.md:44-45`) is scoped to STEP and given its mesh counterpart in §8. The provenance bullet's `tag()` sentence (`INGEST.md:46-51`) is scoped to B-rep imports: §2.4 forbids tagging mesh topology. | 12A |
| `INGEST.md` §3 | "No feature recognition" (`INGEST.md:88`) is restated, strengthened, and extended to surface reconstruction (§4.4). | 12A |
| `COMPARE.md` §4 | The sentence "No mesh-based comparison path (sampling is on the BRep); no point-cloud imports" (`COMPARE.md:82-83`) is replaced by the scoped rule of §6: a **scan-target** comparison path exists, it is a different record type from `SolidDiff`, it reports no `iou`, and `align="principal"` is refused against it. `compare_solids`' own contract is byte-for-byte unchanged. **Predecessor interaction:** `PHYSICS.md` declares this sentence an *explicit non-amendment* and leaves it standing verbatim (`PHYSICS.md:54-57` — "an FEA mesh is a solver input, never a comparison operand"), so this stage edits the sentence exactly as quoted whether or not Stage 11 has landed. If a future draft does rewrite it first, this row edits **the sentence as it then stands**, and the FEA-mesh exclusion is preserved in the replacement text. | 12C |
| `COMPARE.md` §1 | The alignment rule (`COMPARE.md:36-38`) gains a third declared mode, `declared`, for an operator-supplied rigid transform; `as_posed`/`principal` semantics are unchanged. | 12C |
| `script_contract.md` §2 | **Five** new injected names in the §2 list (`script_contract.md:38-42`), landing in two waves because the manifest's own rule is that an amendment lands with the machinery that ships it. **12A:** `import_mesh(name, units=…)` and `import_point_cloud(name, units=…)`. **12B:** `mesh_to_solid(asset, intent=…)` (§4.3), `section_polylines(asset, plane, …)` (§5.3) and `loft_sections(polylines, …)` (§5.2, the section→B-spline→loft helper). The "Nothing else" rule (`script_contract.md:44-45`) is unchanged and is precisely why all five must be listed: `__import__` is absent, so a part script has **no** route to `GeomAPI_PointsToBSpline`, `BRepBuilderAPI_Sewing`, or any other OCP name, and a term this spec uses in an example that is not on this list would be unreachable. G12B.29 asserts the injected set is exactly this list. | 12A + 12B |
| `script_contract.md` §6 | `m.scan_diff(part, "scan:<relpath>", align=…)` on the **part-scope** facade only, by the same freeze argument that restricts `import:` targets to part scripts (`script_contract.md:228-236`). | 12C |
| `tool_schema.md` | One new tool, `compare_to_scan`, plus a `mesh` kind in `list_references`-adjacent reads; the `compare_solids` declaration (`tool_schema.md:559-600`) is **not** edited — a `scan:` target is refused there by name (§6.5). | 12C |
| `VALIDATION.md` §1 | A new corpus family `scan-*` is its own split with its own coverage constant and its own threshold, baselined on its own first measurement, neither compared against nor averaged into v1/v2 (the rule as G9C restates it, `KINEMATICS.md:393-398`). | 12C |
| `VALIDATION.md` §5 | The termination reviewer receives mesh-quality facts and the scan-deviation record for every part whose script imports a mesh (§7.4). | 12C |
| `verification.md` | Two additions: the Tier 1 kernel-service list gains mesh quality against hand-computable fixtures, and the golden-provenance rule (`verification.md:66-73`) gains an **(container image, OCCT version)** pair for the sew-derived goldens of §4. **Predecessor interaction, stated because the two drafts touch the same four lines:** today that rule reads *(container image, hephaestus renderer version)* (`verification.md:71-73`); `PHYSICS.md` amends the same block so the image "also pins the mesher and solver" (`PHYSICS.md:52`). This stage therefore **adds a pair to whatever list stands**, and does not rewrite the block: if Stage 11 landed first, OCCT joins the renderer/mesher/solver pins already there; if it did not, OCCT joins the renderer pin alone. G12B.32 asserts the sew goldens carry an OCCT-version sidecar and refuse a mismatched pair, which is true under either predecessor state. | 12B |
| `repo_conventions.md` | A new spike disposition entry beside the STEP one (`repo_conventions.md:180-181`): mesh files are hashed **raw**, and geometric identity rides a second, separately named canonical hash (§1.4). | 12A |
| `core/pyproject.toml` | `scipy` becomes an explicit pinned dependency (§6.3). It is already resolved in the environment as a `pyrender 0.1.45` requirement (measured), so this pins what is installed rather than admitting a new wheel — mission rule 7 (`mission_plan.md:823-827`). `rtree` and `lxml` are measured **absent** and stay absent (§1.2, §6.3). | 12C |

## Design premise

`INGEST.md`'s premise — "real work starts from something that already exists"
(`INGEST.md:10-13`) — is currently true only for work that starts from CAD. A
prosthetic socket starts from a **limb**, and the artifact a limb produces is a
scan: a triangle mesh or a point cloud, with no parameters, no design intent, no
exact surfaces, and no units. Today `import_step` is the only door into the
harness (`script_contract.md:38-42`), and `COMPARE.md:82-83` closes the mesh door
explicitly. Stage 12 opens it — and it is the one frontier capability that lands
*inside* the existing contract rather than against it, because `INGEST.md` §1's
shape ("take this file, apply these operations, the script remains the source of
truth") needs no modification to hold for a scan. What does need designing is
everything downstream: a mesh has no exact topology, so almost every fact the
harness knows how to state about a solid becomes a *different, weaker* fact when
the solid came from triangles, and the entire difficulty of this spec is
refusing to let those two vocabularies share a field name.

## 0. What mesh and scan ingest IS, and what it is NOT

Mesh ingest in Hephaestus is **an immutable measurement target admitted as a
build input**: a content-addressed file under `imports/`, resolved and
normalized by the harness outside the sandbox, exposed to a part script as a
value with a closed set of stated facts, and usable as the target of a
comparison. It is:

- a build input on exactly the `INGEST.md` §1 terms — frozen, hashed, staged
  read-only, threaded through revalidation and staleness (`INGEST.md:40-45`,
  `core/src/hephaestus/core/executor/runner.py:176-178`);
- a **measurement target** for a part the script authored (§6);
- in 12B, and only under the refusal gate of §4.3, a B-rep operand.

It is **not**:

- **A design source.** No feature recognition (`INGEST.md:25-26`), and — the
  strictly stronger statement a mesh forces — **no surface reconstruction**: no
  inference of a cylinder, plane, or NURBS patch from triangles or points. There
  is no machinery for it in the pinned stack (§4.4) and this spec does not add
  any.
- **A parametric model.** A mesh has no parameters. A script that wants a
  parametric socket authors one and *measures it against* the scan (§5.2).
- **A carrier of stable topology identity.** Triangle indices are an artifact of
  the file's triangle order; §1.4's canonicalization deliberately destroys that
  order. `tag()` on mesh topology is refused (§2.4).
- **A clinical claim.** Nothing here evidences that a socket fits a residual
  limb, distributes load, or is safe to wear. Fit-to-scan is a *geometric*
  distance at named samples; rectification is clinical judgement the harness
  cannot verify; structural adequacy is FEA, deferred by name by mission rule 5
  (`mission_plan.md:815-817`). §11.3 states the refusal in contract form.
- **A second geometry kernel.** `geom.mesh` (§2.1) parses, normalizes and
  measures triangle arrays. It performs no mesh booleans, no remeshing, no
  reconstruction. Introducing a mesh-native solid modeller is the mission rule 6
  question (`mission_plan.md:818-822`) and §11.1 refuses it by name.

## 1. Formats, admission, hashing, normalization

### 1.1 The import term

```python
scan = import_mesh("limb-l.stl", units="mm")        # a statement like any other
cloud = import_point_cloud("landmarks.xyz", units="mm")
```

Both are `INGEST.md` §1 terms: harness-resolved, string-literal path relative to
`imports/`, never script I/O. The confinement walk's **properties** are reused
unchanged — `read_import` (`core/src/hephaestus/core/executor/imports.py:258-341`)
opens one directory descriptor per component with `O_NOFOLLOW` and `fstat`s
`S_ISREG`; it reads bytes and knows nothing about STEP.

`read_import` does, however, gain exactly one thing, and this spec states it
rather than claiming the function is untouched: **an `fstat`-size refusal**
(§1.6). It cannot live anywhere else. `read_import` ends in a single unbounded
`stream.read()` (`imports.py:326-327`) and it is the freeze path's only reader;
its caller `PartStore.read_import`
(`core/src/hephaestus/core/project_store/store.py:235-254`) hashes the returned
bytes and writes them into the opstore blob store on the very next line. A
ceiling checked "before the parser" is therefore checked *after* a multi-gigabyte
OBJ is already resident in the parent and already in CAS — which is not a
ceiling, because the resource §1.6 protects is exactly that memory and that
store. The refusal goes on the descriptor the walk already holds, immediately
after the existing `info = os.fstat(handle)` / `S_ISREG` check
(`imports.py:320-327`): if `info.st_size` exceeds the ceiling for the
declaration's kind, refuse `mesh_import_too_large` and never call `read()`.
Because it reads the size off the already-open, `O_NOFOLLOW`-opened descriptor
rather than re-`stat`ing the path, there is no TOCTOU window and the confinement
property is unchanged. The ceiling is a per-kind argument supplied by the caller
(`None` for STEP), so no existing STEP behaviour moves.

Three grammar and plumbing changes are needed, and they are the only ones:

- `_is_import_call` (`imports.py:118-123`) tests `node.func.id == import_step_name`
  against a single name. It becomes a test against a closed set
  `{import_step, import_mesh, import_point_cloud}`, and `ImportDeclaration`
  (`imports.py:108-116`) gains a `kind` field, because the staged form differs
  per kind (§1.5).
- `declared_imports` (`imports.py:143-149`) today accepts **exactly one
  positional string literal and no keywords**; anything else — including a
  keyword — is `DynamicImportPathError`. The mesh terms require the `units`
  keyword, whose value must itself be a string literal from the closed set of
  §1.3. The static-literal rule is not relaxed: a computed path or a computed
  unit is still `DynamicImportPathError` at the offending line, for the same
  reason (`imports.py:151-158`) — a value the freeze cannot read cannot be
  frozen.
- **The declaration's `kind` and `units` must reach the staging code**, and
  today nothing carries them there. `BuildRequest.imports` is a
  `Mapping[str, bytes]` (`runner.py:116`, mirrored at `publication.py:109`), and
  the freeze that fills it iterates *paths only* — `_freeze_imports` walks
  `static_import_paths(script)` and stores `snapshot.data` per path
  (`publication.py:227-238`). A declared unit that stops at the AST is a
  declared unit the geometry never sees. `imports` therefore becomes a mapping
  to a per-path record `ImportPayload(bytes, kind, units)`; `_freeze_imports`
  threads the `ImportDeclaration` rather than its `path` string;
  `import_hashes` (`runner.py:176-178`) hashes `payload.bytes` and is otherwise
  unchanged, so `input_hashes.imports` stays byte-for-byte what it is today; and
  `stage_request_imports` (`runner.py:181-202`) passes `kind` and `units` into
  `stage_import`. §1.5 explains why the staged *identity* depends on it, and
  §12 items 6 and 11 carry the work.

### 1.2 Admitted formats (12A closed set)

| Extension | Kind | Reader | Admitted in 12A |
|---|---|---|---|
| `.stl` (binary, ASCII) | mesh | trimesh from `BytesIO` | yes |
| `.ply` (binary, ASCII) | mesh | trimesh from `BytesIO` | yes |
| `.obj` | mesh | trimesh from `BytesIO` | yes |
| `.off` | mesh | trimesh from `BytesIO` | yes |
| `.xyz` | point cloud | trimesh from `BytesIO` | yes |
| `.glb` / `.gltf` | scene | — | **refused** `mesh_format_unsupported` |
| `.3mf` | mesh | — | **refused** `mesh_format_unsupported` |

The reader is **trimesh, in the parent, over the bytes already hashed**. This is
not a new dependency: `trimesh>=4.12` is already a declared dependency of
`hephaestus-core` (`core/pyproject.toml:16`) and is already used by the render
path (`core/src/hephaestus/core/render/tessellate.py:202-210`). It is also the
only option that can honour `step_io.py:19-24`'s standing rule — *the bytes the
caller already hashed are the bytes parsed*. OCCT cannot: the OCP bindings expose
`RWStl` and `StlAPI` and **no `RWObj` or `RWPly` module at all** (measured:
enumerating `OCP.__path__` yields 316 modules, of which the `RW*` set is
`RWGltf, RWMesh, RWStepAP203, RWStepAP214, RWStepAP242, RWStepBasic,
RWStepDimTol, RWStepElement, RWStepFEA, RWStepGeom, RWStepRepr, RWStepShape,
RWStepVisual, RWStl`), there is no 3MF reader, and `RWStl.ReadFile_s` takes a
path — so an OCCT-side ASCII STL read would be a second filesystem read between
the hash and the geometry, which `step_io.py:19-24` exists to forbid.

The two refusals are refusals of *substance*, not of effort:

- **glTF/GLB is a scene, not a mesh.** Measured: a single-mesh GLB round-trips
  through `trimesh.load(..., file_type="glb")` as a `trimesh.Scene`, not a
  `Trimesh`. Flattening a scene means choosing a node traversal order and
  concatenating transformed meshes, which is a normalization with real semantic
  content. It gets its own amendment or it does not ship.
- **3MF costs a dependency.** trimesh's 3MF loader is a soft dependency on
  `lxml`, and `lxml` is measured **absent** from the environment. Admitting 3MF
  is a rule 7 dependency amendment (`mission_plan.md:823-827`), and it is also a
  zip container — see the ceiling rule in §1.6.

Both are `mesh_format_unsupported`, naming the extension and the amendment
required. Admission is by **extension and sniffed magic**, and a mismatch
(`.stl` whose bytes are a PLY header) is `mesh_format_mismatch`, never a
silently-honoured sniff.

### 1.3 Units cannot be inferred, so they must be declared

STL, OBJ, PLY and XYZ carry **no unit**. The engine is millimetres throughout.
There is exactly one honest response, and it is a named refusal:

- `units` is a required keyword whose value is a string literal from the closed
  set `{"mm", "cm", "m", "in"}`, with exact scale factors `1`, `10`, `1000`,
  `25.4`.
- Omitting it is `mesh_units_undeclared` at the statement. A unit outside the set
  is `mesh_units_unsupported`.
- **The unit is never inferred from the bounding box.** "This is 300 units across
  so it is probably millimetres" is a guess dressed as a measurement, and a limb
  scan is exactly the size where the guess is plausible and wrong.
- A format that later carries its own unit (3MF) and disagrees with the declared
  one is `mesh_units_conflict`, carrying both — never silently preferring either.

The declared unit is part of the staged input and is recorded in the asset
record; a changed unit is a changed build even when the file bytes are identical,
because the geometry the build saw is different.

### 1.4 Hashing: two hashes, and what each one means

`INGEST.md`'s content-addressing rule is kept exactly: `import_hashes`
(`runner.py:176-178`) is `{path: sha256(raw bytes)}` and
`InputHashes.imports` (`core/src/hephaestus/core/types.py:85-90`) is a
`Mapping[str, str]`. Freeze (`core/src/hephaestus/core/project_store/publication.py:229-238`),
revalidation, staleness (`publication.py:240-250`), and lost-response replay ride
this unchanged. **Nothing is normalized before hashing an input.**

The FILE_NAME analogy in the framing of this work needs a correction, because the
correction is the design. The `FILE_NAME` normalizer
(`spikes/cad_kernel/box_build.py:34-45`, disposition recorded at
`repo_conventions.md:180-181`) is an **export-determinism** device: it exists so
two *exports* of the same shape compare equal. Import hashing normalizes
nothing — `runner.py:176-178` hashes raw bytes, deliberately, because a build
input's identity must be the file's identity. Meshes have exactly the same class
of volatile header (an STL `solid <name>` line, an OBJ comment banner, a PLY
`comment` record, a re-export that renumbers vertices), so the same *problem*
appears — but the answer is **not** to normalize the input hash. The answer is a
second hash:

- **`input_hashes.imports[path]`** — sha256 of the raw file bytes. Build
  identity. A re-exported scan with a new banner comment is a **new build**. This
  is conservative and correct: the harness cannot know the re-export is
  geometrically identical until it has parsed it, and the freeze runs before the
  parse.
- **`mesh_canonical_hash`** — sha256 of the canonical blob of §1.5. Geometry
  identity. Recorded on the asset record and in the build's mesh section. Two
  builds whose `input_hashes` differ but whose `mesh_canonical_hash` agrees can
  **say so**: "the file changed, the geometry did not."

The one-way rule is absolute: `mesh_canonical_hash` never substitutes for the
input hash in freeze, revalidation or staleness. It is an explanatory fact, not
an invalidation key. Reversing that would let a normalizer decide what counts as
a changed build, which is exactly the authority `INGEST.md` §1 keeps in the raw
bytes.

### 1.5 Canonicalization: the staged form

Staging converts once, in the parent, outside the sandbox (`imports.py:353-379`,
`runner.py:181-202`). For STEP that conversion is `read_step_bytes` →
`shape_to_brep` (`geom/step_io.py:117-129`). For a mesh it is the following
pipeline, whose every step is named because every step is a decision:

1. **Parse with `process=False`.** trimesh's default `process=True` merges and
   **reorders** vertices; the render path already pins `process=False` for
   exactly this reason (`tessellate.py:210`, determinism contract at
   `tessellate.py:14-18`). Measured on a 320-triangle STL: `process=False` gives
   960 vertices, `process=True` gives 162 — the same 320 triangles, a different
   array. Both were stable across repeats in-process; neither is a *documented*
   function of the input, which is why the harness does its own welding below
   rather than delegating the canonical form to a library default.
2. **Reject non-finite coordinates** — `mesh_not_finite`, naming the first
   offending index. NaN in a scan is common and silently poisons every downstream
   mean.
3. **Scale by the declared unit factor** (§1.3), in float64.
4. **Weld** vertices within `MESH_WELD_TOL_MM` (default `1e-6`) by quantizing
   each coordinate to `round(x / MESH_WELD_TOL_MM)` and merging equal keys. Not
   `trimesh.merge_vertices`: the key function must be documented here, not
   inherited.
5. **Drop degenerate triangles** — zero area within `MESH_DEGENERATE_AREA_MM2`,
   and triangles whose three welded indices are not distinct. The dropped count
   is **recorded on the quality record** (§3), never silently absorbed.
6. **Canonically order.** Vertices sorted by their quantized `(x, y, z)` key
   lexicographically; triangles re-indexed, each rotated so its smallest index
   comes first (winding preserved, orientation untouched), then sorted
   lexicographically.
7. **Serialize** to the canonical blob: a fixed 32-byte header (magic, format
   version, vertex count, triangle count, unit factor as float64), then
   little-endian float64 vertices, then little-endian int32 triangles.
   `mesh_canonical_hash = sha256(blob)`.

Step 6 is the honest cost of step 1: canonical order is a documented function of
the geometry, and the file's own triangle order is gone. §2.4 draws the
consequence.

A point cloud is staged by steps 1-3 and 6-7 with no welding, no triangles, and
its own magic; §2.3 says what it is.

#### 1.5.1 The staged identity must include the declared unit

`staged_filename` (`imports.py:348-350`) is today a pure function of the content
hash — `f"{content_hash[:32]}.brep"` — and `stage_import` returns the existing
file when that name exists (`imports.py:362-366`). Step 3 above bakes the unit
scale **into** the canonical blob. Those two facts are incompatible: two
byte-identical files declared `units="mm"` and `units="in"` would hash to one
staged name, the second declaration would silently receive the first's staged
geometry, and the build would be wrong by a factor of 25.4 with nothing
recording it. That is precisely the silent normalization this document exists to
forbid, and it is not a hypothetical — it is what the unmodified function does.

So the unit is part of the staged identity, stated as a formula rather than a
property:

```
staged_filename(content_hash, kind="step")  = sha256_hex(content_hash)[:32] + ".brep"   # unchanged behaviour
staged_filename(content_hash, kind=mesh|points, units=u)
    = sha256_hex(content_hash + "\x00" + u)[:32] + (".hmesh" | ".hpts")
```

For STEP the name is what it is today (the content hash's own prefix), so no
staged STEP artifact moves. For a mesh the name is a hash *of* the content hash
and the declared unit, joined by a NUL that no unit token can contain, so the
reuse property becomes literally true as stated: **same bytes plus same declared
unit ⇒ same staged file; same bytes at a different declared unit ⇒ a different
staged file.** `stage_import` (`imports.py:353-379`) dispatches on
`ImportDeclaration.kind` and receives `units` through the §1.1 plumbing.
G12A.8 is the test that fails against the unmodified code.

#### 1.5.2 The blob is geometry; the facts ride a sidecar

Canonicalization happens in the **parent**; the `MeshAsset` is built in the
**worker**, from the staged file, and the staged file is the worker's only
channel to the parent. Two of the §3 quality fields — `welded_vertex_pairs` and
`degenerate_triangles_dropped` — are *differences between the as-read mesh and
the canonical mesh*, and the canonical blob is post-weld and post-drop. A
deserializer inside the sandbox cannot recover them from it, by construction.
Specifying a record whose fields cannot be computed where they are built is not
a tightening, it is an unimplementable clause, so staging emits **two files**:

- **`<name>.hmesh`** — the canonical blob of step 7. This is the geometry and
  the **identity**: `mesh_canonical_hash = sha256(blob)` is taken over this file
  and nothing else.
- **`<name>.hmesh.facts`** — a JSON sidecar, staged read-only beside it, written
  by the parent in the same pass, carrying exactly the facts the canonicalizer
  observed and destroyed: the full `MeshQuality` record (§3),
  `vertex_count_as_read` (the `process=False` vertex count of the parsed file,
  before step 4), and the post-scale bbox. Its key order is sorted and its
  floats are `repr`-round-trippable, so it is itself byte-reproducible — but it
  is **explicitly not part of `mesh_canonical_hash`**, and G12A.9 asserts that
  editing the sidecar leaves the hash unchanged. The hash names geometry; the
  sidecar reports history.

A point cloud stages `.hpts` plus `.hpts.facts` on the same rule. The sidecar is
never read by anything but the worker's asset constructor, is never a script
input, and is regenerated from the bytes on every staging — it is a cache of the
parent's own computation, not a second source of truth.

### 1.6 Ceilings, refused before the parser runs

`INGEST.md` has no size cap because a STEP too large simply fails to parse. That
reasoning does not transfer: an OBJ can be gigabytes of ASCII, an XYZ can be 10⁸
points, a 3MF is a zip container. Three ceilings, each named with **the exact
place it fires**, because "before the parser" was not a strong enough
specification — a refusal that runs after the file is in memory and in CAS has
already spent the resource it was protecting:

- `MESH_MAX_BYTES` — enforced **inside the confinement walk**, off
  `os.fstat(handle).st_size` on the already-open descriptor, before
  `stream.read()` (`imports.py:320-327`, the change §1.1 admits). Nothing is
  read, nothing is hashed, and nothing is written to the opstore blob store
  (`store.py:249`). G12A.20 asserts the blob store is untouched after this
  refusal.
- `MESH_MAX_TRIANGLES` / `MESH_MAX_POINTS` — checked in the parent after the
  bytes are in hand but **before** the bytes reach trimesh: from the format's
  own declared counts where the header carries them (STL, binary PLY, OFF), and
  otherwise by a counting pre-pass that aborts at the ceiling. These bound the
  parser's working set; the byte ceiling above is what bounds the harness's.

All three refuse `mesh_import_too_large`, naming the ceiling, the observed value,
and the environment variable that raises it (the local-floor pattern `COMPARE.md`
§5 establishes for `compare_solids`, `COMPARE.md:113-118`). trimesh has no
memory limit of its own; `RWGltf_CafReader.SetMemoryLimitMiB` is the only such
guard anywhere in the pinned kernel surface, and it is on a reader this stage
does not admit.

**Why `mesh_import_too_large` and not `mesh_too_large`.** `PHYSICS.md` already
uses `mesh_too_large` for an entirely different refusal in a different taxonomy —
an FEA node count exceeding `FEA_NODES_MAX`, fired post-mesh, inside the solver
path (`PHYSICS.md:527,853`). One string naming two refusals across two closed
sets would make both taxonomies unreadable in a log and would break the
"named refusals" property at exactly the point it is load-bearing. Since
`PHYSICS.md` is sequenced first (header), this document renames its own code.
The two are now disjoint: `mesh_import_too_large` is an
`ImportResolutionReason` about a *file*; `mesh_too_large` is a solver refusal
about a *discretization*.

### 1.7 The closed refusal set

`ImportResolutionReason` (`imports.py:76-82`) is a closed `Literal` of five
codes. Stage 12 extends it, and this is the complete addition:

`mesh_format_unsupported`, `mesh_format_mismatch`, `mesh_unreadable`,
`mesh_empty`, `mesh_multi_object`, `mesh_not_finite`, `mesh_degenerate_only`,
`mesh_units_undeclared`, `mesh_units_unsupported`, `mesh_units_conflict`,
`mesh_import_too_large`.

`mesh_multi_object` covers an OBJ with several `o` groups or a PLY with several
elements: the harness refuses rather than choosing one or concatenating, because
either choice is a normalization the file did not authorize. Every one of these
surfaces exactly as `unreadable_step` does today — recorded by
`stage_request_imports` into `import_errors` (`runner.py:193-202`), raised by the
registry when the statement runs (`namespace.py:407-425`), so it lands as a §8
build error at the offending line with a frame, not as an opaque pre-build
exception.

## 2. What a mesh IS in the type system

### 2.1 `hephaestus.geom.mesh`, a tenth pure service

The nine existing geom services are pure functions over OCP/build123d shapes,
with a mechanically enforced boundary: a static allowlist of five leaf
`hephaestus.core` modules plus `opstore.types`
(`core/tests/test_geom_import_boundary.py:45-56`) and a subprocess import-closure
check forbidding the executor, project store, checks, registry, **render**, CLI,
lint, toolgen, MCP, bridge, bench and contract prefixes
(`test_geom_import_boundary.py:59-78`).

`geom.mesh` is the tenth service and the first to take something that is not an
`AnyShape`. Two consequences the boundary test must be amended for, and both are
deliberate:

- **Third-party numeric imports are already legal.** The boundary forbids
  `hephaestus.*` prefixes and the three agent top-levels; it says nothing about
  numpy, trimesh or scipy. `geom.mesh` may import them directly.
- **`geom.mesh` may NOT import `hephaestus.core.render.tessellate`** — the
  prefix is forbidden at `test_geom_import_boundary.py:70`. This is not an
  obstacle to route around; it is the correct seam, and the rule 6 answer
  (`mission_plan.md:818-822`) is: **`render.tessellate` owns B-rep → triangles
  for rendering** (its deflection constants are golden provenance,
  `tessellate.py:14-18,52-54`); **`geom.mesh` owns external triangles → facts**.
  They share a data shape and no code, and neither is a second implementation of
  the other's job. A gate clause asserts the closure stays clean.

### 2.2 `MeshAsset` — and a field-naming rule that does the work

```python
@dataclass(frozen=True)
class MeshAsset:
    source_path: str            # as written in the script
    units_declared: str         # "mm" | "cm" | "m" | "in"
    canonical_hash: str         # sha256 of the §1.5 blob (NOT of the sidecar)
    weld_tol_mm: float          # the tolerance the facts below were measured at
    vertex_count_as_read: int   # process=False parse, before §1.5 step 4; from the sidecar
    vertex_count: int           # post-weld, from the blob
    triangle_count: int
    bbox_mm: tuple[float, float, float]
    tessellated_volume_mm3: float | None
    tessellated_area_mm2: float
    watertight_at_weld_tol: bool
    euler_characteristic: int
    quality: MeshQuality        # §3
```

Provenance of each field, since the record is assembled inside the sandbox from
two staged files (§1.5.2): `canonical_hash`, `vertex_count`, `triangle_count`,
`tessellated_*`, `watertight_at_weld_tol` and `euler_characteristic` are
recomputed from the `.hmesh` blob and are therefore checkable against it;
`vertex_count_as_read` and `quality` are **read from the `.hmesh.facts`
sidecar**, because they are facts about the pre-canonical mesh that the blob no
longer contains. `source_path`, `units_declared` and `weld_tol_mm` come from the
declaration and the blob header. No field is guessed, and none is recomputed
from a different mesh than the one the hash names.

The record deliberately has **no field named `volume`, `sealed`, or `genus`.**
That is the whole mechanism. `KINEMATICS.md:201-211` is the precedent: a sweep
emits `holds_at_samples` and never `holds`, because "the verdict name says so" is
stronger than a note asking the reader to remember. Applied to measurement rather
than verdicts:

| Forbidden here | Why | Field that replaces it |
|---|---|---|
| `volume` | It is the **polyhedron's** volume — systematically low, because facets are inscribed. Measured: −0.36% at 0.05 mm deflection, −0.073% at 0.01 mm. It measures the *sample*, not the object. | `tessellated_volume_mm3`, `None` unless `watertight_at_weld_tol` |
| `sealed` | `geom.metrics.is_sealed` (`geom/metrics.py:110-121`) is a B-rep predicate about shells and edge use. Measured on a sewn faceted sphere: `is_sealed=True` while `BRepCheck_Analyzer.IsValid()=False` on the same shape. The two words must not be interchangeable. | `watertight_at_weld_tol` — a combinatorial fact about the file's edge-manifoldness **at a stated tolerance**, which the field name carries |
| `genus` | `geom.metrics.genus` (`metrics.py:134-143`, documented `metrics.py:16-32`) is the Euler characteristic of closed shells. On a scan it counts the *mesh's* handles: bridged folds, self-intersections, scanner artifacts. **The genus of a scan is a property of the scanner, not of the limb.** | `euler_characteristic` — the raw `V − E + F` of the welded mesh, reported as a fact about the file and never translated into a claim about the object |
| any face-kind census | Every triangle is planar, so a mesh reads as 100% `planar_faces` (`geom/compare.py:629-651`). A census delta against a designed solid is dominated by discretization and carries no information. | none — §6.5 refuses `topology_diff` against a scan target rather than filling it |
| any parameter, feature, or design intent | `INGEST.md:25-26` for STEP; strictly stronger here — there is no cylindrical face to recognize | none, ever |

`tessellated_volume_mm3` is `None` — not zero, not a number — when the mesh is
not watertight at the weld tolerance. A volume computed from an open surface is
not a small error; it is not a volume.

### 2.3 `PointCloudAsset` — a distinct kind, because it is not a shape

A point cloud is not a `Shape`, has no faces, and cannot ride
`shape_from_brep` (`geom/step_io.py:132-148`). It is also the sharpest
silent-failure risk in this spec: `surface_distance` on a shape with no faces
returns **zeros with zero sample counts** (`geom/compare.py:599-608`) rather than
refusing — honest only because the counts are in the record, and not honest
enough for something that will be handed a point cloud by mistake.

```python
@dataclass(frozen=True)
class PointCloudAsset:
    source_path: str
    units_declared: str
    canonical_hash: str
    point_count: int
    bbox_mm: tuple[float, float, float]
```

It has no volume, no area, no watertightness, no topology. Passing one where a
shape is expected is refused `point_cloud_not_a_shape` at the boundary, never
silently sampled to zeros. In 12A a point cloud can be measured (bbox, count,
point-to-part distances via §6.2) and nothing else. Reconstruction to a mesh is
§11.2.

### 2.4 Mesh topology carries no identity

`INGEST.md:46-51` makes `tag()` work on imported B-rep topology by selector and
calls the §5.3 drift fingerprint "load-bearing here, not optional". Neither
transfers:

- Triangle and vertex indices are an artifact of the file's triangle order, which
  §1.5 step 6 deliberately replaces with a canonical order. A re-export of the
  same scan produces a different original order and — if a single vertex moved by
  more than the weld tolerance — a different canonical order too.
- The drift fingerprint compares centroid/normal/area descriptors of tagged
  faces. There is nothing stable to fingerprint: every triangle is a
  discretization artifact.

Therefore: **`tag()` on mesh topology is refused by name** (`mesh_topology_not_taggable`),
and no selector grammar addresses a triangle. What a script may address is the
asset as a whole. This is a restriction, and stating it is cheaper than
discovering it as a silently meaningless warning three stages later.

## 3. Mesh quality: measured and named, never silently repaired

The single most dangerous thing this stage could do is quietly clean a scan.
Every defect is measured, named, and reported; **no repair is ever applied
implicitly**, and every repair that exists (§4.2) is an explicit call whose
effects are recorded as a delta.

```python
@dataclass(frozen=True)
class MeshQuality:
    weld_tol_mm: float
    welded_vertex_pairs: int          # merged in §1.5 step 4
    degenerate_triangles_dropped: int # dropped in §1.5 step 5
    boundary_edge_count: int          # edges used by exactly 1 triangle
    boundary_loop_count: int          # holes, assembled from those edges
    largest_hole_perimeter_mm: float
    nonmanifold_edge_count: int       # edges used by 3+ triangles
    nonmanifold_vertex_count: int     # vertices whose triangle fan is not a disc
    connected_component_count: int
    inverted_normal_triangles: int    # inconsistent winding vs. component majority
    self_intersecting_pairs: int | None   # see below
    self_intersection_method: str
```

All but the last are exact combinatorial facts, computable in numpy,
hand-computable on fixtures (a cube with one triangle deleted has exactly 3
boundary edges and 1 loop), and therefore fully gate-testable at 12A. **Where
each is computable matters, and the record splits on it:** the first two fields
are differences between the as-read mesh and the canonical mesh, so they exist
only in the parent, during §1.5 — nothing downstream of the canonical blob can
recover them. Every remaining field is a fact about the blob itself and could in
principle be recomputed anywhere. The whole record is nevertheless computed
**once, in the parent**, and travels in the `.hmesh.facts` sidecar (§1.5.2), so
the worker reports the numbers the canonicalizer actually observed rather than a
second computation that might disagree.

**Self-intersection is the honest exception.** An exact all-pairs triangle
intersection test is O(n²) and unbounded on a 10⁵-triangle scan. `geom.mesh`
therefore reports it as a **sampled** fact:
`self_intersection_method = "uniform_grid_exact_pairs"` with the grid cell size
recorded, and `self_intersecting_pairs = None` with method
`"not_evaluated_ceiling"` when the candidate-pair count exceeds
`MESH_SELFX_PAIR_MAX`. A `None` here means *not measured*, and the method field
says which; it never means *zero*. This is the `holds_at_samples` discipline
applied to a defect count: the absence of a found intersection is evidence, not
proof, and 12A's record must not let a reader mistake one for the other.

A scan that arrives with holes, non-manifold edges and inverted normals is
**admitted** with all of that recorded. Refusal is reserved for what makes the
file unreadable (§1.7), not for what makes the scan imperfect — every real limb
scan is imperfect, and a harness that refuses them all has not opened the door.

## 4. Mesh → B-rep, and where it must refuse

### 4.1 What OCCT actually offers

Measured on a sewn faceted sphere (R20, tessellated at the pinned deflections of
`tessellate.py:52-54`, then `BRepBuilderAPI_Sewing(1e-6)` →
`BRepBuilderAPI_MakeSolid`):

| Operation | Measured result |
|---|---|
| `BRepBuilderAPI_Sewing` | Works. 2004 tris → 0.32 s; 4002 → 0.78 s; 19952 → 4.41 s — **196 → 221 µs/tri, mildly superlinear**. One closed `TopAbs_SHELL` for a clean mesh |
| `BRepBuilderAPI_MakeSolid` | Cheap; `is_sealed` True, `genus` 0 |
| `ShapeUpgrade_UnifySameDomain` | Faceted box: 12 faces → 6. Faceted sphere: 19952 → 19952 (0.82 s). Merges **coplanar** faces only: recovers real faces from a CAD-exported mesh, does nothing for a scan |
| Boolean (19952-face solid `cut` a native Box) | 3.13 s, 16819 faces. Works; explodes face count |
| `BRepCheck_Analyzer(...).IsValid()` | **False**, on the same solid whose `geom.metrics.is_sealed` is **True** |
| `BRepOffsetAPI_MakeOffsetShape(+2 mm)` | **The finding below** |

Sewing cost is the first hard constraint: **196-221 µs/triangle** means a
100k-triangle scan costs ~20-30 s of parent-side work, which alone exceeds the
30 s full-build budget at `verification.md:210-212`. Sewing therefore runs under
the `COMPARE.md` §5 killable-subprocess ceiling (`COMPARE.md:113-120`), with a
named `mesh_sew_timeout` refusal that carries the facts already computed — the
§3 quality record and the bbox — and says the sew was lost.

### 4.2 The offset finding, which is why §4.3 exists

`BRepOffsetAPI_MakeOffsetShape` at +2 mm, measured:

- analytic sphere: instant, correct;
- faceted sphere, 436 faces, `GeomAbs_Arc` join: **null result**, 0.24 s, no
  exception (the class `CompareBooleanError` was created for,
  `geom/compare.py:433-446`);
- faceted sphere, 436 faces, `GeomAbs_Intersection` join: `KeyError:
  TopAbs_COMPOUND` — a garbage result type;
- **faceted sphere, 2004 faces, `GeomAbs_Intersection`: `IsDone()=True`,
  non-null, `TopAbs_SOLID`, 279 faces, `is_sealed=True`, `genus=0`, 29.74 s —
  and `volume = 0.003 mm³` where the correct answer is 44602 mm³.**

That last row is the load-bearing measurement of this spec. OCCT's offset on a
mesh-derived solid returns a plausible-looking, silently, catastrophically wrong
solid that **passes every sanity signal the harness currently has**: `IsDone`,
non-null, sealed, genus 0. Offset is the operation a socket workflow most wants.
A harness that ran this and reported `sealed=True` would be lying in exactly the
register `VALIDATION.md` exists to prevent.

### 4.3 `mesh_to_solid` and its mandatory validity gate (12B)

```python
solid = mesh_to_solid(scan, intent="measurement_target")
```

- `intent` is a closed set: `"measurement_target"` (the solid will be measured,
  compared, sectioned) or `"boolean_operand"` (it will be cut from or united with
  authored geometry). There is no `"offset_operand"` value, and there will not
  be one before §4.5's evidence exists.
- The sew runs under the §4.1 ceiling.
- **`BRepCheck_Analyzer(result).IsValid()` is checked, and a False verdict is a
  refusal: `mesh_solid_invalid`,** carrying the analyzer's own per-sub-shape
  status list, the triangle count, and the §3 quality record so the caller can
  see *why* (holes, non-manifold edges).
- The refusal is the point. On the measured fixture — a clean, watertight,
  tessellated sphere, i.e. the friendliest possible input — `IsValid()` is
  **False**. This spec therefore predicts that `mesh_to_solid` **refuses most
  real scans**, and says so rather than shipping a path that appears to work.
  The socket workflow of §5 is designed to not need it.

Downstream honesty rules, all enforceable:

- A part whose geometry derives from a `mesh_to_solid` result carries
  `geometry_source: "mesh_derived"` on its build record, and the reviewer
  context (§7.4) receives it.
- `offset`, `shell`/`thicken`, `fillet` and `chamfer` on a mesh-derived solid
  are **not** kernel-interceptable: `script_contract.md:28-29` states that
  Hephaestus does not wrap or rename build123d, so there is no chokepoint at
  which the harness can see the operand. This spec does not invent one. What it
  does instead, and the split is deliberate:
  - a **hard refusal** where enforcement is real — the `IsValid()` gate above,
    which withholds the object that would poison the operation;
  - a **named syntactic lint** where it is not — `heph lint` emits
    `mesh_derived_offset` when a script's AST contains an offset/shell/fillet/
    chamfer call whose operand traces by single assignment to a `mesh_to_solid`
    result. It is syntactic, it is defeatable by indirection, and the rule's own
    documentation says so. A lint that overclaims its reach is the same defect
    one level down.

### 4.4 Surface reconstruction is not available, and is not approximated

Verified against the pinned kernel:

- `GeomAPI_PointsToBSplineSurface.Init` requires `TColgp_Array2OfPnt` — a
  **rectangular grid** — across all three overloads. Unstructured scan points
  cannot be fed to it without a parameterization step nothing in the stack
  provides.
- `BRepOffsetAPI_MakeFilling` / `GeomPlate_BuildPlateSurface` fill a patch from
  **boundary curve constraints**. They are not auto-surfacers.
- `BRepLib_PointCloudShape` runs the wrong direction — its own docstring
  describes simulating the points obtained from laser-scanning a shape. It is
  useful for *synthesizing* a scan fixture (§7.5) and reconstructs nothing.
- No Poisson, ball-pivoting, or ICP anywhere: `open3d`, `pymeshlab`,
  `manifold3d` and `rtree` are all measured **absent**.

`mesh_to_nurbs`, `fit_surface`, and every spelling of "auto-surface" are refused
by absence: they are not in the surface, and §11.2 names them as a later stage
rather than leaving a reader to assume they exist.

### 4.5 The one open question this spec does not pre-decide

`ShapeFix_Shape` / `ShapeFix_Shell` / `ShapeFix_Solid` exist in the bindings.
**Whether they can repair a faceted solid to `IsValid()`, and at what cost, was
not measured.** This spec does not assume they can, and does not assume they
cannot. G12B carries a clause that *measures* it on the pinned image and records
the number, and the spec pre-commits to the **disposition rule** rather than the
result:

- if `ShapeFix` reaches `IsValid()` on the reference fixture within the §4.1
  ceiling, `mesh_to_solid` gains a `repair=True` argument whose use is recorded
  on the build record and whose before/after face counts are reported;
- if it does not, `mesh_to_solid` keeps refusing `mesh_solid_invalid` and the
  socket workflow is §5.2 only.

Either way the gate clause is a command and the evidence is archived (rules 1 and
2, `mission_plan.md:801-806`). Naming an unmeasured mechanism as new work rather
than assuming it is the `KINEMATICS.md` discipline.

## 5. The socket workflow: what the kernel supports today

### 5.1 The four operations a socket needs

| Operation | On a mesh-derived solid | On authored analytic geometry |
|---|---|---|
| **offset** (relief, clearance) | **Refused.** §4.2: measured silently wrong | Works (`BRepOffsetAPI_MakeOffsetShape`, instant and correct on the analytic sphere) |
| **shell / thicken** (wall) | **Refused**, same mechanism and same measurement | Works |
| **trim** (proximal cut line) | Works via boolean — measured 3.13 s at 20k faces, and the result's face count explodes | Works, cheap |
| **blend / fillet** (edge relief) | **Refused by geometry, not by policy**: every edge of a faceted body is a facet crease. There is no smooth edge to blend | Works |

`mesh_derived_operation_refused` names the operation and cites this table.

### 5.2 The design this spec pushes: fit, then offset the fit

> **Do not offset the scan. Author geometry against the scan, and offset that.**

```
import_mesh("limb-l.stl", units="mm")          # injected term, 12A
  → section_polylines(scan, plane)             # injected term, 12B — §5.3
  → loft_sections(polylines, closed=True)      # injected term, 12B — see below
  → offset / thicken / trim / fillet           # build123d, already in §2's namespace
  → compare_to_scan(part, "scan:limb-l.stl")   # §6: measure the gap
```

**Every name in that chain is either build123d or an injected term, and the
distinction is not cosmetic.** `script_contract.md:44-45` closes the namespace
with "Nothing else", and `__import__` is absent, so a part script cannot reach
`GeomAPI_PointsToBSpline`, `BRepBuilderAPI_Sewing`, or any other OCP symbol —
naming one in a workflow this spec then gates would specify an unreachable path.
`loft_sections` is therefore a **harness-injected helper** (§12 item 22): it
takes the ordered polylines of §5.3, fits one B-spline per section with
`GeomAPI_PointsToBSpline` *inside the harness*, lofts them with build123d's own
`Solid.make_loft`, and returns an ordinary analytic `Solid` that the script then
treats like any other. `offset`, `thicken` and `fillet` stay plain build123d
because their operand is that analytic solid. The injected surface is exactly
five names (`import_mesh`, `import_point_cloud`, `mesh_to_solid`,
`section_polylines`, `loft_sections`), the manifest row says so, and G12B.29
asserts the set is exactly that and that no OCP name is reachable from a script.

The scan is measurement data. The socket is authored geometry, in a part script,
under version control, with parameters — everything `INGEST.md:22-24` says a
build must be. The gap between them is *measured*, not assumed. This keeps the
entire existing machinery valid and puts the honesty boundary in exactly one
place: the distance record of §6.

### 5.3 `section_polylines` (12B, new work)

`geom.measure.section(shape, plane)` (`core/src/hephaestus/geom/measure.py:109`)
takes an `AnyShape` and returns faces; it cannot take a `MeshAsset`. The new pure
function is a plane/triangle intersection over the canonical blob, assembling
ordered contours:

- returns ordered polylines with a declared point spacing, deterministic in
  canonical triangle order;
- a contour that does not close — the plane crossed a hole in the scan — is
  **`open_section_contour`**, returned as an open polyline flagged as open, never
  silently closed by joining its ends. Closing it would fabricate limb surface
  that the scanner never saw, at exactly the place where a socket would press.
- a plane that misses the mesh is `empty_section`, not an empty success.

## 6. Scoring against a scan target

### 6.1 What COMPARE.md already gives, unchanged

`COMPARE.md` §1's discipline transfers wholesale and is not reimplemented: sample
counts are part of the record because "a number computed from four points is not
the same claim as one computed from four thousand" (`compare.py:176-182`);
thresholds live in a `CHECKS` predicate, never in the measurement
(`COMPARE.md:45-47`); alignment is a declared choice, never a silent
normalization (`COMPARE.md:36-38`); and execution is bounded with partial facts
carried through the refusal (`COMPARE.md:105-129`).

### 6.2 Direction A — scan → part. Exact, and free today

`_point_distances(points, target)` (`compare.py:563-578`) already takes a raw
`list[Vec3]` and a target shape and computes `BRepExtrema_DistShapeShape` to the
true B-rep surface. Measured against a smooth analytic target: **0.05 ms/pt**, so
200k scan points ≈ 10 s. This direction is exact, deterministic, and needs no new
geometry code — only a caller that feeds it the canonical blob's vertices (or a
declared triangle-area-weighted sample of them).

### 6.3 Direction B — part → scan. Catastrophic on the existing path

The existing path cannot be used, and the numbers say why:

- `_face_samples` has a floor of `MIN_FACE_SAMPLES = 4` **per face**
  (`compare.py:128`, applied at `compare.py:506-511`). Every triangle is a face.
  Measured: a 4002-triangle solid yields **9430** samples; the smooth sphere
  yields 256.
- `_point_distances` against a 4002-face target measures **54.6 ms/pt** versus
  0.05 ms/pt against a smooth target — **1000× slower**, because
  `BRepExtrema_DistShapeShape` has no spatial index.
- Product: **~515 s for one direction of one 4002-triangle mesh**, scaling as
  O(n_tri²). A 100k-triangle scan extrapolates to days. `COMPARE.md` §5 already
  records a 19 h grind and five infrastructure deaths on `compare_solids`
  (`COMPARE.md:107-110`); this would be five orders of magnitude past that
  ceiling.

So direction B is genuinely new machinery, and it is built mesh-side:

1. Build a `scipy.spatial.cKDTree` over the canonical blob's welded vertices.
   Measured: 200k queries against a 20480-triangle mesh in **0.09 s**
   (0.45 µs/pt) — ~120,000× faster than `BRepExtrema`.
2. For each query point, the vertex-nearest distance `d_v` is a **sound upper
   bound** on the true point-to-surface distance, because the nearest vertex lies
   on some triangle.
3. Query all triangles having any vertex within `d_v + L_max`, where `L_max` is
   the mesh's longest edge. Any triangle whose closest point lies within `d_v`
   must have a vertex within that radius, so the candidate set is a **sound
   superset**.
4. Compute exact point-to-triangle distance over the candidates in numpy. The
   result is **exact**, not approximate, and the record says so:
   `part_to_scan_method = "kdtree_bound_exact_triangle"`.
5. If a radius query returns more than `SCAN_CANDIDATE_MAX` triangles — a
   pathological mesh with one enormous triangle inflating `L_max` — the exact
   refinement is abandoned by name: `scan_neighborhood_overflow`, and the record
   reports `part_to_scan_upper_bound_mm` from step 2 with
   `part_to_scan_method = "vertex_nn_upper_bound"` and `bias = "over"`. Measured
   bias for reference: vertex-NN mean 0.409, centroid-NN 0.372, true
   point-to-surface 0.300 — always an over-estimate, bounded by mesh edge length.

`scipy` becomes an explicit `core/pyproject.toml` dependency for this. It is
already resolved in the environment as a requirement of `pyrender 0.1.45`
(measured), so this pins what is installed. `rtree` is **not** added, so
`trimesh.proximity.closest_point` — which needs it — is not the mechanism;
`ModuleNotFoundError` on that path was reproduced.

### 6.4 The `ScanDistance` record, and the fields it deliberately lacks

```python
@dataclass(frozen=True)
class ScanDistance:
    align: Literal["as_posed", "declared"]
    declared_transform: tuple[float, ...] | None   # row-major 4x4, when align="declared"
    scan_to_part_mean_mm: float
    scan_to_part_max_mm: float
    scan_samples: int
    part_to_scan_mean_mm: float | None
    part_to_scan_max_mm: float | None
    part_to_scan_upper_bound_mm: float | None
    part_to_scan_method: str          # "kdtree_bound_exact_triangle" | "vertex_nn_upper_bound"
    part_samples: int
    scan_canonical_hash: str
    part_artifact_ref: str
```

There is **no `iou` field, and no `chamfer_mm` field.**

- **No `iou`.** `volume_diff` (`compare.py:484-498`) needs solids on both sides.
  Getting one from a scan costs a sew (196-221 µs/tri) plus `MakeSolid` plus two
  OCCT booleans on a 10⁵-face solid, and — per §4.1 — the resulting solid is
  `IsValid()=False`, so the boolean's own answer is untrustworthy even when it
  returns. The record omits the field rather than computing a number nobody
  should read. Where a caller asks for one, the refusal is
  `scan_iou_unavailable`, citing this clause.
- **No `chamfer_mm`.** `SurfaceDistance.chamfer_mm` is the mean of two directed
  means (`compare.py:614-620`), and here one of the two directions may be an
  upper bound (step 5). Averaging an exact number with a bound produces a number
  with no defined meaning. The two directions are reported separately, always,
  and any symmetric figure is the caller's to form from fields whose methods it
  can read.
- `part_to_scan_mean_mm` is `None` exactly when the exact refinement was
  abandoned; `part_to_scan_upper_bound_mm` is populated exactly then. They are
  never both populated and never both absent.

### 6.5 Alignment, and what `compare_solids` refuses

The `COMPARE.md:36-38` rule is extended, not bent:

- **`as_posed`** — the scan is where the operator placed it. The honest default
  for a scan whose frame was established at capture.
- **`declared`** — an operator- or script-supplied rigid transform, recorded in
  the record. New mode, new field.
- **`principal` is refused**: `scan_principal_unavailable`. Two independent
  reasons. `principal_alignment` raises `ValueError("principal_alignment needs a
  shape with volume")` (`compare.py:351-352`), which an unsewn scan shell or a
  point cloud can never satisfy. And a limb scan is always **partial** — the
  principal axes of the sampled region are not the principal axes of the object,
  so `principal` would be a silent lie even where it ran.
- **There is no fitted registration.** No ICP exists in the pinned stack and this
  stage adds none. Alignment is declared or it is refused; a silently fitted
  transform would be exactly the "silent normalization" `COMPARE.md:36-38`
  forbids.

`compare_solids` (`tool_schema.md:559-600`) and `m.diff`
(`script_contract.md:209-236`) are **unchanged**: a `scan:` target on either is
refused `scan_target_unsupported`, naming `compare_to_scan` / `m.scan_diff`. A
`SolidDiff` promises `iou` and a topology census; neither is available against a
scan, and a record that returns them as zeros or as discretization noise is worse
than a refusal.

### 6.6 Round-trip fidelity, with a named tolerance

The stage's fidelity claim is bound to a closed loop with an analytic ground
truth: tessellate a known analytic solid at the pinned deflections
(`LINEAR_DEFLECTION = 0.1` mm, `tessellate.py:52`), export it, re-import it
through `import_mesh`, and compare it back to the original analytic solid.

The clause is **two clauses**, because the loop measures two different things and
one direction cannot carry both. OCCT's tessellator places its nodes *on* the
surface; the chord deviation that `LINEAR_DEFLECTION` describes lives strictly
*between* the nodes. So the mesh-vertex-to-solid direction is ~0 by construction
and cannot bound fidelity — a bound of `1.10 × LINEAR_DEFLECTION` on it has some
five orders of magnitude of slack and would pass a tessellation that had lost
its shape entirely, or a weld that had collapsed the mesh. Binding the deflection
requires the *other* direction.

- **Identity (that the vertices survived the pipeline):**
  `scan_to_part_max_mm ≤ MESH_ROUNDTRIP_EPS_MM`, a kernel-precision constant on
  the order of `1e-3` mm, measured in the pinned image at gate-authoring time.
  This is not a fidelity check and is not described as one. It asserts exactly
  what it can: every tessellation node, after export, re-import, unit scaling
  (§1.3) and welding (§1.5 step 4), still lies on the surface it came from. A
  scale error, a coordinate-order bug, a corrupted writer, or a weld that moved
  a vertex fails it; a coarse tessellation does not, and must not, because a
  coarse tessellation's nodes are still on the surface.
- **Fidelity (that the mesh actually holds the deflection the pipeline
  declared):** `part_to_scan_max_mm`, measured from samples on the analytic
  solid to the imported mesh, into a **two-sided** window
  `0.5 × LINEAR_DEFLECTION ≤ part_to_scan_max_mm ≤ 1.10 × LINEAR_DEFLECTION`.
  The upper bound catches a tessellation coarser than declared; the lower bound
  catches an implausibly-zero result, which in this loop means the measurement
  did not run, sampled nothing, or silently compared the solid to itself — the
  failure a one-sided ceiling can never see. The clause additionally **requires**
  `part_to_scan_method == "kdtree_bound_exact_triangle"`: an upper-bound method
  (§6.3 step 5) fails the clause outright rather than satisfying it loosely,
  because a bound compared against a window is not a measurement.
  The upper margin is 10% because `LINEAR_DEFLECTION` is a bound OCCT is
  permitted to *approach*, and the sampled maximum is a discrete estimate of a
  continuous maximum, so a sampled figure at or a little under the declared
  bound is the expected result; the margin is headroom for the sampling, not for
  the weld — the weld's effect is bounded by `MESH_WELD_TOL_MM = 1e-6` mm, which
  is four orders of magnitude below the deflection and cannot account for a 10%
  band. The constant's final value is re-measured in the pinned image before the
  gate is authored (mission rule 4), and if the measured maximum does not land
  inside this window the window is not widened — the pipeline is wrong, which is
  the whole point of binding it.
- **Volume:** `tessellated_volume_mm3` is **below** the analytic volume, always
  (facets are inscribed), by no more than `MESH_TESSELLATION_VOLUME_BIAS`. This
  spec fixes the **sign** and the **requirement that the constant be measured in
  the pinned image at gate-authoring time**; it does not guess the value.
  Reference measurements in the repo venv: −0.36% at 0.05 mm deflection, −0.073%
  at 0.01 mm.
- **Identity:** the re-import's `mesh_canonical_hash` equals the hash of a
  second, independent re-import of the same bytes, in a separate process.

## 7. Surface

### 7.1 Script terms (12A)

`import_mesh(name, units=…)` and `import_point_cloud(name, units=…)` join the §2
injected-name list (`script_contract.md:38-42`). Both are terms, not tools — the
8A precedent, which is also the tool-count lever: `import_step` never became a
tool (`INGEST.md:17-22`), and at a tool surface pinned in two places
(`contract/tests/test_toolgen.py:98,109`,
`tests/stage2/test_g2_contract_drift.py:354`) the capability belongs in the
script. The pin's **value** is deliberately not quoted here: it is 53 today, and
`PHYSICS.md` — sequenced ahead of this stage — repoints it when its own tool
surface lands (`PHYSICS.md:47,809`). This spec's contract is that the pin
**increments by exactly one, from whatever its predecessor left it at**
(G12C.42), which is true under either landing order and stays true if a third
stage lands between them.

`ImportRegistry` (`core/src/hephaestus/core/executor/namespace.py:374-438`) gains
two methods that build a `MeshAsset` / `PointCloudAsset` from the staged files.
The step is **a dictionary lookup, a deserialize of the `.hmesh` blob, and a
read of its `.hmesh.facts` sidecar** (§1.5.2) — not the two-step
`import_step` does, and this spec does not claim parity with it. The third step
exists because `welded_vertex_pairs`, `degenerate_triangles_dropped` and
`vertex_count_as_read` are facts about the mesh *before* canonicalization and
are unrecoverable from a post-weld blob; the sidecar is the only honest channel
for them. What is unchanged from `import_step` is the property that matters: the
worker never sees a project path, both files are staged read-only in the
worker's own input area, and `open` stays absent from the script namespace —
the registry reads them, not the script.
`imports_used` records mesh imports the same way it records STEP ones
(`namespace.py:407-415` distinguishes script use from `m.diff` resolution; the
same split applies to `m.scan_diff`).

### 7.2 Tool surface (12C): exactly one new tool

`compare_to_scan(part, scan, align?, declared_transform?)` → the §6.4
`ScanDistance` plus the `MeshQuality` of the target and the resolved artifact
refs. Read-only, freely retryable, stores nothing; `part` and `orchestrator`
profiles, matching `compare_solids`.

One tool, because each tool costs five drift-tested generated artifacts (Python
decl, JSON schema, TypeBox, MCP manifest, `tool_schema.md` heading —
`contract/src/hephaestus/contract/toolgen.py:1-30`), a per-profile decision, and
dispatch tests on both profiles, all under one drift gate. Mesh **facts** are not
a tool: they ride the build record and `heph scan`.

### 7.3 `CHECKS` and CLI

- `m.scan_diff(part, "scan:<relpath>", align=…)` on the **part-scope** facade
  only, flattened like `m.diff`. A `scan:` target is a build input for exactly
  the reason an `import:` target is (`script_contract.md:228-236`): the check's
  verdict changes when the bytes change, so it is frozen, hashed and staged with
  the script's own imports. The freeze scan needs a `scan:`-prefix analogue of
  `diff_import_targets` (`imports.py:170-198`). The cross-part `checks/*.py`
  facade refuses a `scan:` target by name, unchanged in mechanism from its
  `import:` refusal.
- `heph scan <path>` prints the `MeshAsset` + `MeshQuality` facts (`--json`);
  `heph scan check <part> <path>` prints a `ScanDistance`.
- Bounded execution: `compare_to_scan`, `m.scan_diff` and `heph scan check` run
  the distance computation in a killable subprocess under `SCAN_TIMEOUT_S`
  (env-overridable). Cheap facts first — quality record, bboxes, counts — then
  direction A, then direction B; a ceiling kill returns `scan_timeout` **carrying
  the partial facts and naming which directions were lost**, and inside a
  `CHECKS` predicate it makes that check `unverifiable`, never a pass and never a
  crash. This is `COMPARE.md:113-125` reused, not reinvented.

### 7.4 Ladder integration

`VALIDATION.md` §5: for every part whose script imports a mesh, the termination
reviewer receives the `MeshQuality` record, `geometry_source`, and — where a
scan comparison ran — the `ScanDistance` with its method fields intact. A
mesh-derived `geometry_source` is **surfaced, not blocking**: it is a fact the
reviewer must see, and this spec does not add a new never-green rule.

### 7.5 Bench

A new corpus family `scan-*`, seeded with `imports/` fixtures. Under
`VALIDATION.md` §1 as G9C restates it (`KINEMATICS.md:393-398`): **scan-prose and
scan-seeded are each their own split, each baselined on its own first measurement
with the reference model at ≥3 seeds, neither compared against nor averaged into
the v1/v2 baselines**; the existing 0.70 prose bar keys on its own coverage
constant and is not diluted. A new coverage constant and its own threshold land
with the family — adding tasks without declaring the split leaves them invisible
to every gate.

Acceptance uses a new `scan_requirements` vocabulary in `task.json`, installed and
evaluated **through the engine path**, never from what the run reports about
itself. Every check is functional, never reproductive, and carries a named
tolerance (`VALIDATION.md:58-98`): "the socket wall clears the scan by ≥ 1.5 mm
at every sampled scan vertex" is a fit measured as a fit. A fixture scan is
**synthesized from an analytic solid** so ground truth exists — tessellate,
export, seed — which is also the only way §6.6's round-trip clause can have a
truth to compare against.

## 8. Determinism, stated exactly

`INGEST.md:44-45` claims "Identical bytes ⇒ identical geometry (STEP parsing is
deterministic for a pinned OCCT)". That sentence is scoped to STEP by this
amendment, and replaced here by three tiers, because a mesh pipeline is not
uniformly reproducible and pretending otherwise would be the failure mode this
document is about.

**Tier 1 — bit-reproducible, and gated as such.**
`input_hashes.imports[path]` (raw bytes). The canonical blob and its
`mesh_canonical_hash`. Every fact derived purely from the blob: counts, bbox,
`tessellated_area_mm2`, `tessellated_volume_mm3`, `watertight_at_weld_tol`,
`euler_characteristic`, and every exact combinatorial field of `MeshQuality`.
These are asserted **byte-identical across two separate processes** and inside
the pinned image. The chain is: identical file bytes + identical declared unit ⇒
identical canonical blob ⇒ identical facts. Nothing weaker is claimed — in
particular, **two exports of "the same scan" from different software are not
claimed to agree**, and the harness reports the two hashes rather than asserting
sameness.

**Tier 2 — reproducible to a named tolerance.** `ScanDistance` numbers. Every
input is deterministic (no RNG, canonical sample order, fixed reduction order by
sorted sample index), but they are floating-point reductions over large arrays.
Bound: **identical to 1e-9 across two processes** — the tolerance G8B already
uses for `SolidDiff` (`COMPARE.md:93-95`) — with identical sample counts and
identical method strings. A differing method string is a *different measurement*
and fails the clause, not just the number.

**Tier 3 — NOT bit-reproducible, and bound differently.** Everything downstream
of `BRepBuilderAPI_Sewing`. OCCT's sewing is a tolerance-driven merge whose
output topology this spec does not claim is stable across OCCT builds. What is
bound instead:

- within one pinned OCCT (7.9.3, `spikes/REPORT.md:10`), the sewn face and vertex
  counts and the `BRepCheck_Analyzer.IsValid()` verdict are asserted stable
  across processes;
- the sew-derived goldens carry a **provenance sidecar naming the (container
  image digest, OCCT version) pair**, and are valid only for that pair — the
  render-golden rule at `verification.md:66-73` extended from renderer to kernel.
  An OCCT bump is a re-baseline PR, exactly as a renderer digest bump is
  (`repo_conventions.md:186-194`).

A gate binds to Tier 3 by asserting the **verdict and the counts**, never the
bytes; that is the most a sew can honestly offer, and saying so is cheaper than a
flaky golden.

## 9. What deliberately does NOT change

No new persistence machinery: meshes and point clouds ride the opstore CAS
through `read_import` / `ImportSnapshot`
(`core/src/hephaestus/core/project_store/store.py:235-254`) exactly as STEP
imports do, with one new artifact kind registered alongside
`IMPORT_ARTIFACT_KIND`. No script-side file access of any kind. No feature
recognition and no surface reconstruction. No new session profile. No change to
`compare_solids`, `m.diff`, `SolidDiff`, or any G8B evidence — a `scan:` target is
refused there by name (§6.5) rather than widening the record. No change to
`geom.compare`'s purity: the new mesh-side distance code is pure and unbounded;
process management stays an engine concern (`COMPARE.md:121-123`). No change to
`render.tessellate` or any render golden. No change to export: exports are never
mesh-derived unless a script authored the geometry that way, and then the
`geometry_source` field says so. The path-confinement walk (`imports.py:258-341`)
keeps every confinement property it has — one `O_NOFOLLOW` descriptor per
component, no symlink ever followed, `S_ISREG` on the open descriptor — and
gains **exactly one thing and nothing else**: the `fstat`-size refusal of §1.6,
taken off the descriptor the walk already holds and passed a per-kind ceiling by
its caller (`None` for STEP, so STEP reads are bit-for-bit what they are today).
This document does not claim the function is untouched; it claims the confinement
property is, which G12A.3 re-proves for the new kinds. `tag()`, selectors, and §5.3 drift fingerprints
are unchanged for B-rep imports and refused for mesh topology (§2.4) — no third
behaviour is introduced.

## 10. Named refusals, consolidated

Admission (§1.7, extending `ImportResolutionReason`, `imports.py:76-82`):
`mesh_format_unsupported`, `mesh_format_mismatch`, `mesh_unreadable`,
`mesh_empty`, `mesh_multi_object`, `mesh_not_finite`, `mesh_degenerate_only`,
`mesh_units_undeclared`, `mesh_units_unsupported`, `mesh_units_conflict`,
`mesh_import_too_large`.

Type and topology: `point_cloud_not_a_shape` (§2.3),
`mesh_topology_not_taggable` (§2.4).

Conversion and operations: `mesh_sew_timeout` (§4.1), `mesh_solid_invalid`
(§4.3), `mesh_derived_operation_refused` (§5.1), `open_section_contour`,
`empty_section` (§5.3).

Comparison: `scan_target_unsupported` (§6.5), `scan_principal_unavailable`
(§6.5), `scan_iou_unavailable` (§6.4), `scan_neighborhood_overflow` (§6.3),
`scan_timeout` (§7.3).

Lint (warning-class, syntactic, documented as defeatable): `mesh_derived_offset`
(§4.3).

**Disjointness with the predecessor stage.** Every code above is checked against
`PHYSICS.md`'s refusal taxonomy (`PHYSICS.md:840-875`) and no string appears in
both. The one that did — `mesh_too_large`, which `PHYSICS.md` uses for an FEA
node-count ceiling — is spelled `mesh_import_too_large` here (§1.6). A refusal
code is a contract term; two contracts may not spend the same term on different
meanings, and the sequencing rule in the header decides which side renames.

## 11. Deliberately NOT in scope

### 11.1 Lattices and infill — a later stage, named

**Structural lattices (gyroid/TPMS, strut lattices) are out of scope**, by name,
and are a separate gated stage under mission rule 5 with the second-kernel
question as its explicit precondition. Three reasons, each independent:

- Nothing in the kernel does it. A TPMS lattice is an implicit surface; realizing
  it requires marching cubes, which produces a **mesh** — so a lattice is a
  mesh-*producing* operation and inherits every honesty problem in §2 and §4.
- OCCT is the wrong engine. A 20k-face boolean measured 3.13 s (§4.1); a real
  lattice is 10⁵-10⁶ faces and the boolean *is* the operation. Doing it properly
  needs a mesh-native boolean (manifold3d or a voxel path), which is a second
  implementation of what the Python core owns — squarely the mission rule 6
  question (`mission_plan.md:818-822`), and it must be answered before such a
  stage is scheduled, not during it.
- Admitting it here would import an unbounded-cost operation into a spec whose
  entire difficulty is already cost and honesty.

**Print infill is not geometry and already has a home.** The 3MF export path
exists (`contract/src/hephaestus/contract/tools_decl.py`'s `export_part` format
enum; `tool_schema.md` already writes `heph:` manufacturing metadata into 3MF),
and slicers own infill. The split is: print infill is manufacturing metadata;
structural lattice is new geometry machinery in a new stage.

### 11.2 Also out of scope, each named rather than unmentioned

Point-cloud → mesh reconstruction (no machinery, no dependency, §4.4).
Mesh → NURBS auto-surfacing (§4.4). ICP / fitted registration (§6.5).
Mesh booleans and remeshing (§0). glTF and 3MF import (§1.2, each an amendment).
Posed or animated scans. Multi-scan merging or stitching. Texture, colour, and
per-vertex attributes — the canonical blob carries geometry only, and a file's
colour data is discarded with a recorded count, never interpreted.

### 11.3 Clinical claims, refused in contract form

A prosthetic socket is a load-bearing medical device. This stage evidences
**geometric distance between an authored solid and a scan, at named samples, to a
named tolerance** — and nothing else. Specifically refused, in the register of
`KINEMATICS.md:55-58`'s refusal of continuous-motion certification:

- **Fit.** A distance figure is not a fit. Rectification — the clinical act of
  locally relieving and loading soft tissue — is judgement the harness cannot
  verify, and no `CHECKS` predicate over a `ScanDistance` may be presented as
  evidence of it.
- **Load.** Structural adequacy is FEA, deferred by name by mission rule 5
  (`mission_plan.md:815-817`); it enters only by its own gated stage naming its
  own missing pieces.
- **Softness.** The scan is of a rigid capture of a deformable limb. Nothing here
  models tissue.

Shipping the geometric half honestly is real capability. Shipping either half
while calling it "validated for fit" is the failure this project exists to
prevent.

## 12. Named new work

Everything below does not exist today and must be built. Anything absent from
this list is a claim that it already exists, so the list is exhaustive by
intent; each item names the file it lands in or beside.

1. **`hephaestus.geom.mesh`** — the tenth pure geom service: canonical-blob
   parse/serialize, quality computation, section polylines. No such module
   exists.
2. **Geom import-boundary amendment** — `core/tests/test_geom_import_boundary.py`
   admits `mesh` as a pure service and asserts its closure reaches
   `hephaestus.core.render` nowhere (`test_geom_import_boundary.py:64-78`), plus
   a clause pinning the §2.1 seam.
3. **`MeshAsset`, `PointCloudAsset`, `MeshQuality`, `ScanDistance`** — four
   frozen records, none of which exists.
4. **The canonical blob format** (§1.5 steps 4-7) — weld, degenerate drop,
   canonical ordering, header, serializer and deserializer. Entirely new.
4a. **The `.hmesh.facts` sidecar** (§1.5.2) — its JSON schema (sorted keys,
   round-trippable floats), its **parent-side computation** during staging, its
   read-only staging beside the blob, its worker-side read in
   `ImportRegistry`, and the rule that it is excluded from
   `mesh_canonical_hash`. It exists because `welded_vertex_pairs`,
   `degenerate_triangles_dropped` and `vertex_count_as_read` are unrecoverable
   from a post-weld blob; nothing today carries a second staged file per import.
4b. **`vertex_count_as_read` on `MeshAsset`** (§2.2) — the field G12A.9 binds to.
5. **Format admission + magic sniffing** for the five admitted extensions, with
   the two named format refusals (§1.2).
6. **Ceiling enforcement, in two places** (§1.6). (a) The **byte** ceiling
   inside the confinement walk: `read_import` (`imports.py:258-341`, the
   `os.fstat` at `:320-327`) gains a per-kind `max_bytes` argument and a
   `mesh_import_too_large` refusal raised **before** its `stream.read()`, plus
   the caller change in `PartStore.read_import` (`store.py:235-254`) that
   supplies the ceiling from the declaration's kind — without which the file is
   already in memory and in the blob store before any refusal can fire. (b) The
   **triangle/point** ceilings in the parent before trimesh sees the bytes, with
   a counting pre-pass for count-less formats. INGEST has no size cap of any
   kind today.
6a. **`BuildRequest.imports` becomes a per-path record** (§1.1) —
   `Mapping[str, ImportPayload]` carrying `(bytes, kind, units)` instead of
   `Mapping[str, bytes]` (`runner.py:116`, `publication.py:109`), with
   `_freeze_imports` threading `ImportDeclaration`s rather than path strings
   (`publication.py:227-238`), `import_hashes` reading `payload.bytes`
   (`runner.py:176-178`), and `stage_request_imports` passing kind and units
   through (`runner.py:181-202`). Without this the declared unit never reaches
   the staging code at all.
7. **`ImportResolutionReason` extension** — eleven new codes
   (`imports.py:76-82`).
8. **`_is_import_call` widening** from one name to a closed set
   (`imports.py:118-123`).
9. **`declared_imports` keyword grammar** — a required string-literal `units`
   keyword, where today any keyword is `DynamicImportPathError`
   (`imports.py:143-149`).
10. **`ImportDeclaration.kind` / `.units`** (`imports.py:108-116`).
11. **`staged_filename` unit-aware per-kind extension** (`imports.py:348-350`) —
    for mesh kinds the name becomes `sha256(content_hash + "\x00" + units)[:32]`
    plus the kind's extension (§1.5.1), so two byte-identical files at different
    declared units can never resolve to one staged blob; STEP's name is
    unchanged. Plus **`stage_import` kind dispatch** and its `units` argument
    (`imports.py:353-379`), and staging the sidecar of item 4a alongside.
12. **`ImportRegistry.import_mesh` / `.import_point_cloud`**
    (`namespace.py:374-438`) returning assets, not shapes — blob deserialize
    plus sidecar read (§7.1).
13. **Five new injected names** in the worker namespace and `script_contract.md`
    §2: `import_mesh` and `import_point_cloud` at 12A; `mesh_to_solid`,
    `section_polylines` and `loft_sections` at 12B. Each must be injected because
    `__import__` is absent and the §2 namespace is closed — a term used in §4.3
    or §5.2 that is not on this list is unreachable from a script.
14. **A new artifact kind** for mesh imports beside `IMPORT_ARTIFACT_KIND`
    (`store.py:235-254`).
15. **`mesh_canonical_hash` on the build record** and its rendering in build
    output — a second hash the record has never carried.
16. **`mesh_to_solid`** with sew, `MakeSolid`, the mandatory
    `BRepCheck_Analyzer` gate and the `mesh_solid_invalid` refusal (§4.3).
17. **The sew ceiling** — `COMPARE.md` §5's killable-subprocess pattern applied
    to sewing, with `mesh_sew_timeout` carrying partial facts.
18. **The `ShapeFix` repair experiment and its disposition** (§4.5) — measured,
    not assumed.
19. **`geometry_source: "mesh_derived"`** on the build record and through the
    reviewer context.
20. **`heph lint` rule `mesh_derived_offset`** (§4.3) — syntactic, warning-class,
    documented as defeatable.
21. **`geom.mesh.section_polylines`** with `open_section_contour` and
    `empty_section` (§5.3).
22. **`loft_sections`** — the injected section → B-spline → loft helper (§5.2),
    wrapping `GeomAPI_PointsToBSpline` and `Solid.make_loft` **inside the
    harness** and returning an analytic `Solid`, because no OCP name is
    reachable from a part script.
23. **The mesh-side nearest-point structure** (§6.3) — cKDTree candidates, the
    `d_v + L_max` soundness bound, exact point-to-triangle refinement in numpy,
    and `scan_neighborhood_overflow` with its named upper-bound fallback.
24. **`geom.compare.scan_distance`** producing `ScanDistance`, and the
    `declared` alignment mode with its transform validation.
25. **`scipy` as an explicit pinned dependency** (`core/pyproject.toml:7-17`),
    under mission rule 7.
26. **`compare_to_scan`** — one new tool and its five generated drift-tested
    artifacts, per-profile decision, and dispatch tests on both profiles.
27. **`m.scan_diff`** on the part-scope facade, with the cross-part refusal.
28. **A `scan:`-prefix freeze scan** — the `diff_import_targets` analogue
    (`imports.py:170-198`) so a `CHECKS` scan target is a frozen build input.
29. **`heph scan` and `heph scan check`** (human + `--json`).
30. **The `SCAN_TIMEOUT_S` bounded path** with `scan_timeout` carrying partial
    facts and the in-predicate `unverifiable` landing.
31. **Mesh-quality Tier 1 fixtures** — hand-computable meshes (a cube with one
    triangle removed; a non-manifold fin; a two-component file; a reversed-winding
    triangle) and the `verification.md` kernel-service list entry.
32. **A synthesized scan fixture generator** (tessellate → export → seed) so the
    corpus and the §6.6 round-trip clause have analytic ground truth.
33. **Sew-derived golden provenance sidecars** naming the (image digest, OCCT
    version) pair, and the `verification.md:66-73` extension that makes them
    valid only for that pair.
34. **The `scan-*` corpus family** — tasks in both spec variants, dual
    independent solutions, hand-counted budgets, a new coverage constant, its own
    threshold, and the `scan_requirements` acceptance vocabulary with its grader
    half evaluated through the engine path.
35. **Reviewer-context extension** carrying `MeshQuality`, `geometry_source` and
    `ScanDistance` (`VALIDATION.md` §5).
36. **The injected-surface closure test** (§5.2, G12B.29) — an assertion that
    the worker namespace's injected-name set equals the documented list exactly
    and that no OCP symbol is reachable from a script. The closure is asserted
    today for `open`/`__import__`; it has never been asserted as an *exact set*.
37. **The two round-trip constants** (§6.6) — `MESH_ROUNDTRIP_EPS_MM` and the
    two-sided fidelity window, each measured in the pinned image at
    gate-authoring time under mission rule 4, plus the fixture that makes
    `part_to_scan_max_mm` computable against an analytic solid.

## Gates

Stage 12 lands in three gated sub-stages, strictly ordered. Every clause below is
a pytest assertion; ambiguity in any of them is a defect in this document to be
resolved by tightening the clause, never by waiving it
(`mission_plan.md:801-804`).

### Gate G12A — admission, canonicalization, facts

`uv run pytest tests/stage12a -q` exits 0, covering:

1. Happy-path `import_mesh` for each of `.stl` (binary **and** ASCII), `.ply`
   (binary and ASCII), `.obj`, `.off`, and `import_point_cloud` for `.xyz` —
   each producing an asset whose counts and bbox equal independently computed
   values.
2. Every §1.7 refusal fires with its exact code, at the right layer, as a §8
   build error at the offending statement with a source frame: unsupported
   format (`.glb`, `.3mf`, each naming the amendment), extension/magic mismatch,
   unreadable payload, empty payload, multi-object OBJ, NaN coordinate,
   all-degenerate mesh, missing `units`, unsupported `units`, and each of the
   three ceilings.
3. The confinement walk is intact for the new terms: traversal, absolute path,
   symlinked leaf and symlinked parent component each refused with the existing
   codes, and the worker cannot open an `imports/` path directly (sandbox denial
   proven), for a mesh exactly as G8A proves it for STEP.
4. Grammar: a computed path and a computed `units` value each raise
   `DynamicImportPathError` at the right line/col; a positional-only
   `import_mesh("x.stl")` raises `mesh_units_undeclared`; `import_step` with a
   keyword still raises `DynamicImportPathError` (no regression).
5. `input_hashes.imports` carries the mesh path with the sha256 of the **raw**
   bytes; a byte-identical file with a different `units` declaration produces a
   different build; a re-exported file with only a changed ASCII header produces
   a **different** `input_hashes` entry and the **same** `mesh_canonical_hash`.
6. Staleness and revalidation for a mesh import: replaced file ⇒ stale,
   revalidation refuses the current flip, a lost-response retry replays the
   original bytes — the G8A clauses re-run on the new kind.
7. Canonicalization determinism: the same bytes produce a byte-identical
   canonical blob and identical `mesh_canonical_hash` in **two separate
   processes**; a fixture permuted only in triangle order and vertex order
   produces the **identical** canonical blob; a fixture with one vertex moved by
   more than `MESH_WELD_TOL_MM` produces a different one.
8. Unit scaling and staged identity, in **one** script and therefore one build:
   the **same file bytes** are imported four times, declared `mm`, `cm`, `m` and
   `in`, and the four resulting `MeshAsset.bbox_mm` triples stand in the exact
   ratios 1 : 10 : 1000 : 25.4. The clause additionally asserts the mechanism
   that makes that possible: the four staged filenames are **pairwise distinct**
   (the §1.5.1 formula), and a fifth declaration repeating an earlier
   (bytes, unit) pair resolves to the **same** staged file — reuse preserved,
   collision impossible. Against the unmodified `staged_filename`
   (`imports.py:348-350`) this clause fails, which is the point of writing it.
9. Pre-canonical counts survive the sandbox boundary: a fixture STL whose file
   carries duplicated vertices reports `vertex_count_as_read` equal to the
   `process=False` parse count, `vertex_count` equal to the post-weld count, and
   the two differ by exactly the recorded `welded_vertex_pairs`; the same for
   `degenerate_triangles_dropped` on a fixture carrying degenerate triangles.
   Both are read from the `.hmesh.facts` sidecar, and the clause pins the
   separation: mutating the sidecar changes the reported facts and leaves
   `mesh_canonical_hash` **unchanged**, while mutating the `.hmesh` blob changes
   the hash. A worker-side attempt to recompute either field from the blob alone
   is asserted impossible by fixture: two files differing only in duplicated
   vertices produce the identical blob.
10. `MeshQuality` against hand-computable fixtures: a closed cube (0 boundary
    edges, 0 loops, 1 component, χ = 2); a cube with one triangle removed (3
    boundary edges, 1 loop, exact perimeter); a non-manifold fin (exact
    `nonmanifold_edge_count`); a two-component file; a single reversed-winding
    triangle (exact `inverted_normal_triangles`); a file with degenerate
    triangles (exact dropped count).
11. Self-intersection reporting: a fixture with a known intersecting pair reports
    it with method `uniform_grid_exact_pairs`; a fixture exceeding
    `MESH_SELFX_PAIR_MAX` reports `None` with method `not_evaluated_ceiling`, and
    the test asserts the record does **not** read as zero.
12. Field-name discipline, asserted as a test over the record classes:
    `MeshAsset` and `PointCloudAsset` expose **no** attribute named `volume`,
    `sealed`, `genus`, `chamfer_mm` or `iou`. A rename that reintroduces one
    fails the gate.
13. `tessellated_volume_mm3` is `None` for a fixture that is not watertight at
    the weld tolerance, and equals the hand-computed polyhedron volume for one
    that is.
14. `point_cloud_not_a_shape` fires where a `PointCloudAsset` reaches a shape
    parameter; a regression clause asserts a point cloud never reaches
    `surface_distance` and so never produces the zeros-with-zero-counts result of
    `compare.py:599-608`.
15. `tag()` on mesh topology refuses `mesh_topology_not_taggable`; no selector
    grammar resolves a triangle.
16. Mixed builds: a script importing a mesh **and** a STEP file **and** authoring
    native geometry builds, measures and exports, with both import kinds in
    `input_hashes` and `imports_used`.
17. Boundary: `geom.mesh` passes the import-closure check, reaches
    `hephaestus.core.render` nowhere, and the existing geom/contract/core
    boundary tests stay green.
18. `heph scan <path>` human and `--json` output over each admitted format.
19. Performance, measured in the pinned image and enforced as a ceiling: parse +
    canonicalize + quality for the reference fixture scan within a named budget
    (`verification.md` addition), the constant set from the image's own
    measurement.
20. The byte ceiling fires **inside the walk, before anything is spent**: a file
    whose `st_size` exceeds `MESH_MAX_BYTES` refuses `mesh_import_too_large`,
    and the clause asserts all three consequences that distinguish this from a
    post-read check — the opstore blob store gained **no** new blob
    (`store.py:249` never ran), no `ImportSnapshot` was registered, and the
    refusal arrived without the file's bytes ever being read (asserted against a
    sparse fixture far larger than the process's memory, which a
    `stream.read()`-first implementation cannot survive). A STEP import of the
    same size is unaffected, proving the ceiling is per-kind and STEP's `None`
    ceiling left the existing path alone.

### Gate G12B — mesh → B-rep, sections, the socket path

`uv run pytest tests/stage12b -q` exits 0, covering:

21. `mesh_to_solid` on a clean tessellated-sphere fixture: the sew runs,
    `BRepCheck_Analyzer.IsValid()` is evaluated, and the verdict is asserted —
    the test records the measured verdict rather than presuming it, and if it is
    False the call refuses `mesh_solid_invalid` carrying the analyzer status list
    and the quality record.
22. The §4.2 finding is pinned as a regression: an offset of a mesh-derived solid
    is never reachable through `mesh_to_solid`'s `intent` set, and a direct
    fixture reproducing the 279-face / `sealed=True` / 0.003 mm³ result is
    asserted to be exactly what the validity gate withholds.
23. `is_sealed` vs `IsValid()` divergence is asserted **as a fact** on the sewn
    fixture: `geom.metrics.is_sealed` True while `BRepCheck_Analyzer.IsValid()`
    False, so the two are pinned as different predicates and no future change can
    silently conflate them.
24. `mesh_sew_timeout` under a fault-injected slow sew: named refusal, partial
    facts (quality + bbox) attached, subprocess dead afterwards.
25. The `ShapeFix` experiment (§4.5) runs on the pinned image, records its
    outcome and cost as archived evidence, and the gate asserts whichever branch
    of the disposition rule that outcome selects — including that `repair=True`
    does not exist when the experiment fails.
26. `section_polylines` against hand-computable fixtures: a plane through a cube
    yields one closed square contour with exact vertex coordinates; a plane
    through a two-component fixture yields two contours; a plane through a
    holed fixture yields an **open** contour flagged `open_section_contour` and
    is never closed; a missing plane yields `empty_section`.
27. Section determinism: identical polylines, in identical order, in two separate
    processes.
28. The §5.2 path end to end, **written as a real part script and run through
    the executor**: `import_mesh` → `section_polylines` → `loft_sections` →
    build123d `offset` / `thicken` / `fillet`, all succeeding on the authored
    solid, with the resulting part built and measured. Because the script runs
    in the sandbox, this clause also proves the terms are reachable: an
    unreachable name would fail it as a `NameError` at the offending line.
29. The injected surface is closed and **exactly** the documented set: the
    worker namespace's injected names equal
    `{import_step, import_mesh, import_point_cloud, mesh_to_solid,
    section_polylines, loft_sections}` plus the pre-existing §2 list, asserted
    as set equality so an undocumented addition fails the gate just as a missing
    one does. Paired with it: a part script naming `GeomAPI_PointsToBSpline`,
    `BRepBuilderAPI_Sewing`, `OCP`, or `trimesh` fails with the §8 build error at
    its own line, and `__import__` and `open` remain absent — so the closure of
    `script_contract.md:44-45` is **proven** at this stage rather than assumed
    while three new terms were added underneath it.
30. `mesh_derived_operation_refused` fires for each of offset, shell/thicken and
    fillet where a mesh-derived solid reaches them through the harness's own
    surfaces.
31. `heph lint` emits `mesh_derived_offset` for the single-assignment case and
    the test asserts the rule's documented limitation by including a defeating
    case that lint does **not** flag — the lint's reach is pinned, so it can
    never be read as a guarantee.
32. Sew-derived goldens carry an (image digest, OCCT version) provenance sidecar,
    and a clause asserts a mismatched pair invalidates them rather than comparing.
33. Tier 3 determinism binding: sewn face and vertex counts and the `IsValid()`
    verdict identical across two processes in the pinned image; the gate asserts
    **counts and verdict**, never sewn bytes.

### Gate G12C — scan scoring, surface, corpus

`uv run pytest tests/stage12c -q` exits 0, covering:

34. Direction A exactness: `scan_to_part_*` against an analytic target equals
    hand-computed distances to 1e-9 for a fixture whose true distances are known
    in closed form.
35. Direction B exactness: `part_to_scan_mean_mm` with method
    `kdtree_bound_exact_triangle` matches a brute-force all-triangle reference on
    a small fixture to 1e-9, proving the `d_v + L_max` candidate set is a sound
    superset.
36. `scan_neighborhood_overflow`: a pathological fixture with one enormous
    triangle abandons the refinement by name, populates
    `part_to_scan_upper_bound_mm` with method `vertex_nn_upper_bound`, leaves
    `part_to_scan_mean_mm` `None`, and the bound is asserted to be **≥** the true
    distance.
37. Record discipline: `ScanDistance` exposes no `iou` and no `chamfer_mm`
    attribute; `part_to_scan_mean_mm` and `part_to_scan_upper_bound_mm` are never
    both populated and never both absent.
38. `scan_iou_unavailable` fires where a caller asks for an IoU against a scan.
39. Alignment: `as_posed` and `declared` both produce records naming the mode,
    with the declared transform echoed and validated as rigid (orthonormal to
    1e-9, det +1) or refused; `principal` refuses `scan_principal_unavailable`
    on both a scan mesh and a point cloud.
40. `compare_solids` and `m.diff` refuse a `scan:` target with
    `scan_target_unsupported`, naming the replacement, and a byte-for-byte
    regression asserts every existing G8B `SolidDiff` record is unchanged.
41. `compare_to_scan` through dispatch on **both** profiles, with the scan's
    `canonical_hash` and the part's `artifact_ref` attributed in the response, and
    the confinement refusals intact on the tool path.
42. Tool-surface drift, asserted **relatively** so the clause is correct under
    either landing order (header): the tool-count pin in both places
    (`contract/tests/test_toolgen.py:98,109`,
    `tests/stage2/test_g2_contract_drift.py:354`) **increments by exactly one
    from the value the predecessor stage left it at** — the test reads the
    pre-stage value from the repository's own history rather than hard-coding a
    number — the two pins agree with each other, the regenerated artifact set is
    asserted against that same value, and all five generated artifacts
    regenerate deterministically.
43. `m.scan_diff` in a part-scope `CHECKS` predicate passing and failing on either
    side of its named threshold; the cross-part `checks/*.py` facade refuses a
    `scan:` target by name; the `scan:` target appears in the build's frozen
    inputs and a changed scan file changes the build.
44. `scan_timeout`: a fault-injected slow distance returns the named refusal
    carrying quality + bbox + whichever direction completed, and inside a
    predicate lands as `unverifiable` in the check report — not a pass, not a
    crash.
45. **Round-trip identity (§6.6)**: tessellate → export → `import_mesh` →
    compare to the original analytic solid, asserting `scan_to_part_max_mm ≤
    MESH_ROUNDTRIP_EPS_MM` (kernel precision, order `1e-3` mm, value from a
    recorded pinned-image measurement) — the tessellation nodes still lie on the
    surface they came from after export, unit scaling and welding. The clause is
    labelled in the test as a corruption check, **not** a fidelity check, and a
    negative control pins that: a fixture whose vertices are scaled by 1.001
    fails it. Also here: `tessellated_volume_mm3` strictly **below** the
    analytic volume and within `MESH_TESSELLATION_VOLUME_BIAS`, that constant
    from a recorded pinned-image measurement; and the two-process
    canonical-hash identity.
46. **Round-trip fidelity (§6.6)** — the clause that actually binds the
    declared deflection, and the one clause 45 structurally cannot be. On the
    same loop, `part_to_scan_max_mm` (samples on the analytic solid, measured
    against the imported mesh) lands inside the two-sided window
    `0.5 × LINEAR_DEFLECTION ≤ part_to_scan_max_mm ≤ 1.10 × LINEAR_DEFLECTION`,
    with `part_to_scan_method == "kdtree_bound_exact_triangle"` asserted
    **first** — a `vertex_nn_upper_bound` result fails the clause rather than
    satisfying it. Two negative controls pin both sides: a fixture tessellated at
    a deliberately coarser deflection exceeds the upper bound and fails, and a
    fixture whose mesh was replaced by the analytic solid's own dense
    re-tessellation falls under the lower bound and fails. `LINEAR_DEFLECTION`
    is read from `tessellate.py:52`, never copied, so a change to the pinned
    deflection moves the window with it.
47. Tier 2 determinism: identical `ScanDistance` records to 1e-9 across two
    processes, with identical sample counts and identical method strings; a
    differing method string fails the clause.
48. Reviewer context carries `MeshQuality`, `geometry_source` and `ScanDistance`
    with method fields intact, under the FakeModel harness; a mesh-derived
    `geometry_source` is surfaced and asserted **not** to produce a blocking
    finding.
49. `heph scan check` human and `--json`.
50. The `scan-*` corpus family: each task's two independent reference solutions
    pass its own acceptance through the engine path (Tier 1); the
    `scan_requirements` parser rejects a requirement that omits what its check
    needs (`VALIDATION.md:82-98`); corpus-count pins repointed with this stage
    cited.
51. The Tier 3 bench clause, following the split rule verbatim: **scan-prose and
    scan-seeded are each their own split, each baselined on its own first
    measurement with the reference model at ≥3 seeds, neither compared against
    nor averaged into the v1/v2 baselines**; the existing 0.70 prose bar keys on
    its own coverage constant and is not diluted; re-baselining any combined bar
    is its own explicit future amendment.

Existing suites stay green throughout; the geom/contract/core boundary tests keep
every seam clean at each sub-stage.

**Total: 51 gate clauses** (G12A 20, G12B 13, G12C 18). Every one is a pytest
assertion over a named field or a named refusal; a clause that cannot bind to a
field on a record declared above is a defect in this document, to be fixed by
adding the field (§12) or by tightening the clause — never by dropping it
(`mission_plan.md:801-804`).
