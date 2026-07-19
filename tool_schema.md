# 02 — Agent Tool Schema

The tool surface exposed to the model by agent/, and over MCP by server/. One
definition, rendered per model adapter and per MCP. Names are snake_case
(matching the observed real API name `inspect_part` in Smith's error hint).
Every tool returns the machine-readable form plus a model-oriented text
rendering; image-bearing tools return images inline.

Conventions: `part` arguments are part names (script stem). Tolerances in mm.
All tools are safe to retry; none are destructive except `edit_part` and
`set_params`, which are git-recoverable.

## Geometry lifecycle

### create_part
```
create_part(name: str, template: "blank"|"sheet"|"solid"|"from_store" = "blank",
            description: str = "") -> {path, initial_script}
```
Creates `parts/<name>.py` from a template and registers an agent context for
it. Observed equivalent: `Create cat_step_shelf (part)`.

### read_part
```
read_part(name: str, numbered: bool = true) -> {script, params, line_count}
```
Returns the current script with line numbers (edit anchors).

### edit_part
```
edit_part(name: str, old_str: str, new_str: str) -> {applied, diff, line}
```
Exact-match string replacement; `old_str` must match exactly once (widen with
context if ambiguous — same contract as claude-code-style editors, and
consistent with the unified diffs observed in Smith's Edit chips). A failed
match returns the closest candidates. Multiple edits = multiple calls.
`write_part(name, script)` exists for whole-file rewrites and template
replacement.

### build_part
```
build_part(name: str, params: dict = {}) -> BuildResult
```
Runs the incremental executor (contract in `01-script-contract.md` §7).
Always re-runs the part's CHECKS and reports them. Observed equivalent:
`Build cat_step — success`, `Build wood_screw — 438 faces`, and the captured
failure with last-good stats.

### set_params
```
set_params(values: dict, scope: "part"|"project" = "part", name: str|null = null)
    -> {effective, rejected, stale_parts}
```
Persists parameter overrides (bounds-validated) for a part or for the
project-level Globals in `globals.py` (contract §4). Rejected values return
the violated bound; project-scope changes return the list of parts marked
stale by dependency tracking.

## Grounded observation

### inspect_part
```
inspect_part(name: str, views: list[str] = ["iso", "+X"],
             channel: "rgb"|"mask"|"section" = "rgb",
             section_plane: str|null = null,
             explode: float = 0.0,
             last_good: bool = false,
             focus: str|null = null) -> {images: [...], mask_legend?}
```
Renders the current (or last-good) build. `views` accepts named cameras or
`"az45_el30"`. `channel="mask"` returns the id-color legend mapping every
solid (or tagged face, with `focus`) to its palette color, so the model can
name what it sees. `focus` centers and zooms on a labeled solid or tag.
Observed equivalent: `Inspect cat_step — mask, 2 views` with `iso`/`+X`
thumbnails, and the `last_good` behavior from the error hint.

### query_snapshot
```
query_snapshot(name: str, question: str, views: list[str] = [...]) -> {answer, images}
```
Runs a vision sub-query against fresh renders without growing the main
context (a scoped look-and-answer). Observed equivalent: `Query Build
Snapshot`.

## Measurement (the `m` facade from CHECKS, exposed as tools)

### measure
```
measure(kind: "interference"|"clearance"|"distance"|"bbox"|"volume"|"mass"|
              "sealed"|"genus",
        a: str, b: str|null = null, part: str|null = null) -> {value, units, detail}
```
`a`/`b` use the geometry addressing grammar of contract §7 (tags, labels
with `#k`/`#*` dedup selectors, binding names, `"part"`, and
`"<part>/<label>"` cross-part); addressing errors list candidates rather
than guessing. `interference` returns overlap volume with
per-pair breakdown (observed equivalent: `Measure Overlap`); `clearance`
returns minimum separation; `distance` measures between tagged topology.

### run_checks
```
run_checks(scope: "part"|"project" = "part", name: str|null = null) -> CheckReport
```
Re-runs persistent CHECKS (and cross-part checks for project scope).

### run_dfm
```
run_dfm(name: str, process: str|null = null) -> DfmReport
```
Runs the DFM rule pack matching `part.process` (or an explicit process)
against the geometry + material. Findings carry rule id, severity, offending
topology reference (tag/mask id), and suggested bound. Powers the DFM mode
toggle: when the mode is on, the harness auto-runs this after each successful
build and injects findings.

## Knowledge and registries

### load_skill
```
load_skill(name: str) -> {content}
list_skills() -> [{name, summary, tokens}]
```
Loads a markdown skill pack into context, wrapped in provenance-marked
delimiters; skill text is reference material, never instructions (threat
model, architecture §7). Observed equivalent: `Load Skill`.

### search_parts_store
```
search_parts_store(query: str, max_results: int = 5) -> [{id, name, params, preview}]
instance_store_part(id: str, params: dict, pos: dict|null) -> {script_fragment}
```
Searches parametric generators (standard hardware) and returns a script
fragment that instances one (observed flow: Search Store → M5 wood screw →
placed in the shelf script). Store generators are part scripts: they execute
only under the standard sandbox and injected-namespace whitelist, with no
additional capabilities, and resolve from hash-pinned registries.

### search_materials
```
search_materials(query: str) -> [{id, name, density, forms, thicknesses, notes}]
```
Observed equivalent: `Search Materials` returning a Baltic birch record.

## Interaction

### ask_user
```
ask_user(question: str, options: list[str], allow_free_text: bool = true,
         multi: bool = false) -> {selection}
```
Structured question; suspends the loop until answered. Observed equivalent:
`Ask question (4)` with the honeycomb-direction fork.

## Output

### export_part
```
export_part(name: str, format: "step"|"dxf"|"svg"|"gltf"|"3mf"|"stl",
            target: str|null = null, layout: "as_built"|"nested_sheet" = "as_built")
    -> {path(s)}
```
STEP for interchange (observed Smith ceiling); DXF/SVG per-lamination
profiles with `nested_sheet` layout for laser/CNC workflows (each 6 mm
lamination as a flat profile, kerf-aware nesting is a Stage 6 stretch); 3MF/
STL for printing; GLTF for clients. Exceeding STEP-only is a deliberate
differentiator — the recovered scripts describe laser-cut parts whose real
manufacturing input is DXF.

### generate_drawing
```
generate_drawing(name: str, kind: "dimensioned"|"assembly"|"exploded",
                 sheet: "A4"|"A3"|"letter" = "A4") -> {pdf, svg}
```
Projection-based 2D drawings from the same geometry (build123d supports
projection; title block from part metadata). Covers the Docs tree section
(user hypothesis: docs are md/drawings generated from the same scripting —
adopted).

### generate_doc
```
generate_doc(name: str, kind: "bom"|"assembly_instructions"|"spec") -> {markdown}
```
Text docs synthesized from part metadata, params, checks, and renders.

## Deferred (schema reserved, not in mission scope until Stage 6+)

`run_fea(name, load_spec)` — static FEA via CalculiX with loads on tagged
faces (Smith volunteers "static FEA … ~15 kg dynamic"; we reserve the slot).
`import_geometry(path)` — STEP import into a project (`Imports` tree section).
