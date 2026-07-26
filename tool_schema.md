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
  warnings: [W]   // the flattened union of the three sections
}
W = {kind: "interference"|"interference_pairs_capped"|"interference_unavailable"
          |"not_sealed"|"unmatched_request_number"|"dimension_mismatch",
     message, ...per-kind evidence}
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
                     quote: str|null, from: [str], rationale: str|null,
                     material: bool|null, value: number|null,
                     unit: str|null, applies_to: str|null}])
    -> {status: "ok", generation, artifact_ref, entries, unresolved_material}
read_requirements()
    -> {status: "ok", generation, artifact_ref, entries, unresolved_material}
update_requirement(id: str, text: str|null = null,
                   source: "specified"|"derived"|"assumed"|null = null,
                   quote: str|null = null, from: [str]|null = null,
                   rationale: str|null = null, material: bool|null = null,
                   value: number|null = null, unit: str|null = null,
                   applies_to: str|null = null)
    -> {status: "ok", generation, artifact_ref, entries, unresolved_material}
```
The ledger makes interpretation an inspectable artifact instead of an implicit
act. One entry per constraint, emitted **before** any geometry. `source` is
`specified` (traceable to a phrase of the request — `quote` required and
checked), `derived` (computed from other entries — `from` lists their ids, and
every id must resolve), or `assumed` (the model supplied it — `rationale`
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
`unsourced_requirement`.

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
            blank: {width_mm, height_mm, margin_mm?, spacing_mm?}|null = null)
    -> {paths, source_artifact_ref, source_input_hashes, export_hashes}
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
*Kerf-aware auto-nesting is deferred by mission rule 5* — nothing here
compensates a cut width or reorders/rotates to improve yield, and nothing
pretends to. Identical inputs produce byte-identical output.

The blank comes from `blank` when supplied (`margin_mm` and `spacing_mm`
default to 5 mm each); otherwise from the part's `part.blank_size` metadata
(§5.2 free text — the first `W x H` pair in it), read statically from the part
script and trusted **only** while that script still hashes to the exported
artifact's frozen script input. A historical or drifted source therefore
refuses (`blank_unknown`) rather than applying an intent the geometry no longer
matches. DXF output carries the profiles on layer `PROFILES` and the blank
outline on layer `BLANK`; SVG output carries one `<polygon>` per cut contour
(`id` = profile name, holes `<name>_hole_<n>`) inside a blank-sized `viewBox`.

Anything that will not fit is a **structured refusal naming the offending
profile and the blank** — never a silent overlap and never a clipped part:
`profile_too_large` (the profile exceeds the blank's usable area),
`blank_full` (the rows ran out of height; the refusal lists what was already
placed), `not_a_sheet_profile` (a solid with no planar face has no flat
pattern), and `blank_unknown` (no blank was declared or parseable).

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
