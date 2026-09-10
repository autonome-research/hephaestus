// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
import { expect, test, type Page } from "@playwright/test";
import { input, setup, SID } from "./fixture";

async function budget(page: Page, width: number) {
  const box = (await page.locator("#chat-column").boundingBox())!;
  expect(box.width).toBeGreaterThanOrEqual(360);
  expect(width - (width < 1280 ? 0 : 280) - box.width).toBeGreaterThanOrEqual(359);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBe(0);
  expect(await page.evaluate(() => document.body.scrollWidth - document.documentElement.clientWidth)).toBe(0);
  const field = (await input(page).boundingBox())!;
  expect(field.width).toBeGreaterThan(250);
  expect(field.x + field.width).toBeLessThanOrEqual(width);
}
for (const width of [843, 1000, 1024, 1279, 1440]) {
  test(`pointer and keyboard divider, compact header/composer, no overflow at ${width}px`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 900 });
    const c = await setup(page);
    const separator = page.locator("[data-stream-resize]");
    await expect(separator).toHaveAttribute("aria-orientation", "vertical");
    await budget(page, width);
    const header = page.locator("[data-session-strip]");
    const height = (await header.boundingBox())!.height;
    expect(height).toBeLessThanOrEqual(64);
    await expect(header.locator("[data-session-tab]")).toHaveCount(1);
    await page.locator("[data-session-switch]").press("Enter");
    await expect(page.locator("[data-session-option]")).toHaveCount(2);
    expect((await header.boundingBox())!.height).toBe(height);
    await page.keyboard.press("Escape");
    await expect(page.locator("[data-session-switch]")).toBeFocused();
    await separator.focus();
    await separator.press("End");
    await expect(separator).toHaveAttribute("aria-valuenow", (await separator.getAttribute("aria-valuemax"))!);
    await budget(page, width);
    await separator.press("Home");
    await expect(separator).toHaveAttribute("aria-valuenow", "360");
    await separator.press("ArrowLeft");
    await expect(separator).toHaveAttribute("aria-valuenow", "370");
    await separator.press("ArrowRight");
    await expect(separator).toHaveAttribute("aria-valuenow", "360");
    expect(await separator.evaluate(el => getComputedStyle(el).outlineStyle)).not.toBe("none");
    const seam = (await separator.boundingBox())!;
    await page.mouse.move(seam.x + seam.width / 2, seam.y + 100);
    await page.mouse.down();
    await page.mouse.move(seam.x - 35, seam.y + 130, { steps: 5 });
    await page.mouse.up();
    const chosen = (await separator.getAttribute("aria-valuenow"))!;
    expect(Number(chosen)).toBeGreaterThan(360);
    await input(page).fill("Synthetic editable draft\nSecond line");
    const composer = (await page.locator("[data-composer]").boundingBox())!;
    const panel = (await page.locator('[data-testid="stream-panel"]').boundingBox())!;
    expect(composer.height).toBeLessThanOrEqual(panel.height * 0.55);
    for (const selector of ["[data-model-button]", "[data-context-summary]", "[data-composer-input-row]", "[data-composer-hint]"]) {
      const box = (await page.locator(selector).boundingBox())!;
      expect(box.y).toBeGreaterThanOrEqual(composer.y);
      expect(box.y + box.height).toBeLessThanOrEqual(composer.y + composer.height);
    }
    await page.locator("[data-stream-collapse]").click();
    const hidden = (await page.locator('[data-stream-strip]').boundingBox())!;
    expect(hidden.width).toBeGreaterThan(hidden.height * 3);
    await page.locator("[data-stream-strip]").press('Enter');
    await expect(separator).toHaveAttribute("aria-valuenow", chosen);
    await expect(input(page)).toHaveValue("Synthetic editable draft\nSecond line");
    if (width < 1280) {
      await page.locator("[data-rail-toggle]").click();
      await expect(page.locator("[data-rail-scrim]")).toBeVisible();
      await page.locator("[data-rail-close]").click();
    }
    await budget(page, width);
    await page.screenshot({ path: info.outputPath(`chat-${width}.png`) });
    expect(c.mutations).toEqual([]);
    expect(c.faults).toEqual([]);
  });
}

for (const width of [843, 1440]) {
  test(`session switcher keeps keyboard navigation open and dismisses on activation at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const c = await setup(page);
    const switcher = page.locator("[data-session-switch]");
    const menu = page.locator("[data-session-switch-open]");
    const options = page.locator("[data-session-option]");
    await switcher.press("Enter");
    const ids = await options.evaluateAll(elements => elements.map(el => el.getAttribute("data-session-option")!));
    expect(ids).toHaveLength(2);
    const option = (id: string) => page.locator(`[data-session-option="${id}"]`);
    await expect(option(SID)).toBeFocused();
    await page.keyboard.press("ArrowRight");
    const next = ids[(ids.indexOf(SID) + 1) % ids.length]!;
    await expect(menu).toBeVisible();
    await expect(option(next)).toBeFocused();
    await expect(option(next)).toHaveAttribute("aria-selected", "true");
    await page.keyboard.press("Home");
    await expect(option(ids[0]!)).toBeFocused();
    await page.keyboard.press("End");
    await expect(option(ids.at(-1)!)).toBeFocused();
    await expect(menu).toBeVisible();
    await page.keyboard.press("Enter");
    await expect(menu).toHaveCount(0);
    await expect(switcher).toBeFocused();
    await expect(page.locator("[data-session-tab]")).toHaveAttribute("data-session-tab", ids.at(-1)!);
    await switcher.press("Enter");
    await page.keyboard.press("Home");
    await page.keyboard.press("Space");
    await expect(menu).toHaveCount(0);
    await expect(switcher).toBeFocused();
    await switcher.press("Enter");
    await page.keyboard.press("Tab");
    expect(await options.evaluateAll(elements => elements.some(element => element === document.activeElement))).toBe(false);
    await page.keyboard.press("Escape");
    await expect(menu).toHaveCount(0);
    await expect(switcher).toBeFocused();
    await switcher.click();
    await option(ids.at(-1)!).click();
    await expect(menu).toHaveCount(0);
    await expect(switcher).toBeFocused();
    expect(c.mutations).toEqual([]);
    expect(c.faults).toEqual([]);
  });
}

test("explicit width survives viewport clamping", async ({ page }) => {
  const c = await setup(page);
  const separator = page.locator("[data-stream-resize]");
  await separator.press("End");
  const preferred = (await separator.getAttribute("aria-valuenow"))!;
  for (const width of [843, 1000, 1024, 1279, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(page.locator("[data-band]")).toHaveAttribute("data-band", width < 1024 ? "narrow" : width < 1280 ? "medium" : "wide");
    await expect(page.locator('[data-stream-strip]')).toHaveCount(0);
    await expect(separator).toBeVisible();
    await budget(page, width);
  }
  await expect(separator).toHaveAttribute("aria-valuenow", preferred);
  expect(c.mutations).toEqual([]);
  expect(c.faults).toEqual([]);
});
