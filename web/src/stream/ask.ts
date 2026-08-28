// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// What an `AskUserWidget` shows, decided from events rather than in JSX
// (INTERFACE.md §7.3, §2.7).
//
// THE TWO SOURCES, and why they are not the same widget wearing one label.
//
// * **Live.** `question` and `answer` are *synthetic* events minted in
//   `main.ts` around the `py.ask_user` suspension. They carry the question, its
//   options, and the minted `question_id` an answer is idempotent on.
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
// ANSWERING IS NOT PART OF THIS BUILD. §7.3 has the widget post
// `POST /sessions/{id}/answer`, first answer wins, each widget disabling itself
// with `data-answered-by="self"|"other"`. The route exists and this panel does
// not call it yet, so every answer this widget can observe was produced
// elsewhere — the CLI's numbered prompt, or another tab — and `"other"` is the
// only value it can honestly report. `"self"` becomes reachable the moment this
// panel can answer, and not before; reporting it now would be a claim about who
// acted, made by the one client that did not.

import {
  readAnswer,
  readOptions,
  readQuestion,
  readToolCall,
  readToolResult,
  type ClarificationOption,
} from "../api/events";
import { parseToolResult } from "./toolResult";
import type { ChipStatus, TranscriptItem } from "./transcript";

export type AnsweredBy = "self" | "other";

export interface AskContent {
  readonly source: "question" | "tool_result";
  readonly questionId: string | null;
  readonly question: string | null;
  readonly options: readonly ClarificationOption[];
  /** Present is not the same as truthy: `false` and `""` are real answers. */
  readonly answered: boolean;
  readonly answer: unknown;
  readonly answeredBy: AnsweredBy | null;
}

export interface AskRowLike {
  readonly source: "question" | "tool_result";
  readonly question: TranscriptItem | null;
  readonly call: TranscriptItem | null;
  readonly result: TranscriptItem | null;
  readonly answer: TranscriptItem | null;
  readonly status: ChipStatus;
}

/** Everything the widget renders, from whichever of the two sources exists. */
export function askContent(row: AskRowLike): AskContent {
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

  const live = row.answer === null ? null : readAnswer(row.answer.payload);
  if (live !== null) {
    return {
      source: row.source,
      questionId: live.questionId ?? question?.questionId ?? null,
      question: text,
      options,
      answered: true,
      answer: live.answer,
      answeredBy: "other",
    };
  }

  const recorded = recordedSelection(row.result);
  return {
    source: row.source,
    questionId: question?.questionId ?? null,
    question: text,
    options,
    answered: recorded.answered,
    answer: recorded.answer,
    answeredBy: recorded.answered ? "other" : null,
  };
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
