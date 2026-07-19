# 02 — Agent Tool Schema

The tool surface exposed to Pi by `agent/`, over MCP by `server/`, and through
the Python bridge. One language-neutral JSON Schema contract is generated from
the typed Python declaration and committed; generated Pi TypeBox definitions,
FastMCP declarations, this document, and bridge validators MUST match it in CI.
Provider-specific schemas are Pi's responsibility, not a Hephaestus adapter
layer. Names are snake_case (matching the observed real API name
`inspect_part` in Smith's error hint). Every tool returns the machine-readable
form plus a model-oriented text rendering; image-bearing tools return Pi image
content inline and stable artifact references to other clients.

Pi's built-in coding tools are disabled in the product runtime. The tools below
are trusted TypeScript proxies that validate inputs, send versioned requests to
the Python bridge, and validate outputs before returning them to the model.
Registry reference content is returned inside explicit provenance delimiters;
it is never installed as an ambient Pi extension or privileged skill.

Conventions: `part` and new-part `name` arguments are normalized identifiers
matching `^[a-z][a-z0-9_]{0,63}$`; separators, absolute paths, `..`, Unicode
lookalike separators, and encoded traversal are rejected before filesystem
access. Every model-selected output path is relative to a declared project
root (exports use `.heph/exports/`) and rejected on traversal. Confinement is
rechecked at operation time through directory descriptors with no-follow/
beneath semantics (`openat2 RESOLVE_BENEATH|RESOLVE_NO_SYMLINKS` on secure
Linux, an equivalently tested primitive elsewhere); final creation uses atomic
no-replace semantics. Preflight path resolution alone is never trusted, so a
racing parent symlink cannot redirect a write. Writes are atomic; an existing
file is not overwritten unless that tool's contract explicitly provides a matching
base-content hash or idempotent content-addressed replacement. Every read/write snapshot is content-addressed; every accepted overwrite
journals its exact preimage under `.heph/journal/` before mutation. Committed
bytes are recoverable from git, overwritten dirty bytes from that journal, and
rejected contender bytes from the `attempted_snapshot_ref` in the conflict.

Source/config/output mutations carry an idempotency key in trusted invocation
metadata, not in model-visible arguments. The Pi proxy derives it from stable
session UUID + persisted assistant-message entry ID + tool-call ordinal +
provider tool-call ID. HTTP callers MUST send a UUIDv7 `Idempotency-Key`. MCP
callers MAY send `_meta["hephaestus.dev/idempotency-key"]`; otherwise the server
derives the key from the authenticated/local MCP session plus canonical JSON-
RPC request-id type/value. Hephaestus advertises that mutating request IDs must
be unique within an MCP session: same-id/same-payload is a replay and same-id/
different-payload is rejected. Thus stock clients work, while clients needing
cross-request reconciliation use the optional `_meta` key.

The server normalizes every accepted key to a timestamp-prefixed, HMAC-bound
internal key: Pi uses the trusted persisted-entry timestamp; MCP-derived keys
use the server-recorded session start/receive time. On **first sight**, HTTP or
explicit-MCP UUIDv7 timestamps must be within five minutes of server time;
once recognized, the normalized key replays through the full 30-day horizon
without repeating the freshness check. Thus creation time
remains verifiable from the key after metadata GC. The Python store durably
caches normalized key + canonical payload hash + final outcome. The payload
hash covers protocol/schema version, project UUID, tool name, normalized target
identity, and canonical JSON arguments (sorted keys, normalized numbers and
Unicode, excluding invocation metadata). HMAC keys come from the durable
project keyring specified in architecture §3.5; operation rows record key IDs
and retired verification keys outlive the 30-day horizon plus 7-day safety
margin. Retrying the same key/payload returns that outcome after a lost response or restart; key
reuse with another payload is an error. The idempotency horizon is 30 days.
Full outcomes remain protected throughout the horizon, and older normalized
keys return `key_expired` without execution. After expiry, GC keeps a compact
key/payload/terminal-state/commit-hash tombstone for a 7-day safety margin and
may then remove it because the HMAC-verified embedded timestamp still rejects
execution. Clients reconcile uncertain completion with the same key. Read-only tools are freely retryable. Tolerances
are in mm. Mutating tools are `create_part`, `edit_part`, `write_part`,
`set_params`, `build_part`, and `export_part`; none may silently discard bytes.

Pi tool execution is parallel by default, but `ask_user`, `create_part`,
`edit_part`, `write_part`, `set_params`, `build_part`, and `export_part` MUST
declare sequential execution. Any future stateful or mutating tool does the
same. Read-only render and measurement calls MAY run concurrently against the
last completed artifact. A Hephaestus preflight hook inspects the complete
assistant tool-call message: if `ask_user` appears with any sibling stateful or
mutating call, every sibling is blocked with `ask_user_must_be_alone` while the
question proceeds. The model may issue mutations only in a later turn after the
answer, regardless of sibling source order.

**Model-context limits.** Independently of the larger bridge frame cap, each
text tool result sent to Pi is capped at 50 KiB and 2000 lines, measured both
on final UTF-8 `content[].text` and its JSON-escaped representation; paging
dynamically shortens chunks to satisfy both caps. The full value
is retained as a content-addressed local artifact and the result reports
`truncated`, byte/line counts, and an artifact/snapshot reference. Tools with
large model-readable content provide bounded paging; untrusted skill/reference
content is never silently truncated into a misleading success.

## Geometry lifecycle

### create_part
```
create_part(name: str,
            template: "blank"|"sheet"|"solid"|"from_store" = "blank",
            description: str = "")
    -> {path, initial_script, content_hash, snapshot_ref,
        part_param_state_hash, project_param_state_hash}
```
Creates `parts/<name>.py` from a template and registers an agent context for
it. It fails without mutation if the normalized name/path already exists.
Observed equivalent: `Create cat_step_shelf (part)`.

### read_part
```
read_part(name: str, offset_line: int = 1, limit_lines: int = 2000)
    -> {script, numbered_script, params, line_count, content_hash, snapshot_ref,
        part_param_state_hash, project_param_state_hash,
        truncated, next_offset_line?}
```
Returns separate raw and numbered chunks (the raw chunk is suitable for exact
edits), registers an immutable full-file content-addressed snapshot, and
returns the hashes/refs required for optimistic writes and exact conflict
reconstruction. `limit_lines` is bounded to 1–2000 and the 50 KiB result cap
may shorten a page with `next_offset_line`. Snapshot refs are bound to project
UUID, normalized part path, creating principal/session, and content hash;
`expected_hash` is accepted only with a matching authorized snapshot. Snapshots
are retained for at least 30 days and while referenced by a live operation,
conflict, journal, or pin; expired refs return `snapshot_expired` without
falling back to mutable path state. If one source line alone exceeds
50 KiB, `read_part` returns a bounded prefix with `oversized_line=true` and the
snapshot ref; the model continues losslessly by byte cursor through
`read_artifact` rather than receiving an over-cap line.

### edit_part
```
edit_part(name: str, expected_hash: str, old_str: str, new_str: str)
    -> {applied, diff?, line?, content_hash?, snapshot_ref?, journal_ref?,
        conflict?: {current_hash, current_script, current_truncated,
                    next_offset_line?, current_snapshot_ref,
                    base_snapshot_ref, attempted_snapshot_ref}}
```
Exact-match string replacement; `old_str` must match exactly once (widen with
context if ambiguous — same contract as claude-code-style editors, and
consistent with the unified diffs observed in Smith's Edit chips). The write
runs only when `expected_hash` equals the current content hash. The store uses
the immutable snapshot registered for `expected_hash` to materialize the exact
attempted candidate before returning a stale conflict. An exact-match failure
returns closest candidates. Multiple edits are separate invocations with
distinct trusted idempotency metadata. Every accepted overwrite returns the
new snapshot and preimage journal reference. Conflict `current_script` obeys
the 50 KiB/2000-line cap; continue with paged `read_part` when truncated.

### write_part
```
write_part(name: str, expected_hash: str, script: str)
    -> {applied, diff?, content_hash?, snapshot_ref?, journal_ref?,
        conflict?: {current_hash, current_script, current_truncated,
                    next_offset_line?, current_snapshot_ref,
                    base_snapshot_ref, attempted_snapshot_ref}}
```
Whole-file replacement for templates or substantial rewrites. It has the same
optimistic-hash, atomic-write, conflict-payload, and preimage-journal contract
as `edit_part`; there is no force-overwrite model tool.

### build_part
```
build_part(name: str, params: dict = {}) -> BuildResult
```
Runs the incremental executor (contract in `script_contract.md` §8) against an
immutable snapshot. `BuildResult` records script, consumed-`hc` dependency
projection, persisted part params, effective params, and toolchain hashes plus
audit-only full-globals/project-state hashes, `artifact_ref`, optional
`project_snapshot_ref`, and `current: bool`.
Transient `params` create a preview artifact and therefore always return
`current=false`; use `set_params` followed by a default build to change the
current design. Only `status="ok"`, no-transient-override results are eligible
for publication. Publication revalidates persisted/source hashes so failed,
preview, or raced results remain non-current evidence and never clear stale
state. The trusted build invocation id freezes the initial snapshot and cached
outcome, so a retry cannot silently build newer live inputs.
Always re-runs the part's CHECKS and reports them. Observed equivalent:
`Build cat_step — success`, `Build wood_screw — 438 faces`, and the captured
failure with last-good stats.

### set_params
```
set_params(values: dict, expected_state_hash: str,
           scope: "part"|"project" = "part", name: str|null = null)
    -> {effective, rejected, stale_parts, state_hash?, journal_ref?,
        conflict?: {current_state_hash, current_values,
                    base_snapshot_ref, attempted_snapshot_ref}}
```
Persists parameter overrides (bounds-validated) for a part or for the
project-level Globals in `globals.py` (contract §4). The expected hash is the
corresponding part/project parameter-state hash returned by `read_part` or
`create_part`; stale state returns current values/hash without mutation.
Rejected values return the violated bound; project-scope changes return the
list of parts marked stale by dependency tracking. Accepted writes journal the
previous override document. The update is all-or-nothing: if any supplied value
is unknown, wrong-typed, or out of bounds, `rejected` describes every invalid
entry and no value is persisted. `name` is required exactly when
`scope="part"` and MUST be null/omitted for project scope; this conditional is
enforced in the canonical JSON Schema.

## Grounded observation

### inspect_part
```
inspect_part(name: str, views: list[str] = ["iso", "+X"],  # maxItems=4
             channel: "rgb"|"mask"|"section" = "rgb",
             section_plane: str|null = null,
             explode: float = 0.0,
             last_good: bool = false,
             artifact_ref: str|null = null,
             focus: str|null = null) -> {images: [...], mask_legend?}
```
Renders the current build by default. `artifact_ref` renders an exact immutable
build/checkpoint returned by `build_part`; canonical JSON Schema makes it
mutually exclusive with `last_good=true`. `last_good=true` is a convenience
lookup for the most recent failed attempt's checkpoint at call time and the
result always reports the resolved artifact ref; exact/replayed inspection MUST
pass the `last_good_artifact_ref` from that BuildResult. `channel="section"` requires
`section_plane`; other channels require that field to be null/omitted. `views`
has `minItems=1` and
`maxItems=4` in the canonical schema and accepts named cameras or
`"az45_el30"`. `channel="mask"` returns the id-color legend mapping every
solid (or tagged face, with `focus`) to its palette color, so the model can
name what it sees. `focus` centers and zooms on a labeled solid or tag.
Observed equivalent: `Inspect cat_step — mask, 2 views` with `iso`/`+X`
thumbnails, and the `last_good` behavior from the error hint.

### query_snapshot
```
query_snapshot(name: str, question: str,
               views: list[str] = [...], artifact_ref: str|null = null)
    -> {answer, render_artifacts}  # maxItems=4
```
Runs an ephemeral child Pi vision session against 1–4 fresh renders. It uses a
minimal ResourceLoader with `noTools="all"`, no extensions/skills, no session
persistence, and no `query_snapshot`; it is one model turn, max 1024 output
tokens, 60 s hard timeout, and cannot recurse or mutate. Model usage/cost and
time are charged to the parent session budget. Only text answer and artifact
references return to the parent, so image blocks do not grow main context. The
canonical schema enforces the bounds. Observed
equivalent: `Query Build Snapshot`.

### read_artifact
```
read_artifact(ref: str, offset_bytes: int = 0, max_bytes: int = 49152)
    -> {content, mime_type, offset_bytes, next_offset_bytes?, total_bytes,
        truncated}
```
Pages model-readable text/JSON artifacts referenced by another tool result,
including large BuildResult, CheckReport, geometry, mask-legend, skill, and
conflict evidence. `ref` is an opaque capability scoped to the current project
and authorized session, never a filesystem path; binary artifacts return
metadata and must be consumed by their dedicated render/export path. Paging is
UTF-8 boundary-safe, supports a single source line larger than the context cap,
and guarantees cursor progress. `max_bytes` is 1–49152 and returned text still
obeys the 50 KiB/2000-line Pi cap.

## Measurement (the `m` facade from CHECKS, exposed as tools)

### measure
```
measure(kind: "interference"|"clearance"|"distance"|"bbox"|"volume"|"mass"|
              "sealed"|"genus",
        a: str, b: str|null = null, part: str|null = null,
        project_snapshot_ref: str|null = null) -> {value, units, detail}
```
`a`/`b` use the geometry addressing grammar of contract §7 (tags, labels
with `#k`/`#*` dedup selectors, binding names, `"part"`, and
`"<part>/<label>"` cross-part); addressing errors list candidates rather
than guessing. `interference` returns overlap volume with
per-pair breakdown (observed equivalent: `Measure Overlap`); `clearance`
returns minimum separation; `distance` measures between tagged topology. The
canonical schema requires `b` for interference/clearance/distance and forbids
it for unary bbox/volume/mass/sealed/genus operations. Cross-part measurement uses one coherent current project-snapshot manifest or
an explicit immutable `project_snapshot_ref`; stale/mismatched consumed-
dependency projections return `incoherent_project_snapshot` rather than
comparing incompatible geometry.

### run_checks
```
run_checks(scope: "part"|"project" = "part", name: str|null = null,
           project_snapshot_ref: str|null = null) -> CheckReport
```
Re-runs persistent CHECKS (and cross-part checks for project scope). `name` is
required exactly for part scope and null/omitted for project scope; JSON Schema
enforces the conditional for MCP callers without implicit session context.
Project scope requires a coherent current manifest or explicit immutable
`project_snapshot_ref` and rejects stale/mismatched consumed-dependency
projections.

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
load_skill(name: str, offset_line: int = 1, limit_lines: int = 2000)
    -> {content, artifact_ref, truncated, next_offset_line?}
list_skills() -> [{name, summary, tokens}]
```
Loads a bounded markdown skill page into context, wrapped in provenance-marked
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
            artifact_ref: str|null = null, target: str|null = null,
            layout: "as_built"|"nested_sheet" = "as_built")
    -> {paths, source_artifact_ref, source_input_hashes, export_hashes}
```
At first invocation the WAL freezes an immutable successful build artifact.
When `artifact_ref` is omitted, this must be the non-stale current successful
artifact; an explicit authorized ref may select a successful historical or
preview artifact. Failed/checkpoint-only refs are rejected. Every retry uses
the recorded source ref, and every output carries source-input and exported-
byte SHA-256 provenance, so a concurrent rebuild cannot change export meaning.
`target`, when supplied by the model, is a create-only relative filename
beneath `.heph/exports/`, not an arbitrary filesystem path; omitted targets are
content-addressed. Export invocation metadata carries the idempotency key, so a
lost-response retry returns the recorded path/outcome. A pre-existing target
from another operation is never overwritten, even if regenerated bytes happen
to match. Every successful export is pinned as a GC root until explicit
`heph export unpin/delete`. The confinement and no-symlink-escape rules above
apply. Canonical JSON Schema permits `layout="nested_sheet"` only with
`format="dxf"|"svg"`; it is reserved until Stage 6 and returns structured
`capability_not_available` before then. Stage 2 supports `as_built`. STEP for
interchange (observed Smith ceiling); DXF/SVG per-lamination
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
