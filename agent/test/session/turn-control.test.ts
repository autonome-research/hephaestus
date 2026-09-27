// §7A.10A over the pinned Pi 0.80.10 AgentSession, using loopback models only.
import { afterEach, describe, expect, it } from "vitest";
import { mkdtempSync, mkdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { defineTool } from "@earendil-works/pi-coding-agent";
import { Type } from "@sinclair/typebox";
import { SessionService } from "../../src/session/manager.js";
import { FakeModel, createModelRuntime, type FakeTurnResolver } from "../../src/session/runtime.js";
import {
  activeToolsForTurn,
  readTurnControl,
  turnContextBlock,
  type TurnControl,
} from "../../src/session/turn-control.js";

const cleanups: Array<() => Promise<void>> = [];
afterEach(async () => {
  while (cleanups.length > 0) await cleanups.pop()?.();
});

function tool(name: string, execute: () => void) {
  return defineTool({
    name,
    label: name,
    description: `${name} fixture`,
    parameters: Type.Object({}, { additionalProperties: true }),
    async execute() {
      execute();
      return { content: [{ type: "text" as const, text: `${name} ok` }], details: {} };
    },
  });
}

async function fixture(script: readonly FakeTurnResolver[], reasoning = true) {
  const dir = mkdtempSync(path.join(tmpdir(), "turn-control-"));
  const agentDir = path.join(dir, "agent");
  const projectRoot = path.join(dir, "project");
  mkdirSync(agentDir, { recursive: true });
  mkdirSync(projectRoot, { recursive: true });
  const fake = await FakeModel.start(script, { reasoning });
  const { runtime } = await createModelRuntime({ providers: [fake.providerSpec()] }, { agentDir });
  const model = runtime.getModel(fake.providerId, fake.modelId);
  if (!model) throw new Error("fake model missing");
  const calls = { read: 0, edit: 0, dfm: 0 };
  const service = new SessionService({
    runtime,
    agentDir,
    model,
    customTools: [
      tool("read_part", () => { calls.read += 1; }),
      tool("inspect_part", () => { calls.read += 1; }),
      tool("edit_part", () => { calls.edit += 1; }),
      tool("run_dfm", () => { calls.dfm += 1; }),
    ],
  });
  cleanups.push(async () => {
    await service.disposeAll();
    await fake.close();
    rmSync(dir, { recursive: true, force: true });
  });
  return { fake, service, projectRoot, calls };
}

async function runTurn(
  service: SessionService,
  sessionId: string,
  runId: string,
  prompt: string,
  control: TurnControl,
): Promise<string> {
  service.beginRun(sessionId, runId);
  const applied = service.applyTurnControl(sessionId, control);
  try {
    await service.get(sessionId)?.session.prompt(prompt);
    return applied.effectiveThinkingLevel;
  } finally {
    expect(service.restoreTurnControl(sessionId, applied.previousThinkingLevel)).toBe(true);
    service.endRun(runId);
  }
}

describe("closed turn controls", () => {
  it("defaults omission and refuses null, empty, wrong-type, and unknown values", () => {
    expect(readTurnControl({})).toEqual({
      interactionMode: "modeling",
      dfmMode: "off",
      thinkingLevel: "medium",
    });
    for (const params of [
      { interaction_mode: null },
      { interaction_mode: "" },
      { interaction_mode: "execute" },
      { dfm_mode: 1 },
      { dfm_mode: "milling" },
      { thinking_level: false },
      { thinking_level: "max" },
    ]) expect(() => readTurnControl(params)).toThrow(/must be one of/);
  });

  it("uses a deliberate Plan allowlist intersected with profile permissions", () => {
    const profile = ["read_part", "edit_part", "query_snapshot", "delegate_part_agent", "get_delegation_status", "future_readish_tool"];
    expect(activeToolsForTurn(profile, "plan")).toEqual([
      "read_part", "query_snapshot", "get_delegation_status",
    ]);
    expect(activeToolsForTurn(profile, "modeling")).toEqual(profile);
  });

  it("adds bounded Plan/DFM context without claiming or invoking DFM", () => {
    expect(turnContextBlock(undefined, {
      interactionMode: "modeling", dfmMode: "off", thinkingLevel: "medium",
    })).toBeUndefined();
    const block = turnContextBlock("# Workspace context\npart: widget", {
      interactionMode: "plan", dfmMode: "sheet_metal", thinkingLevel: "high",
    });
    expect(block).toContain("# Workspace context");
    expect(block).toContain("Plan mode is active for this turn");
    expect(block).toContain("sheet-metal manufacturing");
    expect(block).toContain("Do not invoke run_dfm");
    expect(block?.length).toBeLessThan(1_000);
  });
});

describe("real Pi turn application", () => {
  it("reports Pi's effective clamp for a non-reasoning model", async () => {
    const fx = await fixture([{ kind: "text", chunks: ["done"] }], false);
    await fx.service.create({
      profile: "part", projectRoot: fx.projectRoot, part: "widget", sessionId: "plain",
    });

    const effective = await runTurn(fx.service, "plain", "plain-run", "no reasoning", {
      interactionMode: "modeling", dfmMode: "off", thinkingLevel: "high",
    });

    expect(effective).toBe("off");
    expect(JSON.parse(fx.fake.requests[0]?.bodyText ?? "{}").reasoning_effort).toBeUndefined();
  }, 30_000);

  it("allows Plan inspection, denies mutation, applies effort before prompt, then restores Modeling", async () => {
    const fx = await fixture([
      { kind: "tool_calls", calls: [
        { name: "read_part", arguments: { name: "widget" }, id: "read" },
        { name: "edit_part", arguments: { name: "widget" }, id: "edit" },
      ] },
      { kind: "text", chunks: ["plan complete"] },
    ]);
    const managed = await fx.service.create({
      profile: "part", projectRoot: fx.projectRoot, part: "widget", sessionId: "turns",
    });

    await runTurn(fx.service, "turns", "plan-run", "inspect and plan", {
      interactionMode: "plan", dfmMode: "machining", thinkingLevel: "low",
    });

    const planRequest = fx.fake.requests[0];
    expect(planRequest?.toolNames).toContain("read_part");
    expect(planRequest?.toolNames).not.toContain("edit_part");
    expect(planRequest?.toolNames).not.toContain("run_dfm");
    expect(JSON.parse(planRequest?.bodyText ?? "{}").reasoning_effort).toBe("low");
    expect(fx.calls.read).toBe(1);
    expect(fx.calls.edit).toBe(0);
    expect(fx.calls.dfm).toBe(0);
    expect(managed.session.getActiveToolNames()).toEqual(["read_part", "edit_part", "inspect_part", "run_dfm"]);
    expect(managed.session.thinkingLevel).toBe("off");

    fx.fake.setScript([
      { kind: "tool_calls", calls: [{ name: "edit_part", arguments: { name: "widget" } }] },
      { kind: "text", chunks: ["modeled"] },
    ]);
    await runTurn(fx.service, "turns", "model-run", "make it", {
      interactionMode: "modeling", dfmMode: "off", thinkingLevel: "high",
    });
    const modelingRequest = fx.fake.requests.find((request) => request.bodyText.includes("make it"));
    expect(modelingRequest?.toolNames).toEqual(["read_part", "edit_part", "inspect_part", "run_dfm"]);
    expect(JSON.parse(modelingRequest?.bodyText ?? "{}").reasoning_effort).toBe("high");
    expect(fx.calls.edit).toBe(1);
  }, 30_000);

  it("keeps effort and tools isolated across concurrent sessions", async () => {
    const resolver: FakeTurnResolver = { kind: "text", chunks: ["done"] };
    const fx = await fixture([resolver, resolver]);
    await fx.service.create({ profile: "part", projectRoot: fx.projectRoot, part: "a", sessionId: "a" });
    await fx.service.create({ profile: "part", projectRoot: fx.projectRoot, part: "b", sessionId: "b" });

    await Promise.all([
      runTurn(fx.service, "a", "run-a", "prompt-low", {
        interactionMode: "plan", dfmMode: "general", thinkingLevel: "low",
      }),
      runTurn(fx.service, "b", "run-b", "prompt-high", {
        interactionMode: "modeling", dfmMode: "off", thinkingLevel: "high",
      }),
    ]);

    const low = fx.fake.requests.find((request) => request.bodyText.includes("prompt-low"));
    const high = fx.fake.requests.find((request) => request.bodyText.includes("prompt-high"));
    expect(JSON.parse(low?.bodyText ?? "{}").reasoning_effort).toBe("low");
    expect(low?.toolNames).not.toContain("edit_part");
    expect(JSON.parse(high?.bodyText ?? "{}").reasoning_effort).toBe("high");
    expect(high?.toolNames).toContain("edit_part");
  }, 30_000);
});
