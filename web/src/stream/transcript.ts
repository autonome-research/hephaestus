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
import type { HistoryUserPrompt, TurnOutcome, TurnOutcomeState } from "../api/sessions";

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
  /**
   * §2.8(1) (amended 2026-09-03): the 0-based ordinal of the user message whose
   * turn recorded this event, on a HISTORY PAGE only.
   *
   * `null` carries two different facts and the difference does not matter to
   * this module: an event recorded before the session's first user message (the
   * spec's prologue), and a page served by a sidecar older than the amendment.
   * Both mean "this event names no turn", and `historicalRows` decides which
   * segmentation rule to run from the PROMPTS, never from this field alone —
   * so a legacy page cannot land every event in a prologue by accident.
   *
   * Always `null` on a live item: §2.8(1) says `turn` is a field of the history
   * page and of nothing else, and it is testable both ways.
   */
  readonly turn: number | null;
}

function item(
  surface: Surface,
  eventId: string,
  runId: string,
  seq: number,
  sessionId: string | null,
  turn: number | null,
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
    turn,
  };
}

/**
 * Read an additive integer ordinal off a wire value.
 *
 * `turn` is additive on both the event and the prompt (§2.8(1), §2.8(2)): a
 * sidecar older than the amendment sends neither, and both are optional on the
 * wire types. Anything that is not a non-negative integer — absent, `null`, a
 * float, a string — reads as absent, so a page that half-carries the field is
 * treated as a page that does not carry it, which is what keeps §8(g)'s two
 * segmentation rules from mixing inside one page.
 */
function readOrdinal(value: unknown): number | null {
  if (typeof value !== "number") return null;
  if (!Number.isInteger(value) || value < 0) return null;
  return value;
}

/** A live socket frame → an item in the `(run_id, seq)` namespace. */
export function liveItem(frame: EventFrame): TranscriptItem {
  return item(
    "live",
    liveEventId(frame.run_id, frame.seq),
    frame.run_id,
    frame.seq,
    frame.session_id,
    // §2.8(1): never on a live frame, even if a sidecar ever sent one. The
    // sidecar's own trap is the shared `wireEvent`; this is the client half of
    // the same rule, and it makes "no turn on the live socket" true here
    // regardless of what arrives.
    null,
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
export function historicalItem(
  frame: HistoryEventFrame & { readonly turn?: number | null },
  sessionId: string,
): TranscriptItem {
  return item(
    "historical",
    historicalEventId(sessionId, frame.seq),
    frame.run_id,
    frame.seq,
    sessionId,
    readOrdinal(frame.turn),
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
 *
 * FIXED 2026-09-03 — the drop is now genuine. `progress` used to produce no row
 * of its own while still *closing* an open `text_delta` or `thought` run, so a
 * tick between two deltas split one paragraph into two rows. That is a gap: the
 * seam between the halves is visible, it is caused by an event the docstring
 * above promises is droppable, and the same content arrives as one paragraph on
 * the reopened surface (history carries no `progress`) — the two surfaces
 * disagreed about the same words. The event is therefore skipped before the
 * run-closing guards, which is the only place the promise can be kept.
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
    // Dropped BEFORE the run-closing guards: see the docstring. A `progress`
    // frame is not a change of kind, it is the absence of one.
    if (event.kind === "progress") continue;
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
 * The kinds a reopened transcript used to announce as named absences (§8).
 *
 * AMENDED 2026-09-03 — both notices left the well. Operator prompts restore
 * from history's additive `user_prompts` field; a finished turn looks finished
 * (last tool chip or assistant markdown) without a "reopened transcript" hedge.
 * The type stays so a stale fixture can still name a key; the panel no longer
 * mints either row.
 *
 * `question` / `answer` have a *rendering*: §7.3 rebuilds the widget from the
 * `ask_user` call and result. `progress` is absent and that is the correct
 * rendering. `image` bytes are absent per-image and the placeholder says so.
 */
export const HISTORICAL_ABSENCES = ["user_prompt", "terminal"] as const;
export type HistoricalAbsence = (typeof HISTORICAL_ABSENCES)[number];

export type { HistoryUserPrompt };

// ---------------------------------------------------------------------------
// §2.8 (amended 2026-09-03) — the turn record
// ---------------------------------------------------------------------------

/**
 * §2.8(2)'s outcome, re-exported from the wire types so a renderer importing
 * from the transcript model does not need two imports for one row.
 *
 * ABSENCE MEANS COMPLETED, NEVER UNKNOWN. Nothing here is ever derived: a short
 * reply, a missing terminal, or a run that stopped sending is not evidence of
 * cancellation, and this module mints no outcome from any of them.
 */
export type { TurnOutcome, TurnOutcomeState };

/**
 * The closed set, as a record rather than a list, so the compiler checks it
 * BOTH ways against `TurnOutcomeState`: a state added to the wire vocabulary
 * and not here fails to compile, and so does one here that the wire does not
 * name. `api/sessions.ts` keeps the runtime list; this module stays free of a
 * runtime import from the API layer, which is what makes it pure.
 */
const KNOWN_OUTCOME_STATES: Readonly<Record<TurnOutcomeState, true>> = {
  cancelled: true,
  error: true,
  interrupted: true,
};

/**
 * One recorded operator turn as §2.8(2) publishes it, read leniently.
 *
 * `HistoryUserPrompt` (`api/sessions.ts`, still the shipped `{seq, text}`) is
 * assignable to this, which is the point: the loader keeps its declared type
 * and this module reads the additive fields off the same objects. Every field
 * past `seq` is optional here **because the running server may or may not send
 * it**, and a client that required them would refuse to render the page it is
 * pointed at today.
 *
 * - `turn` — §2.8(2)'s IDENTITY: 0-based, unique, strictly increasing.
 * - `seq` — unchanged meaning: the ordinal of this turn's first event.
 *   EXPLICITLY NOT UNIQUE (two prompts around a zero-event turn share one), so
 *   it is a segmentation boundary and never an identity.
 * - `text` — the operator's typed sentence and nothing else; `null` when the
 *   record cannot recover it. NOT recovered by stripping a heading (§2.8(3)).
 * - `envelope` — §7A.3's workspace-context block verbatim, when one was sent.
 * - `outcome` — absent for a completed turn.
 */
export interface RestoredPrompt {
  readonly turn?: number;
  readonly seq: number;
  readonly text: string | null;
  readonly envelope?: string | null;
  /**
   * Deliberately LOOSER than `TurnOutcome`: `state` is read as a plain string
   * and validated by `readOutcome`. The wire's vocabulary is the server's, this
   * build's copy of it is a snapshot, and a page carrying a state this build
   * has never heard of must still render its events rather than fail to type.
   */
  readonly outcome?: { readonly state: string; readonly message?: string } | null;
  /** §2.8(3): read loosely for the same reason as `outcome`; only the literal
   *  `"agent"` changes the row's speaker. */
  readonly origin?: string;
}

/**
 * Read a turn outcome off a wire value, or `null`.
 *
 * Structural rather than cast: `outcome` is additive, its `state` is a closed
 * set, and a state this build has never heard of is dropped rather than
 * rendered — an unrecognized word would put an unlabelled row under a prompt.
 */
function readOutcome(value: unknown): TurnOutcome | null {
  if (typeof value !== "object" || value === null) return null;
  const state: unknown = (value as { readonly state?: unknown }).state;
  if (typeof state !== "string") return null;
  if (!Object.hasOwn(KNOWN_OUTCOME_STATES, state)) return null;
  const known = state as TurnOutcomeState;
  const message: unknown = (value as { readonly message?: unknown }).message;
  return typeof message === "string" ? { state: known, message } : { state: known };
}

/**
 * §7A.5 (amended 2026-09-03): what became of one echoed prompt.
 *
 * `sent` — the POST was accepted; the default, so the attribute is
 *   unconditionally present on the rendered row.
 * `unknown` — the POST was lost. The turn MAY have started; the stream is the
 *   authority.
 * `refused` — the server answered with a named refusal. The turn definitively
 *   did NOT start and the text is still sendable.
 *
 * `refused` and `unknown` stay two words because they are two different facts
 * with two different next moves.
 *
 * `live.ts` holds the SENDER's copy of this set (it is the module that decides
 * an echo's fate). The two cannot drift silently: `liveRows` assigns one to the
 * other, so a member added on either side and not the other fails to compile.
 */
export const ECHO_STATES = ["sent", "unknown", "refused"] as const;
export type EchoState = (typeof ECHO_STATES)[number];

/**
 * §7.4 (amended 2026-09-03): which boundary the seam is.
 *
 * `end` — the live suffix begins at the start of a run this tab held whole.
 * `mid-run` — this tab attached while a run was already in progress, so output
 *   of that run exists that it never received. Saying "the transcript ends
 *   here" over that is the dishonest half the amendment removes.
 */
export const SEAM_KINDS = ["end", "mid-run"] as const;
export type SeamKind = (typeof SEAM_KINDS)[number];

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
 * testable, and a presentation row that carries an event id is a build error.
 *
 * The CATEGORY is these two. The archive matcher's SKIP LIST is wider and is
 * not the same list (§7.3, amended 2026-09-03): `local-prompt`, `run-start`,
 * `absence`, `seam`, `resync`, `turn-outcome` — the honesty rows and the turn
 * label carry no id either. The skip stays BY NAME rather than by "has no id"
 * so a real event row that dropped its id still fails. It never enters history and never
 * crosses the wire, and it states its own nature on its visible face (a
 * marker in `.code` at `--ink-muted` plus an accessible equivalent), with
 * `title` carrying only the long form.
 */
export const PRESENTATION_ROWS = ["local-prompt", "run-start"] as const;
export type PresentationRowName = (typeof PRESENTATION_ROWS)[number];

export type PanelRow =
  | TranscriptRow
  | { readonly row: "absence"; readonly key: string; readonly absence: HistoricalAbsence }
  | {
      readonly row: "seam";
      readonly key: string;
      /** §7.4: which boundary this is, decided from held frames alone. */
      readonly kind: SeamKind;
    }
  | { readonly row: "resync"; readonly key: string; readonly resync: ResyncBreak }
  /** C2: the local prompt echo — the sent text verbatim, originating tab only. */
  | {
      readonly row: "local-prompt";
      readonly key: string;
      readonly text: string;
      /**
       * §7A.5: this echo's fate, when the sender learned one. Absent means the
       * sender recorded nothing, and the renderer's default is `sent` — the
       * attribute is unconditional in the DOM, the field is not, so an echo
       * that never learned anything is not asserted to have succeeded here.
       */
      readonly state?: EchoState;
      /**
       * The server's own reason word, VERBATIM. Never translated and never
       * collapsed into a neighbour: a reason this client has never heard of
       * still renders, correctly, as itself.
       */
      readonly refusedReason?: string | null;
    }
  /**
   * A recorded operator turn restored from history (§2.8(2), §7.3).
   *
   * IDENTITY IS THE TURN (§8(i), amended 2026-09-03):
   * `<session_id>@turn:<turn>`. The struck `<session_id>@prompt:<seq>` was not
   * unique — `seq` is the NEXT event's ordinal, and two prompts around a
   * zero-event turn carry the same one, so two rows shared one id.
   */
  | {
      readonly row: "user-prompt";
      readonly key: string;
      /** §2.8(2)'s ordinal: recorded when the page carries one, else counted. */
      readonly turn: number;
      /**
       * The operator's own sentence. `""` when the record could not recover it
       * — see `textUnrecoverable`, which is the field that says so. Never the
       * envelope: §7.3(b) forbids rendering the server's projection as the
       * operator's words.
       */
      readonly text: string;
      /**
       * `true` when the page carried `text: null` (§2.8(3)'s honest answer for
       * a legacy record whose sentence cannot be separated from the envelope).
       * The renderer falls back rather than drawing a blank row; it is a named
       * field because an empty string is not a sentence anyone typed.
       */
      readonly textUnrecoverable: boolean;
      /**
       * §2.8(3), amended 2026-09-03: `"agent"` when the sentence is the sidecar's
       * own transient-retry continuation, so the renderer names the speaker.
       * Absent means the operator.
       */
      readonly origin?: "agent";
      /**
       * §7A.3's workspace-context block, when one was sent with this turn, for
       * the closed-by-default disclosure of §7.3(b). Preformatted when
       * rendered, NEVER markdown: it opens with a `#` heading, and the
       * transcript's renderer would mint an `<h1>` inside an operator's row.
       */
      readonly envelope: string | null;
      readonly eventId: string;
    }
  /**
   * §7.3(c): the label under a turn that did not simply finish.
   *
   * Carries NO `data-event-id` by design — it is a projection of the turn
   * record, not an event — which is why §7.3's skip list names it. It renders
   * for no other turn: absence of `outcome` means the turn completed.
   */
  | {
      readonly row: "turn-outcome";
      readonly key: string;
      readonly turn: number;
      readonly outcome: TurnOutcome;
    }
  /** C21: the run-start boundary — a rule line carrying the run id, derived. */
  | { readonly row: "run-start"; readonly key: string; readonly runId: string };

/**
 * One turn's slice of the historical prefix: the record of what was asked, and
 * the events that turn produced.
 *
 * `turn` is `null` for the PROLOGUE — events recorded before the session's
 * first user message (§2.8(1)). It has no prompt row, because there is no
 * prompt: folding those events into turn 0 would print output above the
 * message that did not cause it.
 */
interface TurnSegment {
  readonly turn: number | null;
  readonly prompt: RestoredPrompt | null;
  readonly items: readonly TranscriptItem[];
}

/**
 * §8(f): partition the page by turn, in the record's own ordinals.
 *
 * Used whenever the page carries them, which is the rule §8(g) says to prefer.
 */
function segmentsByTurn(
  items: readonly TranscriptItem[],
  prompts: readonly RestoredPrompt[],
): readonly TurnSegment[] {
  const prologue: TranscriptItem[] = [];
  const buckets = new Map<number, TranscriptItem[]>();
  for (const event of items) {
    if (event.turn === null) {
      prologue.push(event);
      continue;
    }
    const bucket = buckets.get(event.turn);
    if (bucket === undefined) buckets.set(event.turn, [event]);
    else bucket.push(event);
  }
  const recorded = new Map<number, RestoredPrompt>();
  for (const prompt of prompts) {
    const turn = readOrdinal(prompt.turn);
    // First write wins: `turn` is unique by §2.8(2), and a page that broke that
    // is not a reason to render one turn twice.
    if (turn !== null && !recorded.has(turn)) recorded.set(turn, prompt);
  }
  const ordinals = [...new Set([...recorded.keys(), ...buckets.keys()])].sort((a, b) => a - b);
  const segments: TurnSegment[] = [];
  if (prologue.length > 0) segments.push({ turn: null, prompt: null, items: prologue });
  for (const turn of ordinals) {
    // A turn with a prompt and no events is a real state (cancelled before the
    // first token) and emits its prompt row alone. A turn with events and no
    // prompt is a page that lost a record; its events still render, in place.
    segments.push({ turn, prompt: recorded.get(turn) ?? null, items: buckets.get(turn) ?? [] });
  }
  return segments;
}

/**
 * §8(g)'s FALLBACK, for a sidecar older than the amendment: partition by prompt
 * INDEX over `seq` RANGES.
 *
 * A prompt with `seq` S opens a segment holding the events whose ordinal is
 * `>= S` and below the next prompt's `seq`; consecutive prompts sharing a `seq`
 * each open an empty segment but the last. The ordinal is the prompt's INDEX,
 * which is exactly what §2.8(1) says the sidecar counts — so a legacy page
 * renders with the same identities a current page would give it.
 *
 * NEVER `seq` UNIQUENESS. The walk consumes items in order against a moving
 * upper bound, so equal, missing or out-of-order boundaries cost a segment its
 * contents and never lose an event: everything left over lands in the last
 * segment, whose bound is unbounded.
 *
 * Correct for ordinary chats. It cannot express a textless prompt or a
 * zero-event turn — which is why it is the fallback and not the design.
 */
function segmentsByPromptIndex(
  items: readonly TranscriptItem[],
  prompts: readonly RestoredPrompt[],
): readonly TurnSegment[] {
  const segments: TurnSegment[] = [];
  let index = 0;
  const take = (below: number): TranscriptItem[] => {
    const taken: TranscriptItem[] = [];
    for (;;) {
      const next = items[index];
      if (next === undefined || next.seq >= below) return taken;
      taken.push(next);
      index += 1;
    }
  };
  const prologue = take(prompts[0]?.seq ?? Number.POSITIVE_INFINITY);
  if (prologue.length > 0) segments.push({ turn: null, prompt: null, items: prologue });
  prompts.forEach((prompt, ordinal) => {
    segments.push({
      turn: ordinal,
      prompt,
      items: take(prompts[ordinal + 1]?.seq ?? Number.POSITIVE_INFINITY),
    });
  });
  return segments;
}

/**
 * Which of §8(g)'s two rules this page gets — decided ONCE, for the whole page.
 *
 * "The client prefers `turn` whenever the field is present and NEVER MIXES the
 * two rules within one page." Present means: every prompt carries an ordinal,
 * AND the events carry them too (or there are no events). The second half is
 * the guard against a half-upgraded page — prompts stamped, events not — which
 * would otherwise put every event in the prologue and every prompt row after
 * all of them, i.e. the exact defect this function exists to remove.
 *
 * With NO prompts at all the first test is vacuously true, so the answer is
 * decided by the events alone — turn-bearing events segment, turn-less ones do
 * not. That is the intended reading rather than an accident of `every`: with no
 * prompt records the ordinals on the events are the only turn structure the
 * page carries, and ignoring them would fuse two turns' replies for want of a
 * prompt row nobody was going to render anyway.
 */
function prefersTurnOrdinals(
  items: readonly TranscriptItem[],
  prompts: readonly RestoredPrompt[],
): boolean {
  if (!prompts.every((prompt) => readOrdinal(prompt.turn) !== null)) return false;
  return items.length === 0 || items.some((event) => event.turn !== null);
}

/** §8(f)'s emission order for one turn, and the only place it is decided. */
function segmentRows(segment: TurnSegment, sessionId: string): readonly PanelRow[] {
  const rows: PanelRow[] = [];
  const prompt = segment.prompt;
  const turn = segment.turn;
  if (prompt !== null && turn !== null) {
    const text = typeof prompt.text === "string" ? prompt.text : null;
    rows.push({
      row: "user-prompt",
      key: `user-prompt:${String(turn)}`,
      turn,
      text: text ?? "",
      textUnrecoverable: text === null,
      ...(prompt.origin === "agent" ? { origin: "agent" as const } : {}),
      envelope: typeof prompt.envelope === "string" ? prompt.envelope : null,
      eventId: `${sessionId}@turn:${String(turn)}`,
    });
    const outcome = readOutcome(prompt.outcome);
    // ABOVE this turn's replies, per §8(f), and the cost is stated there: on a
    // long cancelled turn the label ends up far from where the output stops.
    // It is above because a truncated answer LOOKS FINISHED, and learning
    // "cancelled" only at the end is learning it too late to read the reply
    // correctly — and because a zero-event turn has nowhere else to put it.
    if (outcome !== null) {
      rows.push({ row: "turn-outcome", key: `turn-outcome:${String(turn)}`, turn, outcome });
    }
  }
  rows.push(...groupRows(segment.items));
  return rows;
}

/**
 * The historical **prefix**: the recorded conversation, one turn at a time.
 *
 * AMENDED 2026-09-03 — SEGMENT FIRST, GROUP SECOND (§8(f)). This function used
 * to group the whole page and then interleave prompt rows between the groups by
 * comparing `seq`. That is why a reopened three-turn chat rendered as four rows
 * with one bubble reading `PONGPINGZEBRA`: `groupRows` runs over a flat item
 * list and cannot see a turn boundary even in principle, so three replies to
 * three different prompts — all `text_delta`, all adjacent — were one paragraph
 * before any interleave could get between them. A grouping function that cannot
 * see a boundary will always cross it. So the boundary is applied first, and
 * `groupRows` runs ONCE PER TURN over a slice that holds one turn's events.
 *
 * Empty history contributes no rows at all. Prompts come back from the additive
 * `user_prompts` field; no named-absence hedge is minted (§8, C24).
 *
 * A page with NO prompt records still segments, when its events carry turn
 * ordinals: the boundary is a fact about the events, and honouring it costs
 * nothing but stops two turns' replies fusing into one paragraph on a page
 * whose prompt records were lost or were never asked for (a tail read of a
 * turn's events alone). Those segments emit no prompt row — there is no prompt
 * to render — and a page carrying neither turns nor prompts falls through to a
 * single unsegmented run, which is exactly today's behaviour.
 *
 * §8's C3 still holds for *presentation* rows: no `local-prompt` echo and no
 * `run-start` boundary is reconstructed here, and no `run_id` is invented for a
 * historical event (§7.3 C21's surviving negative half). A TURN is a record of
 * one thing the operator asked; a RUN is one live execution. This page has the
 * first and does not have the second.
 *
 * `sessionId` names the session these records came from, for §8(i)'s prompt-row
 * identity `<session_id>@turn:<turn>`. It is OPTIONAL and falls back to the
 * first event's own session id, because that is where every rendered page's id
 * comes from today and a caller that does not pass one must still render. THE
 * FALLBACK HAS A HOLE, stated rather than hidden: a page of prompts with NO
 * events — every turn cancelled before its first token, which §2.8(2) makes
 * expressible for the first time — has no event to read a session id off, and
 * its prompt rows would be identified `@turn:0` with an empty session. Passing
 * the id closes it; `user_prompts` carries no session id of its own, so the
 * caller is the only party that knows.
 */
export function historicalRows(
  items: readonly TranscriptItem[],
  prompts: readonly RestoredPrompt[] = [],
  sessionId: string | null = null,
): readonly PanelRow[] {
  if (items.length === 0 && prompts.length === 0) return [];
  const owner = sessionId ?? items[0]?.sessionId ?? "";
  const segments = prefersTurnOrdinals(items, prompts)
    ? segmentsByTurn(items, prompts)
    : segmentsByPromptIndex(items, prompts);
  const rows: PanelRow[] = [];
  for (const segment of segments) rows.push(...segmentRows(segment, owner));
  return rows;
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
  | {
      readonly entry: "echo";
      readonly key: string;
      readonly text: string;
      /**
       * §7A.5: what the sender learned about this echo's POST, when it learned
       * anything. Written by the sender (`live.ts`), read here and carried onto
       * the row unchanged — this module decides nothing about it, because the
       * fate of a POST is not a fact a transcript can derive.
       */
      readonly state?: EchoState;
      /** The server's reason word, verbatim, when the state is `refused`. */
      readonly refusedReason?: string | null;
    };

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
      // §7A.5, C2: the text is carried VERBATIM whatever became of the POST —
      // the words were typed, and a refusal is not a reason to remove them.
      // The fate rides beside them; the license below is unaffected by it,
      // because a refused Send is still a Send this tab performed.
      const echo: PanelRow =
        entry.state === undefined
          ? { row: "local-prompt", key: entry.key, text: entry.text }
          : entry.refusedReason === undefined || entry.refusedReason === null
            ? { row: "local-prompt", key: entry.key, text: entry.text, state: entry.state }
            : {
                row: "local-prompt",
                key: entry.key,
                text: entry.text,
                state: entry.state,
                refusedReason: entry.refusedReason,
              };
      rows.push(echo);
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
 * §7.4 (amended 2026-09-03): which boundary the seam is, from HELD FRAMES ONLY.
 *
 * A live run's `seq` is run-monotonic and starts at 0 (`agent/src/main.ts:509`,
 * `let seq = 0; const next = () => seq++`), so the first live frame this tab
 * received for a run says which case it is in: `seq === 0` and it held the run
 * from the beginning; `seq > 0` and frames of that run exist that it never
 * received. The originating tab's own C2 echo is the same fact from the other
 * side — a Send this tab performed starts the run it is about to watch — and it
 * licenses the unchanged label without looking at any frame.
 *
 * Nothing is compared across the seam, nothing is read from history, and no run
 * start is inferred: a resync break before the first frame is not evidence
 * either way and is skipped. A seam with no live frame under it yet reads
 * `end`, and switches on the first frame's arrival if its `seq > 0`.
 *
 * HONEST RESIDUAL (§7.4): a frame lost between a run starting and this tab's
 * first receipt presents identically to a mid-run attach. On a fresh attach the
 * queue is empty, so the only path there is a coalesced `progress` — in which
 * case "attached while this run was in progress" is still true, trivially, of
 * one transient tick. That is an argument, not a measurement.
 */
export function seamKind(live: readonly LiveEntry[]): SeamKind {
  for (const entry of live) {
    if (entry.entry === "echo") return "end";
    if (entry.entry === "event") return entry.item.seq === 0 ? "end" : "mid-run";
  }
  return "end";
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
  prompts: readonly RestoredPrompt[] = [],
  /** §8(i)'s prompt-row identity owner; see `historicalRows` for the fallback. */
  sessionId: string | null = null,
): readonly PanelRow[] {
  const before = historicalRows(history, prompts, sessionId);
  const after = liveRows(live);
  if (before.length === 0 || after.length === 0) return [...before, ...after];
  return [...before, { row: "seam", key: "seam", kind: seamKind(live) }, ...after];
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
