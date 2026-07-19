# 01 — Part-Script Contract

The contract every Hephaestus part script is written against, and the contract
the executor MUST implement. It is deliberately source-compatible with the two
recovered Smith scripts (`cat_step_shelf`, `cat_step_gusset`) except where
noted EXTENSION; those scripts are held as private CI fixtures (see
`05-repo-conventions.md`) fetched into `corpus/reference/` and MUST execute
under this contract unmodified (Stage 0 gate).

## 1. Execution model

A part script is a Python module executed top-to-bottom, statement by
statement, in a namespace pre-populated by the executor. There are no imports
in part scripts; the injected namespace is the entire API surface. The script
communicates its output by assigning to `part.*`.

## 2. Injected namespace

- **build123d, complete.** Everything from `from build123d import *`:
  `Box`, `Polyline`, `make_face`, `extrude`, `fillet`, `chamfer`, `Pos`,
  `Rot`, `Plane`, `Axis`, `Align`, `Color`, `Compound`, selectors
  (`.faces()`, `.edges()`, `.sort_by()`, `.filter_by()`), booleans via
  `+ - &`, joints, etc. Hephaestus does not wrap or rename build123d.
- **`math`** (observed in use: `math.sqrt`, `math.degrees`, `math.atan2`).
- **`Param`, `PARAMS`, `p`** — bounded parameters (§3).
- **`hc`** — project-shared constants (§4).
- **`part`** — the output object (§5).
- **`tag`** — topology tagging (§5.3).
- **`check`, `CHECKS`** — EXTENSION, persistent assertions (§6).
- Nothing else. `open`, `__import__`, filesystem and network access are
  absent; attempting them is a build error.

## 3. Parameters

```python
PARAMS = {
    "groove_count":     Param(5,   min=2,   max=10),
    "groove_width":     Param(3.0, min=2,   max=6),
    "brace_slot_clear": Param(0.3, min=0.0, max=0.8),
}
```

`Param(default, min=..., max=..., doc="", step=None)` declares a bounded
numeric parameter (`doc`/`step` are EXTENSIONs; Smith's observed form is
positional default + min + max). `p.<name>` reads the effective value:
default unless overridden by the build request (CLI `--param`, tool
`set_params`, or a client slider). The executor MUST validate overrides
against bounds and reject out-of-range values with a build error naming the
parameter. `PARAMS` MUST appear before first use of `p`; the executor
publishes the dict so clients can generate controls (this is what Smith's
"Globals" sliders are).

Integer-valued defaults declare integer params; float defaults declare floats.

## 4. Project-shared namespace: `hc`

`globals.py` at the project root defines the project-shared namespace; every
part script sees its public names as attributes of `hc` (read-only from
parts). Observed usage crossing part boundaries: `hc.shelf_d`, `hc.shelf_w`,
`hc.hex_half_width`, `hc.tab_w`, `hc.tab_depth`, `hc.ply_t`,
`hc.gusset_joint_z`, `hc.brace_x_offset`. This is the mechanism by which
mating parts agree on interface dimensions (mortise positions, sheet
thickness) without duplicating numbers.

`globals.py` contains two kinds of names:

- **Project parameters.** `globals.py` MAY declare its own `PARAMS` dict with
  the same `Param(default, min=..., max=...)` form as parts (§3). These are
  the user-tunable, bounds-validated, slider-generating knobs of the whole
  design — observed in Smith as "the Globals" (its agent offers the 220 mm
  rise and 250×200 shelf size as changeable "via the Globals"). Effective
  values are readable inside `globals.py` as `p.<name>` and from parts as
  `hc.<name>`; overrides live at project level (`hephaestus.toml` `[params]`,
  CLI `--global-param`, `set_params(scope="project")`).
- **Derived constants.** Plain assignments, computed freely from project
  params and `math` (`hex_half_width = shelf_w / 2 + ply_t`, …). Not
  independently tunable; they change when the params they derive from change.

`globals.py` executes under the injected namespace minus `part` (it declares
values, not geometry). Dependency tracking — EXTENSION: the executor records
which `hc` names each part reads; changing a project param or editing
`globals.py` marks exactly the consuming parts dirty, and `heph build
--stale` rebuilds them. Part-level `PARAMS` (§3) remain for knobs meaningful
to one part only; a part MUST NOT shadow an `hc` name in its own `PARAMS`
(lint error), so every tunable has exactly one home.

Naming: `hc` is retained for source compatibility ("harness constants").

## 5. Part output object

### 5.1 Geometry

```python
part.geometry = Compound(children=[shelf_a, shelf_b, *corner_splines, collar])
```

Required. A single shape or a `Compound`. Child `.label` strings become the
geometry-tree row names (observed: 25 labeled geometries listed in Results);
unlabeled children get the binding name from the source map, prefixed `_` if
the binding was underscore-private (observed: `_placed_spline`). `.color`
renders in rgb views.

### 5.2 Manufacturing metadata

String-valued fields, all optional, schema'd for lint but free-text valued
(observed set, verbatim from the recovered scripts):

```python
part.description       # "Laser-cut laminated hexagonal cat cubby shell…"
part.material_spec     # "Three laminations of 6 mm Baltic birch plywood, BB/BB grade"
part.process           # "laser_cut"  (registry-known values enable DFM packs)
part.stock_form        # "sheet"
part.blank_size        # "Three 210 x 125 x 6 mm nested profiles"
part.general_tolerance # "+/-0.25 mm cut profile; tabs -0.15 mm per side"
part.finish            # "Lightly sand laser char; clear water-based poly (pet-safe)"
part.assembly_method   # "PVA-laminate each face first; register the six faces…"
part.joint             # "PVA-laminated beam; each ply has two top tabs…"
```

`part.process` values that match a DFM registry pack (`laser_cut`,
`cnc_router`, `fdm`, …) make that pack's rules runnable against the part.

### 5.3 Topology tags and per-feature metadata

```python
tag(outer_top_panel.faces().sort_by(Axis.Z)[-1], "tread_top")
part.feature("tread_top").surface_finish = (
    "Outer ply through-slots expose middle ply as 6 mm deep anti-slip recesses"
)
```

`tag(topology, name)` attaches a stable semantic name to a face/edge/solid.
Tags are the join key for: per-feature metadata (`part.feature(name).*`),
measurement tools (`measure(part, "tread_top", …)`), face-mode mask renders,
selection resolution, and checks. The executor records tag → (solid, topology
index, creating statement) in the source map.

Tags are *recomputed by re-running the tagging statement's selector* on each
build, not persisted by topological id. This avoids the classical
topological-naming problem's hard failure (dangling references) but inherits
its soft failure: after an edit, a selector like
`.faces().sort_by(Axis.Z)[-1]` resolves successfully yet may select a
*different* face, and nothing in the resolution itself detects the drift.
The executor therefore fingerprints every tagged topology at build time
(area, centroid, unit normal for faces; length and midpoint for edges) and
stores fingerprints in the build artifact; on rebuild it compares against the
previous fingerprint and emits a `tag_drift` warning when the tag's identity
moved beyond tolerance while its selector still resolved (default: centroid
moved > 1 mm or normal rotated > 5° *more than the geometry change itself
explains* — implemented as: drift is warned when the tagged face's
fingerprint changed but the part's overall bbox/volume delta is below the
same proportional threshold). Warnings surface in the build result, Results
panel, and the agent's context; skills packs teach selectors that survive
edits (filter by normal + position window rather than bare sort-order
indexing).

## 6. Persistent checks — EXTENSION

```python
CHECKS = {
    "splines_clear_middle_panels": lambda m: m.interference(
        "corner_splines", "middle_top_panel") == approx(0, abs=1e-6),
    "envelope": lambda m: m.bbox("part") <= (380.5, 280.5, 250.5),
    "manifold": lambda m: m.sealed("part") and m.genus("part") == 0,
    "one_cat_static": lambda m: m.mass("part") <= 6.0e3,  # grams
}
```

`CHECKS` maps names to predicates over a measurement facade `m` bound to the
built geometry (backed by core kernel services; full facade API in
`02-tool-schema.md` §measure). Checks run on every build of the part and on
`heph check` project-wide; results are part of the build artifact and surface
in Results, CI, and the agent's context. A failing check does not abort the
build; it fails the report. Cross-part checks live in `checks/*.py` with the
same shape but a facade that can address any part.

This is the load-bearing difference from the reference product: Smith's
`Measure Overlap` verifies once, in-loop, and the evidence evaporates;
Hephaestus checks are artifacts with history.

## 7. Geometry addressing

One selector grammar is used everywhere a string names geometry — `CHECKS`
predicates, the `measure`/`inspect_part(focus=…)` tools, cross-part checks,
and DFM findings. Resolution rules, in precedence order within a part:

1. `"part"` — the part's full `part.geometry` compound.
2. A **tag** name (§5.3) — the tagged topology.
3. A **geometry label** — a `.label` string of any node in the geometry tree.
   Duplicate labels are deterministically deduplicated in tree order with
   `#2`, `#3`, … suffixes (observed in Smith's Results: `corner_splines`,
   `corner_splines#2` … `#5`); the bare name addresses the first, `name#k`
   the k-th, and `name#*` the fused compound of all of them.
4. A **binding name** from the source map — the shape (or, for a list binding
   such as `corner_splines = []` accumulated in a loop, the fused compound of
   its members; `name#k` selects the k-th element in append order).

A name matching more than one rule at the same level, or a name resolving to
nothing, is an addressing error whose message lists the candidates /
near-misses — never a silent guess. Cross-part addressing prefixes the part:
`"cat_step_gusset/center_lamination"`. Nested compounds flatten for label
lookup; a label on a compound addresses the whole subtree. The build result's
`geometries` array is exactly the resolvable label set, so what the user sees
in the Results tree and what the agent can measure are the same namespace by
construction.

## 8. Build result

Machine-readable (JSON) and rendered-for-model (text) forms of the same
record:

```
{
  "part": "cat_step_shelf",
  "status": "ok" | "failed",
  "metrics": { "solids": 25, "faces": 438, "bbox_mm": [380.0, 280.0, 250.0],
               "volume_mm3": ..., "sealed": true, "genus": 0 },
  "checks": { "splines_clear_middle_panels": {"pass": true, "measured": 0.0}, … },
  "geometries": [ {"label": "outer_top_panel", "solids": 1, …}, … ],
  "params": { "groove_count": 5, … },
  "source_map": ".heph/cat_step_shelf/srcmap.json",
  "warnings": [ {"kind": "tag_drift", "tag": "tread_top", "detail": "…"} ],
  "error": null | {
      "line": 46, "col": 14, "type": "ValueError",
      "message": "Failed creating a fillet with radius of 6, try a smaller value or use max_fillet() to find the largest valid fillet radius",
      "frame": ["44 | tread_shelf = slotted_shelf - groove_cutter", "45 |", "> 46 | tread_shelf = fillet(…)", …],
      "built_through": {"line": 44, "statement": "tread_shelf = slotted_shelf - groove_cutter"},
      "last_good": { "bodies": 1, "solids": 1, "size_mm": [250.0, 200.0, 18.0],
                     "volume_mm3": 868892.28, "sealed": true, "genus": 0 },
      "hint": "inspect_part(name, last_good=true) renders this snapshot"
  }
}
```

The failed-build text rendering MUST carry the same fields as the captured
Smith error (line/col, type, source frame, built-through statement, last-good
metrics, inspect hint) — that error shape is demonstrably sufficient for an
agent to self-repair, and Stage 0 acceptance-tests our rendering against it.

## 9. Style conventions (lint, not law)

Recovered scripts show a consistent idiom the skills packs will teach and the
linter will nudge toward: module-scope constants prefixed `_`
(`_layer_t = 6.0`), profile-then-extrude construction, comments explaining
manufacturing intent rather than code mechanics, colors assigned per
lamination/role, and `part.*` metadata as the final block. `heph lint` warns
on: geometry unreachable from `part.geometry`, unlabeled multi-solid
compounds, params never read, tags never referenced, and missing
`description`/`process`.
