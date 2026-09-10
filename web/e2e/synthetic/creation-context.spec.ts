// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
import { expect, test, type Page } from "@playwright/test";
import { setup, SID, input } from "./fixture";
import { models, spark, vision } from "../../test/fixtures/models";

async function openCreation(page: Page) {
  await page.locator("[data-session-create-menu]").click();
  await page.locator("[data-session-ask]").click();
  const dialog = page.getByRole("dialog", { name: "New conversation · bracket", exact: true });
  await expect(dialog).toBeVisible();
  return dialog;
}
for (const width of [1440, 843]) test(`bounded creation, inert keyboard/cancel, exact idle create and visible context ownership at ${width}`, async ({ page }) => {
  await page.setViewportSize({ width, height: 800 });
  const c = await setup(page);
  await expect(page.locator("[data-model-button]")).toContainText("Current model");
  await input(page).fill("original draft — never replace");
  const identity = await page.locator("[data-model-button]").textContent();
  const route = new URL(page.url()).hash;
  const dialog = await openCreation(page);
  await expect(dialog.locator("[data-model-button]")).toHaveCount(1);
  await expect(dialog.getByLabel("Scope", { exact: true })).toBeFocused();
  // Native modal top layer actually denies programmatic focus to old controls.
  await input(page).evaluate(el => (el as HTMLElement).focus());
  expect(await page.evaluate(() => document.activeElement?.closest("dialog") !== null)).toBe(true);
  await page.keyboard.press("Shift+Tab");
  await expect(dialog.locator("[data-create-confirm]")).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(dialog.getByLabel("Scope", { exact: true })).toBeFocused();
  await dialog.locator("[data-model-button]").click();
  const picker = page.getByRole("dialog", { name: "Choose model", exact: true });
  await expect(picker.getByRole("option").filter({ hasText: "unknown" })).toHaveAttribute("aria-disabled", "true");
  await picker.getByRole("combobox").fill("unknown");
  await picker.getByRole("combobox").press("Enter");
  await expect(dialog.locator("[data-model-button]")).toContainText(vision.name);
  expect(c.mutations).toEqual([]);
  await page.keyboard.press("Escape");
  await expect(dialog).toBeVisible(); // Escape closes only the nested picker.
  await dialog.locator("[data-model-button]").click();
  await picker.getByRole("option").filter({ hasText: `${spark.provider_id}/${spark.model_id}` }).click();
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(dialog).not.toBeVisible();
  await expect(page.locator("[data-session-create-menu]")).toBeFocused();
  await expect(input(page)).toHaveValue("original draft — never replace");
  expect(await page.locator("[data-model-button]").textContent()).toBe(identity);
  expect(new URL(page.url()).hash).toBe(route);
  expect(c.mutations).toEqual([]);

  const next = await openCreation(page);
  await expect(next.locator("[data-model-button]")).toContainText(vision.name); // cancelled choice did not replace proposal
  await page.keyboard.press("Escape");
  await expect(next).not.toBeVisible();
  await expect(page.locator("[data-session-create-menu]")).toBeFocused();
  await openCreation(page);
  await next.locator("[data-model-button]").click();
  await picker.getByRole("option").filter({ hasText: `${spark.provider_id}/${spark.model_id}` }).click();
  await next.locator("[data-create-confirm]").click();
  await expect(input(page)).toBeFocused();
  await expect(input(page)).toHaveValue("");
  await expect(page.locator("[data-composer]")).toHaveAttribute("data-session-id", "synthetic-created");
  expect(c.mutations).toEqual([{ path: "/sessions", body: { profile: "part", part: "bracket", model: { provider_id: spark.provider_id, model_id: spark.model_id } } }]);
  await expect(page.locator("[data-conversation-scope]")).toHaveText("Part: bracket");
  await expect(page.locator("[data-model-button]")).toContainText(spark.name);
  await input(page).fill("next session draft");
  await page.evaluate(() => { location.hash = "#/p/other-part?s=synthetic-created"; });
  await expect(page.locator("[data-context-mismatch]")).toContainText("Conversation scoped to bracket; next message includes the viewed other-part");
  await expect(page.locator("[data-context-summary]")).toContainText("Next message includes:");
  await expect(page.locator('[data-context-token="part"]')).toHaveText("other-part");
  await page.locator("[data-context-disclose]").click();
  await page.locator('[data-context-drop="part"]').click();
  await expect(page.locator("[data-context-mismatch]")).toContainText("part reference excluded");
  await page.locator('[data-context-drop="part"]').click();
  await page.locator("[data-view-scope]").click();
  await expect(page.locator("[data-context-mismatch]")).toHaveCount(0);
  await expect(page.locator('[data-context-token="part"]')).toHaveText("bracket");
  await expect(input(page)).toHaveValue("next session draft");
  await page.locator("[data-session-switch]").click();
  await page.locator(`[data-session-option="${SID}"]`).click();
  await expect(input(page)).toHaveValue("original draft — never replace");
  // POST /context/preview is the existing read-only advisory route, not a write.
  expect(c.mutations.filter(request => request.path !== "/context/preview")).toHaveLength(1);
  expect(c.mutations.filter(request => request.path === "/context/preview").length).toBeGreaterThan(0);
  expect(c.faults).toEqual([]);
});

for (const unavailable of [false, true]) test(`${unavailable ? "unavailable" : "unknown"} creation default requires explicit choice, never a fallback`, async ({ page }) => {
  const c = await setup(page);
  const catalog = unavailable ? { ...models, providers: models.providers.map(p => ({ ...p,
    models: p.models.map(m => m.model_id === vision.model_id ? { ...m, available: false, unavailable_reason: "model_unavailable" } : m),
  })) } : { ...models, proposed_default: null };
  await page.route("**/providers/models", route => route.fulfill({ json: catalog }));
  const refreshed = page.waitForResponse(r => r.url().endsWith("/providers/models"));
  await page.locator("[data-model-button]").click();
  await refreshed;
  await page.keyboard.press("Escape");
  const dialog = await openCreation(page);
  await expect(dialog.locator("[data-model-button]")).toContainText(unavailable ? vision.name : "Selection required");
  if (unavailable) await expect(dialog).toContainText("Not currently eligible");
  await expect(dialog.locator("[data-create-confirm]")).toBeDisabled();
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  expect(c.mutations).toEqual([]);
});
