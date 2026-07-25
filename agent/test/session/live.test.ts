// Live event normalization: Pi streaming events -> the public Hephaestus
// vocabulary. The regression these tests lock in is that the sidecar streams at
// all: `entry_appended` fires only for extension custom entries, so a live
// stream built on it is silently empty (the bug this module replaced).
import { describe, it, expect } from "vitest";
import { mkdtempSync, mkdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { defineTool } from "@earendil-works/pi-coding-agent";
import type { AgentSessionEvent } from "@earendil-works/pi-coding-agent";
import { Type } from "@sinclair/typebox";
import { normalizeLiveEvent, wireEvent } from "../../src/session/live.js";
import { EVENT_KINDS, type HephaestusEvent } from "../../src/events.js";
import { FakeModel, createModelRuntime } from "../../src/session/runtime.js";
import { SessionService } from "../../src/session/manager.js";

function counter(): () => number {
  let n = 0;
  return () => n++;
}

function run(events: AgentSessionEvent[]): HephaestusEvent[] {
  const next = counter();
  return events.flatMap((ev) => normalizeLiveEvent(ev, "run-1", next));
}

// Minimal shapes of the Pi events under test (the SDK does not export the
// assistant-stream union by name; this mirrors what the runtime emits).
function textDelta(delta: string): AgentSessionEvent {
  return {
    type: "message_update",
    message: { role: "assistant", content: [] },
    assistantMessageEvent: { type: "text_delta", contentIndex: 0, delta },
  } as unknown as AgentSessionEvent;
}

describe("normalizeLiveEvent", () => {
  it("maps assistant text and thinking deltas", () => {
    const events = run([
      textDelta("hello "),
      textDelta("world"),
      {
        type: "message_update",
        message: { role: "assistant", content: [] },
        assistantMessageEvent: { type: "thinking_delta", contentIndex: 0, delta: "hmm" },
      } as unknown as AgentSessionEvent,
    ]);
    expect(events.map((e) => e.kind)).toEqual(["text_delta", "text_delta", "thought"]);
    expect(events.map((e) => e.seq)).toEqual([0, 1, 2]);
    expect(events[0]?.payload).toEqual({ text: "hello " });
    expect(events[2]?.payload).toEqual({ text: "hmm" });
  });

  it("drops empty deltas and Pi-internal lifecycle events", () => {
    const events = run([
      { type: "agent_start" } as AgentSessionEvent,
      { type: "turn_start" } as AgentSessionEvent,
      textDelta(""),
      { type: "queue_update", steering: [], followUp: [] } as AgentSessionEvent,
      { type: "agent_settled" } as AgentSessionEvent,
    ]);
    expect(events).toEqual([]);
  });

  it("maps a tool call, its progress updates, and its result + images", () => {
    const png = Buffer.from("fake-png-bytes").toString("base64");
    const events = run([
      {
        type: "tool_execution_start",
        toolCallId: "call_0",
        toolName: "inspect_part",
        args: { name: "widget" },
      } as AgentSessionEvent,
      {
        type: "tool_execution_update",
        toolCallId: "call_0",
        toolName: "inspect_part",
        args: {},
        partialResult: {},
      } as AgentSessionEvent,
      {
        type: "tool_execution_end",
        toolCallId: "call_0",
        toolName: "inspect_part",
        isError: false,
        result: {
          content: [
            { type: "text", text: '{"status":"ok"}' },
            { type: "image", data: png, mimeType: "image/png" },
          ],
          details: {},
        },
      } as AgentSessionEvent,
    ]);
    expect(events.map((e) => e.kind)).toEqual(["tool_call", "progress", "tool_result", "image"]);
    expect(events.every((e) => e.toolCallId === "call_0")).toBe(true);
    expect(events[0]?.payload).toEqual({
      name: "inspect_part",
      arguments: { name: "widget" },
    });
    expect(events[2]?.payload).toEqual({
      toolName: "inspect_part",
      text: '{"status":"ok"}',
      isError: false,
    });
    expect(events[3]?.payload).toEqual({
      mimeType: "image/png",
      bytes: Buffer.from(png, "base64").length,
      data: png,
    });
  });

  it("marks failed tool results and survives unserializable arguments", () => {
    const cyclic: Record<string, unknown> = {};
    cyclic.self = cyclic;
    const events = run([
      {
        type: "tool_execution_start",
        toolCallId: "c",
        toolName: "build_part",
        args: cyclic,
      } as AgentSessionEvent,
      {
        type: "tool_execution_end",
        toolCallId: "c",
        toolName: "build_part",
        isError: true,
        result: { content: [{ type: "text", text: "boom" }], details: {} },
      } as AgentSessionEvent,
    ]);
    expect(events[0]?.payload).toEqual({ name: "build_part", arguments: null });
    expect(events[1]?.payload).toMatchObject({ isError: true, text: "boom" });
  });

  it("surfaces compaction as audit events", () => {
    const events = run([
      { type: "compaction_start", reason: "threshold" } as AgentSessionEvent,
      {
        type: "compaction_end",
        reason: "threshold",
        result: undefined,
        aborted: false,
        willRetry: false,
      } as AgentSessionEvent,
    ]);
    expect(events.map((e) => e.kind)).toEqual(["audit", "audit"]);
    expect(events[1]?.payload).toEqual({
      event: "compaction_end",
      reason: "threshold",
      aborted: false,
    });
  });

  it("only ever emits kinds from the public vocabulary", () => {
    const png = Buffer.from("x").toString("base64");
    const all = run([
      textDelta("a"),
      { type: "tool_execution_start", toolCallId: "t", toolName: "measure", args: {} } as AgentSessionEvent,
      {
        type: "tool_execution_end",
        toolCallId: "t",
        toolName: "measure",
        isError: false,
        result: { content: [{ type: "image", data: png, mimeType: "image/png" }], details: {} },
      } as AgentSessionEvent,
      { type: "compaction_start", reason: "manual" } as AgentSessionEvent,
    ]);
    for (const ev of all) expect(EVENT_KINDS).toContain(ev.kind);
  });
});

describe("wireEvent", () => {
  it("emits the snake_case envelope and omits absent members", () => {
    expect(wireEvent({ runId: "r", seq: 3, kind: "text_delta", payload: { text: "x" } })).toEqual({
      run_id: "r",
      seq: 3,
      kind: "text_delta",
      payload: { text: "x" },
    });
    expect(
      wireEvent({ runId: "r", seq: 4, kind: "tool_call", toolCallId: "c1", payload: null }),
    ).toEqual({ run_id: "r", seq: 4, kind: "tool_call", tool_call_id: "c1", payload: null });
  });
});

describe("live streaming over a real Pi session", () => {
  it("streams a non-empty normalized stream for a scripted tool turn", async () => {
    const dir = mkdtempSync(path.join(tmpdir(), "heph-live-"));
    const agentDir = path.join(dir, "agent");
    const projectRoot = path.join(dir, "proj");
    mkdirSync(agentDir, { recursive: true });
    mkdirSync(projectRoot, { recursive: true });
    const fake = await FakeModel.start([
      { kind: "tool_calls", calls: [{ name: "inspect_part", arguments: { name: "w" } }] },
      { kind: "text", chunks: ["done"] },
    ]);
    const runtime = await createModelRuntime({ providers: [fake.providerSpec()] }, { agentDir });
    const model = runtime.getModel(fake.providerId, fake.modelId);
    if (!model) throw new Error("fake model did not resolve");
    const service = new SessionService({
      runtime,
      agentDir,
      model,
      customTools: [
        defineTool({
          name: "inspect_part",
          label: "inspect",
          description: "fake inspect",
          parameters: Type.Object({}, { additionalProperties: true }),
          execute: () =>
            Promise.resolve({ content: [{ type: "text" as const, text: "rendered" }], details: {} }),
        }),
      ],
    });
    try {
      const managed = await service.create({
        profile: "part",
        projectRoot,
        part: "w",
        sessionId: "live",
      });
      const seen: HephaestusEvent[] = [];
      const next = counter();
      managed.session.subscribe((ev) => {
        seen.push(...normalizeLiveEvent(ev, "run-live", next));
      });
      await managed.session.prompt("inspect then finish");

      const kinds = seen.map((e) => e.kind);
      expect(kinds).toContain("tool_call");
      expect(kinds).toContain("tool_result");
      expect(kinds).toContain("text_delta");
      expect(seen.map((e) => e.seq)).toEqual([...seen.map((_, i) => i)]);
      expect(seen.every((e) => e.runId === "run-live")).toBe(true);
    } finally {
      await service.disposeAll();
      await fake.close();
      rmSync(dir, { recursive: true, force: true });
    }
  }, 30000);
});
