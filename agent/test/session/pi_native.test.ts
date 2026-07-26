// `pi_native` providers: Pi's built-in catalog + the credential stored in the
// app-owned auth.json. Nothing here touches the network or the operator's real
// ~/.pi/agent/auth.json — every fixture is a synthetic file under tmp.
import { describe, it, expect, afterEach } from "vitest";
import { mkdtempSync, mkdirSync, writeFileSync, symlinkSync, rmSync, realpathSync, lstatSync, readlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { createModelRuntime, RuntimeConfigError } from "../../src/session/runtime.js";

const PROVIDER = "openai-codex";
const MODEL = "gpt-5.6-sol";

const dirs: string[] = [];

function scratch(): string {
  const dir = mkdtempSync(path.join(tmpdir(), "heph-pi-native-"));
  dirs.push(dir);
  return dir;
}

afterEach(() => {
  for (const dir of dirs.splice(0)) rmSync(dir, { recursive: true, force: true });
});

/** A throwaway Pi auth.json with an obviously fake OAuth record. */
function writeSyntheticAuth(dir: string): string {
  const file = path.join(dir, "pi-auth.json");
  writeFileSync(
    file,
    JSON.stringify({
      [PROVIDER]: {
        type: "oauth",
        access: "synthetic-access-token-not-a-real-credential",
        refresh: "synthetic-refresh-token-not-a-real-credential",
        expires: Date.now() + 3_600_000,
        accountId: "synthetic-account",
      },
    }),
  );
  return file;
}

describe("pi_native providers", () => {
  it("resolves a built-in provider/model from a linked auth.json", async () => {
    const root = scratch();
    const source = writeSyntheticAuth(root);
    const agentDir = path.join(root, "agent");
    mkdirSync(agentDir);
    // The supervisor's half of the contract: auth.json is a *symlink*, so the
    // OAuth record rotates in one place instead of drifting between copies.
    const link = path.join(agentDir, "auth.json");
    symlinkSync(source, link);
    expect(lstatSync(link).isSymbolicLink()).toBe(true);
    expect(realpathSync(readlinkSync(link))).toBe(realpathSync(source));

    const runtime = await createModelRuntime(
      { providers: [{ id: PROVIDER, kind: "pi_native", models: [{ id: MODEL }] }] },
      { agentDir },
    );

    // Never registered as an app provider — it came straight from Pi's catalog.
    expect(runtime.getRegisteredProviderIds()).not.toContain(PROVIDER);
    expect(runtime.hasConfiguredAuth(PROVIDER)).toBe(true);
    expect(runtime.getProviderAuthStatus(PROVIDER)).toMatchObject({
      configured: true,
      source: "stored",
    });
    expect(runtime.isUsingOAuth(PROVIDER)).toBe(true);
    expect(runtime.getModel(PROVIDER, MODEL)?.id).toBe(MODEL);
  }, 30000);

  it("without a linked auth.json the built-in provider has no credential", async () => {
    const root = scratch();
    const agentDir = path.join(root, "agent");
    mkdirSync(agentDir);
    // A hostile ambient key must not become a fallback for a built-in provider.
    const saved = process.env.OPENAI_API_KEY;
    process.env.OPENAI_API_KEY = "hostile-ambient-key-must-be-ignored";
    try {
      await expect(
        createModelRuntime(
          { providers: [{ id: PROVIDER, kind: "pi_native", models: [{ id: MODEL }] }] },
          { agentDir },
        ),
      ).rejects.toThrow(/no stored credential/);
      // …and the failure is the *auth* one, not a mistaken "unknown provider".
      const err = await createModelRuntime(
        { providers: [{ id: PROVIDER, kind: "pi_native", models: [{ id: MODEL }] }] },
        { agentDir },
      ).catch((e: unknown) => e);
      expect(err).toBeInstanceOf(RuntimeConfigError);
      expect((err as RuntimeConfigError).code).toBe("provider_not_authenticated");
    } finally {
      if (saved === undefined) delete process.env.OPENAI_API_KEY;
      else process.env.OPENAI_API_KEY = saved;
    }
  }, 30000);

  it("distinguishes an unknown provider from an unknown model", async () => {
    const root = scratch();
    const source = writeSyntheticAuth(root);
    const agentDir = path.join(root, "agent");
    mkdirSync(agentDir);
    symlinkSync(source, path.join(agentDir, "auth.json"));

    const unknownProvider = await createModelRuntime(
      { providers: [{ id: "not-a-real-provider", kind: "pi_native", models: [{ id: "x" }] }] },
      { agentDir },
    ).catch((e: unknown) => e);
    expect(unknownProvider).toBeInstanceOf(RuntimeConfigError);
    expect((unknownProvider as RuntimeConfigError).code).toBe("provider_unknown");

    const unknownModel = await createModelRuntime(
      { providers: [{ id: PROVIDER, kind: "pi_native", models: [{ id: "gpt-nonexistent" }] }] },
      { agentDir },
    ).catch((e: unknown) => e);
    expect(unknownModel).toBeInstanceOf(RuntimeConfigError);
    expect((unknownModel as RuntimeConfigError).code).toBe("model_unknown");
  }, 30000);
});
