// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
import { expect, test, type Page, type Route } from "@playwright/test";
import { execution, input, OTHER, RUN, setup, SID, send, status, stop } from "./fixture";
const question = { question_id: "question-1", question: "Which stock?", options: ["Keep 5.5 mm", "Use 6 mm stock"], allow_free_text: false };
async function select(page: Page, sid: string) {
  await page.locator("[data-session-switch]").click();
  await page.locator(`[data-session-option="${sid}"]`).click();
}
async function reopen(page: Page) {
  await page.locator("[data-stream-collapse]").click();
  await page.locator('[data-skip="composer"]').focus(); await page.keyboard.press("Enter");
}

test("one answer reservation survives remount; accepted same-page answer survives navigation and recorded reload", async ({ page }) => {
  const c = await setup(page);
  let answer: Route | null = null;
  let answers = 0;
  await page.route(`**/sessions/${SID}/answer`, route => { answer = route; answers++; });
  await input(page).fill("Ask before revising stock"); await send(page).click();
  c.execution = execution(RUN);
  await c.frame("tool_call", { name: "ask_user", arguments: question }, 0, RUN, "ask-call");
  await c.frame("question", question, 1, RUN, "ask-call");
  await expect(status(page)).toHaveAttribute("data-current-turn", "Waiting for your answer");
  await expect(input(page)).toHaveValue("");
  await expect(send(page)).toHaveText("Send");
  await expect(page.locator('[data-widget-source]')).not.toContainText("No result");
  await page.getByRole("button", { name: "Go to question" }).click();
  await expect(page.locator('[data-question-id="question-1"]')).toBeFocused();
  await input(page).fill("A newer draft; not queued");
  await page.locator('[data-ask-option="Use 6 mm stock"]').click();
  await expect(status(page)).toHaveAttribute("data-current-turn", "Recording answer");
  await reopen(page);
  await expect(status(page)).toHaveAttribute("data-current-turn", "Recording answer");
  await expect(page.locator('[data-widget-source]')).not.toContainText("Waiting for your answer");
  await expect(page.locator('[data-ask-option="Use 6 mm stock"]')).toHaveAttribute("aria-disabled", "true");
  await expect.poll(() => answer !== null).toBe(true);
  await answer!.fulfill({ json: { status: "ok", session_id: SID, requested_session_id: SID, run_id: RUN, question_id: question.question_id,
    accepted: true, answered_by: "self", answer: "Use 6 mm stock" } });
  await expect(status(page)).toHaveAttribute("data-current-turn", "Working");
  await expect(page.locator('[data-ask-answer]')).toHaveText("Answer recorded:Use 6 mm stock");
  await select(page, OTHER); await select(page, SID);
  await expect(page.locator('[data-ask-answer]')).toHaveText("Answer recorded:Use 6 mm stock");
  await expect(input(page)).toHaveValue("A newer draft; not queued");
  c.execution = execution(RUN, "completed");
  await c.frame("terminal", { state: "completed" }, 2);
  await expect(status(page)).toHaveAttribute("data-current-turn", "Completed");
  await expect(send(page)).toHaveAttribute("aria-disabled", "true"); // POST still unresolved
  await c.release();
  await expect(send(page)).not.toHaveAttribute("aria-disabled", "true");
  await expect(input(page)).toHaveValue("A newer draft; not queued");
  const recorded = [
    { run_id: SID, seq: 0, turn: 0, kind: "tool_call", tool_call_id: "recorded-ask", payload: { name: "ask_user", arguments: question } },
    { run_id: SID, seq: 1, turn: 0, kind: "tool_result", tool_call_id: "recorded-ask", payload: { toolName: "ask_user", text: JSON.stringify({ selection: { option_label: "Use 6 mm stock", option_index: 1 } }), isError: false } },
  ];
  await page.route(`**/sessions/${SID}/history*`, route => route.fulfill({ json: {
    status: "ok", session_id: SID, events: recorded, user_prompts: [], cursor: null, done: true, end_cursor: "recorded-answer-tail",
  } }));
  await page.reload();
  await expect(page.locator('[data-ask-answer]')).toHaveText("Answer recorded:Use 6 mm stock");
  await expect(page.locator('[data-widget-source]')).not.toHaveAttribute("data-answered-by", "other");
  await expect(page.locator('[data-widget-source]')).not.toContainText("another client");
  expect(answers).toBe(1); expect(c.mutations.map(m => m.path)).toEqual([`/sessions/${SID}/prompt`]);
  expect(c.faults).toEqual([]);
});

test("late answer evidence resolves uncertain answer receipt without a second write", async ({ page }) => {
  const c = await setup(page, execution(RUN)); let answers = 0;
  await page.route(`**/sessions/${SID}/answer`, async route => { answers++; await route.abort("failed"); });
  await c.frame("question", question, 0);
  await expect(status(page)).toHaveAttribute("data-current-turn", "Waiting for your answer");
  await page.locator('[data-ask-option="Use 6 mm stock"]').click();
  await expect(status(page)).toHaveAttribute("data-current-turn", "Checking");
  await reopen(page);
  await expect(page.locator('[data-ask-state="checking"]')).toContainText("Checking whether the answer was recorded");
  await expect(page.locator('[data-widget-source]')).not.toContainText("The server refused");
  await expect(page.locator('[data-ask-option="Use 6 mm stock"]')).toHaveAttribute("aria-disabled", "true");
  await c.frame("answer", { question_id: question.question_id, answer: "Use 6 mm stock" }, 1);
  await expect(status(page)).toHaveAttribute("data-current-turn", "Working");
  await expect(page.locator('[data-ask-answer]')).toContainText("Use 6 mm stock");
  expect(answers).toBe(1); expect(c.mutations).toEqual([]); expect(c.faults).toEqual([]);
});

for (const outcome of ["cancelled", "failed"]) test(`delayed Stop never wins over matching ${outcome} terminal at 843`, async ({ page }) => {
  await page.setViewportSize({ width: 843, height: 800 });
  const c = await setup(page, execution(RUN));
  let cancel: Route | null = null; let cancels = 0;
  await page.route(`**/runs/${RUN}/cancel`, route => { cancel = route; cancels++; });
  await input(page).fill("This stays an editable next draft");
  await stop(page).click();
  await expect(status(page)).toHaveAttribute("data-current-turn", "Stop requested");
  await expect(stop(page)).toHaveAttribute("aria-disabled", "true");
  await reopen(page);
  await expect(status(page)).toHaveAttribute("data-current-turn", "Stop requested");
  await expect.poll(() => cancel !== null).toBe(true);
  await cancel!.fulfill({ json: { status: "ok", run_id: RUN, abandoned_questions: 0 } });
  await expect(status(page)).toHaveAttribute("data-current-turn", "Stop requested");
  await expect(send(page)).toHaveAttribute("aria-disabled", "true");
  const error = '400: {"error":{"message":"The comparison was refused. No design changed.","token":"private-value","url":"https://private.invalid"}}';
  c.execution = { ...execution(RUN, outcome), terminal: { run_id: RUN, terminal_id: "terminal-winner", state: outcome, payload: { error } } };
  await c.frame("terminal", { state: outcome, error }, 0);
  await expect(status(page)).toHaveAttribute("data-current-turn", outcome === "failed" ? "Request failed" : "Cancelled");
  await expect(send(page)).not.toHaveAttribute("aria-disabled", "true");
  await expect(input(page)).toHaveValue("This stays an editable next draft");
  if (outcome === "failed") {
    await expect(status(page)).toContainText("The comparison was refused.");
    await expect(status(page)).not.toContainText("400:");
    await expect(status(page)).not.toContainText("No design changed");
    const terminal = page.locator('[data-terminal-state="failed"]');
    await expect(terminal).toContainText("Review the result before writing a new request.");
    await terminal.locator("summary").click();
    await expect(terminal).not.toContainText("private-value");
    await expect(terminal).not.toContainText("private.invalid");
  }
  expect(cancels).toBe(1); expect(c.mutations).toEqual([]); expect(c.faults).toEqual([]);
});
