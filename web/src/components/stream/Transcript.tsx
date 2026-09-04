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

import { useState } from "react";

import { readAudit, readTerminal } from "../../api/events";
import { copy } from "../../copy";
import { Markdown } from "../../stream/markdown";
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
          // §7A.5, amended 2026-09-03: `data-echo-state` is UNCONDITIONAL and
          // defaults to `sent`, while the row's `state` field stays optional.
          // The split is deliberate — the model never asserts that a POST it
          // learned nothing about succeeded, and the DOM never omits the
          // attribute the state is read from. `data-refused-reason` carries the
          // server's own reason word VERBATIM: never translated, never
          // collapsed into a neighbour, and a reason this build has never heard
          // of still renders, correctly, as itself.
          {...(row.row === "local-prompt"
            ? {
                "data-local-echo": "1",
                "data-echo-state": row.state ?? "sent",
                ...(typeof row.refusedReason === "string"
                  ? { "data-refused-reason": row.refusedReason }
                  : {}),
              }
            : {})}
          {...(row.row === "user-prompt" ? { "data-event-id": row.eventId } : {})}
          // §7.3(c), amended 2026-09-03: the outcome's state rides the ROW, beside
          // `data-row="turn-outcome"`, and the row carries NO `data-event-id` —
          // an outcome is not an event, and minting one for it would be the
          // third identity §2.8 declines to invent. The state is also a WORD
          // inside the row; this attribute is the machine-readable half only.
          {...(row.row === "turn-outcome"
            ? { "data-outcome-state": row.outcome.state }
            : {})}
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
      //
      // §7.4, amended 2026-09-03: WHICH boundary it is decides the label. The
      // kind is `stream/transcript.ts`'s decision, taken from held frames alone
      // (`seamKind`); this row reads it and derives nothing. Painting "End of
      // the recorded transcript" over a run this tab attached to mid-flight is
      // a claim the tab has no basis for, and the reader who believes it reads
      // a truncated run as a whole one.
      return (
        <p className={styles["seam"]} data-seam="1" data-seam-kind={row.kind}>
          {row.kind === "mid-run" ? copy.stream.seamMidRun : copy.stream.seam}
        </p>
      );
    case "local-prompt":
      // §7.3 (C2): the sent text, markdown-rendered, with the category's
      // visible-at-rest marker and its accessible equivalent.
      //
      // §7A.5, amended 2026-09-03: a NAMED refusal adds a second marker word
      // beside `unrecorded` and never removes the text — C2's never-removed
      // rule is unchanged because the words were typed. The second marker is
      // rendered here rather than left to `data-echo-state`, because an
      // attribute is not an affordance and colour alone is not one either.
      //
      // §7.3(a), amended 2026-09-03: the echo is the OPERATOR speaking, and it
      // now says so on its face — the `operator` role marker beside the
      // category's own markers, and the shared `.operatorTurn` rule and indent
      // (`Transcript.module.css`). A live echo and a restored prompt are the
      // same voice from two sources, so they carry the same affordance; what
      // differs is the `unrecorded` marker, which is about the ROW's status and
      // not about who spoke.
      return (
        <div className={styles["localPrompt"]} title={copy.stream.localEcho.title}>
          <p className={styles["markerLine"]}>
            <span className={styles["roleMarker"]} aria-hidden="true">
              {copy.stream.userPrompt.marker}
            </span>
            <span className={styles["presentationMarker"]} aria-hidden="true">
              {copy.stream.localEcho.marker}
            </span>
            <span className={styles["visuallyHidden"]}>{copy.stream.localEcho.accessible}</span>
            {row.state === "refused" ? (
              <span title={copy.stream.localEcho.refused.title}>
                <span className={styles["presentationMarker"]} aria-hidden="true">
                  {typeof row.refusedReason === "string" && row.refusedReason !== ""
                    ? `${copy.stream.localEcho.refused.marker}: ${row.refusedReason}`
                    : copy.stream.localEcho.refused.marker}
                </span>
                {/* The accessible half states the fact the marker word implies:
                    the turn did NOT start. §3.9's colour-is-never-alone applied
                    to honesty — the same rule C2's own equivalent exists for. */}
                <span className={styles["visuallyHidden"]}>
                  {copy.stream.localEcho.refused.accessible}
                </span>
              </span>
            ) : null}
          </p>
          {/* §7.3, W4: the operator's own line breaks are CONTENT — they pressed
              Return — so this caller asks for them. Agent prose does not, which
              is markdown's own rule and the right one for a model that hard-wraps
              its paragraphs. One flag, one renderer, so the sanitizing half
              cannot diverge between the two voices. */}
          <div className={styles["localPromptText"]} data-markdown="">
            <Markdown text={row.text} preserveLineBreaks />
          </div>
        </div>
      );
    case "user-prompt":
      // §7.3, amended 2026-09-03 — the restored operator turn, and the three
      // things it must show.
      //
      // (a) ROLE IS VISIBLE AT REST: the `operator` marker word, in `.code` at
      //     `--ink-muted`, plus the rule-and-indent of `.operatorTurn`. The
      //     agent's own rows carry no marker, because the model is this
      //     surface's default voice and a marker on every row is a marker on
      //     none. `data-row` is NOT this affordance: an attribute cannot be
      //     read by anyone looking at the screen.
      // (b) THE ENVELOPE IS A CLOSED DISCLOSURE, below — never inline, and
      //     never as the operator's words.
      // (c) The outcome is its OWN row (`turn-outcome`), emitted by
      //     `stream/transcript.ts` directly under this one.
      return (
        <div className={styles["userPrompt"]}>
          <p className={styles["markerLine"]} data-prompt-origin={row.origin ?? "operator"}>
            <span className={styles["roleMarker"]} aria-hidden="true">
              {row.origin === "agent"
                ? copy.stream.userPrompt.markerAgent
                : copy.stream.userPrompt.marker}
            </span>
            <span className={styles["visuallyHidden"]}>
              {row.origin === "agent"
                ? copy.stream.userPrompt.accessibleAgent
                : copy.stream.userPrompt.accessible}
            </span>
          </p>
          {row.textUnrecoverable ? (
            // §2.8(3)'s honest answer. The record could not separate the
            // operator's sentence from the server's projection, and a GUESS —
            // stripping a heading, cutting at a blank line — would put the
            // server's words in the operator's mouth some of the time and never
            // say which times. A named absence is the only honest row here.
            <p className={styles["promptTextAbsent"]} data-prompt-text="unrecoverable">
              {copy.stream.userPrompt.unrecoverable}
            </p>
          ) : (
            <div className={styles["localPromptText"]} data-markdown="">
              {/* The typed line breaks, kept — see the local echo above. */}
              <Markdown text={row.text} preserveLineBreaks />
            </div>
          )}
          {row.envelope === null ? null : <PromptEnvelope envelope={row.envelope} />}
        </div>
      );
    case "turn-outcome":
      // §7.3(c): one row, directly under its turn's prompt row and above that
      // turn's replies, carrying the state AS A WORD and the house sentence.
      // The recorded `message` renders VERBATIM BESIDE the sentence and never
      // in place of it — the record's wording may be empty, absent or
      // unhelpful, and the house sentence is what guarantees the row says
      // something. Nothing here derives an outcome: this row exists only
      // because `user_prompts[].outcome` was present in the record.
      return (
        <p className={styles["turnOutcome"]}>
          <span className={styles["turnOutcomeState"]}>{row.outcome.state}</span>
          <span>{copy.stream.turnOutcome[row.outcome.state]}</span>
          {row.outcome.message === undefined || row.outcome.message === "" ? null : (
            <span className={styles["turnOutcomeMessage"]}>{row.outcome.message}</span>
          )}
        </p>
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
 * §7.3(b), amended 2026-09-03 — the workspace-context envelope, behind a
 * closed-by-default disclosure inside the operator's row.
 *
 * THE LABEL NAMES THE AUTHOR. The block sits inside a row whose other words are
 * the operator's, so a label reading "context" would read as something they
 * wrote; `copy.stream.userPrompt.envelope.label` says whose projection it is,
 * and the accessible equivalent says it again for a reader who never sees the
 * summary's own phrasing in place.
 *
 * PREFORMATTED, NEVER MARKDOWN. §7.3(b) is explicit: the envelope opens with a
 * `#` heading (`server/.../context.py`), so passing it through `Markdown` would
 * mint an `<h1>` inside an operator's row — the server's projection wearing the
 * loudest type on the surface, inside the words it is not. `<pre>` also keeps
 * the block's own line breaks, which are its structure.
 *
 * `aria-expanded` is written from the element's OWN toggle state rather than
 * assumed: a `<details>` that says `aria-expanded="false"` while standing open
 * is worse than one that says nothing. It reuses §7A.3's disclosure BEHAVIOUR
 * and none of its STATE — the composer's preview is about a turn being
 * composed, this is a record of one already sent, and neither reads the other's
 * flag.
 */
function PromptEnvelope({ envelope }: { readonly envelope: string }): React.JSX.Element {
  const [open, setOpen] = useState(false);
  return (
    <details
      className={styles["envelope"]}
      data-prompt-envelope=""
      aria-expanded={open}
      title={copy.stream.userPrompt.envelope.title}
      onToggle={(event) => {
        setOpen(event.currentTarget.open);
      }}
    >
      <summary className={styles["envelopeSummary"]}>
        <span>{copy.stream.userPrompt.envelope.label}</span>
        <span className={styles["visuallyHidden"]}>
          {copy.stream.userPrompt.envelope.accessible}
        </span>
      </summary>
      <pre className={styles["envelopeBody"]}>{envelope}</pre>
    </details>
  );
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
