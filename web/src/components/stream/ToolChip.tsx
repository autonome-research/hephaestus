// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0

import { useDisclosure } from "../../stream/disclosure";
import { readToolCall, readToolResult } from "../../api/events";
import { copy } from "../../copy";
import { StatusBadge } from "../../system";
import { EventImageInline } from "./EventImage";
import { parseToolResult, referenceFields } from "../../stream/toolResult";
import { displayValue } from "../../stream/toolSummary";
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

/** Shared with the actionable ask_user widget. One identity per call. */
export function chipAttributes(toolName: string, status: ChipStatus, anchor: TranscriptItem) {
  return {
    "data-tool-name": toolName,
    "data-status": status,
    "data-event-id": anchor.eventId,
    "data-surface": anchor.surface,
    ...(anchor.toolCallId === null ? {} : { "data-tool-call-id": anchor.toolCallId }),
  };
}

/**
 * Each tool call gets one native, closed-by-default disclosure. The summary is
 * only the tool's actual name and evidence-based status, not generated prose.
 * Missing results say "No result" rather than claiming an old call is running.
 * Args, results and images stay mounted with their own identities when closed.
 */
export function ToolChip({ toolName, call, result, images, status, children }: ToolChipProps): React.JSX.Element {
  const [open, setOpen] = useDisclosure("tool");
  const callPayload = readToolCall(call.payload);
  const resultPayload = result === null ? null : readToolResult(result.payload);
  const parsed = resultPayload === null ? null : parseToolResult(resultPayload.text);
  const fields = parsed?.state === "parsed" ? parsed.fields : [];
  const refs = new Set(referenceFields(fields));
  const conditions: string[] = [];
  if (result !== null && result.eventId === call.eventId) conditions.push(copy.stream.chip.callMissing);
  if (status === "unknown") conditions.push(copy.stream.chip.unknownWhy);
  if (status === "running") conditions.push(copy.stream.chip.runningWhy);
  const resultIdentity = result !== null && result.eventId !== call.eventId
    ? { "data-event-id": result.eventId, "data-surface": result.surface }
    : {};

  return (
    <article className={styles["chip"]} {...chipAttributes(toolName, status, call)}
      {...(parsed === null ? {} : { "data-field-state": parsed.state })}
      {...(conditions.length === 0 ? {} : { title: conditions.join(" ") })}>
      <details className={styles["detail"]} data-chip-detail="" open={open}
        onToggle={(event) => { setOpen(event.currentTarget.open); }}>
        <summary className={styles["toolSummary"]} aria-expanded={open}>
          <span className={styles["chipName"]}>{toolName || copy.stream.chip.unnamed}</span>
          {status === "ok" ? <span className={styles["toolDone"]} data-tool-outcome="ok">{copy.stream.chip.status[status]}</span>
            : <StatusBadge status={status}>{copy.stream.chip.status[status]}</StatusBadge>}
        </summary>
        <div className={styles["toolBody"]}>
          {conditions.map((condition) => <p key={condition} className={styles["note"]}>{condition}</p>)}
          {callPayload?.args === undefined ? null : (
            <div className={styles["args"]}>
              <span className={styles["argsLabel"]}>{copy.stream.chip.arguments}</span>
              <code className={styles["argsBody"]}>{displayValue(callPayload.args).full}</code>
            </div>
          )}
          {result === null ? null : (
            <div {...resultIdentity}>
              <p className={styles["argsLabel"]}>{copy.stream.chip.fields}</p>
              {parsed?.state === "parsed" ? (
                <>
                  {open ? <p className={styles["detailCount"]} data-chip-detail-count="">
                    {copy.stream.chip.detail(fields.length)}
                  </p> : null}
                  <dl className={styles["fields"]}>
                    {fields.map((field) => (
                      <div key={field} className={styles["field"]} data-field={field}
                        {...(refs.has(field) ? { "data-field-reference": "true" } : {})}>
                        <dt className={styles["fieldName"]}>{field}</dt>
                        <dd className={styles["fieldValue"]}>{displayValue(parsed.doc[field]).full}</dd>
                      </div>
                    ))}
                  </dl>
                </>
              ) : (
                <>
                  <p className={styles["note"]}>{parsed?.state === "unparsed"
                    ? copy.stream.chip.unparsed[parsed.reason] : copy.stream.chip.unknownWhy}</p>
                  <pre className={styles["raw"]}>{resultPayload?.text ?? JSON.stringify(result.payload, null, 2)}</pre>
                </>
              )}
            </div>
          )}
          {images.length === 0 ? null : <div className={styles["chipImages"]}>
            {images.map((image) => <EventImageInline key={image.eventId} item={image} />)}
          </div>}
        </div>
      </details>
      {/* Failures are visible at rest; their exact result is one keypress away. */}
      {status === "error" ? <p className={styles["toolFailure"]}>{copy.stream.chip.failed}</p> : null}
      {children}
    </article>
  );
}
