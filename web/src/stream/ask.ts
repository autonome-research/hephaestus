// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// What an `AskUserWidget` shows **and what it may submit**, decided from events
// rather than in JSX (INTERFACE.md §7.3, §7A.7, §2.7).
//
// THE TWO SOURCES, and why they are not the same widget wearing one label.
//
// * **Live.** `question` and `answer` are *synthetic* events minted in
//   `main.ts` around the `py.ask_user` suspension. They carry the question, its
//   options, `allow_free_text`, `multi`, and the minted `question_id` an answer
//   is idempotent on.
// * **Reopened.** `normalizeEntries` can never emit those two kinds — §2.7's
//   table says so in a row — so a reopened widget is rebuilt from the `ask_user`
//   **tool call and its tool result**, which history does carry, and is marked
//   `data-widget-source="tool_result"` and non-interactive. It is not
//   reconstructed from `question`/`answer`, because those are not there.
//
// The question text and options therefore come from the `question` payload when
// there is one and from the tool call's `arguments` otherwise; the answer comes
// from the `answer` payload live and from the result document's `selection` in a
// reopened transcript. Neither branch invents the other's fields.
//
// ANSWERING IS PART OF THIS BUILD (§7A.7). Two rules shape everything below.
//
// 1. **The affordance is derived from the question's own params, never chosen
//    by the client.** Options with `multi:false` give one button per option,
//    plus a free-text field *only if* `allow_free_text`; `multi:true` gives a
//    multi-select and one submit; no options gives a single text field, the only
//    thing a bare `ask_user` can accept; `allow_free_text:false` gives buttons
//    and **no** text field. Offering free text on a question that declared
//    `allow_free_text:false` would hand the model an answer its own schema does
//    not admit (§15.35 forbids it by name).
// 2. **The submitted value is the label the *server* sent.** `answerValue`
//    indexes `content.options`, which is `readOptions` over the payload, so the
//    string that leaves this client is the payload's `label` byte for byte — not
//    a label read back out of rendered text, and not a client-side rewrite of
//    it. `agent_bridge/cli.py` answers the same question with the same
//    `option_label`, which is what makes two surfaces answering one question
//    hand the model one value (§7A.7's tightening, §19.29).
//
// `"self"` is now reachable and is the **route's** answer, never this client's
// guess: `accepted` decides it, so the winner renders `"self"` and every other
// client `"other"`, including a client that submitted and lost. The recorded
// selection returned by the route is the winner's, so both agree on what the run
// was told. No web-side lock is invented over a suspended question; that would
// be a second session-ownership mechanism (§2.7).

import {
  readAnswer,
  readOptions,
  readQuestion,
  readToolCall,
  readToolResult,
  type ClarificationOption,
} from "../api/events";
import type { AnswerDocument, AnsweredBy } from "../api/sessions";
import type { RuntimeFault } from "./runtimeFault";
import { parseToolResult } from "./toolResult";
import type { ChipStatus, TranscriptItem } from "./transcript";

export type { AnsweredBy };

/**
 * What this widget can offer, closed at six and derived from the question.
 *
 * `none` is not a degenerate case to hide: a question with no options that also
 * forbids free text admits no answer any client could give, and saying so is
 * §4.4's discipline applied to an affordance rather than to a fact.
 */
export const ASK_AFFORDANCES = [
  "options",
  "options_text",
  "multi",
  "multi_text",
  "text",
  "none",
] as const;
export type AskAffordance = (typeof ASK_AFFORDANCES)[number];

/**
 * The widget's state, closed at six. Every value is a *rendered* state with its
 * own copy; none of them is a disabled control with no explanation.
 *
 * `abandoned` is §7A.7's first-class rendering of `404 unknown_question` —
 * "answered, abandoned, or never asked", which are one state to that route and
 * are therefore one state here. It is rendered **in place**, on the widget, not
 * in a toast.
 */
export const ASK_STATES = [
  "answerable",
  "submitting",
  "answered",
  "abandoned",
  "failed",
  "unavailable",
] as const;
export type AskState = (typeof ASK_STATES)[number];

/**
 * Why a widget cannot be answered from this page, closed at four.
 *
 * `reopened` is the honest majority: §7A.7 keeps the reopened widget disabled
 * *correctly* — there is no pending question, the run is over — and requires it
 * to keep its stated reason. The other three are live widgets missing something
 * an answer needs, and each says which rather than rendering a dead control.
 */
export const ASK_UNAVAILABLE_REASONS = [
  "reopened",
  "no_question_id",
  "no_session",
  "no_answer_shape",
] as const;
export type AskUnavailableReason = (typeof ASK_UNAVAILABLE_REASONS)[number];

/** The lifecycle of this client's own POST. Owned by the widget, read here. */
export type AskPost =
  | { readonly phase: "idle" }
  | { readonly phase: "sending" }
  | { readonly phase: "settled"; readonly document: AnswerDocument }
  | { readonly phase: "refused"; readonly reason: string; readonly message: string };

export const ASK_POST_IDLE: AskPost = { phase: "idle" };

/** One choice a person can express in the affordances above. */
export type AskChoice =
  | { readonly kind: "option"; readonly index: number }
  | { readonly kind: "options"; readonly indices: readonly number[] }
  | { readonly kind: "text"; readonly text: string };

export interface AskContent {
  readonly source: "question" | "tool_result";
  readonly questionId: string | null;
  /** The question's own session, from the event envelope — never the URL's. */
  readonly sessionId: string | null;
  readonly question: string | null;
  readonly options: readonly ClarificationOption[];
  readonly allowFreeText: boolean;
  readonly multi: boolean;
  readonly affordance: AskAffordance;
  readonly state: AskState;
  readonly unavailable: AskUnavailableReason | null;
  /** Set only in the `failed` state: the server's own named reason (§2.4). */
  readonly refusal: { readonly reason: string; readonly message: string } | null;
  /** Present is not the same as truthy: `false` and `""` are real answers. */
  readonly answered: boolean;
  readonly answer: unknown;
  readonly answeredBy: AnsweredBy | null;
  /**
   * `data-runtime-fault` is set for this session and this widget's run has
   * not produced a `terminal`. Same six `AskState` values — no sixth §7.4
   * state. An unanswered question is `abandoned`; an accepted answer stays
   * recorded and this flag is what names "the run did not resume".
   */
  readonly lostToRuntime: boolean;
}

export interface AskRowLike {
  readonly source: "question" | "tool_result";
  readonly question: TranscriptItem | null;
  readonly call: TranscriptItem | null;
  readonly result: TranscriptItem | null;
  readonly answer: TranscriptItem | null;
  readonly status: ChipStatus;
}

/** How this session died, if it did. Derived, never a sixth event kind. */
export interface AskRuntimeDeath {
  readonly fault: RuntimeFault | null;
  readonly runHasTerminal: boolean;
}

/** Everything the widget renders, from whichever of the two sources exists. */
export function askContent(
  row: AskRowLike,
  post: AskPost = ASK_POST_IDLE,
  death: AskRuntimeDeath | null = null,
): AskContent {
  const question = row.question === null ? null : readQuestion(row.question.payload);
  const call = row.call === null ? null : readToolCall(row.call.payload);
  const args =
    call === null || typeof call.args !== "object" || call.args === null || Array.isArray(call.args)
      ? null
      : (call.args as Readonly<Record<string, unknown>>);

  const text =
    question?.question ?? (typeof args?.["question"] === "string" ? args["question"] : null);
  const options =
    question !== null && question.options.length > 0
      ? question.options
      : readOptions(args?.["options"]);
  // Live: the payload's own fields. Reopened: the recorded call arguments, read
  // against the same schema defaults — a reopened widget states the shape of the
  // question that *was* asked rather than the shape of a question in general.
  const allowFreeText = question?.allowFreeText ?? (args?.["allow_free_text"] !== false);
  const multi = question?.multi ?? (args?.["multi"] === true);
  const affordance = askAffordance(options.length, allowFreeText, multi);

  // The question's session id comes off the event envelope (§2.7 adds exactly
  // one field, `session_id`, and it is `null` when the run→session binding has
  // been evicted). Falling back to whichever session the workspace happens to be
  // showing would post an answer against a session this question is not in.
  const sessionId = (row.question ?? row.call ?? row.answer)?.sessionId ?? null;

  const live = row.answer === null ? null : readAnswer(row.answer.payload);
  const recorded = recordedSelection(row.result);
  const questionId = question?.questionId ?? live?.questionId ?? null;
  // ANSWERABILITY IS NOT THE LIFECYCLE. `unavailable` says whether this widget
  // could ever be answered from this page and is computed once, so an *answered*
  // reopened widget still carries `reopened` — the reason it has no controls —
  // instead of losing it the moment an answer exists to show.
  const unavailable = askUnavailable(row.source, questionId, sessionId, affordance);
  const lostToRuntime = death !== null && death.fault !== null && !death.runHasTerminal;
  const base = {
    source: row.source,
    sessionId,
    question: text,
    options,
    allowFreeText,
    multi,
    affordance,
    unavailable,
    lostToRuntime,
  } as const;

  // ORDER IS THE ARGUMENT. A settled POST is this client's own outcome and the
  // only thing that can say `"self"`. An `answer` event or a recorded selection
  // outranks a refusal, because "another client answered, here is what the run
  // was told" is truer and more useful than "that question is gone" — and a
  // cancelled run, which has no answer anywhere, still lands on `abandoned`.
  // A runtime fault does not relabel an accepted answer "already answered";
  // `lostToRuntime` is the note that the run did not resume.
  if (post.phase === "settled") {
    return {
      ...base,
      questionId: post.document.question_id,
      state: "answered",
      refusal: null,
      answered: true,
      answer: post.document.answer,
      answeredBy: post.document.answered_by,
    };
  }
  if (live !== null) {
    return {
      ...base,
      questionId,
      state: "answered",
      refusal: null,
      answered: true,
      answer: live.answer,
      answeredBy: "other",
    };
  }
  if (recorded.answered) {
    return {
      ...base,
      questionId,
      state: "answered",
      refusal: null,
      answered: true,
      answer: recorded.answer,
      answeredBy: "other",
    };
  }
  // Sidecar death never yields `terminal` (live-only; the run is gone) and
  // never yields `404 unknown_question` until a click. Once the well knows
  // the runtime is gone, pending widgets go `abandoned` without that click.
  if (lostToRuntime) {
    return {
      ...base,
      questionId,
      state: "abandoned",
      refusal: null,
      answered: false,
      answer: null,
      answeredBy: null,
    };
  }
  if (post.phase === "refused") {
    const abandoned = post.reason === "unknown_question";
    return {
      ...base,
      questionId,
      state: abandoned ? "abandoned" : "failed",
      refusal: { reason: post.reason, message: post.message },
      answered: false,
      answer: null,
      answeredBy: null,
    };
  }

  return {
    ...base,
    questionId,
    state:
      post.phase === "sending" ? "submitting" : unavailable === null ? "answerable" : "unavailable",
    refusal: null,
    answered: false,
    answer: null,
    answeredBy: null,
  };
}

/** §7A.7's mapping from `ask_user`'s three params onto an affordance. */
export function askAffordance(
  optionCount: number,
  allowFreeText: boolean,
  multi: boolean,
): AskAffordance {
  if (optionCount === 0) return allowFreeText ? "text" : "none";
  if (multi) return allowFreeText ? "multi_text" : "multi";
  return allowFreeText ? "options_text" : "options";
}

function askUnavailable(
  source: "question" | "tool_result",
  questionId: string | null,
  sessionId: string | null,
  affordance: AskAffordance,
): AskUnavailableReason | null {
  if (source === "tool_result") return "reopened";
  if (questionId === null) return "no_question_id";
  if (sessionId === null) return "no_session";
  if (affordance === "none") return "no_answer_shape";
  return null;
}

/**
 * The value this client would submit for a choice — or `null` for one the
 * question does not admit.
 *
 * `null` is a refusal, not an empty answer: the widget keeps its submit control
 * inert rather than posting a value `ask_user`'s own schema rejects, and the
 * check lives here so it is the same check in the DOM and in a test.
 *
 * **Every returned string is `content.options[i].label`** — the server's own
 * bytes — or free text the operator typed. Nothing is reconstructed from
 * rendered markup, and a `multi` answer is emitted in the **question's** order
 * rather than in click order, so one set of choices has one submitted value.
 * The `trim` matches `agent_bridge/cli.py`'s `raw.strip()`: without it the two
 * surfaces would answer one question with `"18 mm"` and `"18 mm\n"`.
 */
export function answerValue(content: AskContent, choice: AskChoice): string | string[] | null {
  if (choice.kind === "text") {
    if (!content.allowFreeText) return null;
    const text = choice.text.trim();
    return text === "" ? null : text;
  }
  if (choice.kind === "option") {
    if (content.multi) return null;
    return content.options[choice.index]?.label ?? null;
  }
  if (!content.multi) return null;
  const chosen = new Set(choice.indices);
  const labels = content.options
    .filter((_option, index) => chosen.has(index))
    .map((option) => option.label);
  return labels.length === 0 ? null : labels;
}

/**
 * The answer a reopened transcript records: the result document's `selection`.
 *
 * `ask_user`'s success branch requires `selection` (`schemas/tools/ask_user`),
 * and its refusal branch (`invalid_question`) carries none — a question the tool
 * refused to put to a human was never answered, and this reports that rather
 * than showing an empty selection as one.
 */
function recordedSelection(result: TranscriptItem | null): {
  answered: boolean;
  answer: unknown;
} {
  if (result === null) return { answered: false, answer: null };
  const payload = readToolResult(result.payload);
  if (payload === null) return { answered: false, answer: null };
  const parsed = parseToolResult(payload.text);
  if (parsed.state !== "parsed") return { answered: false, answer: null };
  if (!Object.prototype.hasOwnProperty.call(parsed.doc, "selection")) {
    return { answered: false, answer: null };
  }
  return { answered: true, answer: parsed.doc["selection"] };
}
