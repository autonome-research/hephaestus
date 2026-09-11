// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
import { expect, test, type Locator, type Page } from "@playwright/test";
import { setup, SID, OTHER, RUN, execution, input, send } from "./fixture";

for (const width of [1440, 1280, 1024, 843]) test(`refinement: expanded details preserve readable composition and no-write controls at ${width}`, async ({ page }) => {
  await page.setViewportSize({ width, height: width === 1440 ? 1000 : 800 });
  const c = await setup(page);
  const draft = Array.from({ length: 8 }, (_, n) => `Line ${n + 1}: inspect the evidence; do not change the design.`).join("\n");
  await input(page).fill(draft);
  await page.locator("[data-context-disclose]").click();
  await page.getByText("Full model identity", { exact: true }).click();
  const details = page.getByRole("region", { name: "Message details" });
  const checkCore = async () => {
    const form = (await page.locator("[data-composer]").boundingBox())!;
    for (const selector of ["[data-model-button]", "[data-context-summary]", "[data-composer-input-row]", "[data-composer-send]", "[data-composer-hint]"]) {
      await bounded(page.locator(selector), width, width === 1440 ? 1000 : 800);
      const box = (await page.locator(selector).boundingBox())!;
      expect(box.y).toBeGreaterThanOrEqual(form.y);
      expect(box.y + box.height).toBeLessThanOrEqual(form.y + form.height + 1);
    }
    expect((await input(page).boundingBox())!.height).toBeGreaterThan(65);
    expect((await page.locator("[data-transcript-scroll]").boundingBox())!.height).toBeGreaterThan(120);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  };
  await checkCore();
  await details.focus();
  await page.keyboard.press("End");
  await checkCore();
  await expect(page.locator("[data-context-block]")).toBeVisible();
  // A model/execution read is uncertain until reconciled, not an excuse to send.
  c.execution = execution(RUN);
  await c.frame("text_delta", { text: "Working on the explicit fixture task." }, 0);
  await expect(send(page)).toBeDisabled();
  await checkCore();
  await input(page).press("Enter");
  await send(page).focus();
  await page.keyboard.press("Enter");
  await expect(input(page)).toHaveValue(draft);
  await expect(page.locator("[data-composer-cancel]")).toBeVisible();
  await page.locator("[data-stream-collapse]").click();
  await page.locator("[data-stream-strip]").click();
  await expect(input(page)).toHaveValue(draft);
  await expect(page.locator("[data-context-summary]")).toContainText("Next message includes");
  expect(c.mutations.filter(r => r.path !== "/context/preview")).toEqual([]);
  expect(c.faults).toEqual([]);
});

async function switchTo(page: Page, sid: string) {
  await page.locator("[data-session-switch]").click();
  await page.locator(`[data-session-option="${sid}"]`).click();
  await expect(page.locator("[data-composer]")).toHaveAttribute("data-session-id", sid);
}
async function bounded(target: Locator, width: number, height: number) {
  const box = await target.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.y).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(width);
  expect(box!.y + box!.height).toBeLessThanOrEqual(height);
  // A bounded wrapper is not sufficient if its text is still clipped inside it.
  expect(await target.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
}

for (const width of [1440, 1024, 843]) test(`audit: complete scope choices and focus remain onscreen at ${width}`, async ({ page }) => {
  await page.setViewportSize({ width, height: 800 });
  const c = await setup(page);
  await input(page).fill("Cancel must retain this draft");
  const route = new URL(page.url()).hash;
  for (const scope of ["Project", "bracket"]) {
    await page.getByRole("button", { name: "New conversation", exact: true }).click();
    const menu = page.locator("[data-session-create-open]");
    await bounded(menu, width, 800);
    const project = menu.getByRole("button", { name: "New conversation", exact: true });
    const part = menu.getByRole("button", { name: "Ask about bracket", exact: true });
    await bounded(project, width, 800);
    await bounded(part, width, 800);
    await expect(project).toBeFocused();
    if (scope === "bracket") {
      await page.keyboard.press("Tab");
      await expect(part).toBeFocused();
      await page.keyboard.press("Enter");
    } else await project.click();
    const dialog = page.getByRole("dialog", { name: `New conversation · ${scope}`, exact: true });
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
    await expect(page.locator("[data-session-create-menu]")).toBeFocused();
    await expect(input(page)).toHaveValue("Cancel must retain this draft");
    expect(new URL(page.url()).hash).toBe(route);
  }
  const longPart = "long-part-name-".repeat(24);
  await page.evaluate(({ sid, part }) => { location.hash = `#/p/${part}?s=${sid}`; }, { sid: SID, part: longPart });
  await page.locator("[data-session-create-menu]").click();
  await bounded(page.locator("[data-session-create-open]"), width, 800);
  const longChoice = page.getByRole("button", { name: `Ask about ${longPart}`, exact: true });
  await bounded(longChoice, width, 800);
  await page.keyboard.press("Tab");
  await expect(longChoice).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.locator("[data-session-create-menu]")).toBeFocused();
  expect(c.mutations).toEqual([]);
  expect(c.faults).toEqual([]);
});

for (const width of [1440, 843]) test(`audit: session-owned exclusions survive Hide/Open and keyboard reveal before one explicit send at ${width}`, async ({ page }) => {
  await page.setViewportSize({ width, height: 800 });
  const c = await setup(page);
  await expect(page.locator("[data-model-button]")).toContainText("Current model");
  await input(page).fill("Retain session A draft");
  const model = await page.locator("[data-model-button]").textContent();
  const route = new URL(page.url()).hash;
  await page.locator("[data-context-disclose]").click();
  for (const key of ["view", "part"]) await page.locator(`[data-context-drop="${key}"]`).click();
  await page.locator("[data-context-disclose]").click();
  const keys = await page.locator("[data-context-summary]").getAttribute("data-context-keys");
  for (const reveal of ["open", "skip"]) {
    await page.locator("[data-stream-collapse]").click();
    if (reveal === "open") await page.locator("[data-stream-strip]").click();
    else {
      // Tab to the actual skip link, not a route edit or a programmatic reveal.
      for (let n = 0; n < 30; n++) {
        await page.keyboard.press("Tab");
        if (await page.getByRole("link", { name: "Skip to composer" }).evaluate(el => el === document.activeElement)) break;
      }
      await expect(page.getByRole("link", { name: "Skip to composer" })).toBeFocused();
      await page.keyboard.press("Enter");
    }
    await expect(input(page)).toBeFocused();
    await expect(input(page)).toHaveValue("Retain session A draft");
    await expect(page.locator("[data-context-summary]")).toHaveAttribute("data-context-keys", keys!);
    await expect(page.locator('[data-context-removed="view"]')).toBeVisible();
    await expect(page.locator('[data-context-removed="part"]')).toBeVisible();
    await expect(page.locator("[data-model-button]")).toHaveText(model!);
    expect(new URL(page.url()).hash).toBe(route);
  }
  await switchTo(page, OTHER);
  await expect(page.locator("[data-context-removed]")).toHaveCount(0);
  await input(page).fill("Independent session B draft");
  await page.locator("[data-context-disclose]").click();
  await page.locator('[data-context-drop="stage_tab"]').click();
  await page.locator("[data-context-disclose]").click();
  await switchTo(page, SID);
  await expect(page.locator("[data-context-summary]")).toHaveAttribute("data-context-keys", keys!);
  await expect(input(page)).toHaveValue("Retain session A draft");
  expect(c.mutations.filter(r => r.path !== "/context/preview")).toEqual([]);

  await expect(send(page)).toBeEnabled();
  await send(page).click();
  await expect.poll(() => c.pending !== null).toBe(true);
  const writes = c.mutations.filter(r => r.path !== "/context/preview");
  expect(writes).toHaveLength(1);
  expect(writes[0]!.path).toBe(`/sessions/${SID}/prompt`);
  expect(writes[0]!.body).toEqual({ text: "Retain session A draft", context: null, expected_model_revision: c.model.revision });
  await input(page).fill("Newer unsent draft");
  await page.locator("[data-context-disclose]").click();
  await page.locator('[data-context-drop="view"]').click();
  await page.locator("[data-context-disclose]").click();
  await switchTo(page, OTHER);
  await expect(page.locator('[data-context-removed="stage_tab"]')).toBeVisible();
  await expect(page.locator('[data-context-removed="view"]')).toHaveCount(0);
  await expect(input(page)).toHaveValue("Independent session B draft");
  // Later context edits and switching cannot rewrite the already submitted body.
  expect(c.pending!.request().postDataJSON()).toEqual(writes[0]!.body);
  await c.release();
  await switchTo(page, SID);
  await expect(input(page)).toHaveValue("Newer unsent draft");
  expect(c.mutations.filter(r => r.path !== "/context/preview")).toEqual(writes);
  expect(c.faults).toEqual([]);
});

test("audit: explicit added view survives no-session remount and first-send creation without leaking to another session", async ({ page }) => {
  const c = await setup(page);
  await page.route("**/api/v1/sessions", route => route.request().method() === "GET" && c.created === null
    ? route.fulfill({ json: { status: "ok", sessions: [], profiles: [] } }) : route.fallback());
  await page.goto("about:blank");
  await page.goto("/#/p/bracket");
  await expect(page.locator("[data-composer]")).toHaveAttribute("data-session-id", "");
  await input(page).fill("Explicit view-only first request");
  await page.locator("[data-context-disclose]").click();
  await page.locator('[data-context-drop="part"]').click();
  await page.locator('[data-context-drop="view"]').click();
  await page.locator("[data-context-add-view]").click();
  await page.locator("[data-context-disclose]").click();
  const keys = "stage_tab inspector_tab view";
  await expect(page.locator("[data-context-summary]")).toHaveAttribute("data-context-keys", keys);
  await page.locator("[data-stream-collapse]").click();
  await page.locator("[data-stream-strip]").click();
  await expect(page.locator("[data-context-summary]")).toHaveAttribute("data-context-keys", keys);
  expect(c.mutations.filter(r => r.path !== "/context/preview")).toEqual([]);
  await expect(send(page)).toBeEnabled();
  await send(page).click();
  await expect.poll(() => c.pending !== null).toBe(true);
  await expect(page.locator("[data-composer]")).toHaveAttribute("data-session-id", "synthetic-created");
  await expect(page.locator("[data-context-summary]")).toHaveAttribute("data-context-keys", keys);
  expect(c.mutations.filter(r => r.path !== "/context/preview").map(r => r.path)).toEqual(["/sessions", "/sessions/synthetic-created/prompt"]);
  expect(c.pending!.request().postDataJSON()).toEqual({ text: "Explicit view-only first request", context: { stage_tab: "viewport", inspector_tab: "results", view: "iso" }, expected_model_revision: c.created!.model_state.revision });
  await c.release();
  await switchTo(page, SID);
  await expect(page.locator("[data-context-removed]")).toHaveCount(0);
  await expect(page.locator("[data-context-summary]")).toHaveAttribute("data-context-keys", "part stage_tab inspector_tab view");
  expect(c.faults).toEqual([]);
});
