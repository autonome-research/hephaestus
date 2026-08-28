// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The G4.5 pixel-assertion machinery (INTERFACE.md §5.4).
//
// This suite exists because the helper is *the* evidence for the one gate clause
// with no server-side substitute. If the region split is wrong, G4.5 passes or
// fails for reasons unrelated to the toggle, and nothing downstream would say
// so. So the properties asserted here are the ones §5.4 states in words:
//
//   * the mask is decoded from the **pass**, by palette value, never from a
//     shaded frame;
//   * `inside`, `band`, and `control` **partition** the frame — every pixel in
//     exactly one, which is what "excluded from both, not silently attributed to
//     one" means operationally;
//   * a real toggle passes; a change in the wrong place fails on the control
//     region; a change too small inside the mask fails on the inside region;
//   * antialiasing along the boundary lands in the band and therefore decides
//     nothing.

import { describe, expect, it } from "vitest";
import {
  assertVisibilityDelta,
  changedFraction,
  changedPixels,
  CONTROL_CHANGED_MAX,
  dilate,
  erode,
  INSIDE_CHANGED_MIN,
  MaskDeltaError,
  maskForPalette,
  regions,
  regionSize,
  visibilityDelta,
  type Rgb,
} from "../e2e/helpers/maskDelta";
import { decodePng } from "../e2e/helpers/png";
import { encodePng, paintRect, solidFrame } from "./png";

const WIDTH = 40;
const HEIGHT = 30;
const FRAME = { width: WIDTH, height: HEIGHT };

/** The target solid's palette value, as a legend would give it. */
const TARGET: Rgb = [12, 200, 45];
/** Another solid's, so the mask is a match and not "anything non-background". */
const OTHER: Rgb = [200, 12, 45];
const PASS_BACKGROUND: Rgb = [0, 0, 0];

/** A solid-ID pass: one rectangle per solid, exact palette values, no AA. */
function passPng(): Uint8Array {
  const data = solidFrame(WIDTH, HEIGHT, PASS_BACKGROUND, 3);
  paintRect(data, { width: WIDTH, channels: 3 }, { x: 6, y: 6, w: 12, h: 12 }, TARGET);
  paintRect(data, { width: WIDTH, channels: 3 }, { x: 24, y: 6, w: 10, h: 12 }, OTHER);
  return encodePng({ width: WIDTH, height: HEIGHT, channels: 3, data });
}

/** A lit viewport frame: nothing is a palette value, which is the point. */
function viewportPng(paint: (data: Uint8Array) => void): Uint8Array {
  const data = solidFrame(WIDTH, HEIGHT, [13, 15, 18], 4);
  paint(data);
  return encodePng({ width: WIDTH, height: HEIGHT, channels: 4, data });
}

const rect = (data: Uint8Array, x: number, y: number, w: number, h: number, c: Rgb): void => {
  paintRect(data, { width: WIDTH, channels: 4 }, { x, y, w, h }, c);
};

describe("maskForPalette", () => {
  it("selects exactly the target solid's pixels, not every non-background one", () => {
    const pass = decodePng(passPng());
    const mask = maskForPalette(pass, [TARGET]);
    expect(regionSize(mask)).toBe(12 * 12);
    expect(mask[6 * WIDTH + 6]).toBe(1);
    expect(mask[6 * WIDTH + 24]).toBe(0); // the other solid
    expect(mask[0]).toBe(0); // background
  });

  it("unions several palette values, for a row that covers a group of solids", () => {
    const pass = decodePng(passPng());
    expect(regionSize(maskForPalette(pass, [TARGET, OTHER]))).toBe(12 * 12 + 10 * 12);
  });

  it("refuses an empty palette list rather than matching nothing", () => {
    expect(() => maskForPalette(decodePng(passPng()), [])).toThrow(MaskDeltaError);
  });
});

describe("dilate / erode", () => {
  it("grows and shrinks by the Chebyshev radius", () => {
    const mask = new Uint8Array(WIDTH * HEIGHT);
    paintSquare(mask, 10, 10, 6);
    expect(regionSize(mask)).toBe(36);
    expect(regionSize(dilate(mask, FRAME, 2))).toBe(10 * 10);
    expect(regionSize(erode(mask, FRAME, 2))).toBe(2 * 2);
  });

  it("is the identity at radius 0, so the literal two-region split is reachable", () => {
    const mask = new Uint8Array(WIDTH * HEIGHT);
    paintSquare(mask, 4, 4, 5);
    expect([...dilate(mask, FRAME, 0)]).toEqual([...mask]);
    expect([...erode(mask, FRAME, 0)]).toEqual([...mask]);
  });
});

describe("regions", () => {
  it("partitions the frame: every pixel in exactly one of the three", () => {
    const mask = maskForPalette(decodePng(passPng()), [TARGET]);
    const split = regions(mask, FRAME, 2);
    for (let i = 0; i < WIDTH * HEIGHT; i += 1) {
      const membership =
        (split.inside[i] as number) + (split.band[i] as number) + (split.control[i] as number);
      expect(membership).toBe(1);
    }
    expect(
      regionSize(split.inside) + regionSize(split.band) + regionSize(split.control),
    ).toBe(WIDTH * HEIGHT);
  });

  it("straddles the boundary — the band is inside AND outside the mask", () => {
    const mask = maskForPalette(decodePng(passPng()), [TARGET]);
    const split = regions(mask, FRAME, 2);
    // 12×12 mask: inside is the 8×8 core, band is the 16×16 dilation minus that.
    expect(regionSize(split.inside)).toBe(8 * 8);
    expect(regionSize(split.band)).toBe(16 * 16 - 8 * 8);
    // A pixel just inside the mask's edge belongs to the band, not to `inside`:
    // that is the half an outer-only band would have silently attributed.
    expect(split.inside[6 * WIDTH + 6]).toBe(0);
    expect(split.band[6 * WIDTH + 6]).toBe(1);
  });

  it("refuses a mask whose size does not match the frame", () => {
    expect(() => regions(new Uint8Array(9), FRAME, 2)).toThrow(MaskDeltaError);
  });
});

describe("changedPixels", () => {
  it("counts exact byte inequality by default", () => {
    const before = decodePng(viewportPng(() => undefined));
    const after = decodePng(viewportPng((data) => rect(data, 0, 0, 2, 1, [14, 15, 18])));
    const changed = changedPixels(before, after);
    expect(regionSize(changed)).toBe(2);
  });

  it("honours an explicit tolerance, which a caller must ask for", () => {
    const before = decodePng(viewportPng(() => undefined));
    const after = decodePng(viewportPng((data) => rect(data, 0, 0, 2, 1, [14, 15, 18])));
    expect(regionSize(changedPixels(before, after, 1))).toBe(0);
  });

  it("refuses frames of different sizes rather than comparing a resampler", () => {
    const before = decodePng(viewportPng(() => undefined));
    const small = decodePng(
      encodePng({ width: 4, height: 4, channels: 4, data: solidFrame(4, 4, [0, 0, 0], 4) }),
    );
    expect(() => changedPixels(before, small)).toThrow(MaskDeltaError);
  });
});

describe("visibilityDelta / assertVisibilityDelta (G4.5)", () => {
  const pass = passPng();

  /** The frame before the toggle: both solids drawn in lit, non-palette colours. */
  const bothVisible = viewportPng((data) => {
    rect(data, 6, 6, 12, 12, [180, 190, 200]);
    rect(data, 24, 6, 10, 12, [120, 130, 140]);
  });
  /** After hiding the target: its region goes to ground, the other is untouched. */
  const hidTheTarget = viewportPng((data) => {
    rect(data, 24, 6, 10, 12, [120, 130, 140]);
  });

  it("passes when the toggle changed the target's region and nothing else", () => {
    const result = assertVisibilityDelta({
      before: bothVisible,
      after: hidTheTarget,
      pass,
      palette: [TARGET],
    });
    expect(result.insideChanged).toBe(1);
    expect(result.controlChanged).toBe(0);
    expect(result.width).toBe(WIDTH);
  });

  it("fails on the control region when the wrong solid changed", () => {
    // The *other* solid was hidden instead: the mask region is untouched and the
    // control region is where everything happened.
    const hidTheOther = viewportPng((data) => {
      rect(data, 6, 6, 12, 12, [180, 190, 200]);
    });
    expect(() =>
      assertVisibilityDelta({ before: bothVisible, after: hidTheOther, pass, palette: [TARGET] }),
    ).toThrow(/control region/);
  });

  it("fails inside the mask when almost nothing in it changed", () => {
    const barelyChanged = viewportPng((data) => {
      rect(data, 6, 6, 12, 12, [180, 190, 200]);
      rect(data, 24, 6, 10, 12, [120, 130, 140]);
      rect(data, 10, 10, 1, 1, [0, 0, 0]);
    });
    expect(() =>
      assertVisibilityDelta({ before: bothVisible, after: barelyChanged, pass, palette: [TARGET] }),
    ).toThrow(/inside the mask/);
  });

  it("lets boundary antialiasing decide nothing: it lands in the excluded band", () => {
    // A one-pixel fringe just outside the mask, as an antialiased edge produces.
    const fringed = viewportPng((data) => {
      rect(data, 6, 6, 12, 12, [180, 190, 200]);
      rect(data, 24, 6, 10, 12, [120, 130, 140]);
      rect(data, 5, 5, 14, 1, [90, 95, 100]);
      rect(data, 5, 18, 14, 1, [90, 95, 100]);
    });
    const measured = visibilityDelta({
      before: bothVisible,
      after: fringed,
      pass,
      palette: [TARGET],
    });
    expect(measured.controlChanged).toBe(0);
    expect(measured.bandChanged).toBeGreaterThan(0);
  });

  it("refuses when the palette value does not occur in the pass", () => {
    expect(() =>
      visibilityDelta({ before: bothVisible, after: hidTheTarget, pass, palette: [[1, 1, 1]] }),
    ).toThrow(/does not occur in the pass/);
  });

  it("refuses when the screenshot is not at the pass's resolution", () => {
    const rescaled = encodePng({
      width: 20,
      height: 15,
      channels: 4,
      data: solidFrame(20, 15, [13, 15, 18], 4),
    });
    expect(() =>
      visibilityDelta({ before: rescaled, after: rescaled, pass, palette: [TARGET] }),
    ).toThrow(/resolution and camera/);
  });

  it("pins §5.4's thresholds as constants, not as parameters", () => {
    expect(INSIDE_CHANGED_MIN).toBe(0.1);
    expect(CONTROL_CHANGED_MAX).toBe(0.01);
  });
});

describe("changedFraction", () => {
  it("is 0 for an empty region rather than NaN", () => {
    expect(changedFraction(new Uint8Array(4), new Uint8Array(4))).toBe(0);
  });
});

function paintSquare(mask: Uint8Array, x0: number, y0: number, size: number): void {
  for (let y = y0; y < y0 + size; y += 1) {
    for (let x = x0; x < x0 + size; x += 1) mask[y * WIDTH + x] = 1;
  }
}
