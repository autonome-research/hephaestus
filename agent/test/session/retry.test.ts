// Transient-fault retry over real Pi sessions driven by the scripted FakeModel.
//
// The rule under test (session/retry.ts; EXTERNAL_EVAL.md §5): an errored
// assistant turn whose message names a transient provider class gets exactly
// ONE automatic retry with a continuation prompt and a "turn_retry" audit
// event; a second errored turn fails the run with the SECOND message, and a
// non-transient error fails immediately with no retry. The archived pair this
// repairs is bench/results/gpt-5.6-sol/2026-08-02 tasks 214/218 — one
// "WebSocket error" each, correct geometry already built.
import { describe, it, expect, afterEach } from "vitest";
import { mkdtempSync, mkdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { defineTool } from "@earendil-works/pi-coding-agent";
import { Type } from "@sinclair/typebox";
import {
  FakeModel,
  createModelRuntime,
  type FakeTurnResolver,
} from "../../src/session/runtime.js";
import { SessionService } from "../../src/session/manager.js";
import {
  promptWithTransientRetry,
  transientErrorClass,
  turnErrorOf,
  RETRY_CONTINUATION_PROMPT,
  type PromptRunOutcome,
} from "../../src/session/retry.js";

// A custom tool in the part-profile allowlist, so scripted requests carry a
// tool list — the FakeModel answers tool-less requests as compaction and never
// advances its script.
const inspectTool = defineTool({
  name: "inspect_part",
  label: "Inspect Part",
  description: "Fake inspect that returns a render description.",
  parameters: Type.Object({}, { additionalProperties: true }),
  async execute() {
    return { content: [{ type: "text" as const, text: "rendered iso view" }], details: {} };
  },
});

interface Fixture {
  fake: FakeModel;
  service: SessionService;
  cleanup: () => Promise<void>;
}

async function makeFixture(script: readonly FakeTurnResolver[]): Promise<Fixture> {
  const dir = mkdtempSync(path.join(tmpdir(), "heph-retry-"));
  const agentDir = path.join(dir, "agent");
  mkdirSync(agentDir, { recursive: true });
  const fake = await FakeModel.start(script);
  const runtime = await createModelRuntime({ providers: [fake.providerSpec()] }, { agentDir });
  const model = runtime.getModel(fake.providerId, fake.modelId);
  if (!model) throw new Error("fake model did not resolve");
  const service = new SessionService({ runtime, agentDir, model, customTools: [inspectTool] });
  const cleanup = async (): Promise<void> => {
    await service.disposeAll();
    await fake.close();
    rmSync(dir, { recursive: true, force: true });
  };
  return { fake, service, cleanup };
}

interface AuditRecord {
  error: string;
  transientClass: string;
}

/** Drive one run exactly the way main.ts does: watch turn errors, retry once. */
async function runPrompt(
  fx: Fixture,
  sessionId: string,
): Promise<{ outcome: PromptRunOutcome; audits: AuditRecord[]; prompts: string[] }> {
  const managed = await fx.service.create({
    profile: "part",
    projectRoot: mkdtempSync(path.join(tmpdir(), "heph-retry-proj-")),
    part: "widget",
    sessionId,
  });
  let turnError: string | undefined;
  const unsubscribe = managed.session.subscribe((ev) => {
    const errored = turnErrorOf(ev);
    if (errored !== undefined) turnError = errored;
  });
  const audits: AuditRecord[] = [];
  const prompts: string[] = [];
  try {
    const outcome = await promptWithTransientRetry("build the widget", {
      prompt: async (text) => {
        prompts.push(text);
        await managed.session.prompt(text);
      },
      takeTurnError: () => {
        const captured = turnError;
        turnError = undefined;
        return captured;
      },
      aborted: () => false,
      onRetry: (error, transientClass) => audits.push({ error, transientClass }),
    });
    return { outcome, audits, prompts };
  } finally {
    unsubscribe();
  }
}

let active: Fixture | undefined;
afterEach(async () => {
  if (active) {
    await active.cleanup();
    active = undefined;
  }
});

describe("transient-fault retry", () => {
  it("errors once then succeeds: the run completes, with the audit event", async () => {
    const fx = await makeFixture([
      { kind: "error", message: "WebSocket error" },
      { kind: "text", chunks: ["HEPH_FINAL: recovered"] },
    ]);
    active = fx;

    const { outcome, audits, prompts } = await runPrompt(fx, "s-retry-ok");

    expect(outcome.state).toBe("completed");
    expect(outcome.errorMessage).toBeUndefined();
    // Exactly one retry, prompted with the continuation prompt.
    expect(prompts).toEqual(["build the widget", RETRY_CONTINUATION_PROMPT]);
    // The audit record carries the fault message and its named class.
    expect(audits).toHaveLength(1);
    expect(audits[0]?.error).toContain("WebSocket error");
    expect(audits[0]?.transientClass).toBeTruthy();
  }, 30000);

  it("errors twice: the run fails with the second message", async () => {
    const fx = await makeFixture([
      { kind: "error", message: "WebSocket error" },
      { kind: "error", message: "connection reset by peer" },
      // Never reached: a second errored turn ends the run.
      { kind: "text", chunks: ["HEPH_FINAL: unreachable"] },
    ]);
    active = fx;

    const { outcome, audits, prompts } = await runPrompt(fx, "s-retry-fail");

    expect(outcome.state).toBe("failed");
    expect(outcome.errorMessage).toContain("connection reset by peer");
    expect(outcome.errorMessage).not.toContain("WebSocket");
    // Still exactly one retry — the second fault is never retried.
    expect(prompts).toEqual(["build the widget", RETRY_CONTINUATION_PROMPT]);
    expect(audits).toHaveLength(1);
  }, 30000);

  it("a non-transient errored turn fails immediately, no retry", async () => {
    const fx = await makeFixture([
      { kind: "error", message: "invalid api key", status: 400 },
      { kind: "text", chunks: ["HEPH_FINAL: unreachable"] },
    ]);
    active = fx;

    const { outcome, audits, prompts } = await runPrompt(fx, "s-no-retry");

    expect(outcome.state).toBe("failed");
    expect(outcome.errorMessage).toContain("invalid api key");
    expect(prompts).toEqual(["build the widget"]);
    expect(audits).toHaveLength(0);
  }, 30000);
});

describe("transient class naming", () => {
  it("names the archived 2026-08-02 fault shape and its peers", () => {
    expect(transientErrorClass("WebSocket error")).toBe("websocket");
    expect(transientErrorClass("ECONNRESET")).toBe("connection");
    expect(transientErrorClass("Request timed out")).toBe("timeout");
    expect(transientErrorClass("503: service unavailable")).toBe("provider_unavailable");
    expect(transientErrorClass("Provider finish_reason: network_error")).toBe("connection");
  });

  it("never names auth or request errors as transient", () => {
    expect(transientErrorClass("invalid api key")).toBeUndefined();
    expect(transientErrorClass("OAuth auth derivation failed")).toBeUndefined();
    expect(transientErrorClass("Provider finish_reason: content_filter")).toBeUndefined();
    expect(transientErrorClass("400 bad request: unknown parameter")).toBeUndefined();
  });
});
