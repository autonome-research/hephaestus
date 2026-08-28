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
import { assertVisibilityDelta, type Rgb } from "./helpers/maskDelta";
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
// G4.5 — the visibility toggle, inside the mask and nowhere else

test("hiding a solid changes the viewport inside its mask and not outside (G4.5)", async ({
  page,
}, testInfo) => {
  // 1. The **solid-ID pass**, byte-exact from §2.6, and its legend. Both are
  //    server values: §1's closed list bars the client from decoding a palette,
  //    and this decode happens in the harness against downloaded pass bytes.
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

  // 2. The canvas is sized to the pass BEFORE the scene is framed, and that
  //    order is load-bearing.
  //
  //    `inspect_part` exposes no width/height (they are not schema parameters),
  //    so the pass is always the server's default and it is the CANVAS that has
  //    to move. `assertVisibilityDelta` refuses mismatched dimensions rather
  //    than comparing a resampler, and an element only partly on screen
  //    screenshots as page chrome.
  //
  //    Sizing it *after* the load is not good enough: `Engine.resize` holds the
  //    framing's `halfHeight` and recomputes `halfWidth` from the new aspect, so
  //    a scene framed at the flex layout's aspect and then resized to 4:3 keeps
  //    a vertical extent the server never used, and the mask lands next to the
  //    solid instead of on it. An init script installs the style before React
  //    mounts, so the first framing is already the pass's aspect.
  //
  //    `pointer-events: none` keeps the Results toggle underneath genuinely
  //    clickable rather than clicked through a `force` flag.
  const passSize = sizeOf(pass);
  await page.setViewportSize({ width: passSize.width + 480, height: passSize.height + 320 });
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
    [passSize.width, passSize.height] as [number, number],
  );

  // 3. The target row. §5.4 keys visibility by geometry-entry LABEL, so the
  //    clause is only about one solid when the entry owns one — which
  //    `tests/stage4/test_g4_fixture.py` pins for this fixture. The label→solid
  //    map comes from the scene graph the server built, never from a guess.
  await open(page, route(PART, { tab: "viewport", itab: "results", t: "0" }));
  await awaitViewport(page);
  const scene = await solids(page);
  const target = scene.find((solid) => solid.label === "tread");
  expect(target, "the fixture's tread solid is missing from the scene").toBeDefined();
  const palette = Object.entries(legend)
    .filter(([, entry]) => entry.kind === "solid" && entry.solid_index === target?.solid_index)
    .map(([hex]) => hexToRgb(hex));
  expect(palette.length).toBeGreaterThan(0);

  // 4. Two frames of the canvas. The camera needs no further help: the viewport
  //    frames the plain scene bbox while `explode_t === 0`, which is the extent
  //    `channels.py::_framing` gives the `mask` channel, and both sides now
  //    share the aspect.
  const toggle = page.locator(`[data-visibility-toggle="${target?.label ?? ""}"]`);
  await expect(toggle).toBeEnabled();
  const canvas = page.locator("[data-viewport-canvas]");
  await expect
    .poll(async () => await canvas.boundingBox(), { timeout: 30_000 })
    .toMatchObject({ x: 0, y: 0, width: passSize.width, height: passSize.height });

  const before = await canvas.screenshot();
  await toggle.click();
  await expect
    .poll(async () => (await solids(page)).find((s) => s.label === "tread")?.visible ?? true)
    .toBe(false);
  const after = await canvas.screenshot();

  const measured = assertVisibilityDelta({ before, after, pass, palette });
  // Printed as well as annotated: the numbers §21 item 10 says were "chosen,
  // not measured" are worth reading off a passing run, not only a failing one.
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
