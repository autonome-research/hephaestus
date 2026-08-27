<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

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

Conventions: part, new-part, and project-check `name` arguments are normalized
identifiers matching `^[a-z][a-z0-9_]{0,63}$`; separators, absolute paths, `..`, Unicode
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
provider tool-call ID. Hephaestus **REST API** callers MUST send a UUIDv7
`Idempotency-Key`. MCP calls—including MCP over HTTP—follow the MCP rule below
rather than the REST header rule. MCP callers MAY send `_meta["hephaestus.dev/idempotency-key"]`; otherwise the server
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
identity, and canonical JSON arguments (sorted object keys and normalized
numeric syntax, excluding invocation metadata). String values are **not**
Unicode-normalized: source/check/globals/prompt content hashes preserve the
exact decoded code-point sequence encoded as UTF-8, so NFC/NFD-different bytes
are different payloads. All validators reject unpaired UTF-16 surrogates as
`invalid_unicode_scalar` before UTF-8 sizing/hashing; JavaScript must not apply
replacement-character coercion, and Python/TypeScript/MCP parity is CI-tested. HMAC keys come from the durable
project keyring specified in architecture §3.5; operation rows record key IDs
and retired verification keys outlive the 30-day horizon plus 7-day safety
margin. Retrying the same key/payload returns that outcome after a lost response or restart; key
reuse with another payload is an error. The idempotency horizon is 30 days.
Full outcomes remain protected throughout the horizon, and older normalized
keys return `key_expired` without execution. After expiry, GC keeps a compact
key/payload/terminal-state/commit-hash tombstone for a 7-day safety margin and
may then remove it because the HMAC-verified embedded timestamp still rejects
execution. Clients reconcile uncertain completion with the same key. Read-only tools are freely retryable.
Reconciliation shape is transport-specific for `edit_part` and is pinned by
the Stage 3 parity suite: an MCP same-id retry replays the recorded
`{applied: true, ...}` outcome (the request-id ledger sits in front of the
CAS gate), while a Pi-bridge retry of a committed edit reports
`{applied: false, conflict: {current_hash: <the hash that edit wrote>}}`
(the live-hash read precedes the WAL claim, making ambiguous completion
detectable). Both mutate exactly once and both surface the live hash.
Tolerances are in mm. Source/artifact mutations and stateful delegation tools use this
contract: `create_part`, `edit_part`, `write_part`, `edit_globals`,
`create_project_check`, `edit_project_check`, `set_params`, `build_part`,
`export_part`, `generate_drawing`, `generate_doc`, `delegate_part_agent`, and
`cancel_delegation`; none may silently duplicate work or
discard bytes.

Pi tool execution is parallel by default, but `ask_user`, `create_part`,
`edit_part`, `write_part`, `edit_globals`, `create_project_check`,
`edit_project_check`, `set_params`, `build_part`, `export_part`,
`generate_drawing`, `generate_doc`, and
`delegate_part_agent` and `cancel_delegation` MUST declare sequential
execution. Any future stateful or mutating tool does the
same. Read-only render and measurement calls MAY run concurrently against the
last completed artifact. Pi tool proxies enforce object scope in addition to
tool visibility: a part or quick-edit session is bound to one normalized part ID, and any name/
artifact/snapshot resolving outside it is rejected `scope_denied`. Project-
scoped `set_params` and `run_checks` are orchestrator-only even though they have
no foreign part name; part sessions may use only their own part scope. Only the
project orchestrator may create parts or address multiple parts; MCP/REST
authorization is enforced independently. A Hephaestus preflight hook inspects the complete
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
        truncated, oversized_line, oversized_line_offset_bytes?,
        next_offset_bytes?}
```
Returns separate raw and numbered chunks (the raw chunk is suitable for exact
edits), registers an immutable full-file content-addressed snapshot, and
returns the hashes/refs required for optimistic writes and exact conflict
reconstruction. `offset_line`/`limit_lines` select only the first human-friendly
page. Any truncated response returns snapshot-bound absolute
`next_offset_bytes`; all continuation uses `read_artifact(snapshot_ref,
offset_bytes=...)`, never another mutable source read. When
`oversized_line=true`, `oversized_line_offset_bytes` gives that line's absolute
UTF-8 start (including when the first page starts after line 1), and
`next_offset_bytes` advances from the returned prefix.
Snapshot refs are bound to project
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
                    current_oversized_line,
                    current_oversized_line_offset_bytes?,
                    current_next_offset_bytes?, current_snapshot_ref,
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
new snapshot and preimage journal reference. Every stale-conflict
`current_script` is a conflict-time snapshot, obeys the 50 KiB/2000-line cap,
and MUST be continued from `current_snapshot_ref` at
`current_next_offset_bytes` with `read_artifact` when truncated or
`current_oversized_line=true`. `read_part`
intentionally requests newer live state and is never conflict continuation.

### write_part
```
write_part(name: str, expected_hash: str, script: str)
    -> {applied, diff?, content_hash?, snapshot_ref?, journal_ref?,
        conflict?: {current_hash, current_script, current_truncated,
                    current_oversized_line,
                    current_oversized_line_offset_bytes?,
                    current_next_offset_bytes?, current_snapshot_ref,
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
Before any geometry runs, the **clarification gate** (`VALIDATION.md` §3) reads
the requirement ledger and refuses the build while any entry is `assumed`,
material, and unresolved. The refusal is a discriminated result, not an error:
`{status: "clarification_required", generation, entries, unresolved_material,
message}`, carrying the offending entries so the follow-up `ask_user` can be
written straight from them. Materiality is decided by the harness, not by the
model: an entry counts as material when it declares `material: true` **or** when
its `applies_to`/`text` falls in a §3 material class (envelope dimension,
datum/origin placement, wall or feature direction, fit class or clearance, joint
mating direction, unstated thickness). An assumption cannot be tagged
`material: false` to get past the gate. The refusal claims no idempotency key —
it did no work — so the same invocation id builds for real once the assumption
is resolved.

Always re-runs the part's CHECKS and reports them. Observed equivalent:
`Build cat_step — success`, `Build wood_screw — 438 faces`, and the captured
failure with last-good stats.

Every **successful** build additionally carries `critique` — see below. It is
unrequested and unconditional.

### build_part → critique (`VALIDATION.md` §4)
```
critique: {
  interference: {solids, pairs_total, pairs_measured, pairs_capped,
                 declared_intentional: [str],
                 overlaps: [{a, b, volume_mm3}], warnings: [W]},
  manifold:     {available, sealed?, genus?, solids?, warnings: [W]},
  prompt_number_diff?: {
      numbers: [{value_mm, unit, text, axis: "x"|"y"|"z"|null,
                 matched?, compared_to?, dimension_mm?}],
      dimensions: dict[str, number], warnings: [W]},
  dimension_findings?: {
      generation?, artifact_ref?,
      open:    [F],   // still binding: the run cannot finish while any is here
      cleared: [F],   // closed by a matching rebuild or a user's dismissal
      warnings: [W]},
  warnings: [W]   // the flattened union of the sections above
}
W = {kind: "interference"|"interference_pairs_capped"|"interference_unavailable"
          |"not_sealed"|"unmatched_request_number"|"dimension_mismatch"
          |"open_dimension_finding"|"dimension_findings_unavailable",
     message, ...per-kind evidence}
F = {id, part, kind, request_value_mm, request_text, message, axis,
     dimension, dimension_value_mm, status: "open"|"cleared"|"dismissed",
     asked, dismissal, closed_by}
```
The model does not ask for this and cannot turn it off; it is computed by rule
from the build's own outputs, because a self-authored `CHECKS` block cannot
catch a misreading of the spec that it encodes.

`interference` measures pairwise overlap volume across the built compound's
solids on the *published* artifact. A non-zero overlap (above kernel noise) is
an `interference` warning naming the pair and the volume, **unless** the build
declared it intentional: `part.feature(<name>).intentional_overlap = True` in
the script, or a ledger entry with `applies_to: "intentional_overlap"` (or an
intentional-overlap/press-fit phrase in its `text`/`rationale`). Declarations
are echoed in `declared_intentional`. The pass is bounded — at most 64 pairs —
so a many-solid compound cannot eat the 300 s CAD budget; a compound with fewer
than two solids never reloads its geometry at all, and a bound that bites is
itself reported (`pairs_capped`, plus an `interference_pairs_capped` warning).
A compound that could not be enumerated reports `interference_unavailable`
rather than an implied clean sheet.

`manifold` surfaces the build metrics' `sealed`/`genus`/solid count and warns
`not_sealed` on non-watertight geometry.

`prompt_number_diff` extracts every number carrying a length unit (mm, cm, m,
in) from the **original request** and compares it with the built dimensions.
It is **absent** when the runtime holds no request text — never fabricated.
A number the request tags with an axis (`40 mm (Y)`, `60 mm in X`, "overall
height is 40 mm") is compared against the bbox extent on that axis:
disagreement emits `dimension_mismatch` carrying request value, dimension name
and dimension value, and — since nothing on that axis then measures the stated
number — `unmatched_request_number`. An axis-less number is matched against
every known dimension (bbox extents, tagged edge lengths, `CHECKS` thresholds)
and emits `unmatched_request_number` when none corresponds. Matching is
deliberately crude (regex + unit normalization + a 0.5%/0.05 mm tolerance):
false positives are acceptable, silence on a real mismatch is not.

`dimension_findings` is the **binding** half of that diff (`VALIDATION.md` §4,
"Dimension findings are BINDING"). Every axis-resolved mismatch a published
build raises becomes an open finding on the run, restated as an
`open_dimension_finding` warning carrying its `id`, and **the run may not
terminate green while one is open** (§6). Two things clear it and nothing else:
a later successful build of the same part whose diff no longer raises it, or a
committal user answer to `ask_user(requirement_ids: [<finding id>], …)`, which
the runtime records as a dismissal — a non-committal answer records `asked` and
dismisses nothing. There is no tool that writes this store: not the ledger, not
`update_requirement`, and the reviewer's verdict on a finding id is discarded.
The binding comparison also ignores the script's own `CHECKS` thresholds (the
advisory `dimensions` pool above still includes them), because an acceptance
test the run authored cannot be the evidence that the run read the spec right.
Axis-less unmatched numbers stay advisory: they say the harness did not find the
number, not that the geometry contradicts it. The section is **absent** on a
preview build or with no request text, and reports
`dimension_findings_unavailable` when the record could not be written — an
absent or failed section never means "the dimensions agree".

### set_params
```
set_params(values: dict[str, number|null], expected_state_hash: str,
           scope: "part"|"project" = "part", name: str|null = null)
    -> {effective, rejected, stale_parts, state_hash?, journal_ref?,
        conflict?: {current_state_hash, current_values,
                    base_snapshot_ref, attempted_snapshot_ref}}
```
Persists parameter overrides (bounds-validated) for a part or for the
project-level Globals in `globals.py` (contract §4). The expected hash is the
corresponding part hash from `read_part`/`create_part`, or the project hash from
`read_globals`; stale state returns current values/hash without mutation.
Rejected values return the violated bound; project-scope changes return the
list of parts marked stale by dependency tracking. Accepted writes journal the
previous override document. The update is all-or-nothing: if any supplied value
is unknown, wrong-typed, or out of bounds, `rejected` describes every invalid
entry and no value is persisted. A null value explicitly clears a persisted
override. `name` is required exactly when
`scope="part"` and MUST be null/omitted for project scope; this conditional is
enforced in the canonical JSON Schema.

### read_globals / edit_globals
```
read_globals(offset_line: int = 1, limit_lines: int = 2000)
    -> {script, numbered_script, content_hash, snapshot_ref,
        project_param_state_hash, truncated, oversized_line,
        oversized_line_offset_bytes?, next_offset_bytes?}
edit_globals(expected_hash: str, old_str: str, new_str: str)
    -> {status: "applied", diff, content_hash, snapshot_ref, journal_ref}
     | {status: "validation_error",
        kind: "syntax"|"contract"|"sandbox"|"evaluation"|"invalid_overrides",
        diagnostics, invalid_overrides?}
     | {status: "conflict", kind: "stale_hash", current_hash,
        current_script, current_truncated, current_oversized_line,
        current_oversized_line_offset_bytes?, current_next_offset_bytes?,
        current_snapshot_ref, base_snapshot_ref, attempted_snapshot_ref}
```
Project-orchestrator-only tools for the existing `globals.py`. Paging—including
single-line >50 KiB fallback to byte-cursored `read_artifact`—optimistic CAS,
conflict snapshots, WAL/idempotency, context limits, and path confinement match
`read_part`/`edit_part`. `edit_globals` and project-scoped
`set_params` serialize on the project-config lock. The edited candidate must
parse/evaluate in the secure globals sandbox against the current persisted
overrides; removing a parameter or tightening bounds around an override returns
a top-level `validation_error(kind="invalid_overrides")` and commits nothing
until `set_params(..., null)` clears or replaces it. This is distinct from the
`conflict(kind="stale_hash")` CAS response. Otherwise no bytes or dependency state change on failure. There is no model-visible arbitrary-path
or force-write globals tool.

### list_project_checks / create_project_check / read_project_check / edit_project_check
```
list_project_checks(cursor: str|null = null, limit: int = 100)
    -> {status: "ok", items: [{name, content_hash, summary}], total,
        check_set_generation, check_set_ref, next_cursor?}
     | {status: "invalid_check_generation", check_set_generation,
        check_set_ref, diagnostics_ref}
create_project_check(name: str, description: str = "")
    -> {path, initial_script, content_hash, snapshot_ref}
read_project_check(name: str, offset_line: int = 1, limit_lines: int = 2000)
    -> {script, numbered_script, content_hash, snapshot_ref,
        truncated, oversized_line, oversized_line_offset_bytes?,
        next_offset_bytes?}
edit_project_check(name: str, expected_hash: str, old_str: str, new_str: str)
    -> {status: "applied", diff, content_hash, snapshot_ref, journal_ref}
     | {status: "validation_error",
        kind: "syntax"|"contract"|"sandbox"|"evaluation", diagnostics}
     | {status: "conflict", kind: "stale_hash", current_hash,
        current_script, current_truncated, current_oversized_line,
        current_oversized_line_offset_bytes?, current_next_offset_bytes?,
        current_snapshot_ref, base_snapshot_ref, attempted_snapshot_ref}
```
Project-orchestrator-only, identifier-constrained APIs rooted at `checks/`.
`list_project_checks` is the authoritative discovery path and returns no
arbitrary filesystem entries. The first page freezes an immutable lexical check-
set index (`check_set_ref`); opaque cursors bind its generation/ref and
position, so concurrent
mutation cannot alter later pages. `summary` is capped at 512 UTF-8 bytes per
item with truncation at a valid code-point boundary and no embedded source; `limit` is 1–100 and the server may return fewer
to stay within the global context cap while guaranteeing `next_cursor`
progress. An invalid externally imported generation returns only the
`invalid_check_generation` variant and diagnostics—never a partial normal
listing. `check_set_ref` is the immutable discovery index; `check_bundle_ref`
below is the separately frozen executable bundle for one run. Check reads use the same paging and oversized-
line `read_artifact` fallback as `read_part`.
Creation is no-replace from a safe cross-part CHECKS template; edits use the
same CAS/WAL/journal contract as part edits and must parse in the secure check
sandbox before commit. Check scripts receive the measurement facade and pure
`approx` helper used by `script_contract.md` §6—no filesystem/network/import
surface. Part and quick-edit sessions do not receive
these tools.

## Grounded observation

### inspect_part
```
inspect_part(name: str, views: list[str] = ["iso", "+X"],  # maxItems=4
             channel: "rgb"|"mask"|"section" = "rgb",
             mask_mode: "solid"|"selection" = "solid",
             section_plane: str|null = null,
             explode: float = 0.0,
             last_good: bool = false,
             artifact_ref: str|null = null,
             focus: str|null = null)
    -> {status: "ok", source_artifact_ref, images, render_artifact_refs,
        mask_legend?, mask_legend_ref?, mask_legend_truncated,
        selection_table_ref?,
        selection_bundles?: [{view, bundle_ref,
                              pass_refs: {solid, face, edge}}]}
     | {status: "capability_error", code: "image_model_required",
        source_artifact_ref, render_artifact_refs, message}
```
Renders the current build by default. `artifact_ref` renders an exact immutable
build/checkpoint returned by `build_part`; canonical JSON Schema makes it
mutually exclusive with `last_good=true`. `last_good=true` is a convenience
lookup for the most recent failed attempt's checkpoint at call time and the
result always reports the resolved artifact ref; exact/replayed inspection MUST
pass the `last_good_artifact_ref` from that BuildResult. `channel="section"` requires
`section_plane`; other channels require that field to be null/omitted.
Canonical schema forbids non-default `mask_mode` unless `channel="mask"`.
`solid` legend/domain is exactly one non-antialiased solid-ID pass.
`selection` returns, per view, one bundle containing separate non-antialiased
solid/face/edge ID layers plus a shared global table; pixels never combine
kinds. Those three machine-ID layers are artifact-only. At most one composite
human/model preview per requested view is inline (≤4 total); it is explicitly
not palette-decodable. `selection_bundles` exposes a typed per-view
`bundle_ref` and its solid/face/edge pass refs, so four views yield four inline
previews and twelve unambiguous pass artifacts without violating the bridge
image cap. `render_artifact_refs` remains the flat retention/download list. A
successful `channel="mask", mask_mode="selection"` result requires
`selection_table_ref`, `mask_legend_ref`, and one `selection_bundles` entry per
view; other modes return none of them. A GLTF used for raycast carries the same
selection IDs and an immutable linked bundle ref. A returned per-view bundle
ref, any of its pass refs, or a linked GLTF is accepted as the client's
`selection_artifact_ref`; pass resolution follows its immutable bundle link. Inline legends obey the
50 KiB cap; `mask_legend_truncated` and the opaque readable
`mask_legend_ref` provide lossless paging through `read_artifact`.
`focus` changes only camera framing/visibility and never changes the mode's ID
namespace. Every result variant reports the exact resolved
`source_artifact_ref`, and each render/table is cryptographically bound to it.
`views` has `minItems=1` and
`maxItems=4` in the canonical schema and accepts named cameras or
`"az45_el30"`. The channel's mode-specific id-color legend lets the model name
what it sees. `focus` centers and zooms on a labeled solid or tag without
altering legend semantics.
Observed equivalent: `Inspect cat_step — mask, 2 views` with `iso`/`+X`
thumbnails, and the `last_good` behavior from the error hint. In a Pi session,
inline images require an image-capable active model; a text-only model receives
artifact refs plus structured `image_model_required` rather than malformed
image context.

### query_snapshot
```
query_snapshot(name: str, question: str,
               views: list[str] = [...], artifact_ref: str|null = null)
    -> {status: "ok", answer, render_artifacts, usage}  # maxItems=4
     | {status: "capability_error", code: "capability_not_available", message}
```
Runs an ephemeral child Pi vision session against 1–4 fresh renders. The child
`AgentSession` is created with `noTools="all"`, an explicit minimal
ResourceLoader containing no extensions/skills, and in-memory/no persistence.
It is one model turn, max 1024 output tokens, 60 s hard timeout, and cannot
recurse or mutate. The runtime uses the active model if image-capable,
otherwise a configured image-capable vision model; if neither exists it returns
structured `capability_not_available` without launching a child. Model usage/cost and
time are charged to the parent session budget. Only text answer and artifact
references return to the parent, so image blocks do not grow main context. The
canonical schema enforces the bounds. Observed
equivalent: `Query Build Snapshot`.

### read_artifact
```
read_artifact(ref: str, offset_bytes: int = 0, max_bytes: int = 49152)
    -> {content, mime_type, offset_bytes, next_offset_bytes?, total_bytes,
        truncated}
     | {error: "invalid_utf8_offset", offset_bytes, total_bytes}
```
Pages model-readable text/JSON artifacts referenced by another tool result,
including large BuildResult, CheckReport, geometry, mask-legend, skill, and
conflict evidence. `ref` is an opaque capability scoped to the current project
and authorized session, never a filesystem path; binary artifacts return
metadata and must be consumed by their dedicated render/export path. Paging is UTF-8 boundary-safe: `offset_bytes` must be zero, `total_bytes`, or an
exact code-point boundary, otherwise the tool returns
`invalid_utf8_offset` without normalizing it. The server shortens a page end to
the preceding boundary and emits a boundary-aligned `next_offset_bytes`,
supports a single source line larger than the context cap, and guarantees
cursor progress. `max_bytes` is 1–49152 and returned text still
obeys the 50 KiB/2000-line Pi cap.

## Measurement (the `m` facade from CHECKS, exposed as tools)

### measure
```
measure(kind: "interference"|"clearance"|"distance"|"bbox"|"volume"|"mass"|
              "sealed"|"genus",
        a: str, b: str|null = null, part: str|null = null,
        artifact_ref: str|null = null,
        project_snapshot_ref: str|null = null)
    -> {value, units, detail, resolved_artifact_refs}
```
`a`/`b` use the geometry addressing grammar of contract §7 (tags, labels
with `#k`/`#*` dedup selectors, binding names, `"part"`, and
`"<part>/<label>"` cross-part); addressing errors list candidates rather
than guessing. `interference` returns overlap volume with
per-pair breakdown (observed equivalent: `Measure Overlap`); `clearance`
returns minimum separation; `distance` measures between tagged topology. The
canonical schema requires `b` for interference/clearance/distance and forbids
it for unary bbox/volume/mass/sealed/genus operations. A single-part operation
may target an explicit successful current/historical/preview `artifact_ref`;
default resolves current. Cross-part operations require current coherent or
explicit `project_snapshot_ref`. The two selectors are mutually exclusive and
the result reports exact resolved refs. Cross-part measurement uses one coherent
project-snapshot manifest or an explicit immutable `project_snapshot_ref`; stale/mismatched consumed-
dependency projections return `incoherent_project_snapshot` rather than
comparing incompatible geometry.

### compare_solids
```
compare_solids(part: str, target: str,
               align: "as_posed"|"principal" = "as_posed")
    -> {status: "ok", align,
        a: {kind: "part", name, artifact_ref},
        b: {kind: "part", name, artifact_ref}
         | {kind: "import", path, sha256, snapshot_ref},
        diff: {align,
               volume: {common_mm3, a_only_mm3, b_only_mm3, iou, align},
               surface: {a_to_b_mean_mm, b_to_a_mean_mm, chamfer_mm,
                         max_deviation_mm, a_samples, b_samples, align},
               topology: {a: census, b: census, solids_delta, faces_delta,
                          edges_delta, planar_faces_delta,
                          cylindrical_faces_delta, other_faces_delta,
                          genus_delta, sealed_changed},
               a_bbox_mm, b_bbox_mm, a_volume_mm3, b_volume_mm3},
        resolved_artifact_refs}
```
`COMPARE.md` §2. How far a part is from a target, as **facts** — this is what
closes the editing loop (`import_step` → modify → `compare_solids` → converge)
with the harness measuring convergence instead of the model asserting it.
Read-only, freely retryable, stores nothing; on the `part` and `orchestrator`
profiles.

`part` is compared as its **current successful build artifact**, never a live
build, exactly as `measure` resolves geometry. `target` is `"part:<name>"`
(another part's current artifact) or `"import:<relpath>"` — resolved through the
`INGEST.md` §1 import machinery, so the same confinement walk applies
(traversal, absolute paths and symlink escapes are refused with their own
`unknown_import` / `path_confinement` / `invalid_import_path` /
`unreadable_step` tokens) and the response **attributes the comparison to the
import's content hash**, so it can be re-run against provably the same bytes. A
bound part session may not reach another part through a `part:` target.

`align` is a declared choice, never a silent normalization: `as_posed` compares
the solids where they sit (an edit that must preserve pose wants this — a moved
part *is* wrong), `principal` moves each into its own canonical inertia frame
first (a comparison that should not punish a rigid transform wants this). The
mode is echoed on every record it affects. `a_bbox_mm`/`b_bbox_mm` are always
the shapes **as posed**. `align="principal"` on a shape enclosing no volume has
no inertia frame and refuses with `no_solid_geometry` rather than inventing one.
`a_samples`/`b_samples` are the surface-sample counts behind the chamfer means,
so a number computed on a coarse grid is never read as if it were fine.

**Bounded execution** (`COMPARE.md` §5). The diff is computed in a killable
subprocess under a wall-clock ceiling (`HEPHAESTUS_COMPARE_TIMEOUT_S`, default
300 s). The cheap facts — topology census, both bboxes, both volumes — are
computed and streamed first; a comparison that cannot finish (or whose
subprocess dies) refuses with **`compare_timeout`**, and the refusal's data
carries whatever partial facts arrived (`partial`, or `null` when nothing did)
plus `lost` naming the halves that were cut short (`volume_boolean`,
`surface_sampling`, and `topology_census` when even the first look was lost).
The call can never outlive its session on a pathological B-rep; act on the
partial facts, ask a cheaper question, or raise the ceiling.

**No thresholds live here.** "iou ≥ 0.995 is a pass" is a claim owned by a
`CHECKS` predicate (`m.diff`, script contract §6), a DFM rule, or a bench task
policy, cited like any other requirement under `VALIDATION.md` §1. There are no
`build:<id>` targets in Stage 8B.

### run_checks
```
run_checks(scope: "part"|"project" = "part", name: str|null = null,
           project_snapshot_ref: str|null = null)
    -> CheckReport  # includes geometry/check source provenance
     | {status: "invalid_check_generation", check_set_generation,
        check_set_ref, diagnostics_ref}
```
Re-runs persistent CHECKS (and cross-part checks for project scope). `name` is
required exactly for part scope and null/omitted for project scope; JSON Schema
enforces the conditional for MCP callers without implicit session context.
Project scope fails closed with the discriminated invalid-generation response
before executing any predicate when the current check set is invalid. Otherwise
it requires a coherent current manifest or explicit immutable
`project_snapshot_ref` and rejects stale/mismatched consumed-dependency
projections. At invocation it freezes the lexically ordered authorized project-
check source bundle; every project CheckReport includes
`check_set_generation`, `project_snapshot_ref`, opaque `check_bundle_ref`, and
`{check_path: sha256}` hashes, so concurrent edits
produce a later bundle rather than ambiguous evidence.

### run_dfm
```
run_dfm(name: str, process: str|null = null,
        artifact_ref: str|null = null,
        project_snapshot_ref: str|null = null)
    -> {status: "ok", part, process, source_artifact_ref,
        resolved_from: "current"|"artifact_ref"|"project_snapshot",
        pack: {name, version, registry, registry_digest},
        rules: [{rule_id, title, severity,
                 status: "ok"|"violations"|"error", params, findings, error}],
        findings: [{rule_id, severity: "error"|"warning"|"info", title, message,
                    process, source_artifact_ref, tags: [str],
                    topology: [{kind, solid_id, topology_index, tag}],
                    measured, suggested_bound, bound_unit}],
        severity_counts, errored_rules, truncated, material}
     | {status: "capability_error", code: "capability_not_available", message}
```
Runs the DFM rule pack matching `part.process` (or an explicit `process`)
against current geometry by default, an explicit successful current/historical/
**preview** artifact when `artifact_ref` is given, or the part's entry in an
immutable `project_snapshot_ref` (the two refs are mutually exclusive). The
resolved ref is reported as `source_artifact_ref` with `resolved_from` naming
the mode that produced it, and it is repeated on every finding: a DFM report is
a claim about specific bytes, never about "the part". Automatic DFM always
receives the exact `artifact_ref` from the successful BuildResult that triggered
it, never a mutable current lookup.

Findings carry rule id, severity, suggested bound, resolved
`source_artifact_ref`, and artifact-bound topology descriptor `{kind,
solid_id, topology_index, tag?}`—never a bare mutable mask id. `tags` are the
offending §5.3 tag names, recovered from the source map of the build that
published those bytes; an artifact whose build record has aged out is still
checked and simply addresses topology by index.

A rule whose predicate raises is that rule's `status: "error"` with the
remaining rules still evaluated — a broken pack rule never hides the others and
never fails the run. `process` is never guessed: a part with no `part.process`
and no override is refused with `invalid_params` listing the packs that exist.
Predicates are untrusted registry content and run only under a probed secure
sandbox (`origin: "registry"`, architecture §3.6/§7.2); without one the tool
answers `capability_not_available` rather than evaluating unsandboxed.

**DFM mode** is a project setting, not a tool argument: with `[dfm] auto_run =
true` in `hephaestus.toml`, every successful `build_part` carries a `dfm`
section inside its `VALIDATION.md` §4 `critique` block — the same evaluation
against the artifact that build just published, with each `error`/`warning`
finding flattened into `critique.warnings` as `kind: "dfm_finding"`. The block
reports `available: false` with a `dfm_unavailable` warning when the run could
not happen, so silence never reads as a pass, and a DFM failure never fails the
build.

## Validation (the requirement ledger — `VALIDATION.md` §2)

### record_requirements / read_requirements / update_requirement
```
record_requirements(entries: [{id: str, text: str,
                     source: "specified"|"derived"|"assumed",
                     quote: str|null,
                     cite: {reference: str, page: int|null, quote: str}|null,
                     from: [str], rationale: str|null,
                     material: bool|null, value: number|null,
                     unit: str|null, applies_to: str|null}])
    -> {status: "ok", generation, artifact_ref, entries, unresolved_material}
read_requirements()
    -> {status: "ok", generation, artifact_ref, entries, unresolved_material}
update_requirement(id: str, text: str|null = null,
                   source: "specified"|"derived"|"assumed"|null = null,
                   quote: str|null = null,
                   cite: {reference, page?, quote}|null = null,
                   from: [str]|null = null,
                   rationale: str|null = null, material: bool|null = null,
                   value: number|null = null, unit: str|null = null,
                   applies_to: str|null = null)
    -> {status: "ok", generation, artifact_ref, entries, unresolved_material}
```
The ledger makes interpretation an inspectable artifact instead of an implicit
act. One entry per constraint, emitted **before** any geometry. `source` is
`specified` (traceable to a phrase of the request — `quote` required and
checked, **or** an `INGEST.md` §2 `cite` of a registered reference in its
place: `{"source": "specified", "cite": {"reference": "sheet2.pdf", "page": 2,
"quote": "Ø6.0 ±0.1"}}`, refused with `invalid_requirement` when the reference
is not registered or the page does not exist), `derived` (computed from other
entries — `from` lists their ids, and every id must resolve), or `assumed` (the model supplied it — `rationale`
required, and `material: true|false` declares whether it moves geometry).
Entries failing those obligations are refused with `invalid_requirement` and
**nothing is written**: the batch is all-or-nothing.

Recording upserts by entry id — a first-seen id appends, a repeated id replaces
in place — and each write publishes a new immutable generation
(`artifact:requirements:sha256:…`) naming its parent, CAS-published under the
project-config lock. Older generations stay readable forever, so a lost-response
retry of the same invocation id replays exactly the generation its own committed
write produced. `update_requirement` patches only the fields supplied and
re-validates the resulting entry.

**`asked` and `resolution` are not the caller's to write.** They record what
happened when a human was consulted, and the rest of the ladder keys on them: the
§3 gate opens on them, §5 fails any assumption without a `resolution`, and §8's
`clarification_rate` counts `asked`. So neither appears in the parameters of
either write tool, and supplying one anyway — over MCP/REST, which does not
schema-check — is refused with `invalid_requirement` and nothing is written. They
are written by exactly one thing: the runtime, applying a real `ask_user` answer
(see `ask_user`). Re-recording an entry carries them across untouched, so an
upsert can neither forge nor erase them. Their presence on an entry is therefore
*evidence that a user was asked*, not a claim the run can make about itself.

`unresolved_material` lists the entries with `source: "assumed"`,
`material: true` and no recorded `resolution`. That set is the ledger's
contract with the rest of the ladder: it is what the termination reviewer treats
as fail-unless-confirmed and what a green termination may never contain. (The
clarification gate refuses `build_part` on a *wider* set, classified by the
harness rather than declared by the model, and it clears on the question having
been asked rather than answered — see `build_part`.) `heph lint` reads the same
ledger: a `CHECKS` numeric literal citing no entry id is `unsourced_constant`,
and a `specified` entry whose `quote` is not in the request is
`unsourced_requirement`. A `cite` is verified the same way against the named
reference's extracted text; a citation of an **image** reference has no text to
decide against, so it is `unverifiable_citation` and is verified instead by the
§5 termination reviewer on the vision channel (`INGEST.md` §2).

## Assemblies (declared constraints — `ASSEMBLY.md` §3)

### declare_constraint / update_constraint / read_constraints / check_assembly
```
declare_constraint(id: str, kind: "no_interference"|"clearance_min"|"distance"|
                        "coincident"|"concentric"|"parallel"|"perpendicular"|"fit",
                   a: str, b: str,
                   provenance: {requirement: str|null, assumed: bool|null,
                                reason: str|null},
                   note: str|null = null, poses: [str]|null = null,
                   axis_eps_deg: number|null = null, max_mm: number|null = null,
                   min_mm: number|null = null, normal_eps_deg: number|null = null,
                   tol_deg: number|null = null, tol_mm: number|null = null,
                   tol_mm3: number|null = null, value_mm: number|null = null)
    -> {status: "ok", generation, artifact_ref, change, entries,
        assembly, assembly_ref}
update_constraint(id: str, patch: {...entry fields, withdrawn: bool|null},
                  reason: str)
    -> {status: "ok", generation, artifact_ref, change, entries,
        assembly, assembly_ref}
read_constraints()
    -> {status: "ok", generation, artifact_ref, change, entries,
        assembly, assembly_ref}
check_assembly(ids: [str]|null = null)
    -> {status: "ok", assembly: {generation, constraints, artifact_refs,
                                 stale, counts, blocking},
        artifact_ref, partial}
```
A constraint spans parts, so it cannot live in any one part script: the project
carries a **constraint set** as generational state, exactly like the requirement
ledger (immutable content-addressed generations naming their parent, CAS-published
under the project-config lock, idempotent on the invocation id). Anchors are
`part[:selector]` where the selector is a §5.3 tag, a geometry label or a binding
name — the existing addressing layer, no new naming scheme — and a bare `part`
anchors the whole compound. Declared numbers ride at the entry's top level, and
which ones a kind takes is the evaluator's own table: a missing or unknown one is
refused `invalid_constraint` with nothing written. `poses` (optional, Stage 9A)
binds the entry to named poses for per-pose evaluation — `ASSEMBLY.md` §1/§2 as
amended by `KINEMATICS.md` §3; absent, evaluation and the outcome wire shape are
byte-for-byte the 8C ones.

**Provenance is mandatory.** An entry cites a ledger requirement id or is
`{"assumed": true, "reason": …}` — a constraint IS an interpretation of intent,
so it carries the same honesty taxonomy as a `VALIDATION.md` §2 ledger entry, and
an entry with neither is refused `invalid_constraint`.

**Nothing is erased.** `update_constraint` merges the patch onto the stored entry
and re-validates the whole result (so a patch cannot produce an entry that could
not have been declared), and `patch: {"withdrawn": true}` is the withdrawal path:
a new generation that stops claiming the constraint while keeping it — and the
reason — readable. A revision without a `reason`, a patch of `id`, and a patch or
withdrawal naming an unknown id are refused (`invalid_constraint` /
`unknown_constraint`).

**There is no solver.** Scripts position geometry; constraints verify, they never
move anything, and a constraint that would need motion to satisfy is simply
unsatisfied. `check_assembly` resolves each anchor against the parts' **current
successful build artifacts** and reports each constraint as
`satisfied | violated | unresolvable`. `unresolvable` is its own state, never
silently skipped and never conflated with `violated`; its `reason` names what is
wrong and therefore what would fix it (`missing_part`, `no_current_build`,
`missing_artifact`, `dangling_selector`, `ambiguous_selector`,
`unaddressable_anchor`, `shape_refused`, `invalid_constraint`).

A full `check_assembly()` is projected as the project's assembly status;
`ids=[…]` evaluates that subset only and is deliberately **not** projected
(`partial: true`), because a projection covering some constraints would report a
set the project does not have. Reading never measures: `read_constraints` returns
the *last* evaluation, with `stale` naming parts rebuilt since it was taken, and
`assembly: null` meaning never evaluated — which is not a pass. At termination
review a `violated` or `unresolvable` constraint is a blocking finding **by rule**
(`VALIDATION.md` §5).

## Kinematics (declared joints, poses, motion checks and couplings — `KINEMATICS.md` §1/§3/§4/§5, Stage 9A/9B/9C)

### declare_joint / update_joint / read_joints
```
declare_joint(id: str, kind: "fixed"|"revolute"|"prismatic"|"cylindrical",
              parent: str, child: str,
              limits: {min: number, max: number} |
                      {rotation: {min: number, max: number},
                       translation: {min: number, max: number}} | null = null,
              zero: "as_built" = "as_built",
              provenance: {requirement: str|null, assumed: bool|null,
                           reason: str|null},
              note: str|null = null)
    -> {status: "ok", generation, artifact_ref, change, entries,
        motion, motion_ref}
update_joint(id: str, patch: {...entry fields, withdrawn: bool|null},
             reason: str)
    -> {status: "ok", generation, artifact_ref, change, entries,
        motion, motion_ref}
read_joints()
    -> {status: "ok", generation, artifact_ref, change, entries,
        motion, motion_ref}
```
A joint relates two parts, so — like a constraint — it cannot live in any one
part script: the project carries a **joint set** as generational state, exactly
like the constraint set (immutable content-addressed generations naming their
parent, CAS-published under the project-config lock, idempotent on the
invocation id). Anchors are `part[:selector]` under exactly the 8C anchor
grammar — a slash-bearing anchor is refused `invalid_joint`, the two-grammars
rule. The selector must resolve to geometry whose class defines a frame (a
cylindrical face or circular edge for `revolute`/`cylindrical`, a planar face
or linear edge for `prismatic`, any resolvable anchor for `fixed`); the wrong
shape class is a named refusal at evaluation, never a guessed frame. **The
parent anchor's frame is the joint frame**; a child frame diverging beyond the
named epsilons is `misaligned_joint_anchors`.

Which limit shape a kind requires (one pair for `revolute` degrees /
`prismatic` mm, the two named pairs for `cylindrical`, none for `fixed`) is the
joint set's own table: a wrong shape is refused `invalid_joint` with nothing
written. `zero: "as_built"` — the authored positions ARE parameter zero — is
the only value in the 9A contract. **The joint graph must be a forest**: a
cycle (or a part riding two joints) is refused at declaration
(`cyclic_joint_graph` with the cycle named / `invalid_joint`); closed loops are
an open chain plus a pose-bound constraint, measured rather than solved.

**Provenance is mandatory** (`invalid_joint` otherwise) and **nothing is
erased**: `update_joint` merges the patch onto the stored entry and revalidates
the whole result including the forest check; `patch: {"withdrawn": true}` is
the withdrawal path — a new generation that stops claiming the joint while
keeping it, and its reason, readable. A withdrawn joint is never evaluated. A
pose that binds it is deliberately untouched: it becomes `orphaned_pose` at
evaluation, because withdrawal is not a failure. A revision without a `reason`,
a patch of `id`, and a patch or withdrawal naming an unknown id are refused
(`invalid_joint` / `unknown_joint`).

### declare_pose / update_pose / read_poses
```
declare_pose(id: str, joints: {<joint_id>: number},
             provenance: {requirement: str|null, assumed: bool|null,
                          reason: str|null},
             note: str|null = null)
    -> {status: "ok", generation, artifact_ref, change, entries,
        motion, motion_ref}
update_pose(id: str, patch: {...entry fields, withdrawn: bool|null},
            reason: str)
    -> {status: "ok", generation, artifact_ref, change, entries,
        motion, motion_ref}
read_poses()
    -> {status: "ok", generation, artifact_ref, change, entries,
        motion, motion_ref}
```
A **named pose** binds joint parameter values (`KINEMATICS.md` §3): degrees for
`revolute`, mm for `prismatic`. Joints omitted take their zero value, so `{}`
is legal and means "everything as built". The pose set is its own generational
state on the same ledger pattern, with the same lifecycle contract
(`invalid_pose` / `unknown_pose`, withdrawal as a kept generation).

A pose may only bind declared, unwithdrawn joints **at declaration** — naming
an unknown or already-withdrawn joint is refused `invalid_pose`. A joint
withdrawn *later* orphans the pose at evaluation instead (`orphaned_pose`, a
per-pose unresolvable state naming the withdrawn joint id): the pose is not
erased and the withdrawal is not a failure, so nothing is re-refused
retroactively. A constraint entry may bind poses (`poses: [...]` on
`declare_constraint`), evaluating that constraint at each named pose with the
worst pose's residual in the singular slot and a `pose_residuals` table —
see `ASSEMBLY.md` §1/§2 as amended by `KINEMATICS.md` §3.

### declare_motion_check / update_motion_check / read_motion_checks
```
declare_motion_check(id: str,
                     kind: "sweep_clearance"|"sweep_no_interference"|"reach",
                     a: str|null = null, b: str|null = null,
                     anchor: str|null = null,
                     sweep: {<joint_id>: {from: number, to: number}},
                     samples: int = 64,
                     min_mm: number|null = null,
                     target_point_mm: [number, number, number]|null = null,
                     tol_mm: number|null = null,
                     provenance: {requirement: str|null, assumed: bool|null,
                                  reason: str|null},
                     note: str|null = null)
    -> {status: "ok", generation, artifact_ref, change, entries,
        results, results_ref}
update_motion_check(id: str, patch: {...entry fields, withdrawn: bool|null},
                    reason: str)
    -> {status: "ok", generation, artifact_ref, change, entries,
        results, results_ref}
read_motion_checks()
    -> {status: "ok", generation, artifact_ref, change, entries,
        results, results_ref}
```
A **motion check** (`KINEMATICS.md` §4) evaluates one measurement over a
sampled range of one or more joint parameters. The motion-check set is its own
generational state on the same ledger pattern as the joint and pose sets, with
the same lifecycle contract (`invalid_motion_check` / `unknown_motion_check`,
withdrawal as a kept generation, compelled provenance, nothing erased).

Which anchor and threshold fields a kind takes is the set's own table
(`invalid_motion_check` with nothing written otherwise): the universal kinds
`sweep_clearance(a, b, min_mm)` and `sweep_no_interference(a, b)` name two
anchors under the 8C grammar (a slash is refused, the two-grammars rule); the
existence kind `reach(anchor, target_point_mm, tol_mm)` names one anchor, a
world-mm target point and a tolerance. `sweep` maps **declared, unwithdrawn,
scalar-sweepable** joint ids to `{from, to}` ranges (`from < to`, the joint
kind's own unit) — sweeping an unknown, withdrawn, `fixed` (0 DOF) or
`cylindrical` (pair-valued) joint is refused at declaration; a joint withdrawn
*later* orphans the check at evaluation instead (`orphaned_sweep`, the
`orphaned_pose` rule restated). `samples` is the PER-AXIS request (endpoints
inclusive, default 64); **the cap is on the computed grid total**: a
declaration (or update — a patch is revalidated as a whole) whose product
`samples^n_joints` exceeds 4096 is refused naming the computed total.

`results` carries the LAST full `check_motion` run's per-check §4 result
records (`results: null` means checks were never evaluated — which is not a
pass), with `results_ref` its immutable `artifact:motion-results:` ref.
Reading never measures; `check_motion` is the only thing that does. A
withdrawn check is never evaluated again, but its last recorded result stays
readable exactly as measured.

### check_motion
```
check_motion(ids: [str]|null = null)
    -> {status: "ok",
        motion: {joint_generation, pose_generation, joints, poses,
                 artifact_refs, stale, counts, blocking},
        artifact_ref,
        results: [{id, kind, verdict, samples_evaluated, grid_total,
                   samples_per_axis, sweep, unit, anchors, worst,
                   min_mm, tol_mm, target_point_mm, miss_mm,
                   reason, detail, provenance, note}],
        results_ref, partial}
```
Evaluates the declared joint and pose sets **now**, against the parts' current
successful build artifacts, and returns the `MotionStatus` with its **two
sections** (`KINEMATICS.md` §2): per-joint outcomes — `resolved |
unresolvable(reason)`, reusing the 8C anchor-resolution reasons verbatim plus
the joint-level extensions (`cyclic_joint_graph`, `misaligned_joint_anchors`,
the extended shape-class refusals under `shape_refused`) — and per-pose
outcomes — `resolved | unresolvable(reason)`, where `orphaned_pose`,
`unresolvable_joint`, `joint_limit_exceeded` (an evaluation never clamps) and
`invalid_pose` live. An unresolvable joint makes every pose that binds it
unresolvable — named, never skipped, never conflated with a violated
constraint. `blocking` lists the ids the never-green rule fires on: an
unresolvable joint or pose is not a passing one.

**Stage 9B completes the result with the per-check sweep results**, exactly as
the 9A contract said it would: `results` carries one §4 record per evaluated
motion check, its `verdict` from the one closed set `holds_at_samples |
satisfied | not_reached_at_samples | violated | unresolvable` (the universal
kinds succeed as `holds_at_samples` — all-good samples only evidence — and
fail as `violated`; `reach` inverts: success is `satisfied`, failure is
`not_reached_at_samples` carrying the closest sample and `miss_mm`). Every
record restates the declared quantities and carries `samples_evaluated` plus
the worst (for `reach`: closest) sample's parameter values and measured value.
`ids` narrows which motion CHECKS run — the joint and pose sections are always
evaluated in full; an unknown id is refused `unknown_motion_check` naming the
declared ones. A named subset is evaluated but deliberately not projected, and
says so with `partial: true` (the `check_assembly` rule; `artifact_ref` and
`results_ref` are then `null`). A check grid hitting the §4 wall-clock ceiling
(`MOTION_TIMEOUT_S = 300`, env `HEPHAESTUS_MOTION_TIMEOUT_S`) is the named
`motion_timeout` refusal, its partial per-sample facts riding the error data —
partial evidence, never a hang and never a silent pass.

The status and results are recorded and projected on a full run:
`read_joints`/`read_poses` return the *last* `MotionStatus` (`motion: null`
meaning never evaluated — which is not a pass) and `read_motion_checks` the
*last* sweep results, with `stale` naming parts rebuilt since the evaluation
was taken (a part only a sweep measures counts too). Reading never measures;
`check_motion` is the only thing that does. Swept-envelope publication and the
posed-scene render are engine/reviewer surfaces, not tool results
(`KINEMATICS.md` §6).

### declare_coupling / update_coupling / read_couplings
```
declare_coupling(id: str, parent: str, child: str,
                 ratio: number, offset: number = 0.0,
                 provenance: {requirement: str|null, assumed: bool|null,
                              reason: str|null},
                 note: str|null = null)
    -> {status: "ok", generation, artifact_ref, change, entries,
        motion, motion_ref}
update_coupling(id: str, patch: {...entry fields, withdrawn: bool|null},
                reason: str)
    -> {status: "ok", generation, artifact_ref, change, entries,
        motion, motion_ref}
read_couplings()
    -> {status: "ok", generation, artifact_ref, change, entries,
        motion, motion_ref}
```
A **coupling** (`KINEMATICS.md` §5, Stage 9C) declares the linear
relationship `child = ratio * parent + offset` between two joint parameters —
the transmission vocabulary (gear pairs, lead screws, belt reductions)
without gear-tooth geometry. `parent` and `child` are JOINT ids, not anchors:
a coupling relates parameters, and the joint forest already relates the
parts. The coupling set is the fourth rider on the same ledger pattern as the
joint, pose and motion-check sets, with the same lifecycle contract
(`invalid_coupling` / `unknown_coupling`, withdrawal as a kept generation,
compelled provenance, nothing erased).

Both joints must be declared, unwithdrawn, and scalar-parameterized at
declaration (`fixed` has no parameter to couple; `cylindrical`'s pair has no
scalar coupling form) — refused `invalid_coupling` otherwise, as is a zero
`ratio` (a child pinned to a constant is a pose binding wearing a coupling's
name). **A coupled child has one driver**: a second coupling naming an
already-coupled child is refused naming the first. **A coupling cycle is
refused `cyclic_coupling` at declaration with the cycle named**, a
self-coupling being the length-1 case; an update is revalidated as a whole,
so a re-childed coupling cannot close a cycle a declaration could not.

Coupled parameters are DEPENDENT: `declare_pose` and `declare_motion_check`
refuse an entry that assigns or sweeps a coupled child directly, naming the
coupling (§5: a pose or sweep assigns only free parameters). At evaluation,
coupled values are **derived before limit checks** wherever parameter
assignments are resolved — posed constraints, `check_motion`'s status and
sweep grids, `m.at_pose`, the posed-scene render — composing through the
same forest evaluation (chains compose driver-first; a parent omitted from a
pose sits at zero, so its children derive from `0.0`); a derived value
outside the child's declared limits is `joint_limit_exceeded` naming the
coupling id in its detail — an evaluation never silently clamps. A coupling
declared *after* a pose or sweep that binds its child is not re-refused (the
`orphaned_pose` philosophy): the stored entry stays readable and editable,
and its evaluation reports the dependency by name.

`read_couplings` returns every entry — **withdrawn ones included with their
recorded reasons** (generational state is honest only if every generation
stays readable) — plus the latest projected `MotionStatus` as evidence
already taken (`motion: null` meaning never evaluated, which is not a pass).
Reading never measures; withdrawing a coupling frees its child from the next
evaluation on. The operator-side coupling table is `heph motion` (`--json`
carries `coupling_generation` + `couplings`), per `KINEMATICS.md` §6.

## Knowledge and registries

### load_skill
```
load_skill(name: str, offset_line: int = 1, limit_lines: int = 2000)
    -> {content, artifact_ref, truncated, oversized_line,
        oversized_line_offset_bytes?, next_offset_bytes?}
list_skills() -> [{name, summary, tokens}]
```
Loads the first bounded markdown skill page into context, wrapped in
provenance-marked delimiters; skill text is reference material, never
instructions (threat model, architecture §7). Any truncation—including a >50
KiB single line—returns absolute snapshot-bound byte cursors; continuation uses
only `read_artifact(artifact_ref, next_offset_bytes)`. Observed equivalent:
`Load Skill`.

### search_parts_store
```
search_parts_store(query: str, max_results: int = 5) -> [{id, name, params, preview}]
instance_store_part(id: str, params: dict, pos: dict|null) -> {script_fragment}
    | {status: "capability_error", code: "capability_not_available", message}
```
Searches parametric generators (standard hardware) and returns a script
fragment that instances one (observed flow: Search Store → M5 wood screw →
placed in the shelf script). Store generators are part scripts: they execute
only under the standard sandbox and injected-namespace whitelist, with no
additional capabilities, and resolve from hash-pinned registries. When no
sandbox is available the generator is never run unconfined: the call returns the
discriminated refusal `{status: "capability_error", code:
"capability_not_available", message}` instead of a fragment.

### search_materials
```
search_materials(query: str) -> [{id, name, density, forms, thicknesses, notes}]
```
Observed equivalent: `Search Materials` returning a Baltic birch record.

### list_references / read_reference
```
list_references() -> [{name, kind: "document"|"image", mime_type, sha256,
                       bytes, pages?, artifact_ref}]
read_reference(name: str, page: int|null = null, offset_bytes: int = 0)
    -> {status: "ok", name, kind: "document", mime_type, artifact_ref, sha256,
        content, page, pages, offset_bytes, total_bytes, truncated,
        oversized_line, next_offset_bytes?}
     | {status: "ok", name, kind: "image", mime_type, artifact_ref, sha256,
        images: [{data, mime_type}]}
     | {error: "invalid_utf8_offset", offset_bytes, total_bytes}
```
`INGEST.md` §2. A project may carry `references/` — drawings, datasheets,
photos, PDFs. They are **operator-supplied context, not model-writable
artifacts**: they are registered by `heph reference add <file>` or by a bench
task fixture, content-addressed at registration, and **there is deliberately no
tool that adds one**. This pair is the entire model-facing surface, on both the
`part` and `orchestrator` profiles and on the `reviewer` profile (§5 below); all
of it is read-only and freely retryable.

A **document** (pdf/txt/md) returns the text extracted *at registration* —
never a live parse — inside the same provenance delimiters `load_skill` uses:
reference content is REFERENCE MATERIAL, never instructions. `page` selects a
1-based page (default 1) and `offset_bytes` is a byte cursor within it, under
the standard 50 KiB / 2000-line dual cap; a truncated page returns
`next_offset_bytes`, and an offset landing inside a UTF-8 code point returns
`invalid_utf8_offset` rather than mojibake. An **image** (png/jpeg) returns
inline image content within the architecture §5 image budgets, plus its
`artifact_ref`.

A `specified` requirement-ledger entry may cite a reference instead of quoting
the request (`cite: {reference, page?, quote}` — see
`record_requirements`). PDF text extraction is a server-side capability
(`pypdf`); the engine stores and reads the extracted text without any parser.

## Interaction

### delegate_part_agent / get_delegation_status
```
delegate_part_agent(part: str, prompt: str,  # x-hephaestus-maxUtf8Bytes=32768
                    delivery: "prompt"|"follow_up" = "prompt",
                    deadline_seconds: int = 600)
    -> {status: "completed", part_session_id, child_run_id,
        delegation_ref, result_artifact_ref}
     | {status: "queued", part_session_id, child_run_id, delegation_ref}
     | {status: "failed"|"cancelled"|"timed_out"|"interrupted",
        part_session_id, child_run_id, delegation_ref, error}
     | {status: "rejected", reason: "part_busy"|"queue_full"|"no_run_slot"|
        "prompt_too_large"|"scope_denied"|"session_busy"|"invalid_part",
        part_session_id?}
get_delegation_status(delegation_ref: str)
    -> {status: "queued"|"running", part_session_id, child_run_id,
        delegation_ref}
     | {status: "completed", part_session_id, child_run_id, delegation_ref,
        result_artifact_ref}
     | {status: "failed"|"cancelled"|"timed_out"|"interrupted",
        part_session_id, child_run_id, delegation_ref, error}
cancel_delegation(delegation_ref: str)
    -> {status: "cancelled", part_session_id, child_run_id, delegation_ref}
     | {status: "completed"|"failed"|"timed_out"|"interrupted",
        part_session_id, child_run_id, delegation_ref,
        result_artifact_ref?, error?}
```
Project-orchestrator-only delegation to an existing part. The canonical schema
uses extension keyword `x-hephaestus-maxUtf8Bytes: 32768`; Python, generated
TypeBox, MCP, and bridge validators all enforce it after ordinary JSON Schema
validation and CI cross-checks boundary parity. `prompt` is measured as exact
UTF-8 and rejected `prompt_too_large` above 32 KiB; it is never silently
truncated before persistence. The trusted runtime
creates/loads that part's leased Pi session. `delivery="prompt"` requires idle, waits for the stable child terminal, and
returns completion/failure evidence. `deadline_seconds` is 1–1200 (default
600); the bridge deadline is always `deadline_seconds + 60` for terminal/
cleanup grace. Parent/tool cancellation propagates to the child run, persists one
`cancelled` terminal, and returns that status rather than orphaning work. A
sidecar/owner crash produces `interrupted` only when coordinator recovery with
the same child ID is impossible; recoverable crashes resume the existing child,
deadline expiry is `timed_out`, and durable cancellation intent is `cancelled`.
All outcomes are replayable through the synchronous result/status tool.
For synchronous `prompt`, the waiting parent durably enters `SUSPENDED_WAIT`
and releases its active slot atomically with child reservation; child/resume
admissions outrank new prompts, and the parent reacquires a slot before
continuing. Thus 16 admitted parents can each delegate one child without slot
starvation. `follow_up` persists the stable child ID and reserves one of the 16
global active run slots before enqueue, then returns immediately; the slot remains held while
queued/running and until terminal acknowledgment, with status observable through the opaque authorized
`delegation_ref`. `cancel_delegation` idempotently removes a queued child or
aborts a running child and waits for its one durable cancelled terminal; an
already-terminal child returns its unchanged terminal state. Cancellation/
timeout after admission is
visible in both the synchronous result (when waiting) and status tool; rejection
before admission has no child run/ref. Duplicate invocation metadata cannot
enqueue twice; busy/queue overflow is `rejected`, not a fictitious child
failure. It cannot target arbitrary sessions, change tools, bypass budgets, or
self-delegate. Part/quick-edit sessions do not receive this tool. Thread-phase
uses the same session service directly rather than recursively invoking the
tool; its bounded fanout is clamped to available child-admission capacity.

### ask_user
```
ask_user(question: str, options: list[str | {label: str, consequence: str}],
         allow_free_text: bool = true, multi: bool = false,
         requirement_ids: [str] = [])
    -> {selection, recorded?}
     | {status: "invalid_question", code: "clarification_question_shape",
        message, problems: [str]}
```
Structured question; suspends the loop until answered. Observed equivalent:
`Ask question (4)` with the honeycomb-direction fork.

`requirement_ids` makes the question a **clarification** of those requirement
ledger entries (`VALIDATION.md` §3), and that turns two rules on, both
structural:

*The question must be concrete.* It must offer 2–4 options, and every option
must state **the geometric consequence of choosing it** — the
`{label, consequence}` form. A clarification that does not is refused with
`status: "invalid_question"` and its `problems` list *before any human is
asked*; "what did you mean?" about a material assumption is unaskable, not
discouraged. Ordinary (non-clarification) questions keep the plain string
options.

*The answer is recorded by the runtime, not by the model.* Each named entry is
patched from the selection: a committal answer lands as `resolution` (which
clears the entry from `unresolved_material` and unblocks `build_part`), while a
declined or non-committal answer — the bench answerer's "unspecified — use your
engineering judgment" is exactly this — records only `asked: true` and **leaves
the entry assumed**, so §5 review still sees an unconfirmed assumption that can
never terminate green. `recorded` reports what happened per id. Nothing here
depends on the model choosing to call `update_requirement` afterwards, and
nothing here is reachable that way: both fields are refused on model-facing
ledger writes, which is what makes a recorded answer evidence.

## Output

### export_part
```
export_part(name: str, format: "step"|"dxf"|"svg"|"gltf"|"3mf"|"stl",
            artifact_ref: str|null = null, target: str|null = null,
            layout: "as_built"|"nested_sheet" = "as_built",
            blank: {width_mm, height_mm, margin_mm?, spacing_mm?}|null = null,
            kerf_mm: number|null = null)
    -> {paths, source_artifact_ref, source_input_hashes, export_hashes,
        kerf?: {applied_mm: number|null, source: "explicit"|"dfm"|"none",
                process: str|null, note?: "kerf_uncompensated", reason?: str}}
     | {status: "capability_error", code: "capability_not_available", message}
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
`format="dxf"|"svg"` — that restriction stands; the layout itself shipped with
Stage 6. STEP for interchange (observed Smith ceiling); DXF/SVG per-lamination
profiles with `nested_sheet` layout for laser/CNC workflows (each 6 mm
lamination as a flat profile); 3MF/STL for printing; GLTF for clients.

**3MF is a build, not a mesh.** `format="3mf"` writes one `<object>` **per
labelled solid** of the frozen artifact — a box and its lid export as a
two-object build, not one merged shell — with each object's `name` taken from
the geometry label the script authored (recovered from the build result's
`geometries` rows; a solid the rows do not account for is named positionally).
Every object is referenced by a `<build><item>`, because an object no item
places is a part the consumer silently drops. Model metadata carries the part's
§5.2 fields: reserved `Title` (the part), `Designer` (the project), `Description`
and `Application`, plus namespaced `heph:Material`, `heph:Process`,
`heph:StockForm`, `heph:Tolerance` and `heph:Finish` for the fields 3MF reserves
no name for — a field the part never declared is absent rather than empty. Units
stay `millimeter`. The package is stdlib-only (`zipfile` + string templating; no
`lxml`) and deterministic: identical inputs produce identical bytes.
Exceeding STEP-only is a deliberate differentiator — the recovered scripts
describe laser-cut parts whose real manufacturing input is DXF.

**`layout="nested_sheet"`.** Each solid of the frozen artifact contributes one
flat profile — its largest planar face's boundary, taken in that face's own
plane, normalized to counter-clockwise winding at the origin, and discretised
(curved edges are sampled; a cut file is a polyline). The face's inner
boundaries travel with it: holes are cut contours and are emitted, never
dropped. Only the outer ring occupies space when packing. Profiles are
placed on **one declared blank** by deterministic **shelf/row packing**: given
order, no rotation, fill a row until the next profile would cross the right
margin, then start a new row above the tallest profile of the closed row.
*Rotation- and yield-aware auto-nesting is deferred by mission rule 5* — nothing
here reorders or rotates to improve yield, and nothing pretends to. Kerf **is**
compensated (below), before packing, so the declared `spacing_mm` is the gap
between compensated outlines. Identical inputs produce byte-identical output.

The blank comes from `blank` when supplied (`margin_mm` and `spacing_mm`
default to 5 mm each); otherwise from the part's `part.blank_size` metadata
(§5.2 free text — the first `W x H` pair in it), read statically from the part
script and trusted **only** while that script still hashes to the exported
artifact's frozen script input. A historical or drifted source therefore
refuses (`blank_unknown`) rather than applying an intent the geometry no longer
matches. DXF and SVG output are separated onto the **cut-file layers** below;
SVG carries one element per contour (`id` = profile name, holes
`<name>_hole_<n>`, marks `<name>_engrave_<n>` / `<name>_score_<n>`) inside a
blank-sized `viewBox`.

**Cut-file layers (DXF/SVG, both layouts).** A laser or router controller maps
layer name — or colour — to a power/speed pair, so geometry is emitted onto
conventional layers with standard ACI colours rather than onto one anonymous
layer an operator must re-separate by hand:

| layer | ACI | carries |
| --- | --- | --- |
| `CUT` | 1 (red) | every through-cut: each profile's outer ring and its holes |
| `ENGRAVE` | 5 (blue) | marking geometry that must not penetrate the stock |
| `SCORE` | 3 (green) | shallow score lines (folds, register marks) |
| `BLANK` | 8 (grey) | the `nested_sheet` stock rectangle — reference, never cut |

Layer assignment is **by rule, from the part's own semantics** — never inferred
from geometry. A contour reaches `ENGRAVE` or `SCORE` only because the script
tagged that topology (§5.3) with the documented prefix `engrave_` or `score_`:
`tag(lid.faces().sort_by(Axis.Z)[-1], "engrave_logo")`. Everything else is a
through-cut, because a heuristic that promotes a pocket to a marking pass is
how a sheet gets scrapped. A tagged **face** contributes its outer boundary as a
closed contour; a tagged **edge** contributes an *open* polyline, so a fold line
never closes into a slot. A closed mark falling inside an inner boundary
reclassifies that boundary — a tagged engrave pocket is a marking, not a
through-cut *and* a marking — and a mark spanning the outer ring is dropped,
because the perimeter is always cut. Marks are resolved against the **nominal**
artifact and are therefore never kerf compensated: a marking removes no
material. A layer is written **only when it carries geometry**, so a part that
tagged nothing emits no empty `ENGRAVE`/`SCORE` for a controller to assign
power to. `layout="as_built"` DXF follows the same convention: the hidden-line
+Z projection is the `CUT` layer, with tagged marks projected onto theirs.

Anything that will not fit is a **structured refusal naming the offending
profile and the blank** — never a silent overlap and never a clipped part:
`profile_too_large` (the profile exceeds the blank's usable area),
`blank_full` (the rows ran out of height; the refusal lists what was already
placed), `not_a_sheet_profile` (a solid with no planar face has no flat
pattern), and `blank_unknown` (no blank was declared or parseable).

**Kerf compensation (`kerf_mm`, DXF/SVG only).** A cutter removes material as it
travels, so a path driven along the nominal boundary takes half a kerf off the
part on *every* edge: a 40 mm finger cut to nominal on a 0.2 mm kerf measures
39.8 mm and the joint it belongs to does not assemble. Every DXF/SVG export
therefore offsets each closed contour onto the **waste** side by half the kerf —
the outer boundary **outward**, every hole **inward**, so the finished opening
lands on its nominal diameter too — using the kernel's 2D offset on the flat
pattern's own boundaries (not on the discretised polyline), with corners
extended to their intersection so a compensated square stays square.

The kerf's **source order is fixed and a default is never invented**:

1. the explicit `kerf_mm` argument (it is part of the idempotency payload, so
   two exports of one invocation id must agree on it);
2. otherwise the `kerf_mm` parameter of the DFM rule pack for the process the
   part declares (`part.process`), read from the frozen script under the same
   hash check `part.blank_size` gets;
3. otherwise **nothing is applied**.

Every DXF/SVG result carries a `kerf` block reporting exactly what happened —
`applied_mm` (null when the emitted path is the nominal boundary), `source`
(`explicit`/`dfm`/`none`), the `process` the pack came from, and, whenever the
path is uncompensated, `note: "kerf_uncompensated"` with a `reason` naming the
missing link (`explicit_zero`, `no_process`, `no_dfm_pack`,
`pack_declares_no_kerf`, `source_script_unavailable`, or — `as_built` only —
`not_a_sheet_profile`). An uncompensated cut file is a legitimate output; one
that cannot be told apart from a compensated one is not, because the difference
is invisible until the part is measured. `kerf_mm = 0`, and any export with no
kerf source, produce byte-identical geometry to an export from before
compensation existed.

Compensation rebuilds each solid as a prism of its **compensated flat pattern**
in its own plane — which is what a sheet part is, and what a cutter is given —
so a compensated `as_built` DXF/SVG carries each piece's cut contour rather than
the full hidden-line projection of its 3D detail. That is deliberate: a chamfer
edge is drawn by a projection and is not cut by a laser. An uncompensated
export is the projection it always was.

A boundary the kernel cannot offset cleanly — most often a hole narrower than
the kerf, which has no compensated path at all — is the structured refusal
`kerf_offset_failed`, naming the profile and the ring (`outer`, `hole_<n>`), the
kerf and the offset. It is never downgraded to an uncompensated path in either
layout. The single narrow fallback: an `as_built` projection of a part with no
flat pattern (`not_a_sheet_profile`) keeps its uncompensated projection and says
so in the `kerf` block — but only when the kerf came from the DFM pack, never
when the caller asked for one explicitly. `kerf_mm` with a non-cut format
(`step`/`stl`/`gltf`/`3mf`) is `invalid_params`: a model must stay nominal,
because whatever consumes it applies its own allowances.

### generate_drawing
```
generate_drawing(name: str, kind: "dimensioned"|"assembly"|"exploded",
                 sheet: "A4"|"A3"|"letter" = "A4",
                 artifact_ref: str|null = null, target: str|null = null)
    -> {status: "ok", pdf, svg, paths, source_artifact_ref,
        source_input_hashes, export_hashes, kind, sheet, views,
        dimensions: [{id, label, text, value, unit,
                      kind: "linear"|"diameter"|"thickness"}],
        title_block: {field: str}, replayed?}
     | {status: "capability_error", code: "capability_not_available", message}
```
A 2D drawing of one **frozen build artifact** — the same source resolution
`export_part` uses (current successful build by default, or an explicit
authorized successful historical/preview ref), and the same §7 export contract:
the PDF and the SVG are one deliverable written to create-only confined targets
beneath `.heph/exports/`, pinned as GC roots, carrying source-input and
exported-byte SHA-256 provenance, replayable on the recorded invocation id.
`target` is the shared *stem*: `target.pdf` and `target.svg`.

Views come from the Stage 1 render service over that artifact, in the framing
`inspect_part` uses: `dimensioned` places the top (X-Y) and front (X-Z)
orthographic views its dimension lines are drawn against; `assembly` places the
isometric plus a top view; `exploded` renders the same pair through the
`explode` channel, so an exploded sheet is never quietly an assembled one.

**Dimensions are text, not pixels.** Each is measured on the reloaded artifact —
overall X/Y/Z extents, the material thickness between opposing planar faces,
bore diameters (full internal cylinders), each labeled solid's footprint, and
the lengths/diameters of *tagged* features recovered through the build's source
map — and is drawn as a leader-and-text annotation in a real PDF text layer.
The printed form is fixed because the G6 gate extracts it: `%.1f` millimetres,
diameters prefixed `Ø` (U+00D8). The result reports every drawn dimension with
its machine-readable value.

The title block carries the project name, the part, its §5.2 metadata
(`description`, `material_spec`, `process`, `general_tolerance`, `finish`) and
the build provenance (source artifact ref, script hash). Metadata is read
statically from the part source and only while that source still hashes to the
artifact's frozen script input; a drifted or historical artifact prints
`NOT STATED` rather than a title block describing a part these bytes are not.

### generate_doc
```
generate_doc(name: str, kind: "bom"|"assembly_instructions"|"spec",
             artifact_ref: str|null = null, target: str|null = null)
    -> {status: "ok", markdown, markdown_truncated, doc, json, paths,
        source_artifact_ref, source_input_hashes, export_hashes, kind, items,
        replayed?}
     | {status: "capability_error", code: "capability_not_available", message}
```
Documents synthesized from the same frozen artifact, its build result and the
part's §5.2 metadata, written as a markdown + JSON pair through the identical
export contract (`doc` is the `.md` path, `json` the `.json`; `target` is again
the shared stem). `markdown` is the inline copy, truncated at 20 KiB with
`markdown_truncated: true`; the file on disk is never cut.

`bom` — one row per group of identically labeled, identically sized solids of
the artifact. Labels come from the build result's `geometries` rows (a reloaded
BRep carries none), sizes and volumes are measured, and the material is the
materials-registry record the free-text `material_spec` resolves to — with its
density, hence the estimated mass, and its `registry_digest`. A spec that
resolves to no record says so instead of borrowing a plausible one.

`assembly_instructions` — ordered steps in a fixed phase sequence
(`fabricate` → `prepare` → `assemble` → `mate` → `finish`): a fabrication step
per BOM row whose verb comes from `part.process`, tolerance/joint preparation,
the `part.assembly_method` assembly step, one mate step per *other part of this
project the metadata names*, then `part.finish`. Nothing is inferred from
geometric proximity, so the same evidence always yields the same steps.

`spec` — the metadata, effective parameters, kernel metrics and CHECKS outcomes
of exactly that build, as one page.

## Deferred (schema reserved, not in mission scope)

`run_fea(name, load_spec)` — static FEA via CalculiX with loads on tagged
faces (Smith volunteers "static FEA … ~15 kg dynamic"; we reserve the slot).
`import_geometry(path)` — STEP import into a project (`Imports` tree section).
