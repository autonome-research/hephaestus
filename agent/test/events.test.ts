import { describe, it, expect } from "vitest";
import {
  EventCoalescer,
  coalesceKey,
  isDroppable,
  EVENT_KINDS,
  type HephaestusEvent,
} from "../src/events.js";

function ev(partial: Partial<HephaestusEvent> & Pick<HephaestusEvent, "kind">): HephaestusEvent {
  return { runId: "r1", seq: 0, ...partial };
}

describe("event vocabulary", () => {
  it("marks only progress as droppable", () => {
    for (const k of EVENT_KINDS) {
      expect(isDroppable(k)).toBe(k === "progress");
    }
  });
  it("keys on (run_id, kind, tool_call_id) with a NUL separator", () => {
    expect(coalesceKey(ev({ kind: "progress", toolCallId: "tc1" }))).toBe("r1\u0000progress\u0000tc1");
    expect(coalesceKey(ev({ kind: "progress" }))).toBe("r1\u0000progress\u0000");
  });
});

describe("EventCoalescer", () => {
  it("coalesces progress deltas to the latest per key", () => {
    const c = new EventCoalescer();
    c.push(ev({ kind: "progress", toolCallId: "tc1", seq: 1, payload: { pct: 10 } }));
    const out = c.push(ev({ kind: "progress", toolCallId: "tc1", seq: 2, payload: { pct: 20 } }));
    expect(out.coalesced).toBe(true);
    const drained = c.drain();
    expect(drained).toHaveLength(1);
    expect(drained[0]!.payload).toEqual({ pct: 20 });
  });
  it("keeps distinct progress keys separate", () => {
    const c = new EventCoalescer();
    c.push(ev({ kind: "progress", toolCallId: "tc1" }));
    c.push(ev({ kind: "progress", toolCallId: "tc2" }));
    expect(c.size).toBe(2);
  });
  it("never coalesces durable events even with identical keys", () => {
    const c = new EventCoalescer();
    c.push(ev({ kind: "tool_result", toolCallId: "tc1", seq: 1 }));
    const out = c.push(ev({ kind: "tool_result", toolCallId: "tc1", seq: 2 }));
    expect(out.coalesced).toBe(false);
    expect(c.size).toBe(2);
  });
  it("preserves arrival order on drain", () => {
    const c = new EventCoalescer();
    c.push(ev({ kind: "tool_call", seq: 1 }));
    c.push(ev({ kind: "progress", toolCallId: "tc1", seq: 2 }));
    c.push(ev({ kind: "terminal", seq: 3 }));
    expect(c.drain().map((e) => e.seq)).toEqual([1, 2, 3]);
  });
  it("signals overflow only when the bound is exceeded after coalescing", () => {
    const c = new EventCoalescer(2);
    expect(c.push(ev({ kind: "audit", seq: 1 })).overflow).toBe(false);
    expect(c.push(ev({ kind: "audit", seq: 2 })).overflow).toBe(false);
    expect(c.push(ev({ kind: "audit", seq: 3 })).overflow).toBe(true);
  });
  it("coalescing keeps a run under the bound where distinct events would overflow", () => {
    const c = new EventCoalescer(2);
    c.push(ev({ kind: "progress", toolCallId: "tc1", seq: 1 }));
    c.push(ev({ kind: "progress", toolCallId: "tc1", seq: 2 }));
    const out = c.push(ev({ kind: "progress", toolCallId: "tc1", seq: 3 }));
    expect(out.overflow).toBe(false);
    expect(c.size).toBe(1);
  });
});
