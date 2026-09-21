// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Part views: Script / Timeline / Results, and PARAMS sliders bound to
// `GET /parts/{part}/params`. Expected values come from the server in the
// same run. No assertion is on UI copy.

import { expect, test } from "@playwright/test";
import { archive } from "./harness/archive";
import { api, open, route } from "./harness/world";

const PART = "tread";

interface ParamRow {
  readonly name: string;
  readonly value: number;
  readonly default: number;
  readonly min: number;
  readonly max: number;
  readonly step: number | null;
  readonly scope: string;
}

interface ParamsDocument {
  readonly status: string;
  readonly params: readonly ParamRow[];
  readonly state_hash: string;
}

/*
 * REWRITTEN 2026-09-20. The stage's tab STRIP is struck. Script, Timeline and
 * Results are all still first-class views of the part and all still routed by
 * `tab=`; what changed is where each is reached from, and the split is by what
 * the thing IS rather than by where it used to sit:
 *
 *   - EDITORS take the stage. Script is a toggle in the header, beside the pin
 *     whose artifact its source produced; Diff sits at the foot of the view
 *     rail. Both keep `[data-stage-tab]`, so a gate that addressed them by
 *     name still finds them — as toggles, carrying `aria-pressed`, because a
 *     tab that is the only member of its strip is a switch.
 *   - READOUTS take a panel. Timeline is one of the side panel's four
 *     disclosures now, not a stage view you have to leave the model to read.
 *   - Results keeps both homes, and the rule that there is only ever ONE of it
 *     is unchanged: the inspector must not mount a second list while the stage
 *     is showing one.
 */
test("Script and Diff take the stage; Timeline reads in the panel; Results is never drawn twice", async ({
  page,
}, testInfo) => {
  await open(page, route(PART, { tab: "script" }));
  const script = page.locator('[data-stage-tab="script"]');
  await expect(script).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator('[data-panel="script"]')).toBeVisible();
  await expect(page.locator('[data-stage-tab="diff"]')).toBeVisible();
  // The strip is struck: Timeline and Results are not controls on the stage.
  await expect(page.locator('[data-stage-tab="timeline"]')).toHaveCount(0);
  await expect(page.locator('[data-stage-tab="results"]')).toHaveCount(0);

  // Timeline reads in the side panel, where the other readouts are.
  await page.locator('[data-panel-toggle="timeline"]').click();
  await expect(page.locator('[data-panel-body="timeline"] [data-panel="timeline"]')).toBeVisible();
  // …and reading it does not navigate: the stage is still the script.
  await expect(page).toHaveURL(/tab=script/);
  await expect(page.locator('[data-panel="script"]')).toBeVisible();

  // Results on the stage is the one ResultsPanel; the inspector must not also
  // mount it — that was the duplicate list/metrics after #6.
  await open(page, route(PART, { tab: "results" }));
  await expect(page.locator('[data-stage-panel="results"] [data-panel="results"]')).toBeVisible();
  await expect(page).toHaveURL(/tab=results/);
  await expect(page.locator('[data-inspector-panel="results"]')).toHaveCount(0);
  await expect(page.locator('[data-inspector-tab="results"]')).toHaveCount(0);

  await archive(page, testInfo, "part-views-tabs");
});

test("the project tree lists the closed sections even when empty", async ({ page }, testInfo) => {
  await open(page, route(PART));
  const ids = ["analyses", "docs", "globals", "imports", "materials"] as const;
  for (const id of ids) {
    const row = page.locator(`[data-tree-row="section"][data-tree-section="${id}"]`);
    await expect(row).toBeVisible();
    await expect(row).toHaveAttribute("aria-expanded", "false");
  }
  await expect(page.locator("[data-tree-section-empty]")).toHaveCount(0);
  // §13.1: the working tree stays a fact. Expanding a section must not hide
  // dirty rows, and this page still addresses them with the same selector.
  await page.locator('[data-tree-section="materials"]').click();
  await expect(page.locator('[data-tree-section-empty="materials"]')).toBeVisible();
  await expect(
    page.locator('[data-tree-section-empty="materials"] [data-source]'),
  ).toHaveCount(0);

  await archive(page, testInfo, "project-tree-sections");
});

test("PARAMS sliders are the GET /parts/{part}/params projection", async ({ page }, testInfo) => {
  const document = await api<ParamsDocument>(`/parts/${PART}/params`);
  expect(document.status).toBe("ok");
  expect(document.params.length).toBeGreaterThan(0);

  await open(page, route(PART, { tab: "script" }));
  await expect(page.locator('[data-panel="params"]')).toBeVisible();

  const names = await page.locator("[data-param]").evaluateAll((nodes) =>
    nodes.map((node) => node.getAttribute("data-param")),
  );
  expect(names).toEqual(document.params.map((row) => row.name));

  const value = page.locator('[data-panel="params"] [data-source="params[].value"]').first();
  await expect(value).toHaveAttribute("data-value", String(document.params[0]?.value));
  await expect(page.locator('[data-panel="params"] [data-source="params.state_hash"]')).toHaveAttribute(
    "data-value",
    document.state_hash,
  );
  await expect(page.locator(`[data-param-slider="${document.params[0]?.name ?? ""}"]`)).toBeVisible();

  await archive(page, testInfo, "params-sliders");
});
