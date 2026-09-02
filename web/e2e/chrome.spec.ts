// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Export / BOM chrome bound to the on-screen pin (issue #12). Expected values
// come from the server in the same run. No assertion is on UI copy.

import { expect, test } from "@playwright/test";
import { archive } from "./harness/archive";
import { api, open, route } from "./harness/world";

const PART = "tread";

interface PropertiesDocument {
  readonly properties: Readonly<Record<string, string>>;
  readonly fields: readonly string[];
  readonly source: string;
  readonly build_artifact_ref: string | null;
}

interface BuildDocument {
  readonly status: string;
  readonly artifact_ref: string;
}

test("Export and BOM sit in header chrome, not only the inspector", async ({ page }, testInfo) => {
  await open(page, route(PART, { tab: "viewport" }));
  await expect(page.locator("[data-part-chrome]")).toBeVisible();
  await expect(page.locator("[data-chrome-export]")).toBeVisible();
  await expect(page.locator("[data-chrome-bom]")).toBeVisible();
  // Signed-in header: the token is the fragment / sessionStorage, not a chip.
  await expect(page.locator("header [data-token-state]")).toHaveCount(0);
  // The inspector export tab still exists; chrome is in addition to it.
  await expect(page.locator('[data-inspector-tab="export"]')).toBeVisible();
  await expect(page.locator('[data-inspector-tab="sourcing"]')).toBeVisible();
  await archive(page, testInfo, "export-bom-chrome");
});

test("Export and BOM are icon+word at ≥1280px, icon-only below, same name (§4.1(i) C26)", async ({
  page,
}) => {
  await open(page, route(PART, { tab: "viewport" }));
  const controls = ["[data-chrome-export]", "[data-chrome-bom]"] as const;

  await page.setViewportSize({ width: 1440, height: 800 });
  const wordedNames: string[] = [];
  for (const selector of controls) {
    const control = page.locator(selector);
    await expect(control).toBeVisible();
    await expect(control.locator("svg[data-icon]")).toHaveCount(1);
    // A visible text node equal to the control's accessible name.
    const word = ((await control.textContent()) ?? "").trim();
    expect(word).not.toBe("");
    expect(await control.getAttribute("aria-label")).toBeNull();
    wordedNames.push(word);
  }

  await page.setViewportSize({ width: 1200, height: 800 });
  for (const [index, selector] of controls.entries()) {
    const control = page.locator(selector);
    // Still visible, unmoved behind no overflow — icon-only, word on the name.
    await expect(control).toBeVisible();
    await expect(control.locator("svg[data-icon]")).toHaveCount(1);
    expect(((await control.textContent()) ?? "").trim()).toBe("");
    // C26's testable: the accessible name is identical in both forms.
    expect(await control.getAttribute("aria-label")).toBe(wordedNames[index]);
  }
});

test("chrome Export is bound to the pin the server named", async ({ page }, testInfo) => {
  const build = await api<BuildDocument>(`/parts/${PART}/build`);
  expect(build.artifact_ref).toMatch(/^artifact:build:/);

  await open(page, route(PART, { tab: "viewport" }));
  await page.locator("[data-chrome-export]").click();
  await expect(page.locator("[data-panel='export-chrome']")).toBeVisible();

  await expect(
    page.locator("[data-panel='export-chrome'] [data-source='workspace.artifact_ref']"),
  ).toHaveAttribute("data-value", build.artifact_ref);

  const formats = await page
    .locator("[data-panel='export-chrome'] button[data-export-format]")
    .evaluateAll((nodes) => nodes.map((node) => node.getAttribute("data-export-format")));
  expect(formats).toEqual(["step", "dxf", "svg", "gltf", "3mf", "stl"]);

  await archive(page, testInfo, "export-chrome-pin");
});

test("chrome BOM shows declared process / stock / material spec from GET properties", async ({
  page,
}, testInfo) => {
  const document = await api<PropertiesDocument>(`/parts/${PART}/properties`);
  const sourcing = ["process", "stock_form", "blank_size", "material_spec"] as const;
  const declared = sourcing.filter((field) => field in document.properties);

  await open(page, route(PART, { tab: "viewport" }));
  await page.locator("[data-chrome-bom]").click();
  await expect(page.locator("[data-chrome-dialog='sourcing'] [data-panel='sourcing']")).toBeVisible();

  const fields = await page
    .locator("[data-chrome-dialog='sourcing'] [data-field]")
    .evaluateAll((nodes) => nodes.map((node) => node.getAttribute("data-field")));
  expect([...fields].sort()).toEqual([...declared].sort());
  expect(fields).not.toContain("description");
  expect(fields).not.toContain("finish");

  for (const field of declared) {
    const fact = page.locator(
      `[data-chrome-dialog='sourcing'] [data-source="properties.${field}"]`,
    );
    await expect(fact).toHaveAttribute("data-value", document.properties[field] ?? "");
  }

  await expect(page.locator("[data-sourcing-catalog='none']").first()).toBeVisible();
  await archive(page, testInfo, "sourcing-chrome");
});
