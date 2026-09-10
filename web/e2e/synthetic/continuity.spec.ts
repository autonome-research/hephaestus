// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
import { expect, test, type Page } from "@playwright/test";
import { execution, input, OTHER, RUN, setup, SID } from "./fixture";

const scroll = (page: Page) => page.locator("[data-transcript-scroll]");
const metrics = (page: Page) => scroll(page).evaluate(el => ({ top: el.scrollTop, height: el.scrollHeight,
  client: el.clientHeight, content: el.firstElementChild!.getBoundingClientRect().height,
  rows: el.querySelectorAll("[data-row]").length }));
async function select(page: Page, id: string) {
  await page.locator("[data-session-switch]").click();
  await page.locator(`[data-session-option="${id}"]`).click();
  await expect(page.locator("[data-history-state]")).toHaveAttribute("data-history-state", "complete");
}
async function atLatest(page: Page) {
  await expect.poll(async () => { const m = await metrics(page); return Math.abs(m.height - m.client - m.top); }).toBeLessThanOrEqual(1);
}

test("large minimum-thumb ranges shrink to short/new and return without decorative overflow", async ({ page }, info) => {
  const c = await setup(page);
  c.events[0]!.payload.text = Array.from({ length: 12000 }, (_, i) => `Recorded paragraph ${i}.`).join("\n\n");
  await page.route(`**/sessions/${OTHER}/history*`, route => route.fulfill({ json: {
    status: "ok", session_id: OTHER, events: [{ run_id: OTHER, seq: 0, kind: "text_delta", payload: { text: "Short recorded reply." } }],
    user_prompts: [], cursor: null, done: true, end_cursor: "short-tail",
  } }));
  await page.reload();
  await expect(page.locator("[data-history-state]")).toHaveAttribute("data-history-state", "complete");
  await atLatest(page);
  const long = await metrics(page);
  await info.attach("large-range-metrics", { body: JSON.stringify(long), contentType: "application/json" });
  expect(long.height).toBeGreaterThan(long.client * long.client / 2);
  // Repeated Latest/scroll synchronizations cannot grow real bounds.
  for (let i = 0; i < 3; i++) {
    await scroll(page).evaluate(el => { el.scrollTop -= 500; });
    await page.locator("[data-jump-latest]").click(); await atLatest(page);
    expect((await metrics(page)).height).toBe(long.height);
  }
  await select(page, OTHER);
  await expect(page.getByText("Short recorded reply.")).toBeVisible();
  expect((await metrics(page)).top).toBe(0);
  expect((await metrics(page)).height).toBe((await metrics(page)).client);
  await info.attach("short-range-metrics", { body: JSON.stringify(await metrics(page)), contentType: "application/json" });
  await page.locator("[data-session-create-menu]").click();
  await page.locator("[data-session-create]").click();
  await page.getByRole("button", { name: "Create conversation", exact: true }).click();
  await expect(page.locator("[data-transcript-empty]")).toBeVisible();
  expect((await metrics(page)).top).toBe(0);
  await select(page, SID); await atLatest(page);
  expect((await metrics(page)).height).toBe(long.height);
  expect(c.mutations.map(m => m.path)).toEqual(["/sessions"]);
  expect(c.faults).toEqual([]);
});

test("same-row live text/result growth follows or preserves anchor, including resize/remount", async ({ page }) => {
  const c = await setup(page, execution(RUN));
  await c.frame("text_delta", { text: "Live opening.\n\n" }, 0);
  await expect(page.getByText("Live opening.")).toBeVisible();
  const count = (await metrics(page)).rows;
  await c.frame("text_delta", { text: "Growing live paragraph.\n\n".repeat(80) }, 1);
  await atLatest(page); expect((await metrics(page)).rows).toBe(count);
  await scroll(page).evaluate(el => { el.scrollTop = 150; });
  await expect(page.locator("[data-jump-latest]")).toBeVisible();
  const before = (await metrics(page)).top;
  await c.frame("text_delta", { text: "Further live growth.\n\n".repeat(30) }, 2);
  await expect(page.getByText("Further live growth.").first()).toBeAttached();
  expect((await metrics(page)).top).toBe(before);
  await page.locator("[data-jump-latest]").click(); await atLatest(page);
  await c.frame("tool_call", { name: "inspect_part", arguments: {} }, 3, RUN, "growing-call");
  const tool = page.locator('[data-tool-call-id="growing-call"]');
  await tool.locator("summary").click();
  const withCall = (await metrics(page)).rows;
  await c.frame("tool_result", { toolName: "inspect_part", text: JSON.stringify({ result: "Dynamic result text ".repeat(800) }), isError: false }, 4, RUN, "growing-call");
  await expect(tool).toHaveAttribute("data-status", "ok");
  await expect(tool.locator("details")).toHaveAttribute("open", "");
  expect((await metrics(page)).rows).toBe(withCall); await atLatest(page);
  await page.locator("[data-stream-resize]").press("End"); await atLatest(page);
  await select(page, OTHER); await select(page, SID);
  await expect(tool.locator("details")).toHaveAttribute("open", ""); await atLatest(page);
  expect(c.mutations).toEqual([]); expect(c.faults).toEqual([]);
});

for (const width of [843, 1440]) test(`focus-only hidden composer/stage and history replay at ${width}`, async ({ page }) => {
  await page.setViewportSize({ width, height: 800 });
  const c = await setup(page);
  await input(page).fill("Unsent session-owned draft");
  const hash = await page.evaluate(() => location.hash);
  const model = await page.locator("[data-model-button]").textContent();
  expect(model).toContain("Current model:");
  for (const hidden of [false, true]) {
    if (hidden) {
      await page.locator("[data-stream-collapse]").click();
      await page.locator('[data-skip="stage"]').focus(); await page.keyboard.press("Enter");
      await expect(page.locator("#stage")).toBeFocused();
      await expect(page.locator("[data-stream-strip]")).toBeVisible();
      expect(await page.evaluate(() => location.hash)).toBe(hash);
    }
    await page.locator('[data-skip="composer"]').focus(); await page.keyboard.press("Enter");
    await expect(input(page)).toBeFocused(); await expect(input(page)).toHaveValue("Unsent session-owned draft");
    expect(await page.evaluate(() => location.hash)).toBe(hash);
    expect(await page.locator("[data-model-button]").textContent()).toBe(model);
    await page.locator('[data-skip="stage"]').focus(); await page.keyboard.press("Enter");
    await expect(page.locator("#stage")).toBeFocused();
    expect(await page.evaluate(() => location.hash)).toBe(hash);
  }
  // Addressable navigation still replays without destroying the forward stack.
  const deep = `#/p/other?itab=checks&s=${OTHER}`;
  await page.evaluate(value => { location.hash = value; }, deep);
  await expect(page.locator("[data-composer]")).toHaveAttribute("data-session-id", OTHER);
  await page.goBack(); await expect(page.locator("[data-composer]")).toHaveAttribute("data-session-id", SID);
  await page.goForward(); await expect(page.locator("[data-composer]")).toHaveAttribute("data-session-id", OTHER);
  expect(await page.evaluate(() => location.hash)).toBe(deep);
  expect(c.mutations).toEqual([]); expect(c.faults).toEqual([]);
});
