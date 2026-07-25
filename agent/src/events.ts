// Normalized Hephaestus event vocabulary + coalescing (architecture §5).
//
// Pi's provider-specific events are normalized into this stable vocabulary before
// any CLI/MCP/web client sees them. Every event carries a run_id. Only explicitly
// droppable "progress" deltas are coalesced — to the latest event per key
// (run_id, event_kind, tool_call_id). Audit events, tool calls/results,
// questions/answers, and terminals are NEVER coalesced or dropped.

import { BUFFERED_EVENTS_MAX } from "./limits.js";
import type { JsonValue } from "./framing.js";

export type EventKind =
  | "text_delta"
  | "thought"
  | "tool_call"
  | "tool_result"
  | "image"
  | "question"
  | "answer"
  | "audit"
  | "progress"
  | "terminal";

export const EVENT_KINDS: readonly EventKind[] = [
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
];

// Only progress deltas are droppable/coalesceable; everything else is durable.
const DROPPABLE: ReadonlySet<EventKind> = new Set<EventKind>(["progress"]);

export interface HephaestusEvent {
  readonly runId: string;
  readonly seq: number;
  readonly kind: EventKind;
  readonly toolCallId?: string;
  readonly payload?: JsonValue;
}

export function isDroppable(kind: EventKind): boolean {
  return DROPPABLE.has(kind);
}

const KEY_SEP = "\u0000";

/** Coalescing key: (run_id, event_kind, tool_call_id). */
export function coalesceKey(ev: HephaestusEvent): string {
  return ev.runId + KEY_SEP + ev.kind + KEY_SEP + (ev.toolCallId ?? "");
}

export interface PushOutcome {
  readonly buffered: number;
  readonly coalesced: boolean;
  readonly overflow: boolean;
}

/**
 * Bounded coalescing buffer. Progress events collapse to the latest per key;
 * durable events always append. `overflow` reports that the bound (1024 ordinary
 * buffered events) is still exceeded after coalescing — the signal the event
 * pump uses to backpressure-cancel the affected run and route its final error
 * through the terminal channel.
 */
export class EventCoalescer {
  private readonly order: HephaestusEvent[] = [];
  private readonly progressIndex = new Map<string, number>();

  constructor(private readonly bound: number = BUFFERED_EVENTS_MAX) {}

  push(ev: HephaestusEvent): PushOutcome {
    let coalesced = false;
    if (isDroppable(ev.kind)) {
      const key = coalesceKey(ev);
      const existing = this.progressIndex.get(key);
      if (existing !== undefined) {
        this.order[existing] = ev;
        coalesced = true;
      } else {
        this.progressIndex.set(key, this.order.length);
        this.order.push(ev);
      }
    } else {
      this.order.push(ev);
    }
    return {
      buffered: this.order.length,
      coalesced,
      overflow: this.order.length > this.bound,
    };
  }

  get size(): number {
    return this.order.length;
  }

  /** Return buffered events in arrival order and reset the buffer. */
  drain(): HephaestusEvent[] {
    const out = this.order.slice();
    this.order.length = 0;
    this.progressIndex.clear();
    return out;
  }
}
