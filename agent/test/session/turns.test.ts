// INTERFACE.md §2.8 (amended 2026-09-03): the turn-record contract.
//
// Written against the PUBLISHED CONTRACT, before the implementation lands —
// these are expected to be RED until `normalizeEntries` / `extractUserPrompts`
// / `pageHistory` grow `turn`, the sentence/envelope split, `outcome`, and the
// `after` tail read. See INTERFACE.md:1112-1315 for the full clause set and
// the round-0 handoff notes for exactly which lines each case pins.
//
// Structural builders mirror history.test.ts's style: Pi session entries are
// built by hand for every case that does not need a real model turn. Case (h)
// (restart-stability) drives a real FakeModel-backed SessionService, because
// that is the only way to exercise the marker surviving an actual JSONL
// round-trip rather than an in-memory array reused twice.
import { describe, it, expect, afterEach } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import type { SessionEntry } from "@earendil-works/pi-coding-agent";
import {
  normalizeEntries,
  extractUserPrompts,
  pageHistory,
  decodeCursor,
} from "../../src/session/history.js";
import { wireEvent } from "../../src/session/live.js";
import { FakeModel, createModelRuntime, type FakeTurnResolver } from "../../src/session/runtime.js";
import { SessionService } from "../../src/session/manager.js";

const TS = "2026-09-03T00:00:00.000Z";

function userMsg(id: string, content: unknown = "hi"): SessionEntry {
  return {
    type: "message",
    id,
    parentId: null,
    timestamp: TS,
    message: { role: "user", content },
  } as unknown as SessionEntry;
}

function assistantText(id: string, text: string): SessionEntry {
  return {
    type: "message",
    id,
    parentId: null,
    timestamp: TS,
    message: { role: "assistant", content: [{ type: "text", text }] },
  } as unknown as SessionEntry;
}

/** An assistant entry carrying Pi's own `stopReason`/`errorMessage` (outcome source (i)). */
function assistantWithStop(id: string, stopReason: string, errorMessage?: string): SessionEntry {
  const content = stopReason === "stop" ? [{ type: "text", text: "ok" }] : [];
  const message: Record<string, unknown> = { role: "assistant", content, stopReason };
  if (errorMessage !== undefined) message.errorMessage = errorMessage;
  return { type: "message", id, parentId: null, timestamp: TS, message } as unknown as SessionEntry;
}

function assistantThinking(id: string, thinking: string): SessionEntry {
  return {
    type: "message",
    id,
    parentId: null,
    timestamp: TS,
    message: { role: "assistant", content: [{ type: "thinking", thinking }] },
  } as unknown as SessionEntry;
}

/** `hephaestus.turn.v1` / `hephaestus.turn_outcome.v1` — sidecar-appended CustomEntry (§2.8(3)/(8)). */
function customEntry(id: string, customType: string, data: unknown): SessionEntry {
  return { type: "custom", id, parentId: null, timestamp: TS, customType, data } as unknown as SessionEntry;
}

function turnOf(event: unknown): unknown {
  return (event as { turn?: unknown }).turn;
}

describe("turn ordinal on events (§2.8(1))", () => {
  it("(a) three user+assistant turns yield three distinct, matching turn ordinals", () => {
    const entries = [
      userMsg("u0", "first"),
      assistantText("a1", "reply one"),
      userMsg("u1", "second"),
      assistantText("a2", "reply two"),
      userMsg("u2", "third"),
      assistantText("a3", "reply three"),
    ];
    const prompts = extractUserPrompts(entries);
    expect(prompts.map((p) => p.turn)).toEqual([0, 1, 2]);
    // Strictly increasing and unique — THE identity per the contract.
    expect(new Set(prompts.map((p) => p.turn)).size).toBe(3);

    const events = normalizeEntries(entries, "sess-3turn");
    expect(events).toHaveLength(3);
    expect(events.map(turnOf)).toEqual([0, 1, 2]);

    // Also true through the paging boundary a client actually reads.
    const page = pageHistory(entries, "sess-3turn");
    expect(page.events.map(turnOf)).toEqual([0, 1, 2]);
  });

  it("events recorded before the first user message carry turn: null, not -1 or 0", () => {
    const entries = [customEntry("c0", "audit.something", {}), assistantText("a0", "prologue")];
    const events = normalizeEntries(entries, "sess-prologue");
    // The custom entry itself never becomes an event; the lone assistant entry
    // precedes any user message, so it is prologue.
    expect(events).toHaveLength(1);
    expect(turnOf(events[0])).toBeNull();
  });
});

describe("distinct prompt entries (§2.8(2))", () => {
  it("(b) two consecutive user messages with nothing between them are two entries, not one", () => {
    const entries = [userMsg("u0", "first"), userMsg("u1", "second"), assistantText("a1", "reply")];
    const prompts = extractUserPrompts(entries);
    expect(prompts).toHaveLength(2);
    expect(prompts[0]).toMatchObject({ turn: 0, text: "first" });
    expect(prompts[1]).toMatchObject({ turn: 1, text: "second" });
    // `turn` distinguishes them even though `seq` — the ordinal of each turn's
    // FIRST event — collides: neither turn has an event yet when the second
    // prompt lands, so both point at the same next-event ordinal. This is the
    // exact case the spec calls out: seq is explicitly not unique, and the old
    // `@prompt:<seq>` identity would have collided here.
    expect(prompts[0].seq).toBe(prompts[1].seq);
    expect(prompts[0].turn).not.toBe(prompts[1].turn);

    // The lone reply belongs to the most recent turn.
    const events = normalizeEntries(entries, "sess-consec");
    expect(turnOf(events[0])).toBe(1);
  });

  it("(c) a user message with no text part still yields one entry with text: null", () => {
    const entries = [userMsg("u0", [{ type: "image", mimeType: "image/png" }]), assistantText("a1", "ok")];
    const prompts = extractUserPrompts(entries);
    // Today's `extractUserPrompts` silently DROPS a textless user message
    // (history.ts:214-215) — this assertion is exactly what closes that gap.
    expect(prompts).toHaveLength(1);
    expect(prompts[0]?.turn).toBe(0);
    expect(prompts[0]?.text).toBeNull();

    // The event after it still belongs to turn 0 — the turn happened, even
    // though nothing recoverable was typed.
    const events = normalizeEntries(entries, "sess-textless");
    expect(turnOf(events[0])).toBe(0);
  });

  it("every user message yields exactly one entry across a longer mixed session", () => {
    const entries = [
      userMsg("u0", "a"),
      userMsg("u1", [{ type: "image", mimeType: "image/png" }]),
      assistantText("a1", "reply"),
      userMsg("u2", "b"),
    ];
    const prompts = extractUserPrompts(entries);
    expect(prompts.map((p) => p.turn)).toEqual([0, 1, 2]);
  });
});

describe("sentence/envelope separation (§2.8(3))", () => {
  it("(d) a context-carrying turn restores the operator's sentence byte-for-byte, envelope separate", () => {
    const envelope = "# Workspace context\nfoo=bar\nbaz=qux";
    const sentence = "Add a 2 mm chamfer.";
    const entries = [
      customEntry("m0", "hephaestus.turn.v1", { turn: 0, text: sentence, envelope }),
      // Pi joins a content array's text parts with "\n" (INTERFACE.md §7A.4's
      // documented DEVIATION) — the persisted entry is what the marker exists
      // to see behind.
      userMsg("u0", `${envelope}\n${sentence}`),
      assistantText("a1", "done"),
    ];
    const prompts = extractUserPrompts(entries);
    expect(prompts).toHaveLength(1);
    expect(prompts[0]).toEqual({ turn: 0, seq: 0, text: sentence, envelope });
    // Byte-for-byte: no trimming, no re-derivation from the fused string.
    expect(prompts[0]?.text).toBe(sentence);
    expect(prompts[0]?.envelope).toBe(envelope);

    // The marker is neither `message` nor `compaction`; it must not shift any
    // seq — mirrors item 5's own required test.
    const events = normalizeEntries(entries, "sess-envelope");
    expect(events.map((e) => e.seq)).toEqual([0]);
  });

  it("the retry's own continuation sentence is attributed to the agent, not the operator", () => {
    // §2.8(3), amended 2026-09-03: the single transient retry re-prompts with a
    // sentence THIS sidecar wrote (session/retry.ts). Pi persists it as an
    // ordinary user message; its marker carries `origin: "agent"` so the record
    // never puts a machine's sentence in the operator's mouth. It is still a
    // turn — exactly one entry — and an operator marker (no `origin`) is
    // projected with the field ABSENT, so every pre-existing marker keeps its
    // meaning.
    const entries = [
      customEntry("m0", "hephaestus.turn.v1", { turn: 0, text: "Add a chamfer.", envelope: null }),
      userMsg("u0", "Add a chamfer."),
      assistantWithStop("a1", "error", "WebSocket error"),
      customEntry("m1", "hephaestus.turn.v1", {
        turn: 1,
        text: "Your previous turn failed with a transient provider error; continue.",
        envelope: null,
        origin: "agent",
      }),
      userMsg("u1", "Your previous turn failed with a transient provider error; continue."),
      assistantText("a2", "done"),
    ];
    const prompts = extractUserPrompts(entries);
    expect(prompts).toHaveLength(2);
    expect(prompts[0]).not.toHaveProperty("origin");
    expect(prompts[1]?.origin).toBe("agent");
    expect(prompts[1]?.turn).toBe(1);
    // An unknown origin value is read as the operator, never as a third party.
    const odd = [
      customEntry("m0", "hephaestus.turn.v1", { turn: 0, text: "x", envelope: null, origin: "elsewhere" }),
      userMsg("u0", "x"),
    ];
    expect(extractUserPrompts(odd)[0]).not.toHaveProperty("origin");
  });

  it("a marker with no following user message changes nothing (defensive)", () => {
    const entries = [customEntry("m0", "hephaestus.turn.v1", { turn: 0, text: "x", envelope: null }), assistantText("a1", "y")];
    // No user message at all: no prompt is recorded, and the assistant entry
    // is prologue (turn: null) since it precedes the (never-arriving) first
    // user message.
    expect(extractUserPrompts(entries)).toEqual([]);
    const events = normalizeEntries(entries, "sess-orphan-marker");
    expect(turnOf(events[0])).toBeNull();
  });
});

describe("legacy fallback, per turn not per session (§2.8(3), item 6)", () => {
  it("(e) a legacy session without markers still pages, joined text, turns derived by counting", () => {
    const fused = "# Workspace context\nfoo=bar\nDo the thing.";
    const entries = [
      userMsg("u0", fused),
      assistantText("a1", "ok"),
      userMsg("u1", "second legacy prompt"),
      assistantText("a2", "ok2"),
    ];
    const prompts = extractUserPrompts(entries);
    expect(prompts).toEqual([
      { turn: 0, seq: 0, text: fused, envelope: null },
      { turn: 1, seq: 1, text: "second legacy prompt", envelope: null },
    ]);
    // No outcome key on a completed legacy turn.
    expect(prompts[0]).not.toHaveProperty("outcome");
    expect(prompts[1]).not.toHaveProperty("outcome");

    const page = pageHistory(entries, "sess-legacy");
    expect(page.events.map(turnOf)).toEqual([0, 1]);
    expect(page.userPrompts).toEqual(prompts);
  });

  it("forbidden: never strips a '# Workspace context' heading to recover the sentence", () => {
    // A legacy entry whose fused text happens to start with the heading must
    // come back whole — `text` is the fused string verbatim, not a guess at
    // where the projection ends.
    const fused = "# Workspace context\nsome server-composed block\nthe operator's real ask";
    const prompts = extractUserPrompts([userMsg("u0", fused), assistantText("a1", "ok")]);
    expect(prompts[0]?.text).toBe(fused);
    expect(prompts[0]?.text?.startsWith("# Workspace context")).toBe(true);
  });
});

describe("outcome, from two sources (§2.8(4), notes item 8)", () => {
  it("(f) a completed turn carries no outcome key", () => {
    const entries = [userMsg("u0", "go"), assistantText("a1", "done")];
    const prompts = extractUserPrompts(entries);
    expect(prompts[0]).not.toHaveProperty("outcome");
  });

  it("(f) a cancelled turn with NO assistant entry gets its outcome from the sidecar-appended marker", () => {
    const entries = [
      userMsg("u0", "stop please"),
      customEntry("o0", "hephaestus.turn_outcome.v1", { turn: 0, state: "cancelled" }),
    ];
    const prompts = extractUserPrompts(entries);
    expect(prompts).toHaveLength(1);
    expect(prompts[0]?.outcome).toEqual({ state: "cancelled" });
    // The outcome marker is neither `message` nor `compaction`: it mints no event.
    expect(normalizeEntries(entries, "sess-cancel")).toHaveLength(0);
  });

  it("(f) an interrupted turn's outcome carries the recorded message verbatim", () => {
    const entries = [
      userMsg("u0", "keep going"),
      customEntry("o0", "hephaestus.turn_outcome.v1", { turn: 0, state: "interrupted", message: "sidecar restarted mid-turn" }),
    ];
    const prompts = extractUserPrompts(entries);
    expect(prompts[0]?.outcome).toEqual({ state: "interrupted", message: "sidecar restarted mid-turn" });
  });

  it("an errored turn's outcome is recoverable from Pi's own stopReason/errorMessage (source (i))", () => {
    const entries = [userMsg("u0", "try"), assistantWithStop("a1", "error", "boom")];
    const prompts = extractUserPrompts(entries);
    expect(prompts[0]?.outcome).toEqual({ state: "error", message: "boom" });
  });

  it("a normal stopReason ('stop') is a completed turn — outcome absent", () => {
    const entries = [userMsg("u0", "try"), assistantWithStop("a1", "stop")];
    const prompts = extractUserPrompts(entries);
    expect(prompts[0]).not.toHaveProperty("outcome");
  });
});

describe("tail read (§2.8(5), notes item 9)", () => {
  it("(g) end_cursor is always present, even on a fully-done first page", () => {
    const entries = [userMsg("u0", "hi"), assistantText("a1", "hello")];
    const page = pageHistory(entries, "sess-tail");
    expect(page.done).toBe(true);
    expect(page.cursor).toBeNull();
    expect((page as { endCursor?: unknown }).endCursor).toBeTruthy();
  });

  it("(g) a tail read after a completed walk returns only NEW events, prior identities unchanged", () => {
    const entries = [userMsg("u0", "hi"), assistantText("a1", "hello")];
    const page1 = pageHistory(entries, "sess-tail2") as unknown as { endCursor?: string; events: unknown[] };
    const after = page1.endCursor;
    expect(after).toBeTruthy();

    const grown = [...entries, userMsg("u1", "again"), assistantText("a2", "world")];
    const tail = pageHistory(grown, "sess-tail2", { after } as never) as unknown as {
      events: { seq: number }[];
      userPrompts: unknown[];
      done: boolean;
      endCursor?: string;
    };
    expect(tail.events.map((e) => e.seq)).toEqual([1]);
    expect(turnOf(tail.events[0])).toBe(1);
    expect(tail.userPrompts).toEqual([{ turn: 1, seq: 1, text: "again", envelope: null }]);
    expect(tail.done).toBe(true);
    expect(tail.endCursor).toBeTruthy();

    // Prior identities never move: re-reading the ORIGINAL page from scratch
    // reproduces byte-identical output.
    const page1Again = pageHistory(entries, "sess-tail2");
    expect(page1Again.events).toEqual(page1.events);
  });

  it("an `after` beyond the current end returns no events, done: true, the same end_cursor", () => {
    const entries = [userMsg("u0", "hi"), assistantText("a1", "hello")];
    const page1 = pageHistory(entries, "sess-tail3") as unknown as { endCursor?: string };
    const tail1 = pageHistory(entries, "sess-tail3", { after: page1.endCursor } as never) as unknown as {
      events: unknown[];
      done: boolean;
      endCursor?: string;
    };
    expect(tail1.events).toEqual([]);
    expect(tail1.done).toBe(true);
    expect(tail1.endCursor).toBe(page1.endCursor);
  });

  it("rejects a request carrying both cursor and after", () => {
    // Use a genuinely valid, non-null cursor (a small page size over two
    // events) so a throw here can only be the "both given" refusal — not an
    // accidental malformed-cursor throw that would pass for the wrong reason.
    const entries = [assistantText("a1", "x"), assistantText("a2", "y")];
    const page1 = pageHistory(entries, "sess-tail4", {}, { pageSize: 1 });
    expect(page1.cursor).not.toBeNull();
    expect(() =>
      pageHistory(entries, "sess-tail4", { cursor: page1.cursor ?? undefined, after: "a" } as never, { pageSize: 1 }),
    ).toThrow();
  });
});

describe("restart-stability of the turn record (item h)", () => {
  interface Fixture {
    dir: string;
    fake: FakeModel;
    service: SessionService;
    projectRoot: string;
    cleanup: () => Promise<void>;
  }

  async function makeFixture(script: readonly FakeTurnResolver[]): Promise<Fixture> {
    const dir = mkdtempSync(path.join(tmpdir(), "heph-turns-"));
    const agentDir = path.join(dir, "agent");
    const projectRoot = path.join(dir, "proj");
    const fake = await FakeModel.start(script, {});
    const { runtime } = await createModelRuntime({ providers: [fake.providerSpec()] }, { agentDir });
    const model = runtime.getModel(fake.providerId, fake.modelId);
    if (!model) throw new Error("fake model did not resolve");
    const service = new SessionService({ runtime, agentDir, model });
    const cleanup = async (): Promise<void> => {
      await service.disposeAll();
      await fake.close();
      rmSync(dir, { recursive: true, force: true });
    };
    return { dir, fake, service, projectRoot, cleanup };
  }

  let active: Fixture | undefined;
  afterEach(async () => {
    if (active) {
      await active.cleanup();
      active = undefined;
    }
  });

  it("(h) paging is byte-identical after dispose+resume: same turns, same events", async () => {
    const fx = await makeFixture([
      { kind: "text", chunks: ["reply zero"] },
      { kind: "text", chunks: ["reply one"] },
    ]);
    active = fx;

    const managed = await fx.service.create({ profile: "part", projectRoot: fx.projectRoot, part: "widget", sessionId: "s-restart" });

    // Mirrors what main.ts's prompt handler will do at prompt time
    // (notes_for_sidecar item 4): append the marker, THEN send the message.
    managed.session.sessionManager.appendCustomEntry("hephaestus.turn.v1", { turn: 0, text: "turn zero", envelope: null });
    await managed.session.prompt("turn zero");
    managed.session.sessionManager.appendCustomEntry("hephaestus.turn.v1", { turn: 1, text: "turn one", envelope: null });
    await managed.session.prompt("turn one");

    const before = pageHistory(managed.session.sessionManager.getEntries(), "s-restart");
    expect(before.userPrompts.map((p) => p.turn)).toEqual([0, 1]);

    await fx.service.dispose("s-restart");
    fx.fake.setScript([{ kind: "text", chunks: ["unused after restart"] }]);
    const resumed = await fx.service.resume({ profile: "part", projectRoot: fx.projectRoot, part: "widget", sessionId: "s-restart" });

    const after = pageHistory(resumed.session.sessionManager.getEntries(), "s-restart");
    expect(after).toEqual(before);
    expect(after.userPrompts).toEqual([
      { turn: 0, seq: 0, text: "turn zero", envelope: null },
      { turn: 1, seq: 1, text: "turn one", envelope: null },
    ]);
  }, 30000);

  // OPEN QUESTION from the published contract, answered by measurement rather
  // than by reading: does Pi's compaction preserve `CustomEntry` records?
  //
  // It does, and for a structural reason: `SessionManager.appendCompaction`
  // APPENDS a `compaction` entry naming a `firstKeptEntryId` and rewrites
  // nothing, and `getEntries()` (the only thing `history.ts` reads) returns the
  // whole append-only file rather than the compaction-aware projection —
  // `buildContextEntries` is what drops summarized entries, and it is used for
  // LLM context, not for the historical read. So a compacted session keeps
  // every turn marker, and §2.8(3)'s per-turn legacy fallback stays a fallback
  // instead of quietly becoming the common path on any long session.
  it("Pi compaction keeps the turn markers: a compacted session still separates sentence from envelope", async () => {
    const fx = await makeFixture([{ kind: "text", chunks: ["reply zero"] }, { kind: "text", chunks: ["reply one"] }]);
    active = fx;
    const managed = await fx.service.create({
      profile: "part",
      projectRoot: fx.projectRoot,
      part: "widget",
      sessionId: "s-compact",
    });
    const manager = managed.session.sessionManager;

    manager.appendCustomEntry("hephaestus.turn.v1", {
      turn: 0,
      text: "turn zero",
      envelope: "# Workspace context\nunits=mm",
    });
    await managed.session.prompt("# Workspace context\nunits=mm\nturn zero");
    const keepFrom = manager.getLeafId();
    if (keepFrom === null) throw new Error("no leaf to keep from");

    manager.appendCustomEntry("hephaestus.turn.v1", { turn: 1, text: "turn one", envelope: null });
    await managed.session.prompt("turn one");

    // Compact, keeping only the second turn — the first turn's marker is now
    // BEHIND the compaction boundary, which is the case that would break the
    // record if compaction dropped or orphaned custom entries.
    manager.appendCompaction("summary of turn zero", keepFrom, 1234);

    const page = pageHistory(manager.getEntries(), "s-compact");
    expect(page.userPrompts.map((p) => ({ turn: p.turn, text: p.text, envelope: p.envelope }))).toEqual([
      { turn: 0, text: "turn zero", envelope: "# Workspace context\nunits=mm" },
      { turn: 1, text: "turn one", envelope: null },
    ]);
    // The compaction itself surfaces as an audit event on the LAST turn, and
    // no earlier event identity moved.
    expect(page.events.at(-1)?.kind).toBe("audit");
  }, 30000);
});

describe("the marker is inert: appending one moves no event identity (§2.8(3), notes item 5)", () => {
  // A Pi `CustomEntry` is neither `message` nor `compaction`, so it emits no
  // event and advances no `seq`. This is the property `tests/stage4/
  // test_g4_event_archive.py` defends from the other side, and it is exactly
  // the kind of thing that breaks silently: `normalizeEntries` and
  // `extractUserPrompts` mirror each other's arithmetic, so a walk that
  // consumed a marker in one and not the other would drift a prompt's `seq`
  // by one with nothing failing.
  const bare: SessionEntry[] = [
    userMsg("u0", "first"),
    assistantText("a1", "reply one"),
    userMsg("u1", "second"),
    assistantText("a2", "reply two"),
  ];
  const marked: SessionEntry[] = [
    customEntry("m0", "hephaestus.turn.v1", { turn: 0, text: "first", envelope: null }),
    bare[0] as SessionEntry,
    bare[1] as SessionEntry,
    customEntry("m1", "hephaestus.turn.v1", { turn: 1, text: "second", envelope: null }),
    bare[2] as SessionEntry,
    bare[3] as SessionEntry,
    customEntry("o1", "hephaestus.turn_outcome.v1", { turn: 1, state: "cancelled" }),
  ];

  it("the event sequence is identical with and without markers interleaved", () => {
    expect(normalizeEntries(marked, "r")).toEqual(normalizeEntries(bare, "r"));
  });

  it("every prompt keeps the seq it had, and an outcome marker adds no event", () => {
    expect(extractUserPrompts(marked).map((p) => p.seq)).toEqual(
      extractUserPrompts(bare).map((p) => p.seq),
    );
    // Source (i) wins over the outcome marker: turn 1 HAS an assistant entry,
    // so the marker cannot relabel a turn the model actually finished.
    expect(extractUserPrompts(marked).some((p) => p.outcome !== undefined)).toBe(false);
  });

  it("the page's boundaries do not move either", () => {
    const a = pageHistory(bare, "r", {}, { pageSize: 1 });
    const b = pageHistory(marked, "r", {}, { pageSize: 1 });
    expect(b.events).toEqual(a.events);
    expect(b.done).toEqual(a.done);
    // The OFFSET is the identity-bearing half of a cursor and it must not move.
    // The token itself is deliberately not compared: it also names the frozen
    // high-water ENTRY, and a session whose last entry is a marker legitimately
    // freezes on that marker. The token is opaque, is never decoded outside the
    // sidecar, and names a snapshot rather than an event.
    const offset = (token: string | null): number | null =>
      token === null ? null : decodeCursor(token).offset;
    expect(offset(b.cursor)).toEqual(offset(a.cursor));
    expect(offset(b.endCursor)).toEqual(offset(a.endCursor));
  });
});

describe("`turn` is a field of the history page and of nothing else (§2.8(1))", () => {
  // The one-line trap named in the contract: `wireEvent` serves BOTH the live
  // `notify("event", …)` path and the history page, so stamping `turn` inside
  // it would put the field on the live socket. `main.ts` stamps it after
  // `wireEvent` instead; this pins the wire form from the other side.
  it("wireEvent never carries turn, even handed a history event that has one", () => {
    const events = normalizeEntries([userMsg("u0", "hi"), assistantText("a1", "yo")], "r");
    const historical = events[0];
    if (historical === undefined) throw new Error("no event to wire");
    expect(historical.turn).toBe(0);
    expect(Object.keys(wireEvent(historical))).not.toContain("turn");
  });
});

describe("empty thinking items emit no thought event (item i)", () => {
  it("(i) a thinking item with empty text is silently dropped, not emitted as a blank thought", () => {
    const entries = [assistantThinking("a1", ""), assistantText("a2", "real reply")];
    const events = normalizeEntries(entries, "sess-empty-thought");
    expect(events.map((e) => e.kind)).not.toContain("thought");
    expect(events.map((e) => e.kind)).toEqual(["text_delta"]);
  });

  it("a NON-empty thinking item still emits a thought event (control)", () => {
    const entries = [assistantThinking("a1", "reasoning here")];
    const events = normalizeEntries(entries, "sess-real-thought");
    expect(events.map((e) => e.kind)).toEqual(["thought"]);
  });
});
