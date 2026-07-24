// Spike D+G runtime proof:
//  - Pi SDK session with ALL built-in coding tools disabled (noTools: "all")
//  - one custom tool `heph_fake` registered via `customTools` + defineTool
//  - ModelRuntime pointed at a local fake OpenAI-compatible server via
//    registerProvider({ baseUrl, api: "openai-completions" }) — programmatic,
//    no extension file, no ambient ~/.pi state (agentDir/authPath sandboxed)
//  - proves: tool executes, text/tool events stream, session file persisted
//    in an app-owned directory, and a second session resumes from it.
import { mkdtempSync, existsSync, readdirSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { Type } from "typebox";
import {
  createAgentSession,
  defineTool,
  ModelRuntime,
  SessionManager,
} from "@earendil-works/pi-coding-agent";
import { startFakeServer } from "./fake_openai_server.mjs";

const scratch = mkdtempSync(path.join(tmpdir(), "heph-pi-spike-"));
const agentDir = path.join(scratch, "agent-dir");
const sessionDir = path.join(scratch, "sessions"); // app-owned session directory
const cwd = scratch;

const { server, port, requests } = await startFakeServer((m) => console.log(m));
console.log(`fake server on 127.0.0.1:${port}`);

// --- ModelRuntime with a custom OpenAI-compatible provider ---
const modelRuntime = await ModelRuntime.create({
  authPath: path.join(agentDir, "auth.json"),
  modelsPath: null, // do not read any models.json
  modelsStorePath: path.join(agentDir, "models-store.json"),
  allowModelNetwork: false,
});
modelRuntime.registerProvider("heph-fake", {
  name: "Hephaestus Fake Provider",
  baseUrl: `http://127.0.0.1:${port}/v1`,
  apiKey: "fake-key-not-a-secret",
  api: "openai-completions",
  models: [{
    id: "heph-fake-model", name: "Heph Fake Model", reasoning: false,
    input: ["text"], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    contextWindow: 128000, maxTokens: 4096,
  }],
});
const model = modelRuntime.getModel("heph-fake", "heph-fake-model");
if (!model) throw new Error("custom provider model not found in ModelRuntime");
console.log(`model resolved: ${model.provider}/${model.id} baseUrl=${model.baseUrl}`);

// --- custom tool ---
let toolExecuted = null;
const hephFake = defineTool({
  name: "heph_fake",
  label: "Heph Fake",
  description: "Fake Hephaestus tool; echoes the ping.",
  parameters: Type.Object({ ping: Type.String() }),
  async execute(toolCallId, params) {
    toolExecuted = { toolCallId, params };
    return { content: [{ type: "text", text: `heph_fake received ping=${params.ping}` }], details: { ok: true } };
  },
});

// --- session with all built-in coding tools disabled ---
const { session } = await createAgentSession({
  cwd,
  agentDir,
  modelRuntime,
  model,
  thinkingLevel: "off",
  // Allowlist: ONLY heph_fake. (noTools:"all" empties even custom tools;
  // noTools:"builtin" also works — the allowlist is the strictest form.)
  tools: ["heph_fake"],
  customTools: [hephFake],
  sessionManager: SessionManager.create(cwd, sessionDir),
});

const toolNames = session.agent.state.tools.map((t) => t.name);
console.log(`session tools: [${toolNames}]`);
if (toolNames.some((n) => ["read", "bash", "edit", "write", "grep", "find", "ls"].includes(n)))
  throw new Error("built-in coding tools still enabled");
if (!toolNames.includes("heph_fake")) throw new Error("heph_fake not registered");

const events = [];
let streamedText = "";
session.subscribe((ev) => {
  events.push(ev.type);
  if (ev.type === "message_update" && ev.assistantMessageEvent?.type === "text_delta")
    streamedText += ev.assistantMessageEvent.delta;
  if (ev.type === "tool_execution_start") console.log(`event: tool_execution_start ${ev.toolName}`);
  if (ev.type === "tool_execution_end") console.log(`event: tool_execution_end isError=${ev.isError}`);
});

await session.prompt("Call the heph_fake tool once, then summarize.");

// --- assertions ---
const assert = (cond, msg) => { if (!cond) throw new Error(`ASSERT FAILED: ${msg}`); console.log(`ok: ${msg}`); };
assert(toolExecuted?.params?.ping === "from-fake-server", "heph_fake executed with streamed tool-call args");
assert(events.includes("tool_execution_start") && events.includes("tool_execution_end"), "tool events streamed");
assert(streamedText.includes("HEPH_FINAL:"), `final text streamed via text_delta (got: "${streamedText}")`);
assert(requests.length === 2, `fake server saw 2 model requests (saw ${requests.length})`);
assert(requests[0].toolNamesOffered.length === 1 && requests[0].toolNamesOffered[0] === "heph_fake",
  "exactly one tool (heph_fake) offered to the model");
const sessionFile = session.sessionFile;
assert(sessionFile && existsSync(sessionFile), `session persisted at ${sessionFile}`);
assert(sessionFile.startsWith(sessionDir), "session file lives in the app-owned session directory");
const lineCount = readFileSync(sessionFile, "utf8").trim().split("\n").length;
console.log(`session file entries (jsonl lines): ${lineCount}`);
session.dispose();

// --- resume from the app-owned directory in a fresh SessionManager ---
const resumed = await createAgentSession({
  cwd,
  agentDir,
  modelRuntime,
  model,
  tools: ["heph_fake"],
  customTools: [hephFake],
  sessionManager: SessionManager.continueRecent(cwd, sessionDir),
});
assert(resumed.session.messages.length >= 3,
  `resumed session reloaded ${resumed.session.messages.length} messages (user, assistant tool-call, tool result, final)`);
assert(resumed.session.sessionFile === sessionFile, "resume picked the same session file");
resumed.session.dispose();

server.close();
console.log("PROOF COMPLETE");
console.log(JSON.stringify({ sessionDirListing: readdirSync(sessionDir, { recursive: true }) }));
process.exit(0);
