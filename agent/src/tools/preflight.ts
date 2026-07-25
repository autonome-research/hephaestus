// Assistant tool-call preflight: ask_user isolation + mutation sequencing
// (architecture §4.1 "Tool scheduling", digest §1).
//
// Pi executes tool calls in parallel by default. Before a batch runs we inspect
// the COMPLETE assistant tool-call message and decide, per call:
//   - If the batch contains `ask_user` alongside ANY stateful/mutating sibling,
//     every non-`ask_user` sibling is BLOCKED with `ask_user_must_be_alone`
//     (regardless of source order — both orders block identically) while the
//     question proceeds; the mutations must be re-issued in a later turn after
//     the answer.
//   - Otherwise, stateful/mutating (sequential) tools run one-at-a-time
//     (serialized) and read-only tools run concurrently.
//
// This module is a pure decision function; the session layer applies the plan
// via Pi's tool-call hook and per-tool executionMode.

import { TOOLS } from "./schema.gen.js";

export const ASK_USER_MUST_BE_ALONE = "ask_user_must_be_alone";

/** A single tool call from the assistant message, in source order. */
export interface ToolCall {
  readonly toolCallId: string;
  readonly toolName: string;
}

export type PreflightDecision =
  | {
      readonly toolCallId: string;
      readonly toolName: string;
      readonly action: "run";
      /** "sequential" for stateful/mutating tools, "parallel" for read-only. */
      readonly mode: "sequential" | "parallel";
    }
  | {
      readonly toolCallId: string;
      readonly toolName: string;
      readonly action: "block";
      readonly reason: typeof ASK_USER_MUST_BE_ALONE;
    };

export interface PreflightPlan {
  readonly decisions: readonly PreflightDecision[];
  /** toolCallIds of the sequential runs, in source order (serialize these). */
  readonly serializedOrder: readonly string[];
}

/**
 * A tool is "stateful/mutating" iff it declares sequential execution. The
 * generated `meta.sequential` flag is the single source of truth (it covers
 * ask_user, the part/globals/check editors, set_params, build_part, export_part,
 * and the delegation tools). Unknown tool names are treated as mutating
 * (fail-safe: never let an unrecognized call run concurrently with a question).
 */
export function isMutating(toolName: string): boolean {
  const meta = TOOLS[toolName]?.meta;
  return meta ? meta.sequential : true;
}

function isAskUser(toolName: string): boolean {
  return toolName === "ask_user";
}

/**
 * Compute the execution plan for a complete assistant tool-call batch.
 * Order-independent: the same set of calls yields the same block decisions in
 * either source order.
 */
export function preflight(calls: readonly ToolCall[]): PreflightPlan {
  const hasAskUser = calls.some((c) => isAskUser(c.toolName));
  const hasMutatingSibling = calls.some(
    (c) => !isAskUser(c.toolName) && isMutating(c.toolName),
  );
  // Trigger isolation only when a question co-occurs with a mutating sibling.
  const isolate = hasAskUser && hasMutatingSibling;

  const decisions: PreflightDecision[] = [];
  const serializedOrder: string[] = [];

  for (const call of calls) {
    if (isolate && !isAskUser(call.toolName)) {
      decisions.push({
        toolCallId: call.toolCallId,
        toolName: call.toolName,
        action: "block",
        reason: ASK_USER_MUST_BE_ALONE,
      });
      continue;
    }
    const mode = isMutating(call.toolName) ? "sequential" : "parallel";
    decisions.push({
      toolCallId: call.toolCallId,
      toolName: call.toolName,
      action: "run",
      mode,
    });
    if (mode === "sequential") serializedOrder.push(call.toolCallId);
  }

  return { decisions, serializedOrder };
}
