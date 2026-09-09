import { describe, it, expect } from "vitest";
import type { SessionEntry } from "@earendil-works/pi-coding-agent";
import {
  normalizeEntries,
  extractUserPrompts,
  pageHistory,
  decodeCursor,
  encodeCursor,
  HISTORY_PAGE_SIZE,
  MalformedCursorError,
} from "../../src/session/history.js";
import type { HistoryPageRequest } from "../../src/session/history.js";

/** Continue from a cursor the caller has just proven is present.
 *
 * `HistoryPageRequest.cursor` is `?: string` under `exactOptionalPropertyTypes`,
 * so `{ cursor: page.cursor ?? undefined }` does not type-check — and the
 * coalescing form was silently weaker anyway: a null cursor would have
 * requested a FIRST page and the assertion below would then have compared the
 * wrong page. Failing by name here says which page had no cursor.
 */
function from(cursor: string | null): HistoryPageRequest {
  if (cursor === null) throw new Error("expected a continuation cursor, got null");
  return { cursor };
}

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
    // §2.8(5): `endCursor` is ALWAYS present, never null, even on an empty page.
    expect(pageHistory([], "r")).toEqual({
      events: [],
      userPrompts: [],
      cursor: null,
      done: true,
      endCursor: expect.any(String),
    });
  });

  it("carries operator prompts beside the page without shifting event seqs", () => {
    const entries = [
      userMsg("u0", "Add a 2 mm chamfer."),
      assistantText("a1", "done"),
    ];
    // §2.8(2)/(3): `turn` is the identity now, and a marker-less prompt's
    // `envelope` is null (today's legacy fallback, verbatim).
    expect(extractUserPrompts(entries)).toEqual([
      { turn: 0, seq: 0, text: "Add a 2 mm chamfer.", envelope: null },
    ]);
    const page = pageHistory(entries, "sess-1");
    expect(page.events.map((e) => e.kind)).toEqual(["text_delta"]);
    expect(page.events[0]?.seq).toBe(0);
    expect(page.userPrompts).toEqual([{ turn: 0, seq: 0, text: "Add a 2 mm chamfer.", envelope: null }]);
  });

  it("freezes the high-water at the first page and never crosses it as the log grows", () => {
    const p1 = pageHistory(initial, "r", {}, { pageSize: 2 });
    expect(p1.events.map((e) => e.seq)).toEqual([0, 1]);
    expect(p1.done).toBe(false);
    expect(p1.cursor).not.toBeNull();

    // Log grows by 3 entries before the next page is requested.
    const grown = [...initial, assistantText("e5", "t5"), assistantText("e6", "t6"), assistantText("e7", "t7")];
    const p2 = pageHistory(grown, "r", from(p1.cursor), { pageSize: 2 });
    expect(p2.events.map((e) => e.seq)).toEqual([2, 3]);

    const p3 = pageHistory(grown, "r", from(p2.cursor), { pageSize: 2 });
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
    const cont = pageHistory(initial, "r", from(first.cursor), { pageSize: 3 });
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

// --------------------------------------------------------------------------
// B-11(a): a malformed cursor is a NAMED error, not a plain `Error`.
//
// `rpc.ts`'s catch turns any thrown value that is not an `RpcError` into a
// bare JSON-RPC internal error (-32603), which the HTTP layer could not tell
// apart from "the sidecar stopped answering" — a `%%%` cursor was reported as
// `503 agent_unavailable` while the very next history call returned 200.
// `main.ts` catches `MalformedCursorError` specifically and re-throws it as an
// `RpcError` carrying `data: {reason: "invalid_cursor"}`; these tests pin the
// decoder's half of that contract — the named class, not merely "throws" —
// independent of `main.ts` or a built sidecar.
describe("a malformed cursor is a named error (B-11a)", () => {
  it("is thrown for a non-base64-shaped token", () => {
    expect(() => decodeCursor("%%%")).toThrow(MalformedCursorError);
  });

  it("is thrown for a well-formed-base64 payload that is not JSON", () => {
    const notJson = Buffer.from("not json at all", "utf8").toString("base64url");
    expect(() => decodeCursor(notJson)).toThrow(MalformedCursorError);
  });

  it("is thrown when the high-water mark is missing", () => {
    const missingMark = Buffer.from(JSON.stringify({ offset: 3 }), "utf8").toString("base64url");
    expect(() => decodeCursor(missingMark)).toThrow(MalformedCursorError);
  });

  it("is thrown for a non-integer offset", () => {
    const nonInteger = Buffer.from(JSON.stringify({ hw: "e1", offset: 1.5 }), "utf8").toString(
      "base64url",
    );
    expect(() => decodeCursor(nonInteger)).toThrow(MalformedCursorError);
  });

  it("is thrown for a negative offset", () => {
    const negative = Buffer.from(JSON.stringify({ hw: "e1", offset: -1 }), "utf8").toString(
      "base64url",
    );
    expect(() => decodeCursor(negative)).toThrow(MalformedCursorError);
  });

  it("is thrown (not a plain Error) for the mutually-exclusive cursor/after pair", () => {
    // `pageHistory` throws this one itself, from the same named class, so a
    // client cannot tell the two `invalid_cursor` causes apart by error type —
    // only §2.4's envelope (and its message) distinguishes them.
    const initial: SessionEntry[] = [];
    const cursor = encodeCursor({ hw: "e0", offset: 0 });
    expect(() => pageHistory(initial, "r", { cursor, after: cursor })).toThrow(
      MalformedCursorError,
    );
  });

  it("decodes a well-formed cursor without throwing", () => {
    // The positive case, so the named refusal is not over-tightened: a real
    // cursor this module minted still round-trips.
    const token = encodeCursor({ hw: "e4", offset: 2 });
    expect(decodeCursor(token)).toEqual({ hw: "e4", offset: 2 });
  });
});

// --------------------------------------------------------------------------
// J-http-envelope-9: a cursor naming an unknown mark reads as a complete,
// empty history.
//
// `pageHistory` widened the frozen snapshot to the WHOLE log whenever the
// cursor's `hw` named no entry ("should not happen for append-only logs"),
// then a slice past the end silently produced an empty, `done: true` page —
// the same shape a genuinely exhausted, quiet session returns. A client
// walking history could not tell "you reached the end" from "your cursor is
// nonsense over a 250-event session" and rendered the latter as the former.
//
// The fix must draw three distinct lines the code currently draws as one:
//   1. a mark absent from a NON-EMPTY log is a malformed cursor (refused);
//   2. an offset STRICTLY BEYOND the frozen snapshot's length is a client
//      error (refused) — distinct from...
//   3. ...an offset EQUAL to the snapshot's length, which is the legitimate
//      "you are caught up" quiet-tail case and must stay a plain 200.
// The empty-mark-over-an-empty-log case (the sidecar's own minted cursor for
// a session with no history yet) must keep working throughout.
describe("a cursor naming an unknown mark (J-http-envelope-9)", () => {
  const entries = Array.from({ length: 5 }, (_, i) => assistantText(`e${i}`, `t${i}`));

  it("is refused — not read as an exhausted walk — over a non-empty log", () => {
    // `zzz` names no entry in `entries`: today this silently widens to the
    // whole frozen log and returns an empty, done:true page instead of
    // throwing. A client cannot distinguish that from a genuinely quiet tail.
    const bogus = encodeCursor({ hw: "zzz", offset: 0 });
    expect(() => pageHistory(entries, "r", { cursor: bogus })).toThrow(MalformedCursorError);
  });

  it("proves the events were there all along: an unqualified read still returns them", () => {
    // Same log, no cursor: the full transcript comes back. This is the
    // end-to-end half of the ledger's ask — the bogus mark was never a "the
    // session is empty" situation, only a malformed request.
    const bogus = encodeCursor({ hw: "zzz", offset: 0 });
    expect(() => pageHistory(entries, "r", { cursor: bogus })).toThrow(MalformedCursorError);
    const full = pageHistory(entries, "r");
    expect(full.events).toHaveLength(5);
    expect(full.done).toBe(true);
  });

  it("still works for the empty mark over a genuinely empty session", () => {
    // The sidecar's own minted cursor for a brand-new session: hw="" over
    // entries=[]. This must NOT be treated as "unknown mark" — there is no
    // entry to have named, and the empty-history short-circuit already
    // handles it correctly.
    const emptyMark = encodeCursor({ hw: "", offset: 0 });
    const page = pageHistory([], "r", { cursor: emptyMark });
    expect(page).toEqual({
      events: [],
      userPrompts: [],
      cursor: null,
      done: true,
      endCursor: expect.any(String),
    });
  });

  it("an offset strictly beyond the frozen snapshot's length is refused", () => {
    // "e4" is a real, current mark — the snapshot it names has exactly 5
    // events (offsets 0..5 valid as page starts). offset=6 names a position
    // past the end of a snapshot that unambiguously has an end.
    const pastEnd = encodeCursor({ hw: "e4", offset: 6 });
    expect(() => pageHistory(entries, "r", { cursor: pastEnd })).toThrow(MalformedCursorError);
  });

  it("an offset EQUAL to the frozen snapshot's length stays the legitimate done case", () => {
    // The boundary the fix must not break: offset === length is "you are
    // caught up", not an error — same contract as today, pinned so the
    // strictly-greater fix does not overreach by one.
    const atEnd = encodeCursor({ hw: "e4", offset: 5 });
    const page = pageHistory(entries, "r", { cursor: atEnd });
    expect(page).toEqual({
      events: [],
      userPrompts: [],
      cursor: null,
      done: true,
      endCursor: expect.any(String),
    });
  });

  it("the polling contract survives: a valid tail token at the exact end is byte-identical", () => {
    // The explicit regression the ledger's fix must not break: a quiet
    // session's poll returns the SAME end cursor back, unchanged.
    const first = pageHistory(entries, "r", {}, { pageSize: 10 });
    expect(first.done).toBe(true);
    expect(first.endCursor).toEqual(expect.any(String));

    const second = pageHistory(entries, "r", { after: first.endCursor });
    expect(second.events).toEqual([]);
    expect(second.done).toBe(true);
    expect(second.endCursor).toBe(first.endCursor);
  });
});
