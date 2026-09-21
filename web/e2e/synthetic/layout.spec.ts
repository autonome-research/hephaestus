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
    // ONE ROW (2026-09-20, corrected twice). This block was written for a
    // two-line strip — title and scope above, readable word-buttons below —
    // and then patched to keep that shape. The strip is a single flex row now:
    // create, then the session title, then close. Both corrections below are
    // of assertions this file made about a header that no longer exists.
    expect(height).toBeLessThanOrEqual(96);
    const title = (await header.locator("[data-session-tab]").boundingBox())!;

    // (1) The switcher does not print the word "Switch" in a decorative span.
    // It merged INTO the title tab, so `[data-session-switch]` and
    // `[data-session-tab]` are one element, and its `aria-hidden` span is the
    // chevron — drawn with CSS `content`, so it carries no text at all. The
    // word was never the contract; a control with no visible label keeping an
    // accessible name is.
    await expect(header.locator("[data-session-switch]")).toHaveAccessibleName(/./);
    await expect(header.locator("[data-session-switch]").locator('span[aria-hidden="true"]')).toHaveText("");
    await expect(header.locator("[data-session-create-menu]")).toHaveAccessibleName(/./);
    await expect(header.locator("[data-session-create-menu]")).toHaveText("");
    const switcher = (await header.locator("[data-session-switch]").boundingBox())!;
    expect(switcher, "the switcher is the title tab, not a control beneath it").toEqual(title);

    // (2) The create is not on a second line below the title — it LEADS the
    // row, with close at the far end, which is the arrangement the strip was
    // rebuilt for. So the contract is that the three share one row and none of
    // them overflows the strip, not that any of them sits under the title.
    const create = (await header.locator("[data-session-create-menu]").boundingBox())!;
    const strip = (await header.boundingBox())!;
    expect(create.x + create.width).toBeLessThanOrEqual(title.x + 1);
    for (const [box, name] of [[switcher, "switcher"], [create, "create"]] as const) {
      expect(box.y, name).toBeGreaterThanOrEqual(strip.y - 1);
      expect(box.y + box.height, name).toBeLessThanOrEqual(strip.y + height + 1);
      expect(box.height, name).toBeGreaterThanOrEqual(24);
    }
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
    await page.mouse.move(seam.x - 35, seam.y + 130, { steps: 5 });
    await page.mouse.up();
    const chosen = (await separator.getAttribute("aria-valuenow"))!;
    expect(Number(chosen)).toBeGreaterThan(360);
    await input(page).fill("Synthetic editable draft\nSecond line");
    const composer = (await page.locator("[data-composer]").boundingBox())!;
    const panel = (await page.locator('[data-testid="stream-panel"]').boundingBox())!;
    expect(composer.height).toBeLessThanOrEqual(panel.height * 0.55);
    // `[data-context-summary]` is struck (2026-09-20) — the composer no longer
    // narrates the envelope it sends. Its slot on this row is held by
    // `[data-composer-shell-bar]`, the message box's own settings row, so the
    // clause still counts every row of composer chrome and not one fewer.
    for (const selector of ["[data-model-button]", "[data-composer-shell-bar]", "[data-composer-input-row]", "[data-composer-hint]"]) {
      const box = (await page.locator(selector).boundingBox())!;
      expect(box.y).toBeGreaterThanOrEqual(composer.y);
      expect(box.y + box.height).toBeLessThanOrEqual(composer.y + composer.height);
    }
    // C25 (2026-09-20): no collapsed state. The width and the draft must
    // survive a viewport clamp and its restoration instead.
    await page.setViewportSize({ width: 720, height: 900 });
    await page.setViewportSize({ width, height: 900 });
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
    // The Stream is a peer column in every band; nothing docks it (C25).
    await expect(page.locator('#chat-column [data-testid="stream-panel"]')).toBeVisible();
    await expect(separator).toBeVisible();
    await budget(page, width);
  }
  await expect(separator).toHaveAttribute("aria-valuenow", preferred);
  expect(c.mutations).toEqual([]);
  expect(c.faults).toEqual([]);
});
