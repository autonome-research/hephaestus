// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// `AskUserWidget` (INTERFACE.md §7.3, §7A.7, §2.7).
//
// `architecture.md` §4.3 already says the same question is a numbered prompt in
// the CLI, structured content over MCP, and a widget in the web. This is that
// widget. Options render **label and geometric consequence**, because
// `_CLARIFICATION_OPTION` requires both — and a bare-string option, which the
// schema also admits, carries no consequence at all and says so rather than
// showing an empty line where a consequence would be.
//
// TWO SOURCES, MARKED. `data-widget-source="question"` live — the synthetic
// `question` event minted around the `py.ask_user` suspension —
// `data-widget-source="tool_result"` in a reopened transcript, where §7.3 has
// the widget rebuilt from the `ask_user` call and its result because
// `normalizeEntries` can never emit `question`/`answer`. The reopened widget
// says so in place, so a reader does not take the absence of a live exchange for
// a question nobody answered.
//
// ANSWERING IS IN THIS BUILD, AND EVERY DISABLED STATE STILL SAYS WHY (§7A.7).
// A live question posts `POST /sessions/{id}/answer`; first answer wins, and the
// retained POST receipt decides `data-answered-by`; observers without that
// receipt omit attribution. An event or component remount cannot identify an
// actor. Primary answer copy stays neutral and readable. The four
// states that cannot be answered — a reopened transcript, a question with no id,
// an event with no session, and a question that admits no answer at all — each
// render with their own named reason rather than as an inert control, and a
// `404 unknown_question` or terminal evidence for this question's own run
// renders `data-ask-state="abandoned"` in place.
//
// THE SUBMITTED VALUE IS THE SERVER'S LABEL, and the widget cannot express any
// other. Every control carries the option's **index**; `answerValue` turns an
// index into `content.options[i].label`, which is the payload's own string.
// Nothing here reads a label back out of the DOM, and nothing rewrites one —
// `agent_bridge/cli.py` answers the same question with the same label, which is
// what makes two surfaces answering one question hand the model one value.
//
// The widget satisfies §7.2's chip attribute contract whenever it has an
// `ask_user` tool call to satisfy it with — "both satisfy the same attribute
// contract, so a degraded fixture never breaks the contract". A live widget
// built from a `question` event alone has no tool call and therefore no
// `data-tool-name`; it is not a chip, and pretending otherwise would put a tool
// name on an event that carries none.

import { useState } from "react";
import { WorkspaceError } from "../../api/client";
import { answerQuestion } from "../../api/sessions";
import { copy } from "../../copy";
import {
  answerValue,
  readableAnswer,
  askContent,
  ASK_POST_IDLE,
  type AskChoice,
  type AskRowLike,
  type AskRuntimeDeath,
} from "../../stream/ask";
import { fieldDisplay, parseToolResult } from "../../stream/toolResult";
import { readToolResult } from "../../api/events";
import { chipAttributes } from "./ToolChip";
import { conversationStore, useConversation, readExecutionSessions, readSessionModel, questionRunId } from "../../stream/conversation";
import { readableReason, sanitizeDiagnostic } from "../../stream/outcome";
import { Button, TextInput } from "../../system";
import styles from "./Transcript.module.css";

export function AskUserWidget({
  row,
  death = null,
  executionAllowed: executionPermitted = true,
  taskStatus = null,
}: {
  readonly taskStatus?: string | null;
  readonly executionAllowed?: boolean;
  readonly row: AskRowLike;
  readonly death?: AskRuntimeDeath | null;
}): React.JSX.Element | null {
  const initial = askContent(row);
  const conversation = useConversation(initial.sessionId);
  const executionAllowed = executionPermitted && (!row.recovery || row.recovery.epoch === conversation.execution?.epoch);
  const post = initial.questionId === null ? ASK_POST_IDLE : conversation.answers[initial.questionId] ?? ASK_POST_IDLE;
  // The two in-progress answers a person can be composing. They are pixels, not
  // facts: nothing is sent until a submit, and nothing here is ever read back as
  // the answer — `answerValue` reads the payload's labels (§1).
  const [checked, setChecked] = useState<readonly number[]>([]);
  const [typed, setTyped] = useState("");

  const anchor = row.call ?? row.question ?? row.answer ?? { eventId: undefined, surface: undefined };
  const boundRun = questionRunId(conversation, row);
  const terminal = conversation.execution?.terminal;
  const content = askContent(row, post, {
    fault: death?.fault ?? null,
    runHasTerminal: death?.runHasTerminal === true || (boundRun !== null && terminal?.run_id === boundRun),
  });
  const chip = row.call === null ? null : chipAttributes("ask_user", row.status, row.call);
  const resultPayload = row.result === null ? null : readToolResult(row.result.payload);
  const parsed = resultPayload === null ? null : parseToolResult(resultPayload.text);
  if (anchor.eventId === undefined && !row.recovery) return null;

  // Two flags, because "the controls are here but busy" and "there are no
  // controls" are different states and rendering them the same way would make a
  // post in flight look like a question that cannot be answered.
  const interactive = content.state === "answerable" && executionAllowed;
  const composing = interactive || content.state === "submitting";
  /**
   * WHY A CONTROL IS OFF, in words (§4.7: "Disabled requires a `reason` prop…
   * a disabled control in this app must always be able to say why").
   *
   * Every state that turns the controls off already has a sentence in
   * `copy.ts`; this picks the one that is true rather than minting a new one,
   * so the `title` a pointer sees and the `aria-describedby` a screen reader
   * hears are the same sentence the widget already prints in place.
   */
  // A settled question's own lifecycle outranks the global execution gate.
  // In particular, a durable terminal removes active ownership (so
  // `executionAllowed` is false) while also proving this question is closed.
  // Calling that state "Checking execution" forever would hide the stronger
  // fact the widget already renders. Unknown ownership still reaches the
  // checking branch and remains unable to send.
  const offReason = content.lostToRuntime && content.answered
    ? copy.stream.ask.answeredRunLost
    : content.lostToRuntime
      ? copy.stream.ask.abandonedRuntime
      : content.answered
        ? copy.stream.ask.answeredAlready
        : content.state === "submitting"
          ? copy.stream.ask.sending
          : content.state === "abandoned"
            ? copy.stream.ask.abandoned
            : content.state === "checking"
              ? copy.stream.ask.checking
            : content.state === "failed"
              ? copy.stream.ask.failed
              : content.unavailable !== null
                ? copy.stream.ask.unavailable[content.unavailable]
                : !executionAllowed
                  ? taskStatus ?? copy.composer.checking
                  : copy.stream.ask.answeredAlready;
  const sessionId = content.sessionId;
  const questionId = content.questionId;

  function submit(choice: AskChoice): void {
    const value = answerValue(content, choice);
    // Three guards, and none of them is defensive noise: `answerValue` returns
    // `null` for a choice the question does not admit, and the two ids are what
    // the route is addressed by. A widget without them is already rendering
    // `unavailable` with the reason, so there is nothing to say here.
    if (!interactive || value === null || sessionId === null || questionId === null) return;
    if (!conversationStore.beginAnswer(sessionId, row)) return;
    void answerQuestion(sessionId, questionId, value).then(
      (document) => {
        conversationStore.answer(sessionId, questionId, { phase: "settled", document });
      },
      (error: unknown) => {
        conversationStore.answer(sessionId, questionId,
          error instanceof WorkspaceError
            ? { phase: "refused", reason: error.reason, message: error.message }
            : {
                phase: "refused",
                reason: "transport_error",
                message: error instanceof Error ? error.message : String(error),
              },
        );
      },
    ).finally(() => {
      void readExecutionSessions().catch(() => undefined);
      void readSessionModel(sessionId);
    });
  }

  // The chip attributes are spread *before* the identity pair below: `anchor` is
  // `row.call` whenever a chip exists, so the two agree by construction, and
  // writing the explicit pair last keeps a widget with no call (a live
  // `question` alone) carrying its identity all the same.
  return (
    <section
      className={styles["ask"]}
      tabIndex={-1}
      data-widget-source={content.source}
      data-ask-state={content.state}
      data-ask-affordance={content.affordance}
      {...(content.unavailable === null ? {} : { "data-ask-unavailable": content.unavailable })}
      {...(content.refusal === null ? {} : { "data-refusal-reason": content.refusal.reason })}
      {...(content.questionId === null ? {} : { "data-question-id": content.questionId })}
      {...(content.answeredBy === null ? {} : { "data-answered-by": content.answeredBy })}
      {...(chip ?? {})}
      data-event-id={anchor.eventId}
      data-surface={anchor.surface}
      {...(parsed === null ? {} : { "data-field-state": parsed.state })}
    >
      <header className={styles["askHeader"]}>
        <span className={styles["askTitle"]}>{copy.stream.ask.title}</span>
      </header>
      {content.source === "live_state" ? <p className={styles["note"]}>{copy.stream.ask.recovered}</p> : null}


      <p
        className={styles["askQuestion"]}
        data-ask-question="1"
        {...(row.question === null || row.question.eventId === anchor.eventId
          ? {}
          : { "data-event-id": row.question.eventId, "data-surface": row.question.surface })}
      >
        {content.question ?? copy.absent.unavailable}
      </p>

      {content.options.length === 0 ? (
        <p className={styles["note"]}>{copy.stream.ask.noOptions}</p>
      ) : (
        <ul className={styles["askOptions"]}>
          {content.options.map((option, index) => (
            <li key={`${String(index)}:${option.label}`} className={styles["askOption"]}>
              {composing && content.multi ? (
                <label className={styles["askCheck"]}>
                  <input
                    type="checkbox"
                    disabled={!interactive}
                    data-ask-option={option.label}
                    data-ask-option-index={index}
                    checked={checked.includes(index)}
                    onChange={(event) => {
                      setChecked((current) =>
                        event.target.checked
                          ? [...current, index]
                          : current.filter((other) => other !== index),
                      );
                    }}
                  />
                  {option.label}
                </label>
              ) : interactive ? (
                <Button
                  variant="secondary"
                  data-ask-option={option.label}
                  data-ask-option-index={index}
                  onClick={() => {
                    submit({ kind: "option", index });
                  }}
                >
                  {option.label}
                </Button>
              ) : (
                <Button
                  variant="secondary"
                  disabled
                  reason={offReason}
                  data-ask-option={option.label}
                  data-ask-option-index={index}
                >
                  {option.label}
                </Button>
              )}
              <span
                className={styles["askConsequence"]}
                data-ask-consequence={option.consequence === null ? "absent" : "present"}
              >
                {option.consequence ?? copy.stream.ask.consequenceMissing}
              </span>
            </li>
          ))}
        </ul>
      )}

      {/* §7A.7: the free-text field exists **only if** the question allows it,
          and the multi submit exists only for a `multi` question. The affordance
          is the question's, so it is read off `content` and never toggled by a
          preference of this client's. */}
      {composing && content.multi ? (
        <div className={styles["askForm"]}>
          <span className={styles["note"]}>{copy.stream.ask.multiHint}</span>
          {interactive && checked.length > 0 ? (
            <Button
              variant="primary"
              data-ask-submit="options"
              onClick={() => {
                submit({ kind: "options", indices: checked });
              }}
            >
              {copy.stream.ask.submitMulti}
            </Button>
          ) : (
            <Button
              variant="primary"
              disabled
              reason={interactive ? copy.stream.ask.chooseFirst : offReason}
              data-ask-submit="options"
            >
              {copy.stream.ask.submitMulti}
            </Button>
          )}
        </div>
      ) : null}

      {composing && content.allowFreeText ? (
        <div className={styles["askForm"]}>
          <TextInput
            className={styles["askText"]}
            label={copy.stream.ask.freeTextLabel}
            disabled={!interactive}
            data-ask-text="1"
            value={typed}
            placeholder={copy.stream.ask.freeTextPlaceholder}
            onChange={setTyped}
          />
          {interactive && typed.trim() !== "" ? (
            <Button
              variant="primary"
              data-ask-submit="text"
              onClick={() => {
                submit({ kind: "text", text: typed });
              }}
            >
              {copy.stream.ask.submit}
            </Button>
          ) : (
            <Button
              variant="primary"
              disabled
              reason={interactive ? copy.stream.ask.typeFirst : offReason}
              data-ask-submit="text"
            >
              {copy.stream.ask.submit}
            </Button>
          )}
        </div>
      ) : null}

      {content.state === "submitting" ? (
        <p className={styles["note"]}>{copy.stream.ask.sending}</p>
      ) : null}

      {content.state === "abandoned" ? (
        <p className={styles["note"]} data-ask-abandoned="1">
          {content.lostToRuntime ? copy.stream.ask.abandonedRuntime : copy.stream.ask.abandoned}
        </p>
      ) : null}

      {content.answered && content.lostToRuntime ? (
        <p className={styles["note"]} data-ask-run-lost="1">
          {copy.stream.ask.answeredRunLost}
        </p>
      ) : null}

      {content.state === "checking" ? <p className={styles["note"]} role="status">{copy.stream.ask.checking}</p> : null}

      {content.state === "failed" && content.refusal !== null ? (
        <p className={styles["note"]}>
          {copy.stream.ask.failed} {readableReason(content.refusal.message)}
        </p>
      ) : null}

      {content.unavailable === null || content.answered || content.state === "abandoned" ? null : (
        <p className={styles["note"]} data-ask-disabled="1">
          {copy.stream.ask.unavailable[content.unavailable]}
        </p>
      )}

      {content.answered ? (
        <div
          className={styles["askAnswer"]}
          data-ask-answer="1"
          {...(row.answer === null || row.answer.eventId === anchor.eventId
            ? {}
            : { "data-event-id": row.answer.eventId, "data-surface": row.answer.surface })}
        >
          <span className={styles["fieldName"]}>{copy.stream.ask.answer}</span>
          <span>{readableAnswer(content.answer) ?? copy.stream.ask.answerInDetails}</span>
        </div>
      ) : content.state === "answerable" ? (
        <p className={styles["note"]}>{executionAllowed ? copy.stream.ask.pending : taskStatus ?? copy.composer.checking}</p>
      ) : null}

      {/* As in `ToolChip`: the result block carries the result event's own
          identity, so a reopened transcript names every archived event. */}
      {parsed === null && !content.answered ? null : <details>
        <summary>{copy.stream.ask.details}</summary>
        {content.source === "tool_result" ? <p className={styles["note"]}>{copy.stream.ask.fromToolResult}</p> : null}
        {content.answered ? <pre className={styles["raw"]}>{sanitizeDiagnostic(content.answer)}</pre> : null}
      {parsed === null ? null : parsed.state === "unparsed" ? (
        <p
          className={styles["note"]}
          {...(row.result === null || row.result.eventId === anchor.eventId
            ? {}
            : { "data-event-id": row.result.eventId, "data-surface": row.result.surface })}
        >
          {copy.stream.chip.unparsed[parsed.reason]}
        </p>
      ) : (
        <dl
          className={styles["fields"]}
          {...(row.result === null || row.result.eventId === anchor.eventId
            ? {}
            : { "data-event-id": row.result.eventId, "data-surface": row.result.surface })}
        >
          {parsed.fields.map((field) => (
            <div key={field} className={styles["field"]} data-field={field}>
              <dt className={styles["fieldName"]}>{field}</dt>
              <dd className={styles["fieldValue"]}>{fieldDisplay(parsed.doc[field])}</dd>
            </div>
          ))}
        </dl>
      )}
      </details>}
    </section>
  );
}
