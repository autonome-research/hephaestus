// Real RPC admission and pinned Pi loop; all provider traffic is loopback scripted.
import { expect, it, vi } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { AgentSession, SessionManager } from "@earendil-works/pi-coding-agent";
import { extractUserPrompts, TURN_MARKER_TYPE } from "../src/session/history.js";
import { registerHandlers } from "../src/main.js";
import { RpcPeer } from "../src/rpc.js";
import { FakeModel } from "../src/session/runtime.js";
import { PLAN_TOOLS, readPrompt, readTurnControls } from "../src/session/turn-controls.js";
import { toolsForProfile, SESSION_PROFILES } from "../src/session/profiles.js";
import type { JsonValue } from "../src/framing.js";

it("defaults are closed and immutable; malformed and unknown prompt members refuse", () => {
  const base = { session_id: "s", run_id: "r", prompt: "operator" };
  expect(readPrompt(base).controls).toEqual({ interaction_mode: "modeling", dfm_mode: "off", thinking_level: "medium" });
  expect(Object.isFrozen(readPrompt(base).controls)).toBe(true);
  for (const field of ["interaction_mode", "dfm_mode", "thinking_level"]) {
    for (const value of [null, 1, false, [], {}, "", "unknown", "HIGH"]) {
      expect(() => readPrompt({ ...base, [field]: value })).toThrow();
    }
  }
  for (const params of [{ ...base, thinkingLevel: "low" }, { ...base, prompt: {} }, { ...base, context: [] }, { ...base, prompt: "x".repeat(32769) }, { ...base, prompt: "\ud800" }]) {
    expect(() => readPrompt(params)).toThrow();
  }
  for (const profile of SESSION_PROFILES) {
    const plan = toolsForProfile(profile).filter(name => PLAN_TOOLS.has(name));
    expect(plan.every(name => /^(read_|list_|search_|inspect_|compare_)/u.test(name) || ["measure", "query_snapshot", "get_delegation_status"].includes(name))).toBe(true);
    expect(plan).not.toContain("run_dfm");
    expect(plan).not.toContain("delegate_part_agent");
    expect(plan).not.toContain("record_requirements");
  }
  expect(PLAN_TOOLS.has("read_future_unclassified_tool")).toBe(false);
});

it("never invents controls for legacy, incomplete or malformed history records", () => {
  for (const turn_controls of [undefined, null, {}, { interaction_mode: "plan" }, { interaction_mode: "plan", dfm_mode: "off", thinking_level: "invalid" }]) {
    const manager = SessionManager.inMemory();
    manager.appendCustomEntry(TURN_MARKER_TYPE, { text: "operator", envelope: null, turn_controls });
    manager.appendMessage({ role: "user", content: "fused control context and operator", timestamp: 1 });
    const prompts = extractUserPrompts(manager.getEntries());
    expect(prompts[0]).toMatchObject({ text: "operator", envelope: null });
    expect(prompts[0]).not.toHaveProperty("turn_controls");
  }
});

it("keeps choices through retry, cancellation and overlapping sessions; Pi clamps nonreasoning models", async () => {
  const dir = mkdtempSync(path.join(tmpdir(), "turn-isolation-"));
  const fake = await FakeModel.start([]);
  const client = new RpcPeer(frame => { void server.handleFrame(Buffer.from(JSON.stringify(frame))); });
  const server = new RpcPeer(frame => { void client.handleFrame(Buffer.from(JSON.stringify(frame))); });
  registerHandlers(server);
  const terminals: JsonValue[] = [];
  client.onNotify("terminal", params => { terminals.push(params); });
  try {
    const spec = fake.providerSpec();
    if (spec.kind === "pi_native") throw new Error("expected loopback provider");
    const config = { providers: [{ ...spec, models: spec.models.map(model => ({ ...model, input: ["text"], reasoning: false })) }] };
    await client.request("runtime.configure", config);
    for (const session_id of ["plan", "modeling"]) {
      await client.request("session.create", { session_id, profile: "part", part: "widget", project_root: dir });
    }
    fake.setScript([{ kind: "stall" }, { kind: "text", chunks: ["other session"] }]);
    const pending = client.request("session.prompt", { session_id: "plan", run_id: "holding", prompt: "plan", interaction_mode: "plan", dfm_mode: "casting", thinking_level: "high" });
    await vi.waitFor(() => expect(fake.requests).toHaveLength(1), { timeout: 5000 });
    await expect(client.request("session.prompt", { session_id: "plan", run_id: "contender", prompt: "change mode", interaction_mode: "modeling" })).rejects.toMatchObject({ data: { reason: "run_in_flight" } });
    await client.request("session.prompt", { session_id: "modeling", run_id: "other", prompt: "model" });
    expect(fake.requests[0]?.toolNames).toEqual(toolsForProfile("part").filter(name => PLAN_TOOLS.has(name)));
    expect(fake.requests[1]?.toolNames).toEqual(toolsForProfile("part"));
    expect(fake.requests[0]?.bodyText).not.toContain("reasoning_effort");
    expect(fake.requests[1]?.bodyText).not.toContain("casting");
    await client.request("session.cancel", { run_id: "holding" });
    await expect(pending).resolves.toMatchObject({ status: "cancelled" });
    await client.request("session.cancel", { run_id: "holding" }); // idempotent

    fake.setScript([{ kind: "error", message: "WebSocket error", status: 400 }, { kind: "text", chunks: ["retried"] }]);
    const before = fake.requests.length;
    await expect(client.request("session.prompt", { session_id: "plan", run_id: "retry", prompt: "operator retry request", interaction_mode: "plan", dfm_mode: "additive", thinking_level: "low" })).resolves.toMatchObject({ status: "completed" });
    expect(fake.requests.length - before).toBe(2);
    for (const request of fake.requests.slice(before)) {
      expect(request.toolNames).toEqual(toolsForProfile("part").filter(name => PLAN_TOOLS.has(name)));
      expect(request.bodyText).toContain("additive manufacturing");
      expect(request.bodyText).not.toContain("reasoning_effort");
    }
    expect(await client.request("history.page", { session_id: "plan" })).toMatchObject({ user_prompts: expect.arrayContaining([
      expect.objectContaining({ origin: "agent", run_id: "retry", turn_controls: { interaction_mode: "plan", dfm_mode: "additive", thinking_level: "low" } }),
    ]) });
    const beforeFailure = fake.requests.length;
    const setter = vi.spyOn(AgentSession.prototype, "setThinkingLevel").mockImplementationOnce(() => { throw new Error("synthetic SDK persistence failure"); });
    try {
      await expect(client.request("session.prompt", { session_id: "plan", run_id: "sdk-failure", prompt: "never contact provider" })).resolves.toMatchObject({ status: "failed" });
      expect(fake.requests).toHaveLength(beforeFailure);
      expect(terminals).toContainEqual(expect.objectContaining({ run_id: "sdk-failure", state: "failed" }));
    } finally { setter.mockRestore(); }
    fake.setScript([{ kind: "text", chunks: ["restored after cancel and retry"] }]);
    await client.request("session.prompt", { session_id: "plan", run_id: "restored", prompt: "default" });
    expect(fake.requests.at(-1)?.toolNames).toEqual(toolsForProfile("part"));
  } finally {
    await client.request("session.cancel", { run_id: "holding" });
    await fake.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

it("keeps Plan and effort through a queued Pi continuation and cancellation at retry audit", async () => {
  const dir = mkdtempSync(path.join(tmpdir(), "turn-queued-"));
  const fake = await FakeModel.start([]);
  const client = new RpcPeer(frame => { void server.handleFrame(Buffer.from(JSON.stringify(frame))); });
  const server = new RpcPeer(frame => { void client.handleFrame(Buffer.from(JSON.stringify(frame))); });
  registerHandlers(server);
  const dispatched: JsonValue[] = [];
  client.on("py.tool_dispatch", params => { dispatched.push(params); throw new Error("unexpected mutation"); });
  const ask = vi.fn(() => { throw new Error("cancelled run must not ask a budget question"); });
  client.on("py.ask_user", ask);
  let cancellation: Promise<JsonValue> | undefined;
  client.onNotify("event", params => {
    if (params.kind === "audit" && typeof params.payload === "object" && params.payload !== null &&
        !Array.isArray(params.payload) && params.payload.event === "turn_retry") {
      cancellation = client.request("session.cancel", { run_id: "cancel-retry" });
    }
  });
  const original = AgentSession.prototype.sendUserMessage;
  const sender = vi.spyOn(AgentSession.prototype, "sendUserMessage");
  try {
    const spec = fake.providerSpec();
    if (spec.kind === "pi_native") throw new Error("expected loopback provider");
    await client.request("runtime.configure", { providers: [{ ...spec, models: spec.models.map(model => ({ ...model, input: ["text"], reasoning: true })) }] });
    await client.request("session.create", { session_id: "s", profile: "orchestrator", project_root: dir });
    sender.mockImplementationOnce(function (this: AgentSession, content, options) {
      // Exercise Pi's real queue, not a second RPC (which admission refuses).
      // No production extension currently queues this; it guards the SDK path.
      let queued: Promise<void> | undefined;
      const unsubscribe = this.subscribe(event => {
        if (event.type === "message_end" && event.message.role === "assistant" && !queued) {
          queued = this.followUp("queued continuation: create a part now");
        }
      });
      return original.call(this, content, options).finally(async () => {
        unsubscribe();
        await queued;
      });
    });
    fake.setScript([
      { kind: "text", chunks: ["initial plan"] },
      { kind: "tool_calls", calls: [{ name: "create_part", arguments: { name: "forged", description: "queued write" } }] },
      { kind: "text", chunks: ["still inspection only"] },
    ]);
    await expect(client.request("session.prompt", { session_id: "s", run_id: "queue", prompt: "inspect", interaction_mode: "plan", dfm_mode: "casting", thinking_level: "high" })).resolves.toMatchObject({ status: "completed" });
    expect(fake.requests).toHaveLength(3);
    for (const request of fake.requests) {
      expect(request.toolNames).toEqual(toolsForProfile("orchestrator").filter(name => PLAN_TOOLS.has(name)));
      expect(request.bodyText).toContain('"reasoning_effort":"high"');
      expect(request.bodyText).toContain("casting");
    }
    expect(fake.requests.at(-1)?.bodyText).toContain("Tool create_part not found");
    expect(dispatched).toEqual([]);
    fake.setScript([{ kind: "error", message: "WebSocket error", status: 400 }, { kind: "text", chunks: ["must not retry"] }]);
    const usage = vi.spyOn(AgentSession.prototype, "getContextUsage").mockReturnValue({ tokens: 95, contextWindow: 100, percent: 95 });
    const compact = vi.spyOn(AgentSession.prototype, "compact").mockRejectedValue(new Error("cancelled run must not compact"));
    try {
      await expect(client.request("session.prompt", { session_id: "s", run_id: "cancel-retry", prompt: "inspect", interaction_mode: "plan" })).resolves.toMatchObject({ status: "cancelled" });
      expect(cancellation).toBeDefined();
      await cancellation;
      expect(fake.requests).toHaveLength(4);
      expect(compact).not.toHaveBeenCalled();
      // Stop between maintenance actions must also prevent the queued budget
      // question, and must not report the earlier completed provider outcome.
      fake.setScript([{ kind: "text", chunks: ["finished before Stop"] }]);
      compact.mockImplementationOnce(async () => {
        await client.request("session.cancel", { run_id: "cancel-maintenance" });
        return { summary: "compacted", firstKeptEntryId: "entry", tokensBefore: 95 };
      });
      await expect(client.request("session.prompt", { session_id: "s", run_id: "cancel-maintenance", prompt: "inspect", interaction_mode: "plan" })).resolves.toMatchObject({ status: "cancelled" });
      expect(compact).toHaveBeenCalledTimes(1);
      expect(ask).not.toHaveBeenCalled();
    } finally {
      usage.mockRestore();
      compact.mockRestore();
    }
    fake.setScript([{ kind: "text", chunks: ["ordinary legacy call"] }]);
    await client.request("session.prompt", { session_id: "s", run_id: "restored", prompt: "model" });
    expect(fake.requests.at(-1)?.toolNames).toEqual(toolsForProfile("orchestrator"));
  } finally {
    sender.mockRestore();
    await fake.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

it("propagates every control, enforces Plan against forged calls, restores Modeling, and records exact operator text", async () => {
  const dir = mkdtempSync(path.join(tmpdir(), "turn-controls-"));
  const fake = await FakeModel.start([]);
  const client = new RpcPeer(frame => { void server.handleFrame(Buffer.from(JSON.stringify(frame))); });
  const server = new RpcPeer(frame => { void client.handleFrame(Buffer.from(JSON.stringify(frame))); });
  registerHandlers(server);
  const dispatched: JsonValue[] = [];
  client.on("py.tool_dispatch", params => { dispatched.push(params); throw new Error("test dispatch reached; no CAD execution"); });
  client.on("py.delegate", params => { dispatched.push(params); throw new Error("unexpected delegation"); });
  client.on("py.ask_user", params => { dispatched.push(params); throw new Error("unexpected question"); });
  try {
    const spec = fake.providerSpec();
    if (spec.kind === "pi_native") throw new Error("expected loopback provider");
    const config = { providers: [{ ...spec, models: spec.models.map(model => ({ ...model, input: [...(model.input ?? ["text"])], reasoning: true })) }] };
    await client.request("runtime.configure", config);
    await client.request("session.create", { profile: "orchestrator", project_root: dir, session_id: "s" });
    const prompt = (run: string, options: Record<string, JsonValue> = {}) => client.request("session.prompt", {
      session_id: "s", run_id: run, prompt: "make 12 mm part", context: "workspace 99 mm", ...options,
    });
    for (const options of [{ interaction_mode: "PLAN" }, { thinking_level: null }, { dfm_mode: [] }, { unknown: "field" }]) {
      await expect(prompt("invalid", options)).rejects.toMatchObject({ data: { reason: "invalid_params" } });
    }
    expect(fake.requests).toHaveLength(0);
    expect(await client.request("history.page", { session_id: "s" })).toMatchObject({ user_prompts: [] });

    for (const name of ["write_part", "build_part", "delegate_part_agent", "run_dfm", "ask_user"]) {
      fake.setScript([{ kind: "tool_calls", calls: [{ name, arguments: { name: "widget", content: "forged" } }] }, { kind: "text", chunks: ["refused"] }]);
      const before = fake.requests.length;
      await expect(prompt(`plan-${name}`, { interaction_mode: "plan", thinking_level: "high", dfm_mode: "machining" })).resolves.toMatchObject({ status: "completed" });
      expect(fake.requests[before]?.toolNames).toEqual(toolsForProfile("orchestrator").filter(tool => PLAN_TOOLS.has(tool)));
      expect(fake.requests[before]?.bodyText).toContain('"reasoning_effort":"high"');
      expect(fake.requests.at(-1)?.bodyText).toContain(`Tool ${name} not found`);
    }
    expect(dispatched).toHaveLength(0);

    // Same session, next turn: normal defaults restore all profile tools and medium.
    fake.setScript([{ kind: "tool_calls", calls: [{ name: "create_part", arguments: { name: "widget", description: "test" } }] }, { kind: "text", chunks: ["done"] }]);
    const before = fake.requests.length;
    await prompt("modeling");
    expect(fake.requests[before]?.toolNames).toEqual(toolsForProfile("orchestrator"));
    expect(fake.requests[before]?.bodyText).toContain('"reasoning_effort":"medium"');
    expect(dispatched).toHaveLength(1);

    const labels = { off: "No manufacturing-review context", general: "general manufacturing", additive: "additive manufacturing", sheet_metal: "sheet metal", machining: "machining", casting: "casting" };
    for (const [dfm, label] of Object.entries(labels)) {
      fake.setScript([{ kind: "text", chunks: ["review only"] }]);
      await prompt(`dfm-${dfm}`, { dfm_mode: dfm, thinking_level: "low" });
      const request = fake.requests.at(-1);
      expect(request?.bodyText).toContain(label);
      expect(request?.bodyText).toContain('"reasoning_effort":"low"');
    }
    expect(dispatched).toHaveLength(1); // choosing DFM never calls a tool
    const history = await client.request("history.page", { session_id: "s" });
    expect(history).toMatchObject({ user_prompts: expect.arrayContaining([
      expect.objectContaining({ text: "make 12 mm part", envelope: "workspace 99 mm", turn_controls: { interaction_mode: "plan", dfm_mode: "machining", thinking_level: "high" } }),
      expect.objectContaining({ run_id: "modeling", text: "make 12 mm part", turn_controls: readTurnControls({}) }),
    ]) });
    await client.request("runtime.configure", config);
    await client.request("session.create", { profile: "orchestrator", project_root: dir, session_id: "s", resume: true });
    expect(await client.request("history.page", { session_id: "s" })).toEqual(history);
  } finally {
    await fake.close();
    rmSync(dir, { recursive: true, force: true });
  }
});
