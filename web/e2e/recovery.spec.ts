// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
// PACKAGED server/fake-provider regression. No synthetic question documents;
// delayed responses below are actual authenticated reads of the live registry.
import { expect, test, type Page } from "@playwright/test";
import { api, open, route, world, startRecoveryWorld, closeRecoveryWorld } from "./harness/recoveryWorld";
import { archive } from "./harness/archive";
import type { SessionModelDocument } from "../src/api/sessions";

test.beforeAll(async ({ browserName }, info) => {
  expect(browserName).toBe("chromium");
  await startRecoveryWorld(info.project.outputDir);
});
test.afterAll(async () => { await closeRecoveryWorld(); });

const input = (page: Page) => page.locator("[data-composer-input]");
const ask = (page: Page) => page.locator('[data-question-id][data-ask-state]').last();
const recovered = (page: Page) => page.locator('[data-widget-source="live_state"]');
async function startFromUI(page: Page): Promise<string> {
  await open(page, route("tread"));
  await page.getByRole("button", { name: "New conversation", exact: true }).click();
  await page.getByText("New conversation", { exact: true }).last().click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Create conversation", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await input(page).fill(`${world().ask.sentinel}: ask which wall thickness before changing anything`);
  await expect(page.locator("[data-composer-send]")).not.toHaveAttribute("aria-disabled", "true");
  const sid = await page.locator("[data-composer]").getAttribute("data-session-id");
  expect(sid).toBeTruthy();
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(ask(page)).toHaveAttribute("data-ask-state", "answerable");
  await expect(page.locator('[data-current-turn="Waiting for your answer"]')).toBeVisible();
  return sid!;
}
async function knownRead(sid: string) {
  return api<SessionModelDocument>(`/sessions/${encodeURIComponent(sid)}/model`);
}
async function finishOwned(sid: string) {
  // Failure cleanup only. Never used to establish recovery/task success.
  const doc = await knownRead(sid);
  if (doc.execution.active_run_id) await api(`/runs/${encodeURIComponent(doc.execution.active_run_id)}/cancel`, { method: "POST" });
}

// Two writes are needed for setup (explicit Create + Send); reload must not
// repeat either, and the visible answer contributes exactly one further write.
test("real reload mid-question recovers exact options and accepts one UI answer; wrong-session read/refusal", async ({ page }, info) => {
  const writes: string[] = [];
  const receipts: { accepted: boolean; answer: unknown }[] = [];
  page.on("request", request => {
    if (["POST", "PUT"].includes(request.method()) && !request.url().endsWith("/context/preview")) writes.push(new URL(request.url()).pathname);
  });
  page.on("response", response => {
    if (response.url().endsWith("/answer")) void response.json().then(doc => receipts.push(doc));
  });
  const sid = await startFromUI(page);
  try {
    const before = await knownRead(sid);
    const question = before.live_questions?.pending[0];
    expect(question).toBeTruthy();
    expect(question?.question_id).toBe(await ask(page).getAttribute("data-question-id"));
    await archive(page, info, "recovery-before-real-reload");
    await page.reload();
    await expect(recovered(page)).toBeVisible();
    await expect(page.locator('[data-current-turn="Waiting for your answer"]')).toBeVisible();
    await expect(recovered(page)).toHaveAttribute("data-question-id", question!.question_id);
    await expect(recovered(page)).not.toHaveAttribute("data-event-id", /.+/);
    await expect(recovered(page)).toContainText("Recovered from the live run");
    await expect(recovered(page).locator("[data-ask-text]")).toHaveCount(0);
    expect(await recovered(page).locator("[data-ask-option]").allTextContents()).toEqual(world().ask.options.map(o => o.label));
    expect(await recovered(page).locator("[data-ask-consequence]").allTextContents()).toEqual(world().ask.options.map(o => o.consequence));
    await expect(page.locator('[data-widget-source="tool_result"] [data-ask-option]').first()).toHaveAttribute("aria-disabled", "true");
    await page.setViewportSize({ width: 843, height: 800 });
    await page.getByRole("button", { name: "Go to question" }).click();
    await archive(page, info, "recovery-after-real-reload-843");

    const other = world().sessions[0]!;
    expect(other).not.toBe(sid);
    const foreignRead = await knownRead(other);
    expect(foreignRead.live_questions?.pending).toEqual([]);
    const foreign = await page.request.post(`${world().base_url}/api/v1/sessions/${encodeURIComponent(other)}/answer`, {
      headers: { Authorization: `Bearer ${world().token}` }, data: { question_id: question!.question_id, answer: "foreign must not win" },
    });
    expect(foreign.status()).toBe(404);
    expect(await foreign.json()).not.toHaveProperty("answer");
    expect((await knownRead(sid)).live_questions?.pending).toEqual(before.live_questions?.pending);

    await input(page).fill("A newer draft, never queued");
    const answerResponse = page.waitForResponse(r => r.url().endsWith(`/sessions/${sid}/answer`));
    await recovered(page).getByRole("button", { name: world().ask.options[1]!.label, exact: true }).click();
    expect((await (await answerResponse).json()).accepted).toBe(true);
    await expect(page.locator('[data-current-turn="Completed"]')).toBeVisible();
    await expect(page.locator("[data-ask-answer]").last()).toContainText(world().ask.options[1]!.label);
    await expect(input(page)).toHaveValue("A newer draft, never queued");
    expect((await knownRead(sid)).live_questions?.pending).toEqual([]);
    expect(receipts).toEqual([{ ...receipts[0], accepted: true, answer: world().ask.options[1]!.label }]);
    expect(writes).toEqual(["/api/v1/sessions", `/api/v1/sessions/${sid}/prompt`, `/api/v1/sessions/${sid}/answer`]);
    await archive(page, info, "recovery-answer-once-completed");
    await page.reload();
    await expect(page.locator("[data-ask-answer]").last()).toContainText(world().ask.options[1]!.label);
    await expect(page.locator('[data-answered-by="other"]')).toHaveCount(0);
    await expect(recovered(page)).toHaveCount(0);
    expect(writes).toHaveLength(3);
  } finally { await finishOwned(sid); }
});

for (const reconnect of [false, true]) test(`real pending snapshot delayed past remote answer/terminal${reconnect ? " and stale reconnect" : ""} cannot resurrect controls`, async ({ page, context }, info) => {
  let interrupt: (() => Promise<void>) | undefined;
  if (reconnect) await page.routeWebSocket("**/api/v1/events", socket => {
    socket.connectToServer();
    interrupt = () => socket.close({ code: 1001, reason: "disposable reconnect regression" });
  });
  const sid = await startFromUI(page);
  const observer = await context.newPage();
  let release: (() => void) | undefined;
  let held: Promise<void> | undefined;
  let intercepted = false;
  let readCaptured: (() => void) | undefined;
  const captured = new Promise<void>(resolve => { readCaptured = resolve; });
  const writes: string[] = [];
  page.on("request", r => { if (r.method() === "POST" && !r.url().endsWith("/context/preview")) writes.push(new URL(r.url()).pathname); });
  try {
    await page.reload();
    await expect(recovered(page)).toBeVisible();
    await open(observer, route("tread", { s: sid }));
    await expect(recovered(observer)).toBeVisible(); // a client first attached AFTER the question
    const before = await knownRead(sid);
    await page.route(`**/sessions/${sid}/model`, async route_ => {
      if (intercepted || route_.request().method() !== "GET") { await route_.continue(); return; }
      intercepted = true;
      const response = await route_.fetch();
      const document = await response.json() as SessionModelDocument;
      expect(document.live_questions?.pending).toEqual(before.live_questions?.pending);
      held = new Promise<void>(resolve => { release = resolve; });
      readCaptured?.();
      await held;
      await route_.fulfill({ response }); // unchanged actual response, now stale
    });
    // Controlled read scheduling, not a product write or invented snapshot.
    await page.evaluate(() => window.dispatchEvent(new Event("online")));
    await captured;
    if (reconnect) {
      // Close this page's actual socket; the normal retained-cursor reconnect
      // runs while an older authenticated question snapshot remains delayed.
      expect(interrupt).toBeDefined();
      await interrupt!();
    }
    await recovered(observer).getByRole("button", { name: world().ask.options[0]!.label, exact: true }).click();
    await expect(observer.locator('[data-current-turn="Completed"]')).toBeVisible();
    release?.();
    await expect(page.locator('[data-current-turn="Completed"]')).toBeVisible();
    await expect(page.locator('[data-question-id] [data-ask-option]:not([aria-disabled="true"])')).toHaveCount(0);
    expect(writes).toEqual([]);
    expect((await knownRead(sid)).live_questions?.pending).toEqual([]);
    await archive(page, info, reconnect ? "recovery-stale-reconnect" : "recovery-answer-terminal-beat-read");
  } finally {
    release?.();
    await page.unrouteAll({ behavior: "wait" });
    await observer.close();
    await finishOwned(sid);
  }
});
