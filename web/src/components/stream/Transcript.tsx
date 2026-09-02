// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The transcript's rows (INTERFACE.md §7.3, §8).
//
// This component renders the closed row vocabulary `stream/transcript.ts`
// produces and decides nothing of its own. Every honesty claim the panel makes —
// the seam between the historical prefix and the live suffix, the named
// absences, the labelled resync break — is a *row*, produced by a pure function
// and tested there, so what the DOM says and what the model decided cannot drift
// apart.

import { readAudit, readTerminal } from "../../api/events";
import { copy } from "../../copy";
import type { RuntimeFault } from "../../stream/runtimeFault";
import type { PanelRow, TranscriptItem } from "../../stream/transcript";
import { runsWithTerminal } from "../../stream/transcript";
import { AskUserWidget } from "./AskUserWidget";
import { TextBlock, ThoughtSection } from "./ThoughtSection";
import { EventImageInline } from "./EventImage";
import { ToolChip } from "./ToolChip";
import styles from "./Transcript.module.css";

export function Transcript({
  rows,
  runtimeFault = null,
}: {
  readonly rows: readonly PanelRow[];
  readonly runtimeFault?: RuntimeFault | null;
}): React.JSX.Element {
  const terminals = runsWithTerminal(rows);
  return (
    <ol className={styles["transcript"]} data-testid="transcript">
      {rows.map((row) => (
        <li key={row.key} className={styles["row"]} data-row={row.row}>
          <Row row={row} runtimeFault={runtimeFault} terminals={terminals} />
        </li>
      ))}
    </ol>
  );
}

function Row({
  row,
  runtimeFault,
  terminals,
}: {
  readonly row: PanelRow;
  readonly runtimeFault: RuntimeFault | null;
  readonly terminals: ReadonlySet<string>;
}): React.JSX.Element | null {
  switch (row.row) {
    case "text":
      return <TextBlock items={row.items} />;
    case "thought":
      return <ThoughtSection items={row.items} />;
    case "chip":
      return (
        <ToolChip
          toolName={row.toolName}
          call={row.call}
          result={row.result}
          images={row.images}
          status={row.status}
          // §7.2 (a): the repeat group `stream/transcript.ts` decided. Grouping
          // is not a chip's decision to make — a chip cannot see its neighbours.
          repeat={row.repeat ?? null}
        />
      );
    case "ask": {
      const runId = (row.question ?? row.call ?? row.answer)?.runId ?? null;
      return (
        <AskUserWidget
          row={row}
          death={{
            fault: runtimeFault,
            runHasTerminal: runId !== null && terminals.has(runId),
          }}
        />
      );
    }
    case "image":
      return <EventImageInline item={row.item} />;
    case "audit":
      return (
        <p
          className={styles["audit"]}
          data-event-id={row.item.eventId}
          data-surface={row.item.surface}
          data-audit="1"
        >
          <span className={styles["auditLabel"]}>{copy.stream.audit}</span>
          <span>{readAudit(row.item.payload) ?? copy.absent.unavailable}</span>
        </p>
      );
    case "terminal":
      return <TerminalBand item={row.item} />;
    case "unknown":
      return (
        <p
          className={styles["note"]}
          data-event-id={row.item.eventId}
          data-surface={row.item.surface}
          data-unknown-kind={row.item.rawKind}
        >
          {copy.stream.unknownKind}
        </p>
      );
    case "absence":
      // §8(d), amended 2026-09-01: one short sentence in the transcript's own
      // type role — not a bordered blockquote. The notice still renders exactly
      // once, in place, and the fuller reading is on `title`: shortening is not
      // deletion, and §8's absence rule is re-affirmed by this row existing.
      return (
        <p
          className={styles["absence"]}
          data-absence={row.absence}
          title={copy.stream.absenceDetail[row.absence]}
        >
          {copy.stream.absence[row.absence]}
        </p>
      );
    case "seam":
      // §8: "the boundary between them is a visible seam, not a silent join."
      return (
        <p className={styles["seam"]} data-seam="1">
          {copy.stream.seam}
        </p>
      );
    case "resync":
      return (
        <p
          className={styles["resync"]}
          data-resync={row.resync.outcome}
          role="status"
          title={copy.stream.resyncDetail[row.resync.outcome]}
        >
          <span className={styles["resyncTitle"]}>{copy.stream.resync.title}</span>
          {/* §7.4(d): the verdict is drawn, the mechanism is on `title`. `gap`
              still says the events are NOT recovered — §7.4(c) keeps this break
              exactly as specified, and nothing here permits a silent one. */}
          <span>{copy.stream.resync[row.resync.outcome]}</span>
          {row.resync.after === null ? null : (
            <span className={styles["resyncAfter"]}>
              {copy.stream.resync.after}: {row.resync.after.run_id}#{row.resync.after.seq}
            </span>
          )}
        </p>
      );
    default:
      return null;
  }
}

/**
 * §7.3's run-terminal band, carrying `{state, terminal_id}`.
 *
 * `aria-live="polite"` because a run ending while the operator is reading
 * elsewhere is exactly the transition §3's accessibility floor names.
 *
 * The `backpressure_cancel` case renders its own copy — "a user must be able to
 * distinguish 'the model stopped' from 'the plumbing gave up'" — detected from
 * the terminal id, which is the only place that reason reaches the event stream.
 * See `api/events.ts::BACKPRESSURE_TERMINAL_PREFIX` for why.
 */
function TerminalBand({ item }: { readonly item: TranscriptItem }): React.JSX.Element {
  const payload = readTerminal(item.payload);
  const state = payload?.state ?? null;
  return (
    <div
      className={styles["terminal"]}
      data-event-id={item.eventId}
      data-surface={item.surface}
      data-terminal-state={state ?? "unknown"}
      // The exact identity of a terminal: its `seq` cannot survive a browser's
      // JSON parse (see `api/events.ts::liveEventId`), so the band identifies
      // itself by the id the pump actually minted.
      {...(payload === null || payload.terminalId === null
        ? {}
        : { "data-terminal-id": payload.terminalId })}
      {...(payload?.backpressure === true ? { "data-terminal-backpressure": "1" } : {})}
      role="status"
      aria-live="polite"
    >
      <span className={styles["terminalTitle"]}>{copy.stream.terminal.title}</span>
      <span>
        {copy.stream.terminal.state}: {state ?? copy.absent.unavailable}
      </span>
      {payload?.terminalId === null || payload === null ? null : (
        <span className={styles["terminalId"]}>
          {copy.stream.terminal.id}: {payload.terminalId}
        </span>
      )}
      {payload?.backpressure === true ? (
        <span className={styles["note"]}>{copy.stream.terminal.backpressure}</span>
      ) : null}
    </div>
  );
}
