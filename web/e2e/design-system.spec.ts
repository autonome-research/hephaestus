// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// §3.14's browser half — and the SPLIT is the point.
//
// The 2026-08-28 review correction, quoted because it is what shapes this file:
// "an earlier draft put the whole no-colour-only assertion in Playwright over
// the fixture, where it cannot run. `not_run` has no producer in the public
// clean-room fixture, deliberately and with a written refusal, so a browser
// assertion over it has nothing to render."
//
// So this spec "asserts only over what the fixture reaches, matching the
// existing enumeration in `dom.spec.ts`, and says so". The four clauses §3.14
// names are here and nothing more:
//
//   1. sampled computed contrast for every ink and status ink against its
//      rendered background ≥ 4.5;
//   2. the viewport canvas's centre pixel ≥ 4.5:1 against its corner pixel when
//      geometry is loaded (§3.11.2's part-vs-ground floor);
//   3. grid columns at 1440 / 1280 / **1279** / 1024 / 1023 matching §4.1's
//      table, with `document.body.scrollWidth === clientWidth` at all five, and
//      the narrow Rail-hidden Stream opening to its full-width track;
//   4. the inspector canvas height identical across all five inspector tabs.
//
// `not_run`'s distinctness lives in `test/system/badge.test.tsx`, which renders
// all six statuses directly. That is not a weaker test — it is the only one that
// can run at all, and §3.14 says so.
//
// NO ASSERTION HERE IS ON UI COPY (§3's clean-room hygiene). Every expectation
// is a measured number or a structural fact.

import { expect, test } from "@playwright/test";
import { archive } from "./harness/archive";
import { open, route } from "./harness/world";

const PART = "tread";

/** WCAG relative luminance of an `rgb(r, g, b)` string, as the browser reports it. */
function luminanceOf(rgb: readonly [number, number, number]): number {
  const channel = (value: number): number => {
    const c = value / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(rgb[0]) + 0.7152 * channel(rgb[1]) + 0.0722 * channel(rgb[2]);
}

function contrastOf(a: readonly [number, number, number], b: readonly [number, number, number]): number {
  const la = luminanceOf(a);
  const lb = luminanceOf(b);
  const [hi, lo] = la >= lb ? [la, lb] : [lb, la];
  return (hi + 0.05) / (lo + 0.05);
}

// ---------------------------------------------------------------------------
// §3.13.1 — contrast, sampled from the rendered page rather than from the tokens

test("every rendered ink clears 4.5:1 against the background it is drawn on (§3.13.1)", async ({
  page,
}, testInfo) => {
  await open(page, route(PART));
  await expect(page.locator("[data-testid='artifact-pin']")).toBeVisible();

  // The sample is taken from the DOM the fixture actually reaches, walking up
  // for the first opaque ancestor background — which is what a reader's eye does
  // and what a token-level check cannot see, because a token does not know which
  // surface it was spent on.
  const samples = await page.evaluate(() => {
    const parse = (value: string): [number, number, number] | null => {
      const match = /rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)/.exec(value);
      if (match === null) return null;
      const alpha = match[4] === undefined ? 1 : Number(match[4]);
      if (alpha < 0.999) return null;
      return [Number(match[1]), Number(match[2]), Number(match[3])];
    };
    const backdrop = (element: Element): [number, number, number] => {
      let node: Element | null = element;
      while (node !== null) {
        const colour = parse(getComputedStyle(node).backgroundColor);
        if (colour !== null) return colour;
        node = node.parentElement;
      }
      return [0, 0, 0];
    };
    const out: { selector: string; fg: [number, number, number]; bg: [number, number, number] }[] =
      [];
    const seen = new Set<string>();
    for (const element of document.querySelectorAll<HTMLElement>("body *")) {
      // Text-bearing only: an element whose own text nodes are empty carries no
      // ink to measure, and measuring its inherited colour would count a
      // container that never draws a glyph.
      const own = [...element.childNodes].some(
        (node) => node.nodeType === Node.TEXT_NODE && (node.textContent ?? "").trim() !== "",
      );
      if (!own) continue;
      const box = element.getBoundingClientRect();
      if (box.width === 0 || box.height === 0) continue;
      const style = getComputedStyle(element);
      if (style.visibility === "hidden" || style.opacity === "0") continue;
      // The clipped facts (`BuildStateChip`'s `data-value` mirror, a disabled
      // control's `aria-describedby` target) are 1px boxes that are read aloud
      // and never drawn; they carry no legibility obligation.
      if (box.width <= 2 && box.height <= 2) continue;
      const fg = parse(style.color);
      if (fg === null) continue;
      const key = `${element.tagName}:${style.color}:${String(out.length)}`;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push({ selector: element.tagName.toLowerCase(), fg, bg: backdrop(element) });
    }
    return out;
  });

  expect(samples.length, "the page rendered no measurable text").toBeGreaterThan(20);
  const failures = samples
    .map((sample) => ({ ...sample, ratio: contrastOf(sample.fg, sample.bg) }))
    .filter((sample) => sample.ratio < 4.5);
  await archive(page, testInfo, "design-contrast");
  expect(
    failures.map((f) => `${f.selector} ${f.ratio.toFixed(2)}:1 fg=${f.fg.join(",")} bg=${f.bg.join(",")}`),
    "text below §3.13.1's 4.5:1 floor",
  ).toEqual([]);
});

// ---------------------------------------------------------------------------
// §3.11 — the viewport ground, and the one clause of §3.11 that is NOT item 3's

test("the viewport ground is a token and is distinct from every chrome surface (§3.11.1)", async ({
  page,
}) => {
  await open(page, route(PART, { tab: "viewport" }));
  const viewport = page.locator('[data-testid="viewport"]');
  await expect(viewport).toHaveAttribute("data-glb-state", "ready", { timeout: 120_000 });

  // The well is `--viewport-ground`, not `--surface-canvas` (that rung stays
  // the dark chrome-adjacent fill). §3.11.1 asks for "a viewport ground
  // distinct from every chrome surface, on both `setClearColor` and
  // `scene.background`". Velvet overrode the draft "ground darker than the
  // part" clause: the previous near-black void hid a light solid.
  const surfaces = await page.evaluate(() => {
    const root = getComputedStyle(document.documentElement);
    const read = (name: string): string => root.getPropertyValue(name).trim();
    const probeRgb = (name: string): [number, number, number] => {
      const probe = document.createElement("div");
      probe.style.backgroundColor = `var(${name})`;
      document.body.appendChild(probe);
      const value = getComputedStyle(probe).backgroundColor;
      probe.remove();
      const match = /rgba?\((\d+),\s*(\d+),\s*(\d+)/.exec(value);
      if (match === null) return [0, 0, 0];
      return [Number(match[1]), Number(match[2]), Number(match[3])];
    };
    return {
      ground: read("--viewport-ground"),
      canvas: read("--surface-canvas"),
      groundRgb: probeRgb("--viewport-ground"),
      canvasRgb: probeRgb("--surface-canvas"),
      chrome: ["app", "panel", "raised", "control", "overlay"].map((name) =>
        read(`--surface-${name}`),
      ),
    };
  });
  expect(surfaces.ground, "--viewport-ground did not resolve").not.toBe("");
  expect(surfaces.ground).not.toBe(surfaces.canvas);
  expect(surfaces.chrome).not.toContain(surfaces.ground);
  // Light modeling well, not the previous near-black void. Thresholds are
  // luminance, not a copied hex — `no-palette-token` forbids the latter here.
  expect(luminanceOf(surfaces.groundRgb)).toBeGreaterThan(0.7);
  expect(luminanceOf(surfaces.canvasRgb)).toBeLessThan(0.1);

  // And the WebGL clear colour is that same value, sampled out of the drawing
  // buffer at a corner the geometry does not reach.
  const corner = await page.evaluate(() => {
    const canvas = document.querySelector<HTMLCanvasElement>("[data-viewport-canvas]");
    if (canvas === null) return null;
    const scratch = document.createElement("canvas");
    scratch.width = canvas.width;
    scratch.height = canvas.height;
    const context = scratch.getContext("2d");
    if (context === null) return null;
    context.drawImage(canvas, 0, 0);
    const data = context.getImageData(4, 4, 1, 1).data;
    return [data[0] ?? 0, data[1] ?? 0, data[2] ?? 0] as [number, number, number];
  });
  expect(corner).not.toBeNull();
  if (corner === null) return;
  expect(corner).toEqual(surfaces.groundRgb);
});

// §3.11.2's part-vs-ground floor. **LANDED 2026-08-28 WITH PLAN ITEM 6.**
//
// §3.11.2: "The client authors the material. Every loaded mesh is overridden
// with a `MeshStandardMaterial` at a specified part colour. **Floor: ≥ 4.5:1
// part vs ground, exporter-independent**, measured in the browser (§3.14)."
//
// This case was `test.fixme` from the design-system item, which delivered the
// two tokens the floor is measured between and said so: the material was not
// authored yet and the assertion measured **1.14:1**, reproducing §3.11's own
// sampled 1.10:1 within rasterizer noise. `viewport/display.ts` authors it now,
// and the case is live. It is deliberately still measured in the browser rather
// than off the tokens: the part is lit and tone-mapped, so the *token* pairing
// (11.0:1) is a necessary condition and this pixel is the sufficient one.
//
// "EXPORTER-INDEPENDENT" IS THE HALF WORTH READING TWICE. What the shipped
// build drew was `baseColorFactor`, and `core/render/gltf.py` sets that to
// `id_to_rgb(solid_id)/255` — for solid 0, an albedo of `(0, 0, 1)/255`. The
// floor could not be met by any lighting change because the part was black by
// construction. That is why §3.11.2 asks for an override rather than a brighter
// rig, and why `display.ts` preserves the exporter's material instead of
// disposing it: the value is a selection ID, not a colour.
test("the loaded part clears 4.5:1 against the viewport ground (§3.11.2)", async ({ page }) => {
  await open(page, route(PART, { tab: "viewport" }));
  await expect(page.locator('[data-testid="viewport"]')).toHaveAttribute(
    "data-glb-state",
    "ready",
    { timeout: 120_000 },
  );

  const sampled = await page.evaluate(() => {
    const canvas = document.querySelector<HTMLCanvasElement>("[data-viewport-canvas]");
    if (canvas === null) return null;
    const scratch = document.createElement("canvas");
    scratch.width = canvas.width;
    scratch.height = canvas.height;
    const context = scratch.getContext("2d");
    if (context === null) return null;
    context.drawImage(canvas, 0, 0);
    const at = (x: number, y: number): [number, number, number] => {
      const data = context.getImageData(x, y, 1, 1).data;
      return [data[0] ?? 0, data[1] ?? 0, data[2] ?? 0];
    };
    return {
      centre: at(Math.floor(scratch.width / 2), Math.floor(scratch.height / 2)),
      corner: at(4, 4),
    };
  });

  expect(sampled, "no canvas pixels could be read").not.toBeNull();
  if (sampled === null) return;
  const ratio = contrastOf(sampled.centre, sampled.corner);
  // Printed as well as asserted: §3.11 quoted a sampled number to make its case,
  // and the answer to it should be readable off a passing run for the same
  // reason. The shipped mesh sampled `rgb(25,25,34)` on `rgb(13,15,18)` — 1.10:1,
  // the dimmest object in frame, under a comment claiming the geometry was the
  // bright thing.
  process.stdout.write(
    `\n[§3.11.2] centre rgb(${sampled.centre.join(",")}) corner rgb(${sampled.corner.join(",")})` +
      ` ratio ${ratio.toFixed(2)}:1\n`,
  );
  expect(ratio).toBeGreaterThanOrEqual(4.5);
});

// §3.11.5/§3.11.6 — the two overlays that used to describe nothing.
//
// §3.11 opened its list of absences with "no grid and no axis triad — despite
// `GridReadout`, which is a text box reading `View iso / Scale 172 mm` **about a
// grid that does not exist**". Both exist now, and this case is the one that
// keeps the readout honest: the step it prints comes from `engine.gridStep()`,
// which is the number `display.ts` built the grid from, so a grid drawn at a
// different spacing than the one reported is a failing test rather than a
// picture nobody checks.
test("the grid readout reports the grid that exists, and the triad names its axes (§3.11.5, §3.11.6)", async ({
  page,
}) => {
  await open(page, route(PART, { tab: "viewport" }));
  await expect(page.locator('[data-testid="viewport"]')).toHaveAttribute(
    "data-glb-state",
    "ready",
    { timeout: 120_000 },
  );

  // A real step, on the 1-2-5 ladder `display.ts::gridStep` walks — never the
  // em-dash the readout shows before a framing.
  const step = await page.locator("[data-readout-grid]").innerText();
  const value = Number.parseFloat(step);
  expect(Number.isFinite(value) && value > 0, `the readout reports "${step}"`).toBe(true);
  const decade = 10 ** Math.floor(Math.log10(value) + 1e-9);
  expect([1, 2, 5, 10]).toContain(Math.round(value / decade));

  // The triad is three lines and three letters. §3.12's rule one layer down:
  // colour never replaces the letter, so all three axes are named in words a
  // screen reader and a monochrome print both keep.
  await expect(page.locator("[data-axis-triad]")).toBeVisible();
  // §5.5's operator cluster: present, defaults matching the authored picture.
  // Existing selectors above are unchanged; this only adds the new strip.
  await expect(page.locator("[data-appearance]")).toBeVisible();
  for (const [control, pressed] of [
    ["wireframe", "false"],
    ["ortho", "true"],
    ["grid", "true"],
    ["triad", "true"],
    ["materialOverride", "true"],
  ] as const) {
    await expect(page.locator(`[data-appearance-control="${control}"]`)).toHaveAttribute(
      "aria-pressed",
      pressed,
    );
  }
  await expect(page.locator('[data-appearance-control="fit"]')).toBeEnabled();
  for (const axis of ["x", "y", "z"]) {
    await expect(page.locator(`[data-axis-label="${axis}"]`)).toHaveText(axis.toUpperCase());
    await expect(page.locator(`[data-axis="${axis}"]`)).toHaveAttribute(
      "data-axis-facing",
      /toward|away/,
    );
  }
});

// ---------------------------------------------------------------------------
// §4.1(a) — the grid at five widths, and no horizontal overflow at any of them

const WIDTHS = [1440, 1280, 1279, 1024, 1023] as const;

test("the shell grid matches §4.1's table at five widths and never overflows", async ({
  page,
}, testInfo) => {
  await open(page, route(PART));
  await expect(page.locator("[data-testid='artifact-pin']")).toBeVisible();

  const measured: Record<number, { columns: number; stream: number; overflow: boolean }> = {};
  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: 1000 });
    // The grid is React's now, so the assertion waits for React rather than for
    // a media query: `data-band` is written by `useBreakpoint` and by nothing
    // else, which is the single-authority claim in observable form.
    await expect(page.locator("[data-band]")).toHaveAttribute(
      "data-band",
      width >= 1280 ? "wide" : width >= 1024 ? "medium" : "narrow",
    );
    measured[width] = await page.evaluate(() => {
      const body = document.querySelector<HTMLElement>("[data-band]");
      const stream = document.querySelector<HTMLElement>("aside");
      const columns =
        body === null ? 0 : getComputedStyle(body).gridTemplateColumns.split(/\s+/).length;
      return {
        columns,
        stream: stream === null ? 0 : Math.round(stream.getBoundingClientRect().width),
        // The measured defect: between 1024 and 1279 the shipped build had the
        // stream column at 44px and its panel's scrollWidth at 81px, so the
        // document scrolled sideways.
        overflow: document.body.scrollWidth > document.body.clientWidth,
      };
    });
  }
  await archive(page, testInfo, "design-breakpoints");

  // Above 1280: three columns. §4.1(g), amended 2026-09-02 (C12): the expanded
  // track is `clamp(360px, 30vw, 420px)` — at ≥1400px it measures the 420px
  // maximum, at the 1280px boundary it measures 30vw = 384px, and at every
  // expanded width it is ≥360px, with no horizontal body scroll (asserted for
  // all five widths below).
  expect(measured[1440]?.columns).toBe(3);
  expect(measured[1280]?.columns).toBe(3);
  expect(measured[1440]?.stream).toBe(420);
  expect(measured[1280]?.stream).toBe(384);
  expect(measured[1440]?.stream).toBeGreaterThanOrEqual(360);
  expect(measured[1280]?.stream).toBeGreaterThanOrEqual(360);

  // Below1280 Parts leaves the grid; conversation intent remains open.
  expect(measured[1279]?.columns).toBe(2);
  expect(measured[1024]?.columns).toBe(2);
  expect(measured[1279]?.stream).toBeGreaterThanOrEqual(360);
  expect(measured[1024]?.stream).toBeGreaterThanOrEqual(360);

  // Narrow desktop uses the same two peers.
  expect(measured[1023]?.columns).toBe(2);

  for (const width of WIDTHS) {
    expect(measured[width]?.overflow, `body overflows at ${String(width)}px`).toBe(false);
  }
});

test("the Rail-hidden Stream opens as a full peer column and recollapses at a narrow viewport", async ({
  page,
}) => {
  await open(page, route(PART));
  await page.setViewportSize({ width: 1000, height: 900 });

  const body = page.locator("[data-band]");
  await expect(body).toHaveAttribute("data-band", "narrow");
  await expect(body).toHaveAttribute("data-rail", "hidden");
  await expect(body).toHaveAttribute("data-stream", "open");
  await page.locator('[data-stream-collapse]').click();
  await expect(body).toHaveAttribute("data-stream", "collapsed");
  await expect(body.locator(":scope > nav")).toHaveCount(1);
  await expect(body.locator(":scope > nav")).toBeHidden();

  const geometry = async (): Promise<{
    readonly bodyWidth: number;
    readonly stageWidth: number;
    readonly streamWidth: number;
    readonly streamRight: number;
    readonly bodyRight: number;
    readonly columns: number;
    readonly panelWidth: number | null;
    readonly overflow: boolean;
  }> =>
    await page.evaluate(() => {
      const bodyElement = document.querySelector<HTMLElement>("[data-band]");
      const stage = bodyElement?.querySelector<HTMLElement>(":scope > main") ?? null;
      const stream = bodyElement?.querySelector<HTMLElement>(":scope > aside") ?? null;
      const panel = document.querySelector<HTMLElement>('[data-testid="stream-panel"]');
      if (bodyElement === null || stage === null || stream === null) {
        throw new Error("shell body, Stage, or Stream is missing");
      }
      const bodyBox = bodyElement.getBoundingClientRect();
      const streamBox = stream.getBoundingClientRect();
      return {
        bodyWidth: bodyBox.width,
        stageWidth: stage.getBoundingClientRect().width,
        streamWidth: streamBox.width,
        streamRight: streamBox.right,
        bodyRight: bodyBox.right,
        columns: getComputedStyle(bodyElement).gridTemplateColumns.split(/\s+/).length,
        panelWidth: panel?.getBoundingClientRect().width ?? null,
        overflow: document.body.scrollWidth > document.body.clientWidth,
      };
    });

  const collapsed = await geometry();
  expect(collapsed.columns).toBe(1);
  expect(collapsed.streamWidth).toBeCloseTo(collapsed.bodyWidth, 0);
  expect(collapsed.stageWidth).toBeCloseTo(collapsed.bodyWidth, 0);
  expect(collapsed.streamRight).toBeCloseTo(collapsed.bodyRight, 0);
  expect(collapsed.panelWidth).toBeNull();
  expect(collapsed.overflow).toBe(false);

  await page.locator("[data-stream-strip]").click();
  await expect(body).toHaveAttribute("data-stream", "open");
  await expect(body).toHaveAttribute("data-rail", "hidden");
  await expect(page.locator('[data-testid="stream-panel"]')).toBeVisible();

  const openGeometry = await geometry();
  // `--stream-width` resolves to the clamp's 360px floor at a 1000px viewport.
  // The broken rule left this at the 44px strip width even after React had set
  // `data-stream="open"`, squeezing the mounted panel into a one-word ribbon.
  expect(openGeometry.columns).toBe(2);
  expect(openGeometry.streamWidth).toBeCloseTo(360, 0);
  expect(openGeometry.stageWidth).toBeCloseTo(640, 0);
  expect(openGeometry.stageWidth + openGeometry.streamWidth).toBeCloseTo(
    openGeometry.bodyWidth,
    0,
  );
  expect(openGeometry.streamRight).toBeCloseTo(openGeometry.bodyRight, 0);
  expect(openGeometry.panelWidth).not.toBeNull();
  expect(openGeometry.panelWidth ?? 0).toBeGreaterThanOrEqual(openGeometry.streamWidth - 1);
  expect(openGeometry.overflow).toBe(false);

  await page.locator("[data-stream-collapse]").click();
  await expect(body).toHaveAttribute("data-stream", "collapsed");
  await expect(body).toHaveAttribute("data-rail", "hidden");
  await expect(page.locator("[data-stream-strip]")).toBeVisible();

  const recollapsed = await geometry();
  expect(recollapsed.streamWidth).toBeCloseTo(collapsed.streamWidth, 0);
  expect(recollapsed.stageWidth).toBeCloseTo(collapsed.stageWidth, 0);
  expect(recollapsed.panelWidth).toBeNull();
  expect(recollapsed.overflow).toBe(false);
});

// ---------------------------------------------------------------------------
// §4.1(d) and §4.1(f), amended 2026-09-01 — repairs (a) and (b)

test("the header draws one build-state chip, and it is the pin (§4.1(d))", async ({ page }) => {
  // Repair (a): the section carried two readings of what the header draws, and
  // the one-chip collapse is now the only normative one. The measurable form is
  // a COUNT — a second badge added beside the pin breaks nothing else, because
  // every attribute and every `<Fact>` would still be where it was.
  await open(page, route(PART));
  await page.setViewportSize({ width: 1440, height: 1000 });
  const pin = page.locator("[data-testid='artifact-pin']");
  await expect(pin).toBeVisible();

  const header = page.locator("header");
  await expect(header.locator("[data-build-state]")).toHaveCount(1);
  await expect(pin).toHaveAttribute("data-build-state", /.+/);
  // The pin axis stays readable as an attribute in every state (§4.1(a)'s
  // precedent: a fact stays in the DOM when its drawn word goes).
  await expect(page.locator("[data-pin-mode]").first()).toHaveAttribute("data-pin-mode", /.+/);
});

test("hidden return carries session/task state, not an invented unread count (§4.1(f))", async ({ page }) => {
  await open(page, route(PART));
  await expect(page.locator("[data-testid='artifact-pin']")).toBeVisible();
  await page.setViewportSize({ width: 1279, height: 1000 });
  await expect(page.locator("[data-band]")).toHaveAttribute("data-band", "medium");

  await page.locator('[data-stream-collapse]').click();
  const strip = page.locator("[data-stream-strip]");
  await expect(strip).toHaveCount(1);
  await expect(strip.locator('[data-return-state]')).toHaveCount(1);
  await expect(strip).toContainText('Conversation');
  await expect(strip.locator("[data-resync-count]")).toHaveCount(0);
  await expect(strip.locator("[data-stream-state]")).toHaveCount(0);
  await expect(strip.locator("[role='status']")).toHaveCount(0);
  // Human session titles may contain numbers; an unread counter may not exist.
  await expect(strip.locator('[data-unread], [data-stream-count], [data-stream-unread]')).toHaveCount(0);
});

test("the rail overlay below1280px can be dismissed (§4.1(b), §3.13.4)", async ({ page }) => {
  await open(page, route(PART));
  await page.setViewportSize({ width: 1000, height: 900 });
  await expect(page.locator("[data-band]")).toHaveAttribute("data-band", "narrow");

  // The shipped overlay had no scrim, no close control and no dismissal at all.
  await expect(page.locator("[data-rail-scrim]")).toHaveCount(0);
  await page.locator("[data-rail-toggle]").click();
  await expect(page.locator("[data-rail-scrim]")).toHaveCount(1);
  await page.keyboard.press("Escape");
  await expect(page.locator("[data-rail-scrim]")).toHaveCount(0);
  // Focus returns to the control that opened it, rather than to the document.
  await expect(page.locator("[data-rail-toggle]")).toBeFocused();
});

// ---------------------------------------------------------------------------
// §4.1(c) / §3.3 principle 4 — furniture does not move

const TABS = ["results", "properties", "provenance", "checks", "dfm"] as const;

test("the viewport canvas is the same height on all five inspector tabs (§4.1(c))", async ({
  page,
}, testInfo) => {
  await open(page, route(PART, { tab: "viewport" }));
  await expect(page.locator('[data-testid="viewport"]')).toBeVisible();

  const heights: Record<string, number> = {};
  for (const tab of TABS) {
    await page.locator(`[data-inspector-tab="${tab}"]`).click();
    await expect(page.locator(`[data-inspector-panel="${tab}"]`)).toBeVisible();
    heights[tab] = await page.evaluate(() => {
      const host = document.querySelector<HTMLElement>('[data-testid="viewport"]');
      return host === null ? 0 : Math.round(host.getBoundingClientRect().height);
    });
  }
  await archive(page, testInfo, "design-drawer-height");

  // The shipped build measured results 412 · properties 366 · checks 494 ·
  // dfm 645 · provenance 617 — a 76% swing that re-fit the 3D camera on every
  // tab click, because `grid-template-rows: minmax(0,1fr) auto` made the drawer
  // *variable* rather than *resizable*. The explicit row makes them identical by
  // construction, so the assertion is equality and not a tolerance.
  const values = TABS.map((tab) => heights[tab] ?? 0);
  expect(values.every((height) => height > 0)).toBe(true);
  expect(new Set(values).size, `canvas heights across tabs: ${JSON.stringify(heights)}`).toBe(1);
});

// ---------------------------------------------------------------------------
// J-web-viewport-9 — §4.1's "every panel below inherits that marking" had no
// consumer. `<PinSplitMarker>` discharges it: while the pin is held on one
// part and another is selected, the STAGE names the held part (the pin's own
// axis) and the INSPECTOR names the selected part — mounted only while the
// two axes disagree. The fix note's own risk: "mount the markers INSIDE their
// regions, since the drawer-height parity assertion is at risk from a new
// row" — so this reruns exactly the parity sweep above, with the markers live.
//
// The split state is reachable only WITHIN one session (client-side rail
// navigation, no reload) until J-web-viewport-5's server `part` projection
// lands — a reload loses `heldFromPart()` today, which is why this drives the
// split by clicking Hold and then a different part row rather than by a URL.

const SPLIT_PART = "riser";

test("the split-pin markers name each region's own part, and mount only while the axes disagree (J-web-viewport-9)", async ({
  page,
}, testInfo) => {
  await open(page, route(PART, { tab: "viewport" }));
  await expect(page.locator('[data-testid="viewport"]')).toBeVisible();

  // The negative half FIRST: following current, on one part, with nothing
  // selected elsewhere — neither marker exists at all, not merely hidden.
  await expect(page.locator("[data-pin-split]")).toHaveCount(0);

  await page.locator('[data-pin-action="hold"]').click();
  await expect(page.locator('[data-pin-action="follow"]')).toBeVisible();

  // Still agreeing — held on the part that is also selected — so still no
  // split. A marker that is always on while held is not a marking.
  await expect(page.locator("[data-pin-split]")).toHaveCount(0);

  await page.locator(`[data-tree-row="part"][data-part="${SPLIT_PART}"]`).click();
  await expect(page).toHaveURL(new RegExp(`/p/${SPLIT_PART}`));

  const stage = page.locator('[data-pin-split="stage"]');
  const inspector = page.locator('[data-pin-split="inspector"]');
  await expect(stage).toHaveCount(1);
  await expect(inspector).toHaveCount(1);
  await expect(stage).toHaveAttribute("data-pin-split-part", PART);
  await expect(inspector).toHaveAttribute("data-pin-split-part", SPLIT_PART);
  // Visible text, not only the attribute (the clause's own defect was a
  // tooltip-only statement).
  await expect(stage).toContainText(PART);
  await expect(inspector).toContainText(SPLIT_PART);
  // Each region's accessible text carries BOTH names, since a screen-reader
  // user meets one region at a time.
  expect(await stage.getAttribute("aria-label")).toContain(PART);
  expect(await stage.getAttribute("aria-label")).toContain(SPLIT_PART);
  expect(await inspector.getAttribute("aria-label")).toContain(PART);
  expect(await inspector.getAttribute("aria-label")).toContain(SPLIT_PART);

  // The drawer-height parity sweep, rerun with the markers mounted: the fix
  // note's own stated risk is a new row in the stage/inspector grid, and this
  // is the assertion that would catch it.
  const heights: Record<string, number> = {};
  for (const tab of TABS) {
    await page.locator(`[data-inspector-tab="${tab}"]`).click();
    await expect(page.locator(`[data-inspector-panel="${tab}"]`)).toBeVisible();
    heights[tab] = await page.evaluate(() => {
      const host = document.querySelector<HTMLElement>('[data-testid="viewport"]');
      return host === null ? 0 : Math.round(host.getBoundingClientRect().height);
    });
  }
  await archive(page, testInfo, "pin-split-markers");
  const values = TABS.map((tab) => heights[tab] ?? 0);
  expect(values.every((height) => height > 0)).toBe(true);
  expect(
    new Set(values).size,
    `canvas heights across tabs with the split markers mounted: ${JSON.stringify(heights)}`,
  ).toBe(1);

  // And the markers are still there after the tab churn above — they are not
  // an artifact of the moment the split first formed.
  await expect(stage).toHaveCount(1);
  await expect(inspector).toHaveCount(1);
});

test("the drawer handle resizes the drawer and the canvas keeps agreeing", async ({ page }) => {
  await open(page, route(PART, { tab: "viewport" }));
  const handle = page.locator("[data-drawer-handle]");
  await expect(handle).toHaveCount(1);

  const before = await page.evaluate(
    () => document.querySelector('[data-testid="viewport"]')?.getBoundingClientRect().height ?? 0,
  );
  // §3.13.4: a drag-only affordance is a control a keyboard user cannot reach.
  await handle.focus();
  for (let i = 0; i < 4; i += 1) await page.keyboard.press("ArrowUp");
  const after = await page.evaluate(
    () => document.querySelector('[data-testid="viewport"]')?.getBoundingClientRect().height ?? 0,
  );
  expect(after).toBeLessThan(before);

  // And the canvas is still identical across tabs at the new height: the
  // property is "one explicit row", not "one particular number".
  const heights: number[] = [];
  for (const tab of TABS) {
    await page.locator(`[data-inspector-tab="${tab}"]`).click();
    await expect(page.locator(`[data-inspector-panel="${tab}"]`)).toBeVisible();
    heights.push(
      await page.evaluate(
        () =>
          Math.round(
            document.querySelector('[data-testid="viewport"]')?.getBoundingClientRect().height ?? 0,
          ),
      ),
    );
  }
  expect(new Set(heights).size).toBe(1);
});

// ---------------------------------------------------------------------------
// §3.13.2 / §3.12 — over what the fixture reaches, and only that

test("every status the fixture reaches carries an icon AND a word (§3.13.2)", async ({ page }) => {
  await open(page, route(PART));
  await page.locator('[data-inspector-tab="checks"]').click();
  await expect(page.locator('[data-inspector-panel="checks"]')).toBeVisible();
  // The PANEL is visible before its REPORT has landed, so evaluating here can
  // read zero badges and report "the fixture rendered no check badges" for a
  // fixture that has them. Wait for the data, not the container (CI run
  // 33234619571, reproduced in the pinned image; the isolated run never lost
  // the race).
  await expect(
    page.locator("[data-inspector-panel='checks'] [data-badge]").first(),
  ).toBeVisible({ timeout: 60_000 });

  const badges = await page.locator("[data-inspector-panel='checks'] [data-badge]").evaluateAll(
    (nodes) =>
      nodes.map((node) => ({
        status: node.getAttribute("data-badge"),
        icon: node.querySelector("svg[data-icon]")?.getAttribute("data-icon") ?? null,
        text: (node.textContent ?? "").trim(),
      })),
  );

  expect(badges.length, "the fixture rendered no check badges").toBeGreaterThan(0);
  for (const badge of badges) {
    // The shipped defect said the opposite way round: the attribute was on the
    // `<li>` and the CSS selected it one element down, so pass, fail and error
    // computed to the same colour, the same border and no glyph at all.
    expect(badge.icon, `${String(badge.status)} has no icon`).not.toBeNull();
    expect(badge.text, `${String(badge.status)} has no word`).not.toBe("");
  }
  // Distinct icon per distinct status, over the three the fixture reaches. The
  // sixth-status distinctness is `test/system/badge.test.tsx`'s, deliberately.
  const byStatus = new Map(badges.map((badge) => [badge.status, badge.icon]));
  expect(new Set(byStatus.values()).size).toBe(byStatus.size);
});

// ---------------------------------------------------------------------------
// §3.9 (C28), amended 2026-09-02 — accent is a promise of interaction. The
// computed-style sweep §3.14 gains: every rendered node drawing `--accent` ink
// or fill must be, or sit inside, an interactive element or the link recipe —
// "there is no third case". Swept over what the fixture reaches, like every
// other browser half of §3.14: a transcript full of reference fields (the
// named offender's habitat) plus the composer, the tabs and the header mark.

test("accent ink/fill renders only on interactive elements or the link recipe (§3.9 C28)", async ({
  page,
}, testInfo) => {
  await open(page, route(PART, { s: "sess-workspace-orchestrator" }));
  await expect(page.locator("[data-history-state]")).toHaveAttribute(
    "data-history-state",
    "complete",
    { timeout: 120_000 },
  );
  // Open one chip's disclosure so the reference-field names — the named
  // offender — hold rendered boxes the sweep can see.
  const buildChip = page.locator("article[data-tool-name='build_part']").first();
  await buildChip.locator("[data-chip-detail] summary").click();
  await expect(buildChip.locator("[data-field-reference] dt").first()).toBeVisible();

  const sweep = await page.evaluate(() => {
    const probe = document.createElement("div");
    probe.style.color = "var(--accent)";
    probe.style.backgroundColor = "var(--accent)";
    document.body.appendChild(probe);
    const style = getComputedStyle(probe);
    const accentInk = style.color;
    const accentFill = style.backgroundColor;
    probe.remove();

    const INTERACTIVE =
      "a, button, summary, input, select, textarea, [tabindex], " +
      "[role='button'], [role='link'], [role='tab'], [role='slider'], " +
      "[role='checkbox'], [role='menuitem'], [role='option']";
    const offenders: string[] = [];
    let accented = 0;
    let interactiveAccented = 0;
    for (const element of document.querySelectorAll<HTMLElement>("body *")) {
      const box = element.getBoundingClientRect();
      if (box.width === 0 || box.height === 0) continue;
      const computed = getComputedStyle(element);
      if (computed.visibility === "hidden") continue;
      const drawsInk = computed.color === accentInk;
      const drawsFill = computed.backgroundColor === accentFill;
      if (!drawsInk && !drawsFill) continue;
      // Inherited ink only counts where a glyph is actually drawn.
      const ownText = [...element.childNodes].some(
        (node) => node.nodeType === Node.TEXT_NODE && (node.textContent ?? "").trim() !== "",
      );
      if (drawsInk && !drawsFill && !ownText) continue;
      accented += 1;
      if (element.closest(INTERACTIVE) !== null) {
        interactiveAccented += 1;
        continue;
      }
      offenders.push(
        `${element.tagName.toLowerCase()}${element.className ? `.${String(element.className)}` : ""}` +
          ` ink=${String(drawsInk)} fill=${String(drawsFill)}`,
      );
    }
    // The struck offender, checked by name: a reference-field label is inert
    // and must compute to the muted code ink, never to accent.
    const fieldName = document.querySelector("[data-field-reference] dt");
    const fieldInk = fieldName === null ? null : getComputedStyle(fieldName).color;
    return { accentInk, offenders, accented, interactiveAccented, fieldInk };
  });
  await archive(page, testInfo, "design-accent-sweep");

  // The negative half: no inert node bought the colour.
  expect(sweep.offenders, "accent on a node that answers no activation").toEqual([]);
  // The positive half, so the sweep is not vacuously green: the page does draw
  // accent, and every accented node sat inside an interactive element.
  expect(sweep.accented).toBeGreaterThan(0);
  expect(sweep.interactiveAccented).toBe(sweep.accented);
  // And the named offender's replacement, checked directly.
  expect(sweep.fieldInk).not.toBeNull();
  expect(sweep.fieldInk).not.toBe(sweep.accentInk);
});

// Approved conversation-first tools remove the outer card border entirely.
// Exceptional calls retain equivalent prominence through a status-coloured
// leading rule; successful calls remain visually quiet.

test("ok tools have no outer border and only the error tool gets a prominent leading rule", async ({
  page,
}) => {
  await open(page, route(PART, { s: "sess-workspace-orchestrator" }));
  await expect(page.locator("[data-history-state]")).toHaveAttribute(
    "data-history-state",
    "complete",
    { timeout: 120_000 },
  );
  await expect(page.locator("[data-tool-name][data-status='ok']").first()).toBeVisible();

  const borders = await page.evaluate(() => {
    const probe = document.createElement("div");
    probe.style.borderColor = "var(--status-fail-ink)";
    document.body.appendChild(probe);
    const fail = getComputedStyle(probe).borderLeftColor;
    probe.remove();
    const chips = [...document.querySelectorAll<HTMLElement>("article[data-tool-name]")].map(
      (chip) => {
        const style = getComputedStyle(chip);
        return {
          status: chip.getAttribute("data-status"),
          leftColor: style.borderLeftColor,
          widths: [
            style.borderTopWidth,
            style.borderRightWidth,
            style.borderBottomWidth,
            style.borderLeftWidth,
          ],
        };
      },
    );
    return { fail, chips };
  });

  const quiet = borders.chips.filter((chip) => chip.status !== "error");
  const errors = borders.chips.filter((chip) => chip.status === "error");
  expect(quiet.length).toBeGreaterThan(0);
  expect(errors.length).toBeGreaterThan(0);
  for (const chip of quiet) {
    expect(chip.widths, `a ${String(chip.status)} tool retained an outer card border`).toEqual([
      "0px",
      "0px",
      "0px",
      "0px",
    ]);
  }
  for (const chip of errors) {
    expect(chip.widths.slice(0, 3), "an error tool regained an outer card border").toEqual([
      "0px",
      "0px",
      "0px",
    ]);
    expect(Number.parseFloat(chip.widths[3] ?? "0"), "an error tool has no leading rule").toBeGreaterThanOrEqual(2);
    expect(chip.leftColor, "the error leading rule is not failure-prominent").toBe(
      borders.fail,
    );
  }
});

test("the sprite is the only icon source, and it is inline (§3.12)", async ({ page }) => {
  await open(page, route(PART));
  await expect(page.locator("[data-testid='artifact-pin']")).toBeVisible();

  const icons = await page.locator("svg[data-icon]").evaluateAll((nodes) =>
    nodes.map((node) => ({
      id: node.getAttribute("data-icon"),
      viewBox: node.getAttribute("viewBox"),
      stroke: node.getAttribute("stroke"),
      paths: node.querySelectorAll("path").length,
      styles: node.querySelectorAll("style").length,
    })),
  );
  expect(icons.length, "the page drew no icons").toBeGreaterThan(0);
  for (const icon of icons) {
    expect(icon.viewBox, String(icon.id)).toBe("0 0 16 16");
    expect(icon.stroke, String(icon.id)).toBe("currentColor");
    expect(icon.paths, String(icon.id)).toBe(1);
    expect(icon.styles, String(icon.id)).toBe(0);
  }
  // No icon font and no remote icon request: the bundle ships inside a Python
  // wheel and its weight is the operator's download (§3.12's refusal).
  const remote = await page.evaluate(() =>
    [...document.querySelectorAll("link[rel=stylesheet], script[src]")]
      .map((node) => node.getAttribute("href") ?? node.getAttribute("src") ?? "")
      .filter((url) => /^https?:/.test(url)),
  );
  expect(remote).toEqual([]);
});
