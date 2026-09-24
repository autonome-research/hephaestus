// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
// Local route fakes only. Integration owns running this suite.
import { expect, test, type Page, type Route } from "@playwright/test";
import { execution, input, RUN, send, setup, SID } from "./fixture";
import { spark, vision } from "../../test/fixtures/models";

for (const width of [843, 1440]) {
  test(`live identity, capability, full disclosure and keyboard selection at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const c = await setup(page);
    const control = page.locator("[data-model-button]");
    await expect(control).toHaveAccessibleName(/Spark.*Effort: Medium/);
    await expect(control).toBeEnabled();
    /*
     * REWRITTEN 2026-09-20. The bounded "Message details" region is struck
     * along with the rest of the composer's narration of itself, and the
     * composer's model control is compact model-name text. Full identity and
     * capability remain in its `title` and in the open menu, while the creation
     * dialog still spells them out inline. What this
     * case checks is unchanged: the complete provider/model identity is
     * readable without opening anything, the catalog is navigable from the
     * keyboard alone, and choosing costs the draft and the transcript nothing.
     */
    await expect(control).toHaveAttribute("title", /local\/fake\/spark.*Text only/);
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
    await expect(control).toHaveAccessibleName(/Vision.*Effort: Medium/);
    await expect(control).toHaveAttribute("title", /local\/fake\/vision\/image.*Text \+ images/);
    await expect(control).toBeFocused();
    await expect(input(page)).toHaveValue("Draft survives model choice");
    await expect(recorded).toHaveAttribute("open", "");
    await expect(page.locator("[data-composer]")).toHaveAttribute("data-session-id", SID);
    expect(c.mutations).toEqual([{ path: `/sessions/${SID}/model`, body: { model: { provider_id: vision.provider_id, model_id: vision.model_id }, expected_model_revision: { epoch: "models-1", version: 0 } } }]);
    // The control itself is what must stay inside the chat column now that the
    // capability badge it used to carry lives in the open menu and title.
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
  const creationModel = creation.locator("[data-model-button]");
  await expect(creationModel).toContainText("Vision");
  await expect(creationModel).toHaveAttribute("title", /Proposed default: local\/fake\/vision\/image.*Text \+ images/);
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
  await expect(control).toHaveAccessibleName(/Vision.*Effort: Medium/, { timeout: 10_000 });
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
  await expect(page.locator("[data-model-button]")).toHaveAccessibleName(/Vision.*Effort: Medium/);
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

function providerDocument(rows: readonly Record<string, unknown>[], linked = false): Record<string, unknown> {
  return {
    status: "ok", providers: rows, config_path: "/synthetic/providers.json",
    config_exists: true, config_malformed: false, file_mode: "0600", file_mode_private: true,
    credential_allowlist: [], auth_source: linked ? "/synthetic/shared-auth.json" : null,
    auth_source_linked: linked, egress_acknowledged: [], adopted_sources: [],
    credential_sources: rows.filter(row => row.source === "project").map(row => ({
      provider_id: row.id, source: "project", at: "2026-09-24T00:00:00Z",
    })),
    attach: { attached: true, config_path: "/synthetic/providers.json", generation: 1 },
  };
}

const xaiRow = (): Record<string, unknown> => ({
  id: "xai", kind: "pi_native", name: "xAI", models: [{ id: "grok", name: "Grok" }],
  source: "none", health: "unused", last_observed_at: null, available: false,
  unavailable_reason: "provider_not_authenticated",
});
const anthropicRow = (): Record<string, unknown> => ({
  id: "anthropic", kind: "pi_native", name: "Anthropic",
  models: [{ id: "claude", name: "Claude" }], source: "none", health: "unused",
  last_observed_at: null, available: false, unavailable_reason: "provider_not_authenticated",
});
const providerCatalog = {
  status: "ok", catalog: [
    { id: "anthropic", name: "Anthropic", auth_methods: [{ type: "subscription", label: "Claude subscription" }],
      models: [{ id: "claude", name: "Claude", input: ["text"], reasoning: true }] },
    { id: "xai", name: "xAI", auth_methods: [{ type: "api_key", label: "xAI API key" }],
      models: [{ id: "grok", name: "Grok", input: ["text"], reasoning: true }] },
    { id: "amazon-bedrock", name: "Amazon Bedrock", auth_methods: [],
      models: [{ id: "nova", name: "Nova", input: ["text"], reasoning: false }] },
  ],
};

async function routeProviderApi(page: Page, handler: (route: Route, path: string) => Promise<void>): Promise<void> {
  await page.route("**/api/v1/providers**", async route => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    await handler(route, path);
  });
}

test("first API-key provider uses only supported methods and protects the secret", async ({ page }) => {
  const c = await setup(page);
  await input(page).fill("API add keeps this draft");
  const rows: Record<string, unknown>[] = [];
  const observed: { url: string; body: unknown }[] = [];
  await routeProviderApi(page, async (route, path) => {
    const request = route.request();
    if (request.method() === "GET" && path === "/providers/catalog") {
      await route.fulfill({ json: providerCatalog }); return;
    }
    if (request.method() === "GET" && path === "/providers") {
      await route.fulfill({ json: providerDocument(rows) }); return;
    }
    if (request.method() === "POST" && path === "/providers/register") {
      observed.push({ url: request.url(), body: request.postDataJSON() });
      rows.push(xaiRow());
      await route.fulfill({ json: { status: "ok", provider: { id: "xai", kind: "pi_native", models: [{ id: "grok" }] }, auth_type: "api_key" } }); return;
    }
    if (request.method() === "POST" && path === "/providers/xai/auth/key") {
      observed.push({ url: request.url(), body: request.postDataJSON() });
      rows[0] = { ...rows[0], source: "project", available: true, unavailable_reason: null };
      await route.fulfill({ json: { status: "ok", provider_id: "xai", scope: "project", replaced: "none" } }); return;
    }
    await route.fulfill({ status: 500, json: { status: "error", reason: "unexpected_provider_route", message: path } });
  });

  await page.locator("[data-model-button]").click();
  await page.locator("[data-add-provider]").click();
  await page.locator('[data-add-provider-method="api_key"]').click();
  await expect(page.locator('[data-add-provider-option="xai"]')).toBeFocused();
  await expect(page.locator('[data-add-provider-option="anthropic"]')).toHaveCount(0);
  await expect(page.locator('[data-add-provider-option="amazon-bedrock"]')).toHaveCount(0);
  await page.locator('[data-add-provider-option="xai"]').click();
  await page.locator("[data-signin-key]").fill("browser-synthetic-secret");
  await page.locator('[data-signin-scope="project"]').click();
  await page.locator("[data-signin-submit]").click();

  await expect(page.getByRole("group", { name: "Choose model" })).toBeVisible();
  await expect(page.locator("[data-model-button]")).toContainText("Spark");
  await expect(input(page)).toHaveValue("API add keeps this draft");
  expect(c.model.current).toEqual(spark);
  expect(observed).toHaveLength(2);
  expect(observed[1]?.body).toEqual({ key: "browser-synthetic-secret", scope: "project" });
  expect(observed.every(item => !item.url.includes("browser-synthetic-secret"))).toBe(true);
  await expect(page.locator("body")).not.toContainText("browser-synthetic-secret");
  expect(c.faults).toEqual([]);
});

test("subscription Back preserves focus and failed cancellation keeps the flow owned", async ({ page }) => {
  const c = await setup(page);
  await input(page).fill("Subscription add keeps this draft");
  const rows: Record<string, unknown>[] = [];
  let cancellations = 0;
  await routeProviderApi(page, async (route, path) => {
    const request = route.request();
    if (request.method() === "GET" && path === "/providers/catalog") {
      await route.fulfill({ json: providerCatalog }); return;
    }
    if (request.method() === "GET" && path === "/providers") {
      await route.fulfill({ json: providerDocument(rows) }); return;
    }
    if (request.method() === "POST" && path === "/providers/register") {
      rows.push(anthropicRow());
      await route.fulfill({ json: { status: "ok", provider: { id: "anthropic", kind: "pi_native", models: [{ id: "claude" }] }, auth_type: "subscription" } }); return;
    }
    if (request.method() === "POST" && path === "/providers/anthropic/auth/begin") {
      await route.fulfill({ json: { status: "ok", provider_id: "anthropic", type: "device_code", state: "authorization_pending",
        user_code: "SYNTHETIC", verification_uri: "https://provider.invalid/device", interval_seconds: 30 } }); return;
    }
    if (request.method() === "POST" && path === "/providers/anthropic/auth/cancel") {
      cancellations += 1;
      if (cancellations === 1) {
        await route.fulfill({ status: 503, json: { status: "error", reason: "agent_unavailable", message: "Synthetic sidecar unavailable" } }); return;
      }
      await route.fulfill({ json: { status: "ok", flow: { state: "cancelled" } } }); return;
    }
    await route.fulfill({ status: 500, json: { status: "error", reason: "unexpected_provider_route", message: path } });
  });

  await page.locator("[data-model-button]").click();
  await page.locator("[data-add-provider]").click();
  await expect(page.locator('[data-add-provider-method="subscription"]')).toBeFocused();
  await page.locator('[data-add-provider-method="subscription"]').click();
  await expect(page.locator('[data-add-provider-option="anthropic"]')).toBeFocused();
  await expect(page.locator('[data-add-provider-option="xai"]')).toHaveCount(0);
  await page.locator("[data-add-provider-back]").click();
  await expect(page.locator('[data-add-provider-method="subscription"]')).toBeFocused();
  await page.locator('[data-add-provider-method="subscription"]').click();
  await page.locator('[data-add-provider-option="anthropic"]').click();
  await page.locator('[data-signin-begin="auto"]').click();
  await expect(page.locator('[data-signin-device-code="SYNTHETIC"]')).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(page.locator("[data-signin-dialog]")).toBeVisible();
  await expect(page.locator("[data-signin-refusal]")).toContainText("no agent runtime");
  expect(cancellations).toBe(1);
  await page.keyboard.press("Escape");
  await expect(page.locator("[data-signin-dialog]")).toHaveCount(0);
  await expect(page.getByRole("group", { name: "Choose model" })).toBeVisible();
  await expect(page.locator("[data-model-button]")).toContainText("Spark");
  await expect(input(page)).toHaveValue("Subscription add keeps this draft");
  expect(c.model.current).toEqual(spark);
  expect(cancellations).toBe(2);
  expect(c.faults).toEqual([]);
});

test("completed subscription waits through busy-run finalization and preserves selection", async ({ page }) => {
  const c = await setup(page);
  const rows: Record<string, unknown>[] = [];
  let allowCompletion = false;
  await routeProviderApi(page, async (route, path) => {
    const request = route.request();
    if (request.method() === "GET" && path === "/providers/catalog") {
      await route.fulfill({ json: providerCatalog }); return;
    }
    if (request.method() === "GET" && path === "/providers") {
      await route.fulfill({ json: providerDocument(rows) }); return;
    }
    if (request.method() === "POST" && path === "/providers/register") {
      rows.push(anthropicRow());
      await route.fulfill({ json: { status: "ok", provider: { id: "anthropic", kind: "pi_native", models: [{ id: "claude" }] }, auth_type: "subscription" } }); return;
    }
    if (request.method() === "POST" && path === "/providers/anthropic/auth/begin") {
      await route.fulfill({ json: { status: "ok", provider_id: "anthropic", type: "device_code", state: "authorization_pending",
        user_code: "BUSY-RUN", verification_uri: "https://provider.invalid/device", interval_seconds: 0.05 } }); return;
    }
    if (request.method() === "GET" && path === "/providers/anthropic/auth/status") {
      if (!allowCompletion) {
        await route.fulfill({ status: 409, json: { status: "error", reason: "runs_in_flight", message: "Applying would end one run", count: 1 } }); return;
      }
      rows[0] = { ...rows[0], source: "project", available: true, unavailable_reason: null };
      await route.fulfill({ json: { status: "ok", provider_id: "anthropic", state: "project", type: "oauth", flow: { state: "complete" } } }); return;
    }
    await route.fulfill({ status: 500, json: { status: "error", reason: "unexpected_provider_route", message: path } });
  });

  await page.locator("[data-model-button]").click();
  await page.locator("[data-add-provider]").click();
  await page.locator('[data-add-provider-method="subscription"]').click();
  await page.locator('[data-add-provider-option="anthropic"]').click();
  await page.locator('[data-signin-begin="auto"]').click();
  await expect(page.locator("[data-signin-refusal]")).toContainText("turn is running");
  await expect(page.locator("[data-signin-dialog]")).toBeVisible();
  allowCompletion = true;
  await expect(page.locator("[data-signin-dialog]")).toHaveCount(0);
  await expect(page.locator("[data-model-button]")).toContainText("Spark");
  expect(c.model.current).toEqual(spark);
  expect(c.faults).toEqual([]);
});

test("linked credential source keeps its explicit management path in Add provider", async ({ page }) => {
  const c = await setup(page);
  await routeProviderApi(page, async (route, path) => {
    if (route.request().method() === "GET" && path === "/providers/catalog") {
      await route.fulfill({ json: providerCatalog }); return;
    }
    if (route.request().method() === "GET" && path === "/providers") {
      await route.fulfill({ json: providerDocument([], true) }); return;
    }
    await route.fulfill({ status: 500, json: { status: "error", reason: "unexpected_provider_route", message: path } });
  });
  await page.locator("[data-model-button]").click();
  await page.locator("[data-add-provider]").click();
  await expect(page.locator("[data-add-provider-linked]")).toBeVisible();
  await page.locator("[data-add-provider-linked] button").click();
  await expect(page.locator("[data-model-providers]")).toBeVisible();
  expect(c.model.current).toEqual(spark);
  expect(c.faults).toEqual([]);
});

test("active and awaiting-answer turns keep model readable and disable selection", async ({ page }) => {
  const c = await setup(page, execution(RUN));
  await c.frame("question", { question_id: "synthetic-model-question", question: "Continue?", options: ["Yes", "No"], multi: false, allow_free_text: false }, 0);
  const control = page.locator("[data-model-button]");
  await expect(control).toHaveAccessibleName(/Spark.*Effort: Medium/);
  await expect(control).toBeDisabled();
  await control.press("Enter");
  await expect(page.getByRole("dialog", { name: "Choose model" })).toHaveCount(0);
  expect(c.mutations).toEqual([]);
  c.execution = execution(RUN, "completed");
  c.model = { ...c.model, current: null, selected: { provider_id: spark.provider_id, model_id: spark.model_id }, state: "unavailable", reason: "model_unknown", revision: { ...c.model.revision, version: 1 } };
  await expect(control).toHaveAccessibleName(/spark.*Effort: Medium/, { timeout: 10_000 });
  await expect(control).toHaveAttribute("title", /Saved selection.*spark.*Capability unknown/);
  await expect(control).toBeEnabled(); await expect(send(page)).toBeDisabled();
  await expect(page.getByText("Recorded narration stays visible.")).toBeVisible();
  expect(c.mutations).toEqual([]); expect(c.faults).toEqual([]);
});
