// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
import { expect, test } from '@playwright/test';
import { open, route } from './harness/world';
import type { ViewportHandle } from '../src/viewport/testHook';

test('Fit follows resized extents; deliberate orbit/zoom/pan and held artifact survive every capacity band', async ({ page }) => {
  const writes: string[] = [];
  await page.route('**/api/v1/**', async route => {
    if (route.request().method() !== 'GET') { writes.push(new URL(route.request().url()).pathname); await route.abort(); }
    else await route.continue();
  });
  await page.setViewportSize({ width: 1440, height: 800 }); await open(page, route('tread'));
  await expect(page.locator('[data-glb-state="ready"]')).toBeVisible();
  await page.getByRole('button', { name: 'Hold', exact: true }).click();
  await page.getByRole('button', { name: 'Fit', exact: true }).click();
  const snapshot = () => page.evaluate(() => {
    const handle = (window as unknown as { __hephaestus_viewport__: ViewportHandle }).__hephaestus_viewport__;
    return { pin: handle.artifact_ref, ...handle.camera()! };
  });
  await expect.poll(async () => (await snapshot()).fit).toBe(true);
  const initial = await snapshot();
  expect(initial.pin).not.toBeNull();
  for (const width of [1440, 1280, 1024, 843, 1024, 1440]) {
    await page.setViewportSize({ width, height: 800 });
    await expect.poll(async () => (await snapshot()).size[0]).toBe(width - (width < 1280 ? 0 : 280) - Math.round(Math.max(360, Math.min(420, width * 0.3))));
    const state = await snapshot();
    expect(state.fit).toBe(true); expect(state.eye).toEqual(initial.eye); expect(state.target).toEqual(initial.target); expect(state.up).toEqual(initial.up); expect(state.pin).toBe(initial.pin);
    if (width === 843) expect(state.scale).toBeGreaterThan(initial.scale);
  }
  const canvas = page.locator('[data-viewport-canvas]'); const box = (await canvas.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2); await page.mouse.wheel(0, -180);
  for (const button of ['right', 'left'] as const) {
    await page.mouse.down({ button }); await page.mouse.move(box.x + box.width / 2 + 25, box.y + box.height / 2 + 15, { steps: 5 }); await page.mouse.up({ button });
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  }
  const held = await snapshot(); expect(held.fit).toBe(false);
  const pose = ({ size: _size, ...rest }: typeof held) => rest;
  for (const width of [1280, 1024, 843, 1024, 1440]) {
    await page.setViewportSize({ width, height: 800 });
    await expect.poll(async () => (await snapshot()).size[0]).toBe(width - (width < 1280 ? 0 : 280) - Math.round(Math.max(360, Math.min(420, width * 0.3))));
    expect(pose(await snapshot())).toEqual(pose(held));
  }
  await page.getByRole('button', { name: 'Fit', exact: true }).click(); expect((await snapshot()).fit).toBe(true);
  expect(writes).toEqual([]);
});
