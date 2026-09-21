// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
// Browser case definitions for the local fixture only. No turns or session creation.

import { expect, test, type Page } from "@playwright/test";
import { open, route } from "./harness/world";

/**
 * C25 (2026-09-20): the Stream is always mounted, so there is nothing to
 * expand. What every call site actually needed was to wait for the column's
 * resize separator before measuring — that wait is all this keeps.
 */
async function ready(page: Page): Promise<void> {
  await expect(page.locator("[data-stream-resize]")).toBeVisible();
}

const WIDTHS = [843, 1000, 1024, 1279, 1440];

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
    await ready(page);
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
    // 2026-09-20, CORRECTED: this read `outlineStyle` on the separator, and the
    // separator now sets `outline: none` deliberately. The indicator was not
    // removed, it MOVED: the strip is an 8px hit area drawing a 1px hairline
    // through its middle as a `::before`, and on `:focus-visible` that hairline
    // takes the accent and doubles to 2px. An outline around the hit area would
    // have drawn an 8px-wide box around a 1px line. `getComputedStyle(el)` can
    // never see that, so the check has to name the pseudo-element.
    const seamFocus = await separator.evaluate((el) => {
      const before = getComputedStyle(el, "::before");
      return { width: before.width, background: before.backgroundColor, outline: getComputedStyle(el).outlineStyle };
    });
    expect(seamFocus.width, "the focused seam does not thicken").toBe("2px");
    expect(seamFocus.background, "the focused seam is not painted").not.toBe("rgba(0, 0, 0, 0)");
    expect(seamFocus.background).not.toBe("transparent");

    const seam = (await separator.boundingBox())!;
    await page.mouse.move(seam.x + seam.width / 2, seam.y + 100);
    await page.mouse.down();
    await page.mouse.move(seam.x - 20, seam.y + 140, { steps: 4 });
    await page.mouse.up();
    const chosen = await separator.getAttribute("aria-valuenow");
    expect(Number(chosen)).toBeGreaterThan(360);
    await assertBudget(page, width);
    // C25 (2026-09-20): the column has no collapsed state. The width it was
    // dragged to must survive a viewport clamp and its restoration instead —
    // the same preference the collapse/reopen round-trip used to prove.
    await page.setViewportSize({ width: 720, height: 800 });
    await page.setViewportSize({ width, height: 800 });
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
  await ready(page);
  await page.locator("[data-stream-resize]").press("End");
  const preferred = await page.locator("[data-stream-resize]").getAttribute("aria-valuenow");
  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: 900 });
    await expect(page.locator("[data-band]")).toHaveAttribute("data-band", width < 1024 ? "narrow" : width < 1280 ? "medium" : "wide");
    await ready(page);
    await assertBudget(page, width);
  }
  await expect(page.locator("[data-stream-resize]")).toHaveAttribute("aria-valuenow", preferred!);
});

test("selected title stays compact while switcher exposes the session tree", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, route("tread"));
  await ready(page);
  const strip = page.locator("[data-session-strip]");
  await expect(strip.locator("[data-session-tab]")).toHaveCount(1);
  await expect(page.locator("[data-session-option]")).toHaveCount(0);
  const height = (await strip.boundingBox())!.height;
  expect(height).toBeLessThanOrEqual(96); // title/scope plus readable action row
  const titleBox = (await strip.locator("[data-session-tab]").boundingBox())!;
  // 2026-09-20, CORRECTED: both are icon-only now, so each keeps its name on
  // `aria-label` rather than in a visible span. The claim that "the switcher
  // still carries its word" was written without checking the component: the
  // switcher merged into the session title tab, and its `aria-hidden` span is
  // the chevron, drawn with CSS `content` and so carrying no text.
  await expect(strip.locator("[data-session-switch]")).toHaveAccessibleName(/./);
  await expect(strip.locator("[data-session-switch]").locator('span[aria-hidden="true"]')).toHaveText("");
  await expect(strip.locator("[data-session-create-menu]")).toHaveAccessibleName(/./);
  await expect(strip.locator("[data-session-create-menu]")).toHaveText("");
  for (const selector of ["[data-session-switch]", "[data-session-create-menu]"]) {
    const action = strip.locator(selector);
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
