// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
import { expect, test } from "@playwright/test";
import { execution, input, OLD, OTHER, RUN, send, setup, SID, status, stop } from "./fixture";

test("zero-frame ownership guards every send path, drafts survive switch/collapse, Stop waits for terminal", async ({ page }, info) => {
  const c = await setup(page, execution(RUN));
  await expect(status(page)).toHaveAttribute("data-current-turn", "Working");
  await input(page).fill("Editable next draft");
  await expect(send(page)).toBeDisabled();
  await input(page).press("Enter");
  await page.locator("[data-composer]").evaluate(form => form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
  await send(page).dispatchEvent("click");
  expect(c.mutations).toEqual([]);
  await page.locator("[data-stream-collapse]").click();
  await page.locator("[data-stream-strip]").focus();
  await expect(input(page)).toHaveValue("Editable next draft");
  await page.locator("[data-session-switch]").click();
  await page.locator(`[data-session-option="${OTHER}"]`).click();
  await input(page).fill("Other session draft");
  await page.locator("[data-session-switch]").click();
  await page.locator(`[data-session-option="${SID}"]`).click();
  await expect(input(page)).toHaveValue("Editable next draft");
  await stop(page).click();
  await expect(status(page)).toContainText("Stop requested");
  await expect(status(page)).toHaveAttribute("data-current-turn", "Stop requested");
  expect(c.mutations.map(x => x.path)).toEqual([`/runs/${RUN}/cancel`]);
  c.execution = execution(RUN, "cancelled");
  await expect(status(page)).toHaveAttribute("data-current-turn", "Cancelled");
  await expect(stop(page)).toHaveCount(0);
  await expect(send(page)).toBeEnabled();
  await page.screenshot({ path: info.outputPath("terminal-confirmed-stop.png") });
  expect(c.faults).toEqual([]);
});

test("pending POST keeps revisions editable and late responses cannot replace the durable terminal", async ({ page }) => {
  const c = await setup(page, execution(OLD, "completed"));
  await expect(status(page)).toHaveAttribute("data-current-turn", "Completed");
  await input(page).fill("Synthetic sent request");
  await send(page).click();
  await expect(status(page)).not.toHaveAttribute("data-current-turn", "Completed");
  await input(page).fill("Newer revision while POST waits");
  await input(page).press("Enter");
  await expect(send(page)).toBeDisabled();
  c.execution = execution(RUN);
  await expect(status(page)).toHaveAttribute("data-current-turn", "Working");
  c.execution = execution(RUN, "cancelled");
  await c.frame("terminal", { state: "cancelled", terminal_id: `terminal-${RUN}`, payload: { reason: "fixture outcome" } }, 0);
  await expect.poll(() => c.tailReads).toBeGreaterThan(0);
  await c.release(); // deliberately conflicting completed POST
  await expect(status(page)).toHaveAttribute("data-current-turn", "Cancelled");
  await expect(input(page)).toHaveValue("Newer revision while POST waits");
  expect(c.mutations.filter(x => x.path.endsWith("/prompt"))).toHaveLength(1);
  expect(c.mutations.some(x => x.path.endsWith("/cancel"))).toBe(false);
  expect(c.faults).toEqual([]);
});

test("refusal keeps one editable draft, no duplicate echo and no automatic retry", async ({ page }, info) => {
  const c = await setup(page);
  await input(page).fill("Refused synthetic draft");
  await expect(send(page)).toBeEnabled();
  await input(page).press("Enter");
  await c.release(409, { status: "error", reason: "run_in_flight", message: "fixture busy", session_id: SID, run_id: RUN });
  c.execution = execution(RUN);
  await expect(page.locator("[data-composer-refused]")).toHaveAttribute("data-composer-refused", "run_in_flight");
  await expect(input(page)).toHaveValue("Refused synthetic draft");
  await expect(page.locator('[data-testid="transcript"]')).not.toContainText("Refused synthetic draft");
  await expect(send(page)).toBeDisabled();
  await input(page).press("Enter");
  await page.screenshot({ path: info.outputPath("refused-draft.png") });
  expect(c.mutations).toHaveLength(1);
  expect(c.faults).toEqual([]);
});

test("reconnect and missed terminal refresh zero-event outcomes without trusting stale snapshots or live IDs", async ({ page }) => {
  const c = await setup(page, execution(RUN));
  c.prompts = [{ turn: 0, seq: 0, run_id: RUN, text: "Recorded fixture request" }];
  await expect(status(page)).toHaveAttribute("data-current-turn", "Working");
  await c.frame("text_delta", { text: "Live fixture suffix." }, 1);
  await expect(page.getByText("Live fixture suffix.")).toBeVisible();
  c.sessionsFail = true;
  await c.sockets.at(-1)!.close({ code: 4409, reason: "resync_required" });
  await expect(status(page)).toHaveAttribute("data-current-turn", "Checking");
  await expect(send(page)).toBeDisabled();
  await expect(page.locator("[data-resync]")).toBeVisible();
  await expect(page.getByText("Recorded narration stays visible.")).toBeVisible();
  await expect(page.getByText("Live fixture suffix.")).toBeVisible();
  // HTTP can establish the winner even when the browser missed its terminal frame.
  c.execution = execution(RUN, "cancelled");
  c.prompts = [{ turn: 0, seq: 0, run_id: RUN, text: "Recorded fixture request", outcome: { state: "cancelled" } }];
  c.sessionsFail = false;
  await expect(status(page)).toHaveAttribute("data-current-turn", "Cancelled");
  await expect(page.locator('[data-outcome-state="cancelled"]')).toHaveCount(1);
  expect(c.tailReads).toBeGreaterThan(0);
  await expect(stop(page)).toHaveCount(0);
  c.stale = true;
  c.execution = execution(RUN);
  const reads = c.sessionReads;
  await c.frame("text_delta", { text: "Late old frame must not enable Stop." }, 2, OLD);
  await expect.poll(() => c.sessionReads).toBeGreaterThan(reads);
  await expect(stop(page)).toHaveCount(0);
  expect(c.mutations).toEqual([]);
  expect(c.faults).toEqual([]);
});

test("lost POST is not resent, queued or cancelled after terminal reconciliation", async ({ page }) => {
  const c = await setup(page);
  await input(page).fill("Unknown delivery synthetic draft");
  await expect(send(page)).toBeEnabled();
  await send(page).click();
  await expect.poll(() => c.pending !== null).toBe(true);
  await c.pending!.abort("failed");
  c.pending = null;
  await expect(page.locator("[data-composer]")).toHaveAttribute("data-send-state", "unknown");
  c.execution = execution(RUN, "completed");
  await expect(status(page)).toHaveAttribute("data-current-turn", "Checking");
  await input(page).press("Enter");
  await expect(send(page)).toBeDisabled();
  await expect(input(page)).toHaveValue("");
  await page.locator('[data-submitted-attempt] summary').click();
  await expect(page.locator('[data-submitted-attempt]')).toContainText("Unknown delivery synthetic draft");
  await page.getByRole("button", { name: "Keep draft for a new send" }).click();
  await expect(input(page)).toHaveValue("Unknown delivery synthetic draft");
  expect(c.mutations).toHaveLength(1);
  expect(c.faults).toEqual([]);
});

test("visible narration and individual collapsed tools preserve expansion, failures and questions", async ({ page }, info) => {
  const c = await setup(page, execution(RUN));
  const recorded = page.locator('[data-tool-call-id="recorded-call"]');
  await expect(recorded).toBeVisible();
  await expect(recorded.locator("details")).not.toHaveAttribute("open", "");
  await expect(recorded.locator("[data-field=fixture_payload]")).not.toBeVisible();
  await expect(page.getByText("Recorded narration stays visible.")).toBeVisible();
  await recorded.locator("summary").click();
  await expect(recorded.locator("[data-field=fixture_payload]")).toBeVisible();
  await c.frame("text_delta", { text: "Live narration stays visible." }, 0);
  await c.frame("tool_call", { name: "inspect_part", arguments: { name: "bracket", fixture: "expand me" } }, 1, RUN, "live-call");
  const live = page.locator('[data-tool-call-id="live-call"]');
  await expect(live).toBeVisible();
  await live.locator("summary").click();
  await c.frame("tool_result", { toolName: "inspect_part", text: '{"status":"ok","fixture_payload":"streamed result"}', isError: false }, 2, RUN, "live-call");
  await expect(live.locator("details")).toHaveAttribute("open", "");
  await expect(live.locator("[data-field=fixture_payload]")).toContainText("streamed result");
  await expect(recorded.locator("details")).toHaveAttribute("open", "");
  await c.frame("tool_call", { name: "build_part", arguments: { name: "bracket" } }, 3, RUN, "failed-call");
  await c.frame("tool_result", { toolName: "build_part", text: '{"status":"error","message":"Synthetic failure detail"}', isError: true }, 4, RUN, "failed-call");
  const failed = page.locator('[data-tool-call-id="failed-call"]');
  await expect(failed).toHaveAttribute("data-status", "error");
  await expect(failed.locator("details")).not.toHaveAttribute("open", "");
  await expect(failed.getByText("Tool failed", { exact: false }).first()).toBeVisible();
  await c.frame("question", { question_id: "synthetic-question", question: "Which synthetic option?", options: ["First", "Second"], allow_free_text: false, multi: false }, 5, RUN, "ask-call");
  await expect(page.getByText("Which synthetic option?")).toBeVisible();
  await expect(page.getByText("Live narration stays visible.")).toBeVisible();
  await page.screenshot({ path: info.outputPath("continuous-tools-question.png") });
  expect(c.mutations).toEqual([]);
  expect(c.faults).toEqual([]);
});
