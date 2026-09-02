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
import type { CyclePair, PanelRow, TranscriptItem } from "../../stream/transcript";
import { runsWithTerminal } from "../../stream/transcript";
import { StatusBadge } from "../../system";
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
        <li
          key={row.key}
          className={styles["row"]}
          data-row={row.row}
          // §7.3 (C2/C21): the presentation rows' DOM contract rides the same
          // element as `data-row`, so the archive matcher's by-name skip
          // (`local-prompt`, `run-start`) and the contract attributes are one
          // node. Neither ever carries `data-event-id` — the guard cuts both
          // ways, and the matcher treats any OTHER id-less `data-row` as a
          // mismatch.
          {...(row.row === "local-prompt" ? { "data-local-echo": "1" } : {})}
          {...(row.row === "run-start" ? { "data-run-id": row.runId } : {})}
          {...(row.row === "cycle" ? { "data-cycle": String(row.pairs.length) } : {})}
        >
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
    case "cycle": {
      // §7.2 (C4): the first pair in full — its chip (or ×N row) and its text
      // row — then one compact line per subsequent pair. The folded text rows
      // and the chips' Detail render behind the FIRST pair's disclosure, so
      // one disclosure opens the whole cycle. C5: every member event id and
      // tool-call id stays in the DOM — the compact lines carry their pair's,
      // the folded text keeps its own spans.
      const [first, ...rest] = row.pairs;
      if (first === undefined) return null;
      return (
        <div className={styles["cycle"]}>
          <ToolChip
            toolName={first.chip.toolName}
            call={first.chip.call}
            result={first.chip.result}
            images={first.chip.images}
            status={first.chip.status}
            repeat={first.chip.repeat ?? null}
            cycle={rest}
          />
          <TextBlock items={first.text.items} />
          {rest.map((pair, index) => (
            <CycleLine key={pair.chip.key} pair={pair} ordinal={index + 2} />
          ))}
        </div>
      );
    }
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
    case "local-prompt":
      // §7.3 (C2): the sent text verbatim, with the category's visible-at-rest
      // marker (`unrecorded`, `.code` muted) and its accessible equivalent —
      // `title` carries the long form and is never the only copy.
      return (
        <div className={styles["localPrompt"]} title={copy.stream.localEcho.title}>
          <span className={styles["presentationMarker"]} aria-hidden="true">
            {copy.stream.localEcho.marker}
          </span>
          <span className={styles["visuallyHidden"]}>{copy.stream.localEcho.accessible}</span>
          <span className={styles["localPromptText"]}>{row.text}</span>
        </div>
      );
    case "run-start":
      // §7.3 (C21): a rule line drawing the run id in `.code` and nothing
      // else. The rule-line-plus-run-id IS the visible-at-rest marker; the
      // accessible equivalent still states the not-a-recorded-event fact.
      return (
        <p className={styles["runStart"]} title={copy.stream.runStart.title}>
          <span className={styles["visuallyHidden"]}>{copy.stream.runStart.accessible}</span>
          {row.runId}
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
 * §7.2 (C4): one compact line for a cycle group's subsequent pair — the tool
 * name, the running `×N` ordinal, the shared status badge, and nothing else,
 * ≤ 1.5× target-min (36px) tall (`Transcript.module.css`).
 *
 * C5: the line renders this pair's chip, so it carries every member event id
 * in `data-event-ids` (call and result, repeat members included) and every
 * tool-call id in `data-tool-call-ids` — a compact line that lost an id would
 * fail §7.2 (a)'s set-equality testable. The pair's TEXT events are not here:
 * their content and ids render behind the first pair's disclosure, where the
 * folded rows keep their own `data-event-id` spans.
 */
function CycleLine({
  pair,
  ordinal,
}: {
  readonly pair: CyclePair;
  readonly ordinal: number;
}): React.JSX.Element {
  const members = pair.chip.repeat ?? [{ call: pair.chip.call, result: pair.chip.result }];
  const eventIds: string[] = [];
  const callIds: string[] = [];
  for (const member of members) {
    eventIds.push(member.call.eventId);
    if (member.result !== null && member.result.eventId !== member.call.eventId) {
      eventIds.push(member.result.eventId);
    }
    if (member.call.toolCallId !== null) callIds.push(member.call.toolCallId);
  }
  return (
    <p
      className={styles["cycleLine"]}
      data-cycle-line={String(ordinal)}
      data-event-ids={eventIds.join(" ")}
      {...(callIds.length === 0 ? {} : { "data-tool-call-ids": callIds.join(" ") })}
    >
      <span className={styles["chipName"]}>{pair.chip.toolName}</span>
      <span className={styles["chipRepeat"]}>×{ordinal}</span>
      <StatusBadge status={pair.chip.status}>
        {copy.stream.chip.status[pair.chip.status]}
      </StatusBadge>
    </p>
  );
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
