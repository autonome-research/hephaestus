# Agent tool catalogue

> **Verified against** `16f9613` on 2026-09-12.
> Counts printed from `hephaestus.contract.tools_decl`: 57 tools, 27 sequential,
> 27 idempotent, 4 profiles; `ls schemas/tools/ | wc -l` = 57.

A model drives Hephaestus through a **declared** tool catalogue. The declaration
is data in one module, and everything else — JSON Schemas, TypeScript types, MCP
declarations, the reviewer subset, the profile gate — is derived from it.

## One declaration, four generated artifacts

`contract/src/hephaestus/contract/tools_decl.py` is the single source of truth.
`toolgen` renders it to:

| Artifact | What it is |
| --- | --- |
| `schemas/tools/*.schema.json` | 57 committed canonical JSON Schemas, one per tool |
| `agent/src/tools/schema.gen.ts` | the TypeScript sidecar's TypeBox module |
| `schemas/mcp/` | the MCP declarations |
| `tool_schema.md` headings | the normative prose surface |

Those artifacts, this declaration and the `tool_schema.md` headings are
**drift-tested against each other in CI**. Regenerating is a build step, not an
editing step; hand-editing a generated schema fails the suite.

The `contract` package declares **no third-party dependencies**, which is what
lets the tool contract be tested and reasoned about without the CAD kernel
present. It carries its own staged copy of `bridge_limits.json` rather than
importing `hephaestus.core` for one.

## What a declaration carries

```python
@dataclass(frozen=True)
class ToolDecl:
    name: str
    summary: str
    params: JsonSchema
    result: JsonSchema
    profiles: tuple[str, ...]
    sequential: bool
    idempotent: bool
    max_utf8_fields: dict[str, int] = …
```

No numeric limit is ever a literal here. The prompt UTF-8 cap, the delegation
deadline bounds and the images-per-result cap are read from
`schemas/bridge_limits.json` at import time. The custom JSON Schema keyword
`x-hephaestus-maxUtf8Bytes` is emitted on the fields it guards and enforced by
every validator **after** ordinary JSON Schema validation — because JSON Schema's
`maxLength` counts code points, not bytes.

## Profiles

Four profiles. A session has one, and it decides what the session may call.

| Profile | Tools available | What it is |
| --- | --- | --- |
| `orchestrator` | 57 | the operator-equivalent session; addresses every part |
| `part` | 46 | bound to one normalized part id |
| `quick_edit` | 20 | a narrow edit session |
| `reviewer` | 5 | the independent termination-review child |

The reviewer's five are `inspect_part`, `measure`, `read_artifact`,
`list_references`, `read_reference` — a read-only measurement and render subset,
declared as data so the structural "no mutation, no delegation" audit has one
place to read.

**The reviewer's inability to mutate the project is a property of this table, not
of its prompt.** That is the point of declaring availability per tool: a prompt
can be argued with, a table cannot.

`list_references` and `read_reference` are in the subset because an image
citation is lint-unverifiable, so the reviewer is the only thing that can verify
it — and it can only do that by opening the drawing itself.

## The two boolean flags

`sequential` and `idempotent` are both true of 27 tools, but they are **not the
same 27**:

- `ask_user` is sequential and not idempotent — it blocks the turn on a human,
  and asking twice is asking twice.
- `solve_pose` is idempotent and not sequential — it proposes rather than writes,
  so it can run alongside others, and the same invocation id replays.

Every mutation family is idempotent on the **trusted invocation id** through
opstore opkeys: a retry of a committed write replays the recorded outcome, and a
same-id-different-payload presentation is a hard mismatch.

Two families resolve a retry to a **discriminated result** rather than a replay,
because their compare-and-swap gate runs in front of the idempotency key:

- `edit_part` / `write_part` return `conflict` carrying the live hash they wrote
  themselves;
- the project-check family returns `already_exists` (create) or
  `conflict(kind="stale_hash")` (edit).

Neither duplicates work nor discards bytes — the caller reconciles from the
returned live hash. `edit_globals` claims its key *before* the CAS precisely so
it replays `applied` instead.

## The catalogue

### Parts and source

`create_part`, `read_part`, `write_part`, `edit_part`, `set_params`,
`read_globals`, `edit_globals`, `instance_store_part`, `search_parts_store`.

`read_globals` and `edit_globals` are orchestrator-only: the `hc` namespace is
shared across parts, so a part-scoped session editing it would reach outside its
own scope.

### Build, check and measure

`build_part`, `run_checks`, `run_dfm`, `inspect_part`, `measure`,
`compare_solids`, `compare_to_scan`, `query_snapshot`, `read_artifact`.

### Project checks — orchestrator only

`create_project_check`, `edit_project_check`, `read_project_check`,
`list_project_checks`.

### Assemblies, joints, motion, poses

`declare_constraint`, `update_constraint`, `read_constraints`, `check_assembly`;
`declare_joint`, `update_joint`, `read_joints`;
`declare_coupling`, `update_coupling`, `read_couplings`;
`declare_pose`, `update_pose`, `read_poses`;
`declare_motion_check`, `update_motion_check`, `read_motion_checks`,
`check_motion`.

Each family follows the same declare / update / read shape, which is why a reader
who learns one learns all five.

### Placement

`solve_pose`, `propose_placement`, `read_proposals`.

A solve **proposes**; it does not move geometry. `propose_placement` is
orchestrator-only because a placement spans parts.

### Requirements

`record_requirements`, `update_requirement`, `read_requirements`.

A ledger entry declares one of three provenance classes: `specified`, `derived`,
`assumed`. Ledger ids are deliberately a wider grammar than part names
(`^[A-Za-z][A-Za-z0-9_.-]{0,31}$`) because a ledger id is a citation token that
appears verbatim in check comments, not a filesystem name.

### References and registries

`list_references`, `read_reference`, `list_skills`, `load_skill`,
`search_materials`.

The registry family runs over **hash-pinned** registries.

### Egress

`export_part`, `generate_drawing`, `generate_doc`.

`export_part` keeps `layout="nested_sheet"` in the schema, permitted only with
`format="dxf"` or `"svg"`.

### Delegation — orchestrator only

`delegate_part_agent`, `get_delegation_status`, `cancel_delegation`.

### Interaction

`ask_user`.

### Declared elsewhere, not in scope

`run_fea` and `import_geometry` appear in `tool_schema.md` and are explicitly
excluded; the drift test subtracts them from the heading set before comparing.
They are named rather than silently absent.

## How a call is resolved

The sidecar sends `py.tool_dispatch {session_id, run_id, tool, arguments,
invocation}`. The dispatcher resolves it against a bound session principal in
three steps:

1. **Profile availability.** A tool is dispatchable only by a session whose
   profile is in `ToolDecl.profiles`. Otherwise `scope_denied`.
2. **Object scope.** A `part` or `quick_edit` session is bound to one normalized
   part id. Any tool addressing a *different* part — by `name`, by `part`, or by
   a cross-part `"<part>/<selector>"` measurement selector — is `scope_denied`,
   as is a nameless `scope="project"` `set_params` or `run_checks`. The
   orchestrator addresses every part.
3. **Core routing.** File-CRUD goes through `ProjectStore`; everything geometric,
   parametric, check-, artifact- or export-related goes through `CadOps`; the
   delegation family through `DelegationService`; `query_snapshot` through
   `QuerySnapshotService`; the registry family through `RegistryOps`.

Authorization, capability and not-implemented failures raise a `DispatchError`
carrying a stable `reason`. The supervisor maps it to a JSON-RPC error frame, and
the sidecar proxy turns recognized `capability_not_available` and
`image_model_required` codes into **discriminated tool results** rather than
errors — see [refusals](refusal-vocabulary.md).

## Paging

`read_artifact` pages at 49152 bytes (48 KiB) by default. That is a *tool*
default, not a bridge limit, and it is not in `bridge_limits.json` for that
reason.

Image results are capped at 4 per result, both as a limit and as a schema
`maxItems`. See [limits](limits-and-configuration.md).
