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

test("Script / Timeline / Results are first-class stage tabs", async ({ page }, testInfo) => {
  await open(page, route(PART, { tab: "script" }));
  await expect(page.locator('[data-stage-tab="script"]')).toHaveAttribute("aria-selected", "true");
  await expect(page.locator('[data-panel="script"]')).toBeVisible();
  await expect(page.locator('[data-stage-tab="timeline"]')).toBeVisible();
  await expect(page.locator('[data-stage-tab="results"]')).toBeVisible();

  await page.locator('[data-stage-tab="timeline"]').click();
  await expect(page.locator('[data-panel="timeline"]')).toBeVisible();
  await expect(page).toHaveURL(/tab=timeline/);

  await page.locator('[data-stage-tab="results"]').click();
  await expect(page.locator('[data-stage-panel="results"] [data-panel="results"]')).toBeVisible();
  await expect(page).toHaveURL(/tab=results/);

  await archive(page, testInfo, "part-views-tabs");
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
