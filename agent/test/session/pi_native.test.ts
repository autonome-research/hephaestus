// `pi_native` providers: Pi's built-in catalog + the credential stored in the
// app-owned auth.json. Nothing here touches the network or the operator's real
// ~/.pi/agent/auth.json — every fixture is a synthetic file under tmp.
import { describe, it, expect, afterEach } from "vitest";
import { mkdtempSync, mkdirSync, writeFileSync, symlinkSync, rmSync, realpathSync, lstatSync, readlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { createModelRuntime } from "../../src/session/runtime.js";

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

    const { runtime } = await createModelRuntime(
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
      const configured = await createModelRuntime(
        { providers: [{ id: PROVIDER, kind: "pi_native", models: [{ id: MODEL }] }] },
        { agentDir },
      );
      // The failure is the *auth* one, not a mistaken "unknown provider", and
      // it names the provider it belongs to.
      expect(configured.providers).toEqual([
        {
          id: PROVIDER,
          available: false,
          unavailable_reason: "provider_not_authenticated",
          message: expect.stringMatching(/no stored credential/) as unknown as string,
        },
      ]);
      // THE PROPERTY THIS TEST EXISTS FOR, unchanged: a `pi_native` provider
      // with no stored credential can never fall back to the ambient login.
      expect(configured.runtime.hasConfiguredAuth(PROVIDER)).toBe(false);
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
    );
    expect(unknownProvider.providers[0]?.unavailable_reason).toBe("provider_unknown");

    const unknownModel = await createModelRuntime(
      { providers: [{ id: PROVIDER, kind: "pi_native", models: [{ id: "gpt-nonexistent" }] }] },
      { agentDir },
    );
    // The two codes stay DISTINGUISHABLE (§23.11's closed vocabulary): a
    // provider Pi does not have and a model it does not offer are different
    // problems with different remedies, and neither degrades into the other.
    expect(unknownModel.providers[0]?.unavailable_reason).toBe("model_unknown");
  }, 30000);
});
