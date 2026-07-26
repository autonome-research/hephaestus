// Regression: Pi's openai-completions adapter attaches `strict: false` to
// every tool unless the model declares `supportsStrictMode: false`, in which
// case it omits the field. Self-hosted OpenAI-compatible servers (vLLM) read an
// explicit `strict: false` as "disable structured tool-call decoding" and then
// answer with prose instead of tool calls — measured 0/4 with the flag versus
// 4/4 without it against vLLM + Qwen3.6, which silently degraded a whole Tier 3
// bench. Registered models must therefore carry supportsStrictMode: false.

import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { createModelRuntime, type RuntimeConfig } from "../../src/session/runtime.js";

async function runtimeFor(config: RuntimeConfig) {
  return await createModelRuntime(config, {
    agentDir: mkdtempSync(path.join(tmpdir(), "heph-strict-")),
  });
}

function compatOf(model: unknown): Record<string, unknown> {
  return ((model as { compat?: Record<string, unknown> }).compat ?? {}) as Record<string, unknown>;
}

describe("tool strict-mode compat", () => {
  it("declares supportsStrictMode false so Pi omits the strict field", async () => {
    const runtime = await runtimeFor({
      providers: [
        {
          id: "vllm",
          kind: "openai_compatible",
          baseUrl: "http://127.0.0.1:1/v1",
          models: [{ id: "m", name: "m", contextWindow: 1000, maxTokens: 100 }],
        },
      ],
    });
    expect(compatOf(runtime.getModel("vllm", "m")).supportsStrictMode).toBe(false);
  });

  it("still lets an endpoint opt back into strict mode explicitly", async () => {
    const runtime = await runtimeFor({
      providers: [
        {
          id: "hosted",
          kind: "openai_compatible",
          baseUrl: "http://127.0.0.1:1/v1",
          models: [
            {
              id: "m",
              name: "m",
              contextWindow: 1000,
              maxTokens: 100,
              supportsStrictMode: true,
            },
          ],
        },
      ],
    });
    expect(compatOf(runtime.getModel("hosted", "m")).supportsStrictMode).toBe(true);
  });
});
