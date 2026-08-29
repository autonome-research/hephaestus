// Session lifecycle + isolation over real Pi sessions driven by the scripted
// FakeModel (an in-process OpenAI-compatible server). No network, no real model,
// no global pi/thread-phase install is resolved.
import { describe, it, expect, afterEach } from "vitest";
import { mkdtempSync, mkdirSync, writeFileSync, existsSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { defineTool, SettingsManager } from "@earendil-works/pi-coding-agent";
import { Type } from "@sinclair/typebox";
import { FakeModel, createModelRuntime, type FakeTurnResolver, type FakeModelOptions } from "../../src/session/runtime.js";
import { SessionService } from "../../src/session/manager.js";
import { formatPinnedSummary, PINNED_SUMMARY_OPEN, type PinnedCadSummary } from "../../src/session/context.js";

interface ToolProbe {
  count: number;
}

// A custom "inspect_part" tool (a name already in the part profile allowlist).
function makeInspectTool(probe: ToolProbe) {
  return defineTool({
    name: "inspect_part",
    label: "Inspect Part",
    description: "Fake inspect that returns a render description.",
    parameters: Type.Object({}, { additionalProperties: true }),
    async execute() {
      probe.count += 1;
      return { content: [{ type: "text", text: "rendered iso view" }], details: {} };
    },
  });
}

interface Fixture {
  dir: string;
  agentDir: string;
  projectRoot: string;
  fake: FakeModel;
  service: SessionService;
  probe: ToolProbe;
  cleanup: () => Promise<void>;
}

async function makeFixture(
  script: readonly FakeTurnResolver[],
  opts: { fake?: FakeModelOptions; settings?: () => SettingsManager } = {},
): Promise<Fixture> {
  const dir = mkdtempSync(path.join(tmpdir(), "heph-session-"));
  const agentDir = path.join(dir, "agent");
  const projectRoot = path.join(dir, "proj");
  mkdirSync(agentDir, { recursive: true });
  mkdirSync(projectRoot, { recursive: true });
  const fake = await FakeModel.start(script, opts.fake ?? {});
  const { runtime } = await createModelRuntime({ providers: [fake.providerSpec()] }, { agentDir });
  const model = runtime.getModel(fake.providerId, fake.modelId);
  if (!model) throw new Error("fake model did not resolve");
  const probe: ToolProbe = { count: 0 };
  const service = new SessionService({
    runtime,
    agentDir,
    model,
    customTools: [makeInspectTool(probe)],
    settings: opts.settings ? () => opts.settings!() : undefined,
  });
  const cleanup = async (): Promise<void> => {
    await service.disposeAll();
    await fake.close();
    rmSync(dir, { recursive: true, force: true });
  };
  return { dir, agentDir, projectRoot, fake, service, probe, cleanup };
}

function waitFor(pred: () => boolean, timeoutMs = 5000): Promise<void> {
  return new Promise((resolve, reject) => {
    const start = Date.now();
    const tick = (): void => {
      if (pred()) return resolve();
      if (Date.now() - start > timeoutMs) return reject(new Error("waitFor timed out"));
      setTimeout(tick, 20);
    };
    tick();
  });
}

let active: Fixture | undefined;
afterEach(async () => {
  if (active) {
    await active.cleanup();
    active = undefined;
  }
});

describe("FakeModel session lifecycle", () => {
  it("streams text, runs a tool, persists, and resumes", async () => {
    const fx = await makeFixture([
      { kind: "tool_calls", calls: [{ name: "inspect_part", arguments: { name: "widget" } }] },
      { kind: "text", chunks: ["HEPH_FINAL: ", "built"] },
    ]);
    active = fx;

    const managed = await fx.service.create({ profile: "part", projectRoot: fx.projectRoot, part: "widget", sessionId: "s1" });
    const eventTypes: string[] = [];
    let streamed = "";
    managed.session.subscribe((ev) => {
      eventTypes.push(ev.type);
      if (ev.type === "message_update") {
        const a = (ev as { assistantMessageEvent?: { type?: string; delta?: string } }).assistantMessageEvent;
        if (a?.type === "text_delta" && a.delta) streamed += a.delta;
      }
    });

    await managed.session.prompt("inspect the part then finish");

    expect(fx.probe.count).toBeGreaterThanOrEqual(1);
    expect(eventTypes).toContain("tool_execution_start");
    expect(eventTypes).toContain("tool_execution_end");
    expect(streamed).toContain("HEPH_FINAL:");

    const file = managed.session.sessionFile;
    expect(file).toBeTruthy();
    expect(existsSync(file ?? "")).toBe(true);
    expect(managed.sessionDir).toBeTruthy();
    expect(file?.startsWith(managed.sessionDir ?? "")).toBe(true);

    // Dispose and resume the same session from its own persistence dir.
    await fx.service.dispose("s1");
    fx.fake.setScript([{ kind: "text", chunks: ["resumed ok"] }]);
    const resumed = await fx.service.resume({ profile: "part", projectRoot: fx.projectRoot, part: "widget", sessionId: "s1" });
    expect(resumed.session.messages.length).toBeGreaterThanOrEqual(2);
    expect(resumed.session.sessionFile).toBe(file);
  }, 30000);

  it("cancels one run without disturbing another multiplexed session", async () => {
    const fx = await makeFixture([{ kind: "stall" }, { kind: "stall" }]);
    active = fx;
    const a = await fx.service.create({ profile: "part", projectRoot: fx.projectRoot, part: "a", sessionId: "sa" });
    const b = await fx.service.create({ profile: "part", projectRoot: fx.projectRoot, part: "b", sessionId: "sb" });
    fx.service.beginRun("sa", "ra");
    fx.service.beginRun("sb", "rb");

    const pa = a.session.prompt("stall a");
    const pb = b.session.prompt("stall b");
    await waitFor(() => a.session.isStreaming && b.session.isStreaming);

    await fx.service.cancel("ra");
    await pa;

    expect(a.session.isStreaming).toBe(false);
    // B is untouched by A's cancellation.
    expect(b.session.isStreaming).toBe(true);
    expect(fx.service.runController("ra")?.signal.aborted).toBe(true);
    expect(fx.service.runController("rb")?.signal.aborted).toBe(false);

    await fx.service.cancel("rb");
    await pb;
    expect(b.session.isStreaming).toBe(false);
  }, 30000);

  it("compaction preserves the pinned CAD summary across the boundary", async () => {
    const summary: PinnedCadSummary = {
      designIntent: "shelf with gusset",
      decisions: ["gusset thickness 4mm", "shelf depth 120mm"],
      openProblems: [],
      params: { depth: 120, gusset_t: 4 },
      checkStatus: "all passing",
    };
    const pinned = formatPinnedSummary(summary);

    // Four tool-roundtrip turns (tool_call then text) build enough history to
    // compact, mirroring the proven Stage S compaction spike.
    const roundtrips: FakeTurnResolver[] = [];
    for (let i = 0; i < 4; i++) {
      roundtrips.push({ kind: "tool_calls", calls: [{ name: "inspect_part", arguments: { turn: i } }] });
      roundtrips.push({ kind: "text", chunks: [`turn ${i} done`] });
    }
    const fx = await makeFixture(roundtrips, {
      fake: { summarize: () => pinned },
      settings: () => SettingsManager.inMemory({ compaction: { enabled: true, reserveTokens: 100, keepRecentTokens: 10 } }),
    });
    active = fx;

    const managed = await fx.service.create({ profile: "part", projectRoot: fx.projectRoot, part: "shelf", sessionId: "sc" });
    for (let i = 0; i < 4; i++) await managed.session.prompt(`work turn ${i}`);

    const result = await managed.session.compact(pinned);
    expect(result.summary).toContain(PINNED_SUMMARY_OPEN);
    expect(result.summary).toContain("shelf with gusset");

    // Post-compaction: the pinned summary is present in the context handed to the
    // model, so it can answer a pre-compaction decision.
    let sawPinned = false;
    fx.fake.setScript([
      (req) => {
        sawPinned = req.bodyText.includes(PINNED_SUMMARY_OPEN);
        return { kind: "text", chunks: ["the gusset is 4mm"] };
      },
    ]);
    await managed.session.prompt("restate the gusset decision");
    expect(sawPinned).toBe(true);
  }, 40000);
});



describe("isolation from ambient globals", () => {
  it("ignores a planted extension dir and never enables built-in coding tools", async () => {
    const fx = await makeFixture([{ kind: "text", chunks: ["hi"] }]);
    active = fx;
    // Plant a hostile extension under the app-owned agentDir; noExtensions must
    // defeat it.
    const extDir = path.join(fx.agentDir, "extensions");
    mkdirSync(extDir, { recursive: true });
    writeFileSync(
      path.join(extDir, "hostile.js"),
      "export default function(){ return { name:'hostile', tools:[{name:'hostile_tool'}] }; }\n",
    );

    const managed = await fx.service.create({ profile: "part", projectRoot: fx.projectRoot, part: "iso", sessionId: "si" });
    const toolNames = managed.session.agent.state.tools.map((t) => t.name);
    expect(toolNames).not.toContain("hostile_tool");
    for (const builtin of ["read", "bash", "edit", "write", "grep", "find", "ls"]) {
      expect(toolNames).not.toContain(builtin);
    }
    // Only the custom tool that is also in the part allowlist is present.
    expect(toolNames).toContain("inspect_part");
  }, 30000);

  it("credentials come only from the payload allowlist, never process.env", async () => {
    const dir = mkdtempSync(path.join(tmpdir(), "heph-cred-"));
    const agentDir = path.join(dir, "agent");
    mkdirSync(agentDir, { recursive: true });
    const saved = process.env.ANTHROPIC_API_KEY;
    process.env.ANTHROPIC_API_KEY = "hostile-ambient-key-must-be-ignored";
    try {
      // A provider that references a credential missing from the allowlist is
      // rejected — the env var is never consulted as a fallback.
  // AMENDED by INTERFACE.md §23.7 (Stage 10B), and the property under test is
  // UNCHANGED. `createModelRuntime` used to throw on the first provider that
  // failed verification; it now records `available: false` with that provider's
  // own code and brings the runtime up with whatever verified. §23.7 states why
  // that is strictly stronger rather than weaker: "an unavailable provider is
  // never silently replaced, never falls back, and cannot serve a turn. What
  // changes is only that its failure no longer takes its neighbours and the
  // login path down with it." So the assertion moves from "it threw" to "it is
  // unavailable, by name" — which is the same claim about substitution, made
  // against a runtime that can still be signed into.
      const refused = await createModelRuntime(
        {
          providers: [
            {
              id: "anthropic",
              kind: "anthropic",
              credential: "ANTHROPIC_APPROVED",
              models: [{ id: "claude-x", name: "X", contextWindow: 1000, maxTokens: 100 }],
            },
          ],
        },
        { agentDir },
      );
      expect(refused.providers).toEqual([
        {
          id: "anthropic",
          available: false,
          unavailable_reason: "credential_not_allowlisted",
          message: expect.stringMatching(/allowlist/) as unknown as string,
        },
      ]);
      // NOT REGISTERED, which is the substitution half: an unavailable provider
      // cannot serve a turn, so the ambient key has nothing to be a fallback for.
      expect(refused.runtime.getRegisteredProviderIds()).not.toContain("anthropic");

      // With the credential explicitly approved in the payload, it succeeds.
      const { runtime } = await createModelRuntime(
        {
          providers: [
            {
              id: "anthropic",
              kind: "anthropic",
              credential: "ANTHROPIC_APPROVED",
              models: [{ id: "claude-x", name: "X", contextWindow: 1000, maxTokens: 100 }],
            },
          ],
          credentials: { ANTHROPIC_APPROVED: "approved-secret" },
        },
        { agentDir },
      );
      expect(runtime.getModel("anthropic", "claude-x")).toBeDefined();
    } finally {
      if (saved === undefined) delete process.env.ANTHROPIC_API_KEY;
      else process.env.ANTHROPIC_API_KEY = saved;
      rmSync(dir, { recursive: true, force: true });
    }
  }, 30000);
});
