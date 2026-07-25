import { describe, it, expect } from "vitest";
import {
  ImageEvictionTracker,
  ContextPolicy,
  renderStub,
  formatPinnedSummary,
  IMAGE_EVICTION_K,
  COMPACTION_TRIGGER_FRACTION,
  BUDGET_ESCALATION_FRACTION,
  PINNED_SUMMARY_OPEN,
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
