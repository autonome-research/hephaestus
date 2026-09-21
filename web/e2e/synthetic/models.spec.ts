// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
// Local route fakes only. Integration owns running this suite.
import { expect, test } from "@playwright/test";
import { execution, input, RUN, send, setup, SID } from "./fixture";
import { spark, vision } from "../../test/fixtures/models";

for (const width of [843, 1440]) {
  test(`live identity, capability, full disclosure and keyboard selection at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const c = await setup(page);
    const control = page.locator("[data-model-button]");
    await expect(control).toHaveAccessibleName(/local\/fake\/spark.*Text only/);
    await expect(control).toBeEnabled();
    /*
     * REWRITTEN 2026-09-20. The bounded "Message details" region is struck
     * along with the rest of the composer's narration of itself, and the
     * composer's model control is icon-only. FULL IDENTITY did not go with
     * them — it is on the control's accessible name (asserted above) and its
     * `title`, and the creation dialog still spells it out inline. What this
     * case checks is unchanged: the complete provider/model identity is
     * readable without opening anything, the catalog is navigable from the
     * keyboard alone, and choosing costs the draft and the transcript nothing.
     */
    await expect(control).toHaveAttribute("title", /local\/fake\/spark/);
    await input(page).fill("Draft survives model choice");
    const recorded = page.locator('[data-tool-call-id="recorded-call"] details');
    await recorded.locator("summary").click();
    await control.press("Enter");
    // An anchored popover, not a modal: `variant="popover"` is `role="group"`.
    const picker = page.getByRole("group", { name: "Choose model" });
    // §7A: "Search is conditional on a long catalog". Three declared models is
    // not a long catalog, so the first focusable in the panel — and where the
    // trap puts the caret — is the first OPTION.
    await expect(picker.getByRole("combobox")).toHaveCount(0);
    const options = picker.getByRole("option");
    await expect(options.filter({ hasText: "Spark" })).toHaveAttribute("aria-selected", "true");
    await expect(options.first()).toBeFocused();
    await page.keyboard.press("ArrowDown");
    await expect(options.nth(1)).toBeFocused();
    expect(c.mutations).toEqual([]);
    await page.keyboard.press("Escape");
    await expect(control).toBeFocused();
    // The declared-but-unknown model is offered and refused, with its reason.
    await control.press("Enter");
    await expect(options.filter({ hasText: "Unknown declaration" })).toHaveAttribute("aria-disabled", "true");
    await expect(picker).toContainText("model_unknown");
    // Walk onto the unavailable entry and try to take it. The refusal lives in
    // `choose`, so the keyboard path has to be refused exactly as a click is —
    // and it is not clicked here on purpose: `aria-disabled` makes the element
    // unactionable for a pointer, which would prove nothing about the guard.
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("ArrowDown");
    await expect(options.nth(2)).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(picker).toBeVisible();
    expect(c.mutations).toEqual([]);
    // Vision is the one with images, and choosing it is one keystroke away.
    await page.keyboard.press("ArrowDown");
    await expect(options.first()).toBeFocused();
    await expect(options.first()).toContainText("Vision");
    await page.keyboard.press("Enter");
    await expect(picker).toHaveCount(0);
    await expect(control).toHaveAccessibleName(/local\/fake\/vision\/image.*Text \+ images/);
    await expect(control).toBeFocused();
    await expect(input(page)).toHaveValue("Draft survives model choice");
    await expect(recorded).toHaveAttribute("open", "");
    await expect(page.locator("[data-composer]")).toHaveAttribute("data-session-id", SID);
    expect(c.mutations).toEqual([{ path: `/sessions/${SID}/model`, body: { model: { provider_id: vision.provider_id, model_id: vision.model_id }, expected_model_revision: { epoch: "models-1", version: 0 } } }]);
    // The control itself is what must stay inside the chat column now that the
    // capability badge it used to carry lives on the accessible name.
    const bounds = (await control.boundingBox())!;
    const column = (await page.locator("#chat-column").boundingBox())!;
    expect(bounds.x + bounds.width).toBeLessThanOrEqual(column.x + column.width);
    expect(c.faults).toEqual([]);
  });
}

test("explicit creation shows and submits the proposal, without changing the existing session", async ({ page }) => {
  const c = await setup(page);
  await input(page).fill("Existing session draft");
  await page.locator("[data-session-create-menu]").click();
  await page.locator("[data-session-create]").click();
  const creation = page.getByRole("dialog", { name: "New conversation · Project", exact: true });
  await expect(creation).toContainText("Proposed default: local/fake/vision/image");
  await expect(creation).toContainText("Text + images");
  expect(c.mutations).toEqual([]);
  await expect(creation.getByRole("button", { name: "Create conversation", exact: true })).toBeEnabled();
  await creation.getByRole("button", { name: "Create conversation", exact: true }).click();
  await expect(page.locator("[data-composer]")).toHaveAttribute("data-session-id", "synthetic-created");
  expect(c.mutations).toEqual([{ path: "/sessions", body: { profile: "orchestrator", model: { provider_id: vision.provider_id, model_id: vision.model_id } } }]);
  expect(c.model.current).toEqual(spark);
  await page.locator("[data-session-switch]").click();
  await page.locator(`[data-session-option="${SID}"]`).click();
  await expect(input(page)).toHaveValue("Existing session draft");
  expect(c.faults).toEqual([]);
});

test("pending selection gates all Send paths; lost response reconciles without replay", async ({ page }) => {
  const c = await setup(page); c.holdModel = true;
  await input(page).fill("Do not implicitly send me");
  const control = page.locator("[data-model-button]");
  await expect(control).toBeEnabled(); await control.click();
  // No search field for a three-model catalog (§7A); pick from the listbox.
  const choice = page.getByRole("option").filter({ hasText: "Vision" });
  await expect(choice).toHaveAttribute("aria-disabled", "false");
  await choice.click();
  await expect.poll(() => c.pendingModel !== null).toBe(true);
  await expect(control).toBeDisabled(); await expect(send(page)).toBeDisabled();
  await input(page).press("Enter");
  await page.locator("[data-composer]").evaluate(form => form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
  expect(c.mutations).toHaveLength(1);
  await c.pendingModel!.abort("failed"); c.pendingModel = null;
  await expect(page.locator("[data-model-control]")).toContainText("Changing model");
  await expect(send(page)).toBeDisabled();
  c.model = { ...c.model, current: vision, selected: { provider_id: vision.provider_id, model_id: vision.model_id },
    pending_selection: null, state: "ready", revision: { ...c.model.revision, version: 2 } };
  // Visible idle polling observes another client / a late settlement, without an event kind.
  await expect(control).toHaveAccessibleName(/vision\/image.*Text \+ images/, { timeout: 10_000 });
  await expect(send(page)).toBeEnabled();
  await expect(input(page)).toHaveValue("Do not implicitly send me");
  expect(c.mutations).toHaveLength(1);
  await send(page).click();
  await expect.poll(() => c.pending !== null).toBe(true);
  expect(c.mutations.at(-1)?.body).toMatchObject({ expected_model_revision: c.model.revision });
  expect(c.faults).toEqual([]);
});

test("a cross-client model change refuses a stale Send and never resubmits it", async ({ page }) => {
  const c = await setup(page);
  await input(page).fill("Review the new model first");
  await expect(send(page)).toBeEnabled();
  let raced = false;
  await page.route(`**/api/v1/sessions/${SID}/prompt`, async route => {
    if (!raced) {
      raced = true;
      c.model = { ...c.model, current: vision, selected: { provider_id: vision.provider_id, model_id: vision.model_id },
        revision: { ...c.model.revision, version: 2 } };
    }
    await route.fallback();
  });
  await send(page).click();
  await expect(page.locator("[data-composer-refused]")).toHaveAttribute("data-composer-refused", "model_changed");
  await expect(page.locator("[data-model-button]")).toHaveAccessibleName(/vision\/image.*Text \+ images/);
  await expect(input(page)).toHaveValue("Review the new model first");
  await expect(send(page)).toBeEnabled();
  expect(c.mutations).toHaveLength(1);
  expect(c.pending).toBeNull();
  await send(page).click();
  await expect.poll(() => c.pending !== null).toBe(true);
  expect(c.mutations).toHaveLength(2);
  expect(c.mutations.at(-1)?.body).toMatchObject({ expected_model_revision: c.model.revision });
  expect(c.faults).toEqual([]);
});

test("active and awaiting-answer turns keep model readable and disable selection", async ({ page }) => {
  const c = await setup(page, execution(RUN));
  await c.frame("question", { question_id: "synthetic-model-question", question: "Continue?", options: ["Yes", "No"], multi: false, allow_free_text: false }, 0);
  const control = page.locator("[data-model-button]");
  await expect(control).toHaveAccessibleName(/spark.*Text only/);
  await expect(control).toBeDisabled();
  await control.press("Enter");
  await expect(page.getByRole("dialog", { name: "Choose model" })).toHaveCount(0);
  expect(c.mutations).toEqual([]);
  c.execution = execution(RUN, "completed");
  c.model = { ...c.model, current: null, selected: { provider_id: spark.provider_id, model_id: spark.model_id }, state: "unavailable", reason: "model_unknown", revision: { ...c.model.revision, version: 1 } };
  await expect(control).toHaveAccessibleName(/Saved selection.*spark.*Capability unknown/, { timeout: 10_000 });
  await expect(control).toBeEnabled(); await expect(send(page)).toBeDisabled();
  await expect(page.getByText("Recorded narration stays visible.")).toBeVisible();
  expect(c.mutations).toEqual([]); expect(c.faults).toEqual([]);
});
