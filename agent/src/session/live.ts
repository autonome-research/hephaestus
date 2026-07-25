// Live Pi session events -> the normalized Hephaestus event vocabulary.
//
// `history.ts` normalizes *persisted* session entries; this module normalizes the
// *streaming* `AgentSession.subscribe` events so a client sees the same public
// vocabulary while a run is in flight (STAGE2_DIGEST §1 "Event normalization":
// Pi session formats and provider-specific events never become public API).
//
// Why not `entry_appended`: that AgentSession event fires only for extension
// custom entries (`ExtensionAPI.appendEntry`), never for ordinary assistant /
// toolResult messages — subscribing to it yields an empty live stream. The
// streaming surface is `message_update` (assistant text/thinking deltas),
// `tool_execution_{start,update,end}`, and the compaction pair.
//
// Payload keys deliberately mirror `history.ts` so a client can render a live
// stream and a `history.page` replay with one renderer.

import type { AgentSessionEvent } from "@earendil-works/pi-coding-agent";
import type { HephaestusEvent } from "../events.js";
import type { JsonValue } from "../framing.js";

// The Pi assistant-stream event and tool-result shapes are not exported by name
// from the SDK barrel, so they are read structurally. Every `unknown` narrowing
// for the Pi boundary lives in this file (see also history.ts).
interface AssistantStreamEvent {
  readonly type: string;
  readonly delta?: string;
  readonly toolCall?: { readonly id?: string; readonly name?: string; readonly arguments?: unknown };
}

interface ToolResultImage {
  readonly type: "image";
  readonly data?: string;
  readonly mimeType?: string;
}
interface ToolResultText {
  readonly type: "text";
  readonly text?: string;
}
type ToolResultContent = ToolResultImage | ToolResultText | { readonly type: string };

interface ToolResultLike {
  readonly content?: readonly ToolResultContent[];
  readonly details?: unknown;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

/** Best-effort JSON projection of arbitrary tool arguments (never throws). */
function toJson(value: unknown): JsonValue {
  if (value === undefined) return null;
  try {
    return JSON.parse(JSON.stringify(value)) as JsonValue;
  } catch {
    return null;
  }
}

/**
 * Normalize one live Pi session event into zero or more Hephaestus events.
 *
 * `nextSeq` supplies the run-monotonic sequence number, so a caller can
 * interleave synthetic events (question/answer, audit) into the same counter.
 * Events with no public meaning (agent/turn/message lifecycle, queue updates,
 * retries) normalize to an empty list rather than leaking Pi vocabulary.
 */
export function normalizeLiveEvent(
  event: AgentSessionEvent,
  runId: string,
  nextSeq: () => number,
): HephaestusEvent[] {
  const out: HephaestusEvent[] = [];
  const emit = (kind: HephaestusEvent["kind"], payload: JsonValue, toolCallId?: string): void => {
    out.push(
      toolCallId !== undefined
        ? { runId, seq: nextSeq(), kind, toolCallId, payload }
        : { runId, seq: nextSeq(), kind, payload },
    );
  };

  switch (event.type) {
    case "message_update": {
      const stream = event.assistantMessageEvent as unknown as AssistantStreamEvent;
      if (stream.type === "text_delta" && typeof stream.delta === "string" && stream.delta !== "") {
        emit("text_delta", { text: stream.delta });
      } else if (
        stream.type === "thinking_delta" &&
        typeof stream.delta === "string" &&
        stream.delta !== ""
      ) {
        emit("thought", { text: stream.delta });
      }
      // toolcall_end is NOT emitted here: tool_execution_start carries the same
      // call with its resolved arguments, so emitting both would duplicate.
      return out;
    }
    case "tool_execution_start": {
      emit("tool_call", { name: event.toolName, arguments: toJson(event.args) }, event.toolCallId);
      return out;
    }
    case "tool_execution_update": {
      // Droppable/coalescible by (run_id, kind, tool_call_id) — see events.ts.
      emit("progress", { toolName: event.toolName }, event.toolCallId);
      return out;
    }
    case "tool_execution_end": {
      const result = (isRecord(event.result) ? event.result : {}) as ToolResultLike;
      const content = result.content ?? [];
      const text = content
        .filter((c): c is ToolResultText => c.type === "text")
        .map((c) => c.text ?? "")
        .join("");
      emit(
        "tool_result",
        { toolName: event.toolName, text, isError: event.isError },
        event.toolCallId,
      );
      for (const item of content) {
        if (item.type !== "image") continue;
        const image = item as ToolResultImage;
        const data = typeof image.data === "string" ? image.data : "";
        emit(
          "image",
          {
            mimeType: image.mimeType ?? "image/png",
            bytes: Buffer.byteLength(data, "base64"),
            data,
          },
          event.toolCallId,
        );
      }
      return out;
    }
    case "compaction_start": {
      emit("audit", { event: "compaction_start", reason: event.reason });
      return out;
    }
    case "compaction_end": {
      emit("audit", {
        event: "compaction_end",
        reason: event.reason,
        aborted: event.aborted,
      });
      return out;
    }
    default:
      return out;
  }
}

/** Wire form of a normalized event (snake_case envelope, camelCase payload). */
export function wireEvent(ev: HephaestusEvent): { [k: string]: JsonValue } {
  const frame: { [k: string]: JsonValue } = { run_id: ev.runId, seq: ev.seq, kind: ev.kind };
  if (ev.toolCallId !== undefined) frame.tool_call_id = ev.toolCallId;
  if (ev.payload !== undefined) frame.payload = ev.payload;
  return frame;
}
