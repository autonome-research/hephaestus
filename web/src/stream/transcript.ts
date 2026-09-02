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
//
// REPEAT GROUPS (§7.2 (a), amended 2026-09-01) obey the same discipline one step
// further down: consecutive chips of one tool whose results are byte-identical
// after canonical-JSON serialization render as ONE row carrying `×N`, and every
// member's event id and tool-call id stays in the DOM on that row. The decision
// is here rather than in `ToolChip` because §7.2 (e) says so and because a chip
// cannot see its neighbours — a chip that could would be reading the transcript.

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

/** One call of a §7.2 (a) repeat group: the call event and its result event. */
export interface ChipMember {
  readonly call: TranscriptItem;
  readonly result: TranscriptItem | null;
}

export interface TextRow {
  readonly row: "text";
  readonly key: string;
  readonly items: readonly TranscriptItem[];
}

export interface ChipRow {
  readonly row: "chip";
  readonly key: string;
  readonly toolName: string;
  readonly call: TranscriptItem;
  readonly result: TranscriptItem | null;
  readonly images: readonly TranscriptItem[];
  readonly status: ChipStatus;
  /**
   * §7.2 (a): every member of this repeat group, in render order, the first
   * one included — `call` and `result` above are that first member's.
   *
   * Present **only** when the group has two or more members: "N=1 draws no
   * count", so a lone chip carries no `repeat` and renders exactly as it
   * did before the amendment.
   */
  readonly repeat?: readonly ChipMember[];
}

/** One (chip-or-repeat-group, text-row) pair of a §7.2 C4 cycle group. */
export interface CyclePair {
  readonly chip: ChipRow;
  readonly text: TextRow;
}

export type TranscriptRow =
  | TextRow
  | { readonly row: "thought"; readonly key: string; readonly items: readonly TranscriptItem[] }
  | ChipRow
  | {
      /**
       * §7.2 (amended 2026-09-02, C4): a cycle group — three or more
       * consecutive (chip-or-repeat-group, text-row) pairs, one tool, all
       * `ok`, results byte-identical after canonical-JSON serialization. The
       * first pair renders in full; each subsequent pair renders as one
       * compact line, its text row and Detail folded behind the first pair's
       * disclosure. C5: no event id or tool-call id leaves the DOM — the
       * text is relocated, never elided.
       */
      readonly row: "cycle";
      readonly key: string;
      readonly toolName: string;
      readonly pairs: readonly CyclePair[];
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
  return coalesceCycles(coalesceRepeats(rows));
}

// ---------------------------------------------------------------------------
// §7.2 (a) — repeat groups
// ---------------------------------------------------------------------------

/**
 * A value serialized so that two equal documents produce equal strings.
 *
 * §7.2 (a) groups on results that are "byte-identical after canonical-JSON
 * serialization", which is a statement about the DOCUMENT and not about the
 * server's whitespace or key order. Objects therefore serialize with their keys
 * sorted; everything else is `JSON.stringify`'s own canonical form.
 */
export function canonicalJson(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value) ?? "null";
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  const record = value as Readonly<Record<string, unknown>>;
  const keys = Object.keys(record).sort();
  return `{${keys.map((key) => `${JSON.stringify(key)}:${canonicalJson(record[key])}`).join(",")}}`;
}

/**
 * The string two chips must share to coalesce, or `null` if this chip may not.
 *
 * §7.2 (a)'s negative half, in one place: a chip whose status is anything but
 * `ok` never joins a group — "two failed calls never coalesce, even when
 * identical", because a repeated failure is the signal this column exists to
 * carry. A chip with no result cannot be `ok` and is excluded by the same test.
 *
 * A chip carrying inline images is excluded too, and that is this module's own
 * reading rather than a clause: an `image` event has its own identity, a
 * coalesced row renders ONE document, and folding two image-bearing calls into
 * one row would either drop an event id or render bytes the row does not claim.
 * Rendering both members separately loses nothing, so that is what happens.
 *
 * An `ok` result whose text is not a JSON object still coalesces, on the raw
 * text: it has no document to canonicalize, so byte-identity of what the chip
 * actually renders is the honest test, and the `unparsed` refusal renders once
 * with its cause exactly as it does on a lone chip.
 */
function repeatSignature(row: TranscriptRow): string | null {
  if (row.row !== "chip") return null;
  if (row.status !== "ok") return null;
  if (row.images.length > 0) return null;
  if (row.result === null) return null;
  const payload = readToolResult(row.result.payload);
  if (payload === null) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(payload.text) as unknown;
  } catch {
    return `${row.toolName} raw ${payload.text}`;
  }
  return `${row.toolName} doc ${canonicalJson(parsed)}`;
}

/**
 * §7.2 (a): fold each maximal run of ≥2 identical successful chips into one row.
 *
 * A **rendering** operation over already-normalized rows. It computes nothing,
 * merges no payloads and never produces a document no server sent (§1): the one
 * document the row renders is the first member's, and the members are
 * byte-identical by the group's own definition.
 *
 * "Adjacent in render order with no item of any other kind between them" is
 * enforced by running over the row list: a `text_delta` paragraph, a thought, an
 * image, an ask widget, an audit line or a terminal band between two calls is a
 * row between them and breaks the run. The §8 seam, the historical absences and
 * a resync break are added around this function's output by `panelRows`, so a
 * group can never span one of those either.
 */
export function coalesceRepeats(rows: readonly TranscriptRow[]): readonly TranscriptRow[] {
  const out: TranscriptRow[] = [];
  let index = 0;
  while (index < rows.length) {
    const row = rows[index];
    if (row === undefined) break;
    const signature = repeatSignature(row);
    if (signature === null || row.row !== "chip") {
      out.push(row);
      index += 1;
      continue;
    }
    const members: ChipMember[] = [{ call: row.call, result: row.result }];
    let next = index + 1;
    while (next < rows.length) {
      const candidate = rows[next];
      if (candidate === undefined || candidate.row !== "chip") break;
      if (repeatSignature(candidate) !== signature) break;
      members.push({ call: candidate.call, result: candidate.result });
      next += 1;
    }
    // "N=1 draws no count": a run of one is the row it already was.
    out.push(members.length < 2 ? row : { ...row, repeat: members });
    index = next;
  }
  return out;
}

/**
 * §7.2 (C4): "a cycle group coalesces from the second repetition of the pair" —
 * the threshold is three pairs, because two occurrences are not yet a cycle.
 */
export const CYCLE_MIN_PAIRS = 3;

/**
 * §7.2 (C4): fold each maximal run of ≥3 consecutive (chip-or-repeat-group,
 * text-row) pairs — one tool, all `ok`, results byte-identical after
 * canonical-JSON serialization — into one `cycle` row.
 *
 * The chip half of a pair reuses `repeatSignature` verbatim, so the negative
 * half is (a)'s, stated the same four ways: no group forms if any chip
 * member's status is not `ok` (two failed calls never coalesce, even when
 * identical), if any result document differs in a byte, if the interleaved
 * text rows are joined by any item of a third kind (`thought`, `image`,
 * `question`, `answer`, `audit`, `terminal` — each is a row of its own kind
 * here and breaks the chip/text alternation), or across a seam — the §8 seam,
 * a resync break and the §7.3 presentation rows are all appended around this
 * function's output by `liveRows`/`panelRows`, so a group can never span one.
 *
 * The text rows are NOT required to be identical: the cycle is defined by its
 * chip members (C4 conditions name the chip member only), and the narration
 * between repeats is exactly the content C5 relocates behind the first pair's
 * disclosure rather than eliding.
 *
 * Like `coalesceRepeats`, a rendering operation: it computes nothing, merges
 * no payloads, and never produces a document no server sent (§1).
 */
export function coalesceCycles(rows: readonly TranscriptRow[]): readonly TranscriptRow[] {
  const out: TranscriptRow[] = [];
  let index = 0;
  while (index < rows.length) {
    const pairs: CyclePair[] = [];
    let signature: string | null = null;
    let next = index;
    while (next + 1 < rows.length) {
      const chip = rows[next];
      const text = rows[next + 1];
      if (chip === undefined || chip.row !== "chip") break;
      if (text === undefined || text.row !== "text") break;
      const candidate = repeatSignature(chip);
      if (candidate === null) break;
      if (signature === null) signature = candidate;
      else if (candidate !== signature) break;
      pairs.push({ chip, text });
      next += 2;
    }
    const first = pairs[0];
    if (first !== undefined && pairs.length >= CYCLE_MIN_PAIRS) {
      out.push({ row: "cycle", key: first.chip.key, toolName: first.chip.toolName, pairs });
      index = next;
      continue;
    }
    const row = rows[index];
    if (row === undefined) break;
    out.push(row);
    index += 1;
  }
  return out;
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

/**
 * §7.3 (amended 2026-09-02, §0.2c) — the presentation-row category, closed at
 * exactly two members.
 *
 * A presentation row is a transcript row the client mints from state it
 * already holds — never from computing over payloads, never from a fact the
 * server did not send this tab. It carries NO `data-event-id`, appears in no
 * `data-event-ids` list, and is excluded BY NAME from every event-id equality
 * testable: the archive matcher skips exactly `local-prompt` and `run-start`;
 * any other id-less `data-row` element is a mismatch, and a presentation row
 * that carries an event id is a build error. It never enters history and never
 * crosses the wire, and it states its own nature on its visible face (a
 * marker in `.code` at `--ink-muted` plus an accessible equivalent), with
 * `title` carrying only the long form.
 */
export const PRESENTATION_ROWS = ["local-prompt", "run-start"] as const;
export type PresentationRowName = (typeof PRESENTATION_ROWS)[number];

export type PanelRow =
  | TranscriptRow
  | { readonly row: "absence"; readonly key: string; readonly absence: HistoricalAbsence }
  | { readonly row: "seam"; readonly key: string }
  | { readonly row: "resync"; readonly key: string; readonly resync: ResyncBreak }
  /** C2: the local prompt echo — the sent text verbatim, originating tab only. */
  | { readonly row: "local-prompt"; readonly key: string; readonly text: string }
  /** C21: the run-start boundary — a rule line carrying the run id, derived. */
  | { readonly row: "run-start"; readonly key: string; readonly runId: string };

/**
 * The historical **prefix**: the omitted-prompts note, the rows, the
 * no-terminal-band note. Empty history contributes no rows at all — a project
 * with nothing to reopen should not be told what it is missing.
 *
 * §8's C3: NO presentation row renders in the history prefix, ever. History
 * has no echoes (the §2.8 ordinal namespace records no prompts) and no
 * run-start rows (it has no runs to mark), so both notices stay true on every
 * reopen — this function is where that is enforced, by construction: its
 * input is events only, and it mints nothing but the two named absences.
 */
export function historicalRows(items: readonly TranscriptItem[]): readonly PanelRow[] {
  if (items.length === 0) return [];
  return [
    { row: "absence", key: "absence:user_prompt", absence: "user_prompt" },
    ...groupRows(items),
    { row: "absence", key: "absence:terminal", absence: "terminal" },
  ];
}

/**
 * One entry of the live suffix: an event, the labelled break of a resync, or
 * the C2 local-prompt echo the originating tab appended on Send. The echo is
 * an *entry* rather than a row so that it holds its place in arrival order —
 * "at the live suffix's tail" is a fact about when Send happened relative to
 * the frames around it.
 */
export type LiveEntry =
  | { readonly entry: "event"; readonly item: TranscriptItem }
  | { readonly entry: "break"; readonly resync: ResyncBreak }
  | { readonly entry: "echo"; readonly key: string; readonly text: string };

/**
 * The live **suffix**, with each resync break rendered in place.
 *
 * Grouping never spans a break: a paragraph that flowed across a labelled gap
 * would be the silent join §8 forbids.
 *
 * §7.3's C21 lives here: a run-start boundary row is minted when a live
 * frame's `run_id` differs from the run id of the previous rendered live row —
 * derived purely from entries this tab already holds, rendered before that
 * frame's row. THE BASE CASE: with no previous rendered live row (the §8 seam,
 * a fresh attach, a resync refill — `prevRunId === null` below) no boundary is
 * minted by comparison, because there is nothing held to compare and §8's C3
 * forbids reaching across a seam for one. The one licensed exception: the C2
 * echo — itself a held fact, the Send this tab performed — licenses exactly
 * one run-start row for the first frame that follows it. The license survives
 * the seams (the §8 seam and a resync break terminate *comparison*, not the
 * held fact of the Send), and it is consumed by the first frame whether or
 * not a boundary mints, so it can never license a second. The honest
 * consequence: an observer that attaches mid-run renders the run in progress
 * with no top boundary, and gains boundaries from the next run change onward.
 * None is minted within a run; none is reconstructed from history.
 */
export function liveRows(entries: readonly LiveEntry[]): readonly PanelRow[] {
  const rows: PanelRow[] = [];
  let batch: TranscriptItem[] = [];
  /** Run id of the previous rendered live *frame* row; `null` past a seam. */
  let prevRunId: string | null = null;
  /** A C2 echo stands with no frame after it yet (C21's licensed exception). */
  let echoLicense = false;
  const flush = (): void => {
    if (batch.length === 0) return;
    rows.push(...groupRows(batch));
    batch = [];
  };
  for (const entry of entries) {
    if (entry.entry === "break") {
      flush();
      rows.push({ row: "resync", key: entry.resync.key, resync: entry.resync });
      // C21: a resync seam is a derivation boundary exactly as the §8 seam is.
      // Run ids are never compared across a gap in which boundary events may
      // have been lost; derivation restarts from the frames after it.
      prevRunId = null;
      continue;
    }
    if (entry.entry === "echo") {
      flush();
      rows.push({ row: "local-prompt", key: entry.key, text: entry.text });
      echoLicense = true;
      continue;
    }
    const item = entry.item;
    // Comparison when there is a previous rendered live row; the echo license
    // alone in the base case. Never within a run: same-run frames after an
    // echo consume the license without minting.
    const boundary = prevRunId !== null ? item.runId !== prevRunId : echoLicense;
    if (boundary && item.runId !== prevRunId) {
      flush();
      rows.push({ row: "run-start", key: `run-start:${item.eventId}`, runId: item.runId });
    }
    prevRunId = item.runId;
    echoLicense = false;
    batch.push(item);
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
