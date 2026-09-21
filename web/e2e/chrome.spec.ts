// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Export / BOM bound to the on-screen pin (issue #12). Expected values come
// from the server in the same run. No assertion is on UI copy.
//
// REWRITTEN 2026-09-20. These cases drove the HEADER's Export and BOM, which
// are struck (§4.1(i)) along with `PartChrome`/`ExportChrome`: the dialog ran
// the same submission hook as the Export tab over a strict subset of its
// surface, and BOM mounted the very component the Sourcing tab mounts. Every
// clause below is the same clause, addressed to the drawer that kept the
// capability — pin-bound formats, the declared sourcing field set, on-screen
// containment and a body that scrolls instead of a panel that overflows.

import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, test, type Locator, type Page } from "@playwright/test";
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

/** Open one inspector tab and return its panel. */
async function inspectorTab(page: Page, tab: "export" | "sourcing"): Promise<Locator> {
  await page.locator(`[data-inspector-tab="${tab}"]`).click();
  const panel = page.locator(`[data-inspector-panel="${tab}"]`);
  await expect(panel).toBeVisible();
  return panel;
}

test("Export and BOM are the drawer's, and the header grows no second door to them", async ({
  page,
}, testInfo) => {
  await open(page, route(PART, { tab: "viewport" }));
  // The strike is the assertion: neither control, and no chrome to hold them.
  for (const gone of ["[data-part-chrome]", "[data-chrome-export]", "[data-chrome-bom]"]) {
    await expect(page.locator(gone), `${gone} is back in the header`).toHaveCount(0);
  }
  // Signed-in header: the token is the fragment / sessionStorage, not a chip.
  await expect(page.locator("header [data-token-state]")).toHaveCount(0);
  // And the capability is reachable, on one surface each.
  await expect(page.locator('[data-inspector-tab="export"]')).toBeVisible();
  await expect(page.locator('[data-inspector-tab="sourcing"]')).toBeVisible();
  await expect((await inspectorTab(page, "export")).locator("[data-panel='export']")).toBeVisible();
  await expect((await inspectorTab(page, "sourcing")).locator("[data-panel='sourcing']")).toBeVisible();
  await archive(page, testInfo, "export-bom-drawer");
});

test("Export is bound to the pin the server named", async ({ page }, testInfo) => {
  const build = await api<BuildDocument>(`/parts/${PART}/build`);
  expect(build.artifact_ref).toMatch(/^artifact:build:/);

  await open(page, route(PART, { tab: "viewport" }));
  const panel = await inspectorTab(page, "export");

  await expect(panel.locator("[data-source='workspace.artifact_ref']")).toHaveAttribute(
    "data-value",
    build.artifact_ref,
  );

  const formats = await panel
    .locator("button[data-export-format]")
    .evaluateAll((nodes) => nodes.map((node) => node.getAttribute("data-export-format")));
  expect(formats).toEqual(["step", "dxf", "svg", "gltf", "3mf", "stl"]);

  await archive(page, testInfo, "export-pin");
});

test("BOM shows declared process / stock / material spec from GET properties", async ({
  page,
}, testInfo) => {
  const document = await api<PropertiesDocument>(`/parts/${PART}/properties`);
  const sourcing = ["process", "stock_form", "blank_size", "material_spec"] as const;
  const declared = sourcing.filter((field) => field in document.properties);

  await open(page, route(PART, { tab: "viewport" }));
  const panel = await inspectorTab(page, "sourcing");

  const fields = await panel
    .locator("[data-field]")
    .evaluateAll((nodes) => nodes.map((node) => node.getAttribute("data-field")));
  expect([...fields].sort()).toEqual([...declared].sort());
  expect(fields).not.toContain("description");
  expect(fields).not.toContain("finish");

  for (const field of declared) {
    await expect(panel.locator(`[data-source="properties.${field}"]`)).toHaveAttribute(
      "data-value",
      document.properties[field] ?? "",
    );
  }

  await expect(page.locator("[data-sourcing-catalog='none']").first()).toBeVisible();
  await archive(page, testInfo, "sourcing-drawer");
});

// --------------------------------------------------------------------------
// B-8 — the sourcing surface fits the viewport, with scrolling, and its value
// column is readable (audit-2026-09-04-broken.md B-8).
//
// The case above already asserts the surface is "visible" — and a box at
// y=-919 satisfies a visibility check. These cases assert the two facts that
// check missed: the box is actually ON screen, and its value cells actually
// have width. The subject moved from the struck BOM dialog to the drawer panel
// that replaced it; the defect class is the same one, and a drawer is exactly
// as able to render its body taller than the window.

interface Box {
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
}

async function requireBox(locator: Locator): Promise<Box> {
  const box = await locator.boundingBox();
  if (box === null) throw new Error("element has no box (not visible / not rendered)");
  return box;
}

/** The `[data-field]`/`[data-metric]` row's VALUE cell — DataTable's 2nd child. */
function valueCells(host: Locator): Locator {
  return host.locator("[data-field] > *:nth-child(2), [data-metric] > *:nth-child(2)");
}

async function assertContained(page: Page, host: Locator, label: string): Promise<Box> {
  const viewport = page.viewportSize();
  if (viewport === null) throw new Error("no viewport size");
  const box = await requireBox(host);
  expect(box.y, `${label}: top is off-screen (${JSON.stringify(box)})`).toBeGreaterThanOrEqual(0);
  expect(
    box.y + box.height,
    `${label}: bottom exceeds the ${String(viewport.height)}px viewport (${JSON.stringify(box)})`,
  ).toBeLessThanOrEqual(viewport.height);
  return box;
}

test("the sourcing panel stays on screen and its value column is readable, at 1280 and 1920 (B-8)", async ({
  page,
}, testInfo) => {
  for (const width of [1280, 1920]) {
    await page.setViewportSize({ width, height: 900 });
    await open(page, route(PART, { tab: "viewport" }));
    const panel = await inspectorTab(page, "sourcing");
    const panelBox = await assertContained(page, panel, `Sourcing @ ${String(width)}px`);

    const cells = valueCells(panel);
    const count = await cells.count();
    expect(count, `${String(width)}px: no value cells rendered at all`).toBeGreaterThan(0);
    for (let i = 0; i < count; i += 1) {
      const cellBox = await requireBox(cells.nth(i));
      expect(cellBox.width, `${String(width)}px: value cell ${String(i)} is zero-width`).toBeGreaterThan(0);
      expect(
        cellBox.x,
        `${String(width)}px: value cell ${String(i)} starts left of the panel`,
      ).toBeGreaterThanOrEqual(panelBox.x);
      expect(
        cellBox.x + cellBox.width,
        `${String(width)}px: value cell ${String(i)} extends past the panel's right edge`,
      ).toBeLessThanOrEqual(panelBox.x + panelBox.width + 1);
    }
  }
  await archive(page, testInfo, "sourcing-contained");
});

test("the containment contract holds for the Export panel too, not only the one that broke (B-8)", async ({
  page,
}) => {
  await open(page, route(PART, { tab: "viewport" }));
  await assertContained(page, await inspectorTab(page, "export"), "Export");
});

test("at a deliberately short viewport, the sourcing body scrolls rather than the panel overflowing (B-8)", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 420 });
  await open(page, route(PART, { tab: "viewport" }));
  const panel = await inspectorTab(page, "sourcing");
  await assertContained(page, panel, "Sourcing @ 420px tall");

  const body = panel.locator("[data-overlay-scroll]").first();
  const overflow = await body.evaluate((el) => ({
    scrollHeight: el.scrollHeight,
    clientHeight: el.clientHeight,
  }));
  expect(
    overflow.scrollHeight,
    `panel body did not overflow at all (${JSON.stringify(overflow)}) — this case wants a short ` +
      "window where the fixture's fields do not fit, to guard against a 1600x1000 fixture passing by luck",
  ).toBeGreaterThan(overflow.clientHeight);
});

test("no inspector tab's first grid track eats the value column (B-8, the seven-panel half of the fix)", async ({
  page,
}, testInfo) => {
  await open(page, route(PART, { tab: "viewport" }));
  // `provenance` left the strip (2026-09-20): the tab is filtered out of
  // `inspectorTabsFor`, so clicking it here would wait on nothing.
  const tabs = ["properties", "checks", "sourcing"] as const;
  const rows: string[] = [];
  let checkedAny = false;

  for (const tab of tabs) {
    await page.locator(`[data-inspector-tab="${tab}"]`).click();
    const panel = page.locator(`[data-panel="${tab}"]`);
    await expect(panel).toBeVisible();
    const panelBox = await requireBox(panel);
    const labels = panel.locator("[data-field] > *:first-child, [data-metric] > *:first-child");
    const labelCount = await labels.count();
    if (labelCount === 0) continue; // no DataTable/Field rows on this tab — nothing to measure
    checkedAny = true;
    const labelBox = await requireBox(labels.first());
    const fraction = labelBox.width / panelBox.width;
    rows.push(`${tab}: label track ${(fraction * 100).toFixed(1)}% of ${panelBox.width.toFixed(0)}px`);
    expect(fraction, `${tab}: label column is ${(fraction * 100).toFixed(1)}% of the panel`).toBeLessThan(0.4);

    const values = panel.locator("[data-field] > *:nth-child(2), [data-metric] > *:nth-child(2)");
    const valueCount = await values.count();
    for (let i = 0; i < valueCount; i += 1) {
      const box = await requireBox(values.nth(i));
      expect(box.width, `${tab}: value cell ${String(i)} is zero-width`).toBeGreaterThan(0);
    }
  }
  expect(checkedAny, "no inspector tab had any DataTable/Field rows to measure").toBe(true);
  testInfo.annotations.push({ type: "b8-inspector-tracks", description: rows.join(" | ") });
});

test("no DataTable or Field is rendered outside a panel body — a source scan, not a DOM read (B-8)", () => {
  const root = join(process.cwd(), "src");

  function tsxFiles(dir: string): string[] {
    const out: string[] = [];
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const path = join(dir, entry.name);
      if (entry.isDirectory()) out.push(...tsxFiles(path));
      else if (path.endsWith(".tsx")) out.push(path);
    }
    return out;
  }

  // `DataTable.tsx`/`Panel.tsx` define the primitives and legitimately mention
  // both names without using them inside a body; every other caller must wrap
  // its `<DataTable`/`<Field` usage in a `<PanelBody` in the SAME file, which is
  // the container contract `DataTable.tsx`'s own header states.
  const exempt = new Set(["DataTable.tsx", "Panel.tsx"]);
  const offenders: string[] = [];
  for (const file of tsxFiles(root)) {
    const base = file.split("/").pop() ?? file;
    if (exempt.has(base)) continue;
    const source = readFileSync(file, "utf8");
    const usesTable = /<DataTable[\s/>]|<Field[\s/>]/.test(source);
    if (!usesTable) continue;
    const usesPanelBody = /<PanelBody[\s/>]/.test(source);
    if (!usesPanelBody) offenders.push(file);
  }
  expect(offenders, offenders.join("\n")).toEqual([]);
});
