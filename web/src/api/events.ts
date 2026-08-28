// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The normalized public event vocabulary, and the two identity namespaces.
//
// INTERFACE.md §2.7: the socket emits "the **normalized public vocabulary
// only** — `text_delta, thought, tool_call, tool_result, image, question,
// answer, audit, progress, terminal`", with a wire shape that is "the
// Python-side shape verbatim — `{run_id, seq, kind, tool_call_id?, payload?}` —
// plus exactly one envelope field, `session_id`". **No web-specific event kind
// is minted and no field is added**, and nothing here invents one either: the
// vocabulary below is closed and a frame outside it is reported unknown rather
// than coerced into a neighbour.
//
// §2.8 names two identities and refuses to merge them:
//
//   live stream  (run_id, seq)          serialized `<run_id>#<seq>`
//   history page (session_id, ordinal)  serialized `<session_id>@<ordinal>`
//
// The separators differ so a `data-event-id` in the DOM tells a live chip from a
// historical one without a second attribute. This module mirrors
// `server/src/hephaestus/http/event_identity.py` exactly — same separators, same
// three-valued `identitySurface` — because a client that spelled an identity
// differently from the server would make the G4.11 archive unassertable.
//
// **The historical frame's `run_id` field carries the session id.** That is not
// a bug here: `main.ts`'s `history.page` handler passes the session id into the
// parameter `history.ts` names `runId`, and `wireEvent` serializes it under
// `run_id`. §2.8 names the misnomer; this module reads the page's own
// `session_id` for the identity and never treats a historical `run_id` as a run.
//
// Every payload reader below is **total and never throws**. An unreadable
// payload yields `null` — a named absence the panel renders as such — because a
// transcript is a durable log and a client that threw on one malformed entry
// would take the whole transcript with it.

/** §2.7's closed vocabulary, in the order that section lists it. */
export const EVENT_KINDS = [
  "text_delta",
  "thought",
  "tool_call",
  "tool_result",
  "image",
  "question",
  "answer",
  "audit",
  "progress",
  "terminal",
] as const;

export type EventKind = (typeof EVENT_KINDS)[number];

const KIND_SET: ReadonlySet<string> = new Set<string>(EVENT_KINDS);

export function isEventKind(value: unknown): value is EventKind {
  return typeof value === "string" && KIND_SET.has(value);
}

/**
 * One frame off `GET /events` (§2.7): the Python shape plus `session_id`.
 *
 * `session_id` is always present and is `null` when the run→session binding has
 * been evicted — "a named absence a client must render unrouted rather than
 * attribute to whatever session it happens to be showing"
 * (`http/sessions.py::wire_frame`).
 */
export interface EventFrame {
  readonly run_id: string;
  readonly seq: number;
  readonly kind: string;
  readonly session_id: string | null;
  readonly tool_call_id?: string;
  readonly payload?: unknown;
}

/**
 * One event inside a `GET /sessions/{id}/history` page.
 *
 * Same serialization (`wireEvent`), no `session_id` envelope field — the page
 * carries the session once, at the document level — and `run_id` holds the
 * session id (see the module docstring).
 */
export interface HistoryEventFrame {
  readonly run_id: string;
  readonly seq: number;
  readonly kind: string;
  readonly tool_call_id?: string;
  readonly payload?: unknown;
}

// ---------------------------------------------------------------------------
// identity
// ---------------------------------------------------------------------------

/** Live: `<run_id>#<seq>` (`http/event_identity.py::LIVE_SEPARATOR`). */
export const LIVE_SEPARATOR = "#";

/** Historical: `<session_id>@<ordinal>` (`HISTORICAL_SEPARATOR`). */
export const HISTORICAL_SEPARATOR = "@";

export type IdentitySurface = "live" | "historical" | "unknown";

/**
 * Serialize a live event's run-scoped identity.
 *
 * **HONEST LIMIT, found against a live socket.** A `terminal` is minted with
 * `seq = 2**62` so terminals sort last (`agent_bridge/events.py`), and `2**62`
 * exceeds `Number.MAX_SAFE_INTEGER`: by the time a frame reaches this function
 * a browser's `JSON.parse` has already rounded it, so a live terminal's id here
 * reads `…#4611686018427388000` where the server would write
 * `…#4611686018427387904`. Nothing on this side can recover the exact value —
 * the precision is gone before any client code runs — so it is stated rather
 * than papered over. It costs nothing that a gate reads: G4.11's archive is over
 * the **historical** namespace (§2.8), whose ordinals are small, and a terminal
 * carries an exact `terminal_id` in its own payload, which is what the run-end
 * band identifies itself by. `live.ts` additionally refuses to put an unsafe
 * seq into a resume cursor, because that one *would* produce a false gap.
 */
export function liveEventId(runId: string, seq: number): string {
  return `${runId}${LIVE_SEPARATOR}${seq}`;
}

export function historicalEventId(sessionId: string, ordinal: number): string {
  return `${sessionId}${HISTORICAL_SEPARATOR}${ordinal}`;
}

/**
 * Which namespace a serialized identity belongs to, from its separator alone.
 *
 * An id carrying neither separator is `"unknown"` rather than guessed into one
 * of the two, which is the same three-valued answer the server gives.
 */
export function identitySurface(eventId: string): IdentitySurface {
  if (eventId.includes(LIVE_SEPARATOR)) return "live";
  if (eventId.includes(HISTORICAL_SEPARATOR)) return "historical";
  return "unknown";
}

// ---------------------------------------------------------------------------
// payload readers — total, never throwing, absence-preserving
// ---------------------------------------------------------------------------

function record(value: unknown): Readonly<Record<string, unknown>> | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  return value as Readonly<Record<string, unknown>>;
}

function str(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

/** `text_delta` and `thought` both carry `{text}` (`live.ts`, `history.ts`). */
export function readText(payload: unknown): string | null {
  const body = record(payload);
  return body === null ? null : str(body["text"]);
}

export interface ToolCallPayload {
  readonly name: string;
  readonly args: unknown;
}

/** `tool_call` → `{name, arguments}`. */
export function readToolCall(payload: unknown): ToolCallPayload | null {
  const body = record(payload);
  if (body === null) return null;
  const name = str(body["name"]);
  if (name === null) return null;
  return { name, args: body["arguments"] };
}

export interface ToolResultPayload {
  readonly toolName: string | null;
  readonly text: string;
  /**
   * §7.2 / §19.13: `null` is the **third** answer and it is not `false`.
   *
   * `normalizeEntries` emits `isError: boolean | null` — Pi's own flag first,
   * then the serialized envelope's `status`, and `null` when neither is
   * recoverable. A client MUST NOT read `null` as `ok`: that is exactly the
   * silently-dropped state §7.2 exists to remove, and it is why the chip's
   * status set gains the visible `unknown` value for historical chips.
   */
  readonly isError: boolean | null;
}

/** `tool_result` → `{toolName, text, isError}`. */
export function readToolResult(payload: unknown): ToolResultPayload | null {
  const body = record(payload);
  if (body === null) return null;
  const raw = body["isError"];
  return {
    toolName: str(body["toolName"]),
    text: str(body["text"]) ?? "",
    isError: typeof raw === "boolean" ? raw : null,
  };
}

export interface ImagePayload {
  readonly mimeType: string | null;
  /** Live only: base64 bytes. History retains `{mimeType}` alone (§7.3). */
  readonly data: string | null;
  readonly bytes: number | null;
}

/** `image` → live `{mimeType, bytes, data}`, historical `{mimeType}`. */
export function readImage(payload: unknown): ImagePayload | null {
  const body = record(payload);
  if (body === null) return null;
  const bytes = body["bytes"];
  return {
    mimeType: str(body["mimeType"]),
    data: str(body["data"]),
    bytes: typeof bytes === "number" && Number.isFinite(bytes) ? bytes : null,
  };
}

/**
 * One `ask_user` option.
 *
 * `_CLARIFICATION_OPTION` (`contract/tools_decl.py`) requires **both** `label`
 * and `consequence`, and §7.3 says options render both. The schema also admits a
 * bare string, which carries no consequence at all — that case keeps
 * `consequence: null` so the widget can state the absence instead of inventing
 * a geometric consequence the model never wrote.
 */
export interface ClarificationOption {
  readonly label: string;
  readonly consequence: string | null;
}

export function readOptions(value: unknown): readonly ClarificationOption[] {
  if (!Array.isArray(value)) return [];
  const out: ClarificationOption[] = [];
  for (const item of value as readonly unknown[]) {
    if (typeof item === "string") {
      out.push({ label: item, consequence: null });
      continue;
    }
    const body = record(item);
    if (body === null) continue;
    const label = str(body["label"]);
    if (label === null) continue;
    out.push({ label, consequence: str(body["consequence"]) });
  }
  return out;
}

export interface QuestionPayload {
  /** Minted in `main.ts` around the `py.ask_user` suspension (§2.7). */
  readonly questionId: string | null;
  readonly question: string | null;
  readonly options: readonly ClarificationOption[];
}

/** `question` → `{question_id, question, options}`. Live only (§7.3). */
export function readQuestion(payload: unknown): QuestionPayload | null {
  const body = record(payload);
  if (body === null) return null;
  return {
    questionId: str(body["question_id"]),
    question: str(body["question"]),
    options: readOptions(body["options"]),
  };
}

export interface AnswerPayload {
  readonly questionId: string | null;
  readonly answer: unknown;
}

/** `answer` → `{question_id, answer}`. Live only (§7.3). */
export function readAnswer(payload: unknown): AnswerPayload | null {
  const body = record(payload);
  if (body === null) return null;
  return { questionId: str(body["question_id"]), answer: body["answer"] };
}

/** `audit` → a compact line carrying `payload.event` (§7.3). */
export function readAudit(payload: unknown): string | null {
  const body = record(payload);
  return body === null ? null : str(body["event"]);
}

/** `progress` → `{toolName}`; coalesced, never durable (§7.3). */
export function readProgress(payload: unknown): string | null {
  const body = record(payload);
  return body === null ? null : str(body["toolName"]);
}

/** `opstore.types.TerminalState`, closed at five. */
export const TERMINAL_STATES = [
  "completed",
  "failed",
  "cancelled",
  "timed_out",
  "interrupted",
] as const;

export type TerminalState = (typeof TERMINAL_STATES)[number];

const TERMINAL_STATE_SET: ReadonlySet<string> = new Set<string>(TERMINAL_STATES);

/**
 * The prefix `EventPump._backpressure_cancel` mints its terminal id with.
 *
 * **DEVIATION, recorded rather than papered over.** §7.3 says "a
 * `backpressure_cancel` reason renders with its own explanatory copy", but the
 * terminal *event*'s payload is only `{state, terminal_id}`
 * (`agent_bridge/events.py`): the pump puts `{"reason": "backpressure_cancel"}`
 * in the durable terminal record's `data`, which the event never carries. The
 * one observable signal on the socket is therefore the terminal id, which that
 * path mints as `backpressure:<run_id>`. This client reads that prefix and says
 * so. Adding a `reason` to the terminal payload would be a field added to
 * `HephaestusEvent`'s payload vocabulary, which §2.7 forbids outright, and
 * rendering nothing would be the exact confusion §7.3 asks us to prevent.
 */
export const BACKPRESSURE_TERMINAL_PREFIX = "backpressure:";

export interface TerminalPayload {
  readonly state: string | null;
  readonly terminalId: string | null;
  /** `true` only when the id says so; `false` is "not by this signal". */
  readonly backpressure: boolean;
}

/** `terminal` → `{state, terminal_id}` (`agent_bridge/events.py`). Live only. */
export function readTerminal(payload: unknown): TerminalPayload | null {
  const body = record(payload);
  if (body === null) return null;
  const terminalId = str(body["terminal_id"]);
  return {
    state: str(body["state"]),
    terminalId,
    backpressure: terminalId !== null && terminalId.startsWith(BACKPRESSURE_TERMINAL_PREFIX),
  };
}

export function isTerminalState(value: string | null): value is TerminalState {
  return value !== null && TERMINAL_STATE_SET.has(value);
}
