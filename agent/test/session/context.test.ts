import { describe, it, expect } from "vitest";
import type { SessionEntry } from "@earendil-works/pi-coding-agent";
import type { ManagedSession } from "../../src/session/manager.js";
import {
  ImageEvictionTracker,
  ContextPolicy,
  renderStub,
  formatPinnedSummary,
  // B-12's real producer and the caps it is bounded by, exported as constants
  // so these tests read the numbers rather than duplicating them.
  summarize,
  MAX_SUMMARY_ITEMS,
  MAX_SUMMARY_BYTES,
  IMAGE_EVICTION_K,
  COMPACTION_TRIGGER_FRACTION,
  BUDGET_ESCALATION_FRACTION,
  PINNED_SUMMARY_OPEN,
  PINNED_SUMMARY_CLOSE,
  type PinnedCadSummary,
  type RenderRef,
} from "../../src/session/context.js";

const summary: PinnedCadSummary = {
  designIntent: "L-bracket with two through-holes",
  decisions: ["fillet inner corner r=3", "holes on 20mm pitch"],
  openProblems: ["confirm wall thickness"],
  params: { hole_d: 5, fillet_r: 3, gap: null },
  checkStatus: "1 failing (bbox)",
};

describe("render stub", () => {
  it("matches the exact digest format", () => {
    const ref: RenderRef = { name: "cat_step", view: "iso", channel: "mask" };
    expect(renderStub(ref)).toBe("[render: cat_step iso/mask, superseded — re-run inspect_part to view]");
  });
});

describe("image eviction K=3", () => {
  const mk = (id: string): { toolCallId: string; renders: RenderRef[] } => ({
    toolCallId: id,
    renders: [{ name: "widget", view: "iso", channel: "rgb" }],
  });

  it("keeps the most recent 3; the 4th evicts the 1st with a stub", () => {
    expect(IMAGE_EVICTION_K).toBe(3);
    const tracker = new ImageEvictionTracker();
    expect(tracker.record(mk("t1"))).toEqual([]);
    expect(tracker.record(mk("t2"))).toEqual([]);
    expect(tracker.record(mk("t3"))).toEqual([]);
    const evicted = tracker.record(mk("t4"));
    expect(evicted).toHaveLength(1);
    expect(evicted[0]?.toolCallId).toBe("t1");
    expect(evicted[0]?.stub).toBe("[render: widget iso/rgb, superseded — re-run inspect_part to view]");
    expect(tracker.liveToolCallIds()).toEqual(["t2", "t3", "t4"]);
  });

  it("stubs every render of an evicted multi-view result", () => {
    const tracker = new ImageEvictionTracker();
    tracker.record({ toolCallId: "a", renders: [
      { name: "widget", view: "iso", channel: "rgb" },
      { name: "widget", view: "+X", channel: "rgb" },
    ] });
    tracker.record(mk("b"));
    tracker.record(mk("c"));
    const evicted = tracker.record(mk("d"));
    expect(evicted).toHaveLength(2);
    expect(evicted.every((e) => e.toolCallId === "a")).toBe(true);
  });
});

describe("pinned summary", () => {
  it("is delimited and contains the CAD-aware fields", () => {
    const text = formatPinnedSummary(summary);
    expect(text).toContain(PINNED_SUMMARY_OPEN);
    expect(text).toContain("Design intent: L-bracket with two through-holes");
    expect(text).toContain("fillet inner corner r=3");
    expect(text).toContain("confirm wall thickness");
    expect(text).toContain("hole_d=5");
    expect(text).toContain("gap=null");
    expect(text).toContain("Check status: 1 failing (bbox)");
  });
});

describe("context policy latching", () => {
  it("triggers compaction at 70% with the pinned summary as instructions", () => {
    const policy = new ContextPolicy({ summary: () => summary });
    expect(policy.evaluate(0.5)).toEqual([]);
    const actions = policy.evaluate(COMPACTION_TRIGGER_FRACTION);
    expect(actions).toHaveLength(1);
    expect(actions[0]?.kind).toBe("compact");
    if (actions[0]?.kind === "compact") {
      expect(actions[0].instructions).toContain(PINNED_SUMMARY_OPEN);
      expect(actions[0].instructions).toContain("L-bracket");
    }
    // Latched: no repeat until reset.
    expect(policy.evaluate(0.75)).toEqual([]);
  });

  it("escalates once at 90%", () => {
    const policy = new ContextPolicy({ summary: () => summary });
    const actions = policy.evaluate(BUDGET_ESCALATION_FRACTION);
    // At >=90% both compaction (first cross) and escalation fire, in order.
    expect(actions.map((a) => a.kind)).toEqual(["compact", "escalate"]);
    const escalate = actions.find((a) => a.kind === "escalate");
    expect(escalate?.kind === "escalate" && escalate.percent).toBe(0.9);
    expect(policy.evaluate(0.95)).toEqual([]);
  });

  it("null usage yields no action", () => {
    const policy = new ContextPolicy({ summary: () => summary });
    expect(policy.evaluate(null)).toEqual([]);
  });

  it("reset re-arms the compaction trigger", () => {
    const policy = new ContextPolicy({ summary: () => summary });
    policy.evaluate(0.72);
    policy.reset();
    expect(policy.evaluate(0.72).map((a) => a.kind)).toEqual(["compact"]);
  });
});

// ── summarize (B-12) ─────────────────────────────────────────────────────────
//
// audit-2026-09-04-broken.md §B-12: `stubSummary` (agent/src/main.ts) was the
// ONLY producer of the pinned CAD summary, and it was a stub — every field
// empty, `checkStatus: "unknown"`. `summarize` is the real producer the fix
// design asks for: derived entirely from the session's own recorded entries
// (agent/src/session/history.ts's reader shapes), zero bridge calls.
//
// Structural builders mirror history.test.ts / turns.test.ts: Pi session
// entries built by hand, cast at the Pi-boundary the way those files do.

const CTX_TS = "2026-09-05T00:00:00.000Z";

function ctxUserMsg(id: string, text: string): SessionEntry {
  return {
    type: "message",
    id,
    parentId: null,
    timestamp: CTX_TS,
    message: { role: "user", content: text },
  } as unknown as SessionEntry;
}

function ctxToolCall(id: string, callId: string, name: string, args: Record<string, unknown>): SessionEntry {
  return {
    type: "message",
    id,
    parentId: null,
    timestamp: CTX_TS,
    message: { role: "assistant", content: [{ type: "toolCall", id: callId, name, arguments: args }] },
  } as unknown as SessionEntry;
}

/** A `toolResult` whose content is the tool's canonical-JSON result envelope. */
function ctxToolResult(id: string, callId: string, name: string, result: unknown): SessionEntry {
  return {
    type: "message",
    id,
    parentId: null,
    timestamp: CTX_TS,
    message: {
      role: "toolResult",
      toolCallId: callId,
      toolName: name,
      content: [{ type: "text", text: JSON.stringify(result) }],
    },
  } as unknown as SessionEntry;
}

/** A `toolResult` that FAILED — Pi's own `isError: true`, plain-text envelope. */
function ctxToolError(id: string, callId: string, name: string, text: string): SessionEntry {
  return {
    type: "message",
    id,
    parentId: null,
    timestamp: CTX_TS,
    message: {
      role: "toolResult",
      toolCallId: callId,
      toolName: name,
      content: [{ type: "text", text }],
      isError: true,
    },
  } as unknown as SessionEntry;
}

const managed = { id: "sess-ctx-1", profile: "part" } as unknown as ManagedSession;

/** One operator prompt, an answered `ask_user` question, a `set_params` result,
 *  a mixed-outcome `run_checks` result, and a failed `build_part` — the fix
 *  design's own worked example, and the "Tests to add" §B-12 first bullet. */
function fullTranscript(): SessionEntry[] {
  return [
    ctxUserMsg("u0", "Build an L-bracket with two through-holes and a filleted inner corner."),
    ctxToolCall("a1", "call_ask", "ask_user", {
      question: "What hole diameter?",
      options: ["5mm", "6mm"],
    }),
    ctxToolResult("r1", "call_ask", "ask_user", { selection: "5mm", recorded: [] }),
    ctxToolCall("a2", "call_set", "set_params", {
      values: { hole_d: 5, fillet_r: 3 },
      expected_state_hash: "h0",
    }),
    ctxToolResult("r2", "call_set", "set_params", {
      effective: { hole_d: 5, fillet_r: 3 },
      rejected: [],
      state_hash: "h1",
    }),
    ctxToolCall("a3", "call_checks", "run_checks", { scope: "part", name: "bracket" }),
    ctxToolResult("r3", "call_checks", "run_checks", {
      status: "error",
      scope: "part",
      part: "bracket",
      checks: {
        bbox: { pass: false, measured: { max_mm: 61.2 } },
        symmetry: { pass: true, measured: { delta_mm: 0.01 } },
      },
    }),
    ctxToolCall("a4", "call_build", "build_part", { name: "bracket" }),
    ctxToolError("r4", "call_build", "build_part", "wall_too_thin: measured 1.2mm < required 2mm"),
  ];
}

describe("summarize (B-12)", () => {
  it("populates all five pinned-summary fields from the session's own recorded entries", () => {
    const summary = summarize(fullTranscript(), managed);

    // design intent — the operator's own first prompt, not the session/profile
    // fallback `stubSummary` used unconditionally.
    expect(summary.designIntent).toContain("L-bracket");
    expect(summary.designIntent).not.toBe(`session ${managed.id} (${managed.profile})`);

    // decisions — the answered ask_user question: the question and the
    // stable, server-sent selected label.
    expect(summary.decisions.length).toBeGreaterThan(0);
    expect(summary.decisions.some((d) => d.includes("hole diameter"))).toBe(true);
    expect(summary.decisions.some((d) => d.includes("5mm"))).toBe(true);

    // params — the newest set_params result's effective map.
    expect(summary.params).toEqual({ hole_d: 5, fillet_r: 3 });

    // check status — the newest run_checks result, "<n> passing, <m> failing
    // (<names>)" (the fix design's own template).
    expect(summary.checkStatus).toBe("1 passing, 1 failing (bbox)");

    // open problems — the failing check name, and the failed build's reason.
    expect(summary.openProblems.some((p) => p.includes("bbox"))).toBe(true);
    expect(
      summary.openProblems.some((p) => p.includes("wall_too_thin") || p.includes("1.2mm")),
    ).toBe(true);
  });

  it("falls back to the session/profile string only when there is no operator prompt", () => {
    const summary = summarize([], managed);
    expect(summary.designIntent).toBe(`session ${managed.id} (${managed.profile})`);
    expect(summary.decisions).toEqual([]);
    expect(summary.openProblems).toEqual([]);
    expect(summary.params).toEqual({});
  });

  it("is deterministic: the same entries produce byte-identical output twice", () => {
    const entries = fullTranscript();
    const first = formatPinnedSummary(summarize(entries, managed));
    const second = formatPinnedSummary(summarize(entries, managed));
    expect(second).toBe(first);
  });

  it("caps decisions at MAX_SUMMARY_ITEMS, newest first, and stays under MAX_SUMMARY_BYTES", () => {
    const entries: SessionEntry[] = [
      ctxUserMsg("u0", "Build a widget."),
    ];
    const total = MAX_SUMMARY_ITEMS + 5;
    for (let i = 0; i < total; i += 1) {
      entries.push(ctxToolCall(`a-ask-${i}`, `call_ask_${i}`, "ask_user", {
        question: `Question number ${i}?`,
        options: [`opt_${i}_a`, `opt_${i}_b`],
      }));
      entries.push(
        ctxToolResult(`r-ask-${i}`, `call_ask_${i}`, "ask_user", {
          selection: `opt_${i}_a`,
          recorded: [],
        }),
      );
    }

    const summary = summarize(entries, managed);
    expect(summary.decisions.length).toBe(MAX_SUMMARY_ITEMS);
    // newest first: the very last question asked (total - 1) leads the list,
    // and the earliest ones (evicted oldest-first per the fix design) are gone.
    expect(summary.decisions[0]).toContain(`Question number ${total - 1}?`);
    expect(summary.decisions.some((d) => d.includes("Question number 0?"))).toBe(false);

    const bytes = Buffer.byteLength(formatPinnedSummary(summary), "utf8");
    expect(bytes).toBeLessThanOrEqual(MAX_SUMMARY_BYTES);
  });

  it("does not throw on a malformed entry list; compaction keeps working", () => {
    const malformed: SessionEntry[] = [
      ctxUserMsg("u0", "Build a widget."),
      // A "message" entry whose `message` is missing entirely — the shape
      // `walkEntries` (history.ts) does not guard against, since production
      // Pi entries always carry one. `summarize` must not propagate a crash
      // out of a bookkeeping read: a bad entry must not fail compaction.
      { type: "message", id: "broken", parentId: null, timestamp: CTX_TS } as unknown as SessionEntry,
      ctxToolResult("r-bad", "call_missing", "set_params", "not-an-object"),
    ];

    let summary: PinnedCadSummary | undefined;
    expect(() => {
      summary = summarize(malformed, managed);
    }).not.toThrow();
    expect(typeof summary?.designIntent).toBe("string");
    expect(Array.isArray(summary?.decisions)).toBe(true);
    expect(Array.isArray(summary?.openProblems)).toBe(true);
    expect(typeof summary?.params).toBe("object");
    expect(typeof summary?.checkStatus).toBe("string");
    // Must still be usable as compaction instructions.
    expect(() => formatPinnedSummary(summary as PinnedCadSummary)).not.toThrow();
  });
});

// ── summarize: the cases the block above leaves open ─────────────────────────

/** A transcript rebuilt from scratch, to prove restart-stability rather than
 *  the weaker "same array read twice". */
function rebuiltTranscript(): SessionEntry[] {
  return [
    ctxUserMsg("u0", "Build a shelf bracket that carries 40 kg."),
    ctxToolCall("a1", "call_p", "set_params", { values: { w: 65 } }),
    ctxToolResult("r1", "call_p", "set_params", { effective: { w: 65, t: 4 }, rejected: [] }),
    ctxToolCall("a2", "call_c", "run_checks", { scope: "part", name: "bracket" }),
    ctxToolResult("r2", "call_c", "run_checks", {
      status: "ok",
      checks: { load: { pass: true, measured: 41 }, span: { pass: false, measured: 3 } },
    }),
  ];
}

describe("summarize: restart stability and the byte budget", () => {
  it("renders identically from two independently built entry lists", () => {
    const first = formatPinnedSummary(summarize(rebuiltTranscript(), managed));
    const second = formatPinnedSummary(summarize(rebuiltTranscript(), managed));
    expect(second).toBe(first);
    // No timestamp reaches the block, which is what makes the two runs equal
    // across a restart and not merely inside one process.
    expect(first).not.toContain(CTX_TS.slice(0, 10));
  });

  it("shrinks a block whose items are each legal but jointly oversized", () => {
    const long = "x".repeat(600);
    const entries: SessionEntry[] = [ctxUserMsg("u0", long)];
    for (let i = 0; i < MAX_SUMMARY_ITEMS; i += 1) {
      entries.push(ctxToolCall(`a${i}`, `c${i}`, "ask_user", { question: `${long} ${i}` }));
      entries.push(ctxToolResult(`r${i}`, `c${i}`, "ask_user", { selection: long }));
    }
    const summary = summarize(entries, managed);
    const block = formatPinnedSummary(summary);
    expect(Buffer.byteLength(block, "utf8")).toBeLessThanOrEqual(MAX_SUMMARY_BYTES);
    // Shrinking never empties a list that had content, and never breaks the
    // delimiters the post-compaction assertions depend on.
    expect(summary.decisions.length).toBeGreaterThan(0);
    expect(block.startsWith(PINNED_SUMMARY_OPEN)).toBe(true);
  });

  it("an entry list that throws on read falls back instead of failing compaction", () => {
    const hostile = new Proxy([] as SessionEntry[], {
      get(): never {
        throw new Error("entry store is gone");
      },
    });
    expect(() => summarize(hostile, managed)).not.toThrow();
    expect(summarize(hostile, managed)).toEqual({
      designIntent: `session ${managed.id} (${managed.profile})`,
      decisions: [],
      openProblems: [],
      params: {},
      checkStatus: "unknown",
    });
  });
});

describe("summarize: CAD state the compaction boundary must carry", () => {
  it("keeps a later good build from clearing another part's failure", () => {
    const entries = [
      ctxUserMsg("u0", "build both"),
      ctxToolCall("a0", "c0", "build_part", { name: "bracket" }),
      ctxToolResult("r0", "c0", "build_part", {
        status: "error",
        error: { line: 3, col: 1, type: "NameError", message: "p.thick", frame: [] },
      }),
      ctxToolCall("a1", "c1", "build_part", { name: "gusset" }),
      ctxToolResult("r1", "c1", "build_part", {
        status: "error",
        error: { line: 9, col: 1, type: "ValueError", message: "negative depth", frame: [] },
      }),
      ctxToolCall("a2", "c2", "build_part", { name: "bracket" }),
      ctxToolResult("r2", "c2", "build_part", { status: "ok", effective_params: {} }),
    ];
    expect(summarize(entries, managed).openProblems).toEqual([
      "build gusset failed at line 9: ValueError: negative depth",
    ]);
  });

  it("carries requirement resolutions and the ledger's unresolved material", () => {
    const entries = [
      ctxUserMsg("u0", "record the requirements"),
      ctxToolCall("a0", "c0", "update_requirement", { id: "R2", resolution: "bead blast" }),
      ctxToolResult("r0", "c0", "update_requirement", {
        status: "ok",
        generation: 2,
        artifact_ref: null,
        entries: [
          { id: "R1", text: "gusset thickness", source: "specified", resolution: "4 mm" },
          { id: "R2", text: "finish", source: "assumed", resolution: "bead blast" },
          { id: "R3", text: "material", source: "assumed", resolution: null },
        ],
        unresolved_material: ["R3"],
      }),
    ];
    const summary = summarize(entries, managed);
    expect(summary.decisions).toContain("R2 resolved: bead blast");
    expect(summary.decisions).toContain("R1 resolved: 4 mm");
    expect(summary.openProblems).toEqual(["unresolved requirement R3"]);
  });

  it("prefers the newest set_params map over an earlier build's parameters", () => {
    const entries = [
      ctxUserMsg("u0", "set then build"),
      ctxToolCall("a0", "c0", "build_part", { name: "bracket" }),
      ctxToolResult("r0", "c0", "build_part", { status: "ok", effective_params: { w: 60, t: 4 } }),
      ctxToolCall("a1", "c1", "set_params", { values: { w: 65 } }),
      ctxToolResult("r1", "c1", "set_params", { effective: { w: 65, t: 4, gap: "unset" }, rejected: [] }),
    ];
    // A non-numeric effective value is `null`, never a guess: every declared
    // parameter is numeric (core/params.py), so anything else is unknown.
    expect(summarize(entries, managed).params).toEqual({ gap: null, t: 4, w: 65 });
  });

  it("reports a refused check run as unavailable rather than as a pass", () => {
    const entries = [
      ctxUserMsg("u0", "check it"),
      ctxToolCall("a0", "c0", "run_checks", { scope: "project" }),
      ctxToolResult("r0", "c0", "run_checks", {
        status: "invalid_check_generation",
        check_set_generation: "7",
      }),
    ];
    expect(summarize(entries, managed).checkStatus).toBe("unavailable (invalid_check_generation)");
  });

  it("a truncated result contributes nothing rather than a wrong verdict", () => {
    const entries = [
      ctxUserMsg("u0", "intent"),
      ctxToolCall("a0", "c0", "run_checks", { scope: "project" }),
      {
        type: "message",
        id: "r0",
        parentId: null,
        timestamp: CTX_TS,
        message: {
          role: "toolResult",
          toolCallId: "c0",
          toolName: "run_checks",
          content: [{ type: "text", text: '{"status": "ok", "checks": {"bb' }],
        },
      } as unknown as SessionEntry,
    ];
    const summary = summarize(entries, managed);
    expect(summary.checkStatus).toBe("unknown");
    expect(summary.designIntent).toBe("intent");
  });
});

// ── the byte-budget shrink ───────────────────────────────────────────────────
//
// MAX_SUMMARY_BYTES is a HARD budget on the whole formatted block, and the
// block is PREPENDED to the compaction request — it competes for exactly the
// context the compaction is reclaiming. The per-item cap alone cannot enforce
// it: MAX_SUMMARY_ITEMS items of MAX_SUMMARY_ITEM_BYTES each, in two lists plus
// a parameter map, jointly exceed the budget while every individual item is
// legal. Only the shrink pass enforces it, and its ORDER is part of the
// contract: the lists are newest-first, so shedding from the tail sheds the
// OLDEST claim; decisions go before open problems; parameters go last and never
// empty. The mutation these tests exist to kill is deleting that pass — every
// assertion below is on a transcript whose UNSHRUNK block is over budget, and
// each supplies exactly MAX_SUMMARY_ITEMS decisions so the item cap sheds none
// of them and anything missing is the shrink's doing.

/** A string long enough that the item it is rendered into fills the per-item
 *  byte budget, tagged at the front so the survivor can still be named after
 *  the clamp cuts its tail off. */
function bulky(tag: string): string {
  return `${tag} ${"x".repeat(400)}`;
}

/** `count` parameters with names long enough to make the parameter map itself
 *  a material share of the block. */
function bulkyParams(count: number): Record<string, number> {
  const out: Record<string, number> = {};
  for (let i = 0; i < count; i += 1) out[`p_${String(i).padStart(3, "0")}_${"w".repeat(26)}`] = 12.5;
  return out;
}

/**
 * A transcript whose summary is over budget before shrinking: MAX_SUMMARY_ITEMS
 * answered questions, MAX_SUMMARY_ITEMS unresolved requirements, and `params`.
 * Growing `params` is the dial that decides how much has to be shed.
 */
function oversizedEntries(params: Record<string, number>): SessionEntry[] {
  const entries: SessionEntry[] = [ctxUserMsg("u0", `Design a manifold. ${"z".repeat(400)}`)];
  for (let i = 0; i < MAX_SUMMARY_ITEMS; i += 1) {
    const tag = `Q${String(i).padStart(2, "0")}`;
    entries.push(ctxToolCall(`a-${tag}`, `c-${tag}`, "ask_user", { question: bulky(tag) }));
    entries.push(ctxToolResult(`r-${tag}`, `c-${tag}`, "ask_user", { selection: `${tag}-answer` }));
  }
  entries.push(ctxToolCall("a-req", "c-req", "record_requirements", { entries: [] }));
  entries.push(
    ctxToolResult("r-req", "c-req", "record_requirements", {
      status: "ok",
      generation: 1,
      artifact_ref: null,
      entries: [],
      unresolved_material: Array.from(
        { length: MAX_SUMMARY_ITEMS },
        (_unused, i) => `R${String(i).padStart(2, "0")}${"y".repeat(400)}`,
      ),
    }),
  );
  entries.push(ctxToolCall("a-set", "c-set", "set_params", { values: params }));
  entries.push(ctxToolResult("r-set", "c-set", "set_params", { effective: params, rejected: [] }));
  return entries;
}

/** The `Qnn` tag each surviving decision was built from, in rendered order. */
function decisionTags(summary: PinnedCadSummary): string[] {
  return summary.decisions.map((d) => d.slice(0, 3));
}

/** `Qnn` tags newest-first — the order a shrunk decision list must be a PREFIX of. */
const NEWEST_FIRST_TAGS = Array.from(
  { length: MAX_SUMMARY_ITEMS },
  (_unused, i) => `Q${String(MAX_SUMMARY_ITEMS - 1 - i).padStart(2, "0")}`,
);

describe("summarize: the byte budget is enforced by shrinking", () => {
  it("shrinks an over-budget summary to within MAX_SUMMARY_BYTES, delimiters intact", () => {
    const summary = summarize(oversizedEntries(bulkyParams(10)), managed);
    const block = formatPinnedSummary(summary);

    expect(Buffer.byteLength(block, "utf8")).toBeLessThanOrEqual(MAX_SUMMARY_BYTES);
    // The delimiters are what makes the block recoverable in the
    // post-compaction transcript (the G2 gate reads INSIDE this span), so
    // shrinking must never reach them: it drops items, never bytes off the ends.
    expect(block.startsWith(PINNED_SUMMARY_OPEN)).toBe(true);
    expect(block.endsWith(PINNED_SUMMARY_CLOSE)).toBe(true);

    // The transcript supplied exactly MAX_SUMMARY_ITEMS answers, so the item cap
    // dropped none: a shorter list here is the byte budget being enforced, and
    // it is the assertion that fails if the shrink pass is removed.
    expect(summary.decisions.length).toBeLessThan(MAX_SUMMARY_ITEMS);
    expect(summary.decisions.length).toBeGreaterThanOrEqual(1);
  });

  it("sheds oldest-first and keeps the most recent decision", () => {
    const summary = summarize(oversizedEntries(bulkyParams(10)), managed);
    const tags = decisionTags(summary);

    // Newest-first, so the survivors are a PREFIX of the newest-first order:
    // shedding from the tail sheds the oldest claim. A shrink that popped the
    // head, reversed the list, or shed from the middle fails here.
    expect(tags).toEqual(NEWEST_FIRST_TAGS.slice(0, tags.length));
    expect(tags[0]).toBe(`Q${String(MAX_SUMMARY_ITEMS - 1).padStart(2, "0")}`);
    expect(tags).not.toContain("Q00");
  });

  it("sheds decisions before open problems, and parameters not at all while a list can still give", () => {
    const params = bulkyParams(10);
    const summary = summarize(oversizedEntries(params), managed);

    // Decisions are shed down to their last item before open problems lose one,
    // and parameters go last of all — so an overshoot the decision list alone
    // can absorb leaves the other two untouched.
    expect(summary.decisions.length).toBeLessThan(MAX_SUMMARY_ITEMS);
    expect(summary.openProblems).toHaveLength(MAX_SUMMARY_ITEMS);
    expect(Object.keys(summary.params)).toEqual(Object.keys(params).sort());
  });

  it("sheds parameters only once both lists are down to one, and never empties them", () => {
    // A parameter map big enough that shrinking both lists to their last item
    // still leaves the block over budget.
    const params = bulkyParams(100);
    const summary = summarize(oversizedEntries(params), managed);
    const block = formatPinnedSummary(summary);

    expect(Buffer.byteLength(block, "utf8")).toBeLessThanOrEqual(MAX_SUMMARY_BYTES);
    expect(block.startsWith(PINNED_SUMMARY_OPEN)).toBe(true);
    expect(block.endsWith(PINNED_SUMMARY_CLOSE)).toBe(true);

    // Each list always leaves one behind: a block naming some current state is
    // worth more than one naming none.
    expect(summary.decisions).toHaveLength(1);
    expect(decisionTags(summary)[0]).toBe(`Q${String(MAX_SUMMARY_ITEMS - 1).padStart(2, "0")}`);
    expect(summary.openProblems).toHaveLength(1);
    expect(summary.openProblems[0]).toContain("unresolved requirement R00");

    const keys = Object.keys(summary.params);
    expect(keys.length).toBeGreaterThanOrEqual(1);
    expect(keys.length).toBeLessThan(Object.keys(params).length);
    // Parameters are shed from the tail of their sorted order too, so the map
    // that survives is a prefix of the sorted keys rather than an arbitrary set.
    expect(keys).toEqual(Object.keys(params).sort().slice(0, keys.length));
  });

  it("shrinks deterministically: the same entries render byte-identically twice", () => {
    const entries = oversizedEntries(bulkyParams(10));
    const first = formatPinnedSummary(summarize(entries, managed));
    const second = formatPinnedSummary(summarize(entries, managed));
    expect(second).toBe(first);
    // And from a list rebuilt from scratch, which is what restart-stability
    // actually means: the shrink must not depend on anything but the entries.
    const rebuilt = formatPinnedSummary(summarize(oversizedEntries(bulkyParams(10)), managed));
    expect(rebuilt).toBe(first);
    expect(Buffer.byteLength(first, "utf8")).toBeLessThanOrEqual(MAX_SUMMARY_BYTES);
  });
});
