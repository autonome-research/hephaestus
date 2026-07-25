import { describe, it, expect } from "vitest";
import type { SessionEntry } from "@earendil-works/pi-coding-agent";
import {
  normalizeEntries,
  pageHistory,
  decodeCursor,
  HISTORY_PAGE_SIZE,
} from "../../src/session/history.js";

// Minimal structural builders for Pi session entries (test-boundary shapes).
function assistantText(id: string, text: string): SessionEntry {
  return {
    type: "message",
    id,
    parentId: null,
    timestamp: "2026-07-24T00:00:00.000Z",
    message: { role: "assistant", content: [{ type: "text", text }] },
  } as unknown as SessionEntry;
}

function assistantToolCall(id: string, callId: string, name: string): SessionEntry {
  return {
    type: "message",
    id,
    parentId: null,
    timestamp: "2026-07-24T00:00:00.000Z",
    message: { role: "assistant", content: [{ type: "toolCall", id: callId, name, arguments: { x: 1 } }] },
  } as unknown as SessionEntry;
}

function toolResult(id: string, callId: string, name: string, withImage: boolean): SessionEntry {
  const content: unknown[] = [{ type: "text", text: "ok" }];
  if (withImage) content.push({ type: "image", mimeType: "image/png" });
  return {
    type: "message",
    id,
    parentId: null,
    timestamp: "2026-07-24T00:00:00.000Z",
    message: { role: "toolResult", toolCallId: callId, toolName: name, content },
  } as unknown as SessionEntry;
}

function userMsg(id: string): SessionEntry {
  return {
    type: "message",
    id,
    parentId: null,
    timestamp: "2026-07-24T00:00:00.000Z",
    message: { role: "user", content: "hi" },
  } as unknown as SessionEntry;
}

describe("normalization", () => {
  it("maps assistant/toolResult content to the public vocabulary; omits user prompts", () => {
    const entries = [
      userMsg("u0"),
      assistantToolCall("a1", "call_0", "inspect_part"),
      toolResult("r1", "call_0", "inspect_part", true),
      assistantText("a2", "done"),
    ];
    const events = normalizeEntries(entries, "run-1");
    expect(events.map((e) => e.kind)).toEqual(["tool_call", "tool_result", "image", "text_delta"]);
    expect(events[0]?.toolCallId).toBe("call_0");
    expect(events[2]?.kind).toBe("image");
    expect(events[2]?.toolCallId).toBe("call_0");
    // seq is dense and ordered.
    expect(events.map((e) => e.seq)).toEqual([0, 1, 2, 3]);
    expect(events.every((e) => e.runId === "run-1")).toBe(true);
  });

  it("is deterministic across repeated calls (restart-stable)", () => {
    const entries = [assistantText("a1", "one"), assistantText("a2", "two")];
    expect(normalizeEntries(entries, "r")).toEqual(normalizeEntries(entries, "r"));
  });
});

describe("cursor paging over a frozen high-water mark", () => {
  const initial = Array.from({ length: 5 }, (_, i) => assistantText(`e${i}`, `t${i}`));

  it("empty history is done immediately", () => {
    expect(pageHistory([], "r")).toEqual({ events: [], cursor: null, done: true });
  });

  it("freezes the high-water at the first page and never crosses it as the log grows", () => {
    const p1 = pageHistory(initial, "r", {}, { pageSize: 2 });
    expect(p1.events.map((e) => e.seq)).toEqual([0, 1]);
    expect(p1.done).toBe(false);
    expect(p1.cursor).not.toBeNull();

    // Log grows by 3 entries before the next page is requested.
    const grown = [...initial, assistantText("e5", "t5"), assistantText("e6", "t6"), assistantText("e7", "t7")];
    const p2 = pageHistory(grown, "r", { cursor: p1.cursor ?? undefined }, { pageSize: 2 });
    expect(p2.events.map((e) => e.seq)).toEqual([2, 3]);

    const p3 = pageHistory(grown, "r", { cursor: p2.cursor ?? undefined }, { pageSize: 2 });
    expect(p3.events.map((e) => e.seq)).toEqual([4]);
    expect(p3.done).toBe(true);
    expect(p3.cursor).toBeNull();

    // Total events delivered == the 5 that existed when the cursor was frozen —
    // the 3 later entries never appear.
    const decoded = decodeCursor(p1.cursor ?? "");
    expect(decoded.hw).toBe("e4");
  });

  it("reconstructs identical pages after a manager restart", () => {
    // "Restart": a fresh pass with the same cursor and the same underlying log.
    const first = pageHistory(initial, "r", {}, { pageSize: 3 });
    const firstAgain = pageHistory(initial, "r", {}, { pageSize: 3 });
    expect(firstAgain).toEqual(first);
    const cont = pageHistory(initial, "r", { cursor: first.cursor ?? undefined }, { pageSize: 3 });
    expect(cont.events.map((e) => e.seq)).toEqual([3, 4]);
    expect(cont.done).toBe(true);
  });

  it("has a sane default page size", () => {
    expect(HISTORY_PAGE_SIZE).toBeGreaterThan(0);
  });

  it("rejects a malformed cursor", () => {
    expect(() => pageHistory(initial, "r", { cursor: "!!!not-base64!!!" })).toThrow();
  });
});
