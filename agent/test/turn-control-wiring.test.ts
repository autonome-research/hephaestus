// Full session.prompt RPC -> real pinned Pi session, with loopback HTTP only.
import { expect, it } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { registerHandlers } from "../src/main.js";
import { RpcPeer } from "../src/rpc.js";
import { FakeModel } from "../src/session/runtime.js";
import type { JsonValue } from "../src/framing.js";
import type { SessionModelState } from "../src/session/model-selection.js";

it("validates, persists, applies, and restores per-turn controls through RPC", async () => {
  const dir = mkdtempSync(path.join(tmpdir(), "turn-wire-"));
  const fake = await FakeModel.start([
    { kind: "text", chunks: ["plan"] },
    { kind: "error", status: 400, message: "deliberate failure" },
    { kind: "text", chunks: ["model"] },
    { kind: "text", chunks: ["defaults"] },
  ], { reasoning: true });
  const client = new RpcPeer((frame) => { void server.handleFrame(Buffer.from(JSON.stringify(frame))); });
  const server = new RpcPeer((frame) => { void client.handleFrame(Buffer.from(JSON.stringify(frame))); });
  registerHandlers(server);
  try {
    await client.request("runtime.configure", {
      providers: [fake.providerSpec() as unknown as JsonValue],
    });
    const created = await client.request("session.create", {
      profile: "part",
      project_root: dir,
      part: "widget",
      session_id: "controlled",
    }) as { model_state: SessionModelState };

    const invalidValues = [
      { interaction_mode: null },
      { interaction_mode: "" },
      { interaction_mode: "execute" },
      { dfm_mode: 4 },
      { dfm_mode: "milling" },
      { thinking_level: false },
      { thinking_level: "max" },
    ];
    for (const invalid of invalidValues) {
      await expect(client.request("session.prompt", {
        session_id: "controlled", run_id: `invalid-${JSON.stringify(invalid)}`,
        prompt: "must not run", ...invalid,
      })).rejects.toMatchObject({ data: { reason: "invalid_params" } });
    }
    expect(fake.requests).toHaveLength(0);

    const planResult = await client.request("session.prompt", {
      session_id: "controlled",
      run_id: "plan",
      prompt: "inspect the bracket",
      interaction_mode: "plan",
      dfm_mode: "machining",
      thinking_level: "high",
      expected_model_revision: created.model_state.revision,
    }) as { effective_thinking_level: string };
    expect(planResult.effective_thinking_level).toBe("high");
    const plan = fake.requests[0];
    expect(plan?.toolNames).toContain("read_part");
    expect(plan?.toolNames).toContain("inspect_part");
    expect(plan?.toolNames).not.toContain("edit_part");
    expect(plan?.toolNames).not.toContain("run_dfm");
    expect(plan?.bodyText).toContain("Plan mode is active for this turn");
    expect(plan?.bodyText).toContain("machining");
    expect(plan?.bodyText).toContain("Do not invoke run_dfm");
    expect(JSON.parse(plan?.bodyText ?? "{}").reasoning_effort).toBe("high");

    // A failed Plan turn must execute the same finally-path restoration before
    // a subsequent Modeling turn. The explicit Modeling snapshot also reapplies
    // the immutable profile set, so both protections are exercised.
    const failed = await client.request("session.prompt", {
      session_id: "controlled",
      run_id: "failed-plan",
      prompt: "this provider request fails",
      interaction_mode: "plan",
      dfm_mode: "off",
      thinking_level: "low",
    }) as { status: string };
    expect(failed.status).toBe("failed");

    await client.request("session.prompt", {
      session_id: "controlled",
      run_id: "model",
      prompt: "model the bracket",
      interaction_mode: "modeling",
      dfm_mode: "off",
      thinking_level: "low",
    });
    const modeling = fake.requests.find((request) => request.bodyText.includes("model the bracket"));
    expect(modeling?.toolNames).toContain("edit_part");
    expect(modeling?.toolNames).toContain("run_dfm");
    expect(JSON.parse(modeling?.bodyText ?? "{}").reasoning_effort).toBe("low");

    await client.request("session.prompt", {
      session_id: "controlled", run_id: "defaults", prompt: "use defaults",
    });
    const defaults = fake.requests.find((request) => request.bodyText.includes("use defaults"));
    expect(defaults?.toolNames).toContain("edit_part");
    expect(JSON.parse(defaults?.bodyText ?? "{}").reasoning_effort).toBe("medium");

    fake.setScript([{ kind: "stall" }, { kind: "text", chunks: ["after cancel"] }]);
    const requestCount = fake.requests.length;
    const pendingCancel = client.request("session.prompt", {
      session_id: "controlled",
      run_id: "cancelled-plan",
      prompt: "stall in plan",
      interaction_mode: "plan",
      dfm_mode: "general",
      thinking_level: "high",
    }) as Promise<{ status: string }>;
    for (let attempt = 0; attempt < 100 && fake.requests.length === requestCount; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 5));
    }
    expect(fake.requests.length).toBeGreaterThan(requestCount);
    await client.request("session.cancel", { run_id: "cancelled-plan" });
    await expect(pendingCancel).resolves.toMatchObject({ status: "cancelled" });

    await client.request("session.prompt", {
      session_id: "controlled",
      run_id: "after-cancel",
      prompt: "model after cancellation",
      interaction_mode: "modeling",
      dfm_mode: "off",
      thinking_level: "medium",
    });
    const afterCancel = fake.requests.find((request) => request.bodyText.includes("model after cancellation"));
    expect(afterCancel?.toolNames).toContain("edit_part");
    expect(JSON.parse(afterCancel?.bodyText ?? "{}").reasoning_effort).toBe("medium");

    const history = await client.request("history.page", { session_id: "controlled" }) as {
      user_prompts: Array<{ run_id?: string; effective_thinking_level?: string }>;
    };
    expect(history.user_prompts.find((prompt) => prompt.run_id === "plan")?.effective_thinking_level).toBe("high");
    const historyText = JSON.stringify(history);
    expect(historyText).toContain("Plan mode is active for this turn");
    expect(historyText).toContain("machining");
    expect(historyText).toContain("inspect the bracket");
  } finally {
    await fake.close();
    rmSync(dir, { recursive: true, force: true });
  }
}, 30_000);
