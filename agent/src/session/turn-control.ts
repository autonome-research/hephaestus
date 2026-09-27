// Closed per-turn interaction, manufacturing-context, and effort semantics.
//
// INTERFACE.md §7A.10A makes these values a turn snapshot, not session-wide UI
// state. Validation happens again in the sidecar before admission. Plan tools
// are an explicit classification of today's generated surface: no startsWith
// predicate can silently admit a future tool, and intersection with the
// profile's immutable allowlist can never broaden that profile.

export const INTERACTION_MODES = ["modeling", "plan"] as const;
export const DFM_MODES = ["off", "general", "additive", "sheet_metal", "machining", "casting"] as const;
export const THINKING_LEVELS = ["low", "medium", "high"] as const;

export type InteractionMode = (typeof INTERACTION_MODES)[number];
export type DfmMode = (typeof DFM_MODES)[number];
export type TurnThinkingLevel = (typeof THINKING_LEVELS)[number];

export interface TurnControl {
  readonly interactionMode: InteractionMode;
  readonly dfmMode: DfmMode;
  readonly thinkingLevel: TurnThinkingLevel;
}

export const DEFAULT_TURN_CONTROL: TurnControl = {
  interactionMode: "modeling",
  dfmMode: "off",
  thinkingLevel: "medium",
};

const PLAN_INSPECTION_TOOLS: ReadonlySet<string> = new Set([
  "read_part",
  "read_globals",
  "read_project_check",
  "read_artifact",
  "read_requirements",
  "read_constraints",
  "read_joints",
  "read_poses",
  "read_motion_checks",
  "read_couplings",
  "read_proposals",
  "read_reference",
  "list_project_checks",
  "list_skills",
  "list_references",
  "search_parts_store",
  "search_materials",
  "inspect_part",
  "measure",
  "compare_solids",
  "compare_to_scan",
  "query_snapshot",
  "get_delegation_status",
]);

const PLAN_CONTEXT = [
  "# Turn interaction mode",
  "Plan mode is active for this turn. Inspect the available project evidence and return an actionable plan.",
  "Do not claim that the plan changed the project; mutation and delegated-write tools are unavailable.",
].join("\n");

const DFM_CONTEXT: Readonly<Record<Exclude<DfmMode, "off">, string>> = {
  general: "Review the design for general manufacturability considerations.",
  additive: "Review the design in the context of additive manufacturing.",
  sheet_metal: "Review the design in the context of sheet-metal manufacturing.",
  machining: "Review the design in the context of machining.",
  casting: "Review the design in the context of casting.",
};

function closedValue<T extends string>(
  params: { [key: string]: unknown },
  key: string,
  values: readonly T[],
  fallback: T,
): T {
  if (!(key in params)) return fallback;
  const value = params[key];
  if (typeof value !== "string" || !values.includes(value as T)) {
    throw new Error(`${key} must be one of ${values.join(", ")}`);
  }
  return value as T;
}

export function readTurnControl(params: { [key: string]: unknown }): TurnControl {
  return {
    interactionMode: closedValue(params, "interaction_mode", INTERACTION_MODES, "modeling"),
    dfmMode: closedValue(params, "dfm_mode", DFM_MODES, "off"),
    thinkingLevel: closedValue(params, "thinking_level", THINKING_LEVELS, "medium"),
  };
}

export function activeToolsForTurn(
  profileTools: readonly string[],
  interactionMode: InteractionMode,
): string[] {
  if (interactionMode === "modeling") return [...profileTools];
  return profileTools.filter((name) => PLAN_INSPECTION_TOOLS.has(name));
}

/** Bounded, application-owned context. It never invokes DFM or changes settings. */
export function turnContextBlock(existing: string | undefined, control: TurnControl): string | undefined {
  const blocks: string[] = [];
  if (existing !== undefined) blocks.push(existing);
  if (control.interactionMode === "plan") blocks.push(PLAN_CONTEXT);
  if (control.dfmMode !== "off") {
    blocks.push([
      "# Manufacturing review context",
      DFM_CONTEXT[control.dfmMode],
      "This is bounded review context only. Do not invoke run_dfm, change automatic DFM settings, or make manufacturing-safety claims.",
    ].join("\n"));
  }
  return blocks.length === 0 ? undefined : blocks.join("\n\n");
}
