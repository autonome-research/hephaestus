// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
import { expect, test } from "@playwright/test";
import { setup, SID, input } from "./fixture";

test("compact long history retains every call/result identity, native disclosure, narration and speaker landmarks", async ({ page }) => {
  const c = await setup(page);
  c.events = Array.from({ length: 75 }, (_, i) => [
    { run_id: SID, seq: i * 3, turn: 0, kind: "text_delta", payload: { text: `Narration ${i}.` } },
    { run_id: SID, seq: i * 3 + 1, turn: 0, kind: "tool_call", tool_call_id: `call-${i}`, payload: { name: "inspect_part", arguments: { name: `part-${i}` } } },
    { run_id: SID, seq: i * 3 + 2, turn: 0, kind: "tool_result", tool_call_id: `call-${i}`, payload: { toolName: "inspect_part", text: `{"status":"ok","index":${i}}`, isError: false } },
  ]).flat();
  await page.reload();
  const transcript = page.locator('[data-testid="transcript"]');
  await expect(transcript.locator("[data-tool-call-id]")).toHaveCount(75);
  await expect(transcript.locator("[data-chip-detail]:not([open])")).toHaveCount(75);
  await expect(transcript.locator("[data-assistant-landmark]")).toHaveCount(75);
  const identities = await transcript.locator("[data-event-id]").evaluateAll(nodes => nodes.map(n => n.getAttribute("data-event-id")));
  expect(identities).toHaveLength(226); // 225 tool/narration events + one recorded request
  expect(new Set(identities).size).toBe(226);
  for (let i = 0; i < 75; i++) {
    const call = transcript.locator(`[data-tool-call-id="call-${i}"]`);
    await expect(call.locator("summary")).toContainText("inspect_part");
    await expect(call.locator("summary")).toContainText("Done");
    expect(await call.locator("summary").evaluate(el => el.getBoundingClientRect().height)).toBe(24);
    await expect(transcript).toContainText(`Narration ${i}.`);
  }
  const call = transcript.locator('[data-tool-call-id="call-40"]');
  await call.locator("summary").click();
  await expect(call.locator('[data-field="index"]')).toContainText("40");
  await expect(transcript.locator('[data-row="user-prompt"]')).toContainText("You");
  expect(c.mutations).toEqual([]);
  expect(c.faults).toEqual([]);
});

test("unbuilt Open conversation reveals/focuses only, preserving existing draft/session with no write", async ({ page }) => {
  await page.setViewportSize({ width: 843, height: 800 });
  const c = await setup(page);
  await page.route("**/parts/bracket/build", route => route.fulfill({ json: { status: "not_built", artifact_ref: null, geometries: [], geometry_count: 0 } }));
  // Explicit workspace return re-reads the newly supplied unbuilt projection.
  await page.reload();
  await expect(page.locator('[data-viewport-absence="not-built"]')).toBeVisible();
  await input(page).fill("keep this exact draft");
  const route = new URL(page.url()).hash;
  const model = await page.locator("[data-model-button]").textContent();
  await page.locator("[data-stream-collapse]").click();
  await page.locator("[data-unbuilt-conversation]").click();
  await expect(input(page)).toBeFocused();
  await expect(input(page)).toHaveValue("keep this exact draft");
  await expect(page.locator("[data-composer]")).toHaveAttribute("data-session-id", SID);
  expect(new URL(page.url()).hash).toBe(route);
  await expect(page.locator("[data-model-button]")).toHaveText(model!);
  expect(c.mutations).toEqual([]);
  expect(c.faults).toEqual([]);
});

test("unbuilt reveal with no session focuses the invitation composer without creating or inserting", async ({ page }) => {
  const c = await setup(page);
  await page.route("**/sessions", route => route.request().method() === "GET"
    ? route.fulfill({ json: { status: "ok", sessions: [], profiles: [] } }) : route.fallback());
  await page.route("**/parts/bracket/build", route => route.fulfill({ json: { status: "not_built", artifact_ref: null, geometries: [], geometry_count: 0 } }));
  // New document, not a same-document hash navigation whose cached listing
  // legitimately reselects its first session before the empty read arrives.
  await page.goto("about:blank");
  await page.goto("/#/p/bracket");
  await expect(page.locator('[data-viewport-absence="not-built"]')).toBeVisible();
  await expect(page.locator("[data-composer]")).not.toHaveAttribute("data-session-id", SID);
  await page.locator("[data-stream-collapse]").click();
  await page.locator("[data-unbuilt-conversation]").click();
  await expect(input(page)).toBeFocused();
  await expect(input(page)).toHaveValue("");
  await expect(page.locator("[data-stream-empty]")).toBeVisible();
  expect(c.mutations).toEqual([]);
  expect(c.faults).toEqual([]);
});
