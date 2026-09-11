// Real RPC handlers and Pi tool loop, with only loopback fake model traffic.
import { expect, it } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { registerHandlers } from "../src/main.js";
import { RpcPeer } from "../src/rpc.js";
import { FakeModel } from "../src/session/runtime.js";
import type { JsonValue } from "../src/framing.js";
import type { SessionModelState } from "../src/session/model-selection.js";

it("uses the switched live model for the next explicit turn's images and provider attribution; no implicit retry", async () => {
  const dir = mkdtempSync(path.join(tmpdir(), "model-wire-"));
  const text = await FakeModel.start([], { providerId: "text-provider", modelId: "spark" });
  const vision = await FakeModel.start([], { providerId: "image-provider", modelId: "model/vision" });
  const tools = [{ kind: "tool_calls" as const, calls: [{ name: "inspect_part", arguments: { name: "widget" } }] }, { kind: "text" as const, chunks: ["done"] }];
  text.setScript(tools);
  vision.setScript(tools);
  const client = new RpcPeer(frame => { void server.handleFrame(Buffer.from(JSON.stringify(frame))); });
  const server = new RpcPeer(frame => { void client.handleFrame(Buffer.from(JSON.stringify(frame))); });
  registerHandlers(server);
  const notifications: JsonValue[] = [];
  client.onNotify("event", params => { notifications.push(params); });
  client.onNotify("terminal", params => { notifications.push(params); });
  const png = Buffer.alloc(24);
  Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]).copy(png);
  png.write("IHDR", 12); png.writeUInt32BE(2, 16); png.writeUInt32BE(2, 20);
  client.on("py.tool_dispatch", () => ({ status: "ok", source_artifact_ref: "a", render_artifact_refs: ["r"], images: [{ data: png.toString("base64"), mime_type: "image/png" }] }));
  try {
    const imageSpec = vision.providerSpec();
    if (imageSpec.kind === "pi_native") throw new Error("fake provider kind");
    await client.request("runtime.configure", { providers: [text.providerSpec(), { ...imageSpec, models: imageSpec.models.map(m => ({ ...m, input: ["text", "image"] })) }] as unknown as JsonValue });
    const created = await client.request("session.create", { profile: "orchestrator", project_root: dir, session_id: "wire", model: { provider_id: text.providerId, model_id: text.modelId } }) as { model_state: SessionModelState };
    await client.request("session.prompt", { session_id: "wire", run_id: "text-turn", prompt: "inspect", expected_model_revision: created.model_state.revision });
    expect(text.requests.at(-1)?.bodyText).toContain("image_model_required");
    expect(text.requests.at(-1)?.bodyText).not.toContain("image_url");
    const before = text.requests.length + vision.requests.length;
    const changed = await client.request("session.model.set", { session_id: "wire", model: { provider_id: vision.providerId, model_id: vision.modelId }, expected_model_revision: created.model_state.revision }) as { model_state: SessionModelState };
    expect(changed.model_state.current).toMatchObject({ provider_id: vision.providerId, model_id: vision.modelId, input: ["text", "image"] });
    expect(text.requests.length + vision.requests.length).toBe(before);
    const eventCount = notifications.length;
    await expect(client.request("session.prompt", { session_id: "wire", run_id: "stale", prompt: "don't send", expected_model_revision: created.model_state.revision })).rejects.toMatchObject({ data: { reason: "model_changed" } });
    expect(notifications).toHaveLength(eventCount);
    await client.request("session.prompt", { session_id: "wire", run_id: "vision-turn", prompt: "inspect again", expected_model_revision: changed.model_state.revision });
    expect(vision.requests.at(-1)?.bodyText).toContain("image_url");
    expect(text.requests).toHaveLength(2);
    const health = await client.request("credentials.status", { provider_id: vision.providerId });
    expect(health).toMatchObject({ health: "accepted" });
    const history = await client.request("history.page", { session_id: "wire" });
    expect(JSON.stringify(history)).toContain("inspect again");
    expect(JSON.stringify(history)).not.toContain("don't send");
  } finally {
    await text.close(); await vision.close();
    rmSync(dir, { recursive: true, force: true });
  }
});
