// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
import { expect, test, type Page } from "@playwright/test";
import { execution, input, RUN, setup, SID, send, status, stop } from "./fixture";
const widths = [1440, 1280, 1024, 843, 1024, 1440];
async function resize(page: Page, width: number) {
  await page.setViewportSize({ width, height: 800 });
  await expect(page.locator('[data-band]')).toHaveAttribute('data-band', width >= 1280 ? 'wide' : width >= 1024 ? 'medium' : 'narrow');
  await expect.poll(() => page.evaluate(() => document.body.scrollWidth <= document.body.clientWidth)).toBe(true);
}
async function reachable(page: Page, selector: string) {
  const box = await page.locator(selector).boundingBox();
  expect(box).not.toBeNull();
  expect(box!.x).toBeGreaterThanOrEqual(0); expect(box!.y).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(page.viewportSize()!.width);
  expect(box!.y + box!.height).toBeLessThanOrEqual(800);
  expect(await page.locator(selector).evaluate(el => {
    const r = el.getBoundingClientRect();
    return el.contains(document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2));
  })).toBe(true);
}

test('active question, attempt, next draft and historical disclosure survive full capacity/intent transitions', async ({ page }) => {
  const c = await setup(page);
  c.events[0]!.payload.text = 'Historical reading material.\n\n'.repeat(80);
  await page.reload();
  await expect(page.locator('[data-history-state]')).toHaveAttribute('data-history-state', 'complete');
  const tool = page.locator('[data-tool-call-id="recorded-call"] details');
  await tool.locator('summary').click();
  await input(page).fill('Submitted attempt stays immutable'); await send(page).click();
  c.execution = execution(RUN);
  const question = { question_id: 'resize-question', question: 'Which stock?', options: ['Keep 5.5 mm', 'Use 6 mm stock'], allow_free_text: false };
  await c.frame('question', question, 0);
  await expect(status(page)).toHaveAttribute('data-current-turn', 'Waiting for your answer');
  await input(page).fill('Editable next draft, never queued');
  const model = await page.locator('[data-model-button]').textContent();
  const hash = await page.evaluate(() => location.hash);
  const scroll = page.locator('[data-transcript-scroll]');
  await tool.scrollIntoViewIfNeeded();
  await scroll.evaluate(el => { el.scrollTop -= 100; });
  await expect(page.locator('[data-jump-latest]')).toBeVisible();
  const anchor = await scroll.evaluate(el => {
    const r = [...el.querySelectorAll<HTMLElement>('[data-row-key]')].find(row => row.getBoundingClientRect().bottom > el.getBoundingClientRect().top)!;
    return { key: r.dataset['rowKey'], offset: r.getBoundingClientRect().top - el.getBoundingClientRect().top };
  });
  for (const width of widths) {
    await resize(page, width);
    await expect(input(page)).toHaveValue('Editable next draft, never queued');
    await expect(status(page)).toHaveAttribute('data-current-turn', 'Waiting for your answer');
    expect(await page.locator('[data-model-button]').textContent()).toBe(model);
    expect(await page.evaluate(() => location.hash)).toBe(hash);
    await expect(tool).toHaveAttribute('open', '');
    await expect.poll(() => scroll.evaluate((el, anchor) => {
      const row = [...el.querySelectorAll<HTMLElement>('[data-row-key]')].find(r => r.dataset['rowKey'] === anchor.key)!;
      return Math.abs(row.getBoundingClientRect().top - el.getBoundingClientRect().top - anchor.offset);
    }, anchor)).toBeLessThanOrEqual(1);
    await reachable(page, '[data-composer-cancel]');
    await reachable(page, '[data-current-turn] button');
  }
  await page.locator('[data-stream-collapse]').click();
  const back = page.locator('[data-stream-strip]');
  await expect(back).toBeFocused();
  for (const width of widths) {
    await resize(page, width);
    await expect(back).toContainText('Answer needed');
    await expect(back).toHaveAttribute('data-return-session', SID);
    await expect(back).toBeFocused();
    await expect(input(page)).toHaveCount(0);
    await reachable(page, '[data-stream-strip]');
    const box = await back.boundingBox(); expect(box!.width).toBeGreaterThan(box!.height * 3);
  }
  await resize(page, 843); await back.press('Enter');
  await expect(page.locator('[data-question-id="resize-question"]')).toBeFocused();
  await expect(page.locator('[data-ask-option="Use 6 mm stock"]')).not.toHaveAttribute('aria-disabled', 'true');
  await expect(input(page)).toHaveValue('Editable next draft, never queued');
  await expect(tool).toHaveAttribute('open', '');
  // Both separators remain keyboard-operable in the supported narrow layout.
  const seam = page.locator('[data-stream-resize]');
  await seam.press('Home'); const min = await seam.getAttribute('aria-valuenow');
  await seam.press('ArrowLeft'); expect(Number(await seam.getAttribute('aria-valuenow'))).toBe(Number(min) + 10);
  const drawer = page.getByRole('separator', { name: /inspector/i });
  const drawerY = (await drawer.boundingBox())!.y;
  await drawer.press('ArrowUp');
  await expect.poll(async () => (await drawer.boundingBox())!.y).toBeLessThan(drawerY);
  await stop(page).focus(); await expect(stop(page)).toBeFocused(); // focus is not Stop
  expect(c.mutations.map(m => m.path)).toEqual([`/sessions/${SID}/prompt`]); expect(c.faults).toEqual([]);
});

test('Parts contains keyboard focus, dismisses with return, and never replaces conversation', async ({ page }) => {
  const c = await setup(page); await resize(page, 1024);
  await input(page).fill('Draft while Parts is open');
  const hash = await page.evaluate(() => location.hash);
  for (const dismissal of ['Escape', 'scrim', 'Close']) {
    await page.locator('[data-rail-toggle]').click();
    const rail = page.locator('#parts-navigation'); const close = page.locator('[data-rail-close]');
    await expect(close).toBeFocused();
    await page.keyboard.press('Shift+Tab');
    expect(await rail.evaluate(el => el.contains(document.activeElement))).toBe(true);
    await page.keyboard.press('Tab'); await expect(close).toBeFocused();
    await resize(page, 843); await expect(page.locator('[data-rail-scrim]')).toBeVisible();
    if (dismissal === 'Escape') await page.keyboard.press('Escape');
    else if (dismissal === 'scrim') await page.locator('[data-rail-scrim]').click({ position: { x: 700, y: 100 } });
    else await close.click();
    await expect(page.locator('[data-rail-toggle]')).toBeFocused();
    await expect(rail).toBeHidden();
    await expect(input(page)).toHaveValue('Draft while Parts is open');
    expect(await page.evaluate(() => location.hash)).toBe(hash);
  }
  await page.locator('[data-rail-toggle]').click();
  await page.locator('[data-part="panel"]').first().click();
  await page.keyboard.press('Escape');
  await expect(page.locator('[data-composer]')).toHaveAttribute('data-session-id', SID);
  await expect(input(page)).toHaveValue('Draft while Parts is open');
  // A reveal made around an asynchronous resize must not be overridden later.
  await page.locator('[data-stream-collapse]').click();
  await page.setViewportSize({ width: 1440, height: 800 });
  await page.locator('[data-skip="composer"]').focus(); await page.keyboard.press('Enter');
  await expect(input(page)).toBeFocused(); await resize(page, 843); await expect(input(page)).toBeVisible();
  expect(c.mutations).toEqual([]); expect(c.faults).toEqual([]);
});

for (const state of ['Working', 'Request failed', 'Checking'] as const) test(`hidden return updates from authority: ${state}, without writes or focus theft`, async ({ page }) => {
  const c = await setup(page, execution(RUN));
  await page.locator('[data-stream-collapse]').click(); const back = page.locator('[data-stream-strip]');
  if (state === 'Request failed') { c.execution = execution(RUN, 'failed'); await c.frame('terminal', { state: 'failed', error: 'Fixture refused the request' }, 0); }
  if (state === 'Checking') { c.sessionsFail = true; await page.evaluate(() => window.dispatchEvent(new Event('focus'))); }
  await expect(back.locator('[data-return-state]')).toHaveText(state);
  await expect(back).toBeFocused(); expect(c.mutations).toEqual([]); expect(c.faults).toEqual([]);
});
