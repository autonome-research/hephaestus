// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Provider sign-in and credential discovery, end to end (Gates G10B and G10C;
// INTERFACE.md §23).
//
// **This suite runs against its own serve, and that is the clause.** G10B opens
// with "serve a project with **no** `providers.json`" and G10C adds "beside a
// scripted home-directory Pi `auth.json` and a scripted local
// OpenAI-compatible endpoint". Neither is a page state; both are properties of
// a differently configured serve. `harness/providers_serve.py` is that serve.
//
// What is asserted here rather than in pytest, and why the split is where it
// is: everything below is either a *rendered* fact (the panel names the refusal,
// the offer shows four fields and no fifth, the key field is a password field
// in a real browser) or an end-to-end arc across the HTTP boundary. The
// property-level negatives — the allowlist refusal, the symlink guard, the
// stderr redaction, the no-listener assertion — are `server/tests/
// test_http_providers.py`, `test_provider_discovery.py` and
// `test_credential_leak.py`, because they are assertions about channels a
// browser cannot see.
//
// NO ASSERTION HERE READS UI COPY (§3). Selectors are the `data-*` contract
// `ProvidersPanel.tsx` and `SignInDialog.tsx` declare in their headers.

import { spawn, type ChildProcess } from "node:child_process";
import { readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { world } from "./harness/world";

/** Kept in step with `providers_serve.py`; a drift fails loudly rather than quietly. */
const DISCOVERED_SECRET = "oauth-refresh-E2E-71bc4a09-never-echo-me";
const DISCOVERED_PROVIDER = "openai-codex";
/** Kept in step with `providers_serve.py`s ARC_REPLY; a drift fails loudly. */
const ARC_REPLY = "attached-and-streaming-9f3c1d";

interface Serve {
  readonly proc: ChildProcess;
  readonly baseUrl: string;
  readonly token: string;
  readonly projectRoot: string;
  readonly home: string;
  readonly modelUrl: string;
}

let serve: Serve;

async function startServe(): Promise<Serve> {
  return new Promise<Serve>((resolve, reject) => {
    const proc = spawn(
      world().python,
      [new URL("./harness/providers_serve.py", import.meta.url).pathname],
      { stdio: ["ignore", "pipe", "inherit"] },
    );
    const timer = setTimeout(() => {
      reject(new Error("the provider-less serve never became ready"));
    }, 300_000);
    let buffer = "";
    proc.stdout?.on("data", (chunk: Buffer) => {
      buffer += chunk.toString("utf8");
      const line = buffer.split("\n").find((candidate) => candidate.startsWith("READY "));
      if (line === undefined) return;
      clearTimeout(timer);
      const [, url, token, projectRoot, home, modelUrl] = line.trim().split(" ");
      resolve({
        proc,
        baseUrl: url ?? "",
        token: token ?? "",
        projectRoot: projectRoot ?? "",
        home: home ?? "",
        modelUrl: modelUrl ?? "",
      });
    });
    proc.on("exit", (code) => {
      clearTimeout(timer);
      reject(new Error(`the provider-less serve exited with ${String(code)}`));
    });
  });
}

/** One authenticated call against this suite's own serve. */
/** The same authorized call, against a serve this test owns rather than the shared one. */
async function callOn(
  target: Serve,
  method: string,
  path: string,
  body?: unknown,
  headers: Record<string, string> = {},
): Promise<{ status: number; text: string; json: Record<string, unknown> }> {
  const response = await fetch(`${target.baseUrl}/api/v1${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${target.token}`,
      Connection: "close",
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      ...headers,
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const text = await response.text();
  let parsed: Record<string, unknown> = {};
  try {
    parsed = JSON.parse(text) as Record<string, unknown>;
  } catch {
    parsed = {};
  }
  return { status: response.status, text, json: parsed };
}

async function call(
  method: string,
  path: string,
  body?: unknown,
  headers: Record<string, string> = {},
): Promise<{ status: number; text: string; json: Record<string, unknown> }> {
  const response = await fetch(`${serve.baseUrl}/api/v1${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${serve.token}`,
      Connection: "close",
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      ...headers,
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const text = await response.text();
  let parsed: Record<string, unknown> = {};
  try {
    parsed = JSON.parse(text) as Record<string, unknown>;
  } catch {
    parsed = {};
  }
  return { status: response.status, text, json: parsed };
}

function providersJson(): string {
  return readFileSync(join(serve.projectRoot, ".heph", "providers.json"), "utf8");
}

test.describe.configure({ mode: "serial" });

test.beforeAll(async () => {
  serve = await startServe();
});

test.afterAll(() => {
  serve.proc.kill("SIGTERM");
});

// ---------------------------------------------------------------------------
// G10B — the zero-config state, named on screen
// ---------------------------------------------------------------------------

test("the panel renders the zero-config state and names agent_unavailable", async ({ page }) => {
  await page.goto(`${serve.baseUrl}/#t=${serve.token}`);

  // §23.0: "Today a project with no `.heph/providers.json` serves every read
  // route and refuses every session route with `agent_unavailable`. That
  // refusal is correct, named, and addressed **to someone at a terminal**." The
  // panel is the surface that changes that.
  const panel = page.locator("[data-providers-empty]");
  await expect(panel).toHaveCount(1, { timeout: 90_000 });

  const sessions = await call("GET", "/sessions");
  expect(sessions.status).toBe(503);
  expect(sessions.json["reason"]).toBe("agent_unavailable");
  expect(sessions.json["cause"]).toBe("no_provider_config");

  // …and every read route still serves. `agent_unavailable` is about sessions,
  // not about the project.
  expect((await call("GET", "/project")).status).toBe(200);
  expect((await call("GET", "/providers")).status).toBe(200);
});

// ---------------------------------------------------------------------------
// G10C — the offer, and what it may not carry
// ---------------------------------------------------------------------------

test("discovery lists what exists, by four fields and no secret", async ({ page }) => {
  await page.goto(`${serve.baseUrl}/#t=${serve.token}`);
  const run = page.locator("[data-discovery-run]");
  await expect(run).toHaveCount(1, { timeout: 90_000 });

  // NOTHING is offered before the click. §15.41's "no background credential
  // probe" is unrelaxed by the 2026-08-28 ruling, and this is the browser half
  // of that: the panel mounted, and it discovered nothing.
  await expect(page.locator("[data-discovery]")).toHaveCount(0);

  await run.click();
  const offers = page.locator("[data-discovery]");
  await expect(offers.first()).toBeVisible({ timeout: 30_000 });

  // Both scripted sources are found and told apart by KIND.
  await expect(page.locator('[data-discovery-kind="pi_auth"]')).toHaveCount(1);
  await expect(page.locator('[data-discovery-kind="local_endpoint"]')).toHaveCount(1);

  // The response body carries no secret material and NO MASKED KEY TAIL. The
  // ruling permits "a masked hint at most" — a ceiling, not an instruction —
  // and §15.41 is stricter and stands (§0.2a).
  const discovered = await call("POST", "/providers/discover");
  expect(discovered.status).toBe(200);
  expect(discovered.text).not.toContain(DISCOVERED_SECRET);
  expect(discovered.text).not.toContain(DISCOVERED_SECRET.slice(-4));

  const sources = discovered.json["sources"] as Record<string, unknown>[];
  for (const source of sources) {
    expect(Object.keys(source).sort()).toEqual([
      "discovery_id",
      "kind",
      "model_ids",
      "provider_id",
      "source_path",
    ]);
  }

  // The offer names the provider and its models — which is what makes it an
  // offer rather than a list of paths (§23.5's superseded draft clause).
  const pi = sources.find((source) => source["kind"] === "pi_auth");
  expect(pi?.["provider_id"]).toBe(DISCOVERED_PROVIDER);
  expect(pi?.["model_ids"]).toEqual(["gpt-5-codex", "gpt-5-mini"]);

  // Nothing in the panel adopted on render, on hover, or on selection
  // (§23.14 item 19): the file the ruling's mechanical test reads still does
  // not exist.
  const providers = await call("GET", "/providers");
  expect(providers.json["config_exists"]).toBe(false);
});

test("a discovered but unadopted source leaves sessions refusing exactly as before", async () => {
  // §23.5's negative half, and the clause that keeps the approval honest: "a
  // discovered-but-**unadopted** login behaves **identically** to no login at
  // all — the session routes to `agent_unavailable`, byte for byte."
  await call("POST", "/providers/discover");
  const sessions = await call("GET", "/sessions");
  expect(sessions.status).toBe(503);
  expect(sessions.json["reason"]).toBe("agent_unavailable");
  expect(sessions.json["cause"]).toBe("no_provider_config");
});

test("one explicit adoption names the source in providers.json at 0600", async ({ page }) => {
  await page.goto(`${serve.baseUrl}/#t=${serve.token}`);
  await page.locator("[data-discovery-run]").click();

  const local = page.locator('[data-discovery-kind="local_endpoint"]');
  await expect(local).toHaveCount(1, { timeout: 30_000 });
  // The adopt control is unmistakably an ACT: a click, on a control that names
  // the handle it will send.
  await local.locator("[data-discovery-adopt]").click();

  const written = page.locator('[data-provider-source]');
  await expect(written.first()).toBeVisible({ timeout: 30_000 });

  // §23.5's distinguishing test, mechanically: the file names the source.
  const document_ = JSON.parse(providersJson()) as Record<string, unknown>;
  const adopted = document_["adopted_sources"] as Record<string, unknown>[];
  expect(adopted.map((row) => row["kind"])).toContain("local_endpoint");
  expect(document_["providers"]).toBeTruthy();

  // …and it is `0600`, created private (§23.5 constraint 4).
  const mode = statSync(join(serve.projectRoot, ".heph", "providers.json")).mode & 0o777;
  expect(mode).toBe(0o600);

  // The adoption wrote no secret, and the adoption RESPONSE carried none.
  expect(providersJson()).not.toContain(DISCOVERED_SECRET);
});

// ---------------------------------------------------------------------------
// G10B — the two refusals, through the browser's own origin
// ---------------------------------------------------------------------------

test("the web path cannot add a name to the credential allowlist", async () => {
  // §23.14 item 11, aimed at the property rather than the message: the naive
  // "export a variable and assert the sidecar's env lacks it" passes trivially,
  // *because the attack is to put the variable inside the allowlist*.
  const refused = await call(
    "PUT",
    "/providers/specs",
    {
      providers: [
        {
          id: "collector",
          kind: "openai_compatible",
          baseUrl: "https://collector.example/v1",
          credential: "ANTHROPIC_API_KEY",
          models: [{ id: "m", name: "m", contextWindow: 8, maxTokens: 8 }],
        },
      ],
      credential_allowlist: ["ANTHROPIC_API_KEY"],
    },
    { "Idempotency-Key": uuid7() },
  );
  expect(refused.status).toBe(400);
  expect(refused.json["reason"]).toBe("allowlist_not_web_writable");
  expect(providersJson()).not.toContain("ANTHROPIC_API_KEY");
});

test("an adopt body carrying a path is refused by its own name", async () => {
  // §23.6: refused `path_not_web_writable`, and it does NOT degrade to
  // `invalid_params`. "A client-supplied path is what turns a credential route
  // into a traversal primitive, and no route accepts one."
  const refused = await call("POST", "/providers/adopt", {
    discovery_id: "disc-anything",
    source_path: `${serve.home}/.pi/agent/auth.json`,
  });
  expect(refused.status).toBe(400);
  expect(refused.json["reason"]).toBe("path_not_web_writable");
});

test("a remote endpoint needs a typed acknowledgement and then is listed permanently", async ({
  page,
}) => {
  const host = "models.example";
  const refused = await call(
    "PUT",
    "/providers/specs",
    {
      providers: [
        {
          id: "remote",
          kind: "openai_compatible",
          baseUrl: `https://${host}/v1`,
          models: [{ id: "m", name: "m", contextWindow: 8, maxTokens: 8 }],
        },
      ],
    },
    { "Idempotency-Key": uuid7() },
  );
  expect(refused.status).toBe(400);
  expect(refused.json["reason"]).toBe("egress_not_acknowledged");

  const accepted = await call(
    "PUT",
    "/providers/specs",
    {
      providers: [
        {
          id: "remote",
          kind: "openai_compatible",
          baseUrl: `https://${host}/v1`,
          models: [{ id: "m", name: "m", contextWindow: 8, maxTokens: 8 }],
        },
      ],
      acknowledge_egress: [host],
    },
    { "Idempotency-Key": uuid7() },
  );
  expect(accepted.status).toBe(200);

  // §23.13: "A silent redirection is not available; a loud one is." The record
  // is on disk AND on screen, permanently.
  expect(providersJson()).toContain(host);
  await page.goto(`${serve.baseUrl}/#t=${serve.token}`);
  await expect(page.locator(`[data-egress-host="${host}"]`)).toHaveCount(1, { timeout: 90_000 });
});

// ---------------------------------------------------------------------------
// G10B — the dialog, in a real browser
// ---------------------------------------------------------------------------

test("the key field is a password field with no name, and the scope is not defaulted", async ({
  page,
}) => {
  await page.goto(`${serve.baseUrl}/#t=${serve.token}`);
  const signIn = page.locator("[data-provider-signin]").first();
  await expect(signIn).toBeVisible({ timeout: 90_000 });
  await signIn.click();

  const field = page.locator("[data-signin-key]");
  await expect(field).toBeVisible();
  // §23.3's three properties, read off the REAL element rather than off static
  // markup: the browser's attribute is what a password manager reads.
  await expect(field).toHaveAttribute("type", "password");
  await expect(field).toHaveAttribute("autocomplete", "off");
  expect(await field.getAttribute("name")).toBeNull();

  // §23.2: nothing is preselected, and the control that would submit says why
  // it cannot.
  for (const scope of ["serve", "project"]) {
    await expect(page.locator(`[data-signin-scope="${scope}"]`)).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  }
  await expect(page.locator("[data-signin-submit]")).toBeDisabled();
});

test("the sign-in response and the panel carry no credential material", async () => {
  // §23.13's purchase, asserted over every read this surface has: "a total
  // compromise of the page is an escalation to *use* and to *replace*, never to
  // *exfiltrate*."
  const sentinel = "sk-e2e-SENTINEL-6b0d3f21-never-echo-me";
  const providers = (await call("GET", "/providers")).json;
  const rows = providers["providers"] as Record<string, unknown>[];
  const first = rows[0];
  if (first === undefined) test.skip(true, "no provider was written by an earlier case");
  const providerId = String(first?.["id"] ?? "");

  const set = await call("POST", `/providers/${providerId}/auth/key`, {
    key: sentinel,
    scope: "serve",
  });
  // With no sidecar this is `503 agent_unavailable` by §23.0's third row — and
  // that is itself the assertion worth making, because a route that answered
  // without a credential store would be inventing one. Either way, no echo.
  expect([200, 503]).toContain(set.status);
  expect(set.text).not.toContain(sentinel);
  expect((await call("GET", "/providers")).text).not.toContain(sentinel);
  expect(providersJson()).not.toContain(sentinel);
});

/** A UUIDv7, because §2.5 refuses a v4 by name. Mirrors `api/idempotency.ts`. */
// ---------------------------------------------------------------------------
// G10B — the arc the gate binds to THIS command
// ---------------------------------------------------------------------------
//
// Added 2026-08-28 after independent verification found four G10B clauses that
// bind to `pnpm test:e2e` and were exercised only in pytest: this suite ran
// against a serve with no sidecar throughout, never attached one, never
// configured a provider against a scripted model, never streamed a turn, and
// never signed out. The behaviour was real and live-verified; the gate's own
// command did not reach it, which is a mission-rule-1 mapping gap of exactly
// the shape G4 carried until 0701af4. Nothing below duplicates pytest: the
// property-level negatives stay where a browser cannot see them, and this
// asserts only what crossing the browser boundary can prove.

test("write specs, attach, configure, stream, sign out — in one process", async ({
  page,
}) => {
  // THIS TEST OWNS ITS SERVE. The clause opens "serve a project with **no**
  // `providers.json`", and by the time this runs last in the file, eight
  // earlier tests have adopted a source (leaving it `linked`) and written a
  // remote provider whose host does not resolve — so the shared serve is no
  // longer the one the clause describes, and the composer correctly refuses to
  // enable against it. Passing in isolation and failing in the full suite was
  // that difference, not a timing budget (CI run 33234619571).
  const own = await startServe();
  try {
    await runArc(page, own);
  } finally {
    own.proc.kill("SIGTERM");
  }
});

async function runArc(page: Page, serve: Serve): Promise<void> {
  const call = (
    method: string,
    path: string,
    body?: unknown,
    headers: Record<string, string> = {},
  ) => callOn(serve, method, path, body, headers);
  await page.goto(`${serve.baseUrl}/#t=${serve.token}`);

  // The process that refuses is the process that will serve: pinned before the
  // attach, so "without restarting" is measured rather than assumed (§23.0).
  const before = (await call("GET", "/providers")).json;
  expect((before["attach"] as Record<string, unknown>)["cause"]).toBe("no_provider_config");
  expect((await call("POST", "/sessions", { profile: "orchestrator" })).status).toBe(503);
  const pid = serve.proc.pid;

  // (1) write specs against the scripted model. The clause's path is specs +
  // sign-in, NOT discovery-adoption: an adopted source is `linked`, and §23
  // refuses sign-out while linked ("unlink first"), so the adoption path cannot
  // reach this clause's last assertion.
  const wrote = await call(
    "PUT",
    "/providers/specs",
    {
      providers: [
        {
          id: "e2e-scripted",
          kind: "openai_compatible",
          baseUrl: serve.modelUrl,
          models: [{ id: "heph-fake-model", name: "Heph Fake Model", contextWindow: 8192, maxTokens: 1024 }],
        },
      ],
    },
    { "Idempotency-Key": uuid7() },
  );
  expect(wrote.status).toBe(200);

  // (2) configure the credential, then attach — WITHOUT restarting the process
  const keyed = await call("POST", "/providers/e2e-scripted/auth/key", {
    key: "e2e-scripted-key-not-echoed",
    scope: "serve",
  });
  expect([200, 503]).toContain(keyed.status);
  expect(keyed.text).not.toContain("e2e-scripted-key-not-echoed");

  const attached = await call("POST", "/providers/attach", {}, { "Idempotency-Key": uuid7() });
  expect(attached.status).toBe(200);
  expect(attached.json["attached"]).toBe(true);
  expect(serve.proc.pid).toBe(pid);
  // The page was loaded before the specs existed, so its cache predates them.
  // A reload is the honest way to see the new state: §7A.11's read-refresh
  // boundary governs a session's OWN turn, not a provider written out of band
  // by this test through the API.
  await page.reload();
  await expect(page.locator('[data-provider-available="true"]').first()).toBeVisible({
    timeout: 120_000,
  });

  // (3) a session now runs and STREAMS INTO THE PANEL. The reply is a sentinel
  // the harness scripts, so a panel that rendered without a turn having run
  // cannot pass this.
  // Create through the API and OPEN THAT SESSION BY ID, which is the path
  // composer.spec.ts uses: the composer is per-session and derives
  // `no_session` from `sessionId === null`, so a create that does not also
  // select leaves a correctly disabled box. Clicking create and waiting for
  // the input to enable was waiting for a selection nothing had made — that,
  // not a timing budget, is why this failed only in the full suite where the
  // page had not been navigated with an `s` query (CI run 33234619571).
  const created = (await call("POST", "/sessions", { profile: "orchestrator" })).json;
  const sessionId = String(created["session_id"] ?? "");
  expect(sessionId).not.toBe("");
  // The token is claimed on the first load and moved to sessionStorage, so the
  // route navigation carries no credential in its URL (§2.2) — the same
  // two-step arrival `harness/world.ts::open` makes, done here against the
  // serve this test owns.
  await page.waitForFunction(() => document.querySelector("[data-pin-mode]") !== null, null, {
    timeout: 60_000,
  });
  const search = new URLSearchParams({ s: sessionId }).toString();
  await page.evaluate((next: string) => {
    window.location.hash = next;
  }, `#/p/tread?${search}`);
  const composer = page.locator(`[data-composer][data-session-id="${sessionId}"]`);
  await expect(composer).toHaveCount(1, { timeout: 120_000 });
  await expect(composer).toHaveAttribute("data-disabled-reason", "null", { timeout: 180_000 });
  await composer.locator("[data-composer-input]").fill("say the sentinel");
  await composer.locator("[data-composer-send]").click();
  await expect(page.getByText(ARC_REPLY, { exact: false }).first()).toBeVisible({
    timeout: 180_000,
  });

  // (4) sign-out returns the panel to `none` and the session routes to refusing
  const out = await call("POST", "/providers/e2e-scripted/auth/signout", {});
  expect(out.status).toBe(200);
  await page.reload();
  // "returns the panel to `none`" is the SOURCE axis: ProvidersPanel derives
  // signedIn as `row.source !== "none"`, so `none` is the rendered fact that a
  // credential is gone. The health/available axis is about reachability and is
  // deliberately unaffected by signing out.
  await expect(page.locator('[data-provider-source="none"]').first()).toBeVisible({
    timeout: 60_000,
  });
  expect((await call("GET", "/providers")).text).not.toContain("e2e-scripted-key-not-echoed");
  expect(serve.proc.pid).toBe(pid);
}


function uuid7(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  const ms = Date.now();
  for (let i = 0; i < 6; i += 1) {
    bytes[i] = Number((BigInt(ms) >> BigInt(8 * (5 - i))) & 0xffn);
  }
  bytes[6] = ((bytes[6] ?? 0) & 0x0f) | 0x70;
  bytes[8] = ((bytes[8] ?? 0) & 0x3f) | 0x80;
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
