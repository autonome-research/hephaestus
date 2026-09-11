import { expect, test } from "@playwright/test";
import { api, open, route, world, startRecoveryWorld, closeRecoveryWorld } from "./harness/recoveryWorld";
import type { CreatedSessionDocument, SessionModelDocument } from "../src/api/sessions";
import type { ModelsDocument } from "../src/api/providers";
import { writeFileSync } from "node:fs";

test.beforeAll(async ({ browserName }, info) => {
  expect(browserName).toBe("chromium");
  test.setTimeout(600_000);
  await startRecoveryWorld(info.outputPath("unknown-receipt-world"));
});
test.afterAll(async () => { await closeRecoveryWorld(); });

test("lost browser prompt response plus dropped Stop must allow same-run explicit retry", async ({ page }, info) => {
  test.setTimeout(180_000);
  const external: string[] = [];
  const writes: string[] = [];
  page.on("request", request => { if (request.method() === "POST") writes.push(new URL(request.url()).pathname); });
  await page.context().route("**/*", async r => {
    if (new URL(r.request().url()).origin !== world().base_url) { external.push(new URL(r.request().url()).origin); await r.abort(); }
    else await r.fallback();
  });
  await page.routeWebSocket("**/*", ws => {
    if (new URL(ws.url()).host !== new URL(world().base_url).host) { external.push(new URL(ws.url()).origin); void ws.close(); }
    else ws.connectToServer();
  });
  const models = await api<ModelsDocument>("/providers/models");
  const created = await api<CreatedSessionDocument>("/sessions", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ profile: "orchestrator", model: { provider_id: models.proposed_default!.provider_id, model_id: models.proposed_default!.model_id } }) });
  const sid = created.session_id;
  await open(page, route("tread", { s: sid }));
  await expect(page.locator('[data-testid="stream-panel"]')).toHaveAttribute("data-stream", "live");
  let losePrompt = () => {};
  const lossEdge = new Promise<void>(resolve => { losePrompt = resolve; });
  let forwarded: Promise<unknown> | undefined;
  await page.route(`**/sessions/${sid}/prompt`, async r => {
    forwarded = r.fetch({ timeout: 150_000 }); // real delivered request; response channel remains owned by harness
    void forwarded.catch(() => undefined);
    await lossEdge;
    await r.abort("failed"); // lose only browser transport, not the server's waiting turn
  });
  let runId: string | null = null;
  try {
    await page.locator("[data-composer-input]").fill(world().ask.sentinel);
    await page.getByRole("button", { name: "Send", exact: true }).click();
    await expect(page.locator('[data-current-turn="Waiting for your answer"]')).toBeVisible();
    const waiting = await api<SessionModelDocument>(`/sessions/${sid}/model`);
    runId = waiting.execution.active_run_id;
    expect(runId).not.toBeNull();
    expect(waiting.live_questions?.pending).toHaveLength(1);
    losePrompt();
    await expect(page.locator('[data-composer][data-send-state="unknown"]')).toBeVisible();
    const cancelPath = `/api/v1/runs/${runId}/cancel`;
    let cancels = 0;
    await page.route(`**${cancelPath}`, async r => { cancels++; if (cancels === 1) await r.abort("failed"); else await r.continue(); });
    await page.locator("[data-composer-input]").fill("preserve next draft");
    await page.getByRole("button", { name: "Stop", exact: true }).click();
    await expect(page.locator("[data-cancel-note]")).toContainText("request or response may be lost");
    // Observe a positive browser read edge AFTER Stop failure, then independent readback.
    await page.waitForResponse(r => r.request().method() === "GET" && r.url().endsWith(`/sessions/${sid}/model`) && r.status() === 200);
    const active = await api<SessionModelDocument>(`/sessions/${sid}/model`);
    expect(active.execution.active_run_id).toBe(runId);
    expect(active.live_questions?.pending).toHaveLength(1);
    expect(cancels).toBe(1);
    expect(external).toEqual([]);
    const evidence = { sid, runId, execution: active.execution, questionCount: active.live_questions?.pending.length,
      modelRevision: active.model_state.revision, cancels, writes, external, stopText: await page.locator("[data-composer-cancel]").innerText(),
      stopDisabled: await page.locator("[data-composer-cancel]").isDisabled(), promptState: await page.locator("[data-composer]").getAttribute("data-send-state") };
    writeFileSync(info.outputPath("same-run-authority.json"), JSON.stringify(evidence, null, 2));
    await page.screenshot({ path: info.outputPath("same-run-retry.png") });
    await expect(page.getByRole("button", { name: "Retry Stop", exact: true })).toBeEnabled();
    await expect(page.getByRole("button", { name: "Send", exact: true })).toBeDisabled();
    await page.getByRole("button", { name: "Retry Stop", exact: true }).click();
    await expect(page.locator("[data-composer-cancel]")).toHaveCount(0);
    const terminal = await api<SessionModelDocument>(`/sessions/${sid}/model`);
    expect(terminal.execution.active_run_id).toBeNull();
    expect(terminal.execution.terminal).toMatchObject({ run_id: runId, state: "cancelled" });
    expect(terminal.live_questions?.pending).toHaveLength(0);
    expect(cancels).toBe(2);
    expect(writes.filter(path => path.endsWith("/prompt"))).toHaveLength(1);
    expect(writes.filter(path => path.endsWith("/answer"))).toHaveLength(0);
    expect(external).toEqual([]);
    await expect(page.locator("[data-composer-input]")).toHaveValue("preserve next draft");
  } finally {
    losePrompt();
    const current = await api<SessionModelDocument>(`/sessions/${sid}/model`, { signal: AbortSignal.timeout(30_000) });
    if (runId !== null && current.execution.active_run_id === runId) await api(`/runs/${runId}/cancel`, { method: "POST", signal: AbortSignal.timeout(30_000) });
    await forwarded?.catch(() => undefined);
  }
});
