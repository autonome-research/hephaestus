// Negative Sol transport: real pinned Pi session + real ToolProxy, synthetic
// bridge results. Positive real-CAD/browser identity is web/e2e/image-identity.
import { createServer } from "node:http";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { zstdDecompressSync } from "node:zlib";
import { describe, it, expect, vi } from "vitest";
import { defineTool, SettingsManager } from "@earendil-works/pi-coding-agent";
import { Type } from "@sinclair/typebox";
import { createModelRuntime } from "../src/session/runtime.js";
import { SessionService } from "../src/session/manager.js";
import { ToolProxy } from "../src/tools/proxy.js";
import { makeInvocation } from "../src/tools/invocation.js";
import { LIMITS } from "../src/limits.js";
import { renderRef } from "../src/image-identity.js";
import type { JsonValue } from "../src/framing.js";

function bridgeResult(fault: string): JsonValue {
  const bytes = Buffer.alloc(24);
  Buffer.from("89504e470d0a1a0a", "hex").copy(bytes);
  bytes.write("IHDR", 12); bytes.writeUInt32BE(fault === "dimensions" ? 4097 : 2, 16); bytes.writeUInt32BE(2, 20);
  const ref = renderRef(bytes);
  const source = `artifact:build:sha256:${"a".repeat(64)}`;
  const image = { part: "p", view: "iso", channel: "rgb", source_artifact_ref: source, render_artifact_ref: ref, mime_type: fault === "mime" ? "image/jpeg" : "image/png", data: bytes.toString("base64") + (fault === "base64" ? "!" : "") };
  if (fault === "hash") image.render_artifact_ref = `artifact:render:sha256:${"b".repeat(64)}`;
  return { status: "ok", source_artifact_ref: source, render_artifact_refs: [ref], images: Array.from({ length: fault === "count" ? 5 : 1 }, () => image) };
}

describe("pinned Sol fail-closed image inputs over actual HTTP", () => {
  // capability-gate injects a false proxy capability (defensive unit seam).
  // Actual text-only admission with Sol available is the packaged browser case.
  it.each(["base64", "hash", "mime", "dimensions", "count", "capability-gate"])("%s sends zero input_image blocks", async fault => {
    const dir = mkdtempSync(path.join(tmpdir(), "heph-sol-negative-"));
    const agentDir = path.join(dir, "agent"); const projectRoot = path.join(dir, "project");
    mkdirSync(agentDir); mkdirSync(projectRoot);
    const access = `synthetic.${Buffer.from(JSON.stringify({ "https://api.openai.com/auth": { chatgpt_account_id: "owned-negative" } })).toString("base64")}.not-a-signature`;
    writeFileSync(path.join(agentDir, "auth.json"), JSON.stringify({ "openai-codex": { type: "oauth", access, refresh: "unused", expires: Date.now() + 3600000 } }), { mode: 0o600 });
    const requests: { model: string; input: { type: string; output?: unknown }[] }[] = [];
    const errors: string[] = [];
    const server = createServer((req, res) => {
      void (async () => {
        expect(req.url).toBe("/codex/responses");
        expect(requests.length).toBeLessThan(2);
        const chunks: Buffer[] = []; let length = 0;
        for await (const chunk of req) { length += (chunk as Buffer).length; expect(length).toBeLessThanOrEqual(LIMITS.wire.max_frame_bytes); chunks.push(chunk as Buffer); }
        const wire = Buffer.concat(chunks);
        const raw = req.headers["content-encoding"] === "zstd" ? zstdDecompressSync(wire, { maxOutputLength: LIMITS.wire.max_frame_bytes }) : wire;
        const body = JSON.parse(raw.toString("utf8")) as typeof requests[number];
        expect(body.model).toBe("gpt-5.6-sol");
        expect(raw.toString("utf8")).not.toContain('"type":"input_image"');
        requests.push(body);
        const item = requests.length === 1
          ? { type: "function_call", id: "fc_negative", call_id: "negative_call", name: "inspect_part", arguments: '{"name":"p"}' }
          : { type: "message", id: "msg_negative", role: "assistant", content: [{ type: "output_text", text: "REFUSAL_TRANSPORT_ONLY", annotations: [] }] };
        const events = [{ type: "response.output_item.done", output_index: 0, item }, { type: "response.completed", response: { id: "resp_negative", status: "completed", output: [item] } }];
        res.writeHead(200, { "content-type": "text/event-stream" });
        res.end(events.map(event => `data: ${JSON.stringify(event)}\n\n`).join(""));
      })().catch(error => { errors.push(String(error)); res.writeHead(400); res.end("negative fixture assertion failed"); });
    });
    await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    if (!address || typeof address === "string") throw Error("missing loopback address");
    const endpoint = `http://127.0.0.1:${address.port}`;
    const originalFetch = globalThis.fetch;
    const denied: string[] = [];
    vi.stubGlobal("fetch", ((input: Parameters<typeof fetch>[0], init?: RequestInit) => {
      const url = new URL(input instanceof Request ? input.url : String(input));
      if (url.origin !== endpoint) { denied.push(url.origin); throw Error("non-loopback fixture request refused"); }
      return originalFetch(input, { ...init, redirect: "error" });
    }) as typeof fetch);
    let service: SessionService | undefined;
    try {
      const { runtime } = await createModelRuntime({ providers: [{ id: "openai-codex", kind: "pi_native", models: [{ id: "gpt-5.6-sol" }] }] }, { agentDir });
      // Pinned API: endpoint-only provider override preserves native metadata.
      runtime.registerProvider("openai-codex", { baseUrl: endpoint });
      const model = runtime.getModel("openai-codex", "gpt-5.6-sol");
      expect(model).toMatchObject({ api: "openai-codex-responses", input: ["text", "image"], contextWindow: 372000, maxTokens: 128000 });
      if (!model) throw Error("pinned Sol missing");
      const proxy = new ToolProxy(async () => bridgeResult(fault));
      service = new SessionService({ runtime, agentDir, model,
        settings: () => SettingsManager.inMemory({ transport: "sse", retry: { enabled: false }, compaction: { enabled: false } }),
        customTools: [defineTool({ name: "inspect_part", label: "Inspect", description: "Negative bridge fixture", parameters: Type.Object({ name: Type.String() }),
          execute: async (_id, args) => proxy.execute("inspect_part", args, { sessionId: "s", runId: "r", imagesSupported: fault !== "capability-gate", invocation: makeInvocation({ sessionId: "s", entryId: "e", ordinal: 0, providerCallId: "negative_call" }) }),
        })],
      });
      const managed = await service.create({ profile: "part", projectRoot, part: "p", sessionId: "s" });
      await managed.session.prompt("Exercise the negative bridge fixture once.");
      expect(requests).toHaveLength(2);
      const outputs = requests[1]!.input.filter(item => item.type === "function_call_output");
      expect(outputs).toHaveLength(1);
      expect(typeof outputs[0]?.output).toBe("string");
      expect(String(outputs[0]?.output)).toMatch(fault === "capability-gate" ? /image_model_required/ : /image|images/i);
      expect(denied).toEqual([]); expect(errors).toEqual([]);
      writeFileSync(path.join(dir, "proof.json"), JSON.stringify({ fault, model: model.id, api: model.api, requests: requests.length, input_images: 0, output: outputs[0]?.output, denied, errors }));
    } finally {
      await service?.disposeAll();
      vi.unstubAllGlobals();
      server.closeAllConnections();
      await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
    }
  }, 30_000);
});
