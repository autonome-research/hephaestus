# CADGenBench — ground-truth facts for the adapter

Recon date: 2026-07-28. Every fact below was read from the actual sources
(cloned repo, HF API, downloaded samples), not from documentation summaries.

## Provenance / pinning

| Thing | Value |
|---|---|
| Code repo | `https://github.com/huggingface/cadgenbench` |
| Repo commit at recon | `8ae143221935ecece1d3d4b5141f3afa4e915988` (2026-06-27) |
| Package name / version | `cadgenbench` 0.1.0, requires Python `>=3.12` |
| Code license | **Apache-2.0** |
| Inputs dataset | `HuggingAI4Engineering/cadgenbench-data` (public, not gated) |
| Inputs dataset sha at recon | `f76f965585817c621d6ea0d150d745adf670e66e` (lastModified 2026-06-08) |
| Data license | **ODC-BY** (Open Data Commons Attribution 1.0). Geometry sourced from Mecado — attribution required. |
| GT dataset | `HuggingAI4Engineering/cadgenbench-data-gt` — **private**, only the Space reads it. Do not plan on local scoring. |
| Leaderboard Space | `HuggingAI4Engineering/CADGenBench` (public, docker SDK) |
| Submissions dataset | `HuggingAI4Engineering/cadgenbench-submissions` |

Console entry points: `cadgenbench` and the alias `cgb` (both →
`cadgenbench.cli:main`).

## Dataset layout (verified against the real file list, 360 files)

Snapshot root **is** the fixtures root: each top-level entry is a sample
directory named by a numeric id. Root also holds three non-sample files:

```
.gitattributes
README.md
sanity_check_submission.py
```

**81 samples total** — 49 generation, 32 editing.

- Generation ids: `101`–`143`, `145`–`150`. Note **`144` does not exist** —
  do not assume a contiguous range.
- Editing ids: `201 202 203 204 205 206 207 208 209 211 212 214 215 217 218
  224 225 229 230 231 238 240 241 242 243 244 245 246 247 248 249 250`
  (also non-contiguous: 210, 213, 216, 219–223, 226–228, 232–237, 239 absent).

Never hardcode the id list; enumerate directories from the snapshot.

### Generation sample (46 dirs, exactly these two files)

```
<id>/
├── description.yaml
└── input.png
```

Exactly three generation samples ship a second drawing (`input2.png`):
**`127`, `134`, `145`**. No sample has an `input3.png`. Still drive off
`input_files` rather than hardcoding. Verified real:
`101/input.png` is `PNG image data, 3072 x 2118, 8-bit/color RGBA`. Drawings
are large (824 KB for 101).

### Editing sample (all 32 dirs, exactly these eight files)

```
<id>/
├── description.yaml
├── edit_description.txt      # the instruction, plain text, no trailing newline
├── input.step                # the starting solid (ISO-10303-21, AP214, OCC 7.8 export)
├── input.mesh.npz            # trusted watertight mesh sidecar for input.step
└── renders/
    ├── front.png
    ├── iso.png
    ├── right.png
    └── top.png
```

- `input.step` is large: **2.8 MB** for sample 201.
- `input.mesh.npz` is a numpy `.npz` with exactly three arrays:
  `vertices.npy`, `triangles.npy`, `linear_deflection_mm.npy`.
- `renders/*.png` are `1024 x 768` RGB. Render view names are exactly
  `iso`, `front`, `top`, `right`.

## `description.yaml` schema — exact keys

Only four keys exist. Verified from `_discover_fixtures`
(`baseline/_cli.py:255`), `_load_description`
(`eval/report/single_run.py:167`), `_read_task_type`
(`eval/run_summary.py:196`), and the dataset README's field table.

| Key | Type | Required? | Notes |
|---|---|---|---|
| `description` | string | yes | The task prompt. Authored as a YAML folded block (`>`), so it arrives with a **trailing newline** — `.strip()` it. |
| `task_type` | `"generation"` \| `"editing"` | **no** | **Absent on generation samples.** Readers default to `"generation"`: `str(data.get("task_type") or "generation")`. |
| `input_files` | list[str] | yes in practice | Filenames relative to the sample dir. |
| `input_type` | `"text+image"` \| `"text+step"` | yes in practice | Modality label; nothing in the grader branches on it. |

Runtime-only keys the CLI injects into the parsed dict (never in the YAML
on disk): `name`, `_inputs_dir`, `_gt_dir`.

Real files, byte-exact:

`101/description.yaml` (generation — note **no `task_type`**):
```yaml
description: >
  Reproduce the geometry as accurately as possible from the drawing.

input_files:
  - input.png

input_type: text+image
```

`127/description.yaml` (multi-image generation — "drawing**s**"):
```yaml
description: >
  Reproduce the geometry as accurately as possible from the drawings.

input_files:
  - input.png
  - input2.png

input_type: text+image
```

`201/description.yaml` (editing):
```yaml
description: >
  For each of the four non-circular pockets on the +X side of the central bore, bring their walls (faces with long axis along Y) inward by 6mm.

task_type: editing
input_files:
  - input.step

input_type: text+step
```

**Where the instruction lives.** For generation, the entire prompt is the
boilerplate `description` ("Reproduce the geometry as accurately as possible
from the drawing.") — all real information is in `input.png`. For editing,
the real instruction is the `description` field, and `edit_description.txt`
holds the **same** text verbatim (201's `edit_description.txt` is byte-identical
to the folded `description`, minus the newline). Read `description.yaml` as the
source of truth; `edit_description.txt` is a convenience duplicate.

## Submission contract

### Per-sample output

One directory per sample, containing exactly one candidate file:

```
<sample_id>/output.step        # or output.stp
```

Accepted candidate names, in this priority order (constant `_CANDIDATE_NAMES`,
identical in `baseline/package.py`, `baseline/types.py`, `eval/evaluate.py`,
and the Space's `submit.py`):

```python
("output.step", "output.stp")
```

Nothing else is required or read: no description, no metadata, no sub-volumes,
no renders. Extra files inside a sample folder are ignored by the grader.

A sample folder **may** omit its candidate — the evaluator records
`status: "missing"` and `cad_score = 0`. That is a legal submission, not a
rejection. The folder must still exist.

The contract is task-agnostic: editing samples write `output.step` exactly like
generation samples (not a patched `input.step` under a different name).

### Submission ZIP layout

```
submission.zip
├── meta.json                  # top level, at the ZIP root
├── 101/
│   └── output.step
├── 102/
│   └── output.step
├── ...
└── 250/
    └── output.step
```

**No wrapper directory.** The Space extracts the ZIP and takes
`{p.name for p in unpacked.iterdir() if p.is_dir()}` as the sample set — a
single top-level folder wrapping everything fails validation as
`unexpected folder(s): <wrapper>` plus 81 `missing sample(s)`.

The reference packager (`baseline/package.py`) also writes an explicit
directory entry `f"{sample}/"` for every sample so that candidate-less folders
survive extraction. Emit those directory entries; an empty folder that
disappears becomes a "missing sample" rejection rather than a scored zero.

### `meta.json` — exact schema

`REQUIRED_META_KEYS` in the Space's `submit.py` (lines 130–136), mirrored in
`baseline/package.py`. All five keys must be **present**:

```json
{
  "submitter_name": "Your Name",
  "submission_name": "My agent v1",
  "agent_url": null,
  "notes": null,
  "agree_to_publish": true
}
```

| Key | Validation (`_load_and_validate_meta`) |
|---|---|
| `submitter_name` | must be a **non-empty** string (`.strip()` non-empty) |
| `submission_name` | must be a **non-empty** string |
| `agent_url` | string **or `null`** — the key must exist even when null |
| `notes` | string or `null`; if a string, newlines/tabs collapse to spaces, stripped, and must be **≤ 500 chars** (`NOTES_MAX_CHARS`) after normalization |
| `agree_to_publish` | must be the **literal JSON boolean `true`**. `"true"`, `1`, and truthy values are all rejected (`is not True`). This is the sole consent gate; there is no separate UI checkbox. |

`meta.json` must be a JSON **object** at the top level and parse as valid JSON.

## Server-side validation gates, in order

From `submit.py` module docstring and `handle_submit`:

1. **Form**: a file was attached.
2. **ZIP safety** (`_extract_zip`): parseable as a zip; **no absolute paths**;
   **no `..` components**; **no symlinks** (unix mode `0o120000` in the high 16
   bits of `external_attr`). Any violation → hard reject with the offending
   filename. `BadZipFile` → "Upload is not a valid zip file".
3. **`meta.json` schema**: as tabulated above.
4. **Sample-set match** (`_validate_fixture_set`): the set of top-level
   directories in the ZIP must **exactly equal** the set of sample directories
   in `data_inputs_dir()`. Both missing and extra folders are fatal:
   `"Sample set does not match the dataset. missing sample(s): …; unexpected
   folder(s): …."` **You must submit all 81 folders**, even for samples you did
   not solve.
5. **Candidate presence** (`_validate_candidates_parseable`): deliberately
   cheap — presence + non-zero size only. It does **not** OCC-parse candidates
   at submit time (that was removed as slow/OOM-prone). An empty or malformed
   STEP passes submit and scores 0 at eval. A missing candidate logs nothing
   fatal.

Duplicate detection: the Space computes the ZIP's sha256
(`_compute_sha256`) and looks up an existing submission with the same hash
(`_find_existing_submission_by_sha256`) — resubmitting a byte-identical ZIP
will not produce a fresh row.

Submission id is minted as `f"{slug(submitter_name)}_{slug(submission_name)}_{ts}"`
with a 40-char slug cap.

## `sanity_check_submission.py`

**Location**: root of the `cadgenbench-data` dataset (NOT in the GitHub repo).
Download at
`https://huggingface.co/datasets/HuggingAI4Engineering/cadgenbench-data/resolve/main/sanity_check_submission.py`.

**Invocation** (one candidate STEP at a time — it is not a whole-ZIP checker):

```bash
python sanity_check_submission.py path/to/output.step [--quiet]
```

Or, resolving the snapshot path the documented way:

```bash
DATA=$(python -c 'from cadgenbench.common.paths import data_inputs_dir; print(data_inputs_dir())')
python "$DATA/sanity_check_submission.py" path/to/output.step
```

**Hard dependency**: it does `from cadgenbench.common.validity import analyze_step`
and `from cadgenbench.common.mesh import deflection_for_bbox`. It therefore
requires the `cadgenbench` package installed (which pulls build123d ≥0.10,
cadquery-ocp, trimesh, manifold3d, numpy, scipy, open3d, Pillow, pyyaml,
pyvista, huggingface_hub — Python 3.12+). There is no lightweight path.

**Exit codes and output** (verified from the actual script):

| Exit | Condition | Stream |
|---|---|---|
| `2` | file does not exist → `ERROR: file not found: <path>` | stderr |
| `1` | STEP load raised → `FAIL  STEP load failed: <exc>` | stderr |
| `1` | `is_valid == False` → `FAIL  <name>: is_valid=False  watertight=<bool>` followed by up to **10** `      - <err>` topology-error lines, then `      ... and N more` | stderr |
| `0` | valid; prints a `PASS  <name>: is_valid=True watertight=True` block with solids/shells/faces, volume, bbox, `defl_used` — suppressed by `--quiet` | stdout |

## Validity gate (the thing that zeroes a score)

`is_valid` is True **iff all three** hold (`common/validity.py`):

1. `BRepCheck_Analyzer.IsValid()` reports no per-face/edge/vertex topology
   errors over the whole shape.
2. Every shell is closed — watertight, no naked/free edges. A non-watertight
   shape is never valid.
3. The boundary tessellates into a clean **closed orientable manifold** (every
   edge in exactly two triangles with opposite orientations).

`topology_errors` is a de-duplicated tuple of human-readable strings, e.g.
`"Face: BRepCheck_SelfIntersectingWire"`, `"BREP not watertight: open shells /
naked edges"`, `"mesh non-manifold: edge (220, 243) shared by 4 triangles"`.

**Resource ceilings** (env-overridable, applied identically to GT and
submissions; tripping one marks the part invalid):

| Constant | Default | Env var |
|---|---|---|
| `MAX_TRIANGLES` | `1_000_000` | `CADGENBENCH_MAX_TRIANGLES` |
| `MAX_STEP_FILE_BYTES` | `50_000_000` (50 MB) | `CADGENBENCH_MAX_STEP_FILE_BYTES` |
| `MESH_TIMEOUT_S` | `180.0` s per mesh, process-killed, **no retry** | `CADGENBENCH_MESH_TIMEOUT_S` (≤0 disables process isolation) |

## Scoring (for calibration, not something we implement)

Gate: invalid → `cad_score = 0`.

```
generation: cad_score = 0.4·shape + 0.4·interface + 0.2·topology
editing:    cad_score = 0.6·s_renorm + 0.3·interface + 0.1·topology
            s_renorm = max(0, (shape - b_shape) / (1 - b_shape))
```

`b_shape` is the no-op baseline `shape_similarity(input.step, GT)`, precomputed
into the private GT as `<sample>/edit_baseline.json`; **the presence of that
file is how the grader decides a sample is an editing task** (not
`description.yaml`). A no-op edit caps at `0.3 + 0.1 = 0.4`.

Axes that are absent (e.g. a sample with no jig sub-volumes → no interface
score) drop out and the remaining weights **renormalize** rather than diluting
the mean (`_cad_score`, `evaluate.py:368`).

Alignment before scoring is rotation + translation only, never scale: identity
plus the 24 octahedral PCA orientations, refined with Open3D multi-scale
point-to-plane ICP, selected by bidirectional F1 / capped symmetric Chamfer /
RMSE with a deterministic tie-break.

**Canonical pose (recommended, reduces symmetric-part alignment ambiguity):**
1. bbox centre at origin `(0,0,0)`;
2. bbox extents ordered `Lx ≥ Ly ≥ Lz` (longest along X, shortest along Z);
3. natural mounting face on the `z = -Lz/2` plane, outward normal along `-Z`.

## Result JSON (what comes back, for reference)

Per sample, `<sample>/result.json`:
`status` (`"valid"`|`"invalid"`|`"missing"`), `validation` (`is_valid`,
`is_watertight`, `solid_count`, `shell_count`, `face_count`, `volume`,
`bbox{x,y,z}`, `topology_errors`), `alignment{rmse}`, `gt_metrics`,
`shape_diagnostics`, optional `metric_errors`, optional `interface_metrics`,
`topology_metrics`, `edit_metrics` (editing only), `cad_score`.

Run level, `run_summary.json`: `aggregate_score`, `validity_rate`, `n_samples`,
`n_valid`, `n_invalid`, `n_missing`, `score_by_task_type`, `per_task_scores`,
`per_sample_scores`.

## Downloading the dataset

**Library path** (what `cadgenbench` itself does — `common/paths.py`):

```python
from huggingface_hub import snapshot_download
root = Path(snapshot_download(repo_id="HuggingAI4Engineering/cadgenbench-data",
                              repo_type="dataset"))
# root IS the samples root: each top-level dir is a sample
```

Resolution order in `data_inputs_dir()`, first match wins:
1. `$CADGENBENCH_DATA_REPO` set → `snapshot_download(repo_type="dataset")`;
2. `$CADGENBENCH_DATA_DIR` → a local dir containing `inputs/` and/or `gt/`;
3. `./data/` in the CWD, same layout.

Note the asymmetry: the **Hub** branch returns the snapshot root directly,
while the **local** branches return `<data_dir>/inputs`. `data_gt_dir()` is
the parallel helper using `$CADGENBENCH_DATA_GT_REPO` (private, needs
`HF_TOKEN`) or `<data_dir>/gt`; GT filename is `ground_truth.step`
(`GT_STEP_NAME`, `evaluate.py:109`), with jig sub-volumes named
`jig_<context_id>__<index>__<fit_type>.step` where fit type is `KOR`
(keep-out) or `KIR` (keep-in).

**No-dependency HTTP path** (what this recon used — works without
`huggingface_hub` installed):

```
GET https://huggingface.co/api/datasets/HuggingAI4Engineering/cadgenbench-data
    → JSON with .siblings[].rfilename  (full file list, 360 entries)
GET https://huggingface.co/datasets/HuggingAI4Engineering/cadgenbench-data/resolve/main/<path>
    → the file bytes (follow redirects: curl -L)
```

Total dataset storage is ~218 MB (`usedStorage`), dominated by the 32
`input.step` + `input.mesh.npz` pairs and the 3072×2118 drawings.

## Gotchas the adapter must handle

1. **`task_type` is absent on generation samples** — default to `"generation"`,
   never `KeyError`.
2. **Sample ids are non-contiguous** — `144` and many 2xx ids are missing.
   Enumerate; never range().
3. **All 81 folders must be in the ZIP**, including unsolved ones, or the
   submission is rejected outright rather than partially scored.
4. **No wrapper directory** in the ZIP; `meta.json` sits at the root.
5. **`agree_to_publish` must be literal `true`**, not `"true"`.
6. **`agent_url` and `notes` keys must exist** even when their value is `null`.
7. **Multi-image generation samples** (`input2.png`) — drive off `input_files`,
   not a hardcoded `input.png`.
8. `description` comes from a YAML folded block → trailing newline; strip it.
9. `sanity_check_submission.py` checks **one STEP**, not a ZIP, and needs the
   full `cadgenbench` install (OCC stack).
10. Editing candidates are still written as `output.step` — not a modified
    `input.step`.
11. `notes` cap is 500 chars **after** whitespace normalization.
12. Local scoring is impossible: GT is private. Only the Space produces a
    `cad_score`. Any local gate we build is a validity pre-check only.

## Attribution obligation

Data is ODC-BY; CAD geometry sourced from **Mecado** (https://www.mecado.com).
Any redistribution or derived artifact must carry attribution to the
CADGenBench team (HuggingAI4Engineering) and Mecado. Code reused from the
GitHub repo is Apache-2.0 and needs the license header / NOTICE treatment.
