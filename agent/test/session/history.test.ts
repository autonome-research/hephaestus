import { describe, it, expect } from "vitest";
import type { SessionEntry } from "@earendil-works/pi-coding-agent";
import {
  normalizeEntries,
  extractUserPrompts,
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

/** A `toolResult` entry with an explicit envelope text and optional `isError`. */
function toolResultWith(
  id: string,
  text: string,
  isError?: boolean,
): SessionEntry {
  const message: Record<string, unknown> = {
    role: "toolResult",
    toolCallId: "call_0",
    toolName: "build_part",
    content: [{ type: "text", text }],
  };
  if (isError !== undefined) message.isError = isError;
  return {
    type: "message",
    id,
    parentId: null,
    timestamp: "2026-07-24T00:00:00.000Z",
    message,
  } as unknown as SessionEntry;
}

function userMsg(id: string, text = "hi"): SessionEntry {
  return {
    type: "message",
    id,
    parentId: null,
    timestamp: "2026-07-24T00:00:00.000Z",
    message: { role: "user", content: text },
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

  // INTERFACE.md §7.2 / §19 item 13. Before this, `normalizeEntries` emitted
  // `{toolName, text}` with no `isError`, so a REOPENED transcript rendered
  // every failed tool call as `ok` — a silently-dropped state. The fix lands in
  // the engine before the G4.11 event archive is baselined, so the archive
  // records the corrected shape and is not re-baselined a stage later.
  describe("tool_result carries isError (§7.2)", () => {
    function isErrorOf(entry: SessionEntry): unknown {
      const events = normalizeEntries([entry], "sess-1");
      const result = events.find((e) => e.kind === "tool_result");
      return (result?.payload as { isError?: unknown } | undefined)?.isError;
    }

    it("reads Pi's own toolResult.isError when the entry carries it", () => {
      expect(isErrorOf(toolResultWith("r1", '{"status":"ok"}', false))).toBe(false);
      expect(isErrorOf(toolResultWith("r2", "boom", true))).toBe(true);
    });

    it("a failed call is never reported as ok — Pi's flag wins over the envelope", () => {
      // The envelope says ok and Pi says the call failed: Pi is the authority.
      expect(isErrorOf(toolResultWith("r3", '{"status":"ok"}', true))).toBe(true);
    });

    it("falls back to the serialized envelope status on a legacy entry", () => {
      expect(isErrorOf(toolResultWith("r4", '{"status":"error","reason":"invalid_part"}'))).toBe(true);
      expect(isErrorOf(toolResultWith("r5", '{"status":"ok","artifact_ref":"a"}'))).toBe(false);
      // A discriminated *successful* result is not an error, per tool_schema.md.
      expect(isErrorOf(toolResultWith("r6", '{"status":"capability_error","code":"x"}'))).toBe(false);
      expect(isErrorOf(toolResultWith("r7", '{"status":"conflict"}'))).toBe(false);
    });

    it("is null — never false — when neither source records the outcome", () => {
      // §7.2's named fallback: the closed set gains a VISIBLE `unknown`. The one
      // thing this must never be is `false`, which reads as a successful call.
      expect(isErrorOf(toolResultWith("r8", "not json at all"))).toBeNull();
      expect(isErrorOf(toolResultWith("r9", '{"no_status":true}'))).toBeNull();
      expect(isErrorOf(toolResultWith("r10", "[1,2,3]"))).toBeNull();
    });
  });

  // INTERFACE.md §2.8: the historical identity is (session_id, ordinal). The
  // parameter is named `runId` and is fed the SESSION id by main.ts's
  // history.page handler; the ordinal restarts at 0 per session. Nothing here
  // reconstructs a live (run_id, seq) pair, and the two are never merged.
  it("mints the session-scoped identity, restarting the ordinal at 0", () => {
    const events = normalizeEntries(
      [assistantText("a1", "one"), assistantText("a2", "two")],
      "sess-42",
    );
    expect(events.every((e) => e.runId === "sess-42")).toBe(true);
    expect(events.map((e) => e.seq)).toEqual([0, 1]);
    // A second session's page restarts at 0 with its own id — the ordinals of
    // two sessions collide, which is exactly why the namespace is the pair.
    const other = normalizeEntries([assistantText("b1", "x")], "sess-43");
    expect(other[0]?.seq).toBe(0);
    expect(other[0]?.runId).toBe("sess-43");
  });

  it("is deterministic across repeated calls (restart-stable)", () => {
    const entries = [assistantText("a1", "one"), assistantText("a2", "two")];
    expect(normalizeEntries(entries, "r")).toEqual(normalizeEntries(entries, "r"));
  });
});

describe("cursor paging over a frozen high-water mark", () => {
  const initial = Array.from({ length: 5 }, (_, i) => assistantText(`e${i}`, `t${i}`));

  it("empty history is done immediately", () => {
    expect(pageHistory([], "r")).toEqual({ events: [], userPrompts: [], cursor: null, done: true });
  });

  it("carries operator prompts beside the page without shifting event seqs", () => {
    const entries = [
      userMsg("u0", "Add a 2 mm chamfer."),
      assistantText("a1", "done"),
    ];
    expect(extractUserPrompts(entries)).toEqual([{ seq: 0, text: "Add a 2 mm chamfer." }]);
    const page = pageHistory(entries, "sess-1");
    expect(page.events.map((e) => e.kind)).toEqual(["text_delta"]);
    expect(page.events[0]?.seq).toBe(0);
    expect(page.userPrompts).toEqual([{ seq: 0, text: "Add a 2 mm chamfer." }]);
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
