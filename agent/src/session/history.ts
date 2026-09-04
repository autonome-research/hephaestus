// history.page — normalized, bounded, restart-stable historical reads.
//
// STAGE2_DIGEST §2 (historical-session reads): a private bounded bridge method
// reads Pi JSONL via Pi's session API, normalizes it into the public Hephaestus
// event vocabulary, and freezes a first-page high-water mark into opaque cursors.
// HTTP/CLI serve only that normalized snapshot; nothing outside the sidecar ever
// parses Pi JSONL. Because Pi session entries are append-only and carry stable
// IDs, the same public events reconstruct byte-for-byte after a restart.
//
// INTERFACE.md §2.8, amended 2026-09-03 (the turn record): a reopened
// transcript must be reconstructible from the durable record, which needs three
// things this module now provides — a `turn` ordinal on every historical event,
// one `user_prompts` entry per user message carrying the operator's sentence
// *apart* from the workspace envelope, and a tail read (`after`) so a client can
// pick up what was recorded since the page it already holds. All three are
// additive: no event's `seq`, page boundary or payload moves, which is what
// keeps the G4.11 event archive green without a re-baseline.

import type { SessionEntry } from "@earendil-works/pi-coding-agent";
import type { HephaestusEvent, EventKind } from "../events.js";
import type { JsonValue } from "../framing.js";

/** Default maximum events returned per page (bounded historical read). */
export const HISTORY_PAGE_SIZE = 250;

/**
 * The prompt-time marker's `customType` (INTERFACE.md §2.8(3)).
 *
 * A Pi `CustomEntry` is the right carrier for exactly one reason: it is
 * **excluded from LLM context** (`session-manager.d.ts`: "Does NOT participate
 * in LLM context"), so recording what the operator typed cannot change what the
 * model reads. It rides in the same JSONL as the messages, so it survives resume
 * for the same reason the transcript does.
 */
export const TURN_MARKER_TYPE = "hephaestus.turn.v1";

/**
 * The end-of-turn marker's `customType` (INTERFACE.md §2.8(4), source (ii)).
 *
 * Only for a turn that ended with **no assistant entry at all** — cancelled
 * before the model answered, or failed before the first token. A turn that has
 * an assistant entry is projected from that entry (source (i)), which is why
 * every session already on disk gets an outcome without ever having been
 * recorded with a marker.
 */
export const TURN_OUTCOME_MARKER_TYPE = "hephaestus.turn_outcome.v1";

// Pi message content is not exported by name from the SDK barrel; we read its
// JSON shape structurally. Isolated at this Pi-boundary adapter, no `any`.
interface PiTextContent {
  type: "text";
  text: string;
}
interface PiThinkingContent {
  type: "thinking";
  thinking: string;
}
interface PiToolCallContent {
  type: "toolCall";
  id: string;
  name: string;
  arguments: Record<string, unknown>;
}
interface PiImageContent {
  type: "image";
  mimeType: string;
}
type PiAssistantContent = PiTextContent | PiThinkingContent | PiToolCallContent;
type PiToolResultContent = PiTextContent | PiImageContent;

interface PiAssistantMessage {
  role: "assistant";
  content: PiAssistantContent[];
  /**
   * Pi's `AssistantMessage.stopReason` / `errorMessage` (`pi-ai` `types.d.ts`).
   *
   * Declared `unknown` and optional here rather than as `StopReason`: this is a
   * *persisted* entry, possibly written by an older sidecar or an older Pi, and
   * a durable log read through a type that promises a closed string union is a
   * lie the compiler cannot catch. §2.8(4) reads them defensively below.
   */
  stopReason?: unknown;
  errorMessage?: unknown;
}
interface PiToolResultMessage {
  role: "toolResult";
  toolCallId: string;
  toolName: string;
  content: PiToolResultContent[];
  /**
   * Pi's own failure flag (`@earendil-works/pi-ai` `ToolResultMessage.isError`).
   * Declared optional here and nowhere else: the SDK types it as required, but a
   * *persisted* entry written by an older sidecar has no such field, and reading
   * a durable log through a type that promises one would be a lie the compiler
   * cannot catch.
   */
  isError?: unknown;
}
interface PiUserMessage {
  role: "user";
  content: unknown;
}
type PiMessage = PiAssistantMessage | PiToolResultMessage | PiUserMessage;

/** The closed set of non-completed turn states (INTERFACE.md §2.8(4)). */
export type TurnOutcomeState = "cancelled" | "error" | "interrupted";

/**
 * A recorded turn's outcome. **Absent means completed, never unknown** — that
 * is the whole reason §2.8(4) names two sources rather than one: a turn with an
 * assistant entry is read off the entry, a turn without one is read off the
 * marker, and a turn with neither really did complete.
 */
export interface HistoryTurnOutcome {
  readonly state: TurnOutcomeState;
  readonly message?: string;
}

/**
 * One recorded operator prompt (INTERFACE.md §2.8(2)).
 *
 * `turn` is THE IDENTITY: 0-based, unique, strictly increasing. `seq` keeps its
 * shipped meaning — the ordinal of this turn's first event, which the shipped
 * client reads — but is explicitly **not** unique: two prompts around a
 * zero-event turn share one, which is exactly the collision that made
 * `<session_id>@prompt:<seq>` an unusable row key.
 */
export interface HistoryUserPrompt {
  readonly turn: number;
  readonly seq: number;
  /** The operator's typed sentence and nothing else; null when unrecoverable. */
  readonly text: string | null;
  /** §7A.3's workspace-context block verbatim, when one was sent. */
  readonly envelope: string | null;
  readonly outcome?: HistoryTurnOutcome;
  /**
   * Who wrote `text` (INTERFACE.md §2.8(3), amended 2026-09-03). ABSENT means the
   * operator. `"agent"` marks the one user-role message this sidecar writes
   * itself: the continuation prompt of the single transient retry
   * (`session/retry.ts`). It is still a turn — §2.8(2)'s exactly-one-entry rule
   * holds — but a panel must not label that sentence as the operator's.
   */
  readonly origin?: "agent";
}

/**
 * A historical event plus its turn ordinal (INTERFACE.md §2.8(1)).
 *
 * `turn` is a field of the HISTORY PAGE and of nothing else. It is deliberately
 * NOT on `HephaestusEvent`: `wireEvent` (`live.ts`) serves both the live
 * `notify("event", …)` path and the history page, so a field on the shared
 * event type would leak onto the live socket, which §2.8(1) forbids. The
 * history.page handler in `main.ts` stamps it after `wireEvent`.
 */
export interface HistoryEvent extends HephaestusEvent {
  /** 0-based index of the user message whose turn recorded this event; `null`
   *  — not -1, not 0 — for an event recorded before the session's first user
   *  message, which the client renders as a prologue with no prompt row. */
  readonly turn: number | null;
}

/** Recover the operator's words from a Pi user message. */
export function userPromptText(content: unknown): string | null {
  if (typeof content === "string") {
    const text = content.trim();
    return text === "" ? null : text;
  }
  if (!Array.isArray(content)) return null;
  const parts: string[] = [];
  for (const item of content) {
    if (item === null || typeof item !== "object") continue;
    const record = item as { type?: unknown; text?: unknown };
    if (record.type === "text" && typeof record.text === "string" && record.text !== "") {
      parts.push(record.text);
    }
  }
  const text = parts.join("").trim();
  return text === "" ? null : text;
}

/**
 * Recover a historical `tool_result`'s failure flag (INTERFACE.md §7.2, §19.13).
 *
 * WHY THIS EXISTS. Only the *live* normalizer emitted `isError` (`live.ts`);
 * `normalizeEntries` emitted `{toolName, text}` and nothing else, so in a
 * reopened transcript every chip's `isError` was `undefined`, which under §7.2's
 * rule ("false is ok") rendered a tool call that FAILED as `ok`. A panel stating
 * as fact that a failed call succeeded is a silently-dropped state, and §7.2
 * requires it fixed in the engine *before* the G4.11 event archive is baselined
 * so the archive records the corrected shape.
 *
 * Two sources, in the order §7.2 names them:
 *
 * 1. **Pi's `toolResult` message.** `ToolResultMessage.isError` is a real
 *    boolean on the persisted entry — this is the recoverable branch, and it is
 *    why §7.2's `unknown` fallback stays a fallback.
 * 2. **The serialized result envelope's `status`.** Every dispatched tool result
 *    is one canonical-JSON text block (`tools/proxy.ts`), so a legacy entry
 *    written before (1) existed still carries `{"status": …}`. `"error"` is a
 *    failure; every other status (`ok`, `conflict`, `capability_error`, …) is a
 *    successful discriminated result, exactly as `tool_schema.md` has it.
 *
 * `null` when NEITHER is present. It is deliberately not `false`: an unknown
 * outcome rendered as success is the defect this function exists to remove, and
 * §7.2's closed `running | ok | error` set gains its named fourth value
 * `unknown` for precisely this case. A client MUST NOT read `null` as `ok`.
 */
function recoverIsError(message: PiToolResultMessage, text: string): boolean | null {
  if (typeof message.isError === "boolean") return message.isError;
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return null;
  }
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) return null;
  const status = (parsed as { status?: unknown }).status;
  if (typeof status !== "string") return null;
  return status === "error";
}

/**
 * The turn's outcome as recorded on its last assistant entry — §2.8(4)'s source
 * (i), and the branch that works for every session ALREADY ON DISK.
 *
 * `null` for `stopReason: "stop"` and for an entry that records no stop reason
 * at all: absence of an outcome means the turn completed, so guessing here would
 * label a completed turn. `aborted` is the operator's cancel; `error` is the
 * provider/stream failure Pi resolves rather than throws (see `retry.ts`);
 * `length`, `toolUse` and any stop reason a future Pi adds are `interrupted` —
 * the turn stopped without finishing, and the honest word for "we know it did
 * not complete and we do not know a better name" is the one §2.8(4) reserves.
 */
function assistantOutcome(message: PiAssistantMessage): HistoryTurnOutcome | null {
  const stop = typeof message.stopReason === "string" ? message.stopReason : undefined;
  if (stop === undefined || stop === "stop") return null;
  const state: TurnOutcomeState =
    stop === "aborted" ? "cancelled" : stop === "error" ? "error" : "interrupted";
  const detail =
    typeof message.errorMessage === "string" && message.errorMessage !== ""
      ? message.errorMessage
      : undefined;
  return detail !== undefined ? { state, message: detail } : { state };
}

/** The prompt-time marker's payload, read defensively (it is durable JSON). */
interface TurnMarker {
  readonly text: string | null;
  readonly envelope: string | null;
  readonly origin: "operator" | "agent";
}

function readTurnMarker(data: unknown): TurnMarker | null {
  if (data === null || typeof data !== "object" || Array.isArray(data)) return null;
  const record = data as { text?: unknown; envelope?: unknown; origin?: unknown };
  const text =
    typeof record.text === "string" && record.text.trim() !== "" ? record.text : null;
  const envelope =
    typeof record.envelope === "string" && record.envelope !== "" ? record.envelope : null;
  // Absent means operator, so every marker written before `origin` existed keeps
  // its meaning; only the literal "agent" changes the attribution.
  const origin = record.origin === "agent" ? "agent" : "operator";
  return { text, envelope, origin };
}

function readOutcomeMarker(data: unknown): HistoryTurnOutcome | null {
  if (data === null || typeof data !== "object" || Array.isArray(data)) return null;
  const record = data as { state?: unknown; message?: unknown };
  const state = record.state;
  if (state !== "cancelled" && state !== "error" && state !== "interrupted") return null;
  const detail =
    typeof record.message === "string" && record.message !== "" ? record.message : undefined;
  return detail !== undefined ? { state, message: detail } : { state };
}

function makeEvent(
  runId: string,
  seq: number,
  turn: number | null,
  kind: EventKind,
  payload: JsonValue,
  toolCallId?: string,
): HistoryEvent {
  return toolCallId !== undefined
    ? { runId, seq, turn, kind, toolCallId, payload }
    : { runId, seq, turn, kind, payload };
}

/** Mutable per-turn accumulator; frozen into a `HistoryUserPrompt` at the end. */
interface TurnAccumulator {
  readonly turn: number;
  readonly seq: number;
  readonly text: string | null;
  readonly envelope: string | null;
  readonly origin: "operator" | "agent";
  /** Whether this turn recorded any assistant entry at all — the §2.8(4) switch
   *  between outcome source (i) and source (ii). */
  hasAssistant: boolean;
  /** The LAST assistant entry's outcome; later entries overwrite earlier ones. */
  assistantOutcome: HistoryTurnOutcome | null;
  markerOutcome: HistoryTurnOutcome | null;
}

interface Walk {
  readonly events: HistoryEvent[];
  readonly prompts: HistoryUserPrompt[];
}

/**
 * The single walk over the entry slice that produces BOTH the event sequence and
 * the prompt records.
 *
 * WHY ONE WALK. `normalizeEntries` and `extractUserPrompts` used to walk
 * separately and each maintained its own copy of the seq arithmetic — a mirror
 * that had to be edited in two places and would have broken silently in one.
 * §2.8(1)-(2) now makes the two outputs *interdependent* (a prompt's `seq` is
 * the next event's ordinal; an event's `turn` is the count of prompts before
 * it), so they are computed together and the two exported functions are
 * projections of this result. Both exports keep their shipped signatures.
 *
 * MARKER ENTRIES CONSUME NOTHING. A Pi `CustomEntry` is neither `message` nor
 * `compaction`, so it emits no event and advances no `seq`. Appending markers to
 * a session therefore changes no event identity — the property `history.test.ts`
 * pins and `tests/stage4/test_g4_event_archive.py` defends.
 */
function walkEntries(entries: readonly SessionEntry[], runId: string): Walk {
  const events: HistoryEvent[] = [];
  const accumulators: TurnAccumulator[] = [];
  let seq = 0;
  let turn: number | null = null;
  // A marker binds to the NEXT user message entry after it (§2.8(3)). Any other
  // message in between orphans it: the sidecar appends the marker immediately
  // before `sendUserMessage`, so anything else arriving first means this marker
  // is not the one that describes the next prompt.
  let pendingMarker: TurnMarker | null = null;

  const emit = (kind: EventKind, payload: JsonValue, toolCallId?: string): void => {
    events.push(makeEvent(runId, seq, turn, kind, payload, toolCallId));
    seq += 1;
  };

  for (const entry of entries) {
    if (entry.type === "custom") {
      if (entry.customType === TURN_MARKER_TYPE) {
        pendingMarker = readTurnMarker(entry.data);
      } else if (entry.customType === TURN_OUTCOME_MARKER_TYPE) {
        // Appended after the run ends, so it describes the turn in progress —
        // the positional count, not the marker's own informational `turn`.
        const current = accumulators[accumulators.length - 1];
        const outcome = readOutcomeMarker(entry.data);
        if (current !== undefined && outcome !== null && current.markerOutcome === null) {
          current.markerOutcome = outcome;
        }
      }
      continue;
    }
    if (entry.type === "compaction") {
      emit("audit", { event: "compaction" });
      continue;
    }
    if (entry.type !== "message") continue;
    // entry.message is a Pi AgentMessage; read it via the structural adapter.
    const message = entry.message as unknown as PiMessage;
    if (message.role === "user") {
      // The turn ordinal is COUNTED, never read: it is deterministic from this
      // frozen slice, therefore restart-stable for exactly the reason `seq` is,
      // and nothing is written to disk to support it. On any disagreement with a
      // marker's own `turn` field, this count wins (§2.8(3)).
      turn = turn === null ? 0 : turn + 1;
      const marker = pendingMarker;
      pendingMarker = null;
      accumulators.push({
        turn,
        seq,
        // With a marker the operator's sentence is recorded apart from the
        // envelope. Without one — every pre-existing session, and any turn whose
        // marker a compaction or a branch dropped — §2.8(3)'s per-turn fallback
        // is today's behaviour verbatim: the whole joined text, no envelope.
        // The `# Workspace context` heading is NEVER regex-stripped to guess a
        // separation: the block's tail is application-state dependent
        // (server/src/hephaestus/http/context.py), so a guess would put the
        // server's words in the operator's mouth some of the time and never say
        // which times.
        text: marker !== null ? marker.text : userPromptText(message.content),
        envelope: marker !== null ? marker.envelope : null,
        origin: marker !== null ? marker.origin : "operator",
        hasAssistant: false,
        assistantOutcome: null,
        markerOutcome: null,
      });
      continue;
    }
    pendingMarker = null;
    if (message.role === "assistant") {
      const current = accumulators[accumulators.length - 1];
      if (current !== undefined) {
        current.hasAssistant = true;
        current.assistantOutcome = assistantOutcome(message);
      }
      for (const item of message.content) {
        if (item.type === "text") emit("text_delta", { text: item.text });
        // An EMPTY thinking block is not a thought — the live normalizer already
        // drops zero-length deltas (`live.ts`), and a reopened transcript that
        // renders an empty bubble where the live one rendered nothing is the two
        // surfaces disagreeing about the same turn.
        else if (item.type === "thinking") {
          if (item.thinking !== "") emit("thought", { text: item.thinking });
        } else if (item.type === "toolCall")
          emit("tool_call", { name: item.name, arguments: item.arguments as JsonValue }, item.id);
      }
    } else if (message.role === "toolResult") {
      const text = message.content
        .filter((c): c is PiTextContent => c.type === "text")
        .map((c) => c.text)
        .join("");
      emit(
        "tool_result",
        { toolName: message.toolName, text, isError: recoverIsError(message, text) },
        message.toolCallId,
      );
      for (const item of message.content) {
        if (item.type === "image") emit("image", { mimeType: item.mimeType }, message.toolCallId);
      }
    }
    // user messages: recorded beside the page (`extractUserPrompts`), not here.
  }

  const prompts: HistoryUserPrompt[] = accumulators.map((acc) => {
    // §2.8(4)'s two sources, in order. A turn WITH an assistant entry is read
    // off that entry and the marker is ignored, which is what keeps `absent`
    // meaning *completed*: a cancel that raced a finished turn cannot relabel a
    // turn the model actually finished.
    const outcome = acc.hasAssistant ? acc.assistantOutcome : acc.markerOutcome;
    const base = { turn: acc.turn, seq: acc.seq, text: acc.text, envelope: acc.envelope };
    const attributed = acc.origin === "agent" ? { ...base, origin: "agent" as const } : base;
    return outcome !== null ? { ...attributed, outcome } : attributed;
  });
  return { events, prompts };
}

/**
 * Normalize an ordered list of session entries into public Hephaestus events.
 * Deterministic: identical entries always yield identical events + seq numbers,
 * which is what makes cursors restart-stable. Compaction entries surface as
 * audit. User prompts travel beside the page as the additive `user_prompts`
 * field and do not enter this event sequence.
 *
 * **IDENTITY NAMESPACE (INTERFACE.md §2.8).** The `runId` parameter is a
 * misnomer kept for compatibility: every production caller (`main.ts`'s
 * `history.page` handler) passes the **session id**, and `seq` restarts at 0 for
 * the whole session. A historical event's identity is therefore
 * `(session_id, ordinal)` — session-scoped — while a live event's is
 * `(run_id, seq)`, run-scoped and minted by `active.nextSeq()` in `live.ts`.
 * **The two are disjoint and are never merged.** Nothing here reconstructs a
 * live-comparable identity, and history must never be used to close a live gap:
 * a dedupe on `(run_id, seq)` across the two surfaces would never match and
 * would render every refilled event twice.
 *
 * The additive `turn` (§2.8(1)) does not change that: a turn is a record of one
 * thing the operator asked, a run is one live execution, and no `run_id` is
 * reconstructed from a turn ordinal.
 */
export function normalizeEntries(entries: readonly SessionEntry[], runId: string): HistoryEvent[] {
  return walkEntries(entries, runId).events;
}

/**
 * Walk the same entries `normalizeEntries` does and collect operator prompts
 * at the **current** seq — the next event that would be emitted. Prompts do
 * not consume a seq, so the event archive is unchanged.
 *
 * EXACTLY ONE ENTRY PER USER MESSAGE (§2.8(2)), including a textless one
 * (`text: null`) and a turn that produced zero events. The shipped version
 * dropped a user message with no recoverable text entirely, so a reopened
 * transcript silently lost a turn the operator really took.
 */
export function extractUserPrompts(entries: readonly SessionEntry[]): HistoryUserPrompt[] {
  return walkEntries(entries, "").prompts;
}

/**
 * The turn ordinal the NEXT user message will take (INTERFACE.md §2.8(3)).
 *
 * Used at prompt time by `main.ts` to stamp the marker it appends. It is the
 * same count `walkEntries` performs, exported so the writer and the reader
 * cannot drift — though on disagreement the reader's positional count wins,
 * because the count is deterministic from the frozen slice and a written field
 * is not.
 */
export function nextTurnOrdinal(entries: readonly SessionEntry[]): number {
  let count = 0;
  for (const entry of entries) {
    if (entry.type !== "message") continue;
    const message = entry.message as unknown as PiMessage;
    if (message.role === "user") count += 1;
  }
  return count;
}

interface Cursor {
  /** Frozen high-water entry ID: the last entry included on the first page. */
  readonly hw: string;
  /** Number of normalized events already delivered. */
  readonly offset: number;
}

export function encodeCursor(cursor: Cursor): string {
  return Buffer.from(JSON.stringify(cursor), "utf8").toString("base64url");
}

export function decodeCursor(token: string): Cursor {
  let parsed: unknown;
  try {
    parsed = JSON.parse(Buffer.from(token, "base64url").toString("utf8"));
  } catch {
    throw new Error("malformed history cursor");
  }
  const obj = parsed as { hw?: unknown; offset?: unknown };
  if (typeof obj.hw !== "string" || typeof obj.offset !== "number" || !Number.isInteger(obj.offset) || obj.offset < 0) {
    throw new Error("malformed history cursor");
  }
  return { hw: obj.hw, offset: obj.offset };
}

export interface HistoryPageRequest {
  /** Continue inside the snapshot this token froze. */
  readonly cursor?: string;
  /**
   * TAIL READ (§2.8(5)): freeze a NEW high-water mark now and start at the
   * ordinal this token names. Mutually exclusive with `cursor` — a call
   * carrying both is refused rather than letting one silently win.
   */
  readonly after?: string;
}

export interface HistoryPage {
  readonly events: HistoryEvent[];
  /**
   * Operator prompts belonging to this page, keyed to the next event `seq`.
   * Additive: omitted by older clients, never shifts event identities.
   */
  readonly userPrompts: HistoryUserPrompt[];
  /** Opaque continuation token, or null when the frozen snapshot is exhausted. */
  readonly cursor: string | null;
  readonly done: boolean;
  /**
   * ALWAYS present, NEVER null, on every page including the last (§2.8(5)).
   * Names the ordinal after this page's last event; hand it back as `after` to
   * read what has been recorded since. `cursor` cannot serve this purpose: it is
   * null exactly when the walk finished, which is exactly when a client wants a
   * durable end mark.
   */
  readonly endCursor: string;
}

export interface HistoryPageOptions {
  readonly pageSize?: number;
}

/**
 * Page normalized events over a frozen high-water snapshot. The first call (no
 * cursor) freezes the high-water mark at the last current entry; later pages —
 * even after the session grew or the process restarted — reconstruct events only
 * up to that mark, so pagination never shifts under a concurrent writer.
 *
 * A tail read (`after`) freezes a NEW mark and starts at the named ordinal.
 * Prior identities never move under it: a historical `seq` is a
 * session-cumulative ordinal over an append-only log, so re-normalizing from
 * entry zero and slicing returns every event with the identity it always had.
 */
export function pageHistory(
  entries: readonly SessionEntry[],
  runId: string,
  request: HistoryPageRequest = {},
  options: HistoryPageOptions = {},
): HistoryPage {
  const pageSize = options.pageSize ?? HISTORY_PAGE_SIZE;
  if (request.cursor !== undefined && request.after !== undefined) {
    throw new Error("history page accepts cursor or after, not both");
  }

  const last = entries[entries.length - 1];
  const currentMark = last === undefined ? "" : last.id;

  let hw: string;
  let offset: number;
  if (request.cursor !== undefined) {
    const decoded = decodeCursor(request.cursor);
    hw = decoded.hw;
    offset = decoded.offset;
  } else if (request.after !== undefined) {
    // The tail read deliberately DISCARDS the token's frozen mark: the point of
    // the call is to see what was appended after it.
    offset = decodeCursor(request.after).offset;
    hw = currentMark;
  } else {
    hw = currentMark;
    offset = 0;
  }

  if (entries.length === 0) {
    return {
      events: [],
      userPrompts: [],
      cursor: null,
      done: true,
      endCursor: request.after ?? encodeCursor({ hw, offset }),
    };
  }

  const hwIndex = entries.findIndex((e) => e.id === hw);
  // If the high-water entry is gone (should not happen for append-only logs),
  // fall back to the full frozen set we do have.
  const frozen = hwIndex >= 0 ? entries.slice(0, hwIndex + 1) : entries.slice();
  const { events: all, prompts } = walkEntries(frozen, runId);

  const page = all.slice(offset, offset + pageSize);
  const nextOffset = offset + page.length;
  const done = nextOffset >= all.length;
  const userPrompts = prompts.filter(
    (prompt) => prompt.seq >= offset && (prompt.seq < nextOffset || done),
  );
  return {
    events: page,
    userPrompts,
    cursor: done ? null : encodeCursor({ hw, offset: nextOffset }),
    done,
    // An `after` that found nothing echoes the token it was given, so a polling
    // client's end mark is byte-stable while the session is quiet.
    endCursor:
      page.length === 0 && request.after !== undefined
        ? request.after
        : encodeCursor({ hw, offset: nextOffset }),
  };
}
