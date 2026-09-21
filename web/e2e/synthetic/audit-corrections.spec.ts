// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
import { expect, test, type Locator, type Page } from "@playwright/test";
import { setup, SID, OTHER, RUN, execution, input, modelName, send } from "./fixture";

/*
 * REWRITTEN 2026-09-20, because its operands were struck and its clause was
 * not. The case used to open the context disclosure, expand "Full model
 * identity", and check the composer's core controls stayed readable around
 * the grown panel. The disclosure, the summary line and the composed-block
 * preview were all removed from the composer on operator request.
 *
 * What it was protecting survives and still has a way to be provoked: a
 * composer that GROWS must keep its controls inside the form, keep the input
 * usable, leave the transcript room, and never overflow the page. A long
 * multi-line draft grows it, which is what this now uses.
 */
for (const width of [1440, 1280, 1024, 843]) test(`refinement: a grown composer keeps readable composition and no-write controls at ${width}`, async ({ page }) => {
  await page.setViewportSize({ width, height: width === 1440 ? 1000 : 800 });
  const c = await setup(page);
  const draft = Array.from({ length: 8 }, (_, n) => `Line ${n + 1}: inspect the evidence; do not change the design.`).join("\n");
  await input(page).fill(draft);
  const checkCore = async () => {
    const form = (await page.locator("[data-composer]").boundingBox())!;
    // `[data-composer-hint]` is NOT in this list, and that is a finding rather
    // than an omission. It is screen-reader-only now — `.hint` is the 1px
    // clipped box `.srOnly` is — so `bounded()`'s "its text is not clipped
    // inside it" check can never pass for it. The sentence is not lost: Send
    // carries the same string on `title`. It is asserted below as what it is.
    for (const selector of ["[data-model-button]", "[data-composer-input-row]", "[data-composer-send]"]) {
      await bounded(page.locator(selector), width, width === 1440 ? 1000 : 800);
      const box = (await page.locator(selector).boundingBox())!;
      expect(box.y).toBeGreaterThanOrEqual(form.y);
      expect(box.y + box.height).toBeLessThanOrEqual(form.y + form.height + 1);
    }
    expect((await input(page).boundingBox())!.height).toBeGreaterThan(65);
    expect((await page.locator("[data-transcript-scroll]").boundingBox())!.height).toBeGreaterThan(120);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    // The hint is present and reachable, and its sentence is on Send too.
    await expect(page.locator("[data-composer-hint]")).toHaveCount(1);
    expect(await page.locator("[data-composer-hint]").evaluate((el) => el.clientWidth)).toBeLessThan(4);
    await expect(page.locator("[data-composer-send]")).toHaveAttribute("title", /./);
  };
  await checkCore();
  // Caret to the end of a long draft: the box scrolls its own text rather
  // than growing past the column.
  await input(page).focus();
  await page.keyboard.press("End");
  await checkCore();
  // A model/execution read is uncertain until reconciled, not an excuse to send.
  c.execution = execution(RUN);
  await c.frame("text_delta", { text: "Working on the explicit fixture task." }, 0);
  await expect(send(page)).toBeDisabled();
  await checkCore();
  await input(page).press("Enter");
  await send(page).focus();
  await page.keyboard.press("Enter");
  await expect(input(page)).toHaveValue(draft);
  await expect(page.locator("[data-composer-cancel]")).toBeVisible();
  // C25 (2026-09-20): no collapse to hide and reveal through. The draft must
  // still be the composer's own state rather than something a reveal restores.
  await expect(input(page)).toHaveValue(draft);
  // `/context/preview` had no caller left once the disclosure went, so the
  // filter that used to excuse it would now hide a real mutation.
  expect(c.mutations).toEqual([]);
  expect(c.faults).toEqual([]);
});

async function switchTo(page: Page, sid: string) {
  await page.locator("[data-session-switch]").click();
  await page.locator(`[data-session-option="${sid}"]`).click();
  await expect(page.locator("[data-composer]")).toHaveAttribute("data-session-id", sid);
}
async function bounded(target: Locator, width: number, height: number) {
  const box = await target.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.y).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(width);
  expect(box!.y + box!.height).toBeLessThanOrEqual(height);
  // A bounded wrapper is not sufficient if its text is still clipped inside it.
  expect(await target.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
}

for (const width of [1440, 1024, 843]) test(`audit: complete scope choices and focus remain onscreen at ${width}`, async ({ page }) => {
  await page.setViewportSize({ width, height: 800 });
  const c = await setup(page);
  await input(page).fill("Cancel must retain this draft");
  const route = new URL(page.url()).hash;
  for (const scope of ["Project", "bracket"]) {
    await page.getByRole("button", { name: "New conversation", exact: true }).click();
    const menu = page.locator("[data-session-create-open]");
    await bounded(menu, width, 800);
    const project = menu.getByRole("button", { name: "New conversation", exact: true });
    const part = menu.getByRole("button", { name: "Ask about bracket", exact: true });
    await bounded(project, width, 800);
    await bounded(part, width, 800);
    await expect(project).toBeFocused();
    if (scope === "bracket") {
      await page.keyboard.press("Tab");
      await expect(part).toBeFocused();
      await page.keyboard.press("Enter");
    } else await project.click();
    const dialog = page.getByRole("dialog", { name: `New conversation · ${scope}`, exact: true });
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
    await expect(page.locator("[data-session-create-menu]")).toBeFocused();
    await expect(input(page)).toHaveValue("Cancel must retain this draft");
    expect(new URL(page.url()).hash).toBe(route);
  }
  const longPart = "long-part-name-".repeat(24);
  await page.evaluate(({ sid, part }) => { location.hash = `#/p/${part}?s=${sid}`; }, { sid: SID, part: longPart });
  await page.locator("[data-session-create-menu]").click();
  await bounded(page.locator("[data-session-create-open]"), width, 800);
  const longChoice = page.getByRole("button", { name: `Ask about ${longPart}`, exact: true });
  await bounded(longChoice, width, 800);
  await page.keyboard.press("Tab");
  await expect(longChoice).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.locator("[data-session-create-menu]")).toBeFocused();
  expect(c.mutations).toEqual([]);
  expect(c.faults).toEqual([]);
});

/*
 * REWRITTEN 2026-09-20. The per-member exclusion UI is struck: there is no
 * context disclosure and no `[data-context-drop]` chip, because the composer
 * no longer narrates the envelope it is about to send. ONE exclusion control
 * survives, and it is the one that changes what the agent is told about the
 * picture — `[data-context-add-view]`, which drops `view` (and `selection`
 * with it) when it is switched off and puts them back when it is switched on.
 *
 * Everything this case was protecting is unchanged and is asserted against
 * that control: an exclusion is SESSION-OWNED, it survives a keyboard reveal
 * and a route round-trip, it costs no mutation, and one explicit Send writes
 * exactly one prompt whose body no later edit can rewrite. The envelope's
 * member list is read from `[data-composer]`, which is where
 * `data-context-keys` is minted now that the line that carried it is gone.
 */
const keysOf = (page: Page) => page.locator("[data-composer]").getAttribute("data-context-keys");
const viewToggle = (page: Page) => page.locator("[data-context-add-view]");

for (const width of [1440, 843]) test(`audit: a session-owned exclusion survives a keyboard reveal and one explicit send at ${width}`, async ({ page }) => {
  await page.setViewportSize({ width, height: 800 });
  const c = await setup(page);
  await expect(page.locator("[data-model-button]")).toHaveAccessibleName(/Current model/);
  await input(page).fill("Retain session A draft");
  const model = await modelName(page);
  const route = new URL(page.url()).hash;
  await expect(viewToggle(page)).toHaveAttribute("aria-pressed", "true");
  await viewToggle(page).click();
  await expect(viewToggle(page)).toHaveAttribute("aria-pressed", "false");
  const keys = (await keysOf(page))!;
  expect(keys).not.toContain("view");
  // C25 (2026-09-20): the "open" arm revealed a collapsed column and is struck
  // with it. Skip remains, and is now the only way focus is moved into the
  // composer without a route edit — which is the half this loop was for.
  // Tab to the actual skip link, not a route edit or a programmatic reveal.
  for (let n = 0; n < 30; n++) {
    await page.keyboard.press("Tab");
    if (await page.getByRole("link", { name: "Skip to composer" }).evaluate(el => el === document.activeElement)) break;
  }
  await expect(page.getByRole("link", { name: "Skip to composer" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(input(page)).toBeFocused();
  await expect(input(page)).toHaveValue("Retain session A draft");
  expect(await keysOf(page)).toBe(keys);
  await expect(viewToggle(page)).toHaveAttribute("aria-pressed", "false");
  expect(await modelName(page)).toBe(model);
  expect(new URL(page.url()).hash).toBe(route);

  await switchTo(page, OTHER);
  // The exclusion belongs to session A, not to the tab.
  await expect(viewToggle(page)).toHaveAttribute("aria-pressed", "true");
  expect(await keysOf(page)).toContain("view");
  await input(page).fill("Independent session B draft");
  await viewToggle(page).click();
  await expect(viewToggle(page)).toHaveAttribute("aria-pressed", "false");
  await switchTo(page, SID);
  expect(await keysOf(page)).toBe(keys);
  await expect(input(page)).toHaveValue("Retain session A draft");
  expect(c.mutations).toEqual([]);

  await expect(send(page)).toBeEnabled();
  await send(page).click();
  await expect.poll(() => c.pending !== null).toBe(true);
  const writes = c.mutations;
  expect(writes).toHaveLength(1);
  expect(writes[0]!.path).toBe(`/sessions/${SID}/prompt`);
  // The exclusion is on the wire, not just on the screen: an operator who has
  // shaped the envelope gets an EXPLICIT context — `view` absent because they
  // switched it off — rather than the `null` that means "whatever the
  // workspace implies". The three per-message settings ride with it
  // (2026-09-20); they are explicit prompt members, so a body that omitted
  // them would be a body the server had to guess at.
  expect(writes[0]!.body).toEqual({ text: "Retain session A draft",
    context: { part: "bracket", stage_tab: "viewport", inspector_tab: "results" },
    expected_model_revision: c.model.revision,
    interaction_mode: "modeling", dfm_mode: "off", thinking_level: "medium" });
  await input(page).fill("Newer unsent draft");
  await viewToggle(page).click(); // put the view back, AFTER the send
  await expect(viewToggle(page)).toHaveAttribute("aria-pressed", "true");
  await switchTo(page, OTHER);
  await expect(viewToggle(page)).toHaveAttribute("aria-pressed", "false");
  await expect(input(page)).toHaveValue("Independent session B draft");
  // Later context edits and switching cannot rewrite the already submitted body.
  expect(c.pending!.request().postDataJSON()).toEqual(writes[0]!.body);
  await c.release();
  await switchTo(page, SID);
  await expect(input(page)).toHaveValue("Newer unsent draft");
  expect(c.mutations).toEqual(writes);
  expect(c.faults).toEqual([]);
});

/*
 * REWRITTEN 2026-09-20, same strike as the case above. The `part` drop and the
 * disclosure it was made through are gone; what made the envelope EXPLICIT is
 * not. Switching the view toggle off and on again puts `view` in the `added`
 * set — the operator asked for it rather than inheriting it — which is the
 * state this case exists to follow through a session-less draft into the
 * session its first Send creates.
 */
test("audit: an explicitly added view survives the first-send creation without leaking to another session", async ({ page }) => {
  const c = await setup(page);
  await page.route("**/api/v1/sessions", route => route.request().method() === "GET" && c.created === null
    ? route.fulfill({ json: { status: "ok", sessions: [], profiles: [] } }) : route.fallback());
  await page.goto("about:blank");
  await page.goto("/#/p/bracket");
  await expect(page.locator("[data-composer]")).toHaveAttribute("data-session-id", "");
  await input(page).fill("Explicit view-only first request");
  await viewToggle(page).click();
  await expect(viewToggle(page)).toHaveAttribute("aria-pressed", "false");
  await viewToggle(page).click();
  await expect(viewToggle(page)).toHaveAttribute("aria-pressed", "true");
  const keys = "part stage_tab inspector_tab view";
  expect(await keysOf(page)).toBe(keys);
  // C25 (2026-09-20) — COVERAGE LOST, recorded rather than quietly dropped.
  //
  // This step used to hide and reveal the Stream, which unmounted `StreamPanel`
  // while the module-level conversation store survived, proving the envelope
  // was STORE state and not component state. With the collapse struck there is
  // no UI path that unmounts the composer for a session-less draft: the aside
  // always renders `<StreamPanel />`, and the session round-trip that replaces
  // this elsewhere needs a switcher, which a no-session page does not draw.
  //
  // A full reload is not a substitute — the store is in-memory, so it would
  // assert the opposite. What survives is the envelope's stability across the
  // steps that remain, and the first-send assertions below, which are the ones
  // that actually catch leakage into another session.
  expect(await keysOf(page)).toBe(keys);
  expect(c.mutations).toEqual([]);
  await expect(send(page)).toBeEnabled();
  await send(page).click();
  await expect.poll(() => c.pending !== null).toBe(true);
  await expect(page.locator("[data-composer]")).toHaveAttribute("data-session-id", "synthetic-created");
  expect(await keysOf(page)).toBe(keys);
  expect(c.mutations.map(r => r.path)).toEqual(["/sessions", "/sessions/synthetic-created/prompt"]);
  expect(c.pending!.request().postDataJSON()).toEqual({ text: "Explicit view-only first request",
    context: { part: "bracket", stage_tab: "viewport", inspector_tab: "results", view: "iso" },
    expected_model_revision: c.created!.model_state.revision,
    interaction_mode: "modeling", dfm_mode: "off", thinking_level: "medium" });
  await c.release();
  await switchTo(page, SID);
  // The other session never saw the toggle: its envelope is the implied one.
  await expect(viewToggle(page)).toHaveAttribute("aria-pressed", "true");
  expect(await keysOf(page)).toBe("part stage_tab inspector_tab view");
  expect(c.faults).toEqual([]);
});
