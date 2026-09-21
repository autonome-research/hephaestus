// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
import { expect, test, type Page } from "@playwright/test";
import { setup, SID, input, modelName } from "./fixture";
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
  await expect(page.locator("[data-model-button]")).toHaveAccessibleName(/Current model/);
  await input(page).fill("original draft — never replace");
  const identity = await modelName(page);
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
  // The picker is an ANCHORED popover now, not a nested modal — `role="group"`
  // — and its entries are named by the configured model name rather than by
  // the provider/model pair, which §7A keeps for assistive technology on the
  // group label and the control's accessible name.
  const picker = page.getByRole("group", { name: "Choose model", exact: true });
  const unknown = picker.getByRole("option").filter({ hasText: "Unknown declaration" });
  await expect(unknown).toHaveAttribute("aria-disabled", "true");
  // Walk onto it with the arrows rather than pressing it where it stands:
  // the highlighted entry is listbox STATE, and a bare `press` would focus
  // this row while Enter still took whichever row the state was pointing at.
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowDown");
  await expect(unknown).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(picker).toBeVisible(); // refused, and the menu stays open
  await expect(dialog.locator("[data-model-button]")).toContainText(vision.name);
  expect(c.mutations).toEqual([]);
  await page.keyboard.press("Escape");
  await expect(dialog).toBeVisible(); // Escape closes only the nested picker.
  await dialog.locator("[data-model-button]").click();
  await picker.getByRole("option").filter({ hasText: spark.name }).click();
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(dialog).not.toBeVisible();
  await expect(page.locator("[data-session-create-menu]")).toBeFocused();
  await expect(input(page)).toHaveValue("original draft — never replace");
  expect(await modelName(page)).toBe(identity);
  expect(new URL(page.url()).hash).toBe(route);
  expect(c.mutations).toEqual([]);

  const next = await openCreation(page);
  await expect(next.locator("[data-model-button]")).toContainText(vision.name); // cancelled choice did not replace proposal
  await page.keyboard.press("Escape");
  await expect(next).not.toBeVisible();
  await expect(page.locator("[data-session-create-menu]")).toBeFocused();
  await openCreation(page);
  await next.locator("[data-model-button]").click();
  await picker.getByRole("option").filter({ hasText: spark.name }).click();
  await next.locator("[data-create-confirm]").click();
  await expect(input(page)).toBeFocused();
  await expect(input(page)).toHaveValue("");
  await expect(page.locator("[data-composer]")).toHaveAttribute("data-session-id", "synthetic-created");
  expect(c.mutations).toEqual([{ path: "/sessions", body: { profile: "part", part: "bracket", model: { provider_id: spark.provider_id, model_id: spark.model_id } } }]);
  await expect(page.locator("[data-conversation-scope]")).toHaveText("Part: bracket");
  await expect(page.locator("[data-model-button]")).toHaveAccessibleName(new RegExp(`${spark.provider_id}/${spark.model_id}`));
  await input(page).fill("next session draft");
  await page.evaluate(() => { location.hash = "#/p/other-part?s=synthetic-created"; });
  /*
   * The SCOPE MISMATCH is the half of the context readout that survived
   * (2026-09-20). The summary line, its member tokens and the per-member drop
   * chips are struck — the composer does not narrate its envelope any more —
   * but the mismatch note is not narration: it is a warning that the
   * conversation and the view disagree, which the operator cannot see any
   * other way. The envelope itself is still readable, as `data-context-keys`
   * on the form, and `[data-view-scope]` still resolves the disagreement.
   */
  await expect(page.locator("[data-context-mismatch]")).toContainText("Conversation scoped to bracket; next message includes the viewed other-part");
  expect(await page.locator("[data-composer]").getAttribute("data-context-keys")).toContain("part");
  await page.locator("[data-view-scope]").click();
  await expect(page.locator("[data-context-mismatch]")).toHaveCount(0);
  await expect(input(page)).toHaveValue("next session draft");
  await page.locator("[data-session-switch]").click();
  await page.locator(`[data-session-option="${SID}"]`).click();
  await expect(input(page)).toHaveValue("original draft — never replace");
  // `/context/preview` had no caller left once the disclosure went (2026-09-20),
  // so the filter that used to excuse it would now hide a real mutation.
  expect(c.mutations).toHaveLength(1);
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
