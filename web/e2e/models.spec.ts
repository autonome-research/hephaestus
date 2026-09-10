// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
// Packaged browser -> HTTP -> sidecar -> disposable provider, with no interception.
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import type { ModelsDocument } from "../src/api/providers";
import type { SessionModelDocument } from "../src/api/sessions";
import { api, open, route, world } from "./harness/world";

function requests(): { index: number; model: string }[] {
  return readFileSync(world().model_observations, "utf8").trim().split("\n")
    .filter(Boolean).map(line => JSON.parse(line) as { index: number; model: string });
}

test("actual picker preserves the session/draft and changes the next provider HTTP request; busy selection refuses", async ({ page }) => {
  const catalog = await api<ModelsDocument>("/providers/models");
  const options = catalog.providers.flatMap(p => p.models);
  const text = options.find(m => m.available && m.input?.length === 1)!;
  const vision = options.find(m => m.available && m.input?.includes("image"))!;
  expect(text).toBeDefined();
  expect(vision).toBeDefined();
  expect(catalog.proposed_default?.model_id).toBe(vision.model_id);
  const ref = (m: typeof text) => ({ provider_id: m.provider_id, model_id: m.model_id });
  const created = await api<SessionModelDocument>("/sessions", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ profile: "orchestrator", model: ref(text) }),
  });
  const sid = created.session_id;
  await open(page, route("tread", { s: sid }));
  const composer = page.locator(`[data-composer][data-session-id="${sid}"]`);
  const input = composer.locator("[data-composer-input]");
  const send = composer.locator("[data-composer-send]");
  const picker = page.locator("[data-model-button]");
  await expect(picker).toContainText(text.model_id);
  await expect(picker).toContainText("Text only");
  await expect(page.locator('[data-testid="stream-panel"]')).toHaveAttribute("data-stream", "live");

  const beforeText = requests().length;
  await input.fill("HEPH_MODEL_SELECTION first text-only turn");
  const textTurn = page.waitForResponse(r => r.url().endsWith(`/sessions/${sid}/prompt`) && r.request().method() === "POST");
  await send.click();
  expect((await (await textTurn).json() as { run_status: string }).run_status).toBe("completed");
  expect(requests().slice(beforeText).map(r => r.model)).toEqual([text.model_id]);
  await expect(page.getByText("HEPH_MODEL_SELECTION_DONE", { exact: true })).toBeVisible();
  const historyBefore = await page.locator("[data-event-id]").evaluateAll(nodes => nodes.map(n => n.getAttribute("data-event-id")));
  expect(historyBefore.length).toBeGreaterThan(0);

  const draft = `${world().ask.sentinel} HEPH_MODEL_SELECTION keep this draft while switching`;
  await input.fill(draft);
  const beforeSwitch = requests().length;
  await expect(picker).toBeEnabled();
  await picker.click();
  await page.getByRole("combobox").fill(vision.model_id);
  const option = page.getByRole("option").filter({ hasText: `${vision.provider_id}/${vision.model_id}` });
  await expect(option).toHaveAttribute("aria-disabled", "false");
  await option.click();
  await expect(picker).toContainText(vision.model_id);
  await expect(picker).toContainText("Text + images");
  await expect(input).toHaveValue(draft);
  await expect(composer).toHaveAttribute("data-session-id", sid);
  const selected = await api<SessionModelDocument>(`/sessions/${sid}/model`);
  expect(selected.model_state).toMatchObject({ state: "ready", current: { ...ref(vision), input: ["text", "image"] }, selected: ref(vision) });
  expect(selected.model_state.revision).not.toEqual(created.model_state.revision);
  expect(requests()).toHaveLength(beforeSwitch);
  for (const id of historyBefore) await expect(page.locator(`[data-event-id="${id}"]`)).toHaveCount(1);

  const shots = "/tmp/hephaestus-model-selection-validation";
  mkdirSync(shots, { recursive: true });
  for (const width of [843, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    if (width < 1024) await page.getByRole("button", { name: "Expand the agent column" }).click();
    expect(page.url()).not.toContain(world().token);
    expect(await page.locator("body").innerText()).not.toContain(world().token);
    await expect(picker).toBeEnabled();
    await page.screenshot({ path: `${shots}/picker-${width}-closed.png` });
    await picker.click();
    await expect(page.getByRole("combobox")).toBeVisible();
    await expect(page.getByRole("option")).toHaveCount(2);
    for (const choice of await page.getByRole("option").all()) await expect(choice).toHaveAttribute("aria-disabled", "false");
    await page.screenshot({ path: `${shots}/picker-${width}-open.png` });
    await page.keyboard.press("Escape");
    await expect(input).toHaveValue(draft);
  }
  expect(requests()).toHaveLength(beforeSwitch);

  const visionTurn = page.waitForResponse(r => r.url().endsWith(`/sessions/${sid}/prompt`) && r.request().method() === "POST");
  await send.click();
  const question = page.locator('[data-testid="transcript"] [data-ask-state]').last();
  await expect(question).toHaveAttribute("data-ask-state", "answerable");
  expect(requests().slice(beforeSwitch).map(r => r.model)).toEqual([vision.model_id]);
  await expect(picker).toHaveAttribute("aria-disabled", "true");
  const { base_url, token } = world();
  const refused = await fetch(`${base_url}/api/v1/sessions/${sid}/model`, {
    method: "PUT", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json", Connection: "close" },
    body: JSON.stringify({ model: ref(text), expected_model_revision: selected.model_state.revision }),
  });
  expect(refused.status).toBe(409);
  expect(await refused.json()).toMatchObject({ reason: "run_in_flight", session_id: sid, scope: "session" });
  expect((await api<SessionModelDocument>(`/sessions/${sid}/model`)).model_state.current).toMatchObject(ref(vision));
  await question.locator("[data-ask-option]").first().click();
  expect((await (await visionTurn).json() as { run_status: string }).run_status).toBe("completed");
  expect(requests().slice(beforeSwitch).map(r => r.model)).toEqual([vision.model_id, vision.model_id]);
  await expect(picker).toBeEnabled();
  expect((await api<SessionModelDocument>(`/sessions/${sid}/model`)).model_state.selected).toEqual(ref(vision));
  // Reload is a new browser adoption, not a claim of sidecar restart coverage.
  await page.reload();
  await expect(page.locator(`[data-composer][data-session-id="${sid}"]`)).toBeVisible();
  await expect(picker).toContainText(vision.model_id);
  await expect(question).toHaveAttribute("data-ask-state", "answered");
  writeFileSync(`${shots}/packaged-evidence.json`, JSON.stringify({
    session_id: sid, initial: created.model_state, selected: selected.model_state,
    provider_requests: requests().slice(beforeText), busy_status: refused.status,
    browser_readoption: "same session and selected model after reload; not a sidecar restart",
  }, null, 2) + "\n");
});
