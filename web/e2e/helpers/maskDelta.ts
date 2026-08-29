// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// G4.5's evidence, as a harness helper (INTERFACE.md §5.4).
//
// G4.5 — "visibility toggle changes the viewport within the target solid's mask
// region" — is the one pixel clause with no server-side substitute, so §5.4
// gives it a **self-referential delta over viewport pixels**, not a golden:
//
//   1. Fetch the solid-ID pass PNG for the pinned build from
//      `/artifacts/{ref}/bytes` and decode it test-side to a mask `M` for the
//      target solid's palette value. "The mask is never decoded from the
//      viewport, which is lit and antialiased, and the workspace itself never
//      displays a pass."
//   2. Screenshot the viewport **before** and **after** the toggle, in the
//      pinned CI image, at the pass's own resolution and camera.
//   3. "Assert on two regions: inside `M`, the fraction of changed pixels is
//      **≥ 0.10**; inside a **control region** outside `M` (its complement,
//      minus a two-pixel dilation band around `M`'s boundary to absorb
//      antialiasing), the fraction of changed pixels is **≤ 0.01**. The dilation
//      band is excluded from both, not silently attributed to one."
//
// "**This is a delta assertion between two frames from the same rasterizer, not
// a pinned-rasterizer golden.** Nothing is compared against a stored image, no
// reference pixels are committed, and no `(container image, renderer version)`
// pair is pinned for browser output — so it creates **no browser-golden
// determinism family**, and §5.3's refusal stands untouched."
//
// ── THE ONE READING THIS FILE HAD TO CHOOSE ─────────────────────────────────
// "its complement, minus a two-pixel dilation band around `M`'s boundary" and
// "The dilation band is excluded from **both**" are only jointly satisfiable if
// the band **straddles** the boundary — an outer-only band is already outside
// `M` and could not be excluded from `M` as well. So the band here is
//
//     band = dilate(M, r) \ erode(M, r)
//
// and the three regions partition the frame exactly:
//
//     inside  = erode(M, r)              the mask, minus its own boundary band
//     band    = dilate(M, r) \ erode(M, r)   excluded from both assertions
//     control = complement(dilate(M, r))     the complement, minus the band
//
// This is the conservative reading: it removes antialiasing from the numerator
// of the ≤ 0.01 assertion *and* from the denominator of the ≥ 0.10 one, so
// neither threshold is met by boundary noise. `dilation: 0` recovers the literal
// two-region split for a caller that wants it.
//
// ── AND THE ONE THRESHOLD DEFAULT ───────────────────────────────────────────
// "changed" is **exact byte inequality** by default. §5.3 has just refused to
// make any claim about this rasterizer's output, and a per-channel tolerance
// would be such a claim smuggled into a helper. Two frames from one browser in
// one run are bit-identical where nothing changed; if they are not, that is a
// finding, not a nuisance to be tuned away. `tolerance` exists for a caller that
// has a stated reason and must pass one explicitly.

import { decodePng, type DecodedPng } from "./png";

/** An 8-bit palette colour, as `id_to_rgb` publishes it in the mask legend. */
export type Rgb = readonly [number, number, number];

/** One byte per pixel: 1 inside the region, 0 outside. */
export type Region = Uint8Array;

// ── THE THRESHOLD DERIVATION, 2026-08-28 (plan item 6, §3.11, §21.10) ───────
//
// §21.10 recorded that these two numbers were **chosen rather than measured**,
// and §3.11 made re-deriving them a precondition on viewport display
// authorship: they "must be re-derived against the new material **before that
// work lands**, not loosened after it". Item 6 landed the material, the edge
// pass, the ground grid and the axis triad. This is the derivation, recorded
// where the constants are so it cannot drift away from them.
//
// MEASURED, at 960×720 over every toggleable entry in the public fixture, by
// `viewport.spec.ts`'s "the G4.5 thresholds hold for EVERY solid" case. The
// `before` row is the tread entry alone, because measuring one entry is all the
// pre-item-6 suite did — which is itself part of why this derivation measures
// all of them:
//
//   entry         mask px    inside    control    band (excluded)
//   ─────────────────────────────────────────────────────────────
//   tread  BEFORE  142025    1.0000    0.0000     0.5578
//   tread  AFTER   142025    1.0000    0.0000     0.6527
//   cleat_left      7957     1.0000    0.0000     0.6439
//   cleat_right     7957     1.0000    0.0000     0.6439
//                            ≥ 0.10    ≤ 0.01     no threshold
//
// The two cleats are an 18× smaller region than the tread and land on the same
// two numbers, which is the part a single-solid measurement could not have told
// anyone: the floor is not a property of a large silhouette.
//
// RESULT: **both thresholds are unchanged**, and neither was loosened.
//
//   * `INSIDE_CHANGED_MIN` stays 0.10 against a measurement of 1.0000. The
//     margin is 10×, and it is structural rather than lucky: the mask IS the
//     target solid's silhouette, so hiding the solid replaces every pixel in it.
//     Raising the floor toward the measurement would convert a question about
//     *where* the change is into a claim about this rasterizer's exact output,
//     which is the claim §5.3 has just refused to make and §5.4 restates ("The
//     thresholds are loose on purpose").
//   * `CONTROL_CHANGED_MAX` stays 0.01 against a measurement of 0.0000 — exact
//     byte equality outside the mask. Everything item 6 draws outside the
//     silhouette is static under a visibility toggle (the grid is rebuilt only
//     on a re-framing; the triad moves only with the camera; the readout's grid
//     row is fixed-width), and the authored silhouette itself falls inside the
//     two-pixel dilation band, which is excluded from both assertions by
//     construction. That is where the change went: the band rose from 0.5578 to
//     0.6527 because a bright edge now sits where a black one did.
//
// This is a *record*, not a licence. A future measurement that fails these
// numbers is evidence that something moved pixels outside the toggled solid.
// §5.4 states 0.10 and 0.01 normatively; this file may report against them and
// may never quietly edit them.

/** §5.4's two thresholds and its band width, as the constants they are. */
export const INSIDE_CHANGED_MIN = 0.1;
export const CONTROL_CHANGED_MAX = 0.01;
export const DILATION_RADIUS = 2;

/** A comparison the helper refused to make, naming which assumption broke. */
export class MaskDeltaError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "MaskDeltaError";
  }
}

export interface Frame {
  readonly width: number;
  readonly height: number;
}

function requireSameSize(a: Frame, b: Frame, what: string): void {
  if (a.width !== b.width || a.height !== b.height) {
    throw new MaskDeltaError(
      `${what}: ${a.width}×${a.height} and ${b.width}×${b.height} differ. §5.4 requires the ` +
        "screenshots be taken at the pass's own resolution and camera; comparing across a " +
        "rescale would compare a resampler, not a toggle.",
    );
  }
}

/**
 * The mask `M` for one or more palette values in a decoded **pass** PNG.
 *
 * Several values because a Results row can cover more than one solid: the
 * toggle's namespace is the geometry-entry label (`state/visibility.ts`), so the
 * region a group toggle changes is the union of its solids' palette values. The
 * caller supplies them from the inspection's own `mask_legend` — a server value,
 * read by the harness, never derived here.
 *
 * Alpha is ignored: the passes are opaque and `id_to_rgb` addresses three
 * channels. An RGBA pass matches on its first three.
 */
export function maskForPalette(pass: DecodedPng, values: readonly Rgb[]): Region {
  if (values.length === 0) {
    throw new MaskDeltaError("a mask needs at least one palette value to match");
  }
  const { width, height, channels, data } = pass;
  const mask = new Uint8Array(width * height);
  for (let pixel = 0; pixel < mask.length; pixel += 1) {
    const at = pixel * channels;
    const r = data[at] as number;
    const g = data[at + 1] as number;
    const b = data[at + 2] as number;
    for (const value of values) {
      if (r === value[0] && g === value[1] && b === value[2]) {
        mask[pixel] = 1;
        break;
      }
    }
  }
  return mask;
}

/** How many pixels a region holds. */
export function regionSize(region: Region): number {
  let count = 0;
  for (const value of region) if (value !== 0) count += 1;
  return count;
}

/**
 * Chebyshev dilation by `radius` — a `(2r+1)²` square structuring element.
 *
 * Square rather than a disc because the thing being absorbed is one- to
 * two-pixel antialiasing along an edge of arbitrary orientation, and a square is
 * the shape that covers a diagonal edge's fringe at the stated radius. Separable
 * (rows then columns), so the cost is linear in pixels rather than in `r²`.
 */
export function dilate(mask: Region, frame: Frame, radius: number): Region {
  if (radius <= 0) return Uint8Array.from(mask);
  const { width, height } = frame;
  const rows = new Uint8Array(mask.length);
  for (let y = 0; y < height; y += 1) {
    const row = y * width;
    for (let x = 0; x < width; x += 1) {
      let hit = 0;
      const from = Math.max(0, x - radius);
      const to = Math.min(width - 1, x + radius);
      for (let k = from; k <= to && hit === 0; k += 1) hit = mask[row + k] as number;
      rows[row + x] = hit === 0 ? 0 : 1;
    }
  }
  const out = new Uint8Array(mask.length);
  for (let x = 0; x < width; x += 1) {
    for (let y = 0; y < height; y += 1) {
      let hit = 0;
      const from = Math.max(0, y - radius);
      const to = Math.min(height - 1, y + radius);
      for (let k = from; k <= to && hit === 0; k += 1) hit = rows[k * width + x] as number;
      out[y * width + x] = hit === 0 ? 0 : 1;
    }
  }
  return out;
}

/** How many pixels a frame holds. */
function pixelCount(frame: Frame): number {
  return frame.width * frame.height;
}

/** Erosion is dilation of the complement, complemented. */
export function erode(mask: Region, frame: Frame, radius: number): Region {
  if (radius <= 0) return Uint8Array.from(mask);
  const inverted = new Uint8Array(mask.length);
  for (let i = 0; i < mask.length; i += 1) inverted[i] = mask[i] === 0 ? 1 : 0;
  const grown = dilate(inverted, frame, radius);
  const out = new Uint8Array(mask.length);
  for (let i = 0; i < mask.length; i += 1) out[i] = grown[i] === 0 ? 1 : 0;
  return out;
}

/** §5.4's three regions. Disjoint, and together they cover every pixel. */
export interface Regions {
  readonly inside: Region;
  readonly band: Region;
  readonly control: Region;
}

export function regions(mask: Region, frame: Frame, radius = DILATION_RADIUS): Regions {
  if (mask.length !== pixelCount(frame)) {
    throw new MaskDeltaError(
      `mask holds ${mask.length} pixels but the frame is ${frame.width}×${frame.height}`,
    );
  }
  const grown = dilate(mask, frame, radius);
  const shrunk = erode(mask, frame, radius);
  const inside = new Uint8Array(mask.length);
  const band = new Uint8Array(mask.length);
  const control = new Uint8Array(mask.length);
  for (let i = 0; i < mask.length; i += 1) {
    if (shrunk[i] !== 0) inside[i] = 1;
    else if (grown[i] !== 0) band[i] = 1;
    else control[i] = 1;
  }
  return { inside, band, control };
}

/**
 * Which pixels differ between two frames.
 *
 * `tolerance` is the maximum per-channel absolute difference still counted as
 * unchanged; it defaults to 0 — exact — for the reason in the header.
 */
export function changedPixels(before: DecodedPng, after: DecodedPng, tolerance = 0): Region {
  requireSameSize(before, after, "the before and after frames");
  if (before.channels !== after.channels) {
    throw new MaskDeltaError(
      `frames have ${before.channels} and ${after.channels} channels; the same source produces one`,
    );
  }
  const channels = before.channels;
  const count = before.width * before.height;
  const out = new Uint8Array(count);
  for (let pixel = 0; pixel < count; pixel += 1) {
    const at = pixel * channels;
    for (let c = 0; c < channels; c += 1) {
      const delta = Math.abs((before.data[at + c] as number) - (after.data[at + c] as number));
      if (delta > tolerance) {
        out[pixel] = 1;
        break;
      }
    }
  }
  return out;
}

/** The fraction of `region`'s pixels that `changed` marks. `0` for an empty region. */
export function changedFraction(changed: Region, region: Region): number {
  let total = 0;
  let hits = 0;
  for (let i = 0; i < region.length; i += 1) {
    if (region[i] === 0) continue;
    total += 1;
    if (changed[i] !== 0) hits += 1;
  }
  return total === 0 ? 0 : hits / total;
}

export interface VisibilityDeltaInput {
  /** The viewport screenshot before the toggle. */
  readonly before: Uint8Array;
  /** The viewport screenshot after it. */
  readonly after: Uint8Array;
  /** The **solid-ID pass** bytes from `/artifacts/{ref}/bytes`. Never a preview. */
  readonly pass: Uint8Array;
  /** The target solid's palette value(s), from the inspection's `mask_legend`. */
  readonly palette: readonly Rgb[];
  readonly dilation?: number;
  readonly tolerance?: number;
}

/** Everything the assertion decided on, so a failure can print all of it. */
export interface VisibilityDelta {
  readonly width: number;
  readonly height: number;
  readonly maskPixels: number;
  readonly insidePixels: number;
  readonly bandPixels: number;
  readonly controlPixels: number;
  readonly insideChanged: number;
  readonly controlChanged: number;
  /** Reported, never asserted on: the band is excluded from both thresholds. */
  readonly bandChanged: number;
}

/**
 * Run §5.4's three steps over already-fetched bytes and return the measurements.
 *
 * The helper does no fetching and drives no browser: the e2e owns the page, the
 * artifact route, and the legend, because those are the parts that need a
 * fixture. What is here is the part that must be identical every time it is
 * asserted.
 */
export function visibilityDelta(input: VisibilityDeltaInput): VisibilityDelta {
  const before = decodePng(input.before);
  const after = decodePng(input.after);
  const pass = decodePng(input.pass);
  requireSameSize(pass, before, "the solid-ID pass and the viewport screenshot");

  const mask = maskForPalette(pass, input.palette);
  const maskPixels = regionSize(mask);
  if (maskPixels === 0) {
    throw new MaskDeltaError(
      "the target solid's palette value does not occur in the pass, so there is no region to " +
        "assert in. Check the legend entry and the pinned artifact ref before relaxing anything.",
    );
  }

  const split = regions(mask, pass, input.dilation ?? DILATION_RADIUS);
  const changed = changedPixels(before, after, input.tolerance ?? 0);
  return {
    width: pass.width,
    height: pass.height,
    maskPixels,
    insidePixels: regionSize(split.inside),
    bandPixels: regionSize(split.band),
    controlPixels: regionSize(split.control),
    insideChanged: changedFraction(changed, split.inside),
    controlChanged: changedFraction(changed, split.control),
    bandChanged: changedFraction(changed, split.band),
  };
}

/**
 * §5.4's assertion, thresholds included. Throws with every number on failure.
 *
 * "The thresholds are loose on purpose: the clause asks whether the toggle
 * changed the right region, which is a question about *where* the change is, and
 * a tight threshold would be a claim about the renderer's output that this spec
 * has just refused to make." They are therefore **not** parameters.
 */
export function assertVisibilityDelta(input: VisibilityDeltaInput): VisibilityDelta {
  const result = visibilityDelta(input);
  const failures: string[] = [];
  if (!(result.insideChanged >= INSIDE_CHANGED_MIN)) {
    failures.push(
      `inside the mask only ${(result.insideChanged * 100).toFixed(2)}% of ` +
        `${result.insidePixels} pixels changed (need ≥ ${INSIDE_CHANGED_MIN * 100}%)`,
    );
  }
  if (!(result.controlChanged <= CONTROL_CHANGED_MAX)) {
    failures.push(
      `in the control region ${(result.controlChanged * 100).toFixed(2)}% of ` +
        `${result.controlPixels} pixels changed (need ≤ ${CONTROL_CHANGED_MAX * 100}%)`,
    );
  }
  if (failures.length > 0) {
    throw new MaskDeltaError(
      `visibility delta (INTERFACE.md §5.4, G4.5) failed: ${failures.join("; ")}. ` +
        `frame ${result.width}×${result.height}, mask ${result.maskPixels}px, ` +
        `band ${result.bandPixels}px changed ${(result.bandChanged * 100).toFixed(2)}% ` +
        "(excluded from both assertions).",
    );
  }
  return result;
}
