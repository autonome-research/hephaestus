// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The composer, end to end (INTERFACE.md §7A.12; plan item 4).
//
// §7A.12's seven cases, minus the three that belong elsewhere and are named
// here so the split is visible rather than silent:
//
//   * case 3 (request-text purity) and case 4 (concurrent purity) are **pytest**
//     by the spec's own instruction — "it asserts on the ops layer, not the
//     DOM". They live in `server/tests/test_context_envelope.py` and
//     `server/tests/test_request_binding.py`.
//   * case 5 (`ask_user` answered from the browser) is `ask.spec.ts`, which
//     landed with plan item 1.
//
// THE FIXTURE IS SEPARATE FROM G4.8'S, AND THAT IS NON-NEGOTIABLE (§7A.9).
// "An agent session started from CLI streams live into the web panel" is a claim
// about lease topology — a session started in a terminal is the *same session
// object* the browser attaches to, because there is only ever one runtime. If
// that clause were rewritten to drive its session through the composer, the
// cross-process round trip it exists to test would go untested and the clause
// would degenerate into a self-observation. So every session below is created
// **in the browser**, `stream.spec.ts` keeps creating G4.8's from the CLI, and
// case 6 stands up a whole second serve of its own.
//
// CASE 1 IS THE CLAUSE THE OPERATOR ASKED FOR. §7A.11: "The e2e asserts the end
// state the operator cares about, not the transcript… because 'the agent said
// it worked' is not what complaint 1 asked for." So the assertion that matters
// is not that events arrived — it is that the part the turn created is in the
// tree, **with no manual reload**.

import { spawn, type ChildProcess } from "node:child_process";
import { expect, test, type Page } from "@playwright/test";
import { api, open, route, world } from "./harness/world";

const PART = "tread";

interface SessionDocument {
  readonly session_id: string;
  readonly profile: string;
  readonly part: string | null;
}

interface PartsDocument {
  readonly parts: readonly { readonly name: string }[];
}

interface ContextDocument {
  readonly block: string;
  readonly truncated: boolean;
  readonly sources: readonly string[];
}

interface RefusalDocument {
  readonly reason: string;
  readonly message: string;
}

/** One request that is EXPECTED to be refused; the envelope comes back intact. */
async function refusal(path: string, body: unknown): Promise<{ status: number; body: RefusalDocument }> {
  const { base_url, token } = world();
  const response = await fetch(`${base_url}/api/v1${path}`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      Connection: "close",
    },
    body: JSON.stringify(body),
  });
  return { status: response.status, body: (await response.json()) as RefusalDocument };
}

/**
 * Point the page at a session the browser created, then wait for its composer.
 *
 * `?s=` is §4.5's session address, so this is how a real operator arrives at a
 * tab: the workspace route names the session, and the composer's identity is
 * that tab's `session_id` (§7A.1) rather than anything it chose for itself.
 */
async function openSession(page: Page, sessionId: string, part = PART): Promise<void> {
  await open(page, route(part, { s: sessionId }));
  await expect(page.locator(`[data-composer][data-session-id="${sessionId}"]`)).toHaveCount(1);
}

test.describe("§7A.12 case 1 — the blank canvas reaches the workspace", () => {
  test("a part the composer's own turn creates appears in the tree", async ({ page }) => {
    test.setTimeout(180_000);
    const created = await api<SessionDocument>("/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profile: "orchestrator" }),
    });
    // §7A.2: the blank canvas IS the orchestrator profile with no part.
    // `dispatch.py` exempts an orchestrator principal from object scope, and a
    // session that must be able to create the first part cannot be scoped to a
    // part that does not exist.
    expect(created.profile).toBe("orchestrator");
    expect(created.part).toBeNull();

    const newPart = world().composer.part;
    const before = await api<PartsDocument>("/parts");
    expect(before.parts.map((row) => row.name)).not.toContain(newPart);

    await openSession(page, created.session_id);
    const composer = page.locator(`[data-composer][data-session-id="${created.session_id}"]`);
    await expect(composer).toHaveAttribute("data-composer-state", "idle");
    await expect(composer).toHaveAttribute("data-disabled-reason", "null");
    await expect(composer).toHaveAttribute("data-profile", "orchestrator");
    // #114: idle composer is context + textarea + Send. No model chip.
    await expect(composer.locator("[data-composer-model]")).toHaveCount(0);
    await expect(
      composer.locator("[data-composer-input-row] [data-composer-send]"),
    ).toHaveCount(1);
    expect(
      await composer.locator("[data-composer-input-row] button, [data-composer-input-row] [role='button']").count(),
    ).toBe(1);
    const sendBox = await composer.locator("[data-composer-send]").boundingBox();
    const inputRowBox = await composer.locator("[data-composer-input-row]").boundingBox();
    expect(sendBox).not.toBeNull();
    expect(inputRowBox).not.toBeNull();
    const within = (
      inner: { x: number; y: number; width: number; height: number },
      outer: { x: number; y: number; width: number; height: number },
    ): boolean =>
      inner.y >= outer.y - 1 &&
      inner.y + inner.height <= outer.y + outer.height + 1 &&
      inner.x >= outer.x - 1 &&
      inner.x + inner.width <= outer.x + outer.width + 1;
    expect(within(sendBox!, inputRowBox!)).toBe(true);
    // C15's negative half: no third row mounts at rest — no meta line, no
    // empty action row. Cancel does not mount while nothing is cancellable
    // (§7A.10(b)) and the state attribute says so with no control present,
    // and the chip form does not mount while the disclosure is collapsed
    // (§7A.3(c)).
    expect(
      await composer.evaluate((form) => form.children.length),
    ).toBe(2);
    await expect(composer).toHaveAttribute("data-cancel-state", "unavailable");
    await expect(composer.locator("[data-composer-cancel]")).toHaveCount(0);
    await expect(composer.locator("[data-context-chips]")).toHaveCount(0);
    await expect(composer.locator("[data-context-summary]")).toHaveCount(1);

    // §7A.3, amended 2026-09-02 (§0.2c, C22): with no selection in workspace
    // state, the RESTING line mounts no Add-current-view — the gap the line
    // copy exists for is not this one. The disclosure's own copy remains the
    // route on the blank canvas.
    await expect(
      composer.locator("[data-context-summary] [data-context-add-view]"),
    ).toHaveCount(0);
    await expect(composer.locator("[data-context-disclose]")).toHaveCount(1);
    await composer.locator("[data-context-disclose]").click();
    await expect(composer.locator("[data-context-add-view]")).toHaveCount(1);
    // …and the other half: opening it mounts the editable form.
    await expect(composer.locator("[data-context-chips]")).toHaveCount(1);
    await composer.locator("[data-context-disclose]").click();
    await expect(composer.locator("[data-context-chips]")).toHaveCount(0);

    await composer
      .locator("[data-composer-input]")
      .fill(`${world().composer.sentinel} please make me a part`);
    await composer.locator("[data-composer-send]").click();

    // §7A.5 (C1, amended 2026-09-02): the sent words appear the moment they
    // are sent. The local-prompt echo renders immediately on Send — the model
    // round-trip has not settled — carrying the sent text verbatim, C2's DOM
    // contract, the visible-at-rest `unrecorded` marker, and NO event id.
    const echoRow = page.locator('[data-row="local-prompt"]');
    await expect(echoRow).toHaveCount(1);
    await expect(echoRow).toHaveAttribute("data-local-echo", "1");
    await expect(echoRow).toContainText("please make me a part");
    await expect(echoRow).toContainText("unrecorded");
    expect(await echoRow.getAttribute("data-event-id")).toBeNull();

    // The turn's events reach the transcript.
    await expect(page.locator("[data-tool-name]").first()).toBeVisible({ timeout: 120_000 });

    // §7.3 (C21): the echo licensed exactly one run-start boundary for the
    // first frame — the originating tab's turn edge, marked from both sides.
    const boundary = page.locator('[data-row="run-start"]');
    await expect(boundary).toHaveCount(1);
    expect(await boundary.getAttribute("data-run-id")).toBeTruthy();
    expect(await boundary.getAttribute("data-event-id")).toBeNull();

    // THE CLAUSE. §7A.11: refetch, never merge — so the tree gains the part
    // because the client re-read `GET /parts`, not because it patched a list
    // from a tool result. No reload happens anywhere in this test.
    const treeRow = page.locator(`[role="tree"] [data-part="${newPart}"]`);
    await expect(treeRow).toHaveCount(1, { timeout: 60_000 });

    // §7A.11 (C7, amended 2026-09-02): after settle, exactly the created
    // part's row carries the transient `data-turn-changed` — the diff of two
    // server projections across the refetch, created parts included; rows the
    // turn did not touch are never marked.
    const marked = page.locator('[role="tree"] [data-turn-changed]');
    await expect(marked).toHaveCount(1, { timeout: 60_000 });
    expect(await marked.getAttribute("data-part")).toBe(newPart);

    // …and it is selectable, which is the other half of "appears in the tree".
    // Selecting it moves §4.5's addressed part, which is the observable form of
    // "the workspace can now work on the thing the agent just made".
    await treeRow.click();
    await page.waitForFunction(
      (expected: string) => window.location.hash.includes(`/p/${expected}`),
      newPart,
      { timeout: 30_000 },
    );
    await expect(treeRow).toHaveAttribute("aria-selected", "true");

    // C7's first exit: clicking the row clears its marker — and nothing else
    // in this test's remaining reads may re-mint it.
    await expect(page.locator('[role="tree"] [data-turn-changed]')).toHaveCount(0);

    // The server agrees, which is what makes the DOM assertion a projection
    // rather than a claim about the DOM alone (§14's rule for this suite).
    const after = await api<PartsDocument>("/parts");
    expect(after.parts.map((row) => row.name)).toContain(newPart);
  });
});

test.describe("§7A.12 case 2 — the context envelope", () => {
  test("the chip row names the references, and each one is droppable", async ({ page }) => {
    const created = await api<SessionDocument>("/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profile: "orchestrator" }),
    });
    await openSession(page, created.session_id);
    const composer = page.locator(`[data-composer][data-session-id="${created.session_id}"]`);

    // §7A.3(a)(d), amended 2026-09-01: at rest the envelope is ONE line, and
    // the line publishes the member keys the POST would send. The `part` is in
    // the route, so it is on the line before anything is opened.
    const summary = composer.locator("[data-context-summary]");
    await expect(summary).toHaveCount(1);
    await expect(summary).toContainText(PART);
    expect(((await summary.getAttribute("data-context-keys")) ?? "").split(" ")).toContain("part");

    // Context chips and Add current view fold into disclose. Open it so
    // the row is in the DOM; the idle composer is one context line, the
    // prompt, and Send.
    await composer.locator("[data-context-disclose]").click();

    // §7A.3(d)'s testable, against the running app: the published key set IS
    // the chips' key set. A summary that named a member the form did not offer
    // — or offered one it did not name — would be the line and the envelope
    // disagreeing about what is being sent.
    //
    // Both halves are read in ONE DOM evaluation, after the disclosure is open.
    // The product is same-render consistent (Composer derives chips, envelope
    // and summary from one `state` in one pass), but `state.artifact_ref`
    // arrives asynchronously, so sampling the line before the click and the
    // chips after it compares two different states and fails on a correct
    // build. One sample, one render, no retry.
    const { published, chipKeys } = await composer.evaluate((host) => ({
      published: (host.querySelector("[data-context-summary]")?.getAttribute("data-context-keys") ??
        ""
      )
        .split(" ")
        .filter((key) => key !== ""),
      chipKeys: [...host.querySelectorAll("[data-context-chips] [data-context-key]")].map(
        (node) => node.getAttribute("data-context-key") ?? "",
      ),
    }));
    expect([...chipKeys].sort()).toEqual([...published].sort());

    // The part is in the route, so the part chip is in the row. §7A.10's DOM
    // contract: a chip carries `data-context-key` and its value, and NO
    // `data-source`, because no chip is a fact.
    const partChip = composer.locator('[data-context-key="part"]');
    await expect(partChip).toHaveAttribute("data-context-value", PART);
    await expect(composer.locator("[data-context-chips] [data-source]")).toHaveCount(0);

    // §6.4: the two DFM controls live on the inspector panel, not the
    // composer. The fixture starts `[dfm] auto_run = false`.
    await expect(composer.locator("[data-composer-dfm]")).toHaveCount(0);
    await expect(composer.locator("[data-dfm-auto-run-toggle]")).toHaveCount(0);
    await expect(composer.locator("[data-dfm-run]")).toHaveCount(0);
    await page.locator('[data-inspector-tab="dfm"]').click();
    const dfmPanel = page.locator('[data-inspector-panel="dfm"]');
    await expect(dfmPanel.locator("[data-panel='dfm']")).toBeVisible();
    await expect(dfmPanel.locator("[data-composer-dfm]")).toHaveCount(1);
    await expect(dfmPanel.locator("[data-dfm-auto-run-toggle]")).toHaveAttribute(
      "data-dfm-auto-run",
      "false",
    );
    await expect(dfmPanel.locator("[data-dfm-run]")).toHaveCount(1);

    // Every member is opt-out (§7A.3).
    await partChip.locator('[data-context-drop="part"]').click();
    await expect(partChip).toHaveAttribute("data-context-dropped", "");

    // §7A.3(e): an EXCLUDED member stays visible on the resting line. "The
    // agent will not be told about the part" is a fact about what is being
    // sent, so it is drawn rather than left to the absence of a token — and it
    // survives collapsing the form that removed it.
    await composer.locator("[data-context-disclose]").click();
    await expect(composer.locator("[data-context-chips]")).toHaveCount(0);
    await expect(summary.locator('[data-context-removed="part"]')).toHaveCount(1);
    await expect(summary).not.toContainText(PART);
    await composer.locator("[data-context-disclose]").click();

    // Add current view stays a real action on disclose; POST /context/preview
    // must still compose the camera token — a disclosure that said the agent
    // would be told nothing would be the client/server emptiness predicates
    // disagreeing.
    await composer.locator("[data-context-add-view]").click();
    const viewChip = composer.locator('[data-context-key="view"]');
    await expect(viewChip).not.toHaveAttribute("data-context-dropped", "");
    await expect(composer.locator("[data-context-preview]")).toBeVisible();
    await expect(composer.locator("[data-context-block]")).toContainText("camera view:");
  });

  test("the disclosure renders the server's block, and says it is advisory", async ({ page }) => {
    const created = await api<SessionDocument>("/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profile: "orchestrator" }),
    });
    await openSession(page, created.session_id);
    const composer = page.locator(`[data-composer][data-session-id="${created.session_id}"]`);
    await composer.locator("[data-context-disclose]").click();

    const block = composer.locator("[data-context-block]");
    await expect(block).toBeVisible();

    // DOM versus SERVER, never DOM versus a string typed into a test: the same
    // route the app calls answers here, and the two must agree byte for byte.
    const preview = await api<ContextDocument>("/context/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ context: { part: PART, stage_tab: "viewport" } }),
    });
    expect(preview.block).toContain(`## Part: ${PART}`);
    await expect(block).toContainText(`## Part: ${PART}`);

    // §7A.3: "The preview is **advisory**." The composed block the model is
    // handed comes back on the turn, not from here.
    expect(preview.sources).toContain(`/parts/${PART}/build`);
  });

  test("the preview refuses a member outside the closed set", async () => {
    // §7A.3: there is no free-form field, no number the client computed, and no
    // string the client authored — and an extra member is refused BY NAME
    // rather than ignored, because a silently dropped member is a context the
    // operator saw in the chip row and the model never received.
    const refused = await refusal("/context/preview", {
      context: { part: PART, bbox_mm: [250, 156, 5.5] },
    });
    expect(refused.status).toBe(400);
    expect(refused.body.reason).toBe("invalid_params");
  });
});

test.describe("the composer stays typable with no session", () => {
  test("the textarea is not disabled when GET /sessions is empty", async ({ page }) => {
    await page.route("**/api/v1/sessions", async (route) => {
      if (route.request().method() !== "GET") {
        await route.continue();
        return;
      }
      const path = new URL(route.request().url()).pathname.replace(/\/$/, "");
      if (path !== "/api/v1/sessions") {
        await route.continue();
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          status: "ok",
          sessions: [],
          profiles: [
            {
              profile: "orchestrator",
              can_delegate: true,
              part_scoped: false,
              requires_part: false,
            },
            { profile: "part", can_delegate: false, part_scoped: true, requires_part: true },
          ],
        }),
      });
    });
    await open(page, route(PART));
    const composer = page.locator("[data-composer]");
    await expect(composer).toHaveCount(1);
    await expect(composer).toHaveAttribute("data-disabled-reason", "no_session");
    const input = composer.locator("[data-composer-input]");
    await expect(input).toBeEnabled();
    await input.click();
    await input.fill("Ask about this plate.");
    await expect(input).toHaveValue("Ask about this plate.");
  });
});

test.describe("the composer creates its own session (§7A.5/§8, amended 2026-09-03)", () => {
  // Every other case in this file addresses a session `POST /sessions`
  // already minted — `openSession` navigates straight to `?s=<id>`. Real
  // first contact is the OTHER path: the operator lands on a blank canvas
  // with no `?s=` at all, types, and hits Send — the composer's OWN
  // `createSession` call mints the session, live. §7A.5(C1)/§8 both promise
  // the same echo and run-start boundary that an already-open session's
  // first turn gets; this is the reproduction that would have caught the
  // stale-`sessionId`-closure defect (`useStream.echo` used to be bound to
  // the tab's `sessionId` prop, which was still `null` at the instant
  // `createSession()` resolved, so the echo silently landed nowhere).
  test("the first turn's echo and run-start boundary render for a session the composer itself minted", async ({
    page,
  }) => {
    test.setTimeout(180_000);
    // Force `selected === null` on arrival — same technique as the block
    // above — so this send goes through Composer's create-then-send branch
    // rather than auto-selecting a pre-existing session (`StreamPanel.tsx`'s
    // "first session wins" default, §4.5).
    await page.route("**/api/v1/sessions", async (route) => {
      if (route.request().method() !== "GET") {
        await route.continue();
        return;
      }
      const path = new URL(route.request().url()).pathname.replace(/\/$/, "");
      if (path !== "/api/v1/sessions") {
        await route.continue();
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          status: "ok",
          sessions: [],
          profiles: [
            {
              profile: "orchestrator",
              can_delegate: true,
              part_scoped: false,
              requires_part: false,
            },
            { profile: "part", can_delegate: false, part_scoped: true, requires_part: true },
          ],
        }),
      });
    });

    await open(page, route(PART));
    const composer = page.locator("[data-composer]");
    await expect(composer).toHaveAttribute("data-disabled-reason", "no_session");
    await expect(composer.locator("[data-composer-input]")).toBeEnabled();

    await composer
      .locator("[data-composer-input]")
      .fill(`${world().composer.sentinel} please make me a part`);
    await composer.locator("[data-composer-send]").click();

    // The URL gains `?s=` for the session the composer itself minted — the
    // observable form of "today it creates over the API and opens ?s=<id>",
    // here reached from the composer's own POST rather than a pre-created one.
    await page.waitForFunction(() => window.location.hash.includes("s="), null, {
      timeout: 30_000,
    });
    await expect(page.locator("[data-composer][data-session-id]")).not.toHaveAttribute(
      "data-session-id",
      "",
    );

    // §7A.5 (C1): the echo renders for THIS session, not lost in the
    // create-then-send hand-off.
    const echoRow = page.locator('[data-row="local-prompt"]');
    await expect(echoRow).toHaveCount(1);
    await expect(echoRow).toContainText("please make me a part");
    await expect(echoRow).toHaveAttribute("data-echo-state", "sent");

    // The turn's events reach the transcript, and — §7.3 (C21) — the echo
    // licensed exactly one run-start boundary for the first frame, same as
    // an already-open session's first turn gets it.
    await expect(page.locator("[data-tool-name]").first()).toBeVisible({ timeout: 120_000 });
    const boundary = page.locator('[data-row="run-start"]');
    await expect(boundary).toHaveCount(1);
    expect(await boundary.getAttribute("data-event-id")).toBeNull();
  });
});

test.describe("§7A.12 case 7 — POST /sessions validation", () => {
  test("quick_edit is refused by name, pointing at the route that seeds one", async () => {
    // §7A.2's TIGHTENING. A bare create would produce that profile's
    // restrictions and NONE of its context — a scope the operator can feel but
    // cannot see — so the refusal names `POST /parts/{part}/quick_edit`.
    const refused = await refusal("/sessions", { profile: "quick_edit", part: PART });
    expect(refused.status).toBe(400);
    expect(refused.body.reason).toBe("invalid_params");
    expect(refused.body.message).toContain("quick_edit");
  });

  test("a part session with no part is refused", async () => {
    // Unvalidated, this produced a part-profile session bound to nothing, whose
    // every object-scoped call fails `scope_denied` against a `None` binding.
    const refused = await refusal("/sessions", { profile: "part" });
    expect(refused.status).toBe(400);
    expect(refused.body.reason).toBe("invalid_params");
  });
});

// ---------------------------------------------------------------------------
// §7A.12 case 6 — a serve with no `providers.json`
//
// Its own process, because it is a property of a differently configured SERVE.
// See `harness/no_agent_serve.py` for why it cannot be a flag on the G4 harness.

test.describe("§7A.12 case 6 — no agent runtime", () => {
  let child: ChildProcess | null = null;
  let baseUrl = "";
  let token = "";

  test.beforeAll(async () => {
    const started = await new Promise<{ proc: ChildProcess; url: string; token: string }>(
      (resolve, reject) => {
        const proc = spawn(
          world().python,
          [new URL("./harness/no_agent_serve.py", import.meta.url).pathname],
          { stdio: ["ignore", "pipe", "inherit"] },
        );
        const timer = setTimeout(() => {
          reject(new Error("the runtime-less serve never became ready"));
        }, 180_000);
        let buffer = "";
        proc.stdout?.on("data", (chunk: Buffer) => {
          buffer += chunk.toString("utf8");
          const line = buffer.split("\n").find((candidate) => candidate.startsWith("READY "));
          if (line === undefined) return;
          clearTimeout(timer);
          const [, url, bearer] = line.trim().split(" ");
          resolve({ proc, url: url ?? "", token: bearer ?? "" });
        });
        proc.on("exit", (code) => {
          clearTimeout(timer);
          reject(new Error(`the runtime-less serve exited with ${String(code)}`));
        });
      },
    );
    child = started.proc;
    baseUrl = started.url;
    token = started.token;
  });

  test.afterAll(() => {
    child?.kill("SIGTERM");
  });

  test("the composer renders disabled, with the named cause and the path", async ({ page }) => {
    await page.goto(`${baseUrl}/#t=${token}`);
    const composer = page.locator("[data-composer]");
    await expect(composer).toHaveCount(1, { timeout: 60_000 });

    // §7A.8: the refusal is right and does not change; what changes is that it
    // now carries its cause. "A disabled composer **with** its reason" is the
    // third option `StreamPanel.tsx`'s original reasoning did not consider.
    await expect(composer).toHaveAttribute("data-composer-state", "disabled");
    await expect(composer).toHaveAttribute("data-disabled-reason", "agent_unavailable");
    await expect(composer.locator("[data-attach-cause]")).toHaveAttribute(
      "data-attach-cause",
      "no_provider_config",
    );

    // It NAMES the file the server looked for. §7A.8: it does not offer to
    // write it, "because until §23 lands there is nothing behind such an offer
    // but a text editor".
    const path = await composer.locator("[data-attach-path]").getAttribute("data-attach-path");
    expect(path).toMatch(/providers\.json$/);

    // Named absence: do not render a model picker that reads as a signed-in agent.
    await expect(composer.locator("[data-composer-model]")).toHaveCount(0);
    await expect(composer.locator("[data-context-disclose]")).toHaveCount(1);
    await composer.locator("[data-context-disclose]").click();
    await expect(composer.locator("[data-context-add-view]")).toHaveCount(1);

    // The serve still answers every read route: `agent_unavailable` is about
    // sessions, not about the project.
    const project = await fetch(`${baseUrl}/api/v1/project`, {
      headers: { Authorization: `Bearer ${token}`, Connection: "close" },
    });
    expect(project.status).toBe(200);
  });

  test("the composer's own disclosure still works with no runtime", async ({ page }) => {
    // §7A.3's route is deliberately not gated on the runtime. A disclosure that
    // went dark exactly when the composer is disabled would be missing at the
    // one moment the operator is trying to understand why.
    const response = await fetch(`${baseUrl}/api/v1/context/preview`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        Connection: "close",
      },
      body: JSON.stringify({ context: { part: PART } }),
    });
    expect(response.status).toBe(200);
    const body = (await response.json()) as ContextDocument;
    expect(body.block).toContain(`## Part: ${PART}`);
    void page;
  });
});
