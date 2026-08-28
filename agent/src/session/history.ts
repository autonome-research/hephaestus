// history.page — normalized, bounded, restart-stable historical reads.
//
// STAGE2_DIGEST §2 (historical-session reads): a private bounded bridge method
// reads Pi JSONL via Pi's session API, normalizes it into the public Hephaestus
// event vocabulary, and freezes a first-page high-water mark into opaque cursors.
// HTTP/CLI serve only that normalized snapshot; nothing outside the sidecar ever
// parses Pi JSONL. Because Pi session entries are append-only and carry stable
// IDs, the same public events reconstruct byte-for-byte after a restart.

import type { SessionEntry } from "@earendil-works/pi-coding-agent";
import type { HephaestusEvent, EventKind } from "../events.js";
import type { JsonValue } from "../framing.js";

/** Default maximum events returned per page (bounded historical read). */
export const HISTORY_PAGE_SIZE = 250;

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

function makeEvent(
  runId: string,
  seq: number,
  kind: EventKind,
  payload: JsonValue,
  toolCallId?: string,
): HephaestusEvent {
  return toolCallId !== undefined ? { runId, seq, kind, toolCallId, payload } : { runId, seq, kind, payload };
}

/**
 * Normalize an ordered list of session entries into public Hephaestus events.
 * Deterministic: identical entries always yield identical events + seq numbers,
 * which is what makes cursors restart-stable. User prompts are not part of the
 * public event vocabulary and are omitted; compaction entries surface as audit.
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
 */
export function normalizeEntries(entries: readonly SessionEntry[], runId: string): HephaestusEvent[] {
  const events: HephaestusEvent[] = [];
  let seq = 0;
  const emit = (kind: EventKind, payload: JsonValue, toolCallId?: string): void => {
    events.push(makeEvent(runId, seq, kind, payload, toolCallId));
    seq += 1;
  };
  for (const entry of entries) {
    if (entry.type === "compaction") {
      emit("audit", { event: "compaction" });
      continue;
    }
    if (entry.type !== "message") continue;
    // entry.message is a Pi AgentMessage; read it via the structural adapter.
    const message = entry.message as unknown as PiMessage;
    if (message.role === "assistant") {
      for (const item of message.content) {
        if (item.type === "text") emit("text_delta", { text: item.text });
        else if (item.type === "thinking") emit("thought", { text: item.thinking });
        else if (item.type === "toolCall") emit("tool_call", { name: item.name, arguments: item.arguments as JsonValue }, item.id);
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
    // user messages: prompts, not public events — omitted.
  }
  return events;
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
  readonly cursor?: string;
}

export interface HistoryPage {
  readonly events: HephaestusEvent[];
  /** Opaque continuation token, or null when the frozen snapshot is exhausted. */
  readonly cursor: string | null;
  readonly done: boolean;
}

export interface HistoryPageOptions {
  readonly pageSize?: number;
}

/**
 * Page normalized events over a frozen high-water snapshot. The first call (no
 * cursor) freezes the high-water mark at the last current entry; later pages —
 * even after the session grew or the process restarted — reconstruct events only
 * up to that mark, so pagination never shifts under a concurrent writer.
 */
export function pageHistory(
  entries: readonly SessionEntry[],
  runId: string,
  request: HistoryPageRequest = {},
  options: HistoryPageOptions = {},
): HistoryPage {
  const pageSize = options.pageSize ?? HISTORY_PAGE_SIZE;
  if (entries.length === 0) {
    return { events: [], cursor: null, done: true };
  }

  let hw: string;
  let offset: number;
  if (request.cursor !== undefined) {
    const decoded = decodeCursor(request.cursor);
    hw = decoded.hw;
    offset = decoded.offset;
  } else {
    const last = entries[entries.length - 1];
    hw = last === undefined ? "" : last.id;
    offset = 0;
  }

  const hwIndex = entries.findIndex((e) => e.id === hw);
  // If the high-water entry is gone (should not happen for append-only logs),
  // fall back to the full frozen set we do have.
  const frozen = hwIndex >= 0 ? entries.slice(0, hwIndex + 1) : entries.slice();
  const all = normalizeEntries(frozen, runId);

  const page = all.slice(offset, offset + pageSize);
  const nextOffset = offset + page.length;
  const done = nextOffset >= all.length;
  return {
    events: page,
    cursor: done ? null : encodeCursor({ hw, offset: nextOffset }),
    done,
  };
}
