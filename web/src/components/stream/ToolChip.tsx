// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// `ToolChip` — INTERFACE.md §7.2's testability contract, made into a component.
//
//   <article data-tool-name="build_part" data-status="ok"
//            data-event-id="run-a1b2c3d4e5f6#41"   <!-- live -->
//            data-tool-call-id="…">
//     <header>…</header>
//     <p data-chip-summary>…</p>
//     <details data-chip-detail>
//       <dl><div data-field="artifact_ref">…</div>…</dl>
//     </details>
//   </article>
//
// * `data-tool-name` — the canonical name from `tool_call.name`. For a result
//   whose call is not on this page it falls back to `tool_result.toolName`,
//   which is the same canonical name from the other side of the pair.
// * `data-status` — `running | ok | error`, derived **only** from normalized
//   events, plus §7.2's own named fallback `unknown` for a historical result
//   whose failure flag `normalizeEntries` could not recover. `unknown` renders
//   with explanatory copy; it never renders as `ok`. A cancelled run's orphan
//   chips stay `running`, because cancellation is a property of the run and the
//   `terminal` band is where it is stated.
// * `data-event-id` — the chip's own event in its own namespace. The separator
//   (`#` live, `@` historical) tells a reader which surface this chip came from
//   without a second attribute (§2.8), and `data-surface` is emitted beside it
//   for legibility, not as the discriminator.
// * `data-field` — one node per key of the **parsed result document**, under
//   §7.2's containment-plus-groundedness predicate. `stream/toolResult.ts`
//   carries the whole argument; the short version is that the field set is
//   exactly `keys(JSON.parse(payload.text))`, which satisfies containment for
//   every tool and satisfies groundedness by construction.
//
// A degraded result renders **plainly**: zero `data-field` nodes,
// `data-field-state="unparsed"`, and the reason in the body — a visible refusal
// carrying its cause rather than a silent pass. **A chip degrades by omission
// and names what is absent; it never fabricates a placeholder value**, which is
// why nothing here ever writes a `data-field` for a key the document lacks.
//
// The call's `arguments` are shown but carry no `data-field`: `data-field` names
// keys of the *result* document, and putting an argument under it would break
// groundedness on the very attribute the gate reads.
//
// WHAT CHANGED, AND WHY THE CONTRACT DID NOT. The field rows used to be the
// chip's whole visible body: every key of every document, values verbatim, in
// `.code` — which sets `word-break: break-all`. A `read_part` result carrying a
// `part_param_state_hash` therefore rendered a 71-glyph sha256 in a column the
// CSS had already collapsed to zero width (see `Transcript.module.css` on the
// auto-placement bug), one character per line. Two facts about that failure are
// worth separating: the vertical letter stack was a layout bug and is fixed in
// the stylesheet, and the wall of hash was a READING failure that no stylesheet
// fixes — a successful call has an outcome, and it belongs in a sentence.
//
// So the chip now leads with §7.2's two attributes as words (name, status) plus
// a headline drawn from the result document by `stream/toolSummary.ts`, and the
// arguments and the full field list move behind one `<details>`, collapsed.
// **Every `data-field` node is still rendered, in document order, inside that
// disclosure**: `<details>` hides its children from view, not from the DOM, and
// both gates read the attribute set (`e2e/stream.spec.ts` through `evaluateAll`,
// `test/stream/components.test.tsx` through `querySelectorAll`). §7.2's
// predicate is a statement about `F`, the chip's `data-field` values, and `F` is
// unchanged. §4.7's own instruction for the neighbouring case is the precedent:
// "a reading surface never receives `JSON.stringify` output… the raw object goes
// behind a `<details>`."

import { readToolCall, readToolResult } from "../../api/events";
import { copy } from "../../copy";
import { StatusBadge } from "../../system";
import { EventImageInline } from "./EventImage";
import { parseToolResult, referenceFields } from "../../stream/toolResult";
import { chipHeadline, displayValue, type ToolSummary } from "../../stream/toolSummary";
import type { ChipStatus, TranscriptItem } from "../../stream/transcript";
import styles from "./Transcript.module.css";

export interface ToolChipProps {
  readonly toolName: string;
  readonly call: TranscriptItem;
  readonly result: TranscriptItem | null;
  readonly images: readonly TranscriptItem[];
  readonly status: ChipStatus;
  readonly children?: React.ReactNode;
}

/** The chip's `data-*` contract, shared with the `ask_user` widget (§7.2). */
export interface ChipAttributes {
  readonly "data-tool-name": string;
  readonly "data-status": ChipStatus;
  readonly "data-event-id": string;
  readonly "data-surface": string;
  readonly "data-tool-call-id"?: string;
}

export function chipAttributes(
  toolName: string,
  status: ChipStatus,
  anchor: TranscriptItem,
): ChipAttributes {
  const base = {
    "data-tool-name": toolName,
    "data-status": status,
    "data-event-id": anchor.eventId,
    "data-surface": anchor.surface,
  } as const;
  return anchor.toolCallId === null ? base : { ...base, "data-tool-call-id": anchor.toolCallId };
}

export function ToolChip({
  toolName,
  call,
  result,
  images,
  status,
  children,
}: ToolChipProps): React.JSX.Element {
  const callPayload = readToolCall(call.payload);
  const resultPayload = result === null ? null : readToolResult(result.payload);
  const parsed = resultPayload === null ? null : parseToolResult(resultPayload.text);
  const fields = parsed !== null && parsed.state === "parsed" ? parsed.fields : [];
  const refs = new Set(referenceFields(fields));
  const fieldState = parsed === null ? undefined : parsed.state;
  const args = callPayload?.args;
  const summary = chipHeadline({
    args,
    doc: parsed !== null && parsed.state === "parsed" ? parsed.doc : null,
    fields: parsed !== null && parsed.state === "parsed" ? parsed.fields : [],
  });

  return (
    <article
      className={styles["chip"]}
      {...chipAttributes(toolName, status, call)}
      {...(fieldState === undefined ? {} : { "data-field-state": fieldState })}
    >
      <header className={styles["chipHeader"]}>
        <span className={styles["chipName"]}>{toolName}</span>
        {/* §4.7: "status via `Badge`". The shipped bordered pill was the fifth
            independent spelling of a status readout in this repo; the primitive
            makes it the same recipe as a check badge and a DFM severity, icon
            and word included. */}
        <StatusBadge status={status}>{copy.stream.chip.status[status]}</StatusBadge>
      </header>

      {status === "unknown" ? (
        <p className={styles["note"]}>{copy.stream.chip.unknownWhy}</p>
      ) : null}
      {status === "running" ? (
        <p className={styles["note"]}>{copy.stream.chip.runningWhy}</p>
      ) : null}
      {result !== null && result.eventId === call.eventId ? (
        <p className={styles["note"]}>{copy.stream.chip.callMissing}</p>
      ) : null}

      {summary.parts.length > 0 || (parsed !== null && parsed.state === "parsed") ? (
        <SummaryLine summary={summary} />
      ) : null}

      {children}

      {/* The result's OWN identity goes on the result block. A chip carries the
          call's id, so without this the `tool_result` event — a real event with
          a real archived identity — would be the one kind a reopened transcript
          renders and never names. It is omitted when call and result are the
          same event (an orphan result), so no id is ever in the DOM twice. */}
      {parsed === null ? null : parsed.state === "unparsed" ? (
        <div
          className={styles["degraded"]}
          {...(result !== null && result.eventId !== call.eventId
            ? { "data-event-id": result.eventId, "data-surface": result.surface }
            : {})}
        >
          <p className={styles["note"]}>{copy.stream.chip.unparsed[parsed.reason]}</p>
          <p className={styles["note"]}>{copy.stream.chip.unparsedNote}</p>
          {resultPayload !== null && resultPayload.text !== "" ? (
            <details className={styles["rawResult"]}>
              <summary className={styles["rawSummary"]}>{copy.stream.chip.raw}</summary>
              <pre className={styles["raw"]}>{resultPayload.text}</pre>
            </details>
          ) : null}
        </div>
      ) : null}

      {/* One disclosure for the wire format: the call's arguments and every key
          of the result document. Collapsed, and the `data-field` nodes inside
          are in the DOM whether it is open or not (see the module header). */}
      {args === undefined && parsed?.state !== "parsed" ? null : (
        <details className={styles["detail"]} data-chip-detail="">
          <summary className={styles["detailSummary"]}>
            {parsed !== null && parsed.state === "parsed"
              ? copy.stream.chip.detail(parsed.fields.length)
              : copy.stream.chip.detailNoFields}
          </summary>
          {args === undefined ? null : (
            <div className={styles["args"]}>
              <span className={styles["argsLabel"]}>{copy.stream.chip.arguments}</span>
              <code className={styles["argsBody"]}>{displayValue(args).full}</code>
            </div>
          )}
          {parsed === null || parsed.state !== "parsed" ? null : (
            <dl
              className={styles["fields"]}
              {...(result !== null && result.eventId !== call.eventId
                ? { "data-event-id": result.eventId, "data-surface": result.surface }
                : {})}
            >
              {parsed.fields.map((field) => {
                const shown = displayValue(parsed.doc[field]);
                return (
                  <div
                    key={field}
                    className={styles["field"]}
                    data-field={field}
                    {...(refs.has(field) ? { "data-field-reference": "true" } : {})}
                  >
                    <dt className={styles["fieldName"]}>{field}</dt>
                    {/* The whole value on `title`, always: an elided digest a
                        reader cannot recover is a digest this page destroyed. */}
                    <dd className={styles["fieldValue"]} title={shown.full}>
                      {shown.text}
                    </dd>
                  </div>
                );
              })}
            </dl>
          )}
        </details>
      )}

      {images.length > 0 ? (
        <div className={styles["chipImages"]}>
          {images.map((image) => (
            // The image rendering rules (§7.3's live bytes, historical metadata
            // placeholder, undecodable placeholder) live in one component, so a
            // chip's inline image and a standalone one can never disagree.
            <EventImageInline key={image.eventId} item={image} />
          ))}
        </div>
      ) : null}
    </article>
  );
}

/**
 * The headline: the outcome a successful call reported, in one line.
 *
 * Composed of the document's own keys and values (`stream/toolSummary.ts` picks
 * them; nothing here re-words one). When the document carried nothing short
 * enough to headline — a result that is only refs and hashes — the line says
 * that instead of printing one, and points at the disclosure that holds them.
 */
function SummaryLine({ summary }: { readonly summary: ToolSummary }): React.JSX.Element {
  if (summary.parts.length === 0) {
    return (
      <p className={styles["summary"]} data-chip-summary="opaque">
        {copy.stream.chip.summaryOpaque}
      </p>
    );
  }
  return (
    <p className={styles["summary"]} data-chip-summary="fields">
      {summary.parts.map((part) => (
        <span key={part.field} className={styles["summaryPart"]}>
          <span className={styles["summaryField"]}>{part.field}</span>
          <span className={styles["summaryValue"]}>{part.value}</span>
        </span>
      ))}
    </p>
  );
}
