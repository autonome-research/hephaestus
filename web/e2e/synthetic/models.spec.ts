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
    const details = page.locator("[data-model-control] > details");
    await details.locator("summary").press("Enter");
    await expect(details).toContainText("local/fake/spark");
    await details.locator("summary").click(); // touch/click-accessible disclosure as well
    await input(page).fill("Draft survives model choice");
    const recorded = page.locator('[data-tool-call-id="recorded-call"] details');
    await recorded.locator("summary").click();
    await control.press("Enter");
    const dialog = page.getByRole("dialog", { name: "Choose model" });
    const search = dialog.getByRole("combobox", { name: "Search provider or model" });
    await expect(search).toBeFocused();
    await expect(dialog.getByRole("option", { name: /local\/fake\/spark/ })).toHaveAttribute("aria-selected", "true");
    await search.press("ArrowDown");
    expect(c.mutations).toEqual([]);
    await search.press("Escape");
    await expect(control).toBeFocused();
    await control.press("Enter");
    await search.fill("unknown");
    await expect(dialog.getByRole("option")).toHaveAttribute("aria-disabled", "true");
    await expect(dialog).toContainText("model_unknown");
    await search.press("Enter");
    expect(c.mutations).toEqual([]);
    await search.fill("vision/image");
    await expect(dialog.getByRole("option")).toContainText("Text + images");
    await expect(dialog.getByRole("option")).toHaveAttribute("aria-disabled", "false");
    await search.press("Enter");
    await expect(dialog).toHaveCount(0);
    await expect(control).toHaveAccessibleName(/local\/fake\/vision\/image.*Text \+ images/);
    await expect(control).toBeFocused();
    await expect(input(page)).toHaveValue("Draft survives model choice");
    await expect(recorded).toHaveAttribute("open", "");
    await expect(page.locator("[data-composer]")).toHaveAttribute("data-session-id", SID);
    expect(c.mutations).toEqual([{ path: `/sessions/${SID}/model`, body: { model: { provider_id: vision.provider_id, model_id: vision.model_id }, expected_model_revision: { epoch: "models-1", version: 0 } } }]);
    const badge = control.locator('span[aria-hidden="true"]').last();
    await expect(badge).toBeVisible();
    const bounds = (await badge.boundingBox())!;
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
  const search = page.getByRole("combobox", { name: "Search provider or model" });
  await search.fill("vision");
  await expect(page.getByRole("option")).toHaveAttribute("aria-disabled", "false");
  await search.press("Enter");
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
