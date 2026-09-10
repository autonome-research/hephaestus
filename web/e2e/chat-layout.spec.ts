// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
// Browser case definitions for the local fixture only. No turns or session creation.

import { expect, test, type Page } from "@playwright/test";
import { open, route } from "./harness/world";

const WIDTHS = [843, 1000, 1024, 1279, 1440];

async function expand(page: Page): Promise<void> {
  const strip = page.locator("[data-stream-strip]");
  if (await strip.isVisible()) await strip.click();
  await expect(page.locator("[data-stream-resize]")).toBeVisible();
}

async function assertBudget(page: Page, width: number): Promise<void> {
  const box = await page.locator("#chat-column").boundingBox();
  expect(box).not.toBeNull();
  expect(box!.width).toBeGreaterThanOrEqual(360);
  expect(width - (width < 1280 ? 0 : 280) - box!.width).toBeGreaterThanOrEqual(359);
  const dimensions = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    client: document.documentElement.clientWidth,
    body: document.body.scrollWidth,
  }));
  expect(dimensions.scroll).toBe(dimensions.client);
  expect(dimensions.body).toBe(dimensions.client);
  const composer = page.locator("[data-composer-input]");
  await expect(composer).toBeVisible();
  const input = await composer.boundingBox();
  expect(input!.width).toBeGreaterThan(250);
  expect(input!.x).toBeGreaterThanOrEqual(box!.x);
  expect(input!.x + input!.width).toBeLessThanOrEqual(width);
}

for (const width of WIDTHS) {
  test(`chat resize, keyboard, collapse/reopen and independent rail at ${String(width)}px`, async ({ page }) => {
    // Fail closed if any UI action unexpectedly attempts a mutation.
    const mutations: string[] = [];
    await page.route("**/api/v1/**", async (request) => {
      if (!["GET", "HEAD", "OPTIONS"].includes(request.request().method())) {
        mutations.push(request.request().url());
        await request.abort();
      } else await request.continue();
    });
    await page.setViewportSize({ width, height: 900 });
    await open(page, route("tread"));
    await expand(page);
    const separator = page.locator("[data-stream-resize]");
    await expect(separator).toHaveAttribute("aria-orientation", "vertical");
    await assertBudget(page, width);
    await separator.focus();
    await separator.press("End");
    await expect(separator).toHaveAttribute("aria-valuenow", (await separator.getAttribute("aria-valuemax"))!);
    await assertBudget(page, width);
    await separator.press("Home");
    await expect(separator).toHaveAttribute("aria-valuenow", "360");
    await separator.press("ArrowLeft");
    await expect(separator).toHaveAttribute("aria-valuenow", "370");
    await separator.press("ArrowRight");
    await expect(separator).toHaveAttribute("aria-valuenow", "360");
    await expect(separator).toBeFocused();
    expect(await separator.evaluate((el) => getComputedStyle(el).outlineStyle)).not.toBe("none");

    const seam = (await separator.boundingBox())!;
    await page.mouse.move(seam.x + seam.width / 2, seam.y + 100);
    await page.mouse.down();
    await page.mouse.move(seam.x - 20, seam.y + 140, { steps: 4 });
    await page.mouse.up();
    const chosen = await separator.getAttribute("aria-valuenow");
    expect(Number(chosen)).toBeGreaterThan(360);
    await assertBudget(page, width);
    await page.locator("[data-stream-collapse]").click();
    await expect(separator).toHaveCount(0);
    const hidden = (await page.locator('[data-stream-strip]').boundingBox())!;
    expect(hidden.width).toBeGreaterThan(hidden.height * 3);
    await expand(page);
    await expect(separator).toHaveAttribute("aria-valuenow", chosen!);

    if (width < 1280) {
      await page.locator("[data-rail-toggle]").click();
      await expect(page.locator("[data-rail-scrim]")).toBeVisible();
      await expect(separator).toHaveCount(0); // covered separators cannot take focus
      await page.locator("[data-rail-close]").click();
      await expect(separator).toHaveAttribute("aria-valuenow", chosen!);
      await assertBudget(page, width);
    }
    expect(mutations).toEqual([]);
  });
}

test("explicit chat width survives temporary viewport clamps and band changes", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, route("tread"));
  await expand(page);
  await page.locator("[data-stream-resize]").press("End");
  const preferred = await page.locator("[data-stream-resize]").getAttribute("aria-valuenow");
  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: 900 });
    await expect(page.locator("[data-band]")).toHaveAttribute("data-band", width < 1024 ? "narrow" : width < 1280 ? "medium" : "wide");
    await expand(page);
    await assertBudget(page, width);
  }
  await expect(page.locator("[data-stream-resize]")).toHaveAttribute("aria-valuenow", preferred!);
});

test("selected title stays compact while switcher exposes the session tree", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, route("tread"));
  await expand(page);
  const strip = page.locator("[data-session-strip]");
  await expect(strip.locator("[data-session-tab]")).toHaveCount(1);
  await expect(page.locator("[data-session-option]")).toHaveCount(0);
  const height = (await strip.boundingBox())!.height;
  expect(height).toBeLessThanOrEqual(96); // title/scope plus readable action row
  const titleBox = (await strip.locator("[data-session-tab]").boundingBox())!;
  for (const [selector, label] of [["[data-session-switch]", "Switch"], ["[data-session-create-menu]", "New"], ["[data-stream-collapse]", "Hide"]]) {
    const action = strip.locator(selector!);
    await expect(action.locator('span[aria-hidden="true"]')).toHaveText(label!);
    expect((await action.boundingBox())!.y).toBeGreaterThanOrEqual(titleBox.y + titleBox.height);
  }
  await page.locator("[data-session-switch]").focus();
  await page.locator("[data-session-switch]").press("Enter");
  await expect(page.locator("[data-session-switch-open]")).toBeVisible();
  expect(await page.locator("[data-session-option]").count()).toBeGreaterThan(0);
  expect((await strip.boundingBox())!.height).toBe(height);
  await page.keyboard.press("Escape");
  await expect(page.locator("[data-session-switch]")).toBeFocused();
});
