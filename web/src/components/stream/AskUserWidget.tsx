// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// `AskUserWidget` (INTERFACE.md §7.3, §2.7).
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
// ANSWERING IS NOT IN THIS BUILD, AND THE WIDGET SAYS WHICH. §7.3's widget posts
// `POST /sessions/{id}/answer`; that route exists and this panel does not call
// it yet. The controls are therefore rendered **disabled with a stated reason**.
// A disabled control with no explanation is indistinguishable from a broken one,
// and §4.4's discipline — a weak answer says why it is weak — is not only about
// provenance. `data-answered-by` is emitted when an answer exists and its value
// is `"other"`: every answer this panel can observe came from the CLI or another
// tab, because this one cannot produce one. `"self"` becomes reachable when the
// post does, and claiming it now would be a claim about who acted made by the
// one client that did not act.
//
// The widget satisfies §7.2's chip attribute contract whenever it has an
// `ask_user` tool call to satisfy it with — "both satisfy the same attribute
// contract, so a degraded fixture never breaks the contract". A live widget
// built from a `question` event alone has no tool call and therefore no
// `data-tool-name`; it is not a chip, and pretending otherwise would put a tool
// name on an event that carries none.

import { copy } from "../../copy";
import { askContent, type AskRowLike } from "../../stream/ask";
import { fieldDisplay, parseToolResult } from "../../stream/toolResult";
import { readToolResult } from "../../api/events";
import { chipAttributes } from "./ToolChip";
import styles from "./Transcript.module.css";

export function AskUserWidget({ row }: { readonly row: AskRowLike }): React.JSX.Element | null {
  const anchor = row.call ?? row.question ?? row.answer;
  if (anchor === null) return null;
  const content = askContent(row);
  const chip = row.call === null ? null : chipAttributes("ask_user", row.status, row.call);
  const resultPayload = row.result === null ? null : readToolResult(row.result.payload);
  const parsed = resultPayload === null ? null : parseToolResult(resultPayload.text);

  // The chip attributes are spread *before* the identity pair below: `anchor` is
  // `row.call` whenever a chip exists, so the two agree by construction, and
  // writing the explicit pair last keeps a widget with no call (a live
  // `question` alone) carrying its identity all the same.
  return (
    <section
      className={styles["ask"]}
      data-widget-source={content.source}
      {...(content.questionId === null ? {} : { "data-question-id": content.questionId })}
      {...(content.answeredBy === null ? {} : { "data-answered-by": content.answeredBy })}
      {...(chip ?? {})}
      data-event-id={anchor.eventId}
      data-surface={anchor.surface}
      {...(parsed === null ? {} : { "data-field-state": parsed.state })}
    >
      <header className={styles["askHeader"]}>
        <span className={styles["askTitle"]}>{copy.stream.ask.title}</span>
        {row.call === null ? null : (
          <span className={styles["chipStatus"]} data-chip-status={row.status}>
            {copy.stream.chip.status[row.status]}
          </span>
        )}
      </header>

      {content.source === "tool_result" ? (
        <p className={styles["note"]}>{copy.stream.ask.fromToolResult}</p>
      ) : null}

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
              <button
                type="button"
                className={styles["askButton"]}
                disabled
                data-ask-option={option.label}
                data-ask-option-index={index}
              >
                {option.label}
              </button>
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

      <p className={styles["note"]} data-ask-disabled="1">
        {copy.stream.ask.disabled}
      </p>

      {content.answered ? (
        <div
          className={styles["askAnswer"]}
          data-ask-answer="1"
          {...(row.answer === null || row.answer.eventId === anchor.eventId
            ? {}
            : { "data-event-id": row.answer.eventId, "data-surface": row.answer.surface })}
        >
          <span className={styles["fieldName"]}>{copy.stream.ask.answer}</span>
          <code className={styles["fieldValue"]}>{fieldDisplay(content.answer)}</code>
          <span className={styles["note"]}>
            {content.answeredBy === "self"
              ? copy.stream.ask.answeredSelf
              : copy.stream.ask.answeredOther}
          </span>
        </div>
      ) : (
        <p className={styles["note"]}>{copy.stream.ask.pending}</p>
      )}

      {/* As in `ToolChip`: the result block carries the result event's own
          identity, so a reopened transcript names every archived event. */}
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
    </section>
  );
}
