// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The transcript model (INTERFACE.md §7.2, §7.3, §8): normalized events in, a
// closed list of render rows out. Pure, synchronous, and tested directly against
// recorded normalized events, because everything the panel claims about a
// transcript is decided here rather than in JSX.
//
// THE ONE RULE THAT SHAPES EVERYTHING. §8: "Live and historical events are never
// merged, because they are not in one namespace." History renders as the
// transcript's **prefix**, the live stream as its suffix, and the boundary is a
// **visible seam**. So every function here takes a surface and never sees both:
// a tool call from history is never resolved by a live tool result, even though
// Pi's `toolCallId` happens to be the same string on both sides. Resolving
// across the seam would be the merge §8 forbids, and it would let a live result
// silently rewrite the status of a chip in the archived prefix.
//
// GROUPING IS LAYOUT, NEVER IDENTITY. Contiguous `text_delta` / `thought` events
// group into one paragraph or one collapsible section, because a live stream
// emits one event per delta and one `<details>` per token is not a transcript.
// **No event id is lost to grouping**: a group of one renders its id on the
// group element, and a group of many renders one span per event, each carrying
// its own `data-event-id`. G4.11 matches archived ids against the reopened DOM,
// so an id that grouping swallowed would be an id the gate cannot find.

import {
  isEventKind,
  historicalEventId,
  liveEventId,
  readToolCall,
  readToolResult,
  type EventFrame,
  type EventKind,
  type HistoryEventFrame,
} from "../api/events";

export type Surface = "live" | "historical";

/** One normalized event, with its identity already serialized in its namespace. */
export interface TranscriptItem {
  /** `<run_id>#<seq>` or `<session_id>@<ordinal>` — §2.8's two namespaces. */
  readonly eventId: string;
  readonly surface: Surface;
  /** `null` when the wire carried a kind outside §2.7's closed vocabulary. */
  readonly kind: EventKind | null;
  readonly rawKind: string;
  readonly runId: string;
  readonly seq: number;
  readonly sessionId: string | null;
  readonly toolCallId: string | null;
  readonly payload: unknown;
}

function item(
  surface: Surface,
  eventId: string,
  runId: string,
  seq: number,
  sessionId: string | null,
  frame: { readonly kind: string; readonly tool_call_id?: string; readonly payload?: unknown },
): TranscriptItem {
  return {
    eventId,
    surface,
    kind: isEventKind(frame.kind) ? frame.kind : null,
    rawKind: frame.kind,
    runId,
    seq,
    sessionId,
    toolCallId: frame.tool_call_id ?? null,
    payload: frame.payload,
  };
}

/** A live socket frame → an item in the `(run_id, seq)` namespace. */
export function liveItem(frame: EventFrame): TranscriptItem {
  return item(
    "live",
    liveEventId(frame.run_id, frame.seq),
    frame.run_id,
    frame.seq,
    frame.session_id,
    frame,
  );
}

/**
 * A history page event → an item in the `(session_id, ordinal)` namespace.
 *
 * The identity is built from the **page's** `session_id`, not from the frame's
 * `run_id`: the sidecar passes the session id into the parameter `history.ts`
 * names `runId`, so the frame's `run_id` is the session id under a misnamed key
 * (§2.8). Reading the page's own field says what is true instead of relying on
 * that coincidence.
 */
export function historicalItem(frame: HistoryEventFrame, sessionId: string): TranscriptItem {
  return item(
    "historical",
    historicalEventId(sessionId, frame.seq),
    frame.run_id,
    frame.seq,
    sessionId,
    frame,
  );
}

// ---------------------------------------------------------------------------
// §7.2 — the chip's status
// ---------------------------------------------------------------------------

/**
 * §7.2's status set — `running | ok | error` — plus its own named fallback.
 *
 * "A `tool_call` with no matching `tool_result` is `running`; a `tool_result`
 * with `isError` true is `error`, false is `ok`. There is no fourth value — a
 * cancelled run's orphan chips stay `running` until the `terminal` event marks
 * the *run*, because cancellation is a property of the run, not of a chip."
 *
 * `unknown` is the fourth value §7.2 names as its **fallback**, and it appears
 * only where the section says it may: a historical `tool_result` whose failure
 * flag could be recovered from neither Pi's own `isError` nor the serialized
 * envelope's `status`, so `normalizeEntries` emitted `null`. Reading that `null`
 * as `false` would state, as fact, that a call which failed succeeded — the
 * exact defect §7.2 requires removed. It renders with explanatory copy.
 */
export const CHIP_STATUSES = ["running", "ok", "error", "unknown"] as const;
export type ChipStatus = (typeof CHIP_STATUSES)[number];

export function chipStatus(result: TranscriptItem | null): ChipStatus {
  if (result === null) return "running";
  const payload = readToolResult(result.payload);
  if (payload === null) return "unknown";
  if (payload.isError === null) return "unknown";
  return payload.isError ? "error" : "ok";
}

// ---------------------------------------------------------------------------
// rows
// ---------------------------------------------------------------------------

/** The tool whose result §7.3 renders as a widget rather than a generic chip. */
export const ASK_USER_TOOL = "ask_user";

export type TranscriptRow =
  | { readonly row: "text"; readonly key: string; readonly items: readonly TranscriptItem[] }
  | { readonly row: "thought"; readonly key: string; readonly items: readonly TranscriptItem[] }
  | {
      readonly row: "chip";
      readonly key: string;
      readonly toolName: string;
      readonly call: TranscriptItem;
      readonly result: TranscriptItem | null;
      readonly images: readonly TranscriptItem[];
      readonly status: ChipStatus;
    }
  | {
      readonly row: "ask";
      readonly key: string;
      /** §7.3: `question` live, `tool_result` in a reopened transcript. */
      readonly source: "question" | "tool_result";
      readonly question: TranscriptItem | null;
      readonly call: TranscriptItem | null;
      readonly result: TranscriptItem | null;
      readonly answer: TranscriptItem | null;
      readonly status: ChipStatus;
    }
  | { readonly row: "image"; readonly key: string; readonly item: TranscriptItem }
  | { readonly row: "audit"; readonly key: string; readonly item: TranscriptItem }
  | { readonly row: "terminal"; readonly key: string; readonly item: TranscriptItem }
  | { readonly row: "unknown"; readonly key: string; readonly item: TranscriptItem };

interface ChipDraft {
  index: number;
  toolName: string;
  call: TranscriptItem;
  result: TranscriptItem | null;
  images: TranscriptItem[];
}

interface AskDraft {
  index: number;
  source: "question" | "tool_result";
  question: TranscriptItem | null;
  call: TranscriptItem | null;
  result: TranscriptItem | null;
  answer: TranscriptItem | null;
}

/**
 * Group one surface's events into render rows, in arrival order.
 *
 * Pairing is by `tool_call_id` **within this call only** — see the module
 * docstring on why the two surfaces are grouped separately.
 *
 * `progress` produces **no row at all**. §7.3: "a coalesced transient indicator
 * that never accumulates history; it is the only droppable kind and treating it
 * as durable in the DOM would misrepresent the stream." A dropped `progress` is
 * therefore not a gap, and a rendered one would be a claim the vocabulary does
 * not make.
 */
export function groupRows(items: readonly TranscriptItem[]): readonly TranscriptRow[] {
  const rows: TranscriptRow[] = [];
  const chips = new Map<string, ChipDraft>();
  const asks = new Map<string, AskDraft>();
  /** The `ask_user` call currently suspending this run, if any. See below. */
  const openAsk = new Map<string, AskDraft>();
  let textRun: TranscriptItem[] | null = null;
  let thoughtRun: TranscriptItem[] | null = null;

  const closeRuns = (): void => {
    if (textRun !== null) {
      const first = textRun[0];
      if (first !== undefined) rows.push({ row: "text", key: first.eventId, items: textRun });
      textRun = null;
    }
    if (thoughtRun !== null) {
      const first = thoughtRun[0];
      if (first !== undefined)
        rows.push({ row: "thought", key: first.eventId, items: thoughtRun });
      thoughtRun = null;
    }
  };

  for (const event of items) {
    if (event.kind !== "text_delta" && textRun !== null) {
      const first = textRun[0];
      if (first !== undefined) rows.push({ row: "text", key: first.eventId, items: textRun });
      textRun = null;
    }
    if (event.kind !== "thought" && thoughtRun !== null) {
      const first = thoughtRun[0];
      if (first !== undefined) rows.push({ row: "thought", key: first.eventId, items: thoughtRun });
      thoughtRun = null;
    }

    switch (event.kind) {
      case "text_delta": {
        if (textRun === null) textRun = [event];
        else textRun.push(event);
        break;
      }
      case "thought": {
        if (thoughtRun === null) thoughtRun = [event];
        else thoughtRun.push(event);
        break;
      }
      case "tool_call": {
        const call = readToolCall(event.payload);
        const toolName = call?.name ?? "";
        if (toolName === ASK_USER_TOOL) {
          const draft: AskDraft = {
            index: rows.length,
            source: "tool_result",
            question: null,
            call: event,
            result: null,
            answer: null,
          };
          rows.push({
            row: "ask",
            key: event.eventId,
            source: draft.source,
            question: null,
            call: event,
            result: null,
            answer: null,
            status: "running",
          });
          if (event.toolCallId !== null) asks.set(event.toolCallId, draft);
          openAsk.set(event.runId, draft);
          break;
        }
        const draft: ChipDraft = {
          index: rows.length,
          toolName,
          call: event,
          result: null,
          images: [],
        };
        rows.push({
          row: "chip",
          key: event.eventId,
          toolName,
          call: event,
          result: null,
          images: [],
          status: "running",
        });
        if (event.toolCallId !== null) chips.set(event.toolCallId, draft);
        break;
      }
      case "tool_result": {
        const ask = event.toolCallId === null ? undefined : asks.get(event.toolCallId);
        if (ask !== undefined) {
          ask.result = event;
          openAsk.delete(event.runId);
          rows[ask.index] = askRow(ask);
          break;
        }
        const chip = event.toolCallId === null ? undefined : chips.get(event.toolCallId);
        if (chip === undefined) {
          // A result whose call is not in this surface. It is a real event with
          // a real identity, so it renders as its own chip with the call absent
          // rather than being dropped: a page boundary in the middle of a call
          // is a fact about the transcript, not a reason to hide the outcome.
          const toolName = readToolResult(event.payload)?.toolName ?? "";
          rows.push({
            row: "chip",
            key: event.eventId,
            toolName,
            call: event,
            result: event,
            images: [],
            status: chipStatus(event),
          });
          break;
        }
        chip.result = event;
        rows[chip.index] = chipRow(chip);
        break;
      }
      case "image": {
        const chip = event.toolCallId === null ? undefined : chips.get(event.toolCallId);
        if (chip === undefined) {
          rows.push({ row: "image", key: event.eventId, item: event });
          break;
        }
        chip.images.push(event);
        rows[chip.index] = chipRow(chip);
        break;
      }
      case "question": {
        // §7.3: `question` is synthetic and live-only, minted around the
        // `py.ask_user` suspension. The suspension blocks the turn, so at most
        // one `ask_user` call is open per run — which is what makes attaching
        // the question to that call sound. With no open call (a resync that
        // dropped the `tool_call`, or a question raised outside a tool) it
        // renders as a widget of its own rather than being discarded.
        const open = openAsk.get(event.runId);
        if (open !== undefined) {
          open.source = "question";
          open.question = event;
          rows[open.index] = askRow(open);
          break;
        }
        const draft: AskDraft = {
          index: rows.length,
          source: "question",
          question: event,
          call: null,
          result: null,
          answer: null,
        };
        rows.push(askRow(draft));
        openAsk.set(event.runId, draft);
        break;
      }
      case "answer": {
        const open = openAsk.get(event.runId);
        if (open !== undefined) {
          open.answer = event;
          rows[open.index] = askRow(open);
          break;
        }
        // §7.3: "`answer` → the recorded answer". With its question dropped by a
        // resync there is still a recorded answer to show, so it renders as a
        // widget carrying the answer and an absent question — not as an unknown
        // kind, which would be a lie about the vocabulary.
        rows.push(
          askRow({
            index: rows.length,
            source: "question",
            question: null,
            call: null,
            result: null,
            answer: event,
          }),
        );
        break;
      }
      case "audit": {
        rows.push({ row: "audit", key: event.eventId, item: event });
        break;
      }
      case "terminal": {
        rows.push({ row: "terminal", key: event.eventId, item: event });
        break;
      }
      case "progress": {
        // No row, by §7.3. See the function docstring.
        break;
      }
      case null:
      default: {
        rows.push({ row: "unknown", key: event.eventId, item: event });
        break;
      }
    }
  }
  closeRuns();
  return rows;
}

function chipRow(draft: ChipDraft): TranscriptRow {
  return {
    row: "chip",
    key: draft.call.eventId,
    toolName: draft.toolName,
    call: draft.call,
    result: draft.result,
    images: [...draft.images],
    status: chipStatus(draft.result),
  };
}

function askRow(draft: AskDraft): TranscriptRow {
  const anchor = draft.call ?? draft.question ?? draft.answer;
  return {
    row: "ask",
    key: anchor === null ? `ask:${String(draft.index)}` : anchor.eventId,
    source: draft.source,
    question: draft.question,
    call: draft.call,
    result: draft.result,
    answer: draft.answer,
    status: draft.call === null ? "running" : chipStatus(draft.result),
  };
}

// ---------------------------------------------------------------------------
// §8 — the panel's rows, seam and named absences included
// ---------------------------------------------------------------------------

/**
 * The kinds a reopened transcript **cannot** contain, each rendered as a named
 * absence rather than as nothing (§8).
 *
 * `user_prompt` — normalization omits prompts by design, so the transcript shows
 * the agent's side and says so once, in place.
 * `terminal` — pump-minted and live-only, so a reopened transcript shows no
 * terminal band and says so rather than implying the run is still open.
 *
 * `question` / `answer` are absent too, but they have a *rendering*: §7.3 has the
 * reopened widget rebuilt from the `ask_user` call and result, marked
 * `data-widget-source="tool_result"`, so the widget itself carries the
 * statement and a third absence row would repeat it. `progress` is absent and
 * that is the correct rendering anyway (§7.3), so it is not announced as a loss.
 * `image` bytes are absent per-image and the placeholder says so in place.
 */
export const HISTORICAL_ABSENCES = ["user_prompt", "terminal"] as const;
export type HistoricalAbsence = (typeof HISTORICAL_ABSENCES)[number];

/** §7.4's closed vocabulary on the Stream header. */
export const STREAM_STATES = [
  "live",
  "reconnecting",
  "resyncing",
  "historical",
  "detached",
] as const;
export type StreamState = (typeof STREAM_STATES)[number];

/**
 * What a `4409 resync_required` cost this transcript, as far as the client can
 * honestly tell.
 *
 * `pending` — the socket has not resumed yet.
 * `contiguous` — the replay began exactly at the event after the cursor, so
 *   nothing between them was lost. The break still renders: the socket did drop,
 *   and a reader deserves to know the panel stopped receiving for a while.
 * `gap` — the replay resumed past the cursor: events were dropped, and they are
 *   **not** recoverable. §2.7 is explicit that history never closes a live gap —
 *   the two identity namespaces do not compare — so the break is labelled and
 *   left as a break.
 * `unknown` — the socket resumed but nothing arrived for the cursor's run, so
 *   contiguity cannot be decided. Not reported as either of the other two.
 */
export const RESYNC_OUTCOMES = ["pending", "contiguous", "gap", "unknown"] as const;
export type ResyncOutcome = (typeof RESYNC_OUTCOMES)[number];

export interface ResyncBreak {
  readonly key: string;
  readonly outcome: ResyncOutcome;
  /** The last identity seen before the socket dropped, or `null` if none was. */
  readonly after: { readonly run_id: string; readonly seq: number } | null;
}

export type PanelRow =
  | TranscriptRow
  | { readonly row: "absence"; readonly key: string; readonly absence: HistoricalAbsence }
  | { readonly row: "seam"; readonly key: string }
  | { readonly row: "resync"; readonly key: string; readonly resync: ResyncBreak };

/**
 * The historical **prefix**: the omitted-prompts note, the rows, the
 * no-terminal-band note. Empty history contributes no rows at all — a project
 * with nothing to reopen should not be told what it is missing.
 */
export function historicalRows(items: readonly TranscriptItem[]): readonly PanelRow[] {
  if (items.length === 0) return [];
  return [
    { row: "absence", key: "absence:user_prompt", absence: "user_prompt" },
    ...groupRows(items),
    { row: "absence", key: "absence:terminal", absence: "terminal" },
  ];
}

/** One entry of the live suffix: an event, or the labelled break of a resync. */
export type LiveEntry =
  | { readonly entry: "event"; readonly item: TranscriptItem }
  | { readonly entry: "break"; readonly resync: ResyncBreak };

/**
 * The live **suffix**, with each resync break rendered in place.
 *
 * Grouping never spans a break: a paragraph that flowed across a labelled gap
 * would be the silent join §8 forbids.
 */
export function liveRows(entries: readonly LiveEntry[]): readonly PanelRow[] {
  const rows: PanelRow[] = [];
  let batch: TranscriptItem[] = [];
  const flush = (): void => {
    if (batch.length === 0) return;
    rows.push(...groupRows(batch));
    batch = [];
  };
  for (const entry of entries) {
    if (entry.entry === "break") {
      flush();
      rows.push({ row: "resync", key: entry.resync.key, resync: entry.resync });
      continue;
    }
    batch.push(entry.item);
  }
  flush();
  return rows;
}

/**
 * The whole transcript: history's prefix, a **visible seam**, the live suffix.
 *
 * The seam appears only when there is something on both sides of it. A seam over
 * an empty live stream would announce a boundary that has not been crossed.
 */
export function panelRows(
  history: readonly TranscriptItem[],
  live: readonly LiveEntry[],
): readonly PanelRow[] {
  const before = historicalRows(history);
  const after = liveRows(live);
  if (before.length === 0 || after.length === 0) return [...before, ...after];
  return [...before, { row: "seam", key: "seam" }, ...after];
}

/**
 * Run ids that have produced a live `terminal` row in this transcript.
 *
 * Sidecar death never mints one (live-only; the run is gone). `ask_user`
 * widgets whose run is not in this set go `abandoned` once
 * `data-runtime-fault` is set — derived from the fault + the rows, not a
 * sixth event kind (§15.10).
 */
export function runsWithTerminal(rows: readonly PanelRow[]): ReadonlySet<string> {
  const ids = new Set<string>();
  for (const row of rows) {
    if (row.row === "terminal") ids.add(row.item.runId);
  }
  return ids;
}
