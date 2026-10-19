// INTERFACE.md §7A.10A. Choices belong to one admitted turn, not the session.
import type { AgentSession } from "@earendil-works/pi-coding-agent";
import { modelError } from "./model-selection.js";
import { enforceMaxUtf8Bytes, PROMPT_MAX_UTF8_BYTES } from "../limits.js";

export interface TurnControls {
  readonly interaction_mode: "modeling" | "plan";
  readonly dfm_mode: "off" | "general" | "additive" | "sheet_metal" | "machining" | "casting";
  readonly thinking_level: "low" | "medium" | "high";
}

export function readTurnControls(params: Readonly<Record<string, unknown>>): TurnControls {
  const mode = params.interaction_mode === undefined ? "modeling" : params.interaction_mode;
  const dfm = params.dfm_mode === undefined ? "off" : params.dfm_mode;
  const effort = params.thinking_level === undefined ? "medium" : params.thinking_level;
  if (mode !== "modeling" && mode !== "plan") throw modelError("invalid_params");
  if (dfm !== "off" && dfm !== "general" && dfm !== "additive" && dfm !== "sheet_metal" && dfm !== "machining" && dfm !== "casting") throw modelError("invalid_params");
  if (effort !== "low" && effort !== "medium" && effort !== "high") throw modelError("invalid_params");
  return Object.freeze({ interaction_mode: mode, dfm_mode: dfm, thinking_level: effort });
}

const PROMPT_MEMBERS = new Set([
  "session_id", "run_id", "prompt", "context", "expected_model_revision",
  "interaction_mode", "dfm_mode", "thinking_level",
]);

export function readPrompt(params: Readonly<Record<string, unknown>>) {
  if (Object.keys(params).some(key => !PROMPT_MEMBERS.has(key)) ||
      typeof params.session_id !== "string" || !params.session_id ||
      typeof params.run_id !== "string" || !params.run_id ||
      typeof params.prompt !== "string" || !params.prompt ||
      (params.context !== undefined && params.context !== null && typeof params.context !== "string")) {
    throw modelError("invalid_params");
  }
  enforceMaxUtf8Bytes(params.prompt, PROMPT_MAX_UTF8_BYTES, "prompt");
  return Object.freeze({ sessionId: params.session_id, runId: params.run_id,
    promptText: params.prompt, contextBlock: params.context ?? undefined,
    controls: readTurnControls(params) });
}

// Deliberately enumerated: a newly added read_* (or other) tool is NOT approved
// just because of its spelling. This is intersected with the existing profile.
export const PLAN_TOOLS: ReadonlySet<string> = new Set([
  "read_part", "read_globals", "read_project_check", "read_artifact",
  "read_constraints", "read_couplings", "read_joints", "read_motion_checks",
  "read_poses", "read_proposals", "read_reference", "read_requirements",
  "list_project_checks", "list_references", "list_skills",
  "search_materials", "search_parts_store", "inspect_part", "measure",
  "compare_solids", "compare_to_scan", "query_snapshot", "get_delegation_status",
]);

export function applyTurnControls(session: AgentSession, profileTools: readonly string[], controls: TurnControls): void {
  session.setActiveToolsByName(profileTools.filter(name => controls.interaction_mode === "modeling" || PLAN_TOOLS.has(name)));
  session.setThinkingLevel(controls.thinking_level); // Pinned Pi owns capability clamping.
}

const DFM_LABELS = {
  general: "general manufacturing",
  additive: "additive manufacturing",
  sheet_metal: "sheet metal",
  machining: "machining",
  casting: "casting",
} as const;

export function turnControlContext(controls: TurnControls): string {
  const mode = controls.interaction_mode === "plan"
    ? "Plan: inspect and propose an actionable plan; do not change modeling source, configuration, parameters or requirements, or execute, delegate or queue modeling work. Inspection may retain immutable evidence; status reads may finalize expired deadlines. Only the existing bounded evidence and session bookkeeping effects are allowed, not arbitrary writes."
    : "Modeling: use the session's allowed tools as needed.";
  const dfm = controls.dfm_mode === "off"
    ? "No manufacturing-review context is selected for this turn."
    : `Consider ${DFM_LABELS[controls.dfm_mode]} in your manufacturing review. This is review context, not a request to run DFM or change auto_run. Do not claim unmeasured findings.`;
  return `# Current turn controls\nThese choices apply to this turn, superseding earlier turn choices.\n${mode}\n${dfm}`;
}
