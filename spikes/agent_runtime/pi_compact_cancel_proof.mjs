// Bonus proof for mission Stage S item (d): compaction and cancel (abort)
// on a Pi SDK session driven entirely by local fake servers.
import { mkdtempSync } from "node:fs";
import http from "node:http";
import { tmpdir } from "node:os";
import path from "node:path";
import { Type } from "typebox";
import { createAgentSession, defineTool, ModelRuntime, SessionManager, SettingsManager } from "@earendil-works/pi-coding-agent";
import { startFakeServer } from "./fake_openai_server.mjs";

const assert = (cond, msg) => { if (!cond) throw new Error(`ASSERT FAILED: ${msg}`); console.log(`ok: ${msg}`); };
const scratch = mkdtempSync(path.join(tmpdir(), "heph-pi-spike2-"));
const agentDir = path.join(scratch, "agent-dir");

const makeRuntime = async (port) => {
  const rt = await ModelRuntime.create({
    authPath: path.join(agentDir, "auth.json"), modelsPath: null,
    modelsStorePath: path.join(agentDir, "models-store.json"), allowModelNetwork: false,
  });
  rt.registerProvider("heph-fake", {
    name: "Heph Fake", baseUrl: `http://127.0.0.1:${port}/v1`, apiKey: "fake", api: "openai-completions",
    models: [{ id: "heph-fake-model", name: "Fake", reasoning: false, input: ["text"], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 128000, maxTokens: 4096 }],
  });
  return rt;
};
const hephFake = defineTool({
  name: "heph_fake", label: "Heph Fake", description: "fake tool",
  parameters: Type.Object({ ping: Type.String() }),
  async execute(id, params) { return { content: [{ type: "text", text: `pong ${params.ping}` }], details: {} }; },
});

// ---- Part 1: compaction ----
{
  const { server, port } = await startFakeServer();
  const modelRuntime = await makeRuntime(port);
  const model = modelRuntime.getModel("heph-fake", "heph-fake-model");
  const { session } = await createAgentSession({
    cwd: scratch, agentDir, modelRuntime, model, thinkingLevel: "off",
    tools: ["heph_fake"], customTools: [hephFake],
    sessionManager: SessionManager.create(scratch, path.join(scratch, "sessions")),
    // Default keepRecentTokens is 20000 — a tiny fixture session never crosses
    // it, so compact() reports "Nothing to compact". Shrink the window.
    settingsManager: SettingsManager.inMemory({ compaction: { enabled: true, reserveTokens: 100, keepRecentTokens: 10 } }),
  });
  const events = [];
  session.subscribe((ev) => events.push(ev.type));
  // Compaction refuses tiny sessions ("Nothing to compact"); build up a few
  // real tool-roundtrip turns first.
  for (let i = 0; i < 4; i++) await session.prompt(`call the tool (turn ${i})`);
  const before = session.messages.length;
  const result = await session.compact("keep it terse");
  assert(events.includes("compaction_start") && events.includes("compaction_end"), "compaction_start/end events fired");
  assert(result && typeof result.summary === "string" && result.summary.length > 0, `compact() returned summary: "${result.summary}"`);
  console.log(`messages before=${before} after=${session.messages.length}; compaction result keys: ${Object.keys(result)}`);
  session.dispose(); server.close();
}

// ---- Part 2: cancel/abort mid-stream against a stalling server ----
{
  const stalling = http.createServer((req, res) => {
    res.writeHead(200, { "content-type": "text/event-stream" });
    res.write(`data: ${JSON.stringify({ id: "c", object: "chat.completion.chunk", created: 0, model: "heph-fake-model", choices: [{ index: 0, delta: { role: "assistant", content: "thinking..." }, finish_reason: null }] })}\n\n`);
    // ...then never send more; hold the connection open.
  });
  const port = await new Promise((r) => stalling.listen(0, "127.0.0.1", () => r(stalling.address().port)));
  const modelRuntime = await makeRuntime(port);
  const model = modelRuntime.getModel("heph-fake", "heph-fake-model");
  const { session } = await createAgentSession({
    cwd: scratch, agentDir, modelRuntime, model, thinkingLevel: "off",
    tools: ["heph_fake"], customTools: [hephFake],
    sessionManager: SessionManager.inMemory(scratch),
  });
  const t0 = Date.now();
  const p = session.prompt("this will stall");
  await new Promise((r) => setTimeout(r, 500));
  assert(session.isStreaming, "session is streaming against stalled server");
  await session.abort();
  await p;
  assert(!session.isStreaming, `abort() cancelled the stalled stream in ${Date.now() - t0}ms total`);
  session.dispose(); stalling.closeAllConnections(); stalling.close();
}
console.log("COMPACT+CANCEL PROOF COMPLETE");
process.exit(0);
