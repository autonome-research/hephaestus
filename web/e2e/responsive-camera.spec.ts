// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
import { expect, test, type Page } from '@playwright/test';
import { open, route } from './harness/world';
import type { ViewportHandle } from '../src/viewport/testHook';

/*
 * The stage is the viewport less the tracks beside it (2026-09-20).
 *
 * The Views bar leads the shell and keeps its place in the template at every
 * band — removing a grid item shifts auto-placement for everything after it —
 * but its WIDTH is 44px only while the Parts panel is shut. Open, as a column
 * or as an overlay, the same hamburger sits in the panel's own corner and the
 * strip would be an empty track, so it goes to zero. `data-rail` is where the
 * shell says which of the four it is in, so the expectation reads it rather
 * than assuming one.
 */
const VIEWS_WIDTH = 44;
async function stageWidthFor(page: Page, width: number): Promise<number> {
  const rail = await page.locator('[data-band]').getAttribute('data-rail');
  const views = rail === 'closed' || rail === 'hidden' ? VIEWS_WIDTH : 0;
  const parts = width < 1280 ? 0 : 280;
  const stream = Math.round(Math.max(360, Math.min(420, width * 0.3)));
  return width - views - parts - stream;
}

test('Fit follows resized extents; deliberate orbit/zoom/pan and held artifact survive every capacity band', async ({ page }) => {
  const writes: string[] = [];
  await page.route('**/api/v1/**', async route => {
    if (route.request().method() !== 'GET') { writes.push(new URL(route.request().url()).pathname); await route.abort(); }
    else await route.continue();
  });
  await page.setViewportSize({ width: 1440, height: 800 }); await open(page, route('tread'));
  await expect(page.locator('[data-glb-state="ready"]')).toBeVisible();
  await page.getByRole('button', { name: 'Hold', exact: true }).click();
  // FIT IS THE CUBE'S NOW (2026-09-20). The appearance cluster's Fit button is
  // struck; clicking the cell whose camera the workspace is already on re-frames
  // that view, which is the same action on the control it belongs to. A fresh
  // load is already framed, so the first press is the polled `fit` below.
  const snapshot = () => page.evaluate(() => {
    const handle = (window as unknown as { __hephaestus_viewport__: ViewportHandle }).__hephaestus_viewport__;
    return { pin: handle.artifact_ref, ...handle.camera()! };
  });
  await expect.poll(async () => (await snapshot()).fit).toBe(true);
  const initial = await snapshot();
  expect(initial.pin).not.toBeNull();
  for (const width of [1440, 1280, 1024, 843, 1024, 1440]) {
    await page.setViewportSize({ width, height: 800 });
    await expect.poll(async () => (await snapshot()).size[0]).toBe(await stageWidthFor(page, width));
    const state = await snapshot();
    /*
     * A FIXED LENS FITS BY MOVING (2026-09-20). This asserted the EYE was
     * identical across every band, which was true while the default projection
     * was orthographic: an ortho camera fits by changing its extents and never
     * its position. Under perspective the lens is fixed and the fit is a
     * standoff, so a narrower canvas steps the camera back — measured here at
     * 363.52 to 387.03 per axis. Requiring the eye to hold still is requiring
     * the fov to change, which is what magnified the near half of the model off
     * the canvas (`viewport/scene.ts::applyPerspectiveFraming`).
     *
     * What the clause is for is unchanged and is asserted as such: a resize
     * re-fits without becoming a NAVIGATION. The view direction, the target,
     * the up and the held artifact are the framing's at every band, and the
     * camera is still reported as fitted.
     */
    expect(state.fit).toBe(true); expect(state.target).toEqual(initial.target); expect(state.up).toEqual(initial.up); expect(state.pin).toBe(initial.pin);
    const ray = (eye: readonly number[], target: readonly number[]): number[] => {
      const away = eye.map((value, axis) => value - (target[axis] ?? 0));
      const length = Math.hypot(...away) || 1;
      return away.map(value => Number((value / length).toFixed(9)));
    };
    expect(ray(state.eye, state.target)).toEqual(ray(initial.eye, initial.target));
    if (width === 843) expect(state.scale).toBeGreaterThan(initial.scale);
  }
  const canvas = page.locator('[data-viewport-canvas]'); const box = (await canvas.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2); await page.mouse.wheel(0, -180);
  for (const button of ['right', 'left'] as const) {
    await page.mouse.down({ button }); await page.mouse.move(box.x + box.width / 2 + 25, box.y + box.height / 2 + 15, { steps: 5 }); await page.mouse.up({ button });
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  }
  /*
   * LET THE DAMPING FINISH before calling this the held pose.
   *
   * `OrbitControls` damps, so a drag leaves velocity that keeps decaying for a
   * few frames after `mouse.up`. Sampling immediately captured a camera still
   * in motion and then asserted that a resize had not moved it — measured drift
   * of 0.07 in an eye component and 2.6e-5 in a target one, which is the tail
   * of the drag and not the resize. Waiting for two identical consecutive
   * samples is what makes the exact comparison below mean what it says; a
   * tolerance here would have hidden a real nudge just as well as this noise.
   */
  const atRest = async (): Promise<Awaited<ReturnType<typeof snapshot>>> => {
    let previous = JSON.stringify(await snapshot());
    for (let attempt = 0; attempt < 60; attempt += 1) {
      await page.waitForTimeout(50);
      const current = JSON.stringify(await snapshot());
      if (current === previous) return await snapshot();
      previous = current;
    }
    throw new Error('the camera never came to rest');
  };
  const held = await atRest(); expect(held.fit).toBe(false);
  const pose = ({ size: _size, ...rest }: typeof held) => rest;
  for (const width of [1280, 1024, 843, 1024, 1440]) {
    await page.setViewportSize({ width, height: 800 });
    await expect.poll(async () => (await snapshot()).size[0]).toBe(await stageWidthFor(page, width));
    expect(pose(await snapshot())).toEqual(pose(held));
  }
  /*
   * THE WAY BACK IS THE CUBE, and after a free orbit it is a FACE.
   *
   * `[data-cube-current]` is the cell whose camera the workspace is on, and
   * after an arbitrary orbit there is no such cell: the pose names itself
   * `az<d>_el<d>` and only the twenty-six standard cameras have cells. That is
   * correct — the cube draws cameras, not orbits — so this clicks a drawn face,
   * which is what an operator reaches for and what every view cube does.
   *
   * Clicking the CURRENT cell re-fits without changing the camera, and that is
   * the other half of the affordance (`ViewCube.tsx`); it is reachable after a
   * zoom or a pan, which leave the direction alone and the cell current. This
   * case orbits, so it takes the face.
   */
  await expect(page.locator('[data-view-cube] [data-cube-current]')).toHaveCount(0);
  await page.locator('[data-view-cube] [data-cube-hit="face"]').first().click();
  await expect.poll(async () => (await snapshot()).fit).toBe(true);
  expect(writes).toEqual([]);
});
