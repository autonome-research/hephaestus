// Clarification-question shaping (VALIDATION.md §3), agent side.
//
// When the clarification gate refuses `build_part` the model must ask the user —
// and §3 fixes what that question may look like: 2-4 concrete options, EACH
// stating the geometric consequence of choosing it, never an open "what did you
// mean?". A question that names ledger requirement ids is a clarification, and
// this module decides structurally whether it is well-shaped.
//
// The rule is enforced twice on purpose: here, before the question crosses the
// bridge (so the model gets its correction in the same turn, without disturbing
// a human), and again in `agent_bridge.app` on the way in — the Python side is
// authoritative and also covers the MCP path. Parity between the two is asserted
// by tests on both sides, exactly as with the JSON-Schema conditional evaluator.

import type { JsonValue } from "../framing.js";

/** §3: "2-4 options, each stating its geometric consequence". */
export const CLARIFICATION_MIN_OPTIONS = 2;
export const CLARIFICATION_MAX_OPTIONS = 4;

/** Discriminated code of a badly-shaped clarification question. */
export const INVALID_QUESTION_CODE = "clarification_question_shape";

function isRecord(value: JsonValue): value is { [k: string]: JsonValue } {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** The display text of an option in either supported form. */
export function optionLabel(option: JsonValue): string {
  if (isRecord(option)) {
    const label = option.label;
    return typeof label === "string" ? label : "";
  }
  return typeof option === "string" ? option : String(option);
}

/** The stated geometric consequence of an option, if it carries one. */
export function optionConsequence(option: JsonValue): string | undefined {
  if (!isRecord(option)) return undefined;
  const consequence = option.consequence;
  return typeof consequence === "string" && consequence.trim() !== "" ? consequence : undefined;
}

/** The ledger ids a question is raised against; empty when it is not a clarification. */
export function requirementIds(raw: JsonValue | undefined): readonly string[] {
  if (!Array.isArray(raw)) return [];
  return raw.filter((item): item is string => typeof item === "string" && item.trim() !== "");
}

/**
 * Every way this clarification question fails §3's concrete-options pattern.
 * Empty means it may be asked.
 */
export function questionProblems(
  question: JsonValue | undefined,
  options: JsonValue | undefined,
): readonly string[] {
  const problems: string[] = [];
  if (typeof question !== "string" || question.trim() === "") {
    problems.push("question must be a non-empty string");
  }
  if (!Array.isArray(options)) {
    problems.push("options must be an array of 2-4 concrete options");
    return problems;
  }
  if (options.length < CLARIFICATION_MIN_OPTIONS || options.length > CLARIFICATION_MAX_OPTIONS) {
    problems.push(
      `a clarification needs ${CLARIFICATION_MIN_OPTIONS}-${CLARIFICATION_MAX_OPTIONS} options, ` +
        `got ${options.length}`,
    );
  }
  options.forEach((option, index) => {
    if (optionLabel(option).trim() === "") {
      problems.push(`option ${index}: a non-empty label is required`);
    }
    if (optionConsequence(option) === undefined) {
      problems.push(
        `option ${index}: must state its geometric consequence ` +
          `({"label": …, "consequence": …})`,
      );
    }
  });
  return problems;
}

/** The discriminated `ask_user` result returned instead of asking. */
export function invalidQuestionResult(problems: readonly string[]): JsonValue {
  return {
    status: "invalid_question",
    code: INVALID_QUESTION_CODE,
    message:
      `a clarification question must offer ${CLARIFICATION_MIN_OPTIONS}-` +
      `${CLARIFICATION_MAX_OPTIONS} concrete options, each stating its geometric ` +
      `consequence; the question was not asked`,
    problems: [...problems],
  };
}

/**
 * The refusal for a badly-shaped clarification, or `undefined` when the call is
 * either not a clarification or is well-shaped.
 */
export function clarificationRefusal(args: { [k: string]: JsonValue }): JsonValue | undefined {
  if (requirementIds(args.requirement_ids).length === 0) return undefined;
  const problems = questionProblems(args.question, args.options);
  return problems.length === 0 ? undefined : invalidQuestionResult(problems);
}
