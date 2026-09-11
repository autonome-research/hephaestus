// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Gate G4's pixel and scene-graph clauses:
//
//   G4.5  the visibility toggle changes the viewport inside the target solid's
//         mask region, and leaves a control region outside it alone (§5.4);
//   G4.6  explode(1.0) increases pairwise centroid distances in the scene graph
//         (§5.2, read through the harness handle, never off the screen);
//   G4.7  the section plane produces a golden-matched render — a **server**
//         render, displayed as a plate, compared byte-for-byte (§5.3).
//
// THE DIVISION OF LABOUR IS §5.3'S AND IT IS NOT NEGOTIABLE HERE. No browser
// screenshot in this file is compared against a stored image. G4.5 compares two
// frames from the same rasterizer in the same run, inside a mask decoded from
// *server* bytes, and stores nothing; G4.7 compares *server* bytes against the
// committed golden. That is what lets §5.3's refusal to create a browser-golden
// family and G4.5's pixel clause both stand.

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, type Page } from "@playwright/test";
import { test } from "./harness/geometryHealth";
import {
  CONTROL_CHANGED_MAX,
  INSIDE_CHANGED_MIN,
  assertVisibilityDelta,
  visibilityDelta,
  type Rgb,
} from "./helpers/maskDelta";
import { archive } from "./harness/archive";
import { api, apiBytes, open, refSegment, route } from "./harness/world";

const PART = "tread";

/** `tests/stage4/goldens/section`, from `web/`. */
const GOLDENS = join(process.cwd(), "..", "tests", "stage4", "goldens");

/** `hephaestus.testing.workspace_fixture` — the one definition of both. */
const SECTION_PLANE = "+X@0";
const SECTION_VIEW = "iso";

interface BuildDocument {
  readonly artifact_ref: string;
  readonly geometries: readonly { readonly label: string; readonly solids: number }[];
}

interface InspectDocument {
  readonly status: string;
  readonly render_artifact_refs: readonly string[];
  readonly mask_legend: string | null;
  readonly source_artifact_ref: string;
}

interface LegendEntry {
  readonly kind: string;
  readonly solid_index: number;
  readonly topology_index: number;
}

interface SolidSnapshot {
  readonly solid_index: number;
  readonly position: readonly [number, number, number];
  readonly label: string | null;
  readonly visible: boolean;
  readonly centroid: readonly [number, number, number] | null;
  readonly explode_offset: readonly [number, number, number];
}

function hexToRgb(hex: string): Rgb {
  const value = Number.parseInt(hex.replace("#", ""), 16);
  return [(value >> 16) & 0xff, (value >> 8) & 0xff, value & 0xff];
}

async function solids(page: Page): Promise<SolidSnapshot[]> {
  return await page.evaluate(() => {
    const handle = (
      window as unknown as {
        __hephaestus_viewport__?: { solids: () => SolidSnapshot[] };
      }
    ).__hephaestus_viewport__;
    return handle === undefined ? [] : structuredClone(handle.solids());
  });
}

/** Wait until the pinned GLB is on the canvas, not merely requested. */
async function awaitViewport(page: Page): Promise<void> {
  const viewport = page.locator('[data-testid="viewport"]');
  await expect(viewport).toHaveAttribute("data-glb-state", "ready", { timeout: 120_000 });
  await expect
    .poll(async () => (await solids(page)).length, { timeout: 60_000 })
    .toBeGreaterThan(0);
}

// --------------------------------------------------------------------------
// The world G4.5 and its threshold derivation share.

interface PassWorld {
  readonly pass: Buffer;
  readonly legend: Record<string, LegendEntry>;
  readonly size: { width: number; height: number };
  readonly build: BuildDocument;
}

/**
 * Fetch the **solid-ID pass**, byte-exact from §2.6, and its legend, then size
 * the canvas to it.
 *
 * Both are server values: §1's closed list bars the client from decoding a
 * palette, and this decode happens in the harness against downloaded pass bytes.
 *
 * THE CANVAS IS SIZED BEFORE THE SCENE IS FRAMED, and that order is
 * load-bearing. `inspect_part` exposes no width/height (they are not schema
 * parameters), so the pass is always the server's default and it is the CANVAS
 * that has to move. `assertVisibilityDelta` refuses mismatched dimensions rather
 * than comparing a resampler, and an element only partly on screen screenshots
 * as page chrome.
 *
 * Sizing it *after* the load is not good enough: `Engine.resize` holds the
 * framing's `halfHeight` and recomputes `halfWidth` from the new aspect, so a
 * scene framed at the flex layout's aspect and then resized to 4:3 keeps a
 * vertical extent the server never used, and the mask lands next to the solid
 * instead of on it. An init script installs the style before React mounts, so
 * the first framing is already the pass's aspect.
 *
 * `pointer-events: none` keeps the Results toggle underneath genuinely clickable
 * rather than clicked through a `force` flag.
 */
async function passWorld(page: Page): Promise<PassWorld> {
  const build = await api<BuildDocument>(`/parts/${PART}/build`);
  const inspection = await api<InspectDocument>(`/parts/${PART}/inspect`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      views: [SECTION_VIEW],
      channel: "mask",
      mask_mode: "solid",
      artifact_ref: build.artifact_ref,
    }),
  });
  expect(inspection.status).toBe("ok");
  expect(inspection.mask_legend).not.toBeNull();
  const legend = JSON.parse(inspection.mask_legend ?? "{}") as Record<string, LegendEntry>;
  const passRef = inspection.render_artifact_refs[0] ?? "";
  expect(passRef).toContain("artifact:render:");
  const pass = await apiBytes(`/artifacts/${refSegment(passRef)}/bytes`);

  const size = sizeOf(pass);
  await page.setViewportSize({ width: size.width + 480, height: size.height + 320 });
  await page.addInitScript(
    ([width, height]: [number, number]) => {
      const install = (): void => {
        const style = document.createElement("style");
        style.textContent =
          `[data-testid="viewport"]{position:fixed !important;top:0 !important;left:0 !important;` +
          `width:${String(width)}px !important;height:${String(height)}px !important;` +
          `flex:none !important;z-index:9999 !important;pointer-events:none !important;}`;
        document.head.appendChild(style);
      };
      if (document.head as HTMLElement | null) install();
      else document.addEventListener("DOMContentLoaded", install);
    },
    [size.width, size.height] as [number, number],
  );
  return { pass, legend, size, build };
}

/** The palette values a Results row's label owns — the union over its solids. */
function paletteFor(
  legend: Record<string, LegendEntry>,
  solidIndices: ReadonlySet<number>,
): Rgb[] {
  return Object.entries(legend)
    .filter(([, entry]) => entry.kind === "solid" && solidIndices.has(entry.solid_index))
    .map(([hex]) => hexToRgb(hex));
}

/** Wait until the canvas has actually taken the pass's box before shooting it. */
async function awaitCanvasBox(page: Page, size: { width: number; height: number }): Promise<void> {
  const canvas = page.locator("[data-viewport-canvas]");
  await expect
    .poll(async () => await canvas.boundingBox(), { timeout: 30_000 })
    .toMatchObject({ x: 0, y: 0, width: size.width, height: size.height });
}

// --------------------------------------------------------------------------
// G4.5 — the visibility toggle, inside the mask and nowhere else

test("hiding a solid changes the viewport inside its mask and not outside (G4.5)", async ({
  page,
}, testInfo) => {
  // 1./2. The pass, its legend, and a canvas sized to it.
  const { pass, legend, size: passSize } = await passWorld(page);

  // 3. The target row. §5.4 keys visibility by geometry-entry LABEL, so the
  //    clause is only about one solid when the entry owns one — which
  //    `tests/stage4/test_g4_fixture.py` pins for this fixture. The label→solid
  //    map comes from the scene graph the server built, never from a guess.
  await open(page, route(PART, { tab: "viewport", itab: "results", t: "0" }));
  await awaitViewport(page);
  const scene = await solids(page);
  const target = scene.find((solid) => solid.label === "tread");
  expect(target, "the fixture's tread solid is missing from the scene").toBeDefined();
  const palette = paletteFor(legend, new Set([target?.solid_index ?? -1]));
  expect(palette.length).toBeGreaterThan(0);

  // 4. Two frames of the canvas. The camera needs no further help: the viewport
  //    frames the plain scene bbox while `explode_t === 0`, which is the extent
  //    `channels.py::_framing` gives the `mask` channel, and both sides now
  //    share the aspect.
  const toggle = page.locator(`[data-visibility-toggle="${target?.label ?? ""}"]`);
  await expect(toggle).toBeEnabled();
  const canvas = page.locator("[data-viewport-canvas]");
  await awaitCanvasBox(page, passSize);

  const before = await canvas.screenshot();
  await toggle.click();
  await expect
    .poll(async () => (await solids(page)).find((s) => s.label === "tread")?.visible ?? true)
    .toBe(false);
  const after = await canvas.screenshot();

  const measured = assertVisibilityDelta({ before, after, pass, palette });
  // Printed as well as annotated: the numbers §21 item 10 says were "chosen,
  // not measured" are worth reading off a passing run, not only a failing one.
  // They have since been RE-DERIVED against §3.11's authored material — see the
  // dated block above `INSIDE_CHANGED_MIN` in `helpers/maskDelta.ts` and the
  // envelope case below, which measures every entry rather than this one.
  process.stdout.write(
    `\n[G4.5] frame ${String(measured.width)}x${String(measured.height)} ` +
      `mask ${String(measured.maskPixels)}px inside ${measured.insideChanged.toFixed(4)} ` +
      `control ${measured.controlChanged.toFixed(4)} band ${measured.bandChanged.toFixed(4)}\n`,
  );
  testInfo.annotations.push({
    type: "g4.5",
    description:
      `mask ${String(measured.maskPixels)}px; inside changed ` +
      `${measured.insideChanged.toFixed(4)}; control changed ${measured.controlChanged.toFixed(4)}`,
  });
  await archive(page, testInfo, "g4.5-visibility-after");
});

// --------------------------------------------------------------------------
// THE G4.5 THRESHOLD RE-DERIVATION — 2026-08-28, plan item 6 (§3.11, §21.10)
//
// §3.11 states the consequence rather than leaving it to be discovered: "It does
// move the numbers: §21.10 already records that the 0.10 / 0.01 thresholds are
// chosen rather than measured, and they must be **re-derived against the new
// material before this work lands**, not loosened after it."
//
// This case is that re-derivation, and it is a test rather than a note in a
// commit message so the derivation runs on every gate rather than once. It
// measures the delta for **every toggleable geometry entry** in the fixture, not
// only the one G4.5 names, and asserts the *envelope*: the worst inside-mask
// change over all of them still clears the floor, and the worst control-region
// change over all of them still clears the ceiling. A threshold derived from one
// lucky solid is a threshold that has not been derived.
//
// ── WHAT WAS MEASURED, AND WHAT IT SAYS ─────────────────────────────────────
//
// At 960×720, over the fixture's three entries (the `before` row is `tread`
// alone, because one entry is all the pre-item-6 suite measured):
//
//   entry         mask px    inside    control    band (excluded)
//   ─────────────────────────────────────────────────────────────
//   tread  BEFORE  142025    1.0000    0.0000     0.5578
//   tread  AFTER   142025    1.0000    0.0000     0.6527
//   cleat_left      7957     1.0000    0.0000     0.6439
//   cleat_right     7957     1.0000    0.0000     0.6439
//                            ≥ 0.10    ≤ 0.01     no threshold
//
// The cleats are an 18× smaller region than the tread and land on the same two
// numbers — which is the part a single-solid measurement could not establish.
//
// **The thresholds are therefore UNCHANGED at 0.10 and 0.01, and that is the
// derivation's result rather than an omission.** Three things follow from the
// numbers and each is the reason a different change was not made:
//
// 1. *Inside* did not need raising even though it could be. It measures 1.0000
//    — every pixel of the target's silhouette changed — which is 10× the floor.
//    It is 1.0000 for a structural reason that survives any material: hiding a
//    solid replaces every pixel of its own silhouette with whatever is behind
//    it, and the mask IS that silhouette. Raising the floor to fit a measurement
//    that is already saturated would pin the gate to the *rasterizer's* exact
//    output, which is precisely the claim §5.3 has refused to make. §5.4 says so
//    in as many words: "The thresholds are loose on purpose: the clause asks
//    whether the toggle changed the right region."
// 2. *Control* did not need loosening, which is the failure mode §3.11 was
//    warning about. It measures 0.0000 — exact byte equality outside the mask —
//    and the reason is that everything item 6 added outside the silhouette is
//    **static under a visibility toggle**: the ground grid is rebuilt only on a
//    re-framing, the axis triad moves only with the camera, and the readout's
//    new grid row is fixed-width. The one thing that could have leaked into the
//    control region — the authored silhouette, which is drawn along the mask's
//    own boundary — is absorbed by §5.4's two-pixel dilation band, and the band
//    is where the change shows up: it rose from 0.5578 to 0.6527 because a
//    bright edge now sits where a black one did.
// 3. Nothing was loosened to accommodate a regression, explained or otherwise,
//    because there was no regression: both measurements are identical to the
//    pre-item-6 run and the control region is at its absolute floor.
//
// If a later change makes this case fail, the honest reading is that the change
// moved pixels outside the toggled solid — not that the ceiling is too tight.
// §5.4's numbers are normative; this file may report against them, never edit
// them.

test("the G4.5 thresholds hold for EVERY solid, not only the named one (§3.11, item 6)", async ({
  page,
}, testInfo) => {
  const { pass, legend, size: passSize, build } = await passWorld(page);

  await open(page, route(PART, { tab: "viewport", itab: "results", t: "0" }));
  await awaitViewport(page);
  await awaitCanvasBox(page, passSize);
  const scene = await solids(page);
  const canvas = page.locator("[data-viewport-canvas]");

  // The toggle's namespace is the geometry-entry LABEL (§5.4), so the rows are
  // the build's own entries and the mask for a row is the union of its solids'
  // palette values. Both sides of that join are server values.
  const labels = build.geometries.map((geometry) => geometry.label);
  expect(labels.length).toBeGreaterThanOrEqual(1);

  const rows: string[] = [];
  let worstInside = Number.POSITIVE_INFINITY;
  let worstControl = 0;

  for (const label of labels) {
    const owned = new Set(
      scene.filter((solid) => solid.label === label).map((solid) => solid.solid_index),
    );
    const palette = paletteFor(legend, owned);
    if (palette.length === 0) {
      // An entry with no solid in the pass has no region to assert in. Named
      // rather than skipped: `assertVisibilityDelta` refuses this case outright,
      // and a derivation that silently dropped a row would be measuring a
      // subset it never disclosed.
      rows.push(`${label}: no palette value in the pass — not measurable`);
      continue;
    }

    const toggle = page.locator(`[data-visibility-toggle="${label}"]`);
    await expect(toggle).toBeEnabled();
    const before = await canvas.screenshot();
    await toggle.click();
    await expect
      .poll(async () => (await solids(page)).find((s) => s.label === label)?.visible ?? true)
      .toBe(false);
    const after = await canvas.screenshot();
    // Restore, so the next row is measured against the whole assembly rather
    // than against whatever the previous row left hidden.
    await toggle.click();
    await expect
      .poll(async () => (await solids(page)).find((s) => s.label === label)?.visible ?? false)
      .toBe(true);

    const measured = visibilityDelta({ before, after, pass, palette });
    worstInside = Math.min(worstInside, measured.insideChanged);
    worstControl = Math.max(worstControl, measured.controlChanged);
    rows.push(
      `${label}: mask ${String(measured.maskPixels)}px inside ${measured.insideChanged.toFixed(4)} ` +
        `control ${measured.controlChanged.toFixed(4)} band ${measured.bandChanged.toFixed(4)}`,
    );
  }

  expect(Number.isFinite(worstInside), "no entry was measurable at all").toBe(true);
  process.stdout.write(`\n[G4.5 derivation] ${rows.join(" | ")}\n`);
  testInfo.annotations.push({ type: "g4.5-derivation", description: rows.join(" | ") });

  // The envelope, against §5.4's own constants — imported, not retyped, so a
  // future edit to the thresholds cannot leave this derivation asserting the
  // old pair.
  expect(worstInside, "an entry changed too little inside its own mask").toBeGreaterThanOrEqual(
    INSIDE_CHANGED_MIN,
  );
  expect(worstControl, "an entry changed pixels outside its mask").toBeLessThanOrEqual(
    CONTROL_CHANGED_MAX,
  );
  await archive(page, testInfo, "g4.5-threshold-derivation");
});

// --------------------------------------------------------------------------
// G4.6 — explode(1.0) increases pairwise centroid distances

test("explode(1.0) increases every pairwise centroid distance (G4.6)", async ({
  page,
}, testInfo) => {
  await open(page, route(PART, { tab: "viewport", t: "0" }));
  await awaitViewport(page);
  const collapsed = await solids(page);
  expect(collapsed.length).toBeGreaterThanOrEqual(3); // §14's ≥3 solids, or vacuous

  await page.locator('[data-testid="explode-slider"]').fill("1");
  await expect(page.locator("[data-explode-t]")).toHaveAttribute("data-explode-t", "1");
  await expect
    .poll(async () => {
      const now = await solids(page);
      return now.every((solid, index) => solid.position !== collapsed[index]?.position);
    })
    .toBe(true);
  const exploded = await solids(page);

  // THE SUBTRACTION IS THE HARNESS'S (§1). The client applied `offset · t` and
  // computed nothing; these are node positions crossing the boundary, and the
  // distances are computed here.
  const grew: string[] = [];
  for (let i = 0; i < collapsed.length; i += 1) {
    for (let j = i + 1; j < collapsed.length; j += 1) {
      const near = distance(collapsed[i]?.centroid, collapsed[j]?.centroid);
      const far = distance(exploded[i]?.centroid, exploded[j]?.centroid);
      expect(far, `pair (${String(i)},${String(j)}) did not grow`).toBeGreaterThan(near);
      grew.push(`${near.toFixed(3)}->${far.toFixed(3)}`);
    }
  }
  expect(grew.length).toBe((collapsed.length * (collapsed.length - 1)) / 2);

  // And the displacement each node moved by is the SERVER's declared vector at
  // `t = 1`, not a client-computed one: §5.2 ships `explode_offset` precisely so
  // the client never reconstructs a magnitude.
  for (const solid of exploded) {
    expect(solid.position).toEqual(solid.explode_offset);
  }

  process.stdout.write(`\n[G4.6] pairwise ${grew.join(", ")}\n`);
  testInfo.annotations.push({ type: "g4.6", description: grew.join(", ") });
  await archive(page, testInfo, "g4.6-explode");
});

// --------------------------------------------------------------------------
// G4.7 — the section plate is the golden's bytes

test("the section plane renders a golden-matched server plate (G4.7)", async ({
  page,
}, testInfo) => {
  const stem = `workspace_tread_section_${SECTION_VIEW}_section`;
  const sidecar = JSON.parse(
    readFileSync(join(GOLDENS, "section", `${stem}.json`), "utf8"),
  ) as Record<string, string>;
  const goldenBytes = readFileSync(join(GOLDENS, "section", `${stem}.png`));

  await open(page, route(PART, { tab: "viewport", view: SECTION_VIEW, t: "0" }));
  await awaitViewport(page);

  // Drive the control the way an operator does, then take the plane the control
  // itself reports. A spec that typed the plane into the URL would never learn
  // that the control produces a different spelling.
  await page.locator('[data-testid="section-enable"]').click();
  // The control opens on Z; the golden is a cut across the width, so the axis is
  // chosen through the control rather than written into the URL. Taking the
  // plane back OFF the control is what makes this a test of the control's own
  // spelling: `formatSectionPlane` trims trailing zeros, and a golden baselined
  // on a differently-spelled plane would never be requested.
  await page.locator('[data-testid="section-axis"]').selectOption("X");
  await expect(page.locator("[data-section-control]")).toHaveAttribute(
    "data-section-plane",
    SECTION_PLANE,
  );
  const viewport = page.locator('[data-testid="viewport"]');
  await expect(viewport).toHaveAttribute("data-section-state", "preview");

  // §5.3: the preview is explicitly NON-EVIDENTIARY. The evidence is the plate.
  await page.locator('[data-testid="section-render"]').click();
  await expect(viewport).toHaveAttribute("data-section-state", "rendered", { timeout: 120_000 });
  // The plate has three states and only one of them names an artifact: it is
  // `pending` while the bytes are in flight and `refused` when the server said
  // no. Waiting for the named state is what makes the next line an assertion
  // about the plate rather than a race against the fetch.
  const plate = page.locator('[data-section-plate="rendered"]');
  await expect(plate).toBeVisible({ timeout: 120_000 });
  const plateRef = await plate.getAttribute("data-plate-ref");
  expect(plateRef, "the plate names no artifact").toBeTruthy();
  expect(plateRef).toContain("artifact:render:");

  // A golden is valid only for its `(container image, renderer version)` pair
  // (verification.md Tier 2). A mismatch is reported BY NAME rather than
  // skipped: a suite that quietly passed on the wrong rasterizer asserts
  // nothing, which is the degenerate pass mission rule 1 requires be closed.
  const served = await apiBytes(`/artifacts/${refSegment(plateRef ?? "")}/bytes`);
  const digest = `sha256:${await sha256(served)}`;
  expect(
    digest,
    `the section plate does not reproduce the golden baselined on ${sidecar["gl_renderer"] ?? "?"}` +
      " — re-baseline inside the pinned CI image with" +
      " `uv run python scripts/record_workspace_transcript.py` (INTERFACE.md §14)",
  ).toBe(sidecar["png_sha256"]);
  expect(Buffer.compare(served, goldenBytes)).toBe(0);

  // The plate is bound to the artifact the SERVER resolved, and says so (§4.4).
  const build = await api<BuildDocument>(`/parts/${PART}/build`);
  await expect(page.locator('[data-source="inspect.source_artifact_ref"]')).toHaveAttribute(
    "data-value",
    build.artifact_ref,
  );

  await archive(page, testInfo, "g4.7-section-plate");
});

// --------------------------------------------------------------------------
// §5.5 C18/C19 — the viewport overlays are pairwise non-intersecting, at the
// steady width and at the band's yield width. The same assertion style as
// §7.4's C20 pill clause, stated once per surface set.

interface Box {
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
}

function intersects(a: Box, b: Box): boolean {
  return a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
}

/**
 * §5.5 C19's named surface set.
 *
 * `[data-plate-header]`, NOT `[data-section-plate]` (J-web-viewport-2). The
 * clause names the plate's HEADER; the plate itself is absolutely positioned to
 * the whole well, so listing it makes the sweep assert that a full-bleed layer
 * does not intersect the six things drawn on top of it — which is false by
 * construction the moment a plate mounts, and was never noticed because this
 * test never engaged a section, so the selector matched nothing and the helper
 * skipped it. A gate that has never run against the state it governs asserts
 * nothing (RC-10).
 */
const OVERLAY_SURFACES = [
  "[data-view-cube]",
  "[data-appearance]",
  "[data-grid-readout]",
  "[data-explode-t]",
  "[data-section-control]",
  "[data-plate-header]",
] as const;

async function overlayBoxes(page: Page): Promise<{ selector: string; box: Box }[]> {
  const found: { selector: string; box: Box }[] = [];
  for (const selector of OVERLAY_SURFACES) {
    const locator = page.locator(selector).first();
    if ((await locator.count()) === 0) continue;
    const box = await locator.boundingBox();
    if (box !== null) found.push({ selector, box });
  }
  return found;
}

function assertPairwiseDisjoint(boxes: readonly { selector: string; box: Box }[]): void {
  for (let i = 0; i < boxes.length; i += 1) {
    for (let j = i + 1; j < boxes.length; j += 1) {
      const a = boxes[i];
      const b = boxes[j];
      if (a === undefined || b === undefined) continue;
      expect(
        intersects(a.box, b.box),
        `${a.selector} intersects ${b.selector}: ${JSON.stringify(a.box)} vs ${JSON.stringify(b.box)}`,
      ).toBe(false);
    }
  }
}

test("viewport overlays are pairwise non-intersecting at 1280x800 and at the yield width (§5.5 C18/C19)", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await open(page, route(PART, { tab: "viewport", t: "0" }));
  await awaitViewport(page);

  // C19: the named views live INSIDE the one view-cube plate — one bounding box
  // in the corner, so the pairwise sweep below covers them by construction.
  //
  // AMENDED with B-7's fix: the cube draws exactly the cells facing the viewer,
  // so which `data-view` is present depends on the camera. This route carries no
  // `view`, so it is `iso` and the `iso` corner is the cell toward the eye; the
  // `front` face is behind the cube here and is asserted at its own camera in
  // the B-7 gate below. The shipped cube passed the old unconditional form by
  // drawing `Front` at EVERY azimuth, which is the defect, not compliance.
  const cube = page.locator("[data-view-cube]");
  await expect(cube).toHaveCount(1);
  await expect(cube.locator('[data-view="iso"]')).toHaveCount(1);
  await expect(cube).toHaveAttribute("aria-label", "View cube");
  await expect(cube).toHaveAttribute("tabindex", "0");
  for (const axis of ["+Y", "+Z", "-X", "+X", "-Z", "-Y"]) {
    await expect(page.getByRole("button", { name: axis, exact: true })).toHaveCount(0);
  }

  const steady = await overlayBoxes(page);
  expect(
    steady.length,
    `expected the resting overlay set, saw ${steady.map((entry) => entry.selector).join(", ")}`,
  ).toBeGreaterThanOrEqual(5);
  assertPairwiseDisjoint(steady);

  // C18's yield width: shrink the window until the stage column measures below
  // the named 560px. The stage does not shrink 1:1 with the window (the rail
  // and stream have their own floors), so walk down and measure.
  const viewport = page.locator('[data-testid="viewport"]');
  let window = 1280;
  await expect
    .poll(
      async () => {
        const box = await viewport.boundingBox();
        if (box !== null && box.width < 560) return true;
        window -= 80;
        if (window < 500) return "cannot reach the yield width";
        await page.setViewportSize({ width: window, height: 800 });
        return false;
      },
      { timeout: 30_000 },
    )
    .toBe(true);

  // The fixed order's first step: the explode slider collapsed to its
  // disclosure (the fixture has ≥3 solids, so this is the C18 yield, not #60).
  await expect(page.locator("[data-explode-collapsed]")).toHaveCount(1);
  assertPairwiseDisjoint(await overlayBoxes(page));
});

// --------------------------------------------------------------------------
// §5.3 / §5.5 C19 (amended 2026-09-05) — THE PLATE-MOUNTED SWEEP.
//
// The sweep above has never run against a mounted plate: this test is the one
// that engages a section, waits for the server's rendered plate, and only then
// measures. With the plate up, §5.3 says the plate owns the well
// (J-web-viewport-2), so the four CANVAS-AUTHORING overlays unmount — a view
// cube, an appearance cluster, an axis triad and a grid readout all address or
// describe a live camera the reader is no longer looking at — and the section
// control stays, because it is the exit.
//
// THE SURFACE FLOOR IS THE POINT. `overlayBoxes` skips a selector that matches
// nothing, so a plate that fails to mount would shrink the set to the surfaces
// that happen to be there and pass. The floor makes a missing plate a failure.

test("with a rendered plate the plate owns the well, and the header is readable (§5.3, C19)", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await open(page, route(PART, { tab: "viewport", view: SECTION_VIEW, t: "0" }));
  await awaitViewport(page);

  await page.locator('[data-testid="section-enable"]').click();
  await page.locator('[data-testid="section-axis"]').selectOption("X");
  await page.locator('[data-testid="section-render"]').click();

  const viewport = page.locator('[data-testid="viewport"]');
  await expect(viewport).toHaveAttribute("data-section-state", "rendered", { timeout: 120_000 });
  const header = page.locator("[data-plate-header]");
  await expect(header).toHaveCount(1, { timeout: 120_000 });

  // The four that unmount, and the one that must not.
  for (const gone of [
    "[data-view-cube]",
    "[data-appearance]",
    "[data-axis-triad]",
    "[data-grid-readout]",
  ]) {
    await expect(page.locator(gone), `${gone} is painted over a rendered plate`).toHaveCount(0);
  }
  await expect(page.locator("[data-section-control]")).toHaveCount(1);

  const boxes = await overlayBoxes(page);
  expect(
    boxes.map((entry) => entry.selector),
    "the plate header must be in the measured set — a plate that did not mount must FAIL, not shrink the sweep",
  ).toContain("[data-plate-header]");
  expect(boxes.length, "expected at least the header and the section control").toBeGreaterThanOrEqual(2);
  assertPairwiseDisjoint(boxes);

  // §5.3's reference is shown, and shown INSIDE the bar: a ninety-character ref
  // that runs to the plate's edge is not "shown in the header".
  const headerBox = await header.boundingBox();
  const refBox = await page.locator('[data-source="inspect.source_artifact_ref"]').boundingBox();
  expect(headerBox, "the plate header has no box").not.toBeNull();
  expect(refBox, "the plate header names no artifact").not.toBeNull();
  if (headerBox !== null && refBox !== null) {
    expect(refBox.x).toBeGreaterThanOrEqual(headerBox.x - 1);
    expect(refBox.x + refBox.width).toBeLessThanOrEqual(headerBox.x + headerBox.width + 1);
    expect(refBox.y).toBeGreaterThanOrEqual(headerBox.y - 1);
    expect(refBox.y + refBox.height).toBeLessThanOrEqual(headerBox.y + headerBox.height + 1);
  }
});

// --------------------------------------------------------------------------
// §5.5 C18 (amended 2026-09-05) — no band occupant paints outside its own card.
//
// The negative half J-web-viewport-3 adds. The ladder used to compare a width
// constant against the stage width and never measured what the band demands, so
// a section engaged at 1600px squeezed the explode card to 113px around 172px of
// content and drew its Collapse button on the canvas.

test("no bottom-band occupant paints outside its own card, section engaged (§5.5 C18)", async ({
  page,
}) => {
  for (const width of [1280, 1600, 1920]) {
    await page.setViewportSize({ width, height: 900 });
    await open(page, route(PART, { tab: "viewport", t: "0.5" }));
    await awaitViewport(page);
    await page.locator('[data-testid="section-enable"]').click();
    await expect(page.locator("[data-section-control]")).toHaveCount(1);

    const overflow = await page.evaluate(() => {
      const band = document.querySelector("[data-viewport-band]");
      if (band === null) throw new Error("no [data-viewport-band]");
      const escaped: string[] = [];
      for (const card of band.children) {
        const cardBox = card.getBoundingClientRect();
        if (card.scrollWidth > card.clientWidth + 1) {
          escaped.push(`${card.className}: content ${String(card.scrollWidth)} > box ${String(card.clientWidth)}`);
        }
        for (const child of card.querySelectorAll("*")) {
          const box = child.getBoundingClientRect();
          if (box.width === 0 && box.height === 0) continue;
          if (box.right > cardBox.right + 1 || box.left < cardBox.left - 1) {
            escaped.push(`${child.tagName}.${String(child.className)} escapes ${card.className}`);
          }
        }
      }
      return {
        escaped,
        bandOverflow: band.scrollWidth > band.clientWidth + 1,
      };
    });
    expect(overflow.escaped, `at ${String(width)}px`).toEqual([]);
    expect(overflow.bandOverflow, `the band overflows at ${String(width)}px`).toBe(false);
  }
});

// --------------------------------------------------------------------------
// J-web-viewport-4 — a 7ch readout cannot hold `0.00`.
//
// The reproduction IS a width measurement ("both readouts report a client
// width of 48 and a scroll width of 51-52 for the value 0.00"), so the test is
// the same measurement, taken at the values that stress it: minimum, middle
// and maximum. jsdom cannot lay out a `<input type="number">`'s spin buttons
// at all, which is exactly why this has to run here rather than in vitest.

/** The editable number-input readout beside a range input carrying `testid`. */
function readoutFor(page: Page, testid: string) {
  return page.locator(`[data-testid="${testid}"]`).locator("xpath=..").locator('input[type="number"]');
}

async function assertNoOverflow(readout: ReturnType<typeof readoutFor>, label: string): Promise<void> {
  const { scrollWidth, clientWidth, value } = await readout.evaluate((el: HTMLInputElement) => ({
    scrollWidth: el.scrollWidth,
    clientWidth: el.clientWidth,
    value: el.value,
  }));
  expect(scrollWidth, `${label} clips its value "${value}" (scroll ${String(scrollWidth)} > client ${String(clientWidth)})`).toBeLessThanOrEqual(clientWidth);
}

test("the explode readout never clips its value, at min/mid/max (J-web-viewport-4)", async ({ page }) => {
  await open(page, route(PART, { tab: "viewport" }));
  await awaitViewport(page);
  const range = page.locator('[data-testid="explode-slider"]');
  const readout = readoutFor(page, "explode-slider");
  for (const value of ["0", "0.5", "1"]) {
    await range.fill(value);
    await assertNoOverflow(readout, `explode readout at t=${value}`);
  }
});

test("the section-offset readout never clips its value, at min/mid/max (J-web-viewport-4)", async ({
  page,
}) => {
  await open(page, route(PART, { tab: "viewport" }));
  await awaitViewport(page);
  await page.locator('[data-testid="section-enable"]').click();
  const range = page.locator('[data-testid="section-offset"]');
  const readout = readoutFor(page, "section-offset");
  const { min, max } = await range.evaluate((el: HTMLInputElement) => ({
    min: Number(el.min),
    max: Number(el.max),
  }));
  const mid = (min + max) / 2;
  for (const value of [min, mid, max]) {
    await range.fill(String(value));
    await assertNoOverflow(readout, `section-offset readout at ${String(value)}`);
  }
});

test("a PARAMS readout stays fully visible carrying a rejected out-of-bounds value (J-web-viewport-4, §10)", async ({
  page,
}) => {
  // The case the fix note calls out as mattering more: a PARAMS slider does
  // not clamp (`clamp={false}`), so a typed out-of-bounds value is sent for
  // the server to refuse — and a refused value the operator cannot read back
  // is a refusal they cannot act on.
  const document = await api<{
    readonly status: string;
    readonly params: readonly { readonly name: string; readonly min: number; readonly max: number }[];
  }>(`/parts/${PART}/params`);
  const first = document.params[0];
  if (first === undefined) throw new Error("fixture part has no params to drive");

  await open(page, route(PART, { tab: "script" }));
  const range = page.locator(`[data-param-slider="${first.name}"]`);
  await expect(range).toBeVisible();
  const readout = page
    .locator(`[data-param-slider="${first.name}"]`)
    .locator("xpath=..")
    .locator('input[type="number"]');
  const outOfBounds = first.max + Math.max(1, Math.abs(first.max - first.min));
  await readout.fill(String(outOfBounds));
  await readout.blur();
  // Not an exact-string match: an integer-valued param renders its readout at
  // 0 decimal places (`isIntegerParam`), so the only thing worth pinning here
  // is that the CONTROL WAS NOT CLAMPED BACK — clamp is off for PARAMS
  // sliders by contract (§10, G5.3) — never a particular formatting.
  await expect
    .poll(async () => Number(await readout.inputValue()))
    .toBeGreaterThanOrEqual(outOfBounds - 0.005);
  await assertNoOverflow(readout, `PARAMS readout for ${first.name} carrying a rejected value`);
});

// --------------------------------------------------------------------------

function distance(
  a: readonly [number, number, number] | null | undefined,
  b: readonly [number, number, number] | null | undefined,
): number {
  if (a == null || b == null) throw new Error("a solid has no centroid; the scene is not loaded");
  return Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
}

async function sha256(bytes: Buffer): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new Uint8Array(bytes));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** PNG dimensions, straight out of the IHDR — no decode needed. */
function sizeOf(png: Buffer): { width: number; height: number } {
  return { width: png.readUInt32BE(16), height: png.readUInt32BE(20) };
}

// --------------------------------------------------------------------------
// B-7 — the view cube's reachability gate (audit-2026-09-04-broken.md B-7).
//
// THIS IS THE ASSERTION WHOSE ABSENCE LET THE DEFECT SHIP. The commit that
// introduced the cube rewrote `viewportChrome.test.tsx` to count boxes, check
// `tabindex`, and read the stylesheet as text — "Not one assertion is about
// geometry or reachability" (B-7's own history section). This sweep is that
// missing assertion: it buckets every pixel of the cube's bounding box by the
// button under it, exactly the way the audit's own reproduction did, and reads
// the address off each button's OWN accessible name — never off `data-view`,
// which today is minted on only two of fifteen buttons and would make this
// gate vacuously pass on the unfixed cube.

/** Every button inside the view cube, bucketed by pixel under `elementFromPoint`. */
async function sweepCube(page: Page): Promise<{
  readonly counts: Record<string, number>;
  readonly boxes: Record<string, { width: number; height: number }>;
}> {
  return await page.evaluate(() => {
    const cube = document.querySelector("[data-view-cube]");
    if (cube === null) throw new Error("no [data-view-cube] in the DOM");
    const rect = cube.getBoundingClientRect();
    const counts: Record<string, number> = {};
    const boxes: Record<string, { width: number; height: number }> = {};
    for (const button of cube.querySelectorAll("button")) {
      const label = button.getAttribute("aria-label") ?? button.textContent ?? "";
      const box = button.getBoundingClientRect();
      boxes[label] = { width: box.width, height: box.height };
    }
    for (let y = Math.ceil(rect.top); y < Math.floor(rect.bottom); y += 1) {
      for (let x = Math.ceil(rect.left); x < Math.floor(rect.right); x += 1) {
        const el = document.elementFromPoint(x, y);
        const button = el?.closest("button") ?? null;
        if (button === null || !cube.contains(button)) continue;
        const label = button.getAttribute("aria-label") ?? button.textContent ?? "";
        counts[label] = (counts[label] ?? 0) + 1;
      }
    }
    return { counts, boxes };
  });
}

const NAMED_VIEWS = ["iso", "+X", "-X", "+Y", "-Y", "+Z", "-Z", "front"] as const;

test("every drawn view-cube button collects at least one pixel, at iso and at every standard view (B-7 reachability gate)", async ({
  page,
}, testInfo) => {
  const failures: string[] = [];
  for (const view of NAMED_VIEWS) {
    await open(page, route(PART, { tab: "viewport", view, t: "0" }));
    await awaitViewport(page);
    await expect(page.locator("[data-view-cube]")).toBeVisible();
    const { counts, boxes } = await sweepCube(page);
    for (const [label, box] of Object.entries(boxes)) {
      if (box.width <= 0 || box.height <= 0) continue; // not drawn; nothing to reach
      const hit = counts[label] ?? 0;
      if (hit === 0) failures.push(`${view}: "${label}" (${box.width}x${box.height}) collected 0px`);
      // The audit's own numbers: Front swallowed 2646px of a 90x98 plate — a
      // button collecting far more than its own drawn area is another
      // target's paint-order victim, not a generously-sized hit region.
      const area = box.width * box.height;
      if (hit > area * 1.5) {
        failures.push(`${view}: "${label}" collected ${String(hit)}px over its own ${area.toFixed(0)}px box`);
      }
    }
  }
  testInfo.annotations.push({ type: "b7-reachability", description: failures.join(" | ") });
  expect(failures, failures.join("\n")).toEqual([]);
  await archive(page, testInfo, "b7-cube-reachability");
});

/** §5.5's two-names-one-camera pair, spelled the way the cube spells it. */
function canonicalView(view: string): string {
  return view === "-Y" ? "front" : view;
}

test("the cube always draws the camera the workspace is on, and addresses it (B-7, C19)", async ({
  page,
}) => {
  // C19's `front` clause, at the camera where `front` is the cell toward the
  // eye. Stated as a rule rather than about one name: at every named view the
  // cell whose normal IS the eye direction is drawn and carries that camera's
  // `data-view`. `-Y` and `front` are one camera with two names (`cameras.ts`),
  // and the cube spells it `front`.
  for (const view of NAMED_VIEWS) {
    await open(page, route(PART, { tab: "viewport", view, t: "0" }));
    await awaitViewport(page);
    const cube = page.locator("[data-view-cube]");
    await expect(cube.locator(`[data-view="${canonicalView(view)}"]`), view).toHaveCount(1);
    // And it is the CURRENT one, so the plate says where the camera is.
    await expect(cube.locator("[data-cube-current]"), view).toHaveCount(1);
  }
});

test("clicking -X, +Y and -Z view-cube targets moves the URL's view to each (B-7)", async ({
  page,
}) => {
  await open(page, route(PART, { tab: "viewport", t: "0" }));
  await awaitViewport(page);

  // The audit names these three by their FACE labels — Left (-X), Back (+Y),
  // Bottom (-Z) — as unreachable at EVERY azimuth on the shipped cube: `Left`
  // and `Bottom` collected zero pixels at all fifteen named views, and `Back`
  // was culled by `backface-visibility` at all of them. All three are reached
  // here, which is the regression this test exists for.
  //
  // They are reached BY TURNING THE CUBE, because that is what the fix makes
  // true: the cube draws exactly the cells facing the viewer, so a face on the
  // far side is not drawn and — §5.5's negative half — not clickable either. A
  // corner brings it round, which is what corner targets are for and what no
  // shipped corner could do (five of eight existed and several named the wrong
  // camera). Every step below therefore also exercises a corner target.
  const steps: readonly { readonly label: string; readonly view: string }[] = [
    { label: "Left / Back / Top", view: "az135_el35" },
    { label: "Left", view: "-X" },
    { label: "Left / Front / Bottom", view: "az225_el-35" },
    { label: "Bottom", view: "-Z" },
    { label: "Left / Back / Bottom", view: "az135_el-35" },
    { label: "Back", view: "+Y" },
  ];

  for (const { label, view } of steps) {
    await page.locator("[data-view-cube]").getByRole("button", { name: label, exact: true }).click({
      timeout: 5_000,
    });
    await expect
      .poll(() => new URL(page.url()).hash, `clicking "${label}" did not move the view to ${view}`)
      .toMatch(new RegExp(`view=${view.replace(/[+]/g, "%2B")}|view=${view}`));
  }
});
