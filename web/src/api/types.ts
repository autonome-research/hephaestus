// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The wire shapes this client reads, transcribed from the routes that serve
// them (INTERFACE.md §2.3) rather than invented here.
//
// These are *read* types only. Nothing in this file is a computed shape: every
// field below is a field the server sends, and the `<Fact source="…">` paths
// used in the panels index into exactly these documents (§1, §4.6). Where a
// server field is optional it is optional here too, because a `?` that the
// server can omit and the client assumes present is how a named absence turns
// into a silent zero.

/** `GET /api/v1/project` — `open_project_projection` (`agent_bridge/project_projections.py`). */
export interface ProjectDocument {
  readonly status: "ok";
  readonly root: string;
  readonly name: string;
  readonly units: string;
  readonly parts: readonly string[];
  readonly serve_mode: boolean;
  /** §2.3, closed at `CAPABILITY_KEYS`. An open map would be a key-sniffing surface. */
  readonly capabilities?: { readonly secure_executor: boolean; readonly git: boolean };
}

/** One row of `GET /api/v1/parts` — `list_parts_projection`. */
export interface PartSummary {
  readonly name: string;
  /** Relative to the project root: no route hands back an absolute path (§2.3). */
  readonly path: string;
  readonly content_hash: string;
  readonly snapshot_ref: string;
}

export interface PartsDocument {
  readonly status: "ok";
  readonly parts: readonly PartSummary[];
}

/** One `BuildResult.geometries` entry (`core/types.py::GeometryEntry`). */
export interface GeometryEntry {
  readonly label: string;
  readonly solids: number;
}

export interface BuildWarning {
  readonly kind: string;
  readonly tag?: string;
  readonly detail: string;
}

/**
 * `GET /api/v1/parts/{part}/build` — the §2.3 BuildResult projection.
 *
 * `geometry_count` is an **explicit server field** (§6.1's TIGHTENING binding
 * G4.2), and it is the number the tree renders. The client never recounts it
 * from `geometries`, never reads it off the GLTF, and never derives it from the
 * selection table — three plausible numbers exist and the gate names this one.
 */
export interface BuildDocument {
  readonly status: "ok" | "error" | "not_built";
  readonly current: boolean;
  readonly geometry_count: number;
  readonly geometries: readonly GeometryEntry[];
  // Both are `str | None` on `BuildResult`, and the projection passes them
  // through unchanged — so both arrive as `null` on a build that has neither.
  // Typing them `string | undefined` said the key would be absent, which is a
  // different absence; the recorded fixture (`web/test/fixtures/build.json`)
  // caught the drift.
  readonly artifact_ref?: string | null;
  readonly project_snapshot_ref?: string | null;
  readonly effective_params?: Readonly<Record<string, unknown>>;
  readonly metrics?: Readonly<Record<string, unknown>> | null;
  readonly checks?: Readonly<Record<string, unknown>>;
  readonly source_map_ref?: string | null;
  readonly warnings?: readonly BuildWarning[];
  readonly error?: BuildError | undefined;
  readonly critique?: Readonly<Record<string, unknown>>;
}

/**
 * `BuildResult.error` (`core/types.py::ErrorRecord`) — the incremental
 * executor's failure object. The Timeline reads only these fields; it does not
 * invent statement events the projection does not carry.
 */
export interface BuiltThrough {
  readonly line: number;
  readonly statement: string;
}

/** `error.last_good` — metrics of the last-good checkpoint geometry. */
export interface LastGoodMetrics {
  readonly bodies: number;
  readonly solids: number;
  readonly size_mm: readonly number[];
  readonly volume_mm3: number;
  readonly sealed: boolean;
  readonly genus: number;
}

export interface BuildError {
  readonly line: number;
  readonly col: number;
  readonly type: string;
  readonly message: string;
  readonly frame: readonly string[];
  readonly built_through: BuiltThrough | null;
  readonly last_good: LastGoodMetrics | null;
  readonly last_good_artifact_ref: string | null;
  readonly hint: string;
}

/**
 * One row of `GET /api/v1/parts/{part}/params` — `params_projection`.
 *
 * Bounds, step, and the current value are the script's `PARAMS` as the server
 * projected them. The sliders render these fields and invent neither names nor
 * ranges (§10).
 */
export interface ParamRow {
  readonly name: string;
  readonly value: number;
  readonly default: number;
  readonly min: number;
  readonly max: number;
  readonly step: number | null;
  readonly doc: string;
  readonly scope: string;
}

/** `GET /api/v1/parts/{part}/params`. */
export interface ParamsDocument {
  readonly status: "ok";
  readonly params: readonly ParamRow[];
  readonly state_hash: string;
}

/** One `set_params` `rejected[]` entry (`cad_ops/_params.py`). */
export interface ParamRejection {
  readonly name: string;
  readonly reason: string;
  readonly value?: unknown;
  readonly min?: number;
  readonly max?: number;
  readonly declared?: readonly string[];
  readonly detail?: string;
}

/**
 * `POST /api/v1/parts/{part}/params` — `set_params` verbatim.
 *
 * A stale `expected_state_hash` is a 200 with `conflict`, not a 4xx (§2.4,
 * §10). `rejected[]` is all-or-nothing: if it is non-empty, nothing persisted.
 */
export interface SetParamsResult {
  readonly effective: Readonly<Record<string, number>>;
  readonly rejected: readonly ParamRejection[];
  readonly stale_parts: readonly string[];
  readonly state_hash: string;
  readonly journal_ref?: string;
  readonly conflict?: {
    readonly current_state_hash: string;
    readonly current_values: Readonly<Record<string, number>>;
  };
}

/**
 * `GET /api/v1/parts/{part}/script` — `read_part` verbatim.
 *
 * `tool_schema.md` §read_part: "Any truncated response returns snapshot-bound
 * absolute `next_offset_bytes`; all continuation uses `read_artifact(
 * snapshot_ref, offset_bytes=…)`, **never another mutable source read**." The
 * web continuation of that rule is `GET /artifacts/{snapshot_ref}/text`
 * (§2.6) — the same pager behind a different principal check.
 */
export interface ScriptDocument {
  readonly script: string;
  readonly content_hash: string;
  readonly snapshot_ref: string;
  readonly line_count: number;
  readonly truncated: boolean;
  readonly next_offset_bytes?: number;
  readonly oversized_line?: boolean;
  readonly oversized_line_offset_bytes?: number;
  readonly part_param_state_hash?: string;
  readonly project_param_state_hash?: string;
}

/** `GET /api/v1/artifacts/{ref}/text` — `core.artifacts.page_text` + mime. */
export interface ArtifactTextPage {
  readonly status: "ok";
  readonly mime_type: string;
  readonly content: string;
  readonly offset_bytes: number;
  readonly total_bytes: number;
  readonly truncated: boolean;
  readonly next_offset_bytes?: number;
}

/** One `--porcelain=v2` row, as `git_projection.git_status` projects it. */
export interface GitDirtyEntry {
  readonly path: string;
  /** Filled only for `parts/<name>.py`; §13.1 says dirtiness is a fact about those. */
  readonly part?: string | null;
  readonly index: string;
  readonly worktree: string;
}

/** `GET /api/v1/git/status` — §13.1's `{dirty[], clean, head, branch}`. */
export interface GitStatusDocument {
  readonly status: "ok";
  readonly dirty: readonly GitDirtyEntry[];
  readonly clean: boolean;
  readonly head: string | null;
  readonly branch: string | null;
}

/** One `GET /api/v1/git/log?part=` commit. */
export interface GitCommit {
  readonly sha: string;
  readonly short: string;
  readonly subject: string;
  readonly author_date: string;
  readonly tags: readonly string[];
}

export interface GitLogDocument {
  readonly status: "ok";
  readonly commits: readonly GitCommit[];
}

/** One `GET /api/v1/git/tags` row. §13.2 calls these releases, never "publish". */
export interface GitTag {
  readonly name: string;
  readonly object: string;
  readonly subject: string;
}

export interface GitTagsDocument {
  readonly status: "ok";
  readonly tags: readonly GitTag[];
}

/**
 * One inline image of an `inspect_part` result (`cad_ops/_build.py`:344-352).
 *
 * `data` is base64 PNG and is a **preview**: §12.2 says the inline composite "is
 * explicitly not palette-decodable and is used only as a thumbnail", and "**No
 * pixel assertion anywhere in G4 or G5 may be made against an inline preview**".
 * The workspace therefore displays a section plate from its
 * `render_artifact_ref` through `/artifacts/{ref}/bytes` (§2.6, byte-exact) and
 * ignores `data` entirely — the pixels on screen are then the same bytes the
 * golden comparison reads.
 */
export interface InspectImage {
  readonly mime_type: string;
  readonly view: string;
  readonly channel: string;
  readonly render_artifact_ref: string;
  readonly palette_decodable: boolean;
  readonly data: string;
}

/**
 * `POST /api/v1/parts/{part}/inspect` — `inspect_part` verbatim (§2.3),
 * "including its `capability_error` variant".
 *
 * The viewport uses exactly one call shape: `channel="section"` with a
 * `section_plane` and the pinned `artifact_ref` (§5.3, §12.1). The mask fields
 * are declared here because the result document carries them in other modes and
 * a type that omitted them would invite a widening later; nothing in the
 * viewport reads them.
 */
export interface InspectDocument {
  readonly status: "ok" | "capability_error";
  readonly source_artifact_ref: string;
  readonly images?: readonly InspectImage[];
  readonly render_artifact_refs?: readonly string[];
  readonly mask_legend_truncated?: boolean;
  readonly mask_legend?: string;
  readonly mask_legend_ref?: string;
  readonly selection_table_ref?: string;
  /** `capability_error` only: the closed code, `image_model_required`. */
  readonly code?: string;
  readonly message?: string;
}

/** §2.4's closed refusal envelope: `{status, reason, message, …data}`. */
export interface RefusalDocument {
  readonly status: "error";
  readonly reason: string;
  readonly message: string;
}

// ---------------------------------------------------------------------------
// The INSPECTOR's four read routes (§6) and the §12.3 resolution envelope.
// ---------------------------------------------------------------------------

/** The `part.*` metadata vocabulary — closed at nine names (`script_contract.md` §5.2). */
export type MetadataField =
  | "description"
  | "material_spec"
  | "process"
  | "stock_form"
  | "blank_size"
  | "general_tolerance"
  | "finish"
  | "assembly_method"
  | "joint";

/** Which read answered a properties projection. Closed (`http/projections.py`). */
export type PropertySource = "build_record" | "script_literals";

/**
 * `GET /api/v1/parts/{part}/properties` — the enumerated `part.*` projection.
 *
 * `properties` carries **exactly** the subset of the closed vocabulary the part
 * declares, and `fields` the whole vocabulary beside it, so an undeclared field
 * renders as a visible absence rather than as a silently missing row (§6.2).
 *
 * `source` is load-bearing rather than decorative: `build_record` means the
 * values are the ones the *worker evaluated*, so a computed
 * `part.blank_size = f"…"` is carried like a literal; `script_literals` means
 * the weaker static parse answered, which recovers string constants only.
 */
export interface PropertiesDocument {
  readonly status: "ok";
  readonly properties: Readonly<Partial<Record<MetadataField, string>>>;
  readonly fields: readonly MetadataField[];
  readonly source: PropertySource;
  /** The artifact the runtime metadata was evaluated with; `null` under the fallback. */
  readonly build_artifact_ref: string | null;
}

/** §6.3's closed badge vocabulary. `not_run` is a state, never a silent pass. */
export type CheckBadge = "pass" | "fail" | "error" | "not_run";

/** One `CheckResult` (`core/types.py`): the verdict and what was measured. */
export interface CheckResultDocument {
  readonly pass: boolean;
  readonly measured: unknown;
}

/** The `heph check --json` document, served verbatim by the shared serializer. */
export interface CheckReportDocument {
  readonly part: string;
  readonly check_set_generation: number;
  readonly check_bundle_ref: string;
  readonly file_hashes: Readonly<Record<string, string>>;
  readonly project_snapshot_ref: string | null;
  readonly motion_generations: Readonly<Record<string, number>> | null;
  readonly checks: Readonly<Record<string, CheckResultDocument>>;
}

/**
 * `GET /api/v1/parts/{part}/checks` — `report` plus the `badges` projection.
 *
 * §6.3: "The web client never runs checks." `badges` is the server's own reading
 * of the same report (`core/checks/report.py::badge`), so the panel renders a
 * verdict it was given rather than one it derived — `measured.error` outranking
 * `pass`/`fail` is an engine decision, not a UI one.
 */
export interface ChecksDocument {
  readonly status: "ok";
  readonly part?: string;
  readonly report: CheckReportDocument;
  readonly badges: Readonly<Record<string, CheckBadge>>;
}

/** `core/dfm/types.py::TopologyDescriptor` — an artifact-bound address. */
export interface TopologyDescriptor {
  readonly kind: "solid" | "face" | "edge" | "wire" | "vertex" | "other";
  readonly solid_id: number;
  readonly topology_index: number;
  readonly tag: string | null;
}

/** One `DfmFinding`. `topology` is why §6.4 forbids rendering a bare mask id. */
export interface DfmFinding {
  readonly rule_id: string;
  readonly severity: string;
  readonly title: string;
  readonly message: string;
  readonly process: string;
  readonly source_artifact_ref: string;
  readonly tags: readonly string[];
  readonly topology: readonly TopologyDescriptor[];
  readonly measured: unknown;
  readonly suggested_bound: number | null;
  readonly bound_unit: string;
}

/** One rule's outcome. `error` is set exactly when `status === "error"`. */
export interface DfmRuleOutcome {
  readonly rule_id: string;
  readonly title: string;
  readonly severity: string;
  readonly status: "ok" | "violations" | "error";
  readonly findings: readonly DfmFinding[];
  readonly params: Readonly<Record<string, number>>;
  readonly error: string | null;
}

/** Which artifact a DFM run was resolved against (`cad_ops/_dfm.py`, closed). */
export type DfmResolvedFrom = "current" | "artifact_ref" | "project_snapshot";

/** One recorded `run_dfm` evaluation — `DfmEvaluation.to_json()` plus its target. */
export interface DfmRun {
  readonly status: "ok";
  readonly part: string;
  readonly process: string;
  readonly source_artifact_ref: string;
  readonly pack: {
    readonly name: string;
    readonly version: string;
    readonly registry: string;
    readonly registry_digest: string;
  };
  readonly rules: readonly DfmRuleOutcome[];
  readonly findings: readonly DfmFinding[];
  readonly severity_counts: Readonly<Record<string, number>>;
  readonly errored_rules: readonly string[];
  readonly truncated: boolean;
  readonly resolved_from: DfmResolvedFrom;
  readonly material: Readonly<Record<string, unknown>> | null;
}

/**
 * `GET /api/v1/parts/{part}/dfm` — the last run plus the project setting.
 *
 * Two different facts in one body, and §6.4 keeps them apart: `auto_run` is
 * `[dfm] auto_run` in `hephaestus.toml` — a *project setting* — while `last` is
 * the most recent recorded evaluation. Before any run `last` is `null`: a named
 * absence, never an empty finding list, because an empty list reads as "no DFM
 * problems".
 */
export interface DfmDocument {
  readonly status: "ok";
  readonly part: string;
  readonly auto_run: boolean;
  readonly last: DfmRun | null;
  readonly resolved_from: DfmResolvedFrom | null;
}

/** §4.4's three popover shapes, closed. Each is a designed state, not a gap. */
export type ProvenanceState = "tagged" | "owned" | "unattributed";

/**
 * `POST /api/v1/parts/{part}/selection/resolve` — §12.3's response.
 *
 * **No route serves this yet** (§19 item 8: the concrete `SelectionResolver`,
 * the `selection-crop` kind and its GC links are named new work). The type is
 * transcribed from §12.3's response shape and the panel that renders it is
 * driven by recorded fixtures assembled around real selection-table entries; see
 * `web/test/fixtures/README.md`. It is declared here rather than inside the
 * panel so the day the route lands, the panel is already the thing that reads
 * it.
 *
 * `provenance.state` is §4.4's vocabulary. `provenance.reason` carries the one
 * case §4.4 singles out: a face that *is* tagged whose pinned build's source map
 * is no longer stored renders `owned` **with the reason said out loud**, because
 * "the machinery cannot attribute this face" and "the attribution existed and
 * was not retained" are different facts.
 */
export interface ResolvedSelection {
  readonly status: "ok";
  readonly selection_id: number;
  readonly kind: "solid" | "face" | "edge";
  readonly solid_index: number;
  readonly topology_index: number;
  readonly tag: string | null;
  readonly label: string | null;
  readonly line: number | null;
  readonly source_artifact_ref: string;
  readonly bundle_ref: string;
  readonly selection_table_ref: string;
  readonly provenance: {
    readonly state: ProvenanceState;
    readonly statement_line?: number | null;
    readonly reason?: string;
  };
  readonly crop_artifact_ref: string | null;
}
