// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
// Real built UI + packaged sidecar + unchanged 16-request fake script, in a
// separate owned world. Transport injection is at the browser HTTP boundary;
// execution/question readback and all terminal events remain real.
import { expect, test } from "@playwright/test";
import { api, open, route, world, startRecoveryWorld, closeRecoveryWorld } from "./harness/recoveryWorld";
import type { CreatedSessionDocument, SessionModelDocument, PromptDocument, CancelDocument } from "../src/api/sessions";
import type { ModelsDocument } from "../src/api/providers";

test.beforeAll(async ({ browserName }, info) => {
  expect(browserName).toBe("chromium");
  test.setTimeout(600_000); // packaged setup hang detector, unchanged model budget
  await startRecoveryWorld(info.outputPath("stop-owned"));
});
test.afterAll(async () => { await closeRecoveryWorld(); });

for (const scenario of ["dropped request with explicit retry", "dropped request then reload", "lost response after terminal"] as const) {
  test(scenario, async ({ page }, info) => {
    test.setTimeout(180_000); // real packaged startup/turn hang detector
    await page.setViewportSize({ width: 1440, height: 900 });
    const external: string[] = [];
    const errors: string[] = [];
    const writes: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.context().route("**/*", async r => {
      const url = new URL(r.request().url());
      if (url.origin !== world().base_url) {
        external.push(url.origin);
        await r.abort();
        return;
      }
      if (r.request().method() === "POST") writes.push(url.pathname);
      await r.fallback();
    });
    await page.routeWebSocket("**/*", ws => {
      if (new URL(ws.url()).host !== new URL(world().base_url).host) {
        external.push(new URL(ws.url()).origin);
        void ws.close();
      } else ws.connectToServer();
    });
    const models = await api<ModelsDocument>("/providers/models");
    expect(models.proposed_default).not.toBeNull();
    const created = await api<CreatedSessionDocument>("/sessions", { method: "POST",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ profile: "orchestrator", model: {
        provider_id: models.proposed_default!.provider_id, model_id: models.proposed_default!.model_id } }) });
    const sid = created.session_id;
    await open(page, route("tread", { s: sid }));
    await expect(page.locator('[data-testid="stream-panel"]')).toHaveAttribute("data-stream", "live");
    const turn = api<PromptDocument>(`/sessions/${sid}/prompt`, { method: "POST", signal: AbortSignal.timeout(150_000),
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: world().ask.sentinel,
        expected_model_revision: created.model_state.revision }) });
    // Keep a rejection observed even if a browser assertion fails first.
    void turn.catch(() => undefined);
    let release = () => {};
    let delivered: CancelDocument | null = null;
    const cancelPaths: string[] = [];
    let runId: string | null = null;
    try {
      await expect(page.locator('[data-current-turn="Waiting for your answer"]')).toBeVisible();
      const before = await api<SessionModelDocument>(`/sessions/${sid}/model`);
      runId = before.execution.active_run_id;
      expect(runId).not.toBeNull();
      expect(before.live_questions?.pending).toHaveLength(1);
      const cancelPath = `/api/v1/runs/${runId}/cancel`;
      const input = page.locator("[data-composer-input]");
      await input.fill("keep this next-message draft");
      const held = new Promise<void>(resolve => { release = resolve; });
      await page.route(`**${cancelPath}`, async r => {
        cancelPaths.push(new URL(r.request().url()).pathname);
        if (cancelPaths.length > 1) { await r.continue(); return; }
        if (scenario === "lost response after terminal") {
          const response = await r.fetch(); // server receives Stop and abandons the question
          expect(response.status()).toBe(200);
          delivered = await response.json() as CancelDocument;
          await held; // terminal must clear Stop while the HTTP callback is still pending
        }
        await r.abort("failed"); // request never sent OR response deliberately lost
      });
      await page.getByRole("button", { name: "Stop", exact: true }).click();
      if (scenario !== "lost response after terminal") {
        await expect(page.getByRole("button", { name: "Retry Stop", exact: true })).toBeEnabled();
        await expect(page.locator("[data-cancel-note]")).toContainText("request or response may be lost");
        const stillActive = await api<SessionModelDocument>(`/sessions/${sid}/model`);
        expect(stillActive.execution.active_run_id).toBe(runId);
        expect(stillActive.live_questions?.pending[0]?.question_id).toBe(before.live_questions?.pending[0]?.question_id);
        expect(cancelPaths).toEqual([cancelPath]); // positive reconciliation edge, no timed negative
        await expect(input).toHaveValue("keep this next-message draft");
        await page.screenshot({ path: info.outputPath("retry-stop.png") });
        if (scenario === "dropped request then reload") {
          await page.reload();
          await expect(page.locator('[data-current-turn="Waiting for your answer"]')).toBeVisible();
          // Reload has no delivery receipt to invent: known active authority
          // offers ordinary Stop, not an automatic replay or fake acknowledgement.
          expect(cancelPaths).toEqual([cancelPath]);
          await page.getByRole("button", { name: "Stop", exact: true }).click();
        } else await page.getByRole("button", { name: "Retry Stop", exact: true }).click();
      }
      await expect(page.locator('[data-current-turn="Cancelled"]')).toBeVisible();
      await expect(page.locator("[data-composer-cancel]")).toHaveCount(0);
      await expect(page.locator("[data-cancel-note]")).toHaveCount(0);
      release();
      const result = await turn;
      expect(result.run_id).toBe(runId);
      expect(result.run_status).toBe("cancelled");
      const ended = await api<SessionModelDocument>(`/sessions/${sid}/model`);
      expect(ended.execution.active_run_id).toBeNull();
      expect(ended.execution.terminal?.state).toBe("cancelled");
      expect(ended.live_questions?.pending).toEqual([]);
      expect(ended.model_state.revision).toEqual(before.model_state.revision);
      await expect(page.locator("[data-composer-cancel]")).toHaveCount(0);
      await expect(page.locator("[data-cancel-note]")).toHaveCount(0);
      expect(cancelPaths).toEqual(scenario === "lost response after terminal" ? [cancelPath] : [cancelPath, cancelPath]);
      if (scenario === "lost response after terminal") expect(delivered).toMatchObject({ run_id: runId, abandoned_questions: 1 });
      expect(writes.filter(path => /\/(prompt|answer)$/.test(path))).toEqual([]);
      expect(external).toEqual([]);
      expect(errors).toEqual([]);
      await info.attach("stop-authority", { contentType: "application/json", body: JSON.stringify({ scenario, sid, runId,
        cancelPaths, terminal: ended.execution.terminal, modelRevision: ended.model_state.revision, external, errors }) });
      await page.screenshot({ path: info.outputPath("terminal.png") });
    } finally {
      release();
      const current = await api<SessionModelDocument>(`/sessions/${sid}/model`, { signal: AbortSignal.timeout(30_000) });
      if (runId !== null && current.execution.active_run_id === runId) {
        await api(`/runs/${runId}/cancel`, { method: "POST", signal: AbortSignal.timeout(30_000) });
      }
      await turn.catch(() => undefined);
    }
  });
}
