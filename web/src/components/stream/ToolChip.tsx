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
// THE RESTING FACE, AMENDED 2026-09-01 (§7.2 (a)-(d)). Three changes, none of
// them to the attribute contract above:
//
// * **A repeat group renders as one row.** `stream/transcript.ts` decides the
//   grouping (§7.2 (e)) and hands it here as `repeat`; this component draws the
//   `×N` count in §3.8's `.data` role and carries `data-chip-repeat`,
//   `data-event-ids` and `data-tool-call-ids` so **no id leaves the DOM**. The
//   members' RESULT ids ride on the field list the same way a lone chip's does.
// * **The `N result fields` count is not on the resting face.** It is the
//   disclosure's first line, rendered only while the disclosure is open, so a
//   closed chip does not spend a row on chrome about a list.
// * **At most one preamble note, below the headline.** `unknownWhy`,
//   `runningWhy` and `callMissing` used to stack; the most specific one draws
//   (`callMissing` → `unknown` → `running`) and every applicable condition —
//   drawn or suppressed — stays on the chip's `title`, so nothing is lost.
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

import { useState } from "react";
import { readToolCall, readToolResult } from "../../api/events";
import { copy } from "../../copy";
import { StatusBadge } from "../../system";
import { EventImageInline } from "./EventImage";
import { parseToolResult, referenceFields } from "../../stream/toolResult";
import { chipHeadline, displayValue, type ToolSummary } from "../../stream/toolSummary";
import type { ChipMember, ChipStatus, TranscriptItem } from "../../stream/transcript";
import styles from "./Transcript.module.css";

export interface ToolChipProps {
  readonly toolName: string;
  readonly call: TranscriptItem;
  readonly result: TranscriptItem | null;
  readonly images: readonly TranscriptItem[];
  readonly status: ChipStatus;
  /** §7.2 (a)'s repeat group, first member included. `null` for a lone chip. */
  readonly repeat?: readonly ChipMember[] | null;
  readonly children?: React.ReactNode;
}

/** The chip's `data-*` contract, shared with the `ask_user` widget (§7.2). */
export interface ChipAttributes {
  readonly "data-tool-name": string;
  readonly "data-status": ChipStatus;
  readonly "data-event-id": string;
  readonly "data-surface": string;
  readonly "data-tool-call-id"?: string;
  readonly "data-chip-repeat"?: string;
  readonly "data-event-ids"?: string;
  readonly "data-tool-call-ids"?: string;
}

/**
 * §7.2's attributes, plus §7.2 (a)'s plural forms when this row is a group.
 *
 * `data-event-id` stays the FIRST member's, so every address that resolved
 * before the amendment still resolves, and `data-event-ids` carries every
 * member's id in render order — the first one included, so one attribute reads
 * as the whole group rather than as the tail of it. `data-tool-call-id` goes
 * plural on a coalesced row and stays singular on a single chip, exactly as
 * §7.2 (a) words it.
 */
export function chipAttributes(
  toolName: string,
  status: ChipStatus,
  anchor: TranscriptItem,
  members: readonly ChipMember[] | null = null,
): ChipAttributes {
  const base = {
    "data-tool-name": toolName,
    "data-status": status,
    "data-event-id": anchor.eventId,
    "data-surface": anchor.surface,
  } as const;
  if (members === null || members.length < 2) {
    return anchor.toolCallId === null ? base : { ...base, "data-tool-call-id": anchor.toolCallId };
  }
  const callIds = members
    .map((member) => member.call.toolCallId)
    .filter((id): id is string => id !== null);
  return {
    ...base,
    "data-chip-repeat": String(members.length),
    "data-event-ids": members.map((member) => member.call.eventId).join(" "),
    ...(callIds.length === 0 ? {} : { "data-tool-call-ids": callIds.join(" ") }),
  };
}

/**
 * One `Arguments` block per DISTINCT argument document across the group.
 *
 * A group is defined by its results, so its members' arguments may differ — and
 * a row that showed only the first member's arguments would be claiming they
 * were all that call. Distinct documents each render once, in first-appearance
 * order, with the number of members that sent them: a count of what the server
 * sent, never a value this component composed (§1).
 */
interface ArgumentBlock {
  readonly text: string;
  readonly count: number;
}

export function argumentBlocks(members: readonly ChipMember[]): readonly ArgumentBlock[] {
  const order: string[] = [];
  const counts = new Map<string, number>();
  for (const member of members) {
    const args = readToolCall(member.call.payload)?.args;
    if (args === undefined) continue;
    const text = displayValue(args).full;
    const seen = counts.get(text);
    if (seen === undefined) {
      order.push(text);
      counts.set(text, 1);
    } else {
      counts.set(text, seen + 1);
    }
  }
  return order.map((text) => ({ text, count: counts.get(text) ?? 1 }));
}

export function ToolChip({
  toolName,
  call,
  result,
  images,
  status,
  repeat = null,
  children,
}: ToolChipProps): React.JSX.Element {
  // The disclosure's own state, because §7.2 (b) makes the field count a thing
  // the DOM must not carry while the disclosure is shut — an attribute selector
  // and a `<details>` the browser opens on its own cannot express that.
  const [detailOpen, setDetailOpen] = useState(false);

  const members: readonly ChipMember[] = repeat ?? [{ call, result }];
  const coalesced = members.length > 1;
  const callPayload = readToolCall(call.payload);
  const resultPayload = result === null ? null : readToolResult(result.payload);
  const parsed = resultPayload === null ? null : parseToolResult(resultPayload.text);
  const fields = parsed !== null && parsed.state === "parsed" ? parsed.fields : [];
  const refs = new Set(referenceFields(fields));
  const fieldState = parsed === null ? undefined : parsed.state;
  const args = callPayload?.args;
  const argBlocks = argumentBlocks(members);
  const doc = parsed !== null && parsed.state === "parsed" ? parsed.doc : null;
  // A coalesced row headlines the SHARED DOCUMENT (§7.2 (a)). The call operand
  // is a fact about one call, and the members' calls need not agree on it.
  const summary = chipHeadline(coalesced ? { doc, fields } : { args, doc, fields });

  // §7.2 (c): every exceptional condition that holds, most specific first. The
  // first one draws below the headline; all of them stay on `title`.
  const conditions: string[] = [];
  if (result !== null && result.eventId === call.eventId) {
    conditions.push(copy.stream.chip.callMissing);
  }
  if (status === "unknown") conditions.push(copy.stream.chip.unknownWhy);
  if (status === "running") conditions.push(copy.stream.chip.runningWhy);
  const note = conditions[0] ?? null;

  // The result events' OWN identities. A lone chip carries one; a coalesced row
  // carries every member's, because a group that swallowed a result id would be
  // an id G4.11 cannot find in the reopened DOM.
  const resultIds: string[] = [];
  for (const member of members) {
    if (member.result === null) continue;
    if (member.result.eventId === member.call.eventId) continue;
    resultIds.push(member.result.eventId);
  }
  const resultIdentity =
    result !== null && result.eventId !== call.eventId
      ? {
          "data-event-id": result.eventId,
          "data-surface": result.surface,
          ...(coalesced ? { "data-event-ids": resultIds.join(" ") } : {}),
        }
      : {};

  return (
    <article
      className={styles["chip"]}
      {...chipAttributes(toolName, status, call, repeat)}
      {...(fieldState === undefined ? {} : { "data-field-state": fieldState })}
      {...(conditions.length === 0 ? {} : { title: conditions.join(" ") })}
    >
      <header className={styles["chipHeader"]}>
        <span className={styles["chipName"]}>{toolName}</span>
        {/* §7.2 (a): the count, in §3.8's `.data` role — "never as a sentence". */}
        {coalesced ? <span className={styles["chipRepeat"]}>×{members.length}</span> : null}
        {/* §4.7: "status via `Badge`". The shipped bordered pill was the fifth
            independent spelling of a status readout in this repo; the primitive
            makes it the same recipe as a check badge and a DFM severity, icon
            and word included. */}
        <StatusBadge status={status}>{copy.stream.chip.status[status]}</StatusBadge>
      </header>

      {/* §7.2 (d): a coalesced row is never `data-chip-summary` absent — an
          `ok` group whose result cannot be headlined still says so. */}
      {coalesced || summary.parts.length > 0 || (parsed !== null && parsed.state === "parsed") ? (
        <SummaryLine summary={summary} />
      ) : null}

      {/* §7.2 (c): at most one note, and BELOW the headline. */}
      {note === null ? null : <p className={styles["note"]}>{note}</p>}

      {children}

      {/* The result's OWN identity goes on the result block. A chip carries the
          call's id, so without this the `tool_result` event — a real event with
          a real archived identity — would be the one kind a reopened transcript
          renders and never names. It is omitted when call and result are the
          same event (an orphan result), so no id is ever in the DOM twice. */}
      {parsed === null ? null : parsed.state === "unparsed" ? (
        <div className={styles["degraded"]} {...resultIdentity}>
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
      {argBlocks.length === 0 && parsed?.state !== "parsed" ? null : (
        <details
          className={styles["detail"]}
          data-chip-detail=""
          open={detailOpen}
          onToggle={(event) => {
            setDetailOpen(event.currentTarget.open);
          }}
        >
          <summary className={styles["detailSummary"]}>{copy.stream.chip.detailLabel}</summary>
          {/* §7.2 (b): the field count lives INSIDE the disclosure, as its first
              line. On the resting face it was chrome about a list; here it is
              what a reader who asked for the list is about to get. */}
          {detailOpen && parsed !== null && parsed.state === "parsed" ? (
            <p className={styles["detailCount"]} data-chip-detail-count="">
              {copy.stream.chip.detail(parsed.fields.length)}
            </p>
          ) : null}
          {argBlocks.map((block) => (
            <div key={block.text} className={styles["args"]}>
              <span className={styles["argsLabel"]}>{copy.stream.chip.arguments}</span>
              {block.count > 1 ? (
                <span className={styles["chipRepeat"]}>×{block.count}</span>
              ) : null}
              <code className={styles["argsBody"]}>{block.text}</code>
            </div>
          ))}
          {parsed === null || parsed.state !== "parsed" ? null : (
            <dl className={styles["fields"]} {...resultIdentity}>
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
