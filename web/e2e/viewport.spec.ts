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
import { expect, test, type Page } from "@playwright/test";
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

/** §5.5 C19's named surface set. The section plate header joins when mounted. */
const OVERLAY_SURFACES = [
  "[data-view-cube]",
  "[data-appearance]",
  "[data-grid-readout]",
  "[data-explode-t]",
  "[data-section-control]",
  "[data-section-plate]",
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

  // C19: `front` lives INSIDE the one view-cube plate — one bounding box in
  // the corner, so the pairwise sweep below covers it by construction.
  const cube = page.locator("[data-view-cube]");
  await expect(cube).toHaveCount(1);
  await expect(cube.locator('[data-view="front"]')).toHaveCount(1);
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
